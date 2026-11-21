# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The 3ds Max classes the project knows, by constant name: superclass ids (SC_*, ints) and ClassIds.

A ClassId is unique only within its superclass (Standard material and RootNode are both (2, 0)), so dispatch
compares both: `entry.superclass == SC_MATERIAL and entry.class_id == STANDARD_MTL`. CLASSES maps each known
pair to the class name 3ds Max writes; tests/unit/test_classdir.py checks every entry against the class directory
of a committed fixture, so add a class here only together with a fixture that has it. No bpy.
"""
from .classdir import ClassId

# Superclass ids (SClass_ID of the 3ds Max SDK).
SC_BASENODE = 0x0001
SC_PARAMETER_BLOCK = 0x0008
SC_GEOMOBJECT = 0x0010
SC_CAMERA = 0x0020
SC_LIGHT = 0x0030
SC_SHAPE = 0x0040
SC_HELPER = 0x0050
SC_PARAMETER_BLOCK2 = 0x0082
SC_OSMODIFIER = 0x0810
SC_WSMODIFIER = 0x0820
SC_REF_MAKER = 0x0100
SC_REF_TARGET = 0x0200
SC_MATERIAL = 0x0C00
SC_TEXMAP = 0x0C10
SC_UVGEN = 0x0C20
SC_XYZGEN = 0x0C30
SC_TEXOUTPUT = 0x0C40
SC_TEXMAP_CONTAINER = 0x1080
SC_LAYER = 0x10F0
SC_RENDER_ENVIRONMENT = 0x1010  # RenderEnvironment's superclass in every class directory
SC_SHADER = 0x10B0
SC_SAMPLER = 0x1110
SC_CTRL_FLOAT = 0x9003
SC_CTRL_POINT3 = 0x9005
SC_CTRL_MATRIX3 = 0x9008
SC_CTRL_POSITION = 0x900B
SC_CTRL_ROTATION = 0x900C
SC_CTRL_SCALE = 0x900D
SC_CTRL_MASTERPOINT = 0x9010

# Scene structure.
NODE = ClassId(0x00000001, 0)
ROOT_NODE = ClassId(0x00000002, 0)
SCENE = ClassId(0x00002222, 0)
RENDER_ENVIRONMENT = ClassId(0xEE448B23, 0)
BASE_LAYER = ClassId(0x7E9858FE, 0x1DBA1DF0)
LAYER_MANAGER = ClassId(0x0D7374FC, 0x51FF028E)
PARAM_BLOCK = ClassId(0x00000008, 0)
PARAM_BLOCK2 = ClassId(0x00000082, 0)

# Geometry and helpers.
EDITABLE_MESH = ClassId(0xE44F10B3, 0)
EDITABLE_POLY = ClassId(0x1BF8338D, 0x192F6098)
DUMMY = ClassId(0x00876234, 0)
TARGET_OBJECT = ClassId(0x00001020, 0)  # the node a Look At controller aims at (a target camera's, light's)

# Lights (convert/lights.py).
VRAY_LIGHT = ClassId(0x3C5575A1, 0x5FD602DF)
VRAY_SUN = ClassId(0x732C0383, 0x7D993776)
VRAY_IES = ClassId(0x2EAF2F07, 0x7EC44F31)
VRAY_SKY = ClassId(0x48480B4E, 0x62FF5A90)  # a map (superclass Texmap), the environment's
SKYLIGHT = ClassId(0x7BF61478, 0x522E4705)
# Standard lights: their parameters in an old ParamBlock
OMNI = ClassId(0x00001011, 0)
TARGET_SPOT = ClassId(0x00001012, 0)
FREE_DIRECT = ClassId(0x00001013, 0)
FREE_SPOT = ClassId(0x00001014, 0)
TARGET_DIRECT = ClassId(0x00001015, 0)
# Photometric lights: one class per shape, the same ParamBlock2s
FREE_POINT_LIGHT = ClassId(0x32375FCC, 0x0B025CF0)  # "Free Light"
FREE_LINE_LIGHT = ClassId(0x78207401, 0x357F1D58)
FREE_RECTANGLE_LIGHT = ClassId(0x36507D92, 0x105A1A47)
FREE_DISC_LIGHT = ClassId(0x5BCC6D42, 0x0C4F430E)
FREE_SPHERE_LIGHT = ClassId(0x7CA93582, 0x1ABB6B32)
FREE_CYLINDER_LIGHT = ClassId(0x46F634E3, 0x0A327AAF)
TARGET_POINT_LIGHT = ClassId(0x658D4F97, 0x72CD4259)  # "Target Light"
TARGET_LINE_LIGHT = ClassId(0x45076885, 0x40791449)
TARGET_RECTANGLE_LIGHT = ClassId(0x71794F9D, 0x70AE52F2)
TARGET_DISC_LIGHT = ClassId(0x38732348, 0x201758B3)
TARGET_SPHERE_LIGHT = ClassId(0x33FC7AE9, 0x54433DC5)
TARGET_CYLINDER_LIGHT = ClassId(0x7C8B5B10, 0x4BD33E86)

# Cameras (convert/cameras.py).
FREE_CAMERA = ClassId(0x00001001, 0)
TARGET_CAMERA = ClassId(0x00001002, 0)  # its class directory names it "Target", as it does the Target object
PHYSICAL_CAMERA = ClassId(0x46697218, 0x28E8008D)
VRAY_PHYSICAL_CAMERA = ClassId(0x405E3FEE, 0x4F6513BE)

# Primitives (convert/primitives.py).
BOX = ClassId(0x00000010, 0)
SPHERE = ClassId(0x00000011, 0)
CYLINDER = ClassId(0x00000012, 0)
TORUS = ClassId(0x00000020, 0)
CONE = ClassId(0xA86C23DD, 0)
TUBE = ClassId(0x00007B21, 0)
GEOSPHERE = ClassId(0x00000000, 0x00007F9E)
PLANE = ClassId(0x081F1DFC, 0x77566F65)
PYRAMID = ClassId(0x76BF318A, 0x4BF37B10)

# Shapes.
SPLINE_SHAPE = ClassId(0x0000000A, 0)  # an Editable Spline
LINE = ClassId(0x00001040, 0)
RECTANGLE = ClassId(0x00001065, 0)
CIRCLE = ClassId(0x00001999, 0)
ELLIPSE = ClassId(0x00001097, 0)
ARC = ClassId(0x00001996, 0)
NGON = ClassId(0x00001050, 0)

# Modifiers.
EXTRUDE = ClassId(0x000000A0, 0)
UVW_MAP = ClassId(0x000F72B1, 0)
TURBOSMOOTH = ClassId(0x0D727B3E, 0x491D29A7)
MESHSMOOTH = ClassId(0x00000032, 0x00007F9E)
SHELL = ClassId(0x3B9B1A16, 0x6D84E8D0)
SYMMETRY = ClassId(0x2D7E702B, 0x0BE41A6E)

# Materials, maps and their parts.
STANDARD_MTL = ClassId(0x00000002, 0)
MULTI_SUB_MTL = ClassId(0x00000200, 0)
SHELL_MTL = ClassId(0x00000255, 0)
PHYSICAL_MTL = ClassId(0x3D6B1CEC, 0xDEADC001)
VRAY_MTL = ClassId(0x37BF3F2F, 0x7034695C)
VRAY_2SIDED_MTL = ClassId(0x6066686A, 0x11731B4B)
VRAY_BLEND_MTL = ClassId(0x3DA0041B, 0x0F436E31)
VRAY_LIGHT_MTL = ClassId(0x7CCF263E, 0x3F5B39B9)
VRAY_FAST_SSS2 = ClassId(0x3F2C5FAA, 0x750008BC)
VRAY_CAR_PAINT_MTL = ClassId(0x38312C74, 0x47280883)
VRAY_CAR_PAINT_MTL2 = ClassId(0x56BC47E2, 0x03E008C7)
VRAY_OVERRIDE_MTL = ClassId(0x15D20E6B, 0x54E217EB)
VRAY_MTL_WRAPPER = ClassId(0x409517DF, 0x3A5F44B6)
DOUBLE_SIDED_MTL = ClassId(0x00000210, 0)  # MAXScript's DoubleSided
SHELLAC_MTL = ClassId(0x46EE536A, 0)
BITMAP_TEX = ClassId(0x00000240, 0)
VRAY_NORMAL_MAP = ClassId(0x71FA6E51, 0x72057C2F)
VRAY_BITMAP = ClassId(0x6769144B, 0x02C1017D)  # MAXScript's VRayHDRI (before V-Ray 5) is the same class
VRAY_COLOR = ClassId(0x58F82B74, 0x73B75D7F)
VRAY_DIRT = ClassId(0x2F567899, 0x090D5EA4)
VRAY_COLOR2BUMP = ClassId(0x31E15D1D, 0x7D7E2810)
RGB_TINT = ClassId(0x00000224, 0)
MIX = ClassId(0x00000230, 0)
NOISE = ClassId(0x00000234, 0)
COMPOSITE = ClassId(0x00000280, 0)
RGB_MULTIPLY = ClassId(0x00000290, 0)
OUTPUT_MAP = ClassId(0x000002B0, 0)  # the Output map (superclass Texmap), not a map's TexOutput part
COLOR_CORRECTION = ClassId(0x000002D0, 0)
FALLOFF = ClassId(0x6EC3730C, 0)
NORMAL_BUMP = ClassId(0x243E22C6, 0x63F6A014)
CORONA_PHYSICAL_MTL = ClassId(0x6912AB89, 0x87151720)
CORONA_LEGACY_MTL = ClassId(0x70BE6506, 0x448931DD)  # MAXScript's CoronaMtl is the same class
CORONA_LAYERED_MTL = ClassId(0x65486584, 0x8425554E)
CORONA_LIGHT_MTL = ClassId(0x53B7717A, 0x500D5093)
CORONA_SKIN_MTL = ClassId(0xBEC41C73, 0x44CFDE95)
CORONA_HAIR_MTL = ClassId(0x22C05DD6, 0xCA41F546)
CORONA_RAY_SWITCH_MTL = ClassId(0x6816116A, 0xABE651DE)
CORONA_SELECT_MTL = ClassId(0xC74E9F94, 0xC319F213)
CORONA_BITMAP = ClassId(0xABBA5784, 0x65484244)
CORONA_NORMAL = ClassId(0x2870CEAA, 0xCC18437C)
CORONA_COLOR = ClassId(0x68426DCA, 0x372362D4)
CORONA_MIX = ClassId(0x6847286F, 0x3FFFAAB4)
STD_UVGEN = ClassId(0x00000100, 0)  # superclass UVGen ("Placement")
STD_TEXOUTPUT = ClassId(0x00000100, 0)  # superclass TexOutput ("Output"): the same ClassId as STD_UVGEN
PHONG_SHADER = ClassId(0x00000037, 0)
BLINN_SHADER = ClassId(0x00000038, 0)
METAL_SHADER = ClassId(0x00000039, 0)
ANISOTROPIC_SHADER = ClassId(0x2857F460, 0)
OREN_NAYAR_BLINN_SHADER = ClassId(0x2857F421, 0)
MULTI_LAYER_SHADER = ClassId(0x2857F470, 0)
TRANSLUCENT_SHADER = ClassId(0x2857F480, 0)
STRAUSS_SHADER = ClassId(0x2857F450, 0)
STAR_SAMPLER = ClassId(0x25773211, 0)

# Controllers.
PRS = ClassId(0x00002005, 0)
LINEAR_FLOAT = ClassId(0x00002001, 0)
LINEAR_POSITION = ClassId(0x00002002, 0)
LINEAR_ROTATION = ClassId(0x00002003, 0)
LINEAR_SCALE = ClassId(0x00002004, 0)
BEZIER_FLOAT = ClassId(0x00002007, 0)
BEZIER_POSITION = ClassId(0x00002008, 0)
BEZIER_ROTATION = ClassId(0x00002009, 0)  # "Smooth Rotation" in the class directory (MAXScript: Bezier_Rotation)
BEZIER_SCALE = ClassId(0x00002010, 0)
EULER_XYZ = ClassId(0x00002012, 0)
TCB_FLOAT = ClassId(0x00442311, 0)
TCB_POSITION = ClassId(0x00442312, 0)
TCB_ROTATION = ClassId(0x00442313, 0)
TCB_SCALE = ClassId(0x00442315, 0)
POSITION_XYZ = ClassId(0x118F7E02, 0xFFEE238A)
SCALE_XYZ = ClassId(0x118F7C01, 0xFEEE238B)
FLOAT_LIST = ClassId(0x4B4B1000, 0)
POSITION_LIST = ClassId(0x4B4B1002, 0)
ROTATION_LIST = ClassId(0x4B4B1003, 0)
SCALE_LIST = ClassId(0x4B4B1004, 0)
MASTER_POINT = ClassId(0x0D9C20FF, 0)
LOOK_AT = ClassId(0x00002006, 0)  # a Matrix3 controller: target cameras and lights
LOOKAT_CONSTRAINT = ClassId(0x00002021, 0)  # a rotation controller

CLASSES = {
    (SC_BASENODE, NODE): "Node",
    (SC_BASENODE, ROOT_NODE): "RootNode",
    (SC_REF_MAKER, SCENE): "Scene",
    (SC_RENDER_ENVIRONMENT, RENDER_ENVIRONMENT): "RenderEnvironment",
    (SC_LAYER, BASE_LAYER): "Base Layer",
    (SC_REF_TARGET, LAYER_MANAGER): "Layer Manager",
    (SC_PARAMETER_BLOCK, PARAM_BLOCK): "ParamBlock",
    (SC_PARAMETER_BLOCK2, PARAM_BLOCK2): "ParamBlock2",
    (SC_GEOMOBJECT, EDITABLE_MESH): "Editable Mesh",
    (SC_GEOMOBJECT, EDITABLE_POLY): "Editable Poly",
    (SC_HELPER, DUMMY): "Dummy",
    (SC_GEOMOBJECT, TARGET_OBJECT): "Target",
    (SC_GEOMOBJECT, BOX): "Box",
    (SC_GEOMOBJECT, SPHERE): "Sphere",
    (SC_GEOMOBJECT, CYLINDER): "Cylinder",
    (SC_GEOMOBJECT, TORUS): "Torus",
    (SC_GEOMOBJECT, CONE): "Cone",
    (SC_GEOMOBJECT, TUBE): "Tube",
    (SC_GEOMOBJECT, GEOSPHERE): "GeoSphere",
    (SC_GEOMOBJECT, PLANE): "Plane",
    (SC_GEOMOBJECT, PYRAMID): "Pyramid",
    (SC_LIGHT, VRAY_LIGHT): "VRayLight",
    (SC_LIGHT, VRAY_SUN): "VRaySun",
    (SC_LIGHT, VRAY_IES): "VRayIES",
    (SC_TEXMAP, VRAY_SKY): "VRaySky",
    (SC_LIGHT, SKYLIGHT): "Skylight",
    (SC_LIGHT, OMNI): "Omni",
    (SC_LIGHT, TARGET_SPOT): "Target Spot",
    (SC_LIGHT, FREE_DIRECT): "Free Direct",
    (SC_LIGHT, FREE_SPOT): "Free Spot",
    (SC_LIGHT, TARGET_DIRECT): "Target Direct",
    (SC_LIGHT, FREE_POINT_LIGHT): "Free Light",
    (SC_LIGHT, FREE_LINE_LIGHT): "Free Line",
    (SC_LIGHT, FREE_RECTANGLE_LIGHT): "Free Rectangle",
    (SC_LIGHT, FREE_DISC_LIGHT): "Free Disc",
    (SC_LIGHT, FREE_SPHERE_LIGHT): "Free Sphere",
    (SC_LIGHT, FREE_CYLINDER_LIGHT): "Free Cylinder",
    (SC_LIGHT, TARGET_POINT_LIGHT): "Target Light",
    (SC_LIGHT, TARGET_LINE_LIGHT): "Target Line",
    (SC_LIGHT, TARGET_RECTANGLE_LIGHT): "Target Rectangle",
    (SC_LIGHT, TARGET_DISC_LIGHT): "Target Disc",
    (SC_LIGHT, TARGET_SPHERE_LIGHT): "Target Sphere",
    (SC_LIGHT, TARGET_CYLINDER_LIGHT): "Target Cylinder",
    (SC_CAMERA, FREE_CAMERA): "Free",
    (SC_CAMERA, TARGET_CAMERA): "Target",
    (SC_CAMERA, PHYSICAL_CAMERA): "Physical",
    (SC_CAMERA, VRAY_PHYSICAL_CAMERA): "VRayPhysicalCamera",
    (SC_SHAPE, SPLINE_SHAPE): "SplineShape",
    (SC_SHAPE, LINE): "Line",
    (SC_SHAPE, RECTANGLE): "Rectangle",
    (SC_SHAPE, CIRCLE): "Circle",
    (SC_SHAPE, ELLIPSE): "Ellipse",
    (SC_SHAPE, ARC): "Arc",
    (SC_SHAPE, NGON): "NGon",
    (SC_OSMODIFIER, EXTRUDE): "Extrude",
    (SC_OSMODIFIER, UVW_MAP): "UVW Map",
    (SC_OSMODIFIER, TURBOSMOOTH): "TurboSmooth",
    (SC_OSMODIFIER, MESHSMOOTH): "MeshSmooth",
    (SC_OSMODIFIER, SHELL): "Shell",
    (SC_OSMODIFIER, SYMMETRY): "Symmetry",
    (SC_MATERIAL, STANDARD_MTL): "Standard",
    (SC_MATERIAL, MULTI_SUB_MTL): "Multi/Sub-Object",
    (SC_MATERIAL, SHELL_MTL): "Shell Material",
    (SC_MATERIAL, PHYSICAL_MTL): "Physical Material",
    (SC_MATERIAL, VRAY_MTL): "VRayMtl",
    (SC_MATERIAL, VRAY_2SIDED_MTL): "VRay2SidedMtl",
    (SC_MATERIAL, VRAY_BLEND_MTL): "VRayBlendMtl",
    (SC_MATERIAL, VRAY_LIGHT_MTL): "VRayLightMtl",
    (SC_MATERIAL, VRAY_FAST_SSS2): "VRayFastSSS2",
    (SC_MATERIAL, VRAY_CAR_PAINT_MTL): "VRayCarPaintMtl",
    (SC_MATERIAL, VRAY_CAR_PAINT_MTL2): "VRayCarPaintMtl2",
    (SC_MATERIAL, VRAY_OVERRIDE_MTL): "VRayOverrideMtl",
    (SC_MATERIAL, VRAY_MTL_WRAPPER): "VRayMtlWrapper",
    (SC_MATERIAL, DOUBLE_SIDED_MTL): "Double Sided",
    (SC_MATERIAL, SHELLAC_MTL): "Shellac",
    (SC_TEXMAP, BITMAP_TEX): "Bitmap",
    (SC_TEXMAP, VRAY_NORMAL_MAP): "VRayNormalMap",
    (SC_TEXMAP, VRAY_BITMAP): "VRayBitmap",
    (SC_TEXMAP, VRAY_COLOR): "VRayColor",
    (SC_TEXMAP, VRAY_DIRT): "VRayDirt",
    (SC_TEXMAP, VRAY_COLOR2BUMP): "VRayColor2Bump",
    (SC_TEXMAP, RGB_TINT): "RGB Tint",
    (SC_TEXMAP, MIX): "Mix",
    (SC_TEXMAP, NOISE): "Noise",
    (SC_TEXMAP, COMPOSITE): "Composite",
    (SC_TEXMAP, RGB_MULTIPLY): "RGB Multiply",
    (SC_TEXMAP, OUTPUT_MAP): "Output",
    (SC_TEXMAP, COLOR_CORRECTION): "Color Correction",
    (SC_TEXMAP, FALLOFF): "Falloff",
    (SC_TEXMAP, NORMAL_BUMP): "Normal Bump",
    (SC_MATERIAL, CORONA_PHYSICAL_MTL): "\rCoronaPhysicalMtl",  # the leading CR is in the class directory
    (SC_MATERIAL, CORONA_LEGACY_MTL): "CoronaLegacyMtl",
    (SC_MATERIAL, CORONA_LAYERED_MTL): "CoronaLayeredMtl",
    (SC_MATERIAL, CORONA_LIGHT_MTL): "CoronaLightMtl",
    (SC_MATERIAL, CORONA_SKIN_MTL): "CoronaSkinMtl",
    (SC_MATERIAL, CORONA_HAIR_MTL): "CoronaHairMtl",
    (SC_MATERIAL, CORONA_RAY_SWITCH_MTL): "CoronaRaySwitchMtl",
    (SC_MATERIAL, CORONA_SELECT_MTL): "CoronaSelectMtl",
    (SC_TEXMAP, CORONA_BITMAP): "CoronaBitmap",
    (SC_TEXMAP, CORONA_NORMAL): "CoronaNormal",
    (SC_TEXMAP, CORONA_COLOR): "CoronaColor",
    (SC_TEXMAP, CORONA_MIX): "CoronaMix",
    (SC_UVGEN, STD_UVGEN): "Placement",
    (SC_TEXOUTPUT, STD_TEXOUTPUT): "Output",
    (SC_SHADER, PHONG_SHADER): "Phong",
    (SC_SHADER, BLINN_SHADER): "Blinn",
    (SC_SHADER, METAL_SHADER): "Metal",
    (SC_SHADER, ANISOTROPIC_SHADER): "Anisotropic",
    (SC_SHADER, OREN_NAYAR_BLINN_SHADER): "Oren-Nayar-Blinn",
    (SC_SHADER, MULTI_LAYER_SHADER): "Multi-Layer",
    (SC_SHADER, TRANSLUCENT_SHADER): "Translucent Shader",
    (SC_SHADER, STRAUSS_SHADER): "Strauss",
    (SC_SAMPLER, STAR_SAMPLER): "Max 2.5 Star",
    (SC_CTRL_MATRIX3, PRS): "Position/Rotation/Scale",
    (SC_CTRL_FLOAT, LINEAR_FLOAT): "Linear Float",
    (SC_CTRL_POSITION, LINEAR_POSITION): "Linear Position",
    (SC_CTRL_ROTATION, LINEAR_ROTATION): "Linear Rotation",
    (SC_CTRL_SCALE, LINEAR_SCALE): "Linear Scale",
    (SC_CTRL_FLOAT, BEZIER_FLOAT): "Bezier Float",
    (SC_CTRL_POSITION, BEZIER_POSITION): "Bezier Position",
    (SC_CTRL_ROTATION, BEZIER_ROTATION): "Smooth Rotation",
    (SC_CTRL_SCALE, BEZIER_SCALE): "Bezier Scale",
    (SC_CTRL_ROTATION, EULER_XYZ): "Euler XYZ",
    (SC_CTRL_FLOAT, TCB_FLOAT): "TCB Float",
    (SC_CTRL_POSITION, TCB_POSITION): "TCB Position",
    (SC_CTRL_ROTATION, TCB_ROTATION): "TCB Rotation",
    (SC_CTRL_SCALE, TCB_SCALE): "TCB Scale",
    (SC_CTRL_POSITION, POSITION_XYZ): "Position XYZ",
    (SC_CTRL_SCALE, SCALE_XYZ): "ScaleXYZ",
    (SC_CTRL_FLOAT, FLOAT_LIST): "Float List",
    (SC_CTRL_POSITION, POSITION_LIST): "Position List",
    (SC_CTRL_ROTATION, ROTATION_LIST): "Rotation List",
    (SC_CTRL_SCALE, SCALE_LIST): "Scale List",
    (SC_CTRL_MASTERPOINT, MASTER_POINT): "Master Point Controller",
    (SC_CTRL_MATRIX3, LOOK_AT): "Look At",
    (SC_CTRL_ROTATION, LOOKAT_CONSTRAINT): "LookAt Constraint",
}


def name_of(superclass, class_id):
    """The class name of a known (superclass, ClassId) pair, else None."""
    return CLASSES.get((superclass, ClassId(*class_id)))
