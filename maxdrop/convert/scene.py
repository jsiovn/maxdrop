# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scene description: every node of a .max file with its transform and mesh, in meters, ready for build/.

    desc = read(path)                   # the file's own system unit; read(path, meters=0.01) overrides it
    desc.nodes                          # NodeDescription per node, pre-order: a parent before its children
    desc.meshes[node.mesh]              # MeshDescription, shared by the nodes of one base object
    desc.curves[node.curve]             # CurveDescription of a shape node, shared the same way
    desc.placeholders                   # Counter: class name -> nodes built as an empty
    desc.layers                         # LayerDescription per layer that holds a node, a parent before its children
    desc.unknown_controllers            # Counter: controller class name -> times met
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

A shape (reader.shapes: Line, Editable Spline, Rectangle, Circle, Ellipse, Arc, NGon) becomes a CURVE, keyed and
shared like a mesh, its offset baked into the knots: one Bezier spline per spline, Max's in and out vectors as the
left and right handles. A segment 3ds Max draws straight (segment type line) gets handles a third of the way along
its chord, whatever the stored vectors. Resolution: 3ds Max's steps + 1 segments per Bezier segment, ADAPTIVE for
an adaptive shape. A shape that renders (Enable In Renderer) gets a round bevel of its thickness (Max's thickness
is the diameter) with about as many sides; a rectangular section is drawn round (an issue).

A node becomes an EMPTY placeholder when its base object is not an Editable Mesh, Editable Poly or a shape read
here, when it has no object, or when the reader refuses its geometry or its record; placeholders counts them by the class name of the
file's class directory ("" when there is none). A Dummy helper (a group head is one) is an EMPTY too, but that is
its conversion, not a placeholder. A group head keeps its members as children: that is how 3ds Max stores a group.
Modifiers are listed, not evaluated: the base mesh is built.

Layers: each node names its layer's object index (None without one, or when the layer record cannot be read, which
is an issue); desc.layers holds the layers that hold a node and their parent layers, in the Layer Manager's order
with every parent before its children. A node's hidden, frozen and renderable flags are its own: a hidden layer
hides its nodes in 3ds Max without setting their flag, so build/ applies the layer's flags to its collection.

A local matrix with shear (a scale along a rotated axis) sets node.sheared: Blender's matrix_basis cannot hold
it, so build/ puts the rest into matrix_parent_inverse. A base object's reader arrays are dropped once its last
node is described.
Nothing here imports bpy; numpy is imported when a scene is described.
"""
import collections
import math

from ..reader import cfb, chunks, classids, controllers, geometry, shapes, units
from ..reader import scene as reader_scene

MESH, CURVE, EMPTY = "MESH", "CURVE", "EMPTY"
ADAPTIVE = 12  # Blender's default curve resolution, for a shape 3ds Max interpolates adaptively
UV_FIRST = "UVMap"
UV_NAME = "UVChannel_%d"
MAX_EDGE_MASKS = 64  # distinct smoothing-group masks paired on one non-manifold edge
SHEAR_TOLERANCE = 1e-5  # |cos| between two rows of a local matrix

ChunkError = chunks.ChunkError


class NodeDescription:
    """One node: index is its object index, parent the parent's (None at the top level); kind MESH, CURVE or EMPTY;
    mesh the key into SceneDescription.meshes, curve the key into SceneDescription.curves (None when not one); class_name the base object's class ("" without
    one); modifiers the class names of its modifier stack, top first; layer the layer's object index (None without
    one); hidden, frozen, renderable, group_head and group_member the node's own flags; sheared whether matrix has
    shear (see sheared())."""
    __slots__ = ("index", "name", "parent", "matrix", "world", "kind", "mesh", "class_name", "mirrored",
                 "modifiers", "layer", "hidden", "frozen", "renderable", "group_head", "group_member", "sheared",
                 "curve")

    def __init__(self, index, name, parent, matrix, world, kind, mesh, class_name, mirrored, modifiers, layer=None,
                 hidden=False, frozen=False, renderable=True, group_head=False, group_member=False, sheared=False,
                 curve=None):
        self.index, self.name, self.parent, self.matrix, self.world = index, name, parent, matrix, world
        self.kind, self.mesh, self.class_name, self.mirrored, self.modifiers = kind, mesh, class_name, mirrored, \
            modifiers
        self.layer, self.hidden, self.frozen, self.renderable = layer, hidden, frozen, renderable
        self.group_head, self.group_member, self.sheared = group_head, group_member, sheared
        self.curve = curve

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


class SplineDescription:
    """One Bezier spline in meters: points, left and right handles, each [(x, y, z)] (Blender's handle_left is Max's
    in vector, handle_right its out vector), cyclic for a closed spline."""
    __slots__ = ("points", "left", "right", "cyclic")

    def __init__(self, points, left, right, cyclic):
        self.points, self.left, self.right, self.cyclic = points, left, right, cyclic

    def __repr__(self):
        return "SplineDescription(%d points%s)" % (len(self.points), ", cyclic" if self.cyclic else "")


class CurveDescription:
    """One curve in meters, offset baked: splines [SplineDescription]; resolution the Bezier resolution (segments
    per Bezier segment); bevel_depth the bevel's radius (0: no bevel), bevel_resolution its round profile's
    resolution; users the object indices of the nodes that share it, in walk order."""
    __slots__ = ("key", "name", "splines", "resolution", "bevel_depth", "bevel_resolution", "users")

    def __init__(self, key, name, splines, resolution, bevel_depth=0.0, bevel_resolution=0):
        self.key, self.name, self.splines, self.resolution = key, name, splines, resolution
        self.bevel_depth, self.bevel_resolution = bevel_depth, bevel_resolution
        self.users = []

    def __repr__(self):
        return "CurveDescription(%r, %d splines)" % (self.name, len(self.splines))


class LayerDescription:
    """One layer: index its object index, parent the parent layer's (None at the top level)."""
    __slots__ = ("index", "name", "parent", "hidden", "frozen", "renderable")

    def __init__(self, index, name, parent=None, hidden=False, frozen=False, renderable=True):
        self.index, self.name, self.parent = index, name, parent
        self.hidden, self.frozen, self.renderable = hidden, frozen, renderable

    def __repr__(self):
        return "LayerDescription(%d, %r, parent=%r)" % (self.index, self.name, self.parent)


