# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the tests of maxdrop/reader/controllers/ share: the package loaded without Blender, the chunk
builders, the class directory of the synthetic scenes, Build and MatrixCase."""
import glob
import importlib
import os
import struct
import sys
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
    (0x2011, 0, 0x9005, "Bezier Color"),
]
(C_NODE, C_ROOT, C_PRS, C_POSXYZ, C_EULER, C_BSCALE, C_BFLOAT, C_PB2, C_POSLIST, C_ROTLIST, C_SCALELIST,
 C_LOOKAT, C_SCALEXYZ, C_TCBROT, C_BPOS, C_TCBSCALE, C_TCBFLOAT, C_LOOKAT_CONSTRAINT, C_UNKNOWN_M3,
 C_LINFLOAT, C_LINPOS, C_LINROT, C_LINSCALE, C_TCBPOS, C_SMOOTHROT, C_FLOATLIST, C_UNKNOWN_FLOAT, C_BCOLOR) = \
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
    """A list or constraint weight held by a Bezier Float controller (a table element tagged 0x80) instead of
    stored."""

    def __repr__(self):
        return "Anim(%r)" % float(self)


def list_block(b, *weights, average=0):
    """A list controller's ParamBlock2 as 3ds Max 2020 writes it: parameter 0 the weights, a float table (an Anim is
    a controller in the block's next reference slot), parameter 1 Average (an i32, 1 when on)."""
    body, slots = struct.pack("<BI", 0, len(weights)), []
    for w in weights:
        if isinstance(w, Anim):
            body += b"\x80"
            slots.append(b.flt(float(w)))
        else:
            body += struct.pack("<Bf", 0xC0, w)
    entries = [pb2_entry(0, 0x800, 0x921089, body), pb2_entry(1, 4, 0x820000, struct.pack("<Bi", 0x40, average))]
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

    def transforms(self, ticks_per_frame=160):
        s = scene.Scene(node(0x2025, *self.objects), CLASSES)
        s.ticks_per_frame = ticks_per_frame
        return ct.Transforms(s)


def rows12(m):
    return [m[r][c] for r in range(4) for c in range(3)]


class MatrixCase(unittest.TestCase):
    def assertMatrix(self, got, expected, places=6):
        self.assertEqual(len(got), len(expected))
        for r in range(len(expected)):
            for c in range(4):
                self.assertAlmostEqual(got[r][c], expected[r][c], places=places, msg="row %d col %d: %r" %
                                       (r, c, got))
