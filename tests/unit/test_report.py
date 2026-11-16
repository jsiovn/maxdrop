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
textures = importlib.import_module(_PKG + ".convert.textures")
colors = importlib.import_module(_PKG + ".convert.colors")
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


def stats(**kw):
    return types.SimpleNamespace(**kw)


def lookup(found=(), missing=()):
    """A real convert.textures.TextureReport with these names found (by the scene's folder) and missing."""
    out = textures.TextureReport()
    for name in found:
        out.add(name, textures.Found("C:/scene/" + name, textures.SCENE))
    for name in missing:
        out.add(name, None)
    return out


def box():
    desc = conv.SceneDescription(1.0)
    desc.nodes = [node(1, "Box")]
    desc.meshes = {(1, None): None}
    return desc


class TestMaterials(unittest.TestCase):
    def setUp(self):
        self.rep = report.gather(box(), source="box.max")
        report.add_materials(
            self.rep, 6, collections.Counter({"VRayMtl": 3, "Standard": 2}),
            conv_stats=stats(peeled=collections.Counter({"VRay2SidedMtl": 1, "Shell Material": 1}),
                             unknown=collections.Counter({"FooMtl": 2}), issues=[(7, "wrapper: no sub-material")]),
            tex_stats=stats(peeled=collections.Counter({"Falloff": 3}), unsupported=collections.Counter({"BarMap": 1}),
                            issues=[(9, "Mix 'm': its mix curve not converted")]),
            lookup=lookup(found=("wood.jpg",), missing=("b.png", "A.png")),
            sockets=collections.Counter({"Thin Wall": 2}), blender="4.2.23")

    def test_counters(self):
        rep = self.rep
        self.assertEqual(rep.approximated, 1 + 1 + 3)
        self.assertEqual(rep.textures_missing, ["A.png", "b.png"])
        self.assertEqual(rep.left_out, 2 + 1 + 2 + 2 + 2)  # grey, unsupported, sockets, issues, missing

    def test_text(self):
        self.assertEqual(self.rep.text().split("\n")[7:], [
            "Materials built: 6 (converted by class: VRayMtl 3, Standard 2)",
            "Textures found: 1 (the scene's folder 1, maps or textures folders 0, texture search folders 0, "
            "the stored path 0)",
            "Approximated:",
            "  Wrappers peeled to their sub-material, by class: Shell Material 1, VRay2SidedMtl 1",
            "  Maps peeled to the map below them, by class: Falloff 3",
            "Not converted:",
            "  Material classes without a rule (grey material), by class: FooMtl 2",
            "  Map classes without a map below (not used), by class: BarMap 1",
            "  Principled inputs not on Blender 4.2.23 (not set), materials: Thin Wall 2",
            "  Textures not found: 2",
            "    A.png",
            "    b.png",
            "  Material issues: 2",
            "    object 7: wrapper: no sub-material",
            "    object 9: Mix 'm': its mix curve not converted",
        ])

    def test_summary_warns(self):
        self.assertEqual(self.rep.summary(), (
            "WARNING", "Imported box.max: 1 object, 1 mesh, 6 materials; 2 textures missing, 5 approximated, "
                       "7 issues. See the text MaxDrop Report."))

    def test_only_approximated_warns(self):
        rep = report.gather(box(), source="box.max")
        report.add_materials(rep, 1, {"VRayMtl": 1}, conv_stats=stats(
            peeled=collections.Counter({"Shell Material": 1}), unknown=collections.Counter(), issues=[]))
        self.assertEqual(rep.summary(), ("WARNING", "Imported box.max: 1 object, 1 mesh, 1 material; "
                                                    "1 approximated. See the text MaxDrop Report."))
        lines = rep.text().split("\n")
        self.assertEqual(lines[-2:], ["Approximated:",
                                      "  Wrappers peeled to their sub-material, by class: Shell Material 1"])
        self.assertNotIn("Not converted:", lines)

    def test_nothing_left_out(self):
        rep = report.gather(box(), source="box.max")
        report.add_materials(rep, 3, collections.Counter({"Standard": 3}), lookup=lookup())
        self.assertEqual(rep.summary(), ("INFO", "Imported box.max: 1 object, 1 mesh, 3 materials, nothing left out."))
        self.assertEqual(rep.text().split("\n")[7:], [
            "Materials built: 3 (converted by class: Standard 3)",
            "Textures found: 0 (the scene's folder 0, maps or textures folders 0, texture search folders 0, "
            "the stored path 0)",
            "Nothing was left out.",
        ])

    def test_no_materials_imported(self):
        lines = report.gather(box(), source="box.max").text().split("\n")
        self.assertFalse(any(line.startswith(("Materials", "Textures")) for line in lines))

    def test_no_material_converted(self):
        rep = report.gather(box())
        report.add_materials(rep, 0)
        self.assertIn("Materials built: 0", rep.text().split("\n"))

    def test_search_stopped(self):
        found = lookup()
        found.truncated.append((textures.USER, "D:/tex/deep", 200000))
        rep = report.gather(box())
        report.add_materials(rep, 0, lookup=found)
        self.assertIn("Texture search of texture search folders stopped after 200000 files and folders, in "
                      "D:/tex/deep", rep.text().split("\n"))

    def test_long_missing_list_is_cut(self):
        rep = report.gather(box())
        report.add_materials(rep, 0, lookup=lookup(missing=["t%03d.png" % i for i in range(report.MAX_LISTED + 3)]))
        text = rep.text()
        self.assertIn("  Textures not found: %d" % (report.MAX_LISTED + 3), text)
        self.assertNotIn("t%03d.png" % report.MAX_LISTED, text)
        self.assertIn("    ... and 3 more", text)

    def test_missing_texture_in_a_pack(self):
        pack = Pack()
        pack.collided = ["sub/Wood.JPG"]
        pack.refused = [("../evil.jpg", "a path outside the pack")]
        pack.not_regular = ["maps/link.jpg"]
        pack.skipped = {".tif": 2}
        rep = report.gather(box(), pack=pack, pack_name="room.zip")
        report.add_materials(rep, 1, lookup=lookup(missing=("wood.jpg", "evil.jpg", "link.jpg", "scan.tif",
                                                            "gone.png")))
        lines = rep.text().split("\n")
        start = lines.index("  Textures not found: 5")
        self.assertEqual(lines[start + 1:start + 6], [
            "    evil.jpg: in the archive, refused: a path outside the pack",
            "    gone.png: not in the archive",
            "    link.jpg: in the archive, not a regular file",
            "    scan.tif: the archive's .tif files were skipped",
            "    wood.jpg: in the archive more than once, a copy written (not written: sub/Wood.JPG)",
        ])

    def test_missing_texture_in_a_reused_pack(self):
        pack = Pack()
        pack.mode = "reused"
        rep = report.gather(box(), pack=pack, pack_name="room.zip")
        report.add_materials(rep, 1, lookup=lookup(missing=("wood.jpg",)))
        lines = rep.text().split("\n")
        self.assertEqual(lines[lines.index("  Textures not found: 1") + 1], "    wood.jpg")


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