class SceneDescription:
    """nodes in walk order, meshes {key: MeshDescription} and curves {key: CurveDescription} in order of first use,
    meters per file unit, unit the reader's SystemUnit (None when the file does not say), layers, placeholders,
    unknown_controllers and issues."""
    __slots__ = ("nodes", "meshes", "curves", "meters", "unit", "layers", "placeholders", "unknown_controllers",
                 "issues")

    def __init__(self, meters, unit=None):
        self.nodes, self.meshes, self.meters, self.unit, self.layers = [], {}, meters, unit, []
        self.curves = {}
        self.placeholders = collections.Counter()
        self.unknown_controllers = collections.Counter()
        self.issues = []

    def __repr__(self):
        return "SceneDescription(%d nodes, %d meshes, %d curves, %d placeholders, %g m per unit)" % (
            len(self.nodes), len(self.meshes), len(self.curves), sum(self.placeholders.values()), self.meters)


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


def _straight(knots, closed):
    """(left, right) handle lists of reader knots, those of each straight segment (segment type line) moved to a
    third and two thirds of its chord."""
    left = [k.in_vec for k in knots]
    right = [k.out_vec for k in knots]
    n = len(knots)
    for k, knot in enumerate(knots):
        if knot.segment != shapes.LINE or n < 2 or (k == n - 1 and not closed):
            continue
        a, b = knot.point, knots[(k + 1) % n].point
        right[k] = tuple(x + (y - x) / 3.0 for x, y in zip(a, b))
        left[(k + 1) % n] = tuple(x + (y - x) * 2.0 / 3.0 for x, y in zip(a, b))
    return left, right


