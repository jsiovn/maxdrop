# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""maxdrop/reader, maxdrop/convert and maxdrop/intake run under plain Python: no module there imports bpy or
mathutils, nor another module of the add-on outside these packages (those may import bpy) except the shared
bpy-free modules (maxdrop/pathnames.py), which are held to the same rules, nor the add-on by its absolute name
(that runs maxdrop/__init__.py)."""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGES = ("reader", "convert", "intake")
SHARED = ("pathnames",)  # top-level modules of the add-on these packages may import
FORBIDDEN = {"bpy", "mathutils"}
ADDON = "maxdrop"


def modules(root=ROOT):
    for package in PACKAGES:
        base = os.path.join(root, ADDON, package)
        for folder, _dirs, files in os.walk(base):
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(folder, name)
    for name in SHARED:
        yield os.path.join(root, ADDON, name + ".py")


def _package_of(path, root):
    """The dotted package a module file belongs to, as a list: maxdrop/reader/cfb.py -> [maxdrop, reader]."""
    rel = os.path.relpath(os.path.dirname(os.path.abspath(path)), root)
    return [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]


def _relative(level, module, names, package):
    """Absolute names of a relative import of `level` dots from `package`; None when it climbs above it."""
    if level > len(package):
        return None
    base = package[:len(package) - level + 1]
    if module:
        return [".".join(base + module.split("."))]
    return [".".join(base + [n]) for n in names]


def _targets(node, package):
    """(module name, relative) for each module an import statement loads; None for a relative import above the
    top package."""
    if isinstance(node, ast.Import):
        return [(a.name, False) for a in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level == 0:
            return [(node.module, False)] if node.module else []
        names = _relative(node.level, node.module, [a.name for a in node.names], package)
        return None if names is None else [(n, True) for n in names]
    if (isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", ""))
            in ("import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant)):
        name = str(node.args[0].value)
        if not name.startswith("."):
            return [(name, False)]
        anchor = package
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
            anchor = node.args[1].value.split(".")
        rest = name.lstrip(".")
        names = _relative(len(name) - len(rest), rest, [], anchor)
        return None if names is None else [(n, True) for n in names]
    return []


def _refused(name, relative):
    """bpy and mathutils always. An absolute `maxdrop...` import always: it runs maxdrop/__init__.py, which imports
    bpy, and inside Blender the add-on is not named maxdrop (bl_ext.<repo>.maxdrop). A relative one when it leaves
    the bpy-free packages."""
    parts = name.split(".")
    if parts[0] in FORBIDDEN:
        return True
    if parts[0] != ADDON:
        return False
    return not relative or len(parts) < 2 or parts[1] not in PACKAGES + SHARED


def forbidden_imports(path, root=ROOT):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    package = _package_of(path, root)
    # a shared module imports nothing of the add-on: the packages import it, an import back could be a cycle
    shared = package == [ADDON] and os.path.splitext(os.path.basename(path))[0] in SHARED
    found = []
    for node in ast.walk(tree):
        names = _targets(node, package)
        if names is None:
            found.append("%s:%d relative import above %s" % (path, node.lineno, ".".join(package)))
            continue
        found += ["%s:%d %s" % (path, node.lineno, n) for n, relative in names
                  if _refused(n, relative) or (shared and n.split(".")[0] == ADDON)]
    return found


class NoBpy(unittest.TestCase):
    def test_reader_convert_and_intake_never_import_bpy(self):
        paths = list(modules())
        for seen in (("reader", "cfb.py"), ("intake", "archive.py"), ("pathnames.py",)):  # the scan saw each part
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
                        "import maxdrop.reader.cfb\nfrom maxdrop.reader import cfb\n"
                        "importlib.import_module('..compat', 'maxdrop.reader')\n"
                        "importlib.import_module('..reader.cfb', __package__)\n"
                        "importlib.import_module('.cfb', 'maxdrop.reader')\n"
                        "from .. import pathnames\nfrom ..pathnames import base_name\nimport maxdrop.pathnames\n")
            found = forbidden_imports(path, tmp)
            self.assertEqual([hit.split(":")[-1] for hit in found],
                             ["1 maxdrop.compat", "2 maxdrop.ops", "3 maxdrop.update", "4 maxdrop",
                              "5 relative import above maxdrop.intake", "9 maxdrop.reader.cfb",
                              "10 maxdrop.reader", "16 maxdrop.pathnames", "11 maxdrop.compat"], found)

    def test_a_shared_module_is_held_to_the_same_rules(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ADDON))
            path = os.path.join(tmp, ADDON, "pathnames.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("import bpy\nfrom . import compat\nfrom .. import x\nfrom .reader import cfb\n"
                        "import os\n")
            self.assertEqual([hit.split(":")[-1] for hit in forbidden_imports(path, tmp)],
                             ["1 bpy", "2 maxdrop.compat", "3 relative import above maxdrop",
                              "4 maxdrop.reader"])


if __name__ == "__main__":
    unittest.main()
