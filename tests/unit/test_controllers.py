# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/controllers/, the transforms at frame 0: no Blender. The matrix conventions, synthetic
controller trees (PRS, the XYZ controllers, saved values and keys, lists with weights, unknown classes, damaged
input) and every committed fixture's world and object transforms against its 3ds Max oracle.

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
    Anim, Build, C_BFLOAT, C_BPOS, C_BSCALE, C_FLOATLIST, C_LINFLOAT, C_NODE, C_PB2, C_POSLIST,
    C_POSXYZ, C_ROTLIST, C_SCALELIST, C_SCALEXYZ, C_TCBFLOAT, C_TCBROT, C_TCBSCALE, C_UNKNOWN_FLOAT,
    C_UNKNOWN_M3, classdir, CLASSES, classids, ct, float_keys, leaf, list_block, MatrixCase, node,
    pb2_entry, refs34, scale_keys, scene,
)


class TestConventions(MatrixCase):
    def test_euler_z_is_a_standard_row_vector_rotation(self):
        c, s = math.cos(math.pi / 6), math.sin(math.pi / 6)
        m = ct.euler_matrix((0.0, 0.0, math.pi / 6))
        self.assertMatrix(m, ((c, s, 0, 0), (-s, c, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))

    def test_euler_xyz_applies_x_first(self):
        a, b, g = 0.3, -0.7, 1.1
        x, y, z = (ct.euler_matrix(v) for v in ((a, 0, 0), (0, b, 0), (0, 0, g)))
        self.assertMatrix(ct.euler_matrix((a, b, g)), ct.multiply(ct.multiply(x, y), z))
        self.assertMatrix(ct.euler_matrix((a, b, g), 5), ct.multiply(ct.multiply(z, y), x))  # ZYX
        self.assertMatrix(ct.euler_matrix((a, b, g), 2), ct.multiply(ct.multiply(y, z), x))  # YZX

    def test_max_quaternion_is_the_conjugate(self):
        # ORACLE.md: +30 degrees about Z (row 1 = [0.866, 0.5, 0]) is stored as [0, 0, -0.258819, 0.965926]
        h = math.radians(15)
        self.assertMatrix(ct.quat_matrix((0, 0, -math.sin(h), math.cos(h))), ct.euler_matrix((0, 0, math.pi / 6)))
        self.assertMatrix(ct.quat_matrix((0, 0, -2 * math.sin(h), 2 * math.cos(h))),
                          ct.euler_matrix((0, 0, math.pi / 6)))  # not normalized
        self.assertIs(ct.quat_matrix((0, 0, 0, 0)), ct.IDENTITY)

    def test_scale_axis(self):
        h = math.radians(45)  # the scale axes turned +90 degrees about Z: their X is the world's Y
        m = ct.scale_matrix((2.0, 1.0, 1.0), (0, 0, -math.sin(h), math.cos(h)))
        self.assertMatrix(m, ((1, 0, 0, 0), (0, 2, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
        self.assertMatrix(ct.scale_matrix((-1, 2, 3)), ((-1, 0, 0, 0), (0, 2, 0, 0), (0, 0, 3, 0), (0, 0, 0, 1)))

    def test_multiply_applies_left_first(self):
        t = ct.translation((1, 0, 0))
        r = ct.euler_matrix((0, 0, math.pi / 2))
        self.assertMatrix(ct.multiply(t, r)[3:], ((0, 1, 0, 1),))  # moved, then turned
        self.assertMatrix(ct.multiply(r, t)[3:], ((1, 0, 0, 1),))


class TestPRS(MatrixCase):
    def test_local_is_scale_rotation_position(self):
        b = Build()
        n = b.node(b.simple_prs((1, 2, 3), (0, 0, math.pi / 2), (2, 2, 2)))
        t = b.transforms()
        self.assertMatrix(t.local(n), ((0, 2, 0, 0), (-2, 0, 0, 0), (0, 0, 2, 0), (1, 2, 3, 1)))
        self.assertEqual(t.world(n), t.local(n))
        self.assertEqual(t.issues, [])

    def test_whole_chain_and_negative_scale(self):
        b = Build()
        top = b.node(b.simple_prs((10, 0, 0), (0, 0, math.pi / 6)))
        mid = b.node(b.simple_prs((30, 0, 0), (0.2, 0.1, 0)), parent=top)
        low = b.node(b.simple_prs((25, 5, 0), (0, 0, 0), (-1, -1, -1)), parent=mid)
        t = b.transforms()
        expected = ct.multiply(ct.multiply(t.local(low), t.local(mid)), t.local(top))
        self.assertMatrix(t.world(low), expected)
        self.assertMatrix(t.world(mid), ct.multiply(t.local(mid), t.local(top)))
        r = t.world(low)
        det = (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1]) - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0]) +
               r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))
        self.assertAlmostEqual(det, -1.0)  # mirrored, kept as it is

    def test_parent_after_child_in_object_order(self):
        b = Build()
        child_tm, parent_tm = b.simple_prs((1, 0, 0)), b.simple_prs((0, 0, 5))
        child = len(b.objects)
        b.node(child_tm, parent=child + 1)
        parent = b.node(parent_tm)
        t = b.transforms()
        self.assertMatrix(t.world(child), ct.translation((1, 0, 5)))
        self.assertMatrix(t.world(parent), ct.translation((0, 0, 5)))

    def test_offset_and_object_world(self):
        b = Build()
        h = math.radians(45)
        q = (0, 0, -math.sin(h), math.cos(h))  # +90 degrees about Z
        n = b.node(b.simple_prs((100, 0, 0)), pivot=((5, 0, 0), q, (2, 2, 2)))
        t = b.transforms()
        self.assertMatrix(t.offset(n), ((0, 2, 0, 0), (-2, 0, 0, 0), (0, 0, 2, 0), (5, 0, 0, 1)))
        self.assertMatrix(t.object_world(n), ct.multiply(t.offset(n), t.world(n)))
        self.assertMatrix(t.object_world(n)[3:], ((105, 0, 0, 1),))

    def test_missing_slots_are_identity(self):
        b = Build()
        n = b.node(b.prs(b.xyz(C_POSXYZ, (1, None, 3))))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((1, 0, 3)))
        self.assertEqual(t.issues, [])


