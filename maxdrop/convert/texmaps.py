# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Texture-map rules: the map that drives a material input, turned into a small renderer-neutral graph.

    tex = TexmapConverter(graph, assets, textures=index, swatches=sw)   # MaterialGraph, AssetTable, optional
                                        # TextureIndex, colors.Swatches (default: read from graph's scene)
    g = tex.convert(map_ref, kind, value)   # TextureGraphIR, None when nothing usable drives the input
    g.root, g.kind, g.approximated, g.issues
    graphs = texture_graphs(ir, tex)        # {MaterialIR input name: TextureGraphIR}
    tex.stats.peeled, tex.stats.unsupported, tex.stats.issues

kind says what the input is: COLOR (base color, specular and transmission, which V-Ray and Standard drive with the
reflection and refraction colors, emission), DATA (roughness, metallic, opacity, and every mask below them), MASK (a
mask inside a COLOR or MASK graph: a Mix's, CoronaMix's or Composite layer's mask, the Corona layer mask; mask_kind),
NORMAL or BUMP. A map's value does not depend on its slot (V-Ray 5.2 renders, maxdrop-em3.122): a data input takes
it as it is; with the gamma on it is linear, with it off display-referred, so a color, and a mask that mixes colors,
is decoded in Blender while a data number is not. The gamma 3ds Max reads a Bitmap with in this scene is kept on its
Image (None: automatic, sRGB; 1.0 for an EXR or HDR file): with the gamma on its override, else the scene's file
input gamma (colors.Swatches.file_in); with the gamma off none, whatever its override, as 3ds Max reads the image as
stored then (maxdrop-em3.38), an EXR or HDR file too (the display-referred scene shows it decoded; maxdrop-em3.123).
A VRayBitmap's own decode on a color input or a mask is shown decoded once more with the gamma off (_shown,
maxdrop-em3.123; CoronaBitmap's is not: a Corona render is not measured, maxdrop-em3.165).
The color space (colorspace): a gamma of 2.2 is sRGB, any other Linear Rec.709 (sRGB
primaries: Blender converts them into the scene's working space; the builder falls back to Non-Color where the color
space is missing) and the builder applies the gamma (1.0: none), on a COLOR, DATA or MASK input alike; on a DATA or
MASK input an image read as linear (1.0) is Non-Color, and so is a DATA image whose pixels are read as stored in
this scene (a Bitmap, a VRayBitmap From 3ds Max, with the gamma off). NORMAL and BUMP images are always Non-Color
(not measured). A 128 grey PNG as glossiness, opacity or a mask renders 0.2195 with the gamma on (Bitmap auto or 2.2,
CoronaBitmap auto, VRayBitmap From 3ds Max), 0.502 with it off (Bitmap whatever its override; CoronaBitmap and
VRayBitmap sRGB keep their curve: 0.2195, 0.2159).
Constants are linear, a swatch made so by the scene's swatch rule (convert/colors.py: linear with the gamma on, the
sRGB curve with it off): in a COLOR graph always linear RGB (also when the input itself is a float, as specular and
transmission are: the builder takes the mean of the graph's color there, the measure materials.py uses); in a MASK
graph a float, the scene's rule applied to the mean of the swatch (V-Ray 5.2 renders a red mask as 1 / 3 before any
gamma; TexmapConverter._swatch); in a DATA or BUMP graph the mean of the swatch as stored, whatever the gamma (a grey
64 VRayColor renders glossiness 0.251 in both modes); the mean of the color for one that is linear already
(CoronaColor's HDR color; its temperature with the gamma on). In a NORMAL graph, and below a wrapper that works on
color (an RGB Tint other than the identity, an Output part that changes anything, a Color Correction) in a DATA or
BUMP graph (the kinds DATA_RGB and BUMP_RGB, rgb_kind), a swatch keeps its three channels as stored, and so do the
Tint's rows, the mean taken at the float input by the builder (maxdrop-em3.128). Measured: an empty RGB Tint of rows
128 / 64 / 32 renders 0.293 on opacity with the gamma off, the mean of the tinted white with the rows as stored
(maxdrop-em3.76); that a colored constant keeps its color below the wrapper, Color Correction, and the rows in a
normal input are assumed by the same rule. Images and masks below such a wrapper are as in DATA / BUMP (base_kind;
which output the wrapper asks an image for is not measured); a MASK graph keeps its rule of the mean below a wrapper
too (maxdrop-6n0.6.2). With the gamma off V-Ray mixes display values, so a mask between two colors is approximated
(a 0.502 mask between grey 40 and 220 renders 0.511, shown from 0.225 linear; MaxDrop's decoded mask gives 0.171).

The graph's nodes (frozen dataclasses): Image (an image map: the file as the scene stores it, the one the texture lookup
found, Mapping, Crop, TexOutput, color space, gamma, alpha), Constant, Invert, Mix(a, b, factor, mask), Multiply,
Blend (an arithmetic operation, optionally in a gamma space),
ColorCorrect (with its rewiring), Composite (CompositeLayers bottom first: node, opacity, blend mode, mask), Facing
(a Falloff's ratio), Remap (a float through a polyline: a Falloff's mix curve), Smoothstep (a Mix's curve on its
mask), Adjust (a wrapper's Output), Tint, NormalMap (an image, its strength, flips, the map channel of
its tangents, an additional Bump) and Bump (a height input and its strength). A map reached by
several paths is converted once per kind and depth, so a graph is a DAG of shared nodes; a graph larger than
MAX_NODES when drawn as a tree is cut down to its first image (an issue).

Rules, by ClassID (the decisions of an earlier 3ds Max -> FBX exporter, made native: node graphs instead of baked
files, the map angle kept, a height map in a bump slot a Bump node instead of dropped):

- Bitmap -> Image. Its Placement: tiling, offset, U / V / W angles, tile and mirror per axis, the map channel (the
  vertex color channel is channel 0), the axis (UV, VW, WU) and the coordinate source; environment mapping and the
  object or world XYZ sources are described and named as an issue (no UVs drive them), real-world scale too (its
  tiling is in scene units). Cropping or placement when applied and not the whole image; the Output (invert,
  amount, RGB level and offset) when it changes anything; alpha when the Bitmap gives its alpha to a mono input
  (mono output Alpha) or as its color (RGB output Alpha). A Bitmap without a file is no image (an issue).
- CoronaBitmap -> Image the same way, from its own parameters: UVW scale and offset, W angle, tiling (none, repeat,
  mirror) per axis, map channel, blur, clipping (crop or place), gamma (-1 automatic: 2.2 whatever the scene's
  gamma and input gamma, its override applied also with the gamma off, both measured), mono / RGB output alpha,
  real-world scale (an issue); its Output part as a Bitmap's.
- VRayBitmap (VRayHDRI before V-Ray 5: the same class) -> Image the same way: its Placement and Output parts as a
  Bitmap's, its own crop / place and mono / RGB output alpha; its transfer function as the gamma (none: 1.0, inverse
  gamma g: 1 / g, sRGB and auto: automatic, from 3ds Max: a Bitmap's automatic gamma, linear for an EXR or HDR
  file), its overall times render multiplier times the Output's amount (the order against the Output's invert and
  offset is assumed, not measured). With the gamma off a color input or mask shows that decode decoded once more
  (V-Ray 5.2), From 3ds Max the image as stored, decoded as a Bitmap's.
  An environment mapping type (angular, cubic, spherical, mirrored ball), a map
  source, ACEScg primaries, RGB output intensity, an unusable transfer function or multiplier are issues.
- CoronaColor -> Constant (color and hex as swatches, the HDR color linear, the temperature Corona's own linear
  color from CORONA_KELVIN, times the multiplier, decoded as a swatch with the gamma off). VRayColor -> Constant:
  its swatch times its RGB multiplier, then to the power of its color gamma (that order measured), made linear as a
  swatch; in temperature mode its color holds V-Ray's temperature color. Its alpha below 1, RGB primaries other
  than sRGB and unusable values are issues. CoronaMix: operation mix -> Mix(bottom, top, amount, mask), multiply ->
  Multiply, add, subtract, divide, min, max, difference, screen, overlay, color dodge, color burn, linear burn,
  linear light, hard light and exclusion -> Blend (in gamma 2.2 with mix in sRGB on, as Corona does: CM_BLENDS),
  gamma over a grey top color -> ColorCorrect gamma, all under a Mix for an amount below 1 or a mask; soft light,
  vivid light, pin light, hard mix (and gamma over another top) peeled to the first bitmap (an issue naming the
  operation); each layer times its multiplier plus its offset (CM_OFFSET_SCALE), measured.
- Kept as nodes (the allow-list): Mix (color 1 / 2 where a map is off or missing, the mask, the mix amount; Use
  Curve as mix_factor: folded into the mix amount, over a mask a Smoothstep), RGB Multiply, Color Correction (its
  rewiring first: monochrome, invert or custom channels, an alpha source drawn as one or zero, an issue; hue shift
  in turns, saturation as a factor; lightness either standard, brightness and contrast as fractions, or advanced,
  gain and gamma, whichever is chosen; tint and the advanced pivot and lift are not converted: an issue), Composite
  (each layer's blend mode in BLENDS and its mask as a data node; a layer in another mode peels the Composite),
  Falloff (types 0 to 2 in the viewing direction: Mix(side 1, side 2) by a Facing, a side lerp(color, map, map
  amount); its own Output as an Adjust; an edited MixCurve as a Remap of the Facing (curve_samples; one that cannot
  be read is drawn linear, an issue); another type or direction is peeled to map 1, else color 1, counted, an
  issue), Output (its Output part as an Adjust) and RGB Tint (a Tint unless the identity). Measured in 3ds Max 2020
  (renderMap, a rendered sphere for the Falloff): see the constants below.
- Peeled to the first usable map below, an approximation counted by class: VRayDirt (the unoccluded map when on,
  else the unoccluded color), VRayColor2Bump (its map). An Output or RGB Tint without a map (or with it off) is
  drawn as over a white map, its own Output or tint applied; a VRayColor2Bump without a map (it has no switch) is
  the constant (0.5, 0.5, 1); neither is counted (3ds Max 2020 renderMap and V-Ray 5.2 renders with the gamma off,
  maxdrop-em3.76; with it on assumed the same swatch, Corona not measured). In a normal map's normal slot that color
  as stored, drawn: V-Ray tilts the normal by the white as by a white map, (0.5, 0.5, 1) is flat (maxdrop-em3.128).
  Any other map class with maps below gives the first image below it (depth first, in reference order), counted the
  same way; one without is unsupported (counted, no graph).
- Normal maps (VRayNormalMap, Normal Bump, CoronaNormal) in a normal or bump input -> NormalMap: the normal image
  with the class's multiplier as its strength, flip red / green and swap, and the additional bump map as a Bump with
  its multiplier; a normal map class with only its bump map is that Bump. In any other input it is peeled to its
  normal image (or its bump image).
- A map that is set (and switched on) but converts to nothing (an unsupported class with no bitmap below, a
  Bitmap without a file, a cut branch) is an issue on its wrapper
  naming its class, and never stands in as the wrapper's own color for it (3ds Max uses that color only without a
  map or with the map off): a Color Correction, VRayDirt, Output, RGB Tint or VRayColor2Bump over it gives
  no graph and is not counted (the lost map is reported), so the input keeps its own value.
  A Mix or CoronaMix weighs it by its amount: a side that does not show is drawn as its color (exact), a side that
  fills the result gives no graph, any other weight (or a mask) peels the wrapper to its other side's map, or no
  graph; an RGB Multiply and a Falloff (its sides show by the angle) are always peeled that way. A lost mask
  leaves the mix amount, a lost Composite layer is left out (both approximations); a normal map class keeps its
  other map.
