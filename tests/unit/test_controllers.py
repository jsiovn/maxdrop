# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/controllers.py, the transforms at frame 0: no Blender. The matrix conventions, synthetic
controller trees (PRS, the XYZ controllers, saved values and keys, lists with weights, unknown classes, damaged
input) and every committed fixture's world and object transforms against its 3ds Max oracle.

    python -I -m unittest discover tests
"""
import glob
import importlib.util
import json
import math
import os
import struct
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
TOLERANCE = 1e-4  # absolute, per element (the oracle prints 6 significant digits)


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
ct = _load("maxdrop_reader.controllers", os.path.join(_READER, "controllers.py"))
ChunkError = chunks.ChunkError


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def class_entry(a, b, superclass, name):
    return node(0x2040, leaf(0x2060, struct.pack("<iIII", -1, a, b, superclass)),
                leaf(0x2042, name.encode("utf-16-le")))


_CLASSES = [
    (1, 0, 0x1, "Node"), (2, 0, 0x1, "RootNode"), (0x2005, 0, 0x9008, "Position/Rotation/Scale"),
    (0x118F7E02, 0xFFEE238A, 0x900B, "Position XYZ"), (0x2012, 0, 0x900C, "Euler XYZ"),
    (0x2010, 0, 0x900D, "Bezier Scale"), (0x2007, 0, 0x9003, "Bezier Float"), (0x82, 0, 0x82, "ParamBlock2"),
    (0x4B4B1002, 0, 0x900B, "Position List"), (0x4B4B1003, 0, 0x900C, "Rotation List"),
    (0x4B4B1004, 0, 0x900D, "Scale List"), (0x2006, 0, 0x9008, "Look At"),
    (0x118F7C01, 0xFEEE238B, 0x900D, "ScaleXYZ"), (0x442313, 0, 0x900C, "TCB Rotation"),
    (0x2008, 0, 0x900B, "Bezier Position"), (0x442315, 0, 0x900D, "TCB Scale"), (0x442311, 0, 0x9003, "TCB Float"),
    (0x2021, 0, 0x900C, "LookAt Constraint"), (0x7777, 0, 0x9008, "Some Matrix3"),
]
(C_NODE, C_ROOT, C_PRS, C_POSXYZ, C_EULER, C_BSCALE, C_BFLOAT, C_PB2, C_POSLIST, C_ROTLIST, C_SCALELIST,
 C_LOOKAT, C_SCALEXYZ, C_TCBROT, C_BPOS, C_TCBSCALE, C_TCBFLOAT, C_LOOKAT_CONSTRAINT, C_UNKNOWN_M3) = \
    range(len(_CLASSES))
CLASSES = classdir.ClassDirectory.parse(b"".join(class_entry(*c) for c in _CLASSES))


def refs34(*indices):
    return leaf(0x2034, struct.pack("<%di" % len(indices), *(-1 if i is None else i for i in indices)))


def float_keys(*keys):
    """Bezier Float keys: (time, value) -> 28 bytes each."""
    return leaf(0x2525, b"".join(struct.pack("<iIf4f", t, 0x1690, v, 0, 0, 1 / 3, 1 / 3) for t, v in keys))


def scale_keys(*keys):
    """Bezier Scale keys: (time, (sx, sy, sz, qx, qy, qz, qw)) -> 148 bytes each."""
    return leaf(0x2528, b"".join(struct.pack("<iI7f28f", t, 0x1680, *v, *([0.0] * 28)) for t, v in keys))


class Build:
    """A synthetic Scene stream: object 0 is the RootNode; add() returns an object's index."""

    def __init__(self):
        self.objects = [node(C_ROOT)]

    def add(self, chunk):
        self.objects.append(chunk)
        return len(self.objects) - 1

    def flt(self, value=None, wrap=True, keys=None):
        parts = [] if value is None else [leaf(0x2501, struct.pack("<f", value))]
        if keys is not None:
            parts.append(keys)
        return self.add(node(C_BFLOAT, node(0x7127, *parts), leaf(0x7230)) if wrap else node(C_BFLOAT, *parts))

    def xyz(self, cid, values, default_wrap=True):
        return self.add(node(cid, refs34(*(self.flt(v, default_wrap) if v is not None else None
                                           for v in values))))

    def euler(self, angles, order=None):
        extra = [] if order is None else [leaf(0x1003, struct.pack("<i", order))]
        return self.add(node(C_EULER, refs34(*(self.flt(v) for v in angles)), *extra))

    def bscale(self, scale=(1, 1, 1), axis=(0, 0, 0, 1), keys=None, saved=True):
        parts = [leaf(0x2505, struct.pack("<7f", *scale, *axis))] if saved else []
        if keys is not None:
            parts.append(keys)
        return self.add(node(C_BSCALE, *parts))

    def prs(self, pos=None, rot=None, scale=None):
        return self.add(node(C_PRS, refs34(pos, rot, scale)))

    def simple_prs(self, pos=(0, 0, 0), euler=(0, 0, 0), scale=(1, 1, 1)):
        return self.prs(self.xyz(C_POSXYZ, pos), self.euler(euler), self.bscale(scale))

    def node(self, tm, parent=0, pivot=None):
        pairs = [] if tm is None else [(0, tm)]
        flat = [v for pair in pairs for v in pair]
        parts = [leaf(0x2035, struct.pack("<I" + "Ii" * len(pairs), 16, *flat)),
                 leaf(0x0960, struct.pack("<iI", parent, 0x800)), leaf(0x0962, "N".encode("utf-16-le"))]
        if pivot is not None:
            pos, rot, scl = pivot
            parts += [leaf(0x096A, struct.pack("<3f", *pos)), leaf(0x096B, struct.pack("<4f", *rot)),
                      leaf(0x096C, struct.pack("<7f", *scl, 0, 0, 0, 1))]
        return self.add(node(C_NODE, *parts))

    def transforms(self):
        return ct.Transforms(scene.Scene(node(0x2025, *self.objects), CLASSES))


