# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every error a damaged .max or scene pack raises is a MaxFileError (maxdrop/reader/errors.py), and a ValueError:
the operator reports it as the reason a file was not imported. No Blender.

    python -I -m unittest discover tests
"""
import importlib
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PKG = "maxdrop_convert_test"  # as the convert tests: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg


def _cls(module, name):
    return getattr(importlib.import_module(_PKG + "." + module), name)


LAYERS = (
    ("reader.cfb", "CfbError"),
    ("reader.chunks", "ChunkError"),
    ("reader.geometry", "GeometryError"),
    ("reader.shapes", "ShapeError"),
    ("reader.metadata", "MetadataError"),
    ("convert.cameras", "CameraError"),
    ("convert.extrude", "ExtrudeError"),
    ("convert.lights", "LightError"),
    ("convert.modifiers", "ModifierError"),
    ("convert.primitives", "PrimitiveError"),
    ("convert.uvwmap", "UVWMapError"),
    ("intake.archive", "PackError"),
    ("intake.archive", "Cancelled"),
)


class HierarchyTest(unittest.TestCase):
    def test_max_file_error_is_a_value_error(self):
        self.assertTrue(issubclass(_cls("reader.errors", "MaxFileError"), ValueError))

    def test_every_layer_raises_a_max_file_error(self):
        base = _cls("reader.errors", "MaxFileError")
        for module, name in LAYERS:
            with self.subTest(error=name):
                self.assertTrue(issubclass(_cls(module, name), base))

    def test_the_message_is_kept(self):
        err = _cls("reader.cfb", "CfbError")("not a compound file")
        self.assertEqual(str(err), "not a compound file")


if __name__ == "__main__":
    unittest.main()
