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
reads it); describe(..., files), a convert.textures.TextureIndex, finds the IES file of a VRayIES or a photometric
web light, read once per file (convert.ies.Lookup): the light's profile, and a VRayIES's power when it depends on it;
without it the power is taken as the flux (an issue) and no light has a profile.

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
mesh has open edges. A Symmetry right above the lowest Shell (only Symmetries converted below it) whose slice plane
holds the mesh's open edges drops the rim the Shell made there in 3ds Max and welds the cut: where that rim lies on
the plane (lowered()), its Mirror is moved below the Solidify (node.converted is in Blender's order), which welds the
cut before the shell is made, and the rim is that of the Mirrors below; otherwise an issue. ("seam", the Mirrors
below the Shell, those right above it) joins the mesh key before its shading entry. Viewport levels that would give
an object more than convert.modifiers.MAX_VIEWPORT_CORNERS face corners are lowered (an issue).
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

from ...reader import assets as reader_assets
from ...reader import cfb, chunks, classids, controllers, geometry, modifiers as reader_modifiers, shapes, units
from ...reader import scene as reader_scene
from .. import cameras, colors, extrude, ies, lights, modifiers as rules, primitives, uvwmap

from .descriptions import (
    MESH, CURVE, EMPTY, LIGHT, CAMERA, EMITTER, ADAPTIVE, UV_FIRST, UV_NAME, MAX_EDGE_MASKS, MAX_BUILT_CORNERS,
    MAX_MIRRORED_CORNERS, MAX_MIRROR_IMAGES, PLANE_TOLERANCE, BISECT_DISTANCE, NORMAL_TOLERANCE, SEAM_STAYS,
    SEAM_UNTESTED, _SPENT, SHEAR_TOLERANCE, OFFSET, NO_RECEIVE, ENVIRONMENT, ChunkError, CurveError, MeshError,
    Cancelled, _raising, NodeDescription, LookAtDescription, _TRACK, NO_TRACK_ROLL, NO_TRACK_AXIS, look_at_description,
    MeshDescription, SplineDescription, CurveDescription, LayerDescription, SceneDescription, blender_matrix,
    determinant3,
)
from .meshes import (
    sharp_edges, open_edges, _open_loops, _merged_edges, rim_corners, _disjoint, mesh_area, valid_faces,
    _reversed_loops, _positions, mesh_description,
)
from .curves import _straight, segment_ids, curve_description, rectangular_section, _fits, _flat, sheared
from .nodes import _dome, _light, _camera, _primitive, _shape, _curve
from .emitters import _emitter, _emitter_mesh, _active, _emitter_rest, _emitter_shape, _source_object, _mesh_of
from .stack import (
    _evaluated, _offset, _converted, _split, _mapping, _mapped_mesh, _name_zeroed, _extruded, _SHAPE_KIND, _SPENT_KIND,
    _EXTRUDE_KIND, _DROPPED, _Extrusions, _layer, _layer_descriptions, _class_name,
)
from .rims import (
    _shading, _rim, _mirrors, _seam, _lowered, _unit, _reflection, welded, _rim_edges, _mirrored, _mirror_once,
    _face_normals, lowered, rim_issues, _name_rim, _rim_mirrors, _name_seam, _large,
)
from .walk import describe, read
