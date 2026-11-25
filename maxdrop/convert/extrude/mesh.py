# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mesh: nesting, self-crossing, the sides, the caps (morph and grid) and extrude()."""
import collections
import math

from ...reader import geometry
from .params import (
    BOTTOM_ID, CAP_GRID, CAP_GROUP, CapError, CROSS_CHUNK, ExtrudeError, GRID, GRID_DIVISIONS, GRID_MARGIN,
    GRID_MAX_DIVISIONS, GRID_SHIFT, GRID_SPAN, MAX_CAP_POINTS, MAX_CLIP_STEPS, MAX_CROSS_TESTS, MAX_GRID_CLIP_STEPS,
    MAX_GRID_TESTS, MAX_LOOPS, MAX_NEST_TESTS, MAX_VERTICES, SIDE_ID, TOP_ID,
)
from .interpolation import polylines
from .planar import _area, _inside, triangulate


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


def _turn_sign(numpy, o, e, f):
    """The sign of the turn o -> e -> f, row by row of (x, y) arrays."""
    return numpy.sign((e[:, 0] - o[:, 0]) * (f[:, 1] - o[:, 1]) - (e[:, 1] - o[:, 1]) * (f[:, 0] - o[:, 0]))


def _crosses(numpy, xy, tests):
    """Whether two edges of the closed polygon xy ((x, y) points) that do not follow each other meet: cross, touch
    or run over each other, without a tolerance, as 3ds Max finds it; adjacent edges never count. None when the edge
    pairs whose x ranges overlap are more than the tests left (a one-item list, charged before any is tested)."""
    n = len(xy)
    if n < 4:  # every edge follows every other
        return False
    p = numpy.asarray(xy, dtype=numpy.float64)
    q = numpy.roll(p, -1, axis=0)
    x0, x1 = numpy.minimum(p[:, 0], q[:, 0]), numpy.maximum(p[:, 0], q[:, 0])
    y0, y1 = numpy.minimum(p[:, 1], q[:, 1]), numpy.maximum(p[:, 1], q[:, 1])
    order = numpy.argsort(x0, kind="stable")
    # sweep: the edges after edge k in x order that start within its x range
    count = numpy.searchsorted(x0[order], x1[order], side="right") - numpy.arange(n) - 1
    total = int(count.sum())
    tests[0] -= total
    if tests[0] < 0:
        return None
    ends = numpy.cumsum(count)
    lo = 0
    while lo < n:
        hi = max(int(numpy.searchsorted(ends, ends[lo] - count[lo] + CROSS_CHUNK, side="right")), lo + 1)
        c = count[lo:hi]
        a = numpy.repeat(numpy.arange(lo, hi), c)
        b = a + 1 + numpy.arange(len(a)) - numpy.repeat(numpy.cumsum(c) - c, c)
        i, j = order[a], order[b]
        gap = numpy.abs(i - j)
        keep = (gap != 1) & (gap != n - 1) & (y0[i] <= y1[j]) & (y0[j] <= y1[i])
        i, j = i[keep], j[keep]
        lo = hi
        if not len(i):
            continue
        pa, pb, pc, pd = p[i], q[i], p[j], q[j]
        # on opposite sides or on the line, both ways; four zeros: collinear, and the boxes overlap
        ab = _turn_sign(numpy, pa, pb, pc) * _turn_sign(numpy, pa, pb, pd)
        cd = _turn_sign(numpy, pc, pd, pa) * _turn_sign(numpy, pc, pd, pb)
        if ((ab <= 0) & (cd <= 0)).any():
            return True
    return False


