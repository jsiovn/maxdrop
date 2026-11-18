# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scene description: every node of a .max file with its transform and mesh, in meters, ready for build/.

    desc = read(path)                   # the file's own system unit; read(path, meters=0.01) overrides it
    desc.nodes                          # NodeDescription per node, pre-order: a parent before its children
    desc.meshes[node.mesh]              # MeshDescription, shared by the nodes of one base object
    desc.curves[node.curve]             # CurveDescription of a shape node, shared the same way
    desc.lights[node.light]             # convert.lights LightDescription of a LIGHT node, shared the same way
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

A standard primitive (Box, Plane, Pyramid, Sphere, GeoSphere, Cylinder, Cone, Tube, Torus) becomes the mesh 3ds Max
builds from its parameters (convert.primitives) and from there on is a mesh like any other; one with an option that is
not built (Slice, a hemisphere) is a placeholder (an issue).

A node becomes an EMPTY placeholder when its base object is not an Editable Mesh, Editable Poly, a primitive built
here or a shape read here, when it has no object, or when the reader refuses its geometry or its record; placeholders
counts them by the class name of the file's class directory ("" when there is none). A Dummy helper (a group head is
one) and a Target (the node a target camera or light aims at) are EMPTYs too, but that is their conversion, not a
placeholder. A group head keeps its members as children: that is how 3ds Max stores a group.

A light becomes a LIGHT (convert.lights): a VRayLight's plane and disc an area light, its sphere a point light; a
standard Omni, Spot and Direct a point, spot and sun light; a photometric light a point, spot or area light by its
distribution; a VRaySun a sun; a VRayIES a spot. It is keyed by its base object index and the factor the node's
world scale puts on its area (lights.area_scale, 1 but for a VRayLight), so instances of one scale share it; the
issues of its parameters are named on its first node, those of a description on the first node of that key. A
VRayLight's mesh or dome light or a Skylight (not built yet), or a light whose parameters cannot be read, is an EMPTY
with the reason as an issue, on every node, not counted as a placeholder. A VRaySky as the environment map is an
issue on its own object index. describe(..., assets) takes the scene's reader.assets.AssetTable for the names of the
web and IES files (read() reads it).

Look At: the matrices of a node aimed by a Look At controller or a LookAt Constraint are the ones 3ds Max computes
at frame 0 (reader.controllers), baked. A node with a Look At controller aimed at a node also gets node.look_at, a
LookAtDescription: the Track To constraint that keeps it aimed in Blender (built only on request, build.objects),
or why none can (a roll, the Y axis: Track To has no roll and no downward up axis).
Modifiers are listed, not evaluated: the base mesh is built, but for an Extrude on a shape and UVW Maps, and the
modifiers converted to Blender modifiers.

Extrude: a shape whose lowest modifier that renders is an Extrude becomes a MESH (convert.extrude), keyed (base
object index, offset, Extrude modifier index), its offset baked like any mesh's; node.applied names the Extrude and
node.modifiers the rest of the stack, which is not evaluated. A shape with another modifier below its Extrude, or
whose Extrude cannot be evaluated, stays a curve (an issue).

UVW Map: the UVW Maps that render and sit right above the base mesh, or right above an applied Extrude, are evaluated
into their map channel (convert.uvwmap), bottom first; each applied one adds (modifier index, its context matrix)
to the mesh key and its name to node.applied. A UVW Map of a type evaluated nowhere here (shrink-wrap, face, XYZ to
UVW), one writing the vertex color channel (no UV layer) or whose parameters cannot be read keeps the stored channel
and stays in node.modifiers (an issue); so does one above any other modifier, which is not evaluated.

Blender modifiers: right above what is evaluated here (the base mesh, an applied Extrude, the UVW Maps above them;
one left unapplied changes no geometry), the run of TurboSmooth, MeshSmooth, Shell and Symmetry that render becomes
node.converted (convert.modifiers ModifierDescriptions, bottom first), built as Subdivision Surface, Solidify and
Mirror; the first other modifier, or one the rules refuse, ends the run, and each of the four above it is an issue.
The lowest converted smoother that changes the shading sets the mesh's, which adds ("shading", SMOOTH or CREASE) to the mesh key: SMOOTH
leaves no sharp edge or flat face, CREASE keeps them and sets md.creases. Viewport levels that would give an
object more than convert.modifiers.MAX_VIEWPORT_CORNERS face corners are lowered (an issue).
describe(..., convert_modifiers=False) converts nothing.

