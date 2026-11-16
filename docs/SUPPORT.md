# What MaxDrop imports

**This page describes version 0.0.4.** Nodes, meshes, transforms, hierarchy, instances, layers, scene units and
materials are read by MaxDrop's own reader; the engine of [io_scene_max](https://github.com/nrgsille76/io_scene_max)
1.9.2 that 0.0.3 still used for materials is gone. A scene pack (`.zip`, `.rar`, `.7z`) is unpacked and its `.max`
imported (see [Files](#files)), and several `.max` files chosen at once are imported one after the other.

How far to trust the list: MaxDrop's test files (`tests/fixtures/`, saved by 3ds Max 2020) are compared with what
3ds Max itself reports for every node: world matrix, bounding box, vertex and face counts, parents, instances,
layers and the hidden, frozen and renderable flags. Two commercial interior scenes (3ds Max 2015 and 2020) import
without an error, and 99.7 % and 99.9 % of their objects without modifiers get the world matrix and bounding box
3ds Max reports (the rest are a camera and a light per scene aimed by a Look At controller; see
[BASELINE.md](BASELINE.md)). Materials are checked on the test files (VRayMtl, its wrappers, Multi/Sub-Object,
Standard, Physical Material and the texture maps below): the parameters MaxDrop reads are compared with what 3ds Max
reports, and the Blender material with those parameters, on Blender 4.2, 4.5 and 5.2. In the two commercial scenes,
the conversion of 213 of 214 and 220 of 220 materials (99.5 % and 100 %) gives what the same rules give from the
parameters 3ds Max reports, textures included (see [BASELINE.md](BASELINE.md)). The page is updated with every
version.

"Not yet" means the importer does not convert it: the node arrives as an empty (a *placeholder*) at its place in
the hierarchy, with its 3ds Max class name in the custom property `maxdrop_class`.

After every import the **import report** says what arrived and what did not: the unit, the objects and meshes
built, layers, hidden and frozen objects, groups, the placeholders by class, the modifiers not applied, unknown
controllers and geometry errors, the unpack of a scene pack; the materials built and converted by class, the
wrappers and maps that were simplified (peeled to what is below them) by class, material and map classes without a
rule, the textures found by each step of the lookup and the ones not found by file name (for a scene from a pack:
whether the archive held that file and why it was not written), each material input this Blender version lacks,
and what a material or map rule could not convert. It is printed to the system console (each line starting with
`MaxDrop:`) and kept in the text **MaxDrop Report** (Text Editor); the status bar shows a one-line summary, a
warning when anything was simplified or left out. The report names the scene's objects and files: it stays on
your computer.

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

Each 3ds Max material becomes one Blender material with the same name (two different materials of one name both
arrive, the second with Blender's `.001`), shared by every object that uses it: a Principled BSDF with its maps as
nodes. Color swatches follow the gamma setting the scene was saved with (Gamma and LUT, stored in the file): with
the gamma on (2.2, 3ds Max's default since 2014) a swatch's value is taken as linear, as 3ds Max and V-Ray render it
(a 128 grey swatch is 0.502 in Blender); with the gamma off it is decoded from sRGB, so it shows as in 3ds Max (128
grey is 0.216). A file that does not store the setting is taken as gamma on, and the report says so. The report
names the rule it used. A scene saved in LUT mode is read as gamma on (the file stores it so). Image files are
sRGB either way (or what their own gamma says). Turn materials off with
**Object Filter**.

| Material | This version |
|---|---|
| VRayMtl | **Imported**: diffuse, reflection (glossiness or roughness, metalness, Fresnel IOR), refraction (transmission, IOR, thin-walled), self-illumination, coat, bump, opacity. Fresnel off with a bright reflection becomes a metal; a refracting material takes its color from the refraction color |
| VRayLightMtl, VRayFastSSS2, VRayCarPaintMtl, VRayCarPaintMtl2 | **Imported**: emission; subsurface; a metal base with a coat |
| Standard (Blinn, Phong, Metal, Anisotropic, Oren-Nayar-Blinn, Multi-Layer, Translucent, Strauss) | **Imported**: diffuse, specular level and color, glossiness, self-illumination, opacity, IOR, bump |
| Physical Material | **Imported**: base, reflectivity, roughness, metalness, transparency, IOR, thin-walled, emission (luminance in cd/m²), coating, bump, cutout |
| Multi/Sub-Object | **Imported**: one material slot per material ID the faces use; nested ones too. A face whose ID has no entry in the list gets no material (3ds Max repeats the list for such IDs) |
| VRay2SidedMtl, VRayBlendMtl, VRayOverrideMtl, VRayMtlWrapper, Double Sided, Shellac | **The first sub-material** (the front, the base) |
| Shell Material | **The render sub-material** |
| CoronaPhysicalMtl | **Imported**: base color and level, roughness or glossiness mode, metalness, IOR, refraction (transmission, thin mode with its tint), opacity, self-illumination, clearcoat, bump. Verified on scenes made with Corona 12 |
| CoronaMtl (CoronaLegacyMtl) | **Imported**: diffuse, reflection (level, glossiness, Fresnel IOR), refraction (transmission, IOR, thin), opacity, self-illumination, bump; a Fresnel IOR of 10 or more with a bright reflection becomes a metal. Roughness is 1 - glossiness also with PBR mode off. Verified on Corona 12 scenes; one older Corona scene checked as well |
| CoronaLightMtl | **Imported**: emission (color, intensity, texture) and its opacity map |
| CoronaLayeredMtl | **The base material** (its first layer that is on when it has no base): the layers are not mixed in |
| Corona Skin and Hair, Arnold Standard Surface, Raytrace, Architectural and every other material | Not yet: a grey material that keeps its name |

| Channel | This version |
|---|---|
| Base color, metallic, roughness, IOR, opacity (alpha), specular, transmission, emission color and strength, coat, subsurface | **Imported**, by input name. **Thin Wall** exists from Blender 5.0: on 4.2 and 4.5 a thin-walled material is listed in the report instead |
| Bitmap | **Imported** as an Image Texture: tiling, offset, the U, V and W angles (about the map's center, as 3ds Max turns it), tile and mirror (one setting for both directions in Blender), cropping and placing, the map channel (a UV Map node), the Output's invert, level, offset and amount, its alpha. Color maps in sRGB, data maps (roughness, metallic, opacity, normal, bump) Non-Color; a gamma override on a color map is applied |
| CoronaBitmap | **Imported** like a Bitmap: UVW scale and offset, W angle, tiling or mirror per direction, cropping and placing, the map channel, gamma, alpha output |
| VRayBitmap (VRayHDRI) | **Imported** like a Bitmap: its coordinates, cropping and placing, alpha output; its transfer function on color maps (None as linear, Inverse gamma applied, sRGB; Auto and From 3ds Max as sRGB, as linear for an EXR or HDR file; data maps are read as they are, as for a Bitmap); its overall and render multipliers scale it. The environment mapping types (spherical, angular, cubic, mirrored ball) are drawn with the UVs |
| CoronaColor | **Imported** as a color: RGB, HDR, temperature (an approximate curve) or hex, times its multiplier |
| VRayColor | **Imported** as a color: RGB or temperature, times its RGB multiplier, with its color gamma. Its alpha and RGB primaries are not converted |
| CoronaMix | **Imported** as nodes for the Mix and Multiply operations (with the mix map as mask); the other operations are **simplified** to the first bitmap below; layer multipliers and offsets are not converted; the blend is linear (Corona's "mix in sRGB" is not read) |
| Mix, RGB Multiply, Color Correction, Composite (normal blend mode, no masks) | **Imported** as nodes (Mix, Hue/Saturation, Bright/Contrast, Gamma). A Mix curve, the rewiring, tint, pivot and lift of Color Correction are not converted |
| A map MaxDrop cannot convert below a map that wraps it | Named in the report. Never drawn as the wrapper's own color for that map: under a Color Correction, Falloff, VRayDirt, Output, RGB Tint or VRayColor2Bump the material keeps its own color or value. A Mix or CoronaMix whose amount hides that map is imported as it is; one whose amount shows only that map leaves the material its own color; otherwise it is **simplified** to its other map (or the material keeps its own), as an RGB Multiply always is. A mask it cannot convert leaves the mix amount, a Composite layer is left out, a normal map class keeps its other map |
| VRayNormalMap, Normal Bump, CoronaNormal | **Imported**: a Normal Map node with its strength and flips, its additional bump map as a Bump node |
| Bump (height) maps | **Imported** as a Bump node |
| Falloff, VRayDirt, Output, RGB Tint, VRayColor2Bump | **Simplified** to the map below them (Falloff and VRayDirt without a map: their color) |
| Every other map (noise, gradient, procedural maps…) | **Simplified** to the first Bitmap, CoronaBitmap or VRayBitmap below it, or not converted |
| Environment and planar (object or world XYZ) mapping, real-world scale | Drawn with the UVs |
| Displacement | Not yet |

## Textures

A `.max` file stores the path of each texture file as it was on the computer that saved the scene, not the
images. MaxDrop takes the **file name** of each path and looks for it, without regard to case, in this order:

1. the folder of the `.max` file (with **Image Search** on, its subfolders too);
2. folders named `maps` or `textures` beside the `.max` file or beside its folder, with their subfolders;
3. the **Texture Search Folders** of the add-on preferences, in their order, with their subfolders;
4. the stored path itself, only when it is a full path on a local drive of this computer (Windows only).

The first place that has the file wins. A path stored as a network share (`\\server\share\...`), a device path,
a relative path or one that climbs with `..` is never opened; its file name is still looked for in places 1 to 3.
Each place is searched once per import, at most 8 folders deep and 200,000 files and folders; links and
junctions are not followed. A file that is not found keeps its Image Texture node, without an image and not
connected, so the channel keeps its plain value (no black or magenta surface, in EEVEE or Cycles), and is named in
the import report. Each file is loaded once per color space.

From a scene pack, the image and `.ies` files the scene names are unpacked flat into the folder of the `.max`, so
the lookup above finds them wherever they were in the archive; the pack's other images are left out (all of them
are unpacked when the scene's asset list cannot be read). Of two maps with the same file name, the one nearest to
the scene in the archive is kept.

## Files

- `.max` files as 3ds Max writes them (OLE compound files), also streams 3ds Max compressed.
- MaxDrop's test files come from 3ds Max 2020; scenes of 3ds Max 2015 and 2020 have been imported. Other versions
  are not verified one by one yet.
- When a `.max` is dropped, the options popup shows a **File** line: the 3ds Max version, the renderer, the
  number of objects and the unit, read in a fraction of a second even from a large scene.
- A very large scene works but needs time and memory: see [BASELINE.md](BASELINE.md) (version 0.0.4 next to
  0.0.3 and the engine they replaced).
- **Scene packs**: a `.zip`, `.rar` or `.7z` holding the scene, chosen in *File › Import*; a `.rar` or `.7z` can
  also be dropped (a dropped `.zip` goes to Blender's extension installer). The format is recognised by the file's
  content. The chosen `.max` and the image and `.ies` files it names are unpacked into a folder named after the
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

In this order: room shells (splines, Extrude, UVW Map), then lights and cameras.
