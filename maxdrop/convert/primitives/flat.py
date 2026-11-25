# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Box, Plane and Pyramid."""
from .builder import _corners, _first_use, _grid, _sign, _stack


def _box(b, p):
    """Each side is a grid of layer of the index lattice (i along X, j along Y, k along Z, the sizes signed). A
    side's role (its material ID and how its UVs run) is that of the side it faces in a box of positive sizes;
    a negative size hands the role to the opposite layer (top and bottom when an odd number of sizes is negative,
    front and back when the width is, left and right when the length is), while the smoothing group stays with
    the layer. The faces point out when width and length have the same sign, else in: 3ds Max's own box. A point
    is made when a face first needs it."""
    np = b.np
    w, ln, h = p.width, p.length, p.height
    nx, ny, nz = p.width_segs, p.length_segs, p.height_segs
    rw = p.real_world

    def pos(i, j, k):
        return (-w / 2 + w * i / nx, -ln / 2 + ln * j / ny, h * k / nz)

    sw, sl, sh = _sign(w), _sign(ln), _sign(h)
    swap_tb, swap_fb, swap_rl = sw * sl * sh < 0, sw < 0, sl < 0
    ax, ay, az = w, ln, h  # signed: a box dragged down has V running down
    # role: (material ID zero-based, U and V counts, real-world size, index of grid corner (a, c) on a layer)
    roles = {"bottom": (1, nx, ny, (ax, ay), lambda a, c, e: (nx - a, c, e)),
             "top": (0, nx, ny, (ax, ay), lambda a, c, e: (a, c, e)),
             "front": (4, nx, nz, (ax, az), lambda a, c, e: (a, e, c)),
             "back": (5, nx, nz, (ax, az), lambda a, c, e: (nx - a, e, c)),
             "right": (3, ny, nz, (ay, az), lambda a, c, e: (e, a, c)),
             "left": (2, ny, nz, (ay, az), lambda a, c, e: (e, ny - a, c))}
    # layer: (its index, smoothing group, role, the axis it is across)
    layers = ((0, 2, "top" if swap_tb else "bottom", 2), (nz, 4, "bottom" if swap_tb else "top", 2),
              (0, 8, "back" if swap_fb else "front", 1), (nx, 16, "left" if swap_rl else "right", 0),
              (ny, 32, "front" if swap_fb else "back", 1), (0, 64, "right" if swap_rl else "left", 0))
    outward = sw * sl > 0
    center = (0.0, 0.0, h / 2)
    sides = []
    for e, group, role, axis in layers:
        mat, nu, nv, size, corner = roles[role]
        p0, p1, p2 = (pos(*corner(a, c, e)) for a, c in ((0, 0), (1, 0), (0, 1)))
        u = [p1[k] - p0[k] for k in range(3)]
        v = [p2[k] - p0[k] for k in range(3)]
        normal = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        out = (normal[axis] * (p0[axis] - center[axis])) > 0
        a, c = _grid(np, nu, nv, flip=out != outward)
        i, j, k = (np.broadcast_to(x, a.shape) for x in corner(a, c, e))
        su, sv = size if rw else (1.0, 1.0)
        sides.append(((i * (ny + 1) + j) * (nz + 1) + k, mat, group,
                      _stack(np, a / nu * su, c / nv * sv, dtype=np.float64)))
    keys = np.concatenate([key.reshape(-1) for key, _m, _g, _uv in sides])
    first, ids = _first_use(np, keys)
    i, rest = np.divmod(keys[first], (ny + 1) * (nz + 1))
    j, k = np.divmod(rest, nz + 1)
    made = b.points(_stack(np, *pos(i, j, k), dtype=np.float64))
    at = 0
    for key, mat, group, uvs in sides:
        b.faces(made[ids[at:at + key.size]].reshape(key.shape), mat, group, uvs)
        at += key.size


