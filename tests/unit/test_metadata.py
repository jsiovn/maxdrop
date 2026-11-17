# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/metadata.py, the pre-flight facts of a .max: no Blender. Every committed fixture
against its 3ds Max oracle (version, renderer, node and material counts), that no user, computer, author, node or
material name and no path comes back, and synthetic property-set streams, damaged ones included.

    python -I -m unittest discover tests
"""
import glob
import importlib.util
import json
import os
import struct
import sys
import unittest
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))


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
metadata = _load("maxdrop_reader.metadata", os.path.join(_READER, "metadata.py"))
MetadataError = metadata.MetadataError

# What tools/sanitize_fixture.py leaves in place of the user and computer name, and words that must not appear.
SANITISED = "xxxxx"
FORBIDDEN_WORDS = ("user", "computer", "author", "xxx", "\\", "/")


def _walk(value):
    """Every key and value of a nested dict / list as strings."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _walk(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk(v)
    else:
        yield str(value)


def _pad(raw):
    return raw + b"\0" * (-len(raw) % 4)


def i2(v):
    return struct.pack("<Ihh", metadata.VT_I2, v, 0)


def i4(v):
    return struct.pack("<Ii", metadata.VT_I4, v)


def lpstr(text, vt=metadata.VT_LPSTR):
    raw = text.encode("utf-8") + b"\0"
    return struct.pack("<II", vt, len(raw)) + _pad(raw)


def _lpstr_body(text):
    raw = text.encode("utf-8") + b"\0"
    return struct.pack("<I", len(raw)) + _pad(raw)


