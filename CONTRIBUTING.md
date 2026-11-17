# Contributing

Bug reports, ideas and pull requests are welcome.

## Reporting a bug

Open an [issue](https://github.com/jsiovn/maxdrop/issues/new/choose) with your Blender version, your operating
system, how you installed the add-on and what the system console printed during the import (on Windows: *Window ›
Toggle System Console*; elsewhere start Blender from a terminal). Say which 3ds Max version and renderer the file
comes from if you know.

A `.max` file that shows the problem helps most, but only attach one you made yourself or may share: **never
post a scene you bought or received from a client.** If the scene cannot be shared, a small file with one
object that shows the same problem is just as good.

Check [docs/SUPPORT.md](docs/SUPPORT.md) first: much of what a scene holds is simply not imported yet.

## Working on the code

You need Blender 4.2 or newer and any Python 3 for the plain tests. There is nothing to install.

```powershell
python -I -m unittest discover tests                  # the unit tests, the tools, the landing page: no Blender
powershell -ExecutionPolicy Bypass -File build.ps1    # dist\: the zip, index.json and the landing page
```

The plain tests include a guard: `maxdrop/reader`, `maxdrop/convert` and `maxdrop/intake` must run without
Blender, so no module there may import `bpy`, `mathutils`, another module of the add-on outside these three
packages, or the add-on by its absolute name (`import maxdrop...` runs `maxdrop/__init__.py`, and inside Blender
the add-on has another name): import within them relatively. The code is linted with [ruff](https://docs.astral.sh/ruff/), configured in `pyproject.toml`. Install it in a virtual environment of its own, at the
version the `test` workflow pins:

```powershell
python -m venv $env:TEMP\maxdrop-ruff
& $env:TEMP\maxdrop-ruff\Scripts\python.exe -m pip install ruff==0.17.5
& $env:TEMP\maxdrop-ruff\Scripts\ruff.exe check .
```

Run the Blender tests headless with a profile of their own, so your preferences are never touched:

```powershell
$env:BLENDER_USER_RESOURCES = "$env:TEMP\maxdrop-profile"
& blender --background --factory-startup --python-exit-code 1 --python tests\smoke_register.py
& blender --background --factory-startup --python-exit-code 1 --python tests\smoke_import.py
```

Without arguments the import test takes every `tests/fixtures/*.max`; give a `.max` file or a folder after `--`
to import others.

On Linux and macOS the same commands work with `BLENDER_USER_RESOURCES=/tmp/maxdrop-profile blender …` and
forward slashes; `build.ps1` is three Blender commands, `python tools/check_zip.py <zip>` and
`python tools/make_site.py dist` (see the `test` workflow).

To try an install or an update the way users get them, serve `dist\` with
`python -m http.server --directory dist`, add `http://127.0.0.1:8000/index.json` in *Preferences › Get Extensions
› Repositories* and install from it. Do not test with *Install from Disk*: Blender never updates that copy, and
the same extension enabled from two repositories clashes.

## Layout

| Path | What it is |
|------|------------|
| `maxdrop/__init__.py` | Thin aggregator: registers the modules of `_NAMES`, reloads them, and drops the modules imported on demand. |
| `maxdrop/ops.py` | The import operator, its options popup (with the scene of a pack), the file handler for `.max`, `.rar` and `.7z`, and the *File › Import* entry. |
| `maxdrop/reader/`, `maxdrop/convert/` | The `.max` file read into plain Python objects, then the scene description, the material and texture-map rules, the texture lookup and the import report. No `bpy`. |
| `maxdrop/build/` | The only part that creates Blender data: objects and meshes, collections, materials (`materials.py`: Principled BSDF node trees), the report's text. Imported only when a file is imported. |
| `maxdrop/prefs.py` | The add-on preferences: version, Check for Updates, where scene packs are unpacked, texture search folders. |
| `maxdrop/update.py` | Check for Updates. The only code that goes online. |
| `maxdrop/compat.py` | What differs between Blender 4.2 and 5.2. |
| `maxdrop/intake/` | Scene packs: `archive.py` lists a `.zip`, `.rar` or `.7z` and unpacks the chosen `.max` with its maps into a flat folder; `external.py` runs the unpacker found on the computer for `.rar` and `.7z`. Plain Python, no `bpy`. |
| `site/index.html`, `tools/make_site.py` | The landing page and the script that fills it from `dist/index.json`. |
| `tools/baseline.py`, `tools/baseline_import.py` | Measure one import: time, peak memory, counts ([docs/BASELINE.md](docs/BASELINE.md)). |
| `tools/census.py` | Class census of one `.max`, no Blender: the objects per class, the nodes per base-object class and the modifier classes (`--json` for a machine-readable form). It names classes only, never a node, material, layer or the file, so its output from a scene that is not ours can be kept in notes ([docs/FORMAT.md](docs/FORMAT.md)). |
| `LICENSE`, `maxdrop/LICENSE` | The GPL v3 text, and the same file again so that it is in every zip. `tools/check_zip.py` checks a built zip for it. |
| `tools/fixtures/*.ms`, `tools/sanitize_fixture.py`, `tools/check_fixture.py`, `tools/cfb.py` | The test files: the MAXScript that authors each one, the tool that blanks the user and computer name 3ds Max writes into a file, the check that refuses names and paths, and the compound-file reader both use. |
| `tools/oracle/dump_scene.ms` | Writes what 3ds Max itself says about a scene as JSON: the `tests/fixtures/*.oracle.json` files the reader is checked against ([docs/ORACLE.md](docs/ORACLE.md)). |
| `tests/` | `test_site.py`, `test_license.py`, `test_intake*.py`, `test_fixtures.py`, `test_oracle.py` and `unit/` (the reader and the no-bpy guard) in plain Python, `smoke_register.py`, `smoke_import.py` (inside Blender); `fixtures/` holds the test `.max` files with their 3ds Max oracle (`.oracle.json`) and `fixtures/packs/` the test scene packs. |

## Test files

The `.max` files in `tests/fixtures/` are tiny scenes authored for MaxDrop, one MAXScript each in
`tools/fixtures/`. 3ds Max writes the Windows user name and the computer name into every file it saves, and the
repository is public, so a file goes in only after both tools have run on it:

```powershell
# in 3ds Max 2020, with nothing to keep in the scene: run tools\fixtures\<name>.ms, which saves
# C:\maxdrop_fixtures\<name>.max; then
python -I tools/sanitize_fixture.py C:\maxdrop_fixtures\<name>.max   # blanks the two names, in place
python -I tools/check_fixture.py C:\maxdrop_fixtures\<name>.max      # must print "clean"
```

The fixtures are saved with 3ds Max's gamma off (Preferences > Gamma and LUT), but gamma_swatches, whose script
turns it on; `tests/unit/test_gamma.py` fails for a fixture saved under the other setting. Copy it into
`tests/fixtures/` only then, regenerate its oracle (`MaxDropOracle.dumpFolder`, see
[docs/ORACLE.md](docs/ORACLE.md)) and commit both files together. `tests/test_fixtures.py` runs the same check
over every committed fixture. Keep each file under 1 MB and give every object and material a neutral name. The
tools know how 3ds Max 2020 stores the two names; a file from another version that they cannot read is refused
(`identity slots not found`) and needs the tools taught first.

## Conventions

- **Blender 4.2 LTS to 5.2 LTS, one zip.** Write Python 3.11 syntax (4.2 and 4.5 ship 3.11). Reach node sockets
  by name and check that they exist, never by index: `Thin Wall` and `Diffuse Roughness` are missing in 4.2. Use
  `Material.surface_render_method`, not `shadow_method` or `blend_method`. Anything else that differs goes into
  `compat.py`.
- **No commercial assets in git, ever**: no bought scene, none of its textures, names or dumps. Test files are
  self-authored, tiny, and free of user names, machine names and paths.
- English only for UI strings and comments; comment only the non-obvious *why*.
- Operators are `maxdrop.*` (the importer is `import_scene.maxdrop`), classes `MAXDROP_OT_*`; every module in
  `_NAMES` has `register()` / `unregister()` and its classes in a module-level `_classes` tuple.
- Only `update.py` reaches the network, only on the button, and it honours `bpy.app.online_access`. A new
  permission goes into the manifest.
- Files that come from io_scene_max keep their copyright and license header. A change to one adds a line saying
  what changed and when; new files are `GPL-3.0-or-later`.
- No new dependencies: the standard library and what Blender ships. `.rar` and `.7z` scene packs are unpacked by
  a program found on the user's computer (UnRAR, 7-Zip, bsdtar), never bundled: UnRAR's license is not compatible
  with the GPL, and a bundled program would have to be kept up to date by this project.
- A change users can see gets a line in `CHANGELOG.md` and, if it changes what is imported, in
  `docs/SUPPORT.md`.

## Pull requests

Keep them small and say what you tested and on which Blender version. The `test` workflow runs the plain tests
and the fixture scan on Linux and Windows, ruff on Linux, then, on Blender 4.2 LTS, 4.5 LTS and 5.2 LTS, the
build, the register smoke test, the import smoke test, and the fixture tests (`tests/blender/run.py`).
Dependabot proposes updates of the actions it uses once a week.

By contributing you agree that your work is released under the [GNU General Public License](LICENSE), either
version 3 of the License, or (at your option) any later version (GPL-3.0-or-later).
