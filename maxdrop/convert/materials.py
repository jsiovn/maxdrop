# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material rules: a 3ds Max material's parameters turned into a renderer-neutral MaterialIR in linear color.

    conv = MaterialConverter(graph, texmaps=tex, swatches=sw)   # graph: reader.materials.MaterialGraph; tex: an
                                        # optional texmaps.TexmapConverter, which fills ir.textures; sw: the
                                        # colors.Swatches rule (default: tex's, else read from graph's scene);
                                        # pass tex's own rule, or none: the two must agree
    ir = conv.convert(node.material)    # MaterialIR (wrappers peeled); None for no material or not a material
    ir.base_color.value, ir.base_color.map        # linear RGB, MapRef(index, amount, invert) or None
    conv.material_for(index, mat_id)    # the MaterialIR a face with that zero-based material ID renders with
                                        # (Multi/Sub-Objects resolved), None for an empty slot
    slots = assign(desc, node_materials(scene, desc), conv)   # {mesh key: MeshSlots}, for build/objects.py
    conv.peel(index)                    # (object index of the renderable material or None, reason)
    conv.stats.peeled, conv.stats.unknown, conv.stats.issues

Each input of a MaterialIR is an Input: a value (a linear RGB tuple or a float) and, when a map drives it, a
MapRef to the map object (the value is what the slot shows without it). With a TexmapConverter, ir.textures holds
the TextureGraphIR of each input a usable map drives (convert/texmaps.py), its issues added to ir.issues. One
MaterialIR per Max material object index; a wrapper converts to the IR of the material it peels to, so every node
using either shares it.

Rules (the decisions of an earlier 3ds Max -> FBX exporter, without its FBX workarounds):

- VRayMtl: base color = diffuse; roughness = reflection glossiness g, or 1 - g unless brdf_useRoughness (a
  glossiness map is then inverted); metallic = reflection_metalness; specular = the mean of the linear reflection
  color; emission = self-illumination color times its multiplier; transmission = the mean of the refraction color,
  ior and thin-walled from the refraction parameters; maps where their slot is on, with their multiplier as the
  amount; a normal map (VRayNormalMap, Normal Bump, CoronaNormal) in a bump slot is the normal input, any other
  map the bump input. Added here: a refracting material takes its base color from the refraction color (mixed by
  the transmission), and with Fresnel off a bright reflection (mean >= METAL_REFLECTION) makes the material a metal
  in the reflection color.
  The Fresnel IOR is the refraction IOR when the material refracts or locks the IOR, else the reflection IOR.