- The slot itself: a glossiness map feeding roughness (MapRef.invert) is under an Invert; a slot amount below 1 mixes
  the input's value with the map (Mix(Constant(value), map, amount)), above 1 multiplies the map; in a bump input the
  amount is the Bump's strength, in a normal input it scales the NormalMap's strengths.

Each map object counts at most once in stats.peeled or stats.unsupported, each issue once in stats.issues. The file
comes from anywhere: a reference cycle, a chain deeper than MAX_DEPTH, a reference to an object that is not a map or
a damaged object end that branch (an issue), a shared map is converted once (no blow-up through repeated
references), and unreadable Placement, Output or BitmapInfo chunks take the defaults. Those chunks are read by
reader/materials.py (placement, output_invert, bitmap_gamma, mix_curve); what they hold is judged here. No bpy, no
mathutils.
"""
import collections
import dataclasses
import math

from ..reader import chunks, classids, pblock
from ..reader import materials as reader_materials
from ..reader.classdir import ClassId
from ..reader.errors import MaxFileError
from . import colors, params
from .params import finite as _finite

ChunkError = chunks.ChunkError

COLOR, DATA, MASK, NORMAL, BUMP = "color", "data", "mask", "normal", "bump"
FLOATS = (DATA, MASK)  # the kinds a map gives one number to: its mono output
# The input of a wrapper that works on color (RGB Tint, an Output part, Color Correction) in a data or bump graph:
# a swatch keeps its channels as stored, images and masks below are as in DATA / BUMP (rgb_kind, base_kind).
DATA_RGB, BUMP_RGB = "data rgb", "bump rgb"
_RGB_KINDS = {DATA: DATA_RGB, BUMP: BUMP_RGB}
_BASE_KINDS = {v: k for k, v in _RGB_KINDS.items()}
STORED_RGB = (DATA_RGB, BUMP_RGB, NORMAL)  # the kinds whose swatch is its three channels as stored
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
# only for a grey top that is its color: _corona_gamma_exponent); 15 soft light (Photoshop's, not Blender's), 17 vivid
# light, 18 pin light and 19 hard mix have no node (peeled). mixInSRgb (on by default) runs the operation on
# layer^(1 / 2.2) and raises the magnitude of the result to 2.2 (linear light: black over black renders white);
# multiply, divide, min and max come out the same either way. The amount lerp is linear in both modes.
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


@dataclasses.dataclass(frozen=True)
class Mapping:
    """How a Bitmap is laid on the surface. angle: U, V, W in radians; axis 0 UV, 1 VW, 2 WU; source EXPLICIT (the
    map channel), OBJECT_XYZ, VERTEX_COLOR (channel 0) or WORLD_XYZ."""
    channel: int = 1
    tiling: tuple = (1.0, 1.0)
    offset: tuple = (0.0, 0.0)
    angle: tuple = (0.0, 0.0, 0.0)
    tile: tuple = (True, True)
    mirror: tuple = (False, False)
    axis: int = 0
    source: int = EXPLICIT
    environment: bool = False
    real_world: bool = False
    blur: float = 1.0


@dataclasses.dataclass(frozen=True)
class Crop:
    """The part of the image used (u, v from the top left, width, height, 0..1): cropped, or placed (place: the
    whole image shrunk into that rectangle)."""
    u: float
    v: float
    w: float
    h: float
    place: bool = False


@dataclasses.dataclass(frozen=True)
class TexOutput:
    """A map's Output: level times the color plus offset (inverted: level times (1 - color) minus offset, measured),
    then times amount."""
    invert: bool = False
    amount: float = 1.0
    level: float = 1.0
    offset: float = 0.0


@dataclasses.dataclass(frozen=True)
class Image:
    """An image map (Bitmap, CoronaBitmap, VRayBitmap). path / resolved: as the scene stores them (resolved:
    FileAssetMetaData3's); found: the textures.Found of the lookup, None without a lookup or when the file was not
    found; gamma: the gamma 3ds Max reads it with in this scene (linear = pixel ^ gamma: its override, or the file
    input gamma), None for automatic (sRGB; 1.0 for an EXR or HDR file); with the gamma off on a color input or a
    mask the one the display-referred scene shows it with (None, sRGB, for an image read as stored; _shown; a
    CoronaBitmap keeps its own, Corona not measured); alpha: the image's alpha is used, not its color."""
    index: int
    name: str
    path: str = ""
    resolved: str = ""
    found: object = None
    mapping: Mapping = Mapping()
    crop: object = None
    output: object = None
    colorspace: str = SRGB
    gamma: object = None
    alpha: bool = False


@dataclasses.dataclass(frozen=True)
class Constant:
    """A swatch: linear RGB in a color input, a float elsewhere."""
    value: object


@dataclasses.dataclass(frozen=True)
class Invert:
    input: object


@dataclasses.dataclass(frozen=True)
class Mix:
    """a where factor (or the mask) is 0, b where it is 1."""
    a: object
    b: object
    factor: float = 0.5
    mask: object = None


@dataclasses.dataclass(frozen=True)
class Multiply:
    a: object
    b: object


@dataclasses.dataclass(frozen=True)
class Blend:
    """op (BLEND_OPS) per channel on a^(1 / gamma) and b^(1 / gamma), the magnitude of the result raised to gamma:
    add a + b, subtract a - b floored at 0, divide a / b (a where b is 0, as Blender divides), min, max, difference
    |a - b|, screen 1 - (1 - a)(1 - b), overlay 2ab where a < 0.5 else 1 - 2(1 - a)(1 - b), hard light overlay(b, a),
    dodge a / (1 - b) at most 1 (1 where b is 1), burn 1 - (1 - a) / b at least 0 (0 where b is 0), linear burn
    a + b - 1 at least 0, linear light a + 2b - 1, exclusion a + b - 2ab. Not clamped otherwise (CoronaMix's
    formulas; Blender's Dodge, Burn and Exclusion nodes clamp to 0..1 where those leave it, which only a layer
    outside 0..1 reaches, and a dodge of 0 under 1). A CoronaMix in sRGB mode is gamma 2.2."""
    op: str
    a: object
    b: object
    gamma: float = 1.0


@dataclasses.dataclass(frozen=True)
class ColorCorrect:
    """rewire: the source of the red, green and blue outputs (REWIRE_NONE: unchanged; codes as CC_REWIRE's), applied
    first; hue: shift in turns; saturation: factor (1 = unchanged); brightness, contrast: added fractions; gain:
    factor; gamma: the advanced mode's (1 = none)."""
    input: object
    rewire: tuple = REWIRE_NONE
    hue: float = 0.0
    saturation: float = 1.0
    brightness: float = 0.0
    contrast: float = 0.0
    gain: float = 1.0
    gamma: float = 1.0


@dataclasses.dataclass(frozen=True)
class CompositeLayer:
    """A Composite layer: its node, opacity 0..1, blend mode (BLENDS) and mask (a data node, None: none). The result
    is lerp(below, blend(below, node), opacity x mask); the bottom layer is over black whatever its mode."""
    node: object
    opacity: float = 1.0
    blend: int = NORMAL_BLEND
    mask: object = None


@dataclasses.dataclass(frozen=True)
class Composite:
    """layers: CompositeLayers, bottom first."""
    layers: tuple


@dataclasses.dataclass(frozen=True)
class Facing:
    """A Falloff's ratio, 0 facing the viewer and 1 at grazing (PERPENDICULAR: 1 - |N.V|), away from it (TOWARDS:
    (1 - N.V) / 2), or the dielectric Fresnel reflectance of ior (FRESNEL)."""
    mode: str = PERPENDICULAR
    ior: float = 1.6


@dataclasses.dataclass(frozen=True)
class Remap:
    """A float input through a curve: points, (x, y) pairs with x ascending, joined by straight lines and flat past
    the ends (a Falloff's mix curve, curve_samples; flat is assumed, a Falloff's ratio stays within 0..1). Its result
    is not clamped."""
    input: object
    points: tuple


@dataclasses.dataclass(frozen=True)
class Smoothstep:
    """Mix's Use Curve on a float input (mix_factor): 0 below lower, 1 from upper, smoothstep between; a step at
    lower when lower >= upper."""
    input: object
    lower: float = 0.3
    upper: float = 0.7


@dataclasses.dataclass(frozen=True)
class Adjust:
    """A wrapper's Output (TexOutput) over its input."""
    input: object
    output: TexOutput


@dataclasses.dataclass(frozen=True)
class Tint:
    """RGB Tint: input R x red + G x green + B x blue, each a linear RGB."""
    input: object
    red: tuple = (1.0, 0.0, 0.0)
    green: tuple = (0.0, 1.0, 0.0)
    blue: tuple = (0.0, 0.0, 1.0)


@dataclasses.dataclass(frozen=True)
class Bump:
    """A height input and its strength."""
    input: object
    strength: float = 1.0


@dataclasses.dataclass(frozen=True)
class NormalMap:
    """A tangent-space normal image, its strength, its channel flips, the map channel of its tangents and an
    additional Bump (or None)."""
    input: object
    strength: float = 1.0
    flip_red: bool = False
    flip_green: bool = False
    swap: bool = False
    bump: object = None
    channel: int = 1


@dataclasses.dataclass(frozen=True)
class TextureGraphIR:
    """What drives one input: root node, the input's kind, approximated (a map was peeled below a class whose own
    effect is lost), and the issues met on the way, each once. Shared by every material using the same slot."""
    root: object
    kind: str
    approximated: bool = False
    issues: tuple = ()


class TexmapStats:
    """peeled {class name: map objects peeled}, unsupported {class name: map objects without a usable map below},
    issues [(object index, reason)]."""
    __slots__ = ("peeled", "unsupported", "issues")

    def __init__(self):
        self.peeled, self.unsupported, self.issues = collections.Counter(), collections.Counter(), []


class _Walk:
    """The state of one map's conversion: approximated and the issues of its subtree."""
    __slots__ = ("approximated", "issues")

    def __init__(self):
        self.approximated, self.issues = False, []

    def merge(self, approximated, issues):
        self.approximated = self.approximated or approximated
        self.issues.extend(r for r in issues if r not in self.issues)


def _children(node):
    if isinstance(node, (Invert, Bump, ColorCorrect, Adjust, Tint, Remap, Smoothstep)):
        return (node.input,)
    if isinstance(node, Mix):
        return tuple(n for n in (node.a, node.b, node.mask) if n is not None)
    if isinstance(node, (Multiply, Blend)):
        return (node.a, node.b)
    if isinstance(node, Composite):
        return tuple(n for layer in node.layers for n in (layer.node, layer.mask) if n is not None)
    if isinstance(node, NormalMap):
        return (node.input,) if node.bump is None else (node.input, node.bump)
    return ()


def tree_size(node):
    """The number of nodes of a graph drawn as a tree (a shared node counted at each use), in linear time."""
    sizes = {}

    def size(n):
        k = id(n)
        if k not in sizes:
            sizes[k] = 1 + sum(size(c) for c in _children(n))
        return sizes[k]
    return size(node)


def first_image(node):
    """The first Image of a graph, depth first, None without one."""
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        if isinstance(n, Image):
            return n
        stack.extend(reversed(_children(n)))
    return None


def _num(m, pid, default):
    return params.num(m, pid, 0, default)


def _flag(m, pid, default):
    return params.flag(m, pid, 0, default)


def _vec(m, pid, default):
    """A point3 parameter as a tuple of floats, default when it is unusable."""
    v = m.param(pid, 0)
    n = len(default)
    if isinstance(v, tuple) and len(v) >= n and all(_finite(c) for c in v[:n]):
        return tuple(float(c) for c in v[:n])
    return default


def kelvin_rgb(kelvin):
    """A color temperature as an sRGB swatch (0..1): the curve fit of the rules source, 1000 K to 40000 K."""
    t = min(40000.0, max(1000.0, kelvin)) / 100.0
    r = 255.0 if t <= 66.0 else 329.698727446 * (t - 60.0) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66.0 else 288.1221695283 * (t - 60.0) ** -0.0755148492
    b = 255.0 if t >= 66.0 else 0.0 if t <= 19.0 else 138.5177312231 * math.log(t - 10.0) - 305.0447927307
    return tuple(min(255.0, max(0.0, c)) / 255.0 for c in (r, g, b))


def corona_kelvin(kelvin):
    """Corona's color of a temperature, linear RGB 0..1: CORONA_KELVIN, clamped to its 1000 K to 40000 K."""
    pts = CORONA_KELVIN
    k = min(float(pts[-1][0]), max(float(pts[0][0]), kelvin))
    for (k0, c0), (k1, c1) in zip(pts, pts[1:]):
        if k <= k1:
            t = (k - k0) / (k1 - k0)
            return tuple((a + (b - a) * t) / 255.0 for a, b in zip(c0, c1))
    return tuple(c / 255.0 for c in pts[-1][1])


def _overlay(x, y):
    return 2.0 * x * y if x < 0.5 else 1.0 - 2.0 * (1.0 - x) * (1.0 - y)


def blend_value(op, a, b, gamma=1.0):
    """Blend's result for two constants (linear RGB tuples or floats), CoronaMix's formulas (Blend): a Gamma node
    leaves an input channel at or below 0 as it is, the result's magnitude is raised. Inputs held within
    +-MAX_MULTIPLIER (no overflow), the result before its gamma too."""
    def power(v, p):
        return v ** p if v > 0.0 else v

    def one(x, y):
        x, y = (min(MAX_MULTIPLIER, max(-MAX_MULTIPLIER, v)) for v in (x, y))
        if gamma != 1.0:
            x, y = power(x, 1.0 / gamma), power(y, 1.0 / gamma)
        r = {BLEND_ADD: lambda: x + y, BLEND_SUBTRACT: lambda: max(0.0, x - y),
             BLEND_DIVIDE: lambda: x / y if y != 0.0 else x, BLEND_MIN: lambda: min(x, y),
             BLEND_MAX: lambda: max(x, y), BLEND_DIFFERENCE: lambda: abs(x - y),
             BLEND_SCREEN: lambda: 1.0 - (1.0 - x) * (1.0 - y), BLEND_OVERLAY: lambda: _overlay(x, y),
             BLEND_HARD_LIGHT: lambda: _overlay(y, x),
             BLEND_DODGE: lambda: 1.0 if y == 1.0 else min(1.0, x / (1.0 - y)),
             BLEND_BURN: lambda: 0.0 if y == 0.0 else max(0.0, 1.0 - (1.0 - x) / y),
             BLEND_LINEAR_BURN: lambda: max(0.0, x + y - 1.0), BLEND_LINEAR_LIGHT: lambda: x + 2.0 * y - 1.0,
             BLEND_EXCLUSION: lambda: x + y - 2.0 * x * y}[op]()
        r = min(MAX_MULTIPLIER, max(-MAX_MULTIPLIER, r))
        return abs(r) ** gamma if gamma != 1.0 else r
    if isinstance(a, tuple):
        return tuple(one(x, y) for x, y in zip(a, b))
    return one(a, b)


def _ref(m, pid, tab=0):
    """The object index of a reference parameter, None when it is empty or not a reference."""
    v = m.param(pid, 0, tab=tab)
    return v.index if isinstance(v, pblock.Reference) else None


def _old(part, index, default):
    """A value of a part's old ParamBlock (slot order: the first one)."""
    if part is None or not part.legacy:
        return default
    v = part.legacy[min(part.legacy)].get(index)
    return float(v) if _finite(v) else default


def rgb_kind(kind):
    """The kind of a color wrapper's input below a map of that kind: DATA_RGB in a data graph, BUMP_RGB in a height,
    the kind itself elsewhere (a color, a normal; a mask keeps its rule of the mean)."""
    return _RGB_KINDS.get(kind, kind)


def base_kind(kind):
    """The kind an image or a normal map class below takes: DATA for DATA_RGB, BUMP for BUMP_RGB."""
    return _BASE_KINDS.get(kind, kind)


def _linear(rgb, kind):
    """A linear color (not a swatch) as a Constant of the input's kind: its channels in a color input and where a
    swatch keeps its channels (STORED_RGB), else their mean."""
    return Constant(tuple(rgb) if kind == COLOR or kind in STORED_RGB else sum(rgb) / 3.0)


def colorspace(kind, gamma, stored=False):
    """The color space of an image in an input of that kind read with that gamma (None: automatic, sRGB); stored:
    the map reads its pixels as stored in this scene (a Bitmap, or a VRayBitmap From 3ds Max, with the gamma off),
    which a data input takes as they are. A normal or bump image is always data (unmeasured). A float input's image
    read as linear (gamma 1.0) is Non-Color too: the same numbers, and one Blender image with the normal and bump
    uses of the file."""
    if kind in (NORMAL, BUMP) or (kind == DATA and stored):
        return NON_COLOR
    if kind in FLOATS and gamma is not None and abs(gamma - 1.0) <= GAMMA_TOLERANCE:
        return NON_COLOR
    if gamma is None or abs(gamma - SRGB_GAMMA) <= GAMMA_TOLERANCE:
        return SRGB
    return LINEAR


def _auto_gamma(gamma, name):
    """A Bitmap's or CoronaBitmap's gamma: automatic (None) reads a float file (EXR, HDR) as linear, as 3ds Max and
    Corona do; an override is kept."""
    return 1.0 if gamma is None and name.lower().endswith(FLOAT_IMAGES) else gamma


def _shown(gamma):
    """The gamma Blender reads an image with when a gamma-off scene shows the map's own decode (gamma: linear =
    pixel ^ gamma; None: the sRGB curve) decoded once more, as V-Ray 5.2 shows a VRayBitmap and a float file there
    (maxdrop-em3.123): 2.2 x its own (2.2 itself: sRGB, exact), SRGB_TWICE for the sRGB curve."""
    return SRGB_TWICE if gamma is None else gamma * SRGB_GAMMA


def unshown(image):
    """A Bitmap's or VRayBitmap's color Image made in a gamma-off scene with its own decode again (_shown undone;
    None, an image read as stored, gives linear): for a float file lighting a scene, where the display decode of
    values far above 1 is not measured (convert.lights.dome_texture)."""
    g = image.gamma
    own = 1.0 if g is None else (None if abs(g - SRGB_TWICE) <= GAMMA_TOLERANCE else g / SRGB_GAMMA)
    return dataclasses.replace(image, gamma=own, colorspace=colorspace(COLOR, own))


def drawn_gamma(image):
    """The power a builder applies after an Image's texture, None for none: its gamma when the image is Linear
    Rec.709 for it (any other gamma is its color space's, or 1.0)."""
    g = image.gamma
    if g is not None and abs(g - 1.0) > 1e-6 and image.colorspace == LINEAR == colorspace(COLOR, g):
        return g
    return None


class TexmapConverter:
    """Converts the maps of one MaterialGraph; assets: the scene's reader.assets.AssetTable (None: no file is
    known); textures: a convert.textures.TextureIndex to look each file up (None: no lookup); swatches: the
    colors.Swatches rule of the scene (None: read from graph's scene)."""

    def __init__(self, graph, assets=None, textures=None, swatches=None):
        self.graph, self.assets, self.textures = graph, assets, textures
        self.swatches = swatches if swatches is not None else colors.of_graph(graph)
        self.stats = TexmapStats()
        self._counted, self._done, self._reported = set(), {}, set()
        self._nodes, self._firsts = {}, {}  # keyed (object, kind, depth)

    def _issue(self, walk, index, reason):
        if (index, reason) not in self._reported:
            self._reported.add((index, reason))
            self.stats.issues.append((index, reason))
        if reason not in walk.issues:
            walk.issues.append(reason)

    def _class_name(self, m):
        entry = self.graph.scene.entry(m.index)  # m came from graph.get: an object of the scene
        return (entry.name if entry is not None else "") or classids.name_of(m.superclass, m.class_id) or \
            "ClassID%s" % (ClassId(*m.class_id),)

    def _count(self, counter, m):
        if m.index not in self._counted:
            self._counted.add(m.index)
            counter[self._class_name(m)] += 1

    def convert(self, ref, kind, value=None):
        """The TextureGraphIR of a materials.MapRef in an input of that kind whose own value is value; None when no
        usable map drives it."""
        key = (ref, kind, value)
        if key in self._done:
            return self._done[key]
        walk = _Walk()
        root = self._node(ref.index, kind, walk, 0, ())
        out = None
        if root is not None:
            root = self._slot(root, ref, kind, value, walk)
            if tree_size(root) > MAX_NODES:
                image = first_image(root)
                self._issue(walk, ref.index, "map %d: graph of more than %d nodes cut down to its first image"
                            % (ref.index, MAX_NODES))
                walk.approximated = True
                root = self._slot(image, ref, kind, value, walk) if image is not None else None
            if root is not None:
                out = TextureGraphIR(root, kind, walk.approximated, tuple(walk.issues))
        self._done[key] = out
        return out

    def _slot(self, root, ref, kind, value, walk):
        amount = ref.amount
        if ref.invert:
            root = Invert(root)
        if kind == BUMP:
            if isinstance(root, NormalMap):
                return _scaled(root, amount)
            if isinstance(root, Bump):
                return Bump(root.input, root.strength * amount)
            return Bump(root, amount)
        if kind == NORMAL:
            if isinstance(root, NormalMap):
                return _scaled(root, amount)
            if isinstance(root, Bump):
                return Bump(root.input, root.strength * amount)
            return NormalMap(root, amount)
        if kind == COLOR and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = (float(value),) * 3  # a color graph is RGB throughout, also on a float input
        if amount < 1.0 and value is not None:
            return Mix(Constant(value), root, amount)
        if amount > 1.0:
            return Multiply(root, Constant(amount if kind != COLOR else (amount,) * 3))
        return root

    def _get(self, i, walk, depth, chain):
        """The MtlBase of map object i, None (an issue) when the branch ends there."""
        if depth > MAX_DEPTH:
            self._issue(walk, i, "maps deeper than %d below object %d" % (MAX_DEPTH, chain[0] if chain else i))
            return None
        if i in chain:
            self._issue(walk, i, "map cycle through object %d" % i)
            return None
        if self.graph.superclass(i) != classids.SC_TEXMAP:
            self._issue(walk, chain[-1] if chain else i, "object %d is not a map" % i)
            return None
        try:
            return self.graph.get(i)
        except ChunkError as e:
            self._issue(walk, i, "map %d: %s" % (i, e))
            return None

    def _node(self, i, kind, walk, depth, chain):
        """The node of map object i in an input of that kind, None when nothing usable is there. Converted once per
        (object, kind, depth): the same map reached again shares the node, its issues and its approximation."""
        # The key leaves out the chain, so a map met first through a cycle keeps the branch the cycle cut, also where
        # it is reached again without one: order-dependent, and only in a scene that has a cycle. Keying on the chain
        # (or not caching a cut) would make a shared map cost one conversion per path to it, not one in all
        # (test_shared_maps_do_not_blow_up).
        if i is None:
            return None
        key = (i, kind, depth)
        hit = self._nodes.get(key)
        if hit is None:
            sub = _Walk()
            node = self._convert_node(i, kind, sub, depth, chain)
            hit = self._nodes[key] = (node, sub.approximated, tuple(sub.issues))
        walk.merge(hit[1], hit[2])
        return hit[0]

    def _convert_node(self, i, kind, walk, depth, chain):
        m = self._get(i, walk, depth, chain)
        if m is None:
            return None
        key, chain, depth = ClassId(*m.class_id), chain + (i,), depth + 1
        if key in IMAGES:
            return self._image(m, kind, walk)
        if key in NORMAL_MAPS:
            return self._normal(m, NORMAL_MAPS[key], kind, walk, depth, chain)
        rule = _KEEP.get(key)
        if rule is not None:
            return rule(self, m, kind, walk, depth, chain)
        rule = _PEEL.get(key)
        if rule is not None:
            node = rule(self, m, kind, walk, depth, chain)
            if node is not None:
                walk.approximated = True
                self._count(self.stats.peeled, m)
            return node
        return self._peel_to_image(m, kind, walk, depth, chain, "no bitmap below")

    def _peel_to_image(self, m, kind, walk, depth, chain, why):
        """The first image below map m, counted as a peel; None (unsupported, an issue) without one."""
        image = self._first_image(m, kind, walk, depth, chain)
        if image is None:
            self._count(self.stats.unsupported, m)
            self._issue(walk, m.index, "%s %r: %s" % (self._class_name(m), m.name, why))
            return None
        walk.approximated = True
        self._count(self.stats.peeled, m)
        return image

    def _first_image(self, m, kind, walk, depth, chain):
        """The first image below map m, depth first in reference order, None without one; looked for once per
        (map, kind, depth), its issues replayed into every walk that finds it."""
        key = (m.index, kind, depth)
        if key not in self._firsts:
            self._firsts[key] = (None, False, ())  # a cycle back to here finds nothing
            sub = _Walk()
            image = self._first_image_walk(m, kind, sub, depth, chain)
            self._firsts[key] = (image, sub.approximated, tuple(sub.issues))
        image, approximated, issues = self._firsts[key]
        walk.merge(approximated, issues)
        return image

    def _first_image_walk(self, m, kind, walk, depth, chain):
        for c in m.children:
            if depth > MAX_DEPTH or c in chain or self.graph.superclass(c) != classids.SC_TEXMAP:
                continue
            try:
                sub = self.graph.get(c)
            except ChunkError:
                continue
            if ClassId(*sub.class_id) in IMAGES:
                image = self._image(sub, kind, walk)
                if image is not None:
                    return image
                continue
            image = self._first_image(sub, kind, walk, depth + 1, chain + (c,))
            if image is not None:
                return image
        return None

    def _constant(self, m, pid, kind, default):
        """A color parameter as a Constant of the input's kind."""
        v = m.param(pid, 0)
        rgb = v if isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3]) else default
        return self._swatch(rgb, kind)

    def _swatch(self, rgb, kind):
        """A swatch (0..1 per channel) as a Constant of the input's kind: on a color input the linear color; on a mask
        in a color graph the scene's rule applied to the mean of the swatch (maxdrop-em3.36); on a data input (and a
        height) the mean as stored, whatever the gamma (maxdrop-em3.122); in a normal input and below a wrapper that
        works on color in a data graph or a height (STORED_RGB) its channels as stored: the wrapper acts on the color
        and the mean comes after it, at the float input (maxdrop-em3.128). Each channel clamped to 0..1 first.
        V-Ray 5.2 renders a grey 64 / red VRayColor as glossiness or opacity 0.251 / 0.333 in both modes; as a mask
        between black and white with the gamma off it renders byte 64 / 85, which Blender shows from the decoded number.
        Between two colors V-Ray mixes the display values, so the decoded mask is only close there."""
        if kind == COLOR:
            return Constant(self.swatches.color(rgb))
        stored = tuple(min(1.0, max(0.0, c)) for c in rgb[:3])
        if kind in STORED_RGB:
            return Constant(stored)
        mean = sum(stored) / 3.0
        return Constant(self.swatches.channel(mean) if kind == MASK else mean)

    def _on(self, m, map_pid, on_pid, tab=0):
        """The object index of the map a parameter uses: set and its switch (on_pid, None: none) on; else None."""
        if on_pid is not None and not _flag(m, on_pid, True):
            return None
        return _ref(m, map_pid, tab)

    def _lost(self, m, i, walk):
        """The issue of a map i that wrapper m uses and that converts to nothing, naming its class. None for an
        object that is no readable map: _get has named it already."""
        try:
            sub = self.graph.get(i) if self.graph.superclass(i) == classids.SC_TEXMAP else None
        except ChunkError:
            sub = None
        if sub is not None:
            self._issue(walk, m.index, "%s %r: its map %s %r converts to nothing" % (
                self._class_name(m), m.name, self._class_name(sub), sub.name))

    def _sub(self, m, map_pid, on_pid, kind, walk, depth, chain, tab=0):
        """The node of the map a parameter uses (see _on), None without one. A used map that converts to nothing is
        an issue on m: the caller never draws m's own color in its place."""
        i = self._on(m, map_pid, on_pid, tab)
        node = self._node(i, kind, walk, depth, chain)
        if i is not None and node is None:
            self._lost(m, i, walk)
        return node

    def _image(self, m, kind, walk):
        """The Image of a Bitmap, CoronaBitmap or VRayBitmap, None (an issue) without a file."""
        kind = base_kind(kind)  # below a color wrapper in a data graph: a data image (its output not measured)
        key = ClassId(*m.class_id)
        cls, pid = _IMAGE_FILES.get(key, ("Bitmap", BM_FILE))
        entry = self.assets.entry(m.param(pid, 0)) if self.assets is not None else None
        if entry is None:
            self._issue(walk, m.index, "%s %r: no file" % (cls, m.name))
            return None
        found = self.textures.find(entry.path, entry.resolved) if self.textures is not None else None
        out = next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_TEXOUTPUT), None)
        if key == classids.CORONA_BITMAP:
            return self._corona_image(m, kind, walk, entry, found, out)
        uv = next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_UVGEN), None)
        mapping = self._mapping(uv)
        if key == classids.VRAY_BITMAP:
            return self._vray_image(m, kind, walk, entry, found, out, mapping)
        self._placement_issues(m, walk, "Bitmap", mapping)
        crop = None
        clip = tuple(_num(m, pid, d) for pid, d in ((BM_CLIP_U, 0.0), (BM_CLIP_V, 0.0), (BM_CLIP_W, 1.0),
                                                     (BM_CLIP_H, 1.0)))
        if _flag(m, BM_APPLY, False) and clip != (0.0, 0.0, 1.0, 1.0):
            crop = Crop(*clip, place=m.param(BM_CROP_PLACE, 0) == 1)
        gamma = self._bitmap_gamma(self._gamma(m), entry.name)
        alpha = m.param(BM_MONO if kind in FLOATS else BM_RGB, 0) == 1
        return Image(m.index, entry.name, entry.path, entry.resolved, found, mapping, crop, self._output(out),
                     colorspace(kind, gamma, not self.swatches.linear), gamma, alpha)

    def _placement_issues(self, m, walk, cls, mapping):
        """The issues of a UVGen's mapping that no UVs can draw."""
        if mapping.environment:
            self._issue(walk, m.index, "%s %r: environment mapping, drawn with the UVs" % (cls, m.name))
        elif mapping.source in (OBJECT_XYZ, WORLD_XYZ):
            self._issue(walk, m.index, "%s %r: planar %s XYZ mapping, drawn with the UVs" % (
                cls, m.name, "object" if mapping.source == OBJECT_XYZ else "world"))
        if mapping.real_world:
            self._issue(walk, m.index, "%s %r: real-world scale, its tiling in scene units not converted"
                        % (cls, m.name))

    def _vray_image(self, m, kind, walk, entry, found, out, mapping):
        """A VRayBitmap's Image: its Placement as a Bitmap's, its transfer function as a gamma (a Bitmap's
        meaning: linear = pixel ^ gamma), overall times render multiplier times its Output's amount (renderMap
        scales by the overall one; the render one applies when V-Ray renders)."""
        map_type = m.param(VB_MAP_TYPE, 0)
        if map_type not in (None, VB_STANDARD):
            mapping = dataclasses.replace(mapping, environment=True)
            self._issue(walk, m.index, "VRayBitmap %r: environment mapping (type %r), drawn with the UVs"
                        % (m.name, map_type))
        else:
            self._placement_issues(m, walk, "VRayBitmap", mapping)
        if _flag(m, VB_SOURCE_ON, True) and _ref(m, VB_SOURCE) is not None:
            self._issue(walk, m.index, "VRayBitmap %r: the placement of its map source not converted" % (m.name,))
        gamma = self._vray_gamma(m, walk, entry.name)
        if m.param(VB_RGB_SPACE, VB_RGB_SPACE_BLOCK) == VB_ACESCG:
            self._issue(walk, m.index, "VRayBitmap %r: ACEScg primaries drawn as sRGB" % (m.name,))
        if kind not in FLOATS and m.param(VB_RGB, 0) == VB_INTENSITY:
            self._issue(walk, m.index, "VRayBitmap %r: RGB output intensity as gray drawn as its color" % (m.name,))
        crop = None
        clip = tuple(_num(m, pid, d) for pid, d in ((VB_CROP_U, 0.0), (VB_CROP_V, 0.0), (VB_CROP_W, 1.0),
                                                     (VB_CROP_H, 1.0)))
        if _flag(m, VB_CROP_ON, False) and clip != (0.0, 0.0, 1.0, 1.0):
            crop = Crop(*clip, place=m.param(VB_CROP_MODE, 0) == 1)
        mult = max(0.0, _num(m, VB_MULT, 1.0)) * max(0.0, _num(m, VB_RENDER_MULT, 1.0))
        if not mult <= MAX_MULTIPLIER:
            self._issue(walk, m.index, "VRayBitmap %r: multiplier %r not converted: 1" % (m.name, mult))
            mult = 1.0
        output = self._output(out) or TexOutput()
        output = dataclasses.replace(output, amount=output.amount * mult)
        alpha = m.param(VB_MONO if kind in FLOATS else VB_RGB, 0) == 1
        stored = m.param(VB_COLOR_SPACE, 0) == VB_FROM_MAX and not self.swatches.linear
        if not self.swatches.linear and kind in (COLOR, MASK):
            # gamma off: From 3ds Max reads any file as stored, which the scene shows decoded (a Bitmap's rule);
            # every other transfer function is V-Ray's own decode, shown decoded once more
            gamma = None if stored else _shown(gamma)
        return Image(m.index, entry.name, entry.path, entry.resolved, found, mapping, crop,
                     None if output == TexOutput() else output, colorspace(kind, gamma, stored), gamma, alpha)

    def _bitmap_gamma(self, override, name):
        """A Bitmap's gamma as 3ds Max reads it in this scene (maxdrop-em3.38, V-Ray 5.2 renders): with the gamma on
        the override, else the file input gamma (None for 2.2: sRGB), a float file (EXR, HDR) without an override
        linear; with it off the image as stored whatever its override, which the display-referred scene shows
        decoded: None (sRGB), a float file too (V-Ray 5.2: an EXR of 0.5 renders 0.5, shown from 0.214 linear;
        maxdrop-em3.123)."""
        if not self.swatches.linear:
            return None
        if override is None and name.lower().endswith(FLOAT_IMAGES):
            return 1.0
        return override if override is not None else self._file_in()

    def _file_in(self):
        """The gamma an automatic image is read with: the scene's file input gamma with the gamma on, None for 2.2
        (sRGB) or with the gamma off."""
        g = self.swatches.file_in
        return g if self.swatches.linear and g != colors.SRGB_FILE_GAMMA else None

    def _vray_gamma(self, m, walk, name):
        """A VRayBitmap's transfer function as a Bitmap gamma, None for automatic: V-Ray's own decode, the same with
        the gamma on and off (V-Ray 5.2). Auto and From 3ds Max read a float file (EXR, HDR) as linear, as V-Ray and
        3ds Max do; From 3ds Max reads an 8-bit file as a Bitmap with automatic gamma does (the file input gamma
        with the gamma on). With the gamma off _vray_image turns it into what the scene shows (_shown)."""
        space = m.param(VB_COLOR_SPACE, 0)
        if space == VB_LINEAR:
            return 1.0
        if space == VB_INVERSE_GAMMA:
            inverse = _num(m, VB_GAMMA, 0.0)
            if 0.1 <= inverse <= 10.0:
                return 1.0 / inverse
            self._issue(walk, m.index, "VRayBitmap %r: transfer function inverse gamma %r not converted: automatic"
                        % (m.name, m.param(VB_GAMMA, 0)))
        elif space is not None and space not in VB_AUTOMATIC:
            self._issue(walk, m.index, "VRayBitmap %r: transfer function %r not converted: automatic"
                        % (m.name, space))
        elif space != VB_SRGB and name.lower().endswith(FLOAT_IMAGES):
            return 1.0
        elif space == VB_FROM_MAX:
            return self._file_in()
        return None

    def _corona_image(self, m, kind, walk, entry, found, out):
        """A CoronaBitmap's Image. Its tiling, offset and W angle place the image as a Bitmap's do (measured in
        3ds Max); its environment mode applies only to an environment map."""
        def mode(pid):
            v = m.param(pid, 0)
            return v if v in (0, 1, 2) else 1
        tile_u, tile_v = mode(CB_TILE_U), mode(CB_TILE_V)
        channel = m.param(CB_CHANNEL, 0)
        if not (isinstance(channel, int) and not isinstance(channel, bool) and 0 <= channel <= 99):
            channel = 1
        mapping = Mapping(
            channel=channel, tiling=_vec(m, CB_SCALE, (1.0, 1.0, 1.0))[:2],
            offset=_vec(m, CB_OFFSET, (0.0, 0.0, 0.0))[:2],
            angle=(0.0, 0.0, _num(m, CB_W_ANGLE, 0.0)),
            tile=(tile_u != CB_NO_TILE, tile_v != CB_NO_TILE), mirror=(tile_u == CB_MIRROR, tile_v == CB_MIRROR),
            real_world=_flag(m, CB_REAL_WORLD, False), blur=_num(m, CB_BLUR, 1.0))
        if mapping.real_world:
            self._issue(walk, m.index, "CoronaBitmap %r: real-world scale, its tiling in scene units not converted"
                        % (m.name,))
        crop = None
        clip = tuple(_num(m, pid, d) for pid, d in ((CB_CLIP_U, 0.0), (CB_CLIP_V, 0.0), (CB_CLIP_W, 1.0),
                                                     (CB_CLIP_H, 1.0)))
        if _flag(m, CB_CLIP_ON, False) and clip != (0.0, 0.0, 1.0, 1.0):
            crop = Crop(*clip, place=m.param(CB_CLIP_MODE, 0) == 1)
        gamma = _num(m, CB_GAMMA, -1.0)  # -1: automatic
        gamma = _auto_gamma(gamma if 0.1 <= gamma <= 10.0 else None, entry.name)
        alpha = m.param(CB_MONO if kind in FLOATS else CB_RGB, 0) == 1
        return Image(m.index, entry.name, entry.path, entry.resolved, found, mapping, crop, self._output(out),
                     colorspace(kind, gamma), gamma, alpha)

    def _mapping(self, uv):
        if uv is None:
            return Mapping()
        p = reader_materials.placement(self.graph.scene, uv.index)
        source = p.source if p.source in (EXPLICIT, OBJECT_XYZ, VERTEX_COLOR, WORLD_XYZ) else EXPLICIT
        channel = 1 if p.channel is None else p.channel
        channel = 0 if source == VERTEX_COLOR else (channel if 0 <= channel <= 99 else 1)
        return Mapping(
            channel=channel,
            tiling=(_old(uv, UV_U_TILING, 1.0), _old(uv, UV_V_TILING, 1.0)),
            offset=(_old(uv, UV_U_OFFSET, 0.0), _old(uv, UV_V_OFFSET, 0.0)),
            angle=(_old(uv, UV_U_ANGLE, 0.0), _old(uv, UV_V_ANGLE, 0.0), _old(uv, UV_W_ANGLE, 0.0)),
            tile=p.tile,
            mirror=p.mirror,
            axis=p.axis if p.axis in (0, 1, 2) else 0,
            source=source,
            environment=p.environment,
            real_world=p.real_world,
            blur=_old(uv, UV_BLUR, 1.0))

    def _output(self, part):
        """The TexOutput of a map's Output part, None when it changes nothing."""
        if part is None:
            return None
        out = TexOutput(reader_materials.output_invert(self.graph.scene, part.index), _old(part, OUT_AMOUNT, 1.0),
                        _old(part, OUT_LEVEL, 1.0), _old(part, OUT_OFFSET, 0.0))
        return None if out == TexOutput() else out

    def _gamma(self, m):
        """The Bitmap's gamma override, None for automatic, when it cannot be read or is outside 0.1 to 10."""
        gamma = reader_materials.bitmap_gamma(self.graph.scene, m)
        return gamma if gamma is not None and math.isfinite(gamma) and 0.1 <= gamma <= 10.0 else None

    def _normal(self, m, ids, kind, walk, depth, chain):
        normal = self._sub(m, ids.normal, ids.normal_on, NORMAL, walk, depth, chain)
        bump = self._sub(m, ids.bump, ids.bump_on, BUMP, walk, depth, chain)
        kind = base_kind(kind)
        if kind not in (NORMAL, BUMP):  # a normal map in a color or data input: its image only
            # a graph without an image (an empty Output or RGB Tint, a constant) is no image to stand for the normal
            # map's color
            image = next((n for n in (_peeled_image(normal), _peeled_image(bump))
                          if n is not None and first_image(n) is not None), None)
            if image is None:
                self._count(self.stats.unsupported, m)
                return None
            walk.approximated = True
            self._count(self.stats.peeled, m)
            return image
        key = ClassId(*m.class_id)
        if key == NORMAL_BUMP and m.param(NORMAL_BUMP_METHOD, 0) not in (None, 0):
            self._issue(walk, m.index, "Normal Bump %r: method %r drawn as tangent space" % (
                m.name, m.param(NORMAL_BUMP_METHOD, 0)))
        if key == CORONA_NORMAL and _flag(m, CORONA_ADD_GAMMA, False):
            self._issue(walk, m.index, "CoronaNormal %r: 'add gamma to input' not converted" % (m.name,))
        bump = Bump(_bump_input(bump), max(0.0, _num(m, ids.bump_strength, 1.0))) if bump is not None else None
        if normal is None:
            return bump
        channel = m.param(ids.channel, 0) if ids.channel is not None else None
        channel = channel if isinstance(channel, int) and not isinstance(channel, bool) and 0 <= channel <= 99 else 1
        return NormalMap(normal, max(0.0, _num(m, ids.strength, 1.0)), _flag(m, ids.flip_red, False),
                         _flag(m, ids.flip_green, False), _flag(m, ids.swap, False), bump, channel)


