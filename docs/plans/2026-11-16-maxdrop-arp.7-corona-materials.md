# maxdrop-arp.7 Corona materials by parameter id Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CoronaPhysicalMtl, CoronaLegacyMtl (CoronaMtl), CoronaLayeredMtl, CoronaLightMtl and the maps
CoronaBitmap, CoronaNormal, CoronaColor and CoronaMix converted by parameter id into the MaterialIR /
TextureGraphIR of `convert/`, verified against five self-authored Corona 12 fixtures and their oracles.

**Architecture:** Rules added to the existing dispatch tables: `materials.RULES` (three material rules),
`materials.WRAPPERS` (CoronaLayeredMtl peels to its base, else its first set layer), `texmaps` (CoronaBitmap is an
Image like Bitmap, CoronaColor a Constant, CoronaMix a Mix / Multiply or peeled). ClassIDs verified by the fixtures
move into `reader/classids.py`. The builder needs no change: it already draws every node kind used.

**Tech Stack:** Python 3.11 syntax, standard library, `unittest`; 3ds Max 2020 + Corona 12 (12.0.27266) for the
fixtures and oracles (headless `3dsmaxbatch` for probes and oracles, an own interactive instance for the saves).

---

## Facts (probes of 2026-11-16 in 3ds Max 2020 + Corona 12; oracle dumps of the fixtures)

ClassIDs and class-directory names (DLL `coronamaxutils2020.dlt`): CoronaPhysicalMtl `(0x6912AB89, 0x87151720)`,
name `"\rCoronaPhysicalMtl"` (a leading carriage return); CoronaLegacyMtl `(0x70BE6506, 0x448931DD)` (MAXScript's
`CoronaMtl` is the same class; the corpus Corona scene, saved with `coronamaxutils2015.dlt`, has the same ClassID
and the same parameter ids); CoronaLayeredMtl `(0x65486584, 0x8425554E)`; CoronaLightMtl `(0x53B7717A,
0x500D5093)`; CoronaBitmap `(0xABBA5784, 0x65484244)`; CoronaNormal `(0x2870CEAA, 0xCC18437C)`; CoronaColor
`(0x68426DCA, 0x372362D4)`; CoronaMix `(0x6847286F, 0x3FFFAAB4)`. Every parameter in block 0.

Parameter ids (map amounts are fractions, not percent):

- CoronaPhysicalMtl: 101 baseColor, 102 baseLevel, 103 / 104 / 105 base map (on, amount), 111 metalnessMode
  (1 metal), 121 opacityColor, 122 opacityLevel, 123 / 124 / 125 opacity map, 131 baseRoughness, 132 / 133 / 134
  its map, 171 baseIor, 191 refractionAmount, 192 / 193 / 194 its map, 203 useThinMode, 211 clearcoatAmount,
  221 clearcoatIor, 231 clearcoatRoughness, 331 selfIllumColor, 332 selfIllumLevel, 333 / 334 / 335 its map,
  351 / 352 / 353 baseBump map, 381 thinAbsorptionColor, 391 clearcoatAbsorptionColor, 411 / 412 metalness map
  (on; no amount), 421 roughnessMode (0 roughness, 1 glossiness: every roughness of the material).
- CoronaLegacyMtl: 101 colorDiffuse, 102 colorReflect, 103 colorRefract, 105 colorOpacity, 107 colorSelfIllum;
  levels 121 diffuse, 122 reflect, 123 refract, 127 opacity, 128 selfIllum; maps 141 diffuse, 142 reflect,
  143 reflectGlossiness, 144 refract, 146 opacity, 147 bump, 158 selfIllum; their switches 161, 162, 163, 164, 166,
  167, 178; their amounts 290, 291, 292, 293, 295, 296, 303; 180 reflectGlossiness, 182 fresnelIor, 183 ior,
  210 thin, 402 pbrMode. Unsaved obsolete parameters are named "removedParam" (also in the other classes).
- CoronaLayeredMtl: 1000 baseMtl, 1001 layers (table), 1002 amounts, 1003 mixmaps; getSubMtl order base, layers.
- CoronaLightMtl: 110 intensity, 111 texmap, 112 texmapOn, 113 color, 150 opacityTexmap, 151 opacityTexmapOn.
- CoronaBitmap: 101 filename (asset id), 103 uvwChannel, 105 uvwScale, 106 uvwOffset (point3), 107 filteringBlur,
  108 / 109 tilingU / V (0 none, 1 repeat, 2 mirror), 114 realWorldScale, 117 monoChannelOutput, 118
  rgbChannelOutput (1 alpha as gray), 119 clippingOn, 120 clippingMode (0 crop, 1 place), 121-124 clipping u, v,
  width, height, 125 gamma (-1 automatic, else the override), 129 wAngle (radians), 130 uAngle (the U offset times
  2 pi, kept in step by Corona: not read); an Output part (TexOutput) at slot 1. Percent parameters
  (CoronaPhysicalMtl's base and roughness map amounts, CoronaLayeredMtl's amounts) are set in percent from MAXScript
  and stored as fractions (revised after the first fixture run).
