# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Texture-map rules: the map that drives a material input, turned into a small renderer-neutral graph.

    tex = TexmapConverter(graph, assets, textures=index, swatches=sw)   # MaterialGraph, AssetTable, optional
                                        # TextureIndex, colors.Swatches (default: read from graph's scene),
                                        # renderer= the scene's renderer ClassID (None: not known)
    g = tex.convert(map_ref, kind, value)   # TextureGraphIR, None when nothing usable drives the input
    g.root, g.kind, g.approximated, g.issues
    graphs = texture_graphs(ir, tex)        # {MaterialIR input name: TextureGraphIR}
    tex.stats.peeled, tex.stats.unsupported, tex.stats.approximated, tex.stats.issues

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
maxdrop-em3.123), and so is a CoronaBitmap's, and CoronaColor's HDR color (Corona 12 renders, maxdrop-em3.165: Corona
holds them, and a swatch as stored, the same with the gamma on and off).
The color space (colorspace): a gamma of 2.2 is sRGB, any other Linear Rec.709 (sRGB
primaries: Blender converts them into the scene's working space; the builder falls back to Non-Color where the color
space is missing) and the builder applies the gamma (1.0: none), on every input alike; on any but a COLOR input an
image read as linear (1.0) is Non-Color, and so is a DATA, NORMAL or BUMP image whose pixels are read as stored in
this scene (a Bitmap, a VRayBitmap From 3ds Max, with the gamma off). A NORMAL or BUMP input takes an image as a DATA
input does (V-Ray 5.2 and Corona 12 renders, maxdrop-em3.159: a flat (128, 128, 255) normal PNG under a Bitmap auto
or 2.2 tilts 38.5 degrees with the gamma on, none with it off or with 1.0; a CoronaBitmap auto decodes in both modes),
except that V-Ray reads a VRayBitmap below a normal map as stored whatever its transfer function (Non-Color, gamma
1.0). CoronaNormal's 'add gamma to input' raises an image input to 1 / 2.2 with the gamma on (_add_gamma) and does
nothing with it off. A 128 grey PNG as glossiness, opacity or a mask renders 0.2195 with the gamma on (Bitmap auto or
2.2, CoronaBitmap auto, VRayBitmap From 3ds Max), 0.502 with it off (Bitmap whatever its override; CoronaBitmap and
VRayBitmap sRGB keep their curve: 0.2195, 0.2159).
With the gamma off an image read as stored as a mask in a color graph is the mean of its stored pixel, decoded
(_stored_mask; V-Ray 5.2, maxdrop-6n0.6.36): a (200, 100, 50) PNG 0.4575 internal, not the mean of its decoded channels.
Constants are linear, a swatch made so by the scene's swatch rule (convert/colors.py: linear with the gamma on, the
sRGB curve with it off): in a COLOR graph always linear RGB (also when the input itself is a float, as specular and
transmission are: the builder takes the mean of the graph's color there, the measure materials/ uses); in a MASK
graph a float, the scene's rule applied to the mean of the swatch (V-Ray 5.2 renders a red mask as 1 / 3 before any
gamma; TexmapConverter._swatch); in a DATA or BUMP graph the mean of the swatch as stored, whatever the gamma (a grey
64 VRayColor renders glossiness 0.251 in both modes); the mean of the color for one that is not a swatch
(CoronaColor's HDR color, decoded on a mask with the gamma off; its temperature with the gamma on). In a NORMAL graph, and below a wrapper that works on
color (an RGB Tint other than the identity, an Output part that changes anything, a Color Correction) in a DATA or
BUMP graph (the kinds DATA_RGB and BUMP_RGB, rgb_kind), a swatch keeps its three channels as stored, and so do the
Tint's rows, the mean taken at the float input by the builder (maxdrop-em3.128). Measured: an empty RGB Tint of rows
128 / 64 / 32 renders 0.293 on opacity with the gamma off, the mean of the tinted white with the rows as stored
(maxdrop-em3.76); that a colored constant keeps its color below the wrapper, Color Correction, and the rows in a
normal input are assumed by the same rule. Images and masks below such a wrapper are as in DATA / BUMP (base_kind;
which output the wrapper asks an image for is not measured). In a MASK graph an RGB Tint or an Output part takes its
map as the color V-Ray holds (COLOR with the gamma on, STORED with it off: _wrapper_input) and the mask is the mean of
its output, decoded after the mean with the gamma off (_mask_mean; V-Ray 5.2 renders, maxdrop-6n0.6.2: rows 128 / 64 /
32 over a VRayColor (200, 100, 50) mask 0.1722 in both modes; assumed for Corona, a Corona layer mask and a Diffuse
Level map, which are MASK graphs too); an image there takes its RGB output's alpha rule, as in a color graph (not
measured). A Color Correction in a mask does the same (maxdrop-6n0.6.18: brightness 20 over a VRayColor 128 0.702 in
both modes; saturation -50 over that VRayColor 0.4739, the mean of the HSL saturation the builder draws).
With the gamma off V-Ray computes a Mix or Composite on the stored values (DISPLAY_MIXES; V-Ray 5.2 renders,
maxdrop-em3.158): its internal value is the one the gamma on gives (a Mix of greys 40 and 220 at 50 % renders 0.510,
by a 0.502 mask 0.511, a Composite of 64 + 64 in Addition 0.502), which the display-referred scene shows decoded
(0.223, 0.225, 0.216 linear). Such a map at a color root is converted in the kind STORED (a swatch as stored, an
image by its own decode, a Bitmap or a VRayBitmap From 3ds Max as stored, a mask DATA; CoronaColor's HDR color as
stored), every map below it too, under one Decode (drawn as
a power of 2.2, within 0.009 of the sRGB curve on 0..1; a constant, or a Mix of constants, folded exactly; a lone
image, a peel, is its map again as a color). A Mix between its colors black and white stays a Mix of decoded colors
by a decoded mask or amount (exact: maxdrop-em3.36). An RGB Multiply at a color root is left as it is: the decoded
product is within 0.005 of V-Ray's (128 x 128: 0.047 against 0.052). Corona 12 computes a Mix and a CoronaMix on
the values it holds, the same with the gamma on and off (maxdrop-em3.165: a 50 % Mix of CoronaBitmaps 64 and 192
renders 0.2917, a CoronaMix's operations their renderMap values): a CoronaMix is in DISPLAY_MIXES too. So are a
Falloff, a Color Correction, an Output and an RGB Tint (V-Ray 5.2 renders, maxdrop-6n0.6.18, the same internal value
in both modes: a Falloff of greys 40 / 220 at facing ratio 0.5 0.510, brightness 20 over 128 0.702, an Output's level
0.5 over 200 0.392; Corona 12 alike): a Tint or an Output over a constant folded exactly. A slot's amount below 1 on a
color input mixes the input's own value as stored with its map in STORED, under one Decode (a VRayMtl
self-illumination of 40 with a VRayColor 220 at 50 % 0.510; a Standard's Diffuse Level other than 1 on its diffuse
map, a scale, keeps the decoded mix, while _leveled's diffuse at level 1 takes the stored one: neither measured with
an amount; an amount of 0 is the value alone). Inside a mask such a mix (MASK_MIXES: a Mix, Composite, CoronaMix or Falloff, not
black to white) is computed on the held values too, and the mask is the mean of it decoded (Decode mean; a Mix of greys
40 / 220 at 50 % as a mask 0.510, shown 0.223).