def _crossed(numpy, lines, closed, capped, issues):
    """{j}: the closed polylines that cross, touch or run over themselves (_crosses), or lost a zero-length segment
    after a straight edge (Polyline.doubled): 3ds Max gives them no cap and leaves them out of the nesting. With
    capped, one issue counts them and one more those past MAX_CROSS_TESTS (capped unchecked)."""
    out, tests, unchecked = set(), [MAX_CROSS_TESTS], 0
    for j, xy in closed.items():
        r = True if lines[j].doubled else _crosses(numpy, xy, tests)
        if r is None:
            unchecked += 1
        elif r:
            out.add(j)
    if capped and out:
        issues.append("%d closed spline%s that cross%s or touch%s %s: no cap, as in 3ds Max" %
                      ((len(out), "", "es", "es", "itself") if len(out) == 1 else
                       (len(out), "s", "", "", "themselves")))
    if capped and unchecked:
        issues.append("%d closed spline%s not checked for crossings (more than %d tests): capped" %
                      (unchecked, "" if unchecked == 1 else "s", MAX_CROSS_TESTS))
    return out


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
    """The most points the polylines of shape can have, known before any is interpolated; Adaptive's steps are not
    known (up to 2047 a segment): they are counted as they are made (polylines)."""
    per = 1 if shape.adaptive else shape.steps + 1
    return sum(len(sp.knots) * per + 1 for sp in shape.splines)


def _sides(numpy, pl, base, first, params, side_id):
    """(loops, groups, materials, map loops, map vertices) of the sides of a polyline: a grid of segments x columns,
    its vertices from base, its map vertices from first; side_id None: each column its segment's material ID."""
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
    if side_id is None:
        mats = numpy.tile(numpy.asarray(pl.ids[:columns], dtype=numpy.uint16), segs)
    else:
        mats = numpy.full(segs * columns, side_id, dtype=numpy.uint16)
    if not params.mapping:
        return loops, groups, mats, None, None
    p = numpy.asarray(pl.points, dtype=numpy.float64)
    nxt = numpy.roll(p, -1, axis=0)[:columns]
    lengths = numpy.concatenate(([0.0], numpy.cumsum(numpy.linalg.norm(nxt - p[:columns], axis=1))))
    if not params.real_world:
        lengths = lengths / lengths[-1] if lengths[-1] else numpy.zeros_like(lengths)
    # V 0 at the shape and 1 at the far level, but downwards 0 at the far level (z = amount), 1 at the shape;
    # Real-World Map Size: times the signed amount, so downwards from the amount at the shape to 0 (3ds Max 2020)
    vs = numpy.arange(segs + 1, dtype=numpy.float64)
    if params.amount < 0:
        vs = vs[::-1]
    vs = vs / segs
    if params.real_world:
        vs = vs * params.amount
    uvw = numpy.zeros((segs + 1, row, 3), dtype=numpy.float32)
    uvw[:, :, 0] = lengths[None, :]
    uvw[:, :, 1] = vs[:, None]
    return loops, groups, mats, numpy.stack(mquads, axis=-1).reshape(-1), uvw.reshape(-1, 3)


def _divisions(span, sizes):
    """3ds Max's grid divisions along one axis of a solid span across: 20, raised by each hole of extent s on that
    axis to floor(0.95 x span / (s / 2)), at most 50."""
    n = GRID_DIVISIONS
    for s in sizes:
        if s > 0:
            r = GRID_SPAN * span / (s / 2.0)
            n = max(n, GRID_MAX_DIVISIONS if not r < GRID_MAX_DIVISIONS else int(math.floor(r)))
    return n


def _charge_grid(tests, count):
    tests[0] -= count
    if tests[0] < 0:
        raise CapError("more than %d tests to lay out the grids" % MAX_GRID_TESTS)


