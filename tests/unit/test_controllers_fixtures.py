# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/controllers/ on the fixtures (controllers, tangents, ranges, look-at weights)
and the parameter controllers of materials and maps, no Blender.

    python -I -m unittest discover tests
"""
import importlib
import json
import math
import os
import struct
import sys
import types
import unittest

_TESTS = "maxdrop_unit_tests"  # tests/unit as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_unit_tests.controllers_support import (  # noqa: E402 (after the loader)
    _PKG, AT_FRAME_30, Build, C_BCOLOR, C_FLOATLIST, C_UNKNOWN_FLOAT, cfb, CLASSES, classids, ct,
    FIXTURES, KEYFRAMED, keys_of, leaf, list_block, node, pblock, refs34, ROOT, rows12, scene,
    TOLERANCE,
)


@unittest.skipUnless(FIXTURES, "no fixtures")
class TestFixtures(unittest.TestCase):
    def test_world_and_object_transforms_match_the_oracle(self):
        for path in FIXTURES:
            name = os.path.basename(path)
            with open(path[:-4] + ".oracle.json", encoding="utf-8") as f:
                oracle = json.load(f)
            with cfb.CompoundFile(path) as cf:
                s = scene.Scene.from_file(cf)
                t = ct.Transforms(s)
                walk = s.walk()
                self.assertEqual(len(walk), oracle["node_count"], name)
                for i, o in zip(walk, oracle["nodes"]):
                    self.assertEqual(s.node(i).name, o["name"])
                    for got, key in ((t.world(i), "transform"), (t.object_world(i), "object_transform")):
                        for k, (a, e) in enumerate(zip(rows12(got), o[key])):
                            self.assertLessEqual(abs(a - e), TOLERANCE, "%s node %d %s[%d]: %r vs %r" %
                                                 (name, o["index"], key, k, a, e))
                self.assertEqual(t.issues, [], name)


CONTROLLERS = os.path.join(ROOT, "tests", "fixtures", "controllers.max")


@unittest.skipUnless(os.path.exists(CONTROLLERS), "no controllers fixture")
class TestControllersFixture(unittest.TestCase):
    """controllers.max holds what tools/fixtures/controllers.ms says: a regenerated fixture that lost a controller
    would still pass the oracle comparison above."""

    CLASSES = {
        "FixtureScaleXYZ": {"ScaleXYZ"},
        "FixtureLinear": {"Linear Position", "Linear Rotation", "Linear Scale"},
        "FixtureTCB": {"TCB Position", "TCB Rotation", "TCB Scale"},
        "FixtureBezier": {"Bezier Position", "Smooth Rotation", "Bezier Scale"},
        "FixtureLinearKeyed": {"Linear Position", "Linear Rotation", "Linear Scale"},
        "FixtureTCBKeyed": {"TCB Position", "TCB Rotation", "TCB Scale"},
        "FixtureBezierKeyed": {"Bezier Position", "Smooth Rotation", "Bezier Scale"},
        "FixtureLinearBetween": {"Linear Position", "Linear Rotation", "Linear Scale"},
        "FixtureTCBBefore": {"TCB Position", "TCB Rotation", "TCB Scale"},
        "FixturePosList": {"Position List"},
        "FixtureRotList": {"Rotation List"},
        "FixtureScaleList": {"Scale List"},
        "FixtureFloats": {"Linear Float", "TCB Float", "Float List"},
        "FixtureFloatsKeyed": {"Linear Float", "TCB Float"},
        "FixtureCam": {"Look At"},
    }
    EULER = {"FixtureEulerMulti": 0, "FixtureEulerXZY": 101, "FixtureEulerYZX": 102, "FixtureEulerYXZ": 103,
             "FixtureEulerZXY": 104, "FixtureEulerZYX": 105}

    @classmethod
    def setUpClass(cls):
        cls.cf = cfb.CompoundFile(CONTROLLERS)
        cls.s = scene.Scene.from_file(cls.cf)
        cls.nodes = {cls.s.node(i).name: i for i in cls.s.walk()}

    @classmethod
    def tearDownClass(cls):
        cls.cf.close()

    def tree(self, name):
        """The controllers below node name's transform controller, itself included."""
        s, out, todo = self.s, [], [self.s.node(self.nodes[name]).tm]
        while todo:
            i = todo.pop()
            entry = s.entry(i)
            if i in out or entry is None or entry.superclass == classids.SC_BASENODE:
                continue
            out.append(i)
            todo.extend(r for r in s.refs(i).values() if r is not None)
        return out

    def test_controller_classes(self):
        for name, want in self.CLASSES.items():
            names = {self.s.entry(i).name for i in self.tree(name)}
            self.assertLessEqual(want, names, name)

    def test_euler_orders(self):
        for name, stored in self.EULER.items():
            euler = self.s.refs(self.s.node(self.nodes[name]).tm)[1]
            self.assertEqual(self.s.chunk(euler).first(0x1003).unpack("<i")[0], stored, name)
            angles = [self.s.chunk(f).first(0x7127).first(0x2501).unpack("<f")[0]
                      for f in (self.s.refs(euler)[k] for k in range(3))]
            self.assertTrue(all(abs(a) > 0.3 for a in angles), (name, angles))  # three angles: the order matters

    def test_scale_axis_turned(self):
        bscale = self.s.refs(self.s.node(self.nodes["FixtureScaleAxis"]).tm)[2]
        value = self.s.chunk(bscale).first(0x2505).unpack("<7f")
        self.assertEqual([round(v, 4) for v in value[:3]], [2.0, 0.5, 1.0])
        self.assertLess(abs(value[6]), 0.99)  # the axis quaternion is a turn, not the identity

    def test_keyed_values_saved_at_frame_30(self):
        # every keyed controller's saved value holds at frame 30 only: the keys decide the frame-0 value
        keyed = 0
        for name in self.nodes:
            if name == "FixtureCam.Target":
                continue
            for i in self.tree(name):
                chunk = self.s.chunk(i)
                for holder in (chunk, chunk.first(0x7127) if chunk.container else None):
                    if holder is None or not holder.container:
                        continue
                    if any(c.id in range(0x2510, 0x2530) for c in holder.children):
                        keyed += 1
                        self.assertEqual(holder.first(0x2500).unpack("<ii"), AT_FRAME_30, (name, i))
        self.assertEqual(keyed, 23)

    def test_list_weights_stored(self):
        for name in ("FixturePosList", "FixtureRotList", "FixtureScaleList", "FixtureFloats"):
            lists = [i for i in self.tree(name) if self.s.entry(i).name.endswith(" List")]
            self.assertEqual(len(lists), 1, name)
            refs = self.s.refs(lists[0])
            block = next(r for r in refs.values() if self.s.entry(r).superclass == classids.SC_PARAMETER_BLOCK2)
            pb = pblock.ParamBlock2.from_chunk(self.s.chunk(block), self.s.refs(block), refs, len(self.s))
            self.assertEqual(pb.value(0), [0.5, 1.0] if name == "FixtureFloats" else [0.5, 0.5], name)


