# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material rules: a 3ds Max material's parameters turned into a renderer-neutral MaterialIR in linear color.

    conv = MaterialConverter(graph, texmaps=tex, swatches=sw)   # graph: reader.materials.MaterialGraph; tex: an
                                        # optional texmaps.TexmapConverter, which fills ir.textures; sw: the
                                        # colors.Swatches rule (default: tex's, else read from graph's scene);
                                        # pass tex's own rule, or none: the two must agree
    ir = conv.convert(node.material)    # MaterialIR (wrappers peeled); None for no material or not a material
    ir.base_color.value, ir.base_color.map        # linear RGB, MapRef(index, amount, invert, scale) or None
    conv.material_for(index, mat_id)    # the MaterialIR a face with that zero-based material ID renders with
                                        # (Multi/Sub-Objects resolved), None for an empty slot
    slots = assign(desc, node_materials(scene, desc), conv)   # Slots {mesh key: MeshSlots}, for build/objects.py
    slots.curves                        # {curve key: MeshSlots}: the slots of each curve with a material, indices
                                        # per spline
    conv.peel(index)                    # (object index of the renderable material or None, reason)
    conv.stats.peeled, conv.stats.unknown, conv.stats.issues

Each input of a MaterialIR is an Input: a value (a linear RGB tuple or a float) and, when a map drives it, a
MapRef to the map object (the value is what the slot shows without it). With a TexmapConverter, ir.textures holds
the TextureGraphIR of each input a usable map drives (convert/texmaps/), its issues added to ir.issues. One
MaterialIR per Max material object index; a wrapper converts to the IR of the material it peels to, so every node
using either shares it.

Rules (the decisions of an earlier 3ds Max -> FBX exporter, without its FBX workarounds):

- VRayMtl: base color = diffuse; roughness = reflection glossiness g, or 1 - g unless brdf_useRoughness (a
  glossiness map is then inverted); metallic = reflection_metalness; specular = the mean of the linear reflection
  color (as in every rule, a reflection weight: 1 is the full Fresnel reflection at the IOR, which
  build/materials/ draws as Specular IOR Level 0.5, and a weight between 0 and 1 as a Mix Shader by it over a
  twin without reflection, so the whole curve scales as V-Ray scales it; with Fresnel on a white and a grey one
  match V-Ray 5.2 at every angle, measured in the maxdrop-em3.34 and maxdrop-em3.119 plans);
  emission = self-illumination color times its multiplier; transmission = the mean of the refraction color,
  ior and thin-walled from the refraction parameters; maps where their slot is on, with their multiplier as the
  amount; a normal map (VRayNormalMap, Normal Bump, CoronaNormal) in a bump slot is the normal input, any other
  map the bump input. Added here: a refracting material takes its base color from the refraction color (mixed by
  the transmission), and with Fresnel off a bright reflection (mean >= METAL_REFLECTION) beside a reflection map or
  with a channel of 1 or more makes the material a metal in the reflection color; below 1 and without a map it keeps
  the diffuse: V-Ray renders R_c + (1 - R_c) x the diffuse per channel (maxdrop-em3.153: 128 grey over 200 40 40
  gives 0.8925 0.5801 0.5801 facing the camera, the metal 0.502), drawn as the mirror below by the brightest channel
  max(R), tinted R / max(R) (mirror_color): R_c + (1 - max R) x the diffuse, V-Ray's for grey or a black diffuse and
  between the metal and V-Ray in every channel otherwise (maxdrop-6n0.6.16: 230 128 26 over 40 80 200 renders
  0.9175 0.6582 0.8060, the copy 0.917 0.533 0.179, the metal 0.900 0.503 0.102; no Mix of two closures meets V-Ray
  when max(R) + max_c((1 - R_c) d_c) > 1); a dimmer colored swatch stays the white mirror by its mean (102 51 13 over
  grey: V-Ray 0.701 0.602 0.527, white 0.609 0.611 0.609, tinted 0.701 0.501 0.352), so a saturated swatch's weight
  jumps from its mean to its brightest channel at METAL_REFLECTION (not measured near it); outside the metal rule a
  constant metalness m only dims the diffuse: V-Ray renders R_c + (1 - m)(1 - R_c) d_c (maxdrop-6n0.6.39: 128 grey
  over 40 80 200 at m 1 0.502, at m 0.5 0.541 0.580 0.697), so Metallic 0 and the diffuse swatch times 1 - m before
  the swatch rule, its map by the rule's factor (MapRef.scale, left out at m 1; with the gamma off and an amount below
  1 the decoded mix, as a Standard's Diffuse Level: gamma off not rendered); a metalness map and a refracting
  material (a refraction swatch or map) as before, not measured; beside a reflection map only the swatch's
  share counts (its mean times 1 - the map amount): a map at full amount hides the swatch, so it never makes a metal
  (the map itself is not judged), a map at 0 % amount is left out (the swatch alone, as V-Ray renders it).
  Fresnel off sets fresnel False; outside the metal rule the weight (a swatch below 1, or a reflection map such as the
  black to white Falloff) is then reflected as it is at every angle, which build/materials/ draws as a metal of
  mirror_color (white, or the tint above) mixed by it over the material without reflection (V-Ray 5.2: a 0.2 swatch
  reflects 0.200 facing the camera, maxdrop-em3.120).
  The Fresnel IOR is the refraction IOR when the material refracts or locks the IOR, else the reflection IOR.