class TestSwatches(unittest.TestCase):
    """The scene's swatch rule: a line under the materials; the note of a scene without the setting is an issue."""

    def test_gamma_on_and_off_are_a_line(self):
        for rule, words in ((colors.GAMMA_ON, "linear (the scene's gamma is on)"),
                            (colors.GAMMA_OFF, "decoded from sRGB (the scene's gamma is off)")):
            with self.subTest(rule):
                rep = report.gather(box(), source="box.max")
                report.add_materials(rep, 3, collections.Counter({"Standard": 3}), lookup=lookup(), swatches=rule)
                self.assertEqual(rep.text().split("\n")[7:9], [
                    "Materials built: 3 (converted by class: Standard 3)", "Color swatches: " + words])
                self.assertEqual(rep.summary()[0], "INFO")

    def test_unknown_is_an_issue(self):
        rep = report.gather(box(), source="box.max")
        report.add_materials(rep, 3, collections.Counter({"Standard": 3}), lookup=lookup(), swatches=colors.UNKNOWN)
        lines = rep.text().split("\n")
        self.assertIn("Color swatches: linear (the scene's gamma setting not found)", lines)
        self.assertIn("    color swatches: " + colors.GAMMA_NOTE, lines)
        self.assertEqual(rep.summary()[0], "WARNING")
        self.assertEqual(rep.left_out, 1)

    def test_without_a_rule_no_line(self):
        rep = report.gather(box(), source="box.max")
        report.add_materials(rep, 3, collections.Counter({"Standard": 3}), lookup=lookup())
        self.assertFalse(any(line.startswith("Color swatches") for line in rep.text().split("\n")))


if __name__ == "__main__":
    unittest.main()