class TestValues(MatrixCase):
    def position_of(self, build, pos_ctrl):
        n = build.node(build.prs(pos_ctrl))
        t = build.transforms()
        return t.world(n)[3][:3], t.issues

    def float_node(self, **kw):
        b = Build()
        return self.position_of(b, b.add(node(C_POSXYZ, refs34(b.flt(**kw)))))

    def test_float_direct_and_wrapped(self):
        self.assertEqual(self.float_node(value=4.0)[0], (4.0, 0.0, 0.0))
        self.assertEqual(self.float_node(value=-2.5, wrap=False)[0], (-2.5, 0.0, 0.0))
        self.assertEqual(self.float_node()[0], (0.0, 0.0, 0.0))

    def test_saved_value_wins_over_keys(self):
        pos, issues = self.float_node(value=4.0, keys=float_keys((0, 9.0)))
        self.assertEqual((pos, issues), ((4.0, 0.0, 0.0), []))
        pos, issues = self.float_node(value=4.0, keys=float_keys((0, 9.0), (100, 7.0)))
        self.assertEqual(pos, (4.0, 0.0, 0.0))
        self.assertEqual([i.reason for i in issues], [ct.ANIMATED])
        self.assertEqual(issues[0].class_id, classids.BEZIER_FLOAT)

    def test_keys_without_saved_value(self):
        self.assertEqual(self.float_node(keys=float_keys((0, 9.0)))[0], (9.0, 0.0, 0.0))
        self.assertEqual(self.float_node(keys=float_keys((200, 3.0), (400, 5.0)))[0], (3.0, 0.0, 0.0))
        self.assertEqual(self.float_node(keys=float_keys((-400, 3.0), (-200, 5.0)))[0], (5.0, 0.0, 0.0))
        self.assertEqual(self.float_node(keys=float_keys((-100, 3.0), (0, 6.0), (100, 5.0)))[0], (6.0, 0.0, 0.0))
        pos, issues = self.float_node(keys=float_keys((-100, 2.0), (300, 6.0)))
        self.assertAlmostEqual(pos[0], 2.625)  # flat tangents, handles a third long: 3u^2 - 2u^3 of the way
        self.assertEqual(issues, [])
        free = leaf(0x2525, b"".join(struct.pack("<iIf4f", t, 0x101690, v, 0, 0, -1, -1)
                                     for t, v in ((-100, 2.0), (300, 6.0))))
        pos, issues = self.float_node(keys=free)
        self.assertAlmostEqual(pos[0], 3.0)  # a free handle of a negative length: linear, an issue
        self.assertEqual([i.reason for i in issues], [ct.KEYS_INTERPOLATED])
        self.assertEqual(self.float_node(keys=float_keys())[0], (0.0, 0.0, 0.0))

    def test_damaged_keys(self):
        for name, keys in (("size", leaf(0x2525, b"\0" * 27)),
                           ("order", float_keys((-100, 1.0), (100, 2.0), (-50, 3.0), (-20, 4.0)))):
            with self.subTest(name):
                pos, issues = self.float_node(keys=keys)
                self.assertEqual(pos, (0.0, 0.0, 0.0))
                self.assertEqual(len(issues), 1)
                self.assertTrue(issues[0].reason.startswith(ct.DAMAGED), issues[0].reason)

    def test_odd_key_chunk_beside_a_saved_value(self):
        pos, issues = self.float_node(value=1.5, keys=leaf(0x2525, b"k" * 30))
        self.assertEqual(pos, (1.5, 0.0, 0.0))
        self.assertEqual([i.reason for i in issues], [ct.KEYS_UNKNOWN])

    def test_unknown_key_chunk(self):
        b = Build()
        f = b.add(node(C_BFLOAT, leaf(0x2501, struct.pack("<f", 1.5)), leaf(0x2521, b"\0" * 8)))
        pos, issues = self.position_of(b, b.add(node(C_POSXYZ, refs34(f))))
        self.assertEqual(pos, (1.5, 0.0, 0.0))
        self.assertEqual([i.reason for i in issues], [ct.KEYS_UNKNOWN])

    def test_scale_keys(self):
        b = Build()
        n = b.node(b.prs(None, None, b.bscale(saved=False, keys=scale_keys((0, (2, 3, 4, 0, 0, 0, 1))))))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.scale_matrix((2, 3, 4)))
        b = Build()
        n = b.node(b.prs(None, None, b.bscale((5, 5, 5), keys=scale_keys((0, (2, 3, 4, 0, 0, 0, 1))))))
        self.assertMatrix(b.transforms().world(n), ct.scale_matrix((5, 5, 5)))

    def test_other_value_controllers(self):
        b = Build()
        h = math.radians(15)
        pos = b.add(node(C_BPOS, leaf(0x2503, struct.pack("<3f", 1, 2, 3))))
        rot = b.add(node(C_TCBROT, leaf(0x2504, struct.pack("<4f", 0, 0, -math.sin(h), math.cos(h)))))
        scl = b.add(node(C_TCBSCALE, leaf(0x2505, struct.pack("<7f", 2, 2, 2, 0, 0, 0, 1))))
        n = b.node(b.prs(pos, rot, scl))
        t = b.transforms()
        expected = ct.multiply(ct.multiply(ct.scale_matrix((2, 2, 2)), ct.euler_matrix((0, 0, math.pi / 6))),
                               ct.translation((1, 2, 3)))
        self.assertMatrix(t.world(n), expected)
        b = Build()  # a 12-byte ScaleValue: no axis
        n = b.node(b.prs(None, None, b.add(node(C_TCBSCALE, leaf(0x2505, struct.pack("<3f", 2, 3, 4))))))
        self.assertMatrix(b.transforms().world(n), ct.scale_matrix((2, 3, 4)))
        b = Build()
        n = b.node(b.prs(None, None, b.xyz(C_SCALEXYZ, (2, None, -1), default_wrap=False)))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.scale_matrix((2, 1, -1)))
        self.assertEqual(t.issues, [])

    def test_euler_order(self):
        b = Build()
        angles = (0.3, 0.2, 0.1)
        n = b.node(b.prs(None, b.euler(angles, order=4)))
        self.assertMatrix(b.transforms().world(n), ct.euler_matrix(angles, 4))
        for stored in (7, 106, -1):  # 106: XYX, an Euler order that repeats an axis
            b = Build()
            n = b.node(b.prs(None, b.euler(angles, order=stored)))
            t = b.transforms()
            self.assertMatrix(t.world(n), ct.euler_matrix(angles, 0))
            self.assertEqual([i.reason for i in t.issues], [ct.EULER_ORDER])

    def test_euler_order_as_3ds_max_saves_it(self):
        # controllers fixture: XYZ saved as 0, XZY ... ZYX as 101 ... 105
        angles = (0.3, 0.2, 0.1)
        for stored, order in ((0, 0), (100, 0), (101, 1), (102, 2), (103, 3), (104, 4), (105, 5)):
            b = Build()
            n = b.node(b.prs(None, b.euler(angles, order=stored)))
            t = b.transforms()
            self.assertMatrix(t.world(n), ct.euler_matrix(angles, order))
            self.assertEqual(t.issues, [])

    def test_float_controllers(self):
        b = Build()
        lin = b.add(node(C_LINFLOAT, leaf(0x2501, struct.pack("<f", 11))))
        tcb = b.add(node(C_TCBFLOAT, leaf(0x2501, struct.pack("<f", -22))))
        flist = b.add(node(C_FLOATLIST, refs34(b.flt(30.0), b.flt(7.0), None, None, list_block(b, 0.5, 1.0)),
                           leaf(0x1010, struct.pack("<i", 2))))
        n = b.node(b.prs(b.add(node(C_POSXYZ, refs34(lin, tcb, flist)))))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((11, -22, 22)))  # 0.5 * 30 + 1.0 * 7
        self.assertEqual(t.issues, [])
        b = Build()  # under ScaleXYZ: an empty list keeps the default, an unknown entry adds nothing
        empty = b.add(node(C_FLOATLIST, refs34(None, None, None, None, list_block(b)),
                           leaf(0x1010, struct.pack("<i", 0))))
        odd = b.add(node(C_UNKNOWN_FLOAT, leaf(0x2501, struct.pack("<f", 9))))
        mixed = b.add(node(C_FLOATLIST, refs34(b.flt(2.0), odd, None, None, list_block(b, 1.0, 1.0)),
                           leaf(0x1010, struct.pack("<i", 2))))
        n = b.node(b.prs(None, None, b.add(node(C_SCALEXYZ, refs34(empty, mixed, None)))))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.scale_matrix((1, 2, 1)))
        self.assertEqual([i.reason for i in t.issues], [ct.UNKNOWN_CLASS])


