# Scene pack intake (.zip) Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `maxdrop/intake/archive.py` lists a scene pack and unpacks the chosen `.max` with its maps into a flat
folder, without ever letting a name stored in the archive decide where a file is written. `.zip` only; `.rar`
and `.7z` plug into the same backend interface in bead `maxdrop-tpr.2`.

**Architecture:** One self-contained module (no relative imports, no `bpy` / `mathutils`), loaded by path in its
tests. Format by magic bytes; a backend interface (`names()` / `extract()`); the rules (name policy, allow-list,
duplicate ranking, limits, destination, staging, marker) live outside the backends so later backends reuse them.

**Tech Stack:** Python 3.11 syntax, standard library only (`zipfile`, `struct`, `shutil`, `tempfile`, `json`).

Bead: `maxdrop-tpr.1`

---

## File Structure

- Create `maxdrop/intake/__init__.py`: docstring only (imported on demand; `maxdrop._purge()` drops it on reload).
- Create `maxdrop/intake/archive.py`:
  - `kind(path)`: `zip` / `rar` / `7z` / `None` from the first 8 bytes.
  - `PackError`: the only exception, message a user can act on.
  - `Limits` (frozen dataclass, defaults in one place) and `DEFAULT_LIMITS`; `_Budget` enforces files, bytes per
    file, total bytes and wall time while bytes are really written.
  - `Entry`: archive path, base name, directory parts, declared size, flags (directory, regular, encrypted,
    unsupported method, guessed name), backend key.
  - `ZipBackend.names(path)` / `ZipBackend.extract(path, wanted, staging, budget)`: `wanted` is a list of
    `(Entry, target base name)`; streams each entry with `ZipFile.open()` into `staging/<target>` (`"xb"`), never
    `extract()` / `extractall()`. `_BACKENDS = {"zip": ZipBackend()}`.
  - Name policy `refused_reason(base)`: empty, `.`, `..`, control character, `:`, the other characters Windows
    cannot store (`<>"|?*`, so a flat write can never fail half-way on Windows), reserved device names with any
    extension (CON, PRN, AUX, NUL, COM1-9, LPT1-9, also the superscript digits and CONIN$ / CONOUT$), a trailing dot
    or space, longer than 200 characters.
  - Allow-list: the chosen `.max`, images (`.jpg .jpeg .png .tif .tiff .tga .bmp .gif .exr .hdr .psd .dds .webp .jp2
    .tx`), `.ies`; casefolded.
  - Duplicates keyed by `NFC(base).casefold()`: same folder as the scene, then below it (fewer steps first), then by
    path steps; archive order breaks ties.
  - Zip names: UTF-8 flag -> as is; else raw bytes `orig_filename.encode("cp437")`: Info-ZIP Unicode Path extra
    field 0x7075 when its CRC matches (same result on 3.11 and 3.13), else strict UTF-8, else the first of `gbk`,
    `shift_jis`, `cp1252` that decodes, else `cp437` (guessed).
  - `list_pack(path, limits)` -> `PackListing(kind, scenes, assets, skipped, problems, encrypted, guessed)`.
  - `unpack(path, scene, dest_parent, limits, wanted)` -> `UnpackResult(max_path, folder, mode, backend, written,
    reused, skipped, refused, not_regular, collided, unwanted, guessed)`; `mode` is `unpacked` / `reused` /
    `in_place`.
  - Destination: one scene -> `<dest_parent>/<archive stem>/`; several -> `<dest_parent>/<archive stem>/<scene
    stem>/`, the container folder carrying its own marker (`scene: null`) so that a later scene of the same pack may
    be added to it. Candidates `<name>`, `<name> (2)`, ... up to 99: missing -> unpack there; matching marker and its
    `.max` present -> reuse; no marker but the chosen scene's base name within 3 levels -> use that copy in place;
    anything else -> next candidate.
  - Staging: `tempfile.mkdtemp(prefix=".maxdrop-staging-", dir=<parent of the destination>)`; marker written last
    inside staging, then `os.rename(staging, dest)`; any failure removes staging (and a container folder created by
    this call).
- Create `tests/test_intake.py`: archives built in a temp folder with `zipfile` (bytes patched where `zipfile`
  cannot write the case: encryption flag, Deflate64 method, raw non-UTF-8 names, multi-disk, lying size).
- Modify `.gitignore`: `.zip` -> `*.zip`, add `*.rar`, `*.7z`, negations for `tests/fixtures/packs/`.
- Modify `CLAUDE.md`: `maxdrop/intake/` in the planned layout (no bpy); archive rules under "Untrusted input".

## Tasks

### Task 1: tests first

- [ ] Write `tests/test_intake.py` covering: kind by magic (extension ignored, empty zip, unknown); a flat pack; a
  pack with folders; two scenes (container reused for the second); duplicates (same folder wins, then below, then
  steps; losers named); every refused name (nothing outside the destination, nothing under a refused name); a
  `../` and absolute name written flat inside; a lying size (backend reports 1 byte, writes stop at
  `max_file_bytes`, staging removed); a zip whose declared size lies (CRC error -> PackError, staging removed); a
  too-large pack (total, files, entries; nothing created); encrypted entry and Deflate64 entry (PackError, "by
  hand"); multi-disk; non-UTF-8 names (GBK guessed, UTF-8 without flag, 0x7075); a link entry; reuse through the
  marker; a folder without marker left untouched; a user-extracted copy used in place; `wanted`; no `bpy` /
  `mathutils` import under `maxdrop/intake/` (AST scan).
- [ ] Run `python -I -m unittest tests.test_intake` -> fails (module missing).

### Task 2: implement `maxdrop/intake/`

- [ ] Write `__init__.py` and `archive.py` as above.
- [ ] Run `python -I -m unittest discover tests` -> OK.

### Task 3: repository files

- [ ] `.gitignore` and `CLAUDE.md` edits; `git check-ignore -q` on `x.zip`, `pack.rar`, `pack.7z`.
- [ ] Commit (`Add the scene pack intake for .zip archives`, body with `Bead: maxdrop-tpr.1`).

## Verification

Working directory: the repo root. Blender paths are machine-specific (bead notes); never committed.

1. `python -I -m unittest discover tests` -> `OK`.
2. Bundled Pythons, each -> `OK`:
   - `"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -I -m unittest discover tests`
   - `D:\tools\blender\blender-4.2.23-windows-x64\4.2\python\bin\python.exe -I -m unittest discover tests`
   - `D:\tools\blender\blender-4.5.16-windows-x64\4.5\python\bin\python.exe -I -m unittest discover tests`
3. `git check-ignore -q x.zip && git check-ignore -q pack.rar && git check-ignore -q pack.7z` -> exit 0; and
   `git check-ignore -q tests/fixtures/packs/a.zip` -> exit 1.
4. Smoke register, isolated profile in the scratchpad, on each of Blender 5.2, 4.2.23, 4.5.16:
   `BLENDER_USER_RESOURCES=<scratch>/profile-<v> <blender.exe> --background --factory-startup --python-exit-code 1
   --python tests/smoke_register.py` -> last line `SMOKE PASSED`, exit 0.
5. `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...`; `python -c` listing of
   `dist/maxdrop-0.0.1.zip` shows `intake/__init__.py` and `intake/archive.py`; `git status --short` shows no
   build output.
