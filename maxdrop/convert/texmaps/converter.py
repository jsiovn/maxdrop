# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""TexmapConverter: a texmap of the scene converted into a texture graph."""
import contextlib
import dataclasses
import math

from ...reader import classids, units
from ...reader import materials as reader_materials
from ...reader import scene as reader_scene
from ...reader.classdir import ClassId
from .. import colors, params
from ..params import finite as _finite
from .ids import (
    _IMAGE_FILES, BM_APPLY, BM_CLIP_H, BM_CLIP_U, BM_CLIP_V, BM_CLIP_W, BM_CROP_PLACE, BM_FILE, BM_MONO, BM_RGB, BUMP,
    CB_BLUR, CB_CHANNEL, CB_CLIP_H, CB_CLIP_MODE, CB_CLIP_ON, CB_CLIP_U, CB_CLIP_V, CB_CLIP_W, CB_GAMMA, CB_MIRROR,
    CB_MONO, CB_NO_TILE, CB_OFFSET, CB_REAL_WORLD, CB_RGB, CB_SCALE, CB_TILE_U, CB_TILE_V, CB_W_ANGLE, ChunkError,
    COLOR, CORONA_ADD_GAMMA, CORONA_NORMAL, DEFAULT_METERS, DISPLAY_MIXES, EXPLICIT, FLOAT_IMAGES, FLOATS, IMAGES,
    MASK, MASK_MIXES, MAX_DEPTH, MAX_MULTIPLIER, MAX_NODES, NON_COLOR, NORMAL, NORMAL_BUMP, NORMAL_BUMP_METHOD,
    NORMAL_MAPS, OBJECT_XYZ,
    OUT_AMOUNT, OUT_LEVEL, OUT_OFFSET, SRGB_GAMMA, STORED, STORED_RGB, UV_BLUR, UV_U_ANGLE, UV_U_OFFSET, UV_U_TILING,
    UV_V_ANGLE, UV_V_OFFSET, UV_V_TILING, UV_W_ANGLE, VB_ACESCG, VB_AUTOMATIC, VB_COLOR_SPACE, VB_CROP_H, VB_CROP_MODE,
    VB_CROP_ON, VB_CROP_U, VB_CROP_V, VB_CROP_W, VB_FROM_MAX, VB_GAMMA, VB_INTENSITY, VB_INVERSE_GAMMA, VB_LINEAR,
    VB_MAP_TYPE, VB_MONO, VB_MULT, VB_RENDER_MULT, VB_RGB, VB_RGB_SPACE, VB_RGB_SPACE_BLOCK, VB_SOURCE, VB_SOURCE_ON,
    VB_SRGB, VB_STANDARD, VERTEX_COLOR, VRAY_DIRT, WORLD_XYZ,
)
from .ir import (
    _has_decode, _Walk, Bump, Constant, Crop, Decode, first_image, Image, Invert, Mapping, Mix, Multiply, NormalMap,
    TexmapStats, TexOutput, TextureGraphIR, tree_size,
)
from .values import (
    _auto_gamma, _constant_value, _flag, _num, _ref, _shown, _stored_mask, _stored_value, _vec, base_kind, colorspace,
)
from .maps import _black_white, CORONA_RENDERER, WHITE
from .dispatch import _KEEP, _PEEL


