# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rules of Standard (its shaders' ids, defaults and map slots) and of the Physical Material."""
import collections
import dataclasses

from ...reader import classids, pblock
from ...reader import materials as reader_materials
from ...reader.classdir import ClassId
from .. import colors, params
from ..params import finite as _finite, flag as _flag, num as _num
from .ids import LUMENS_PER_WATT
from .ir import DiffuseLevel, Input
from .values import _clamp01, _ior, _mix, _roughness, mean


# Standard: the shader is a part (superclass Shader); its block 0 holds the colors, with ids per shader class
# (fixture standard_shaders).
# Strauss (classids.STRAUSS_SHADER) has its own: 0 diffuse, 1 glossiness, 2 metalness. diffuse_level (a fraction,
# 1 = 100 %): None where the shader has none.
ShaderIds = collections.namedtuple(
    "ShaderIds", "diffuse specular level glossiness si_amount si_color use_si_color diffuse_level", defaults=(None,))
_BLINN_IDS = ShaderIds(1, 2, 9, 10, 7, 8, 6)
SHADERS = {
    classids.PHONG_SHADER: _BLINN_IDS,
    classids.BLINN_SHADER: _BLINN_IDS,
    classids.METAL_SHADER: _BLINN_IDS,
    classids.ANISOTROPIC_SHADER: ShaderIds(1, 2, 5, 7, 6, 3, 14, 4),
    classids.OREN_NAYAR_BLINN_SHADER: ShaderIds(1, 2, 6, 5, 4, 3, 13, 8),
    classids.MULTI_LAYER_SHADER: ShaderIds(1, 6, 7, 8, 3, 2, 19, 4),  # the first specular layer
    classids.TRANSLUCENT_SHADER: ShaderIds(1, 2, 6, 5, 4, 3, 14, 7),
}
# What a shader holds as created (3ds Max 2020), read where its parameter is missing or unread (a controller not
# evaluated at frame 0): diffuse swatch, glossiness and specular level (fractions). A shader without a rule takes
# Blinn's.
ShaderDefaults = collections.namedtuple("ShaderDefaults", "diffuse glossiness level")
_BLINN_DEFAULTS = ShaderDefaults((150 / 255,) * 3, 0.1, 0.0)
_GREY = (0.5, 0.5, 0.5)  # 127.5
SHADER_DEFAULTS = {
    classids.PHONG_SHADER: _BLINN_DEFAULTS,
    classids.BLINN_SHADER: _BLINN_DEFAULTS,
    classids.METAL_SHADER: _BLINN_DEFAULTS,
    classids.ANISOTROPIC_SHADER: ShaderDefaults(_GREY, 0.25, 0.05),
    classids.OREN_NAYAR_BLINN_SHADER: ShaderDefaults(_GREY, 0.25, 0.0),
    classids.MULTI_LAYER_SHADER: ShaderDefaults(_GREY, 0.5, 0.05),
    classids.TRANSLUCENT_SHADER: ShaderDefaults(_GREY, 0.3, 0.0),
    classids.STRAUSS_SHADER: ShaderDefaults(_GREY, 0.2, 0.0),
}
# Physical Material, block 0: the ids physical_mtl reads, keyed by the names 3ds Max gives them (fixture
# standard_shaders checks every one against its oracle); a map's switch (`<name>_on`) is at its id + PHYSICAL_SWITCH.
PHYSICAL = {
    "base_weight": 1, "base_color": 2, "reflectivity": 3, "roughness": 4, "roughness_inv": 5, "metalness": 6,
    "refl_color": 10, "transparency": 30, "trans_color": 31, "trans_ior": 33, "thin_walled": 37, "emission": 50,
    "emit_color": 51, "emit_luminance": 52, "coating": 60, "coat_color": 61, "coat_roughness": 62,
    "coat_roughness_inv": 63, "coat_ior": 66, "base_color_map": 101, "reflectivity_map": 102, "roughness_map": 104,
    "metalness_map": 105, "transparency_map": 109, "emission_map": 116, "emit_color_map": 117, "bump_map": 130,
    "cutout_map": 133, "bump_map_amt": 230,  # the bump amount: a factor
}
PHYSICAL_SWITCH = 50

