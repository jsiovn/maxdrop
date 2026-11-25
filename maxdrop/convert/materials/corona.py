# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rules of the Corona materials (Physical, Legacy, Light, Skin, Hair, Shadow Catcher, Volume) and their media."""
import dataclasses
import math

from ...reader import classids
from ...reader.classdir import ClassId
from .. import colors
from ..params import finite as _finite, flag as _flag, num as _num
from .ids import (
    CORONA_EDGE_DEFAULT, CORONA_MAX_F0, CORONA_MAX_IOR, CORONA_METAL_IOR, CORONA_SPECULAR_F0, GREY_SRGB, MAX_ANISOTROPY,
    MAX_MEDIUM_DENSITY, METAL_REFLECTION,
)
from .ir import Input, Medium
from .values import (
    _clamp01, _ior, _mix, _roughness, class_name, corona_legacy_roughness, f0_from_complex_ior, ior_from_reflectance,
    mean,
)


def _corona_amount_map(conv, m, map_pid, ir, invert=False):
    """A Corona map slot: the map at map_pid, its switch at + 1, its amount (a fraction) at + 2."""
    return conv.map_ref(m, map_pid, map_pid + 1, map_pid + 2, 0, invert=invert, ir=ir, percent=False)


def _corona_opacity(conv, m, pid, level, ref, ir):
    """A Corona opacity: the swatch at pid (mono_swatch) times its level, clamped to 0..1; a colored swatch is an
    issue only where it shows (a level above 0, no map at full amount over it)."""
    shown = level > 0.0 and (ref is None or ref.amount < 1.0)
    return _clamp01(conv.mono_swatch(m, pid, 0, (1.0, 1.0, 1.0), ir if shown else None) * level)


def _unread_map(conv, m, map_pid, ir, what):
    """A Corona map slot (map, switch at + 1) whose input the IR has no map for: an issue when a map is on there."""
    if conv.map_ref(m, map_pid, map_pid + 1, None, 0, ir=ir) is not None:
        conv.issue(m.index, "%s %r: %s map not converted" % (class_name(m.superclass, m.class_id), m.name, what), ir)


def _subsurface(conv, m, ir, weight_pid, radius_pid, color_pid):
    """Corona SSS: the amount as the subsurface weight, the radius (world units) in meters, the scatter color as the
    per-channel radius."""
    ir.subsurface_weight = _clamp01(_num(m, weight_pid, 0, 0.0))
    ir.subsurface_radius = max(0.0, _num(m, radius_pid, 0, 1.0)) * conv.meters
    ir.subsurface_color = conv.rgb(m, color_pid, 0, (1.0, 0.35, 0.2))