- VRayLightMtl -> emission only; VRayFastSSS2 -> base + subsurface; VRayCarPaintMtl / VRayCarPaintMtl2 -> a metal
  base + coat (VRayCarPaintMtl's coat_strength is the coat's reflectance at normal incidence: a full coat whose
  IOR gives that reflectance; VRayCarPaintMtl2's coat_amount is the coat weight).
- Standard: the colors come from its shader (ids per shader class in SHADERS; Metal is a metal, Strauss has a
  metalness); base = diffuse; roughness = 1 - glossiness; specular = specular level times the mean of the linear
  specular color; alpha = opacity; self-illumination: its color at strength 1, or the diffuse at the amount;
  two-sided flag; map slots with their amounts where switched on (a glossiness map inverted; the specular level
  map drives the specular, else the specular color map); a map in the
  reflection slot makes the specular at least that slot's amount (the map is an environment: not used).
- Physical Material: base = base color times base weight; roughness (1 - it with roughness_inv); metalness;
  specular = reflectivity times the mean of the linear reflection color; transparency is the transmission and
  mixes the transparency color into the base, as for VRayMtl; IOR, thin-walled; emission color at emission
  weight times luminance / LUMENS_PER_WATT (cd/m2 to Blender's W/(m2 sr)), a weight map standing for the
  weight; coating; map slots where on.
- CoronaPhysicalMtl: base = base color times base level; roughness, or 1 - it in glossiness mode (every roughness
  of the material, a map then inverted); metallic from the metalness mode; transmission = refraction amount, the base
  mixed toward white (thin mode: the thin absorption color) by it; IOR, thin mode; alpha = the mean of the linear
  opacity color times its level; emission color at its level; clearcoat amount, IOR, roughness and absorption color;
  maps where on, their amounts fractions. Specular stays 0.5 (Corona derives it from the IOR).
- CoronaLegacyMtl (CoronaMtl): diffuse, reflection, refraction, opacity and self-illumination colors times their
  levels; specular = the mean reflection; roughness = 1 - glossiness (PBR mode or not); transmission and the glass
  base color as for VRayMtl, the IOR as well (refraction IOR when it refracts, else the Fresnel IOR); a Fresnel IOR
  of CORONA_METAL_IOR or more with a bright reflection (as METAL_REFLECTION) is a metal in the reflection color.
- CoronaLightMtl -> emission (color, intensity, map) and its opacity map.
- Wrappers (VRay2SidedMtl, VRayBlendMtl, VRayOverrideMtl, VRayMtlWrapper, DoubleSided, Shellac, CoronaLayeredMtl:
  base, then its layers that are on) -> the first set sub-material in 3ds Max's getSubMtl order; Shell Material -> its render
  sub-material. Peeling stops at any other
  class (a Multi/Sub-Object included), at most MAX_PEEL wrappers deep; each wrapper object peeled counts once.
- Multi/Sub-Object: entry k has the material ID materialIDList[k] (zero-based, as the faces store it), the
  material materialList[k] and the switch mapEnabled[k]; the first entry with an ID wins. A face ID without an
  entry, or whose entry is switched off or empty, gets no material (an empty slot). A Multi/Sub-Object inside a
  wrapper or inside another Multi/Sub-Object (which looks up the same ID) resolves the same way, at most MAX_PEEL
  deep. convert() of one (a caller without face IDs) gives the material of its first entry that is on and set.
- Any other class -> a grey material that keeps its name, counted by class name.

The slots of a mesh (assign): its distinct face IDs, each keyed by the materials its users (the nodes sharing the
mesh) get for that ID; one slot per key, in ID order, faces remapped to their slot. A material that is not a
Multi/Sub-Object gives one slot; an empty key (no material) is a slot only beside others.

Colors are 3ds Max swatches, clamped to 0..1 and made linear by the scene's swatch rule (convert/colors.py): the
value itself when the scene was saved with the gamma on (or does not say), the sRGB curve when it was off.
A missing, animated or non-finite parameter takes the class's default; an IOR is clamped to 1..100. The SSS radius is
in meters (VRayFastSSS2 stores it in centimeters whatever the system unit).
Parameter ids: docs/FORMAT.md for the classes of the fixtures (the Corona ones: Corona 12); the others (named beside
each rule) were read from 3ds Max 2020 + V-Ray 5.2 through the SDK or from probe scenes it saved, not from a
fixture. No bpy, no mathutils.
"""
import collections
import dataclasses
import math

from ..reader import chunks, classids, pblock
from ..reader.classdir import ClassId
from . import colors
from . import texmaps as _texmaps

ChunkError = chunks.ChunkError

MAX_PEEL = 8
METAL_REFLECTION = 0.25  # mean linear reflection (about sRGB 137 grey) above which Fresnel off means metal
CORONA_METAL_IOR = 10.0  # a CoronaLegacyMtl Fresnel IOR from which a bright reflection is a metal (made with 999)
GREY_SRGB = 128 / 255  # the grey of a material without a rule: MaxDrop's own, not a swatch

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
    classids.CORONA_LAYERED_MTL: (1000, 1001),  # baseMtl, layers (table)
}
SHELL_RENDER_INDEX, SHELL_SUBS = 1, (2, 3)  # renderMtlIndex; originalMaterial, bakedMaterial
CORONA_LAYERS, CORONA_LAYERS_ON = 1001, 1004  # CoronaLayeredMtl: a layer switched off is not a sub-material

LUMENS_PER_WATT = 683.0  # luminous efficacy at 555 nm: cd/m2 -> W/(m2 sr)

# Multi/Sub-Object, block 0: materialList, mapEnabled, materialIDList (zero-based)
MULTI_MATERIALS, MULTI_ENABLED, MULTI_IDS = 0, 1, 3

# Standard: the shader is a part (superclass Shader); its block 0 holds the colors, with ids per shader class
# (probe scenes saved by 3ds Max 2020 with each shader; only Blinn is in a fixture).
PHONG_SHADER = ClassId(0x00000037, 0)
METAL_SHADER = ClassId(0x00000039, 0)
ANISOTROPIC_SHADER = ClassId(0x2857F460, 0)
OREN_NAYAR_BLINN_SHADER = ClassId(0x2857F421, 0)
MULTI_LAYER_SHADER = ClassId(0x2857F470, 0)
TRANSLUCENT_SHADER = ClassId(0x2857F480, 0)
STRAUSS_SHADER = ClassId(0x2857F450, 0)  # 0 color, 1 glossiness, 2 metalness

ShaderIds = collections.namedtuple("ShaderIds", "diffuse specular level glossiness si_amount si_color use_si_color")
_BLINN_IDS = ShaderIds(1, 2, 9, 10, 7, 8, 6)
SHADERS = {
    PHONG_SHADER: _BLINN_IDS,
    classids.BLINN_SHADER: _BLINN_IDS,
    METAL_SHADER: _BLINN_IDS,
    ANISOTROPIC_SHADER: ShaderIds(1, 2, 5, 7, 6, 3, 14),
    OREN_NAYAR_BLINN_SHADER: ShaderIds(1, 2, 6, 5, 4, 3, 13),
    MULTI_LAYER_SHADER: ShaderIds(1, 6, 7, 8, 3, 2, 19),  # the first specular layer
    TRANSLUCENT_SHADER: ShaderIds(1, 2, 6, 5, 4, 3, 14),
}
# Standard map slots: index into block 3's tables (mapEnables 0, maps 1, mapAmounts 2)
STD_DIFFUSE, STD_SPECULAR, STD_LEVEL, STD_GLOSSINESS, STD_SELF_ILLUM, STD_OPACITY, STD_BUMP, STD_REFLECTION = (
    1, 2, 3, 4, 5, 6, 8, 9)
STD_DIFFUSE_DEFAULT = (150 / 255,) * 3
STD_SPECULAR_DEFAULT = (0.9, 0.9, 0.9)


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
    two_sided: bool = False  # Standard's twoSided: 3ds Max renders the back faces too
    unknown: bool = False
    textures: dict = dataclasses.field(default_factory=dict)  # {input name: texmaps.TextureGraphIR}
    issues: list = dataclasses.field(default_factory=list)


class ConvertStats:
    """What the report needs: peeled {class name: wrapper objects peeled}, unknown {class name: materials made
    grey}, issues [(object index, reason)]."""
    __slots__ = ("peeled", "unknown", "issues")

    def __init__(self):
        self.peeled, self.unknown, self.issues = collections.Counter(), collections.Counter(), []


def mean(rgb):
    """The mean of the channels: the rules' measure of how strong a reflection or refraction color is."""
    return sum(rgb[:3]) / 3.0


def class_name(superclass, class_id):
    """The class name for the report: the class directory's for a known class (without the blanks around it:
    CoronaPhysicalMtl's starts with a carriage return), else the ClassID."""
    cid = ClassId(*class_id)
    return (classids.name_of(superclass, cid) or CLASS_NAMES.get(cid) or "ClassID%s" % (cid,)).strip()


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


def _mix(a, b, t):
    return tuple(x * (1.0 - t) + y * t for x, y in zip(a, b))


def _ior(v):
    return min(100.0, max(1.0, v))


def ior_from_reflectance(f0):
    """The IOR whose Fresnel reflectance at normal incidence is f0: ((n - 1) / (n + 1)) ** 2 = f0."""
    r = math.sqrt(min(0.99, max(0.0, f0)))
    return (1.0 + r) / (1.0 - r)


def _roughness(gloss, use_roughness):
    return _clamp01(gloss if use_roughness else 1.0 - gloss)


class MaterialConverter:
    """Converts the materials of one MaterialGraph, each object once."""

    def __init__(self, graph, texmaps=None, swatches=None):
        self.graph, self.texmaps = graph, texmaps
        if swatches is None:
            swatches = texmaps.swatches if texmaps is not None else colors.of_graph(graph)
        self.swatches = swatches
        self.stats = ConvertStats()
        self._done, self._peels, self._counted = {}, {}, set()
        self._multis, self._for, self._reported = {}, {}, set()

    def rgb(self, m, pid, block, default):
        """A swatch parameter as linear RGB by the scene's rule; default is the swatch value (0..1) used when the
        parameter is unusable."""
        v = m.param(pid, block)
        if not (isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3])):
            v = default
        return self.swatches.color(v)

    def issue(self, index, reason, ir=None):
        self.stats.issues.append((index, reason))
        if ir is not None:
            ir.issues.append(reason)

    def _issue_once(self, index, reason):
        """An issue material_for finds again for every face ID: reported once."""
        if (index, reason) not in self._reported:
            self._reported.add((index, reason))
            self.issue(index, reason)

    def to_map(self, m, ref, what, amount, invert=False, ir=None):
        """The MapRef of a reference found in material m's slot `what`: None for no reference or one that is not a
        map (an issue)."""
        if not isinstance(ref, pblock.Reference) or ref.index is None:
            return None
        if self.graph.superclass(ref.index) != classids.SC_TEXMAP:
            self.issue(m.index, "%s: object %d is not a map" % (what, ref.index), ir)
            return None
        return MapRef(ref.index, amount, invert)

    def map_ref(self, m, map_pid, on_pid, amount_pid, block, invert=False, ir=None, percent=True):
        """The MapRef of a map slot: None when it holds no map, is switched off or holds something else. The amount
        parameter is in percent, or a plain factor when not percent."""
        if on_pid is not None and not _flag(m, on_pid, block, True):
            return None
        scale = 100.0 if percent else 1.0
        amount = 1.0 if amount_pid is None else max(0.0, _num(m, amount_pid, block, scale) / scale)
        return self.to_map(m, m.param(map_pid, block), "parameter %d" % map_pid, amount, invert, ir)

    def is_class(self, index, superclass, class_id):
        try:
            m = self.graph.get(index)
        except ChunkError:
            return False
        return m.superclass == superclass and ClassId(*m.class_id) == class_id

    def bump_slot(self, ir, ref):
        """A map in a bump slot: a normal map class is the normal input, anything else a height map."""
        if ref is None:
            return
        if any(self.is_class(ref.index, classids.SC_TEXMAP, k) for k in _texmaps.NORMAL_MAPS):
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
            for k, v in enumerate(values if isinstance(values, list) else [values]):
                if key == classids.CORONA_LAYERED_MTL and pid == CORONA_LAYERS:
                    on = m.param(CORONA_LAYERS_ON, 0, tab=k)
                    if _finite(on) and not on:
                        continue
                if isinstance(v, pblock.Reference) and v.index is not None:
                    if self.graph.superclass(v.index) != classids.SC_MATERIAL:
                        return None, "%s: sub-material %d is not a material" % (m.name or "wrapper", v.index)
                    return v.index, None
        return None, "%s: no sub-material" % (m.name or "wrapper")

    def peel(self, index):
        """(object index of the material a wrapper stands for, None), the index itself for an object that is no
        wrapper; (None, reason) when the peel ends without a material. The depth guard counts from index, so the
        same chain can fail from its top and succeed from lower down; the wrappers a failed peel walked through are
        counted in stats.peeled all the same."""
        if index in self._peels:
            return self._peels[index]
        chain, i, out = [], index, None
        while out is None:
            try:
                m = self.graph.get(i)
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
        """The MaterialIR of material object index, None for no index (a node without a material) or an object
        that is not a material."""
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        if index in self._done:
            return self._done[index]
        if self.graph.superclass(index) != classids.SC_MATERIAL:
            return None
        base, reason = self.peel(index)
        if base is None:
            ir = self._grey(index, reason)
        elif base != index:
            ir = self.convert(base)
        elif self.is_class(index, classids.SC_MATERIAL, classids.MULTI_SUB_MTL):
            ir = self._multi_default(index)
        else:
            ir = self._rule(index)
        self._done[index] = ir
        return ir

    def _multi(self, index):
        """(entries {zero-based material ID: sub-material object index or None (off or empty)} of a Multi/Sub-Object,
        the IDs in list order)."""
        if index in self._multis:
            return self._multis[index]
        block = self.graph.get(index).block(0)
        values = (lambda pid: block.value(pid)) if block is not None else (lambda pid: None)
        materials, enabled, ids = values(MULTI_MATERIALS), values(MULTI_ENABLED), values(MULTI_IDS)
        materials = materials if isinstance(materials, list) else []
        enabled = enabled if isinstance(enabled, list) else []
        if not isinstance(ids, list):
            ids = list(range(len(materials)))
        entries, order = {}, []
        for k, mid in enumerate(ids):
            if not isinstance(mid, int) or isinstance(mid, bool) or mid < 0 or mid in entries:
                continue
            ref = materials[k] if k < len(materials) else None
            on = enabled[k] if k < len(enabled) else 1
            off = _finite(on) and not on
            sub = None if off or not isinstance(ref, pblock.Reference) else ref.index
            entries[mid] = sub
            order.append(mid)
        self._multis[index] = entries, order
        return entries, order

    def _multi_default(self, index):
        """The IR of a Multi/Sub-Object for a caller without face IDs: its first entry that is on and set."""
        entries, order = self._multi(index)
        for mid in order:
            if entries[mid] is not None:
                ir = self.material_for(index, mid)
                if ir is not None:
                    return ir
        try:
            name = self.graph.get(index).name or "Multi/Sub-Object"
        except ChunkError:
            name = "Multi/Sub-Object"
        return self._grey(index, "%s: no sub-material" % name)

    def material_for(self, index, material_id):
        """The MaterialIR a face with that zero-based material ID renders with under material object index: wrappers
        peeled, Multi/Sub-Objects looked up by the ID (nested ones with the same ID); None for no material, an ID
        without an entry, an entry switched off or empty, or a Multi/Sub-Object cycle or chain deeper than
        MAX_PEEL (an issue)."""
        key = (index, material_id)
        if key in self._for:
            return self._for[key]
        chain, i, out = [], index, None
        while True:
            if not isinstance(i, int) or isinstance(i, bool) or self.graph.superclass(i) != classids.SC_MATERIAL:
                if chain and isinstance(i, int) and not isinstance(i, bool):
                    self._issue_once(chain[-1], "Multi/Sub-Object %d: sub-material %d is not a material"
                                     % (chain[-1], i))
                break
            base, _reason = self.peel(i)
            if base is None or not self.is_class(base, classids.SC_MATERIAL, classids.MULTI_SUB_MTL):
                out = self.convert(i)
                break
            if base in chain:
                self._issue_once(index, "Multi/Sub-Object cycle through object %d" % base)
                break
            if len(chain) == MAX_PEEL:
                self._issue_once(index, "more than %d nested Multi/Sub-Objects below object %d" % (MAX_PEEL, index))
                break
            chain.append(base)
            i = self._multi(base)[0].get(material_id)
        self._for[key] = out
        return out

    def _grey(self, index, reason):
        """The grey material for an object no rule converts, named after it."""
        try:
            m = self.graph.get(index)
            name, source = m.name, class_name(m.superclass, m.class_id)
        except ChunkError:
            name, source = "", ""
        g = colors.srgb_to_linear(GREY_SRGB)
        ir = MaterialIR(index, name, source, base_color=Input((g, g, g)), unknown=True)
        if reason:
            self.issue(index, reason, ir)
        return ir

    def _rule(self, index):
        try:
            m = self.graph.get(index)
        except ChunkError as e:
            return self._grey(index, "object %d: %s" % (index, e))
        source = class_name(m.superclass, m.class_id)
        rule = RULES.get((m.superclass, ClassId(*m.class_id)))
        if rule is None:
            self.stats.unknown[source] += 1
            return self._grey(index, "")
        ir = MaterialIR(index, m.name, source)
        rule(self, m, ir)
        if self.texmaps is not None:
            ir.textures = _texmaps.texture_graphs(ir, self.texmaps)
            for g in ir.textures.values():
                ir.issues.extend(g.issues)
        return ir


