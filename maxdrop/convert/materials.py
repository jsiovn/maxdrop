# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material rules: a 3ds Max material's parameters turned into a renderer-neutral MaterialIR in linear color.

    conv = MaterialConverter(graph, meters=desc.meters)   # graph: reader.materials.MaterialGraph
    ir = conv.convert(node.material)    # MaterialIR (wrappers peeled), None when the object is not a material
    ir.base_color.value, ir.base_color.map        # linear RGB, MapRef(index, amount, invert) or None
    conv.peel(index)                    # (object index of the renderable material or None, reason)
    conv.stats.peeled, conv.stats.unknown, conv.stats.issues

Each input of a MaterialIR is an Input: a value (a linear RGB tuple or a float) and, when a map drives it, a
MapRef to the map object (convert/texmaps.py turns that into a texture graph; the value is what the slot shows
without it). One MaterialIR per Max material object index; a wrapper converts to the IR of the material it peels
to, so every node using either shares it.

Rules (the decisions of an earlier 3ds Max -> FBX exporter, without its FBX workarounds):

- VRayMtl: base color = diffuse; roughness = reflection glossiness g, or 1 - g unless brdf_useRoughness (a
  glossiness map is then inverted); metallic = reflection_metalness; specular = the mean of the linear reflection
  color; emission = self-illumination color times its multiplier; transmission = the mean of the refraction color,
  ior and thin-walled from the refraction parameters; maps where their slot is on, with their multiplier as the
  amount; a VRayNormalMap in the bump slot is the normal input, any other map the bump input. Added here: a
  refracting material takes its base color from the refraction color (mixed by the transmission), and with
  Fresnel off a bright reflection (mean >= METAL_REFLECTION) makes the material a metal in the reflection color.
  The Fresnel IOR is the refraction IOR when the material refracts or locks the IOR, else the reflection IOR.
- VRayLightMtl -> emission only; VRayFastSSS2 -> base + subsurface; VRayCarPaintMtl / VRayCarPaintMtl2 -> a metal
  base + coat.
- Wrappers (VRay2SidedMtl, VRayBlendMtl, VRayOverrideMtl, VRayMtlWrapper, DoubleSided, Shellac) -> the first set
  sub-material in 3ds Max's getSubMtl order; Shell Material -> its render sub-material. Peeling stops at any other
  class (a Multi/Sub-Object included), at most MAX_PEEL wrappers deep; each wrapper object peeled counts once.
- Any other class -> a grey material that keeps its name, counted by class name.