The graph's nodes (frozen dataclasses): Image (an image map: the file as the scene stores it, the one the texture lookup
found, Mapping, Crop, TexOutput, color space, gamma, alpha), Constant, Invert, Decode (a gamma-off color mixed on
stored values, shown decoded), Mix(a, b, factor, mask), Multiply,
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
- CoronaColor -> Constant (color and hex as swatches, the HDR color as stored, decoded with the gamma off on a color
  input or mask, the temperature Corona's own linear
  color from CORONA_KELVIN, times the multiplier, decoded as a swatch with the gamma off). VRayColor -> Constant:
  its swatch times its RGB multiplier, then to the power of its color gamma (that order measured), made linear as a
  swatch; in temperature mode its color holds V-Ray's temperature color. Its alpha below 1, RGB primaries other
  than sRGB and unusable values are issues. CoronaMix: operation mix -> Mix(bottom, top, amount, mask), multiply ->
  Multiply, add, subtract, divide, min, max, difference, screen, overlay, color dodge, color burn, linear burn,
  linear light, hard light and exclusion -> Blend (in gamma 2.2 with mix in sRGB on, as Corona does: CM_BLENDS),
  gamma over a grey top color (its own or a map that converts to a constant, decided on the converted layers) ->
  ColorCorrect gamma (of a bottom map's magnitude in sRGB mode), all under a Mix for an amount below 1 or a mask; soft light, vivid light, pin light, hard mix
  (and gamma over another top) peeled to the first bitmap (an issue naming the operation); each layer times its
  multiplier plus its offset (CM_OFFSET_SCALE), measured.
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
  maxdrop-em3.76; V-Ray with the gamma on and Corona 12 render the same, maxdrop-em3.127; Corona renders an
  Output's map with its switch off, which a scene saved with Corona as its renderer keeps). In a normal map's normal
  slot that color as stored, drawn: V-Ray tilts the normal by the white as by a white map, (0.5, 0.5, 1) is flat
  (maxdrop-em3.128).
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
- The slot itself: a glossiness map feeding roughness (MapRef.invert) is under an Invert; a MapRef.scale other than 1
  (Standard's Diffuse Level, a Fresnel-off VRayMtl's metalness) multiplies the map; a slot amount below 1 mixes
  the input's value with the map (Mix(Constant(value), map, amount)), above 1 multiplies the map; in a bump input the
  amount is the Bump's strength, in a normal input it scales the NormalMap's strengths. A Standard material's
  Diffuse Level map (materials.DiffuseLevel) makes the base color graph Multiply(the diffuse at level 1, a Tint of
  rows 1/3 (the mean) over lerp(level, the map as a MASK, its amount)), each side over its constant where its
  images are missing (_leveled).

Each map object counts at most once in stats.peeled, stats.unsupported or stats.approximated (a procedural map
drawn with Blender's own pattern), each issue once in stats.issues. The file
comes from anywhere: a reference cycle, a chain deeper than MAX_DEPTH, a reference to an object that is not a map or
a damaged object end that branch (an issue), a shared map is converted once (no blow-up through repeated
references), and unreadable Placement, Output or BitmapInfo chunks take the defaults. Those chunks are read by
reader/materials.py (placement, output_invert, bitmap_gamma, mix_curve); what they hold is judged here. No bpy, no
mathutils.
"""

import collections
import contextlib
import dataclasses
import math

from ...reader import chunks, classids, pblock
from ...reader import materials as reader_materials
from ...reader.classdir import ClassId
from ...reader.errors import MaxFileError
from .. import colors, params
from ..params import finite as _finite

from .ids import (
    ChunkError, COLOR, DATA, MASK, NORMAL, BUMP, FLOATS, DATA_RGB, BUMP_RGB, _RGB_KINDS, _BASE_KINDS, STORED,
    STORED_RGB, _AS_STORED, SRGB, NON_COLOR, LINEAR, EXPLICIT, OBJECT_XYZ, VERTEX_COLOR, WORLD_XYZ, MAX_DEPTH,
    MAX_NODES, SRGB_GAMMA, GAMMA_TOLERANCE, SRGB_TWICE, FALLOFF, VRAY_DIRT, VRAY_COLOR2BUMP, OUTPUT, RGB_TINT, MIX,
    RGB_MULTIPLY, COLOR_CORRECTION, COMPOSITE, NORMAL_BUMP, CORONA_NORMAL, IMAGES, _NormalIds, NORMAL_MAPS,
    NORMAL_BUMP_METHOD, CORONA_ADD_GAMMA, CB_FILE, CB_CHANNEL, CB_SCALE, CB_OFFSET, CB_BLUR, CB_TILE_U, CB_TILE_V,
    CB_REAL_WORLD, CB_MONO, CB_RGB, CB_CLIP_ON, CB_CLIP_MODE, CB_CLIP_U, CB_CLIP_V, CB_CLIP_W, CB_CLIP_H, CB_GAMMA,
    CB_W_ANGLE, CB_NO_TILE, CB_MIRROR, VB_FILE, VB_MULT, VB_MAP_TYPE, VB_GAMMA, VB_RENDER_MULT, VB_CROP_ON,
    VB_CROP_MODE, VB_CROP_U, VB_CROP_V, VB_CROP_W, VB_CROP_H, VB_RGB, VB_MONO, VB_COLOR_SPACE, VB_SOURCE, VB_SOURCE_ON,
    VB_RGB_SPACE, VB_RGB_SPACE_BLOCK, VB_STANDARD, VB_INTENSITY, VB_ACESCG, VB_LINEAR, VB_INVERSE_GAMMA, VB_SRGB,
    VB_FROM_MAX, VB_AUTOMATIC, FLOAT_IMAGES, MAX_MULTIPLIER, _IMAGE_FILES, CC_METHOD, CC_TEMPERATURE, CC_COLOR,
    CC_MULTIPLIER, CC_HDR, CC_HEX, VC_RED, VC_GREEN, VC_BLUE, VC_ALPHA, VC_MULTIPLIER, VC_COLOR, VC_MODE, VC_GAMMA,
    VC_PRIMARIES, CM_OPERATION, CM_AMOUNT, CM_MULT_TOP, CM_MULT_BOTTOM, CM_OFFSET_TOP, CM_OFFSET_BOTTOM, CM_MAP_TOP,
    CM_MAP_BOTTOM, CM_COLOR_TOP, CM_COLOR_BOTTOM, CM_MASK, CM_MASK_ON, CM_TOP_ON, CM_BOTTOM_ON, CM_MULTIPLY, CM_MIX,
    CM_GAMMA, CM_SRGB, BLEND_ADD, BLEND_SUBTRACT, BLEND_DIVIDE, BLEND_MIN, BLEND_MAX, BLEND_DIFFERENCE, BLEND_SCREEN,
    BLEND_OVERLAY, BLEND_HARD_LIGHT, BLEND_DODGE, BLEND_BURN, BLEND_LINEAR_BURN, BLEND_LINEAR_LIGHT, BLEND_EXCLUSION,
    BLEND_OPS, CM_BLENDS, CM_OP_NAMES, CM_SRGB_GAMMA, CM_GAMMA_RANGE, CM_GAMMA_OPS, CM_OFFSET_SCALE, CORONA_KELVIN,
    BM_CLIP_U, BM_CLIP_V, BM_CLIP_W, BM_CLIP_H, BM_APPLY, BM_CROP_PLACE, BM_MONO, BM_RGB, BM_FILE, FO_COLOR1,
    FO_AMOUNT1, FO_MAP1, FO_ON1, FO_COLOR2, FO_AMOUNT2, FO_MAP2, FO_ON2, FO_TYPE, FO_DIRECTION, FO_IOR_OVERRIDE, FO_IOR,
    TOWARDS, PERPENDICULAR, FRESNEL, FALLOFF_TYPES, CURVE_STEPS, CURVE_IDENTITY, MAX_CURVE_SAMPLES, MIX_LOWER,
    MIX_UPPER, NORMAL_BLEND, AVERAGE, ADDITION, SUBTRACT, DARKEN, MULTIPLY_BLEND, COLOR_BURN, LINEAR_BURN, LIGHTEN,
    SCREEN, COLOR_DODGE, LINEAR_DODGE, SPOTLIGHT, SPOTLIGHT_BLEND, OVERLAY, SOFT_LIGHT, HARD_LIGHT, PIN_LIGHT, HARD_MIX,
    DIFFERENCE, EXCLUSION, HUE, SATURATION, COLOR_BLEND, VALUE, BLENDS, CC_REWIRE_MODE, CC_REWIRE, REWIRE_NONE,
    REWIRE_INVERT, REWIRE_MONO, RW_ALPHA, RW_INV_ALPHA, RW_MONO, RW_ONE, RW_ZERO, TINT_RED, TINT_GREEN, TINT_BLUE,
    UV_U_OFFSET, UV_V_OFFSET, UV_U_TILING, UV_V_TILING, UV_U_ANGLE, UV_V_ANGLE, UV_W_ANGLE, UV_BLUR, OUT_LEVEL,
    OUT_OFFSET, OUT_AMOUNT, MASK_MIXES, DISPLAY_MIXES,
)
from .ir import (
    Mapping, Crop, TexOutput, Image, Constant, Invert, Decode, Mix, Multiply, Blend, ColorCorrect, CompositeLayer,
    Composite, Facing, Remap, Smoothstep, Adjust, Tint, Bump, NormalMap, TextureGraphIR, TexmapStats, _Walk, _children,
    _has_decode, tree_size, first_image,
)
from .values import (
    _num, _flag, _vec, kelvin_rgb, corona_kelvin, _overlay, blend_value, _ref, rgb_kind, base_kind, _linear, colorspace,
    _auto_gamma, _shown, _stored_mask, unshown, drawn_gamma, _constant_value, _rgb3, _stored_value,
)
from .converter import TexmapConverter, _add_gamma, _bump_input, _peeled_image, _scaled
from .maps import (
    _falloff_peel, _bezier_y, curve_samples, _resampled, mix_factor, _mix_curve, _own_part, _own_output, _falloff,
    _vray_dirt, WHITE, C2B_EMPTY, CORONA_RENDERER, _wrapped, _wrapper_input, _mask_mean, _output_map, _rgb_tint,
    _color2bump, _sides, _lost_weight, _other_side, mask_kind, _black_white, _mask, _mix, _rgb_multiply,
    _color_correction, _rewire, _composite,
)
from .maps_color import (
    _hex_rgb, _corona_color, _vray_color, _corona_layer, _corona_gamma_exponent, _cm_top, _cm_bottom, _gamma_layers,
    _corona_peel, _gamma_value, _corona_mix,
)
from .dispatch import _KEEP, _PEEL, SLOT_KINDS
from .graphs import MEAN_ROW, _kept, _leveled, texture_graphs
