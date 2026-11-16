# VRayColor as a constant color Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VRayColor converts to a Constant (like CoronaColor), so a Falloff, a Color Correction or a Mix mask over
it gives its color instead of nothing.

**Architecture:** `reader/classids.py` gets `VRAY_COLOR` and its class name; `convert/texmaps.py` gets a
`_vray_color` rule in `_KEEP`, next to `_corona_color`, reading the parameters below. No builder change: a
Constant is drawn already. The `vray_texmaps` fixture (maxdrop-arp.12) already holds five VRayColors (diffuse with
RGB multiplier 1.5, reflection with color gamma 2.2, Falloff map 1, Color Correction input, Mix mask): no new
fixture.

**Tech Stack:** Python 3.11 syntax, standard library, `unittest`; 3ds Max 2020 + V-Ray 5.2 (`3dsmaxbatch` probes,
local only); Blender 4.2 / 4.5 / 5.2 headless.

---

## Facts

- ClassID `(0x58F82B74, 0x73B75D7F)` (oracle `tests/fixtures/vray_texmaps.oracle.json`, class name `VRayColor`).
- Block 0: 9 color_mode (0 RGB, 1 temperature), 8 temperature (6500), 0 / 1 / 2 red / green / blue (floats, the
  same values as color), 4 rgb_multiplier (1), 3 alpha (1), 5 color (swatch, 0..1), 10 color_gamma (1),
  11 rgb_primaries (0). Block 1 (transient, not saved): 6 gamma_correction, 7 gamma_value.
- Measured with `renderMap` (8-bit output, 3ds Max gamma 2.2; probe scripts kept outside the repo,
  `C:\maxdrop_fixtures\probe\vcolor\`):
  - 128 gray -> 128; multiplier 2 -> 255; color gamma g -> 255 * (c / 255) ^ g (2.2 -> 55.98, 0.4545 -> 186.4).
  - The multiplier comes before the gamma: (200 100 50, multiplier 1.5, gamma 2.2) -> (255, 79.35, 17.27) =
    (c * 1.5) ^ 2.2; (100, multiplier 2, gamma 2) -> 156.86.
  - Temperature mode: the render follows the temperature; V-Ray writes the temperature's color into `color` when
    the temperature is set in that mode and when the mode switches to it (3000 K -> 255 123.9 38.4, not
    kelvin_rgb's curve). Setting `color` while in temperature mode changes `color` but not the render: the only
    path where `color` is stale.
  - Mono (a Mix mask): the mean of the color (red 255 0 0 -> 85); the alpha does not enter it.
  - gamma_correction 1 / 2 and rgb_primaries 1 changed nothing in `renderMap`.

## Rule

`_vray_color`: swatch = `color` (5), else red / green / blue (0..2), else white; times the multiplier (finite,
>= 0, else 1 and an issue); then ^ color_gamma (0.01..100, else 1 and an issue) per channel; then decoded from
sRGB like every swatch (`_linear`, which clamps to 0..1). COLOR: the linear RGB; other kinds: the mean of it (the
convention of `_constant`). Temperature mode: `color` (V-Ray keeps it in step) and an issue only if the mode is
neither 0 nor 1. alpha below 1: an issue (it matters only where a map's alpha is used, e.g. as a Composite layer).
rgb_primaries other than 0: an issue (drawn as sRGB). Never an exception.

## Chunk 1: code and tests

### Task 1: ClassID

- [ ] `maxdrop/reader/classids.py`: `VRAY_COLOR = ClassId(0x58F82B74, 0x73B75D7F)`, CLASSES name `VRayColor`.
- [ ] `tests/unit/test_texmaps.py::VRayTexmaps.test_class_ids_match_the_class_directory`: add it.

### Task 2: tests first (fail before the rule)

- [ ] `VRayTexmaps`: FixtureVColor base_color = Constant(_linear(200*1.5, 100*1.5, 50*1.5)) clamped;
  specular = Constant of (128/255)^2.2 decoded; FixtureVFalloff base_color = Constant(lin(50,150,250)) (Falloff
  peeled); FixtureCCColor = ColorCorrect over Constant(lin(100,200,50)), saturation 1.2; FixtureMixMask mask =
  Constant(mean lin 64); stats.unsupported = {Noise: 1}.
- [ ] `VRayColorSynthetic`: multiplier then gamma; red / green / blue fallback; bad values -> issue and default;
  data kind = mean; temperature mode reads color; alpha and primaries issues.

### Task 3: the rule

- [ ] `maxdrop/convert/texmaps.py`: constants `VC_*`, `_vray_color`, `_KEEP` entry, module docstring line.
- [ ] `python -I -m unittest discover tests` -> OK.

### Task 4: docs

- [ ] `docs/SUPPORT.md` map table: VRayColor row imported, removed from "Every other map".
- [ ] `docs/FORMAT.md` texmap table: VRayColor parameters.
- [ ] `CHANGELOG.md` under `## [0.0.4]`: VRayColor as a color.
- [ ] `tests/smoke_import.py` docstrings: vray_texmaps' unsupported class is now Noise only.

## Verification

- `python -I -m unittest discover tests` -> OK; again in a venv without numpy -> OK.
- `powershell -ExecutionPolicy Bypass -File build.ps1` -> dist zip; register + import smokes on Blender 4.2.23,
  4.5.16 and 5.2 (build-and-test skill, headless, isolated `BLENDER_USER_RESOURCES`) -> `FIXTURES PASSED` /
  `IMPORT PASSED`.
- Local only, if `matparity.py` and scenes A / B are present: A >= 213/214, B 220/220; `--fixtures` passes.
