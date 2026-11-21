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
    slots = assign(desc, node_materials(scene, desc), conv)   # Slots {mesh key: MeshSlots}, for build/objects.py
    slots.curves                        # {curve key: MeshSlots}: the slot of each curve with a material
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
  color (as in every rule, a reflection weight: 1 is the full Fresnel reflection at the IOR, which
  build/materials.py draws as Specular IOR Level 0.5, and a weight between 0 and 1 as a Mix Shader by it over a
  twin without reflection, so the whole curve scales as V-Ray scales it; with Fresnel on a white and a grey one
  match V-Ray 5.2 at every angle, measured in the maxdrop-em3.34 and maxdrop-em3.119 plans);
  emission = self-illumination color times its multiplier; transmission = the mean of the refraction color,
  ior and thin-walled from the refraction parameters; maps where their slot is on, with their multiplier as the
  amount; a normal map (VRayNormalMap, Normal Bump, CoronaNormal) in a bump slot is the normal input, any other
  map the bump input. Added here: a refracting material takes its base color from the refraction color (mixed by
  the transmission), and with Fresnel off a bright reflection (mean >= METAL_REFLECTION) makes the material a metal
  in the reflection color; beside a reflection map only the swatch's share counts (its mean times 1 - the map
  amount): a map at full amount hides the swatch, so it never makes a metal (the map itself is not judged).
  The Fresnel IOR is the refraction IOR when the material refracts or locks the IOR, else the reflection IOR.
