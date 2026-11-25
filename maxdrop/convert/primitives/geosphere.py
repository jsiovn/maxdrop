# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GeoSphere: the base solids and their subdivided, slerped lattice."""
import math
import struct

from .specs import _TAU
from .builder import _first_use, _stack


def _f32(x):
    """x rounded to single precision: 3ds Max's angle of 180 degrees is a hair past pi, so the point's y is a hair
    below 0 and its U is 0, not 1."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _solid(base_type):
    """(points on the unit sphere, triangles facing out) of the GeoSphere's base solid: 0 tetrahedron, 1
    octahedron, else icosahedron."""
    if base_type == 0:
        rho = math.sqrt(8.0) / 3.0
        pts = [(0.0, 0.0, 1.0)] + [(rho * math.cos(k * _TAU / 3), rho * math.sin(k * _TAU / 3), -1.0 / 3.0)
                                   for k in range(3)]
        tris = [(0, 1, 2), (0, 2, 3), (0, 3, 1), (1, 3, 2)]
    elif base_type == 1:
        pts = [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0),
               (0.0, 0.0, -1.0)]
        tris = [(0, 1 + k, 1 + (k + 1) % 4) for k in range(4)] + [(5, 1 + (k + 1) % 4, 1 + k) for k in range(4)]
    else:
        z, rho = 1.0 / math.sqrt(5.0), 2.0 / math.sqrt(5.0)
        pts = [(0.0, 0.0, 1.0)]
        pts += [(rho * math.cos(_f32(k * _TAU / 5)), rho * math.sin(_f32(k * _TAU / 5)), z) for k in range(5)]
        pts += [(rho * math.cos(_f32((k + 0.5) * _TAU / 5)), rho * math.sin(_f32((k + 0.5) * _TAU / 5)), -z)
                for k in range(5)]
        pts.append((0.0, 0.0, -1.0))
        tris = []
        for k in range(5):
            u0, u1, l0, l1 = 1 + k, 1 + (k + 1) % 5, 6 + k, 6 + (k + 1) % 5
            tris += [(0, u0, u1), (l0, u1, u0), (u1, l0, l1), (11, l1, l0)]
    return pts, tris


def _slerp(np, a, b, t):
    """The points a fraction t of the way from unit vectors a to unit vectors b along their great circles (arrays
    whose last axis is x, y, z; t broadcast against the others)."""
    dot = np.clip(a[..., 0] * b[..., 0] + a[..., 1] * b[..., 1] + a[..., 2] * b[..., 2], -1.0, 1.0)
    angle = np.arccos(dot)
    sin = np.sin(angle)
    wa, wb = np.sin((1.0 - t) * angle) / sin, np.sin(t * angle) / sin
    return np.where((angle < 1e-12)[..., None], a, wa[..., None] * a + wb[..., None] * b)


def _geo_uv(np, unit):
    """(u, v), each (faces, 3), of triangles whose corners are the unit vectors unit (faces, 3, xyz): U = 0.5 +
    atan2(y, x) / 360 degrees, V = 1 - polar angle / 180 degrees; a face across the seam brings its corners past 3/4
    down by one, a pole (or the base center) takes the mean U of the face's other corners."""
    x, y, z = unit[..., 0], unit[..., 1], unit[..., 2]
    known = ~((np.abs(x) < 1e-6) & (np.abs(y) < 1e-6))
    u = 0.5 + np.arctan2(y, x) / _TAU
    v = 1.0 - np.arccos(np.clip(z, -1.0, 1.0)) / math.pi
    across = known.any(axis=1) & (np.where(known, u, -np.inf).max(axis=1) - np.where(known, u, np.inf).min(axis=1)
                                  > 0.5)
    u = np.where(across[:, None] & known & (u > 0.75), u - 1.0, u)
    count = known.sum(axis=1)
    middle = np.where(count > 0, np.where(known, u, 0.0).sum(axis=1) / np.maximum(count, 1), 0.5)
    return np.where(known, u, middle[:, None]), v


def _geo_base(base_type, hemisphere):
    """(points, triangles) of a GeoSphere's base solid. A hemisphere keeps the faces above the equator of a
    tetrahedron whose three lower corners are raised onto the equator, of the octahedron, or of the icosahedron
    with each face split in four at its edges' midpoints (its band then has edges on the equator; the corner
    triangles start at their corner of the face, the middle one at the midpoint across from the face's first
    corner)."""
    if not hemisphere or base_type == 1:
        return _solid(base_type)
    if base_type == 0:
        pts = [(0.0, 0.0, 1.0)] + [(math.cos(k * _TAU / 3), math.sin(k * _TAU / 3), 0.0) for k in range(3)]
        return pts, [(0, 1, 2), (0, 2, 3), (0, 3, 1)]
    pts, tris = _solid(base_type)

    def mid(i, k):
        x, y, z = (a + b for a, b in zip(pts[i], pts[k]))
        length = math.sqrt(x * x + y * y + z * z)
        return (x / length, y / length, z / length)

    out, faces = [], []
    for a, b, c in tris:
        at = len(out)
        out += [pts[a], pts[b], pts[c], mid(a, b), mid(b, c), mid(c, a)]
        pa, pb, pc, ab, bc, ca = range(at, at + 6)
        faces += [(pa, ab, ca), (ab, pb, bc), (ca, bc, pc), (bc, ca, ab)]
    return out, faces


