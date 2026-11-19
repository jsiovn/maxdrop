# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The standard primitives as the meshes 3ds Max builds from their parameters: Box, Plane, Pyramid, Sphere,
GeoSphere, Cylinder, Cone, Tube and Torus (Teapot is not built: it stays a placeholder).

    is_primitive(scene, i)              # object i is one of the nine classes
    data, issues = mesh(scene, i)       # reader.geometry.MeshData in object space, file units; PrimitiveError
    params, issues = read_params(scene, i)   # Params: the class and its parameters by name

Each keeps one ParamBlock2 in reference slot 0, its parameters by id (docs/FORMAT.md, "Primitives"). The mesh is the
one the object's own TriMesh holds (`o.mesh`), checked vertex for vertex against 3ds Max 2020: the same vertices
(their order aside), the same triangles merged into the polygons 3ds Max shows (two triangles that share a hidden
edge are one quad; a cap's fan stays triangles around its center vertex, so the vertex and triangle counts are 3ds
Max's), smoothing groups and material IDs as 3ds Max assigns them (a Box's sides have IDs 1 to 6), and, when
Generate Mapping Coords is on, the map channel 1 3ds Max makes, real-world map size included (the UVs are then in
file units). The pivot is 3ds Max's: a Box, Plane, Pyramid, Cylinder, Cone and Tube stand on it, a Sphere, GeoSphere
and Torus are centered on it (Base To Pivot raises a Sphere or GeoSphere by its radius).

Not built (PrimitiveError, the node stays a placeholder): a Sphere's hemisphere, a GeoSphere's hemisphere, Slice on a
Sphere, Cylinder, Cone, Tube or Torus. Plane's render scale and density act only at render time: built at their
viewport size (an issue when they are not 1).

