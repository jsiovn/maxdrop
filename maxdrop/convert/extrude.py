# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Extrude modifier evaluated on a shape: a reader Shape and the modifier's parameters become a MeshData.

    is_extrude(modifier)                # a reader.modifiers.Modifier of class Extrude
    params, issues = read_params(scene, modifier)   # Params; ExtrudeError when they cannot be read
    lines = polylines(shape)            # [Polyline]: each spline as 3ds Max interpolates it
    data, issues = extrude(shape, params)           # reader.geometry.MeshData in the shape's object space
    triangles = triangulate(points, outer, holes)   # ear clipping of a polygon with holes, in 2D

The parameters are an old ParamBlock in reference slot 0 (0 amount, 1 segments, 2 cap start, 3 cap end, 4 cap
type 0 morph / 1 grid, 5 output 0 patch / 1 mesh / 2 NURBS, 6 generate mapping coordinates, 7 generate material
IDs, 8 use shape IDs, 9 smooth); Real-World Map Size is the u32 0x0130 of the 0x0110 entry in the modifier's 0x2150
whose 0x0120 names the Extrude class (reader.realworld; another class's entry is not this flag).

Interpolation (3ds Max's, fitted to its own counts): each segment gets steps points between its knots; with
optimize a straight segment (segment type line, or both vectors on the chord) gets none; adaptive gives a straight
segment none and a curved one 2^d - 1, d the smallest depth up to 5 at which every piece turns by at most 2 degrees
(the angle between the chords of its two halves). Without optimize even a straight segment gets its steps.

The sides join segments + 1 copies of each polyline along the object's Z, one per level, amount * level / segments
up; a closed polyline also gets a cap at level 0 (Cap Start) and at the last level (Cap End). Closed polylines nest
even-odd: one inside an even number of others is a solid, inside an odd number a hole of its innermost container.
Every solid is turned counter-clockwise and every hole clockwise seen from +Z before the sides are made, and a
negative amount reverses the sides, so the normals point out whatever way the splines run; an open polyline keeps its
own direction (its faces look to the right of it). A cap without holes is one n-gon, a cap with holes is ear-clipped
after a bridge to each hole, which gives the triangle count 3ds Max gives. The cap facing +Z gets material ID 1, the
one facing -Z ID 2, the sides ID 3 (zero-based here: 0, 1, 2) when Generate Material IDs is on, else every face
ID 1. Smooth gives the sides smoothing groups that change only at a corner or Bezier corner knot, the caps group
16; without it the sides have none. Mapping: the sides' U runs along each polyline (0 to 1, or its length with
Real-World Map Size), V up the levels (0 to 1, or the height); the caps map the shape's XY box (0 to 1, or its size).

The file comes from anywhere: a parameter that is animated or no number raises ExtrudeError; segments are clamped
to 1 .. MAX_SEGMENTS; a mesh past MAX_VERTICES raises ExtrudeError; a holed cap past MAX_CAP_POINTS or one that
cannot be bridged is left open, and outlines that take more than MAX_NEST_TESTS to nest get no caps (an issue
each); the holed cap that passes the mesh's MAX_CLIP_STEPS and those after it are left open (an issue, and one
more that counts the rest). docs/FORMAT.md says which fixture shows what.
No bpy; numpy is imported when a mesh is made.
"""
import collections
import math
import struct

from ..reader import chunks, classids, geometry, pblock, realworld, shapes

ChunkError = chunks.ChunkError

(P_AMOUNT, P_SEGMENTS, P_CAP_START, P_CAP_END, P_CAP_TYPE, P_OUTPUT, P_MAPPING, P_MATERIAL_IDS, P_SHAPE_IDS,
 P_SMOOTH) = range(10)
CAP_MORPH, CAP_GRID = 0, 1
OUTPUT_PATCH, OUTPUT_MESH, OUTPUT_NURBS = 0, 1, 2
SLOT_PARAMS = 0

ADAPTIVE_ANGLE = math.radians(2.0)
ADAPTIVE_DEPTH = 5
TOP_ID, BOTTOM_ID, SIDE_ID = 0, 1, 2  # zero-based: 3ds Max shows 1, 2, 3
CAP_GROUP = 1 << 4
MAX_SEGMENTS = 10000
MAX_VERTICES = 1 << 21  # about 2 million: about a second and 500 MB at most
MAX_CAP_POINTS = 5000  # a holed cap is ear-clipped in Python: quadratic
MAX_CLIP_STEPS = 1 << 25  # the holed caps of one mesh: a 5000-point cap takes up to about 8 million, 3 s
MAX_LOOPS = 4000  # closed polylines nested against each other: quadratic
MAX_NEST_TESTS = 1 << 24  # point-edge tests telling which outline lies in which: about 2 s in Python
_STRAIGHT = 1e-6  # relative distance of a vector from the chord


class ExtrudeError(ChunkError):
    """An Extrude that cannot be evaluated; the shape stays a curve."""


class CapError(ValueError):
    """A cap that cannot be triangulated."""


class Params(collections.namedtuple("Params", "amount segments cap_start cap_end cap_type output mapping "
                                              "material_ids shape_ids smooth real_world")):
    __slots__ = ()


DEFAULT = Params(0.0, 1, True, True, CAP_MORPH, OUTPUT_MESH, False, True, False, True, False)


class Polyline(collections.namedtuple("Polyline", "points hard closed")):
    """A spline as points (x, y, z); hard[k]: point k is a corner or Bezier corner knot (the sides' smoothing
    changes there)."""
    __slots__ = ()


def is_extrude(modifier):
    return modifier.superclass == classids.SC_OSMODIFIER and modifier.class_id == classids.EXTRUDE


def _number(block, i, default):
    v = block.get(i)
    if v is None:
        return default
    if isinstance(v, pblock.Animated):
        raise ExtrudeError("parameter %d is animated (a controller)" % i)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ExtrudeError("parameter %d is not a number: %r" % (i, v))
    return v


def read_params(scene, modifier):
    """(Params, issues) of an Extrude modifier (reader.modifiers.Modifier); ExtrudeError when they cannot be
    read."""
    block = modifier.legacy.get(SLOT_PARAMS)
    if block is None:
        raise ExtrudeError("no parameter block (reference slot 0)")
    d, issues = DEFAULT, []

    def flag(i, default):
        return _number(block, i, int(default)) != 0

    segments = _number(block, P_SEGMENTS, d.segments)
    clamped = int(min(max(segments, 1), MAX_SEGMENTS))
    if clamped != segments:
        issues.append("%g segments, made with %d" % (segments, clamped))
    try:
        real_world = realworld.flag(scene.chunk(modifier.index), modifier.class_id)
    except (ChunkError, struct.error):
        real_world = False
    p = Params(float(_number(block, P_AMOUNT, d.amount)), clamped, flag(P_CAP_START, d.cap_start),
               flag(P_CAP_END, d.cap_end), int(_number(block, P_CAP_TYPE, d.cap_type)),
               int(_number(block, P_OUTPUT, d.output)), flag(P_MAPPING, d.mapping),
               flag(P_MATERIAL_IDS, d.material_ids), flag(P_SHAPE_IDS, d.shape_ids), flag(P_SMOOTH, d.smooth),
               real_world)
    if p.cap_type == CAP_GRID:
        issues.append("grid caps are made as morph caps")
    if p.output != OUTPUT_MESH:
        issues.append("%s output is made as a mesh" % ("patch" if p.output == OUTPUT_PATCH else "NURBS"))
    if p.shape_ids and p.material_ids:
        issues.append("Use Shape IDs: the shape's segment IDs are not read, the sides get ID 3")
    return p, issues


# Interpolation

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _lerp(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)


def _bezier(p0, c1, c2, p3, t):
    s = 1.0 - t
    a, b, c, d = s * s * s, 3 * t * s * s, 3 * t * t * s, t * t * t
    return tuple(a * p0[k] + b * c1[k] + c * c2[k] + d * p3[k] for k in range(3))


def _norm(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _straight(p0, c1, c2, p3):
    """Whether both vectors lie on the chord (a Bezier segment drawn straight)."""
    chord = _sub(p3, p0)
    length = _norm(chord)
    scale = max(length, _norm(_sub(c1, p0)), _norm(_sub(c2, p3)))
    if scale == 0:
        return True
    tolerance = _STRAIGHT * scale
    for c in (c1, c2):
        v = _sub(c, p0)
        if length == 0:
            if _norm(v) > tolerance:
                return False
            continue
        cross = (v[1] * chord[2] - v[2] * chord[1], v[2] * chord[0] - v[0] * chord[2],
                 v[0] * chord[1] - v[1] * chord[0])
        if _norm(cross) / length > tolerance:
            return False
    return True


def _turn(a, b):
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    c = (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (na * nb)
    return math.acos(max(-1.0, min(1.0, c)))


def _adaptive_steps(p0, c1, c2, p3):
    for depth in range(ADAPTIVE_DEPTH):
        n = 1 << depth
        pts = [_bezier(p0, c1, c2, p3, k / n) for k in range(n + 1)]
        if all(_turn(_sub(m, pts[k]), _sub(pts[k + 1], m)) <= ADAPTIVE_ANGLE
               for k, m in enumerate(_bezier(p0, c1, c2, p3, (k + 0.5) / n) for k in range(n))):
            return n - 1
    return (1 << ADAPTIVE_DEPTH) - 1


def _hard(knot):
    return knot.kind in (shapes.CORNER, shapes.BEZIER_CORNER)


def _polyline(spline, steps, optimize, adaptive):
    knots = spline.knots
    n = len(knots)
    closed = spline.closed
    pts, hard = [], []
    for k in range(n if closed else n - 1):
        a, b = knots[k], knots[(k + 1) % n]
        p0, p3 = a.point, b.point
        line = a.segment == shapes.LINE
        c1, c2 = (_lerp(p0, p3, 1 / 3.0), _lerp(p0, p3, 2 / 3.0)) if line else (a.out_vec, b.in_vec)
        straight = line or _straight(p0, c1, c2, p3)
        if adaptive:
            count = 0 if straight else _adaptive_steps(p0, c1, c2, p3)
        else:
            count = 0 if optimize and straight else steps
        pts.append(p0)
        hard.append(_hard(a))
        pts.extend(_bezier(p0, c1, c2, p3, s / (count + 1.0)) for s in range(1, count + 1))
        hard.extend([False] * count)
    if not closed and n:
        pts.append(knots[-1].point)
        hard.append(_hard(knots[-1]))
    out_p, out_h = [], []
    for p, h in zip(pts, hard):  # a zero-length segment would make faces of no area
        if out_p and p == out_p[-1]:
            out_h[-1] = out_h[-1] or h
            continue
        out_p.append(p)
        out_h.append(h)
    if closed and len(out_p) > 1 and out_p[0] == out_p[-1]:
        out_h[0] = out_h[0] or out_h[-1]
        out_p.pop()
        out_h.pop()
    if closed and len(out_p) < 3:
        closed = False
    return Polyline(out_p, out_h, closed)


def polylines(shape):
    """[Polyline] of a reader Shape, one per spline of two points or more."""
    out = []
    for sp in shape.splines:
        pl = _polyline(sp, shape.steps, shape.optimize, shape.adaptive)
        if len(pl.points) >= 2:
            out.append(pl)
    return out


# 2D geometry

def _area(xy):
    s = 0.0
    n = len(xy)
    for k in range(n):
        x0, y0 = xy[k]
        x1, y1 = xy[(k + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def _inside(p, poly):
    """True / False for a point inside / outside a polygon, None on its boundary."""
    x, y = p
    inside = False
    n = len(poly)
    for k in range(n):
        (x0, y0), (x1, y1) = poly[k - 1], poly[k]
        if (x0, y0) == (x, y):
            return None
        if (y0 > y) != (y1 > y):
            xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if xi == x:
                return None
            if xi > x:
                inside = not inside
        elif y0 == y1 == y and min(x0, x1) <= x <= max(x0, x1):
            return None
    return inside


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _in_triangle(a, b, c, p):
    """p inside or on the counter-clockwise triangle a, b, c."""
    return _cross(a, b, p) >= 0 and _cross(b, c, p) >= 0 and _cross(c, a, p) >= 0


def _locally_inside(prev, a, nxt, b):
    """Whether the direction from a to b leaves a into the polygon, a being a corner of a counter-clockwise ring
    between prev and nxt."""
    if _cross(prev, a, nxt) > 0:  # convex: inside both edges
        return _cross(a, nxt, b) >= 0 and _cross(a, b, prev) >= 0
    return _cross(a, nxt, b) >= 0 or _cross(a, b, prev) >= 0


def _bridge(pts, ring, hole):
    """ring (point indices, counter-clockwise) with the clockwise hole spliced in through a bridge from the hole's
    rightmost point to a ring vertex it sees (Eberly's construction)."""
    m = max(range(len(hole)), key=lambda k: (pts[hole[k]][0], -pts[hole[k]][1]))
    mx, my = pts[hole[m]]
    best, at = None, None
    n = len(ring)
    for k in range(n):
        a, b = pts[ring[k]], pts[ring[(k + 1) % n]]
        if not (a[1] <= my <= b[1] and a[1] < b[1]):  # the ring runs up where the ray leaves it
            continue
        x = a[0] + (my - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        if x < mx or (best is not None and x >= best):
            continue
        best = x
        if x == a[0] and my == a[1]:
            at = k
        elif x == b[0] and my == b[1]:
            at = (k + 1) % n
        else:
            at = k if a[0] > b[0] else (k + 1) % n
    if at is None:
        raise CapError("a hole outside its outline")
    p = pts[ring[at]]
    if best != p[0] or my != p[1]:  # a reflex vertex inside the triangle (M, I, P) may hide P
        tri = ((mx, my), p, (best, my)) if p[1] < my else ((mx, my), (best, my), p)  # counter-clockwise
        choice = None
        for k in range(n):
            q = pts[ring[k]]
            if k == at or q[0] < mx:
                continue
            if _cross(pts[ring[k - 1]], q, pts[ring[(k + 1) % n]]) > 0:
                continue
            if _in_triangle(tri[0], tri[1], tri[2], q):
                dx, dy = q[0] - mx, q[1] - my
                key = (abs(dy) / dx if dx > 0 else math.inf, dx * dx + dy * dy)
                if choice is None or key < choice[0]:
                    choice = (key, k)
        if choice is not None:
            at = choice[1]
    # a vertex bridged before is in the ring more than once: the bridge leaves from the copy whose corner M is in
    p = pts[ring[at]]
    copies = [k for k in range(n) if pts[ring[k]] == p]
    if len(copies) > 1:
        at = next((k for k in copies if _locally_inside(pts[ring[k - 1]], p, pts[ring[(k + 1) % n]], (mx, my))), at)
    loop = hole[m:] + hole[:m] + [hole[m]]
    return ring[:at + 1] + loop + ring[at:]


def _charge(budget, steps):
    budget[0] -= steps
    if budget[0] < 0:
        raise CapError("more than %d steps to triangulate the caps" % MAX_CLIP_STEPS)


def _earclip(pts, ring, budget):
    n = len(ring)
    if n < 3:
        return []
    xy = [pts[i] for i in ring]
    prev = [(k - 1) % n for k in range(n)]
    nxt = [(k + 1) % n for k in range(n)]
    span = max(max(abs(c) for p in xy for c in p), 1e-30)
    eps = span * span * 1e-14

    def convexity(k):
        return _cross(xy[prev[k]], xy[k], xy[nxt[k]])

    reflex = {k for k in range(n) if convexity(k) <= eps}
    tris = []
    remaining, k, stall = n, 0, 0
    while remaining > 3:
        a, c = prev[k], nxt[k]
        ear = convexity(k) > eps
        _charge(budget, 1 + len(reflex) if ear else 1)  # a hostile outline can stall round after round
        if ear:
            pa, pb, pc = xy[a], xy[k], xy[c]
            for r in reflex:
                if r in (a, k, c):
                    continue
                q = xy[r]
                if q == pa or q == pb or q == pc:
                    continue
                if _in_triangle(pa, pb, pc, q):
                    ear = False
                    break
        if not ear:
            stall += 1
            if stall < remaining:
                k = nxt[k]
                continue
            # no ear in a whole round (a self-touching or degenerate outline): clip the most convex vertex
            _charge(budget, remaining)
            best, j = None, k
            for _ in range(remaining):
                v = convexity(j)
                if best is None or v > best:
                    best, k = v, j
                j = nxt[j]
            a, c = prev[k], nxt[k]
        if len({ring[a], ring[k], ring[c]}) == 3:
            tris.append((ring[a], ring[k], ring[c]))
        nxt[a], prev[c] = c, a
        reflex.discard(k)
        remaining -= 1
        for j in (a, c):
            if convexity(j) <= eps:
                reflex.add(j)
            else:
                reflex.discard(j)
        k, stall = c, 0
    a, c = prev[k], nxt[k]
    if len({ring[a], ring[k], ring[c]}) == 3:
        tris.append((ring[a], ring[k], ring[c]))
    return tris


def triangulate(pts, outer, holes=(), budget=None):
    """Counter-clockwise triangles (index triples into pts, (x, y) each) of the counter-clockwise polygon outer
    with the clockwise holes; CapError when a hole cannot be bridged or the work passes budget, a one-item list of
    steps left that calls can share (None: MAX_CLIP_STEPS for this call)."""
    if budget is None:
        budget = [MAX_CLIP_STEPS]
    ring = list(outer)
    for hole in sorted(holes, key=lambda h: -max(pts[i][0] for i in h)):
        _charge(budget, 3 * len(ring) + len(hole))  # _bridge walks the ring up to three times, the hole once
        ring = _bridge(pts, ring, list(hole))
    return _earclip(pts, ring, budget)


# The mesh

def _nest(loops, issues):
    """{solid: [holes]} for the closed polylines (index -> (x, y) points, counter-clockwise or not): the depth of
    each in the others, even = solid; a hole belongs to its innermost container. None when that takes more than
    MAX_NEST_TESTS point-edge tests (an issue)."""
    areas = {j: abs(_area(xy)) for j, xy in loops.items()}
    boxes = {j: (min(p[0] for p in xy), min(p[1] for p in xy), max(p[0] for p in xy), max(p[1] for p in xy))
             for j, xy in loops.items()}
    containers = {j: [] for j in loops}
    tests = 0
    for i in loops:
        bi = boxes[i]
        for j in loops:
            bj = boxes[j]
            if i == j or areas[j] <= areas[i] or bi[0] < bj[0] or bi[1] < bj[1] or bi[2] > bj[2] or bi[3] > bj[3]:
                continue
            outer = loops[j]
            for p in loops[i]:  # the first point not on outer's boundary decides
                tests += len(outer)
                if tests > MAX_NEST_TESTS:
                    issues.append("%d closed splines take more than %d tests to nest: no caps" %
                                  (len(loops), MAX_NEST_TESTS))
                    return None
                r = _inside(p, outer)
                if r is not None:
                    if r:
                        containers[i].append(j)
                    break
    solids = {j: [] for j in loops if len(containers[j]) % 2 == 0}
    for j in loops:
        if j in solids:
            continue
        parent = min(containers[j], key=lambda c: areas[c])
        if parent in solids:
            solids[parent].append(j)
        else:
            issues.append("an outline overlaps another: its hole is left open")
    return solids


def _side_groups(hard, closed, columns, smooth):
    if not smooth:
        return [0] * columns
    if not closed:
        out, run = [], 0
        for k in range(columns):
            if k and hard[k]:
                run += 1
            out.append(1 << (run % 2))
        return out
    corners = [k for k in range(columns) if hard[k]]
    if not corners:
        return [1] * columns
    out = [0] * columns
    start = corners[0]
    if len(corners) == 1:  # one corner: a chain of groups that meet everywhere but there
        for step in range(columns):
            out[(start + step) % columns] = 1 if step == 0 else 3 if step == 1 and columns > 2 else 2
        return out
    run, runs = -1, len(corners)
    for step in range(columns):
        k = (start + step) % columns
        if hard[k]:
            run += 1
        out[k] = 4 if runs % 2 and run == runs - 1 else 1 << (run % 2)
    return out


def _estimate(shape):
    """The most points the polylines of shape can have: known before any is interpolated."""
    per = (1 << ADAPTIVE_DEPTH) if shape.adaptive else shape.steps + 1
    return sum(len(sp.knots) * per + 1 for sp in shape.splines)


def _sides(numpy, pl, base, first, params, side_id):
    """(loops, groups, materials, map loops, map vertices) of the sides of a polyline: a grid of segments x columns,
    its vertices from base, its map vertices from first."""
    n, segs = len(pl.points), params.segments
    columns = n if pl.closed else n - 1
    k = numpy.arange(columns, dtype=numpy.int32)  # indices stay below MAX_VERTICES
    level = numpy.arange(segs, dtype=numpy.int32)[:, None]
    low, high = base + level * n, base + (level + 1) * n
    k1 = (k + 1) % n
    quads = [low + k, low + k1, high + k1, high + k]
    row = columns + 1
    mlow, mhigh = first + level * row, first + (level + 1) * row
    mquads = [mlow + k, mlow + k + 1, mhigh + k + 1, mhigh + k]
    if params.amount < 0:  # downwards: the same faces the other way round keep facing out
        quads = [quads[0], quads[3], quads[2], quads[1]]
        mquads = [mquads[0], mquads[3], mquads[2], mquads[1]]
    loops = numpy.stack(quads, axis=-1).reshape(-1)
    groups = numpy.tile(numpy.asarray(_side_groups(pl.hard, pl.closed, columns, params.smooth), dtype=numpy.uint32),
                        segs)
    mats = numpy.full(segs * columns, side_id, dtype=numpy.uint16)
    if not params.mapping:
        return loops, groups, mats, None, None
    p = numpy.asarray(pl.points, dtype=numpy.float64)
    nxt = numpy.roll(p, -1, axis=0)[:columns]
    lengths = numpy.concatenate(([0.0], numpy.cumsum(numpy.linalg.norm(nxt - p[:columns], axis=1))))
    if not params.real_world:
        lengths = lengths / lengths[-1] if lengths[-1] else numpy.zeros_like(lengths)
    vs = numpy.arange(segs + 1, dtype=numpy.float64) / segs
    if params.real_world:
        vs = vs * abs(params.amount)
    uvw = numpy.zeros((segs + 1, row, 3), dtype=numpy.float32)
    uvw[:, :, 0] = lengths[None, :]
    uvw[:, :, 1] = vs[:, None]
    return loops, groups, mats, numpy.stack(mquads, axis=-1).reshape(-1), uvw.reshape(-1, 3)


def _caps(closed, solids, issues):
    """{solid: [[(polyline, point), ...]]}: each cap polygon counter-clockwise; a holed cap that cannot be
    triangulated is left out (an issue; those after the budget is spent, one issue for all)."""
    out = {}
    budget = [MAX_CLIP_STEPS]  # shared: many holed caps must not each take the whole budget
    spent = 0
    for s, hs in solids.items():
        if not hs:
            out[s] = [[(s, k) for k in range(len(closed[s]))]]
            continue
        if budget[0] < 0:
            spent += 1
            continue
        count = len(closed[s]) + sum(len(closed[x]) for x in hs)
        if count > MAX_CAP_POINTS:
            issues.append("a cap of %d points with holes, more than %d: left open" % (count, MAX_CAP_POINTS))
            continue
        ids = [(j, k) for j in [s] + hs for k in range(len(closed[j]))]
        index = {key: i for i, key in enumerate(ids)}
        pts = [closed[j][k] for j, k in ids]
        try:
            tris = triangulate(pts, [index[(s, k)] for k in range(len(closed[s]))],
                               [[index[(x, k)] for k in range(len(closed[x]))] for x in hs], budget)
        except CapError as exc:
            issues.append("a cap with holes is left open: %s" % exc)
            continue
        out[s] = [[ids[i] for i in t] for t in tris]
    if spent:
        issues.append("%d more cap%s with holes left open: no steps left" % (spent, "" if spent == 1 else "s"))
    return out


def extrude(shape, params):
    """(MeshData, issues) of a reader Shape under an Extrude with params, in the shape's object space."""
    import numpy
    issues = []
    segs = params.segments
    levels = segs + 1
    most = _estimate(shape) * levels
    if most > MAX_VERTICES:  # before any point is made: a small file can ask for hundreds of millions
        raise ExtrudeError("up to %d vertices, more than %d" % (most, MAX_VERTICES))
    lines = polylines(shape)
    if params.amount == 0:
        issues.append("an amount of 0: a flat mesh")
    closed = {j: [(p[0], p[1]) for p in pl.points] for j, pl in enumerate(lines) if pl.closed}
    solids, nested = {}, False
    if len(closed) > MAX_LOOPS:
        issues.append("%d closed splines, more than %d: no caps" % (len(closed), MAX_LOOPS))
    elif closed:
        solids = _nest(closed, issues)
        nested = solids is not None
        solids = solids or {}
    if nested:  # solids counter-clockwise, holes (those left open too) clockwise
        for j in closed:
            if (_area(closed[j]) > 0) != (j in solids):
                pl = lines[j]
                pts, hard = pl.points[::-1], pl.hard[::-1]
                lines[j] = Polyline(pts[-1:] + pts[:-1], hard[-1:] + hard[:-1], True)  # the first point first
                closed[j] = [(p[0], p[1]) for p in lines[j].points]

    base, start = [], 0
    for pl in lines:
        base.append(start)
        start += len(pl.points) * levels
    positions = numpy.empty((start, 3), dtype=numpy.float64)
    rise = params.amount * numpy.arange(levels, dtype=numpy.float64) / segs
    for j, pl in enumerate(lines):
        block = numpy.tile(numpy.asarray(pl.points, dtype=numpy.float64), (levels, 1))
        block[:, 2] += numpy.repeat(rise, len(pl.points))
        positions[base[j]:base[j] + len(block)] = block
    if not (numpy.abs(positions) < float(numpy.finfo(numpy.float32).max)).all():
        raise ExtrudeError("the mesh does not fit single precision (amount %g)" % params.amount)

    side_id = SIDE_ID if params.material_ids else 0
    loop_parts, total_parts, group_parts, mat_parts, map_parts, uvw_parts = [], [], [], [], [], []
    mapped = 0
    for j, pl in enumerate(lines):
        loops, groups, mats, mloops, uvw = _sides(numpy, pl, base[j], mapped, params, side_id)
        loop_parts.append(loops)
        total_parts.append(numpy.full(len(groups), 4, dtype=numpy.int32))
        group_parts.append(groups)
        mat_parts.append(mats)
        if params.mapping:
            map_parts.append(mloops)
            uvw_parts.append(uvw)
            mapped += len(uvw)

    caps = ([0] if params.cap_start else []) + ([segs] if params.cap_end else [])
    cap_faces = _caps(closed, solids, issues) if solids and caps else {}
    faces, cap_mats, map_faces, cap_uvw = [], [], [], []
    if cap_faces:
        xs = [p[0] for j in solids for p in closed[j]]
        ys = [p[1] for j in solids for p in closed[j]]
        x0, y0 = min(xs), min(ys)
        w, h = max(xs) - x0, max(ys) - y0
    for level in caps:
        up = (level == segs) == (params.amount >= 0)  # this cap faces +Z
        mat = (TOP_ID if up else BOTTOM_ID) if params.material_ids else 0
        index = {}
        for polys in cap_faces.values():
            for poly in polys:
                loop = poly if up else poly[::-1]
                faces.append([base[j] + level * len(lines[j].points) + k for j, k in loop])
                cap_mats.append(mat)
                if not params.mapping:
                    continue
                for j, k in loop:
                    if (j, k) not in index:
                        x, y = closed[j][k]
                        u, v = x - x0, y - y0
                        if not params.real_world:
                            u, v = (u / w if w else 0.0), (v / h if h else 0.0)
                        index[(j, k)] = mapped + len(cap_uvw)
                        cap_uvw.append((u, v, 0.0))
                map_faces.append([index[(j, k)] for j, k in loop])
    if faces:
        loop_parts.append(numpy.asarray([v for f in faces for v in f], dtype=numpy.int64))
        total_parts.append(numpy.asarray([len(f) for f in faces], dtype=numpy.int64))
        group_parts.append(numpy.full(len(faces), CAP_GROUP, dtype=numpy.uint32))
        mat_parts.append(numpy.asarray(cap_mats, dtype=numpy.uint16))
        if params.mapping:
            map_parts.append(numpy.asarray([v for f in map_faces for v in f], dtype=numpy.int64))
            uvw_parts.append(numpy.asarray(cap_uvw, dtype=numpy.float64).reshape(-1, 3))

    def joined(parts, dtype, shape=(0,)):
        return numpy.concatenate(parts).astype(dtype) if parts else numpy.zeros(shape, dtype=dtype)

    totals = joined(total_parts, numpy.int64)
    starts = numpy.zeros(len(totals), dtype=numpy.int32)
    if len(totals):
        starts[1:] = numpy.cumsum(totals[:-1])
    maps = {}
    if params.mapping:
        maps[1] = geometry.MapChannel(1, joined(uvw_parts, numpy.float32, (0, 3)), joined(map_parts, numpy.int32))
    data = geometry.MeshData(positions.astype(numpy.float32), joined(loop_parts, numpy.int32), starts,
                             joined(group_parts, numpy.uint32), joined(mat_parts, numpy.uint16), maps)
    return data, issues
