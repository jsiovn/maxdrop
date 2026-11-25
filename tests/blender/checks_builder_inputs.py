# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of the material builder's inputs: Fresnel off, mono maps, negative constants, mask means,
saturation, the World shown as the sky and in a render."""
import dataclasses
import math
import os
import shutil
import tempfile

import bpy

from .core import check, close, empty_scene
from .tables import MIRROR_LABEL
from .nodes import (
    _bsdfs, _color_into_float, _from, _input, _meaned, _principled, _reaches_image, _refracting, _shaders, _thin,
    _weight_mix, _write_png,
)
from .checks_materials import check_specular


def check_builder_fresnel_off():
    """A weight without Fresnel (bead maxdrop-em3.120, VRayMtl Fresnel off): between 0 and 1, or a converted map, a
    Mix Shader by the weight from the BSDF at Specular IOR Level 0 to its copy as a metal (white unless the IR's
    mirror color tints it); 0, a metal and a
    reflection map that did not convert or whose image is not found (no node: its swatch) keep em3.119's drawing;
    Fresnel on keeps the twin. Refracting glass (bead maxdrop-6n0.7.2): the mirror's first shader refracts without
    reflecting (em3.135's refraction twin, the weight 1 under total internal reflection) and the filled BSDF feeds
    nothing; a black reflection is the twin at 0, a white one the lone BSDF; a coat keeps the mirror over the BSDF.
    A tinted mirror color (bead maxdrop-6n0.6.16) is the copy's Base Color, over the BSDF and over refracting glass."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    empty_scene()
    builder = build_materials.MaterialBuilder()
    facing = tx.TextureGraphIR(tx.Mix(tx.Constant((0.0,) * 3), tx.Constant((1.0,) * 3), 0.0,
                                      tx.Facing(tx.PERPENDICULAR)), tx.COLOR)
    glass = dict(specular=cm.Input(0.2), transmission=cm.Input(1.0))
    for name, kw, textures, drawing, level in (
            ("GlassOff", dict(glass, roughness=cm.Input(0.2)), {}, "mirror", 0.0),
            ("GlassOffGrey", dict(glass, base_color=cm.Input((0.25, 0.25, 0.25))), {}, "mirror", 0.0),
            ("HalfGlassOff", dict(glass, transmission=cm.Input(0.5)), {}, "mirror", 0.0),
            ("GlassOffMap", dict(glass, specular=cm.Input(0.0, cm.MapRef(1))), {"specular": facing}, "mirror", 0.0),
            ("ThinGlassOff", dict(glass, thin_walled=True), {}, "mirror", 0.0),
            ("GlassOffCoat", dict(glass, coat_weight=0.5), {}, "mirror", 0.0),
            ("GlassOffBlack", dict(glass, specular=cm.Input(0.0)), {}, "twin", 0.5),
            ("GlassOffWhite", dict(glass, specular=cm.Input(1.0)), {}, "lone", 0.5),
            ("GlassOffUnconverted", dict(glass, specular=cm.Input(0.6, cm.MapRef(1))), {}, "twin", 0.5),
            ("GlassOffTinted", dict(glass, mirror_color=(1.0, 0.5, 0.25)), {}, "mirror", 0.0),
            ("Tinted", dict(specular=cm.Input(0.6), base_color=cm.Input((0.2, 0.3, 0.8)),
                            mirror_color=(1.0, 0.5, 0.25)), {}, "mirror", 0.0),
            ("Dim", dict(specular=cm.Input(0.2), roughness=cm.Input(0.3)), {}, "mirror", 0.0),
            ("DimRed", dict(specular=cm.Input(0.2), base_color=cm.Input((1.0, 0.0, 0.0), cm.MapRef(1)),
                            metallic=cm.Input(0.2, cm.MapRef(1))),
             {"base_color": facing, "metallic": tx.TextureGraphIR(tx.Mix(tx.Constant(0.0), tx.Constant(0.5), 0.0,
                                                                          tx.Facing(tx.PERPENDICULAR)), tx.DATA)},
             "mirror", 0.0),
            ("Falloff", dict(specular=cm.Input(0.0, cm.MapRef(1))), {"specular": facing}, "mirror", 0.0),
            ("None", dict(specular=cm.Input(0.0)), {}, "lone", 0.0),
            ("Metal", dict(specular=cm.Input(0.4), metallic=cm.Input(1.0)), {}, "lone", 0.2),
            ("Unconverted", dict(specular=cm.Input(0.6, cm.MapRef(1))), {}, "twin", 0.5),
            ("LostImage", dict(specular=cm.Input(0.8, cm.MapRef(2))),
             {"specular": tx.TextureGraphIR(tx.Image(2, "nothere.png", "C:\\x\\nothere.png", "", None), tx.COLOR)},
             "twin", 0.5),
            ("On", dict(specular=cm.Input(0.2), fresnel=True), {}, "twin", 0.5)):
        ir = cm.MaterialIR(80, name, "test", **{"fresnel": False, **kw})
        ir.textures = textures
        m = builder.make(ir)
        p = _principled(m) if m is not None else None
        mix = _weight_mix(p) if p is not None else None
        level_ok = p is not None and abs(p.inputs["Specular IOR Level"].default_value - level) < 1e-6
        second = _from(mix.inputs[2]) if mix is not None else None
        got = "lone" if mix is None else "mirror" if getattr(second, "label", "") == MIRROR_LABEL else "twin"
        check("fresnel off: %s: %s, Specular IOR Level %.1f" % (name, drawing, level), level_ok and got == drawing,
              "%s, level %r" % (got, None if p is None else p.inputs["Specular IOR Level"].default_value))
        if name in ("Tinted", "GlassOffTinted") and got == "mirror":
            check("fresnel off: %s: the mirror's Base Color is the IR's mirror color, the BSDF's the base" % name,
                  close(list(second.inputs["Base Color"].default_value)[:3], [1.0, 0.5, 0.25], 1e-6)
                  and close(list(p.inputs["Base Color"].default_value)[:3], list(ir.base_color.value), 1e-6))
        if name == "DimRed" and got == "mirror":
            check("fresnel off: DimRed: the source's Base Color and Metallic are linked (the copy's are not)",
                  p.inputs["Base Color"].is_linked and p.inputs["Metallic"].is_linked)
        if p is not None and mix is not None:
            check_specular("fresnel off: " + name, p, ir, name != "LostImage")
            out = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
            check("fresnel off: %s: the surface is the Mix Shader" % name, _from(out.inputs["Surface"]) == mix)
        if name.startswith(("Glass", "HalfGlass", "ThinGlass")) and drawing == "mirror" and p is not None:
            refracts = name != "GlassOffCoat"
            check("fresnel off: %s: %s" % (name, "the BSDF feeds nothing, the refraction twin is below the mirror"
                                           if refracts else "the mirror is over the BSDF (a coat: no twin)"),
                  _refracting(p) == refracts and p.outputs["BSDF"].is_linked != refracts)
        if name == "ThinGlassOff" and p is not None:
            check("fresnel off: ThinGlassOff: drawn as a thin wall where Blender has one",
                  _thin(p) == ("Thin Wall" in p.inputs))
    base = cm.MaterialIR(81, "OffBase", "test", specular=cm.Input(1.0))
    base.layers = [cm.Layer(cm.MaterialIR(82, "OffGlassTop", "test", fresnel=False, **glass), 0.5)]
    m = builder.make(base)
    bsdfs, shaders = _bsdfs(m), _shaders(m)
    under = _weight_mix(bsdfs[1]) if len(bsdfs) == 2 else None
    layer_mix = shaders[0] if len(shaders) == 1 else None
    check("fresnel off: a glass layer over a base: the layer's mirror into the layer's Mix Shader",
          under is not None and layer_mix is not None and _weight_mix(bsdfs[0]) is None
          and _from(layer_mix.inputs[1]) == bsdfs[0] and _from(layer_mix.inputs[2]) == under,
          "%d BSDFs, %d shaders" % (len(bsdfs), len(shaders)))
    if under is not None:
        check_specular("fresnel off: the glass layer", bsdfs[1], base.layers[0].ir, True)
    base = cm.MaterialIR(83, "OffGlassBase", "test", fresnel=False, roughness=cm.Input(0.1), **glass)
    base.layers = [cm.Layer(cm.MaterialIR(84, "OffGlassTop", "test", fresnel=False, roughness=cm.Input(0.3),
                                          **glass), 0.5)]
    m = builder.make(base)
    bsdfs, shaders = _bsdfs(m), _shaders(m)
    mixes = [_weight_mix(b) for b in bsdfs]
    layer_mix = shaders[0] if len(shaders) == 1 else None
    check("fresnel off: a glass layer over a glass base: each BSDF's own mirror, the base's below the layer's",
          len(bsdfs) == 2 and None not in mixes and mixes[0] != mixes[1] and layer_mix is not None
          and _from(layer_mix.inputs[1]) == mixes[0] and _from(layer_mix.inputs[2]) == mixes[1],
          "%d BSDFs, %d shaders" % (len(bsdfs), len(shaders)))
    if len(bsdfs) == 2 and None not in mixes:
        check_specular("fresnel off: the glass base", bsdfs[0], base, True)
        check_specular("fresnel off: the glass top", bsdfs[1], base.layers[0].ir, True)
    empty_scene()


def check_builder_mono():
    """Colored data maps on float inputs (bead maxdrop-em3.42): V-Ray 5.2 takes a data map as the mean of its
    channels (red 1 / 3, measured on a Mix mask, a reflection glossiness and an opacity map), Blender's link from a
    color output into a float input its luminance (red 0.2126). Every float input a map feeds (an image, a Color
    Correction over one, a Mix of images and its mask, a layer mask, a bump height) goes through one DOT_PRODUCT by
    (1/3, 1/3, 1/3); an image's alpha stays as it is."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-mono-")
    try:
        png = os.path.join(scratch, "mono.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        a = tx.Image(1, "mono.png", "mono.png", "", found, colorspace=tx.NON_COLOR)
        b = tx.Image(2, "mono.png", "mono.png", "", found, colorspace=tx.NON_COLOR,
                     mapping=tx.Mapping(tiling=(2.0, 2.0)))
        alpha = tx.Image(3, "mono.png", "mono.png", "", found, colorspace=tx.NON_COLOR, alpha=True)
        ir = cm.MaterialIR(50, "Mono", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)),
                           roughness=cm.Input(0.5, cm.MapRef(1)), metallic=cm.Input(0.0, cm.MapRef(1)),
                           alpha=cm.Input(1.0, cm.MapRef(1)), transmission=cm.Input(0.0, cm.MapRef(1)))
        ir.textures = {
            "base_color": tx.TextureGraphIR(tx.Mix(tx.Constant((0.0,) * 3), a, 0.0, b), tx.COLOR),
            "roughness": tx.TextureGraphIR(a, tx.DATA),
            "metallic": tx.TextureGraphIR(tx.ColorCorrect(a, hue=0.25), tx.DATA),
            "alpha": tx.TextureGraphIR(tx.Mix(a, b, 0.0, b), tx.DATA),
            "transmission": tx.TextureGraphIR(alpha, tx.DATA),
            "bump": tx.TextureGraphIR(tx.Bump(b, 1.0), tx.BUMP)}
        layer = cm.MaterialIR(51, "MonoTop", "test")
        ir.layers = [cm.Layer(layer, 1.0, cm.MapRef(1), tx.TextureGraphIR(a, tx.DATA))]
        m = build_materials.MaterialBuilder().make(ir)
        check("mono: material built", m is not None)
        if m is None:
            return
        mixed = _color_into_float(m)
        check("mono: no color output linked into a float input", mixed == [], str(mixed))
        p = next(n for n in _bsdfs(m) if n.inputs["Roughness"].is_linked)
        rough = _meaned(p.inputs["Roughness"])
        check("mono: a colored roughness image through the mean",
              getattr(rough, "bl_idname", None) == "ShaderNodeTexImage")
        hue = _meaned(p.inputs["Metallic"])
        check("mono: a Color Correction on the metallic, the mean after its hue",
              getattr(hue, "bl_idname", None) == "ShaderNodeHueSaturation")
        mix = _from(p.inputs["Alpha"])
        sides = [_meaned(_input(mix, k)) for k in ("A_Float", "B_Float", "Factor_Float")] \
            if mix is not None and mix.bl_idname == "ShaderNodeMix" else []
        check("mono: a float Mix of images by an image mask, each side and the mask through the mean",
              len(sides) == 3 and all(getattr(n, "bl_idname", None) == "ShaderNodeTexImage" for n in sides)
              and mix.data_type == 'FLOAT', str(sides))
        base = _from(p.inputs["Base Color"])
        check("mono: the mask of a color Mix through the mean, its sides in color",
              getattr(_meaned(_input(base, "Factor_Float")), "bl_idname", None) == "ShaderNodeTexImage"
              and _from(_input(base, "B_Color")).bl_idname == "ShaderNodeTexImage")
        trans = p.inputs["Transmission Weight"]
        check("mono: an image's alpha straight into the float input",
              trans.is_linked and trans.links[0].from_socket.identifier == "Alpha")
        bump = _from(p.inputs["Normal"])
        check("mono: a colored bump height through the mean",
              getattr(bump, "bl_idname", None) == "ShaderNodeBump"
              and getattr(_meaned(_input(bump, "Height")), "bl_idname", None) == "ShaderNodeTexImage")
        shader = next(iter(_shaders(m)), None)
        check("mono: a layer mask through the mean", shader is not None
              and getattr(_meaned(shader.inputs[0]), "bl_idname", None) == "ShaderNodeTexImage")
        dots = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeVectorMath" and n.operation == 'DOT_PRODUCT']
        check("mono: one mean per image in a float graph (two images, and the Color Correction)", len(dots) == 3,
              str(len(dots)))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_negative_constants():
    """A constant color below 0 on a Mix node's color input (bead maxdrop-6n0.6.26): a color input, and an RGB
    node's color, clamp their own value at 0, so mix, multiply, a Composite's opacity Mix and its blend Mix, and
    _Tree.socket put it on a Combine XYZ node, which keeps it; a constant of no channel below 0 stays the input's own
    value (an RGB node for socket)."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    scratch = tempfile.mkdtemp(prefix="maxdrop-negative-")
    neg, pos = (-0.5, 0.25, -0.2), (0.2, 0.3, 0.4)

    def held(socket):  # the constant on a color input: (its values, whether a Combine XYZ holds them)
        n = _from(socket)
        if n is None:
            return list(socket.default_value)[:3], False
        if n.bl_idname == "ShaderNodeCombineXYZ":
            return [i.default_value for i in n.inputs], True
        return None, False

    try:
        png = os.path.join(scratch, "negative.png")
        _write_png(png)
        img = tx.Image(1, "negative.png", "negative.png", "", ct.Found(png, ct.SCENE))
        cases = (("mix", lambda c: tx.Mix(img, tx.Constant(c), 0.5), 'MIX'),
                 ("multiply", lambda c: tx.Multiply(img, tx.Constant(c)), 'MULTIPLY'),
                 ("mix (A)", lambda c: tx.Mix(tx.Constant(c), img, 0.5), 'MIX'),
                 ("multiply (A)", lambda c: tx.Multiply(tx.Constant(c), img), 'MULTIPLY'),
                 ("composite opacity", lambda c: tx.Composite((tx.CompositeLayer(img),
                                                               tx.CompositeLayer(tx.Constant(c), 0.5))), 'MIX'),
                 ("composite blend", lambda c: tx.Composite((tx.CompositeLayer(img),
                                                             tx.CompositeLayer(tx.Constant(c), 1.0, tx.ADDITION))),
                  'ADD'))
        builder = build_materials.MaterialBuilder()
        for what, graph, blend in cases:
            for c in (neg, pos):
                ir = cm.MaterialIR(80, "Negative", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)))
                ir.textures = {"base_color": tx.TextureGraphIR(graph(c), tx.COLOR)}
                m = builder.make(ir)
                mixes = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeMix" and n.blend_type == blend]
                side, other = ("A_Color", "B_Color") if what.endswith("(A)") else ("B_Color", "A_Color")
                value, combined = held(_input(mixes[0], side)) if len(mixes) == 1 else (None, False)
                check("negative constants: %s of an image and %s: %s" % (
                          what, list(c), "on a Combine XYZ" if min(c) < 0 else "the input's own value"),
                      value is not None and close(value, list(c), 1e-6) and combined == (min(c) < 0)
                      and _reaches_image(_input(mixes[0], other)), "%d %s %s" % (len(mixes), value, combined))
                bpy.data.materials.remove(m)
        # a constant bottom layer below 0 under a spotlight-blended map: the blend's A, the add's A and the opacity
        # Mix's A all from one Combine XYZ holding it
        ir = cm.MaterialIR(82, "NegativeBelow", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)))
        ir.textures = {"base_color": tx.TextureGraphIR(tx.Composite((
            tx.CompositeLayer(tx.Constant(neg)), tx.CompositeLayer(img, 0.5, tx.SPOTLIGHT_BLEND))), tx.COLOR)}
        m = builder.make(ir)
        mixes = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeMix"]
        combines = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeCombineXYZ"]
        sources = [_from(_input(n, "A_Color")) for n in mixes]
        check("negative constants: a constant bottom layer below 0 under a spotlight blend: one Combine XYZ on the A "
              "of its three Mix nodes", len(mixes) == 3 and len(combines) == 1 and all(s == combines[0] for s in
                                                                                    sources)
              and close([i.default_value for i in combines[0].inputs], list(neg), 1e-6),
              "%d Mix, %d Combine XYZ, %s" % (len(mixes), len(combines), [getattr(s, "bl_idname", None)
                                                                         for s in sources]))
        bpy.data.materials.remove(m)
        m = bpy.data.materials.new("NegativeSocket")
        tree = build_materials._Tree(builder, m, cm.MaterialIR(81, "NegativeSocket", "test"))
        for c, kind in ((neg, "ShaderNodeCombineXYZ"), (pos, "ShaderNodeRGB")):
            out = tree.socket(c, build_materials.COLOR, 0)
            node = out.node
            got = [i.default_value for i in node.inputs] if node.bl_idname == "ShaderNodeCombineXYZ" else \
                list(out.default_value)[:3]
            check("negative constants: socket() of %s: a %s holding it" % (list(c), kind[10:]),
                  node.bl_idname == kind and close(got, list(c), 1e-6), "%s %s" % (node.bl_idname, got))
        bpy.data.materials.remove(m)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        empty_scene()


