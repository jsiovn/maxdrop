# Falloff in a reflection slot Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a Falloff in a VRayMtl reflection slot is drawn as its two sides mixed by the viewing angle (Specular IOR
Level changes with the angle), proven by a fixture, unit tests and a builder check on Blender 4.2, 4.5 and 5.2.

**Architecture:** bead `maxdrop-em3.33` was filed (2026-11-16) when every Falloff was peeled to color 1. Since M5
(4909ae7, 2026-11-20) `convert/texmaps.py` `_falloff` draws types 0 to 2 in the viewing direction as
`Mix(side 1, side 2, mask=Facing)` in every input, the specular input included, and `build/materials.py` draws the
Facing (Layer Weight, Fresnel node, Geometry dot product); a color graph on the float Specular IOR Level goes
through the mean of its channels. A local probe of the two corpus scenes of the A/B render confirms it: every
reflection Falloff there is now a Facing mix (perpendicular and Fresnel), none is peeled for its type. So no new
graph node type and no converter change: the bead's remaining work is the proof the reflection slot never had
(every Falloff test drives base color) and the docs.

**Tech Stack:** plain Python unittest (convert, no bpy), MAXScript fixture (3ds Max 2020 + V-Ray 5), Blender
headless builder checks.

---

## Chunk 1: tests, fixture, docs

### Task 1: unit test on a hand-made Falloff in the specular input

**Files:** Test: `tests/unit/test_texmaps.py` (next to `test_falloff_types_and_amounts`)

- [ ] Add `test_falloff_in_a_reflection_slot`: a default Falloff (no params: perpendicular / parallel, black to
  white, no maps) converted with `tex.convert(MapRef(1), tx.COLOR, 0.0)` (how `texture_graphs` converts
  `specular`) is `Mix(Constant(black), Constant(white), 0.0, Facing(PERPENDICULAR))`, not approximated, no issue,
  `stats.peeled` empty; with type 2 the mask is `Facing(FRESNEL, ior)`; with a slot amount of 0.5 the root is
  `Mix(Constant((0,)*3), <that Mix>, 0.5)`.
- [ ] Run `python -I -m unittest tests.unit.test_texmaps -k reflection`: passes on HEAD (the behavior exists since
  4909ae7; this is the missing guard, so there is no red step).

### Task 2: fixture materials

**Files:** Modify `tools/fixtures/vray_texmaps.ms`; regenerate `tests/fixtures/vray_texmaps.max` and
`tests/fixtures/vray_texmaps.oracle.json`.

- [ ] Append two boxes after FixtureCCNoise (existing handles and indices stay): `FixtureVReflPerp`, a VRayMtl with
  reflection Fresnel off and the black default swatch whose reflection map is a default Falloff (perpendicular /
  parallel, black to white); `FixtureVReflFresnel`, a VRayMtl whose reflection map is a Falloff of type Fresnel
  (IOR override on, IOR 1.5) at a reflection map amount of 50. Update the header comment (twelve boxes).
- [ ] In my own 3ds Max 2020 instance (record its PID, close only it; gamma off, V-Ray loaded): run the script,
  `python -I tools/sanitize_fixture.py C:\maxdrop_fixtures\vray_texmaps.max`, `python -I tools/check_fixture.py
  ...` -> `clean`; copy into `tests/fixtures/`; `MaxDropOracle.dumpFile` of the committed copy into
  `tests/fixtures/vray_texmaps.oracle.json`. File under 1 MB.

### Task 3: fixture unit tests

**Files:** `tests/unit/test_texmaps.py` class `VRayTexmaps`

- [ ] `test_falloff_in_reflection`: `FixtureVReflPerp` specular graph = Mix(black, white, Facing(PERPENDICULAR)),
  not approximated, no issues; metallic 0 (Fresnel off, dark swatch: not a metal). `FixtureVReflFresnel`: root
  `Mix(Constant, Mix(..., Facing(FRESNEL, 1.5)), 0.5)`.
- [ ] Adjust any fixture-wide counts that change (`tests/unit/test_materials.py` FLOORS if needed; asset counts
  do not change: the Falloffs name no file).

### Task 4: builder check

**Files:** `tests/blender/run.py`

- [ ] In `check_found_textures`, for `vray_texmaps`: `Specular IOR Level` of `FixtureVReflPerp` is linked and a
  `ShaderNodeLayerWeight` is upstream of it; of `FixtureVReflFresnel` a `ShaderNodeFresnel`.

### Task 5: docs

- [ ] `docs/SUPPORT.md` Falloff row: in any input, a VRayMtl's reflection included (its Specular IOR Level then
  follows the angle). No CHANGELOG line: the import does not change in this bead (it changed in 1.0.0, whose
  section already lists the Falloff).

### Task 6: debt

- [ ] File a debt bead under `maxdrop-em3`: `convert/materials.py` `vray_mtl` decides "Fresnel off means metal" from
  the reflection swatch even when a reflection map at full amount hides the swatch (a Falloff over a bright swatch
  becomes a metal whose base color is the Falloff). Out of this bead's files.

## Verification

Working directory `D:\www\maxdrop`.

- `python -I -m unittest discover tests` -> `OK`.
- `python -I tools/lint.py` -> clean.
- `powershell -ExecutionPolicy Bypass -File build.ps1` -> dist zip built.
- Per Blender (5.2 installed; `D:\tools\blender\blender-4.2.23-windows-x64\blender.exe`,
  `D:\tools\blender\blender-4.5.16-windows-x64\blender.exe`), isolated profile
  (`BLENDER_USER_RESOURCES=<scratch>`, `--background --factory-startup --python-exit-code 1`):
  `tests/smoke_register.py`, `tests/smoke_import.py` -> `FIXTURES PASSED`, `tests/blender/run.py` -> every check
  passes, including the two new reflection Falloff checks.
- Local only (never committed or quoted): `matparity.py` on corpus scenes A and B does not drop below the baseline
  taken before the change (A 210/214, B 220/220).