# Standard map slots: the channel in the Texmaps object (reader.materials.standard_maps) and the index into block 3's
# tables (mapEnables 0, maps 1, mapAmounts 2), both following the shader's own map channels (docs/FORMAT.md;
# fixture standard_maps); None: the shader has no such channel. A shader without a rule is read with Blinn's.
# diffuse_level: the Diffuse Level map, on the shaders with a Diffuse Level (SHADERS).
StdSlots = collections.namedtuple(
    "StdSlots", "diffuse specular level glossiness self_illum opacity bump reflection metalness diffuse_level",
    defaults=(None,))
_BLINN_SLOTS = StdSlots(1, 2, 3, 4, 5, 6, 8, 9, None)
_ONB_SLOTS = StdSlots(1, 2, 4, 3, 5, 6, 10, 11, None, 8)  # Oren-Nayar-Blinn, Translucent Shader
STD_SLOTS = {
    classids.PHONG_SHADER: _BLINN_SLOTS,
    classids.BLINN_SHADER: _BLINN_SLOTS,
    classids.METAL_SHADER: _BLINN_SLOTS,
    classids.ANISOTROPIC_SHADER: StdSlots(1, 2, 4, 5, 8, 9, 11, 12, None, 3),
    classids.OREN_NAYAR_BLINN_SHADER: _ONB_SLOTS,
    classids.MULTI_LAYER_SHADER: StdSlots(1, 4, 5, 6, 14, 15, 17, 18, None, 2),  # the first specular layer
    classids.TRANSLUCENT_SHADER: _ONB_SLOTS,
    classids.STRAUSS_SHADER: StdSlots(0, None, None, 1, None, 3, 5, 6, 2),
}
STD_SPECULAR_DEFAULT = (0.9, 0.9, 0.9)


class _PartParams:
    """The parameters of a material's part (its blocks), read like a MtlBase's: param(pid, block_id); with the
    scene, an animated one at frame 0 (params.frame_zero), its lines to report(owner's index, line)."""

    def __init__(self, part, scene=None, report=None, owner=None):
        self._blocks = [b for _slot, b in sorted(part.blocks.items())] if part is not None else []
        self._scene = scene
        self._heard = params.hearing(report, owner.index, "%r shader" % (owner.name,)) if owner is not None else None

    def param(self, pid, block_id=None, tab=0, default=None):
        for b in self._blocks:
            if (block_id is None or b.block_id == block_id) and pid in b:
                return params.frame_zero(self._scene, b, pid, b.get(pid, tab, default), self._heard)
        return default


def _std_channels(conv, m):
    """Standard material m's map channels as 3ds Max answers them (reader.materials.standard_maps: its Texmaps
    object); None without a readable one (or a graph without a scene), then _std_map reads block 3's tables, which
    can keep the channel layout the material was created with."""
    scene = getattr(conv.graph, "scene", None)
    return None if scene is None else reader_materials.standard_maps(scene, m)


def _std_map(conv, m, slot, ir, invert=False, channels=None):
    """Standard's map slot (a channel of the shader's own layout): None when the shader has no such slot (None),
    empty or switched off; its amount is a fraction. From channels (_std_channels) when given, else block 3's tables
    (mapEnables 0, maps 1, mapAmounts 2, one table element per slot)."""
    if slot is None:
        return None
    if channels is not None:
        index, on, amount = channels.channel(slot)
        if index is None or not on:
            return None
        amount = max(0.0, float(amount)) if _finite(amount) else 1.0
        return conv.to_map(m, pblock.Reference(index), "map channel %d" % slot, amount, invert, ir)
    on = m.param(0, 3, tab=slot)
    if _finite(on) and not on:
        return None
    amount = m.param(2, 3, tab=slot)
    amount = max(0.0, float(amount)) if _finite(amount) else 1.0
    return conv.to_map(m, m.param(1, 3, tab=slot), "map slot %d" % slot, amount, invert, ir)


