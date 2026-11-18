# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender materials from convert.materials.MaterialIR: a Principled BSDF, its texture graphs drawn as nodes.

    builder = MaterialBuilder()
    material = builder.make(ir)         # a new Material, None when it fails; build.objects: once per Max material
    builder.issues()                    # [(label, reason)]: textures that do not load, channel 0, failed materials
    builder.classes                     # Counter {class name: materials made by a rule (grey ones not counted)}
    builder.sockets_skipped             # Counter {Principled input name: materials that needed it on this Blender}

The Principled BSDF's inputs are looked up by name with an existence check: Thin Wall exists from Blender 5.0 and
Diffuse Roughness from 4.5, so on an older Blender a value the IR asks for there is skipped and counted. Other
nodes' inputs are looked up by identifier (Fac, Bright, A_Color...), which stays the same while their names change
between versions.

Inputs: Base Color, Metallic, Roughness, IOR, Alpha, Specular IOR Level (SPECULAR_LEVEL times the IR's specular:
a reflection weight, 1 being the full Fresnel reflection at the IOR, Blender's 0.5), Transmission Weight, Emission
Color and Strength, Coat Weight, Roughness, IOR and Tint, Subsurface Weight, Radius (the IR's subsurface color, per
channel) and Scale (its radius in meters), Thin Wall, Normal. A color graph on a float input (specular,
transmission) goes through the mean of its channels, the measure convert/materials.py uses.

Texture graphs (convert/texmaps.py) become nodes, a node of the IR shared by several inputs once per material:
Image -> Image Texture (its image datablock reused per file and color space: one file used in two color spaces is
two datablocks), with its placement as a Mapping node and a UV Map node for a map channel other than 1; Invert,
Mix, Multiply, ColorCorrect (Hue/Saturation/Value, Bright/Contrast, gain, Gamma), Composite (Mix per layer),
NormalMap (Normal Map node, flips through Separate / Combine Color), Bump (Bump node). A texture file that was not
found (or does not load) keeps its Image Texture node, without an image and not connected. The texture lookup
(convert.textures) reports a file not found by name; the builder reports a file that does not load. The graph
above the node carries on without it (a Mix gives its other side, a normal map without its image nothing) and an
input left without a map keeps the IR's value. An empty image node renders black in EEVEE and magenta in Cycles,
and in a normal or alpha input it would wreck the shading or hide the object.

Placement, the 3ds Max convention (StdUVGen: scaled and turned about the map's center, offset in UV fractions):
sample = R(u, v, w angles) S(tiling) (uv - 0.5 - offset) + 0.5, one Mapping node (POINT): uv_transform(). Crop:
that brought into the 0..1 cell per axis as the map repeats there (crop_repeat: wrapped for tile, ping-ponged for
mirror, outside the image for neither), then a Mapping POINT into the cropped rectangle (TEXTURE, out of it, for a
placed image). Without a crop Blender's one extension for both axes stands for tile and mirror (extension()).
Map channel 0 (the vertex color as UVW) has no UV layer: such a map is drawn on channel 1 and reported.
A texture file that holds no image (empty, or not starting as its format does: image_has_data) is reported and
left out as one that does not load. A material whose build raises is removed again and reported: its slot stays
empty.
Alpha: Material.surface_render_method only, BLENDED for a constant alpha below 1, DITHERED for an alpha map.
"""
import collections
import os
import traceback

import bpy
from mathutils import Euler, Matrix, Vector

from .. import compat
from ..convert import scene as convert_scene
from ..convert import texmaps as tx

SPECULAR_LEVEL = 0.5
X_STEP, Y_STEP = 300, 280
COLOR, FLOAT = "color", "float"
_EPS = 1e-6
MISSING = object()  # what a graph gives where its image is missing


def uv_transform(mapping):
    """(location, rotation, scale) of the Mapping node (POINT) that places a texmaps.Mapping; None for the identity."""
    tiling, offset, angle = tuple(mapping.tiling), tuple(mapping.offset), tuple(mapping.angle)
    if tiling == (1.0, 1.0) and offset == (0.0, 0.0) and angle == (0.0, 0.0, 0.0):
        return None
    rs = Euler(angle, 'XYZ').to_matrix() @ Matrix.Diagonal((tiling[0], tiling[1], 1.0))
    location = Vector((0.5, 0.5, 0.0)) - rs @ Vector((0.5 + offset[0], 0.5 + offset[1], 0.0))
    return tuple(location), angle, (tiling[0], tiling[1], 1.0)


def crop_axes(mapping):
    """Per axis (U, V), how a cropped or placed image repeats: 'MIRROR' (mirror on, which tiles too, as in 3ds
    Max), 'REPEAT' (tile) or 'CLIP'."""
    return tuple('MIRROR' if m else 'REPEAT' if t else 'CLIP' for t, m in zip(mapping.tile, mapping.mirror))


def extension(mapping, crop=None):
    """The Image Texture extension of a placement: Blender has one for both axes. With a crop the nodes repeat
    per axis and keep the coordinates inside the crop rectangle (EXTEND: no bleed from its opposite edge), unless
    the image is placed or an axis clips (CLIP)."""
    if crop is not None:
        return 'CLIP' if crop.place or 'CLIP' in crop_axes(mapping) else 'EXTEND'
    if all(mapping.tile):
        return 'REPEAT'
    if any(mapping.mirror):
        return 'MIRROR'
    if any(mapping.tile):
        return 'REPEAT'
    return 'CLIP'


# the first bytes of every image format Blender reads that has a signature (TGA has none: _targa; WebP apart)
_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"BM", b"BA", b"CI", b"CP", b"IC", b"PT", b"II*\x00",
               b"MM\x00*", b"II+\x00", b"MM\x00+", b"v/1\x01", b"#?", b"DDS ", b"8BPS",
               b"\x00\x00\x00\x0cjP  \r\n\x87\n", b"\xffO\xffQ", b"\x01\xda", b"\xda\x01", b"\x80\x2a\x5f\xd7",
               b"\xd7\x5f\x2a\x80", b"SDPX", b"XPDS")


def _targa(head):
    """A plausible TGA header (color map type, image type, pixel depth): Blender reads a Targa whatever its name."""
    return (len(head) >= 18 and head[1] in (0, 1) and head[2] in (1, 2, 3, 9, 10, 11)
            and head[16] in (8, 15, 16, 24, 32))
_SIGNED = frozenset((".png", ".jpg", ".jpeg", ".jpe", ".bmp", ".tif", ".tiff", ".exr", ".hdr", ".dds", ".psd",
                     ".webp", ".jp2", ".j2k", ".j2c", ".sgi", ".rgb", ".rgba", ".bw", ".cin", ".dpx"))


def image_has_data(path):
    """False when the file at path cannot hold an image: empty, or named as a format with a signature but starting
    with none Blender reads. Only the first bytes are read: Blender loads images lazily, and asking it
    (Image.has_data) would decode every image during the import. A file that cannot be opened passes: its load
    reports it."""
    try:
        with open(path, "rb") as f:
            head = f.read(18)
    except OSError:
        return True
    if not head:
        return False
    if os.path.splitext(path)[1].lower() not in _SIGNED:
        return True
    return head.startswith(_SIGNATURES) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP") or _targa(head)


def uv_layer_name(channel):
    """The UV layer build.objects made for a 3ds Max map channel (convert/scene.py's names)."""
    return convert_scene.UV_FIRST if channel == 1 else convert_scene.UV_NAME % channel


def _mean(v):
    return sum(v[:3]) / 3.0 if isinstance(v, (tuple, list)) else float(v)


def _as(value, space):
    """A constant in a space: an RGB tuple for COLOR, a float for FLOAT."""
    if space == COLOR:
        return tuple(value[:3]) if isinstance(value, (tuple, list)) else (float(value),) * 3
    return _mean(value)


def _default(socket, value):
    """Set an unlinked input from a constant, whatever its type."""
    if socket.type == 'RGBA':
        socket.default_value = _as(value, COLOR) + (1.0,)
    elif socket.type == 'VECTOR':
        socket.default_value = _as(value, COLOR)
    elif socket.type == 'BOOLEAN':
        socket.default_value = bool(value)
    else:
        socket.default_value = _mean(value)


def _in(node, identifier):
    """A node's input by identifier: names change between Blender versions (Fac / Factor), identifiers do not."""
    return next(s for s in node.inputs if s.identifier == identifier)


def _out(node, identifier):
    return next(s for s in node.outputs if s.identifier == identifier)


class MaterialBuilder:
    """Makes the materials of one import; images shared between them."""

    def __init__(self):
        self.images = {}  # (normalized path, color space) -> Image or None (not loaded)
        self._issues = []
        self._seen = set()
        self.classes = collections.Counter()
        self.sockets_skipped = collections.Counter()

    def issue(self, label, reason):
        if (label, reason) not in self._seen:
            self._seen.add((label, reason))
            self._issues.append((label, reason))

    def issues(self):
        """[(label, reason)] for the import report, each once, in the order met."""
        return list(self._issues)

    def make(self, ir):
        """A new Material for a MaterialIR; None (an empty slot, and an issue) when building it fails: one material
        never costs the scene."""
        material = bpy.data.materials.new(ir.name or "Material")
        try:
            tree = _Tree(self, material, ir)
            tree.build()
        except Exception as e:
            name = material.name
            bpy.data.materials.remove(material)
            print("MaxDrop: material %s not built:\n%s" % (name, traceback.format_exc()), end="")
            self.issue("material %s" % name, "material not built (%s: %s)" % (type(e).__name__, e))
            return None
        self.sockets_skipped.update(tree.skipped)
        if not ir.unknown:
            self.classes[ir.source] += 1
        return material

    def image(self, img, label):
        """The Image of a texmaps.Image (None when its file was not found or does not load)."""
        if img.found is None:
            return None
        key = (os.path.normcase(os.path.abspath(img.found.path)), img.colorspace)
        if key not in self.images:
            if not image_has_data(img.found.path):
                self.issue(label, "texture not loaded: %s (no image data)" % img.name)
                self.images[key] = None
                return None
            try:
                image = bpy.data.images.load(img.found.path, check_existing=False)
            except RuntimeError as e:
                self.issue(label, "texture not loaded: %s (%s)" % (img.name, e))
                image = None
            if image is not None:
                image.colorspace_settings.name = img.colorspace
            self.images[key] = image
        return self.images[key]


class _Tree:
    """The node tree of one material while it is built."""

    def __init__(self, builder, material, ir):
        self.builder, self.material, self.ir = builder, material, ir
        self.label = "material %s" % (material.name,)
        self.skipped = set()  # the Principled inputs the IR needs that this Blender lacks
        tree = compat.material_node_tree(material)
        self.nodes, self.links = tree.nodes, tree.links
        self.nodes.clear()
        self.memo, self.uvs, self.texture_nodes = {}, {}, {}
        self.columns, self.row = {}, 0.0
        self.bsdf = self.nodes.new("ShaderNodeBsdfPrincipled")
        self.bsdf.location = (0.0, 0.0)
        out = self.nodes.new("ShaderNodeOutputMaterial")
        out.location = (X_STEP, 0.0)
        self.links.new(_out(self.bsdf, "BSDF"), _in(out, "Surface"))

    # nodes and layout

    def node(self, kind, depth):
        """A new node at its column (depth to the left of the BSDF), below the nodes already there."""
        n = self.nodes.new(kind)
        y = min(self.row, self.columns.get(depth, self.row))
        n.location = (-X_STEP * (depth + 1), y)
        self.columns[depth] = y - Y_STEP
        return n

    def start_row(self):
        self.row = min(self.columns.values(), default=0.0)

    def feed(self, socket, value):
        """Link a node output into socket, or set a constant on it."""
        if isinstance(value, bpy.types.NodeSocket):
            self.links.new(value, socket)
        else:
            _default(socket, value)

    def socket(self, value, space, depth):
        """A node output for a value: the value itself when it is one, else an RGB or Value node holding it."""
        if isinstance(value, bpy.types.NodeSocket):
            return value
        if space == COLOR:
            n = self.node("ShaderNodeRGB", depth)
            n.outputs[0].default_value = _as(value, COLOR) + (1.0,)
        else:
            n = self.node("ShaderNodeValue", depth)
            n.outputs[0].default_value = _mean(value)
        return n.outputs[0]

    # the Principled inputs

    def bsdf_input(self, name, needed=True):
        """The Principled input of that name; None (counted when needed) on a Blender without it."""
        s = self.bsdf.inputs.get(name)
        if s is None and needed:
            self.skipped.add(name)
        return s

    def value(self, name, value, needed=True):
        s = self.bsdf_input(name, needed)
        if s is not None:
            _default(s, value)

    def color_input(self, name, inp, graph):
        s = self.bsdf_input(name)
        if s is None:
            return
        self.start_row()
        v = self.graph(graph.root, COLOR, 0) if graph is not None else MISSING
        self.feed(s, inp.value if v is MISSING else v)

    def float_input(self, name, inp, graph, scale=1.0):
        """A float input; a color graph on it goes through the mean of its channels, times scale. True when a
        node drives it."""
        s = self.bsdf_input(name)
        if s is None:
            return False
        self.start_row()
        color = graph is not None and graph.kind == tx.COLOR
        v = MISSING if graph is None else (
            self.graph(graph.root, COLOR, 1) if color else self.graph(graph.root, FLOAT, 0))
        if not isinstance(v, bpy.types.NodeSocket):
            _default(s, _mean(inp.value if v is MISSING else v) * scale)
            return False
        if color:
            dot = self.node("ShaderNodeVectorMath", 0)
            dot.operation = 'DOT_PRODUCT'
            self.links.new(v, _in(dot, "Vector"))
            _in(dot, "Vector_001").default_value = (scale / 3.0,) * 3
            v = _out(dot, "Value")
        elif scale != 1.0:
            mul = self.node("ShaderNodeMath", 0)
            mul.operation = 'MULTIPLY'
            self.links.new(v, mul.inputs[0])
            mul.inputs[1].default_value = scale
            v = mul.outputs[0]
        self.links.new(v, s)
        return True

    def build(self):
        """Fill the material from its IR."""
        ir, tex = self.ir, self.ir.textures
        self.color_input("Base Color", ir.base_color, tex.get("base_color"))
        self.float_input("Metallic", ir.metallic, tex.get("metallic"))
        self.float_input("Roughness", ir.roughness, tex.get("roughness"))
        self.float_input("Specular IOR Level", ir.specular, tex.get("specular"), SPECULAR_LEVEL)
        self.value("IOR", ir.ior)
        self.float_input("Transmission Weight", ir.transmission, tex.get("transmission"))
        self.color_input("Emission Color", ir.emission_color, tex.get("emission_color"))
        self.value("Emission Strength", ir.emission_strength)
        alpha_map = self.float_input("Alpha", ir.alpha, tex.get("alpha"))
        out = None
        for key in ("normal", "bump"):  # a bump on top of the normal map, when both are there
            if key in tex:
                self.start_row()
                out = self.normal_root(tex[key].root, 0, out)
        normal = self.bsdf_input("Normal") if out is not None else None
        if normal is not None:
            self.links.new(out, normal)
        self.value("Coat Weight", ir.coat_weight)
        self.value("Coat Roughness", ir.coat_roughness)
        self.value("Coat IOR", ir.coat_ior)
        self.value("Coat Tint", ir.coat_color)
        self.value("Subsurface Weight", ir.subsurface_weight)
        if ir.subsurface_weight > 0:
            self.value("Subsurface Radius", ir.subsurface_color)
            self.value("Subsurface Scale", ir.subsurface_radius)
        if ir.thin_walled:
            self.value("Thin Wall", True)
        m = self.material
        alpha = self.bsdf_input("Alpha", needed=False)
        if alpha_map:
            m.surface_render_method = 'DITHERED'
        elif alpha is not None and alpha.default_value < 1.0:
            m.surface_render_method = 'BLENDED'
        m.diffuse_color = _as(ir.base_color.value, COLOR) + (1.0,)
        m.metallic = min(1.0, max(0.0, _mean(ir.metallic.value)))
        m.roughness = min(1.0, max(0.0, _mean(ir.roughness.value)))

    def graph(self, node, space, depth):
        """The output (a node socket) or constant of an IR node in a space."""
        key = (id(node), space)
        if key not in self.memo:
            self.memo[key] = self._build(node, space, depth)
        return self.memo[key]

    def _build(self, n, space, depth):
        if isinstance(n, tx.Constant):
            return _as(n.value, space)
        if isinstance(n, tx.Image):
            return self.image(n, space, depth)
        if isinstance(n, tx.Invert):
            return self.invert(self.graph(n.input, space, depth + 1), space, depth)
        if isinstance(n, tx.Mix):
            return self.mix(n, space, depth)
        if isinstance(n, tx.Multiply):
            return self.multiply(n, space, depth)
        if isinstance(n, tx.ColorCorrect):
            return self.color_correct(n, space, depth)
        if isinstance(n, tx.Composite):
            return self.composite(n, space, depth)
        if isinstance(n, (tx.NormalMap, tx.Bump)):  # texmaps puts these at a normal or bump root only: its image
            image = tx.first_image(n)
            return self.graph(image, space, depth) if image is not None else MISSING
        return MISSING

    def normal_root(self, n, depth, normal):
        """The Normal output of a normal or bump graph's root (normal when its images are missing); normal: a
        normal to bump further, or None."""
        if isinstance(n, tx.NormalMap):
            out = self.normal_map(n, depth + (1 if n.bump is not None else 0))
            out = normal if out is None else out
            return self.bump(n.bump, depth, out) if n.bump is not None else out
        if not isinstance(n, tx.Bump):
            n = tx.Bump(n)
        return self.bump(n, depth, normal)

    def bump(self, n, depth, normal):
        """A Bump node over normal (None: the surface's); normal itself when the height map is missing."""
        height = self.graph(n.input, FLOAT, depth + 1)
        if not isinstance(height, bpy.types.NodeSocket):
            return normal
        b = self.node("ShaderNodeBump", depth)
        self.links.new(height, _in(b, "Height"))
        b.invert = n.strength < 0  # a negative bump amount inverts the height
        _in(b, "Strength").default_value = min(1.0, abs(n.strength))
        _in(b, "Distance").default_value = max(1.0, abs(n.strength))
        if normal is not None:
            self.links.new(normal, _in(b, "Normal"))
        return _out(b, "Normal")

    def normal_map(self, n, depth):
        """A Normal Map node, None when its image is missing."""
        flips = n.flip_red or n.flip_green or n.swap
        color = self.graph(n.input, COLOR, depth + (3 if flips else 1))
        if not isinstance(color, bpy.types.NodeSocket):
            return None
        nm = self.node("ShaderNodeNormalMap", depth)
        nm.space = 'TANGENT'
        channel = self.channel(n.channel, tx.first_image(n))
        if channel != 1:
            nm.uv_map = uv_layer_name(channel)
        _in(nm, "Strength").default_value = max(0.0, n.strength)
        if flips:
            sep = self.node("ShaderNodeSeparateColor", depth + 2)
            comb = self.node("ShaderNodeCombineColor", depth + 1)
            self.links.new(color, _in(sep, "Color"))
            red, green = _out(sep, "Red"), _out(sep, "Green")
            if n.swap:
                red, green = green, red
            for out, flip, target in ((red, n.flip_red, "Red"), (green, n.flip_green, "Green")):
                if flip:
                    inv = self.node("ShaderNodeMath", depth + 1)
                    inv.operation = 'SUBTRACT'
                    inv.inputs[0].default_value = 1.0
                    self.links.new(out, inv.inputs[1])
                    out = inv.outputs[0]
                self.links.new(out, _in(comb, target))
            self.links.new(_out(sep, "Blue"), _in(comb, "Blue"))
            color = _out(comb, "Color")
        self.links.new(color, _in(nm, "Color"))
        return _out(nm, "Normal")

    def channel(self, channel, img):
        """The map channel drawn for img: channel 0 (the vertex color as UVW) is no UV layer build.objects makes,
        so UV channel 1, reported."""
        if channel != 0:
            return channel
        self.builder.issue(self.label, "map channel 0 (vertex color) not imported: %s on UV channel 1"
                           % (img.name if img is not None else "a normal map"))
        return 1

    def uv(self, channel, depth):
        if channel not in self.uvs:
            if channel == 1:
                n = self.node("ShaderNodeTexCoord", depth)
            else:
                n = self.node("ShaderNodeUVMap", depth)
                n.uv_map = uv_layer_name(channel)
            self.uvs[channel] = _out(n, "UV")
        return self.uvs[channel]

    def image(self, img, space, depth):
        """The output of an Image's Texture node (made once per material), MISSING when it has no image."""
        tex = self.texture_nodes.get(id(img))
        if tex is None:
            tex = self.texture_nodes[id(img)] = self.texture_node(img, depth)
        if tex.image is None:
            return MISSING
        out = tex.outputs["Alpha" if img.alpha else "Color"]
        # texmaps made a color input's image Non-Color for its gamma override: decode it with that gamma. A mask is
        # built in FLOAT, so it never gets it, nor does a data input.
        if space == COLOR and not img.alpha and img.gamma is not None and abs(img.gamma - 1.0) > _EPS \
                and img.colorspace == tx.NON_COLOR == tx.colorspace(tx.COLOR, img.gamma):
            g = self.node("ShaderNodeGamma", depth)
            self.links.new(out, _in(g, "Color"))
            _in(g, "Gamma").default_value = img.gamma
            out = _out(g, "Color")
        return self.output(img.output, out, depth) if img.output is not None else out

    def texture_node(self, img, depth):
        tex = self.node("ShaderNodeTexImage", depth)
        tex.image = self.builder.image(img, self.label)
        tex.label = img.name
        tex.extension = extension(img.mapping, img.crop)
        placed = uv_transform(img.mapping)
        channel = self.channel(img.mapping.channel, img)
        vector = None
        if placed is not None or img.crop is not None or channel != 1:
            vector = self.uv(channel, depth + 5)
        if placed is not None:
            m = self.node("ShaderNodeMapping", depth + 4)
            m.vector_type = 'POINT'
            _in(m, "Location").default_value = placed[0]
            _in(m, "Rotation").default_value = placed[1]
            _in(m, "Scale").default_value = placed[2]
            self.links.new(vector, _in(m, "Vector"))
            vector = _out(m, "Vector")
        if img.crop is not None:
            c = img.crop
            vector = self.crop_repeat(vector, img.mapping, c, depth + 1)
            m = self.node("ShaderNodeMapping", depth + 1)
            m.vector_type = 'TEXTURE' if c.place else 'POINT'
            _in(m, "Location").default_value = (c.u, 1.0 - c.v - c.h, 0.0)
            _in(m, "Scale").default_value = (c.w, c.h, 1.0)
            self.links.new(vector, _in(m, "Vector"))
            vector = _out(m, "Vector")
        if vector is not None:
            self.links.new(vector, _in(tex, "Vector"))
        return tex

    def crop_repeat(self, vector, mapping, crop, depth):
        """The UV of a crop's 0..1 cell, per axis: wrapped (tile), ping-ponged (mirror) or left as it is (clip).
        A cropped image's clipped axis goes c + K floor(c), K = 1 / size + 1: 0 <= c < 1 stays, any other c lands
        outside the image once the crop mapping scales it into the crop rectangle. A placed image needs nothing
        there: its TEXTURE mapping already sends a c outside 0..1 out of the image."""
        axes = crop_axes(mapping)
        if axes == ('REPEAT', 'REPEAT'):
            frac = self.node("ShaderNodeVectorMath", depth + 1)
            frac.operation = 'FRACTION'
            self.links.new(vector, _in(frac, "Vector"))
            return _out(frac, "Vector")
        if crop.place and axes == ('CLIP', 'CLIP'):
            return vector
        sep = self.node("ShaderNodeSeparateXYZ", depth + 2)
        comb = self.node("ShaderNodeCombineXYZ", depth)
        self.links.new(vector, _in(sep, "Vector"))
        for axis, how, size in (("X", axes[0], crop.w), ("Y", axes[1], crop.h)):
            v = _out(sep, axis)
            if how == 'CLIP' and not crop.place:
                fl = self.node("ShaderNodeMath", depth + 1)
                fl.operation = 'FLOOR'
                self.links.new(v, fl.inputs[0])
                n = self.node("ShaderNodeMath", depth + 1)
                n.operation = 'MULTIPLY_ADD'
                self.links.new(fl.outputs[0], n.inputs[0])
                n.inputs[1].default_value = 1.0 / max(size, _EPS) + 1.0
                self.links.new(v, n.inputs[2])
                v = n.outputs[0]
            elif how != 'CLIP':
                n = self.node("ShaderNodeMath", depth + 1)
                self.links.new(v, n.inputs[0])
                if how == 'REPEAT':
                    n.operation = 'WRAP'
                    n.inputs[1].default_value, n.inputs[2].default_value = 1.0, 0.0
                else:
                    n.operation = 'PINGPONG'
                    n.inputs[1].default_value = 1.0
                v = n.outputs[0]
            self.links.new(v, _in(comb, axis))
        return _out(comb, "Vector")

    def output(self, o, out, depth):
        """A map's Output: inverted, then times level plus offset, then times amount."""
        if o.invert:
            out = self.invert(out, COLOR, depth)
        if o.level != 1.0 or o.offset != 0.0:
            n = self.node("ShaderNodeVectorMath", depth)
            n.operation = 'MULTIPLY_ADD'
            self.links.new(out, _in(n, "Vector"))
            _in(n, "Vector_001").default_value = (o.level,) * 3
            _in(n, "Vector_002").default_value = (o.offset,) * 3
            out = _out(n, "Vector")
        if o.amount != 1.0:
            out = self.scale(out, o.amount, depth)
        return out

    def scale(self, out, factor, depth):
        n = self.node("ShaderNodeVectorMath", depth)
        n.operation = 'SCALE'
        self.links.new(out, _in(n, "Vector"))
        _in(n, "Scale").default_value = factor
        return _out(n, "Vector")

    def invert(self, v, space, depth):
        if v is MISSING:
            return MISSING
        if not isinstance(v, bpy.types.NodeSocket):
            return tuple(1.0 - c for c in v) if space == COLOR else 1.0 - v
        if space == COLOR:
            n = self.node("ShaderNodeInvert", depth)
            self.links.new(v, _in(n, "Color"))
            return _out(n, "Color")
        n = self.node("ShaderNodeMath", depth)
        n.operation = 'SUBTRACT'
        n.inputs[0].default_value = 1.0
        self.links.new(v, n.inputs[1])
        return n.outputs[0]

    def mix_node(self, space, depth, blend='MIX'):
        """A Mix node of the space's data type: (node, A, B, Result)."""
        n = self.node("ShaderNodeMix", depth)
        n.data_type = 'RGBA' if space == COLOR else 'FLOAT'
        n.blend_type = blend
        kind = "Color" if space == COLOR else "Float"
        return n, _in(n, "A_" + kind), _in(n, "B_" + kind), _out(n, "Result_" + kind)

    def mix(self, n, space, depth):
        """A missing side gives the other one; a missing mask the mix amount."""
        va, vb = self.graph(n.a, space, depth + 1), self.graph(n.b, space, depth + 1)
        mask = self.graph(n.mask, FLOAT, depth + 1) if n.mask is not None else MISSING  # its node even when unused
        if va is MISSING or vb is MISSING:
            return vb if va is MISSING else va
        node, a, b, result = self.mix_node(space, depth)
        self.feed(a, va)
        self.feed(b, vb)
        self.feed(_in(node, "Factor_Float"), n.factor if mask is MISSING else mask)
        return result

    def multiply(self, n, space, depth):
        """A missing side gives the other one when that is a map, else MISSING (a slot amount times a lost map)."""
        va, vb = self.graph(n.a, space, depth + 1), self.graph(n.b, space, depth + 1)
        if va is MISSING or vb is MISSING:
            other = vb if va is MISSING else va
            return other if isinstance(other, bpy.types.NodeSocket) else MISSING
        if not isinstance(va, bpy.types.NodeSocket) and not isinstance(vb, bpy.types.NodeSocket):
            return tuple(x * y for x, y in zip(va, vb)) if space == COLOR else va * vb
        if space == COLOR:
            node, a, b, result = self.mix_node(space, depth, 'MULTIPLY')
            _in(node, "Factor_Float").default_value = 1.0
        else:
            node = self.node("ShaderNodeMath", depth)
            node.operation = 'MULTIPLY'
            a, b, result = node.inputs[0], node.inputs[1], node.outputs[0]
        self.feed(a, va)
        self.feed(b, vb)
        return result

    def color_correct(self, n, space, depth):
        steps = [n.hue % 1.0 != 0.0 or n.saturation != 1.0, n.brightness != 0.0 or n.contrast != 0.0,
                 n.gain != 1.0, n.gamma != 1.0]
        d = depth + sum(steps) - 1  # the first step's column; the input one further left
        v = self.graph(n.input, COLOR, d + 1)
        if v is MISSING:
            return MISSING
        if not any(steps):
            return v if space == COLOR or isinstance(v, bpy.types.NodeSocket) else _mean(v)
        v = self.socket(v, COLOR, d + 1)
        if steps[0]:
            h = self.node("ShaderNodeHueSaturation", d)
            _in(h, "Hue").default_value = (0.5 + n.hue) % 1.0
            _in(h, "Saturation").default_value = max(0.0, n.saturation)
            self.links.new(v, _in(h, "Color"))
            v, d = _out(h, "Color"), d - 1
        if steps[1]:
            bc = self.node("ShaderNodeBrightContrast", d)
            _in(bc, "Bright").default_value = n.brightness
            _in(bc, "Contrast").default_value = n.contrast
            self.links.new(v, _in(bc, "Color"))
            v, d = _out(bc, "Color"), d - 1
        if steps[2]:
            v, d = self.scale(v, n.gain, d), d - 1
        if steps[3]:
            g = self.node("ShaderNodeGamma", d)
            _in(g, "Gamma").default_value = 1.0 / n.gamma
            self.links.new(v, _in(g, "Color"))
            v = _out(g, "Color")
        return v

    def composite(self, n, space, depth):
        """Each layer over the ones below in the normal mode: a Mix by its opacity (times an image's alpha). A
        layer whose image is missing is left out."""
        result = MISSING
        for layer, opacity in n.layers:
            v = self.graph(layer, space, depth + 1)
            if v is MISSING:
                continue
            if result is MISSING and opacity >= 1.0:
                result = v
                continue
            node, a, b, out = self.mix_node(space, depth)
            self.feed(a, _as(0.0, space) if result is MISSING else result)
            self.feed(b, v)
            factor = _in(node, "Factor_Float")
            tex = self.texture_nodes.get(id(layer)) if isinstance(layer, tx.Image) and not layer.alpha else None
            if tex is not None and result is not MISSING:
                mul = self.node("ShaderNodeMath", depth + 1)
                mul.operation = 'MULTIPLY'
                self.links.new(_out(tex, "Alpha"), mul.inputs[0])
                mul.inputs[1].default_value = opacity
                self.links.new(mul.outputs[0], factor)
            else:
                factor.default_value = opacity
            result = out
        return result
