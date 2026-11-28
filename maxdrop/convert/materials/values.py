# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Value helpers of the rules: means, clamps, IOR and roughness conversions."""
import math
import unicodedata

from ...reader import classids
from ...reader.classdir import ClassId
from ..params import finite as _finite
from ..texmaps.converter import _scene_meters as _scene_meters  # the texture maps' rule: one for both
from .ids import CORONA_LEGACY_GLOSS, MAX_COMPLEX_IOR


def mean(rgb):
    """The mean of the channels: the rules' measure of how strong a reflection or refraction color is."""
    return sum(rgb[:3]) / 3.0


MAX_CLASS_NAME = 64  # characters of a class-directory name the report shows: the name comes from the file
_HIDDEN = frozenset(("Cc", "Cf", "Cs", "Zl", "Zp"))  # control, format, surrogate, line and paragraph separators


def class_label(text):
    """A class-directory name as the report shows it: each hidden character a blank, the blanks collapsed and
    stripped, cut to MAX_CLASS_NAME characters ("..." at the end); "" for a name of nothing else."""
    text = " ".join("".join(" " if unicodedata.category(c) in _HIDDEN else c for c in text).split())
    return text if len(text) <= MAX_CLASS_NAME else text[:MAX_CLASS_NAME - 3] + "..."


def class_name(superclass, class_id, directory=""):
    """The class name for the report: classids' for a known class (without the blanks around it: CoronaPhysicalMtl's
    starts with a carriage return), else directory (the name the file's class directory gives the class, through
    class_label), else the ClassID."""
    cid = ClassId(*class_id)
    known = classids.name_of(superclass, cid)
    return known.strip() if known else class_label(directory) or "ClassID%s" % (cid,)


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


def f0_from_complex_ior(n, k):
    """The Fresnel reflectance at normal incidence of a conductor of complex IOR n + ik:
    ((n - 1)^2 + k^2) / ((n + 1)^2 + k^2)."""
    n, k = (min(MAX_COMPLEX_IOR, max(0.0, v)) for v in (n, k))
    return ((n - 1.0) ** 2 + k * k) / ((n + 1.0) ** 2 + k * k)
