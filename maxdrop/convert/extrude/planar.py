# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""2D geometry of the caps: areas, point in polygon, holes bridged and ear clipping (triangulate())."""
import math

from .params import CapError, MAX_CLIP_STEPS


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
