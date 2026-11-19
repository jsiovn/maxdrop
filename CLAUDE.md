# Project Instructions for AI Agents

**MaxDrop**: a public, GPL-3.0-or-later Blender extension (`maxdrop/`) that imports 3ds Max `.max` scenes without
3ds Max. A fork of `nrgsille76/io_scene_max` v1.9.2 (commit `37db107`); the upstream history is kept and the git
remote `upstream` is fetch-only. Not affiliated with Autodesk or Chaos: say so wherever users read about it.

## Build & Test

No package manager. Build = Blender's extension CLI; tests = plain Python for the tools, Blender for the add-on.

```powershell
python -I -m unittest discover tests                  # tools/, the landing page, the license files: no Blender
powershell -ExecutionPolicy Bypass -File build.ps1    # dist\ (git-ignored): zip, index.json, index.html
```

- **Never touch the user's Blender preferences, installed extensions or running session.** Every Blender run is
  headless with an isolated profile: `BLENDER_USER_RESOURCES=<scratch dir> blender --background --factory-startup
  --python-exit-code 1 --python <file>`. Add `--online-mode` when a test uses a repository. Do not use the
  `blender` MCP bridge unless the task says so: that session is shared.
- `tests/smoke_register.py` (register, reload, register, unregister) and `tests/smoke_import.py -- <file.max or
  folder>` (the operator on `.max` files; without arguments `tests/fixtures/*.max`) import the dev package from
  the repo root.
- **Three Blender versions, every time**: the manifest says `blender_version_min = "4.2.0"`, so a change is run
  on 4.2 LTS, 4.5 LTS and 5.2 LTS (CI: 4.2.23, 4.5.16, 5.2.4). Locally: the installed 5.2 and portable zips of
  4.2 / 4.5 from `download.blender.org/release/`, extracted outside the repo and run by full path
  (`build.ps1 -Blender <path>`), never installed.
