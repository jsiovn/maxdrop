# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of texture placement: mirror tiling, clip masks, a clipped normal map, a Checker's and a Noise's pattern."""
import math
import os
import shutil
import tempfile

import bpy
from mathutils import Vector

from .core import check, close, empty_scene
from .nodes import (
    _clip_axes_of, _clip_mask_input, _from, _image_of, _input, _meaned, _principled, _write_png, CLIP_LABEL,
)


_ONE_MIRROR = ("8 24 40 55 72 88 104 119 136 152 168 184 200 216 231 248 248 231 216 200 184 168 152 136 119 104 88 72 "
               "55 40 24 8")
# 3ds Max 2020 renderMap (scanline, filter off, Bitmap filtering none) of a 64 x 64 ramp, red 4 x its column, green
# 4 x its row from the top (bead maxdrop-em3.60): (label, Mapping keywords, crop (u, v, w, h, place) or None, render
# size, 'row' at y or 'col' at x, that index, the channel, its values; '-' black: outside the image)
_MIRROR_ROWS = (
    ("mirror U, tiling 1", dict(mirror=(True, False)), None, (32, 8), "row", 4, "R",
     _ONE_MIRROR),
    ("mirror U, tile off", dict(tile=(False, True), mirror=(True, False)), None, (32, 8), "row", 4, "R",
     _ONE_MIRROR),
    ("mirror U, tiling 0.5", dict(tiling=(0.5, 1.0), mirror=(True, False)), None, (32, 8), "row", 4, "R",
     "131 139 147 156 164 171 180 187 195 204 212 220 228 235 244 252 252 244 235 228 220 212 204 195 187 180 171 164 "
     "156 147 139 131"),
    ("mirror U, tiling 2", dict(tiling=(2.0, 1.0), mirror=(True, False)), None, (32, 8), "row", 4, "R",
     "239 208 176 144 112 80 48 16 16 48 80 112 144 176 208 239 239 208 176 144 112 80 48 16 16 48 80 112 144 176 208 "
     "239"),
    ("mirror U, offset 0.1", dict(offset=(0.1, 0.0), mirror=(True, False)), None, (32, 32), "row", 16, "R",
     "40 24 8 4 19 36 52 68 84 100 116 131 147 164 180 195 212 228 244 248 231 216 200 184 168 152 136 119 104 88 72 "
     "55"),
    ("mirror U, crop", dict(mirror=(True, False)), (0.25, 0.0, 0.5, 1.0, False), (32, 32), "row", 16, "R",
     "68 75 84 91 100 108 116 124 131 139 147 156 164 171 180 187 187 180 171 164 156 147 139 131 124 116 108 100 91 "
     "84 75 68"),
    ("mirror U, placed", dict(mirror=(True, False)), (0.25, 0.0, 0.5, 1.0, True), (32, 8), "row", 4, "R",
     "- - - - 16 48 80 112 144 176 208 239 - - - - - - - - 239 208 176 144 112 80 48 16 - - - -"),
    ("mirror both, along U", dict(mirror=(True, True)), None, (32, 32), "row", 16, "R",
     _ONE_MIRROR),
    ("mirror both, along V", dict(mirror=(True, True)), None, (32, 32), "col", 3, "G",
     "248 231 216 200 184 168 152 136 119 104 88 72 55 40 24 8 8 24 40 55 72 88 104 119 136 152 168 184 200 216 231 "
     "248"),
    ("mirror V", dict(mirror=(False, True)), None, (32, 32), "col", 3, "G",
     "248 231 216 200 184 168 152 136 119 104 88 72 55 40 24 8 8 24 40 55 72 88 104 119 136 152 168 184 200 216 231 "
     "248"),
    ("mirror V, along U", dict(mirror=(False, True)), None, (32, 32), "row", 16, "R",
     "4 12 19 28 36 44 52 60 68 75 84 91 100 108 116 124 131 139 147 156 164 171 180 187 195 204 212 220 228 235 244 "
     "252"),
    ("mirror U, V clipped at tiling 2, along U", dict(tiling=(1.0, 2.0), tile=(True, False), mirror=(True, False)),
     None, (32, 32), "row", 16, "R", _ONE_MIRROR),
    ("mirror U, V clipped at tiling 2, along V", dict(tiling=(1.0, 2.0), tile=(True, False), mirror=(True, False)),
     None, (32, 32), "col", 3, "G",
     "- - - - - - - - 8 24 40 55 72 88 104 119 136 152 168 184 200 216 231 248 - - - - - - - -"),
    ("crop, mirror U, V clipped at tiling 2, along U",
     dict(tiling=(1.0, 2.0), tile=(True, False), mirror=(True, False)), (0.25, 0.25, 0.5, 0.5, False), (32, 32),
     "row", 16, "R",
     "68 75 84 91 100 108 116 124 131 139 147 156 164 171 180 187 187 180 171 164 156 147 139 131 124 116 108 100 91 "
     "84 75 68"),
    ("crop, mirror U, V clipped at tiling 2, along V",
     dict(tiling=(1.0, 2.0), tile=(True, False), mirror=(True, False)), (0.25, 0.25, 0.5, 0.5, False), (32, 32),
     "col", 3, "G",
     "- - - - - - - - 68 75 84 91 100 108 116 124 131 139 147 156 164 171 180 187 - - - - - - - -"),
    ("mirror U, W 90, along V", dict(angle=(0.0, 0.0, math.pi / 2), mirror=(True, False)), None, (16, 16), "col", 8,
     "R", "16 48 80 112 144 176 208 239 239 208 176 144 112 80 48 16"),
    ("mirror U, W 90, along U", dict(angle=(0.0, 0.0, math.pi / 2), mirror=(True, False)), None, (16, 16), "row", 8,
     "G", "248 231 216 200 184 168 152 136 119 104 88 72 55 40 24 8"),
)


