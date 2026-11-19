# Baseline: import time, memory and accuracy

What MaxDrop does with two large real interior scenes: first the engine inherited from io_scene_max 1.9.2
(`maxdrop/import_max.py`, unchanged in MaxDrop 0.0.1), then MaxDrop's own reader in version 0.0.3, its
materials in 0.0.4, its room shells and modifiers in 0.0.5 and its lights and cameras in 0.1.0, measured the same way
and compared with what 3ds Max itself reports.

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

## Version 0.0.5: room shells and modifiers

Shapes arrive as curves, an Extrude on a shape as its mesh, UVW Maps are applied to their map channel, the standard
primitives are built from their parameters, and TurboSmooth, MeshSmooth, Shell and Symmetry are kept as Blender
modifiers. Measured as above (`tools/baseline.py`, Blender 5.2.0 LTS, Python 3.13.13, the same machine, default
options, Modifiers: Keep as Blender Modifiers), MaxDrop 0.0.5, once, on 2026-11-18. Vertices and polygons count the
meshes as built, before Blender's own modifiers. The 0.0.4 placeholders are those measured for 0.0.3: no object
kind changed in 0.0.4.

| | Scene A 0.0.4 | Scene A 0.0.5 | Scene B 0.0.4 | Scene B 0.0.5 |
|---|---:|---:|---:|---:|
| Outcome | finished, no traceback | finished, no traceback | finished, no traceback | finished, no traceback |
| Wall time | 13 s | 14 s | 17 s | 17 s |
| Import time (operator) | 11 s | 11 s | 15 s | 14 s |
| Peak memory | 1.3 GB (1.4 GB) | 1.3 GB (1.4 GB) | 1.4 GB (1.4 GB) | 1.4 GB (1.4 GB) |
| Blender objects created | 747 | 747 | 2,252 | 2,252 |
| … meshes | 343 | 363 | 1,625 | 1,629 |
| … curves | | 9 | | 0 |
| Vertices | 3,116,416 | 3,117,812 | 9,027,887 | 9,027,919 |
| Polygons | 4,828,478 | 4,830,308 | 11,859,710 | 11,859,734 |
| Meshes with a UV layer | 271 | 317 | 1,570 | 1,574 |
| Meshes with a material | 336 | 363 | 1,625 | 1,629 |
| Materials created | 141 | 158 | 141 | 143 |
| Images loaded | 115 | 127 | 135 | 141 |
| Placeholders | 323 | 294 | 448 | 444 |
| Modifiers applied (nodes, per class) | | 71 | | 20 |
| Modifiers converted to Blender modifiers (nodes, per class) | | 1 | | 158 |
| Modifiers not applied (nodes, per class) | | 41 | | 102 |

- Scene A's room is built from outlines: its 20 extruded shapes are now meshes, the shell of the room, so it no
  longer arrives open. They and the 9 shapes without an Extrude (now curves) were placeholders in 0.0.4. Scene B's
  4 boxes are meshes now. More materials and images: the extruded room and the Multi/Sub-Object IDs past the list
  (0.0.4 left 7 meshes of scene A without one) take their materials.
- Time and memory are unchanged: evaluating the stack costs little next to reading the file.
- Modifiers not applied, by class (nodes): scene A Edit Mesh 18, FFD 2x2x2 9, UVW Map 9 (above an Edit Mesh or an
  FFD), Edit Poly 1, Edit Spline 1, and a TurboSmooth, a Shell and a Symmetry on a shape without an Extrude; scene B
  UVW Map 45 (24 above an Edit Mesh, 19 switched off, 2 above a TurboSmooth), Edit Mesh 24, TurboSmooth 13 (7
  switched off, 6 above an FFD), Edit Poly 6, FFD(box) 6, Noise 6, FFD 2x2x2 1, VRayDisplacementMod 1.

### Modifiers against 3ds Max

