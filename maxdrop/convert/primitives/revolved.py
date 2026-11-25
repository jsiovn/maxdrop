# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The primitives turned around an axis: Sphere, Cylinder (and its pie slice), Tube and Torus."""
import math

from .specs import _SEAM, _TAU
from .builder import _corners, _stack


def _pie(p):
    """(start, arc) of a primitive's Slice, radians: the part kept runs arc from start counterclockwise (start the
    slice's To angle, arc From - To in 0 .. 2 pi, 0 a whole turn); (0, 2 pi) without Slice."""
    if not p.slice:
        return 0.0, _TAU
    arc = math.fmod(p.slice_from - p.slice_to, _TAU)
    if arc <= 0.0:
        arc += _TAU
    return math.fmod(p.slice_to, _TAU), arc


def _sphere_rings(p):
    """(how many rings a Sphere has below its top pole, the polar angle in radians of its ring k (one-based), its
    cut: pi without a hemisphere). A hemisphere cuts at (1 - hemisphere) * 180 degrees: chopped, the rings keep
    their places every 360 / segs degrees down to the cut (counted in single precision as 3ds Max does: a ring
    that falls on the cut is doubled there), then a ring at the cut; squashed, segs // 2 - 1 rings spread down to
    the cut, the last on it."""
    n = p.segs
    h = min(max(p.hemisphere, 0.0), 0.9999)  # 3ds Max stops short of a point
    cut = (1.0 - h) * math.pi
    if cut >= math.pi:  # also a hemisphere too small to move the cut
        return n // 2 - 1, lambda k: k * _TAU / n, math.pi
    if p.squash:
        rows = n // 2 - 1
        step = cut / (n / 2.0 - 1.0)
        return rows, lambda k: k * step if k < rows else cut, cut
    import numpy
    f32 = numpy.float32
    cut32 = (f32(1.0) - f32(h)) * f32(math.pi)
    delta32 = f32(2.0) * f32(math.pi) / f32(n)
    kept = int(cut32 / delta32)
    # a step or two either way; bounded, as segments a file stores as a huge float leave k * delta32 unchanged
    for _ in range(4):
        if kept > 0 and not f32(kept) * delta32 <= cut32:
            kept -= 1
        elif f32(kept + 1) * delta32 <= cut32:
            kept += 1
    return kept + 1, lambda k: k * _TAU / n if k <= kept else cut, cut


