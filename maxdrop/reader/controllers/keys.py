# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keys: easing, Hermite and Bezier curves, tangents, interpolation and out-of-range types."""
import bisect
import math
import struct

from .. import classids, scene as scene_mod
from .ids import (
    _BEZIER, _CHORDS, _CONSTANT_VELOCITY, _CUSTOM, _DEFAULT_LENGTH, _FREE_HANDLE, _IN_TYPE, _KEY_VALUE, _LINEAR,
    _LINEAR_TANGENT, _NEAR_OPPOSITE, _ORT_CONSTANT, _ORT_KNOWN, _ORT_LINEAR, _ORT_LOOP, _ORT_PING_PONG, _ORT_RELATIVE,
    _OUT_TYPE, _QUAT_VALUE, _SCALE_VALUE, _SOLVE_STEPS, _SPIN, _SPIN_GAP, _STEP, _TCB, ORT_APPROXIMATED, ORT_UNKNOWN,
)
from .math3d import _opposite, _qmul, _qpow, _slerp_long, _unit, _unit_quat, slerp, spin, squad, turn


def ease(u, ease_from, ease_to):
    """The fraction u of a TCB segment after its ease: ease_from of the earlier key, ease_to of the later, fractions
    (MAXScript's percentages / 50). Accelerates over ease_from, decelerates over ease_to, both scaled down when they
    add up past 1."""
    s = ease_from + ease_to
    if s == 0.0:
        return u
    if s > 1.0:
        ease_from, ease_to = ease_from / s, ease_to / s
    k = 1.0 / (2.0 - ease_from - ease_to)
    if u < ease_from:
        return k / ease_from * u * u
    if u < 1.0 - ease_to:
        return k * (2.0 * u - ease_from)
    u = 1.0 - u
    return 1.0 - k / ease_to * u * u


def hermite(p0, p1, out_tangent, in_tangent, u):
    """The cubic from p0 to p1 with the stored TCB tangents (value per segment) at fraction u."""
    u2 = u * u
    u3 = u2 * u
    return (p0 * (2.0 * u3 - 3.0 * u2 + 1.0) + p1 * (3.0 * u2 - 2.0 * u3) + out_tangent * (u3 - 2.0 * u2 + u) +
            in_tangent * (u3 - u2))


def handle(length, tangent, dt, ticks_per_frame=0):
    """A Bezier handle's extent in ticks: length a fraction of the segment dt (-1, or any negative: a third); a free
    handle's (ticks_per_frame given) length is in frames, measured along the handle in (ticks, stored value) space."""
    if ticks_per_frame:
        return length * ticks_per_frame / math.sqrt(1.0 + tangent * tangent)
    return (_DEFAULT_LENGTH if length < 0.0 else length) * dt


def _cubic(p0, p1, p2, p3, u):
    w = 1.0 - u
    return w * w * w * p0 + 3.0 * w * w * u * p1 + 3.0 * w * u * u * p2 + u * u * u * p3


def bezier(t0, v0, out_tangent, out_length, t1, v1, in_tangent, in_length, t, free_out=0, free_in=0):
    """A Bezier segment's value at time t (ticks): the cubic through (t0, v0), its out handle (t0 + x, v0 + tangent
    x), the in handle (t1 - x, v1 + tangent x) and (t1, v1), the tangents in value per tick (the in tangent points
    back), x the handle's extent (handle(); free_out and free_in: ticks per frame of a free handle, 0 for one whose
    length is a fraction). The time curve is solved for t by bisection; NaN for values that are not finite."""
    if not all(math.isfinite(v) for v in (v0, out_tangent, out_length, v1, in_tangent, in_length)):
        return math.nan
    dt = t1 - t0
    out_x, in_x = handle(out_length, out_tangent, dt, free_out), handle(in_length, in_tangent, dt, free_in)
    x1, x2 = t0 + out_x, t1 - in_x
    y1, y2 = v0 + out_tangent * out_x, v1 + in_tangent * in_x
    lo, hi = 0.0, 1.0
    for _ in range(_SOLVE_STEPS):
        mid = (lo + hi) / 2.0
        if _cubic(t0, x1, x2, t1, mid) < t:
            lo = mid
        else:
            hi = mid
    return _cubic(v0, y1, y2, v1, (lo + hi) / 2.0)