Colors are 3ds Max swatches (display-referred), clamped to 0..1 and decoded with the sRGB transfer function.
A missing, animated or non-finite parameter takes V-Ray's default. Lengths (the SSS radius) are in meters.
Parameter ids: docs/FORMAT.md for the classes of the fixtures; the others (named beside each rule) were read from
3ds Max 2020 + V-Ray 5.2 through the SDK, not from a file. No bpy, no mathutils.
"""
import collections
import dataclasses
import math

from ..reader import chunks, classids, pblock
from ..reader.classdir import ClassId

ChunkError = chunks.ChunkError

MAX_PEEL = 8
METAL_REFLECTION = 0.25  # mean linear reflection (about sRGB 137 grey) above which Fresnel off means metal
GREY_SRGB = 128 / 255

# The classes no fixture has: reader/classids.py takes a class only with a fixture.
VRAY_LIGHT_MTL = ClassId(0x7CCF263E, 0x3F5B39B9)
VRAY_FAST_SSS2 = ClassId(0x3F2C5FAA, 0x750008BC)
VRAY_CAR_PAINT_MTL = ClassId(0x38312C74, 0x47280883)
VRAY_CAR_PAINT_MTL2 = ClassId(0x56BC47E2, 0x03E008C7)
VRAY_OVERRIDE_MTL = ClassId(0x15D20E6B, 0x54E217EB)
VRAY_MTL_WRAPPER = ClassId(0x409517DF, 0x3A5F44B6)
DOUBLE_SIDED_MTL = ClassId(0x00000210, 0)
SHELLAC_MTL = ClassId(0x46EE536A, 0)

CLASS_NAMES = {
    VRAY_LIGHT_MTL: "VRayLightMtl", VRAY_FAST_SSS2: "VRayFastSSS2", VRAY_CAR_PAINT_MTL: "VRayCarPaintMtl",
    VRAY_CAR_PAINT_MTL2: "VRayCarPaintMtl2", VRAY_OVERRIDE_MTL: "VRayOverrideMtl",
    VRAY_MTL_WRAPPER: "VRayMtlWrapper", DOUBLE_SIDED_MTL: "DoubleSided", SHELLAC_MTL: "Shellac",
}

# wrapper ClassId -> its sub-material parameters (block 0) in getSubMtl order; a table parameter gives each element
WRAPPERS = {
    classids.VRAY_2SIDED_MTL: (0, 1),  # frontMtl, backMtl
    classids.VRAY_BLEND_MTL: (0, 1),  # baseMtl, coatMtl (table)
    VRAY_OVERRIDE_MTL: (0, 2, 4, 6, 8),  # baseMtl, giMtl, reflectMtl, refractMtl, shadowMtl
    VRAY_MTL_WRAPPER: (0,),  # baseMtl
    DOUBLE_SIDED_MTL: (0, 1),  # material1 (facing), material2 (back)
    SHELLAC_MTL: (0, 1),  # shellacMtl1 (base), shellacMtl2
}
SHELL_RENDER_INDEX, SHELL_SUBS = 1, (2, 3)  # renderMtlIndex; originalMaterial, bakedMaterial


@dataclasses.dataclass(frozen=True)
class MapRef:
    """A map object driving an input: its object index, the slot's amount (1 = full) and whether the map holds the
    inverse of the input (a glossiness map feeding roughness)."""
    index: int
    amount: float = 1.0
    invert: bool = False


@dataclasses.dataclass(frozen=True)
class Input:
    """A value (linear RGB tuple or float) and the map that drives it, None without one."""
    value: object
    map: object = None


@dataclasses.dataclass
class MaterialIR:
    """One material, renderer-neutral, linear color. index: the Max material object it was converted from; source:
    that material's class name; unknown: the grey material of a class without a rule."""
    index: object
    name: str
    source: str = ""
    base_color: Input = Input((0.8, 0.8, 0.8))
    metallic: Input = Input(0.0)
    roughness: Input = Input(0.5)
    specular: Input = Input(0.5)
    ior: float = 1.5
    transmission: Input = Input(0.0)
    thin_walled: bool = False
    emission_color: Input = Input((0.0, 0.0, 0.0))
    emission_strength: float = 0.0
    alpha: Input = Input(1.0)
    normal: object = None  # MapRef of a normal map
    bump: object = None  # MapRef of a height map
    subsurface_weight: float = 0.0
    subsurface_color: tuple = (1.0, 1.0, 1.0)
    subsurface_radius: float = 0.0  # meters
    coat_weight: float = 0.0
    coat_color: tuple = (1.0, 1.0, 1.0)
    coat_roughness: float = 0.0
    coat_ior: float = 1.5
    unknown: bool = False
    issues: list = dataclasses.field(default_factory=list)


class ConvertStats:
    """What the report needs: peeled {class name: wrapper objects peeled}, unknown {class name: materials made
    grey}, issues [(object index, reason)]."""
    __slots__ = ("peeled", "unknown", "issues")

    def __init__(self):
        self.peeled, self.unknown, self.issues = collections.Counter(), collections.Counter(), []


def srgb_to_linear(c):
    """One sRGB-encoded channel (0..1) to linear."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_color(rgb):
    """A 3ds Max swatch (0..1 per channel, display-referred) to linear RGB, clamped to 0..1 first."""
    return tuple(srgb_to_linear(min(1.0, max(0.0, c))) for c in rgb[:3])


def mean(rgb):
    """The mean of the channels: the rules' measure of how strong a reflection or refraction color is."""
    return sum(rgb[:3]) / 3.0


def class_name(superclass, class_id):
    """The class name for the report: the class directory's for a known class, else the ClassID."""
    cid = ClassId(*class_id)
    return classids.name_of(superclass, cid) or CLASS_NAMES.get(cid) or "ClassID%s" % (cid,)


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _num(m, pid, block, default):
    v = m.param(pid, block)
    return float(v) if _finite(v) else default


def _clamp01(v):
    return min(1.0, max(0.0, v))


def _flag(m, pid, block, default):
    v = m.param(pid, block)
    return bool(v) if _finite(v) else default


def _rgb(m, pid, block, default):
    """A swatch as linear RGB; default is the swatch value (sRGB, 0..1) used when the parameter is unusable."""
    v = m.param(pid, block)
    if not (isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3])):
        v = default
    return linear_color(v)


