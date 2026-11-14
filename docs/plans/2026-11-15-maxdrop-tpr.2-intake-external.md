# maxdrop-tpr.2: .rar and .7z through the unpacker already on the computer

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** `maxdrop/intake/external.py` gives archive.py backends for `.rar` and `.7z` that run UnRAR, 7-Zip or
bsdtar found at fixed absolute paths, under the same rules as the zip backend, and say what to do when none is
usable.

**Architecture:** One `ExternalBackend` per archive kind holds an ordered tool chain (.rar: UnRAR, 7-Zip, tar;
RAR 4 without tar; .7z: 7-Zip, tar). `names()` lists with the first usable tool (parsed listing: UnRAR `lt`,
7-Zip `l -slt`, tar `-tf` + `-tvf`). `extract()` passes the EXACT archive paths of archive.py's plan through a
list file into a private work folder inside staging, watches the folder while the tool runs, discards it on any
non-zero exit or timeout and tries the next tool on a fresh work folder; on success every file is checked
(regular, one link, inside, no link or reparse point, name policy, exactly the planned names) and moved flat
into staging. archive.py registers the backends through `from . import external` (skipped when archive.py is
loaded by path), external.py receives the archive module through `install()`: no import cycle, both files stay
loadable on their own.

**Tech Stack:** Python 3.9+ standard library only (subprocess, threading, ctypes job objects on Windows,
winreg). No bpy.

Measured tool behaviour, the floors and their sources: the bead's notes ("Executor measurements").

---

## Files

- Create `maxdrop/intake/external.py`: discovery, version floors, process runner (job object / session,
  timeout, output cap, watchdog), listing parsers, argument builders, header checks (RAR volume / encrypted
  headers, split 7z), backends, `install(archive)`.
- Modify `maxdrop/intake/archive.py`: the registration block at the end only (plus the "Modified" line is not
  needed: the file is ours, GPL-3.0).
- Create `tests/test_intake_external.py`: pure tests (builders, parsers, versions, discovery on fake folders,
  headers, runner with Python children), real-tool tests printing `RAN` / `SKIPPED (reason)` per case.
- Create `tests/fixtures/packs/`: `normal.rar`, `solid.rar`, `pwdata.rar`, `pwhead.rar` (local Rar.exe 7.23,
  dummy content) and `plain.7z` (bsdtar), all with the same dummy tree; byte-scanned before commit.
- Modify `.github/workflows/test.yml`: install `libarchive-tools` in the plain-Python job.

## Task 1: external.py core (pure parts) + tests

- [ ] Version parsing (`UNRAR 7.23`, `7-Zip 26.06 (x64)`, `7-Zip [64] 16.02`, `7-Zip (z) 23.01`,
  `bsdtar 3.8.9 - libarchive 3.8.9`), floors table `FLOORS = {"unrar": (7, 23), "7z": (25, 1), "bsdtar":
  (3, 7, 4)}` with sources in a comment; system-tar exemption on POSIX `/usr/bin`, `/bin`.
- [ ] Discovery: candidate absolute paths per platform; Windows reads `App Paths\WinRAR.exe` and
  `SOFTWARE\7-Zip` (HKLM) for install folders; a candidate must be an absolute path, a regular file, `.exe` with
  `MZ` on Windows, ELF / Mach-O on POSIX (never a script, `.bat`, `.cmd`), not inside the pack's folder.
- [ ] Parsers for the three listings; wildcard characters in a path mark the entry unsupported for that tool
  (UnRAR `*?`, tar `*?[\`; 7-Zip runs with `-spd`).
- [ ] Argument builders (pure): list + extract per tool, `--` before the archive where supported, list file.
- [ ] Header checks: RAR 5 / RAR 4 volume flag and RAR 5 encryption header, 7z next-header beyond the file
  end, volume names (`.partN.rar`, `.rNN`, `.NNN`).
- [ ] Tests for each; run `python -I -m unittest tests.test_intake_external -v`.

## Task 2: runner, backends, registration + real-tool tests

- [ ] `_run(args, timeout, cap, watch)`: Popen (argument list, stdin DEVNULL, stdout+stderr one pipe, cwd =
  tool folder, reduced env, CREATE_NO_WINDOW / new session), job object with KILL_ON_JOB_CLOSE on Windows,
  reader thread with a byte cap, poll loop calling the watchdog; kill the tree on timeout / limit / overflow.
- [ ] Backends, fallback chain, messages (no unpacker, too old, password, multi-volume, tool error shortened).
- [ ] `archive.py`: registration block; `install()` in external.py.
- [ ] Fixtures + byte scan; real-tool tests (RAN / SKIPPED) incl. same files as the zip backend, passwords,
  duplicate collision, timing; optional `MAXDROP_TEST_7Z` = a 7z.exe outside the standard folders for the
  7-Zip cases (test only).
- [ ] Commit.

## Task 3: CI

- [ ] `test.yml` plain job: `sudo apt-get install -y -qq libarchive-tools` before the tests. YAML parse +
  `bash -n` on each run block.

## Verification

Working directory: the repo root. Machine paths come from the bead notes; none is committed.

1. `python -I -m unittest discover tests` -> `OK`; the output lists every real-tool case as `RAN` or `SKIPPED`.
2. Bundled Pythons, each -> `OK`:
   - `"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -I -m unittest discover tests`
   - `<portable Blender 4.2.23>\4.2\python\bin\python.exe -I -m unittest discover tests`
   - `<portable Blender 4.5.16>\4.5\python\bin\python.exe -I -m unittest discover tests`
3. Once with the portable 7-Zip of the scratchpad: `MAXDROP_TEST_7Z=<scratch>\7zip\7z.exe python -I -m
   unittest tests.test_intake_external -v` -> 7-Zip cases `RAN`, `OK`.
4. On this machine (System32 tar.exe, UnRAR.exe) the real-tool cases RAN: RAR 5 normal + solid + 7z give the
   files the zip backend gives for the same content; password on data / headers -> PackError, no staging left,
   each call under its timeout; two wood.jpg -> one kept, the other in `collided`.
5. Byte scan of `tests/fixtures/packs/` (ASCII and UTF-16LE, case-insensitive) for the Windows user name, the
   computer name and `C:\Users` / `\Users\` -> no hit; command and result go into the bead notes.
6. Workflow: `python -I -c "import yaml"` is not available everywhere: parse with the YAML parser of any
   bundled Python that has one, else a structural check; `bash -n` on each `run:` block -> no error. Close note:
   "workflow change unproven" (no push in this session).
7. Smoke register, isolated profile in the scratchpad, on Blender 5.2, 4.2.23, 4.5.16:
   `BLENDER_USER_RESOURCES=<scratch>/profile-<v> <blender.exe> --background --factory-startup --python-exit-code 1
   --python tests/smoke_register.py` -> `SMOKE PASSED`, exit 0.
8. `powershell -ExecutionPolicy Bypass -File build.ps1` -> zip contains `intake/external.py`; `git status
   --short` shows no build output.
