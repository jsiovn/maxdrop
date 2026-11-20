# Changelog

All notable changes to **MaxDrop** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The version is
`version` in `maxdrop/blender_manifest.toml`; publishing a version requires its section here.

## [Unreleased]

### Changed

- Import: Esc while a windowed import reads a very large mesh stops the reading inside that mesh, so the next
  import can start at once (one mesh of 5.6 million face corners kept it busy for about a second more).

### Fixed

- Import: a defect in MaxDrop's reader (a TypeError or KeyError while reading a file) reports that file as not
  imported, with the error in the reason and its traceback in the console for a bug report, instead of ending the
  import with a Python error. The other files of the run are still imported.
- Scene packs on Linux and macOS: a folder another program creates at the name of the unpack's folder in the
  instant before it is put in place is no longer taken over (renamed with a rename that never replaces; Windows
  already refused).

## [1.0.0] - 2026-11-21

### Added

- **Version 1.0**: an import shows its progress and Esc cancels it, large scenes stay within a time and memory
  budget (see `docs/BASELINE.md`), the Falloff, Output and RGB Tint maps, Composite's blend modes and masks and
  Color Correction's rewiring are drawn as nodes, files of 3ds Max 2012 and older are read with their names
  (checked on made-up data), and hostile files are refused by limits instead of running Blender out of memory.
  Checked on two commercial interior scenes on Blender 4.2 and 5.2, as for 0.1.0. What is not imported yet stays
  listed in `docs/SUPPORT.md`.
- Import: started from a window (a drop, or File > Import), an import runs in steps: the status bar shows what it
  does (unpacking with the bytes written, reading, building with the count) and Blender keeps drawing. Esc
  cancels it and removes everything that import made (objects, meshes, materials, images, collections, the report
  text it created; the scene camera and render size are put back), also the scenes of the run it had finished; an
  unpack is stopped and its staging folder removed, a finished pack folder stays. A finished import is one undo step.
  An undo or a file load from another window during the import cancels it the same way.
  Imports from scripts (`bpy.ops.import_scene.maxdrop(filepath=...)`) and without a window stay synchronous.

- Materials: the map wrappers that were simplified to their first bitmap are drawn as nodes, from what 3ds Max
  2020 renders (measured): a Falloff (Perpendicular / Parallel, Fresnel, Towards / Away in the viewing direction)
  as its two sides mixed by Layer Weight, Fresnel or the facing ratio, each side mixed with its color by the map
  amount; a Composite with its blend modes (all but linear burn, soft light, pin light and hard mix) and layer
  masks; Color Correction's rewiring; an Output map's levels; an RGB Tint's channel mix. Other Falloff types and
  directions and the four blend modes left out are simplified as before.

- Import: files of 3ds Max 2012 and older, whose names are 8-bit text in the code page of the computer that saved
  them, are read with their names: in the code page the file records, else as UTF-8, else Western (1252). The new
  option **Text Encoding** picks another code page (Central European, Cyrillic, Greek, Turkish, Japanese,
  Simplified and Traditional Chinese, Korean, UTF-8); Unicode files of 3ds Max 2013 and later ignore it. The File
  line of the popup says which code page Auto reads such a file in. No file of those versions has been imported
  yet: checked on made-up data.
- Tests: files saved by 3ds Max 2020 in the 2017, 2018 and 2019 formats, with accented and Chinese names; docs/
  SUPPORT.md lists which 3ds Max versions are tested, expected to work or not supported.
- Landing page: three short videos (a scene pack chosen in File > Import, the same pack dropped from File Explorer,
  the unpacked .max chosen in File > Import), recorded in Blender 5.2 with the scene's contents blurred, and
  pictures of the options and the report. The page and the README no longer say Blender stops responding during
  an import.
- Landing page in Vietnamese (`vi.html`), with the same pictures and videos; a link in the header switches between
  English and Tiếng Việt.

### Changed

- Import: Esc while a windowed import reads its file stops the reading at the next object (it ran to the end of
  the file, and a new import was refused until then), and a very large mesh is built in several steps, so Blender
  keeps drawing and Esc answers during it.
- Primitives: a primitive is built with array operations instead of one Python step per face corner, the same mesh
  about ten times faster: one with segments in the thousands (up to the cap of 2,097,152 face corners) takes a few
  tenths of a second instead of up to 4 s, and a scene of many such primitives no longer stalls the reading.
- Materials: an inverted Output (of a Bitmap or an Output map) with an RGB offset subtracts the offset, as 3ds Max
  renders it (it was added).
- Report: a scene saved with a view through no camera active (common) names its scene camera, the first camera, in
  the render line instead of raising a warning; a damaged Config stream is named as such, not as "no saved view".
