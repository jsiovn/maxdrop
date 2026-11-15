# maxdrop-arp.5 Texture-map rules Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decide, for every map slot of a MaterialIR, which image file drives it and how, as a small renderer-neutral
graph (TextureGraphIR) that the builder of maxdrop-arp.6 turns into nodes.

**Architecture:** A new pure module `maxdrop/convert/texmaps.py` (no bpy, no mathutils) walks the map object a
`MapRef` points at, through the reader's `MaterialGraph` and `AssetTable`: a Bitmap becomes an `Image` node with its
`Mapping` (tiling, offset, U/V/W angles, tile / mirror, map channel, coordinate source), crop or placement, Output
(invert, amount, level, offset) and gamma override; the allow-listed wrappers (Mix, RGB Multiply, Color Correction,
simple Composite) stay nodes; the peel classes (Falloff, VRayDirt, Output, RGB Tint, VRayColor2Bump) and any other
class with maps below give the first usable Bitmap below (counted as approximations); VRayNormalMap, Normal Bump and
CoronaNormal give a `NormalMap` (flip green, strength, an additional bump); a height map in a bump slot gives a
`Bump`; a glossiness map feeding roughness gets an `Invert`. Color space per slot: sRGB for color slots, Non-Color
for data, normal and bump slots; swatches are already linear (materials.py). `MaterialConverter` takes an optional
`TexmapConverter` and fills `MaterialIR.textures` ({input name: TextureGraphIR}); its bump slot sends every normal-map
class to the normal input.

**Tech Stack:** Python 3.11 syntax, standard library; plain `unittest`; 3ds Max 2020 + V-Ray 5 + Corona 12 to
author the fixture and its oracle (headless `3dsmaxbatch` for probes and the oracle; an own interactive instance for
the fixture save, whose thumbnail must pass the scan).

---

## Facts (verified on the fixtures and probe scenes of this bead)

- New fixture `texmap_rules` (`tools/fixtures/texmap_rules.ms`): FixtureTexPeel (Falloff over a Bitmap in diffuse,
  VRayDirt with an unoccluded Bitmap in reflection at 80 %, Output over a Bitmap in glossiness, VRayColor2Bump over
  a Bitmap in bump at 40 %, RGB Tint over a Bitmap in opacity, a Falloff without map in metalness, a Falloff whose
  map1 is off (color1 red) in self-illumination); FixtureTexKeep (Mix of two Bitmaps with a Bitmap mask at 30 %,
  RGB Multiply of a Bitmap and color 200 150 100, Color Correction hue 30 saturation 20 brightness 10 contrast 5
  advanced gamma 1.2, Normal Bump normal 0.8 / bump 0.4 flip green, a glossiness Bitmap with gamma override 1.0);
  FixtureTexPlace (Composite of two Bitmaps, top at 60 %; a Bitmap with crop 0.1 0.2 0.5 0.6, channel 3, U mirror,
  V tile off, angles U 10 V 20 W 30, tiling 2 x 3, gamma override 2.2; a Bitmap in placement mode on the vertex
  color channel; one with environment mapping; one with an inverted Output; CoronaNormal 0.9, flip green, an
  additional bump at 0.5).
- Parameter ids (block 0 unless named), from the oracle: Falloff (0x6EC3730C, 0) 0 color1, 1 map1Amount, 2 map1,
  3 map1On, 4 color2, 5 map2Amount, 6 map2, 7 map2On; VRayDirt (0x2F567899, 0x090D5EA4) 13 unoccluded_color,
  17 texmap_unoccluded_color, 18 on, 19 multiplier; VRayColor2Bump (0x31E15D1D, 0x7D7E2810) 0 map, 1 height;
  Output (0x2B0, 0) 0 map1, 1 map1Enabled, its TexOutput part; RGB Tint (0x224, 0) 3 map1, 4 map1Enabled; Mix
  (0x230, 0) 0 mixAmount (fraction), 4 color1, 5 color2, 6 map1, 7 map2, 8 mask, 9 / 10 / 11 their switches;
  RGB Multiply (0x290, 0) 0 color1, 1 color2, 2 map1, 3 map2, 4 / 5 switches; Color Correction (0x2D0, 0) 0 color,
  1 map, 7 hueShift (degrees), 8 saturation (%), 11 lightnessMode (1 advanced), 12 brightness, 13 contrast,
  22 gammaRGB; Composite (0x280, 0) tables 1 mapEnabled, 3 maskEnabled, 5 blendMode, 8 opacity (%), 9 mapList,
  10 mask (0, 2, 4 unnamed, empty, not saved); Normal Bump (0x243E22C6, 0x63F6A014) 0 mult_spin, 1 bump_spin,
  2 normal_map, 3 bump_map, 4 / 5 switches, 7 flipred, 8 flipgreen, 9 swap_rg; CoronaNormal (0x2870CEAA,
  0xCC18437C) 500 normalMap, 501 multiplier, 502 addGamma, 503 flipRed, 504 flipGreen, 505 swapRedGreen,
  507 additionalBump, 508 additionalBumpStrength, 509 additionalBumpOn; VRayNormalMap 0 normal_map, 2 on,
  3 multiplier, 4 bump_map, 5 on, 6 multiplier, 1 map_channel, 7 flip_red, 8 flip_green, 9 swap_red_and_green.
