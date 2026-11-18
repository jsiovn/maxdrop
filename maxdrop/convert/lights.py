# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""VRayLights as Blender lights: shape, size in meters, linear color and power in watts.

    is_vray_light(scene, i)             # object i is a VRayLight
    values, issues = read_params(scene, i)   # {parameter id: value}, LightError without a block
    not_built(values)                   # why a mesh or dome light is not built, None for the others
    scale = area_scale(values, world)   # what a node's scale does to the area, rounded (part of the key)
    ld, issues = describe(key, name, values, meters, swatches, scale)   # LightDescription, or None and the reason
    watts(units, multiplier, area(kind, size0, size1, double_sided, meters))

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

The file comes from anywhere: a parameter that is animated, missing or no finite number takes its default (the
animated one an issue); a block that cannot be read raises LightError; a power past the float32 range (sizes near
the float range) is 0 W, an issue. No bpy.
"""
import math

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

AREA, POINT = "AREA", "POINT"
RECTANGLE, DISK = "RECTANGLE", "DISK"

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
DOUBLE_SIDED = "double-sided: Blender's area light shines on one side, with half the power"
TEXMAP = "its texture is not imported: the light has its color"
DIRECTIONAL = "directional %g is not imported: it shines over the whole hemisphere"
GLOSSY = ("affect specular %s, affect reflections %s: Cycles has one switch for both and keeps the light in glossy "
          "rays; EEVEE's specular factor follows affect specular")
NOT_FINITE = "the power is out of range (sizes %g, %g): 0 W"
MAX_POWER = 3.4028234663852886e38  # the largest float32: what a Blender light holds
CONTRIBUTION = "%s contribution %g: Blender's %s factor, which only EEVEE uses"


class LightDescription:
    """One light in meters: kind AREA or POINT; shape RECTANGLE or DISK (AREA), size and size_y the area's extents
    (a disk's diameter in size), radius a POINT's; watts the total flux of the rules, power what Blender's light gets
    before the Light Strength (half of watts for a double-sided area); color linear RGB; on, invisible (to the
    camera); diffuse_rays and glossy_rays whether diffuse and glossy rays see it (Cycles); diffuse and specular
    Blender's factors (EEVEE); users the object indices of the nodes that share it, in walk order."""
    __slots__ = ("key", "name", "kind", "shape", "size", "size_y", "radius", "watts", "power", "color", "on",
                 "invisible", "diffuse_rays", "glossy_rays", "diffuse", "specular", "users")

    def __init__(self, key, name, kind, shape=None, size=0.0, size_y=0.0, radius=0.0, watts=0.0, power=0.0,
                 color=(1.0, 1.0, 1.0), on=True, invisible=False, diffuse_rays=True, glossy_rays=True, diffuse=1.0,
                 specular=1.0):
        self.key, self.name, self.kind, self.shape = key, name, kind, shape
        self.size, self.size_y, self.radius = size, size_y, radius
        self.watts, self.power, self.color = watts, power, color
        self.on, self.invisible, self.diffuse_rays, self.glossy_rays = on, invisible, diffuse_rays, glossy_rays
        self.diffuse, self.specular = diffuse, specular
        self.users = []

    def __repr__(self):
        return "LightDescription(%r, %s%s, %g W)" % (self.name, self.kind, " " + self.shape if self.shape else "",
                                                     self.power)


def is_vray_light(scene, i):
    entry = scene.entry(i)
    return entry is not None and entry.superclass == classids.SC_LIGHT and entry.class_id == classids.VRAY_LIGHT


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
    if values[P_UNITS] in (UNITS_LM, UNITS_W):
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


def _value(block, pid, issues):
    default = DEFAULTS[pid]
    v = block.get(pid)
    if isinstance(v, pblock.Animated):
        issues.append("%s is animated: %r is used" % (_NAMES[pid], default))
        return default
    if isinstance(default, tuple):
        ok = isinstance(v, tuple) and len(v) >= 3 and all(finite(c) for c in v[:3])
        return tuple(float(c) for c in v[:3]) if ok else default
    if not finite(v):
        return default
    return int(v) if isinstance(default, int) else float(v)


def read_params(scene, i):
    """({parameter id: value} of VRayLight object i, every id of DEFAULTS, issues); LightError without its block."""
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


def not_built(values):
    """Why a VRayLight of these parameter values is not built (a mesh or dome light, a type 3ds Max does not have),
    None when it is."""
    kind = values[P_TYPE]
    if kind not in TYPE_NAMES:
        return "type %d is not a VRayLight type" % kind
    return NOT_YET.get(kind)


def describe(key, name, values, meters, swatches, scale=1.0):
    """(LightDescription of a VRayLight's parameter values, or None, issues): None and the reason when it is not
    built (not_built). scale: area_scale of its nodes."""
    reason = not_built(values)
    if reason is not None:
        return None, [reason]
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


def describe_light(scene, i, name, meters, swatches, scale=1.0):
    """(LightDescription of VRayLight object i keyed (i, scale), or None, issues); LightError when its block is
    missing or damaged."""
    values, issues = read_params(scene, i)
    ld, more = describe((i, scale), name, values, meters, swatches, scale)
    return ld, issues + more
