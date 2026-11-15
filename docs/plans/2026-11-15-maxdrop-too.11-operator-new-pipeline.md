# Operator on the new pipeline Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `import_scene.maxdrop` imports nodes and geometry through reader -> convert -> build, with a Units
choice and a pre-flight line in the popup, while materials still come from the old engine (until M2).

**Architecture:** `ops.execute` resolves packs as before, then per `.max`: open it with `reader.cfb`, read the
system unit, pick meters per unit (Units option x Scale), `convert.scene.describe`, `build.collections.make` +
`build.objects.build` + `build.collections.finish`, the axis conversion on the top-level objects, then (Object
Filter > Material) a small adapter in `import_max.py` parses the file the old way and runs `adjust_material` per
mesh with the node's material chunk (object index = position in the Scene stream in both readers). Everything of
`import_max.py` the new path no longer calls is deleted.

**Tech Stack:** Blender 4.2 / 4.5 / 5.2 Python API, the dev package's `reader/`, `convert/`, `build/`.

---

## Decisions

- **Units** (`units`, EnumProperty, saved in presets, explicit numbers): `AUTO` 0, `MILLIMETERS` 1, `CENTIMETERS`
  2, `METERS` 3, `INCHES` 4, `FEET` 5. Auto = the file's system unit; a file that does not state one gives 1 m
  per unit and a WARNING line ("... does not state its unit: 1 unit = Scale meters"). **Scale** (`scale_objects`,
  identifier kept) multiplies meters per unit; its minimum becomes 0.0001 (meters must be > 0). The resolution is
  `_meters(choice, unit, scale) -> (meters, note)` in `ops.py`.
- **Removed options** (CHANGELOG line each): `use_apply_matrix` (node transforms are always applied),
  `use_collection` (every import makes a collection named after the file in the active collection, one per
  layer below), Object Filter items `PRIMITIVE`, `EMPTY`, `ARMATURE` (primitives, Biped and Boolean objects are
  placeholder empties of the new pipeline; Dummy helpers and group heads are always empties). Object Filter keeps
  `MATERIAL` (0x1: run the old material code) and `UV` (0x2: off = no UV layers), identifier unchanged.
  Forward / Up stay: the axis conversion applies to the top-level objects.
- **Materials**: `import_max.open_materials(path)` parses the class directory, the DLL directory, the Scene
  stream and the metadata stream into the engine's globals; `import_max.assign_material(path, search, obj,
  index)` runs `adjust_material` with node `index`'s material chunk; `import_max.close_materials()` drops the
  globals. A shared mesh gets the material of its first node only (adjust_material appends to the mesh's slots).
  The old parse runs after the build and after the scene description is dropped, so the peak is not the sum of
  both readers. A failing old parse or material is printed (`MaxDrop: ...`), counted, and leaves geometry intact.
- **Pre-flight**: `invoke()` reads `reader.metadata.read` + `Scene.from_file` node count + `units.system_unit`
  for each `.max` given (0.12 s on scene B, measured), and for a pack only when its folder is already on disk
  (`_existing`). Cached by `_key(path)`; the popup draws one line per file: `3ds Max 2020 · Scanline Renderer ·
  1 node · millimeters`.
- **Report**: an INFO line per file (`Imported <file>: n objects, m meshes, k materials`), plus the unit WARNING;
  the full report (convert.report / build.report) is maxdrop-too.14.
- **Verify "same box size in meters"**: the three units fixtures hold the *same box in system units* (10 x 20 x 30)
  saved with mm / cm / in (tools/fixtures/units_*.ms). So: with Units = Auto each box measures 10 x 20 x 30 times
  its unit (0.001 / 0.01 / 0.0254 m); with Units = Millimeters all three give the same size in meters.
- `tests/blender/run.py` imports each fixture through the operator (Verify: "now through the operator"); the
  description-mutation test (check_layer_flags) still builds directly.
- CHANGELOG: an `## [Unreleased]` section (the version bump is maxdrop-too.13). docs/SUPPORT.md, README and the
  page describe "the version in development" where they describe what is imported.

## Chunk 1: Engine adapter and deletion

### Task 1: material adapter in import_max.py

**Files:** Modify `maxdrop/import_max.py`

- [ ] Add after `get_matrix_mesh_material`:

