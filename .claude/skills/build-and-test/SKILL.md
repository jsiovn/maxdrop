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

A run goes: **Change scope** (what changed) -> **Feature map** (which blocks that selects) -> **Doctor** (are
their prerequisites here) -> **Launch** (build, serve) -> **Drive** (the checks) -> **Evidence** (the report) ->
**Cleanup**. The blocks keep the numbers 1 to 8 that plans cite, under the section they belong to.

## Environment

Report a missing piece as a blocker instead of guessing (Doctor checks them). **User- and machine-specific
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

## Change scope

**Change scope:** every file in `git diff --name-only <BASE>..HEAD` plus every path in `git status --porcelain`; never `git diff HEAD` alone, which is empty once the work is committed. `<BASE>` = `git merge-base HEAD origin/<branch this work merges into>` (the PR base: the default branch or `epic/<id>`), unless the task prompt, or the `Base-SHA:` note of the bead this session is executing, names a commit between that merge-base and HEAD: then that commit.

- Use the caller's file list when one is given (`writing-plans`, `requesting-code-review` and
  `address-pr-comments` pass one). Otherwise compute it (below).
- The branch is the one the executor names, else the open PR's base (`gh pr view --json baseRefName`), else the default branch. With no `origin/<branch>` ref, use the local branch.
- A named commit is "between" only when `git merge-base --is-ancestor <merge-base> <sha>` and `git merge-base --is-ancestor <sha> HEAD` both succeed. Anything else is stale (the branch was rebased since) and is ignored.
- An empty change list means the base is wrong: recompute it. Never skip validation because the list is empty.

```powershell
git fetch origin
$ref = "origin/main"                     # epic bead: origin/epic/<epic-id>
if (-not (git rev-parse --verify --quiet $ref)) { throw "no $ref: git fetch origin, or name the PR base" }
$mb = git merge-base HEAD $ref
$sha = ""                                # the Base-SHA: of the task prompt or of this bead's notes, if any
$base = $mb
if ($sha) {
    git merge-base --is-ancestor $mb $sha; $after = $LASTEXITCODE -eq 0
    git merge-base --is-ancestor $sha HEAD; $before = $LASTEXITCODE -eq 0
    if ($after -and $before) { $base = $sha } else { "stale Base-SHA $sha ignored" }
}
"base $base"; git diff --name-only "$base..HEAD"; git status --porcelain
```

Pass: a base line and at least one path. The Feature map turns the paths into blocks.

## Feature map

Block 1 is cheap: run it for every change.

| Changed | Run |
|---|---|
| Nothing (empty change list) | the base is wrong: recompute it (Change scope). Never "nothing to run" |
| Docs only (`*.md`, `docs/`, `.claude/`, `.beads` metadata) | 1 (the site and license tests read some of these files) |
| `maxdrop/*.py` (operator, prefs, compat) | 1, 2, 5 (= 3 and 4 on all three versions), 6 for a fix |
| `maxdrop/__init__.py` (`_NAMES`, `_purge`, reload), `maxdrop/update.py` | the row above, plus 7 on 5.2 and 4.2 |
| `maxdrop/intake/` | 1 (its tests load it without Blender), 2, 5, 6 for a fix |
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
python -I tools/check_fixture.py "tests/fixtures/**/*"
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

## Doctor

Before the first Blender block, check what the selected blocks need. Fill in the session's values; leave
`$corpus` empty unless the plan measures a corpus scene:

```powershell
$S = "<scratch>"; $B52 = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"; $B42 = "<4.2 blender.exe>"; $B45 = "<4.5 blender.exe>"
$fixture = "<local fixture .max>"; $corpus = @()    # e.g. @("<scene A .max>"), only when the plan measures it
$script:miss = 0
function Test-Need($what, $ok, $hint) { if ($ok) { "ok $what" } else { "MISSING ${what}: $hint"; $script:miss++ } }
Test-Need "PowerShell 7" ($PSVersionTable.PSVersion.Major -ge 7) "run the blocks in pwsh, not Windows PowerShell 5 (see Process rules)"
Test-Need "Python 3" ("$(python -I --version 2>&1)" -match '^Python 3\.(9|\d\d)\b') "Python 3.9 or later on PATH (CI runs 3.11 and 3.13)"
Test-Need "scratch folder outside the repo" ((Test-Path $S) -and -not "$((Resolve-Path $S).Path)\".StartsWith("$((Resolve-Path .).Path)\", [StringComparison]::OrdinalIgnoreCase)) "use the session's scratchpad"
$env:BLENDER_USER_RESOURCES = "$S\profile-doctor"
foreach ($b in @(@("5.2", $B52), @("4.2", $B42), @("4.5", $B45))) {
    $ver = if (Test-Path $b[1]) { (& $b[1] --factory-startup --version 2>$null | Select-String '^Blender ').Line } else { "" }
    Test-Need "Blender $($b[0]) ($ver)" ($ver -like "Blender $($b[0]).*") "see B42, B45 in Environment; path in the bead notes"
}
Test-Need "local fixture" (Test-Path $fixture) "path in the bead notes; without it block 4 imports only tests/fixtures (say so in the report)"
for ($i = 0; $i -lt $corpus.Count; $i++) { Test-Need "corpus scene $($i + 1)" (Test-Path $corpus[$i]) "path in the bead notes; block 8 on it is skipped (report it)" }
$bdOk = $false; if (Get-Command bd -ErrorAction SilentlyContinue) { bd where *> $null; $bdOk = $LASTEXITCODE -eq 0 }
Test-Need "bd where" $bdOk "bd on PATH, then bd bootstrap --yes"
if ($script:miss) { "DOCTOR FAILED: $($script:miss) missing" } else { "DOCTOR OK" }
```

