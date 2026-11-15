# M2 gate (version 0.0.4) Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove milestone M2 (materials and textures) against 3ds Max on the fixtures and on the two corpus scenes,
measure the import, and prepare release 0.0.4, not pushed.

**Architecture:** No engine, operator or test code changes. Two gate measurements are throwaway scripts in the
session scratch folder (never committed: they take local paths, and their logs name scene materials); their
numbers, counts and class names only, go into the bead notes and `docs/BASELINE.md`. The repository changes are the
version bump, the CHANGELOG section and the docs that must be true for 0.0.4.

**Tech Stack:** Python 3 (plain), `3dsmaxbatch.exe` of 3ds Max 2020 (headless, an own process: an interactive Max
that runs is left alone), Blender headless (`--background --factory-startup`, isolated `BLENDER_USER_RESOURCES`),
`tools/baseline.py`, `python -m http.server`.

---

## Facts

- The corpus oracle dumps of M1 are layout 1 (no `material_graph`). Layout 2 dumps of scene A and scene B were made
  in this session with `3dsmaxbatch.exe` running `MaxDropOracle.dumpFile` (`tools/oracle/dump_scene.ms`) into the
  scratch folder: A 746 nodes, 726 graph entries (214 materials), dump 29 s; B 2,251 nodes, 560 entries (220
  materials), dump 32 s. The batch exits 127 ("Task Completed with Error(s)") only because a third-party DLL
  (Chaos Scatter) fails to initialize; the dump line is written. The reader reached 726 and 560 too (bead arp.1).
- A Bitmap's file (block 0, param 13, type bitmap) is `null` in the oracle; its transient `fileName` (param 16)
  holds the base name. A CoronaBitmap's file (param 101, type file name) is the base name.
- The rules read three things that are not parameters, from raw chunks: UVGen flags / axis / source / channel,
  the Output's invert flag, the Bitmap's gamma override. The oracle has no such field: both sides read them from
  the file.
- Released versions: 0.0.1, 0.0.2, 0.0.3 (GitHub releases, tags local). The previous version for the upgrade test
  is the released `maxdrop-0.0.3.zip`.
- A/B render needs the owner's Blender session or their FBX export and the owner's word on how; this session is
  unattended (no questions): it is reported as not done, with that reason.
- Corona: bead arp.7 verified five Corona 12 fixtures (raw-param parity, Blender textured check on 4.2 / 4.5 / 5.2)
  and the one older Corona scene of the corpus (13 CoronaLegacyMtl, 0 grey, 5 textured, 6/6 images found).

## Files

- Modify: `maxdrop/blender_manifest.toml` (`version = "0.0.4"`)
- Modify: `CHANGELOG.md` (`## [Unreleased]` becomes `## [0.0.4] - 2026-11-16`, a new empty `## [Unreleased]`)
- Modify: `docs/SUPPORT.md` (describes 0.0.4; the trust paragraph gains the corpus material parity; BASELINE pointer)
- Modify: `docs/BASELINE.md` (0.0.4 measurement beside 0.0.1 and 0.0.3; material parity table)
- Modify: `README.md`, `site/index.html` (materials no longer from io_scene_max's code; the materials list as
  converted now; the "Materials arrive without textures" answer: nested maps are now followed)
- Modify: `SECURITY.md` ("Known limits of this version": the inherited parser is gone)
- `tests/test_site.py`: only if a sentence it asserts changes
- Scratch, not committed: `matparity.py`, `upgrade.py`

## Chunk 1: Gate measurements (scratch, results in bead notes)

### Task 1: raw-param parity on the fixtures

- [ ] `python -I -m unittest tests.unit.test_materials -v` -> every fixture's parity test `ok`; record the values
      compared per V-Ray fixture (the test's floors: vray_basic 190, vray_maps 630, vray_wrappers 2000,
      standard_physical 290).

### Task 2: per-material IR parity — `matparity.py`

What "matching" means: the material's IR made from MaxDrop's reader equals the IR the same rules make from the
parameters 3ds Max reports. The oracle side is an adapter with the interface the rules read (`MaterialGraph.get /
superclass / scene`, `MtlBase.param / block / blocks / legacy / parts / children / refs`, `AssetTable.entry`), filled
from `material_graph`:

- [ ] Pair oracle entries with reader objects: node roots by walk position (`scene.walk()` order = oracle `nodes`),
      each node's `materials[k]` located in `material_graph` by rebuilding Max's depth-first order (next unvisited
      root = next graph position; its subtree = everything reachable over `subs` and material / map parameters),
      then pairs spread through every material / map parameter (oracle graph index <-> reader `Reference`) and
      `subs` slot. A conflict (one oracle entry, two reader objects) or an unpaired entry is a structural miss.
- [ ] Oracle blocks: pb2 params that are not transient and not `removedParam`, by id, tables as lists, colors and
      points as tuples, references as `Reference(reader index)` (an unpaired target gets an index past the object
      list, so it can never equal a reader index); Bitmap param 13 = the file of param 16, CoronaBitmap 101 = its
      base name, given to an asset adapter whose entry has that name. pb1 by index. Parts at their reference slot,
      the part's object index and superclass from the reader's part at that slot (raw-chunk fields shared).
