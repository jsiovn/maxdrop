# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""3ds Max lights as Blender lights: shape, size in meters, linear color and power in watts.

    light_class(scene, i)               # VRAY, STANDARD, PHOTOMETRIC, SUN, IES or SKYLIGHT; None: not one read here
    values, issues = read_params(scene, i, assets)   # the light's values, LightError without its block
    not_built(values)                   # why a mesh or dome light or a Skylight is not built, None for the others
    scale = area_scale(values, world)   # what a node's scale does to the area, rounded (part of the key)
    ld, issues = describe(key, name, values, meters, swatches, scale)   # LightDescription, or None and the reason
    watts(units, multiplier, area(kind, size0, size1, double_sided, meters))
    environment_sky(scene)              # the object index of a VRaySky that is the environment map, else None

A VRayLight's values are {parameter id: value}; every other family's {name: value}, with CLASS naming the family
(light_class).

VRayLight:

A VRayLight keeps one ParamBlock2 in reference slot 0 (docs/FORMAT.md, "VRayLight"): 0 on, 1 type (0 plane, 1 dome,
2 sphere, 3 mesh, 4 disc), 2 / 3 size0 / size1 (a plane's half length along local X and half width along local Y;
a disc's or sphere's radius), 7 color, 8 multiplier, 9 double-sided, 10 invisible, 12 units (0 default, 1 lm,
2 lm/m2/sr, 3 W, 4 W/m2/sr), 18 / 19 texmap (on), 25 / 26 / 30 affect diffuse / specular / reflections, 36
directional, 38 color temperature, 39 color mode (1: temperature), 53 / 54 diffuse / specular contribution.

The rules are the ones of the 3ds Max -> FBX exporter (f_export_scene.ms, ocbaby_exsVrayLightWatts and
ocbaby_exsKelvinRGB): the power is the total radiant flux in watts. Radiance units are integrated over the emitting
area (plane 2 size0 x 2 size1, disc pi size0^2, sphere 4 pi size0^2, in m^2; a double-sided plane or disc twice
that), photometric units at 683 lm/W, and one default (image) unit is 1500 / pi cd/m^2. One change, measured
against V-Ray 5.2 renders (docs/FORMAT.md, "VRayLight"): in lm/m2/sr and W/m2/sr a disc emits as if its area were
(2 size0)^2, 4 / pi times its own; in the default units it does not. A node's scale grows the area in V-Ray (in
the default units, lm/m2/sr and W/m2/sr, where the flux follows the area; not in lm and W): a plane or disc by its X
times its Y scale, a sphere by the square of its largest scale (measured with a scale of 2, 1.5, 1: 3 and 4).
Blender's area light grows with the object's scale but keeps its power, so the power takes that factor, and the
nodes of one VRayLight share one LightDescription per factor (area_scale). Blender's area light shines
on one side only: a double-sided plane or disc gets half the flux, the side it faces (an issue). Cycles has no
per-light diffuse or specular factor: affect diffuse off hides the light from diffuse rays, affect specular and
affect reflections both off from glossy rays (one switch for both: an issue when only one is off); a contribution
other than 1 sets the light's diffuse or specular factor, which only EEVEE uses (an issue). The color is the
scene's swatch rule (convert.colors) of the color, or in temperature mode kelvin_rgb (convert.texmaps) decoded from
sRGB, as CoronaColor's temperature; V-Ray's own temperature color, which it also stores, is not used.