- VRayLightMtl -> emission only; VRayFastSSS2 -> base + subsurface; VRayCarPaintMtl / VRayCarPaintMtl2 -> a metal
  base + coat (VRayCarPaintMtl's coat_strength is the coat's reflectance at normal incidence: a full coat whose
  IOR gives that reflectance; VRayCarPaintMtl2's coat_amount is the coat weight). Their maps where their slot is on,
  with their multiplier as the amount, as VRayMtl's; VRayFastSSS2's specular is specular_amount times the mean of the
  linear specular color.
- Standard: the colors come from its shader (ids per shader class in SHADERS; Metal is a metal, Strauss has a
  metalness and no specular level: specular 1, the IOR's own Fresnel); base = diffuse (Anisotropic, Multi-Layer,
  Oren-Nayar-Blinn, Translucent: the swatch times the Diffuse Level, before the swatch rule; a diffuse map times
  the level as the swatch rule makes it (MapRef.scale); a Diffuse Level map replaces the level by its amount,
  ir.diffuse_level, maxdrop-em3.150); roughness = 1 -
  glossiness; specular = specular level times the mean of the linear specular color; a missing or unread diffuse,
  glossiness or specular level takes its shader's default (SHADER_DEFAULTS); alpha = opacity; self-illumination: its
  color at strength 1, or the diffuse as set (not scaled) at the amount; two-sided flag; map slots with their
  amounts where switched on, at the shader's own map channels (STD_SLOTS; Strauss: its metalness map drives the
  metallic; map, switch and amount from the material's Texmaps object, as 3ds Max answers them, block 3's tables
  only without one) (a glossiness map inverted; the specular level map drives the specular, else the specular color
  map); a map in the reflection slot makes the specular at least that slot's amount (the map is an environment: not
  used).
