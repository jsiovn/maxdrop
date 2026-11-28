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
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PKG = "maxdrop_convert_test"  # the same package name as test_convert_scene: maxdrop/__init__.py never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
conv = importlib.import_module(_PKG + ".convert.scene")
report = importlib.import_module(_PKG + ".convert.report")
texmaps = importlib.import_module(_PKG + ".convert.texmaps")
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
            "  Modifiers not applied (ignored: the object arrives as its base object, or as its Extrude makes it), "
            "nodes by class: UVW Map 2, TurboSmooth 1",
            "  Unknown controllers by class (identity used): Noise Position 2",
            "  UV channels past Blender's limit: 1",
            "  Geometry errors: 1",
            "    Wall: 0x0100 of 3 bytes has no count",
            "  Other issues: 1",
            "    object 99: node: damaged",
        ])

    def test_modifier_outcomes(self):
        """Applied and converted modifiers are listed with what was built and left out of the count; ignored ones
        are what the report calls not applied. Each class counts once per node."""
        rep = self.rep
        self.assertEqual((dict(rep.modifiers_applied), dict(rep.modifiers_converted)), ({}, {}))
        rep.add_modifiers(report.APPLIED, ("Extrude", "UVW Map", "UVW Map"))
        rep.add_modifiers(report.CONVERTED, ("TurboSmooth",))
        rep.add_modifiers(report.CONVERTED, ("TurboSmooth", "Shell"))
        self.assertEqual((dict(rep.modifiers_applied), dict(rep.modifiers_converted)),
                         ({"Extrude": 1, "UVW Map": 1}, {"TurboSmooth": 2, "Shell": 1}))
        self.assertEqual(rep.left_out, 2 + 3 + 1 + 1 + 1 + 1)
        lines = rep.text().split("\n")
        self.assertEqual(lines[7:9], [
            "Modifiers applied (baked into the mesh), nodes by class: Extrude 1, UVW Map 1",
            "Modifiers converted to a Blender modifier, nodes by class: TurboSmooth 2, Shell 1"])
        with self.assertRaises(KeyError):
            rep.add_modifiers("dropped", ("Bend",))

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

    def test_scene_camera_note_is_no_issue(self):
        desc = conv.SceneDescription(1.0)
        desc.nodes = [node(1, "Box"), node(2, "Cam", conv.CAMERA)]
        desc.meshes = {(1, None): None}
        desc.camera, desc.camera_note = 2, "the first camera: the view 3ds Max renders (viewport 4) looks through " \
            "no camera"
        rep = report.gather(desc, source="room.max")
        self.assertEqual(rep.summary()[0], report.LEVEL_INFO)
        self.assertIn("Render size: not stored, Blender's kept; scene camera: Cam, the first camera: the view 3ds Max "
                      "renders (viewport 4) looks through no camera", rep.text().split("\n"))

    def test_emitters_are_counted_with_the_lights(self):
        desc = conv.SceneDescription(1.0)
        desc.nodes = [node(1, "Box"), node(2, "Strip")]
        desc.meshes = {(1, None): None, ("emitter", 2, 1, None): None}
        desc.lights = {(3, 1.0): None}
        desc.emitters = {2: None}
        rep = report.gather(desc, source="room.max")
        self.assertEqual(rep.lights_built, 2)

    def test_curves_are_counted(self):
        desc = conv.SceneDescription(1.0)
        desc.nodes = [node(1, "Box"), node(2, "Outline", conv.CURVE)]
        desc.meshes = {(1, None): None}
        desc.curves = {(3, None): None}
        rep = report.gather(desc, source="room.max")
        self.assertEqual(rep.summary(), ("INFO", "Imported room.max: 2 objects, 1 mesh, 1 curve, nothing left out."))
        self.assertIn("Objects built: 2, meshes: 1, curves: 1", rep.text().split("\n"))


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
                            issues=[(9, "Mix 'm': its mix curve not converted")], approximated=collections.Counter()),
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
            "Material problems: 7 (listed under Not converted)",
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
                       "7 material problems. See the text MaxDrop Report."))
        self.assertEqual(self.rep.material_problems, 2 + 1 + 2 + 2)  # grey, unsupported, sockets, issues

    def test_material_problems_named_apart(self):
        rep = report.gather(synthetic(), source="room.max", objects_built=6, meshes_built=2, dropped_uv_layers=1)
        report.add_materials(rep, 1, conv_stats=stats(peeled=collections.Counter(),
                                                      unknown=collections.Counter({"FooMtl": 1}), issues=[]))
        self.assertEqual(rep.material_problems, 1)
        self.assertEqual(rep.summary(), (
            "WARNING", "Imported room.max: 6 objects, 2 meshes, 1 material; 2 placeholders, 3 modifiers not applied, "
                       "1 material problem, 4 issues. See the text MaxDrop Report."))
        self.assertIn("Material problems: 1 (listed under Not converted)", rep.text().split("\n"))

    def test_build_issues_are_material_issues(self):
        """The builder's own problems (a texture file found but not loaded) are material issues, not other issues:
        the report is not clean when a material lost its image."""
        rep = report.gather(box(), source="box.max")
        report.add_materials(rep, 1, collections.Counter({"Standard": 1}), lookup=lookup(found=("a.png",)),
                             build_issues=[("Wood", "texture not loaded: a.png (bad header)")])
        lines = rep.text().split("\n")
        self.assertEqual(lines[-4:], ["Material problems: 1 (listed under Not converted)", "Not converted:",
                                      "  Material issues: 1", "    Wood: texture not loaded: a.png (bad header)"])
        self.assertNotIn("Nothing was left out.", lines)
        self.assertEqual(rep.left_out, 1)
        self.assertEqual(rep.summary(), ("WARNING", "Imported box.max: 1 object, 1 mesh, 1 material; "
                                                    "1 material problem. See the text MaxDrop Report."))

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

    def test_maps_drawn_with_blenders_pattern(self):
        """Procedural maps drawn with Blender's own pattern: a third line of the Approximated block, counted in
        approximated; an empty counter adds no line (test_text)."""
        rep = report.gather(box(), source="box.max")
        report.add_materials(rep, 1, {"VRayMtl": 1}, tex_stats=stats(
            peeled=collections.Counter(), unsupported=collections.Counter(), issues=[],
            approximated=collections.Counter({"Noise": 2})))
        self.assertEqual((rep.approximated, dict(rep.maps_approximated)), (2, {"Noise": 2}))
        self.assertEqual(rep.summary(), ("WARNING", "Imported box.max: 1 object, 1 mesh, 1 material; "
                                                    "2 approximated. See the text MaxDrop Report."))
        self.assertEqual(rep.text().split("\n")[-2:], [
            "Approximated:", "  Procedural maps drawn with Blender's own pattern, by class: Noise 2"])
        self.assertFalse(any("Blender's own pattern" in line for line in self.rep.text().split("\n")))

    def test_texmap_stats_start_empty(self):
        self.assertEqual(texmaps.TexmapStats().approximated, collections.Counter())

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

    def test_found_counts_per_rule(self):
        found = lookup(found=["s.png"])
        for rule, names in ((textures.SIBLING, ["a.png", "b.png"]), (textures.USER, ["c.png", "d.png", "e.png"]),
                            (textures.ORIGINAL, ["f.png", "g.png", "h.png", "i.png"])):
            for name in names:
                found.add(name, textures.Found("C:/x/" + name, rule))
        rep = report.gather(box())
        report.add_materials(rep, 0, lookup=found)
        self.assertIn("Textures found: 10 (the scene's folder 1, maps or textures folders 2, texture search folders 3, "
                      "the stored path 4)", rep.text().split("\n"))

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


