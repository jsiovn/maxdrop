# Changelog

All notable changes to **MaxDrop** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The version is
`version` in `maxdrop/blender_manifest.toml`; publishing a version requires its section here.

## [Unreleased]

### Added

- Target cameras, target lights and other objects aimed by a Look At controller or a LookAt Constraint point where
  they point in 3ds Max (they kept the rotation of no controller before); their targets arrive as empties, not
  placeholders. The new import option **Keep Targets** aims them at their targets with a Track To constraint, so
  they follow when a target moves.

### Changed

- Scene packs: the import popup names the exact folder a pack unpacks into (`<archive> (2)` when that name is
  taken, `<archive>/<scene>` for a pack with several scenes), and names it again when the Scene field picks
  another scene.
- Scene packs: a password-protected pack gives one message, naming the archive, whether it is a `.zip`, a `.rar`
  with a password on its data or one with encrypted names; entry names in messages and the Scene field are shown
  with `/` on every backend, and no message says "drop the .max" any more.
- Materials: importing a scene again, or a scene that shares texture files with one already imported, uses the
  images already in the `.blend` for the same file and color space instead of loading copies (`name.001`); an
  image that was painted on, packed, linked from a library or given another alpha mode is left alone and the file
  loaded anew.

### Fixed

- Materials: a Bitmap or CoronaBitmap with automatic gamma reads an EXR or HDR file as linear, as 3ds Max and
  Corona do, instead of as sRGB (too dark); a VRayBitmap already did.
- A damaged `.max` whose objects reference objects that do not exist no longer risks crashing Blender 4.2 and 4.5
  (Python 3.11) after the import is refused.
- Scene packs: a hidden `.maxdrop-staging-*` folder left by an unpack that never finished (Blender closed or crashed
  mid-way) is removed by the next unpack into that folder once it is hours old; two imports of the same pack at
  once no longer make the second fail or replace a folder made in between: it takes the next free folder name (or
  reuses the first one's folder); a `.zip` listing more entries than MaxDrop reads is refused before its directory
  is loaded into memory; a Windows junction is no longer searched or written into, like a link.
- Texture lookup: a folder with millions of files no longer slows an import down. Each search place reads at most
  200,000 files and folders, the listing of the `.max` file's folder and its parent for `maps` / `textures`
  folders included, instead of reading every entry of a huge folder before stopping; the report names the folder
  where a search stopped.
- Import report: the status line names material problems on their own ("2 material problems, 1 issue") and the text
  MaxDrop Report states their total; a texture file that was found but did not load is listed under the material
  issues instead of the other issues.
- Import report: a Falloff, VRayDirt, Output, RGB Tint or VRayColor2Bump over a map that converts to nothing is no
  longer listed as a simplified map (it draws nothing; its lost map is reported), and no longer marks a Mix that
  hides it as approximated.
- Import report: the Unpacker line of a `.rar` or `.7z` scene pack names the program that wrote the files when the
  first one failed and another took over, not the one that only listed the pack.
- Materials: a cropped or placed Bitmap with tiling off no longer repeats over the whole surface, and its mirror
  setting now applies, per direction; a map on map channel 0 (vertex colors) is drawn on UV channel 1 and named in
  the import report instead of sampling a UV map that does not exist; a texture file that holds no image is named
  in the report instead of rendering magenta; a material whose conversion or build fails no longer stops the whole
  scene from importing: the scene comes in without it and the report says so.

## [0.0.5] - 2026-11-18

### Added

- **Shapes as curves**: Line, Editable Spline, Rectangle, Circle, Ellipse, Arc and NGon arrive as Blender curve
  objects with their splines, knots and handles as 3ds Max draws them, straight segments straight, open or closed,
  at their place in the hierarchy. A shape set to render in 3ds Max gets its thickness as a round bevel. The import
  report counts the curves.
- **Extrude**: a shape with an Extrude arrives as the mesh 3ds Max makes of it: walls, floors and ceilings drawn as
  outlines are closed, with caps (holes where one outline lies inside another), outward normals, material IDs,
  sharp corners and mapping coordinates. The import report counts it as applied.
- **UVW Map**: planar, box, cylindrical (with cap) and spherical UVW Map modifiers give the mesh the mapping the
  artist set, in their map channel, with the gizmo's place, turn and size, tiling, flips, alignment and Real-World
  Map Size, also on an extruded shape and with several UVW Maps on one stack. Faces across the seam of a round map
  do not smear. Shrink-wrap, face and XYZ-to-UVW keep the stored coordinates, as does a UVW Map above a modifier
  MaxDrop does not apply (each a line in the report).
- **TurboSmooth, MeshSmooth, Shell and Symmetry as Blender modifiers**: they arrive as Subdivision Surface, Solidify
  and Mirror in 3ds Max's order, with their iterations, Smooth Result and smoothing-group creases, inner and outer
  amounts, axis, flip, slice, weld threshold and a moved or turned mirror gizmo (an empty), so the evaluated mesh
  matches 3ds Max's. New import option **Modifiers: Keep as Blender Modifiers / Ignore**. One above a modifier
  MaxDrop does not evaluate stays off (a line in the report); the report counts the converted ones.
- **Primitives**: Box, Plane, Pyramid, Sphere, GeoSphere, Cylinder, Cone, Tube and Torus arrive as the meshes 3ds
  Max builds from their parameters (segments, smoothing, material IDs, mapping coordinates, Real-World Map Size,
  negative sizes) instead of empties, and take UVW Maps and the modifiers kept as Blender modifiers like any mesh.
  Slice and hemispheres are not built yet: such a primitive stays an empty, with a line in the report.

### Changed

- **Import report, modifiers**: the line of modifiers not applied says what that means, "ignored: the object
  arrives as its base object, or as its Extrude makes it", and the report lists the modifiers applied (Extrude,
  UVW Map) apart from those converted to a Blender modifier.