Pass: `DOCTOR OK`, every line `ok`. A `MISSING` line blocks the blocks that need it (Blender 4.2 / 4.5: block 5;
the fixture: blocks 4 and 8 on it; PowerShell 7: every PowerShell block): fix it with the hint or report it as a
blocker, never as a pass. The corpus lines print a number, never the path. Ruff is checked by block 1 itself
(`tools/lint.py` exit 3).

## Launch

### 2. Build

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Pass: exit 0 and `Built ...\dist\maxdrop-<manifest version>.zip, ...\dist\index.json, ...\dist\index.html and
...\dist\vi.html`.
The script empties `dist\` and `maxdrop\**\__pycache__`, builds, runs `extension validate`, `tools/check_zip.py`
(the zip carries `maxdrop/LICENSE`), `server-generate` and `tools/make_site.py`. Another Blender:
`-Blender <path>`.

### 7. Local repository (steps 1-3; the run is Drive block 7)

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
   same one in Drive block 7 (Cleanup reads it from `server.port`):

   ```powershell
   $S = "<scratch>"; $port = 8791
   if (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue) { throw "port $port is taken" }
   $py = python -c "import sys; print(sys.executable)"
   $srv = Start-Process $py -ArgumentList "-m", "http.server", $port, "--bind", "127.0.0.1", "--directory", "`"$S\serve`"" -PassThru -WindowStyle Hidden
   $srv.Id | Out-File "$S\server.pid"; $port | Out-File "$S\server.port"
   Start-Sleep 1; (Invoke-WebRequest "http://127.0.0.1:$port/index.json" -UseBasicParsing).StatusCode
   "pid $($srv.Id), listener $((Get-NetTCPConnection -LocalPort $port -State Listen).OwningProcess)"
   ```

   Pass: `200`, and the listener's id is the kept id.

## Drive

### 1. Plain tests (no Blender)

```powershell
python -I -m unittest discover tests
python -I tools/lint.py
```

Pass: exit 0, last line `OK` or `OK (skipped=N)`. A skip is a real-tool case whose tool this machine lacks
(the test prints why); a skip that is new for the change is reported. Then ruff, the check CI's Ruff step runs:
exit 0 and `All checks passed!`. The version is `required-version` in `pyproject.toml`; `tools/lint.py` uses
`ruff` on PATH at that version, else `uvx --offline ruff@<version>`, and adds an unreachable-code check (a
statement after `return`, `raise`, `continue` or `break`, or after a `with` (return, continue, break),
`if`/`else`, `try` or `match` that always exits; ruff has no rule for it). Exit 3 = no ruff of that version
here: fetch it once (`uvx ruff@<version> --version`, network) and rerun, or report the lint as skipped.
Exit 1 = findings: fix them, never commit past them. Exit 2 = ruff's own error (a bad argument, a config error).

### 3. Register smoke

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

### 4. Import smoke

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

### 5. Three versions

Blocks 3 and 4 run on `B52`, `B42` and `B45` (tags `52`, `42`, `45`), each with its own profile. The manifest
claims 4.2.0, so a pass on 5.2 alone is not a pass. Version differences go into `maxdrop/compat.py`.

### 6. Red check

