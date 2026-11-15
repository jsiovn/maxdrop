# V-Ray material rules (maxdrop-arp.3) Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `maxdrop/convert/materials.py`: pure functions from a material's parameters (reader `MtlBase`) to a
renderer-neutral `MaterialIR` in linear color, for VRayMtl, the wrappers, VRayLightMtl, VRayFastSSS2 and the two
car-paint classes; an unknown class gives a grey material that keeps its name.

**Architecture:** A `MaterialConverter(graph, meters)` over a `reader.materials.MaterialGraph` peels wrappers
(`peel(index)`), dispatches on `(superclass, ClassId)` to one rule per class (`RULES`, a dict later beads extend:
Standard, Physical, Multi/Sub in maxdrop-arp.4) and caches one `MaterialIR` per Max material object index. Each
input of the IR is an `Input(value, map)`: a value (linear color or float) and an optional `MapRef(index, amount,
invert)` to the map object; maxdrop-arp.5 turns a `MapRef` into a texture graph. `ConvertStats` counts peels and
unknown classes for the report (maxdrop-arp.8). No bpy, no mathutils.

**Tech Stack:** Python 3.11 stdlib (dataclasses, collections, math), unittest.

---

## Facts this plan rests on

- VRayMtl parameter ids: `docs/FORMAT.md` (block 1 basic, 2 BRDF, 3 options, 4 maps; map / on / multiplier ids).
- Wrapper, light, SSS and car-paint ids and ClassIDs: a probe run on 2026-11-16 in this machine's 3ds Max 2020 +
  V-Ray 5.2 (`3dsmaxbatch.exe` with a scratch MAXScript reading `IParamBlock2` through the SDK's .NET wrapper, as
  `tools/oracle/dump_scene.ms` does). Every one is in block 0 of its class:

  | Class | ClassID (A, B) | Parameters |
  |---|---|---|
  | VRayLightMtl | `0x7CCF263E, 0x3F5B39B9` | 0 color, 1 multiplier, 2 texmap, 3 texmap_on, 5 opacity_texmap, 6 opacity_texmap_on |
  | VRayFastSSS2 | `0x3F2C5FAA, 0x750008BC` | 26 diffuse_color, 27 / 28 texmap_diffuse_color (on), 36 diffuse_amount, 2 sub_surface_color, 0 scatter_radius, 22 scale, 31 IOR, 40 specular_color, 51 specular_glossiness, 3 / 4 texmap_bump (on), 85 / 86 texmap_opacity (on) |
  | VRayCarPaintMtl | `0x38312C74, 0x47280883` | 0 base_color, 1 / 2 texmap_base_color (on), 4 base_reflection, 8 base_glossiness, 27 coat_color, 31 coat_strength, 39 coat_glossiness, 55 / 56 texmap_base_bump (on) |
  | VRayCarPaintMtl2 | `0x56BC47E2, 0x03E008C7` | 0 base_color, 1 / 2 texmap_base_color (on), 4 base_reflection, 8 base_glossiness, 27 coat_color, 31 coat_amount, 39 coat_glossiness, 81 coat_ior, 54 / 55 texmap_base_bump (on) |
  | VRayOverrideMtl | `0x15D20E6B, 0x54E217EB` | 0 baseMtl, 2 giMtl, 4 reflectMtl, 6 refractMtl, 8 shadowMtl (getSubMtl order) |
  | VRayMtlWrapper | `0x409517DF, 0x3A5F44B6` | 0 baseMtl |
  | DoubleSided | `0x00000210, 0` | 0 material1 (facing), 1 material2 (back) |
  | Shellac | `0x46EE536A, 0` | 0 shellacMtl1 (base), 1 shellacMtl2 |
  | VRay2SidedMtl | `0x6066686A, 0x11731B4B` | 0 frontMtl, 1 backMtl (fixture) |
  | VRayBlendMtl | `0x3DA0041B, 0x0F436E31` | 0 baseMtl, 1 coatMtl table (fixture) |
  | Shell Material | `0x00000255, 0` | 1 renderMtlIndex, 2 originalMaterial, 3 bakedMaterial (fixture) |

  The local V-Ray 5.2 does have VRayCarPaintMtl2 (the bead note said otherwise). Only the classes of the
  fixtures (VRayMtl, VRay2SidedMtl, VRayBlendMtl, Shell) are verified against a file; the others are probe ids,
  tested on synthetic parameters. `reader/classids.py` takes a class only with a fixture, so the probe classes'
  ClassIDs live in `convert/materials.py`, marked unverified by a file.
- Rules source (read-only): `f_export_scene.ms` `ocbaby_exsChannels` 611-667, `ocbaby_exsUnwrap` 587-606.
  `ocbaby_exsLum` is the channel mean.

## The rules

Colors: every swatch goes through the sRGB transfer function to linear (3ds Max swatches are display-referred;
maxdrop-arp.4 may refine with the scene's gamma). `lum(c)` = mean of the linear channels (the source's mean,
taken in linear). Floats from the file are checked finite; a non-finite or missing value takes V-Ray's default.

VRayMtl (ported):
- base color = diffuse (1); map 100 if 150, amount 200 / 100.
- g = reflection_glossiness (3); roughness = g if brdf_useRoughness (89, block 2) else 1 - g; map 104 if 154,
  amount 204 / 100, invert = not useRoughness. texmap_roughness (113) is the diffuse roughness: not used.