def _pingpong(a, b):
    """Blender's Math PINGPONG (pingpongf)."""
    if not b:
        return 0.0
    t = (a - b) / (b * 2)
    return abs((t - math.floor(t)) * b * 2 - b)


def _sample_vector(socket, uv):
    """The vector a node tree gives an input at the UV uv, as Blender evaluates the node kinds the texture placement
    uses (Texture Coordinate / UV Map, Mapping, Vector Math, Separate / Combine XYZ, Math)."""
    from mathutils import Euler
    if not socket.is_linked:
        return None
    link = socket.links[0]
    n, out = link.from_node, link.from_socket.identifier
    if n.bl_idname in ("ShaderNodeTexCoord", "ShaderNodeUVMap"):
        return Vector((uv[0], uv[1], 0.0))
    if n.bl_idname == "ShaderNodeSeparateXYZ":
        return _sample_vector(n.inputs["Vector"], uv)["XYZ".index(out)]
    if n.bl_idname == "ShaderNodeCombineXYZ":
        return Vector([_sample_value(n.inputs[a], uv) for a in "XYZ"])
    if n.bl_idname == "ShaderNodeMath":
        a, b, c = (_sample_value(n.inputs[i], uv) for i in range(3))
        return {'PINGPONG': lambda: _pingpong(a, b), 'FLOOR': lambda: math.floor(a),
                'WRAP': lambda: a - (b - c) * math.floor((a - c) / (b - c)), 'MULTIPLY_ADD': lambda: a * b + c,
                'COMPARE': lambda: float(abs(a - b) <= max(c, 1e-5)), 'MULTIPLY': lambda: a * b,
                'ADD': lambda: a + b,
                }[n.operation]()
    v = _sample_vector(n.inputs["Vector"], uv)
    if n.bl_idname == "ShaderNodeVectorMath":
        if n.operation == 'MULTIPLY':
            return Vector([x * f for x, f in zip(v, _input(n, "Vector_001").default_value)])
        if n.operation == 'FRACTION':
            return Vector([x - math.floor(x) for x in v])
    if n.bl_idname == "ShaderNodeMapping":
        loc, scale = Vector(n.inputs["Location"].default_value), Vector(n.inputs["Scale"].default_value)
        rot = Euler(n.inputs["Rotation"].default_value, 'XYZ').to_matrix()
        if n.vector_type == 'POINT':
            return loc + rot @ Vector([x * s for x, s in zip(v, scale)])
        if n.vector_type == 'TEXTURE':
            return Vector([x / s for x, s in zip(rot.transposed() @ (v - loc), scale)])
    raise AssertionError("not evaluated: %s %s" % (n.bl_idname, getattr(n, "operation", "")))


