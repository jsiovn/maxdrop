# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/colors.py, the swatch rule: no Blender. The curve, each setting, and the rule read from
the committed fixtures (every one saved with the gamma off but gamma_swatches).

    python -I -m unittest discover tests
"""
import glob
import importlib
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
TOLERANCE = 1e-6

_PKG = "maxdrop_convert_test"  # a package named apart from the add-on: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
colors = importlib.import_module(_PKG + ".convert.colors")
gamma = importlib.import_module(_PKG + ".reader.gamma")
cfb = importlib.import_module(_PKG + ".reader.cfb")
reader_scene = importlib.import_module(_PKG + ".reader.scene")
reader_materials = importlib.import_module(_PKG + ".reader.materials")


class Rule(unittest.TestCase):
    def close(self, ours, theirs):
        for a, b in zip(ours, theirs):
            self.assertAlmostEqual(a, b, delta=TOLERANCE)

    def test_srgb_to_linear(self):
        self.assertEqual(colors.srgb_to_linear(0.0), 0.0)
        self.assertAlmostEqual(colors.srgb_to_linear(1.0), 1.0, delta=TOLERANCE)
        self.assertAlmostEqual(colors.srgb_to_linear(0.5), 0.214041, delta=TOLERANCE)
        self.assertAlmostEqual(colors.srgb_to_linear(0.04), 0.04 / 12.92, delta=TOLERANCE)  # the linear segment

    def test_grey_128_by_setting(self):
        g = (128 / 255,) * 3
        self.close(colors.GAMMA_ON.color(g), (0.501961,) * 3)
        self.close(colors.GAMMA_OFF.color(g), (0.215861,) * 3)
        self.close(colors.UNKNOWN.color(g), (0.501961,) * 3)

    def test_clamped_first(self):
        self.close(colors.GAMMA_ON.color((-1.0, 2.0, 0.5, 9.0)), (0.0, 1.0, 0.5))
        self.close(colors.GAMMA_OFF.color((-1.0, 2.0, 0.5)), (0.0, 1.0, 0.214041))

    def test_for_gamma(self):
        self.assertIs(colors.for_gamma(gamma.SceneGamma(True, 2.2, 2.2)), colors.GAMMA_ON)
        self.assertIs(colors.for_gamma(gamma.SceneGamma(False, 2.2, 2.2)), colors.GAMMA_OFF)
        self.assertIs(colors.for_gamma(gamma.SceneGamma(True, None, None)), colors.GAMMA_ON)
        self.assertIs(colors.for_gamma(None), colors.UNKNOWN)

    def test_note_and_lines(self):
        self.assertEqual((colors.GAMMA_ON.note, colors.GAMMA_OFF.note), ("", ""))
        self.assertEqual(colors.UNKNOWN.note, colors.GAMMA_NOTE)
        self.assertIn("linear", colors.GAMMA_ON.line())
        self.assertIn("sRGB", colors.GAMMA_OFF.line())
        self.assertIn("not found", colors.UNKNOWN.line())

    def test_graph_without_a_reader_scene(self):
        self.assertIs(colors.of_graph(object()), colors.UNKNOWN)
        self.assertIs(colors.of_graph(types.SimpleNamespace(scene="not a scene")), colors.UNKNOWN)


@unittest.skipUnless(glob.glob(os.path.join(FIXTURE_DIR, "*.max")), "no fixtures")
class Fixtures(unittest.TestCase):
    def test_every_fixture(self):
        for path in sorted(glob.glob(os.path.join(FIXTURE_DIR, "*.max"))):
            name = os.path.basename(path)[:-4]
            want = colors.GAMMA_ON if name == "gamma_swatches" else colors.GAMMA_OFF
            with self.subTest(name), cfb.CompoundFile(path) as cf:
                self.assertIs(colors.of_scene(cf), want)
                graph = reader_materials.MaterialGraph(reader_scene.Scene.from_file(cf))
                self.assertIs(colors.of_graph(graph), want)


if __name__ == "__main__":
    unittest.main()
