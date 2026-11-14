# Scene packs gate (version 0.0.2) Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the scene-packs epic (maxdrop-tpr) on Blender 5.2, 4.2.23 and 4.5.16 and prepare release 0.0.2, not pushed.

**Architecture:** No engine or operator code changes. The gate runs throwaway Blender scripts kept in the session
scratch folder (never committed: they name local paths), builds the test archives around the local fixture in a
scratch folder outside the repo, and records every result in the bead's notes. The repository changes are the
version bump and the docs that must be true for 0.0.2.

**Tech Stack:** Blender headless (`--background --factory-startup`, isolated `BLENDER_USER_RESOURCES`), Python
`zipfile`, WinRAR `Rar.exe` 7.23 (rar, rar with password), bsdtar 3.8.9 (`tar -a -cf x.7z`), `python -m http.server`.

---

## Files

- Modify: `maxdrop/blender_manifest.toml` (`version = "0.0.2"`)
- Modify: `docs/SUPPORT.md` (first line and the "Version 0.0.1" headings -> 0.0.2; the engine is still io_scene_max 1.9.2's)
- Modify: `README.md` (the early-release note and "What version 0.0.1 imports")
- Modify: `SECURITY.md` ("version 0.0.1 uses the parser" -> 0.0.2)
- Modify: `site/index.html` ("This first version imports exactly what that importer imports" is no longer the first version)
- Modify: `CHANGELOG.md` only if the `## [0.0.2]` date is not the date of the gate (it is 2026-11-15 = today: keep)
- `tests/test_site.py`: changes only if a page sentence it asserts changes (none planned)
- Scratch, not committed: `gate_packs.py` (five pack cases), `corpus_pack.py` (scene A timing), `install_upgrade.py`

## Chunk 1: Version and docs

### Task 1: Bump and docs

- [ ] Set `version = "0.0.2"` in `maxdrop/blender_manifest.toml`.
- [ ] `docs/SUPPORT.md`: "**This page describes version 0.0.2.**" and say the engine is still io_scene_max 1.9.2's,
      with scene packs added in front of it; every "Version 0.0.1" table heading and the Textures paragraph -> 0.0.2.
- [ ] `README.md`: "version 0.0.2 imports exactly what that importer imports" and "## What version 0.0.2 imports".
- [ ] `SECURITY.md` line 55: "version 0.0.2 uses the parser inherited from io_scene_max as it is".
- [ ] `site/index.html` line 193: "This version imports exactly what that importer imports, also from the scene
      pack it came in; nothing more yet."
- [ ] Run `python -I -m unittest discover tests` -> `OK` (includes `test_this_release_is_in_the_changelog`).
- [ ] Commit `Set version 0.0.2 and make the docs true for it` (Bead: maxdrop-tpr.4).

## Chunk 2: The gate runs (scratch scripts, results in bead notes)

### Task 2: Five pack cases per Blender version — `gate_packs.py`

Runs inside Blender, imports the dev package from the repo root, `maxdrop.register()`. Inputs after `--`: repo
root, fixture path, scratch folder. For each kind it builds archives in `<scratch>/<kind>/case<n>/` (a fresh
folder per case so "nothing left behind" is a folder listing):

- archive contents: `box/box_poly_standard.max` + `box/maps/dummy.png` (a tiny valid PNG written by the script)
- kinds: `zip` (Python `zipfile`), `rar` (`Rar.exe a -ep1 -r`), `7z` (`tar -a -cf box.7z box`), each skipped with
  a reason when its tool is missing
- no-max archive: only `readme/dummy.png` (+ a `.txt`)
- password archive: zip via `tar --format zip --options zip:encryption=zipcrypt --passphrase x`; rar via
  `Rar.exe a -px` and `-hpx` (both); 7z: no local tool writes an encrypted 7z -> recorded "not testable here"

Checks per kind (each prints `GATE <kind> <case> yes|no [detail]`):

1. `bpy.ops.import_scene.maxdrop(filepath=archive)` -> `{'FINISHED'}`, a mesh with faces and a material slot with a material.
2. `<case>/box/box_poly_standard.max` and `<case>/box/.maxdrop-pack.json` exist; `dummy.png` beside them.
3. Second import of the same archive -> `{'FINISHED'}`; the case folder holds the same entries as after the first
   (no `box (2)`, no staging folder) and the marker's mtime is unchanged.
4. No-max archive -> cancelled (RuntimeError) with "holds no .max scene" in the message; the case folder holds
   only the archive afterwards.
5. Password archive -> cancelled with "password" or "encrypted" in the message; the case folder holds only the
   archive afterwards.

Ends with `GATE PASSED` (all testable cases yes) or `GATE FAILED: ...`, exit 1 on a no.

### Task 3: Corpus scene A on 5.2 — `corpus_pack.py`

Outside the repo: copy nothing; build `<scratch>/corpus/a.zip` (Python zipfile, deflate) and `a.rar`
(`Rar.exe a -ep1 -r -m1`) from scene A's folder. In Blender 5.2, import (a) the `.max` from its own folder,
(b) the zip, (c) the rar; record per run: unpack time (the `archive.unpack` call wrapped with a timer), total
time, files written (`UnpackResult.written`), images loaded (`len(bpy.data.images)`), no names. Remove the scratch
copies afterwards. Results go to the bead notes as counts only.

### Task 4: Localhost install + upgrade on 4.2 and 5.2 — `install_upgrade.py`

- [ ] Build 0.0.1: `git archive v0.0.1 maxdrop | tar -x -C <scratch>/v001` then
      `blender --command extension build --source-dir <scratch>/v001/maxdrop --output-dir <scratch>/serve`;
      `blender --command extension server-generate --repo-dir <scratch>/serve`.
- [ ] Serve: `python -m http.server <port> --bind 127.0.0.1 --directory <scratch>/serve` (own process, stopped by its pid).
- [ ] Run A (per Blender, `--online-mode`, fresh profile): add the remote repo `http://127.0.0.1:<port>/index.json`,
      sync, `extensions.package_install(repo_index=i, pkg_id="maxdrop")`, check installed version 0.0.1.
- [ ] Replace served content with the 0.0.2 build from `build.ps1` (`dist\maxdrop-0.0.2.zip` + regenerated index).
- [ ] Run B (same profile): point `update.REPO_URL` of the installed module at the local index, call
      `bpy.ops.maxdrop.check_updates()`, then `update._upgrade(index)`; check the manifest version is 0.0.2, the
      add-on registers (operator present) and `import_scene.maxdrop(filepath=<fixture zip>)` -> FINISHED with a mesh.

## Verification

Working directory: the repo root; Blender paths in the bead notes (5.2 installed, 4.2.23 and 4.5.16 portable).
Each Blender run: `BLENDER_USER_RESOURCES=<scratch>/profile-<ver>` + `--background --factory-startup --python-exit-code 1`.

1. `python -I -m unittest discover tests` -> `OK`
2. `<blender> ... --python tests/smoke_register.py` -> `SMOKE PASSED`, on 5.2, 4.2.23, 4.5.16
3. `<blender> ... --python tests/smoke_import.py -- <the local fixture>` -> `IMPORT PASSED`, on all three
4. `<blender> ... --python <scratch>/gate_packs.py -- <repo root> <the local fixture> <scratch>/gate-<ver>` -> `GATE PASSED` on all three (7z password case recorded as not testable)
5. `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...\dist\maxdrop-0.0.2.zip ...`; check_zip runs inside it; also `python tools/check_zip.py dist\maxdrop-0.0.2.zip` -> exit 0
6. Install 0.0.1 + upgrade to 0.0.2 from localhost on 4.2.23 and 5.2 -> version 0.0.2 installed, operator registered, pack import FINISHED
7. Corpus scene A on 5.2: zip and rar import FINISHED; counts recorded (no names); scratch copies removed

**Success criteria:** every command above reports its pass line with exit 0; each of the five cases is yes per
Blender version per archive kind, except the encrypted 7z, which no tool on this machine can create (reported).
A "no" is reported as a no in the close note.