def _bump_input(node):
    return node.input if isinstance(node, Bump) else node


def _peeled_image(node):
    """The image of a normal map's sub-node, else the node itself."""
    if isinstance(node, NormalMap):
        return node.input
    if isinstance(node, Bump):
        return node.input
    return node


def _scaled(n, amount):
    bump = Bump(n.bump.input, n.bump.strength * amount) if n.bump is not None else None
    return dataclasses.replace(n, strength=n.strength * amount, bump=bump)


def _falloff_peel(conv, m, kind, walk, depth, chain):
    """A Falloff of a type or direction not drawn: map 1 when used, else color 1; counted as a peel."""
    if conv._on(m, FO_MAP1, FO_ON1) is not None:
        node = conv._sub(m, FO_MAP1, FO_ON1, kind, walk, depth, chain)
    else:
        node = conv._constant(m, FO_COLOR1, kind, (0.0, 0.0, 0.0))
    if node is not None:
        walk.approximated = True
        conv._count(conv.stats.peeled, m)
    return node


def _bezier_y(p0, c1, c2, p3, x):
    """y of the cubic Bezier p0, c1, c2, p3 where its x is x (bisection on the curve parameter, which assumes x(t)
    rises: handles far past the neighbouring points make it fold back, and y is then only near; a fixed 40 steps)."""
    def at(t, i):
        s = 1.0 - t
        return s * s * s * p0[i] + 3.0 * s * s * t * c1[i] + 3.0 * s * t * t * c2[i] + t * t * t * p3[i]
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if at(mid, 0) < x:
            lo = mid
        else:
            hi = mid
    return at(0.5 * (lo + hi), 1)