Layers: each node names its layer's object index (None without one, or when the layer record cannot be read, which
is an issue); desc.layers holds the layers that hold a node and their parent layers, in the Layer Manager's order
with every parent before its children. A node's hidden, frozen and renderable flags are its own: a hidden layer
hides its nodes in 3ds Max without setting their flag, so build/ applies the layer's flags to its collection.

A local matrix with shear (a scale along a rotated axis) sets node.sheared: Blender's matrix_basis cannot hold
it, so build/ puts the rest into matrix_parent_inverse. A base object's reader arrays (an extruded shape's too) are
dropped once its last node is described. Once the primitives and extrusions made so far have MAX_BUILT_CORNERS face
corners, the next primitive is a placeholder and the next extruded shape a curve (an issue each).
Nothing here imports bpy; numpy is imported when a scene is described.
"""
import collections
import math

from ..reader import assets as reader_assets
from ..reader import cfb, chunks, classids, controllers, geometry, modifiers as reader_modifiers, shapes, units
from ..reader import scene as reader_scene
from . import colors, extrude, lights, modifiers as rules, primitives, uvwmap

MESH, CURVE, EMPTY, LIGHT = "MESH", "CURVE", "EMPTY", "LIGHT"
ADAPTIVE = 12  # Blender's default curve resolution, for a shape 3ds Max interpolates adaptively
UV_FIRST = "UVMap"
UV_NAME = "UVChannel_%d"
MAX_EDGE_MASKS = 64  # distinct smoothing-group masks paired on one non-manifold edge
# Face corners the primitives and extrusions of one scene may make: each has its own cap (primitives.MAX_CORNERS,
# extrude.MAX_VERTICES), but a file can hold any number of them, each costing seconds and hundreds of MB. Checked
# before each is made, so the last one made can pass it by up to its own cap.
MAX_BUILT_CORNERS = 1 << 24
_SPENT = "the primitives and extrusions before it reach %d face corners, the budget for one scene"
SHEAR_TOLERANCE = 1e-5  # |cos| between two rows of a local matrix

ChunkError = chunks.ChunkError


class NodeDescription:
    """One node: index is its object index, parent the parent's (None at the top level); kind MESH, CURVE, LIGHT or
    EMPTY; mesh the key into SceneDescription.meshes, curve the key into SceneDescription.curves, light the key into
    SceneDescription.lights (None when not one);
    class_name the base object's class ("" without one); modifiers the class names of its modifier stack not applied,
    top first, applied those evaluated into its mesh (an Extrude); layer the layer's object index (None without
    one); hidden, frozen, renderable, group_head and group_member the node's own flags; sheared whether matrix has
    shear (see sheared()); converted the modifiers that become Blender modifiers (convert.modifiers
    ModifierDescriptions, bottom first); look_at the LookAtDescription of a Look At controller aimed at a node, else
    None."""
    __slots__ = ("index", "name", "parent", "matrix", "world", "kind", "mesh", "class_name", "mirrored",
                 "modifiers", "layer", "hidden", "frozen", "renderable", "group_head", "group_member", "sheared",
                 "curve", "applied", "converted", "look_at", "light")

    def __init__(self, index, name, parent, matrix, world, kind, mesh, class_name, mirrored, modifiers, layer=None,
                 hidden=False, frozen=False, renderable=True, group_head=False, group_member=False, sheared=False,
                 curve=None, applied=(), converted=(), look_at=None, light=None):
        self.index, self.name, self.parent, self.matrix, self.world = index, name, parent, matrix, world
        self.kind, self.mesh, self.class_name, self.mirrored, self.modifiers = kind, mesh, class_name, mirrored, \
            modifiers
        self.layer, self.hidden, self.frozen, self.renderable = layer, hidden, frozen, renderable
        self.group_head, self.group_member, self.sheared = group_head, group_member, sheared
        self.curve, self.applied, self.converted, self.look_at = curve, applied, converted, look_at
        self.light = light

    def __repr__(self):
        return "NodeDescription(%d, %r, %s, parent=%r)" % (self.index, self.name, self.kind, self.parent)


class LookAtDescription(collections.namedtuple("LookAtDescription", "target track up target_z reason")):
    """How a node's Look At controller aims it, as a Blender Track To: target the target node's object index; track
    and up Blender's track_axis and up_axis, target_z its use_target_z (the target's Z is up). track and up are None
    when no Track To gives 3ds Max's frame, and reason says why."""
    __slots__ = ()


