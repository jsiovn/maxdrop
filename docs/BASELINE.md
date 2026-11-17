# Baseline: import time, memory and accuracy

What MaxDrop does with two large real interior scenes: first the engine inherited from io_scene_max 1.9.2
(`maxdrop/import_max.py`, unchanged in MaxDrop 0.0.1), then MaxDrop's own reader in version 0.0.3 and its
materials in 0.0.4, measured the same way and compared with what 3ds Max itself reports.

The two scenes are commercial assets and are not in this repository: they are called **scene A** and **scene B**
here, and only counts and measurements are recorded. Both are V-Ray interior scenes.

## How it was measured

- MaxDrop 0.0.1 (its engine is io_scene_max 1.9.2, commit `37db107`, byte for byte), Blender 5.2.0 LTS
  (Python 3.13.13), Windows 11, 64 GB of memory.
- `python tools/baseline.py`, one scene at a time: Blender headless with `--factory-startup` and a profile of its
  own, the operator `import_scene.maxdrop` with its default options (materials, UV maps, primitives, empties,
  Image Search on, Scale 1.0), into an emptied scene.
- Limits: 30 minutes, 40 GB for the process, 6 GB left on the machine. Neither run came near them.
- Wall time is the whole Blender process, start to exit; import time is the operator call alone. Peak memory is
  the peak working set of the Blender process (the peak commit charge is in brackets).
- Measured once, on 2026-11-14.

## Results

| | Scene A | Scene B |
|---|---:|---:|
| File size | about 370 MB | about 780 MB |
| Outcome | finished, no traceback | finished, no traceback |
| Wall time | 29 s | 102 s |
| Import time (operator) | 26 s | 90 s |
| Peak memory | 3.9 GB (4.1 GB) | 15.8 GB (16.2 GB) |
| Nodes in the file | 746 | 2,251 |
| Blender objects created | 423 | 1,806 |
| … meshes | 343 | 1,628 |
| … empties | 80 | 178 |
| … with a parent | 302 | 1,728 |
| Nodes skipped with a console line | 294 | 26 |
| Nodes that failed with an error | 0 | 1 |
| Nodes that left nothing and no message | 29 | 418 |
| Vertices | 3,116,435 | 9,027,149 |
| Polygons | 4,828,377 | 11,858,991 |
| Meshes with a UV layer | 271 | 1,573 |
| Meshes with a material | 337 | 1,581 |
| Materials created | 145 | 162 |
| Images loaded | 111 | 110 |

"Nodes in the file" counts the scene chunks the engine treats as nodes; "left nothing and no message" is that
count minus the objects created, the skipped and the failed nodes.

## Reading the numbers

- **Time is not the problem**: half a minute and under two minutes, with Blender frozen meanwhile.
- **Memory is**: the peak is about 10 times the file size for scene A and about 20 times for scene B. The engine
  turns the whole `Scene` stream into Python objects before it builds anything.
- **Coverage**: 57 % of the nodes of scene A and 80 % of scene B became an object. Most of the rest of scene A
  are lights.

## What was skipped or failed

- **Scene A**, 294 nodes skipped by name of their class: 282 V-Ray lights, 5 rectangles, 4 lines, 2 camera
  targets, 1 camera.
- **Scene B**, 26 nodes skipped: 24 V-Ray lights, 2 camera targets. One node failed inside the engine with
  `unpack requires a buffer of 12 bytes`; the engine caught it and went on.
- The nodes that left nothing are classes the engine neither converts nor names. Which classes they are is the
  first thing the new reader's census has to say.

## What the numbers do not say

Finishing without a traceback is not the same as a correct scene. Nothing here compares the result with 3ds Max:
positions, scale (scene units are not read), smoothing, instancing, material values and textures are unchecked,
and both scenes arrive without lights, cameras and anything built by a modifier. The counts are a starting line
for speed, memory and coverage, not a measure of quality.

## Version 0.0.3: MaxDrop's reader

Nodes, meshes, transforms, hierarchy, layers and units come from MaxDrop's reader; the materials still come from
the inherited engine, which reads the file a second time for them.

