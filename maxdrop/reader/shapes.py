# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shapes: the splines of a shape object (superclass 0x40) as Bezier knots in object space.

    sh = read_shape(scene, i)           # Shape, or None when object i is no shape class read here
    sp = sh.splines[0]                  # Spline(knots, closed)
    k = sp.knots[0]                     # Knot(kind, segment, point, in_vec, out_vec, material): absolute positions
    k.kind                              # SMOOTH, CORNER, BEZIER or BEZIER_CORNER (KNOT_NAMES: 3ds Max's names)
    k.segment                           # CURVE or LINE: the segment from this knot to the next
    k.material                          # that segment's material ID, zero-based (3ds Max shows 1 more)
    sh.steps, sh.optimize, sh.adaptive  # the interpolation, kept for meshing
    sh.render                           # Render: Enable In Renderer / In Viewport, thickness, sides, ...
    sh.issues                           # what was left out or drawn otherwise, as text

An Editable Spline (SplineShape) and a Line store their knots; a Line wraps the same chunks in a 0x2000 container.
0x1010 is the BezierShape: one 0x1010 per spline {0x2900 u32 knot count, 0x290A knots of 52 bytes (i32 knot
type, i32 segment type, f32, the point, the in vector and the out vector as 3 x f32 each, u32 whose high 16 bits are
the zero-based material ID of the segment that starts at the knot), 0x290D u32 closed}, then 0x1050 i32 steps (-1:
adaptive) and 0x1060 optimize; the object's own 0x1060 is the steps. Vectors are stored as positions, not offsets,
for every knot type: what 3ds Max computed for a corner or smooth knot is in the file. A segment of type LINE is
straight whatever its vectors.

The parametric shapes keep parameters only (reference slot 1: an old ParamBlock, the Ellipse a ParamBlock2) and
their interpolation in slot 2 (old ParamBlock: 0 steps, 1 optimize, 2 adaptive). Their splines are made here the
way 3ds Max makes them (every segment material ID 1, zero-based 0), checked against 3ds Max's own conversion to an
Editable Spline (the oracle): a circular arc of angle a has vectors of radius * veccalc(a), the SDK's float32
bisection for the vector length (0.5517862 for 90 degrees, not the textbook 0.5523); an Arc always has 3 segments,
its angles clamped to [0, 360]; an NGon's corner radius makes two knots per corner, an Ellipse's outline a second
spline. Every shape keeps its rendering block in slot 0 (old ParamBlock: 0 thickness, 1 sides, 2 angle in
degrees, 6 Enable In Renderer, 8 Enable In Viewport, 11 rectangular, 12 width, 13 length, 14 the rectangular
section's angle in degrees).

The file comes from anywhere: a spline whose record cannot be read is left out (an issue), a shape whose
parameters cannot be read raises ShapeError (a ChunkError) naming the object; counts are bounded by the payload,
values must be finite. docs/FORMAT.md says which fixture shows what. No bpy.
"""
import collections
import functools
import math
import struct

from . import chunks, classids, pblock
from .errors import MaxFileError

ChunkError = chunks.ChunkError

SMOOTH, CORNER, BEZIER, BEZIER_CORNER = 0, 1, 2, 3
CURVE, LINE = 0, 1
KNOT_NAMES = {SMOOTH: "smooth", CORNER: "corner", BEZIER: "bezier", BEZIER_CORNER: "bezierCorner"}
SEGMENT_NAMES = {CURVE: "curve", LINE: "line"}
MAX_KNOTS = 1 << 20  # per shape: a hostile count must not become millions of tuples
MAX_SIDES = 10000  # NGon: 3ds Max offers 3 to 100
MAX_STEPS = 100  # 3ds Max's own limit
DEFAULT_STEPS = 6

SLOT_RENDER, SLOT_PARAMS, SLOT_INTERPOLATION = 0, 1, 2
_WRAPPER, _BEZIER_SHAPE, _SPLINE = 0x2000, 0x1010, 0x1010
_KNOT_COUNT, _KNOTS, _CLOSED = 0x2900, 0x290A, 0x290D
_SHAPE_STEPS, _SHAPE_OPTIMIZE, _STEPS = 0x1050, 0x1060, 0x1060
_KNOT = struct.Struct("<iif9fI")
_I32 = struct.Struct("<i")
_U32 = struct.Struct("<I")


class ShapeError(ChunkError):
    """A shape object that cannot be read; the message names the object."""


class Knot(collections.namedtuple("Knot", "kind segment point in_vec out_vec material", defaults=(0,))):
    """One knot: its type, the type of the segment that starts at it, three (x, y, z) positions and that segment's
    zero-based material ID."""
    __slots__ = ()


class Spline(collections.namedtuple("Spline", "knots closed")):
    __slots__ = ()


class Render(collections.namedtuple("Render", "renderable viewport thickness sides angle rectangular width "
                                              "length section_angle")):
    """The shape's rendering settings: renderable = Enable In Renderer, viewport = Enable In Viewport; angle (the
    round section's) and section_angle (the rectangular one's) in degrees; width and length are the rectangular
    section's."""
    __slots__ = ()