- CoronaColor: 50 method (0 color, 1 HDR color, 2 temperature, 3 hex), 51 temperature (K), 52 color, 57 multiplier,
  58 colorHdr, 59 hexColor.
- CoronaMix: 200 mixOperation (0 add, 1 subtract, 2 multiply, 3 divide, 4 min, 5 max, 6 mix, 7 gamma,
  8 difference, ...), 201 mixAmount, 202 / 203 multiplierTop / Bottom, 204 / 205 offsetTop / Bottom, 206 / 207
  texmapTop / Bottom, 208 / 209 colorTop / Bottom, 210 texmapMix, 211 / 212 / 213 switches mix, top, bottom.
- CoronaNormal: the ids already in `texmaps.NORMAL_MAPS` (confirmed).

Behaviour measured with `renderMap` (8 x 8 renders of known images): CoronaBitmap tiling, U / V offset and W angle
place the image exactly as a Bitmap's U / V tiling, offset and W angle do; uAngle shifts U because it is the U
offset again; tiling mode 0 leaves black outside, 2 mirrors; clipping mode 0 crops, 1 places; gamma 1.0
makes an 8-bit image linear data, 2.2 and -1 sRGB (as Bitmap's override); rgbChannelOutput 1 = alpha as gray;
enviroMapping has no effect on a UV-mapped map. CoronaMix result = mix(bottom, op(bottom, top), amount), the mask
map replacing the amount when on. CoronaColor's multiplier scales the color before display; temperature gives
Kelvin colors (3000 K = (255, 122, 39) linear 0..255).

## The rules

CoronaPhysicalMtl: base = baseColor x baseLevel (map 103 if 104, amount 105); roughness = baseRoughness, or
1 - it in glossiness mode (the map then inverted); metallic = metalnessMode == 1 (map 411 if 412); transmission =
refractionAmount (map 192); a refracting material's base color is mixed toward white, or toward the thin absorption
color in thin mode, by the transmission; ior = baseIor; thin = useThinMode; alpha = mean(linear opacityColor) x
opacityLevel (map 123); emission = selfIllumColor at selfIllumLevel (map 333); coat = clearcoatAmount, ior,
roughness (glossiness mode as above), color = clearcoatAbsorptionColor; bump slot 351 (a CoronaNormal there is the
normal input). Specular stays 0.5: Corona derives reflectance from the IOR.

CoronaLegacyMtl: diffuse = colorDiffuse x levelDiffuse; reflection = colorReflect x levelReflect; refraction =
colorRefract x levelRefract; specular = mean(reflection) (map 142); roughness = 1 - reflectGlossiness (map 143
inverted), in PBR mode or not (PBR off is approximated the same way: documented); transmission = mean(refraction)
(map 144) and base = mix(diffuse, colorRefract, transmission) as for VRayMtl; ior = ior when refracting, else
fresnelIor; Fresnel IOR >= CORONA_METAL_IOR (10) with mean(reflection) >= METAL_REFLECTION makes a metal in the
reflection color (the reflection map driving the base); alpha, emission and bump like the physical material
(maps 146, 158, 147). Base map 141.

CoronaLayeredMtl: a wrapper (`WRAPPERS`: 1000 baseMtl, then the layers table 1001): counted in stats.peeled.
CoronaLightMtl: base black, roughness 1, specular 0, emission color (map 111 if 112) at intensity, alpha map 150
if 151.

Maps: CoronaBitmap -> Image (Mapping from the parameters above, Crop, Output part, gamma, alpha), also found by
the first-image search of peeled maps; CoronaColor -> Constant (color and hex as swatches decoded from sRGB, HDR
as linear, temperature through the Kelvin formula of the rules source, times the multiplier); CoronaMix with
operation mix -> Mix(bottom, top, amount, mask), multiply -> Multiply (under a Mix when the amount is below 1 or a
mask is set), any other operation -> its first bitmap (peeled, an issue); top / bottom multipliers or offsets that
change anything are an issue (approximated). class_name() strips the class-directory name (the leading `\r`).

## Chunk 1: fixtures and oracles

### Task 1: fixtures

**Files:** Create `tools/fixtures/corona_{physical,legacy,maps,layered,light}.ms`,
`tests/fixtures/corona_*.max` + `.oracle.json`; modify `tests/unit/test_materials.py` (parity accepts unsaved
"removedParam").

- [ ] Write the five scripts (values above and in each script's header).
- [ ] Dry run in `3dsmaxbatch`; raw-param parity on the batch files.
- [ ] Final save from an own interactive 3ds Max (`3dsmax.exe -q -silent -U MAXScript <wrapper>`), ViewCube hidden,
  solid background; `tools/sanitize_fixture.py` then `tools/check_fixture.py` -> clean; oracles through
  `MaxDropOracle.dumpFile` in `3dsmaxbatch`.
- [ ] `python -I -m unittest discover tests` -> parity OK; commit fixtures, scripts and oracles together.

## Chunk 2: rules

### Task 2: classids

- [ ] Add the eight ClassIDs and names to `reader/classids.py`; `texmaps.CORONA_NORMAL` becomes an alias.
- [ ] `test_classdir.test_every_known_class_is_in_a_fixture` passes.

### Task 3: material rules (tests first, in `tests/unit/test_convert_materials.py`)

- [ ] Fixture tests: every channel of each fixture material equals hand-computed values (physical rough / gloss /
  glass, legacy PBR / non-PBR / metal, light, layered peel and its count, layered without base -> its layer).
- [ ] Synthetic tests: defaults, map switches off, glossiness-mode map inverted, metal threshold, damaged values.
- [ ] Implement `corona_physical_mtl`, `corona_legacy_mtl`, `corona_light_mtl`, `WRAPPERS` entry, `class_name`
  strip; register in `RULES`.

### Task 4: map rules (tests first, in `tests/unit/test_texmaps.py`)

- [ ] Fixture tests on corona_maps / corona_light: the base Image's Mapping (tiling 2 x 3, offset, W angle 30 deg
  in radians, channel 2, U mirror, V no tile, blur 0.8) under the 75 % Mix, the gloss Image gamma 1.0 Non-Color
  under Invert, the placed opacity Crop with alpha, the NormalMap (0.8 x 0.9, flip green, bump 0.3 x 0.9), the
  CoronaColor Constant, the CoronaMix Mix with its mask, the Multiply, the Add peeled with an issue, the HDR
  Constant, the switched-off slot absent, the light's emission and opacity images.
- [ ] Synthetic: CoronaColor methods (Kelvin 3000 K, hex, multiplier), CoronaMix multiplier issue,
  real-world issue, gamma -1 -> None, a CoronaBitmap below a Falloff found by the first-image search.
- [ ] Implement `_corona_image`, `_corona_color`, `_corona_mix`, `kelvin_rgb`; generalize the first-image search.

## Chunk 3: docs and the corpus scene

- [ ] `docs/FORMAT.md`: the Corona parameter tables. `docs/SUPPORT.md`: Corona rows "Imported" (verified on the
  Corona 12 fixtures; older Corona versions checked on one scene only), CoronaBitmap / CoronaColor / CoronaMix rows,
  the roadmap line. `CHANGELOG.md` Unreleased: Added line. README line about Corona.
- [ ] Corpus Corona scene (local, never named): convert every Corona material object with the pack's maps on the
  texture search path; counts (materials, textured inputs, images found) into the close note.

## Verification

**Working directory:** the checkout root; Blender paths from the bead notes; `$S` = this session's scratchpad.

1. `python -I -m unittest discover tests` -> `OK` (skips as before); includes raw-param parity on the five Corona
   fixtures, the fixture privacy scan and the class-directory check.
2. `python -I tools/check_fixture.py tests/fixtures/corona_*.max` -> every file `clean`.
3. `ruff check .` (if installed) -> clean.
4. Repo-local `build-and-test`: `powershell -ExecutionPolicy Bypass -File build.ps1` (zip, index), then on Blender
   4.2.23, 4.5.16 and 5.2 (headless, `BLENDER_USER_RESOURCES=$S\profile-<v>`, `--background --factory-startup
   --python-exit-code 1`): `tests/smoke_register.py`, `tests/smoke_import.py` (all fixtures, the Corona ones
   included: each imports, its Corona materials are Principled materials, not grey) and `tests/blender/run.py`;
   equal counts on the three versions.
5. Corpus Corona scene (outside the repo): it imports without an exception on 5.2; a scratch script converts its
   Corona material objects with the maps folder as texture search folder: counts only, in the close note.

**Success criteria:** 1-4 pass; the corpus check runs; no commercial name or user path in the diff.