```python
def open_materials(filename):
    """Parse filename the old way for adjust_material: class and DLL directories, Scene and metadata streams."""
    global SCENE_LIST, META_DATA
    close_materials()
    if not is_maxfile(filename):
        raise ValueError("not a 3ds Max file")
    maxfile = ImportMaxFile(filename)
    try:
        read_directory(maxfile, filename)
        read_class_directory(maxfile, filename)
        metasid = min(max(entry.sid for entry in maxfile.direntries if entry is not None), 11)
        SCENE_LIST = read_chunks(maxfile, 'Scene', SceneChunk)
        META_DATA = read_chunks(maxfile, maxfile.direntries[metasid].name, superId=metasid) if metasid >= 0xA else []
    finally:
        maxfile.close()


def assign_material(filename, search, obj, index):
    """adjust_material with the material of the node at object index `index`."""
    node = get_node(index)
    if node is not None:
        adjust_material(filename, search, obj, get_matrix_mesh_material(node)[2])


def close_materials():
    global SCENE_LIST, META_DATA, CLS_DIR3_LIST, DLL_DIR_LIST
    SCENE_LIST, META_DATA, CLS_DIR3_LIST, DLL_DIR_LIST = [], [], [], []
```

- [ ] Delete every top-level definition the roots `ImportMaxFile, read_directory, read_class_directory,
  read_chunks, get_node, get_matrix_mesh_material, adjust_material, SceneChunk, is_maxfile, open_materials,
  assign_material, close_materials` do not reach (AST name reachability; list in the session), and the imports
  left unused. Keep the header, add `# Modified for MaxDrop, 2026-11-15 (jsiovn). ...`.

## Chunk 2: Operator

### Task 2: options, units, pipeline in ops.py

**Files:** Modify `maxdrop/ops.py`

- [ ] Properties: add `units` (above), Scale min 0.0001, Object Filter items MATERIAL/UV, remove
  `use_apply_matrix`, `use_collection`. Draw: Units + Scale + Forward + Up in Transform; Image Search + Object
  Filter in Include.
- [ ] `_meters(choice, unit, scale)`; `_import_max(self, context, max_path)` = read, describe, build, axis,
  materials; `execute` calls it per resolved path, reports per file.
- [ ] `_preflight(path)` + `_PREFLIGHT` cache; `invoke()` fills it, `draw()` shows a "File" panel.
- [ ] Header: add a dated "Modified for MaxDrop" line.

## Chunk 3: Tests, tools, docs

### Task 3: tests and tools

- [ ] `tests/smoke_register.py`: "the engine loads" checks `open_materials`/`assign_material`, not `load`;
  add a check that `use_apply_matrix` / `use_collection` are gone and `units` has the six items with numbers.
- [ ] `tests/smoke_import.py`: per fixture, the operator report and objects as before; plus: units fixtures (Auto:
  size = 10/20/30 x unit; Millimeters: identical), Scale 2 doubles, `_meters` with an unknown unit returns the
  Scale with a note, pre-flight text of a fixture names "3ds Max 2020" and the node count.
- [ ] `tests/blender/run.py`: register the package, import through the operator, look objects up by node name.
- [ ] `tools/baseline_import.py`: count nodes with `reader.scene` (no engine internals).

### Task 4: docs

- [ ] `docs/SUPPORT.md`, `README.md`, `site/index.html`, `tests/test_site.py`, `CHANGELOG.md` (`[Unreleased]`).

## Verification

Working directory: repo root. `$S` = session scratchpad. Blender paths from the bead notes:
`$B52 = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"`,
`$B42 = "D:\tools\blender\blender-4.2.23-windows-x64\blender.exe"`,
`$B45 = "D:\tools\blender\blender-4.5.16-windows-x64\blender.exe"`.

1. `python -I -m unittest discover tests` -> `OK`.
2. `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...` (validate passes).
3. For each `$B` in 52/42/45, isolated profile `$S\profile-<tag>`:
   - `& $B --background --factory-startup --python-exit-code 1 --python tests\smoke_register.py` -> `SMOKE PASSED`
   - `& $B ... --python tests\smoke_import.py` -> `IMPORT PASSED` (all fixtures, packs, units checks)
   - `& $B ... --python tests\blender\run.py` -> `FIXTURES PASSED`
4. Local fixture outside the repo: `tests\smoke_import.py -- C:\maxdrop_fixtures\box_poly_standard.max` on 5.2 ->
   `IMPORT PASSED`.
5. `tools/baseline.py` on scene A (5.2): import finishes, no traceback; counts and peak recorded in the bead notes
   only (never committed).

Success: every line above passes on all three versions; no `FAIL` line.