def constant_velocity(v0, out_tangent, v1, in_tangent, dt, f):
    """A Bezier Position segment with constant velocity out of its earlier key, a fraction f of its time on: the
    cubic of the values and tangents (value per tick, the in tangent pointing back) with handles of a third of the
    segment dt (the stored lengths and free handles do not count), cut into _CHORDS chords of equal parameter; the
    point a fraction f of the polyline's length along it (3ds Max 2020). NaN for values that are not finite."""
    controls = [(v0[c], v0[c] + out_tangent[c] * dt / 3.0, v1[c] + in_tangent[c] * dt / 3.0, v1[c])
                for c in range(3)]
    points = [tuple(_cubic(*p, k / _CHORDS) for p in controls) for k in range(_CHORDS + 1)]
    lengths = [math.dist(p, q) for p, q in zip(points, points[1:])]
    total = math.fsum(lengths)
    if not (math.isfinite(total) and math.isfinite(f)):
        return (math.nan,) * 3
    left = f * total
    for k, piece in enumerate(lengths):
        if left <= piece and piece > 0.0:
            s = left / piece
            return tuple(p + (q - p) * s for p, q in zip(points[k], points[k + 1]))
        left -= piece
    return points[-1] if total > 0.0 else points[0]


def _tangents(n, dt, a, flags_a, auto_a, b, flags_b, auto_b):
    """The Bezier records a and b (the floats after the flags, n of them the value) as 3ds Max 2020 draws the segment
    between them (dt ticks long): a handle's stored length counts only for a custom tangent (type 5 without the
    auto bit) or a free handle, every other type is a third long; a Linear tangent facing a custom or auto one is
    the slope of the chord (the stored one is stale), beside any other type the stored one."""
    out_type, in_type = (flags_a >> _OUT_TYPE) & 7, (flags_b >> _IN_TYPE) & 7
    keep_out = (out_type == _CUSTOM and not auto_a) or flags_a & _FREE_HANDLE
    keep_in = (in_type == _CUSTOM and not auto_b) or flags_b & _FREE_HANDLE
    a, b = list(a), list(b)
    for c in range(min(n, 3)):
        if not keep_out:
            a[4 * n + c] = -1.0
        if not keep_in:
            b[3 * n + c] = -1.0
        if out_type == _LINEAR_TANGENT and in_type == _CUSTOM:
            a[2 * n + c] = (b[c] - a[c]) / dt
        if in_type == _LINEAR_TANGENT and out_type == _CUSTOM:
            b[n + c] = (a[c] - b[c]) / dt
    return a, b


def _between(cid, n, t0, a, flags_a, t1, b, flags_b, t=0, ticks_per_frame=scene_mod.DEFAULT_TICKS_PER_FRAME,
             auto_a=False, auto_b=False):
    """The value at time t between the Bezier, TCB or Smooth Rotation keys a (at t0) and b (at t1), each the floats
    of its record after the flags, n of them the value; a free handle's length is in frames of ticks_per_frame;
    auto_a and auto_b: a's out and b's in tangent is auto (_tangents). None where 3ds Max's curve is not known (a
    free handle of a negative length, scale axes whose quaternions point apart, a TCB turn just short of a
    revolution or about no axis, opposite Smooth Rotation quaternions or controls)."""
    f = (t - t0) / (t1 - t0)
    if cid in _BEZIER or cid in _TCB:
        axis = ()
        if n == 7:  # the scale axis turns by slerp at the plain fraction of the time, whatever the class's curve
            if sum(x * y for x, y in zip(a[3:7], b[3:7])) < 0.0:
                return None
            axis = slerp(a[3:7], b[3:7], f)
        m = min(n, 3)
        if cid in _BEZIER:
            # value, in tangent, out tangent, in length, out length: n floats each
            if (flags_a >> _OUT_TYPE) & 7 == _STEP or (flags_b >> _IN_TYPE) & 7 == _STEP:
                return tuple(a[:n])
            a, b = _tangents(n, t1 - t0, a, flags_a, auto_a, b, flags_b, auto_b)
            if cid == classids.BEZIER_POSITION and flags_a & _CONSTANT_VELOCITY:
                return constant_velocity(a[:3], a[6:9], b[:3], b[3:6], t1 - t0, f)
            free_out = ticks_per_frame if flags_a & _FREE_HANDLE else 0
            free_in = ticks_per_frame if flags_b & _FREE_HANDLE else 0
            if (free_out and min(a[4 * n:4 * n + m]) < 0.0) or (free_in and min(b[3 * n:3 * n + m]) < 0.0):
                return None
            v = tuple(bezier(t0, a[c], a[2 * n + c], a[4 * n + c], t1, b[c], b[n + c], b[3 * n + c], t, free_out,
                             free_in) for c in range(m))
        else:
            # value, tension, continuity, bias, ease to, ease from, in tangent, out tangent
            u = ease(f, a[n + 4], b[n + 3])
            v = tuple(hermite(a[c], b[c], a[2 * n + 5 + c], b[n + 5 + c], u) for c in range(m))
        return v + axis
    if cid == classids.TCB_ROTATION:
        # quaternion, tension, continuity, bias, ease to, ease from, axis and angle turned from the previous key,
        # the in and the out control quaternion
        axis, angle, u = b[9:12], b[12], ease(f, a[8], b[7])
        if not (math.isfinite(angle) and all(math.isfinite(v) for v in axis)):
            return (math.nan,) * 4
        if angle >= _SPIN:
            axis = _unit(axis)
            return None if axis is None else spin(a[:4], a[17:21], b[13:17], b[:4], axis, angle, u)
        # no probe stored a negative angle: one past the gap below a revolution is not known either
        if abs(angle) > _SPIN - _SPIN_GAP or _opposite(a[:4], b[:4]) or _opposite(a[17:21], b[13:17]):
            return None
        return squad(a[:4], a[17:21], b[13:17], b[:4], u)
    if cid == classids.BEZIER_ROTATION:  # quaternion, the in and the out control quaternion
        if _opposite(a[:4], b[:4]) or _opposite(a[8:12], b[4:8]):
            return None
        return squad(a[:4], a[8:12], b[4:8], b[:4], f)
    return None