class TexmapConverter:
    """Converts the maps of one MaterialGraph; assets: the scene's reader.assets.AssetTable (None: no file is
    known); textures: a convert.textures.TextureIndex to look each file up (None: no lookup); swatches: the
    colors.Swatches rule of the scene (None: read from graph's scene); renderer: the scene's renderer ClassID
    (reader.metadata's renderer class_id; None: not known), for the rules a renderer changes (corona); meters: per
    file unit, as the geometry is scaled (a 3D map's size and offset; None: the file's own unit, DEFAULT_METERS when
    it says none)."""

    def __init__(self, graph, assets=None, textures=None, swatches=None, renderer=None, meters=None):
        self.graph, self.assets, self.textures = params.at_frame_zero(graph, self._heard), assets, textures
        self.meters = meters if meters is not None else _scene_meters(graph)
        self.swatches = swatches if swatches is not None else colors.of_graph(graph)
        self.corona = renderer is not None and tuple(renderer) == CORONA_RENDERER
        self.stats = TexmapStats()
        self._counted, self._done, self._reported = set(), {}, set()
        self._nodes, self._firsts = {}, {}  # keyed (object, kind, depth)
        self._walks = []  # the walks being filled, innermost last: where a controller's line goes

    def _heard(self, index, line):
        """A line of a parameter read through its controller (params.frame_zero): the innermost walk's issue, which
        it marks approximated (the value is one, or the default); stats only outside a walk."""
        if self._walks:
            self._walks[-1].approximated = True
            self._issue(self._walks[-1], index, line)
        else:
            self.note(index, line)

    @contextlib.contextmanager
    def _into(self, walk):
        """with self._into(walk): walk is the innermost one, where a controller's line goes."""
        self._walks.append(walk)
        try:
            yield
        finally:
            self._walks.pop()

    def _old(self, part, index, default, m, what):
        """A float of a part's old ParamBlock (params.old_value: a controller's at frame 0 too), default when it has
        none; a line goes under map m, what naming the part."""
        heard = params.hearing(self._heard, m.index, "%r %s" % (m.name, what))
        v = params.old_value(self.graph.scene, part, index, heard, number=True)
        return float(v) if _finite(v) else default

    def _old_vec(self, part, index, default, m, what):
        """A Point3 of a part's old ParamBlock (params.old_value), default when it holds no three finite numbers."""
        heard = params.hearing(self._heard, m.index, "%r %s" % (m.name, what))
        v = params.old_value(self.graph.scene, part, index, heard)
        ok = isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3])
        return tuple(float(c) for c in v[:3]) if ok else default

    def _issue(self, walk, index, reason):
        self.note(index, reason)
        if reason not in walk.issues:
            walk.issues.append(reason)

    def note(self, index, reason):
        """An issue of map object index in stats.issues, once."""
        if (index, reason) not in self._reported:
            self._reported.add((index, reason))
            self.stats.issues.append((index, reason))

    def _class_name(self, m):
        entry = self.graph.scene.entry(m.index)  # m came from graph.get: an object of the scene
        return (entry.name if entry is not None else "") or classids.name_of(m.superclass, m.class_id) or \
            "ClassID%s" % (ClassId(*m.class_id),)

    def _count(self, counter, m):
        if m.index not in self._counted:
            self._counted.add(m.index)
            counter[self._class_name(m)] += 1

    def convert(self, ref, kind, value=None):
        """The TextureGraphIR of a materials.MapRef in an input of that kind whose own value is value; None when no
        usable map drives it."""
        key = (ref, kind, value)
        if key in self._done:
            return self._done[key]
        walk = _Walk()
        # a gamma-off color input mixed with its own value by an amount below 1: V-Ray mixes the stored values and the
        # display-referred scene shows the result decoded (maxdrop-6n0.6.18), as a Mix at a color root; a scale (a
        # Standard's Diffuse Level other than 1 on its diffuse map, a Fresnel-off VRayMtl's metalness, linear) keeps
        # the decoded mix (not measured with an
        # amount; _leveled's diffuse at level 1 takes the stored one); an amount of 0 is the value alone, exact
        stored = (kind == COLOR and not self.swatches.linear and 0.0 < ref.amount < 1.0 and value is not None
                  and ref.scale == 1.0)
        root = self._node(ref.index, STORED if stored else kind, walk, 0, ())
        out = None
        if root is not None:
            if stored:
                root = self._decoded(self._slot(root, ref, STORED, _stored_value(value), walk), walk, 0, ())
            else:
                root = self._slot(root, ref, kind, value, walk)
            if tree_size(root) > MAX_NODES:
                image = first_image(root)
                if image is not None and _has_decode(root):  # it may be in STORED: its map again as a color
                    image = self._node(image.index, kind, walk, 0, ()) or image
                self._issue(walk, ref.index, "map %d: graph of more than %d nodes cut down to its first image"
                            % (ref.index, MAX_NODES))
                walk.approximated = True
                root = self._slot(image, ref, kind, value, walk) if image is not None else None
            if root is not None:
                out = TextureGraphIR(root, kind, walk.approximated, tuple(walk.issues))
        self._done[key] = out
        return out

    def _slot(self, root, ref, kind, value, walk):
        amount = ref.amount
        if ref.invert:
            root = Invert(root)
        if kind == BUMP:
            if isinstance(root, NormalMap):
                return _scaled(root, amount)
            if isinstance(root, Bump):
                return Bump(root.input, root.strength * amount)
            return Bump(root, amount)
        if kind == NORMAL:
            if isinstance(root, NormalMap):
                return _scaled(root, amount)
            if isinstance(root, Bump):
                return Bump(root.input, root.strength * amount)
            return NormalMap(root, amount)
        rgb = kind in (COLOR, STORED)  # a color graph is RGB throughout, also on a float input
        if rgb and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = (float(value),) * 3
        if ref.scale != 1.0:
            root = Multiply(root, Constant((ref.scale,) * 3 if rgb else ref.scale))
        if amount < 1.0 and value is not None:
            return Mix(Constant(value), root, amount)
        if amount > 1.0:
            return Multiply(root, Constant((amount,) * 3 if rgb else amount))
        return root

    def _get(self, i, walk, depth, chain):
        """The MtlBase of map object i, None (an issue) when the branch ends there."""
        if depth > MAX_DEPTH:
            self._issue(walk, i, "maps deeper than %d below object %d" % (MAX_DEPTH, chain[0] if chain else i))
            return None
        if i in chain:
            self._issue(walk, i, "map cycle through object %d" % i)
            return None
        if self.graph.superclass(i) != classids.SC_TEXMAP:
            self._issue(walk, chain[-1] if chain else i, "object %d is not a map" % i)
            return None
        try:
            return self.graph.get(i)
        except ChunkError as e:
            self._issue(walk, i, "map %d: %s" % (i, e))
            return None

    def _node(self, i, kind, walk, depth, chain):
        """The node of map object i in an input of that kind, None when nothing usable is there. Converted once per
        (object, kind, depth): the same map reached again shares the node, its issues and its approximation."""
        # The key leaves out the chain, so a map met first through a cycle keeps the branch the cycle cut, also where
        # it is reached again without one: order-dependent, and only in a scene that has a cycle. Keying on the chain
        # (or not caching a cut) would make a shared map cost one conversion per path to it, not one in all
        # (test_shared_maps_do_not_blow_up).
        if i is None:
            return None
        key = (i, kind, depth)
        hit = self._nodes.get(key)
        if hit is None:
            sub = _Walk()
            with self._into(sub):
                node = self._convert_node(i, kind, sub, depth, chain)
            hit = self._nodes[key] = (node, sub.approximated, tuple(sub.issues))
        walk.merge(hit[1], hit[2])
        return hit[0]

    def _convert_node(self, i, kind, walk, depth, chain):
        m = self._get(i, walk, depth, chain)
        if m is None:
            return None
        key, chain, depth = ClassId(*m.class_id), chain + (i,), depth + 1
        if key in IMAGES:
            return self._image(m, kind, walk)
        if key in NORMAL_MAPS:
            return self._normal(m, NORMAL_MAPS[key], kind, walk, depth, chain)
        rule = _KEEP.get(key)
        if rule is not None:
            if not self.swatches.linear and ((kind == COLOR and key in DISPLAY_MIXES)
                                             or (kind == MASK and key in MASK_MIXES)) and not _black_white(self, m):
                node = rule(self, m, STORED, walk, depth, chain)
                if kind == MASK:
                    return self._decoded_mask(node, walk, depth, chain)
                return self._decoded(node, walk, depth, chain)
            return rule(self, m, kind, walk, depth, chain)
        if key == VRAY_DIRT and self.corona:  # what Corona 12 renders, not a peel (_vray_dirt)
            return self._swatch(WHITE, kind)
        rule = _PEEL.get(key)
        if rule is not None:
            node = rule(self, m, kind, walk, depth, chain)
            if node is not None:
                walk.approximated = True
                self._count(self.stats.peeled, m)
            return node
        return self._peel_to_image(m, kind, walk, depth, chain, "no bitmap below")

    def _decoded(self, node, walk, depth, chain):
        """A STORED node at a color root of a gamma-off scene, shown decoded: a Constant (or a Mix of constants)
        folded exactly, a lone image (a peel, a single layer) its map converted again as a color, else a Decode."""
        if node is None:
            return None
        if isinstance(node, Image):
            return self._node(node.index, COLOR, walk, depth, chain) or node
        value = _constant_value(node)
        if value is not None:
            return Constant(tuple(colors.srgb_to_linear(c) for c in value))
        return Decode(node)

    def _decoded_mask(self, node, walk, depth, chain):
        """A STORED node as a mask in a color graph of a gamma-off scene: V-Ray mixes by the mean of the value it
        holds, which the display-referred scene shows decoded (maxdrop-6n0.6.18: a Mix of greys 40 / 220 at 50 % as
        a mask renders 0.510 in both modes, shown 0.223), so the mean through the exact sRGB curve (Decode mean): a
        constant (or a Mix of constants) folded, a lone image (a peel) its map converted again as a mask."""
        if node is None:
            return None
        if isinstance(node, Image):
            return self._node(node.index, MASK, walk, depth, chain) or node
        value = _constant_value(node)
        if value is not None:
            return Constant(self.swatches.channel(sum(value) / 3.0))
        return Decode(node, mean=True)

    def _peel_to_image(self, m, kind, walk, depth, chain, why):
        """The first image below map m, counted as a peel; None (unsupported, an issue) without one."""
        image = self._first_image(m, kind, walk, depth, chain)
        if image is None:
            self._count(self.stats.unsupported, m)
            self._issue(walk, m.index, "%s %r: %s" % (self._class_name(m), m.name, why))
            return None
        walk.approximated = True
        self._count(self.stats.peeled, m)
        return image

    def _first_image(self, m, kind, walk, depth, chain):
        """The first image below map m, depth first in reference order, None without one; looked for once per
        (map, kind, depth), its issues replayed into every walk that finds it."""
        key = (m.index, kind, depth)
        if key not in self._firsts:
            self._firsts[key] = (None, False, ())  # a cycle back to here finds nothing
            sub = _Walk()
            with self._into(sub):
                image = self._first_image_walk(m, kind, sub, depth, chain)
            self._firsts[key] = (image, sub.approximated, tuple(sub.issues))
        image, approximated, issues = self._firsts[key]
        walk.merge(approximated, issues)
        return image

    def _first_image_walk(self, m, kind, walk, depth, chain):
        for c in m.children:
            if depth > MAX_DEPTH or c in chain or self.graph.superclass(c) != classids.SC_TEXMAP:
                continue
            try:
                sub = self.graph.get(c)
            except ChunkError:
                continue
            if ClassId(*sub.class_id) in IMAGES:
                image = self._image(sub, kind, walk)
                if image is not None:
                    return image
                continue
            image = self._first_image(sub, kind, walk, depth + 1, chain + (c,))
            if image is not None:
                return image
        return None

    def _constant(self, m, pid, kind, default):
        """A color parameter as a Constant of the input's kind."""
        v = m.param(pid, 0)
        rgb = v if isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3]) else default
        return self._swatch(rgb, kind)

    def _swatch(self, rgb, kind):
        """A swatch (0..1 per channel) as a Constant of the input's kind: on a color input the linear color; on a mask
        in a color graph the scene's rule applied to the mean of the swatch (maxdrop-em3.36); on a data input (and a
        height) the mean as stored, whatever the gamma (maxdrop-em3.122); in a normal input and below a wrapper that
        works on color in a data graph or a height (STORED_RGB) its channels as stored: the wrapper acts on the color
        and the mean comes after it, at the float input (maxdrop-em3.128). Each channel clamped to 0..1 first.
        V-Ray 5.2 renders a grey 64 / red VRayColor as glossiness or opacity 0.251 / 0.333 in both modes; as a mask
        between black and white with the gamma off it renders byte 64 / 85, which Blender shows from the decoded number.
        Between two colors V-Ray mixes the stored values: such a Mix is converted in STORED (maxdrop-em3.158)."""
        if kind == COLOR:
            return Constant(self.swatches.color(rgb))
        stored = tuple(min(1.0, max(0.0, c)) for c in rgb[:3])
        if kind in STORED_RGB:
            return Constant(stored)
        mean = sum(stored) / 3.0
        return Constant(self.swatches.channel(mean) if kind == MASK else mean)

    def _on(self, m, map_pid, on_pid, tab=0):
        """The object index of the map a parameter uses: set and its switch (on_pid, None: none) on; else None."""
        if on_pid is not None and not _flag(m, on_pid, True):
            return None
        return _ref(m, map_pid, tab)

    def _lost(self, m, i, walk):
        """The issue of a map i that wrapper m uses and that converts to nothing, naming its class. None for an
        object that is no readable map: _get has named it already."""
        try:
            sub = self.graph.get(i) if self.graph.superclass(i) == classids.SC_TEXMAP else None
        except ChunkError:
            sub = None
        if sub is not None:
            self._issue(walk, m.index, "%s %r: its map %s %r converts to nothing" % (
                self._class_name(m), m.name, self._class_name(sub), sub.name))

    def _sub(self, m, map_pid, on_pid, kind, walk, depth, chain, tab=0):
        """The node of the map a parameter uses (see _on), None without one. A used map that converts to nothing is
        an issue on m: the caller never draws m's own color in its place."""
        i = self._on(m, map_pid, on_pid, tab)
        node = self._node(i, kind, walk, depth, chain)
        if i is not None and node is None:
            self._lost(m, i, walk)
        return node

    def _image(self, m, kind, walk):
        """The Image of a Bitmap, CoronaBitmap or VRayBitmap, None (an issue) without a file."""
        kind = base_kind(kind)  # below a color wrapper in a data graph: a data image (its output not measured)
        key = ClassId(*m.class_id)
        cls, pid = _IMAGE_FILES.get(key, ("Bitmap", BM_FILE))
        entry = self.assets.entry(m.param(pid, 0)) if self.assets is not None else None
        if entry is None:
            self._issue(walk, m.index, "%s %r: no file" % (cls, m.name))
            return None
        found = self.textures.find(entry.path, entry.resolved) if self.textures is not None else None
        out = next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_TEXOUTPUT), None)
        if key == classids.CORONA_BITMAP:
            return self._corona_image(m, kind, walk, entry, found, out)
        uv = next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_UVGEN), None)
        mapping = self._mapping(uv, m)
        if key == classids.VRAY_BITMAP:
            return self._vray_image(m, kind, walk, entry, found, out, mapping)
        self._placement_issues(m, walk, "Bitmap", mapping)
        crop = None
        clip = tuple(_num(m, pid, d) for pid, d in ((BM_CLIP_U, 0.0), (BM_CLIP_V, 0.0), (BM_CLIP_W, 1.0),
                                                     (BM_CLIP_H, 1.0)))
        if _flag(m, BM_APPLY, False) and clip != (0.0, 0.0, 1.0, 1.0):
            crop = Crop(*clip, place=m.param(BM_CROP_PLACE, 0) == 1)
        gamma = self._bitmap_gamma(self._gamma(m), entry.name)
        alpha = m.param(BM_MONO if kind in FLOATS else BM_RGB, 0) == 1
        stored = not self.swatches.linear
        return _stored_mask(Image(m.index, entry.name, entry.path, entry.resolved, found, mapping, crop,
                                  self._output(out, m), colorspace(kind, gamma, stored), gamma, alpha), kind, stored)

    def _placement_issues(self, m, walk, cls, mapping):
        """The issues of a UVGen's mapping that no UVs can draw."""
        if mapping.environment:
            self._issue(walk, m.index, "%s %r: environment mapping, drawn with the UVs" % (cls, m.name))
        elif mapping.source in (OBJECT_XYZ, WORLD_XYZ):
            self._issue(walk, m.index, "%s %r: planar %s XYZ mapping, drawn with the UVs" % (
                cls, m.name, "object" if mapping.source == OBJECT_XYZ else "world"))
        if mapping.real_world:
            self._issue(walk, m.index, "%s %r: real-world scale, its tiling in scene units not converted"
                        % (cls, m.name))

    def _vray_image(self, m, kind, walk, entry, found, out, mapping):
        """A VRayBitmap's Image: its Placement as a Bitmap's, its transfer function as a gamma (a Bitmap's
        meaning: linear = pixel ^ gamma), overall times render multiplier times its Output's amount (renderMap
        scales by the overall one; the render one applies when V-Ray renders)."""
        map_type = m.param(VB_MAP_TYPE, 0)
        if map_type not in (None, VB_STANDARD):
            mapping = dataclasses.replace(mapping, environment=True)
            self._issue(walk, m.index, "VRayBitmap %r: environment mapping (type %r), drawn with the UVs"
                        % (m.name, map_type))
        else:
            self._placement_issues(m, walk, "VRayBitmap", mapping)
        if _flag(m, VB_SOURCE_ON, True) and _ref(m, VB_SOURCE) is not None:
            self._issue(walk, m.index, "VRayBitmap %r: the placement of its map source not converted" % (m.name,))
        if kind == NORMAL:  # below VRayNormalMap and Normal Bump V-Ray 5.2 reads it as stored, whatever its transfer
            gamma, stored = 1.0, True  # function (CoronaNormal assumed alike)
        else:
            gamma = self._vray_gamma(m, walk, entry.name)
            stored = m.param(VB_COLOR_SPACE, 0) == VB_FROM_MAX and not self.swatches.linear
        if m.param(VB_RGB_SPACE, VB_RGB_SPACE_BLOCK) == VB_ACESCG:
            self._issue(walk, m.index, "VRayBitmap %r: ACEScg primaries drawn as sRGB" % (m.name,))
        if kind not in FLOATS and m.param(VB_RGB, 0) == VB_INTENSITY:
            self._issue(walk, m.index, "VRayBitmap %r: RGB output intensity as gray drawn as its color" % (m.name,))
        crop = None
        clip = tuple(_num(m, pid, d) for pid, d in ((VB_CROP_U, 0.0), (VB_CROP_V, 0.0), (VB_CROP_W, 1.0),
                                                     (VB_CROP_H, 1.0)))
        if _flag(m, VB_CROP_ON, False) and clip != (0.0, 0.0, 1.0, 1.0):
            crop = Crop(*clip, place=m.param(VB_CROP_MODE, 0) == 1)
        mult = max(0.0, _num(m, VB_MULT, 1.0)) * max(0.0, _num(m, VB_RENDER_MULT, 1.0))
        if not mult <= MAX_MULTIPLIER:
            self._issue(walk, m.index, "VRayBitmap %r: multiplier %r not converted: 1" % (m.name, mult))
            mult = 1.0
        output = self._output(out, m) or TexOutput()
        output = dataclasses.replace(output, amount=output.amount * mult)
        alpha = m.param(VB_MONO if kind in FLOATS else VB_RGB, 0) == 1
        if not self.swatches.linear and kind in (COLOR, MASK):
            # gamma off: From 3ds Max reads any file as stored, which the scene shows decoded (a Bitmap's rule);
            # every other transfer function is V-Ray's own decode, shown decoded once more
            gamma = None if stored else _shown(gamma)
        return _stored_mask(Image(m.index, entry.name, entry.path, entry.resolved, found, mapping, crop,
                                  None if output == TexOutput() else output, colorspace(kind, gamma, stored), gamma,
                                  alpha), kind, stored)

    def _bitmap_gamma(self, override, name):
        """A Bitmap's gamma as 3ds Max reads it in this scene (maxdrop-em3.38, V-Ray 5.2 renders): with the gamma on
        the override, else the file input gamma (None for 2.2: sRGB), a float file (EXR, HDR) without an override
        linear; with it off the image as stored whatever its override, which the display-referred scene shows
        decoded: None (sRGB), a float file too (V-Ray 5.2: an EXR of 0.5 renders 0.5, shown from 0.214 linear;
        maxdrop-em3.123)."""
        if not self.swatches.linear:
            return None
        if override is None and name.lower().endswith(FLOAT_IMAGES):
            return 1.0
        return override if override is not None else self._file_in()

    def _file_in(self):
        """The gamma an automatic image is read with: the scene's file input gamma with the gamma on, None for 2.2
        (sRGB) or with the gamma off."""
        g = self.swatches.file_in
        return g if self.swatches.linear and g != colors.SRGB_FILE_GAMMA else None

    def _vray_gamma(self, m, walk, name):
        """A VRayBitmap's transfer function as a Bitmap gamma, None for automatic: V-Ray's own decode, the same with
        the gamma on and off (V-Ray 5.2). Auto and From 3ds Max read a float file (EXR, HDR) as linear, as V-Ray and
        3ds Max do; From 3ds Max reads an 8-bit file as a Bitmap with automatic gamma does (the file input gamma
        with the gamma on). With the gamma off _vray_image turns it into what the scene shows (_shown)."""
        space = m.param(VB_COLOR_SPACE, 0)
        if space == VB_LINEAR:
            return 1.0
        if space == VB_INVERSE_GAMMA:
            inverse = _num(m, VB_GAMMA, 0.0)
            if 0.1 <= inverse <= 10.0:
                return 1.0 / inverse
            self._issue(walk, m.index, "VRayBitmap %r: transfer function inverse gamma %r not converted: automatic"
                        % (m.name, m.param(VB_GAMMA, 0)))
        elif space is not None and space not in VB_AUTOMATIC:
            self._issue(walk, m.index, "VRayBitmap %r: transfer function %r not converted: automatic"
                        % (m.name, space))
        elif space != VB_SRGB and name.lower().endswith(FLOAT_IMAGES):
            return 1.0
        elif space == VB_FROM_MAX:
            return self._file_in()
        return None

    def _corona_image(self, m, kind, walk, entry, found, out):
        """A CoronaBitmap's Image. Its tiling, offset and W angle place the image as a Bitmap's do (measured in
        3ds Max); its environment mode applies only to an environment map. Its gamma applies with the gamma on and
        off (Corona 12 renders the same internal value); with it off a color input or a mask shows it decoded once
        more (_shown, maxdrop-em3.165)."""
        def mode(pid):
            v = m.param(pid, 0)
            return v if v in (0, 1, 2) else 1
        tile_u, tile_v = mode(CB_TILE_U), mode(CB_TILE_V)
        channel = m.param(CB_CHANNEL, 0)
        if not (isinstance(channel, int) and not isinstance(channel, bool) and 0 <= channel <= 99):
            channel = 1
        mapping = Mapping(
            channel=channel, tiling=_vec(m, CB_SCALE, (1.0, 1.0, 1.0))[:2],
            offset=_vec(m, CB_OFFSET, (0.0, 0.0, 0.0))[:2],
            angle=(0.0, 0.0, _num(m, CB_W_ANGLE, 0.0)),
            tile=(tile_u != CB_NO_TILE, tile_v != CB_NO_TILE), mirror=(tile_u == CB_MIRROR, tile_v == CB_MIRROR),
            real_world=_flag(m, CB_REAL_WORLD, False), blur=_num(m, CB_BLUR, 1.0))
        if mapping.real_world:
            self._issue(walk, m.index, "CoronaBitmap %r: real-world scale, its tiling in scene units not converted"
                        % (m.name,))
        crop = None
        clip = tuple(_num(m, pid, d) for pid, d in ((CB_CLIP_U, 0.0), (CB_CLIP_V, 0.0), (CB_CLIP_W, 1.0),
                                                     (CB_CLIP_H, 1.0)))
        if _flag(m, CB_CLIP_ON, False) and clip != (0.0, 0.0, 1.0, 1.0):
            crop = Crop(*clip, place=m.param(CB_CLIP_MODE, 0) == 1)
        gamma = _num(m, CB_GAMMA, -1.0)  # -1: automatic
        gamma = _auto_gamma(gamma if 0.1 <= gamma <= 10.0 else None, entry.name)
        if not self.swatches.linear and kind in (COLOR, MASK):
            # gamma off: Corona 12 holds its own decode, in both modes, which the scene shows decoded once more
            # (maxdrop-em3.165), as V-Ray a VRayBitmap's; in STORED the Decode above does that
            gamma = _shown(gamma)
        alpha = m.param(CB_MONO if kind in FLOATS else CB_RGB, 0) == 1
        return Image(m.index, entry.name, entry.path, entry.resolved, found, mapping, crop, self._output(out, m),
                     colorspace(kind, gamma), gamma, alpha)

    def _mapping(self, uv, m):
        if uv is None:
            return Mapping()
        p = reader_materials.placement(self.graph.scene, uv.index)
        source = p.source if p.source in (EXPLICIT, OBJECT_XYZ, VERTEX_COLOR, WORLD_XYZ) else EXPLICIT
        channel = 1 if p.channel is None else p.channel
        channel = 0 if source == VERTEX_COLOR else (channel if 0 <= channel <= 99 else 1)
        def old(index, default):
            return self._old(uv, index, default, m, "Coordinates")

        return Mapping(
            channel=channel,
            tiling=(old(UV_U_TILING, 1.0), old(UV_V_TILING, 1.0)),
            offset=(old(UV_U_OFFSET, 0.0), old(UV_V_OFFSET, 0.0)),
            angle=(old(UV_U_ANGLE, 0.0), old(UV_V_ANGLE, 0.0), old(UV_W_ANGLE, 0.0)),
            tile=p.tile,
            mirror=p.mirror,
            axis=p.axis if p.axis in (0, 1, 2) else 0,
            source=source,
            environment=p.environment,
            real_world=p.real_world,
            blur=old(UV_BLUR, 1.0))

    def _output(self, part, m):
        """The TexOutput of map m's Output part, None when it changes nothing."""
        if part is None:
            return None
        out = TexOutput(reader_materials.output_invert(self.graph.scene, part.index),
                        *(self._old(part, pid, default, m, "Output") for pid, default in
                          ((OUT_AMOUNT, 1.0), (OUT_LEVEL, 1.0), (OUT_OFFSET, 0.0))))
        return None if out == TexOutput() else out

    def _gamma(self, m):
        """The Bitmap's gamma override, None for automatic, when it cannot be read or is outside 0.1 to 10."""
        gamma = reader_materials.bitmap_gamma(self.graph.scene, m)
        return gamma if gamma is not None and math.isfinite(gamma) and 0.1 <= gamma <= 10.0 else None

    def _normal(self, m, ids, kind, walk, depth, chain):
        normal = self._sub(m, ids.normal, ids.normal_on, NORMAL, walk, depth, chain)
        bump = self._sub(m, ids.bump, ids.bump_on, BUMP, walk, depth, chain)
        kind = base_kind(kind)
        if kind not in (NORMAL, BUMP):  # a normal map in a color or data input: its image only
            # a graph without an image (an empty Output or RGB Tint, a constant) is no image to stand for the normal
            # map's color
            image = next((n for n in (_peeled_image(normal), _peeled_image(bump))
                          if n is not None and first_image(n) is not None), None)
            if image is None:
                self._count(self.stats.unsupported, m)
                return None
            walk.approximated = True
            self._count(self.stats.peeled, m)
            return image
        key = ClassId(*m.class_id)
        if key == NORMAL_BUMP and m.param(NORMAL_BUMP_METHOD, 0) not in (None, 0):
            self._issue(walk, m.index, "Normal Bump %r: method %r drawn as tangent space" % (
                m.name, m.param(NORMAL_BUMP_METHOD, 0)))
        if key == CORONA_NORMAL and _flag(m, CORONA_ADD_GAMMA, False) and self.swatches.linear:
            # Corona 12 raises the input to 1 / 2.2 with the gamma on, and does nothing with it off (maxdrop-em3.159);
            # folded into the image's gamma, which the builder applies before its Output and not to its alpha
            if isinstance(normal, Image) and normal.output is None and not normal.alpha:
                normal = _add_gamma(normal)
            elif normal is not None:
                self._issue(walk, m.index, "CoronaNormal %r: 'add gamma to input' not converted" % (m.name,))
        bump = Bump(_bump_input(bump), max(0.0, _num(m, ids.bump_strength, 1.0))) if bump is not None else None
        if normal is None:
            return bump
        channel = m.param(ids.channel, 0) if ids.channel is not None else None
        channel = channel if isinstance(channel, int) and not isinstance(channel, bool) and 0 <= channel <= 99 else 1
        return NormalMap(normal, max(0.0, _num(m, ids.strength, 1.0)), _flag(m, ids.flip_red, False),
                         _flag(m, ids.flip_green, False), _flag(m, ids.swap, False), bump, channel)


