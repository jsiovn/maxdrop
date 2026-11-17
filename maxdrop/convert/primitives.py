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
or collapsed mesh 3ds Max builds (UVs that would divide by it take 0 there). No bpy; numpy is imported when a mesh is made.
"""
import collections
import math
import struct

from ..reader import chunks, classids, geometry, pblock

ChunkError = chunks.ChunkError

SLOT_BLOCK = 0
# Face corners one primitive may make (a file can ask for any number of segments): 524,288 quads, measured at the
# cap in 1.5 to 4 s (a GeoSphere the slowest) and 450 MB at most, of the order of convert/extrude.py's budget.
MAX_CORNERS = 1 << 21
_REAL_WORLD, _RW_ENTRY, _RW_FLAG = 0x2150, 0x0110, 0x0130
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


def _real_world(chunk):
    """Whether Real-World Map Size is on: 0x2150{0x0110{..., 0x0130 u32}} of the object's chunk."""
    if not chunk.container:
        return False
    held = chunk.first(_REAL_WORLD)
    if held is None or not held.container:
        return False
    for entry in held.find_all(_RW_ENTRY):
        flag = entry.first(_RW_FLAG) if entry.container else None
        if flag is not None and flag.payload_size >= 4 and flag.unpack("<I")[0]:
            return True
    return False


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
    return params_of(entry.class_id, block, _real_world(scene.chunk(i)))


class _Builder:
    """Points, polygons and their corners' UVW, gathered in plain lists."""

    def __init__(self):
        self.points, self.loops, self.starts, self.mats, self.groups, self.uvw = [], [], [], [], [], []
        self.flip = False  # reverse every face made from now on (with its corners' UVs)

    def point(self, x, y, z):
        self.points.append((x, y, z))
        return len(self.points) - 1

    def face(self, verts, mat, group, uvs):
        if self.flip:
            verts, uvs = verts[::-1], uvs[::-1]
        self.starts.append(len(self.loops))
        self.loops.extend(verts)
        self.mats.append(mat)
        self.groups.append(group)
        self.uvw.extend((u, v, 0.0) for u, v in uvs)

    def data(self, mapping):
        import numpy
        with numpy.errstate(over="ignore", invalid="ignore"):  # checked below
            positions = numpy.asarray(self.points, dtype=numpy.float32).reshape(-1, 3)
            uvw = numpy.asarray(self.uvw, dtype=numpy.float32).reshape(-1, 3) if mapping else None
        if not numpy.isfinite(positions).all() or (uvw is not None and not numpy.isfinite(uvw).all()):
            raise PrimitiveError("its sizes give points or UVs past the float range")
        loops = numpy.asarray(self.loops, dtype=numpy.int32)
        maps = {}
        if mapping:
            maps[1] = geometry.MapChannel(1, uvw, numpy.arange(len(loops), dtype=numpy.int32))
        return geometry.MeshData(positions, loops, numpy.asarray(self.starts, dtype=numpy.int32),
                                 numpy.asarray(self.groups, dtype=numpy.uint32),
                                 numpy.asarray(self.mats, dtype=numpy.uint16), maps)


def _grid(b, vert, nu, nv, mat, group, scale=(1.0, 1.0), flip=False):
    """Quads of a grid: vert(a, c) the point at grid corner (a, c), a in 0..nu along U, c in 0..nv along V; UV
    (a / nu, c / nv) times scale. The quad (a, c), (a+1, c), (a+1, c+1), (a, c+1) faces U x V, the other way
    with flip."""
    su, sv = scale
    for c in range(nv):
        for a in range(nu):
            corners = ((a, c), (a + 1, c), (a + 1, c + 1), (a, c + 1))
            if flip:
                corners = corners[::-1]
            b.face([vert(x, y) for x, y in corners], mat, group,
                   [(x / nu * su, y / nv * sv) for x, y in corners])


def _sign(x):
    return -1.0 if x < 0 else 1.0


