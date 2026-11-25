# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scene description: kinds, limits, errors, the description dataclasses and the axis conversion."""
import collections

from ...reader import chunks


MESH, CURVE, EMPTY, LIGHT, CAMERA = "MESH", "CURVE", "EMPTY", "LIGHT", "CAMERA"
EMITTER = "emitter"  # an emitter mesh's key: (EMITTER, light base, mesh base object index, the light node's offset)
ADAPTIVE = 12  # Blender's default curve resolution, for a shape 3ds Max interpolates adaptively
UV_FIRST = "UVMap"
UV_NAME = "UVChannel_%d"
MAX_EDGE_MASKS = 64  # distinct smoothing-group masks paired on one non-manifold edge
# Face corners the primitives and extrusions of one scene may make: each has its own cap (primitives.MAX_CORNERS,
# extrude.MAX_VERTICES), but a file can hold any number of them, each costing up to about a second and hundreds of
# MB (an adaptive Extrude several seconds, also when it is refused: ExtrudeError.spent counts it). Checked before
# each is made, so the last one made can pass it by up to its own cap.
MAX_BUILT_CORNERS = 1 << 24
# Face corners of a mesh with its copies under the Mirrors below a Shell, counted for the rim's corners (each Mirror
# doubles them): past it the corners are not counted (a line in the report)
MAX_MIRRORED_CORNERS = 1 << 22
MAX_MIRROR_IMAGES = 64  # copies of the open edges tested against the next Mirror below a Shell (_rim_edges)
# 3ds Max 2020's slice drops the rim faces of a Shell below it lying within this many system units of its plane
# (1e-4 off: dropped; 1e-3 off: kept, doubled; lowered()). Positions are float32: some 1000 units from the origin
# along the plane's axis one step passes it, and such a cut keeps the order
PLANE_TOLERANCE = 1e-4
# Blender's Mirror keeps a vertex this close to the plane (meters, bisect_threshold's default) on the kept side: in
# files of large units the on-plane test stays within it, so a moved Mirror cuts no end of the cut away
BISECT_DISTANCE = 1e-3
# |cos| between a face's normal and a plane's axis: a face at the plane offset along it by a Shell up to 10 units
# thick stays within PLANE_TOLERANCE of the plane
NORMAL_TOLERANCE = 1e-5
SEAM_STAYS = ("the rim of the Shell below it along the mirror plane differs from 3ds Max's: the Mirror is moved below "
              "the Solidify only for a rim lying on the plane, with slice and weld on")
SEAM_UNTESTED = ("whether the rim of the Shell below it lies on the mirror plane is not tested (with its copies the "
                 "mesh would pass %d face corners): where it does, it differs from 3ds Max's" % MAX_MIRRORED_CORNERS)
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
    set to 0; lowered how many Mirrors right above its Shell go below it, seam_issue why the next one does not when
    it may leave a rim on its plane (SEAM_STAYS, SEAM_UNTESTED or None: lowered())."""
    __slots__ = ("key", "name", "positions", "loop_vertices", "loop_starts", "loop_totals", "material_indices",
                 "sharp_faces", "sharp_edges", "uv_layers", "users", "dropped_faces", "applied", "creases",
                 "zeroed_uvs", "lowered", "seam_issue")

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
        self.lowered, self.seam_issue = 0, None

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
