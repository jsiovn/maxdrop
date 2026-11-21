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
    classids.SPHERE: ("Sphere", {"radius": (0, "f", 0.0, None), "segs": (1, "i", 32, 4),
                                 "smooth": (2, "b", True, None), "hemisphere": (3, "f", 0.0, None),
                                 "squash": (4, "b", False, None), "base_to_pivot": (5, "b", False, None),
                                 "mapping": (6, "b", True, None), "slice": (7, "b", False, None),
                                 "slice_from": (8, "f", 0.0, None), "slice_to": (9, "f", 0.0, None)}),
    classids.GEOSPHERE: ("GeoSphere", {"radius": (0, "f", 0.0, None), "segs": (1, "i", 4, 1),
                                       "base_type": (2, "i", 2, None), "hemisphere": (3, "b", False, None),
                                       "smooth": (4, "b", True, None), "base_to_pivot": (5, "b", False, None),
                                       "mapping": (6, "b", True, None)}),
    classids.CYLINDER: ("Cylinder", {"radius": (0, "f", 0.0, None), "height": (1, "f", 0.0, None),
                                     "height_segs": (2, "i", 5, 1), "cap_segs": (3, "i", 1, 1),
                                     "sides": (4, "i", 18, 3), "smooth": (5, "b", True, None),
                                     "slice": (6, "b", False, None), "slice_from": (7, "f", 0.0, None),
                                     "slice_to": (8, "f", 0.0, None), "mapping": (9, "b", True, None)}),
    classids.CONE: ("Cone", {"radius1": (0, "f", 0.0, None), "radius2": (1, "f", 0.0, None),
                             "height": (2, "f", 0.0, None), "height_segs": (3, "i", 5, 1),
                             "cap_segs": (4, "i", 1, 1), "sides": (5, "i", 24, 3), "smooth": (6, "b", True, None),
                             "slice": (7, "b", False, None), "slice_from": (8, "f", 0.0, None),
                             "slice_to": (9, "f", 0.0, None), "mapping": (10, "b", True, None)}),
    classids.TUBE: ("Tube", {"radius1": (0, "f", 0.0, None), "radius2": (1, "f", 0.0, None),
                             "height": (2, "f", 0.0, None), "sides": (3, "i", 18, 3), "cap_segs": (4, "i", 1, 1),
                             "height_segs": (5, "i", 5, 1), "smooth": (6, "b", True, None),
                             "slice": (7, "b", False, None), "slice_from": (8, "f", 0.0, None),
                             "slice_to": (9, "f", 0.0, None), "mapping": (10, "b", True, None)}),
    classids.TORUS: ("Torus", {"radius1": (0, "f", 0.0, None), "radius2": (1, "f", 0.0, None),
                               "rotation": (2, "f", 0.0, None), "twist": (3, "f", 0.0, None),
                               "segs": (4, "i", 24, 3), "sides": (5, "i", 12, 3), "smooth": (6, "i", 2, None),
                               # Torus alone keeps the slice's end before its start
                               "slice": (7, "b", False, None), "slice_to": (8, "f", 0.0, None),
                               "slice_from": (9, "f", 0.0, None), "mapping": (10, "b", True, None)}),
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
    if h == 0.0:
        return n // 2 - 1, lambda k: k * _TAU / n, math.pi
    cut = (1.0 - h) * math.pi
    if p.squash:
        rows = n // 2 - 1
        step = cut / (n / 2.0 - 1.0)
        return rows, lambda k: k * step if k < rows else cut, cut
    import numpy
    f32 = numpy.float32
    cut32 = (f32(1.0) - f32(h)) * f32(math.pi)
    delta32 = f32(2.0) * f32(math.pi) / f32(n)
    kept = int(cut32 / delta32)
    while kept > 0 and not f32(kept) * delta32 <= cut32:
        kept -= 1
    while f32(kept + 1) * delta32 <= cut32:
        kept += 1
    return kept + 1, lambda k: k * _TAU / n if k <= kept else cut, cut


def _sphere(b, p):
    """Rings from the top pole down, segs points around each from +Y turning towards -X (with Slice, segs + 1
    over the part kept, then a point on the axis); the bottom pole, a hemisphere's base center on the axis at the
    cut (with Slice, the last ring's axis point). Faces: the top fan, the quads between rings, the bottom fan or
    the hemisphere's base (ID 1, group 2); with Slice each row ends with the faces of its two cut planes (the
    end's ID 3, group 4, then the start's ID 4, group 8). U across the part kept as a fraction of a whole turn, V
    down the rows (1 - 2k / segs; a hemisphere's 1 - k / (rings + 1)); the cut planes U 0 on the axis, 1 at the
    rim."""
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

    def us(rho, seam=True):
        """(U at the start, at the end) of faces jj on a ring of radius rho, as _cylinder's: seam False for a
        face that closes on a point at its top."""
        a, e = _seam(np, u0, step / _TAU)
        if not seam:
            a, e = u0 % 1.0, (u0 + step / _TAU) % 1.0
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
        rows, _angle, cut = _sphere_rings(p)
        caps = (2 * rows + (0 if cut != math.pi else 2)) if v["slice"] else 0
        return v["segs"] * (rows + 1) + caps
    if c == classids.GEOSPHERE:
        if v["hemisphere"]:  # the faces above the equator, then the base's fan
            per = {0: (3, 3), 1: (4, 4)}.get(v["base_type"], (40, 10))
            return per[0] * v["segs"] * v["segs"] + per[1] * v["segs"]
        return len(_solid(v["base_type"])[1]) * v["segs"] * v["segs"]
    if c in (classids.CYLINDER, classids.CONE):
        rings = v["height_segs"] + 2 * v["cap_segs"] - 1
        return v["sides"] * (rings + 1) + (4 * (rings - 1) if v["slice"] else 0)
    if c == classids.TUBE:
        profile = 2 * (v["height_segs"] + v["cap_segs"])
        return v["sides"] * profile + (2 * profile if v["slice"] else 0)
    return v["segs"] * v["sides"] + (2 * v["sides"] if v["slice"] else 0)


def build(p):
    """(MeshData of Params p, issues); PrimitiveError for what is not built."""
    issues = []
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
    elif c in (classids.CYLINDER, classids.CONE):
        b.flip = p.height < 0 and not p.slice
        r1, r2 = (p.radius, p.radius) if c == classids.CYLINDER else (p.radius1, p.radius2)
        (_cylinder_pie if p.slice else _cylinder)(b, p, r1, r2)
    elif c == classids.TUBE:  # under a negative height the radii trade sides: the faces point out unflipped
        _tube(b, p)
    else:
        _torus(b, p)


def mesh(scene, i):
    """(MeshData of primitive object i, issues); PrimitiveError when it is not built."""
    params, issues = read_params(scene, i)
    data, more = build(params)
    return data, issues + more
