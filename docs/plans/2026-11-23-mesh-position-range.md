# Mesh positions past single precision Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stored or built mesh whose positions (offset and meters applied) are NaN, inf or past the largest
float32 is not handed to Blender: its nodes become EMPTY placeholders with an issue, as a curve (em3.107) and a
primitive (`primitives.data()`) already are. Bead: maxdrop-em3.149.

**Architecture:** `convert/scene.py` only (part E owns everything there but `rim_corners`, `_emitter`,
`_emitter_mesh`). `mesh_description` checks its float64 positions after the offset and meters, before the
float32 cast, and raises a new `MeshError(ValueError)`; its three callers handle it:

- `_mapped_mesh` (MESH branch and Extrude): checks the positions (`_positions`) before any UVW Map is read, so a
  NaN mesh gets no "uvw map" issue; caches a flag per key before its maps in a `ranges` dict (trailing keywords
  `ranges=None` and `refusal=` on `_mapped_mesh`, `ranges=None` on `_extruded`, so part F's calls stay valid; a
  flag, not the MeshError, whose traceback would keep the refused mesh alive); names the refusal once per key and
  returns `(None, ())`. The issue is `geometry: not built: ...`, on the Extrude path `extrude: not made: ...`: its
  caller already falls back to the shape's curve (whose own range guard may refuse it too).
- MESH branch of `describe`: key None -> kind stays EMPTY (a placeholder), the converted modifiers and their
  issues dropped and their `told` entries rolled back, as the Extrude branch does.
