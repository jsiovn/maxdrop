# Shared pathnames helper Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One bpy-free module, `maxdrop/pathnames.py`, holds `base_name()` and the reserved Windows device names
(set plus check); `reader/assets.py`, `convert/textures.py`, `convert/report.py` and `intake/archive.py` use it
and their copies go. Bead: maxdrop-em3.41.

**Architecture:** A top-level module of the add-on, imported on demand (`from .. import pathnames`) by the three
bpy-free packages, so `_purge()` drops it on re-enable like the rest. `tests/unit/test_reader_no_bpy.py` allows
exactly this module as a relative import target outside reader/convert/intake, and scans it for bpy too. Tests that
loaded the consumers by path under a one-level synthetic package (`maxdrop_reader`, `maxdrop_convert`) or with no
package (`maxdrop_intake_archive`) switch to the existing stub-package pattern (`types.ModuleType` with
`__path__ = [maxdrop/]`, the add-on's `__init__` never runs), because `..` needs a parent package.

**Tech Stack:** Python 3.11 syntax, unittest, Blender 4.2 / 4.5 / 5.2 headless smokes.

---

## Chunk 1: helper, consumers, tests

### Task 1: maxdrop/pathnames.py

**Files:** Create `maxdrop/pathnames.py`; test `tests/unit/test_pathnames.py`.

- [ ] Test first (`tests/unit/test_pathnames.py`, stub package `maxdrop_convert_test`):
  - `base_name`: `""`→`""`, `"a.jpg"`, `C:\x\a.jpg`, `C:/x/a.jpg`, `\\host\share\a.jpg` → `a.jpg`; `"x/"`→`""`;
    `mixed/x\a.jpg`→`a.jpg`; `"C:a"`→`"C:a"` (no drive split: the caller's rules refuse it).
  - `is_reserved`: CON, con, `Con.txt`, `NUL.tar.gz`, `AUX .jpg` (space before the dot), `COM1`, `LPT9`, `COM¹`,
    `LPT³`, `CONIN$`, `conout$.x` → True; `COM0`, `LPT`, `CONSOLE`, `xCON`, `a.CON`, `""`, `COM10` → False.
  - `RESERVED` is a frozenset of 6 + 12 + 12 = 30 names.
- [ ] Run: `python -I -m unittest tests.unit.test_pathnames` fails (no module).
- [ ] Implement:

```python
RESERVED = frozenset(["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
                     + ["%s%s" % (p, d) for p in ("COM", "LPT") for d in "123456789¹²³"])

def base_name(path):
    return path.replace("\\", "/").rsplit("/", 1)[-1]

def is_reserved(name):
    return name.split(".", 1)[0].rstrip(" ").upper() in RESERVED
```

- [ ] Run the test: OK.

### Task 2: point the consumers at it

**Files:** `maxdrop/reader/assets.py`, `maxdrop/convert/textures.py`, `maxdrop/convert/report.py`,
`maxdrop/intake/archive.py`, `maxdrop/intake/external.py` (docstring only).

- [ ] assets.py: `from .. import pathnames`; drop `base_name`; `AssetEntry.name` uses `pathnames.base_name`.
- [ ] textures.py: `from .. import pathnames`; drop `_RESERVED` and `base_name`; `refused_reason` uses
  `pathnames.is_reserved(p)`; `find()` uses `pathnames.base_name`. Docstring "no reader import" stays true.
- [ ] report.py line 254: `pathnames.base_name` (`from .. import pathnames`).
- [ ] archive.py: `from .. import pathnames`; drop `_RESERVED`; `refused_reason` uses `pathnames.is_reserved`.
  Module docstring: no longer self-contained; tests load it under a stub package. The external backends register
  unconditionally (the "loaded by path without its package" mode is gone: the module needs its package now).
- [ ] external.py docstring: drop "(the tests load them by path)".

### Task 3: tests

**Files:** `tests/unit/test_assets.py`, `tests/unit/test_textures.py`, `tests/unit/test_reader_no_bpy.py`,
`tests/test_intake.py`, `tests/test_intake_external.py`.

- [ ] test_assets.py, test_textures.py: load through `_PKG = "maxdrop_convert_test"` (the package the other
  convert tests make) with `importlib.import_module`.
- [ ] test_textures.py: delete `CopiesTest` (equality tests replaced by test_pathnames).
- [ ] test_intake.py: own stub `maxdrop_intake_zip_test`; after import, pop the `rar` / `7z` backends so the
  suite stays zip-only (as before, when it loaded the file without its package).
- [ ] test_intake_external.py: stub `maxdrop_convert_test`; `external` = the package's `intake.external` (the one
  archive.py installed); drop the manual `install()` call. `test_archive_registers_in_its_package`: the stub
  package's path is `maxdrop/`, import `mdpkg.intake.archive`.
- [ ] test_reader_no_bpy.py: `SHARED = ("pathnames",)`; `_refused` accepts a relative `maxdrop.pathnames`;
  `modules()` also yields `maxdrop/pathnames.py`; the absolute-import and other-module cases stay refused
  (extend `test_other_modules_of_the_addon_are_refused` with `from .. import pathnames` accepted and
  `import maxdrop.pathnames` refused).

### Task 4: docs

- [ ] CLAUDE.md Architecture Overview: a bullet for `maxdrop/pathnames.py` (shared bpy-free name rules, the only
  module outside reader/convert/intake they may import).
- [ ] Commit: `Share base_name and reserved device names in one module`.

## Verification

Working directory `D:\www\maxdrop`.

- `python -I -m unittest discover tests` -> `OK` (skips allowed as before).
- Without numpy: `python -m venv <scratch>\venv-nonumpy` then `<scratch>\venv-nonumpy\Scripts\python -I -m
  unittest discover tests` -> `OK`.
- `powershell -ExecutionPolicy Bypass -File build.ps1` (and `-Blender <path>` for 4.2 and 4.5 portable builds) ->
  zip in `dist\`, `tools/check_zip.py` accepts it (build.ps1 runs it).
- Per Blender (5.2 installed; 4.2 and 4.5 portable, paths in the build-and-test skill), isolated profile:
  `BLENDER_USER_RESOURCES=<scratch> blender --background --factory-startup --python-exit-code 1 --python
  tests/smoke_register.py` -> passes (register, reload, register, unregister: pathnames is purged and re-imported);
  `... --python tests/smoke_import.py` -> `FIXTURES PASSED`.
- Success: all of the above on 4.2, 4.5 and 5.2.
