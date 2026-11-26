# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/controllers/ on keys: keyframe controllers, their tangents and the
out-of-range types, no Blender.

    python -I -m unittest discover tests
"""
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
    AT_FRAME_30, Build, C_LINPOS, C_POSXYZ, ct, FOREVER, KEYFRAMED, keyframed, keys_of, leaf,
    MatrixCase, NEVER, node, refs34, TOLERANCE,
)


def _rotz(degrees):
    """A Max quaternion of a turn about Z."""
    h = math.radians(degrees) / 2
    return (0.0, 0.0, math.sin(h), math.cos(h))


# two values per keyframe value size: a key at an earlier and one at a later time
KEY_VALUES = {1: ((2.0,), (6.0,)), 3: ((1.0, 2.0, 3.0), (6.0, 7.0, 8.0)), 4: (_rotz(30), _rotz(90)),
              7: ((2.0, 3.0, 4.0, 0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0))}
STALE = {1: (99.0,), 3: (99.0, 99.0, 99.0), 4: _rotz(170), 7: (9.0, 9.0, 9.0, 0.0, 0.0, 0.0, 1.0)}


class TestKeyframe(MatrixCase):
    """Keyframe controllers: the saved value where its interval holds time 0, else the keys at time 0."""

    @staticmethod
    def expected(name, value):
        count = KEYFRAMED[name][3]
        if count == 1:
            return ct.translation((value[0], 0.0, 0.0))
        if count == 3:
            return ct.translation(value)
        if count == 4:
            return ct.quat_matrix(value)
        return ct.scale_matrix(value[:3], value[3:])

    @staticmethod
    def world(name, ticks_per_frame=160, **kw):
        """(world matrix, issues) of a node whose controller of keyframe class name is made with kw, in a scene of
        ticks_per_frame."""
        b = Build()
        obj = keyframed(b, name, **kw)
        count = KEYFRAMED[name][3]
        if count == 1:
            prs = b.prs(b.add(node(C_POSXYZ, refs34(obj))))
        else:
            prs = b.prs(*[obj if k == {3: 0, 4: 1, 7: 2}[count] else None for k in range(3)])
        n = b.node(prs)
        t = b.transforms(ticks_per_frame)
        return t.world(n), t.issues

    def test_every_class_reads_its_keys(self):
        for name, (_c, _cid, _size, count) in KEYFRAMED.items():
            first, last = KEY_VALUES[count]
            with self.subTest(name):
                got, issues = self.world(name, saved=STALE[count], interval=AT_FRAME_30,
                                         keys=keys_of(name, (0, first), (8000, last)))
                self.assertMatrix(got, self.expected(name, first))
                self.assertEqual(issues, [])
                got, issues = self.world(name, saved=STALE[count], interval=AT_FRAME_30,
                                         keys=keys_of(name, (-800, first), (-400, last)))
                self.assertMatrix(got, self.expected(name, last))  # after the last key: its value
                self.assertEqual(issues, [])
                got, issues = self.world(name, keys=keys_of(name, (160, first), (800, last)))
                self.assertMatrix(got, self.expected(name, first))  # before the first key: its value
                self.assertEqual(issues, [])

    def test_saved_value_whose_interval_holds_time_0(self):
        for interval in (FOREVER, (0, 0), (-160, 4800)):
            with self.subTest(interval=interval):
                got, issues = self.world("Linear Position", saved=(4, 5, 6), interval=interval,
                                         keys=keys_of("Linear Position", (0, (1, 2, 3)), (800, (6, 7, 8))))
                self.assertMatrix(got, ct.translation((4, 5, 6)))
                self.assertEqual(issues, [])

    def test_saved_value_that_holds_never_takes_the_keys(self):
        got, issues = self.world("Bezier Float", saved=(0.0,), interval=NEVER,
                                 keys=keys_of("Bezier Float", (16000, (5.0,))))
        self.assertMatrix(got, ct.translation((5, 0, 0)))
        self.assertEqual(issues, [])

    def test_between_keys(self):
        # records zero after the value: flat tangents, TCB's and a smooth Bezier key's (flags 0, whose handles are a
        # third long whatever length is stored) go 3u^2 - 2u^3 of the way; the rotations' zero control quaternions
        # are TestTangents' business
        for name, (_c, _cid, _size, count) in KEYFRAMED.items():
            first, last = KEY_VALUES[count]
            if count == 4 and not name.startswith("Linear"):
                continue
            with self.subTest(name):
                got, issues = self.world(name, saved=STALE[count], interval=AT_FRAME_30,
                                         keys=keys_of(name, (-1600, first), (6400, last)))  # 0 a fifth of the way
                f = 0.2 if name.startswith("Linear") else 0.104
                if count == 4:
                    want = ct.quat_matrix(_rotz(42))
                else:
                    want = self.expected(name, tuple(a + (b - a) * f for a, b in zip(first, last))[:3] +
                                         tuple(first[3:]))
                self.assertMatrix(got, want)
                self.assertEqual(issues, [])

    def test_key_chunk_of_another_class(self):
        tcb_keys = keys_of("TCB Position", (0, (1, 2, 3)))
        got, issues = self.world("Linear Position", saved=(4, 5, 6), interval=AT_FRAME_30, keys=tcb_keys)
        self.assertMatrix(got, ct.translation((4, 5, 6)))
        self.assertEqual([i.reason for i in issues], [ct.KEYS_UNKNOWN])
        got, issues = self.world("Linear Position", keys=tcb_keys)
        self.assertMatrix(got, ct.IDENTITY)
        self.assertEqual([i.reason for i in issues], [ct.KEYS_UNKNOWN])

    def test_damaged_keys_or_interval(self):
        got, issues = self.world("TCB Scale", saved=(2, 2, 2, 0, 0, 0, 1), interval=AT_FRAME_30,
                                 keys=leaf(0x2523, b"\0" * 113))
        self.assertMatrix(got, ct.scale_matrix((2, 2, 2)))  # a stale value beats keys of an unknown size
        self.assertEqual([i.reason for i in issues], [ct.KEYS_UNKNOWN])
        b = Build()
        obj = b.add(node(C_LINPOS, leaf(0x2503, struct.pack("<3f", 1, 2, 3)), leaf(0x2500, b"\0" * 4),
                         keys_of("Linear Position", (0, (1, 2, 3)))))
        n = b.node(b.prs(obj))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertTrue(t.issues[0].reason.startswith(ct.DAMAGED), t.issues)

    def test_slerp(self):
        self.assertMatrix(ct.quat_matrix(ct.slerp(_rotz(0), _rotz(180), 0.5)), ct.quat_matrix(_rotz(90)))
        flipped = tuple(-v for v in _rotz(90))  # the same rotation: the shorter arc still
        self.assertMatrix(ct.quat_matrix(ct.slerp(_rotz(30), flipped, 0.5)), ct.quat_matrix(_rotz(60)))
        self.assertMatrix(ct.quat_matrix(ct.slerp((0, 0, 0, 0), _rotz(90), 0.5)), ct.quat_matrix(_rotz(45)))
        self.assertMatrix(ct.quat_matrix(ct.slerp(_rotz(10), _rotz(10 + 1e-7), 0.3)), ct.quat_matrix(_rotz(10)))
        for bad in ((math.nan, 0, 0, 1), (0, 0, 0, math.inf)):
            self.assertFalse(ct._finite(ct.quat_matrix(ct.slerp(bad, _rotz(90), 0.5))))
        self.assertMatrix(ct.quat_matrix(ct.slerp((0, 0, 3, 3), _rotz(0), 0.5)), ct.quat_matrix(_rotz(45)))


def records(name, *keys):
    """The key chunk of keyframe class name from whole records: (time, flags, floats after the flags) per key."""
    _c, cid, size, _count = KEYFRAMED[name]
    out = b""
    for t, flags, floats in keys:
        rec = struct.pack("<iI%df" % len(floats), t, flags, *floats)
        assert len(rec) == size, (name, len(rec))
        out += rec
    return leaf(cid, out)


NO_TURN = (0.0, 0.0, 0.0, 1.0)
# key records of the probes (3ds Max 2020, frame 0 a fifth of the way between keys at frames -10 and 40, or a third
# between -20 and 10); the tests expect the transform 3ds Max gave at frame 0
BEZIER_CUSTOM = ((-1600, 0x1480, (-20, 50, 0.1, -1, 0.3333)), (6400, 0x680, (30, -0.05, -50, 0.3333, -1)))
BEZIER_LENGTHS = ((-1600, 0x1480, (-20, 50, 1 / 30, -1, 0.6)), (6400, 0x680, (30, -1 / 60, -50, 0.15, -1)))
TCB_TWO = ((-1600, 0, (-20, -0.6, 0.6, 1.4, 0, 0.4, 0, 80)), (6400, 0, (30, 0.4, -0.4, 0.2, 0.8, 0, 30, 0)))
BEZIER_POSITION = ((-1600, 0x1480, (1, 2, 3, 19, -12, 5, 0.02, -0.01, 1 / 150, -1, -1, -1, 0.5, 0.2, 0.4, 0, 0, 0)),
                   (6400, 0x680, (20, -10, 8, -1 / 150, 1 / 75, -1 / 60, -19, 12, -5, 0.1, 0.3, 0.6, -1, -1, -1,
                                  0, 0, 0)))
BEZIER_SCALE = ((-1600, 0x1480, (1, 1, 1) + NO_TURN + (1, -0.5, 0.5) + NO_TURN +
                 (0.05 / 3000, -0.02 / 3000, 0.01 / 3000) + NO_TURN + (-1, -1, -1) + NO_TURN +
                 (0.5, 0.2, 0.4) + NO_TURN),
                (6400, 0x680, (2, 0.5, 1.5) + NO_TURN + (-0.01 / 3000, 0.03 / 3000, -0.02 / 3000) + NO_TURN +
                 (-1, 0.5, -0.5) + NO_TURN + (0.1, 0.3, 0.6) + NO_TURN + (-1, -1, -1) + NO_TURN))
TCB_POSITION = ((-1600, 0, (1, 2, 3, 0.6, 0, 0, 0, 0.6, 0, 0, 0, 7.6, -4.8, 2)),
                (6400, 0, (20, -10, 8, 0, -0.8, 0, 0.2, 0, 19, -12, 5, 0, 0, 0)))
TCB_SCALE = ((-3200, 0, (1, 1, 1) + NO_TURN + (-0.6, 0.6, 0, 0, 0) + (0, 0, 0) + NO_TURN +
              (0.8, -0.288, 0.288) + NO_TURN),
             (1600, 0, (1.5, 0.8, 1.2) + NO_TURN + (0, 0, 0.2, 0.8, 0) + (0.5, -0.24, 0.24) + NO_TURN +
              (0.5, -0.24, 0.24) + NO_TURN),
             (6400, 0, (2, 0.5, 1.5) + NO_TURN + (0, 0, 0, 0, 0) + (0.5, -0.33, 0.33) + NO_TURN + (0, 0, 0) + NO_TURN))
# keys at frames -30, 10, 20, 50: segments of unequal length on either side of the second key
TCB_UNEVEN = ((-4800, 0, (-20, -0.6, 0.6, 1.4, 0, 0.4, 0, 45.1945)),
              (1600, 0, (5, 0.4, -0.4, 0.2, 0.8, 0, 18.5069, 4.96128)), (3200, 0, (12, 0, 0, 0, 0, 0, -0.5, -1.5)),
              (8000, 0, (3, 0, 0, 0, 0, 0, -12.75, 0)))
SMOOTH_UNEVEN = ((-4800, 0x480, (-0.217653, 0.122123, -0.508438, 0.824138) +
                  (-0.0887743, 0.152137, -0.801977, 0.570795) * 2 + NO_TURN * 2),
                 (1600, 0x480, (-0.350306, 0.00907553, 0.271078, 0.896504) +
                  (-0.471429, 0.120902, 0.589106, 0.645052) * 2 + NO_TURN * 2),
                 (3200, 0x480, (0.34758, -0.46743, -0.400732, 0.707185) +
                  (0.536339, -0.553661, -0.554141, 0.314209) * 2 + NO_TURN * 2),
                 (8000, 0x480, (-0.0416356, -0.0454372, -0.0416356, 0.99723) +
                  (-0.241957, 0.191339, 0.160492, 0.937597) * 2 + NO_TURN * 2))
_SR1, _SR2 = (-0.217653, 0.122123, -0.508438, 0.824138), (-0.350306, 0.00907553, 0.271078, 0.896504)
SMOOTH = ((-1600, 0x480, _SR1 + (-0.0887743, 0.152137, -0.801977, 0.570795) * 2 + NO_TURN + NO_TURN),
          (6400, 0x480, _SR2 + (-0.331813, -0.0549815, 0.626207, 0.70338) * 2 + NO_TURN + NO_TURN))
TCB_ROTATION = ((-3200, 0, _SR1 + (-0.6, 0.6, 1.4, 0, 0.4) + (-0.384283, 0.215616, -0.897684, 1.20423) +
                 (-0.290831, 0.0860713, -0.231307, 0.924395) + (-0.349584, 0.0127199, 0.249234, 0.903057)),
                (1600, 0, _SR2 + (0.4, -0.4, 0.2, 0.8, 0) + (-0.178697, -0.461555, 0.868927, 1.65051) +
                 (-0.38782, 0.0192559, 0.498383, 0.775138) + (-0.517174, 0.186085, 0.533234, 0.64309)),
                (6400, 0, (0.34758, -0.46743, -0.400732, 0.707185) + (0, 0, 0, 0, 0) +
                 (0.47586, -0.41374, -0.776129, 2.31995) + (0.34758, -0.46743, -0.400732, 0.707185) * 2))
# key records of the maxdrop-em3.144 probes (3ds Max 2020; key times moved so that the sample taken lies at 0) and
# 3ds Max's rows there
_Q1 = (0.2176535, -0.1221225, 0.508438, 0.8241383)  # eulerAngles 15 -25 60, as the probes store it
_POS_A, _POS_B = (-10, 30, 5), (5, 25, 12)
# free handles: lengths in frames of the scene's frame rate (0x100000 on both keys), steep tangents
FREE_STEEP = ((-1600, 0x101480, (-25, 10, 0.1, -1, 0.6)), (6400, 0x100680, (-15, -0.05, -10, 0.15, -1)))
FREE_25FPS = ((-1920, 0x101480, (-25, 10, 0.12, -1, 0.6)), (7680, 0x100680, (-15, -0.06, -10, 0.15, -1)))
FREE_POSITION = ((-1600, 0x101480, _POS_A + (15, -5, 7, 0.01, -0.005, 0.003333333, -1, -1, -1, 0.5, 0.2, 0.4, 0, 0, 0)),
                 (6400, 0x100680, _POS_B + (-0.003333333, 0.006666667, -0.008333334, -15, 5, -7, 0.1, 0.3, 0.6, -1, -1,
                                            -1, 0, 0, 0)))
# constant velocity (0x8000) out of the earlier key: handles of a third whatever the lengths or a free handle say
_CV_OUT = _POS_A + (15, -5, 7, 0.03, -0.02, 0.01333333)
_CV_IN = _POS_B + (-0.003333333, 0.02666667, -0.01666667, -15, 5, -7)
_CV_CACHE = (113.7363, 0.8749997, 91.86395)  # 3ds Max's last length lookup: not read
CONSTANT_VELOCITY = ((-1600, 0x9480, _CV_OUT + (-1,) * 6 + _CV_CACHE), (6400, 0x8680, _CV_IN + (-1,) * 6 + (0,) * 3))
CONSTANT_VELOCITY_LENGTHS = ((-1600, 0x9480, _CV_OUT + (-1, -1, -1, 0.3333, 0.3333, 0.3333) + _CV_CACHE),
                             (6400, 0x680, _CV_IN + (0.6, 0.1, 0.3, -1, -1, -1, 0, 0, 0)))
CONSTANT_VELOCITY_FREE = ((-1600, 0x109480, _CV_OUT + (-1, -1, -1, 8, 3, 5) + _CV_CACHE),
                          (6400, 0x680, _CV_IN + (0.3333, 0.3333, 0.3333, -1, -1, -1, 0, 0, 0)))
_CV_WANT = ct.translation((8.649943, 19.27765, 12.3126))
# scale axes that differ: the axis turns by slerp at the plain fraction of the time
_AXIS_A, _AXIS_B = (-0.1677313, -0.04494344, -0.254887, 0.9512512), (0.3094445, 0.02984081, 0.1391709, 0.9402048)
_AXIS_C = (0.3213206, 0.1919111, -0.02149021, 0.9270713)
_AXES_ROWS = ((1.739538, 0.4233863, 0.02604014), (0.4233864, 0.7781497, -0.1179727),
              (0.02604019, -0.1179726, 1.382313))
AXES_BEZIER = ((-1600, 0x480, (2, 0.5, 1) + _AXIS_A + (-0.5, 0.5, 2) + NO_TURN + (-6.25e-05, 6.25e-05, 0.00025) +
                NO_TURN + (-1, -1, -1) + NO_TURN + (-1, -1, -1) + NO_TURN),
               (6400, 0x480, (1.5, 1, 3) + _AXIS_B + (6.25e-05, -6.25e-05, -0.00025) + NO_TURN + (0.5, -0.5, -2) +
                NO_TURN + (-1, -1, -1) + NO_TURN + (-1, -1, -1) + NO_TURN))
AXES_TCB = ((-3200, 0, (2, 0.5, 1) + _AXIS_A + (-0.6, 0, 0, 0, 0) + (0, 0, 0) + NO_TURN +
             (-0.6080004, 0.9919998, 5.12) + NO_TURN),
            (1600, 0, (1.5, 1, 3) + _AXIS_B + (0, 0.6, 0, 0.6, 0) + (-0.7399999, 0.2600001, -0.4) + NO_TURN +
             (-0.5600001, 0.44, 1.4) + NO_TURN),
            (6400, 0, (0.7, 1.2, 2) + _AXIS_C + (0, 0, 0, 0, 0) + (-0.9199998, 0.08000018, -2.2) + NO_TURN + (0, 0, 0) +
             NO_TURN))
AXES_LINEAR = ((-1600, 0, (2, 0.5, 1) + _AXIS_A), (6400, 0, (1.5, 1, 3) + _AXIS_B))
# TCB Rotation turns of a revolution or more: squad over a half-turn at either end, the plain turn between
TURN_TCB = ((-1600, 0, _Q1 + (0, 0, 0, 0, 0) + (0.3842829, -0.2156161, 0.8976839, 1.204234) + _Q1 * 2),
            (6400, 0, tuple(-v for v in _Q1) + (0, 0, 0, 0, 0) + (-0.7071068, -0.7071068, 0, 6.2831855) +
             tuple(-v for v in _Q1) * 2))
_SPIN_KEY1 = _Q1 + (-0.6, 0, 0, 0, 0.4) + (0.3842829, -0.2156161, 0.8976839, 1.204234) + \
    (0.177091, -0.05708491, 0.5239475, 0.8311793, 0.2568741, -0.1864072, 0.4897937, 0.8120161)
_SPIN_KEY2 = (0.3418306, -0.331264, 0.4347805, 0.7644488, 0, -0.4, 0.2, 0.8, 0.2, 0, -1, 0, 0.5235988, 0.3042242,
              -0.312087, 0.564356, 0.7011075, 0.2673074, -0.2867367, 0.657185, 0.6437677)
_SPIN_KEY3 = (-0.4493841, 0.4115395, 0.3177683, -0.7264383, 0.4, 0.6, 1.4, 0.6, 0, -0.2672612, -0.5345225,
              -0.8017837, 7.853981, -0.3374873, 0.3064483, 0.7745848, -0.438418, -0.3780216, 0.2699545, 0.8783795,
              -0.1125782)
_SPIN_KEY4 = (-0.1738264, 0.2780375, 0.4393593, -0.8363271, 0, 0, 0, 0, 0, -1, 0, 0, 0.6981317, -0.1738264,
              0.2780375, 0.4393593, -0.8363271, -0.1738264, 0.2780375, 0.4393593, -0.8363271)
# 450 degrees between keys at frames -5 and 25, frame 0 a sixth of the way: the first half-turn
SPIN_START = ((-4000, 0, _SPIN_KEY1), (-800, 0, _SPIN_KEY2), (4000, 0, _SPIN_KEY3), (8800, 0, _SPIN_KEY4))
_FIRST = _Q1 + (0, 0, 0, 0, 0) + (0.3842829, -0.2156161, 0.8976839, 1.204234) + _Q1 * 2
_SPUN = (-0.2556345, 0.2522139, -0.2008212, -0.911433, 0, 0, 0, 0, 0, -0.2672612, -0.5345225, -0.8017837, 6.981317)
# 400 degrees into a key with a control, frame 0 two thirds of the way: the last half-turn
SPIN_END = ((-3200, 0, _FIRST), (1600, 0, _SPUN + (-0.2405288, 0.2500319, 0.1379594, -0.9276838) * 2),
            (6400, 0, (-0.3217966, 0.6741401, -0.04609904, -0.6632172, 0, 0, 0, 0, 0, 0, -1, 0, 1.047198) +
             (-0.3217966, 0.6741401, -0.04609904, -0.6632172) * 2))
# 760 degrees after a turn of 400, frame 0 half way: the plain turn
_SPUN2 = (-0.3264801, 0.1495713, 0.1230183, -0.9251517)
SPIN_MIDDLE = ((-7200, 0, _FIRST), (-2400, 0, _SPUN + (-0.1754667, 0.4744749, -0.1856225, -0.842395) * 2),
               (2400, 0, _SPUN2 + (0, 0, 0, 0, 0, 0, 0, -1, 13.2645) + _SPUN2 * 2))
# 359 degrees after a turn of 60, frame 0 half way: neither squad nor the spin fits 3ds Max
NEAR_TCB = ((-7200, 0, _FIRST),
            (-2400, 0, (0.4427125, -0.5178303, 0.3314935, 0.6526634, 0, 0, 0, 0, 0, 0, -1, 0, 1.047198) +
             (0.4830321, -0.5986848, 0.2688695, 0.5796254) * 2),
            (2400, 0, (-0.4390483, 0.5170906, -0.3393202, -0.6517021, 0, 0, 0, 0, 0, -0.2672612, -0.5345225,
                       -0.8017837, 6.265732) + (-0.4390483, 0.5170906, -0.3393202, -0.6517021) * 2))
# a whole turn between Linear Rotation keys: about the earlier key's local Z, whichever axis it was made about
OPPOSITE_LINEAR = ((-1600, 0, _Q1), (6400, 0, tuple(-v for v in _Q1)))


def auto_bits(cid, count, *indices):
    """0x2533 (auto in tangents) or 0x2534 (auto out tangents): a 0x2700 bit array of count keys, indices set."""
    data = bytearray((count + 7) // 8)
    for k in indices:
        data[k >> 3] |= 1 << (k & 7)
    return node(cid, leaf(0x2700, struct.pack("<i", count) + bytes(data)))


def ort(before=None, after=None, off=None):
    """0x8499: the out-of-range types before (0x3000) and after (0x3001), 0x3003 1 when switched off."""
    return node(0x8499, *(leaf(cid, struct.pack("<i", v)) for cid, v in ((0x3000, before), (0x3001, after),
                                                                           (0x3003, off)) if v is not None))


def time_range(start, end):
    return leaf(0x3003, struct.pack("<ii", start, end))


# probes of 3ds Max 2020 (maxdrop-6n0.6.12): Bezier Float keys at frames -20, 10, 40 (, 55) and 3ds Max's value at
# frame 0. A Linear tangent beside a custom key, whose stored tangent is stale (0.00520833, 0.003125)
LINEAR_BESIDE_CUSTOM = ((-3200, 0x480, (-25, 0, 0.00520833302, -1, 0.333000004)),
                        (1600, 0x1680, (-10, 0.0666666701, 0.0666666701, 0.400000006, 0.899999976)),
                        (6400, 0x480, (-15, 0.00312499981, -10, 0.333299994, -1)))
# the same beside an auto key (its auto bits set), and four auto keys: lengths of 0.3333 drawn as a third
LINEAR_BESIDE_AUTO = ((-3200, 0x480, (-25, 0, 0.00520833302, -1, 0.333000004)),
                      (1600, 0x1680, (-10, -0.0, 0, 0.333299994, 0.333299994)),
                      (6400, 0x480, (-15, 0.00312499981, -10, 0.333299994, -1)))
AUTO_KEYS = ((-3200, 0x1680, (-25, 0, 0, -1, 0.333299994)),
             (1600, 0x1680, (-10, -0.00312500005, 0.00312500005, 0.333299994, 0.333299994)),
             (6400, 0x1680, (5, -0.00555555569, 0.00555555569, 0.333299994, 0.333299994)),
             (8800, 0x1680, (30, 0, 0, 0.333299994, -1)))
SMOOTH_KEYS = ((-3200, 0x0, (-25, 0, 0.00520833302, -1, 0.333000004)),
               (1600, 0x0, (-10, -0.0010416666, 0.0010416666, 0.333299994, 0.333000004)),
               (6400, 0x0, (-15, -0.012152778, 0.012152778, 0.333299994, 0.333000004)),
               (8800, 0x0, (30, -0.0253472216, 0, 0.333299994, -1)))
# key 2's in tangent auto and its out tangent custom, key 3's in custom and its out auto
AUTO_IN_CUSTOM_OUT = ((-3200, 0x480, (-25, 0, 0.00312499981, -1, 0.333000004)),
                      (1600, 0x1680, (-10, -0.0333333351, 0.0333333351, 0.333299994, 0.333000004)),
                      (6400, 0x1680, (5, 0.0166666675, -0.0166666675, 0.333299994, 0.333299994)),
                      (8800, 0x480, (30, -0.0128472215, -55, 0.333299994, -1)))
LINEAR_BESIDE_AUTO_POSITION = (
    (-3200, 0x480, (-25, 3, 7, 0, 0, 0, 0.00520833302, 0.00687499996, -0.00489583332, -1, -1, -1, 0.333299994,
                    0.333299994, 0.333299994, 0, 0, 0)),
    (1600, 0x1680, (-10, 20, -4, 0, 0, 0, 0, 0, 0) + (0.333299994,) * 6 + (0, 0, 0)),
    (6400, 0x480, (-15, 5, 10, 0.00312499981, 0.00645833323, -0.00552083366, -10, -2, -3, 0.333299994, 0.333299994,
                   0.333299994, -1, -1, -1, 0, 0, 0)))


class TestTangents(MatrixCase):
    """Between two Bezier, TCB or Smooth Rotation keys: the curve of their stored tangents, as 3ds Max samples it."""

    @staticmethod
    def world(name, keys, ticks_per_frame=160):
        return TestKeyframe.world(name, ticks_per_frame, saved=STALE[KEYFRAMED[name][3]], interval=AT_FRAME_30,
                                  keys=records(name, *keys))

    def assertNear(self, got, rows):
        """got's rotation and translation rows within the oracle's tolerance of rows (up to 4 x 3)."""
        for r, want in enumerate(rows):
            for c, w in enumerate(want[:3]):
                self.assertLessEqual(abs(got[r][c] - w), TOLERANCE, "row %d col %d: %r" % (r, c, got))

    def test_curves_equal_3ds_max(self):
        cases = [
            ("Bezier Float", BEZIER_CUSTOM, ct.translation((74.7929, 0, 0))),
            ("Bezier Float", BEZIER_LENGTHS, ct.translation((25.5877, 0, 0))),
            ("Bezier Position", BEZIER_POSITION, ct.translation((26.2614, -2.11258, 4.032))),
            ("Bezier Scale", BEZIER_SCALE, ct.scale_matrix((1.07181, 0.919857, 1.05302))),
            ("TCB Float", TCB_TWO, ct.translation((-10.9587, 0, 0))),
            ("TCB Position", TCB_POSITION, ct.translation((1.49064, 1.69012, 3.12912))),
            ("TCB Scale", TCB_SCALE, ct.scale_matrix((1.44568, 0.825726, 1.17427))),
            ("Smooth Rotation", SMOOTH, ((0.596507, 0.693709, 0.403668), (-0.802477, 0.506398, 0.315583),
                                         (0.0145058, -0.512181, 0.858755), (0, 0, 0))),
            ("TCB Rotation", TCB_ROTATION, ((0.891253, -0.438291, -0.116489), (0.398801, 0.635144, 0.661476),
                                            (-0.215931, -0.635998, 0.740864), (0, 0, 0))),
            ("TCB Float", TCB_UNEVEN, ct.translation((3.31704, 0, 0))),
            ("Smooth Rotation", SMOOTH_UNEVEN, ((0.946646, -0.316752, 0.0594076), (0.172725, 0.654293, 0.736252),
                                                (-0.27208, -0.686709, 0.674095), (0, 0, 0))),
        ]
        for name, keys, want in cases:
            with self.subTest(name, keys=keys[0][2][:2]):
                got, issues = self.world(name, keys)
                self.assertNear(got, want)
                self.assertEqual(issues, [])

    def test_tangent_types_equal_3ds_max(self):
        # a stored length counts only for a custom tangent; a Linear one facing a custom or auto one is the chord's
        cases = [
            ("linear beside custom", "Bezier Float", LINEAR_BESIDE_CUSTOM, b"", (44.1966133, 0, 0)),
            ("linear beside auto", "Bezier Float", LINEAR_BESIDE_AUTO,
             auto_bits(0x2533, 3, 1) + auto_bits(0x2534, 3, 1), (-12.7777777, 0, 0)),
            ("auto", "Bezier Float", AUTO_KEYS, auto_bits(0x2533, 4, 0, 1, 2, 3) + auto_bits(0x2534, 4, 0, 1, 2, 3),
             (-16.1111107, 0, 0)),
            ("smooth", "Bezier Float", SMOOTH_KEYS, b"", (-12.7777777, 0, 0)),
            ("auto in, custom out", "Bezier Float", AUTO_IN_CUSTOM_OUT,
             auto_bits(0x2533, 4, 1) + auto_bits(0x2534, 4, 2), (-36.4814835, 0, 0)),
            ("position", "Bezier Position", LINEAR_BESIDE_AUTO_POSITION,
             auto_bits(0x2533, 3, 1) + auto_bits(0x2534, 3, 1), (-12.7777777, 16.8518524, -1.96296322)),
        ]
        for label, name, keys, bits, want in cases:
            with self.subTest(label):
                got, issues = TestKeyframe.world(name, keys=records(name, *keys) + bits)
                self.assertNear(got, ct.translation(want))
                self.assertEqual(issues, [])
        # the later key's Linear in tangent facing a custom out tangent: frame 20 of the first case
        shifted = tuple((t - 3200, flags, floats) for t, flags, floats in LINEAR_BESIDE_CUSTOM)
        got, issues = TestKeyframe.world("Bezier Float", keys=records("Bezier Float", *shifted))
        self.assertNear(got, ct.translation((83.2255325, 0, 0)))
        self.assertEqual(issues, [])
        # without its bits an auto tangent reads as custom: its stored length, a curve 3ds Max does not draw
        got, _issues = TestKeyframe.world("Bezier Float", keys=records("Bezier Float", *AUTO_IN_CUSTOM_OUT))
        self.assertGreater(abs(got[3][0] - -36.4814835), 1e-3)

    def test_damaged_auto_bits_are_none(self):
        for bits in (node(0x2533, leaf(0x2700, b"\1")), node(0x2533), leaf(0x2533, b"\0" * 9),
                     node(0x2533, leaf(0x2700, struct.pack("<i", 2 ** 31 - 1) + b"\xff"))):
            with self.subTest(bits=bits):
                got, issues = TestKeyframe.world("Bezier Float", keys=records("Bezier Float", *SMOOTH_KEYS) + bits)
                self.assertNear(got, ct.translation((-12.7777777, 0, 0)))
                self.assertEqual(issues, [])

    def test_linear_rotation_keeps_the_long_way(self):
        # 270 degrees about Z from frame -10 to 40: 3ds Max is 54 degrees on at frame 0, not -18
        got, issues = self.world("Linear Rotation", ((-1600, 0, NO_TURN), (6400, 0, (0, 0, -0.7071068, -0.7071068))))
        self.assertNear(got, ((0.587785, 0.809017, 0), (-0.809017, 0.587785, 0), (0, 0, 1)))
        self.assertEqual(issues, [])

    def test_step(self):
        # a step out of the earlier key or into the later holds the earlier key's value
        for flags in ((0x880, 0x480), (0x480, 0x500)):
            with self.subTest(flags=flags):
                keys = ((-1600, flags[0], (-20, 50, 0, -1, -1)), (6400, flags[1], (30, 0, -50, -1, -1)))
                got, issues = self.world("Bezier Float", keys)
                self.assertNear(got, ct.translation((-20, 0, 0)))
                self.assertEqual(issues, [])

    def test_constant_velocity_on_a_float_changes_nothing(self):
        # three smooth keys at frames -20, 10, 40 (-20, 15, 5), with and without constant velocity: 8.33333 at 0
        for flags in (0, 0x8000):
            keys = ((-3200, flags, (-20, 0, 0.0119792, -1, -1)), (1600, flags, (15, -0.00260417, 0.00260417, -1, -1)),
                    (6400, flags, (5, 0.00677083, 0, -1, -1)))
            got, issues = self.world("Bezier Float", keys)
            self.assertNear(got, ct.translation((8.33333, 0, 0)))
            self.assertEqual(issues, [])

    def test_free_handles_spins_and_axes_equal_3ds_max(self):
        cases = [
            ("Bezier Float", FREE_STEEP, 160, ct.translation((-19.08361, 0, 0))),
            ("Bezier Float", FREE_25FPS, 192, ct.translation((-17.35247, 0, 0))),
            ("Bezier Position", FREE_POSITION, 160, ct.translation((-6.720174, 28.98971, 6.343373))),
            ("Bezier Position", CONSTANT_VELOCITY, 160, _CV_WANT),
            ("Bezier Position", CONSTANT_VELOCITY_LENGTHS, 160, _CV_WANT),
            ("Bezier Position", CONSTANT_VELOCITY_FREE, 160, _CV_WANT),
            # constant velocity on the later key alone, or on a Bezier Scale: the plain curve (probes)
            ("Bezier Position", (BEZIER_POSITION[0], (6400, 0x8680, BEZIER_POSITION[1][2])), 160,
             ct.translation((26.2614, -2.11258, 4.032))),
            ("Bezier Scale", ((-1600, 0x9480, BEZIER_SCALE[0][2]), (6400, 0x8680, BEZIER_SCALE[1][2])), 160,
             ct.scale_matrix((1.07181, 0.919857, 1.05302))),
            ("Bezier Scale", AXES_BEZIER, 160, _AXES_ROWS),
            ("TCB Scale", AXES_TCB, 160, ((1.588367, -0.01132296, -0.007636474), (-0.01132295, 1.157975, 0.5991784),
                                          (-0.007636414, 0.5991784, 2.829143))),
            ("Linear Scale", AXES_LINEAR, 160, _AXES_ROWS),
            ("TCB Rotation", TURN_TCB, 160, ((0.002162099, -0.4402154, -0.8978895), (0.3230723, 0.8500489, -0.4159822),
                                             (0.9463718, -0.2891839, 0.1440593))),
            ("TCB Rotation", SPIN_START, 160, ((0.6442479, -0.4869778, -0.5897434), (-0.2280298, 0.6137177, -0.755879),
                                               (0.7300323, 0.6214526, 0.2843409))),
            ("TCB Rotation", SPIN_END, 160, ((-0.8056253, -0.5518919, 0.2153679), (0.5903108, -0.7171367, 0.3704703),
                                             (-0.05001131, 0.4255942, 0.9035311))),
            ("TCB Rotation", SPIN_MIDDLE, 160, ((0.913654, -0.1942455, -0.3570784),
                                                (-0.04691131, 0.8221828, -0.5672872),
                                                (0.4037767, 0.5350553, 0.7420783))),
            ("Linear Rotation", OPPOSITE_LINEAR, 160, ((0.9876206, 0.1555768, 0.02003492),
                                                       (-0.126691, 0.866442, -0.4829366),
                                                       (-0.09249283, 0.4744199, 0.8754261))),
        ]
        for name, keys, ticks, want in cases:
            with self.subTest(name, keys=keys[0][2][:2], ticks=ticks):
                got, issues = self.world(name, keys, ticks)
                self.assertNear(got, want)
                self.assertEqual(issues, [])

    def test_free_handle_length_is_in_frames(self):
        # the 25 fps probe read at 30 fps: handles 160 / 192 as long, and 3ds Max's value is missed
        got, issues = self.world("Bezier Float", FREE_25FPS, 160)
        self.assertGreater(abs(got[3][0] - -17.35247), 0.5)
        self.assertEqual(issues, [])

    def test_spin_pieces(self):
        # a turn of 2 pi from the identity about Z, keys without controls: the plain turn in every piece
        a = NO_TURN + (0, 0, 0, 0, 0) + (0, 0, 1, 0) + NO_TURN * 2
        b = tuple(-v for v in NO_TURN) + (0, 0, 0, 0, 0) + (0, 0, 1, 2 * math.pi) + tuple(-v for v in NO_TURN) * 2
        for frame in (5, 20, 35):  # the first half-turn, the middle, the last half-turn of 40 frames
            with self.subTest(frame=frame):
                got, issues = self.world("TCB Rotation", ((-160 * frame, 0, a), (160 * (40 - frame), 0, b)))
                self.assertMatrix(got, ct.quat_matrix(_rotz(9 * frame)), places=5)
                self.assertEqual(issues, [])

    def test_unknown_curves_stay_linear_with_an_issue(self):
        # a free handle of a negative length (3ds Max converts a third into frames when the handle is freed)
        free = ((-1600, 0x101480, (-20, 50, 0.1, -1, -1)), (6400, 0x100680, (30, -0.05, -50, -1, -1)))
        # scale axes whose stored quaternions point apart (the same turn, the other sign)
        turned = (TCB_SCALE[0], (1600, 0, (1.5, 0.8, 1.2) + (0, 0, 0.5, -0.8660254) + TCB_SCALE[1][2][7:]))
        linear_scale = ((-1600, 0, (2, 0.5, 1) + _AXIS_A), (6400, 0, (1.5, 1, 3) + tuple(-v for v in _AXIS_B)))
        no_axis = (TURN_TCB[0], (6400, 0, TURN_TCB[1][2][:9] + (0, 0, 0, 7.0) + TURN_TCB[1][2][13:]))
        # 359 degrees from the identity between Linear Rotation keys: 3ds Max's branch is not known
        near = ((-1600, 0, NO_TURN), (6400, 0, (0, 0, math.sin(math.radians(179.5)), math.cos(math.radians(179.5)))))
        # a whole revolution between Smooth Rotation keys: opposite quaternions, the earlier rotation kept
        q, opposite = _rotz(30), tuple(-v for v in _rotz(30))
        smooth = ((-1600, 0x480, q * 3 + NO_TURN * 2), (6400, 0x480, opposite * 3 + NO_TURN * 2))
        cases = [("Bezier Float", free, ct.translation((-10, 0, 0))), ("TCB Scale", turned, None),
                 ("Linear Scale", linear_scale, None), ("TCB Rotation", NEAR_TCB, None),
                 ("TCB Rotation", no_axis, None), ("Linear Rotation", near, None),
                 ("Smooth Rotation", smooth, ct.quat_matrix(q))]
        for name, keys, want in cases:
            with self.subTest(name, keys=keys[1][2][:4]):
                got, issues = self.world(name, keys)
                if want is not None:
                    self.assertMatrix(got, want, places=5)
                self.assertTrue(ct._finite(got))
                self.assertEqual([i.reason for i in issues], [ct.KEYS_INTERPOLATED])

    def test_damaged_floats_are_non_finite(self):
        nan, inf = math.nan, math.inf
        cases = [("Bezier Float", ((-1600, 0x1480, (-20, 50, nan, -1, 0.3333)), BEZIER_CUSTOM[1])),
                 ("Bezier Float", ((-1600, 0x1480, (-20, 50, 0.1, -1, inf)), BEZIER_CUSTOM[1])),
                 ("TCB Float", ((-1600, 0, (-20, -0.6, 0.6, 1.4, 0, inf, 0, 80)), TCB_TWO[1])),
                 ("TCB Float", ((-1600, 0, (-20, -0.6, 0.6, 1.4, 0, 0.4, 0, nan)), TCB_TWO[1])),
                 ("TCB Rotation", ((-3200, 0, TCB_ROTATION[0][2][:8] + (inf,) + TCB_ROTATION[0][2][9:]),
                                   TCB_ROTATION[1])),
                 ("Smooth Rotation", ((-1600, 0x480, _SR1 + (nan, 0, 0, 1) * 2 + NO_TURN + NO_TURN), SMOOTH[1])),
                 ("TCB Rotation", (TCB_ROTATION[0], (1600, 0, TCB_ROTATION[1][2][:12] + (nan,) +
                                                     TCB_ROTATION[1][2][13:]))),
                 ("TCB Rotation", (TURN_TCB[0], (6400, 0, TURN_TCB[1][2][:9] + (0, inf, 0, 7.0) +
                                                 TURN_TCB[1][2][13:]))),
                 ("Bezier Float", ((-1600, 0x101480, (-25, 10, 0.1, -1, inf)), FREE_STEEP[1])),
                 ("Bezier Position", ((-1600, 0x9480, _POS_A + (15, -5, 7, nan, -0.02, 0.01333333) + (-1,) * 6 +
                                       _CV_CACHE), CONSTANT_VELOCITY[1]))]
        for name, keys in cases:
            with self.subTest(name, keys=keys[0][2]):
                got, issues = self.world(name, keys)
                self.assertEqual(got, ct.IDENTITY)
                self.assertEqual([i.reason for i in issues], [ct.NON_FINITE])

    def test_damaged_ease_never_raises(self):
        # eases far out of range give some fraction, finite or not, but never an exception from math
        for ease_from, ease_to in ((3e38, 0.0), (-3e38, 0.0), (0.0, -3e38), (3e38, 3e38), (-1.0, -1.0),
                                   (3e38, -3e38), (1e30, 1.0)):
            with self.subTest(ease_from=ease_from, ease_to=ease_to):
                a = TCB_ROTATION[0][2][:7] + (0.0, ease_from) + TCB_ROTATION[0][2][9:]
                b = TCB_ROTATION[1][2][:7] + (ease_to, 0.0) + TCB_ROTATION[1][2][9:]
                got, issues = self.world("TCB Rotation", ((-3200, 0, a), (1600, 0, b), TCB_ROTATION[2]))
                self.assertTrue(ct._finite(got) or [i.reason for i in issues] == [ct.NON_FINITE], (got, issues))

    def test_ease_and_hermite(self):
        self.assertAlmostEqual(ct.ease(0.2, 0.4, 0.8), 0.12)  # the sum past 1: a third and two thirds
        self.assertAlmostEqual(ct.ease(0.5, 0.0, 0.0), 0.5)
        self.assertAlmostEqual(ct.ease(0.5, 0.25, 0.25), 0.5)
        self.assertAlmostEqual(ct.hermite(-20, 30, 80, 30, 0.12), -10.95872)
        self.assertAlmostEqual(ct.hermite(1, 2, 0, 0, 0.5), 1.5)

    def test_bezier_time_curve(self):
        # handles a third of the segment: the time curve is straight, the value the plain cubic at the fraction
        self.assertAlmostEqual(ct.bezier(0, 0.0, 0.0, -1, 300, 3.0, 0.0, -1, 150), 1.5)
        self.assertAlmostEqual(ct.bezier(0, 0.0, 0.01, 1 / 3, 300, 3.0, -0.01, 1 / 3, 100), 1.0)  # a straight line
        self.assertTrue(math.isnan(ct.bezier(0, 0.0, math.nan, -1, 300, 3.0, 0.0, -1, 150)))

    def test_bezier_negative_length_is_a_third(self):
        # tangents that make the handle length matter: any negative length, not only -1, is the default third
        third = ct.bezier(0, 0.0, 0.02, 1 / 3, 300, 3.0, -0.005, 1 / 3, 100)
        self.assertNotAlmostEqual(ct.bezier(0, 0.0, 0.02, 0.5, 300, 3.0, -0.005, 0.5, 100), third)
        for length in (-1.0, -2.5, -1e30):
            with self.subTest(length=length):
                self.assertAlmostEqual(ct.bezier(0, 0.0, 0.02, length, 300, 3.0, -0.005, 1 / 3, 100), third)
                self.assertAlmostEqual(ct.bezier(0, 0.0, 0.02, 1 / 3, 300, 3.0, -0.005, length, 100), third)

    def test_squad_keeps_the_stored_signs(self):
        q0, q1 = NO_TURN, (0.0, 0.0, -0.7071068, -0.7071068)  # 270 degrees about Z, stored the long way
        self.assertMatrix(ct.quat_matrix(ct.squad(q0, q0, q1, q1, 0.5)), ct.quat_matrix(_rotz(-135)), places=5)
        self.assertMatrix(ct.quat_matrix(ct.squad(q0, q0, q1, q1, 0.0)), ct.IDENTITY)
        self.assertFalse(ct._finite(ct.quat_matrix(ct.squad(q0, (math.nan, 0, 0, 1), q1, q1, 0.5))))


# Linear Float keys at frames 10, 30, 50 (0, 20, 5) and at -50, -30, -10: 3ds Max 2020's value at frame 0 for each
# out-of-range type (probe of maxdrop-em3.144: 12.5, 12.5, 10, -10, 7.5 before the keys)
LATER_KEYS = ((1600, (0.0,)), (4800, (20.0,)), (8000, (5.0,)))
EARLIER_KEYS = ((-8000, (0.0,)), (-4800, (20.0,)), (-1600, (5.0,)))
BEFORE = {1: 0.0, 2: 12.5, 3: 12.5, 4: 10.0, 5: -10.0, 7: 7.5}
AFTER = {1: 5.0, 2: 10.0, 3: 10.0, 4: 12.5, 5: -2.5, 7: 15.0}


class TestOutOfRange(MatrixCase):
    """Out-of-range types and the range they apply outside (0x8499 and 0x3003 beside the keys)."""

    def value(self, keys, *extra, name="Linear Float"):
        got, issues = TestKeyframe.world(name, keys=keys_of(name, *keys) + b"".join(extra))
        return got, [i.reason for i in issues]

    def test_every_type_before_and_after_the_keys(self):
        for code, want in BEFORE.items():
            with self.subTest("before", code=code):
                got, issues = self.value(LATER_KEYS, ort(before=code, after=2))
                self.assertMatrix(got, ct.translation((want, 0, 0)))
                self.assertEqual(issues, [])
        for code, want in AFTER.items():
            with self.subTest("after", code=code):
                got, issues = self.value(EARLIER_KEYS, ort(before=4, after=code))
                self.assertMatrix(got, ct.translation((want, 0, 0)))
                self.assertEqual(issues, [])
        got, issues = self.value(LATER_KEYS)  # no 0x8499: constant
        self.assertMatrix(got, ct.translation((0, 0, 0)))
        self.assertEqual(issues, [])

    def test_unknown_type(self):
        # MAXScript's #identity is stored as 0 and reads zero everywhere in 3ds Max; 6 was never seen
        for code in (0, 6, 99, -1):
            with self.subTest(code=code):
                got, issues = self.value(LATER_KEYS, ort(before=code, after=code))
                self.assertMatrix(got, ct.translation((0, 0, 0)))
                self.assertEqual(issues, [ct.ORT_UNKNOWN])
                # inside the keys too: the whole curve changes, not only past the range
                got, issues = self.value(((-1600, (5.0,)), (1600, (5.0,))), ort(before=2, after=code))
                self.assertMatrix(got, ct.translation((5, 0, 0)))
                self.assertEqual(issues, [ct.ORT_UNKNOWN])

    def test_whole_periods_and_bezier_in_the_wrap(self):
        b = Build()  # Bezier Float keys with chord tangents (a straight line), the types inside 0x7127
        keys = records("Bezier Float", (1600, 0x480, (0, 0, 0.00625, -1, -1)),
                       (4800, 0x480, (20, -0.00625, -0.0046875, -1, -1)), (8000, 0x480, (5, 0.0046875, 0, -1, -1)))
        n = b.node(b.prs(b.add(node(C_POSXYZ, refs34(b.flt(keys=keys + ort(2, 2)))))))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((12.5, 0, 0)))
        self.assertEqual(t.issues, [])
        # a time a whole period before the first key lands on the last key, after the last on the first
        got, _issues = self.value(((9600, (0.0,)), (14400, (20.0,)), (19200, (5.0,))), ort(before=2))
        self.assertMatrix(got, ct.translation((5, 0, 0)))
        got, _issues = self.value(((-9600, (0.0,)), (-4800, (20.0,)), (0, (5.0,))), ort(after=2))
        self.assertMatrix(got, ct.translation((5, 0, 0)))  # frame 0 is the last key
        # half a range after the keys: the middle key's 20 plus the change over the range, 5
        got, _issues = self.value(((-9600 * 3, (0.0,)), (-9600 * 2, (20.0,)), (-9600, (5.0,))), ort(after=7))
        self.assertMatrix(got, ct.translation((25, 0, 0)))

    def test_range(self):
        # inside the range the keys (the nearest key's value outside them), outside it the type over the range
        cases = [
            ("constant, range inside the keys", (ort(), time_range(3200, 6400)), 10.0, []),
            ("cycle, range past the keys", (ort(2, 2), time_range(0, 9600)), 0.0, []),
            ("cycle, range inside the keys", (ort(2, 2), time_range(3200, 6400)), 12.5, []),  # lands on its end
            ("loop, range past the keys", (ort(3, 3), time_range(0, 9600)), 2.5, []),
            ("loop before only", (ort(3, 1), time_range(0, 9600)), 0.0, [ct.ORT_APPROXIMATED]),
            ("switched off", (ort(2, 2, 1),), 0.0, []),
            ("switched off, range moved", (ort(2, 2, 1), time_range(3200, 6400)), 10.0, [ct.ORT_APPROXIMATED]),
            ("range reversed", (ort(2, 2), time_range(6400, 3200)), 12.5, []),
            ("no range", (ort(2, 2), time_range(-2 ** 31, -2 ** 31)), 12.5, []),
            ("loop, range moved past the last key", (ort(3, 3), time_range(4800, 9600)), 5.0, [ct.ORT_APPROXIMATED]),
        ]
        for label, extra, want, reasons in cases:
            with self.subTest(label):
                got, issues = self.value(LATER_KEYS, *extra)
                self.assertMatrix(got, ct.translation((want, 0, 0)))
                self.assertEqual(issues, reasons)

    def test_loop_over_a_moved_range_is_a_guess(self):
        # keys at 0, 3200, 6400 over a range of 1600 to 9600: frame 0, before it, lands at 8000, in the gap
        keys = ((0, (0.0,)), (3200, (20.0,)), (6400, (5.0,)))
        got, issues = self.value(keys, ort(3, 3), time_range(1600, 9600))
        self.assertMatrix(got, ct.translation((5, 0, 0)))  # as Cycle: the last key's value
        self.assertEqual(issues, [ct.ORT_APPROXIMATED])
        # the straight line across the gap of a wider range, measured on Bezier Floats only
        got, issues = self.value(((1600, _rotz(0)), (8000, _rotz(60))), ort(3, 3), time_range(0, 9600),
                                 name="Linear Rotation")
        self.assertMatrix(got, ct.quat_matrix(_rotz(30)))
        self.assertEqual(issues, [ct.ORT_APPROXIMATED])

    def test_rotation_position_and_scale(self):
        keys = ((1600, _rotz(0)), (4800, _rotz(60)))
        for code, angle in ((2, 30), (4, 30), (5, -30), (7, -30)):
            with self.subTest("rotation", code=code):
                got, issues = self.value(keys, ort(before=code), name="Linear Rotation")
                self.assertMatrix(got, ct.quat_matrix(_rotz(angle)))
                self.assertEqual(issues, [])
        got, issues = self.value(((1600, (0, 4, -2)), (4800, (20, -6, 9))), ort(before=7), name="Linear Position")
        self.assertMatrix(got, ct.translation((-10, 9, -7.5)))  # the middle, less the change over a cycle
        self.assertEqual(issues, [])
        plain = (0.0, 0.0, 0.0, 1.0)
        got, issues = self.value(((1600, (1, 2, 3) + plain), (4800, (2, 4, 4) + plain)), ort(before=7),
                                 name="Linear Scale")
        self.assertMatrix(got, ct.scale_matrix((0.5, 1, 2.5)))
        self.assertEqual(issues, [])
        turned = (0.0, 0.0, math.sin(0.2), math.cos(0.2))
        for code in (5, 7):  # scale axes that differ: the components alone, an issue
            with self.subTest("scale axes", code=code):
                _got, issues = self.value(((1600, (1, 2, 3) + plain), (4800, (2, 4, 4) + turned)), ort(before=code),
                                          name="Linear Scale")
                self.assertEqual(issues, [ct.ORT_APPROXIMATED])

    def test_damaged(self):
        for extra in (leaf(0x8499, b"\0" * 30), node(0x8499, leaf(0x3000, b"\2\0")), leaf(0x3003, b"\0" * 4)):
            with self.subTest(extra=extra):
                got, issues = self.value(LATER_KEYS, extra)
                self.assertEqual(got, ct.IDENTITY)
                self.assertTrue(issues[0].startswith(ct.DAMAGED), issues)
        for code in (5, 7):  # rotations not finite: never raises
            got, issues = self.value(((1600, (math.nan, 0, 0, 1)), (4800, _rotz(60))), ort(before=code),
                                     name="Linear Rotation")
            self.assertEqual(got, ct.IDENTITY)
            self.assertEqual(issues, [ct.NON_FINITE])


if __name__ == "__main__":
    unittest.main()
