# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rules of VRayMtl, VRayLightMtl, VRayFastSSS2 and the V-Ray car paint materials."""
import dataclasses

from ..params import flag as _flag, num as _num
from .ids import METAL_REFLECTION
from .ir import Input
from .values import _clamp01, _ior, _mix, _roughness, ior_from_reflectance, mean


def vray_mtl(conv, m, ir):
    """VRayMtl: blocks 1 basic, 2 BRDF, 3 options, 4 maps (map id, on = id + 50, multiplier in % = id + 100)."""
    use_roughness = _flag(m, 89, 2, False)  # brdf_useRoughness
    diffuse = conv.rgb(m, 1, 1, (0.5, 0.5, 0.5))
    reflection = conv.rgb(m, 2, 1, (0.0, 0.0, 0.0))
    refraction = conv.rgb(m, 5, 1, (0.0, 0.0, 0.0))
    reflection_map = conv.map_ref(m, 101, 151, 201, 4, ir=ir)
    if reflection_map is not None and reflection_map.amount <= 0.0:  # shows nothing of itself: the swatch alone
        reflection_map = None

    t = _clamp01(mean(refraction))
    base = _mix(diffuse, refraction, t) if t > 0 else diffuse
    ir.base_color = Input(base, conv.map_ref(m, 100, 150, 200, 4, ir=ir))  # texmap_diffuse
    ir.roughness = Input(_roughness(_num(m, 3, 1, 1.0), use_roughness),  # reflection_glossiness
                         conv.map_ref(m, 104, 154, 204, 4, invert=not use_roughness, ir=ir))
    ir.metallic = Input(_clamp01(_num(m, 91, 1, 0.0)),  # reflection_metalness
                        conv.map_ref(m, 119, 169, 219, 4, ir=ir))
    ir.specular = Input(_clamp01(mean(reflection)), reflection_map)
    # the swatch's share of the slot: a map at full amount hides it (a Falloff there is a dielectric's ramp)
    hidden = min(1.0, reflection_map.amount) if reflection_map is not None else 0.0
    shown = mean(reflection) * (1.0 - hidden)
    ir.fresnel = _flag(m, 8, 1, True)  # reflection_fresnel
    # a swatch below 1 without a map is the mirror tinted R / max(R) by max(R): R_c + (1 - max R) d_c, V-Ray's R_c +
    # (1 - R_c) d_c for grey or a black diffuse; at max(R) 1 (build draws no mirror there) it is the metal
    top = max(reflection)
    metal_rule = not ir.fresnel and shown >= METAL_REFLECTION and (reflection_map is not None or top >= 1.0)
    if metal_rule:
        ir.metallic = Input(1.0)
        ir.base_color = Input(reflection, reflection_map)
    elif not ir.fresnel and shown >= METAL_REFLECTION:
        ir.specular = Input(top)
        ir.mirror_color = tuple(c / top for c in reflection)

    emit_map = conv.map_ref(m, 117, 167, 217, 4, ir=ir)  # texmap_self_illumination
    ir.emission_color = Input(conv.rgb(m, 81, 1, (0.0, 0.0, 0.0)), emit_map)  # selfIllumination
    if max(ir.emission_color.value) > 0 or emit_map is not None:
        ir.emission_strength = max(0.0, _num(m, 83, 1, 1.0))  # selfIllumination_multiplier

    ir.transmission = Input(t, conv.map_ref(m, 102, 152, 202, 4, ir=ir))  # texmap_refraction
    # Fresnel off outside the metal rule, not refracting (no refraction swatch or map): V-Ray renders R_c + (1 - m)
    # (1 - R_c) d_c, the metalness only dims the diffuse (maxdrop-6n0.6.39); the swatch scaled before the swatch rule
    # as a Standard's Diffuse Level is, its map by the rule's factor (MapRef.scale)
    metal = ir.metallic.value
    if not ir.fresnel and not metal_rule and t <= 0 and ir.transmission.map is None and ir.metallic.map is None \
            and metal > 0.0:
        k = conv.swatches.channel(1.0 - metal)
        ref = ir.base_color.map
        ir.base_color = Input(conv.rgb(m, 1, 1, (0.5, 0.5, 0.5), 1.0 - metal),
                              dataclasses.replace(ref, scale=ref.scale * k) if ref is not None and k > 0 else None)
        ir.metallic = Input(0.0)
    refraction_ior, reflection_ior = _num(m, 9, 1, 1.6), _num(m, 63, 1, 1.6)
    ir.ior = _ior(refraction_ior if t > 0 or _flag(m, 65, 1, True) else reflection_ior)  # reflection_lockIOR
    ir.thin_walled = _flag(m, 107, 1, False)  # refraction_thinWalled
    conv.bump_slot(ir, conv.map_ref(m, 103, 153, 203, 4, ir=ir))  # texmap_bump
    ir.alpha = Input(1.0, conv.map_ref(m, 112, 162, 212, 4, ir=ir))  # texmap_opacity

    ir.coat_weight = _clamp01(_num(m, 96, 1, 0.0))  # coat_amount
    ir.coat_color = conv.rgb(m, 97, 1, (1.0, 1.0, 1.0))
    ir.coat_roughness = _roughness(_num(m, 98, 1, 1.0), use_roughness)  # coat_glossiness
    ir.coat_ior = _ior(_num(m, 99, 1, 1.6))