class TestRun(unittest.TestCase):
    """The text of a run of several files: every report in import order, then a line per file not imported."""

    def test_reports_then_failures(self):
        first, second = report.gather(box(), source="a.max"), report.gather(synthetic(), source="b.max")
        self.assertEqual(report.run_text([first, second], ["junk.max: not a 3ds Max file"]),
                         first.text() + "\n\n" + second.text() + "\n\nNot imported: junk.max: not a 3ds Max file")

    def test_one_report(self):
        rep = report.gather(box(), source="a.max")
        self.assertEqual(report.run_text([rep], []), rep.text())


@unittest.skipIf(numpy is None, "numpy missing")
class TestFixture(unittest.TestCase):
    def test_layers_flags(self):
        desc = conv.read(os.path.join(ROOT, "tests", "fixtures", "layers_flags.max"))
        rep = report.gather(desc, source="layers_flags.max")
        self.assertEqual(rep.summary(), ("WARNING", "Imported layers_flags.max: 8 objects, 7 meshes; 1 issue. See the "
                                                    "text MaxDrop Report."))
        self.assertEqual(rep.text().split("\n")[1:], [
            "Units: millimeters (0.001 m per unit)",
            "Nodes read: 8",
            "Objects built: 8, meshes: 7",
            "Render size: 640 x 480 (not applied: the file has no camera); scene camera: none",
            "Layers: 2 (0 hidden)",
            "Objects hidden: 1, not renderable: 1, frozen: 0",
            "Groups: 1",
            "Not converted:",
            "  Other issues: 1",
            "    FixtureNoReceiveShadow: " + conv.NO_RECEIVE,
        ])


class TestSceneIssues(unittest.TestCase):
    def test_an_issue_of_the_whole_scene_is_labelled_scene(self):
        desc = box()
        desc.issues.append((None, "render: the render size 3 x 450 is out of Blender's range: Blender's is kept"))
        rep = report.gather(desc, source="a.max")
        self.assertIn(("scene", "render: the render size 3 x 450 is out of Blender's range: Blender's is kept"),
                      rep.issues)

    def test_a_scene_level_issue_keeps_its_own_label(self):
        desc = box()
        desc.issues.append((conv.ENVIRONMENT, "light: the environment map is a VRaySky"))
        rep = report.gather(desc, source="a.max")
        self.assertIn(("environment", "light: the environment map is a VRaySky"), rep.issues)
        self.assertFalse([label for label, _r in rep.issues if label.startswith("object ")], rep.issues)


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