- Physical Material: base = base color times base weight; roughness (1 - it with roughness_inv); metalness;
  specular = reflectivity times the mean of the linear reflection color; transparency is the transmission and
  mixes the transparency color into the base, as for VRayMtl; IOR, thin-walled; emission color at emission
  weight times luminance / LUMENS_PER_WATT (cd/m2 to Blender's W/(m2 sr)), a weight map standing for the
  weight; coating; map slots where on.
- CoronaPhysicalMtl: base = base color times base level; roughness, or 1 - it in glossiness mode (every roughness of the
  material, a map then inverted); metallic from the metalness mode; transmission = refraction amount, the base mixed
  toward white (thin mode: the thin absorption color) by it; IOR, thin mode; alpha = the mean of the stored opacity
  color (mono_swatch) times its level; emission color at its level; clearcoat amount, IOR, roughness and absorption
  color; sheen amount, color and roughness; SSS amount, radius (world units, in meters) and scatter color (the
  per-channel radius); a metal with a complex IOR takes the F0 of its n and k as its base color; maps where on, their
  amounts fractions. Specular 1, the IOR's own Fresnel (the material has no reflection level); in IOR mode 1 the base
  and clearcoat IORs are specular levels (F0 = 0.08 x level, at most 0.25); in the other modes a base IOR of a
  material that does not refract is taken as Corona reflects it (below 1 its reciprocal, at most 3). Translucency in
  thin mode (Corona ignores it otherwise), maps in the volumetric slots, single bounce, a metal edge color other than
  the default, an IOR mode other than 0 and 1, a refracting material's base IOR outside 1..3 and maps in the sheen
  and SSS slots are named issues. Volumetric absorption and scattering: a
  medium (corona_medium) inside a solid that refracts (no medium in thin mode: Corona 12 renders none there).
- CoronaLegacyMtl (CoronaMtl): diffuse, reflection, refraction, opacity and self-illumination colors times their
  levels, the maps in the first four slots too (MapRef.scale, Corona's documentation; a level of 0: no map);
  specular = the mean reflection; roughness = 1 - glossiness, with PBR mode off the measured
  CORONA_LEGACY_GLOSS (corona_legacy_roughness; a glossiness map stays inverted); transmission and the glass
  base color as for VRayMtl, the IOR as well (refraction IOR when it refracts, else the Fresnel IOR); a Fresnel IOR
  of CORONA_METAL_IOR or more with a bright reflection (as METAL_REFLECTION) is a metal in the reflection color;
  beside a reflection map only the swatch's share counts, as for VRayMtl (its mean, the level included, times 1 - the
  map amount; Corona's documentation has the level multiply the color and the map alike, so the map is not judged);
  SSS as the physical material's; absorption and scattering as a medium (corona_medium; media mode 1, inside a solid
  that refracts). A glossiness map with PBR mode off, translucency, media mode 0 and the medium's maps are named issues.
- CoronaLightMtl -> emission (color, intensity, map) and its opacity map.
- CoronaSkinMtl -> one Principled layer: skin color times level, its three SSS layers as one (weighted mean radius
  times the radius scale, weighted mean color), the first reflection as specular, roughness and IOR, opacity, bump.
- CoronaHairMtl -> one Principled layer (Corona 12 renders on a mesh, maxdrop-em3.164): the base color Corona gives a
  mesh of its melanin, pheomelanin and tint (hair_color) times its transmission color, its diffuse color mixed in;
  roughness = 1 - glossiness, IOR, opacity, bump. Its other maps (the tint map too) and randomizeMelanin are named
  issues.
- CoronaShadowCatcherMtl -> the grey material marked shadow_catcher: an object whose every slot holds one is a shadow
  catcher (build/objects.py); a backplate map and a reflection are named issues.
- CoronaVolumeMtl -> no surface (alpha 0) and its medium (corona_medium): absorption, scattering, directionality and
  emission; its maps and single bounce are named issues.
- Corona media (corona_medium, Corona 12 renders, maxdrop-em3.163): the absorption color is the transmission at its
  distance (world units), per channel (sigma_t = -ln(color) / distance); the scattering color is the albedo of that
  extinction; the directionality a Henyey-Greenstein g; emission its color over its distance per unit length.
- CoronaScannedMtl, CoronaSlicerMtl -> the grey material with a named issue (CORONA_GREY), not counted as a class
  without a rule.
- CoronaLayeredMtl with a base and a layer that is on -> the base's IR with its layers (Layer: IR, amount, mask
  with its mask amount; at most MAX_LAYERS), which build/materials/ mixes over it; the weight is the amount times
  lerp(1, mask, mask amount), as Corona 12 renders it (maxdrop-em3.115: amount 0.6, mask 0.25, mask amount 0.5 gives
  0.375), the mask taking the value the same map gives a color input.
- VRayBlendMtl with a base and a coat that is set and on -> the base's IR with those coats as layers (vray_blend_mtl:
  the same limits), mixed over it or, in additive mode, added (Layer.mode ADD); the weight is the blend color as a
  swatch on a mask (the scene's rule on the mean of its channels), with a blend map that and the map mixed by the map
  multiplier (a MASK graph). Not measured against V-Ray (maxdrop-o53.3.2); a colored blend color is an issue.
- VRay2SidedMtl with a front (not a Multi/Sub-Object itself) whose translucency is not black, or with a back material
  set, on and not the front -> the front's IR with translucency (vray_2sided_mtl: the translucency color as a swatch
  on a mask, with a translucency map that and the map mixed by its multiplier, a DATA graph) and translucency_color
  (the back's base color, else the front's), which build/materials/ draws as a Translucent BSDF mixed in by it; the
  back material a Layer (BACK) shown on back faces with the same translucency in the front's color. V-Ray's
  documented rule, not measured (maxdrop-o53.3.2); a colored translucency color is an issue.