- Bitmap block 0: 0-3 clip u, v, w, h; 6 apply; 7 cropPlace (0 crop, 1 place); 9 monoOutput; 11 alphaSource;
  13 bitmap (asset). Placement part (UVGen, slot 0), old ParamBlock: 0 U offset, 1 V offset, 2 U tiling, 3 V tiling,
  4 U angle, 5 V angle, 6 W angle (radians), 7 blur. Its own chunks: 0x9002 flags (bit 0 U tile, 1 V tile, 2 U mirror,
  3 V mirror, 27 real-world scale; bit 30 always set), 0x9003 axis (0 UV, 1 VW, 2 WU), 0x9005 mapping type (0
  texture, 1 environment), 0x9006 coordinate source (0 explicit channel, 1 object XYZ, 2 vertex color, 3 world XYZ),
  0x900B map channel. Output part (TexOutput, slot 2), old ParamBlock: 0 RGB level, 1 RGB offset, 2 output amount,
  3 bump amount; its 0x0002 u32 flags, bit 1 (2) invert.
- Gamma: the Bitmap's block 0 holds its BitmapInfo in the 0x0003 sibling's 0x1201 (70 bytes in every file seen): the
  last 14 bytes start with an f32 gamma and a u32 flags; flags bit 0 set = override (5 seen, the value is the
  override), 20 = automatic (the default). Gamma override 1.0 on a color slot = linear data.
