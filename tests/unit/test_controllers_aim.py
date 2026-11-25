# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/controllers/ on aiming: the Look At controller and the LookAt Constraint
against 3ds Max's matrices, no Blender.

    python -I -m unittest discover tests
"""
import math
import os
import struct
import sys
import time
import types
import unittest

_TESTS = "maxdrop_unit_tests"  # tests/unit as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_unit_tests.controllers_support import (  # noqa: E402 (after the loader)
    Anim, Build, C_FLOATLIST, C_LOOKAT, C_LOOKAT_CONSTRAINT, C_PB2, C_POSXYZ, C_ROTLIST, C_SCALEXYZ,
    C_UNKNOWN_FLOAT, C_UNKNOWN_M3, CLASSES, ct, leaf, list_block, MatrixCase, node, pb2_entry, refs34,
    scene,
)


def rows3(frame):
    """A frame of three row vectors as a 4x4 matrix without translation."""
    return tuple(tuple(r) + (0.0,) for r in frame) + ((0.0, 0.0, 0.0, 1.0),)


def m3(*rows):
    return rows3(rows)


# 3ds Max 2020 (MAXScript, node.transform) for a box at [50, 50, 0] with a Look At controller aiming at a target
# at [0, 0, 20]; rows rounded to 6 digits as Max prints them.
MAX_LOOK_AT = {
    (2, False, 0): m3((-0.707107, 0.707107, 0), (0.19245, 0.19245, 0.96225), (0.680414, 0.680414, -0.272166)),
    (0, False, 0): m3((0.680414, 0.680414, -0.272166), (0.19245, 0.19245, 0.96225), (0.707107, -0.707107, 0)),
    (1, False, 0): m3((-0.707107, 0.707107, 0), (0.680414, 0.680414, -0.272166), (-0.19245, -0.19245, -0.96225)),
    (2, True, 0): m3((0.707107, -0.707107, 0), (0.19245, 0.19245, 0.96225), (-0.680414, -0.680414, 0.272166)),
    (0, True, 0): m3((-0.680414, -0.680414, 0.272166), (0.19245, 0.19245, 0.96225), (-0.707107, 0.707107, 0)),
    (1, True, 0): m3((0.707107, -0.707107, 0), (-0.680414, -0.680414, 0.272166), (-0.19245, -0.19245, -0.96225)),
    (2, False, 30): m3((-0.516147, 0.708597, 0.481125), (0.52022, -0.186887, 0.833333),
                       (0.680414, 0.680414, -0.272166)),
    (0, False, 30): m3((0.680414, 0.680414, -0.272166), (0.52022, -0.186887, 0.833333),
                       (0.516147, -0.708597, -0.481125)),
    (1, True, 30): m3((0.708597, -0.516147, 0.481125), (-0.680414, -0.680414, 0.272166),
                      (0.186887, -0.52022, -0.833333)),
}
# The same LookAt Constraint box at [-50, 50, 0], target at [0, 0, 20]: (target axis, flip, source up axis, source
# up flip, up node axis, up control) -> node.transform.
MAX_CONSTRAINT = {
    (0, False, 2, False, 2, 1): m3((0.680414, -0.680414, 0.272166), (0.707107, 0.707107, 0),
                                   (-0.19245, 0.19245, 0.96225)),
    (1, False, 0, False, 0, 1): m3((0.732828, 0.631748, -0.252699), (0.680414, -0.680414, 0.272166),
                                   (0, -0.371391, -0.928477)),
    (0, True, 2, False, 2, 1): m3((-0.680414, 0.680414, -0.272166), (-0.707107, -0.707107, 0),
                                  (-0.19245, 0.19245, 0.96225)),
    (0, False, 1, False, 2, 1): m3((0.680414, -0.680414, 0.272165), (-0.19245, 0.19245, 0.96225),
                                   (-0.707107, -0.707107, 0)),
    (0, False, 2, True, 2, 1): m3((0.680414, -0.680414, 0.272166), (-0.707107, -0.707107, 0),
                                  (0.19245, -0.19245, -0.96225)),
    (0, False, 2, False, 0, 1): m3((0.680414, -0.680414, 0.272166), (0, -0.371391, -0.928477),
                                   (0.732828, 0.631748, -0.252699)),
    (0, False, 2, False, 2, 0): m3((0.680414, -0.680414, 0.272166), (-0.707107, -0.707107, 0),
                                   (0.19245, -0.19245, -0.96225)),
    (1, False, 0, False, 0, 0): m3((0.19245, -0.19245, -0.96225), (0.680414, -0.680414, 0.272165),
                                   (-0.707107, -0.707107, 0)),
}
# 3ds Max 2020 probes of the offsets: name -> (box position, settings (2 relative, 4 set orientation), the
# constraint's chunks as saved, [(target position, node.transform rows)]): the box turned before the constraint was
# assigned (Keep Initial Offset) or with Set Orientation on after. 0x1001 (the world rotation at assignment) is
# replaced by identity: the local one, 0x1002, is what counts.
_INITIAL_FRAME = (-0.0173361, 0.090019, -0.1883112, 0.9778215)  # aimed from the origin at [50, 20, 10]
MAX_OFFSETS = {
    "keep initial offset": (
        (0, 0, 0), {2: 1},
        {0x1001: (0, 0, 0, 1), 0x1002: (-0.0704393, -0.2968829, -0.2831141, 0.9092553), 0x1003: _INITIAL_FRAME,
         0x1004: (0, 0, 0, 1)},
        [((50, 20, 10), m3((0.663414, 0.5566704, -0.4999999), (-0.4730215, 0.8297694, 0.2961981),
                           (0.5797694, 0.04000875, 0.8137977))),
         ((-30, 40, 25), m3((-0.7736892, 0.5808025, -0.2531276), (-0.6322067, -0.7338866, 0.2484454),
                            (-0.0414692, 0.3522485, 0.9349873)))]),
    "set orientation": (
        (0, 0, 0), {4: 1}, {0x1003: _INITIAL_FRAME, 0x1004: (-0.0694609, -0.0582117, -0.234247, 0.9679437)},
        [((50, 20, 10), m3((0.6703855, 0.7233281, 0.1654684), (-0.7416493, 0.646203, 0.1799388),
                           (0.02322861, -0.2433479, 0.9696609))),
         ((-30, 40, 25), m3((-0.7278689, 0.3344707, 0.5986118), (-0.4395502, -0.8976144, -0.03292488),
                            (0.5263101, -0.2870849, 0.8003623)))]),
    # Set Orientation on, the box turned, Set Orientation off again: the rotation stays
    "set orientation turned off": (
        (-30, 0, 0), {}, {0x1004: (-0.0620619, -0.0701832, -0.2330402, 0.9679437)},
        [((20, 30, 10), m3((0.5485346, 0.8219741, 0.153194), (-0.8329241, 0.5211591, 0.1860934),
                           (0.07312555, -0.2296776, 0.9705158))),
         ((-10, 50, 30), m3((0.007349193, 0.8234046, 0.5674073), (-0.9827967, -0.0987699, 0.1560614),
                            (0.1845444, -0.5587929, 0.8085133)))]),
    # both on, the box turned with Set Orientation after the offset was kept: Keep Initial Offset alone counts
    "both": (
        (-40, 20, 0), {2: 1, 4: 1},
        {0x1002: (0.1814979, -0.144184, -0.5026271, 0.8328478), 0x1003: (-0.0067123, 0.0811034, -0.0822069, 0.9932871),
         0x1004: (0.1502972, -0.0341292, 0.1514035, 0.9763826)},
        [((20, 30, 10), m3((0.4531538, 0.7848856, -0.4226183), (-0.889562, 0.4288489, -0.1573787),
                           (0.05771513, 0.4472619, 0.8925389))),
         ((-10, 50, 30), m3((0.002207398, 0.9917443, -0.1282119), (-0.8670341, -0.06198299, -0.4943783),
                            (-0.4982438, 0.1122554, 0.8597394)))]),
}


def constraint_block(owner, weights, targets=0, settings=None, slots=()):
    """A LookAt Constraint's ParamBlock2 as 3ds Max 2020 writes it: weights (floats; an Anim is a controller,
    no value: that form by the block rule, not measured), as many node elements as targets (no value: the block's reference slots, slots, after the weights'
    controllers), {param id: int} settings; the up node (9) with a setting 9."""
    entries = [pb2_entry(0, 0x800, 0x121081, struct.pack("<BI", 0, len(weights)) +
                         b"".join(b"\x80" if isinstance(w, Anim) else struct.pack("<Bf", 0xC0, w) for w in weights)),
               pb2_entry(1, 0x811, 0x811000, struct.pack("<BI", 0, targets) + b"\x40" * targets)]
    for pid, value in sorted((settings or {}).items()):
        if pid == 9:
            entries.append(pb2_entry(9, 0x11, 0x1810000, b"\x40"))
        else:
            entries.append(pb2_entry(pid, 4 if pid in (2, 4, 6, 8, 11) else 1, 0x920020,
                                     struct.pack("<Bi", 0x40, value)))
    head = leaf(0x0009, struct.pack("<IHIHI", 0x1B, 0, 0x55F03700, len(entries), owner))
    return node(C_PB2, *([refs34(*slots)] if slots else []), head, *entries)


class LookAtBuild(Build):
    def target(self, pos):
        return self.node(self.simple_prs(pos))

    def look_at(self, target, pos=(50, 50, 0), axis=None, flip=False, target_up=False, roll=0.0, scale=(1, 1, 1),
                parent=0):
        parts = [refs34(target, self.xyz(C_POSXYZ, pos), self.flt(roll), self.bscale(scale))]
        if axis is not None:
            parts.append(leaf(0x0100, struct.pack("<I", axis)))
        if flip:
            parts.append(leaf(0x0110))
        parts.append(leaf(0x0201, struct.pack("<B", 1 if target_up else 0)))
        return self.node(self.add(node(C_LOOKAT, *parts)), parent=parent)

    def constrained(self, targets, weights, settings=None, pos=(-50, 50, 0), scale=(1, 1, 1), parent=0, up=None,
                    offsets=None, weight_controllers=None):
        """A node whose PRS rotation is a LookAt Constraint; its block is the object right before the
        constraint. offsets: {chunk id: quaternion (4 floats) or raw bytes} of the constraint's own chunks. An Anim
        weight is held by a Bezier Float, or by weight_controllers' next object index (None: an empty slot)."""
        animated = [w for w in weights if isinstance(w, Anim)]
        if weight_controllers is None:
            controllers = [self.flt(float(w)) for w in animated]
        else:
            assert len(weight_controllers) == len(animated), "one controller per Anim weight"
            controllers = list(weight_controllers)
        block = len(self.objects)
        slots = controllers + list(targets) + ([up] if up is not None else [])
        settings = dict(settings or {})
        if up is not None:
            settings[9] = 1
        self.add(constraint_block(block + 1, weights, len(targets), settings, slots))
        own = [leaf(cid, v if isinstance(v, bytes) else struct.pack("<4f", *v))
               for cid, v in sorted((offsets or {}).items())]
        lc = self.add(node(C_LOOKAT_CONSTRAINT, refs34(block), *own))
        prs = self.prs(self.xyz(C_POSXYZ, pos), lc, self.bscale(scale))
        return self.node(prs, parent=parent)