class TestLists(MatrixCase):
    def weights(self, b, *values):
        return list_block(b, *values)

    def test_position_list_is_a_weighted_sum(self):
        b = Build()
        p1, p2 = b.xyz(C_POSXYZ, (1, 2, 3)), b.xyz(C_POSXYZ, (10, 20, 30))
        lst = b.add(node(C_POSLIST, refs34(p1, p2, None, None, self.weights(b, 1.0, 0.5)),
                         leaf(0x1010, struct.pack("<i", 2)), leaf(0x1020, struct.pack("<i", 0))))
        n = b.node(b.prs(lst))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((6, 12, 18)))
        self.assertEqual(t.issues, [])

    def test_missing_weight_is_one(self):
        b = Build()
        p1, p2 = b.xyz(C_POSXYZ, (1, 2, 3)), b.xyz(C_POSXYZ, (10, 20, 30))
        lst = b.add(node(C_POSLIST, refs34(p1, p2, None, None, self.weights(b, 0.0)),
                         leaf(0x1010, struct.pack("<i", 2))))
        n = b.node(b.prs(lst))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((10, 20, 30)))
        self.assertEqual([(i.reason, i.class_id) for i in t.issues], [(ct.LIST_WEIGHT, classids.POSITION_LIST)])

    def test_count_without_0x1010(self):
        b = Build()
        lst = b.add(node(C_POSLIST, refs34(b.xyz(C_POSXYZ, (1, 0, 0)), b.xyz(C_POSXYZ, (0, 1, 0)), None,
                                           self.weights(b, 1.0, 1.0))))
        n = b.node(b.prs(lst))
        self.assertMatrix(b.transforms().world(n), ct.translation((1, 1, 0)))

    def test_sparse_slots_without_0x1010(self):
        b = Build()
        p1, p2 = b.xyz(C_POSXYZ, (1, 0, 0)), b.xyz(C_POSXYZ, (0, 1, 0))
        lst = b.add(node(C_POSLIST, refs34(p1, None, None, p2, self.weights(b, 1.0, 0.0, 0.0, 1.0))))
        n = b.node(b.prs(lst))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((1, 1, 0)))
        self.assertEqual(t.issues, [])

    def test_half_of_a_half_turn(self):
        half_turn = ct.quat_matrix((0, 0, 1, 0))
        quarter = ct._weighted_quat(half_turn, 0.5)  # +90 or -90 degrees about Z: both halve it
        self.assertMatrix(ct.multiply(quarter, quarter), half_turn)
        self.assertAlmostEqual(abs(quarter[0][1]), 1.0)
        h = math.radians(15)
        self.assertMatrix(ct._weighted_quat(ct.quat_matrix((math.sin(h), 0, 0, math.cos(h))), 2.0),
                          ct.quat_matrix((math.sin(2 * h), 0, 0, math.cos(2 * h))))
        self.assertEqual(ct._weighted_quat(ct.IDENTITY, 0.3), ct.IDENTITY)

    def test_rotation_list(self):
        b = Build()
        r1, r2 = b.euler((0, 0, math.pi / 2)), b.euler((math.pi / 2, 0, 0))
        lst = b.add(node(C_ROTLIST, refs34(r1, r2, None, None, self.weights(b, 1.0, 0.0)),
                         leaf(0x1010, struct.pack("<i", 2))))
        n = b.node(b.prs(None, lst))
        self.assertMatrix(b.transforms().world(n), ct.euler_matrix((0, 0, math.pi / 2)))
        b = Build()
        lst = b.add(node(C_ROTLIST, refs34(b.euler((0, 0, math.pi / 2)), None, None, self.weights(b, 0.5)),
                         leaf(0x1010, struct.pack("<i", 1))))
        n = b.node(b.prs(None, lst))
        self.assertMatrix(b.transforms().world(n), ct.euler_matrix((0, 0, math.pi / 4)))
        b = Build()  # each entry pre-rotates the ones before it: the second entry applies first
        r1, r2 = b.euler((0, 0, math.pi / 2)), b.euler((math.pi / 2, 0, 0))
        lst = b.add(node(C_ROTLIST, refs34(r1, r2, None, None, self.weights(b, 1.0, 1.0)),
                         leaf(0x1010, struct.pack("<i", 2))))
        n = b.node(b.prs(None, lst))
        expected = ct.multiply(ct.euler_matrix((math.pi / 2, 0, 0)), ct.euler_matrix((0, 0, math.pi / 2)))
        self.assertMatrix(b.transforms().world(n), expected)

    def test_scale_list(self):
        b = Build()
        lst = b.add(node(C_SCALELIST, refs34(b.bscale((2, 2, 2)), b.bscale((3, 1, 1)), None, None,
                                             self.weights(b, 1.0, 0.5)), leaf(0x1010, struct.pack("<i", 2))))
        n = b.node(b.prs(None, None, lst))
        self.assertMatrix(b.transforms().world(n), ct.scale_matrix((4, 2, 2)))

    def test_animated_weight(self):
        # an animated weight is a controller in the block's next reference slot (the corpus), a stored one a value
        b = Build()
        p1, p2 = b.xyz(C_POSXYZ, (1, 2, 3)), b.xyz(C_POSXYZ, (10, 20, 30))
        lst = b.add(node(C_POSLIST, refs34(p1, p2, None, None, self.weights(b, Anim(2.0), 0.5)),
                         leaf(0x1010, struct.pack("<i", 2))))
        n = b.node(b.prs(lst))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((7, 14, 21)))
        self.assertEqual(t.issues, [])

    def test_weights_not_stored_or_damaged(self):
        b = Build()
        p1, p2 = b.xyz(C_POSXYZ, (1, 2, 3)), b.xyz(C_POSXYZ, (10, 20, 30))
        head = leaf(0x0009, struct.pack("<IHIHI", 0x1E, 0, 0x55F03700, 1, 0))
        damaged = b.add(node(C_PB2, head, pb2_entry(0, 0x800, 0x921089, struct.pack("<BI", 0, 9) + b"\xc0")))
        lst = b.add(node(C_POSLIST, refs34(p1, p2, None, None, damaged), leaf(0x1010, struct.pack("<i", 2))))
        n = b.node(b.prs(lst))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((11, 22, 33)))
        self.assertEqual([i.reason.split(":")[0] for i in t.issues], [ct.LIST_BLOCK, ct.LIST_WEIGHT, ct.LIST_WEIGHT])
        b = Build()  # a block without its header: the list is damaged, the node at identity
        lst = b.add(node(C_POSLIST, refs34(b.xyz(C_POSXYZ, (1, 2, 3)), None, None, None, b.add(node(C_PB2))),
                         leaf(0x1010, struct.pack("<i", 1))))
        n = b.node(b.prs(lst))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertTrue(t.issues[0].reason.startswith(ct.DAMAGED), t.issues)