# Look At axis -> Track To axis that looks (unflipped: -axis looks at the target). The up axis is Y for X and Z;
# for Y it is -Z, which Track To cannot take.
_TRACK = {(0, False): "TRACK_NEGATIVE_X", (0, True): "TRACK_X", (2, False): "TRACK_NEGATIVE_Z", (2, True): "TRACK_Z"}
NO_TRACK_ROLL = "a roll, which Track To cannot hold"
NO_TRACK_AXIS = "aimed along Y with -Z up, which Track To cannot hold"


def look_at_description(look):
    """The LookAtDescription of a reader.controllers.LookAt aimed at a node; None without a target node."""
    if look is None or look.target is None:
        return None
    if look.axis == 1:
        return LookAtDescription(look.target, None, None, look.target_up, NO_TRACK_AXIS)
    if look.roll:
        return LookAtDescription(look.target, None, None, look.target_up, NO_TRACK_ROLL)
    return LookAtDescription(look.target, _TRACK[(look.axis, look.flip)], "UP_Y", look.target_up, None)


class MeshDescription:
    """One mesh in meters, offset baked: positions float32 (N, 3); loop_vertices int32 (L,); loop_starts and
    loop_totals int32 (F,); material_indices int32 (F,), zero-based; sharp_faces bool (F,); sharp_edges int32
    (E, 2), sorted vertex pairs; uv_layers [(name, float32 (L, 2))]; users the object indices of the nodes that
    share it, in walk order; dropped_faces the faces left out (a repeated vertex, doubled); applied the UVW Maps
    (reader.modifiers Modifiers) evaluated into it; creases whether its sharp edges are to be creased (a converted
    smoother separates by smoothing groups)."""
    __slots__ = ("key", "name", "positions", "loop_vertices", "loop_starts", "loop_totals", "material_indices",
                 "sharp_faces", "sharp_edges", "uv_layers", "users", "dropped_faces", "applied", "creases")

    def __init__(self, key, name, positions, loop_vertices, loop_starts, loop_totals, material_indices,
                 sharp_faces, sharp_edges, uv_layers, dropped_faces=0):
        self.key, self.name, self.positions = key, name, positions
        self.loop_vertices, self.loop_starts, self.loop_totals = loop_vertices, loop_starts, loop_totals
        self.material_indices, self.sharp_faces, self.sharp_edges = material_indices, sharp_faces, sharp_edges
        self.uv_layers, self.dropped_faces = uv_layers, dropped_faces
        self.users = []
        self.applied = ()
        self.creases = False

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
    """nodes in walk order, meshes {key: MeshDescription}, curves {key: CurveDescription} and lights {key:
    convert.lights.LightDescription} in order of first use, meters per file unit, unit the reader's SystemUnit
    (None when the file does not say), layers, placeholders, unknown_controllers and issues."""
    __slots__ = ("nodes", "meshes", "curves", "lights", "meters", "unit", "layers", "placeholders",
                 "unknown_controllers", "issues")

    def __init__(self, meters, unit=None):
        self.nodes, self.meshes, self.meters, self.unit, self.layers = [], {}, meters, unit, []
        self.curves, self.lights = {}, {}
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
    matrix) applied, then meters; issues name what this drawing changes (the reader's own are the Shape's)."""
    issues = []

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


def describe(scene, meters=1.0, unit=None, convert_modifiers=True, assets=None):
    """The SceneDescription of a reader.scene.Scene; meters is the length of one file unit; convert_modifiers False
    leaves the modifiers Blender has an equivalent for in node.modifiers, unconverted and unreported; assets, the
    scene's reader.assets.AssetTable, names the files of web and IES lights (None: not named)."""
    if not (math.isfinite(meters) and meters > 0):
        raise ValueError("meters per unit must be a positive number, not %r" % (meters,))
    t = controllers.Transforms(scene)
    stacks = reader_modifiers.Modifiers(scene)
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
    extruded = {}  # base object index -> {Extrude modifier index: MeshData, or None when it cannot be evaluated}
    built = [0]  # face corners the primitives and extrusions made so far
    mapped = {}  # UVW Map modifier index -> (Params, gizmo matrix), or None when it is not evaluated
    told = set()  # modifier indices whose conversion issues were named (on the first node only)
    layers = {}  # layer object index -> reader Layer, or None when its record cannot be read
    unlit = {}  # light base object index -> why it is not built
    light_params = {}  # light base object index -> its values (convert.lights.read_params)
    swatches = None  # the scene's swatch rule, read for the first light
    for i in order:
        local, world = t.local(i), t.world(i)
        kind, key, class_name, modifiers, name, node, layer, base = EMPTY, None, "", (), "", None, None, None
        curve, applied, converted, light = None, (), (), None
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
                ext, maps, rest = _evaluated(scene, stacks, node, desc.issues, i, True) if stack.modifiers else \
                    (None, (), ())
                if ext is not None:
                    fresh = {m.index for m in rest} - told  # named on this node only if its Extrude is made
                    conv, conv_issues = _converted(scene, rest, meters, _offset(t, i), told, convert_modifiers)
                    key, done = _extruded(scene, desc, shape_of, extruded, mapped, base, ext, maps, i, name,
                                          t.offset(i), meters, built, _shading(conv))
                    if key is None:
                        told.difference_update(fresh)
                if key is not None:
                    kind = MESH
                    converted, more = rules.budget(conv, len(desc.meshes[key].loop_vertices))
                    desc.issues.extend((i, x) for x in conv_issues + more)
                    applied, modifiers = _split(scene, stack.modifiers, (ext,) + done, conv)
                else:
                    kind, curve = _curve(scene, desc, shape_of, base, i, name, t.offset(i), meters)
                remaining[base] -= 1
                if not remaining[base]:
                    extruded.pop(base, None)
            elif base is not None and lights.light_class(scene, base) is not None:
                class_name = _class_name(scene, base)
                if swatches is None:
                    swatches = colors.of_scene(scene)
                light = _light(scene, desc, unlit, light_params, base, i, name, meters, swatches, world, assets)
                kind = LIGHT if light is not None else EMPTY
            elif base is not None:
                class_name = _class_name(scene, base)
                if base not in data_of:
                    try:
                        data_of[base] = geometry.read_mesh(scene, base)
                    except geometry.GeometryError as exc:
                        data_of[base] = None
                        desc.issues.append((i, "geometry: %s" % exc))
                    else:
                        if data_of[base] is None and primitives.is_primitive(scene, base):
                            data_of[base] = _primitive(scene, base, desc.issues, i, built)
                data = data_of[base]
                if data is not None:
                    _ext, maps, rest = _evaluated(scene, stacks, node, desc.issues, i, False) if stack.modifiers \
                        else (None, (), ())
                    offset = _offset(t, i)
                    converted, conv_issues = _converted(scene, rest, meters, offset, told, convert_modifiers)
                    desc.issues.extend((i, x) for x in conv_issues)
                    key, done = _mapped_mesh(scene, desc, mapped, (base, offset), data, maps, i, name, offset,
                                             meters, _shading(converted))
                    converted, more = rules.budget(converted, len(desc.meshes[key].loop_vertices))
                    desc.issues.extend((i, x) for x in more)
                    if done or converted:
                        applied, modifiers = _split(scene, stack.modifiers, done, converted)
                    kind = MESH
                remaining[base] -= 1
                if not remaining[base]:
                    del data_of[base]
        if kind == EMPTY and not (base is not None and (scene.is_a(base, classids.SC_HELPER, classids.DUMMY) or
                                                        scene.is_a(base, classids.SC_GEOMOBJECT,
                                                                   classids.TARGET_OBJECT) or base in unlit)):
            desc.placeholders[class_name] += 1
        flags = {} if node is None else dict(hidden=node.hidden, frozen=node.frozen, renderable=node.renderable,
                                             group_head=node.group_head, group_member=node.group_member)
        desc.nodes.append(NodeDescription(i, name, scene.parent(i), blender_matrix(local, meters),
                                          blender_matrix(world, meters), kind, key, class_name,
                                          determinant3(world) < 0, modifiers, layer, sheared=sheared(local),
                                          curve=curve, applied=applied, converted=converted,
                                          look_at=look_at_description(t.look_at(i)), light=light, **flags))
    sky = lights.environment_sky(scene)
    if sky is not None:
        desc.issues.append((sky, "light: %s" % lights.SKY))
    desc.issues.extend((issue.node, "transform: %s" % issue.reason) for issue in t.issues)
    desc.unknown_controllers.update(
        _class_name(scene, issue.controller) if issue.controller is not None else ""
        for issue in t.issues if issue.reason == controllers.UNKNOWN_CLASS)
    desc.layers = _layer_descriptions(scene, layers)
    return desc


