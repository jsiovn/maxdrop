# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/strings.py: how a file's strings decode. No Blender. Synthetic 8-bit files (3ds Max 2012
and older write their names in the saving machine's code page) through the class directory, the Scene, a layer and
a ParamBlock2 string; the choice of code page; the decision wide or 8-bit (the directories' bytes, then the writer's
version); every committed fixture is UTF-16, and the non-ASCII names of the saved_as fixtures equal their oracle's.

    python -I -m unittest discover tests
"""
import glob
import importlib
import json
import os
import struct
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
SAVED_AS = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "saved_as_*.max")))

_PKG = "maxdrop_convert_test"  # the package the convert tests make: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
cfb = importlib.import_module(_PKG + ".reader.cfb")
chunks = importlib.import_module(_PKG + ".reader.chunks")
classdir = importlib.import_module(_PKG + ".reader.classdir")
metadata = importlib.import_module(_PKG + ".reader.metadata")
pblock = importlib.import_module(_PKG + ".reader.pblock")
scene = importlib.import_module(_PKG + ".reader.scene")
strings = importlib.import_module(_PKG + ".reader.strings")
materials = importlib.import_module(_PKG + ".reader.materials")

KOREAN = "상자"  # "box" in Korean: two characters of code page 949
CYRILLIC = "Куб"  # "cube" in Russian: code page 1251


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def narrow(text, codec="ascii"):
    """A string as 3ds Max 2012 and older write it: 8-bit, ended by a NUL."""
    return text.encode(codec) + b"\0"


def wide(text):
    return text.encode("utf-16-le")


def class_entry(a, b, superclass, name, enc):
    return node(0x2040, leaf(0x2060, struct.pack("<iIII", -1, a, b, superclass)), leaf(0x2042, enc(name)))


def dll_entry(description, file, enc):
    return node(0x2038, leaf(0x2039, enc(description)), leaf(0x2037, enc(file)))


C_NODE, C_LAYER, C_MANAGER = range(3)


def directories(enc):
    classes = (class_entry(1, 0, 1, "Node", enc) +
               class_entry(0x7E9858FE, 0x1DBA1DF0, 0x10F0, "Base Layer", enc) +
               class_entry(0x0D7374FC, 0x51FF028E, 0x200, "Layer Manager", enc))
    dlls = leaf(0x21C0, b"\0" * 4) + dll_entry("Some plug-in", "some.dlo", enc) + dll_entry("Other", "other.dlu", enc)
    return classes, dlls


def scene_stream(node_name, layer_name):
    """A Layer Manager, one layer and one node on it; names as raw bytes."""
    return node(0x2014,
                node(C_MANAGER, leaf(0x2034, struct.pack("<i", 1))),
                node(C_LAYER, leaf(0x1000, b"\1\0\0\0"), leaf(0x1010, layer_name),
                     leaf(0x1020, struct.pack("<I", 0)), leaf(0x1050, struct.pack("<I", 0x8000)), leaf(0x1090, b"\0")),
                node(C_NODE, leaf(0x2035, struct.pack("<IIi", 16, 6, 1)), leaf(0x0960, struct.pack("<iI", -1, 0x800)),
                     leaf(0x0962, node_name)))


# Property sets, as tests/unit/test_metadata.py builds them.
def _pad(raw):
    return raw + b"\0" * (-len(raw) % 4)


def _lpstr(text):
    raw = text.encode("utf-8") + b"\0"
    return struct.pack("<II", metadata.VT_LPSTR, len(raw)) + _pad(raw)


def _section(props):
    head = 8 + 8 * len(props)
    offsets, body = [], b""
    for pid, value in props:
        offsets.append((pid, head + len(body)))
        body += value
    table = b"".join(struct.pack("<II", pid, off) for pid, off in offsets)
    return struct.pack("<II", head + len(body), len(props)) + table + body


def summary(fmtid, code_page=None, version=None):
    props = []
    if code_page is not None:
        props.append((1, struct.pack("<Ihh", metadata.VT_I2, code_page - 65536 if code_page > 32767 else code_page,
                                     0)))
    if version is not None:
        pairs = [_lpstr("General"), struct.pack("<Ii", metadata.VT_I4, 1)]
        props.append((12, struct.pack("<II", metadata.VT_VECTOR | metadata.VT_VARIANT, 2) + b"".join(pairs)))
        part = ("3ds Max Version: %s" % version).encode("utf-8") + b"\0"
        props.append((13, struct.pack("<III", metadata.VT_VECTOR | metadata.VT_LPSTR, 1, len(part)) + _pad(part)))
    sec = _section(props)
    return (b"\xfe\xff\x00\x00\x0a\x00\x02\x00" + b"\0" * 16 + struct.pack("<I", 1) + fmtid.bytes_le +
            struct.pack("<I", 48) + sec)


class Stream(bytes):
    """A stream of a FakeFile: bytes-like for the chunk reader, read() and size for the summary reader."""

    @property
    def size(self):
        return len(self)

    def read(self):
        return bytes(self)


class FakeFile:
    def __init__(self, **streams):
        names = {"doc_summary": metadata.DOC_SUMMARY, "summary": "\x05SummaryInformation"}
        self.streams = {names.get(k, k): Stream(v) for k, v in streams.items() if v is not None}

    def exists(self, name):
        return name in self.streams

    def open(self, name, decompress=True):
        return self.streams[name]


def old_file(node_name, layer_name, code_page=None, version="14.00", enc=None):
    classes, dlls = directories(enc or narrow)
    doc = summary(metadata.FMTID_DOC_SUMMARY, code_page, version) if code_page or version else None
    return FakeFile(ClassDirectory3=classes, DllDirectory=dlls, Scene=scene_stream(node_name, layer_name),
                    doc_summary=doc)


def read_names(cf, encoding="AUTO"):
    sc = scene.Scene.from_file(cf, encoding=encoding)
    (i,) = sc.node_indices
    (layer,) = sc.layers()
    return sc.node(i).name, layer.name, sc.classes[C_LAYER].name, sc.classes.dlls[0].file


class TestText(unittest.TestCase):
    def test_wide(self):
        self.assertEqual(strings.UNICODE.text(wide("Box" + KOREAN)), "Box" + KOREAN)
        self.assertEqual(strings.UNICODE.text(wide("Box") + b"\0"), "Box")  # an odd byte is dropped
        self.assertEqual(strings.Strings(True, "cp949").text(wide("Box")), "Box")  # the choice is for 8-bit only

    def test_narrow_cut_at_nul(self):
        self.assertEqual(strings.Strings(False, "cp1252").text(b"Box\0junk"), "Box")
        self.assertEqual(strings.Strings(False, "cp1252").text(b"Box"), "Box")

    def test_auto_utf8_then_cp1252(self):
        auto = strings.Strings(False)
        self.assertEqual(auto.text(narrow("Boïte", "utf-8")), "Boïte")
        self.assertEqual(auto.text(narrow("Boïte", "cp1252")), "Boïte")

    def test_code_page(self):
        self.assertEqual(strings.Strings(False, "cp949").text(narrow(KOREAN, "cp949")), KOREAN)
        self.assertEqual(strings.Strings(False, "cp1251").text(narrow(CYRILLIC, "cp1251")), CYRILLIC)

    def test_unknown_codec(self):
        with self.assertRaises(ValueError):
            strings.Strings(False, "rot13")
        with self.assertRaises(ValueError):
            strings.of_file(FakeFile(), "rot13")

    def test_choices_are_codecs(self):
        for codec, _label in strings.CHOICES:
            "x".encode(codec)
        self.assertNotIn(1200, strings.CODE_PAGES)
        self.assertNotIn(65001, strings.CODE_PAGES)


class TestLooksWide(unittest.TestCase):
    def test_votes(self):
        self.assertTrue(strings.looks_wide([(b"N\0", 8), (b"B\0", 20)]))
        self.assertFalse(strings.looks_wide([(b"No", 5), (b"Ba", 11)]))
        self.assertIsNone(strings.looks_wide([]))
        self.assertIsNone(strings.looks_wide([(b"N", 1), (b"N\0", 2), (b"Na", 3)]))  # too short, then a tie
        self.assertIsNone(strings.looks_wide([(b"N\0", 7)]))  # an odd count is not UTF-16, a NUL second not 8-bit
        self.assertFalse(strings.looks_wide([(b"No", 5), (b"Ba", 11), (b"N\0", 8)]))  # the majority


class TestSyntheticOldFile(unittest.TestCase):
    """An 8-bit file round-trips its non-ASCII names through the class directory, the Scene and a layer."""

    def test_recorded_code_page(self):
        cf = old_file(narrow("Box" + KOREAN, "cp949"), narrow("Layer" + KOREAN, "cp949"), code_page=949)
        self.assertEqual(strings.of_file(cf), strings.Strings(False, "cp949"))
        self.assertEqual(read_names(cf), ("Box" + KOREAN, "Layer" + KOREAN, "Base Layer", "some.dlo"))

    def test_auto_without_code_page(self):
        cf = old_file(narrow("Boïte", "cp1252"), narrow("Calqueé", "utf-8"), code_page=65001)
        self.assertEqual(strings.of_file(cf), strings.Strings(False))
        self.assertEqual(read_names(cf)[:2], ("Boïte", "Calqueé"))

    def test_choice_wins_over_recorded(self):
        cf = old_file(narrow(CYRILLIC, "cp1251"), narrow("0"), code_page=1252)
        self.assertEqual(read_names(cf, "cp1251")[0], CYRILLIC)
        self.assertNotEqual(read_names(cf)[0], CYRILLIC)  # Auto believed the 1252 the file records

    def test_choice_ignored_on_wide(self):
        cf = old_file(wide("Box" + KOREAN), ("Layer" + KOREAN).encode("utf-8"), version="22.00", enc=wide)
        self.assertIs(strings.of_file(cf, "cp949"), strings.UNICODE)
        self.assertEqual(read_names(cf, "cp949"), ("Box" + KOREAN, "Layer" + KOREAN, "Base Layer", "some.dlo"))

    def test_bytes_decide_before_version(self):
        """3ds Max 2015 saving in the 2012 format writes UTF-16; a summary claiming 2020 over 8-bit names loses."""
        cf = old_file(wide("Box"), b"0", version="14.00", enc=wide)
        self.assertIs(strings.of_file(cf), strings.UNICODE)
        cf = old_file(narrow("Box"), narrow("0"), version="22.00")
        self.assertFalse(strings.of_file(cf).wide)

    def test_version_when_bytes_say_nothing(self):
        empty = dict(ClassDirectory3=b"", Scene=scene_stream(narrow("Box"), narrow("0")))
        for version, is_wide in (("14.00", False), ("12.00", False), ("15.00", True), ("22.00", True)):
            cf = FakeFile(doc_summary=summary(metadata.FMTID_DOC_SUMMARY, version=version), **empty)
            self.assertEqual(strings.of_file(cf).wide, is_wide, version)
        self.assertIs(strings.of_file(FakeFile(**empty)), strings.UNICODE)  # nothing says: UTF-16

    def test_code_page_from_summary_information(self):
        cf = old_file(narrow(KOREAN, "cp949"), narrow("0"), code_page=None, version=None)
        cf.streams["\x05SummaryInformation"] = Stream(summary(metadata.FMTID_SUMMARY, 949))
        self.assertEqual(strings.of_file(cf).codec, "cp949")

    def test_damaged_summary_records_nothing(self):
        cf = old_file(narrow("Box"), narrow("0"), code_page=None, version=None)
        cf.streams[metadata.DOC_SUMMARY] = Stream(b"\xfe\xff garbage")
        self.assertEqual(strings.of_file(cf), strings.Strings(False))

    def test_material_name(self):
        holder = node(0x4000, leaf(0x4001, narrow("Mat" + KOREAN, "cp949")))
        top = chunks.index(node(5, holder), strings=strings.Strings(False, "cp949"))
        self.assertEqual(materials._name(top[0]), "Mat" + KOREAN)

    def test_param_block_string(self):
        entry = struct.pack("<HIII", 7, pblock.STRING, 0, 0) + b"\x40"
        raw = narrow("map" + KOREAN + ".jpg", "cp949")
        block = node(0x82, leaf(0x0009, struct.pack("<IHIHI", 9, 1, 0x55F03700, 1, 7)),
                     leaf(0x100E, entry + struct.pack("<I", len(raw)) + raw))
        pb = pblock.ParamBlock2.from_chunk(chunks.index(block, strings=strings.Strings(False, "cp949"))[0])
        self.assertEqual(pb.get(7), "map" + KOREAN + ".jpg")
        pb = pblock.ParamBlock2.from_chunk(chunks.index(block)[0])  # the same bytes read as UTF-16: not the name
        self.assertNotEqual(pb.get(7), "map" + KOREAN + ".jpg")


def _oracle(path):
    with open(path[:-4] + ".oracle.json", encoding="ascii") as f:
        return json.load(f)


class TestFixtures(unittest.TestCase):
    def test_every_fixture_is_utf16(self):
        for path in FIXTURES:
            with self.subTest(os.path.basename(path)), cfb.CompoundFile(path) as cf:
                self.assertIs(strings.of_file(cf), strings.UNICODE)
                self.assertIs(strings.of_file(cf, "cp949"), strings.UNICODE)

    @unittest.skipUnless(SAVED_AS, "tests/fixtures/saved_as_*.max are missing")
    def test_non_ascii_names_round_trip(self):
        """saved_as_2017/2018/2019 (tools/fixtures/saved_as.ms): node, material and layer names with U+00F6, U+00E4
        and U+4E2D, as 3ds Max reports them."""
        self.assertEqual([os.path.basename(p) for p in SAVED_AS],
                         ["saved_as_2017.max", "saved_as_2018.max", "saved_as_2019.max"])
        for path in SAVED_AS:
            o = _oracle(path)
            with self.subTest(os.path.basename(path)), cfb.CompoundFile(path) as cf:
                sc = scene.Scene.from_file(cf)
                names = [sc.node(i).name for i in sc.node_indices]
                self.assertEqual(names, [n["name"] for n in o["nodes"]])
                self.assertEqual(names, ["FixtureBöx中"])
                layers = [la.name for la in sc.layers()]
                self.assertEqual(layers, [la["name"] for la in o["layers"]])
                self.assertIn("FixtureLäyer中", layers)
                graph = materials.MaterialGraph(sc)
                (i,) = sc.node_indices
                mat = sc.node(i).refs.get(scene.SLOT_MATERIAL)
                self.assertEqual(graph.get(mat).name, o["materials"][0]["name"])
                self.assertEqual(o["materials"][0]["name"], "FixtureRöt中")


if __name__ == "__main__":
    unittest.main()