def lpwstr(text):
    raw = (text + "\0").encode("utf-16-le")
    return struct.pack("<II", metadata.VT_LPWSTR, len(raw) // 2) + _pad(raw)


def vector_lpstr(items):
    return struct.pack("<II", metadata.VT_VECTOR | metadata.VT_LPSTR, len(items)) + b"".join(map(_lpstr_body, items))


def vector_variant(items):
    body = b"".join(lpstr(x) if isinstance(x, str) else i4(x) for x in items)
    return struct.pack("<II", metadata.VT_VECTOR | metadata.VT_VARIANT, len(items)) + body


def section(props):
    """props: [(pid, encoded value)]."""
    head = 8 + 8 * len(props)
    offsets, body = [], b""
    for pid, value in props:
        offsets.append((pid, head + len(body)))
        body += value
    table = b"".join(struct.pack("<II", pid, off) for pid, off in offsets)
    return struct.pack("<II", head + len(body), len(props)) + table + body


def stream(*sections):
    """sections: [(uuid, section bytes)]."""
    head = 28 + 20 * len(sections)
    out, listing = b"", b""
    for fmtid, sec in sections:
        listing += fmtid.bytes_le + struct.pack("<I", head + len(out))
        out += sec
    return b"\xfe\xff\x00\x00\x0a\x00\x02\x00" + b"\0" * 16 + struct.pack("<I", len(sections)) + listing + out


def doc_summary(groups, codepage=65001):
    pairs, parts = [], []
    for heading, items in groups:
        pairs += [heading, len(items)]
        parts += items
    return stream((metadata.FMTID_DOC_SUMMARY, section([(1, i2(codepage - 65536 if codepage > 32767 else codepage)),
                                                        (12, vector_variant(pairs)), (13, vector_lpstr(parts))])))


GROUPS = [
    ("General", ["3ds Max Version: 27.00", "Compressed", "Build: 27.0.0.1", "Saved As Version: 25.00"]),
    ("Mesh Totals", ["Vertices: 12", "Faces: 7"]),
    ("Scene Totals", ["Objects: 3", "Shapes: 1", "Lights: 2", "Cameras: 1", "Helpers: 0", "Space Warps: 0",
                      "Total: 7"]),
    ("External Dependencies", ["C:\\Users\\alice\\maps\\wood.jpg"]),
    ("Objects", ["SecretNode", "OtherNode", "Third"]),
    ("Materials", ["SecretMat", "OtherMat"]),
    ("Used Plug-Ins", ["vrender.dlr", "epoly.dlo"]),
    ("Render Data", ["User Name=alice", "Computer Name=ALICE-PC", "Renderer ClassIDA=1941615238",
                     "Renderer ClassIDB=2012806412", "Renderer Name=V-Ray 6"]),
]


def _summary(data):
    return metadata.summarize(metadata.groups(metadata.property_sets(data)[metadata.FMTID_DOC_SUMMARY]))


@unittest.skipUnless(FIXTURES, "no fixtures")
class TestFixtures(unittest.TestCase):
    def _info(self, path):
        with cfb.CompoundFile(path) as cf:
            return metadata.read(cf)

    def test_against_the_oracle(self):
        for path in FIXTURES:
            with self.subTest(os.path.basename(path)):
                with open(path[:-4] + ".oracle.json", encoding="ascii") as f:
                    oracle = json.load(f)
                info = self._info(path)
                self.assertEqual(info["max_version"], "22.00")
                self.assertEqual(info["max_release"], oracle["max_version"][1])
                self.assertEqual(info["saved_as_version"], "22.00")
                self.assertFalse(info["compressed"])
                self.assertEqual(info["renderer"]["name"], "Scanline Renderer")
                self.assertEqual(info["renderer"]["class_id"],
                                 tuple(int(x, 16) for x in oracle["renderer"]["class_id"]))
                self.assertEqual(info["counts"]["total"], oracle["node_count"])
                self.assertEqual(info["counts"]["materials"], len(oracle["materials"]))
                # the evaluated meshes, after the modifiers (modifier_pivot's TurboSmooth: 74, not 20)
                self.assertEqual(info["counts"]["vertices"], sum(n.get("eval_verts") or 0 for n in oracle["nodes"]))
                self.assertIn("ctrl.dlc", info["plugins"])

    def test_no_identity_or_names(self):
        for path in FIXTURES:
            with self.subTest(os.path.basename(path)):
                with open(path[:-4] + ".oracle.json", encoding="ascii") as f:
                    oracle = json.load(f)
                names = {n["name"] for n in oracle["nodes"]} | {m["name"] for m in oracle["materials"]}
                for text in _walk(self._info(path)):
                    low = text.lower()
                    self.assertNotIn(SANITISED, low)
                    for word in FORBIDDEN_WORDS:
                        self.assertNotIn(word, low)
                    for name in names:
                        self.assertNotIn(name.lower(), low)


class TestSynthetic(unittest.TestCase):
    def test_summary(self):
        info = _summary(doc_summary(GROUPS))
        self.assertEqual(info, {
            "max_version": "27.00", "max_release": 2025, "saved_as_version": "25.00", "build": "27.0.0.1",
            "compressed": True,
            "counts": {"vertices": 12, "faces": 7, "objects": 3, "shapes": 1, "lights": 2, "cameras": 1,
                       "helpers": 0, "space_warps": 0, "total": 7, "materials": 2},
            "renderer": {"name": "V-Ray 6", "class_id": (1941615238, 2012806412)},
            "plugins": ["vrender.dlr", "epoly.dlo"],
        })

    def test_identity_never_returned(self):
        text = " ".join(_walk(_summary(doc_summary(GROUPS)))).lower()
        for secret in ("alice", "secret", "othernode", "othermat", "third", "wood", "users"):
            self.assertNotIn(secret, text)

    def test_missing_groups_leave_keys_out(self):
        self.assertEqual(_summary(doc_summary([("General", ["3ds Max Version: 9.00"])])), {"max_version": "9.00"})
        self.assertEqual(_summary(doc_summary([])), {})

    def test_release_years(self):
        self.assertEqual(metadata.release("10.00"), 2008)
        self.assertEqual(metadata.release("22.00"), 2020)
        self.assertEqual(metadata.release("28.00"), 2026)
        self.assertIsNone(metadata.release("9.00"))
        self.assertIsNone(metadata.release("abc"))
        self.assertIsNone(metadata.release(None))

    def test_utf16_codepage_and_lpwstr(self):
        raw = "ab\0".encode("utf-16-le")
        wide_lpstr = struct.pack("<II", metadata.VT_LPSTR, len(raw)) + _pad(raw)
        data = stream((metadata.FMTID_DOC_SUMMARY, section([(1, i2(1200)), (2, lpwstr("Ünïcode")),
                                                            (3, wide_lpstr)])))
        props = metadata.property_sets(data)[metadata.FMTID_DOC_SUMMARY]
        self.assertEqual(props[2], "Ünïcode")
        self.assertEqual(props[3], "ab")  # in a code page 1200 section a VT_LPSTR is UTF-16, its count in bytes

    def test_other_sections_and_types_are_skipped(self):
        other = uuid.UUID("F29F85E0-4FF9-1068-AB91-08002B27B3D9")
        filetime = struct.pack("<IQ", 0x40, 0)
        data = stream((other, section([(4, lpstr("alice")), (12, filetime)])))
        self.assertEqual(metadata.property_sets(data), {other: {4: "alice"}})
        self.assertEqual(_summary_or_empty(data), {})


def _summary_or_empty(data):
    props = metadata.property_sets(data).get(metadata.FMTID_DOC_SUMMARY)
    return {} if props is None else metadata.summarize(metadata.groups(props))


class TestDamaged(unittest.TestCase):
    def assertRefused(self, data):
        with self.assertRaises(MetadataError):
            metadata.property_sets(data)

    def test_not_a_property_set(self):
        self.assertRefused(b"")
        self.assertRefused(b"\0" * 64)

    def test_too_many_sections(self):
        data = bytearray(stream())
        struct.pack_into("<I", data, 24, 1000)
        self.assertRefused(bytes(data))

    def test_section_past_the_stream(self):
        good = doc_summary(GROUPS)
        data = bytearray(good)
        struct.pack_into("<I", data, 44, len(good) + 10)
        self.assertRefused(bytes(data))
        data = bytearray(good)
        base = struct.unpack_from("<I", good, 44)[0]
        struct.pack_into("<I", data, base, len(good))  # section size larger than what follows
        self.assertRefused(bytes(data))

    def test_too_many_properties(self):
        data = bytearray(doc_summary(GROUPS))
        base = struct.unpack_from("<I", data, 44)[0]
        struct.pack_into("<I", data, base + 4, 1 << 20)
        self.assertRefused(bytes(data))

    def test_property_offset_outside(self):
        data = bytearray(doc_summary(GROUPS))
        base = struct.unpack_from("<I", data, 44)[0]
        struct.pack_into("<I", data, base + 12, 1 << 30)
        self.assertRefused(bytes(data))

    def test_string_past_its_section(self):
        data = stream((metadata.FMTID_DOC_SUMMARY, section([(2, struct.pack("<II", metadata.VT_LPSTR, 1 << 30))])))
        self.assertRefused(data)

    def test_huge_vector(self):
        data = stream((metadata.FMTID_DOC_SUMMARY,
                       section([(13, struct.pack("<II", metadata.VT_VECTOR | metadata.VT_LPSTR, 1 << 30))])))
        self.assertRefused(data)

    def test_nested_vector_refused(self):
        inner = struct.pack("<II", metadata.VT_VECTOR | metadata.VT_VARIANT, 1)
        data = stream((metadata.FMTID_DOC_SUMMARY,
                       section([(12, struct.pack("<II", metadata.VT_VECTOR | metadata.VT_VARIANT, 1) + inner * 50)])))
        self.assertRefused(data)

    def test_vector_item_of_unknown_type(self):
        data = stream((metadata.FMTID_DOC_SUMMARY,
                       section([(12, struct.pack("<III", metadata.VT_VECTOR | metadata.VT_VARIANT, 1, 0x40))])))
        self.assertRefused(data)

    def test_heading_pairs_longer_than_the_parts(self):
        data = stream((metadata.FMTID_DOC_SUMMARY, section([(12, vector_variant(["General", 5])),
                                                            (13, vector_lpstr(["3ds Max Version: 22.00"]))])))
        props = metadata.property_sets(data)[metadata.FMTID_DOC_SUMMARY]
        with self.assertRaises(MetadataError):
            metadata.groups(props)

    def test_cut_short_everywhere(self):
        good = doc_summary(GROUPS)
        for n in range(0, len(good), 7):
            try:
                metadata.property_sets(good[:n])
            except MetadataError:
                pass

    def test_flipped_bytes_raise_only_metadata_error(self):
        good = doc_summary(GROUPS)
        for at in range(len(good)):
            for value in (0x00, 0xFF, 0x41):
                data = bytearray(good)
                data[at] = value
                try:
                    props = metadata.property_sets(bytes(data), metadata.WANTED).get(metadata.FMTID_DOC_SUMMARY)
                    if props is not None:
                        metadata.summarize(metadata.groups(props))
                except MetadataError:
                    pass

    def test_one_value_shared_by_many_ids_is_bounded(self):
        # 4096 property ids on one 1 MB vector would decode it 4096 times: the decode budget stops it at once.
        big = vector_lpstr(["x" * 1000] * 1000)
        head = 8 + 8 * 4096
        table = b"".join(struct.pack("<II", metadata.PID_DOC_PARTS if j % 2 else 2 + j, head) for j in range(4096))
        sec = struct.pack("<II", head + len(big), 4096) + table + big
        data = stream((metadata.FMTID_DOC_SUMMARY, sec))
        for wanted in (None, metadata.WANTED):
            with self.subTest(wanted=wanted), self.assertRaises(MetadataError):
                metadata.property_sets(data, wanted)

    def test_parts_that_are_not_strings(self):
        data = stream((metadata.FMTID_DOC_SUMMARY, section([(12, vector_variant(["Used Plug-Ins", 1])),
                                                            (13, vector_variant([5]))])))
        props = metadata.property_sets(data, metadata.WANTED)[metadata.FMTID_DOC_SUMMARY]
        with self.assertRaises(MetadataError):
            metadata.groups(props)


class TestOddValues(unittest.TestCase):
    def test_plugin_entries_must_be_file_names(self):
        info = _summary(doc_summary([("Used Plug-Ins", ["epoly.dlo", "C:\\tools\\x.dlo", "a/b.dlu", "", "y" * 300])]))
        self.assertEqual(info["plugins"], ["epoly.dlo"])

    def test_counts_and_years_must_be_plausible(self):
        info = _summary(doc_summary([("General", ["3ds Max Version: 999999.00"]),
                                     ("Scene Totals", ["Objects: -5", "Lights: \u00b2", "Cameras: 2"])]))
        self.assertEqual(info, {"max_version": "999999.00", "counts": {"cameras": 2}})

    def test_long_text_is_cut(self):
        info = _summary(doc_summary([("General", ["Build: " + "9" * 5000])]))
        self.assertEqual(len(info["build"]), metadata.MAX_TEXT)

    def test_negative_class_id_half(self):
        info = _summary(doc_summary([("Render Data", ["Renderer ClassIDA=-1", "Renderer ClassIDB=12"])]))
        self.assertEqual(info["renderer"]["class_id"], (0xFFFFFFFF, 12))
        info = _summary(doc_summary([("Render Data", ["Renderer ClassIDA=99999999999", "Renderer ClassIDB=1"])]))
        self.assertNotIn("renderer", info)


if __name__ == "__main__":
    unittest.main()