def _geosphere(b, p):
    """Each face of the base solid split into segs x segs triangles on the sphere, from a lattice (i, j) of points
    slerped from its corners; a point on an edge of two base faces is one vertex. A point is made when a face first
    needs it, and its UV comes from that face's lattice point. A hemisphere (_geo_base) keeps the triangles above
    the equator and closes them with a fan to the center (ID 1, group 2), standing on the pivot."""
    np = b.np
    r = p.radius
    hemi = p.hemisphere
    pts, tris = _geo_base(p.base_type, hemi)
    n = p.segs
    smooth = p.smooth
    mat, group = (1, 1) if smooth else (0, 0)
    lift = r if p.base_to_pivot and not hemi else 0.0
    # the lattice of one base face: (i, j) with i + j <= n, i after i
    li = np.repeat(np.arange(n + 1, dtype=np.int64), np.arange(n + 1, 0, -1))
    lj = np.concatenate([np.arange(n + 1 - i, dtype=np.int64) for i in range(n + 1)])
    row = li + lj
    size = len(li)
    corner = np.asarray(pts, dtype=np.float64)[np.asarray(tris, dtype=np.int64)][:, :, None, :]  # (faces, 3, 1, xyz)
    a, bb, c = corner[:, 0], corner[:, 1], corner[:, 2]
    t = (row / n)[None, :]
    q = _slerp(np, _slerp(np, a, bb, t), _slerp(np, a, c, t), (lj / np.maximum(row, 1))[None, :])
    q = np.where((row == 0)[None, :, None], a, q).reshape(-1, 3)  # (faces * size, xyz)
    # lattice point -> the id of its vertex: its own, or on a base edge, that of the first point that rounds alike
    vertex = np.arange(len(q), dtype=np.int64)
    edge = np.flatnonzero(np.tile((li == 0) | (lj == 0) | (row == n), len(tris)))
    index = {}
    for at, point in zip(edge.tolist(), q[edge].tolist()):
        vertex[at] = index.setdefault(tuple(round(x, 9) for x in point), at)
    # the triangles of one base face in 3ds Max's order: for each (i, j), the one at (i, j), then the one beside it
    lattice = np.full((n + 2, n + 2), -1, dtype=np.int64)
    lattice[li, lj] = np.arange(size, dtype=np.int64)
    ti = np.repeat(np.arange(n, dtype=np.int64), np.arange(n, 0, -1))
    tj = np.concatenate([np.arange(n - i, dtype=np.int64) for i in range(n)])
    up = _stack(np, lattice[ti, tj], lattice[ti + 1, tj], lattice[ti, tj + 1])
    beside = _stack(np, lattice[ti + 1, tj], lattice[ti + 1, tj + 1], lattice[ti, tj + 1])
    local = _stack(np, up, beside).swapaxes(-1, -2)[_stack(np, True, ti + tj < n - 1)]  # (triangles, 3)
    stream = (np.arange(len(tris), dtype=np.int64)[:, None, None] * size + local).reshape(-1)
    if hemi:  # the triangles above the equator (each is wholly above or below it)
        above = (q[stream, 2].reshape(-1, 3) > -1e-9).all(axis=1)
        stream = stream.reshape(-1, 3)[above].reshape(-1)
    first, ids = _first_use(np, vertex[stream])
    unit = q[stream[first]]
    made = b.points(_stack(np, unit[:, 0] * r, unit[:, 1] * r, unit[:, 2] * r + lift, dtype=np.float64))
    corners = unit[ids].reshape(-1, 3, 3)
    u, v = _geo_uv(np, corners)
    if p.real_world:
        u, v = u * _TAU * abs(r), v * math.pi * abs(r)
    b.faces(made[ids].reshape(-1, 3), mat, group, _stack(np, u, v, dtype=np.float64))
    if not hemi:
        return
    # the base: a fan from each step of the equator to the center
    ring = np.flatnonzero(np.abs(unit[:, 2]) < 1e-9)
    ring = ring[np.argsort(np.arctan2(unit[ring, 1], unit[ring, 0]) % _TAU, kind="stable")]
    center = b.points((0.0, 0.0, 0.0))
    nxt = np.roll(ring, -1)
    origin = np.zeros((len(ring), 3))
    u, v = _geo_uv(np, np.stack((unit[nxt], unit[ring], origin), axis=1))
    if p.real_world:
        u, v = u * _TAU * abs(r), v * math.pi * abs(r)
    b.faces(_stack(np, made[nxt], made[ring], center), 0, 2 if smooth else 0, _stack(np, u, v, dtype=np.float64))