def curve_samples(points):
    """A Custom Curve Control's curve (reader CurvePoints) as 3ds Max 2020 evaluates it (measured, ICurve.GetValue
    and Falloff renders): segment i the cubic Bezier point i, its out handle, the in handle of point i + 1, point
    i + 1, its y at x; the flags do not change it; a point's y outside 0..1 is taken at the nearest bound, its handles
    moved with it; between the points the curve is not clamped. As a polyline, (x, y) pairs x ascending: a segment
    whose handles lie on its points is straight (its ends), any other one CURVE_STEPS steps of x (fewer, and the
    result resampled, past MAX_CURVE_SAMPLES). None when it is y = x (the default curve): no node. points: two or more
    (reader mix_curve's bound; an empty one raises IndexError)."""
    pts = []
    for p in points:
        (x, y), (ix, iy), (ox, oy) = p.point, p.in_handle, p.out_handle
        shift = min(1.0, max(0.0, y)) - y
        pts.append(((x, y + shift), (ix, iy + shift), (ox, oy + shift)))
    segments = list(zip(pts, pts[1:]))
    curved = sum(1 for (p0, _i0, o0), (p1, i1, _o1) in segments if p1[0] > p0[0] and not (o0 == p0 and i1 == p1))
    steps = max(1, min(CURVE_STEPS, (MAX_CURVE_SAMPLES - len(pts)) // max(1, curved)))
    out = [pts[0][0]]
    for (p0, _in0, out0), (p1, in1, _out1) in segments:
        if p1[0] <= p0[0] or (out0 == p0 and in1 == p1):
            out.append(p1)
            continue
        for k in range(1, steps + 1):
            x = p0[0] + (p1[0] - p0[0]) * k / steps
            out.append((x, p1[1] if k == steps else _bezier_y(p0, out0, in1, p1, x)))
    if len(out) > MAX_CURVE_SAMPLES:
        out = _resampled(out, MAX_CURVE_SAMPLES)
    if out[0][0] <= 0.0 and out[-1][0] >= 1.0 and all(abs(y - x) <= CURVE_IDENTITY for x, y in out) and \
            abs(out[0][1]) <= CURVE_IDENTITY and abs(out[-1][1] - 1.0) <= CURVE_IDENTITY:
        return None
    return tuple(out)


def _resampled(points, n):
    """The polyline points (x ascending) at n even steps of x from its first x to its last."""
    x0, x1 = points[0][0], points[-1][0]
    out, k = [], 0
    for j in range(n):
        x = x0 + (x1 - x0) * j / (n - 1)
        while k < len(points) - 2 and points[k + 1][0] <= x:
            k += 1
        (xa, ya), (xb, yb) = points[k], points[k + 1]
        out.append((x, yb if xb <= xa else ya + (yb - ya) * min(1.0, max(0.0, (x - xa) / (xb - xa)))))
    return out


def mix_factor(x, lower, upper):
    """A Mix's factor under Use Curve (measured with renderMap, by the mix amount and by a mask alike): 0 below lower,
    1 from upper on, between them smoothstep of (x - lower) / (upper - lower); lower >= upper: a step at lower."""
    if x < lower:
        return 0.0
    if x >= upper:
        return 1.0
    u = (x - lower) / (upper - lower)
    return u * u * (3.0 - 2.0 * u)


def _mix_curve(conv, m, walk):
    """The Remap points of Falloff m's MixCurve; None when it is linear, has none, or cannot be read (an issue)."""
    try:
        points = reader_materials.mix_curve(conv.graph.scene, m)
    except MaxFileError as e:
        walk.approximated = True
        conv._issue(walk, m.index, "Falloff %r: its mix curve could not be read (%s): drawn linear" % (m.name, e))
        return None
    return curve_samples(points) if points is not None else None


def _own_part(conv, m):
    """The TexOutput of the map's own Output part, None when it changes nothing."""
    return conv._output(next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_TEXOUTPUT), None))


