# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fixture tests of the new pipeline inside Blender: every tests/fixtures/*.max imported through the operator
(import_scene.maxdrop, default options: Units Auto), compared with its 3ds Max oracle
(tests/fixtures/<name>.oracle.json) and with convert.scene.read of the same file.

Run headless with an isolated profile so your own preferences are never touched:
  $env:BLENDER_USER_RESOURCES="<scratch>\\profile"
  & blender --background --factory-startup --python-exit-code 1 --python tests\\blender\\run.py [-- <file.max> ...]

Per fixture, into an emptied scene, below a collection named after the file with one collection per layer
(build.collections), objects found by node name (objects are made in walk order, so the second node of a name is
"<name>.001" in the emptied scene): node order and names, parents, each object in its layer's collection, the oracle's
hidden, renderable and frozen flags, world matrices (1e-4, in file units), world bounding boxes of the meshes (1e-3),
vertex and face counts, UV layers, sharp edges and flat faces, material indices, which objects share a mesh (the
oracle's instances), outward normals as rendered (the inverse transpose of the world matrix times each face normal
points away from the oracle's bounding box center, also on the mirrored object) and the class of each placeholder. The
oracle has no map channels or smoothing groups of a base mesh: those expectations come from the fixture scripts
(tools/fixtures/*.ms).
Each mesh and curve object casts shadows (visible_shadow) as the oracle's cast_shadows says; layers_flags:
FixtureNoCastShadow is the one that casts none.
shapes: each shape node a curve object (3D, FREE handles) with the oracle's splines, point counts and cyclic flags,
its points where 3ds Max has its knots, each segment's middle (mathutils.geometry.interpolate_bezier) where 3ds Max
interpolates it (the straight segment included), the resolution from the steps, a bevel and faces only on the
renderable FixtureLine, its open spline capped at both ends (the polygon of its sides), its closed one not.
shapes_more: the same for its NGon corners, Ellipse outlines and Arcs; a rectangular section
a hidden bevel object in the import's collection, its corners where 3ds Max's render mesh has them; FixtureCurveStd's
Standard material and FixtureCurveMulti's Multi/Sub-Object entry for ID 1 in one slot on their curves,
FixtureCurveIds' two splines (IDs 2 and 1) each on the slot of its entry, FixtureCurveMixed (IDs 2, 1, 1) on ID 2's,
no slot on the other curves; on every fixture each spline's material index is its slot.
Converted modifiers (TurboSmooth, MeshSmooth, Shell, Symmetry): each object's Blender modifiers in the converted order
(3ds Max's, but a Symmetry moved below the Shell whose rim lies on its plane) with the description's settings and
mirror empties, creases where a smoother separates by smoothing groups (none on open
edges), and the evaluated mesh with 3ds Max's vertex and triangle counts, world box and shading (flat faces, smooth
regions and hard edges, the oracle's eval_mesh.smoothing; SMOOTHING_DIFFERS pins Blender's where it differs: two
Shell rims, a weld); under a Solidify its triangles facing up, down and sideways in object space as 3ds Max's
(stack_shell: Shells on one side of the original and inside out, their rims) (stack_convert, stack_shell,
stack_basic, modifier_pivot; not FixtureOrder, whose seam 3ds Max leaves unwelded, nor FixtureShellUnderSymNoWeld,
whose cut it leaves open: EVAL_COUNT_DIFFERS); stack_convert
imported with Modifiers: Ignore gets none.
primitives (convert/primitives/): each node a mesh with 3ds Max's vertex and triangle counts (eval_verts, eval_faces)
and world box, its UV layer (none without Generate Mapping Coords), sharp edges, the unsmoothed GeoSphere flat, normals
outward but for the Planes (up, or down for the one of negative width) and the Box of negative width (in, as 3ds Max
makes it); the instance shares FixtureBox's mesh; the TurboSmooth over a Box evaluates to 3ds Max's counts.
layers_flags: two layer collections, one hidden object, one with hide_render, the group head as the parent of its two
members. layers_more: the hidden layer's collection excluded, hide_select on the frozen layer's, no hide_render on the
non-rendering layer's (its By Object node renders, as in 3ds Max), the child layer's collection below its parent's
(which holds no node), the non-ASCII layer name, only the nodes' own flags on objects, the hidden parent's child
visible. layers_render: no collection with hide_render; the By Layer nodes render and cast shadows as their own
layers say (FixtureByLayerNoRender hide_render, FixtureByLayerNoCast no shadow), the By Object nodes on those layers
as their own. modifier_pivot: a node with modifiers gets its base mesh (no bounding box check, the oracle's is after the
modifiers), the report names the modifiers not applied, and the node whose pivot alone is rotated keeps its object
in place. lookat: the nodes aimed by a Look At controller or a LookAt Constraint have 3ds Max's world matrices (above),
the Target objects are empties; imported again with Keep Targets, each Look At a Track To can follow gets one aimed at
its target's object, with the same evaluated world matrix, and the report names the two it cannot follow (a roll, the
Y axis). vray_lights: each VRayLight node a light object (mesh and dome lights empties, the dome the World), its light
of the description's type, shape and size and of the shape the fixture script made, its -Z axis along the oracle's, its
energy the watts 3ds Max computed with the rules source's function times the default Light Strength (the disc's 4 / pi,
the double-sided plane's half), its color, the off light hidden in viewport and render, the invisible one unseen by
the camera and glossy rays; the instance shares the plane's light, the disc's instance scaled 2, 1.5, 1 has its
own, three times as strong; FixtureNoShadow's light casts no shadows (its own Cast shadows off), the others
do; imported again with Light Strength 2, twice the
power. vray_dome: the dome is the scene's World (its texture image, strength, hemisphere, the Mapping rotations
that look its texels up where V-Ray does, camera visibility off), the report's World line, the World before it
kept with a fake user; the second dome an empty; the spheres' radii and powers (X scale only);
undo() after the run, and a build that fails after the World, put the World before back (no fake user) and remove
the new one; a World that cannot be built leaves the scene imported, a line in the report; of two files with a dome
the first gives the World. vray_mesh_light and vray_dome's mesh light: each emitter a mesh object of its mesh at the
light's place (EMITTER_BOXES), its only material an Emission of the radiance V-Ray gives it (EMITTER_RADIANCE)
times the Light Strength, one side through a Backfacing mix (flipped for Flip normals) or both, its camera, shadow,
diffuse and glossy visibility; the mesh light without a mesh an empty; FixtureEmitterOwn's Shell a Solidify of 2 mm
on its emitter, the radiance spread over the shelled area, measured the same with the emitter hidden or its
collection excluded. lights_standard, lights_photometric (and lookat's
target spot): each light of the type, spot cone, power and color of the rules (STOCK_LIGHTS), its -Z axis along the
oracle's, its flags, its shadow switch (STOCK_SHADOWS); the Skylight an empty.
Cameras (cameras, lookat): each camera node a camera object of the description's type, sensor fit HORIZONTAL, sensor,
lens, shift, clipping and orthographic width, Blender's horizontal field of view (angle_x) within 0.05 degrees of 3ds
Max's (the oracle's EvalCameraState), depth of field off, its -Z axis and +Y up along the oracle's; cameras' shifts and
sensors from its script (CAMERA_SHIFTS, CAMERA_SENSORS). A fixture with a camera: the scene's render size is the
oracle's, and scene.camera the oracle's render camera (cameras: CamTarget, the locked render view) or else the first
camera (lookat: FixtureCam); cameras holds eleven camera objects with a Camera each. Without a camera the scene's render
size and camera stay as they were.
Each fixture's import report is published (build.report) and must say nothing was left out; the one the
operator published for vray_wrappers lists its two peeled wrappers by class (its VRayBlendMtl's coats are layers). layers_nested: the objects below a
hidden parent layer (one and two levels down) are out of the view layer, the one below a frozen parent layer cannot
be selected, as the oracle's inherited layer flags say; only the flagged layers' own collections carry a flag.
A hand-made
description with sheared local matrices (top-level and parented, hidden, a zero scale) checks that Blender's world
matrices equal the products of the locals, through the helper empty for top-level ones; controllers' FixtureScaleAxis
(a scale along a turned axis) is such a top-level node in a fixture. Material
slots (build with convert.materials.assign): vray_wrappers' Multi/Sub-Object box with its faces set to IDs 1, 3
and 7 lands them on the slots of FixtureSubOne, an empty one (ID 3 is switched off) and FixtureSubSeven; the same
mesh shared with the Shell box gets slots linked to each object; standard_physical's boxes one slot each;
shapes_more's FixtureCurveStd and FixtureCurveMulti made to share one curve get one empty slot on it, linked to each
object with its own material, and FixtureBox given FixtureCurveRed shares that Blender material with the curve.
Materials (build.materials through the operator): each face on its material's slot, each slot's material named after
the 3ds Max material, its Principled inputs equal to the MaterialIR the same file converts to (values, or linked when
a texture graph drives them), the render method, one Image Texture node per file; pblock_animated's animated diffuse
and glossiness at their frame-0 values (not the class defaults); vray_maps' Mapping values by hand
from its authoring script, texture nodes without an image and each missing file listed once by name; vray_maps,
texmap_rules, corona_maps, corona_light, vray_texmaps, texmap_wrappers and falloff_curve copied beside generated
PNGs load every image in its color space, one datablock per file and color space, the report counts every file as
found (and texmap_wrappers draws each wrapper with its nodes: Layer Weight, Fresnel, blend types, Separate / Combine
Color; falloff_curve each Falloff curve as a Float Curve that evaluates as 3ds Max's, each Mix's Use Curve;
untextured, FixtureCurveJump's two points at one x in the convert side's order, a masked Mix at its amount
through the curve);
hand-made IRs check shared images, a missing file, the materials counted by class, Thin Wall (set on 5.x, counted on
4.x), a name clash, BLENDED / DITHERED and every node kind, the wrappers' links and values (Facing, blend modes and
masks, rewiring, Adjust, Tint), layers mixed by a Mix Shader and added layers by an Add Shader over a Mix Shader from
nothing (VRayBlendMtl's additive coats); a crop repeating per axis (wrap, ping-pong, clip), a mirrored axis drawn as
3ds Max renders it (two copies per tile, the nodes evaluated at its sample points), map channel 0 drawn on
channel 1 and reported, a texture file without image data reported, a material whose build raises removed and
reported; a material conversion that raises leaves the scene imported without materials, the report says why.
A normal map over a clipped image reads it black outside the image, never mixed toward flat, as 3ds Max renders it.
Images already in the file (an earlier import's) are reused by file and color space, unless modified, packed,
generated or linked from a library; vray_maps imported twice with its textures adds no image the second time.
lights_photometric copied beside a self-authored fixture_web.ies (rated 500 lm, 100 cd everywhere): IesPower,
IesOverride and PhWeb shine with it, point lights sharing one Text, of the flux they shed (EEVEE's plain light) times
the node's Strength, together the file's candelas times 3, 300 / 400 pi and 4 (x 0.2604 W x Light Strength, over
4.x's one-plane gain), no rated-lumens line in the report; through the run's steps,
undo() and a build that fails after the lights leave no Text. Hand-made IES lights: one IES Texture of the profile's
Text into the Emission's Strength, one Text per file, no node without a profile.
The same beside filler files with a texture walk of 2 entries: IesPower takes its power as its flux and its line says
where the search stopped, as the report does once, with materials and without.
compat.light_nodes gives a new point and spot light its tree with an Emission linked into the Light Output, the same
nodes on a second call, both back in an emptied tree.
The performance budget of one big mesh (tests/blender/bench.py) runs last, without file arguments.
Prints `FIXTURES PASSED` (exit 0) or `FIXTURES FAILED` (exit 1).
"""
import os
import sys
import traceback
import types

# The parts of the fixture tests are modules of a package of their own whose path is this folder (tests/blender).
_PARTS = "maxdrop_fixture_tests"
if _PARTS not in sys.modules:
    _parts = types.ModuleType(_PARTS)
    _parts.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_PARTS] = _parts
from maxdrop_fixture_tests.core import failures  # noqa: E402 (after the loader)
from maxdrop_fixture_tests.suite import main  # noqa: E402 (after the loader)


try:
    main()
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FIXTURES FAILED: %s" % ", ".join(failures) if failures else "FIXTURES PASSED")
sys.stdout.flush()
sys.exit(1 if failures else 0)
