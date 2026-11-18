# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/pathnames.py, the name rules reader/, convert/ and intake/ share: no Blender.

    python -I -m unittest discover tests
"""
import importlib
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PKG = "maxdrop_convert_test"  # the package the convert tests make: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
pathnames = importlib.import_module(_PKG + ".pathnames")


class BaseNameTest(unittest.TestCase):
    def test_both_separators(self):
        for path, want in (("", ""), ("a.jpg", "a.jpg"), (r"C:\x\a.jpg", "a.jpg"), ("C:/x/a.jpg", "a.jpg"),
                           (r"\\host\share\a.jpg", "a.jpg"), ("x/", ""), (r"mixed/x\a.jpg", "a.jpg"),
                           ("C:a", "C:a")):  # no drive split: the callers' rules refuse such a name
            with self.subTest(path=path):
                self.assertEqual(pathnames.base_name(path), want)


class ReservedTest(unittest.TestCase):
    def test_reserved(self):
        for name in ("CON", "con", "Con.txt", "NUL.tar.gz", "AUX .jpg", "COM1", "LPT9", "COM¹", "lpt³",
                     "CONIN$", "conout$.x", "PRN"):
            with self.subTest(name=name):
                self.assertTrue(pathnames.is_reserved(name))

    def test_not_reserved(self):
        for name in ("", "COM0", "LPT", "CONSOLE", "xCON", "a.CON", "COM10", " CON", "NUL_", "COM4²"):
            with self.subTest(name=name):
                self.assertFalse(pathnames.is_reserved(name))

    def test_the_set(self):
        self.assertIsInstance(pathnames.RESERVED, frozenset)
        self.assertEqual(len(pathnames.RESERVED), 30)
        self.assertTrue(all(n == n.upper() for n in pathnames.RESERVED))


if __name__ == "__main__":
    unittest.main()
