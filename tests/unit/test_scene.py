# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/scene.py, the scene index: no Blender. Synthetic Scene streams for references, node
records, the hierarchy, derived objects and damaged input; every committed fixture against its 3ds Max oracle
(node count, names in order, parents, pivot offsets, base classes, instances, material and layer slots).

    python -I -m unittest discover tests
"""
import glob
import importlib.util
import json
import os
import struct
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
HIERARCHY = os.path.join(ROOT, "tests", "fixtures", "hierarchy.max")


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
chunks = _load("maxdrop_reader.chunks", os.path.join(_READER, "chunks.py"))
classdir = _load("maxdrop_reader.classdir", os.path.join(_READER, "classdir.py"))
classids = _load("maxdrop_reader.classids", os.path.join(_READER, "classids.py"))
scene = _load("maxdrop_reader.scene", os.path.join(_READER, "scene.py"))
ChunkError = chunks.ChunkError
ClassId = classdir.ClassId


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def utf16(text):
    return text.encode("utf-16-le")


def class_entry(a, b, superclass, name):
    return node(0x2040, leaf(0x2060, struct.pack("<iIII", -1, a, b, superclass)), leaf(0x2042, utf16(name)))


# Class indices of the synthetic directory.
C_PB2, C_NODE, C_ROOT, C_POLY, C_LAYER, C_STD, C_MOD, C_PRS = range(8)
CLASSES = classdir.ClassDirectory.parse(
    class_entry(0x82, 0, 0x82, "ParamBlock2") + class_entry(1, 0, 1, "Node") + class_entry(2, 0, 1, "RootNode") +
    class_entry(0x1BF8338D, 0x192F6098, 0x10, "Editable Poly") +
    class_entry(0x7E9858FE, 0x1DBA1DF0, 0x10F0, "Base Layer") + class_entry(2, 0, 0xC00, "Standard") +
    class_entry(0x12345678, 0x9ABCDEF0, 0x810, "Some Modifier") + class_entry(0x2005, 0, 0x9008, "PRS"))
DERIVED = scene.DERIVED_OBJECT


def refs34(*indices):
    return leaf(0x2034, struct.pack("<%di" % len(indices), *indices))


def refs35(*pairs, head=16):
    flat = [v for pair in pairs for v in pair]
    return leaf(0x2035, struct.pack("<I" + "Ii" * len(pairs), head, *flat))


def node_obj(name, parent, flags=0x800, refs=(), pivot=True):
    parts = [refs35(*refs), leaf(0x0960, struct.pack("<iI", parent, flags)), leaf(0x0962, utf16(name))]
    if pivot:
        parts += [leaf(0x096A, struct.pack("<3f", 5, 6, 7)), leaf(0x096B, struct.pack("<4f", 0, 0, 0.5, 0.75)),
                  leaf(0x096C, struct.pack("<7f", 2, 3, 4, 0, 0, 0, 1))]
    return node(C_NODE, *parts)


def stream(*objects, root_id=0x2025):
    return node(root_id, *objects)


def make(*objects, root_id=0x2025):
    return scene.Scene(stream(*objects, root_id=root_id), CLASSES)


# 0 RootNode, 1 PRS, 2 Poly, 3 Layer, 4 Standard, 5 Node A (top), 6 Node B (child of A), 7 Node A again (child of
# B), 8 a ParamBlock2 leaf, 9 Node C (parent = the poly: not a node, so top level)
BASIC = (node(C_ROOT, refs35(head=16), leaf(0x0120)),
         node(C_PRS, refs35(head=2)),
         node(C_POLY, refs34(-1, 8)),
         node(C_LAYER, leaf(0x1000, b"\0\0\0\0")),
         node(C_STD, refs34(8)),
         node_obj("A", 0, refs=((0, 1), (1, 2), (3, 4), (6, 3))),
         node_obj("B", 5, flags=0x100800, refs=((1, 2),), pivot=False),
         node_obj("A", 6, flags=0, refs=((1, 2), (6, 3))),
         leaf(C_PB2, b"\x01\x02"),
         node_obj("C", 2, refs=()))


class TestIndexAndRefs(unittest.TestCase):
    def setUp(self):
        self.s = make(*BASIC)

    def test_index(self):
        s = self.s
        self.assertEqual((s.root_id, len(s)), (0x2025, 10))
        self.assertIn(s.root_id, scene.ROOT_IDS)
        self.assertEqual([s.class_index(i) for i in range(len(s))], [C_ROOT, C_PRS, C_POLY, C_LAYER, C_STD,
                                                                      C_NODE, C_NODE, C_NODE, C_PB2, C_NODE])
        self.assertEqual(s.entry(2).class_id, ClassId(0x1BF8338D, 0x192F6098))
        self.assertTrue(s.is_a(5, classids.SC_BASENODE, classids.NODE))
        self.assertFalse(s.is_a(0, classids.SC_BASENODE, classids.NODE))
        self.assertTrue(s.is_a(0, classids.SC_BASENODE, classids.ROOT_NODE))
        self.assertFalse(s.is_a(4, classids.SC_BASENODE, classids.ROOT_NODE))  # Standard shares (2, 0)
        offset, size = s.span(0)
        self.assertEqual(offset, 6)  # right after the root container's header
        self.assertEqual(s.span(1)[0], offset + size)
        self.assertEqual(s.chunk(8).container, False)
        with self.assertRaises(IndexError):
            s.class_index(10)
        with self.assertRaises(IndexError):
            s.entry(-1)

    def test_refs(self):
        s = self.s
        self.assertEqual(s.ref_list(2), [None, 8])
        self.assertEqual(s.refs(2), {1: 8})
        self.assertEqual(s.refs(5), {0: 1, 1: 2, 3: 4, 6: 3})
        self.assertEqual(s.ref_list(5), [])
        self.assertEqual(s.refs(1), {})
        self.assertEqual(s.refs(3), {})
        self.assertEqual(s.refs(8), {})  # a leaf object

    def test_root_ids(self):
        for root_id in (0x2014, 0x2023, 0x2025, 0x2999):
            self.assertEqual(make(*BASIC, root_id=root_id).root_id, root_id)

    def test_special_id(self):
        s = make(node(C_POLY), node(DERIVED, refs34(0)))
        self.assertIsNone(s.entry(1))
        self.assertEqual(s.class_index(1), DERIVED)

    def test_damaged(self):
        cases = {
            "ref past the end": [node(C_POLY, refs34(5))],
            "negative ref": [node(C_POLY, refs34(-2))],
            "pair ref past the end": [node(C_NODE, refs35((1, 9)))],
            "0x2034 odd size": [node(C_POLY, leaf(0x2034, b"\0\0\0\0\0"))],
            "0x2035 odd size": [node(C_POLY, leaf(0x2035, b"\x10\0\0\0\0\0\0\0\0"))],
            "0x2035 too short": [node(C_POLY, leaf(0x2035, b"\x10\0"))],
        }
        for name, objects in cases.items():
            with self.subTest(name), self.assertRaises(ChunkError):
                make(*objects).refs(0)

    def test_bad_streams(self):
        with self.assertRaises(ChunkError):
            scene.Scene(b"", CLASSES)
        with self.assertRaises(ChunkError):
            scene.Scene(leaf(0x2025, b"abc"), CLASSES)
        with self.assertRaises(ChunkError):
            scene.Scene(stream(*BASIC)[:-3], CLASSES)


class TestNodes(unittest.TestCase):
    def setUp(self):
        self.s = make(*BASIC)

    def test_records(self):
        s = self.s
        self.assertEqual(s.node_indices, (5, 6, 7, 9))
        self.assertEqual(s.root_node, 0)
        a = s.node(5)
        self.assertEqual((a.index, a.name, a.parent, a.parent_index, a.flags), (5, "A", None, 0, 0x800))
        self.assertEqual(a.pivot_position, (5.0, 6.0, 7.0))
        self.assertEqual(a.pivot_rotation, (0.0, 0.0, 0.5, 0.75))
        self.assertEqual((a.pivot_scale, a.pivot_scale_axis), ((2.0, 3.0, 4.0), (0.0, 0.0, 0.0, 1.0)))
        self.assertEqual((a.tm, a.object, a.material, a.layer), (1, 2, 4, 3))
        b = s.node(6)
        self.assertEqual((b.parent, b.flags, b.tm, b.material, b.layer), (5, 0x100800, None, None, None))
        self.assertEqual((b.pivot_position, b.pivot_rotation, b.pivot_scale, b.pivot_scale_axis),
                         ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0)))
        self.assertIs(s.node(5), a)
        self.assertEqual([n.index for n in s.nodes()], [5, 6, 7, 9])
        self.assertIn("'A'", repr(a))

    def test_same_name_two_nodes(self):
        s = self.s
        first, second = s.node(5), s.node(7)
        self.assertEqual(first.name, second.name)
        self.assertNotEqual(first.index, second.index)
        self.assertEqual((first.parent, second.parent), (None, 6))

    def test_parent_not_a_node_is_top_level(self):
        c = self.s.node(9)
        self.assertEqual((c.parent_index, c.parent), (2, None))

    def test_hierarchy(self):
        s = self.s
        self.assertEqual(s.children(), (5, 9))
        self.assertEqual(s.children(5), (6,))
        self.assertEqual(s.children(7), ())
        self.assertEqual(s.walk(), [5, 6, 7, 9])
        self.assertEqual(s.cut_cycles, ())
        self.assertEqual([s.parent(i) for i in s.node_indices], [None, 5, 6, None])

    def test_not_a_node(self):
        for call in (self.s.node, self.s.parent, self.s.children):
            with self.subTest(call.__name__), self.assertRaises(ChunkError):
                call(2)
        with self.assertRaises(IndexError):
            self.s.node(99)

    def test_pivot_scale_without_axis(self):
        s = make(node(C_ROOT), node(C_NODE, leaf(0x0960, struct.pack("<i", 0)),
                                    leaf(0x096C, struct.pack("<3f", 2, 2, 2))))
        n = s.node(1)
        self.assertEqual((n.pivot_scale, n.pivot_scale_axis, n.flags), ((2.0, 2.0, 2.0), (0.0, 0.0, 0.0, 1.0), 0))
        self.assertEqual(n.name, "")

    def test_short_records(self):
        cases = (leaf(0x0960, b"\0\0"), leaf(0x096A, bytes(8)), leaf(0x096B, bytes(12)), leaf(0x096C, bytes(8)))
        for bad in cases:
            with self.subTest(bad=bad.hex()), self.assertRaises(ChunkError):
                make(node(C_ROOT), node(C_NODE, bad)).node(1)

    def test_cycles_are_cut_at_the_lowest_index(self):
        # 1 -> 3 -> 2 -> 1 (a loop of three), 4 -> itself, 5 -> 2 (hangs below the loop), 6 top level
        s = make(node(C_ROOT),
                 node_obj("n1", 3), node_obj("n2", 1), node_obj("n3", 2), node_obj("n4", 4), node_obj("n5", 2),
                 node_obj("n6", 0))
        self.assertEqual(s.cut_cycles, (1, 4))
        self.assertEqual([s.parent(i) for i in s.node_indices], [None, 1, 2, None, 2, None])
        self.assertEqual(s.walk(), [1, 2, 3, 5, 4, 6])  # 2 under 1, then 3 and 5 under 2
        self.assertEqual(sorted(s.walk()), list(s.node_indices))
        self.assertEqual(s.node(1).parent_index, 3)

    def test_deep_chain(self):
        n = 10000
        objects = [node(C_ROOT)] + [node_obj("n", i, pivot=False) for i in range(n)]  # node k+1 -> parent k
        s = make(*objects)
        order = s.walk()
        self.assertEqual(order, list(range(1, n + 1)))
        self.assertEqual(s.parent(n), n - 1)
        objects[1] = node_obj("n", n, pivot=False)  # close the chain into one loop
        s = make(*objects)
        self.assertEqual(s.cut_cycles, (1,))
        self.assertEqual(len(s.walk()), n)


class TestDamagedRecords(unittest.TestCase):
    def test_one_bad_parent_poisons_only_itself(self):
        n = 3000
        objects = [node(C_ROOT)] + [node_obj("n%d" % k, 0, pivot=False) for k in range(n)]
        objects[1500] = node(C_NODE, leaf(0x0960, b"\0\0"), leaf(0x0962, utf16("bad")))
        objects[1501] = node_obj("child of bad", 1500, pivot=False)
        s = make(*objects)
        start = time.perf_counter()
        good = [s.node(i) for i in s.node_indices if i != 1500]
        self.assertLess(time.perf_counter() - start, 5)  # one hierarchy pass, not one per node
        self.assertEqual(len(good), n - 1)
        self.assertEqual(s.bad_parents, (1500,))
        self.assertIsNone(s.parent(1500))
        self.assertEqual(s.node(1501).parent, 1500)
        with self.assertRaises(ChunkError):
            s.node(1500)
        self.assertEqual(len(s.walk()), n)

    def test_reference_cap(self):
        saved = scene.MAX_REFS
        scene.MAX_REFS = 3
        try:
            s = make(node(C_POLY, refs34(0, 0, 0)), node(C_POLY, refs34(0, 0, 0, 0)),
                     node(C_NODE, refs35((0, 0), (1, 0), (2, 0))),
                     node(C_NODE, refs35((0, 0), (1, 0), (2, 0), (3, 0))))
            self.assertEqual(s.ref_list(0), [0, 0, 0])
            self.assertEqual(s.refs(2), {0: 0, 1: 0, 2: 0})
            for i in (1, 3):
                with self.subTest(i=i), self.assertRaises(ChunkError):
                    s.refs(i)
        finally:
            scene.MAX_REFS = saved

    def test_file_without_scene_stream(self):
        class NoScene:
            def exists(self, name):
                return False

        with self.assertRaises(ChunkError):
            scene.Scene.from_file(NoScene(), CLASSES)

    def test_0x2032_is_a_class_when_the_directory_reaches_it(self):
        big = classdir.ClassDirectory.parse(class_entry(1, 0, 1, "Node") * (DERIVED + 1))
        s = scene.Scene(stream(node(C_POLY), node(DERIVED, refs34(0))), big)
        self.assertFalse(s.is_derived(1))
        self.assertEqual(s.object_stack(1), (1, (), ()))
        self.assertTrue(make(node(C_POLY), node(DERIVED, refs34(0))).is_derived(1))


class TestObjectStack(unittest.TestCase):
    def test_stacks(self):
        # 0 poly, 1 mod, 2 mod, 3 derived [2, 1, 0], 4 derived [1, 3] (nested), 5 derived [1, -1] (empty base),
        # 6 derived [], 7 derived [8], 8 derived [7] (a cycle)
        s = make(node(C_POLY), node(C_MOD), node(C_MOD), node(DERIVED, refs34(2, 1, 0)),
                 node(DERIVED, refs34(1, 3)), node(DERIVED, refs34(1, -1)), node(DERIVED),
                 node(DERIVED, refs34(8)), node(DERIVED, refs34(7)))
        self.assertEqual(s.object_stack(0), (0, (), ()))
        self.assertEqual(s.object_stack(3), scene.Stack(0, (2, 1), (3,)))
        self.assertEqual(s.object_stack(4), scene.Stack(0, (1, 2, 1), (4, 3)))
        self.assertEqual(s.object_stack(5), scene.Stack(None, (1,), (5,)))
        self.assertEqual(s.object_stack(6), scene.Stack(None, (), (6,)))
        self.assertEqual(s.object_stack(1).base, 1)  # a modifier is returned as it is
        with self.assertRaises(ChunkError):
            s.object_stack(7)
        with self.assertRaises(IndexError):
            s.object_stack(9)


def _oracle(path):
    with open(path[:-4] + ".oracle.json", encoding="ascii") as f:
        return json.load(f)


L_NODE, L_LAYER, L_MANAGER = range(3)
LAYER_CLASSES = classdir.ClassDirectory.parse(
    class_entry(1, 0, 1, "Node") + class_entry(0x7E9858FE, 0x1DBA1DF0, 0x10F0, "Base Layer") +
    class_entry(0x0D7374FC, 0x51FF028E, 0x200, "Layer Manager"))


def layer_obj(name, flags=0, render=0x0B00D600, parent=None, raw_name=None):
    parts = [leaf(0x1000, b"\1\0\0\0"), leaf(0x1010, raw_name if raw_name is not None else name.encode("utf-8")),
             leaf(0x1020, struct.pack("<I", flags)), leaf(0x1050, struct.pack("<I", render))]
    if parent is None:
        parts.append(leaf(0x1090, b"\0"))
    else:
        parts += [leaf(0x1090, b"\1"), leaf(0x10A0, utf16("parent")), leaf(0x10B0, struct.pack("<i", parent))]
    return node(L_LAYER, *parts)


def layer_node(name, layer, flags=0x800, render=0x0F00D600):
    return node(L_NODE, refs35((6, layer)), leaf(0x0960, struct.pack("<iI", -1, flags)), leaf(0x0962, utf16(name)),
                leaf(0x099C, struct.pack("<I", render)))


class TestLayers(unittest.TestCase):
    def make(self, *objects):
        return scene.Scene(stream(*objects), LAYER_CLASSES)

    def test_records_flags_and_manager_order(self):
        s = self.make(layer_obj("0"), layer_obj("B", flags=0x100000), layer_obj("A", flags=0x200000, render=0x0B005600),
                      node(L_MANAGER, refs34(0, 2, 1)), layer_node("n", 1, flags=0x300940, render=0x0F005600))
        self.assertEqual(s.layer_indices, (0, 1, 2))
        self.assertEqual(s.layer_order(), [0, 2, 1])
        self.assertEqual([la.name for la in s.layers()], ["0", "A", "B"])
        b, a = s.layer(1), s.layer(2)
        self.assertEqual((b.hidden, b.frozen, b.renderable, b.parent), (True, False, True, None))
        self.assertEqual((a.hidden, a.frozen, a.renderable), (False, True, False))
        n = s.node(4)
        self.assertEqual(n.layer, 1)
        self.assertEqual((n.hidden, n.frozen, n.renderable, n.group_head, n.group_member), (True, True, False, True,
                                                                                          True))

    def test_unlisted_layers_follow_the_manager_order(self):
        s = self.make(layer_obj("x"), layer_obj("y"), node(L_MANAGER, refs34(1)))
        self.assertEqual(s.layer_order(), [1, 0])
        s = self.make(layer_obj("x"), layer_obj("y"))  # no manager at all
        self.assertEqual(s.layer_order(), [0, 1])

    def test_utf8_name(self):
        s = self.make(layer_obj("", raw_name=b"L\xc3\xa4\xe4\xb8\xad"), layer_obj("", raw_name=b"bad\xff\0"))
        self.assertEqual(s.layer(0).name, "Lä中")
        self.assertEqual(s.layer(1).name, "bad�")

    def test_parents_and_cycles(self):
        s = self.make(layer_obj("top"), layer_obj("child", parent=0), layer_obj("loop1", parent=3),
                      layer_obj("loop2", parent=2), layer_obj("not a layer", parent=5), layer_node("n", 0),
                      layer_obj("self", parent=6), layer_obj("outside", parent=-1))
        self.assertEqual([s.layer(i).parent for i in s.layer_indices], [None, 0, None, 2, None, None, None])

    def test_defaults_without_chunks(self):
        s = self.make(node(L_LAYER, leaf(0x1000, b"\0\0\0\0")),
                      node(L_NODE, leaf(0x0960, struct.pack("<iI", -1, 0)), leaf(0x0962, utf16("n"))))
        la = s.layer(0)
        self.assertEqual((la.name, la.hidden, la.frozen, la.renderable, la.parent), ("", False, False, True, None))
        n = s.node(1)
        self.assertEqual((n.renderable, n.hidden, n.layer), (True, False, None))

    def test_damaged_records(self):
        s = self.make(node(L_LAYER, leaf(0x1020, b"\1")), node(L_LAYER, leaf(0x1050, b"")), leaf(L_LAYER),
                      node(L_NODE, leaf(0x0960, struct.pack("<iI", -1, 0)), leaf(0x099C, b"\0\0")))
        for i in (0, 1, 2):
            with self.assertRaises(ChunkError):
                s.layer(i)
        with self.assertRaises(ChunkError):
            s.layer(3)  # a node, not a layer
        with self.assertRaises(ChunkError):
            s.node(3)
        self.assertEqual(s.layers(), [])

    def test_short_parent_is_top_level(self):
        body = [leaf(0x1010, b"p"), leaf(0x1090, b"\1"), leaf(0x10B0, b"\0\0")]
        s = self.make(layer_obj("top"), node(L_LAYER, *body))
        self.assertIsNone(s.layer(1).parent)


def _scene(cf):
    return scene.Scene.from_file(cf)


@unittest.skipUnless(FIXTURES, "no fixtures")
class TestFixtures(unittest.TestCase):
    def test_against_the_oracle(self):
        for path in FIXTURES:
            oracle = _oracle(path)
            with self.subTest(fixture=os.path.basename(path)), cfb.CompoundFile(path) as cf:
                s = _scene(cf)
                self.assertIn(s.root_id, scene.ROOT_IDS)
                self.assertEqual(s.cut_cycles, ())
                order = s.walk()
                expected = oracle["nodes"]
                self.assertEqual(len(order), oracle["node_count"])
                self.assertEqual(len(s.node_indices), oracle["node_count"])
                nodes = [s.node(i) for i in order]
                self.assertEqual([n.name for n in nodes], [e["name"] for e in expected])
                by_handle = {e["handle"]: e["index"] for e in expected}
                position = {i: k for k, i in enumerate(order)}
                for n, e in zip(nodes, expected):
                    want = None if e["parent"] is None else by_handle[e["parent"]]
                    self.assertEqual(None if n.parent is None else position[n.parent], want, e["name"])
                    if n.parent is None:
                        self.assertEqual(n.parent_index, s.root_node)
                    for got, ref in zip(n.pivot_position + n.pivot_scale, e["offset_pos"] + e["offset_scale"]):
                        self.assertAlmostEqual(got, ref, places=4)
                    # every fixture's offset rotation is the identity: its sign convention is not shown yet
                    self.assertEqual(e["offset_rot"], [0, 0, 0, 1])
                    self.assertEqual(n.pivot_rotation, (0.0, 0.0, 0.0, 1.0))
                    stack = s.object_stack(n.object)
                    base = s.entry(stack.base)
                    self.assertEqual(["0x%08x" % base.class_a, "0x%08x" % base.class_b], e["base_class_id"])
                    self.assertEqual(base.superclass, e["base_superclass"])
                    self.assertEqual(len(stack.modifiers), len(e["modifiers"]))
                    sharing = sorted(expected[position[m.index]]["handle"] for m in nodes if m.object == n.object)
                    self.assertEqual(sharing, e["instances"], e["name"])
                    self.assertEqual(n.material is not None, e["material"] is not None, e["name"])
                    self.assertEqual(s.entry(n.layer).superclass, classids.SC_LAYER)
                    self.assertTrue(s.is_a(n.tm, classids.SC_CTRL_MATRIX3, classids.PRS))
                    flags = (n.hidden, n.frozen, n.renderable, s.layer(n.layer).name)
                    self.assertEqual(flags, (e["hidden"], e["frozen"], e["renderable"], e["layer"]), e["name"])
                layers = [(la.name, la.hidden, la.frozen, la.renderable) for la in s.layers()]
                self.assertEqual(layers, [(e["name"], e["hidden"], e["frozen"], e["renderable"])
                                          for e in oracle["layers"]])
                self.assertTrue(all(la.parent is None for la in s.layers()))
                del nodes

    def test_groups(self):
        with cfb.CompoundFile(os.path.join(ROOT, "tests", "fixtures", "layers_flags.max")) as cf:
            s = _scene(cf)
            by_name = {n.name: n for n in s.nodes()}
            self.assertEqual([k for k, n in by_name.items() if n.group_head], ["FixtureGroup"])
            self.assertEqual(sorted(k for k, n in by_name.items() if n.group_member),
                             ["FixtureGroupA", "FixtureGroupB"])
            members = sorted(by_name[k].index for k in ("FixtureGroupA", "FixtureGroupB"))
            self.assertEqual(sorted(s.children(by_name["FixtureGroup"].index)), members)

    def test_flags_and_pair_heads(self):
        """The values docs/FORMAT.md quotes: 0x0960 flags per node, the first u32 of 0x2035 per class."""
        flags = {"FixtureHidden": 0x100800, "FixtureGroup": 0x40, "FixtureGroupA": 0x900, "FixtureGroupB": 0x900,
                 "FixtureInstance01": 0, "FixtureInstance02": 0, "FixtureInstance03": 0, "FixtureCopy": 0}
        heads = {"Node": 16, "RootNode": 16, "Texmaps": 48, "Bezier Float": 2, "Bezier Scale": 2, "Bezier Color": 2,
                 "Boolean Controller": 2, "Grid Reference": 2, "VRayMtl": 34,
                 "": 2}  # Custom Curve Control's point class, nameless in the class directory (texmap_rules' Falloffs)
        varies = {"ParamBlock2"}  # the number of reference slots of its descriptor: 25 and 37 in the fixtures
        for path in FIXTURES:
            with self.subTest(fixture=os.path.basename(path)), cfb.CompoundFile(path) as cf:
                s = _scene(cf)
                for n in s.nodes():
                    self.assertEqual(n.flags, flags.get(n.name, 0x800), n.name)
                seen = {}
                for i in range(len(s)):
                    chunk = s.chunk(i)
                    pairs = chunk.first(0x2035) if chunk.container else None
                    if pairs is not None:
                        head = pairs.unpack("<I")[0]
                        slots = [slot for slot, _v in struct.iter_unpack("<Ii", pairs.tobytes()[4:])]
                        self.assertTrue(all(slot < head for slot in slots), (s.entry(i).name, head, slots))
                        if s.entry(i).name not in varies:
                            seen.setdefault(s.entry(i).name, set()).add(head)
                self.assertEqual(seen, {k: {v} for k, v in heads.items() if k in seen})
                self.assertTrue({"Node", "RootNode", "Texmaps"} <= set(seen))
                del chunk, pairs

    def test_hierarchy_twins(self):
        with cfb.CompoundFile(HIERARCHY) as cf:
            s = _scene(cf)
            by_name = {}
            for n in s.nodes():
                by_name.setdefault(n.name, []).append(n)
            twins = by_name["FixtureTwin"]
            self.assertEqual(len(twins), 2)
            self.assertNotEqual(twins[0].index, twins[1].index)
            root = by_name["FixtureRoot"][0]
            self.assertEqual(sorted((t.parent is None, t.parent) for t in twins), [(False, root.index), (True, None)])
            self.assertEqual(s.children(root.index), (by_name["FixtureChild"][0].index, twins[0].index))
            self.assertNotEqual(twins[0].object, twins[1].object)


if __name__ == "__main__":
    unittest.main()
