# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shapes: the splines of a shape object (superclass 0x40) as Bezier knots in object space.

    sh = read_shape(scene, i)           # Shape, or None when object i is no shape class read here
    sp = sh.splines[0]                  # Spline(knots, closed)
    k = sp.knots[0]                     # Knot(kind, segment, point, in_vec, out_vec): absolute positions
    k.kind                              # SMOOTH, CORNER, BEZIER or BEZIER_CORNER (KNOT_NAMES: 3ds Max's names)
    k.segment                           # CURVE or LINE: the segment from this knot to the next
    sh.steps, sh.optimize, sh.adaptive  # the interpolation, kept for meshing
    sh.render                           # Render: Enable In Renderer / In Viewport, thickness, sides, ...
    sh.issues                           # what was left out or drawn otherwise, as text

An Editable Spline (SplineShape) and a Line store their knots; a Line wraps the same chunks in a 0x2000 container.
0x1010 is the BezierShape: one 0x1010 per spline {0x2900 u32 knot count, 0x290A knots of 52 bytes (i32 knot
type, i32 segment type, f32, the point, the in vector and the out vector as 3 x f32 each, u32), 0x290D u32 closed},
then 0x1050 i32 steps (-1: adaptive) and 0x1060 optimize; the object's own 0x1060 is the steps. Vectors are stored
as positions, not offsets, for every knot type: what 3ds Max computed for a corner or smooth knot is in the file.
A segment of type LINE is straight whatever its vectors.

The parametric shapes keep parameters only (reference slot 1: an old ParamBlock, the Ellipse a ParamBlock2) and
their interpolation in slot 2 (old ParamBlock: 0 steps, 1 optimize, 2 adaptive). Their splines are made here the
way 3ds Max makes them, checked against 3ds Max's own conversion to an Editable Spline (the oracle): a circular
arc of angle a has vectors of radius * veccalc(a), the SDK's bisection for the vector length (0.5517857 for 90
degrees, not the textbook 0.5523); an Arc always has 3 segments. NGon's corner radius and Ellipse's outline are not
drawn (an issue each). Every shape keeps its rendering block in slot 0 (old ParamBlock: 0 thickness, 1 sides,
2 angle in degrees, 6 Enable In Renderer, 8 Enable In Viewport, 11 rectangular, 12 width, 13 length).

The file comes from anywhere: a spline whose record cannot be read is left out (an issue), a shape whose
parameters cannot be read raises ShapeError (a ChunkError) naming the object; counts are bounded by the payload,
values must be finite. docs/FORMAT.md says which fixture shows what. No bpy.
"""
import collections
import functools
import math
import struct

from . import chunks, classids, pblock

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


class Knot(collections.namedtuple("Knot", "kind segment point in_vec out_vec")):
    """One knot: its type, the type of the segment that starts at it, and three (x, y, z) positions."""
    __slots__ = ()


class Spline(collections.namedtuple("Spline", "knots closed")):
    __slots__ = ()


class Render(collections.namedtuple("Render", "renderable viewport thickness sides angle rectangular width "
                                              "length")):
    """The shape's rendering settings: renderable = Enable In Renderer, viewport = Enable In Viewport; angle in
    degrees; width and length are the rectangular section's."""
    __slots__ = ()


DEFAULT_RENDER = Render(False, False, 1.0, 12, 0.0, False, 2.0, 6.0)


class Shape(collections.namedtuple("Shape", "class_id splines steps optimize adaptive render issues")):
    __slots__ = ()


