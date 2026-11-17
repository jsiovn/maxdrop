---
name: build-and-test
description: "Use after implementing changes to build the MaxDrop Blender extension and verify it: the plain tests, build.ps1, the register and import smoke tests on Blender 4.2, 4.5 and 5.2 (headless, isolated profile), the red check for a fix, the localhost install + upgrade flow and tools/baseline.py for a measured import."
---

# Build and Test (MaxDrop, stage 2)

**Workflow position:** Executor session, between implementation (step 3) and verification (step 6). See BEADS_WORKFLOW.md.

The repo is a Blender extension (`maxdrop/`, minimum Blender 4.2.0). No package manager: build = Blender's
extension CLI (`build.ps1`), tests = plain Python for the tools, the intake and the site (`tests/test_*.py`),
and scripts run inside Blender for the add-on (`tests/smoke_*.py`). Bead-specific suites are scratch scripts
written per bead from the plan.

## Core Rule

Run the **exact commands** of the current plan's `## Verification` section (`docs/plans/<date>-<bead-id>-*.md`,
or the bead's `notes`). The blocks below are the standard pieces those sections are made of: adapt paths to
this session, never swap in a lighter check. No usable `## Verification` section -> stop and send the plan back
to `writing-plans`.

## Environment

Check before running anything; report a missing piece as a blocker instead of guessing. **User- and machine-specific
paths never go into a committed file** (the repository is public): the portable Blenders, the fixture, the corpus
and the scratchpad come from the bead notes or the session.

| What | Value |
|---|---|
| `ROOT` | this checkout's root (the main checkout or a worktree). Every test imports `maxdrop` from here, never from another checkout or an installed copy. Run every command from `ROOT` |
| `S` | this session's scratchpad dir. Profiles, logs, scratch packages and served folders go here, never into the repo |
| `B52` | Blender 5.2, installed: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` (`build.ps1`'s default) |
| `B42`, `B45` | Blender 4.2 LTS and 4.5 LTS, portable (the versions CI runs are in `.github/workflows/test.yml`). Paths in the bead notes. Missing: download `blender-<x.y.z>-windows-x64.zip` from `https://download.blender.org/release/Blender<x.y>/`, check its SHA-256 against the `.sha256` file there, extract **outside the repo**. Never install them |
| Local fixture | a `.max` saved by 3ds Max, kept **outside** the repo (3ds Max writes the Windows user and computer name into every file it saves). Path in the bead notes. The committed `tests/fixtures/*.max` are sanitized copies (`tools/sanitize_fixture.py`); the import smoke without arguments imports them all |
| Corpus scenes | commercial, private, never in the repo or named in it: "scene A", "scene B". Paths in the bead notes |

PowerShell 7 is the primary shell. Shell state (variables) does not carry between tool calls: repeat the
`$S = ...; $B = ...` line in every block. In Git Bash convert paths with `cygpath -w` (to Windows) or `cygpath -u` (from Windows) and read `$?` (or
`${PIPESTATUS[0]}` when piping) for Blender's exit code.

## Process rules

- **Isolated profile on every Blender run:** `BLENDER_USER_RESOURCES=$S\profile-<tag>` plus `--background
  --factory-startup --python-exit-code 1` (`--online-mode` only when a repository is used). The user's
  preferences, installed extensions and running Blender are never touched. Do not use the `blender` MCP bridge
  unless the bead says so: that session is shared.
- **Own processes only.** Other people and agents use this machine: never stop a process you did not start, and
  stop yours by the process id you kept, not by name.
- **One `http.server` per port.** Check the port is free first (`Get-NetTCPConnection -LocalPort <port>` returns
  nothing). A taken port belongs to someone else, even when it looks like a leftover `python` server: pick
  another port, never stop it (the 3ds Max MCP bridge listens on 8765 when it runs). After a server stops, `TimeWait` entries stay
  on the port for a while: only a `Listen` entry means it is still serving.
- No wildcard `Remove-Item` (`Remove-Item <dir>\*` is refused by the harness): `Get-ChildItem <dir> -File |
  Remove-Item`, or `Remove-Item -Recurse -Force <dir>` for a whole scratch folder.
- **`python` is a pyenv shim** (a `.bat`): `Start-Process python` gives the shim's id, not the server's. Resolve the
  interpreter first, `$py = python -c "import sys; print(sys.executable)"`, and start `$py`. A multi-line
  `python -c` breaks in the shim: write a script file or use a Bash heredoc (`python -I - <<'EOF'`).