def check_builder_mask_mean():
    """An image read as stored as a gamma-off mask (texmaps.Decode mean, bead maxdrop-6n0.6.36): the mean of its
    channels (a DOT_PRODUCT) through the exact sRGB curve in Math nodes (a FLOAT Mix of the power and the linear
    branch by a LESS_THAN), evaluated here from the nodes' own constants against colors.srgb_to_linear; over a
    constant folded; a Composite layer below it keeps its image's alpha."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import colors
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    scratch = tempfile.mkdtemp(prefix="maxdrop-mask-mean-")

    def evaluate(socket, f, image):  # the float reaching socket when the image's mean is f
        if not socket.is_linked:
            return socket.default_value
        n = _from(socket)
        if n == image:
            return f
        if n.bl_idname == "ShaderNodeMath":
            x = [evaluate(i, f, image) for i in n.inputs[:3]]
            return {'MULTIPLY_ADD': lambda: x[0] * x[1] + x[2], 'POWER': lambda: x[0] ** x[1] if x[0] > 0 else 0.0,
                    'DIVIDE': lambda: x[0] / x[1], 'LESS_THAN': lambda: float(x[0] < x[1])}[n.operation]()
        if n.bl_idname == "ShaderNodeMix" and n.data_type == 'FLOAT':
            t = min(1.0, max(0.0, evaluate(_input(n, "Factor_Float"), f, image)))
            a, b = evaluate(_input(n, "A_Float"), f, image), evaluate(_input(n, "B_Float"), f, image)
            return a + (b - a) * t
        raise ValueError(n.bl_idname)

    try:
        png = os.path.join(scratch, "mask.png")
        _write_png(png)
        img = tx.Image(1, "mask.png", "mask.png", "", ct.Found(png, ct.SCENE), colorspace=tx.NON_COLOR)
        builder = build_materials.MaterialBuilder()
        black, white = tx.Constant((0.0,) * 3), tx.Constant((1.0,) * 3)
        ir = cm.MaterialIR(83, "MaskMean", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)))
        ir.textures = {"base_color": tx.TextureGraphIR(tx.Mix(black, white, 0.0, tx.Decode(img, mean=True)),
                                                       tx.COLOR)}
        m = builder.make(ir)
        mix = _from(_principled(m).inputs["Base Color"])
        factor = _input(mix, "Factor_Float") if mix is not None and mix.bl_idname == "ShaderNodeMix" else None
        curve = _from(factor) if factor is not None else None
        texture = None
        if curve is not None and curve.bl_idname == "ShaderNodeMix":
            dots = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeVectorMath"
                    and n.operation == 'DOT_PRODUCT' and close(list(_input(n, "Vector_001").default_value),
                                                                [1 / 3.0] * 3, 1e-6)]
            texture = _from(_input(dots[0], "Vector")) if len(dots) == 1 else None
        ok = (texture is not None and texture.bl_idname == "ShaderNodeTexImage"
              and texture.image.colorspace_settings.name == "Non-Color")
        samples = (0.0, 0.02, 0.04, 0.0405, 0.2, 0.457511, 0.5, 1.0, 1.5)
        got = [evaluate(factor, f, dots[0]) for f in samples] if ok else []
        want = [colors.srgb_to_linear(f) for f in samples]
        check("mask mean: the Non-Color image's mean through the sRGB curve in Math nodes, exact",
              ok and close(got, want, 1e-6), "%s %s" % (got, want))
        bpy.data.materials.remove(m)
        ir = cm.MaterialIR(84, "MaskMeanConstant", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)))
        ir.textures = {"base_color": tx.TextureGraphIR(tx.Mix(black, white, 0.0, tx.Decode(tx.Constant((
            0.8, 0.4, 0.2)), mean=True)), tx.COLOR)}
        m = builder.make(ir)
        mix = _from(_principled(m).inputs["Base Color"])
        value = _input(mix, "Factor_Float").default_value if mix is not None else None
        check("mask mean: over a constant folded to the sRGB curve of its mean",
              value is not None and abs(value - colors.srgb_to_linear(1.4 / 3)) <= 1e-6, str(value))
        bpy.data.materials.remove(m)
        alpha = dataclasses.replace(img, index=2)
        ir = cm.MaterialIR(85, "MaskMeanLayer", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)))
        ir.textures = {"base_color": tx.TextureGraphIR(tx.Composite((tx.CompositeLayer(black), tx.CompositeLayer(
            tx.Decode(alpha, mean=True), 0.5))), tx.COLOR)}
        m = builder.make(ir)
        alphas = [k for k in m.node_tree.links if k.from_node.bl_idname == "ShaderNodeTexImage"
                  and k.from_socket.identifier == "Alpha"]
        check("mask mean: a Composite layer of a mean keeps its image's alpha in the opacity", len(alphas) == 1,
              str(len(alphas)))
        bpy.data.materials.remove(m)
    finally:
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def _evaluate_color(socket):
    """The RGB a color or vector socket gives, from the nodes' own constants (RGB, Separate Color, Math MAXIMUM /
    MINIMUM / ADD / MULTIPLY, Vector Math MULTIPLY_ADD / MAXIMUM / MINIMUM, Gamma); a float is returned as three equal
    channels."""
    if not socket.is_linked:
        v = socket.default_value
        return tuple(v[:3]) if hasattr(v, "__len__") else (float(v),) * 3
    link = socket.links[0]
    n, out = link.from_node, link.from_socket
    if n.bl_idname == "ShaderNodeRGB":
        return tuple(n.outputs[0].default_value[:3])
    if n.bl_idname == "ShaderNodeSeparateColor":
        c = _evaluate_color(n.inputs["Color"])
        return (c[("Red", "Green", "Blue").index(out.name)],) * 3
    if n.bl_idname == "ShaderNodeMath":
        a, b = (_evaluate_color(i)[0] for i in n.inputs[:2])
        f = {'MAXIMUM': max, 'MINIMUM': min, 'ADD': lambda x, y: x + y, 'MULTIPLY': lambda x, y: x * y}[n.operation]
        return (f(a, b),) * 3
    if n.bl_idname == "ShaderNodeVectorMath" and n.operation == 'MULTIPLY_ADD':
        v, s, add = (_evaluate_color(_input(n, k)) for k in ("Vector", "Vector_001", "Vector_002"))
        return tuple(x * y + z for x, y, z in zip(v, s, add))
    if n.bl_idname == "ShaderNodeVectorMath" and n.operation in ('MAXIMUM', 'MINIMUM'):
        a, b = (_evaluate_color(_input(n, k)) for k in ("Vector", "Vector_001"))
        return tuple((max if n.operation == 'MAXIMUM' else min)(x, y) for x, y in zip(a, b))
    if n.bl_idname == "ShaderNodeGamma":
        c, g = _evaluate_color(n.inputs["Color"]), n.inputs["Gamma"].default_value
        return tuple(x ** g if x > 0 else x for x in c)
    raise ValueError(n.bl_idname)


def check_builder_saturation():
    """A Color Correction's saturation drawn as 3ds Max's (HSL: each channel towards (max + min) / 2; V-Ray 5.2
    renders, bead maxdrop-6n0.6.18: -50 % over (200, 100, 50) gives (0.637, 0.441, 0.343)), evaluated from the nodes'
    constants; the hue shift alone on the Hue/Saturation/Value node, its saturation 1."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    empty_scene()
    color = (200 / 255, 100 / 255, 50 / 255)
    builder = build_materials.MaterialBuilder()
    for label, hue in (("saturation", 0.0), ("hue and saturation", 0.5)):
        ir = cm.MaterialIR(86, "Saturation", "test", emission_color=cm.Input((0.0,) * 3, cm.MapRef(1)),
                           emission_strength=1.0)
        ir.textures = {"emission_color": tx.TextureGraphIR(tx.ColorCorrect(tx.Constant(color), hue=hue,
                                                                           saturation=0.5), tx.COLOR)}
        m = builder.make(ir)
        socket = _principled(m).inputs["Emission Color"]
        sat = _from(socket)
        ok = sat is not None and sat.bl_idname == "ShaderNodeVectorMath" and sat.operation == 'MULTIPLY_ADD'
        got = _evaluate_color(socket) if ok and hue == 0.0 else None
        hues = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeHueSaturation"]
        if hue == 0.0:
            check("builder saturation: HSL, (0.637, 0.441, 0.343) as V-Ray renders it, no HSV node",
                  ok and not hues and close(got, [0.6373, 0.4412, 0.3431], 0.0005), str(got))
        else:
            source = _from(_input(sat, "Vector")) if ok else None
            check("builder saturation: the hue on a Hue/Saturation/Value node of saturation 1, before the HSL step",
                  len(hues) == 1 and source == hues[0] and abs(hues[0].inputs["Saturation"].default_value - 1.0) < 1e-6
                  and abs(hues[0].inputs["Hue"].default_value - 0.0) < 1e-6, str(hues))
        bpy.data.materials.remove(m)
    # above 0 %: a channel below 0 is 0, one above 1 kept (V-Ray 5.2, bead maxdrop-6n0.6.38: +100 % over
    # (200, 100, 50) gives 1.078 0.294 0, +50 % 0.931 0.343 0.049)
    for saturation, want in ((2.0, [1.0784, 0.2941, 0.0]), (1.5, [0.9314, 0.3431, 0.0490])):
        ir = cm.MaterialIR(86, "Saturation", "test", emission_color=cm.Input((0.0,) * 3, cm.MapRef(1)),
                           emission_strength=1.0)
        ir.textures = {"emission_color": tx.TextureGraphIR(tx.ColorCorrect(tx.Constant(color), saturation=saturation),
                                                           tx.COLOR)}
        m = builder.make(ir)
        socket = _principled(m).inputs["Emission Color"]
        low = _from(socket)
        ok = low is not None and low.bl_idname == "ShaderNodeVectorMath" and low.operation == 'MAXIMUM'
        got = _evaluate_color(socket) if ok else None
        check("builder saturation %+d %%: a channel below 0 is 0, above 1 kept, as V-Ray renders it" % (
            round(saturation * 100) - 100), ok and close(got, want, 0.0005), str(got))
        bpy.data.materials.remove(m)


