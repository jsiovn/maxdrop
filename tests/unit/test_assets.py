# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/assets.py: the asset table on synthetic FileAssetMetaData2 / 3 streams (layout,
damaged and hostile input), and on the committed fixtures, where every Bitmap's file equals the file name 3ds Max
reports in the oracle. No Blender.

    python -I -m unittest discover tests
"""
import glob
import importlib.util
import json
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
FIXTURES = sorted(glob.glob(os.path.join(FIXTURE_DIR, "*.max")))
ASSET_COUNTS = {"vray_maps": 7, "standard_physical": 1, "texmap_rules": 22}  # every other fixture names no file


def _load(name, path, package_dir=None):
    if name in sys.modules:
        return sys.modules[name]
    kw = {"submodule_search_locations": [package_dir]} if package_dir else {}
    spec = importlib.util.spec_from_file_location(name, path, **kw)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_READER = os.path.join(ROOT, "maxdrop", "reader")
_load("maxdrop_reader", os.path.join(_READER, "__init__.py"), _READER)
cfb = _load("maxdrop_reader.cfb", os.path.join(_READER, "cfb.py"))
classids = _load("maxdrop_reader.classids", os.path.join(_READER, "classids.py"))
scene = _load("maxdrop_reader.scene", os.path.join(_READER, "scene.py"))
pblock = _load("maxdrop_reader.pblock", os.path.join(_READER, "pblock.py"))
materials = _load("maxdrop_reader.materials", os.path.join(_READER, "materials.py"))
assets = _load("maxdrop_reader.assets", os.path.join(_READER, "assets.py"))
AssetTable, AssetEntry = assets.AssetTable, assets.AssetEntry


def wstr(text):
    units = text.encode("utf-16-le")
    return struct.pack("<I", len(units) // 2) + units + b"\0\0"


def record(guid, kind, path, resolved=None):
    out = guid + wstr(kind) + wstr(path)
    return out if resolved is None else out + wstr(resolved)


G1, G2, G3 = bytes(range(16)), bytes(range(16, 32)), bytes(range(32, 48))


class LayoutTest(unittest.TestCase):
    def test_v3_records(self):
        data = record(G1, "Bitmap", "wood.jpg", r"D:\maps\wood.jpg") + record(G2, "Photometric", r"C:\ies\a.ies", "")
        t = AssetTable.parse(data, 3)
        self.assertEqual(t.issues, [])
        self.assertEqual(len(t), 2)
        self.assertEqual(t.get(G1), AssetEntry(G1, "Bitmap", "wood.jpg", r"D:\maps\wood.jpg"))
        self.assertEqual(t.get(G2).type, "Photometric")
        self.assertEqual(t.get(G2).name, "a.ies")
        self.assertEqual([e.guid for e in t], [G1, G2])

    def test_v2_records(self):
        t = AssetTable.parse(record(G1, "Bitmap", "a.png") + record(G2, "Bitmap", "maps/b.png"), 2)
        self.assertEqual(t.issues, [])
        self.assertEqual(t.get(G2), AssetEntry(G2, "Bitmap", "maps/b.png", ""))
        self.assertEqual(t.get(G2).name, "b.png")

    def test_empty_stream(self):
        t = AssetTable.parse(b"", 3)
        self.assertEqual((len(t), t.issues), (0, []))

    def test_name_falls_back_to_the_resolved_path(self):
        self.assertEqual(AssetEntry(G1, "Bitmap", "", r"C:\x\y.tga").name, "y.tga")
        self.assertEqual(AssetEntry(G1, "Bitmap", r"\\host\share\z.jpg", "").name, "z.jpg")
        self.assertEqual(AssetEntry(G1, "Bitmap", "", "").name, "")

    def test_get_takes_an_asset_value(self):
        t = AssetTable.parse(record(G1, "Bitmap", "a.png", ""), 3)
        self.assertEqual(t.get(pblock.Asset(G1)).path, "a.png")
        self.assertEqual(t.entry(pblock.Asset(G1)).path, "a.png")
        self.assertIsNone(t.entry(G1))  # raw bytes are not a parameter's asset value
        self.assertIsNone(t.entry(pblock.Reference(3)))
        self.assertIsNone(t.get(G2))

    def test_strings_must_be_two_or_three(self):
        with self.assertRaises(ValueError):
            AssetTable.parse(b"", 4)


class DamagedTest(unittest.TestCase):
    def test_count_past_the_end_keeps_the_records_before(self):
        good = record(G1, "Bitmap", "a.png", "")
        bad = G2 + wstr("Bitmap") + struct.pack("<I", 500) + "b.png".encode("utf-16-le")
        t = AssetTable.parse(good + bad, 3)
        self.assertEqual([e.guid for e in t], [G1])
        self.assertEqual(len(t.issues), 1)
        self.assertIn("leaves the stream", t.issues[0])

    def test_missing_nul(self):
        bad = G1 + struct.pack("<I", 1) + "ab".encode("utf-16-le")
        t = AssetTable.parse(bad + record(G2, "Bitmap", "x", ""), 3)
        self.assertEqual(len(t), 0)
        self.assertIn("NUL", t.issues[0])

    def test_short_guid(self):
        t = AssetTable.parse(record(G1, "Bitmap", "a", "") + b"\x01\x02", 3)
        self.assertEqual(len(t), 1)
        self.assertIn("asset id", t.issues[0])

    def test_over_long_string(self):
        bad = G1 + struct.pack("<I", assets.MAX_STRING + 1) + b"\0" * 64
        t = AssetTable.parse(bad, 3)
        self.assertEqual(len(t), 0)
        self.assertIn("longer than", t.issues[0])

    def test_repeated_id_keeps_the_first(self):
        t = AssetTable.parse(record(G1, "Bitmap", "first.png", "") + record(G1, "Bitmap", "second.png", ""), 3)
        self.assertEqual(t.get(G1).path, "first.png")
        self.assertIn("twice", t.issues[0])

    def test_wrong_layout_is_an_issue_not_an_exception(self):
        # a v2 stream read as v3: the third string swallows the next record's id
        data = record(G1, "Bitmap", "a.png") + record(G2, "Bitmap", "b.png") + record(G3, "Bitmap", "c.png")
        t = AssetTable.parse(data, 3)
        self.assertLess(len(t), 3)
        self.assertTrue(t.issues)

    def test_bad_utf16_is_replaced(self):
        data = G1 + wstr("Bitmap") + struct.pack("<I", 1) + b"\x00\xd8" + b"\0\0" + wstr("")
        t = AssetTable.parse(data, 3)
        self.assertEqual(t.get(G1).path, "\ufffd")

    def test_oversized_stream_is_not_read(self):
        old = assets.MAX_STREAM
        assets.MAX_STREAM = 10
        try:
            t = AssetTable.parse(record(G1, "Bitmap", "a.png", ""), 3)
        finally:
            assets.MAX_STREAM = old
        self.assertEqual(len(t), 0)
        self.assertIn("larger than", t.issues[0])


def _oracle(path):
    with open(path[:-len(".max")] + ".oracle.json", encoding="ascii") as f:
        return json.load(f)


def _cid(hex_pair):
    return tuple(int(h, 16) for h in hex_pair)


def _oracle_file_names(oracle):
    """{(class id, name): fileName} of every Bitmap in the oracle's material graph."""
    out = {}
    for e in oracle["material_graph"]:
        if _cid(e["class_id"]) != tuple(classids.BITMAP_TEX):
            continue
        for b in e["blocks"]:
            for p in b.get("params", ()):
                if p["name"] == "fileName":
                    out[(_cid(e["class_id"]), e["name"])] = p["value"]
    return out


