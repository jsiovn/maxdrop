# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""tools/baseline.py reads the operator's import line from Blender's console log: plain Python, no Blender."""
import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("baseline", os.path.join(ROOT, "tools", "baseline.py"))
baseline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(baseline)

_PKG = "maxdrop_convert_test"  # as in tests/unit/test_report.py: maxdrop/__init__.py (and bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
report = importlib.import_module(_PKG + ".convert.report")

ZERO = {"curves": 0, "placeholders": 0, "modifiers_not_applied": 0, "textures_missing": 0, "approximated": 0, "issues": 0}


class ReadLog(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)

    def read(self, *lines):
        path = os.path.join(self.folder, "out.json.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(line + "\n" for line in lines))
        return baseline.read_log(path)

    def test_clean_import(self):
        found = self.read("Read prefs: x",
                          "MaxDrop: Imported box.max: 2 objects, 1 mesh, 1 material, nothing left out.")
        self.assertEqual(found["import_report"], dict(ZERO, objects=2, meshes=1, materials=1))
        self.assertFalse(found["traceback"])

    def test_left_out_counts_and_no_name(self):
        found = self.read("MaxDrop: Imported a: secret.max: 747 objects, 343 meshes, 141 materials; 323 placeholders, "
                          "1 modifier not applied, 2 textures missing, 4 approximated, 5 issues. "
                          "See the text MaxDrop Report.")
        self.assertEqual(found["import_report"], {
            "objects": 747, "meshes": 343, "curves": 0, "materials": 141, "placeholders": 323, "modifiers_not_applied": 1,
            "textures_missing": 2, "approximated": 4, "issues": 5})
        self.assertNotIn("secret", repr(found))

    def test_curves(self):
        found = self.read("MaxDrop: Imported shapes.max: 4 objects, 1 mesh, 3 curves, 1 material, nothing left out.")
        self.assertEqual(found["import_report"], dict(ZERO, objects=4, meshes=1, curves=3, materials=1))

    def test_curves_with_left_out_and_no_materials(self):
        found = self.read("MaxDrop: Imported a.max: 2 objects, 0 meshes, 1 curve; 1 placeholder, 2 issues. "
                          "See the text MaxDrop Report.")
        self.assertEqual(found["import_report"], dict(ZERO, objects=2, meshes=0, curves=1, materials=None,
                                                      placeholders=1, issues=2))

    def test_without_materials(self):
        found = self.read("MaxDrop: Imported box.max: 1 object, 1 mesh, nothing left out.")
        self.assertEqual(found["import_report"], dict(ZERO, objects=1, meshes=1, materials=None))

    def test_several_scenes_are_summed(self):
        found = self.read("MaxDrop: Imported a.max: 1 object, 1 mesh, nothing left out.",
                          "MaxDrop: Imported b.max: 3 objects, 2 meshes, 2 materials; 1 placeholder. "
                          "See the text MaxDrop Report.")
        self.assertEqual(found["import_report"], dict(ZERO, objects=4, meshes=3, materials=2, placeholders=1))

    def test_no_import_line(self):
        found = self.read("Traceback (most recent call last):", "  File \"x\", line 1")
        self.assertIsNone(found["import_report"])
        self.assertTrue(found["traceback"])

    def test_old_engine_fields_are_gone(self):
        found = self.read("\tImportError: boom [ 1f]Box Box001", "\tskipping Box002")
        for key in ("node_errors", "nodes_failed", "nodes_skipped"):
            self.assertNotIn(key, found)
        self.assertIsNone(found["import_report"])

    def test_round_trip_with_report_summary(self):
        """The line Report.summary() really builds, so a change of its wording fails here, not silently in a
        measurement: every left-out part, singular and plural, and a name that looks like a summary itself."""
        for n in (1, 2):
            rep = report.Report("x: 9 objects, 9 meshes, nothing left out.max")
            rep.objects_built, rep.meshes_built, rep.curves_built, rep.materials_built = n, n, n, n
            rep.placeholders["Light"] = n
            rep.modifiers["Bend"] = n
            rep.textures_missing = ["t.png"] * n
            rep.wrappers["Blend"] = n
            rep.issues = ["?"] * n
            found = self.read("MaxDrop: " + rep.summary()[1])
            self.assertEqual(found["import_report"], {
                "objects": n, "meshes": n, "curves": n, "materials": n, "placeholders": n, "modifiers_not_applied": n,
                "textures_missing": n, "approximated": n, "issues": n}, rep.summary()[1])
        rep = report.Report("")
        found = self.read("MaxDrop: " + rep.summary()[1])
        self.assertEqual(found["import_report"], dict(ZERO, objects=0, meshes=0, materials=None))

    def test_missing_log(self):
        found = baseline.read_log(os.path.join(self.folder, "none.log"))
        self.assertEqual(found, {"import_report": None, "traceback": False})


if __name__ == "__main__":
    unittest.main()
