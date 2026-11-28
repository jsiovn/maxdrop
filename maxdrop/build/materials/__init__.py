# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender materials from convert.materials.MaterialIR: a Principled BSDF, its texture graphs drawn as nodes.

    builder = MaterialBuilder()
    material = builder.make(ir)         # a new Material, None when it fails; build.objects: once per Max material
    builder.issues()                    # [(label, reason)]: textures that do not load, channel 0, failed materials
    builder.classes                     # Counter {class name: materials made by a rule (grey ones not counted)}
    builder.sockets_skipped             # Counter {Principled input name: materials that needed it on this Blender}

The Principled BSDF's inputs are looked up by name with an existence check: Thin Wall exists from Blender 5.0 and
Diffuse Roughness from 4.5, so on an older Blender a value the IR asks for there is skipped and counted. Other
nodes' inputs are looked up by identifier (Fac, Bright, A_Color...), which stays the same while their names change
between versions.

Inputs: Base Color, Metallic, Roughness, IOR, Alpha, Specular IOR Level (the IR's specular is a reflection weight,
1 being the full Fresnel reflection at the IOR, Blender's 0.5; see Reflection weight below), Transmission Weight,
Emission Color and Strength, Coat Weight, Roughness, IOR and Tint, Subsurface Weight, Radius (the IR's subsurface color, per
channel) and Scale (its radius in meters), Sheen Weight, Tint and Roughness, Thin Wall, Normal. A material with layers
(a CoronaLayeredMtl, a VRayBlendMtl with coats) has a Principled BSDF per layer, each mixed over the ones below by a
Mix Shader (factor: the layer's amount times its mask), or for an added layer (VRayBlendMtl's additive mode) added
over them by an Add Shader, the layer scaled by a Mix Shader from nothing, or for a back layer (a VRay2SidedMtl's
back material) shown on back faces by a Mix Shader whose factor is Geometry > Backfacing; the render method follows
every one of them. A translucency (a VRay2SidedMtl's) mixes a Translucent BSDF (its color translucency_color, the
BSDF's normal; through the BSDF's alpha by a Mix Shader from a Transparent BSDF) over the BSDF by a Mix Shader
(TRANSLUCENCY_LABEL) whose factor is the translucency.
A material with a translucency (its own or a layer's) has a Value of 0 (THIN_LABEL) on the Material Output's Thickness
(compat.thin_surface: EEVEE then lets the light from behind through as Cycles does) and renders DITHERED, also at a
constant alpha below 1 (EEVEE's blended surface shows no light from behind; maxdrop-o53.1.10, docs/FORMAT.md).
A color graph on a float input (specular, transmission) goes through the mean of its channels, the measure convert/materials/ uses.

Medium (MaterialIR.medium, the Corona volumes, maxdrop-em3.163): on the Material Output's Volume socket, the sum (Add
Shader) of a Volume Scatter (density the largest scattering coefficient, color each channel's share of it, anisotropy),
a Volume Absorption (density the largest absorption coefficient, color 1 - each channel's share) and an Emission
(color the emission over its largest channel, strength that channel), each where it is above 0: Cycles takes the
coefficients per meter of world space, which convert/materials/ gives. A volume-only material (CoronaVolumeMtl:
a medium, alpha 0 without a map, no layers) leaves the Surface unlinked once its Volume is (maxdrop-6n0.6.29): Cycles
then crosses the box as a volume boundary, where an Alpha-0 Principled BSDF spends two of the 8 transparent bounces
per box (six stacked boxes render black); its viewport color is VOLUME_VIEWPORT_ALPHA opaque, so Solid view shows the
scene inside. Without a medium it keeps its Principled BSDF at Alpha 0: an unlinked Surface with nothing on Volume
renders black in Cycles. A medium that scatters is a builder issue (VOLUME_BOUNCES): Cycles scatters once at its
default Volume Bounces of 0, and the import changes no scene setting (owner, 2026-11-24); not with Corona's single
bounce on (Medium.single), which that default renders.

Reflection weight: V-Ray (and 3ds Max's Physical and Corona materials) multiply the whole Fresnel curve by it, where
Specular IOR Level scales only the reflectance facing the camera and the curve still rises to 1 at grazing. So a
weight w between 0 and 1, or a map, is a Mix Shader (WEIGHT_LABEL) by w between a twin of the filled Principled BSDF
(TWIN_LABEL: the same links and values, Specular IOR Level 0) and the BSDF at SPECULAR_LEVEL: w F spec + (1 - w F)
diffuse, V-Ray's split. Measured on V-Ray 5.2 (bead maxdrop-em3.119, the maxdrop-em3.34 scene, reflection grey 128 at
IOR 1.6, black diffuse, white environment): 0.0415 / 0.0789 at 0.8-0.88 / 0.9-0.95 of the sphere's radius, Cycles
the same, EEVEE about 7 % lower (as for a white reflection); the Specular IOR Level 0.25 drawn before gave 0.053 /
0.121. The lone BSDF (Specular IOR Level SPECULAR_LEVEL x w) stays where the twin would change nothing: a constant
w of 0 (but on glass, below) or at least 1 (above 1 counted as 1, as a map is by the Mix Shader's factor), a constant
Metallic of 1. Every
material class follows: the rule reads the IR's weight, whatever made it (Standard, Physical, CoronaLegacyMtl: not
measured against their renderers).
Refracting glass (Transmission Weight linked or above 0): Specular IOR Level does not change a transmissive
Principled's reflection (measured in Cycles), so there the twin's part without reflection is a Refraction BSDF
(REFRACTION_LABEL: the Principled's Roughness, IOR and Normal, its color the square root of the Base Color, as the
Principled tints each of the two passes through a solid; a thin wall: the Base Color at IOR 1, as Cycles tints each
wall, where EEVEE tints a closed thin-walled object once), below em3.119's twin with Transmission Weight 0 by a Mix
Shader (TWIN_LABEL) whose factor is the transmission, unless that is a constant of at least 1: w F + (1 - w F) T,
V-Ray's split; a constant w of 0 too (a black reflection on glass reflects nothing, as in V-Ray). The weight is 1 where the Fresnel at the IOR is 1 (TIR_LABEL: a Fresnel node, GREATER_THAN
TIR_FRESNEL, MAXIMUM with w; not on a thin wall): there the glass reflects totally, and Cycles' Refraction BSDF is
black. Measured in Blender 4.2, 4.5 and 5.2 (bead maxdrop-em3.135, a smooth sphere, IOR 1.6, black base, white
environment): w 0.502 reflects 0.502 times the white reflection in every band, Cycles and EEVEE; a rotated cube of
white glass keeps 0.999 of the white environment in Cycles (0.83 without the mask). A rough twin is GGX (a Refraction
BSDF has no multiscatter GGX), and a Principled with a metallic, an alpha below 1 or a map, an emission, a coat or a
sheen (none of which a Refraction BSDF has) keeps em3.119's twin, whose glass still reflects in full. Not measured against V-Ray (no V-Ray render of a glass with a grey reflection).
An IR whose fresnel is off (VRayMtl Fresnel off) reflects its weight at every angle: the same Mix Shader then has the
filled BSDF at Specular IOR Level 0 first and a copy of it second (MIRROR_LABEL: Metallic 1, Base Color the IR's
mirror_color, white unless a VRayMtl's colored swatch tints it, both unlinked), a metal reflecting that color at every
angle, so w x color + (1 - w) diffuse. Measured on V-Ray 5.2 (bead
maxdrop-em3.120, the same scene): a 0.2 swatch reflects 0.200 facing the camera, where Specular IOR Level 0.1 gave
0.011. A reflection map that did not convert, or whose image is not found, keeps the twin (its swatch is a weight with
Fresnel), so a bright swatch it hid never becomes a mirror. On refracting glass (refracting() above, full or partial)
the mirror's first shader is the refraction twin, its factor raised to 1 under total internal reflection on a solid
(the filled BSDF, whose glass still reflects, then feeds nothing): w + (1 - w) T, V-Ray's split. Measured in Blender
4.2, 4.5 and 5.2 (bead maxdrop-6n0.7.2, a smooth sphere, IOR 1.6, white environment, w 0.2): a black base reflects
0.200 in every band in Cycles (the lone glass gave 0.053 facing the camera to 0.166 at 0.9-0.95 of the radius), a
base 0.25 0.400 (0.2 + 0.8 x 0.25), a thin wall and half transmission 0.200; a rotated cube of white glass keeps 1.0
of the white environment in Cycles; EEVEE 0.198-0.199 on the black base and 0.356-0.358 on the 0.25 one, flat.
EEVEE gives w + ((1 - w) c)^2 for the twin's color c (= the square root of T), not w + (1 - w) T: it refracts
through a solid as two events, each applying the refraction closure's weight times color, the Mix Shader's factor
included, and has no internal bounce to return the share the mirror reflects back inside, as Cycles' bounces do.
Measured in Blender 4.2, 4.5 and 5.2 (bead maxdrop-6n0.7.4, w 0.2, white glass): a rotated cube 0.836-0.839 and
a smooth sphere 0.831-0.834, flat (Cycles 1.000 both; w 0.5 on the cube: EEVEE 0.746-0.748, Cycles 0.995); the
lone Principled glass gave 0.926-0.930 on the cube in EEVEE. Not total internal reflection: on the cube a lone
Refraction BSDF keeps 0.994 of the environment, one of color 0.8 0.636 (0.8^2; hand-wired, 5.2). The drawing
stays: both engines read the same factor and color, so a factor or color that lifts EEVEE lifts Cycles too (short
of a second Material Output for EEVEE only, which would duplicate the stack above every such BSDF). Material
Output's Thickness linked to 0 (one refraction event in EEVEE, a thin shell's look; Cycles ignores it) gives white
glass 0.990-0.994 (a sphere), but applies c once, so tinted glass gets too light (a sphere, c 0.5, w 0.2: 0.594-0.596, where Cycles gives 0.400 and the
default 0.356-0.358; hand-wired, 4.2 to 5.2); left out, for white glass too: it changes the view through a curved
solid. Measured in Blender 4.2, 4.5 and 5.2 (bead maxdrop-6n0.7.6, white glass w 0.2 drawn here, Thickness linked
to 0 by hand, orthographic camera, a checker world of 0.1 / 0.9): a sphere's mean |EEVEE - Cycles| rises from
0.111-0.121 to 0.273-0.278 (one refraction's magnified view in place of the ball lens's small inverted one; a
rotated cube's from 0.206-0.221 to 0.196-0.217, both far off), and on a white world half transmission (sphere and
cube) moves away from Cycles' 0.851-0.853 (0.975-0.983, the default 0.896-0.905).
Glass that refracting() refuses keeps the filled BSDF under the mirror, its glass Fresnel still reflecting; a
constant w of at least 1 keeps the lone BSDF (a VRayMtl's full Fresnel-off reflection is a metal before it gets
here). Not measured against V-Ray.

Data maps (a map on roughness, metallic or alpha, a mask, a bump height: a graph drawn as a float) take the mean of
their channels too: wherever a float graph comes out as a color socket (an image's Color, a Color Correction, a
Blend or a blend-mode Composite) one Vector Math DOT_PRODUCT by (1/3, 1/3, 1/3) follows it, so no color output is
linked into a float input, where Blender would convert by its luminance (0.2126, 0.7152, 0.0722 in EEVEE and Cycles,
4.2 to 5.2). A vector socket (Adjust, Tint, an image's Output), which Blender already averages, gets the same node,
so every float graph ends the same way. Measured on V-Ray 5.2 (bead maxdrop-em3.42, stripes of pure red, green,
blue, yellow, cyan and magenta): a Mix mask, a VRayMtl reflection glossiness map and an opacity map each give 1/3
for red, green and blue and 2/3 for the others, where the luminance gave 0.21, 0.72 and 0.07. The same rule, not
measured, for a metallic map, a layer or Composite mask, a bump height (3ds Max's own mono value is that mean) and
Corona's materials. A Multiply of two maps in a float graph is the product of their means, not the mean of their
product: measured on V-Ray 5.2 (bead maxdrop-em3.124, an RGB Multiply as a Mix mask and a reflection glossiness map,
a CoronaMix Multiply as a Mix mask), red x green gives 1/9 (not 0) and yellow x cyan 4/9 (not 1/3).

Texture graphs (convert/texmaps/) become nodes, a node of the IR shared by several inputs once per material: Image
-> Image Texture (its image datablock reused per file and color space: one file used in two color spaces is two
datablocks; see Images below), with its placement as a Mapping node and a UV Map node for a map channel other than
1; Invert, Decode (a Gamma node of 2.2, a constant through the sRGB curve; a mean: the sRGB curve in Math nodes), Mix,
Multiply, Blend (Gamma nodes around a Mix node of its operation or Vector Math nodes), ColorCorrect (its rewiring as
Invert, the mean or Separate / Combine Color, then Hue/Saturation/Value for the hue, the saturation in HSL (Math
and Vector Math nodes), Bright/Contrast, gain, Gamma (a Vector Math ABSOLUTE before it with magnitude)), Composite
(per layer its blend at factor 1, then a Mix by opacity x mask), Facing (Layer Weight Facing, Fresnel, or the
Geometry node's Normal . Incoming), Checker (its placed UV through Separate XYZ, FLOOR, ADD and WRAP: 0 or 1),
Noise (the object's coordinates through a Mapping node, a Noise Texture, a fold for turbulence, a Map Range),
Remap (Float Curve, its points straight between them, not clipped; the Mix it
drives does not clamp its factor), Smoothstep (Map Range SMOOTHSTEP, or a step: 1 - LESS_THAN), Adjust (a map's
Output, as an image's), Tint (Separate Color, three scales, two adds), NormalMap (Normal Map node, flips through
Separate / Combine Color), Bump (Bump node). A texture file that was not found (or does not load) keeps its Image
Texture node, without an image and not connected. The texture lookup (convert.textures) reports a file not found by
name; the builder reports a file that does not load. The graph above the node carries on without it (a Mix gives its
other side, a normal map without its image nothing) and an input left without a map keeps the IR's value. An empty
image node renders black in EEVEE and magenta in Cycles, and in a normal or alpha input it would wreck the shading
or hide the object.

Placement, the 3ds Max convention (StdUVGen: scaled and turned about the map's center, offset in UV fractions):
sample = R(u, v, w angles) S(tiling) (uv - 0.5 - offset) + 0.5, one Mapping node (POINT): uv_transform(). Per axis
the map mirrors (mirror on, which tiles too: it wins over tile), tiles or clips (repeat_axes()). A mirrored axis
shows two copies per tile, the second one mirrored: the sample, on the image's axis after the turn, is doubled (a
Vector Math MULTIPLY: mirror_scale()) and ping-ponged with period 2 (3ds Max 2020, measured: Bitmap and CoronaBitmap,
with and without a crop). Crop: that brought into the 0..1 cell per axis as the map repeats there (repeat_cell:
wrapped for tile, ping-ponged for mirror, outside the image for neither), then a Mapping POINT into the cropped
rectangle (TEXTURE, out of it, for a placed image). Without a crop Blender's one extension serves when both axes
repeat alike; otherwise the same per-axis nodes over the whole image (extension()). Where an axis repeats, what
clips (a clipped axis, a placed image's rectangle) is a mask on the image's Color and Alpha under EXTEND, not the
CLIP extension, which fades the border half-texel toward black at every tile and mirror line (clip_axes()).
That black is kept under a normal map too: 3ds Max renders the area outside a clipped Bitmap under Normal Bump or
VRayNormalMap exactly as a black normal image, skewed, not flat (V-Ray 5.2 and scanline, maxdrop-em3.137).
Map channel 0 (the vertex color as UVW) has no UV layer: such a map is drawn on channel 1 and reported.
A texture file that holds no image (empty, or not starting as its format does: image_has_data) is reported and
left out as one that does not load. A material whose build raises is removed again and reported: its slot stays
empty.
Alpha: Material.surface_render_method only, BLENDED for a constant alpha below 1, DITHERED for an alpha map; a
volume-only material keeps the default (no surface: Medium above).

Images: an image already in the file (an earlier import's, or the user's) is reused for the same file and color
space when it is still that file: a local image (no library), source FILE, not packed, not modified (is_dirty
False), its alpha mode the one a load gives (_load_alpha_mode), and its path absolute or the .blend saved (a
relative path of an unsaved file has no folder to resolve against). Its color space is never changed:
images.load(check_existing=True) would hand back an image of that file in any color space, and setting ours on it
would recolor whatever already uses it. A linked image is left out: its path is relative to its library and it goes
away when the user drops the link. Otherwise the file is loaded anew. A reused image keeps the pixels Blender read
before: a file changed on disk since shows once the image is reloaded.
"""

import collections
import os
import traceback

import bpy
from mathutils import Euler, Matrix, Vector

from ... import compat
from ...convert import colors
from ...convert import scene as convert_scene
from ...convert import texmaps as tx

from .sockets import (
    SPECULAR_LEVEL, TWIN_LABEL, WEIGHT_LABEL, MIRROR_LABEL, MIRROR_INPUTS, REFRACTION_LABEL, TIR_LABEL, TIR_FRESNEL,
    CLIP_LABEL, MAX_LAYER_DEPTH, SRGB_CURVE_COLUMNS, VOLUME_VIEWPORT_ALPHA, VOLUME_BOUNCES, X_STEP, Y_STEP, COLOR,
    FLOAT, BLEND_OPS, NON_NEGATIVE_BLENDS, BLEND_TYPES, _EPS, MISSING, uv_transform, repeat_axes, mirror_scale,
    per_axis, clip_axes, extension, _SIGNATURES, _targa, _SIGNED, image_has_data, uv_layer_name, _mean, _on, _as,
    _default, _in, _out,
)
from .builder import MaterialBuilder, _PREMUL_ON_LOAD, _input_colorspaces, _load_alpha_mode, _key
from .tree import _volume_only, _Tree
from .surface import _Surface
from .textures import _Textures
from .map_nodes import _MapNodes