class TestListAverage(MatrixCase):
    """A list with Average on (parameter 1 of its block), against probes of 3ds Max 2020 (maxdrop-6n0.6.12)."""

    @staticmethod
    def build(b, cid, entries, weights, average=1):
        refs = list(entries) + [None] * (4 - len(entries)) + [list_block(b, *weights, average=average)]
        return b.add(node(cid, refs34(*refs), leaf(0x1010, struct.pack("<i", len(entries)))))

    def test_float_and_position_lists(self):
        for weights, want in (((0.5, 1.0), 14.666667), ((0.5, -0.5), 0.0), ((0.4,), 30.0), ((0.0, 0.0), 0.0)):
            with self.subTest(weights=weights):
                b = Build()
                lst = self.build(b, C_FLOATLIST, [b.flt(30.0), b.flt(7.0)][:len(weights)], weights)
                n = b.node(b.prs(b.add(node(C_POSXYZ, refs34(lst)))))
                t = b.transforms()
                self.assertMatrix(t.world(n), ct.translation((want, 0, 0)))
                self.assertEqual(t.issues, [])
        values = ((10, 20, 30), (-4, 8, 2), (7, -3, 5))
        for weights, want in (((0.2, 0.3, 0.7), (4.75, 3.583333, 8.416667)), ((0.5, -0.5), (0, 0, 0))):
            with self.subTest(weights=weights):
                b = Build()
                lst = self.build(b, C_POSLIST, [b.xyz(C_POSXYZ, v) for v in values[:len(weights)]], weights)
                n = b.node(b.prs(lst))
                self.assertMatrix(b.transforms().world(n), ct.translation(want))
        b = Build()  # Average off: the weighted sum
        lst = self.build(b, C_POSLIST, [b.xyz(C_POSXYZ, v) for v in values[:2]], (0.5, 1.0), average=0)
        n = b.node(b.prs(lst))
        self.assertMatrix(b.transforms().world(n), ct.translation((1, 18, 17)))

    def test_rotation_list(self):
        x30, y45, z80 = (math.radians(30), 0, 0), (0, math.radians(45), 0), (0, 0, math.radians(80))
        cases = [
            ((x30, z80), (1.0, 0.5), ((0.762534678, 0.63984257, 0.0956156477),
                                      (-0.63984257, 0.724034905, 0.257633239),
                                      (0.0956156477, -0.257633239, 0.961500287))),
            ((x30,), (0.5,), ((1, 0, 0), (0, 0.965925813, 0.258819073), (0, -0.258819073, 0.965925813))),
            ((x30, y45, z80), (0.5, 0.7, 0.2), ((0.859163105, 0.286063075, -0.424271971),
                                                (-0.25611937, 0.958210468, 0.127418965),
                                                (0.442991704, -0.000809386373, 0.896525383))),
            ((x30, z80), (0.5, 1.0), ct.euler_matrix(z80)),  # a weight of 1: the later entry alone
        ]
        for angles, weights, want in cases:
            with self.subTest(weights=weights):
                b = Build()
                lst = self.build(b, C_ROTLIST, [b.euler(a) for a in angles], weights)
                n = b.node(b.prs(None, lst))
                t = b.transforms()
                got = t.world(n)
                for r in range(3):
                    for c in range(3):
                        self.assertAlmostEqual(got[r][c], want[r][c], places=6)
                self.assertEqual(t.issues, [])

    def test_scale_list(self):
        for weights, want in (((0.5, 1.0), (4 / 3, 7 / 3, 2 / 3)), ((0.5, -0.5), (1, 1, 1))):
            with self.subTest(weights=weights):
                b = Build()
                lst = self.build(b, C_SCALELIST, [b.bscale((2, 1, 1)), b.bscale((1, 3, 0.5))], weights)
                n = b.node(b.prs(None, None, lst))
                t = b.transforms()
                self.assertMatrix(t.world(n), ct.scale_matrix(want))
                self.assertEqual(t.issues, [])
        b = Build()  # along a turned axis no rule fits: an issue
        lst = self.build(b, C_SCALELIST, [b.bscale((2, 0.5, 1), SW_AXIS), b.bscale((1, 3, 0.5))], (0.6, 0.3))
        n = b.node(b.prs(None, None, lst))
        t = b.transforms()
        t.world(n)
        self.assertEqual([i.reason for i in t.issues], [ct.LIST_AVERAGE])