def vray_mtl(conv, m, ir):
    """VRayMtl: blocks 1 basic, 2 BRDF, 3 options, 4 maps (map id, on = id + 50, multiplier in % = id + 100)."""
    use_roughness = _flag(m, 89, 2, False)  # brdf_useRoughness
    diffuse = conv.rgb(m, 1, 1, (0.5, 0.5, 0.5))
    reflection = conv.rgb(m, 2, 1, (0.0, 0.0, 0.0))
    refraction = conv.rgb(m, 5, 1, (0.0, 0.0, 0.0))
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
    ir.emission_color = Input(conv.rgb(m, 81, 1, (0.0, 0.0, 0.0)), emit_map)  # selfIllumination
    if max(ir.emission_color.value) > 0 or emit_map is not None:
        ir.emission_strength = max(0.0, _num(m, 83, 1, 1.0))  # selfIllumination_multiplier

    ir.transmission = Input(t, conv.map_ref(m, 102, 152, 202, 4, ir=ir))  # texmap_refraction
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
    """VRayFastSSS2, block 0: 26 diffuse_color, 27 / 28 its map (on), 36 diffuse_amount, 2 sub_surface_color,
    0 scatter_radius (cm, a plain float: not in system units), 22 scale, 31 IOR, 40 specular_color, 51 specular_glossiness, 3 / 4 texmap_bump (on),
    85 / 86 texmap_opacity (on)."""
    ir.base_color = Input(conv.rgb(m, 26, 0, (0.5, 0.5, 0.5)), conv.map_ref(m, 27, 28, None, 0, ir=ir))
    ir.roughness = Input(_roughness(_num(m, 51, 0, 0.6), False))
    ir.specular = Input(_clamp01(mean(conv.rgb(m, 40, 0, (1.0, 1.0, 1.0)))))
    ir.ior = _ior(_num(m, 31, 0, 1.3))
    ir.subsurface_weight = _clamp01(1.0 - _num(m, 36, 0, 0.0))
    ir.subsurface_color = conv.rgb(m, 2, 0, (1.0, 1.0, 1.0))
    ir.subsurface_radius = max(0.0, _num(m, 0, 0, 1.0) * _num(m, 22, 0, 1.0)) * 0.01
    conv.bump_slot(ir, conv.map_ref(m, 3, 4, None, 0, ir=ir))
    ir.alpha = Input(1.0, conv.map_ref(m, 85, 86, None, 0, ir=ir))