def corona_physical_mtl(conv, m, ir):
    """CoronaPhysicalMtl, block 0 (map, its switch and amount at id, id + 1, id + 2): 101 baseColor, 102 baseLevel,
    103 base map, 111 metalnessMode, 121 opacityColor, 122 opacityLevel, 123 opacity map, 131 baseRoughness,
    132 its map, 171 baseIor, 191 refractionAmount, 192 its map, 203 useThinMode, 211 clearcoatAmount,
    221 clearcoatIor, 231 clearcoatRoughness, 331 selfIllumColor, 332 selfIllumLevel, 333 its map, 351 baseBump map,
    381 thinAbsorptionColor, 391 clearcoatAbsorptionColor, 411 / 412 metalness map (on), 421 roughnessMode (1:
    every roughness is a glossiness, the sheen's too); 241 sheenAmount, 245 sheenColor, 251 sheenRoughness; 291
    sssAmount, 301 sssRadius (world units), 311 sssScatterColor; 451 useComplexIor, 452-454 n and 455-457 k per
    channel (a metal's base color is then the F0 they give). Translucency (371, 375), the edge color (161) and maps
    in the sheen and SSS slots are named issues. With refraction and without thin mode, a medium (corona_medium):
    261 volumetricAbsorptionColor, 271 volumetricScatteringColor, 281 attenuationDistance, 282
    scatterDirectionality; its maps (262 / 263, 272 / 273) and 283 scatterSingleBounce are named.
    461 iorMode (Corona 12 renders, maxdrop-em3.115): 0 the IOR parameters (171, 221) are IORs; 1 they are specular
    levels, F0 = CORONA_SPECULAR_F0 x level (MAXScript's setter converts them on a mode change); 2 renders as an IOR
    (not a mode the UI offers): named. No IOR reflects more than F0 CORONA_MAX_F0 (IOR 3), and a base IOR below 1
    reflects as its reciprocal: a material that does not refract (no refraction amount, no refraction map) takes its
    base IOR so (_corona_reflection_ior); a refracting one keeps it (its refraction through such an IOR was not
    measured: clamped to 1..100), named when it is outside 1..3. The clearcoat IOR is left as it is (whether the same
    cap holds was not measured: an IOR 2 coat rendered as IOR 2).
    Translucency only works in thin mode (fraction 0.5 without it: no light through). The edge color is not Blender's
    Specular Tint: a white edge brightens the grazing reflection above Schlick, a black one darkens it, and the default
    0.75 is close to Schlick; no single tint, Gulbrandsen edge tint or conductor fits the renders (FORMAT.md)."""
    gloss = m.param(421, 0) == 1
    ior_mode = m.param(461, 0)
    level = max(0.0, _num(m, 102, 0, 1.0))
    base = tuple(min(1.0, c * level) for c in conv.rgb(m, 101, 0, (0.5, 0.5, 0.5)))
    t = _clamp01(_num(m, 191, 0, 0.0))
    thin = _flag(m, 203, 0, False)
    if t > 0:  # the refraction is clear unless thin mode tints it
        base = _mix(base, conv.rgb(m, 381, 0, (1.0, 1.0, 1.0)) if thin else (1.0, 1.0, 1.0), t)
    ir.base_color = Input(base, _corona_amount_map(conv, m, 103, ir))
    r = _clamp01(_num(m, 131, 0, 0.75))
    ir.roughness = Input(1.0 - r if gloss else r, _corona_amount_map(conv, m, 132, ir, invert=gloss))
    ir.metallic = Input(1.0 if m.param(111, 0) == 1 else 0.0, conv.map_ref(m, 411, 412, None, 0, ir=ir))
    ir.transmission = Input(t, _corona_amount_map(conv, m, 192, ir))
    refracts = t > 0 or ir.transmission.map is not None
    ir.ior = _corona_ior(m, 171, ior_mode, reflects_only=not refracts)
    base_ior = _num(m, 171, 0, 1.5)
    if refracts and ior_mode != 1 and not 1.0 <= base_ior <= CORONA_MAX_IOR:
        conv.issue(m.index, "CoronaPhysicalMtl %r: base IOR %g outside 1..%g on a refracting material drawn as IOR %g: "
                   "Corona reflects it as IOR %g, its refraction not measured" % (
                       m.name, base_ior, CORONA_MAX_IOR, ir.ior, _corona_reflection_ior(base_ior)), ir)
    ir.specular = Input(1.0)  # no reflection level in the pblock: the IOR's own Fresnel
    if ior_mode not in (None, 0, 1):
        conv.issue(m.index, "CoronaPhysicalMtl %r: unknown IOR mode %r read as an IOR" % (m.name, ior_mode), ir)
    ir.thin_walled = thin
    ref = _corona_amount_map(conv, m, 123, ir)
    ir.alpha = Input(_corona_opacity(conv, m, 121, max(0.0, _num(m, 122, 0, 1.0)), ref, ir), ref)
    ir.emission_color = Input(conv.rgb(m, 331, 0, (1.0, 1.0, 1.0)), _corona_amount_map(conv, m, 333, ir))
    ir.emission_strength = max(0.0, _num(m, 332, 0, 0.0))
    ir.coat_weight = _clamp01(_num(m, 211, 0, 0.0))
    ir.coat_ior = _corona_ior(m, 221, ior_mode)
    c = _clamp01(_num(m, 231, 0, 0.0))
    ir.coat_roughness = 1.0 - c if gloss else c
    ir.coat_color = conv.rgb(m, 391, 0, (1.0, 1.0, 1.0))
    conv.bump_slot(ir, _corona_amount_map(conv, m, 351, ir))
    sheen_r = _clamp01(_num(m, 251, 0, 0.3))
    ir.sheen_weight = _clamp01(_num(m, 241, 0, 0.0))
    ir.sheen_color = conv.rgb(m, 245, 0, (1.0, 1.0, 1.0))
    ir.sheen_roughness = 1.0 - sheen_r if gloss else sheen_r
    _subsurface(conv, m, ir, 291, 301, 311)
    for pid, what in ((242, "sheen amount"), (246, "sheen color"), (252, "sheen roughness"), (292, "SSS amount"),
                      (302, "SSS radius"), (312, "SSS scatter color")):
        _unread_map(conv, m, pid, ir, what)
    if _flag(m, 451, 0, False) and ir.metallic.value == 1.0:
        n = [_num(m, pid, 0, 1.0) for pid in (452, 453, 454)]
        k = [_num(m, pid, 0, 0.0) for pid in (455, 456, 457)]
        ir.base_color = Input(tuple(_clamp01(f0_from_complex_ior(a, b)) for a, b in zip(n, k)))
    elif ir.metallic.value == 1.0 or ir.metallic.map is not None:
        edge = m.param(161, 0)
        if isinstance(edge, tuple) and any(_finite(c) and abs(c - CORONA_EDGE_DEFAULT) > 1e-4 for c in edge[:3]):
            conv.issue(m.index, "CoronaPhysicalMtl %r: metal edge color not converted" % (m.name,), ir)
    if thin and (_num(m, 371, 0, 0.0) > 0 or conv.map_ref(m, 372, 373, None, 0, ir=ir) is not None):
        conv.issue(m.index, "CoronaPhysicalMtl %r: translucency not converted" % (m.name,), ir)
    if t > 0 and not thin:
        _corona_volume(conv, m, ir, 281, 261, 271, 282, ((262, 263, "absorption"), (272, 273, "scattering")), 283)