- Mesh lights: `_mesh_of` (part E's) refuses a mesh whose raw positions times `desc.meters` do not fit, a reason
  string (`lights.EMITTER_UNREAD`), so `_emitter_mesh` tries the mesh source next. The light node's offset is
  applied later, in `_emitter` (part F's, not edited): `describe` catches `MeshError` around the `_emitter(...)`
  call (nothing of `desc.meshes` / `desc.emitters` is written before it raises), `light: not built: ...` on each
  node, as `_emitter` names its other reasons, and remembers the refusal per (light base, node offset) in
  `emitter_refused` so a second node of the light is not described again.

**UVs: kept, not refused.** Primitives refuse a mesh whose UVs leave the float range because their UVs come from
the same sizes as the positions. Stored UVs are independent of the positions, and `uvwmap.apply` refuses a map's
non-finite UVs by keeping the geometry (the stored channel stays). So: the U and V of the imported channels
(>= 1, the loops kept) that are not finite are set to 0 in the copy `mesh_description` makes (`mc.uvw` is never
written), counted in `MeshDescription.zeroed_uvs`, one issue per mesh key (`geometry: N UV coordinates that are
not numbers set to 0`). Stored UVs are float32 already: finite ones fit.

**Tech Stack:** Python 3.11, numpy (`numpy.errstate` around the matmul and the cast: inf times 0 warns).

---

### Task 1: Guard and UV zeroing in `mesh_description`

**Files:** Modify `maxdrop/convert/scene.py` (`MeshError`, `MeshDescription.zeroed_uvs`, `mesh_description`,
`_positions` helper, module docstring paragraph). Test: `tests/unit/test_convert_scene.py` (new class
`MeshRange`, appended at the end of the file, nothing reordered).

- [ ] Write failing tests: NaN position -> `MeshError`; 1e36 at meters 1000 -> `MeshError`; an offset scale 1e39
  -> `MeshError`; 1e30 at meters 1 passes; a NaN UV -> 0 and `zeroed_uvs == 1`, the input array unchanged.
- [ ] `_positions(data, offset, meters)`: float64 positions under `errstate(over/invalid ignore)`; raises
  `MeshError("its points do not fit single precision (Blender's meshes hold no larger value)")` unless
  `(abs(q) < lights.MAX_FLOAT).all()` (False for NaN; True for an empty mesh). No `check()` call added
  (DescribeCancel counts them).
- [ ] UV zeroing after the indexing copy.

### Task 2: Callers

- [ ] `_mapped_mesh(..., refused=None)` and `_extruded(..., refused=None)`: `_positions` checked before the maps,
  key added to `refused`, issue once per key. `_zeroed(desc, md, node)` names the zeroed UVs.
- [ ] `describe` MESH branch: key None -> EMPTY, `told` rollback, `converted = ()`.
- [ ] `describe` LIGHT branch: `except MeshError` around `_emitter`; zeroed UVs named on the mesh's first user.
- [ ] `_mesh_of`: raw positions * `desc.meters` checked (`_positions(data, None, desc.meters)`), reason string.
- [ ] Tests through `describe`: `instances` fixture with `geometry.read_mesh` patched to return a NaN mesh and a
  1e36 mesh at meters 1000: every node EMPTY, placeholders counted, one issue per base object, no meshes; a 1e30
  mesh stays MESH. A mesh light (`vray_mesh_light` fixture) whose mesh is patched to 1e36 at meters 1000 and an
  offset-overflow case: `describe` does not raise, the node is not MESH, a `light: not built:` issue.

### Task 3: Docs

- [ ] CHANGELOG `[Unreleased]` / Fixed: one line (append, do not re-wrap neighbours).

## Verification

**Working directory:** `D:/www/maxdrop-epic-maxdrop-6n0.6` (the worktree).

1. `python -I -m unittest tests.unit.test_convert_scene -v` -> the new cases OK.
2. `python -I -m unittest discover tests` -> OK (fuzz, malformed and reader-net tests included).
3. `python -I tools/lint.py` -> exit 0.
4. `powershell -ExecutionPolicy Bypass -File build.ps1` -> `dist\maxdrop-<version>.zip`.
5. Blender smoke and fixtures, each headless with an isolated profile of this session
   (`BLENDER_USER_RESOURCES=<scratch>`), on 4.2.23, 4.5.16 and 5.2: `tests/smoke_register.py`,
   `tests/smoke_import.py`, `tests/blender/run.py` -> `FIXTURES PASSED`, no fixture count changes (the guard
   refuses nothing in the committed fixtures).

**Success criteria:** all of the above pass; the new cases give a placeholder with an issue.

## Results (2026-11-23)

- Commits: c870444 (guard, callers, tests, CHANGELOG), 2791ed1 (flag cache after review: a cached MeshError kept
  the refused mesh in a reference cycle; `zeroed_uvs` a constructor argument; rollback and Extrude fallback cases),
  8b77f5e (`extrude: not made:` on the Extrude path), then the emitter refusal cache and the offset-only case.
- Tests in `MeshRange`: NaN, inf, 1e36 at meters 1000, an offset scale of 1e39 refused and 1e30 kept
  (`mesh_description`); UV zeroing (the reader's array untouched); `instances` refused per key (placeholders, one
  issue per key, no mesh); zeroed UVs named once per mesh, emitters included; a mesh light's mesh refused in
  `_mesh_of`; a refusal after the light's offset caught, described once per light and offset; a refused mesh's
  converted modifiers taken back from `told`; a refused extrusion drawn as its curve; one node's offset past the
  range refusing that node only.
- Red: the new cases fail on the base (5 FAIL, 5 ERROR for the first six); the rollback and emitter-cache cases
  fail with that code removed.
- Every committed fixture describes the same as on the base: node kinds, placeholders, meshes, their counts and
  the issues in order.
- Plain suite OK, lint clean, build OK; register, import and fixture smoke pass on Blender 4.2.23, 4.5.16 and 5.2
  (COUNTS lines equal across versions).
- Part F assumptions for the merge: `describe`'s catch relies on `_emitter` writing nothing before it calls
  `mesh_description` (true on origin/epic/maxdrop-6n0.7 as last fetched), and `_mesh_of` reads `desc.meters`.