def _grid(numpy, outline, holes, tests):
    """(points, quads, loops) of a solid's grid, None when no cell of it lies wholly inside the solid: points the
    grid points (x, y) that are corners of such a cell, quads those cells counter-clockwise and loops the boundary of
    their union (point indices, the cells on the right), both as indices into points. outline counter-clockwise,
    holes clockwise; tests a one-item list of point-edge tests left (CapError when spent)."""
    rings = [numpy.asarray(r, dtype=numpy.float64) for r in [outline] + list(holes)]
    lo, hi = rings[0].min(axis=0), rings[0].max(axis=0)
    w, h = float(hi[0] - lo[0]), float(hi[1] - lo[1])
    if not (w > 0 and h > 0):
        return None
    nx = _divisions(w, [float(numpy.ptp(r[:, 0])) for r in rings[1:]])
    ny = _divisions(h, [float(numpy.ptp(r[:, 1])) for r in rings[1:]])
    dx, dy = GRID_SPAN * w / nx, GRID_SPAN * h / ny
    xs = lo[0] + GRID_MARGIN * w + dx * (numpy.arange(nx + 1) + GRID_SHIFT)
    ys = lo[1] + GRID_MARGIN * h + dy * (numpy.arange(ny + 1) + GRID_SHIFT)
    a = numpy.concatenate(rings)
    b = numpy.concatenate([numpy.roll(r, -1, axis=0) for r in rings])
    _charge_grid(tests, (ny + 1) * len(a))
    # even-odd per row: the x where each edge crosses the row, counted right of each grid point
    ay, by = a[:, 1][None, :], b[:, 1][None, :]
    row = ys[:, None]
    crossing = (ay > row) != (by > row)
    with numpy.errstate(divide="ignore", invalid="ignore"):
        cx = a[:, 0][None, :] + (row - ay) * (b[:, 0] - a[:, 0])[None, :] / (by - ay)
    inside = numpy.zeros((ny + 1, nx + 1), dtype=bool)
    for j in range(ny + 1):
        at = numpy.sort(cx[j][crossing[j]])
        inside[j] = (len(at) - numpy.searchsorted(at, xs, side="right")) % 2 == 1
    filled = inside[:-1, :-1] & inside[:-1, 1:] & inside[1:, :-1] & inside[1:, 1:]
    # a cell an outline or hole edge touches is not wholly inside (a slit, a hole within the cell)
    for p, q in zip(a, b):
        x0, x1 = min(p[0], q[0]), max(p[0], q[0])
        y0, y1 = min(p[1], q[1]), max(p[1], q[1])
        if x1 < xs[0] or x0 > xs[-1] or y1 < ys[0] or y0 > ys[-1]:
            continue
        i0, i1 = (min(max(int(math.floor((v - xs[0]) / dx)), 0), nx - 1) for v in (x0, x1))
        j0, j1 = (min(max(int(math.floor((v - ys[0]) / dy)), 0), ny - 1) for v in (y0, y1))
        if not filled[j0:j1 + 1, i0:i1 + 1].any():
            continue
        _charge_grid(tests, (i1 - i0 + 1) * (j1 - j0 + 1))
        rx0, rx1 = xs[i0:i1 + 1][None, :], xs[i0 + 1:i1 + 2][None, :]
        ry0, ry1 = ys[j0:j1 + 1][:, None], ys[j0 + 1:j1 + 2][:, None]
        d = q - p
        t0 = numpy.zeros((j1 - j0 + 1, i1 - i0 + 1))
        t1 = numpy.ones_like(t0)
        hit = numpy.ones(t0.shape, dtype=bool)
        for pk, qk in ((-d[0], p[0] - rx0), (d[0], rx1 - p[0]), (-d[1], p[1] - ry0), (d[1], ry1 - p[1])):
            qk = numpy.broadcast_to(qk, t0.shape)
            if pk == 0:
                hit &= qk >= 0
                continue
            t = qk / pk
            if pk < 0:
                t0 = numpy.maximum(t0, t)
            else:
                t1 = numpy.minimum(t1, t)
        filled[j0:j1 + 1, i0:i1 + 1] &= ~(hit & (t0 <= t1))
    if not filled.any():
        return None
    kept = numpy.zeros((ny + 1, nx + 1), dtype=bool)
    for dj in (0, 1):
        for di in (0, 1):
            kept[dj:ny + dj, di:nx + di] |= filled
    index = numpy.full(kept.shape, -1, dtype=numpy.int64)
    jj, ii = numpy.nonzero(kept)
    index[jj, ii] = numpy.arange(len(jj))
    points = list(zip(xs[ii].tolist(), ys[jj].tolist()))
    cj, ci = numpy.nonzero(filled)
    quads = numpy.stack([index[cj, ci], index[cj, ci + 1], index[cj + 1, ci + 1], index[cj + 1, ci]], axis=1)
    return points, quads.tolist(), _cell_loops(filled, index)


