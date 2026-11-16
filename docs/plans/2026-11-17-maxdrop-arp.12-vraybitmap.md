# VRayBitmap as an image texture (+ vray_texmaps fixture) Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VRayBitmap (VRayHDRI before V-Ray 5, the same class) converts to an Image like Bitmap and CoronaBitmap,
verified on a new self-authored fixture `vray_texmaps` that also carries the cases of maxdrop-arp.13 (VRayColor)
and maxdrop-arp.14 (a wrapper over a map that converts to nothing).

**Architecture:** `reader/classids.py` gets `VRAY_BITMAP` (and `NOISE`, which the fixture holds); `convert/texmaps.py`
adds it to `IMAGES` and gives it its own image method next to `_corona_image`: the file from parameter 0, the
Placement part (slot 2, a standard UVGen) through the existing `_mapping`, crop / place, mono / RGB output alpha,
the transfer function as a color space and gamma, the overall times render multiplier folded into the Output's
amount. `reader/assets.py` learns its file parameter; `reader/owner_slots.py` its 0x0013 table (and Noise's). The
builder needs no change: an Image with a gamma and an Output amount is drawn already.

**Tech Stack:** Python 3.11 syntax, standard library, `unittest`; 3ds Max 2020 + V-Ray 5.2 (headless `3dsmaxbatch`
for probes and the oracle, an own interactive instance for the fixture save); Blender 4.2 / 4.5 / 5.2 headless.

---

## Facts (3ds Max 2020 + V-Ray 5.2, 2026-11-17)

- ClassID `(0x6769144B, 0x02C1017D)` (V-Ray SDK `include/pb2vrayhdri.h`, `HDRIMAP_CLASS_ID`; oracle class name
  `VRayBitmap`). MAXScript's `VRayHDRI` is the same class. VRayColor is `(0x58F82B74, 0x73B75D7F)` (arp.13's),
  Noise `(0x00000234, 0)`.