def _sphere(b, p):
    """Rings from the top pole down, segs points around each from +Y turning towards -X (with Slice, segs + 1
    over the part kept, then a point on the axis); the bottom pole, a hemisphere's base center on the axis at the
    cut (with Slice, the last ring's axis point). Faces: the top fan, the quads between rings, the bottom fan or
    the hemisphere's base (ID 1, group 2); with Slice each row ends with the faces of its two cut planes (the
    end's ID 3, group 4, then the start's ID 4, group 8). U across the part kept as a fraction of a whole turn, V
    down the rows (1 - 2k / segs, a hemisphere's base center one row below its last ring); the cut planes U 0 on
    the axis, 1 at the rim."""
    np = b.np
    r, n = p.radius, p.segs
    smooth = p.smooth
    group, cap4, cap8, base_group = (1, 4, 8, 2) if smooth else (0, 0, 0, 0)
    rows, angle, cut = _sphere_rings(p)
    angles = [angle(k) for k in range(1, rows + 1)]
    hemi = cut != math.pi
    start, arc = _pie(p)
    pie = p.slice
    m = n + 1 if pie else n
    if p.base_to_pivot:
        lift = -r * math.cos(cut) if hemi else r
    else:
        lift = 0.0
    top = b.points((0.0, 0.0, r + lift))
    rho = np.array([r * math.sin(a) for a in angles], dtype=np.float64)[:, None]
    z = np.array([r * math.cos(a) for a in angles], dtype=np.float64)[:, None]
    phi = [start + j * arc / n for j in range(m)] if pie else [j * _TAU / n for j in range(n)]
    sin = np.array([math.sin(a) for a in phi], dtype=np.float64)
    cos = np.array([math.cos(a) for a in phi], dtype=np.float64)
    ring = _stack(np, -rho * sin, rho * cos, np.broadcast_to(z + lift, (len(angles), m)), dtype=np.float64)
    if pie:  # each ring's axis point after it
        ring = np.concatenate((ring, _stack(np, 0.0, 0.0, z + lift, dtype=np.float64)), axis=1)
    made = b.points(ring)
    rings, axis = made[:, :m], (made[:, m] if pie else None)
    if hemi:
        bottom = axis[-1] if pie else b.points((0.0, 0.0, r * math.cos(cut) + lift))
    else:
        bottom = b.points((0.0, 0.0, -r + lift))
    su, sv = (_TAU * abs(r), math.pi * abs(r)) if p.real_world else (1.0, 1.0)
    span = arc / _TAU if pie else 1.0

    def v_of(k):
        return 1.0 - 2.0 * k / n

    def uv(j, k):
        return (j / n * span * su, v_of(k) * sv)

    j = np.arange(n, dtype=np.int64)
    j1 = j + 1 if pie else (j + 1) % n
    last = rows

    rw = p.real_world
    z_rows = z[:, 0].tolist()
    rho_rows = rho[:, 0].tolist()
    widest, lowest = (max(rho_rows), min(z_rows)) if rows else (0.0, 0.0)

    def cap(k, rim, end):
        """The UV of a cut plane's corner on ring k (-1 the top pole), at the rim or on the axis, on the end's
        plane or the start's. Real-world: flat over the plane, U from the axis (from the widest ring on the end's
        plane), V up from the lowest ring."""
        if rw:
            rh = rho_rows[k] if rim and k >= 0 else 0.0
            return ((widest - rh) if end else rh, (r if k < 0 else z_rows[k]) - lowest)
        return (1.0 if rim else 0.0, v_of(k + 1))

    def one(verts, mat, grp, *corners):
        b.faces(np.array([verts]), mat, grp, _corners(np, *corners)[None])

    # the top fan
    b.faces(_stack(np, top, rings[0][j], rings[0][j1]), 1, group, _corners(np, uv(j, 0), uv(j, 1), uv(j + 1, 1)))
    if pie:
        one((top, rings[0][n], axis[0]), 2, cap4, cap(-1, False, True), cap(0, True, True), cap(0, False, True))
        one((top, axis[0], rings[0][0]), 3, cap8, cap(-1, False, False), cap(0, False, False), cap(0, True, False))
    for k in range(rows - 1):
        b.faces(_stack(np, rings[k][j], rings[k + 1][j], rings[k + 1][j1], rings[k][j1]), 1, group,
                _corners(np, uv(j, k + 1), uv(j, k + 2), uv(j + 1, k + 2), uv(j + 1, k + 1)))
        if pie:
            one((rings[k][n], rings[k + 1][n], axis[k + 1], axis[k]), 2, cap4,
                cap(k, True, True), cap(k + 1, True, True), cap(k + 1, False, True), cap(k, False, True))
            one((axis[k], axis[k + 1], rings[k + 1][0], rings[k][0]), 3, cap8,
                cap(k, False, False), cap(k + 1, False, False), cap(k + 1, True, False), cap(k, True, False))
    # the bottom fan, or a hemisphere's base
    end = rows + 1
    if hemi and rw:  # flat over the base's extent
        bx, by = ring[-1, :m, 0], ring[-1, :m, 1]
        x0, y1 = float(bx.min()), float(by.max())
        base_uv = _corners(np, (-x0, y1), (bx[j1] - x0, y1 - by[j1]), (bx[j] - x0, y1 - by[j]))
    else:
        base_uv = _corners(np, uv(j, end), uv(j + 1, last), uv(j, last))
    b.faces(_stack(np, bottom, rings[-1][j1], rings[-1][j]), 0 if hemi else 1, base_group if hemi else group,
            base_uv)
    if pie and not hemi:  # the bottom pole's cut-plane faces keep the sphere's own UVs, also in real-world
        vb, vl = v_of(end) * sv, v_of(last) * sv
        one((bottom, axis[-1], rings[-1][n]), 2, cap4, (0.0, vb), (0.0, vl), (su, vl))
        one((bottom, rings[-1][0], axis[-1]), 3, cap8, (0.0, vb), (su, vl), (0.0, vl))