TANGENTS = os.path.join(ROOT, "tests", "fixtures", "controllers_tangents.max")


@unittest.skipUnless(os.path.exists(TANGENTS), "no controllers_tangents fixture")
class TestTangentsFixture(unittest.TestCase):
    """controllers_tangents.max holds what tools/fixtures/controllers_tangents.ms says: every keyed controller has
    frame 0 strictly between two keys, a saved value that does not hold at frame 0, and tangents other than linear."""

    KEYED = {"FixtureBezierFloats": ["Bezier Float"] * 3, "FixtureBezierCustom": ["Bezier Float"],
             "FixtureBezierPosition": ["Bezier Position"], "FixtureBezierScale": ["Bezier Scale"],
             "FixtureSmoothRotation": ["Smooth Rotation"], "FixtureTCBFloats": ["TCB Float"] * 2,
             "FixtureTCBPosition": ["TCB Position"], "FixtureTCBRotation": ["TCB Rotation"],
             "FixtureTCBScale": ["TCB Scale"], "FixtureLinearRotationWide": ["Linear Rotation"]}

    @classmethod
    def setUpClass(cls):
        cls.cf = cfb.CompoundFile(TANGENTS)
        cls.s = scene.Scene.from_file(cls.cf)
        cls.nodes = {cls.s.node(i).name: i for i in cls.s.walk()}

    @classmethod
    def tearDownClass(cls):
        cls.cf.close()

    def keyed(self, name):
        """[(class name, holder chunk, records around time 0 as (flags, floats))] of node name's keyed controllers."""
        s, out, seen, todo = self.s, [], [], [self.s.node(self.nodes[name]).tm]
        while todo:
            i = todo.pop()
            entry = s.entry(i)
            if i in seen or entry is None or entry.superclass == classids.SC_BASENODE:
                continue
            seen.append(i)
            todo.extend(r for r in s.refs(i).values() if r is not None)
            if entry.name not in KEYFRAMED:
                continue
            _c, key_id, size, _count = KEYFRAMED[entry.name]
            chunk = s.chunk(i)
            for holder in (chunk, chunk.first(0x7127)):
                keys = holder.first(key_id) if holder is not None and holder.container else None
                if keys is None:
                    continue
                view = keys.view()
                recs = [struct.unpack_from("<iI%df" % ((size - 8) // 4), view, k * size)
                        for k in range(len(view) // size)]
                k = next((k for k in range(1, len(recs)) if recs[k - 1][0] < 0 < recs[k][0]), None)
                self.assertIsNotNone(k, "%s: no two keys around frame 0" % name)
                out.append((entry.name, holder, [(r[1], r[2:]) for r in recs[k - 1:k + 1]]))
        return out

    # maxdrop-em3.144: free handles, constant velocity, scale axes that differ, TCB spins, a whole Linear turn
    SPUN = {"FixtureFreeHandles": ["Bezier Float"] * 3, "FixtureFreePosition": ["Bezier Position"],
            "FixtureConstantVelocity": ["Bezier Position"], "FixtureScaleAxesBezier": ["Bezier Scale"],
            "FixtureScaleAxesTCB": ["TCB Scale"], "FixtureScaleAxesLinear": ["Linear Scale"],
            "FixtureTCBSpinStart": ["TCB Rotation"], "FixtureTCBSpinEnd": ["TCB Rotation"],
            "FixtureTCBSpinMiddle": ["TCB Rotation"], "FixtureTCBTurn": ["TCB Rotation"],
            "FixtureLinearRotationTurn": ["Linear Rotation"]}

    def test_frame_0_between_two_keys(self):
        for name, want in {**self.KEYED, **self.SPUN}.items():
            with self.subTest(name):
                found = self.keyed(name)  # fails where no two keys straddle frame 0
                self.assertEqual(sorted(c for c, _h, _r in found), want)
                for _c, holder, _r in found:
                    start, end = holder.first(0x2500).unpack("<ii")
                    if name in self.KEYED:
                        self.assertEqual((start, end), AT_FRAME_30)
                    else:  # FixtureTCBSpinMiddle's last key is at frame 15: its interval is (2400, 2400)
                        self.assertFalse(start <= 0 <= end, name)

    def test_tangents_are_not_linear(self):
        for name in self.KEYED:
            for cls, _h, ((flags_a, a), (flags_b, b)) in self.keyed(name):
                with self.subTest(name, cls=cls):
                    if cls.startswith("Bezier"):  # out of the earlier key, into the later: not both linear (type 1)
                        self.assertNotEqual(((flags_a >> 10) & 7, (flags_b >> 7) & 7), (1, 1))
                    elif cls.startswith("TCB"):  # tension, continuity, bias, eases: not all 25 / 0
                        n = {"TCB Float": 1, "TCB Position": 3, "TCB Rotation": 4, "TCB Scale": 7}[cls]
                        self.assertTrue(any(a[n:n + 5]) or any(b[n:n + 5]))

    def test_turns_past_half_a_revolution(self):
        (_c, _h, (_a, (_fb, b))), = self.keyed("FixtureTCBRotation")
        self.assertGreater(b[12], math.pi)  # 200 degrees from the earlier key
        (_c, _h, ((_fa, a), (_fb, b))), = self.keyed("FixtureLinearRotationWide")
        self.assertLess(sum(x * y for x, y in zip(a[:4], b[:4])), 0.0)  # stored the long way round

    def test_free_handles_and_constant_velocity(self):
        for name in ("FixtureFreeHandles", "FixtureFreePosition"):
            for cls, _h, ((flags_a, a), (flags_b, b)) in self.keyed(name):
                with self.subTest(name, values=(a[0], b[0])):
                    n = {"Bezier Float": 1, "Bezier Position": 3}[cls]
                    self.assertTrue((flags_a | flags_b) & 0x100000)  # a free handle in the segment
                    if flags_a & 0x100000:
                        self.assertGreater(min(a[4 * n:5 * n]), 0.0)  # the out length, in frames
                    if flags_b & 0x100000:
                        self.assertGreater(min(b[3 * n:4 * n]), 0.0)
        longest = max(a[4] for _c, _h, ((_fa, a), _b) in self.keyed("FixtureFreeHandles"))
        self.assertGreater(longest, 50.0)  # a handle longer than its 50-frame segment
        (_c, _h, ((flags_a, a), (flags_b, b))), = self.keyed("FixtureConstantVelocity")
        self.assertTrue(flags_a & 0x8000)
        self.assertFalse(flags_a & 0x100000)
        self.assertEqual([round(v, 4) for v in b[9:12]], [0.6, 0.1, 0.3])  # in lengths that do not count

    def test_scale_axes_differ(self):
        for name in ("FixtureScaleAxesBezier", "FixtureScaleAxesTCB", "FixtureScaleAxesLinear"):
            (_c, _h, ((_fa, a), (_fb, b))), = self.keyed(name)
            dot = sum(x * y for x, y in zip(a[3:7], b[3:7]))
            self.assertTrue(0.0 < dot < 0.99, (name, dot))

    def test_spins_and_whole_turns(self):
        # the eased fraction of frame 0 against the half-turn h at either end of a turn past a revolution
        for name, piece in (("FixtureTCBSpinStart", "first"), ("FixtureTCBSpinEnd", "last"),
                            ("FixtureTCBSpinMiddle", "middle"), ("FixtureTCBTurn", "last")):
            with self.subTest(name):
                (_c, holder, ((_fa, a), (_fb, b))), = self.keyed(name)
                view = holder.first(0x2522).view()
                times = [struct.unpack_from("<i", view, k * 92)[0] for k in range(len(view) // 92)]
                t0 = max(t for t in times if t < 0)
                t1 = min(t for t in times if t > 0)
                self.assertGreaterEqual(b[12], 2 * math.pi)
                u, h = ct.ease(-t0 / (t1 - t0), a[8], b[7]), math.pi / b[12]
                self.assertEqual("first" if u < h else "last" if u > 1 - h else "middle", piece)
        (_c, _h, ((_fa, a), (_fb, b))), = self.keyed("FixtureLinearRotationTurn")
        self.assertLess(1.0 + sum(x * y for x, y in zip(a[:4], b[:4])), 5e-7)  # opposite quaternions

    def test_lists_of_turned_entries(self):
        s = self.s
        scale_list = s.refs(s.node(self.nodes["FixtureScaleListAxes"]).tm)[2]
        axes = [s.chunk(s.refs(scale_list)[k]).first(0x2505).unpack("<7f")[3:] for k in (0, 1)]
        self.assertTrue(all(abs(q[3]) < 0.99 for q in axes))  # both turned
        self.assertLess(abs(sum(x * y for x, y in zip(*axes))), 0.99)  # and not alike: the order matters
        rot_list = s.refs(s.node(self.nodes["FixtureRotListMulti"]).tm)[1]
        for k in (0, 1):
            euler = s.refs(rot_list)[k]
            angles = [s.chunk(f).first(0x7127).first(0x2501).unpack("<f")[0]
                      for f in (s.refs(euler)[j] for j in range(3))]
            self.assertGreaterEqual(sum(abs(v) > 0.1 for v in angles), 2, angles)  # about several axes


RANGES = os.path.join(ROOT, "tests", "fixtures", "controllers_ranges.max")


@unittest.skipUnless(os.path.exists(RANGES), "no controllers_ranges fixture")
class TestRangesFixture(unittest.TestCase):
    """controllers_ranges.max holds what tools/fixtures/controllers_ranges.ms says (maxdrop-6n0.6.12): out-of-range
    types with frame 0 outside the range, ranges moved off the keys, lists with Average on, auto tangents."""

    # node -> its keyframe controllers in walk order, each (class, before, after, switched off, range in frames)
    TYPED = {
        "FixtureFloatTypes": [("Bezier Float", 2, 1, False, (10, 50)), ("Bezier Float", 4, 1, False, (10, 50)),
                              ("Bezier Float", 7, 1, False, (10, 50))],
        "FixtureFloatTypesMore": [("Bezier Float", 3, 3, False, (10, 50)), ("Bezier Float", 5, 1, False, (1, 40)),
                                  ("Bezier Float", 2, 1, True, (10, 50))],
        "FixtureFloatAfter": [("Bezier Float", 1, 2, False, (-50, -10)), ("Bezier Float", 1, 7, False, (-50, -10)),
                              ("Bezier Float", 1, 5, False, (-40, -1))],
        "FixtureFloatRanges": [("Bezier Float", 3, 3, False, (0, 60)), ("Bezier Float", 1, 1, False, (20, 40)),
                               ("Bezier Float", 2, 1, False, (20, 40))],
        "FixtureORTPosition": [("Bezier Position", 2, 1, False, (10, 50))],
        "FixtureORTRotation": [("TCB Rotation", 7, 1, False, (10, 50))],
        "FixtureORTLinearRotation": [("Linear Rotation", 5, 1, False, (1, 30))],
        "FixtureORTScale": [("Bezier Scale", 4, 1, False, (10, 50))],
        "FixtureORTLinearPosition": [("Linear Position", 1, 7, False, (-50, -10))],
        "FixtureORTTCBFloat": [("TCB Float", 1, 4, False, (-50, -10)), ("Linear Float", 2, 1, False, (10, 50))],
    }

    @classmethod
    def setUpClass(cls):
        cls.cf = cfb.CompoundFile(RANGES)
        cls.s = scene.Scene.from_file(cls.cf)
        cls.nodes = {cls.s.node(i).name: i for i in cls.s.walk()}

    @classmethod
    def tearDownClass(cls):
        cls.cf.close()

    def controllers(self, name, kinds):
        """[(class name, index)] below node name's transform controller whose class name is in kinds, in walk
        order (references in slot order)."""
        s, out, seen = self.s, [], set()

        def walk(i):
            entry = s.entry(i)
            if i is None or i in seen or entry is None or entry.superclass == classids.SC_BASENODE:
                return
            seen.add(i)
            if entry.name in kinds:
                out.append((entry.name, i))
            for k in sorted(s.refs(i)):
                walk(s.refs(i)[k])
        walk(s.node(self.nodes[name]).tm)
        return out

    def holder(self, i, chunk_id):
        """The chunk of controller i (or its 0x7127) that holds chunk_id; None when neither does."""
        chunk = self.s.chunk(i)
        return next((h for h in (chunk, chunk.first(0x7127)) if h is not None and h.container and
                     h.first(chunk_id) is not None), None)

    def test_types_and_ranges(self):
        for name, want in self.TYPED.items():
            with self.subTest(name):
                found = []
                for cls, i in self.controllers(name, KEYFRAMED):
                    _c, key_id, size, _count = KEYFRAMED[cls]
                    holder = self.holder(i, key_id)
                    if holder is None or holder.first(key_id).payload_size == 0:
                        continue  # the untouched floats of a Position XYZ or Euler XYZ
                    view = holder.first(key_id).view()
                    first, last = (struct.unpack_from("<i", view, k * size)[0] for k in (0, len(view) // size - 1))
                    self.assertFalse(first <= 0 <= last, "%s: frame 0 inside the keys" % name)
                    before, after, off = ct._Eval._ort([holder])
                    start, end = holder.first(0x3003).unpack("<ii")
                    found.append((cls, before, after, off, (start // 160, end // 160)))
                self.assertEqual(found, want)

    def test_lists_average_on(self):
        lists = ("Float List", "Position List", "Rotation List", "Scale List")
        for name, want in (("FixtureListAverages", ["Position List", "Rotation List", "Scale List"]),
                           ("FixtureFloatListAverage", ["Float List"])):
            with self.subTest(name):
                found = self.controllers(name, lists)
                self.assertEqual([c for c, _i in found], want)
                ev = ct._Eval(self.s, self.nodes[name], [])
                for _c, i in found:
                    _entries, average = ev._list(i)
                    self.assertTrue(average)

    def test_auto_tangents(self):
        found = self.controllers("FixtureLinearTangents", ("Bezier Float",))
        bits = []
        for _c, i in found[:3]:
            holder = self.holder(i, 0x2525)
            bits.append((sorted(ct._bits(holder, 0x2533, 9)), sorted(ct._bits(holder, 0x2534, 9))))
        self.assertEqual(bits, [([], []), ([1], [1]), ([1], [2])])  # custom, auto beside Linear, auto and custom
        _c, i = self.controllers("FixtureSmoothAuto", ("Bezier Float",))[1]
        holder = self.holder(i, 0x2525)
        self.assertEqual(sorted(ct._bits(holder, 0x2533, 9)), [0, 1, 2, 3])

    def test_no_issue(self):
        t = ct.Transforms(self.s)
        for i in self.s.walk():
            t.world(i)
        self.assertEqual(t.issues, [])


LOOKAT = os.path.join(ROOT, "tests", "fixtures", "lookat.max")


@unittest.skipUnless(os.path.exists(LOOKAT), "no lookat fixture")
class TestLookAtWeightFixture(unittest.TestCase):
    """lookat's two LookAt Constraints with an animated weight keep the slots 3ds Max 2020 gave them
    (GetControllerByID): the weight's controller is the block's reference slot 0, the targets and the up node after
    it. TestFixtures checks their matrices (FixtureWeightUp's, one target, only the slots: one weight cancels out);
    this checks a regenerated fixture still holds the controller there, and its keys."""

    # node: (weights as stored, the slots after the controller's by node name, up node or None, key values at 0, 50)
    WEIGHTED = {"FixtureWeightAnimated": ([50.0, "animated"], ["FixtureAim", "FixtureCam.Target"], None, [20.0, 90.0]),
                "FixtureWeightUp": (["animated"], ["FixtureAim"], "FixtureRig", [60.0, 10.0])}

    @classmethod
    def setUpClass(cls):
        cls.cf = cfb.CompoundFile(LOOKAT)
        cls.s = scene.Scene.from_file(cls.cf)
        cls.nodes = {cls.s.node(i).name: i for i in cls.s.walk()}

    @classmethod
    def tearDownClass(cls):
        cls.cf.close()

    def test_weight_controller_takes_slot_0(self):
        s = self.s
        for name, (weights, targets, up, values) in self.WEIGHTED.items():
            with self.subTest(name):
                c = s.refs(s.node(self.nodes[name]).tm)[1]
                self.assertEqual(s.entry(c).class_id, classids.LOOKAT_CONSTRAINT)
                block = s.refs(c)[0]
                refs = s.refs(block)
                ctrl = refs[0]
                self.assertEqual(s.entry(ctrl).class_id, classids.BEZIER_FLOAT)
                named = targets + ([up] if up else [])
                self.assertEqual({k: s.node(v).name for k, v in refs.items() if k}, dict(enumerate(named, 1)))
                pb = pblock.ParamBlock2.from_chunk(s.chunk(block), refs, s.refs(c), len(s),
                                                   (s.entry(c).superclass, s.entry(c).class_id))
                self.assertFalse(pb.issues)
                want = [pblock.Animated(ctrl) if w == "animated" else w for w in weights]
                self.assertEqual(pb.value(0), want)
                self.assertEqual(pb.value(1), [pblock.Reference(self.nodes[t]) for t in targets])
                if up:
                    self.assertEqual(pb.get(9), pblock.Reference(self.nodes[up]))
                holder = s.chunk(ctrl).first(0x7127)
                keys = holder.first(0x2525).view()  # Bezier Float key records, 28 bytes: time, flags, value
                records = [struct.unpack_from("<iIf", keys, k * 28) for k in range(len(keys) // 28)]
                self.assertEqual([r[0] for r in records], [0, 50 * 160])  # frames 0 and 50, in ticks
                for got, want in zip([r[2] for r in records], values):
                    self.assertAlmostEqual(got, want, places=4)


class ParameterValue(unittest.TestCase):
    """parameter_value: a material or map parameter's controller at frame 0 (maxdrop-em3.152). pblock_animated holds
    Bezier Float and Bezier Color controllers in a VRayBlendMtl, a VRayMtl and a VRayNormalMap; the oracle gives
    each one's frame-0 value."""

    PATH = os.path.join(ROOT, "tests", "fixtures", "pblock_animated.max")

    def test_fixture_controllers(self):
        materials = importlib.import_module(_PKG + ".reader.materials")
        with open(os.path.join(ROOT, "tests", "fixtures", "pblock_animated.oracle.json"), encoding="utf-8") as f:
            oracle = {m["name"]: m for m in json.load(f)["material_graph"]}
        with cfb.CompoundFile(self.PATH) as cf:
            s = scene.Scene.from_file(cf)
            g = materials.MaterialGraph(s)
            seen = 0
            for i in g.walk(s.node(n).material for n in s.walk()):
                m = g.get(i)
                for b in oracle[m.name]["blocks"]:
                    for c in b.get("controllers", ()):
                        with self.subTest(material=m.name, param=c["id"], tab=c["tab"]):
                            a = m.block(b["block_id"]).get(c["id"], c["tab"])
                            self.assertIsInstance(a, pblock.Animated)
                            value, issues = ct.parameter_value(s, a.index)
                            self.assertEqual(issues, [])
                            want = c["value"]
                            if isinstance(want, list):
                                self.assertIsInstance(value, tuple)
                                self.assertEqual(len(value), len(want))
                                for x, y in zip(value, want):
                                    self.assertAlmostEqual(x, y, delta=1e-5)
                            else:
                                self.assertIsInstance(value, float)
                                self.assertAlmostEqual(value, want, delta=1e-5)
                            seen += 1
            self.assertEqual(seen, 6)

    def test_bezier_color_keys(self):
        """A Bezier Color's keys (0x2526): 80 bytes each, time, flags, then the color: key 0 (frame 0) holds the saved
        value, key 1 the color at frame 50."""
        with cfb.CompoundFile(self.PATH) as cf:
            s = scene.Scene.from_file(cf)
            colors = [i for i in range(len(s)) if s.entry(i) is not None
                      and (s.entry(i).superclass, s.entry(i).class_id) == (classids.SC_CTRL_POINT3,
                                                                           classids.BEZIER_COLOR)]
            keyed = 0
            for i in colors:
                holder = s.chunk(i).first(0x7127)
                keys = holder.first(0x2526)
                if keys is None:
                    continue
                self.assertEqual(keys.payload_size, 2 * 80)
                view = keys.view()
                saved = holder.first(0x2501).unpack("<3f")
                self.assertEqual(struct.unpack_from("<i", view, 0)[0], 0)
                self.assertEqual(struct.unpack_from("<i", view, 80)[0], 50 * 160)
                self.assertEqual(struct.unpack_from("<3f", view, 8), saved)
                keyed += 1
            self.assertEqual(keyed, 2)  # the blend color and the diffuse

    @staticmethod
    def scene_of(b):
        return scene.Scene(node(0x2025, *b.objects), CLASSES)

    def test_float_list(self):
        """A Float List sums its entries times their weights; one entry of another class (an expression, a script)
        leaves no value: the parameter keeps its default rather than the sum of the rest."""
        b = Build()
        flist = b.add(node(C_FLOATLIST, refs34(b.flt(30.0), b.flt(7.0), None, None, list_block(b, 0.5, 1.0)),
                           leaf(0x1010, struct.pack("<i", 2))))
        odd = b.add(node(C_UNKNOWN_FLOAT, leaf(0x2501, struct.pack("<f", 9))))
        mixed = b.add(node(C_FLOATLIST, refs34(b.flt(2.0), odd, None, None, list_block(b, 1.0, 1.0)),
                           leaf(0x1010, struct.pack("<i", 2))))
        s = self.scene_of(b)
        self.assertEqual(ct.parameter_value(s, flist), (22.0, []))
        value, issues = ct.parameter_value(s, mixed)
        self.assertIsNone(value)
        self.assertEqual([x.reason for x in issues], [ct.UNKNOWN_CLASS])

    def test_float_list_without_a_value(self):
        """A Float List whose entries are of a known class but give no value gives none (maxdrop-6n0.6.17): the
        parameter keeps its default, where the list read 0 before."""
        b = Build()
        flist = b.add(node(C_FLOATLIST, refs34(b.flt(), None, None, None, list_block(b, 1.0)),
                           leaf(0x1010, struct.pack("<i", 1))))
        self.assertEqual(ct.parameter_value(self.scene_of(b), flist), (None, []))

    def test_bezier_color_from_keys(self):
        """Without a saved value whose interval holds frame 0: the keys (80 bytes each), the first one before it, the
        last one after it, linear between two with an issue (the curve not measured)."""
        before, after = (0.2, 0.4, 0.6), (0.6, 0.8, 1.0)
        for times, want, reasons in (((10, 20), before, []), ((-20, -10), after, []),
                                     ((-10, 10), (0.4, 0.6, 0.8), [ct.KEYS_INTERPOLATED])):
            with self.subTest(times=times):
                b = Build()
                keys = keys_of("Bezier Position", (times[0], before), (times[1], after))
                i = b.add(node(C_BCOLOR, node(0x7127, leaf(0x2501, struct.pack("<3f", 9, 9, 9)),
                                              leaf(0x2500, struct.pack("<ii", 5, 5)), keys)))
                value, issues = ct.parameter_value(self.scene_of(b), i)
                for x, y in zip(value, want):
                    self.assertAlmostEqual(x, y, places=6)
                self.assertEqual([x.reason for x in issues], reasons)

    def test_not_a_value(self):
        with cfb.CompoundFile(self.PATH) as cf:
            s = scene.Scene.from_file(cf)
            value, issues = ct.parameter_value(s, len(s))
            self.assertIsNone(value)
            self.assertEqual(len(issues), 1)
            self.assertTrue(issues[0].reason.startswith(ct.DAMAGED), issues)
            node = s.walk()[0]
            value, issues = ct.parameter_value(s, node)  # a node, not a controller
            self.assertIsNone(value)
            self.assertEqual([x.reason for x in issues], [ct.UNKNOWN_CLASS])


if __name__ == "__main__":
    unittest.main()
