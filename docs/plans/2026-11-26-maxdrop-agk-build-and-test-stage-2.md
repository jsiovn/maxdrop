# Build-and-test 1.5.0 stage-2 shape Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `.claude/skills/build-and-test/SKILL.md` carries the agent-workflow-beads 1.5.0 change-scope rule and the
stage-2 layout (Launch, Doctor, Drive, Evidence, Cleanup, Feature map), and has been run end to end once.

**Architecture:** edit the existing skill in place. The numbered blocks 1-8 keep their numbers (plans under
`docs/plans/` cite them) and move under the new headings: Launch = 2 (build) and 7 (local repository: serve v1,
build v2, start the server); Drive = 1, 3, 4, 5, 6, the upgrade run of 7, 8; Feature map = the old "Changed paths
-> checks" table with the fixture scan and the CHANGELOG check. Doctor is new: a runnable block split out of
Environment. Cleanup is new and runs after Evidence (the logs are the evidence).

**Tech Stack:** Markdown skill file; PowerShell 7 and Git Bash snippets; Blender 4.2 / 4.5 / 5.2 headless.

**Precondition:** the bead wants agent-workflow-beads 1.5.0 applied first. On `main` it is not: the refresh is
open PR #36 (`chore/refresh-workflow-scaffold`, commit `05d42bb`), which does not touch this skill. The rule text is
taken word for word from `git show 05d42bb:.claude/skills/verification-before-completion/SKILL.md` (Change Scope
Gate; identical to the 1.5.0 template's stage-1 `build-and-test` step 2). This PR should merge after #36.

---

### Task 1: Change scope

**Files:** Modify `.claude/skills/build-and-test/SKILL.md`

- [x] Add a `## Change scope` section: the `**Change scope:**` paragraph verbatim (the literal marker is what
      `agent-workflow-beads update` looks for), the branch bullet, the `--is-ancestor` "between" bullet (a stale
      `Base-SHA:` is ignored), "use the caller's file list when one is given", "an empty change list means the base
      is wrong: recompute it, never skip validation because of it".
- [x] Replace the old snippet (`"$base...HEAD"`, `git status --short`) with `git diff --name-only "$base..HEAD"`
      and `git status --porcelain`.

### Task 2: Layout

- [x] Environment stays (the table of placeholders, the PowerShell note) and Process rules stay.
- [x] `## Doctor`: one PowerShell block, one line per prerequisite (`ok <what>` or `MISSING <what>: <fix hint>`),
      `DOCTOR FAILED: <n> missing` on any miss: PowerShell 7, Python 3 on PATH, each Blender `$B52`, `$B42`,
      `$B45` answering `--version` with its series, the local fixture, the corpus scenes only when the plan
      measures one, `bd where` (also when `bd` is missing). The base ref check (`origin/main` or the epic branch)
      fails fast in the Change scope snippet itself. No machine path in the file: all from session variables.
- [x] `## Launch`: block 2 (build) and block 7 steps 1-3 (serve v1, build v2, start the server).
- [x] `## Drive`: blocks 1, 3, 4, 5, 6, 7 (steps 4-5: the upgrade run), 8.
- [x] `## Evidence`: the old "Evidence and report" (per-block capture, corpus privacy rule kept).
- [x] `## Cleanup`: stop the kept server id and check no `Listen` entry is left; remove the named scratch
      folders and logs one by one (`red`, `serve`, `v2src`, `v2`, `profile-*`, `baseline`, `*.log`, `upgrade.py`,
      `server.pid`) after the report; corpus logs never leave `S`.
- [x] `## Feature map`: the old table (renamed), plus the row "change list empty -> the base is wrong"; the
      docs-only row keeps block 1; fixture scan and CHANGELOG check stay under it.
- [x] Fix-and-Retry: any edit after the last passing run voids that pass, a review fix included.

### Task 3: Cleanup of this change

- [x] `grep -n "Changed paths\|Evidence and report" .claude/skills/build-and-test/SKILL.md` -> nothing; no other
      file cites the old headings (checked: `tests/`, `tools/` hold none).
- [x] Commit with the plan's boxes ticked.

## Verification

Run the new skill top to bottom once, on this branch, as written (it is the thing under test). `S` = this
session's scratchpad, `B52` installed 5.2, `B42` / `B45` the portable 4.2.23 / 4.5.16 (bead notes), fixture =
the local fixture (bead notes) and `tests/fixtures/*.max`.

1. Rule text: extract the `**Change scope:**` paragraph from the skill and from
   `git show 05d42bb:.claude/skills/verification-before-completion/SKILL.md`; `diff` -> no output.
   `grep -c '\*\*Change scope:\*\*' .claude/skills/build-and-test/SKILL.md` -> `1`.
2. Change scope commands -> non-empty list (the skill file and this plan).
3. Doctor -> every line `ok`, exit 0.
4. Drive 1: `python -I -m unittest discover tests` -> `OK (skipped=N)`; `python -I tools/lint.py` -> exit 0,
   `All checks passed!`.
5. Launch 2: `build.ps1` -> `Built ...maxdrop-<version>.zip ...`.
6. Drive 3 + 4 on 5.2, 4.2, 4.5 (5): `SMOKE PASSED`, `IMPORT PASSED`, equal `COUNTS` across versions.
7. Drive 6: red check on a deliberately broken scratch package (no fix to turn red) -> `SMOKE FAILED` on the
   broken case.
8. Launch 7 + Drive 7 on 5.2 and 4.2: `UPGRADE PASSED`.
9. Drive 8 on the local fixture: `"outcome": "finished"`, `"traceback": false`.
10. Cleanup: no `Listen` entry on the port; the scratch folders listed are gone.

Docs-only change by the feature map, so blocks 3-8 are run here only because the Done criterion asks for the
whole skill once. If review changes a command, re-run that section and block 1.