def _light(scene, desc, unlit, params, base, node, name, meters, swatches, world, assets=None):
    """The key in desc.lights of light base on node (world: its reader world matrix), made on first use; None when it
    is not built (unlit caches the reason, an issue on every node). params caches the light's values, whose issues
    are named on the first node; a description's on the first node of its key."""
    if base not in params and base not in unlit:
        try:
            values, issues = lights.read_params(scene, base, assets)
            reason = lights.not_built(values)
        except ChunkError as exc:
            values, issues, reason = None, [], "parameters cannot be read: %s" % exc
        desc.issues.extend((node, "light: %s" % x) for x in issues)
        if reason is None:
            params[base] = values
        else:
            unlit[base] = reason
    if base in unlit:
        desc.issues.append((node, "light: not built: %s" % unlit[base]))
        return None
    scale = lights.area_scale(params[base], world)
    key = (base, scale)
    if key not in desc.lights:
        ld, issues = lights.describe(key, name, params[base], meters, swatches, scale)
        desc.lights[key] = ld
        desc.issues.extend((node, "light: %s" % x) for x in issues)
    desc.lights[key].users.append(node)
    return key


def _primitive(scene, base, issues, node, built):
    """The MeshData convert.primitives builds for primitive base, or None when it is not built (an issue); its
    issues are named on the first node only (the caller caches the result). built: [face corners made so far]."""
    if built[0] >= MAX_BUILT_CORNERS:
        issues.append((node, "primitive: not built: " + _SPENT % MAX_BUILT_CORNERS))
        return None
    try:
        data, more = primitives.mesh(scene, base)
    except ChunkError as exc:  # PrimitiveError, or a block the reader refuses
        issues.append((node, "primitive: %s" % exc))
        return None
    except (ArithmeticError, ValueError) as exc:  # a formula the sizes break costs the object, not the import
        issues.append((node, "primitive: not built: %s" % exc))
        return None
    built[0] += len(data.loop_vertices)
    issues.extend((node, "primitive: %s" % x) for x in more)
    return data