def _box(b, p):
    """Each side is a grid of layer of the index lattice (i along X, j along Y, k along Z, the sizes signed). A
    side's role (its material ID and how its UVs run) is that of the side it faces in a box of positive sizes;
    a negative size hands the role to the opposite layer (top and bottom when an odd number of sizes is negative,
    front and back when the width is, left and right when the length is), while the smoothing group stays with
    the layer. The faces point out when width and length have the same sign, else in: 3ds Max's own box."""
    w, ln, h = p.width, p.length, p.height
    nx, ny, nz = p.width_segs, p.length_segs, p.height_segs
    rw = p.real_world
    index = {}

    def pos(i, j, k):
        return (-w / 2 + w * i / nx, -ln / 2 + ln * j / ny, h * k / nz)

    def at(i, j, k):
        key = (i, j, k)
        if key not in index:
            index[key] = b.point(*pos(i, j, k))
        return index[key]

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
    for e, group, role, axis in layers:
        mat, nu, nv, size, corner = roles[role]
        p0, p1, p2 = (pos(*corner(a, c, e)) for a, c in ((0, 0), (1, 0), (0, 1)))
        u = [p1[k] - p0[k] for k in range(3)]
        v = [p2[k] - p0[k] for k in range(3)]
        normal = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        out = (normal[axis] * (p0[axis] - center[axis])) > 0
        _grid(b, lambda a, c, corner=corner, e=e: at(*corner(a, c, e)), nu, nv, mat, group,
              size if rw else (1.0, 1.0), flip=out != outward)


def _plane(b, p):
    """The faces point up when width and length have the same sign; else down, with material ID 2 and U running
    against the width."""
    w, ln, nx, ny = p.width, p.length, p.width_segs, p.length_segs
    index = {}

    def at(i, j):
        if (i, j) not in index:
            index[(i, j)] = b.point(-w / 2 + w * i / nx, -ln / 2 + ln * j / ny, 0.0)
        return index[(i, j)]

    same = _sign(w) * _sign(ln) > 0
    scale = (w, ln) if p.real_world else (1.0, 1.0)
    if same:
        _grid(b, at, nx, ny, 0, 1, scale)
    else:  # U runs against i: the quads face U x V, which is down here
        _grid(b, lambda a, c: at(nx - a, c), nx, ny, 1, 1, scale, flip=True)


def _div(a, b):
    """a / b, 0 for a size b of 0 (a flat pyramid)."""
    return a / b if b else 0.0


def _pyramid(b, p):
    w, d, h = p.width, p.depth, p.height
    nw, nd, nh = p.width_segs, p.depth_segs, p.height_segs
    rw = p.real_world
    # the base's outline from the front left corner, counterclockwise seen from above: (x, y, side)
    outline = []
    for i in range(nw):
        outline.append((-w / 2 + w * i / nw, -d / 2, 0))
    for j in range(nd):
        outline.append((w / 2, -d / 2 + d * j / nd, 1))
    for i in range(nw):
        outline.append((w / 2 - w * i / nw, d / 2, 2))
    for j in range(nd):
        outline.append((-w / 2, d / 2 - d * j / nd, 3))
    n = len(outline)
    apex = b.point(0.0, 0.0, h)
    rings = []  # ring k = 1 .. nh, the outline scaled by k / nh at height h * (1 - k / nh); ring nh is the base
    for k in range(1, nh + 1):
        s = k / nh
        rings.append([b.point(x * s, y * s, h * (1 - s)) for x, y, _side in outline])
    center = b.point(0.0, 0.0, 0.0)
    groups = (4, 2, 16, 32)  # front, right, back, left
    sizes = (w, d, w, d)

    def side_uv(side, x, y, z):
        if side == 0:
            u = 0.5 + _div(x, w)
        elif side == 2:
            u = 0.5 - _div(x, w)
        elif side == 1:
            u = 1.0 - _div(w, 2.0 * d) + _div(y, d)
        else:
            u = 1.0 - _div(w, 2.0 * d) - _div(y, d)
        v = _div(z, h)
        return (u * sizes[side], v * h) if rw else (u, v)

    def corner(k, q, side):
        x, y, _s = outline[q % n]
        s = (k + 1) / nh
        return side_uv(side, x * s, y * s, h * (1 - s))

    for q in range(n):
        side = outline[q][2]
        apex_uv = (0.5 * sizes[side], h) if rw else (0.5, 1.0)
        b.face([apex, rings[0][q], rings[0][(q + 1) % n]], 0, groups[side],
               [apex_uv, corner(0, q, side), corner(0, q + 1, side)])
        for k in range(nh - 1):
            b.face([rings[k][q], rings[k + 1][q], rings[k + 1][(q + 1) % n], rings[k][(q + 1) % n]], 0,
                   groups[side], [corner(k, q, side), corner(k + 1, q, side), corner(k + 1, q + 1, side),
                                  corner(k, q + 1, side)])
    base = rings[-1]

    def base_uv(x, y):
        u, v = 0.5 + _div(x, w), 0.5 - _div(y, d)
        return (u * w, v * d) if rw else (u, v)

    for q in range(n):
        (x0, y0, _a), (x1, y1, _b) = outline[q], outline[(q + 1) % n]
        b.face([base[q], center, base[(q + 1) % n]], 0, 8, [base_uv(x0, y0), base_uv(0.0, 0.0), base_uv(x1, y1)])


