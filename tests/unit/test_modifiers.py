# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/modifiers.py, the modifier stack of a node: no Blender. Every committed fixture against
its 3ds Max oracle (classes, names, order, the three switches, the modifier context), stack_basic's instanced
modifier and nested stack, and synthetic Scene streams for the world-space derived object and damaged input.

    python -I -m unittest discover tests
"""
import glob
import importlib.util
import json
import math
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
STACK_BASIC = os.path.join(ROOT, "tests", "fixtures", "stack_basic.max")


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
scene = _load("maxdrop_reader.scene", os.path.join(_READER, "scene.py"))
pblock = _load("maxdrop_reader.pblock", os.path.join(_READER, "pblock.py"))
modifiers = _load("maxdrop_reader.modifiers", os.path.join(_READER, "modifiers.py"))
ChunkError = chunks.ChunkError


def _oracle(path):
    with open(path[:-4] + ".oracle.json", encoding="ascii") as f:
        return json.load(f)


def _cid(pair):
    return tuple(int(x, 16) for x in pair)


def _close(test, got, want, msg):
    test.assertEqual(len(got), len(want), msg)
    for g, w in zip(got, want):
        test.assertTrue(math.isclose(g, w, rel_tol=1e-5, abs_tol=1e-4), "%s: %r vs %r" % (msg, got, want))


def _stacks(path):
    """{node name: (ModifierStack, node)} of a fixture, read once."""
    with cfb.CompoundFile(path) as cf:
        s = scene.Scene.from_file(cf)
        reader = modifiers.Modifiers(s)
        out = {}
        for n in s.nodes():
            out[n.name] = (reader.stack(n), s.object_stack(n.object) if n.object is not None else None)
        return out


@unittest.skipUnless(FIXTURES, "no fixtures")
class TestFixtures(unittest.TestCase):
    def test_every_fixture_against_the_oracle(self):
        """Class, name, switches and context of every modifier, bottom first (the oracle lists them top first),
        and the base object, which is the one Scene.object_stack finds."""
        for path in FIXTURES:
            oracle = _oracle(path)
            with self.subTest(fixture=os.path.basename(path)):
                stacks = _stacks(path)
                for n in oracle["nodes"]:
                    st, plain = stacks[n["name"]]
                    label = n["name"]
                    self.assertEqual(st.issues, (), label)
                    self.assertEqual(st.base, plain.base if plain is not None else None, label)
                    want = list(reversed(n["modifiers"]))
                    self.assertEqual([m.class_id for m in st.modifiers], [_cid(m["class_id"]) for m in want], label)
                    self.assertEqual([m.name for m in st.modifiers], [m["name"] for m in want], label)
                    self.assertEqual([(m.enabled, m.enabled_in_views, m.enabled_in_renders) for m in st.modifiers],
                                     [(m["enabled"], m["enabled_in_views"], m["enabled_in_renders"]) for m in want],
                                     label)
                    for m, w in zip(st.modifiers, want):
                        self.assertIsNotNone(m.context.tm, label)
                        _close(self, [v for row in m.context.tm for v in row[:3]], w["context_tm"], label)
                        self.assertEqual([row[3] for row in m.context.tm], [0.0, 0.0, 0.0, 1.0], label)
                        # Max computes a context's box when the modifier first needs it: the file may hold none
                        if m.context.box is not None:
                            _close(self, m.context.box[0] + m.context.box[1],
                                   w["context_bbox_min"] + w["context_bbox_max"], label)
                        self.assertFalse(m.world_space, label)

    @unittest.skipUnless(os.path.exists(STACK_BASIC), "no stack_basic")
    def test_stack_basic(self):
        stacks = _stacks(STACK_BASIC)
        smooth = stacks["FixtureTurbo"][0]
        self.assertEqual([m.name for m in smooth.modifiers], ["FixtureUVW", "TurboSmooth"])  # bottom first
        uvw, turbo = smooth.modifiers
        # UVW Map keeps the old ParamBlock: 0 map type (4 = box), 9..11 length, width, height
        self.assertEqual(list(uvw.blocks), [])
        old = next(iter(uvw.legacy.values()))
        self.assertEqual((old.get(0), old.get(9), old.get(10), old.get(11)), (4, 30.0, 30.0, 30.0))
        self.assertIsNotNone(uvw.gizmo)
        # TurboSmooth: a ParamBlock2, parameter 0 = iterations
        self.assertEqual([b.get(0) for b in turbo.blocks.values()], [2])
        self.assertIsNone(turbo.gizmo)
        self.assertEqual(smooth.modifiers[0].context.box, ((-10.0, -10.0, 0.0), (10.0, 10.0, 20.0)))

        flags = stacks["FixtureFlags"][0]
        self.assertEqual([(m.name, m.enabled, m.enabled_in_views, m.enabled_in_renders) for m in flags.modifiers],
                         [("Bend", False, True, True), ("Taper", True, False, True), ("Twist", True, True, False)])
        self.assertEqual([m.active for m in flags.modifiers], [False, False, True])
        self.assertEqual([m.renders for m in flags.modifiers], [False, True, False])

        a, b = stacks["FixtureSharedA"][0], stacks["FixtureSharedB"][0]
        self.assertEqual(a.modifiers[0].index, b.modifiers[0].index)  # one modifier object on two nodes
        self.assertNotEqual(a.derived, b.derived)
        self.assertEqual(a.modifiers[0].context.tm[3], (-10.0, 0.0, -10.0, 1.0))
        self.assertEqual(b.modifiers[0].context.tm[3], (10.0, 0.0, -10.0, 1.0))
        self.assertEqual(a.modifiers[0].context.box, ((-15.0, -5.0, -10.0), (15.0, 5.0, 10.0)))
        self.assertEqual(a.modifiers[0].name, "FixtureNoise")

        nested, ref = stacks["FixtureNested"][0], stacks["FixtureNestedRef"][0]
        self.assertEqual(nested.base, ref.base)
        self.assertEqual([m.name for m in ref.modifiers], ["Taper", "Twist"])
        self.assertEqual(ref.modifiers[0].index, nested.modifiers[0].index)
        self.assertEqual(len(ref.derived), 2)
        self.assertEqual(ref.derived[1], nested.derived[0])
        self.assertEqual(ref.modifiers[0].derived, nested.derived[0])  # the derived object holding each one
        self.assertEqual(ref.modifiers[1].derived, ref.derived[0])

    def test_box_not_computed(self):
        """modifier_pivot was saved before anything evaluated its stacks: the Bend and the TurboSmooth have the
        empty box (+1e30 .. -1e30), the UVW Map one; the oracle, dumped after evaluating, has all three."""
        stacks = _stacks(os.path.join(ROOT, "tests", "fixtures", "modifier_pivot.max"))
        uvw, bend = stacks["FixtureBent"][0].modifiers
        self.assertEqual((uvw.context.box, bend.context.box), (((-5.0, -5.0, 0.0), (5.0, 5.0, 40.0)), None))
        self.assertIsNone(stacks["FixtureSmooth"][0].modifiers[0].context.box)

    def test_module_function(self):
        with cfb.CompoundFile(STACK_BASIC) as cf:
            s = scene.Scene.from_file(cf)
            n = next(n for n in s.nodes() if n.name == "FixtureFlags")
            def key(st):  # parameter blocks are compared by what they hold, not by identity
                return st.base, st.derived, st.issues, [m[:8] + (sorted(m.blocks), sorted(m.legacy)) + m[10:]
                                                        for m in st.modifiers]
            self.assertEqual(key(modifiers.stack(s, n)), key(modifiers.Modifiers(s).stack(n)))
            self.assertEqual(key(modifiers.Modifiers(s).object_stack(n.object)), key(modifiers.stack(s, n)))


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def _entry(a, b, superclass, name):
    return node(0x2040, leaf(0x2060, struct.pack("<iIII", -1, a, b, superclass)),
                leaf(0x2042, name.encode("utf-16-le")))


def _refs(*values):
    return leaf(0x2034, struct.pack("<%di" % len(values), *values))


IDENTITY = struct.pack("<12fI", 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 7)
EMPTY_BOX = struct.pack("<6f", 1e30, 1e30, 1e30, -1e30, -1e30, -1e30)


def _context(tm=IDENTITY, box=EMPTY_BOX):
    parts = [leaf(0x2510, tm)] if tm is not None else []
    if box is not None:
        parts.append(leaf(0x2511, box))
    return node(0x2500, *parts, leaf(0x2513, b"\x00\x01\x04\x00"))


def _derived(cid, refs, contexts):
    return node(cid, _refs(*refs), leaf(0x204B, b"\x2e"), *contexts, leaf(0x2501))


def _modifier(cls, *info):
    return node(cls, leaf(0x204B, b"\x2e"), node(0x39BF, *info))


def _scene(*objects):
    """Class indices: 0 Editable Poly, 1 Bend (modifier), 2 Map Scaler (world-space modifier), 3 Node."""
    classes = classdir.ClassDirectory.parse(
        _entry(0x1BF8338D, 0x192F6098, 0x10, "Editable Poly") + _entry(0x10, 0, 0x810, "Bend") +
        _entry(0x2A3C4D5E, 0, 0x820, "MapScaler") + _entry(1, 0, 1, "Node"))
    return scene.Scene(node(0x2025, *objects), classes)


class TestSynthetic(unittest.TestCase):
    def test_world_space_derived_object(self):
        """0x2033 (a scratch file of 3ds Max 2020 with a Map Scaler binding): [world-space modifiers, the object's
        derived object]; its modifiers come last, marked world_space."""
        s = _scene(node(0), _modifier(1, leaf(0x0100)), _modifier(2, leaf(0x0100)),
                   _derived(0x2032, (1, 0), [_context()]), _derived(0x2033, (2, 3), [_context()]))
        st = modifiers.Modifiers(s).object_stack(4)
        self.assertEqual(st.base, 0)
        self.assertEqual([(m.index, m.name, m.world_space) for m in st.modifiers],
                         [(1, "Bend", False), (2, "MapScaler", True)])
        self.assertEqual(st.derived, (4, 3))
        self.assertEqual(st.issues, ())

    def test_no_object_and_bare_object(self):
        s = _scene(node(0))
        reader = modifiers.Modifiers(s)
        self.assertEqual(reader.object_stack(None), modifiers.ModifierStack(None, (), (), ()))
        self.assertEqual(reader.object_stack(0), modifiers.ModifierStack(0, (), (), ()))

    def test_empty_slots_and_empty_base(self):
        s = _scene(node(0), _modifier(1), _derived(0x2032, (-1, 1, -1), [_context(), _context()]))
        st = modifiers.Modifiers(s).object_stack(2)
        self.assertEqual((st.base, [m.index for m in st.modifiers]), (None, [1]))

    def test_missing_and_damaged_contexts(self):
        """A context that is missing or short leaves that modifier without one (an issue); the stack is kept."""
        s = _scene(node(0), _modifier(1), _modifier(1),
                   _derived(0x2032, (1, 2, 0), [_context(tm=IDENTITY[:20])]))
        st = modifiers.Modifiers(s).object_stack(3)
        self.assertEqual([m.index for m in st.modifiers], [2, 1])
        self.assertEqual([m.context for m in st.modifiers], [None, None])
        self.assertEqual(len(st.issues), 2)

    def test_non_finite_tm_and_box(self):
        nan_tm = struct.pack("<12fI", float("nan"), 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 7)
        s = _scene(node(0), _modifier(1), _derived(0x2032, (1, 0), [_context(tm=nan_tm, box=b"\x00" * 7)]))
        st = modifiers.Modifiers(s).object_stack(2)
        self.assertIsNone(st.modifiers[0].context)
        self.assertEqual(len(st.issues), 2)

    def test_flags_and_name(self):
        name = "Bent ä".encode("utf-16-le")
        s = _scene(node(0), _modifier(1, leaf(0x0100, name), leaf(0x0110), leaf(0x0130)), node(1),
                   _derived(0x2032, (1, 0), [_context()]), _derived(0x2032, (2, 0), [_context()]))
        reader = modifiers.Modifiers(s)
        m = reader.object_stack(3).modifiers[0]
        self.assertEqual((m.name, m.enabled, m.enabled_in_views, m.enabled_in_renders), ("Bent ä", False, True,
                                                                                           False))
        bare = reader.object_stack(4).modifiers[0]  # no 0x39BF at all: the class name, every switch on
        self.assertEqual((bare.name, bare.enabled, bare.enabled_in_views, bare.enabled_in_renders),
                         ("Bend", True, True, True))

    def test_cycle(self):
        s = _scene(node(0), _modifier(1), _derived(0x2032, (1, 3), [_context()]),
                   _derived(0x2032, (1, 2), [_context()]))
        with self.assertRaises(ChunkError):
            modifiers.Modifiers(s).object_stack(2)

    def test_damaged_modifier_poisons_itself(self):
        """A modifier whose references cannot be read keeps its class and switches, no blocks, and an issue."""
        s = _scene(node(0), node(1, leaf(0x2034, b"\x01\x02\x03")), _derived(0x2032, (1, 0), [_context()]))
        st = modifiers.Modifiers(s).object_stack(2)
        self.assertEqual([(m.index, m.blocks, m.legacy) for m in st.modifiers], [(1, {}, {})])
        self.assertEqual(len(st.issues), 1)

    def test_shared_modifier_read_once(self):
        s = _scene(node(0), _modifier(1), _derived(0x2032, (1, 0), [_context()]),
                   _derived(0x2032, (1, 0), [_context()]))
        reader = modifiers.Modifiers(s)
        a, b = reader.object_stack(2).modifiers[0], reader.object_stack(3).modifiers[0]
        self.assertIs(a.blocks, b.blocks)
        self.assertEqual((a.derived, b.derived), (2, 3))


if __name__ == "__main__":
    unittest.main()