def _shape(scene, desc, shape_of, base, node):
    """The reader Shape of base, read once (shape_of caches it, None when refused); its issues, or the refusal,
    are named on the first node only."""
    if base not in shape_of:
        try:
            shape_of[base] = shapes.read_shape(scene, base)
            desc.issues.extend((node, "shape: %s" % x) for x in shape_of[base].issues)
        except shapes.ShapeError as exc:
            shape_of[base] = None
            desc.issues.append((node, "shape: %s" % exc))
    return shape_of[base]


def _curve(scene, desc, shape_of, base, node, name, offset, meters):
    """(kind, curve key) of a node whose base object is a shape: CURVE and its key in desc.curves, made on first
    use; EMPTY and None when the reader refuses the shape (an issue). shape_of caches the reader's Shapes (small:
    knots, no arrays), whose issues are named once, on the first node."""
    sh = _shape(scene, desc, shape_of, base, node)
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


def _evaluated(scene, stacks, node, issues, i, shape):
    """(Extrude, UVW Maps, rest): the bottom run of node i's modifiers that render and are evaluated here
    (reader.modifiers Modifiers, bottom first), and the modifiers that render above it. On a shape the run starts
    with an Extrude (None without one: no UVW Map either, no rest); an Extrude or a UVW Map above another modifier
    is an issue."""
    try:
        st = stacks.object_stack(node.object)
    except ChunkError as exc:
        issues.append((i, "modifiers: the modifier stack cannot be read: %s" % exc))
        return None, (), ()
    active = [m for m in st.modifiers if m.renders]  # bottom first
    ext, start = None, 0
    if shape:
        if not (active and extrude.is_extrude(active[0])):
            if any(extrude.is_extrude(m) for m in active):
                issues.append((i, "extrude: an Extrude above %s is not evaluated: the shape is a curve" %
                               (_class_name(scene, active[0].index) or "another modifier")))
            return None, (), ()
        ext, start = active[0], 1
    maps = []
    for m in active[start:]:
        if not uvwmap.is_uvwmap(m):
            break
        maps.append(m)
    rest = active[start + len(maps):]
    if any(uvwmap.is_uvwmap(m) for m in rest):
        issues.append((i, "uvw map: a UVW Map above %s is not evaluated" %
                       (_class_name(scene, rest[0].index) or "another modifier")))
    return ext, tuple(maps), tuple(rest)