def _sphere(b, p):
    r, n = p.radius, p.segs
    rows = n // 2
    group = 1 if p.smooth else 0
    lift = r if p.base_to_pivot else 0.0
    top = b.point(0.0, 0.0, r + lift)
    rings = []
    for k in range(1, rows):
        a = k * _TAU / n
        rho, z = r * math.sin(a), r * math.cos(a)
        rings.append([b.point(-rho * math.sin(j * _TAU / n), rho * math.cos(j * _TAU / n), z + lift)
                      for j in range(n)])
    bottom = b.point(0.0, 0.0, -r + lift)
    su, sv = (_TAU * abs(r), math.pi * abs(r)) if p.real_world else (1.0, 1.0)

    def uv(j, k):
        return (j / n * su, (1.0 - 2.0 * k / n) * sv)

    for j in range(n):
        j1 = (j + 1) % n
        b.face([top, rings[0][j], rings[0][j1]], 1, group, [uv(j, 0), uv(j, 1), uv(j + 1, 1)])
    for k in range(len(rings) - 1):
        for j in range(n):
            j1 = (j + 1) % n
            b.face([rings[k][j], rings[k + 1][j], rings[k + 1][j1], rings[k][j1]], 1, group,
                   [uv(j, k + 1), uv(j, k + 2), uv(j + 1, k + 2), uv(j + 1, k + 1)])
    last = len(rings)
    for j in range(n):
        j1 = (j + 1) % n
        b.face([bottom, rings[-1][j1], rings[-1][j]], 1, group, [uv(j, rows), uv(j + 1, last), uv(j, last)])


def _seam(a, step):
    """(u at the face's start, at its end) of a face that starts at a and spans step, shifted down by whole turns
    until it ends below 1: 3ds Max's cylinder seam."""
    b = a + step
    while b > 1.0 - _SEAM:
        a, b = a - 1.0, b - 1.0
    return a, b


def _cylinder(b, p, r1, r2):
    """A Cylinder (r1 == r2) or a Cone: center fans and rings on the caps, the side between them. U runs around
    from +X (0.75 there), the seam where it would pass 1; V up the side, 0 on the bottom cap and 1 on the top (the
    caps take the side's U: degenerate). Real-world map size: the side in file units (U 2 pi times the bottom
    radius around, V the height), each cap mapped flat over its rim's extent."""
    h, nh, nc, ns = p.height, p.height_segs, p.cap_segs, p.sides
    smooth = 8 if p.smooth else 0
    angles = [(math.cos(j * _TAU / ns), math.sin(j * _TAU / ns)) for j in range(ns)]

    def ring(rho, z):
        return [b.point(rho * c, rho * s, z) for c, s in angles]

    bottom_center = b.point(0.0, 0.0, 0.0)
    bottom = [ring(r1 * k / nc, 0.0) for k in range(1, nc)]  # inner rings, inside out
    side = [ring(r1 + (r2 - r1) * k / nh, h * k / nh) for k in range(nh + 1)]
    top = [ring(r2 * k / nc, h) for k in range(nc - 1, 0, -1)]  # inner rings, outside in
    top_center = b.point(0.0, 0.0, h)
    radii = ([r1 * k / nc for k in range(1, nc)] + [r1 + (r2 - r1) * k / nh for k in range(nh + 1)]
             + [r2 * k / nc for k in range(nc - 1, 0, -1)])
    rings = bottom + side + top
    rw = p.real_world
    vs = [0.0] * len(bottom) + [k / nh for k in range(nh + 1)] + [1.0] * len(top)
    around = _TAU * abs(r1)
    if rw:
        vs = [v * h for v in vs]

    def us(j, rho, seam=True):
        if rho == 0.0:
            return 0.5, 0.5
        if seam:
            a, e = _seam(0.75 + j / ns, 1.0 / ns)
        else:  # a face that closes on a point at its top: 3ds Max leaves out the seam's shift there
            a, e = (0.75 + j / ns) % 1.0, (0.75 + (j + 1) / ns) % 1.0
        return (a * around, e * around) if rw else (a, e)

    def flat(rim, top_cap):
        """The real-world UV of a cap's point: over the extent of the cap's rim (radius rim)."""
        xs = [rim * c for c, _s in angles]
        ys = [rim * s for _c, s in angles]
        x0, y0, y1 = min(xs), min(ys), max(ys)
        return lambda x, y: (x - x0, y - y0 if top_cap else y1 - y)

    first_side, last_side = len(bottom), len(bottom) + nh
    low, high = flat(r1, False), flat(r2, True)

    def cap_uv(k, j, top_cap):
        c, s = angles[j % ns]
        return (high if top_cap else low)(radii[k] * c, radii[k] * s)

    for j in range(ns):
        j1 = (j + 1) % ns
        if rw:
            uvs = [low(0.0, 0.0), cap_uv(0, j1, False), cap_uv(0, j, False)]
        else:
            a, e = us(j, radii[0])
            uvs = [(0.5, vs[0]), (e, vs[0]), (a, vs[0])]
        b.face([bottom_center, rings[0][j1], rings[0][j]], 1, 1, uvs)
        for k in range(len(rings) - 1):
            on_side = first_side <= k < last_side
            if k < first_side:
                mat, group = 0, 1
            elif on_side:
                mat, group = 2, smooth
            else:
                mat, group = 1, 1
            if rw and not on_side:
                top_cap = k >= last_side
                uvs = [cap_uv(k, j, top_cap), cap_uv(k, j1, top_cap), cap_uv(k + 1, j1, top_cap),
                       cap_uv(k + 1, j, top_cap)]
            else:
                seam = radii[k + 1] != 0.0
                a0, e0 = us(j, radii[k], seam)
                a1, e1 = us(j, radii[k + 1], seam)
                uvs = [(a0, vs[k]), (e0, vs[k]), (e1, vs[k + 1]), (a1, vs[k + 1])]
            b.face([rings[k][j], rings[k][j1], rings[k + 1][j1], rings[k + 1][j]], mat, group, uvs)
        last = len(rings) - 1
        if rw:
            uvs = [high(0.0, 0.0), cap_uv(last, j, True), cap_uv(last, j1, True)]
        else:
            a, e = us(j, radii[-1])
            uvs = [(0.5, vs[-1]), (a, vs[-1]), (e, vs[-1])]
        b.face([top_center, rings[-1][j], rings[-1][j1]], 0, 1, uvs)


