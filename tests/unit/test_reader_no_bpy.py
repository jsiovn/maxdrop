# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""maxdrop/reader, maxdrop/convert and maxdrop/intake run under plain Python: no module there imports bpy or
mathutils, nor another module of the add-on outside these packages (those may import bpy)."""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGES = ("reader", "convert", "intake")
FORBIDDEN = {"bpy", "mathutils"}
ADDON = "maxdrop"


def modules(root=ROOT):
    for package in PACKAGES:
        base = os.path.join(root, ADDON, package)
        for folder, _dirs, files in os.walk(base):
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(folder, name)


def _package_of(path, root):
    """The dotted package a module file belongs to, as a list: maxdrop/reader/cfb.py -> [maxdrop, reader]."""
    rel = os.path.relpath(os.path.dirname(os.path.abspath(path)), root)
    return [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]


def _targets(node, package):
    """The absolute module names an import statement loads; None for a relative import above the top package."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level == 0:
            return [node.module] if node.module else []
        if node.level > len(package):
            return None
        base = package[:len(package) - node.level + 1]
        if node.module:
            return [".".join(base + node.module.split("."))]
        return [".".join(base + [a.name]) for a in node.names]
    if (isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", ""))
            in ("import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant)):
        return [str(node.args[0].value)]
    return []


def _refused(name):
    parts = name.split(".")
    if parts[0] in FORBIDDEN:
        return True
    return parts[0] == ADDON and (len(parts) < 2 or parts[1] not in PACKAGES)


def forbidden_imports(path, root=ROOT):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    package = _package_of(path, root)
    found = []
    for node in ast.walk(tree):
        names = _targets(node, package)
        if names is None:
            found.append("%s:%d relative import above %s" % (path, node.lineno, ".".join(package)))
            continue
        found += ["%s:%d %s" % (path, node.lineno, n) for n in names if _refused(n)]
    return found


class NoBpy(unittest.TestCase):
    def test_reader_convert_and_intake_never_import_bpy(self):
        paths = list(modules())
        for seen in (("reader", "cfb.py"), ("intake", "archive.py")):  # the scan saw each package
            self.assertIn(os.path.join(ROOT, ADDON, *seen), paths)
        found = [hit for p in paths for hit in forbidden_imports(p)]
        self.assertEqual(found, [])

    def test_the_scan_catches_each_form(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ADDON, "reader"))
            path = os.path.join(tmp, ADDON, "reader", "m.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("import os, bpy\nfrom mathutils import Matrix\nimport bpy.types\n"
                        "import importlib\nimportlib.import_module('bpy')\nfrom . import x\n")
            self.assertEqual(len(forbidden_imports(path, tmp)), 4)

    def test_other_modules_of_the_addon_are_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, ADDON, "intake")
            os.makedirs(folder)
            path = os.path.join(folder, "m.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("from .. import compat\nfrom ..ops import x\nimport maxdrop.update\nimport maxdrop\n"
                        "from .... import y\n"
                        "from . import sibling\nfrom ..reader import cfb\nfrom .. import convert\n"
                        "import maxdrop.reader.cfb\n")
            found = forbidden_imports(path, tmp)
            self.assertEqual([hit.split(":")[-1] for hit in found],
                             ["1 maxdrop.compat", "2 maxdrop.ops", "3 maxdrop.update", "4 maxdrop",
                              "5 relative import above maxdrop.intake"], found)


if __name__ == "__main__":
    unittest.main()
