# reader/controllers.py: transforms, pivots, full hierarchy Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute every node's world matrix (and its object-offset matrix) at frame 0 from the transform
controllers in the Scene stream, as 3ds Max does, with unknown controllers reported instead of guessed.

**Architecture:** A new `maxdrop/reader/controllers.py` on top of `reader/scene.py`: small pure-Python 4x4 matrix
helpers in Max's row-vector convention (`p' = p * M`, row 4 = translation, the layout of the oracle's
`transform`), a dispatch table keyed by `(superclass, ClassId)` that evaluates each controller at time 0, and a
`Transforms` class that composes `local * parent world` up the whole parent chain (memoized, iterative) and
collects an `issues` list (node, controller, superclass, ClassId, reason). No bpy, no mathutils, and no numpy
either: Python floats are float64 and the plain CI job has no numpy, so the oracle test runs everywhere.

**Tech Stack:** Python 3.11 syntax (local plain tests run on 3.9), `math`, `struct`, unittest.

---

## Facts found while planning (fixtures + corpus, 2026-11-15)

- Every fixture node: PRS (0x2005) -> slot 0 Position XYZ (3 Bezier Float), slot 1 Euler XYZ (3 Bezier Float,
  radians), slot 2 Bezier Scale (0x2505 = 3 scale + 4 quat axis).
- Bezier Float value: `0x2501` (f32), directly in the object or inside a `0x7127` container. Keys: `0x2525`,
  28 bytes each (i32 time, u32 flags, f32 value, 4 x f32 tangents/lengths). Bezier Scale keys: `0x2528`, 148
  bytes each, value (3 + 4 floats) at byte 8.
- Corpus: only single keys (time 0, 200, 16000); 1 Bezier Float and 3 Bezier Scale have a key value that differs
  from the plain value chunk: the oracle decides which is right at frame 0 (expectation: the key; outcome: the saved value matches the oracle in all of them, so it wins).
- hierarchy fixture: local = S * R * T, world = local * parent world (checked by hand: leaf with scale -1,-1,-1
  matches the oracle including the mirrored rotation rows).
- Rotations: a +30 degree Z Euler value gives row 1 = [cos, sin, 0] (standard row-vector rotation). A Max
  quaternion (x, y, z, w) as stored gives the row-vector matrix with the standard column-vector formula (it is the
  conjugate, ORACLE.md).
- List controllers (corpus, scene B): `0x1010` = entry count, `0x1020` = active entry, entries at ref slots
  0..n-1, a ParamBlock2 at a later slot whose refs 0..n-1 are the weight controllers (Bezier Float).
- Look At (0x2006, superclass 0x9008) on 2 camera nodes per corpus scene: unsupported until M4.
- ClassIDs of controllers that no committed fixture has stay in controllers.py (SDK values), not in
  `classids.CLASSES` (whose test requires a fixture for each entry).

## Files

- Create: `maxdrop/reader/controllers.py`
- Create: `tests/unit/test_controllers.py`
- Modify: `docs/FORMAT.md` (Controllers and transforms section; Open list)

### Task 1: matrix helpers + controller evaluation + Transforms

- [ ] Write `tests/unit/test_controllers.py`: synthetic streams (helpers as in test_scene.py) for PRS with
  Position XYZ / Euler XYZ / Bezier Scale, Bezier Float in and out of 0x7127, keys before/at time 0, a list
  controller with weights, an unknown class -> identity + issue, a controller ref cycle -> issue, depth guard;
  matrix helper checks (Euler order, quaternion convention, scale axis); every fixture: world matrix and
  object_transform within 1e-4 of the oracle per element, in oracle order.
- [ ] Run: `python -I -m unittest tests.unit.test_controllers` -> fails (module missing).
- [ ] Implement `maxdrop/reader/controllers.py`.
- [ ] Run the test again -> OK; full `python -I -m unittest discover tests` -> OK.
- [ ] Commit `Add the transform controllers of the reader`.

### Task 2: corpus comparison (local only, scratch script outside the repo)

- [ ] Scratch script compares `Transforms.world()` and `object_world()` with the corpus oracles
  (`C:\maxdrop_fixtures\oracle\scene_{a,b}.oracle.json`), matching nodes by pre-order walk + name. Report share
  within 1e-4 and the controller classes of the rest. Fix conventions until >= 99 % of the supported nodes match.
- [ ] Result in bead notes (counts and class names only).

### Task 3: docs/FORMAT.md

- [ ] Section "Controllers and transforms": chunk ids, conventions, which fixture shows what; Open list updated.
- [ ] Commit `Document the transform controllers in FORMAT.md`.

## Verification

- `python -I -m unittest discover tests` -> OK, including `test_controllers` (every fixture world matrix and
  object transform within 1e-4 of the oracle, absolute, per element).
- `python -I tests/unit/test_reader_no_bpy.py` style check (part of discover): controllers.py imports no bpy /
  mathutils.
- Corpus (local only): scratch script prints share within 1e-4 for scene A and scene B; target >= 99 % of the
  nodes whose controllers are supported.
- Blender: the add-on does not import controllers.py yet (convert/build is maxdrop-too.9), so the Blender part of
  build-and-test is the regular register + import smoke on 4.2, 4.5 and 5.2 to show nothing regressed.