def _offset(t, i):
    """Node i's object offset (a reader matrix), None for the identity."""
    offset = t.offset(i)
    return None if offset == controllers.IDENTITY else offset


def _converted(scene, rest, meters, offset, told, convert):
    """(ModifierDescriptions, issues): the bottom run of rest (the modifiers that render above those evaluated,
    bottom first) that convert.modifiers turns into Blender modifiers. The first other modifier, or one the rules
    refuse, ends the run; each convertible modifier above it is an issue. A UVW Map left unapplied is not in rest
    (it changes no geometry). The rules' own issues are named once per modifier (told). convert False: nothing."""
    out, issues, stop = [], [], None
    if not convert:
        return (), []
    for m in rest:
        cls = _class_name(scene, m.index) or "another modifier"
        if stop is not None:
            if rules.is_convertible(m):
                issues.append("modifiers: %s above %s is not converted" % (cls, stop))
            continue
        if not rules.is_convertible(m):
            stop = cls
            continue
        first = m.index not in told
        told.add(m.index)
        try:
            md, more = rules.convert(scene, m, meters, offset)
        except rules.ModifierError as exc:
            issues.append("modifiers: %s not converted: %s" % (cls, exc))
            stop = cls
            continue
        out.append(md)
        if first:
            issues.extend("modifiers: %s: %s" % (cls, x) for x in more)
    return tuple(out), issues


def _shading(converted):
    """What the lowest converted smoother that changes the shading does to it: convert.modifiers SMOOTH, CREASE or
    None."""
    return next((m.shading for m in converted if m.kind == rules.SUBSURF and m.shading), None)


def _split(scene, stack_modifiers, done, converted=()):
    """(applied, rest): the class names of the modifiers done (reader Modifiers, bottom first) and of the rest of the
    stack (object indices, top first) without them and without those converted (ModifierDescriptions)."""
    rest = list(stack_modifiers)
    for m in tuple(done) + tuple(converted):
        if m.index in rest:
            rest.remove(m.index)
    return tuple(_class_name(scene, m.index) for m in done), tuple(_class_name(scene, m) for m in rest)


def _mapping(scene, mapped, m, issues, node):
    """(Params, gizmo matrix) of UVW Map m, read once (mapped caches it; None when it is not evaluated: an issue on
    the first node only)."""
    if m.index not in mapped:
        mapped[m.index] = None
        try:
            params, more = uvwmap.read_params(scene, m)
            if not params.supported:
                issues.append((node, "uvw map: %s mapping is not evaluated: the stored channel stays" %
                               params.type_name))
            elif params.vertex_color:  # channel 0 is no UV layer: applying it would change nothing in Blender
                issues.append((node, "uvw map: the vertex color channel is not imported: not applied"))
            else:
                tm, gizmo_issues = uvwmap.gizmo(scene, m)
                mapped[m.index] = (params, tm)
                more = more + gizmo_issues
            issues.extend((node, "uvw map: %s" % x) for x in more)
        except uvwmap.UVWMapError as exc:
            issues.append((node, "uvw map: %s: the stored channel stays" % exc))
    return mapped[m.index]


