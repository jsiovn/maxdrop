# The import report: materials and textures (maxdrop-arp.8) Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After every import the text "MaxDrop Report" (and the console, and the status line) says what MaxDrop did
with the scene's materials and textures: converted by class, wrappers and maps peeled, unknown classes, textures
found per lookup rule and missing by name, Principled inputs this Blender lacks, the material issues.

**Architecture:** The converters already count all of it (`MaterialConverter.stats`, `TexmapConverter.stats`,
`TextureIndex.report`) but `ops.py` drops them. `convert/report.py` gets `add_materials()`, which copies those
counters into the Report (read by attribute: no new imports into report.py beyond `convert.textures`), and the
text/summary grow a materials block, an "Approximated:" block and new "Not converted:" entries. `build/materials.py`
counts converted materials by class and the skipped Principled inputs per socket instead of filing one issue per
material; a texture not found is no longer a builder issue (the lookup reports it by name, once).

**Tech Stack:** Python 3.11 (no bpy in convert/), Blender 4.2 / 4.5 / 5.2 for build/ and ops.

---

## Report layout (order follows the MAXScript log 1125-1145: scene, materials, textures)

```
MaxDrop import report: room.max
[Scene pack block, unchanged]
Units: ... / Nodes read / Objects built / Layers / Objects hidden ... / Groups      (unchanged)
Materials built: 6 (converted by class: VRayMtl 3, Standard 2)                     (materials imported only)
Textures found: 4 (the scene's folder 4, maps or textures folders 0, texture search folders 0, the stored path 0)
Texture search of <rule> stopped after N files and folders, in <folder>            (if any)
Approximated:                                                                       (if any)
  Wrappers peeled to their sub-material, by class: Shell Material 1, VRay2SidedMtl 1
  Maps peeled to the map below them, by class: Falloff 3, Output 1
Not converted:                                                                      (if any)
  Placeholders ... / Modifiers ... / Unknown controllers ... / UV channels ...       (unchanged)
  Material classes without a rule (grey material), by class: X 1
  Map classes without a map below (not used), by class: Y 1
  Principled inputs not on Blender 4.2.23 (not set), materials: Thin Wall 1
  Textures not found: 2
    a.png
    b.png: in the archive, lost to a duplicate (sub/b.png)                          (unpacked pack only)
  Geometry errors: n (listed)                                                        (unchanged)
  Material issues: n
    object 422: CoronaMix 'X': operation 0 drawn as its first bitmap
  Other issues: n (listed)                                                           (unchanged)
Nothing was left out.                       (only when nothing is approximated and nothing is left out)
```

Summary: `Imported room.max: 6 objects, 2 meshes, 6 materials, nothing left out.` (INFO), else WARNING with parts
`N placeholders, N modifiers not applied, N textures missing, N approximated, N issues` (the ones that apply) and
`See the text MaxDrop Report.` The materials count appears only when materials were imported. The operator no longer
emits the separate `name: N materials` INFO line: the summary holds it, one line in the status bar.

Pack annotation of a missing name (only when `pack.mode == "unpacked"`, i.e. the unpack listed the archive now),
first match by case-folded base name: collided -> `in the archive, lost to a duplicate (<archive path>)`; refused
-> `in the archive, refused: <reason>`; not_regular -> `in the archive, not a regular file`; extension key in
`skipped` -> `the archive's <ext> files were skipped`; else `not in the archive`.

Counting: `approximated` = wrappers peeled + maps peeled. `_problems` adds grey materials, unsupported maps,
skipped sockets (material-socket pairs), material issues. `left_out` adds missing textures.

## Task 1: convert/report.py + unit tests

**Files:** Modify `maxdrop/convert/report.py`; Test `tests/unit/test_report.py`

- [ ] Write tests: `TestMaterials` with SimpleNamespace stats (conv: peeled {VRay2SidedMtl:1, Shell Material:1},
  unknown {Foo:2}, issues [(7, "wrapper: no sub-material")]; tex: peeled {Falloff:3}, unsupported {Bar:1}, issues
  [(9, "Mix 'm': its mix curve not converted")]); a real `convert.textures.TextureReport` with found/missing names;
  sockets {Thin Wall: 2}, blender "4.2.23". Assert exact block lines and order, `approximated == 5`, summary WARNING
  wording; empty stats + materials built -> INFO "..., 3 materials, nothing left out." and "Nothing was left out.";
  a materials-free report keeps today's text (no "Materials built" line); pack annotations for each case (collided,
  refused, not_regular, skipped ext, absent) and none when mode is "reused"; long missing list cut after MAX_LISTED.
