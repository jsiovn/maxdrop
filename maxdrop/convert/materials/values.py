# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Value helpers of the rules: means, clamps, IOR and roughness conversions."""
import math

from ...reader import classids, units
from ...reader import scene as reader_scene
from ...reader.classdir import ClassId
from ..params import finite as _finite
from .ids import CORONA_LEGACY_GLOSS, DEFAULT_METERS, MAX_COMPLEX_IOR


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


def corona_legacy_roughness(gloss):
    """The roughness of a CoronaLegacyMtl glossiness with PBR mode off: CORONA_LEGACY_GLOSS, linear between its
    points; a glossiness outside 0..1 clamped, one that is not a number taken as 1 (the parameter's default)."""
    g = _clamp01(gloss) if _finite(gloss) else 1.0
    step = len(CORONA_LEGACY_GLOSS) - 1
    i = min(int(g * step), step - 1)
    t = g * step - i
    return CORONA_LEGACY_GLOSS[i] * (1.0 - t) + CORONA_LEGACY_GLOSS[i + 1] * t


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
