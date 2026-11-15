# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The base geometry of Editable Mesh and Editable Poly objects as numpy arrays.

    mesh = read_mesh(scene, i)          # MeshData, or None for an object of another class
    mesh.positions                      # float32 (N, 3), object space, file units
    mesh.loop_vertices, mesh.loop_starts, mesh.loop_totals    # polygons stay polygons
    mesh.smoothing_groups               # uint32 per face, one bit per group (bit 0 = group 1)
    mesh.material_ids                   # uint16 per face, zero-based (3ds Max shows 1 for 0)
    mesh.maps[1].uvw, mesh.maps[1].indices                    # per channel: float32 (M, 3), int32 per loop

Both classes keep their mesh in a 0x08FE container. docs/FORMAT.md says which fixture shows what.

Editable Mesh: 0x0914 = u32 count + 3 x f32 per vertex; 0x0912 = u32 count + 20 bytes per triangle (3 x u32 vertex,
u32 smoothing groups, u32 flags: low 16 bits edge visibility and state, high 16 bits the material ID). Each map
channel is 0x0959 (i32 channel), then 0x2394 (u32 count + 3 x f32 per map vertex) and 0x2396 (u32 count = face count,
3 x u32 per face).

Editable Poly: 0x0100 = u32 count, per vertex u32 flags and, unless the vertex is dead (flag 0x2), 3 x f32.
0x011A = u32 count, per face u32 degree, the vertices, a u16 field mask, then the fields the mask names, in this
order: 0x01 u32 face flags (a dead face has degree 0 and flag 0x2), 0x08 u16 material ID, 0x10 u32 smoothing
groups, 0x20 2 * (degree - 3) x u32 triangulation diagonals. Each map channel is 0x0124 (i32 channel), 0x0128
(u32 count + 3 x f32 per map vertex) and 0x012B (per stored face, dead ones included: u32 degree + the map
vertices; a dead face's map face keeps its old length).
Dead vertices and faces are left out; the vertices are renumbered.

Channel numbers are kept as stored: 0 = vertex color, 1 and up = texture coordinates, -1 and -2 = illumination and
alpha. Fixed-size records are read as numpy views (no Python loop); the variable-length Poly records take one loop
that only collects byte slices. The file comes from anywhere: a size that does not match its count, an index past
its array, an unknown face field, a record cut short or a map face whose degree differs from its face raise
GeometryError (a ChunkError) for that object only. Arrays are copies: nothing keeps the file's mapping alive.
No bpy; numpy is imported when a mesh is read.
"""
import array
import collections
import struct

from . import chunks, classids

ChunkError = chunks.ChunkError

GEOMETRY = 0x08FE
DEAD = 0x2  # vertex, edge and face flag of Editable Poly records that are no longer part of the mesh

# Editable Poly
_P_VERTS, _P_FACES = 0x0100, 0x011A
_P_MAP_CHANNEL, _P_MAP_VERTS, _P_MAP_FACES = 0x0124, 0x0128, 0x012B
FACE_FLAGS, FACE_MATERIAL, FACE_SMOOTHING, FACE_DIAGONALS = 0x01, 0x08, 0x10, 0x20
_FACE_FIELDS = FACE_FLAGS | FACE_MATERIAL | FACE_SMOOTHING | FACE_DIAGONALS

# Editable Mesh
_M_VERTS, _M_FACES = 0x0914, 0x0912
_M_MAP_CHANNEL, _M_MAP_VERTS, _M_MAP_FACES = 0x0959, 0x2394, 0x2396

_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")
_I32 = struct.Struct("<i")


class GeometryError(ChunkError):
    pass


class MapChannel(collections.namedtuple("MapChannel", "channel uvw indices")):
    """One map channel: its number, the map vertices (float32 (M, 3)) and one map vertex index per loop (int32,
    aligned with MeshData.loop_vertices)."""
    __slots__ = ()


class MeshData:
    """A mesh as arrays: positions float32 (N, 3); loop_vertices int32 (L,) and loop_starts int32 (F,), the first
    loop of each face; smoothing_groups uint32 (F,); material_ids uint16 (F,), zero-based; maps {channel:
    MapChannel} in file order. stored_vertices and stored_faces count the records as stored, dead ones included:
    what 3ds Max reports (polyop.getNumVerts, polyop.getNumFaces)."""
    __slots__ = ("positions", "loop_vertices", "loop_starts", "smoothing_groups", "material_ids", "maps",
                 "stored_vertices", "stored_faces")

    def __init__(self, positions, loop_vertices, loop_starts, smoothing_groups, material_ids, maps,
                 stored_vertices=None, stored_faces=None):
        self.positions, self.loop_vertices, self.loop_starts = positions, loop_vertices, loop_starts
        self.smoothing_groups, self.material_ids, self.maps = smoothing_groups, material_ids, maps
        self.stored_vertices = len(positions) if stored_vertices is None else stored_vertices
        self.stored_faces = len(loop_starts) if stored_faces is None else stored_faces

    def __repr__(self):
        return "MeshData(%d vertices, %d faces, %d loops, channels %s)" % (
            len(self.positions), len(self.loop_starts), len(self.loop_vertices), sorted(self.maps))

    @property
    def loop_totals(self):
        """The number of loops (vertices) of each face, int32 (F,)."""
        import numpy
        return numpy.diff(self.loop_starts, append=numpy.int32(len(self.loop_vertices))).astype(numpy.int32)


def _geometry(chunk):
    geo = chunk.first(GEOMETRY) if chunk.container else None
    if geo is None or not geo.container:
        raise GeometryError("no 0x08FE geometry container")
    return geo


def _required(geo, cid):
    chunk = geo.first(cid)
    if chunk is None:
        raise GeometryError("no %04X chunk" % cid)
    return chunk


def _count(chunk, item_size):
    """The u32 count at the start of chunk, checked against the payload: count items of item_size follow."""
    if chunk.payload_size < 4:
        raise GeometryError("%04X of %d bytes has no count" % (chunk.id, chunk.payload_size))
    n, = chunk.unpack("<I")
    if chunk.payload_size != 4 + n * item_size:
        raise GeometryError("%04X: %d bytes for %d items of %d bytes" % (chunk.id, chunk.payload_size, n, item_size))
    return n


def _points(chunk):
    """u32 count + 3 x f32 per point as float32 (n, 3)."""
    import numpy
    n = _count(chunk, 12)
    return numpy.array(chunk.as_array("<f4", 4, n * 3), dtype=numpy.float32).reshape(n, 3)


def _indices(values, limit, what):
    """values (unsigned ints) as int32, each below limit."""
    import numpy
    if len(values) and int(values.max()) >= limit:
        raise GeometryError("%s index %d past the %d items" % (what, int(values.max()), limit))
    return numpy.array(values, dtype=numpy.int32)


def _channels(geo, channel_id, verts_id, faces_id, read_faces):
    """The map channels in file order: a channel chunk, then its map vertices and map faces."""
    maps, channel, uvw = {}, None, None
    for chunk in geo.children:
        if chunk.id == channel_id:
            if chunk.payload_size < 4:
                raise GeometryError("map channel chunk %04X of %d bytes" % (chunk.id, chunk.payload_size))
            channel, = chunk.unpack("<i")
            if channel in maps:
                raise GeometryError("map channel %d twice" % channel)
            uvw = None
        elif chunk.id == verts_id:
            if channel is None:
                raise GeometryError("map vertices without a channel")
            uvw = _points(chunk)
        elif chunk.id == faces_id:
            if channel is None or uvw is None:
                raise GeometryError("map faces without a channel and its map vertices")
            maps[channel] = MapChannel(channel, uvw, _indices(read_faces(chunk), len(uvw),
                                                              "map channel %d vertex" % channel))
            channel = uvw = None
    return maps


def read_editable_mesh(chunk):
    """MeshData of an Editable Mesh object's chunk."""
    import numpy
    geo = _geometry(chunk)
    positions = _points(_required(geo, _M_VERTS))
    faces = _required(geo, _M_FACES)
    nf = _count(faces, 20)
    rec = faces.as_array([("v", "<u4", (3,)), ("smooth", "<u4"), ("flags", "<u4")], 4, nf)
    loop_vertices = _indices(rec["v"].reshape(-1), len(positions), "vertex")
    loop_starts = numpy.arange(0, 3 * nf, 3, dtype=numpy.int32)
    smoothing = numpy.array(rec["smooth"], dtype=numpy.uint32)
    materials = (rec["flags"] >> 16).astype(numpy.uint16)
    del rec

    def map_faces(c):
        if _count(c, 12) != nf:
            raise GeometryError("%d map faces for %d faces" % (_count(c, 12), nf))
        return c.as_array("<u4", 4, 3 * nf)

    maps = _channels(geo, _M_MAP_CHANNEL, _M_MAP_VERTS, _M_MAP_FACES, map_faces)
    return MeshData(positions, loop_vertices, loop_starts, smoothing, materials, maps)


def _poly_positions(chunk):
    """(float32 (live, 3), remap or None): remap[i] is the new index of stored vertex i, -1 for a dead one."""
    import numpy
    if chunk.payload_size < 4:
        raise GeometryError("%04X of %d bytes has no count" % (chunk.id, chunk.payload_size))
    n, = chunk.unpack("<I")
    if chunk.payload_size == 4 + 16 * n:  # no dead vertex: fixed-size records
        rec = chunk.as_array([("flags", "<u4"), ("p", "<f4", (3,))], 4, n)
        if numpy.any(rec["flags"] & DEAD):
            raise GeometryError("a dead vertex with a position")
        return numpy.array(rec["p"], dtype=numpy.float32), None
    data = chunk.view()
    size, off, live, points = len(data), 4, bytearray(n), bytearray()
    try:
        for i in range(n):
            flags, = _U32.unpack_from(data, off)
            if flags & DEAD:
                off += 4
            else:
                if off + 16 > size:
                    raise GeometryError("vertex %d cut short" % i)
                points += data[off + 4:off + 16]
                live[i] = 1
                off += 16
    except struct.error:
        raise GeometryError("vertex records cut short (%d of %d bytes)" % (off, size)) from None
    if off != size:
        raise GeometryError("%d bytes after the %d vertex records" % (size - off, n))
    mask = numpy.frombuffer(bytes(live), dtype=numpy.uint8).astype(bool)
    remap = numpy.full(n, -1, dtype=numpy.int64)
    remap[mask] = numpy.arange(int(mask.sum()))
    return numpy.frombuffer(bytes(points), dtype="<f4").astype(numpy.float32).reshape(-1, 3), remap


def _poly_faces(chunk):
    """(loops u32, degrees of every stored face, live mask, smoothing, materials) from 0x011A."""
    data = chunk.view()
    size = len(data)
    if size < 4:
        raise GeometryError("%04X of %d bytes has no count" % (chunk.id, size))
    n, = _U32.unpack_from(data, 0)
    off = 4
    loops, degrees, live = bytearray(), array.array("I"), bytearray(n)
    smooth, mats = array.array("I"), array.array("H")
    unpack_u32, unpack_u16 = _U32.unpack_from, _U16.unpack_from
    try:
        for i in range(n):
            deg, = unpack_u32(data, off)
            start = off + 4
            off = start + 4 * deg
            if off > size:
                raise GeometryError("face %d: %d vertices past the end" % (i, deg))
            mask, = unpack_u16(data, off)
            off += 2
            if mask & ~_FACE_FIELDS:
                raise GeometryError("face %d: unknown field mask %04X" % (i, mask))
            flags = sg = mat = 0
            if mask & FACE_FLAGS:
                flags, = unpack_u32(data, off)
                off += 4
            if mask & FACE_MATERIAL:
                mat, = unpack_u16(data, off)
                off += 2
            if mask & FACE_SMOOTHING:
                sg, = unpack_u32(data, off)
                off += 4
            if mask & FACE_DIAGONALS:
                if deg < 3:
                    raise GeometryError("face %d: diagonals of a face with %d vertices" % (i, deg))
                off += 8 * (deg - 3)
            degrees.append(deg)
            if deg == 0 or flags & DEAD:
                continue
            if deg < 3:
                raise GeometryError("face %d has %d vertices" % (i, deg))
            loops += data[start:start + 4 * deg]
            live[i] = 1
            smooth.append(sg)
            mats.append(mat)
    except struct.error:
        raise GeometryError("face records cut short (%d of %d bytes)" % (off, size)) from None
    if off != size:
        raise GeometryError("%d bytes after the %d face records" % (size - off, n))
    return loops, degrees, live, smooth, mats


def _poly_map_faces(chunk, degrees, live):
    """The map vertex indices of the live faces from a 0x012B payload, one record per stored face. The map face of
    a dead face keeps the length it had (scene A), so its length is read, not known."""
    import numpy
    data = chunk.view()
    size, off, out = len(data), 0, bytearray()
    try:
        for i, deg in enumerate(degrees):
            n, = _U32.unpack_from(data, off)
            start = off + 4
            off = start + 4 * n
            if off > size:
                raise GeometryError("map face %d: %d vertices past the end" % (i, n))
            if live[i]:
                if n != deg:
                    raise GeometryError("map face %d has %d vertices, its face %d" % (i, n, deg))
                out += data[start:off]
    except struct.error:
        raise GeometryError("map faces cut short (%d of %d bytes)" % (off, size)) from None
    if off != size:
        raise GeometryError("%d bytes after the %d map faces" % (size - off, len(degrees)))
    return numpy.frombuffer(bytes(out), dtype="<u4")


def read_editable_poly(chunk):
    """MeshData of an Editable Poly object's chunk."""
    import numpy
    geo = _geometry(chunk)
    positions, remap = _poly_positions(_required(geo, _P_VERTS))
    loops, stored_degrees, stored_live, smooth, mats = _poly_faces(_required(geo, _P_FACES))
    nstored = len(remap) if remap is not None else len(positions)
    loop_vertices = _indices(numpy.frombuffer(bytes(loops), dtype="<u4"), nstored, "vertex")
    if remap is not None:
        loop_vertices = remap[loop_vertices]
        if len(loop_vertices) and int(loop_vertices.min()) < 0:
            raise GeometryError("a face uses a dead vertex")
        loop_vertices = loop_vertices.astype(numpy.int32)
    degrees = numpy.frombuffer(stored_degrees, dtype=numpy.uint32).astype(numpy.int64)
    live = numpy.frombuffer(bytes(stored_live), dtype=numpy.uint8).astype(bool)
    totals = degrees[live]
    loop_starts = numpy.zeros(len(totals), dtype=numpy.int32)
    if len(totals):
        numpy.cumsum(totals[:-1], out=loop_starts[1:])
    # word positions of each stored face's degree in a 0x012B payload laid out like the faces
    heads = numpy.zeros(len(degrees), dtype=numpy.int64)
    if len(degrees):
        numpy.cumsum(degrees[:-1] + 1, out=heads[1:])
    words = int(degrees.sum()) + len(degrees)
    keep = numpy.ones(words, dtype=bool)
    keep[heads] = False
    dead_words = numpy.repeat(~live, degrees + 1)  # a dead face's words, its degree included

    def map_faces(c):
        if c.payload_size == 4 * words:  # every map face as long as its face: the layout is known
            w = c.as_array("<u4")
            if not len(heads) or numpy.array_equal(w[heads], degrees):
                return w[keep & ~dead_words]
        return _poly_map_faces(c, stored_degrees, stored_live)

    maps = _channels(geo, _P_MAP_CHANNEL, _P_MAP_VERTS, _P_MAP_FACES, map_faces)
    return MeshData(positions, loop_vertices, loop_starts, numpy.frombuffer(smooth, dtype=numpy.uint32).copy(),
                    numpy.frombuffer(mats, dtype=numpy.uint16).copy(), maps, nstored, len(degrees))


_READERS = {
    classids.EDITABLE_MESH: read_editable_mesh,
    classids.EDITABLE_POLY: read_editable_poly,
}


def read_mesh(scene, i):
    """MeshData of object i when it is an Editable Mesh or Editable Poly, else None. A broken mesh raises
    GeometryError naming the object."""
    entry = scene.entry(i)
    if entry is None or entry.superclass != classids.SC_GEOMOBJECT:
        return None
    reader = _READERS.get(entry.class_id)
    if reader is None:
        return None
    try:
        return reader(scene.chunk(i))
    except (ChunkError, struct.error) as exc:
        raise GeometryError("object %d (%s): %s" % (i, entry.name, exc)) from None