def _own_output(conv, m, node):
    """node under the map's own Output part (Adjust) when that changes anything."""
    out = _own_part(conv, m)
    return node if node is None or out is None else Adjust(node, out)


def _falloff(conv, m, kind, walk, depth, chain):
    """Types 0, 1 and 2 in the viewing direction: Mix(side 1, side 2) by a Facing; side k is lerp(color k, map k,
    amount k) when map k is used, else color k (measured). An edited MixCurve: the Facing under a Remap (_mix_curve;
    3ds Max applies it to the ratio of all three types, unclamped, measured). Any other type or direction: peeled
    (_falloff_peel). A used map that converts to nothing: the other side's map (a peel)."""
    ftype, direction = m.param(FO_TYPE, 0), m.param(FO_DIRECTION, 0)
    ftype = 1 if ftype is None else ftype
    if ftype not in FALLOFF_TYPES or direction not in (None, 0):
        node = _falloff_peel(conv, m, kind, walk, depth, chain)
        if node is not None:
            conv._issue(walk, m.index, "Falloff %r: type %r, direction %r drawn as its first side"
                        % (m.name, ftype, direction))
        return node
    ids = ((FO_MAP1, FO_ON1), (FO_MAP2, FO_ON2))
    (a, b), lost = _sides(conv, m, ids, kind, walk, depth, chain)
    if any(lost):
        return _other_side(conv, m, (a, b), walk)
    sides = []
    for node, color, amount_pid, default in ((a, FO_COLOR1, FO_AMOUNT1, (0.0, 0.0, 0.0)),
                                              (b, FO_COLOR2, FO_AMOUNT2, (1.0, 1.0, 1.0))):
        constant = conv._constant(m, color, kind, default)
        if node is None:
            sides.append(constant)
            continue
        amount = min(1.0, max(0.0, _num(m, amount_pid, 100.0) / 100.0))
        sides.append(node if amount >= 1.0 else Mix(constant, node, amount))
    mode, ior = FALLOFF_TYPES[ftype], 1.6
    if mode == FRESNEL:
        ior = _num(m, FO_IOR, 1.6)
        if not 1.0 <= ior <= 10.0:
            conv._issue(walk, m.index, "Falloff %r: IOR %r not converted: 1.6" % (m.name, ior))
            ior = 1.6
        if not _flag(m, FO_IOR_OVERRIDE, True):
            conv._issue(walk, m.index, "Falloff %r: the material's IOR not read: its own, %g" % (m.name, ior))
    ratio = Facing(mode, ior)
    curve = _mix_curve(conv, m, walk)
    return _own_output(conv, m, Mix(sides[0], sides[1], 0.0, ratio if curve is None else Remap(ratio, curve)))