- **Blender's stderr under Windows PowerShell 5.** Blender 4.2 writes to stderr; Windows PowerShell 5 with
  `$ErrorActionPreference = "Stop"` turns a redirected native stderr line into a terminating error. Redirect in
  PowerShell 7 (as below) or through `cmd /c "<command> > <log> 2>&1"`, never `2>&1` inside a PS 5 script with
  `Stop`. `build.ps1` does not redirect, so it is safe as written.
- Logs as UTF-8 (`Out-File -Encoding utf8`). The importer prints object and texture names: logs of a corpus
  scene stay in `S` and are never quoted in a commit, a bead or a PR.

## Changed paths -> checks

The base is where the branch left its parent: `origin/main`, or `origin/epic/<epic-id>` for a bead of an epic
branch (local `main` can lag: fetch first). Block 1 is cheap: run it for every change.

```powershell
git fetch origin
$base = git merge-base HEAD origin/main    # epic bead: origin/epic/<epic-id>
git diff --name-only "$base...HEAD"; git status --short
```

| Changed | Run |
|---|---|
| Docs only (`*.md`, `docs/`, `.claude/`, `.beads` metadata) | 1 (the site and license tests read some of these files) |
| `maxdrop/*.py` (operator, prefs, compat) | 1, 2, 5 (= 3 and 4 on all three versions), 6 for a fix |
| `maxdrop/__init__.py` (`_NAMES`, `_purge`, reload), `maxdrop/update.py` | the row above, plus 7 on 5.2 and 4.2 |
| `maxdrop/intake/` | 1 (its tests load it by path), 2, 5, 6 for a fix |
| `maxdrop/reader/`, `maxdrop/convert/`, `maxdrop/build/` | the `maxdrop/*.py` row, plus 8 when the plan measures (fixture, then the corpus scenes it names) |
| `maxdrop/blender_manifest.toml` `version` | 1, 2, 3 on all three versions, and the CHANGELOG check below; `docs/SUPPORT.md` says what that version imports |
| `maxdrop/blender_manifest.toml` other fields (permissions, `blender_version_min`, ...) | 1, 2, 5, and 7 on 5.2 and 4.2 |
| `tests/smoke_*.py` | that script green on all three versions + 6 (a red run on a broken scratch package) |
| `tests/fixtures/*` (a new or changed file) | the fixture scan below **before `git add`**, then 4 on all three versions with that file (and 1 for `packs/`) |
| `tests/test_*.py`, `tools/check_zip.py`, `tools/make_site.py`, `site/` | 1, 2 |
| `tools/baseline*.py` | 8 on the fixture |
| `build.ps1` | 2, also with `-Blender $B42` |
| `.github/workflows/*.yml` | 1, 2; the workflow itself is the PR's `Test` run (Publish runs only on `main`) |

Fixture scan (CLAUDE.md: a fixture is committed only when its bytes, ASCII and UTF-16LE, hold no user name,
machine name or user path; 3ds Max writes the first two into every file it saves, `tools/sanitize_fixture.py`
blanks them):

```powershell
python -I tools/check_fixture.py "tests/fixtures/*.max"
```

Pass: exit 0, one `clean` line per file. Otherwise the file is not committed; the tool prints the kind of string
(`user name`, `computer name`, `user folder`, `drive path`, `identity property not blank`), never the string.

CHANGELOG check for a version bump (the Publish workflow refuses a version without its section, but only after
the merge):

```powershell
$v = (Select-String -Path maxdrop\blender_manifest.toml -Pattern '^version\s*=\s*"(.+)"').Matches[0].Groups[1].Value
Select-String -SimpleMatch "## [$v]" CHANGELOG.md
```

Pass: one line `## [<version>] - <date>`.

## 1. Plain tests (no Blender)

```powershell
python -I -m unittest discover tests
```

Pass: exit 0, last line `OK` or `OK (skipped=N)`. A skip is a real-tool case whose tool this machine lacks
(the test prints why); a skip that is new for the change is reported.