class TestLookAt(MatrixCase):
    def test_frame_equals_max(self):
        for (axis, flip, roll), expected in MAX_LOOK_AT.items():
            got = rows3(ct.look_frame((50, 50, 0), (0, 0, 20), axis=axis, flip=flip, roll=math.radians(roll)))
            self.assertMatrix(got, expected, places=5)

    def test_degenerate_frames_equal_max(self):
        self.assertMatrix(rows3(ct.look_frame((50, 50, 0), (50, 50, 100))), m3((1, 0, 0), (0, -1, 0), (0, 0, -1)))
        self.assertMatrix(rows3(ct.look_frame((50, 50, 0), (50, 50, -100))), ct.IDENTITY)
        self.assertMatrix(rows3(ct.look_frame((50, 50, 0), (50, 50, 0))), m3((0, 1, 0), (0, 0, 1), (1, 0, 0)))
        frame = ct.look_frame((0, 0, 0), (-10, 0, 0), up=(1, 0, 0))  # up along the view: still a rotation
        self.assertAlmostEqual(_det(frame), 1.0, places=9)
        self.assertMatrix(ct.multiply(rows3(frame), ct._transpose3(rows3(frame))), ct.IDENTITY)

    def test_target_as_up_node(self):
        # the target turned 40 degrees about Y (and moved by it): Max's rows for the box
        target = m3((0.766045, 0, 0.642788), (0, 1, 0), (-0.642788, 0, 0.766045))
        got = rows3(ct.look_frame((50, 50, 0), (-12.8558, 0, 15.3209), up=target[2][:3]))
        self.assertMatrix(got, m3((-0.60812, 0.60812, -0.510274), (-0.198088, 0.506212, 0.839352),
                                  (0.768733, 0.611506, -0.187376)), places=5)

    def test_controller_in_a_file(self):
        for (axis, flip, roll), expected in MAX_LOOK_AT.items():
            b = LookAtBuild()
            target = b.target((0, 0, 20))
            n = b.look_at(target, axis=axis, flip=flip, roll=math.radians(roll), scale=(2, 1, 1))
            t = b.transforms()
            want = ct.multiply(ct.scale_matrix((2, 1, 1)), expected[:3] + ((50, 50, 0, 1),))
            self.assertMatrix(t.world(n), want, places=5)
            self.assertMatrix(t.local(n), want, places=5)
            self.assertEqual(t.look_at(n), ct.LookAt(target, axis, flip, t.look_at(n).roll, False))
            self.assertAlmostEqual(t.look_at(n).roll, math.radians(roll), places=6)
            self.assertEqual(t.issues, [])

    def test_without_target_aims_at_the_origin(self):
        b = LookAtBuild()
        n = b.look_at(None)
        t = b.transforms()
        self.assertMatrix(t.world(n), m3((-0.707107, 0.707107, 0), (0, 0, 1), (0.707107, 0.707107, 0))[:3] +
                          ((50, 50, 0, 1),), places=5)
        self.assertEqual(t.look_at(n), ct.LookAt(None, 2, False, 0.0, False))
        b = LookAtBuild()  # a target that is no node: an issue, the origin
        n = b.look_at(b.xyz(C_POSXYZ, (0, 0, 20)))
        t = b.transforms()
        self.assertMatrix(t.world(n), m3((-0.707107, 0.707107, 0), (0, 0, 1), (0.707107, 0.707107, 0))[:3] +
                          ((50, 50, 0, 1),), places=5)
        self.assertEqual([i.reason for i in t.issues], [ct.LOOK_AT_NODE])

    def test_parented(self):
        """The parent places the position; its rotation and scale do not reach the frame. Children follow the
        world matrix, and local * parent world = world."""
        b = LookAtBuild()
        rig = b.node(b.simple_prs((200, 0, 0), (0, 0, math.radians(40)), (1.5, 1.5, 1.5)))
        target = b.target((150, 60, 0))
        cam = b.look_at(target, pos=(30, 0, 50), parent=rig)
        child = b.node(b.simple_prs((0, 0, 10)), parent=cam)
        t = b.transforms()
        # what 3ds Max 2020 reports for this camera (a probe; the fixture's Dummy is at [60, 0, 0])
        want = m3((0.345248, 0.938511, 0), (-0.600795, 0.221013, 0.768243), (0.721005, -0.265235, 0.640158))
        want = want[:3] + ((234.472, 28.9254, 75, 1),)
        self.assertMatrix(t.world(cam), want, places=3)
        self.assertMatrix(ct.multiply(t.local(cam), t.world(rig)), t.world(cam))
        self.assertMatrix(t.world(child), ct.multiply(ct.translation((0, 0, 10)), t.world(cam)))
        self.assertEqual(t.issues, [])

    def test_axis_out_of_range(self):
        b = LookAtBuild()
        n = b.look_at(b.target((0, 0, 20)), axis=7)
        t = b.transforms()
        self.assertMatrix(t.world(n), MAX_LOOK_AT[(2, False, 0)][:3] + ((50, 50, 0, 1),), places=5)
        self.assertEqual([i.reason for i in t.issues], [ct.LOOK_AT_AXIS])

    def test_cycles(self):
        b = LookAtBuild()  # aims at itself
        n = len(b.objects) + 7  # the node look_at adds: position (4), roll, scale, controller, then the node
        self.assertEqual(b.look_at(n), n)
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertEqual([(i.node, i.reason[:len(ct.DAMAGED)]) for i in t.issues], [(n, ct.DAMAGED)])
        self.assertIn("depends on itself", t.issues[0].reason)
        self.assertIsNone(t.look_at(n))
        b = LookAtBuild()  # two aiming at each other: both damaged, whichever is asked for first
        a = len(b.objects) + 7
        other = b.look_at(a + 8, pos=(10, 0, 0))
        self.assertEqual(other, a)
        second = b.look_at(a, pos=(0, 10, 0))
        for first in (a, second):
            t = b.transforms()
            t.world(first)
            self.assertEqual(sorted((i.node, i.reason[:len(ct.DAMAGED)]) for i in t.issues),
                             [(a, ct.DAMAGED), (second, ct.DAMAGED)])
            self.assertEqual((t.world(a), t.world(second)), (ct.IDENTITY, ct.IDENTITY))
            self.assertEqual((t.look_at(a), t.look_at(second)), (None, None))
        b = LookAtBuild()  # a node aiming into a cycle is not on it: it aims at the damaged node
        c = len(b.objects) + 7
        self.assertEqual(b.look_at(c + 8), c)
        self.assertEqual(b.look_at(c + 16, pos=(10, 0, 0)), c + 8)
        self.assertEqual(b.look_at(c + 8, pos=(0, 10, 0)), c + 16)
        t = b.transforms()
        t.world(c)
        self.assertEqual(sorted(i.node for i in t.issues), [c + 8, c + 16])
        self.assertIsNotNone(t.look_at(c))

    def test_long_chain(self):
        b = LookAtBuild()
        first = len(b.objects) + 7
        for k in range(ct.MAX_LOOK_AT_DEPTH + 10):  # each node aims at the next (8 objects each)
            self.assertEqual(b.look_at(first + 8 * (k + 1), pos=(k, 0, 0)), first + 8 * k)
        b.target((0, 0, 0))
        t = b.transforms()
        world = t.world(first)
        self.assertTrue(all(math.isfinite(v) for row in world for v in row))
        self.assertTrue(any("more than %d" % ct.MAX_LOOK_AT_DEPTH in i.reason for i in t.issues))

    def test_parent_that_cannot_be_inverted(self):
        b = LookAtBuild()
        flat = b.node(b.simple_prs((0, 0, 0), (0, 0, 0), (1, 1, 0)))
        n = b.look_at(b.target((0, 0, 20)), parent=flat)
        t = b.transforms()
        self.assertEqual(t.local(n), ct.IDENTITY)
        self.assertEqual([i.reason for i in t.issues], [ct.LOOK_AT_PARENT])

    def test_outside_a_node(self):
        b = LookAtBuild()
        look = b.add(node(C_LOOKAT, refs34(None, b.xyz(C_POSXYZ, (1, 2, 3)))))
        m, issues = ct.matrix(scene.Scene(node(0x2025, *b.objects), CLASSES), look)
        self.assertEqual((m, [i.reason for i in issues]), (ct.IDENTITY, [ct.UNKNOWN_CLASS]))