DEFAULT_RENDER = Render(False, False, 1.0, 12, 0.0, False, 2.0, 6.0, 0.0)


class Shape(collections.namedtuple("Shape", "class_id splines steps optimize adaptive render issues")):
    __slots__ = ()


_F32 = struct.Struct("<f")


def _f32(x):
    """x rounded to float32: a double operation on float32 values, rounded, is the float32 operation."""
    return _F32.unpack(_F32.pack(x))[0]


@functools.lru_cache(maxsize=256)
def veccalc(angle):
    """The vector length, per unit radius, that 3ds Max gives the two knots of a circular arc of angle radians:
    the SDK's veccalc, a float32 bisection until the mean distance of 10 points of the segment from the center is
    exactly 1. In float32 it stops early on small angles (1.5 / 1024 for 0, where a zero-length Arc's vectors lie),
    as the oracle shows."""
    a = _f32(angle)
    s, c = _f32(math.sin(a)), _f32(math.cos(a))
    lo, hi, test = 0.0, 1.5, 0.75
    for _ in range(200):  # the SDK's count
        test = _f32((lo + hi) / 2.0)
        ix, iy = _f32(c + _f32(s * test)), _f32(s - _f32(c * test))
        total = 0.0
        for k in range(10):
            t = _f32(k / 10.0)
            u = _f32(1.0 - t)
            u2, t2 = _f32(u * u), _f32(t * t)
            u3, t3 = _f32(u2 * u), _f32(t2 * t)
            b, d = _f32(_f32(3.0 * t) * u2), _f32(_f32(3.0 * t2) * u)
            # the Bezier (1, 0), out (1, test), in (ix, iy), (c, s) at t, term by term in the SDK's order
            x = _f32(_f32(_f32(u3 + b) + _f32(d * ix)) + _f32(t3 * c))
            y = _f32(_f32(_f32(b * test) + _f32(d * iy)) + _f32(t3 * s))
            total = _f32(total + _f32(math.sqrt(_f32(_f32(x * x) + _f32(y * y)))))
        total = _f32(total / 10.0)
        if total == 1.0 or test in (lo, hi):  # test at a bound: the rest of the 200 passes repeat it
            break
        if total > 1.0:
            hi = test
        else:
            lo = test
    return test


def _p(x, y):
    return (float(x), float(y), 0.0)


def _toward(p, q, f):
    return tuple(a + (b - a) * f for a, b in zip(p, q))


def _polygon(points, kind=BEZIER_CORNER):
    """A closed spline through points with straight sides: each vector a third of the way to the neighbour."""
    n = len(points)
    return [Knot(kind, CURVE, p, _toward(p, points[k - 1], 1 / 3.0), _toward(p, points[(k + 1) % n], 1 / 3.0))
            for k, p in enumerate(points)]


def _circle(n, radius, start=0.0):
    """n Bezier knots on a circle, counter-clockwise from the angle start: 3ds Max's circle, round NGon and Arc."""
    step = 2 * math.pi / n
    return _arc_knots(radius, start, step, n)