def _vray_dirt(conv, m, kind, walk, depth, chain):
    """13 unoccluded_color, 17 texmap_unoccluded_color, 18 its switch. The color only when the map is not used."""
    if conv._on(m, 17, 18) is not None:
        return conv._sub(m, 17, 18, kind, walk, depth, chain)
    return conv._constant(m, 13, kind, (1.0, 1.0, 1.0))


WHITE = (1.0, 1.0, 1.0)
C2B_EMPTY = (0.5, 0.5, 1.0)  # what a VRayColor2Bump without a map renders: a flat normal's color


def _wrapped(conv, m, map_pid, on_pid, kind, walk, depth, chain, empty=WHITE):
    """The map of a wrapper that has no color of its own (Output, RGB Tint, VRayColor2Bump), in kind (the caller's
    rgb_kind when the wrapper changes the color); without a used map the swatch empty: an Output or RGB Tint renders
    as over a white map, a VRayColor2Bump the color C2B_EMPTY (3ds Max 2020 renderMap and V-Ray 5.2 renders with the
    gamma off, maxdrop-em3.76; with it on assumed, Corona not measured). In a normal input (a normal map's normal
    slot) that color as stored: V-Ray tilts the normal by an Output's or RGB Tint's white as by a white map, and
    leaves it flat for C2B_EMPTY, which the builder draws the same (maxdrop-em3.128)."""
    if conv._on(m, map_pid, on_pid) is None:
        return conv._swatch(empty, kind)
    return conv._sub(m, map_pid, on_pid, kind, walk, depth, chain)


def _output_map(conv, m, kind, walk, depth, chain):
    """0 map1, 1 map1Enabled; its Output part as an Adjust (its clamp and color map curve are not read) over its map
    as a color (rgb_kind); an Output part that changes nothing leaves the map in its own kind, as with no wrapper."""
    out = _own_part(conv, m)
    node = _wrapped(conv, m, 0, 1, kind if out is None else rgb_kind(kind), walk, depth, chain)
    return node if node is None or out is None else Adjust(node, out)


def _rgb_tint(conv, m, kind, walk, depth, chain):
    """0 / 1 / 2 red / green / blue (swatches: made linear in a color graph and a mask, as stored in a data graph, a
    height or a normal, as every swatch there; em3.76 measured 0.293 on opacity for rows 128 / 64 / 32 over white,
    gamma off), 3 map1, 4 map1Enabled: a Tint over its map as a color (rgb_kind) unless the identity, which leaves
    the map in its own kind."""
    rows = COLOR if kind in (COLOR, MASK) else rgb_kind(kind)
    tint = tuple(conv._constant(m, pid, rows, d).value
                 for pid, d in ((TINT_RED, (1.0, 0.0, 0.0)), (TINT_GREEN, (0.0, 1.0, 0.0)),
                                (TINT_BLUE, (0.0, 0.0, 1.0))))
    if all(abs(c - (1.0 if i == j else 0.0)) <= 1e-6 for j, row in enumerate(tint) for i, c in enumerate(row)):
        return _wrapped(conv, m, 3, 4, kind, walk, depth, chain)
    node = _wrapped(conv, m, 3, 4, rgb_kind(kind), walk, depth, chain)
    return None if node is None else Tint(node, *tint)


def _color2bump(conv, m, kind, walk, depth, chain):
    """0 map (no switch): peeled to it, counted; without one the constant C2B_EMPTY, exact (not counted)."""
    if conv._on(m, 0, None) is None:
        return _wrapped(conv, m, 0, None, kind, walk, depth, chain, C2B_EMPTY)
    node = conv._sub(m, 0, None, kind, walk, depth, chain)
    if node is not None:
        walk.approximated = True
        conv._count(conv.stats.peeled, m)
    return node


