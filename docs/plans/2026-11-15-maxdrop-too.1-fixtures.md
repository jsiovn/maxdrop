# Clean .max fixtures and the private-string guard Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Small self-authored `.max` fixtures in `tests/fixtures/`, the MAXScripts that author them, a sanitizer
that blanks the user and computer name 3ds Max writes into every file, and a check that keeps user, machine and
path strings out of the repository.

**Architecture:** Plain-Python tools (standard library, loaded by path in their tests, as `check_zip.py` is).
`tools/cfb.py` reads a Compound File (the `.max` container) and maps every stream byte to its file offset, so the
sanitizer can overwrite values in place. `tools/sanitize_fixture.py` parses the two OLE property-set streams and
replaces exactly the identity values with `x` of the same length. `tools/check_fixture.py` scans the raw file and
every stream (gunzipped when compressed) in ASCII and UTF-16LE, and also requires the identity properties to be
blank. One deterministic MAXScript per fixture in `tools/fixtures/`, run through the 3dsmax-mcp bridge.

**Tech Stack:** Python 3.11 syntax, standard library (`struct`, `re`, `gzip`, `zlib`, `getpass`, `socket`);
MAXScript on 3ds Max 2020; Blender 4.2 / 4.5 / 5.2 for the import smoke.

Bead: `maxdrop-too.1`. Owner decision (2026-11-15, bead notes): option (a), the sanitizer.

---

## What 3ds Max writes (measured on the local Max 2020 fixture)

- `\x05DocumentSummaryInformation`, section FMTID `D5CDD502-2E9C-101B-9397-08002B2CF9AE`, property 13
  (TitlesOfParts, `VT_VECTOR | VT_LPSTR`): entries `User Name=<user>` and `Computer Name=<machine>`.
- `\x05SummaryInformation`, FMTID `F29F85E0-4FF9-1068-AB91-08002B27B3D9`: property 8 (last author) and
  property 34 (`VT_LPSTR`) hold the user name; 4 (author) is the standard author slot. Property 17 is the
  thumbnail (about 600 KB of the file).
- No path strings were found. The stream names are fixed; the property streams sit in the mini stream.

## File Structure

- Create `tools/cfb.py`: `Compound(data)` -> `.names()`, `.read(name)`, `.runs(name)` (list of `(file offset,
  length)` covering the stream in order); bounded (sector chains checked for cycles and range, sizes capped).
  `CfbError` on anything malformed. `is_cfb(data)`.
- Create `tools/sanitize_fixture.py`: `identity_values(data)` -> list of `(stream name, offset in stream, length,
  kind, encoding)`; `sanitize(data)` -> `(new bytes, count)`; CLI `python -I tools/sanitize_fixture.py <file>...`
  rewrites in place, prints counts only, never the values; idempotent.