def _corona_reflection_ior(v):
    """The IOR a CoronaPhysicalMtl base IOR reflects as (Corona 12 renders, maxdrop-em3.115): below 1 its reciprocal,
    at most CORONA_MAX_IOR; 0 or below (a damaged value) 1."""
    if v <= 0.0:
        return 1.0
    return min(CORONA_MAX_IOR, max(v, 1.0 / v))


def _corona_ior(m, pid, ior_mode, reflects_only=False):
    """A CoronaPhysicalMtl IOR parameter (default 1.5): an IOR, or in IOR mode 1 a specular level made an IOR.
    reflects_only: an IOR (not mode 1) of a material that does not refract, taken as Corona reflects it."""
    if ior_mode != 1:
        v = _num(m, pid, 0, 1.5)
        return _ior(_corona_reflection_ior(v) if reflects_only else v)
    level = max(0.0, _num(m, pid, 0, 0.5))  # mode 1's value of IOR 1.5
    return _ior(ior_from_reflectance(min(CORONA_MAX_F0, CORONA_SPECULAR_F0 * level)))


def corona_legacy_mtl(conv, m, ir):
    """CoronaLegacyMtl (CoronaMtl), block 0: colors 101 diffuse, 102 reflect, 103 refract, 105 opacity, 107
    selfIllum; their levels 121, 122, 123, 127, 128 (the first four scale the map in their slot as well, as Corona's
    documentation has it: the MapRef's scale, no map at level 0; 128 is the emission strength); maps 141 diffuse,
    142 reflect, 143 reflectGlossiness, 144 refract, 146 opacity, 147 bump, 158 selfIllum, each switched on by id +
    20, with amounts (fractions) 290, 291, 292, 293, 295, 296, 303; 180 reflectGlossiness, 182 fresnelIor, 183 ior,
    210 thin; 410 levelSss, 411 sssRadius (world units), 412 sssScatterColor. 402 pbrMode off curves the glossiness
    otherwise (Corona 12 renders, maxdrop-em3.115): its roughness is corona_legacy_roughness; a glossiness
    map then stays 1 - the map, a named issue. Translucency (106, 126, map 148) and the SSS amount map (414) are named
    issues. With refraction and without thin, in media mode 1 (427; the default, also when not stored), a medium
    (corona_medium): 188 absorptionDistance, 190 absorptionColor, 215 scatterColor, 216 scatterDirectionality; its
    maps (305 / 306, 308 / 309), 315 singleBounceOnly and media mode 0 (Corona 12 renders the slab black) are
    named."""
    def slot(map_pid, on_pid, amount_pid, invert=False, level=1.0):
        ref = conv.map_ref(m, map_pid, on_pid, amount_pid, 0, invert=invert, ir=ir, percent=False)
        if ref is None or level == 1.0:
            return ref
        return dataclasses.replace(ref, scale=level) if level > 0.0 else None
    levels = [max(0.0, _num(m, pid, 0, d)) for pid, d in ((121, 1.0), (122, 0.0), (123, 0.0), (127, 1.0))]
    diffuse_level, reflect_level, refract_level, opacity_level = levels
    diffuse = tuple(min(1.0, c * diffuse_level) for c in conv.rgb(m, 101, 0, (0.5, 0.5, 0.5)))
    reflect_color = conv.rgb(m, 102, 0, (1.0, 1.0, 1.0))
    reflection = tuple(min(1.0, c * reflect_level) for c in reflect_color)
    refract_color = conv.rgb(m, 103, 0, (1.0, 1.0, 1.0))
    t = _clamp01(mean(refract_color) * refract_level)
    reflection_map = slot(142, 162, 291, level=reflect_level)
    fresnel_ior = _num(m, 182, 0, 1.52)
    ir.base_color = Input(_mix(diffuse, refract_color, t) if t > 0 else diffuse, slot(141, 161, 290,
                                                                                     level=diffuse_level))
    ir.specular = Input(_clamp01(mean(reflection)), reflection_map)
    pbr = _flag(m, 402, 0, True)
    gloss = _num(m, 180, 0, 1.0)
    gloss_map = slot(143, 163, 292, invert=True)
    ir.roughness = Input(_roughness(gloss, False) if pbr else corona_legacy_roughness(gloss), gloss_map)
    # the swatch's share of the slot, as vray_mtl's (the level multiplies swatch and map alike: it stays in it)
    hidden = min(1.0, reflection_map.amount) if reflection_map is not None else 0.0
    if fresnel_ior >= CORONA_METAL_IOR and mean(reflection) * (1.0 - hidden) >= METAL_REFLECTION:
        ir.metallic = Input(1.0)
        ir.base_color = Input(reflection, reflection_map)
    ir.transmission = Input(t, slot(144, 164, 293, level=refract_level))
    ir.ior = _ior(_num(m, 183, 0, 1.52) if t > 0 else fresnel_ior)
    ir.thin_walled = _flag(m, 210, 0, False)
    ref = slot(146, 166, 295, level=opacity_level)
    ir.alpha = Input(_corona_opacity(conv, m, 105, opacity_level, ref, ir), ref)
    ir.emission_color = Input(conv.rgb(m, 107, 0, (1.0, 1.0, 1.0)), slot(158, 178, 303))
    ir.emission_strength = max(0.0, _num(m, 128, 0, 0.0))
    conv.bump_slot(ir, slot(147, 167, 296))
    _subsurface(conv, m, ir, 410, 411, 412)
    if slot(414, 417, None) is not None:
        conv.issue(m.index, "CoronaLegacyMtl %r: SSS amount map not converted" % (m.name,), ir)
    if not pbr and gloss_map is not None and (mean(reflection) > 0 or reflection_map is not None):
        conv.issue(m.index, "CoronaLegacyMtl %r: glossiness map of PBR mode off read as in PBR mode" % (m.name,), ir)
    if _num(m, 126, 0, 0.0) > 0 or slot(148, 168, None) is not None:
        conv.issue(m.index, "CoronaLegacyMtl %r: translucency not converted" % (m.name,), ir)
    if t > 0 and not ir.thin_walled:
        mode = _num(m, 427, 0, 1.0)
        if mode == 1:
            _corona_volume(conv, m, ir, 188, 190, 215, 216, ((305, 306, "absorption"), (308, 309, "scattering")), 315)
        elif _num(m, 188, 0, 0.0) > 0:
            conv.issue(m.index, "CoronaLegacyMtl %r: media mode %g not converted (Corona 12 renders it black)"
                       % (m.name, mode), ir)


