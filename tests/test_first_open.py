# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""tools/first_open.py: the parts that need no Blender (pixel statistics, issue kinds, the verdict, the log)."""
import collections
import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("first_open", os.path.join(ROOT, "tools", "first_open.py"))
first_open = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(first_open)

_PKG = "maxdrop_convert_test"  # as in tests/unit/convert_scene_support.py: maxdrop/__init__.py (and bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
cfb = importlib.import_module(_PKG + ".reader.cfb")
classids = importlib.import_module(_PKG + ".reader.classids")
reader_scene = importlib.import_module(_PKG + ".reader.scene")
chunks = importlib.import_module(_PKG + ".reader.chunks")
convert_scene = importlib.import_module(_PKG + ".convert.scene")
try:
    import numpy
except ImportError:  # the plain tests skip what needs numpy (mesh reading), as tests/unit/test_convert_scene.py does
    numpy = None
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def image(*pixels):
    """A flat RGBA list of the given RGB pixels (alpha 1)."""
    flat = []
    for r, g, b in pixels:
        flat += [r, g, b, 1.0]
    return flat


def passing():
    """A result that passes every check."""
    return {
        "traceback": False, "exit_code": 0,
        "scene_camera": True,
        "image": {"mean_luminance": 0.2, "magenta_share": 0.0, "lights_off_mean_luminance": 0.05},
        "rays": {"quadrants": [1.0, 1.0, 0.95, 0.9]},
        "room_height_m": 2.8,
        "accounting": {"nodes": True, "lights": True, "cameras": True, "modifiers": True, "textures": True},
    }


class ImageStats(unittest.TestCase):
    def test_black(self):
        stats = first_open.image_stats(image((0, 0, 0), (0, 0, 0)), 2, 1)
        self.assertEqual(stats["mean_luminance"], 0.0)
        self.assertEqual(stats["lit_share"], 0.0)
        self.assertEqual(stats["magenta_share"], 0.0)

    def test_half_magenta(self):
        stats = first_open.image_stats(image((1, 0, 1), (0.3, 0.02, 0.28), (0.5, 0.5, 0.5), (0.2, 0.2, 0.2)), 2, 2)
        self.assertEqual(stats["magenta_share"], 0.5)

    def test_purple_grey_and_dark_are_not_magenta(self):
        stats = first_open.image_stats(image((0.5, 0.4, 0.5), (0.05, 0.0, 0.05), (0.6, 0.0, 0.2)), 3, 1)
        self.assertEqual(stats["magenta_share"], 0.0)

    def test_luminance_uses_rec709_weights(self):
        stats = first_open.image_stats(image((1, 0, 0), (0, 1, 0), (0, 0, 1)), 3, 1)
        self.assertAlmostEqual(stats["mean_luminance"], (0.2126 + 0.7152 + 0.0722) / 3, places=4)

    def test_size_mismatch_is_refused(self):
        with self.assertRaises(ValueError):
            first_open.image_stats(image((0, 0, 0)), 2, 1)


class IssueKind(unittest.TestCase):
    def test_names_and_numbers_go(self):
        self.assertEqual(first_open.issue_kind("VRayBitmap 'wall.jpg': multiplier 2.5 not converted: 1"),
                         "VRayBitmap <name>: multiplier N not converted")

    def test_double_quotes_and_negative_numbers(self):
        self.assertEqual(first_open.issue_kind('light: decay "Inverse" at -12 m'), "light: decay <name> at N m")

    def test_plain_reason_keeps_its_words(self):
        self.assertEqual(first_open.issue_kind("camera: depth of field not imported"),
                         "camera: depth of field not imported")

    def test_unquoted_file_names_go(self):
        self.assertEqual(first_open.issue_kind("light: its photometric web Lamp-01_x.IES is a spot of 120 degrees"),
                         "light: its photometric web <file> is a spot of N degrees")
        self.assertEqual(first_open.issue_kind("light: web D:\\maps\\lamp.ies not read"),
                         "light: web <file> not read")

    def test_an_apostrophe_is_not_a_quote(self):
        self.assertEqual(first_open.issue_kind("light: the sun's dimming toward the horizon is not imported"),
                         "light: the sun's dimming toward the horizon is not imported")

    def test_a_bare_material_name_goes(self):
        self.assertEqual(first_open.issue_kind("Oak_Floor_X: no sub-material"), "<name>: no sub-material")
        self.assertEqual(first_open.issue_kind("Standard: shader 3 has no rule: its defaults"),
                         "<name>: shader N has no rule")

    def test_topics_stay(self):
        self.assertEqual(first_open.issue_kind("uvw map: a UVW Map above Edit Mesh is not evaluated"),
                         "uvw map: a UVW Map above Edit Mesh is not evaluated")
        self.assertEqual(first_open.issue_kind("map 12: graph cut"), "map N: graph cut")
        self.assertEqual(first_open.issue_kind("texture not loaded: wood.jpg (no image data)"),
                         "texture not loaded: <file> (no image data)")

    def test_a_texture_not_loaded_hides_any_file_name(self):
        self.assertEqual(first_open.issue_kind("texture not loaded: wall_diffuse.webp (no image data)"),
                         "texture not loaded: <file> (no image data)")
        self.assertEqual(first_open.issue_kind("texture not loaded: Wall Diffuse (cannot read)"),
                         "texture not loaded: <file> (cannot read)")

    def test_not_built_keeps_its_reason(self):
        self.assertEqual(first_open.issue_kind("light: not built: VRayLight mesh lights are not imported yet"),
                         "light: not built: VRayLight mesh lights are not imported yet")

    def test_a_reason_without_a_colon_stays(self):
        self.assertEqual(first_open.issue_kind("2 faces with a repeated vertex or doubled, left out"),
                         "N faces with a repeated vertex or doubled, left out")

    def test_a_file_named_after_a_colon_is_cut(self):
        self.assertEqual(first_open.issue_kind("light: IES file not imported: C:/maps/lamp.ies"),
                         "light: IES file not imported")