- `test_scene` pair heads: the nameless point class of Custom Curve Control (Falloff's curve) has head 2.

## File structure

- Create `maxdrop/convert/texmaps.py`: node dataclasses (`Mapping`, `Crop`, `TexOutput`, `Image`, `Constant`,
  `Invert`, `Mix`, `Multiply`, `ColorCorrect`, `Composite`, `NormalMap`, `Bump`), `TextureGraphIR`, `TexmapStats`,
  `TexmapConverter` (`graph(map_ref, kind, value)`), `SLOT_KINDS`, `NORMAL_MAPS`, `texture_graphs(ir, tex)`.
- Modify `maxdrop/convert/materials.py`: `MaterialIR.textures`; `MaterialConverter(graph, texmaps=None)` fills it;
  `bump_slot` routes every class of `texmaps.NORMAL_MAPS`.
- Create `tests/unit/test_texmaps.py`: vray_maps and texmap_rules expectations, synthetic guards.
- Modify `tests/unit/test_assets.py`, `test_convert_scene.py`, `test_materials.py`, `test_scene.py`: the new fixture.
- Add `tools/fixtures/texmap_rules.ms`, `tests/fixtures/texmap_rules.max` + `.oracle.json`.
- Modify `docs/FORMAT.md`: the facts above.

## Tasks

### Task 1: fixture + oracle (done while planning)

- [x] Author `tools/fixtures/texmap_rules.ms`, run it, sanitize, check `clean`, copy, dump the oracle.
- [x] Teach the fixture-enumerating tests (asset count 22, UV layer `UVMap`, Composite's unsaved empty tables, the
  nameless curve point class).
- [ ] Commit the fixture with those test changes.

### Task 2: texmaps.py

- [ ] Write `tests/unit/test_texmaps.py` first:
  - vray_maps FixtureVRayMaps: diffuse -> Image `fixture_diffuse.png`, tiling (2.0, 2.5), offset (0.1, 0.15), W angle
    15 deg, channel 1, sRGB, Mix with the diffuse swatch at 0.91; reflection (specular input, data) ->
    `fixture_reflect.png` tiling (3, 3.5), offset (0.2, 0.25), 25 deg, Non-Color; glossiness -> Invert over
    `fixture_gloss.png` tiling (4, 4.5) 35 deg, Non-Color; bump -> Bump strength 0.64 over `fixture_bump.png`
    (5, 5.5), 45 deg; opacity -> `fixture_opacity.png` (6, 6.5) 55 deg, Non-Color, at 0.55.
  - FixtureVRayNormal: NormalMap strength 0.85 (1.0 x 0.85), flip green, image `fixture_normal.png` Non-Color, bump
    Bump strength 0.35 over `fixture_normal_bump.png`.
  - texmap_rules FixtureTexPeel: each slot peels to its Bitmap (diffuse `peel_diffuse.png` sRGB, specular
    `peel_reflect.png`, roughness Invert over `peel_gloss.png`, bump Bump 0.4 over `peel_height.png`, alpha
    `peel_opacity.png`), each graph approximated, stats.peeled {Falloff 1, VRayDirt 1, Output 1, VRayColor2Bump 1,
    RGB Tint 1, ...}; metallic: Falloff without map -> Constant color1 (linear); emission: map1 off -> Constant red.
  - FixtureTexKeep: Mix(a, b, factor 0.3, mask Non-Color), Multiply(Image, Constant linear(200,150,100)),
    ColorCorrect(hue 30/360, saturation 1.2, brightness 0.1, contrast 0.05, gamma 1.2), NormalMap 0.8 flip green
    with Bump 0.4; glossiness gamma override 1.0 -> Image gamma 1.0, Non-Color (data slot anyway).
  - FixtureTexPlace: Composite layers [base 1.0, top 0.6]; crop Image: crop (0.1, 0.2, 0.5, 0.6, place False),
    channel 3, mirror (True, False), tile (False, False), angles (10, 20, 30 deg), tiling (2, 3), gamma 2.2, sRGB
    on the color slot; placement Image: crop place True, source vertex color (channel 0); env Image: an issue
    `environment mapping`, graph None? (decided: the graph keeps the Image with `mapping.environment = True` and the
    converter records an issue); inverted Output -> Image output.invert True; CoronaNormal: NormalMap 0.9 flip green,
    Bump 0.5 over `place_cbump.png`.
  - Synthetic: cycle in maps, depth > MAX_DEPTH, a map reference to a material (issue), a Bitmap without file
    (None + issue), unknown class with a Bitmap below (approximated, counted), unknown class without (None, counted
    unsupported), Composite with a mask or a non-normal blend mode -> peeled (approximated), color slot gamma
    override 1.0 -> Non-Color, override 1.8 -> Non-Color + gamma 1.8, damaged UVGen chunks -> defaults.
- [ ] Run: `python -I -m unittest discover -s tests -p test_texmaps.py` -> fails (module missing).
- [ ] Implement `maxdrop/convert/texmaps.py`.
- [ ] Run the module's tests -> pass; run the whole suite -> pass.
- [ ] Commit.

### Task 3: wire into materials.py

- [ ] Tests: `MaterialConverter(graph, texmaps=TexmapConverter(...))` gives `ir.textures` keys exactly the inputs
  with a map; Normal Bump / CoronaNormal in a bump slot land in `ir.normal`, not `ir.bump`; no texmaps -> `{}`.
- [ ] Implement; whole suite passes; commit.

### Task 4: docs

- [ ] `docs/FORMAT.md`: Bitmap placement chunks, Output part, BitmapInfo gamma, the new classes' parameter ids, the
  pair head; commit.

## Verification

**Build:** `powershell -ExecutionPolicy Bypass -File build.ps1` -> `dist\maxdrop-<version>.zip`, `check_zip` ok.

**Plain tests:** `python -I -m unittest discover tests` -> `OK` (skips allowed as before); includes
`test_texmaps.py` (the vray_maps slot / file / tiling / offset / angle checks, Falloff peel counted, glossiness
invert, color space per slot), `test_fixtures.py` (texmap_rules scans clean), `test_oracle.py`.

**Blender (headless, isolated profile, 4.2.23, 4.5.16, 5.2):** `tests/smoke_register.py` -> `SMOKE PASSED`;
`tests/smoke_import.py` -> `IMPORT PASSED` (the operator on every fixture, texmap_rules included);
`tests/blender/run.py` -> `FIXTURES PASSED`. The builder does not use the graphs yet (maxdrop-arp.6), so
nothing visible changes: no CHANGELOG or SUPPORT.md line.

**Corpus (local, counts only, nothing committed):** convert every material of scenes A and B with textures; report
the number of graphs, approximations by class, unsupported classes and issues; no exception.

**Success criteria:** all of the above pass on the three versions; no commercial name or user path in the diff;
the fixture scan prints `clean`.
