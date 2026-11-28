# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""LightDescription and describe(): the rules of each light family (VRayLight, standard, photometric, sun, IES)."""
import collections
import math

from ...reader import classids
from .. import colors, texmaps
from .ids import (
    _FAMILIES, _PHOTOMETRIC, _STANDARD, AMBIENT, AREA, BEAM, ChunkError, CLASS, CONTRIBUTION, DECAY_NONE, DECAY_SQUARE,
    DIFFUSE_DISTRIBUTION, DIRECT, DIRECTIONAL, DISC, DISK, DOME, DOUBLE_SIDED, EMITTER, ENVIRONMENT_MAP_SLOT, FAR,
    GLOSSY, IES, IES_DARK, IES_FILE, IES_PROFILE, IES_RATED, IES_SHAPE, IES_SHAPES, IES_SPHERE, IES_UNREAD, IES_WATTS,
    IES_ZERO, IMAGE_UNIT, INVERSE, ISOTROPIC, LINE_WIDTH, LUMENS_PER_WATT, LUX_PER_UNIT, MAX_FLOAT, MAX_POWER, MESH,
    MIN_CONE, NEGATIVE, NO_DECAY, NO_FILE, NOT_FINITE, NOT_SKYLIGHT, OUT_OF_RANGE, OVERSHOOT, P_AFFECT_DIFFUSE,
    P_AFFECT_REFLECTIONS, P_AFFECT_SPECULAR, P_COLOR, P_COLOR_MODE, P_DIFFUSE, P_DIRECTIONAL, P_DOUBLE_SIDED,
    P_INVISIBLE, P_MULTIPLIER, P_ON, P_SHADOW, P_SIZE0, P_SIZE1, P_SPECULAR, P_TEMPERATURE, P_TEXMAP, P_TEXMAP_ON,
    P_TYPE, P_UNITS, PHOTOMETRIC, PLANE, POINT, RECTANGLE, RECTANGLE_CONE, REFERENCE_DISTANCE, SHAPE, SHAPE_CYLINDER,
    SHAPE_DISC, SHAPE_LINE, SHAPE_POINT, SHAPE_RECTANGLE, SHAPE_SPHERE, SKYLIGHT, SPHERE, SPOT, SPOT_DISTRIBUTION,
    SPOTLIGHT, STANDARD, SUN, SUN_ANGLE, SUN_COLOR, SUN_IRRADIANCE, SUN_LIGHT, SUN_ZENITH, TEXMAP, TYPE_NAMES,
    UNITS_DEFAULT, UNITS_LM, UNITS_LM_M2_SR, UNITS_W, UNITS_W_M2_SR, UPWARD, VRAY, WEB_FALLOFF, WEB_FILE, WEB_HOTSPOT,
    WEB_PROFILE, ZERO_START,
)


class Profile(collections.namedtuple("Profile", "file photometry rotation")):
    """The IES file a light shines with: file the base name of the file found; photometry its convert.ies.Photometry
    (one per file, shared); rotation a photometric web's X, Y, Z rotation as stored ((0, 0, 0) for a VRayIES; not
    applied yet, its unit and order not measured: maxdrop-o53.3.5). text, peak, nadir, flux and up are the
    photometry's."""
    __slots__ = ()

    text = property(lambda self: self.photometry.text)
    peak = property(lambda self: self.photometry.peak)
    nadir = property(lambda self: self.photometry.nadir)
    flux = property(lambda self: self.photometry.flux)
    up = property(lambda self: self.photometry.up)

    def __repr__(self):  # the text can be megabytes
        return "Profile(%r, peak %g cd, rotation %r)" % (self.file, self.peak, self.rotation)


def _profile(v, rotation=(0.0, 0.0, 0.0)):
    """The Profile of a light's values (read_params: "photometry" and "ies_name" of the file found), None without,
    and None for a file whose ballast-lamp factor is not above 0 (Cycles multiplies the candelas by it, V-Ray does
    not: the light would be dark or negative)."""
    photometry = v.get("photometry")
    if photometry is None or not photometry.ballast_lamp > 0:
        return None
    return Profile(v.get("ies_name"), photometry, rotation)


def _shine(ld, s, line, file, issues):
    """ld shines with its profile (docs/FORMAT.md, "The IES Texture node in Blender, measured"): a point light, since a
    spot cuts the profile at half its size and above its horizon; its power s x IES_WATTS over the file's ballast-lamp
    factor (Cycles applies that factor, V-Ray does not), s the factor on the file's candelas; build/ divides by the
    gain Blender 4.x reads a file with. The issue line, UPWARD appended when the file sends light upward."""
    p = ld.profile
    ld.kind, ld.spot_size, ld.spot_blend = POINT, 0.0, 0.0
    ld.power = s * IES_WATTS / p.photometry.ballast_lamp
    issues.append(line % file + (UPWARD % ("%.3g" % (100.0 * p.up)) if p.up > 0 else ""))