def _mix(a, b, t):
    return tuple(x * (1.0 - t) + y * t for x, y in zip(a, b))


def _roughness(gloss, use_roughness):
    return _clamp01(gloss if use_roughness else 1.0 - gloss)


class MaterialConverter:
    """Converts the materials of one MaterialGraph, each object once."""

    def __init__(self, graph, meters=1.0):
        if not (_finite(meters) and meters > 0):
            raise ValueError("meters per unit must be a positive number, not %r" % (meters,))
        self.graph, self.meters = graph, meters
        self.stats = ConvertStats()
        self._done, self._peels, self._counted = {}, {}, set()

    def issue(self, index, reason, ir=None):
        self.stats.issues.append((index, reason))
        if ir is not None:
            ir.issues.append(reason)

    def _get(self, index):
        """The MtlBase of a material or map object; ChunkError when it cannot be read."""
        return self.graph.get(index)

    def map_ref(self, m, map_pid, on_pid, amount_pid, block, invert=False, ir=None):
        """The MapRef of a map slot: None when it holds no map, is switched off or holds something else."""
        ref = m.param(map_pid, block)
        if not isinstance(ref, pblock.Reference) or ref.index is None:
            return None
        if on_pid is not None and not _flag(m, on_pid, block, True):
            return None
        if self.graph.superclass(ref.index) != classids.SC_TEXMAP:
            self.issue(m.index, "parameter %d: object %d is not a map" % (map_pid, ref.index), ir)
            return None
        amount = 1.0 if amount_pid is None else max(0.0, _num(m, amount_pid, block, 100.0) / 100.0)
        return MapRef(ref.index, amount, invert)

    def is_class(self, index, superclass, class_id):
        try:
            m = self._get(index)
        except ChunkError:
            return False
        return m.superclass == superclass and ClassId(*m.class_id) == class_id

    def bump_slot(self, ir, ref):
        """A map in a bump slot: a VRayNormalMap is the normal input, anything else a height map."""
        if ref is None:
            return
        if self.is_class(ref.index, classids.SC_TEXMAP, classids.VRAY_NORMAL_MAP):
            ir.normal = ref
        else:
            ir.bump = ref

    def _sub(self, m, key):
        """The sub-material a wrapper peels to: (object index or None, reason)."""
        if key == classids.SHELL_MTL:
            k = _num(m, SHELL_RENDER_INDEX, 0, 0.0)
            if k not in (0.0, 1.0):
                return None, "Shell Material: render index %r" % (k,)
            pids = (SHELL_SUBS[int(k)],)
        else:
            pids = WRAPPERS[key]
        block = m.block(0)
        for pid in pids:
            values = block.value(pid) if block is not None else None
            for v in values if isinstance(values, list) else [values]:
                if isinstance(v, pblock.Reference) and v.index is not None:
                    if self.graph.superclass(v.index) != classids.SC_MATERIAL:
                        return None, "%s: sub-material %d is not a material" % (m.name or "wrapper", v.index)
                    return v.index, None
        return None, "%s: no sub-material" % (m.name or "wrapper")

    def peel(self, index):
        """(object index of the material a wrapper stands for, None), the index itself for a material that is no
        wrapper; (None, reason) when the peel ends without a material."""
        if index in self._peels:
            return self._peels[index]
        chain, i, out = [], index, None
        while out is None:
            try:
                m = self._get(i)
            except ChunkError as e:
                out = (None, "object %d: %s" % (i, e))
                break
            key = ClassId(*m.class_id)
            if m.superclass != classids.SC_MATERIAL or not (key in WRAPPERS or key == classids.SHELL_MTL):
                out = (i, None)
                break
            if len(chain) == MAX_PEEL:
                out = (None, "more than %d wrappers below object %d" % (MAX_PEEL, index))
                break
            if i not in self._counted:
                self._counted.add(i)
                self.stats.peeled[class_name(m.superclass, key)] += 1
            chain.append(i)
            sub, reason = self._sub(m, key)
            if sub is None:
                out = (None, reason)
            elif sub in chain:
                out = (None, "wrapper cycle through object %d" % sub)
            i = sub
        self._peels[index] = out
        return out

    def convert(self, index):
        """The MaterialIR of material object index, None when the object is not a material."""
        if index in self._done:
            return self._done[index]
        if self.graph.superclass(index) != classids.SC_MATERIAL:
            return None
        base, reason = self.peel(index)
        if base is None:
            ir = self._grey(index, reason)
        elif base != index:
            ir = self.convert(base)
        else:
            ir = self._rule(index)
        self._done[index] = ir
        return ir

    def _grey(self, index, reason):
        """The grey material for an object no rule converts, named after it."""
        try:
            m = self._get(index)
            name, source = m.name, class_name(m.superclass, m.class_id)
        except ChunkError:
            name, source = "", ""
        g = srgb_to_linear(GREY_SRGB)
        ir = MaterialIR(index, name, source, base_color=Input((g, g, g)), unknown=True)
        if reason:
            self.issue(index, reason, ir)
        return ir

    def _rule(self, index):
        try:
            m = self._get(index)
        except ChunkError as e:
            return self._grey(index, "object %d: %s" % (index, e))
        source = class_name(m.superclass, m.class_id)
        rule = RULES.get((m.superclass, ClassId(*m.class_id)))
        if rule is None:
            self.stats.unknown[source] += 1
            return self._grey(index, "")
        ir = MaterialIR(index, m.name, source)
        rule(self, m, ir)
        return ir


