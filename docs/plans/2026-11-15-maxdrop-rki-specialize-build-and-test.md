# Specialize build-and-test for MaxDrop Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generic stage-1 `.claude/skills/build-and-test/SKILL.md` with the MaxDrop stage-2 skill, so
that every executor session verifies a change with the same commands and the same pass lines.

**Architecture:** One Markdown skill file. It lists the environment (placeholders only: machine paths stay out of
the public repository), a table "changed paths -> checks", and numbered building blocks, each with its exact
command and pass line: plain tests, `build.ps1`, register smoke, import smoke, the same on 4.2 and 4.5, the red
check, the localhost install + upgrade flow (scratch script inlined in the skill), `tools/baseline.py`. Shape and
tone follow the sibling repository's specialised skill.

**Tech Stack:** Markdown; PowerShell 7 / Git Bash; Blender 4.2.23, 4.5.16, 5.2 headless; Python standard library.

---

### Task 1: Write the skill

**Files:**

- Modify: `.claude/skills/build-and-test/SKILL.md` (full rewrite)

- [ ] **Step 1:** Read `CLAUDE.md` (Build & Test), `tests/smoke_register.py`, `tests/smoke_import.py`,
  `build.ps1`, `tools/baseline.py`, `maxdrop/update.py`, `.github/workflows/test.yml`, the sibling's skill.
- [ ] **Step 2:** Write the new skill: Core Rule, Environment, Process rules, Changed paths -> checks, blocks
  1 plain tests, 2 build, 3 register smoke, 4 import smoke, 5 three versions, 6 red check, 7 update flow (with
  the scratch `upgrade.py`), 8 baseline, Evidence and report, Fix-and-Retry, Skip Conditions.
- [ ] **Step 3:** Commit `docs(skill): specialize build-and-test for MaxDrop`.

### Task 2: Follow the skill top to bottom on the unchanged tree

- [ ] **Step 1:** Run every block as written (red check: on a scratch package with `maxdrop/ops.py` broken, to
  show a failing run is caught). Fix the skill text wherever a command does not run as written.
- [ ] **Step 2:** If a command in `CLAUDE.md` turns out wrong, fix it there (only then).
- [ ] **Step 3:** Commit any corrections.

## Verification

Working directory: the repo root. `S` = this session's scratchpad. Blender: 5.2 installed
(`C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`), 4.2.23 and 4.5.16 portable (paths in the bead
notes). Local fixture: path in the bead notes.

1. `python -I -m unittest discover tests` -> `OK`
2. `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...\dist\maxdrop-0.0.2.zip, ...index.json and ...index.html`
3. Block 3 (register smoke) on 5.2, 4.2.23, 4.5.16 -> `SMOKE PASSED`, exit 0 each
4. Block 4 (import smoke, local fixture) on all three -> `IMPORT PASSED`, exit 0 each
5. Block 6 (red check) on 5.2 with a broken scratch package -> `SMOKE FAILED`, exit 1
6. Block 7 (update flow) on 5.2 and 4.2.23 -> `UPGRADE PASSED`, exit 0; the server stopped by its own id
7. Block 8 (baseline) on the local fixture, 5.2 -> exit 0, `"outcome": "finished"`, `"traceback": false`

**Success criteria:** every command prints its pass line exactly as the skill states it; any mismatch is fixed in
the skill text and re-run.
