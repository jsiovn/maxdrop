# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Kinds, color spaces, ClassIDs, parameter ids and the tables of the texture-map rules."""
import collections

from ...reader import chunks, classids
from ...reader import materials as reader_materials


ChunkError = chunks.ChunkError

COLOR, DATA, MASK, NORMAL, BUMP = "color", "data", "mask", "normal", "bump"
FLOATS = (DATA, MASK)  # the kinds a map gives one number to: its mono output
# The input of a wrapper that works on color (RGB Tint, an Output part, Color Correction) in a data or bump graph:
# a swatch keeps its channels as stored, images and masks below are as in DATA / BUMP (rgb_kind, base_kind).
DATA_RGB, BUMP_RGB = "data rgb", "bump rgb"
_RGB_KINDS = {DATA: DATA_RGB, BUMP: BUMP_RGB}
_BASE_KINDS = {v: k for k, v in _RGB_KINDS.items()}
# A map V-Ray or Corona computes on stored values in a gamma-off scene (DISPLAY_MIXES) at a color root, and every map
# below it: a color as the renderer holds it there (swatches as stored, images by their own decode, a Bitmap as stored,
# CoronaColor's HDR color as stored), which the display-referred scene shows decoded (the Decode above it).
STORED = "stored"
STORED_RGB = (DATA_RGB, BUMP_RGB, NORMAL, STORED)  # the kinds whose swatch is its three channels as stored
_AS_STORED = (DATA, NORMAL, BUMP, STORED)  # the kinds that take an image read as stored as it is (colorspace)
SRGB, NON_COLOR, LINEAR = "sRGB", "Non-Color", "Linear Rec.709"  # Blender color space names
EXPLICIT, OBJECT_XYZ, VERTEX_COLOR, WORLD_XYZ = (  # Placement coordinate source
    reader_materials.UV_EXPLICIT, reader_materials.UV_OBJECT_XYZ, reader_materials.UV_VERTEX_COLOR,
    reader_materials.UV_WORLD_XYZ)
MAX_DEPTH = 8
MAX_NODES = 256  # nodes of one graph drawn as a tree
SRGB_GAMMA, GAMMA_TOLERANCE = 2.2, 0.05
# With the gamma off a map whose own decode is the sRGB curve shows decoded once more (_shown): the sRGB curve
# applied twice is within 0.008 of x ^ 5 over 0..1 (2.2 x 2.2 = 4.84 within 0.019; maxdrop-em3.123).
SRGB_TWICE = 5.0

# ClassIDs (texmap superclass), aliased from reader/classids.py.
FALLOFF = classids.FALLOFF
VRAY_DIRT = classids.VRAY_DIRT
VRAY_COLOR2BUMP = classids.VRAY_COLOR2BUMP
OUTPUT = classids.OUTPUT_MAP
RGB_TINT = classids.RGB_TINT
MIX = classids.MIX
RGB_MULTIPLY = classids.RGB_MULTIPLY
COLOR_CORRECTION = classids.COLOR_CORRECTION
COMPOSITE = classids.COMPOSITE
CHECKER = classids.CHECKER
NORMAL_BUMP = classids.NORMAL_BUMP
CORONA_NORMAL = classids.CORONA_NORMAL
IMAGES = (classids.BITMAP_TEX, classids.CORONA_BITMAP, classids.VRAY_BITMAP)  # map classes that are an image file

# normal map class -> parameter ids in block 0: normal map, its switch, multiplier, bump map, its switch, multiplier,
# flip red, flip green, swap red and green, the tangents' map channel (None: the class has no such parameter)
_NormalIds = collections.namedtuple("_NormalIds", "normal normal_on strength bump bump_on bump_strength flip_red "
                                                  "flip_green swap channel")
NORMAL_MAPS = {
    classids.VRAY_NORMAL_MAP: _NormalIds(0, 2, 3, 4, 5, 6, 7, 8, 9, 1),
    NORMAL_BUMP: _NormalIds(2, 4, 0, 3, 5, 1, 7, 8, 9, None),
    CORONA_NORMAL: _NormalIds(500, None, 501, 507, 509, 508, 503, 504, 505, None),
}
NORMAL_BUMP_METHOD, CORONA_ADD_GAMMA = 6, 502

# CoronaBitmap, block 0: tiling 0 none, 1 repeat, 2 mirror; wAngle in radians. uAngle (130) is the U offset times
# 2 pi (Corona keeps the two in step, for an environment map's turn): not read
CB_FILE, CB_CHANNEL, CB_SCALE, CB_OFFSET, CB_BLUR, CB_TILE_U, CB_TILE_V, CB_REAL_WORLD = (
    101, 103, 105, 106, 107, 108, 109, 114)