def _car_paint(conv, m, ir, base_gloss, bump_pid):
    """Both car paints, block 0: 0 base_color, 1 / 2 its map (on), 4 base_reflection, 8 base_glossiness,
    27 coat_color, 39 coat_glossiness, then the base bump map and its on switch at bump_pid, bump_pid + 1."""
    ir.base_color = Input(conv.rgb(m, 0, 0, (0.3, 0.4, 0.5)), conv.map_ref(m, 1, 2, None, 0, ir=ir))
    ir.roughness = Input(_roughness(_num(m, 8, 0, base_gloss), False))
    ir.metallic = Input(1.0)
    ir.specular = Input(_clamp01(_num(m, 4, 0, 0.5)))
    ir.coat_color = conv.rgb(m, 27, 0, (1.0, 1.0, 1.0))
    ir.coat_roughness = _roughness(_num(m, 39, 0, 1.0), False)
    conv.bump_slot(ir, conv.map_ref(m, bump_pid, bump_pid + 1, None, 0, ir=ir))


def vray_car_paint_mtl(conv, m, ir):
    """31 coat_strength: the coat's reflectance at normal incidence (default 0.05), not a weight; 55 / 56 bump."""
    _car_paint(conv, m, ir, 0.6, 55)
    f0 = _clamp01(_num(m, 31, 0, 0.05))
    ir.coat_weight = 1.0 if f0 > 0 else 0.0
    ir.coat_ior = ior_from_reflectance(f0)