- [ ] Both sides: `TexmapConverter(graph, assets, textures=None)` + `MaterialConverter(graph, texmaps=tex)`;
      per oracle material entry (superclass 3072) with a pair `r`: `convert(r)` on both; a Multi/Sub-Object also
      compares `_multi(r)` (ID -> sub-material).
- [ ] Compare the two IRs field by field, recursively through `textures` (TextureGraphIR roots and their nodes):
      numbers within `1e-3 * max(1, |oracle|)`, booleans / ints / strings equal, object indices equal (both in the
      reader's index space), Image `name` equal without regard to case; not compared: `name` of the material (a
      label, not a channel), `issues`, Image `path` / `resolved` / `found`.
- [ ] Print per scene: materials, paired, matching, share; failing material classes and the first differing field
      kind per class (counts and class names only); same run over every committed fixture (`tests/fixtures`).
- [ ] Gate: >= 95 % per scene. A miss: list failing classes, mark the bead blocked, stop (do not lower the target).

### Task 3: time and memory — `tools/baseline.py`

- [ ] Scene A, then scene B, Blender 5.2, operator default options, results in the scratch folder.

## Chunk 2: Version and docs

### Task 4: bump and docs

- [ ] `version = "0.0.4"`; CHANGELOG `## [0.0.4] - 2026-11-16` (the Unreleased content) + an empty Unreleased.
- [ ] `docs/SUPPORT.md`: "This page describes version 0.0.4."; trust paragraph: corpus per-material parity numbers;
      BASELINE pointer (0.0.4 next to 0.0.3).
- [ ] `docs/BASELINE.md`: section "Version 0.0.4: MaxDrop's materials" (table beside 0.0.1 / 0.0.3 + material
      parity table + what fails by class).
- [ ] `README.md` / `site/index.html`: early-release note and support list match 0.0.4.
- [ ] `SECURITY.md`: limits paragraph for 0.0.4.
- [ ] `python -I -m unittest discover tests` -> `OK`; commit `Set version 0.0.4 and make the docs true for it`.

## Verification

Working directory: the repo root. Blender paths in the bead notes (5.2 installed, 4.2.23 and 4.5.16 portable).
Each Blender run: `BLENDER_USER_RESOURCES=<scratch>\profile-<tag>` + `--background --factory-startup
--python-exit-code 1` (`--online-mode` for block 7).

1. `python -I -m unittest discover tests` -> `OK`
2. `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...\dist\maxdrop-0.0.4.zip ...`
3. `tests/smoke_register.py` -> `SMOKE PASSED` on 5.2, 4.2.23, 4.5.16
4. `tests/smoke_import.py` (no arguments: every committed fixture, also as packs) -> `IMPORT PASSED` on all three,
   `COUNTS` equal
5. `tests/blender/run.py` -> `FIXTURES PASSED` on all three
6. CHANGELOG check -> one line `## [0.0.4] - 2026-11-16`
7. Install from a localhost repository and upgrade (build-and-test block 7 with v1 = the released
   `maxdrop-0.0.3.zip` + its `server-generate`d index, v2 = `dist\maxdrop-0.0.4.zip` + index) -> `UPGRADE PASSED` on
   5.2 and 4.2.23
8. `matparity.py`: scene A and scene B >= 95 % matching materials; raw-param parity tests `ok`; baseline: both
   `"outcome": "finished"`, `"traceback": false`
9. Close note states: A/B render not done (reason), Corona verified on Corona 12 fixtures + one older scene

**Success criteria:** every command above reports its pass line with exit 0. A missed number fails the bead: say which
and by how much.

## Gate result 2026-11-16: blocked before Chunk 2

- Raw-param parity: `tests/unit/test_materials.py` OK on every fixture.
- Per-material IR parity (Task 2, scratch tool kept outside the repository, location in the bead notes): fixtures
  49 of 49 materials match (a 10 % perturbation of the oracle's floats makes all 49 fail: the check compares);
  scene B 220 of 220 (100 %); **scene A 175 of 214 (81.8 %), below the 95 % target.**
- Cause (scene A only): it is a file of format 14000 (saved by 3ds Max 2015 in the 2012 format). None of its
  ParamBlock2 objects has the 0x0013 owner-reference table, and for some P_OWNERS_REF map parameters the stored
  object index is -1 although 3ds Max reports the map set: the reader reads an empty reference. 126 references
  in 39 materials: Color Correction `map` (44), Mix `map1` / `map2` / `mask` (49), Falloff `map1` / `map2` (18),
  VRayMtl `texmap_diffuse` / `texmap_reflection` / `texmap_bump` (13), Output `map1` (2). Failing classes:
  VRayMtl 32, Multi/Sub-Object 6, VRayBlendMtl 1.
- The owner slot of each is a constant of its class (the parameter definition's reference number), equal in every
  object of scene A and to what the 0x0013 tables of scene B (format 20000) say, e.g. Mix 6 -> 1, 7 -> 2, 8 -> 3;
  Color Correction 1 -> 1; Falloff 2 -> 4, 6 -> 5; VRayMtl block 4: param 100 + k -> slot 7 + k. A projection
  that fills the empty references from such a per-ClassID table gives scene A 213 of 214 (99.5 %).
- The fix is in `maxdrop/reader/pblock.py` (outside this bead's Files): stopped, bead blocked for the owner's
  decision. Chunk 2 (bump, docs, baseline, upgrade test) waits for the rerun.
