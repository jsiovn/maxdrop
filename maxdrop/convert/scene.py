# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scene description: every node of a .max file with its transform and mesh, in meters, ready for build/.

    desc = read(path)                   # the file's own system unit; read(path, meters=0.01) overrides it
    desc.nodes                          # NodeDescription per node, pre-order: a parent before its children
    desc.meshes[node.mesh]              # MeshDescription, shared by the nodes of one base object
    desc.placeholders                   # Counter: class name -> nodes built as an empty
    desc.issues                         # [(node object index, reason)] for the report

Matrices are Blender's convention: 4x4 tuples of rows, a column vector p becomes M @ p, the translation is the
last column. The reader's row-vector matrices are transposed here. node.matrix is the local matrix (relative to
the parent's node transform), node.world the world matrix; both are the node transform (Max's pivot), so a
child placed relative to its parent lands where 3ds Max puts it. The object offset (where the object sits
relative to the pivot) is baked into the mesh vertices instead, which is why a mesh is keyed by (base object
index, offset): instances share one mesh as long as their offsets agree, which is the usual case. An offset with
a negative determinant reverses every polygon's loops, so the normals stay outward.

`meters` (per file unit) scales vertex positions and every translation, never a rotation or scale. Z is up in 3ds
Max and in Blender: no axis change. mirrored flags a world matrix with a negative determinant; Blender renders
such an object with outward normals by itself, so nothing is flipped for it.

Smoothing groups become flat faces (no group) and sharp edges: an edge is sharp where two of its faces share no
group, never on a boundary; on an edge with more than two faces any such pair decides, and past MAX_EDGE_MASKS
distinct masks the edge is sharp (a file can put any number of faces on one edge). Faces Blender cannot hold (a
vertex used twice, the vertex set of an earlier face) are left out and reported. UV layers: every map channel >= 1, ascending; channel 1 is "UVMap", channel n
"UVChannel_<n>"; the w coordinate is dropped.

A node becomes an EMPTY placeholder when its base object is not an Editable Mesh or Editable Poly, when it has no
object, or when the reader refuses its geometry or its record; placeholders counts them by the class name of the
file's class directory ("" when there is none). Modifiers are listed, not evaluated: the base mesh is built.
A local matrix with shear (a scale along a rotated axis) is reported: Blender's matrix_basis cannot hold it. A
base object's reader arrays are dropped once its last node is described.
Nothing here imports bpy; numpy is imported when a scene is described.
"""
import collections
import math

from ..reader import cfb, chunks, controllers, geometry, units
from ..reader import scene as reader_scene

MESH, EMPTY = "MESH", "EMPTY"
UV_FIRST = "UVMap"
UV_NAME = "UVChannel_%d"
MAX_EDGE_MASKS = 64  # distinct smoothing-group masks paired on one non-manifold edge
SHEAR_TOLERANCE = 1e-5  # |cos| between two rows of a local matrix
SHEARED = "shear in the local matrix, not kept"

ChunkError = chunks.ChunkError


class NodeDescription:
    """One node: index is its object index, parent the parent's (None at the top level); kind MESH or EMPTY; mesh
    the key into SceneDescription.meshes (None for an empty); class_name the base object's class ("" without
    one); modifiers the class names of its modifier stack, top first."""
    __slots__ = ("index", "name", "parent", "matrix", "world", "kind", "mesh", "class_name", "mirrored",
                 "modifiers")

    def __init__(self, index, name, parent, matrix, world, kind, mesh, class_name, mirrored, modifiers):
        self.index, self.name, self.parent, self.matrix, self.world = index, name, parent, matrix, world
        self.kind, self.mesh, self.class_name, self.mirrored, self.modifiers = kind, mesh, class_name, mirrored, \
            modifiers

    def __repr__(self):
        return "NodeDescription(%d, %r, %s, parent=%r)" % (self.index, self.name, self.kind, self.parent)


class MeshDescription:
    """One mesh in meters, offset baked: positions float32 (N, 3); loop_vertices int32 (L,); loop_starts and
    loop_totals int32 (F,); material_indices int32 (F,), zero-based; sharp_faces bool (F,); sharp_edges int32
    (E, 2), sorted vertex pairs; uv_layers [(name, float32 (L, 2))]; users the object indices of the nodes that
    share it, in walk order; dropped_faces the faces left out (a repeated vertex, doubled)."""
    __slots__ = ("key", "name", "positions", "loop_vertices", "loop_starts", "loop_totals", "material_indices",
                 "sharp_faces", "sharp_edges", "uv_layers", "users", "dropped_faces")

    def __init__(self, key, name, positions, loop_vertices, loop_starts, loop_totals, material_indices,
                 sharp_faces, sharp_edges, uv_layers, dropped_faces=0):
        self.key, self.name, self.positions = key, name, positions
        self.loop_vertices, self.loop_starts, self.loop_totals = loop_vertices, loop_starts, loop_totals
        self.material_indices, self.sharp_faces, self.sharp_edges = material_indices, sharp_faces, sharp_edges
        self.uv_layers, self.dropped_faces = uv_layers, dropped_faces
        self.users = []

    def __repr__(self):
        return "MeshDescription(%r, %d vertices, %d faces, %d UV layers)" % (
            self.name, len(self.positions), len(self.loop_starts), len(self.uv_layers))


class SceneDescription:
    """nodes in walk order, meshes {key: MeshDescription} in order of first use, meters per file unit, unit the
    reader's SystemUnit (None when the file does not say), placeholders and issues."""
    __slots__ = ("nodes", "meshes", "meters", "unit", "placeholders", "issues")

    def __init__(self, meters, unit=None):
        self.nodes, self.meshes, self.meters, self.unit = [], {}, meters, unit
        self.placeholders = collections.Counter()
        self.issues = []

    def __repr__(self):
        return "SceneDescription(%d nodes, %d meshes, %d placeholders, %g m per unit)" % (
            len(self.nodes), len(self.meshes), sum(self.placeholders.values()), self.meters)


