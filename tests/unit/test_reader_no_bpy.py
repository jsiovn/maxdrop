# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""maxdrop/reader and maxdrop/convert run under plain Python: no module there imports bpy or mathutils."""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGES = ("reader", "convert")
FORBIDDEN = {"bpy", "mathutils"}


def modules():
    for package in PACKAGES:
        base = os.path.join(ROOT, "maxdrop", package)
        for folder, _dirs, files in os.walk(base):
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(folder, name)


def forbidden_imports(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in (
                "import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant):
            names = [str(node.args[0].value)]
        else:
            continue
        found += ["%s:%d %s" % (path, node.lineno, n) for n in names
                  if n.split(".")[0] in FORBIDDEN]
    return found


class NoBpy(unittest.TestCase):
    def test_reader_and_convert_never_import_bpy(self):
        paths = list(modules())
        self.assertIn(os.path.join(ROOT, "maxdrop", "reader", "cfb.py"), paths)  # the scan saw the package
        found = [hit for p in paths for hit in forbidden_imports(p)]
        self.assertEqual(found, [])

    def test_the_scan_catches_each_form(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("import os, bpy\nfrom mathutils import Matrix\nimport bpy.types\n"
                        "import importlib\nimportlib.import_module('bpy')\nfrom . import x\n")
            self.assertEqual(len(forbidden_imports(path)), 4)


if __name__ == "__main__":
    unittest.main()
