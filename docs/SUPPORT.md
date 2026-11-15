# What MaxDrop imports

**This page describes version 0.0.3.** Nodes, meshes, transforms,
hierarchy, instances, layers and scene units are read by MaxDrop's own reader; the materials still come from the
engine of [io_scene_max](https://github.com/nrgsille76/io_scene_max) 1.9.2 (`maxdrop/import_max.py`), which reads
the file a second time for them. A scene pack (`.zip`, `.rar`, `.7z`) is unpacked and its `.max` imported (see
[Files](#files)), and several `.max` files chosen at once are imported one after the other.

How far to trust the list: MaxDrop's test files (`tests/fixtures/`, saved by 3ds Max 2020) are compared with what
3ds Max itself reports for every node: world matrix, bounding box, vertex and face counts, parents, instances,
layers and the hidden, frozen and renderable flags. Two commercial interior scenes (3ds Max 2015 and 2020) import
without an error, and 99.7 % and 99.9 % of their objects without modifiers get the world matrix and bounding box
3ds Max reports (the rest are cameras and lights aimed by a Look At controller; see [BASELINE.md](BASELINE.md)). Materials are checked on the test files' Standard materials only. The page is updated with
every version.

"Not yet" means the importer does not convert it: the node arrives as an empty (a *placeholder*) at its place in
the hierarchy, with its 3ds Max class name in the custom property `maxdrop_class`.

After every import the **import report** says what arrived and what did not: the unit, the objects and meshes
built, layers, hidden and frozen objects, groups, the placeholders by class, the modifiers not applied, unknown
controllers and geometry errors, and the unpack of a scene pack. It is printed to the system console and kept in
the text **MaxDrop Report** (Text Editor); the status line says whether anything was left out.

## Objects

| In the `.max` file | This version |
|---|---|
| Editable Poly, Editable Mesh | **Imported**: vertices, faces (polygons stay polygons), material IDs. A face that uses a vertex twice or repeats another face is left out |
| UV channels of those meshes | **Imported**, every channel from 1 up: `UVMap` for channel 1, `UVChannel_<n>` for channel n; at most 8 per mesh (Blender's limit) |
| Smoothing groups | **Imported**: an edge between two faces that share no group is sharp, a face without a group is flat |
| Instances | **Imported** as one mesh shared by the objects |
| Object with modifiers | **Base object only**: the stack is not evaluated, so Extrude, UVW Map, TurboSmooth, Shell, Symmetry, Edit Poly and the others have no effect |
| Dummy helper, group head | **Imported** as an empty (the group's members are its children, as in 3ds Max) |
| Box, Sphere, Cylinder, Cone, Torus, Plane | Not yet: placeholder (version 0.0.2 rebuilt them as Blender primitives) |
| Boolean compound object, Biped | Not yet: placeholder |
| Line, Rectangle, Ellipse, Circle, NURBS surface | Not yet: placeholder |
| Standard lights, V-Ray lights, sky | Not yet: placeholder |
| Cameras and their targets | Not yet: placeholder |
| Everything else: other lights, hair, proxies (`.vrmesh`, Corona proxy), XRefs, particles, bones… | Not yet: placeholder |

## Scene structure

| | This version |
|---|---|
| Position, rotation, scale | **Imported** as 3ds Max computes them at frame 0: Position / Rotation / Scale controllers (Bezier, TCB, Euler XYZ and the other Tait-Bryan orders, Position XYZ, list controllers with their weights), negative scale, pivot offsets. An unknown controller (Look At, constraints…) counts as no transform for that node |
| Parent and child | **Imported** through the whole chain, by the file's object references: objects with the same name stay apart |
| Scene units | **Imported**: **Units: Auto** takes the system unit the file was saved with (inches, feet, miles, millimeters, centimeters, meters, kilometers, and a custom scale of those), so the scene arrives in meters. **Units** can name the unit instead, and **Scale** multiplies every length. A file that does not state its unit is imported at one meter per unit, times Scale, with a warning |
| Layers | **Imported** as collections below a collection named after the file, nested like the layers. A hidden layer is excluded from the view layer, a frozen one is not selectable, one that does not render has rendering off |
| Hidden, frozen and renderable flags of objects | **Imported** |
| Groups | Their head is an empty with the members as children |
| Selection sets | Not yet |
| A shear inside one object's transform (a scale along a rotated axis) | **Imported**: what Blender's location, rotation and scale cannot hold goes into the parent inverse. An object without a parent gets the empty **MaxDrop Shear** at the origin as its parent, one per imported file |
| Animation | Not yet: objects arrive as they stand at frame 0 |

## Materials

Materials still come from io_scene_max's engine, unchanged. Each mesh gets the material of its first object:
instances that carry different materials in 3ds Max share the first one's. A material the engine cannot read is
named in the system console; the mesh keeps its geometry. Turn materials off with **Object Filter**.

A material becomes a Principled BSDF through Blender's `PrincipledBSDFWrapper`. Values are copied as they are
stored in the file: colors are not converted between 3ds Max's and Blender's color spaces.

| Material | This version |
|---|---|
| Standard, Physical Material | **Imported** |
| VRayMtl | **Imported** |
| CoronaMtl, CoronaPhysicalMtl, Corona Skin and Hair | **Imported**; parameters are read by their position in the file, so a Corona version that stores them differently gives wrong values |
| Arnold Standard Surface | **Imported** |
| Raytrace, Architectural | **Imported**, colors and a few values only |
| Multi/Sub-Object | **Imported**: each sub-material becomes a material slot, faces keep their material ID |
| VRay2SidedMtl, Shellac, CoronaLayeredMtl | Their sub-materials, as slots |
| VRayLightMtl, VRayFastSSS2, VRayCarPaintMtl, VRayBlendMtl, other wrappers and every other material | Not yet: the object gets no material from it |

| Channel | This version |
|---|---|
| Base color, roughness, metallic, IOR, opacity (alpha), specular level and tint | **Imported** as plain values |
| Emission | The color only; its strength stays at Blender's default |
| Image textures | **One Bitmap per channel**, for base color, roughness, specular tint, normal (with its strength) and opacity, when the Bitmap is plugged straight into the material |
| Tiling, offset, rotation and cropping of a Bitmap | Not yet |
| Color Correction, Falloff, Mix, Composite, VRayColor, VRayDirt, noise and every other procedural or nested map | Not yet: the channel keeps its plain value |
| Bump (height) maps, displacement | Not yet |

## Textures

A `.max` file stores the paths of its texture files, not the images. This version takes only the **file name**
of each path and looks for it in the folder of the `.max` file, and with **Image Search** on in its subfolders.
A file that is not found is skipped; the material keeps its plain color. The texture search folders of the
add-on preferences are stored but not used by this version.

From a scene pack, the image and `.ies` files of the pack are unpacked flat into the folder of the `.max`, so the
lookup above finds them wherever they were in the archive. Of two maps with the same file name, the one nearest to
the scene in the archive is kept.

## Files

- `.max` files as 3ds Max writes them (OLE compound files). MaxDrop's reader also reads streams 3ds Max
  compressed; the material engine reads them only partly, so such a scene may arrive without materials.
- MaxDrop's test files come from 3ds Max 2020; scenes of 3ds Max 2015 and 2020 have been imported. Other versions
  are not verified one by one yet.
- When a `.max` is dropped, the options popup shows a **File** line: the 3ds Max version, the renderer, the
  number of objects and the unit, read in a fraction of a second even from a large scene.
- A very large scene works but needs time and memory: see [BASELINE.md](BASELINE.md) (version 0.0.3 next to
  the engine it replaces).
- **Scene packs**: a `.zip`, `.rar` or `.7z` holding the scene, chosen in *File › Import*; a `.rar` or `.7z` can
  also be dropped (a dropped `.zip` goes to Blender's extension installer). The format is recognised by the file's
  content. The chosen `.max` and the pack's image and `.ies` files are unpacked into a folder named after the
  archive, next to it or in the folder set in the preferences, and the scene is imported from there; a pack with
  several scenes asks which one. Everything else in the pack is skipped.
- `.zip` is read by Python's own `zipfile`: stored, Deflate, bzip2 and LZMA entries; not encrypted entries,
  Deflate64 or archives split into parts. File names without the UTF-8 flag are decoded as UTF-8, then GBK,
  Shift-JIS, cp1252, cp437.
- `.rar` (RAR 5; RAR 4 through UnRAR or 7-Zip only) and `.7z` need a program already installed: UnRAR 7.23 or
  newer, 7-Zip 25.01 or newer, or bsdtar 3.7.4 or newer (the `tar` of the system on macOS and Linux is taken
  whatever version it prints). Not readable: password-protected archives and archives split into volumes.
- Limits for one pack: 20,000 entries listed, 5,000 files and 16 GiB written, 4 GiB per file, 15 minutes, and
  512 MiB left free on the disk.

## What comes next

In this order: the material and texture-map conversion for V-Ray,
Corona, Standard and Physical materials, room shells (splines, Extrude, UVW Map), then lights and cameras.