class LightDescription:
    """One light in meters: kind AREA, POINT, SPOT or SUN; shape RECTANGLE or DISK (AREA), size and size_y the area's
    extents (a disk's diameter in size), radius a POINT's or SPOT's; spot_size (radians) and spot_blend a SPOT's cone,
    angle (radians) a SUN's; watts the total flux of the rules (a SUN's irradiance in W/m^2), power what Blender's
    light gets before the Light Strength (half of watts for a double-sided area); color linear RGB; on, invisible (to
    the camera); diffuse_rays and glossy_rays whether diffuse and glossy rays see it (Cycles); diffuse and specular
    Blender's factors (EEVEE); shadow whether it casts shadows; profile the Profile of the IES file it shines with
    (a photometric web or a VRayIES whose file is found and read), else None; users the object indices of the nodes
    that share it, in walk order."""
    __slots__ = ("key", "name", "kind", "shape", "size", "size_y", "radius", "spot_size", "spot_blend", "angle",
                 "watts", "power", "color", "on", "invisible", "diffuse_rays", "glossy_rays", "diffuse", "specular",
                 "shadow", "profile", "users")

    def __init__(self, key, name, kind, shape=None, size=0.0, size_y=0.0, radius=0.0, watts=0.0, power=0.0,
                 color=(1.0, 1.0, 1.0), on=True, invisible=False, diffuse_rays=True, glossy_rays=True, diffuse=1.0,
                 specular=1.0, spot_size=0.0, spot_blend=0.0, angle=0.0, shadow=True, profile=None):
        self.key, self.name, self.kind, self.shape = key, name, kind, shape
        self.size, self.size_y, self.radius = size, size_y, radius
        self.spot_size, self.spot_blend, self.angle = spot_size, spot_blend, angle
        self.watts, self.power, self.color = watts, power, color
        self.on, self.invisible, self.diffuse_rays, self.glossy_rays = on, invisible, diffuse_rays, glossy_rays
        self.diffuse, self.specular, self.shadow, self.profile = diffuse, specular, shadow, profile
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
    light of values, rounded to 9 digits: a plane's or disc's X times Y scale, 1 in lm and W (its flux does not
    follow the area, and Blender scales the area light's size itself); a sphere's X scale squared in every units mode
    (its radius takes the root: describe); 1 when that is no finite positive number."""
    if values.get(CLASS, VRAY) != VRAY:
        return 1.0
    sphere = values[P_TYPE] == SPHERE
    if not sphere and values[P_UNITS] in (UNITS_LM, UNITS_W):
        return 1.0
    lengths = [math.sqrt(sum(c * c for c in world[r][:3])) for r in range(3)]
    f = lengths[0] ** 2 if sphere else lengths[0] * lengths[1]
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


def is_dome(values):
    """Whether the values are a VRayLight dome's: the World, not a light (describe_dome)."""
    return values.get(CLASS, VRAY) == VRAY and values[P_TYPE] == DOME


def is_mesh_light(values):
    """Whether the values are a VRayLight mesh light's: an emitter, not a light (describe_emitter)."""
    return values.get(CLASS, VRAY) == VRAY and values[P_TYPE] == MESH


def not_built(values):
    """Why a light of these values is not built (a type 3ds Max does not have, a Skylight), None when it is (a dome
    too: describe_dome; a mesh light too: convert.scene finds its mesh, or says why it has none, NO_MESH)."""
    family = values.get(CLASS, VRAY)
    if family == SKYLIGHT:
        return NOT_SKYLIGHT
    if family != VRAY:
        return None
    kind = values[P_TYPE]
    if kind not in TYPE_NAMES:
        return "type %d is not a VRayLight type" % kind
    return None


def describe(key, name, values, meters, swatches, scale=1.0):
    """(LightDescription of a light's values, or None, issues): None and the reason when it is not built
    (not_built; a dome: describe_dome; a mesh light: describe_emitter). scale: area_scale of its nodes."""
    reason = EMITTER if is_mesh_light(values) else (
        not_built(values) or ("a dome light is the World, not a light" if is_dome(values) else None))
    if reason is not None:
        return None, [reason]
    family = values.get(CLASS, VRAY)
    if family != VRAY:
        issues = []
        try:
            ld = _DESCRIBE[family](key, name, values, meters, swatches, issues)
        except OverflowError:  # a size or intensity near the float range
            ld = None
        if ld is None or not (abs(ld.watts) <= MAX_POWER and abs(ld.power) <= MAX_POWER):  # also NaN
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
    flux_scale = 1.0 if units in (UNITS_LM, UNITS_W) else scale  # a sphere's scale is in its key in every mode
    try:
        w = watts(units, values[P_MULTIPLIER], area(kind, size0, size1, double, meters, units) * flux_scale)
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
                          diffuse=values[P_DIFFUSE] if diffuse else 0.0, specular=values[P_SPECULAR] if spec else 0.0,
                          shadow=bool(values[P_SHADOW]))
    if kind == PLANE:
        ld.shape, ld.size, ld.size_y = RECTANGLE, 2.0 * size0 * meters, 2.0 * size1 * meters
    elif kind == DISC:
        ld.shape, ld.size = DISK, 2.0 * size0 * meters
        ld.size_y = ld.size
    else:
        ld.radius = size0 * meters * math.sqrt(scale)
        if not ld.radius <= MAX_FLOAT:  # past the float32 range a Blender light's radius holds
            ld.radius = 0.0
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
                          diffuse_rays=v["diffuse"], glossy_rays=v["specular"], shadow=bool(v["shadow"]))
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
                          glossy_rays=bool(v["specular"]), shadow=bool(v["shadow"]))
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
            ld.profile = _profile(v, v.get("rotation", (0.0, 0.0, 0.0)))
            if ld.profile is None:
                issues.append(WEB_FILE % (v["file"] or NO_FILE))
            else:
                # Not measured (maxdrop-o53.3.5 calibrates it): the light's intensity is taken as the file's peak.
                peak = ld.profile.peak
                s = cd / peak if peak > 0 else 0.0
                ld.watts = s * ld.profile.flux / LUMENS_PER_WATT
                _shine(ld, s, WEB_PROFILE, v["file"] or NO_FILE, issues)
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
    # Measured (docs/FORMAT.md, "Power, measured"): the stored power is lumens in both units of the override (V-Ray's
    # panel converts cd with the file) and V-Ray renders that flux; without the override it scales the file's
    # candelas by power / the file's rated lumens, the flux only when those are the file's own. Power 0 is dark. A
    # file V-Ray cannot find renders the power as an isotropic flux, as a file not found here does (measured).
    lm = _nonnegative("power", v["power"], issues)
    file = v["file"] or NO_FILE
    if v["power"] == 0:
        issues.append(IES_ZERO)
    elif lm > 0 and not v["override"]:  # a negative power is 0 W, said by _nonnegative
        photometry = v.get("photometry")
        if photometry is not None:
            lm *= photometry.scale  # past the float range: describe() makes it 0 W, OUT_OF_RANGE
            if lm == 0:
                issues.append(IES_DARK % file)
        elif v.get("photometry_issue"):
            issues.append(IES_UNREAD % (file, v["photometry_issue"]))
        else:
            issues.append(IES_RATED)
    color = colors.GAMMA_OFF.color(texmaps.kelvin_rgb(v["temperature"])) if v["color_mode"] == 1 else \
        swatches.color(v["color"])
    ld = LightDescription(key, name, SPOT, watts=lm / LUMENS_PER_WATT, power=lm / LUMENS_PER_WATT, color=color,
                          on=bool(v["on"]), spot_size=WEB_CONE, spot_blend=WEB_BLEND, shadow=bool(v["shadow"]),
                          profile=_profile(v))
    _rays(ld, bool(v["diffuse"]), bool(v["specular"]), v["diffuse_contribution"], v["specular_contribution"], issues)
    if ld.profile is None:
        issues.append(IES_FILE % file)
    else:  # lm is the flux V-Ray renders: the file's candelas times lm / its flux
        flux = ld.profile.flux
        _shine(ld, lm / flux if flux > 0 else 0.0, IES_PROFILE, file, issues)
    ld.radius = _ies_radius(v, meters, issues)
    return ld


def _ies_radius(v, meters, issues):
    """A VRayIES's radius in meters: with its light shape used and overridden, half the largest size the shape uses
    (a sphere's diameter exact, another shape an issue); else 0 (without the override V-Ray takes the IES file's
    shape, which is not read)."""
    if not v["use_shape"] or not v["override_shape"]:
        return 0.0
    name, sizes = IES_SHAPES.get(v["shape_type"], ("", ()))
    across = max((abs(v[k]) for k in sizes), default=0.0) * meters
    if not across <= MAX_FLOAT:  # past the float32 range a Blender light's radius holds (also inf, NaN)
        across = 0.0
    if across > 0 and v["shape_type"] != IES_SPHERE:
        issues.append(IES_SHAPE % (name, across))
    return across / 2.0


_DESCRIBE = {STANDARD: _describe_standard, PHOTOMETRIC: _describe_photometric, SUN: _describe_sun,
             IES: _describe_ies}