def vray_car_paint_mtl2(conv, m, ir):
    """31 coat_amount (weight), 81 coat_ior; 54 / 55 bump."""
    _car_paint(conv, m, ir, 0.4, 54)
    ir.coat_weight = _clamp01(_num(m, 31, 0, 1.0))
    ir.coat_ior = _ior(_num(m, 81, 0, 1.5))


class _PartParams:
    """The parameters of a material's part (its blocks), read like a MtlBase's: param(pid, block_id)."""

    def __init__(self, part):
        self._blocks = [b for _slot, b in sorted(part.blocks.items())] if part is not None else []

    def param(self, pid, block_id=None, tab=0, default=None):
        for b in self._blocks:
            if (block_id is None or b.block_id == block_id) and pid in b:
                return b.get(pid, tab, default)
        return default


def _std_map(conv, m, slot, ir, invert=False):
    """Standard's map slot (block 3: mapEnables 0, maps 1, mapAmounts 2, one table element per slot): None when
    empty or switched off; its amount is a fraction."""
    on = m.param(0, 3, tab=slot)
    if _finite(on) and not on:
        return None
    amount = m.param(2, 3, tab=slot)
    amount = max(0.0, float(amount)) if _finite(amount) else 1.0
    return conv.to_map(m, m.param(1, 3, tab=slot), "map slot %d" % slot, amount, invert, ir)


