# Baseline: import time, memory and accuracy

What MaxDrop does with two large real interior scenes: first the engine inherited from io_scene_max 1.9.2
(`maxdrop/import_max.py`, unchanged in MaxDrop 0.0.1), then MaxDrop's own reader in version 0.0.3, measured the
same way and compared with what 3ds Max itself reports.

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
the table above.

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
- Time dropped by a third. Peak memory barely moved: the inherited material engine still parses the whole file,
  and it is the larger share. It goes away with the material conversion.

### Accuracy against 3ds Max

Every node of both scenes was compared with the dump of 3ds Max 2020 itself (`tools/oracle/dump_scene.ms`, see
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

The four nodes that miss, two per scene, are a camera and lights aimed by a Look At controller, which this version
does not evaluate. The milestone's target was 99 % in both scenes.

## Reproduce

```powershell
python tools\baseline.py --blender "<blender.exe>" --profile "<scratch>\profile" --label "scene A" `
    --out "<scratch>\scene_a.json" "<path>\scene.max"
```

Keep `--out` outside the repository: the JSON holds counts only, but the engine's log written next to it
(`<out>.log`) names objects and texture files of the scene.