- Wrappers (VRay2SidedMtl with a black translucency and no back material shown, VRayBlendMtl without a coat set and
  on, VRayOverrideMtl, VRayMtlWrapper, Double Sided, Shellac, CoronaLayeredMtl without a base or without a layer on:
  base, then its layers that are on; CoronaRaySwitchMtl: direct, GI, reflect, refract) -> the first set sub-material
  in 3ds Max's getSubMtl order (VRayOverrideMtl's and Double Sided's whatever their switches say: V-Ray 5.2 renders the base and the facing material switched off all the
  same, measured in maxdrop-em3.136; the scanline renders a Double Sided side switched off black: an issue for the
  facing one). Where the renderer draws no sub-material for an empty first slot the peel ends there, with a reason
  (WRAPPER_STOPS, rendered in maxdrop-em3.136 and maxdrop-6n0.6.4): VRayOverrideMtl's base (V-Ray renders black),
  Double Sided's facing material and VRay2SidedMtl's front (that side is not rendered), CoronaRaySwitchMtl's direct
  material, empty or switched off (Corona renders nothing to the camera). An empty VRayBlendMtl base gives its first
  set coat that is on and an issue (V-Ray renders the coat over nothing); an empty Shellac base its coat, as rendered;
  CoronaSelectMtl -> its selected material (zero-based: the default is 0); Shell Material -> its render sub-material.
  Peeling stops at any other class (a Multi/Sub-Object included), at most MAX_PEEL wrappers deep; each wrapper object
  peeled counts once.
- Multi/Sub-Object: entry k has the material ID materialIDList[k] (zero-based, as the faces store it), the
  material materialList[k] and the switch mapEnabled[k]; the first entry with an ID wins. A face ID without an
  entry wraps as 3ds Max renders it: to ID modulo (the highest ID of the list + 1), every entry counted. A face ID
  that still has no entry, or whose entry is switched off or empty, gets no material (an empty slot; 3ds Max renders
  it black). A Multi/Sub-Object inside a wrapper or inside another Multi/Sub-Object (which looks up the face's own
  ID and wraps it by its own list) resolves the same way, at most MAX_PEEL deep. convert() of one (a caller
  without face IDs) gives the material of its first entry that is on and set.
- Any other class -> a grey material that keeps its name (specular 1, the IOR's own Fresnel), counted by class name.

The slots of a mesh (assign): its distinct face IDs, each keyed by the materials its users (the nodes sharing the
mesh) get for that ID; one slot per key, in ID order, faces remapped to their slot. A material that is not a
Multi/Sub-Object gives one slot; an empty key (no material) is a slot only beside others. A curve (a shape node
built as a curve) gets its slots the same way from its splines' material IDs (one per spline: its first segment's,
convert.scene.SplineDescription.material), each spline remapped to its slot; none when no user has a material. A
spline whose segments have other IDs too is drawn with its first segment's material: an issue on the curve's first
user (SceneDescription.issues) when a user gets another material for one of those IDs.

