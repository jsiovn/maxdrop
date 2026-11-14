# Operator and preferences for scene packs Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** File › Import › MaxDrop takes a `.max`, `.zip`, `.rar` or `.7z`; a drop takes `.max`, `.rar` or `.7z`;
an archive is listed, its scene chosen, unpacked, and the engine imports the `.max` from the pack folder.

**Architecture:** `maxdrop/ops.py` gets a resolve step in front of the unchanged engine: every selected path that
`intake.archive.kind()` recognises is listed (`list_pack`) and unpacked (`unpack`) into the folder the
preferences give; then `import_max.load()` runs once per resolved `.max` with `files=[<name>]`,
`directory=<folder>`. The scene of a pack with several is the operator property `pack_scene` (search callback
fed from a module-level listing cache that `invoke()` fills). `maxdrop/prefs.py` gets "Unpack scene packs into".

**Tech Stack:** Blender Python API 4.2–5.2, `maxdrop/intake/` (plain Python), headless smoke tests.

---

## Facts this plan relies on

- `ImportHelper.invoke_popup()` opens the props dialog when `filepath` is set, else the file browser
  (4.2.23 `bpy_extras/io_utils.py`). `ImportHelper.check()` only does the axis conversion: no extension rewrite.
- `import_max.load()` reads `fl.name` of every element of `files` and joins it with `directory`; with empty
  `files` it uses `filepath`. A `pathlib.Path(<base name>)` element works.
- `bpy.ops.*` raises `RuntimeError` carrying the message when the operator reports `ERROR`: the EXEC test of the
  two-scene zip reads the scene names from that message.
- `archive.unpack()` wraps every `OSError` into `PackError`: whether the archive's folder can be written is
  probed beforehand (`tempfile.mkdtemp` + `rmdir` in it), not inferred from the error.

## Chunk 1: preferences

### Task 1: "Unpack scene packs into"

**Files:** Modify `maxdrop/prefs.py`

- [ ] `pack_target: EnumProperty(items=(('ARCHIVE', "Next to the Archive", ...), ('FOLDER', "This Folder", ...)),
  default='ARCHIVE')`, `pack_dir: StringProperty(subtype='DIR_PATH')`; drawn as "Unpack Scene Packs Into" with the
  folder field below.
- [ ] `pack_parent(archive_path, context=None) -> str` (raises `ValueError` with the user message):
  - FOLDER: the folder (abspath, normpath); missing or not set -> error naming the preference.
  - ARCHIVE: the archive's folder when `writable()`; else the folder of the preference when set and writable;
    else error "Cannot write into <dir>. Choose a folder under Unpack Scene Packs Into in the MaxDrop
    preferences."
  - Without add-on preferences (headless dev package): the archive's folder.
- [ ] `writable(folder)`: `tempfile.mkdtemp(prefix=".maxdrop-probe-", dir=folder)` then `os.rmdir`; False on
  `OSError`.

## Chunk 2: operator

### Task 2: formats and labels

**Files:** Modify `maxdrop/ops.py`

- [ ] `filter_glob` default `*.max;*.zip;*.rar;*.7z`; handler `bl_file_extensions = ".max;.rar;.7z"`, `bl_label =
  "MaxDrop (.max, .rar, .7z)"`; menu text `MaxDrop (.max, .zip, .rar, .7z)`. `bl_idname`s unchanged. Dated
  "Modified for MaxDrop" line in the header.

### Task 3: resolve step

- [ ] `pack_scene: StringProperty(name="Scene", search=_scene_search, options={'SKIP_SAVE', 'SKIP_PRESET'})`.
- [ ] `_paths()`: `directory` + each non-empty `files[i].name`, else `[filepath]` when set.
- [ ] `_listing(path)`: module cache keyed by (normcase abspath, size, mtime_ns), at most 16 entries; calls
  `archive.list_pack`.
- [ ] `_packs(paths)`: `[(path, listing)]` for the paths whose `archive.kind()` is not None. A path with an
  archive extension that is not an archive -> `PackError` from `archive.backend_for` (its message). Problems
  checked here, each a `PackError` with a user message:
  - a pack without a scene: "<name> holds no .max scene: it is not a scene pack."
  - several packs and one of them holds several scenes: "<name> holds N scenes: import that pack alone to
    choose one."
- [ ] `_chosen(listing)`: one scene -> it; else `pack_scene` matched exactly, then by base name
  (case-insensitive, unique); empty -> None; no match -> `PackError` naming the scenes.
- [ ] `execute()`: no path -> error. Resolve packs; a pack needing a choice with `pack_scene` empty:
  if `self.options.is_invoke and not bpy.app.background` re-open with `bpy.ops.import_scene.maxdrop(
  'INVOKE_DEFAULT', filepath=..., directory=..., files=[...], <options>)` and return `{'CANCELLED'}` (a failure of
  that call falls through); else report ERROR "<name> holds N scenes: <list>. Choose one in the Scene field." and
  cancel. Unpack each pack with the wait cursor (`archive.unpack(path, scene, pack_parent(path))`); `PackError`
  or `ValueError` -> report ERROR, cancel. Then `import_max.load()` once per `.max`, one INFO report + console
  line `MaxDrop: <archive>: <scene> from <folder>: N files written|reused|in place, K skipped`.
