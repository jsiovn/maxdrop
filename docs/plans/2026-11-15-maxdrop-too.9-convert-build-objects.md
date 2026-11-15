# maxdrop-too.9 Scene description and Blender objects Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn what the reader finds (nodes, transforms, Editable Mesh / Poly geometry, system unit) into a
scene description in meters (`maxdrop/convert/scene.py`, no bpy) and build Blender objects from it
(`maxdrop/build/objects.py`): one object per node, shared meshes for instances, parents by index, sharp edges
from smoothing groups, UV layers per map channel, empties as placeholders for every other class.

**Architecture:** `convert.scene.describe(scene, meters)` walks `reader.scene.Scene` pre-order, takes each
node's local matrix from `reader.controllers.Transforms`, reads the base object through `Scene.object_stack` and
`reader.geometry.read_mesh`, and returns a `SceneDescription`: `NodeDescription`s (walk order, parents first) and
`MeshDescription`s keyed by `(base object index, object offset)`. `convert.scene.read(path, meters=None)` opens
the file and takes the system unit (`reader.units`) when `meters` is not given. `build.objects.build(desc,
collection)` creates the meshes with `foreach_set`, then the objects in walk order. `tests/blender/run.py` runs
both on every fixture inside Blender and compares with the oracle.

**Tech Stack:** Python 3.11 syntax (local plain Python is 3.9: nothing newer than 3.9 is used), numpy (imported
on demand, as in the reader), bpy only in `maxdrop/build/`.

---

## Decisions