CB_MONO, CB_RGB, CB_CLIP_ON, CB_CLIP_MODE, CB_CLIP_U, CB_CLIP_V, CB_CLIP_W, CB_CLIP_H = (
    117, 118, 119, 120, 121, 122, 123, 124)
CB_GAMMA, CB_W_ANGLE = 125, 129
CB_NO_TILE, CB_MIRROR = 0, 2
# VRayBitmap (VRayHDRI), block 0 (rgbColorSpace: block 3); its Placement is a standard UVGen, read as a Bitmap's.
# mapType 4 is 3ds Max standard mapping (the UVGen), 0 to 3 environment projections; its own mapChannel (7) only
# serves those: the UVGen's channel is the one used
VB_FILE, VB_MULT, VB_MAP_TYPE, VB_GAMMA, VB_RENDER_MULT = 0, 1, 2, 8, 9
VB_CROP_ON, VB_CROP_MODE, VB_CROP_U, VB_CROP_V, VB_CROP_W, VB_CROP_H = 16, 17, 18, 19, 20, 21
VB_RGB, VB_MONO, VB_COLOR_SPACE, VB_SOURCE, VB_SOURCE_ON, VB_RGB_SPACE, VB_RGB_SPACE_BLOCK = (
    22, 23, 25, 38, 39, 41, 3)
VB_STANDARD, VB_INTENSITY, VB_ACESCG = 4, 2, 2
# color_space (transfer function), measured with renderMap: 0 none (linear), 1 inverse gamma (pixel ^ (1 / gamma)),
# 2 sRGB, 3 from 3ds Max (the input gamma, as a Bitmap's automatic), 4 auto (sRGB for an 8-bit file, the default)
VB_LINEAR, VB_INVERSE_GAMMA, VB_SRGB, VB_FROM_MAX, VB_AUTOMATIC = 0, 1, 2, 3, (2, 3, 4)
FLOAT_IMAGES = (".exr", ".hdr")  # files an automatic gamma (Bitmap, CoronaBitmap, VRayBitmap auto) reads as linear
MAX_MULTIPLIER = 1e6
# image class -> (class name in issues, its file parameter in block 0); any other image class is a Bitmap
_IMAGE_FILES = {classids.CORONA_BITMAP: ("CoronaBitmap", CB_FILE), classids.VRAY_BITMAP: ("VRayBitmap", VB_FILE)}
# CoronaColor, block 0: method 0 color, 1 HDR color (linear), 2 temperature, 3 hex
CC_METHOD, CC_TEMPERATURE, CC_COLOR, CC_MULTIPLIER, CC_HDR, CC_HEX = 50, 51, 52, 57, 58, 59
# VRayColor, block 0: color_mode 0 RGB, 1 temperature (V-Ray writes the temperature's color into color, measured);
# red / green / blue are color again; rgb_primaries 0 sRGB. Block 1 (gamma_correction, gamma_value) is transient
VC_RED, VC_GREEN, VC_BLUE, VC_ALPHA, VC_MULTIPLIER, VC_COLOR, VC_MODE, VC_GAMMA, VC_PRIMARIES = (
    0, 1, 2, 3, 4, 5, 9, 10, 11)
# CoronaMix, block 0: result = mix(bottom, operation(bottom, top), amount), the mask map replacing the amount
CM_OPERATION, CM_AMOUNT, CM_MULT_TOP, CM_MULT_BOTTOM, CM_OFFSET_TOP, CM_OFFSET_BOTTOM = 200, 201, 202, 203, 204, 205
CM_MAP_TOP, CM_MAP_BOTTOM, CM_COLOR_TOP, CM_COLOR_BOTTOM, CM_MASK, CM_MASK_ON, CM_TOP_ON, CM_BOTTOM_ON = (
    206, 207, 208, 209, 210, 211, 212, 213)
CM_MULTIPLY, CM_MIX, CM_GAMMA, CM_SRGB = 2, 6, 7, 214
BLEND_ADD, BLEND_SUBTRACT, BLEND_DIVIDE, BLEND_MIN, BLEND_MAX, BLEND_DIFFERENCE = (
    "add", "subtract", "divide", "min", "max", "difference")
BLEND_SCREEN, BLEND_OVERLAY, BLEND_HARD_LIGHT, BLEND_DODGE, BLEND_BURN, BLEND_LINEAR_BURN, BLEND_LINEAR_LIGHT = (
    "screen", "overlay", "hard_light", "dodge", "burn", "linear_burn", "linear_light")
