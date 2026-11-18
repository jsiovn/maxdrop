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

    @unittest.skipUnless(WINDOWS, "junctions are a Windows thing")
    def test_rule_4_refuses_a_link_anywhere_in_the_path(self):
        self.touch("real", "sub", "e.jpg")
        link = os.path.join(self.root, "link")
        if not BoundsTest.junction(link, os.path.join(self.root, "real")):
            self.skipTest("cannot create a junction here")
        through = os.path.join(link, "sub", "e.jpg")
        self.assertTrue(os.path.isfile(through))
        self.assertIsNone(self.index(is_local_drive=self.spy(True)).find(through))
        lstat = os.lstat
        seen = []
        with mock.patch.object(textures.os, "lstat", side_effect=lambda p: seen.append(p) or lstat(p)):
            self.assertIsNone(self.index(is_local_drive=self.spy(True)).find(through))
        self.assertEqual(seen[-1], link)  # nothing behind the junction was touched

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

    def test_max_entries_stops_the_walk_and_is_reported_once(self):
        lib, lib2 = os.path.join(self.root, "lib"), os.path.join(self.root, "lib2")
        for n in range(5):
            self.touch("lib", "f%d.png" % n)
        self.touch("lib2", "g.png")
        idx = self.index(user_dirs=[lib, lib2], max_entries=3)
        self.assertIsNotNone(idx.find("f0.png"))
        self.assertIsNone(idx.find("f4.png"))
        self.assertIsNone(idx.find("g.png"))  # the budget is per rule
        self.assertEqual(idx.report.truncated, [(USER, lib, 3)])

    def test_folders_count_against_the_budget(self):
        lib = os.path.join(self.root, "lib")
        for n in range(6):
            os.makedirs(os.path.join(lib, "d%d" % n))
        self.touch("lib", "z", "deep.png")
        idx = self.index(user_dirs=[lib], max_entries=4)
        self.assertIsNone(idx.find("deep.png"))
        self.assertEqual(idx.report.truncated, [(USER, lib, 4)])

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

    def test_a_folder_listing_holds_one_past_the_budget(self):
        names = ["f%d.png" % n for n in (4, 0, 3, 1, 2)]
        for name in names:
            self.touch("lib", name)
        lib = os.path.join(self.root, "lib")
        cut = [e.name for e in textures._entries(lib, 3)]
        # which three depends on the file system's order (name order on NTFS, hash order on ext4)
        self.assertEqual(len(cut), 3)
        self.assertEqual(cut, sorted(cut))
        self.assertLessEqual(set(cut), set(names))
        self.assertEqual([e.name for e in textures._entries(lib, 10)], sorted(names))
        real = textures._entries
        with mock.patch.object(textures, "_entries", side_effect=real) as entries:
            self.index(user_dirs=[lib], max_entries=2).find("x.png")
        self.assertEqual(entries.call_args.args, (lib, 3))