SW_AXIS = (-0.167731255, -0.044943437, -0.254887044, 0.951251209)  # (eulerAngles 20 0 30) as a scale axis


class TestScaleListWeights(MatrixCase):
    def scale_list(self, entries, weights):
        b = Build()
        lst = b.add(node(C_SCALELIST, refs34(*[b.bscale(*e) for e in entries], None, None,
                                             list_block(b, *weights)), leaf(0x1010, struct.pack("<i", len(entries)))))
        n = b.node(b.prs(None, None, lst))
        t = b.transforms()
        return t.world(n), [i.reason for i in t.issues]

    def test_one_turned_entry(self):
        got, issues = self.scale_list((((2, 0.5, 1), SW_AXIS),), (0.6,))  # 3ds Max 2020: I + (S - I) * 0.6
        want = ((1.38377309, 0.374515593, 0.0482090786), (0.374515474, 0.951319873, -0.0835005045),
                (0.0482091159, -0.0835005045, 0.964906514))
        for r in range(3):
            for c in range(3):
                self.assertAlmostEqual(got[r][c], want[r][c], places=6)
        self.assertEqual(issues, [])

    def test_weight_after_a_turned_entry(self):
        _got, issues = self.scale_list((((2, 0.5, 1), SW_AXIS), ((1.5, 0.8, 2.5),)), (1.0, 0.4))
        self.assertEqual(issues, [ct.SCALE_LIST_WEIGHT])
        for entries, weights in (((((2, 0.5, 1), SW_AXIS), ((1.5, 0.8, 2.5),)), (0.4, 1.0)),  # the turned one first
                                 ((((2, 0.5, 1),), ((1.5, 0.8, 2.5),)), (0.6, 0.3)),  # plain scales
                                 ((((2, 0.5, 1), SW_AXIS), ((1, 1, 1),)), (1.0, 0.4))):  # a unit scale changes nothing
            with self.subTest(weights=weights):
                _got, issues = self.scale_list(entries, weights)
                self.assertEqual(issues, [])


