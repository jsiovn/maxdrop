# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The fixture tables of the fixture tests: what each fixture's script makes, as literals (tests/unit/
test_convert_scene.py reads some of them with ast)."""
import math


MATRIX_TOLERANCE = 1e-4
BBOX_TOLERANCE = 1e-3
UV_LAYERS = {  # mapcoords:true in the script gives channel 1; kept literal: test_convert_scene reads it with ast
    "arc_pie_reverse": ["UVMap"],  # every Extrude with Generate Mapping Coords; the two plain arcs are curves
    "box_poly_standard": ["UVMap"],
    "corona_layered": ["UVMap"],
    "corona_classes": ["UVMap"],
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
    "layers_render": [],
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
    "vray_mesh_light": ["UVMap"],  # Planes, also as the emitters' meshes
    "lights_standard": [],
    "lights_photometric": [],
    "cameras": [],  # its box, without Generate Mapping Coords
    "controllers": [],  # boxes without Generate Mapping Coords
    "controllers_tangents": [],  # boxes without Generate Mapping Coords
    "controllers_ranges": [],  # boxes without Generate Mapping Coords
    "vray_wrappers": ["UVMap"],
    "uvwmap": {"FixtureUVWGizmo": ["UVMap", "UVChannel_2"], "FixtureUVWTwo": ["UVMap", "UVChannel_3"]},  # else UVMap
    "uvwmap_oblique": ["UVMap"],
    "uvwmap_pole": ["UVMap"],
    "exposure": [],  # its box, without Generate Mapping Coords
}
# editable_mesh: group 1 on top and bottom, 2 on the sides; a box with a group per side: 12; modifier_pivot's box of
# four height segments: 4 x 4 vertical side edges and both rims
# a converted TurboSmooth or MeshSmooth with Smooth Result leaves no sharp edge
SHARP_EDGES = {"editable_mesh": 8, "modifier_pivot": {"FixtureSmooth": 0, None: 24},
               "stack_basic": {"FixtureTurbo": 0, None: 12},
               "stack_convert": {"FixtureTurboOne": 0, "FixtureMeshSmooth": 0, "FixtureOrder": 0,
                                 "FixtureTurboSymHalf": 0, None: 12},
               # boxes without their top: the 4 vertical and the 4 bottom edges, and the 4 open edges a hardened Shell
               # rim makes sharp; the plane's open edges; a TurboSmooth below the Shell clears the groups, not the
               # open edges; one above it smooths the rim too
               "stack_shell": {"FixtureShellPlane": 4, "FixtureShellTurbo": 4, "FixtureShellSmoothed": 0, None: 12,
                               # half and quarter boxes below a Symmetry: the edges between their sides and the
                               # top's open edges, not the cut's (on the mirror plane: the weld shuts them)
                               "FixtureShellSymHalf": 10, "FixtureShellSymClosed": 10, "FixtureShellSymQuarter": 5,
                               # below a Symmetry whose plane holds their cut: the Mirror moved below the Shell welds
                               # it; a TurboSmooth with Smooth Result above clears them; weld off: the cut's sharp too
                               "FixtureShellUnderSym": 10, "FixtureShellUnderSymTurbo": 0,
                               "FixtureShellBetweenSym": 5, "FixtureShellUnderSymNoWeld": 14},
               "vray_mesh_light": 0,  # Planes: open edges only
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
                 "FixtureShellPlane": 1.0,  # stack_shell's base plane (its Shell is a Solidify)
                 "FixtureEmitterSource": 1.0}  # vray_mesh_light's source
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
BARE_MESHES = {"FixtureMeshSource", "FixtureEmitterSource"}  # meshes a fixture leaves without a material: the
# mesh lights' sources (vray_dome, vray_mesh_light)
# mesh lights (tools/fixtures/vray_mesh_light.ms, vray_dome.ms): the radiance in W/m2/sr by hand (docs/FORMAT.md,
# "VRayLight": default units m 1500 / (683 pi); W m / (pi a), a double-sided one over 2 a; lm m / (683 pi a); a the
# object-space mesh area), the world box of the emitter's mesh in file units from the scripts (the source's mesh at
# the light's place: its position, turn, scale and object offset), double-sided, flip, camera, shadow, diffuse, glossy.
# The box is the mesh's below the modifiers on the emitter (EMITTER_SOLIDIFY: FixtureEmitterOwn's Shell, in file units)
EMITTER_SOLIDIFY = {"FixtureEmitterOwn": 2.0}
EMITTER_SHELLED = 760.0  # FixtureEmitterOwn's evaluated area in file units squared (EMITTER_RADIANCE)
EMITTER_RADIANCE = {"FixtureEmitter": 2.0 * 1500.0 / (683.0 * math.pi),
                    "FixtureEmitterW": 5.0 / (2.0 * math.pi * 0.0008),
                    "FixtureEmitterOwn": 100.0 / 683.0 / (math.pi * 0.00076),  # the 30 x 10 plane under a 2 mm
                    # Shell: both surfaces and the rim, 2 x 300 + 80 x 2 mm^2
                    "FixtureMeshLight": 10.0 / (math.pi * 0.0016)}
EMITTER_BOXES = {"FixtureEmitter": ((-20.0, -10.0, 50.0), (20.0, 10.0, 50.0)),
                 "FixtureEmitterW": ((60.0, -10.0, 50.0), (140.0, 10.0, 50.0)),
                 "FixtureEmitterOwn": ((-80.0 - 15.0 * math.cos(math.radians(30.0)) - 2.5,
                                        -7.5 - 5.0 * math.cos(math.radians(30.0)), 40.0),
                                       (-80.0 + 15.0 * math.cos(math.radians(30.0)) + 2.5,
                                        7.5 + 5.0 * math.cos(math.radians(30.0)), 40.0)),
                 "FixtureMeshLight": ((-10.0, -70.0, 50.0), (10.0, -50.0, 60.0))}
EMITTER_FLAGS = {"FixtureEmitter": (False, False, True, True, True, True),
                 "FixtureEmitterW": (True, True, False, False, True, True),
                 "FixtureEmitterOwn": (False, False, True, True, True, False),
                 "FixtureMeshLight": (False, False, True, True, True, True)}

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
# the oracle's base_class_id of the primitives MaxDrop builds (convert/primitives/)
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
                     "FixtureArcRevExt": ["UVMap"], "FixtureClockwiseExt": ["UVMap"], "FixtureHoleExt": ["UVMap"],
                     "FixtureShellUnderSymExtrude": ["UVMap"],
                     "FixtureExtDownStart": ["UVMap"], "FixtureExtDownEndReal": ["UVMap"]}
EXTRUDE_SHARP_EDGES = {"FixtureExtRect": 16, "FixtureExtL": 18, "FixtureExtHole": 68, "FixtureExtIsland": 36,
                       "FixtureExtOpen": 0, "FixtureExtMirror": 72, "FixtureExtAdaptive": 256,
                       "FixtureExtShapeIDs": 41, "FixtureExtShapeIDsRect": 12, "FixtureUVWExtrude": 12,
                       "FixtureExtGrid": 36, "FixtureExtGridCircle": 16,
                       "FixturePieRevExt": 52, "FixturePieRevWrapExt": 52, "FixturePieExt": 52,
                       "FixtureArcRevExt": 0, "FixtureClockwiseExt": 16, "FixtureHoleExt": 72,
                       # stack_shell: an open Line's two corner columns and the rim the Shell above hardens (top and
                       # bottom, not the ends on the Symmetry's plane, which its Mirror welds below the Shell)
                       "FixtureShellUnderSymExtrude": 8,
                       "FixtureExtDownStart": 16, "FixtureExtDownEndReal": 12}
EXTRUDE_EULER = {"FixtureExtRect": 2, "FixtureExtL": 2, "FixtureExtHole": 0, "FixtureExtIsland": 2,
                 "FixtureExtOpen": None, "FixtureExtMirror": 2, "FixtureExtAdaptive": 2, "FixtureExtShapeIDs": 0,
                 "FixtureExtShapeIDsRect": 2, "FixtureUVWExtrude": 2, "FixturePieRevExt": 2,
                 "FixtureExtGrid": 0, "FixtureExtGridCircle": None,  # grid caps: a holed solid; one cap
                 "FixturePieRevWrapExt": 2, "FixturePieExt": 2, "FixtureArcRevExt": None, "FixtureClockwiseExt": 2,
                 "FixtureHoleExt": 0, "FixtureShellUnderSymExtrude": None,
                 "FixtureExtDownStart": None, "FixtureExtDownEndReal": None}  # one cap each
VALUE_TOLERANCE = 1e-4
SPECULAR_LEVEL = 0.5  # the IR's specular is a reflection weight: 1 is Blender's Specular IOR Level 0.5
TWIN_LABEL, WEIGHT_LABEL = "Without reflection", "Reflection weight"  # a weight between 0 and 1 (maxdrop-em3.119)
MIRROR_LABEL = "Mirror reflection"  # the metal (white, or tinted) of a weight without Fresnel (maxdrop-em3.120)
MIRROR_INPUTS = {"Metallic": 1.0, "Base Color": (1.0, 1.0, 1.0, 1.0), "Specular IOR Level": SPECULAR_LEVEL}
REFRACTION_LABEL = "Refraction without reflection"  # refracting glass's twin (maxdrop-em3.135)
TIR_LABEL = "Total internal reflection"  # the weight's mask where glass reflects totally (maxdrop-em3.135)
DEG = math.pi / 180.0