def blender_matrix(m, meters=1.0):
    """A reader matrix (row vectors, translation in row 4) as Blender's (column vectors), translation scaled."""
    return ((m[0][0], m[1][0], m[2][0], m[3][0] * meters),
            (m[0][1], m[1][1], m[2][1], m[3][1] * meters),
            (m[0][2], m[1][2], m[2][2], m[3][2] * meters),
            (0.0, 0.0, 0.0, 1.0))


def determinant3(m):
    """The determinant of the upper-left 3x3 of a 4x4 matrix (the same in either convention)."""
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def sharp_edges(loop_vertices, loop_starts, loop_totals, groups):
    """The edges, as sorted vertex pairs int32 (E, 2), where two faces meet that share no smoothing group."""
    import numpy
    lv = numpy.asarray(loop_vertices, dtype=numpy.int64)
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    if not len(lv):
        return numpy.zeros((0, 2), dtype=numpy.int32)
    face = numpy.repeat(numpy.arange(len(starts)), totals)
    following = numpy.arange(1, len(lv) + 1)
    following[starts + totals - 1] = starts  # the last loop of a face closes it
    a, b = lv, lv[following]
    lo, hi = numpy.minimum(a, b), numpy.maximum(a, b)
    key = lo * (int(lv.max()) + 1) + hi
    order = numpy.argsort(key, kind="stable")
    key, face = key[order], face[order]
    groups = numpy.asarray(groups, dtype=numpy.uint32)
    _keys, first, counts = numpy.unique(key, return_index=True, return_counts=True)
    two = first[counts == 2]
    sharp = two[(groups[face[two]] & groups[face[two + 1]]) == 0]
    more = [start for start, n in zip(first[counts > 2], counts[counts > 2])
            if _disjoint(groups[face[start:start + n]])]
    if more:
        sharp = numpy.sort(numpy.concatenate((sharp, numpy.asarray(more, dtype=sharp.dtype))))
    src = order[sharp]
    return numpy.stack((lo[src], hi[src]), axis=1).astype(numpy.int32)


