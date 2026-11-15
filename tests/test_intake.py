# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/intake/archive.py, the scene pack reader: no Blender, no network. Every archive is built here,
in a temp folder; where zipfile cannot write a case (encryption, Deflate64, raw non-UTF-8 names, a lying size,
several disks) its bytes are patched.

    python -I -m unittest discover tests
"""
import ast
import importlib.util
import json
import os
import shutil
import stat
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTAKE = os.path.join(ROOT, "maxdrop", "intake")

# By path: `import maxdrop` would pull bpy.
_spec = importlib.util.spec_from_file_location("maxdrop_intake_archive", os.path.join(INTAKE, "archive.py"))
archive = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = archive
_spec.loader.exec_module(archive)

PackError = archive.PackError


def write_zip(path, files, compression=zipfile.ZIP_DEFLATED):
    """files: (name, data) pairs, or (ZipInfo, data). A name is stored exactly as given (zipfile would turn a
    backslash into a slash on Windows)."""
    with zipfile.ZipFile(path, "w", compression) as z:
        for name, data in files:
            if isinstance(name, zipfile.ZipInfo):
                info = name
            else:
                info = zipfile.ZipInfo("placeholder", date_time=(2020, 1, 1, 0, 0, 0))
                info.filename = name
            info.compress_type = compression
            z.writestr(info, data)
    return path


def patch_entry(path, name, flags=0, method=None, size=None, volume=None):
    """Patch the local header and the central directory record of one entry."""
    with zipfile.ZipFile(path) as z:
        info = z.getinfo(name)
        start = z.start_dir
    raw = info.orig_filename.encode("utf-8" if info.flag_bits & 0x800 else "cp437")
    data = bytearray(read(path))
    local, central = info.header_offset, None
    pos = start
    while data[pos:pos + 4] == b"PK\x01\x02":
        nlen, xlen, clen = struct.unpack_from("<HHH", data, pos + 28)
        if bytes(data[pos + 46:pos + 46 + nlen]) == raw:
            central = pos
            break
        pos += 46 + nlen + xlen + clen
    assert central is not None
    for at, flag_at, method_at, size_at in ((local, 6, 8, 22), (central, 8, 10, 24)):
        struct.pack_into("<H", data, at + flag_at, struct.unpack_from("<H", data, at + flag_at)[0] | flags)
        if method is not None:
            struct.pack_into("<H", data, at + method_at, method)
        if size is not None:
            struct.pack_into("<L", data, at + size_at, size)
    if volume is not None:
        struct.pack_into("<H", data, central + 34, volume)
    write(path, bytes(data))


def replace_bytes(path, old, new):
    assert len(old) == len(new)
    data = read(path)
    assert data.count(old) == 2  # local header and central directory
    write(path, data.replace(old, new))


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data=b""):
    with open(path, "wb") as f:
        f.write(data)


def files_under(root):
    found = set()
    for folder, _dirs, files in os.walk(root):
        found.update(os.path.join(folder, f) for f in files)
    return found


def inside(path, folder):
    return os.path.commonpath([os.path.abspath(path), os.path.abspath(folder)]) == os.path.abspath(folder)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maxdrop-intake-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = os.path.join(self.tmp, "out")
        os.mkdir(self.out)

    def pack(self, files, name="pack.zip", **kw):
        return write_zip(os.path.join(self.tmp, name), files, **kw)

    def assert_clean(self, before):
        """Nothing written anywhere: no new file, no staging folder left."""
        self.assertEqual(files_under(self.tmp), before)
        for folder, dirs, _files in os.walk(self.tmp):
            for d in dirs:
                self.assertFalse(d.startswith(archive.STAGING_PREFIX), os.path.join(folder, d))

    def listing(self, folder):
        return sorted(os.listdir(folder))


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
                                (archive.Limits(entries=2), "lists 3 entries"),
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


class Unreadable(Base):
    def test_encrypted_entry(self):
        path = self.pack([("room.max", b"MAX"), ("secret.jpg", b"S")])
        patch_entry(path, "secret.jpg", flags=0x1)
        listing = archive.list_pack(path)
        self.assertEqual(listing.encrypted, ["secret.jpg"])
        self.assertTrue(any("encrypted" in p for p in listing.problems))
        before = files_under(self.tmp)
        with self.assertRaisesRegex(PackError, "secret.jpg is encrypted.*Extract the archive by hand"):
            archive.unpack(path, dest_parent=self.out)
        self.assert_clean(before)

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

    def test_existing_folder_says_what_unpack_will_use(self):
        path = self.pack([("Pack/room.max", b"MAX"), ("Pack/wood.jpg", b"J")])
        before = files_under(self.tmp)
        self.assertIsNone(archive.existing_folder(path, "Pack/room.max", False, self.out))
        self.assertEqual(files_under(self.tmp), before)
        mine = os.path.join(self.out, "pack", "Pack")
        os.makedirs(mine)
        write(os.path.join(mine, "room.max"))
        self.assertEqual(archive.existing_folder(path, "Pack/room.max", False, self.out),
                         ("in_place", os.path.join(mine, "room.max")))
        shutil.rmtree(os.path.join(self.out, "pack"))
        r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(archive.existing_folder(path, "Pack/room.max", False, self.out), ("reused", r.max_path))
        self.assertIsNone(archive.existing_folder(os.path.join(self.tmp, "gone.zip"), "room.max", False, self.out))

    def test_existing_folder_of_one_scene_among_several(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2")])
        self.assertIsNone(archive.existing_folder(path, "two.max", True, self.out))
        r = archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertEqual(archive.existing_folder(path, "two.max", True, self.out), ("reused", r.max_path))
        self.assertIsNone(archive.existing_folder(path, "one.max", True, self.out))

    def test_unsafe_archive_or_scene_stem_falls_back(self):
        path = self.pack([("a/CON .max", b"x"), ("good.max", b"1"), ("b/end..max", b"2")], name="pack.zip")
        r = archive.unpack(path, "good.max", dest_parent=self.out)
        self.assertEqual(r.folder, os.path.join(self.out, "pack", "good"))
        self.assertEqual(archive._safe_stem("end..max", "scene"), "scene")
        self.assertEqual(archive._safe_stem("CON.zip", "pack"), "pack")


class NoBlender(unittest.TestCase):
    def test_intake_never_imports_bpy_or_mathutils(self):
        files = [os.path.join(INTAKE, n) for n in sorted(os.listdir(INTAKE)) if n.endswith(".py")]
        self.assertIn(os.path.join(INTAKE, "archive.py"), files)
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
