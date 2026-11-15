# reader/geometry.py: Editable Mesh and Editable Poly as numpy arrays Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decode the base geometry of Editable Mesh and Editable Poly objects completely (positions, polygons,
smoothing groups, material IDs, every map channel) into numpy arrays, one `MeshData` per object.

**Architecture:** A new `maxdrop/reader/geometry.py` on top of `reader/scene.py` and `reader/chunks.py`.
`read_mesh(scene, i)` dispatches on `(superclass, ClassId)` to `read_editable_mesh(chunk)` (fixed-size records:
numpy structured views, no Python loop) or `read_editable_poly(chunk)` (variable-length vertex and face records:
one Python loop per record that only appends byte slices; numpy does the rest). Every index array is bounds
checked; anything broken raises `GeometryError` (a `ChunkError`) for that object only. numpy is imported inside
the functions (the plain CI job has no numpy; the geometry tests skip there, debt bead filed).

**Tech Stack:** Python 3.11 syntax (local plain tests run on 3.9), numpy, struct, unittest.

---

## Facts found while planning (fixtures + corpus, 2026-11-15)

Editable Poly, `0x08FE` container (box_poly_standard, multi_uv; parse checked on every Poly of scenes A and B):

- `0x0100` vertices: `u32` count, then per vertex `u32` flags and, unless flags bit `0x2` (dead) is set, 3 x `f32`
  (16 or 4 bytes). The corpus has dead vertices (scene A: one object 654 records, 597 x 16 bytes worth of payload).
- `0x010A` edges: `u32` count, per edge `u32` flags + (unless dead, `0x2`) 2 x `u32` vertices. Not needed for
  MeshData: not read.
- `0x011A` faces: `u32` count, per face `u32` degree, degree x `u32` vertex, `u16` field mask, then in mask order:
  `0x01` -> `u32` face flags (dead faces: degree 0, flags with bit `0x2`), `0x08` -> `u16` material ID
  (zero-based), `0x10` -> `u32` smoothing groups, `0x20` -> `2 * (degree - 3)` x `u32` triangulation diagonals.
  No other mask bit occurs in the corpus (2.7 M + 1.3 M faces parse to the byte). The box: mask `0x38` / `0x30`,
  material 1 (bottom, Max ID 2), smoothing 2 / 4.
- `0x0120` = number of map channels (getNumMaps); then per present channel `0x0124` (`i32` channel), `0x0128`
  map vertices (`u32` count + 3 x `f32`), `0x012B` map faces (per face `u32` degree + degree x `u32`, no count;
  one per face).

Editable Mesh, `0x08FE` (editable_mesh; corpus):

- `0x0914` vertices: `u32` count + 3 x `f32`. `0x0912` faces: `u32` count + 20 bytes: 3 x `u32` vertex,
  `u32` smoothing groups, `u32` flags (low 16: edge visibility 1/2/4 and others, high 16: zero-based material ID).
  editable_mesh: smoothing 1 (faces 0-3) and 2, material 0,0,0,0,1,1,2,2,1,1,2,2.
- Map channels: `0x0959` (`i32` channel, -2..n seen), `0x2398` (`u32`, 1 everywhere), `0x2394` map vertices
  (`u32` count + 3 x `f32`), `0x2396` map faces (`u32` count = face count, 3 x `u32` each). `0x0956`, `0x23A0`,
  `0x0924/0x0928/0x092A`, `0x092C/D/E` are not map data.

## Files

- Create: `maxdrop/reader/geometry.py`
- Create: `tests/unit/test_geometry.py`
- Modify: `docs/FORMAT.md` (Geometry section; Open list)

## Task 1: geometry.py

- [ ] `GeometryError(ChunkError)`; `MapChannel(channel, uvw, indices)` namedtuple; `MeshData` (positions float32
  (N,3), loop_vertices int32 (L,), loop_starts int32 (F,), loop_totals property, smoothing_groups uint32 (F,),
  material_ids uint16 (F,) zero-based, maps {channel: MapChannel}).
- [ ] `read_editable_mesh(chunk)`: structured numpy views; checks: sizes exact, indices < counts, map face count
  = face count.
- [ ] `read_editable_poly(chunk)`: fast path for vertices when the payload is 4 + 16 n (no dead), else a loop;
  faces loop appending slices to bytearrays; dead faces skipped (geometry and every map channel alike); dead
  vertices compacted with a remap (a live face on a dead vertex = error); unknown mask bits = error; map face
  degree must equal the face's degree.
- [ ] `read_mesh(scene, i)`: None for other classes; ChunkError/struct errors inside -> GeometryError naming i.

## Task 2: tests (TDD alongside)

- [ ] Fixtures: every node whose base object is Editable Mesh/Poly -> vertex/face counts = oracle
  base_verts/base_faces; box_poly_standard 8 vertices, 6 quads, 24 map vertices in channel 1, bbox of the
  positions [-10,-15,0]..[10,15,40]; editable_mesh smoothing {1,2} by face, Max IDs 1-3 by face; multi_uv
  channels 1, 2, 3, each with indices per loop.
- [ ] Synthetic: every face field alone and together, dead vertices + dead faces (with map channels), unknown
  mask bit, index out of range (vertices, map vertices), truncated record, wrong map face degree / count,
  missing `0x08FE`, Editable Mesh size mismatch -> GeometryError; `read_mesh` on a non-geometry object -> None.
- [ ] Skip the module when numpy is missing (like test_chunks).

## Task 3: FORMAT.md

- [ ] Geometry section with the facts the fixtures show; corpus-only facts (dead records, face flags field,
  negative channels, unknown mask bits) under Open.

## Verification

Working directory: the repo root. No Blender part beyond regression: the add-on does not import
`reader/geometry.py` yet (convert/build is maxdrop-too.9).

1. `python -I -m unittest discover tests` -> `OK (skipped=N)` with no new skip (numpy is present locally),
   test_geometry green.
2. Corpus, local only (scratch script in the session scratchpad, output not committed): decode every Editable
   Mesh / Poly base object of scene A and scene B (paths in the bead notes); 0 errors; per node, vertex and face
   counts = `C:\maxdrop_fixtures\oracle\scene_{a,b}.oracle.json` base_verts / base_faces (nodes matched by
   pre-order walk index); totals printed; scene B decode time and peak memory (tracemalloc peak + process peak
   working set) recorded in the bead notes. Target: under 20 s, under 3 GB.
3. build-and-test blocks 2, 3, 4 on Blender 5.2, 4.2, 4.5 (register + import smoke on the fixtures) to show
   nothing regressed.