def _mapped_mesh(scene, desc, mapped, key, data, maps, node, name, offset, meters, shading=None):
    """(the key in desc.meshes of reader MeshData data under the UVW Maps maps, the maps applied), made on first use:
    key extended by (modifier index, context matrix) per UVW Map evaluated, then by ("shading", shading) when a
    converted smoother changes the shading (SMOOTH: no sharp edge or flat face; CREASE: the sharp edges creased)."""
    usable = []
    for m in maps:
        found = _mapping(scene, mapped, m, desc.issues, node)
        if found is None:
            continue
        if m.context is None:
            desc.issues.append((node, "uvw map: no modifier context: the stored channel stays"))
            continue
        usable.append((m, found))
    key = key + tuple((m.index, m.context.tm) for m, _found in usable)
    if shading is not None:
        key = key + (("shading", shading),)
    md = desc.meshes.get(key)
    if md is None:
        done = []
        for m, (params, tm) in usable:
            try:
                data = uvwmap.apply(data, params, tm, m.context.tm)
                done.append(m)
            except uvwmap.UVWMapError as exc:
                desc.issues.append((node, "uvw map: %s: the stored channel stays" % exc))
        md = desc.meshes[key] = mesh_description(key, name, data, offset, meters)
        md.applied = tuple(done)
        if shading == rules.SMOOTH:
            md.sharp_faces[:] = False
            md.sharp_edges = md.sharp_edges[:0]
        md.creases = shading == rules.CREASE
        if md.dropped_faces:
            desc.issues.append((node, "geometry: %d faces with a repeated vertex or doubled, left out"
                                % md.dropped_faces))
    md.users.append(node)
    return key, md.applied


def _extruded(scene, desc, shape_of, extruded, mapped, base, ext, maps, node, name, offset, meters, built,
              shading=None):
    """(the key in desc.meshes of shape base under the Extrude ext and the UVW Maps maps, the maps applied), made on
    first use; (None, ()) when the shape or the Extrude cannot be read or the scene's MAX_BUILT_CORNERS are spent (an
    issue, once per base object and Extrude). extruded caches the MeshData per base object, built counts the face
    corners made."""
    cache = extruded.setdefault(base, {})
    if ext.index not in cache:
        cache[ext.index] = None
        sh = _shape(scene, desc, shape_of, base, node)
        if sh is not None and built[0] >= MAX_BUILT_CORNERS:
            desc.issues.append((node, "extrude: not made: " + _SPENT % MAX_BUILT_CORNERS))
        elif sh is not None:
            try:
                params, issues = extrude.read_params(scene, ext)
                data, more = extrude.extrude(sh, params)
                cache[ext.index] = data
                built[0] += len(data.loop_vertices)
                desc.issues.extend((node, "extrude: %s" % x) for x in issues + more)
            except extrude.ExtrudeError as exc:
                desc.issues.append((node, "extrude: %s" % exc))
    data = cache[ext.index]
    if data is None:
        return None, ()
    offset = None if offset == controllers.IDENTITY else offset
    return _mapped_mesh(scene, desc, mapped, (base, offset, ext.index), data, maps, node, name, offset, meters,
                        shading)


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


def read(path, meters=None, convert_modifiers=True):
    """The SceneDescription of a .max file. meters None: the file's system unit, 1.0 when it does not say;
    convert_modifiers as describe's."""
    with cfb.CompoundFile(path) as cf:
        sc = reader_scene.Scene.from_file(cf)
        unit = units.system_unit(sc)
        if meters is None:
            meters = unit.meters if unit is not None else 1.0
        return describe(sc, meters, unit, convert_modifiers, reader_assets.AssetTable.from_file(cf))
