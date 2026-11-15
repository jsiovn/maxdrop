# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transform controllers at frame 0: every node's local, world and object-offset matrix, as 3ds Max computes them.

    t = Transforms(scene)
    t.world(i)          # node i's world transform (node.transform in MAXScript, the pivot)
    t.offset(i)         # object offset: where the object sits relative to the pivot
    t.object_world(i)   # offset * world (node.objectTransform): object-space vertices times this = world
    t.issues            # Issue(node, controller, superclass, class_id, reason), in the order met

Matrices are 4x4 tuples of row tuples of floats (float64) in Max's row-vector convention: a point p becomes
p * M, row 4 holds the translation, and A * B applies A first. That is the layout of the oracle's `transform`.
Local = scale * rotation * position (PRS); world = local * parent world through the whole parent chain.
Negative scale is kept as it is (a mirrored node has a negative determinant).

Controllers are dispatched on (superclass, ClassId). A Bezier Float holds its value in 0x2501, directly or inside
0x7127, and its keys in 0x2525 (28 bytes each: i32 time, u32 flags, f32 value, then tangents); a Bezier Scale holds
0x2505 (3 x f32 scale, then the scale axis as a 4 x f32 quaternion) and keys in 0x2528 (148 bytes each, the value
at byte 8). The saved value is the one used, also beside keys: in the corpus it is what 3ds Max reports at frame 0
where the two differ (one key each), so several keys only add an issue (the saved value may be another frame's).
Without a saved value the keys are evaluated at time 0: the first key's value at or before it, the last key's
after it (out-of-range types are not read), linear between two keys (an issue: Max follows Bezier tangents).
Euler angles are radians; a Max quaternion (x, y, z, w) as stored is the conjugate of the usual one, so the
standard column-vector formula applied to it gives the row-vector matrix. List controllers keep their entry
count in 0x1010 and the entries at reference slots 0..n-1; their weights are the float controllers at reference
slots 0..n-1 of the list's ParamBlock2.

Anything not supported gives identity (zero position, no rotation, unit scale) for that controller and an Issue:
an unknown class (Look At until M4), keys of an unknown layout, a list weight without a controller, an Euler order
other than the six Tait-Bryan ones, a damaged controller (a reference cycle, a chain deeper than MAX_DEPTH, a
payload too short) or a non-finite result. The file comes from anywhere: one bad controller poisons only its own
node's local matrix. Classes without a committed fixture are 3ds Max SDK ids, named in docs/FORMAT.md as
unverified. No bpy, no mathutils, no numpy.
"""
import bisect
import collections
import math
import struct

from . import chunks, classids
from .classdir import ClassId

ChunkError = chunks.ChunkError

MAX_DEPTH = 32  # controllers below one node's transform controller
MAX_KEYS = 1 << 20  # per key chunk, read only without a saved value

IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))

UNKNOWN_CLASS = "unknown controller class"
KEYS_UNKNOWN = "keys of an unknown layout, value chunk used"
KEYS_INTERPOLATED = "between two keys, interpolated linearly"
ANIMATED = "several keys, the saved value used"
LIST_WEIGHT = "list weight without a controller, 1.0 used"
EULER_ORDER = "unsupported Euler order, XYZ used"
NO_CONTROLLER = "node without a transform controller"
DAMAGED = "damaged controller"
NON_FINITE = "non-finite transform"


class Issue(collections.namedtuple("Issue", "node controller superclass class_id reason")):
    """One thing the transforms could not follow: node and controller are object indices (controller None when
    the node has none), superclass and class_id those of the controller (None when unknown)."""
    __slots__ = ()


# Controllers no committed fixture has: 3ds Max SDK class ids (all with classB 0), unverified (docs/FORMAT.md).
LINEAR_POSITION = ClassId(0x00002002, 0)
LINEAR_ROTATION = ClassId(0x00002003, 0)
LINEAR_SCALE = ClassId(0x00002004, 0)
LOOK_AT = ClassId(0x00002006, 0)
BEZIER_POSITION = ClassId(0x00002008, 0)
BEZIER_ROTATION = ClassId(0x00002009, 0)
TCB_POSITION = ClassId(0x00442312, 0)
TCB_ROTATION = ClassId(0x00442313, 0)
TCB_SCALE = ClassId(0x00442315, 0)
SCALE_XYZ = ClassId(0x118F7C01, 0xFEEE238B)

_FLOAT_VALUE, _FLOAT_WRAP, _FLOAT_KEYS = 0x2501, 0x7127, 0x2525
_POINT_VALUE, _QUAT_VALUE, _SCALE_VALUE, _SCALE_KEYS = 0x2503, 0x2504, 0x2505, 0x2528
_EULER_ORDER = 0x1003
_LIST_COUNT = 0x1010
_KEY_IDS = range(0x2520, 0x2530)
_FLOAT_KEY = struct.Struct("<iIf")  # time, flags, value; 16 more bytes of tangents follow
_FLOAT_KEY_SIZE = 28
_SCALE_KEY_SIZE = 148
_TIME = struct.Struct("<i")


def multiply(a, b):
    """a * b in the row-vector convention: a applied first."""
    return tuple(tuple(a[r][0] * b[0][c] + a[r][1] * b[1][c] + a[r][2] * b[2][c] + a[r][3] * b[3][c]
                       for c in range(4)) for r in range(4))


def _mat3(m3, t=(0.0, 0.0, 0.0)):
    return (tuple(m3[0]) + (0.0,), tuple(m3[1]) + (0.0,), tuple(m3[2]) + (0.0,), tuple(t) + (1.0,))


def translation(p):
    return _mat3(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), p)


def quat_matrix(q):
    """The row-vector matrix of a Max quaternion (x, y, z, w) as stored; a zero quaternion gives identity."""
    x, y, z, w = (float(v) for v in q)
    n = x * x + y * y + z * z + w * w
    if not n > 1e-30:
        return IDENTITY
    s = 2.0 / n
    return _mat3(((1.0 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)),
                  (s * (x * y + z * w), 1.0 - s * (x * x + z * z), s * (y * z - x * w)),
                  (s * (x * z - y * w), s * (y * z + x * w), 1.0 - s * (x * x + y * y))))


def _axis(axis, angle):
    c, s = math.cos(angle), math.sin(angle)
    if axis == 0:
        return _mat3(((1.0, 0.0, 0.0), (0.0, c, s), (0.0, -s, c)))
    if axis == 1:
        return _mat3(((c, 0.0, -s), (0.0, 1.0, 0.0), (s, 0.0, c)))
    return _mat3(((c, s, 0.0), (-s, c, 0.0), (0.0, 0.0, 1.0)))


# Euler orders of Max's Euler controller (0x1003): the axis applied first comes first.
EULER_ORDERS = {0: (0, 1, 2), 1: (0, 2, 1), 2: (1, 2, 0), 3: (1, 0, 2), 4: (2, 0, 1), 5: (2, 1, 0)}


def euler_matrix(angles, order=0):
    """Rotation by angles (x, y, z) in radians; order 0 = XYZ: about X first, then Y, then Z."""
    m = IDENTITY
    for axis in EULER_ORDERS[order]:
        m = multiply(m, _axis(axis, angles[axis]))
    return m


def _transpose3(m):
    return _mat3(((m[0][0], m[1][0], m[2][0]), (m[0][1], m[1][1], m[2][1]), (m[0][2], m[1][2], m[2][2])))


def scale_matrix(scale, axis=(0.0, 0.0, 0.0, 1.0)):
    """Scale along the axes of the quaternion `axis` (a Max ScaleValue): Q^-1 * S * Q."""
    s = _mat3(((scale[0], 0.0, 0.0), (0.0, scale[1], 0.0), (0.0, 0.0, scale[2])))
    q = quat_matrix(axis)
    if q is IDENTITY:
        return s
    return multiply(multiply(_transpose3(q), s), q)


def _weighted_quat(m, weight):
    """The rotation of matrix m scaled by weight along its own axis, as a matrix."""
    if weight == 1.0:
        return m
    # rotation axis and angle of the row-vector matrix (its transpose is the column-vector one)
    trace = m[0][0] + m[1][1] + m[2][2]
    angle = math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0)))
    ax = (m[1][2] - m[2][1], m[2][0] - m[0][2], m[0][1] - m[1][0])
    n = math.sqrt(ax[0] * ax[0] + ax[1] * ax[1] + ax[2] * ax[2])
    if n < 1e-12:
        return IDENTITY if angle < 1e-6 or weight == 0.0 else m
    h = angle * weight / 2.0
    s = math.sin(h) / n
    # a row-vector matrix comes from the stored (conjugate) quaternion of its column-vector rotation
    return quat_matrix((-ax[0] * s, -ax[1] * s, -ax[2] * s, math.cos(h)))


def _finite(m):
    return all(math.isfinite(v) for row in m for v in row)


class _At:
    __slots__ = ("ev", "i")

    def __init__(self, ev, i):
        self.ev, self.i = ev, i

    def __enter__(self):
        ev, i = self.ev, self.i
        if i in ev.path or len(ev.path) >= MAX_DEPTH:
            ev.failed = i
            if i in ev.path:
                raise ChunkError("controller %d references itself" % i)
            raise ChunkError("controllers deeper than %d below node %d" % (MAX_DEPTH, ev.node))
        ev.path.append(i)

    def __exit__(self, exc_type, exc, tb):
        self.ev.path.pop()
        if exc_type is not None and self.ev.failed is None:
            self.ev.failed = self.i
        return False


class _Eval:
    """Evaluation of one node's controller tree, with its issues; references are followed with a depth and a
    cycle guard."""

    def __init__(self, scene, node, issues):
        self.scene, self.node, self.issues = scene, node, issues
        self.path = []
        self.failed = None

    def issue(self, i, reason):
        entry = self.scene.entry(i) if i is not None else None
        self.issues.append(Issue(self.node, i, entry.superclass if entry else None,
                                 entry.class_id if entry else None, reason))

    def at(self, i):
        """with self.at(i): evaluating controller i; failed is set to the innermost controller an error left."""
        return _At(self, i)

    def kind(self, i):
        entry = self.scene.entry(i)
        return (entry.superclass, entry.class_id) if entry is not None else (None, None)

    def _keys(self, i, holder, known):
        for child in holder.children:
            if child.id in _KEY_IDS and child.id != known:
                self.issue(i, KEYS_UNKNOWN)
                return

    def _saved_or_keyed(self, i, saved, keys, size, value_at):
        """The saved value when there is one (with an issue when keys animate it), else the keys at time 0;
        None without either."""
        if keys is None:
            return saved
        n, rest = divmod(keys.payload_size, size)
        if rest:
            raise ChunkError("object %d: keys %04X of %d bytes, not a multiple of %d" %
                             (i, keys.id, keys.payload_size, size))
        if saved is not None:
            if n > 1:
                self.issue(i, ANIMATED)
            return saved
        if n == 0:
            return None
        if n > MAX_KEYS:
            raise ChunkError("object %d: %d keys, more than %d" % (i, n, MAX_KEYS))
        view = keys.view()
        times = [_TIME.unpack_from(view, k * size)[0] for k in range(n)]
        if any(b < a for a, b in zip(times, times[1:])):
            raise ChunkError("object %d: key times out of order" % i)
        k = bisect.bisect_right(times, 0)  # times[k - 1] <= 0 < times[k]
        if k == 0:
            return value_at(0)
        if k == n or times[k - 1] == 0:
            return value_at(k - 1)
        self.issue(i, KEYS_INTERPOLATED)
        f = -times[k - 1] / (times[k] - times[k - 1])
        a, b = value_at(k - 1), value_at(k)
        if isinstance(a, float):
            return a + (b - a) * f
        return tuple(x + (y - x) * f for x, y in zip(a, b))

    # -- floats

    def scalar(self, i, default):
        if i is None:
            return default
        with self.at(i):
            sc, cid = self.kind(i)
            if sc == classids.SC_CTRL_FLOAT and cid == classids.BEZIER_FLOAT:
                return self._bezier_float(i, default)
            self.issue(i, UNKNOWN_CLASS)
            return default

    def _bezier_float(self, i, default):
        chunk = self.scene.chunk(i)
        if not chunk.container:
            return default
        saved = keys = None
        for holder in (chunk, chunk.first(_FLOAT_WRAP)):
            if holder is None or not holder.container:
                continue
            self._keys(i, holder, _FLOAT_KEYS)
            value = holder.first(_FLOAT_VALUE)
            if saved is None and value is not None:
                saved = float(value.unpack("<f")[0])
            keys = keys or holder.first(_FLOAT_KEYS)
        view = keys.view() if keys is not None else None
        value = self._saved_or_keyed(i, saved, keys, _FLOAT_KEY_SIZE,
                                     lambda k: float(_FLOAT_KEY.unpack_from(view, k * _FLOAT_KEY_SIZE)[2]))
        return default if value is None else value

    def _floats3(self, i, default):
        refs = self.scene.refs(i)
        return tuple(self.scalar(refs.get(k), default) for k in range(3))

    def _value(self, i, cid, count):
        chunk = self.scene.chunk(i)
        if not chunk.container:
            return None
        self._keys(i, chunk, None)
        value = chunk.first(cid)
        return None if value is None else tuple(float(v) for v in value.unpack("<%df" % count))

    # -- lists

    def _list(self, i):
        """[(entry index, weight)] of a list controller."""
        chunk = self.scene.chunk(i)
        refs = self.scene.refs(i)
        count = chunk.first(_LIST_COUNT) if chunk.container else None
        if count is not None:
            n = count.unpack("<i")[0]
        else:
            n = sum(1 for slot in refs if self.kind(refs[slot])[0] != classids.SC_PARAMETER_BLOCK2)
        if not 0 <= n <= len(self.scene):
            raise ChunkError("list controller %d: %d entries" % (i, n))
        block = next((r for r in refs.values() if self.kind(r)[0] == classids.SC_PARAMETER_BLOCK2), None)
        weights = self.scene.refs(block) if block is not None else {}
        out = []
        for k in range(n):
            entry = refs.get(k)
            if entry is None:
                continue
            weight = weights.get(k)
            if weight is None:
                self.issue(i, LIST_WEIGHT)
                w = 1.0
            else:
                with self.at(block):
                    w = self.scalar(weight, 1.0)
            out.append((entry, w))
        return out

    # -- position, rotation, scale

    def position(self, i):
        if i is None:
            return (0.0, 0.0, 0.0)
        with self.at(i):
            sc, cid = self.kind(i)
            if sc == classids.SC_CTRL_POSITION:
                if cid == classids.POSITION_XYZ:
                    return self._floats3(i, 0.0)
                if cid in (BEZIER_POSITION, TCB_POSITION, LINEAR_POSITION):
                    return self._value(i, _POINT_VALUE, 3) or (0.0, 0.0, 0.0)
                if cid == classids.POSITION_LIST:
                    total = [0.0, 0.0, 0.0]
                    for entry, w in self._list(i):
                        p = self.position(entry)
                        for k in range(3):
                            total[k] += w * p[k]
                    return tuple(total)
            self.issue(i, UNKNOWN_CLASS)
            return (0.0, 0.0, 0.0)

    def rotation(self, i):
        if i is None:
            return IDENTITY
        with self.at(i):
            sc, cid = self.kind(i)
            if sc == classids.SC_CTRL_ROTATION:
                if cid == classids.EULER_XYZ:
                    chunk = self.scene.chunk(i)
                    order = chunk.first(_EULER_ORDER) if chunk.container else None
                    order = order.unpack("<i")[0] if order is not None else 0
                    if order not in EULER_ORDERS:
                        self.issue(i, EULER_ORDER)
                        order = 0
                    return euler_matrix(self._floats3(i, 0.0), order)
                if cid in (TCB_ROTATION, LINEAR_ROTATION, BEZIER_ROTATION):
                    q = self._value(i, _QUAT_VALUE, 4)
                    return quat_matrix(q) if q is not None else IDENTITY
                if cid == classids.ROTATION_LIST:
                    # each entry pre-rotates what came before, as a relative controller does
                    m = IDENTITY
                    for entry, w in self._list(i):
                        m = multiply(_weighted_quat(self.rotation(entry), w), m)
                    return m
            self.issue(i, UNKNOWN_CLASS)
            return IDENTITY

    def scale(self, i):
        if i is None:
            return IDENTITY
        with self.at(i):
            sc, cid = self.kind(i)
            if sc == classids.SC_CTRL_SCALE:
                if cid == classids.BEZIER_SCALE:
                    return self._bezier_scale(i)
                if cid in (TCB_SCALE, LINEAR_SCALE):
                    v = self._value(i, _SCALE_VALUE, 7)
                    return scale_matrix(v[:3], v[3:]) if v is not None else IDENTITY
                if cid == SCALE_XYZ:
                    return scale_matrix(self._floats3(i, 1.0))
                if cid == classids.SCALE_LIST:
                    m = IDENTITY
                    for entry, w in self._list(i):
                        s = self.scale(entry)
                        if w != 1.0:
                            s = tuple(tuple(IDENTITY[r][c] + (s[r][c] - IDENTITY[r][c]) * w for c in range(4))
                                      for r in range(4))
                        m = multiply(s, m)
                    return m
            self.issue(i, UNKNOWN_CLASS)
            return IDENTITY

    def _bezier_scale(self, i):
        chunk = self.scene.chunk(i)
        if not chunk.container:
            return IDENTITY
        self._keys(i, chunk, _SCALE_KEYS)
        keys = chunk.first(_SCALE_KEYS)
        value = chunk.first(_SCALE_VALUE)
        saved = None
        if value is not None:
            saved = value.unpack("<7f") if value.payload_size >= 28 else value.unpack("<3f") + (0.0, 0.0, 0.0, 1.0)
        view = keys.view() if keys is not None else None
        v = self._saved_or_keyed(i, saved, keys, _SCALE_KEY_SIZE,
                                 lambda k: struct.unpack_from("<7f", view, k * _SCALE_KEY_SIZE + 8))
        return IDENTITY if v is None else scale_matrix(v[:3], v[3:])

    # -- the node's transform controller

    def matrix(self, i):
        with self.at(i):
            sc, cid = self.kind(i)
            if sc == classids.SC_CTRL_MATRIX3 and cid == classids.PRS:
                refs = self.scene.refs(i)
                rot = self.rotation(refs.get(1))
                rot_pos = _mat3([row[:3] for row in rot[:3]], self.position(refs.get(0)))
                return multiply(self.scale(refs.get(2)), rot_pos)
            self.issue(i, UNKNOWN_CLASS)
            return IDENTITY


class Transforms:
    """The matrices of a reader.scene.Scene's nodes at frame 0, computed on demand and kept."""

    def __init__(self, scene):
        self.scene = scene
        self.issues = []
        self._local = {}
        self._world = {}

    def local(self, i):
        """Node i's transform relative to its parent: scale * rotation * position."""
        m = self._local.get(i)
        if m is not None:
            return m
        ev = _Eval(self.scene, i, self.issues)
        try:
            node = self.scene.node(i)
        except ChunkError as exc:  # a damaged node record: identity, its children still placed
            ev.issue(None, "%s: %s" % (DAMAGED, exc))
            self._local[i] = IDENTITY
            return IDENTITY
        if node.tm is None:
            ev.issue(None, NO_CONTROLLER)
            m = IDENTITY
        else:
            mark = len(self.issues)
            try:
                m = ev.matrix(node.tm)
            except (ChunkError, IndexError, struct.error) as exc:
                del self.issues[mark:]
                bad = ev.failed if ev.failed is not None else node.tm
                ev.issue(bad, "%s: %s" % (DAMAGED, exc))
                m = IDENTITY
            if not _finite(m):
                ev.issue(node.tm, NON_FINITE)
                m = IDENTITY
        self._local[i] = m
        return m

    def world(self, i):
        """Node i's world transform: its local matrix times every parent's, up to the top level."""
        m = self._world.get(i)
        if m is not None:
            return m
        chain = []
        j = i
        while j is not None and j not in self._world:  # bounded: the scene's parents have no cycle
            chain.append(j)
            j = self.scene.parent(j)
        parent = self._world[j] if j is not None else IDENTITY
        for j in reversed(chain):
            parent = multiply(self.local(j), parent)
            self._world[j] = parent
        return self._world[i]

    def offset(self, i):
        """Node i's object offset: scale (along its axis) * rotation * position, from the node record (identity
        when that record is damaged)."""
        try:
            node = self.scene.node(i)
        except ChunkError:
            return IDENTITY
        m = multiply(multiply(scale_matrix(node.pivot_scale, node.pivot_scale_axis),
                              quat_matrix(node.pivot_rotation)), translation(node.pivot_position))
        return m if _finite(m) else IDENTITY

    def object_world(self, i):
        """offset * world: where node i's object-space vertices land in the world."""
        return multiply(self.offset(i), self.world(i))