- **Install and update test without CI:** build, serve `dist\` with `python -m http.server <port> --bind
  127.0.0.1 --directory dist`, add `http://127.0.0.1:<port>/index.json` as a remote repository in the isolated
  profile, `extensions.package_install(repo_index=..., pkg_id="maxdrop")`; then put a bumped build into the
  served folder and upgrade. `update.REPO_URL` is the public index: point it at the local one in that session.
  Timers do not run with `--background`: call `update._upgrade(index)` after `maxdrop.check_updates()`. One
  server per port, and stop it by its own process id (the id of a `python` shim is not the server's).
- **Measure an import** with `tools/baseline.py` (time limit, memory watch, counts). Results of scenes that are
  not ours stay outside the repo.
- Other people and agents use the same machine: never stop a process you did not start.
- Verify the actual environment before claiming a run passed.

## Architecture Overview

- `maxdrop/__init__.py`: thin aggregator. `_NAMES` is the register order (a module comes after the ones it
  imports); each module has `register()` / `unregister()` and its classes in a module-level `_classes` tuple,
  which `tests/smoke_register.py` reads. Re-enabling after an upgrade re-runs `__init__` while old submodules
  stay in `sys.modules`: those of `_NAMES` are reloaded, every other module of the package (imported on demand)
  is dropped by `_purge()`, its name on the package included.
- `maxdrop/ops.py`: operator `import_scene.maxdrop` (options popup through `ImportHelper.invoke_popup`), file
  handler `IO_FH_maxdrop`, the *File › Import* entry. Was upstream's `__init__.py`. An import runs reader ->
  convert (scene description, material and texture-map rules, texture lookup) -> build (objects, collections,
  materials) -> the report. Upstream's engine (`import_max.py`) is deleted: nothing of it is left to call.
- `maxdrop/build/materials.py`: a MaterialIR and its texture graphs as a Principled BSDF node tree, one material
  per 3ds Max material, images reused per file and color space.
- `maxdrop/prefs.py`: add-on preferences: version, Check for Updates, the texture search folders
  (`texture_dirs()`, read by the texture lookup).
- `maxdrop/update.py`: reads the published `index.json`, compares with the manifest version, adds the remote
  repository on first use and runs Blender's own upgrade from a timer. The only code that goes online.
- `maxdrop/compat.py`: the differences between Blender 4.2 and 5.2.
- Planned layout for new code: `maxdrop/reader/` (the `.max` file: CFB, chunks, class directory, scene index,
  nodes, controllers, geometry, parameter blocks, assets, units) and `maxdrop/convert/` (scene description in
  meters, Z up, linear color; material, light and camera rules; the report) **never import `bpy` or
  `mathutils`**, so they run under plain Python; `maxdrop/build/` is the only part that creates Blender data.
  Dispatch on ClassID, never on class-name strings.
- `maxdrop/intake/`: what a scene was downloaded as, turned into a `.max` on disk. `archive.py` lists a scene
  pack (`.zip` through `zipfile`; `.rar` and `.7z` through backends of the same interface) and unpacks the
  chosen `.max` with its maps into a flat folder. Imported on demand, **never imports `bpy` or `mathutils`**.
- `maxdrop/pathnames.py`: name rules reader/, convert/ and intake/ share (`base_name()`, the reserved Windows
  device names): the one module outside those packages they may import (`from .. import pathnames`), bpy-free
  like them and importing nothing of the add-on (`tests/unit/test_reader_no_bpy.py` scans it). A test of a
  module that imports it (directly or through another module) must load that module under a package of its own
  whose path is `maxdrop/` (`maxdrop/__init__.py`, which imports bpy, never runs), as the `maxdrop_convert_test`
  stub of the tests and `maxdrop_tool` of the tools do: a package rooted at `maxdrop/reader/` cannot resolve `..`.
- `site/index.html` + `tools/make_site.py`: the landing page, filled from `dist/index.json` (`{{token}}`
  values). Self-contained: no third-party requests. The install link keeps the form Blender's own generator
  emits (`./maxdrop-<version>.zip?repository=.%2Findex.json&blender_version_min=4.2.0`).
- `.github/workflows/publish.yml`: on every push to `main`: the `test` job (calls `test.yml`), then, gated on
  the manifest version, GitHub Pages and release `v<version>`. A released zip is reused, never rebuilt.
  `test.yml`: plain tests, then build + smoke on Blender 4.2, 4.5 and 5.2.

## Conventions & Patterns

- **Blender 4.2 ↔ 5.2, one zip:**
  - Python 3.11 syntax (4.2 and 4.5 ship 3.11, 5.2 ships 3.13); no numpy call that 2.x removed.
  - Principled BSDF sockets by name with an existence check, never by index: `Thin Wall` and `Diffuse
    Roughness` do not exist in 4.2.
  - `Material.surface_render_method` only; `shadow_method` exists only in 4.2 and `blend_method` is legacy.
  - EEVEE is `BLENDER_EEVEE_NEXT` in 4.x and `BLENDER_EEVEE` in 5.x: tests pick the engine by version.
  - `poll_file_object_drop` comes from `compat.py`. Any other difference goes there too.
- **No commercial assets in git, ever.** The history is public. Bought scenes, their textures, their names and
  anything dumped from them stay outside the repo (the corpus folder is local; `*.max` is git-ignored except
  `tests/fixtures/`). Fixtures are self-authored, tiny, saved under a neutral path, and committed only when a
  scan of their bytes (ASCII and UTF-16LE) finds no user name, machine name or user path. 3ds Max writes the
  Windows user and computer name into every file it saves.
- **Version source of truth:** `version` in `maxdrop/blender_manifest.toml`. Bump it to ship, and add a matching
  `## [x.y.z] - DATE` section to `CHANGELOG.md` (the workflow refuses without it). `docs/SUPPORT.md` says what
  that version imports: keep it true.
- **License:** GPL-3.0-or-later. Files from io_scene_max keep their `GPL-2.0-or-later` SPDX header and their
  copyright lines; a change to one adds a dated "Modified for MaxDrop" line. New files carry
  `SPDX-License-Identifier: GPL-3.0-or-later`. `LICENSE` is the unmodified GPL v3 text and `maxdrop/LICENSE` the
  same file again (`tests/test_license.py` keeps them identical; `tools/check_zip.py` fails a zip without it).
- **Naming:** operators `maxdrop.*` (the importer is `import_scene.maxdrop`), classes `MAXDROP_OT_*`, handler
  `IO_FH_maxdrop`, console prefix `MaxDrop:`. These ids are public: never rename them.
- **Untrusted input:** a `.max` file comes from anywhere. Bounded reads, depth and cycle guards, a size cap on
  compressed streams; texture lookup never follows a UNC path. No network except the update button, no
  telemetry.
- **Archives (scene packs) are untrusted too:** the format comes from the magic bytes, never the extension. A
  name stored in an archive never decides a path: only base names are used, they pass the name policy
  (`refused_reason`) and the output is flat. Only the chosen `.max`, image files and `.ies` are written; nothing
  from a pack is executed or imported as code. Never `extract()` / `extractall()`: stream each entry and count
  the bytes really written against the limits (`Limits`). Unpack into a staging folder beside the destination,
  rename at the end, remove staging on any failure, and remove only folders this code created. A folder without
  the `.maxdrop-pack.json` marker is never written into.
- **Install from the repository, not from disk:** Blender only upgrades an extension inside the repository it
  came from.
- English only for UI strings, comments and docs; comment only non-obvious *why*.

### Git

The repository is public and `main` feeds users: a version bump on `main` ships through Blender's update check.

- **`main` changes only through a pull request** that passes `test.yml`. No direct push, no force-push, no
  history rewrite: a fix is a new commit. (`main` was rewritten once, on 2026-11-15, to split the fork commit;
  the original is kept as branch `backup/c49ee9a` and tag `v0.0.1`.)
- **Branches:** `feat/<bead-id>-<slug>` (one bead, PR into `main`), `epic/<epic-bead-id>` (one epic, its beads
  PR into it, one PR into `main`), `fix/<slug>` or `chore/<slug>` for work without a bead. Never delete
  `backup/*`.
- **Commit messages:** an imperative subject of at most 72 characters (`Add CFB reader`, not `Added ...`), a
  blank line, then a body that says what changed and why, wrapped at 72. One logical change per commit; a bead's
  id goes in the body (`Bead: maxdrop-xyz`). End with the attribution trailer the session asks for.
- **Author:** the repo-local e-mail (`git config user.email` here is a GitHub noreply address). Never change the
  global git config.
- **Push a branch, never tags:** no `--tags`, `--follow-tags`, `--all` or `--mirror`. The 42 upstream tags
  (`v1.5.0` … `v1.9.2`) stay local, or the Publish gate would take one for a MaxDrop release; the release job
  creates `v<version>`. Never delete a release or a tag. Never push to `upstream` (its push URL is disabled).
- **`origin`** is `git@github.com-jsiovn:jsiovn/maxdrop.git`, an SSH host alias; an https remote fails here.
- **Bead state** is a Dolt database (`.beads/dolt/`, never committed); its remote `origin` is this repository
  (Dolt data under `refs/dolt/data`, not a branch). `bd dolt pull` before claiming work in a new checkout,
  `bd dolt push` after closing beads. That ref is public like the rest: a bead never quotes a commercial asset
  name, a user path or anything else the history must not hold.

<!-- BEGIN TEMPLATE BD WORKFLOW -->

### PR review replies

Only append `@claude review` when posting a reply to a **conversation comment authored by `claude[bot]`**. This triggers the bot to re-run its review.

Do **not** include `@claude review` in replies to human reviewer inline thread comments or in any other conversation comments.

## Issue tracking

This repo uses `bd` for issue tracking. Use `bd`, not markdown TODO files or alternate trackers.

Live `.beads` state is local-only and should not be committed. Use one top-level executor session at a time per branch.

Preferred workflow entry points are `plan-beads`, `executor-task`, and `executor-task-worktree`. When the bead is part of an epic that should land in main as a single merge, use `executor-epic-task` (or `executor-epic-task-worktree` for parallel work) — these branch off and PR into `epic/<epic-bead-id>` instead of main. To deliver a whole epic unattended on a single branch, use `executor-epic-sequential <epic-id>` — it runs every ready child bead in turn, each in a fresh worker session that the skill picks itself (inside Herdr: an agent you start in the tab `<epic-id>-implementer` when the run asks, cleared before every bead, via `run-bead-in-herdr`; outside Herdr: a headless run of the CLI you invoked it from, `claude -p`, `opencode run` or `omp -p`, via `run-bead-headless-claude`, `-opencode` or `-omp`), commits them onto one `epic/<epic-bead-id>` branch, skips any bead that blocks, and opens one PR to the default branch at the end; use `executor-epic-sequential-worktree <epic-id>` for the same whole-epic run inside an isolated git worktree that never touches the main checkout (then `cleanup-worktree` to remove it). Use `planner-research` only inside planner sessions and keep `writing-plans` executor-only. Invoke a skill with `/<name>` in Claude Code, `/skill:<name>` in omp, or by naming it in OpenCode. The epic skills need a POSIX shell: OpenCode on Windows runs PowerShell unless `"shell"` in `opencode.json` points at Git Bash.

Each bead must be fresh-session-safe: a new executor session should be able to execute from the bead contract, persisted inputs, and local code inspection without replaying prior chat.

**Technical debt** lives under the standing epic `maxdrop-em3` ("Technical debt"), never as a loose bead and
never inside a milestone epic: deprecations with a date, workarounds to undo, tooling stubs, guards or tests a
milestone left out, docs that drifted, and defects found while working on something else when fixing them would
widen that bead. A debt bead is a `chore` (or `bug`) with `--parent maxdrop-em3 --labels tech-debt` and the usual
contract; its Goal says what leaving it costs and any deadline. An executor that takes such a shortcut or finds
such a gap files the debt bead before closing its own. The epic is never closed, also when empty, and is itself
never run with `executor-epic-sequential`: each debt bead lands on its own (`executor-task`). The one exception:
small debt beads that need no corpus scene, render, 3ds Max session or external tool may be re-parented, on the
owner's word, into a named batch epic (type `epic`, not a milestone) and run with `executor-epic-sequential` as one
PR; they keep the `tech-debt` label, and `maxdrop-em3` stays their home otherwise. List all debt beads with
`bd list --label tech-debt`.

Workflow scaffold files such as `CLAUDE.md`, `BEADS_WORKFLOW.md`, repo-local skills under `.claude/skills/`, and repo-local subagents under `.claude/agents/` (plus their generated omp / OpenCode copies under `.omp/agents/` and `.opencode/agents/` when the repo was scaffolded with `--with-omp` / `--with-opencode`) are committed to this repo's git — so they travel with feature branches and `git worktree` checkouts. Refresh them from the template with `agent-workflow-beads update`. Plan files under `docs/plans/` are committed too: `writing-plans` commits each bead's plan on its branch, so plans travel with the branch and land in the PR. A plan is only visible from other branches once it merges; until then, inline it into the bead's `notes` (Dolt-synced) when another checkout needs it.

Keep repo exploration local. Verify the actual environment before running build, test, run, deploy, or migration commands; do not assume local execution.

Useful commands:

```bash
bd ready --json
bd show <id> --json
bd update <id> --status=in_progress
bd close <id> --reason="Completed"
bd dep add <child-id> <parent-id>
```

<!-- END TEMPLATE BD WORKFLOW -->
