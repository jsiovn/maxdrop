# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/controllers.py, the transforms at frame 0: no Blender. The matrix conventions, synthetic
controller trees (PRS, the XYZ controllers, saved values and keys, lists with weights, unknown classes, damaged
input) and every committed fixture's world and object transforms against its 3ds Max oracle.

    python -I -m unittest discover tests
"""
import glob
import importlib
import json
import math
import os
import struct
import sys
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
TOLERANCE = 1e-4  # absolute, per element (the oracle prints 6 significant digits)


_PKG = "maxdrop_convert_test"  # the package the convert tests make: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
cfb = importlib.import_module(_PKG + ".reader.cfb")
chunks = importlib.import_module(_PKG + ".reader.chunks")
classdir = importlib.import_module(_PKG + ".reader.classdir")
classids = importlib.import_module(_PKG + ".reader.classids")
scene = importlib.import_module(_PKG + ".reader.scene")
ct = importlib.import_module(_PKG + ".reader.controllers")
pblock = importlib.import_module(_PKG + ".reader.pblock")
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
    (0x2001, 0, 0x9003, "Linear Float"), (0x2002, 0, 0x900B, "Linear Position"),
    (0x2003, 0, 0x900C, "Linear Rotation"), (0x2004, 0, 0x900D, "Linear Scale"), (0x442312, 0, 0x900B, "TCB Position"),
    (0x2009, 0, 0x900C, "Smooth Rotation"), (0x4B4B1000, 0, 0x9003, "Float List"), (0x7778, 0, 0x9003, "Some Float"),
]
(C_NODE, C_ROOT, C_PRS, C_POSXYZ, C_EULER, C_BSCALE, C_BFLOAT, C_PB2, C_POSLIST, C_ROTLIST, C_SCALELIST,
 C_LOOKAT, C_SCALEXYZ, C_TCBROT, C_BPOS, C_TCBSCALE, C_TCBFLOAT, C_LOOKAT_CONSTRAINT, C_UNKNOWN_M3,
 C_LINFLOAT, C_LINPOS, C_LINROT, C_LINSCALE, C_TCBPOS, C_SMOOTHROT, C_FLOATLIST, C_UNKNOWN_FLOAT) = \
    range(len(_CLASSES))
CLASSES = classdir.ClassDirectory.parse(b"".join(class_entry(*c) for c in _CLASSES))
# the keyframe classes as the controllers fixture shows them: (class index, key chunk, bytes per key, value floats)
KEYFRAMED = {"Linear Float": (C_LINFLOAT, 0x2511, 12, 1), "TCB Float": (C_TCBFLOAT, 0x2520, 40, 1),
             "Bezier Float": (C_BFLOAT, 0x2525, 28, 1), "Linear Position": (C_LINPOS, 0x2513, 20, 3),
             "TCB Position": (C_TCBPOS, 0x2521, 64, 3), "Bezier Position": (C_BPOS, 0x2526, 80, 3),
             "Linear Rotation": (C_LINROT, 0x2514, 24, 4), "TCB Rotation": (C_TCBROT, 0x2522, 92, 4),
             "Smooth Rotation": (C_SMOOTHROT, 0x2527, 88, 4), "Linear Scale": (C_LINSCALE, 0x2515, 36, 7),
             "TCB Scale": (C_TCBSCALE, 0x2523, 112, 7), "Bezier Scale": (C_BSCALE, 0x2528, 148, 7)}
VALUE_CHUNK = {1: 0x2501, 3: 0x2503, 4: 0x2504, 7: 0x2505}
FOREVER, AT_FRAME_30, NEVER = (-2 ** 31, 2 ** 31 - 1), (4800, 4800), (-2 ** 31, -2 ** 31)


def pb2_entry(pid, ptype, flags, body):
    return leaf(0x100E, struct.pack("<HIII", pid, ptype, flags, 0) + body)


def refs34(*indices):
    return leaf(0x2034, struct.pack("<%di" % len(indices), *(-1 if i is None else i for i in indices)))


def float_keys(*keys):
    """Bezier Float keys: (time, value) -> 28 bytes each."""
    return leaf(0x2525, b"".join(struct.pack("<iIf4f", t, 0x1690, v, 0, 0, 1 / 3, 1 / 3) for t, v in keys))


def scale_keys(*keys):
    """Bezier Scale keys: (time, (sx, sy, sz, qx, qy, qz, qw)) -> 148 bytes each."""
    return leaf(0x2528, b"".join(struct.pack("<iI7f28f", t, 0x1680, *v, *([0.0] * 28)) for t, v in keys))


def keys_of(name, *keys):
    """The key chunk of keyframe class name: (time, value tuple) per key, the rest of each record zero."""
    _c, cid, size, count = KEYFRAMED[name]
    return leaf(cid, b"".join(struct.pack("<iI%df" % count, t, 0, *v).ljust(size, b"\0") for t, v in keys))


def keyframed(b, name, saved=None, interval=None, keys=None):
    """An object of keyframe class name: its saved value (a tuple), the interval it holds for, a key chunk."""
    c, _cid, _size, count = KEYFRAMED[name]
    parts = [] if saved is None else [leaf(VALUE_CHUNK[count], struct.pack("<%df" % count, *saved))]
    if interval is not None:
        parts.append(leaf(0x2500, struct.pack("<ii", *interval)))
    if keys is not None:
        parts.append(keys)
    return b.add(node(c, *parts))


class Anim(float):
    """A list weight held by a Bezier Float controller (a table element tagged 0x80) instead of stored."""


def list_block(b, *weights):
    """A list controller's ParamBlock2 as 3ds Max 2020 writes it: parameter 0 the weights, a float table (an Anim is
    a controller in the block's next reference slot), parameter 1 a bool."""
    body, slots = struct.pack("<BI", 0, len(weights)), []
    for w in weights:
        if isinstance(w, Anim):
            body += b"\x80"
            slots.append(b.flt(float(w)))
        else:
            body += struct.pack("<Bf", 0xC0, w)
    entries = [pb2_entry(0, 0x800, 0x921089, body), pb2_entry(1, 4, 0x820000, struct.pack("<Bi", 0x40, 0))]
    head = leaf(0x0009, struct.pack("<IHIHI", 0x1E, 0, 0x55F03700, len(entries), 0))
    return b.add(node(C_PB2, *([refs34(*slots)] if slots else []), head, *entries))


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
    def world(name, **kw):
        """(world matrix, issues) of a node whose controller of keyframe class name is made with kw."""
        b = Build()
        obj = keyframed(b, name, **kw)
        count = KEYFRAMED[name][3]
        if count == 1:
            prs = b.prs(b.add(node(C_POSXYZ, refs34(obj))))
        else:
            prs = b.prs(*[obj if k == {3: 0, 4: 1, 7: 2}[count] else None for k in range(3)])
        n = b.node(prs)
        t = b.transforms()
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
        for name, (_c, _cid, _size, count) in KEYFRAMED.items():
            first, last = KEY_VALUES[count]
            with self.subTest(name):
                got, issues = self.world(name, saved=STALE[count], interval=AT_FRAME_30,
                                         keys=keys_of(name, (-1600, first), (6400, last)))  # 0 a fifth of the way
                if count == 4:
                    want = ct.quat_matrix(_rotz(42))
                else:
                    want = self.expected(name, tuple(a + (b - a) * 0.2 for a, b in zip(first, last)))
                self.assertMatrix(got, want)
                # Linear is exact; Bezier and TCB follow tangents that are not read
                self.assertEqual([i.reason for i in issues], [] if name.startswith("Linear") else
                                 [ct.KEYS_INTERPOLATED])

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

    def constrained(self, targets, weights, settings=None, pos=(-50, 50, 0), scale=(1, 1, 1), parent=0, up=None,
                    offsets=None):
        """A node whose PRS rotation is a LookAt Constraint; its block is the object right before the
        constraint. offsets: {chunk id: quaternion (4 floats) or raw bytes} of the constraint's own chunks."""
        block = len(self.objects)
        slots = list(targets) + ([up] if up is not None else [])
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


if __name__ == "__main__":
    unittest.main()