def _arc_knots(radius, start, step, count):
    v = radius * veccalc(abs(step)) * (1 if step >= 0 else -1)
    out = []
    for k in range(count):
        a = start + k * step
        c, s = math.cos(a), math.sin(a)
        p = _p(radius * c, radius * s)
        out.append(Knot(BEZIER, CURVE, p, _p(p[0] + s * v, p[1] - c * v), _p(p[0] - s * v, p[1] + c * v)))
    return out


def _scaled(knots, sx, sy):
    def sc(p):
        return (p[0] * sx, p[1] * sy, p[2])
    return [k._replace(point=sc(k.point), in_vec=sc(k.in_vec), out_vec=sc(k.out_vec)) for k in knots]


def _reversed(knots):
    return [k._replace(in_vec=k.out_vec, out_vec=k.in_vec) for k in reversed(knots)]


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


class _Params:
    """An old ParamBlock or a ParamBlock2 read by index / parameter id alike. A value is whatever the file stored:
    a point3 where a float belongs, or a controller (pblock.Animated) on an animated parameter, so number()
    refuses anything that is not a finite number."""

    def __init__(self, block):
        self.block = block

    def get(self, i, default=None):
        value = None if self.block is None else self.block.get(i)
        return default if value is None else value

    def number(self, i, default=0.0):
        """Parameter i as a float; ChunkError when it is stored as anything but a finite number."""
        v = self.get(i, default)
        if not _is_number(v):
            raise ChunkError("parameter %d is %s" % (i, "animated (a controller)" if isinstance(v, pblock.Animated)
                                                     else "not a number: %r" % (v,)))
        return float(v)

    def flag(self, i, default=False):
        """Parameter i as a switch: a number other than 0; anything else is the default."""
        v = self.get(i)
        return bool(v) if _is_number(v) else default


def _rectangle(params, _issues):
    length, width, radius = params.number(0), params.number(1), params.number(2)
    x, y, r = abs(width) / 2.0, abs(length) / 2.0, max(radius, 0.0)
    if r <= 0:
        return [Spline(_polygon([_p(x, y), _p(-x, y), _p(-x, -y), _p(x, -y)]), True)]
    v = r * veccalc(math.pi / 2)
    sides = (((x, y - r), (0, 1)), ((x - r, y), (-1, 0)), ((r - x, y), (-1, 0)), ((-x, y - r), (0, -1)),
             ((-x, r - y), (0, -1)), ((r - x, -y), (1, 0)), ((x - r, -y), (1, 0)), ((x, r - y), (0, 1)))
    knots = [Knot(BEZIER_CORNER, CURVE, _p(px, py), _p(px - dx * v, py - dy * v), _p(px + dx * v, py + dy * v))
             for (px, py), (dx, dy) in sides]
    return [Spline(knots, True)]


def _circle_shape(params, _issues):
    return [Spline(_circle(4, abs(params.number(0))), True)]


def _ellipse(params, issues):
    length, width = params.number(0), params.number(1)
    x, y = abs(width) / 2.0, abs(length) / 2.0
    unit = _circle(4, 1.0)
    splines = [Spline(_scaled(unit, x, y), True)]
    if params.flag(3):  # the outline: both semi-axes plus the thickness, each clamped at 0
        try:
            t = params.number(2)
        except ChunkError as exc:  # the ellipse itself is still known
            issues.append("the outline is left out: its thickness %s" % exc)
            return splines
        splines.append(Spline(_scaled(unit, max(x + t, 0.0), max(y + t, 0.0)), True))
    return splines


def _arc(params, _issues):
    radius, start, end = params.number(0), params.number(1), params.number(2)
    start, end = min(max(start, 0.0), 360.0), min(max(end, 0.0), 360.0)
    span = end - start if end >= start else end + 360.0 - start  # from = to: a zero-length arc
    knots = _arc_knots(abs(radius), math.radians(start), math.radians(span) / 3.0, 4)
    knots[0] = knots[0]._replace(in_vec=knots[0].point)
    knots[-1] = knots[-1]._replace(out_vec=knots[-1].point)
    if params.flag(4):
        knots = _reversed(knots)
    pie = params.flag(3)
    if pie:  # closed through the center
        center = _p(0, 0)
        knots.append(Knot(BEZIER, CURVE, center, center, center))
    return [Spline(knots, pie)]