def _sample_value(socket, uv):
    return _sample_vector(socket, uv) if socket.is_linked else socket.default_value


def _sample_image(tex, uv, mask=None):
    """The image coordinate (x, y) an Image Texture node reads at uv, its extension applied; None outside a CLIP
    image or where its clip mask (the socket mask, _image_of) is 0."""
    if mask is not None and _sample_value(mask, uv) < 0.5:
        return None
    v = _sample_vector(tex.inputs["Vector"], uv)
    v = Vector((uv[0], uv[1], 0.0)) if v is None else v
    xy = []
    for x in v[:2]:
        if tex.extension == 'REPEAT':
            x -= math.floor(x)
        elif tex.extension == 'MIRROR':
            x = _pingpong(x, 1.0)
        elif tex.extension == 'EXTEND':
            x = min(max(x, 0.0), 1.0)
        elif not 0.0 <= x <= 1.0:
            return None
        xy.append(x)
    return xy


def check_builder_mirror():
    """MaterialBuilder on hand-made IRs (bead maxdrop-em3.60): a mirrored axis shows two copies per tile, the second
    mirrored (ping-pong of twice the placed coordinate), mirror winning over tile, with and without a crop; the
    nodes evaluated at 3ds Max's sample points give the image coordinates 3ds Max rendered; one extension where both
    axes agree, per-axis nodes where they differ."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-builder-mirror-")
    try:
        png = os.path.join(scratch, "shared.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        builder = build_materials.MaterialBuilder()

        def tex_mask(name, mapping, crop=None):
            ir = cm.MaterialIR(30, name, "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
            img = tx.Image(1, "shared.png", "shared.png", "", found, mapping=mapping, crop=crop)
            ir.textures = {"base_color": tx.TextureGraphIR(img, tx.COLOR)}
            return _image_of(_principled(builder.make(ir)).inputs["Base Color"])

        def tex_of(name, mapping, crop=None):
            return tex_mask(name, mapping, crop)[0]

        for label, kw, crop, (w, h), sweep, fixed, channel, values in _MIRROR_ROWS:
            tex, mask = tex_mask("Mirror " + label, tx.Mapping(**kw), tx.Crop(*crop) if crop else None)
            bad = []
            for i, value in enumerate(values.split()):
                x, y = (i, fixed) if sweep == "row" else (fixed, i)
                got = _sample_image(tex, ((x + 0.5) / w, 1.0 - (y + 0.5) / h), mask)
                if value == "-":
                    if got is not None:
                        bad.append((i, value, got))
                    continue
                want = (int(value) / 4 + 0.5) / 64
                want = want if channel == "R" else 1.0 - want
                if got is None or abs(got[0 if channel == "R" else 1] - want) > 1.0 / 64:
                    bad.append((i, value, got))
            check("builder mirror: %s: the nodes read the image where 3ds Max rendered it" % label, not bad,
                  "%s %s" % (tex.extension, bad[:4]))

        def double(node, factor):
            return (node is not None and node.bl_idname == "ShaderNodeVectorMath" and node.operation == 'MULTIPLY'
                    and close(list(_input(node, "Vector_001").default_value), factor, 1e-6))

        tex = tex_of("MirrorTileBoth", tx.Mapping(tile=(True, True), mirror=(True, True)))
        mul = _from(tex.inputs["Vector"])
        check("builder mirror: mirror and tile on both axes, no placement: UV -> times (2, 2, 1) -> image MIRROR",
              tex.extension == 'MIRROR' and double(mul, [2.0, 2.0, 1.0])
              and _from(mul.inputs["Vector"]).bl_idname == "ShaderNodeTexCoord",
              "%s %s" % (tex.extension, mul and mul.bl_idname))

        tex = tex_of("MirrorUTileV", tx.Mapping(tile=(True, True), mirror=(True, False)))
        comb = _from(tex.inputs["Vector"])
        x, y = (_from(comb.inputs[a]) for a in ("X", "Y")) if comb is not None else (None, None)
        sep = x and _from(x.inputs[0])
        check("builder mirror: mirror U, tile V: times (2, 1, 1) -> ping-pong X, wrap Y -> image EXTEND (REPEAT "
              "would bleed the opposite edge into the mirror line)",
              tex.extension == 'EXTEND' and comb.bl_idname == "ShaderNodeCombineXYZ" and x.operation == 'PINGPONG'
              and y.operation == 'WRAP' and _from(y.inputs[0]) == sep and sep.bl_idname == "ShaderNodeSeparateXYZ"
              and double(_from(sep.inputs["Vector"]), [2.0, 1.0, 1.0]),
              "%s %s" % (tex.extension, comb and comb.bl_idname))

        tex = tex_of("TileUOnly", tx.Mapping(tile=(True, False)))
        comb = _from(tex.inputs["Vector"])
        x, y = (_from(comb.inputs[a]) for a in ("X", "Y")) if comb is not None else (None, None)
        check("builder mirror: tile U only: wrap X, Y straight through -> image EXTEND, Y clipped by a mask (CLIP "
              "would fade the border half-texel at every tile line)",
              tex.extension == 'EXTEND' and x is not None and x.operation == 'WRAP'
              and y.bl_idname == "ShaderNodeSeparateXYZ" and _clip_axes_of(tex) == ["Y"],
              "%s %s %s" % (tex.extension, comb and comb.bl_idname, _clip_axes_of(tex)))
        tex = tex_of("MirrorVClipU", tx.Mapping(tile=(False, True), mirror=(False, True)))
        check("builder mirror: mirror V, U clipped: image EXTEND, X clipped by a mask",
              tex.extension == 'EXTEND' and _clip_axes_of(tex) == ["X"], "%s %s" % (tex.extension,
                                                                                    _clip_axes_of(tex)))

        tex = tex_of("TileBoth", tx.Mapping())
        check("builder mirror: tile both, no placement: no vector, image REPEAT",
              tex.extension == 'REPEAT' and not tex.inputs["Vector"].is_linked, tex.extension)
        tex, mask = tex_mask("TileNone", tx.Mapping(tile=(False, False)))
        check("builder mirror: tile off both, no placement: no vector, image CLIP, no mask",
              tex.extension == 'CLIP' and not tex.inputs["Vector"].is_linked and mask is None, tex.extension)
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_clip_mask():
    """MaterialBuilder on hand-made IRs (bead maxdrop-em3.112): an image that repeats on one axis and clips on the
    other is drawn EXTEND with a clip mask, which every output of its Image Texture goes through (Color and Alpha:
    an alpha image, a Composite layer's alpha), one Clip node per output however many inputs read it."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-builder-clip-")
    try:
        png = os.path.join(scratch, "shared.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        builder = build_materials.MaterialBuilder()
        mixed = tx.Mapping(tiling=(2.0, 2.0), tile=(True, False))

        def clips_of(tex):
            """{output name: [the nodes its links go to]} of the linked outputs."""
            return {o.name: [link.to_node for link in o.links] for o in tex.outputs if o.is_linked}

        alpha = tx.Image(1, "shared.png", "shared.png", "", found, colorspace=tx.NON_COLOR, alpha=True, mapping=mixed)
        ir = cm.MaterialIR(50, "ClipAlpha", "test", alpha=cm.Input(1.0, cm.MapRef(1)))
        ir.textures = {"alpha": tx.TextureGraphIR(alpha, tx.DATA)}
        m = builder.make(ir)
        tex = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage")
        outs = clips_of(tex)
        check("builder clip mask: an alpha image tiled in U, clipped in V: EXTEND, its Alpha only through a Clip node "
              "masking V", tex.extension == 'EXTEND' and list(outs) == ["Alpha"]
              and all(n.label == CLIP_LABEL for n in outs["Alpha"]) and _clip_axes_of(tex) == ["Y"], str(outs))

        top = tx.Image(2, "shared.png", "shared.png", "", found, mapping=mixed)
        bottom = tx.Image(3, "shared.png", "shared.png", "", found)
        layered = tx.Composite((tx.CompositeLayer(bottom), tx.CompositeLayer(top, 0.5)))
        ir = cm.MaterialIR(51, "ClipLayer", "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)),
                           emission_color=cm.Input((0.0, 0.0, 0.0), cm.MapRef(2)))
        ir.textures = {"base_color": tx.TextureGraphIR(layered, tx.COLOR),
                       "emission_color": tx.TextureGraphIR(top, tx.COLOR)}
        m = builder.make(ir)
        texes = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.inputs["Vector"].is_linked]
        tex = texes[0] if len(texes) == 1 else None
        outs = clips_of(tex) if tex is not None else {}
        clip_nodes = [n for n in m.node_tree.nodes if n.label == CLIP_LABEL]
        check("builder clip mask: a Composite layer and the emission read one mixed-axis image: its Color and its "
              "Alpha (the layer's factor) each through one Clip node, the same mask",
              tex is not None and sorted(outs) == ["Alpha", "Color"]
              and all(n.label == CLIP_LABEL and n in clip_nodes for ns in outs.values() for n in ns)
              and len(clip_nodes) == 2 and len({_from(_clip_mask_input(n)) for n in clip_nodes}) == 1
              and _clip_axes_of(tex) == ["Y"],
              "%d textures, %s, %d Clip nodes" % (len(texes), sorted(outs), len(clip_nodes)))
        for name in ("Base Color", "Emission Color"):
            check("builder clip mask: %s linked" % name, _principled(m).inputs[name].is_linked)
        check("builder clip mask: the tests' Clip label is the builder's",
              CLIP_LABEL == build_materials.CLIP_LABEL, build_materials.CLIP_LABEL)

        rough = tx.Image(4, "shared.png", "shared.png", "", found, colorspace=tx.NON_COLOR, mapping=mixed)
        ir = cm.MaterialIR(52, "ClipData", "test", roughness=cm.Input(0.5, cm.MapRef(1)))
        ir.textures = {"roughness": tx.TextureGraphIR(rough, tx.DATA)}
        m = builder.make(ir)
        tex = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage")
        outs = clips_of(tex)
        mean = _meaned(_principled(m).inputs["Roughness"])
        check("builder clip mask: a data map (roughness) over a mixed-axis image: the mean of its masked Color",
              list(outs) == ["Color"] and all(n.label == CLIP_LABEL for n in outs["Color"])
              and mean is not None and mean.label == CLIP_LABEL and _from(mean.inputs[0]) == tex,
              "%s %s" % (outs, getattr(mean, "bl_idname", None)))

        lost = tx.Image(5, "nothere.png", "C:\\x\\nothere.png", "", None, mapping=mixed)
        ir = cm.MaterialIR(53, "ClipLost", "test", base_color=cm.Input((0.1, 0.2, 0.3), cm.MapRef(1)))
        ir.textures = {"base_color": tx.TextureGraphIR(lost, tx.COLOR)}
        m = builder.make(ir)
        check("builder clip mask: a missing image gets no mask nodes",
              not any(n.bl_idname == "ShaderNodeMath" and n.operation == 'COMPARE' for n in m.node_tree.nodes)
              and not any(n.label == CLIP_LABEL for n in m.node_tree.nodes))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_clipped_normal():
    """MaterialBuilder on hand-made IRs (bead maxdrop-em3.137): a normal map over a clipped image reads the image
    black outside it, as 3ds Max renders it (V-Ray 5.2 and scanline gave the pixels of a black normal image there):
    the Normal Map node's Color comes from the image's Color through its Clip node (one axis clips, or a placed crop)
    or straight from the image under the CLIP extension (both axes clip), never mixed toward a flat (0.5, 0.5, 1)."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-builder-clipped-normal-")
    try:
        png = os.path.join(scratch, "shared.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        builder = build_materials.MaterialBuilder()
        cases = (("U clips, V tiles", tx.Mapping(tiling=(2.0, 2.0), tile=(False, True)), None, 'EXTEND', ["X"]),
                 ("both axes clip", tx.Mapping(tiling=(2.0, 2.0), tile=(False, False)), None, 'CLIP', []),
                 ("a placed crop", tx.Mapping(), tx.Crop(0.25, 0.25, 0.5, 0.5, place=True), 'EXTEND', ["X", "Y"]))
        for i, (label, mapping, crop, ext, axes) in enumerate(cases):
            img = tx.Image(i + 1, "shared.png", "shared.png", "", found, colorspace=tx.NON_COLOR, mapping=mapping,
                           crop=crop)
            ir = cm.MaterialIR(60 + i, "ClippedNormal%d" % i, "test")
            ir.normal = cm.MapRef(1)
            ir.textures = {"normal": tx.TextureGraphIR(tx.NormalMap(img), tx.NORMAL)}
            m = builder.make(ir)
            check("builder clipped normal (%s): material built" % label, m is not None)
            if m is None:
                continue
            tex = next((n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"), None)
            nm = _from(_principled(m).inputs["Normal"])
            src = nm.inputs["Color"].links[0] if nm is not None and nm.bl_idname == "ShaderNodeNormalMap" \
                and nm.inputs["Color"].is_linked else None
            if axes:
                clip = src.from_node if src is not None else None
                fed = clip is not None and clip.label == CLIP_LABEL and clip.inputs[0].is_linked \
                    and clip.inputs[0].links[0].from_node == tex and clip.inputs[0].links[0].from_socket.name == "Color"
            else:
                fed = src is not None and src.from_node == tex and src.from_socket.name == "Color"
            kinds = sorted({n.bl_idname for n in m.node_tree.nodes if n.bl_idname in ("ShaderNodeMix", "ShaderNodeRGB",
                                                                                     "ShaderNodeMixRGB")})
            check("builder clipped normal (%s): the image %s, the Normal Map reads its Color %s, black outside, "
                  "nothing mixes toward flat" % (label, ext, "through the Clip node" if axes else "straight"),
                  tex is not None and tex.extension == ext and _clip_axes_of(tex) == axes and fed and not kinds
                  and not nm.inputs["Strength"].is_linked,
                  "%s %s %s %s" % (getattr(tex, "extension", None), _clip_axes_of(tex) if tex else None,
                                   getattr(getattr(src, "from_node", None), "bl_idname", None), kinds))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_checker():
    """MaterialBuilder on hand-made IRs (bead maxdrop-o53.1.4): a Checker leaf is Math nodes on the placed UV that the
    node evaluator reads as texmaps.checker_value on a 12 x 12 grid of UVs (tiling 2 x 3; tiled, offset and turned;
    on UV channel 2), 0 or 1 and both; the Mix between the two colors by it; in a bump input the Bump's height."""
    from maxdrop.build import materials as build_materials
    from maxdrop.build.materials.sockets import uv_layer_name
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    empty_scene()
    builder = build_materials.MaterialBuilder()
    red, blue, grid = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), 12

    def sampled(socket, pattern):
        """The (i, j, node value, checker_value) where they differ on the grid, and the values the nodes gave."""
        bad, seen = [], set()
        for i in range(grid):
            for j in range(grid):
                uv = ((i + 0.5) / grid, (j + 0.5) / grid)
                got, want = _sample_value(socket, uv), tx.checker_value(pattern, *uv)
                seen.add(got)
                if abs(got - want) > 1e-6:
                    bad.append((i, j, got, want))
        return bad, seen

    try:
        cases = (("tiling 2 x 3", tx.Mapping(tiling=(2.0, 3.0))),
                 ("tiled, offset and turned", tx.Mapping(tiling=(1.5, 1.0), offset=(0.1, -0.2),
                                                         angle=(0.0, 0.0, math.radians(30.0)))),
                 ("UV channel 2", tx.Mapping(channel=2)))
        for k, (label, mapping) in enumerate(cases):
            pattern = tx.Checker(mapping)
            ir = cm.MaterialIR(80 + k, "Checker%d" % k, "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
            ir.textures = {"base_color": tx.TextureGraphIR(
                tx.Mix(tx.Constant(red), tx.Constant(blue), 0.0, pattern), tx.COLOR)}
            m = builder.make(ir)
            mix = _from(_principled(m).inputs["Base Color"])
            ok = mix is not None and mix.bl_idname == "ShaderNodeMix" and mix.data_type == 'RGBA'
            check("builder checker (%s): a Mix of the two colors drives the base color" % label,
                  ok and close(list(_input(mix, "A_Color").default_value)[:3], list(red), 1e-6)
                  and close(list(_input(mix, "B_Color").default_value)[:3], list(blue), 1e-6),
                  getattr(mix, "bl_idname", None))
            if not ok:
                continue
            factor = _input(mix, "Factor_Float")
            bad, seen = sampled(factor, pattern)
            check("builder checker (%s): the nodes give the pattern texmaps.checker_value gives, 0 and 1" % label,
                  not bad and seen == {0.0, 1.0}, "%s %s" % (bad[:4], sorted(seen)))
            if mapping.channel != 1:
                uvs = [(n.bl_idname, getattr(n, "uv_map", "")) for n in m.node_tree.nodes
                       if n.bl_idname in ("ShaderNodeUVMap", "ShaderNodeTexCoord")]
                check("builder checker (%s): on that UV layer" % label,
                      uvs == [("ShaderNodeUVMap", uv_layer_name(2))], str(uvs))
        pattern = tx.Checker(tx.Mapping(tiling=(2.0, 3.0)))
        ir = cm.MaterialIR(90, "CheckerBump", "test")
        ir.bump = cm.MapRef(1)
        ir.textures = {"bump": tx.TextureGraphIR(tx.Bump(pattern, 0.5), tx.BUMP)}
        bump = _from(_principled(builder.make(ir)).inputs["Normal"])
        ok = bump is not None and bump.bl_idname == "ShaderNodeBump"
        bad, seen = sampled(_input(bump, "Height"), pattern) if ok else ([None], set())
        check("builder checker (bump): a Bump whose height is the pattern",
              ok and not bad and seen == {0.0, 1.0} and abs(_input(bump, "Strength").default_value - 0.5) < 1e-6,
              "%s %s" % (getattr(bump, "bl_idname", None), bad[:4]))
    finally:
        empty_scene()


def check_builder_noise():
    """MaterialBuilder on hand-made IRs (bead maxdrop-o53.1.5): a Noise leaf is the object's coordinates through a
    POINT Mapping node of texmaps.noise_placement, a Noise Texture (fBm, normalized, Scale 1, Detail
    texmaps.noise_detail, Roughness 0.5, Lacunarity 2; 4D with W the phase), for turbulence |2 fac - 1|, then a
    clamped Map Range from the thresholds: the Mix factor between the two colors; in a bump input the Bump's
    height. The committed tests render nothing: the structure and the copied numbers are checked."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    empty_scene()
    builder = build_materials.MaterialBuilder()
    red, blue = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)

    def chain(socket, noise, label):
        """Check the nodes from a Map Range feeding socket back to the Texture Coordinate node."""
        ramp = _from(socket)
        ok = ramp is not None and ramp.bl_idname == "ShaderNodeMapRange"
        check("builder noise (%s): a clamped linear Map Range from the thresholds" % label,
              ok and ramp.clamp and ramp.interpolation_type == 'LINEAR'
              and close([_input(ramp, k).default_value for k in ("From Min", "From Max", "To Min", "To Max")],
                        [noise.low, noise.high, 0.0, 1.0], 1e-6), getattr(ramp, "bl_idname", None))
        if not ok:
            return
        node = _from(_input(ramp, "Value"))
        if noise.kind == tx.TURBULENCE:
            ok = node is not None and node.bl_idname == "ShaderNodeMath" and node.operation == 'ABSOLUTE'
            fold = _from(_input(node, "Value")) if ok else None
            ok = ok and fold is not None and fold.operation == 'MULTIPLY_ADD' and close(
                [_input(fold, "Value_001").default_value, _input(fold, "Value_002").default_value], [2.0, -1.0], 1e-6)
            check("builder noise (%s): the turbulence folded, |2 fac - 1|" % label, ok)
            if not ok:
                return
            node = _from(_input(fold, "Value"))
        ok = node is not None and node.bl_idname == "ShaderNodeTexNoise"
        want = [noise.phase, 1.0, tx.noise_detail(noise), 0.5, 2.0, 0.0]
        check("builder noise (%s): a Noise Texture, fBm, normalized, its inputs set" % label,
              ok and node.noise_type == 'FBM' and node.normalize
              and node.noise_dimensions == ('4D' if noise.phase else '3D')
              and close([_input(node, k).default_value for k in ("W", "Scale", "Detail", "Roughness", "Lacunarity",
                                                                 "Distortion")], want, 1e-6),
              getattr(node, "bl_idname", None))
        if not ok:
            return
        mapping = _from(_input(node, "Vector"))
        location, rotation, scale = tx.noise_placement(noise)
        ok = mapping is not None and mapping.bl_idname == "ShaderNodeMapping" and mapping.vector_type == 'POINT'
        check("builder noise (%s): a POINT Mapping node of texmaps.noise_placement" % label,
              ok and close(list(_input(mapping, "Location").default_value), list(location), 1e-6)
              and close(list(_input(mapping, "Rotation").default_value), list(rotation), 1e-6)
              and close(list(_input(mapping, "Scale").default_value), list(scale), 1e-5),
              getattr(mapping, "bl_idname", None))
        if not ok:
            return
        link = _input(mapping, "Vector").links[0] if _input(mapping, "Vector").is_linked else None
        check("builder noise (%s): on the object's coordinates" % label,
              link is not None and link.from_node.bl_idname == "ShaderNodeTexCoord"
              and link.from_socket.identifier == "Object")

    try:
        coords = tx.Coordinates(offset=(0.1, 0.0, -0.2), tiling=(2.0, 1.0, 0.5), angle=(0.0, 0.0, math.radians(30.0)))
        cases = (("regular, size 0.25 m", tx.Noise(size=0.25)),
                 ("fractal, placed, phase", tx.Noise(coords, 0.5, 1.5, 4.0, 0.2, 0.7, tx.FRACTAL)),
                 ("turbulence", tx.Noise(size=0.1, levels=2.5, kind=tx.TURBULENCE)))
        for k, (label, noise) in enumerate(cases):
            ir = cm.MaterialIR(100 + k, "Noise%d" % k, "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
            ir.textures = {"base_color": tx.TextureGraphIR(
                tx.Mix(tx.Constant(red), tx.Constant(blue), 0.0, noise), tx.COLOR, True)}
            mix = _from(_principled(builder.make(ir)).inputs["Base Color"])
            ok = mix is not None and mix.bl_idname == "ShaderNodeMix" and mix.data_type == 'RGBA'
            check("builder noise (%s): a Mix of the two colors drives the base color" % label,
                  ok and close(list(_input(mix, "A_Color").default_value)[:3], list(red), 1e-6)
                  and close(list(_input(mix, "B_Color").default_value)[:3], list(blue), 1e-6),
                  getattr(mix, "bl_idname", None))
            if ok:
                chain(_input(mix, "Factor_Float"), noise, label)
        noise = tx.Noise(size=0.25)
        ir = cm.MaterialIR(110, "NoiseBump", "test")
        ir.bump = cm.MapRef(1)
        ir.textures = {"bump": tx.TextureGraphIR(tx.Bump(noise, 0.5), tx.BUMP, True)}
        bump = _from(_principled(builder.make(ir)).inputs["Normal"])
        ok = bump is not None and bump.bl_idname == "ShaderNodeBump"
        check("builder noise (bump): a Bump of strength 0.5", ok and abs(_input(bump, "Strength").default_value - 0.5)
              < 1e-6, getattr(bump, "bl_idname", None))
        if ok:
            chain(_input(bump, "Height"), noise, "bump")
    finally:
        empty_scene()