def _det(f):
    return (f[0][0] * (f[1][1] * f[2][2] - f[1][2] * f[2][1]) - f[0][1] * (f[1][0] * f[2][2] - f[1][2] * f[2][0]) +
            f[0][2] * (f[1][0] * f[2][1] - f[1][1] * f[2][0]))


class TestConstraint(MatrixCase):
    def test_frame_equals_max(self):
        for (axis, flip, source, source_flip, up_axis, control), expected in MAX_CONSTRAINT.items():
            p = (-50, 50, 0)
            up = ct.IDENTITY[up_axis][:3] if control else tuple(-v for v in p)
            got = rows3(ct.constraint_frame(p, (0, 0, 20), up, axis, flip, source, source_flip))
            self.assertMatrix(got, expected, places=5)

    def test_cannot_be_aimed(self):
        self.assertIsNone(ct.constraint_frame((0, 0, 0), (0, 0, 0), (0, 0, 1)))
        self.assertIsNone(ct.constraint_frame((0, 0, 0), (0, 0, 5), (0, 0, 1)))
        self.assertIsNone(ct.constraint_frame((0, 0, 0), (5, 0, 0), (0, 0, 1), axis=2, source_up=2))
        self.assertIsNone(ct.constraint_frame((0, 0, 0), (5, 0, 0), (0, 0, 1), axis=3))

    def test_weighted_targets_in_a_file(self):
        b = LookAtBuild()
        targets = [b.target((0, 0, 20)), b.target((100, 0, 0))]
        n = b.constrained(targets, [50.0, 100.0], scale=(1, 2, 1))
        t = b.transforms()
        two = m3((0.91788, -0.393377, 0.0524503), (0.393919, 0.919145, 0), (-0.0482094, 0.0206612, 0.998624))
        want = ct.multiply(ct.scale_matrix((1, 2, 1)), two[:3] + ((-50, 50, 0, 1),))
        self.assertMatrix(t.world(n), want, places=5)
        self.assertIsNone(t.look_at(n))
        self.assertEqual(t.issues, [])

    def test_animated_weight(self):
        """An animated weight is a controller in the block's next reference slot: weight (0) comes before the targets
        (1) and the up node (9), so its controller takes slot 0 and moves each of them up by one."""
        two = m3((0.91788, -0.393377, 0.0524503), (0.393919, 0.919145, 0), (-0.0482094, 0.0206612, 0.998624))
        want = ct.multiply(ct.scale_matrix((1, 2, 1)), two[:3] + ((-50, 50, 0, 1),))
        for weights in ([Anim(50.0), 100.0], [50.0, Anim(100.0)], [Anim(50.0), Anim(100.0)]):
            with self.subTest(weights=weights):
                b = LookAtBuild()
                targets = [b.target((0, 0, 20)), b.target((100, 0, 0))]
                n = b.constrained(targets, weights, scale=(1, 2, 1))
                t = b.transforms()
                self.assertMatrix(t.world(n), want, places=5)
                self.assertEqual(t.issues, [])

        def up_node(weight, up_pos):
            b = LookAtBuild()
            target, up = b.target((0, 0, 20)), b.target(up_pos)
            n = b.constrained([target], [weight], {8: 0, 13: 0}, up=up)
            t = b.transforms()
            return t.world(n), t.issues

        world, issues = up_node(Anim(50.0), (0, 0, 0))  # the up node at the origin, looked at: 3ds Max's frame
        self.assertMatrix(world, MAX_CONSTRAINT[(0, False, 2, False, 2, 0)][:3] + ((-50, 50, 0, 1),), places=5)
        self.assertEqual(issues, [])
        world, issues = up_node(Anim(50.0), (30, -40, 60))  # off the origin: the up node itself, not the world
        self.assertMatrix(world, up_node(50.0, (30, -40, 60))[0])
        self.assertEqual(issues, [])
        self.assertNotAlmostEqual(world[2][2], MAX_CONSTRAINT[(0, False, 2, False, 2, 0)][2][2], places=3)

        def fallback(controller):
            """The world of [Anim(7), 100] whose weight controller is made by controller(b), the issues, the
            controller's index and the constraint's (7 only marks the slot: a weight read gives no 50)."""
            b = LookAtBuild()
            targets = [b.target((0, 0, 20)), b.target((100, 0, 0))]
            c = controller(b)
            lc = len(b.objects) + 1  # constrained adds the block, then the constraint
            n = b.constrained(targets, [Anim(7.0), 100.0], scale=(1, 2, 1), weight_controllers=[c])
            t = b.transforms()
            return t.world(n), [(i.controller, i.reason) for i in t.issues], c, lc

        b = LookAtBuild()  # a weight of 1 (the old fallback) aims elsewhere: the cases below tell the two apart
        n = b.constrained([b.target((0, 0, 20)), b.target((100, 0, 0))], [1.0, 100.0], scale=(1, 2, 1))
        one = b.transforms().world(n)
        self.assertFalse(all(abs(one[r][c] - want[r][c]) < 1e-3 for r in range(3) for c in range(3)))
        # a weight the reader cannot read is 50 (appendTarget's default on the 0-100 scale): want's weights
        for name, controller in (("Bezier Float without a value or keys", lambda b: b.flt()),
                                 ("empty slot", lambda b: None)):
            with self.subTest(name):
                world, issues, _c, lc = fallback(controller)
                self.assertMatrix(world, want, places=5)
                self.assertEqual(issues, [(lc, ct.CONSTRAINT_SETTING)])
        world, issues, c, _lc = fallback(lambda b: b.add(node(C_UNKNOWN_M3)))  # reported once, as its class
        self.assertMatrix(world, want, places=5)
        self.assertEqual(issues, [(c, ct.UNKNOWN_CLASS)])

    def test_unreadable_stored_weight(self):
        """A stored weight that is not finite, and a weight table shorter than the targets: 50, reported."""
        two = m3((0.91788, -0.393377, 0.0524503), (0.393919, 0.919145, 0), (-0.0482094, 0.0206612, 0.998624))
        want = ct.multiply(ct.scale_matrix((1, 2, 1)), two[:3] + ((-50, 50, 0, 1),))  # weights 50 and 100
        for name, weights, positions in (("not finite", [float("nan"), 100.0], ((0, 0, 20), (100, 0, 0))),
                                         ("missing", [100.0], ((100, 0, 0), (0, 0, 20)))):
            with self.subTest(name):
                b = LookAtBuild()
                targets = [b.target(p) for p in positions]
                n = b.constrained(targets, weights, scale=(1, 2, 1))
                t = b.transforms()
                self.assertMatrix(t.world(n), want, places=5)
                self.assertEqual([i.reason for i in t.issues], [ct.CONSTRAINT_SETTING])

    def test_unreadable_animated_weight_more(self):
        """An empty Float List gives no value (50, reported); one unknown controller in two weights' slots is 50 in
        both and reported once, also when the memo answers the second."""
        def world(weights, controllers=None):
            b = LookAtBuild()
            targets = [b.target(p) for p in ((0, 0, 20), (100, 0, 0), (0, 80, 0))[:len(weights)]]
            cs = [c(b) for c in controllers] if controllers else None
            if cs and len(cs) == 2 and cs[1] == "same":
                cs[1] = cs[0]
            n = b.constrained(targets, weights, scale=(1, 2, 1), weight_controllers=cs)
            t = b.transforms()
            return t.world(n), [(i.controller, i.reason) for i in t.issues], cs

        def empty_list(b):
            return b.add(node(C_FLOATLIST, refs34(None, None, None, None, list_block(b)),
                              leaf(0x1010, struct.pack("<i", 0))))

        want, _issues, _cs = world([50.0, 100.0])
        got, issues, _cs = world([Anim(7.0), 100.0], [empty_list])
        self.assertMatrix(got, want, places=5)
        self.assertEqual([reason for _c, reason in issues], [ct.CONSTRAINT_SETTING])
        third, _issues, _cs = world([50.0, 50.0, 100.0])  # beside a stored 100, so 50 and 1 aim apart
        got, issues, cs = world([Anim(7.0), Anim(7.0), 100.0],
                                [lambda b: b.add(node(C_UNKNOWN_M3)), lambda b: "same"])
        self.assertMatrix(got, third, places=5)
        self.assertEqual(issues, [(cs[0], ct.UNKNOWN_CLASS)])

    def test_weight_list_without_a_readable_entry(self):
        """A Float List whose entries give no value (maxdrop-6n0.6.17) is no weight: 50, as one weight controller of
        an unknown class or without a value; unknown entries are reported once each, as their class."""
        def world(weights, controllers=None):
            b = LookAtBuild()
            targets = [b.target(p) for p in ((0, 0, 20), (100, 0, 0))]
            cs = [c(b) for c in controllers] if controllers else None
            n = b.constrained(targets, weights, scale=(1, 2, 1), weight_controllers=cs)
            t = b.transforms()
            return t.world(n), [(i.controller, i.reason) for i in t.issues], cs

        def weight_list(*make):
            def build(b):
                entries = [m(b) for m in make]
                weights = list_block(b, *([1.0] * len(entries)))
                return b.add(node(C_FLOATLIST, refs34(*(entries + [None] * (4 - len(entries))), weights),
                                  leaf(0x1010, struct.pack("<i", len(entries)))))
            return build

        want, _issues, _cs = world([50.0, 100.0])
        unknown = weight_list(lambda b: b.add(node(C_UNKNOWN_FLOAT, leaf(0x2501, struct.pack("<f", 9)))),
                              lambda b: b.add(node(C_UNKNOWN_FLOAT, leaf(0x2501, struct.pack("<f", 9)))))
        got, issues, _cs = world([Anim(7.0), 100.0], [unknown])
        self.assertMatrix(got, want, places=5)
        self.assertEqual([reason for _c, reason in issues], [ct.UNKNOWN_CLASS, ct.UNKNOWN_CLASS])
        self.assertEqual(len({c for c, _reason in issues}), 2)
        got, issues, _cs = world([Anim(7.0), 100.0], [weight_list(lambda b: b.flt())])  # a value-less Bezier Float
        self.assertMatrix(got, want, places=5)
        self.assertEqual([reason for _c, reason in issues], [ct.CONSTRAINT_SETTING])
        got, issues, _cs = world([Anim(7.0), 100.0], [weight_list(lambda b: b.flt(50.0),  # one readable: its sum
                                                                  lambda b: b.add(node(C_UNKNOWN_FLOAT)))])
        self.assertMatrix(got, want, places=5)
        self.assertEqual([reason for _c, reason in issues], [ct.UNKNOWN_CLASS])
        b = Build()  # under ScaleXYZ the same list still adds nothing: that axis reads 0, as before
        odd = b.add(node(C_UNKNOWN_FLOAT, leaf(0x2501, struct.pack("<f", 9))))
        flist = b.add(node(C_FLOATLIST, refs34(odd, None, None, None, list_block(b, 1.0)),
                           leaf(0x1010, struct.pack("<i", 1))))
        n = b.node(b.prs(None, None, b.add(node(C_SCALEXYZ, refs34(None, flist, None)))))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.scale_matrix((1, 0, 1)))
        self.assertEqual([i.reason for i in t.issues], [ct.UNKNOWN_CLASS])

    def test_many_unreadable_weights_stay_linear(self):
        """A hostile table of empty animated weight slots (one byte each) is read in linear time."""
        n_weights = 20000
        b = LookAtBuild()
        targets = [b.target((0, 0, 20))] + [None] * (n_weights - 1)
        n = b.constrained(targets, [Anim(7.0)] * n_weights, weight_controllers=[None] * n_weights)
        t = b.transforms()
        start = time.perf_counter()
        t.world(n)
        self.assertLess(time.perf_counter() - start, 5.0)
        self.assertEqual(len(t.issues), n_weights)

    def test_settings_and_up_node(self):
        for (axis, flip, source, source_flip, up_axis, control), expected in MAX_CONSTRAINT.items():
            b = LookAtBuild()
            target = b.target((0, 0, 20))
            n = b.constrained([target], [50.0], {5: axis, 6: int(flip), 7: up_axis, 10: source, 11: int(source_flip),
                                                 13: control})
            t = b.transforms()
            self.assertMatrix(t.world(n), expected[:3] + ((-50, 50, 0, 1),), places=5)
            self.assertEqual(t.issues, [])
        b = LookAtBuild()  # an up node instead of the world: its position, looked at, is the origin's here
        target, up = b.target((0, 0, 20)), b.target((0, 0, 0))
        n = b.constrained([target], [50.0], {8: 0, 13: 0}, up=up)
        t = b.transforms()
        self.assertMatrix(t.world(n), MAX_CONSTRAINT[(0, False, 2, False, 2, 0)][:3] + ((-50, 50, 0, 1),),
                          places=5)

    def test_parent_scale_still_applies(self):
        """3ds Max: a constrained box (own scale 1) under a Dummy rotated (10, 0, 40) and scaled (1, 2, 3)."""
        b = LookAtBuild()
        rig = b.node(b.simple_prs((200, 0, 0), (math.radians(10), 0, math.radians(40)), (1, 2, 3)))
        n = b.constrained([b.target((150, 60, 0))], [50.0], pos=(-20, 10, 5), parent=rig)
        t = b.transforms()
        want = m3((-0.354542, 0.894293, -0.27302), (-1.85922, -0.737086, 0), (-0.301858, 0.761406, 2.88603))
        self.assertMatrix(t.world(n), want[:3] + ((173.693, 0.237043, 18.2451, 1),), places=3)
        self.assertMatrix(ct.multiply(t.local(n), t.world(rig)), t.world(n))

    def test_offsets_equal_max(self):
        """3ds Max 2020 probes: node.transform of a box with its constraint's chunks as saved, the target where it
        was at assignment and moved after."""
        for name, (pos, settings, offsets, states) in MAX_OFFSETS.items():
            for target, expected in states:
                with self.subTest(name, target=target):
                    b = LookAtBuild()
                    n = b.constrained([b.target(target)], [50.0], settings, pos=pos, offsets=offsets)
                    t = b.transforms()
                    self.assertMatrix(t.world(n), expected[:3] + (tuple(pos) + (1,),), places=5)
                    self.assertEqual(t.issues, [])

    def test_keep_initial_offset_under_a_parent(self):
        """3ds Max 2020: a box under a Dummy turned (10, 0, 40) and scaled 1.5, turned (20, 30, 40) in its parent's
        space before the constraint; then the target moved and the Dummy turned 30 more about Z. The local rotation
        at assignment (0x1002), not the world one (0x1001), is kept relative to the frame."""
        offsets = {0x1001: (-0.0841859, -0.2499998, 0.0669874, 0.9622502),
                   0x1002: (-0.0704393, -0.2968827, -0.2831139, 0.9092554),
                   0x1003: (-9e-05, 7.27e-05, -0.7777493, 0.6285746), 0x1004: (0, 0, 0, 1)}
        for z, target, expected in (
                (40, (20, 30, 10), ((0.6634143, 0.5566702, -0.4999997), (-0.4730213, 0.8297696, 0.2961979),
                                    (0.5797691, 0.04000861, 0.8137979), (28.36047, -8.965195, 9.99078))),
                (70, (-10, 50, 30), ((0.3718089, 0.8391132, -0.3970479), (-0.6857191, 0.5365602, 0.4918255),
                                     (0.6257374, 0.08939828, 0.7748938), (37.08196, -23.58385, 9.99078)))):
            with self.subTest(target=target):
                b = LookAtBuild()
                rig = b.node(b.simple_prs((60, 0, 0), (math.radians(10), 0, math.radians(z)), (1.5, 1.5, 1.5)))
                n = b.constrained([b.target(target)], [50.0], {2: 1}, pos=(-20, 10, 5), scale=(1 / 1.5,) * 3,
                                  parent=rig, offsets=offsets)
                t = b.transforms()
                self.assertMatrix(t.world(n), m3(*expected[:3])[:3] + (expected[3] + (1,),), places=4)
                self.assertEqual(t.issues, [])

    def test_offset_not_stored(self):
        plain = MAX_CONSTRAINT[(0, False, 2, False, 2, 1)][:3] + ((-50, 50, 0, 1),)
        quat = (0.1814979, -0.144184, -0.5026271, 0.8328478)
        for settings, offsets in (({2: 1}, {}), ({2: 1}, {0x1002: quat}),
                                  ({2: 1}, {0x1002: quat, 0x1003: bytes(8)}), ({4: 1}, {}),
                                  ({4: 1}, {0x1004: bytes(12)})):
            with self.subTest(settings=settings, offsets=offsets):
                b = LookAtBuild()
                n = b.constrained([b.target((0, 0, 20))], [50.0], settings, offsets=offsets)
                t = b.transforms()
                self.assertMatrix(t.world(n), plain, places=5)
                self.assertEqual([i.reason for i in t.issues], [ct.CONSTRAINT_OFFSET])
        for offsets in ({}, {0x1004: (0, 0, 0, 0)}, {0x1004: (0, 0, 0, 1)}):  # nothing set: no offset, no issue
            with self.subTest(offsets=offsets):
                b = LookAtBuild()
                n = b.constrained([b.target((0, 0, 20))], [50.0], offsets=offsets)
                t = b.transforms()
                self.assertMatrix(t.world(n), plain, places=5)
                self.assertEqual(t.issues, [])
        b = LookAtBuild()  # a quaternion that is not finite
        n = b.constrained([b.target((0, 0, 20))], [50.0], {2: 1},
                          offsets={0x1002: (float("nan"), 0, 0, 1), 0x1003: (0, 0, 0, 1)})
        t = b.transforms()
        self.assertTrue(all(math.isfinite(v) for row in t.world(n) for v in row))
        self.assertEqual([i.reason for i in t.issues], [ct.NON_FINITE])

    def test_without_weight(self):
        b = LookAtBuild()
        n = b.constrained([b.target((0, 0, 20))], [0.0])
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((-50, 50, 0)))
        self.assertEqual([i.reason for i in t.issues], [ct.CONSTRAINT_EMPTY])
        b = LookAtBuild()  # target on the node: no rotation
        n = b.constrained([b.target((-50, 50, 0))], [50.0])
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((-50, 50, 0)))
        self.assertEqual([i.reason for i in t.issues], [ct.CONSTRAINT_DEGENERATE])

    def test_missing_or_damaged_parameters(self):
        b = LookAtBuild()  # an empty block: no target, no other issue
        block = b.add(node(C_PB2, leaf(0x0009, struct.pack("<IHIHI", 0x1B, 0, 0x55F03700, 0, 0))))
        lc = b.add(node(C_LOOKAT_CONSTRAINT, refs34(block)))
        n = b.node(b.prs(b.xyz(C_POSXYZ, (1, 2, 3)), lc, b.bscale()))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((1, 2, 3)))
        self.assertEqual([i.reason for i in t.issues], [ct.CONSTRAINT_EMPTY])
        b = LookAtBuild()  # a damaged target axis entry (3 bytes of value): reported, its default used
        target = b.target((0, 0, 20))
        start = len(b.objects)
        good = constraint_block(start + 1, [50.0], 1, None, (target,))
        bad = pb2_entry(5, 1, 0x920020, struct.pack("<B", 0x40) + b"\x01\x00\x00")
        raw = good[6:] + bad
        b.add(struct.pack("<HI", C_PB2, (6 + len(raw)) | 0x80000000) + raw)
        lc = b.add(node(C_LOOKAT_CONSTRAINT, refs34(start)))
        n = b.node(b.prs(b.xyz(C_POSXYZ, (-50, 50, 0)), lc, b.bscale()))
        t = b.transforms()
        self.assertMatrix(t.world(n), MAX_CONSTRAINT[(0, False, 2, False, 2, 1)][:3] + ((-50, 50, 0, 1),), places=5)
        self.assertEqual([i.reason.split(":")[0] for i in t.issues], [ct.CONSTRAINT_BLOCK])

    def test_not_under_a_prs(self):
        b = LookAtBuild()
        block = b.add(constraint_block(0, [50.0], 0))
        lc = b.add(node(C_LOOKAT_CONSTRAINT, refs34(block)))
        lst = b.add(node(C_ROTLIST, refs34(lc), leaf(0x1010, struct.pack("<i", 1))))
        n = b.node(b.prs(None, lst))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertIn((lc, ct.UNKNOWN_CLASS), [(i.controller, i.reason) for i in t.issues])


if __name__ == "__main__":
    unittest.main()