def _cell_loops(filled, index):
    """The boundary loops of the union of the filled cells as indices of their corners, each run with the cells on
    its right (clockwise round a group of cells, counter-clockwise round a gap in it); where two cells touch only at
    a corner the loop turns right, so each loop hugs its own cells."""
    ny, nx = filled.shape

    def cell(j, i):
        return 0 <= j < ny and 0 <= i < nx and bool(filled[j, i])

    out = {}  # corner (i, j) -> the corners the boundary runs on to
    rows, cols = filled.nonzero()
    for j, i in zip(rows.tolist(), cols.tolist()):
        for ok, a, b in ((cell(j, i - 1), (i, j), (i, j + 1)), (cell(j + 1, i), (i, j + 1), (i + 1, j + 1)),
                         (cell(j, i + 1), (i + 1, j + 1), (i + 1, j)), (cell(j - 1, i), (i + 1, j), (i, j))):
            if not ok:
                out.setdefault(a, []).append(b)
    loops = []
    # start where one edge leaves where there is one: the walk then closes where it began
    for start in sorted(out, key=lambda c: (len(out[c]) != 1, c)):
        while out[start]:
            loop, prev, at = [], None, start
            while True:
                nxt = out[at]
                if len(nxt) > 1 and prev is not None:
                    din = (at[0] - prev[0], at[1] - prev[1])
                    nxt.sort(key=lambda c: din[0] * (c[1] - at[1]) - din[1] * (c[0] - at[0]))
                loop.append(int(index[at[1], at[0]]))
                prev, at = at, nxt.pop(0)
                if at == start:
                    break
            loops.append(loop)
    return loops


def _splice(rings):
    """The rings (point index lists) with every two that share a point joined there into one: holes whose cells
    touch only at a corner, which a bridge cannot take one by one."""
    out = []
    for ring in rings:
        ring = list(ring)
        joined = True
        while joined:
            joined = False
            for k, other in enumerate(out):
                shared = set(ring) & set(other)
                if shared:
                    v = min(shared)
                    a, b = other.index(v), ring.index(v)
                    ring = other[a:] + other[:a] + ring[b:] + ring[:b]
                    del out[k]
                    joined = True
                    break
        out.append(ring)
    return out


def _grid_cap(numpy, closed, s, hs, first, room, tests, budget):
    """(polygons, points) of solid s's grid cap: polygons of keys, (polyline, point) or (GRID, first + i), counter-
    clockwise; points the grid points it adds, at most room. None when no cell is whole (a morph cap); CapError when
    the grid or its band cannot be made, or the band's triangles do not tile it."""
    g = _grid(numpy, closed[s], [closed[x] for x in hs], tests)
    if g is None:
        return None
    points, quads, cell_loops = g
    if len(points) > room:
        raise CapError("past %d vertices" % MAX_VERTICES)
    keys = [(s, k) for k in range(len(closed[s]))]
    rings = [list(range(len(keys)))]
    for x in hs:
        rings.append([len(keys) + k for k in range(len(closed[x]))])
        keys.extend((x, k) for k in range(len(closed[x])))
    xy = [closed[j][k] for j, k in keys]
    offset = len(keys)
    keys.extend((GRID, first + i) for i in range(len(points)))
    xy.extend(points)
    rings.extend([[offset + i for i in loop] for loop in cell_loops])
    nest_issues = []
    regions = _nest({r: [xy[i] for i in ring] for r, ring in enumerate(rings)}, nest_issues)
    if regions is None or nest_issues:
        raise CapError("its band does not nest")
    lo, hi = numpy.min(xy, axis=0), numpy.max(xy, axis=0)
    tolerance = 1e-9 * float((hi[0] - lo[0]) * (hi[1] - lo[1]))
    polys = [[keys[offset + i] for i in quad] for quad in quads]
    for r, inner in regions.items():
        outer = rings[r] if _area([xy[i] for i in rings[r]]) > 0 else rings[r][::-1]
        holes = _splice([rings[x] if _area([xy[i] for i in rings[x]]) < 0 else rings[x][::-1] for x in inner])
        try:
            tris = triangulate(xy, outer, holes, budget)
        except CapError:
            if budget[0] < 0:
                raise CapError("more than %d steps to triangulate the grid bands" % MAX_GRID_CLIP_STEPS) from None
            raise
        areas = [_area([xy[i] for i in t]) for t in tris]
        want = _area([xy[i] for i in outer]) + sum(_area([xy[i] for i in h]) for h in holes)
        spread = abs(sum(abs(a) for a in areas) - want)
        if (areas and min(areas) < -tolerance) or spread > 100 * tolerance + 1e-9 * want:
            raise CapError("its band does not triangulate")
        polys.extend([keys[i] for i in t] for t in tris)
    return polys, points


