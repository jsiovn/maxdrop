# Pack names APFS cannot store Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stored name that holds an unassigned code point or a lone surrogate is refused by the name policy on
every OS, so a scene pack never fails half-way on macOS (APFS: EILSEQ) while Windows and Linux write it.

**Architecture:** `archive.refused_reason` gains one named reason, checked by Unicode category (`Cn`, `Cs`), next
to the `_FORBIDDEN` rule that already refuses on every OS what one OS cannot store. The map is then skipped and
reported (`UnpackResult.refused`) like any other refused name. The property test keeps one rule for all OSes: both
of its OS branches (the `UnicodeEncodeError` one and the darwin `EILSEQ` one) go.

**Tech Stack:** Python 3.11 / 3.13 (`unicodedata`), unittest.

Bead: maxdrop-em3.157

---

## Decision

- Refuse on every OS, not only for the target folder's OS: the output stays deterministic (the same pack writes
  the same files on every machine) and the property test promises one thing everywhere. Same reasoning as
  `_FORBIDDEN` (Windows' characters refused on Linux too).
- Only `Cn` (unassigned, noncharacters included) and `Cs` (lone surrogates: the `\udc80`-`\udcff` of a
  surrogateescape listing in `external.py`, or a lone one from a zip's UTF-16 name). Private use (`Co`) stays
  accepted: 95 of the 300 created names hold one and APFS stores them (legacy CJK names decode to them). Format
  characters (`Cf`) stay accepted.
- Evidence (no local macOS): run 45041269014 (PR #26, macOS, Python 3.13) failed on 30 names with EILSEQ; all 30
  hold a `Cn` code point by Python 3.13's tables (checked from the job log). Python's rule refuses 34 of the 300
  (a little more than APFS: safe).
- "Unassigned" follows the interpreter's Unicode tables (14.0 on Python 3.11 = Blender 4.2/4.5, 15.1 on 3.13 =
  Blender 5.2): a character assigned in 15.0/15.1 is accepted on 5.2 and refused on 4.x. Deterministic per
  Blender, written in the comment. A character newer than APFS's own tables could still fail there (clean failure,
  as today); unmeasured.
- Lost by the rule: a name that was not valid in the archive's encoding (surrogateescape) now is skipped on Linux
  too, where it used to be written as raw bytes. Such a name can never equal a texture reference of the `.max`
  (valid Unicode), so no map the scene uses is lost; a `.max` with such a name is no longer offered as a scene.

## Other callers of refused_reason (checked, none blocks)

- `_is_scene`, `list_pack`: a `.max` / asset with such a name is not listed (same as any refused name).
- `_select`: the map goes to `result.refused` with the reason.
- `_stale_reservation`: filters the names listed in a reservation through the policy: a name now refused is not
  counted as a map of the pack. A reservation written by the old code naming such a map: the folder holds that
  file, which is no longer "a map it lists", so the folder is not cleared as stale; the unpack takes another
  name. Rare (a crash mid-move of such a pack) and safe.
- `_safe_stem`: the folder name falls back as for other refused stems.
- `external.py:789`: a refused name in a tool's output fails the pack, but the tool is only asked for names that
  passed the policy (`wanted` comes from `_select`), so it cannot write such a name.

## Task 1: test first

**Files:** `tests/test_intake_fuzz.py` (owned by this bead; `tests/test_intake.py` is left alone).

- [ ] New class `UnstorableNameTest`: `refused_reason` returns the new reason for `"wood￿.jpg"` (a
      noncharacter: never assigned), the plane 14 noncharacter `"\U000EFFFE"`, a lone `"\ud800"`, a
      surrogateescape `"\udcff"`; accepted: `".jpg"` (private use), `"a​b.jpg"` (Cf),
      `"中文.png"`, `"\U0001F600.jpg"`.
- [ ] End to end: a zip with `room.max`, `ok.jpg` and `wood￿.jpg` (UTF-8 flag) unpacks; `ok.jpg` written,
      the bad name in `result.refused` with the new reason, not on disk.
- [ ] Add `"￿"` and `"͸"` (unassigned since forever in Greek) to `TOKENS`.
- [ ] Property test: assert no `Cn`/`Cs` in an accepted name; drop both `except` branches of
      `test_an_accepted_name_creates_exactly_that_file`.
- [ ] Run: red (the new tests fail, the property test fails on lone surrogates off Windows only; on Windows the
      unit test is red).

## Task 2: the rule

**Files:** `maxdrop/intake/archive.py` (`refused_reason`).

- [ ] After the control-character check: `if any(unicodedata.category(c) in ("Cn", "Cs") for c in base): return
      "unassigned or unpaired Unicode character"`, with a comment (APFS EILSEQ; interpreter tables).
- [ ] Green on the system Python, Blender 4.5's 3.11 and Blender 5.2's 3.13.

## Task 3: docs

- [ ] `CHANGELOG.md` `## [Unreleased]`: one added line (no neighbours touched).
- [ ] `SECURITY.md`: the refused names list names this class too.

## Verification

- `python -I -m unittest discover tests` (system Python and both Blender Pythons), `python -I tools/lint.py`.
- build.ps1 + smoke on 4.2 / 4.5 / 5.2 (build-and-test skill).
- Unverified locally: the macOS job of test.yml; it runs in part F's pull request.