def standard_mtl(conv, m, ir):
    """Standard: block 0 shader (2 twoSided), block 1 extended (1 opacity, 6 ior), block 3 maps; the colors in the
    shader part's block 0 (SHADERS, STRAUSS_SHADER)."""
    ir.two_sided = _flag(m, 2, 0, False)
    ir.ior = _ior(_num(m, 6, 1, 1.5))
    ir.alpha = Input(_clamp01(_num(m, 1, 1, 1.0)), _std_map(conv, m, STD_OPACITY, ir))
    shader = next((p for _slot, p in sorted(m.parts.items()) if p.superclass == classids.SC_SHADER), None)
    sid = ClassId(*shader.class_id) if shader is not None else None
    s = _PartParams(shader)
    gloss_map = _std_map(conv, m, STD_GLOSSINESS, ir, invert=True)
    level_map = _std_map(conv, m, STD_LEVEL, ir) or _std_map(conv, m, STD_SPECULAR, ir)
    emit_map = _std_map(conv, m, STD_SELF_ILLUM, ir)
    specular, amount, emit = 0.0, 0.0, None
    if sid == STRAUSS_SHADER:
        diffuse, gloss = conv.rgb(s, 0, 0, STD_DIFFUSE_DEFAULT), _num(s, 1, 0, 0.1)
        ir.metallic = Input(_clamp01(_num(s, 2, 0, 0.0)))
        specular = 0.5
    elif sid in SHADERS:
        ids = SHADERS[sid]
        diffuse, gloss = conv.rgb(s, ids.diffuse, 0, STD_DIFFUSE_DEFAULT), _num(s, ids.glossiness, 0, 0.1)
        specular = max(0.0, _num(s, ids.level, 0, 0.0)) * mean(conv.rgb(s, ids.specular, 0, STD_SPECULAR_DEFAULT))
        if _flag(s, ids.use_si_color, 0, False):
            emit = conv.rgb(s, ids.si_color, 0, (0.0, 0.0, 0.0))
        else:
            amount = max(0.0, _num(s, ids.si_amount, 0, 0.0))
        if sid == METAL_SHADER:
            ir.metallic = Input(1.0)
    else:
        diffuse, gloss = conv.swatches.color(STD_DIFFUSE_DEFAULT), 0.1
        conv.issue(m.index, "Standard: shader %s has no rule: its defaults" % (
            "missing" if sid is None else "ClassID%s" % (sid,)), ir)
    ir.base_color = Input(diffuse, _std_map(conv, m, STD_DIFFUSE, ir))
    ir.roughness = Input(_roughness(gloss, False), gloss_map)
    reflection = _std_map(conv, m, STD_REFLECTION, ir)
    if reflection is not None:
        specular = max(specular, min(1.0, reflection.amount))
    ir.specular = Input(_clamp01(specular), level_map)
    if emit is not None:  # its own color, at full strength
        ir.emission_color = Input(emit, emit_map)
        ir.emission_strength = 1.0 if max(emit) > 0 or emit_map is not None else 0.0
    elif amount > 0 or emit_map is not None:  # the diffuse lights itself by the amount; a map overrides it
        ir.emission_color = Input(diffuse, emit_map)
        ir.emission_strength = 1.0 if emit_map is not None else amount
    conv.bump_slot(ir, _std_map(conv, m, STD_BUMP, ir))


def physical_mtl(conv, m, ir):
    """Physical Material, block 0: 1 base_weight, 2 base_color, 3 reflectivity, 4 roughness, 5 roughness_inv,
    6 metalness, 10 refl_color, 30 transparency, 31 trans_color, 33 trans_ior, 37 thin_walled, 50 emission,
    51 emit_color, 52 emit_luminance, 60 coating, 61 coat_color, 62 coat_roughness, 63 coat_roughness_inv,
    66 coat_ior; maps 101 base_color, 102 reflectivity, 104 roughness, 105 metalness, 109 transparency,
    116 emission, 117 emit_color, 130 bump (amount 230, a factor), 133 cutout, each switched on by id + 50."""
    weight = _clamp01(_num(m, 1, 0, 1.0))
    base = tuple(c * weight for c in conv.rgb(m, 2, 0, (0.5, 0.5, 0.5)))
    t = _clamp01(_num(m, 30, 0, 0.0))
    if t > 0:
        base = _mix(base, conv.rgb(m, 31, 0, (1.0, 1.0, 1.0)), t)
    ir.base_color = Input(base, conv.map_ref(m, 101, 151, None, 0, ir=ir))
    inverted = _flag(m, 5, 0, False)
    r = _clamp01(_num(m, 4, 0, 0.0))
    ir.roughness = Input(1.0 - r if inverted else r, conv.map_ref(m, 104, 154, None, 0, invert=inverted, ir=ir))
    ir.metallic = Input(_clamp01(_num(m, 6, 0, 0.0)), conv.map_ref(m, 105, 155, None, 0, ir=ir))
    ir.specular = Input(_clamp01(max(0.0, _num(m, 3, 0, 1.0)) * mean(conv.rgb(m, 10, 0, (1.0, 1.0, 1.0)))),
                        conv.map_ref(m, 102, 152, None, 0, ir=ir))
    ir.transmission = Input(t, conv.map_ref(m, 109, 159, None, 0, ir=ir))
    ir.ior = _ior(_num(m, 33, 0, 1.52))
    ir.thin_walled = _flag(m, 37, 0, False)
    # A map in a weight slot stands for the weight, one in a color slot only for the color: weight 0 and a color
    # map is no emission. The IR has no strength map, so the weight map drives the color when no color map does.
    color_map = conv.map_ref(m, 117, 167, None, 0, ir=ir)
    weight_map = conv.map_ref(m, 116, 166, None, 0, ir=ir)
    emission = max(0.0, _num(m, 50, 0, 0.0))
    if emission > 0 or weight_map is not None:
        if color_map is not None and weight_map is not None:
            conv.issue(m.index, "Physical Material: emission weight map %d not used beside the color map"
                       % weight_map.index, ir)
        ir.emission_color = Input(conv.rgb(m, 51, 0, (1.0, 1.0, 1.0)), color_map or weight_map)
        luminance = max(0.0, _num(m, 52, 0, 1500.0))
        ir.emission_strength = (1.0 if weight_map is not None else emission) * luminance / LUMENS_PER_WATT
    ir.coat_weight = _clamp01(_num(m, 60, 0, 0.0))
    ir.coat_color = conv.rgb(m, 61, 0, (1.0, 1.0, 1.0))
    c = _clamp01(_num(m, 62, 0, 0.0))
    ir.coat_roughness = 1.0 - c if _flag(m, 63, 0, False) else c
    ir.coat_ior = _ior(_num(m, 66, 0, 1.52))
    conv.bump_slot(ir, conv.map_ref(m, 130, 180, 230, 0, ir=ir, percent=False))
    ir.alpha = Input(1.0, conv.map_ref(m, 133, 183, None, 0, ir=ir))


