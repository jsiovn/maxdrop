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
renderable FixtureLine. shapes_more: the same for its NGon corners, Ellipse outlines and Arcs; a rectangular section
a hidden bevel object in the import's collection, its corners where 3ds Max's render mesh has them; FixtureCurveStd's
Standard material and FixtureCurveMulti's Multi/Sub-Object entry for ID 1 in one slot on their curves,
FixtureCurveIds' two splines (IDs 2 and 1) each on the slot of its entry, FixtureCurveMixed (IDs 2, 1, 1) on ID 2's,
no slot on the other curves; on every fixture each spline's material index is its slot.
Converted modifiers (TurboSmooth, MeshSmooth, Shell, Symmetry): each object's Blender modifiers in 3ds Max's order with
the description's settings and mirror empties, creases where a smoother separates by smoothing groups (none on open
edges), and the evaluated mesh with 3ds Max's vertex and triangle counts, world box and shading (flat faces, smooth
regions and hard edges, the oracle's eval_mesh.smoothing; SMOOTHING_DIFFERS pins Blender's where it differs: two
Shell rims, a weld); under a Solidify its triangles facing up, down and sideways in object space as 3ds Max's
(stack_shell: Shells on one side of the original and inside out, their rims) (stack_convert, stack_shell,
stack_basic, modifier_pivot; not FixtureOrder, whose seam 3ds Max leaves unwelded: EVAL_COUNT_DIFFERS); stack_convert
imported with Modifiers: Ignore gets none.
primitives (convert/primitives.py): each node a mesh with 3ds Max's vertex and triangle counts (eval_verts, eval_faces)
and world box, its UV layer (none without Generate Mapping Coords), sharp edges, the unsmoothed GeoSphere flat, normals
outward but for the Planes (up, or down for the one of negative width) and the Box of negative width (in, as 3ds Max
makes it); the instance shares FixtureBox's mesh; the TurboSmooth over a Box evaluates to 3ds Max's counts.
layers_flags: two layer collections, one hidden object, one with hide_render, the group head as the parent of its two
members. layers_more: the hidden layer's collection excluded, hide_select on the frozen layer's, hide_render on the
non-rendering layer's, the child layer's collection below its parent's (which holds no node), the non-ASCII layer
name, only the nodes' own flags on objects, the hidden parent's child visible. modifier_pivot: a node with modifiers gets its base mesh (no bounding box check, the oracle's is after the
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
kept with a fake user; the second dome and the mesh light empties; the spheres' radii and powers (X scale only);
undo() after the run, and a build that fails after the World, put the World before back (no fake user) and remove
the new one; a World that cannot be built leaves the scene imported, a line in the report; of two files with a dome
the first gives the World. lights_standard, lights_photometric (and lookat's target spot): each light of the type,
spot cone, power and color of the rules (STOCK_LIGHTS), its -Z axis along the oracle's, its flags, its shadow switch (STOCK_SHADOWS);
the Skylight an empty.
Cameras (cameras, lookat): each camera node a camera object of the description's type, sensor fit HORIZONTAL, sensor,
lens, shift, clipping and orthographic width, Blender's horizontal field of view (angle_x) within 0.05 degrees of 3ds
Max's (the oracle's EvalCameraState), depth of field off, its -Z axis and +Y up along the oracle's; cameras' shifts and
sensors from its script (CAMERA_SHIFTS, CAMERA_SENSORS). A fixture with a camera: the scene's render size is the
oracle's, and scene.camera the oracle's render camera (cameras: CamTarget, the locked render view) or else the first
camera (lookat: FixtureCam); cameras holds eleven camera objects with a Camera each. Without a camera the scene's render
size and camera stay as they were.
Each fixture's import report is published (build.report) and must say nothing was left out; the one the
operator published for vray_wrappers lists its three peeled wrappers by class. layers_nested: the objects below a
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
a texture graph drives them), the render method, one Image Texture node per file; vray_maps' Mapping values by hand
from its authoring script, texture nodes without an image and each missing file listed once by name; vray_maps,
texmap_rules, corona_maps, corona_light, vray_texmaps, texmap_wrappers and falloff_curve copied beside generated
PNGs load every image in its color space, one datablock per file and color space, the report counts every file as
found (and texmap_wrappers draws each wrapper with its nodes: Layer Weight, Fresnel, blend types, Separate / Combine
Color; falloff_curve each Falloff curve as a Float Curve that evaluates as 3ds Max's, each Mix's Use Curve);
hand-made IRs check shared images, a missing file, the materials counted by class, Thin Wall (set on 5.x, counted on
4.x), a name clash, BLENDED / DITHERED and every node kind, the wrappers' links and values (Facing, blend modes and
masks, rewiring, Adjust, Tint); a crop repeating per axis (wrap, ping-pong, clip), a mirrored axis drawn as
3ds Max renders it (two copies per tile, the nodes evaluated at its sample points), map channel 0 drawn on
channel 1 and reported, a texture file without image data reported, a material whose build raises removed and
reported; a material conversion that raises leaves the scene imported without materials, the report says why.
Images already in the file (an earlier import's) are reused by file and color space, unless modified, packed,
generated or linked from a library; vray_maps imported twice with its textures adds no image the second time.
lights_photometric copied beside a self-authored fixture_web.ies (rated 500 lm, 100 cd everywhere): IesPower's energy
is 1500 x 400 pi / 500 / 683 W x Light Strength, IesOverride's stays 300 / 683 W, no rated-lumens line in the report.
The performance budget of one big mesh (tests/blender/bench.py) runs last, without file arguments.
Prints `FIXTURES PASSED` (exit 0) or `FIXTURES FAILED` (exit 1).
"""
import collections
import glob
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
import traceback

import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import interpolate_bezier

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MATRIX_TOLERANCE = 1e-4
BBOX_TOLERANCE = 1e-3
UV_LAYERS = {  # mapcoords:true in the script gives channel 1; kept literal: test_convert_scene reads it with ast
    "arc_pie_reverse": ["UVMap"],  # every Extrude with Generate Mapping Coords; the two plain arcs are curves
    "box_poly_standard": ["UVMap"],
    "corona_layered": ["UVMap"],
    "corona_mix_blends": ["UVMap"],
    "corona_mix_ops": ["UVMap"],
    "corona_more": ["UVMap"],
    "corona_legacy": ["UVMap"],
    "corona_light": ["UVMap"],
    "corona_maps": ["UVMap"],
    "corona_physical": ["UVMap"],
    "editable_mesh": ["UVMap"],
    "falloff_curve": ["UVMap"],
    "extrude": [],  # per mesh: EXTRUDE_UV_LAYERS
    "gamma_swatches": ["UVMap"],
    "hierarchy": [],
    "instances": ["UVMap"],
    "layers_flags": [],
    "layers_more": [],
    "layers_nested": [],
    "lookat": [],  # boxes without Generate Mapping Coords
    "modifier_pivot": ["UVMap"],  # FixtureBent's UVW Map writes channel 1 (applied, the Bend above it is not)
    "multi_uv": ["UVMap", "UVChannel_2", "UVChannel_3"],
    "pblock_animated": ["UVMap"],
    "primitives": {"FixtureBoxNoMap": []},  # else UVMap: Generate Mapping Coords
    "shapes": ["UVMap"],  # FixtureBox; the shapes are curves
    "shapes_more": ["UVMap"],  # FixtureBox; the shapes are curves
    "stack_basic": ["UVMap"],  # FixtureTurbo's UVW Map writes channel 1; no other modifier is applied
    "stack_convert": ["UVMap"],  # the modifiers become Blender modifiers on the base meshes
    "stack_shell": ["UVMap"],  # the Shells become Solidify on the base meshes (open boxes)
    "stack_wsm": ["UVMap"],  # FixtureWSM's UVW Map writes channel 1; the Map Scaler bindings are not applied
    "standard_physical": ["UVMap"],
    "standard_shaders": ["UVMap"],
    "standard_maps": ["UVMap"],
    "saved_as_2017": ["UVMap"],
    "saved_as_2018": ["UVMap"],
    "saved_as_2019": ["UVMap"],
    "texmap_rules": ["UVMap"],
    "texmap_wrappers": ["UVMap"],
    "units_cm": ["UVMap"],
    "units_in": ["UVMap"],
    "units_mm": ["UVMap"],
    "vray_basic": ["UVMap"],
    "vray_maps": ["UVMap"],
    "vray_texmaps": ["UVMap"],
    "vray_more": ["UVMap"],
    "vray_lights": [],  # lights and a target: no mesh
    "vray_dome": [],  # lights and a box without Generate Mapping Coords
    "lights_standard": [],
    "lights_photometric": [],
    "cameras": [],  # its box, without Generate Mapping Coords
    "controllers": [],  # boxes without Generate Mapping Coords
    "controllers_tangents": [],  # boxes without Generate Mapping Coords
    "vray_wrappers": ["UVMap"],
    "uvwmap": {"FixtureUVWGizmo": ["UVMap", "UVChannel_2"], "FixtureUVWTwo": ["UVMap", "UVChannel_3"]},  # else UVMap
    "uvwmap_oblique": ["UVMap"],
    "uvwmap_pole": ["UVMap"],
}
# editable_mesh: group 1 on top and bottom, 2 on the sides; a box with a group per side: 12; modifier_pivot's box of
# four height segments: 4 x 4 vertical side edges and both rims
# a converted TurboSmooth or MeshSmooth with Smooth Result leaves no sharp edge
SHARP_EDGES = {"editable_mesh": 8, "modifier_pivot": {"FixtureSmooth": 0, None: 24},
               "stack_basic": {"FixtureTurbo": 0, None: 12},
               "stack_convert": {"FixtureTurboOne": 0, "FixtureMeshSmooth": 0, "FixtureOrder": 0, None: 12},
               # boxes without their top: the 4 vertical and the 4 bottom edges, and the 4 open edges a hardened Shell
               # rim makes sharp; the plane's open edges; a TurboSmooth below the Shell clears the groups, not the
               # open edges; one above it smooths the rim too
               "stack_shell": {"FixtureShellPlane": 4, "FixtureShellTurbo": 4, "FixtureShellSmoothed": 0, None: 12},
               # boxes of 3 x 2 x 2 segments: 28; the cylinder's rims 2 x 16; the sphere is smooth
               "uvwmap": {"FixtureUVWCyl": 32, "FixtureUVWSphere": 0, "FixtureUVWSharedB": 12, None: 28},
               # smooth spheres, the rims of a 10-sided cylinder
               "uvwmap_oblique": {"FixtureUVWObliqueCap": 20, None: 0},
               # the rims of 10-sided cylinders, smooth spheres
               "uvwmap_pole": {"FixtureUVWPoleCylinder": 20, "FixtureUVWPoleNear": 20, "FixtureUVWPoleOff": 20,
                               "FixtureUVWPoleDiagonal": 20,
                               "FixtureUVWPoleCone": 10,  # its base rim
                               "FixtureUVWPoleTile": 20, "FixtureUVWPoleCenter": 20, None: 0},
               # primitives (tests/unit/test_convert_scene.py, SHARP_EDGES_PRIMITIVES); the TurboSmooth smooths
               "primitives": {"FixtureBox": 36, "FixtureBoxCopy": 36, "FixtureBoxDown": 12, "FixtureBoxNoMap": 12,
                              "FixtureBoxSmooth": 0, "FixturePyramid": 18, "FixtureGeoOcta": 48,
                              "FixtureCylinder": 20, "FixtureCone": 18, "FixtureTube": 32, "FixtureTorus": 96,
                              "FixtureBoxInside": 16, "FixtureCylinderDown": 14, "FixtureConeTip": 14,
                              "FixtureTubeSwap": 28, "FixtureTorusOdd": 35, "FixturePyramidDown": 14,
                              "FixtureCylinderReal": 14, "FixtureTubeDown": 28,
                              "FixtureSphereHemi": 12, "FixtureSphereSquash": 13, "FixtureSphereSlice": 12,
                              "FixtureSphereSliceHemi": 29, "FixtureGeoHemi": 30, "FixtureGeoHemiTetra": 6,
                              "FixtureCylinderSlice": 30, "FixtureCylinderSliceDown": 19, "FixtureConeSlice": 26,
                              "FixtureTubeSlice": 36, "FixtureTorusSlice": 60, None: 0}}
SHARP_EDGES_DEFAULT = 12
# the class directory's name of a placeholder (maxdrop_class) where it is not MAXScript's (the oracle's)
CLASS_NAMES = {"Targetobject": "Target", "Targetcamera": "Target"}
FLAT_SHADED = {"FixtureGeoOcta"}  # a GeoSphere not smoothed: no smoothing group, every face flat
# primitives whose normals are not "away from the box center": a Plane's point up or down (by its sizes' signs), and
# a Box of width -12 keeps 3ds Max's faces, which point in
PLANE_NORMALS = {"FixturePlane": 1.0, "FixturePlaneDown": -1.0, "FixturePlaneReal": 1.0,
                 "FixtureShellPlane": 1.0}  # stack_shell's base plane (its Shell is a Solidify)
INSIDE_OUT = {"FixtureBoxInside"}
# vray_lights (tools/fixtures/vray_lights.ms): watts of the rules source's ocbaby_exsVrayLightWatts, run in 3ds Max
# on each light; the factor MaxDrop changes them by (the disc in lm/m2/sr, measured against V-Ray; the double-sided
# plane's one side); the shape and size in meters the script made; the linear colors (the fixture is saved with the
# gamma off: swatches and the Kelvin curve decoded from sRGB); the object and light flags that are not the default
VRAY_LIGHT_WATTS = {"FixturePlane": 0.0527086444, "FixturePlaneInst": 0.0527086444, "FixturePlaneLm": 2.19619322,
                    "FixtureDisc": 0.00975400303, "FixtureSphere": 40.0, "FixtureSphereKelvin": 0.252661914,
                    "FixtureOff": 0.00439238735, "FixtureInvisible": 20.0, "FixtureTargeted": 25.0,
                    "FixtureDiscScaled": 0.00975400303,
                    "FixtureNoShadow": 15.0,  # by hand, not run in 3ds Max: in W the rules give the multiplier
                    # vray_dome (tools/fixtures/vray_dome.ms): the rules' watts by hand (W/m2/sr: pi m 4 pi r^2; W: m),
                    # which V-Ray's X-scale rule leaves as they are for these scales
                    "FixtureSphereTall": math.pi * 2.0 * 4.0 * math.pi * 0.005 ** 2, "FixtureSphereWide": 40.0,
                    "FixtureSphereWideInst": 40.0}
# the scaled disc: its area times 2 x 1.5, as V-Ray lights it (measured)
VRAY_LIGHT_POWER = {"FixtureDisc": 4.0 / math.pi, "FixturePlaneLm": 0.5, "FixtureDiscScaled": 4.0 / math.pi * 3.0}
VRAY_LIGHT_SHAPES = {"FixturePlane": ('AREA', 'RECTANGLE', 0.04, 0.02, 0.0),
                     "FixturePlaneInst": ('AREA', 'RECTANGLE', 0.04, 0.02, 0.0),
                     "FixturePlaneLm": ('AREA', 'RECTANGLE', 0.03, 0.03, 0.0),
                     "FixtureDisc": ('AREA', 'DISK', 0.03, 0.0, 0.0), "FixtureSphere": ('POINT', None, 0.0, 0.0, 0.005),
                     "FixtureSphereKelvin": ('POINT', None, 0.0, 0.0, 0.008),
                     "FixtureOff": ('AREA', 'RECTANGLE', 0.02, 0.02, 0.0), "FixtureInvisible": ('AREA', 'DISK', 0.02,
                                                                                               0.0, 0.0),
                     "FixtureTargeted": ('AREA', 'RECTANGLE', 0.02, 0.01, 0.0),
                     "FixtureDiscScaled": ('AREA', 'DISK', 0.03, 0.0, 0.0),
                     "FixtureNoShadow": ('AREA', 'RECTANGLE', 0.02, 0.02, 0.0),
                     # vray_dome: radius 5 mm times the X scale (1, 2, 1), whatever the Y and Z scale
                     "FixtureSphereTall": ('POINT', None, 0.0, 0.0, 0.005),
                     "FixtureSphereWide": ('POINT', None, 0.0, 0.0, 0.01),
                     "FixtureSphereWideInst": ('POINT', None, 0.0, 0.0, 0.005)}
VRAY_LIGHT_COLORS = {"FixturePlane": (1.0, 0.57758, 0.304987), "FixturePlaneInst": (1.0, 0.57758, 0.304987),
                     "FixtureDisc": (0.187821, 0.351533, 1.0), "FixtureDiscScaled": (0.187821, 0.351533, 1.0),
                     "FixtureSphereKelvin": (1.0, 0.5304, 0.265643)}
VRAY_LIGHT_FLAGS = {"FixtureInvisible": (False, True, False, 0.5, 0.0)}  # camera, diffuse, glossy, factors
VRAY_NO_SHADOWS = {"FixtureNoShadow"}  # the VRayLights whose own Cast shadows is off (V-Ray's default on)
# cameras (tools/fixtures/cameras.ms): Blender's shift (image widths) and sensor where they are not 0 and 36 mm
CAMERA_SHIFTS = {"CamPhysShift": (-0.1, 0.15), "CamVRayShift": (-0.1, -0.25)}
CAMERA_SENSORS = {"CamVRayTarget": 30.0}
FOV_TOLERANCE = 0.05  # degrees
KEPT_SIZE = (1234, 567, 50)  # the scene's render size before each import (empty_scene)
USER_WORLD = "UserWorld"  # the scene's World before each import (empty_scene)
BARE_MESHES = {"FixtureMeshSource"}  # meshes a fixture leaves without a material: vray_dome's mesh light source

# lights_standard, lights_photometric (tools/fixtures/*.ms) and lookat's target spot: Blender's light type, spot
# size in degrees and blend, and the watts of the rules (docs/FORMAT.md, "Standard and photometric lights") from
# what the scripts set: a point or spot light 4 pi I / 683 W for I cd (a standard light's I = 1500 multiplier d^2,
# d the decay start or 1 m), a diffuse one pi I / 683, a standard Direct 1500 multiplier / 683 W/m^2, a VRaySun
# 146.4 x its multiplier, a VRayIES lm / 683
_CD, _LAMBERT = 4.0 * math.pi / 683.0, math.pi / 683.0
def _blend(falloff, hotspot):
    """Blender's spot blend whose full intensity ends at the hotspot (Blender blends in cosine space)."""
    edge = math.cos(math.radians(falloff) / 2.0)
    return (math.cos(math.radians(hotspot) / 2.0) - edge) / (1.0 - edge)


_WEB = (170.0, _blend(170.0, 100.0))
STOCK_LIGHTS = {
    "StdOmni": ('POINT', 0.0, 0.0, 2250.0 * _CD), "StdOmniInst": ('POINT', 0.0, 0.0, 2250.0 * _CD),
    "StdOmniSquare": ('POINT', 0.0, 0.0, 1920.0 * _CD), "StdOmniInverse": ('POINT', 0.0, 0.0, 375.0 * _CD),
    "StdOmniNegative": ('POINT', 0.0, 0.0, 0.0), "StdOmniNoDiffuse": ('POINT', 0.0, 0.0, 1500.0 * _CD),
    "StdOmniAmbient": ('POINT', 0.0, 0.0, 750.0 * _CD), "StdSpot": ('SPOT', 50.0, _blend(50.0, 30.0), 4500.0 * _CD),
    "StdSpotRect": ('SPOT', 45.0, _blend(45.0, 40.0), 1500.0 * _CD),
    "StdTargetSpot": ('SPOT', 60.0, _blend(60.0, 20.0), 3000.0 * _CD),
    "StdTargetDirect": ('SUN', 0.0, 0.0, 1500.0 * 0.8 / 683.0), "StdDirect": ('SUN', 0.0, 0.0, 1500.0 * 1.2 / 683.0),
    "StdSun": ('SUN', 0.0, 0.0, 73.2), "FixtureSpot": ('SPOT', 45.0, _blend(45.0, 43.0), 1500.0 * _CD),
    "PhPoint": ('POINT', 0.0, 0.0, 1200.0 * _CD), "PhPointInst": ('POINT', 0.0, 0.0, 1200.0 * _CD),
    "PhSpot": ('SPOT', 70.0, _blend(70.0, 40.0), 1000.0 * _CD), "PhRect": ('AREA', 0.0, 0.0, 800.0 * _LAMBERT),
    "PhDisc": ('AREA', 0.0, 0.0, 500.0 * _LAMBERT), "PhLine": ('AREA', 0.0, 0.0, 300.0 * _LAMBERT),
    "PhSphere": ('POINT', 0.0, 0.0, 900.0 * _CD), "PhCylinder": ('POINT', 0.0, 0.0, 700.0 * _CD),
    "PhWeb": ('SPOT',) + _WEB + (400.0 * _CD,), "PhOff": ('POINT', 0.0, 0.0, 1000.0 * _CD),
    "IesPower": ('SPOT',) + _WEB + (1500.0 / 683.0,), "IesOverride": ('SPOT',) + _WEB + (300.0 / 683.0,),
    "PhTPoint": ('POINT', 0.0, 0.0, 100.0 * _CD), "PhTLine": ('POINT', 0.0, 0.0, 100.0 * _CD),
    "PhTRectangle": ('POINT', 0.0, 0.0, 100.0 * _CD), "PhTSphere": ('POINT', 0.0, 0.0, 100.0 * _CD),
    "PhTCylinder": ('POINT', 0.0, 0.0, 100.0 * _CD)}
# swatches (0..255, decoded from sRGB: the fixtures are saved with the gamma off), the Kelvin colors 3ds Max computed
# with the rules source's ocbaby_exsKelvinRGB; white when not listed
STOCK_COLORS = {"StdOmni": (255, 200, 150), "StdOmniInst": (255, 200, 150), "StdSpot": (120, 160, 255),
                "StdDirect": (255, 240, 220), "StdSun": (255, 230, 200), "PhOff": (255, 128, 0),
                "PhPoint": (255, 177.2, 109.917), "PhPointInst": (255, 177.2, 109.917),
                "IesOverride": (255, 205.816, 166.081)}
STOCK_GREY = ("StdOmniSquare", "StdOmniInverse", "StdOmniNegative", "StdOmniNoDiffuse", "StdOmniAmbient",
              "StdSpotRect", "StdTargetSpot", "StdTargetDirect", "FixtureSpot")  # a standard light's default 180
STOCK_FLAGS = {"StdOmniNoDiffuse": (True, False, True, 0.0, 1.0), "StdSpotRect": (True, True, False, 1.0, 0.0),
               "PhCylinder": (True, True, False, 1.0, 0.0), "IesOverride": (True, True, False, 1.0, 0.0)}
# the stock lights that cast shadows (Light.use_shadow): a light MAXScript makes has them off, the scripts switch these
# on; a VRayIES has them on but IesOverride; a VRaySun has no switch
STOCK_SHADOWS = {"StdOmni", "StdOmniInst", "StdSpot", "StdTargetDirect", "StdSun", "PhPoint", "PhPointInst",
                 "PhSpot", "IesPower"}
# hollow: a tube's inner side and a torus's inner half face the box center; closed, they enclose a positive volume
# the oracle's base_class_id of the primitives MaxDrop builds (convert/primitives.py)
PRIMITIVE_CLASSES = {("0x00000010", "0x00000000"), ("0x00000011", "0x00000000"), ("0x00000012", "0x00000000"),
                     ("0x00000020", "0x00000000"), ("0xa86c23dd", "0x00000000"), ("0x00007b21", "0x00000000"),
                     ("0x00000000", "0x00007f9e"), ("0x081f1dfc", "0x77566f65"), ("0x76bf318a", "0x4bf37b10")}
# closed meshes checked by their volume: tubes and tori have no inside point, a Slice's cut planes run through the
# axis (beside the box center), a chopped hemisphere has a ring of flat faces
HOLLOW = {"FixtureTube", "FixtureTubeSwap", "FixtureTubeDown", "FixtureTorus", "FixtureTorusOdd", "FixtureSphereHemi",
          "FixtureSphereSquash", "FixtureSphereSlice", "FixtureSphereSliceHemi", "FixtureGeoHemi",
          "FixtureGeoHemiTetra", "FixtureCylinderSlice", "FixtureCylinderSliceDown", "FixtureConeSlice",
          "FixtureTubeSlice", "FixtureTorusSlice"}
# extrude (Generate Mapping Coords on two nodes); sharp edges: the vertical edges at corner knots, one per level, and
# both rims of every capped outline; V - E + F: a solid 2, one with a round tunnel 0, a ring and its island 0 + 2
EXTRUDE_UV_LAYERS = {"FixtureExtRect": ["UVMap"], "FixtureExtAdaptive": ["UVMap"],
                     "FixtureUVWExtrude": ["UVMap"],  # uvwmap: no mapping from the Extrude, the UVW Map's
                     "FixturePieRevExt": ["UVMap"], "FixturePieRevWrapExt": ["UVMap"], "FixturePieExt": ["UVMap"],
                     "FixtureArcRevExt": ["UVMap"], "FixtureClockwiseExt": ["UVMap"], "FixtureHoleExt": ["UVMap"]}
EXTRUDE_SHARP_EDGES = {"FixtureExtRect": 16, "FixtureExtL": 18, "FixtureExtHole": 68, "FixtureExtIsland": 36,
                       "FixtureExtOpen": 0, "FixtureExtMirror": 72, "FixtureExtAdaptive": 256,
                       "FixtureExtShapeIDs": 41, "FixtureExtShapeIDsRect": 12, "FixtureUVWExtrude": 12,
                       "FixtureExtGrid": 36, "FixtureExtGridCircle": 16,
                       "FixturePieRevExt": 52, "FixturePieRevWrapExt": 52, "FixturePieExt": 52,
                       "FixtureArcRevExt": 0, "FixtureClockwiseExt": 16, "FixtureHoleExt": 72}
EXTRUDE_EULER = {"FixtureExtRect": 2, "FixtureExtL": 2, "FixtureExtHole": 0, "FixtureExtIsland": 2,
                 "FixtureExtOpen": None, "FixtureExtMirror": 2, "FixtureExtAdaptive": 2, "FixtureExtShapeIDs": 0,
                 "FixtureExtShapeIDsRect": 2, "FixtureUVWExtrude": 2, "FixturePieRevExt": 2,
                 "FixtureExtGrid": 0, "FixtureExtGridCircle": None,  # grid caps: a holed solid; one cap
                 "FixturePieRevWrapExt": 2, "FixturePieExt": 2, "FixtureArcRevExt": None, "FixtureClockwiseExt": 2,
                 "FixtureHoleExt": 0}
VALUE_TOLERANCE = 1e-4
SPECULAR_LEVEL = 0.5  # the IR's specular is a reflection weight: 1 is Blender's Specular IOR Level 0.5
TWIN_LABEL, WEIGHT_LABEL = "Without reflection", "Reflection weight"  # a weight between 0 and 1 (maxdrop-em3.119)
MIRROR_LABEL = "Mirror reflection"  # the white metal of a weight without Fresnel (maxdrop-em3.120)
DEG = math.pi / 180.0
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  [%s]" % detail if detail else ""))
    if not cond:
        failures.append(name)


def empty_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for curve in list(bpy.data.curves):
        bpy.data.curves.remove(curve)
    for light in list(bpy.data.lights):
        bpy.data.lights.remove(light)
    for camera in list(bpy.data.cameras):
        bpy.data.cameras.remove(camera)
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)
    for text in list(bpy.data.texts):
        bpy.data.texts.remove(text)
    r = bpy.context.scene.render  # a size no fixture has: a file without a camera must leave it
    r.resolution_x, r.resolution_y, r.resolution_percentage = KEPT_SIZE
    r.pixel_aspect_x = r.pixel_aspect_y = 1.0
    bpy.context.scene.camera = None
    for material in list(bpy.data.materials):
        bpy.data.materials.remove(material)
    world = bpy.data.worlds.get(USER_WORLD) or bpy.data.worlds.new(USER_WORLD)  # a dome replaces the scene's World
    world.use_fake_user = False
    bpy.context.scene.world = world
    for other in [w for w in bpy.data.worlds if w != world]:
        bpy.data.worlds.remove(other)


def close(a, b, tolerance):
    return len(a) == len(b) and all(abs(x - y) <= tolerance for x, y in zip(a, b))


def world_of(ob):
    """ob's world matrix: matrix_world, or for an object hidden in the viewport or out of the view layer (an excluded
    collection's, layers_nested) the same product Blender evaluates, up the parent chain: such an object is left out
    of the evaluated scene, so its matrix_world is never updated. A visible child of a hidden parent is read from
    matrix_world: Blender must place it."""
    if not ob.hide_viewport and ob.name in bpy.context.view_layer.objects:
        return ob.matrix_world
    m = ob.matrix_basis.copy()
    while ob.parent is not None:
        m = ob.parent.matrix_basis @ ob.matrix_parent_inverse @ m
        ob = ob.parent
    return m


def max_rows(m, meters):
    """A Blender world matrix as the oracle's 12 floats: Max's rows, translation in file units."""
    out = []
    for r in range(3):
        out += [m[c][r] for c in range(3)]
    return out + [m[c][3] / meters for c in range(3)]


def objects_of(desc):
    """The object of each node of desc after an import into an emptied scene."""
    seen = collections.Counter()
    out = []
    for node in desc.nodes:
        k = seen[node.name]
        seen[node.name] += 1
        out.append(bpy.data.objects[node.name if not k else "%s.%03d" % (node.name, k)])
    return out


def build_scene(desc, name, modules, **slots):
    _cs, _cr, build_objects, build_collections, _br = modules
    view_layer = bpy.context.view_layer
    cols = build_collections.make(desc, bpy.context.scene.collection, name)
    built = build_objects.build(desc, cols.root, cols, view_layer, **slots)
    build_collections.finish(cols, view_layer)
    view_layer.update()
    return cols, built, view_layer


