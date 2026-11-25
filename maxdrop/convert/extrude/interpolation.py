# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A shape's splines as polylines: Bezier steps as 3ds Max interpolates them (Interpolation)."""
import math

from ...reader import shapes
from .params import ADAPTIVE_ANGLE, ADAPTIVE_DEPTH, ExtrudeError, Polyline, STRAIGHT_AT


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


def _turn(a, b):
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    c = (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (na * nb)
    return math.acos(max(-1.0, min(1.0, c)))


def _bent(p0, c1, c2, p3, a, b, pa, pb):
    """Whether the piece [a, b] of the curve, from pa to pb, fails _straight's test."""
    for f in STRAIGHT_AT:
        s = _bezier(p0, c1, c2, p3, a + f * (b - a))
        if _turn(_sub(s, pa), _sub(pb, s)) > ADAPTIVE_ANGLE:
            return True
    return False


def _straight(p0, c1, c2, p3):
    """Whether 3ds Max's Optimize and Adaptive call a curve segment straight: at t 0.4 and at 0.6 the curve's point S
    turns the path p0 -> S -> p3 by at most ADAPTIVE_ANGLE (3ds Max 2020, maxdrop-em3.142). A vector a little off the
    chord passes (2 degrees: about 2 % of the chord at a third), as an S whose middle is on the chord does; vectors
    on the chord's line fail once S lies past an end (the curve folds back)."""
    if p0 == p3:  # S comes back off the point by rounding, turning 180 degrees: only vectors on it are straight
        return c1 == p0 and c2 == p3
    return not _bent(p0, c1, c2, p3, 0.0, 1.0, p0, p3)


def _adaptive(p0, c1, c2, p3, room):
    """[(t, point)] of Adaptive's steps on a curved segment, in order: 3ds Max 2020 splits it at its middle and each
    piece again while the piece fails the straight test and is wider than 2^-ADAPTIVE_DEPTH (maxdrop-6n0.6.11). The
    whole segment is split without a test (it failed it). Stops once it has more than room steps."""
    out = []
    todo = [(0.0, 1.0, p0, p3, 0)]  # a stack of pieces: (a, b, B(a), B(b), depth)
    while todo:
        a, b, pa, pb, depth = todo.pop()
        if depth >= ADAPTIVE_DEPTH or (depth and not _bent(p0, c1, c2, p3, a, b, pa, pb)):
            continue
        m = (a + b) / 2
        pm = _bezier(p0, c1, c2, p3, m)
        todo.append((m, b, pm, pb, depth + 1))
        todo.append((a, m, pa, pm, depth + 1))
        out.append((m, pm))
        if len(out) > room:
            break
    out.sort()
    return out


def _hard(knot):
    """Whether the sides' smoothing changes at knot: a corner or Bezier corner knot whatever the angle, or a Bezier
    knot with a vector exactly on its point (a pie Arc's from, center and to); never a smooth knot, nor a Bezier
    knot whose vectors are off its point, kinked or not (3ds Max 2020, maxdrop-em3.111)."""
    if knot.kind in (shapes.CORNER, shapes.BEZIER_CORNER):
        return True
    return knot.kind == shapes.BEZIER and (knot.in_vec == knot.point or knot.out_vec == knot.point)


def _polyline(spline, steps, optimize, adaptive, room):
    """The Polyline of a spline, or None when it has more than room points before equal ones are merged."""
    knots = spline.knots
    n = len(knots)
    closed = spline.closed
    pts, hard, ids, flat = [], [], [], []  # flat[k]: the edge leaving point k is straight (a straight segment's,
    # Optimize's test, or a curve's one chord)
    for k in range(n if closed else n - 1):
        a, b = knots[k], knots[(k + 1) % n]
        p0, p3 = a.point, b.point
        line = a.segment == shapes.LINE
        c1, c2 = (_lerp(p0, p3, 1 / 3.0), _lerp(p0, p3, 2 / 3.0)) if line else (a.out_vec, b.in_vec)
        straight = line or _straight(p0, c1, c2, p3)
        pts.append(p0)
        if adaptive:
            made = [] if straight else _adaptive(p0, c1, c2, p3, room - len(pts))
            count = len(made)
            pts.extend(pm for _t, pm in made)
        else:  # Optimize gives a segment back to the same spot no steps whatever its vectors (3ds Max 2020)
            count = 0 if optimize and (straight or p0 == p3) else steps
            if straight and p0 == p3:  # its steps on its point exactly: the Bezier sum can round them off it
                pts.extend([p0] * count)
            else:
                pts.extend(_bezier(p0, c1, c2, p3, s / (count + 1.0)) for s in range(1, count + 1))
        if len(pts) > room:
            return None
        hard.append(_hard(a))
        hard.extend([False] * count)
        flat.append(straight or count == 0)  # no steps: one chord, straight whatever the curve
        flat.extend([straight] * count)
        ids.extend([a.material] * (count + 1))
    if not closed and n:
        if len(pts) >= room:
            return None
        pts.append(knots[-1].point)
        hard.append(_hard(knots[-1]))
        flat.append(True)
        ids.append(0)  # no column leaves the last point
    # A zero-length segment is merged into one point (3ds Max keeps both, with faces of no area: docs/FORMAT.md,
    # Extrude); run[k]: point k stood for more than one.
    out_p, out_h, out_i, out_f, run = [], [], [], [], []
    for p, h, i, f in zip(pts, hard, ids, flat):
        if out_p and p == out_p[-1]:
            out_h[-1] = out_h[-1] or h
            out_i[-1] = i  # the column that leaves this point is the one that remains
            out_f[-1] = f
            run[-1] = True
            continue
        out_p.append(p)
        out_h.append(h)
        out_i.append(i)
        out_f.append(f)
        run.append(False)
    if closed and len(out_p) > 1 and out_p[0] == out_p[-1]:  # the last point on the first: one run with it
        out_h[0] = out_h[0] or out_h[-1]
        run[0] = True
        for column in (out_p, out_h, out_i, out_f, run):
            column.pop()
    if closed and len(out_p) < 3:
        closed = False
    # a straight edge into a run: 3ds Max, keeping its points, finds the spline touching itself there whatever the
    # edge out and the steps; after a curve's step its rounding decides, a straight edge out or not (MaxDrop: a cap)
    doubled = closed and any(r and out_f[k - 1] for k, r in enumerate(run))
    return Polyline(out_p, out_h, closed, out_i, doubled)


def polylines(shape, most=None):
    """[Polyline] of a reader Shape, one per spline of two points or more; ExtrudeError when its splines make more
    than most points (Adaptive's are known only once made): a spline is stopped once its points before merging pass
    what is left, and what it keeps after merging is taken from that."""
    out = []
    room = math.inf if most is None else most
    for sp in shape.splines:
        pl = _polyline(sp, shape.steps, shape.optimize, shape.adaptive, room)
        if pl is None:
            raise ExtrudeError("more than %d points to interpolate" % most)
        room -= len(pl.points)
        if len(pl.points) >= 2:
            out.append(pl)
    return out
