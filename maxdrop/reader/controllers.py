# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transform controllers at frame 0: every node's local, world and object-offset matrix, as 3ds Max computes them.

    t = Transforms(scene)
    t.world(i)          # node i's world transform (node.transform in MAXScript, the pivot)
    t.offset(i)         # object offset: where the object sits relative to the pivot
    t.object_world(i)   # offset * world (node.objectTransform): object-space vertices times this = world
    t.issues            # Issue(node, controller, superclass, class_id, reason), in the order met
    m, issues = matrix(scene, i)        # Matrix3 controller i alone (a modifier's gizmo); Issue.node is None

Matrices are 4x4 tuples of row tuples of floats (float64) in Max's row-vector convention: a point p becomes
p * M, row 4 holds the translation, and A * B applies A first. That is the layout of the oracle's `transform`.
Local = scale * rotation * position (PRS); world = local * parent world through the whole parent chain.
Negative scale is kept as it is (a mirrored node has a negative determinant).

Controllers are dispatched on (superclass, ClassId). A keyframe controller (Linear, Bezier or TCB Float, Position,
Rotation or Scale) saves its value at the time slider of the save in 0x2501 (float), 0x2503 (point), 0x2504
(quaternion) or 0x2505 (3 x f32 scale, then the scale axis as a 4 x f32 quaternion), directly or inside 0x7127,
with 0x2500, the interval that value holds for (forever without keys), and its keys in a chunk of its class
(_KEYFRAMED: i32 time, u32 flags, the value at byte 8, then tangents or TCB parameters). The saved value is used
when its interval holds time 0; otherwise the keys are evaluated at time 0: the first key's value at or before it,
the last key's after it (out-of-range types are not read), between two keys linear for a Linear controller
(rotation by slerp), linear with an issue for the others (Max follows their tangents). A saved value without an
interval is used as it is, with an issue when several keys animate it (it may be another frame's). Euler angles
are radians, the axis order (0x1003) 0 for XYZ and 100 + order for the others; a Max quaternion (x, y, z, w) as stored is the conjugate of the usual one, so the standard
column-vector formula applied to it gives the row-vector matrix. List controllers keep their entry count in 0x1010
and the entries at reference slots 0..n-1; their weights are parameter 0 of the list's ParamBlock2 (a float table:
stored values, or controllers where animated). A list sums its entries times their weights (Float and Position
List), multiplies I + (S - I) * weight (Scale List) or the rotations turned by their weights, a later entry first
(Rotation List).

A Look At controller (a Matrix3 controller: target cameras and lights) and a LookAt Constraint (a rotation
controller in a PRS) give the node's world matrix from the world positions of other nodes (the target, the
constraint's targets and up node): scale * aim frame * translation(P), P the position controller's value times the
parent's world matrix; the parent's rotation and scale do not reach the frame. The node's local matrix is that
world matrix times the parent's inverse, and its children follow the world matrix. look_frame() and
constraint_frame() say how a frame is aimed, look_at(i) describes a node's Look At controller. Every node of a
look-at cycle (one aimed at itself included) is damaged, whichever node is asked for first; a look-at that waits on
more than MAX_LOOK_AT_DEPTH others is damaged.