def corona_light_mtl(conv, m, ir):
    """CoronaLightMtl, block 0: 110 intensity, 111 / 112 texmap (on), 113 color, 150 / 151 opacityTexmap (on)."""
    ir.base_color, ir.roughness, ir.specular = Input((0.0, 0.0, 0.0)), Input(1.0), Input(0.0)
    ir.emission_color = Input(conv.rgb(m, 113, 0, (1.0, 1.0, 1.0)), conv.map_ref(m, 111, 112, None, 0, ir=ir))
    ir.emission_strength = max(0.0, _num(m, 110, 0, 1.0))
    ir.alpha = Input(1.0, conv.map_ref(m, 150, 151, None, 0, ir=ir))


def _num_tab(m, pid, k, default):
    v = m.param(pid, 0, tab=k)
    return float(v) if _finite(v) and not isinstance(v, bool) else default


def _flag_tab(m, pid, k, default):
    v = m.param(pid, 0, tab=k)
    return bool(v) if _finite(v) else default


def corona_skin_mtl(conv, m, ir):
    """CoronaSkinMtl, block 0, approximated as one Principled layer: base = skinColor x skinLevel (map 124, switch
    145, amount 166); subsurface weight = sssAmount (103); the three SSS layers (color, radius in world units,
    weight: 105-107, 108-110, 111-113) as one: radius = sssRadiusScale (104) x their weighted mean radius, per-channel
    color their weighted mean color; specular = reflection1Level (115) x the mean of reflection1Color (114),
    roughness = 1 - reflection1Glossiness (116, map 137 / 158 / 179 inverted), ior = reflection1Ior (117);
    alpha = mono_swatch(opacityColor 122) x opacityLevel (123), map 143 / 164 / 185; bump 144 / 165 / 186. The second
    reflection and the SSS maps are named issues."""
    def slot(map_pid, invert=False):
        return conv.map_ref(m, map_pid, map_pid + 21, map_pid + 42, 0, invert=invert, ir=ir, percent=False)
    level = max(0.0, _num(m, 102, 0, 1.0))
    skin = conv.rgb(m, 101, 0, (143 / 255, 70 / 255, 41 / 255))
    ir.base_color = Input(tuple(min(1.0, c * level) for c in skin), slot(124))
    layers = [(conv.rgb(m, c, 0, (1.0, 1.0, 1.0)), max(0.0, _num(m, r, 0, 1.0)), max(0.0, _num(m, w, 0, 1.0)))
              for c, r, w in ((105, 106, 107), (108, 109, 110), (111, 112, 113))]
    total = sum(w for _c, _r, w in layers)
    ir.subsurface_weight = _clamp01(_num(m, 103, 0, 1.0)) if total > 0 else 0.0
    if total > 0:
        ir.subsurface_color = tuple(sum(c[i] * w for c, _r, w in layers) / total for i in range(3))
        radius = sum(r * w for _c, r, w in layers) / total
        ir.subsurface_radius = max(0.0, _num(m, 104, 0, 1.0)) * radius * conv.meters
    reflection = mean(conv.rgb(m, 114, 0, (1.0, 1.0, 1.0)))
    ir.specular = Input(_clamp01(max(0.0, _num(m, 115, 0, 1.0)) * reflection), slot(135))
    ir.roughness = Input(_roughness(_num(m, 116, 0, 0.5), False), slot(137, invert=True))
    ir.ior = _ior(_num(m, 117, 0, 1.4))
    ref = slot(143)
    ir.alpha = Input(_corona_opacity(conv, m, 122, max(0.0, _num(m, 123, 0, 1.0)), ref, ir), ref)
    conv.bump_slot(ir, slot(144))
    if _num(m, 119, 0, 0.0) > 0:
        conv.issue(m.index, "CoronaSkinMtl %r: second reflection not converted" % (m.name,), ir)
    if any(slot(pid) is not None for pid in range(125, 135)):
        conv.issue(m.index, "CoronaSkinMtl %r: SSS maps not converted" % (m.name,), ir)