## 2. Build

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Pass: exit 0 and `Built ...\dist\maxdrop-<manifest version>.zip, ...\dist\index.json and ...\dist\index.html`.
The script empties `dist\` and `maxdrop\**\__pycache__`, builds, runs `extension validate`, `tools/check_zip.py`
(the zip carries `maxdrop/LICENSE`), `server-generate` and `tools/make_site.py`. Another Blender:
`-Blender <path>`.

## 3. Register smoke

```powershell
$S = "<scratch>"; $B = "<blender.exe>"; $tag = "52"
$env:BLENDER_USER_RESOURCES = "$S\profile-$tag"
& $B --background --factory-startup --python-exit-code 1 --python tests\smoke_register.py *>&1 | Out-File -Encoding utf8 "$S\register-$tag.log"
"exit $LASTEXITCODE"; Select-String -Pattern "^SMOKE ", "^FAIL " "$S\register-$tag.log"
```

Pass: `exit 0`, `SMOKE PASSED`, no `FAIL` line. It imports the dev package from `ROOT` (or `-- <root>` after the
script), checks it came from there, registers, checks every class of each module's `_classes`, the operators,
the file handler, the File > Import entry, that the build package and the intake are not loaded yet and no
io_scene_max engine is left, reloads like Reload Scripts, registers again and unregisters. A new module must keep
its classes in a module-level `_classes` tuple and appear in `_NAMES` after the modules it imports.

## 4. Import smoke

```powershell
$S = "<scratch>"; $B = "<blender.exe>"; $tag = "52"; $fixture = "<local fixture .max>"
$env:BLENDER_USER_RESOURCES = "$S\profile-$tag"
& $B --background --factory-startup --python-exit-code 1 --python tests\smoke_import.py -- $fixture *>&1 | Out-File -Encoding utf8 "$S\import-$tag.log"
"exit $LASTEXITCODE"; Select-String -Pattern "^IMPORT ", "^FAIL ", "^COUNTS " "$S\import-$tag.log"
```

Pass: `exit 0`, `IMPORT PASSED`, no `FAIL` line. It imports the file through `import_scene.maxdrop` into an
emptied scene, then as a `.zip` pack, a two-scene pack and the file-browser selections; `COUNTS` lines compare
versions (they must be equal on all three). Arguments may be files or folders; a `.zip`, `.rar` or `.7z` argument
is imported as it is. `IMPORT SKIPPED` (no file found) is **not** a pass for a change that touches the import.

## 5. Three versions

Blocks 3 and 4 run on `B52`, `B42` and `B45` (tags `52`, `42`, `45`), each with its own profile. The manifest
claims 4.2.0, so a pass on 5.2 alone is not a pass. Version differences go into `maxdrop/compat.py`.

## 6. Red check

For a bug fix, prove the test fails without it; for a new or changed smoke script, prove it fails on broken
code. Never `git stash` or revert in the real tree: build a scratch copy of the base and run the **new** tests on
it (the smoke scripts and the plain tests find the package next to their own `tests\` folder).

```bash
# Git Bash: byte-exact export of the whole base tree (the plain tests also read LICENSE, site/, tools/), then
# the new tests over it, with any fixture or helper under tests/ they need.
S=$(cygpath -u '<scratch>'); base=$(git merge-base HEAD origin/main)   # epic bead: origin/epic/<epic-id>
rm -rf "$S/red" && mkdir -p "$S/red"
git archive "$base" | tar -x -C "$S/red"
cp tests/<the new or changed test files> "$S/red/tests/"
```

Then run the test from `$S\red` in place of `ROOT`: `python -I -m unittest discover $S\red\tests`, or block 3/4
with `--python $S\red\tests\smoke_<x>.py` (block 3 also takes `-- $S\red`). Pass: the run **fails** (`FAILED`,
`SMOKE FAILED`, `IMPORT FAILED`, exit 1) on exactly the case the fix is about; record its `FAIL` lines. A test
that passes on the unfixed code proves nothing. For a smoke script without a fix, break the scratch package
on purpose (e.g. drop an entry from `filter_glob` in `$S\red\maxdrop\ops.py`) and show that check fails.

## 7. Install and upgrade from a local repository

Proves the zip installs from a repository, enables, and that Check for Updates upgrades it in place (the reload
path real users take). On 5.2 and 4.2 (add 4.5 when the plan says so).

1. Block 2 has built `dist\` (v1 = the manifest version). Serve a copy of its `index.json` and zip (files only:
   the script swaps them for v2's):

   ```powershell
   $S = "<scratch>"
   Remove-Item -Recurse -Force "$S\serve", "$S\v2src", "$S\v2" -ErrorAction SilentlyContinue
   New-Item -ItemType Directory "$S\serve", "$S\v2" | Out-Null
   Copy-Item dist\index.json, dist\*.zip "$S\serve"
   ```

2. v2 = the same package with a higher version (patch + 100), built into its own folder (`server-generate` lists
   every zip it finds):

   ```powershell
   $S = "<scratch>"; $B = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
   New-Item -ItemType Directory "$S\v2src" | Out-Null
   Copy-Item -Recurse maxdrop "$S\v2src\maxdrop"
   Get-ChildItem "$S\v2src\maxdrop" -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
   $m = "$S\v2src\maxdrop\blender_manifest.toml"
   $v1 = (Select-String -Path $m -Pattern '^version\s*=\s*"(.+)"').Matches[0].Groups[1].Value
   $p = $v1.Split("."); $v2 = "$($p[0]).$($p[1]).$([int]$p[2] + 100)"
   (Get-Content -Raw $m) -replace '(?m)^version\s*=\s*".+"', "version = `"$v2`"" | Set-Content -NoNewline $m
   & $B --factory-startup --command extension build --source-dir "$S\v2src\maxdrop" --output-dir "$S\v2"
   & $B --factory-startup --command extension server-generate --repo-dir "$S\v2"
   "v1 $v1 -> v2 $v2"; Get-ChildItem "$S\v2" -Name
   ```

   Pass: `maxdrop-<v2>.zip` and `index.json` in `$S\v2`.

