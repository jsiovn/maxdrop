# Swatch colors by the scene's gamma Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decode every 3ds Max color swatch by the gamma setting the scene was saved with: as linear when the gamma
is on (3ds Max's default since 2014), with the sRGB curve when it is off; linear plus one report note when the file
does not say.

**Architecture:** `reader/gamma.py` reads the scene's Gamma/LUT chunk (RenderEnvironment's `0x6010`). A new
`convert/colors.py` holds the one swatch rule (`Swatches`), chosen from that reading; `MaterialConverter` and
`TexmapConverter` take it (default: read from the graph's scene) and use it wherever a swatch becomes a color. The
import report states the rule.

**Tech Stack:** Python 3.11 standard library (reader, convert), 3ds Max 2020 + V-Ray 5.2 (`3dsmaxbatch`) for the
probes, Blender 4.2 / 4.5 / 5.2 headless for the smokes.

---

## Format discovery (done before this plan, evidence local in `C:\maxdrop_fixtures\probe\gamma\`)

- `save_probes.ms` saved an empty scene with a box under gamma on 2.2 (twice), off, off with all gammas 1.0,
  display gamma 1.8 and 1.0, file-in gamma 1.0, file-out gamma 1.0, LUT mode, and with the picker / Material
  Editor switches off. `tools/maxdiff.py A A2 B --stream Scene --stream Config`:
  - Scene stream: the RenderEnvironment object (`(0xEE448B23, 0)`, superclass `0x1010`) has a `0x6010` leaf of
    12 bytes: `u32` gamma enabled (1 on, 0 off), `f32` file input gamma, `f32` file output gamma. Config
    `0x2160/0x0100` repeats it.
  - The display gamma (`IDisplayGamma.gamma`) and the two switches are not in the file (no difference).
  - LUT mode: the Scene leaf keeps 1, the Config one says 0. Not taken further (the rule reads the Scene stream).
- Every committed fixture: `0` (gamma off), `2.2`, `2.2`. Corpus scene A (format 14000): `0`; scene B: `1`; same
  layout in both versions.
- `render_probes.ms` (V-Ray 5.2, VRayLightMtl planes, multiplier 1): gamma off: the 128 swatch renders byte 128,
  the 128 sRGB JPEG 128; gamma 2.2: swatch 187 (0.502 linear), JPEG 128. So: gamma on -> swatch value is linear;
  gamma off -> displayed as stored, i.e. sRGB-decoded in Blender's terms; images sRGB in both. Corona render in
  `3dsmaxbatch` fails ("Unable to open renderer"): Corona swatches follow the same rule unmeasured (noted).

## The rule

| Scene gamma (`0x6010`) | Swatch 128 grey | Report |
|---|---|---|
| enabled = 1 | 0.502 linear (value as linear) | `Color swatches: linear (gamma on)` |
| enabled = 0 | 0.216 linear (sRGB decode) | `Color swatches: sRGB (gamma off)` |
| missing / unreadable / enabled not 0 or 1 | 0.502 (linear, 3ds Max default) | the same line + `GAMMA_NOTE` as an issue |

Unchanged: image files (sRGB / their gamma override), CoronaColor HDR color (linear already), the kelvin curve fit
(an sRGB color by its source, measured against Corona's 3000 K), MaxDrop's own grey for a material without a rule
(0.216). There is no display gamma in the file, so no `value ** (gamma / 2.2)` case.

## File structure

- Create `maxdrop/reader/gamma.py`: `SceneGamma(enabled, file_in, file_out)`, `decode(payload)`,
  `scene_gamma(source)` (as `units.system_unit`).
- Modify `maxdrop/reader/classids.py`: `SC_RENDER_ENVIRONMENT = 0x1010`, `RENDER_ENVIRONMENT`, in `CLASSES`.
- Create `maxdrop/convert/colors.py`: `srgb_to_linear`, `Swatches(linear, note)` with `channel()` / `color()` /
  `line()`, `GAMMA_ON`, `GAMMA_OFF`, `UNKNOWN`, `GAMMA_NOTE`, `for_gamma(g)`, `of_scene(scene)`.
- Modify `maxdrop/convert/materials.py`: drop `srgb_to_linear`, `linear_color`, `GAMMA_NOTE`; `MaterialConverter(...,
  swatches=None)` and `conv.rgb(m, pid, block, default)` replacing `_rgb`; every rule calls `conv.rgb`; Standard's
  default diffuse through the rule; docstring.
- Modify `maxdrop/convert/texmaps.py`: drop `_srgb_to_linear`, `_linear`; `TexmapConverter(..., swatches=None)`;
  `_constant`, CoronaColor (color, hex; kelvin stays sRGB), VRayColor use `self.swatches`; docstring.
- Modify `maxdrop/convert/report.py`: `Report.swatches` (line) and `add_materials(..., swatches=None)`; the unknown
  case counts as an issue under "Other issues".
- Modify `maxdrop/ops.py`: read the gamma once, pass the rule to both converters and to the report.
- Modify `tests/blender/run.py` only where it builds converters (they read the scene themselves: no change needed
  unless a test asserts swatch values).
- Tests: `tests/unit/test_gamma.py` (new: every fixture 0 / 2.2 / 2.2, the new fixture 1, synthetic payloads:
  short, enabled 2, NaN gamma, missing chunk, unreadable scene); `tests/unit/test_colors.py` (new: the rule);
  `test_convert_materials.py`, `test_texmaps.py` (synthetic graphs have no gamma: unknown -> linear; update their
  hand-computed expectations, add one test per setting); `test_report.py` (the line and the note).
- Fixture `tools/fixtures/gamma_swatches.ms` -> `tests/fixtures/gamma_swatches.max` + oracle: gamma on 2.2, a
  VRayMtl with a 128 diffuse, one with a VRayColor 128 diffuse map, a Mix of 128 colors. Sanitized, checked.
- Docs: `docs/FORMAT.md` (Scene gamma section), `docs/SUPPORT.md` (color management), `CHANGELOG.md` under
  `## [0.0.4]`.
- Local only: `C:\maxdrop_fixtures\oracle\m2gate\matparity.py` if it encodes sRGB; its README.txt.

## Tasks

### Task 1: reader/gamma.py

- [ ] Test first (`tests/unit/test_gamma.py`): decode of `<Iff` payloads (1/2.2/2.2 -> on; 0 -> off; 2 -> None;
  11 bytes -> None; NaN gammas -> enabled kept, gammas None); every committed fixture -> enabled False, 2.2, 2.2;
  `gamma_swatches.max` -> True (after task 5).
- [ ] Implement: find the RenderEnvironment objects by class directory (superclass + ClassID), first `0x6010` leaf,
  `decode(view)`; `CfbError` / `ChunkError` -> None.
- [ ] Run `python -I -m unittest tests.unit.test_gamma` -> OK. Commit.

### Task 2: convert/colors.py + converters

- [ ] Tests (`tests/unit/test_colors.py`): `GAMMA_ON.color((0.502,)*3) == 0.502`, `GAMMA_OFF` -> 0.2158, clamp,
  `UNKNOWN` linear with note, `for_gamma(None) is UNKNOWN`, `of_scene` of a fixture -> `GAMMA_OFF`.
- [ ] Implement colors.py; wire `swatches` into both converters (default `colors.of_scene(graph.scene)` for a
  real reader Scene, else `UNKNOWN`; MaterialConverter defaults to its texmaps converter's rule).
- [ ] Update synthetic expectations (linear) in `test_convert_materials.py` / `test_texmaps.py`; add per-setting
  tests (VRayMtl diffuse 128, Mix color, VRayColor, CoronaColor hex under GAMMA_ON / GAMMA_OFF).
- [ ] `python -I -m unittest discover tests` -> OK. Commit.

### Task 3: report + ops

- [ ] Test (`test_report.py`): `add_materials(rep, ..., swatches=colors.GAMMA_ON)` -> text has
  `Color swatches: linear (the scene's gamma is on)`, no issue; `UNKNOWN` -> the note under Other issues and a
  WARNING summary.
- [ ] Implement; ops.py passes `colors.of_scene(sc)` to both converters and to `add_materials`.
- [ ] Unit tests OK. Commit.

### Task 4: fixture gamma_swatches

- [ ] Write `tools/fixtures/gamma_swatches.ms` (saves `C:\maxdrop_fixtures\gamma_swatches.max`), run it in an own
  `3dsmaxbatch`; `python -I tools/sanitize_fixture.py ...`; `python -I tools/check_fixture.py ...` -> clean; copy;
  oracle with `MaxDropOracle.dumpFile` in `3dsmaxbatch`.
- [ ] Fixture test: its VRayMtl diffuse 128 -> 0.50196 linear; VRayColor -> 0.50196; Mix colors -> 0.50196.
- [ ] Commit fixture + oracle + script + tests together.

### Task 5: docs, local parity

- [ ] FORMAT.md "Scene gamma"; SUPPORT.md color management; CHANGELOG 0.0.4 line; module docstrings.
- [ ] matparity.py (local): check for the sRGB rule; update; README.txt note. Run A, B, --fixtures.
- [ ] Close `maxdrop-em3.22` as superseded.

## Verification

**Working directory:** `D:\www\maxdrop`, branch `epic/maxdrop-arp`.

1. Plain tests: `python -I -m unittest discover tests` -> `OK`; again in a venv without numpy
   (`python -m venv <scratch>\nonumpy` then `<scratch>\nonumpy\Scripts\python -I -m unittest discover tests`) -> `OK`.
   Includes: gamma_swatches (gamma on) 128 swatch -> 0.502; every gamma-off fixture's 128 -> 0.216; images still
   sRGB (existing texmaps tests).
2. Build: `powershell -ExecutionPolicy Bypass -File build.ps1` -> `dist\maxdrop-0.0.4.zip`, check_zip passes.
3. Smokes on Blender 4.2.23, 4.5.16 (portable, `D:\tools\blender\...`) and installed 5.2, each headless with
   `BLENDER_USER_RESOURCES=<scratch>`: `tests/smoke_register.py` and `tests/smoke_import.py` -> `FIXTURES PASSED`
   (build-and-test skill commands).
4. Probe agreement (local): import `C:\maxdrop_fixtures\probe\gamma\render_vray_gamma.max` and
   `render_vray_none.max` in Blender 5.2 headless, render the swatch plane (emission, Standard view transform) ->
   byte 187 +- 5 (0.502 +- 0.02 linear) and 128 +- 5 (0.216); 3ds Max gave 187 / 128.
5. Local: `matparity.py` scene A and B >= 95 %, `--fixtures` passes.

**Success criteria:** all of the above; a missing optional tool (Corona render) is noted, not a failure.