def check_world_shown_sky():
    """A float dome texture of a gamma-off scene (DomeTexture.shown, bead maxdrop-6n0.6.21): camera rays see a second
    Background of the sRGB curve of texture x strength (at strength 1), picked by the Light Path's Is Camera Ray on a
    Mix Shader; other rays the texture at the strength. Evaluated from the nodes' constants: a 0.5 sky at multiplier
    2 is srgb_to_linear(1.0), 0.25 at 2 srgb_to_linear(0.5); a hemisphere masks both; a texture not shown has none."""
    from maxdrop.build import world as build_world
    from maxdrop.convert import colors
    from maxdrop.convert import lights as cl
    from maxdrop.convert import texmaps as tx
    empty_scene()
    image = bpy.data.images.new("ShownSky", 4, 4, float_buffer=True)
    texture = tx.Image(1, "sky.exr", "sky.exr", colorspace=tx.LINEAR, gamma=1.0)
    try:
        for hemisphere in (False, True):
            dd = cl.DomeDescription(None, "ShownSky", radiance=2.0, hemisphere=hemisphere)
            dd.texture = cl.DomeTexture(texture, shown=True)
            world = build_world.make_world(dd, image, 1.0)
            nodes = world.node_tree.nodes
            out = next(n for n in nodes if n.bl_idname == "ShaderNodeOutputWorld")
            mix = _from(out.inputs["Surface"])
            seen = nodes.get(build_world.CAMERA_BACKGROUND)
            path = _from(mix.inputs[0]) if mix is not None and mix.bl_idname == "ShaderNodeMixShader" else None
            light = _from(mix.inputs[1]) if path is not None else None
            ok = (path is not None and path.bl_idname == "ShaderNodeLightPath"
                  and mix.inputs[0].links[0].from_socket.name == "Is Camera Ray"
                  and light is not None and light.bl_idname == "ShaderNodeBackground" and light != seen
                  and _from(mix.inputs[2]) == seen)
            power = _from(seen.inputs["Color"]) if ok else None
            curve = _from(power.inputs["Color"]) if power is not None else None
            env = _from(_input(curve, "Vector")) if curve is not None else None
            got = []
            if env is not None and env.bl_idname == "ShaderNodeTexEnvironment":
                for texel in (0.5, 0.25):
                    s, add = (_input(curve, k).default_value[0] for k in ("Vector_001", "Vector_002"))
                    got.append((texel * s + add) ** power.inputs["Gamma"].default_value)
            check("world shown sky%s: camera rays see the sRGB curve of texture x 2, others the texture"
                  % (" (hemisphere)" if hemisphere else ""), ok and len(got) == 2
                  and close(got, [colors.srgb_to_linear(1.0), colors.srgb_to_linear(0.5)], 0.001)
                  and _from(light.inputs["Color"]) == env, "%s %s" % (ok, got))
            if hemisphere:
                above = _from(seen.inputs["Strength"]) if seen is not None else None
                check("world shown sky (hemisphere): the camera's strength the mask alone, the light's mask x 2",
                      above is not None and above.operation == 'GREATER_THAN'
                      and _from(light.inputs["Strength"]).operation == 'MULTIPLY')
            else:
                check("world shown sky: the camera's Background at strength 1, the light's at 2",
                      ok and abs(seen.inputs["Strength"].default_value - 1.0) < 1e-6
                      and abs(light.inputs["Strength"].default_value - 2.0) < 1e-6)
            bpy.data.worlds.remove(world)
        dd = cl.DomeDescription(None, "PlainSky", radiance=2.0)
        dd.texture = cl.DomeTexture(texture)
        world = build_world.make_world(dd, image, 1.0)
        kinds = {n.bl_idname for n in world.node_tree.nodes}
        check("world shown sky: a texture not shown has no Light Path", "ShaderNodeLightPath" not in kinds
              and "ShaderNodeMixShader" not in kinds, str(sorted(kinds)))
        bpy.data.worlds.remove(world)
        dd = cl.DomeDescription(None, "ColorSky", color=(colors.srgb_to_linear(0.5),) * 3, radiance=0.5)
        dd.shown = True
        world = build_world.make_world(dd, None, 1.0)
        seen = world.node_tree.nodes.get(build_world.CAMERA_BACKGROUND)
        out = next(n for n in world.node_tree.nodes if n.bl_idname == "ShaderNodeOutputWorld")
        mix = _from(out.inputs["Surface"])
        got = list(seen.inputs["Color"].default_value)[:3] if seen is not None else None
        check("world shown sky: an untextured gamma-off dome (grey 128 at 0.5): the camera sees srgb_to_linear(0.25)",
              mix is not None and mix.bl_idname == "ShaderNodeMixShader" and got is not None
              and close(got, [colors.srgb_to_linear(0.25)] * 3, 1e-6) and not seen.inputs["Color"].is_linked
              and abs(seen.inputs["Strength"].default_value - 1.0) < 1e-6, str(got))
        bpy.data.worlds.remove(world)
    finally:
        bpy.data.images.remove(image)