class TestUnsupportedAndDamaged(MatrixCase):
    def test_unknown_transform_controller_is_identity(self):
        b = Build()
        other = b.add(node(C_UNKNOWN_M3, refs34(b.xyz(C_POSXYZ, (1, 2, 3)))))
        n = b.node(other)
        child = b.node(b.simple_prs((0, 0, 1)), parent=n)
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertMatrix(t.world(child), ct.translation((0, 0, 1)))
        self.assertEqual(t.issues, [ct.Issue(n, other, classids.SC_CTRL_MATRIX3, classdir.ClassId(0x7777, 0),
                                             ct.UNKNOWN_CLASS)])

    def test_unknown_sub_controller(self):
        b = Build()
        tcb = b.add(node(C_UNKNOWN_FLOAT, leaf(0x2501, struct.pack("<f", 9))))
        pos = b.add(node(C_POSXYZ, refs34(b.flt(1.0), tcb, b.flt(3.0))))
        n = b.node(b.prs(pos))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((1, 0, 3)))
        self.assertEqual([(i.node, i.controller, i.reason) for i in t.issues], [(n, tcb, ct.UNKNOWN_CLASS)])
        b = Build()  # a controller of the wrong kind in a slot
        n = b.node(b.prs(b.euler((1, 0, 0))))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertEqual([i.reason for i in t.issues], [ct.UNKNOWN_CLASS])

    def test_no_transform_controller(self):
        b = Build()
        n = b.node(None)
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertEqual(t.issues, [ct.Issue(n, None, None, None, ct.NO_CONTROLLER)])

    def test_cycle_and_depth(self):
        b = Build()
        lst = len(b.objects)
        b.add(node(C_POSLIST, refs34(lst), leaf(0x1010, struct.pack("<i", 1))))
        n = b.node(b.prs(lst))
        sibling = b.node(b.simple_prs((7, 0, 0)))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertEqual(len(t.issues), 1)
        self.assertTrue(t.issues[0].reason.startswith(ct.DAMAGED))
        self.assertEqual(t.issues[0].controller, lst)
        self.assertMatrix(t.world(sibling), ct.translation((7, 0, 0)))
        b = Build()
        inner = b.xyz(C_POSXYZ, (1, 0, 0))
        for _ in range(ct.MAX_DEPTH):
            inner = b.add(node(C_POSLIST, refs34(inner), leaf(0x1010, struct.pack("<i", 1))))
        n = b.node(b.prs(inner))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertIn("deeper", t.issues[0].reason)

    def test_bad_list_count(self):
        b = Build()
        lst = b.add(node(C_POSLIST, leaf(0x1010, struct.pack("<i", -3))))
        n = b.node(b.prs(lst))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertTrue(t.issues[0].reason.startswith(ct.DAMAGED))

    def test_short_payload(self):
        b = Build()
        bad = b.add(node(C_BSCALE, leaf(0x2505, b"\0" * 8)))
        n = b.node(b.prs(None, None, bad))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertTrue(t.issues[0].reason.startswith(ct.DAMAGED))

    def test_damaged_node_record(self):
        b = Build()
        top = b.node(b.simple_prs((1, 0, 0)))
        b.objects[top] = node(C_NODE, leaf(0x0960, struct.pack("<i", 0)), leaf(0x2034, b"abc"))
        child = b.node(b.simple_prs((0, 2, 0)), parent=top)
        t = b.transforms()
        self.assertEqual((t.world(top), t.offset(top)), (ct.IDENTITY, ct.IDENTITY))
        self.assertMatrix(t.world(child), ct.translation((0, 2, 0)))
        self.assertEqual([(i.node, i.controller) for i in t.issues], [(top, None)])
        self.assertTrue(t.issues[0].reason.startswith(ct.DAMAGED))

    def test_infinite_angle_and_weight(self):
        b = Build()
        n = b.node(b.simple_prs((1, 2, 3), (float("inf"), 0, 0)))
        sibling = b.node(b.simple_prs((7, 0, 0)))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertEqual([x.reason for x in t.issues], [ct.NON_FINITE])  # cos(inf) is NaN, not a math error
        self.assertMatrix(t.world(sibling), ct.translation((7, 0, 0)))
        b = Build()
        lst = b.add(node(C_ROTLIST, refs34(b.euler((0, 0, 1)), None, None,
                                           list_block(b, Anim(float("inf"))))))
        n = b.node(b.prs(None, lst))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertEqual([x.reason for x in t.issues], [ct.NON_FINITE])

    def test_infinite_weight_fails_an_outer_list_too(self):
        # the NaN matrix of an infinite weight, weighted again by an outer list, stays NaN at any weight: never
        # the identity of a zero quaternion
        for outer in (0.0, 0.5, 1.0, 2.0):
            b = Build()
            inner = b.add(node(C_ROTLIST, refs34(b.euler((0, 0, 1)), None, None,
                                                 list_block(b, Anim(float("inf"))))))
            lst = b.add(node(C_ROTLIST, refs34(inner, None, None, list_block(b, Anim(outer)))))
            n = b.node(b.prs(None, lst))
            sibling = b.node(b.simple_prs((7, 0, 0)))
            t = b.transforms()
            self.assertEqual(t.world(n), ct.IDENTITY, outer)
            self.assertEqual([x.reason for x in t.issues], [ct.NON_FINITE], outer)
            self.assertMatrix(t.world(sibling), ct.translation((7, 0, 0)))

    def test_shared_sub_controllers_are_evaluated_once(self):
        b = Build()
        inner = b.xyz(C_POSXYZ, (1, 0, 0))
        depth = ct.MAX_DEPTH - 3
        for _ in range(depth):  # each list holds the one below twice: 2^depth paths, no weights
            inner = b.add(node(C_POSLIST, refs34(inner, inner)))
        n = b.node(b.prs(inner))
        t = b.transforms()
        start = time.perf_counter()
        world = t.world(n)
        self.assertLess(time.perf_counter() - start, 2.0)
        self.assertEqual(world[3][0], 2.0 ** depth)
        self.assertEqual(len(t.issues), 2 * depth)  # one missing weight per entry, not per path

    def test_non_finite(self):
        b = Build()
        n = b.node(b.simple_prs((float("nan"), 0, 0)))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertEqual([i.reason for i in t.issues], [ct.NON_FINITE])
        b = Build()
        n = b.node(b.simple_prs(), pivot=((float("inf"), 0, 0), (0, 0, 0, 1), (1, 1, 1)))
        t = b.transforms()
        self.assertEqual(t.offset(n), ct.IDENTITY)
        self.assertEqual(t.offset(n), ct.IDENTITY)  # kept: reported once
        self.assertEqual([(i.node, i.controller, i.reason) for i in t.issues], [(n, None, ct.NON_FINITE)])

    def test_non_finite_stored_quaternion(self):
        # a NaN or infinite quaternion in the file is NON_FINITE, never the identity a zero quaternion reads as
        def tcb_rot(b, q):
            return b.prs(None, b.add(node(C_TCBROT, leaf(0x2504, struct.pack("<4f", *q)))))

        def tcb_scale(b, q):
            return b.prs(None, None, b.add(node(C_TCBSCALE, leaf(0x2505, struct.pack("<7f", 2, 2, 2, *q)))))

        def bezier_saved(b, q):
            return b.prs(None, None, b.bscale((2, 2, 2), q))

        def bezier_key(b, q):
            return b.prs(None, None, b.bscale(saved=False, keys=scale_keys((0, (2, 2, 2) + q))))

        def in_list(b, q):
            rot = b.add(node(C_TCBROT, leaf(0x2504, struct.pack("<4f", *q))))
            return b.prs(None, b.add(node(C_ROTLIST, refs34(rot, None, None, list_block(b, 0.5)))))

        for bad in (float("nan"), float("inf"), -float("inf")):
            for q in ((bad, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0, bad)):
                for name, make in (("tcb rotation", tcb_rot), ("tcb scale axis", tcb_scale),
                                   ("bezier scale axis", bezier_saved), ("bezier scale key axis", bezier_key),
                                   ("rotation list", in_list)):
                    with self.subTest(name, q=q):
                        b = Build()
                        n = b.node(make(b, q))
                        sibling = b.node(b.simple_prs((7, 0, 0)))
                        t = b.transforms()
                        self.assertEqual(t.world(n), ct.IDENTITY)
                        self.assertEqual([(x.node, x.reason) for x in t.issues], [(n, ct.NON_FINITE)])
                        self.assertMatrix(t.world(sibling), ct.translation((7, 0, 0)))
                with self.subTest("pivot rotation", q=q):
                    b = Build()
                    n = b.node(b.simple_prs((1, 0, 0)), pivot=((0, 0, 0), q, (1, 1, 1)))
                    t = b.transforms()
                    self.assertEqual(t.offset(n), ct.IDENTITY)
                    self.assertMatrix(t.world(n), ct.translation((1, 0, 0)))
                    self.assertEqual([(x.node, x.controller, x.reason) for x in t.issues], [(n, None, ct.NON_FINITE)])

    def test_zero_stored_quaternion_stays_identity(self):
        b = Build()
        zero = leaf(0x2504, struct.pack("<4f", 0, 0, 0, 0))
        n = b.node(b.prs(b.xyz(C_POSXYZ, (1, 0, 0)), b.add(node(C_TCBROT, zero))),
                   pivot=((0, 0, 0), (0, 0, 0, 0), (1, 1, 1)))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((1, 0, 0)))
        self.assertEqual(t.offset(n), ct.IDENTITY)
        self.assertEqual(t.issues, [])
        self.assertFalse(ct._finite(ct.quat_matrix((math.nan, 0, 0, 1))))
        self.assertFalse(ct._finite(ct.quat_matrix((0, 0, 0, math.inf))))