def run_fixture(path, modules):
    convert_scene, convert_report, _bo, _bc, build_report = modules
    name = os.path.splitext(os.path.basename(path))[0]
    with open(path[:-4] + ".oracle.json", encoding="utf-8") as f:
        oracle = json.load(f)
    empty_scene()
    desc = convert_scene.read(path)
    _same, plan = _irs(path)
    result = bpy.ops.import_scene.maxdrop(filepath=path)
    check("%s: the operator finishes" % name, result == {'FINISHED'}, str(result))
    listed = name in UV_LAYERS  # a named failure, not a KeyError (the plain suite also checks the keys)
    check("%s: listed in UV_LAYERS of tests/blender/run.py" % name, listed)
    if name == "vray_wrappers":
        check_wrappers_report()
    view_layer = bpy.context.view_layer
    view_layer.update()
    root = bpy.data.collections.get(name)
    meters = desc.meters
    nodes = oracle["nodes"]
    helpers = [ob for ob in bpy.data.objects if ob.get("maxdrop_helper") == "mirror"]
    mirrors = sum(1 for n in desc.nodes for m in n.converted if m.mirror is not None)
    shears = [ob for ob in bpy.data.objects if ob.get("maxdrop_helper") == "shear"]
    sheared = any(n.sheared and n.parent is None for n in desc.nodes)  # controllers: FixtureScaleAxis
    sections = [ob for ob in bpy.data.objects if ob.get("maxdrop_helper") == "section"]
    sectioned = sum(1 for cd in desc.curves.values() if cd.section is not None)
    check("%s: one object per node, one empty per mirror object, one for top-level sheared nodes, one per section"
          % name, len(desc.nodes) == len(nodes) == len(bpy.data.objects) - len(helpers) - len(shears) - len(sections)
          and len(helpers) == mirrors and len(shears) == int(sheared) and len(sections) == sectioned,
          "%d objects, %d nodes, %d mirror empties, %d shear empties, %d sections" % (
              len(bpy.data.objects), len(nodes), len(helpers), len(shears), len(sections)))
    check("%s: nodes in oracle order" % name, [n.name for n in desc.nodes] == [n["name"] for n in nodes])
    obs = objects_of(desc)
    meshes = {ob.data.name: ob.data for ob in obs if ob.type == 'MESH'}
    handle_of = {ob.as_pointer(): o["handle"] for ob, o in zip(obs, nodes)}
    offset_of = {o["handle"]: (o["offset_pos"], o["offset_rot"], o["offset_scale"]) for o in nodes}
    shading_of = {o["handle"]: next((m.shading for m in node.converted if m.kind == "SUBSURF"), None)
                  for node, o in zip(desc.nodes, nodes)}
    for ob, node, o in zip(obs, desc.nodes, nodes):
        label = "%s/%s" % (name, o["name"])
        parent = handle_of.get(ob.parent.as_pointer()) if ob.parent else None
        check(label + ": parent", parent == o["parent"], "%r vs %r" % (parent, o["parent"]))
        got = max_rows(world_of(ob), meters)
        check(label + ": world matrix", close(got, o["transform"], MATRIX_TOLERANCE),
              "%s vs %s" % (["%.6g" % v for v in got], o["transform"]))
        homes = [c.name for c in ob.users_collection]
        check(label + ": in its layer's collection", homes == [o["layer"]], str(homes))
        flags = (ob.hide_viewport, ob.hide_get(view_layer=view_layer), ob.hide_render, ob.hide_select)
        want = (o["hidden"], o["hidden"], not o["renderable"], o["frozen"])
        if node.kind == convert_scene.LIGHT and not desc.lights[node.light].on:  # a light switched off
            want = (True, o["hidden"], True, o["frozen"])
        check(label + ": hidden, renderable and frozen flags", flags == want, str(flags))
        if node.kind in (convert_scene.MESH, convert_scene.CURVE):
            check(label + ": casts shadows as in 3ds Max", ob.visible_shadow == o["cast_shadows"],
                  str(ob.visible_shadow))
        if node.kind == convert_scene.LIGHT:
            check_light(label, ob, desc.lights[node.light], o)
            continue
        if o["camera"] is not None:
            check_camera(label, ob, node, desc, o)
            continue
        if o["shape"] is not None and node.kind == convert_scene.MESH:
            check_extruded(label, ob, node, o, meters, plan)
            continue
        if o["shape"] is not None:
            check_curve(label, ob, o["shape"], meters)
            continue
        primitive = tuple(o["base_class_id"]) in PRIMITIVE_CLASSES  # built from its parameters
        if o["base_verts"] is None and not primitive:
            want = CLASS_NAMES.get(o["base_class_name"], o["base_class_name"])
            check(label + ": placeholder empty", ob.type == 'EMPTY' and ob.get("maxdrop_class") == want,
                  "%s %r" % (ob.type, ob.get("maxdrop_class")))
            continue
        check(label + ": mesh object", ob.type == 'MESH', ob.type)
        if ob.type != 'MESH':
            continue
        check_converted(label, ob, node, o, meters, desc)
        mesh = ob.data
        mw = world_of(ob)
        world = [mw @ v.co for v in mesh.vertices]
        lo = [min(p[k] for p in world) / meters for k in range(3)]
        hi = [max(p[k] for p in world) / meters for k in range(3)]
        if not o["modifiers"]:  # the oracle's box is after the modifiers, the base mesh is built
            check(label + ": world bounding box", close(lo, o["bbox_min"], BBOX_TOLERANCE)
                  and close(hi, o["bbox_max"], BBOX_TOLERANCE),
                  "%s..%s vs %s..%s" % (["%.6g" % v for v in lo], ["%.6g" % v for v in hi], o["bbox_min"],
                                        o["bbox_max"]))
        if primitive:  # the oracle counts the triangles of the TriMesh 3ds Max builds, after the modifiers
            if not o["modifiers"]:
                triangles = sum(len(p.vertices) - 2 for p in mesh.polygons)
                check(label + ": vertex and triangle counts = 3ds Max's", (len(mesh.vertices), triangles) ==
                      (o["eval_verts"], o["eval_faces"]), "%d, %d" % (len(mesh.vertices), triangles))
        else:
            check(label + ": vertex and face counts", (len(mesh.vertices), len(mesh.polygons)) ==
                  (o["base_verts"], o["base_faces"]), "%d, %d" % (len(mesh.vertices), len(mesh.polygons)))
        uv = [layer.name for layer in mesh.uv_layers]
        if listed:
            want = UV_LAYERS[name]
            check(label + ": UV layers", uv == (want.get(o["name"], ["UVMap"]) if isinstance(want, dict) else want),
                  str(uv))
        md = desc.meshes[node.mesh]
        for (uv_name, uv_data), layer in zip(md.uv_layers, mesh.uv_layers):
            got = [c for d in layer.data for c in d.uv]
            check(label + ": UV data of " + uv_name, close(got, uv_data.ravel().tolist(), 1e-6))
        sharp = mesh.attributes.get("sharp_edge")
        count = sum(1 for d in sharp.data if d.value) if sharp else 0
        want = SHARP_EDGES.get(name, SHARP_EDGES_DEFAULT)
        want = want.get(o["name"], want[None]) if isinstance(want, dict) else want
        check(label + ": sharp edges", count == want, str(count))
        flat = mesh.attributes.get("sharp_face")
        if o["name"] in FLAT_SHADED:
            check(label + ": every face flat", flat is not None and all(d.value for d in flat.data))
        else:
            check(label + ": every face smooth", flat is None or not any(d.value for d in flat.data))
        indices = [p.material_index for p in mesh.polygons]
        check(label + ": each face on its material's slot", indices == plan[node.mesh].indices.tolist(),
              str(indices))
        sharing = sorted(handle_of[other.as_pointer()] for other in obs if other.data == mesh)
        # the object offset is baked into the mesh: only the instances with the same offset share it
        same_offset = [h for h in o["instances"] if offset_of[h] == offset_of[o["handle"]]
                       and shading_of[h] == shading_of[o["handle"]]]  # a converted smoother's shading: own mesh
        check(label + ": objects sharing the mesh = oracle instances with its offset", sharing == same_offset,
              str(sharing))
        box = (lo, hi) if o["modifiers"] else (o["bbox_min"], o["bbox_max"])
        center = (Vector(box[0]) + Vector(box[1])) * (meters / 2.0)
        normal_matrix = mw.to_3x3().inverted().transposed()
        faces = [p for p in mesh.polygons if p.area > 1e-12]  # a cone's tip cap: its points all in one place
        if o["name"] in HOLLOW:
            volume = 0.0
            for p in mesh.polygons:
                a = mesh.vertices[p.vertices[0]].co
                for k in range(1, len(p.vertices) - 1):
                    volume += a.dot(mesh.vertices[p.vertices[k]].co.cross(mesh.vertices[p.vertices[k + 1]].co)) / 6
            check(label + ": a closed mesh facing out (positive volume)", volume * mw.determinant() > 0, str(volume))
        elif o["name"] in PLANE_NORMALS:
            up = [(normal_matrix @ p.normal).z * PLANE_NORMALS[o["name"]] > 0 for p in faces]
            check(label + ": normals point %s as in 3ds Max" % ("up" if PLANE_NORMALS[o["name"]] > 0 else "down"),
                  all(up), "%d of %d" % (sum(up), len(up)))
        else:
            outward = [(normal_matrix @ p.normal).dot(mw @ p.center - center) > 0 for p in faces]
            if o["name"] in INSIDE_OUT:
                check(label + ": normals inward as 3ds Max makes them", not any(outward),
                      "%d of %d out" % (sum(outward), len(outward)))
            else:
                check(label + ": normals outward as rendered", all(outward), "%d of %d" % (sum(outward),
                                                                                          len(outward)))
    if name == "instances":
        users = sorted(m.users for m in bpy.data.meshes)
        check("instances: four objects share one mesh, the copy has its own", users == [1, 4], str(users))
    if name == "modifier_pivot":
        check_modifier_pivot(obs, meters)
    if name == "extrude":
        kinds = [ob.type for ob in obs]
        check("extrude: eleven meshes, the switched-off Extrude a curve",
              kinds == ['MESH'] * 7 + ['CURVE'] + ['MESH'] * 4, str(kinds))
    if name == "shapes":
        curves = sorted(c.name for c in bpy.data.curves)
        shaped = sum(1 for o in nodes if o["shape"] is not None)
        check("shapes: one curve per shape node, one mesh", len(curves) == shaped == 13 and len(meshes) == 1,
              str(curves))
    if name == "shapes_more":
        check_shapes_more(obs, meters)
    if name == "hierarchy":
        mirrored = [n.name for n in desc.nodes if n.mirrored]
        check("hierarchy: FixtureLeaf is the mirrored node", mirrored == ["FixtureLeaf"], str(mirrored))
    layer_names = [c.name for c in root.children] if root else []
    parent_of = {la["name"]: la["parent"] for la in oracle["layers"]}
    kept = {o["layer"] for o in nodes}
    for layer in list(kept):  # a parent layer is kept, nodes or not
        while parent_of[layer] is not None:
            layer = parent_of[layer]
            kept.add(layer)
    order = [la["name"] for la in oracle["layers"]]

    def tree(col):
        return [(c.name, tree(c)) for c in col.children]

    def layer_tree(parent):  # Layer Manager order: every fixture makes a parent layer before its children
        return [(la, layer_tree(la)) for la in order if la in kept and parent_of[la] == parent]
    got = tree(root) if root else []
    check("%s: one collection per layer below the file's collection, nested as the layers" % name,
          root is not None and got == layer_tree(None) and root.name in bpy.context.scene.collection.children,
          "%s: %s" % (root and root.name, got))
    if name == "layers_flags":
        check("layers_flags: two layer collections", layer_names == ["FixtureLayerA", "FixtureLayerB"])
        hidden = [ob.name for ob in obs if ob.hide_viewport and ob.hide_get(view_layer=view_layer)]
        check("layers_flags: one hidden object", hidden == ["FixtureHidden"], str(hidden))
        no_render = [ob.name for ob in obs if ob.hide_render]
        check("layers_flags: one object with hide_render", no_render == ["FixtureNoRender"], str(no_render))
        no_shadow = [ob.name for ob in obs if not ob.visible_shadow]
        check("layers_flags: one object that casts no shadows", no_shadow == ["FixtureNoCastShadow"], str(no_shadow))
        group = bpy.data.objects["FixtureGroup"]
        members = sorted(ob.name for ob in group.children)
        check("layers_flags: the group head is an empty with its members as children",
              group.type == 'EMPTY' and members == ["FixtureGroupA", "FixtureGroupB"], "%s %s" % (group.type, members))
        excluded = [lc.name for lc in view_layer.layer_collection.children[name].children if lc.exclude]
        check("layers_flags: no layer excluded (none is hidden in 3ds Max)", excluded == [], str(excluded))
    if name == "layers_more":
        check_layers_more(root, obs, view_layer)
    if name == "layers_nested":
        check_layers_nested(root, obs, view_layer, oracle)
    bare = sorted(ob.name for ob in obs if ob.type == 'MESH' and not any(sl.material for sl in ob.material_slots)
                  and ob.name not in BARE_MESHES)
    check("%s: a material on every mesh" % name, bare == [], str(bare))
    check_fixture_materials(name, plan, desc, obs)
    rep = convert_report.gather(desc, source=os.path.basename(path), objects_built=len(obs),
                                meshes_built=len(meshes))
    level, line = build_report.publish(rep)
    text = bpy.data.texts.get(build_report.TEXT_NAME)
    published = text is not None and text.as_string().rstrip("\n") == rep.text()
    # the report counts each modifier class once per node whose stack holds it, applied (an Extrude on a shape, the
    # UVW Maps right above it or a mesh) or not (the rest: the base mesh is built); every modifier of the oracle is
    # one or the other
    split = [len(n.applied) + len(n.converted) + len(n.modifiers) for n in desc.nodes]
    check("%s: each modifier applied or not" % name, split == [len(o["modifiers"]) for o in nodes], str(split))
    modified = sum(len(set(n.modifiers)) for n in desc.nodes)
    applied = sum(len(set(n.applied)) for n in desc.nodes)
    issues = len(desc.issues)  # the issues a fixture is made to raise (tests/unit/test_convert_scene.py)
    check("%s: the report counts each applied modifier" % name, sum(rep.modifiers_applied.values()) == applied,
          str(dict(rep.modifiers_applied)))
    converted = sum(len({m.class_name for m in n.converted}) for n in desc.nodes)
    check("%s: the report counts each converted modifier" % name,
          sum(rep.modifiers_converted.values()) == converted, str(dict(rep.modifiers_converted)))

    if modified:
        check("%s: report published, nothing left out but the %d modifiers and %d issues" % (name, modified, issues),
              level == "WARNING" and published and not rep.approximated
              and rep.left_out == sum(rep.modifiers.values()) + issues and sum(rep.modifiers.values()) == modified
              and line.endswith("; %d modifier%s not applied%s. See the text %s." % (
                  modified, "" if modified == 1 else "s", ", %d issue%s" % (issues, "" if issues == 1 else "s")
                  if issues else "", build_report.TEXT_NAME)),
              line)
    elif desc.placeholders:
        held = sum(desc.placeholders.values())
        check("%s: report published, nothing left out but the %d placeholders and %d issues" % (name, held, issues),
              level == "WARNING" and published and rep.left_out == held + issues, line)
    elif issues:
        check("%s: report published, nothing left out but the %d issues" % (name, issues),
              level == "WARNING" and published and rep.left_out == issues, line)
    else:
        check("%s: report published, nothing left out" % name, level == "INFO" and published, line)
    print("COUNTS %s: objects=%d meshes=%d placeholders=%d issues=%d" % (
        name, len(bpy.data.objects), len(bpy.data.meshes), sum(desc.placeholders.values()), len(desc.issues)))
    check_render(name, oracle, obs, desc)
    if name == "lookat":  # imports the file again: last
        check_lookat(path, desc, obs, nodes, meters)
    if name == "vray_lights":
        lit = sorted(ob.name for ob in obs if ob.type == 'LIGHT')
        check("vray_lights: eleven light objects, ten lights (the instance shares one, the scaled one has its own)",
              len(lit) == 11 and len(bpy.data.lights) == 10 and bpy.data.objects["FixturePlane"].data ==
              bpy.data.objects["FixturePlaneInst"].data and bpy.data.objects["FixtureDisc"].data !=
              bpy.data.objects["FixtureDiscScaled"].data, "%s, %d lights" % (lit, len(bpy.data.lights)))
        world = bpy.context.scene.world
        strength = world.node_tree.nodes.get("Background").inputs["Strength"].default_value if world else None
        from maxdrop import ops
        check("vray_lights: its dome (white, multiplier 1 in the default units) is the World, strength 1500 / (683 pi) "
              "x Light Strength", world is not None and world.name == "FixtureDome" and strength is not None and
              abs(strength - 1500.0 / (683.0 * math.pi) * ops.LIGHT_STRENGTH) < 1e-5 and
              bpy.data.worlds.get(USER_WORLD) is not None, "%s %s" % (world and world.name, strength))
        check_light_strength(path)
    if name == "vray_dome":
        check_dome(desc)
    if name in ("lights_standard", "lights_photometric"):
        lit = [ob for ob in obs if ob.type == 'LIGHT']
        shared = {"lights_standard": ("StdOmni", "StdOmniInst"), "lights_photometric": ("PhPoint", "PhPointInst")}
        a, b = (bpy.data.objects[n] for n in shared[name])
        count = {"lights_standard": 13, "lights_photometric": 17}[name]
        check("%s: %d light objects, the instance shares its light" % (name, count),
              len(lit) == count and len(bpy.data.lights) == count - 1 and a.data == b.data, "%d, %d lights" % (
                  len(lit), len(bpy.data.lights)))


def check_camera(label, ob, node, desc, o):
    """A camera node: a camera object whose Camera is the description's, frames 3ds Max's horizontal field of view
    (the oracle's) and looks along the oracle's -Z with its +Y up."""
    check(label + ": a camera object", ob.type == 'CAMERA' and node.kind == "CAMERA", ob.type)
    if ob.type != 'CAMERA':
        return
    cam, cd = ob.data, desc.cameras[node.camera]
    got = (cam.type, cam.sensor_fit, cam.sensor_width, cam.lens, cam.shift_x, cam.shift_y, cam.dof.use_dof)
    want = (cd.kind, 'HORIZONTAL', cd.sensor, cd.lens, cd.shift_x, cd.shift_y, False)
    check(label + ": type, sensor fit, sensor, lens, shift, no depth of field", got[:2] == want[:2] and
          close(got[2:6], want[2:6], 1e-5) and got[6] == want[6], "%s vs %s" % (got, want))
    sx, sy = CAMERA_SHIFTS.get(o["name"], (0.0, 0.0))
    check(label + ": the shift and sensor the fixture script made", close((cam.shift_x, cam.shift_y), (sx, sy), 1e-6)
          and abs(cam.sensor_width - CAMERA_SENSORS.get(o["name"], 36.0)) < 1e-5, "%g, %g, %g" % (
              cam.shift_x, cam.shift_y, cam.sensor_width))
    fov = math.degrees(cam.angle_x)
    check(label + ": horizontal field of view = 3ds Max's", abs(fov - o["camera"]["fov"]) < FOV_TOLERANCE,
          "%g vs %g" % (fov, o["camera"]["fov"]))
    check(label + ": orthographic as in 3ds Max", (cam.type == 'ORTHO') == o["camera"]["ortho"], cam.type)
    if cam.type == 'ORTHO':
        check(label + ": orthographic width", abs(cam.ortho_scale - cd.ortho_scale) < 1e-6, "%g" % cam.ortho_scale)
    if o["camera"]["manual_clip"]:
        want = (o["camera"]["hither"] * desc.meters, o["camera"]["yon"] * desc.meters)
        check(label + ": clipping = 3ds Max's", close((cam.clip_start, cam.clip_end), want, 1e-6),
              "%g, %g" % (cam.clip_start, cam.clip_end))
    rows = o["transform"]
    m = ob.matrix_world.to_3x3()
    for axis, k, sign in (("-Z", 6, -1.0), ("+Y", 3, 1.0)):
        want = Vector(rows[k:k + 3]).normalized() * sign
        got = (m @ Vector((0.0, 0.0, 1.0) if k == 6 else (0.0, 1.0, 0.0))).normalized() * sign
        check(label + ": %s along the oracle's" % axis, (got - want).length < 1e-5, "%s vs %s" % (
            tuple(got), tuple(want)))


def check_render(name, oracle, obs, desc):
    """Every fixture: with a camera, the scene's render size is the oracle's and scene.camera the oracle's render
    camera or else the first camera; without one, the scene's render size and camera stay as they were."""
    scene = bpy.context.scene
    r = oracle["render"]
    got = (scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage,
           scene.render.pixel_aspect_x / scene.render.pixel_aspect_y)
    by_handle = {o["handle"]: ob for ob, o in zip(obs, oracle["nodes"])}
    cams = [ob for ob, o in zip(obs, oracle["nodes"]) if o["camera"] is not None]
    want = by_handle[r["camera"]] if r["camera"] is not None else (cams[0] if cams else None)
    if want is not None:
        check("%s: render size = 3ds Max's" % name, got[:3] == (r["width"], r["height"], 100) and
              abs(got[3] - r["pixel_aspect"]) < 1e-6, str(got))
        check("%s: scene camera = %s" % (name, want.name), scene.camera == want,
              scene.camera.name if scene.camera else "none")
    else:
        check("%s: no camera: the scene's render size and camera are kept" % name,
              got == KEPT_SIZE + (1.0,) and scene.camera is None, "%s %s" % (got, scene.camera))
    if name == "cameras":
        check("cameras: eleven camera objects, one Camera each, CamTarget the scene camera",
              len(cams) == 11 and len(bpy.data.cameras) == 11 and scene.camera.name == "CamTarget",
              "%d, %d" % (len(cams), len(bpy.data.cameras)))
    if name == "lookat":
        check("lookat: FixtureCam (the first camera) is the scene camera, a note, no camera issue",
              scene.camera is not None and scene.camera.name == "FixtureCam" and desc.camera is not None
              and desc.camera_note is not None and not any(r.startswith("camera: ") for _i, r in desc.issues),
              str(desc.camera_note))


