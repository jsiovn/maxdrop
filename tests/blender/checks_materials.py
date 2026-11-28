# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of the Principled BSDF: specular, the mirror, the refraction twin, the inputs, layers, media."""
import bpy

from .core import _mirror_inputs, check, close
from .tables import COAT_WEIGHT_LABEL, MIRROR_LABEL, REFRACTION_LABEL, SPECULAR_LEVEL, TIR_LABEL, TWIN_LABEL
from .nodes import (
    _alpha_of, _bsdfs, _color_into_float, _constant_one, _fold, _from, _images_of, _layers_of, _mean, _medium_of,
    _normal_linked, _on, _refracting, _same_inputs, _same_source, _shaders, _thin, _value_ok, _weight_factor,
    _weight_mix, LOST, MAP,
)


def check_specular(label, p, ir, present):
    """Specular IOR Level from the IR's reflection weight w: a weight map or a constant between 0 and 1 is a Mix
    Shader by w over a twin without reflection (Specular IOR Level 0.5 on p), else 0.5 x w (w taken at most 1) on p
    alone; a constant metal is 0.5 x w alone; a constant 0 on a transmitting p is a weight of 0 over the twin (bead
    maxdrop-em3.135: Specular IOR Level 0 leaves glass its reflection). With Fresnel off, refracting glass takes the
    mirror too (bead maxdrop-6n0.7.2)."""
    folded = _fold(ir.textures["specular"].root, present) if "specular" in ir.textures else LOST
    linked = folded is MAP
    w = None if linked else _mean(ir.specular.value if folded is LOST else folded)
    metal_glass = _constant_one(p, "Metallic")
    black_glass = not metal_glass and not linked and w <= 0 and _on(p, "Transmission Weight")
    lone = metal_glass or (not linked and not 0 < w < 1 and not black_glass)
    s, mix = p.inputs["Specular IOR Level"], _weight_mix(p)
    if lone:
        check("%s: Specular IOR Level %s, no reflection weight" % (label, "linked" if linked else "value"),
              mix is None and s.is_linked == linked and (linked or _value_ok(s, w * SPECULAR_LEVEL if metal_glass
                                                                       else max(0.0, min(1.0, w)) * SPECULAR_LEVEL)),
              "mix %s, linked %s, %r vs %r" % (mix is not None, s.is_linked, s.default_value, w))
        return
    fac = _weight_factor(mix) if mix is not None else None
    mirror = not ir.fresnel and (linked or ir.specular.map is None) and not black_glass
    level = 0.0 if mirror else SPECULAR_LEVEL
    w = 0.0 if black_glass else w
    check("%s: reflection weight %s %s, Specular IOR Level %.1f" % (
              label, "linked" if linked else "value", "under a mirror" if mirror else "over a twin", level),
          mix is not None and not s.is_linked and _value_ok(s, level) and fac.is_linked == linked
          and (linked or _value_ok(fac, w)),
          "mix %s, level %r, factor %r vs %r" % (mix is not None, s.default_value,
                                                  None if fac is None else fac.default_value, w))
    if mix is not None and mirror:
        check_mirror(label, p, mix, ir.mirror_color)
    elif mix is not None:
        (check_refraction_twin if _refracting(p) else check_twin)(label, p, mix)


def check_mirror(label, p, mix, color=(1.0, 1.0, 1.0)):
    """A weight without Fresnel: the Mix Shader's first shader is p (Specular IOR Level 0), its second p's copy as
    a metal of color (the IR's mirror_color: white, or a VRayMtl's tint, bead maxdrop-6n0.6.16): p's links and
    values but Metallic 1, Base Color color (both unlinked), Specular IOR Level 0.5. On refracting glass (bead
    maxdrop-6n0.7.2) the first shader is the refraction twin (check_refraction_twin)."""
    copy = _from(mix.inputs[2])
    refracts = _refracting(p)
    ok = copy is not None and copy.bl_idname == "ShaderNodeBsdfPrincipled" and copy.label == MIRROR_LABEL \
        and (refracts or _from(mix.inputs[1]) == p)
    bad = _same_inputs(p, copy, _mirror_inputs(color)) if ok else []
    tint = "white" if tuple(color[:3]) == (1.0, 1.0, 1.0) else "color %s" % (tuple(round(c, 3) for c in color[:3]),)
    check(label + ": the mirror is the Principled BSDF as a metal of " + tint, ok and bad == [], str(bad))
    if ok and refracts:
        check_refraction_twin(label, p, mix, copy)