def _ngon(params, issues):
    radius, stored = params.number(0), params.number(1, 6)
    sides = int(min(max(stored, 3), MAX_SIDES))
    if sides != stored:
        issues.append("%g sides, drawn with %d" % (stored, sides))
    r = abs(radius) if params.flag(4) else abs(radius) / math.cos(math.pi / sides)  # scribe 0: r is the apothem
    if params.flag(2):  # circular: the corner radius is ignored
        return [Spline(_circle(sides, r), True)]
    step = 2 * math.pi / sides
    corners = [_p(r * math.cos(k * step), r * math.sin(k * step)) for k in range(sides)]
    corner = params.get(3, 0.0)
    if not _is_number(corner):
        issues.append("the corner radius is no number (%s): sharp corners"
                      % ("animated" if isinstance(corner, pblock.Animated) else "%r" % (corner,)))
    if not (_is_number(corner) and corner > 0):
        return [Spline(_polygon(corners), True)]
    return [Spline(_rounded(corners, corner * math.tan(math.pi / sides)), True)]


def _rounded(corners, d):
    """An NGon's rounded corners: two Bezier knots per corner, d along the sides to the previous and the next corner
    (no clamp: past half a side they cross, as in 3ds Max), each vector along its side, d * veccalc(90 degrees) long
    (the SDK's CIRCLE_VECTOR_LENGTH, whatever the corner's angle)."""
    v = d * veccalc(math.pi / 2)
    n, knots = len(corners), []
    for k, p in enumerate(corners):
        for q, first in ((corners[k - 1], True), (corners[(k + 1) % n], False)):
            length = math.hypot(q[0] - p[0], q[1] - p[1]) or 1.0
            ux, uy = (q[0] - p[0]) / length, (q[1] - p[1]) / length
            at = _p(p[0] + ux * d, p[1] + uy * d)
            away, toward = _p(at[0] + ux * v, at[1] + uy * v), _p(at[0] - ux * v, at[1] - uy * v)
            knots.append(Knot(BEZIER, CURVE, at, away, toward) if first else Knot(BEZIER, CURVE, at, toward, away))
    return knots


_PARAMETRIC = {
    classids.RECTANGLE: _rectangle,
    classids.CIRCLE: _circle_shape,
    classids.ELLIPSE: _ellipse,
    classids.ARC: _arc,
    classids.NGON: _ngon,
}
_STORED = frozenset((classids.SPLINE_SHAPE, classids.LINE))


def is_shape(scene, i):
    """Whether object i is a shape class read here."""
    entry = scene.entry(i)
    return entry is not None and entry.superclass == classids.SC_SHAPE and (
        entry.class_id in _STORED or entry.class_id in _PARAMETRIC)


def _int(chunk, fmt=_I32):
    if chunk is None or chunk.payload_size < fmt.size:
        return None
    return fmt.unpack(chunk.view()[:fmt.size])[0]


def _spline(c):
    if not c.container:
        raise ChunkError("a leaf chunk")
    count = _int(c.first(_KNOT_COUNT), _U32)
    data = c.first(_KNOTS)
    if count is None or data is None:
        raise ChunkError("no knot count (0x2900) or knots (0x290A)")
    if count * _KNOT.size > data.payload_size:
        raise ChunkError("%d knots announced, %d bytes of knots" % (count, data.payload_size))
    raw = data.view()
    knots = []
    for k in range(count):
        v = _KNOT.unpack_from(raw, k * _KNOT.size)
        kind, segment, xyz, material = v[0], v[1], v[3:12], v[12] >> 16
        if kind not in KNOT_NAMES or segment not in SEGMENT_NAMES:
            raise ChunkError("knot %d: type %d, segment type %d" % (k, kind, segment))
        if not all(math.isfinite(x) for x in xyz):
            raise ChunkError("knot %d is not finite" % k)
        xyz = tuple(float(x) for x in xyz)
        knots.append(Knot(kind, segment, xyz[0:3], xyz[3:6], xyz[6:9], material))
    closed = _int(c.first(_CLOSED), _U32)
    return Spline(tuple(knots), bool(closed))