def check_light(label, ob, ld, o):
    """vray_lights: a LIGHT node's object holds its light: the description's type, shape and size; its -Z axis
    (where a V-Ray plane and a Blender area light shine) along the oracle's; its energy the watts 3ds Max computed
    with the rules source's own function (VRAY_LIGHT_WATTS) times the operator's default Light Strength, halved for
    the double-sided plane; its color, its object flags and its shadow switch (VRAY_NO_SHADOWS). Any other light:
    check_stock_light."""
    light = ob.data
    check(label + ": a light object", ob.type == 'LIGHT', ob.type)
    if ob.type != 'LIGHT':
        return
    if o["name"] not in VRAY_LIGHT_WATTS:
        check_stock_light(label, ob, ld, o)
        return
    size = (light.type, getattr(light, "shape", None) if light.type == 'AREA' else None,
            light.size if light.type == 'AREA' else 0.0,
            light.size_y if light.type == 'AREA' and light.shape == 'RECTANGLE' else 0.0,
            light.shadow_soft_size if light.type == 'POINT' else 0.0)
    want = (ld.kind, ld.shape, ld.size, ld.size_y if ld.shape == 'RECTANGLE' else 0.0, ld.radius)
    check(label + ": type, shape and size", size[:2] == want[:2] and close(size[2:], want[2:], 1e-7),
          "%s vs %s" % (size, want))
    expected = VRAY_LIGHT_SHAPES.get(o["name"])
    check(label + ": the shape the fixture script made", expected is not None and size[:2] == expected[:2] and
          close(size[2:], expected[2:], 1e-7), str(expected))
    rows = o["transform"]
    z = Vector(rows[6:9]).normalized()
    got = -(ob.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
    check(label + ": shines along the oracle's -Z", (got + z).length < 1e-5, "%s vs %s" % (tuple(got), tuple(-z)))
    from maxdrop import ops
    watts = VRAY_LIGHT_WATTS[o["name"]] * VRAY_LIGHT_POWER.get(o["name"], 1.0)
    check(label + ": power = 3ds Max's watts x Light Strength", abs(light.energy - watts * ops.LIGHT_STRENGTH) <=
          watts * ops.LIGHT_STRENGTH * 1e-5, "%g vs %g" % (light.energy, watts * ops.LIGHT_STRENGTH))
    color = VRAY_LIGHT_COLORS.get(o["name"], (1.0, 1.0, 1.0))
    check(label + ": color", close(tuple(light.color), color, 1e-5) and close(tuple(light.color), ld.color, 1e-6),
          str(tuple(light.color)))
    flags = (ob.visible_camera, ob.visible_diffuse, ob.visible_glossy, round(light.diffuse_factor, 6),
             round(light.specular_factor, 6))
    want = VRAY_LIGHT_FLAGS.get(o["name"], (True, True, True, 1.0, 1.0))
    check(label + ": camera, diffuse and glossy visibility, diffuse and specular factors", flags == want, str(flags))
    check(label + ": shadows as in 3ds Max", light.use_shadow == ld.shadow == (o["name"] not in VRAY_NO_SHADOWS),
          "%s, %s" % (light.use_shadow, ld.shadow))


def check_stock_light(label, ob, ld, o):
    """lights_standard, lights_photometric, lookat's target spot: the light's type, spot cone, size or radius as the
    description says, energy the watts of STOCK_LIGHTS times the default Light Strength, color, flags, shadows
    (STOCK_SHADOWS); its -Z axis (where a spot, an area light and a sun shine in both programs) along the oracle's."""
    from maxdrop import ops
    light = ob.data
    kind, cone, blend, watts = STOCK_LIGHTS[o["name"]]
    check(label + ": type", light.type == kind == ld.kind, "%s vs %s" % (light.type, kind))
    if light.type == 'SPOT':
        check(label + ": spot size and blend", abs(math.degrees(light.spot_size) - cone) < 1e-4 and
              abs(light.spot_blend - blend) < 1e-6, "%g, %g" % (math.degrees(light.spot_size), light.spot_blend))
    if light.type == 'AREA':
        got = (light.shape, light.size, light.size_y if light.shape == 'RECTANGLE' else light.size)
        check(label + ": area shape and size", got[0] == ld.shape and close(got[1:], (ld.size, ld.size_y), 1e-7),
              str(got))
    elif light.type == 'SUN':
        check(label + ": sun angle", abs(light.angle - ld.angle) < 1e-7, "%g" % light.angle)
    else:
        check(label + ": radius", abs(light.shadow_soft_size - ld.radius) < 1e-7, "%g" % light.shadow_soft_size)
    want = watts * ops.LIGHT_STRENGTH
    check(label + ": power = the rules' watts x Light Strength", abs(light.energy - want) <= max(want, 1.0) * 1e-5,
          "%g vs %g" % (light.energy, want))
    rgb = STOCK_COLORS.get(o["name"], (180, 180, 180) if o["name"] in STOCK_GREY else (255, 255, 255))
    color = tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (v / 255.0 for v in rgb))
    check(label + ": color", close(tuple(light.color), color, 1e-5), str(tuple(light.color)))
    rows = o["transform"]
    z = Vector(rows[6:9]).normalized()
    got = -(ob.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
    check(label + ": shines along the oracle's -Z", (got + z).length < 1e-5, "%s vs %s" % (tuple(got), tuple(-z)))
    flags = (ob.visible_camera, ob.visible_diffuse, ob.visible_glossy, round(light.diffuse_factor, 6),
             round(light.specular_factor, 6))
    want = STOCK_FLAGS.get(o["name"], (True, True, True, 1.0, 1.0))
    check(label + ": camera, diffuse and glossy visibility, diffuse and specular factors", flags == want, str(flags))
    check(label + ": shadows as in 3ds Max", light.use_shadow == ld.shadow == (o["name"] in STOCK_SHADOWS),
          "%s, %s" % (light.use_shadow, ld.shadow))


def check_dome(desc):
    """vray_dome: the dome is the World: Background strength (through the hemisphere's Math nodes) = 2 x 1500 /
    (683 pi) x Light Strength, its color an Environment Texture of fixture_dome.png, the texture's Mapping (scale 1, -1,
    1; turned 60 degrees about Z: -30 of the VRayBitmap's horizontal rotation, then the mirrored dome turned 90 about Z)
    and the hemisphere's (the dome's -90 about Z), camera rays off, diffuse and glossy on. The two spheres share one
    light, the scaled one has its own. The report says the World and the one it replaced, which is kept."""
    from maxdrop import ops
    world = bpy.context.scene.world
    user = bpy.data.worlds.get(USER_WORLD)
    check("vray_dome: FixtureDome is the World, UserWorld kept with a fake user", world is not None and
          world.name == "FixtureDome" and user is not None and user.use_fake_user, world.name if world else "none")
    if world is None or world.name != "FixtureDome":
        return
    nodes = world.node_tree.nodes
    env = next((n for n in nodes if n.bl_idname == "ShaderNodeTexEnvironment"), None)
    times = next((n for n in nodes if n.bl_idname == "ShaderNodeMath" and n.operation == 'MULTIPLY'), None)
    above = next((n for n in nodes if n.bl_idname == "ShaderNodeMath" and n.operation == 'GREATER_THAN'), None)
    maps = {tuple(round(v, 6) for v in n.inputs["Scale"].default_value): n for n in nodes
            if n.bl_idname == "ShaderNodeMapping"}
    want = 2.0 * 1500.0 / (683.0 * math.pi) * ops.LIGHT_STRENGTH
    check("vray_dome: hemisphere strength = 2 x 1500 / (683 pi) x Light Strength, masked by Z > 0",
          times is not None and above is not None and abs(times.inputs[1].default_value - want) < 1e-5 and
          times.inputs[0].links and times.inputs[0].links[0].from_node == above,
          "%s" % (times and times.inputs[1].default_value))
    check("vray_dome: an Environment Texture of fixture_dome.png drives the color",
          env is not None and env.image is not None and env.image.name.startswith("fixture_dome") and
          nodes["Background"].inputs["Color"].links and
          nodes["Background"].inputs["Color"].links[0].from_node == env, str(env and env.image))
    tex, up = maps.get((1.0, -1.0, 1.0)), maps.get((1.0, 1.0, 1.0))
    check("vray_dome: the texture's Mapping turned 60 degrees about Z, the hemisphere's -90",
          tex is not None and up is not None and
          close(tuple(tex.inputs["Rotation"].default_value), (0.0, 0.0, math.radians(60.0)), 1e-5) and
          close(tuple(up.inputs["Rotation"].default_value), (0.0, 0.0, math.radians(-90.0)), 1e-5),
          "%s %s" % (tex and tuple(tex.inputs["Rotation"].default_value),
                     up and tuple(up.inputs["Rotation"].default_value)))
    rays = world.cycles_visibility
    check("vray_dome: invisible: camera rays off, diffuse and glossy on", (rays.camera, rays.diffuse, rays.glossy) ==
          (False, True, True), str((rays.camera, rays.diffuse, rays.glossy)))
    for name in ("FixtureDomeColor", "FixtureMeshLight"):
        ob = bpy.data.objects.get(name)
        check("vray_dome: %s an empty" % name, ob is not None and ob.type == 'EMPTY', ob and ob.type)
    check("vray_dome: three sphere objects, three lights (the scaled instance its own)",
          len([ob for ob in bpy.data.objects if ob.type == 'LIGHT']) == 3 and len(bpy.data.lights) == 3 and
          bpy.data.objects["FixtureSphereWide"].data != bpy.data.objects["FixtureSphereWideInst"].data,
          str(len(bpy.data.lights)))


def check_dome_undo(path):
    """vray_dome: the report names the World and the one it replaced; undo() of a finished modal run (the World is
    made at the end of the build), and a build that fails after making the World, put the scene's World back and
    remove the new one with everything else the run made."""
    from maxdrop import ops
    empty_scene()
    result = bpy.ops.import_scene.maxdrop(filepath=path)
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    check("dome undo: the report names the World and the one it replaced", result == {'FINISHED'} and
          "\nWorld: the dome light FixtureDome, in place of %s (kept)\n" % USER_WORLD in body, body[:600])
    empty_scene()
    for img in list(bpy.data.images):  # so that the run loads the dome's image anew, and undo() must remove it
        bpy.data.images.remove(img)
    before = _state()
    run = _cancel_run([path])
    for _ in run.steps():
        pass
    made = bpy.context.scene.world is not None and bpy.context.scene.world.name == "FixtureDome"
    run.undo()
    check("dome undo: undo() after the run: the World before is back without a fake user, nothing made",
          made and _state() == before and not bpy.data.worlds[USER_WORLD].use_fake_user,
          "%s | %s" % (_state(), before))
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    before = _state()
    original = ops._make_world

    def failing(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("maxdrop test: build fails after the World")

    ops._make_world = failing
    try:
        steps = _cancel_run([path]).steps()
        failed = False
        try:
            for _ in steps:
                pass
        except RuntimeError:
            failed = True
        except Exception as e:  # the runner may wrap it
            failed = "maxdrop test" in str(e)
    finally:
        ops._make_world = original
    check("dome undo: a build that fails after the World puts the World before back, nothing made",
          failed and _state() == before and not bpy.data.worlds[USER_WORLD].use_fake_user,
          "%s | %s" % (_state(), before))

    # a World that cannot be built: the scene is imported, the World stays, a line in the report
    from maxdrop.build import world as build_world
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    real = build_world.make_world

    def broken(*args, **kwargs):
        bpy.data.worlds.new("Half")
        raise RuntimeError("maxdrop test: World fails")

    build_world.make_world = broken
    try:
        result = bpy.ops.import_scene.maxdrop(filepath=path)
    finally:
        build_world.make_world = real
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    check("dome undo: a World that cannot be built: the scene imported, its World kept, nothing left, a report line",
          result == {'FINISHED'} and len(bpy.data.objects) == 7 and bpy.context.scene.world.name == USER_WORLD and
          [w.name for w in bpy.data.worlds] == [USER_WORLD] and not bpy.data.images and
          "the World is not built (RuntimeError: maxdrop test: World fails)" in body,
          "%s %d %s %s" % (result, len(bpy.data.objects), [w.name for w in bpy.data.worlds], body[-400:]))

    # two files with a dome: the first gives the World, the second's dome is a line in the report
    lights = os.path.join(os.path.dirname(path), "vray_lights.max")
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    before = _state()
    run = _cancel_run([path, lights])
    for _ in run.steps():
        pass
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    names = sorted(w.name for w in bpy.data.worlds)
    check("dome undo: two files with a dome: the first file's dome is the World, the second's a line in the report",
          bpy.context.scene.world.name == "FixtureDome" and names == ["FixtureDome", USER_WORLD] and
          "dome light not imported: an earlier file of this import gave the World (FixtureDome)" in body,
          "%s %s" % (names, body[-600:]))
    run.undo()
    check("dome undo: two files undone: the World before is back without a fake user, nothing made",
          _state() == before and not bpy.data.worlds[USER_WORLD].use_fake_user, "%s | %s" % (_state(), before))
    empty_scene()


def check_light_strength(path):
    """vray_lights imported again with Light Strength 2: every light's energy is its power times 2."""
    empty_scene()
    result = bpy.ops.import_scene.maxdrop(filepath=path, light_strength=2.0)
    check("vray_lights Light Strength 2: the operator finishes", result == {'FINISHED'}, str(result))
    sphere = bpy.data.objects.get("FixtureSphere")
    check("vray_lights Light Strength 2: 40 W x 2", sphere is not None and abs(sphere.data.energy - 80.0) < 1e-4,
          str(sphere and sphere.data.energy))


def check_extruded(label, ob, node, o, meters, plan):
    """A shape under an Extrude: a mesh with the oracle's world box, vertex count and triangle count, closed with
    normals outward as rendered (the signed volume of the world mesh, times the sign of the world matrix's
    determinant, is positive) when capped, its UV layers, sharp edges and material slots."""
    check(label + ": mesh object", ob.type == 'MESH', ob.type)
    if ob.type != 'MESH':
        return
    mesh, mw = ob.data, world_of(ob)
    world = [mw @ v.co for v in mesh.vertices]
    lo = [min(p[k] for p in world) / meters for k in range(3)]
    hi = [max(p[k] for p in world) / meters for k in range(3)]
    check(label + ": world bounding box", close(lo, o["bbox_min"], BBOX_TOLERANCE)
          and close(hi, o["bbox_max"], BBOX_TOLERANCE),
          "%s..%s vs %s..%s" % (["%.6g" % v for v in lo], ["%.6g" % v for v in hi], o["bbox_min"], o["bbox_max"]))
    triangles = sum(len(p.vertices) - 2 for p in mesh.polygons)
    check(label + ": vertex and triangle counts", (len(mesh.vertices), triangles) == (o["eval_verts"], o["eval_faces"]),
          "%d, %d" % (len(mesh.vertices), triangles))
    name = o["name"]
    euler = EXTRUDE_EULER[name]
    if euler is not None:
        uses = collections.Counter(tuple(sorted(e.vertices)) for p in mesh.polygons for e in
                                   (mesh.edges[mesh.loops[i].edge_index] for i in p.loop_indices))
        check(label + ": closed (every edge has two faces)", set(uses.values()) == {2}, str(set(uses.values())))
        check(label + ": V - E + F", len(mesh.vertices) - len(mesh.edges) + len(mesh.polygons) == euler)
        volume = 0.0
        for p in mesh.polygons:
            v = [world[i] for i in p.vertices]
            for k in range(1, len(v) - 1):
                volume += v[0].dot(v[k].cross(v[k + 1])) / 6.0
        check(label + ": normals outward as rendered", volume * mw.to_3x3().determinant() > 0, "%g" % volume)
    uv = [layer.name for layer in mesh.uv_layers]
    check(label + ": UV layers", uv == EXTRUDE_UV_LAYERS.get(name, []), str(uv))
    sharp = mesh.attributes.get("sharp_edge")
    count = sum(1 for d in sharp.data if d.value) if sharp else 0
    check(label + ": sharp edges", count == EXTRUDE_SHARP_EDGES[name], str(count))
    indices = [p.material_index for p in mesh.polygons]
    check(label + ": each face on its material's slot", indices == plan[node.mesh].indices.tolist(), str(indices))
    check(label + ": a material", any(sl.material for sl in ob.material_slots))


# 3ds Max leaves the seam of FixtureOrder's shelled boxes unwelded (32 vertices before the TurboSmooth, 100 after);
# Blender's Mirror welds it (84): the same surface, so only the box is compared there
EVAL_COUNT_DIFFERS = {"FixtureOrder"}
# Blender's evaluated (flat, regions, hard edges) where it is not 3ds Max's, pinned so that a change shows. 3ds Max
# gives a Shell's rim smoothing groups of its own, hard against both surfaces, which the open edges marked sharp give
# Blender too, but for two cases the report names: auto smooth also splits the rim where its faces turn by more than
# 45 degrees (FixtureShellPlane: 3ds Max 6 regions and 12 hard edges), and the override group with auto smooth off
# merges the rim into the side of that group (FixtureShellOverride: 3ds Max 9 and 22).
# FixtureSymmetryTurned: Blender's Mirror welds the corner 0.062 off the plane onto it, where 3ds Max slices beside
# it: 3ds Max keeps a sliver of the side beyond the box's sharp vertical corner edge, smooth with its mirror copy;
# in Blender that corner edge lands on the plane as the seam between the other side and its copy, a hard edge that
# splits one more region (the vertex and triangle counts agree).
SMOOTHING_DIFFERS = {"FixtureShellPlane": (0, 3, 8), "FixtureShellOverride": (0, 11, 24),
                     "FixtureSymmetryTurned": (0, 7, 17)}
FACING_TOLERANCE = 1e-4  # the oracle's: a winding normal's z within it faces sideways


def _smoothing(mesh):
    """How an evaluated mesh is shaded, as the oracle's eval_mesh.smoothing: (flat, regions, hard edges): the
    triangles of flat faces; the smooth faces joined through the edges with exactly two faces, both smooth, not
    sharp, counted; such edges marked sharp."""
    n = len(mesh.polygons)
    attr = mesh.attributes.get("sharp_face")
    flat = [d.value for d in attr.data] if attr else [False] * n
    attr = mesh.attributes.get("sharp_edge")
    sharp = [d.value for d in attr.data] if attr else [False] * len(mesh.edges)
    faces_of = collections.defaultdict(list)
    for p in mesh.polygons:
        for i in p.loop_indices:
            faces_of[mesh.loops[i].edge_index].append(p.index)
    parent = list(range(n))

    def root(f):
        while parent[f] != f:
            parent[f] = parent[parent[f]]
            f = parent[f]
        return f

    hard = 0
    for e, fs in faces_of.items():
        if len(fs) != 2 or flat[fs[0]] or flat[fs[1]]:
            continue
        if sharp[e]:
            hard += 1
        else:
            a, b = root(fs[0]), root(fs[1])
            if a != b:
                parent[a] = b
    return (sum(len(p.vertices) - 2 for p in mesh.polygons if flat[p.index]),
            len({root(p.index) for p in mesh.polygons if not flat[p.index]}), hard)


def _facing(mesh, mw, meters, object_transform):
    """The evaluated triangles by the way they face in 3ds Max's object space, as the oracle's eval_mesh counts
    them, summed over material IDs: [up, down, side]. The world vertices (file units) are taken back by the
    inverse of the oracle's object transform (rows, row vectors); a face's triangles share its winding normal."""
    t = object_transform
    to_object = Matrix(((t[0], t[3], t[6], t[9]), (t[1], t[4], t[7], t[10]), (t[2], t[5], t[8], t[11]),
                        (0.0, 0.0, 0.0, 1.0))).inverted()
    pts = [to_object @ ((mw @ v.co) / meters) for v in mesh.vertices]
    counts = [0, 0, 0]
    for p in mesh.polygons:
        v = [pts[i] for i in p.vertices]
        for k in range(1, len(v) - 1):
            nrm = (v[k] - v[0]).cross(v[k + 1] - v[0])
            z = nrm.normalized().z if nrm.length > 1e-12 else 0.0
            counts[0 if z > FACING_TOLERANCE else 1 if z < -FACING_TOLERANCE else 2] += 1
    return counts


def _setting_ok(got, want):
    if isinstance(want, tuple):
        return tuple(got) == want
    if isinstance(want, float):
        return abs(got - want) <= 1e-6 * max(1.0, abs(want))
    return got == want


def check_converted(label, ob, node, o, meters, desc):
    """The Blender modifiers of a node (node.converted, convert.modifiers): types, order, names, settings and mirror
    objects; when MaxDrop evaluates the rest of the stack, the evaluated mesh has 3ds Max's vertex and triangle
    counts (eval_verts, eval_faces) and world box. Creases on the sharp edges of a mesh that asks for them, but its
    open edges (a hardened Shell rim's)."""
    md = desc.meshes[node.mesh]
    crease = ob.data.attributes.get("crease_edge")
    sharp = ob.data.attributes.get("sharp_edge")
    if md.creases:
        faces = collections.Counter(lp.edge_index for lp in ob.data.loops)
        flags = [d.value and faces[k] != 1 for k, d in enumerate(sharp.data)] if sharp else []
        check(label + ": sharp edges creased", crease is not None and len(flags) == len(crease.data)
              and all((c.value == 1.0) == f for c, f in zip(crease.data, flags)) and any(flags))
    else:
        check(label + ": no crease", crease is None or not any(d.value for d in crease.data))
    mods = list(ob.modifiers)
    check(label + ": Blender modifiers in 3ds Max's order", [(m.type, m.name) for m in mods] ==
          [(c.kind, c.name) for c in node.converted], str([(m.type, m.name) for m in mods]))
    if not node.converted:
        return
    for mod, c in zip(mods, node.converted):
        bad = [a for a, v in c.settings if not _setting_ok(getattr(mod, a), v)]
        check(label + ": %s settings" % mod.name, not bad and mod.show_viewport == c.show_viewport, str(bad))
        if mod.type == 'MIRROR':
            mirror = mod.mirror_object
            if c.mirror is None:
                check(label + ": no mirror object", mirror is None)
            else:
                check(label + ": the mirror object an empty child at the gizmo", mirror is not None
                      and mirror.type == 'EMPTY' and mirror.parent == ob and close(
                          [v for row in mirror.matrix_basis for v in row], [v for row in c.mirror for v in row],
                          1e-6), mirror and str(mirror.matrix_basis))
    if node.modifiers:
        return
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    mesh = ev.to_mesh()
    try:
        mw = world_of(ob)
        world = [mw @ v.co for v in mesh.vertices]
        triangles = sum(len(p.vertices) - 2 for p in mesh.polygons)
        counts = (len(mesh.vertices), triangles)
        smoothing = _smoothing(mesh)
        facing = _facing(mesh, mw, meters, o["object_transform"]) if any(
            c.kind == 'SOLIDIFY' for c in node.converted) else None
    finally:
        ev.to_mesh_clear()
    lo = [min(p[k] for p in world) / meters for k in range(3)]
    hi = [max(p[k] for p in world) / meters for k in range(3)]
    # a vertex within the weld threshold of the mirror plane: Blender's Mirror merges it with its copy onto the
    # plane, 3ds Max's Symmetry slices beside it (FixtureSymmetryTurned: a corner 0.062 off the plane, threshold 0.2)
    weld = max([dict(c.settings)["merge_threshold"] / meters for c in node.converted
                if c.kind == 'MIRROR' and dict(c.settings)["use_mirror_merge"]] or [0.0])
    tolerance = BBOX_TOLERANCE + weld
    check(label + ": evaluated world box = 3ds Max's", close(lo, o["bbox_min"], tolerance)
          and close(hi, o["bbox_max"], tolerance),
          "%s..%s vs %s..%s" % (["%.6g" % v for v in lo], ["%.6g" % v for v in hi], o["bbox_min"], o["bbox_max"]))
    if o["name"] not in EVAL_COUNT_DIFFERS:
        check(label + ": evaluated vertex and triangle counts = 3ds Max's", counts == (o["eval_verts"],
                                                                                       o["eval_faces"]),
              "%d, %d vs %s, %s" % (counts + (o["eval_verts"], o["eval_faces"])))
        sm = o["eval_mesh"]["smoothing"]
        want = (sm["flat"], sm["regions"], sm["hard_edges"])
        if o["name"] in SMOOTHING_DIFFERS:
            check(label + ": evaluated shading (flat, regions, hard edges) as pinned, 3ds Max's %s" % (want,),
                  smoothing == SMOOTHING_DIFFERS[o["name"]] and smoothing != want, str(smoothing))
        else:
            check(label + ": evaluated shading (flat, regions, hard edges) = 3ds Max's", smoothing == want,
                  "%s vs %s" % (smoothing, want))
        if facing is not None:  # a Shell's side and facing (inside out or not)
            want = [sum(h[k] for h in o["eval_mesh"]["material_ids"]) for k in (1, 2, 3)]
            check(label + ": evaluated triangles facing up, down, sideways = 3ds Max's", facing == want,
                  "%s vs %s" % (facing, want))


def check_ignore_option(path, modules):
    """stack_convert imported with Modifiers: Ignore: no Blender modifier, no mirror empty, every modifier counted as
    not applied."""
    empty_scene()
    result = bpy.ops.import_scene.maxdrop(filepath=path, modifiers='IGNORE')
    check("stack_convert: Ignore: the operator finishes", result == {'FINISHED'}, str(result))
    mods = [m.type for ob in bpy.data.objects for m in ob.modifiers]
    check("stack_convert: Ignore: no Blender modifier, no empty", mods == [] and all(
        ob.type == 'MESH' for ob in bpy.data.objects), str(mods))
    text = bpy.data.texts.get(modules[4].TEXT_NAME)
    check("stack_convert: Ignore: the report counts them as not applied", text is not None and
          "nodes by class: Symmetry 4, TurboSmooth 4, Shell 2, Bend 1, MeshSmooth 1" in text.as_string()
          and "converted to a Blender modifier" not in text.as_string())


def check_curve(label, ob, shape, meters):
    """A shape node's curve object against the oracle's knots (object space: no fixture shape has an object
    offset): splines, points, cyclic flags, each segment's middle, resolution and bevel."""
    check(label + ": curve object", ob.type == 'CURVE', ob.type)
    if ob.type != 'CURVE':
        return
    cu = ob.data
    want = shape["splines"]
    got = [(len(sp.bezier_points), sp.use_cyclic_u, sp.type) for sp in cu.splines]
    check(label + ": splines, points and cyclic flags", got == [(len(w["knots"]), w["closed"], 'BEZIER') for w in want],
          str(got))
    check(label + ": 3D", cu.dimensions == '3D', cu.dimensions)
    steps = 12 if shape["adaptive"] else shape["steps"] + 1
    check(label + ": resolution from the steps", cu.resolution_u == steps and
          all(sp.resolution_u == steps for sp in cu.splines), "%d vs %d" % (cu.resolution_u, steps))
    if shape["renderable"] and shape["rectangular"]:
        check_section(label, ob, shape, meters)
    elif shape["renderable"]:
        check(label + ": a bevel of the thickness", abs(cu.bevel_depth - shape["thickness"] / 2 * meters) < 1e-9 and
              cu.bevel_resolution == (shape["sides"] - 4) // 2 and cu.bevel_mode == 'ROUND',
              "%g, %d, %s" % (cu.bevel_depth, cu.bevel_resolution, cu.bevel_mode))
    else:
        check(label + ": no bevel", cu.bevel_depth == 0 and cu.bevel_object is None, str(cu.bevel_depth))
    for k, (sp, w) in enumerate(zip(cu.splines, want)):
        pts = sp.bezier_points
        n = len(pts)
        knots = [list(p.co / meters) for p in pts]
        check("%s spline %d: points at the knots" % (label, k),
              close([c for p in knots for c in p], [c for x in w["knots"] for c in x["pos"]], MATRIX_TOLERANCE))
        check("%s spline %d: FREE handles" % (label, k),
              all(p.handle_left_type == p.handle_right_type == 'FREE' for p in pts))
        mids, expected = [], []
        for j, x in enumerate(w["knots"]):
            if x["mid"] is None:
                continue
            a, b = pts[j], pts[(j + 1) % n]
            mid = interpolate_bezier(a.co, a.handle_right, b.handle_left, b.co, 3)[1]
            mids += list(mid / meters)
            expected += x["mid"]
        check("%s spline %d: segment middles where 3ds Max interpolates them" % (label, k),
              close(mids, expected, MATRIX_TOLERANCE), "%s vs %s" % (["%.6g" % v for v in mids], expected))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = ob.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    faces = len(mesh.polygons)
    evaluated.to_mesh_clear()
    check(label + ": faces exactly when it renders", (faces > 0) == shape["renderable"], str(faces))


def check_section(label, ob, shape, meters):
    """A rectangular section: a bevel object of the width x length rectangle (any angle), hidden, unselectable, in
    the import's collection tree (the cleanup removes that tree; an unlinked one is lost on save)."""
    cu = ob.data
    sec = cu.bevel_object
    check(label + ": a bevel object, no round bevel", cu.bevel_mode == 'OBJECT' and sec is not None and
          sec.type == 'CURVE' and cu.bevel_depth == 0, "%s %r %g" % (cu.bevel_mode, sec, cu.bevel_depth))
    if sec is None or sec.type != 'CURVE':
        return
    root = bpy.data.collections.get(label.split("/")[0])  # the import's collection is named after the file
    flags = (sec.hide_viewport, sec.hide_render, sec.hide_select, sec.get("maxdrop_helper"))
    check(label + ": the section object hidden, marked, in the import's collection",
          flags == (True, True, True, "section") and root is not None and sec.name in root.all_objects,
          "%s %s" % (flags, [c.name for c in sec.users_collection]))
    pts = [p.co for sp in sec.data.splines for p in sp.points]
    half = math.hypot(shape["width"], shape["length"]) / 2 * meters
    check(label + ": the section a closed 2D rectangle of width x length", sec.data.dimensions == '2D' and
          sec.data.fill_mode == 'NONE' and len(sec.data.splines) == 1 and sec.data.splines[0].use_cyclic_u and
          len(pts) == 4 and all(abs(math.hypot(p.x, p.y) - half) < 1e-9 for p in pts) and
          abs((pts[0] - pts[1]).length - shape["width"] * meters) < 1e-9 and
          abs((pts[1] - pts[2]).length - shape["length"] * meters) < 1e-9, str([tuple(p) for p in pts]))


def check_shapes_more(obs, meters):
    """The rectangular sections against 3ds Max's render meshes (snapshotAsMesh renderMesh:true; the fixture's
    script): FixtureSection, a line along X with width 4, length 1 and angle 30, has at x = 0 the corners
    (Y, Z) = (-1.48205, 1.43301), (1.98205, -0.566987), (1.48205, -1.43301), (-1.98205, 0.566987) and a cap at each
    end; FixtureSectionLoop,
    a circle of radius 10 with width 3, length 1.5, spans 8.49005 .. 11.5099 out from its center (3ds Max mitres at
    its polyline points, Blender a little less) and Z -0.75 .. 0.75."""
    by_name = {ob.name: ob for ob in obs}
    depsgraph = bpy.context.evaluated_depsgraph_get()

    def verts(ob):
        evaluated = ob.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        out = [Vector(v.co) / meters for v in mesh.vertices]
        evaluated.to_mesh_clear()
        return out

    got = sorted({(round(v.y, 4), round(v.z, 4)) for v in verts(by_name["FixtureSection"]) if abs(v.x) < 1e-6})
    want = sorted((round(y, 4), round(z, 4)) for y, z in ((-1.48205, 1.43301), (1.98205, -0.566987),
                                                          (1.48205, -1.43301), (-1.98205, 0.566987)))
    check("shapes_more/FixtureSection: the section's corners where 3ds Max renders them",
          len(got) == 4 and close([c for p in got for c in p], [c for p in want for c in p], 1e-3),
          "%s vs %s" % (got, want))
    evaluated = by_name["FixtureSection"].evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    caps = [0.0, 0.0]  # the area of the faces lying in the planes x = 0 and x = 10, in square units
    for f in mesh.polygons:
        xs = [mesh.vertices[i].co.x / meters for i in f.vertices]
        for k, end in enumerate((0.0, 10.0)):
            if all(abs(x - end) < 1e-6 for x in xs):
                caps[k] += f.area / meters ** 2
    evaluated.to_mesh_clear()
    check("shapes_more/FixtureSection: capped at both ends, as 3ds Max caps it (width x length each)",
          all(abs(a - 4.0) < 1e-4 for a in caps), str(caps))
    loop = verts(by_name["FixtureSectionLoop"])
    radial = [math.hypot(v.x, v.y) for v in loop]
    zs = [v.z for v in loop]
    check("shapes_more/FixtureSectionLoop: the section across the circle and up",
          abs(min(radial) - 8.49005) < 0.02 and abs(max(radial) - 11.5099) < 0.02 and
          abs(min(zs) + 0.75) < 1e-6 and abs(max(zs) - 0.75) < 1e-6,
          "%g .. %g, z %g .. %g" % (min(radial), max(radial), min(zs), max(zs)))
    slots = {ob.name: [(s.link, s.material and s.material.name) for s in ob.material_slots]
             for ob in obs if ob.type == 'CURVE'}
    want = dict.fromkeys(slots, [])
    want.update(FixtureCurveStd=[('DATA', "FixtureCurveRed")], FixtureCurveMulti=[('DATA', "FixtureCurveSubOne")],
                FixtureCurveIds=[('DATA', "FixtureCurveSubOne"), ('DATA', "FixtureCurveSubTwo")],
                FixtureCurveMixed=[('DATA', "FixtureCurveSubTwo")])
    check("shapes_more: a curve's 3ds Max materials in slots on the curve (a Multi/Sub-Object's entries for its "
          "splines' IDs), none on the others", slots == want and len(slots) == 17, str(slots))
    indices = {name: [sp.material_index for sp in by_name[name].data.splines]
               for name in ("FixtureCurveIds", "FixtureCurveMixed", "FixtureCurveMulti")}
    check("shapes_more: each spline on the slot of its segments' material ID (FixtureCurveIds: ID 2 then ID 1; "
          "FixtureCurveMixed: its first segment's)",
          indices == {"FixtureCurveIds": [1, 0], "FixtureCurveMixed": [0], "FixtureCurveMulti": [0]}, str(indices))


def check_modifier_pivot(obs, meters):
    """FixtureBent's pivot alone is turned 30 degrees about Z: its base mesh lands where the source's does, moved by
    the 30 units between the two nodes (the offset rotation undoes the pivot's)."""
    by_name = {ob.name: ob for ob in obs}
    src, bent = by_name["FixtureSource"], by_name["FixtureBent"]
    a = [c / meters for v in src.data.vertices for c in src.matrix_world @ v.co]
    b = [c / meters for v in bent.data.vertices for c in bent.matrix_world @ v.co - Vector((30 * meters, 0, 0))]
    check("modifier_pivot: FixtureBent has a mesh of its own", src.data != bent.data)
    check("modifier_pivot: the rotated pivot leaves the object in place", close(b, a, BBOX_TOLERANCE))


def check_lookat(path, desc, obs, nodes, meters):
    """lookat: the Target objects are empties, not placeholders; by default nothing is constrained (the rotation is
    baked, checked with every world matrix above). With Keep Targets each node whose Look At a Track To can follow
    gets one, aimed at its target's object, and its evaluated world matrix is still 3ds Max's; a roll and the Y axis
    keep the baked rotation and the report names them."""
    targets = [ob.name for ob, o in zip(obs, nodes) if o["base_class_name"] == "Targetobject"]
    # the target cameras are cameras, the target spot a light: the Point helper is the one placeholder
    check("lookat: the five targets are empties, no placeholders", len(targets) == 5 and all(
        bpy.data.objects[t].type == 'EMPTY' for t in targets) and dict(desc.placeholders) == {"Point": 1},
        str(dict(desc.placeholders)))
    check("lookat: no constraint without Keep Targets", not any(ob.constraints for ob in obs))
    empty_scene()
    result = bpy.ops.import_scene.maxdrop(filepath=path, keep_targets=True)
    check("lookat Keep Targets: the operator finishes", result == {'FINISHED'}, str(result))
    bpy.context.view_layer.update()
    obs = objects_of(desc)
    by_index = {node.index: ob for node, ob in zip(desc.nodes, obs)}
    tracked = []
    for ob, node, o in zip(obs, desc.nodes, nodes):
        label = "lookat Keep Targets/%s" % o["name"]
        look = node.look_at
        cons = [(c.type, c.name) for c in ob.constraints]
        if look is None or look.track is None:
            check(label + ": no constraint", cons == [], str(cons))
            continue
        tracked.append(o["name"])
        c = ob.constraints.get("MaxDrop Target")
        check(label + ": one Track To aimed at its target", cons == [('TRACK_TO', "MaxDrop Target")] and
              c.target == by_index[look.target] and (c.track_axis, c.up_axis, c.use_target_z) ==
              (look.track, look.up, look.target_z), "%s %s" % (cons, c and (c.track_axis, c.up_axis)))
        got = max_rows(ob.matrix_world, meters)
        check(label + ": evaluated world matrix = 3ds Max's", close(got, o["transform"], MATRIX_TOLERANCE),
              "%s vs %s" % (["%.6g" % v for v in got], o["transform"]))
    check("lookat Keep Targets: the Look At nodes a Track To can aim", tracked == [
        "FixtureCam", "FixtureCamDown", "FixtureSpot", "FixtureCamChild", "FixtureLooker"], str(tracked))
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    named = [n for n in ("FixtureCamRoll", "FixtureLookerY") if any(
        n in line and "Keep Targets" in line for line in body.splitlines())]
    check("lookat Keep Targets: the report names the two kept fixed", named == ["FixtureCamRoll", "FixtureLookerY"],
          str(named))
    # a look-at whose target was not built, or that aims at itself, keeps its rotation and is named with the reason.
    # No .max reaches either guard (every node is built; a self-aim is damaged by reader.controllers, look_at None):
    # hand-built descriptions
    from types import SimpleNamespace
    from maxdrop.build import objects as build_objects
    from maxdrop.convert.scene import LookAtDescription
    lone = [bpy.data.objects.new("FixtureLone%d" % k, None) for k in range(2)]
    aim = ("TRACK_NEGATIVE_Z", "UP_Y", False, None)
    fake = SimpleNamespace(nodes=[SimpleNamespace(index=0, look_at=LookAtDescription(99, *aim)),
                                  SimpleNamespace(index=1, look_at=LookAtDescription(1, *aim))])
    kept = build_objects.track_targets(fake, SimpleNamespace(objects={0: lone[0], 1: lone[1]}))
    check("lookat Keep Targets: a missing or self target is returned with its reason, no constraint",
          kept == [(0, build_objects.NO_TARGET), (1, build_objects.SELF_TARGET)]
          and not any(ob.constraints for ob in lone), str(kept))
    for ob in lone:
        bpy.data.objects.remove(ob)
    # the note on the axis conversion: only when the file's up does not stay Blender's Z
    for forward, up, expected in (('X', 'Z', False), ('-Z', 'Y', True)):
        empty_scene()
        result = bpy.ops.import_scene.maxdrop(filepath=path, keep_targets=True, axis_forward=forward, axis_up=up)
        text = bpy.data.texts.get("MaxDrop Report")
        noted = text is not None and "Track To keeps Blender's Z up" in text.as_string()
        label = "lookat Keep Targets, Forward %s, Up %s" % (forward, up)
        check(label + ": the up note " + ("given" if expected else "not given"),
              result == {'FINISHED'} and noted == expected, "%s, noted %s" % (result, noted))


def _irs(path):
    """convert.scene.read of path and the slot plan of its materials, converted with the texture-map rules."""
    from maxdrop.convert import materials as convert_materials
    from maxdrop.convert import scene as convert_scene
    from maxdrop.convert import texmaps as convert_texmaps
    from maxdrop.reader import assets, cfb, materials as reader_materials, scene as reader_scene
    desc = convert_scene.read(path)
    with cfb.CompoundFile(path) as cf:
        sc = reader_scene.Scene.from_file(cf)
        graph = reader_materials.MaterialGraph(sc)
        tex = convert_texmaps.TexmapConverter(graph, assets.AssetTable.from_file(cf))
        conv = convert_materials.MaterialConverter(graph, texmaps=tex)
        slots = convert_materials.assign(desc, convert_materials.node_materials(sc, desc), conv)
    return desc, slots


def _bsdfs(material):
    """The Principled BSDFs of a material, the twins and mirrors of a reflection weight left out."""
    return [n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"
            and n.label not in (TWIN_LABEL, MIRROR_LABEL)]


def _shaders(material):
    """The Mix Shaders of a material's layers (a reflection weight's left out)."""
    return [n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeMixShader" and n.label != WEIGHT_LABEL]


def _principled(material):
    nodes = _bsdfs(material)
    return nodes[0] if len(nodes) == 1 else None


def _weight_mix(p):
    """The reflection weight's Mix Shader over Principled p, None when p's Specular IOR Level alone draws it."""
    out = next(s for s in p.outputs if s.identifier == "BSDF")
    return next((link.to_node for link in out.links if link.to_node.bl_idname == "ShaderNodeMixShader"
                 and link.to_node.label == WEIGHT_LABEL), None)


def _specular_socket(p):
    """The input the IR's specular drives: the reflection weight's factor, else Specular IOR Level."""
    mix = _weight_mix(p)
    return mix.inputs[0] if mix is not None else p.inputs["Specular IOR Level"]


def _constant_one(p, name):
    s = p.inputs.get(name)
    return s is not None and not s.is_linked and s.default_value >= 1.0


def check_specular(label, p, ir, present):
    """Specular IOR Level from the IR's reflection weight w: a weight map or a constant between 0 and 1 is a Mix
    Shader by w over a twin without reflection (Specular IOR Level 0.5 on p), else 0.5 x w (w taken at most 1) on p
    alone; a constant metal or full transmission is 0.5 x w alone."""
    folded = _fold(ir.textures["specular"].root, present) if "specular" in ir.textures else LOST
    linked = folded is MAP
    w = None if linked else _mean(ir.specular.value if folded is LOST else folded)
    metal_glass = _constant_one(p, "Metallic") or _constant_one(p, "Transmission Weight")
    lone = metal_glass or (not linked and not 0 < w < 1)
    s, mix = p.inputs["Specular IOR Level"], _weight_mix(p)
    if lone:
        check("%s: Specular IOR Level %s, no reflection weight" % (label, "linked" if linked else "value"),
              mix is None and s.is_linked == linked and (linked or _value_ok(s, w * SPECULAR_LEVEL if metal_glass
                                                                       else max(0.0, min(1.0, w)) * SPECULAR_LEVEL)),
              "mix %s, linked %s, %r vs %r" % (mix is not None, s.is_linked, s.default_value, w))
        return
    fac = mix.inputs[0] if mix is not None else None
    mirror = not ir.fresnel and (linked or ir.specular.map is None)
    level = 0.0 if mirror else SPECULAR_LEVEL
    check("%s: reflection weight %s %s, Specular IOR Level %.1f" % (
              label, "linked" if linked else "value", "under a mirror" if mirror else "over a twin", level),
          mix is not None and not s.is_linked and _value_ok(s, level) and fac.is_linked == linked
          and (linked or _value_ok(fac, w)),
          "mix %s, level %r, factor %r vs %r" % (mix is not None, s.default_value,
                                                  None if fac is None else fac.default_value, w))
    if mix is not None:
        (check_mirror if mirror else check_twin)(label, p, mix)


def _same_inputs(p, copy, own):
    """The identifiers of p's inputs copy does not repeat: own {name: value} unlinked on copy, the others p's link
    or value."""
    bad = []
    for a, b in zip(p.inputs, copy.inputs):
        if a.name in own:
            va, want = b.default_value, own[a.name]
            same = not b.is_linked and (close(list(va), list(want), 1e-6) if hasattr(want, "__len__")
                                        else abs(float(va) - want) <= 1e-6)
        elif a.is_linked:
            same = b.is_linked and b.links[0].from_socket == a.links[0].from_socket
        elif hasattr(a, "default_value"):
            va, vb = a.default_value, b.default_value
            same = not b.is_linked and (close(list(va), list(vb), 1e-6) if hasattr(va, "__len__")
                                        else abs(float(va) - float(vb)) <= 1e-6)
        else:
            same = True
        if not same:
            bad.append(a.identifier)
    return bad


def check_mirror(label, p, mix):
    """A weight without Fresnel: the Mix Shader's first shader is p (Specular IOR Level 0), its second p's copy as
    a white metal: p's links and values but Metallic 1, Base Color white (both unlinked), Specular IOR Level 0.5."""
    copy = _from(mix.inputs[2])
    ok = copy is not None and copy.bl_idname == "ShaderNodeBsdfPrincipled" and copy.label == MIRROR_LABEL \
        and _from(mix.inputs[1]) == p
    bad = _same_inputs(p, copy, {"Metallic": 1.0, "Base Color": (1.0, 1.0, 1.0, 1.0),
                                 "Specular IOR Level": SPECULAR_LEVEL}) if ok else []
    check(label + ": the mirror is the Principled BSDF as a white metal", ok and bad == [], str(bad))


def check_twin(label, p, mix):
    """The Mix Shader's first shader is p's twin: p's links and values, Specular IOR Level 0; its second p."""
    twin = _from(mix.inputs[1])
    ok = twin is not None and twin.bl_idname == "ShaderNodeBsdfPrincipled" and twin.label == TWIN_LABEL \
        and _from(mix.inputs[2]) == p
    bad = _same_inputs(p, twin, {"Specular IOR Level": 0.0}) if ok else []
    check(label + ": the twin is the Principled BSDF without reflection", ok and bad == [], str(bad))


def _layers_of(ir):
    """Every Layer of a MaterialIR, its layers' layers included, in the order the builder draws them."""
    out = []
    for layer in ir.layers:
        out.append(layer)
        out.extend(_layers_of(layer.ir))
    return out


def _alpha_of(ir, present):
    """(alpha linked, the constant alpha or None) the builder gives a Principled BSDF filled from ir."""
    folded = _fold(ir.textures["alpha"].root, present) if "alpha" in ir.textures else LOST
    if folded is MAP:
        return True, None
    return False, _mean(ir.alpha.value if folded is LOST else folded)


def _value_ok(socket, want):
    """The socket's value against want; a color input stores no negative, so want is held at 0 there."""
    got = socket.default_value
    if isinstance(want, (tuple, list)):
        if socket.type == 'RGBA':
            want = [max(0.0, w) for w in want]
        return close(list(got)[:3], list(want)[:3], VALUE_TOLERANCE)
    return abs(float(got) - float(want)) <= VALUE_TOLERANCE


def _mean(v):
    return sum(v[:3]) / 3.0 if isinstance(v, (tuple, list)) else v


def _images_of(ir):
    """The texmaps.Image nodes of every texture graph of an IR, its layers' and their masks' included, each once."""
    from maxdrop.convert import texmaps as tx
    seen, out = set(), []
    stack = [g.root for g in ir.textures.values()]
    for layer in _layers_of(ir):
        stack.extend(g.root for g in layer.ir.textures.values())
        if layer.graph is not None:
            stack.append(layer.graph.root)
    while stack:
        n = stack.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        if isinstance(n, tx.Image):
            out.append(n)
        stack.extend(tx._children(n))
    return out


MAP, LOST = "map", "lost"  # what _fold gives for a graph a node drives, and for one whose images are all missing


def _fold(n, present):
    """What build.materials makes of a texture graph: MAP when a node drives the input, LOST when the missing images
    leave nothing, else the constant it folds to. present: whether the graph's image files were found. Written from
    the builder's rules (a missing side of a Mix or Multiply gives the other, a Composite drops missing layers)."""
    from maxdrop.convert import texmaps as tx
    if isinstance(n, tx.Constant):
        return n.value
    if isinstance(n, tx.Image):
        return MAP if present else LOST
    if isinstance(n, tx.Invert):
        v = _fold(n.input, present)
        if v in (MAP, LOST):
            return v
        return tuple(1.0 - c for c in v) if isinstance(v, tuple) else 1.0 - v
    if isinstance(n, tx.Mix):
        a, b = _fold(n.a, present), _fold(n.b, present)
        return (b if a is LOST else a) if LOST in (a, b) else MAP
    if isinstance(n, tx.Multiply):
        a, b = _fold(n.a, present), _fold(n.b, present)
        if LOST in (a, b):
            other = b if a is LOST else a
            return MAP if other is MAP else LOST
        if MAP in (a, b):
            return MAP
        return tuple(x * y for x, y in zip(a, b)) if isinstance(a, tuple) else a * b
    if isinstance(n, tx.Blend):
        a, b = _fold(n.a, present), _fold(n.b, present)
        if LOST in (a, b):
            other = b if a is LOST else a
            return MAP if other is MAP else LOST
        if MAP in (a, b):
            return MAP
        return tx.blend_value(n.op, a, b, n.gamma)
    if isinstance(n, tx.ColorCorrect):
        v = _fold(n.input, present)
        changes = n.hue % 1.0 != 0.0 or n.saturation != 1.0 or n.brightness or n.contrast or n.gain != 1.0 \
            or n.gamma != 1.0 or tuple(n.rewire) != tx.REWIRE_NONE
        return v if v is LOST or not changes else MAP
    if isinstance(n, (tx.Adjust, tx.Tint)):  # made only when they change something: nodes
        v = _fold(n.input, present)
        return LOST if v is LOST else MAP
    if isinstance(n, tx.Facing):
        return MAP
    if isinstance(n, (tx.Remap, tx.Smoothstep)):  # a float through a curve: a node over its input
        v = _fold(n.input, present)
        return LOST if v is LOST else MAP
    if isinstance(n, tx.Composite):
        layers = [(v, la) for v, la in ((_fold(la.node, present), la) for la in n.layers) if v is not LOST]
        if not layers:
            return LOST
        v, la = layers[0]
        masked = la.mask is not None and _fold(la.mask, present) is not LOST
        return v if len(layers) == 1 and la.opacity >= 1.0 and not masked else MAP
    image = tx.first_image(n)
    return _fold(image, present) if image is not None else LOST


def _normal_linked(tex, present):
    from maxdrop.convert import texmaps as tx
    linked = False
    for key in ("normal", "bump"):
        if key in tex:
            r = tex[key].root
            if isinstance(r, tx.NormalMap):
                linked = linked or _fold(r.input, present) is MAP or (
                    r.bump is not None and _fold(r.bump.input, present) is MAP)
            else:
                linked = linked or _fold(r.input if isinstance(r, tx.Bump) else r, present) is MAP
    return linked


def check_principled(label, material, ir, present=False):
    """A Blender material against its MaterialIR: every Principled input (linked when a node drives it, else the
    value the graph folds to, or the IR's when its images are missing), the render method, one Image Texture node
    per file. present: whether the texture files were found."""
    layers = _layers_of(ir)
    bsdfs = _bsdfs(material) if material is not None and material.node_tree else []
    p = bsdfs[0] if len(bsdfs) == 1 + len(layers) else None
    check(label + ": one Principled BSDF, and one per layer", p is not None, "%d for %d layers" % (len(bsdfs),
                                                                                              len(layers)))
    if p is None:
        return
    if layers:
        check_layers(label, material, layers, present)
    tex = ir.textures
    wants = [
        ("Base Color", "base_color", ir.base_color.value, None),
        ("Metallic", "metallic", ir.metallic.value, 1.0),
        ("Roughness", "roughness", ir.roughness.value, 1.0),
        ("Transmission Weight", "transmission", ir.transmission.value, 1.0),
        ("Emission Color", "emission_color", ir.emission_color.value, None),
        ("Alpha", "alpha", ir.alpha.value, 1.0),
    ]
    alpha = None
    check_specular(label, p, ir, present)
    for socket, key, want, scale in wants:
        s = p.inputs[socket]
        folded = _fold(tex[key].root, present) if key in tex else LOST
        linked = folded is MAP
        if folded not in (MAP, LOST):
            want = folded
        if scale is not None:
            want = _mean(want) * scale
        if socket == "Alpha":
            alpha = None if linked else want
        check("%s: %s %s" % (label, socket, "linked" if linked else "value"),
              s.is_linked == linked and (linked or _value_ok(s, want)),
              "linked %s, %r vs %r" % (s.is_linked, tuple(s.default_value) if hasattr(s.default_value, "__len__")
                                       else s.default_value, want))
    values = [("IOR", ir.ior), ("Emission Strength", ir.emission_strength), ("Coat Weight", ir.coat_weight),
              ("Coat Roughness", ir.coat_roughness), ("Coat IOR", ir.coat_ior), ("Coat Tint", ir.coat_color),
              ("Subsurface Weight", ir.subsurface_weight)]
    if ir.subsurface_weight > 0:
        values += [("Subsurface Radius", ir.subsurface_color), ("Subsurface Scale", ir.subsurface_radius)]
    if ir.sheen_weight > 0:
        values += [("Sheen Weight", ir.sheen_weight), ("Sheen Tint", ir.sheen_color),
                   ("Sheen Roughness", ir.sheen_roughness)]
    for socket, want in values:
        check("%s: %s" % (label, socket), _value_ok(p.inputs[socket], want),
              "%r vs %r" % (p.inputs[socket].default_value, want))
    normal = _normal_linked(tex, present)
    check(label + ": Normal linked iff a normal or bump map with its image", p.inputs["Normal"].is_linked == normal)
    thin = p.inputs.get("Thin Wall")
    check(label + ": Thin Wall", (thin is None and bpy.app.version < (5, 0, 0)) or
          (thin is not None and bool(thin.default_value) == ir.thin_walled))
    alphas = [(alpha is None, alpha)] + [_alpha_of(layer.ir, present) for layer in layers]
    method = 'DITHERED' if any(linked for linked, _v in alphas) else \
        'BLENDED' if any(v is not None and v < 1.0 for _l, v in alphas) else 'DITHERED'
    check(label + ": surface_render_method", material.surface_render_method == method,
          "%s vs %s" % (material.surface_render_method, method))
    want_images = sorted({img.name for img in _images_of(ir)})
    got_images = sorted({n.label for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"})
    check(label + ": one Image Texture node per file", got_images == want_images, "%s vs %s" % (got_images,
                                                                                               want_images))
    loose = [n.label for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.image is None
             and any(o.is_linked for o in n.outputs)]
    check(label + ": an Image Texture node without an image feeds nothing", loose == [], str(loose))
    mixed = _color_into_float(material)
    check(label + ": no color output linked into a float input (a data map is the mean of its channels)",
          mixed == [], str(mixed))


def check_layers(label, material, layers, present=False):
    """A layered material: a Mix Shader per layer, the last one into the output; a layer whose mask graph a node
    drives has a linked factor, any other its amount (times the mask's constant)."""
    nodes = material.node_tree.nodes
    mixes = _shaders(material)
    check(label + ": a Mix Shader per layer", len(mixes) == len(layers), "%d for %d" % (len(mixes), len(layers)))
    out = next(n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial")
    surface = out.inputs["Surface"]
    check(label + ": the top Mix Shader is the surface",
          surface.is_linked and surface.links[0].from_node in mixes)
    plain = []
    for layer in layers:
        folded = _fold(layer.graph.root, present) if layer.graph is not None else LOST
        if folded is not MAP:
            plain.append(round(min(1.0, layer.amount * (1.0 if folded is LOST else _mean(folded))), 5))
    plain.sort()
    got = sorted(round(m.inputs[0].default_value, 5) for m in mixes if not m.inputs[0].is_linked)
    linked = sum(1 for m in mixes if m.inputs[0].is_linked)
    check(label + ": the layers' amounts, masks linked", got == plain and linked == len(layers) - len(plain),
          "%s vs %s, %d linked" % (got, plain, linked))


def check_fixture_materials(name, plan, desc, obs):
    """Each face slot of each imported object holds a material equal to the IR the same file converts to (plan:
    the slot plan of _irs)."""
    by_index = {node.index: ob for node, ob in zip(desc.nodes, obs)}
    checked = set()
    corona = []
    for slots in list(plan.values()) + list(plan.curves.values()):
        for s, irs in enumerate(slots.slots):
            for node, ir in zip(slots.users, irs):
                ob = by_index[node]
                material = ob.material_slots[s].material if s < len(ob.material_slots) else None
                if ir is None:
                    check("%s/%s: slot %d empty" % (name, ob.name, s), material is None)
                    continue
                if material is None or material.name in checked:
                    check("%s/%s: slot %d has a material" % (name, ob.name, s), material is not None)
                    continue
                checked.add(material.name)
                check("%s/%s: material named after the 3ds Max material" % (name, material.name),
                      material.name.split(".")[0] == (ir.name or "Material").split(".")[0], ir.name)
                check_principled("%s/%s" % (name, material.name), material, ir)
                if ir.source == "CoronaPhysicalMtl":
                    corona.append(material)
    if name == "corona_physical":  # absolute: check_principled follows the IR, which drew 0.25 (maxdrop-em3.121)
        sockets = [(m.name, n.inputs["Specular IOR Level"]) for m in corona for n in _bsdfs(m)]
        levels = [(name, s.is_linked, round(s.default_value, 6)) for name, s in sockets]
        check("corona_physical: every CoronaPhysicalMtl reflects the IOR's own Fresnel (Specular IOR Level 0.5)",
              len(levels) >= 3 and all(not linked and v == 0.5 for _n, linked, v in levels), str(levels))
    for key, cd in desc.curves.items():  # each spline on its slot; without a plan, 0
        ob = next((by_index[u] for u in cd.users if u in by_index), None)
        if ob is None:
            continue
        got = [sp.material_index for sp in ob.data.splines]
        want = plan.curves[key].indices.tolist() if key in plan.curves else [0] * len(cd.splines)
        check("%s/%s: each spline on its material's slot" % (name, ob.name), got == want, "%s vs %s" % (got, want))
    if name == "falloff_curve":
        check_falloff_curve(textured=False)
    if name == "vray_maps":
        check_vray_maps_nodes(textured=False)
        text = bpy.data.texts.get("MaxDrop Report")
        lines = text.as_string().split("\n") if text else []
        names = sorted(("fixture_diffuse.png", "fixture_reflect.png", "fixture_gloss.png", "fixture_bump.png",
                        "fixture_opacity.png", "fixture_normal.png", "fixture_normal_bump.png"), key=str.casefold)
        at = lines.index("  Textures not found: 7") if "  Textures not found: 7" in lines else -1
        check("vray_maps: the report names each texture not found, once, by file name",
              at >= 0 and lines[at + 1:at + 8] == ["    " + n for n in names], "\n".join(lines[-14:]))
        empty = [n.label for m in bpy.data.materials for n in m.node_tree.nodes
                 if n.bl_idname == "ShaderNodeTexImage" and n.image is not None]
        check("vray_maps: texture nodes without an image when the files are missing", empty == [], str(empty))


def check_falloff_curve(textured):
    """falloff_curve imported: each edited Falloff curve is a Float Curve on the Falloff's ratio that evaluates as 3ds
    Max 2020 does (tests/fixtures/falloff_curve.curves.jsonl, x = k / 64) and drives an unclamped Mix; the default
    curve makes none. Each Mix's Use Curve: textured, a Map Range SMOOTHSTEP (lower < upper) or a step
    (1 - LESS_THAN) over its mask; without the mask's file, the mix amount through the curve."""
    with open(os.path.join(ROOT, "tests", "fixtures", "falloff_curve.curves.jsonl"), encoding="ascii") as f:
        rows = {r["name"]: r["y"] for r in map(json.loads, f)}
    ratios = {"FixtureCurveBezier": "ShaderNodeLayerWeight", "FixtureCurveCorner": "ShaderNodeMath",
              "FixtureCurveOvershoot": "ShaderNodeFresnel", "FixtureCurveClamped": "ShaderNodeLayerWeight"}
    for name, ratio in ratios.items():
        mix = _from(_principled(bpy.data.materials[name]).inputs["Base Color"])
        fc = _from(_input(mix, "Factor_Float"))
        ok = fc is not None and fc.bl_idname == "ShaderNodeFloatCurve"
        check("falloff_curve/%s: a Float Curve drives the Mix, unclamped" % name,
              ok and not mix.clamp_factor and _from(_input(fc, "Value")).bl_idname == ratio
              and abs(_input(fc, "Factor").default_value - 1.0) < 1e-6,
              "%s %s" % (getattr(fc, "bl_idname", None), getattr(mix, "clamp_factor", None)))
        if ok:
            mapping = fc.mapping
            mapping.initialize()
            err = max(abs(mapping.evaluate(mapping.curves[0], k / 64.0) - y) for k, y in enumerate(rows[name]))
            check("falloff_curve/%s: the Float Curve evaluates as 3ds Max's curve, within 0.001" % name, err < 1e-3,
                  str(err))
    linear = bpy.data.materials["FixtureCurveLinear"]
    check("falloff_curve: the default curve makes no Float Curve",
          not any(n.bl_idname == "ShaderNodeFloatCurve" for n in linear.node_tree.nodes)
          and _from(_input(_from(_principled(linear).inputs["Base Color"]), "Factor_Float")).bl_idname
          == "ShaderNodeLayerWeight")
    amount = _from(_principled(bpy.data.materials["FixtureMixCurveAmount"]).inputs["Base Color"])
    check("falloff_curve: a Mix's Use Curve folded into its amount (0.4 -> 0.15625)",
          amount.bl_idname == "ShaderNodeMix" and _from(_input(amount, "Factor_Float")) is None
          and abs(_input(amount, "Factor_Float").default_value - 0.15625) < 1e-4)
    for name, kind in (("FixtureMixCurve", "SMOOTHSTEP"), ("FixtureMixCurveStep", "STEP")):
        mix = _from(_principled(bpy.data.materials[name]).inputs["Base Color"])
        factor = _from(_input(mix, "Factor_Float"))
        if not textured:
            check("falloff_curve/%s: without its mask's file, the mix amount through the curve (0)" % name,
                  factor is None and abs(_input(mix, "Factor_Float").default_value) < 1e-6)
            continue
        if kind == "SMOOTHSTEP":
            ok = factor is not None and factor.bl_idname == "ShaderNodeMapRange" and \
                factor.interpolation_type == 'SMOOTHSTEP' and factor.clamp and \
                close([_input(factor, k).default_value for k in ("From Min", "From Max", "To Min", "To Max")],
                      [0.2, 0.9, 0.0, 1.0], 1e-6)
        else:  # 1 - LESS_THAN(mask, lower)
            less = _from(factor.inputs[1]) if factor is not None and factor.bl_idname == "ShaderNodeMath" else None
            ok = less is not None and factor.operation == 'SUBTRACT' and factor.inputs[0].default_value == 1.0 \
                and less.operation == 'LESS_THAN' and abs(less.inputs[1].default_value - 0.6) < 1e-6
            factor = less
        image = _from(_input(factor, "Value") if kind == "SMOOTHSTEP" else factor.inputs[0]) if factor else None
        check("falloff_curve/%s: Use Curve as a %s over its mask image" % (name, kind),
              ok and image is not None and image.bl_idname in ("ShaderNodeTexImage", "ShaderNodeVectorMath"),
              "%s %s" % (getattr(factor, "bl_idname", None), getattr(image, "bl_idname", None)))


def check_curve_step():
    """A Remap with two points at one x (curve_samples' vertical step: a segment with no width) as a Float Curve:
    the points stay in their order, also when the step is the first two points (set, not added) or comes out of
    curve_samples, and the curve evaluates as the polyline on either side of the step (at the step x itself
    either side is right) and flat past the ends."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.reader.materials import CurvePoint

    def polyline(points, x):
        if x <= points[0][0]:
            return points[0][1]
        for (xa, ya), (xb, yb) in zip(points, points[1:]):
            if xa <= x < xb:
                return ya + (yb - ya) * (x - xa) / (xb - xa)
        return points[-1][1]

    corner = [CurvePoint((0.0, 1.0), (0.0, 1.0), (0.2, 1.0), 0), CurvePoint((0.5, 0.9), (0.4, 0.9), (0.5, 0.9), 0),
              CurvePoint((0.5, 0.1), (0.5, 0.1), (0.6, 0.1), 0), CurvePoint((1.0, 0.0), (0.9, 0.0), (1.0, 0.0), 0)]
    cases = (("falling step", ((0.0, 1.0), (0.5, 0.9), (0.5, 0.1), (1.0, 0.0))),
             ("rising step", ((0.0, 0.0), (0.5, 0.2), (0.5, 0.8), (1.0, 1.0))),
             ("step in the first two points", ((0.2, 0.9), (0.2, 0.1), (1.0, 0.0))),
             ("step from curve_samples", tx.curve_samples(corner)))
    empty_scene()
    builder = build_materials.MaterialBuilder()
    for label, points in cases:
        ir = cm.MaterialIR(1, "CurveStep", "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
        mix = tx.Mix(tx.Constant((0.0, 0.0, 0.0)), tx.Constant((1.0, 1.0, 1.0)), 0.0, tx.Remap(tx.Facing(), points))
        ir.textures = {"base_color": tx.TextureGraphIR(mix, tx.COLOR)}
        material = builder.make(ir)
        fc = next((n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeFloatCurve"), None) \
            if material is not None else None
        if fc is None:
            check("curve step/%s: a Float Curve" % label, False)
            continue
        mapping = fc.mapping
        mapping.initialize()
        stored = [tuple(p.location) for p in mapping.curves[0].points]
        steps = [a[0] for a, b in zip(points, points[1:]) if a[0] == b[0]]
        check("curve step/%s: the points kept in their order" % label,
              len(stored) == len(points) and all(close(a, b, 1e-6) for a, b in zip(stored, points)),
              "%d points, at the step %s" % (len(stored), [p for p in stored if any(abs(p[0] - s) < 1e-6
                                                                                 for s in steps)]))
        xs = [k / 64.0 for k in range(-4, 69)] + [x + d for x in steps for d in (-0.01, 0.01)]
        err = max(abs(mapping.evaluate(mapping.curves[0], x) - polyline(points, x)) for x in xs
                  if all(abs(x - s) > 0.005 for s in steps))
        check("curve step/%s: evaluates as the polyline beside the step, within 0.001" % label, err < 1e-3, str(err))


def check_wrappers_report():
    """Right after the operator imported vray_wrappers: the text MaxDrop Report counts the materials and lists the
    wrappers it peeled by class, and the summary warns about them."""
    text = bpy.data.texts.get("MaxDrop Report")
    lines = text.as_string().split("\n") if text else []
    check("vray_wrappers: the report counts the materials built",
          any(line.startswith("Materials built: ") for line in lines), "\n".join(lines))
    check("vray_wrappers: the report lists the peeled wrappers by class",
          "  Wrappers peeled to their sub-material, by class: Shell Material 1, VRay2SidedMtl 1, VRayBlendMtl 1"
          in lines and lines.index("Approximated:") < lines.index(
              "  Wrappers peeled to their sub-material, by class: Shell Material 1, VRay2SidedMtl 1, VRayBlendMtl 1"),
          "\n".join(lines))


def _expected_mapping(tiling, offset, w_degrees):
    """The Mapping node values for a W angle only: location = 0.5 - R S (0.5 + offset), by hand."""
    c, s = math.cos(w_degrees * DEG), math.sin(w_degrees * DEG)
    x, y = tiling[0] * (0.5 + offset[0]), tiling[1] * (0.5 + offset[1])
    return (0.5 - (c * x - s * y), 0.5 - (s * x + c * y), 0.0), (0.0, 0.0, w_degrees * DEG), (tiling[0], tiling[1], 1.0)


def _mapping_of(material, label):
    """The values of the Mapping node feeding the Image Texture node labelled label."""
    tex = next(n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.label == label)
    link = tex.inputs["Vector"].links[0] if tex.inputs["Vector"].is_linked else None
    m = link.from_node if link is not None else None
    if m is None or m.bl_idname != "ShaderNodeMapping":
        return None, tex
    return tuple(tuple(m.inputs[k].default_value) for k in ("Location", "Rotation", "Scale")), tex


def _from(socket):
    """The node feeding an input, None when it is not linked."""
    return socket.links[0].from_node if socket.is_linked else None


def _input(node, identifier):
    return next(s for s in node.inputs if s.identifier == identifier)


def _meaned(socket):
    """The node whose output a DOT_PRODUCT by (1/3, 1/3, 1/3) turns into the float feeding socket, else None."""
    dot = _from(socket)
    if dot is None or dot.bl_idname != "ShaderNodeVectorMath" or dot.operation != 'DOT_PRODUCT' \
            or not close(list(_input(dot, "Vector_001").default_value), [1 / 3.0] * 3, 1e-6):
        return None
    return _from(_input(dot, "Vector"))


def _color_into_float(material):
    """Every link of a material's tree from a color output into a float input, as 'node.output -> node.input':
    Blender converts there by its luminance, where 3ds Max and V-Ray take the mean of the channels."""
    return ["%s.%s -> %s.%s" % (k.from_node.name, k.from_socket.identifier, k.to_node.name, k.to_socket.identifier)
            for k in material.node_tree.links if k.from_socket.type == 'RGBA' and k.to_socket.type == 'VALUE']


def check_vray_maps_nodes(textured):
    """FixtureVRayMaps' bitmaps: tiling, offset and W angle as Mapping values (the authoring script's numbers),
    extension REPEAT. With its textures: the gloss map's mean inverted (1 - x) into the Mix of the roughness, the bump
    map's mean a Bump node's height, FixtureVRayNormal's Normal Map node (strength 0.85, its green flipped) under its
    bump map's Bump node. Without them: no Normal Map node and the Normal input free."""
    m = bpy.data.materials.get("FixtureVRayMaps")
    for file, tile, offset, angle in (("fixture_diffuse.png", 2.0, 0.1, 15.0), ("fixture_reflect.png", 3.0, 0.2, 25.0),
                                      ("fixture_gloss.png", 4.0, 0.3, 35.0), ("fixture_bump.png", 5.0, 0.4, 45.0),
                                      ("fixture_opacity.png", 6.0, 0.5, 55.0)):
        got, tex = _mapping_of(m, file)
        want = _expected_mapping((tile, tile + 0.5), (offset, offset + 0.05), angle)
        ok = got is not None and all(close(g, w, VALUE_TOLERANCE) for g, w in zip(got, want))
        check("vray_maps/%s: Mapping location, rotation, scale" % file, ok, "%s vs %s" % (got, want))
        check("vray_maps/%s: extension REPEAT" % file, tex.extension == 'REPEAT', tex.extension)
    n = bpy.data.materials.get("FixtureVRayNormal")
    if not textured:
        check("vray_maps without textures: no Normal Map node, the Normal input free",
              not any(x.bl_idname == "ShaderNodeNormalMap" for x in n.node_tree.nodes)
              and not _principled(n).inputs["Normal"].is_linked)
        return
    mix = _from(_principled(m).inputs["Roughness"])
    inv = _from(_input(mix, "B_Float")) if mix is not None and mix.bl_idname == "ShaderNodeMix" else None
    gloss = _meaned(inv.inputs[1]) if inv is not None and inv.bl_idname == "ShaderNodeMath" else None
    check("vray_maps: the gloss map as 1 - its mean into the roughness Mix at 73 %, glossiness 1 beside it",
          gloss is not None and gloss.label == "fixture_gloss.png" and inv.operation == 'SUBTRACT'
          and abs(inv.inputs[0].default_value - 1.0) < 1e-6 and abs(_input(mix, "Factor_Float").default_value - 0.73)
          < 1e-5 and abs(_input(mix, "A_Float").default_value) < 1e-6)
    bump = _from(_principled(m).inputs["Normal"])
    check("vray_maps: the bump map through a Bump node of strength 0.64",
          bump is not None and bump.bl_idname == "ShaderNodeBump" and not bump.invert
          and abs(bump.inputs["Strength"].default_value - 0.64) < 1e-5
          and getattr(_meaned(bump.inputs["Height"]), "label", None) == "fixture_bump.png")
    top = _from(_principled(n).inputs["Normal"])
    nm = _from(top.inputs["Normal"]) if top is not None and top.bl_idname == "ShaderNodeBump" else None
    comb = _from(nm.inputs["Color"]) if nm is not None and nm.bl_idname == "ShaderNodeNormalMap" else None
    green = _from(comb.inputs["Green"]) if comb is not None and comb.bl_idname == "ShaderNodeCombineColor" else None
    sep = _from(green.inputs[1]) if green is not None and green.bl_idname == "ShaderNodeMath" else None
    check("vray_maps: FixtureVRayNormal: Bump (its bump map) over a Normal Map node of strength 0.85, green 1 - G",
          sep is not None and sep.bl_idname == "ShaderNodeSeparateColor"
          and green.inputs[1].links[0].from_socket.identifier == "Green"
          and _from(comb.inputs["Red"]) == sep and abs(nm.inputs["Strength"].default_value - 0.85) < 1e-5
          and getattr(_meaned(top.inputs["Height"]), "label", None) == "fixture_normal_bump.png"
          and _from(sep.inputs["Color"]).label == "fixture_normal.png")


def check_failed_build_cleanup(max_path):
    """A build that fails after its materials were made: the operator removes the materials and images it made and
    leaves a material and an image that were there before."""
    from maxdrop.build import objects as build_objects
    keep_material = bpy.data.materials.new("UserMaterial")
    keep_image = bpy.data.images.new("UserImage", 2, 2)
    before = ({m.as_pointer() for m in bpy.data.materials}, {i.as_pointer() for i in bpy.data.images})
    original, made = build_objects.build_steps, []

    def failing(*args, **kwargs):
        built = yield from original(*args, **kwargs)
        made.append((len(built.materials), len(bpy.data.images)))
        raise RuntimeError("maxdrop test: build fails")

    build_objects.build_steps = failing
    try:
        try:
            bpy.ops.import_scene.maxdrop(filepath=max_path)
            raised = False
        except RuntimeError:
            raised = True
    finally:
        build_objects.build_steps = original
    after = ({m.as_pointer() for m in bpy.data.materials}, {i.as_pointer() for i in bpy.data.images})
    check("failed build: materials and images were made before it failed",
          raised and made and made[0][0] > 0 and made[0][1] > len(before[1]), str(made))
    check("failed build: the materials and images it made are removed, the user's stay",
          after == before and keep_material.name in bpy.data.materials and keep_image.name in bpy.data.images
          and not bpy.data.objects, "%d / %d materials, %d / %d images" % (
              len(after[0]), len(before[0]), len(after[1]), len(before[1])))
    bpy.data.materials.remove(keep_material)
    bpy.data.images.remove(keep_image)


def _write_png(path):
    img = bpy.data.images.new("maxdrop-probe", 4, 4)
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


CANCEL_KINDS = ("objects", "meshes", "curves", "lights", "cameras", "materials", "images", "collections", "texts",
                "node_groups", "worlds")


def _state():
    """What a cancelled run must leave as it found it: the datablocks of each kind, the scene camera, render size,
    the scene's World."""
    r = bpy.context.scene.render
    return ({kind: sorted(b.as_pointer() for b in getattr(bpy.data, kind)) for kind in CANCEL_KINDS},
            bpy.context.scene.camera, (r.resolution_x, r.resolution_y, r.resolution_percentage, r.pixel_aspect_x,
                                       r.pixel_aspect_y), bpy.context.scene.world)


def _cancel_run(paths):
    from maxdrop import ops
    opts = ops.ImportOptions(units='AUTO', scale_objects=1.0, use_image_search=True, object_filter={'MATERIAL', 'UV'},
                             modifiers='KEEP', light_strength=ops.LIGHT_STRENGTH, keep_targets=False,
                             axis_forward='Y', axis_up='Z')
    return ops._Run(opts, list(paths), {}, bpy.context)


def _advance(steps, until, limit=100000):
    """next() on steps until until() holds (a short sleep while a worker thread reads); whether it held before the
    run ended."""
    import time
    from maxdrop import ops
    for _ in range(limit):
        if until():
            return True
        try:
            if next(steps) is ops._WAIT:
                time.sleep(0.005)
        except StopIteration:
            return False
    return False


def check_cancel(textured, other):
    """The modal import's step generator (ops._Run.steps), driven without a window: closed early (Esc) it leaves
    the datablocks, the scene camera and the render size as they were, the user's own material and image too. textured:
    a .max whose textures are found (materials and images are made); other: a .max with a camera (it sets the scene
    camera and render size)."""
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    keep_material = bpy.data.materials.new("UserMaterial")
    keep_image = bpy.data.images.new("UserImage", 2, 2)
    before = _state()
    images = len(bpy.data.images)

    run = _cancel_run([textured])
    steps = run.steps()
    held = _advance(steps, lambda: len(bpy.data.images) > images)
    made = len(bpy.data.objects), len(bpy.data.materials), len(bpy.data.images)
    steps.close()
    check("cancel: one file closed during its build, after materials and images were made", held, str(made))
    check("cancel: one file: every datablock it made is removed, the user's stay", _state() == before,
          "%s | %s" % (_state(), before))

    run = _cancel_run([other, textured])
    steps = run.steps()
    held = _advance(steps, lambda: len(run._made) == 1 and len(bpy.data.images) > images)
    camera = bpy.context.scene.camera
    camera = camera is not None and camera.type == 'CAMERA'
    steps.close()
    check("cancel: two files closed in the second one's build, the first one finished with its camera",
          held and camera)
    check("cancel: two files: both removed, the report text too, the scene camera and render size put back",
          _state() == before, "%s | %s" % (_state(), before))

    run = _cancel_run([textured])
    steps = run.steps(threaded=True)
    from maxdrop import ops
    waited = next(steps) is ops._WAIT
    steps.close()
    check("cancel: threaded, closed while the worker reads: nothing made", waited and _state() == before)
    run = _cancel_run([other, textured])
    steps = run.steps(threaded=True)
    held = _advance(steps, lambda: len(run._made) == 1 and len(bpy.data.objects) > len(before[0]["objects"]) + 1)
    steps.close()
    check("cancel: threaded, two files closed in the second one's build: nothing left",
          held and _state() == before, "%s | %s" % (_state(), before))

    run = _cancel_run([other, textured])
    steps = run.steps(threaded=True)
    ended = not _advance(steps, lambda: False)
    report = bpy.data.texts.get("MaxDrop Report")
    check("cancel: threaded, run to its end: both files imported, the run's report written",
          ended and len(run._made) == 2 and bpy.context.scene.camera is not None and report is not None
          and report.as_string().count("MaxDrop import report: ") == 2,
          "%s %d %s" % (ended, len(run._made), report and report.as_string()[:200]))
    run.undo()
    check("cancel: undo() after a finished run removes it", _state() == before, "%s | %s" % (_state(), before))

    run = _cancel_run([os.path.join(os.path.dirname(other), "shapes_more.max")])  # its sections: hidden objects
    steps = run.steps()
    ended = not _advance(steps, lambda: False)
    sections = sum(1 for ob in bpy.data.objects if ob.get("maxdrop_helper") == "section")
    run.undo()
    check("cancel: undo() removes the rectangular sections' objects and curves too",
          ended and sections == 2 and _state() == before, "%d sections | %s | %s" % (sections, _state(), before))
    bpy.data.materials.remove(keep_material)
    bpy.data.images.remove(keep_image)


def check_run_guards(textured):
    """The modal runner's safety nets without a window: an undo or file load elsewhere closes the active run
    (ops._stop_active), the runner's teardown never leaves a run active even when the window manager raises, the
    windowed import keeps its settings as the last-used ones (ops._store_last), and a cancelled read still running
    keeps the next import waiting (ops._busy)."""
    import threading
    import types
    from maxdrop import ops
    empty_scene()
    before = _state()
    run = _cancel_run([textured])
    steps = run.steps()
    run.close = steps.close
    held = _advance(steps, lambda: len(bpy.data.objects) > 0)
    ops._ACTIVE.append(run)
    ops._guard(True)
    try:
        guarded = all(ops._stop_active in getattr(bpy.app.handlers, n) for n in ops._GUARDED)
        ops._stop_active()
        check("guards: an undo or file load elsewhere closes the active run, nothing left",
              held and guarded and run.stopped and _state() == before, "%s | %s" % (_state(), before))

        def raising(*_args):
            raise RuntimeError("maxdrop test: window manager fails")

        wm = types.SimpleNamespace(event_timer_remove=raising, progress_end=raising)
        context = types.SimpleNamespace(window_manager=wm, workspace=types.SimpleNamespace(status_text_set=raising))
        runner = types.SimpleNamespace(_run=run, _timer=object())
        ops.MAXDROP_OT_import_progress._teardown(runner, context)
        check("guards: teardown with a failing window manager: no run active, the handlers removed",
              not ops._ACTIVE and not any(ops._stop_active in getattr(bpy.app.handlers, n) for n in ops._GUARDED)
              and runner._timer is None and not ops._busy())
    finally:
        ops._ACTIVE.clear()
        ops._guard(False)

    source = types.SimpleNamespace(units='CENTIMETERS', scale_objects=2.0, light_strength=2.5, keep_targets=True,
                                   modifiers='IGNORE', object_filter={'UV'}, pack_scene="not kept")
    ops._store_last(source, bpy.context.window_manager)
    last = bpy.context.window_manager.operator_properties_last("import_scene.maxdrop")
    check("guards: the windowed import's settings kept as the last-used ones (Scene is not)",
          last.units == 'CENTIMETERS' and abs(last.scale_objects - 2.0) < 1e-6 and abs(last.light_strength - 2.5) < 1e-6
          and last.keep_targets and last.modifiers == 'IGNORE' and set(last.object_filter) == {'UV'}
          and last.pack_scene == "",
          "%s %s %s %s %s %s %r" % (last.units, last.scale_objects, last.light_strength, last.keep_targets,
                                    last.modifiers, set(last.object_filter), last.pack_scene))
    for name in ("units", "scale_objects", "light_strength", "keep_targets", "modifiers", "object_filter"):
        last.property_unset(name)

    release = threading.Event()
    steps = ops._in_thread(release.wait, 30)
    waited = next(steps) is ops._WAIT
    steps.close()
    busy = ops._busy()
    release.set()
    for worker in list(ops._WORKERS):
        worker.join(10)
    check("guards: a cancelled read still running keeps the next import waiting, until it ends",
          waited and "still reading" in busy and ops._busy() == "", busy)


def check_read_cancel(path):
    """Esc while a threaded run reads: the reading stops at the next node (convert.scene.describe's cancel check), so
    close() ends the worker and the next import is not refused (ops._busy). The read is slowed per node."""
    import time
    from maxdrop import ops
    from maxdrop.convert import scene as convert_scene
    empty_scene()
    before = _state()
    original, calls = convert_scene.blender_matrix, []

    def slow(*args, **kwargs):
        calls.append(None)
        time.sleep(0.2)  # twice per node: the read of every node takes 0.4 s
        return original(*args, **kwargs)

    convert_scene.blender_matrix = slow
    try:
        run = _cancel_run([path])
        steps = run.steps(threaded=True)
        held = _advance(steps, lambda: len(calls) > 0)
        start = time.perf_counter()
        steps.close()
        closed = time.perf_counter() - start
        while ops._busy() and time.perf_counter() - start < 1.0:
            time.sleep(0.01)
        free = ops._busy() == ""
        seen = len(calls)
        time.sleep(0.5)
        check("read cancel: closed while the worker reads, it stops at the next node: close() within 1 s, the next "
              "import not refused within 1 s, nothing made",
              held and closed < 1.0 and free and len(calls) == seen and _state() == before,
              "close %.2f s, busy %r, %d -> %d calls" % (closed, ops._busy(), seen, len(calls)))
    finally:
        for worker in list(ops._WORKERS):
            worker.join(60)
        convert_scene.blender_matrix = original

    # around the material conversion: before it (which is then not run) and after it
    opts, converted = _cancel_run([path]).opts, []
    real_slots = ops._material_slots

    def counting(after):
        calls = []

        def cancel():
            calls.append(None)
            return len(calls) > after
        return cancel, calls

    def slots(*args, **kwargs):
        converted.append(None)
        return real_slots(*args, **kwargs)

    ops._material_slots = slots
    try:
        cancel, calls = counting(10 ** 9)
        ops._read_scene(path, opts, (), cancel)
        total, outcomes = len(calls), []
        for after in (total - 2, total - 1):
            converted.clear()
            try:
                ops._read_scene(path, opts, (), counting(after)[0])
                outcomes.append(None)
            except convert_scene.Cancelled:
                outcomes.append(len(converted))
        check("read cancel: asked just before the material conversion (not run then) and just after it",
              outcomes == [0, 1], "%d calls, %s" % (total, outcomes))
    finally:
        ops._material_slots = real_slots


def _mesh_arrays(mesh):
    """Every array build.objects writes into a Mesh, as lists."""
    import numpy

    def get(seq, attr, width, dtype):
        out = numpy.empty(len(seq) * width, dtype=dtype)
        seq.foreach_get(attr, out)
        return out.tolist()

    arrays = {"co": get(mesh.vertices, "co", 3, numpy.float32),
              "vertex_index": get(mesh.loops, "vertex_index", 1, numpy.int32),
              "loop_start": get(mesh.polygons, "loop_start", 1, numpy.int32),
              "material_index": get(mesh.polygons, "material_index", 1, numpy.int32),
              "edges": get(mesh.edges, "vertices", 2, numpy.int32)}
    for name in ("sharp_face", "sharp_edge"):
        attr = mesh.attributes.get(name)
        arrays[name] = get(attr.data, "value", 1, bool) if attr is not None else None
    arrays["uv"] = [(layer.name, get(layer.data, "uv", 2, numpy.float32)) for layer in mesh.uv_layers]
    return arrays


def check_mesh_steps(paths, cancel_path):
    """build.objects.build_steps() makes a mesh above STEP_LOOPS face corners in phases (mesh_steps), looking its
    sharp edges up EDGE_CHUNK edges at a time: the same mesh as make_mesh() in one go, several yields per mesh with
    the count repeated; a run closed while a mesh is half made leaves nothing."""
    from maxdrop.build import objects as build_objects
    from maxdrop.convert import scene as convert_scene
    saved = build_objects.STEP_LOOPS, build_objects.EDGE_CHUNK, build_objects.mesh_steps
    try:
        for path in paths:
            empty_scene()
            name = os.path.basename(path)
            desc = convert_scene.read(path)
            whole = {}
            for key, md in desc.meshes.items():
                mesh, _dropped = build_objects.make_mesh(md)
                whole[key] = _mesh_arrays(mesh)
                bpy.data.meshes.remove(mesh)
            build_objects.STEP_LOOPS, build_objects.EDGE_CHUNK = 0, 7
            steps = build_objects.build_steps(desc, bpy.context.scene.collection)
            counts = []
            while True:
                try:
                    counts.append(next(steps))
                except StopIteration as end:
                    built = end.value
                    break
            build_objects.STEP_LOOPS, build_objects.EDGE_CHUNK = saved[:2]
            total = build_objects.steps_of(desc)
            dones = [d for d, _t in counts]
            sharp = sum(sum(a["sharp_edge"] or []) for a in whole.values())
            check("mesh steps: %s: 3 or more yields per mesh, the count repeated, never back, ending at the total" % name,
                  len(counts) >= total + 3 * len(desc.meshes) and dones == sorted(dones) and dones[-1] == total
                  and {t for _d, t in counts} == {total}, "%d yields, %d steps" % (len(counts), total))
            same = {key: _mesh_arrays(built.meshes[key]) == arrays for key, arrays in whole.items()}
            check("mesh steps: %s: every mesh built in phases equals make_mesh's (%d meshes, %d sharp edges, UVs)"
                  % (name, len(whole), sharp), whole and all(same.values()) and sharp > 0,
                  str([k for k, ok in same.items() if not ok]))
            import numpy
            key, md = max(desc.meshes.items(), key=lambda item: len(item[1].sharp_edges))
            pairs = numpy.asarray(md.sharp_edges)
            shuffled = numpy.concatenate((pairs[::-1], pairs[:3]))  # not sorted, repeated pairs
            flags = build_objects._sharp_edge_flags(built.meshes[key], shuffled)
            check("mesh steps: %s: sharp pairs out of order or repeated mark the same edges" % name,
                  flags.tolist() == whole[key]["sharp_edge"] and len(pairs) > 3, str(len(pairs)))
            flags = build_objects._sharp_edge_flags(built.meshes[key], pairs[:, ::-1])  # each pair (high, low)
            check("mesh steps: %s: sharp pairs given (high, low) mark the same edges" % name,
                  flags.tolist() == whole[key]["sharp_edge"] and len(pairs) > 3, str(len(pairs)))

        empty_scene()
        before = _state()
        inside = []

        def tracked(md, indices=None):
            inside.append(md)
            result = yield from saved[2](md, indices)
            inside.remove(md)
            return result

        build_objects.STEP_LOOPS, build_objects.EDGE_CHUNK, build_objects.mesh_steps = 0, 7, tracked
        meshes = len(bpy.data.meshes)
        run = _cancel_run([cancel_path])
        steps = run.steps()
        held = _advance(steps, lambda: bool(inside) and len(bpy.data.meshes) > meshes + 1)
        steps.close()
        check("mesh steps: closed while a mesh is half made: nothing left", held and _state() == before,
              "%s | %s" % (_state(), before))
    finally:
        build_objects.STEP_LOOPS, build_objects.EDGE_CHUNK, build_objects.mesh_steps = saved


def check_worker_errors():
    """ops._in_thread() hands the worker's outcome to the main thread: its value; an Exception unchanged; a SystemExit
    as a RuntimeError caused by it, so that the modal runner's except Exception still tears the run down."""
    from maxdrop import ops

    def outcome(fn):
        try:
            return ops._drain(ops._in_thread(fn))
        except BaseException as e:  # a SystemExit let through must fail this check, not end Blender
            return e

    def exits():
        raise SystemExit(3)

    def fails():
        raise ValueError("maxdrop test: read fails")

    got = outcome(lambda: 42)
    check("worker errors: a worker's value is returned", got == 42, repr(got))
    got = outcome(fails)
    check("worker errors: a worker's ValueError is raised unchanged",
          type(got) is ValueError and str(got) == "maxdrop test: read fails", repr(got))
    got = outcome(exits)
    check("worker errors: a worker's SystemExit is raised as a RuntimeError caused by it",
          type(got) is RuntimeError and type(got.__cause__) is SystemExit and got.__cause__.code == 3,
          "%r from %r" % (got, getattr(got, "__cause__", None)))


def check_pack_cancel(fixture):
    """The threaded unpack of a .zip pack as the run's first step: closed while it unpacks, no staging folder and no
    pack folder are left; closed during the build after it, the finished pack folder stays and nothing in Blender;
    run to its end, the unpack's summary is reported."""
    import time
    import zipfile
    from maxdrop import ops
    archive = ops._archive()
    empty_scene()
    before = _state()
    scratch = tempfile.mkdtemp(prefix="maxdrop-pack-cancel-")
    original = archive.unpack
    try:
        pack = os.path.join(scratch, "pack.zip")
        with zipfile.ZipFile(pack, "w") as z:
            z.write(fixture, "pack/" + os.path.basename(fixture))
        scene = "pack/" + os.path.basename(fixture)

        def slow(*args, watch=None, **kwargs):
            def slowed(n):
                time.sleep(0.3)  # the close below comes while the scene is being written
                watch(n)
            return original(*args, watch=slowed, **kwargs)

        archive.unpack = slow
        run = ops._Run(_cancel_run([pack]).opts, [pack], {pack: scene}, bpy.context)
        steps = run.steps(threaded=True)
        waited = next(steps) is ops._WAIT
        steps.close()
        archive.unpack = original
        check("pack cancel: closed while it unpacks: only the archive is left, nothing in Blender",
              waited and os.listdir(scratch) == ["pack.zip"] and _state() == before,
              "%s %s" % (os.listdir(scratch), run.text))

        run = ops._Run(_cancel_run([pack]).opts, [pack], {pack: scene}, bpy.context)
        steps = run.steps(threaded=True)
        held = _advance(steps, lambda: len(bpy.data.objects) > 0)
        steps.close()
        folder = os.path.join(scratch, "pack")
        check("pack cancel: closed during the build: the finished pack folder stays, nothing in Blender",
              held and os.path.isfile(os.path.join(folder, os.path.basename(fixture)))
              and os.path.isfile(os.path.join(folder, archive.MARKER)) and _state() == before,
              "%s %s" % (sorted(os.listdir(scratch)), held))

        run = ops._Run(_cancel_run([pack]).opts, [pack], {pack: scene}, bpy.context)
        ended = not _advance(run.steps(threaded=True), lambda: False)
        check("pack cancel: run to its end: the unpack's summary reported, the scene imported",
              ended and any(level == 'INFO' and line.startswith("pack.zip: ") for level, line in run.lines)
              and len(run._made) == 1, str(run.lines[:2]))
        run.undo()
    finally:
        archive.unpack = original
        shutil.rmtree(scratch, ignore_errors=True)


def check_found_textures():
    """vray_maps, texmap_rules, corona_maps, corona_light, vray_texmaps, texmap_wrappers and falloff_curve copied
    beside a PNG for
    each texture name:
    every Image Texture node gets its file, in the color space the IR asks for, one datablock per file and color
    space; the report lists no texture."""
    from maxdrop.convert import texmaps as tx
    fixtures = os.path.join(ROOT, "tests", "fixtures")
    scratch = tempfile.mkdtemp(prefix="maxdrop-textures-")
    linear = []  # the images the IR puts in Linear Rec.709, over every fixture
    try:
        for name in ("vray_maps", "texmap_rules", "corona_maps", "corona_light", "vray_texmaps", "texmap_wrappers",
                     "falloff_curve"):
            empty_scene()
            for ob in list(bpy.data.images):
                bpy.data.images.remove(ob)
            src = os.path.join(fixtures, name + ".max")
            dst = os.path.join(scratch, name + ".max")
            shutil.copy(src, dst)
            _desc, plan = _irs(src)
            irs = {ir.name: ir for s in plan.values() for irs in s.slots for ir in irs if ir is not None}
            wants = {}
            for ir in irs.values():
                for img in _images_of(ir):
                    wants.setdefault(img.name, set()).add(img.colorspace)
            linear += [file for file, spaces in wants.items() if tx.LINEAR in spaces]
            os.makedirs(os.path.join(scratch, "maps"), exist_ok=True)
            for file in wants:  # in the maps folder beside the scene: the lookup's second rule
                _write_png(os.path.join(scratch, "maps", file))
            result = bpy.ops.import_scene.maxdrop(filepath=dst)
            check("%s with its textures: imported" % name, result == {'FINISHED'})
            got = {}
            for m in bpy.data.materials:
                for n in m.node_tree.nodes:
                    if n.bl_idname == "ShaderNodeTexImage":
                        img = n.image
                        check("%s/%s/%s: image loaded" % (name, m.name, n.label), img is not None)
                        if img is not None:
                            check("%s/%s/%s: its file" % (name, m.name, n.label),
                                  os.path.normcase(bpy.path.abspath(img.filepath)) ==
                                  os.path.normcase(os.path.join(scratch, "maps", n.label)), img.filepath)
                            got.setdefault(n.label, set()).add((img.colorspace_settings.name, img.name))
            colorspaces = {k: {c for c, _n in v} for k, v in got.items()}
            check("%s with its textures: the color space of every image as the IR asks" % name,
                  colorspaces == wants, "%s vs %s" % (colorspaces, wants))
            images = sum(len(v) for v in wants.values())
            check("%s with its textures: one image datablock per file and color space" % name,
                  len(bpy.data.images) == images and all(len(v) == len(colorspaces[k]) for k, v in got.items()),
                  "%d images, %d wanted" % (len(bpy.data.images), images))
            text = bpy.data.texts.get("MaxDrop Report")
            body = text.as_string() if text is not None else ""
            check("%s with its textures: no texture reported missing, every file counted as found" % name,
                  text is not None and "Textures not found" not in body
                  and "\nTextures found: %d (" % len(wants) in body, body[-600:])
            for ir in irs.values():
                check_principled("%s with its textures/%s" % (name, ir.name), bpy.data.materials.get(ir.name), ir,
                                 present=True)
            if name == "vray_maps":
                check_vray_maps_nodes(textured=True)
                empty_scene()
                for img in list(bpy.data.images):
                    bpy.data.images.remove(img)
                check_failed_build_cleanup(dst)
                check_cancel(dst, os.path.join(fixtures, "cameras.max"))
                check_run_guards(dst)
                check_pack_cancel(os.path.join(fixtures, "cameras.max"))
            if name == "texmap_rules":
                m = bpy.data.materials["FixtureTexPlace"]
                cropped = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"
                               and n.label == "place_crop.png")
                uv = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeUVMap"]
                comb = _from(_from(cropped.inputs["Vector"]).inputs["Vector"])
                ops = [getattr(_from(comb.inputs[a]), "operation", None) for a in ("X", "Y")] if comb else []
                double = _from(_from(_from(comb.inputs["X"]).inputs[0]).inputs["Vector"]) if comb else None
                check("texmap_rules: place_crop.png on map channel 3, cropped, mirrored (U doubled) in U and clipped "
                      "in V (a mask under EXTEND)", cropped.extension == 'EXTEND' and _clip_axes_of(cropped) == ["Y"]
                      and any(n.uv_map == "UVChannel_3" for n in uv)
                      and ops == ['PINGPONG', 'MULTIPLY_ADD'] and getattr(double, "operation", None) == 'MULTIPLY'
                      and close(list(_input(double, "Vector_001").default_value), [2.0, 1.0, 1.0], 1e-6),
                      "%s %s %s" % (cropped.extension, [n.uv_map for n in uv], ops))
                check("texmap_rules: place_place.png on map channel 0 drawn on UV channel 1, reported",
                      not any(n.uv_map == "UVChannel_0" for mat in bpy.data.materials
                              for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeUVMap")
                      and "map channel 0 (vertex color) not imported: place_place.png on UV channel 1" in body,
                      body[-600:])
                keep = bpy.data.materials["FixtureTexKeep"]
                kinds = {n.bl_idname for n in keep.node_tree.nodes}
                check("texmap_rules: Mix with a mask, Multiply, Color Correction as nodes",
                      {"ShaderNodeMix", "ShaderNodeHueSaturation", "ShaderNodeGamma"} <= kinds, str(sorted(kinds)))
            if name == "texmap_wrappers":
                check_wrapper_nodes()
            if name == "vray_texmaps":
                check_reflection_falloff()
            if name == "falloff_curve":
                check_falloff_curve(textured=True)
        check("found textures: a linear color image (VRayBitmap transfer function None) imported in Linear Rec.709",
              "vtx_linear.png" in linear, str(linear))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder():
    """MaterialBuilder on hand-made IRs: one file in two color spaces is two images, the same twice is one; a file
    not found leaves its node without an image and a report line; Thin Wall on 5.x, skipped with a line on 4.x;
    two materials of one name both kept; BLENDED for a constant alpha, DITHERED for an alpha map; every node kind."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-builder-")
    try:
        png = os.path.join(scratch, "shared.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        srgb = tx.Image(1, "shared.png", "shared.png", "", found)
        data = tx.Image(1, "shared.png", "shared.png", "", found, colorspace=tx.NON_COLOR)
        lost = tx.Image(2, "nothere.png", "C:\\x\\nothere.png", "", None)
        placed = tx.Image(3, "shared.png", "shared.png", "", found,
                          mapping=tx.Mapping(channel=2, tiling=(2.0, 1.0), angle=(0.0, 0.0, 0.5),
                                             tile=(False, False), mirror=(True, True)),
                          crop=tx.Crop(0.1, 0.2, 0.5, 0.5, place=True),
                          output=tx.TexOutput(invert=True, amount=0.5, level=2.0, offset=0.1))
        gamma = tx.Image(4, "shared.png", "shared.png", "", found, colorspace=tx.LINEAR, gamma=1.8)

        def graph(root, kind):
            return tx.TextureGraphIR(root, kind)

        a = cm.MaterialIR(10, "Clash", "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)),
                          roughness=cm.Input(0.4, cm.MapRef(1)), specular=cm.Input(0.6, cm.MapRef(1)),
                          thin_walled=True, alpha=cm.Input(0.5))
        a.textures = {"base_color": graph(tx.Mix(tx.Constant((0.5, 0.5, 0.5)), srgb, 0.7, data), tx.COLOR),
                      "roughness": graph(tx.Invert(data), tx.DATA),
                      "specular": graph(tx.Multiply(srgb, tx.Constant((2.0, 2.0, 2.0))), tx.COLOR)}
        b = cm.MaterialIR(11, "Clash", "test", alpha=cm.Input(1.0, cm.MapRef(2)),
                          emission_color=cm.Input((1.0, 0.5, 0.0), cm.MapRef(3)), emission_strength=2.0)
        b.textures = {"alpha": graph(lost, tx.DATA),
                      "emission_color": graph(tx.ColorCorrect(tx.Composite((tx.CompositeLayer(placed, 1.0),
                                                                             tx.CompositeLayer(gamma, 0.5))),
                                                              hue=0.25, saturation=1.5, brightness=0.1,
                                                              contrast=0.2, gain=1.2, gamma=1.1), tx.COLOR),
                      "normal": graph(tx.NormalMap(data, 0.7, flip_red=True, flip_green=True, swap=True,
                                                   bump=tx.Bump(data, 2.0), channel=2), tx.NORMAL),
                      "metallic": graph(tx.Constant(0.3), tx.DATA)}
        builder = build_materials.MaterialBuilder()
        ma, mb = builder.make(a), builder.make(b)
        check("builder: two materials named Clash both kept", sorted([ma.name, mb.name]) == ["Clash", "Clash.001"],
              "%s %s" % (ma.name, mb.name))
        shared = sorted(i.colorspace_settings.name for i in bpy.data.images)
        check("builder: shared.png in sRGB, Non-Color (data) and Linear Rec.709 (a color input's gamma override) is "
              "three images, reused by every node",
              shared == ["Linear Rec.709", "Non-Color", "sRGB"] and len(builder.images) == 3, str(shared))
        lost_nodes = [n for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.label == "nothere.png"]
        issues = builder.issues()
        check("builder: a file not found keeps its node, without an image, and is no builder issue (the texture "
              "lookup reports it by name)", len(lost_nodes) == 1 and lost_nodes[0].image is None and issues == [],
              str(issues))
        check("builder: materials counted by class", dict(builder.classes) == {"test": 2}, str(builder.classes))
        thin = _principled(ma).inputs.get("Thin Wall")
        skipped = dict(builder.sockets_skipped)
        if bpy.app.version >= (5, 0, 0):
            check("builder: Thin Wall set on Blender 5", thin is not None and thin.default_value and not skipped)
        else:
            check("builder: Thin Wall skipped and counted once on Blender 4", thin is None
                  and skipped == {"Thin Wall": 1}, str(skipped))
        check("builder: BLENDED for a constant alpha below 1, DITHERED for an alpha map",
              ma.surface_render_method == 'BLENDED' and mb.surface_render_method == 'DITHERED')
        pb = _principled(mb)
        check("builder: emission, normal linked; metallic from a constant graph",
              pb.inputs["Emission Color"].is_linked and pb.inputs["Normal"].is_linked
              and not pb.inputs["Metallic"].is_linked and abs(pb.inputs["Metallic"].default_value - 0.3) < 1e-6
              and abs(pb.inputs["Emission Strength"].default_value - 2.0) < 1e-6)
        kinds = {n.bl_idname for n in mb.node_tree.nodes}
        need = {"ShaderNodeHueSaturation", "ShaderNodeBrightContrast", "ShaderNodeGamma", "ShaderNodeMix",
                "ShaderNodeNormalMap", "ShaderNodeBump", "ShaderNodeSeparateColor", "ShaderNodeCombineColor",
                "ShaderNodeUVMap", "ShaderNodeMapping", "ShaderNodeVectorMath", "ShaderNodeInvert"}
        check("builder: every node kind of the graphs", need <= kinds, str(sorted(need - kinds)))
        place = next(n for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.label == "shared.png"
                     and n.inputs["Vector"].is_linked)
        check("builder: a placed crop that mirrors clips by a mask on both axes under EXTEND",
              place.extension == 'EXTEND' and _clip_axes_of(place) == ["X", "Y"],
              "%s %s" % (place.extension, _clip_axes_of(place)))
        uv = [n.uv_map for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeUVMap"]
        nm = next(n for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeNormalMap")
        check("builder: map channel 2 is UVChannel_2, for the image and the normal map's tangents",
              uv == ["UVChannel_2"] and nm.uv_map == "UVChannel_2", "%s %s" % (uv, nm.uv_map))
        pa = _principled(ma)
        spec, mix = pa.inputs["Specular IOR Level"], _weight_mix(pa)
        dot = _from(mix.inputs[0]) if mix is not None else None
        check("builder: a color graph on the specular goes through the mean into the reflection weight, level 0.5",
              not spec.is_linked and spec.default_value == SPECULAR_LEVEL and dot is not None
              and dot.operation == 'DOT_PRODUCT' and close(list(dot.inputs[1].default_value), [1 / 3.0] * 3, 1e-6))
        check("builder: the viewport color is the base color", close(list(ma.diffuse_color)[:3], [0.5] * 3, 1e-6))
        check_builder_wiring(ma, mb, builder, cm, tx, srgb, data, lost, gamma)
        check_wrapper_wiring(builder, cm, tx, srgb, data)
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_blend():
    """Blend nodes (CoronaMix operations, bead maxdrop-em3.28): Gamma nodes of 1 / 2.2 on both sides and 2.2 after a
    Mix node of the operation, not clamped; subtract floored by a Vector Math MAXIMUM; two constants folded; a
    layered IR as a Principled BSDF per layer under Mix Shaders, the mask's graph times the amount on the factor."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    scratch = tempfile.mkdtemp(prefix="maxdrop-blend-")
    try:
        png = os.path.join(scratch, "blend.png")
        _write_png(png)
        img = tx.Image(1, "blend.png", "blend.png", "", ct.Found(png, ct.SCENE))
        c = tx.Constant((0.2, 0.4, 0.6))
        ir = cm.MaterialIR(20, "Blends", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)),
                           emission_color=cm.Input((0.0,) * 3, cm.MapRef(1)), emission_strength=1.0,
                           specular=cm.Input(0.5, cm.MapRef(1)))
        ir.textures = {"base_color": tx.TextureGraphIR(tx.Blend(tx.BLEND_ADD, c, img, 2.2), tx.COLOR),
                       "emission_color": tx.TextureGraphIR(tx.Blend(tx.BLEND_SUBTRACT, img, c), tx.COLOR),
                       "specular": tx.TextureGraphIR(tx.Blend(tx.BLEND_MAX, c, tx.Constant((0.5, 0.1, 0.9))),
                                                     tx.COLOR)}
        layer = cm.MaterialIR(21, "Top", "test", base_color=cm.Input((1.0, 0.0, 0.0)), sheen_weight=0.5)
        mask = tx.TextureGraphIR(tx.Mix(tx.Constant(1.0), img, 0.5), tx.DATA)
        ir.layers = [cm.Layer(layer, 0.4), cm.Layer(layer, 0.8, cm.MapRef(1, 0.5), mask)]
        builder = build_materials.MaterialBuilder()
        m = builder.make(ir)
        nodes = m.node_tree.nodes
        mixes = [n for n in nodes if n.bl_idname == "ShaderNodeMix" and n.blend_type in ('ADD', 'SUBTRACT')]
        add = next((n for n in mixes if n.blend_type == 'ADD'), None)
        gammas = sorted(round(n.inputs[1].default_value, 4) for n in nodes if n.bl_idname == "ShaderNodeGamma")
        check("blend: add between Gamma 1 / 2.2 and 2.2, unclamped",
              add is not None and not add.clamp_result and gammas == [round(1 / 2.2, 4)] * 2 + [2.2], str(gammas))
        floor = [n for n in nodes if n.bl_idname == "ShaderNodeVectorMath" and n.operation == 'MAXIMUM']
        check("blend: subtract floored at 0", len(floor) == 1)
        bsdfs, shaders = _bsdfs(m), _shaders(m)
        pb = bsdfs[0]
        spec, mix = pb.inputs["Specular IOR Level"], _weight_mix(pb)
        check("blend: two constants folded (max), the mean as the reflection weight", not spec.is_linked
              and spec.default_value == SPECULAR_LEVEL and mix is not None and not mix.inputs[0].is_linked
              and abs(mix.inputs[0].default_value - (0.5 + 0.4 + 0.9) / 3) < 1e-5,
              str(mix.inputs[0].default_value if mix else None))
        check("layers: a Principled BSDF and a Mix Shader per layer", len(bsdfs) == 3 and len(shaders) == 2)
        plain = [n for n in shaders if not n.inputs[0].is_linked]
        masked = [n for n in shaders if n.inputs[0].is_linked]
        check("layers: amount 0.4 as the factor, the masked one linked through a multiply by 0.8",
              len(plain) == 1 and abs(plain[0].inputs[0].default_value - 0.4) < 1e-6 and len(masked) == 1
              and masked[0].inputs[0].links[0].from_node.bl_idname == "ShaderNodeMath")
        out = next(n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial")
        check("layers: the top Mix Shader into the output", out.inputs["Surface"].links[0].from_node in masked)
        top = bsdfs[1]
        check("layers: the layer's sheen set", abs(top.inputs["Sheen Weight"].default_value - 0.5) < 1e-6)
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def _reaches_image(socket, depth=4):
    """Whether an Image Texture node feeds socket, through at most depth nodes."""
    if depth == 0 or not socket.is_linked:
        return False
    n = socket.links[0].from_node
    return n.bl_idname == "ShaderNodeTexImage" or any(_reaches_image(i, depth - 1) for i in n.inputs)


def check_builder_blend_modes():
    """The CoronaMix blend modes of bead maxdrop-em3.117 over an image: a Mix node of the mode (bottom in A, hard
    light's top in A), linear burn's add minus 1 floored at 0; in sRGB mode a Vector Math ABSOLUTE before the
    closing Gamma (Corona raises the magnitude) but for linear burn, in linear mode none."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    scratch = tempfile.mkdtemp(prefix="maxdrop-blend-modes-")
    try:
        png = os.path.join(scratch, "blend.png")
        _write_png(png)
        img = tx.Image(1, "blend.png", "blend.png", "", ct.Found(png, ct.SCENE))
        top = tx.Constant((0.6, 0.2, 0.75))
        types = {tx.BLEND_SCREEN: 'SCREEN', tx.BLEND_OVERLAY: 'OVERLAY', tx.BLEND_HARD_LIGHT: 'OVERLAY',
                 tx.BLEND_DODGE: 'DODGE', tx.BLEND_BURN: 'BURN', tx.BLEND_LINEAR_BURN: 'ADD',
                 tx.BLEND_LINEAR_LIGHT: 'LINEAR_LIGHT', tx.BLEND_EXCLUSION: 'EXCLUSION'}
        builder = build_materials.MaterialBuilder()
        for op, blend_type in types.items():
            for gamma in (2.2, 1.0):
                ir = cm.MaterialIR(30, "Mode", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)))
                ir.textures = {"base_color": tx.TextureGraphIR(tx.Blend(op, img, top, gamma), tx.COLOR)}
                m = builder.make(ir)
                nodes = m.node_tree.nodes
                what = "blend mode %s, gamma %s" % (op, gamma)
                mix = [n for n in nodes if n.bl_idname == "ShaderNodeMix" and n.blend_type == blend_type]
                ok = len(mix) == 1 and not mix[0].clamp_result
                if ok:
                    a, b = _input(mix[0], "A_Color"), _input(mix[0], "B_Color")
                    image, constant = (b, a) if op == tx.BLEND_HARD_LIGHT else (a, b)
                    ok = _reaches_image(image) and not _reaches_image(constant)
                check("%s: one unclamped Mix node, the bottom image in %s" % (what, "B" if op == tx.BLEND_HARD_LIGHT
                                                                              else "A"), ok)
                vm = {n.operation: n for n in nodes if n.bl_idname == "ShaderNodeVectorMath"}
                absolute = vm.get('ABSOLUTE')
                wants = gamma != 1.0 and op != tx.BLEND_LINEAR_BURN  # linear burn is floored at 0: none
                check("%s: %s" % (what, "ABSOLUTE into the closing Gamma" if wants else "no ABSOLUTE"),
                      (absolute is not None and absolute.outputs[0].links
                       and absolute.outputs[0].links[0].to_node.bl_idname == "ShaderNodeGamma") if wants
                      else absolute is None)
                if op == tx.BLEND_LINEAR_BURN:
                    add, floor = vm.get('ADD'), vm.get('MAXIMUM')
                    check("%s: minus 1, then floored at 0" % what,
                          add is not None and tuple(_input(add, "Vector_001").default_value) == (-1.0, -1.0, -1.0)
                          and floor is not None and floor.inputs[0].links[0].from_node == add)
                bpy.data.materials.remove(m)
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_weight():
    """A reflection weight (bead maxdrop-em3.119): between 0 and 1, or a map, a Mix Shader by the weight over a
    twin without reflection; 0, 1, a metal and full glass keep the lone Principled at 0.5 x the weight; a layer
    gets a twin of its own."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    empty_scene()
    builder = build_materials.MaterialBuilder()

    def make(name, **kw):
        return builder.make(cm.MaterialIR(70, name, "test", base_color=cm.Input((0.2, 0.3, 0.4)), **kw))

    for name, kw, mixed, level in (
            ("None", dict(specular=cm.Input(0.0)), False, 0.0),
            ("Grey", dict(specular=cm.Input(0.4), roughness=cm.Input(0.3), alpha=cm.Input(0.5)), True, 0.5),
            ("White", dict(specular=cm.Input(1.0)), False, 0.5),
            ("Above", dict(specular=cm.Input(1.6)), False, 0.5),
            ("Metal", dict(specular=cm.Input(0.4), metallic=cm.Input(1.0)), False, 0.2),
            ("Glass", dict(specular=cm.Input(0.4), transmission=cm.Input(1.0)), False, 0.2),
            ("HalfGlass", dict(specular=cm.Input(0.4), transmission=cm.Input(0.5)), True, 0.5)):
        m = make(name, **kw)
        p = _principled(m)
        mix = _weight_mix(p) if p is not None else None
        level_ok = p is not None and abs(p.inputs["Specular IOR Level"].default_value - level) < 1e-6
        check("weight: %s: %s, Specular IOR Level %.1f" % (name, "a reflection weight" if mixed else "a lone BSDF",
                                                           level), level_ok and (mix is not None) == mixed)
        out = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
        top = _from(out.inputs["Surface"])
        check("weight: %s: the surface is the %s" % (name, "Mix Shader" if mixed else "Principled BSDF"),
              top == (mix if mixed else p))
        if mixed:
            check("weight: %s: the factor is the weight" % name, abs(mix.inputs[0].default_value - 0.4) < 1e-6)
            check_twin("weight: " + name, p, mix)
            twin = _from(mix.inputs[1])
            check("weight: %s: the twin keeps the BSDF's alpha and transmission" % name,
                  abs(twin.inputs["Alpha"].default_value - p.inputs["Alpha"].default_value) < 1e-6
                  and abs(twin.inputs["Transmission Weight"].default_value
                          - p.inputs["Transmission Weight"].default_value) < 1e-6)
    m = make("BlendedGrey", specular=cm.Input(0.4), alpha=cm.Input(0.5))
    check("weight: a constant alpha below 1 still blends", m.surface_render_method == 'BLENDED',
          m.surface_render_method)
    top = cm.MaterialIR(71, "GreyTop", "test", specular=cm.Input(0.6))
    ir = cm.MaterialIR(72, "Layered", "test", specular=cm.Input(1.0))
    ir.layers = [cm.Layer(top, 0.5)]
    m = builder.make(ir)
    bsdfs, shaders = _bsdfs(m), _shaders(m)
    weights = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeMixShader" and n.label == WEIGHT_LABEL]
    layer_mix = shaders[0] if len(shaders) == 1 else None
    check("weight: a grey layer over a white base: one weight, on the layer, into the layer's Mix Shader",
          len(bsdfs) == 2 and len(weights) == 1 and _weight_mix(bsdfs[0]) is None and layer_mix is not None
          and _weight_mix(bsdfs[1]) == weights[0] and _from(layer_mix.inputs[2]) == weights[0]
          and _from(layer_mix.inputs[1]) == bsdfs[0], "%d BSDFs, %d weights" % (len(bsdfs), len(weights)))
    if len(bsdfs) == 2 and len(weights) == 1:
        check_twin("weight: the layer", bsdfs[1], weights[0])
    ir = cm.MaterialIR(73, "GreyUnder", "test", specular=cm.Input(0.3))
    ir.layers = [cm.Layer(top, 0.5)]
    m = builder.make(ir)
    bsdfs, shaders = _bsdfs(m), _shaders(m)
    under = _weight_mix(bsdfs[0]) if bsdfs else None
    layer_mix = shaders[0] if len(shaders) == 1 else None
    check("weight: a grey base under a grey layer: the base's weight below the layer's Mix Shader",
          len(bsdfs) == 2 and under is not None and layer_mix is not None and _from(layer_mix.inputs[1]) == under
          and _weight_mix(bsdfs[1]) is not None and _from(layer_mix.inputs[2]) == _weight_mix(bsdfs[1]))
    if under is not None:
        check_twin("weight: the base under a layer", bsdfs[0], under)
    empty_scene()


def check_builder_fresnel_off():
    """A weight without Fresnel (bead maxdrop-em3.120, VRayMtl Fresnel off): between 0 and 1, or a converted map, a
    Mix Shader by the weight from the BSDF at Specular IOR Level 0 to its copy as a white metal; 0, a metal and a
    reflection map that did not convert or whose image is not found (no node: its swatch) keep em3.119's drawing;
    Fresnel on keeps the twin."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    empty_scene()
    builder = build_materials.MaterialBuilder()
    facing = tx.TextureGraphIR(tx.Mix(tx.Constant((0.0,) * 3), tx.Constant((1.0,) * 3), 0.0,
                                      tx.Facing(tx.PERPENDICULAR)), tx.COLOR)
    for name, kw, textures, drawing, level in (
            ("Dim", dict(specular=cm.Input(0.2), roughness=cm.Input(0.3)), {}, "mirror", 0.0),
            ("DimRed", dict(specular=cm.Input(0.2), base_color=cm.Input((1.0, 0.0, 0.0), cm.MapRef(1)),
                            metallic=cm.Input(0.2, cm.MapRef(1))),
             {"base_color": facing, "metallic": tx.TextureGraphIR(tx.Mix(tx.Constant(0.0), tx.Constant(0.5), 0.0,
                                                                          tx.Facing(tx.PERPENDICULAR)), tx.DATA)},
             "mirror", 0.0),
            ("Falloff", dict(specular=cm.Input(0.0, cm.MapRef(1))), {"specular": facing}, "mirror", 0.0),
            ("None", dict(specular=cm.Input(0.0)), {}, "lone", 0.0),
            ("Metal", dict(specular=cm.Input(0.4), metallic=cm.Input(1.0)), {}, "lone", 0.2),
            ("Unconverted", dict(specular=cm.Input(0.6, cm.MapRef(1))), {}, "twin", 0.5),
            ("LostImage", dict(specular=cm.Input(0.8, cm.MapRef(2))),
             {"specular": tx.TextureGraphIR(tx.Image(2, "nothere.png", "C:\\x\\nothere.png", "", None), tx.COLOR)},
             "twin", 0.5),
            ("On", dict(specular=cm.Input(0.2), fresnel=True), {}, "twin", 0.5)):
        ir = cm.MaterialIR(80, name, "test", **{"fresnel": False, **kw})
        ir.textures = textures
        m = builder.make(ir)
        p = _principled(m) if m is not None else None
        mix = _weight_mix(p) if p is not None else None
        level_ok = p is not None and abs(p.inputs["Specular IOR Level"].default_value - level) < 1e-6
        second = _from(mix.inputs[2]) if mix is not None else None
        got = "lone" if mix is None else "mirror" if getattr(second, "label", "") == MIRROR_LABEL else "twin"
        check("fresnel off: %s: %s, Specular IOR Level %.1f" % (name, drawing, level), level_ok and got == drawing,
              "%s, level %r" % (got, None if p is None else p.inputs["Specular IOR Level"].default_value))
        if name == "DimRed" and got == "mirror":
            check("fresnel off: DimRed: the source's Base Color and Metallic are linked (the copy's are not)",
                  p.inputs["Base Color"].is_linked and p.inputs["Metallic"].is_linked)
        if p is not None and mix is not None:
            check_specular("fresnel off: " + name, p, ir, name != "LostImage")
            out = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
            check("fresnel off: %s: the surface is the Mix Shader" % name, _from(out.inputs["Surface"]) == mix)
    empty_scene()


def check_builder_mono():
    """Colored data maps on float inputs (bead maxdrop-em3.42): V-Ray 5.2 takes a data map as the mean of its
    channels (red 1 / 3, measured on a Mix mask, a reflection glossiness and an opacity map), Blender's link from a
    color output into a float input its luminance (red 0.2126). Every float input a map feeds (an image, a Color
    Correction over one, a Mix of images and its mask, a layer mask, a bump height) goes through one DOT_PRODUCT by
    (1/3, 1/3, 1/3); an image's alpha stays as it is."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-mono-")
    try:
        png = os.path.join(scratch, "mono.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        a = tx.Image(1, "mono.png", "mono.png", "", found, colorspace=tx.NON_COLOR)
        b = tx.Image(2, "mono.png", "mono.png", "", found, colorspace=tx.NON_COLOR,
                     mapping=tx.Mapping(tiling=(2.0, 2.0)))
        alpha = tx.Image(3, "mono.png", "mono.png", "", found, colorspace=tx.NON_COLOR, alpha=True)
        ir = cm.MaterialIR(50, "Mono", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)),
                           roughness=cm.Input(0.5, cm.MapRef(1)), metallic=cm.Input(0.0, cm.MapRef(1)),
                           alpha=cm.Input(1.0, cm.MapRef(1)), transmission=cm.Input(0.0, cm.MapRef(1)))
        ir.textures = {
            "base_color": tx.TextureGraphIR(tx.Mix(tx.Constant((0.0,) * 3), a, 0.0, b), tx.COLOR),
            "roughness": tx.TextureGraphIR(a, tx.DATA),
            "metallic": tx.TextureGraphIR(tx.ColorCorrect(a, hue=0.25), tx.DATA),
            "alpha": tx.TextureGraphIR(tx.Mix(a, b, 0.0, b), tx.DATA),
            "transmission": tx.TextureGraphIR(alpha, tx.DATA),
            "bump": tx.TextureGraphIR(tx.Bump(b, 1.0), tx.BUMP)}
        layer = cm.MaterialIR(51, "MonoTop", "test")
        ir.layers = [cm.Layer(layer, 1.0, cm.MapRef(1), tx.TextureGraphIR(a, tx.DATA))]
        m = build_materials.MaterialBuilder().make(ir)
        check("mono: material built", m is not None)
        if m is None:
            return
        mixed = _color_into_float(m)
        check("mono: no color output linked into a float input", mixed == [], str(mixed))
        p = next(n for n in _bsdfs(m) if n.inputs["Roughness"].is_linked)
        rough = _meaned(p.inputs["Roughness"])
        check("mono: a colored roughness image through the mean",
              getattr(rough, "bl_idname", None) == "ShaderNodeTexImage")
        hue = _meaned(p.inputs["Metallic"])
        check("mono: a Color Correction on the metallic, the mean after its hue",
              getattr(hue, "bl_idname", None) == "ShaderNodeHueSaturation")
        mix = _from(p.inputs["Alpha"])
        sides = [_meaned(_input(mix, k)) for k in ("A_Float", "B_Float", "Factor_Float")] \
            if mix is not None and mix.bl_idname == "ShaderNodeMix" else []
        check("mono: a float Mix of images by an image mask, each side and the mask through the mean",
              len(sides) == 3 and all(getattr(n, "bl_idname", None) == "ShaderNodeTexImage" for n in sides)
              and mix.data_type == 'FLOAT', str(sides))
        base = _from(p.inputs["Base Color"])
        check("mono: the mask of a color Mix through the mean, its sides in color",
              getattr(_meaned(_input(base, "Factor_Float")), "bl_idname", None) == "ShaderNodeTexImage"
              and _from(_input(base, "B_Color")).bl_idname == "ShaderNodeTexImage")
        trans = p.inputs["Transmission Weight"]
        check("mono: an image's alpha straight into the float input",
              trans.is_linked and trans.links[0].from_socket.identifier == "Alpha")
        bump = _from(p.inputs["Normal"])
        check("mono: a colored bump height through the mean",
              getattr(bump, "bl_idname", None) == "ShaderNodeBump"
              and getattr(_meaned(_input(bump, "Height")), "bl_idname", None) == "ShaderNodeTexImage")
        shader = next(iter(_shaders(m)), None)
        check("mono: a layer mask through the mean", shader is not None
              and getattr(_meaned(shader.inputs[0]), "bl_idname", None) == "ShaderNodeTexImage")
        dots = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeVectorMath" and n.operation == 'DOT_PRODUCT']
        check("mono: one mean per image in a float graph (two images, and the Color Correction)", len(dots) == 3,
              str(len(dots)))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_multiply():
    """A Multiply of two maps in a float graph (bead maxdrop-em3.124): V-Ray 5.2 takes the product of the two maps'
    means (red x green 1/9, measured on an RGB Multiply as a Mix mask and a glossiness map, a CoronaMix Multiply as
    a Mix mask), not the mean of their product (0). On roughness and on a color Mix's mask: a Math MULTIPLY of two
    DOT_PRODUCTs by (1/3, 1/3, 1/3), one from each image."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-multiply-")
    try:
        png = os.path.join(scratch, "mult.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        a = tx.Image(1, "mult.png", "mult.png", "", found, colorspace=tx.NON_COLOR)
        b = tx.Image(2, "mult.png", "mult.png", "", found, colorspace=tx.NON_COLOR,
                     mapping=tx.Mapping(tiling=(2.0, 2.0)))
        ir = cm.MaterialIR(52, "Multiply", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)),
                           roughness=cm.Input(0.5, cm.MapRef(1)))
        ir.textures = {
            "base_color": tx.TextureGraphIR(tx.Mix(tx.Constant((0.0,) * 3), tx.Constant((1.0,) * 3), 0.0,
                                                   tx.Multiply(a, b)), tx.COLOR),
            "roughness": tx.TextureGraphIR(tx.Multiply(a, b), tx.DATA)}
        m = build_materials.MaterialBuilder().make(ir)
        check("multiply: material built", m is not None)
        if m is None:
            return
        mixed = _color_into_float(m)
        check("multiply: no color output linked into a float input", mixed == [], str(mixed))
        p = _principled(m)

        def means_product(socket):
            mul = _from(socket)
            if mul is None or mul.bl_idname != "ShaderNodeMath" or mul.operation != 'MULTIPLY':
                return False
            sides = [_meaned(s) for s in mul.inputs[:2]]
            return all(getattr(n, "bl_idname", None) == "ShaderNodeTexImage" for n in sides) and sides[0] != sides[1]

        check("multiply: roughness is the product of the two images' means", means_product(p.inputs["Roughness"]))
        base = _from(p.inputs["Base Color"])
        check("multiply: a color Mix's mask is the product of the two images' means",
              base is not None and base.bl_idname == "ShaderNodeMix"
              and means_product(_input(base, "Factor_Float")))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_linear_fallback():
    """A color management config without Linear Rec.709 (a custom OCIO config; the stock one of every supported
    version has it): a linear color image falls back to Non-Color, shares the datablock of the same file as data,
    and keeps its gamma override's Gamma node (bead maxdrop-em3.62)."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-linear-")
    stock = build_materials._input_colorspaces
    try:
        check("linear fallback: the stock config has Linear Rec.709", tx.LINEAR in stock())
        png = os.path.join(scratch, "linear.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        build_materials._input_colorspaces = lambda: frozenset((tx.SRGB, tx.NON_COLOR))
        ir = cm.MaterialIR(40, "LinearFallback", "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)),
                           roughness=cm.Input(0.5, cm.MapRef(2)))
        ir.textures = {
            "base_color": tx.TextureGraphIR(tx.Image(1, "linear.png", "linear.png", "", found, colorspace=tx.LINEAR,
                                                     gamma=1.8), tx.COLOR),
            "roughness": tx.TextureGraphIR(tx.Image(2, "linear.png", "linear.png", "", found,
                                                    colorspace=tx.NON_COLOR), tx.DATA)}
        builder = build_materials.MaterialBuilder()
        m = builder.make(ir)
        p = _principled(m)
        gam = _from(p.inputs["Base Color"])
        rough = _meaned(p.inputs["Roughness"])
        tex = _from(gam.inputs["Color"]) if gam is not None and gam.bl_idname == "ShaderNodeGamma" else None
        check("linear fallback: Non-Color, one datablock with the data image, the Gamma node kept",
              tex is not None and abs(gam.inputs["Gamma"].default_value - 1.8) < 1e-6
              and tex.image is not None and tex.image.colorspace_settings.name == tx.NON_COLOR
              and rough is not None and rough.image is not None
              and tex.image.as_pointer() == rough.image.as_pointer()
              and len(bpy.data.images) == 1,
              "%s %s" % (getattr(gam, "bl_idname", None), [i.colorspace_settings.name for i in bpy.data.images]))
    finally:
        build_materials._input_colorspaces = stock
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_image_reuse():
    """MaterialBuilder reuses an image already in the file (an earlier import's) of the same file and color space,
    untouched (bead maxdrop-em3.43): a second builder adds no image; the same file in another color space is a new
    image and the first keeps its color space; a modified, a packed, a generated, a library image or one whose alpha
    mode was changed is not reused."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-reuse-")
    try:
        png = os.path.join(scratch, "reuse.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        spaces = [i.identifier for i in bpy.types.ColorManagedInputColorspaceSettings.bl_rna.properties["name"]
                  .enum_items if i.identifier not in (tx.SRGB, tx.NON_COLOR)]
        other = next((c for c in spaces if c.startswith("Linear")), spaces[0])

        def build(name, *colorspaces):
            """The images of a material whose base color and roughness are reuse.png in these color spaces, made by
            a builder of its own (another import)."""
            ir = cm.MaterialIR(30, name, "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)),
                               roughness=cm.Input(0.5, cm.MapRef(2)))
            a, b = (tx.Image(k + 1, "reuse.png", "reuse.png", "", found, colorspace=c)
                    for k, c in enumerate(colorspaces))
            ir.textures = {"base_color": tx.TextureGraphIR(a, tx.COLOR), "roughness": tx.TextureGraphIR(b, tx.DATA)}
            m = build_materials.MaterialBuilder().make(ir)
            return _from(_principled(m).inputs["Base Color"]).image, _meaned(_principled(m).inputs["Roughness"]).image

        def names():
            return [(i.name, i.colorspace_settings.name, i.is_dirty, i.source, bool(i.packed_file), bool(i.library))
                    for i in bpy.data.images]

        base, rough = build("ReuseA", tx.SRGB, tx.NON_COLOR)
        check("reuse: the first builder loads the file in sRGB and Non-Color", len(bpy.data.images) == 2
              and base.colorspace_settings.name == tx.SRGB and rough.colorspace_settings.name == tx.NON_COLOR,
              str(names()))
        base2, rough2 = build("ReuseB", tx.SRGB, tx.NON_COLOR)
        check("reuse: a second builder reuses both images, adds none", len(bpy.data.images) == 2
              and base2.as_pointer() == base.as_pointer() and rough2.as_pointer() == rough.as_pointer(),
              str(names()))
        base3, rough3 = build("ReuseC", other, tx.SRGB)
        check("reuse: the same file in %s is a new image, the sRGB one reused and still sRGB" % other,
              len(bpy.data.images) == 3 and rough3.as_pointer() == base.as_pointer()
              and base3.colorspace_settings.name == other and base.colorspace_settings.name == tx.SRGB,
              str(names()))
        base.pixels[0] = 0.25  # painted on: it no longer is the file
        check("reuse: writing a pixel makes the image dirty", base.is_dirty)
        base4, rough4 = build("ReuseD", tx.SRGB, tx.NON_COLOR)
        check("reuse: a modified image is not reused, a new one loaded", len(bpy.data.images) == 4
              and base4.as_pointer() != base.as_pointer() and base4.colorspace_settings.name == tx.SRGB
              and not base4.is_dirty and rough4.as_pointer() == rough.as_pointer(), str(names()))
        for img in (base, base4):
            bpy.data.images.remove(img)
        base5 = build("ReuseE", tx.SRGB, tx.NON_COLOR)[0]
        base5.pack()
        base6 = build("ReuseF", tx.SRGB, tx.NON_COLOR)[0]
        check("reuse: a packed image is not reused", base6.as_pointer() != base5.as_pointer()
              and base5.packed_file is not None and base6.packed_file is None, str(names()))
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        straight = build("ReuseAlpha", tx.SRGB, tx.NON_COLOR)[0]
        straight.alpha_mode = 'CHANNEL_PACKED'
        packed_alpha = build("ReuseAlpha2", tx.SRGB, tx.NON_COLOR)[0]
        check("reuse: an image whose alpha mode was changed is not reused",
              packed_alpha.as_pointer() != straight.as_pointer() and packed_alpha.alpha_mode == 'STRAIGHT',
              str(names()))
        exr = os.path.join(scratch, "reuse.exr")
        probe = bpy.data.images.new("maxdrop-probe", 4, 4, float_buffer=True)
        probe.filepath_raw = exr
        probe.file_format = 'OPEN_EXR'
        probe.save()
        bpy.data.images.remove(probe)

        def build_exr(name):
            ir = cm.MaterialIR(32, name, "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
            ir.textures = {"base_color": tx.TextureGraphIR(
                tx.Image(1, "reuse.exr", "reuse.exr", "", ct.Found(exr, ct.SCENE), colorspace=other), tx.COLOR)}
            m = build_materials.MaterialBuilder().make(ir)
            return _from(_principled(m).inputs["Base Color"]).image

        first_exr = build_exr("ReuseExr")
        count = len(bpy.data.images)
        again_exr = build_exr("ReuseExr2")
        check("reuse: an EXR (premultiplied on load) is reused too", first_exr.alpha_mode == 'PREMUL'
              and again_exr.as_pointer() == first_exr.as_pointer() and len(bpy.data.images) == count, str(names()))
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        generated = bpy.data.images.new("Generated", 4, 4)
        generated.filepath_raw = png  # a generated image with a file name, never loaded from it
        base7 = build("ReuseG", tx.SRGB, tx.NON_COLOR)[0]
        check("reuse: a generated image is not reused", generated.source == 'GENERATED'
              and base7.as_pointer() != generated.as_pointer() and base7.source == 'FILE', str(names()))
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        blend = os.path.join(scratch, "library.blend")
        own = bpy.data.images.load(png, check_existing=False)
        own.colorspace_settings.name = tx.SRGB
        bpy.data.libraries.write(blend, {own}, path_remap='ABSOLUTE')
        library_name = own.name
        bpy.data.images.remove(own)
        with bpy.data.libraries.load(blend, link=True) as (_src, dst):
            dst.images = [library_name]
        linked = [i for i in bpy.data.images if i.library is not None]
        base8 = build("ReuseH", tx.SRGB, tx.NON_COLOR)[0]
        check("reuse: an image linked from a library is not reused", len(linked) == 1
              and os.path.normcase(bpy.path.abspath(linked[0].filepath, library=linked[0].library)) ==
              os.path.normcase(png) and linked[0].colorspace_settings.name == tx.SRGB
              and base8.as_pointer() != linked[0].as_pointer() and base8.library is None, str(names()))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        for lib in list(bpy.data.libraries):
            bpy.data.libraries.remove(lib)
        shutil.rmtree(scratch, ignore_errors=True)


def check_double_import():
    """vray_maps copied beside a PNG for each texture, imported twice into an emptied scene whose images stay: the
    second import adds no image datablock and its nodes take the first import's images."""
    fixtures = os.path.join(ROOT, "tests", "fixtures")
    scratch = tempfile.mkdtemp(prefix="maxdrop-twice-")
    try:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        src = os.path.join(fixtures, "vray_maps.max")
        dst = os.path.join(scratch, "vray_maps.max")
        shutil.copy(src, dst)
        _desc, plan = _irs(src)
        files = {img.name for s in plan.values() for irs in s.slots for ir in irs if ir is not None
                 for img in _images_of(ir)}
        os.makedirs(os.path.join(scratch, "maps"), exist_ok=True)
        for file in files:
            _write_png(os.path.join(scratch, "maps", file))

        def used():
            return {n.image.as_pointer() for m in bpy.data.materials for n in m.node_tree.nodes
                    if n.bl_idname == "ShaderNodeTexImage" and n.image is not None}

        check("twice: first import", bpy.ops.import_scene.maxdrop(filepath=dst) == {'FINISHED'})
        before = {i.as_pointer() for i in bpy.data.images}
        first = used()
        empty_scene()
        check("twice: second import", bpy.ops.import_scene.maxdrop(filepath=dst) == {'FINISHED'})
        after = {i.as_pointer() for i in bpy.data.images}
        check("twice: the second import adds no image datablock, its nodes use the first import's images",
              bool(first) and after == before and used() == first,
              "%d images before, %d after, %d used" % (len(before), len(after), len(first)))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def _crop_case(builder, cm, tx, found, name, mapping, crop):
    """A material whose base color is one cropped image: (its Image Texture node, the node feeding the crop
    Mapping)."""
    ir = cm.MaterialIR(20, name, "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
    img = tx.Image(1, "shared.png", "shared.png", "", found, mapping=mapping, crop=crop)
    ir.textures = {"base_color": tx.TextureGraphIR(img, tx.COLOR)}
    m = builder.make(ir)
    tex = _image_of(_principled(m).inputs["Base Color"])[0]
    return tex, _from(_from(tex.inputs["Vector"]).inputs["Vector"])


def check_builder_debt():
    """MaterialBuilder on hand-made IRs (bead maxdrop-em3.26): a crop repeats per axis as its tile and mirror say
    (wrap, ping-pong, clip); map channel 0 drawn on channel 1 and reported; a texture file without image data
    reported and left out; a material whose build raises is removed, its slot empty, the failure reported."""
    import dataclasses
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-builder-debt-")
    try:
        png = os.path.join(scratch, "shared.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        builder = build_materials.MaterialBuilder()
        crop = tx.Crop(0.25, 0.0, 0.5, 0.25)

        tex, comb = _crop_case(builder, cm, tx, found, "CropClip", tx.Mapping(tile=(False, False)), crop)
        chain = [_from(comb.inputs[a]) for a in ("X", "Y")]
        floors = [_from(n.inputs[0]) for n in chain]
        ks = [n.inputs[1].default_value for n in chain]
        check("builder debt: a crop with tile off: c + K floor(c) per axis, K = 1/w + 1 and 1/h + 1, image CLIP, "
              "no mask",
              tex.extension == 'CLIP' and all(n.operation == 'MULTIPLY_ADD' for n in chain) and not _clip_axes_of(tex)
              and all(f.operation == 'FLOOR' for f in floors) and close(ks, [3.0, 5.0], 1e-6)
              and all(_from(n.inputs[2]) == _from(f.inputs[0]) for n, f in zip(chain, floors))
              and _from(chain[0].inputs[2]).bl_idname == "ShaderNodeSeparateXYZ",
              "%s %s %s" % (tex.extension, [n.operation for n in chain], ks))
        # the formula itself (the nodes and K are checked above): the image coordinate the crop Mapping (POINT:
        # c * size + location) gives each cell coordinate c
        inside = []
        for size, loc, k in ((0.5, 0.25, ks[0]), (0.25, 0.75, ks[1])):
            for c in (-2.5, -0.01, 0.0, 0.3, 0.99, 1.0, 1.4, 7.0):
                x = (c + k * math.floor(c)) * size + loc
                inside.append((0.0 <= x <= 1.0) == (0.0 <= c < 1.0))
        check("builder debt: a clipped crop axis keeps the 0..1 cell in the image and sends every other c out",
              all(inside), str(inside))

        tex, comb = _crop_case(builder, cm, tx, found, "CropMirrorU",
                               tx.Mapping(tile=(True, True), mirror=(True, False)), crop)
        chain = [_from(comb.inputs[a]) for a in ("X", "Y")]
        double = _from(_from(chain[0].inputs[0]).inputs["Vector"])
        check("builder debt: a crop mirrored in U, tiled in V: U doubled, ping-pong on X, wrap 0..1 on Y, image "
              "EXTEND",
              tex.extension == 'EXTEND' and chain[0].operation == 'PINGPONG'
              and chain[0].inputs[1].default_value == 1.0 and chain[1].operation == 'WRAP'
              and chain[1].inputs[1].default_value == 1.0 and chain[1].inputs[2].default_value == 0.0
              and double.bl_idname == "ShaderNodeVectorMath" and double.operation == 'MULTIPLY'
              and close(list(_input(double, "Vector_001").default_value), [2.0, 1.0, 1.0], 1e-6),
              "%s %s %s" % (tex.extension, [n.operation for n in chain], double.bl_idname))

        tex, comb = _crop_case(builder, cm, tx, found, "CropMirrorNoTile",
                               tx.Mapping(tile=(False, False), mirror=(True, True)), crop)
        pings = [_from(comb.inputs[a]) for a in ("X", "Y")]
        chain = [n.operation for n in pings]
        double = _from(_from(pings[0].inputs[0]).inputs["Vector"])
        check("builder debt: mirror on with tile off still mirrors (mirror tiles), both axes doubled, image EXTEND",
              tex.extension == 'EXTEND' and chain == ['PINGPONG', 'PINGPONG']
              and double.bl_idname == "ShaderNodeVectorMath" and double.operation == 'MULTIPLY'
              and close(list(_input(double, "Vector_001").default_value), [2.0, 2.0, 1.0], 1e-6),
              "%s %s %s" % (tex.extension, chain, double.bl_idname))

        tex, comb = _crop_case(builder, cm, tx, found, "PlaceMixed", tx.Mapping(tile=(True, False)),
                               tx.Crop(0.25, 0.0, 0.5, 0.25, place=True))
        x, y = _from(comb.inputs["X"]), _from(comb.inputs["Y"])
        check("builder debt: a placed image tiled in U, clipped in V: wrap on X, V straight through, image EXTEND, "
              "the placed rectangle masked on both axes",
              tex.extension == 'EXTEND' and x.operation == 'WRAP' and y.bl_idname == "ShaderNodeSeparateXYZ"
              and comb.outputs["Vector"].links[0].to_node.vector_type == 'TEXTURE'
              and _clip_axes_of(tex) == ["X", "Y"], "%s %s %s %s" % (tex.extension, x.operation, y.bl_idname,
                                                                      _clip_axes_of(tex)))

        tex, frac = _crop_case(builder, cm, tx, found, "CropTile", tx.Mapping(), crop)
        check("builder debt: a crop tiled both ways: one Fraction, image EXTEND",
              tex.extension == 'EXTEND' and frac.bl_idname == "ShaderNodeVectorMath" and frac.operation == 'FRACTION',
              "%s %s" % (tex.extension, frac.bl_idname))

        tex, uv = _crop_case(builder, cm, tx, found, "PlaceClip", tx.Mapping(tile=(False, False)),
                             tx.Crop(0.25, 0.0, 0.5, 0.25, place=True))
        check("builder debt: a placed image with tile off: the UV straight into the TEXTURE Mapping, image CLIP",
              tex.extension == 'CLIP' and uv.bl_idname == "ShaderNodeTexCoord",
              "%s %s" % (tex.extension, uv.bl_idname))

        zero = tx.Image(5, "channel0.png", "channel0.png", "", found, mapping=tx.Mapping(channel=0))
        ir = cm.MaterialIR(21, "ChannelZero", "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
        ir.textures = {"base_color": tx.TextureGraphIR(zero, tx.COLOR),
                       "normal": tx.TextureGraphIR(tx.NormalMap(dataclasses.replace(zero, colorspace=tx.NON_COLOR),
                                                                1.0, channel=0), tx.NORMAL)}
        before = len(builder.issues())
        m = builder.make(ir)
        nodes = m.node_tree.nodes
        nm = next(n for n in nodes if n.bl_idname == "ShaderNodeNormalMap")
        new = builder.issues()[before:]
        check("builder debt: map channel 0 drawn on UV channel 1: no UV Map node, the normal map's default "
              "tangents, one report line", not any(n.bl_idname == "ShaderNodeUVMap" for n in nodes)
              and nm.uv_map == "" and new == [("material ChannelZero", "map channel 0 (vertex color) not imported: "
                                                                       "channel0.png on UV channel 1")], str(new))

        junk = os.path.join(scratch, "junk.png")
        with open(junk, "wb") as f:
            f.write(b"this is not an image at all")
        empty = os.path.join(scratch, "empty.jpg")
        open(empty, "wb").close()
        tga = os.path.join(scratch, "any.tga")
        with open(tga, "wb") as f:
            f.write(b"junk without a header")
        targa = os.path.join(scratch, "really_tga.png")  # an uncompressed 24-bit Targa header, 1 x 1
        with open(targa, "wb") as f:
            f.write(b"\x00\x00\x02" + bytes(9) + b"\x01\x00\x01\x00\x18\x00" + b"\x10\x20\x30")
        renamed = os.path.join(scratch, "really_png.jpg")
        shutil.copy(png, renamed)
        has = [build_materials.image_has_data(p) for p in (png, renamed, tga, targa, junk, empty)]
        check("builder debt: image_has_data: a PNG yes, a PNG named .jpg yes, any .tga (no signature) yes, a Targa "
              "named .png yes, text named .png no, an empty file no", has == [True, True, True, True, False, False],
              str(has))
        images = len(bpy.data.images)
        ir = cm.MaterialIR(22, "Undecodable", "test", base_color=cm.Input((0.2, 0.3, 0.4), cm.MapRef(1)))
        lost = tx.Image(6, "junk.png", "junk.png", "", ct.Found(junk, ct.SCENE))
        ir.textures = {"base_color": tx.TextureGraphIR(lost, tx.COLOR)}
        before = len(builder.issues())
        m = builder.make(ir)
        node = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage")
        base = _principled(m).inputs["Base Color"]
        new = builder.issues()[before:]
        check("builder debt: a texture file without image data: node without image, no datablock, the swatch, one "
              "report line", node.image is None and len(bpy.data.images) == images and not base.is_linked
              and close(list(base.default_value)[:3], [0.2, 0.3, 0.4], 1e-6)
              and new == [("material Undecodable", "texture not loaded: junk.png (no image data)")], str(new))

        original = build_materials._Tree.build

        def failing(self):
            raise RuntimeError("maxdrop test: tree fails")

        build_materials._Tree.build = failing
        try:
            materials = len(bpy.data.materials)
            got = builder.make(cm.MaterialIR(23, "Broken", "test"))
        finally:
            build_materials._Tree.build = original
        new = builder.issues()[-1]
        check("builder debt: a material whose build raises: None, removed again, reported, not counted",
              got is None and len(bpy.data.materials) == materials and "Broken" not in bpy.data.materials
              and new == ("material Broken", "material not built (RuntimeError: maxdrop test: tree fails)")
              and builder.classes["test"] == 8, "%s %s %s" % (got, new, dict(builder.classes)))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


_ONE_MIRROR = ("8 24 40 55 72 88 104 119 136 152 168 184 200 216 231 248 248 231 216 200 184 168 152 136 119 104 88 72 "
               "55 40 24 8")
# 3ds Max 2020 renderMap (scanline, filter off, Bitmap filtering none) of a 64 x 64 ramp, red 4 x its column, green
# 4 x its row from the top (bead maxdrop-em3.60): (label, Mapping keywords, crop (u, v, w, h, place) or None, render
# size, 'row' at y or 'col' at x, that index, the channel, its values; '-' black: outside the image)
_MIRROR_ROWS = (
    ("mirror U, tiling 1", dict(mirror=(True, False)), None, (32, 8), "row", 4, "R",
     _ONE_MIRROR),
    ("mirror U, tile off", dict(tile=(False, True), mirror=(True, False)), None, (32, 8), "row", 4, "R",
     _ONE_MIRROR),
    ("mirror U, tiling 0.5", dict(tiling=(0.5, 1.0), mirror=(True, False)), None, (32, 8), "row", 4, "R",
     "131 139 147 156 164 171 180 187 195 204 212 220 228 235 244 252 252 244 235 228 220 212 204 195 187 180 171 164 "
     "156 147 139 131"),
    ("mirror U, tiling 2", dict(tiling=(2.0, 1.0), mirror=(True, False)), None, (32, 8), "row", 4, "R",
     "239 208 176 144 112 80 48 16 16 48 80 112 144 176 208 239 239 208 176 144 112 80 48 16 16 48 80 112 144 176 208 "
     "239"),
    ("mirror U, offset 0.1", dict(offset=(0.1, 0.0), mirror=(True, False)), None, (32, 32), "row", 16, "R",
     "40 24 8 4 19 36 52 68 84 100 116 131 147 164 180 195 212 228 244 248 231 216 200 184 168 152 136 119 104 88 72 "
     "55"),
    ("mirror U, crop", dict(mirror=(True, False)), (0.25, 0.0, 0.5, 1.0, False), (32, 32), "row", 16, "R",
     "68 75 84 91 100 108 116 124 131 139 147 156 164 171 180 187 187 180 171 164 156 147 139 131 124 116 108 100 91 "
     "84 75 68"),
    ("mirror U, placed", dict(mirror=(True, False)), (0.25, 0.0, 0.5, 1.0, True), (32, 8), "row", 4, "R",
     "- - - - 16 48 80 112 144 176 208 239 - - - - - - - - 239 208 176 144 112 80 48 16 - - - -"),
    ("mirror both, along U", dict(mirror=(True, True)), None, (32, 32), "row", 16, "R",
     _ONE_MIRROR),
    ("mirror both, along V", dict(mirror=(True, True)), None, (32, 32), "col", 3, "G",
     "248 231 216 200 184 168 152 136 119 104 88 72 55 40 24 8 8 24 40 55 72 88 104 119 136 152 168 184 200 216 231 "
     "248"),
    ("mirror V", dict(mirror=(False, True)), None, (32, 32), "col", 3, "G",
     "248 231 216 200 184 168 152 136 119 104 88 72 55 40 24 8 8 24 40 55 72 88 104 119 136 152 168 184 200 216 231 "
     "248"),
    ("mirror V, along U", dict(mirror=(False, True)), None, (32, 32), "row", 16, "R",
     "4 12 19 28 36 44 52 60 68 75 84 91 100 108 116 124 131 139 147 156 164 171 180 187 195 204 212 220 228 235 244 "
     "252"),
    ("mirror U, V clipped at tiling 2, along U", dict(tiling=(1.0, 2.0), tile=(True, False), mirror=(True, False)),
     None, (32, 32), "row", 16, "R", _ONE_MIRROR),
    ("mirror U, V clipped at tiling 2, along V", dict(tiling=(1.0, 2.0), tile=(True, False), mirror=(True, False)),
     None, (32, 32), "col", 3, "G",
     "- - - - - - - - 8 24 40 55 72 88 104 119 136 152 168 184 200 216 231 248 - - - - - - - -"),
    ("crop, mirror U, V clipped at tiling 2, along U",
     dict(tiling=(1.0, 2.0), tile=(True, False), mirror=(True, False)), (0.25, 0.25, 0.5, 0.5, False), (32, 32),
     "row", 16, "R",
     "68 75 84 91 100 108 116 124 131 139 147 156 164 171 180 187 187 180 171 164 156 147 139 131 124 116 108 100 91 "
     "84 75 68"),
    ("crop, mirror U, V clipped at tiling 2, along V",
     dict(tiling=(1.0, 2.0), tile=(True, False), mirror=(True, False)), (0.25, 0.25, 0.5, 0.5, False), (32, 32),
     "col", 3, "G",
     "- - - - - - - - 68 75 84 91 100 108 116 124 131 139 147 156 164 171 180 187 - - - - - - - -"),
    ("mirror U, W 90, along V", dict(angle=(0.0, 0.0, math.pi / 2), mirror=(True, False)), None, (16, 16), "col", 8,
     "R", "16 48 80 112 144 176 208 239 239 208 176 144 112 80 48 16"),
    ("mirror U, W 90, along U", dict(angle=(0.0, 0.0, math.pi / 2), mirror=(True, False)), None, (16, 16), "row", 8,
     "G", "248 231 216 200 184 168 152 136 119 104 88 72 55 40 24 8"),
)


def _pingpong(a, b):
    """Blender's Math PINGPONG (pingpongf)."""
    if not b:
        return 0.0
    t = (a - b) / (b * 2)
    return abs((t - math.floor(t)) * b * 2 - b)


def _sample_vector(socket, uv):
    """The vector a node tree gives an input at the UV uv, as Blender evaluates the node kinds the texture placement
    uses (Texture Coordinate / UV Map, Mapping, Vector Math, Separate / Combine XYZ, Math)."""
    from mathutils import Euler
    if not socket.is_linked:
        return None
    link = socket.links[0]
    n, out = link.from_node, link.from_socket.identifier
    if n.bl_idname in ("ShaderNodeTexCoord", "ShaderNodeUVMap"):
        return Vector((uv[0], uv[1], 0.0))
    if n.bl_idname == "ShaderNodeSeparateXYZ":
        return _sample_vector(n.inputs["Vector"], uv)["XYZ".index(out)]
    if n.bl_idname == "ShaderNodeCombineXYZ":
        return Vector([_sample_value(n.inputs[a], uv) for a in "XYZ"])
    if n.bl_idname == "ShaderNodeMath":
        a, b, c = (_sample_value(n.inputs[i], uv) for i in range(3))
        return {'PINGPONG': lambda: _pingpong(a, b), 'FLOOR': lambda: math.floor(a),
                'WRAP': lambda: a - (b - c) * math.floor((a - c) / (b - c)), 'MULTIPLY_ADD': lambda: a * b + c,
                'COMPARE': lambda: float(abs(a - b) <= max(c, 1e-5)), 'MULTIPLY': lambda: a * b,
                }[n.operation]()
    v = _sample_vector(n.inputs["Vector"], uv)
    if n.bl_idname == "ShaderNodeVectorMath":
        if n.operation == 'MULTIPLY':
            return Vector([x * f for x, f in zip(v, _input(n, "Vector_001").default_value)])
        if n.operation == 'FRACTION':
            return Vector([x - math.floor(x) for x in v])
    if n.bl_idname == "ShaderNodeMapping":
        loc, scale = Vector(n.inputs["Location"].default_value), Vector(n.inputs["Scale"].default_value)
        rot = Euler(n.inputs["Rotation"].default_value, 'XYZ').to_matrix()
        if n.vector_type == 'POINT':
            return loc + rot @ Vector([x * s for x, s in zip(v, scale)])
        if n.vector_type == 'TEXTURE':
            return Vector([x / s for x, s in zip(rot.transposed() @ (v - loc), scale)])
    raise AssertionError("not evaluated: %s %s" % (n.bl_idname, getattr(n, "operation", "")))


def _sample_value(socket, uv):
    return _sample_vector(socket, uv) if socket.is_linked else socket.default_value


def _sample_image(tex, uv, mask=None):
    """The image coordinate (x, y) an Image Texture node reads at uv, its extension applied; None outside a CLIP
    image or where its clip mask (the socket mask, _image_of) is 0."""
    if mask is not None and _sample_value(mask, uv) < 0.5:
        return None
    v = _sample_vector(tex.inputs["Vector"], uv)
    v = Vector((uv[0], uv[1], 0.0)) if v is None else v
    xy = []
    for x in v[:2]:
        if tex.extension == 'REPEAT':
            x -= math.floor(x)
        elif tex.extension == 'MIRROR':
            x = _pingpong(x, 1.0)
        elif tex.extension == 'EXTEND':
            x = min(max(x, 0.0), 1.0)
        elif not 0.0 <= x <= 1.0:
            return None
        xy.append(x)
    return xy


CLIP_LABEL = "Clip"  # build/materials.py's CLIP_LABEL (the package is imported inside the checks)


def _clip_mask_input(node):
    """The input of a Clip node that carries the clip mask (Math MULTIPLY for Alpha, Vector Math SCALE for Color)."""
    return node.inputs[1] if node.bl_idname == "ShaderNodeMath" else _input(node, "Scale")


def _image_of(socket):
    """(the Image Texture feeding an input, the input of its Clip node that carries the clip mask, or None without
    one)."""
    n = _from(socket)
    if n is not None and n.label == CLIP_LABEL:
        return _from(n.inputs[0]), _clip_mask_input(n)
    return n, None


def _clip_axes_of(tex):
    """The axes ("X", "Y") an Image Texture's clip mask tests (Math COMPARE, |x - 0.5| <= 0.5, of the vector the
    node reads), [] without a mask; None for a mask of another form or Clip nodes that disagree."""
    clips = [n for n in tex.id_data.nodes if n.label == CLIP_LABEL and _from(n.inputs[0]) == tex]
    if not clips:
        return []
    found = set()
    for clip in clips:
        todo, axes = [_from(_clip_mask_input(clip))], []
        while todo:
            n = todo.pop()
            if n is None or n.bl_idname != "ShaderNodeMath":
                return None
            if n.operation == 'MULTIPLY':
                todo += [_from(i) for i in n.inputs[:2]]
                continue
            sep = _from(n.inputs[0])
            if n.operation != 'COMPARE' or n.inputs[1].default_value != 0.5 or n.inputs[2].default_value != 0.5 \
                    or sep is None or sep.bl_idname != "ShaderNodeSeparateXYZ" or not tex.inputs["Vector"].is_linked \
                    or sep.inputs["Vector"].links[0].from_socket != tex.inputs["Vector"].links[0].from_socket:
                return None
            axes.append(n.inputs[0].links[0].from_socket.identifier)
        found.add(tuple(sorted(axes)))
    return list(found.pop()) if len(found) == 1 else None


def check_builder_mirror():
    """MaterialBuilder on hand-made IRs (bead maxdrop-em3.60): a mirrored axis shows two copies per tile, the second
    mirrored (ping-pong of twice the placed coordinate), mirror winning over tile, with and without a crop; the
    nodes evaluated at 3ds Max's sample points give the image coordinates 3ds Max rendered; one extension where both
    axes agree, per-axis nodes where they differ."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-builder-mirror-")
    try:
        png = os.path.join(scratch, "shared.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        builder = build_materials.MaterialBuilder()

        def tex_mask(name, mapping, crop=None):
            ir = cm.MaterialIR(30, name, "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
            img = tx.Image(1, "shared.png", "shared.png", "", found, mapping=mapping, crop=crop)
            ir.textures = {"base_color": tx.TextureGraphIR(img, tx.COLOR)}
            return _image_of(_principled(builder.make(ir)).inputs["Base Color"])

        def tex_of(name, mapping, crop=None):
            return tex_mask(name, mapping, crop)[0]

        for label, kw, crop, (w, h), sweep, fixed, channel, values in _MIRROR_ROWS:
            tex, mask = tex_mask("Mirror " + label, tx.Mapping(**kw), tx.Crop(*crop) if crop else None)
            bad = []
            for i, value in enumerate(values.split()):
                x, y = (i, fixed) if sweep == "row" else (fixed, i)
                got = _sample_image(tex, ((x + 0.5) / w, 1.0 - (y + 0.5) / h), mask)
                if value == "-":
                    if got is not None:
                        bad.append((i, value, got))
                    continue
                want = (int(value) / 4 + 0.5) / 64
                want = want if channel == "R" else 1.0 - want
                if got is None or abs(got[0 if channel == "R" else 1] - want) > 1.0 / 64:
                    bad.append((i, value, got))
            check("builder mirror: %s: the nodes read the image where 3ds Max rendered it" % label, not bad,
                  "%s %s" % (tex.extension, bad[:4]))

        def double(node, factor):
            return (node is not None and node.bl_idname == "ShaderNodeVectorMath" and node.operation == 'MULTIPLY'
                    and close(list(_input(node, "Vector_001").default_value), factor, 1e-6))

        tex = tex_of("MirrorTileBoth", tx.Mapping(tile=(True, True), mirror=(True, True)))
        mul = _from(tex.inputs["Vector"])
        check("builder mirror: mirror and tile on both axes, no placement: UV -> times (2, 2, 1) -> image MIRROR",
              tex.extension == 'MIRROR' and double(mul, [2.0, 2.0, 1.0])
              and _from(mul.inputs["Vector"]).bl_idname == "ShaderNodeTexCoord",
              "%s %s" % (tex.extension, mul and mul.bl_idname))

        tex = tex_of("MirrorUTileV", tx.Mapping(tile=(True, True), mirror=(True, False)))
        comb = _from(tex.inputs["Vector"])
        x, y = (_from(comb.inputs[a]) for a in ("X", "Y")) if comb is not None else (None, None)
        sep = x and _from(x.inputs[0])
        check("builder mirror: mirror U, tile V: times (2, 1, 1) -> ping-pong X, wrap Y -> image EXTEND (REPEAT "
              "would bleed the opposite edge into the mirror line)",
              tex.extension == 'EXTEND' and comb.bl_idname == "ShaderNodeCombineXYZ" and x.operation == 'PINGPONG'
              and y.operation == 'WRAP' and _from(y.inputs[0]) == sep and sep.bl_idname == "ShaderNodeSeparateXYZ"
              and double(_from(sep.inputs["Vector"]), [2.0, 1.0, 1.0]),
              "%s %s" % (tex.extension, comb and comb.bl_idname))

        tex = tex_of("TileUOnly", tx.Mapping(tile=(True, False)))
        comb = _from(tex.inputs["Vector"])
        x, y = (_from(comb.inputs[a]) for a in ("X", "Y")) if comb is not None else (None, None)
        check("builder mirror: tile U only: wrap X, Y straight through -> image EXTEND, Y clipped by a mask (CLIP "
              "would fade the border half-texel at every tile line)",
              tex.extension == 'EXTEND' and x is not None and x.operation == 'WRAP'
              and y.bl_idname == "ShaderNodeSeparateXYZ" and _clip_axes_of(tex) == ["Y"],
              "%s %s %s" % (tex.extension, comb and comb.bl_idname, _clip_axes_of(tex)))
        tex = tex_of("MirrorVClipU", tx.Mapping(tile=(False, True), mirror=(False, True)))
        check("builder mirror: mirror V, U clipped: image EXTEND, X clipped by a mask",
              tex.extension == 'EXTEND' and _clip_axes_of(tex) == ["X"], "%s %s" % (tex.extension,
                                                                                    _clip_axes_of(tex)))

        tex = tex_of("TileBoth", tx.Mapping())
        check("builder mirror: tile both, no placement: no vector, image REPEAT",
              tex.extension == 'REPEAT' and not tex.inputs["Vector"].is_linked, tex.extension)
        tex, mask = tex_mask("TileNone", tx.Mapping(tile=(False, False)))
        check("builder mirror: tile off both, no placement: no vector, image CLIP, no mask",
              tex.extension == 'CLIP' and not tex.inputs["Vector"].is_linked and mask is None, tex.extension)
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_clip_mask():
    """MaterialBuilder on hand-made IRs (bead maxdrop-em3.112): an image that repeats on one axis and clips on the
    other is drawn EXTEND with a clip mask, which every output of its Image Texture goes through (Color and Alpha:
    an alpha image, a Composite layer's alpha), one Clip node per output however many inputs read it."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-builder-clip-")
    try:
        png = os.path.join(scratch, "shared.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        builder = build_materials.MaterialBuilder()
        mixed = tx.Mapping(tiling=(2.0, 2.0), tile=(True, False))

        def clips_of(tex):
            """{output name: [the nodes its links go to]} of the linked outputs."""
            return {o.name: [link.to_node for link in o.links] for o in tex.outputs if o.is_linked}

        alpha = tx.Image(1, "shared.png", "shared.png", "", found, colorspace=tx.NON_COLOR, alpha=True, mapping=mixed)
        ir = cm.MaterialIR(50, "ClipAlpha", "test", alpha=cm.Input(1.0, cm.MapRef(1)))
        ir.textures = {"alpha": tx.TextureGraphIR(alpha, tx.DATA)}
        m = builder.make(ir)
        tex = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage")
        outs = clips_of(tex)
        check("builder clip mask: an alpha image tiled in U, clipped in V: EXTEND, its Alpha only through a Clip node "
              "masking V", tex.extension == 'EXTEND' and list(outs) == ["Alpha"]
              and all(n.label == CLIP_LABEL for n in outs["Alpha"]) and _clip_axes_of(tex) == ["Y"], str(outs))

        top = tx.Image(2, "shared.png", "shared.png", "", found, mapping=mixed)
        bottom = tx.Image(3, "shared.png", "shared.png", "", found)
        layered = tx.Composite((tx.CompositeLayer(bottom), tx.CompositeLayer(top, 0.5)))
        ir = cm.MaterialIR(51, "ClipLayer", "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)),
                           emission_color=cm.Input((0.0, 0.0, 0.0), cm.MapRef(2)))
        ir.textures = {"base_color": tx.TextureGraphIR(layered, tx.COLOR),
                       "emission_color": tx.TextureGraphIR(top, tx.COLOR)}
        m = builder.make(ir)
        texes = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.inputs["Vector"].is_linked]
        tex = texes[0] if len(texes) == 1 else None
        outs = clips_of(tex) if tex is not None else {}
        clip_nodes = [n for n in m.node_tree.nodes if n.label == CLIP_LABEL]
        check("builder clip mask: a Composite layer and the emission read one mixed-axis image: its Color and its "
              "Alpha (the layer's factor) each through one Clip node, the same mask",
              tex is not None and sorted(outs) == ["Alpha", "Color"]
              and all(n.label == CLIP_LABEL and n in clip_nodes for ns in outs.values() for n in ns)
              and len(clip_nodes) == 2 and len({_from(_clip_mask_input(n)) for n in clip_nodes}) == 1
              and _clip_axes_of(tex) == ["Y"],
              "%d textures, %s, %d Clip nodes" % (len(texes), sorted(outs), len(clip_nodes)))
        for name in ("Base Color", "Emission Color"):
            check("builder clip mask: %s linked" % name, _principled(m).inputs[name].is_linked)
        check("builder clip mask: the tests' Clip label is the builder's",
              CLIP_LABEL == build_materials.CLIP_LABEL, build_materials.CLIP_LABEL)

        rough = tx.Image(4, "shared.png", "shared.png", "", found, colorspace=tx.NON_COLOR, mapping=mixed)
        ir = cm.MaterialIR(52, "ClipData", "test", roughness=cm.Input(0.5, cm.MapRef(1)))
        ir.textures = {"roughness": tx.TextureGraphIR(rough, tx.DATA)}
        m = builder.make(ir)
        tex = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage")
        outs = clips_of(tex)
        mean = _meaned(_principled(m).inputs["Roughness"])
        check("builder clip mask: a data map (roughness) over a mixed-axis image: the mean of its masked Color",
              list(outs) == ["Color"] and all(n.label == CLIP_LABEL for n in outs["Color"])
              and mean is not None and mean.label == CLIP_LABEL and _from(mean.inputs[0]) == tex,
              "%s %s" % (outs, getattr(mean, "bl_idname", None)))

        lost = tx.Image(5, "nothere.png", "C:\\x\\nothere.png", "", None, mapping=mixed)
        ir = cm.MaterialIR(53, "ClipLost", "test", base_color=cm.Input((0.1, 0.2, 0.3), cm.MapRef(1)))
        ir.textures = {"base_color": tx.TextureGraphIR(lost, tx.COLOR)}
        m = builder.make(ir)
        check("builder clip mask: a missing image gets no mask nodes",
              not any(n.bl_idname == "ShaderNodeMath" and n.operation == 'COMPARE' for n in m.node_tree.nodes)
              and not any(n.label == CLIP_LABEL for n in m.node_tree.nodes))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_conversion_failure(max_path):
    """The material conversion raises: the operator imports the scene without materials and the report says so."""
    import maxdrop.ops as ops
    empty_scene()
    original = ops._material_slots

    def failing(*args, **kwargs):
        raise RuntimeError("maxdrop test: conversion fails")

    ops._material_slots = failing
    try:
        result = bpy.ops.import_scene.maxdrop(filepath=max_path)
    finally:
        ops._material_slots = original
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    check("conversion failure: the scene imported without materials, the report says why",
          result == {'FINISHED'} and len(bpy.data.objects) > 0 and not bpy.data.materials
          and "materials: not converted (RuntimeError: maxdrop test: conversion fails): the scene is imported "
              "without materials" in body and "Material issues: 1" in body,
          "%s %d objects %d materials | %s" % (result, len(bpy.data.objects), len(bpy.data.materials), body[-500:]))
    empty_scene()


def check_light_note_on_failure(max_path):
    """A file with lights whose gamma setting is not found and whose material conversion raises: the swatch note of
    the light colors is still in the report (with converted materials it comes through them)."""
    import maxdrop.ops as ops
    from maxdrop.convert import colors
    empty_scene()
    original_slots, original_rule = ops._material_slots, colors.of_scene

    def failing(*args, **kwargs):
        raise RuntimeError("maxdrop test: conversion fails")

    ops._material_slots, colors.of_scene = failing, lambda source: colors.UNKNOWN
    try:
        result = bpy.ops.import_scene.maxdrop(filepath=max_path)
    finally:
        ops._material_slots, colors.of_scene = original_slots, original_rule
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    check("conversion failure: the light colors' swatch note is still reported",
          result == {'FINISHED'} and len(bpy.data.lights) > 0 and "color swatches: " + colors.GAMMA_NOTE in body,
          "%s %d lights | %s" % (result, len(bpy.data.lights), body[-500:]))
    empty_scene()


def check_ies_header(max_path):
    """max_path (lights_photometric) copied beside a self-authored fixture_web.ies, rated 500 lm, 100 cd in every
    direction: the import finds it, IesPower (1500, override off) gets 1500 x 400 pi / 500 lm, IesOverride (override
    on) keeps 300 lm; the report has no rated-lumens line for it."""
    from maxdrop import ops
    from maxdrop.convert import lights
    empty_scene()
    scratch = tempfile.mkdtemp(prefix="maxdrop-ies-")
    try:
        dst = os.path.join(scratch, os.path.basename(max_path))
        shutil.copy(max_path, dst)
        with open(os.path.join(scratch, "fixture_web.ies"), "wb") as f:
            f.write(b"IESNA:LM-63-2002\n[TEST] MaxDrop test\nTILT=NONE\n1 500 1 3 1 1 2 0 0 0\n1 1 0\n0 90 180\n0\n"
                    b"100 100 100\n")
        result = bpy.ops.import_scene.maxdrop(filepath=dst)
        energy = {n: bpy.data.objects[n].data.energy for n in ("IesPower", "IesOverride") if n in bpy.data.objects}
        want = {"IesPower": 1500.0 * 400.0 * math.pi / 500.0 / 683.0 * ops.LIGHT_STRENGTH,
                "IesOverride": 300.0 / 683.0 * ops.LIGHT_STRENGTH}
        check("ies header: IesPower is power x the file's flux / its rated lumens, IesOverride its power",
              result == {'FINISHED'} and set(energy) == set(want)
              and all(abs(energy[n] - w) <= w * 1e-5 for n, w in want.items()), "%s %s vs %s" % (result, energy, want))
        text = bpy.data.texts.get("MaxDrop Report")
        body = text.as_string() if text is not None else ""
        check("ies header: no rated-lumens line in the report", text is not None and lights.IES_RATED not in body,
              body[-600:])
    finally:
        empty_scene()
        shutil.rmtree(scratch, ignore_errors=True)


def check_reader_defect(first, second):
    """A TypeError or KeyError of the reading (a reader defect, never raised on purpose) reports the file as not
    imported, its type in the reason, instead of ending the operator: in a run of two files, synchronous and with the
    reading in the worker thread, the other file is still imported; alone, the operator reports Nothing imported;
    the pre-flight line says it is not readable."""
    import contextlib
    import io
    from maxdrop import ops
    from maxdrop.reader import assets
    from maxdrop.reader import scene as reader_scene
    name = os.path.basename(first)
    reason = "a defect in MaxDrop's reader (TypeError: maxdrop test: reader defect), see the console"
    original_table = assets.AssetTable.__dict__["from_file"]  # the classmethods themselves, put back as they were
    original_scene = reader_scene.Scene.__dict__["from_file"]
    calls = []

    def failing_first(cls, cf):
        calls.append(cf)
        if len(calls) == 1:
            raise TypeError("maxdrop test: reader defect")
        return original_table.__func__(cls, cf)

    def no_scene(cls, *args, **kwargs):
        raise KeyError("maxdrop test")

    try:
        for threaded in (False, True):
            label = "threaded" if threaded else "synchronous"
            empty_scene()
            del calls[:]
            assets.AssetTable.from_file = classmethod(failing_first)
            run = _cancel_run([first, second])
            steps = run.steps(threaded=threaded)
            console = io.StringIO()
            with contextlib.redirect_stdout(console):
                _advance(steps, lambda: False)
            assets.AssetTable.from_file = original_table
            printed = console.getvalue()
            sys.stdout.write(printed)
            check("reader defect: %s run, the traceback is in the console" % label,
                  "MaxDrop: reading %s failed, a defect in MaxDrop (please report it with this traceback):" % name
                  in printed and "Traceback (most recent call last)" in printed
                  and "TypeError: maxdrop test: reader defect" in printed, printed[-500:])
            check("reader defect: %s run, the file is not imported, the other one is" % label,
                  ('WARNING', "Not imported: %s: %s" % (name, reason)) in run.lines and len(bpy.data.objects) > 0
                  and len(calls) == 2,
                  "%d objects, %d calls | %s" % (len(bpy.data.objects), len(calls), run.lines[-3:]))
        empty_scene()
        del calls[:]
        assets.AssetTable.from_file = classmethod(failing_first)
        try:
            result, message = bpy.ops.import_scene.maxdrop(filepath=first), ""
        except RuntimeError as e:  # bpy.ops raises with the message when the operator reports an error
            result, message = {'CANCELLED'}, str(e)
        assets.AssetTable.from_file = original_table
        check("reader defect: one file, the operator reports Nothing imported with the reason",
              result == {'CANCELLED'} and "Nothing imported. %s: %s" % (name, reason) in message
              and not bpy.data.objects, "%s %r" % (result, message))
        reader_scene.Scene.from_file = classmethod(no_scene)
        line = ops._preflight(first)
        reader_scene.Scene.from_file = original_scene
        check("reader defect: the pre-flight line of a KeyError says the file is not readable",
              line == "Not readable as a .max file (a defect in MaxDrop's reader (KeyError: 'maxdrop test'), see "
                      "the console)", repr(line))
    finally:
        assets.AssetTable.from_file = original_table
        reader_scene.Scene.from_file = original_scene
        empty_scene()


def check_asset_table_once(max_path):
    """One import of a file with lights and materials reads the file's asset table once (the scene description and
    the material conversion share it)."""
    from maxdrop.reader import assets
    empty_scene()
    original = assets.AssetTable.__dict__["from_file"]  # the classmethod itself, put back as it was
    calls = []

    def counting(cls, cf):
        calls.append(cf)
        return original.__func__(cls, cf)

    assets.AssetTable.from_file = classmethod(counting)
    try:
        result = bpy.ops.import_scene.maxdrop(filepath=max_path)
    finally:
        assets.AssetTable.from_file = original
    check("asset table: read once per import", result == {'FINISHED'} and len(calls) == 1,
          "%s, %d reads" % (result, len(calls)))
    empty_scene()


def check_builder_wiring(ma, mb, builder, cm, tx, srgb, data, lost, gamma):
    """The links and values of the hand-made IRs' nodes, against numbers worked out by hand."""
    pa, pb = _principled(ma), _principled(mb)
    mix = _from(pa.inputs["Base Color"])
    mask = _meaned(_input(mix, "Factor_Float")) if mix.bl_idname == "ShaderNodeMix" else None
    check("wiring: base color Mix: A the swatch, B the sRGB image, the mask image's mean on the factor",
          mix.bl_idname == "ShaderNodeMix" and mix.blend_type == 'MIX' and not _input(mix, "A_Color").is_linked
          and close(list(_input(mix, "A_Color").default_value)[:3], [0.5] * 3, 1e-6)
          and _from(_input(mix, "B_Color")).image.colorspace_settings.name == "sRGB"
          and getattr(mask, "image", None) is not None and mask.image.colorspace_settings.name == "Non-Color")
    inv = _from(pa.inputs["Roughness"])
    check("wiring: roughness 1 - the mean of the data image", inv.bl_idname == "ShaderNodeMath"
          and inv.operation == 'SUBTRACT' and inv.inputs[0].default_value == 1.0
          and getattr(_meaned(inv.inputs[1]), "bl_idname", None) == "ShaderNodeTexImage")
    dot = _from(_specular_socket(pa))
    mul = _from(dot.inputs[0])
    check("wiring: specular map times 2 through a Multiply Mix", mul.bl_idname == "ShaderNodeMix"
          and mul.blend_type == 'MULTIPLY' and _input(mul, "Factor_Float").default_value == 1.0
          and close(list(_input(mul, "B_Color").default_value)[:3], [2.0] * 3, 1e-6))
    gam = _from(pb.inputs["Emission Color"])
    gain = _from(gam.inputs["Color"])
    bc = _from(gain.inputs[0])
    hue = _from(bc.inputs["Color"])
    comp = _from(hue.inputs["Color"])
    check("wiring: Color Correction: Hue 0.75, Saturation 1.5, Bright 0.1, Contrast 0.2, gain 1.2, Gamma 1 / 1.1",
          gam.bl_idname == "ShaderNodeGamma" and abs(gam.inputs["Gamma"].default_value - 1 / 1.1) < 1e-6
          and gain.bl_idname == "ShaderNodeVectorMath" and gain.operation == 'SCALE'
          and abs(_input(gain, "Scale").default_value - 1.2) < 1e-6
          and bc.bl_idname == "ShaderNodeBrightContrast" and abs(_input(bc, "Bright").default_value - 0.1) < 1e-6
          and abs(_input(bc, "Contrast").default_value - 0.2) < 1e-6
          and hue.bl_idname == "ShaderNodeHueSaturation" and abs(hue.inputs["Hue"].default_value - 0.75) < 1e-6
          and abs(hue.inputs["Saturation"].default_value - 1.5) < 1e-6)
    factor = _from(_input(comp, "Factor_Float"))
    top = _from(_input(comp, "B_Color"))
    check("wiring: Composite: the top layer over the bottom by its alpha times 0.5, its gamma override 1.8 applied",
          comp.bl_idname == "ShaderNodeMix" and factor.bl_idname == "ShaderNodeMath" and factor.operation == 'MULTIPLY'
          and abs(factor.inputs[1].default_value - 0.5) < 1e-6 and factor.inputs[0].links[0].from_socket.name == "Alpha"
          and top.bl_idname == "ShaderNodeGamma" and abs(top.inputs["Gamma"].default_value - 1.8) < 1e-6
          and _from(top.inputs["Color"]).image.colorspace_settings.name == "Linear Rec.709")
    amount = _from(_input(comp, "A_Color"))
    level = _from(amount.inputs[0])
    out_inv = _from(level.inputs[0])
    tex, clip = _image_of(out_inv.inputs["Color"])
    crop = _from(tex.inputs["Vector"])
    comb = _from(crop.inputs["Vector"])
    pings = [_from(comb.inputs[axis]) for axis in ("X", "Y")]
    sep = _from(pings[0].inputs[0])
    double = _from(sep.inputs["Vector"])
    place = _from(double.inputs["Vector"])
    uv = _from(place.inputs["Vector"])
    from maxdrop.build import materials as build_materials
    want = build_materials.uv_transform(tx.Mapping(tiling=(2.0, 1.0), angle=(0.0, 0.0, 0.5)))
    check("wiring: Output: inverted, times 2 minus 0.1 (3ds Max's offset under an invert), times 0.5",
          amount.operation == 'SCALE' and abs(_input(amount, "Scale").default_value - 0.5) < 1e-6
          and level.operation == 'MULTIPLY_ADD' and close(list(_input(level, "Vector_001").default_value), [2.0] * 3,
                                                          1e-6)
          and close(list(_input(level, "Vector_002").default_value), [-0.1] * 3, 1e-6)
          and out_inv.bl_idname == "ShaderNodeInvert")
    check("wiring: a placed crop mirrored both ways: UVChannel_2 -> placement -> times (2, 2, 1) -> ping-pong per "
          "axis -> Mapping TEXTURE at (0.1, 0.3) x 0.5",
          crop.bl_idname == "ShaderNodeMapping" and crop.vector_type == 'TEXTURE'
          and close(list(crop.inputs["Location"].default_value), [0.1, 0.3, 0.0], 1e-6)
          and close(list(crop.inputs["Scale"].default_value), [0.5, 0.5, 1.0], 1e-6)
          and comb.bl_idname == "ShaderNodeCombineXYZ" and sep.bl_idname == "ShaderNodeSeparateXYZ"
          and all(n.operation == 'PINGPONG' and n.inputs[1].default_value == 1.0 for n in pings)
          and _from(pings[1].inputs[0]) == sep
          and double.bl_idname == "ShaderNodeVectorMath" and double.operation == 'MULTIPLY'
          and close(list(_input(double, "Vector_001").default_value), [2.0, 2.0, 1.0], 1e-6)
          and place.bl_idname == "ShaderNodeMapping" and place.vector_type == 'POINT'
          and close(list(place.inputs["Location"].default_value), list(want[0]), 1e-6)
          and close(list(place.inputs["Rotation"].default_value), [0.0, 0.0, 0.5], 1e-6)
          and uv.bl_idname == "ShaderNodeUVMap" and uv.uv_map == "UVChannel_2")
    check("wiring: the placed image's Color masked (Clip) before its Output's invert, as CLIP's black was",
          clip is not None and _from(clip).bl_idname == "ShaderNodeMath" and out_inv.bl_idname == "ShaderNodeInvert")
    bump = _from(pb.inputs["Normal"])
    nm = _from(bump.inputs["Normal"])
    comb = _from(nm.inputs["Color"])
    red, green = _from(comb.inputs["Red"]), _from(comb.inputs["Green"])
    check("wiring: normal map swapped then flipped: Red = 1 - G, Green = 1 - R, Blue = B; its bump at 2 (1, distance 2)",
          bump.bl_idname == "ShaderNodeBump" and bump.inputs["Strength"].default_value == 1.0
          and bump.inputs["Distance"].default_value == 2.0 and abs(nm.inputs["Strength"].default_value - 0.7) < 1e-6
          and red.operation == 'SUBTRACT' and red.inputs[1].links[0].from_socket.identifier == "Green"
          and green.operation == 'SUBTRACT' and green.inputs[1].links[0].from_socket.identifier == "Red"
          and comb.inputs["Blue"].links[0].from_socket.identifier == "Blue")
    c = cm.MaterialIR(12, "Inverted", "test", base_color=cm.Input((0.2, 0.3, 0.4), cm.MapRef(5)))
    c.textures = {"bump": tx.TextureGraphIR(tx.Bump(data, -0.5), tx.BUMP),
                  "base_color": tx.TextureGraphIR(tx.Mix(tx.Constant((0.2, 0.3, 0.4)), srgb, 0.5, gamma), tx.COLOR)}
    d = cm.MaterialIR(13, "Lost", "test", alpha=cm.Input(0.8, cm.MapRef(6)), base_color=cm.Input((0.1, 0.2, 0.3),
                                                                                                  cm.MapRef(7)))
    d.textures = {"normal": tx.TextureGraphIR(tx.NormalMap(lost, 1.0, bump=tx.Bump(lost, 0.5)), tx.NORMAL),
                  "alpha": tx.TextureGraphIR(tx.Mix(tx.Constant(0.8), lost, 0.6), tx.DATA),
                  "base_color": tx.TextureGraphIR(tx.ColorCorrect(lost, hue=0.1), tx.COLOR)}
    mc, md = builder.make(c), builder.make(d)
    b = _from(_principled(mc).inputs["Normal"])
    check("wiring: a negative bump amount inverts the Bump node", b.invert and b.inputs["Strength"].default_value == 0.5)
    mask = _meaned(_input(_from(_principled(mc).inputs["Base Color"]), "Factor_Float"))
    check("wiring: a mask with a gamma override is decoded by a Gamma node of 1.8, then the mean (maxdrop-em3.122)",
          getattr(mask, "bl_idname", None) == "ShaderNodeGamma"
          and abs(_input(mask, "Gamma").default_value - 1.8) < 1e-6
          and getattr(_from(_input(mask, "Color")), "bl_idname", None) == "ShaderNodeTexImage")
    pd = _principled(md)
    check("wiring: missing images leave the IR's values: Normal free, alpha 0.8 (BLENDED), base color the swatch",
          not pd.inputs["Normal"].is_linked and not pd.inputs["Alpha"].is_linked
          and abs(pd.inputs["Alpha"].default_value - 0.8) < 1e-6 and md.surface_render_method == 'BLENDED'
          and not pd.inputs["Base Color"].is_linked
          and close(list(pd.inputs["Base Color"].default_value)[:3], [0.1, 0.2, 0.3], 1e-6)
          and not any(o.is_linked for n in md.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" for o in n.outputs)
          and len([n for n in md.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"]) == 1)


def _node_kinds(material):
    """{bl_idname, and bl_idname:operation or :blend_type where a node has one} of a material's nodes."""
    out = set()
    for n in material.node_tree.nodes:
        out.add(n.bl_idname)
        for attr in ("operation", "blend_type"):
            if hasattr(n, attr):
                out.add("%s:%s" % (n.bl_idname, getattr(n, attr)))
    return out


def _upstream(socket):
    """Every node that feeds socket, directly or further up."""
    out, todo = {}, [socket]
    while todo:
        for link in todo.pop().links:
            n = link.from_node
            if n.name not in out:
                out[n.name] = n
                todo.extend(n.inputs)
    return list(out.values())


def check_reflection_falloff():
    """vray_texmaps imported: a Falloff in a VRayMtl's reflection drives the reflection weight by the angle (Layer
    Weight for perpendicular / parallel, the Fresnel node for Fresnel), not its color 1."""
    for name, kind in (("FixtureVReflPerp", "ShaderNodeLayerWeight"), ("FixtureVReflFresnel", "ShaderNodeFresnel")):
        m = bpy.data.materials.get(name)
        socket = _specular_socket(_principled(m)) if m is not None else None
        nodes = _upstream(socket) if socket is not None else []
        by_facing = [n for n in nodes if n.bl_idname == "ShaderNodeMix"
                     and getattr(_from(_input(n, "Factor_Float")), "bl_idname", None) == kind]
        check("vray_texmaps/%s: the reflection Falloff into the reflection weight, a Mix by %s" % (name, kind),
              socket is not None and socket.is_linked and len(by_facing) == 1,
              str(sorted(n.bl_idname for n in nodes)))


def check_wrapper_nodes():
    """texmap_wrappers imported with its textures found: the node types and links each wrapper is drawn with."""
    wants = {
        "FixtureWrapFalloff": {"ShaderNodeLayerWeight", "ShaderNodeFresnel", "ShaderNodeNewGeometry",
                               "ShaderNodeVectorMath:DOT_PRODUCT", "ShaderNodeMath:MULTIPLY_ADD", "ShaderNodeMix:MIX"},
        "FixtureWrapComposite": {"ShaderNodeMix:MULTIPLY", "ShaderNodeMix:OVERLAY", "ShaderNodeMix:SCREEN",
                                 "ShaderNodeMix:ADD", "ShaderNodeLayerWeight", "ShaderNodeMath:MULTIPLY"},
        "FixtureWrapColor": {"ShaderNodeInvert", "ShaderNodeSeparateColor", "ShaderNodeCombineColor",
                             "ShaderNodeVectorMath:DOT_PRODUCT", "ShaderNodeMath:SUBTRACT", "ShaderNodeBrightContrast"},
        "FixtureWrapOutput": {"ShaderNodeVectorMath:MULTIPLY_ADD", "ShaderNodeVectorMath:SCALE",
                              "ShaderNodeVectorMath:ADD", "ShaderNodeSeparateColor", "ShaderNodeInvert"},
    }
    for name, want in wants.items():
        m = bpy.data.materials.get(name)
        kinds = _node_kinds(m) if m is not None else set()
        check("texmap_wrappers/%s: its wrappers' nodes" % name, want <= kinds, str(sorted(want - kinds)))
    p = _principled(bpy.data.materials["FixtureWrapFalloff"])
    mix = _from(p.inputs["Base Color"])
    side = _from(_input(mix, "A_Color"))
    check("texmap_wrappers: the Falloff's side 1 is lerp(color 1, its map, 0.6), by Layer Weight Facing",
          _from(_input(mix, "Factor_Float")).bl_idname == "ShaderNodeLayerWeight" and side.bl_idname == "ShaderNodeMix"
          and abs(_input(side, "Factor_Float").default_value - 0.6) < 1e-6
          and _from(_input(side, "B_Color")).bl_idname == "ShaderNodeTexImage")
    p = _principled(bpy.data.materials["FixtureWrapComposite"])
    top = _from(p.inputs["Base Color"])
    screen = _from(_input(top, "B_Color"))
    check("texmap_wrappers: the Composite's top layer: Screen, then a clamped Mix by 0.7 times its image's alpha",
          screen.blend_type == 'SCREEN' and top.clamp_result
          and _from(_input(top, "Factor_Float")).operation == 'MULTIPLY'
          and abs(_from(_input(top, "Factor_Float")).inputs[1].default_value - 0.7) < 1e-6)


def check_wrapper_wiring(builder, cm, tx, srgb, data):
    """The nodes of the wrappers maxdrop-3gc.3 draws (Falloff's Facing, Composite blend modes and masks, Color
    Correction rewiring, Adjust, Tint) on a hand-made IR, against the measured 3ds Max rules."""
    L = tx.CompositeLayer
    tinted = tx.Tint(srgb, (1.0, 0.5, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    adjusted = tx.Adjust(srgb, tx.TexOutput(level=2.0, offset=0.1))
    custom = tx.ColorCorrect(srgb, rewire=(2, 4, tx.RW_MONO))
    comp = tx.Composite((L(srgb), L(tinted, 0.5, tx.SCREEN, data), L(adjusted, 1.0, tx.SPOTLIGHT_BLEND),
                         L(custom, 0.25, tx.HARD_LIGHT)))
    w = cm.MaterialIR(14, "Wrappers", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)),
                      roughness=cm.Input(0.4, cm.MapRef(1)), metallic=cm.Input(0.0, cm.MapRef(1)),
                      emission_color=cm.Input((0.0,) * 3, cm.MapRef(1)), specular=cm.Input(0.5, cm.MapRef(1)),
                      transmission=cm.Input(0.0, cm.MapRef(1)))
    w.textures = {
        "base_color": tx.TextureGraphIR(tx.Mix(tx.Constant((0.0,) * 3), srgb, 0.0, tx.Facing(tx.PERPENDICULAR)),
                                        tx.COLOR),
        "roughness": tx.TextureGraphIR(tx.Mix(tx.Constant(0.2), tx.Constant(0.8), 0.0, tx.Facing(tx.FRESNEL, 1.45)),
                                       tx.DATA),
        "metallic": tx.TextureGraphIR(tx.Mix(tx.Constant(0.0), tx.Constant(1.0), 0.0, tx.Facing(tx.TOWARDS)),
                                      tx.DATA),
        "emission_color": tx.TextureGraphIR(comp, tx.COLOR),
        "specular": tx.TextureGraphIR(tx.ColorCorrect(srgb, rewire=tx.REWIRE_MONO), tx.COLOR),
        "transmission": tx.TextureGraphIR(tx.ColorCorrect(srgb, rewire=tx.REWIRE_INVERT), tx.COLOR)}
    mw = builder.make(w)
    check("wrappers: material built", mw is not None)
    if mw is None:
        return
    p = _principled(mw)
    mix = _from(p.inputs["Base Color"])
    lw = _from(_input(mix, "Factor_Float"))
    check("wrappers: Falloff perpendicular / parallel: a Mix by Layer Weight Facing at blend 0.5",
          mix.bl_idname == "ShaderNodeMix" and lw.bl_idname == "ShaderNodeLayerWeight"
          and _input(mix, "Factor_Float").links[0].from_socket.identifier == "Facing"
          and abs(_input(lw, "Blend").default_value - 0.5) < 1e-6
          and _from(_input(mix, "B_Color")).bl_idname == "ShaderNodeTexImage")
    mix = _from(p.inputs["Roughness"])
    fr = _from(_input(mix, "Factor_Float"))
    check("wrappers: Falloff Fresnel: a float Mix by the Fresnel node at IOR 1.45",
          mix.bl_idname == "ShaderNodeMix" and mix.data_type == 'FLOAT' and fr.bl_idname == "ShaderNodeFresnel"
          and abs(_input(fr, "IOR").default_value - 1.45) < 1e-6
          and abs(_input(mix, "A_Float").default_value - 0.2) < 1e-6)
    mix = _from(p.inputs["Metallic"])
    ma = _from(_input(mix, "Factor_Float"))
    dot = _from(ma.inputs[0]) if ma is not None else None
    geo = {link.from_socket.identifier for s in dot.inputs for link in s.links} if dot is not None else set()
    check("wrappers: Falloff towards / away: (1 - Normal . Incoming) / 2 of the Geometry node",
          ma.bl_idname == "ShaderNodeMath" and ma.operation == 'MULTIPLY_ADD'
          and (ma.inputs[1].default_value, ma.inputs[2].default_value) == (-0.5, 0.5)
          and dot.operation == 'DOT_PRODUCT' and geo == {"Normal", "Incoming"})
    dot = _from(_from(_specular_socket(p)).inputs[0])
    check("wrappers: Color Correction monochrome: the mean of the channels",
          dot.bl_idname == "ShaderNodeVectorMath" and dot.operation == 'DOT_PRODUCT'
          and close(list(_input(dot, "Vector_001").default_value), [1 / 3.0] * 3, 1e-6)
          and _from(_input(dot, "Vector")).bl_idname == "ShaderNodeTexImage")
    inv = _from(_from(p.inputs["Transmission Weight"]).inputs[0])
    check("wrappers: Color Correction invert: an Invert node", inv.bl_idname == "ShaderNodeInvert")
    top = _from(p.inputs["Emission Color"])
    hard = _from(_input(top, "B_Color"))
    comb = _from(_input(hard, "A_Color"))
    third = _from(_input(hard, "B_Color"))
    check("wrappers: Composite hard light at 25 %: Overlay with the layer as A over the result as B, then a clamped "
          "Mix by 0.25",
          top.blend_type == 'MIX' and top.clamp_result and abs(_input(top, "Factor_Float").default_value - 0.25) < 1e-6
          and hard.blend_type == 'OVERLAY' and abs(_input(hard, "Factor_Float").default_value - 1.0) < 1e-6
          and comb.bl_idname == "ShaderNodeCombineColor" and _from(_input(top, "A_Color")) == third)
    red, green, blue = (_input(comb, k).links[0] for k in ("Red", "Green", "Blue"))
    check("wrappers: Color Correction custom (B, 1 - R, mono): Separate / Combine Color",
          red.from_socket.identifier == "Blue" and red.from_node.bl_idname == "ShaderNodeSeparateColor"
          and green.from_node.operation == 'SUBTRACT' and green.from_node.inputs[1].links[0].from_socket.identifier
          == "Red" and blue.from_node.operation == 'DOT_PRODUCT')
    add = _from(_input(third, "B_Color"))
    mul = _from(_input(add, "B_Color"))
    adj = _from(_input(mul, "B_Color"))
    second = _from(_input(third, "A_Color"))
    check("wrappers: Composite spotlight blend: below + below x layer; the layer's Output times 2 plus 0.1",
          third.clamp_result and abs(_input(third, "Factor_Float").default_value - 1.0) < 1e-6
          and add.blend_type == 'ADD' and mul.blend_type == 'MULTIPLY' and _from(_input(add, "A_Color")) == second
          and _from(_input(mul, "A_Color")) == second and adj.operation == 'MULTIPLY_ADD'
          and close(list(_input(adj, "Vector_002").default_value), [0.1] * 3, 1e-6))
    screen = _from(_input(second, "B_Color"))
    factor = _from(_input(second, "Factor_Float"))
    tint = _from(_input(screen, "B_Color"))
    scales = [n for n in mw.node_tree.nodes if n.bl_idname == "ShaderNodeVectorMath" and n.operation == 'SCALE']
    mean = _from(factor.inputs[0])
    check("wrappers: Composite screen at 50 % with a mask: Screen of the Tint, Mix by mean(mask) x 0.5; Tint as "
          "three scales and two adds",
          screen.blend_type == 'SCREEN' and factor.operation == 'MULTIPLY'
          and abs(factor.inputs[1].default_value - 0.5) < 1e-6 and getattr(mean, "operation", None) == 'DOT_PRODUCT'
          and close(list(_input(mean, "Vector_001").default_value), [1 / 3.0] * 3, 1e-6)
          and _from(_input(mean, "Vector")).image.colorspace_settings.name == "Non-Color"
          and tint.operation == 'ADD' and len(scales) == 3
          and any(close(list(_input(n, "Vector").default_value), [1.0, 0.5, 0.0], 1e-6) for n in scales)
          and _from(_input(second, "A_Color")).bl_idname == "ShaderNodeTexImage")
    missing = tx.Image(9, "nothere.png", "nothere.png", "", None, colorspace=tx.NON_COLOR)
    lone = tx.Composite((L(tx.Constant(0.3)), L(missing, 1.0, tx.MULTIPLY_BLEND)))
    f = cm.MaterialIR(15, "LoneLayer", "test", roughness=cm.Input(0.4, cm.MapRef(1)))
    f.textures = {"roughness": tx.TextureGraphIR(tx.Invert(lone), tx.DATA)}
    mf = builder.make(f)
    rough = _principled(mf).inputs["Roughness"] if mf is not None else None
    check("wrappers: a blended Composite left with one constant layer in a float input (a glossiness map under an "
          "Invert) is that constant: 1 - 0.3",
          rough is not None and not rough.is_linked and abs(rough.default_value - 0.7) < 1e-6,
          "%s %s" % (mf, builder.issues()[-1:]))


def check_layers_more(root, obs, view_layer):
    """layers_more as 3ds Max saved it: the flags of a hidden, a frozen and a non-rendering layer go on their
    collections, not on their objects; the child layer sits below its parent (which holds no node); a hidden parent
    leaves its child visible."""
    text = "FixtureLäyer中"
    check("layers_more: the layer collections, the child layer below its parent",
          [c.name for c in root.children] == ["0", "FixtureHiddenLayer", "FixtureFrozenLayer", "FixtureNoRenderLayer",
                                              "FixtureParentLayer", text]
          and [c.name for c in root.children["FixtureParentLayer"].children] == ["FixtureChildLayer"],
          str([c.name for c in root.children]))
    lcs = view_layer.layer_collection.children[root.name].children
    excluded = [lc.name for lc in lcs if lc.exclude]
    check("layers_more: the hidden layer excluded in the view layer", excluded == ["FixtureHiddenLayer"], str(excluded))
    flags = {c.name: (c.hide_select, c.hide_render) for c in root.children_recursive}
    want = {c: (c == "FixtureFrozenLayer", c == "FixtureNoRenderLayer") for c in flags}
    check("layers_more: hide_select on the frozen layer's collection, hide_render on the non-rendering one's",
          flags == want, str(flags))
    visible = {ob.name for ob in view_layer.objects}
    check("layers_more: only the hidden layer's object is out of the view layer",
          {ob.name for ob in obs} - visible == {"FixtureOnHiddenLayer"}, str(sorted(visible)))
    own = {ob.name: (ob.hide_get(view_layer=view_layer), ob.hide_select, ob.hide_render) for ob in obs
           if ob.name in visible}
    check("layers_more: only the nodes' own flags on objects (FixtureHiddenParent hidden, FixtureFrozen frozen)",
          {k: v for k, v in own.items() if any(v)} == {"FixtureHiddenParent": (True, False, False),
                                                       "FixtureFrozen": (False, True, False)}, str(own))
    child = bpy.data.objects["FixtureVisibleChild"]
    check("layers_more: the hidden parent's child is visible, its child in Blender",
          child.parent is bpy.data.objects["FixtureHiddenParent"] and child.visible_get(view_layer=view_layer))


def check_layers_nested(root, obs, view_layer, oracle):
    """layers_nested as 3ds Max saved it: the flag sits on the parent layer only, and the layers below (one and two
    levels down) are hidden or frozen with it, as the oracle's layer flags (MAXScript's) say. Excluding a parent's
    collection leaves out the collections below it; hide_select on a parent's reaches them too."""
    flags = {la["name"]: la for la in oracle["layers"]}
    by_layer = {o["name"]: flags[o["layer"]] for o in oracle["nodes"]}
    want_out = {k for k, la in by_layer.items() if la["hidden"]}
    want_frozen = {k for k, la in by_layer.items() if la["frozen"]}
    check("layers_nested: the oracle calls the layers below a hidden or frozen parent hidden or frozen",
          want_out == {"FixtureUnderHiddenParent", "FixtureDeepNested"} and want_frozen == {"FixtureUnderFrozenParent"},
          "%s %s" % (sorted(want_out), sorted(want_frozen)))
    lcs = view_layer.layer_collection.children[root.name].children
    excluded = [lc.name for lc in lcs if lc.exclude]
    check("layers_nested: the hidden parent layers' collections excluded",
          excluded == ["FixtureHiddenParentLayer", "FixtureTopLayer"], str(excluded))
    check("layers_nested: hide_select on the frozen parent layer's collection only",
          [c.name for c in root.children_recursive if c.hide_select] == ["FixtureFrozenParentLayer"]
          and not any(c.hide_render for c in root.children_recursive))
    visible = {ob.name for ob in view_layer.objects}
    names = {ob.name for ob in obs}
    check("layers_nested: the objects below a hidden parent layer are out of the view layer",
          names - visible == want_out, str(sorted(names - visible)))
    shown = [ob for ob in obs if ob.name in visible]
    check("layers_nested: no object carries a flag of its own",
          not any(ob.hide_get(view_layer=view_layer) or ob.hide_select or ob.hide_render for ob in shown))
    for ob in shown:
        ob.select_set(True, view_layer=view_layer)
    picked = {ob.name for ob in shown if ob.select_get(view_layer=view_layer)}
    for ob in shown:
        ob.select_set(False, view_layer=view_layer)
    check("layers_nested: the object below the frozen parent layer cannot be selected, FixtureControl can",
          picked == {ob.name for ob in shown} - want_frozen and "FixtureControl" in picked, str(sorted(picked)))


def _local(a, t):
    """A Blender 4x4 (rows) of a 3x3 and a translation."""
    return tuple(tuple(a[r]) + (t[r],) for r in range(3)) + ((0.0, 0.0, 0.0, 1.0),)


def check_shear(modules):
    """A hand-made description with sheared local matrices (a scale along a rotated axis), with and without a
    parent, one with a zero scale: Blender's world matrices equal the products of the locals."""
    import numpy
    convert_scene, build_objects = modules[0], modules[2]
    empty_scene()
    desc = convert_scene.SceneDescription(1.0)
    md = convert_scene.MeshDescription(
        "tri", "ShearTri", numpy.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], dtype=numpy.float32),
        numpy.array([0, 1, 2], dtype=numpy.int32), numpy.array([0], dtype=numpy.int32),
        numpy.array([3], dtype=numpy.int32), numpy.zeros(1, dtype=numpy.int32), numpy.zeros(1, dtype=bool),
        numpy.zeros((0, 2), dtype=numpy.int32), [])
    desc.meshes["tri"] = md
    c, s = 0.8, 0.6
    plain = _local(((c, -s, 0), (s, c, 0), (0, 0, 1)), (0.5, -1.0, 2.0))
    nodes = [  # index, name, parent, local, kind, sheared, hidden
        (1, "ShearTop", None, _local(((1, 0.4, 0), (0.1, 1.2, 0.3), (0, 0, 0.8)), (1, 2, 3)), "EMPTY", True, False),
        (2, "ShearChild", 1, _local(((0.9, 0, 0.5), (0.2, 1.1, 0), (0, -0.3, 1.4)), (-2, 0.5, 1)), "MESH", True,
         False),
        (3, "ShearGrandchild", 2, plain, "MESH", False, False),
        (4, "ShearHiddenTop", None, _local(((2, 0.7, 0), (0, 1, 0), (0.2, 0, 1)), (3, -1, 0)), "MESH", True, True),
        (5, "PlainTop", None, plain, "EMPTY", False, False),
        (6, "ShearZeroScale", 5, _local(((0, 0.5, 0), (0, 1, 0), (0, 0.3, 1)), (1, 1, 1)), "EMPTY", True, False),
    ]
    expected = {}
    for index, name, parent, local, kind, sheared, hidden in nodes:
        m = numpy.array(local, dtype=numpy.float64)
        expected[name] = (expected[nodes[parent - 1][1]] @ m) if parent else m
        mesh = "tri" if kind == "MESH" else None
        if mesh:
            md.users.append(index)
        desc.nodes.append(convert_scene.NodeDescription(
            index, name, parent, local, tuple(map(tuple, expected[name].tolist())), kind, mesh, "", False, (),
            hidden=hidden, sheared=sheared))
    cols, built, view_layer = build_scene(desc, "shear", modules)
    helpers = built.helpers
    check("shear: one helper empty, at the identity, in the file's collection",
          len(helpers) == 1 and helpers[0].type == 'EMPTY' and helpers[0].parent is None
          and helpers[0].matrix_world == Matrix.Identity(4)
          and [col.name for col in helpers[0].users_collection] == [cols.root.name],
          str([(h.name, [col.name for col in h.users_collection]) for h in helpers]))
    for index, name, parent, _local_m, _kind, sheared, _hidden in nodes:
        ob = built.objects[index]
        want = built.objects[parent] if parent else (helpers[0] if sheared and helpers else None)
        check("shear/%s: parent" % name, ob.parent == want, "%r" % (ob.parent and ob.parent.name))
        got = numpy.array(world_of(ob), dtype=numpy.float64)
        error = float(numpy.abs(got - expected[name]).max())
        check("shear/%s: world matrix = the product of the locals" % name, error <= 1e-6, "%.3g" % error)
    roots = sorted(ob.name for ob in built.roots())
    check("shear: roots are the plain top-level object and the helper",
          roots == sorted(["PlainTop"] + [h.name for h in helpers]), str(roots))
    axis = numpy.array([(1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)], dtype=numpy.float64)
    for ob in built.roots():
        ob.matrix_basis = Matrix(axis.tolist()) @ ob.matrix_basis
    view_layer.update()
    errors = {name: float(numpy.abs(numpy.array(world_of(built.objects[index]), dtype=numpy.float64)
                                    - axis @ expected[name]).max()) for index, name, *_rest in nodes}
    check("shear: an axis change on the roots turns every object", max(errors.values()) <= 1e-6, str(errors))
    plain_only = convert_scene.SceneDescription(1.0)
    plain_only.nodes.append(convert_scene.NodeDescription(1, "PlainOnly", None, plain, plain, "EMPTY", None, "",
                                                          False, ()))
    empty_scene()
    _cols, built, _vl = build_scene(plain_only, "no_shear", modules)
    check("shear: no helper without a sheared top-level node", built.helpers == [] and len(bpy.data.objects) == 1)
    if build_objects.SHEAR_HELPER in bpy.data.objects:
        failures.append("shear: helper left over")


def _plan(path, edit=None, pick=None):
    """convert.scene.read of path, edit(desc) applied, then its slot plan; pick(desc, materials) may change the
    {node index: material object index} the plan is made from."""
    from maxdrop.convert import materials as convert_materials
    from maxdrop.convert import scene as convert_scene
    from maxdrop.reader import cfb, materials as reader_materials, scene as reader_scene
    desc = convert_scene.read(path)
    if edit is not None:
        edit(desc)
    with cfb.CompoundFile(path) as cf:
        sc = reader_scene.Scene.from_file(cf)
        conv = convert_materials.MaterialConverter(reader_materials.MaterialGraph(sc))
        materials = convert_materials.node_materials(sc, desc)
        if pick is not None:
            pick(desc, materials)
        slots = convert_materials.assign(desc, materials, conv)
    return desc, slots


def _faces(ob):
    """The material name each face of ob renders with (None: an empty slot)."""
    return [(lambda m: m and m.name)(ob.material_slots[p.material_index].material) for p in ob.data.polygons]


def check_material_slots(modules):
    """Multi/Sub-Object by material ID, slots shared by objects or linked to each, one slot per plain material."""
    import numpy
    fixtures = os.path.join(ROOT, "tests", "fixtures")

    def make(ir):
        return bpy.data.materials.new(ir.name)

    def share(desc):
        nodes = {n.name: n for n in desc.nodes}
        multi, shell = nodes["FixtureMultiBox"], nodes["FixtureShellBox"]
        md = desc.meshes[multi.mesh]
        md.material_indices = numpy.array([0, 2, 6, 0, 2, 6], dtype=numpy.int32)  # IDs 1, 3, 7 (stored zero-based)
        del desc.meshes[shell.mesh]
        shell.mesh = multi.mesh
        md.users = sorted([shell.index, multi.index])

    empty_scene()
    desc, slots = _plan(os.path.join(fixtures, "vray_wrappers.max"), share)
    _cols, built, _vl = build_scene(desc, "material_slots", modules, slots=slots, material=make)
    obs = {n.name: built.objects[n.index] for n in desc.nodes}
    multi, shell = obs["FixtureMultiBox"], obs["FixtureShellBox"]
    check("material slots: faces with IDs 1, 3, 7 on the slots of their sub-materials",
          _faces(multi) == ["FixtureSubOne", None, "FixtureSubSeven"] * 2, str(_faces(multi)))
    check("material slots: three slots on the shared mesh, linked to each object",
          len(multi.data.materials) == 3 and multi.data is shell.data
          and all(s.link == 'OBJECT' for ob in (multi, shell) for s in ob.material_slots),
          str([(s.link, s.material and s.material.name) for s in multi.material_slots]))
    check("material slots: the Shell box renders its original material on every face",
          _faces(shell) == ["FixtureShellOriginal"] * 6, str(_faces(shell)))
    two = obs["FixtureTwoSidedBox"]
    check("material slots: a wrapper gives one slot on the mesh",
          [m.name for m in two.data.materials] == ["FixtureFront"] and two.material_slots[0].link == 'DATA'
          and _faces(two) == ["FixtureFront"] * 6, str(_faces(two)))
    names = sorted(m.name for m in bpy.data.materials)
    check("material slots: one Blender material per Max material",
          names == sorted(["FixtureFront", "FixtureBlendBase", "FixtureShellOriginal", "FixtureSubOne",
                           "FixtureSubSeven"]) and len(built.materials) == 5, str(names))

    empty_scene()
    desc, slots = _plan(os.path.join(fixtures, "standard_physical.max"))
    _cols, built, _vl = build_scene(desc, "standard_physical_slots", modules, slots=slots, material=make)
    got = {n.name: [m.name for m in built.objects[n.index].data.materials] for n in desc.nodes}
    faces = {n.name: [p.material_index for p in built.objects[n.index].data.polygons] for n in desc.nodes}
    check("material slots: Standard and Physical boxes, one slot each",
          got == {"FixtureStandardBox": ["FixtureStandard"], "FixturePhysicalBox": ["FixturePhysical"]}
          and all(v == [0] * 6 for v in faces.values()), "%s %s" % (got, faces))
    check_curve_slots(modules, make)


def check_curve_slots(modules, make):
    """shapes_more: FixtureCurveStd (FixtureCurveRed) and FixtureCurveMulti (ID 1: FixtureCurveSubOne) made to share
    one curve: an empty slot on the curve, linked to each object with its own material; FixtureBox given
    FixtureCurveRed: the mesh and the curve share one Blender material; build_steps counts the curve's slots."""
    build_objects = modules[2]
    nodes_of = {}

    def share(desc):
        nodes_of.update((n.name, n) for n in desc.nodes)
        std, multi = nodes_of["FixtureCurveStd"], nodes_of["FixtureCurveMulti"]
        del desc.curves[multi.curve]
        multi.curve = std.curve
        desc.curves[std.curve].users = sorted([std.index, multi.index])

    def pick(desc, materials):
        materials[nodes_of["FixtureBox"].index] = materials[nodes_of["FixtureCurveStd"].index]

    empty_scene()
    desc, slots = _plan(os.path.join(ROOT, "tests", "fixtures", "shapes_more.max"), share, pick)
    steps = build_objects.build_steps(desc, bpy.context.scene.collection, slots=slots, material=make)
    counts = []
    while True:
        try:
            counts.append(next(steps))
        except StopIteration as end:
            built = end.value
            break
    total = build_objects.steps_of(desc, slots)
    check("curve slots: build_steps ends at steps_of, which counts the curve plans",
          counts[-1] == (total, total) and len(slots.curves) == 3
          and total == build_objects.steps_of(desc, dict(slots)) + 3, "%s %d" % (counts[-1:], total))
    obs = {n.name: built.objects[n.index] for n in desc.nodes}
    std, multi, box = obs["FixtureCurveStd"], obs["FixtureCurveMulti"], obs["FixtureBox"]
    got = [(s.link, s.material and s.material.name) for ob in (std, multi) for s in ob.material_slots]
    check("curve slots: a curve shared by objects with different materials, its slot linked to each object",
          std.data is multi.data and list(std.data.materials) == [None]
          and got == [('OBJECT', "FixtureCurveRed"), ('OBJECT', "FixtureCurveSubOne")], str(got))
    reds = [m.name for m in bpy.data.materials if m.name.startswith("FixtureCurveRed")]
    check("curve slots: a mesh and a curve with the same 3ds Max material share one Blender material",
          reds == ["FixtureCurveRed"] and box.data.materials[0] is std.material_slots[0].material, str(reds))
    with_slots = sorted(ob.name for ob in obs.values() if ob.type == 'CURVE' and len(ob.data.materials))
    check("curve slots: curves without a material get no slot",
          with_slots == ["FixtureCurveIds", "FixtureCurveMixed", "FixtureCurveMulti", "FixtureCurveStd"],
          str(with_slots))

    def curves_only(desc):
        share(desc)
        box = nodes_of["FixtureBox"]
        desc.meshes.clear()
        desc.nodes = [n for n in desc.nodes if n is not box]  # no node is FixtureBox's child

    empty_scene()
    desc, slots = _plan(os.path.join(ROOT, "tests", "fixtures", "shapes_more.max"), curves_only)
    steps = build_objects.build_steps(desc, bpy.context.scene.collection, slots=slots, material=make)
    counts = []
    while True:
        try:
            counts.append(next(steps))
        except StopIteration as end:
            built = end.value
            break
    total = build_objects.steps_of(desc, slots)
    std = built.objects[nodes_of["FixtureCurveStd"].index]
    check("curve slots: a scene without meshes (a Slots that is empty as a dict) still gets its curve slots",
          not slots and len(slots.curves) == 3 and counts[-1] == (total, total)
          and [s.material and s.material.name for s in std.material_slots] == ["FixtureCurveRed"],
          "%s %s" % (counts[-1:], [s.material for s in std.material_slots]))


def _bench():
    """tests/blender/bench.py, the performance budget of one big mesh (its own docstring says what it checks)."""
    spec = importlib.util.spec_from_file_location("maxdrop_bench", os.path.join(ROOT, "tests", "blender", "bench.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_crease_open_edges():
    """build.modifiers: a mesh that asks for creases gets none on its open edges (sharp for a Shell's rim), its other
    sharp edges creased."""
    from maxdrop.build import modifiers as build_modifiers
    mesh = bpy.data.meshes.new("maxdrop crease test")
    try:
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)], [],
                         [(0, 1, 4, 3), (1, 2, 5, 4)])
        sharp = mesh.attributes.get("sharp_edge") or mesh.attributes.new("sharp_edge", 'BOOLEAN', 'EDGE')
        sharp.data.foreach_set("value", [True] * len(mesh.edges))
        build_modifiers._crease(mesh)
        crease = [d.value for d in mesh.attributes["crease_edge"].data]
        want = [1.0 if tuple(sorted(e.vertices)) == (1, 4) else 0.0 for e in mesh.edges]
        check("crease: the sharp edge between two faces creased, the open ones not", crease == want, str(crease))
    finally:
        bpy.data.meshes.remove(mesh)


def main():
    print("Blender " + bpy.app.version_string)
    sys.path.insert(0, ROOT)
    import maxdrop
    maxdrop.register()
    check("package imported from the repo root",
          os.path.normcase(os.path.dirname(os.path.dirname(maxdrop.__file__))) == os.path.normcase(ROOT))
    from maxdrop.build import collections as build_collections
    from maxdrop.build import objects as build_objects
    from maxdrop.build import report as build_report
    from maxdrop.convert import report as convert_report
    from maxdrop.convert import scene as convert_scene
    modules = (convert_scene, convert_report, build_objects, build_collections, build_report)
    paths = argv or sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
    check("fixtures found", bool(paths))
    for path in paths:
        try:
            run_fixture(path, modules)
        except Exception:
            traceback.print_exc()
            check("%s: no exception" % os.path.basename(path), False)
    if not argv:
        try:
            check_shear(modules)
        except Exception:
            traceback.print_exc()
            check("shear: no exception", False)
        try:
            check_ignore_option(os.path.join(ROOT, "tests", "fixtures", "stack_convert.max"), modules)
        except Exception:
            traceback.print_exc()
            check("modifiers ignored: no exception", False)
        for label, run_check in (("material slots", lambda: check_material_slots(modules)),
                                 ("found textures", check_found_textures), ("builder", check_builder),
                                 ("builder debt", check_builder_debt), ("builder mirror", check_builder_mirror),
                                 ("builder blend", check_builder_blend), ("builder mono", check_builder_mono),
                                 ("builder blend modes", check_builder_blend_modes),
                                 ("builder multiply", check_builder_multiply),
                                 ("builder weight", check_builder_weight),
                                 ("builder fresnel off", check_builder_fresnel_off),
                                 ("builder clip mask", check_builder_clip_mask),
                                 ("curve step", check_curve_step),
                                 ("crease open edges", check_crease_open_edges),
                                 ("linear fallback", check_linear_fallback),
                                 ("image reuse", check_image_reuse), ("double import", check_double_import),
                                 ("worker errors", check_worker_errors),
                                 ("read cancel", lambda: check_read_cancel(
                                     os.path.join(ROOT, "tests", "fixtures", "primitives.max"))),
                                 ("mesh steps", lambda: check_mesh_steps(
                                     [os.path.join(ROOT, "tests", "fixtures", n) for n in ("multi_uv.max",
                                                                                          "primitives.max")],
                                     os.path.join(ROOT, "tests", "fixtures", "primitives.max"))),
                                 ("conversion failure", lambda: check_conversion_failure(
                                     os.path.join(ROOT, "tests", "fixtures", "vray_maps.max"))),
                                 ("light note on failure", lambda: check_light_note_on_failure(
                                     os.path.join(ROOT, "tests", "fixtures", "vray_lights.max"))),
                                 ("dome undo", lambda: check_dome_undo(
                                     os.path.join(ROOT, "tests", "fixtures", "vray_dome.max"))),
                                 ("reader defect", lambda: check_reader_defect(
                                     os.path.join(ROOT, "tests", "fixtures", "primitives.max"),
                                     os.path.join(ROOT, "tests", "fixtures", "multi_uv.max"))),
                                 ("asset table once", lambda: check_asset_table_once(
                                     os.path.join(ROOT, "tests", "fixtures", "vray_lights.max"))),
                                 ("ies header", lambda: check_ies_header(
                                     os.path.join(ROOT, "tests", "fixtures", "lights_photometric.max"))),
                                 ("benchmark", lambda: _bench().run(check))):
            try:
                run_check()
            except Exception:
                traceback.print_exc()
                check("%s: no exception" % label, False)


try:
    main()
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FIXTURES FAILED: %s" % ", ".join(failures) if failures else "FIXTURES PASSED")
sys.stdout.flush()
sys.exit(1 if failures else 0)
