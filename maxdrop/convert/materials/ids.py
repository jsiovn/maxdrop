# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The material rules' limits, wrapper tables, parameter ids and constants."""
from ...reader import chunks, classids
from ..texmaps.ids import DEFAULT_METERS as DEFAULT_METERS  # meters per system unit of a scene that does not say


ChunkError = chunks.ChunkError

MAX_PEEL = 8
METAL_REFLECTION = 0.25  # mean linear reflection (about sRGB 137 grey) above which Fresnel off means metal (VRayMtl: a
# swatch below 1 without a map is the tinted mirror instead, MaterialIR.mirror_color)
CORONA_EDGE_DEFAULT = 0.75  # CoronaPhysicalMtl's edgeColor as created (grey): not reported
CORONA_METAL_IOR = 10.0  # a CoronaLegacyMtl Fresnel IOR from which a bright reflection is a metal (made with 999)
CORONA_SPECULAR_F0 = 0.08  # CoronaPhysicalMtl IOR mode 1: F0 = 0.08 x the specular level held by an IOR parameter
CORONA_MAX_F0 = 0.25  # CoronaPhysicalMtl: no IOR reflects more than IOR 3 does (Corona 12 renders, both IOR modes)
CORONA_MAX_IOR = 3.0  # the IOR of F0 CORONA_MAX_F0: a non-refracting base IOR above it reflects as it (mode 0)
# CoronaLegacyMtl glossiness with PBR mode off (402) -> the roughness (1 - the PBR-mode glossiness) whose highlight
# Corona 12 renders alike, at glossiness 0, 0.05 ... 1 (maxdrop-em3.115: a mirror under a small emitter, the highlight
# profiles matched). From 0.35 up the profiles agree; below 0.3 no PBR-mode glossiness has the same lobe (the closest)
CORONA_LEGACY_GLOSS = (0.618, 0.617, 0.612, 0.600, 0.5745, 0.525, 0.4555, 0.386, 0.324, 0.272, 0.2295, 0.1945, 0.165,
                       0.140, 0.1185, 0.099, 0.082, 0.0665, 0.051, 0.035, 0.0)
MAX_MEDIUM_DENSITY = 1e6  # a medium coefficient per meter at most: a black channel or a distance near 0 (1 um: opaque)
MAX_ANISOTROPY = 0.99  # a Corona directionality past it is clamped: Blender's Henyey-Greenstein takes -1 < g < 1
GREY_SRGB = 128 / 255  # the grey of a material without a rule: MaxDrop's own, not a swatch

# wrapper ClassId -> its sub-material parameters (block 0) in getSubMtl order; a table parameter gives each element.
# A class of WRAPPER_STOPS is peeled to its first slot or not at all: its later slots are never read
WRAPPERS = {
    classids.VRAY_2SIDED_MTL: (0, 1),  # frontMtl, backMtl
    classids.VRAY_BLEND_MTL: (0, 1),  # baseMtl, coatMtl (table)
    classids.VRAY_OVERRIDE_MTL: (0, 2, 4, 6, 8),  # baseMtl, giMtl, reflectMtl, refractMtl, shadowMtl
    classids.VRAY_MTL_WRAPPER: (0,),  # baseMtl
    classids.DOUBLE_SIDED_MTL: (0, 1),  # material1 (facing), material2 (back)
    classids.SHELLAC_MTL: (0, 1),  # shellacMtl1 (base), shellacMtl2
    classids.CORONA_LAYERED_MTL: (1000, 1001),  # baseMtl, layers (table): a wrapper only without a layer on
    classids.CORONA_RAY_SWITCH_MTL: (1603, 1600, 1601, 1602),  # directMtl, giMtl, reflectMtl, refractMtl
    classids.CORONA_SELECT_MTL: (312,),  # materials (table): the one at selected (313, zero-based)
}
# wrapper ClassId -> (its first slot's name, the slot's on switch or None, what the renderer shows): a wrapper whose
# first slot is empty (or switched off) is not peeled to the next one, the renderer draws no sub-material there
# (maxdrop-em3.136, maxdrop-6n0.6.4). VRayOverrideMtl's switches (1, 3, 5, 7, 9) and Double Sided's (2, 3) are ignored:
# V-Ray 5.2 renders their sub-materials switched off all the same. Shellac's empty base renders its coat (V-Ray and
# the scanline): it peels on; VRayBlendMtl's renders its coats over nothing: it peels on with an issue (_sub)
WRAPPER_STOPS = {
    classids.VRAY_OVERRIDE_MTL: ("base material", None, "V-Ray renders it black"),
    classids.DOUBLE_SIDED_MTL: ("facing material", None, "V-Ray renders that side not at all, the scanline black"),
    classids.VRAY_2SIDED_MTL: ("front material", None, "V-Ray renders that side not at all"),
    classids.CORONA_RAY_SWITCH_MTL: ("direct material", 1613, "Corona renders nothing to the camera"),
}
DOUBLE_SIDED_FACING_ON = 2  # map1Enabled
CORONA_SELECT_LIST, CORONA_SELECT_INDEX = 312, 313
SHELL_RENDER_INDEX, SHELL_SUBS = 1, (2, 3)  # renderMtlIndex; originalMaterial, bakedMaterial
# CoronaLayeredMtl, block 0: 1000 baseMtl, 1001 layers, 1002 amounts, 1003 mixmaps (masks), 1004 layersOn, 1005 masksOn,
# 1006 maskAmounts (each a table, one element per layer)
CORONA_BASE, CORONA_LAYERS, CORONA_AMOUNTS, CORONA_MASKS, CORONA_LAYERS_ON, CORONA_MASKS_ON, CORONA_MASK_AMOUNTS = (
    1000, 1001, 1002, 1003, 1004, 1005, 1006)
MAX_LAYERS = 16  # layers mixed over a CoronaLayeredMtl's base (Corona offers 10)
MAX_LAYER_BSDFS = 64  # Principled BSDFs one material may draw, its layers' layers counted at each use
# (each may come with a twin without reflection, the reflection weight of build/materials/: at most twice as many nodes)
MAX_COMPLEX_IOR = 100.0  # n and k of a complex IOR are held within 0..this

LUMENS_PER_WATT = 683.0  # luminous efficacy at 555 nm: cd/m2 -> W/(m2 sr)

# Multi/Sub-Object, block 0: materialList, mapEnabled, materialIDList (zero-based)
MULTI_MATERIALS, MULTI_ENABLED, MULTI_IDS = 0, 1, 3