- References: 0 block 0, 1 block 1, 2 UVGen (standard Placement), 3 block 2 (IFL), 4 TexOutput, 5 block 3.
- Block 0 parameter ids: 0 HDRIMapName (file name: a pblock.Asset in the asset table), 1 multiplier (overall),
  2 mapType (0 angular, 1 cubic, 2 spherical, 3 mirrored ball, 4 3ds Max standard, the default), 7 mapChannel (not
  used in standard mode: the UVGen's channel is; the two are independent, probed), 8 gamma, 9 renderMultiplier,
  16 cropplace_on, 17 cropplace_mode (1 place), 18-21 u v w h, 22 rgbOutput (0 color, 1 alpha as gray, 2 intensity
  as gray), 23 monoOutput (1 alpha), 25 color_space, 31 coords, 38 mapSource, 39 mapSource_on. Block 3: 41
  rgbColorSpace (0 default, 1 sRGB, 2 ACEScg, 3 raw).
- color_space, measured with `renderMap` on a 128-gray PNG (0..255 linear): 0 None -> 128 (linear, no decode);
  1 Inverse gamma g -> pixel^(1/g) (g 0.4545 -> 56.0, g 2 -> 180.7); 2 sRGB -> 55.0 (the sRGB curve); 3 From
  3ds Max -> 56.0 (the scene's input gamma 2.2, as a Bitmap's automatic); 4 Auto (default) -> 55.0 (sRGB for an
  8-bit file).
- multiplier 2 doubles the color in `renderMap`; renderMultiplier changes nothing there (it applies when V-Ray
  renders). Rule: the product of the two scales the image.
- 0x0013 of the fixture: VRayBitmap block 0 `{31: 2}`; Noise block 0 (its ref 1) `{2: 2, 3: 3, 13: 4}`.

## Rules

- `_vray_image`: file from param 0 (no file: an issue `VRayBitmap %r: no file`, None). Mapping = `_mapping(uv)`
  of the UVGen part; mapType != 4 -> `Mapping.environment = True` and the issue `VRayBitmap %r: environment
  mapping (type n), drawn with the UVs`; the UVGen's own environment / XYZ / real-world issues as for Bitmap.
  mapSource set and on -> issue (its placement not converted).
- Color space: 0 -> gamma 1.0; 1 -> gamma 1 / g (g in 0.1..10, else an issue and None); 2, 3, 4 -> None
  (automatic); any other value -> None and an issue. `colorspace(kind, gamma)` as for Bitmap; rgbColorSpace 2
  (ACEScg) -> an issue.
- Multiplier: `multiplier * renderMultiplier` (each finite, >= 0) times the Output part's amount; the Output is
  kept when it changes anything (`TexOutput()` equality).
- Crop / place, alpha (mono 1 on a DATA input, RGB 1 elsewhere) as Bitmap; RGB output 2 -> an issue.

## Chunk 1: fixture (done before this plan was written)

- [x] `tools/fixtures/vray_texmaps.ms` (ten boxes, see its header); dry run in `3dsmaxbatch`; final save from an own
  `3dsmax.exe -q -silent -U MAXScript` wrapper (ViewCube hidden, solid background); `tools/sanitize_fixture.py`
  (4 values blanked), `tools/check_fixture.py` -> clean; own byte scan (ASCII + UTF-16LE) for the user name,
  computer name and drive paths -> none; oracle by `MaxDropOracle.dumpFile` in `3dsmaxbatch`.
- Images are not committed: as for the other fixtures, the files are bare names, and `tests/blender/run.py`
  writes a PNG for each name beside a copy of the scene (`check_found_textures`). Deviation from the bead's
  "small self-made files under tests/fixtures": the generated PNGs are self-made and keep binaries out of git.

## Chunk 2: tests and registrations

### Task 1: register the fixture in the per-fixture tables

**Files:** `tests/unit/test_convert_scene.py` (UV_LAYERS), `tests/unit/test_assets.py` (ASSET_COUNTS 12),
`tests/blender/run.py` (UV_LAYERS, `check_found_textures` list), `tests/unit/test_materials.py` (parity, FLOORS
if needed).

- [ ] Add `vray_texmaps` to each table; run `python -I -m unittest discover tests`.

### Task 2: classids and owner slots

**Files:** `maxdrop/reader/classids.py`, `maxdrop/reader/owner_slots.py`, `maxdrop/reader/assets.py`.

- [ ] `VRAY_BITMAP`, `NOISE` + CLASSES names (`VRayBitmap`, `Noise`); test_classdir passes.
- [ ] owner_slots: `(SC_TEXMAP, VRAY_BITMAP): {0: {31: 2}}`, `(SC_TEXMAP, NOISE): {0: {2: 2, 3: 3, 13: 4}}`;
  `test_pblock.OwnerSlotsOnFixtures` passes.
- [ ] assets: `VRAY_BITMAP_FILE = 0` in `_FILE_PARAMS`; a test in test_texmaps / test_assets that `bitmap_file`
  gives its entry.

### Task 3: texmaps rule (tests first)

**Files:** `maxdrop/convert/texmaps.py`, `tests/unit/test_texmaps.py`.

- [ ] Fixture tests (`class VRayTexmaps`): FixtureVBDiffuse base color = Image vtx_diffuse.png sRGB, gamma None,
  no output; its reflection (spherical) an Image with environment and the issue. FixtureVBPlace: tiling (2, 3),
  offset (0.1, 0.2), W 30 deg, blur 0.8, output amount 3.0; reflection Non-Color gamma 1.0; refraction
  (transmission) Non-Color gamma 0.5; glossiness (roughness, Invert) Non-Color; opacity alpha True. FixtureVBBump:
  Bump 0.5 over the image; FixtureVBNormal: NormalMap strength 0.9 over a Non-Color image. FixtureCCComposite:
  ColorCorrect over a Composite of the two layer images (top at 0.5). FixtureMixMask: Mix whose a is the
  vtx_mix_a.png image. ClassID matches the class directory.
- [ ] Synthetic tests: no file -> None + issue, no exception; color_space 0 / 1 / 2 / 3 / 4 / out of range;
  inverse gamma out of range; multipliers and a negative or NaN one; mapSource on; RGB output 2; ACEScg; found by
  `_first_image` below an unknown class.
- [ ] Implement; module docstring rule line for VRayBitmap.

## Chunk 3: docs

- [ ] `docs/SUPPORT.md` map table: a VRayBitmap row; `CHANGELOG.md` line under `## [0.0.4]`.

## Verification

- `python -I -m unittest discover tests` -> OK; again with a Python that has no numpy (the plain CI job has none).
- `build-and-test`: `build.ps1`, `tests/smoke_register.py`, `tests/smoke_import.py`, `tests/blender/run.py`
  (FIXTURES PASSED) on Blender 4.2.23, 4.5.16 (portable) and 5.2 (installed), headless, isolated profile.
- Local only: `C:\maxdrop_fixtures\oracle\m2gate\matparity.py` on scenes A and B stays at or above A 213/214, B
  220/220; `--fixtures` passes with vray_texmaps.