# CoronaHairMtl's color on a mesh, measured on Corona 12 renders (maxdrop-em3.164: planes in a white furnace, every
# channel R + P0 x exp(-u), R = 0.070 the colorless specular, P0 = 0.929): u has the shape of the eumelanin and
# pheomelanin absorption Cycles' Principled Hair BSDF uses (its channel ratios), the melanin's weight is
# HAIR_MELANIN[0] m^2 + HAIR_MELANIN[1] m^3 (largest error 0.009 over melanin 0..1), Corona's pheomelanin (the share
# of the melanin that is red) absorbs HAIR_PHEOMELANIN_SCALE x Cycles' and a tint t adds HAIR_TINT x ln(t)^2
HAIR_EUMELANIN = (0.506, 0.841, 1.653)
HAIR_PHEOMELANIN = (0.343, 0.733, 1.924)
HAIR_MELANIN = (7.68, 1.2)
HAIR_PHEOMELANIN_SCALE = 0.685
HAIR_TINT = 0.054
HAIR_FLOOR = 1e-4  # the tint's floor (ln 0): a black tint leaves 0.010, Corona the colorless floor only
# The base color that renders a mesh as Corona does in that furnace: Corona's colorless floor HAIR_SPECULAR plus
# HAIR_PIGMENT x the color, against the Principled BSDF's own HAIR_PRINCIPLED_SPECULAR (Cycles 5.2, IOR 1.55,
# roughness 0.5: CoronaHairMtl's defaults) plus the rest x the base color
HAIR_SPECULAR = 0.070
HAIR_PIGMENT = 0.929
HAIR_PRINCIPLED_SPECULAR = 0.043
# CoronaHairMtl map slots no input of the IR takes: (map, its switch, what)
HAIR_UNREAD = ((112, 121, "tint"), (113, 122, "diffuse"), (115, 124, "IOR"), (117, 126, "softness"),
               (118, 127, "colorless glossiness"), (119, 128, "highlight shift"), (144, 146, "melanin"),
               (145, 147, "pheomelanin"), (153, 156, "colorless specular"), (154, 157, "colored specular"),
               (155, 158, "transmission"), (163, 164, "glint strength"))