How it was measured: as above (`tools/baseline.py`, Blender 5.2.0 LTS, Python 3.13.13, the same machine, default
options: Units Auto, materials and UV maps on), MaxDrop 0.0.3, measured once on 2026-11-15. The 0.0.1 column is
the table above; 0.0.2 has the same engine (it added scene packs in front of it).

| | Scene A 0.0.1 | Scene A 0.0.3 | Scene B 0.0.1 | Scene B 0.0.3 |
|---|---:|---:|---:|---:|
| Outcome | finished | finished, no traceback | finished | finished, no traceback |
| Wall time | 29 s | 19 s | 102 s | 65 s |
| Import time (operator) | 26 s | 17 s | 90 s | 63 s |
| Peak memory | 3.9 GB (4.1 GB) | 3.7 GB (3.9 GB) | 15.8 GB (16.2 GB) | 14.4 GB (14.8 GB) |
| Nodes in the file | 746 | 746 | 2,251 | 2,251 |
| Blender objects created | 423 | 747 | 1,806 | 2,252 |
| … meshes | 343 | 343 | 1,628 | 1,625 |
| … empties | 80 | 404 | 178 | 627 |
| … of them placeholders | | 323 | | 448 |
| … with a parent | 302 | 472 | 1,728 | 1,743 |
| Nodes skipped or lost | 323 | 0 | 445 | 0 |
| Vertices | 3,116,435 | 3,116,416 | 9,027,149 | 9,027,887 |
| Polygons | 4,828,377 | 4,828,478 | 11,858,991 | 11,859,710 |
| Meshes with a UV layer | 271 | 271 | 1,573 | 1,570 |
| Meshes with a material | 337 | 337 | 1,581 | 1,578 |
| Materials created | 145 | 145 | 162 | 154 |
| Images loaded | 111 | 111 | 110 | 109 |

- Every node now becomes an object: one the reader does not convert arrives as an empty (a placeholder) in its
  place in the hierarchy, and the import report counts them by class. Both scenes also get the helper empty that
  carries sheared transforms (counted with the empties).
- Placeholders, scene A: 282 V-Ray lights, 20 spline shapes, 6 free lights, 5 rectangles, 4 lines and 6 others
  (a camera, a directional light, their targets, link composites). Scene B: 416 Particle Flow operators and events,
  24 V-Ray lights, 4 boxes, 2 targets, a camera and a sun.
- Time dropped by a third. Peak memory dropped little (scene A 0.2 GB, scene B 1.4 GB): the inherited material
  engine still parses the whole file for the materials. That goes away with the material conversion.

### Accuracy against 3ds Max