def vray_mtl(conv, m, ir):
    """VRayMtl: blocks 1 basic, 2 BRDF, 3 options, 4 maps (map id, on = id + 50, multiplier in % = id + 100)."""
    use_roughness = _flag(m, 89, 2, False)  # brdf_useRoughness
    diffuse = _rgb(m, 1, 1, (0.5, 0.5, 0.5))
    reflection = _rgb(m, 2, 1, (0.0, 0.0, 0.0))
    refraction = _rgb(m, 5, 1, (0.0, 0.0, 0.0))
    reflection_map = conv.map_ref(m, 101, 151, 201, 4, ir=ir)

    t = _clamp01(mean(refraction))
    base = _mix(diffuse, refraction, t) if t > 0 else diffuse
    ir.base_color = Input(base, conv.map_ref(m, 100, 150, 200, 4, ir=ir))  # texmap_diffuse
    ir.roughness = Input(_roughness(_num(m, 3, 1, 1.0), use_roughness),  # reflection_glossiness
                         conv.map_ref(m, 104, 154, 204, 4, invert=not use_roughness, ir=ir))
    ir.metallic = Input(_clamp01(_num(m, 91, 1, 0.0)),  # reflection_metalness
                        conv.map_ref(m, 119, 169, 219, 4, ir=ir))
    ir.specular = Input(_clamp01(mean(reflection)), reflection_map)
    if not _flag(m, 8, 1, True) and mean(reflection) >= METAL_REFLECTION:  # reflection_fresnel off
        ir.metallic = Input(1.0)
        ir.base_color = Input(reflection, reflection_map)

    emit_map = conv.map_ref(m, 117, 167, 217, 4, ir=ir)  # texmap_self_illumination
    ir.emission_color = Input(_rgb(m, 81, 1, (0.0, 0.0, 0.0)), emit_map)  # selfIllumination
    if max(ir.emission_color.value) > 0 or emit_map is not None:
        ir.emission_strength = max(0.0, _num(m, 83, 1, 1.0))  # selfIllumination_multiplier

    ir.transmission = Input(t, conv.map_ref(m, 102, 152, 202, 4, ir=ir))  # texmap_refraction
    refraction_ior, reflection_ior = _num(m, 9, 1, 1.6), _num(m, 63, 1, 1.6)
    ir.ior = refraction_ior if t > 0 or _flag(m, 65, 1, True) else reflection_ior  # reflection_lockIOR
    ir.thin_walled = _flag(m, 107, 1, False)  # refraction_thinWalled
    conv.bump_slot(ir, conv.map_ref(m, 103, 153, 203, 4, ir=ir))  # texmap_bump
    ir.alpha = Input(1.0, conv.map_ref(m, 112, 162, 212, 4, ir=ir))  # texmap_opacity

    ir.coat_weight = _clamp01(_num(m, 96, 1, 0.0))  # coat_amount
    ir.coat_color = _rgb(m, 97, 1, (1.0, 1.0, 1.0))
    ir.coat_roughness = _roughness(_num(m, 98, 1, 1.0), use_roughness)  # coat_glossiness
    ir.coat_ior = _num(m, 99, 1, 1.6)