3. Start the server (the real interpreter, not the shim) and keep its id. 8791 is an example: any free port, the
   same one in step 5:

   ```powershell
   $S = "<scratch>"; $port = 8791
   if (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue) { throw "port $port is taken" }
   $py = python -c "import sys; print(sys.executable)"
   $srv = Start-Process $py -ArgumentList "-m", "http.server", $port, "--bind", "127.0.0.1", "--directory", "`"$S\serve`"" -PassThru -WindowStyle Hidden
   $srv.Id | Out-File "$S\server.pid"
   Start-Sleep 1; (Invoke-WebRequest "http://127.0.0.1:$port/index.json" -UseBasicParsing).StatusCode
   "pid $($srv.Id), listener $((Get-NetTCPConnection -LocalPort $port -State Listen).OwningProcess)"
   ```

   Pass: `200`, and the listener's id is the kept id.

4. Write `$S\upgrade.py`:

   ```python
   """Install maxdrop from a local repository, then upgrade it through Check for Updates (MaxDrop build-and-test)."""
   import os, shutil, sys, tomllib, traceback
   import bpy

   PORT, SERVE, V2, OLD, NEW = sys.argv[sys.argv.index("--") + 1:][:5]
   URL = "http://127.0.0.1:%s/index.json" % PORT
   failures = []

   def check(name, cond, detail=""):
       print(("PASS " if cond else "FAIL ") + name + ("  [%s]" % (detail,) if detail != "" else ""))
       if not cond:
           failures.append(name)

   def version_of(module):
       with open(os.path.join(os.path.dirname(sys.modules[module].__file__), "blender_manifest.toml"), "rb") as f:
           return tomllib.load(f)["version"]

   def run():
       print("Blender " + bpy.app.version_string)
       bpy.ops.preferences.extension_repo_add(type='REMOTE', name="maxdrop-local", remote_url=URL,
                                              use_sync_on_startup=False)
       repos = bpy.context.preferences.extensions.repos
       index = next(i for i, r in enumerate(repos) if r.use_remote_url and r.remote_url == URL)
       module = "bl_ext.%s.maxdrop" % repos[index].module
       bpy.ops.extensions.repo_sync(repo_index=index)
       bpy.ops.extensions.package_install(repo_index=index, pkg_id="maxdrop", enable_on_install=True)
       check("installed and enabled as " + module, module in bpy.context.preferences.addons)
       check("installed version is " + OLD, version_of(module) == OLD, version_of(module))
       check("the importer is registered", hasattr(bpy.types, "IMPORT_SCENE_OT_maxdrop"))
       for name in os.listdir(SERVE):
           os.remove(os.path.join(SERVE, name))
       for name in os.listdir(V2):
           shutil.copy(os.path.join(V2, name), SERVE)
       update = sys.modules[module + ".update"]
       update.REPO_URL = URL  # the public index otherwise
       result = bpy.ops.maxdrop.check_updates()
       check("Check for Updates finds " + NEW, result == {'FINISHED'} and update._status == "Updating to " + NEW,
             "%s %r" % (result, update._status))
       update._upgrade(index)  # timers do not run with --background
       check("still enabled after the upgrade", module in bpy.context.preferences.addons)
       check("installed version is " + NEW, version_of(module) == NEW, version_of(module))
       # The files on disk are new either way; a stale module still answers the old version (functools.cache).
       loaded = sys.modules[module + ".update"].installed_version()
       check("the loaded code is " + NEW, loaded == NEW, loaded)
       check("the importer is registered after the upgrade", hasattr(bpy.types, "IMPORT_SCENE_OT_maxdrop"))

   try:
       run()
   except Exception:
       traceback.print_exc()
       failures.append("exception")
   print("UPGRADE FAILED: %s" % ", ".join(failures) if failures else "UPGRADE PASSED")
   sys.stdout.flush()
   sys.exit(1 if failures else 0)
   ```

5. Per Blender version, a fresh profile and the v1 files served again:

   ```powershell
   $S = "<scratch>"; $B = "<blender.exe>"; $tag = "52"; $port = 8791; $v1 = "<v1>"; $v2 = "<v2>"
   Remove-Item -Recurse -Force "$S\profile-upgrade-$tag" -ErrorAction SilentlyContinue
   Get-ChildItem "$S\serve" -File | Remove-Item; Copy-Item dist\index.json, dist\*.zip "$S\serve"
   $env:BLENDER_USER_RESOURCES = "$S\profile-upgrade-$tag"
   & $B --background --factory-startup --online-mode --python-exit-code 1 --python "$S\upgrade.py" -- $port "$S\serve" "$S\v2" $v1 $v2 *>&1 | Out-File -Encoding utf8 "$S\upgrade-$tag.log"
   "exit $LASTEXITCODE"; Select-String -Pattern "^UPGRADE ", "^FAIL ", "Traceback" "$S\upgrade-$tag.log"
   ```

   Pass: `exit 0`, `UPGRADE PASSED`, no `FAIL` line, no traceback.

6. Stop **your** server: `Stop-Process -Id (Get-Content "$S\server.pid")`, then
   `Get-NetTCPConnection -LocalPort <port> -State Listen -ErrorAction SilentlyContinue` returns nothing.

To test the live repository instead (after a release), skip the server and use the public `index.json` with
the real `REPO_URL`: Check for Updates must say `Up to date`.

## 8. Measured import (`tools/baseline.py`)

```powershell
$S = "<scratch>"; $B = "<blender.exe>"; $fixture = "<local fixture .max>"
python tools\baseline.py --blender $B --profile "$S\profile-baseline" --label fixture --out "$S\baseline\fixture.json" $fixture
"exit $LASTEXITCODE"
```

Pass: exit 0, and the printed JSON has `"outcome": "finished"`, `"traceback": false` and non-null `counts`. It
stops Blender (by its own process id) at `--limit-minutes` (30), `--max-memory-gb` (40) or below
`--min-free-gb` (6) free. For a corpus scene: `--label "scene A"` (or `"scene B"`), the result and its `.log`
stay in `S`, and only counts and measurements are compared with `docs/BASELINE.md` (wall time, peak memory,
objects, meshes, materials, placeholders). `counts.nodes` is the number of nodes MaxDrop's reader walks in the
file (`tools/baseline_import.py`; the importer builds one object per node), `null` only when the reader cannot
index the file. `import_report` holds the counts of the operator's `Imported ...` line (objects, meshes,
materials, placeholders, modifiers not applied, textures missing, approximated, issues), `null` when the log
has no such line.

## Evidence and report

For each block: the command, the Blender version, the exit code and the pass line (`OK`, `Built ...`,
`SMOKE PASSED`, `IMPORT PASSED`, `UPGRADE PASSED`, `"outcome": "finished"`) or the exact `FAIL` lines; for a red
check, the failing lines on the base. Report the changed areas, the blocks run, pass/fail per block and version,
skipped blocks with the reason, blockers. Never "mostly passed". No corpus scene name, texture name or user path
in the report, the bead or the PR.

## Fix-and-Retry Loop

```
implement -> build-and-test -> FAIL -> fix code (or the plan) -> build-and-test -> PASS -> verification
```

Only proceed to `verification-before-completion` when every required block passes.

## Skip Conditions

Do NOT run this skill when:

- the user explicitly says no testing is needed
- in a planner session
- only planner artifacts changed and the current plan does not require validation