Both scenes were compared node by node with the dump of 3ds Max 2020 itself (`tools/oracle/dump_scene.ms`, see
[ORACLE.md](ORACLE.md)), by position in the node walk (the order and names are equal). Nodes with modifiers are
left out: MaxDrop does not apply modifiers yet. A world matrix matches when each of its 12 numbers is within 1e-4
(translation in the file's own unit), or within 1e-5 of its value when that is larger: the dump prints 6
significant digits, so a position of 1234.56 mm is only known to 0.01. A bounding box (meshes only) matches within
1e-3, or 1e-5 of its value.

| | Scene A | Scene B |
|---|---:|---:|
| Nodes | 746 | 2,251 |
| … with modifiers, left out | 84 | 209 |
| … compared | 662 | 2,042 |
| World matrix matches | 660 (99.7 %) | 2,040 (99.9 %) |
| Bounding box matches (meshes) | 280 of 280 (100 %) | 1,416 of 1,416 (100 %) |
| Both | 660 (99.7 %) | 2,040 (99.9 %) |

The four nodes that miss are a camera and a light in each scene, aimed by a Look At controller, which this version
does not evaluate. The milestone's target was 99 % in both scenes.

## Version 0.0.4: MaxDrop's materials

Materials and their texture maps now come from MaxDrop's reader too, so the file is read once. Measured as above
(`tools/baseline.py`, Blender 5.2.0 LTS, Python 3.13.13, the same machine, default options), MaxDrop 0.0.4, once,
on 2026-11-16.

| | Scene A 0.0.3 | Scene A 0.0.4 | Scene B 0.0.3 | Scene B 0.0.4 |
|---|---:|---:|---:|---:|
| Outcome | finished, no traceback | finished, no traceback | finished, no traceback | finished, no traceback |
| Wall time | 19 s | 13 s | 65 s | 17 s |
| Import time (operator) | 17 s | 11 s | 63 s | 15 s |
| Peak memory | 3.7 GB (3.9 GB) | 1.3 GB (1.4 GB) | 14.4 GB (14.8 GB) | 1.4 GB (1.4 GB) |
| Blender objects created | 747 | 747 | 2,252 | 2,252 |
| … meshes | 343 | 343 | 1,625 | 1,625 |
| Vertices | 3,116,416 | 3,116,416 | 9,027,887 | 9,027,887 |
| Polygons | 4,828,478 | 4,828,478 | 11,859,710 | 11,859,710 |
| Meshes with a UV layer | 271 | 271 | 1,570 | 1,570 |
| Meshes with a material | 337 | 336 | 1,578 | 1,625 |
| Materials created | 145 | 141 | 154 | 141 |
| Images loaded | 111 | 115 | 109 | 135 |

- Peak memory is now about 4 and 2 times the file size instead of 10 and 20, and scene B imports four times
  faster: the inherited engine parsed the whole file a second time for the materials.
- Materials: one Blender material per 3ds Max material that a mesh renders with (wrappers give their
  sub-material, a Multi/Sub-Object one slot per ID), where 0.0.3 made one per material and sub-material it met.
  Images: maps below Mix, Color Correction, Falloff and other wrappers are now loaded too.
- Scene B: every mesh now has its material. Scene A: 7 meshes (instances of one object) get none: their faces
  use material IDs past the end of their two-entry Multi/Sub-Object list, which 3ds Max repeats for such IDs and
  this version does not.

### Materials against 3ds Max

Each material was converted twice with the same rules: once from what MaxDrop's reader reads, once from the
parameters 3ds Max 2020 reports for it (the dump of `tools/oracle/dump_scene.ms` with its material graph). A
material matches when every channel of the two results agrees: numbers within 1e-3 (relative above 1), the same
texture file name per input, the same map structure below, and for a Multi/Sub-Object the same sub-material per
ID. The comparison script is local (it reads the commercial scenes); a 10 % change of 3ds Max's numbers makes
every test-file material fail it, so it compares.

| | Test files | Scene A | Scene B |
|---|---:|---:|---:|
| Materials | 62 | 214 | 220 |
| … matching | 62 (100 %) | 214 (100 %) | 220 (100 %) |
| Texture file names compared | 55 | 240 | 324 |

The milestone's target was 95 % in both scenes. The last VRayMtl of scene A to miss had a Normal Bump whose stored
reference to its normal map is stale; 0.0.4 reads the map 3ds Max shows. Scene A is a 3ds Max 2015
file saved in the 2012 format, whose parameter blocks do not list which reference holds each map: version 0.0.4
reads that from a table per class (before it, 39 of scene A's materials lost maps). Separately, the raw parameter
values of every V-Ray test file equal what 3ds Max reports (`tests/unit/test_materials.py`).

## Reproduce

```powershell
python tools\baseline.py --blender "<blender.exe>" --profile "<scratch>\profile" --label "scene A" `
    --out "<scratch>\scene_a.json" "<path>\scene.max"
```

Keep `--out` outside the repository: the JSON holds counts only, but Blender's console log written next to it
(`<out>.log`) names objects and texture files of the scene. Besides the measurements and `counts`, the JSON's
`import_report` holds the counts of the operator's `Imported ...` line (objects, meshes, materials,
placeholders, modifiers not applied, textures missing, approximated, issues). The skipped and failed nodes of
the 0.0.1 table came from lines the inherited engine printed; the tool no longer reads them.
