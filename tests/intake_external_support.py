# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the tests of maxdrop/intake/external.py share: the package loaded without Blender, the test tree,
the fixtures' paths and the helpers."""
import importlib
import os
import sys
import tempfile
import types
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTAKE = os.path.join(ROOT, "maxdrop", "intake")
PACKS = os.path.join(ROOT, "tests", "fixtures", "packs")


# Under a package whose path is maxdrop/ (`import maxdrop` would pull bpy), not tests/test_intake.py's: that one
# keeps a zip-only archive/. archive/ installs the external backends of this package itself.
_PKG = "maxdrop_intake_ext_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
archive = importlib.import_module(_PKG + ".intake.archive")
external = importlib.import_module(_PKG + ".intake.external")

PackError = archive.PackError
Tool = external.Tool
UNRAR, SEVENZIP, BSDTAR = external.UNRAR, external.SEVENZIP, external.BSDTAR

# What every test pack holds.
TREE = {
    "pack/scene/scene.max": b"MAXDROP TEST SCENE",
    "pack/scene/maps/wood.jpg": b"near wood",
    "pack/other/wood.jpg": b"far wood",
    "pack/sub dir/my map.png": b"map with a space",
    "pack/scene/light.IES": b"ies",
    "pack/readme.txt": b"not unpacked",
}
EXPECTED = {"scene.max": b"MAXDROP TEST SCENE", "wood.jpg": b"near wood", "my map.png": b"map with a space",
            "light.IES": b"ies"}

PY = sys.executable


def say(case, ran, reason=""):
    sys.stderr.write("\n  real tool: %s: %s" % (case, "RAN" if ran else "SKIPPED (%s)" % reason))
    sys.stderr.flush()


def folder_files(folder):
    out = {}
    for name in os.listdir(folder):
        if name != archive.MARKER:
            with open(os.path.join(folder, name), "rb") as f:
                out[name] = f.read()
    return out


def rar5_header(htype, hflags=0, aflags=0, extra=()):
    body = bytes([htype, hflags]) + bytes(extra) + bytes([aflags])
    return b"Rar!\x1a\x07\x01\x00" + b"\0\0\0\0" + bytes([len(body)]) + body + b"\0" * 32


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maxdrop-ext-")
        self.addCleanup(external._remove_tree, external._long(self.tmp))
