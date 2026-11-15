# M1 gate (version 0.0.3) Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove milestone M1 (fixtures equal the oracle, both corpus scenes within the 99 % target, time and memory
recorded) on Blender 5.2, 4.2.23 and 4.5.16, and prepare release 0.0.3, not pushed.

**Architecture:** No engine, operator or test code changes. The corpus scoreboard is a throwaway Blender script in
the session scratch folder (never committed: it takes local paths and its log names scene objects); its numbers,
counts only, go into the bead notes and `docs/BASELINE.md`. The repository changes are the version bump, the
CHANGELOG section and the docs that must be true for 0.0.3.

**Tech Stack:** Blender headless (`--background --factory-startup`, isolated `BLENDER_USER_RESOURCES`),
`tools/baseline.py`, `python -m http.server`.

---

## Files

- Modify: `maxdrop/blender_manifest.toml` (`version = "0.0.3"`: 0.0.2 shipped with the scene-packs gate)
- Modify: `CHANGELOG.md` (`## [Unreleased]` becomes `## [0.0.3] - 2026-11-15`, a new empty `## [Unreleased]` above)
- Modify: `docs/SUPPORT.md` (describes 0.0.3; the import report moves from "What comes next" into what this version
  imports; the BASELINE pointer says the new reader is measured)
- Modify: `docs/BASELINE.md` (keeps the M0 table, adds the 0.0.3 measurement beside it, scene A / scene B, counts only,
  and the scoreboard)
- Modify: `README.md`, `site/index.html` (the import report in *Use*)
- Modify: `SECURITY.md` ("Known limits of this version": the own reader has bounded reads; the materials still go
  through the inherited parser)
- `tests/test_site.py`: changes only if a sentence it asserts changes (none planned)
- Scratch, not committed: `scoreboard.py` (convert.scene.read + build, every node vs the corpus oracle by walk
  position), `upgrade.py` (build-and-test block 7, installing the released version first)

## Chunk 1: Gate measurements (scratch, results in bead notes)

### Task 1: Corpus scoreboard — `scoreboard.py`

- [ ] In Blender 5.2: import the dev package from the repo root, `convert.scene.read(<scene>)`, `build.collections.make`
      + `build.objects.build` + `finish`, `view_layer.update()`.
- [ ] Per node (walk position = oracle index; check node count and names equal): skip nodes with oracle modifiers;
      world matrix as the oracle's 12 floats (translation in file units) within `max(1e-4, 1e-5*|oracle|)` (the oracle
      prints `%.6g`, so a strict absolute 1e-4 is reachable on about 0.3 % of nodes: also printed); mesh objects: world
      vertex extremes vs `bbox_min/max` within `max(1e-3, 1e-5*|oracle|)`.
- [ ] Print per scene: in scope, matrix / bbox / both shares, failing classes, placeholders by class, sheared nodes.
- [ ] Gate: both >= 99 % for scene A and scene B. A miss: list failing classes, mark the bead blocked, stop.

### Task 2: Time and memory — `tools/baseline.py`

- [ ] Scene A, then scene B, Blender 5.2, operator default options, results in the scratch folder.

## Chunk 2: Version and docs

### Task 3: Bump and docs

- [ ] `version = "0.0.3"`; CHANGELOG section `## [0.0.3] - 2026-11-15` (the Unreleased content) + an empty Unreleased.
- [ ] `docs/SUPPORT.md`: "This page describes version 0.0.3."; the report row; "What comes next" without the report;
      BASELINE pointer.
- [ ] `docs/BASELINE.md`: section "Version 0.0.3: MaxDrop's reader" beside the M0 table, plus the scoreboard.
- [ ] `README.md` / `site/index.html`: one sentence on the **MaxDrop Report** text after an import.
- [ ] `SECURITY.md`: the limits paragraph for 0.0.3.
- [ ] `python -I -m unittest discover tests` -> `OK`; commit `Set version 0.0.3 and make the docs true for it`.

## Verification

Working directory: the repo root. Blender paths in the bead notes (5.2 installed, 4.2.23 and 4.5.16 portable).
Each Blender run: `BLENDER_USER_RESOURCES=<scratch>\profile-<tag>` + `--background --factory-startup
--python-exit-code 1` (`--online-mode` for block 7).

1. `python -I -m unittest discover tests` -> `OK`
2. `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...\dist\maxdrop-0.0.3.zip ...`
3. `tests/smoke_register.py` -> `SMOKE PASSED` on 5.2, 4.2.23, 4.5.16
4. `tests/smoke_import.py` (no arguments: every committed fixture, also as a zip pack) -> `IMPORT PASSED` on all three
5. `tests/blender/run.py` -> `FIXTURES PASSED` on all three
6. CHANGELOG check -> one line `## [0.0.3] - 2026-11-15`
7. Install from a localhost repository and upgrade (build-and-test block 7, served v1 = the released 0.0.2 zip built
   from `git archive v0.0.2 maxdrop`, v2 = `dist\maxdrop-0.0.3.zip`), then `import_scene.maxdrop` on a fixture ->
   `UPGRADE PASSED` and the import `FINISHED` on 5.2 and 4.2.23; also from 0.0.1 on both
8. Scoreboard: scene A and scene B >= 99 % matrix and bbox (in-scope nodes), no traceback; baseline: both
   `"outcome": "finished"`, `"traceback": false`

**Success criteria:** every command above reports its pass line with exit 0. A missed number fails the bead: say which
and by how much.