def vray_light_mtl(conv, m, ir):
    """VRayLightMtl, block 0: 0 color, 1 multiplier, 2 / 3 texmap (on), 5 / 6 opacity_texmap (on)."""
    ir.base_color, ir.roughness, ir.specular = Input((0.0, 0.0, 0.0)), Input(1.0), Input(0.0)
    ir.emission_color = Input(_rgb(m, 0, 0, (1.0, 1.0, 1.0)), conv.map_ref(m, 2, 3, None, 0, ir=ir))
    ir.emission_strength = max(0.0, _num(m, 1, 0, 1.0))
    ir.alpha = Input(1.0, conv.map_ref(m, 5, 6, None, 0, ir=ir))


def vray_fast_sss2(conv, m, ir):
    """VRayFastSSS2, block 0: 26 diffuse_color, 27 / 28 its map (on), 36 diffuse_amount, 2 sub_surface_color,
    0 scatter_radius, 22 scale, 31 IOR, 40 specular_color, 51 specular_glossiness, 3 / 4 texmap_bump (on),
    85 / 86 texmap_opacity (on)."""
    ir.base_color = Input(_rgb(m, 26, 0, (0.5, 0.5, 0.5)), conv.map_ref(m, 27, 28, None, 0, ir=ir))
    ir.roughness = Input(_roughness(_num(m, 51, 0, 0.6), False))
    ir.specular = Input(_clamp01(mean(_rgb(m, 40, 0, (1.0, 1.0, 1.0)))))
    ir.ior = _num(m, 31, 0, 1.3)
    ir.subsurface_weight = _clamp01(1.0 - _num(m, 36, 0, 0.0))
    ir.subsurface_color = _rgb(m, 2, 0, (1.0, 1.0, 1.0))
    ir.subsurface_radius = max(0.0, _num(m, 0, 0, 2.0) * _num(m, 22, 0, 1.0)) * conv.meters
    conv.bump_slot(ir, conv.map_ref(m, 3, 4, None, 0, ir=ir))
    ir.alpha = Input(1.0, conv.map_ref(m, 85, 86, None, 0, ir=ir))


def _car_paint(conv, m, ir, coat_ior, bump_pid):
    """Both car paints, block 0: 0 base_color, 1 / 2 its map (on), 4 base_reflection, 8 base_glossiness,
    27 coat_color, 31 coat_strength (CarPaint) or coat_amount (CarPaint2), 39 coat_glossiness, then the base bump
    map and its on switch at bump_pid, bump_pid + 1."""
    ir.base_color = Input(_rgb(m, 0, 0, (0.5, 0.5, 0.5)), conv.map_ref(m, 1, 2, None, 0, ir=ir))
    ir.roughness = Input(_roughness(_num(m, 8, 0, 0.6), False))
    ir.metallic = Input(1.0)
    ir.specular = Input(_clamp01(_num(m, 4, 0, 0.5)))
    ir.coat_weight = _clamp01(_num(m, 31, 0, 0.0))
    ir.coat_color = _rgb(m, 27, 0, (1.0, 1.0, 1.0))
    ir.coat_roughness = _roughness(_num(m, 39, 0, 1.0), False)
    ir.coat_ior = coat_ior
    conv.bump_slot(ir, conv.map_ref(m, bump_pid, bump_pid + 1, None, 0, ir=ir))


def vray_car_paint_mtl(conv, m, ir):
    _car_paint(conv, m, ir, 1.5, 55)  # texmap_base_bump 55, on 56; no coat IOR parameter


def vray_car_paint_mtl2(conv, m, ir):
    _car_paint(conv, m, ir, _num(m, 81, 0, 1.5), 54)  # coat_ior 81; texmap_base_bump 54, on 55


# (superclass, ClassId) -> rule(converter, MtlBase, MaterialIR): fills the IR in place
RULES = {
    (classids.SC_MATERIAL, classids.VRAY_MTL): vray_mtl,
    (classids.SC_MATERIAL, VRAY_LIGHT_MTL): vray_light_mtl,
    (classids.SC_MATERIAL, VRAY_FAST_SSS2): vray_fast_sss2,
    (classids.SC_MATERIAL, VRAY_CAR_PAINT_MTL): vray_car_paint_mtl,
    (classids.SC_MATERIAL, VRAY_CAR_PAINT_MTL2): vray_car_paint_mtl2,
}
