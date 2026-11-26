# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/intake/archive/ on pack folders: the destination search, the entry count, links,
stale staging folders and races between unpacks, no Blender, no network.

    python -I -m unittest discover tests
"""
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

_TESTS = "maxdrop_tests"  # tests/ as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_tests.intake_support import (  # noqa: E402 (after the loader)
    archive, Base, files_under, junction, PackError, patching, read, set_declared_count, to_zip64,
    write,
)


class Destination(Base):
    def test_reuse_through_the_marker(self):
        path = self.pack([("room.max", b"MAX"), ("wood.jpg", b"J")])
        first = archive.unpack(path, dest_parent=self.out)
        stamp = os.stat(first.max_path).st_mtime_ns
        second = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((second.mode, second.folder, second.max_path, second.written, second.reused),
                         ("reused", first.folder, first.max_path, 0, 2))
        self.assertEqual(os.stat(first.max_path).st_mtime_ns, stamp)

    def test_a_changed_archive_is_not_reused(self):
        path = self.pack([("room.max", b"MAX")])
        first = archive.unpack(path, dest_parent=self.out)
        self.pack([("room.max", b"MAX2"), ("wood.jpg", b"J")])
        second = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(second.folder, os.path.join(self.out, "pack (2)"))
        self.assertEqual(read(first.max_path), b"MAX")

    def test_a_folder_without_marker_is_left_untouched(self):
        path = self.pack([("room.max", b"MAX"), ("wood.jpg", b"J")])
        mine = os.path.join(self.out, "pack")
        os.makedirs(os.path.join(mine, "sub"))
        with open(os.path.join(mine, "wood.jpg"), "wb") as f:
            f.write(b"user's own")
        before = files_under(mine)
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("unpacked", os.path.join(self.out, "pack (2)")))
        self.assertEqual(files_under(mine), before)
        self.assertEqual(read(os.path.join(mine, "wood.jpg")), b"user's own")
        self.assertEqual(sorted(os.listdir(mine)), ["sub", "wood.jpg"])

    def test_a_copy_the_user_extracted_is_used_in_place(self):
        path = self.pack([("Pack/room.max", b"MAX"), ("Pack/wood.jpg", b"J")])
        mine = os.path.join(self.out, "pack", "Pack")
        os.makedirs(mine)
        with open(os.path.join(mine, "ROOM.max"), "wb") as f:
            f.write(b"theirs")
        before = files_under(self.tmp)
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((r.mode, r.max_path, r.folder, r.written),
                         ("in_place", os.path.join(mine, "ROOM.max"), mine, 0))
        self.assertEqual(files_under(self.tmp), before)

    def test_a_copy_too_deep_is_not_searched(self):
        path = self.pack([("room.max", b"MAX")])
        deep = os.path.join(self.out, "pack", "a", "b", "c", "d")
        os.makedirs(deep)
        write(os.path.join(deep, "room.max"))
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("unpacked", os.path.join(self.out, "pack (2)")))

    def test_several_scenes_and_a_user_folder(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2")])
        mine = os.path.join(self.out, "pack")
        os.makedirs(mine)
        write(os.path.join(mine, "notes.txt"))
        r = archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertEqual(r.folder, os.path.join(self.out, "pack (2)", "two"))
        self.assertEqual(os.listdir(mine), ["notes.txt"])
        write(os.path.join(mine, "one.max"))
        r = archive.unpack(path, "one.max", dest_parent=self.out)
        self.assertEqual((r.mode, r.max_path), ("in_place", os.path.join(mine, "one.max")))

    def test_preview_says_what_unpack_will_use(self):
        path = self.pack([("Pack/room.max", b"MAX"), ("Pack/wood.jpg", b"J")])
        before = files_under(self.tmp)
        self.assertEqual(archive.preview(path, "Pack/room.max", False, self.out),
                         ("unpacked", os.path.join(self.out, "pack", "room.max")))
        self.assertEqual(files_under(self.tmp), before)
        mine = os.path.join(self.out, "pack", "Pack")
        os.makedirs(mine)
        write(os.path.join(mine, "room.max"))
        self.assertEqual(archive.preview(path, "Pack/room.max", False, self.out),
                         ("in_place", os.path.join(mine, "room.max")))
        shutil.rmtree(os.path.join(self.out, "pack"))
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(archive.preview(path, "Pack/room.max", False, self.out), ("reused", r.max_path))
        self.assertIsNone(archive.preview(os.path.join(self.tmp, "gone.zip"), "room.max", False, self.out))

    def test_preview_of_one_scene_among_several(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2")])
        self.assertEqual(archive.preview(path, "two.max", True, self.out),
                         ("unpacked", os.path.join(self.out, "pack", "two", "two.max")))
        r = archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertEqual(archive.preview(path, "two.max", True, self.out), ("reused", r.max_path))
        self.assertEqual(archive.preview(path, "one.max", True, self.out),
                         ("unpacked", os.path.join(self.out, "pack", "one", "one.max")))

    def assert_no_free_folder(self, path, scene, several):
        """Every candidate name is a folder of someone else's: preview() raises with the message unpack() refuses
        with, and neither writes anything."""
        for name in ("pack", "pack (2)", "pack (3)"):
            os.mkdir(os.path.join(self.out, name))
            write(os.path.join(self.out, name, "notes.txt"))
        with patching.patch_all(archive, "_CANDIDATES", 3):
            before = files_under(self.tmp)
            with self.assertRaisesRegex(PackError, "No free folder for pack.zip") as previewed:
                archive.preview(path, scene, several, self.out)
            self.assert_clean(before)
            with self.assertRaises(PackError) as unpacked:
                archive.unpack(path, scene, dest_parent=self.out)
            self.assert_clean(before)
        self.assertEqual(str(previewed.exception), str(unpacked.exception))

    def test_preview_says_no_folder_is_free(self):
        self.assert_no_free_folder(self.pack([("room.max", b"MAX")]), "room.max", False)

    def test_preview_of_one_of_several_says_no_folder_is_free(self):
        self.assert_no_free_folder(self.pack([("one.max", b"1"), ("two.max", b"2")]), "two.max", True)

    def test_preview_says_no_folder_is_free_inside_the_pack_folder(self):
        """The pack folder is this pack's (its marker matches), but every name for the scene's sub-folder is
        taken."""
        path = self.pack([("one.max", b"1"), ("two.max", b"2")])
        archive.unpack(path, "two.max", dest_parent=self.out)
        os.mkdir(os.path.join(self.out, "pack", "one"))
        write(os.path.join(self.out, "pack", "one", "notes.txt"))
        with patching.patch_all(archive, "_CANDIDATES", 1):
            before = files_under(self.tmp)
            with self.assertRaisesRegex(PackError, "No free folder for pack.zip") as previewed:
                archive.preview(path, "one.max", True, self.out)
            with self.assertRaises(PackError) as unpacked:
                archive.unpack(path, "one.max", dest_parent=self.out)
            self.assert_clean(before)
        self.assertEqual(str(previewed.exception), str(unpacked.exception))

    def assert_preview_is_unpack(self, path, scene, several, expected):
        """preview() names expected, writes nothing, and unpack() then does exactly that."""
        before = files_under(self.tmp)
        found = archive.preview(path, scene, several, self.out)
        self.assertEqual(files_under(self.tmp), before)
        r = archive.unpack(path, scene, dest_parent=self.out)
        self.assertEqual(found, (r.mode, r.max_path))
        self.assertEqual(found, expected)

    def test_preview_equals_unpack_with_one_scene(self):
        path = self.pack([("room.max", b"MAX"), ("wood.jpg", b"J")])
        free = os.path.join(self.out, "pack", "room.max")
        self.assert_preview_is_unpack(path, "room.max", False, ("unpacked", free))
        self.assert_preview_is_unpack(path, "room.max", False, ("reused", free))
        shutil.rmtree(os.path.join(self.out, "pack"))
        os.makedirs(os.path.join(self.out, "pack"))
        write(os.path.join(self.out, "pack", "notes.txt"))
        self.assert_preview_is_unpack(path, "room.max", False,
                                      ("unpacked", os.path.join(self.out, "pack (2)", "room.max")))
        mine = os.path.join(self.out, "pack", "by hand")
        os.makedirs(mine)
        write(os.path.join(mine, "room.max"))
        self.assert_preview_is_unpack(path, "room.max", False, ("in_place", os.path.join(mine, "room.max")))

    def test_preview_equals_unpack_with_several_scenes(self):
        path = self.pack([("one/one.max", b"1"), ("two/two.max", b"2")])
        self.assert_preview_is_unpack(path, "two/two.max", True,
                                      ("unpacked", os.path.join(self.out, "pack", "two", "two.max")))
        self.assert_preview_is_unpack(path, "one/one.max", True,
                                      ("unpacked", os.path.join(self.out, "pack", "one", "one.max")))
        self.assert_preview_is_unpack(path, "one/one.max", True,
                                      ("reused", os.path.join(self.out, "pack", "one", "one.max")))
        shutil.rmtree(os.path.join(self.out, "pack"))
        os.makedirs(os.path.join(self.out, "pack"))
        write(os.path.join(self.out, "pack", "notes.txt"))
        self.assert_preview_is_unpack(path, "two/two.max", True,
                                      ("unpacked", os.path.join(self.out, "pack (2)", "two", "two.max")))

    def test_unsafe_archive_or_scene_stem_falls_back(self):
        path = self.pack([("a/CON .max", b"x"), ("good.max", b"1"), ("b/end..max", b"2")], name="pack.zip")
        r = archive.unpack(path, "good.max", dest_parent=self.out)
        self.assertEqual(r.folder, os.path.join(self.out, "pack", "good"))
        self.assertEqual(archive._safe_stem("end..max", "scene"), "scene")
        self.assertEqual(archive._safe_stem("CON.zip", "pack"), "pack")


THREE = [("room.max", b"MAX"), ("wood.jpg", b"W"), ("stone.png", b"S")]


class EntryCount(Base):
    """The entry count comes from the end records, before ZipFile builds the whole directory."""

    def assert_refused_unparsed(self, path, limit=2):
        limits = archive.Limits(entries=limit)
        message = "lists more than the %d entries" % limit
        before = files_under(self.tmp)
        with mock.patch.object(archive.ZipBackend, "_open", side_effect=AssertionError("ZipFile parsed it")):
            with self.assertRaisesRegex(PackError, message):
                archive.list_pack(path, limits=limits)
            with self.assertRaisesRegex(PackError, message):
                archive.unpack(path, dest_parent=self.out, limits=limits)
        self.assert_clean(before)

    def test_the_declared_count(self):
        path = self.pack(THREE)
        self.assertEqual(archive._zip_entry_count(path, 100), 3)
        self.assert_refused_unparsed(path)
        self.assertEqual(archive.list_pack(path, limits=archive.Limits(entries=3)).scenes, ["room.max"])

    def test_a_lying_count_is_counted_record_by_record(self):
        path = self.pack(THREE)
        set_declared_count(path, 1)
        self.assertEqual(len(archive.ZipBackend().names(path)), 3)  # zipfile reads all three anyway
        self.assert_refused_unparsed(path)

    def test_data_before_the_archive(self):
        # A self-extractor: kind() does not take it (its magic is not a zip's), the count still holds.
        path = self.pack(THREE)
        set_declared_count(path, 1)
        write(path, b"MZ" + b"\0" * 1000 + read(path))
        self.assertEqual(len(archive.ZipBackend().names(path)), 3)
        self.assertEqual(archive._zip_entry_count(path, 2), 3)

    def test_zip64_end_records(self):
        path = self.pack(THREE)
        to_zip64(path)
        self.assertEqual(archive.list_pack(path).scenes, ["room.max"])
        self.assertEqual(archive._zip_entry_count(path, 100), 3)
        self.assert_refused_unparsed(path)
        lying = self.pack(THREE, name="lying.zip")
        to_zip64(lying, declared=1)
        self.assertEqual(len(archive.ZipBackend().names(lying)), 3)
        self.assert_refused_unparsed(lying)

    def test_counting_stops_above_the_cap(self):
        path = self.pack([("f%d.jpg" % i, b"") for i in range(50)])
        set_declared_count(path, 1)
        self.assertEqual(archive._zip_entry_count(path, 10), 11)
        self.assertEqual(archive._zip_entry_count(path, 100), 50)

    def test_without_an_end_record_zipfile_says_what_is_wrong(self):
        path = os.path.join(self.tmp, "broken.zip")
        write(path, b"PK\x03\x04" + b"\0" * 100)
        self.assertEqual(archive._zip_entry_count(path, 10), 0)
        with self.assertRaisesRegex(PackError, "not a readable .zip"):
            archive.list_pack(path)


class Links(Base):
    """A link or a junction at a candidate folder or below it is never followed."""

    def elsewhere(self):
        folder = os.path.join(self.tmp, "elsewhere")
        os.mkdir(folder)
        write(os.path.join(folder, "room.max"), b"theirs")
        return folder

    def link(self, target, link):
        junction(target, link)
        self.addCleanup(os.rmdir, link)  # removes the junction, not what it points to
        self.assertTrue(archive._is_link(link))

    def test_a_junction_at_the_destination_is_not_used(self):
        path = self.pack([("room.max", b"MAX")])
        target = self.elsewhere()
        self.link(target, os.path.join(self.out, "pack"))
        self.assertEqual(archive.preview(path, "room.max", False, self.out),
                         ("unpacked", os.path.join(self.out, "pack (2)", "room.max")))
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("unpacked", os.path.join(self.out, "pack (2)")))
        self.assertEqual(os.listdir(target), ["room.max"])

    def test_a_junction_below_a_candidate_is_not_searched(self):
        path = self.pack([("room.max", b"MAX")])
        target = self.elsewhere()
        mine = os.path.join(self.out, "pack")
        os.mkdir(mine)
        self.link(target, os.path.join(mine, "sub"))
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("unpacked", os.path.join(self.out, "pack (2)")))

    def test_a_junction_as_the_pack_folder_of_several_scenes(self):
        path = self.pack([("one.max", b"1"), ("room.max", b"2")])
        target = self.elsewhere()
        self.link(target, os.path.join(self.out, "pack"))
        r = archive.unpack(path, "room.max", dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("unpacked", os.path.join(self.out, "pack (2)", "room")))

    def test_a_symbolic_link(self):
        target = self.elsewhere()
        link = os.path.join(self.out, "pack")
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError) as e:
            self.skipTest("cannot create a symbolic link here (%s)" % e)
        self.addCleanup(os.remove if os.name != "nt" else os.rmdir, link)
        self.assertTrue(archive._is_link(link))
        r = archive.unpack(self.pack([("room.max", b"MAX")]), dest_parent=self.out)
        self.assertEqual(r.folder, os.path.join(self.out, "pack (2)"))

    def test_plain_folders_and_files_are_not_links(self):
        self.assertFalse(archive._is_link(self.out))
        self.assertFalse(archive._is_link(self.pack([("room.max", b"MAX")])))
        self.assertFalse(archive._is_link(os.path.join(self.tmp, "missing")))


class StaleStaging(Base):
    """Staging folders an interrupted unpack left behind are removed by the next unpack into that folder."""

    OLD = 7 * 3600

    def aged(self, path):
        then = time.time() - self.OLD
        os.utime(path, (then, then))
        return os.path.basename(path)

    def test_only_old_staging_folders_are_removed(self):
        prefix = archive.STAGING_PREFIX
        stale = os.path.join(self.out, prefix + "old")
        os.makedirs(os.path.join(stale, "sub"))
        write(os.path.join(stale, "room.max"), b"half")
        self.aged(stale)
        fresh = os.path.join(self.out, prefix + "new")
        os.mkdir(fresh)
        write(os.path.join(fresh, "room.max"), b"running")
        keep = os.path.join(self.out, "keep-old")
        os.mkdir(keep)
        self.aged(keep)
        a_file = os.path.join(self.out, prefix + "file")
        write(a_file, b"not a folder")
        self.aged(a_file)
        r = archive.unpack(self.pack([("room.max", b"MAX")]), dest_parent=self.out)
        self.assertEqual(self.listing(self.out), sorted([prefix + "new", "keep-old", prefix + "file", "pack"]))
        self.assertEqual(r.folder, os.path.join(self.out, "pack"))
        self.assertEqual(os.listdir(fresh), ["room.max"])

    def test_every_unpack_of_several_scenes_cleans_beside_the_pack_folder(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2")])
        archive.unpack(path, "one.max", dest_parent=self.out)
        # A pack folder a crash left under its staging name (holding the pack marker), once the folder exists.
        beside = os.path.join(self.out, archive.STAGING_PREFIX + "new-beside")
        os.mkdir(beside)
        write(os.path.join(beside, archive.MARKER), b"{}")
        self.aged(beside)
        inside_pack = os.path.join(self.out, "pack", archive.STAGING_PREFIX + "inside")
        os.mkdir(inside_pack)
        self.aged(inside_pack)
        elsewhere = os.path.join(self.tmp, archive.STAGING_PREFIX + "elsewhere")
        os.mkdir(elsewhere)
        self.aged(elsewhere)
        archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertFalse(os.path.lexists(beside))
        self.assertFalse(os.path.lexists(inside_pack))
        self.assertTrue(os.path.isdir(elsewhere))
        self.assertEqual(self.listing(self.out), ["pack"])

    def test_a_linked_staging_folder_is_not_followed(self):
        target = os.path.join(self.tmp, "target")
        os.mkdir(target)
        write(os.path.join(target, "keep.jpg"), b"K")
        link = os.path.join(self.out, archive.STAGING_PREFIX + "link")
        junction(target, link)
        self.addCleanup(os.rmdir, link)
        stale = os.path.join(self.out, archive.STAGING_PREFIX + "old")
        os.mkdir(stale)
        with patching.patch_all(archive, "_STALE_SECONDS", -60):  # everything counts as old
            archive._remove_stale_staging(self.out, archive.Limits(seconds=-60))
        self.assertFalse(os.path.lexists(stale))
        self.assertTrue(archive._is_link(link))
        self.assertEqual(os.listdir(target), ["keep.jpg"])


class Race(Base):
    """Two unpacks of one pack at once: the later one takes the next folder name, never an existing folder."""

    def racing_backend(self, folder, user_file):
        class Racer(archive.ZipBackend):
            def extract(self, path, wanted, staging, budget):
                super().extract(path, wanted, staging, budget)
                if not os.path.lexists(folder):
                    os.mkdir(folder)
                    if user_file:
                        write(os.path.join(folder, "notes.txt"), b"mine")
        self.addCleanup(archive._BACKENDS.__setitem__, "zip", archive._BACKENDS["zip"])
        archive._BACKENDS["zip"] = Racer()

    def test_a_folder_made_during_the_unpack_is_left_alone(self):
        for user_file in (False, True):
            with self.subTest(user_file=user_file):
                out = tempfile.mkdtemp(dir=self.tmp)
                path = self.pack([("room.max", b"MAX"), ("wood.jpg", b"W")])
                self.racing_backend(os.path.join(out, "pack"), user_file)
                r = archive.unpack(path, dest_parent=out)
                self.assertEqual((r.mode, r.folder), ("unpacked", os.path.join(out, "pack (2)")))
                self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "wood.jpg"]))
                self.assertEqual(os.listdir(os.path.join(out, "pack")), ["notes.txt"] if user_file else [])
                self.assertEqual(self.listing(out), ["pack", "pack (2)"])

    def test_a_pack_folder_made_first_by_someone_else(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2")])
        real, calls = archive._destination, []

        def racing(*args):
            found = real(*args)
            if not calls:
                os.mkdir(os.path.join(self.out, "pack"))
            calls.append(found[0])
            return found
        with patching.patch_all(archive, "_destination", racing):
            r = archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertEqual(r.folder, os.path.join(self.out, "pack (2)", "two"))
        self.assertEqual(calls, ["free", "free"])
        self.assertEqual(os.listdir(os.path.join(self.out, "pack")), [])

    def test_the_same_scene_unpacked_first_by_another_unpack_is_reused(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2")])
        real, done = archive._destination, []

        def racing(*args):
            found = real(*args)
            if not done:
                done.append(None)
                done[0] = archive.unpack(path, "two.max", dest_parent=self.out)
            return found
        with patching.patch_all(archive, "_destination", racing):
            r = archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertEqual((done[0].mode, r.mode, r.folder), ("unpacked", "reused", done[0].folder))
        self.assertEqual(self.listing(os.path.join(self.out, "pack")), sorted([archive.MARKER, "two"]))

    def test_the_marker_comes_last_and_a_failed_move_leaves_nothing(self):
        path = self.pack([("room.max", b"MAX"), ("wood.jpg", b"W"), ("stone.png", b"S")])
        real, moved = os.rename, []

        def failing(src, dst):
            if os.path.isdir(src):  # the destination, renamed into place holding its reservation
                return real(src, dst)
            moved.append(os.path.basename(dst))
            if len(moved) == 3:
                raise OSError("disk gone")
            return real(src, dst)
        before = files_under(self.tmp)
        with mock.patch.object(archive.os, "rename", failing):
            with self.assertRaisesRegex(PackError, "disk gone"):
                archive.unpack(path, dest_parent=self.out)
        self.assert_clean(before)
        self.assertEqual(os.listdir(self.out), [])
        self.assertEqual(moved, ["wood.jpg", "stone.png", "room.max"])

    def test_a_pack_folder_that_cannot_be_made(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2")])
        before = files_under(self.tmp)
        with mock.patch.object(archive.os, "mkdir", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(PackError, "Could not unpack pack.zip into .*denied"):
                archive.unpack(path, "two.max", dest_parent=self.out)
        self.assert_clean(before)

    def test_a_failure_keeps_the_pack_folder_once_another_scene_is_in_it(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2")])
        out = self.out

        class Failing(archive.ZipBackend):
            def extract(self, path, wanted, staging, budget):
                # Another unpack of this pack finishes the first scene meanwhile.
                archive._BACKENDS["zip"] = archive.ZipBackend()
                archive.unpack(path, "one.max", dest_parent=out)
                raise PackError("disk gone")
        self.addCleanup(archive._BACKENDS.__setitem__, "zip", archive._BACKENDS["zip"])
        archive._BACKENDS["zip"] = Failing()
        with self.assertRaisesRegex(PackError, "disk gone"):
            archive.unpack(path, "two.max", dest_parent=self.out)
        top = os.path.join(self.out, "pack")
        self.assertEqual(self.listing(top), sorted([archive.MARKER, "one"]))
        self.assertEqual(self.listing(os.path.join(top, "one")), sorted([archive.MARKER, "one.max"]))

    def test_no_free_name_left(self):
        path = self.pack([("room.max", b"MAX")])
        self.racing_backend(os.path.join(self.out, "pack"), False)
        with patching.patch_all(archive, "_CANDIDATES", 1):
            before = files_under(self.tmp)
            with self.assertRaisesRegex(PackError, "No free folder"):
                archive.unpack(path, dest_parent=self.out)
        self.assert_clean(before)
        self.assertEqual(os.listdir(self.out), ["pack"])


if __name__ == "__main__":
    unittest.main()