def vray_light_mtl(conv, m, ir):
    """VRayLightMtl, block 0: 0 color, 1 multiplier, 2 / 3 texmap (on), 5 / 6 opacity_texmap (on)."""
    ir.base_color, ir.roughness, ir.specular = Input((0.0, 0.0, 0.0)), Input(1.0), Input(0.0)
    ir.emission_color = Input(conv.rgb(m, 0, 0, (1.0, 1.0, 1.0)), conv.map_ref(m, 2, 3, None, 0, ir=ir))
    ir.emission_strength = max(0.0, _num(m, 1, 0, 1.0))
    ir.alpha = Input(1.0, conv.map_ref(m, 5, 6, None, 0, ir=ir))


def vray_fast_sss2(conv, m, ir):
    """VRayFastSSS2, block 0: 26 diffuse_color, 27 / 28 / 29 its map (on, multiplier in %), 36 diffuse_amount,
    2 sub_surface_color, 0 scatter_radius (cm, a plain float: not in system units), 22 scale, 31 IOR,
    40 specular_color, 44 specular_amount, 51 specular_glossiness, 3 / 4 / 5 texmap_bump (on, multiplier: default
    30), 85 / 86 / 87 texmap_opacity (on, multiplier)."""
    ir.base_color = Input(conv.rgb(m, 26, 0, (0.5, 0.5, 0.5)), conv.map_ref(m, 27, 28, 29, 0, ir=ir))
    ir.roughness = Input(_roughness(_num(m, 51, 0, 0.6), False))
    amount = max(0.0, _num(m, 44, 0, 1.0))
    ir.specular = Input(_clamp01(amount * mean(conv.rgb(m, 40, 0, (1.0, 1.0, 1.0)))))
    ir.ior = _ior(_num(m, 31, 0, 1.3))
    ir.subsurface_weight = _clamp01(1.0 - _num(m, 36, 0, 0.0))
    ir.subsurface_color = conv.rgb(m, 2, 0, (0.5, 0.5, 0.5))
    ir.subsurface_radius = max(0.0, _num(m, 0, 0, 1.0) * _num(m, 22, 0, 1.0)) * 0.01
    conv.bump_slot(ir, conv.map_ref(m, 3, 4, 5, 0, ir=ir, default=30.0))
    ir.alpha = Input(1.0, conv.map_ref(m, 85, 86, 87, 0, ir=ir))


def _car_paint(conv, m, ir, base_gloss, bump_pid):
    """Both car paints, block 0: 0 base_color, 1 / 2 / 3 its map (on, multiplier in %), 4 base_reflection,
    8 base_glossiness, 27 coat_color, 39 coat_glossiness, then the base bump map, its on switch and its multiplier
    at bump_pid, bump_pid + 1, bump_pid + 2."""
    ir.base_color = Input(conv.rgb(m, 0, 0, (0.3, 0.4, 0.5)), conv.map_ref(m, 1, 2, 3, 0, ir=ir))
    ir.roughness = Input(_roughness(_num(m, 8, 0, base_gloss), False))
    ir.metallic = Input(1.0)
    ir.specular = Input(_clamp01(_num(m, 4, 0, 0.5)))
    ir.coat_color = conv.rgb(m, 27, 0, (1.0, 1.0, 1.0))
    ir.coat_roughness = _roughness(_num(m, 39, 0, 1.0), False)
    # a missing multiplier is read as 100; both car paints are created with 30 (docs/FORMAT.md), but what V-Ray does
    # with a file that lacks the parameter is not measured
    conv.bump_slot(ir, conv.map_ref(m, bump_pid, bump_pid + 1, bump_pid + 2, 0, ir=ir))


def vray_car_paint_mtl(conv, m, ir):
    """31 coat_strength: the coat's reflectance at normal incidence (default 0.05), not a weight; 55 / 56 / 57
    bump."""
    _car_paint(conv, m, ir, 0.6, 55)
    f0 = _clamp01(_num(m, 31, 0, 0.05))
    ir.coat_weight = 1.0 if f0 > 0 else 0.0
    ir.coat_ior = _ior(ior_from_reflectance(f0))


def vray_car_paint_mtl2(conv, m, ir):
    """31 coat_amount (weight), 81 coat_ior; 54 / 55 / 56 bump."""
    _car_paint(conv, m, ir, 0.4, 54)
    ir.coat_weight = _clamp01(_num(m, 31, 0, 1.0))
    ir.coat_ior = _ior(_num(m, 81, 0, 1.5))
