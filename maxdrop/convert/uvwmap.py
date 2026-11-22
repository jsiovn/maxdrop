# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The UVW Map modifier evaluated on a mesh: one UVW per face corner, written into the modifier's map channel.

    is_uvwmap(modifier)                 # a reader.modifiers.Modifier of class UVW Map
    params, issues = read_params(scene, modifier)   # Params; UVWMapError when they cannot be read
    params.supported                    # planar, cylindrical, spherical or box: the types evaluated here
    tm, issues = gizmo(scene, modifier)             # the gizmo's matrix at frame 0 (row vectors)
    data = apply(mesh_data, params, tm, context_tm)    # a reader MeshData with the channel replaced

The parameters are an old ParamBlock in reference slot 1 (0 map type, 1-3 U/V/W tile, 4-6 U/V/W flip, 7 cap, 8 0 map
channel / 1 vertex color, 9 length, 10 width, 11 height, 12 alignment 0 X / 1 Y / 2 Z, 13 map channel); the gizmo
is the Position/Rotation/Scale controller in slot 0; Real-World Map Size is the u32 0x0130 of the modifier's 0x2150
entry that names its own class (reader.realworld). docs/FORMAT.md says which fixture shows what.

What 3ds Max 2020 computes (fitted to its own map vertices, tests/unit/test_uvwmap.py against the uvwmap fixture's
oracle): a point p of the object goes to q = p * context * inverse(gizmo), then to a frame (a, b, c) that depends on
the type and the alignment (FRAMES). Planar: u = a / width + 0.5, v = b / length + 0.5, w = c / height + 0.5;
Real-World Map Size drops the 0.5 of u and v. Box: the face normal, transformed like the points and divided by
(width, length, height), picks the side, which is mapped like a planar projection seen from outside it, w the depth
along that side's axis. Cylindrical: X = a / (length / 2), Y = b / (width / 2); u = 0.5 + atan2(X, -Y) / 2 pi,
v = c / height + 0.5, w = |(X, Y)|; with cap, a face whose normal (divided by (length / 2, width / 2, height)) is
largest along c is mapped u = 0.5 - Y / 2, v = 0.5 + X / 2, w = c / height / 2. Spherical: Z = c / (height / 2),
u as cylindrical, v = 0.5 + asin(Z / r) / pi, w = r = |(X, Y, Z)|. Then each component is flipped (1 - x) and
tiled (times its tile).

Seams: a face with an edge across the seam (where u wraps from 1 to 0) gets -1 on its corners above 0.5, so it does
not smear across the texture: the turn 3ds Max gives it, which keeps the image also when the U tile is not a whole
number. A corner on the axis of a round map has no angle: on a cylindrical map it gets U 0.5 (on every face, also
across the seam), on a spherical map the mean U of the rest of its face. On the axis means within POLE_TOLERANCE of
it, as in 3ds Max: |(X, Y)| below it (cylindrical), each of |X| and |Y| below it times r (spherical), so that a turned
gizmo's float residue is a pole, not an arbitrary angle. A corner at a spherical gizmo's center (r below
CENTER_TOLERANCE) is a pole with V 0.5.