Plane -> AREA RECTANGLE, disc -> AREA DISK, sphere -> POINT with the radius: a V-Ray plane shines along its local
-Z, as a Blender area light does, so the node transform stays. Mesh and dome lights are not built (the reason; "dome
light -> World" is later work). The FBX route's spot mirrors and light de-instancing are dropped: the nodes of one
VRayLight with the same area_scale share one LightDescription. build/ multiplies the power by the import's Light
Strength.

The other lights (docs/FORMAT.md, "Standard and photometric lights"): V-Ray 5.2 lights a white floor at distance d
from a light of intensity I cd with a pixel of I / d^2 / 1500 (lx / 1500), whatever the light's class, and Blender
(Cycles) with P / (4 pi^2 d^2) from a point or spot light of P watts, P / (pi^2 d^2) on the axis of a small area
light, S / pi from a sun of strength S; the Light Strength 1.43 is pi 683 / 1500. So the power here is the flux in
watts at 683 lm/W: 4 pi I / 683 for a point or spot light of on-axis intensity I, pi I / 683 for a uniform diffuse
(Lambertian) one, and a sun of illuminance E lx gets E / 683 W/m^2.

- Standard (Omni, Free / Target Spot, Free / Target Direct; an old ParamBlock by index and chunks of the light):
  V-Ray lights the floor at distance d with m x 1500 lx (m the multiplier) without decay, m (d0 / d)^2 x 1500 lx with
  inverse-square decay from d0, m d0 / d x 1500 lx with inverse decay: the intensity is 1500 m d0^2 cd, d0 the decay
  start (exact past it with inverse-square decay; at it with inverse decay, an issue), REFERENCE_DISTANCE without
  decay (an issue: Blender's light falls off). Omni -> POINT, Spot -> SPOT (_cone: size the falloff, the blend
  that puts Blender's full-intensity edge on the hotspot; Blender blends in cosine space, (cos theta - cos(size / 2))
  / ((1 - cos(size / 2)) blend)), Direct -> SUN of 1500 m lx (its beam, the falloff's cylinder, is not: an issue,
  but with overshoot). Radius and angle 0: they are point sources with hard shadows. Decay from a start of 0 gives
  0 W (an issue).
- Photometric (Free / Target Light in its six shapes, one class each; ParamBlock2s 0, 2, 3, 4): the intensity is
  always cd, times the dimmer. Isotropic -> POINT, spotlight -> SPOT (block 2's cone), web -> SPOT of WEB_CONE
  (the rules source's wide spot, falloff 170 and hotspot 100 degrees; the web file named in an issue), uniform
  diffuse -> AREA (a rectangle or disc as it is; a line a rectangle LINE_WIDTH wide, a point a disc LINE_WIDTH
  across, a sphere or cylinder a disc of its diameter). A point or spot light gets the radius of a disc, sphere or
  cylinder. The color is white, or in Kelvin mode kelvin_rgb decoded from sRGB, times the filter color.
- VRaySun -> SUN of SUN_IRRADIANCE W/m^2 per unit of its multiplier (the rules source's 100 klx / 683; V-Ray 5.2
  measured 102.7 klx at the zenith), angle SUN_ANGLE x its size multiplier, its filter color; the sky model's
  dimming and color are not imported (issues).
- VRayIES: its power in lm (with the intensity overridden in cd, the power is that intensity: x 4 pi) -> SPOT of
  WEB_CONE, power lm / 683, its color or temperature, the IES file named in an issue; a power of 0 (V-Ray then takes
  the file's own) is 0 W, an issue.
- Skylight: not built (the reason; World is later work). environment_sky finds a VRaySky as the environment map
  (RenderEnvironment reference ENVIRONMENT_MAP_SLOT) for convert.scene's report line.

Every light shines along its local -Z, as Blender's spot, area and sun lights do: the node transform stays. Off ->
hidden; affect diffuse / specular and V-Ray's contributions as for the VRayLight; ambient only, far attenuation:
issues. A negative multiplier or intensity is 0 W (an issue). Their instances share one description (area_scale is 1
but for VRayLights).

The file comes from anywhere: a parameter that is animated, missing or no finite number takes its default (the
animated one an issue; for a standard light a missing one too); a block that cannot be read raises LightError (a
photometric light's, VRaySun's or VRayIES's other blocks are skipped, an issue, their parameters take defaults);
a power past the float32 range (sizes near the float range) is 0 W, an issue; environment_sky skips a
RenderEnvironment whose references cannot be read. No bpy.
"""
import math

from .. import pathnames
from ..reader import chunks, classids, pblock
from . import colors, texmaps
from .params import finite

ChunkError = chunks.ChunkError


class LightError(ChunkError):
    pass


SLOT_BLOCK = 0
PLANE, DOME, SPHERE, MESH, DISC = 0, 1, 2, 3, 4
TYPE_NAMES = {PLANE: "plane", DOME: "dome", SPHERE: "sphere", MESH: "mesh", DISC: "disc"}
UNITS_DEFAULT, UNITS_LM, UNITS_LM_M2_SR, UNITS_W, UNITS_W_M2_SR = 0, 1, 2, 3, 4
LUMENS_PER_WATT = 683.0
IMAGE_UNIT = 1500.0  # one default (image) unit is IMAGE_UNIT / pi cd/m^2

AREA, POINT, SPOT, SUN_LIGHT = "AREA", "POINT", "SPOT", "SUN"
RECTANGLE, DISK = "RECTANGLE", "DISK"

CLASS = "class"  # the family in a values dict (a VRayLight's has none: VRAY)
VRAY, STANDARD, PHOTOMETRIC, SUN, IES, SKYLIGHT = "VRayLight", "standard", "photometric", "VRaySun", "VRayIES", \
    "Skylight"
OMNI, SPOTLIGHT, DIRECT = "omni", "spot", "direct"
SHAPE_POINT, SHAPE_LINE, SHAPE_RECTANGLE, SHAPE_DISC, SHAPE_SPHERE, SHAPE_CYLINDER = \
    "point", "line", "rectangle", "disc", "sphere", "cylinder"
_FAMILIES = {classids.VRAY_LIGHT: VRAY, classids.VRAY_SUN: SUN, classids.VRAY_IES: IES, classids.SKYLIGHT: SKYLIGHT}
_STANDARD = {classids.OMNI: OMNI, classids.TARGET_SPOT: SPOTLIGHT, classids.FREE_SPOT: SPOTLIGHT,
             classids.FREE_DIRECT: DIRECT, classids.TARGET_DIRECT: DIRECT}
_PHOTOMETRIC = {classids.FREE_POINT_LIGHT: SHAPE_POINT, classids.TARGET_POINT_LIGHT: SHAPE_POINT,
                classids.FREE_LINE_LIGHT: SHAPE_LINE, classids.TARGET_LINE_LIGHT: SHAPE_LINE,
                classids.FREE_RECTANGLE_LIGHT: SHAPE_RECTANGLE, classids.TARGET_RECTANGLE_LIGHT: SHAPE_RECTANGLE,
                classids.FREE_DISC_LIGHT: SHAPE_DISC, classids.TARGET_DISC_LIGHT: SHAPE_DISC,
                classids.FREE_SPHERE_LIGHT: SHAPE_SPHERE, classids.TARGET_SPHERE_LIGHT: SHAPE_SPHERE,
                classids.FREE_CYLINDER_LIGHT: SHAPE_CYLINDER, classids.TARGET_CYLINDER_LIGHT: SHAPE_CYLINDER}

# Measured in V-Ray 5.2: a white floor's pixel is its illuminance in lx / LUX_PER_UNIT, and a standard light of
# multiplier m gives it m.
LUX_PER_UNIT = 1500.0
REFERENCE_DISTANCE = 1.0  # m: where a standard light without decay is as bright as in V-Ray
SUN_IRRADIANCE = 146.4  # W/m^2 per unit of a VRaySun's multiplier (the rules source's 100 klx / 683)
SUN_ANGLE = math.radians(0.53)  # the sun's angular diameter at size multiplier 1
WEB_FALLOFF, WEB_HOTSPOT = 170.0, 100.0  # degrees: the rules source's wide spot for a web or IES
LINE_WIDTH = 0.01  # m: the width of the area light of a diffuse line, the diameter of a diffuse point
MIN_CONE = math.radians(1.0)  # Blender's smallest spot size
ENVIRONMENT_MAP_SLOT = 5  # RenderEnvironment's reference to the environment map

# standard lights: chunks of the light object, old ParamBlock indices
_ON, _DECAY, _CONE, _OVERSHOOT, _NO_DIFFUSE, _NO_SPECULAR, _AMBIENT = \
    0x2580, 0x25D0, 0x2573, 0x2575, 0x25B0, 0x25B1, 0x2600
DECAY_NONE, DECAY_INVERSE, DECAY_SQUARE = 0, 1, 2
_OLD_COLOR, _OLD_MULTIPLIER, _OLD_HOTSPOT, _OLD_FALLOFF = 0, 1, 4, 5
_OLD_START = {OMNI: 8, SPOTLIGHT: 11, DIRECT: 11}  # decay start
_OLD_NAMES = {_OLD_COLOR: "color", _OLD_MULTIPLIER: "multiplier", _OLD_HOTSPOT: "hotspot", _OLD_FALLOFF: "falloff",
              8: "decay start", 11: "decay start"}
_OLD_DEFAULTS = {_OLD_COLOR: (1.0, 1.0, 1.0), _OLD_MULTIPLIER: 1.0, _OLD_HOTSPOT: 43.0, _OLD_FALLOFF: 45.0,
                 8: 40.0, 11: 40.0}

ISOTROPIC, SPOT_DISTRIBUTION, DIFFUSE_DISTRIBUTION, WEB = 0, 1, 2, 3
# name: (block id, parameter id, default of 3ds Max 2020's new light)
_PHOTOMETRIC_PARAMS = {"distribution": (0, 1, ISOTROPIC), "on": (0, 2, 1), "filter": (0, 5, (1.0, 1.0, 1.0)),
                       "intensity": (0, 6, 1500.0), "kelvin": (0, 8, 3600.0), "use_kelvin": (0, 10, 0),
                       "use_dimmer": (0, 18, 0), "dimmer": (0, 19, 100.0), "far": (0, 21, 0),
                       "hotspot": (2, 0, 30.0), "falloff": (2, 1, 60.0), "diffuse": (4, 4, 1), "specular": (4, 5, 1),
                       "ambient": (4, 6, 0), "length": (4, 11, 1220.0), "width": (4, 12, 610.0),
                       "radius": (4, 13, 130.0)}
_PHOTOMETRIC_FILE = (3, 0)
_SUN_PARAMS = {"on": (0, 0, 1), "multiplier": (0, 2, 1.0), "size": (0, 3, 1.0), "invisible": (0, 9, 0),
               "diffuse": (0, 14, 1), "diffuse_contribution": (0, 19, 1.0), "specular": (0, 15, 1),
               "specular_contribution": (0, 20, 1.0), "filter": (0, 17, (1.0, 1.0, 1.0)), "color_mode": (0, 18, 0)}
_IES_PARAMS = {"on": (0, 0, 1), "temperature": (0, 7, 6500.0), "color": (0, 8, (1.0, 1.0, 1.0)),
               "color_mode": (0, 9, 0), "power": (0, 10, 1500.0), "diffuse": (0, 14, 1),
               "diffuse_contribution": (0, 30, 1.0), "specular": (0, 15, 1), "specular_contribution": (0, 31, 1.0),
               "intensity_type": (0, 32, 0), "override": (0, 34, 0)}
_IES_FILE = (0, 1)

P_ON, P_TYPE, P_SIZE0, P_SIZE1, P_COLOR, P_MULTIPLIER = 0, 1, 2, 3, 7, 8
P_DOUBLE_SIDED, P_INVISIBLE, P_UNITS, P_TEXMAP, P_TEXMAP_ON = 9, 10, 12, 18, 19
P_AFFECT_DIFFUSE, P_AFFECT_SPECULAR, P_AFFECT_REFLECTIONS, P_DIRECTIONAL = 25, 26, 30, 36
P_TEMPERATURE, P_COLOR_MODE, P_DIFFUSE, P_SPECULAR = 38, 39, 53, 54

# V-Ray 5.2's values of a new VRayLight (sizes in world units)
DEFAULTS = {P_ON: 1, P_TYPE: PLANE, P_SIZE0: 10.0, P_SIZE1: 10.0, P_COLOR: (1.0, 1.0, 1.0), P_MULTIPLIER: 30.0,
            P_DOUBLE_SIDED: 0, P_INVISIBLE: 0, P_UNITS: UNITS_DEFAULT, P_TEXMAP_ON: 1, P_AFFECT_DIFFUSE: 1,
            P_AFFECT_SPECULAR: 1, P_AFFECT_REFLECTIONS: 1, P_DIRECTIONAL: 0.0, P_TEMPERATURE: 6500.0,
            P_COLOR_MODE: 0, P_DIFFUSE: 1.0, P_SPECULAR: 1.0}
_NAMES = {P_ON: "on", P_TYPE: "type", P_SIZE0: "size0", P_SIZE1: "size1", P_COLOR: "color",
          P_MULTIPLIER: "multiplier", P_DOUBLE_SIDED: "doubleSided", P_INVISIBLE: "invisible",
          P_UNITS: "normalizeColor", P_TEXMAP_ON: "texmap_on", P_AFFECT_DIFFUSE: "affect_diffuse",
          P_AFFECT_SPECULAR: "affect_specular", P_AFFECT_REFLECTIONS: "affect_reflections",
          P_DIRECTIONAL: "lightDistribution", P_TEMPERATURE: "color_temperature", P_COLOR_MODE: "color_mode",
          P_DIFFUSE: "diffuse_contribution", P_SPECULAR: "specular_contribution"}

NOT_YET = {MESH: "a mesh light is not imported yet",
           DOME: "a dome light is not imported yet (dome -> World is later work)"}
NOT_SKYLIGHT = "a Skylight is not imported yet (Skylight -> World is later work)"
SKY = "the environment map is a VRaySky: not imported yet (environment -> World is later work)"
NO_DECAY = "no decay: Blender's light falls off with the square of the distance; as bright as in 3ds Max at %g m"
INVERSE = "inverse decay: Blender's light falls off with the square of the distance; as bright as in 3ds Max at %g m"
ZERO_START = "decay start 0: its power grows with the square of the decay start, so 0 W"
BEAM = "its beam (%g m across) is not imported: the sun lights the whole scene"
RECTANGLE_CONE = "its rectangular cone is drawn round"
OVERSHOOT = "overshoot is not imported: the spot lights its cone only"
AMBIENT = "ambient only is not imported: it lights as any light"
FAR = "far attenuation is not imported"
NEGATIVE = "%s %g is negative: 0 W"
SHAPE = "its %s shape is %s"
WEB_FILE = "its photometric web %s is approximated by a spot of 170 degrees"
IES_FILE = "its IES file %s is approximated by a spot of 170 degrees"
IES_ZERO = "power 0: V-Ray takes the IES file's own intensity, which is not read: 0 W"
NO_FILE = "(no file)"
SUN_ZENITH = "its strength is the sun's at the zenith: the sky model's dimming toward the horizon is not imported"
SUN_COLOR = "its color is its filter color: the sky model's sun color is not imported"
MISSING = "%s is animated or not stored: %r is used"
DOUBLE_SIDED = "double-sided: Blender's area light shines on one side, with half the power"
TEXMAP = "its texture is not imported: the light has its color"
DIRECTIONAL = "directional %g is not imported: it shines over the whole hemisphere"
GLOSSY = ("affect specular %s, affect reflections %s: Cycles has one switch for both and keeps the light in glossy "
          "rays; EEVEE's specular factor follows affect specular")
NOT_FINITE = "the power is out of range (sizes %g, %g): 0 W"
OUT_OF_RANGE = "the power is out of range: 0 W"
MAX_POWER = 3.4028234663852886e38  # the largest float32: what a Blender light holds
CONTRIBUTION = "%s contribution %g: Blender's %s factor, which only EEVEE uses"


class LightDescription:
    """One light in meters: kind AREA, POINT, SPOT or SUN; shape RECTANGLE or DISK (AREA), size and size_y the area's
    extents (a disk's diameter in size), radius a POINT's or SPOT's; spot_size (radians) and spot_blend a SPOT's cone,
    angle (radians) a SUN's; watts the total flux of the rules (a SUN's irradiance in W/m^2), power what Blender's
    light gets before the Light Strength (half of watts for a double-sided area); color linear RGB; on, invisible (to
    the camera); diffuse_rays and glossy_rays whether diffuse and glossy rays see it (Cycles); diffuse and specular
    Blender's factors (EEVEE); users the object indices of the nodes that share it, in walk order."""
    __slots__ = ("key", "name", "kind", "shape", "size", "size_y", "radius", "spot_size", "spot_blend", "angle",
                 "watts", "power", "color", "on", "invisible", "diffuse_rays", "glossy_rays", "diffuse", "specular",
                 "users")

    def __init__(self, key, name, kind, shape=None, size=0.0, size_y=0.0, radius=0.0, watts=0.0, power=0.0,
                 color=(1.0, 1.0, 1.0), on=True, invisible=False, diffuse_rays=True, glossy_rays=True, diffuse=1.0,
                 specular=1.0, spot_size=0.0, spot_blend=0.0, angle=0.0):
        self.key, self.name, self.kind, self.shape = key, name, kind, shape
        self.size, self.size_y, self.radius = size, size_y, radius
        self.spot_size, self.spot_blend, self.angle = spot_size, spot_blend, angle
        self.watts, self.power, self.color = watts, power, color
        self.on, self.invisible, self.diffuse_rays, self.glossy_rays = on, invisible, diffuse_rays, glossy_rays
        self.diffuse, self.specular = diffuse, specular
        self.users = []

    def __repr__(self):
        return "LightDescription(%r, %s%s, %g W)" % (self.name, self.kind, " " + self.shape if self.shape else "",
                                                     self.power)


def light_class(scene, i):
    """The family of light object i (VRAY, STANDARD, PHOTOMETRIC, SUN, IES, SKYLIGHT), None for any other object."""
    entry = scene.entry(i)
    if entry is None or entry.superclass != classids.SC_LIGHT:
        return None
    cid = entry.class_id
    if cid in _STANDARD:
        return STANDARD
    if cid in _PHOTOMETRIC:
        return PHOTOMETRIC
    return _FAMILIES.get(cid)


def environment_sky(scene):
    """The object index of the VRaySky that is the scene's environment map, None when there is none."""
    holders = {e.index for e in scene.classes
               if e.superclass == classids.SC_RENDER_ENVIRONMENT and e.class_id == classids.RENDER_ENVIRONMENT}
    if not holders:
        return None
    for i in range(len(scene)):
        if scene.class_index(i) in holders:
            try:
                sky = scene.refs(i).get(ENVIRONMENT_MAP_SLOT)
            except ChunkError:
                continue
            if sky is not None and 0 <= sky < len(scene) and scene.is_a(sky, classids.SC_TEXMAP, classids.VRAY_SKY):
                return sky
    return None


def area(kind, size0, size1, double_sided, meters, units=UNITS_DEFAULT):
    """The emitting area in m^2 of a light of type kind (1 for a mesh or dome light), doubled for a double-sided
    plane or disc; a disc's is (2 size0)^2 in the radiance units lm/m2/sr and W/m2/sr, as V-Ray integrates it."""
    s0, s1 = size0 * meters, size1 * meters
    if kind == PLANE:
        a = (2.0 * s0) * (2.0 * s1)
    elif kind == DISC:
        a = (2.0 * s0) ** 2 if units in (UNITS_LM_M2_SR, UNITS_W_M2_SR) else math.pi * s0 ** 2
    elif kind == SPHERE:
        a = 4.0 * math.pi * s0 ** 2
    else:
        return 1.0
    return a * 2.0 if double_sided and kind in (PLANE, DISC) else a


def area_scale(values, world):
    """The factor a node's world matrix (reader rows: the local axes in world space) puts on the emitting area of the
    light of values, rounded to 9 digits: 1 in lm and W; a plane's or disc's X times Y scale; a sphere's largest
    scale squared; 1 when that is no finite positive number."""
    if values.get(CLASS, VRAY) != VRAY or values[P_UNITS] in (UNITS_LM, UNITS_W):
        return 1.0
    lengths = [math.sqrt(sum(c * c for c in world[r][:3])) for r in range(3)]
    f = max(lengths) ** 2 if values[P_TYPE] == SPHERE else lengths[0] * lengths[1]
    return float("%.9g" % f) if math.isfinite(f) and f > 0 else 1.0


def watts(units, multiplier, a):
    """The total radiant flux in watts of a light of the units mode, multiplier and emitting area a (m^2)."""
    if units == UNITS_LM:
        return multiplier / LUMENS_PER_WATT
    if units == UNITS_LM_M2_SR:
        return math.pi * multiplier * a / LUMENS_PER_WATT
    if units == UNITS_W:
        return multiplier
    if units == UNITS_W_M2_SR:
        return math.pi * multiplier * a
    return multiplier * a * IMAGE_UNIT / LUMENS_PER_WATT


def light_color(values, swatches):
    """Linear RGB: kelvin_rgb of the temperature decoded from sRGB in temperature mode, else the color swatch."""
    if values[P_COLOR_MODE] == 1:
        return colors.GAMMA_OFF.color(texmaps.kelvin_rgb(values[P_TEMPERATURE]))
    return swatches.color(values[P_COLOR])


def _value(block, pid, issues, default=None, name=None):
    if name is None:
        default, name = DEFAULTS[pid], _NAMES[pid]
    v = block.get(pid)
    if isinstance(v, pblock.Animated):
        issues.append("%s is animated: %r is used" % (name, default))
        return default
    if isinstance(default, tuple):
        ok = isinstance(v, tuple) and len(v) >= 3 and all(finite(c) for c in v[:3])
        return tuple(float(c) for c in v[:3]) if ok else default
    if not finite(v):
        return default
    return int(v) if isinstance(default, int) else float(v)


def read_params(scene, i, assets=None):
    """(values of light object i, issues); LightError without its block. A VRayLight's are {parameter id: value} of
    every id of DEFAULTS, the others' {name: value} with CLASS; assets (reader.assets.AssetTable) names the file of
    a web or IES light."""
    family = light_class(scene, i)
    if family == STANDARD:
        return _read_standard(scene, i)
    if family == SKYLIGHT:
        return {CLASS: SKYLIGHT}, []
    if family in (PHOTOMETRIC, SUN, IES):
        return _read_blocks(scene, i, family, assets)
    entry = scene.entry(i)
    refs = scene.refs(i)
    target = refs.get(SLOT_BLOCK)
    te = scene.entry(target) if target is not None and 0 <= target < len(scene) else None
    if te is None or te.superclass != classids.SC_PARAMETER_BLOCK2:
        raise LightError("no parameter block (reference slot 0)")
    block = pblock.ParamBlock2.from_chunk(scene.chunk(target), scene.refs(target), refs, len(scene),
                                          (entry.superclass, entry.class_id))
    issues = list(block.issues)
    values = {pid: _value(block, pid, issues) for pid in DEFAULTS}
    texmap = block.get(P_TEXMAP)
    values[P_TEXMAP] = texmap.index if isinstance(texmap, pblock.Reference) else None
    return values, issues


def _blocks(scene, i):
    """({block id: ParamBlock2} of the ParamBlock2s light object i references (the first of each id), issues): a
    block that cannot be read is skipped, an issue (its id is unknown: a needed one then counts as missing)."""
    entry = scene.entry(i)
    refs = scene.refs(i)
    found, issues = {}, []
    for slot in sorted(refs):
        target = refs[slot]
        te = scene.entry(target) if target is not None and 0 <= target < len(scene) else None
        if te is None or te.superclass != classids.SC_PARAMETER_BLOCK2:
            continue
        try:
            block = pblock.ParamBlock2.from_chunk(scene.chunk(target), scene.refs(target), refs, len(scene),
                                                  (entry.superclass, entry.class_id))
        except ChunkError as exc:
            issues.append("the parameter block of reference %d cannot be read: %s" % (slot, exc))
            continue
        found.setdefault(block.block_id, block)
    return found, issues


def _file_name(blocks, where, assets):
    """The base name of the asset at (block id, parameter id), None when there is none or the table lacks it."""
    block = blocks.get(where[0])
    entry = assets.entry(block.get(where[1])) if block is not None and assets is not None else None
    if entry is None:
        return None
    return pathnames.base_name(entry.path) or pathnames.base_name(entry.resolved) or None


def _read_blocks(scene, i, family, assets):
    """The values of a photometric light, VRaySun or VRayIES: its parameters by name, its file's name."""
    spec, where = {PHOTOMETRIC: (_PHOTOMETRIC_PARAMS, _PHOTOMETRIC_FILE), SUN: (_SUN_PARAMS, None),
                   IES: (_IES_PARAMS, _IES_FILE)}[family]
    blocks, issues = _blocks(scene, i)
    if 0 not in blocks:
        raise LightError("no parameter block 0" + ("".join("; " + x for x in issues)))
    issues += [x for b in blocks.values() for x in b.issues]
    values = {CLASS: family}
    for name, (bid, pid, default) in spec.items():
        block = blocks.get(bid)
        values[name] = default if block is None else _value(block, pid, issues, default, name)
    for bid in sorted({bid for bid, _pid, _default in spec.values()} - set(blocks)):
        issues.append("parameter block %d is missing: its defaults are used" % bid)
    if family == PHOTOMETRIC:
        values["shape"] = _PHOTOMETRIC[scene.entry(i).class_id]
    values["file"] = _file_name(blocks, where, assets) if where else None
    return values, issues


def _u16(chunk, cid, default):
    c = chunk.first(cid) if chunk.container else None
    if c is None or c.container or c.payload_size < 2:
        return default
    return c.unpack("<H")[0]


def _read_standard(scene, i):
    """The values of a standard light: its old ParamBlock (reference 0) and the chunks of the light object."""
    entry = scene.entry(i)
    target = scene.refs(i).get(SLOT_BLOCK)
    if target is None or not 0 <= target < len(scene) or not scene.is_a(target, classids.SC_PARAMETER_BLOCK,
                                                                         classids.PARAM_BLOCK):
        raise LightError("no parameter block (reference slot 0)")
    block = pblock.ParamBlock.from_chunk(scene.chunk(target))
    issues = list(block.issues)
    kind = _STANDARD[entry.class_id]

    def old(index):
        default = _OLD_DEFAULTS[index]
        v = block.get(index)
        if isinstance(default, tuple):
            ok = isinstance(v, tuple) and len(v) >= 3 and all(finite(c) for c in v[:3])
            v = tuple(float(c) for c in v[:3]) if ok else None
        elif finite(v):
            v = float(v)
        else:
            v = None
        if v is None:
            issues.append(MISSING % (_OLD_NAMES[index], default))
            return default
        return v

    chunk = scene.chunk(i)

    def present(cid):
        return chunk.container and chunk.first(cid) is not None

    values = {CLASS: STANDARD, "shape": kind, "on": _u16(chunk, _ON, 1), "decay": _u16(chunk, _DECAY, DECAY_NONE),
              "color": old(_OLD_COLOR), "multiplier": old(_OLD_MULTIPLIER), "start": 0.0,
              "rectangle": kind != OMNI and _u16(chunk, _CONE, 1) == 0, "overshoot": present(_OVERSHOOT),
              "diffuse": not present(_NO_DIFFUSE), "specular": not present(_NO_SPECULAR),
              "ambient": present(_AMBIENT)}
    if kind != DIRECT and values["decay"] != DECAY_NONE:  # unused otherwise: no issue when it is missing
        values["start"] = old(_OLD_START[kind])
    if kind != OMNI:
        values["hotspot"], values["falloff"] = old(_OLD_HOTSPOT), old(_OLD_FALLOFF)
    return values, issues


def not_built(values):
    """Why a light of these values is not built (a mesh or dome light, a type 3ds Max does not have, a Skylight),
    None when it is."""
    family = values.get(CLASS, VRAY)
    if family == SKYLIGHT:
        return NOT_SKYLIGHT
    if family != VRAY:
        return None
    kind = values[P_TYPE]
    if kind not in TYPE_NAMES:
        return "type %d is not a VRayLight type" % kind
    return NOT_YET.get(kind)


def describe(key, name, values, meters, swatches, scale=1.0):
    """(LightDescription of a light's values, or None, issues): None and the reason when it is not built
    (not_built). scale: area_scale of its nodes."""
    reason = not_built(values)
    if reason is not None:
        return None, [reason]
    family = values.get(CLASS, VRAY)
    if family != VRAY:
        issues = []
        try:
            ld = _DESCRIBE[family](key, name, values, meters, swatches, issues)
        except OverflowError:  # a size or intensity near the float range
            ld = None
        if ld is None or not abs(ld.watts) <= MAX_POWER:  # also NaN
            if ld is None:
                ld = LightDescription(key, name, POINT)
            issues.append(OUT_OF_RANGE)
            ld.watts = ld.power = 0.0
        return ld, issues
    kind = values[P_TYPE]
    issues = []
    size0, size1 = abs(values[P_SIZE0]), abs(values[P_SIZE1])
    double = bool(values[P_DOUBLE_SIDED]) and kind in (PLANE, DISC)
    units = values[P_UNITS]
    try:
        w = watts(units, values[P_MULTIPLIER], area(kind, size0, size1, double, meters, units) * scale)
    except OverflowError:
        w = math.inf
    if not abs(w) <= MAX_POWER:  # also NaN
        issues.append(NOT_FINITE % (size0, size1))
        w = 0.0
    if double:
        issues.append(DOUBLE_SIDED)
    if values[P_TEXMAP] is not None and values[P_TEXMAP_ON]:
        issues.append(TEXMAP)
    if values[P_DIRECTIONAL] > 0:
        issues.append(DIRECTIONAL % values[P_DIRECTIONAL])
    diffuse, spec, refl = (bool(values[p]) for p in (P_AFFECT_DIFFUSE, P_AFFECT_SPECULAR, P_AFFECT_REFLECTIONS))
    if spec != refl:
        issues.append(GLOSSY % ("on" if spec else "off", "on" if refl else "off"))
    for on, pid, label in ((diffuse, P_DIFFUSE, "diffuse"), (spec, P_SPECULAR, "specular")):
        if on and values[pid] != 1.0:
            issues.append(CONTRIBUTION % (label, values[pid], label))
    ld = LightDescription(key, name, POINT if kind == SPHERE else AREA, watts=w, power=w / 2.0 if double else w,
                          color=light_color(values, swatches), on=bool(values[P_ON]),
                          invisible=bool(values[P_INVISIBLE]), diffuse_rays=diffuse, glossy_rays=spec or refl,
                          diffuse=values[P_DIFFUSE] if diffuse else 0.0, specular=values[P_SPECULAR] if spec else 0.0)
    if kind == PLANE:
        ld.shape, ld.size, ld.size_y = RECTANGLE, 2.0 * size0 * meters, 2.0 * size1 * meters
    elif kind == DISC:
        ld.shape, ld.size = DISK, 2.0 * size0 * meters
        ld.size_y = ld.size
    else:
        ld.radius = size0 * meters
    return ld, issues


def _rays(ld, diffuse, specular, diffuse_contribution, specular_contribution, issues):
    """Affect diffuse / specular and V-Ray's contributions on ld, as for the VRayLight (one glossy switch)."""
    ld.diffuse_rays, ld.glossy_rays = diffuse, specular
    ld.diffuse = diffuse_contribution if diffuse else 0.0
    ld.specular = specular_contribution if specular else 0.0
    for on, value, label in ((diffuse, diffuse_contribution, "diffuse"), (specular, specular_contribution,
                                                                           "specular")):
        if on and value != 1.0:
            issues.append(CONTRIBUTION % (label, value, label))


def _nonnegative(label, value, issues):
    if value < 0:
        issues.append(NEGATIVE % (label, value))
        return 0.0
    return value


def _cone(falloff, hotspot):
    """(spot_size, spot_blend) of a cone of falloff and hotspot in degrees (full angles): Blender's full intensity
    ends at the hotspot, as 3ds Max's does (Blender blends between cos(size / 2) and that plus (1 - cos(size / 2))
    blend)."""
    size = min(math.pi, max(MIN_CONE, math.radians(falloff)))
    edge = math.cos(size / 2.0)
    hot = math.cos(math.radians(min(max(hotspot, 0.0), math.degrees(size))) / 2.0)
    return size, min(1.0, max(0.0, (hot - edge) / (1.0 - edge)))


WEB_CONE, WEB_BLEND = _cone(WEB_FALLOFF, WEB_HOTSPOT)


def point_watts(cd):
    """The power of a point or spot light of on-axis intensity cd: its isotropic flux at 683 lm/W."""
    return 4.0 * math.pi * cd / LUMENS_PER_WATT


def _describe_standard(key, name, v, meters, swatches, issues):
    kind = v["shape"]
    m = _nonnegative("multiplier", v["multiplier"], issues)
    ld = LightDescription(key, name, POINT, color=swatches.color(v["color"]), on=bool(v["on"]),
                          diffuse_rays=v["diffuse"], glossy_rays=v["specular"])
    ld.diffuse, ld.specular = float(v["diffuse"]), float(v["specular"])
    if v["ambient"]:
        issues.append(AMBIENT)
    if kind == DIRECT:
        ld.kind = SUN_LIGHT
        ld.watts = ld.power = LUX_PER_UNIT * m / LUMENS_PER_WATT
        if not v["overshoot"]:
            issues.append(BEAM % (2.0 * abs(v["falloff"]) * meters))
        return ld
    if v["decay"] == DECAY_NONE:
        d = REFERENCE_DISTANCE
        issues.append(NO_DECAY % d)
    else:
        d = abs(v["start"]) * meters
        if d == 0.0:
            issues.append(ZERO_START)
        elif v["decay"] != DECAY_SQUARE:
            issues.append(INVERSE % d)
    ld.watts = ld.power = point_watts(LUX_PER_UNIT * m * d * d)
    if kind == SPOTLIGHT:
        ld.kind = SPOT
        ld.spot_size, ld.spot_blend = _cone(v["falloff"], v["hotspot"])
        if v["rectangle"]:
            issues.append(RECTANGLE_CONE)
        if v["overshoot"]:
            issues.append(OVERSHOOT)
    return ld


def _describe_photometric(key, name, v, meters, swatches, issues):
    cd = v["intensity"] * (v["dimmer"] / 100.0 if v["use_dimmer"] else 1.0)
    cd = _nonnegative("intensity", cd, issues)
    white = colors.GAMMA_OFF.color(texmaps.kelvin_rgb(v["kelvin"])) if v["use_kelvin"] else (1.0, 1.0, 1.0)
    color = tuple(a * b for a, b in zip(white, swatches.color(v["filter"])))
    ld = LightDescription(key, name, POINT, color=color, on=bool(v["on"]), diffuse_rays=bool(v["diffuse"]),
                          glossy_rays=bool(v["specular"]))
    ld.diffuse, ld.specular = float(bool(v["diffuse"])), float(bool(v["specular"]))
    shape, dist = v["shape"], v["distribution"]
    length, width, radius = (abs(v[k]) * meters for k in ("length", "width", "radius"))
    if dist == DIFFUSE_DISTRIBUTION:
        ld.kind = AREA
        ld.watts = ld.power = math.pi * cd / LUMENS_PER_WATT
        if shape == SHAPE_RECTANGLE:
            ld.shape, ld.size, ld.size_y = RECTANGLE, width, length
        elif shape == SHAPE_LINE:
            ld.shape, ld.size, ld.size_y = RECTANGLE, LINE_WIDTH, length
            issues.append(SHAPE % ("line", "a rectangle %g m wide" % LINE_WIDTH))
        else:
            ld.shape = DISK
            ld.size = ld.size_y = LINE_WIDTH if shape == SHAPE_POINT else 2.0 * radius
            if shape in (SHAPE_SPHERE, SHAPE_CYLINDER):
                issues.append(SHAPE % (shape, "a disc of its diameter"))
    else:
        ld.watts = ld.power = point_watts(cd)
        if shape in (SHAPE_DISC, SHAPE_SPHERE, SHAPE_CYLINDER):
            ld.radius = radius
            if shape != SHAPE_SPHERE:
                issues.append(SHAPE % (shape, "a sphere of its radius"))
        elif shape != SHAPE_POINT:
            issues.append(SHAPE % (shape, "not imported: a point"))
        if dist == SPOT_DISTRIBUTION:
            ld.kind = SPOT
            ld.spot_size, ld.spot_blend = _cone(v["falloff"], v["hotspot"])
        elif dist != ISOTROPIC:
            ld.kind = SPOT
            ld.spot_size, ld.spot_blend = WEB_CONE, WEB_BLEND
            issues.append(WEB_FILE % (v["file"] or NO_FILE))
    if v["far"]:
        issues.append(FAR)
    if v["ambient"]:
        issues.append(AMBIENT)
    return ld


def _describe_sun(key, name, v, meters, swatches, issues):
    m = _nonnegative("multiplier", v["multiplier"], issues)
    ld = LightDescription(key, name, SUN_LIGHT, watts=SUN_IRRADIANCE * m, power=SUN_IRRADIANCE * m,
                          color=swatches.color(v["filter"]), on=bool(v["on"]), invisible=bool(v["invisible"]),
                          angle=min(math.pi, SUN_ANGLE * abs(v["size"])))
    _rays(ld, bool(v["diffuse"]), bool(v["specular"]), v["diffuse_contribution"], v["specular_contribution"], issues)
    issues.append(SUN_ZENITH)
    if v["color_mode"] == 0:
        issues.append(SUN_COLOR)
    return ld


def _describe_ies(key, name, v, meters, swatches, issues):
    # power holds the override's value in its own unit (the stored intensity_value is a stale alias)
    lm = v["power"] * (4.0 * math.pi if v["override"] and v["intensity_type"] == 1 else 1.0)
    lm = _nonnegative("power", lm, issues)
    if v["power"] == 0:
        issues.append(IES_ZERO)
    color = colors.GAMMA_OFF.color(texmaps.kelvin_rgb(v["temperature"])) if v["color_mode"] == 1 else \
        swatches.color(v["color"])
    ld = LightDescription(key, name, SPOT, watts=lm / LUMENS_PER_WATT, power=lm / LUMENS_PER_WATT, color=color,
                          on=bool(v["on"]), spot_size=WEB_CONE, spot_blend=WEB_BLEND)
    _rays(ld, bool(v["diffuse"]), bool(v["specular"]), v["diffuse_contribution"], v["specular_contribution"], issues)
    issues.append(IES_FILE % (v["file"] or NO_FILE))
    return ld


_DESCRIBE = {STANDARD: _describe_standard, PHOTOMETRIC: _describe_photometric, SUN: _describe_sun,
             IES: _describe_ies}
