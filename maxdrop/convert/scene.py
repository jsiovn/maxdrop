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
group, never on a boundary. UV layers: every map channel >= 1, ascending; channel 1 is "UVMap", channel n
"UVChannel_<n>"; the w coordinate is dropped.

A node becomes an EMPTY placeholder when its base object is not an Editable Mesh or Editable Poly, when it has no
object, or when the reader refuses its geometry or its record; placeholders counts them by the class name of the
file's class directory ("" when there is none). Modifiers are listed, not evaluated: the base mesh is built.
Nothing here imports bpy; numpy is imported when a scene is described.
"""
import collections
import math

from ..reader import cfb, chunks, controllers, geometry, units
from ..reader import scene as reader_scene

MESH, EMPTY = "MESH", "EMPTY"
UV_FIRST = "UVMap"
UV_NAME = "UVChannel_%d"

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
    share it, in walk order."""
    __slots__ = ("key", "name", "positions", "loop_vertices", "loop_starts", "loop_totals", "material_indices",
                 "sharp_faces", "sharp_edges", "uv_layers", "users")

    def __init__(self, key, name, positions, loop_vertices, loop_starts, loop_totals, material_indices,
                 sharp_faces, sharp_edges, uv_layers):
        self.key, self.name, self.positions = key, name, positions
        self.loop_vertices, self.loop_starts, self.loop_totals = loop_vertices, loop_starts, loop_totals
        self.material_indices, self.sharp_faces, self.sharp_edges = material_indices, sharp_faces, sharp_edges
        self.uv_layers = uv_layers
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
    more = []
    for start, n in zip(first[counts > 2], counts[counts > 2]):  # non-manifold: rare, any pair decides
        g = [int(v) for v in groups[face[start:start + n]]]
        if any(g[x] & g[y] == 0 for x in range(n) for y in range(x + 1, n)):
            more.append(start)
    if more:
        sharp = numpy.sort(numpy.concatenate((sharp, numpy.asarray(more, dtype=sharp.dtype))))
    src = order[sharp]
    return numpy.stack((lo[src], hi[src]), axis=1).astype(numpy.int32)


def _reversed_loops(loop_starts, loop_totals):
    """The loop permutation that reverses every polygon in place."""
    import numpy
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    face = numpy.repeat(numpy.arange(len(starts)), totals)
    return 2 * starts[face] + totals[face] - 1 - numpy.arange(int(totals.sum()))


def mesh_description(key, name, data, offset, meters):
    """A MeshDescription of reader MeshData: the offset (a reader matrix) applied, then meters."""
    import numpy
    p = numpy.asarray(data.positions, dtype=numpy.float64)
    if offset is not None:
        m = numpy.asarray(offset, dtype=numpy.float64)
        p = p @ m[:3, :3] + m[3, :3]
    positions = (p * meters).astype(numpy.float32)
    starts = numpy.asarray(data.loop_starts, dtype=numpy.int32)
    totals = data.loop_totals
    lv = numpy.asarray(data.loop_vertices, dtype=numpy.int32)
    perm = None
    if offset is not None and determinant3(offset) < 0:
        perm = _reversed_loops(starts, totals)
        lv = lv[perm]
    uv_layers = []
    for channel in sorted(c for c in data.maps if c >= 1):
        mc = data.maps[channel]
        indices = mc.indices if perm is None else mc.indices[perm]
        uv = numpy.ascontiguousarray(mc.uvw[indices][:, :2], dtype=numpy.float32)
        uv_layers.append((UV_FIRST if channel == 1 else UV_NAME % channel, uv))
    return MeshDescription(key, name, positions, lv, starts, totals.astype(numpy.int32),
                           data.material_ids.astype(numpy.int32), data.smoothing_groups == 0,
                           sharp_edges(lv, starts, totals, data.smoothing_groups), uv_layers)


def describe(scene, meters=1.0, unit=None, transforms=None):
    """The SceneDescription of a reader.scene.Scene; meters is the length of one file unit."""
    if not (math.isfinite(meters) and meters > 0):
        raise ValueError("meters per unit must be a positive number, not %r" % (meters,))
    t = transforms if transforms is not None else controllers.Transforms(scene)
    desc = SceneDescription(meters, unit)
    data_of = {}  # base object index -> MeshData, or None when the reader refused or does not read it
    for i in scene.walk():
        local, world = t.local(i), t.world(i)
        parent = scene.parent(i)
        kind, key, class_name, modifiers, name = EMPTY, None, "", (), ""
        try:
            node = scene.node(i)
            name = node.name
            if node.object is not None:
                stack = scene.object_stack(node.object)
                modifiers = tuple(_class_name(scene, m) for m in stack.modifiers)
                if stack.base is not None:
                    class_name = _class_name(scene, stack.base)
                    if stack.base not in data_of:
                        try:
                            data_of[stack.base] = geometry.read_mesh(scene, stack.base)
                        except geometry.GeometryError as exc:
                            data_of[stack.base] = None
                            desc.issues.append((i, "geometry: %s" % exc))
                    data = data_of[stack.base]
                    if data is not None:
                        offset = t.offset(i)
                        offset = None if offset == controllers.IDENTITY else offset
                        key = (stack.base, offset)
                        md = desc.meshes.get(key)
                        if md is None:
                            md = desc.meshes[key] = mesh_description(key, name, data, offset, meters)
                        md.users.append(i)
                        kind = MESH
        except ChunkError as exc:  # a damaged node record or object stack: an empty, its children still placed
            desc.issues.append((i, "node: %s" % exc))
        if kind == EMPTY:
            desc.placeholders[class_name] += 1
        matrix, world_b = blender_matrix(local, meters), blender_matrix(world, meters)
        desc.nodes.append(NodeDescription(i, name, parent, matrix, world_b, kind, key, class_name,
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