def _plane(b, p):
    """The faces point up when width and length have the same sign; else down, with material ID 2 and U running
    against the width."""
    np = b.np
    w, ln, nx, ny = p.width, p.length, p.width_segs, p.length_segs
    same = _sign(w) * _sign(ln) > 0
    su, sv = (w, ln) if p.real_world else (1.0, 1.0)
    a, c = _grid(np, nx, ny, flip=not same)
    i = a if same else nx - a  # else U runs against i: the quads face U x V, which is down here
    first, ids = _first_use(np, i * (ny + 1) + c)
    i, j = i.reshape(-1)[first], c.reshape(-1)[first]
    made = b.points(_stack(np, -w / 2 + w * i / nx, -ln / 2 + ln * j / ny, 0.0, dtype=np.float64))
    b.faces(made[ids].reshape(a.shape), 0 if same else 1, 1, _stack(np, a / nx * su, c / ny * sv, dtype=np.float64))


def _div(a, b):
    """a / b, 0 for a size b of 0 (a flat pyramid); a a number or an array."""
    return a / b if b else 0.0


def _pyramid(b, p):
    np = b.np
    w, d, h = p.width, p.depth, p.height
    nw, nd, nh = p.width_segs, p.depth_segs, p.height_segs
    rw = p.real_world
    # the base's outline from the front left corner, counterclockwise seen from above: (x, y, side)
    iw, idp = np.arange(nw, dtype=np.int64), np.arange(nd, dtype=np.int64)
    ox = np.concatenate((-w / 2 + w * iw / nw, np.full(nd, w / 2), w / 2 - w * iw / nw, np.full(nd, -w / 2)))
    oy = np.concatenate((np.full(nw, -d / 2), -d / 2 + d * idp / nd, np.full(nw, d / 2), d / 2 - d * idp / nd))
    side = np.repeat(np.arange(4, dtype=np.int64), (nw, nd, nw, nd))
    n = len(ox)
    apex = b.points((0.0, 0.0, h))
    # ring k = 1 .. nh, the outline scaled by k / nh at height h * (1 - k / nh); ring nh is the base
    s = (np.arange(1, nh + 1, dtype=np.int64) / nh)[:, None]
    rings = b.points(_stack(np, ox * s, oy * s, h * (1 - s), dtype=np.float64))
    center = b.points((0.0, 0.0, 0.0))
    groups = np.array((4, 2, 16, 32), dtype=np.int64)  # front, right, back, left
    sizes = np.array((w, d, w, d), dtype=np.float64)

    def side_uv(sd, x, y, z):
        xw, yd, back = _div(x, w), _div(y, d), 1.0 - _div(w, 2.0 * d)
        u = np.where(sd == 0, 0.5 + xw, np.where(sd == 2, 0.5 - xw, np.where(sd == 1, back + yd, back - yd)))
        v = _div(z, h)
        return (u * sizes[sd], v * h) if rw else (u, v)

    q = np.arange(n, dtype=np.int64)[:, None]  # one column per outline step: its triangle, then its quads
    q1 = (q + 1) % n
    sd = side[q]

    def corner(k, at):
        x, y = ox[at % n], oy[at % n]
        s = (k + 1) / nh
        return side_uv(sd, x * s, y * s, h * (1 - s))

    apex_uv = (0.5 * sizes[sd], h) if rw else (0.5, 1.0)
    k = np.arange(nh - 1, dtype=np.int64)[None, :]
    b.columns((_stack(np, apex, rings[0][q], rings[0][q1]), 0, groups[sd],
               _corners(np, apex_uv, corner(0, q), corner(0, q + 1))),
              (_stack(np, rings[k, q], rings[k + 1, q], rings[k + 1, q1], rings[k, q1]), 0, groups[sd],
               _corners(np, corner(k, q), corner(k + 1, q), corner(k + 1, q + 1), corner(k, q + 1))))
    base = rings[-1]

    def base_uv(x, y):
        u, v = 0.5 + _div(x, w), 0.5 - _div(y, d)
        return (u * w, v * d) if rw else (u, v)

    q, q1 = q[:, 0], q1[:, 0]
    b.faces(_stack(np, base[q], center, base[q1]), 0, 8,
            _corners(np, base_uv(ox[q], oy[q]), base_uv(0.0, 0.0), base_uv(ox[q1], oy[q1])))