For a bug fix, prove the test fails without it; for a new or changed smoke script, prove it fails on broken
code. Never `git stash` or revert in the real tree: build a scratch copy of the base and run the **new** tests on
it (the smoke scripts and the plain tests find the package next to their own `tests\` folder).

```bash
# Git Bash: byte-exact export of the whole base tree (the plain tests also read LICENSE, site/, tools/), then
# the new tests over it, with any fixture or helper under tests/ they need. base = the Change scope base.
S=$(cygpath -u '<scratch>'); base='<the Change scope base>'   # its $base: the merge-base or a valid Base-SHA
rm -rf "$S/red" && mkdir -p "$S/red"
git archive "$base" | tar -x -C "$S/red"
cp tests/<the new or changed test files> "$S/red/tests/"
```

Then run the test from `$S\red` in place of `ROOT`: `python -I -m unittest discover $S\red\tests`, or block 3/4
with `--python $S\red\tests\smoke_<x>.py` (block 3 also takes `-- $S\red`). Pass: the run **fails** (`FAILED`,
`SMOKE FAILED`, `IMPORT FAILED`, exit 1) on exactly the case the fix is about; record its `FAIL` lines. A test
that passes on the unfixed code proves nothing. For a smoke script without a fix, break the scratch package
on purpose (e.g. drop an entry from `filter_glob` in `$S\red\maxdrop\ops.py`) and show that check fails.

### 7. Install and upgrade run (steps 4-5; Launch block 7 first)

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

To test the live repository instead (after a release), skip the server and use the public `index.json` with
the real `REPO_URL`: Check for Updates must say `Up to date`.

### 8. Measured import (`tools/baseline.py`)

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
curves, materials, placeholders, modifiers not applied, textures missing, approximated, material problems,
issues), `null` when the log has no such line.

## Evidence

For each section, what the report and the closeout note's `Verified:` line carry:

| Section | Capture |
|---|---|
| Change scope | the base (and a stale `Base-SHA:` ignored, if any), the paths it listed |
| Feature map | the blocks those paths selected, and any block the plan adds or a skip with its reason |
| Doctor | `DOCTOR OK`, or each `MISSING` line and what it blocked |
| Launch | `Built ...maxdrop-<version>.zip ...`; for 7, `v1 <x> -> v2 <y>`, the `200` and the kept server id |
| Drive | per block and Blender version: the command, the exit code and the pass line (`OK`, `All checks passed!`, `SMOKE PASSED`, `IMPORT PASSED` with its `COUNTS`, `UPGRADE PASSED`, `"outcome": "finished"`) or the exact `FAIL` lines; for a red check, the failing lines on the base |
| Cleanup | the server stopped (no `Listen` entry) and the scratch folders removed |

Report pass/fail per block and version, skipped blocks with the reason, blockers. Never "mostly passed". No
corpus scene name, texture name or user path in the report, the bead or the PR: corpus logs stay in `S`, only
counts and measurements leave it.

## Cleanup

After the report (the logs are the evidence), stop what Launch started and remove this skill's scratch state.
`dist\` stays (git-ignored; the next build empties it).

```powershell
$S = "<scratch>"
if (Test-Path "$S\server.pid") {
    $id = [int](Get-Content "$S\server.pid"); $port = [int](Get-Content "$S\server.port")
    # Only while that id still serves the port: a stopped server's id may belong to someone else's process now.
    if ((Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).OwningProcess -contains $id) {
        Stop-Process -Id $id; Wait-Process -Id $id -Timeout 10 -ErrorAction SilentlyContinue
    }
}
foreach ($d in "red", "serve", "v2src", "v2", "baseline") { Remove-Item -Recurse -Force "$S\$d" -ErrorAction SilentlyContinue }
Get-ChildItem $S -Directory -Filter "profile-*" | Remove-Item -Recurse -Force
Get-ChildItem $S -File | Where-Object { $_.Name -match '^(register|import|upgrade)-.+\.log$' -or $_.Name -in "upgrade.py" } | Remove-Item
if ($port) { "listen: $(@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).Count)" }
Remove-Item "$S\server.pid", "$S\server.port" -ErrorAction SilentlyContinue; Get-ChildItem $S -Name
```

Pass: `listen: 0` (when block 7 ran), and none of `red`, `serve`, `v2src`, `v2`, `baseline`, `profile-*`,
`register-*.log`, `import-*.log`, `upgrade-*.log`, `upgrade.py`, `server.pid`, `server.port` is listed. A run that stopped early still cleans up; a server whose id you did not keep is not
yours to stop: report it.

## Fix-and-Retry Loop

```
implement -> build-and-test -> FAIL -> fix code (or the plan) -> build-and-test -> PASS -> verification
```

Only proceed to `verification-before-completion` when every required block passes. Any edit after the last
passing run voids that pass, a code-review fix included: run the blocks the Feature map selects for the whole
change again (block 1 always).

## Skip Conditions

Do NOT run this skill when:

- the user explicitly says no testing is needed
- in a planner session
- only planner artifacts changed and the current plan does not require validation
