# Baseline: the engine as forked

What the importer inherited from io_scene_max 1.9.2 (`maxdrop/import_max.py`, unchanged in MaxDrop 0.0.1) does
with two large real interior scenes. The reader rework is measured against these numbers.

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

## Reproduce

```powershell
python tools\baseline.py --blender "<blender.exe>" --profile "<scratch>\profile" --label "scene A" `
    --out "<scratch>\scene_a.json" "<path>\scene.max"
```

Keep `--out` outside the repository: the JSON holds counts only, but the engine's log written next to it
(`<out>.log`) names objects and texture files of the scene.