- Materials: an Output, RGB Tint or VRayColor2Bump map without a map of its own (or an Output or RGB Tint with it
  switched off) is named in the report; it is drawn as before (directly in a slot, the material keeps its own color
  or value), but no longer silently.
- Report: a VRaySky as the environment map is named under "environment" instead of "object N" (the number was the
  map's, not an object's).
- Materials: a color map read as linear (an EXR or HDR file under automatic gamma, a VRayBitmap transfer function
  None, a gamma override other than 2.2) is loaded in the Linear Rec.709 color space instead of Non-Color, so its
  colors keep their primaries in a scene whose working space is not Linear Rec.709 (Non-Color where Blender's color
  management config lacks it). Data maps stay Non-Color.
- Import: a scene with more than 1,048,576 objects is refused, and a mesh with more than 67,108,864 vertices (or map
  vertices in one channel) or 134,217,728 face corners is skipped with an issue naming the counts, instead of
  running Blender out of memory. A file whose reading runs out of memory or recursion depth ends in "Not imported"
  with a reason, like any other damaged file.
- Scene packs: `.7z` and `.rar` need 7-Zip 26.02 or newer (was 25.01) or bsdtar 3.8.8 or newer (was 3.7.4), the
  first versions with the vendors' fixes of overflows in their RAR and 7-Zip readers; UnRAR stays at 7.23. On
  Windows this applies to its own `tar.exe` too: an older one is not used (install WinRAR or 7-Zip instead).

### Fixed

- Scene pack popup: when every name the pack folder could take is already someone else's folder, the popup says so
  (what the import would stop with) instead of "Unpacks into a folder named after the archive"; a pack replaced at
  the same path while the popup is open no longer shows the folder of the old one. "No free folder" and "Cannot
  write into" put the folder on a line of its own, so a long path no longer cuts off the end of the message.
- Primitives: a standard primitive whose Real-World Map Size data is damaged is built with that option off instead
  of as a placeholder.
- Scene packs: Blender closing at the moment an unpack creates its folder (or the folder of a pack with several
  scenes) no longer leaves an empty folder behind that makes the next unpack use `<name> (2)`.
- Scene packs: the hidden folders left by rare crashes or by several unpacks of one pack at once are cleaned up by
  a later unpack of that pack (a half-filled `.maxdrop-reclaim-*` folder once stale; a leftover beside the folder
  of a pack with several scenes by every unpack of that pack that writes), and a folder holding a scene is kept
  instead of removed; a folder name freed from a stale unpack is taken again when its folder cannot be renamed
  into place.

## [0.1.0] - 2026-11-19

### Added

- **First open of a whole scene**: a dropped V-Ray interior scene now opens through its own camera, lit by its own
  lights, at its real size. Checked on two commercial interior scenes on Blender 4.2 and 5.2 (see
  `docs/BASELINE.md`).
- Target cameras, target lights and other objects aimed by a Look At controller or a LookAt Constraint point where
  they point in 3ds Max (they kept the rotation of no controller before); their targets arrive as empties, not
  placeholders. The new import option **Keep Targets** aims the ones with a Look At controller at their targets
  with a Track To constraint, so they follow when a target moves (a roll or the Y axis keeps the fixed rotation).
- V-Ray lights: plane and disc lights arrive as area lights, sphere lights as point lights, with their size, color
  or color temperature, on / off, invisibility and diffuse / specular / reflection switches, and a power in watts
  from their units. The new import option **Light Strength** (default 1.43, calibrated so that Cycles matches V-Ray's
  brightness) scales every light. A scaled light is as bright as in V-Ray. Instances share one light. Mesh and dome lights are not imported yet (a line in
  the report).
- Standard lights (Omni, Spot, Direct), photometric lights (every shape and distribution), VRaySun and VRayIES
  arrive as Blender point, spot, area and sun lights, as bright as V-Ray 5.2 renders them (measured), with their
  cones, colors, Kelvin temperatures, on / off and diffuse / specular switches. What Blender cannot hold is a line
  in the report: decay other than inverse square, a Direct's beam, IES and web distributions (a wide spot, the file
  named), the sky model's sun color. A Skylight and a VRaySky environment are not imported yet (a line each).
- Cameras: Free, Target, Physical and VRayPhysicalCamera arrive as Blender cameras with 3ds Max's framing: the
  horizontal field of view whatever the render aspect (zoom, lens breathing and a specified FOV included, as 3ds Max
  and V-Ray render them), lens shift, clipping and orthographic width. For a file with a camera, the camera of the view 3ds
  Max renders (the locked render view, else the active viewport), else the first, becomes the scene camera and the
  file's render size Blender's; a file without a camera leaves the scene's render settings alone. Depth of field, distortion, tilt correction and V-Ray's exposure are lines in the report.

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