def standard_mtl(conv, m, ir):
    """Standard: block 0 shader (2 twoSided), block 1 extended (1 opacity, 6 ior), block 3 maps; the colors in the
    shader part's block 0 (SHADERS; Strauss its own)."""
    ir.two_sided = _flag(m, 2, 0, False)
    ir.ior = _ior(_num(m, 6, 1, 1.5))
    shader = next((p for _slot, p in sorted(m.parts.items()) if p.superclass == classids.SC_SHADER), None)
    sid = ClassId(*shader.class_id) if shader is not None else None
    s = _PartParams(shader, getattr(conv.graph, "scene", None), conv._issue_once, m)
    slots = STD_SLOTS.get(sid, _BLINN_SLOTS)
    ch = _std_channels(conv, m)
    ir.alpha = Input(_clamp01(_num(m, 1, 1, 1.0)), _std_map(conv, m, slots.opacity, ir, channels=ch))
    gloss_map = _std_map(conv, m, slots.glossiness, ir, invert=True, channels=ch)
    level_map = _std_map(conv, m, slots.level, ir, channels=ch) or _std_map(conv, m, slots.specular, ir, channels=ch)
    emit_map = _std_map(conv, m, slots.self_illum, ir, channels=ch)
    specular, amount, emit = 0.0, 0.0, None
    d = SHADER_DEFAULTS.get(sid, _BLINN_DEFAULTS)
    base, level = None, 1.0
    if sid == classids.STRAUSS_SHADER:
        diffuse, gloss = conv.rgb(s, 0, 0, d.diffuse), _num(s, 1, 0, d.glossiness)
        ir.metallic = Input(_clamp01(_num(s, 2, 0, 0.0)), _std_map(conv, m, slots.metalness, ir, channels=ch))
        specular = 1.0  # no specular level: the IOR's own Fresnel
    elif sid in SHADERS:
        ids = SHADERS[sid]
        diffuse, gloss = conv.rgb(s, ids.diffuse, 0, d.diffuse), _num(s, ids.glossiness, 0, d.glossiness)
        if ids.diffuse_level is not None:
            # 3ds Max shades with swatch x level (not clamped; Default Scanline, gamma off: linear in the stored
            # value), so the level applies before the swatch rule; the self-illumination keeps the swatch as set.
            level = max(0.0, _num(s, ids.diffuse_level, 0, 1.0))
            base = conv.rgb(s, ids.diffuse, 0, d.diffuse, level)
        specular = max(0.0, _num(s, ids.level, 0, d.level)) * mean(conv.rgb(s, ids.specular, 0, STD_SPECULAR_DEFAULT))
        if _flag(s, ids.use_si_color, 0, False):
            emit = conv.rgb(s, ids.si_color, 0, (0.0, 0.0, 0.0))
        else:
            amount = max(0.0, _num(s, ids.si_amount, 0, 0.0))
        if sid == classids.METAL_SHADER:
            ir.metallic = Input(1.0)
    else:
        diffuse, gloss = conv.swatches.color(d.diffuse), d.glossiness
        conv.issue(m.index, "Standard: shader %s has no rule: its defaults" % (
            "missing" if sid is None else "ClassID%s" % (sid,)), ir)
    # A mapped diffuse is scaled by the level too, in the stored value: the map, decoded in Blender, takes the level
    # as the swatch rule makes it (an approximation with the gamma off: the sRGB curve of a product is not a product).
    diffuse_map = _std_map(conv, m, slots.diffuse, ir, channels=ch)
    k = level if conv.swatches.linear else colors.srgb_to_linear(level)
    if diffuse_map is not None and k != 1.0:
        diffuse_map = dataclasses.replace(diffuse_map, scale=k)
    ir.base_color = Input(diffuse if base is None else base, diffuse_map)
    diffuse_level_map = _std_map(conv, m, slots.diffuse_level, ir, channels=ch)
    if diffuse_level_map is not None:
        ir.diffuse_level = DiffuseLevel(diffuse, k, diffuse_level_map)
    ir.roughness = Input(_roughness(gloss, False), gloss_map)
    reflection = _std_map(conv, m, slots.reflection, ir, channels=ch)
    if reflection is not None:
        specular = max(specular, min(1.0, reflection.amount))
    ir.specular = Input(_clamp01(specular), level_map)
    if emit is not None:  # its own color, at full strength
        ir.emission_color = Input(emit, emit_map)
        ir.emission_strength = 1.0 if max(emit) > 0 or emit_map is not None else 0.0
    elif amount > 0 or emit_map is not None:  # the diffuse lights itself by the amount; a map overrides it
        ir.emission_color = Input(diffuse, emit_map)
        ir.emission_strength = 1.0 if emit_map is not None else amount
    conv.bump_slot(ir, _std_map(conv, m, slots.bump, ir, channels=ch))