def _tube(b, p):
    """The profile (outer side up, top inwards, inner side down, bottom outwards) swept around from +Y: U along the
    profile, V around. The outer side's role (its material ID, the profile's start) goes to the larger radius, to the
    smaller one under a negative height, which keeps the faces pointing out. Real-world map size: U
    around (2 pi times the larger radius, falling), V along the profile (the height signed, the caps' widths), both
    in file units."""
    h = p.height
    down = h < 0
    big, small = sorted((p.radius1, p.radius2), key=abs, reverse=True)
    r1, r2 = (small, big) if down else (big, small)
    ns, nc, nh = p.sides, p.cap_segs, p.height_segs
    # (radius, z, material ID, smoothing group of the face that starts there)
    sides_group, cap_group = (2, 4) if p.smooth else (0, 0)
    profile = []
    for k in range(nh):
        profile.append((r1, h * k / nh, 2, sides_group))
    for k in range(nc):
        profile.append((r1 + (r2 - r1) * k / nc, h, 0, cap_group))
    for k in range(nh):
        profile.append((r2, h - h * k / nh, 3, sides_group))
    for k in range(nc):
        profile.append((r2 + (r1 - r2) * k / nc, 0.0, 1, cap_group))
    m = len(profile)
    grid = [[b.point(rho * math.sin(j * _TAU / ns), rho * math.cos(j * _TAU / ns), z) for rho, z, _m, _g in profile]
            for j in range(ns)]
    if p.real_world:
        steps = [h / nh] * nh + [abs(r1 - r2) / nc] * nc
        along = [0.0]
        for step in steps + steps:
            along.append(along[-1] + step)
        around = _TAU * abs(big)

        def uv(q, j):
            return ((1.0 - j / ns) * around, along[q])
    else:
        def uv(q, j):
            return (q / m, j / ns)
    for j in range(ns):
        j1 = (j + 1) % ns
        for q in range(m):
            q1 = (q + 1) % m
            _r, _z, mat, group = profile[q]
            b.face([grid[j][q], grid[j][q1], grid[j1][q1], grid[j1][q]], mat, group,
                   [uv(q, j), uv(q + 1, j), uv(q + 1, j + 1), uv(q, j + 1)])


def _alternate(k, n):
    """Smoothing group of row k of n rows that alternate (2, 1, 2, ...): an odd n gives its last row 4, which
    shares no group with the first."""
    if n % 2 and k == n - 1:
        return 4
    return 2 if k % 2 == 0 else 1