def check_twin(label, p, mix):
    """The Mix Shader's first shader is p's twin: p's links and values, Specular IOR Level 0; its second p."""
    twin = _from(mix.inputs[1])
    ok = twin is not None and twin.bl_idname == "ShaderNodeBsdfPrincipled" and twin.label == TWIN_LABEL \
        and _from(mix.inputs[2]) == p
    bad = _same_inputs(p, twin, {"Specular IOR Level": 0.0}) if ok else []
    check(label + ": the twin is the Principled BSDF without reflection", ok and bad == [], str(bad))


def check_refraction_twin(label, p, mix, above=None):
    """Refracting glass (bead maxdrop-em3.135): the weight's first shader refracts without reflecting: a Refraction
    BSDF (its color the square root of p's Base Color, a constant's or a Gamma 0.5 on its link; a thin wall: the Base
    Color and IOR 1; p's Roughness, IOR and Normal), alone for a constant transmission of at least 1, else under p's
    twin (Specular IOR Level 0, Transmission Weight 0) by a Mix Shader whose factor is p's transmission. On a solid
    the weight is raised to 1 where a Fresnel node at p's IOR and normal is above 0.9999. The weight's second shader
    is above: p, or under a mirror its white-metal copy."""
    top, thin = _from(mix.inputs[1]), _thin(p)
    full = _constant_one(p, "Transmission Weight")
    if full:
        refr, ok = top, True
    else:
        ok = top is not None and top.bl_idname == "ShaderNodeMixShader" and top.label == TWIN_LABEL \
            and _same_source(p.inputs["Transmission Weight"], top.inputs[0])
        twin = _from(top.inputs[1]) if ok else None
        refr = _from(top.inputs[2]) if ok else None
        ok = ok and twin is not None and twin.bl_idname == "ShaderNodeBsdfPrincipled" and twin.label == TWIN_LABEL
        bad = _same_inputs(p, twin, {"Specular IOR Level": 0.0, "Transmission Weight": 0.0}) if ok else ["structure"]
        check(label + ": the refracting twin's Principled is the BSDF without reflection or transmission",
              ok and bad == [], str(bad))
    ok = ok and _from(mix.inputs[2]) == (p if above is None else above) and refr is not None \
        and refr.bl_idname == "ShaderNodeBsdfRefraction" and refr.label == REFRACTION_LABEL
    check(label + ": the twin refracts through a Refraction BSDF%s" % ("" if full else " by the transmission"), ok)
    if not ok:
        return
    base, color = p.inputs["Base Color"], refr.inputs["Color"]
    if thin:
        color_ok = _same_source(base, color)
    elif base.is_linked:
        root = _from(color)
        color_ok = root is not None and root.bl_idname == "ShaderNodeGamma" \
            and abs(root.inputs["Gamma"].default_value - 0.5) < 1e-6 and _same_source(base, root.inputs["Color"])
    else:
        color_ok = not color.is_linked and close(list(color.default_value)[:3],
                                                 [max(0.0, c) ** 0.5 for c in list(base.default_value)[:3]], 1e-5)
    ior = refr.inputs["IOR"]
    check(label + ": the Refraction BSDF's color is the %s" % ("Base Color (thin wall)" if thin else
                                                              "square root of the Base Color"), color_ok,
          "%r vs %r" % (list(color.default_value), list(base.default_value)))
    check(label + ": the Refraction BSDF has the roughness, normal and %s" % ("IOR 1" if thin else "IOR"),
          _same_source(p.inputs["Roughness"], refr.inputs["Roughness"])
          and _same_source(p.inputs["Normal"], refr.inputs["Normal"])
          and (abs(ior.default_value - 1.0) < 1e-6 if thin else _same_source(p.inputs["IOR"], ior)))
    maximum = _from(mix.inputs[0])
    if thin:
        check(label + ": no total internal reflection mask on a thin wall",
              maximum is None or maximum.label != TIR_LABEL)
        return
    greater = _from(maximum.inputs[1]) if maximum is not None and maximum.label == TIR_LABEL else None
    fresnel = _from(greater.inputs[0]) if greater is not None else None
    check(label + ": the weight is 1 where the glass reflects totally (Fresnel at its IOR > 0.9999)",
          greater is not None and maximum.operation == 'MAXIMUM'
          and greater.label == TIR_LABEL and greater.operation == 'GREATER_THAN'
          and abs(greater.inputs[1].default_value - 0.9999) < 1e-6 and fresnel is not None
          and fresnel.bl_idname == "ShaderNodeFresnel" and _same_source(p.inputs["IOR"], fresnel.inputs["IOR"])
          and _same_source(p.inputs["Normal"], fresnel.inputs["Normal"]))


