# maxdrop-too.12 CI: unit tests, the no-bpy guard, ruff, fixture tests on the Blender matrix

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Test workflow runs what milestone M1 adds, on Ubuntu and Windows, so a push cannot ship a reader
that only works on one machine.

**Architecture:** Workflow and configuration only. The plain job becomes an OS matrix (ubuntu-latest,
windows-latest, Python 3.11, bash on both) running the unit tests, the fixture scan over `tests/fixtures/` and
`tests/fixtures/packs/`, and ruff (Linux) with a minimal committed configuration. The existing no-bpy guard
(`tests/unit/test_reader_no_bpy.py`) also covers `maxdrop/intake` and imports of other `maxdrop` modules (which
may import `bpy`). The Blender job runs `tests/blender/run.py` after the import smoke when that file exists
(bead maxdrop-too.9 adds it). Dependabot keeps the actions current.

**Tech Stack:** GitHub Actions, Python 3.11 unittest, ruff (pinned), Blender 4.2.23 / 4.5.16 / 5.2.4.

---

## Findings before planning

- `tests/blender/run.py` does not exist yet: bead maxdrop-too.9 creates it, and this bead does not depend on
  too.9. The step is gated with `if: hashFiles('tests/blender/run.py') != ''`, so it switches on by itself.
- `tests/unit/test_reader_no_bpy.py` already exists (from maxdrop-too.3) and scans `reader` and `convert`.
- `ruff check` with the classic minimal set `E4,E7,E9,F` (pinned explicitly: newer ruff releases widen the
  default set) finds one problem outside `import_max.py`: an unused `Counter` import in
  `maxdrop/intake/archive.py`. Removing it is the one-line change needed for "ruff check clean".
- `tools/check_fixture.py` scans any file; identity-slot checks apply to compound files only, so the packs and
  oracle JSON scan clean as raw bytes (verified locally: every file of both folders "clean").

## Files

- Modify: `tests/unit/test_reader_no_bpy.py` (intake, maxdrop-internal imports)
- Modify: `pyproject.toml` (add `[tool.ruff]`, keep the autopep8 block)
- Modify: `maxdrop/intake/archive.py:31` (drop the unused import)
- Modify: `.github/workflows/test.yml`
- Create: `.github/dependabot.yml`
- Modify: `CONTRIBUTING.md`

### Task 1: The guard covers intake and maxdrop-internal imports

- [ ] Add a failing test: a scratch module with `from .. import compat`, `from ..ops import x`,
  `import maxdrop.update`, `from . import sibling`, `from ..reader import cfb` → 3 hits (the last two allowed).
- [ ] `PACKAGES = ("reader", "convert", "intake")`; resolve relative imports against the module's package and
  flag any `maxdrop.<name>` target whose `<name>` is not in `PACKAGES` (or that climbs above `maxdrop`).
- [ ] Assert the scan saw `maxdrop/intake/archive.py` too.
- [ ] `python -I -m unittest tests.unit.test_reader_no_bpy -v` → OK.

### Task 2: ruff

- [ ] Append to `pyproject.toml`:

```toml
[tool.ruff]
line-length = 120
target-version = "py311"
# The upstream engine is replaced step by step (strangler) and deleted when empty: not linted meanwhile.
extend-exclude = ["maxdrop/import_max.py"]

[tool.ruff.lint]
# Errors only, stated explicitly so a newer ruff does not widen the set on its own.
select = ["E4", "E7", "E9", "F"]
```

- [ ] Drop `from collections import Counter` in `maxdrop/intake/archive.py`.
- [ ] `ruff check .` (scratch venv) → `All checks passed!`

### Task 3: test.yml

- python job: `strategy.matrix.os: [ubuntu-latest, windows-latest]`, `fail-fast: false`, `defaults.run.shell:
  bash`, `actions/setup-python@v5` with 3.11; bsdtar step `if: runner.os == 'Linux'`; unit tests; fixture scan
  `python -I tools/check_fixture.py "tests/fixtures/*.*" "tests/fixtures/packs/*"`; ruff
  (`pip install ruff==0.17.5`, `ruff check --output-format=github .`) on Linux only.
- blender job: after the import smoke, `tests/blender/run.py` with the same headless command, gated on
  `hashFiles`.
- Header comment updated.

### Task 4: Dependabot

`.github/dependabot.yml`: `github-actions`, directory `/`, weekly, grouped into one PR.

### Task 5: CONTRIBUTING.md

The ruff command, the guard, the fixture scan, the layout row for `tests/unit/`.

## Verification

Working directory `D:\www\maxdrop`; `$S` = the session scratchpad.

1. `python -I -m unittest discover tests` → `OK` (RAN/SKIPPED lines from the real-tool tests).
2. `$S/ruffvenv/Scripts/ruff.exe check .` → `All checks passed!`
3. `python -I tools/check_fixture.py "tests/fixtures/*.*" "tests/fixtures/packs/*"` → every file `clean`, exit 0.
4. Guard red check: copy `maxdrop/` and `tests/unit/` into `$S/guardcopy/`, add `import bpy` to
   `maxdrop/reader/cfb.py` there, run `python -I -m unittest discover -s tests/unit -t .` from that copy → FAIL
   naming `cfb.py:<line> bpy`; same with `from .. import compat` in `maxdrop/intake/archive.py` → FAIL.
5. Static workflow check (the owner did not tell this session to push, so the workflow change stays unproven by
   a run): YAML parse of `test.yml`, `publish.yml`, `dependabot.yml` (PyYAML in the scratch venv); `bash -n` on
   every `run:` block of `test.yml`; every `steps.<id>.outputs` reference has a step with that id.
6. build-and-test skill: `build.ps1`, register + import smoke on Blender 4.2.23, 4.5.16, 5.2 (the archive.py
   line is in the add-on zip).