def _torus(b, p):
    """Rings of the tube around Z from +Y (the segments), each the tube's sides from the outer equator upwards,
    turned by Rotation and by Twist times (segment + 1) / segments. U along the sides, V around. Smooth: 0 none,
    1 alternating groups by side (smooth along the ring), 2 all, 3 alternating by segment. Real-world map size: U
    around (2 pi times radius 1, falling), V along the sides (2 pi times radius 2), in file units."""
    big, small, ns, nt = p.radius1, p.radius2, p.segs, p.sides
    rotation, twist = p.rotation, p.twist  # radians, as stored
    grid = []
    for s in range(ns):
        phi = s * _TAU / ns
        row = []
        for t in range(nt):
            psi = t * _TAU / nt + rotation + twist * (s + 1) / ns
            rho = big + small * math.cos(psi)
            row.append(b.point(rho * math.sin(phi), rho * math.cos(phi), small * math.sin(psi)))
        grid.append(row)
    mode = p.smooth
    if p.real_world:
        def uv(t, s):
            return ((1.0 - s / ns) * _TAU * abs(big), t / nt * _TAU * abs(small))
    else:
        def uv(t, s):
            return (t / nt, s / ns)
    for s in range(ns):
        s1 = (s + 1) % ns
        for t in range(nt):
            t1 = (t + 1) % nt
            if mode == 0:
                group = 0
            elif mode == 1:
                group = _alternate(t, nt)
            elif mode == 3:
                group = _alternate(s, ns)
            else:
                group = 1
            b.face([grid[s][t], grid[s][t1], grid[s1][t1], grid[s1][t]], 0, group,
                   [uv(t, s), uv(t + 1, s), uv(t + 1, s + 1), uv(t, s + 1)])


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


def _slerp(a, b, t):
    """The point a fraction t of the way from unit vector a to unit vector b along their great circle."""
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))
    angle = math.acos(dot)
    if angle < 1e-12:
        return a
    wa, wb = math.sin((1.0 - t) * angle) / math.sin(angle), math.sin(t * angle) / math.sin(angle)
    return tuple(wa * x + wb * y for x, y in zip(a, b))


def _geosphere(b, p):
    r, n = p.radius, p.segs
    pts, tris = _solid(p.base_type)
    smooth = p.smooth
    mat, group = (1, 1) if smooth else (0, 0)
    lift = r if p.base_to_pivot else 0.0
    index = {}
    unit = {}

    lattice = {}  # (face, i, j) -> point index: the slerps once per lattice point

    def at(face, i, j):
        found = lattice.get((face, i, j))
        if found is not None:
            return found
        a, bb, c = (pts[x] for x in face)
        row = i + j
        q = a if row == 0 else _slerp(_slerp(a, bb, row / n), _slerp(a, c, row / n), j / row)
        key = tuple(round(x, 9) for x in q)  # a point on an edge of two base faces is one vertex
        if key not in index:
            index[key] = b.point(q[0] * r, q[1] * r, q[2] * r + lift)
            unit[index[key]] = q
        lattice[(face, i, j)] = index[key]
        return index[key]

    rw = p.real_world

    def uvs(corners):
        out = []
        for v in corners:
            x, y, z = unit[v]
            pole = abs(x) < 1e-6 and abs(y) < 1e-6
            u = None if pole else 0.5 + math.atan2(y, x) / _TAU
            out.append([u, 1.0 - math.acos(max(-1.0, min(1.0, z))) / math.pi])
        known = [c[0] for c in out if c[0] is not None]
        if known and max(known) - min(known) > 0.5:  # across the seam: the corners past 3/4 come round
            for c in out:
                if c[0] is not None and c[0] > 0.75:
                    c[0] -= 1.0
            known = [c[0] for c in out if c[0] is not None]
        for c in out:
            if c[0] is None:
                c[0] = sum(known) / len(known) if known else 0.5
        if rw:
            return [(u * _TAU * abs(r), v * math.pi * abs(r)) for u, v in out]
        return [tuple(c) for c in out]

    for face in tris:
        for i in range(n):
            for j in range(n - i):
                corners = [at(face, i, j), at(face, i + 1, j), at(face, i, j + 1)]
                b.face(corners, mat, group, uvs(corners))
                if i + j < n - 1:
                    corners = [at(face, i + 1, j), at(face, i + 1, j + 1), at(face, i, j + 1)]
                    b.face(corners, mat, group, uvs(corners))


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
    b = _Builder()
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
    return b.data(p.mapping), issues


def mesh(scene, i):
    """(MeshData of primitive object i, issues); PrimitiveError when it is not built."""
    params, issues = read_params(scene, i)
    data, more = build(params)
    return data, issues + more