- [ ] `invoke()`: with paths (drop, or a script with filepath): list the packs, problems -> report ERROR, cancel;
  then `invoke_popup`. Without paths: the file browser as before.
- [ ] `draw()`: a "Scene Pack" panel when a listed pack is among the paths (the scene field, alert when empty and
  needed; textures count; "Unpacks into <folder>"), and in the file browser always the Scene field (typed into
  when a pack holds several scenes).
- [ ] `_scene_search(self, context, edit_text)`: the scenes of the single pack among the paths (cached listing,
  listed on demand; any error -> no suggestions), filtered by `edit_text`.

## Chunk 3: manifest and tests

### Task 4: manifest

**Files:** Modify `maxdrop/blender_manifest.toml` (permission text only; version stays 0.0.1)

- [ ] `files = "Read .max scenes and textures, unpack scene archives"` (<= 64 chars, ends in a letter).

### Task 5: smoke tests

**Files:** Modify `tests/smoke_register.py`, `tests/smoke_import.py`

- [ ] smoke_register: handler extensions `.max;.rar;.7z`; the operator has `pack_scene`.
- [ ] smoke_import: an argument that is an archive (`.zip`/`.rar`/`.7z`) is imported through the operator with
  the same checks. For every `.max`: (a) import it, remember the image count; (b) build `<stem>.zip` in a scratch
  folder holding `<stem>/<name>.max` plus the image / `.ies` files of its folder tree; import it -> same checks,
  images >= (a), the pack folder `<scratch>/<stem>/` holds the `.max` and the marker, every image path is under
  the scratch folder; (c) `two.zip` with `a/<name>.max` and `b/second.max` in EXEC mode -> `RuntimeError` (or
  CANCELLED) whose message names both, nothing unpacked; (d) the same zip with `pack_scene="second.max"` ->
  FINISHED, a mesh arrives. Scratch folder removed at the end. No file -> `IMPORT SKIPPED` as before.

## Chunk 4: docs

**Files:** README.md, site/index.html, tests/test_site.py, docs/SUPPORT.md, SECURITY.md, CONTRIBUTING.md,
CHANGELOG.md

- [ ] README Use + FAQ "Can I give it the archive I downloaded?" (yes for .zip/.rar/.7z via File › Import; drop
  .rar/.7z; a dropped .zip opens Blender's own extension installer, which claims every dropped .zip first).
- [ ] site: Using it + a Troubleshooting entry; test_site asserts the new sentences.
- [ ] SUPPORT: Files (archives, unpackers), Textures (maps of a pack beside the scene).
- [ ] SECURITY: rewrite "What MaxDrop does with a file": what is unpacked and where, never unpacked or run,
  which programs may be started (UnRAR, 7-Zip, bsdtar from fixed paths, minimum versions, no shell, timeout).
- [ ] CONTRIBUTING: system unpackers found on the computer, never bundled; layout row for `maxdrop/intake/`.
- [ ] CHANGELOG: `## [0.0.2] - 2026-11-15` with Added lines (the gate bead sets the final date).

## Verification

Prerequisites: Windows, the repo root, the local fixture (outside the repo; its path is in the bead notes),
Blender 5.2 `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`, portable Blender 4.2.23 and 4.5.16
(paths in the bead notes),
WinRAR 7.23 `C:\Program Files\WinRAR\Rar.exe`. `<S>` = a fresh scratch folder in the session scratchpad.

1. `python -I -m unittest discover tests` -> `OK`.
2. For each of the three Blender paths `<B>` (Git Bash):
   `BLENDER_USER_RESOURCES=<S>/profile-<v> "<B>" --background --factory-startup --python-exit-code 1 --python tests/smoke_register.py`
   -> last line `SMOKE PASSED`, exit 0.
3. For each `<B>`:
   `BLENDER_USER_RESOURCES=<S>/profile-<v> "<B>" --background --factory-startup --python-exit-code 1 --python tests/smoke_import.py -- <the local fixture>`
   -> PASS lines for the .max, its zip (mesh, material, pack folder), the two-scene zip cancelled naming both
   scenes, the chosen scene; last line `IMPORT PASSED`, exit 0.
4. Blender 5.2 only: copy the fixture to `<S>/rar/box/`, run `"C:/Program Files/WinRAR/Rar.exe" a -r -ma5 -ep1
   <S>/rar/box.rar <S>/rar/box` then
   `... --python tests/smoke_import.py -- <S>/rar/box.rar` -> `IMPORT PASSED` (unpacked by UnRAR).
5. `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...`, extension validate passes (the
   permission text is accepted), check_zip passes.
6. Without fixture arguments on 5.2, `tests/smoke_import.py` -> `IMPORT SKIPPED` (tests/fixtures has no .max in
   a clean checkout; skip this check if the git-ignored copy is present).

Only a window can show (owner's check, bead maxdrop-tpr.5): the popup's Scene field and its search list, the
re-open after the file browser, the file browser side panel field, the drop of a .max / .rar / .7z on the 3D
Viewport, and a dropped .zip going to Blender's extension installer.