def check_principled(label, material, ir, present=False):
    """A Blender material against its MaterialIR: every Principled input (linked when a node drives it, else the
    value the graph folds to, or the IR's when its images are missing), the render method, one Image Texture node
    per file. present: whether the texture files were found."""
    layers = _layers_of(ir)
    bsdfs = _bsdfs(material) if material is not None and material.node_tree else []
    p = bsdfs[0] if len(bsdfs) == 1 + len(layers) else None
    check(label + ": one Principled BSDF, and one per layer", p is not None, "%d for %d layers" % (len(bsdfs),
                                                                                              len(layers)))
    if p is None:
        return
    if layers:
        check_layers(label, material, layers, present)
    tex = ir.textures
    wants = [
        ("Base Color", "base_color", ir.base_color.value, None),
        ("Metallic", "metallic", ir.metallic.value, 1.0),
        ("Roughness", "roughness", ir.roughness.value, 1.0),
        ("Transmission Weight", "transmission", ir.transmission.value, 1.0),
        ("Emission Color", "emission_color", ir.emission_color.value, None),
        ("Alpha", "alpha", ir.alpha.value, 1.0),
    ]
    alpha = None
    check_specular(label, p, ir, present)
    for socket, key, want, scale in wants:
        s = p.inputs[socket]
        folded = _fold(tex[key].root, present) if key in tex else LOST
        linked = folded is MAP
        if folded not in (MAP, LOST):
            want = folded
        if scale is not None:
            want = _mean(want) * scale
        if socket == "Alpha":
            alpha = None if linked else want
        check("%s: %s %s" % (label, socket, "linked" if linked else "value"),
              s.is_linked == linked and (linked or _value_ok(s, want)),
              "linked %s, %r vs %r" % (s.is_linked, tuple(s.default_value) if hasattr(s.default_value, "__len__")
                                       else s.default_value, want))
    values = [("IOR", ir.ior), ("Emission Strength", ir.emission_strength), ("Coat Weight", ir.coat_weight),
              ("Coat Roughness", ir.coat_roughness), ("Coat IOR", ir.coat_ior), ("Coat Tint", ir.coat_color),
              ("Subsurface Weight", ir.subsurface_weight)]
    if ir.subsurface_weight > 0:
        values += [("Subsurface Radius", ir.subsurface_color), ("Subsurface Scale", ir.subsurface_radius)]
    if ir.sheen_weight > 0:
        values += [("Sheen Weight", ir.sheen_weight), ("Sheen Tint", ir.sheen_color),
                   ("Sheen Roughness", ir.sheen_roughness)]
    for socket, want in values:
        check("%s: %s" % (label, socket), _value_ok(p.inputs[socket], want),
              "%r vs %r" % (p.inputs[socket].default_value, want))
    normal = _normal_linked(tex, present)
    check(label + ": Normal linked iff a normal or bump map with its image", p.inputs["Normal"].is_linked == normal)
    thin = p.inputs.get("Thin Wall")
    check(label + ": Thin Wall", (thin is None and bpy.app.version < (5, 0, 0)) or
          (thin is not None and bool(thin.default_value) == ir.thin_walled))
    alphas = [(alpha is None, alpha)] + [_alpha_of(layer.ir, present) for layer in layers]
    from maxdrop.build import materials as build_materials
    output = next(n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
    volume_only = build_materials._volume_only(ir) and output.inputs["Volume"].is_linked  # no surface: maxdrop-6n0.6.29
    method = 'DITHERED' if volume_only or any(linked for linked, _v in alphas) else \
        'BLENDED' if any(v is not None and v < 1.0 for _l, v in alphas) else 'DITHERED'
    check(label + ": surface_render_method", material.surface_render_method == method,
          "%s vs %s" % (material.surface_render_method, method))
    want_images = sorted({img.name for img in _images_of(ir)})
    got_images = sorted({n.label for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"})
    check(label + ": one Image Texture node per file", got_images == want_images, "%s vs %s" % (got_images,
                                                                                               want_images))
    loose = [n.label for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.image is None
             and any(o.is_linked for o in n.outputs)]
    check(label + ": an Image Texture node without an image feeds nothing", loose == [], str(loose))
    mixed = _color_into_float(material)
    check(label + ": no color output linked into a float input (a data map is the mean of its channels)",
          mixed == [], str(mixed))
    check_medium(label, material, ir)


def check_medium(label, material, ir):
    """The Volume socket is linked iff the IR has a medium, and its nodes give back the IR's coefficients (relative
    1e-5: Blender stores float32) and anisotropy."""
    got = _medium_of(material) if material is not None and material.node_tree else None
    want = ir.medium
    check(label + ": Volume linked iff the IR has a medium", (got is None) == (want is None),
          "%s vs %s" % (got, want))
    if got is None or want is None:
        return
    check(label + ": the medium's nodes are Volume Scatter, Volume Absorption, Emission and Add Shaders",
          got["other"] == [], str(got["other"]))
    for field in ("scattering", "absorption", "emission"):
        g, w = got[field], list(getattr(want, field))
        check("%s: medium %s" % (label, field), all(abs(a - b) <= max(1e-6, 1e-5 * abs(b)) for a, b in zip(g, w)),
              "%s vs %s" % (g, w))
    if max(want.scattering) > 0:
        check(label + ": medium anisotropy", abs(got["anisotropy"][0] - want.anisotropy) <= 1e-6,
              "%s vs %s" % (got["anisotropy"], want.anisotropy))


def check_layers(label, material, layers, present=False):
    """A layered material: a Mix Shader per layer, the last one (or an added layer's Add Shader) into the output; an
    added layer (mode "add") an Add Shader over a Mix Shader from nothing (COAT_WEIGHT_LABEL); a layer whose mask graph
    a node drives has a linked factor, any other its amount (times the mask's constant)."""
    nodes = material.node_tree.nodes
    mixes = _shaders(material)
    check(label + ": a Mix Shader per layer", len(mixes) == len(layers), "%d for %d" % (len(mixes), len(layers)))
    adds = [n for n in nodes if n.bl_idname == "ShaderNodeAddShader" and _from(n.inputs[1]) in mixes
            and _from(n.inputs[1]).label == COAT_WEIGHT_LABEL and not _from(n.inputs[1]).inputs[1].is_linked]
    added = sum(1 for layer in layers if getattr(layer, "mode", "mix") == "add")
    check(label + ": an Add Shader per added layer, over its layer scaled from nothing", len(adds) == added
          and sum(1 for m in mixes if m.label == COAT_WEIGHT_LABEL) == added, "%d for %d" % (len(adds), added))
    out = next(n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial")
    surface = out.inputs["Surface"]
    check(label + ": the top Mix Shader (Add Shader for an added layer) is the surface",
          surface.is_linked and surface.links[0].from_node in mixes + adds)
    plain = []
    for layer in layers:
        folded = _fold(layer.graph.root, present) if layer.graph is not None else LOST
        if folded is not MAP:
            plain.append(round(min(1.0, layer.amount * (1.0 if folded is LOST else _mean(folded))), 5))
    plain.sort()
    got = sorted(round(m.inputs[0].default_value, 5) for m in mixes if not m.inputs[0].is_linked)
    linked = sum(1 for m in mixes if m.inputs[0].is_linked)
    check(label + ": the layers' amounts, masks linked", got == plain and linked == len(layers) - len(plain),
          "%s vs %s, %d linked" % (got, plain, linked))
