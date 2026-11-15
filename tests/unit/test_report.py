# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/report.py, the import report: no Blender. A synthetic import (every counter and list,
the pack block, the cut of long lists) and the layers_flags fixture.

    python -I -m unittest discover tests
"""
import collections
import importlib
import os
import sys
import types
import unittest

try:
    import numpy
except ImportError:  # the plain CI job has no numpy; Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PKG = "maxdrop_convert_test"  # the same package name as test_convert_scene: maxdrop/__init__.py never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
conv = importlib.import_module(_PKG + ".convert.scene")
report = importlib.import_module(_PKG + ".convert.report")
units = importlib.import_module(_PKG + ".reader.units")

IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))


def node(index, name, kind=conv.MESH, **kw):
    modifiers = kw.pop("modifiers", ())
    return conv.NodeDescription(index, name, None, IDENTITY, IDENTITY, kind, None, "", False, modifiers, **kw)


def synthetic():
    desc = conv.SceneDescription(0.001, units.SystemUnit("millimeters", 0.001))
    desc.nodes = [node(5, "Wall", hidden=True), node(6, "Lamp", conv.EMPTY, renderable=False),
                  node(7, "", conv.EMPTY, frozen=True), node(8, "Group", conv.EMPTY, group_head=True),
                  node(9, "Chair", modifiers=("TurboSmooth", "UVW Map")), node(10, "Table", modifiers=("UVW Map",))]
    desc.meshes = {(1, None): None, (2, None): None}
    desc.layers = [conv.LayerDescription(20, "Walls", hidden=True), conv.LayerDescription(21, "Props")]
    desc.placeholders = collections.Counter({"VRayLight": 1, "": 1})
    desc.unknown_controllers = collections.Counter({"Noise Position": 2})
    desc.issues = [(5, "geometry: 0x0100 of 3 bytes has no count"), (7, "transform: unknown controller class"),
                   (99, "node: damaged")]
    return desc


class Pack:
    """The fields of maxdrop.intake.archive.UnpackResult the report reads."""
    max_path, folder, mode, backend = "C:/packs/room/room.max", "C:/packs/room", "unpacked", "zipfile"
    written, reused, unwanted = 12, 0, 3
    skipped = {".psd": 2, ".txt": 1}
    refused = [("../evil.jpg", "a path outside the pack")]
    not_regular = ["link.jpg"]
    collided = ["wood.jpg"]
    guessed = []


class TestSynthetic(unittest.TestCase):
    def setUp(self):
        self.rep = report.gather(synthetic(), source="room.max", objects_built=6, meshes_built=2,
                                 dropped_uv_layers=1)

    def test_counters(self):
        rep = self.rep
        self.assertEqual((rep.nodes, rep.objects_built, rep.meshes_built, rep.layers, rep.hidden_layers),
                         (6, 6, 2, 2, 1))
        self.assertEqual((rep.hidden, rep.unrenderable, rep.frozen, rep.groups), (1, 1, 1, 1))
        self.assertEqual(dict(rep.modifiers), {"TurboSmooth": 1, "UVW Map": 2})
        self.assertEqual(rep.geometry_errors, [("Wall", "0x0100 of 3 bytes has no count")])
        self.assertEqual(rep.issues, [("object 99", "node: damaged")])  # the unknown controller is counted by class
        self.assertEqual(rep.unknown_controller_nodes, 1)
        self.assertEqual(rep.left_out, 2 + 3 + 1 + 1 + 1 + 1)

    def test_text(self):
        self.assertEqual(self.rep.text().split("\n"), [
            "MaxDrop import report: room.max",
            "Units: millimeters (0.001 m per unit)",
            "Nodes read: 6",
            "Objects built: 6, meshes: 2",
            "Layers: 2 (1 hidden)",
            "Objects hidden: 1, not renderable: 1, frozen: 1",
            "Groups: 1",
            "Not converted:",
            "  Placeholders (empties) by class: (unnamed class) 1, VRayLight 1",
            "  Modifiers not applied (the base mesh is built), nodes by class: UVW Map 2, TurboSmooth 1",
            "  Unknown controllers by class (identity used): Noise Position 2",
            "  UV channels past Blender's limit: 1",
            "  Geometry errors: 1",
            "    Wall: 0x0100 of 3 bytes has no count",
            "  Other issues: 1",
            "    object 99: node: damaged",
        ])

    def test_summary_warns(self):
        self.assertEqual(self.rep.summary(), (
            "WARNING", "Imported room.max: 6 objects, 2 meshes; 2 placeholders, 3 modifiers not applied, 4 issues. "
                       "See the text MaxDrop Report."))

    def test_pack_block_comes_first(self):
        rep = report.gather(synthetic(), source="room.max", pack=Pack(), pack_name="room.zip")
        lines = rep.text().split("\n")
        self.assertEqual(lines[1:11], [
            "Scene pack: room.zip",
            "  Pack folder: C:/packs/room",
            "  Unpacker: zipfile",
            "  Files written: 12, reused from an earlier unpack: 0",
            "  Skipped by extension: .psd 2, .txt 1",
            "  Names that collided (the copy nearer the scene was kept): 1: wood.jpg",
            "  Refused: 1: ../evil.jpg (a path outside the pack)",
            "  Not regular files: 1: link.jpg",
            "  Files the scene does not use, left out: 3",
            "Units: millimeters (0.001 m per unit)",
        ])

    def test_pack_used_in_place(self):
        pack = Pack()
        pack.mode = "in_place"
        lines = report.gather(synthetic(), pack=pack).text().split("\n")
        self.assertIn("  Files: a copy already in that folder, used in place", lines)
        self.assertEqual(lines[1], "Scene pack: room")

    def test_long_lists_are_cut(self):
        desc = synthetic()
        desc.issues = [(5, "transform: shear") for _ in range(report.MAX_LISTED + 7)]
        text = report.gather(desc).text()
        self.assertEqual(text.count("Wall: transform: shear"), report.MAX_LISTED)
        self.assertIn("    ... and 7 more", text)

    def test_nothing_left_out(self):
        desc = conv.SceneDescription(1.0)
        desc.nodes = [node(1, "Box")]
        desc.meshes = {(1, None): None}
        rep = report.gather(desc, source="box.max")
        self.assertEqual(rep.summary(), ("INFO", "Imported box.max: 1 object, 1 mesh, nothing left out."))
        lines = rep.text().split("\n")
        self.assertEqual(lines[1], "Units: not stated in the file, 1 m per unit")
        self.assertEqual(lines[-1], "Nothing was left out.")


@unittest.skipIf(numpy is None, "numpy missing")
class TestFixture(unittest.TestCase):
    def test_layers_flags(self):
        desc = conv.read(os.path.join(ROOT, "tests", "fixtures", "layers_flags.max"))
        rep = report.gather(desc, source="layers_flags.max")
        self.assertEqual(rep.summary(), ("INFO", "Imported layers_flags.max: 6 objects, 5 meshes, nothing left out."))
        self.assertEqual(rep.text().split("\n")[1:], [
            "Units: millimeters (0.001 m per unit)",
            "Nodes read: 6",
            "Objects built: 6, meshes: 5",
            "Layers: 2 (0 hidden)",
            "Objects hidden: 1, not renderable: 1, frozen: 0",
            "Groups: 1",
            "Nothing was left out.",
        ])


if __name__ == "__main__":
    unittest.main()