- Create `tools/check_fixture.py`: `problems(data, names=None)` -> list of kind strings; CLI exits 1 on any
  problem and prints `<file>: <kind> (<encoding>[, stream <name>])`, never the string.
  Kinds: `user name`, `computer name`, `user folder` (`Users\` or `Users/` followed by a name), `drive path`
  (`X:\` followed by at least two path characters, not preceded by a letter or digit), `identity property not
  blank` (the values the sanitizer targets are not all `x`). Names shorter than 3 characters are not searched.
- Create `tools/fixtures/<name>.ms` x 9: reset, fixed names and numbers, Standard materials, save to
  `C:\maxdrop_fixtures\<name>.max`; the units fixtures restore the system unit they found.
- Create `tests/test_fixtures.py`: cfb reader on a CFB built in the test; sanitizer + check on temp copies of
  `tests/fixtures/box_poly_standard.max` re-dirtied with fake names, the current user name, the computer name and a
  drive path; the scan over every committed fixture; only the identity bytes change.
- Create `tests/fixtures/*.max` (9 files, sanitized, checked, each < 1.5 MB).
- Modify `.github/workflows/test.yml`: import smoke step in the Blender job (and its header comment).
- Modify `CONTRIBUTING.md`: the fixture workflow and the new tools in the layout table.
- Modify `.claude/skills/build-and-test/SKILL.md`: the line saying `tests/fixtures/` holds no `.max`, and the
  fixture scan now `tools/check_fixture.py`.

## Tasks

### Task 1: tools/cfb.py + its tests
- [ ] Test: build a v3 CFB (512-byte sectors) in the test with one large stream (FAT) and one small (mini
  stream); `names()`, `read()` equal the input; `runs()` bytes equal `read()`; a FAT cycle raises `CfbError`.
- [ ] Implement; run `python -I -m unittest tests.test_fixtures -v` (cfb tests green).

### Task 2: tools/sanitize_fixture.py
- [ ] Parse property sets (header, FMTID/offset list, property id/offset list, `VT_LPSTR` 0x1E, `VT_LPWSTR`
  0x1F, `VT_VECTOR|VT_LPSTR` 0x101E, `VT_VECTOR|VT_VARIANT` 0x100C), bounded by the section size.
- [ ] Targets: DocumentSummaryInformation strings starting `User Name=` / `Computer Name=` (the part after `=`
  up to the first NUL); SummaryInformation properties 4 and 8; any other SummaryInformation or
  DocumentSummaryInformation string equal (casefolded) to a collected identity value.
- [ ] Overwrite each value range with `x` (`x\0` for UTF-16) through `runs()`; re-read and assert.

### Task 3: tools/check_fixture.py
- [ ] Needles: `getpass.getuser()`, `USERNAME`/`USER`, `socket.gethostname()` (also its first label),
  `COMPUTERNAME`; regexes for the folder and drive kinds; both encodings; case-insensitive.
- [ ] Haystacks: the raw bytes, plus each stream that starts with the gzip magic, decompressed up to 64 MB.
- [ ] Identity check reuses `sanitize_fixture.identity_values` (loaded by path).

### Task 4: tests/test_fixtures.py (sanitizer + check)
- [ ] Every `tests/fixtures/*.max` -> no problem.
- [ ] Temp copy dirtied (identity fields set to `jdoe1`-style text of the same length, and separately the
  current user / computer name injected into the Scene bytes, a `D:\scenes\` string, a UTF-16 `C:\Users\abc`)
  -> the check names the kind and the CLI exits 1 without printing the injected text.
- [ ] Sanitizing the dirtied copy returns the committed bytes exactly; a second run changes nothing.

### Task 5: MAXScripts and fixtures (3ds Max through the bridge, port 8766 this session)
- [ ] box_poly_standard, editable_mesh, hierarchy, instances, units_mm, units_cm, units_in, multi_uv,
  layers_flags. Run each, sanitize, check, copy to `tests/fixtures/`.

### Task 6: CI + docs
- [ ] `test.yml` import smoke step; CONTRIBUTING; build-and-test skill lines.

## Verification

Run from the repo root. `S` = session scratchpad, `B52` = installed Blender 5.2, `B42` / `B45` = portable
4.2.23 / 4.5.16 (paths in the bead notes).

1. `python -I -m unittest discover tests` -> `OK` (fixture scan included).
2. `python -I tools/check_fixture.py tests/fixtures/*.max` -> exit 0, one `clean` line per file.
   `python -I tools/check_fixture.py C:\maxdrop_fixtures\box_poly_standard.max` (as Max saved it, before
   sanitizing) -> exit 1, lines naming `user name`, `computer name`, `identity property not blank`, no name printed.
3. Import smoke on each Blender, no arguments (takes `tests/fixtures/*.max`):
   ```powershell
   $S="<scratch>"; foreach ($t in @(@("52","<B52>"),@("42","<B42>"),@("45","<B45>"))) {
     $env:BLENDER_USER_RESOURCES="$S\profile-$($t[0])"
     & $t[1] --background --factory-startup --python-exit-code 1 --python tests\smoke_import.py *>&1 | Out-File -Encoding utf8 "$S\import-$($t[0]).log"
     "$($t[0]) exit $LASTEXITCODE"; Select-String -Pattern "^IMPORT ","^FAIL ","^COUNTS " "$S\import-$($t[0]).log" }
   ```
   Pass: exit 0 and `IMPORT PASSED` on all three. A fixture the old engine cannot read is listed in the bead
   notes (not deleted) and passed explicitly only where it works.
4. Register smoke on 5.2 (CI change only touches the workflow; run once): `tests\smoke_register.py` -> `SMOKE PASSED`.
5. Build: `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...`.
6. `git diff --cached --stat` before each fixture commit: no file above 1.5 MB.
