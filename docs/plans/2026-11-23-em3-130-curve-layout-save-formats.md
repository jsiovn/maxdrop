# Curve Control layout in other save formats Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find out whether the Custom Curve Control layout `reader/materials.mix_curve` reads (`0x1000` point
count, one `0x1030` per point holding a 28-byte `0x1000`) holds in files saved in older formats, and record it.

**Architecture:** A probe outside the repo runs `tools/fixtures/falloff_curve.ms` as it is on the branch (output
redirected into the probe folder) in headless 3dsmaxbatch, saves the scene as 2017, 2018 and 2019, loads each
again and evaluates every Falloff curve (`ICurve.GetValue`). A plain-Python script reads every variant (and the
local corpus scenes, counts only) with `mix_curve`. The layout holds, so no reader change: docs/FORMAT.md gets
the result under Open (the header rule: the main sections hold only what a committed fixture shows).

**Tech Stack:** 3ds Max 2020 (3dsmaxbatch), Python 3.11 reader, Markdown.

---

## Results (probe C:\maxdrop_fixtures\probe\em3_130, outside the repo)

- 3ds Max 2020.2 (22.2.0.2176) saved falloff_curve as 2017, 2018, 2019 (file versions 19000, 20000, 21000;
  writer 22000). Every variant: 6 Falloffs, 6 curves read by mix_curve, 0 failed; curve chunk shape
  `2035:4, 204b:1, 1000:4, 1030[1000:28] x n, 1020:4, 1040:28` in all four files; the points (positions,
  handles, flags) equal those of the 2020 file. Reloaded in 3ds Max, the GetValue tables of all four files are
  byte-identical (same md5).
- Corpus scene A (3ds Max 2015, saved in the 2012 format): 60 Falloffs, 60 curves read, 0 failed, same shape
  (34 not the default curve; 2 to 5 points); its 3ds Max 2020 re-save gives the same points. Scene B (3ds Max
  2020 saved as 2018): 23 of 23 read, same shape. Flags seen there beyond the fixture's: `0x1`, `0x11`,
  `0x103`, `0x110`, `0x113`; nothing in maxdrop/ reads a curve point's flags.
- A newer 3ds Max than 2020: not available on this machine; not known.
- No fixture committed: a 2017 copy of falloff_curve adds about 0.9 MB of public history and an entry in every
  per-fixture table for a test that repeats the existing one; regenerating saved_as_* moves three fixtures, their
  oracles and the string, census and floor tests.

### Task 1: docs/FORMAT.md

**Files:** Modify: `docs/FORMAT.md` (Open; a pointer line under The Falloff mix curve). Add lines only: part F
edits the file too.

- [x] Add an Open item: the curve layout and points read the same in 3ds Max 2020's saves as 2017 / 2018 / 2019
  (probe, not committed) and in corpus scenes A and B; the extra flag values; a newer 3ds Max not known.
- [x] Add one pointer sentence at the end of The Falloff mix curve's layout paragraph to that Open item.
- [x] `python -I -m unittest discover tests` -> OK, `python -I tools/lint.py` -> clean.
- [x] Commit `Record the curve layout in older save formats` (Bead: maxdrop-em3.130).

### Task 2: bead notes

- [x] Append the results above (scene A / scene B only, no file names or paths of the corpus) to the bead notes.

## Verification

Docs only (build-and-test's table: block 1). No fixture, no code: no Blender run, no red check (nothing fixed).

```powershell
python -I -m unittest discover tests   # OK
python -I tools/lint.py                 # All checks passed!
```
