# Standard map channels from the Texmaps object Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Standard material's map channels (map, on switch, amount) come from its Texmaps object, which 3ds Max
answers from, not from block 3's tables, which can keep the layout the material was created with (maxdrop-em3.148).

**Architecture:** `reader/materials.py` gains `standard_maps(scene, m)` (bpy-free, bounded): the Texmaps object
(superclass 0x1080, class (0x1200, 0)) referenced by the material; its leaf `0x5003` (u32 on mask, bit k = channel
k), its leaves `0x5100 + k` (f32 amount where not 1.0) and its references `2k + 1` (the map of channel k; `2k` is
the amount's Bezier Float). `convert/materials.py` `standard_mtl` reads it once and `_std_map` takes the channel
from it; block 3's tables only when the material has no readable Texmaps object (per material, never per channel).

**Tech Stack:** Python 3.11, plain unittest; 3ds Max 2020 for the probe and the fixture; Blender 4.2/4.5/5.2 smoke.

---

## Probe (done, scratch outside the repo)

3ds Max 2020, batch and an own interactive instance, saves of one change each:

- `0x5003` is the on switch: a map switched off clears its bit; a channel switched on without a map sets it. It
  equals 3ds Max's `mapEnables` in every case.
- Block 3's maps and mapEnables go stale like mapAmounts: a Blinn material with diffuse and bump maps switched to
  Anisotropic keeps the bump map and its enable at Blinn's channel 8 in the table; 3ds Max answers channel 11, and
  the Texmaps object has it there (reference 23, bit 11, `0x510b` = 0.3).
- The leaves sit directly in the Texmaps object's chunk in all 58 committed fixtures (no `0x0003` container).

## Task 1: fixture

**Files:** `tools/fixtures/standard_maps.ms`, `tests/fixtures/standard_maps.max`, `tests/fixtures/standard_maps.oracle.json`

- [ ] Append after the last node: `FixtureMapsSwitchedAfter` (created Blinn, diffuse and bump maps with their
      amounts untouched, then switched to Anisotropic) and `FixtureMapsSwitchedOff` (Anisotropic, self-illumination
      and bump maps, the bump switched off). No reads of the material before the save.
- [ ] Run in an own interactive 3ds Max 2020, sanitize, check (clean), copy, regenerate the oracle (`dumpFile`).

## Task 2: reader

**Files:** `maxdrop/reader/materials.py`, `tests/unit/test_materials.py`

- [ ] `StdMaps(maps, enabled, amounts)` with `channel(k) -> (map index or None, on, amount)`;
      `standard_maps(scene, m)` -> StdMaps or None (no Texmaps object, a leaf of the wrong size, no 0x5003,
      a MaxFileError). Channels below 32; a reference that leaves the objects or is not a texmap is no map.
- [ ] Parity: for every Standard material of every fixture, the reader's channels equal the oracle's block 3
      (maps, mapEnables, mapAmounts) at every channel; Parity.stale's mapAmounts skip goes.
- [ ] Synthetic: damaged leaves give None; a reference past the objects is no map.

## Task 3: convert

**Files:** `maxdrop/convert/materials.py`, `tests/unit/test_convert_materials.py`

- [ ] `standard_mtl` reads `standard_maps` once; `_std_map(conv, m, slot, ir, invert, channels)` takes map, on and
      amount from it, the table without it (FakeMtl tests).
- [ ] StandardMaps: FixtureMapsUnsetAmounts self-illumination 1.0, bump 0.3 (and its table still stale: 0.3 at 8);
      FixtureMapsSwitchedAfter diffuse and bump at 0.3 in their inputs, no self-illumination map;
      FixtureMapsSwitchedOff no bump. Red check against the old `_std_map`.

## Task 4: docs

- [ ] docs/FORMAT.md (Standard map paragraph), docs/SUPPORT.md (drop the known issue), CHANGELOG.md (Fixed).

## Verification

- `python -I -m unittest discover tests` -> OK
- `python -I tools/lint.py` -> exit 0
- `powershell -ExecutionPolicy Bypass -File build.ps1` -> dist zip
- `tests/smoke_register.py`, `tests/smoke_import.py` and `tests/blender/run.py` on Blender 4.2.23, 4.5.16, 5.2
  (headless, isolated profile in the session scratch) -> exit 0
- Red check: the new StandardMaps tests fail with the old `_std_map`.