The file comes from anywhere: a missing block, an animated parameter or one that is no number or not finite raise
PrimitiveError; segments below 3ds Max's own minimum are raised to it, a mesh past MAX_CORNERS face corners is
refused, and so is one whose points or UVs are not finite (sizes near the float range). A size of 0 builds the flat
or collapsed mesh 3ds Max builds (UVs that would divide by it take 0 there). No bpy; numpy is imported when a mesh is
made, and every generator works on whole arrays of points and faces, in the order 3ds Max makes them.
"""
import collections
import math
import struct

from ..reader import chunks, classids, geometry, pblock, realworld

ChunkError = chunks.ChunkError

SLOT_BLOCK = 0
# Face corners one primitive may make (a file can ask for any number of segments): 524,288 quads, measured at the
# cap in 0.1 to 0.3 s (Box, Plane and GeoSphere the slowest) and 200 MB at most, of the order of
# convert/extrude.py's budget.
MAX_CORNERS = 1 << 21
_TAU = 2.0 * math.pi
_SEAM = 1e-6


class PrimitiveError(ChunkError):
    """A primitive that is not built; its node stays a placeholder."""


# class -> (name, {parameter: (id, kind, default, minimum)}); kind "f" a length or angle, "i" a count, "b" a switch
_SPECS = {
    classids.BOX: ("Box", {"length": (0, "f", 0.0, None), "width": (1, "f", 0.0, None),
                           "height": (2, "f", 0.0, None), "width_segs": (3, "i", 1, 1),
                           "length_segs": (4, "i", 1, 1), "height_segs": (5, "i", 1, 1),
                           "mapping": (6, "b", True, None)}),
    classids.PLANE: ("Plane", {"length": (0, "f", 0.0, None), "width": (1, "f", 0.0, None),
                               "width_segs": (2, "i", 4, 1), "length_segs": (3, "i", 4, 1),
                               "density": (4, "f", 1.0, None), "render_scale": (5, "f", 1.0, None),
                               "mapping": (6, "b", True, None)}),
    classids.PYRAMID: ("Pyramid", {"width": (0, "f", 0.0, None), "depth": (1, "f", 0.0, None),
                                   "height": (2, "f", 0.0, None), "width_segs": (3, "i", 1, 1),
                                   "depth_segs": (4, "i", 1, 1), "height_segs": (5, "i", 1, 1),
                                   "mapping": (6, "b", True, None)}),
    # squash (chop or squash) shapes only a hemisphere, which build() refuses: read and checked, never used
    classids.SPHERE: ("Sphere", {"radius": (0, "f", 0.0, None), "segs": (1, "i", 32, 4),
                                 "smooth": (2, "b", True, None), "hemisphere": (3, "f", 0.0, None),
                                 "squash": (4, "i", 0, None), "base_to_pivot": (5, "b", False, None),
                                 "mapping": (6, "b", True, None), "slice": (7, "b", False, None)}),
    classids.GEOSPHERE: ("GeoSphere", {"radius": (0, "f", 0.0, None), "segs": (1, "i", 4, 1),
                                       "base_type": (2, "i", 2, None), "hemisphere": (3, "b", False, None),
                                       "smooth": (4, "b", True, None), "base_to_pivot": (5, "b", False, None),
                                       "mapping": (6, "b", True, None)}),
    classids.CYLINDER: ("Cylinder", {"radius": (0, "f", 0.0, None), "height": (1, "f", 0.0, None),
                                     "height_segs": (2, "i", 5, 1), "cap_segs": (3, "i", 1, 1),
                                     "sides": (4, "i", 18, 3), "smooth": (5, "b", True, None),
                                     "slice": (6, "b", False, None), "mapping": (9, "b", True, None)}),
    classids.CONE: ("Cone", {"radius1": (0, "f", 0.0, None), "radius2": (1, "f", 0.0, None),
                             "height": (2, "f", 0.0, None), "height_segs": (3, "i", 5, 1),
                             "cap_segs": (4, "i", 1, 1), "sides": (5, "i", 24, 3), "smooth": (6, "b", True, None),
                             "slice": (7, "b", False, None), "mapping": (10, "b", True, None)}),
    classids.TUBE: ("Tube", {"radius1": (0, "f", 0.0, None), "radius2": (1, "f", 0.0, None),
                             "height": (2, "f", 0.0, None), "sides": (3, "i", 18, 3), "cap_segs": (4, "i", 1, 1),
                             "height_segs": (5, "i", 5, 1), "smooth": (6, "b", True, None),
                             "slice": (7, "b", False, None), "mapping": (10, "b", True, None)}),
    classids.TORUS: ("Torus", {"radius1": (0, "f", 0.0, None), "radius2": (1, "f", 0.0, None),
                               "rotation": (2, "f", 0.0, None), "twist": (3, "f", 0.0, None),
                               "segs": (4, "i", 24, 3), "sides": (5, "i", 12, 3), "smooth": (6, "i", 2, None),
                               "slice": (7, "b", False, None), "mapping": (10, "b", True, None)}),
}


class Params(collections.namedtuple("Params", "class_id name values real_world")):
    """A primitive's parameters: class_id, name (its class), values {parameter: value}, real_world whether Real-World
    Map Size is on."""
    __slots__ = ()

    def __getattr__(self, key):
        try:
            return self.values[key]
        except KeyError:
            raise AttributeError(key) from None


def is_primitive(scene, i):
    entry = scene.entry(i)
    return entry is not None and entry.superclass == classids.SC_GEOMOBJECT and entry.class_id in _SPECS


def _value(block, pid, kind, default):
    v = block.get(pid)
    if v is None:
        return default
    if isinstance(v, pblock.Animated):
        raise PrimitiveError("parameter %d is animated (a controller)" % pid)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise PrimitiveError("parameter %d is not a number: %r" % (pid, v))
    if kind == "b":
        return bool(v)
    if kind == "i":
        return int(v)
    return float(v)


def params_of(class_id, block, real_world=False):
    """(Params of a primitive of class_id from its ParamBlock2 block, issues): parameters by id, the defaults for
    those not stored; segments below 3ds Max's minimum raised to it (an issue)."""
    name, spec = _SPECS[class_id]
    issues = list(getattr(block, "issues", ()))
    values = {}
    for key, (pid, kind, default, minimum) in spec.items():
        v = _value(block, pid, kind, default)
        if minimum is not None and v < minimum:
            issues.append("%s %d, made %d" % (key.replace("_", " "), v, minimum))
            v = minimum
        values[key] = v
    return Params(class_id, name, values, real_world), issues