Anything not supported gives identity (zero position, no rotation, unit scale) for that controller and an Issue:
an unknown class (also a Look At or a constraint outside a node, as a modifier's gizmo, and a constraint anywhere
but a PRS's rotation), keys of an unknown layout, a list weight that is not stored, an Euler order other than
the six Tait-Bryan ones, a damaged controller (a reference cycle, a chain deeper than MAX_DEPTH, a payload too
short) or a non-finite result. The file comes from anywhere: one bad controller poisons only its own
node's local matrix. Every class read here is in a committed fixture (docs/FORMAT.md). No bpy, no mathutils, no
numpy.
"""
import bisect
import collections
import math
import struct

from . import chunks, classids, pblock
from .errors import MaxFileError

ChunkError = chunks.ChunkError

MAX_DEPTH = 32  # controllers below one node's transform controller
MAX_KEYS = 1 << 20  # per key chunk, read only without a saved value
MAX_LOOK_AT_DEPTH = 64  # nodes whose matrices wait on one another: a look-at's target aimed at another target...

IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))

UNKNOWN_CLASS = "unknown controller class"
KEYS_UNKNOWN = "keys of an unknown layout, not read"
KEYS_INTERPOLATED = "between two keys, interpolated linearly"
ANIMATED = "several keys beside a saved value without its interval, the saved value used"
LIST_WEIGHT = "list weight not stored, 1.0 used"
LIST_BLOCK = "damaged list weights, 1.0 used where unread"
EULER_ORDER = "unsupported Euler order, XYZ used"
NO_CONTROLLER = "node without a transform controller"
DAMAGED = "damaged controller"
NON_FINITE = "non-finite transform"
LOOK_AT_AXIS = "Look At axis out of range, Z used"
LOOK_AT_NODE = "look-at target or up node that is no node, none used"
LOOK_AT_PARENT = "look-at under a parent that cannot be inverted"
CONSTRAINT_EMPTY = "LookAt Constraint without a target of any weight, no rotation"
CONSTRAINT_OFFSET = "LookAt Constraint offset (Keep Initial Offset, Set Orientation) not applied"
CONSTRAINT_DEGENERATE = "LookAt Constraint that cannot be aimed (on its target, up along the view), no rotation"
CONSTRAINT_SETTING = "animated or damaged LookAt Constraint setting, its default used"
CONSTRAINT_BLOCK = "damaged LookAt Constraint parameters, the defaults used where unread"


class Issue(collections.namedtuple("Issue", "node controller superclass class_id reason")):
    """One thing the transforms could not follow: node and controller are object indices (controller None when
    the node has none), superclass and class_id those of the controller (None when unknown)."""
    __slots__ = ()


class LookAt(collections.namedtuple("LookAt", "target axis flip roll target_up")):
    """A node's Look At controller: target the target node's object index (None without one), axis 0, 1 or 2 (-X,
    -Y or -Z looks at the target), flip (+ that axis looks instead), roll in radians, target_up whether the
    target's Z axis is the up direction (else the world's)."""
    __slots__ = ()


_FLOAT_VALUE, _POINT_VALUE, _QUAT_VALUE, _SCALE_VALUE = 0x2501, 0x2503, 0x2504, 0x2505
_INTERVAL, _WRAP = 0x2500, 0x7127
_EULER_ORDER = 0x1003
_EULER_ORDER_BASE = 100  # 3ds Max 2020 saves XYZ as 0 and the other orders as 100 + order
_LIST_COUNT = 0x1010
_LIST_WEIGHTS = 0  # parameter of the list's ParamBlock2
_KEY_IDS = range(0x2510, 0x2530)
_KEY_VALUE = 8  # a key record: i32 time, u32 flags, then the value
_TIME = struct.Struct("<i")
_INTERVAL_FORMAT = "<ii"  # start and end time
# keyframe controllers: (superclass, ClassId) -> (value chunk, floats of the value, key chunk, bytes per key)
_KEYFRAMED = {
    (classids.SC_CTRL_FLOAT, classids.LINEAR_FLOAT): (_FLOAT_VALUE, 1, 0x2511, 12),
    (classids.SC_CTRL_FLOAT, classids.TCB_FLOAT): (_FLOAT_VALUE, 1, 0x2520, 40),
    (classids.SC_CTRL_FLOAT, classids.BEZIER_FLOAT): (_FLOAT_VALUE, 1, 0x2525, 28),
    (classids.SC_CTRL_POSITION, classids.LINEAR_POSITION): (_POINT_VALUE, 3, 0x2513, 20),
    (classids.SC_CTRL_POSITION, classids.TCB_POSITION): (_POINT_VALUE, 3, 0x2521, 64),
    (classids.SC_CTRL_POSITION, classids.BEZIER_POSITION): (_POINT_VALUE, 3, 0x2526, 80),
    (classids.SC_CTRL_ROTATION, classids.LINEAR_ROTATION): (_QUAT_VALUE, 4, 0x2514, 24),
    (classids.SC_CTRL_ROTATION, classids.TCB_ROTATION): (_QUAT_VALUE, 4, 0x2522, 92),
    (classids.SC_CTRL_ROTATION, classids.BEZIER_ROTATION): (_QUAT_VALUE, 4, 0x2527, 88),
    (classids.SC_CTRL_SCALE, classids.LINEAR_SCALE): (_SCALE_VALUE, 7, 0x2515, 36),
    (classids.SC_CTRL_SCALE, classids.TCB_SCALE): (_SCALE_VALUE, 7, 0x2523, 112),
    (classids.SC_CTRL_SCALE, classids.BEZIER_SCALE): (_SCALE_VALUE, 7, 0x2528, 148),
}
_LINEAR = frozenset((classids.LINEAR_FLOAT, classids.LINEAR_POSITION, classids.LINEAR_ROTATION,
                     classids.LINEAR_SCALE))
_LOOK_AXIS, _LOOK_FLIP, _LOOK_TARGET_UP = 0x0100, 0x0110, 0x0201
# the LookAt Constraint's ParamBlock2 (3 viewline length, 12 viewline length absolute: display only)
(_LC_WEIGHTS, _LC_TARGETS, _LC_RELATIVE, _LC_SET_ORIENTATION, _LC_AXIS, _LC_AXIS_FLIP, _LC_UP_AXIS, _LC_UP_WORLD,
 _LC_UP_NODE, _LC_SOURCE_UP, _LC_SOURCE_UP_FLIP, _LC_UP_CONTROL) = 0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 13
_TINY = 1e-12


def multiply(a, b):
    """a * b in the row-vector convention: a applied first."""
    return tuple(tuple(a[r][0] * b[0][c] + a[r][1] * b[1][c] + a[r][2] * b[2][c] + a[r][3] * b[3][c]
                       for c in range(4)) for r in range(4))


def _mat3(m3, t=(0.0, 0.0, 0.0)):
    return (tuple(m3[0]) + (0.0,), tuple(m3[1]) + (0.0,), tuple(m3[2]) + (0.0,), tuple(t) + (1.0,))


def translation(p):
    return _mat3(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), p)


_NAN_MATRIX = _mat3(((math.nan,) * 3,) * 3, (math.nan,) * 3)


def quat_matrix(q):
    """The row-vector matrix of a Max quaternion (x, y, z, w) as stored; a zero quaternion gives identity, a NaN or
    infinite one a matrix that is not finite, which the evaluation reports (NON_FINITE)."""
    x, y, z, w = (float(v) for v in q)
    n = x * x + y * y + z * z + w * w
    if not math.isfinite(n):
        return _NAN_MATRIX
    if n <= 1e-30:
        return IDENTITY
    s = 2.0 / n
    return _mat3(((1.0 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)),
                  (s * (x * y + z * w), 1.0 - s * (x * x + z * z), s * (y * z - x * w)),
                  (s * (x * z - y * w), s * (y * z + x * w), 1.0 - s * (x * x + y * y))))


def _cos_sin(angle):
    """(cos, sin) of angle; (nan, nan) when it is not finite, where math raises: the matrix made of them is not
    finite, which the evaluation reports (NON_FINITE)."""
    if not math.isfinite(angle):
        return math.nan, math.nan
    return math.cos(angle), math.sin(angle)


def _axis(axis, angle):
    c, s = _cos_sin(angle)
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
    # the standard quaternion of the column-vector rotation m^T (Shepperd's method)
    r = [[m[c][r] for c in range(3)] for r in range(3)]
    trace = r[0][0] + r[1][1] + r[2][2]
    if trace > 0.0:
        t = math.sqrt(trace + 1.0) * 2.0
        w, x, y, z = t / 4.0, (r[2][1] - r[1][2]) / t, (r[0][2] - r[2][0]) / t, (r[1][0] - r[0][1]) / t
    elif r[0][0] >= r[1][1] and r[0][0] >= r[2][2]:
        t = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2.0
        w, x, y, z = (r[2][1] - r[1][2]) / t, t / 4.0, (r[0][1] + r[1][0]) / t, (r[0][2] + r[2][0]) / t
    elif r[1][1] >= r[2][2]:
        t = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2.0
        w, x, y, z = (r[0][2] - r[2][0]) / t, (r[0][1] + r[1][0]) / t, t / 4.0, (r[1][2] + r[2][1]) / t
    else:
        t = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2.0
        w, x, y, z = (r[1][0] - r[0][1]) / t, (r[0][2] + r[2][0]) / t, (r[1][2] + r[2][1]) / t, t / 4.0
    if w < 0.0:
        w, x, y, z = -w, -x, -y, -z
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12:
        return IDENTITY
    h = math.atan2(n, w) * weight
    if not math.isfinite(h):  # an infinite weight or a NaN matrix, where math.sin raises
        return _NAN_MATRIX
    k = math.sin(h) / n
    # stored the Max way: the conjugate of the standard quaternion
    return quat_matrix((-x * k, -y * k, -z * k, math.cos(h)))


def _unit_quat(q):
    """q normalized; identity for a zero quaternion (as quat_matrix), None when it is not finite."""
    n = math.sqrt(sum(v * v for v in q))
    if not math.isfinite(n):
        return None
    return tuple(v / n for v in q) if n > 1e-30 else (0.0, 0.0, 0.0, 1.0)


def slerp(a, b, f):
    """The rotation a fraction f of the way from quaternion a to b, along the shorter arc; NaN when either is not
    finite (quat_matrix then gives a matrix that is not finite)."""
    a, b = _unit_quat(a), _unit_quat(b)
    if a is None or b is None or not math.isfinite(f):
        return (math.nan,) * 4
    d = sum(x * y for x, y in zip(a, b))
    if d < 0.0:
        b, d = tuple(-v for v in b), -d
    if d > 0.9999995:  # sin(theta) too small to divide by: the same rotation to float precision
        return tuple(x + (y - x) * f for x, y in zip(a, b))
    theta = math.acos(min(d, 1.0))
    s = math.sin(theta)
    wa, wb = math.sin((1.0 - f) * theta) / s, math.sin(f * theta) / s
    return tuple(wa * x + wb * y for x, y in zip(a, b))


def _interpolate(a, b, f, value_id):
    """The key value a fraction f of the way from a to b: components linearly, a quaternion (a rotation, a scale's
    axis) by slerp."""
    if value_id == _QUAT_VALUE:
        return slerp(a, b, f)
    lerp = tuple(x + (y - x) * f for x, y in zip(a, b))
    if value_id == _SCALE_VALUE:
        return lerp[:3] + slerp(a[3:], b[3:], f)
    return lerp


def _scale_value(chunk):
    """A 0x2505 ScaleValue: scale and axis, or a scale alone (12 bytes) with the identity axis; None without it."""
    if chunk is None:
        return None
    return chunk.unpack("<7f") if chunk.payload_size >= 28 else chunk.unpack("<3f") + (0.0, 0.0, 0.0, 1.0)


def _finite(m):
    return all(math.isfinite(v) for row in m for v in row)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _neg(v):
    return (-v[0], -v[1], -v[2])


def _unit(v):
    """v normalized; None when it has (almost) no length or is not finite."""
    n = math.sqrt(_dot(v, v))
    if not (n > _TINY and math.isfinite(n)):
        return None
    return (v[0] / n, v[1] / n, v[2] / n)


def _point(p, m):
    """Point p times matrix m."""
    return tuple(p[0] * m[0][c] + p[1] * m[1][c] + p[2] * m[2][c] + m[3][c] for c in range(3))


def _inverse(m):
    """The inverse of an affine matrix; None when its 3x3 part cannot be inverted."""
    a = m
    cof = ((a[1][1] * a[2][2] - a[1][2] * a[2][1], a[0][2] * a[2][1] - a[0][1] * a[2][2],
            a[0][1] * a[1][2] - a[0][2] * a[1][1]),
           (a[1][2] * a[2][0] - a[1][0] * a[2][2], a[0][0] * a[2][2] - a[0][2] * a[2][0],
            a[0][2] * a[1][0] - a[0][0] * a[1][2]),
           (a[1][0] * a[2][1] - a[1][1] * a[2][0], a[0][1] * a[2][0] - a[0][0] * a[2][1],
            a[0][0] * a[1][1] - a[0][1] * a[1][0]))
    det = a[0][0] * cof[0][0] + a[0][1] * cof[1][0] + a[0][2] * cof[2][0]
    if not (math.isfinite(det) and abs(det) > 1e-30):
        return None
    inv = tuple(tuple(v / det for v in row) for row in cof)
    return _mat3(inv, _neg(_point(m[3][:3], _mat3(inv))))


def look_frame(position, target, up=(0.0, 0.0, 1.0), axis=2, flip=False, roll=0.0):
    """The rotation rows (x, y, z) of a Look At controller at position aiming at target, as 3ds Max 2020 computes
    them: z points from the target to the position (-Z looks at it), x = up x z, y = z x x; flip turns that half
    round y (+Z looks), roll turns it about z, then axis 0 makes it (z, y, -x) and axis 1 (x, z, -y), so that -X or
    -Y looks. Degenerate: on the target z is +X; z along up gives x = +X."""
    z = _unit(_sub(position, target)) or (1.0, 0.0, 0.0)
    x = _unit(_cross(up, z)) or (1.0, 0.0, 0.0)
    y = _unit(_cross(z, x))
    if y is None:  # z along +-X as well (an up node of the target's along the view): any x across z
        y = _unit(_cross(z, (0.0, 1.0, 0.0)))
        x = _cross(y, z)
    if flip:
        x, z = _neg(x), _neg(z)
    if roll:
        c, s = _cos_sin(roll)
        x, y = (tuple(c * a + s * b for a, b in zip(x, y)), tuple(c * b - s * a for a, b in zip(x, y)))
    if axis == 0:
        return (z, y, _neg(x))
    if axis == 1:
        return (x, z, _neg(y))
    return (x, y, z)


def constraint_frame(position, target, up, axis=0, flip=False, source_up=2, source_flip=False):
    """The rotation rows of a LookAt Constraint at position: row axis points at target (away with flip), row
    source_up along up without its part along the view (negated with source_flip), the third row completes a
    right-handed frame. None when it cannot be aimed: on the target, up along the view, the two axes the same."""
    if axis == source_up or axis not in (0, 1, 2) or source_up not in (0, 1, 2):
        return None
    n = _unit(_sub(target, position))
    if n is None:
        return None
    s = _unit(_sub(up, tuple(_dot(up, n) * v for v in n)))
    if s is None:
        return None
    rows = [None, None, None]
    rows[axis] = _neg(n) if flip else n
    rows[source_up] = _neg(s) if source_flip else s
    t = 3 - axis - source_up
    rows[t] = _cross(rows[(t + 1) % 3], rows[(t + 2) % 3])
    return tuple(rows)


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
            raise ChunkError("controllers deeper than %d below %s" % (MAX_DEPTH, ev.where()))
        ev.path.append(i)

    def __exit__(self, exc_type, exc, tb):
        self.ev.path.pop()
        if exc_type is not None and self.ev.failed is None:
            self.ev.failed = self.i
        return False


class _Eval:
    """Evaluation of one node's controller tree, with its issues; references are followed with a depth and a
    cycle guard."""

    def __init__(self, scene, node, issues, transforms=None):
        self.scene, self.node, self.issues, self.transforms = scene, node, issues, transforms
        self.path = []
        self.failed = None
        self.memo = {}  # (kind, controller) -> value: a shared sub-controller is evaluated once per node
        self.world = False  # matrix() gave the node's world matrix (a look-at), not its local one
        self.look = None  # the LookAt of a Look At controller node

    def where(self):
        return "node %d" % self.node if self.node is not None else "the controller"

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

    def _keyframe(self, i):
        """Keyframe controller i's value at time 0 as a tuple of floats; None without a saved value or keys."""
        sc, cid = self.kind(i)
        value_id, count, key_id, size = _KEYFRAMED[(sc, cid)]
        chunk = self.scene.chunk(i)
        if not chunk.container:
            return None
        saved = interval = keys = None
        for holder in (chunk, chunk.first(_WRAP)):
            if holder is None or not holder.container:
                continue
            self._keys(i, holder, key_id)
            value = holder.first(value_id)
            if saved is None and value is not None:
                saved = _scale_value(value) if value_id == _SCALE_VALUE else value.unpack("<%df" % count)
                held = holder.first(_INTERVAL)
                interval = held.unpack(_INTERVAL_FORMAT) if held is not None else None
            keys = keys or holder.first(key_id)
        if keys is None or saved is not None and interval is not None and interval[0] <= 0 <= interval[1]:
            return saved
        n, rest = divmod(keys.payload_size, size)
        if saved is not None and (rest or n == 0 or interval is None):
            if rest:
                self.issue(i, KEYS_UNKNOWN)
            elif n > 1:
                self.issue(i, ANIMATED)
            return saved
        if rest:
            raise ChunkError("object %d: keys %04X of %d bytes, not a multiple of %d" %
                             (i, keys.id, keys.payload_size, size))
        if n == 0:
            return None
        if n > MAX_KEYS:
            raise ChunkError("object %d: %d keys, more than %d" % (i, n, MAX_KEYS))
        view = keys.view()
        fmt = "<%df" % count

        def value_at(k):
            return struct.unpack_from(fmt, view, k * size + _KEY_VALUE)

        times = [_TIME.unpack_from(view, k * size)[0] for k in range(n)]
        if any(b < a for a, b in zip(times, times[1:])):
            raise ChunkError("object %d: key times out of order" % i)
        k = bisect.bisect_right(times, 0)  # times[k - 1] <= 0 < times[k]
        if k == 0:
            return value_at(0)
        if k == n or times[k - 1] == 0:
            return value_at(k - 1)
        if cid not in _LINEAR:
            self.issue(i, KEYS_INTERPOLATED)
        return _interpolate(value_at(k - 1), value_at(k), -times[k - 1] / (times[k] - times[k - 1]), value_id)

    def scalar(self, i, default):
        if i is None:
            return default
        key = ("scalar", i, default)
        if key not in self.memo:
            self.memo[key] = self._scalar(i, default)
        return self.memo[key]

    def _scalar(self, i, default):
        with self.at(i):
            sc, cid = self.kind(i)
            if (sc, cid) in _KEYFRAMED and sc == classids.SC_CTRL_FLOAT:
                value = self._keyframe(i)
                return default if value is None else float(value[0])
            if sc == classids.SC_CTRL_FLOAT and cid == classids.FLOAT_LIST:
                total = 0.0
                for entry, w in self._list(i):
                    total += w * self.scalar(entry, default)
                return total
            self.issue(i, UNKNOWN_CLASS)
            return default

    def _floats3(self, i, default):
        refs = self.scene.refs(i)
        return tuple(self.scalar(refs.get(k), default) for k in range(3))

    def _weights(self, i, refs):
        """(block, weights) of list controller i: parameter 0 of its ParamBlock2, each element a number or an
        Animated; (None, []) without a block."""
        block = next((r for r in refs.values() if self.kind(r)[0] == classids.SC_PARAMETER_BLOCK2), None)
        if block is None:
            return None, []
        pb = pblock.ParamBlock2.from_chunk(self.scene.chunk(block), self.scene.refs(block), refs, len(self.scene),
                                           self.kind(i))
        if pb.issues:  # a damaged entry reads as missing: weight 1.0
            self.issue(i, "%s: %s" % (LIST_BLOCK, pb.issues[0]))
        weights = pb.value(_LIST_WEIGHTS, [])
        return block, weights if isinstance(weights, list) else [weights]

    def _list(self, i):
        """[(entry index, weight)] of a list controller."""
        chunk = self.scene.chunk(i)
        refs = self.scene.refs(i)
        count = chunk.first(_LIST_COUNT) if chunk.container else None
        if count is not None:
            n = count.unpack("<i")[0]
            if not 0 <= n <= len(self.scene):
                raise ChunkError("list controller %d: %d entries" % (i, n))
            slots = range(n)
        else:
            slots = sorted(k for k, r in refs.items() if self.kind(r)[0] != classids.SC_PARAMETER_BLOCK2)
        block, weights = self._weights(i, refs)
        out = []
        for k in slots:
            entry = refs.get(k)
            if entry is None:
                continue
            w = weights[k] if k < len(weights) else None
            if isinstance(w, pblock.Animated) and w.index is not None:
                with self.at(block):
                    w = self.scalar(w.index, 1.0)
            if isinstance(w, bool) or not isinstance(w, (int, float)):
                self.issue(i, LIST_WEIGHT)
                w = 1.0
            out.append((entry, float(w)))
        return out

    def position(self, i):
        if i is None:
            return (0.0, 0.0, 0.0)
        key = ("position", i)
        if key not in self.memo:
            self.memo[key] = self._position(i)
        return self.memo[key]

    def _position(self, i):
        with self.at(i):
            sc, cid = self.kind(i)
            if sc == classids.SC_CTRL_POSITION:
                if cid == classids.POSITION_XYZ:
                    return self._floats3(i, 0.0)
                if (sc, cid) in _KEYFRAMED:
                    return self._keyframe(i) or (0.0, 0.0, 0.0)
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
        key = ("rotation", i)
        if key not in self.memo:
            self.memo[key] = self._rotation(i)
        return self.memo[key]

    def _rotation(self, i):
        with self.at(i):
            sc, cid = self.kind(i)
            if sc == classids.SC_CTRL_ROTATION:
                if cid == classids.EULER_XYZ:
                    chunk = self.scene.chunk(i)
                    order = chunk.first(_EULER_ORDER) if chunk.container else None
                    order = order.unpack("<i")[0] if order is not None else 0
                    if order >= _EULER_ORDER_BASE:
                        order -= _EULER_ORDER_BASE
                    if order not in EULER_ORDERS:
                        self.issue(i, EULER_ORDER)
                        order = 0
                    return euler_matrix(self._floats3(i, 0.0), order)
                if (sc, cid) in _KEYFRAMED:
                    q = self._keyframe(i)
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
        key = ("scale", i)
        if key not in self.memo:
            self.memo[key] = self._scale(i)
        return self.memo[key]

    def _scale(self, i):
        with self.at(i):
            sc, cid = self.kind(i)
            if sc == classids.SC_CTRL_SCALE:
                if (sc, cid) in _KEYFRAMED:
                    v = self._keyframe(i)
                    return scale_matrix(v[:3], v[3:]) if v is not None else IDENTITY
                if cid == classids.SCALE_XYZ:
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

    def matrix(self, i):
        with self.at(i):
            sc, cid = self.kind(i)
            in_node = self.transforms is not None and self.node is not None
            if in_node and sc == classids.SC_CTRL_MATRIX3 and cid == classids.LOOK_AT:
                return self._look_at(i)
            if sc == classids.SC_CTRL_MATRIX3 and cid == classids.PRS:
                refs = self.scene.refs(i)
                if in_node and refs.get(1) is not None and \
                        self.kind(refs[1]) == (classids.SC_CTRL_ROTATION, classids.LOOKAT_CONSTRAINT):
                    return self._constrained(refs)
                rot = self.rotation(refs.get(1))
                rot_pos = _mat3([row[:3] for row in rot[:3]], self.position(refs.get(0)))
                return multiply(self.scale(refs.get(2)), rot_pos)
            self.issue(i, UNKNOWN_CLASS)
            return IDENTITY

    def _node_world(self, i, j):
        """The world matrix of node j, which controller i aims with; None when j is empty or no node (an issue)."""
        if j is None:
            return None
        if not self.scene.is_a(j, classids.SC_BASENODE, classids.NODE):
            self.issue(i, LOOK_AT_NODE)
            return None
        return self.transforms.world(j)

    def _world_position(self, i):
        """Position controller i's value placed by the node's parent: where the node is in the world."""
        return _point(self.position(i), self.transforms.parent_world(self.node))

    def _look_at(self, i):
        # the parent's scale is intentionally dropped: 3ds Max's Look At frame is absolute (_constrained keeps it)
        chunk = self.scene.chunk(i)
        refs = self.scene.refs(i)
        axis, flip, target_up = 2, False, False
        if chunk.container:
            value = chunk.first(_LOOK_AXIS)
            if value is not None:
                axis = value.unpack("<I")[0]
            flip = chunk.first(_LOOK_FLIP) is not None
            value = chunk.first(_LOOK_TARGET_UP)
            target_up = value is not None and value.unpack("<B")[0] != 0
        if axis not in (0, 1, 2):
            self.issue(i, LOOK_AT_AXIS)
            axis = 2
        position = self._world_position(refs.get(1))
        target = refs.get(0)
        tw = self._node_world(i, target)
        if tw is None:
            target = None  # 3ds Max aims at the world origin then
        up = (_unit(tw[2][:3]) if tw is not None and target_up else None) or (0.0, 0.0, 1.0)
        roll = self.scalar(refs.get(2), 0.0)
        frame = look_frame(position, tw[3][:3] if tw is not None else (0.0, 0.0, 0.0), up, axis, flip, roll)
        self.world = True
        self.look = LookAt(target, axis, flip, roll, target_up)
        return multiply(self.scale(refs.get(3)), _mat3(frame, position))

    def _constrained(self, refs):
        """A PRS whose rotation is a LookAt Constraint: the world matrix. Unlike a Look At controller's, its
        scale is relative: the parent's (the lengths of its rows) still scales it."""
        position = self._world_position(refs.get(0))
        with self.at(refs[1]):
            frame = self._constraint(refs[1], position)
        self.world = True
        parent = self.transforms.parent_world(self.node)
        inherited = scale_matrix([math.sqrt(_dot(row[:3], row[:3])) for row in parent[:3]])
        rotation = _mat3(frame, position) if frame is not None else translation(position)
        return multiply(multiply(self.scale(refs.get(2)), inherited), rotation)

    def _setting(self, c, pb, pid, default):
        """An int or bool setting of constraint c's block; its default (and an issue) when animated or damaged."""
        value = pb.get(pid)
        if value is None:
            return default
        if isinstance(value, (int, float)) and math.isfinite(value):
            return int(value)
        self.issue(c, CONSTRAINT_SETTING)
        return default

    def _constraint(self, c, position):
        """The frame of LookAt Constraint c at position, None (and an issue) when it has none."""
        block = self.scene.refs(c).get(0)
        if block is None or self.kind(block)[0] != classids.SC_PARAMETER_BLOCK2:
            self.issue(c, CONSTRAINT_EMPTY)
            return None
        pb = pblock.ParamBlock2.from_chunk(self.scene.chunk(block), self.scene.refs(block), self.scene.refs(c),
                                           len(self.scene), self.kind(c))
        if pb.issues:  # a damaged entry reads as missing: its default is used
            self.issue(c, "%s: %s" % (CONSTRAINT_BLOCK, pb.issues[0]))
        if self._setting(c, pb, _LC_RELATIVE, 0) or self._setting(c, pb, _LC_SET_ORIENTATION, 0):
            self.issue(c, CONSTRAINT_OFFSET)
        weights = pb.value(_LC_WEIGHTS, [])
        weights = weights if isinstance(weights, list) else [weights]
        targets = pb.value(_LC_TARGETS, [])
        targets = targets if isinstance(targets, list) else [targets]
        total, point = 0.0, [0.0, 0.0, 0.0]
        for k, ref in enumerate(targets):
            w = weights[k] if k < len(weights) else None
            if isinstance(w, pblock.Animated):
                w = self.scalar(w.index, 1.0)
            if not (isinstance(w, (int, float)) and math.isfinite(w)):
                self.issue(c, CONSTRAINT_SETTING)
                w = 1.0
            tw = self._node_world(c, ref.index if isinstance(ref, pblock.Reference) else None)
            if tw is None or w == 0.0:
                continue
            total += w
            for a in range(3):
                point[a] += w * tw[3][a]
        if not abs(total) > _TINY:
            self.issue(c, CONSTRAINT_EMPTY)
            return None
        target = tuple(v / total for v in point)
        up_axis = self._setting(c, pb, _LC_UP_AXIS, 2)
        if up_axis not in (0, 1, 2):
            self.issue(c, CONSTRAINT_SETTING)
            up_axis = 2
        up_node = IDENTITY  # the world: its axes, its origin
        if not self._setting(c, pb, _LC_UP_WORLD, 1):
            ref = pb.get(_LC_UP_NODE)
            j = ref.index if isinstance(ref, pblock.Reference) else None
            if j is None:
                self.issue(c, LOOK_AT_NODE)
            up_node = self._node_world(c, j) or IDENTITY
        if self._setting(c, pb, _LC_UP_CONTROL, 1):  # axis alignment
            up = up_node[up_axis][:3]
        else:  # the up axis looks at the up node
            up = _sub(up_node[3][:3], position)
        frame = constraint_frame(position, target, up, self._setting(c, pb, _LC_AXIS, 0),
                                 bool(self._setting(c, pb, _LC_AXIS_FLIP, 0)), self._setting(c, pb, _LC_SOURCE_UP, 2),
                                 bool(self._setting(c, pb, _LC_SOURCE_UP_FLIP, 0)))
        if frame is None:
            self.issue(c, CONSTRAINT_DEGENERATE)
        return frame


