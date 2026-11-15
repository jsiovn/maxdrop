# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/textures.py on temporary folder trees: each lookup rule, their order, the walk's
bounds, the report, and the stored paths that are never opened (network, device, relative, climbing). No Blender.

    python -I -m unittest discover tests
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name, path, package_dir=None):
    if name in sys.modules:
        return sys.modules[name]
    kw = {"submodule_search_locations": [package_dir]} if package_dir else {}
    spec = importlib.util.spec_from_file_location(name, path, **kw)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_CONVERT = os.path.join(ROOT, "maxdrop", "convert")
_load("maxdrop_convert", os.path.join(_CONVERT, "__init__.py"), _CONVERT)
textures = _load("maxdrop_convert.textures", os.path.join(_CONVERT, "textures.py"))
TextureIndex, Found = textures.TextureIndex, textures.Found
SCENE, SIBLING, USER, ORIGINAL = textures.SCENE, textures.SIBLING, textures.USER, textures.ORIGINAL
WINDOWS = os.name == "nt"


def never_local(path):
    raise AssertionError("is_local_drive called with %r" % path)


class Tree(unittest.TestCase):
    """<root>/proj/scene/scene.max with folders around it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.scene_dir = self.touch("proj", "scene", "scene.max").rsplit(os.sep, 1)[0]
        self.scene = os.path.join(self.scene_dir, "scene.max")
        self.calls = []

    def tearDown(self):
        self._tmp.cleanup()

    def touch(self, *parts):
        path = os.path.join(self.root, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x")
        return path

    def spy(self, answer):
        def local(path):
            self.calls.append(path)
            return answer
        return local

    def index(self, **kw):
        kw.setdefault("is_local_drive", never_local)
        return TextureIndex(self.scene, **kw)


class RuleTest(Tree):
    def test_rule_1_scene_folder_any_case(self):
        a = self.touch("proj", "scene", "Wood.JPG")
        self.assertEqual(self.index().find(r"D:\old\project\wood.jpg"), Found(a, SCENE))

    def test_rule_1_is_flat_without_image_search(self):
        deep = self.touch("proj", "scene", "deep", "f.jpg")
        self.assertIsNone(self.index().find("f.jpg"))
        self.assertEqual(self.index(scene_subfolders=True).find("f.jpg"), Found(deep, SCENE))

    def test_rule_2_maps_beside_the_scene_file(self):
        b = self.touch("proj", "scene", "Maps", "b.png")
        self.assertEqual(self.index().find("b.png"), Found(b, SIBLING))

    def test_rule_2_textures_beside_the_scene_folder_with_subfolders(self):
        c = self.touch("proj", "Textures", "sub", "c.tga")
        self.assertEqual(self.index().find("maps/c.tga"), Found(c, SIBLING))

    def test_rule_2_takes_no_other_folder(self):
        self.touch("proj", "other", "d.png")
        self.touch("maps", "d.png")  # beside the parent: too far
        self.assertIsNone(self.index().find("d.png"))

    def test_rule_3_user_folders_recursive_in_order(self):
        first = self.touch("lib1", "x", "y", "d.exr")
        self.touch("lib2", "d.exr")
        lib1, lib2 = os.path.join(self.root, "lib1"), os.path.join(self.root, "lib2")
        self.assertEqual(self.index(user_dirs=[lib1, lib2]).find("d.exr"), Found(first, USER))
        self.assertEqual(self.index(user_dirs=[lib2, lib1]).find("d.exr").path, os.path.join(lib2, "d.exr"))

    @unittest.skipUnless(WINDOWS, "rule 4 takes drive-letter paths: Windows only")
    def test_rule_4_stored_path_on_a_local_drive(self):
        e = self.touch("elsewhere", "e.jpg")
        self.assertEqual(self.index(is_local_drive=self.spy(True)).find(e), Found(os.path.normpath(e), ORIGINAL))
        self.assertEqual(self.calls, [e])
        self.assertIsNone(self.index(is_local_drive=self.spy(False)).find(e))

    @unittest.skipUnless(WINDOWS, "rule 4 takes drive-letter paths: Windows only")
    def test_rule_4_tries_the_resolved_path_after_the_stored_one(self):
        e = self.touch("elsewhere", "e.jpg")
        found = self.index(is_local_drive=self.spy(True)).find(r"\\host\share\e.jpg", e)
        self.assertEqual(found, Found(os.path.normpath(e), ORIGINAL))
        self.assertEqual(self.calls, [e])

    def test_rule_4_off_windows_never(self):
        if WINDOWS:
            self.skipTest("Windows has drive letters")
        e = self.touch("elsewhere", "e.jpg")
        self.assertIsNone(self.index(is_local_drive=textures.is_local_drive).find(e))

    def test_is_local_drive_of_the_temp_folder(self):
        self.assertEqual(textures.is_local_drive(self.root), WINDOWS)


class OrderTest(Tree):
    def test_scene_folder_before_maps_before_user(self):
        a = self.touch("proj", "scene", "a.jpg")
        self.touch("proj", "scene", "maps", "a.jpg")
        self.touch("lib", "a.jpg")
        idx = self.index(user_dirs=[os.path.join(self.root, "lib")])
        self.assertEqual(idx.find("a.jpg"), Found(a, SCENE))
        b = self.touch("proj", "scene", "maps", "b.jpg")
        self.touch("lib", "b.jpg")
        idx = self.index(user_dirs=[os.path.join(self.root, "lib")])
        self.assertEqual(idx.find("b.jpg"), Found(b, SIBLING))

    def test_nearest_file_wins_inside_a_rule(self):
        self.touch("lib", "a", "a", "n.png")
        near = self.touch("lib", "z", "n.png")
        self.assertEqual(self.index(user_dirs=[os.path.join(self.root, "lib")]).find("n.png").path, near)


class BoundsTest(Tree):
    def test_max_depth(self):
        lib = os.path.join(self.root, "lib")
        one = self.touch("lib", "x", "one.png")
        self.touch("lib", "x", "y", "two.png")
        idx = self.index(user_dirs=[lib], max_depth=1)
        self.assertEqual(idx.find("one.png"), Found(one, USER))
        self.assertIsNone(idx.find("two.png"))

    def test_max_files_stops_the_walk_and_is_reported(self):
        lib = os.path.join(self.root, "lib")
        for n in range(5):
            self.touch("lib", "f%d.png" % n)
        idx = self.index(user_dirs=[lib], max_files=3)
        self.assertIsNotNone(idx.find("f0.png"))
        self.assertIsNone(idx.find("f4.png"))
        self.assertEqual(idx.report.truncated, [(lib, 3)])
        self.assertIn("stopped after 3 files in " + lib, "\n".join(idx.report.lines()))

    def test_each_rule_is_walked_once(self):
        self.touch("proj", "scene", "a.jpg")
        lib = os.path.join(self.root, "lib")
        self.touch("lib", "u.jpg")
        real = os.scandir
        with mock.patch.object(textures.os, "scandir", side_effect=real) as scandir:
            idx = self.index(user_dirs=[lib])
            idx.find("a.jpg")
            self.assertEqual(scandir.call_count, 1)  # rule 1 only: the others are not needed yet
            for name in ("u.jpg", "missing1.jpg", "missing2.jpg", "a.jpg", "u.jpg"):
                idx.find(name)
            walked = scandir.call_count
            idx.find("missing3.jpg")
            self.assertEqual(scandir.call_count, walked)

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlinks")
    def test_links_are_not_followed(self):
        outside = os.path.join(self.root, "outside")
        self.touch("outside", "secret.png")
        lib = os.path.join(self.root, "lib")
        os.makedirs(lib)
        try:
            os.symlink(outside, os.path.join(lib, "link"), target_is_directory=True)
            os.symlink(os.path.join(outside, "secret.png"), os.path.join(lib, "file.png"))
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlinks here")
        idx = self.index(user_dirs=[lib])
        self.assertIsNone(idx.find("secret.png"))
        self.assertIsNone(idx.find("file.png"))

    @unittest.skipUnless(WINDOWS, "junctions are a Windows thing")
    def test_junctions_are_not_entered(self):
        outside = os.path.join(self.root, "outside")
        self.touch("outside", "secret.png")
        lib = os.path.join(self.root, "lib")
        os.makedirs(lib)
        if not self.junction(os.path.join(lib, "junction"), outside):
            self.skipTest("cannot create a junction here")
        self.assertTrue(os.path.isfile(os.path.join(lib, "junction", "secret.png")))
        self.assertIsNone(self.index(user_dirs=[lib]).find("secret.png"))
        self.assertTrue(self.junction(os.path.join(self.scene_dir, "maps"), outside))
        self.assertIsNone(self.index().find("secret.png"))  # a junction named maps is not a maps folder

    @staticmethod
    def junction(link, target):
        return subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

    def test_missing_folders_are_skipped(self):
        idx = self.index(user_dirs=[os.path.join(self.root, "gone")])
        self.assertIsNone(idx.find("a.png"))


class RefusalTest(Tree):
    REFUSED = (
        r"\\host\share\a.jpg", "//host/share/a.jpg", r"\\?\C:\a.jpg", r"\\.\C:\a.jpg", r"..\..\a.jpg",
        "a.jpg", r"maps\a.jpg", "C:a.jpg", r"C:\x\..\a.jpg", r"C:\a.jpg:stream", r"C:\x\CON", r"C:\x\nul.jpg",
        "C:\\a\x00.jpg", "/home/user/a.jpg", "")

    def test_refused_reason(self):
        for path in self.REFUSED:
            with self.subTest(path=path):
                self.assertIsNotNone(textures.refused_reason(path))
        for path in (r"C:\maps\a.jpg", "D:/x/y.png", r"e:\a b\c.tif"):
            with self.subTest(path=path):
                self.assertIsNone(textures.refused_reason(path))

    def test_unc_path_is_never_opened(self):
        self.assertIsNone(self.index().find(r"\\host\share\a.jpg"))

    def test_climbing_path_is_never_followed(self):
        # ..\..\a.jpg from the scene's folder names <root>/a.jpg, which exists
        self.touch("a.jpg")
        self.assertTrue(os.path.isfile(os.path.join(self.scene_dir, "..", "..", "a.jpg")))
        self.assertIsNone(self.index().find(r"..\..\a.jpg"))
        self.assertIsNone(self.index().find("../../a.jpg"))

    def test_device_path_is_never_opened(self):
        target = self.touch("outside", "a.jpg")
        device = "\\\\?\\" + target
        if WINDOWS:
            self.assertTrue(os.path.isfile(device))
        self.assertIsNone(self.index().find(device))
        self.assertIsNone(self.index().find("\\\\.\\" + target))

    def test_the_file_name_of_a_refused_path_is_still_looked_up(self):
        a = self.touch("proj", "scene", "maps", "a.jpg")
        self.assertEqual(self.index().find(r"\\host\share\a.jpg"), Found(a, SIBLING))

    def test_names_that_are_not_file_names(self):
        for name in ("", ".", "..", "C:a.jpg", "a\x01.jpg"):
            with self.subTest(name=name):
                self.assertIsNotNone(textures.name_refused(name))
        self.touch("proj", "scene", "C")
        self.assertIsNone(self.index().find("C:a.jpg"))


class ReportTest(Tree):
    def test_counts_per_rule_and_missing_names(self):
        self.touch("proj", "scene", "a.jpg")
        self.touch("proj", "scene", "maps", "b.jpg")
        self.touch("lib", "c.jpg")
        idx = self.index(user_dirs=[os.path.join(self.root, "lib")], is_local_drive=self.spy(False))
        for path in ("a.jpg", r"D:\x\A.jpg", "b.jpg", "c.jpg", "zz.png", "Gone.tif", "zz.png", r"E:\y\ZZ.png"):
            idx.find(path)
        r = idx.report
        self.assertEqual(r.found, {SCENE: 1, SIBLING: 1, USER: 1, ORIGINAL: 0})
        self.assertEqual(r.missing, ["Gone.tif", "zz.png"])
        lines = r.lines()
        self.assertEqual(lines[0], "Textures found: 3 (the scene's folder 1, maps or textures folders 1, "
                                   "texture search folders 1, the stored path 0)")
        self.assertEqual(lines[1], "Textures not found: 2: Gone.tif, zz.png")

    def test_find_is_cached(self):
        a = self.touch("proj", "scene", "a.jpg")
        idx = self.index()
        self.assertEqual(idx.find("a.jpg"), idx.find("a.jpg"))
        os.remove(a)
        self.assertEqual(idx.find("a.jpg"), Found(a, SCENE))

    def test_empty_name(self):
        idx = self.index()
        self.assertIsNone(idx.find("", ""))
        self.assertEqual(idx.report.missing, ["(no file name)"])


if __name__ == "__main__":
    unittest.main()
