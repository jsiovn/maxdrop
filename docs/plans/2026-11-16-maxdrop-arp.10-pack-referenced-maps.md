# Unpack only the maps a scene references Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** importing a scene pack writes the chosen `.max` and only the image / `.ies` files its asset table names,
instead of every image of the pack.

**Architecture:** `archive.unpack()` already takes `wanted` (a set of base names, kept in the marker so a filtered
folder serves only what it covers). The set is only known once the `.max` is on disk, so `unpack()` gets a second,
exclusive way to say it: `references`, a callable asked about a `.max` path that returns the base names the scene
uses (None: every asset). With `references`, a fresh unpack writes the scene into the staging folder first, asks
`references` about that file, then selects and writes the maps through the same backend and budget (a second
`extract()` call); an earlier unpack is reused when the set computed from its `.max` is covered by its marker.
`existing_folder()` takes the same callable so the popup announces what `unpack()` will do. `ops.py` passes a
callable that reads `reader.assets.AssetTable` of the file and returns the names of its entries; it returns None
(unpack everything) when the file has no asset stream, the table is damaged or the file cannot be read.
`archive.py` stays self-contained (no reader import).

**Tech Stack:** Python 3.11, zipfile, unittest; Blender 4.2 / 4.5 / 5.2 for the smoke tests.

---

## Files

- Modify: `maxdrop/intake/archive.py` (`unpack`, `existing_folder`, `_destination`, `_probe`, `_marker_matches`,
  `_check_space`; new `_wanted_at`)
- Modify: `maxdrop/ops.py` (new `_referenced_maps(max_path)`; passed to `archive.unpack` and, through
  `_existing`, to `archive.existing_folder`)
- Test: `tests/test_intake.py` (class `References`)
- Docs: `CHANGELOG.md` `[Unreleased]` line, `docs/SUPPORT.md` if it describes what a pack unpacks

## Task 1: archive.unpack(references=...)

- [ ] Tests in `tests/test_intake.py`, class `References`:
  - the callable is called once with the staged `.max` (an existing file inside a `.maxdrop-staging-` folder beside
    the destination) and only the named maps are written; `unwanted` counts the rest; marker `wanted` is the sorted
    `name_key` list
  - a callable returning None writes every asset and stores `wanted: null`
  - reuse: same callable -> `mode == "reused"`; a callable naming one more map -> a new folder (`pack (2)`);
    `existing_folder(..., references=...)` agrees with `unpack()` in both cases
  - an encrypted map the scene does not use no longer fails the unpack
  - a callable that raises leaves no staging folder and no destination
  - `wanted` and `references` together -> ValueError
- [ ] Run `python -I -m unittest tests.test_intake` -> new tests fail
- [ ] Implement in `archive.py`; run again -> OK; full `python -I -m unittest discover tests` -> OK
- [ ] Commit `Unpack a pack's maps after asking the scene which it uses`

## Task 2: ops.py passes the scene's asset names

- [ ] `_referenced_maps(max_path)`: `cfb.CompoundFile` + `assets.AssetTable.from_file`; None when
  `table.stream is None`, `table.issues`, or any error (one console line); else `{e.name for e in table if e.name}`
- [ ] `archive.unpack(path, chosen[path], parent, references=_referenced_maps)`;
  `_existing(...)` -> `archive.existing_folder(..., references=_referenced_maps)`
- [ ] CHANGELOG / SUPPORT lines
- [ ] Commit `Unpack only the maps the chosen scene names`

## Verification

Working directory: repo root. Blender paths from the bead's environment block (4.2.23, 4.5.16 portable; 5.2 installed).

1. `python -I -m unittest discover tests` -> `OK`
2. `powershell -ExecutionPolicy Bypass -File build.ps1` -> zip, index.json, index.html in `dist\`
3. For each Blender: `BLENDER_USER_RESOURCES=<scratch> <blender> --background --factory-startup --python-exit-code 1
   --python tests/smoke_register.py` -> `SMOKE PASSED`; `... --python tests/smoke_import.py` -> `IMPORT PASSED`
   (the fixtures, each also as a .zip pack)
4. For each Blender, a scratch script (outside the repo): zip `tests/fixtures/vray_maps.max` with one map it names
   (from its asset table) plus an unrelated `unused.png`, import the zip through `bpy.ops.import_scene.maxdrop`
   -> FINISHED, the pack folder holds the `.max` and the named map but not `unused.png`, the marker's `wanted`
   lists the named map, the report says `Files the scene does not use, left out: 1`.