Both scenes were compared node by node with the same 3ds Max 2020 dumps as the materials, which hold each node's
mesh after its whole stack (`eval_verts`, `eval_faces`, the world bounding box). Blender's side is the evaluated
object, its Blender modifiers included. A box matches within 1e-3 in file units, plus 1e-5 of the value for the
dump's 6 significant digits (the room of scene A is in millimeters: a wall corner at 6,260 mm is printed to 0.01).

| | Scene A | Scene B |
|---|---:|---:|
| Extrude modifiers (census) | 20 | 0 |
| … evaluated | 20 | |
| … vertex and triangle counts = 3ds Max's | 20 | |
| … bounding box = 3ds Max's | 16 | |
| UVW Map modifiers (census, objects) | 29 | 10 |
| … applied | 23 | 4 |
| Nodes with a UVW Map (census) | 59 | 46 |
| … with one applied | 51 | 20 |
| Objects whose modifiers are all applied or converted | 57 | 150 |
| … vertex count = 3ds Max's | 57 | 150 |
| … bounding box = 3ds Max's | 57 | 149 |

- The census counts modifier objects: a UVW Map instanced on several nodes counts once there, and once per node in
  the rows below it and in the first table. A node can hold a UVW Map that is applied and one that is not (above an
  Edit Mesh), so the first table's applied and not-applied nodes add up to more than the nodes with a UVW Map.
- The 4 extruded shapes whose box misses carry an Edit Mesh (3) or an FFD (1) above the Extrude, which MaxDrop does
  not apply: their box is off by 5 to 200 mm, what those modifiers move. The 6 UVW Maps of scene A that are not
  applied sit above an Edit Mesh or an FFD; in scene B above an Edit Mesh or a TurboSmooth, or switched off (the
  census counts a switched-off modifier too).
- Scene B's one box that misses is a TurboSmooth (kept as a Subdivision Surface), 0.3 mm off on an object 213 mm
  across (scene B is in millimeters too).
- Triangle counts can differ where vertex counts agree: a face that repeats another face or uses a vertex twice is
  left out (see [SUPPORT.md](SUPPORT.md)). That is the case for one object of scene A with a UVW Map, 27 of its 280
  objects without modifiers and 13 of scene B's 1,420.
- A render of scene A's room, headless from a fixed point inside it with a default light (its own lights and cameras
  are not imported yet), shows walls, floor and ceiling closed around the furniture; the image is not kept here.

## Version 0.1.0: lights and cameras

V-Ray, standard and photometric lights, VRaySun and VRayIES arrive as Blender lights, the cameras as Blender cameras,
and a file with a camera sets the scene camera and the render size. Measured as above (`tools/baseline.py`, Blender
5.2.0 LTS, Python 3.13.13, the same machine, default options), MaxDrop 0.1.0, once, on 2026-11-19.

| | Scene A 0.0.5 | Scene A 0.1.0 | Scene B 0.0.5 | Scene B 0.1.0 |
|---|---:|---:|---:|---:|
| Outcome | finished, no traceback | finished, no traceback | finished, no traceback | finished, no traceback |
| Wall time | 14 s | 13 s | 17 s | 16 s |
| Import time (operator) | 11 s | 11 s | 14 s | 14 s |
| Peak memory | 1.3 GB (1.4 GB) | 1.3 GB (1.4 GB) | 1.4 GB (1.4 GB) | 1.4 GB (1.4 GB) |
| Blender objects created | 747 | 747 | 2,252 | 2,252 |
| … lights (light datablocks) | | 289 (117) | | 25 (13) |
| … cameras | | 1 | | 1 |
| … meshes | 363 | 363 | 1,629 | 1,629 |
| Materials created | 158 | 158 | 143 | 143 |
| Images loaded | 127 | 127 | 141 | 141 |
| Placeholders | 294 | 2 | 444 | 416 |

