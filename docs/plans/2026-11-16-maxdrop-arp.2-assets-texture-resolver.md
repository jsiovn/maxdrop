# Asset table and safe texture resolver Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read the path of every file a scene names (asset GUID -> type, path) and find each texture on the
user's disk in a fixed order, never following a stored path to a network, device or climbing location.

**Architecture:** `maxdrop/reader/assets.py` (no bpy) parses the `FileAssetMetaData3` / `FileAssetMetaData2`
stream into an `AssetTable` and maps a material graph's `pblock.Asset` values to entries (a Bitmap's file is its
parameter 13). `maxdrop/convert/textures.py` (no bpy, no reader import) holds the stored-path policy
(`refused_reason`), a `TextureIndex` built once per import (one bounded walk per rule tier, lazily, nearest file
first) and a `TextureReport` (found per rule, missing by file name). Wiring into the material build is bead
maxdrop-arp.6 (build/materials.py, ops.py): out of this bead's Files.

**Tech Stack:** Python 3.11 syntax (tests also run on the local 3.9), unittest, os.scandir, ctypes on Windows.

---

## Format facts (verified 2026-11-16 on vray_maps, standard_physical and the two corpus scenes)

- Stream `FileAssetMetaData3` (Max 2018+ files; every committed fixture, scene B) or `FileAssetMetaData2`
  (scene A). Empty (0 bytes) when the scene names no file.
- Records back to back, no header, no count. A string = `u32` count of UTF-16 units (without the NUL), the
  units, then a UTF-16 NUL (always, also for count 0).
  - v2 record: 16-byte asset GUID, type string (`Bitmap`, `Photometric`), path string.
  - v3 record: the same plus a third string: the absolute path 3ds Max resolved the file to when saving
    (empty when it was not found, or when the path was absolute already).
- Corpus: scene A 155 records (153 Bitmap, 2 Photometric), 154 bare file names, 1 absolute path; scene B 168
  records, 167 bare names with an absolute resolved path of the same base name, 1 absolute path. GUIDs unique.
- A Bitmap's file: `pblock.Asset` in parameter 13 (`bitmap`, type 16) of its block 0 (already read by
  reader/pblock.py); `fileName` (16) is transient and not stored.

## File structure

- Create `maxdrop/reader/assets.py`: `AssetEntry`, `AssetTable` (`from_file`, `parse`, `get`, `entry`),
  `bitmap_file(table, mtl)`, `files_of(table, mtl)`.
- Create `maxdrop/convert/textures.py`: `base_name`, `name_key`, `refused_reason`, `Found`, `TextureIndex`,
  `TextureReport`, rule constants.
- Create `tests/unit/test_assets.py`, `tests/unit/test_textures.py`.
- Modify `maxdrop/prefs.py` (label out, tooltips in), `docs/FORMAT.md`, `docs/SUPPORT.md`, `README.md`,
  `SECURITY.md`, `site/index.html`, `CHANGELOG.md` (Unreleased).

## Chunk 1: reader/assets.py

### Task 1: asset table

**Files:** Create `maxdrop/reader/assets.py`, test `tests/unit/test_assets.py`

