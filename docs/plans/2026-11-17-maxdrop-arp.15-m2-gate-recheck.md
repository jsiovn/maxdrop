# M2 gate recheck (A/B render, parity, 0.0.4 docs) Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-check the M2 gate after maxdrop-arp.12 (VRayBitmap), .13 (VRayColor) and .14 (a lost map is not
the wrapper's color): rerun the A/B render against the FBX route and the parity gate, and make the 0.0.4 docs
true and dated, without releasing.

**Architecture:** No engine code changes are planned. The A/B render reruns the local scripts of the first run
(outside the repository: the corpus is commercial) into a separate `recheck` folder so the first run's evidence
stays as it was. Its verdict goes to a local `findings_recheck.md`; only counts, class names and rules reach the
repository or the bead. If the pass bar fails, the bead is blocked with the remaining cases and nothing is fixed
here.

**Tech Stack:** Blender 5.2 headless (`--background --factory-startup`, isolated `BLENDER_USER_RESOURCES`), plain
Python 3 (numpy, Pillow) for the comparison scripts, the local `matparity.py`.

---

## Facts

- The first A/B run (2026-11-17, commit 27528f2) failed with 11 materials (findings.md, "MaxDrop bug" rows): in
  scene A a Falloff over a VRayColor (2 materials), a Color Correction over a VRayColor (1), a plain VRayColor
  (1), a Mix with amount 0 and a VRayColor mask (4), a Color Correction over a Composite of VRayBitmaps (1); in
  scene B a VRayBitmap in diffuse (1) and a Color Correction over a VRayBitmap (1).
- Route B's FBX exports (`fbx_a\`, `fbx_b\`) exist; no new 3ds Max export is needed.
- `CHANGELOG.md` already has `## [0.0.4] - 2026-11-16` with the lines of .12 to .14; `docs/SUPPORT.md` has the
  VRayBitmap and VRayColor rows and the lost-map behavior. README and the site do not list map classes beyond
  Mix / Color Correction, which stay true.

## Files

- Modify: `CHANGELOG.md` (0.0.4 dated the day the bead closes: 2026-11-17; lines of .12 to .14 checked)
- Modify: `docs/SUPPORT.md` only where it is not true for the code
- Local only (never committed): `C:\maxdrop_fixtures\oracle\m2gate\ab\recheck\` (script copies, renders, logs),
  `ab\findings_recheck.md`

## Chunk 1: A/B rerun

### Task 1: script copies writing to `recheck`

- [ ] Copy `ab\scripts\*.py` to `ab\recheck\scripts\`; in the copies `AB` points at `ab\recheck`, the FBX paths
      and `REPO` stay; `camfix_A.json` is copied to `recheck\renders\`.

### Task 2: renders and material dumps, both routes, both scenes

- [ ] For scene in A, B: route b then route a:
      `BLENDER_USER_RESOURCES=ab\profile blender --background --factory-startup --python-exit-code 1 --python
      recheck\scripts\render_route.py -- --route <r> --scene <s>` (log to `recheck\logs\render_<s>_<r>.log`),
      then `mat_compare.py` the same way. Expect `ROUTE DONE` and `MATS` lines, exit 0.
- [ ] `compose.py` (Blender), `analyze.py`, `mat_diff.py`, `evidence.py` (plain `python -I`).

### Task 3: verdict

- [ ] For each of the 11 materials: the MaxDrop base color now (image / constant / swatch) against the oracle tree
      and the FBX route; the zoomed evidence crops; any new difference in `matdiff_*.txt` and `analysis_*.txt`
      against the first run.
- [ ] Write `ab\findings_recheck.md`; pass bar = no material grey, untextured or clearly wrong in MaxDrop but right
      in the FBX route (filed approximations maxdrop-em3 and the documented gaps excluded).

## Chunk 2: parity and docs

- [ ] From `C:\maxdrop_fixtures\oracle\m2gate`: `python -I matparity.py D:\www\maxdrop <scene A> scene_a.v2.oracle.json
      "scene A"`, the same for B, and `python -I matparity.py D:\www\maxdrop --fixtures` -> A >= 213/214, B 220/220,
      fixtures all.
- [ ] `python -I -m unittest tests.unit.test_materials -v` (raw-param parity) -> OK.
- [ ] CHANGELOG 0.0.4 date -> 2026-11-17; SUPPORT checked against `convert/texmaps.py`.
- [ ] Commit `Date the 0.0.4 changelog for the gate recheck`.

## Verification

Working directory `D:\www\maxdrop`, branch `epic/maxdrop-arp`.

- `python -I -m unittest discover tests` -> OK; again in a venv without numpy -> OK.
- `powershell -ExecutionPolicy Bypass -File build.ps1` -> `dist\maxdrop-0.0.4.zip`; register and import smokes and
  `tests/blender/run.py` FIXTURES PASSED on Blender 5.2, 4.2.23 and 4.5.16 (portable paths from local memory notes),
  each headless with an isolated `BLENDER_USER_RESOURCES`.
- Localhost install of the released 0.0.3 zip and upgrade to the built 0.0.4 on 5.2 and 4.2 (build-and-test
  recipe) -> UPGRADE PASSED.
- `findings_recheck.md`: pass bar met; matparity >= 95 % on both scenes.
- Failure of the pass bar: `bd update maxdrop-arp.15 --status blocked` with class and rule only, no scene or
  material names.