- Instances of one light share its datablock, as instanced meshes do. Every light node of both files arrives as a
  light: none is a placeholder or left unbuilt. Scene A's two placeholders are LinkComposite helpers; scene B's are
  Particle Flow's operators and helpers (Mapping, Event, Display, Spin and the others), which MaxDrop does not read.
- Each scene's one camera is the scene camera (the view its file renders) and its render size Blender's.

### First open

The v0.1.0 gate: drop each scene and look through its own camera. `tools/first_open.py` imports the file with the
operator's default options (Units: Auto) in a fresh headless Blender, renders one frame through `scene.camera` with
EEVEE at 640 pixels across, the world dark so that only the imported lights light it (and once more with those
lights off: the brightness must come from them, not from glowing materials alone), and answers the gate's questions.
Run on Blender 5.2.0 and 4.2.23 on 2026-11-19: both versions gave the same answers and counts; the luminances below are
5.2's (4.2.23's within 0.002).

| | Scene A | Scene B |
|---|---|---|
| No traceback | yes | yes |
| No magenta, every texture found and loaded | yes: 0 % of the pixels; 118 textures found, 0 not found or not loaded | yes: 0 %; 132 found, 0 not found or not loaded |
| Lit by its own lights (mean luminance; with its lights off) | yes: 0.35 (0.001) | yes: 0.44 (0.0004) |
| Closed: rays through each quarter of the frame hit geometry | yes: 98 %, 100 %, 94 %, 94 % | yes: 100 % in each |
| Right scale: floor to ceiling in front of the camera | yes: 3.4 m | yes: 3.3 m |
| The report accounts for every node, light, camera and modifier class | yes: 746 nodes, 289 lights, 1 camera | yes: 2,251 nodes, 25 lights, 1 camera |

- Scene A's camera stands behind a wall and clips it away (3ds Max's clipping planes, imported): the image shows a
  closed, textured room, its floor, walls, ceiling and furniture lit by its spots and strips. The bottom of the frame
  is empty where the clipped floor would be, as in 3ds Max: those rays start past the near clip and pass under the
  floor, hence the 94 %.
- Scene B's camera is a long lens (139 mm) on one piece of furniture inside the room: every ray of the frame hits.
  A wide lens from the same point shows the room around it: floor, walls, ceiling and windows, lit through the
  windows by its VRaySun.
- "Accounts for" is checked against the file read again: its node count, each light or camera node a Blender light or
  camera, a placeholder of its class or an issue that says it was not built, and each modifier class of a node
  counted as applied, converted or not applied. What was simplified (wrappers and maps peeled, maps without a usable
  map below, lights' and cameras' settings Blender has no place for) is listed by class in the report.
- Scene A from a `.zip` and from a `.rar` of its folder: the same objects (747), materials (158) and images (127)
  as from the `.max` itself, and the same answers.

## Reproduce

```powershell
python tools\baseline.py --blender "<blender.exe>" --profile "<scratch>\profile" --label "scene A" `
    --out "<scratch>\scene_a.json" "<path>\scene.max"
```

Keep `--out` outside the repository: the JSON holds counts only, but Blender's console log written next to it
(`<out>.log`) names objects and texture files of the scene. Besides the measurements and `counts`, the JSON's
`import_report` holds the counts of the operator's `Imported ...` line (objects, meshes, curves,
materials, placeholders, modifiers not applied, textures missing, approximated, material problems, issues). The
skipped and failed nodes of the 0.0.1 table came from lines the inherited engine printed; the tool no longer reads
them.

The first open:

```powershell
python tools\first_open.py --blender "<blender.exe>" --profile "<scratch>\profile" --label "scene A" --tag 52 `
    --out "<scratch>\first_open" "<path>\scene.max"
```

It prints its JSON (counts, class names, issue kinds and a yes or no per question) and exits 0 when every answer is
yes. The images and the log it writes beside the JSON show and name the scene: keep `--out` outside the repository
too.