class Verdict(unittest.TestCase):
    def test_everything_passes(self):
        verdict = first_open.verdict(passing())
        self.assertEqual(set(verdict), {"traceback", "magenta", "lit", "closed", "scale", "report", "passed"})
        self.assertTrue(all(verdict.values()), verdict)

    def check_fails(self, key, **change):
        result = passing()
        for name, value in change.items():
            path = name.split("__")
            target = result
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
        verdict = first_open.verdict(result)
        self.assertFalse(verdict[key], verdict)
        self.assertFalse(verdict["passed"])

    def test_a_traceback_fails(self):
        self.check_fails("traceback", traceback=True)

    def test_a_failed_blender_fails(self):
        self.check_fails("traceback", exit_code=1)

    def test_magenta_above_the_limit_fails(self):
        self.check_fails("magenta", image__magenta_share=first_open.MAGENTA_MAX * 2)

    def test_a_dark_image_fails(self):
        self.check_fails("lit", image__mean_luminance=first_open.LIT_MEAN_MIN / 2)

    def test_light_from_emissive_materials_alone_fails(self):
        self.check_fails("lit", image__lights_off_mean_luminance=0.15)

    def test_no_lights_fails_lit(self):
        self.check_fails("lit", image__lights_off_mean_luminance=None)

    def test_an_open_quadrant_fails(self):
        self.check_fails("closed", rays__quadrants=[1.0, 1.0, 1.0, first_open.CLOSED_MIN - 0.01])

    def test_no_camera_fails_closed_and_scale(self):
        result = passing()
        result.update(scene_camera=False, rays=None, room_height_m=None)
        verdict = first_open.verdict(result)
        self.assertFalse(verdict["closed"])
        self.assertFalse(verdict["scale"])

    def test_a_room_out_of_range_fails(self):
        self.check_fails("scale", room_height_m=first_open.HEIGHT[1] + 0.1)
        self.check_fails("scale", room_height_m=first_open.HEIGHT[0] - 0.1)

    def test_an_unaccounted_light_fails(self):
        self.check_fails("report", accounting__lights=False)

    def test_no_image_fails_magenta_and_lit(self):
        result = passing()
        result["image"] = None
        verdict = first_open.verdict(result)
        self.assertFalse(verdict["magenta"])
        self.assertFalse(verdict["lit"])


def report(**fields):
    """A stand-in for convert.report.Report with the fields accounting() reads."""
    rep = types.SimpleNamespace(nodes=10, objects_built=10, issues=[], material_issues=[], textures_missing=[],
                                placeholders=collections.Counter(), modifiers=collections.Counter(),
                                modifiers_applied=collections.Counter(), modifiers_converted=collections.Counter())
    for name, value in fields.items():
        setattr(rep, name, value)
    return rep


CENSUS = {"nodes": 10, "light_nodes": 3, "camera_nodes": 1, "light_classes": ["VRayLight", "Omni"],
          "camera_classes": ["Targetcamera"], "modifier_nodes_by_class": {"UVW Map": 2, "Edit Mesh": 1}}
MODIFIERS = dict(modifiers_applied=collections.Counter({"UVW Map": 1}),
                 modifiers=collections.Counter({"UVW Map": 1, "Edit Mesh": 1}))
TYPES = {"LIGHT": 3, "CAMERA": 1, "MESH": 6}


