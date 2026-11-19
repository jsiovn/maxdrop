# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/classdir.py and classids.py: no Blender. ClassId, synthetic class and DLL
directories, and the committed fixtures: their class directories, the class index of the Scene chunks, and every
entry of classids.CLASSES found in a fixture with its name.

    python -I -m unittest discover tests
"""
import glob
import importlib
import os
import pickle
import struct
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
BOX = os.path.join(ROOT, "tests", "fixtures", "box_poly_standard.max")


_PKG = "maxdrop_convert_test"  # the package the convert tests make: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
cfb = importlib.import_module(_PKG + ".reader.cfb")
chunks = importlib.import_module(_PKG + ".reader.chunks")
classdir = importlib.import_module(_PKG + ".reader.classdir")
classids = importlib.import_module(_PKG + ".reader.classids")
DERIVED_OBJECT = 0x2032  # reader/scene.py: an object with modifiers
ClassId = classdir.ClassId
ChunkError = chunks.ChunkError


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def utf16(text):
    return text.encode("utf-16-le")


def class_entry(dll, a, b, superclass, name=None):
    parts = [leaf(0x2060, struct.pack("<iIII", dll, a, b, superclass))]
    if name is not None:
        parts.append(leaf(0x2042, utf16(name)))
    return node(0x2040, *parts)


def dll_entry(file, description):
    return node(0x2038, leaf(0x2039, utf16(description)), leaf(0x2037, utf16(file)))


DLLDIR = leaf(0x21C0, b"\x80\x08\xf0\x55") + dll_entry("first.dlo", "First") + dll_entry("second.dlc", "Second")
CLASSDIR = (class_entry(-1, 0x82, 0, 0x82, "ParamBlock2") + class_entry(1, 0x1BF8338D, 0x192F6098, 0x10, "Poly") +
            class_entry(0, 2, 0, 0xC00, "Standard") + class_entry(-2, 0x1D5B0B9F, 0x74167F1B, 0x1160, "Props") +
            class_entry(7, 9, 9, 0xFFFFFE00) + class_entry(1, 2, 0, 0x1, "RootNode"))


class TestClassId(unittest.TestCase):
    def test_compares_and_hashes_as_the_pair(self):
        cid = ClassId(0x1BF8338D, 0x192F6098)
        self.assertEqual(cid, (0x1BF8338D, 0x192F6098))
        self.assertEqual(hash(cid), hash((0x1BF8338D, 0x192F6098)))
        self.assertEqual({cid: 1}[(0x1BF8338D, 0x192F6098)], 1)
        self.assertNotEqual(cid, ClassId(0x192F6098, 0x1BF8338D))
        self.assertEqual((cid.a, cid.b), (0x1BF8338D, 0x192F6098))
        self.assertLess(ClassId(1, 5), ClassId(2, 0))

    def test_hex(self):
        cid = ClassId(0x1BF8338D, 0x192F6098)
        self.assertEqual(str(cid), "(0x1BF8338D, 0x192F6098)")
        self.assertEqual(repr(cid), "ClassId(0x1BF8338D, 0x192F6098)")
        self.assertEqual(eval(repr(cid), {"ClassId": ClassId}), cid)

    def test_upstream_64_bit_form(self):
        cid = ClassId.from_int(0x192F60981BF8338D)
        self.assertEqual(cid, ClassId(0x1BF8338D, 0x192F6098))
        self.assertEqual(int(cid), 0x192F60981BF8338D)
        self.assertEqual(ClassId.from_int(0xE44F10B3), ClassId(0xE44F10B3, 0))

    def test_range_and_pickle(self):
        for a, b in ((-1, 0), (0, 1 << 32), (1 << 32, 0)):
            with self.assertRaises(ValueError):
                ClassId(a, b)
        for a in (1.5, "12"):
            with self.assertRaises(TypeError):
                ClassId(a, 0)
        cid = ClassId(0xFFFFFFFF, 0)
        self.assertEqual(pickle.loads(pickle.dumps(cid)), cid)
        self.assertIsInstance(pickle.loads(pickle.dumps(cid)), ClassId)


class TestSynthetic(unittest.TestCase):
    def test_entries_and_dlls(self):
        d = classdir.ClassDirectory.parse(CLASSDIR, DLLDIR, "ClassDirectory3")
        self.assertEqual(len(d), 6)
        self.assertEqual([(x.index, x.file, x.description) for x in d.dlls],
                         [(0, "first.dlo", "First"), (1, "second.dlc", "Second")])
        poly = d[1]
        self.assertEqual((poly.index, poly.class_id, poly.superclass, poly.name), (1, ClassId(0x1BF8338D, 0x192F6098),
                                                                                    0x10, "Poly"))
        self.assertEqual((poly.class_a, poly.class_b, poly.dll_index, poly.dll_name), (0x1BF8338D, 0x192F6098, 1,
                                                                                        "second.dlc"))
        self.assertEqual(d[2].dll_name, "first.dlo")
        self.assertEqual([d[i].dll for i in (0, 3, 4)], [None, None, None])  # -1, -2, past the list
        self.assertEqual(d[4].superclass, 0xFFFFFE00)
        self.assertEqual(d[4].name, "")
        self.assertEqual(d.stream, "ClassDirectory3")
        self.assertEqual([e.index for e in d], list(range(6)))

    def test_lookup(self):
        d = classdir.ClassDirectory.parse(CLASSDIR)
        self.assertEqual(d.dlls, ())
        self.assertIsNone(d[1].dll)
        self.assertIsNone(d.get(6))
        self.assertIsNone(d.get(-1))
        self.assertEqual(d.get(5).name, "RootNode")
        with self.assertRaises(IndexError):
            d[6]
        with self.assertRaises(IndexError):
            d[-1]
        self.assertEqual([e.index for e in d.find((2, 0))], [2, 5])  # Standard and RootNode share a ClassId
        self.assertEqual(d.find(ClassId(7, 7)), [])

    def test_other_top_level_chunks_do_not_count(self):
        d = classdir.ClassDirectory.parse(leaf(0x1234, b"zz") + CLASSDIR)
        self.assertEqual(d[1].name, "Poly")

    def test_entry_without_ids(self):
        for bad in (node(0x2040, leaf(0x2042, utf16("X"))), node(0x2040, leaf(0x2060, bytes(12))),
                    leaf(0x2040, bytes(16))):
            with self.subTest(bad=bad.hex()), self.assertRaises(ChunkError):
                classdir.ClassDirectory.parse(CLASSDIR + bad)

    def test_damaged_stream(self):
        with self.assertRaises(ChunkError):
            classdir.ClassDirectory.parse(CLASSDIR[:-3])


class FakeFile:
    def __init__(self, streams):
        self.streams = streams

    def exists(self, name):
        return name in self.streams

    def open(self, name):
        return self.streams[name]


class TestFromFile(unittest.TestCase):
    def test_fallback_and_missing(self):
        d = classdir.ClassDirectory.from_file(FakeFile({"ClassDirectory": CLASSDIR}))
        self.assertEqual((len(d), d.stream, d.dlls), (6, "ClassDirectory", ()))
        d = classdir.ClassDirectory.from_file(FakeFile({"ClassDirectory3": CLASSDIR, "ClassDirectory": b"",
                                                        "DllDirectory": DLLDIR}))
        self.assertEqual((d.stream, d[1].dll_name), ("ClassDirectory3", "second.dlc"))
        with self.assertRaises(ChunkError):
            classdir.ClassDirectory.from_file(FakeFile({}))


def _directory(path):
    with cfb.CompoundFile(path) as cf:
        return classdir.ClassDirectory.from_file(cf)


@unittest.skipUnless(FIXTURES, "no fixtures")
class TestFixtures(unittest.TestCase):
    def test_box_lists_editable_poly(self):
        d = _directory(BOX)
        self.assertEqual(d.stream, "ClassDirectory3")
        polys = [e for e in d if e.name == "Editable Poly"]
        self.assertEqual(len(polys), 1)
        poly = polys[0]
        self.assertEqual(poly.class_id, ClassId(0x1BF8338D, 0x192F6098))
        self.assertEqual(int(poly.class_id), 0x192F60981BF8338D)  # the id of the notes and of import_max.py
        self.assertEqual(poly.superclass, classids.SC_GEOMOBJECT)
        self.assertEqual(poly.dll_name, "epoly.dlo")
        self.assertEqual(d.find(classids.EDITABLE_POLY), [poly])

    def test_scene_chunk_ids_are_class_indices(self):
        for path in FIXTURES:
            with self.subTest(fixture=os.path.basename(path)), cfb.CompoundFile(path) as cf:
                d = classdir.ClassDirectory.from_file(cf)
                top = chunks.index(cf.open("Scene"))
                objects = top[0].children
                # past the directory only the derived object id (modifier_pivot's two stacks)
                self.assertTrue(all(i < len(d) or i == DERIVED_OBJECT for i in objects.ids))
                nodes = [c for c in objects if c.id < len(d) and d[c.id].superclass == classids.SC_BASENODE
                         and d[c.id].class_id == classids.NODE]
                self.assertGreater(len(nodes), 0)
                for c in nodes:
                    self.assertIsNotNone(c.first(0x0962), "a Node without a name chunk at %d" % c.offset)
                del top, objects, nodes

    def test_every_known_class_is_in_a_fixture(self):
        seen = set()
        for path in FIXTURES:
            for e in _directory(path):
                seen.add((e.superclass, e.class_id, e.name))
        for (superclass, class_id), name in classids.CLASSES.items():
            with self.subTest(name=name):
                self.assertIn((superclass, class_id, name), seen)
                self.assertEqual(classids.name_of(superclass, class_id), name)
        constants = {v for k, v in vars(classids).items() if k.isupper() and isinstance(v, ClassId)}
        self.assertEqual(constants, {cid for _sup, cid in classids.CLASSES})
        self.assertIsNone(classids.name_of(classids.SC_GEOMOBJECT, classids.STANDARD_MTL))


if __name__ == "__main__":
    unittest.main()