def physical_mtl(conv, m, ir):
    """Physical Material, block 0, by the ids of PHYSICAL; each map switched on by its id + PHYSICAL_SWITCH."""
    P = PHYSICAL

    def num(name, default):
        return _num(m, P[name], 0, default)

    def slot(name, invert=False, amount=None):
        pid = P[name + "_map"]
        return conv.map_ref(m, pid, pid + PHYSICAL_SWITCH, None if amount is None else P[amount], 0, invert=invert,
                            ir=ir, percent=False)

    weight = _clamp01(num("base_weight", 1.0))
    base = tuple(c * weight for c in conv.rgb(m, P["base_color"], 0, (0.5, 0.5, 0.5)))
    t = _clamp01(num("transparency", 0.0))
    if t > 0:
        base = _mix(base, conv.rgb(m, P["trans_color"], 0, (1.0, 1.0, 1.0)), t)
    ir.base_color = Input(base, slot("base_color"))
    inverted = _flag(m, P["roughness_inv"], 0, False)
    r = _clamp01(num("roughness", 0.0))
    ir.roughness = Input(1.0 - r if inverted else r, slot("roughness", invert=inverted))
    ir.metallic = Input(_clamp01(num("metalness", 0.0)), slot("metalness"))
    reflection = mean(conv.rgb(m, P["refl_color"], 0, (1.0, 1.0, 1.0)))
    ir.specular = Input(_clamp01(max(0.0, num("reflectivity", 1.0)) * reflection), slot("reflectivity"))
    ir.transmission = Input(t, slot("transparency"))
    ir.ior = _ior(num("trans_ior", 1.52))
    ir.thin_walled = _flag(m, P["thin_walled"], 0, False)
    # A map in a weight slot stands for the weight, one in a color slot only for the color: weight 0 and a color
    # map is no emission. The IR has no strength map, so the weight map drives the color when no color map does.
    color_map = slot("emit_color")
    weight_map = slot("emission")
    emission = max(0.0, num("emission", 0.0))
    if emission > 0 or weight_map is not None:
        if color_map is not None and weight_map is not None:
            conv.issue(m.index, "Physical Material: emission weight map %d not used beside the color map"
                       % weight_map.index, ir)
        ir.emission_color = Input(conv.rgb(m, P["emit_color"], 0, (1.0, 1.0, 1.0)), color_map or weight_map)
        luminance = max(0.0, num("emit_luminance", 1500.0))
        ir.emission_strength = (1.0 if weight_map is not None else emission) * luminance / LUMENS_PER_WATT
    ir.coat_weight = _clamp01(num("coating", 0.0))
    ir.coat_color = conv.rgb(m, P["coat_color"], 0, (1.0, 1.0, 1.0))
    c = _clamp01(num("coat_roughness", 0.0))
    ir.coat_roughness = 1.0 - c if _flag(m, P["coat_roughness_inv"], 0, False) else c
    ir.coat_ior = _ior(num("coat_ior", 1.52))
    conv.bump_slot(ir, slot("bump", amount="bump_map_amt"))
    ir.alpha = Input(1.0, slot("cutout"))