def read_params(scene, i):
    """(Params of primitive object i, issues): its block in reference slot 0 (params_of) and its Real-World Map Size
    flag."""
    entry = scene.entry(i)
    if not is_primitive(scene, i):
        raise PrimitiveError("object %d is not a primitive" % i)
    refs = scene.refs(i)
    target = refs.get(SLOT_BLOCK)
    te = scene.entry(target) if target is not None and 0 <= target < len(scene) else None
    if te is None or te.superclass != classids.SC_PARAMETER_BLOCK2:
        raise PrimitiveError("no parameter block (reference slot 0)")
    block = pblock.ParamBlock2.from_chunk(scene.chunk(target), scene.refs(target), refs, len(scene),
                                          (entry.superclass, entry.class_id))
    return params_of(entry.class_id, block, realworld.flag(scene.chunk(i), entry.class_id))


class _Builder:
    """Points, polygons and their corners' UVs, gathered as numpy blocks in the order they are made."""

    def __init__(self, numpy):
        self.np = numpy
        self.count = 0
        self.positions, self.loops, self.uvs, self.sizes, self.mats, self.groups = [], [], [], [], [], []
        self.flip = False  # reverse every face made from now on (with its corners' UVs)

    def points(self, xyz):
        """The indices of new points xyz (an array whose last axis is x, y, z), shaped like xyz without that axis."""
        np = self.np
        xyz = np.asarray(xyz, dtype=np.float64)
        first = self.count
        self.positions.append(xyz.reshape(-1, 3))
        self.count += len(self.positions[-1])
        return np.arange(first, self.count, dtype=np.int64).reshape(xyz.shape[:-1])

    def faces(self, verts, mat, group, uvs):
        """F faces of n corners: verts (F, n) point indices, uvs (F, n, 2); mat and group one value or one per face."""
        np = self.np
        verts = np.asarray(verts)
        self.columns((verts[:, None], np.reshape(mat, (-1, 1)), np.reshape(group, (-1, 1)),
                      np.broadcast_to(uvs, verts.shape + (2,))[:, None]))

    def columns(self, *parts):
        """Faces in C columns, made column after column: each part (verts (C, F, n), mat, group, uvs (C, F, n, 2))
        puts F faces of n corners in every column, after those of the parts before it; mat and group broadcast to
        (C, F). 3ds Max's own order where one column mixes triangles and quads."""
        np = self.np
        c = len(parts[0][0])
        loops, uvs, sizes, mats, groups = [], [], [], [], []
        for verts, mat, group, uv in parts:
            verts = np.asarray(verts, dtype=np.int64)
            uv = np.asarray(uv, dtype=np.float64)
            _c, f, n = verts.shape
            if self.flip:
                verts, uv = verts[..., ::-1], uv[..., ::-1, :]
            loops.append(verts.reshape(c, f * n))
            # UVs that do not vary along an axis (a size of 0) come with that axis 1, also when F is 0
            uvs.append(np.broadcast_to(uv, (c, f, n, 2)).reshape(c, f * n * 2))
            sizes.append(np.full((c, f), n, dtype=np.int64))
            mats.append(np.broadcast_to(np.asarray(mat, dtype=np.int64), (c, f)))
            groups.append(np.broadcast_to(np.asarray(group, dtype=np.int64), (c, f)))
        for out, blocks in ((self.loops, loops), (self.uvs, uvs), (self.sizes, sizes), (self.mats, mats),
                            (self.groups, groups)):
            out.append(np.concatenate(blocks, axis=1).reshape(-1))

    def data(self, mapping):
        """The MeshData; run under build()'s errstate: values past the float range become inf, refused here."""
        np = self.np
        positions = np.concatenate(self.positions).astype(np.float32)
        uvw = None
        if mapping:
            uv = np.concatenate(self.uvs).reshape(-1, 2)
            uvw = np.zeros((len(uv), 3), dtype=np.float32)
            uvw[:, :2] = uv
        if not np.isfinite(positions).all() or (uvw is not None and not np.isfinite(uvw).all()):
            raise PrimitiveError("its sizes give points or UVs past the float range")
        loops = np.concatenate(self.loops).astype(np.int32)
        sizes = np.concatenate(self.sizes)
        maps = {}
        if mapping:
            maps[1] = geometry.MapChannel(1, uvw, np.arange(len(loops), dtype=np.int32))
        return geometry.MeshData(positions, loops, (np.cumsum(sizes) - sizes).astype(np.int32),
                                 np.concatenate(self.groups).astype(np.uint32),
                                 np.concatenate(self.mats).astype(np.uint16), maps)


