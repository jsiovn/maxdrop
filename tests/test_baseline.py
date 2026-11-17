# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""tools/baseline.py reads the operator's import line from Blender's console log: plain Python, no Blender."""
import importlib.util
import os
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("baseline", os.path.join(ROOT, "tools", "baseline.py"))
baseline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(baseline)

ZERO = {"placeholders": 0, "modifiers_not_applied": 0, "textures_missing": 0, "approximated": 0, "issues": 0}


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
            "objects": 747, "meshes": 343, "materials": 141, "placeholders": 323, "modifiers_not_applied": 1,
            "textures_missing": 2, "approximated": 4, "issues": 5})
        self.assertNotIn("secret", repr(found))

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

    def test_missing_log(self):
        found = baseline.read_log(os.path.join(self.folder, "none.log"))
        self.assertEqual(found, {"import_report": None, "traceback": False})


if __name__ == "__main__":
    unittest.main()