def _seam(np, a, step):
    """(u at the face's start, at its end) of faces that start at a and span step, shifted down by whole turns
    until they lie below 1: 3ds Max's cylinder seam (a negative step, a sliced Cylinder of negative height, runs
    back from its start)."""
    a = np.array(a, dtype=np.float64)
    b = a + step
    while True:
        past = np.maximum(a, b) > 1.0 - _SEAM
        if not past.any():
            return a, b
        a, b = np.where(past, a - 1.0, a), np.where(past, b - 1.0, b)


def _cylinder(b, p, r1, r2):
    """A Cylinder (r1 == r2) or a Cone: center fans and rings on the caps, the side between them. U runs around
    from +X (0.75 there), the seam where it would pass 1; V up the side, 0 on the bottom cap and 1 on the top (the
    caps take the side's U: degenerate). Real-world map size: the side in file units (U 2 pi times the bottom
    radius around, V the height), each cap mapped flat over its rim's extent. Faces side by side: the bottom fan's
    triangle, the quads up the rings, the top fan's triangle."""
    np = b.np
    h, nh, nc, ns = p.height, p.height_segs, p.cap_segs, p.sides
    smooth = 8 if p.smooth else 0
    cos = np.array([math.cos(j * _TAU / ns) for j in range(ns)], dtype=np.float64)
    sin = np.array([math.sin(j * _TAU / ns) for j in range(ns)], dtype=np.float64)
    kc, kh = np.arange(1, nc, dtype=np.int64), np.arange(nh + 1, dtype=np.int64)
    kt = np.arange(nc - 1, 0, -1, dtype=np.int64)
    # the rings: the bottom cap's inside out, the side's, the top cap's outside in
    radii = np.concatenate((r1 * kc / nc, r1 + (r2 - r1) * kh / nh, r2 * kt / nc))
    zs = np.concatenate((np.zeros(nc - 1), h * kh / nh, np.full(nc - 1, h)))
    bottom_center = b.points((0.0, 0.0, 0.0))
    rings = b.points(_stack(np, radii[:, None] * cos, radii[:, None] * sin, zs[:, None], dtype=np.float64))
    top_center = b.points((0.0, 0.0, h))
    rw = p.real_world
    vs = np.concatenate((np.zeros(nc - 1), kh / nh, np.ones(nc - 1)))
    around = _TAU * abs(r1)
    if rw:
        vs = vs * h

    def us(j, rho, seam=None):
        """(U at the start, at the end) of faces j on a ring of radius rho; seam (an array) False where the face
        closes on a point at its top, None for every face shifted at the seam."""
        a, e = _seam(np, 0.75 + j / ns, 1.0 / ns)
        if seam is not None:  # a face that closes on a point at its top: 3ds Max leaves out the seam's shift there
            a = np.where(seam, a, (0.75 + j / ns) % 1.0)
            e = np.where(seam, e, (0.75 + (j + 1) / ns) % 1.0)
        if rw:
            a, e = a * around, e * around
        point = rho == 0.0
        return np.where(point, 0.5, a), np.where(point, 0.5, e)

    def flat(rim, top_cap):
        """The real-world UV of a cap's point: over the extent of the cap's rim (radius rim)."""
        xs, ys = (rim * cos).tolist(), (rim * sin).tolist()
        x0, y0, y1 = min(xs), min(ys), max(ys)  # Python's: the first of 0.0 and -0.0, as before
        return lambda x, y: (x - x0, y - y0 if top_cap else y1 - y)

    first_side, last_side = nc - 1, nc - 1 + nh
    low, high = flat(r1, False), flat(r2, True)

    def cap_uv(k, j, top_cap):
        """The real-world UV of ring k's points j, on the top cap where top_cap (a bool or an array of them)."""
        rho = radii[k]
        x, y = rho * cos[j % ns], rho * sin[j % ns]
        (lu, lv), (hu, hv) = low(x, y), high(x, y)
        return np.where(top_cap, hu, lu), np.where(top_cap, hv, lv)

    j = np.arange(ns, dtype=np.int64)[:, None]
    j1 = (j + 1) % ns
    if rw:
        bottom_uv = _corners(np, low(0.0, 0.0), cap_uv(0, j1, False), cap_uv(0, j, False))
    else:
        a, e = us(j, radii[0])
        bottom_uv = _corners(np, (0.5, vs[0]), (e, vs[0]), (a, vs[0]))
    k = np.arange(len(radii) - 1, dtype=np.int64)[None, :]
    on_side = (first_side <= k) & (k < last_side)
    mats = np.where(k < first_side, 0, np.where(on_side, 2, 1))
    groups = np.where(on_side, smooth, 1)
    seam = radii[k + 1] != 0.0
    a0, e0 = us(j, radii[k], seam)
    a1, e1 = us(j, radii[k + 1], seam)
    ring_uv = _corners(np, (a0, vs[k]), (e0, vs[k]), (e1, vs[k + 1]), (a1, vs[k + 1]))
    if rw:
        top_cap = k >= last_side
        caps = _corners(np, cap_uv(k, j, top_cap), cap_uv(k, j1, top_cap), cap_uv(k + 1, j1, top_cap),
                        cap_uv(k + 1, j, top_cap))
        ring_uv = np.where(on_side[..., None, None], ring_uv, caps)
    last = len(radii) - 1
    if rw:
        top_uv = _corners(np, high(0.0, 0.0), cap_uv(last, j, True), cap_uv(last, j1, True))
    else:
        a, e = us(j, radii[-1])
        top_uv = _corners(np, (0.5, vs[-1]), (a, vs[-1]), (e, vs[-1]))
    b.columns((_stack(np, bottom_center, rings[0][j1], rings[0][j]), 1, 1, bottom_uv),
              (_stack(np, rings[k, j], rings[k, j1], rings[k + 1, j1], rings[k + 1, j]), mats, groups, ring_uv),
              (_stack(np, top_center, rings[-1][j], rings[-1][j1]), 0, 1, top_uv))