def curve_description(key, name, shape, offset, meters):
    """(a CurveDescription of a reader Shape, issues): straight segments as straight handles, the offset (a reader
    matrix) applied, then meters; issues name what is drawn otherwise."""
    issues = list(shape.issues)

    def place(p):
        if offset is not None:
            p = tuple(p[0] * offset[0][c] + p[1] * offset[1][c] + p[2] * offset[2][c] + offset[3][c]
                      for c in range(3))
        return tuple(x * meters for x in p)

    splines = []
    for sp in shape.splines:
        if not sp.knots:
            continue
        left, right = _straight(sp.knots, sp.closed)
        splines.append(SplineDescription([place(k.point) for k in sp.knots], [place(p) for p in left],
                                         [place(p) for p in right], sp.closed))
    resolution = ADAPTIVE if shape.adaptive else shape.steps + 1
    depth, profile = 0.0, 0
    r = shape.render
    if r.renderable and r.thickness > 0:
        if r.rectangular:
            issues.append("a rectangular section (%g x %g) is drawn round, %g across" % (r.width, r.length,
                                                                                        r.thickness))
        depth = r.thickness / 2.0 * meters
        profile = max(0, (r.sides - 4) // 2)  # Blender's round profile has 4 + 2 * resolution sides
    return CurveDescription(key, name, splines, resolution, depth, profile), issues


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
    found = {}  # node -> (reader Node, Stack or None), or the ChunkError its record or object stack raised
    shape_of = {}  # base object index -> reader Shape, or None when the reader refused it
    remaining = collections.Counter()  # base object -> nodes still to build: its MeshData goes with the last
    for i in order:
        try:
            node = scene.node(i)
            stack = scene.object_stack(node.object) if node.object is not None else None
            found[i] = (node, stack)
            if stack is not None and stack.base is not None:
                remaining[stack.base] += 1
        except ChunkError as exc:
            found[i] = exc
    data_of = {}  # base object index -> MeshData, or None when the reader refused or does not read it
    layers = {}  # layer object index -> reader Layer, or None when its record cannot be read
    for i in order:
        local, world = t.local(i), t.world(i)
        kind, key, class_name, modifiers, name, node, layer, base = EMPTY, None, "", (), "", None, None, None
        curve = None
        if isinstance(found[i], ChunkError):  # a damaged node record or object stack: an empty, children placed
            desc.issues.append((i, "node: %s" % found[i]))
        else:
            node, stack = found[i]
            name = node.name
            layer = _layer(scene, node.layer, layers, desc.issues, i)
            base = stack.base if stack is not None else None
            if stack is not None:
                modifiers = tuple(_class_name(scene, m) for m in stack.modifiers)
            if base is not None and shapes.is_shape(scene, base):
                class_name = _class_name(scene, base)
                kind, curve = _curve(scene, desc, shape_of, base, i, name, t.offset(i), meters)
                remaining[base] -= 1
            elif base is not None:
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
        if kind == EMPTY and not (base is not None and scene.is_a(base, classids.SC_HELPER, classids.DUMMY)):
            desc.placeholders[class_name] += 1
        flags = {} if node is None else dict(hidden=node.hidden, frozen=node.frozen, renderable=node.renderable,
                                             group_head=node.group_head, group_member=node.group_member)
        desc.nodes.append(NodeDescription(i, name, scene.parent(i), blender_matrix(local, meters),
                                          blender_matrix(world, meters), kind, key, class_name,
                                          determinant3(world) < 0, modifiers, layer, sheared=sheared(local),
                                          curve=curve, **flags))
    desc.issues.extend((issue.node, "transform: %s" % issue.reason) for issue in t.issues)
    desc.unknown_controllers.update(
        _class_name(scene, issue.controller) if issue.controller is not None else ""
        for issue in t.issues if issue.reason == controllers.UNKNOWN_CLASS)
    desc.layers = _layer_descriptions(scene, layers)
    return desc


def _curve(scene, desc, shape_of, base, node, name, offset, meters):
    """(kind, curve key) of a node whose base object is a shape: CURVE and its key in desc.curves, made on first
    use; EMPTY and None when the reader refuses the shape (an issue). shape_of caches the reader's Shapes."""
    if base not in shape_of:
        try:
            shape_of[base] = shapes.read_shape(scene, base)
        except shapes.ShapeError as exc:
            shape_of[base] = None
            desc.issues.append((node, "shape: %s" % exc))
    sh = shape_of[base]
    if sh is None:
        return EMPTY, None
    offset = None if offset == controllers.IDENTITY else offset
    key = (base, offset)
    cd = desc.curves.get(key)
    if cd is None:
        cd, issues = curve_description(key, name, sh, offset, meters)
        desc.curves[key] = cd
        desc.issues.extend((node, "shape: %s" % x) for x in issues)
    cd.users.append(node)
    return CURVE, key


def _layer(scene, i, layers, issues, node):
    """The object index of node's layer i, or None (no layer, or a record that cannot be read: an issue, once per
    node); layers caches the reader records."""
    if i is None:
        return None
    if i not in layers:
        try:
            layers[i] = scene.layer(i)
        except ChunkError as exc:
            layers[i] = exc
    if isinstance(layers[i], ChunkError):
        issues.append((node, "layer: %s" % layers[i]))
        return None
    return i


def _layer_descriptions(scene, used):
    """The layers that hold a node and their parent layers, in the Layer Manager's order, every parent first."""
    records = {i: la for i, la in used.items() if not isinstance(la, ChunkError)}
    wanted = set()
    for la in list(records.values()):
        seen = set()
        while la is not None and la.index not in seen:  # parents are cycle-free; seen only bounds the walk
            seen.add(la.index)
            wanted.add(la.index)
            if la.parent is None:
                break
            try:
                la = records[la.parent] if la.parent in records else scene.layer(la.parent)
            except ChunkError:
                break
            records[la.index] = la
    out, done = [], set()
    for i in scene.layer_order():
        if i not in wanted or i in done:
            continue
        chain, j = [], i
        while j is not None and j in wanted and j not in done:
            chain.append(j)
            done.add(j)
            j = records[j].parent
        for j in reversed(chain):
            la = records[j]
            parent = la.parent if la.parent in wanted else None
            out.append(LayerDescription(j, la.name, parent, la.hidden, la.frozen, la.renderable))
    return out


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