class WorkBoundTest(Tree):
    """The budget bounds the entries read, not only those kept: a huge folder costs no more than the budget."""

    def read(self, idx, *names, under=None):
        """How many directory entries the lookups of names made os.scandir yield (in the folder under and its
        subfolders only, when given)."""
        real, count = os.scandir, [0]

        class Counting:
            def __init__(self, path):
                self._it = real(path)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self._it.close()

            def __iter__(self):
                for e in self._it:
                    if under is None or e.path.startswith(under + os.sep):
                        count[0] += 1
                    yield e

        with mock.patch.object(textures.os, "scandir", Counting):
            for name in names:
                idx.find(name)
        return count[0]

    def test_a_huge_folder_is_read_only_as_far_as_the_budget(self):
        for n in range(40):
            self.touch("lib", "f%02d.png" % n)
        lib = os.path.join(self.root, "lib")
        idx = self.index(user_dirs=[lib], max_entries=5)
        self.assertLessEqual(self.read(idx, "x.png", under=lib), 6)
        self.assertEqual(idx.report.truncated, [(USER, lib, 5)])

    def test_a_rule_reads_at_most_one_past_its_budget(self):
        for n in range(10):
            self.touch("lib", "top%d.png" % n)
            self.touch("lib", "a", "a%d.png" % n)
            self.touch("lib", "b", "b%d.png" % n)
        lib = os.path.join(self.root, "lib")
        idx = self.index(user_dirs=[lib], max_entries=12)
        self.assertLessEqual(self.read(idx, "x.png", under=lib), 13)
        self.assertEqual(len(idx.report.truncated), 1)

    def test_the_sibling_listing_counts(self):
        for n in range(30):
            self.touch("proj", "f%02d.png" % n)
        self.touch("proj", "textures", "t.png")
        proj = os.path.join(self.root, "proj")
        idx = self.index(max_entries=10)
        self.assertLessEqual(self.read(idx, "t.png"), 1 + 11)  # rule 1: the scene's folder, 1 entry
        self.assertIsNone(idx.find("t.png"))
        self.assertEqual(idx.report.truncated, [(SIBLING, proj, 10)])

    def test_a_crowded_parent_does_not_hide_the_scene_folders_maps(self):
        for n in range(50):
            self.touch("proj", "f%02d.png" % n)
        wood = self.touch("proj", "scene", "maps", "wood.jpg")
        proj = os.path.join(self.root, "proj")
        idx = self.index(max_entries=20)
        self.assertEqual(idx.find("wood.jpg"), Found(wood, SIBLING))
        self.assertEqual(idx.report.truncated, [(SIBLING, proj, 20)])

    def test_the_sibling_listing_leaves_less_for_the_walk(self):
        for n in range(3):
            self.touch("proj", "scene", "s%d.png" % n)
        for n in range(6):
            self.touch("proj", "maps", "m%d.png" % n)
        maps = os.path.join(self.root, "proj", "maps")
        # listings: the scene's folder (scene.max + 3) and proj (scene, maps) take 6 of 8: 2 left for maps
        idx = self.index(max_entries=8)
        found = [n for n in range(6) if idx.find("m%d.png" % n)]
        self.assertEqual(len(found), 2, found)
        self.assertEqual(idx.report.truncated, [(SIBLING, maps, 8)])
        idx = self.index(max_entries=100)
        self.assertEqual(idx.find("m5.png"), Found(os.path.join(maps, "m5.png"), SIBLING))
        self.assertEqual(idx.report.truncated, [])


class RefusalTest(Tree):
    REFUSED = (
        r"\\host\share\a.jpg", "//host/share/a.jpg", r"\\?\C:\a.jpg", r"\\.\C:\a.jpg", r"..\..\a.jpg",
        "a.jpg", r"maps\a.jpg", "C:a.jpg", r"C:\x\..\a.jpg", r"C:\a.jpg:stream", r"C:\x\CON", r"C:\x\nul.jpg",
        "C:\\a\x00.jpg", "/home/user/a.jpg", "", "C:\\x\\COM\u00b9.jpg", "C:\\x\\lpt\u00b3")

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

    def test_a_name_found_later_is_no_longer_missing(self):
        r = textures.TextureReport()
        r.add("x.jpg", None)
        r.add("X.JPG", Found("/a/x.jpg", ORIGINAL))
        r.add("x.jpg", None)
        self.assertEqual((r.missing, r.found[ORIGINAL]), ([], 1))

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


class CopiesTest(unittest.TestCase):
    """convert/ does not import the reader or intake/, so these helpers are copies: they must stay equal."""

    def test_base_name_matches_reader_assets(self):
        reader = os.path.join(ROOT, "maxdrop", "reader")
        _load("maxdrop_reader", os.path.join(reader, "__init__.py"), reader)
        assets = _load("maxdrop_reader.assets", os.path.join(reader, "assets.py"))
        for path in ("", "a.jpg", r"C:\x\a.jpg", "C:/x/a.jpg", r"\\host\share\a.jpg", "x/", r"mixed/x\a.jpg", "C:a"):
            with self.subTest(path=path):
                self.assertEqual(textures.base_name(path), assets.base_name(path))

    def test_reserved_names_match_intake_archive(self):
        archive = _load("maxdrop_intake_archive", os.path.join(ROOT, "maxdrop", "intake", "archive.py"))
        self.assertEqual(textures._RESERVED, archive._RESERVED)


if __name__ == "__main__":
    unittest.main()