def _scene_meters(graph):
    """Meters per system unit of a MaterialGraph's scene: what the file says, else DEFAULT_METERS."""
    s = getattr(graph, "scene", None)
    unit = units.system_unit(s) if isinstance(s, reader_scene.Scene) else None
    return unit.meters if unit is not None else DEFAULT_METERS


def _add_gamma(image):
    """A normal image below a CoronaNormal that adds gamma to its input in a gamma-on scene: its decode divided by
    2.2 (Non-Color counts as 1.0, sRGB as 2.2; Corona 12 renders a Bitmap or CoronaBitmap auto as stored, a 1.0 one
    raised to 1 / 2.2)."""
    own = 1.0 if image.colorspace == NON_COLOR else SRGB_GAMMA if image.gamma is None else image.gamma
    gamma = own / SRGB_GAMMA
    return dataclasses.replace(image, gamma=gamma, colorspace=colorspace(NORMAL, gamma))


def _bump_input(node):
    return node.input if isinstance(node, Bump) else node


def _peeled_image(node):
    """The image of a normal map's sub-node, else the node itself."""
    if isinstance(node, NormalMap):
        return node.input
    if isinstance(node, Bump):
        return node.input
    return node


def _scaled(n, amount):
    bump = Bump(n.bump.input, n.bump.strength * amount) if n.bump is not None else None
    return dataclasses.replace(n, strength=n.strength * amount, bump=bump)