class Accounting(unittest.TestCase):
    def checks(self, rep, census=CENSUS, kinds=TYPES, missing_files=0):
        return first_open.accounting(rep, census, kinds, missing_files)[0]

    def test_everything_accounted(self):
        self.assertTrue(all(self.checks(report(**MODIFIERS)).values()))

    def test_a_light_not_built_still_balances(self):
        rep = report(issues=[("lamp", "light: not built: mesh lights are not imported yet")], **MODIFIERS)
        checks, counters = first_open.accounting(rep, CENSUS, dict(TYPES, LIGHT=2), 0)
        self.assertTrue(checks["lights"])
        self.assertEqual(counters["lights_not_built"], 1)

    def test_a_light_placeholder_still_balances(self):
        rep = report(placeholders=collections.Counter({"Omni": 1}), **MODIFIERS)
        self.assertTrue(self.checks(rep, kinds=dict(TYPES, LIGHT=2))["lights"])

    def test_a_light_dropped_fails(self):
        self.assertFalse(self.checks(report(**MODIFIERS), kinds=dict(TYPES, LIGHT=2))["lights"])

    def test_a_camera_dropped_fails(self):
        self.assertFalse(self.checks(report(**MODIFIERS), kinds=dict(TYPES, CAMERA=0))["cameras"])

    def test_a_modifier_class_in_no_counter_fails(self):
        rep = report(modifiers_applied=collections.Counter({"UVW Map": 2}))
        self.assertFalse(self.checks(rep)["modifiers"])

    def test_a_node_not_built_fails(self):
        self.assertFalse(self.checks(report(objects_built=9, **MODIFIERS))["nodes"])
        self.assertFalse(self.checks(report(**MODIFIERS), census=dict(CENSUS, nodes=11))["nodes"])

    def test_textures_not_found_or_not_loaded_fail(self):
        self.assertFalse(self.checks(report(textures_missing=["a.jpg"], **MODIFIERS))["textures"])
        rep = report(material_issues=[("wood", "texture not loaded: a.jpg (no image data)")], **MODIFIERS)
        self.assertFalse(self.checks(rep)["textures"])
        self.assertFalse(self.checks(report(**MODIFIERS), missing_files=1)["textures"])


@unittest.skipIf(numpy is None, "numpy is not installed: convert.scene.read needs it")
class FileCensus(unittest.TestCase):
    """The census reads the file again; on the fixtures it agrees with the scene description MaxDrop builds from."""

    def census(self, name):
        path = os.path.join(FIXTURES, name)
        return first_open.file_census(path, cfb, classids, reader_scene, chunks.ChunkError), \
            convert_scene.read(path)

    def test_lights(self):
        census, desc = self.census("lights_standard.max")
        self.assertEqual(census["nodes"], len(desc.nodes))
        self.assertGreater(census["light_nodes"], 0)
        built = sum(1 for n in desc.nodes if n.kind == convert_scene.LIGHT)
        not_built = sum(1 for _i, reason in desc.issues if reason.startswith("light: not built"))
        placed = sum(desc.placeholders.get(c, 0) for c in census["light_classes"])
        self.assertEqual(census["light_nodes"], built + not_built + placed)

    def test_cameras(self):
        census, desc = self.census("cameras.max")
        self.assertGreater(census["camera_nodes"], 0)
        self.assertEqual(census["camera_nodes"], sum(1 for n in desc.nodes if n.kind == convert_scene.CAMERA))

    def test_modifiers(self):
        census, desc = self.census("stack_basic.max")
        expected = collections.Counter()
        for node in desc.nodes:
            expected.update(set(node.modifiers) | set(node.applied) | {m.class_name for m in node.converted})
        self.assertTrue(census["modifier_nodes_by_class"])
        self.assertEqual(census["modifier_nodes_by_class"], dict(expected))


class ReadLog(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)

    def read(self, *lines):
        path = os.path.join(self.folder, "run.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(line + "\n" for line in lines))
        return first_open.read_log(path)

    def test_traceback_found(self):
        self.assertTrue(self.read("MaxDrop: materials of x.max not converted:", "Traceback (most recent call last):",
                                  '  File "x.py", line 1', "ValueError: bad"))

    def test_clean_log(self):
        self.assertFalse(self.read("MaxDrop: Imported x.max: 3 objects, 2 meshes, nothing left out."))

    def test_missing_log(self):
        self.assertFalse(first_open.read_log(os.path.join(self.folder, "none.log")))


class SafeLabel(unittest.TestCase):
    def test_label_becomes_a_file_name(self):
        self.assertEqual(first_open.safe_label("scene A"), "scene-A")
        self.assertEqual(first_open.safe_label("a/b\\c:d"), "a-b-c-d")


if __name__ == "__main__":
    unittest.main()
