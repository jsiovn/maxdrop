# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/pblock.py on synthetic ParamBlock2 and ParamBlock chunks: every value type, tables,
references held by the block or by its owner, controllers, assets, and damaged input. No Blender. The committed
fixtures are checked against the 3ds Max oracle in test_materials.py.

    python -I -m unittest discover tests
"""
import importlib.util
import os
import struct
import sys
import unittest

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


_READER = os.path.join(ROOT, "maxdrop", "reader")
_load("maxdrop_reader", os.path.join(_READER, "__init__.py"), _READER)
chunks = _load("maxdrop_reader.chunks", os.path.join(_READER, "chunks.py"))
pblock = _load("maxdrop_reader.pblock", os.path.join(_READER, "pblock.py"))
ChunkError = chunks.ChunkError
Reference, Animated, Asset = pblock.Reference, pblock.Animated, pblock.Asset

FLOAT, INT, RGBA, POINT3, BOOL, ANGLE, STRING, FILENAME, MTL, TEXMAP, BITMAP, POINT4, FRGBA, POINT2, MATRIX3 = (
    0, 1, 2, 3, 4, 5, 8, 9, 14, 15, 16, 22, 23, 30, 20)
TAB = 0x800
ANIM, TRANSIENT, NO_REF, OWNERS = 0x1, 0x2, 0x100, 0x200


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def container(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def head(pid, ptype, flags):
    return struct.pack("<HIII", pid, ptype, flags, 0)


def scalar(pid, ptype, flags, tag, value=b""):
    return leaf(0x100E, head(pid, ptype, flags) + bytes([tag]) + value)


def table(pid, ptype, flags, *elements):
    """elements: (tag, value bytes) pairs."""
    body = b"".join(bytes([tag]) + value for tag, value in elements)
    return leaf(0x100E, head(pid, ptype | TAB, flags) + b"\x00" + struct.pack("<I", len(elements)) + body)


def f32(*v):
    return struct.pack("<%df" % len(v), *v)


def i32(*v):
    return struct.pack("<%di" % len(v), *v)


def utf16(text):
    data = (text + "\x00").encode("utf-16-le")
    return struct.pack("<I", len(data)) + data


def block(*entries, block_id=1, owner=7, count=None, extra=(), header_id=0x0009):
    n = sum(1 for e in entries if e[:2] == b"\x0e\x10") if count is None else count
    tail = struct.pack("<IHIHI", 9, block_id, 0x55F03700, n, owner)
    if header_id == 0x000B:
        tail = struct.pack("<II", 0x5A06293C, 0x30420C1E) + tail
    return container(0x82, leaf(header_id, tail), *entries, *extra)


def owner_table(*triples):
    return leaf(0x0013, struct.pack("<I", len(triples)) + b"".join(struct.pack("<HHH", *t) for t in triples))


def parse(data, block_refs=None, owner_refs=None):
    return pblock.ParamBlock2.from_chunk(chunks.index(data)[0], block_refs, owner_refs)


class Values(unittest.TestCase):
    def test_header(self):
        pb = parse(block(scalar(1, FLOAT, ANIM, 0xC0, f32(0.5)), block_id=3, owner=42))
        self.assertEqual((pb.block_id, pb.owner, pb.version, pb.count), (3, 42, 0x55F03700, 1))
        self.assertEqual(pb.issues, ())

    def test_class_header(self):
        pb = parse(block(scalar(1, INT, 0, 0x40, i32(5)), block_id=0, owner=1, header_id=0x000B))
        self.assertEqual((pb.block_id, pb.owner, pb.get(1)), (0, 1, 5))

    def test_older_entry_id(self):
        """Entries are 0x000E in a file saved as 3ds Max 2012 (corpus scene A), the same layout."""
        old = scalar(3, FLOAT, ANIM, 0xC0, f32(0.5)).replace(b"\x0e\x10", b"\x0e\x00", 1)
        pb = parse(block(old, count=1))
        self.assertEqual((pb.get(3), pb.issues), (0.5, ()))

    def test_every_scalar_type(self):
        pb = parse(block(
            scalar(1, FLOAT, ANIM, 0xC0, f32(0.25)), scalar(2, INT, 0, 0x40, i32(-3)),
            scalar(3, RGBA, ANIM, 0xC0, f32(0.1, 0.2, 0.3)), scalar(4, POINT3, 0, 0x40, f32(1, 2, 3)),
            scalar(5, BOOL, 0, 0x40, i32(1)), scalar(6, ANGLE, ANIM, 0xC0, f32(0.5)),
            scalar(7, STRING, 0, 0x40, utf16("Slot")), scalar(8, POINT4, 0, 0x40, f32(1, 2, 3, 4)),
            scalar(9, FRGBA, 0, 0x40, f32(0.5, 0.25, 0.125, 1)), scalar(10, POINT2, 0, 0x40, f32(7, 8)),
            scalar(11, STRING, 0, 0x40, struct.pack("<I", 0xFFFFFFFF))))
        self.assertEqual(pb.get(1), 0.25)
        self.assertEqual(pb.get(2), -3)
        self.assertEqual([round(v, 6) for v in pb.get(3)], [0.1, 0.2, 0.3])
        self.assertEqual(pb.get(4), (1.0, 2.0, 3.0))
        self.assertEqual((pb.get(5), pb.get(6)), (1, 0.5))
        self.assertEqual(pb.get(7), "Slot")
        self.assertEqual(pb.get(8), (1.0, 2.0, 3.0, 4.0))
        self.assertEqual(pb.get(9), (0.5, 0.25, 0.125, 1.0))
        self.assertEqual(pb.get(10), (7.0, 8.0))
        self.assertIsNone(pb.get(11))  # a string saved as none
        self.assertEqual(sorted(pb.ids()), list(range(1, 12)))
        self.assertEqual(pb.param(3).base_type, RGBA)
        self.assertFalse(pb.param(3).table)

    def test_missing_and_defaults(self):
        pb = parse(block(scalar(1, FLOAT, 0, 0x40, f32(2))))
        self.assertNotIn(99, pb)
        self.assertIsNone(pb.get(99))
        self.assertEqual(pb.get(99, default=7), 7)
        self.assertEqual(pb.get(1, tab=1, default="x"), "x")
        self.assertIsNone(pb.param(99))
        self.assertEqual(pb.value(1), 2.0)

    def test_tables(self):
        pb = parse(block(
            table(1, BOOL, 0, (0x40, i32(1)), (0x40, i32(0)), (0x40, i32(1))),
            table(2, STRING, 0, (0x40, utf16("A")), (0x40, utf16("Bc"))),
            table(3, RGBA, ANIM, (0xC0, f32(0.5, 0.5, 0.5)), (0xC0, f32(1, 0, 0))),
            table(4, INT, 0)))
        self.assertEqual(pb.value(1), [1, 0, 1])
        self.assertEqual(pb.value(2), ["A", "Bc"])
        self.assertEqual(pb.get(2, tab=1), "Bc")
        self.assertEqual(pb.value(3), [(0.5, 0.5, 0.5), (1.0, 0.0, 0.0)])
        self.assertEqual(pb.value(4), [])
        self.assertTrue(pb.param(1).table)

    def test_transient_flag_is_reported(self):
        pb = parse(block(scalar(56, BOOL, TRANSIENT, 0x40, i32(0))))
        self.assertTrue(pb.param(56).transient)


class References(unittest.TestCase):
    def test_block_held_references_take_slots_in_entry_order(self):
        # a VRayBlendMtl: baseMtl, an unrelated bool table, then a table of three coats
        pb = parse(block(scalar(0, MTL, 0, 0x40), table(6, BOOL, 0, (0x40, i32(1))),
                         table(1, MTL, 0, (0x40, b""), (0x40, b""), (0x40, b"")), scalar(3, TEXMAP, 0, 0x40)),
                   block_refs={0: 100, 1: 101, 3: 103})
        self.assertEqual(pb.get(0), Reference(100))
        self.assertEqual(pb.value(1), [Reference(101), Reference(None), Reference(103)])
        self.assertEqual(pb.get(3), Reference(None))  # slot 4: empty

    def test_transient_entries_take_slots_too(self):
        pb = parse(block(scalar(1000, MTL, TRANSIENT, 0x40), scalar(0, MTL, 0, 0x40)), block_refs={1: 55})
        self.assertEqual((pb.get(1000), pb.get(0)), (Reference(None), Reference(55)))

    def test_owner_references_through_0x0013(self):
        # a VRayMtl map whose stored index is -1 although set; a Multi/Sub-Object table at slots 1..3
        pb = parse(block(scalar(100, TEXMAP, OWNERS | NO_REF, 0x40, i32(-1)),
                         table(0, MTL, OWNERS, (0x40, i32(-1)), (0x40, i32(-1)), (0x40, i32(-1))),
                         extra=[owner_table((100, 7, 0), (0, 1, 0))]),
                   owner_refs={7: 300, 1: 301, 3: 303})
        self.assertEqual(pb.get(100), Reference(300))
        self.assertEqual(pb.value(0), [Reference(301), Reference(None), Reference(303)])

    def test_stored_index_without_a_table_entry(self):
        pb = parse(block(scalar(14, 18, OWNERS, 0x40, i32(358)), scalar(15, 18, OWNERS, 0x40, i32(-1)),
                         table(1, TEXMAP, NO_REF, (0x40, i32(-1)), (0x40, i32(77)))))
        self.assertEqual((pb.get(14), pb.get(15)), (Reference(358), Reference(None)))
        self.assertEqual(pb.value(1), [Reference(None), Reference(77)])  # Standard's maps: P_NO_REF

    def test_controllers_after_block_references(self):
        pb = parse(block(scalar(1, RGBA, ANIM, 0x80), scalar(2, MTL, 0, 0x40), scalar(3, FLOAT, ANIM, 0x80),
                         table(4, FLOAT, ANIM, (0xC0, f32(1)), (0x80, b""))),
                   block_refs={0: 10, 1: 11, 2: 12, 3: 13})
        self.assertEqual(pb.get(2), Reference(10))
        self.assertEqual((pb.get(1), pb.get(3)), (Animated(11), Animated(12)))
        self.assertEqual(pb.value(4), [1.0, Animated(13)])

    def test_assets_follow_their_entry(self):
        guid = bytes(range(16))
        pb = parse(block(scalar(13, BITMAP, 0, 0x40, b"\x01"),
                         container(0x0003, leaf(0x1201, b"\x00" * 8), container(0x1260, leaf(0x0002, guid))),
                         scalar(16, FILENAME, 0, 0x40, i32(-2)),
                         container(0x000F, leaf(0x0002, guid[::-1])),
                         scalar(17, FILENAME, 0, 0x40, i32(-1)), scalar(18, BITMAP, 0, 0x40, b"\x00"),
                         scalar(19, FILENAME, 0, 0x40, i32(-2))))  # its asset chunk is missing
        self.assertEqual(pb.get(13), Asset(guid))
        self.assertEqual(pb.get(16), Asset(guid[::-1]))
        self.assertEqual((pb.get(17), pb.get(18), pb.get(19)), (None, None, None))


class Damaged(unittest.TestCase):
    def test_no_header(self):
        with self.assertRaises(ChunkError):
            parse(container(0x82, scalar(1, FLOAT, 0, 0x40, f32(1))))
        with self.assertRaises(ChunkError):
            parse(leaf(0x82, b"\x00" * 4))
        with self.assertRaises(ChunkError):
            parse(container(0x82, leaf(0x0009, b"\x00" * 10)))

    def test_bad_entry_poisons_only_itself(self):
        pb = parse(block(scalar(1, FLOAT, 0, 0x40, f32(1)), scalar(2, FLOAT, 0, 0x40, b"\x00\x00"),
                         scalar(3, MATRIX3, 0, 0x40, f32(*range(12))), leaf(0x100E, b"\x05\x00"),
                         scalar(4, INT, 0, 0x40, i32(9))))
        self.assertEqual((pb.get(1), pb.get(4)), (1.0, 9))
        self.assertIsNone(pb.get(2))
        self.assertIsNotNone(pb.param(2).error)
        self.assertEqual(pb.param(3).raw[:2], b"\x03\x00")  # unknown element size: kept raw
        self.assertIsNone(pb.value(3))
        self.assertIsNotNone(pb.param(5))
        self.assertEqual(len(pb.issues), 4)  # three entries, and the 2-byte one may have held block references
        self.assertIn("block references after parameter 5 unresolved", pb.issues)

    def test_damaged_reference_table_leaves_later_slots_empty(self):
        cut = leaf(0x100E, head(1, MTL | TAB, 0) + b"\x00" + struct.pack("<I", 2) + b"\x40")  # 2 elements, 1 there
        pb = parse(block(scalar(0, MTL, 0, 0x40), cut, scalar(2, MTL, 0, 0x40), scalar(3, FLOAT, ANIM, 0x80),
                         scalar(4, MTL, NO_REF, 0x40, i32(9))),
                   block_refs={0: 100, 1: 101, 2: 102, 3: 103})
        self.assertEqual(pb.get(0), Reference(100))  # before the damage: kept
        self.assertEqual(pb.get(2), Reference(None))  # not slot 1's target
        self.assertEqual(pb.get(3), Animated(None))
        self.assertEqual(pb.get(4), Reference(9))  # a stored index does not depend on slots
        self.assertIn("block references after parameter 1 unresolved", pb.issues)

    def test_damaged_value_entry_keeps_slots_but_drops_controllers(self):
        pb = parse(block(scalar(1, FLOAT, ANIM, 0xC0, b"\x00"), scalar(2, MTL, 0, 0x40),
                         scalar(3, FLOAT, ANIM, 0x80)), block_refs={0: 100, 1: 101})
        self.assertEqual((pb.get(2), pb.get(3)), (Reference(100), Animated(None)))

    def test_stored_index_outside_the_objects(self):
        pb = pblock.ParamBlock2.from_chunk(
            chunks.index(block(scalar(1, MTL, NO_REF, 0x40, i32(1000000000)), scalar(2, MTL, NO_REF, 0x40, i32(4))))[0],
            object_count=5)
        self.assertEqual((pb.get(1), pb.get(2)), (Reference(None), Reference(4)))
        self.assertTrue(any("outside the 5 objects" in x for x in pb.issues))

    def test_asset_only_right_after_its_entry(self):
        guid = bytes(range(16))
        pb = parse(block(scalar(1, FILENAME, 0, 0x40, i32(-2)),  # its 0x000F is missing
                         scalar(2, BITMAP, 0, 0x40, b"\x01"),
                         container(0x0003, container(0x1260, leaf(0x0002, guid))),
                         container(0x000F, leaf(0x0002, guid))))  # belongs to no entry
        self.assertIsNone(pb.get(1))
        self.assertEqual(pb.get(2), Asset(guid))
        self.assertIn("parameter 1: asset chunk missing", pb.issues)
        self.assertTrue(any("belongs to no entry" in x for x in pb.issues))

    def test_asset_of_the_wrong_kind_is_not_taken(self):
        guid = bytes(range(16))
        pb = parse(block(scalar(1, FILENAME, 0, 0x40, i32(-2)), container(0x0003, container(0x1260, leaf(2, guid)))))
        self.assertIsNone(pb.get(1))
        self.assertEqual(len(pb.issues), 2)

    def test_asset_table_takes_a_run_of_chunks(self):
        a, b = bytes(range(16)), bytes(range(16, 32))
        pb = parse(block(table(1, FILENAME, 0, (0x40, i32(-2)), (0x40, i32(-1)), (0x40, i32(-2))),
                         container(0x000F, leaf(0x0002, a)), container(0x000F, leaf(0x0002, b))))
        self.assertEqual(pb.value(1), [Asset(a), None, Asset(b)])
        self.assertEqual(pb.issues, ())

    def test_damaged_asset_chunk_spoils_only_its_parameter(self):
        broken = struct.pack("<HI", 0x0003, (6 + 9) | 0x80000000) + struct.pack("<HI", 0x1260, 3) + b"\x00" * 3
        pb = parse(block(scalar(1, BITMAP, 0, 0x40, b"\x01"), broken, scalar(2, INT, 0, 0x40, i32(7))))
        self.assertEqual((pb.get(1), pb.get(2)), (None, 7))
        self.assertTrue(any("asset chunk damaged" in x for x in pb.issues))

    def test_values_are_read_only(self):
        pb = parse(block(table(1, INT, 0, (0x40, i32(1)), (0x40, i32(2)))))
        self.assertIsInstance(pb.param(1).values, tuple)
        pb.value(1).append(3)
        self.assertEqual(pb.value(1), [1, 2])

    def test_table_larger_than_its_payload(self):
        data = leaf(0x100E, head(1, INT | TAB, 0) + b"\x00" + struct.pack("<I", 0xFFFFFFF0) + b"\x40" + i32(1))
        pb = parse(block(data, scalar(2, INT, 0, 0x40, i32(3))))
        self.assertIsNone(pb.value(1))
        self.assertEqual(pb.get(2), 3)

    def test_string_longer_than_its_entry(self):
        pb = parse(block(scalar(1, STRING, 0, 0x40, struct.pack("<I", 1000) + b"ab")))
        self.assertIsNone(pb.get(1))
        self.assertIn("string", pb.param(1).error)

    def test_owner_table_cut_short(self):
        pb = parse(block(scalar(100, TEXMAP, OWNERS, 0x40, i32(5)),
                         extra=[leaf(0x0013, struct.pack("<I", 3) + b"\x01\x00")]), owner_refs={7: 300})
        self.assertEqual(pb.get(100), Reference(5))  # the stored index, the table being unusable
        self.assertTrue(any("0x0013" in x for x in pb.issues))

    def test_duplicate_and_count_mismatch(self):
        pb = parse(block(scalar(1, INT, 0, 0x40, i32(1)), scalar(1, INT, 0, 0x40, i32(2)), count=5))
        self.assertEqual(pb.get(1), 1)
        self.assertEqual(len(pb.issues), 2)


class OldParamBlock(unittest.TestCase):
    def entry(self, index, cid, payload, controller=False):
        return container(0x0002, leaf(0x0003, struct.pack("<I", index)), *([leaf(0x0004)] if controller else []),
                         leaf(cid, payload))

    def test_values_by_index(self):
        data = container(0x08, leaf(0x0001, struct.pack("<I", 5)), leaf(0x0005, b"\x02\x00"),
                         self.entry(0, 0x0100, f32(0.1)), self.entry(1, 0x0101, i32(4), True),
                         self.entry(2, 0x0102, f32(1, 0.5, 0)), self.entry(3, 0x0103, f32(1, 2, 3)),
                         self.entry(4, 0x0104, i32(1)))
        pb = pblock.ParamBlock.from_chunk(chunks.index(data)[0])
        self.assertEqual(pb.indices(), [0, 1, 2, 3, 4])
        self.assertAlmostEqual(pb.get(0), 0.1, places=6)
        self.assertEqual((pb.get(1), pb.get(2), pb.get(3), pb.get(4)), (4, (1.0, 0.5, 0.0), (1.0, 2.0, 3.0), 1))
        self.assertEqual([pb.type(i) for i in range(5)], [0, 1, 2, 3, 4])
        self.assertIsNone(pb.get(9))
        self.assertEqual(pb.issues, ())

    def test_damaged(self):
        with self.assertRaises(ChunkError):
            pblock.ParamBlock.from_chunk(chunks.index(leaf(0x08, b"x"))[0])
        data = container(0x08, leaf(0x0002, b"x"), container(0x0002, leaf(0x0100, f32(1))),
                         self.entry(0, 0x0102, f32(1)), self.entry(1, 0x0100, f32(2)))
        pb = pblock.ParamBlock.from_chunk(chunks.index(data)[0])
        self.assertEqual(pb.get(1), 2.0)
        self.assertIsNone(pb.get(0))
        self.assertEqual(len(pb.issues), 3)

    def test_declared_count(self):
        data = container(0x08, leaf(0x0001, struct.pack("<I", 3)), self.entry(0, 0x0100, f32(1)))
        pb = pblock.ParamBlock.from_chunk(chunks.index(data)[0])
        self.assertEqual(pb.issues, ("0x0001 announces 3 parameters, 1 found",))


if __name__ == "__main__":
    unittest.main()
