# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/intake/archive/, the scene pack reader: no Blender, no network. Every archive is built here,
in a temp folder; where zipfile cannot write a case (encryption, Deflate64, raw non-UTF-8 names, a lying size,
several disks) its bytes are patched.

    python -I -m unittest discover tests
"""
import ast
import contextlib
import errno
import json
import os
import stat
import struct
import sys
import tempfile
import types
import unittest
import zipfile
import zlib
from unittest import mock

_TESTS = "maxdrop_tests"  # tests/ as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_tests.intake_support import (  # noqa: E402 (after the loader)
    archive, Base, files_under, inside, INTAKE, PackError, patch_entry, patching, read,
    rename_through_os, replace_bytes, write, write_zip,
)


class Kind(Base):
    def test_by_magic_bytes_not_by_extension(self):
        cases = {
            "a.rar": b"PK\x03\x04rest", "b.zip": b"Rar!\x1a\x07\x00rest", "c.7z": b"Rar!\x1a\x07\x01\x00rest",
            "d.zip": b"7z\xbc\xaf\x27\x1crest", "e.zip": b"PK\x05\x06" + b"\0" * 18, "f.zip": b"not an archive",
            "g.zip": b"",
        }
        for name, data in cases.items():
            with open(os.path.join(self.tmp, name), "wb") as f:
                f.write(data)
        got = {name: archive.kind(os.path.join(self.tmp, name)) for name in cases}
        self.assertEqual(got, {"a.rar": "zip", "b.zip": "rar", "c.7z": "rar", "d.zip": "7z", "e.zip": "zip",
                               "f.zip": None, "g.zip": None})
        self.assertIsNone(archive.kind(os.path.join(self.tmp, "missing.zip")))

    def test_a_real_empty_zip_and_formats_without_backend(self):
        empty = self.pack([], name="empty.zip")
        self.assertEqual(archive.kind(empty), "zip")
        self.assertEqual(archive.list_pack(empty).scenes, [])
        with self.assertRaisesRegex(PackError, "no .max"):
            archive.unpack(empty, dest_parent=self.out)
        rar = os.path.join(self.tmp, "pack.rar")
        with open(rar, "wb") as f:
            f.write(b"Rar!\x1a\x07\x01\x00" + b"\0" * 32)
        with self.assertRaisesRegex(PackError, "cannot read .rar"):
            archive.list_pack(rar)
        text = os.path.join(self.tmp, "notes.zip")
        with open(text, "w") as f:
            f.write("hello")
        with self.assertRaisesRegex(PackError, "not a .zip, .rar or .7z"):
            archive.unpack(text, dest_parent=self.out)


class FlatAndFolders(Base):
    def test_flat_pack(self):
        path = self.pack([("room.max", b"MAX"), ("wood.jpg", b"J"), ("Floor.PNG", b"P"), ("light.IES", b"I"),
                          ("readme.txt", b"T"), ("setup.exe", b"E"), ("tool.ms", b"S"), ("other.fbx", b"F"),
                          ("nested.zip", b"Z")])
        listing = archive.list_pack(path)
        self.assertEqual((listing.kind, listing.backend), ("zip", "zipfile"))
        self.assertEqual((listing.scenes, listing.assets, listing.skipped, listing.problems),
                         (["room.max"], 3, 5, []))
        r = archive.unpack(path, dest_parent=self.out)
        folder = os.path.join(self.out, "pack")
        self.assertEqual((r.mode, r.folder, r.max_path, r.written), ("unpacked", folder,
                                                                     os.path.join(folder, "room.max"), 4))
        self.assertEqual(self.listing(folder), sorted([archive.MARKER, "Floor.PNG", "light.IES", "room.max",
                                                       "wood.jpg"]))
        self.assertEqual(r.skipped, {".txt": 1, ".exe": 1, ".ms": 1, ".fbx": 1, ".zip": 1})
        with open(os.path.join(folder, "room.max"), "rb") as f:
            self.assertEqual(f.read(), b"MAX")
        marker = json.loads(read(os.path.join(folder, archive.MARKER)))
        st = os.stat(path)
        self.assertEqual(marker, {"archive": "pack.zip", "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                                  "scene": "room.max", "files": 4, "format": 1, "wanted": None})

    def test_default_destination_is_the_archive_folder(self):
        path = self.pack([("room.max", b"MAX")])
        r = archive.unpack(path)
        self.assertEqual(r.folder, os.path.join(self.tmp, "pack"))

    def test_pack_with_folders_is_unpacked_flat(self):
        path = self.pack([("Pack/", b""), ("Pack/scene/room.max", b"MAX"), ("Pack/scene/maps/wood.jpg", b"J"),
                          ("Pack/textures/stone.tif", b"T"), ("Pack\\win\\brick.tga", b"B")])
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "wood.jpg", "stone.tif",
                                                         "brick.tga"]))
        self.assertEqual(r.skipped, {})

    def test_wanted_writes_only_those_assets(self):
        path = self.pack([("room.max", b"MAX"), ("wood.jpg", b"J"), ("Stone.PNG", b"P"), ("light.ies", b"I")])
        r = archive.unpack(path, dest_parent=self.out, wanted={"stone.png", "WOOD.JPG", "absent.tga"})
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "wood.jpg", "Stone.PNG"]))
        self.assertEqual((r.written, r.unwanted), (3, 1))

    def test_a_folder_unpacked_with_wanted_serves_only_what_it_covers(self):
        path = self.pack([("room.max", b"MAX"), ("a.jpg", b"A"), ("b.jpg", b"B")])
        first = archive.unpack(path, dest_parent=self.out, wanted={"a.jpg"})
        self.assertEqual(archive.unpack(path, dest_parent=self.out, wanted={"A.JPG"}).mode, "reused")
        wider = archive.unpack(path, dest_parent=self.out, wanted={"a.jpg", "b.jpg"})
        self.assertEqual((wider.mode, wider.folder), ("unpacked", os.path.join(self.out, "pack (2)")))
        self.assertIn("b.jpg", os.listdir(wider.folder))
        every = archive.unpack(path, dest_parent=self.out)
        self.assertEqual((every.mode, every.folder), ("unpacked", os.path.join(self.out, "pack (3)")))
        self.assertEqual(archive.unpack(path, dest_parent=self.out, wanted={"b.jpg"}).folder, wider.folder)
        self.assertEqual(sorted(os.listdir(first.folder)), sorted([archive.MARKER, "room.max", "a.jpg"]))


class References(Base):
    """unpack(references=...): the scene is written first and asked which maps it uses."""

    def asker(self, names):
        calls = []

        def references(max_path):
            calls.append((max_path, os.path.isfile(max_path), read(max_path)))
            return names
        return references, calls

    def test_only_the_maps_the_scene_names_are_written(self):
        path = self.pack([("Pack/room.max", b"MAX"), ("Pack/maps/wood.jpg", b"J"), ("Pack/Stone.PNG", b"P"),
                          ("Pack/light.ies", b"I"), ("Pack/unused.tga", b"U")])
        references, calls = self.asker(["WOOD.JPG", "stone.png", "light.IES", "absent.tif"])
        r = archive.unpack(path, dest_parent=self.out, references=references)
        self.assertEqual(len(calls), 1)
        staged, existed, data = calls[0]
        self.assertTrue(existed)
        self.assertEqual(data, b"MAX")
        self.assertEqual(os.path.basename(staged), "room.max")
        self.assertTrue(os.path.basename(os.path.dirname(staged)).startswith(archive.STAGING_PREFIX))
        self.assertEqual(os.path.dirname(os.path.dirname(staged)), self.out)
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "wood.jpg", "Stone.PNG",
                                                         "light.ies"]))
        self.assertEqual((r.mode, r.written, r.unwanted), ("unpacked", 4, 1))
        marker = json.loads(read(os.path.join(r.folder, archive.MARKER)))
        self.assertEqual((marker["files"], marker["wanted"]), (4, ["absent.tif", "light.ies", "stone.png",
                                                                   "wood.jpg"]))

    def test_none_writes_every_map(self):
        path = self.pack([("room.max", b"MAX"), ("a.jpg", b"A"), ("b.jpg", b"B")])
        references, calls = self.asker(None)
        r = archive.unpack(path, dest_parent=self.out, references=references)
        self.assertEqual((len(calls), r.written, r.unwanted), (1, 3, 0))
        self.assertIsNone(json.loads(read(os.path.join(r.folder, archive.MARKER)))["wanted"])

    def test_a_scene_that_names_no_file_is_written_alone(self):
        path = self.pack([("room.max", b"MAX"), ("a.jpg", b"A")])
        references, _calls = self.asker([])
        r = archive.unpack(path, dest_parent=self.out, references=references)
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max"]))
        self.assertEqual((r.written, r.unwanted), (1, 1))

    def test_reuse_asks_the_unpacked_scene(self):
        path = self.pack([("room.max", b"MAX"), ("a.jpg", b"A"), ("b.jpg", b"B")])
        narrow, _ = self.asker(["a.jpg"])
        first = archive.unpack(path, dest_parent=self.out, references=narrow)
        asked, calls = self.asker(["A.JPG"])
        self.assertEqual(archive.preview(path, "room.max", False, self.out, references=asked),
                         ("reused", first.max_path))
        again = archive.unpack(path, dest_parent=self.out, references=asked)
        self.assertEqual((again.mode, again.folder, again.reused), ("reused", first.folder, 2))
        self.assertEqual([c[0] for c in calls], [first.max_path, first.max_path])
        wide, _ = self.asker(["a.jpg", "b.jpg"])
        self.assertEqual(archive.preview(path, "room.max", False, self.out, references=wide),
                         ("unpacked", os.path.join(self.out, "pack (2)", "room.max")))
        wider = archive.unpack(path, dest_parent=self.out, references=wide)
        self.assertEqual((wider.mode, wider.folder), ("unpacked", os.path.join(self.out, "pack (2)")))
        unreadable, _ = self.asker(None)
        self.assertEqual(archive.unpack(path, dest_parent=self.out, references=unreadable).folder,
                         os.path.join(self.out, "pack (3)"))
        # A folder unpacked with every map serves without asking the scene.
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        every = archive.unpack(path, dest_parent=other, references=unreadable)
        silent, calls = self.asker(["b.jpg"])
        self.assertEqual(archive.unpack(path, dest_parent=other, references=silent).folder, every.folder)
        self.assertEqual(calls, [])

    def test_an_encrypted_map_the_scene_does_not_name_is_left_out(self):
        path = self.pack([("room.max", b"MAX"), ("a.jpg", b"A"), ("secret.jpg", b"S")])
        patch_entry(path, "secret.jpg", flags=0x1)
        references, _ = self.asker(["a.jpg"])
        r = archive.unpack(path, dest_parent=self.out, references=references)
        self.assertEqual((r.written, r.unwanted), (2, 1))
        before = files_under(self.tmp)
        named, _ = self.asker(["secret.jpg"])
        with self.assertRaises(PackError) as caught:
            archive.unpack(path, dest_parent=self.tmp, references=named)
        self.assertEqual(str(caught.exception), archive.password_message(path))
        self.assert_clean(before)

    def test_a_failing_question_leaves_nothing(self):
        path = self.pack([("room.max", b"MAX"), ("a.jpg", b"A")])

        def broken(_max_path):
            raise RuntimeError("boom")
        before = files_under(self.tmp)
        with self.assertRaisesRegex(RuntimeError, "boom"):
            archive.unpack(path, dest_parent=self.out, references=broken)
        self.assert_clean(before)
        self.assertEqual(os.listdir(self.out), [])

    def test_the_maps_count_against_the_limits(self):
        path = self.pack([("room.max", b"MAX"), ("a.jpg", b"A"), ("b.jpg", b"B")])
        references, _ = self.asker(["a.jpg", "b.jpg"])
        before = files_under(self.tmp)
        with self.assertRaisesRegex(PackError, "needs 3 files, more than the 2"):
            archive.unpack(path, dest_parent=self.out, references=references, limits=archive.Limits(files=2))
        self.assert_clean(before)
        with self.assertRaisesRegex(PackError, "more than 4 bytes"):
            archive.unpack(path, dest_parent=self.out, references=references,
                           limits=archive.Limits(total_bytes=4, free_margin=0))
        self.assert_clean(before)

    def test_one_scene_of_several(self):
        path = self.pack([("one/one.max", b"1"), ("one/a.jpg", b"A"), ("two/two.max", b"2"), ("two/b.jpg", b"B")])
        references, calls = self.asker(["b.jpg"])
        r = archive.unpack(path, "two/two.max", dest_parent=self.out, references=references)
        self.assertEqual(r.folder, os.path.join(self.out, "pack", "two"))
        self.assertEqual(os.path.dirname(os.path.dirname(calls[0][0])), os.path.join(self.out, "pack"))
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "two.max", "b.jpg"]))
        self.assertEqual(self.listing(os.path.join(self.out, "pack")), sorted([archive.MARKER, "two"]))
        self.assertEqual(archive.preview(path, "two/two.max", True, self.out, references=references),
                         ("reused", r.max_path))

    def test_the_marker_keeps_only_names_of_files_a_pack_writes(self):
        path = self.pack([("room.max", b"MAX"), ("a.jpg", b"A")])
        names = ["a.jpg", "proxy.vrmesh", "xref.max", "noext"] + ["木纹%04d.jpg" % i for i in range(3000)]
        references, _ = self.asker(names)
        first = archive.unpack(path, dest_parent=self.out, references=references)
        marker = json.loads(read(os.path.join(first.folder, archive.MARKER)))
        self.assertEqual(len(marker["wanted"]), 3001)
        self.assertNotIn("xref.max", marker["wanted"])
        self.assertGreater(os.path.getsize(os.path.join(first.folder, archive.MARKER)), 64 * 1024)
        again = archive.unpack(path, dest_parent=self.out, references=references)
        self.assertEqual((again.mode, again.folder), ("reused", first.folder))

    def test_wanted_and_references_together_are_refused(self):
        path = self.pack([("room.max", b"MAX")])
        with self.assertRaises(ValueError):
            archive.unpack(path, dest_parent=self.out, wanted={"a.jpg"}, references=lambda p: None)


class TwoScenes(Base):
    def test_each_scene_in_its_own_folder_of_the_pack(self):
        path = self.pack([("a/one.max", b"1"), ("b/two.max", b"2"), ("a/wood.jpg", b"A"), ("b/wood.jpg", b"B")])
        self.assertEqual(archive.list_pack(path).scenes, ["a/one.max", "b/two.max"])
        with self.assertRaisesRegex(PackError, "holds 2 scenes: choose one"):
            archive.unpack(path, dest_parent=self.out)
        with self.assertRaisesRegex(PackError, "holds no scene c/three.max"):
            archive.unpack(path, "c/three.max", dest_parent=self.out)
        one = archive.unpack(path, "a/one.max", dest_parent=self.out)
        two = archive.unpack(path, "b/two.max", dest_parent=self.out)
        top = os.path.join(self.out, "pack")
        self.assertEqual((one.folder, two.folder), (os.path.join(top, "one"), os.path.join(top, "two")))
        self.assertEqual(self.listing(one.folder), sorted([archive.MARKER, "one.max", "wood.jpg"]))
        self.assertEqual(one.skipped, {".max": 1})
        self.assertEqual(read(os.path.join(two.folder, "wood.jpg")), b"B")
        self.assertEqual(self.listing(top), sorted([archive.MARKER, "one", "two"]))
        again = archive.unpack(path, "a/one.max", dest_parent=self.out)
        self.assertEqual((again.mode, again.folder, again.reused), ("reused", one.folder, 2))

    def test_failure_removes_the_pack_folder_it_created(self):
        path = self.pack([("a/one.max", b"1"), ("b/two.max", b"2"), ("a/big.jpg", b"x" * 5000)])
        before = files_under(self.tmp)
        with self.assertRaises(PackError):
            archive.unpack(path, "a/one.max", dest_parent=self.out, limits=archive.Limits(file_bytes=1000))
        self.assert_clean(before)
        self.assertEqual(os.listdir(self.out), [])

    def test_failure_of_a_later_scene_keeps_the_pack_folder_and_the_first_scene(self):
        class Failing(archive.ZipBackend):
            def extract(self, path, wanted, staging, budget):
                super().extract(path, wanted, staging, budget)
                raise PackError("disk gone")

        path = self.pack([("a/one.max", b"1"), ("b/two.max", b"2"), ("b/wood.jpg", b"W")])
        one = archive.unpack(path, "a/one.max", dest_parent=self.out)
        before = files_under(self.tmp)
        self.addCleanup(archive._BACKENDS.__setitem__, "zip", archive._BACKENDS["zip"])
        archive._BACKENDS["zip"] = Failing()
        with self.assertRaisesRegex(PackError, "disk gone"):
            archive.unpack(path, "b/two.max", dest_parent=self.out)
        self.assert_clean(before)
        self.assertEqual(sorted(os.listdir(os.path.dirname(one.folder))), sorted([archive.MARKER, "one"]))


class Duplicates(Base):
    def test_nearest_to_the_scene_wins(self):
        path = self.pack([
            ("other/WOOD.JPG", b"far"), ("scene/sub/wood.jpg", b"below"), ("scene/wood.jpg", b"same"),
            ("x/y/z/stone.png", b"three"), ("scene/a/b/stone.png", b"below-2"), ("scene/a/stone.png", b"below-1"),
            ("p/q/brick.tga", b"steps-3"), ("p/brick.tga", b"steps-2"), ("r/brick.tga", b"first-steps-2"),
            ("scene/room.max", b"MAX"),
        ])
        r = archive.unpack(path, dest_parent=self.out)
        got = {n: read(os.path.join(r.folder, n)) for n in os.listdir(r.folder) if n != archive.MARKER}
        self.assertEqual(got, {"room.max": b"MAX", "wood.jpg": b"same", "stone.png": b"below-1",
                               "brick.tga": b"steps-2"})
        self.assertEqual(sorted(r.collided), sorted(["other/WOOD.JPG", "scene/sub/wood.jpg", "x/y/z/stone.png",
                                                     "scene/a/b/stone.png", "p/q/brick.tga", "r/brick.tga"]))
        self.assertEqual(r.written, 4)
        self.assertEqual(archive.list_pack(path).assets, 3)


# Each is stored as an asset name the allow-list would otherwise accept.
REFUSED = [
    "maps/.", "maps/..", "a\x01b.jpg", "tab\tname.jpg", "del\x7f.jpg", "c1\x85.jpg", "a:b.jpg", "wood.jpg:x.jpg",
    "q?.jpg", "a<b.png", "a>b.png", 'say"x.png', "pipe|x.png", "star*.png",
    "CON.jpg", "con.png", "PRN.tga", "Aux.tif", "NUL.jpg", "nul.tar.jpg", "COM1.jpg", "com9.png", "LPT1.jpg",
    "lpt9.tga", "COM\u00b9.jpg", "CON .jpg", "conin$.jpg",
    "end.jpg.", "end.jpg ", "x" * 197 + ".jpg",
]


class NamePolicy(Base):
    def test_refused_reason(self):
        for base in ["", ".", ".."] + [archive.Entry(n).base for n in REFUSED]:
            self.assertIsNotNone(archive.refused_reason(base), repr(base))
        for base in ["\U0001F600" * 128 + ".jpg", "\u6728" * 84 + ".jpg"]:
            self.assertEqual(archive.refused_reason(base), "longer than 200 characters", len(base))
        for base in ["wood.jpg", "x" * 196 + ".jpg", "\u6728" * 83 + ".jpg", "CONSOLE.jpg", "com10.jpg", "lpt.jpg", "中文.png", ".jpg",
                     "a b.jpg", "COM0.jpg"]:
            self.assertIsNone(archive.refused_reason(base), repr(base))

    def test_every_refused_name_is_never_written(self):
        for name in REFUSED:
            with self.subTest(name=name):
                sub = tempfile.mkdtemp(dir=self.tmp)
                path = write_zip(os.path.join(sub, "pack.zip"), [("room.max", b"MAX"), (name, b"BAD"),
                                                                  ("ok.jpg", b"OK")])
                before = files_under(self.tmp)
                r = archive.unpack(path, dest_parent=sub)
                new = files_under(self.tmp) - before
                self.assertTrue(all(inside(p, r.folder) for p in new), new)
                self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "ok.jpg"]))
                self.assertEqual([n for n, _reason in r.refused], [name])
                listing = archive.list_pack(path)
                self.assertEqual((listing.assets, listing.skipped), (1, 1))

    def test_refused_scene_names_are_not_scenes(self):
        path = self.pack([("CON.max", b"1"), ("x/scene.max ", b"2"), ("a:b.max", b"3"), ("good.max", b"4")])
        self.assertEqual(archive.list_pack(path).scenes, ["good.max"])

    def test_paths_outside_are_written_flat_inside(self):
        names = ["../../evil.jpg", "/abs/evil2.jpg", "C:\\temp\\evil3.png", "..\\..\\evil4.tga",
                 "C:/x/evil5.tif", "\\\\server\\share\\evil6.bmp"]
        path = self.pack([("room.max", b"MAX")] + [(n, b"E") for n in names])
        before = files_under(self.tmp)
        r = archive.unpack(path, dest_parent=self.out)
        new = files_under(self.tmp) - before
        self.assertTrue(all(inside(p, r.folder) for p in new), new)
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "evil.jpg", "evil2.jpg",
                                                         "evil3.png", "evil4.tga", "evil5.tif", "evil6.bmp"]))

    def test_empty_name_entry(self):
        path = self.pack([("room.max", b"MAX"), ("", b"X")])
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(r.refused, [("", "empty or a folder reference")])

    def test_link_entry_is_skipped(self):
        link = zipfile.ZipInfo("wood.jpg")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        reparse = zipfile.ZipInfo("stone.jpg")
        reparse.external_attr = 0x400
        fifo = zipfile.ZipInfo("pipe.png")
        fifo.create_system = 3
        fifo.external_attr = (stat.S_IFIFO | 0o644) << 16
        regular = zipfile.ZipInfo("ok.png")
        regular.create_system = 3
        regular.external_attr = (stat.S_IFREG | 0o644) << 16
        path = self.pack([("room.max", b"MAX"), (link, b"/etc/passwd"), (reparse, b"x"), (fifo, b"y"),
                          (regular, b"z")])
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(sorted(r.not_regular), ["pipe.png", "stone.jpg", "wood.jpg"])
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "ok.png"]))


class LimitTests(Base):
    def test_a_lying_declared_size_stops_at_the_limit(self):
        class Liar(archive.ZipBackend):
            def names(self, path):
                entries = super().names(path)
                for e in entries:
                    e.size = 1
                return entries

        path = self.pack([("room.max", b"MAX"), ("big.jpg", os.urandom(300000))])
        self.addCleanup(archive._BACKENDS.__setitem__, "zip", archive._BACKENDS["zip"])
        archive._BACKENDS["zip"] = Liar()
        before = files_under(self.tmp)
        for limits, message in ((archive.Limits(file_bytes=100000), "big.jpg is larger than"),
                                (archive.Limits(total_bytes=100000), "more than 97.7 KiB")):
            with self.assertRaisesRegex(PackError, message):
                archive.unpack(path, dest_parent=self.out, limits=limits)
            self.assert_clean(before)
            self.assertEqual(os.listdir(self.out), [])

    def test_a_size_that_lies_in_the_zip_itself(self):
        path = self.pack([("room.max", b"MAX"), ("big.jpg", b"x" * 1000)], compression=zipfile.ZIP_STORED)
        patch_entry(path, "big.jpg", size=10)
        before = files_under(self.tmp)
        with self.assertRaisesRegex(PackError, "Could not unpack big.jpg"):
            archive.unpack(path, dest_parent=self.out)
        self.assert_clean(before)

    def test_too_large_packs_are_refused_before_writing(self):
        path = self.pack([("room.max", b"M" * 600), ("a.jpg", b"a" * 600), ("b.jpg", b"b" * 600)])
        before = files_under(self.tmp)
        for limits, message in ((archive.Limits(total_bytes=1000), "unpacks to more than"),
                                (archive.Limits(file_bytes=500), "room.max is larger than"),
                                (archive.Limits(files=2), "needs 3 files"),
                                (archive.Limits(entries=2), "lists more than the 2 entries"),
                                (archive.Limits(free_margin=1 << 62), "Not enough free space")):
            with self.subTest(limits=limits):
                with self.assertRaisesRegex(PackError, message):
                    archive.unpack(path, dest_parent=self.out, limits=limits)
                self.assert_clean(before)
                self.assertEqual(os.listdir(self.out), [])

    def test_wall_time_through_unpack(self):
        path = self.pack([("room.max", b"MAX")])
        before = files_under(self.tmp)
        with self.assertRaisesRegex(PackError, "longer than"):
            archive.unpack(path, dest_parent=self.out, limits=archive.Limits(seconds=-1))
        self.assert_clean(before)
        self.assertEqual(os.listdir(self.out), [])

    def test_staging_holds_exactly_the_planned_regular_files(self):
        def extra(staging):
            write(os.path.join(staging, "setup.exe"), b"E")

        def folder(staging):
            os.remove(os.path.join(staging, "wood.jpg"))
            os.mkdir(os.path.join(staging, "wood.jpg"))

        def hardlink(staging):
            os.link(os.path.join(staging, "wood.jpg"), os.path.join(self.tmp, "outside.jpg"))

        def missing(staging):
            os.remove(os.path.join(staging, "wood.jpg"))

        path = self.pack([("room.max", b"MAX"), ("wood.jpg", b"W")])
        self.addCleanup(archive._BACKENDS.__setitem__, "zip", archive._BACKENDS["zip"])
        for tamper in (extra, folder, hardlink, missing):
            with self.subTest(tamper=tamper.__name__):
                class Tamper(archive.ZipBackend):
                    def extract(self, path, wanted, staging, budget):
                        super().extract(path, wanted, staging, budget)
                        tamper(staging)

                archive._BACKENDS["zip"] = Tamper()
                with self.assertRaisesRegex(PackError, "wrote other files than asked for"):
                    archive.unpack(path, dest_parent=self.out)
                if os.path.exists(os.path.join(self.tmp, "outside.jpg")):
                    os.remove(os.path.join(self.tmp, "outside.jpg"))
                self.assertEqual(os.listdir(self.out), [])

    def test_budget_counts_files_and_time(self):
        budget = archive._Budget(archive.Limits(files=1))
        budget.start_file("a")
        with self.assertRaisesRegex(PackError, "more files to unpack than the 1"):
            budget.start_file("b")
        budget = archive._Budget(archive.Limits(seconds=0))
        budget.deadline -= 1
        with self.assertRaisesRegex(PackError, "longer than 0 seconds"):
            budget.start_file("a")


class Watch(Base):
    """unpack(watch=...): the bytes written so far, and a way to stop (the import's Esc)."""

    def test_watch_sees_the_bytes_written(self):
        path = self.pack([("room.max", b"M" * 3000), ("wood.jpg", b"W" * 5000)])
        seen = []
        result = archive.unpack(path, dest_parent=self.out, watch=seen.append)
        self.assertEqual(result.written, 2)
        self.assertTrue(seen and seen == sorted(seen), seen)
        self.assertEqual(seen[-1], 8000)

    def test_cancelled_leaves_nothing(self):
        path = self.pack([("room.max", b"M" * 3000), ("wood.jpg", b"W" * 5000)])
        before = files_under(self.tmp)
        calls = []

        def stop(n):
            calls.append(n)
            if len(calls) == 2:
                raise archive.Cancelled()

        with self.assertRaises(archive.Cancelled):
            archive.unpack(path, dest_parent=self.out, watch=stop)
        self.assertEqual(len(calls), 2)
        self.assertEqual(os.listdir(self.out), [])
        self.assert_clean(before)

    def test_cancelled_is_a_pack_error(self):
        self.assertTrue(issubclass(archive.Cancelled, PackError))
        self.assertTrue(str(archive.Cancelled()))


class Unreadable(Base):
    def test_encrypted_entry(self):
        path = self.pack([("room.max", b"MAX"), ("secret.jpg", b"S")])
        patch_entry(path, "secret.jpg", flags=0x1)
        listing = archive.list_pack(path)
        self.assertEqual(listing.encrypted, ["secret.jpg"])
        self.assertTrue(any("encrypted" in p for p in listing.problems))
        before = files_under(self.tmp)
        with self.assertRaises(PackError) as caught:
            archive.unpack(path, dest_parent=self.out)
        self.assertEqual(str(caught.exception), archive.password_message(path))
        self.assert_clean(before)

    def test_the_password_message_names_the_archive(self):
        message = archive.password_message(os.path.join(self.tmp, "pack.zip"))
        self.assertEqual(message, "pack.zip is password-protected: MaxDrop does not ask for passwords. Extract the "
                                  "archive by hand and import the .max from that folder.")

    def test_an_entry_zipfile_finds_encrypted_gives_the_same_message(self):
        # Not flagged in the listing, refused by zipfile when read: the message does not depend on where.
        path = self.pack([("room.max", b"MAX"), ("wood.jpg", b"W")])
        before = files_under(self.tmp)
        with mock.patch.object(zipfile.ZipFile, "open", side_effect=RuntimeError("password required")):
            with self.assertRaises(PackError) as caught:
                archive.unpack(path, dest_parent=self.out)
        self.assertEqual(str(caught.exception), archive.password_message(path))
        self.assert_clean(before)

    def test_an_entry_zipfile_cannot_decode_is_not_called_encrypted(self):
        # NotImplementedError is a RuntimeError: e.g. a patched-data flag set in the local header only.
        path = self.pack([("room.max", b"MAX")])
        with mock.patch.object(zipfile.ZipFile, "open", side_effect=NotImplementedError("patched data")):
            with self.assertRaisesRegex(PackError, "^room.max needs patched data: MaxDrop cannot read it"):
                archive.unpack(path, dest_parent=self.out)

    def test_encrypted_entry_that_is_not_written(self):
        path = self.pack([("room.max", b"MAX"), ("secret.txt", b"S")])
        patch_entry(path, "secret.txt", flags=0x1)
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(r.written, 1)

    def test_deflate64_entry(self):
        path = self.pack([("room.max", b"MAX"), ("wood.jpg", b"W")], compression=zipfile.ZIP_STORED)
        patch_entry(path, "wood.jpg", method=9)
        self.assertTrue(any("cannot read" in p for p in archive.list_pack(path).problems))
        before = files_under(self.tmp)
        with self.assertRaisesRegex(PackError, "compression method 9.*Extract the archive by hand"):
            archive.unpack(path, dest_parent=self.out)
        self.assert_clean(before)

    def test_multi_disk(self):
        path = self.pack([("room.max", b"MAX")])
        patch_entry(path, "room.max", volume=1)
        with self.assertRaisesRegex(PackError, "split over several parts.*by hand"):
            archive.list_pack(path)

    def test_damaged_archive(self):
        path = os.path.join(self.tmp, "broken.zip")
        with open(path, "wb") as f:
            f.write(b"PK\x03\x04" + b"\0" * 100)
        with self.assertRaisesRegex(PackError, "not a readable .zip"):
            archive.list_pack(path)


class Names(Base):
    def test_names_without_the_utf8_flag(self):
        gbk = "中文.jpg".encode("gbk")
        utf8 = "été.png".encode("utf-8")
        path = self.pack([("room.max", b"MAX"), ("G" * (len(gbk) - 4) + ".jpg", b"G"),
                          ("U" * (len(utf8) - 4) + ".png", b"U")])
        replace_bytes(path, b"G" * (len(gbk) - 4) + b".jpg", gbk)
        replace_bytes(path, b"U" * (len(utf8) - 4) + b".png", utf8)
        listing = archive.list_pack(path)
        self.assertEqual(listing.guessed, ["中文.jpg"])
        self.assertTrue(any("guess" in p for p in listing.problems))
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "中文.jpg", "été.png"]))
        self.assertEqual(r.guessed, ["中文.jpg"])

    def test_utf8_flag_and_unicode_path_extra_field(self):
        raw = "木纹.jpg".encode("gbk")
        info = zipfile.ZipInfo("W" * (len(raw) - 4) + ".jpg")
        info.extra = struct.pack("<HHBL", 0x7075, 5 + len("木纹.jpg".encode()), 1, zlib.crc32(raw)) \
            + "木纹.jpg".encode()
        path = self.pack([("room.max", b"MAX"), ("Ünï.png", b"F"), (info, b"X")])
        replace_bytes(path, b"W" * (len(raw) - 4) + b".jpg", raw)
        listing = archive.list_pack(path)
        self.assertEqual(listing.guessed, [])
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "Ünï.png", "木纹.jpg"]))

    def test_backslash_names_are_shown_with_slashes(self):
        path = self.pack([("box\\room.max", b"MAX"), ("box\\maps\\wood.jpg", b"W"), ("box\\bad.jpg", b"B")])
        patch_entry(path, "box\\bad.jpg", method=9)
        listing = archive.list_pack(path)
        self.assertEqual(listing.scenes, ["box/room.max"])
        with self.assertRaisesRegex(PackError, "^box/bad.jpg "):
            archive.unpack(path, "box/room.max", dest_parent=self.out)
        r = archive.unpack(path, "box/room.max", dest_parent=self.out, wanted={"wood.jpg"})
        self.assertEqual(self.listing(r.folder), sorted([archive.MARKER, "room.max", "wood.jpg"]))
        self.assertEqual(archive._read_marker(r.folder)["scene"], "box/room.max")
        # A caller that passes the stored spelling still finds the scene.
        self.assertEqual(archive.preview(path, "box\\room.max", False, self.out, references=lambda _p: ["wood.jpg"]),
                         ("reused", r.max_path))
        self.assertEqual(archive.unpack(path, "box\\room.max", dest_parent=self.out, wanted={"wood.jpg"}).mode,
                         "reused")

    def test_a_marker_written_with_backslashes_is_reused(self):
        path = self.pack([("box\\room.max", b"MAX")])
        first = archive.unpack(path, dest_parent=self.out)
        marker = os.path.join(first.folder, archive.MARKER)
        data = archive._read_marker(first.folder)
        data["scene"] = "box\\room.max"  # as an earlier version wrote a .rar's name listed by UnRAR
        os.chmod(marker, stat.S_IWRITE | stat.S_IREAD)
        with open(marker, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.assertEqual(archive.unpack(path, dest_parent=self.out).mode, "reused")


class RenameNew(Base):
    """_rename_new never replaces a folder: not one that exists, not one made in the instant before the rename."""

    def folders(self):
        """src holding a.txt and a free dst, in a folder of their own (subtests do not share them)."""
        parent = tempfile.mkdtemp(dir=self.tmp)
        src, dst = os.path.join(parent, "src"), os.path.join(parent, "pack")
        os.mkdir(src)
        write(os.path.join(src, "a.txt"), b"A")
        return src, dst

    def assert_kept(self, src, dst):
        self.assertEqual(os.listdir(dst), [])
        self.assertEqual(os.listdir(src), ["a.txt"])

    def test_a_folder_made_in_the_instant_before_the_rename_is_kept(self):
        real = archive._noreplace()
        if real is None:
            self.skipTest("no rename that never replaces on this system: the fallback looks first")
        src, dst = self.folders()

        def racing(s, d):
            os.mkdir(d)  # empty: what a POSIX rename replaces
            return real(s, d)
        with patching.patch_all(archive, "_noreplace", lambda: racing):
            self.assertFalse(archive._rename_new(src, dst))
        self.assert_kept(src, dst)

    def test_an_existing_folder_is_refused(self):
        for fallback in (False, True):
            with self.subTest(fallback=fallback), contextlib.ExitStack() as stack:
                if fallback:
                    stack.enter_context(rename_through_os())
                src, dst = self.folders()
                os.mkdir(dst)
                self.assertFalse(archive._rename_new(src, dst))
                self.assert_kept(src, dst)

    def test_a_free_name_is_taken(self):
        for unsupported in (False, True):
            with self.subTest(unsupported=unsupported), contextlib.ExitStack() as stack:
                if unsupported:  # the file system has no such rename: the fallback renames
                    stack.enter_context(patching.patch_all(archive, "_noreplace", lambda: lambda s, d: False))
                src, dst = self.folders()
                self.assertTrue(archive._rename_new(src, dst))
                self.assertFalse(os.path.lexists(src))
                self.assertEqual(os.listdir(dst), ["a.txt"])

    def test_a_missing_source_raises(self):
        # An OSError of its own, not False: _create then makes the folder by hand (_make).
        with self.assertRaises(FileNotFoundError):
            archive._rename_new(os.path.join(self.tmp, "missing"), os.path.join(self.out, "pack"))
        self.assertEqual(os.listdir(self.out), [])

    def test_the_errno_is_read(self):
        for err in archive._NOREPLACE_UNSUPPORTED:
            self.assertIs(archive._noreplace_failed(err, "a", "b"), False)
        self.assertIn(errno.ENOSYS, archive._NOREPLACE_UNSUPPORTED)
        self.assertIn(errno.EINVAL, archive._NOREPLACE_UNSUPPORTED)
        with self.assertRaises(FileExistsError) as caught:
            archive._noreplace_failed(errno.EEXIST, "a", "b")
        self.assertEqual((caught.exception.filename, caught.exception.filename2), ("a", "b"))
        with self.assertRaises(FileNotFoundError):
            archive._noreplace_failed(errno.ENOENT, "a", "b")
        with self.assertRaises(PermissionError):
            archive._noreplace_failed(errno.EACCES, "a", "b")

    @unittest.skipUnless(sys.platform.startswith("linux") or sys.platform == "darwin", "Linux and macOS")
    def test_the_native_rename_works(self):
        # Called directly: a wrong flag or argument type comes back as EINVAL, which reads as "unsupported", and
        # _rename_new's fallback would hide it.
        rename = archive._noreplace()
        self.assertIsNotNone(rename)
        src, dst = self.folders()
        os.mkdir(dst)
        with self.assertRaises(FileExistsError):
            rename(src, dst)
        self.assert_kept(src, dst)
        os.rmdir(dst)
        self.assertIs(rename(src, dst), True)
        self.assertEqual(os.listdir(dst), ["a.txt"])


class NoBlender(unittest.TestCase):
    def test_intake_never_imports_bpy_or_mathutils(self):
        files = sorted(os.path.join(folder, n) for folder, _dirs, names in os.walk(INTAKE) for n in names
                       if n.endswith(".py"))  # archive/ is a package
        self.assertIn(os.path.join(INTAKE, "archive", "__init__.py"), files)
        for path in files:
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                elif isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in (
                        "__import__", "import_module"):
                    names = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                else:
                    continue
                for name in names:
                    self.assertNotIn(name.split(".")[0], ("bpy", "mathutils"), "%s imports %s" % (path, name))


if __name__ == "__main__":
    unittest.main()