def _stored(chunk, issues):
    """(splines, steps, optimize, adaptive) of an Editable Spline or a Line."""
    if not chunk.container:
        raise ChunkError("a leaf chunk")
    holder = chunk
    wrapper = chunk.first(_WRAPPER)
    if wrapper is not None and wrapper.container:
        holder = wrapper
    shape = holder.first(_BEZIER_SHAPE)
    if shape is None or not shape.container:
        raise ChunkError("no BezierShape (0x1010)")
    splines, total = [], 0
    for k, c in enumerate(shape.find_all(_SPLINE)):
        try:
            sp = _spline(c)
        except MaxFileError as exc:  # its knots are read inside the payload: the count is checked first
            issues.append("spline %d left out: %s" % (k, exc))
            continue
        total += len(sp.knots)
        if total > MAX_KNOTS:
            raise ChunkError("more than %d knots" % MAX_KNOTS)
        splines.append(sp)
    inner = _int(shape.first(_SHAPE_STEPS))
    optimize = _int(shape.first(_SHAPE_OPTIMIZE))
    steps = _int(holder.first(_STEPS))
    if steps is None or steps < 0:
        steps = inner if inner is not None and inner >= 0 else DEFAULT_STEPS
    return splines, steps, optimize is None or optimize != 0, inner == -1


def _block(scene, refs, slot, superclasses):
    t = refs.get(slot)
    if t is None:
        return None
    entry = scene.entry(t)
    if entry is None or entry.superclass not in superclasses:
        return None
    if entry.superclass == classids.SC_PARAMETER_BLOCK2:
        return pblock.ParamBlock2.from_chunk(scene.chunk(t))
    return pblock.ParamBlock.from_chunk(scene.chunk(t))


def _render(scene, refs, issues):
    block = _block(scene, refs, SLOT_RENDER, (classids.SC_PARAMETER_BLOCK,))
    if block is None:
        issues.append("no rendering block (reference slot 0): rendering settings left at 3ds Max's defaults")
        return DEFAULT_RENDER
    d, params = DEFAULT_RENDER, _Params(block)

    def number(i, default):  # a value that is no number keeps 3ds Max's default: it only shapes the bevel
        v = params.get(i)
        return float(v) if _is_number(v) else default

    sides = number(1, d.sides)
    return Render(params.flag(6, d.renderable), params.flag(8, d.viewport), number(0, d.thickness),
                  int(min(max(sides, 0), 1000)), number(2, d.angle), params.flag(11, d.rectangular),
                  number(12, d.width), number(13, d.length), number(14, d.section_angle))


def read_shape(scene, i):
    """The Shape of object i, None when it is no shape class read here. A shape that cannot be read raises
    ShapeError naming the object."""
    if not is_shape(scene, i):
        return None
    entry = scene.entry(i)
    issues = []
    try:
        refs = scene.refs(i)
        if entry.class_id in _STORED:
            splines, steps, optimize, adaptive = _stored(scene.chunk(i), issues)
        else:
            params = _block(scene, refs, SLOT_PARAMS, (classids.SC_PARAMETER_BLOCK, classids.SC_PARAMETER_BLOCK2))
            if params is None:
                raise ChunkError("no parameter block (reference slot 1)")
            splines = _PARAMETRIC[entry.class_id](_Params(params), issues)
            interp = _Params(_block(scene, refs, SLOT_INTERPOLATION, (classids.SC_PARAMETER_BLOCK,)))
            steps, optimize, adaptive = interp.number(0, DEFAULT_STEPS), interp.flag(1, True), interp.flag(2)
        render = _render(scene, refs, issues)
        steps = int(min(max(steps, 0), MAX_STEPS))
    except (MaxFileError, MemoryError, OverflowError) as exc:
        raise ShapeError("object %d (%s): %s" % (i, entry.name, exc or type(exc).__name__)) from None
    return Shape(entry.class_id, tuple(splines), steps, optimize, adaptive, render, tuple(issues))