def _cylinder_pie(b, p, r1, r2):
    """A Cylinder or Cone with Slice: the profile's rings (the bottom cap's inside out, the side's, the top cap's
    outside in), sides + 1 points over the arc kept, each ring after a point on the axis (those spread evenly
    from the bottom center to the top center, which centers the top fan). Faces: the bottom fan, then per pair of
    rings the start's cut plane (two triangles, ID 4, group 2), the quads, the end's cut plane (ID 5, group 4),
    then the top fan; IDs and groups of the rest as without Slice. U around as without Slice (0.75 at +X, the
    seam's shift per face), the cut planes U 0.5 on the axis and V up it. Real-world map size: the side and the
    caps as without Slice; the start's plane U from the axis, V up; the end's U back from its rim along the
    direction of the last side step's start (3ds Max's own), V up."""
    np = b.np
    h, nh, nc, ns = p.height, p.height_segs, p.cap_segs, p.sides
    smooth = 8 if p.smooth else 0
    start, arc = _pie(p)
    # under a negative height the arc is walked back from its end: the faces point out unflipped
    turn = -1.0 if h < 0 else 1.0
    first = start if turn > 0 else math.fmod(start + arc, _TAU)
    step = turn * arc / ns
    phi = [first + j * step for j in range(ns + 1)]
    cos = np.array([math.cos(a) for a in phi], dtype=np.float64)
    sin = np.array([math.sin(a) for a in phi], dtype=np.float64)
    kc, kh = np.arange(1, nc, dtype=np.int64), np.arange(nh + 1, dtype=np.int64)
    kt = np.arange(nc - 1, 0, -1, dtype=np.int64)
    radii = np.concatenate((r1 * kc / nc, r1 + (r2 - r1) * kh / nh, r2 * kt / nc))
    zs = np.concatenate((np.zeros(nc - 1), h * kh / nh, np.full(nc - 1, h)))
    count = len(radii)
    az = h * np.arange(count, dtype=np.int64) / (count - 1)
    pts = np.empty((count, ns + 2, 3), dtype=np.float64)
    pts[:, 0] = _stack(np, 0.0, 0.0, az, dtype=np.float64)
    pts[:, 1:] = _stack(np, radii[:, None] * cos, radii[:, None] * sin, zs[:, None], dtype=np.float64)
    made = b.points(pts)
    axis, rings = made[:, 0], made[:, 1:]
    rw = p.real_world
    vs = np.concatenate((np.zeros(nc - 1), kh / nh, np.ones(nc - 1)))
    va = np.arange(count, dtype=np.int64) / (count - 1)
    if rw:
        vs, va = vs * h, az
    around = _TAU * abs(r1)
    jj = np.arange(ns, dtype=np.int64)
    j1 = jj + 1
    u0 = 0.75 + (first + jj * step) / _TAU

    def us(rho):
        """(U at the start, at the end) of a fan's faces jj on a ring of radius rho, as _cylinder's."""
        a, e = _seam(np, u0, step / _TAU)
        if rho == 0.0:
            a = e = np.full(ns, 0.5)
        return (a * around, e * around) if rw else (a, e)

    # real-world: each ring's points flat over the extent of its cap's rim (the arc kept), (rings, sides + 1)
    bx0, by1 = (radii[nc - 1] * cos).min(), (radii[nc - 1] * sin).max()
    tx0, ty0 = (radii[count - nc] * cos).min(), (radii[count - nc] * sin).min()
    bottom_cap = (np.arange(count) < nc)[:, None]
    fx, fy = radii[:, None] * cos, radii[:, None] * sin
    fu, fv = np.where(bottom_cap, fx - bx0, fx - tx0), np.where(bottom_cap, by1 - fy, fy - ty0)

    first_side, last_side = nc - 1, nc - 1 + nh
    # the bottom fan
    if rw:
        bottom_uv = _corners(np, (-bx0, by1), (fu[0][j1], fv[0][j1]), (fu[0][jj], fv[0][jj]))
    else:
        a, e = us(radii[0])
        bottom_uv = _corners(np, (0.5, vs[0]), (e, vs[0]), (a, vs[0]))
    b.faces(_stack(np, axis[0], rings[0][j1], rings[0][jj]), 1, 1, bottom_uv)
    last_dir = (math.cos(first + (ns - 1) * step), math.sin(first + (ns - 1) * step))
    along_last = radii * cos[ns] * last_dir[0] + radii * sin[ns] * last_dir[1]
    reach = along_last.max()

    # per pair of rings k, k + 1 (one column each): the start's plane, the quads, the end's plane
    k = np.arange(count - 1, dtype=np.int64)
    on_side = (first_side <= k) & (k < last_side)
    mats = np.where(on_side, 2, np.where(k < first_side, 0, 1))
    groups = np.where(on_side, smooth, 1)
    seamed = _seam(np, u0, step / _TAU)
    plain = (u0 % 1.0, (u0 + step / _TAU) % 1.0)  # a face that closes on a point at its top: no seam's shift
    seam = (radii[k + 1] != 0.0)[:, None]

    def ring_us(q):
        """(U at the start, at the end) of the faces of each pair's ring q (k or k + 1), (pairs, sides)."""
        a, e = (np.where(seam, sv, pv) for sv, pv in zip(seamed, plain))
        point = (radii[q] == 0.0)[:, None]
        a, e = np.where(point, 0.5, a), np.where(point, 0.5, e)
        return (a * around, e * around) if rw else (a, e)

    (a0, e0), (a1, e1) = ring_us(k), ring_us(k + 1)
    v0, v1 = vs[k], vs[k + 1]
    if rw:  # the cut planes' V up from their lowest point
        low = min(0.0, h)
        ends_uv = reach - along_last
        s0, s1 = (radii[k], zs[k] - low), (radii[k + 1], zs[k + 1] - low)
        t0, t1 = (ends_uv[k], zs[k] - low), (ends_uv[k + 1], zs[k + 1] - low)
        sa0, sa1 = (0.0, va[k] - low), (0.0, va[k + 1] - low)
        ea0, ea1 = (reach, va[k] - low), (reach, va[k + 1] - low)
    else:
        s0, s1 = (a0[:, 0], v0), (a1[:, 0], v1)
        t0, t1 = (e0[:, -1], v0), (e1[:, -1], v1)
        sa0 = ea0 = (0.5, va[k])
        sa1 = ea1 = (0.5, va[k + 1])
    pair = (slice(None), None)
    start_v = np.stack((_stack(np, axis[k], rings[k + 1, 0], axis[k + 1]), _stack(np, axis[k], rings[k, 0],
                                                                                  rings[k + 1, 0])), axis=1)
    start_uv = np.stack((_corners(np, sa0, s1, sa1), _corners(np, sa0, s0, s1)), axis=1)
    end_v = np.stack((_stack(np, rings[k, ns], axis[k + 1], rings[k + 1, ns]), _stack(np, rings[k, ns], axis[k],
                                                                                      axis[k + 1])), axis=1)
    end_uv = np.stack((_corners(np, t0, ea1, t1), _corners(np, t0, ea0, ea1)), axis=1)
    quad_v = _stack(np, rings[k][:, jj], rings[k][:, j1], rings[k + 1][:, j1], rings[k + 1][:, jj])
    quad_uv = _corners(np, (a0, v0[pair]), (e0, v0[pair]), (e1, v1[pair]), (a1, v1[pair]))
    if rw:  # the caps flat over their rims' extent
        caps = _corners(np, (fu[k][:, jj], fv[k][:, jj]), (fu[k][:, j1], fv[k][:, j1]),
                        (fu[k + 1][:, j1], fv[k + 1][:, j1]), (fu[k + 1][:, jj], fv[k + 1][:, jj]))
        quad_uv = np.where(on_side[:, None, None, None], quad_uv, caps)
    b.columns((start_v, 3, 2, start_uv), (quad_v, mats[:, None], groups[:, None], quad_uv), (end_v, 4, 4, end_uv))
    # the top fan
    if rw:
        top_uv = _corners(np, (-tx0, -ty0), (fu[-1][jj], fv[-1][jj]), (fu[-1][j1], fv[-1][j1]))
    else:
        a, e = us(radii[-1])
        top_uv = _corners(np, (0.5, vs[-1]), (a, vs[-1]), (e, vs[-1]))
    b.faces(_stack(np, axis[-1], rings[-1][jj], rings[-1][j1]), 0, 1, top_uv)


