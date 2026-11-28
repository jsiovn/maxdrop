# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of the material builder: found textures, the builder, blends and their modes, gamma magnitudes,
the reflection weight."""
import os
import shutil
import tempfile

import bpy

from .core import check, close, empty_scene, ROOT
from .tables import COAT_WEIGHT_LABEL, SPECULAR_LEVEL, WEIGHT_LABEL
from .nodes import (
    _bsdfs, _clip_axes_of, _from, _images_of, _input, _irs, _principled, _reaches_image, _refracting, _shaders, _thin,
    _weight_factor, _weight_mix, _write_png,
)
from .checks_materials import check_principled, check_refraction_twin, check_twin
from .checks_maps import check_falloff_curve, check_vray_maps_nodes
from .checks_operator import check_cancel, check_failed_build_cleanup, check_pack_cancel, check_run_guards
from .checks_wiring import check_builder_wiring, check_reflection_falloff, check_wrapper_nodes, check_wrapper_wiring


def check_found_textures():
    """vray_maps, texmap_rules, corona_maps, corona_light, vray_texmaps, texmap_wrappers and falloff_curve copied
    beside a PNG for
    each texture name:
    every Image Texture node gets its file, in the color space the IR asks for, one datablock per file and color
    space; the report lists no texture."""
    from maxdrop.convert import texmaps as tx
    fixtures = os.path.join(ROOT, "tests", "fixtures")
    scratch = tempfile.mkdtemp(prefix="maxdrop-textures-")
    linear = []  # the images the IR puts in Linear Rec.709, over every fixture
    try:
        for name in ("vray_maps", "texmap_rules", "corona_maps", "corona_light", "vray_texmaps", "texmap_wrappers",
                     "falloff_curve"):
            empty_scene()
            for ob in list(bpy.data.images):
                bpy.data.images.remove(ob)
            src = os.path.join(fixtures, name + ".max")
            dst = os.path.join(scratch, name + ".max")
            shutil.copy(src, dst)
            _desc, plan = _irs(src)
            irs = {ir.name: ir for s in plan.values() for irs in s.slots for ir in irs if ir is not None}
            wants = {}
            for ir in irs.values():
                for img in _images_of(ir):
                    wants.setdefault(img.name, set()).add(img.colorspace)
            linear += [file for file, spaces in wants.items() if tx.LINEAR in spaces]
            os.makedirs(os.path.join(scratch, "maps"), exist_ok=True)
            for file in wants:  # in the maps folder beside the scene: the lookup's second rule
                _write_png(os.path.join(scratch, "maps", file))
            result = bpy.ops.import_scene.maxdrop(filepath=dst)
            check("%s with its textures: imported" % name, result == {'FINISHED'})
            got = {}
            for m in bpy.data.materials:
                for n in m.node_tree.nodes:
                    if n.bl_idname == "ShaderNodeTexImage":
                        img = n.image
                        check("%s/%s/%s: image loaded" % (name, m.name, n.label), img is not None)
                        if img is not None:
                            check("%s/%s/%s: its file" % (name, m.name, n.label),
                                  os.path.normcase(bpy.path.abspath(img.filepath)) ==
                                  os.path.normcase(os.path.join(scratch, "maps", n.label)), img.filepath)
                            got.setdefault(n.label, set()).add((img.colorspace_settings.name, img.name))
            colorspaces = {k: {c for c, _n in v} for k, v in got.items()}
            check("%s with its textures: the color space of every image as the IR asks" % name,
                  colorspaces == wants, "%s vs %s" % (colorspaces, wants))
            images = sum(len(v) for v in wants.values())
            check("%s with its textures: one image datablock per file and color space" % name,
                  len(bpy.data.images) == images and all(len(v) == len(colorspaces[k]) for k, v in got.items()),
                  "%d images, %d wanted" % (len(bpy.data.images), images))
            text = bpy.data.texts.get("MaxDrop Report")
            body = text.as_string() if text is not None else ""
            check("%s with its textures: no texture reported missing, every file counted as found" % name,
                  text is not None and "Textures not found" not in body
                  and "\nTextures found: %d (" % len(wants) in body, body[-600:])
            for ir in irs.values():
                check_principled("%s with its textures/%s" % (name, ir.name), bpy.data.materials.get(ir.name), ir,
                                 present=True)
            if name == "vray_maps":
                check_vray_maps_nodes(textured=True)
                empty_scene()
                for img in list(bpy.data.images):
                    bpy.data.images.remove(img)
                check_failed_build_cleanup(dst)
                check_cancel(dst, os.path.join(fixtures, "cameras.max"))
                check_run_guards(dst)
                check_pack_cancel(os.path.join(fixtures, "cameras.max"))
            if name == "texmap_rules":
                m = bpy.data.materials["FixtureTexPlace"]
                cropped = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"
                               and n.label == "place_crop.png")
                uv = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeUVMap"]
                comb = _from(_from(cropped.inputs["Vector"]).inputs["Vector"])
                ops = [getattr(_from(comb.inputs[a]), "operation", None) for a in ("X", "Y")] if comb else []
                double = _from(_from(_from(comb.inputs["X"]).inputs[0]).inputs["Vector"]) if comb else None
                check("texmap_rules: place_crop.png on map channel 3, cropped, mirrored (U doubled) in U and clipped "
                      "in V (a mask under EXTEND)", cropped.extension == 'EXTEND' and _clip_axes_of(cropped) == ["Y"]
                      and any(n.uv_map == "UVChannel_3" for n in uv)
                      and ops == ['PINGPONG', 'MULTIPLY_ADD'] and getattr(double, "operation", None) == 'MULTIPLY'
                      and close(list(_input(double, "Vector_001").default_value), [2.0, 1.0, 1.0], 1e-6),
                      "%s %s %s" % (cropped.extension, [n.uv_map for n in uv], ops))
                check("texmap_rules: place_place.png on map channel 0 drawn on UV channel 1, reported",
                      not any(n.uv_map == "UVChannel_0" for mat in bpy.data.materials
                              for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeUVMap")
                      and "map channel 0 (vertex color) not imported: place_place.png on UV channel 1" in body,
                      body[-600:])
                keep = bpy.data.materials["FixtureTexKeep"]
                kinds = {n.bl_idname for n in keep.node_tree.nodes}
                check("texmap_rules: Mix with a mask, Multiply, Color Correction as nodes",
                      {"ShaderNodeMix", "ShaderNodeHueSaturation", "ShaderNodeGamma"} <= kinds, str(sorted(kinds)))
            if name == "texmap_wrappers":
                check_wrapper_nodes()
            if name == "vray_texmaps":
                check_reflection_falloff()
            if name == "falloff_curve":
                check_falloff_curve(textured=True)
        check("found textures: a linear color image (VRayBitmap transfer function Auto in the gamma-off fixture, "
              "decoded twice) imported in Linear Rec.709", "vtx_diffuse.png" in linear, str(linear))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder():
    """MaterialBuilder on hand-made IRs: one file in two color spaces is two images, the same twice is one; a file
    not found leaves its node without an image and a report line; Thin Wall on 5.x, skipped with a line on 4.x;
    two materials of one name both kept; BLENDED for a constant alpha, DITHERED for an alpha map; every node kind."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-builder-")
    try:
        png = os.path.join(scratch, "shared.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        srgb = tx.Image(1, "shared.png", "shared.png", "", found)
        data = tx.Image(1, "shared.png", "shared.png", "", found, colorspace=tx.NON_COLOR)
        lost = tx.Image(2, "nothere.png", "C:\\x\\nothere.png", "", None)
        placed = tx.Image(3, "shared.png", "shared.png", "", found,
                          mapping=tx.Mapping(channel=2, tiling=(2.0, 1.0), angle=(0.0, 0.0, 0.5),
                                             tile=(False, False), mirror=(True, True)),
                          crop=tx.Crop(0.1, 0.2, 0.5, 0.5, place=True),
                          output=tx.TexOutput(invert=True, amount=0.5, level=2.0, offset=0.1))
        gamma = tx.Image(4, "shared.png", "shared.png", "", found, colorspace=tx.LINEAR, gamma=1.8)

        def graph(root, kind):
            return tx.TextureGraphIR(root, kind)

        a = cm.MaterialIR(10, "Clash", "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)),
                          roughness=cm.Input(0.4, cm.MapRef(1)), specular=cm.Input(0.6, cm.MapRef(1)),
                          thin_walled=True, alpha=cm.Input(0.5))
        a.textures = {"base_color": graph(tx.Mix(tx.Constant((0.5, 0.5, 0.5)), srgb, 0.7, data), tx.COLOR),
                      "roughness": graph(tx.Invert(data), tx.DATA),
                      "specular": graph(tx.Multiply(srgb, tx.Constant((2.0, 2.0, 2.0))), tx.COLOR)}
        b = cm.MaterialIR(11, "Clash", "test", alpha=cm.Input(1.0, cm.MapRef(2)),
                          emission_color=cm.Input((1.0, 0.5, 0.0), cm.MapRef(3)), emission_strength=2.0)
        b.textures = {"alpha": graph(lost, tx.DATA),
                      "emission_color": graph(tx.ColorCorrect(tx.Composite((tx.CompositeLayer(placed, 1.0),
                                                                             tx.CompositeLayer(gamma, 0.5))),
                                                              hue=0.25, saturation=1.5, brightness=0.1,
                                                              contrast=0.2, gain=1.2, gamma=1.1), tx.COLOR),
                      "normal": graph(tx.NormalMap(data, 0.7, flip_red=True, flip_green=True, swap=True,
                                                   bump=tx.Bump(data, 2.0), channel=2), tx.NORMAL),
                      "metallic": graph(tx.Constant(0.3), tx.DATA)}
        builder = build_materials.MaterialBuilder()
        ma, mb = builder.make(a), builder.make(b)
        check("builder: two materials named Clash both kept", sorted([ma.name, mb.name]) == ["Clash", "Clash.001"],
              "%s %s" % (ma.name, mb.name))
        shared = sorted(i.colorspace_settings.name for i in bpy.data.images)
        check("builder: shared.png in sRGB, Non-Color (data) and Linear Rec.709 (a color input's gamma override) is "
              "three images, reused by every node",
              shared == ["Linear Rec.709", "Non-Color", "sRGB"] and len(builder.images) == 3, str(shared))
        lost_nodes = [n for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.label == "nothere.png"]
        issues = builder.issues()
        check("builder: a file not found keeps its node, without an image, and is no builder issue (the texture "
              "lookup reports it by name)", len(lost_nodes) == 1 and lost_nodes[0].image is None and issues == [],
              str(issues))
        check("builder: materials counted by class", dict(builder.classes) == {"test": 2}, str(builder.classes))
        thin = _principled(ma).inputs.get("Thin Wall")
        skipped = dict(builder.sockets_skipped)
        if bpy.app.version >= (5, 0, 0):
            check("builder: Thin Wall set on Blender 5", thin is not None and thin.default_value and not skipped)
        else:
            check("builder: Thin Wall skipped and counted once on Blender 4", thin is None
                  and skipped == {"Thin Wall": 1}, str(skipped))
        check("builder: BLENDED for a constant alpha below 1, DITHERED for an alpha map",
              ma.surface_render_method == 'BLENDED' and mb.surface_render_method == 'DITHERED')
        pb = _principled(mb)
        check("builder: emission, normal linked; metallic from a constant graph",
              pb.inputs["Emission Color"].is_linked and pb.inputs["Normal"].is_linked
              and not pb.inputs["Metallic"].is_linked and abs(pb.inputs["Metallic"].default_value - 0.3) < 1e-6
              and abs(pb.inputs["Emission Strength"].default_value - 2.0) < 1e-6)
        kinds = {n.bl_idname for n in mb.node_tree.nodes}
        need = {"ShaderNodeHueSaturation", "ShaderNodeBrightContrast", "ShaderNodeGamma", "ShaderNodeMix",
                "ShaderNodeNormalMap", "ShaderNodeBump", "ShaderNodeSeparateColor", "ShaderNodeCombineColor",
                "ShaderNodeUVMap", "ShaderNodeMapping", "ShaderNodeVectorMath", "ShaderNodeInvert"}
        check("builder: every node kind of the graphs", need <= kinds, str(sorted(need - kinds)))
        place = next(n for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.label == "shared.png"
                     and n.inputs["Vector"].is_linked)
        check("builder: a placed crop that mirrors clips by a mask on both axes under EXTEND",
              place.extension == 'EXTEND' and _clip_axes_of(place) == ["X", "Y"],
              "%s %s" % (place.extension, _clip_axes_of(place)))
        uv = [n.uv_map for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeUVMap"]
        nm = next(n for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeNormalMap")
        check("builder: map channel 2 is UVChannel_2, for the image and the normal map's tangents",
              uv == ["UVChannel_2"] and nm.uv_map == "UVChannel_2", "%s %s" % (uv, nm.uv_map))
        pa = _principled(ma)
        spec, mix = pa.inputs["Specular IOR Level"], _weight_mix(pa)
        dot = _from(mix.inputs[0]) if mix is not None else None
        check("builder: a color graph on the specular goes through the mean into the reflection weight, level 0.5",
              not spec.is_linked and spec.default_value == SPECULAR_LEVEL and dot is not None
              and dot.operation == 'DOT_PRODUCT' and close(list(dot.inputs[1].default_value), [1 / 3.0] * 3, 1e-6))
        check("builder: the viewport color is the base color", close(list(ma.diffuse_color)[:3], [0.5] * 3, 1e-6))
        check_builder_wiring(ma, mb, builder, cm, tx, srgb, data, lost, gamma)
        check_wrapper_wiring(builder, cm, tx, srgb, data)
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_blend():
    """Blend nodes (CoronaMix operations, bead maxdrop-em3.28): Gamma nodes of 1 / 2.2 on both sides and 2.2 after a
    Mix node of the operation, not clamped; subtract floored by a Vector Math MAXIMUM; two constants folded; a
    layered IR as a Principled BSDF per layer under Mix Shaders, the mask's graph times the amount on the factor."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    scratch = tempfile.mkdtemp(prefix="maxdrop-blend-")
    try:
        png = os.path.join(scratch, "blend.png")
        _write_png(png)
        img = tx.Image(1, "blend.png", "blend.png", "", ct.Found(png, ct.SCENE))
        c = tx.Constant((0.2, 0.4, 0.6))
        ir = cm.MaterialIR(20, "Blends", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)),
                           emission_color=cm.Input((0.0,) * 3, cm.MapRef(1)), emission_strength=1.0,
                           specular=cm.Input(0.5, cm.MapRef(1)))
        ir.textures = {"base_color": tx.TextureGraphIR(tx.Blend(tx.BLEND_ADD, c, img, 2.2), tx.COLOR),
                       "emission_color": tx.TextureGraphIR(tx.Blend(tx.BLEND_SUBTRACT, img, c), tx.COLOR),
                       "specular": tx.TextureGraphIR(tx.Blend(tx.BLEND_MAX, c, tx.Constant((0.5, 0.1, 0.9))),
                                                     tx.COLOR)}
        layer = cm.MaterialIR(21, "Top", "test", base_color=cm.Input((1.0, 0.0, 0.0)), sheen_weight=0.5)
        mask = tx.TextureGraphIR(tx.Mix(tx.Constant(1.0), img, 0.5), tx.DATA)
        ir.layers = [cm.Layer(layer, 0.4), cm.Layer(layer, 0.8, cm.MapRef(1, 0.5), mask)]
        builder = build_materials.MaterialBuilder()
        m = builder.make(ir)
        nodes = m.node_tree.nodes
        mixes = [n for n in nodes if n.bl_idname == "ShaderNodeMix" and n.blend_type in ('ADD', 'SUBTRACT')]
        add = next((n for n in mixes if n.blend_type == 'ADD'), None)
        gammas = sorted(round(n.inputs[1].default_value, 4) for n in nodes if n.bl_idname == "ShaderNodeGamma")
        check("blend: add between Gamma 1 / 2.2 and 2.2, unclamped (the constant side folded: maxdrop-em3.161)",
              add is not None and not add.clamp_result and gammas == [round(1 / 2.2, 4), 2.2], str(gammas))
        floor = [n for n in nodes if n.bl_idname == "ShaderNodeVectorMath" and n.operation == 'MAXIMUM']
        check("blend: subtract floored at 0", len(floor) == 1)
        bsdfs, shaders = _bsdfs(m), _shaders(m)
        pb = bsdfs[0]
        spec, mix = pb.inputs["Specular IOR Level"], _weight_mix(pb)
        check("blend: two constants folded (max), the mean as the reflection weight", not spec.is_linked
              and spec.default_value == SPECULAR_LEVEL and mix is not None and not mix.inputs[0].is_linked
              and abs(mix.inputs[0].default_value - (0.5 + 0.4 + 0.9) / 3) < 1e-5,
              str(mix.inputs[0].default_value if mix else None))
        check("layers: a Principled BSDF and a Mix Shader per layer", len(bsdfs) == 3 and len(shaders) == 2)
        plain = [n for n in shaders if not n.inputs[0].is_linked]
        masked = [n for n in shaders if n.inputs[0].is_linked]
        check("layers: amount 0.4 as the factor, the masked one linked through a multiply by 0.8",
              len(plain) == 1 and abs(plain[0].inputs[0].default_value - 0.4) < 1e-6 and len(masked) == 1
              and masked[0].inputs[0].links[0].from_node.bl_idname == "ShaderNodeMath")
        out = next(n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial")
        check("layers: the top Mix Shader into the output", out.inputs["Surface"].links[0].from_node in masked)
        top = bsdfs[1]
        check("layers: the layer's sheen set", abs(top.inputs["Sheen Weight"].default_value - 0.5) < 1e-6)
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_added_layers():
    """VRayBlendMtl's coats (bead maxdrop-o53.1.6): a mixed coat and an added one over a base, one Principled BSDF
    per layer; the mixed one joined by a Mix Shader at its weight, the added one by an Add Shader over a Mix Shader
    from nothing (COAT_WEIGHT_LABEL) to the coat at its weight, a masked weight's graph linked into that factor."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    empty_scene()
    try:
        base = cm.MaterialIR(30, "Blend", "test", base_color=cm.Input((0.0, 0.0, 1.0)))
        mixed = cm.MaterialIR(31, "CoatA", "test", base_color=cm.Input((1.0, 1.0, 0.0)))
        added = cm.MaterialIR(32, "CoatB", "test", base_color=cm.Input((0.0, 1.0, 1.0)))
        mask = tx.TextureGraphIR(tx.Mix(tx.Constant(0.3), tx.Checker(tx.Mapping()), 0.4), tx.MASK)
        base.layers = [cm.Layer(mixed, 0.25), cm.Layer(added, 0.6, mode=cm.ADD),
                       cm.Layer(added, 1.0, cm.MapRef(1, 0.4), mask, cm.ADD)]
        m = build_materials.MaterialBuilder().make(base)
        nodes = m.node_tree.nodes
        bsdfs, shaders = _bsdfs(m), _shaders(m)
        adds = [n for n in nodes if n.bl_idname == "ShaderNodeAddShader"]
        check("added layers: a Principled BSDF per layer, a Mix Shader per layer, an Add Shader per added one",
              len(bsdfs) == 4 and len(shaders) == 3 and len(adds) == 2,
              "%d BSDFs, %d Mix, %d Add" % (len(bsdfs), len(shaders), len(adds)))
        out = next(n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial")
        top = _from(out.inputs["Surface"])
        check("added layers: the top Add Shader into the output", top in adds)
        scaled = [_from(n.inputs[1]) for n in adds]
        check("added layers: each Add Shader adds a Mix Shader from nothing to its coat",
              all(s is not None and s.label == COAT_WEIGHT_LABEL and not s.inputs[1].is_linked
                  and _from(s.inputs[2]) in bsdfs for s in scaled))
        constant = [s for s in scaled if s is not None and not s.inputs[0].is_linked]
        linked = [s for s in scaled if s is not None and s.inputs[0].is_linked]
        check("added layers: the constant weight 0.6 on its factor, the masked one linked", len(constant) == 1
              and abs(constant[0].inputs[0].default_value - 0.6) < 1e-6 and len(linked) == 1,
              str([s.inputs[0].default_value for s in constant]))
        chain = _from(top.inputs[0]) if top is not None else None  # below the top: the first added coat
        plain = _from(chain.inputs[0]) if chain is not None else None  # below it: the mixed coat
        check("added layers: bottom first, the base, the mixed coat by its Mix Shader, then the two Add Shaders",
              chain in adds and plain in shaders and plain.label != COAT_WEIGHT_LABEL
              and _from(plain.inputs[1]) == bsdfs[0], "%s %s" % tuple(n and n.name for n in (chain, plain)))
        check("added layers: the mixed coat by its weight 0.25 over the base", plain is not None
              and abs(plain.inputs[0].default_value - 0.25) < 1e-6 and _from(plain.inputs[2]) in bsdfs[1:])
    finally:
        empty_scene()


def _blend_form(op, vms, t):
    """Whether the Vector Math nodes vms of a dodge, burn or exclusion of an image (a) and the constant t (b, as the
    operation takes it) are wired as Corona's formula (maxdrop-em3.161): (ok, the operations found)."""
    from maxdrop.convert import texmaps as tx

    def one(operation):
        found = [n for n in vms if n.operation == operation]
        return found[0] if len(found) == 1 else None

    def const(n, name, v):
        socket = _input(n, name)
        return not socket.is_linked and close(list(socket.default_value), list(v), 1e-5)

    ones, zeros = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    madds = [n for n in vms if n.operation == 'MULTIPLY_ADD']
    found = sorted(n.operation for n in vms)
    if op == tx.BLEND_EXCLUSION:  # a + b (1 - 2a)
        inner = next((n for n in madds if const(n, "Vector_001", (-2.0,) * 3)), None)
        outer = next((n for n in madds if n != inner), None)
        ok = len(madds) == 2 and inner is not None and outer is not None and const(inner, "Vector_002", ones) \
            and _reaches_image(_input(inner, "Vector")) and const(outer, "Vector", t) \
            and _from(_input(outer, "Vector_001")) == inner and _input(outer, "Vector_002").is_linked \
            and _input(outer, "Vector_002").links[0].from_socket == _input(inner, "Vector").links[0].from_socket
        return ok, found
    div, sub, top = one('DIVIDE'), one('SUBTRACT'), one('MAXIMUM')
    if None in (div, sub, top) or len(madds) != 1:
        return False, found
    m = madds[0]
    ok = const(m, "Vector_001", (-1.0,) * 3) and const(m, "Vector_002", ones) and const(sub, "Vector", ones) \
        and _from(_input(sub, "Vector_001")) == div and _from(_input(top, "Vector")) == sub \
        and const(top, "Vector_001", zeros)
    if op == tx.BLEND_DODGE:  # 1 - max(0, 1 - a / (1 - b))
        ok = ok and _reaches_image(_input(div, "Vector")) and const(div, "Vector_001", [1.0 - c for c in t]) \
            and _from(_input(m, "Vector")) == top
    else:  # burn: max(0, 1 - (1 - a) / b)
        ok = ok and _from(_input(div, "Vector")) == m and _reaches_image(_input(m, "Vector")) \
            and const(div, "Vector_001", t)
    return ok, found


def check_builder_blend_modes():
    """The CoronaMix blend modes of bead maxdrop-em3.117 over an image: a Mix node of the mode (bottom in A, hard
    light's top in A), linear burn's add minus 1 floored at 0; dodge, burn and exclusion as Vector Math nodes,
    Corona's unclamped formulas (maxdrop-em3.161); in sRGB mode a Vector Math ABSOLUTE before the map side's
    Gamma of 1 / 2.2 and a constant side's magnitude folded (Corona takes a layer's magnitude, maxdrop-em3.161), an
    ABSOLUTE before the closing Gamma but for linear burn and burn (never below 0); in linear mode none."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    scratch = tempfile.mkdtemp(prefix="maxdrop-blend-modes-")
    try:
        png = os.path.join(scratch, "blend.png")
        _write_png(png)
        img = tx.Image(1, "blend.png", "blend.png", "", ct.Found(png, ct.SCENE))
        top = (0.6, -0.2, 0.75)  # a channel below 0: its magnitude in sRGB mode
        types = {tx.BLEND_SCREEN: 'SCREEN', tx.BLEND_OVERLAY: 'OVERLAY', tx.BLEND_HARD_LIGHT: 'OVERLAY',
                 tx.BLEND_LINEAR_BURN: 'ADD', tx.BLEND_LINEAR_LIGHT: 'LINEAR_LIGHT'}
        builder = build_materials.MaterialBuilder()
        for op in list(types) + [tx.BLEND_DODGE, tx.BLEND_BURN, tx.BLEND_EXCLUSION]:
            for gamma in (2.2, 1.0):
                ir = cm.MaterialIR(30, "Mode", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)))
                ir.textures = {"base_color": tx.TextureGraphIR(tx.Blend(op, img, tx.Constant(top), gamma), tx.COLOR)}
                m = builder.make(ir)
                nodes = m.node_tree.nodes
                what = "blend mode %s, gamma %s" % (op, gamma)
                t = tuple(abs(c) ** (1 / gamma) for c in top) if gamma != 1.0 else top
                vms = [n for n in nodes if n.bl_idname == "ShaderNodeVectorMath"]
                if op in types:
                    blend_type = types[op]
                    mix = [n for n in nodes if n.bl_idname == "ShaderNodeMix" and n.blend_type == blend_type]
                    ok = len(mix) == 1 and not mix[0].clamp_result
                    if ok:
                        a, b = _input(mix[0], "A_Color"), _input(mix[0], "B_Color")
                        image, constant = (b, a) if op == tx.BLEND_HARD_LIGHT else (a, b)
                        held = _from(constant)  # a channel below 0: a Combine XYZ (a color input clamps at 0)
                        if held is None:
                            value = list(constant.default_value)[:3]
                        elif held.bl_idname == "ShaderNodeCombineXYZ":
                            value = [s.default_value for s in held.inputs]
                        else:
                            value = None
                        ok = _reaches_image(image) and value is not None and close(value, list(t), 1e-5) \
                            and (held is not None) == (min(t) < 0.0)
                    check("%s: one unclamped Mix node, the bottom image in %s, the top %s"
                          % (what, "B" if op == tx.BLEND_HARD_LIGHT else "A", [round(c, 4) for c in t]), ok)
                else:
                    ok, found = _blend_form(op, vms, t)
                    check("%s: Vector Math nodes wired as Corona's formula, no Mix node" % what,
                          ok and not any(n.bl_idname == "ShaderNodeMix" for n in nodes), str(found))
                absolute = [n for n in vms if n.operation == 'ABSOLUTE']
                into = sorted(round(_input(n.outputs[0].links[0].to_node, "Gamma").default_value, 3)
                              for n in absolute if n.outputs[0].links
                              and n.outputs[0].links[0].to_node.bl_idname == "ShaderNodeGamma")
                closing = gamma != 1.0 and op not in (tx.BLEND_LINEAR_BURN, tx.BLEND_BURN)
                wants = ([round(1 / 2.2, 3)] if gamma != 1.0 else []) + ([2.2] if closing else [])
                check("%s: ABSOLUTE into the Gammas %s" % (what, wants),
                      into == wants and len(absolute) == len(wants), str(into))
                if op == tx.BLEND_LINEAR_BURN:
                    vm = {n.operation: n for n in vms}
                    add, floor = vm.get('ADD'), vm.get('MAXIMUM')
                    check("%s: minus 1, then floored at 0" % what,
                          add is not None and tuple(_input(add, "Vector_001").default_value) == (-1.0, -1.0, -1.0)
                          and floor is not None and floor.inputs[0].links[0].from_node == add)
                bpy.data.materials.remove(m)
        for op in (tx.BLEND_DODGE, tx.BLEND_BURN):  # a map top: nz = ceil(min(|d|, 1)) drawn from the divisor
            ir = cm.MaterialIR(31, "Maps", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)))
            ir.textures = {"base_color": tx.TextureGraphIR(tx.Blend(op, img, tx.Invert(img)), tx.COLOR)}
            m = builder.make(ir)
            vms = {n.operation: n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeVectorMath"}
            div, sub, ceil = vms.get('DIVIDE'), vms.get('SUBTRACT'), vms.get('CEIL')
            low, absolute = vms.get('MINIMUM'), vms.get('ABSOLUTE')
            ok = None not in (div, sub, ceil, low, absolute) and _input(div, "Vector_001").is_linked \
                and _from(_input(absolute, "Vector")) == _from(_input(div, "Vector_001")) \
                and _from(_input(low, "Vector")) == absolute and _from(_input(ceil, "Vector")) == low \
                and _from(_input(sub, "Vector")) == ceil and _from(_input(sub, "Vector_001")) == div
            check("blend mode %s over two maps: ceil(min(|d|, 1)) of the divisor drawn" % op, ok, str(sorted(vms)))
            bpy.data.materials.remove(m)
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_gamma_magnitude():
    """A ColorCorrect gamma that takes the magnitude (a CoronaMix gamma in sRGB mode, maxdrop-6n0.6.40): a Vector Math
    ABSOLUTE between the image and the Gamma node, also beside another step; without the flag none; at a gamma of 1
    the ABSOLUTE alone. Structural, as the other builder checks (the values: test_texmaps_more and the probe)."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    scratch = tempfile.mkdtemp(prefix="maxdrop-gamma-magnitude-")
    try:
        png = os.path.join(scratch, "gamma.png")
        _write_png(png)
        img = tx.Image(1, "gamma.png", "gamma.png", "", ct.Found(png, ct.SCENE))
        builder = build_materials.MaterialBuilder()
        for magnitude in (True, False):
            for hue in (0.0, 0.25):
                ir = cm.MaterialIR(32, "Magnitude", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)))
                ir.textures = {"base_color": tx.TextureGraphIR(
                    tx.ColorCorrect(img, hue=hue, gamma=0.731, magnitude=magnitude), tx.COLOR)}
                m = builder.make(ir)
                nodes = m.node_tree.nodes
                gammas = [n for n in nodes if n.bl_idname == "ShaderNodeGamma"]
                absolute = [n for n in nodes if n.bl_idname == "ShaderNodeVectorMath" and n.operation == 'ABSOLUTE']
                ok = len(gammas) == 1 and abs(_input(gammas[0], "Gamma").default_value - 1 / 0.731) < 1e-5
                if magnitude:
                    ok = (ok and len(absolute) == 1 and _from(_input(gammas[0], "Color")) == absolute[0]
                          and _reaches_image(_input(absolute[0], "Vector"))
                          and absolute[0].location.x < gammas[0].location.x)
                else:
                    ok = ok and not absolute and _reaches_image(_input(gammas[0], "Color"))
                check("ColorCorrect gamma, magnitude %s, hue %s: %s" % (
                    magnitude, hue, "ABSOLUTE into the Gamma" if magnitude else "no ABSOLUTE"), ok,
                    str([n.bl_idname for n in nodes]))
                bpy.data.materials.remove(m)
        ir = cm.MaterialIR(33, "Magnitude1", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)))
        ir.textures = {"base_color": tx.TextureGraphIR(tx.ColorCorrect(img, magnitude=True), tx.COLOR)}
        m = builder.make(ir)
        nodes = m.node_tree.nodes
        absolute = [n for n in nodes if n.bl_idname == "ShaderNodeVectorMath" and n.operation == 'ABSOLUTE']
        check("ColorCorrect magnitude at gamma 1: the ABSOLUTE alone, no Gamma",
              len(absolute) == 1 and _reaches_image(_input(absolute[0], "Vector"))
              and not any(n.bl_idname == "ShaderNodeGamma" for n in nodes), str([n.bl_idname for n in nodes]))
        bpy.data.materials.remove(m)
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_weight():
    """A reflection weight (bead maxdrop-em3.119): between 0 and 1, or a map, a Mix Shader by the weight over a
    twin without reflection; 0, 1 and a metal keep the lone Principled at 0.5 x the weight; a layer gets a twin of
    its own. Refracting glass (bead maxdrop-em3.135): the twin refracts without reflecting (a Refraction BSDF, under
    the Principled twin by a partial transmission), unless an alpha, an emission, a coat or a sheen keep the
    Principled twin; glass with Fresnel off: check_builder_fresnel_off."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    empty_scene()
    builder = build_materials.MaterialBuilder()
    facing = tx.Facing(tx.PERPENDICULAR)

    def make(name, textures=None, **kw):
        ir = cm.MaterialIR(70, name, "test", **{"base_color": cm.Input((0.2, 0.3, 0.4)), **kw})
        ir.textures = textures or {}
        return builder.make(ir)

    glass = dict(specular=cm.Input(0.4), transmission=cm.Input(1.0))
    for name, kw, textures, mixed, level, refracts in (
            ("None", dict(specular=cm.Input(0.0)), None, False, 0.0, False),
            ("Grey", dict(specular=cm.Input(0.4), roughness=cm.Input(0.3), alpha=cm.Input(0.5)), None, True, 0.5,
             False),
            ("White", dict(specular=cm.Input(1.0)), None, False, 0.5, False),
            ("Above", dict(specular=cm.Input(1.6)), None, False, 0.5, False),
            ("Metal", dict(specular=cm.Input(0.4), metallic=cm.Input(1.0)), None, False, 0.2, False),
            ("Glass", dict(glass, roughness=cm.Input(0.2)), None, True, 0.5, True),
            ("GlassGrey", dict(glass, base_color=cm.Input((0.25, 0.25, 0.25))), None, True, 0.5, True),
            ("GlassWhite", dict(glass, specular=cm.Input(1.0)), None, False, 0.5, False),
            ("HalfGlass", dict(specular=cm.Input(0.4), transmission=cm.Input(0.5)), None, True, 0.5, True),
            ("GlassMapBase", dict(glass, base_color=cm.Input((1.0, 1.0, 1.0), cm.MapRef(1))),
             {"base_color": tx.TextureGraphIR(tx.Mix(tx.Constant((0.0,) * 3), tx.Constant((1.0,) * 3), 0.0, facing),
                                              tx.COLOR)}, True, 0.5, True),
            ("GlassTransMap", dict(specular=cm.Input(0.4), transmission=cm.Input(0.5, cm.MapRef(1))),
             {"transmission": tx.TextureGraphIR(tx.Mix(tx.Constant(0.0), tx.Constant(1.0), 0.0, facing), tx.DATA)},
             True, 0.5, True),
            ("GlassAlpha", dict(glass, alpha=cm.Input(0.5)), None, True, 0.5, False),
            ("GlassEmission", dict(glass, emission_color=cm.Input((1.0, 0.5, 0.2)), emission_strength=2.0), None,
             True, 0.5, False),
            ("GlassCoat", dict(glass, coat_weight=0.5), None, True, 0.5, False),
            ("GlassBlack", dict(glass, specular=cm.Input(0.0)), None, True, 0.5, True),
            ("HalfGlassBlack", dict(glass, specular=cm.Input(0.0), transmission=cm.Input(0.5)), None, True, 0.5,
             True),
            ("GlassMetal", dict(glass, metallic=cm.Input(0.5)), None, True, 0.5, False),
            ("GlassSheen", dict(glass, sheen_weight=0.5), None, True, 0.5, False),
            ("GlassWeightMap", dict(glass, specular=cm.Input(0.0, cm.MapRef(1))),
             {"specular": tx.TextureGraphIR(tx.Mix(tx.Constant(0.0), tx.Constant(1.0), 0.0, facing), tx.DATA)},
             True, 0.5, True),
            ("GlassBump", dict(glass), {"bump": tx.TextureGraphIR(tx.Bump(
                tx.Mix(tx.Constant(0.0), tx.Constant(1.0), 0.0, facing), 0.3), tx.DATA)}, True, 0.5, True),
            ("ThinGlass", dict(glass, thin_walled=True), None, True, 0.5, True)):
        m = make(name, textures, **kw)
        p = _principled(m)
        mix = _weight_mix(p) if p is not None else None
        level_ok = p is not None and abs(p.inputs["Specular IOR Level"].default_value - level) < 1e-6
        check("weight: %s: %s, Specular IOR Level %.1f" % (name, "a reflection weight" if mixed else "a lone BSDF",
                                                           level), level_ok and (mix is not None) == mixed)
        out = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
        top = _from(out.inputs["Surface"])
        check("weight: %s: the surface is the %s" % (name, "Mix Shader" if mixed else "Principled BSDF"),
              top == (mix if mixed else p))
        if not mixed or mix is None:
            continue
        fac = _weight_factor(mix)
        check("weight: %s: the factor is the weight" % name,
              fac.is_linked if textures and "specular" in textures
              else not fac.is_linked and abs(fac.default_value - kw["specular"].value) < 1e-6)
        if name == "GlassBump":
            check("weight: GlassBump: the Principled's normal is linked", p.inputs["Normal"].is_linked)
        check("weight: %s: the twin %s" % (name, "refracts" if refracts else "is a Principled BSDF"),
              _refracting(p) == refracts)
        if refracts:
            check_refraction_twin("weight: " + name, p, mix)
            if name == "ThinGlass":
                check("weight: ThinGlass: drawn as a thin wall where Blender has one",
                      _thin(p) == ("Thin Wall" in p.inputs))
            continue
        check_twin("weight: " + name, p, mix)
        twin = _from(mix.inputs[1])
        check("weight: %s: the twin keeps the BSDF's alpha and transmission" % name,
              abs(twin.inputs["Alpha"].default_value - p.inputs["Alpha"].default_value) < 1e-6
              and abs(twin.inputs["Transmission Weight"].default_value
                      - p.inputs["Transmission Weight"].default_value) < 1e-6)
    m = make("BlendedGrey", specular=cm.Input(0.4), alpha=cm.Input(0.5))
    check("weight: a constant alpha below 1 still blends", m.surface_render_method == 'BLENDED',
          m.surface_render_method)
    top = cm.MaterialIR(71, "GreyTop", "test", specular=cm.Input(0.6))
    ir = cm.MaterialIR(72, "Layered", "test", specular=cm.Input(1.0))
    ir.layers = [cm.Layer(top, 0.5)]
    m = builder.make(ir)
    bsdfs, shaders = _bsdfs(m), _shaders(m)
    weights = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeMixShader" and n.label == WEIGHT_LABEL]
    layer_mix = shaders[0] if len(shaders) == 1 else None
    check("weight: a grey layer over a white base: one weight, on the layer, into the layer's Mix Shader",
          len(bsdfs) == 2 and len(weights) == 1 and _weight_mix(bsdfs[0]) is None and layer_mix is not None
          and _weight_mix(bsdfs[1]) == weights[0] and _from(layer_mix.inputs[2]) == weights[0]
          and _from(layer_mix.inputs[1]) == bsdfs[0], "%d BSDFs, %d weights" % (len(bsdfs), len(weights)))
    if len(bsdfs) == 2 and len(weights) == 1:
        check_twin("weight: the layer", bsdfs[1], weights[0])
    ir = cm.MaterialIR(73, "GreyUnder", "test", specular=cm.Input(0.3))
    ir.layers = [cm.Layer(top, 0.5)]
    m = builder.make(ir)
    bsdfs, shaders = _bsdfs(m), _shaders(m)
    under = _weight_mix(bsdfs[0]) if bsdfs else None
    layer_mix = shaders[0] if len(shaders) == 1 else None
    check("weight: a grey base under a grey layer: the base's weight below the layer's Mix Shader",
          len(bsdfs) == 2 and under is not None and layer_mix is not None and _from(layer_mix.inputs[1]) == under
          and _weight_mix(bsdfs[1]) is not None and _from(layer_mix.inputs[2]) == _weight_mix(bsdfs[1]))
    if under is not None:
        check_twin("weight: the base under a layer", bsdfs[0], under)
    empty_scene()