BLEND_EXCLUSION = "exclusion"
BLEND_OPS = (BLEND_ADD, BLEND_SUBTRACT, BLEND_DIVIDE, BLEND_MIN, BLEND_MAX, BLEND_DIFFERENCE, BLEND_SCREEN,
             BLEND_OVERLAY, BLEND_HARD_LIGHT, BLEND_DODGE, BLEND_BURN, BLEND_LINEAR_BURN, BLEND_LINEAR_LIGHT,
             BLEND_EXCLUSION)
# CoronaMix mixOperation (the names of Corona's Mix Operation list) -> Blend op (bottom op top), measured with
# renderMap (maxdrop-em3.28, maxdrop-em3.117): 0 add, 1 subtract (bottom - top, at least 0), 3 divide (bottom /
# top), 4 minimum, 5 maximum, 8 difference, 9 screen, 10 overlay, 11 color dodge, 12 color burn, 13 linear burn, 14
# linear light, 16 hard light, 20 exclusion (Blend's formulas, Corona's own). 7 gamma is bottom^(1 / top) (drawn
# for a top that converts to a grey constant, or over a constant bottom: _gamma_layers); 15 soft light
# (Photoshop's, not Blender's), 17 vivid light, 18 pin light and 19 hard mix have no node (peeled). mixInSRgb (on by
# default) runs the operation on |layer|^(1 / 2.2) and raises the magnitude of the result to 2.2 (linear light: black
# over black renders white); multiply, divide, min and max come out the same either way, a negative layer's sign kept
# (renderMap P5), so they are not CM_GAMMA_OPS. The amount lerp is linear in both modes.
CM_BLENDS = {0: BLEND_ADD, 1: BLEND_SUBTRACT, 3: BLEND_DIVIDE, 4: BLEND_MIN, 5: BLEND_MAX, 8: BLEND_DIFFERENCE,
             9: BLEND_SCREEN, 10: BLEND_OVERLAY, 11: BLEND_DODGE, 12: BLEND_BURN, 13: BLEND_LINEAR_BURN,
             14: BLEND_LINEAR_LIGHT, 16: BLEND_HARD_LIGHT, 20: BLEND_EXCLUSION}
CM_OP_NAMES = {7: "gamma", 15: "soft light", 17: "vivid light", 18: "pin light", 19: "hard mix"}  # in issues
CM_SRGB_GAMMA = 2.2
CM_GAMMA_RANGE = (0.01, 100.0)  # the exponents a gamma operation is drawn with (ColorCorrect's gamma)
CM_GAMMA_OPS = (BLEND_ADD, BLEND_SUBTRACT, BLEND_DIFFERENCE, BLEND_SCREEN, BLEND_OVERLAY, BLEND_HARD_LIGHT,
                BLEND_DODGE, BLEND_BURN, BLEND_LINEAR_BURN, BLEND_LINEAR_LIGHT, BLEND_EXCLUSION)
CM_OFFSET_SCALE = -0.1  # a layer is layer x multiplier + offset x CM_OFFSET_SCALE (renderMap: offset 1 -> -0.1)
# CoronaColor temperature (method 2): Corona 12's own colors, linear (the brightest channel 1), measured with renderMap
# in 3ds Max 2020; corona_kelvin interpolates linearly between the points.
CORONA_KELVIN = (
    (1000, (255, 2.22179, 0)), (1500, (255, 33.9377, 0)), (1900, (255, 59.3074, 0)), (2000, (255, 65.4825, 2.07004)),
    (2500, (255, 94.9066, 17.214)), (3000, (255, 121.607, 39.1868)), (3500, (255, 145.49, 66.1245)),
    (4000, (255, 166.681, 96.2179)), (4500, (255, 185.397, 127.969)), (5000, (255, 201.887, 160.23)),
    (5500, (255, 216.401, 192.171)), (6000, (255, 229.175, 223.218)), (6500, (255, 240.444, 253.004)),
    (6600, (251.265, 238.981, 255)), (7000, (231.144, 226.973, 255)), (8000, (195.163, 204.385, 255)),
    (9000, (171.689, 188.708, 255)), (10000, (155.374, 177.272, 255)), (12000, (134.502, 161.856, 255)),
    (15000, (117.37, 148.393, 255)), (20000, (103.409, 136.763, 255)), (25000, (96.3463, 130.615, 255)),
    (30000, (92.1245, 126.848, 255)), (40000, (87.3463, 122.494, 255)))

# Bitmap, block 0
BM_CLIP_U, BM_CLIP_V, BM_CLIP_W, BM_CLIP_H, BM_APPLY, BM_CROP_PLACE, BM_MONO, BM_RGB, BM_FILE = (
    0, 1, 2, 3, 6, 7, 9, 10, 13)