- VRayLightMtl -> emission only; VRayFastSSS2 -> base + subsurface; VRayCarPaintMtl / VRayCarPaintMtl2 -> a metal
  base + coat (VRayCarPaintMtl's coat_strength is the coat's reflectance at normal incidence: a full coat whose
  IOR gives that reflectance; VRayCarPaintMtl2's coat_amount is the coat weight).
- Standard: the colors come from its shader (ids per shader class in SHADERS; Metal is a metal, Strauss has a
  metalness and no specular level: specular 1, the IOR's own Fresnel); base = diffuse; roughness = 1 - glossiness;
  specular = specular level times the mean of the linear specular color; alpha = opacity; self-illumination: its
  color at strength 1, or the diffuse at the amount; two-sided flag; map slots with their amounts where switched
  on (a glossiness map inverted; the specular level map drives the specular, else the specular color map); a map
  in the reflection slot makes the specular at least that slot's amount (the map is an environment: not used).
- Physical Material: base = base color times base weight; roughness (1 - it with roughness_inv); metalness;
  specular = reflectivity times the mean of the linear reflection color; transparency is the transmission and
  mixes the transparency color into the base, as for VRayMtl; IOR, thin-walled; emission color at emission
  weight times luminance / LUMENS_PER_WATT (cd/m2 to Blender's W/(m2 sr)), a weight map standing for the
  weight; coating; map slots where on.
- CoronaPhysicalMtl: base = base color times base level; roughness, or 1 - it in glossiness mode (every roughness
  of the material, a map then inverted); metallic from the metalness mode; transmission = refraction amount, the base
  mixed toward white (thin mode: the thin absorption color) by it; IOR, thin mode; alpha = the mean of the linear
  opacity color times its level; emission color at its level; clearcoat amount, IOR, roughness and absorption color;
  sheen amount, color and roughness; SSS amount, radius (world units, in meters) and scatter color (the per-channel
  radius); a metal with a complex IOR takes the F0 of its n and k as its base color; maps where on, their amounts
  fractions. Specular 1, the IOR's own Fresnel (the material has no reflection level). Translucency, volumetric
  absorption and scattering, a metal edge color other than the default, the IOR mode and maps in the sheen and SSS
  slots are named issues.
- CoronaLegacyMtl (CoronaMtl): diffuse, reflection, refraction, opacity and self-illumination colors times their
  levels; specular = the mean reflection; roughness = 1 - glossiness (PBR mode or not); transmission and the glass
  base color as for VRayMtl, the IOR as well (refraction IOR when it refracts, else the Fresnel IOR); a Fresnel IOR
  of CORONA_METAL_IOR or more with a bright reflection (as METAL_REFLECTION) is a metal in the reflection color;
  SSS as the physical material's. PBR mode off, translucency and absorption are named issues.
- CoronaLightMtl -> emission (color, intensity, map) and its opacity map.
- CoronaSkinMtl -> one Principled layer: skin color times level, its three SSS layers as one (weighted mean radius
  times the radius scale, weighted mean color), the first reflection as specular, roughness and IOR, opacity, bump.
- CoronaLayeredMtl with a base and a layer that is on -> the base's IR with its layers (Layer: IR, amount, mask
  with its mask amount; at most MAX_LAYERS), which build/materials.py mixes over it; the weight is the amount times
  lerp(1, mask, mask amount), Corona's map-amount convention (not measured: no Corona render here).
- Wrappers (VRay2SidedMtl, VRayBlendMtl, VRayOverrideMtl, VRayMtlWrapper, Double Sided, Shellac, CoronaLayeredMtl
  without a base or without a layer on: base, then its layers that are on; CoronaRaySwitchMtl: direct, GI, reflect,
  refract, each where switched on) -> the first set sub-material in 3ds Max's getSubMtl order; CoronaSelectMtl -> its
  selected material (zero-based: the default is 0); Shell Material -> its render sub-material. Peeling stops at any
  other class (a Multi/Sub-Object included), at most MAX_PEEL wrappers deep; each wrapper object peeled counts once.
- Multi/Sub-Object: entry k has the material ID materialIDList[k] (zero-based, as the faces store it), the
  material materialList[k] and the switch mapEnabled[k]; the first entry with an ID wins. A face ID without an
  entry wraps as 3ds Max renders it: to ID modulo (the highest ID of the list + 1), every entry counted. A face ID
  that still has no entry, or whose entry is switched off or empty, gets no material (an empty slot; 3ds Max renders
  it black). A Multi/Sub-Object inside a wrapper or inside another Multi/Sub-Object (which looks up the face's own
  ID and wraps it by its own list) resolves the same way, at most MAX_PEEL deep. convert() of one (a caller
  without face IDs) gives the material of its first entry that is on and set.
- Any other class -> a grey material that keeps its name (specular 1, the IOR's own Fresnel), counted by class name.

The slots of a mesh (assign): its distinct face IDs, each keyed by the materials its users (the nodes sharing the
mesh) get for that ID; one slot per key, in ID order, faces remapped to their slot. A material that is not a
Multi/Sub-Object gives one slot; an empty key (no material) is a slot only beside others. A curve (a shape node
built as a curve) has one slot, keyed by the materials its users get for material ID 1, none when no user has one:
the shape reader does not read the segments' material IDs.

Colors are 3ds Max swatches, clamped to 0..1 and made linear by the scene's swatch rule (convert/colors.py): the
value itself when the scene was saved with the gamma on (or does not say), the sRGB curve when it was off.
A missing, animated or non-finite parameter takes the class's default; an IOR is clamped to 1..100. The SSS radius is
in meters: VRayFastSSS2's scatter_radius is in centimeters whatever the system unit, multiplied by its scale (V-Ray's
documentation says both). VRayCarPaintMtl's coat_strength is, in V-Ray's documentation, the strength of the coat
reflections seen from the front; that Fresnel gives the other angles is this rule's reading.
Parameter ids: docs/FORMAT.md for the classes of the fixtures (the Corona ones: Corona 12; the V-Ray ones: V-Ray 5.2);
standard_shaders sets every shader's ids and the Physical Material's maps. The Standard map slots (STD_*) are Blinn's
map channels, not yet the other shaders' (maxdrop-em3.104).
No bpy, no mathutils.
"""
import collections
import dataclasses
import math

from ..reader import chunks, classids, pblock, units
from ..reader import scene as reader_scene
from ..reader.classdir import ClassId
from ..reader.errors import MaxFileError
from . import colors
from . import texmaps as _texmaps
from .params import finite as _finite, flag as _flag, num as _num

ChunkError = chunks.ChunkError

MAX_PEEL = 8
METAL_REFLECTION = 0.25  # mean linear reflection (about sRGB 137 grey) above which Fresnel off means metal
CORONA_EDGE_DEFAULT = 0.75  # CoronaPhysicalMtl's edgeColor as created (grey): not reported
CORONA_METAL_IOR = 10.0  # a CoronaLegacyMtl Fresnel IOR from which a bright reflection is a metal (made with 999)
GREY_SRGB = 128 / 255  # the grey of a material without a rule: MaxDrop's own, not a swatch

# wrapper ClassId -> its sub-material parameters (block 0) in getSubMtl order; a table parameter gives each element
WRAPPERS = {
    classids.VRAY_2SIDED_MTL: (0, 1),  # frontMtl, backMtl
    classids.VRAY_BLEND_MTL: (0, 1),  # baseMtl, coatMtl (table)
    classids.VRAY_OVERRIDE_MTL: (0, 2, 4, 6, 8),  # baseMtl, giMtl, reflectMtl, refractMtl, shadowMtl
    classids.VRAY_MTL_WRAPPER: (0,),  # baseMtl
    classids.DOUBLE_SIDED_MTL: (0, 1),  # material1 (facing), material2 (back)
    classids.SHELLAC_MTL: (0, 1),  # shellacMtl1 (base), shellacMtl2
    classids.CORONA_LAYERED_MTL: (1000, 1001),  # baseMtl, layers (table): a wrapper only without a layer on
    classids.CORONA_RAY_SWITCH_MTL: (1603, 1600, 1601, 1602),  # directMtl, giMtl, reflectMtl, refractMtl
    classids.CORONA_SELECT_MTL: (312,),  # materials (table): the one at selected (313, zero-based)
}
WRAPPER_SWITCHES = {classids.CORONA_RAY_SWITCH_MTL: {1603: 1613, 1600: 1610, 1601: 1611, 1602: 1612}}
CORONA_SELECT_LIST, CORONA_SELECT_INDEX = 312, 313
SHELL_RENDER_INDEX, SHELL_SUBS = 1, (2, 3)  # renderMtlIndex; originalMaterial, bakedMaterial
# CoronaLayeredMtl, block 0: 1000 baseMtl, 1001 layers, 1002 amounts, 1003 mixmaps (masks), 1004 layersOn, 1005 masksOn,
# 1006 maskAmounts (each a table, one element per layer)
CORONA_BASE, CORONA_LAYERS, CORONA_AMOUNTS, CORONA_MASKS, CORONA_LAYERS_ON, CORONA_MASKS_ON, CORONA_MASK_AMOUNTS = (
    1000, 1001, 1002, 1003, 1004, 1005, 1006)
MAX_LAYERS = 16  # layers mixed over a CoronaLayeredMtl's base (Corona offers 10)
MAX_LAYER_BSDFS = 64  # Principled BSDFs one material may draw, its layers' layers counted at each use
# (each may come with a twin without reflection, build/materials.py's reflection weight: at most twice as many nodes)
MAX_COMPLEX_IOR = 100.0  # n and k of a complex IOR are held within 0..this
DEFAULT_METERS = 0.0254  # meters per system unit of a scene that does not say: 3ds Max's default, inches

LUMENS_PER_WATT = 683.0  # luminous efficacy at 555 nm: cd/m2 -> W/(m2 sr)

# Multi/Sub-Object, block 0: materialList, mapEnabled, materialIDList (zero-based)
MULTI_MATERIALS, MULTI_ENABLED, MULTI_IDS = 0, 1, 3

# Standard: the shader is a part (superclass Shader); its block 0 holds the colors, with ids per shader class
# (fixture standard_shaders).
# Strauss (classids.STRAUSS_SHADER) has its own: 0 diffuse, 1 glossiness, 2 metalness.
ShaderIds = collections.namedtuple("ShaderIds", "diffuse specular level glossiness si_amount si_color use_si_color")
_BLINN_IDS = ShaderIds(1, 2, 9, 10, 7, 8, 6)
SHADERS = {
    classids.PHONG_SHADER: _BLINN_IDS,
    classids.BLINN_SHADER: _BLINN_IDS,
    classids.METAL_SHADER: _BLINN_IDS,
    classids.ANISOTROPIC_SHADER: ShaderIds(1, 2, 5, 7, 6, 3, 14),
    classids.OREN_NAYAR_BLINN_SHADER: ShaderIds(1, 2, 6, 5, 4, 3, 13),
    classids.MULTI_LAYER_SHADER: ShaderIds(1, 6, 7, 8, 3, 2, 19),  # the first specular layer
    classids.TRANSLUCENT_SHADER: ShaderIds(1, 2, 6, 5, 4, 3, 14),
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

# Standard map slots: index into block 3's tables (mapEnables 0, maps 1, mapAmounts 2). The tables follow the
# shader's map channels: these are Blinn's, Phong's and Metal's; the other shaders order them otherwise
# (docs/FORMAT.md) and are read with these all the same: maxdrop-em3.104.
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
    specular: Input = Input(1.0)  # a reflection weight: 1 is the IOR's own Fresnel (Blender's 0.5)
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
    sheen_weight: float = 0.0
    sheen_color: tuple = (1.0, 1.0, 1.0)
    sheen_roughness: float = 0.5
    two_sided: bool = False  # Standard's twoSided: 3ds Max renders the back faces too
    unknown: bool = False
    textures: dict = dataclasses.field(default_factory=dict)  # {input name: texmaps.TextureGraphIR}
    issues: list = dataclasses.field(default_factory=list)
    layers: list = dataclasses.field(default_factory=list)  # [Layer] mixed over this one, bottom first


@dataclasses.dataclass
class Layer:
    """A material mixed over the ones below it (CoronaLayeredMtl): its MaterialIR, its amount, its mask (a MapRef
    whose amount is the mask amount, or None) and the mask's TextureGraphIR (DATA) when a TexmapConverter made one.
    Its weight is amount x the mask graph, the graph being lerp(1, mask, mask amount)."""
    ir: MaterialIR
    amount: float = 1.0
    mask: object = None
    graph: object = None


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
    return (classids.name_of(superclass, cid) or "ClassID%s" % (cid,)).strip()


def _clamp01(v):
    return min(1.0, max(0.0, v))


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


def _scene_meters(graph):
    """Meters per system unit of a MaterialGraph's scene: what the file says, else DEFAULT_METERS."""
    s = getattr(graph, "scene", None)
    unit = units.system_unit(s) if isinstance(s, reader_scene.Scene) else None
    return unit.meters if unit is not None else DEFAULT_METERS


def f0_from_complex_ior(n, k):
    """The Fresnel reflectance at normal incidence of a conductor of complex IOR n + ik:
    ((n - 1)^2 + k^2) / ((n + 1)^2 + k^2)."""
    n, k = (min(MAX_COMPLEX_IOR, max(0.0, v)) for v in (n, k))
    return ((n - 1.0) ** 2 + k * k) / ((n + 1.0) ** 2 + k * k)


class MaterialConverter:
    """Converts the materials of one MaterialGraph, each object once."""

    def __init__(self, graph, texmaps=None, swatches=None, meters=None):
        self.graph, self.texmaps = graph, texmaps
        if swatches is None:
            swatches = texmaps.swatches if texmaps is not None else colors.of_graph(graph)
        self.swatches = swatches
        self.meters = meters if meters is not None else _scene_meters(graph)
        self.stats = ConvertStats()
        self._done, self._peels, self._counted = {}, {}, set()
        self._multis, self._for, self._reported = {}, {}, set()
        self._active = []  # the materials whose rule is running: a layer that comes back to one is a cycle
        self._bsdfs = {}  # id(MaterialIR) -> (the IR, the Principled BSDFs it draws): bsdf_count

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
        elif key == classids.CORONA_SELECT_MTL:
            return self._selected(m)
        else:
            pids = WRAPPERS[key]
        block = m.block(0)
        switches = WRAPPER_SWITCHES.get(key, {})
        for pid in pids:
            if pid in switches and not _flag(m, switches[pid], 0, True):
                continue
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

    def _selected(self, m):
        """CoronaSelectMtl: the material at selected (zero-based: its default is 0) in materials."""
        k = m.param(CORONA_SELECT_INDEX, 0)
        values = m.block(0).value(CORONA_SELECT_LIST) if m.block(0) is not None else None
        name = m.name or "CoronaSelectMtl"
        if not isinstance(k, int) or isinstance(k, bool) or not isinstance(values, list) or not 0 <= k < len(values):
            return None, "%s: selected %r has no material" % (name, k)
        v = values[k]
        if not isinstance(v, pblock.Reference) or v.index is None:
            return None, "%s: selected %d is empty" % (name, k)
        if self.graph.superclass(v.index) != classids.SC_MATERIAL:
            return None, "%s: sub-material %d is not a material" % (name, v.index)
        return v.index, None

    def corona_layers(self, m):
        """The layers of a CoronaLayeredMtl that are on and set: [(table position, object index)]."""
        block = m.block(0)
        values = block.value(CORONA_LAYERS) if block is not None else None
        out = []
        for k, v in enumerate(values if isinstance(values, list) else []):
            on = m.param(CORONA_LAYERS_ON, 0, tab=k)
            if (_finite(on) and not on) or not isinstance(v, pblock.Reference) or v.index is None:
                continue
            out.append((k, v.index))
        return out

    def bsdf_count(self, ir):
        """The Principled BSDFs build/materials.py draws for ir: one, plus its layers' at each use (a reflection
        weight's twin not counted: each BSDF draws at most one)."""
        k = id(ir)
        if k not in self._bsdfs:
            self._bsdfs[k] = (ir, 1 + sum(self.bsdf_count(layer.ir) for layer in ir.layers))
        return self._bsdfs[k][1]

    def _mixes_layers(self, m):
        """A CoronaLayeredMtl with a base and a layer on is a material of its own (corona_layered_mtl); without either
        it is a wrapper of the one it has."""
        base = m.param(CORONA_BASE, 0)
        return isinstance(base, pblock.Reference) and base.index is not None and bool(self.corona_layers(m))

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
            if m.superclass != classids.SC_MATERIAL or not (key in WRAPPERS or key == classids.SHELL_MTL) or (
                    key == classids.CORONA_LAYERED_MTL and self._mixes_layers(m)):
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
        elif index in self._active or len(self._active) >= MAX_PEEL:
            reason = ("material cycle through object %d" % index if index in self._active else
                      "more than %d layered materials below object %d" % (MAX_PEEL, self._active[0]))
            # Not kept for this object, but the materials converting above it keep IRs built around the grey:
            # only a damaged or crafted file (3ds Max authors neither a cycle nor 8 nested layered materials) gets
            # a result that depends on the order of conversion.
            return self._grey(index, reason)
        else:
            self._active.append(index)
            try:
                ir = self._rule(index)
            finally:
                self._active.pop()
        self._done[index] = ir
        return ir

    def _multi(self, index):
        """(entries {zero-based material ID: sub-material object index or None (off or empty)} of a Multi/Sub-Object,
        the IDs in list order: _entry wraps past the highest of them)."""
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

    def _entry(self, index, material_id):
        """The entry (sub-material object index or None) zero-based face ID material_id picks in Multi/Sub-Object
        index. An ID without an entry wraps modulo the highest ID of the list plus one, entries switched off or empty
        counted: what 3ds Max renders (one-based, as Max shows them: with IDs 3 and 7, face ID 10 gets 3, 14
        gets 7, 15 none). A negative ID never wraps: no entry."""
        entries, order = self._multi(index)
        if material_id not in entries and order and material_id >= 0:
            material_id %= max(order) + 1
        return entries.get(material_id)

    def material_for(self, index, material_id):
        """The MaterialIR a face with that zero-based material ID renders with under material object index: wrappers
        peeled, Multi/Sub-Objects looked up by the ID (_entry; nested ones with the same ID); None for no material,
        an ID without an entry after the wrap, an entry switched off or empty, or a Multi/Sub-Object cycle or chain
        deeper than MAX_PEEL (an issue)."""
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
            i = self._entry(base, material_id)
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
        made = rule(self, m, ir)
        if made is not None:  # a rule that builds its IR from others' (corona_layered_mtl): textures done
            return made
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
    # the swatch's share of the slot: a map at full amount hides it (a Falloff there is a dielectric's ramp)
    hidden = min(1.0, reflection_map.amount) if reflection_map is not None else 0.0
    shown = mean(reflection) * (1.0 - hidden)
    if not _flag(m, 8, 1, True) and shown >= METAL_REFLECTION:  # reflection_fresnel off
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
    ir.subsurface_color = conv.rgb(m, 2, 0, (0.5, 0.5, 0.5))
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
    ir.coat_ior = _ior(ior_from_reflectance(f0))


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
    shader part's block 0 (SHADERS; Strauss its own)."""
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
    if sid == classids.STRAUSS_SHADER:
        diffuse, gloss = conv.rgb(s, 0, 0, STD_DIFFUSE_DEFAULT), _num(s, 1, 0, 0.1)
        ir.metallic = Input(_clamp01(_num(s, 2, 0, 0.0)))
        specular = 1.0  # no specular level: the IOR's own Fresnel
    elif sid in SHADERS:
        ids = SHADERS[sid]
        diffuse, gloss = conv.rgb(s, ids.diffuse, 0, STD_DIFFUSE_DEFAULT), _num(s, ids.glossiness, 0, 0.1)
        specular = max(0.0, _num(s, ids.level, 0, 0.0)) * mean(conv.rgb(s, ids.specular, 0, STD_SPECULAR_DEFAULT))
        if _flag(s, ids.use_si_color, 0, False):
            emit = conv.rgb(s, ids.si_color, 0, (0.0, 0.0, 0.0))
        else:
            amount = max(0.0, _num(s, ids.si_amount, 0, 0.0))
        if sid == classids.METAL_SHADER:
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


def _corona_amount_map(conv, m, map_pid, ir, invert=False):
    """A Corona map slot: the map at map_pid, its switch at + 1, its amount (a fraction) at + 2."""
    return conv.map_ref(m, map_pid, map_pid + 1, map_pid + 2, 0, invert=invert, ir=ir, percent=False)


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
    channel (a metal's base color is then the F0 they give). Translucency (371, 375), volumetric absorption and
    scattering (261, 271, 281), the edge color (161) and maps in the sheen and SSS slots are named issues."""
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
    ir.specular = Input(1.0)  # no reflection level in the pblock: the IOR's own Fresnel
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
    if _num(m, 371, 0, 0.0) > 0 or conv.map_ref(m, 372, 373, None, 0, ir=ir) is not None:
        conv.issue(m.index, "CoronaPhysicalMtl %r: translucency not converted" % (m.name,), ir)
    if t > 0 and _num(m, 281, 0, 0.0) > 0:
        conv.issue(m.index, "CoronaPhysicalMtl %r: volumetric absorption and scattering not converted" % (m.name,),
                   ir)


def corona_legacy_mtl(conv, m, ir):
    """CoronaLegacyMtl (CoronaMtl), block 0: colors 101 diffuse, 102 reflect, 103 refract, 105 opacity, 107
    selfIllum; their levels 121, 122, 123, 127, 128; maps 141 diffuse, 142 reflect, 143 reflectGlossiness,
    144 refract, 146 opacity, 147 bump, 158 selfIllum, each switched on by id + 20, with amounts (fractions) 290,
    291, 292, 293, 295, 296, 303; 180 reflectGlossiness, 182 fresnelIor,
    183 ior, 210 thin; 410 levelSss, 411 sssRadius (world units), 412 sssScatterColor. 402 pbrMode only changes how
    Corona curves the glossiness: 1 - glossiness either way, a named issue when it is off. Translucency (106, 126,
    map 148), absorption (188, 190) and the SSS amount map (414) are named issues."""
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
    _subsurface(conv, m, ir, 410, 411, 412)
    if slot(414, 417, None) is not None:
        conv.issue(m.index, "CoronaLegacyMtl %r: SSS amount map not converted" % (m.name,), ir)
    if not _flag(m, 402, 0, True) and (mean(reflection) > 0 or reflection_map is not None):
        conv.issue(m.index, "CoronaLegacyMtl %r: glossiness of PBR mode off read as in PBR mode" % (m.name,), ir)
    if _num(m, 126, 0, 0.0) > 0 or slot(148, 168, None) is not None:
        conv.issue(m.index, "CoronaLegacyMtl %r: translucency not converted" % (m.name,), ir)
    if t > 0 and _num(m, 188, 0, 0.0) > 0:
        conv.issue(m.index, "CoronaLegacyMtl %r: absorption not converted" % (m.name,), ir)


def corona_light_mtl(conv, m, ir):
    """CoronaLightMtl, block 0: 110 intensity, 111 / 112 texmap (on), 113 color, 150 / 151 opacityTexmap (on)."""
    ir.base_color, ir.roughness, ir.specular = Input((0.0, 0.0, 0.0)), Input(1.0), Input(0.0)
    ir.emission_color = Input(conv.rgb(m, 113, 0, (1.0, 1.0, 1.0)), conv.map_ref(m, 111, 112, None, 0, ir=ir))
    ir.emission_strength = max(0.0, _num(m, 110, 0, 1.0))
    ir.alpha = Input(1.0, conv.map_ref(m, 150, 151, None, 0, ir=ir))


def corona_layered_mtl(conv, m, ir):
    """CoronaLayeredMtl with a base and a layer on (block 0, CORONA_*): the base's IR, named after the layered
    material, with every layer that is on and set as a Layer (its amount, its mask where masksOn, the mask amount);
    at most MAX_LAYERS, and no more than MAX_LAYER_BSDFS Principled BSDFs in all (the rest left out, an issue). A
    base or layer that is a Multi/Sub-Object gives its first entry (an issue). Returns the IR: the textures are the
    base's, the masks' graphs made here."""
    base_index = m.param(CORONA_BASE, 0).index
    base = conv.convert(base_index)
    if base is None:  # not a material (the peel checks only that it is set)
        return conv._grey(m.index, "%s: base is not a material" % (m.name or "CoronaLayeredMtl",))
    out = dataclasses.replace(base, index=ir.index, name=ir.name, source=ir.source, unknown=False,
                              textures=dict(base.textures), issues=list(base.issues), layers=list(base.layers))
    layers = conv.corona_layers(m)
    for sub in [base_index] + [i for _k, i in layers]:
        peeled = conv.peel(sub)[0]
        if peeled is not None and conv.is_class(peeled, classids.SC_MATERIAL, classids.MULTI_SUB_MTL):
            conv.issue(m.index, "%s: Multi/Sub-Object %d mixed as its first entry" % (out.name, sub), out)
    if len(layers) > MAX_LAYERS:
        conv.issue(m.index, "%s: %d layers, only the first %d mixed" % (out.name, len(layers), MAX_LAYERS), out)
    total = 1 + sum(conv.bsdf_count(layer.ir) for layer in out.layers)
    for k, index in layers[:MAX_LAYERS]:
        layer = conv.convert(index)
        if layer is None:
            conv.issue(m.index, "%s: layer %d is not a material" % (out.name, index), out)
            continue
        total += conv.bsdf_count(layer)
        if total > MAX_LAYER_BSDFS:
            conv.issue(m.index, "%s: layers past %d Principled BSDFs not mixed" % (out.name, MAX_LAYER_BSDFS), out)
            break
        amount = max(0.0, _num_tab(m, CORONA_AMOUNTS, k, 1.0))
        mask = None
        if _flag_tab(m, CORONA_MASKS_ON, k, True):
            mask_amount = max(0.0, _num_tab(m, CORONA_MASK_AMOUNTS, k, 1.0))
            mask = conv.to_map(m, m.param(CORONA_MASKS, 0, tab=k), "layer mask %d" % k, mask_amount, ir=out)
        graph = None
        if mask is not None and conv.texmaps is not None:
            graph = conv.texmaps.convert(mask, _texmaps.DATA, 1.0)
            if graph is not None:
                out.issues.extend(r for r in graph.issues if r not in out.issues)
        out.layers.append(Layer(layer, amount, mask, graph))
    return out


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
    alpha = mean(opacityColor 122) x opacityLevel (123), map 143 / 164 / 185; bump 144 / 165 / 186. The second
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
    opacity = _clamp01(mean(conv.rgb(m, 122, 0, (1.0, 1.0, 1.0))) * max(0.0, _num(m, 123, 0, 1.0)))
    ir.alpha = Input(opacity, slot(143))
    conv.bump_slot(ir, slot(144))
    if _num(m, 119, 0, 0.0) > 0:
        conv.issue(m.index, "CoronaSkinMtl %r: second reflection not converted" % (m.name,), ir)
    if any(slot(pid) is not None for pid in range(125, 135)):
        conv.issue(m.index, "CoronaSkinMtl %r: SSS maps not converted" % (m.name,), ir)


# (superclass, ClassId) -> rule(converter, MtlBase, MaterialIR): fills the IR in place, or returns the IR it made
RULES = {
    (classids.SC_MATERIAL, classids.STANDARD_MTL): standard_mtl,
    (classids.SC_MATERIAL, classids.PHYSICAL_MTL): physical_mtl,
    (classids.SC_MATERIAL, classids.VRAY_MTL): vray_mtl,
    (classids.SC_MATERIAL, classids.VRAY_LIGHT_MTL): vray_light_mtl,
    (classids.SC_MATERIAL, classids.VRAY_FAST_SSS2): vray_fast_sss2,
    (classids.SC_MATERIAL, classids.VRAY_CAR_PAINT_MTL): vray_car_paint_mtl,
    (classids.SC_MATERIAL, classids.VRAY_CAR_PAINT_MTL2): vray_car_paint_mtl2,
    (classids.SC_MATERIAL, classids.CORONA_PHYSICAL_MTL): corona_physical_mtl,
    (classids.SC_MATERIAL, classids.CORONA_LEGACY_MTL): corona_legacy_mtl,
    (classids.SC_MATERIAL, classids.CORONA_LIGHT_MTL): corona_light_mtl,
    (classids.SC_MATERIAL, classids.CORONA_LAYERED_MTL): corona_layered_mtl,  # a wrapper without a layer on
    (classids.SC_MATERIAL, classids.CORONA_SKIN_MTL): corona_skin_mtl,
}


class MeshSlots:
    """The material slots of one mesh or curve: users the object indices of the nodes sharing it
    (MeshDescription.users, CurveDescription.users); slots [[MaterialIR or None per user]] per slot (None: an empty
    slot); indices int32 per face, its slot (empty for a curve: every spline is on slot 0)."""
    __slots__ = ("users", "slots", "indices")

    def __init__(self, users, slots, indices):
        self.users, self.slots, self.indices = users, slots, indices

    def __repr__(self):
        return "MeshSlots(%d users, %d slots)" % (len(self.users), len(self.slots))


class Slots(dict):
    """assign()'s result: {mesh key: MeshSlots}, and curves {curve key: MeshSlots} (mesh and curve keys can be
    equal: two dicts)."""
    __slots__ = ("curves",)

    def __init__(self):
        super().__init__()
        self.curves = {}


def node_materials(scene, desc):
    """{node object index: its material's object index, None without one} for the nodes of desc (a reader Scene
    and the SceneDescription made from it)."""
    out = {}
    for node in desc.nodes:
        try:
            out[node.index] = scene.node(node.index).material
        except MaxFileError:
            out[node.index] = None
    return out


def assign(desc, materials, conv):
    """Slots {mesh key: MeshSlots} for the meshes of desc, its curves {curve key: MeshSlots} for the curves of desc.
    materials: {node object index: material object index or None} (node_materials). A mesh's distinct face IDs,
    ascending, are grouped by the materials its users get for them (material_for, by identity): one slot per group
    in order of first appearance. A mesh whose only group has no material gets no slot. A curve's one slot holds
    what its users get for material ID 1 (zero-based 0); a curve none of whose users gets a material is left out."""
    import numpy
    out = Slots()
    for key, cd in desc.curves.items():
        users = list(cd.users)
        irs = [conv.material_for(materials.get(u), 0) for u in users]
        if any(ir is not None for ir in irs):
            out.curves[key] = MeshSlots(users, [irs], numpy.zeros(0, dtype=numpy.int32))
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
