# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scene description: every node of a .max file with its transform and mesh, in meters, ready for build/.

    desc = read(path)                   # the file's own system unit; read(path, meters=0.01) overrides it
    desc.nodes                          # NodeDescription per node, pre-order: a parent before its children
    desc.meshes[node.mesh]              # MeshDescription, shared by the nodes of one base object
    desc.curves[node.curve]             # CurveDescription of a shape node, shared the same way
    desc.lights[node.light]             # convert.lights LightDescription of a LIGHT node, shared the same way
    desc.cameras[node.camera]           # convert.cameras CameraDescription of a CAMERA node, shared the same way
    desc.dome                           # convert.lights DomeDescription of the dome light that is the World, or None
    desc.camera                         # the node index of the scene camera, None without a camera
    desc.render                         # convert.cameras RenderSettings (render size), None when not stored
    desc.placeholders                   # Counter: class name -> nodes built as an empty
    desc.layers                         # LayerDescription per layer that holds a node, a parent before its children
    desc.unknown_controllers            # Counter: controller class name -> times met
    desc.issues                         # [(node object index, None for the whole scene or a scene-level label
                                        #   such as ENVIRONMENT, reason)] for the report
    describe(scene, meters, cancel=stop.is_set)   # Cancelled once cancel() holds: asked between two nodes and
                                                  #   inside a large mesh (reader.geometry.CHECK_EVERY)

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
Blender holds mesh positions in single precision: a mesh whose positions (offset and meters applied) are past the
largest float32, inf or NaN is an EMPTY placeholder (an issue, on the first node of its key), as a curve or a
primitive (an extruded shape is drawn as its curve); a mesh light's emitter is then not built. A U or V coordinate
that is not a number (inf, NaN) becomes 0 (an issue): stored UVs do not depend on the positions, so the mesh is
kept, as a UVW Map's refused UVs keep it.

A shape (reader.shapes: Line, Editable Spline, Rectangle, Circle, Ellipse, Arc, NGon) becomes a CURVE, keyed and
shared like a mesh, its offset baked into the knots: one Bezier spline per spline, Max's in and out vectors as the
left and right handles, each spline with its segments' material IDs (SplineDescription.material_ids: the first
one is the spline's, convert.materials gives it its slot). A segment 3ds Max draws straight (segment type line)
gets handles a third of the way along its chord, whatever the stored vectors.
Resolution: 3ds Max's steps + 1 segments per Bezier segment, ADAPTIVE for
an adaptive shape. A shape that renders (Enable In Renderer) gets a round bevel of its thickness (Max's thickness
is the diameter) with about as many sides, or with a rectangular section a section: the rectangle width x length
turned by its angle, which build.curves makes a bevel object of, capped at the ends of an open spline as 3ds Max
caps it (on the shapes_more fixture's line along X and loop, flat in XY, the corners land where 3ds Max's render
mesh has them; on a curve that is not flat an issue says the section may turn otherwise; a width or length of 0 is
not drawn, an issue). Blender holds curves in single precision: a curve whose points or handles (offset and meters
applied) are past the largest float32, inf or NaN (a hostile NGon radius near 1e308) is an EMPTY placeholder (an
issue, on the first node of its key), as a primitive whose sizes leave the float range; a section or a round bevel
that does not fit is not drawn (an issue).

A standard primitive (Box, Plane, Pyramid, Sphere, GeoSphere, Cylinder, Cone, Tube, Torus) becomes the mesh 3ds Max
builds from its parameters (convert.primitives) and from there on is a mesh like any other, Slice and hemispheres
included; one convert.primitives refuses (a PrimitiveError) is a placeholder (an issue).

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
VRayLight's mesh light is a MESH of its emitter (node.emitter, the key into desc.emitters of its
lights.EmitterDescription, one per light object): its mesh object's base mesh (the light's own, else the picked
node's object; an Editable Mesh, Editable Poly or primitive built here; a shape under an Extrude, extruded here) in
object space with the light node's offset baked, keyed (EMITTER, light base, mesh base, offset), the light's nodes
its users; its area (mesh_area, object space) sets the radiance in lm and W. The mesh object's modifiers that render
above it, but its UVW Maps (an emitter has no texture), are converted as a mesh node's (Blender modifiers in
node.converted, with the light node's offset; build.emitters spreads the radiance over the mesh under them); the
rest are an issue. A mesh light without such a
mesh, a Skylight (not built yet), or a light whose parameters cannot be read, is an EMPTY with the reason as an
issue, on every node, not counted as a placeholder. A VRayLight dome is an EMPTY too (its children
stay placed), not a placeholder: the first dome node that is on (in walk order) gives desc.dome
(lights.describe_dome), the World build/ makes; any other dome node, an instance of it too, and one that is off are
an issue each (Blender has one World). A VRaySky as the environment map is an issue labelled ENVIRONMENT.
describe(..., assets) takes the scene's reader.assets.AssetTable for the names of the web and IES files (read()
reads it); describe(..., files), a convert.textures.TextureIndex, finds the IES file of a VRayIES whose power depends
on it, read once per file (convert.ies.Lookup); without it the power is taken as the flux (an issue).

A camera (Free, Target, Physical, VRayPhysicalCamera) becomes a CAMERA (convert.cameras): the lens, sensor, shift,
clipping and orthographic width that frame what 3ds Max renders. It is keyed by its base object index and, when its
field of view or width depends on it, the distance to its target node (a targeted camera's), so instances share it;
the issues of its parameters are named on its first node, those of a description on the first node of that key. A
camera whose parameters cannot be read is an EMPTY with the reason as an issue, not counted as a placeholder; one with
an object offset keeps the node transform (an issue: 3ds Max looks from the object). desc.render holds the render
size (None, or a size of None, when not stored: the report says so; an issue when out of range) and desc.camera the
camera of the view 3ds Max renders (convert.cameras render_camera, with describe(..., views) the file's saved views;
read() reads them), else the first camera: desc.camera_note says why when that view looks through no camera (the
report's render line), an issue when the saved views cannot be read. Scene-level issues have the index None (the
report labels them "scene") or a label of their own (ENVIRONMENT), a string the report uses as it is.

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
leaves no sharp edge or flat face, CREASE keeps them and sets md.creases. A converted Shell gives its rim smoothing
groups of its own in 3ds Max, hard against both surfaces: unless a smoother with Smooth Result is above it, the
mesh's open edges join its sharp edges (after a SMOOTH smoother cleared them) and ("rim", True) the mesh key; with
Mirrors below the Shell, but the open edges a Mirror welds shut (both ends within its threshold of their copies: a
seam once welded), and the rim entry of the key holds those Mirrors; what Solidify still cannot do (auto smooth
splitting the rim's sharper corners, the override group) is an issue, named once per Shell and mesh, only when the
mesh has open edges. Viewport levels that would give an object more than convert.modifiers.MAX_VIEWPORT_CORNERS face
corners are lowered (an issue).
describe(..., convert_modifiers=False) converts nothing.

Layers: each node names its layer's object index (None without one, or when the layer record cannot be read, which
is an issue); desc.layers holds the layers that hold a node and their parent layers, in the Layer Manager's order
with every parent before its children. A node's hidden and frozen flags are its own: a hidden layer hides its
nodes in 3ds Max without setting their flag, so build/ applies the layer's flags to its collection. Renderable,
Cast Shadows and Receive Shadows are the ones 3ds Max renders with (reader.scene.render_flags): the node's own, or
its own layer's when Rendering Control is By Layer (a layer that does not render leaves its By Object nodes and
the layers below it rendering). Blender has no per-object Receive Shadows, so a mesh or curve node with it off is
an issue (NO_RECEIVE).

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
from . import cameras, colors, extrude, ies, lights, modifiers as rules, primitives, uvwmap

MESH, CURVE, EMPTY, LIGHT, CAMERA = "MESH", "CURVE", "EMPTY", "LIGHT", "CAMERA"
EMITTER = "emitter"  # an emitter mesh's key: (EMITTER, light base, mesh base object index, the light node's offset)
ADAPTIVE = 12  # Blender's default curve resolution, for a shape 3ds Max interpolates adaptively
UV_FIRST = "UVMap"
UV_NAME = "UVChannel_%d"
MAX_EDGE_MASKS = 64  # distinct smoothing-group masks paired on one non-manifold edge
# Face corners the primitives and extrusions of one scene may make: each has its own cap (primitives.MAX_CORNERS,
# extrude.MAX_VERTICES), but a file can hold any number of them, each costing up to about a second and hundreds of
# MB. Checked before each is made, so the last one made can pass it by up to its own cap.
MAX_BUILT_CORNERS = 1 << 24
# Face corners of a mesh with its copies under the Mirrors below a Shell, counted for the rim's corners (each Mirror
# doubles them): past it the corners are not counted (a line in the report)
MAX_MIRRORED_CORNERS = 1 << 22
MAX_MIRROR_IMAGES = 64  # copies of the open edges tested against the next Mirror below a Shell (_rim_edges)
_SPENT = "the primitives and extrusions before it reach %d face corners, the budget for one scene"
SHEAR_TOLERANCE = 1e-5  # |cos| between two rows of a local matrix
OFFSET = "its object is offset from its pivot: the camera looks from the pivot, 3ds Max from the object"
NO_RECEIVE = "shadows: Receive Shadows is off: Blender has no such switch per object, it receives shadows"
ENVIRONMENT = "environment"  # the label of an issue of the environment map (no node holds it)