def _disjoint(masks):
    """Whether two of the smoothing-group masks of one non-manifold edge share no group. Equal non-zero masks always
    share one, so only the distinct masks are paired, at most MAX_EDGE_MASKS of them: a file can put any number of
    faces on one edge, and an edge past the cap is taken as sharp."""
    distinct = {int(v) for v in masks}
    if 0 in distinct or len(distinct) > MAX_EDGE_MASKS:
        return True
    distinct = sorted(distinct)
    return any(x & y == 0 for k, x in enumerate(distinct) for y in distinct[k + 1:])


def valid_faces(loop_vertices, loop_starts, loop_totals):
    """bool (F,): False for a face Blender cannot hold, one that uses a vertex twice or has the vertex set of an
    earlier face (3ds Max keeps both: degenerate and doubled triangles occur in files)."""
    import numpy
    lv = numpy.asarray(loop_vertices, dtype=numpy.int64)
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    keep = numpy.ones(len(starts), dtype=bool)
    for total in numpy.unique(totals):  # one numpy pass per face size
        faces = numpy.flatnonzero(totals == total)
        rows = numpy.sort(lv[starts[faces][:, None] + numpy.arange(total)], axis=1)
        repeated = (numpy.diff(rows, axis=1) == 0).any(axis=1)
        keep[faces[repeated]] = False
        good = faces[~repeated]
        if not len(good):
            continue
        _rows, first = numpy.unique(rows[~repeated], axis=0, return_index=True)
        doubled = numpy.ones(len(good), dtype=bool)
        doubled[first] = False
        keep[good[doubled]] = False
    return keep


def _reversed_loops(loop_starts, loop_totals):
    """The loop permutation that reverses every polygon in place."""
    import numpy
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    face = numpy.repeat(numpy.arange(len(starts)), totals)
    return 2 * starts[face] + totals[face] - 1 - numpy.arange(int(totals.sum()))