def hair_color(melanin, pheomelanin, tint):
    """The linear color Corona 12 gives a mesh with CoronaHairMtl of this melanin (0..1), pheomelanin (the share of
    the melanin that is red, 0..1) and tint (linear RGB), its colorless specular left out: exp(-u) per channel, u =
    (HAIR_MELANIN[0] m^2 + HAIR_MELANIN[1] m^3) x ((1 - p) HAIR_EUMELANIN + p HAIR_PHEOMELANIN_SCALE HAIR_PHEOMELANIN)
    + HAIR_TINT ln(tint)^2."""
    m, p = _clamp01(melanin), _clamp01(pheomelanin)
    k = HAIR_MELANIN[0] * m * m + HAIR_MELANIN[1] * m ** 3
    out = []
    for eu, pheo, t in zip(HAIR_EUMELANIN, HAIR_PHEOMELANIN, tint):
        u = k * ((1.0 - p) * eu + p * HAIR_PHEOMELANIN_SCALE * pheo) + HAIR_TINT * math.log(
            min(1.0, max(HAIR_FLOOR, t))) ** 2
        out.append(math.exp(-u))
    return tuple(out)


def corona_hair_mtl(conv, m, ir):
    """CoronaHairMtl, block 0, as one Principled layer (Corona 12 renders, maxdrop-em3.164): the hair h =
    hair_color(melanin 141, pheomelanin 142, tint colorTint 101 x levelTint 104) x transmission (152) renders as a
    base of (HAIR_SPECULAR + HAIR_PIGMENT h - HAIR_PRINCIPLED_SPECULAR) / (1 - HAIR_PRINCIPLED_SPECULAR); base = d +
    (1 - max d) x that, d = colorDiffuse (102) x levelDiffuse (105), at most 1 (a grey d mixes so exactly, a colored
    one about so); roughness = 1 - glossiness (108, map 116 / 125 / 134 inverted); ior (107); specular 1; alpha =
    mono_swatch(colorOpacity 103) x levelOpacity (106), map 114 / 123 / 132; bump 120 / 129 / 138. Maps in the other
    slots (HAIR_UNREAD) are named issues, the tint map too (Corona adds it to the melanin's absorption: a curve no map
    input draws). Softness, colorless glossiness, highlight shift and GI simplification change no furnace albedo;
    the glint and the specular colors are not read; randomizeMelanin (143) above 0, which lightens a mesh (0.5: blue
    0.099 -> 0.293), is a named issue."""
    def slot(map_pid, invert=False):
        return conv.map_ref(m, map_pid, map_pid + 9, map_pid + 18, 0, invert=invert, ir=ir, percent=False)
    tint = tuple(c * max(0.0, _num(m, 104, 0, 1.0)) for c in conv.rgb(m, 101, 0, (1.0, 1.0, 1.0)))
    diffuse = tuple(c * max(0.0, _num(m, 105, 0, 1.0)) for c in conv.rgb(m, 102, 0, (0.0, 0.0, 0.0)))
    transmission = conv.rgb(m, 152, 0, (1.0, 1.0, 1.0))
    color = hair_color(_num(m, 141, 0, 0.5), _num(m, 142, 0, 0.0), tint)
    principled = 1.0 - HAIR_PRINCIPLED_SPECULAR
    hair = [_clamp01((HAIR_SPECULAR - HAIR_PRINCIPLED_SPECULAR + HAIR_PIGMENT * c * t) / principled)
            for c, t in zip(color, transmission)]
    w = _clamp01(max(diffuse))
    ir.base_color = Input(tuple(min(1.0, d + (1.0 - w) * h) for h, d in zip(hair, diffuse)))
    ir.roughness = Input(_roughness(_num(m, 108, 0, 0.5), False), slot(116, invert=True))
    ir.ior = _ior(_num(m, 107, 0, 1.55))
    ref = slot(114)
    ir.alpha = Input(_corona_opacity(conv, m, 103, max(0.0, _num(m, 106, 0, 1.0)), ref, ir), ref)
    conv.bump_slot(ir, slot(120))
    for map_pid, on_pid, what in HAIR_UNREAD:
        if conv.map_ref(m, map_pid, on_pid, None, 0, ir=ir) is not None:
            conv.issue(m.index, "CoronaHairMtl %r: %s map not converted" % (m.name, what), ir)
    if _num(m, 143, 0, 0.0) > 0:
        conv.issue(m.index, "CoronaHairMtl %r: randomize melanin not converted" % (m.name,), ir)


