# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of the builder's wiring, the reflection falloff and the wrappers' nodes and wiring."""
import bpy

from .core import check, close
from .nodes import _decoded, _from, _image_of, _input, _meaned, _node_kinds, _principled, _specular_socket, _upstream


def check_builder_wiring(ma, mb, builder, cm, tx, srgb, data, lost, gamma):
    """The links and values of the hand-made IRs' nodes, against numbers worked out by hand."""
    pa, pb = _principled(ma), _principled(mb)
    mix = _from(pa.inputs["Base Color"])
    mask = _meaned(_input(mix, "Factor_Float")) if mix.bl_idname == "ShaderNodeMix" else None
    check("wiring: base color Mix: A the swatch, B the sRGB image, the mask image's mean on the factor",
          mix.bl_idname == "ShaderNodeMix" and mix.blend_type == 'MIX' and not _input(mix, "A_Color").is_linked
          and close(list(_input(mix, "A_Color").default_value)[:3], [0.5] * 3, 1e-6)
          and _from(_input(mix, "B_Color")).image.colorspace_settings.name == "sRGB"
          and getattr(mask, "image", None) is not None and mask.image.colorspace_settings.name == "Non-Color")
    inv = _from(pa.inputs["Roughness"])
    check("wiring: roughness 1 - the mean of the data image", inv.bl_idname == "ShaderNodeMath"
          and inv.operation == 'SUBTRACT' and inv.inputs[0].default_value == 1.0
          and getattr(_meaned(inv.inputs[1]), "bl_idname", None) == "ShaderNodeTexImage")
    dot = _from(_specular_socket(pa))
    mul = _from(dot.inputs[0])
    check("wiring: specular map times 2 through a Multiply Mix", mul.bl_idname == "ShaderNodeMix"
          and mul.blend_type == 'MULTIPLY' and _input(mul, "Factor_Float").default_value == 1.0
          and close(list(_input(mul, "B_Color").default_value)[:3], [2.0] * 3, 1e-6))
    gam = _from(pb.inputs["Emission Color"])
    gain = _from(gam.inputs["Color"])
    bc = _from(gain.inputs[0])
    sat = _from(bc.inputs["Color"])
    low = sat if sat.bl_idname == "ShaderNodeVectorMath" and sat.operation == 'MAXIMUM' else None
    sat = _from(_input(low, "Vector")) if low is not None else sat
    hue = _from(_input(sat, "Vector")) if sat.bl_idname == "ShaderNodeVectorMath" else sat
    comp = _from(hue.inputs["Color"])
    check("wiring: Color Correction: Hue 0.75, HSL Saturation 1.5 (maxdrop-6n0.6.18) and a MAXIMUM of 0 after it "
          "(maxdrop-6n0.6.38), Bright 0.1, Contrast 0.2, gain 1.2, Gamma 1 / 1.1", low is not None
          and close(list(_input(low, "Vector_001").default_value), [0.0] * 3, 1e-6)
          and sat.bl_idname == "ShaderNodeVectorMath" and sat.operation == 'MULTIPLY_ADD'
          and close(list(_input(sat, "Vector_001").default_value), [1.5] * 3, 1e-6) and
          gam.bl_idname == "ShaderNodeGamma" and abs(gam.inputs["Gamma"].default_value - 1 / 1.1) < 1e-6
          and gain.bl_idname == "ShaderNodeVectorMath" and gain.operation == 'SCALE'
          and abs(_input(gain, "Scale").default_value - 1.2) < 1e-6
          and bc.bl_idname == "ShaderNodeBrightContrast" and abs(_input(bc, "Bright").default_value - 0.1) < 1e-6
          and abs(_input(bc, "Contrast").default_value - 0.2) < 1e-6
          and hue.bl_idname == "ShaderNodeHueSaturation" and abs(hue.inputs["Hue"].default_value - 0.75) < 1e-6
          and abs(hue.inputs["Saturation"].default_value - 1.0) < 1e-6)
    factor = _from(_input(comp, "Factor_Float"))
    top = _from(_input(comp, "B_Color"))
    check("wiring: Composite: the top layer over the bottom by its alpha times 0.5, its gamma override 1.8 applied",
          comp.bl_idname == "ShaderNodeMix" and factor.bl_idname == "ShaderNodeMath" and factor.operation == 'MULTIPLY'
          and abs(factor.inputs[1].default_value - 0.5) < 1e-6 and factor.inputs[0].links[0].from_socket.name == "Alpha"
          and top.bl_idname == "ShaderNodeGamma" and abs(top.inputs["Gamma"].default_value - 1.8) < 1e-6
          and _from(top.inputs["Color"]).image.colorspace_settings.name == "Linear Rec.709")
    amount = _from(_input(comp, "A_Color"))
    level = _from(amount.inputs[0])
    out_inv = _from(level.inputs[0])
    tex, clip = _image_of(out_inv.inputs["Color"])
    crop = _from(tex.inputs["Vector"])
    comb = _from(crop.inputs["Vector"])
    pings = [_from(comb.inputs[axis]) for axis in ("X", "Y")]
    sep = _from(pings[0].inputs[0])
    double = _from(sep.inputs["Vector"])
    place = _from(double.inputs["Vector"])
    uv = _from(place.inputs["Vector"])
    from maxdrop.build import materials as build_materials
    want = build_materials.uv_transform(tx.Mapping(tiling=(2.0, 1.0), angle=(0.0, 0.0, 0.5)))
    check("wiring: Output: inverted, times 2 minus 0.1 (3ds Max's offset under an invert), times 0.5",
          amount.operation == 'SCALE' and abs(_input(amount, "Scale").default_value - 0.5) < 1e-6
          and level.operation == 'MULTIPLY_ADD' and close(list(_input(level, "Vector_001").default_value), [2.0] * 3,
                                                          1e-6)
          and close(list(_input(level, "Vector_002").default_value), [-0.1] * 3, 1e-6)
          and out_inv.bl_idname == "ShaderNodeInvert")
    check("wiring: a placed crop mirrored both ways: UVChannel_2 -> placement -> times (2, 2, 1) -> ping-pong per "
          "axis -> Mapping TEXTURE at (0.1, 0.3) x 0.5",
          crop.bl_idname == "ShaderNodeMapping" and crop.vector_type == 'TEXTURE'
          and close(list(crop.inputs["Location"].default_value), [0.1, 0.3, 0.0], 1e-6)
          and close(list(crop.inputs["Scale"].default_value), [0.5, 0.5, 1.0], 1e-6)
          and comb.bl_idname == "ShaderNodeCombineXYZ" and sep.bl_idname == "ShaderNodeSeparateXYZ"
          and all(n.operation == 'PINGPONG' and n.inputs[1].default_value == 1.0 for n in pings)
          and _from(pings[1].inputs[0]) == sep
          and double.bl_idname == "ShaderNodeVectorMath" and double.operation == 'MULTIPLY'
          and close(list(_input(double, "Vector_001").default_value), [2.0, 2.0, 1.0], 1e-6)
          and place.bl_idname == "ShaderNodeMapping" and place.vector_type == 'POINT'
          and close(list(place.inputs["Location"].default_value), list(want[0]), 1e-6)
          and close(list(place.inputs["Rotation"].default_value), [0.0, 0.0, 0.5], 1e-6)
          and uv.bl_idname == "ShaderNodeUVMap" and uv.uv_map == "UVChannel_2")
    check("wiring: the placed image's Color masked (Clip) before its Output's invert, as CLIP's black was",
          clip is not None and _from(clip).bl_idname == "ShaderNodeMath" and out_inv.bl_idname == "ShaderNodeInvert")
    bump = _from(pb.inputs["Normal"])
    nm = _from(bump.inputs["Normal"])
    comb = _from(nm.inputs["Color"])
    red, green = _from(comb.inputs["Red"]), _from(comb.inputs["Green"])
    check("wiring: normal map swapped then flipped: Red = 1 - G, Green = 1 - R, Blue = B; its bump at 2 (1, distance 2)",
          bump.bl_idname == "ShaderNodeBump" and bump.inputs["Strength"].default_value == 1.0
          and bump.inputs["Distance"].default_value == 2.0 and abs(nm.inputs["Strength"].default_value - 0.7) < 1e-6
          and red.operation == 'SUBTRACT' and red.inputs[1].links[0].from_socket.identifier == "Green"
          and green.operation == 'SUBTRACT' and green.inputs[1].links[0].from_socket.identifier == "Red"
          and comb.inputs["Blue"].links[0].from_socket.identifier == "Blue")
    c = cm.MaterialIR(12, "Inverted", "test", base_color=cm.Input((0.2, 0.3, 0.4), cm.MapRef(5)))
    c.textures = {"bump": tx.TextureGraphIR(tx.Bump(data, -0.5), tx.BUMP),
                  "base_color": tx.TextureGraphIR(tx.Mix(tx.Constant((0.2, 0.3, 0.4)), srgb, 0.5, gamma), tx.COLOR)}
    d = cm.MaterialIR(13, "Lost", "test", alpha=cm.Input(0.8, cm.MapRef(6)), base_color=cm.Input((0.1, 0.2, 0.3),
                                                                                                  cm.MapRef(7)))
    d.textures = {"normal": tx.TextureGraphIR(tx.NormalMap(lost, 1.0, bump=tx.Bump(lost, 0.5)), tx.NORMAL),
                  "alpha": tx.TextureGraphIR(tx.Mix(tx.Constant(0.8), lost, 0.6), tx.DATA),
                  "base_color": tx.TextureGraphIR(tx.ColorCorrect(lost, hue=0.1), tx.COLOR)}
    mc, md = builder.make(c), builder.make(d)
    b = _from(_principled(mc).inputs["Normal"])
    check("wiring: a negative bump amount inverts the Bump node", b.invert and b.inputs["Strength"].default_value == 0.5)
    mask = _meaned(_input(_from(_principled(mc).inputs["Base Color"]), "Factor_Float"))
    check("wiring: a mask with a gamma override is decoded by a Gamma node of 1.8, then the mean (maxdrop-em3.122)",
          getattr(mask, "bl_idname", None) == "ShaderNodeGamma"
          and abs(_input(mask, "Gamma").default_value - 1.8) < 1e-6
          and getattr(_from(_input(mask, "Color")), "bl_idname", None) == "ShaderNodeTexImage")
    pd = _principled(md)
    check("wiring: missing images leave the IR's values: Normal free, alpha 0.8 (BLENDED), base color the swatch",
          not pd.inputs["Normal"].is_linked and not pd.inputs["Alpha"].is_linked
          and abs(pd.inputs["Alpha"].default_value - 0.8) < 1e-6 and md.surface_render_method == 'BLENDED'
          and not pd.inputs["Base Color"].is_linked
          and close(list(pd.inputs["Base Color"].default_value)[:3], [0.1, 0.2, 0.3], 1e-6)
          and not any(o.is_linked for n in md.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" for o in n.outputs)
          and len([n for n in md.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"]) == 1)


def check_reflection_falloff():
    """vray_texmaps imported: a Falloff in a VRayMtl's reflection drives the reflection weight by the angle (Layer
    Weight for perpendicular / parallel, the Fresnel node for Fresnel), not its color 1."""
    for name, kind in (("FixtureVReflPerp", "ShaderNodeLayerWeight"), ("FixtureVReflFresnel", "ShaderNodeFresnel")):
        m = bpy.data.materials.get(name)
        socket = _specular_socket(_principled(m)) if m is not None else None
        nodes = _upstream(socket) if socket is not None else []
        by_facing = [n for n in nodes if n.bl_idname == "ShaderNodeMix"
                     and getattr(_from(_input(n, "Factor_Float")), "bl_idname", None) == kind]
        check("vray_texmaps/%s: the reflection Falloff into the reflection weight, a Mix by %s" % (name, kind),
              socket is not None and socket.is_linked and len(by_facing) == 1,
              str(sorted(n.bl_idname for n in nodes)))


def check_wrapper_nodes():
    """texmap_wrappers imported with its textures found: the node types and links each wrapper is drawn with."""
    wants = {
        "FixtureWrapFalloff": {"ShaderNodeLayerWeight", "ShaderNodeFresnel", "ShaderNodeNewGeometry",
                               "ShaderNodeVectorMath:DOT_PRODUCT", "ShaderNodeMath:MULTIPLY_ADD", "ShaderNodeMix:MIX"},
        "FixtureWrapComposite": {"ShaderNodeMix:MULTIPLY", "ShaderNodeMix:OVERLAY", "ShaderNodeMix:SCREEN",
                                 "ShaderNodeMix:ADD", "ShaderNodeLayerWeight", "ShaderNodeMath:MULTIPLY"},
        "FixtureWrapColor": {"ShaderNodeInvert", "ShaderNodeSeparateColor", "ShaderNodeCombineColor",
                             "ShaderNodeVectorMath:DOT_PRODUCT", "ShaderNodeMath:SUBTRACT", "ShaderNodeBrightContrast"},
        "FixtureWrapOutput": {"ShaderNodeVectorMath:MULTIPLY_ADD", "ShaderNodeVectorMath:SCALE",
                              "ShaderNodeVectorMath:ADD", "ShaderNodeSeparateColor", "ShaderNodeInvert"},
    }
    for name, want in wants.items():
        m = bpy.data.materials.get(name)
        kinds = _node_kinds(m) if m is not None else set()
        check("texmap_wrappers/%s: its wrappers' nodes" % name, want <= kinds, str(sorted(want - kinds)))
    p = _principled(bpy.data.materials["FixtureWrapFalloff"])
    mix = _decoded(_from(p.inputs["Base Color"]))
    check("texmap_wrappers: the gamma-off Falloff mixed as stored, under a Gamma node of 2.2 (maxdrop-6n0.6.18)",
          mix is not None and mix.bl_idname == "ShaderNodeMix")
    if mix is None:
        return
    side = _from(_input(mix, "A_Color"))
    check("texmap_wrappers: the Falloff's side 1 is lerp(color 1, its map, 0.6), by Layer Weight Facing",
          _from(_input(mix, "Factor_Float")).bl_idname == "ShaderNodeLayerWeight" and side.bl_idname == "ShaderNodeMix"
          and abs(_input(side, "Factor_Float").default_value - 0.6) < 1e-6
          and _from(_input(side, "B_Color")).bl_idname == "ShaderNodeTexImage")
    p = _principled(bpy.data.materials["FixtureWrapComposite"])
    top = _decoded(_from(p.inputs["Base Color"]))
    check("texmap_wrappers: the gamma-off Composite composited as stored, under a Gamma node of 2.2 (maxdrop-em3.158)",
          top is not None and top.bl_idname == "ShaderNodeMix")
    screen = _from(_input(top, "B_Color")) if top is not None else None
    check("texmap_wrappers: the Composite's top layer: Screen, then a clamped Mix by 0.7 times its image's alpha",
          screen is not None and screen.blend_type == 'SCREEN' and top.clamp_result
          and _from(_input(top, "Factor_Float")).operation == 'MULTIPLY'
          and abs(_from(_input(top, "Factor_Float")).inputs[1].default_value - 0.7) < 1e-6)


def check_wrapper_wiring(builder, cm, tx, srgb, data):
    """The nodes of the wrappers maxdrop-3gc.3 draws (Falloff's Facing, Composite blend modes and masks, Color
    Correction rewiring, Adjust, Tint) on a hand-made IR, against the measured 3ds Max rules."""
    L = tx.CompositeLayer
    tinted = tx.Tint(srgb, (1.0, 0.5, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    adjusted = tx.Adjust(srgb, tx.TexOutput(level=2.0, offset=0.1))
    custom = tx.ColorCorrect(srgb, rewire=(2, 4, tx.RW_MONO))
    comp = tx.Composite((L(srgb), L(tinted, 0.5, tx.SCREEN, data), L(adjusted, 1.0, tx.SPOTLIGHT_BLEND),
                         L(custom, 0.25, tx.HARD_LIGHT)))
    w = cm.MaterialIR(14, "Wrappers", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)),
                      roughness=cm.Input(0.4, cm.MapRef(1)), metallic=cm.Input(0.0, cm.MapRef(1)),
                      emission_color=cm.Input((0.0,) * 3, cm.MapRef(1)), specular=cm.Input(0.5, cm.MapRef(1)),
                      transmission=cm.Input(0.0, cm.MapRef(1)))
    w.textures = {
        "base_color": tx.TextureGraphIR(tx.Mix(tx.Constant((0.0,) * 3), srgb, 0.0, tx.Facing(tx.PERPENDICULAR)),
                                        tx.COLOR),
        "roughness": tx.TextureGraphIR(tx.Mix(tx.Constant(0.2), tx.Constant(0.8), 0.0, tx.Facing(tx.FRESNEL, 1.45)),
                                       tx.DATA),
        "metallic": tx.TextureGraphIR(tx.Mix(tx.Constant(0.0), tx.Constant(1.0), 0.0, tx.Facing(tx.TOWARDS)),
                                      tx.DATA),
        "emission_color": tx.TextureGraphIR(comp, tx.COLOR),
        "specular": tx.TextureGraphIR(tx.ColorCorrect(srgb, rewire=tx.REWIRE_MONO), tx.COLOR),
        "transmission": tx.TextureGraphIR(tx.ColorCorrect(srgb, rewire=tx.REWIRE_INVERT), tx.COLOR)}
    mw = builder.make(w)
    check("wrappers: material built", mw is not None)
    if mw is None:
        return
    p = _principled(mw)
    mix = _from(p.inputs["Base Color"])
    lw = _from(_input(mix, "Factor_Float"))
    check("wrappers: Falloff perpendicular / parallel: a Mix by Layer Weight Facing at blend 0.5",
          mix.bl_idname == "ShaderNodeMix" and lw.bl_idname == "ShaderNodeLayerWeight"
          and _input(mix, "Factor_Float").links[0].from_socket.identifier == "Facing"
          and abs(_input(lw, "Blend").default_value - 0.5) < 1e-6
          and _from(_input(mix, "B_Color")).bl_idname == "ShaderNodeTexImage")
    mix = _from(p.inputs["Roughness"])
    fr = _from(_input(mix, "Factor_Float"))
    check("wrappers: Falloff Fresnel: a float Mix by the Fresnel node at IOR 1.45",
          mix.bl_idname == "ShaderNodeMix" and mix.data_type == 'FLOAT' and fr.bl_idname == "ShaderNodeFresnel"
          and abs(_input(fr, "IOR").default_value - 1.45) < 1e-6
          and abs(_input(mix, "A_Float").default_value - 0.2) < 1e-6)
    mix = _from(p.inputs["Metallic"])
    ma = _from(_input(mix, "Factor_Float"))
    dot = _from(ma.inputs[0]) if ma is not None else None
    geo = {link.from_socket.identifier for s in dot.inputs for link in s.links} if dot is not None else set()
    check("wrappers: Falloff towards / away: (1 - Normal . Incoming) / 2 of the Geometry node",
          ma.bl_idname == "ShaderNodeMath" and ma.operation == 'MULTIPLY_ADD'
          and (ma.inputs[1].default_value, ma.inputs[2].default_value) == (-0.5, 0.5)
          and dot.operation == 'DOT_PRODUCT' and geo == {"Normal", "Incoming"})
    dot = _from(_from(_specular_socket(p)).inputs[0])
    check("wrappers: Color Correction monochrome: the mean of the channels",
          dot.bl_idname == "ShaderNodeVectorMath" and dot.operation == 'DOT_PRODUCT'
          and close(list(_input(dot, "Vector_001").default_value), [1 / 3.0] * 3, 1e-6)
          and _from(_input(dot, "Vector")).bl_idname == "ShaderNodeTexImage")
    inv = _from(_from(p.inputs["Transmission Weight"]).inputs[0])
    check("wrappers: Color Correction invert: an Invert node", inv.bl_idname == "ShaderNodeInvert")
    top = _from(p.inputs["Emission Color"])
    hard = _from(_input(top, "B_Color"))
    comb = _from(_input(hard, "A_Color"))
    third = _from(_input(hard, "B_Color"))
    check("wrappers: Composite hard light at 25 %: Overlay with the layer as A over the result as B, then a clamped "
          "Mix by 0.25",
          top.blend_type == 'MIX' and top.clamp_result and abs(_input(top, "Factor_Float").default_value - 0.25) < 1e-6
          and hard.blend_type == 'OVERLAY' and abs(_input(hard, "Factor_Float").default_value - 1.0) < 1e-6
          and comb.bl_idname == "ShaderNodeCombineColor" and _from(_input(top, "A_Color")) == third)
    red, green, blue = (_input(comb, k).links[0] for k in ("Red", "Green", "Blue"))
    check("wrappers: Color Correction custom (B, 1 - R, mono): Separate / Combine Color",
          red.from_socket.identifier == "Blue" and red.from_node.bl_idname == "ShaderNodeSeparateColor"
          and green.from_node.operation == 'SUBTRACT' and green.from_node.inputs[1].links[0].from_socket.identifier
          == "Red" and blue.from_node.operation == 'DOT_PRODUCT')
    add = _from(_input(third, "B_Color"))
    mul = _from(_input(add, "B_Color"))
    adj = _from(_input(mul, "B_Color"))
    second = _from(_input(third, "A_Color"))
    check("wrappers: Composite spotlight blend: below + below x layer; the layer's Output times 2 plus 0.1",
          third.clamp_result and abs(_input(third, "Factor_Float").default_value - 1.0) < 1e-6
          and add.blend_type == 'ADD' and mul.blend_type == 'MULTIPLY' and _from(_input(add, "A_Color")) == second
          and _from(_input(mul, "A_Color")) == second and adj.operation == 'MULTIPLY_ADD'
          and close(list(_input(adj, "Vector_002").default_value), [0.1] * 3, 1e-6))
    screen = _from(_input(second, "B_Color"))
    factor = _from(_input(second, "Factor_Float"))
    tint = _from(_input(screen, "B_Color"))
    scales = [n for n in mw.node_tree.nodes if n.bl_idname == "ShaderNodeVectorMath" and n.operation == 'SCALE']
    mean = _from(factor.inputs[0])
    check("wrappers: Composite screen at 50 % with a mask: Screen of the Tint, Mix by mean(mask) x 0.5; Tint as "
          "three scales and two adds",
          screen.blend_type == 'SCREEN' and factor.operation == 'MULTIPLY'
          and abs(factor.inputs[1].default_value - 0.5) < 1e-6 and getattr(mean, "operation", None) == 'DOT_PRODUCT'
          and close(list(_input(mean, "Vector_001").default_value), [1 / 3.0] * 3, 1e-6)
          and _from(_input(mean, "Vector")).image.colorspace_settings.name == "Non-Color"
          and tint.operation == 'ADD' and len(scales) == 3
          and any(close(list(_input(n, "Vector").default_value), [1.0, 0.5, 0.0], 1e-6) for n in scales)
          and _from(_input(second, "A_Color")).bl_idname == "ShaderNodeTexImage")
    missing = tx.Image(9, "nothere.png", "nothere.png", "", None, colorspace=tx.NON_COLOR)
    lone = tx.Composite((L(tx.Constant(0.3)), L(missing, 1.0, tx.MULTIPLY_BLEND)))
    f = cm.MaterialIR(15, "LoneLayer", "test", roughness=cm.Input(0.4, cm.MapRef(1)))
    f.textures = {"roughness": tx.TextureGraphIR(tx.Invert(lone), tx.DATA)}
    mf = builder.make(f)
    rough = _principled(mf).inputs["Roughness"] if mf is not None else None
    check("wrappers: a blended Composite left with one constant layer in a float input (a glossiness map under an "
          "Invert) is that constant: 1 - 0.3",
          rough is not None and not rough.is_linked and abs(rough.default_value - 0.7) < 1e-6,
          "%s %s" % (mf, builder.issues()[-1:]))
