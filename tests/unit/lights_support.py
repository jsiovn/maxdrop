# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the tests of maxdrop/convert/lights/ share: the fixtures' paths, the package loaded without Blender,
the expected powers and values()."""
import importlib
import importlib.util
import math
import os
import sys
import types


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "vray_lights.max")
DOME_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "vray_dome.max")
MESH_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "vray_mesh_light.max")
EXTRUDE_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "extrude.max")

# A package named apart from the add-on whose path is maxdrop/: relative imports resolve, maxdrop/__init__.py (which
# imports bpy) never runs.
_PKG = "maxdrop_lights_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
lights = importlib.import_module(_PKG + ".convert.lights")
colors = importlib.import_module(_PKG + ".convert.colors")
texmaps = importlib.import_module(_PKG + ".convert.texmaps")
pblock = importlib.import_module(_PKG + ".reader.pblock")
classids = importlib.import_module(_PKG + ".reader.classids")
_spec_patching = importlib.util.spec_from_file_location("maxdrop_test_patching",
                                                        os.path.join(ROOT, "tests", "patching.py"))
patching = importlib.util.module_from_spec(_spec_patching)
_spec_patching.loader.exec_module(patching)  # patch_all(): a split package's modules read their own names
try:
    import numpy  # noqa: F401  convert.scene needs it for meshes
    conv = importlib.import_module(_PKG + ".convert.scene")
except ImportError:
    conv = None

L = lights
MM = 0.001
# 3ds Max 2020, the fixture loaded, the rules source's ocbaby_exsVrayLightWatts per light (toM 0.001)
MAX_WATTS = {"FixturePlane": 0.0527086444, "FixturePlaneInst": 0.0527086444, "FixturePlaneLm": 2.19619322,
             "FixtureDisc": 0.00975400303, "FixtureSphere": 40.0, "FixtureSphereKelvin": 0.252661914,
             "FixtureOff": 0.00439238735, "FixtureInvisible": 20.0, "FixtureTargeted": 25.0,
             "FixtureDiscScaled": 0.00975400303,  # the rules source ignores the node's scale
             "FixtureNoShadow": 15.0}  # by hand, not run in 3ds Max: in W the rules give the multiplier
# what MaxDrop changes: the disc in lm/m2/sr (V-Ray's (2 r)^2), the scaled one's area (2 x 1.5, measured)
FACTORS = {"FixtureDisc": 4.0 / math.pi, "FixtureDiscScaled": 4.0 / math.pi * 3.0}
MAX_KELVIN_3500 = (255.0, 192.534, 140.827)  # ocbaby_exsKelvinRGB 3500 in 3ds Max


def values(**changes):
    """A VRayLight's parameter values: V-Ray's defaults, then changes by parameter name (P_* without P_)."""
    v = dict(L.DEFAULTS)
    v[L.P_TEXMAP] = None
    for key, value in changes.items():
        v[getattr(L, "P_" + key.upper())] = value
    return v