def _corona_amount_map(conv, m, map_pid, ir, invert=False):
    """A Corona map slot: the map at map_pid, its switch at + 1, its amount (a fraction) at + 2."""
    return conv.map_ref(m, map_pid, map_pid + 1, map_pid + 2, 0, invert=invert, ir=ir, percent=False)


def corona_physical_mtl(conv, m, ir):
    """CoronaPhysicalMtl, block 0 (map, its switch and amount at id, id + 1, id + 2): 101 baseColor, 102 baseLevel,
    103 base map, 111 metalnessMode, 121 opacityColor, 122 opacityLevel, 123 opacity map, 131 baseRoughness,
    132 its map, 171 baseIor, 191 refractionAmount, 192 its map, 203 useThinMode, 211 clearcoatAmount,
    221 clearcoatIor, 231 clearcoatRoughness, 331 selfIllumColor, 332 selfIllumLevel, 333 its map, 351 baseBump map,
    381 thinAbsorptionColor, 391 clearcoatAbsorptionColor, 411 / 412 metalness map (on), 421 roughnessMode (1:
    every roughness is a glossiness)."""
    gloss = m.param(421, 0) == 1
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
    ir.ior = _ior(_num(m, 171, 0, 1.5))
    if m.param(461, 0) not in (None, 0):  # iorMode: only the default (baseIor is the IOR) has been measured
        conv.issue(m.index, "CoronaPhysicalMtl %r: IOR mode %r read as an IOR" % (m.name, m.param(461, 0)), ir)
    ir.thin_walled = thin
    opacity = _clamp01(mean(conv.rgb(m, 121, 0, (1.0, 1.0, 1.0))) * max(0.0, _num(m, 122, 0, 1.0)))
    ir.alpha = Input(opacity, _corona_amount_map(conv, m, 123, ir))
    ir.emission_color = Input(conv.rgb(m, 331, 0, (1.0, 1.0, 1.0)), _corona_amount_map(conv, m, 333, ir))
    ir.emission_strength = max(0.0, _num(m, 332, 0, 0.0))
    ir.coat_weight = _clamp01(_num(m, 211, 0, 0.0))
    ir.coat_ior = _ior(_num(m, 221, 0, 1.5))
    c = _clamp01(_num(m, 231, 0, 0.0))
    ir.coat_roughness = 1.0 - c if gloss else c
    ir.coat_color = conv.rgb(m, 391, 0, (1.0, 1.0, 1.0))
    conv.bump_slot(ir, _corona_amount_map(conv, m, 351, ir))


def corona_legacy_mtl(conv, m, ir):
    """CoronaLegacyMtl (CoronaMtl), block 0: colors 101 diffuse, 102 reflect, 103 refract, 105 opacity, 107
    selfIllum; their levels 121, 122, 123, 127, 128; maps 141 diffuse, 142 reflect, 143 reflectGlossiness,
    144 refract, 146 opacity, 147 bump, 158 selfIllum, each switched on by id + 20, with amounts (fractions) 290,
    291, 292, 293, 295, 296, 303; 180 reflectGlossiness, 182 fresnelIor,
    183 ior, 210 thin. 402 pbrMode only changes how Corona curves the glossiness: 1 - glossiness either way."""
    def slot(map_pid, on_pid, amount_pid, invert=False):
        return conv.map_ref(m, map_pid, on_pid, amount_pid, 0, invert=invert, ir=ir, percent=False)
    diffuse = tuple(min(1.0, c * max(0.0, _num(m, 121, 0, 1.0))) for c in conv.rgb(m, 101, 0, (0.5, 0.5, 0.5)))
    reflect_color = conv.rgb(m, 102, 0, (1.0, 1.0, 1.0))
    reflection = tuple(min(1.0, c * max(0.0, _num(m, 122, 0, 0.0))) for c in reflect_color)
    refract_color = conv.rgb(m, 103, 0, (1.0, 1.0, 1.0))
    t = _clamp01(mean(refract_color) * max(0.0, _num(m, 123, 0, 0.0)))
    reflection_map = slot(142, 162, 291)
    fresnel_ior = _num(m, 182, 0, 1.52)
    ir.base_color = Input(_mix(diffuse, refract_color, t) if t > 0 else diffuse, slot(141, 161, 290))
    ir.specular = Input(_clamp01(mean(reflection)), reflection_map)
    ir.roughness = Input(_roughness(_num(m, 180, 0, 1.0), False), slot(143, 163, 292, invert=True))
    if fresnel_ior >= CORONA_METAL_IOR and mean(reflection) >= METAL_REFLECTION:
        ir.metallic = Input(1.0)
        ir.base_color = Input(reflection, reflection_map)
    ir.transmission = Input(t, slot(144, 164, 293))
    ir.ior = _ior(_num(m, 183, 0, 1.52) if t > 0 else fresnel_ior)
    ir.thin_walled = _flag(m, 210, 0, False)
    opacity = _clamp01(mean(conv.rgb(m, 105, 0, (1.0, 1.0, 1.0))) * max(0.0, _num(m, 127, 0, 1.0)))
    ir.alpha = Input(opacity, slot(146, 166, 295))
    ir.emission_color = Input(conv.rgb(m, 107, 0, (1.0, 1.0, 1.0)), slot(158, 178, 303))
    ir.emission_strength = max(0.0, _num(m, 128, 0, 0.0))
    conv.bump_slot(ir, slot(147, 167, 296))