def _stack(np, *arrays, dtype=None):
    """arrays broadcast against each other and stacked along a new last axis."""
    arrays = [np.asarray(x, dtype=dtype) for x in arrays]
    out = np.empty(np.broadcast(*arrays).shape + (len(arrays),), dtype=dtype or np.result_type(*arrays))
    for k, x in enumerate(arrays):
        out[..., k] = x
    return out


def _corners(np, *uvs):
    """(..., corners, 2): the (u, v) pair of each corner, all broadcast against each other."""
    out = np.empty(np.broadcast(*(np.asarray(x) for uv in uvs for x in uv)).shape + (len(uvs), 2), dtype=np.float64)
    for k, (u, v) in enumerate(uvs):
        out[..., k, 0] = u
        out[..., k, 1] = v
    return out


def _first_use(np, keys):
    """(where in keys each distinct key first appears, in that order; for each key its rank in that order): points
    made the first time a face corner needs them, numbered in that order. keys are below 2^31 and there are at most
    MAX_CORNERS of them, so key * len + position fits int64 and one unstable sort finds each first appearance."""
    keys = np.asarray(keys, dtype=np.int64).reshape(-1)
    n = len(keys)
    order = np.argsort(keys * n + np.arange(n, dtype=np.int64))
    ordered = keys[order]
    new = np.ones(n, dtype=bool)
    np.not_equal(ordered[1:], ordered[:-1], out=new[1:])
    first = order[new]  # in key order
    by_use = np.argsort(first)
    rank = np.empty(len(first), dtype=np.int64)
    rank[by_use] = np.arange(len(first), dtype=np.int64)
    ids = np.empty(n, dtype=np.int64)
    ids[order] = rank[np.cumsum(new) - 1]
    return first[by_use], ids


def _grid(np, nu, nv, flip=False):
    """(a, c) of the corners of a grid's quads, (nu * nv, 4) each, a in 0..nu along U and c in 0..nv along V, row c
    after row c: the quad (a, c), (a+1, c), (a+1, c+1), (a, c+1) faces U x V, the other way with flip. Its UV is
    (a / nu, c / nv) times the grid's scale."""
    a = np.arange(nu, dtype=np.int64)[None, :, None] + np.array([0, 1, 1, 0], dtype=np.int64)
    c = np.arange(nv, dtype=np.int64)[:, None, None] + np.array([0, 0, 1, 1], dtype=np.int64)
    a, c = np.broadcast_arrays(a, c)
    if flip:
        a, c = a[..., ::-1], c[..., ::-1]
    return a.reshape(-1, 4), c.reshape(-1, 4)


def _sign(x):
    return -1.0 if x < 0 else 1.0


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


def _sphere(b, p):
    np = b.np
    r, n = p.radius, p.segs
    rows = n // 2
    group = 1 if p.smooth else 0
    lift = r if p.base_to_pivot else 0.0
    top = b.points((0.0, 0.0, r + lift))
    angles = [k * _TAU / n for k in range(1, rows)]
    rho = np.array([r * math.sin(a) for a in angles], dtype=np.float64)[:, None]
    z = np.array([r * math.cos(a) for a in angles], dtype=np.float64)[:, None]
    sin = np.array([math.sin(j * _TAU / n) for j in range(n)], dtype=np.float64)
    cos = np.array([math.cos(j * _TAU / n) for j in range(n)], dtype=np.float64)
    rings = b.points(_stack(np, -rho * sin, rho * cos, z + lift, dtype=np.float64))
    bottom = b.points((0.0, 0.0, -r + lift))
    su, sv = (_TAU * abs(r), math.pi * abs(r)) if p.real_world else (1.0, 1.0)

    def uv(j, k):
        return (j / n * su, (1.0 - 2.0 * k / n) * sv)

    j = np.arange(n, dtype=np.int64)
    j1 = (j + 1) % n
    b.faces(_stack(np, top, rings[0][j], rings[0][j1]), 1, group, _corners(np, uv(j, 0), uv(j, 1), uv(j + 1, 1)))
    k = np.arange(len(rings) - 1, dtype=np.int64)[:, None]
    j, j1 = j[None, :], j1[None, :]
    b.faces(_stack(np, rings[k, j], rings[k + 1, j], rings[k + 1, j1], rings[k, j1]).reshape(-1, 4), 1, group,
            _corners(np, uv(j, k + 1), uv(j, k + 2), uv(j + 1, k + 2), uv(j + 1, k + 1)).reshape(-1, 4, 2))
    last = len(rings)
    j, j1 = j[0], j1[0]
    b.faces(_stack(np, bottom, rings[-1][j1], rings[-1][j]), 1, group,
            _corners(np, uv(j, rows), uv(j + 1, last), uv(j, last)))