def _sides(conv, m, ids, kind, walk, depth, chain):
    """The nodes of a two-map wrapper's sides ((map pid, switch pid) each), None where no map is used, and per side
    whether a used map converted to nothing."""
    nodes = tuple(conv._sub(m, pid, on, kind, walk, depth, chain) for pid, on in ids)
    lost = tuple(n is None and conv._on(m, pid, on) is not None for n, (pid, on) in zip(nodes, ids))
    return nodes, lost


def _lost_weight(lost, weights):
    """How much the lost sides show in the result, from each side's weight (0, 1, or None: partly or unknown, as
    under a mask): 0.0 none of them shows (their colors are drawn and stay invisible, exact), 1.0 one fills it (no
    graph), None partly (the wrapper is peeled to its other map)."""
    ws = [w for gone, w in zip(lost, weights) if gone]
    if any(w == 1.0 for w in ws):
        return 1.0
    return 0.0 if all(w == 0.0 for w in ws) else None


def _other_side(conv, m, nodes, walk):
    """A two-map wrapper with a lost map: its other side's map (a peel), else nothing; never its own color for the
    lost one, which 3ds Max uses only when no map is set or the map is off."""
    node = next((n for n in nodes if n is not None), None)
    if node is not None:
        walk.approximated = True
        conv._count(conv.stats.peeled, m)
    return node


def mask_kind(kind):
    """The kind of a mask below a map of that kind: MASK in a color graph (and below a mask), DATA elsewhere."""
    return MASK if kind in (COLOR, MASK) else DATA


def _mask(conv, m, pid, on_pid, kind, walk, depth, chain):
    """A mask map below a map of that kind; a used one that converts to nothing leaves the mix amount (an
    approximation)."""
    mask = conv._sub(m, pid, on_pid, mask_kind(kind), walk, depth, chain)
    if mask is None and conv._on(m, pid, on_pid) is not None:
        walk.approximated = True
    return mask


def _mix(conv, m, kind, walk, depth, chain):
    """0 mixAmount (fraction), 1 lower, 2 upper, 3 useCurve, 4 / 5 color1 / 2, 6 / 7 map1 / 2, 8 mask, 9 / 10 / 11
    their switches. Use Curve (mix_factor): the mix amount through it, or the mask under a Smoothstep."""
    (a, b), lost = _sides(conv, m, ((6, 9), (7, 10)), kind, walk, depth, chain)
    mask = _mask(conv, m, 8, 11, kind, walk, depth, chain)
    factor, curve = min(1.0, max(0.0, _num(m, 0, 0.0))), _flag(m, 3, False)
    if curve:
        lower, upper = _num(m, MIX_LOWER, 0.3), _num(m, MIX_UPPER, 0.7)
        factor = mix_factor(factor, lower, upper)  # also with a mask: what the builder takes when its image is missing
        mask = Smoothstep(mask, lower, upper) if mask is not None else None
    if any(lost):
        w = _lost_weight(lost, (None, None) if mask is not None else (1.0 - factor, factor))
        if w == 1.0:
            return None
        if w is None:
            return _other_side(conv, m, (a, b), walk)
    a = a or conv._constant(m, 4, kind, (0.0, 0.0, 0.0))
    b = b or conv._constant(m, 5, kind, (1.0, 1.0, 1.0))
    return Mix(a, b, factor, mask)


def _rgb_multiply(conv, m, kind, walk, depth, chain):
    """0 / 1 color1 / 2, 2 / 3 map1 / 2, 4 / 5 their switches."""
    (a, b), lost = _sides(conv, m, ((2, 4), (3, 5)), kind, walk, depth, chain)
    if any(lost):
        return _other_side(conv, m, (a, b), walk)
    a = a or conv._constant(m, 0, kind, (1.0, 1.0, 1.0))
    b = b or conv._constant(m, 1, kind, (1.0, 1.0, 1.0))
    return Multiply(a, b)


def _color_correction(conv, m, kind, walk, depth, chain):
    """0 color, 1 map, 2 rewireMode, 7 hueShift (degrees), 8 saturation (%), 10 tintStrength, 11 lightnessMode
    (0 standard: 12 brightness, 13 contrast; 1 advanced: 18 gainRGB (%), 22 gammaRGB, 26 pivotRGB, 30 liftRGB).
    Its color only without a map (3ds Max's rule): a map that converts to nothing leaves the input its own value.
    The map and the color are a color (rgb_kind): the correction acts on it, a float input takes the mean after."""
    node = conv._sub(m, 1, None, rgb_kind(kind), walk, depth, chain)
    if node is None:
        if conv._on(m, 1, None) is not None:
            return None
        node = conv._constant(m, 0, rgb_kind(kind), (0.0, 0.0, 0.0))
    if _num(m, 10, 0.0) != 0.0:
        walk.approximated = True
        conv._issue(walk, m.index, "Color Correction %r: tint not converted" % (m.name,))
    rewire = _rewire(conv, m, walk)
    hue, saturation = _num(m, 7, 0.0) / 360.0, 1.0 + _num(m, 8, 0.0) / 100.0
    if m.param(11, 0) != 1:
        return ColorCorrect(node, rewire, hue, saturation, _num(m, 12, 0.0) / 100.0, _num(m, 13, 0.0) / 100.0)
    if _num(m, 26, 1.0) != 1.0 or _num(m, 30, 0.0) != 0.0:
        walk.approximated = True
        conv._issue(walk, m.index, "Color Correction %r: pivot and lift not converted" % (m.name,))
    return ColorCorrect(node, rewire, hue, saturation, gain=_num(m, 18, 100.0) / 100.0,
                        gamma=max(0.01, _num(m, 22, 1.0)))


def _rewire(conv, m, walk):
    """The rewiring of a Color Correction (rewireMode 2; channels 3 to 5 in custom mode, 3). An alpha source is
    drawn as one (alpha) or zero (its inverse): the map's alpha is not carried; an unreadable channel or mode
    leaves the color unchanged. Both are issues."""
    mode = m.param(CC_REWIRE_MODE, 0)
    if mode in (None, 0):
        return REWIRE_NONE
    if mode == 1:
        return REWIRE_MONO
    if mode == 2:
        return REWIRE_INVERT
    channels = tuple(m.param(pid, 0) for pid in CC_REWIRE) if mode == 3 else None
    if channels is None or not all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= RW_ZERO
                                   for c in channels):
        walk.approximated = True
        conv._issue(walk, m.index, "Color Correction %r: rewiring %r not converted" % (
            m.name, channels if channels is not None else mode))
        return REWIRE_NONE
    if RW_ALPHA in channels or RW_INV_ALPHA in channels:
        walk.approximated = True
        conv._issue(walk, m.index, "Color Correction %r: rewired from alpha, drawn as opaque" % (m.name,))
        channels = tuple(RW_ONE if c == RW_ALPHA else RW_ZERO if c == RW_INV_ALPHA else c for c in channels)
    return channels


def _composite(conv, m, kind, walk, depth, chain):
    """Tables: 1 mapEnabled, 3 maskEnabled, 5 blendMode, 8 opacity (%), 9 mapList, 10 mask. Kept when every used
    layer above the bottom one has a blend mode in BLENDS (the bottom one is over black whatever its mode); else
    peeled to its first Bitmap. A layer's mask (on and set) is a float node of mask_kind(kind); one that converts to
    nothing leaves the opacity (an approximation)."""
    block = m.block(0)
    maps = block.value(9) if block is not None else None
    maps = maps if isinstance(maps, list) else []

    def at(pid, k, default):
        v = m.param(pid, 0, tab=k)
        return v if _finite(v) else default

    used = [k for k, r in enumerate(maps) if isinstance(r, pblock.Reference) and r.index is not None
            and at(1, k, 1)]
    modes = [at(5, k, 0) for k in used[1:]]
    if not all(mode in BLENDS for mode in modes):
        bad = sorted({mode for mode in modes if mode not in BLENDS})
        image = conv._peel_to_image(m, kind, walk, depth, chain, "blend modes %s, and no bitmap below" % (bad,))
        if image is not None:
            conv._issue(walk, m.index, "Composite %r: blend modes %s not converted" % (m.name, bad))
        return image
    layers = []
    for k in used:
        node = conv._node(maps[k].index, kind, walk, depth, chain)
        if node is None:
            walk.approximated = True
            conv._lost(m, maps[k].index, walk)
            continue
        mask = None
        if at(3, k, 1) and _ref(m, 10, k) is not None:
            mask = conv._node(_ref(m, 10, k), mask_kind(kind), walk, depth, chain)
            if mask is None:
                walk.approximated = True
                conv._lost(m, _ref(m, 10, k), walk)
        blend = at(5, k, 0) if layers else NORMAL_BLEND
        layers.append(CompositeLayer(node, min(1.0, max(0.0, at(8, k, 100.0) / 100.0)), blend, mask))
    if not layers:
        return None
    if len(layers) == 1 and layers[0].opacity == 1.0 and layers[0].mask is None:
        return layers[0].node
    return Composite(tuple(layers))


def _hex_rgb(text):
    """'#RRGGBB' as a swatch (0..1), None when it is not one."""
    s = text.strip().lstrip("#") if isinstance(text, str) else ""
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[k:k + 2], 16) / 255.0 for k in (0, 2, 4))
    except ValueError:
        return None


def _corona_color(conv, m, kind, walk, depth, chain):
    """50 method (0 color 52, 1 HDR color 58, 2 temperature 51, 3 hex 59), 57 multiplier. Color and hex are swatches,
    made linear by the scene's rule after the multiplier (a renderMap render in 3ds Max showed the multiplier
    scaling the swatch value: 2 x 128 = 255); the temperature is Corona's own linear color (corona_kelvin) times the
    multiplier with the gamma on, decoded as a swatch (clamped) with it off: VRayColor's and CoronaColor's 3000 K
    render the same values with the gamma on and off (V-Ray 5.2, renderMap; maxdrop-em3.38), which a gamma-off
    scene shows as stored. The HDR color is linear already (with the gamma off V-Ray 5.2 renders it as stored; kept linear, Corona not
    measured: maxdrop-em3.165). colorSpace (61)
    changed nothing in renderMap: not read."""
    method, mult = m.param(CC_METHOD, 0), max(0.0, _num(m, CC_MULTIPLIER, 1.0))
    if method == 1:
        rgb = tuple(max(0.0, c) * mult for c in _vec(m, CC_HDR, (1.0, 1.0, 1.0)))
        return _linear(rgb, kind)
    swatch = None
    if method == 2:
        lin = tuple(c * mult for c in corona_kelvin(_num(m, CC_TEMPERATURE, 6500.0)))
        if not conv.swatches.linear:
            return conv._swatch(lin, kind)
        return _linear(lin, kind)
    if method == 3:
        swatch = _hex_rgb(m.param(CC_HEX, 0))
        if swatch is None:
            conv._issue(walk, m.index, "CoronaColor %r: hex color %r not read: its color" % (
                m.name, m.param(CC_HEX, 0)))
    elif method not in (None, 0):
        conv._issue(walk, m.index, "CoronaColor %r: method %r not converted: its color" % (m.name, method))
    if swatch is None:
        v = m.param(CC_COLOR, 0)
        swatch = v[:3] if isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3]) else (1.0,) * 3
    return conv._swatch(tuple(c * mult for c in swatch), kind)