def _interpolate(a, b, f, value_id):
    """The key value a fraction f of the way from a to b: components linearly, a rotation by slerp the way the stored
    signs give (270 degrees between two Linear Rotation keys turn the long way round; opposite quaternions, where it
    has no direction, the shorter arc: the earlier rotation), a scale's axis by slerp."""
    if value_id == _QUAT_VALUE:
        return slerp(a, b, f) if _opposite(a, b) else _slerp_long(a, b, f)
    lerp = tuple(x + (y - x) * f for x, y in zip(a, b))
    if value_id == _SCALE_VALUE:
        return lerp[:3] + slerp(a[3:], b[3:], f)
    return lerp


def _scale_value(chunk):
    """A 0x2505 ScaleValue: scale and axis, or a scale alone (12 bytes) with the identity axis; None without it."""
    if chunk is None:
        return None
    return chunk.unpack("<7f") if chunk.payload_size >= 28 else chunk.unpack("<3f") + (0.0, 0.0, 0.0, 1.0)


class _Keys:
    """The keys of a keyframe controller: value(t) at any time, the first key's value before them and the last's
    after; known turns False where a segment 3ds Max curves otherwise was taken linearly (KEYS_INTERPOLATED)."""

    def __init__(self, cid, value_id, count, size, view, times, auto_in, auto_out, ticks_per_frame):
        self.cid, self.value_id, self.count, self.size, self.view = cid, value_id, count, size, view
        self.times, self.auto_in, self.auto_out, self.ticks_per_frame = times, auto_in, auto_out, ticks_per_frame
        self.known = True

    def key(self, k):
        return struct.unpack_from("<%df" % self.count, self.view, k * self.size + _KEY_VALUE)

    def value(self, t):
        times = self.times
        k = bisect.bisect_right(times, t)  # times[k - 1] <= t < times[k]
        if k == 0:
            return self.key(0)
        if k == len(times) or times[k - 1] == t:
            return self.key(k - 1)
        if self.cid not in _LINEAR:
            record = "<I%df" % ((self.size - _KEY_VALUE) // 4)  # the flags, then every float
            a, b = (struct.unpack_from(record, self.view, j * self.size + 4) for j in (k - 1, k))
            value = _between(self.cid, self.count, times[k - 1], a[1:], a[0], times[k], b[1:], b[0], t,
                             self.ticks_per_frame, k - 1 in self.auto_out, k in self.auto_in)
            if value is not None:
                return value
            self.known = False
        f = (t - times[k - 1]) / (times[k] - times[k - 1])
        q0, q1 = self.key(k - 1), self.key(k)
        if self.cid in _LINEAR and self.value_id == _QUAT_VALUE:
            if _opposite(q0, q1):
                return turn(_unit_quat(q0), f)
            if _opposite(q0, q1, _NEAR_OPPOSITE):
                self.known = False
        elif self.cid in _LINEAR and self.value_id == _SCALE_VALUE:
            if sum(x * y for x, y in zip(q0[3:], q1[3:])) < 0.0:
                self.known = False
        return _interpolate(q0, q1, f, self.value_id)


def _conjugate(q):
    return (-q[0], -q[1], -q[2], q[3])


def _repeat(v, first, last, turns, count):
    """Value v of a cycle moved turns whole cycles on by Relative Repeat: each adds last - first (a rotation:
    turns by first^-1 * last; a scale: its components, the axis of v). (value, approximated)."""
    if count == 4:
        return _qmul(v, _qpow(_qmul(_conjugate(first), last), turns)), False
    m = min(count, 3)
    moved = tuple(v[c] + turns * (last[c] - first[c]) for c in range(m)) + tuple(v[m:])
    return moved, tuple(first[m:]) != tuple(last[m:])


def _extend(a, b, ticks, at_start, count):
    """Linear out-of-range: from value a one tick on to b, ticks from the range end (a's time at its start, b's at
    its end), as 3ds Max extrapolates the slope of one tick (a rotation: turns by a^-1 * b per tick; a scale: its
    components, the axis of the end). (value, approximated)."""
    base = a if at_start else b
    if count == 4:
        return _qmul(base, _qpow(_qmul(_conjugate(a), b), ticks)), False
    m = min(count, 3)
    moved = tuple(base[c] + (b[c] - a[c]) * ticks for c in range(m)) + tuple(base[m:])
    return moved, tuple(a[m:]) != tuple(b[m:])


def out_of_range(keys, t, before=_ORT_CONSTANT, after=_ORT_CONSTANT, start=None, end=None):
    """(the value of keys at time t, an issue reason or None) with the out-of-range types before and after the range
    start..end (ticks; the keys' first and last time when None), as 3ds Max 2020 maps a time outside it: Constant
    the range end's value, Cycle and Loop the time a whole number of ranges on (a time a whole range before the
    start lands on the end), Ping Pong mirrored, Relative Repeat that plus the change over a range per range
    crossed, Linear the slope of one tick at the range end. Inside the range the keys (the nearest key's value
    outside them). An unknown type is an issue wherever t is: 3ds Max's #identity (0) changes the whole curve."""
    first, last = keys.times[0], keys.times[-1]
    start = first if start is None else start
    end = last if end is None else end
    unknown = before not in _ORT_KNOWN or after not in _ORT_KNOWN
    if before == after == _ORT_LOOP and start <= first and last <= end and end - start > last - first:
        # Loop over a range wider than the keys: the keys repeat every range, a straight line from the last key's
        # value to the first's across the gap between them, inside the range too
        u = first + (t - first) % (end - start)
        if u <= last:
            return keys.value(u), None
        g = (u - last) / ((end - start) - (last - first))
        v = _interpolate(keys.value(last), keys.value(first), g, keys.value_id)
        return v, None if keys.count == 1 else ORT_APPROXIMATED  # measured on Bezier Floats only
    times = []  # the times the keys are read at: Loop that lands outside them over a range moved off them is a guess

    def at(u):
        times.append(u)
        return keys.value(u)

    approximated = False
    if start <= t <= end:
        v = at(t)
    else:
        kind = before if t < start else after
        span = end - start
        edge = start if t < start else end
        if kind not in _ORT_KNOWN or kind == _ORT_CONSTANT or span <= 0:
            v = at(edge)
        elif kind == _ORT_PING_PONG:
            p = (t - start) % (2 * span)
            v = at(start + (p if p <= span else 2 * span - p))
        elif kind == _ORT_LINEAR:
            if t < start:
                v, approximated = _extend(at(start), at(start + 1), t - start, True, keys.count)
            else:
                v, approximated = _extend(at(end - 1), at(end), t - end, False, keys.count)
        else:
            mapped = end - (start - t) % span if t < start else start + (t - end) % span
            v = at(mapped)
            if kind == _ORT_RELATIVE:
                v, approximated = _repeat(v, at(start), at(end), (t - mapped) // span, keys.count)
    if unknown:
        return v, ORT_UNKNOWN
    moved = start < first or end > last
    if _ORT_LOOP in (before, after) and moved and any(not first <= u <= last for u in times):
        approximated = True  # Loop over a range moved off the keys: measured only on both sides of a wider one
    return v, ORT_APPROXIMATED if approximated else None