def corona_shadow_catcher_mtl(conv, m, ir):
    """CoronaShadowCatcherMtl, block 0: the grey material with shadow_catcher set (build/objects.py makes an object
    whose every slot holds one a shadow catcher). A backplate map (302, switch 360) and a reflection (reflectLevel 306
    above 0) are named issues."""
    g = colors.srgb_to_linear(GREY_SRGB)
    ir.base_color, ir.shadow_catcher = Input((g, g, g)), True
    if conv.map_ref(m, 302, 360, None, 0, ir=ir) is not None:
        conv.issue(m.index, "CoronaShadowCatcherMtl %r: backplate map not converted" % (m.name,), ir)
    if _num(m, 306, 0, 0.0) > 0:
        conv.issue(m.index, "CoronaShadowCatcherMtl %r: reflection not converted" % (m.name,), ir)


def corona_medium(conv, color, distance, albedo, directionality, emission=(0.0, 0.0, 0.0), emission_distance=0.0):
    """A Corona medium (Corona 12 renders, maxdrop-em3.163), None when it has nothing: color (linear) is the
    transmission at distance (world units; 0 or less: no extinction), per channel, sigma_t = -ln(color) / distance;
    albedo the share of it that scatters (sigma_s = albedo x sigma_t, sigma_a the rest); directionality a
    Henyey-Greenstein g (clamped to MAX_ANISOTROPY); emission (linear) the light added over emission_distance, per
    meter emission / that distance. Coefficients at most MAX_MEDIUM_DENSITY."""
    def per_meter(d):
        return d * conv.meters if _finite(d) and d > 0 else 0.0
    d = per_meter(distance)
    t = tuple(min(MAX_MEDIUM_DENSITY, max(0.0, -math.log(max(c, 1e-300)) / d)) if d > 0 else 0.0
              for c in (_clamp01(c) for c in color))
    a = tuple(_clamp01(c) for c in albedo)
    scattering = tuple(x * y for x, y in zip(a, t))
    absorption = tuple((1.0 - x) * y for x, y in zip(a, t))
    e = per_meter(emission_distance)
    emitted = tuple(min(MAX_MEDIUM_DENSITY, max(0.0, c) / e) if e > 0 else 0.0 for c in emission)
    if max(scattering + absorption + emitted) <= 0.0:
        return None
    g = directionality if _finite(directionality) else 0.0
    return Medium(scattering, absorption, max(-MAX_ANISOTROPY, min(MAX_ANISOTROPY, g)), emitted)