The file comes from anywhere: a parameter that is animated or no number, a zero or non-finite size, a map channel
outside 0 .. 99 or a gizmo that cannot be evaluated or inverted raise UVWMapError (the stored channel stays).
No bpy; numpy is imported when a mesh is mapped.
"""
import collections
import math

from ..reader import chunks, classids, controllers, geometry, pblock, realworld

ChunkError = chunks.ChunkError

(P_TYPE, P_UTILE, P_VTILE, P_WTILE, P_UFLIP, P_VFLIP, P_WFLIP, P_CAP, P_CHANNEL_KIND, P_LENGTH, P_WIDTH, P_HEIGHT,
 P_AXIS, P_CHANNEL) = range(14)
PLANAR, CYLINDRICAL, SPHERICAL, SHRINK_WRAP, BOX, FACE, XYZ_TO_UVW = range(7)
TYPE_NAMES = {PLANAR: "planar", CYLINDRICAL: "cylindrical", SPHERICAL: "spherical", SHRINK_WRAP: "shrink-wrap",
              BOX: "box", FACE: "face", XYZ_TO_UVW: "XYZ to UVW"}
SUPPORTED = (PLANAR, CYLINDRICAL, SPHERICAL, BOX)
AXIS_X, AXIS_Y, AXIS_Z = 0, 1, 2
SLOT_GIZMO, SLOT_PARAMS = 0, 1
MAX_CHANNEL = 99
# found in 3ds Max 2020 by pushing an axis vertex off: 9.5e-5 is still a pole, 1.05e-4 is not (both kinds; exactly at
# 1e-4 its single-precision results disagree with each other)
POLE_TOLERANCE = 1e-4
# 3ds Max 2020 takes a vertex at a spherical gizmo's center (U the face mean, V 0.5) only where its single-precision
# point is exactly zero (1e-20 radii off is an angle); here the same vertex is a float64 residue of about 2e-16 radii
CENTER_TOLERANCE = 1e-9
_FATAL = (controllers.UNKNOWN_CLASS, controllers.DAMAGED, controllers.NON_FINITE)

# (a, b, c) of the mapping frame from the gizmo-space point q, by (planar-like or round, alignment): index of q and
# sign. Planar and box share one set, cylindrical and spherical another (3ds Max turns them differently).
FRAMES = {
    (False, AXIS_Z): ((0, -1), (1, -1), (2, 1)),
    (False, AXIS_X): ((2, 1), (1, -1), (0, 1)),
    (False, AXIS_Y): ((0, -1), (2, 1), (1, 1)),
    (True, AXIS_Z): ((0, -1), (1, -1), (2, 1)),
    (True, AXIS_X): ((0, -1), (2, -1), (1, -1)),
    (True, AXIS_Y): ((2, 1), (1, -1), (0, 1)),
}


class UVWMapError(ChunkError):
    """A UVW Map that cannot be evaluated; the mesh keeps its stored channel."""


class Params(collections.namedtuple("Params", "maptype utile vtile wtile uflip vflip wflip cap vertex_color length "
                                              "width height axis map_channel real_world")):
    __slots__ = ()

    @property
    def channel(self):
        """The channel written: 0 (vertex color) or the map channel."""
        return 0 if self.vertex_color else self.map_channel

    @property
    def supported(self):
        return self.maptype in SUPPORTED

    @property
    def type_name(self):
        return TYPE_NAMES.get(self.maptype, "type %d" % self.maptype)


DEFAULT = Params(PLANAR, 1.0, 1.0, 1.0, False, False, False, False, False, 1.0, 1.0, 1.0, AXIS_Z, 1, False)


def is_uvwmap(modifier):
    return modifier.superclass == classids.SC_OSMODIFIER and modifier.class_id == classids.UVW_MAP


def _number(block, i, default):
    v = block.get(i)
    if v is None:
        return default
    if isinstance(v, pblock.Animated):
        raise UVWMapError("parameter %d is animated (a controller)" % i)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise UVWMapError("parameter %d is not a number: %r" % (i, v))
    return v


def read_params(scene, modifier):
    """(Params, issues) of a UVW Map modifier (reader.modifiers.Modifier); UVWMapError when they cannot be read."""
    block = modifier.legacy.get(SLOT_PARAMS)
    if block is None:
        raise UVWMapError("no parameter block (reference slot 1)")
    d, issues = DEFAULT, []

    def flag(i, default):
        return _number(block, i, int(default)) != 0

    def size(i, default):
        v = float(_number(block, i, default))
        if v == 0:
            raise UVWMapError("parameter %d: a size of 0" % i)
        return v

    maptype = int(_number(block, P_TYPE, d.maptype))
    axis = int(_number(block, P_AXIS, d.axis))
    if axis not in (AXIS_X, AXIS_Y, AXIS_Z):
        issues.append("alignment %d, made as Z" % axis)
        axis = AXIS_Z
    channel = int(_number(block, P_CHANNEL, d.map_channel))
    if not 0 <= channel <= MAX_CHANNEL:
        raise UVWMapError("map channel %d" % channel)
    real_world = realworld.flag(scene.chunk(modifier.index), modifier.class_id)
    p = Params(maptype, float(_number(block, P_UTILE, d.utile)), float(_number(block, P_VTILE, d.vtile)),
               float(_number(block, P_WTILE, d.wtile)), flag(P_UFLIP, d.uflip), flag(P_VFLIP, d.vflip),
               flag(P_WFLIP, d.wflip), flag(P_CAP, d.cap), flag(P_CHANNEL_KIND, d.vertex_color),
               size(P_LENGTH, d.length), size(P_WIDTH, d.width), size(P_HEIGHT, d.height), axis, channel, real_world)
    return p, issues


def gizmo(scene, modifier):
    """(the gizmo's matrix at frame 0, issues) of a UVW Map: row vectors, rows 1 to 3 the axes with their scale,
    row 4 the translation; UVWMapError when its controller cannot be evaluated."""
    i = modifier.refs.get(SLOT_GIZMO, modifier.gizmo)
    if i is None:
        raise UVWMapError("no gizmo (reference slot 0)")
    m, issues = controllers.matrix(scene, i)
    fatal = [x.reason for x in issues if x.reason.startswith(_FATAL)]
    if fatal:
        raise UVWMapError("gizmo: %s" % fatal[0])
    return m, ["gizmo: %s" % x.reason for x in issues]


def _face_normals(numpy, p, lv, starts, totals):
    """Newell normals (not unit) of every face, float64 (F, 3)."""
    following = numpy.arange(1, len(lv) + 1)
    following[starts + totals - 1] = starts
    a, b = p[lv], p[lv[following]]
    cross = numpy.stack(((a[:, 1] - b[:, 1]) * (a[:, 2] + b[:, 2]),
                         (a[:, 2] - b[:, 2]) * (a[:, 0] + b[:, 0]),
                         (a[:, 0] - b[:, 0]) * (a[:, 1] + b[:, 1])), axis=1)
    return numpy.add.reduceat(cross, starts, axis=0) if len(starts) else numpy.zeros((0, 3))


def _frame(v, round_, axis):
    (i, si), (j, sj), (k, sk) = FRAMES[(round_, axis)]
    return si * v[:, i], sj * v[:, j], sk * v[:, k]


def apply(data, params, gizmo_tm, context_tm):
    """A copy of reader MeshData data whose channel params.channel holds the UVW Map's coordinates, one map vertex
    per face corner; positions, faces and the other channels are shared with data. gizmo_tm and context_tm are 4x4
    row-vector matrices (reader convention). UVWMapError for an unsupported type or a gizmo that cannot be
    inverted."""
    import numpy
    if not params.supported:
        raise UVWMapError("%s mapping is not evaluated" % params.type_name)
    g = numpy.asarray(gizmo_tm, dtype=numpy.float64)
    ctx = numpy.asarray(context_tm, dtype=numpy.float64)
    axes = g[:3, :3]
    sv = numpy.linalg.svd(axes, compute_uv=False) if numpy.isfinite(axes).all() else None
    if sv is None or not sv[0] > 0 or sv[-1] < 1e-12 * sv[0]:  # relative: a uniformly tiny gizmo still inverts
        raise UVWMapError("the gizmo cannot be inverted")
    m = ctx @ numpy.linalg.inv(g)  # row vectors: object space -> gizmo space
    p = numpy.asarray(data.positions, dtype=numpy.float64)
    lv = numpy.asarray(data.loop_vertices, dtype=numpy.int64)
    starts = numpy.asarray(data.loop_starts, dtype=numpy.int64)
    totals = numpy.diff(starts, append=len(lv))
    if (totals < 1).any():
        raise UVWMapError("a face without corners")
    face = numpy.repeat(numpy.arange(len(starts)), totals)
    q = p[lv] @ m[:3, :3] + m[3, :3]
    # like the points, not by the inverse transpose: that is what 3ds Max does (fitted, see the module docstring)
    n = (_face_normals(numpy, p, lv, starts, totals) @ m[:3, :3])[face]
    kind = params.maptype
    round_ = kind in (CYLINDRICAL, SPHERICAL)
    a, b, c = _frame(q, round_, params.axis)
    na, nb, nc = _frame(n, round_, params.axis)
    width, length, height = params.width, params.length, params.height
    with numpy.errstate(divide="ignore", invalid="ignore", over="ignore"):
        if kind == PLANAR:
            off = 0.0 if params.real_world else 0.5
            u, v, w = a / width + off, b / length + off, c / height + 0.5
        elif kind == BOX:
            x, y, z = a / width, b / length, c / height
            scaled = numpy.stack((na / width, nb / length, nc / height), axis=1)
            side = numpy.argmax(numpy.abs(scaled), axis=1)
            s = numpy.where(scaled[numpy.arange(len(side)), side] < 0, -1.0, 1.0)
            u = numpy.choose(side, (0.5 + s * y, 0.5 - s * x, 0.5 + s * x))
            v = numpy.choose(side, (z, z, y)) + 0.5
            w = numpy.choose(side, (x, y, z)) + 0.5
        else:
            big_x, big_y = a / (length / 2.0) + 0.0, b / (width / 2.0) + 0.0  # + 0.0: no -0.0 at the seam
            u = 0.5 + numpy.arctan2(big_x, -big_y) / (2.0 * math.pi)
            ring = numpy.hypot(big_x, big_y)
            if kind == CYLINDRICAL:
                pole = ring < POLE_TOLERANCE
                v, w = c / height + 0.5, ring
                capped = numpy.zeros(len(u), dtype=bool)
                if params.cap:
                    sa, sb, sc = numpy.abs(na / (length / 2.0)), numpy.abs(nb / (width / 2.0)), numpy.abs(nc / height)
                    capped = sc > numpy.maximum(sa, sb)
                    u = numpy.where(capped, 0.5 - big_y / 2.0, u)
                    v = numpy.where(capped, 0.5 + big_x / 2.0, v)
                    w = numpy.where(capped, c / height / 2.0, w)
            else:
                big_z = c / (height / 2.0)
                r = numpy.sqrt(ring * ring + big_z * big_z)
                v = 0.5 + numpy.arcsin(numpy.clip(numpy.where(r > 0, big_z / numpy.where(r > 0, r, 1.0), 0.0),
                                                  -1.0, 1.0)) / math.pi
                w = r
                capped = numpy.zeros(len(u), dtype=bool)
                center = r < CENTER_TOLERANCE
                v = numpy.where(center, 0.5, v)
                pole = (numpy.maximum(numpy.abs(big_x), numpy.abs(big_y)) < POLE_TOLERANCE * r) | center
            u = _seam(numpy, u, big_x, big_y, ~capped, pole, kind == CYLINDRICAL, starts, totals, face)
        uvw = numpy.stack((u, v, w), axis=1)
    for k, (flip, tile) in enumerate(((params.uflip, params.utile), (params.vflip, params.vtile),
                                      (params.wflip, params.wtile))):
        if flip:
            uvw[:, k] = 1.0 - uvw[:, k]
        uvw[:, k] *= tile
    with numpy.errstate(over="ignore", invalid="ignore"):
        uvw = uvw.astype(numpy.float32)
    if not numpy.isfinite(uvw).all():
        raise UVWMapError("coordinates that are not finite")
    maps = dict(data.maps)
    maps[params.channel] = geometry.MapChannel(params.channel, uvw, numpy.arange(len(lv), dtype=numpy.int32))
    return geometry.MeshData(data.positions, data.loop_vertices, data.loop_starts, data.smoothing_groups,
                             data.material_ids, maps, data.stored_vertices, data.stored_faces)


def _seam(numpy, u, big_x, big_y, side, pole, cylindrical, starts, totals, face):
    """u of the side (not cap) corners of a round map with the seam and the axis handled per face: a face with an
    edge across the seam (the half-plane X = 0, Y > 0, where u wraps) between two corners off the axis gets -1 on
    those above 0.5; a corner on the axis (pole: no angle) gets 0.5 on a cylindrical map, else the mean u of the
    rest of its face."""
    if not len(starts):
        return u
    following = numpy.arange(1, len(u) + 1)
    following[starts + totals - 1] = starts
    x0, y0, x1, y1 = big_x, big_y, big_x[following], big_y[following]
    with numpy.errstate(divide="ignore", invalid="ignore"):
        y_at = y0 + (y1 - y0) * (x0 / (x0 - x1))
    pole = side & pole
    angled = side & ~pole
    # a pole's X and Y are a residue whose sign means nothing: its edges never cross the seam
    across = angled & angled[following] & ((x0 < 0) != (x1 < 0)) & (y_at > 0)
    crossing = (numpy.add.reduceat(across.astype(numpy.int64), starts) > 0)[face]
    u = numpy.where(angled & crossing & (u > 0.5), u - 1.0, u)
    if cylindrical:
        return numpy.where(pole, 0.5, u)
    if pole.any():
        total = numpy.add.reduceat(numpy.where(angled, u, 0.0), starts)[face]
        count = numpy.add.reduceat(angled.astype(numpy.float64), starts)[face]
        u = numpy.where(pole & (count > 0), total / numpy.where(count > 0, count, 1.0), u)
    return u