def _seam(np, a, step):
    """(u at the face's start, at its end) of faces that start at a and span step, shifted down by whole turns
    until they end below 1: 3ds Max's cylinder seam."""
    a = np.array(a, dtype=np.float64)
    b = a + step
    while True:
        past = b > 1.0 - _SEAM
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
    sin = np.array([math.sin(j * _TAU / ns) for j in range(ns)], dtype=np.float64)[:, None]
    cos = np.array([math.cos(j * _TAU / ns) for j in range(ns)], dtype=np.float64)[:, None]
    grid = b.points(_stack(np, rho * sin, rho * cos, z, dtype=np.float64))
    if p.real_world:
        steps = np.concatenate((np.full(nh, h / nh), np.full(nc, abs(r1 - r2) / nc)))
        along = np.cumsum(np.concatenate(((0.0,), steps, steps)))  # 0.0 + the first step, as before
        around = _TAU * abs(big)

        def uv(q, j):
            return ((1.0 - j / ns) * around, along[q])
    else:
        def uv(q, j):
            return (q / m, j / ns)
    j = np.arange(ns, dtype=np.int64)[:, None]
    q = np.arange(m, dtype=np.int64)[None, :]
    j1, q1 = (j + 1) % ns, (q + 1) % m
    b.faces(_stack(np, grid[j, q], grid[j, q1], grid[j1, q1], grid[j1, q]).reshape(-1, 4),
            np.broadcast_to(mats[q], (ns, m)).reshape(-1), np.broadcast_to(groups[q], (ns, m)).reshape(-1),
            _corners(np, uv(q, j), uv(q + 1, j), uv(q + 1, j + 1), uv(q, j + 1)).reshape(-1, 4, 2))


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
    s = np.arange(ns, dtype=np.int64)[:, None]
    t = np.arange(nt, dtype=np.int64)[None, :]
    sin = np.array([math.sin(k * _TAU / ns) for k in range(ns)], dtype=np.float64)[:, None]
    cos = np.array([math.cos(k * _TAU / ns) for k in range(ns)], dtype=np.float64)[:, None]
    psi = t * _TAU / nt + rotation + twist * (s + 1) / ns
    rho = big + small * np.cos(psi)
    grid = b.points(_stack(np, rho * sin, rho * cos, small * np.sin(psi), dtype=np.float64))
    mode = p.smooth
    if mode == 0:
        group = np.zeros((ns, nt), dtype=np.int64)
    elif mode == 1:
        group = _alternate(np, t, nt)
    elif mode == 3:
        group = _alternate(np, s, ns)
    else:
        group = np.ones((ns, nt), dtype=np.int64)
    if p.real_world:
        def uv(t, s):
            return ((1.0 - s / ns) * _TAU * abs(big), t / nt * _TAU * abs(small))
    else:
        def uv(t, s):
            return (t / nt, s / ns)
    s1, t1 = (s + 1) % ns, (t + 1) % nt
    b.faces(_stack(np, grid[s, t], grid[s, t1], grid[s1, t1], grid[s1, t]).reshape(-1, 4), 0,
            np.broadcast_to(group, (ns, nt)).reshape(-1),
            _corners(np, uv(t, s), uv(t + 1, s), uv(t + 1, s + 1), uv(t, s + 1)).reshape(-1, 4, 2))


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