def _morph_cap(closed, s, hs, budget, issues):
    """(polygons, spent) of solid s's morph cap: polygons None when it is left open (an issue, or spent: the
    mesh's clip budget is gone, counted by the caller)."""
    if not hs:
        return [[(s, k) for k in range(len(closed[s]))]], False
    if budget[0] < 0:
        return None, True
    count = len(closed[s]) + sum(len(closed[x]) for x in hs)
    if count > MAX_CAP_POINTS:
        issues.append("a cap of %d points with holes, more than %d: left open" % (count, MAX_CAP_POINTS))
        return None, False
    ids = [(j, k) for j in [s] + hs for k in range(len(closed[j]))]
    index = {key: i for i, key in enumerate(ids)}
    pts = [closed[j][k] for j, k in ids]
    try:
        tris = triangulate(pts, [index[(s, k)] for k in range(len(closed[s]))],
                           [[index[(x, k)] for k in range(len(closed[x]))] for x in hs], budget)
    except CapError as exc:
        issues.append("a cap with holes is left open: %s" % exc)
        return None, False
    return [[ids[i] for i in t] for t in tris], False


def _caps(closed, solids, issues, grid=False, numpy=None, room=0):
    """({solid: [[(polyline, point) or (GRID, i), ...]]}, grid points): each cap polygon counter-clockwise; a holed
    cap that cannot be triangulated is left out (an issue; those after the budget is spent, one issue for all). With
    grid, each solid gets its grid cap while the grid points stay within room (each a vertex per cap); a grid cap
    that cannot be made is a morph cap (an issue per reason; a holed one the morph cap leaves open is named only as
    open). The grid bands have a clip budget of their own, so a refused grid never starves the morph caps."""
    out = {}
    budget = [MAX_CLIP_STEPS]  # shared: many holed caps must not each take the whole budget
    grid_budget = [MAX_GRID_CLIP_STEPS]
    tests = [MAX_GRID_TESTS]
    points, morph = [], collections.Counter()
    spent = 0
    for s, hs in solids.items():
        reason = None
        if grid:
            if len(closed[s]) + sum(len(closed[x]) for x in hs) > MAX_CAP_POINTS:
                reason = "more than %d outline points" % MAX_CAP_POINTS
            elif tests[0] < 0:  # spent by an earlier solid: the same reason
                reason = "more than %d tests to lay out the grids" % MAX_GRID_TESTS
            elif grid_budget[0] < 0:
                reason = "more than %d steps to triangulate the grid bands" % MAX_GRID_CLIP_STEPS
            elif len(points) >= room:
                reason = "past %d vertices" % MAX_VERTICES
            else:
                made = None
                try:
                    made = _grid_cap(numpy, closed, s, hs, len(points), room - len(points), tests, grid_budget)
                except CapError as exc:
                    reason = str(exc)
                if made is not None:
                    out[s] = made[0]
                    points.extend(made[1])
                    continue
        polys, ran_out = _morph_cap(closed, s, hs, budget, issues)
        spent += ran_out
        if polys is not None:
            out[s] = polys
            if reason:
                morph[reason] += 1
    for reason, n in sorted(morph.items()):
        issues.append("%d grid cap%s made as morph cap%s: %s" % (n, "" if n == 1 else "s", "" if n == 1 else "s",
                                                                  reason))
    if spent:
        issues.append("%d more cap%s with holes left open: no steps left" % (spent, "" if spent == 1 else "s"))
    return out, points


