# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/chunks.py, the lazy chunk index: no Blender. Synthetic buffers for the header forms,
the nesting and the damaged cases; every chunked stream of the committed fixtures, indexed to the bottom.

    python -I -m unittest discover tests
"""
import gc
import glob
import importlib.util
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
CHUNKED_STREAMS = ("Scene", "ClassDirectory3", "DllDirectory", "Config", "ClassData", "VideoPostQueue")


def _load(name, path, package_dir=None):
    if name in sys.modules:
        return sys.modules[name]
    kw = {"submodule_search_locations": [package_dir]} if package_dir else {}
    spec = importlib.util.spec_from_file_location(name, path, **kw)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# By path, as a package of its own: `import maxdrop` would pull bpy.
_READER = os.path.join(ROOT, "maxdrop", "reader")
_load("maxdrop_reader", os.path.join(_READER, "__init__.py"), _READER)
cfb = _load("maxdrop_reader.cfb", os.path.join(_READER, "cfb.py"))
chunks = _load("maxdrop_reader.chunks", os.path.join(_READER, "chunks.py"))
ChunkError = chunks.ChunkError

try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None


def leaf(cid, payload=b"", big=False):
    if big:
        return struct.pack("<HIQ", cid, 0, 14 + len(payload)) + payload
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children, big=False):
    body = b"".join(children)
    if big:
        return struct.pack("<HIQ", cid, 0, (14 + len(body)) | (1 << 63)) + body
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def nested(levels):
    data = leaf(0x0001, b"x")
    for _ in range(levels):
        data = node(0x0002, data)
    return data


class FakeStream:
    """Duck-types cfb.Stream: the bytes split into runs at the given cut points."""

    def __init__(self, data, cuts):
        self.name, self.size, self._data = "fake", len(data), data
        edges = [0] + list(cuts) + [len(data)]
        self.runs = [(1000 * i, b - a) for i, (a, b) in enumerate(zip(edges, edges[1:]))]

    def view(self, offset, size):
        return memoryview(self._data)[offset:offset + size]


class TestHeaders(unittest.TestCase):
    def test_leaf(self):
        top = chunks.index(leaf(0x0962, "Box".encode("utf-16-le")))
        self.assertEqual(len(top), 1)
        c = top[0]
        self.assertEqual((c.id, c.offset, c.size, c.header, c.container, c.depth), (0x0962, 0, 12, 6, False, 0))
        self.assertEqual((c.end, c.payload_offset, c.payload_size), (12, 6, 6))
        self.assertEqual(c.text(), "Box")
        self.assertEqual(c.tobytes(), "Box".encode("utf-16-le"))
        self.assertEqual(len(c.children), 0)
        self.assertIsNone(c.first(1))

    def test_container_children_are_lazy_and_kept(self):
        data = node(0x2040, leaf(0x2060, bytes(16)), leaf(0x2042, b"A\0"))
        c = chunks.index(data)[0]
        self.assertTrue(c.container)
        self.assertIsNone(c._children)
        kids = c.children
        self.assertIs(c.children, kids)
        self.assertEqual(list(kids.ids), [0x2060, 0x2042])
        self.assertEqual([k.depth for k in kids], [1, 1])
        self.assertEqual(kids[1].offset, 6 + 22)
        self.assertIs(kids[0], kids[0])

    def test_64_bit_form(self):
        data = node(0x2023, leaf(0x0001, b"ab", big=True), leaf(0x0002), big=True)
        root = chunks.index(data)[0]
        self.assertEqual((root.id, root.header, root.container, root.size), (0x2023, 14, True, len(data)))
        a, b = root.children
        self.assertEqual((a.id, a.header, a.container, a.tobytes()), (1, 14, False, b"ab"))
        self.assertEqual((b.id, b.header, b.size, b.offset), (2, 6, 6, 14 + 16))

    def test_64_bit_size_needs_the_whole_header(self):
        with self.assertRaises(ChunkError):
            chunks.index(struct.pack("<HI", 1, 0) + b"\x00\x00\x00")

    def test_deep_nesting_and_lookup(self):
        data = node(0x10, node(0x20, leaf(0x30, b"q")), leaf(0x30), leaf(0x31), leaf(0x30))
        top = chunks.index(data)
        root = top[0]
        self.assertEqual(root.children.first(0x20).first(0x30).tobytes(), b"q")
        self.assertEqual(root.children.first(0x20).first(0x30).depth, 2)
        self.assertEqual([c.offset for c in root.find_all(0x30)], [root.children[1].offset, root.children[3].offset])
        self.assertIs(root.first(0x31), root.children[-2])
        self.assertIsNone(root.first(0x99))
        self.assertEqual(len(root.children[1:3]), 2)
        with self.assertRaises(IndexError):
            root.children[4]
        with self.assertRaises(IndexError):
            root.children[-5]
        with self.assertRaises(TypeError):
            root.children.ids[0] = 1

    def test_iter_chunks_matches_index(self):
        data = leaf(1, b"a") + node(2, leaf(3)) + leaf(4, big=True)
        self.assertEqual([(c.id, c.offset, c.size) for c in chunks.iter_chunks(data)],
                         [(c.id, c.offset, c.size) for c in chunks.index(data)])
        self.assertEqual(next(iter(chunks.iter_chunks(data))).children.ids.tolist(), [])

    def test_empty_stream(self):
        self.assertEqual(len(chunks.index(b"")), 0)


class TestDamaged(unittest.TestCase):
    def test_size_smaller_than_header(self):
        for data in (struct.pack("<HI", 1, 5), struct.pack("<HI", 1, 0x80000000),
                     struct.pack("<HIQ", 1, 0, 13), struct.pack("<HIQ", 1, 0, 1 << 63)):
            with self.subTest(data=data.hex()), self.assertRaises(ChunkError):
                chunks.index(data + bytes(16))

    def test_child_ends_after_parent(self):
        child = struct.pack("<HI", 3, 6 + 10) + bytes(4)  # says 16 bytes, parent holds 10
        data = struct.pack("<HI", 2, (6 + len(child)) | 0x80000000) + child + leaf(9, bytes(8))
        root = chunks.index(data)[0]
        with self.assertRaises(ChunkError):
            root.children

    def test_top_level_past_the_stream(self):
        with self.assertRaises(ChunkError):
            chunks.index(struct.pack("<HI", 1, 100) + bytes(10))

    def test_trailing_bytes(self):
        for n in range(1, 6):
            with self.subTest(n=n), self.assertRaises(ChunkError):
                chunks.index(leaf(1, b"ab") + bytes(n))

    def test_depth_limit(self):
        data = nested(5)  # containers at depths 0..4, the leaf at depth 5
        c = chunks.index(data, max_depth=5)[0]
        while c.container:
            c = c.children[0]
        self.assertEqual(c.depth, 5)
        c = chunks.index(data, max_depth=4)[0]
        with self.assertRaises(ChunkError):
            while c.container:
                c = c.children[0]

    def test_unpack(self):
        c = chunks.index(leaf(0x2060, struct.pack("<iIII", -1, 1, 2, 3)))[0]
        self.assertEqual(c.unpack("<iIII"), (-1, 1, 2, 3))
        self.assertEqual(c.unpack("<I", 12), (3,))
        with self.assertRaises(ChunkError):
            c.unpack("<iIIII")

    def test_odd_text_length(self):
        self.assertEqual(chunks.index(leaf(1, b"A\0B"))[0].text(), "A")


@unittest.skipIf(numpy is None, "numpy missing")
class TestArrays(unittest.TestCase):
    def test_floats_with_offset_and_count(self):
        values = [1.5, -2.0, 3.25, 4.0]
        data = bytearray(leaf(0x0100, struct.pack("<I4f", 4, *values)))
        c = chunks.index(data)[0]
        a = c.as_array("<f4", offset=4)
        self.assertEqual(a.tolist(), values)
        self.assertEqual(a.dtype, numpy.dtype("<f4"))
        self.assertFalse(a.flags.writeable)
        self.assertTrue(numpy.shares_memory(a, numpy.frombuffer(data, dtype="u1")))
        self.assertEqual(c.as_array("f4", offset=4, count=2).tolist(), values[:2])
        self.assertEqual(c.as_array(">f4", offset=4).dtype, numpy.dtype("<f4"))
        self.assertEqual(c.as_array([("n", "<u4")], count=1)["n"].tolist(), [4])

    def test_bad_lengths(self):
        c = chunks.index(leaf(1, bytes(10)))[0]
        with self.assertRaises(ChunkError):
            c.as_array("<f4")
        with self.assertRaises(ChunkError):
            c.as_array("<f4", count=3)
        with self.assertRaises(ChunkError):
            c.as_array("<f4", offset=11)
        self.assertEqual(c.as_array("<u2", offset=2).shape, (4,))


class TestPieces(unittest.TestCase):
    def test_headers_and_payloads_across_runs(self):
        data = node(0x2025, leaf(1, b"abcdefgh"), node(2, leaf(3, b"xyz", big=True)), leaf(4, b"tail"))
        whole = [(c.id, c.offset, c.size, c.tobytes()) for c in chunks.index(data)[0].children]
        for cuts in ([3], [7, 9], [10, 11, 12, 13], list(range(1, len(data)))):
            with self.subTest(cuts=cuts):
                root = chunks.index(FakeStream(data, cuts))[0]
                self.assertEqual([(c.id, c.offset, c.size, c.tobytes()) for c in root.children], whole)
                self.assertEqual(root.children[1].first(3).tobytes(), b"xyz")

    def test_runs_must_cover_the_size(self):
        stream = FakeStream(leaf(1), [])
        stream.size += 1
        with self.assertRaises(ChunkError):
            chunks.index(stream)

    def test_source_range_checks(self):
        src = chunks.Source(b"abcdef")
        self.assertEqual(src.view(2, 3).tobytes(), b"cde")
        self.assertEqual(chunks.Source(src).size, 6)
        for offset, size in ((-1, 1), (0, 7), (6, 1), (2, -1)):
            with self.assertRaises(ChunkError):
                src.view(offset, size)

    def test_views_are_read_only(self):
        data = bytearray(leaf(1, b"abcd"))
        c = chunks.index(data)[0]
        self.assertTrue(c.view().readonly)

    def test_run_views_are_made_when_touched(self):
        data = leaf(1, b"a" * 20) + leaf(2, b"b" * 20) + leaf(3, b"c" * 20)
        stream = FakeStream(data, [26, 52])
        top = chunks.index(stream)
        self.assertEqual(top[0].tobytes(), b"a" * 20)
        src = top[0]._src
        self.assertIsNotNone(src._pieces[0])
        self.assertIsNotNone(src._pieces[1])  # its header was read by the scan
        self.assertIsNotNone(src._pieces[2])
        lazy = chunks.Source(FakeStream(data, [26, 52]))
        self.assertEqual(lazy._pieces, [None, None, None])
        self.assertEqual(lazy.view(32, 4).tobytes(), b"bbbb")
        self.assertEqual([p is None for p in lazy._pieces], [True, False, True])


class TestLimitsAndCache(unittest.TestCase):
    def test_iterating_does_not_keep_chunks(self):
        root = chunks.index(node(1, *[leaf(2, b"x")] * 1000))[0]
        kids = root.children
        self.assertEqual(sum(1 for _ in kids), 1000)
        self.assertEqual(len(kids.find_all(2)), 1000)
        gc.collect()
        self.assertEqual(len(kids._made), 0)
        held = kids[7]
        self.assertIs(kids[7], held)
        self.assertEqual(len(kids._made), 1)
        self.assertEqual((held.offset, held.size), (6 + 7 * 7, 7))
        self.assertEqual((kids[-1].offset, kids[-1].end), (6 + 999 * 7, root.end))

    def test_children_stay_with_their_chunk(self):
        root = chunks.index(node(1, node(2, leaf(3))))[0]
        inner = root.children[0]
        self.assertIs(root.children[0].children, inner.children)

    def test_max_chunks(self):
        data = node(1, *[leaf(2)] * 10)
        self.assertEqual(len(chunks.index(data, max_chunks=10)[0].children), 10)
        with self.assertRaises(ChunkError):
            chunks.index(data, max_chunks=9)[0].children
        with self.assertRaises(ChunkError):
            chunks.index(leaf(1) * 3, max_chunks=2)
        self.assertEqual(len(list(chunks.iter_chunks(leaf(1) * 3, max_chunks=2))), 3)  # no index, no cap


def _walk(test, chunk_list, counts):
    for c in chunk_list:
        counts[0] += 1
        if c.container:
            end = c.payload_offset
            for k in c.children:
                test.assertEqual(k.offset, end)
                end = k.end
            test.assertEqual(end, c.end)
            _walk(test, c.children, counts)


@unittest.skipUnless(FIXTURES, "no fixtures")
class TestFixtures(unittest.TestCase):
    def test_every_chunked_stream_indexes_to_the_bottom(self):
        for path in FIXTURES:
            with cfb.CompoundFile(path) as cf:
                for name in CHUNKED_STREAMS:
                    if not cf.exists(name):
                        continue
                    with self.subTest(fixture=os.path.basename(path), stream=name):
                        stream = cf.open(name)
                        top = chunks.index(stream)
                        self.assertGreater(len(top), 0)
                        self.assertEqual(top[-1].end, stream.size)
                        counts = [0]
                        _walk(self, top, counts)
                        self.assertGreater(counts[0], 0)
                        del top, stream

    def test_scene_root(self):
        with cfb.CompoundFile(os.path.join(ROOT, "tests", "fixtures", "box_poly_standard.max")) as cf:
            top = chunks.index(cf.open("Scene"))
            self.assertEqual(len(top), 1)
            root = top[0]
            self.assertIn(root.id, (0x2014, 0x2023, 0x2025))
            self.assertTrue(root.container)
            self.assertGreater(len(root.children), 10)
            del top, root


if __name__ == "__main__":
    unittest.main()
