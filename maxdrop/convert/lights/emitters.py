# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Emitters: a VRayLight's mesh source and a self-illuminated material's light (describe_emitter())."""
import math

from .ids import (
    DIRECTIONAL, EMITTER_CONTRIBUTION, EMITTER_FLAT, EMITTER_GLOSSY, EMITTER_SHADOW, EMITTER_TEXMAP, MAX_POWER,
    NEGATIVE, OUT_OF_RANGE, P_AFFECT_DIFFUSE, P_AFFECT_REFLECTIONS, P_AFFECT_SPECULAR, P_DIFFUSE, P_DIRECTIONAL,
    P_DOUBLE_SIDED, P_INVISIBLE, P_MESH_FLIP, P_MULTIPLIER, P_ON, P_SHADOW, P_SPECULAR, P_TEXMAP, P_TEXMAP_ON, P_UNITS,
    SPREAD_UNITS, UNITS_DEFAULT, UNITS_LM, UNITS_W,
)
from .families import light_color, watts


class EmitterDescription:
    """A mesh light as an emissive mesh: key and name (its first node's); color linear RGB; radiance in W/m^2/sr (the
    Emission strength before the Light Strength); area the mesh's object-space area in m^2; double_sided: both sides
    emit, else the side its faces' normals point to (flip: the other one); on; camera: the camera sees it; occluder:
    it shadows other lights (V-Ray: when visible); diffuse_rays and glossy_rays as a light's; users the object
    indices of its nodes, in walk order; units and multiplier the light's (spread)."""
    __slots__ = ("key", "name", "color", "radiance", "area", "double_sided", "flip", "on", "camera", "occluder",
                 "diffuse_rays", "glossy_rays", "users", "units", "multiplier")

    def __init__(self, key, name, color=(1.0, 1.0, 1.0), radiance=0.0, area=0.0, double_sided=False, flip=False,
                 on=True, camera=True, occluder=True, diffuse_rays=True, glossy_rays=True, units=UNITS_DEFAULT,
                 multiplier=1.0):
        self.key, self.name, self.color, self.radiance, self.area = key, name, color, radiance, area
        self.double_sided, self.flip, self.on, self.camera, self.occluder = double_sided, flip, on, camera, occluder
        self.diffuse_rays, self.glossy_rays = diffuse_rays, glossy_rays
        self.units, self.multiplier = units, multiplier
        self.users = []

    def __repr__(self):
        return "EmitterDescription(%r, %g W/m2/sr)" % (self.name, self.radiance)


def emitter_radiance(units, multiplier, a, double_sided=False):
    """The radiance in W/m^2/sr of a mesh light of the units mode and multiplier whose mesh has the object-space area
    a (m^2): V-Ray 5.2 gives a mesh light the radiance of its flux (watts) spread over that area, both sides of it
    when double-sided, a Lambertian emitter (flux = pi L a); in the radiance units (default, lm/m2/sr, W/m2/sr) the
    multiplier alone. Raises ZeroDivisionError for an area of 0 in lm and W."""
    if units in (UNITS_LM, UNITS_W):
        return watts(units, multiplier, a) / (math.pi * a * (2.0 if double_sided else 1.0))
    return watts(units, multiplier, 1.0) / math.pi


def _emitter_strength(units, multiplier, a, double_sided):
    """(the radiance of emitter_radiance, issues): 0 for an area of 0 in lm and W, out of range or negative."""
    issues = []
    try:
        radiance = emitter_radiance(units, multiplier, a, double_sided)
    except ZeroDivisionError:
        issues.append(EMITTER_FLAT % ("lumens" if units == UNITS_LM else "watts"))
        radiance = 0.0
    except OverflowError:
        radiance = math.inf
    if not abs(radiance) <= MAX_POWER:  # also NaN
        issues.append(OUT_OF_RANGE)
        radiance = 0.0
    if radiance < 0:
        issues.append(NEGATIVE % ("multiplier", multiplier))
        radiance = 0.0
    return radiance, issues


def spread(ed, a):
    """(gone, added): EmitterDescription ed's area made a (m^2: its mesh's evaluated area) and its radiance that of its
    units mode and multiplier over a (only SPREAD_UNITS change it); gone the issues of its radiance over the area it
    had (describe_emitter's) that no longer hold, added those that hold now and did not."""
    if ed.units not in SPREAD_UNITS:
        ed.area = a
        return [], []
    _radiance, before = _emitter_strength(ed.units, ed.multiplier, ed.area, ed.double_sided)
    ed.radiance, after = _emitter_strength(ed.units, ed.multiplier, a, ed.double_sided)
    ed.area = a
    return [x for x in before if x not in after], [x for x in after if x not in before]


def describe_emitter(key, name, values, swatches, a):
    """(EmitterDescription of a mesh light's values whose mesh has the object-space area a in m^2, issues)."""
    units = values[P_UNITS]
    double = bool(values[P_DOUBLE_SIDED])
    radiance, issues = _emitter_strength(units, values[P_MULTIPLIER], a, double)
    if values[P_TEXMAP] is not None and values[P_TEXMAP_ON]:
        issues.append(EMITTER_TEXMAP)
    if values[P_DIRECTIONAL] > 0:
        issues.append(DIRECTIONAL % values[P_DIRECTIONAL])
    if not values[P_SHADOW]:
        issues.append(EMITTER_SHADOW)
    diffuse, spec, refl = (bool(values[p]) for p in (P_AFFECT_DIFFUSE, P_AFFECT_SPECULAR, P_AFFECT_REFLECTIONS))
    if spec != refl:
        issues.append(EMITTER_GLOSSY % ("on" if spec else "off", "on" if refl else "off"))
    for on, pid, label in ((diffuse, P_DIFFUSE, "diffuse"), (spec, P_SPECULAR, "specular")):
        if on and values[pid] != 1.0:
            issues.append(EMITTER_CONTRIBUTION % (label, values[pid]))
    visible = not values[P_INVISIBLE]
    ed = EmitterDescription(key, name, light_color(values, swatches), radiance, a, double, bool(values[P_MESH_FLIP]),
                            bool(values[P_ON]), visible, visible, diffuse, spec or refl, units, values[P_MULTIPLIER])
    return ed, issues