- [ ] Run `python -I -m unittest tests.unit.test_report` -> FAIL (no add_materials).
- [ ] Implement: new slots, `approximated`, `_problems`, `left_out`, `summary`, `text`, `add_materials(rep,
  materials_built, classes=(), conv_stats=None, tex_stats=None, lookup=None, sockets=(), blender="")`.
- [ ] Run tests -> OK; commit `Report materials, maps and textures in the import report`.

## Task 2: build/materials.py

**Files:** Modify `maxdrop/build/materials.py`

- [ ] `MaterialBuilder.classes` (Counter of `ir.source` for each converted, non-grey IR made),
  `MaterialBuilder.sockets_skipped` (Counter {input name: materials}); `_Tree.skipped` set filled by `bsdf_input`
  instead of an issue, added to the builder after `build()`. `image()`: a texture not found returns None with no
  issue. Docstring updated. `issues()` keeps "texture not loaded".

## Task 3: ops.py

**Files:** Modify `maxdrop/ops.py`

- [ ] `_material_slots` returns `(slots, conv, tex, index)`; `_import_scene` calls
  `convert_report.add_materials(rep, len(built.materials), builder.classes, conv.stats, tex.stats, index.report,
  builder.sockets_skipped, bpy.app.version_string)` when materials are imported; drop the separate materials INFO
  line. Dated "Modified for MaxDrop, 2026-11-16" header line.

## Task 4: Blender tests

**Files:** Modify `tests/blender/run.py`, `tests/smoke_import.py` (its known-gaps check reads the report format)

- [ ] run.py: vray_maps -> "Textures not found: 7" and each name on its own `    <name>` line; found textures ->
  no "Textures not found"; check_builder -> lost texture: node without image and no builder issue; Thin Wall ->
  `builder.sockets_skipped["Thin Wall"] == 1` on 4.x, absent on 5.x, no issue line; new: after the operator imports
  vray_wrappers, the text exists and holds `  Wrappers peeled to their sub-material, by class: Shell Material 1,
  VRay2SidedMtl 1, VRayBlendMtl 1` and `Materials built: ` (inside run_fixture, name == "vray_wrappers", before the
  report is replaced by the gather-only publish).
- [ ] smoke_import `only_known_gaps`: the fixtures' known gaps are material-side only: heads under "Not converted:"
  among `Textures not found: N`, `Material issues: N`, and on Blender 4 `Principled inputs not on Blender ...`;
  an "Approximated:" block allowed; anything else (placeholders, geometry, other issues) is not a known gap.

## Task 5: docs + bug report form

**Files:** `.github/ISSUE_TEMPLATE/bug_report.yml`, `README.md`, `docs/SUPPORT.md`, `CHANGELOG.md`

- [ ] Bug form: a required-ish textarea "MaxDrop Report" asking to paste the text MaxDrop Report (Text Editor),
  removing names they do not want to publish; console field mentions the `MaxDrop:` lines.
- [ ] README step 4: material problems are in the report now. SUPPORT: report paragraph lists the new contents,
  drop "Maps that were simplified are not listed yet", "What comes next" no longer starts with the material report.
  CHANGELOG Unreleased: the report line rewritten.

## Verification

Working directory: repo root. `$S` = scratchpad; Blender paths from the bead notes.

1. `python -I -m unittest discover tests` -> `OK`.
2. `powershell -ExecutionPolicy Bypass -File build.ps1` -> exit 0, zip in `dist\`.
3. For each `$B` in 5.2 (`C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`), 4.2.23, 4.5.16 (portable):
   `BLENDER_USER_RESOURCES=$S\profile-<tag> $B --background --factory-startup --python-exit-code 1 --python
   tests\smoke_register.py`, then `--python tests\smoke_import.py`, then `--python tests\blender\run.py`;
   each exit 0, `FIXTURES PASSED` for run.py, no `FAIL` line in the smoke logs.
4. Success: the vray_wrappers check passes on all three; on 4.2 / 4.5 the Thin Wall socket line is listed under
   "Principled inputs not on Blender".