def _geosphere(b, p):
    """Each face of the base solid split into segs x segs triangles on the sphere, from a lattice (i, j) of points
    slerped from its corners; a point on an edge of two base faces is one vertex. A point is made when a face first
    needs it, and its UV comes from that face's lattice point."""
    np = b.np
    r, n = p.radius, p.segs
    pts, tris = _solid(p.base_type)
    smooth = p.smooth
    mat, group = (1, 1) if smooth else (0, 0)
    lift = r if p.base_to_pivot else 0.0
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
    first, ids = _first_use(np, vertex[stream])
    unit = q[stream[first]]
    made = b.points(_stack(np, unit[:, 0] * r, unit[:, 1] * r, unit[:, 2] * r + lift, dtype=np.float64))
    x, y, z = unit[:, 0], unit[:, 1], unit[:, 2]
    pole = (np.abs(x) < 1e-6) & (np.abs(y) < 1e-6)
    known = ~pole[ids].reshape(-1, 3)
    u = (0.5 + np.arctan2(y, x) / _TAU)[ids].reshape(-1, 3)
    v = (1.0 - np.arccos(np.clip(z, -1.0, 1.0)) / math.pi)[ids].reshape(-1, 3)
    # across the seam: the corners past 3/4 come round
    across = known.any(axis=1) & (np.where(known, u, -np.inf).max(axis=1) - np.where(known, u, np.inf).min(axis=1)
                                  > 0.5)
    u = np.where(across[:, None] & known & (u > 0.75), u - 1.0, u)
    count = known.sum(axis=1)
    middle = np.where(count > 0, np.where(known, u, 0.0).sum(axis=1) / np.maximum(count, 1), 0.5)
    u = np.where(known, u, middle[:, None])  # a pole takes the mean U of the others
    if p.real_world:
        u, v = u * _TAU * abs(r), v * math.pi * abs(r)
    b.faces(made[ids].reshape(-1, 3), mat, group, _stack(np, u, v, dtype=np.float64))


def _faces(p):
    """How many polygons p makes."""
    v = p.values
    c = p.class_id
    if c == classids.BOX:
        x, y, z = v["width_segs"], v["length_segs"], v["height_segs"]
        return 2 * (x * y + x * z + y * z)
    if c == classids.PLANE:
        return v["width_segs"] * v["length_segs"]
    if c == classids.PYRAMID:
        return 2 * (v["width_segs"] + v["depth_segs"]) * (v["height_segs"] + 1)
    if c == classids.SPHERE:
        return v["segs"] * (v["segs"] // 2)
    if c == classids.GEOSPHERE:
        return len(_solid(v["base_type"])[1]) * v["segs"] * v["segs"]
    if c in (classids.CYLINDER, classids.CONE):
        return v["sides"] * (v["height_segs"] + 2 * v["cap_segs"])
    if c == classids.TUBE:
        return v["sides"] * 2 * (v["height_segs"] + v["cap_segs"])
    return v["segs"] * v["sides"]


def build(p):
    """(MeshData of Params p, issues); PrimitiveError for what is not built."""
    issues = []
    c = p.class_id
    if p.values.get("slice"):
        raise PrimitiveError("%s with Slice on is not built yet" % p.name)
    if c == classids.SPHERE and p.hemisphere != 0.0:
        raise PrimitiveError("a Sphere's hemisphere is not built yet")
    if c == classids.GEOSPHERE and p.hemisphere:
        raise PrimitiveError("a GeoSphere's hemisphere is not built yet")
    faces = _faces(p)
    if faces * 4 > MAX_CORNERS:  # four corners per face at most
        raise PrimitiveError("%s of %d faces refused (more than %d)" % (p.name, faces, MAX_CORNERS // 4))
    import numpy
    b = _Builder(numpy)
    with numpy.errstate(all="ignore"):  # sizes that overflow give points or UVs data() refuses
        _make(b, p, issues)
        return b.data(p.mapping), issues


def _make(b, p, issues):
    """Fill builder b with the mesh of Params p (its issues added to issues)."""
    c = p.class_id
    if c == classids.BOX:
        _box(b, p)
    elif c == classids.PLANE:
        if p.render_scale != 1.0 or p.density != 1.0:
            issues.append("render scale %g and density %g act at render time: built at the viewport size"
                          % (p.render_scale, p.density))
        _plane(b, p)
    elif c == classids.PYRAMID:
        b.flip = p.height < 0
        _pyramid(b, p)
    elif c == classids.SPHERE:
        _sphere(b, p)
    elif c == classids.GEOSPHERE:
        _geosphere(b, p)
    elif c == classids.CYLINDER:
        b.flip = p.height < 0
        _cylinder(b, p, p.radius, p.radius)
    elif c == classids.CONE:
        b.flip = p.height < 0
        _cylinder(b, p, p.radius1, p.radius2)
    elif c == classids.TUBE:  # under a negative height the radii trade sides: the faces point out unflipped
        _tube(b, p)
    else:
        _torus(b, p)


def mesh(scene, i):
    """(MeshData of primitive object i, issues); PrimitiveError when it is not built."""
    params, issues = read_params(scene, i)
    data, more = build(params)
    return data, issues + more
