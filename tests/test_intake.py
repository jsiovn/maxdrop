# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/intake/archive.py, the scene pack reader: no Blender, no network. Every archive is built here,
in a temp folder; where zipfile cannot write a case (encryption, Deflate64, raw non-UTF-8 names, a lying size,
several disks) its bytes are patched.

    python -I -m unittest discover tests
"""
import ast
import contextlib
import importlib
import json
import os
import shutil
import stat
import struct
import sys
import tempfile
import time
import types
import unittest
import zipfile
import zlib
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTAKE = os.path.join(ROOT, "maxdrop", "intake")

# Under a package of its own whose path is maxdrop/: `import maxdrop` would pull bpy, and archive.py imports
# ..pathnames. Zip only: the .rar and .7z backends archive.py registers are tests/test_intake_external.py's.
_PKG = "maxdrop_intake_zip_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
archive = importlib.import_module(_PKG + ".intake.archive")
for _kind in (archive.KIND_RAR, archive.KIND_7Z):
    archive._BACKENDS.pop(_kind, None)

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
        # By the stored name: getinfo() knows a backslash name only as its slash form, on Windows only.
        info = next(i for i in z.infolist() if i.orig_filename == name)
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


def to_zip64(path, declared=None):
    """Rewrite a zip with zip64 end records (zipfile writes them only past 65535 entries or 4 GiB): the zip64
    record and its locator before the end record, whose counts then say 0xFFFF. declared: the zip64 count, the
    real one when None."""
    data = read(path)
    at = data.rfind(b"PK\x05\x06")
    n, cd_size, cd_offset = struct.unpack_from("<HLL", data, at + 10)
    n = n if declared is None else declared
    record = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, n, n, cd_size, cd_offset)
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, at, 1)
    end = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF, cd_size, cd_offset, 0)
    write(path, data[:at] + record + locator + end)


def set_declared_count(path, n):
    """The entry counts of the end record (this disk and total), the central directory left as it is."""
    data = bytearray(read(path))
    at = data.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", data, at + 8, n, n)
    write(path, bytes(data))


def junction(target, link):
    """A Windows directory junction, or SkipTest elsewhere."""
    if os.name != "nt":
        raise unittest.SkipTest("junctions exist on Windows only")
    import _winapi
    _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(link))


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
        with mock.patch.object(archive, "_CANDIDATES", 3):
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
        with mock.patch.object(archive, "_CANDIDATES", 1):
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

    def test_only_the_staging_parent_is_cleaned(self):
        path = self.pack([("one.max", b"1"), ("two.max", b"2")])
        archive.unpack(path, "one.max", dest_parent=self.out)
        beside = os.path.join(self.out, archive.STAGING_PREFIX + "beside")
        os.mkdir(beside)
        self.aged(beside)
        inside_pack = os.path.join(self.out, "pack", archive.STAGING_PREFIX + "inside")
        os.mkdir(inside_pack)
        self.aged(inside_pack)
        archive.unpack(path, "two.max", dest_parent=self.out)
        self.assertTrue(os.path.isdir(beside))
        self.assertFalse(os.path.lexists(inside_pack))

    def test_a_linked_staging_folder_is_not_followed(self):
        target = os.path.join(self.tmp, "target")
        os.mkdir(target)
        write(os.path.join(target, "keep.jpg"), b"K")
        link = os.path.join(self.out, archive.STAGING_PREFIX + "link")
        junction(target, link)
        self.addCleanup(os.rmdir, link)
        stale = os.path.join(self.out, archive.STAGING_PREFIX + "old")
        os.mkdir(stale)
        with mock.patch.object(archive, "_STALE_SECONDS", -60):  # everything counts as old
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
        with mock.patch.object(archive, "_destination", racing):
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
        with mock.patch.object(archive, "_destination", racing):
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
        with mock.patch.object(archive, "_CANDIDATES", 1):
            before = files_under(self.tmp)
            with self.assertRaisesRegex(PackError, "No free folder"):
                archive.unpack(path, dest_parent=self.out)
        self.assert_clean(before)
        self.assertEqual(os.listdir(self.out), ["pack"])


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
        with mock.patch.object(archive.os, "rename", rename), mock.patch.object(archive, "_write_marker", marker), \
                mock.patch.object(archive, "_reserve", reserve), mock.patch.object(archive.shutil, "rmtree"):
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
        with mock.patch.object(archive, "_stale_reservation", judged):
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
                with mock.patch.object(archive.os, "rename", rename):
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
            stack.enter_context(mock.patch.object(archive.shutil, "rmtree"))
            if at_marker:
                stack.enter_context(mock.patch.object(archive, "_write_marker", marker))
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
        with mock.patch.object(archive.os, "rename", rename):
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
        with mock.patch.object(archive, "_stale_reservation", judged):
            self.assertFalse(archive._clear_stale_reservation(folder, ident))
        self.assertEqual(os.listdir(folder), ["third.jpg"])
        kept = [n for n in os.listdir(self.out) if n.startswith(archive.RECLAIM_PREFIX)]
        self.assertEqual(len(kept), 1)
        with mock.patch.object(archive, "_STALE_SECONDS", -60):  # everything counts as old
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
        with mock.patch.object(archive, "_stale_reservation", judged), \
                mock.patch.object(archive.os, "rename", rename):
            self.assertFalse(archive._clear_stale_reservation(folder, ident))
        self.assertFalse(os.path.lexists(folder))
        kept = [n for n in os.listdir(self.out) if n.startswith(archive.RECLAIM_PREFIX)]
        self.assertEqual(len(kept), 1)
        with mock.patch.object(archive, "_STALE_SECONDS", -60):
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
        with mock.patch.object(archive.os, "rename", rename), mock.patch.object(archive.os, "mkdir", mkdir):
            r = archive.unpack(path, dest_parent=self.out)
        self.assertEqual(r.folder, os.path.join(self.out, "pack (2)"))
        self.assertEqual(os.listdir(os.path.join(self.out, "pack")), [])
        self.assertEqual(self.listing(self.out), ["pack", "pack (2)"])

        out = tempfile.mkdtemp(dir=self.tmp)
        before = files_under(self.tmp)
        failing = mock.patch.object(archive, "_write_reservation",
                                    side_effect=[None, OSError("disk gone")])  # fine in staging, not in place
        with mock.patch.object(archive.os, "rename", rename), failing:
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
        with mock.patch.object(archive, "_STALE_SECONDS", -60):
            archive._remove_stale_staging(self.out, archive.Limits(seconds=-60))
        self.assertEqual(os.listdir(self.out), [])

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