- [ ] Tests first (synthetic records built by a helper `record(guid, type, path, resolved=None)`):
  v3 and v2 parse; empty stream -> empty table; count past the end -> records before it kept, one issue;
  missing NUL -> issue; string longer than `MAX_STRING` -> issue; duplicate GUID -> first kept, issue; stream
  over `MAX_STREAM` -> empty table with issue; `get()` takes bytes or `pblock.Asset`; `AssetEntry.name` is the
  base name of `path`, else of `resolved` (`\` and `/` both separators).
- [ ] Fixture tests: every committed fixture opens; `vray_maps` has 7 entries, `standard_physical` 1, the rest 0;
  for every Bitmap reached by the material graph (`MaterialGraph.walk` over the nodes' materials),
  `bitmap_file(table, m).name` equals the oracle's `fileName` parameter (id 16) of that map; no issue.
- [ ] Implement:

```python
STREAMS = (("FileAssetMetaData3", 3), ("FileAssetMetaData2", 2))
MAX_STREAM = 64 << 20
MAX_STRING = 32767          # a Windows long path, in UTF-16 units

class AssetEntry(namedtuple("AssetEntry", "guid type path resolved")):
    name -> base name of path or resolved

class AssetTable:
    from_file(cf)            # first stream of STREAMS that exists; none -> empty
    parse(data, strings)     # strings = 2 or 3
    get(guid_or_asset), entry(value) (None unless a pblock.Asset), __len__, __iter__, issues
def files_of(table, mtl)     # [(block_id, pid, entry)] for every Asset value of mtl's blocks and parts
def bitmap_file(table, mtl)  # class BITMAP_TEX only: param 13 of block 0 -> entry, else None
```

- [ ] Run `python -I -m unittest tests.unit.test_assets -v` -> OK. Commit `Read the asset table of a scene`.

## Chunk 2: convert/textures.py

### Task 2: stored-path policy and the index

**Files:** Create `maxdrop/convert/textures.py`, test `tests/unit/test_textures.py`

- [ ] Tests first, on a temp tree (`tempfile.TemporaryDirectory`):
  - rule 1: `<root>/proj/scene/a.jpg` found for stored `D:\\old\\A.JPG` (case-insensitive), rule 1.
  - rule 2: `<root>/proj/scene/Maps/b.png` and `<root>/proj/Textures/sub/c.tga` found, rule 2 (sibling
    folders of the scene file, i.e. inside the scene's folder, and of the scene's folder, i.e. inside its parent).
  - rule 3: `<root>/lib/x/y/d.exr` found through `user_dirs=[<root>/lib]`, rule 3; not found past `max_depth`;
    walk stops at `max_entries` (files and folders) and the report names the rule and folder once.
  - rule 4 (Windows only, skipped elsewhere): `<root>/elsewhere/e.jpg` by its absolute path with
    `is_local_drive=lambda p: True` -> rule 4; with `lambda p: False` -> None.
  - priority: same name in scene folder and maps -> rule 1; nearest (shallower) file wins inside a tier.
  - refusals: `\\\\host\\share\\a.jpg`, `..\\..\\a.jpg`, `\\\\?\\<root>\\outside\\a.jpg` (an existing file),
    `//host/share/a.jpg`, `C:a.jpg`, `C:\\x\\..\\a.jpg`, `C:\\a.jpg:stream` -> `refused_reason` not None; with
    the file existing only at the place the path names, `find` returns None and `is_local_drive` is never
    called with it (spy).
  - Image Search: `scene_subfolders=True` finds `<scene>/deep/f.jpg` as rule 1; False does not.
  - index built once: a second `find` does not scan again (count `os.scandir` calls through a wrapper).
  - report: found per rule counts each texture once (two finds of one name = 1), missing names sorted unique,
    `lines()` gives the summary.
- [ ] Implement:

```python
SCENE, SIBLING, USER, ORIGINAL = 1, 2, 3, 4
SIBLING_NAMES = frozenset(("maps", "textures"))
DEFAULT_MAX_DEPTH, DEFAULT_MAX_ENTRIES = 8, 200_000    # files and folders, per tier

def base_name(path), name_key(name)                     # NFC casefold
def name_refused(name)                                  # "", ".", "..", control chars, ':' '/' '\\'
def refused_reason(path)                                # rule 4 policy: empty/NUL/control, \\ or // start,
                                                        # not X:\ form, '..' part, ':' after the drive
def is_local_drive(path)                                # Windows GetDriveTypeW in removable/fixed/cdrom/ramdisk
class Found(namedtuple("Found", "path rule"))
class TextureIndex:
    __init__(scene_path, user_dirs=(), scene_subfolders=False, max_depth=..., max_entries=...,
             is_local_drive=is_local_drive)
    find(path, resolved=None) -> Found | None            # cached per (path, resolved); records into report
    report                                              # TextureReport
class TextureReport: found {rule: n}, missing [names], truncated [(rule, folder, n)], lines()
```

  Walk: breadth first, entries sorted by name, never into a symlink or reparse-point folder, files only (no
  symlinked file), every OSError skipped; one dict per tier, first path per key kept; tiers built on first
  need. Rule 4 tries `path`, then `resolved`: `refused_reason` None, the drive local, `os.path.isfile`.
- [ ] Run `python -I -m unittest tests.unit.test_textures -v` -> OK. Commit `Find textures in a fixed, safe order`.

## Chunk 3: preferences and docs

### Task 3

**Files:** `maxdrop/prefs.py`, `docs/FORMAT.md`, `docs/SUPPORT.md`, `README.md`, `SECURITY.md`,
`site/index.html`, `CHANGELOG.md`

- [ ] prefs: drop the "Not searched yet" label and its comment; the folder row's tooltip and the Add operator's
  description give the lookup order (scene folder, maps / textures folders beside the scene and its folder, these
  folders with subfolders, the stored path only on a local drive); keep "Unpack Scene Packs Into" as it is.
- [ ] FORMAT.md: a section "Asset metadata (FileAssetMetaData2 / 3)" with the record layout above.
- [ ] SUPPORT.md "Textures", README, SECURITY.md, site/index.html: the lookup order and the refusals; packs still
  land flat in the scene's folder (rule 1). No test needle of tests/test_site.py changes.
- [ ] CHANGELOG `[Unreleased]`: one Changed line.
- [ ] `python -I -m unittest discover tests` -> OK. Commit `Describe how textures are found`.

Note for maxdrop-arp.6 (recorded in this bead's close note): build `TextureIndex(max_path,
prefs.texture_dirs(), scene_subfolders=use_image_search)` once per import, look each asset entry up with
`find(entry.path, entry.resolved)` and feed `index.report` to the import report; until then the old engine's
lookup is what runs.

## Verification

Working directory: the checkout root. `S` = this session's scratchpad.

1. Plain tests: `python -I -m unittest discover tests` -> exit 0, `OK` (a rule-4 skip only off Windows).
2. Build: `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...maxdrop-0.0.3.zip ...`.
3. Register smoke on 5.2, 4.2.23, 4.5.16 (paths in the bead notes), each with its own profile:
   `$env:BLENDER_USER_RESOURCES="$S\profile-<tag>"; & $B --background --factory-startup --python-exit-code 1
   --python tests\smoke_register.py` -> exit 0, `SMOKE PASSED`.
4. Import smoke on the three versions without arguments (the committed fixtures) -> `IMPORT PASSED`, equal
   `COUNTS` lines (prefs.py changed).
5. Corpus, local only: a scratch script in `S` builds `AssetTable.from_file` + `TextureIndex(scene)` for scene
   A and B and prints only counts per rule and missing count; the share resolved goes into the bead notes, no
   name.
6. Fixture scan unchanged (no fixture added).

Success: every block passes on every version; no corpus name leaves `S`.