def _vray_color(conv, m, kind, walk, depth, chain):
    """VRayColor: its swatch (color, else red / green / blue) times rgb_multiplier, then to the power color_gamma
    (renderMap in 3ds Max: (100 gray, multiplier 2, gamma 2) -> 255 * (200 / 255) ^ 2), then made linear by the
    scene's rule like every swatch. In temperature mode color holds V-Ray's own temperature color, taken through
    the same rule (V-Ray 5.2 renders it the same with the gamma on and off: decoded with it off, as CoronaColor's
    temperature). A mono input takes the color, not the alpha (measured with a Mix mask); on a mask in a color
    graph the Constant is the scene's rule applied to the mean of the swatch, on a data input the mean as stored
    (V-Ray 5.2: glossiness 0.251 for grey 64 in both modes), as every swatch constant's (_swatch)."""
    mode = m.param(VC_MODE, 0)
    v = m.param(VC_COLOR, 0)
    if not (isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3])):
        v = tuple(m.param(pid, 0) for pid in (VC_RED, VC_GREEN, VC_BLUE))
    swatch = tuple(float(c) for c in v[:3]) if all(_finite(c) for c in v[:3]) else None
    if swatch is None:
        swatch = (1.0, 1.0, 1.0)
        if mode == 1:
            conv._issue(walk, m.index, "VRayColor %r: temperature color not read: white" % (m.name,))
    mult = m.param(VC_MULTIPLIER, 0)
    if mult is None:
        mult = 1.0
    elif not (_finite(mult) and mult >= 0.0):
        conv._issue(walk, m.index, "VRayColor %r: RGB multiplier %r not converted: 1" % (m.name, mult))
        mult = 1.0
    gamma = m.param(VC_GAMMA, 0)
    if gamma is None:
        gamma = 1.0
    elif not (_finite(gamma) and 0.01 <= gamma <= 100.0):
        conv._issue(walk, m.index, "VRayColor %r: color gamma %r not converted: 1" % (m.name, gamma))
        gamma = 1.0
    if mode not in (None, 0, 1):
        conv._issue(walk, m.index, "VRayColor %r: color mode %r not converted: its color" % (m.name, mode))
    alpha = m.param(VC_ALPHA, 0)
    if _finite(alpha) and alpha != 1.0:
        conv._issue(walk, m.index, "VRayColor %r: alpha %r not converted: 1" % (m.name, alpha))
    primaries = m.param(VC_PRIMARIES, 0)
    if primaries not in (None, 0):
        conv._issue(walk, m.index, "VRayColor %r: RGB primaries %r drawn as sRGB" % (m.name, primaries))
    scaled = tuple(min(1.0, max(0.0, c * float(mult))) for c in swatch)
    return conv._swatch(tuple(c ** float(gamma) for c in scaled), kind)


def _corona_layer(node, mult, offset):
    """A CoronaMix layer times its multiplier plus its offset (CM_OFFSET_SCALE): a Constant folded, a map under an
    Adjust; the node itself when they change nothing."""
    if mult == 1.0 and offset == 0.0:
        return node
    mult, offset = (min(MAX_MULTIPLIER, max(-MAX_MULTIPLIER, v)) for v in (mult, offset))
    add = offset * CM_OFFSET_SCALE
    if isinstance(node, Constant):
        v = node.value
        return Constant(tuple(c * mult + add for c in v) if isinstance(v, tuple) else v * mult + add)
    return Adjust(node, TexOutput(level=mult, offset=add))


def _corona_gamma_exponent(conv, m, kind):
    """The exponents of a CoronaMix gamma (bottom^(1 / e) per channel, renderMap: e is the top, in sRGB mode
    top^(1 / 2.2)) when its top is its color (no map, or the map off), a Constant: a float or a tuple. None when the
    top is a map or a channel's exponent is outside CM_GAMMA_RANGE (Corona's result is no number at a top of 0)."""
    if conv._on(m, CM_MAP_TOP, CM_TOP_ON) is not None:
        return None
    top = _corona_layer(conv._constant(m, CM_COLOR_TOP, kind, (1.0, 1.0, 1.0)), _num(m, CM_MULT_TOP, 1.0),
                        _num(m, CM_OFFSET_TOP, 0.0)).value
    srgb = _flag(m, CM_SRGB, True)
    es = tuple((t ** (1.0 / CM_SRGB_GAMMA) if srgb and t > 0.0 else t) for t in (top if isinstance(top, tuple)
                                                                                 else (top,)))
    if not all(CM_GAMMA_RANGE[0] <= e <= CM_GAMMA_RANGE[1] for e in es):
        return None
    return es if isinstance(top, tuple) else es[0]


def _gamma_value(v, e):
    """v^(1 / e) as a Gamma node draws it (a channel at or below 0 as it is), held within MAX_MULTIPLIER."""
    def one(x, p):
        return math.exp(min(math.log(MAX_MULTIPLIER), math.log(x) / p)) if x > 0.0 else x
    if isinstance(v, tuple):
        es = e if isinstance(e, tuple) else (e,) * len(v)
        return tuple(one(x, p) for x, p in zip(v, es))
    return one(v, e)


def _corona_mix(conv, m, kind, walk, depth, chain):
    """result = mix(bottom, operation(bottom, top), amount), the mask map replacing the amount (renderMap: an add at
    amount 0.8 under a 0.25 mask weighs 0.25), always a linear mix. Operation mix -> Mix(bottom, top, amount, mask),
    multiply -> Multiply, the operations of CM_BLENDS -> Blend (gamma 2.2 for CM_GAMMA_OPS with mixInSRgb on), gamma
    -> a ColorCorrect gamma of the bottom for a grey top that is its color (two colors folded per channel), each
    under a Mix when the amount is below 1 or a mask is set; any other operation (and a gamma over another top) is
    peeled to its first bitmap. Each layer is its map, or its color where the map is missing or switched off, times
    its multiplier plus its offset times CM_OFFSET_SCALE (measured, the multiplier first)."""
    op = m.param(CM_OPERATION, 0)
    exponent = _corona_gamma_exponent(conv, m, kind) if op == CM_GAMMA else None
    if isinstance(exponent, tuple) and len(set(exponent)) > 1 and conv._on(m, CM_MAP_BOTTOM, CM_BOTTOM_ON) is not None:
        exponent = None  # a colored top over a map: one exponent per channel, which no node draws
    if op not in (CM_MIX, CM_MULTIPLY) and op not in CM_BLENDS and exponent is None:
        name = CM_OP_NAMES.get(op, repr(op))
        image = conv._peel_to_image(m, kind, walk, depth, chain, "operation %s and no bitmap below" % (name,))
        if image is not None:
            conv._issue(walk, m.index, "CoronaMix %r: operation %s drawn as its first bitmap" % (m.name, name))
        return image
    (bottom, top), lost = _sides(conv, m, ((CM_MAP_BOTTOM, CM_BOTTOM_ON), (CM_MAP_TOP, CM_TOP_ON)), kind, walk,
                                 depth, chain)
    mask = _mask(conv, m, CM_MASK, CM_MASK_ON, kind, walk, depth, chain)
    amount = min(1.0, max(0.0, _num(m, CM_AMOUNT, 1.0)))
    if any(lost):
        if mask is not None:
            weights = (None, None)
        elif op == CM_MIX:
            weights = (1.0 - amount, amount)
        else:  # bottom op top: either side shows unless the amount is 0 (the bottom alone)
            weights = (1.0, 0.0) if amount == 0.0 else (None, None)
        w = _lost_weight(lost, weights)
        if w == 1.0:
            return None
        if w is None:
            return _other_side(conv, m, (bottom, top), walk)
    bottom = _corona_layer(bottom or conv._constant(m, CM_COLOR_BOTTOM, kind, (0.0, 0.0, 0.0)),
                           _num(m, CM_MULT_BOTTOM, 1.0), _num(m, CM_OFFSET_BOTTOM, 0.0))
    top = _corona_layer(top or conv._constant(m, CM_COLOR_TOP, kind, (1.0, 1.0, 1.0)),
                        _num(m, CM_MULT_TOP, 1.0), _num(m, CM_OFFSET_TOP, 0.0))
    if op == CM_MIX:
        return Mix(bottom, top, amount, mask)
    if op == CM_MULTIPLY:
        result = Multiply(bottom, top)
    elif op == CM_GAMMA:
        if isinstance(bottom, Constant):
            result = Constant(_gamma_value(bottom.value, exponent))
        else:
            result = ColorCorrect(bottom, gamma=exponent if isinstance(exponent, float) else exponent[0])
    else:
        blend = CM_BLENDS[op]
        gamma = CM_SRGB_GAMMA if blend in CM_GAMMA_OPS and _flag(m, CM_SRGB, True) else 1.0
        if isinstance(bottom, Constant) and isinstance(top, Constant):
            result = Constant(blend_value(blend, bottom.value, top.value, gamma))
        else:
            result = Blend(blend, bottom, top, gamma)
    return result if mask is None and amount == 1.0 else Mix(bottom, result, amount, mask)


_KEEP = {MIX: _mix, RGB_MULTIPLY: _rgb_multiply, COLOR_CORRECTION: _color_correction, COMPOSITE: _composite,
         classids.CORONA_COLOR: _corona_color, classids.CORONA_MIX: _corona_mix, classids.VRAY_COLOR: _vray_color,
         FALLOFF: _falloff, OUTPUT: _output_map, RGB_TINT: _rgb_tint, VRAY_COLOR2BUMP: _color2bump}
_PEEL = {VRAY_DIRT: _vray_dirt}

# MaterialIR input -> its kind (normal and bump: MapRefs of their own)
SLOT_KINDS = (("base_color", COLOR), ("metallic", DATA), ("roughness", DATA), ("specular", COLOR),
              ("transmission", COLOR), ("emission_color", COLOR), ("alpha", DATA))


def texture_graphs(ir, tex):
    """{input name: TextureGraphIR} for the inputs of a MaterialIR that a usable map drives."""
    out = {}
    for name, kind in SLOT_KINDS:
        inp = getattr(ir, name)
        if inp.map is not None:
            g = tex.convert(inp.map, kind, inp.value)
            if g is not None:
                out[name] = g
    for name, kind in (("normal", NORMAL), ("bump", BUMP)):
        ref = getattr(ir, name)
        if ref is not None:
            g = tex.convert(ref, kind)
            if g is not None:
                out[name] = g
    return out