class FakeFile:
    """A compound file with the given streams (bytes, or an exception that open raises)."""

    def __init__(self, streams):
        self.streams, self.read_called = streams, False

    def exists(self, name):
        return name in self.streams

    def open(self, name, max_size=None):
        value = self.streams[name]
        if isinstance(value, Exception):
            raise value
        outer = self

        class Stream:
            def __len__(self):
                return len(value)

            def read(self):
                outer.read_called = True
                return value
        return Stream()


class FixtureTest(unittest.TestCase):
    def test_every_fixture(self):
        checked = 0
        for path in FIXTURES:
            name = os.path.basename(path)[:-4]
            with self.subTest(name), cfb.CompoundFile(path) as cf:
                t = AssetTable.from_file(cf)
                self.assertEqual(t.issues, [])
                self.assertEqual(t.stream, "FileAssetMetaData3")
                self.assertEqual(len(t), ASSET_COUNTS.get(name, 0))
                expected = _oracle_file_names(_oracle(path))
                s = scene.Scene.from_file(cf)
                g = materials.MaterialGraph(s)
                found = {}
                for i in g.walk(s.node(n).material for n in s.walk()):
                    m = g.get(i)
                    entry = assets.bitmap_file(t, m)
                    if entry is not None:
                        found[(tuple(m.class_id), m.name)] = entry.name
                        self.assertEqual(entry.type, "Bitmap")
                        self.assertIn((0, assets.BITMAP_FILE, entry), assets.files_of(t, m))
                    elif tuple(m.class_id) == tuple(classids.BITMAP_TEX):
                        self.fail("%s: Bitmap %r without a file" % (name, m.name))
                    else:
                        self.assertEqual(assets.files_of(t, m), [], "%s %s" % (name, m.name))
                self.assertEqual(found, expected)
                checked += len(found)
                del cf
        self.assertEqual(checked, sum(ASSET_COUNTS.values()))

    def test_falls_back_to_the_older_stream(self):
        data = record(G1, "Bitmap", "a.png") + record(G2, "Photometric", "b.ies")
        t = AssetTable.from_file(FakeFile({"FileAssetMetaData2": data}))
        self.assertEqual((t.stream, len(t), t.issues), ("FileAssetMetaData2", 2, []))
        both = FakeFile({"FileAssetMetaData2": data, "FileAssetMetaData3": record(G3, "Bitmap", "c.png", "")})
        self.assertEqual([e.guid for e in AssetTable.from_file(both)], [G3])

    def test_unreadable_or_oversized_stream(self):
        t = AssetTable.from_file(FakeFile({"FileAssetMetaData3": cfb.CfbError("broken chain")}))
        self.assertEqual((len(t), t.stream), (0, "FileAssetMetaData3"))
        self.assertIn("broken chain", t.issues[0])
        big = FakeFile({"FileAssetMetaData3": b"x" * 64})
        old = assets.MAX_STREAM
        assets.MAX_STREAM = 10
        try:
            t = AssetTable.from_file(big)
        finally:
            assets.MAX_STREAM = old
        self.assertIn("larger than", t.issues[0])
        self.assertFalse(big.read_called)

    def test_files_of_reads_parts_too(self):
        t = AssetTable.parse(record(G1, "Bitmap", "a.png", "") + record(G2, "Bitmap", "b.png", ""), 3)
        own = pblock.ParamBlock2(0, 1, 0, {9: pblock.Param(9, 9, 0, (pblock.Asset(G1),), b"", None),
                                           3: pblock.Param(3, 0, 0, (1.0,), b"", None)})
        part_block = pblock.ParamBlock2(2, 1, 0, {4: pblock.Param(4, 9 | pblock.TABLE, 0,
                                                                  (pblock.Asset(G3), pblock.Asset(G2)), b"", None)})
        part = materials.Part(7, classids.BITMAP_TEX, classids.SC_UVGEN, {0: part_block}, {})
        m = materials.MtlBase(1, (1, 2), classids.SC_TEXMAP, "m", {}, {1: own}, {}, {5: part}, [], [])
        self.assertEqual(assets.files_of(t, m), [(0, 9, t.get(G1)), (2, 4, t.get(G2))])
        self.assertIsNone(assets.bitmap_file(t, m))  # not a Bitmap

    def test_no_stream_is_an_empty_table(self):
        class NoStreams:
            def exists(self, name):
                return False
        t = AssetTable.from_file(NoStreams())
        self.assertEqual((len(t), t.issues, t.stream), (0, [], None))


if __name__ == "__main__":
    unittest.main()
