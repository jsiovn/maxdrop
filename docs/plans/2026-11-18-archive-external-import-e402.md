# Ruff E402 in intake/archive.py Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ruff check .` (ruff 0.17.5) passes again: the `from . import external` import of
`maxdrop/intake/archive.py` no longer sits after module-level code (E402).

**Architecture:** `external.py` never imports `archive.py` (it receives the module object through
`install()`), so its import can join the module's top import block next to `from .. import pathnames`
without a cycle. The `_external.install(sys.modules[__name__])` call stays where it is, right after
`_BACKENDS` is defined, so the .rar / .7z backends are registered at the same point of module load as
before. No `# noqa` needed.

**Tech Stack:** Python 3.11 syntax, ruff 0.17.5 (E4/E7/E9/F), unittest.

Bead: maxdrop-em3.65

---

### Task 1: Move the import

**Files:**

- Modify: `maxdrop/intake/archive.py` (top import block; the registration near `_BACKENDS`)

- [x] Red: `ruff check .` with ruff 0.17.5 in a scratch venv -> E402 at `archive.py:419`.
- [x] Add `from . import external as _external` after `from .. import pathnames`; remove it from the
      bottom; keep the comment and `_external.install(sys.modules[__name__])` after `_BACKENDS`.
- [x] `ruff check .` -> All checks passed.
- [x] `python -I -m unittest discover tests` -> OK (tests/test_intake*.py included).
- [x] build-and-test skill: build.ps1 + smoke on 4.2 / 4.5 / 5.2 (archive.py is imported on demand by
      the operator; smoke_import exercises the import path).
- [x] Commit: `Import external.py at the top of archive.py`.

## Verification

Changed: `maxdrop/intake/` (build-and-test row: blocks 1, 2, 5 = 3 and 4 on 4.2 / 4.5 / 5.2, 6 for a fix).

- Lint (the failing CI step): `ruff check .` with ruff 0.17.5 (a scratch venv) -> `All checks passed!`.
- Red check (block 6): the same `ruff check .` on the tree before the fix (`git archive c6fe12c`;
  `origin/epic/maxdrop-cyn` predates the regression) -> `E402` at `maxdrop/intake/archive.py:419`,
  exit 1. The bug is a lint failure, so ruff is the test.
- Block 1: `python -I -m unittest discover tests` -> `OK` (tests/test_intake*.py included).
- Block 2: `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...`.
- Blocks 3 and 4 on 5.2, 4.2 and 4.5: `tests/smoke_register.py` -> `SMOKE PASSED`; `tests/smoke_import.py`
  (no arguments: `tests/fixtures/*.max`, plus its `.zip` pack passes, which import intake/archive.py)
  -> `IMPORT PASSED`, equal `COUNTS` lines.
