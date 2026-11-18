# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""tools/first_open.py: the parts that need no Blender (pixel statistics, issue kinds, the verdict, the log)."""
import importlib.util
import os
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("first_open", os.path.join(ROOT, "tools", "first_open.py"))
first_open = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(first_open)


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
        "image": {"mean_luminance": 0.2, "magenta_share": 0.0},
        "rays": {"quadrants": [1.0, 1.0, 0.95, 0.9]},
        "room_height_m": 2.8,
        "accounting": {"nodes": True, "lights": True, "cameras": True, "modifiers": True, "image_files": True},
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
        self.assertEqual(first_open.issue_kind("texture: D:\\maps\\wood.jpg not loaded"),
                         "texture: <file> not loaded")

    def test_an_apostrophe_is_not_a_quote(self):
        self.assertEqual(first_open.issue_kind("light: the sun's dimming toward the horizon is not imported"),
                         "light: the sun's dimming toward the horizon is not imported")

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