def _render_mean(scene, camera, path):
    """The mean red of an 8 x 8 render of scene through camera, written to path (an EXR) and read back."""
    scene.camera = camera
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    px = img.pixels[:]
    n = len(px) // 4
    value = sum(px[i * 4] for i in range(n)) / n
    bpy.data.images.remove(img)
    return value


def check_world_shown_render():
    """The Light Path split rendered (bead maxdrop-6n0.6.21): a World of a uniform 0.5 float texture made shown, a
    camera looking at the sky alone sees srgb_to_linear(0.5) = 0.214 and a white diffuse floor under it, seen from
    above, is lit by the texture as it is (0.5), in Cycles and in this version's EEVEE (world lighting is not a camera
    ray there either)."""
    from maxdrop import compat
    from maxdrop.build import world as build_world
    from maxdrop.convert import colors
    from maxdrop.convert import lights as cl
    from maxdrop.convert import texmaps as tx
    empty_scene()
    scene = bpy.context.scene
    scratch = tempfile.mkdtemp(prefix="maxdrop-world-shown-")
    image = bpy.data.images.new("ShownHalf", 8, 4, float_buffer=True)
    image.pixels[:] = [0.5, 0.5, 0.5, 1.0] * 32
    try:
        dd = cl.DomeDescription(None, "ShownHalf", radiance=1.0)
        dd.texture = cl.DomeTexture(tx.Image(1, "half.exr", "half.exr", colorspace=tx.LINEAR, gamma=1.0), shown=True)
        scene.world = build_world.make_world(dd, image, 1.0)
        mesh = bpy.data.meshes.new("ShownFloor")
        mesh.from_pydata([(-50, -50, 0), (50, -50, 0), (50, 50, 0), (-50, 50, 0)], [], [(0, 1, 2, 3)])
        floor = bpy.data.objects.new("ShownFloor", mesh)
        scene.collection.objects.link(floor)
        mat = bpy.data.materials.new("ShownWhite")
        tree = compat.node_tree(mat)
        tree.nodes.clear()
        diffuse = tree.nodes.new("ShaderNodeBsdfDiffuse")
        diffuse.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        out = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(diffuse.outputs[0], out.inputs["Surface"])
        mesh.materials.append(mat)
        cams = {}
        for name, z, angle in (("sky", 1.0, math.pi), ("floor", 1.0, 0.0)):
            data = bpy.data.cameras.new("Shown" + name)
            data.type = 'ORTHO'
            data.ortho_scale = 1.0
            data.clip_start = 0.01
            cam = bpy.data.objects.new("Shown" + name, data)
            cam.location = (0.0, 0.0, z)
            cam.rotation_euler = (angle, 0.0, 0.0)  # 0: looking down; pi: looking up, away from the floor
            scene.collection.objects.link(cam)
            cams[name] = cam
        scene.render.resolution_x = scene.render.resolution_y = 8
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_depth = '32'
        scene.view_settings.view_transform = 'Standard'
        eevee = 'BLENDER_EEVEE' if bpy.app.version >= (5, 0, 0) else 'BLENDER_EEVEE_NEXT'
        for engine in ('CYCLES', eevee):
            scene.render.engine = engine
            if engine == 'CYCLES':
                scene.cycles.samples = 64
                scene.cycles.use_denoising = False
            else:
                scene.eevee.taa_render_samples = 16
            sky = _render_mean(scene, cams["sky"], os.path.join(scratch, "sky_%s.exr" % engine))
            lit = _render_mean(scene, cams["floor"], os.path.join(scratch, "floor_%s.exr" % engine))
            check("world shown sky, %s: the camera sees srgb_to_linear(0.5), the floor is lit by 0.5" % engine,
                  abs(sky - colors.srgb_to_linear(0.5)) <= 0.02 and abs(lit - 0.5) <= 0.03,
                  "sky %.4f floor %.4f" % (sky, lit))
    finally:
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
        bpy.data.images.remove(image)
        shutil.rmtree(scratch, ignore_errors=True)
