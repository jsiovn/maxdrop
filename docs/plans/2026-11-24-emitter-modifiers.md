# Mesh light emitter: apply the modifiers of its mesh (maxdrop-em3.162) Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** A VRayLight mesh light's emitter gets what MaxDrop evaluates or converts of its mesh object's modifiers
(an Extrude on a shape source, the converted Shell / TurboSmooth / MeshSmooth / Symmetry as Blender modifiers), and
in lm and W its radiance is spread over the evaluated mesh's area, as V-Ray 5.2 does.

**Architecture:** convert/ (bpy-free) describes the emitter mesh (an Extrude on a shape source made here) and puts
the converted modifiers of the mesh object on the light node (`node.converted`), so `build/modifiers.add` adds them
as it does for any mesh. The evaluated area is only known in Blender: after the modifiers are added, ops.py calls
`build/emitters.spread`, which measures a throwaway copy of the emitter object (in the scene's master collection,
unhidden, render levels within the viewport budget), scales the convert-side object-space area by evaluated /
unmodified (both measured on the same object, so the offset stays out as before), recomputes the radiance with the
convert rule (`lights.spread`) and sets the Emission strength. Emitters without converted modifiers are untouched.

**Tech Stack:** Python 3.11, Blender 4.2 / 4.5 / 5.2 headless.

---

## Files

- `maxdrop/convert/lights.py`: `EmitterDescription` gains `units` and `multiplier`; `_emitter_strength()` (the
  checks of describe_emitter's radiance, shared); `spread(ed, a)`; `EMITTER_MODIFIERS` reworded (the emitter is its
  mesh below them).
- `maxdrop/convert/scene.py`: `_emitter` (stacks, told, convert; returns the converted list, budgeted),
  `_emitter_mesh` (returns the reader Modifiers above what is evaluated, UVW Maps and non-rendering ones dropped; an
  Extrude on a shape source through `_emitter_shape`), the light branch of `describe()`.
- `maxdrop/build/emitters.py`: `spread(desc, built, collection, view_layer, strength)`; the lit Emission node named.
- `maxdrop/ops.py`: one call after `build_modifiers.add`.
- Tests: `tests/unit/test_lights.py` (Own: a Solidify, no line; Convert Modifiers off: the line; spread rule; an
  Extrude source on extrude.max), `tests/unit/test_convert_scene.py` (vray_mesh_light expected issues),
  `tests/blender/run.py` (FixtureEmitterOwn: Solidify 2 mm, radiance over 760 mm^2; off emitter same area).
- Docs: FORMAT.md "VRayLight", SUPPORT.md mesh light row, CHANGELOG [Unreleased].

## Tasks

- [ ] 1. lights.py: `_emitter_strength`, `spread`, new slots; unit tests for spread (W, lm, default unchanged, zero
  area, double-sided).
- [ ] 2. scene.py: `_emitter_mesh` + `_emitter_shape` + `_emitter_rest`; `_emitter` converts per node with the
  node's offset; `describe()` light branch passes stacks / told / convert_modifiers, budgets, sets `converted`,
  rolls `told` back on a MeshError.
- [ ] 3. Update expectations: test_own_mesh_with_a_shell (converted Solidify 2 mm, no issue), convert off keeps the
  line, test_convert_scene vray_mesh_light issue table, Extrude source test on extrude.max (FixtureExtRect: 30 x 20
  x 10 closed box, area 2 x 600 + 100 x 10 = 2200 mm^2).
- [ ] 4. build/emitters.spread + ops.py call; run.py: EMITTER_RADIANCE Own = 100 / 683 / (pi 0.00076), a check that
  FixtureEmitterOwn has one SOLIDIFY of 0.002 m; a bench check in run.py of spread on an off (hidden) emitter.
- [ ] 5. Docs + CHANGELOG.
- [ ] 6. Plain tests, lint, Blender 5.2 FIXTURES; review; then full matrix (4.2.23, 4.5.16, 5.2).

## Verification

Working directory: the worktree root. Blender headless, isolated profile (`BLENDER_USER_RESOURCES=<scratch>`).

- `python -I -m unittest discover tests` -> `OK`
- `python -I tools/lint.py` -> exit 0
- `powershell -ExecutionPolicy Bypass -File build.ps1` -> dist zip
- `BLENDER_USER_RESOURCES=<scratch> blender --background --factory-startup --python-exit-code 1 --python
  tests/blender/run.py` on 5.2 (before review), then 4.2.23 and 4.5.16 too -> `FIXTURES PASSED`, including
  `vray_mesh_light` FixtureEmitterOwn: a Solidify of 0.002 m and the Emission strength
  100 / 683 / (pi 0.00076) x Light Strength.
- `tests/smoke_register.py`, `tests/smoke_import.py` on the three versions -> pass.

Not measurable here (no 3ds Max in this lane): a V-Ray render of a mesh light under a TurboSmooth or Symmetry; the
TurboSmooth area is Blender's Subdivision Surface at the render levels (capped by the viewport budget).