def _tube(b, p):
    """The profile (outer side up, top inwards, inner side down, bottom outwards) swept around from +Y: U along the
    profile, V around. The outer side's role (its material ID, the profile's start) goes to the larger radius, to the
    smaller one under a negative height, which keeps the faces pointing out. Real-world map size: U
    around (2 pi times the larger radius, falling), V along the profile (the height signed, the caps' widths), both
    in file units."""
    np = b.np
    h = p.height
    down = h < 0
    big, small = sorted((p.radius1, p.radius2), key=abs, reverse=True)
    r1, r2 = (small, big) if down else (big, small)
    ns, nc, nh = p.sides, p.cap_segs, p.height_segs
    # the profile's points: radius, z, and the material ID and smoothing group of the face that starts there
    sides_group, cap_group = (2, 4) if p.smooth else (0, 0)
    kh, kc = np.arange(nh, dtype=np.int64), np.arange(nc, dtype=np.int64)
    rho = np.concatenate((np.full(nh, r1), r1 + (r2 - r1) * kc / nc, np.full(nh, r2), r2 + (r1 - r2) * kc / nc))
    z = np.concatenate((h * kh / nh, np.full(nc, h), h - h * kh / nh, np.zeros(nc)))
    counts = (nh, nc, nh, nc)
    mats = np.repeat(np.array((2, 0, 3, 1), dtype=np.int64), counts)
    groups = np.repeat(np.array((sides_group, cap_group, sides_group, cap_group), dtype=np.int64), counts)
    m = len(rho)
    pie = p.slice
    start, arc = _pie(p)
    first = -(start + arc)  # Slice: from the From angle, turning the tube's way
    cols = ns + 1 if pie else ns
    angles = [first + j * arc / ns for j in range(cols)] if pie else [j * _TAU / ns for j in range(ns)]
    sin = np.array([math.sin(a) for a in angles], dtype=np.float64)[:, None]
    cos = np.array([math.cos(a) for a in angles], dtype=np.float64)[:, None]
    grid = b.points(_stack(np, rho * sin, rho * cos, z, dtype=np.float64))
    rw = p.real_world
    if rw:
        steps = np.concatenate((np.full(nh, h / nh), np.full(nc, abs(r1 - r2) / nc)))
        along = np.cumsum(np.concatenate(((0.0,), steps, steps)))  # 0.0 + the first step, as before
        around = arc * abs(big)

        def uv(q, j):
            return ((1.0 - j / ns) * around, along[q])
    else:
        across = ns + 1 if pie else ns  # with Slice 3ds Max divides by the columns, not the steps

        def uv(q, j):
            return (q / m, j / across)
    j = np.arange(ns, dtype=np.int64)[:, None]
    q = np.arange(m, dtype=np.int64)[None, :]
    j1, q1 = (j + 1 if pie else (j + 1) % ns), (q + 1) % m
    b.faces(_stack(np, grid[j, q], grid[j, q1], grid[j1, q1], grid[j1, q]).reshape(-1, 4),
            np.broadcast_to(mats[q], (ns, m)).reshape(-1), np.broadcast_to(groups[q], (ns, m)).reshape(-1),
            _corners(np, uv(q, j), uv(q + 1, j), uv(q + 1, j + 1), uv(q, j + 1)).reshape(-1, 4, 2))
    if not pie:
        return
    # the cut planes: a fan around the profile's middle at each end, the start's ID 5, the end's ID 6, group 1
    mid = (r1 + r2) / 2.0
    centers = b.points(_stack(np, mid * sin[[0, -1], 0], mid * cos[[0, -1], 0], h / 2.0, dtype=np.float64))
    q, q1 = q[0], q1[0]
    if rw:  # flat, V up from the lowest point; U in from the outer radius at the start, out from the inner at the end
        widest, narrowest, lowest = max(abs(r1), abs(r2)), min(abs(r1), abs(r2)), min(0.0, h)
        ar = np.abs(np.append(rho, rho[0]))
        pv = np.append(z, z[0]) - lowest
        su, eu = widest - ar, ar - narrowest
        mv = h / 2.0 - lowest
        s_uv = _corners(np, (widest - abs(mid), mv), (su[q + 1], pv[q + 1]), (su[q], pv[q]))
        e_uv = _corners(np, (abs(mid) - narrowest, mv), (eu[q], pv[q]), (eu[q + 1], pv[q + 1]))
    else:
        s_uv = _corners(np, (0.5, 1.0), ((q + 1) / m, 0.0), (q / m, 0.0))
        e_uv = _corners(np, (1.0, 0.5), (q / m, ns / across), ((q + 1) / m, ns / across))
    b.faces(_stack(np, centers[0], grid[0][q1], grid[0][q]), 4, 1, s_uv)
    b.faces(_stack(np, centers[1], grid[-1][q], grid[-1][q1]), 5, 1, e_uv)