### Fixed

- **Multi/Sub-Object material IDs past the list**: a face whose material ID has no entry gets the sub-material
  3ds Max renders it with instead of no material: the list repeats every *highest ID* IDs (with IDs 3 and 7,
  face ID 10 takes 3 and 14 takes 7), in nested Multi/Sub-Objects too.

## [0.0.4] - 2026-11-17

### Added

- **Materials by MaxDrop's own rules**: VRayMtl, VRayLightMtl, VRayFastSSS2, the V-Ray car paints, Standard (every
  shader) and Physical Material become a Principled BSDF with their colors converted to Blender's linear colors,
  roughness, metalness, IOR, transmission, emission with its strength, coat, subsurface, bump and normal maps.
  Every IOR is kept between 1 and 100, the coat IOR of VRayCarPaintMtl too (a full coat_strength gives 100).
  Wrappers (VRay2SidedMtl, VRayBlendMtl, VRayOverrideMtl, VRayMtlWrapper, Double Sided, Shellac, Shell Material)
  give their sub-material; Multi/Sub-Object gives one slot per material ID. Each 3ds Max material is one Blender
  material, also when instances carry different materials.
- **Texture maps as nodes**: a Bitmap keeps its tiling, offset, rotation, tile and mirror, cropping and map
  channel; Mix, RGB Multiply, Color Correction and Composite become nodes; Falloff, VRayDirt and other wrappers
  give the map below them. Color maps load as sRGB, data maps as Non-Color. A map MaxDrop cannot convert is named
  in the report and never replaced by the color its wrapper holds for that slot: below a Color Correction the
  material keeps its own color (not the Color Correction's black); a Mix, RGB Multiply or CoronaMix uses its other
  map, or the material keeps its own color.
- **Corona materials by MaxDrop's own rules**: CoronaPhysicalMtl, CoronaMtl (CoronaLegacyMtl) and CoronaLightMtl
  become a Principled BSDF (roughness or glossiness mode, metalness, refraction, opacity, self-illumination,
  clearcoat, bump); CoronaLayeredMtl gives its base material. CoronaBitmap is imported like a Bitmap, CoronaColor as a
  color, CoronaMix (mix and multiply) as nodes, CoronaNormal as a Normal Map node.
- **VRayBitmap (VRayHDRI) as an image texture**, like a Bitmap: its coordinates, cropping, transfer function (None,
  Inverse gamma, sRGB, Auto) and multipliers; a Composite, Color Correction or Mix above it keeps its image.
- **Color swatches follow the scene's gamma**: a scene saved with 3ds Max's gamma on (2.2, the default) takes
  every swatch as linear, as V-Ray renders it, instead of decoding it from sRGB, which made flat colors one display
  gamma too dark (a 128 grey swatch 0.216 instead of 0.502); a scene saved with the gamma off keeps the sRGB decode.
  This covers material colors and the colors of Mix, Falloff, Color Correction, VRayDirt, RGB Multiply, CoronaMix,
  VRayColor and CoronaColor's color and hex value. The import report names the rule; a file without the setting is
  taken as gamma on.
- **VRayColor as a color**: RGB or temperature, times its RGB multiplier, with its color gamma; a Falloff, Color
  Correction or Mix mask above it now gives its color instead of a wrong one.
- In a scene saved in the 3ds Max 2012 format, a map whose stored reference is stale (a Falloff's map, a Normal
  Bump's normal map) now gets the map 3ds Max shows.
- **The import report covers the materials**: materials built and converted by class, wrappers and maps that
  were simplified, material and map classes without a rule, textures found per lookup step and the ones not found
  by file name (for a scene pack: whether the archive held the file), the material inputs this Blender version
  lacks (Thin Wall on 4.2 and 4.5) and what a rule could not convert. The status bar line counts the materials and
  warns when anything was simplified or left out. The bug report form asks for the report.

### Removed

- io_scene_max's engine (`import_max.py`), which still made the materials: Arnold Standard Surface, Raytrace and
  Architectural materials now arrive as a grey material with their name until MaxDrop converts them.

### Changed

- **Faster, with far less memory**: the file is read once, by MaxDrop's reader. Two large interior scenes that
  needed 3.7 GB and 14.4 GB of memory in 0.0.3 now need about 1.3 and 1.4 GB, and import up to four times faster (see
  `docs/BASELINE.md`).
- **Textures are found in more places**: the scene's folder, then `maps` or `textures` folders beside the scene,
  then the **Texture Search Folders** of the preferences (now searched, with their subfolders), and last the path
  stored in the scene, only when it is on a local drive. Network and device paths stored in a scene are never
  opened. Texture paths are read from the scene's asset list, where 3ds Max keeps them.
- **Scene packs unpack only the maps the scene uses**: of a pack's image and `.ies` files, only those the chosen
  scene's asset list names are written (every one when that list cannot be read); the import report counts the
  files left out. A map the scene does not use no longer stops the unpack for being encrypted or unreadable.

## [0.0.3] - 2026-11-15

### Added

- **Units** in the import options: **Auto** (default) takes the unit the scene was saved with, so a scene in
  millimeters, centimeters, inches or feet arrives at its real size in meters; Millimeters, Centimeters, Meters,
  Inches and Feet override it. A file that does not state its unit is imported at one meter per unit, with a
  warning.
- A **File** line in the options popup of a dropped `.max` (or of a scene pack already unpacked): the 3ds Max
  version, the renderer, the number of objects and the unit.
- Smoothing groups (sharp edges, flat faces), instances as shared meshes, every UV channel, the whole parent chain
  matched by the file's object references, layers as nested collections, and the hidden, frozen and renderable
  flags of objects and layers.
- An **import report** after every import: the unit, the objects and meshes built, layers, hidden and frozen
  objects, groups, and what was not converted (placeholders by class, modifiers not applied, unknown controllers,
  geometry errors), plus the unpack of a scene pack. It is printed to the system console and kept in the text
  **MaxDrop Report** (Text Editor); importing several files at once keeps all their reports there. The status
  line says whether anything was left out.
- A shear inside an object's transform (a scale along a rotated axis) is kept: Blender's world matrix is the one
  3ds Max computes. The rest of the transform goes into the object's parent inverse; an object without a parent
  that needs it gets the empty **MaxDrop Shear** (at the origin, custom property `maxdrop_helper`) as its parent.

### Changed

- Nodes, meshes and transforms are read by MaxDrop's own reader instead of io_scene_max's engine; only the
  materials still come from that engine. An object it cannot convert arrives as an empty with its 3ds Max class in
  the custom property `maxdrop_class`.
- **Scale** is now an extra factor on top of **Units**: a preset or script that set it to `0.001` for a
  millimeter scene now shrinks the scene a thousand times more; set it back to `1`.
- Every import makes a collection named after the file in the active collection, with one collection per layer.
- A damaged or hostile `.max` reports "Not imported" and the other files of the run still import; an import that
  fails while building removes the objects, collections and meshes it made.
- Box, Sphere, Cylinder, Cone, Torus and Plane primitives, Boolean objects and Bipeds arrive as empties until a
  later version converts them (0.0.2 rebuilt the primitives as Blender primitives).
- Each mesh gets the material of its first object: instances share one mesh, so they share its material.
- A large scene imports in about two thirds of the time 0.0.2 took ([docs/BASELINE.md](docs/BASELINE.md)); peak
  memory drops only a little while the materials are read by the old engine.

### Removed

- The **Apply Matrix** option (`use_apply_matrix`): node transforms are always applied.
- The **Collection** option (`use_collection`): a collection named after the file is always made.
- The **Primitive**, **Empty** and **Armature** items of **Object Filter**, which keeps **Material** and **UV Maps**.
  A preset or script that names a removed option or item fails with an error until it is edited.

## [0.0.2] - 2026-11-15

### Added

- **Scene packs**: *File › Import › MaxDrop* also takes the `.zip`, `.rar` or `.7z` a scene was downloaded as, and
  a `.rar` or `.7z` can be dropped onto the 3D Viewport (a dropped `.zip` goes to Blender's extension installer).
  The chosen `.max` is unpacked with the pack's image and `.ies` files into a folder named after the archive and
  imported from there; nothing else in the pack is written or run. A pack with several scenes asks which one in
  the options popup (**Scene**). An unpacked pack is used again, and so is a folder you extracted yourself.
- `.rar` and `.7z` are unpacked by a program already installed (UnRAR, 7-Zip or bsdtar), from fixed paths and,
  except for a bsdtar of macOS or Linux itself, only in versions without known extraction problems. MaxDrop bundles
  none.
- **Unpack Scene Packs Into** in the add-on preferences: next to the archive (default) or a folder of your choice,
  which is also used when the archive's folder cannot be written.

### Changed

- The file handler is labelled `MaxDrop (.max, .rar, .7z)` and the menu entry `MaxDrop (.max, .zip, .rar, .7z)`;
  their ids are unchanged.
- The extension's file permission says that scene archives are unpacked.
- Several `.max` files chosen at once are imported one after the other, each on its own: an object can no longer
  be parented to an object of the same name from another file.

## [0.0.1] - 2026-11-14

First release: a fork of [io_scene_max](https://github.com/nrgsille76/io_scene_max) 1.9.2 by Sebastian Schrand,
made installable next to the original. It imports what io_scene_max 1.9.2 imports, nothing more yet;
[docs/SUPPORT.md](docs/SUPPORT.md) lists it. Free software under the GNU General Public License, either version 3
of the License, or (at your option) any later version (GPL-3.0-or-later); the license text is in the extension
zip.

### Added

- **Import of 3ds Max `.max` scenes without 3ds Max**: drop a file onto the 3D Viewport, or *File › Import ›
  MaxDrop (.max)*. Editable Mesh and Editable Poly objects with UVs and material IDs, six primitives, transforms
  and parenting, and materials (Standard, Physical, Multi/Sub-Object, V-Ray, Corona, Arnold Standard Surface) as
  a Principled BSDF with one image per channel.
- **Check for Updates** in the add-on preferences: compares with the published repository and lets Blender
  install the newer version.
- **Texture search folders** in the add-on preferences. The list is stored from this version on; the importer
  starts using it in a later one.

### Changed (from io_scene_max 1.9.2)

- The extension id is `maxdrop`, the operator `import_scene.maxdrop` and the file handler `MaxDrop (.max)`, so
  both importers can be enabled together.
- The file handler no longer names an export operator that never existed.
