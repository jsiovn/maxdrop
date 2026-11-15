# Layers, groups, hidden and renderable flags, and the import report Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the organisation of a 3ds Max scene over to Blender (layers as collections, hidden / frozen /
non-renderable nodes and layers, groups) and tell the user what was not converted (the import report).

**Architecture:** `reader/scene.py` decodes the node and layer flags and the layer records (no bpy).
`convert/scene.py` carries them into the scene description (`LayerDescription`, new `NodeDescription` fields,
unknown controllers by class). `convert/report.py` (no bpy) gathers counters and lists into a `Report` that renders
as text, with an optional scene-pack block. `build/collections.py` makes one collection per layer under a
collection named after the file and applies the visibility flags; `build/objects.py` links each object into its
layer's collection; `build/report.py` publishes a report (console with the `MaxDrop:` prefix, the text datablock
`MaxDrop Report`, one INFO / WARNING line).

**Tech Stack:** Python 3.11 syntax (plain tests run on 3.9 too), Blender 4.2 / 4.5 / 5.2 bpy, numpy.

---

## Format facts this plan relies on

Verified on `tests/fixtures/layers_flags.max` (committed) and, for what that fixture cannot show, on scratch files
saved by an own 3ds Max 2020 batch instance and compared with `tools/maxdiff.py` (base, base again, one change):

| Where | What | Shown by |
|---|---|---|
| node `0x0960` flags | `0x100000` hidden, `0x200000` frozen, `0x40` group head, `0x100` group member | layers_flags (hidden, group); scratch (frozen) |
| node `0x0975`, `0x0976` | empty chunks present on a hidden / frozen node | layers_flags (`0x0975`); scratch |
| node `0x099C` `u32` | bit `0x8000` = renderable | layers_flags (FixtureNoRender `0x0F005600`, others `0x0F00D600`) |
| Base Layer `0x1010` | layer name, UTF-8, no terminator | layers_flags (ASCII); scratch (`L` + U+00E4 + U+4E2D = `4c c3 a4 e4 b8 ad`) |
| Base Layer `0x1020` `u32` | `0x100000` hidden, `0x200000` frozen | scratch |
| Base Layer `0x1050` `u32` | bit `0x8000` = renderable | scratch |
| Base Layer `0x1090` `u8`, `0x10A0`, `0x10B0` `i32` | has a parent layer; its name (UTF-16); its object index | scratch (nested layer) |
| Layer Manager `(0x0D7374FC, 0x51FF028E)` refs | slot 0 = layer `0`, then the layers in creation order | layers_flags; scratch |

Facts only scratch files show go under *Open* in `docs/FORMAT.md` (the rule of that file), with the reader relying
on them like the corpus-only facts.

## Files

- Modify `maxdrop/reader/scene.py`: flag constants, `Node.hidden/frozen/group_head/group_member/renderable`,
  `Layer`, `Scene.layer(i)`, `Scene.layers()`, layer parents with a cycle cut.
- Modify `maxdrop/convert/scene.py`: `LayerDescription`, `SceneDescription.layers`, node fields `layer`, `hidden`,
  `frozen`, `renderable`, `group_head`, `group_member`; `unknown_controllers` Counter; a Dummy helper is an empty
  but not a placeholder.
- Create `maxdrop/convert/report.py`: `Report`, `gather(desc, ...)`, `Report.text()`, `Report.summary()`.
- Create `maxdrop/build/collections.py`: `make(desc, parent, name, view_layer)` -> `Collections`.
- Modify `maxdrop/build/objects.py`: `build(desc, collection, collections=None, view_layer=None)` links to the
  layer's collection and sets `hide_viewport` / `hide_set` / `hide_render` / `hide_select`.
- Create `maxdrop/build/report.py`: `publish(report)` -> `(level, line)`.
- Modify `tests/blender/run.py`: build through collections; check layers_flags (two collections, hidden object,
  hide_render, group parent + children) and the report datablock.
- Create `tests/unit/test_report.py`; extend `tests/unit/test_scene.py`, `tests/unit/test_convert_scene.py`.
- Modify `docs/FORMAT.md`.

`maxdrop/ops.py` is not changed: the operator still runs the old engine until maxdrop-too.11 switches it to
reader -> convert -> build. The report and `build.report.publish()` are ready for it; a follow-up bead wires the
operator (print, text datablock, INFO / WARNING line, the pack block from `archive.unpack()`'s result).

## Task 1: reader flags and layers

- [ ] Tests in `tests/unit/test_scene.py`: layers_flags node flags (`FixtureHidden.hidden`, `FixtureNoRender`
  not renderable, group head / members), `Scene.layers()` = `["0", "FixtureLayerA", "FixtureLayerB"]` with no
  flags set and the oracle's layer of each node; synthetic streams: layer flags bits, UTF-8 name, parent layer,
  a parent cycle cut, a parent that is not a layer, a short payload raising ChunkError.
- [ ] Implement; run `python -I -m unittest tests.unit.test_scene`.

## Task 2: convert description

- [ ] Tests in `tests/unit/test_convert_scene.py`: layers_flags description (layers used: A and B; node layer,
  hidden, renderable, group flags; placeholders `{}` now that Dummy is converted); every fixture: node flags equal
  the oracle's `hidden`, `frozen`, `renderable`, `layer`.
- [ ] Implement; run the module.

## Task 3: report

- [ ] `tests/unit/test_report.py`: a synthetic description (placeholders, unknown controllers, geometry issues,
  unit) renders the expected lines; summary level INFO without problems, WARNING with; the pack block comes first
  and names files written / reused / skipped / collided and the unpacker; a fixture description gives a report
  without issues; long issue lists are capped.
- [ ] Implement `maxdrop/convert/report.py`.

## Task 4: build

- [ ] `build/collections.py`, `build/objects.py`, `build/report.py`.
- [ ] `tests/blender/run.py`: each fixture into a file collection; layers_flags checks; `publish()` writes the
  datablock and returns INFO.

## Task 5: docs

- [ ] `docs/FORMAT.md`: the node flags, `0x099C`, Base Layer records and Layer Manager; scratch-only facts under
  *Open*.

## Verification

Working directory: the repo root. Scratch `S` = the session scratchpad. Blender paths from the bead notes.

1. Plain tests: `python -I -m unittest discover tests` -> last line `OK` (or `OK (skipped=N)` with the same
   skips as before).
2. Build: `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...`.
3. Fixtures in Blender, per version (5.2 installed, 4.2.23 and 4.5.16 portable), isolated profile:
   ```powershell
   $S = "<scratch>"; $B = "<blender.exe>"; $tag = "52"
   $env:BLENDER_USER_RESOURCES = "$S\profile-$tag"
   & $B --background --factory-startup --python-exit-code 1 --python tests\blender\run.py *>&1 | Out-File -Encoding utf8 "$S\fixtures-$tag.log"
   "exit $LASTEXITCODE"; Select-String -Pattern "^FIXTURES ", "^FAIL ", "^COUNTS " "$S\fixtures-$tag.log"
   ```
   Pass: exit 0, `FIXTURES PASSED`, no `FAIL`; layers_flags lines show two layer collections, one hidden object,
   one with hide_render, the group as parent + children; `COUNTS` equal on all three versions.
4. Register and import smoke (blocks 3-5 of build-and-test) on all three versions: `SMOKE PASSED`,
   `IMPORT PASSED` (the operator is unchanged, the package must still register and import).