class Transforms:
    """The matrices of a reader.scene.Scene's nodes at frame 0, computed on demand and kept."""

    def __init__(self, scene):
        self.scene = scene
        self.issues = []
        self._local = {}
        self._world = {}
        self._offset = {}
        self._direct = {}  # node -> world matrix of a look-at node, which its local matrix only approximates
        self._look = {}  # node -> LookAt
        self._busy = []  # nodes whose local matrix is being computed: a look-at waits on other nodes
        self._cycle = set()  # nodes found on a look-at cycle: each one is damaged, not only where it closed

    def local(self, i):
        """Node i's transform relative to its parent: scale * rotation * position (a look-at node: its world
        matrix times the parent's inverse)."""
        m = self._local.get(i)
        if m is not None:
            return m
        if i in self._busy:  # only reached from a look-at below local(i): every node from i on waits on i
            self._cycle.update(self._busy[self._busy.index(i):])
            raise ChunkError("node %d: its look-at depends on itself" % i)
        if len(self._busy) >= MAX_LOOK_AT_DEPTH:
            raise ChunkError("look-at nodes waiting on more than %d others" % MAX_LOOK_AT_DEPTH)
        self._busy.append(i)
        try:
            m = self._evaluate(i)
        finally:
            self._busy.pop()
        self._local[i] = m
        return m

    def _evaluate(self, i):
        ev = _Eval(self.scene, i, self.issues, self)
        try:
            node = self.scene.node(i)
        except ChunkError as exc:  # a damaged node record: identity, its children still placed
            ev.issue(None, "%s: %s" % (DAMAGED, exc))
            return IDENTITY
        if node.tm is None:
            ev.issue(None, NO_CONTROLLER)
            return IDENTITY
        mark = len(self.issues)
        try:
            m = ev.matrix(node.tm)
            if i in self._cycle:  # it completed, aimed at a node the cycle left at identity
                raise ChunkError("node %d: its look-at depends on itself" % i)
            if ev.world and _finite(m):
                inverse = _inverse(self.parent_world(i))
                if inverse is None:
                    ev.issue(node.tm, LOOK_AT_PARENT)
                    return IDENTITY
                world, m = m, multiply(m, inverse)
                if _finite(m):
                    self._direct[i] = world
        except (MaxFileError, OverflowError) as exc:  # anything else is a defect: the fuzz harness sees it
            # this node's issues only: a look-at may have evaluated other nodes, whose issues stay
            self.issues[mark:] = [x for x in self.issues[mark:] if x.node != i]
            bad = ev.failed if ev.failed is not None else node.tm
            ev.issue(bad, "%s: %s" % (DAMAGED, exc))
            return IDENTITY
        if not _finite(m):
            ev.issue(node.tm, NON_FINITE)
            return IDENTITY
        if ev.look is not None:
            self._look[i] = ev.look
        return m

    def parent_world(self, i):
        """The world matrix of node i's parent, identity at the top level."""
        p = self.scene.parent(i)
        return self.world(p) if p is not None else IDENTITY

    def look_at(self, i):
        """The LookAt of node i's Look At controller; None when its controller is none or cannot be evaluated."""
        self.local(i)
        return self._look.get(i)

    def world(self, i):
        """Node i's world transform: its local matrix times every parent's, up to the top level (a look-at node:
        the world matrix its controller gives)."""
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
            local = self.local(j)  # a look-at may have computed this world matrix meanwhile
            parent = self._direct.get(j) or self._world.get(j) or multiply(local, parent)
            self._world[j] = parent
        return self._world[i]

    def offset(self, i):
        """Node i's object offset: scale (along its axis) * rotation * position, from the node record (identity
        when that record is damaged; identity and an issue when it is not finite)."""
        m = self._offset.get(i)
        if m is not None:
            return m
        try:
            node = self.scene.node(i)
            m = multiply(multiply(scale_matrix(node.pivot_scale, node.pivot_scale_axis),
                                  quat_matrix(node.pivot_rotation)), translation(node.pivot_position))
        except ChunkError:
            m = IDENTITY
        if not _finite(m):
            self.issues.append(Issue(i, None, None, None, NON_FINITE))
            m = IDENTITY
        self._offset[i] = m
        return m

    def object_world(self, i):
        """offset * world: where node i's object-space vertices land in the world."""
        return multiply(self.offset(i), self.world(i))


def matrix(scene, i):
    """(the matrix of Matrix3 controller i at frame 0, issues), outside any node: a modifier's gizmo. The same
    rules as a node's local matrix: identity and an issue (node None) when it cannot be evaluated."""
    issues = []
    ev = _Eval(scene, None, issues)
    if not 0 <= i < len(scene):
        issues.append(Issue(None, None, None, None, "%s: object %d past the scene" % (DAMAGED, i)))
        return IDENTITY, issues
    try:
        m = ev.matrix(i)
    except (MaxFileError, OverflowError) as exc:
        del issues[:]
        ev.issue(ev.failed if ev.failed is not None else i, "%s: %s" % (DAMAGED, exc))
        return IDENTITY, issues
    if not _finite(m):
        ev.issue(i, NON_FINITE)
        return IDENTITY, issues
    return m, issues