def extrude(shape, params):
    """(MeshData, issues) of a reader Shape under an Extrude with params, in the shape's object space."""
    import numpy
    issues = []
    segs = params.segments
    levels = segs + 1
    most = _estimate(shape) * levels
    if most > MAX_VERTICES:  # before any point is made: a small file can ask for hundreds of millions
        raise ExtrudeError("up to %d vertices, more than %d" % (most, MAX_VERTICES))
    try:
        lines = polylines(shape, MAX_VERTICES // levels)
    except ExtrudeError:  # Adaptive's points were made before they were counted: charged like the sides they make
        raise ExtrudeError("more than %d vertices" % MAX_VERTICES, MAX_VERTICES // levels * segs * 4) from None
    if params.amount == 0:
        issues.append("an amount of 0: a flat mesh")
    closed = {j: [(p[0], p[1]) for p in pl.points] for j, pl in enumerate(lines) if pl.closed}
    # a spline that crosses itself is no cap, no hole and no container, and keeps its own direction (3ds Max 2020)
    for j in _crossed(numpy, lines, closed, params.cap_start or params.cap_end, issues):
        del closed[j]
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
                # the whole polyline turned, its last point now first, as 3ds Max turns it (arc_pie_reverse: the
                # side U starts there); column k now runs where column n - 2 - k ran, the last where it ran
                ids = pl.ids[::-1]
                lines[j] = pl._replace(points=pl.points[::-1], hard=pl.hard[::-1], ids=ids[1:] + ids[:1])
                closed[j] = [(p[0], p[1]) for p in lines[j].points]

    base, start = [], 0
    for pl in lines:
        base.append(start)
        start += len(pl.points) * levels
    # Cap Start is the bottom cap and Cap End the top one: downwards Cap Start lies at the far level (3ds Max 2020)
    bottom, top = (0, segs) if params.amount >= 0 else (segs, 0)
    caps = ([bottom] if params.cap_start else []) + ([top] if params.cap_end else [])
    cap_faces, grid = {}, []
    if solids and caps:
        cap_faces, grid = _caps(closed, solids, issues, params.cap_type == CAP_GRID, numpy,
                                (MAX_VERTICES - start) // len(caps))
    positions = numpy.empty((start + len(grid) * len(caps), 3), dtype=numpy.float64)
    rise = params.amount * numpy.arange(levels, dtype=numpy.float64) / segs
    for j, pl in enumerate(lines):
        block = numpy.tile(numpy.asarray(pl.points, dtype=numpy.float64), (levels, 1))
        block[:, 2] += numpy.repeat(rise, len(pl.points))
        positions[base[j]:base[j] + len(block)] = block
    for slot, level in enumerate(caps):  # each cap's own grid points, at z 0 plus the level's rise (3ds Max's)
        at = start + slot * len(grid)
        positions[at:at + len(grid), :2] = numpy.asarray(grid, dtype=numpy.float64).reshape(-1, 2)
        positions[at:at + len(grid), 2] = rise[level]
    if not (numpy.abs(positions) < float(numpy.finfo(numpy.float32).max)).all():
        raise ExtrudeError("the mesh does not fit single precision (amount %g)" % params.amount)

    side_id = (None if params.shape_ids else SIDE_ID) if params.material_ids else 0
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

    faces, cap_mats, map_faces, cap_uvw = [], [], [], []
    if cap_faces:
        xs = [p[0] for j in solids for p in closed[j]]
        ys = [p[1] for j in solids for p in closed[j]]
        x0, y0 = min(xs), min(ys)
        w, h = max(xs) - x0, max(ys) - y0
    for slot, level in enumerate(caps):
        up = level == top
        mat = (TOP_ID if up else BOTTOM_ID) if params.material_ids else 0
        index = {}
        first = start + slot * len(grid)
        for polys in cap_faces.values():
            for poly in polys:
                loop = poly if up else poly[::-1]
                faces.append([first + k if j == GRID else base[j] + level * len(lines[j].points) + k
                              for j, k in loop])
                cap_mats.append(mat)
                if not params.mapping:
                    continue
                for j, k in loop:
                    if (j, k) not in index:
                        x, y = grid[k] if j == GRID else closed[j][k]
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