def corona_light_mtl(conv, m, ir):
    """CoronaLightMtl, block 0: 110 intensity, 111 / 112 texmap (on), 113 color, 150 / 151 opacityTexmap (on)."""
    ir.base_color, ir.roughness, ir.specular = Input((0.0, 0.0, 0.0)), Input(1.0), Input(0.0)
    ir.emission_color = Input(conv.rgb(m, 113, 0, (1.0, 1.0, 1.0)), conv.map_ref(m, 111, 112, None, 0, ir=ir))
    ir.emission_strength = max(0.0, _num(m, 110, 0, 1.0))
    ir.alpha = Input(1.0, conv.map_ref(m, 150, 151, None, 0, ir=ir))


# (superclass, ClassId) -> rule(converter, MtlBase, MaterialIR): fills the IR in place
RULES = {
    (classids.SC_MATERIAL, classids.STANDARD_MTL): standard_mtl,
    (classids.SC_MATERIAL, classids.PHYSICAL_MTL): physical_mtl,
    (classids.SC_MATERIAL, classids.VRAY_MTL): vray_mtl,
    (classids.SC_MATERIAL, VRAY_LIGHT_MTL): vray_light_mtl,
    (classids.SC_MATERIAL, VRAY_FAST_SSS2): vray_fast_sss2,
    (classids.SC_MATERIAL, VRAY_CAR_PAINT_MTL): vray_car_paint_mtl,
    (classids.SC_MATERIAL, VRAY_CAR_PAINT_MTL2): vray_car_paint_mtl2,
    (classids.SC_MATERIAL, classids.CORONA_PHYSICAL_MTL): corona_physical_mtl,
    (classids.SC_MATERIAL, classids.CORONA_LEGACY_MTL): corona_legacy_mtl,
    (classids.SC_MATERIAL, classids.CORONA_LIGHT_MTL): corona_light_mtl,
}


class MeshSlots:
    """The material slots of one mesh: users the object indices of the nodes sharing it (MeshDescription.users);
    slots [[MaterialIR or None per user]] per slot (None: an empty slot); indices int32 per face, its slot."""
    __slots__ = ("users", "slots", "indices")

    def __init__(self, users, slots, indices):
        self.users, self.slots, self.indices = users, slots, indices

    def __repr__(self):
        return "MeshSlots(%d users, %d slots)" % (len(self.users), len(self.slots))


def node_materials(scene, desc):
    """{node object index: its material's object index, None without one} for the nodes of desc (a reader Scene
    and the SceneDescription made from it)."""
    out = {}
    for node in desc.nodes:
        try:
            out[node.index] = scene.node(node.index).material
        except (ChunkError, IndexError):
            out[node.index] = None
    return out


def assign(desc, materials, conv):
    """{mesh key: MeshSlots} for the meshes of desc. materials: {node object index: material object index or None}
    (node_materials). A mesh's distinct face IDs, ascending, are grouped by the materials its users get for them
    (material_for, by identity): one slot per group in order of first appearance. A mesh whose only group has no
    material gets no slot."""
    import numpy
    out = {}
    for key, md in desc.meshes.items():
        users = list(md.users)
        faces = numpy.asarray(md.material_indices, dtype=numpy.int64).ravel()
        ids, inverse = numpy.unique(faces, return_inverse=True)
        groups, slots, slot_of_id = {}, [], []
        for mid in ids.tolist():
            irs = [conv.material_for(materials.get(u), mid) for u in users]
            k = tuple(id(ir) for ir in irs)  # the IRs stay referenced by slots: their ids are not reused
            if k not in groups:
                groups[k] = len(slots)
                slots.append(irs)
            slot_of_id.append(groups[k])
        if len(slots) == 1 and all(ir is None for ir in slots[0]):
            slots, slot_of_id = [], [0] * len(slot_of_id)
        indices = numpy.asarray(slot_of_id, dtype=numpy.int32)[inverse.ravel()] if len(faces) else \
            numpy.zeros(0, dtype=numpy.int32)
        out[key] = MeshSlots(users, slots, numpy.ascontiguousarray(indices, dtype=numpy.int32))
    return out