def _corona_volume(conv, m, ir, distance, color, albedo, g, slots, single):
    """The medium of a Corona surface material (corona_medium) into ir from the parameter ids of its distance,
    absorption color (Corona's default 0.5 grey), scattering color and directionality; slots and single as
    _medium_issues', named where the distance is on, also when a map alone would make the medium."""
    d = _num(m, distance, 0, 0.0)
    ir.medium = corona_medium(conv, conv.rgb(m, color, 0, (0.5, 0.5, 0.5)), d, conv.rgb(m, albedo, 0, (0.0, 0.0, 0.0)),
                              _num(m, g, 0, 0.0))
    if _finite(d) and d > 0:
        _medium_issues(conv, m, ir, slots, single)


def _medium_issues(conv, m, ir, slots, single=None):
    """The issues of a medium: each map slot (map id, switch id, what) where a map is on, and single bounce (its id;
    None: not asked) where on."""
    what = class_name(m.superclass, m.class_id)
    for map_pid, on_pid, name in slots:
        if conv.map_ref(m, map_pid, on_pid, None, 0, ir=ir) is not None:
            conv.issue(m.index, "%s %r: %s map not converted" % (what, m.name, name), ir)
    if single is not None and _flag(m, single, 0, False):
        conv.issue(m.index, "%s %r: single bounce not converted" % (what, m.name), ir)
        if ir.medium is not None:
            ir.medium = dataclasses.replace(ir.medium, single=True)


def corona_volume_mtl(conv, m, ir):
    """CoronaVolumeMtl, block 0: no surface (alpha 0: Corona 12 renders none, maxdrop-em3.163) and the medium of 101
    absorptionDist, 102 absorptionColor, 203 scatteringColor, 204 scatteringDirectionality, 201 emissionDist, 202
    emissionColor (corona_medium); its maps (absorption 206 / 208, scattering 205 / 207, emission 210 / 211) and 209
    singleBounce are named."""
    ir.alpha = Input(0.0)
    d, e = _num(m, 101, 0, 0.0), _num(m, 201, 0, 0.0)
    ir.medium = corona_medium(conv, conv.rgb(m, 102, 0, (0.5, 0.5, 0.5)), d, conv.rgb(m, 203, 0, (0.0, 0.0, 0.0)),
                              _num(m, 204, 0, 0.0), conv.rgb(m, 202, 0, (1.0, 1.0, 1.0)), e)
    if _finite(d) and d > 0:
        _medium_issues(conv, m, ir, ((206, 208, "absorption"), (205, 207, "scattering")), 209)
    if _finite(e) and e > 0:
        _medium_issues(conv, m, ir, ((210, 211, "emission"),))


# Corona material classes without a Principled equivalent: grey, with what is not converted named
CORONA_GREY = {
    classids.CORONA_SCANNED_MTL: "scanned material (.ctf) not read",
    classids.CORONA_SLICER_MTL: "slicing not converted",
}


def corona_named_grey(conv, m, ir):
    """CoronaScannedMtl, CoronaSlicerMtl: the grey material, its issue naming what is lost (CORONA_GREY); not counted
    as a class without a rule."""
    return conv._grey(m.index, "%s %r: %s, grey" % (ir.source, m.name, CORONA_GREY[ClassId(*m.class_id)]))
