# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the tests of maxdrop/convert/scene/ share: numpy when present, the fixtures, the tolerances, the
package loaded without Blender, patch_all and the oracle helpers."""
import glob
import importlib
import importlib.util
import json
import os
import sys
import types


try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
MATRIX_TOLERANCE = 1e-4  # file units, per element (the oracle prints 6 significant digits)
BBOX_TOLERANCE = 1e-3

# A package named apart from the add-on whose path is maxdrop/: convert's relative imports of ..reader resolve,
# and maxdrop/__init__.py (which imports bpy) never runs.
_PKG = "maxdrop_convert_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
conv = importlib.import_module(_PKG + ".convert.scene")
geometry = importlib.import_module(_PKG + ".reader.geometry")
cfb = importlib.import_module(_PKG + ".reader.cfb")
reader_scene = importlib.import_module(_PKG + ".reader.scene")
shapes = importlib.import_module(_PKG + ".reader.shapes")
_spec_patching = importlib.util.spec_from_file_location("maxdrop_test_patching",
                                                        os.path.join(ROOT, "tests", "patching.py"))
patching = importlib.util.module_from_spec(_spec_patching)
_spec_patching.loader.exec_module(patching)  # patch_all(): a split package's modules read their own names


def _shading(node):
    """The ("shading", ...) a converted smoother adds to a node's mesh key, else None."""
    last = node.mesh[-1] if node.mesh else None
    return last if isinstance(last, tuple) and len(last) == 2 and last[0] == "shading" else None


def _oracle(path):
    with open(path[:-4] + ".oracle.json", encoding="utf-8") as f:
        return json.load(f)


def _name(path):
    return os.path.splitext(os.path.basename(path))[0]


def _world_points(node, md):
    m = numpy.asarray(node.world, dtype=numpy.float64)
    return numpy.asarray(md.positions, dtype=numpy.float64) @ m[:3, :3].T + m[:3, 3]


def _quad_strip(groups):
    """Two quads sharing the edge (1, 4): 0-1-4-3 and 1-2-5-4."""
    return ([0, 1, 4, 3, 1, 2, 5, 4], [0, 4], [4, 4], groups)
