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

## Performance budget

What an import of the two scenes may cost, and the tests that keep a change from making the reader or the build
slower without anyone noticing. Measured as above (`tools/baseline.py`, Blender 5.2.0 LTS, Python 3.13.13, the same
machine, default options), on the code after 0.1.0 (the modal import of the next version included: a script still
runs the import at once), three times per scene on 2026-11-19 after the changes: the runs differ by up to 0.5 s and 0.02 GB, the table gives
the first.

| | Budget | Before | After |
|---|---:|---:|---:|
| Scene A wall time | 30 s | 13.0 s | 12.5 s |
| Scene A import time (operator) | | 10.9 s | 10.1 s |
| Scene A peak memory | 2 GB | 1.32 GB (1.40 GB) | 1.22 GB (1.29 GB) |
| Scene B wall time | 102 s (0.0.1's) | 17.0 s | 16.5 s |
| Scene B import time (operator) | | 14.6 s | 14.1 s |
| Scene B peak memory | 6 GB | 1.43 GB (1.41 GB) | 1.13 GB (1.22 GB) |

Objects, meshes, vertices, polygons, UV layers, materials, images and the import report's counts are the same before
and after, and the same as 0.1.0's table above.

### Where the time and the memory go

Working set sampled at the boundaries of the import's stages, in the same Blender process (after the changes below):

| | Scene A | Scene B |
|---|---|---|
| Index the file | 0.1 s, 0.20 GB | 0.1 s, 0.22 GB |
| Describe: geometry, controllers, modifiers, lights, cameras | 4.2 s, peak 1.00 GB | 7.0 s, peak 1.05 GB |
| Convert the materials | 0.5 s | 0.8 s |
| File closed | 0.74 GB | 0.66 GB |
| Build: meshes, objects, materials, images | 5.1 s, peak 1.21 GB | 6.6 s, peak 1.13 GB |

- Most of the memory is the file itself (mapped, its pages in the working set while it is read) and the description's
  arrays: closing the file gives back about 0.3 GB, then Blender's meshes take their place.
- The time is spread out. By the profiler, for scene B: the Editable Poly face records (a Python loop, 2.0 s without
  the profiler), Blender's own `foreach_set` of the meshes (2.7 s), the face and edge checks of the conversion and the
  sharp-edge flags of the build (sorting, below), the transform controllers (3 s profiled), the reading of chunks.
  For scene A also the images: 1.3 s for its 127 files, nearly all of it in `images.load` itself (MaxDrop's check
  of their first 18 bytes takes 0.02 s, the color space 0.01 s). No image is decoded during the import: `has_data`
  is false for every one of them after it; Blender reads the pixels on first use.

### What changed

- The sharp edges of a mesh sorted the edges twice (the second time in `numpy.unique`); the runs of equal edges now
  come from the first sort. Their arrays per loop are 32-bit where the indices fit, which was the peak of a mesh's
  conversion: scene B's peak dropped from 1.43 to 1.13 GB.
- Faces repeating another face's vertices were found with `numpy.unique` over rows, which sorts them as opaque
  records: a stable sort by columns finds the same faces.
- The sharp-edge flags of a built mesh compared every edge with every sharp edge through `numpy.isin` (a sort of all
  of them): a mesh without sharp edges now skips that, the others use a binary search.
- Not done, with the reason: a faster loop over the Editable Poly face records (walking only their offsets and
  reading the fields with numpy) gave 25 to 30 % of that loop, 0.3 s and 0.5 s here: not worth a second way of
  reading untrusted records. A build that frees each mesh's arrays as it goes: scene B's peak is in the description,
  not in the build, and both are far below the budget. Loading images later: they are already loaded lazily.

### The benchmarks

Neither corpus scene can be in the repository or in CI, so two tests measure the same code on a synthetic Editable
Poly object (`tests/synthetic_poly.py`: a grid of quads and triangles written as 3ds Max writes them, with smoothing
groups, material IDs, a map channel, doubled and degenerate faces; numpy, no 3ds Max):

- `tests/unit/test_perf.py` (plain Python, part of `python -I -m unittest discover tests`): 300,360 faces read
  (`reader.geometry`) and described (`convert.scene.mesh_description`).
- `tests/blender/bench.py` (in Blender, alone or from `tests/blender/run.py`, so CI's fixture step runs it): a million
  faces read, described and built (`build.objects.make_mesh`), and the built mesh's counts and sharp edges checked.

A time limit in seconds would pass on a fast machine what fails on a slow one. Each time is the best of a few runs
divided by the best time of a reference workload in the same process, their runs alternating so that a slow moment
of a shared machine hits both: plain Python record walking for the reader, the description's own mix of numpy calls
for the description (`describe_reference`: a pass per face size from `numpy.unique`, rows sorted along axis 1, a
stable `lexsort`, int64 pair keys with a stable `argsort`, `concatenate`, a float32 gather, each allocating its
result, on three fifths of the loop vertices, plus streaming numpy work on a sixth), a mesh made with Blender's own
calls alone for the build. The description's first reference was the streaming work alone (no sort, no allocation):
on CI's runners describe took 3.0 to 7.9 times as long as it, two clusters per Blender job by the runner it got and
the highest with numpy 2.3.4 on Linux, because that work speeds up with a CPU's vector units and numpy 2.x and
describe's sorts and allocations do not; no single limit was both twice the highest ratio and under three times the
lowest. Memory is the peak of the Python allocations (`tracemalloc`, numpy's included) as a multiple of the object's
size, which is the same on every Python and numpy measured.

Measured on CI (two attempts of one run of the Test workflow, 2026-11-20: the plain jobs on Linux and Windows with Python 3.11 and
numpy 1.24.3, 3.13 and 2.3.4; the Blender jobs on Linux) and on Windows here (2026-11-19, describe 2026-11-20; Python
3.11 with numpy 1.24.3 and 1.26.4 and 3.13 with 2.3.4 are the interpreters of Blender 4.2.23, 4.5.16 and 5.2.0, run
outside Blender for the plain test, which also ran on 3.9 with 1.26.4):

| Ratio | CI, Linux | CI, Windows | Windows here | Limit |
|---|---:|---:|---:|---:|
| Read / Python reference (300,360 faces) | 2.07 to 2.41 | 2.37 to 2.48 | 2.3 to 3.0 | 6.0 |
| Read / Python reference (a million faces, Blender) | 2.27 to 2.54 | | 2.1 to 2.7 | 6.0 |
| Describe / describe reference (300,360 faces) | 2.14 to 2.27 | 2.03 to 2.24 | 2.00 to 2.28 | 5.2 |
| Describe / describe reference (a million faces, Blender) | 1.92 to 2.35 | | 1.80 to 2.24 | 5.2 |
| Build / Blender reference (a million faces) | 1.96 to 2.29 | | 2.1 to 2.7 | 5.5 |
| Read + describe peak / object size (300,360 faces) | 5.07 | 5.07 | 5.07 | 5.3 |

A limit leaves at least 2.2 times the highest ratio measured on CI and stays under three times the lowest, so that
code three times as slow fails: a scratch copy that runs the reader, the description or `make_mesh` three times over
fails each test (read 6.9 to 8.4, describe 5.62 to 6.79 here, three times the CI ratios 5.76 to 7.05, build 6.8 to
7.9). Describe's 5.2 sits in the only window the CI numbers leave (2.2 x 2.35 = 5.17 to 3 x 1.92 = 5.76); read's 6.0
and build's 5.5 hold on the CI runs too (read 2.2 x 2.54 = 5.59 to 3 x 2.07 = 6.21, build 5.04 to 5.88). The memory
limit leaves 5 % (not the 1.5 times first planned: it is exact, the same on every Python and numpy measured, so a
margin buys nothing): one more 64-bit array per loop alive at the peak makes it 5.46 and fails, and the code before
the changes above gave 7.42 to 7.80. The CI log prints each ratio. A test past its limit is a regression to find, not
a limit to raise.

## Reproduce

```powershell
python tools\baseline.py --blender "<blender.exe>" --profile "<scratch>\profile" --label "scene A" `
    --out "<scratch>\scene_a.json" "<path>\scene.max"
```

Keep `--out` outside the repository: the JSON holds counts only, but Blender's console log written next to it
(`<out>.log`) names objects and texture files of the scene. Besides the measurements and `counts`, the JSON's
`import_report` holds the counts of the operator's `Imported ...` line (objects, meshes, curves, materials,
placeholders, modifiers not applied, textures missing, approximated, material problems, issues). The skipped and
failed nodes of the 0.0.1 table came from lines the inherited engine printed; the tool no longer reads them.

The first open:

```powershell
python tools\first_open.py --blender "<blender.exe>" --profile "<scratch>\profile" --label "scene A" --tag 52 `
    --out "<scratch>\first_open" "<path>\scene.max"
```

It prints its JSON (counts, class names, issue kinds and a yes or no per question) and exits 0 when every answer is
yes. The images and the log it writes beside the JSON show and name the scene: keep `--out` outside the repository
too.

The benchmarks (each prints its ratios and limits):

```powershell
python -I -m unittest discover -s tests -p test_perf.py -v
$env:BLENDER_USER_RESOURCES = "<scratch>\profile"
& "<blender.exe>" --background --factory-startup --python-exit-code 1 --python tests\blender\bench.py
```

The second prints `BENCH PASSED` (exit 0) or `BENCH FAILED` (exit 1).