- **Matrix convention of the description:** Blender's column-vector convention, rows of a 4x4 tuple
  (`Matrix(node.matrix)` works as is). The reader's row-vector matrices are transposed in convert. `matrix` is
  the local matrix (relative to the parent node's pivot), `world` the world matrix; both in meters.
- **Pivot vs. object offset:** a Blender object's matrix is the node transform (the pivot, oracle `transform`),
  so children placed relative to it land where Max puts them. The object offset is baked into the mesh
  vertices. Instances that share a base object but differ in offset get one mesh per distinct offset; the key is
  `(base, offset)` with `offset = None` for identity, so in practice (and in every fixture) instances share one
  mesh. An offset with a negative determinant reverses each polygon's loop order (and its UV loops) so normals
  stay outward.
- **Units:** `meters` (per file unit) scales vertex positions and the translation row of every matrix (local,
  world, offset), never rotation or scale. World translations are linear in the local ones, so scaling locals
  scales worlds.
- **Mirrored:** `NodeDescription.mirrored = det(world 3x3) < 0`. Blender renders a negative-determinant object
  with outward normals itself; nothing is flipped for the node transform.
- **Smoothing groups:** face smooth = `groups != 0` (`sharp_face` attribute = `groups == 0`). An edge is sharp
  when two faces on it share no group (`a & b == 0`); a boundary edge is not sharp. convert computes the sharp
  edges as sorted vertex pairs `int32 (E, 2)`; build maps them onto Blender's edges (computed from polygons)
  with numpy and writes the `sharp_edge` attribute: same code on 4.2, 4.5 and 5.2 (no `use_auto_smooth`).
- **UVs:** every map channel `>= 1`, ascending: `UVMap` for channel 1, `UVChannel_<n>` for the others; per loop
  `uvw[indices][:, :2]`. Each layer's data is written through its own layer object.
- **Material IDs** go to `material_index` (no slots here: M2); they are any u16 and survive without slots
  (checked in run.py on all three versions). `mesh.validate()` is not called, since it may clamp indices without
  slots and would change face counts behind convert's back. Instead convert leaves out what Blender cannot hold
  (`valid_faces`: a face using a vertex twice, a face with the vertex set of an earlier face), keeps materials,
  groups and UV loops aligned, and reports the count as an issue.
- **Bounded work on untrusted geometry:** an edge with more than two faces pairs only the distinct
  smoothing-group masks, at most `MAX_EDGE_MASKS` (64; past it the edge is sharp), so a fan of faces on one edge
  stays linear. A sheared local matrix (scale along a rotated axis) is reported, since `matrix_basis` drops shear.
  A base object's reader arrays are released after its last node.
- **Placeholders:** a node whose base object is not Editable Mesh / Poly, has no object, or whose geometry the
  reader refuses becomes an EMPTY with the node's name and transform and the custom property `maxdrop_class` (the
  class name from the file's class directory, `""` when none). `SceneDescription.placeholders` counts them per
  class name; reader issues (transforms, geometry errors) go to `SceneDescription.issues` as strings for the
  report (M1-10).
- **Modifiers:** the base mesh is built, the stack is not evaluated; `NodeDescription.modifiers` lists their class
  names for the report.
- **Review fixes (after the first implementation):** the bounded-work, face-filter and shear items above, a test
  for each, and tests of the damaged-input paths of `describe`.
- **Instances:** the bead text says "3 objects share one mesh"; the oracle says four nodes (FixtureSource and three
  instances) share the base object. The oracle is the truth: 4 share, FixtureCopy has its own.
- **Not in scope:** materials (old engine stays as is), collections/layers/flags (M1-10), the operator switch
  (M1-11), the CI gate on `tests/blender/run.py` (maxdrop-em3.8).

## File structure

| File | Role |
|---|---|
| `maxdrop/convert/__init__.py` | package doc, imports nothing |
| `maxdrop/convert/scene.py` | `NodeDescription`, `MeshDescription`, `SceneDescription`, `describe()`, `read()`, `sharp_edges()` |
| `maxdrop/build/__init__.py` | package doc, imports nothing |
| `maxdrop/build/objects.py` | `build(desc, collection) -> Built(objects, meshes)`; `make_mesh(md)` |
| `tests/unit/test_convert_scene.py` | plain Python: synthetic + every fixture vs. oracle |
| `tests/blender/run.py` | inside Blender: every fixture through describe + build vs. oracle; `FIXTURES PASSED` |

## Task 1: convert/scene.py (TDD)

- [ ] Tests first (`tests/unit/test_convert_scene.py`, loaded by path under a throwaway package name whose
  `__path__` is `maxdrop/`, so `maxdrop/__init__.py` (bpy) never runs; skipped without numpy):
  - `sharp_edges`: two quads sharing an edge, groups 1/1 -> none sharp; 1/2 -> the shared edge; 0/0 -> shared
    edge sharp; boundary edges never.
  - every fixture: node names and order = oracle order; world matrix (translation / meters) = oracle `transform`
    within 1e-4; parents by position = oracle parents (handle -> position); mesh world bbox (positions through
    `world`) / meters = oracle bbox within 1e-3; vertex/face counts = `base_verts`/`base_faces`; nodes sharing a
    mesh key = oracle `instances`; meters = 0.001 / 0.01 / 0.0254 for units_mm / cm / in.
  - hierarchy: FixtureLeaf `mirrored`, the others not; FixtureRoot's mesh positions include the `[5, 5, 0]`
    offset (bbox matches only then).
  - box_poly_standard: one layer `UVMap`; multi_uv: `UVMap`, `UVChannel_2`, `UVChannel_3`; hierarchy: none.
  - sharp edges: 12 for every poly box, 8 for editable_mesh (groups 1 on top/bottom, 2 on the sides).
  - layers_flags: the Dummy group head is a placeholder `Dummy`, counted once.
  - negative-determinant offset (synthetic: patch a node's offset): loops reversed, UV loops follow.
- [ ] Implement; run `python -I -m unittest discover tests -p test_convert_scene.py -v`; commit
  `Add the scene description of the convert package`.

## Task 2: build/objects.py and tests/blender/run.py

- [ ] `make_mesh(md)`: `vertices.add`, `loops.add`, `polygons.add`, `foreach_set("co" / "vertex_index" /
  "loop_start" / "material_index")`, `mesh.update(calc_edges=True)`; `sharp_face` and `sharp_edge` attributes;
  UV layers by name with `layer.data.foreach_set("uv", ...)`.
- [ ] `build(desc, collection)`: meshes first (named after their first node), then objects in walk order;
  `ob.parent`, `matrix_parent_inverse` identity, `matrix_basis = Matrix(node.matrix)`; empties with
  `maxdrop_class`.
- [ ] `tests/blender/run.py`: imports `maxdrop` from the repo root; per fixture: empty the scene, `read`,
  `build`, then check world matrices (1e-4, in file units), world bboxes of mesh objects (1e-3), vertex / face
  counts, UV layer count and names, sharp edge count, material indices = reader's, shared-mesh groups =
  oracle instances, outward normals (`M^-T n` dot (face center - oracle bbox center) > 0 on every face),
  placeholders' `maxdrop_class`. Prints `FIXTURES PASSED` / `FIXTURES FAILED`, exit 1 on failure.
- [ ] Commit `Build Blender objects from the scene description`.

## Verification

Working directory: the repo root. `$S` = session scratchpad. Blender paths from the bead notes.

1. Plain tests: `python -I -m unittest discover tests` -> `OK` (convert tests run, numpy present locally).
2. Build: `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...`.
3. Fixture tests on 5.2, 4.2.23, 4.5.16:
   ```powershell
   $S = "<scratch>"; $B = "<blender.exe>"; $tag = "52"
   $env:BLENDER_USER_RESOURCES = "$S\profile-$tag"
   & $B --background --factory-startup --python-exit-code 1 --python tests\blender\run.py *>&1 | Out-File -Encoding utf8 "$S\fixtures-$tag.log"
   "exit $LASTEXITCODE"; Select-String -Pattern "^FIXTURES ", "^FAIL " "$S\fixtures-$tag.log"
   ```
   Pass: `exit 0`, `FIXTURES PASSED`, no `FAIL`.
4. Register and import smoke (blocks 3 and 4 of build-and-test, no arguments = every fixture) on the three
   versions: `SMOKE PASSED`, `IMPORT PASSED` (the operator still runs the old engine: unchanged).
5. Red check: run.py against a scratch copy where `build/objects.py` skips the sharp edges -> `FIXTURES FAILED`.
6. Extra (not a gate): `convert.scene.read` on corpus scenes A and B in plain Python: no traceback; counts of
   meshes, placeholders and issues recorded in the session only.