ChunkError = chunks.ChunkError


class CurveError(ValueError):
    """A shape's curve cannot be built: its points or handles do not fit single precision (Blender's)."""


class MeshError(ValueError):
    """A mesh cannot be built: its positions (offset and meters applied) do not fit single precision (Blender's)."""


class Cancelled(Exception):
    """describe() stopped because its cancel check held (an import cancelled while reading). Not a ValueError: the
    file is not damaged."""


def _raising(cancel):
    """The check describe() passes into a node's read: raises Cancelled once cancel() holds; None without cancel."""
    if cancel is None:
        return None

    def check():
        if cancel():
            raise Cancelled()
    return check


class NodeDescription:
    """One node: index is its object index, parent the parent's (None at the top level); kind MESH, CURVE, LIGHT,
    CAMERA or EMPTY; mesh the key into SceneDescription.meshes, curve the key into SceneDescription.curves, light the
    key into SceneDescription.lights, camera the key into SceneDescription.cameras (None when not one);
    class_name the base object's class ("" without one); modifiers the class names of its modifier stack not applied,
    top first, applied those evaluated into its mesh (an Extrude); layer the layer's object index (None without
    one); hidden, frozen, group_head and group_member the node's own flags, renderable, cast_shadows and
    receive_shadows those it renders with (its layer's when By Layer); sheared whether matrix has shear (see
    sheared()); converted the modifiers that become Blender modifiers (convert.modifiers ModifierDescriptions,
    bottom first); look_at the LookAtDescription of a Look At controller aimed at a node, else None; emitter the
    key into SceneDescription.emitters of a mesh light's MESH node (its mesh an emitter mesh), else None."""
    __slots__ = ("index", "name", "parent", "matrix", "world", "kind", "mesh", "class_name", "mirrored",
                 "modifiers", "layer", "hidden", "frozen", "renderable", "group_head", "group_member", "sheared",
                 "curve", "applied", "converted", "look_at", "light", "camera", "cast_shadows", "receive_shadows",
                 "emitter")

    def __init__(self, index, name, parent, matrix, world, kind, mesh, class_name, mirrored, modifiers, layer=None,
                 hidden=False, frozen=False, renderable=True, group_head=False, group_member=False, sheared=False,
                 curve=None, applied=(), converted=(), look_at=None, light=None, camera=None, cast_shadows=True,
                 receive_shadows=True, emitter=None):
        self.index, self.name, self.parent, self.matrix, self.world = index, name, parent, matrix, world
        self.kind, self.mesh, self.class_name, self.mirrored, self.modifiers = kind, mesh, class_name, mirrored, \
            modifiers
        self.layer, self.hidden, self.frozen, self.renderable = layer, hidden, frozen, renderable
        self.group_head, self.group_member, self.sheared = group_head, group_member, sheared
        self.curve, self.applied, self.converted, self.look_at = curve, applied, converted, look_at
        self.light, self.camera = light, camera
        self.cast_shadows, self.receive_shadows, self.emitter = cast_shadows, receive_shadows, emitter

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
    smoother separates by smoothing groups); zeroed_uvs the U and V coordinates that were not numbers (inf, NaN),
    set to 0."""
    __slots__ = ("key", "name", "positions", "loop_vertices", "loop_starts", "loop_totals", "material_indices",
                 "sharp_faces", "sharp_edges", "uv_layers", "users", "dropped_faces", "applied", "creases",
                 "zeroed_uvs")

    def __init__(self, key, name, positions, loop_vertices, loop_starts, loop_totals, material_indices,
                 sharp_faces, sharp_edges, uv_layers, dropped_faces=0, zeroed_uvs=0):
        self.key, self.name, self.positions = key, name, positions
        self.loop_vertices, self.loop_starts, self.loop_totals = loop_vertices, loop_starts, loop_totals
        self.material_indices, self.sharp_faces, self.sharp_edges = material_indices, sharp_faces, sharp_edges
        self.uv_layers, self.dropped_faces = uv_layers, dropped_faces
        self.users = []
        self.applied = ()
        self.creases = False
        self.zeroed_uvs = zeroed_uvs

    def __repr__(self):
        return "MeshDescription(%r, %d vertices, %d faces, %d UV layers)" % (
            self.name, len(self.positions), len(self.loop_starts), len(self.uv_layers))


class SplineDescription:
    """One Bezier spline in meters: points, left and right handles, each [(x, y, z)] (Blender's handle_left is Max's
    in vector, handle_right its out vector), cyclic for a closed spline; material_ids the distinct zero-based
    material IDs of its segments in segment order (segment_ids), material the first of them, the one the spline
    is drawn with (Blender has one material per spline)."""
    __slots__ = ("points", "left", "right", "cyclic", "material", "material_ids")

    def __init__(self, points, left, right, cyclic, material_ids=(0,)):
        self.points, self.left, self.right, self.cyclic = points, left, right, cyclic
        self.material_ids = tuple(material_ids) or (0,)
        self.material = self.material_ids[0]

    def __repr__(self):
        return "SplineDescription(%d points%s)" % (len(self.points), ", cyclic" if self.cyclic else "")


class CurveDescription:
    """One curve in meters, offset baked: splines [SplineDescription]; resolution the Bezier resolution (segments
    per Bezier segment); bevel_depth the bevel's radius (0: no bevel), bevel_resolution its round profile's
    resolution; section None, or the four (x, y) corners in meters of a rectangular section (profile x across the
    curve, y up: Blender's bevel object), which replaces the round bevel; users the object indices of the nodes that
    share it, in walk order."""
    __slots__ = ("key", "name", "splines", "resolution", "bevel_depth", "bevel_resolution", "section", "users")

    def __init__(self, key, name, splines, resolution, bevel_depth=0.0, bevel_resolution=0, section=None):
        self.key, self.name, self.splines, self.resolution = key, name, splines, resolution
        self.bevel_depth, self.bevel_resolution, self.section = bevel_depth, bevel_resolution, section
        self.users = []

    def __repr__(self):
        return "CurveDescription(%r, %d splines)" % (self.name, len(self.splines))


class LayerDescription:
    """One layer: index its object index, parent the parent layer's (None at the top level). renderable is the
    layer's own switch, which only its By Layer nodes follow (already in their NodeDescription.renderable)."""
    __slots__ = ("index", "name", "parent", "hidden", "frozen", "renderable")

    def __init__(self, index, name, parent=None, hidden=False, frozen=False, renderable=True):
        self.index, self.name, self.parent = index, name, parent
        self.hidden, self.frozen, self.renderable = hidden, frozen, renderable

    def __repr__(self):
        return "LayerDescription(%d, %r, parent=%r)" % (self.index, self.name, self.parent)


class SceneDescription:
    """nodes in walk order, meshes {key: MeshDescription}, curves {key: CurveDescription}, lights {key:
    convert.lights.LightDescription} and cameras {key: convert.cameras.CameraDescription} in order of first use,
    dome the convert.lights.DomeDescription of the World (None without a dome light that is on), emitters {light
    base object index: convert.lights.EmitterDescription} of the mesh lights built as emissive meshes,
    camera the scene camera's node index, camera_note why it is the first camera when that is no issue (None: the
    view 3ds Max renders, or an issue says why), render the convert.cameras.RenderSettings (None when not stored),
    meters per file unit, unit the reader's SystemUnit (None when the file does not say), layers, placeholders,
    unknown_controllers and issues."""
    __slots__ = ("nodes", "meshes", "curves", "lights", "cameras", "camera", "camera_note", "render", "meters",
                 "unit", "layers", "placeholders", "unknown_controllers", "issues", "dome", "emitters")

    def __init__(self, meters, unit=None):
        self.nodes, self.meshes, self.meters, self.unit, self.layers = [], {}, meters, unit, []
        self.curves, self.lights, self.cameras, self.camera, self.render = {}, {}, {}, None, None
        self.camera_note, self.dome, self.emitters = None, None, {}
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
    # int32 per loop where it fits (indices are int32, reader.geometry), int64 only for the key: the arrays per loop
    # are the peak of a mesh's conversion
    lv = numpy.asarray(loop_vertices, dtype=numpy.int32)
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    if not len(lv):
        return numpy.zeros((0, 2), dtype=numpy.int32)
    face = numpy.repeat(numpy.arange(len(starts), dtype=numpy.int32), totals)
    following = numpy.arange(1, len(lv) + 1, dtype=numpy.int32)
    following[starts + totals - 1] = starts  # the last loop of a face closes it
    b = lv[following]
    del following
    lo, hi = numpy.minimum(lv, b), numpy.maximum(lv, b)
    del b
    key = lo.astype(numpy.int64)
    key *= int(lv.max()) + 1
    key += hi
    order = numpy.argsort(key, kind="stable")
    key, face = key[order], face[order]
    groups = numpy.asarray(groups, dtype=numpy.uint32)
    first = numpy.flatnonzero(numpy.concatenate(([True], key[1:] != key[:-1])))  # key is sorted: its runs
    counts = numpy.diff(numpy.append(first, len(key)))
    two = first[counts == 2]
    sharp = two[(groups[face[two]] & groups[face[two + 1]]) == 0]
    more = [start for start, n in zip(first[counts > 2], counts[counts > 2])
            if _disjoint(groups[face[start:start + n]])]
    if more:
        sharp = numpy.sort(numpy.concatenate((sharp, numpy.asarray(more, dtype=sharp.dtype))))
    src = order[sharp]
    return numpy.stack((lo[src], hi[src]), axis=1).astype(numpy.int32)


def open_edges(loop_vertices, loop_starts, loop_totals, check=None):
    """The edges only one face uses (the mesh's boundary), as sorted vertex pairs int32 (E, 2) in sharp_edges()'s
    order. check() between the passes."""
    import numpy
    loops, following = _open_loops(loop_vertices, loop_starts, loop_totals, check)
    lv = numpy.asarray(loop_vertices, dtype=numpy.int32)
    a, b = lv[loops], lv[following]
    return _merged_edges(numpy.stack((numpy.minimum(a, b), numpy.maximum(a, b)), axis=1), numpy.zeros((0, 2)))


def _open_loops(loop_vertices, loop_starts, loop_totals, check=None):
    """(loops, following): the loops whose edge to the next loop of their face no other loop has (the open edges, in
    their face's winding) and those next loops, int64 arrays as long as the boundary. Per loop only an int32 and the
    int64 edge key, as in sharp_edges(): the arrays per loop are the peak of a mesh's conversion."""
    import numpy
    lv = numpy.asarray(loop_vertices, dtype=numpy.int32)
    empty = numpy.zeros(0, dtype=numpy.int64)
    if not len(lv):
        return empty, empty
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    following = numpy.arange(1, len(lv) + 1, dtype=numpy.int32)
    following[starts + totals - 1] = starts  # the last loop of a face closes it
    b = lv[following]
    del following
    key = numpy.minimum(lv, b).astype(numpy.int64)
    key *= int(lv.max()) + 1
    key += numpy.maximum(lv, b)
    del b
    order = numpy.argsort(key, kind="stable")
    key = key[order]
    if check is not None:
        check()
    first = numpy.flatnonzero(numpy.concatenate(([True], key[1:] != key[:-1])))
    counts = numpy.diff(numpy.append(first, len(key)))
    del key
    loops = numpy.sort(order[first[counts == 1]]).astype(numpy.int64)
    face = numpy.searchsorted(starts, loops, side="right") - 1
    nxt = loops + 1
    wrap = nxt == starts[face] + totals[face]
    nxt[wrap] = starts[face[wrap]]
    return loops, nxt


def _merged_edges(a, b):
    """The union of two arrays of sorted vertex pairs (E, 2), sorted and without repeats."""
    import numpy
    pairs = numpy.concatenate((numpy.asarray(a, dtype=numpy.int64).reshape(-1, 2),
                               numpy.asarray(b, dtype=numpy.int64).reshape(-1, 2)))
    if not len(pairs):
        return numpy.zeros((0, 2), dtype=numpy.int32)
    n = int(pairs.max()) + 1
    keys = numpy.unique(pairs[:, 0] * n + pairs[:, 1])
    return numpy.stack((keys // n, keys % n), axis=1).astype(numpy.int32)


def rim_corners(positions, loop_vertices, loop_starts, loop_totals, angle, check=None):
    """How many corners of the rim a Shell builds on this mesh turn by more than angle degrees: at each boundary
    vertex two rim faces meet, each along an open edge a -> b (its face's winding) and the shell's offset direction
    at its ends, so its normal is (pb - pa) x (na + nb), n the sum of the unit face normals at a vertex. 3ds Max's
    auto smooth splits the rim there; with the open edges sharp, Blender's Solidify keeps it smooth. Only the faces
    at the boundary are measured; check() between the passes and their chunks.

    Kept at _open_loops()' peak: int32 indices (vertex indices are int32 and face corners below
    reader.geometry.MAX_LOOPS), the work per face corner and per open edge in chunks of geometry.CHECK_EVERY, kept
    only as sums per boundary face and per boundary vertex; a chunk may split a face (numpy.add.at sums in corner
    order, as one pass would)."""
    import numpy
    loops, nxt = _open_loops(loop_vertices, loop_starts, loop_totals, check)
    if not len(loops):
        return 0
    chunk = geometry.CHECK_EVERY
    lv = numpy.asarray(loop_vertices, dtype=numpy.int32)
    starts = numpy.asarray(loop_starts, dtype=numpy.int32)
    totals = numpy.asarray(loop_totals, dtype=numpy.int32)
    p = numpy.asarray(positions)  # float32 from the reader: each chunk takes float64 (exact)
    oa, ob = lv[loops], lv[nxt]
    del loops, nxt
    boundary = numpy.unique(numpy.concatenate((oa, ob)))
    slot = numpy.full(len(p), -1, dtype=numpy.int32)  # vertex -> its place in boundary, -1 off the boundary
    slot[boundary] = numpy.arange(len(boundary), dtype=numpy.int32)
    n_boundary = len(boundary)
    del boundary
    if check is not None:
        check()
    parts = []
    for a in range(0, len(lv), chunk):
        # int32 like starts: searchsorted would copy starts to int64 on every chunk
        touching = (numpy.flatnonzero(slot[lv[a:a + chunk]] >= 0) + a).astype(numpy.int32)
        parts.append(numpy.unique(numpy.searchsorted(starts, touching, side="right") - 1).astype(numpy.int32))
        if check is not None:
            check()
    faces = numpy.unique(numpy.concatenate(parts))
    del parts
    sizes = totals[faces]
    ends = numpy.cumsum(sizes, dtype=numpy.int32)  # those faces' corners one after the other: where each ends

    def corners(a):
        """(own, fl, fn) of the corners a to a + chunk of the boundary faces: the face among them, the loop and the
        next loop of its face."""
        k = numpy.arange(a, min(a + chunk, int(ends[-1])), dtype=numpy.int32)  # as ends, for searchsorted
        own = numpy.searchsorted(ends, k, side="right")
        first = starts[faces[own]].astype(numpy.int64)
        fl = first + (k - (ends[own] - sizes[own]))
        fn = fl + 1
        wrap = fn == first + sizes[own]
        fn[wrap] = first[wrap]
        return own, fl, fn

    normals = numpy.zeros((len(faces), 3))
    for a in range(0, int(ends[-1]), chunk):
        own, fl, fn = corners(a)
        # Newell: twice the area along the normal
        numpy.add.at(normals, own, numpy.cross(p[lv[fl]].astype(numpy.float64), p[lv[fn]].astype(numpy.float64)))
        if check is not None:
            check()
    length = numpy.linalg.norm(normals, axis=1)
    normals = numpy.divide(normals, length[:, None], out=numpy.zeros_like(normals), where=length[:, None] > 0)
    del length
    at_vertex = numpy.zeros((n_boundary, 3))
    for a in range(0, int(ends[-1]), chunk):
        own, fl, _fn = corners(a)
        at = slot[lv[fl]]
        hit = at >= 0
        numpy.add.at(at_vertex, at[hit], normals[own[hit]])
        if check is not None:
            check()
    del normals

    def rim(e):
        """(unit rim normals, nonzero) of the open edges e."""
        pa, pb = p[oa[e]].astype(numpy.float64), p[ob[e]].astype(numpy.float64)
        r = numpy.cross(pb - pa, at_vertex[slot[oa[e]]] + at_vertex[slot[ob[e]]])
        length = numpy.linalg.norm(r, axis=1)
        good = length > 0
        return numpy.divide(r, length[:, None], out=numpy.zeros_like(r), where=good[:, None]), good

    order = numpy.argsort(oa, kind="stable").astype(numpy.int32)
    ordered = oa[order]
    cos = math.cos(math.radians(angle))
    sharp = 0
    for a in range(0, len(oa), chunk):
        e = numpy.arange(a, min(a + chunk, len(oa)), dtype=numpy.int64)
        at = numpy.minimum(numpy.searchsorted(ordered, ob[e]), len(oa) - 1)
        found = ordered[at] == ob[e]  # the open edge leaving the vertex this one ends at
        following = order[at]
        here, good = rim(e)
        there, good_there = rim(following)
        turn = numpy.einsum("ij,ij->i", here, there)
        sharp += int((found & good & good_there & (turn < cos)).sum())
        if check is not None:
            check()
    return sharp


def _disjoint(masks):
    """Whether two of the smoothing-group masks of one non-manifold edge share no group. Equal non-zero masks always
    share one, so only the distinct masks are paired, at most MAX_EDGE_MASKS of them: a file can put any number of
    faces on one edge, and an edge past the cap is taken as sharp."""
    distinct = {int(v) for v in masks}
    if 0 in distinct or len(distinct) > MAX_EDGE_MASKS:
        return True
    distinct = sorted(distinct)
    return any(x & y == 0 for k, x in enumerate(distinct) for y in distinct[k + 1:])


def mesh_area(positions, loop_vertices, loop_starts, loop_totals, keep=None):
    """The total area of a mesh's polygons (Newell's vector of each, so a polygon that is not flat counts its
    projected area), in the square of the positions' unit; keep (bool (F,)): only those polygons."""
    import numpy
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    some = totals > 0
    if keep is not None:
        keep = numpy.asarray(keep, dtype=bool)[some]
    starts, totals = starts[some], totals[some]
    if not len(starts):
        return 0.0
    p = numpy.asarray(positions, dtype=numpy.float64)[numpy.asarray(loop_vertices, dtype=numpy.int64)]
    following = numpy.arange(1, len(p) + 1)
    following[starts + totals - 1] = starts
    newell = numpy.add.reduceat(numpy.cross(p, p[following]), starts, axis=0)
    areas = numpy.sqrt((newell * newell).sum(axis=1))
    return float((areas[keep] if keep is not None else areas).sum() / 2.0)


def valid_faces(loop_vertices, loop_starts, loop_totals):
    """bool (F,): False for a face Blender cannot hold, one of fewer than three vertices, one that uses a vertex twice
    or has the vertex set of an earlier face (3ds Max keeps both: degenerate and doubled triangles occur in files)."""
    import numpy
    lv = numpy.asarray(loop_vertices, dtype=numpy.int64)
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    keep = totals >= 3
    for total in numpy.unique(totals[keep]):  # one numpy pass per face size
        faces = numpy.flatnonzero(totals == total)
        rows = numpy.sort(lv[starts[faces][:, None] + numpy.arange(total)], axis=1)
        repeated = (numpy.diff(rows, axis=1) == 0).any(axis=1)
        keep[faces[repeated]] = False
        good = faces[~repeated]
        if not len(good):
            continue
        rows = rows[~repeated]
        order = numpy.lexsort(rows.T)  # stable: the earliest face of equal rows comes first
        rows = rows[order]
        later = order[1:][(rows[1:] == rows[:-1]).all(axis=1)]
        keep[good[later]] = False
    return keep


def _reversed_loops(loop_starts, loop_totals):
    """The loop permutation that reverses every polygon in place."""
    import numpy
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    face = numpy.repeat(numpy.arange(len(starts)), totals)
    return 2 * starts[face] + totals[face] - 1 - numpy.arange(int(totals.sum()))


def _positions(data, offset, meters):
    """The float64 positions (V, 3) of reader MeshData data, the offset (a reader matrix, or None) applied, then
    meters; MeshError when one is not a number Blender's single precision holds (inf, NaN, past the largest
    float32)."""
    import numpy
    with numpy.errstate(over="ignore", invalid="ignore"):  # inf and NaN are refused below
        p = numpy.asarray(data.positions, dtype=numpy.float64)
        if offset is not None:
            m = numpy.asarray(offset, dtype=numpy.float64)
            p = p @ m[:3, :3] + m[3, :3]
        p = p * meters
    if not (numpy.abs(p) < lights.MAX_FLOAT).all():  # False for NaN too
        raise MeshError("its points do not fit single precision (Blender's meshes hold no larger value)")
    return p


def mesh_description(key, name, data, offset, meters, check=None):
    """A MeshDescription of reader MeshData: faces Blender cannot hold left out (counted in dropped_faces), the
    offset (a reader matrix) applied, then meters; MeshError when a position does not fit single precision
    (_positions). U and V coordinates that are not numbers become 0 (counted in zeroed_uvs). check() between the
    numpy passes of a mesh of more than reader.geometry.CHECK_EVERY face corners; what it raises passes
    unchanged."""
    import numpy
    if check is not None and len(data.loop_vertices) <= geometry.CHECK_EVERY:
        check = None  # one pass of a small mesh is quick: the call counts stay once per node
    positions = _positions(data, offset, meters).astype(numpy.float32)
    starts = numpy.asarray(data.loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(data.loop_totals, dtype=numpy.int64)
    lv = numpy.asarray(data.loop_vertices, dtype=numpy.int32)
    groups, materials = data.smoothing_groups, data.material_ids
    loops = None  # the loops kept, in their new order; None = all, unchanged
    if check is not None:
        check()
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
    zeroed = 0
    for channel in sorted(c for c in data.maps if c >= 1):
        if check is not None:
            check()
        mc = data.maps[channel]
        indices = mc.indices if loops is None else mc.indices[loops]
        uv = numpy.ascontiguousarray(mc.uvw[indices][:, :2], dtype=numpy.float32)  # a copy: mc.uvw is the reader's
        bad = ~numpy.isfinite(uv)
        if bad.any():
            zeroed += int(bad.sum())
            uv[bad] = 0.0
        uv_layers.append((UV_FIRST if channel == 1 else UV_NAME % channel, uv))
    if check is not None:
        check()
    sharp = sharp_edges(lv, starts, totals, groups)
    return MeshDescription(key, name, positions, lv, starts.astype(numpy.int32), totals.astype(numpy.int32),
                           materials.astype(numpy.int32), groups == 0, sharp, uv_layers, dropped, zeroed)


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


def segment_ids(knots, closed):
    """The distinct material IDs of a spline's segments (reader knots) in segment order: the segment from a knot to
    the next carries the knot's; the last knot of an open spline starts none (its ID is left out), a spline without
    a segment has its first knot's."""
    count = len(knots) if closed else len(knots) - 1
    ids = [k.material for k in knots[:max(count, 1)]]
    return tuple(dict.fromkeys(ids))


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
                                         [place(p) for p in right], sp.closed, segment_ids(sp.knots, sp.closed)))
    if not all(_fits(p) for sd in splines for ps in (sd.points, sd.left, sd.right) for p in ps):
        raise CurveError("its points do not fit single precision (Blender's curves hold no larger value)")
    resolution = ADAPTIVE if shape.adaptive else shape.steps + 1
    depth, profile, section = 0.0, 0, None
    r = shape.render
    if r.renderable and r.rectangular:
        if r.width > 0 and r.length > 0:
            section = rectangular_section(r.width * meters, r.length * meters, r.section_angle)
            if not all(_fits(c) for c in section):
                section = None
                issues.append("a rectangular section of %g x %g does not fit single precision: not drawn"
                              % (r.width, r.length))
            elif not _flat(splines):
                issues.append("a rectangular section on a curve that is not flat in XY may turn otherwise than in "
                              "3ds Max")
        else:
            issues.append("a rectangular section of %g x %g is not drawn" % (r.width, r.length))
    elif r.renderable and r.thickness > 0:
        depth = r.thickness / 2.0 * meters
        profile = max(0, (r.sides - 4) // 2)  # Blender's round profile has 4 + 2 * resolution sides
        if not _fits((depth,)):
            depth, profile = 0.0, 0
            issues.append("a thickness of %g does not fit single precision: not drawn" % r.thickness)
    return CurveDescription(key, name, splines, resolution, depth, profile, section), issues


def rectangular_section(width, length, angle):
    """The corners of 3ds Max's rectangular section in Blender's bevel profile: width across the curve (profile x),
    length up (y), turned by angle degrees counter-clockwise in the profile, which is 3ds Max's angle (the
    shapes_more fixture's render mesh)."""
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    x, y = width / 2.0, length / 2.0
    return [(px * c - py * s, px * s + py * c) for px, py in ((x, y), (-x, y), (-x, -y), (x, -y))]


def _fits(p):
    """Whether every coordinate of p is a number Blender's single precision holds (not inf, not NaN)."""
    return all(abs(c) < lights.MAX_FLOAT for c in p)


def _flat(splines):
    """Whether every point and handle of splines (meters) lies in one plane of constant z."""
    zs = [p[2] for sd in splines for ps in (sd.points, sd.left, sd.right) for p in ps]
    if not zs:
        return True
    extent = max(abs(c) for sd in splines for p in sd.points for c in p)
    return max(zs) - min(zs) <= 1e-6 * (1.0 + extent)


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


def describe(scene, meters=1.0, unit=None, convert_modifiers=True, assets=None, views=None, cancel=None,
             files=None):
    """The SceneDescription of a reader.scene.Scene; meters is the length of one file unit; convert_modifiers False
    leaves the modifiers Blender has an equivalent for in node.modifiers, unconverted and unreported; assets, the
    scene's reader.assets.AssetTable, names the files of web and IES lights (None: not named); views, the file's
    convert.cameras.SavedViews, picks the scene camera (None: the first camera); cancel, a callable asked before each
    node of both walks and inside the read and description of a large mesh, ends it with Cancelled once it returns
    true; files, a convert.textures.TextureIndex, finds the IES files of VRayIES lights (None: not looked up)."""
    if not (math.isfinite(meters) and meters > 0):
        raise ValueError("meters per unit must be a positive number, not %r" % (meters,))
    check = _raising(cancel)
    t = controllers.Transforms(scene)
    stacks = reader_modifiers.Modifiers(scene)
    desc = SceneDescription(meters, unit)
    order = scene.walk()
    found = {}  # node -> (reader Node, Stack or None), or the ChunkError its record or object stack raised
    shape_of = {}  # base object index -> reader Shape, or the text of the reader's refusal (_shape)
    unbuilt = set()  # curve keys refused for their range (CurveError), named on their first node
    remaining = collections.Counter()  # base object -> nodes still to build: its MeshData goes with the last
    for i in order:
        if check is not None:
            check()
        try:
            node = scene.node(i)
            stack = scene.object_stack(node.object) if node.object is not None else None
            found[i] = (node, stack)
            if stack is not None and stack.base is not None:
                remaining[stack.base] += 1
        except ChunkError as exc:
            found[i] = exc
    data_of = {}  # base object index -> MeshData, or None when the reader refused or does not read it
    built = [0]  # face corners the primitives and extrusions made so far
    extrusions = _Extrusions(scene, desc, shape_of, built)  # shared by the shapes' nodes and the mesh lights
    mapped = {}  # UVW Map modifier index -> (Params, gizmo matrix), or None when it is not evaluated
    told = set()  # modifier indices whose conversion issues were named (on the first node only)
    rims = set()  # (Shell modifier index, mesh key) whose rim issues were named
    ranges = {}  # mesh key before its maps -> whether its positions fit single precision (_mapped_mesh)
    layers = {}  # layer object index -> reader Layer, or None when its record cannot be read
    unlit = {}  # light base object index -> why it is not built
    light_params = {}  # light base object index -> its values (convert.lights.read_params)
    emitter_meshes = {}  # mesh light base -> its mesh (_emitter_mesh) or why it has none, until its last node
    emitter_refused = {}  # (mesh light base, node offset) -> why its emitter mesh does not fit single precision
    ies_files = ies.Lookup(files) if files is not None else None
    swatches = None  # the scene's swatch rule, read for the first light
    unseen = {}  # camera base object index -> why it is not built
    camera_params = {}  # camera base object index -> its values (convert.cameras.read_params)
    mm = unit.meters * 1000.0 if unit is not None else meters * 1000.0  # the thin lens is in the file's own unit
    for i in order:
        if check is not None:
            check()
        local, world = t.local(i), t.world(i)
        kind, key, class_name, modifiers, name, node, layer, base = EMPTY, None, "", (), "", None, None, None
        curve, applied, converted, light, camera, emitter = None, (), (), None, None, None
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
                    shell = _rim(conv)
                    mirrors = _mirrors(conv, shell)
                    key, done = _extruded(scene, desc, extrusions, mapped, base, ext, maps, i, name, t.offset(i),
                                          meters, _shading(conv), check, shell is not None, mirrors, ranges)
                    if key is None:
                        told.difference_update(fresh)
                if key is not None:
                    kind = MESH
                    converted, more = rules.budget(conv, len(desc.meshes[key].loop_vertices))
                    desc.issues.extend((i, x) for x in conv_issues + more)
                    _name_rim(desc, rims, shell, key, i, check, mirrors)
                    applied, modifiers = _split(scene, stack.modifiers, (ext,) + done, conv)
                else:
                    kind, curve = _curve(scene, desc, shape_of, unbuilt, base, i, name, t.offset(i), meters)
                remaining[base] -= 1
                if not remaining[base]:
                    extrusions.drop(base)
            elif base is not None and lights.light_class(scene, base) is not None:
                class_name = _class_name(scene, base)
                if swatches is None:
                    swatches = colors.of_scene(scene)
                light = _light(scene, desc, unlit, light_params, base, i, name, meters, swatches, world, assets,
                               ies_files)
                kind = LIGHT if light is not None else EMPTY
                if light is None and base in light_params and lights.is_mesh_light(light_params[base]):
                    refused = (base, _offset(t, i))
                    if refused in emitter_refused:  # not described again for each node
                        desc.issues.append((i, "light: not built: %s" % emitter_refused[refused]))
                    else:
                        try:
                            key, emitter, converted = _emitter(scene, t, desc, emitter_meshes, light_params[base],
                                                               base, i, name, meters, swatches, built, check, stacks,
                                                               told, convert_modifiers, extrusions)
                        except MeshError as exc:  # its mesh with the node's offset: nothing of it is written yet
                            emitter_refused[refused] = str(exc)
                            desc.issues.append((i, "light: not built: %s" % exc))
                        else:
                            if key is not None:
                                kind = MESH
                                if desc.meshes[key].users == [i]:
                                    _name_zeroed(desc, desc.meshes[key], i)
                remaining[base] -= 1
                if not remaining[base]:
                    mesh = emitter_meshes.pop(base, None)
                    if isinstance(mesh, tuple) and not remaining[mesh[0]]:  # a picked shape no node still needs
                        extrusions.drop(mesh[0])
            elif base is not None and cameras.camera_class(scene, base) is not None:
                class_name = _class_name(scene, base)
                camera = _camera(scene, t, desc, unseen, camera_params, base, i, name, meters, mm)
                kind = CAMERA if camera is not None else EMPTY
            elif base is not None:
                class_name = _class_name(scene, base)
                if base not in data_of:
                    try:
                        data_of[base] = geometry.read_mesh(scene, base, check)
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
                    fresh = {m.index for m in rest} - told  # named on this node only if its mesh is made
                    converted, conv_issues = _converted(scene, rest, meters, offset, told, convert_modifiers)
                    shell = _rim(converted)
                    mirrors = _mirrors(converted, shell)
                    key, done = _mapped_mesh(scene, desc, mapped, (base, offset), data, maps, i, name, offset,
                                             meters, _shading(converted), check, shell is not None, mirrors, ranges)
                    if key is None:  # its positions do not fit single precision: a placeholder
                        told.difference_update(fresh)
                        converted = ()
                    else:
                        desc.issues.extend((i, x) for x in conv_issues)
                        converted, more = rules.budget(converted, len(desc.meshes[key].loop_vertices))
                        desc.issues.extend((i, x) for x in more)
                        _name_rim(desc, rims, shell, key, i, check, mirrors)
                        if done or converted:
                            applied, modifiers = _split(scene, stack.modifiers, done, converted)
                        kind = MESH
                remaining[base] -= 1
                if not remaining[base]:
                    del data_of[base]
        if kind == EMPTY and not (base is not None and (scene.is_a(base, classids.SC_HELPER, classids.DUMMY) or
                                                        scene.is_a(base, classids.SC_GEOMOBJECT,
                                                                   classids.TARGET_OBJECT) or base in unlit
                                                        or base in light_params or base in unseen)):
            desc.placeholders[class_name] += 1
        flags = {}
        if node is not None:
            render = reader_scene.render_flags(node, None if layer is None else layers[layer])
            flags = dict(hidden=node.hidden, frozen=node.frozen, renderable=bool(render & reader_scene.RENDERABLE),
                         group_head=node.group_head, group_member=node.group_member,
                         cast_shadows=bool(render & reader_scene.CAST_SHADOWS),
                         receive_shadows=bool(render & reader_scene.RECEIVE_SHADOWS))
            if not flags["receive_shadows"] and kind in (MESH, CURVE):
                desc.issues.append((i, NO_RECEIVE))
        desc.nodes.append(NodeDescription(i, name, scene.parent(i), blender_matrix(local, meters),
                                          blender_matrix(world, meters), kind, key, class_name,
                                          determinant3(world) < 0, modifiers, layer, sheared=sheared(local),
                                          curve=curve, applied=applied, converted=converted,
                                          look_at=look_at_description(t.look_at(i)), light=light, camera=camera,
                                          emitter=emitter, **flags))
    desc.render, issues = cameras.render_settings(scene)
    desc.issues.extend((None, "render: %s" % x) for x in issues)
    names = {node.index: node.name or "object %d" % node.index for node in desc.nodes}
    desc.camera, reason, desc.camera_note = cameras.render_camera(
        desc.render, views, [n.index for n in desc.nodes if n.kind == CAMERA], names)
    if reason is not None:
        desc.issues.append((desc.camera, "camera: %s" % reason))
    if lights.environment_sky(scene) is not None:
        desc.issues.append((ENVIRONMENT, "light: %s" % lights.SKY))
    desc.issues.extend((issue.node, "transform: %s" % issue.reason) for issue in t.issues)
    desc.unknown_controllers.update(
        _class_name(scene, issue.controller) if issue.controller is not None else ""
        for issue in t.issues if issue.reason == controllers.UNKNOWN_CLASS)
    desc.layers = _layer_descriptions(scene, layers)
    return desc


def _dome(desc, values, node, name, swatches, world):
    """A dome light's node: desc.dome when it is the first that is on, else an issue."""
    if not values[lights.P_ON]:
        desc.issues.append((node, "light: " + lights.DOME_OFF))
    elif desc.dome is not None:
        desc.issues.append((node, "light: " + lights.SECOND_DOME % (desc.dome.name or "object %d" % desc.dome.node)))
    else:
        desc.dome, issues = lights.describe_dome(node, name, values, swatches, world)
        desc.issues.extend((node, "light: %s" % x) for x in issues)


def _light(scene, desc, unlit, params, base, node, name, meters, swatches, world, assets=None, ies_files=None):
    """The key in desc.lights of light base on node (world: its reader world matrix), made on first use; None when it
    is not built (unlit caches the reason, an issue on every node) and for a dome (_dome). params caches the light's
    values, whose issues are named on the first node; a description's on the first node of its key."""
    if base not in params and base not in unlit:
        try:
            values, issues = lights.read_params(scene, base, assets, ies_files)
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
    if lights.is_dome(params[base]):
        _dome(desc, params[base], node, name, swatches, world)
        return None
    if lights.is_mesh_light(params[base]):  # an emitter (_emitter)
        return None
    scale = lights.area_scale(params[base], world)
    key = (base, scale)
    if key not in desc.lights:
        ld, issues = lights.describe(key, name, params[base], meters, swatches, scale)
        desc.lights[key] = ld
        desc.issues.extend((node, "light: %s" % x) for x in issues)
    desc.lights[key].users.append(node)
    return key


def _emitter(scene, t, desc, meshes, values, base, node, name, meters, swatches, built, check=None, stacks=None,
             told=None, convert=True, extrusions=None):
    """(the key in desc.meshes of mesh light base's emitter mesh on node, its key in desc.emitters, the converted
    modifiers of its mesh object as on node (ModifierDescriptions, budgeted)), or (None, None, ()) when it has no mesh
    MaxDrop builds (meshes caches the reason, an issue on every node). The mesh is the mesh object's mesh below its
    modifiers (_emitter_mesh) in its object space with the light node's offset baked (V-Ray places it at the light's
    object transform); the modifiers above it are converted with that offset (_converted: told and convert as there;
    their issues as a mesh node's), a converted smoother that separates by smoothing groups creasing the mesh's sharp
    edges (md.creases, as _mapped_mesh does: the shape and so the area depend on it; a smoother's SMOOTH shading and a
    Shell's rim change the shading only, which an emitter does not show). The description's issues, and the line
    naming the modifiers neither evaluated nor converted (but those _converted names), are named on the first
    node. extrusions: as _emitter_mesh's."""
    if base not in meshes:
        meshes[base] = _emitter_mesh(scene, desc, values, node, meters, built, check, stacks, extrusions)
    found = meshes[base]
    if isinstance(found, str):
        desc.issues.append((node, "light: not built: %s" % found))
        return None, None, ()
    mesh_base, data, area, rest, unread = found
    offset = _offset(t, node)
    key = (EMITTER, base, mesh_base, offset)
    md = desc.meshes.get(key)
    if md is None:
        md = desc.meshes[key] = mesh_description(key, name, data, offset, meters, check)
        if md.dropped_faces:
            desc.issues.append((node, "geometry: %d faces with a repeated vertex or doubled, left out"
                                % md.dropped_faces))
    md.users.append(node)
    converted, issues = _converted(scene, rest, meters, offset, set() if told is None else told, convert)
    converted, more = rules.budget(converted, len(md.loop_vertices))
    desc.issues.extend((node, x) for x in issues + more)
    if _shading(converted) == rules.CREASE:
        md.creases = True
    if base not in desc.emitters:
        ed, issues = lights.describe_emitter(base, name, values, swatches, area)
        desc.emitters[base] = ed
        done = {m.index for m in converted}
        left = unread + tuple(_class_name(scene, m.index) or "a modifier" for m in reversed(rest)
                              if m.index not in done and not (convert and rules.is_convertible(m)))
        if left:
            issues.append(lights.EMITTER_MODIFIERS % ", ".join(left))
        desc.issues.extend((node, "light: %s" % x) for x in issues)
    desc.emitters[base].users.append(node)
    return key, base, converted


def _emitter_mesh(scene, desc, values, node, meters, built, check=None, stacks=None, extrusions=None):
    """(mesh base object index, reader MeshData, its object-space area in m^2 (the faces Blender holds), the reader
    Modifiers above it that render (bottom first, its UVW Maps left out: _emitter_rest), the class names of the
    modifiers of a stack the reader cannot read (top first)) of a mesh light's mesh: its own mesh object
    (lights.MESH_OBJECT: what V-Ray's Replace mesh with light keeps), else (none, or not a mesh read here) the object
    of the node its mesh source (parameter 34) names; or why it has none (the own object's reason when both fail).
    The mesh is the object's base mesh (_mesh_of), or its shape under the Extrude right above it (_emitter_shape).
    stacks: the scene's reader.modifiers Modifiers (None: none read, every modifier named); extrusions: the scene's
    _Extrusions, shared with the shape's own nodes (None: one of its own, counting into built)."""
    if extrusions is None:
        extrusions = _Extrusions(scene, desc, {}, built)
    reasons = []
    for obj in (values.get(lights.MESH_OBJECT), _source_object(scene, values.get(lights.P_MESH_SOURCE))):
        if obj is None:
            continue
        found = _emitter_shape(scene, desc, stacks, obj, node, extrusions)
        if found is None:
            found = _mesh_of(scene, desc, obj, node, built, check)
            if not isinstance(found, str):
                found = found + (None,)
        if not isinstance(found, str):
            mesh_base, data, stack, ext = found
            keep = valid_faces(data.loop_vertices, data.loop_starts, data.loop_totals)
            area = mesh_area(data.positions, data.loop_vertices, data.loop_starts, data.loop_totals, keep)
            rest, unread = _emitter_rest(scene, desc, stacks, obj, stack, ext, node)
            return mesh_base, data, area * meters * meters, rest, unread
        reasons.append(found)
    return reasons[0] if reasons else lights.NO_MESH


def _active(stacks, obj):
    """The reader Modifiers of object obj that render, bottom first (ChunkError when its stack cannot be read)."""
    return [m for m in stacks.object_stack(obj).modifiers if m.renders]


def _emitter_rest(scene, desc, stacks, obj, stack, ext, node):
    """(rest, unread) of _emitter_mesh: the modifiers of object obj that render above its mesh (the Extrude ext made
    it, or None), but the UVW Maps (an emitter has no texture), bottom first, and (); or, without stacks or when the
    reader cannot read them (an issue on node), () and the class names of reader Stack stack's modifiers."""
    if stacks is not None:
        try:
            active = _active(stacks, obj)
        except ChunkError as exc:
            desc.issues.append((node, "modifiers: the modifier stack cannot be read: %s" % exc))
        else:
            return tuple(m for m in active if not uvwmap.is_uvwmap(m) and (ext is None or m.index != ext.index)), ()
    return (), tuple(_class_name(scene, m) or "a modifier" for m in stack.modifiers)


def _emitter_shape(scene, desc, stacks, obj, node, extrusions):
    """(shape base object index, reader MeshData of the Extrude, reader Stack, the Extrude's reader Modifier) of object
    obj when it is a shape whose lowest modifier that renders is an Extrude (convert.extrude), made once with the
    shape's own nodes (_Extrusions); why it has no mesh when the shape, the Extrude or the positions cannot be made,
    or the scene's MAX_BUILT_CORNERS are spent; None when obj is no such shape (_mesh_of then says why)."""
    if stacks is None:
        return None
    try:
        stack = scene.object_stack(obj)
    except ChunkError:  # _mesh_of names the stack it cannot read
        return None
    if stack.base is None or not shapes.is_shape(scene, stack.base):
        return None
    try:
        active = _active(stacks, obj)
    except ChunkError as exc:  # whether an Extrude makes it a mesh is not known
        return lights.EMITTER_UNREAD % ("the modifier stack cannot be read: %s" % exc)
    if not (active and extrude.is_extrude(active[0])):
        return None
    ext = active[0]
    data = extrusions.get(stack.base, ext, node, light=True)
    if isinstance(data, tuple):
        kind, text = data
        return lights.EMITTER_UNREAD % ("its Extrude is not made: " + text if kind == _SPENT_KIND else text)
    try:
        _positions(data, None, desc.meters)  # before the light node's offset, applied in _emitter (describe)
    except MeshError as exc:
        return lights.EMITTER_UNREAD % exc
    return stack.base, data, stack, ext


def _source_object(scene, source):
    """The object of node source (a mesh light's parameter 34), None when it is no node or has none."""
    if source is None or not 0 <= source < len(scene):
        return None
    try:
        return scene.node(source).object
    except ChunkError:  # not a node, or its record cannot be read
        return None


def _mesh_of(scene, desc, obj, node, built, check=None):
    """(base object index, reader MeshData, reader Stack) of object obj's base mesh, or why there is none (also a
    mesh whose positions in meters do not fit single precision)."""
    try:
        stack = scene.object_stack(obj)
    except ChunkError as exc:
        return lights.EMITTER_UNREAD % exc
    mesh_base = stack.base
    if mesh_base is None:
        return lights.EMITTER_UNREAD % "no base object"
    data = None
    if not shapes.is_shape(scene, mesh_base):
        try:
            data = geometry.read_mesh(scene, mesh_base, check)
        except geometry.GeometryError as exc:
            return lights.EMITTER_UNREAD % exc
        if data is None and primitives.is_primitive(scene, mesh_base):
            data = _primitive(scene, mesh_base, desc.issues, node, built)
    if data is None:
        return lights.EMITTER_CLASS % (_class_name(scene, mesh_base) or "an unknown class")
    try:
        _positions(data, None, desc.meters)  # before the light node's offset, applied in _emitter (describe)
    except MeshError as exc:
        return lights.EMITTER_UNREAD % exc
    return mesh_base, data, stack


def _camera(scene, t, desc, unseen, params, base, node, name, meters, mm):
    """The key in desc.cameras of camera base on node, made on first use; None when its parameters cannot be read
    (unseen caches the reason, an issue on every node). params caches the camera's values, whose issues are named
    on the first node; a description's on the first node of its key. The key holds the distance to the node's
    target when the camera's framing depends on it."""
    if base not in params and base not in unseen:
        try:
            values, issues = cameras.read_params(scene, base)
            params[base] = values
        except ChunkError as exc:
            issues = []
            unseen[base] = "parameters cannot be read: %s" % exc
        desc.issues.extend((node, "camera: %s" % x) for x in issues)
    if base in unseen:
        desc.issues.append((node, "camera: not built: %s" % unseen[base]))
        return None
    values = params[base]
    look = t.look_at(node)
    target = None
    if look is not None and look.target is not None:
        a, b = t.world(node)[3], t.world(look.target)[3]
        target = float("%.9g" % math.sqrt(sum((a[k] - b[k]) ** 2 for k in range(3))))
    used = cameras.focus_target(values, target)
    key = (base, used if target is not None and used == target and cameras.uses_target(values) else None)
    if key not in desc.cameras:
        cd, issues = cameras.describe(key, name, values, meters, mm, target)
        desc.cameras[key] = cd
        desc.issues.extend((node, "camera: %s" % x) for x in issues)
    desc.cameras[key].users.append(node)
    if t.offset(node) != controllers.IDENTITY:
        desc.issues.append((node, "camera: " + OFFSET))
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
    except ArithmeticError as exc:  # a formula the sizes break costs the object, not the import
        issues.append((node, "primitive: not built: %s" % exc))
        return None
    built[0] += len(data.loop_vertices)
    issues.extend((node, "primitive: %s" % x) for x in more)
    return data


def _shape(scene, desc, shape_of, base, node):
    """The reader Shape of base, read once (shape_of caches it, or the text of its refusal), None when refused; its
    issues, or the refusal, are named on the first node only."""
    if base not in shape_of:
        try:
            shape_of[base] = shapes.read_shape(scene, base)
            desc.issues.extend((node, "shape: %s" % x) for x in shape_of[base].issues)
        except ChunkError as exc:  # ShapeError, or a block the reader refuses
            shape_of[base] = str(exc)
            desc.issues.append((node, "shape: %s" % exc))
    sh = shape_of[base]
    return None if isinstance(sh, str) else sh


def _curve(scene, desc, shape_of, unbuilt, base, node, name, offset, meters):
    """(kind, curve key) of a node whose base object is a shape: CURVE and its key in desc.curves, made on first
    use; EMPTY and None when the reader refuses the shape or its curve does not fit single precision (an issue,
    named on the first node of the key: unbuilt holds the keys refused). shape_of caches the reader's Shapes
    (small: knots, no arrays), whose issues are named once, on the first node."""
    sh = _shape(scene, desc, shape_of, base, node)
    if sh is None:
        return EMPTY, None
    offset = None if offset == controllers.IDENTITY else offset
    key = (base, offset)
    if key in unbuilt:
        return EMPTY, None
    cd = desc.curves.get(key)
    if cd is None:
        try:
            cd, issues = curve_description(key, name, sh, offset, meters)
        except CurveError as exc:
            unbuilt.add(key)
            desc.issues.append((node, "shape: not built: %s" % exc))
            return EMPTY, None
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


def _rim(converted):
    """The lowest converted Shell (a ModifierDescription) whose rim MaxDrop hardens as 3ds Max does (the mesh's open
    edges sharp): one without a smoother with Smooth Result above it (which smooths the rim too). None otherwise. A
    Shell above another meets a closed mesh: only the lowest makes a rim. The Mirrors below it: _mirrors."""
    for k, m in enumerate(converted):
        if m.kind == rules.SOLIDIFY:
            above = converted[k + 1:]
            return None if any(x.kind == rules.SUBSURF and x.shading == rules.SMOOTH for x in above) else m
    return None


def _mirrors(converted, shell):
    """The Mirrors (ModifierDescriptions) below Shell shell in converted, bottom first: the open edges they weld shut
    make no rim (welded())."""
    out = []
    for m in converted:
        if m is shell:
            break
        if m.kind == rules.MIRROR:
            out.append(m)
    return tuple(out)


def _reflection(mirror):
    """The 4x4 matrix (numpy, Blender's columns) that mirrors a point of the object's space as Mirror
    ModifierDescription mirror does: F S inverse(F), F the mirror object's matrix (the identity without one), S the
    flip of its axis."""
    import numpy
    f = numpy.identity(4) if mirror.mirror is None else numpy.asarray(mirror.mirror, dtype=numpy.float64)
    flip = numpy.diag([-1.0 if on else 1.0 for on in dict(mirror.settings)["use_axis"]] + [1.0])
    return f @ flip @ numpy.linalg.inv(f)


def welded(positions, mirror):
    """Whether each vertex (positions (V, 3), meters) merges with its copy under Mirror ModifierDescription mirror,
    bool (V,): with its weld on, Blender's Mirror welds a vertex closer than merge_threshold to its mirror image
    (half that to the plane)."""
    import numpy
    p = numpy.asarray(positions, dtype=numpy.float64).reshape(-1, 3)
    threshold = max(float(dict(mirror.settings)["merge_threshold"]), 0.0)  # Blender's hard minimum
    if not dict(mirror.settings)["use_mirror_merge"] or not threshold:
        return numpy.zeros(len(p), dtype=bool)
    r = _reflection(mirror)
    d = p - (p @ r[:3, :3].T + r[:3, 3])
    return numpy.einsum("ij,ij->i", d, d) < threshold * threshold


def _rim_edges(md, mirrors, check=None):
    """The open edges of MeshDescription md that make a rim above the Mirrors mirrors (_mirrors): all but those
    whose two ends a Mirror welds to their copies, the edge's own or one of its copies under the Mirrors below that
    one (the edge and its copy become one, with a face on each side; a copy carries the sharp mark). The copies
    tested stop doubling past MAX_MIRROR_IMAGES, or MAX_MIRRORED_CORNERS positions; check() between the Mirrors."""
    import numpy
    edges = open_edges(md.loop_vertices, md.loop_starts, md.loop_totals, check)
    if not mirrors or not len(edges):
        return edges
    ends = numpy.unique(edges)
    a, b = numpy.searchsorted(ends, edges[:, 0]), numpy.searchsorted(ends, edges[:, 1])
    images = numpy.asarray(md.positions, dtype=numpy.float64)[ends][None]  # (copies, ends, 3) made so far
    keep = numpy.ones(len(edges), dtype=bool)
    for m in mirrors:
        if check is not None:
            check()
        w = welded(images.reshape(-1, 3), m).reshape(len(images), len(ends))
        keep &= ~(w[:, a] & w[:, b]).any(axis=0)
        if 2 * len(images) <= MAX_MIRROR_IMAGES and 2 * images.size <= 3 * MAX_MIRRORED_CORNERS:
            r = _reflection(m)
            images = numpy.concatenate((images, images @ r[:3, :3].T + r[:3, 3]))
    return edges[keep]


def _mirrored(md, mirrors, check=None):
    """(positions, loop_vertices, loop_starts, loop_totals) of MeshDescription md and its copy under each Mirror of
    mirrors (_mirrors) in turn, the vertices it welds shared, each copy's faces reversed: the mesh the Shell above
    them meets, as far as its rim goes (no slice is made: md is taken as the part each Mirror keeps; a welded vertex
    stays where it is, Blender moves it half its distance to the plane). check() between the Mirrors."""
    import numpy
    p = numpy.asarray(md.positions, dtype=numpy.float64)
    lv = numpy.asarray(md.loop_vertices, dtype=numpy.int64)
    starts = numpy.asarray(md.loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(md.loop_totals, dtype=numpy.int64)
    for m in mirrors:
        if check is not None:
            check()
        n = len(p)
        r = _reflection(m)
        w = welded(p, m)
        index = numpy.where(w, numpy.arange(n), n + numpy.arange(n))
        copy = index[lv[_reversed_loops(starts, totals)]]
        p = numpy.concatenate((p, p @ r[:3, :3].T + r[:3, 3]))
        starts = numpy.concatenate((starts, starts + len(lv)))
        lv = numpy.concatenate((lv, copy))
        totals = numpy.concatenate((totals, totals))
    return p, lv, starts, totals


def rim_issues(md, rim, check=None, mirrors=()):
    """What Blender's Solidify does not do of a Shell's RimRule on MeshDescription md (none when md has no open
    edge): auto smooth splitting the rim's sharper corners (rim_corners, on the mesh below the modifiers: a
    TurboSmooth below the Shell keeps a plane's four corners, 1 to 3 iterations in 3ds Max 2020), the override group
    with auto smooth off (3ds Max merges the rim into faces along it of that group; named whatever the groups of
    those faces). Above the Mirrors mirrors (_mirrors) the open edges they weld shut make no rim (_rim_edges) and
    the corners are counted on md with its copies (_mirrored), unless that mesh would pass MAX_MIRRORED_CORNERS face
    corners (a line instead). check() between the passes."""
    if rim is None:
        return []
    if mirrors and not len(_rim_edges(md, mirrors, check)):
        return []
    if rim.auto_smooth:
        if mirrors and len(md.loop_vertices) << len(mirrors) > MAX_MIRRORED_CORNERS:
            return ["auto smooth: the rim's corners not counted: with its copies under %d Symmetries the mesh would "
                    "pass %d face corners" % (len(mirrors), MAX_MIRRORED_CORNERS)]
        mesh = _mirrored(md, mirrors, check) if mirrors else (md.positions, md.loop_vertices, md.loop_starts,
                                                               md.loop_totals)
        n = rim_corners(*mesh, rim.angle, check)
        return ["auto smooth: %d corners of the rim sharper than %g degrees shade smooth (3ds Max splits the rim "
                "there)" % (n, rim.angle)] if n else []
    if rim.override is None or not (mirrors or len(_open_loops(md.loop_vertices, md.loop_starts, md.loop_totals,
                                                                check)[0])):
        return []
    return ["smoothing group override (group %d) not converted: 3ds Max merges the rim into the faces along it of "
            "that group" % rim.override]


def _name_rim(desc, rims, shell, key, node, check=None, mirrors=()):
    """The rim issues of Shell shell (a ModifierDescription or None) above the Mirrors mirrors (_mirrors) on mesh
    key, on node: once per Shell and mesh."""
    if shell is None or (shell.index, key) in rims:
        return
    rims.add((shell.index, key))
    md = desc.meshes[key]
    desc.issues.extend((node, "modifiers: %s: %s" % (shell.class_name or "Shell", x))
                       for x in rim_issues(md, shell.rim, _large(md, check), mirrors))


def _large(md, check):
    """check for the passes over md when it has more than reader.geometry.CHECK_EVERY face corners, else None (the
    call counts of a small mesh stay once per node, as in mesh_description)."""
    return check if check is not None and len(md.loop_vertices) > geometry.CHECK_EVERY else None


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


def _mapped_mesh(scene, desc, mapped, key, data, maps, node, name, offset, meters, shading=None, check=None,
                 rim=False, mirrors=(), ranges=None, refusal="geometry: not built"):
    """(the key in desc.meshes of reader MeshData data under the UVW Maps maps, the maps applied), made on first use:
    key extended by (modifier index, context matrix) per UVW Map evaluated, then by ("shading", shading) when a
    converted smoother changes the shading (SMOOTH: no sharp edge or flat face; CREASE: the sharp edges creased),
    then by ("rim", True) when a converted Shell's rim is hardened (_rim): the open edges join the sharp ones. Above
    the Mirrors mirrors (_mirrors), ("rim", their settings and mirror matrices) instead, and the open edges they
    weld shut stay smooth (_rim_edges): marked sharp, the weld would make them a hard seam. check goes to
    mesh_description. (None, ()) when its positions do not fit single precision (MeshError: an issue), found before
    any UVW Map is read (the maps, the shading and the rim leave the positions as they are); ranges caches per key
    as given whether they fit, a refusal (its issue starts with refusal) then named on the first node only."""
    if ranges is not None and key in ranges:
        if not ranges[key]:
            return None, ()
    else:
        fits = True
        try:
            _positions(data, offset, meters)  # checked before the maps so a refused mesh gets no UVW Map issue
        except MeshError as exc:
            desc.issues.append((node, "%s: %s" % (refusal, exc)))
            fits = False
        if ranges is not None:
            ranges[key] = fits  # a flag: a kept MeshError's traceback would hold the refused mesh in memory
        if not fits:
            return None, ()
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
    if rim:
        key = key + (("rim", tuple((m.settings, m.mirror) for m in mirrors) or True),)
    md = desc.meshes.get(key)
    if md is None:
        done = []
        for m, (params, tm) in usable:
            try:
                data = uvwmap.apply(data, params, tm, m.context.tm)
                done.append(m)
            except uvwmap.UVWMapError as exc:
                desc.issues.append((node, "uvw map: %s: the stored channel stays" % exc))
        md = desc.meshes[key] = mesh_description(key, name, data, offset, meters, check)
        md.applied = tuple(done)
        if shading == rules.SMOOTH:
            md.sharp_faces[:] = False
            md.sharp_edges = md.sharp_edges[:0]
        if rim:
            md.sharp_edges = _merged_edges(md.sharp_edges, _rim_edges(md, mirrors, _large(md, check)))
        md.creases = shading == rules.CREASE
        if md.dropped_faces:
            desc.issues.append((node, "geometry: %d faces with a repeated vertex or doubled, left out"
                                % md.dropped_faces))
        _name_zeroed(desc, md, node)
    md.users.append(node)
    return key, md.applied


def _name_zeroed(desc, md, node):
    """The issue of the UV coordinates of MeshDescription md that were not numbers, on node (none when there were
    none)."""
    if md.zeroed_uvs:
        desc.issues.append((node, "geometry: %d UV coordinates that are not numbers set to 0" % md.zeroed_uvs))


def _extruded(scene, desc, extrusions, mapped, base, ext, maps, node, name, offset, meters, shading=None, check=None,
              rim=False, mirrors=(), ranges=None):
    """(the key in desc.meshes of shape base under the Extrude ext and the UVW Maps maps, the maps applied), made on
    first use; (None, ()) when the shape or the Extrude cannot be read or the scene's MAX_BUILT_CORNERS are spent (an
    issue, once per base object and Extrude: _Extrusions), or when its positions do not fit single precision
    (_mapped_mesh, which gets ranges; the shape is then drawn as a curve)."""
    data = extrusions.get(base, ext, node)
    if isinstance(data, tuple):
        kind, text = data
        if kind != _SHAPE_KIND and extrusions.tell(base, ext):  # a refused shape: _shape named it
            desc.issues.append((node, "extrude: " + ("not made: " + text if kind == _SPENT_KIND else text)))
        return None, ()
    offset = None if offset == controllers.IDENTITY else offset
    return _mapped_mesh(scene, desc, mapped, (base, offset, ext.index), data, maps, node, name, offset, meters,
                        shading, check, rim, mirrors, ranges, "extrude: not made")


_SHAPE_KIND, _SPENT_KIND, _EXTRUDE_KIND = "shape", "spent", "extrude"  # why _Extrusions did not make one
_DROPPED = "dropped"  # an extrusion made, named and counted, whose MeshData is gone


class _Extrusions:
    """The extrusions of one scene's shapes, one per (shape base object, Extrude modifier index), shared by the shape's
    own nodes (_extruded) and the mesh lights that pick it (_emitter_shape): made, its shape and Extrude issues named
    (on the node that makes it) and its face corners counted against MAX_BUILT_CORNERS once. drop() lets the MeshData
    go once no node needs it; a mesh light after that gets the same mesh made again, naming and counting nothing.
    Mesh lights that pick one shape share its count as nodes of the shape at different offsets do (each still gets a
    mesh of its own in desc.meshes). A shape a mesh light reads first and the reader refuses is not kept in shape_of:
    the shape's own node reads it again and names the refusal (_shape), where a user looks for it. shape_of: the
    scene's reader Shapes (_shape); built: [face corners made so far]."""

    def __init__(self, scene, desc, shape_of, built):
        self.scene, self.desc, self.shape_of, self.built = scene, desc, shape_of, built
        self.made = {}  # base -> {Extrude index: MeshData, _DROPPED or (kind, text) why it is not made}
        self.told = set()  # (base, Extrude index) whose refusal a shape's node named

    def get(self, base, ext, node, light=False):
        """The reader MeshData of shape base under the Extrude ext (a reader Modifier) for node (light: a mesh light's),
        or (kind, text) why it is not made: _SHAPE_KIND (the shape is refused; text its reason), _SPENT_KIND
        (MAX_BUILT_CORNERS; text says so) or _EXTRUDE_KIND (the Extrude cannot be read or made)."""
        cache = self.made.setdefault(base, {})
        found = cache.get(ext.index)
        if found is None:
            found = cache[ext.index] = self._make(base, ext, node, light)
        elif found is _DROPPED:
            try:
                found, _issues = extrude.extrude(self.shape_of[base], extrude.read_params(self.scene, ext)[0])
            except ChunkError as exc:  # it did not fail the first time; a refusal all the same
                found = (_EXTRUDE_KIND, str(exc))
        return found

    def _make(self, base, ext, node, light):
        if light and base not in self.shape_of:
            try:
                sh = shapes.read_shape(self.scene, base)
            except ChunkError as exc:  # not kept: the shape's own node reads it again and names it
                return _SHAPE_KIND, str(exc)
            self.shape_of[base] = sh
            self.desc.issues.extend((node, "shape: %s" % x) for x in sh.issues)
        else:
            sh = _shape(self.scene, self.desc, self.shape_of, base, node)
        if sh is None:
            return _SHAPE_KIND, self.shape_of[base]
        if self.built[0] >= MAX_BUILT_CORNERS:
            return _SPENT_KIND, _SPENT % MAX_BUILT_CORNERS
        try:
            params, issues = extrude.read_params(self.scene, ext)
            data, more = extrude.extrude(sh, params)
        except ChunkError as exc:  # ExtrudeError, or a block the reader refuses
            return _EXTRUDE_KIND, str(exc)
        self.built[0] += len(data.loop_vertices)
        self.desc.issues.extend((node, "extrude: %s" % x) for x in issues + more)
        return data

    def tell(self, base, ext):
        """Whether a shape's node is the first to meet the refusal of base under ext (it names it then)."""
        key = (base, ext.index)
        if key in self.told:
            return False
        self.told.add(key)
        return True

    def drop(self, base):
        """The MeshData of base's extrusions let go; what they were (made, or why not) stays known."""
        cache = self.made.get(base, {})
        for index, found in cache.items():
            if not isinstance(found, tuple):
                cache[index] = _DROPPED


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


def read(path, meters=None, convert_modifiers=True, files=None):
    """The SceneDescription of a .max file. meters None: the file's system unit, 1.0 when it does not say;
    convert_modifiers and files as describe's."""
    with cfb.CompoundFile(path) as cf:
        sc = reader_scene.Scene.from_file(cf)
        unit = units.system_unit(sc)
        if meters is None:
            meters = unit.meters if unit is not None else 1.0
        return describe(sc, meters, unit, convert_modifiers, reader_assets.AssetTable.from_file(cf),
                        cameras.saved_views(cf), files=files)