def _alternate(np, k, n):
    """Smoothing group of rows k of n rows that alternate (2, 1, 2, ...): an odd n gives its last row 4, which
    shares no group with the first."""
    return np.where((k == n - 1) & bool(n % 2), 4, np.where(k % 2 == 0, 2, 1))


def _torus(b, p):
    """Rings of the tube around Z from +Y (the segments), each the tube's sides from the outer equator upwards,
    turned by Rotation and by Twist times (segment + 1) / segments. U along the sides, V around. Smooth: 0 none,
    1 alternating groups by side (smooth along the ring), 2 all, 3 alternating by segment. Real-world map size: U
    around (2 pi times radius 1, falling), V along the sides (2 pi times radius 2), in file units."""
    np = b.np
    big, small, ns, nt = p.radius1, p.radius2, p.segs, p.sides
    rotation, twist = p.rotation, p.twist  # radians, as stored
    pie = p.slice
    start, arc = _pie(p)
    cols = ns + 1 if pie else ns
    angles = [-(start + arc) + k * arc / ns for k in range(cols)] if pie else [k * _TAU / ns for k in range(ns)]
    s = np.arange(cols, dtype=np.int64)[:, None]
    t = np.arange(nt, dtype=np.int64)[None, :]
    sin = np.array([math.sin(a) for a in angles], dtype=np.float64)[:, None]
    cos = np.array([math.cos(a) for a in angles], dtype=np.float64)[:, None]
    psi = t * _TAU / nt + rotation + twist * (s + 1) / cols  # with Slice, over the columns
    rho = big + small * np.cos(psi)
    zs = small * np.sin(psi)
    grid = b.points(_stack(np, rho * sin, rho * cos, zs, dtype=np.float64))
    s = s[:ns]
    mode = p.smooth
    if mode == 0:
        group = np.zeros((ns, nt), dtype=np.int64)
    elif mode == 1:
        group = _alternate(np, t, nt)
    elif mode == 3:  # with Slice the segments do not close: no last row apart
        group = np.where(s % 2 == 0, 2, 1) if pie else _alternate(np, s, ns)
    else:
        group = np.ones((ns, nt), dtype=np.int64)
    if p.real_world:
        def uv(t, s):
            return ((1.0 - s / ns) * arc * abs(big), t / nt * _TAU * abs(small))
    else:
        across = ns + 1 if pie else ns  # with Slice 3ds Max divides by the columns, not the steps

        def uv(t, s):
            return (t / nt, s / across)
    s1, t1 = (s + 1 if pie else (s + 1) % ns), (t + 1) % nt
    b.faces(_stack(np, grid[s, t], grid[s, t1], grid[s1, t1], grid[s1, t]).reshape(-1, 4), 0,
            np.broadcast_to(group, (ns, nt)).reshape(-1),
            _corners(np, uv(t, s), uv(t + 1, s), uv(t + 1, s + 1), uv(t, s + 1)).reshape(-1, 4, 2))
    if not pie:
        return
    # the cut planes: a fan around the tube's center at each end, the start's ID 2, the end's ID 3, group 8
    centers = b.points(_stack(np, big * sin[[0, -1], 0], big * cos[[0, -1], 0], 0.0, dtype=np.float64))
    t, t1 = t[0], t1[0]
    if p.real_world:  # flat, V up from the lowest point; U in from the outer point at the start, out at the end
        ends = []
        for col, outward in ((0, False), (-1, True)):
            rr, zz = np.append(rho[col], rho[col][0]), np.append(zs[col], zs[col][0])
            low, inner, outer = zz.min(), rr.min(), rr.max()
            pu = rr - inner if outward else outer - rr
            mid = ((big - inner) if outward else (outer - big), -low)
            ends.append((mid, pu, zz - low))
        (sm, su, sv), (em, eu, ev) = ends
        s_uv = _corners(np, sm, (su[t + 1], sv[t + 1]), (su[t], sv[t]))
        e_uv = _corners(np, em, (eu[t], ev[t]), (eu[t + 1], ev[t + 1]))
    else:
        s_uv = _corners(np, (0.5, 1.0), ((t + 1) / nt, 0.0), (t / nt, 0.0))
        e_uv = _corners(np, (1.0, 0.5), (t / nt, ns / across), ((t + 1) / nt, ns / across))
    b.faces(_stack(np, centers[0], grid[0][t1], grid[0][t]), 1, 8, s_uv)
    b.faces(_stack(np, centers[1], grid[-1][t], grid[-1][t1]), 2, 8, e_uv)