# Falloff, block 0. type 0 towards / away, 1 perpendicular / parallel, 2 Fresnel (3 shadow / light, 4 distance
# blend: peeled); direction 0 the viewing direction (the others: peeled); its MixCurve: curve_samples
FO_COLOR1, FO_AMOUNT1, FO_MAP1, FO_ON1, FO_COLOR2, FO_AMOUNT2, FO_MAP2, FO_ON2, FO_TYPE, FO_DIRECTION = range(10)
FO_IOR_OVERRIDE, FO_IOR = 11, 12
TOWARDS, PERPENDICULAR, FRESNEL = "towards", "perpendicular", "fresnel"  # Facing modes
FALLOFF_TYPES = {0: TOWARDS, 1: PERPENDICULAR, 2: FRESNEL}
# A Falloff's MixCurve as a polyline: a Bezier segment in CURVE_STEPS steps of x (32: within 1e-3 of 3ds Max's values
# on falloff_curve); a curve within CURVE_IDENTITY of y = x everywhere is no node. At most MAX_CURVE_SAMPLES points
# (Blender bakes a Float Curve into a table of 256 entries anyway): a curve of many points gets fewer steps per
# segment, then is resampled at even x, so a hostile curve costs neither time nor a huge node
CURVE_STEPS, CURVE_IDENTITY, MAX_CURVE_SAMPLES = 32, 1e-6, 256
# Mix, block 0: 1 lower, 2 upper (Use Curve's transition zone, 3ds Max's defaults 0.3 and 0.7)
MIX_LOWER, MIX_UPPER = 1, 2
# Checker, block 0: 0 soften, 1 / 2 color1 / 2, 3 / 4 map1 / 2, 5 / 6 their switches, 7 coords (its UVGen, a part)
CK_SOFTEN, CK_COLOR1, CK_COLOR2, CK_MAP1, CK_MAP2, CK_ON1, CK_ON2 = range(7)
# Composite blend modes (blendMode, per layer); measured with renderMap: result = lerp(below, blend(below, layer),
# opacity x mask). 7 linear burn, 15 soft light (Photoshop's), 17 pin light and 18 hard mix are not drawn: peeled
(NORMAL_BLEND, AVERAGE, ADDITION, SUBTRACT, DARKEN, MULTIPLY_BLEND, COLOR_BURN, LINEAR_BURN, LIGHTEN, SCREEN,
 COLOR_DODGE, LINEAR_DODGE, SPOTLIGHT, SPOTLIGHT_BLEND, OVERLAY, SOFT_LIGHT, HARD_LIGHT, PIN_LIGHT, HARD_MIX,
 DIFFERENCE, EXCLUSION, HUE, SATURATION, COLOR_BLEND, VALUE) = range(25)
BLENDS = frozenset(range(25)) - {LINEAR_BURN, SOFT_LIGHT, PIN_LIGHT, HARD_MIX}
# Color Correction rewiring, per output channel: 0..2 R, G, B, 3 A, 4..7 their inverse, 8 the mean of R, G and B,
# 9 one, 10 zero. rewireMode 1 (monochrome) stores (8, 8, 8), 2 (invert) (4, 5, 6), 3 the channels set
CC_REWIRE_MODE, CC_REWIRE = 2, (3, 4, 5)
REWIRE_NONE, REWIRE_INVERT, REWIRE_MONO = (0, 1, 2), (4, 5, 6), (8, 8, 8)
RW_ALPHA, RW_INV_ALPHA, RW_MONO, RW_ONE, RW_ZERO = 3, 7, 8, 9, 10
# RGB Tint, block 0: out = R x red + G x green + B x blue
TINT_RED, TINT_GREEN, TINT_BLUE = 0, 1, 2

# Placement (UVGen) old ParamBlock indices (its chunks: reader_materials.placement)
UV_U_OFFSET, UV_V_OFFSET, UV_U_TILING, UV_V_TILING, UV_U_ANGLE, UV_V_ANGLE, UV_W_ANGLE, UV_BLUR = range(8)
# Output (TexOutput) old ParamBlock indices (its flags: reader_materials.output_invert)
OUT_LEVEL, OUT_OFFSET, OUT_AMOUNT = 0, 1, 2


# the maps computed on the values the renderer holds in a gamma-off scene: at a color root in STORED under a Decode
# (_convert_node), and those not a wrapper of their own (_wrapper_input) in a mask the mean of it decoded
MASK_MIXES = (MIX, COMPOSITE, classids.CORONA_MIX, FALLOFF)
DISPLAY_MIXES = MASK_MIXES + (COLOR_CORRECTION, OUTPUT, RGB_TINT)
