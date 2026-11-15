# Oracle: ground truth from 3ds Max Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A MAXScript that writes what 3ds Max itself says about a scene as deterministic JSON, the oracle files of
the nine fixtures, and the same dump of the two corpus scenes kept outside the repository.

**Architecture:** One MAXScript file, `tools/oracle/dump_scene.ms`, defines a global struct `MaxDropOracle` with
`dumpScene <out>` (the open scene), `dumpFile <max> <out>` (reset, load quietly with the file's units, dump,
restore the session's system unit) and `dumpFolder <dir> <outDir>` (every `*.max` of a folder into
`<name>.oracle.json`). It builds the JSON by hand: keys written in sorted order, floats with `%.6g`, every
non-ASCII or control character escaped as `\uXXXX`, LF line ends, written through .NET so nothing translates
them. A plain-Python test checks the committed oracle files (one per fixture, sorted keys, ASCII, the box values,
the private-string scan). No dependency on any bridge: the bridge only sends one line of MAXScript.

**Tech Stack:** MAXScript on 3ds Max 2020 (driven through the 3dsmax-mcp bridge, port 8766 this session);
Python 3.11 standard library for the test.

Bead: `maxdrop-too.2`.

---

## Decisions

- **Scene order** = pre-order walk of `rootNode.children` (a node, then its children in Max's child order).
  `index` is the 0-based position in that walk; `node_count` its length.
- **Handles**: `node.handle`. Checked stable across a reset + reload (the determinism check reloads).
- **Material handle**: Max materials have no persistent handle, so `material` is the index into the top-level
  `materials` list (materials in order of first use by the node walk). Session anim handles would break the
  byte-identical rule.
- **Class ids**: `["0x%08x", "0x%08x"]` = `classID[1], classID[2]` (= `classA, classB` of `ClassDirectory3`).
  `superclass` = the decimal super class id (`GEOMOBJECT` = 16). The class name is informational only.
- **Counts**: `eval_verts` / `eval_faces` = the evaluated world-state mesh as triangles (`snapshotAsMesh`),
  `null` when the node's world state is not geometry or cannot become a mesh. `base_verts` / `base_faces` = the base
  object: polygons for Editable Poly (`polyop`), triangles for Editable Mesh, `null` for any other class.
- **Instances**: sorted handles of every node whose `baseObject` is this node's base object (self included), found
  through `refs.dependentNodes`.
- **Bounding box**: `nodeGetBoundingBox node (matrix3 1)`, the tight world box of the evaluated points. Measured
  during implementation: `node.min` / `node.max` transform the local box and were 7 units too large per side on a
  rotated sphere of radius 10; `nodeGetBoundingBox` equalled the vertex extremes (rotated, bent, parented sphere).
- **Floats**: `%.6g`; `-0` -> `0`; inf / nan -> `null`. Matrices are 12 floats, rows 1-4 (row 4 = translation).
- **File identity**: `file` = base name only, never a path. Corpus dumps: `C:\maxdrop_fixtures\oracle\` (local,
  outside the repo; named "scene A" / "scene B" in anything committed).
- **Units on load**: `loadMaxFile ... useFileUnits:true quiet:true`, so values are in the file's own units; the
  session's system unit, scale and display units are restored afterwards (the Max here runs in millimeters).
- **Time** (after review): every node is evaluated `at time 0f`; top-level `time` = 0.

## JSON layout (oracle_version 1)

Top level: `file`, `file_version` (`getMaxFileVersionData`: format version, version of the Max that saved it), `layers` (layer
manager order: `frozen`, `hidden`, `name`, `renderable`), `materials` (`class_id`, `class_name`, `index`, `name`,
`sub_count`), `max_version` (running Max: release, year), `node_count`, `nodes`, `oracle_version`, `renderer`
(`class_id`, `class_name`), `units` (`display_metric`, `display_type`, `display_us`, `system_scale`,
`system_type`).

Node: `base_class_id`, `base_class_name`, `base_faces`, `base_superclass`, `base_verts`, `bbox_max`, `bbox_min`,
`eval_faces`, `eval_verts`, `frozen`, `handle`, `hidden`, `index`, `instances`, `layer`, `material`, `modifiers`
(top to bottom: `class_id`, `class_name`), `name`, `object_transform` (12 floats), `offset_pos`, `offset_rot`
(quat x y z w), `offset_scale`, `parent` (handle or `null`), `renderable`, `transform` (12 floats).

## Files

- Create `tools/oracle/dump_scene.ms`.
- Create `tests/fixtures/<name>.oracle.json` x 9 (generated, never hand-edited).
- Create `tests/test_oracle.py` (plain Python; checks the committed oracle files).
- Create `docs/ORACLE.md`: how to run, every field.
- Modify `CONTRIBUTING.md` only if its layout table lists tools (add `tools/oracle/`).

## Tasks

### Task 1: dump_scene.ms
- [ ] Helpers: `num`, `str` (escape), `vec`, `mat12`, `quat4`, `cid`, `bool`, `intOrNull`.
- [ ] `nodeJson`, `collectNodes` (pre-order), materials table, layers, units, renderer, `dumpScene`.
- [ ] `dumpFile`, `dumpFolder` (sorted file list, restore units, `gc light:true` every 100 nodes).
- [ ] Probe on box_poly_standard through the bridge; fix until it writes valid JSON.

### Task 2: tests/test_oracle.py (red first: no oracle files yet)
- [ ] Every fixture has `<name>.oracle.json` and no oracle file lacks its fixture.
- [ ] Each parses, is ASCII, LF only, ends with `\n`, keys sorted at every level (`object_pairs_hook`),
  `oracle_version == 1`, `node_count == len(nodes)`, every node has all node keys, `index` runs 0..n-1,
  `parent` is `null` or a handle in the file, `material` is `null` or a valid index.
- [ ] box_poly_standard: one node, translation `[10,20,0]`, bbox `[0,5,0]..[20,35,40]`, base 8 verts / 6 faces.
- [ ] `check_fixture.problems(bytes)` is empty for every oracle file.
- [ ] Run: fails (files missing).

### Task 3: generate the fixture oracles
- [ ] `MaxDropOracle.dumpFolder @"<ROOT>\tests\fixtures" @"<ROOT>\tests\fixtures"`.
- [ ] Determinism: dump box_poly_standard and hierarchy twice into `S` (each run resets and reloads); `fc /b` identical.
- [ ] Spot checks against the authoring scripts: hierarchy (5 nodes, two `FixtureTwin`, negative scale leaf),
  instances (one base shared by 3 handles + a copy alone), units_* (system_type differs), layers_flags (flags).
- [ ] Bounding box check on hierarchy: `node.min/max` vs the snapshot vertex extremes.
- [ ] Test green.

### Task 4: corpus dumps (outside the repo, one scene at a time)
- [ ] `dumpFile` scene A -> `C:\maxdrop_fixtures\oracle\scene_a.oracle.json`, then scene B; record node count, wall
  time, Max peak working set; reset Max after each. `git status` shows nothing of them.
- [ ] Record location + timings in the bead notes (no asset names).

### Task 5: docs/ORACLE.md, commit
- [ ] How to run (bridge or listener one-liners), the field table, the decisions above.

## Verification

Run from `ROOT`. `S` = session scratchpad. `MX` = a one-line MAXScript sent through the 3dsmax-mcp bridge (here:
`<bridge venv python> S\mx.py <file.ms>` on port 8766).

1. `python -I -m unittest discover tests` -> `OK` (includes tests/test_oracle.py).
2. Determinism: MX `fileIn @"<ROOT>\tools\oracle\dump_scene.ms"; MaxDropOracle.dumpFile @"<ROOT>\tests\fixtures\box_poly_standard.max" @"<S>\box1.json"`,
   again to `box2.json` -> `cmp box1.json box2.json` exit 0, and both equal `tests/fixtures/box_poly_standard.oracle.json`.
3. `python -I tools/check_fixture.py "tests/fixtures/*.oracle.json"` -> exit 0, `clean` per file.
4. Corpus: `C:\maxdrop_fixtures\oracle\scene_a.oracle.json` and `scene_b.oracle.json` exist and parse;
   `git status --short` lists none of them.
5. `powershell -ExecutionPolicy Bypass -File build.ps1` -> builds (no add-on code changed; confirms nothing broke).
6. Blender runs: not needed (no `maxdrop/` change); `tests/fixtures/*` gained JSON only, the import smoke reads
   `*.max` only.
