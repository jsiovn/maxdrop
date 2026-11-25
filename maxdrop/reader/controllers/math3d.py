# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Matrices, quaternions and vectors: rotations, slerp and squad, look-at and constraint frames."""
import math

from .ids import _BITS, _OPPOSITE, _TINY, IDENTITY


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


def _rows3(m):
    return tuple(row[:3] for row in m[:3])


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
    return quat_matrix(_qpow(_matrix_quat(m), weight))


def _qpow(q, s):
    """Max quaternion q turned s times as far about its own axis, along the shorter arc; NaN when it is not
    finite."""
    q = _unit_quat(q)
    if q is None:
        return (math.nan,) * 4
    x, y, z, w = q if q[3] >= 0.0 else tuple(-v for v in q)
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    h = math.atan2(n, w) * s
    if not math.isfinite(h):  # an infinite weight, where math.sin raises
        return (math.nan,) * 4
    k = math.sin(h) / n
    return (x * k, y * k, z * k, math.cos(h))


def _matrix_quat(m):
    """The Max quaternion (w >= 0) of rotation matrix m: the inverse of quat_matrix."""
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
    return (-x, -y, -z, w)  # stored the Max way: the conjugate of the standard quaternion


def _unit_quat(q):
    """q normalized; identity for a zero quaternion (as quat_matrix), None when it is not finite."""
    n = sum(v * v for v in q)
    if not math.isfinite(n):
        return None
    if n <= 1e-30:
        return (0.0, 0.0, 0.0, 1.0)
    n = math.sqrt(n)
    return tuple(v / n for v in q)


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


def _slerp_long(a, b, f):
    """slerp from quaternion a to b without turning b to a's side: the arc the stored signs give (a TCB or Smooth
    Rotation key past half a turn keeps the sign of the long way); NaN when either is not finite."""
    a, b = _unit_quat(a), _unit_quat(b)
    if a is None or b is None or not math.isfinite(f):
        return (math.nan,) * 4
    d = sum(x * y for x, y in zip(a, b))
    if abs(d) > 0.9999995:  # the same or the opposite quaternion: no arc to divide by
        return tuple(x + (y - x) * f for x, y in zip(a, b))
    theta = math.acos(d)
    s = math.sin(theta)
    ta, tb = (1.0 - f) * theta, f * theta
    if not (math.isfinite(ta) and math.isfinite(tb)):  # a fraction from a damaged ease, where math.sin raises
        return (math.nan,) * 4
    wa, wb = math.sin(ta) / s, math.sin(tb) / s
    return tuple(wa * x + wb * y for x, y in zip(a, b))


def _opposite(a, b, within=_OPPOSITE):
    """Whether quaternions a and b are opposite (a whole revolution apart), 1 + their dot below within: the arc the
    stored signs give has no direction there."""
    a, b = _unit_quat(a), _unit_quat(b)
    return a is not None and b is not None and 1.0 + sum(x * y for x, y in zip(a, b)) < within


def _qmul(a, b):
    """The quaternion product a * b, (x, y, z, w): of two Max quaternions, the one whose matrix is quat_matrix(a) *
    quat_matrix(b)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def turn(q, f):
    """Between opposite Linear Rotation keys, the earlier q (unit): a whole turn about its local Z, a fraction f of the
    way, whatever axis the turn was made about (3ds Max 2020)."""
    x, y, z, w = q
    c, s = math.cos(math.pi * f), math.sin(math.pi * f)
    return (c * x - s * y, c * y + s * x, c * z - s * w, c * w + s * z)


def spin(q0, out_control, in_control, q1, axis, angle, u):
    """A TCB Rotation turn of angle >= 2 pi about the unit axis (in q0's frame) from key q0 to key q1 at the eased
    fraction u: squad over the first half-turn with the earlier key's out control, the plain turn, squad over the
    last half-turn with the later key's in control (3ds Max 2020; turns of 360 to 800 degrees)."""
    q0 = _unit_quat(q0)
    if q0 is None or not math.isfinite(u):
        return (math.nan,) * 4

    def at(x):
        s = math.sin(x / 2.0)
        return _qmul(q0, (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(x / 2.0)))

    h = math.pi / angle
    if u < h:
        mid = at(math.pi)
        return squad(q0, out_control, mid, mid, u / h)
    if u > 1.0 - h:
        mid, end = at(angle - math.pi), at(angle)
        if sum(x * y for x, y in zip(end, q1)) < 0.0:  # the control on the computed end's side
            in_control = tuple(-v for v in in_control)
        return squad(mid, mid, in_control, end, (u - 1.0 + h) / h)
    return at(angle * u)


def squad(q0, a, b, q1, f):
    """The spherical quadrangle from q0 to q1 a fraction f of the way, a the out control of q0 and b the in control of
    q1 (stored with each key): how 3ds Max 2020 turns between TCB and Smooth Rotation keys."""
    return _slerp_long(_slerp_long(q0, q1, f), _slerp_long(a, b, f), 2.0 * f * (1.0 - f))


def _bits(holder, cid, n):
    """The key indices (below n) whose bit is set in the bit array chunk cid of holder; none where it is missing or
    unreadable, without an issue: a key whose auto bit is not read keeps its stored length, as a custom one."""
    chunk = holder.first(cid) if holder is not None and holder.container else None
    bits = chunk.first(_BITS) if chunk is not None and chunk.container else None
    if bits is None or bits.payload_size < 4:
        return frozenset()
    data = bytes(bits.view()[4:])
    count = min(bits.unpack("<i")[0], n, len(data) * 8)
    return frozenset(k for k in range(count) if data[k >> 3] >> (k & 7) & 1)


def _finite(m):
    return all(math.isfinite(v) for row in m for v in row)


def _near_identity(m):
    return not any(abs(m[r][c] - IDENTITY[r][c]) > 1e-9 for r in range(3) for c in range(3))


def _diagonal(m):
    """Whether scale matrix m scales along the axes alone (no turned scale axis; a NaN one is NON_FINITE's)."""
    return not any(abs(m[r][c]) > 1e-9 for r in range(3) for c in range(3) if r != c)


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
