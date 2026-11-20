# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The performance budget of the reader and the conversion of a mesh, without Blender: a synthetic Editable Poly
object (tests/synthetic_poly.py) through reader.geometry.read_editable_poly and convert.scene.mesh_description.

    python -I -m unittest discover tests

No limit is a number of seconds: the machine running the tests is unknown. Each time is the best of a few runs,
divided by the best time of a reference workload of the same kind in the same process (plain Python record walking
for the reader, numpy array work for the conversion); the ratio must stay below a limit about twice what it is on
the Pythons and numpys of Blender 4.2, 4.5 and 5.2, so that code three times as slow fails. Memory is the peak of
the Python allocations (tracemalloc, numpy's included) as a multiple of the object's size, which does not depend on
the machine. docs/BASELINE.md says where the limits come from; a change that moves a ratio past its limit is a
regression to fix, not a limit to raise.
"""
import importlib
import importlib.util
import os
import sys
import tracemalloc
import types
import unittest

try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PKG = "maxdrop_convert_test"  # the package the convert tests make: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
chunks = importlib.import_module(_PKG + ".reader.chunks")
geometry = importlib.import_module(_PKG + ".reader.geometry")
conv = importlib.import_module(_PKG + ".convert.scene")

FACES = 300_000
RUNS = 5
# measured 2026-11-19 (Windows, 300 360 faces): read 2.3 (Python 3.11 with numpy 1.24 and 1.26, 3.13 with 2.3) to
# 3.0 (3.9); describe 3.9 to 4.6; memory 5.07 on all of them (one more int64 array per loop alive at the peak makes
# it 5.46). The same ratios at a million faces: tests/blender/bench.py
READ_LIMIT = 6.0
DESCRIBE_LIMIT = 5.0
MEMORY_LIMIT = 5.3


def _synthetic():
    spec = importlib.util.spec_from_file_location("synthetic_poly", os.path.join(ROOT, "tests", "synthetic_poly.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(data):
    return geometry.read_editable_poly(chunks.index(data)[0])


def describe(md):
    return conv.mesh_description(0, "synthetic", md, None, 1.0)


@unittest.skipIf(numpy is None, "numpy missing")
class Synthetic(unittest.TestCase):
    """The generator writes what the reader reads."""

    def test_small_object(self):
        sp = _synthetic()
        data = sp.poly_object(200)
        self.assertEqual(data, sp.poly_object(200))
        md = read(data)
        positions, deg, lv, smoothing, materials = sp.faces_of(200)
        self.assertEqual(len(md.loop_starts), len(deg))
        self.assertEqual(md.loop_totals.tolist(), deg.tolist())
        self.assertEqual(md.loop_vertices.tolist(), lv.tolist())
        self.assertEqual(md.smoothing_groups.tolist(), smoothing.tolist())
        self.assertEqual(md.material_ids.tolist(), materials.tolist())
        self.assertEqual(len(md.positions), len(positions))
        self.assertEqual(list(md.maps), [1])
        self.assertEqual(md.maps[1].indices.tolist(), lv.tolist())
        self.assertEqual({3, 4}, set(deg.tolist()))
        self.assertEqual(len(deg), 202)  # 100 quads, 100 triangles, face 0 doubled and made degenerate
        d = describe(md)
        self.assertEqual(d.dropped_faces, 2)
        self.assertGreater(len(d.sharp_edges), 0)
        self.assertTrue(d.sharp_faces.any() and not d.sharp_faces.all())


@unittest.skipIf(numpy is None, "numpy missing")
class Budget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sp = _synthetic()
        cls.data = cls.sp.poly_object(FACES)
        cls.md = read(cls.data)

    def ratio(self, what, workload, reference, limit):
        work, ref = self.sp.timed(workload, reference, RUNS)
        ratio = work / ref
        print("%s: %.3f s / reference %.3f s = %.2f (limit %.1f)" % (what, work, ref, ratio, limit))
        self.assertLess(ratio, limit, "%s takes %.2f times its reference (%.3f s / %.3f s), the limit is %.1f"
                        % (what, ratio, work, ref, limit))

    def test_read_time(self):
        faces = len(self.md.loop_starts)
        self.ratio("read %d faces" % faces, lambda: read(self.data), lambda: self.sp.reference_loop(faces),
                   READ_LIMIT)

    def test_describe_time(self):
        faces = len(self.md.loop_starts)
        work, ref = self.sp.timed(lambda: describe(self.md), self.sp.numpy_reference(self.md.loop_vertices), RUNS,
                                  3 * RUNS)
        print("diagnostic: describe %d faces / numpy_reference = %.2f (%.3f s / %.3f s)" % (faces, work / ref, work,
                                                                                         ref))
        self.ratio("describe %d faces" % faces, lambda: describe(self.md),
                   self.sp.describe_reference(self.md.loop_vertices), DESCRIBE_LIMIT)

    def test_memory(self):
        tracemalloc.start()
        try:
            described = describe(read(self.data))
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        multiple = peak / len(self.data)
        print("read + describe: peak %.1f MB for %.1f MB = %.2f (limit %.1f)" % (
            peak / 1e6, len(self.data) / 1e6, multiple, MEMORY_LIMIT))
        self.assertEqual(len(described.loop_starts), len(self.md.loop_starts) - described.dropped_faces)
        self.assertLess(multiple, MEMORY_LIMIT, "read + describe allocate %.2f times the object's size at their "
                        "peak, the limit is %.1f" % (multiple, MEMORY_LIMIT))


if __name__ == "__main__":
    unittest.main()