def mesh_description(key, name, data, offset, meters):
    """A MeshDescription of reader MeshData: faces Blender cannot hold left out (counted in dropped_faces), the
    offset (a reader matrix) applied, then meters."""
    import numpy
    p = numpy.asarray(data.positions, dtype=numpy.float64)
    if offset is not None:
        m = numpy.asarray(offset, dtype=numpy.float64)
        p = p @ m[:3, :3] + m[3, :3]
    positions = (p * meters).astype(numpy.float32)
    starts = numpy.asarray(data.loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(data.loop_totals, dtype=numpy.int64)
    lv = numpy.asarray(data.loop_vertices, dtype=numpy.int32)
    groups, materials = data.smoothing_groups, data.material_ids
    loops = None  # the loops kept, in their new order; None = all, unchanged
    keep = valid_faces(lv, starts, totals)
    dropped = int(len(keep) - keep.sum())
    if dropped:
        loops = numpy.flatnonzero(numpy.repeat(keep, totals))
        totals, groups, materials = totals[keep], groups[keep], materials[keep]
        starts = numpy.zeros(len(totals), dtype=numpy.int64)
        if len(totals):
            numpy.cumsum(totals[:-1], out=starts[1:])
    if offset is not None and determinant3(offset) < 0:
        perm = _reversed_loops(starts, totals)
        loops = perm if loops is None else loops[perm]
    if loops is not None:
        lv = lv[loops]
    uv_layers = []
    for channel in sorted(c for c in data.maps if c >= 1):
        mc = data.maps[channel]
        indices = mc.indices if loops is None else mc.indices[loops]
        uv = numpy.ascontiguousarray(mc.uvw[indices][:, :2], dtype=numpy.float32)
        uv_layers.append((UV_FIRST if channel == 1 else UV_NAME % channel, uv))
    return MeshDescription(key, name, positions, lv, starts.astype(numpy.int32), totals.astype(numpy.int32),
                           materials.astype(numpy.int32), groups == 0, sharp_edges(lv, starts, totals, groups),
                           uv_layers, dropped)


def sheared(m):
    """Whether the 3x3 of a reader matrix is more than a rotation and a scale along its own axes (its rows are not
    orthogonal): Blender's matrix_basis cannot hold that."""
    rows = [m[r][:3] for r in range(3)]
    for x in range(3):
        for y in range(x + 1, 3):
            a, b = rows[x], rows[y]
            dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
            size = math.sqrt((a[0] ** 2 + a[1] ** 2 + a[2] ** 2) * (b[0] ** 2 + b[1] ** 2 + b[2] ** 2))
            if abs(dot) > SHEAR_TOLERANCE * size:
                return True
    return False


def describe(scene, meters=1.0, unit=None):
    """The SceneDescription of a reader.scene.Scene; meters is the length of one file unit."""
    if not (math.isfinite(meters) and meters > 0):
        raise ValueError("meters per unit must be a positive number, not %r" % (meters,))
    t = controllers.Transforms(scene)
    desc = SceneDescription(meters, unit)
    order = scene.walk()
    found = {}  # node -> (name, Stack or None), or the ChunkError its record or object stack raised
    remaining = collections.Counter()  # base object -> nodes still to build: its MeshData goes with the last
    for i in order:
        try:
            node = scene.node(i)
            stack = scene.object_stack(node.object) if node.object is not None else None
            found[i] = (node.name, stack)
            if stack is not None and stack.base is not None:
                remaining[stack.base] += 1
        except ChunkError as exc:
            found[i] = exc
    data_of = {}  # base object index -> MeshData, or None when the reader refused or does not read it
    for i in order:
        local, world = t.local(i), t.world(i)
        kind, key, class_name, modifiers, name = EMPTY, None, "", (), ""
        if isinstance(found[i], ChunkError):  # a damaged node record or object stack: an empty, children placed
            desc.issues.append((i, "node: %s" % found[i]))
        else:
            name, stack = found[i]
            base = stack.base if stack is not None else None
            if stack is not None:
                modifiers = tuple(_class_name(scene, m) for m in stack.modifiers)
            if base is not None:
                class_name = _class_name(scene, base)
                if base not in data_of:
                    try:
                        data_of[base] = geometry.read_mesh(scene, base)
                    except geometry.GeometryError as exc:
                        data_of[base] = None
                        desc.issues.append((i, "geometry: %s" % exc))
                data = data_of[base]
                if data is not None:
                    offset = t.offset(i)
                    offset = None if offset == controllers.IDENTITY else offset
                    key = (base, offset)
                    md = desc.meshes.get(key)
                    if md is None:
                        md = desc.meshes[key] = mesh_description(key, name, data, offset, meters)
                        if md.dropped_faces:
                            desc.issues.append((i, "geometry: %d faces with a repeated vertex or doubled, left out"
                                                % md.dropped_faces))
                    md.users.append(i)
                    kind = MESH
                remaining[base] -= 1
                if not remaining[base]:
                    del data_of[base]
        if kind == EMPTY:
            desc.placeholders[class_name] += 1
        if sheared(local):
            desc.issues.append((i, "transform: %s" % SHEARED))
        desc.nodes.append(NodeDescription(i, name, scene.parent(i), blender_matrix(local, meters),
                                          blender_matrix(world, meters), kind, key, class_name,
                                          determinant3(world) < 0, modifiers))
    desc.issues.extend((issue.node, "transform: %s" % issue.reason) for issue in t.issues)
    return desc


def _class_name(scene, i):
    entry = scene.entry(i)
    return entry.name if entry is not None else ""


def read(path, meters=None):
    """The SceneDescription of a .max file. meters None: the file's system unit, 1.0 when it does not say."""
    with cfb.CompoundFile(path) as cf:
        sc = reader_scene.Scene.from_file(cf)
        unit = units.system_unit(sc)
        if meters is None:
            meters = unit.meters if unit is not None else 1.0
        return describe(sc, meters, unit)