def rows12(m):
    return [m[r][c] for r in range(4) for c in range(3)]


class MatrixCase(unittest.TestCase):
    def assertMatrix(self, got, expected, places=6):
        self.assertEqual(len(got), len(expected))
        for r in range(len(expected)):
            for c in range(4):
                self.assertAlmostEqual(got[r][c], expected[r][c], places=places, msg="row %d col %d: %r" %
                                       (r, c, got))


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
        self.assertAlmostEqual(pos[0], 3.0)
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
        b = Build()
        n = b.node(b.prs(None, b.euler(angles, order=7)))
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.euler_matrix(angles, 0))
        self.assertEqual([i.reason for i in t.issues], [ct.EULER_ORDER])


class TestLists(MatrixCase):
    def weights(self, b, *values):
        return b.add(node(C_PB2, refs34(*(b.flt(v) if v is not None else None for v in values))))

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
        lst = b.add(node(C_POSLIST, refs34(p1, p2, None, None, self.weights(b, 0.0, None)),
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
        lst = b.add(node(C_POSLIST, refs34(p1, None, None, p2, self.weights(b, 1.0, None, None, 1.0))))
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
        tcb = b.add(node(C_TCBFLOAT, leaf(0x2501, struct.pack("<f", 9))))
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
        self.assertEqual(len(t.issues), 1)
        self.assertTrue(t.issues[0].reason.startswith(ct.DAMAGED), t.issues[0].reason)
        self.assertMatrix(t.world(sibling), ct.translation((7, 0, 0)))
        b = Build()
        lst = b.add(node(C_ROTLIST, refs34(b.euler((0, 0, 1)), None, None,
                                           b.add(node(C_PB2, refs34(b.flt(float("inf"))))))))
        n = b.node(b.prs(None, lst))
        t = b.transforms()
        self.assertEqual(t.world(n), ct.IDENTITY)
        self.assertEqual(len(t.issues), 1)

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
        self.assertEqual(b.transforms().offset(n), ct.IDENTITY)


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
        other = b.xyz(C_POSXYZ, (1, 0, 0))  # a position controller where a Matrix3 one belongs
        m, issues = ct.matrix(self.scene_of(b), other)
        self.assertEqual((m, [i.reason for i in issues]), (ct.IDENTITY, [ct.UNKNOWN_CLASS]))


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


def pb2_entry(pid, ptype, flags, body):
    return leaf(0x100E, struct.pack("<HIII", pid, ptype, flags, 0) + body)


def constraint_block(owner, weights, targets=0, settings=None, slots=()):
    """A LookAt Constraint's ParamBlock2 as 3ds Max 2020 writes it: weights (floats), as many node elements as
    targets (no value: the block's reference slots, slots), {param id: int} settings; the up node (9) with a
    setting 9."""
    entries = [pb2_entry(0, 0x800, 0x121081, struct.pack("<BI", 0, len(weights)) +
                         b"".join(struct.pack("<Bf", 0xC0, w) for w in weights)),
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

    def constrained(self, targets, weights, settings=None, pos=(-50, 50, 0), scale=(1, 1, 1), parent=0, up=None):
        """A node whose PRS rotation is a LookAt Constraint; its block is the object right before the
        constraint."""
        block = len(self.objects)
        slots = list(targets) + ([up] if up is not None else [])
        settings = dict(settings or {})
        if up is not None:
            settings[9] = 1
        self.add(constraint_block(block + 1, weights, len(targets), settings, slots))
        lc = self.add(node(C_LOOKAT_CONSTRAINT, refs34(block)))
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

    def test_without_weight_or_with_an_offset(self):
        b = LookAtBuild()
        n = b.constrained([b.target((0, 0, 20))], [0.0])
        t = b.transforms()
        self.assertMatrix(t.world(n), ct.translation((-50, 50, 0)))
        self.assertEqual([i.reason for i in t.issues], [ct.CONSTRAINT_EMPTY])
        b = LookAtBuild()
        n = b.constrained([b.target((0, 0, 20))], [50.0], {2: 1})
        t = b.transforms()
        self.assertMatrix(t.world(n), MAX_CONSTRAINT[(0, False, 2, False, 2, 1)][:3] + ((-50, 50, 0, 1),), places=5)
        self.assertEqual([i.reason for i in t.issues], [ct.CONSTRAINT_OFFSET])
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


if __name__ == "__main__":
    unittest.main()