Colors are 3ds Max swatches, clamped to 0..1 and made linear by the scene's swatch rule (convert/colors.py): the
value itself when the scene was saved with the gamma on (or does not say), the sRGB curve when it was off. A color
that stands for a number (the Corona opacity colors) is the mean of the swatch as stored, whatever the gamma, as V-Ray
5.2 renders a swatch on a data input (maxdrop-em3.122). Corona 12 renders an opacity color as stored in both modes
too, but per channel (maxdrop-6n0.6.35: CoronaLegacyMtl and CoronaPhysicalMtl, grey 64 -> 0.251, red -> 1 0 0),
which a float alpha cannot hold: a colored one keeps the mean and is an issue.
A missing or non-finite parameter takes the class's default; an animated one its controller's value at frame 0
(convert/params.py: the converter's graph reads it so), the default where that cannot be had; an IOR is clamped to
1..100. The SSS radius is
in meters: VRayFastSSS2's scatter_radius is in centimeters whatever the system unit, multiplied by its scale (V-Ray's
documentation says both). VRayCarPaintMtl's coat_strength is, in V-Ray's documentation, the strength of the coat
reflections seen from the front; that Fresnel gives the other angles is this rule's reading.
Parameter ids: docs/FORMAT.md for the classes of the fixtures (the Corona ones: Corona 12; the V-Ray ones: V-Ray 5.2);
standard_shaders sets every shader's ids and the Physical Material's maps; standard_maps a map in every Standard map
slot each shader reads.
No bpy, no mathutils.
"""

import collections
import dataclasses
import math

from ...reader import chunks, classids, pblock, units
from ...reader import materials as reader_materials
from ...reader import scene as reader_scene
from ...reader.classdir import ClassId
from ...reader.errors import MaxFileError
from .. import colors, params
from .. import texmaps as _texmaps
from ..params import finite as _finite, flag as _flag, num as _num

from .ids import (
    ChunkError, MAX_PEEL, METAL_REFLECTION, CORONA_EDGE_DEFAULT, CORONA_METAL_IOR, CORONA_SPECULAR_F0, CORONA_MAX_F0,
    CORONA_MAX_IOR, CORONA_LEGACY_GLOSS, MAX_MEDIUM_DENSITY, MAX_ANISOTROPY, GREY_SRGB, WRAPPERS, WRAPPER_STOPS,
    DOUBLE_SIDED_FACING_ON, CORONA_SELECT_LIST, CORONA_SELECT_INDEX, SHELL_RENDER_INDEX, SHELL_SUBS, CORONA_BASE,
    CORONA_LAYERS, CORONA_AMOUNTS, CORONA_MASKS, CORONA_LAYERS_ON, CORONA_MASKS_ON, CORONA_MASK_AMOUNTS, MAX_LAYERS,
    MAX_LAYER_BSDFS, MAX_COMPLEX_IOR, DEFAULT_METERS, LUMENS_PER_WATT, MULTI_MATERIALS, MULTI_ENABLED, MULTI_IDS,
    VRAY_BLEND_BASE, VRAY_BLEND_COATS, VRAY_BLEND_COLORS, VRAY_BLEND_MAPS, VRAY_BLEND_MULTIPLIERS, VRAY_BLEND_ADDITIVE,
    VRAY_BLEND_COATS_ON, VRAY_BLEND_COLOR, VRAY_2SIDED_FRONT, VRAY_2SIDED_BACK, VRAY_2SIDED_BACK_ON, VRAY_2SIDED_MAP,
    VRAY_2SIDED_MAP_ON, VRAY_2SIDED_MULTIPLIER, VRAY_2SIDED_TRANSLUCENCY, VRAY_2SIDED_MULT_DIFFUSE,
)
from .ir import MapRef, DiffuseLevel, Input, Medium, MaterialIR, Layer, ConvertStats, MIX, ADD, BACK
from .values import (
    mean, class_name, _clamp01, _mix, _ior, ior_from_reflectance, _roughness, corona_legacy_roughness, _scene_meters,
    f0_from_complex_ior, class_label, MAX_CLASS_NAME,
)
from .converter import MaterialConverter
from .vray import vray_mtl, vray_light_mtl, vray_fast_sss2, _car_paint, vray_car_paint_mtl, vray_car_paint_mtl2
from .standard import (
    ShaderIds, _BLINN_IDS, SHADERS, ShaderDefaults, _BLINN_DEFAULTS, _GREY, SHADER_DEFAULTS, PHYSICAL, PHYSICAL_SWITCH,
    StdSlots, _BLINN_SLOTS, _ONB_SLOTS, STD_SLOTS, STD_SPECULAR_DEFAULT, _PartParams, _std_channels, _std_map,
    standard_mtl, physical_mtl,
)
from .corona import (
    _corona_amount_map, _corona_opacity, _unread_map, _subsurface, corona_physical_mtl, _corona_reflection_ior,
    _corona_ior, corona_legacy_mtl, corona_light_mtl, _num_tab, _flag_tab, corona_skin_mtl, HAIR_EUMELANIN,
    HAIR_PHEOMELANIN, HAIR_MELANIN, HAIR_PHEOMELANIN_SCALE, HAIR_TINT, HAIR_FLOOR, HAIR_SPECULAR, HAIR_PIGMENT,
    HAIR_PRINCIPLED_SPECULAR, HAIR_UNREAD, hair_color, corona_hair_mtl, corona_shadow_catcher_mtl, corona_medium,
    _corona_volume, _medium_issues, corona_volume_mtl, CORONA_GREY, corona_named_grey,
)
from .layered import corona_layered_mtl, vray_blend_mtl, vray_2sided_mtl
from .rules import RULES
from .slots import MeshSlots, shadow_catcher_users, Slots, node_materials, _group, _mixed, assign