- metallic = reflection_metalness (91); map 119 if 169.
- specular = lum(reflection (2)); map 101 if 151.
- emission color = selfIllumination (81); map 117 if 167; strength = selfIllumination_multiplier (83) when the
  color is not black or the map is set, else 0.
- transmission = lum(refraction (5)); map 102 if 152; ior = refraction_ior (9); thin_walled = refraction_thinWalled
  (107).
- bump slot 103 if 153, amount 203 / 100: a VRayNormalMap there goes to `normal`, anything else to `bump`.
- alpha = 1 with opacity map 112 if 162, amount 212 / 100.
- coat: weight coat_amount (96), color coat_color (97), roughness from coat_glossiness (98) as for reflection,
  ior coat_ior (99).
- Added (native): glass base color: when transmission > 0, base color = diffuse * (1 - t) + refraction * t.
  Fresnel off (8 = 0) with a bright reflection (lum >= `METAL_REFLECTION` = 0.25 linear, about sRGB 137 grey):
  metallic = 1, base color = the reflection color (and its map).
- ior: refraction_ior when transmission > 0 or reflection_lockIOR (65) is on, else reflection_ior (63).
- DROPPED: gamma-1.0 copies, alpha flattening, zeroed map angles, specular < 0.05 -> roughness 1.

VRayLightMtl: base black, roughness 1, specular 0, emission color 0, strength 1, map 2 if 3; alpha map 5 if 6.
VRayFastSSS2: base 26 (map 27 if 28); roughness 1 - 51; specular lum(40); subsurface weight 1 - diffuse_amount
(36), color 2, radius scatter_radius (0) * scale (22) * meters; ior 31; bump 3 if 4; alpha map 85 if 86.
Car paint (both): base 0 (map 1 if 2); roughness 1 - 8; metallic 1 (ported); specular base_reflection (4); coat
weight 31, color 27, roughness 1 - 39, ior 81 (CarPaint2) or 1.5; bump 55 if 56 (CarPaint) / 54 if 55 (CarPaint2).

Wrappers (ported): peel to the first set sub-material in getSubMtl order (table above), Shell to the sub at
renderMtlIndex (0 original, 1 baked). Stop at Multi/Sub-Object (maxdrop-arp.4 converts it) and at any non-wrapper.
Depth guard 8 and a cycle guard; a wrapper whose sub-material is missing or not a material ends the peel with no
material: the IR is the grey material with the wrapper's name, and an issue. Each wrapper object peeled counts
once in `stats.peeled[class name]`.

Unknown class: grey (128/255 sRGB -> linear) with the material's name, `unknown=True`, counted in
`stats.unknown[class name]` (class directory name if known to `classids`, else `ClassID(0x..., 0x...)`).

## Chunk 1: IR, helpers, VRayMtl

### Task 1: IR and helpers

**Files:** Create `maxdrop/convert/materials.py`; test `tests/unit/test_convert_materials.py`.

- [ ] Write tests: `srgb_to_linear` (0, 1, 0.5 -> 0.214041, below the 0.04045 knee), `lum`, `Input` defaults, a
  NaN parameter takes the default.
- [ ] Implement `MapRef`, `Input`, `MaterialIR` (dataclasses), `ConvertStats`, `srgb_to_linear`, `linear_color`,
  `lum`, and the parameter readers (`_num`, `_color`, `_flag`, `_map`).
- [ ] Run `python -I -m unittest tests.unit.test_convert_materials -v` -> PASS.

### Task 2: VRayMtl rule

- [ ] Tests on vray_basic: the IR equals hand-computed expectations for every channel (base color glass mix,
  roughness with useRoughness on, metallic = 1 and base = reflection by the Fresnel-off rule, specular, emission,
  transmission, IOR, thin-walled, alpha, coat); synthetic parameters for each rule alone (useRoughness off,
  Fresnel on, dark reflection, maps on / off, normal map in the bump slot).
- [ ] Implement `vray_mtl(m, conv)`; register in `RULES`.

## Chunk 2: wrappers, other classes, unknown

### Task 3: peel

- [ ] Tests: vray_wrappers: FixtureTwoSided -> FixtureFront, FixtureBlend -> FixtureBlendBase, FixtureShell ->
  FixtureShellOriginal, FixtureMulti -> itself; `stats.peeled` counts each wrapper once. Synthetic: Shell with
  renderMtlIndex 1, empty first slot -> second, Override / MtlWrapper / DoubleSided / Shellac, a cycle, depth > 8,
  an empty wrapper -> grey with the wrapper's name.
- [ ] Implement `WRAPPERS`, `peel`, `convert`.

### Task 4: VRayLightMtl, FastSSS2, car paint, unknown

- [ ] Synthetic tests per rule with hand-computed expectations; unknown class -> grey keeps its name, counted.
- [ ] Implement the rules; commit.

## Verification

**Working directory:** `D:\www\maxdrop`; no Blender needed (convert/ never imports bpy).

1. `python -I -m unittest discover tests` -> `OK` (the new test module included; vray_basic IR equals the
   hand-computed expectations, each vray_wrappers wrapper resolves to its expected sub-material, an unknown class
   gives the grey material).
2. `tests/unit/test_reader_no_bpy.py` (or the equivalent guard) still passes: `convert/materials.py` imports
   neither bpy nor mathutils.
3. Repo-local `build-and-test` skill: `build.ps1`, then the register and import smoke tests on Blender 4.2.23,
   4.5.16 and 5.2 (headless, isolated profile). The add-on does not call the new module yet, so the smoke tests
   guard against packaging breakage only.

**Success criteria:** all three steps pass; no commercial name or user path in the diff.