class TestMatrixAlone(MatrixCase):
    """controllers.matrix: a Matrix3 controller outside any node (a modifier's gizmo)."""

    @staticmethod
    def scene_of(b):
        return scene.Scene(node(0x2025, *b.objects), CLASSES)

    def test_prs(self):
        b = Build()
        tm = b.simple_prs((1, 2, 3), (0, 0, math.pi / 2), (2, 1, 1))
        m, issues = ct.matrix(self.scene_of(b), tm)
        self.assertMatrix(m, ((0, 2, 0, 0), (-1, 0, 0, 0), (0, 0, 1, 0), (1, 2, 3, 1)))
        self.assertEqual(issues, [])

    def test_damaged(self):
        b = Build()
        lst = len(b.objects)
        b.add(node(C_POSLIST, refs34(lst), leaf(0x1010, struct.pack("<i", 1))))
        tm = b.prs(lst)
        m, issues = ct.matrix(self.scene_of(b), tm)
        self.assertEqual(m, ct.IDENTITY)
        self.assertEqual([(i.node, i.controller) for i in issues], [(None, lst)])
        self.assertTrue(issues[0].reason.startswith(ct.DAMAGED), issues[0].reason)
        b = Build()
        inner = b.xyz(C_POSXYZ, (1, 0, 0))
        for _ in range(ct.MAX_DEPTH):
            inner = b.add(node(C_POSLIST, refs34(inner), leaf(0x1010, struct.pack("<i", 1))))
        tm = b.prs(inner)
        m, issues = ct.matrix(self.scene_of(b), tm)
        self.assertEqual(m, ct.IDENTITY)
        self.assertIn("deeper than %d below the controller" % ct.MAX_DEPTH, issues[0].reason)
        m, issues = ct.matrix(self.scene_of(b), len(b.objects))
        self.assertEqual(m, ct.IDENTITY)
        self.assertTrue(issues[0].reason.startswith(ct.DAMAGED), issues[0].reason)

    def test_non_finite_and_unknown(self):
        b = Build()
        tm = b.simple_prs((float("nan"), 0, 0))
        m, issues = ct.matrix(self.scene_of(b), tm)
        self.assertEqual((m, [i.reason for i in issues]), (ct.IDENTITY, [ct.NON_FINITE]))
        b = Build()
        tm = b.prs(None, b.add(node(C_TCBROT, leaf(0x2504, struct.pack("<4f", float("nan"), 0, 0, 1)))))
        m, issues = ct.matrix(self.scene_of(b), tm)
        self.assertEqual((m, [i.reason for i in issues]), (ct.IDENTITY, [ct.NON_FINITE]))
        b = Build()
        other = b.xyz(C_POSXYZ, (1, 0, 0))  # a position controller where a Matrix3 one belongs
        m, issues = ct.matrix(self.scene_of(b), other)
        self.assertEqual((m, [i.reason for i in issues]), (ct.IDENTITY, [ct.UNKNOWN_CLASS]))


if __name__ == "__main__":
    unittest.main()
