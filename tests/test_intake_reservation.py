# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/intake/archive/ on the reservation of a pack folder: a crash at each step of an unpack,
the stale reservation judged and cleared, no Blender, no network.

    python -I -m unittest discover tests
"""
import contextlib
import json
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
    archive, Base, files_under, junction, PackError, patching, rename_through_os, write,
)


class Crash(BaseException):
    """Blender stopping mid-way: nothing of unpack() runs after it."""


class Reservation(Base):
    """A destination a crash left between its reservation and its marker: a later unpack takes the name again once
    the reservation is old, as long as the folder holds nothing but the maps it was reserved for."""

    OLD = 7 * 3600
    FILES = [("room.max", b"MAX"), ("wood.jpg", b"W"), ("stone.png", b"S")]

    def ident(self, path):
        return archive._ident(path, os.stat(path))

    def reservation(self, folder, ident, maps):
        """An aged reservation file, as unpack() writes it."""
        path = os.path.join(folder, archive.RESERVATION)
        write(path, json.dumps(dict(ident, format=archive.MARKER_FORMAT, maps=maps)).encode())
        self.age(path)

    def age(self, *paths):
        then = time.time() - self.OLD
        for path in paths:
            os.utime(path, (then, then))

    def crash(self, path, moves=None, scene=None, out=None):
        """unpack() stopped after `moves` files moved into the destination (None: after every move, before the
        marker). No cleanup runs; the staging folder it leaves is aged so that the next unpack removes it. Returns
        the destination."""
        out = out or self.out
        real_rename, real_marker, real_reserve, reserved = os.rename, archive._write_marker, archive._reserve, []

        def reserve(*args):
            reserved.append(real_reserve(*args))
            return reserved[-1]

        def rename(src, dst):
            if os.path.isdir(src):  # a folder renamed into place, not a file move
                return real_rename(src, dst)
            if moves is not None and moves == 0:
                raise Crash()
            if moves is not None:
                rename.left -= 1
                if rename.left < 0:
                    raise Crash()
            return real_rename(src, dst)
        rename.left = moves

        def marker(folder, ident, scene_name, *args):
            if moves is None and scene_name is not None:
                raise Crash()
            return real_marker(folder, ident, scene_name, *args)
        with mock.patch.object(archive.os, "rename", rename), patching.patch_all(archive, "_write_marker", marker), \
                patching.patch_all(archive, "_reserve", reserve), mock.patch.object(archive.shutil, "rmtree"):
            with self.assertRaises(Crash):
                archive.unpack(path, scene, dest_parent=out)
        for parent, dirs, _files in os.walk(out):
            self.age(*[os.path.join(parent, d) for d in dirs if d.startswith(archive.STAGING_PREFIX)])
        return reserved[0]

    def test_a_crash_after_one_move_leaves_a_folder_a_later_unpack_takes_again(self):
        path = self.pack(self.FILES)
        folder = self.crash(path, moves=1)
        self.assertEqual(folder, os.path.join(self.out, "pack"))
        self.assertEqual(self.listing(folder), sorted([archive.RESERVATION, "wood.jpg"]))
        self.age(os.path.join(folder, archive.RESERVATION))
        self.assertEqual(archive.preview(path, "room.max", False, self.out),
                         ("unpacked", os.path.join(folder, "room.max")))
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("unpacked", folder))
        self.assertEqual(self.listing(folder), sorted([archive.MARKER, "room.max", "stone.png", "wood.jpg"]))
        self.assertEqual(self.listing(self.out), ["pack"])

    def test_a_crash_before_any_move_leaves_a_folder_taken_again(self):
        path = self.pack(self.FILES)
        folder = self.crash(path, moves=0)
        self.assertEqual(os.listdir(folder), [archive.RESERVATION])
        self.age(os.path.join(folder, archive.RESERVATION))
        self.assertEqual(archive.unpack(path, dest_parent=self.out).folder, folder)

    def test_a_recent_reservation_is_left_alone(self):
        path = self.pack(self.FILES)
        folder = self.crash(path, moves=1)
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(r.folder, os.path.join(self.out, "pack (2)"))
        self.assertEqual(self.listing(folder), sorted([archive.RESERVATION, "wood.jpg"]))

    def test_a_crash_after_the_scene_moved_is_used_in_place(self):
        path = self.pack(self.FILES)
        folder = self.crash(path)
        self.assertEqual(self.listing(folder), sorted([archive.RESERVATION, "room.max", "stone.png", "wood.jpg"]))
        self.age(os.path.join(folder, archive.RESERVATION))
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((r.mode, r.max_path), ("in_place", os.path.join(folder, "room.max")))
        self.assertEqual(self.listing(folder), sorted([archive.RESERVATION, "room.max", "stone.png", "wood.jpg"]))

    def test_anything_else_in_the_folder_keeps_it(self):
        cases = {
            "an unlisted file": lambda f: write(os.path.join(f, "notes.txt"), b"mine"),
            "an unlisted map": lambda f: write(os.path.join(f, "other.jpg"), b"O"),
            "a subfolder": lambda f: os.mkdir(os.path.join(f, "sub")),
            "a marker": lambda f: write(os.path.join(f, archive.MARKER), b"{}"),
            "a scene": lambda f: write(os.path.join(f, "room.max"), b"MAX"),
        }
        for label, add in cases.items():
            with self.subTest(label):
                out = tempfile.mkdtemp(dir=self.tmp)
                path = self.pack(self.FILES)
                folder = self.crash(path, moves=1, out=out)
                add(folder)
                self.age(os.path.join(folder, archive.RESERVATION))
                self.assertIsNone(archive._stale_reservation(folder, self.ident(path)))
                kept = self.listing(folder)
                r = archive.unpack(path, dest_parent=out)
                if label == "a scene":
                    self.assertEqual((r.mode, r.folder), ("in_place", folder))
                else:
                    self.assertEqual((r.mode, r.folder), ("unpacked", os.path.join(out, "pack (2)")))
                self.assertEqual(self.listing(folder), kept)

    def test_a_reservation_file_that_does_not_hold_is_not_stale(self):
        path = self.pack(self.FILES)
        ident = self.ident(path)
        folder = os.path.join(self.out, "pack")
        reservation = os.path.join(folder, archive.RESERVATION)
        good = dict(ident, format=archive.MARKER_FORMAT, maps=["wood.jpg"])
        cases = {
            "not json": (b"half", "wood.jpg"),
            "not a dict": (b"[]", "wood.jpg"),
            "another format": (dict(good, format=99), "wood.jpg"),
            "maps not a list": (dict(good, maps="wood.jpg"), "wood.jpg"),
            # A file of an archive extracted by hand: it must name this pack, and only names a pack writes as maps
            # count.
            "another pack": (dict(good, size=ident["size"] + 1), "wood.jpg"),
            "no pack": ({"format": archive.MARKER_FORMAT, "maps": ["wood.jpg"]}, "wood.jpg"),
            "a listed scene": (dict(good, maps=["room.max"]), "room.max"),
            "a listed text": (dict(good, maps=["notes.txt"]), "notes.txt"),
            "a listed refused name": (dict(good, maps=["wood.jpg "]), "wood.jpg"),
        }
        for label, (data, present) in cases.items():
            with self.subTest(label):
                os.mkdir(folder)
                write(reservation, data if isinstance(data, bytes) else json.dumps(data).encode())
                write(os.path.join(folder, present), b"W")
                self.age(reservation)
                self.assertIsNone(archive._stale_reservation(folder, ident))
                self.assertFalse(archive._clear_stale_reservation(folder, ident))
                self.assertEqual(self.listing(folder), sorted([archive.RESERVATION, present]))
                r = archive.unpack(path, dest_parent=self.out)
                if present == "room.max":
                    self.assertEqual((r.mode, r.folder), ("in_place", folder))
                else:
                    self.assertEqual((r.mode, r.folder), ("unpacked", folder + " (2)"))
                    shutil.rmtree(r.folder)
                shutil.rmtree(folder)
        os.makedirs(reservation)  # a folder by that name
        self.age(reservation)
        self.assertIsNone(archive._stale_reservation(folder, ident))

    def test_two_names_of_one_key_are_not_stale(self):
        # NTFS keeps an NFC and an NFD name apart; name_key() makes them one: the second would go unchecked.
        nfc, nfd = "caf\u00e9.jpg", "cafe\u0301.jpg"
        path = self.pack(self.FILES)
        folder = os.path.join(self.out, "pack")
        os.mkdir(folder)
        write(os.path.join(folder, nfc), b"1")
        write(os.path.join(folder, nfd), b"2")
        if len(os.listdir(folder)) != 2:
            raise unittest.SkipTest("this file system stores both names as one")
        self.reservation(folder, self.ident(path), [nfc])
        self.assertIsNone(archive._stale_reservation(folder, self.ident(path)))
        os.remove(os.path.join(folder, nfd))
        self.assertIsNotNone(archive._stale_reservation(folder, self.ident(path)))

    def test_a_linked_folder_is_not_stale(self):
        path = self.pack(self.FILES)
        ident = self.ident(path)
        target = os.path.join(self.tmp, "target")
        os.mkdir(target)
        write(os.path.join(target, "wood.jpg"), b"K")
        self.reservation(target, ident, ["wood.jpg"])
        self.assertIsNotNone(archive._stale_reservation(target, ident))
        link = os.path.join(self.out, "pack")
        junction(target, link)
        self.addCleanup(os.rmdir, link)
        self.assertIsNone(archive._stale_reservation(link, ident))
        self.assertFalse(archive._clear_stale_reservation(link, ident))
        self.assertEqual(self.listing(target), sorted([archive.RESERVATION, "wood.jpg"]))

    def test_a_later_folder_a_retry_completed_is_reused(self):
        path = self.pack(self.FILES)
        folder = self.crash(path, moves=1)
        retry = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(retry.folder, folder + " (2)")
        self.age(os.path.join(folder, archive.RESERVATION))
        self.assertEqual(archive.preview(path, "room.max", False, self.out), ("reused", retry.max_path))
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("reused", retry.folder))
        self.assertEqual(self.listing(folder), sorted([archive.RESERVATION, "wood.jpg"]))

    def test_a_later_scene_folder_a_retry_completed_is_reused(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2"), ("wood.jpg", b"W")])
        folder = self.crash(path, moves=1, scene="two.max")
        retry = archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertEqual(retry.folder, folder + " (2)")
        self.age(os.path.join(folder, archive.RESERVATION))
        r = archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("reused", retry.folder))

    def test_two_unpacks_clearing_one_folder(self):
        path = self.pack(self.FILES)
        folder = self.crash(path, moves=1)
        self.age(os.path.join(folder, archive.RESERVATION))
        real, other, calls = archive._stale_reservation, [], []

        def judged(f, ident):
            found = real(f, ident)
            if f == folder and not other:
                calls.append(found is not None)
                if len(calls) == 2:  # _probe's look, then _clear_stale_reservation's: before its removal
                    # Another unpack of the pack clears the folder and fills it.
                    other.append(None)
                    other[0] = archive.unpack(path, dest_parent=self.out)
            return found
        r = None
        with patching.patch_all(archive, "_stale_reservation", judged):
            r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((other[0].folder, r.folder), (folder, folder + " (2)"))
        complete = sorted([archive.MARKER, "room.max", "stone.png", "wood.jpg"])
        self.assertEqual((self.listing(folder), self.listing(r.folder)), (complete, complete))
        self.assertEqual(self.listing(self.out), ["pack", "pack (2)"])

    def test_a_stale_scene_folder_of_several(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2"), ("wood.jpg", b"W")])
        folder = self.crash(path, moves=1, scene="two.max")
        self.assertEqual(folder, os.path.join(self.out, "pack", "two"))
        self.age(os.path.join(folder, archive.RESERVATION))
        r = archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("unpacked", folder))
        self.assertEqual(self.listing(folder), sorted([archive.MARKER, "two.max", "wood.jpg"]))
        self.assertEqual(self.listing(os.path.join(self.out, "pack")), sorted([archive.MARKER, "two"]))

    def test_a_stale_reservation_only_reserve_meets(self):
        path = self.pack(self.FILES)
        folder = self.crash(path, moves=1)
        moved = os.path.join(self.out, "pack (2)")
        os.rename(folder, moved)
        self.age(os.path.join(moved, archive.RESERVATION))
        made = os.path.join(self.out, "pack")

        class Racer(archive.ZipBackend):
            def extract(self, path, wanted, staging, budget):
                super().extract(path, wanted, staging, budget)
                if not os.path.lexists(made):
                    os.mkdir(made)
        self.addCleanup(archive._BACKENDS.__setitem__, "zip", archive._BACKENDS["zip"])
        archive._BACKENDS["zip"] = Racer()
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(r.folder, moved)
        self.assertEqual(self.listing(moved), sorted([archive.MARKER, "room.max", "stone.png", "wood.jpg"]))
        self.assertEqual(os.listdir(made), [])

    def test_the_destination_appears_holding_its_reservation(self):
        several = [("one.max", b"1"), ("two.max", b"2"), ("wood.jpg", b"W")]
        for files, scene, expected in (
                (self.FILES, None, [("pack", [archive.RESERVATION])]),
                (several, "two.max", [("pack", [archive.MARKER]), (os.path.join("pack", "two"),
                                                                   [archive.RESERVATION])])):
            with self.subTest(scene=scene):
                out = tempfile.mkdtemp(dir=self.tmp)
                real, made = os.rename, []

                def rename(src, dst):
                    if os.path.isdir(src):
                        self.assertFalse(os.path.lexists(dst))
                        made.append((os.path.relpath(dst, out), sorted(os.listdir(src))))
                    return real(src, dst)
                with mock.patch.object(archive.os, "rename", rename), rename_through_os():
                    archive.unpack(self.pack(files), scene, dest_parent=out)
                self.assertEqual(made, expected)

    def crash_on_make(self, path, scene=None, at_marker=False):
        """unpack() stopped while a folder is filled under its staging name, before it is renamed into place: the
        destination's (at its rename) or the pack folder's (at_marker: at its marker). No cleanup runs; what it
        leaves is aged."""
        real = os.rename

        def rename(src, dst):
            if os.path.isdir(src) and not at_marker:
                raise Crash()
            return real(src, dst)

        def marker(*args):
            raise Crash()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(archive.os, "rename", rename))
            stack.enter_context(rename_through_os())
            stack.enter_context(mock.patch.object(archive.shutil, "rmtree"))
            if at_marker:
                stack.enter_context(patching.patch_all(archive, "_write_marker", marker))
            with self.assertRaises(Crash):
                archive.unpack(path, scene, dest_parent=self.out)
        for parent, dirs, files in os.walk(self.out):
            self.age(*[os.path.join(parent, n) for n in dirs + files])

    def assert_only_staging(self, folder):
        left = self.listing(folder)
        self.assertTrue(left and all(n.startswith(archive.STAGING_PREFIX) for n in left), left)

    def test_a_crash_before_the_destination_is_in_place_leaves_no_folder(self):
        path = self.pack(self.FILES)
        self.crash_on_make(path)
        self.assert_only_staging(self.out)
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("unpacked", os.path.join(self.out, "pack")))
        self.assertEqual(self.listing(self.out), ["pack"])

    def test_a_crash_before_the_pack_folder_is_in_place_leaves_no_folder(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2"), ("wood.jpg", b"W")])
        self.crash_on_make(path, "two.max", at_marker=True)
        self.assert_only_staging(self.out)
        r = archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("unpacked", os.path.join(self.out, "pack", "two")))
        self.assertEqual(self.listing(self.out), ["pack"])
        self.assertEqual(self.listing(os.path.join(self.out, "pack")), sorted([archive.MARKER, "two"]))

    def test_a_folder_that_cannot_be_renamed_is_made_as_before(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2"), ("wood.jpg", b"W")])
        real = os.rename

        def rename(src, dst):
            if os.path.isdir(src):
                raise PermissionError("a file in it is open")
            return real(src, dst)
        with mock.patch.object(archive.os, "rename", rename), rename_through_os():
            r = archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertEqual(r.folder, os.path.join(self.out, "pack", "two"))
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "two.max", "wood.jpg"]))
        self.assertEqual(self.listing(self.out), ["pack"])
        self.assertEqual(self.listing(os.path.join(self.out, "pack")), sorted([archive.MARKER, "two"]))

    def test_a_folder_that_cannot_go_back_is_kept(self):
        path = self.pack(self.FILES)
        ident = self.ident(path)
        folder = self.crash(path, moves=1)
        self.age(os.path.join(folder, archive.RESERVATION))
        real = archive._stale_reservation

        def judged(f, i):
            if os.path.basename(f).startswith(archive.STAGING_PREFIX):
                # What was renamed aside had been cleared and filled anew by another unpack, and a third one has
                # taken the name since.
                write(os.path.join(f, "room.max"), b"MAX")
                write(os.path.join(f, archive.MARKER), b"{}")
                os.mkdir(folder)
                write(os.path.join(folder, "third.jpg"), b"T")
            return real(f, i)
        with patching.patch_all(archive, "_stale_reservation", judged):
            self.assertFalse(archive._clear_stale_reservation(folder, ident))
        self.assertEqual(os.listdir(folder), ["third.jpg"])
        kept = [n for n in os.listdir(self.out) if n.startswith(archive.RECLAIM_PREFIX)]
        self.assertEqual(len(kept), 1)
        with patching.patch_all(archive, "_STALE_SECONDS", -60):  # everything counts as old
            archive._remove_stale_staging(self.out, archive.Limits(seconds=-60))
        self.assertEqual(self.listing(self.out), sorted(["pack", kept[0]]))
        self.assertIn("room.max", os.listdir(os.path.join(self.out, kept[0])))

    def test_a_folder_whose_rename_back_is_refused_is_kept(self):
        path = self.pack(self.FILES)
        ident = self.ident(path)
        folder = self.crash(path, moves=1)
        self.age(os.path.join(folder, archive.RESERVATION))
        real_judged, real_rename = archive._stale_reservation, os.rename

        def judged(f, i):
            if os.path.basename(f).startswith(archive.STAGING_PREFIX):  # filled anew by another unpack
                write(os.path.join(f, "room.max"), b"MAX")
                write(os.path.join(f, archive.MARKER), b"{}")
            return real_judged(f, i)

        def rename(src, dst):
            if dst == folder:
                raise PermissionError("a file in it is open")
            return real_rename(src, dst)
        with patching.patch_all(archive, "_stale_reservation", judged), \
                mock.patch.object(archive.os, "rename", rename), rename_through_os():
            self.assertFalse(archive._clear_stale_reservation(folder, ident))
        self.assertFalse(os.path.lexists(folder))
        kept = [n for n in os.listdir(self.out) if n.startswith(archive.RECLAIM_PREFIX)]
        self.assertEqual(len(kept), 1)
        with patching.patch_all(archive, "_STALE_SECONDS", -60):
            archive._remove_stale_staging(self.out, archive.Limits(seconds=-60))
        self.assertIn("room.max", os.listdir(os.path.join(self.out, kept[0])))

    def test_the_fallback_takes_the_next_name_and_cleans_up_a_failure(self):
        real_rename, real_mkdir = os.rename, os.mkdir

        def rename(src, dst):
            if os.path.isdir(src):
                raise PermissionError("a file in it is open")
            return real_rename(src, dst)

        def mkdir(p, *args):
            if os.path.basename(p) == "pack":  # made by someone else between the rename and the mkdir
                real_mkdir(p, *args)
                raise FileExistsError(p)
            return real_mkdir(p, *args)
        path = self.pack(self.FILES)
        with mock.patch.object(archive.os, "rename", rename), mock.patch.object(archive.os, "mkdir", mkdir), \
                rename_through_os():
            r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(r.folder, os.path.join(self.out, "pack (2)"))
        self.assertEqual(os.listdir(os.path.join(self.out, "pack")), [])
        self.assertEqual(self.listing(self.out), ["pack", "pack (2)"])

        out = tempfile.mkdtemp(dir=self.tmp)
        before = files_under(self.tmp)
        failing = patching.patch_all(archive, "_write_reservation",
                                     side_effect=[None, OSError("disk gone")])  # fine in staging, not in place
        with mock.patch.object(archive.os, "rename", rename), failing, rename_through_os():
            with self.assertRaisesRegex(PackError, "disk gone"):
                archive.unpack(path, dest_parent=out)
        self.assertEqual(os.listdir(out), [])
        self.assert_clean(before)

    def test_a_clear_that_fails_half_way_is_removed_later(self):
        path = self.pack(self.FILES)
        ident = self.ident(path)
        folder = self.crash(path, moves=1)
        self.age(os.path.join(folder, archive.RESERVATION))
        with mock.patch.object(archive.os, "remove", side_effect=PermissionError("in use")):
            self.assertTrue(archive._clear_stale_reservation(folder, ident))
        self.assert_only_staging(self.out)
        with patching.patch_all(archive, "_STALE_SECONDS", -60):
            archive._remove_stale_staging(self.out, archive.Limits(seconds=-60))
        self.assertEqual(os.listdir(self.out), [])

    def test_a_crash_between_the_clears_renames_keeps_a_refilled_folder(self):
        # A complete scene, a scene alone, a file this code never writes: more than a stale folder can hold.
        for refill in ([archive.MARKER, "room.max"], ["room.max"], ["notes.txt"]):
            with self.subTest(refill=refill):
                out = tempfile.mkdtemp(dir=self.tmp)
                path = self.pack(self.FILES)
                ident = self.ident(path)
                folder = self.crash(path, moves=1, out=out)
                self.age(os.path.join(folder, archive.RESERVATION))
                real = archive._stale_reservation

                def judged(f, i, refill=refill):
                    if os.path.basename(f).startswith(archive.STAGING_PREFIX):  # filled anew by another unpack
                        for name in refill:
                            write(os.path.join(f, name), b"X")
                    return real(f, i)

                def crash(*args):
                    raise Crash()
                with patching.patch_all(archive, "_stale_reservation", judged), \
                        patching.patch_all(archive, "_rename_new", crash):
                    with self.assertRaises(Crash):
                        archive._clear_stale_reservation(folder, ident)
                self.assert_only_staging(out)
                with patching.patch_all(archive, "_STALE_SECONDS", -60):  # everything counts as old
                    archive._remove_stale_staging(out, archive.Limits(seconds=-60))
                # The unpack's own staging (holding the scene it never moved) is removed; the refilled one is kept.
                left = self.listing(out)
                self.assertEqual(len(left), 1, left)
                self.assertTrue(left[0].startswith(archive.RECLAIM_PREFIX), left)
                self.assertEqual(self.listing(os.path.join(out, left[0])),
                                 sorted([archive.RESERVATION, "wood.jpg"] + refill))

    def test_a_reclaimed_folder_is_cleared_only_when_stale(self):
        path = self.pack(self.FILES)
        ident = self.ident(path)

        def reclaimed(label, reservation_ident, extra=(), aged=True):
            folder = os.path.join(self.out, archive.RECLAIM_PREFIX + label)
            os.mkdir(folder)
            write(os.path.join(folder, "wood.jpg"), b"W")
            for name in extra:
                write(os.path.join(folder, name), b"X")
            self.reservation(folder, reservation_ident, ["wood.jpg"])
            if not aged:
                os.utime(os.path.join(folder, archive.RESERVATION))
            return folder
        stale = reclaimed("stale", ident)  # the half-filled folder of an unpack that then failed
        kept = [reclaimed("complete", ident, [archive.MARKER, "room.max"]),
                reclaimed("other", dict(ident, size=ident["size"] + 1)),
                reclaimed("recent", ident, aged=False)]
        listings = {f: self.listing(f) for f in kept}
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("unpacked", os.path.join(self.out, "pack")))
        self.assertFalse(os.path.lexists(stale))
        self.assertEqual({f: self.listing(f) for f in kept}, listings)
        self.assertEqual(self.listing(self.out), sorted(["pack"] + [os.path.basename(f) for f in kept]))

    def test_a_freed_name_is_made_when_the_rename_is_refused(self):
        real_rename = os.rename

        def rename(src, dst):
            if os.path.basename(src).startswith(archive.STAGING_PREFIX + "new-"):
                raise PermissionError("a file in it is open")
            return real_rename(src, dst)  # the clear's rename aside, the file moves
        path = self.pack(self.FILES)
        folder = self.crash(path, moves=1)
        self.age(os.path.join(folder, archive.RESERVATION))
        with mock.patch.object(archive.os, "rename", rename), rename_through_os():
            r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((r.mode, r.folder), ("unpacked", folder))
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "stone.png", "wood.jpg"]))
        self.assertEqual(self.listing(self.out), ["pack"])

    def test_a_complete_unpack_keeps_no_reservation(self):
        path = self.pack(self.FILES)
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "stone.png", "wood.jpg"]))
        shutil.rmtree(r.folder)
        real = os.remove

        def remove(p):
            if os.path.basename(p) == archive.RESERVATION:
                raise PermissionError("in use")
            return real(p)
        with mock.patch.object(archive.os, "remove", remove):
            r = archive.unpack(path, dest_parent=self.out)
        # Complete all the same: the folder is kept and serves again, however old its reservation file.
        self.assertEqual(self.listing(r.folder),
                         sorted([archive.MARKER, archive.RESERVATION, "room.max", "stone.png", "wood.jpg"]))
        self.age(os.path.join(r.folder, archive.RESERVATION))
        self.assertIsNone(archive._stale_reservation(r.folder, self.ident(path)))
        self.assertEqual(archive.unpack(path, dest_parent=self.out).mode, "reused")


if __name__ == "__main__":
    unittest.main()