@functools.lru_cache(maxsize=256)
def veccalc(angle):
    """The vector length, per unit radius, that 3ds Max gives the two knots of a circular arc of angle radians:
    a bisection until the mean distance of 10 points of the segment from the center is 1 (the SDK's veccalc)."""
    s, c = math.sin(angle), math.cos(angle)
    lo, hi, test = 0.0, 1.5, 0.75
    for _ in range(60):  # past double precision
        test = (lo + hi) / 2.0
        ox, oy = 1.0, test
        ix, iy = c + s * test, s - c * test
        total = 0.0
        for k in range(10):
            u = k / 10.0
            a, b, d, e = (1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3
            total += math.hypot(a + b * ox + d * ix + e * c, b * oy + d * iy + e * s)
        total /= 10.0
        if total == 1.0:
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


def _finite(*values):
    for v in values:
        if v is None or not math.isfinite(v):
            raise ChunkError("a parameter is %r" % (v,))
    return values


def _rectangle(params, _issues):
    length, width, radius = _finite(params.get(0, 0.0), params.get(1, 0.0), params.get(2, 0.0))
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
    (radius,) = _finite(params.get(0, 0.0))
    return [Spline(_circle(4, abs(radius)), True)]


def _ellipse(params, issues):
    length, width = _finite(params.get(0, 0.0), params.get(1, 0.0))
    if params.get(3):
        issues.append("the outline (a second spline) is not drawn: the ellipse alone")
    return [Spline(_scaled(_circle(4, 1.0), abs(width) / 2.0, abs(length) / 2.0), True)]


def _arc(params, _issues):
    radius, start, end = _finite(params.get(0, 0.0), params.get(1, 0.0), params.get(2, 0.0))
    span = (end - start) % 360.0 or 360.0
    knots = _arc_knots(abs(radius), math.radians(start), math.radians(span) / 3.0, 4)
    knots[0] = knots[0]._replace(in_vec=knots[0].point)
    knots[-1] = knots[-1]._replace(out_vec=knots[-1].point)
    if params.get(4):
        knots = _reversed(knots)
    if params.get(3):  # pie: closed through the center
        center = _p(0, 0)
        knots.append(Knot(BEZIER, CURVE, center, center, center))
    return [Spline(knots, bool(params.get(3)))]


def _ngon(params, issues):
    (radius,) = _finite(params.get(0, 0.0))
    sides = params.get(1, 6)
    if not 3 <= sides <= MAX_SIDES:
        issues.append("%d sides, drawn with %d" % (sides, min(max(sides, 3), MAX_SIDES)))
        sides = min(max(sides, 3), MAX_SIDES)
    r = abs(radius) if params.get(4) else abs(radius) / math.cos(math.pi / sides)  # scribe 0: r is the apothem
    if params.get(2):
        return [Spline(_circle(sides, r), True)]
    corner = params.get(3, 0.0)
    if corner and math.isfinite(corner) and corner > 0:
        issues.append("the corner radius is not drawn: sharp corners")
    step = 2 * math.pi / sides
    return [Spline(_polygon([_p(r * math.cos(k * step), r * math.sin(k * step)) for k in range(sides)]), True)]


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
        kind, segment, xyz = v[0], v[1], v[3:12]
        if kind not in KNOT_NAMES or segment not in SEGMENT_NAMES:
            raise ChunkError("knot %d: type %d, segment type %d" % (k, kind, segment))
        if not all(math.isfinite(x) for x in xyz):
            raise ChunkError("knot %d is not finite" % k)
        xyz = tuple(float(x) for x in xyz)
        knots.append(Knot(kind, segment, xyz[0:3], xyz[3:6], xyz[6:9]))
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
        except (ChunkError, struct.error) as exc:
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


class _Params:
    """An old ParamBlock or a ParamBlock2 read by index / parameter id alike."""

    def __init__(self, block):
        self.block = block

    def get(self, i, default=None):
        if self.block is None:
            return default
        value = self.block.get(i)
        return default if value is None else value


def _render(scene, refs, issues):
    block = _block(scene, refs, SLOT_RENDER, (classids.SC_PARAMETER_BLOCK,))
    if block is None:
        issues.append("no rendering block (reference slot 0): rendering settings left at 3ds Max's defaults")
        return DEFAULT_RENDER
    d = DEFAULT_RENDER

    def number(i, default):
        v = block.get(i)
        return float(v) if v is not None and math.isfinite(v) else default

    return Render(bool(block.get(6, d.renderable)), bool(block.get(8, d.viewport)), number(0, d.thickness),
                  int(block.get(1, d.sides)), number(2, d.angle), bool(block.get(11, d.rectangular)),
                  number(12, d.width), number(13, d.length))


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
            steps, optimize, adaptive = interp.get(0, DEFAULT_STEPS), bool(interp.get(1, 1)), bool(interp.get(2, 0))
        render = _render(scene, refs, issues)
    except (ChunkError, struct.error, MemoryError, OverflowError, ValueError) as exc:
        raise ShapeError("object %d (%s): %s" % (i, entry.name, exc or type(exc).__name__)) from None
    steps = min(max(int(steps), 0), MAX_STEPS)
    return Shape(entry.class_id, tuple(splines), steps, optimize, adaptive, render, tuple(issues))
