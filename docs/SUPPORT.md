# What MaxDrop imports

**This page describes version 1.0.0.** Nodes, meshes, transforms, hierarchy, instances, layers, scene units and
materials are read by MaxDrop's own reader; the engine of [io_scene_max](https://github.com/nrgsille76/io_scene_max)
1.9.2 that 0.0.3 still used for materials is gone. From 0.0.5 the room shell arrives too (shapes, Extrude, UVW
Map), as do nine of the standard primitives and TurboSmooth, MeshSmooth, Shell and Symmetry as Blender modifiers.
From 0.1.0 the lights (V-Ray, standard, photometric, VRaySun, VRayIES) and the cameras arrive, and a file with a
camera sets the scene camera and the render size: a dropped interior scene can be looked at through its own camera,
lit by its own lights. From 1.0.0 an import started from a window shows its progress and Esc cancels it, the
Falloff, Output and RGB Tint maps, Composite's blend modes and masks and Color Correction's rewiring are drawn as
nodes, files of 3ds Max 2012 and older are read with their names (checked on made-up data), and limits refuse a
hostile file instead of running Blender out of memory. A scene pack (`.zip`, `.rar`, `.7z`) is unpacked and its
`.max` imported (see [Files](#files)), and several `.max` files chosen at once are imported one after the other.

How far to trust the list: MaxDrop's test files (`tests/fixtures/`, saved by 3ds Max 2020) are compared with what
3ds Max itself reports for every node: world matrix, bounding box, vertex and face counts, parents, instances,
layers and the hidden, frozen and renderable flags. Two commercial interior scenes (3ds Max 2015 and 2020) import
without an error, and all their objects without modifiers get the world matrix and bounding box 3ds Max
reports, the camera and the light aimed by a Look At controller in each included ([BASELINE.md](BASELINE.md) has
the measurement of version 0.0.3: 99.7 % and 99.9 %, before Look At was evaluated). Materials are checked on the test files (VRayMtl, its wrappers, Multi/Sub-Object,
Standard, Physical Material and the texture maps below): the parameters MaxDrop reads are compared with what 3ds Max
reports, and the Blender material with those parameters, on Blender 4.2, 4.5 and 5.2. In the two commercial scenes,
the conversion of 214 of 214 and 220 of 220 materials (100 %) gives what the same rules give from the
parameters 3ds Max reports, textures included (see [BASELINE.md](BASELINE.md)). Modifiers are checked the same
way: in the test files, the meshes MaxDrop makes from shapes with an Extrude, from primitives, with UVW Maps and with
the modifiers it keeps as Blender modifiers have 3ds Max's vertex and triangle counts and bounding box (Symmetry's
weld aside, see its row), and UVW Map coordinates equal 3ds Max's. In the scene whose room is built from outlines
(3ds Max 2015), all 20 extruded shapes of the room get 3ds Max's vertex and triangle counts, and the 16 whose
stack MaxDrop evaluates in full its bounding box (the other 4 have an Edit Mesh or an FFD above the Extrude, which
MaxDrop does not apply); in both scenes every object whose modifiers are all applied or converted gets 3ds Max's
vertex count (57 and 150 objects). Lights are checked against what V-Ray 5.2 renders (their brightness measured) and
cameras against the field of view 3ds Max computes, on the test files and on both scenes' cameras. Dropped on
Blender 4.2 and 5.2 with the default options, both scenes open, through their own camera, as a closed, textured
room at its real height (3.4 m and 3.3 m floor to ceiling), lit by their own lights, with no missing texture and a
report that accounts for every light, camera and modifier of the file (the *first open* in
[BASELINE.md](BASELINE.md)). The page is updated with every version.

"Not yet" means the importer does not convert it: the node arrives as an empty (a *placeholder*) at its place in
the hierarchy, with its 3ds Max class name in the custom property `maxdrop_class`.

After every import the **import report** says what arrived and what did not: the unit, the objects, meshes and
curves built, layers, hidden and frozen objects, groups, the placeholders by class, the modifiers not applied, unknown
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
| Object with modifiers | **Base object only**: the stack is not evaluated, so Edit Poly, Edit Mesh, FFD, Noise, Bend and the others have no effect (each class a line in the report), world-space modifiers too (a Map Scaler or another space-warp binding). The exceptions are Extrude on a shape and UVW Map, applied, and TurboSmooth, MeshSmooth, Shell and Symmetry, kept as Blender modifiers (below) |
| TurboSmooth, MeshSmooth, Shell, Symmetry | **Kept as Blender modifiers** in 3ds Max's order, with the import option *Modifiers: Keep as Blender Modifiers* (the default; *Ignore* leaves them out): TurboSmooth and MeshSmooth become Subdivision Surface (iterations and render iterations as levels; Smooth Result smooths the shading, separate by smoothing groups creases the edges between groups), Shell becomes Solidify (inner and outer amount, also both surfaces on one side of the original, and turned inside out as 3ds Max does when inner + outer is negative; the rim of an open mesh shades smooth into both surfaces, where 3ds Max keeps it hard), Symmetry becomes Mirror (axis, flip, slice, weld threshold; an empty is the mirror object when the gizmo was moved or turned). Only right above the base mesh, its Extrude or its UVW Maps: one above another modifier is not converted (a line in the report). Not converted, each a line in the report: MeshSmooth classic (made as Catmull-Clark) and its smoothness, separate by materials, Shell segments, bevel, material-ID overrides and, with auto smooth off, the smoothing-group override. A vertex within Symmetry's weld threshold of the plane is merged onto the plane, where 3ds Max slices beside it. Viewport levels that would give an object more than about a million faces are lowered (a line in the report; the render levels stay) |
| UVW Map | **Applied** into its map channel as 3ds Max maps it: planar, box, cylindrical (with or without cap) and spherical, with the gizmo's position, rotation and size, U / V / W tiling and flips, the X / Y / Z alignment, Real-World Map Size and an instanced UVW Map's own placement on each object. Several UVW Maps on one stack are applied in order; channel 1 is the UV map `UVMap`, channel n `UVChannel_n`. A face across the seam of a cylindrical or spherical map does not smear. Only UVW Maps right above the base object or its Extrude, with nothing else between: one above another modifier keeps the stored coordinates, as do shrink-wrap, face, XYZ-to-UVW and one writing the vertex color channel (each a line in the report) |
| Extrude on a shape | **Imported** as a mesh, as 3ds Max makes it: the sides in their segments, caps at both ends (holes in a cap where one spline lies inside another, solid again inside a hole), normals outward, material IDs 1 / 2 / 3 when it generates them, sharp edges at corner knots, mapping coordinates when it generates them (Real-World Map Size in file units). Grid caps are made as morph caps, a patch or NURBS output as a mesh and shape IDs are not read (each a line in the report). Only an Extrude that is the lowest modifier of the shape: one with another modifier below it leaves the shape a curve; the modifiers above it are not applied, but for UVW Maps and the modifiers kept as Blender modifiers |
| Dummy helper, group head | **Imported** as an empty (the group's members are its children, as in 3ds Max) |
| Box, Plane, Pyramid, Sphere, GeoSphere, Cylinder, Cone, Tube, Torus | **Imported** as the mesh 3ds Max builds from their parameters: the same vertices, the same polygons (a cap's fan stays triangles around its center), the pivot where 3ds Max has it, smoothing groups (sharp and flat edges) and material IDs as 3ds Max assigns them (a Box's sides 1 to 6), and, with Generate Mapping Coords, the same `UVMap` (Real-World Map Size in file units). Negative sizes as in 3ds Max for a Box, a Plane and the height of a Pyramid, Cylinder, Cone or Tube (a Box whose width and length differ in sign keeps its faces pointing in, as there); other negative sizes are built but not checked against 3ds Max. A primitive with modifiers is a mesh like any other below them (UVW Map applied, TurboSmooth and the others kept as Blender modifiers). Not yet, a placeholder with a line in the report: Slice on a Sphere, Cylinder, Cone, Tube or Torus, and the hemisphere of a Sphere or GeoSphere. A Plane's render scale and density are left out (a line in the report). Near the -X meridian of a GeoSphere a few faces' U may sit a whole turn from 3ds Max's |
| Teapot | Not yet: placeholder |
| Boolean compound object, Biped | Not yet: placeholder |
| Line, Editable Spline, Rectangle, Circle, Ellipse, Arc, NGon | **Imported** as curve objects: each spline with its knots and handles as 3ds Max draws them (straight segments stay straight), open or closed, the interpolation steps as the resolution. An NGon's corner radius, an Ellipse's outline and an Arc's angles as 3ds Max makes them. A shape that renders in 3ds Max (Enable In Renderer) gets a round bevel of its thickness, or its rectangular section (width, length and angle, capped at the ends of an open shape) through a hidden bevel object named after the curve (a section of width or length 0 is not drawn, a line in the report); on a shape that is not flat that section may turn otherwise than in 3ds Max (a line in the report). With modifiers other than an Extrude the shape arrives as the curve |
| Star, Text, Helix, Donut, Section, NURBS curves and surfaces | Not yet: placeholder |
| V-Ray lights: plane, disc, sphere | **Imported**: plane as a rectangular area light, disc as a disk area light, sphere as a point light with its radius, where 3ds Max has them (a plane shines along its -Z in both). Power in watts from each units mode (default, lm, lm/m²/sr, W, W/m²/sr) by the rules of a 3ds Max to FBX exporter, times the import option **Light Strength** (default 1.43: Cycles then renders them as bright as V-Ray 5.2, measured), color or color temperature, on / off (off: hidden in viewport and render), invisible (not seen by the camera), affect diffuse, specular and reflections (Cycles: the light hidden from diffuse or glossy rays; a contribution below 1 only in EEVEE, a line in the report). A scaled light is as bright as V-Ray makes it (its area grows with the scale). Instances share one light. A double-sided plane or disc shines on one side with half the power; a light's texture and directional spread are left out (each a line in the report) |
| V-Ray mesh and dome lights | Not yet: an empty, a line in the report |
| Standard lights: Omni, Free / Target Spot, Free / Target Direct | **Imported**: Omni as a point light, Spot as a spot light (cone from falloff, full intensity out to the hotspot), Direct as a sun, with color, on / off and affect diffuse / specular. Power as bright as V-Ray 5.2 lights them (measured), times **Light Strength**: with inverse-square decay as bright at every distance past the decay start; without decay or with inverse decay as bright at 1 m or at the decay start only (Blender's lights fall off with the square of the distance; a line in the report); decay from a start of 0 gives 0 W (a line in the report). A Direct's beam, a rectangular cone, overshoot and ambient only are left out (a line each) |
| Photometric lights (Free / Target Light, every shape) | **Imported**: isotropic as a point light, spotlight as a spot light with its cone, uniform diffuse as an area light of its rectangle or disc (a point a small disc; a line, sphere or cylinder the nearest area light, a line in the report), photometric web as a wide spot (the web file named in the report); intensity in cd with the dimmer, Kelvin and filter color, on / off, affect diffuse / specular; disc, sphere and cylinder radius on point and spot lights. Power as bright as V-Ray 5.2, times **Light Strength** |
| VRaySun | **Imported** as a sun: strength from the intensity multiplier (100 klx per unit, V-Ray's at the zenith), angle from the size multiplier, its filter color (the sky model's color and dimming toward the horizon are left out: a line in the report) |
| VRayIES | **Imported** as a wide spot: power from its lumens or its intensity override, color or temperature, affect diffuse / specular; the IES file is named in the report, its distribution not imported (nor its own intensity, which V-Ray takes at power 0: then 0 W, a line in the report) |
| Skylight, VRaySky (environment) | Not yet: the Skylight an empty, each a line in the report |
| Cameras: Free, Target, Physical, VRayPhysicalCamera | **Imported** as Blender cameras where 3ds Max has them, framing what 3ds Max renders: the horizontal field of view for the scene's render aspect (Physical and V-Ray: zoom, lens breathing at the focus or target distance, a specified FOV; checked against 3ds Max within 0.05°), lens shift, clipping, orthographic width. Depth of field, distortion, tilt correction, a multi-pass effect and V-Ray's exposure are left out (a line each in the report) |
| Render size, scene camera | **Imported** for a file with a camera: the scene camera is the camera of the view 3ds Max renders (the locked render view, else the active viewport), else the first camera (named in the report's render line; an issue only when the file's saved views cannot be read), and the Blender scene takes the file's render width, height and pixel aspect. A file without a camera (a model dropped into a scene) leaves the scene's render settings and camera as they were; the report gives its render size |
| Targets (of target cameras and lights) | **Imported** as empties where 3ds Max has them, not placeholders |
| Everything else: other lights, hair, proxies (`.vrmesh`, Corona proxy), XRefs, particles, bones… | Not yet: placeholder |

## Scene structure

| | This version |
|---|---|
| Position, rotation, scale | **Imported** as 3ds Max computes them at frame 0: Position / Rotation / Scale controllers (Linear, Bezier, TCB, Euler XYZ in all six Tait-Bryan orders, Position XYZ, ScaleXYZ, Linear, Bezier and TCB Float, list controllers with their weights; an animated one at frame 0 from its keys whatever frame the file was saved at; between two Bezier or TCB keys interpolated linearly, a line in the report), negative scale, pivot offsets, the Look At controller of target cameras and lights (axis, flip, roll, the target as up node) and the LookAt Constraint (weighted targets, axes, an up node looked at or aligned with). The constraint's Keep Initial Offset and Set Orientation are left out (a line in the report). Another controller (other constraints, expressions, scripts…) counts as no transform for that node |
| Look At targets | The rotation 3ds Max computes, fixed. With the import option **Keep Targets** an object with a Look At controller gets a Track To constraint aimed at its target's object instead, so it follows when the target moves; one with a roll or aimed along its Y axis keeps the fixed rotation (a line in the report: Track To has no roll and no downward up axis). Track To takes Blender's Z as up: with Forward and Up other than 3ds Max's (Y forward, Z up) a line in the report says so. A camera straight below its target, and a Look At with a scale along a turned axis, are not checked against 3ds Max with Track To (the fixed rotation is). LookAt Constraints stay fixed |
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
sRGB either way, EXR and HDR files linear (or what their own gamma says). Turn materials off with
**Object Filter**.

| Material | This version |
|---|---|
| VRayMtl | **Imported**: diffuse, reflection (glossiness or roughness, metalness, Fresnel IOR), refraction (transmission, IOR, thin-walled), self-illumination, coat, bump, opacity. Fresnel off with a bright reflection becomes a metal; a refracting material takes its color from the refraction color |
| VRayLightMtl, VRayFastSSS2, VRayCarPaintMtl, VRayCarPaintMtl2 | **Imported**: emission; subsurface; a metal base with a coat |
| Standard (Blinn, Phong, Metal, Anisotropic, Oren-Nayar-Blinn, Multi-Layer, Translucent, Strauss) | **Imported**: diffuse, specular level and color, glossiness, self-illumination, opacity, IOR, bump. Known issue: the maps of an Anisotropic, Oren-Nayar-Blinn, Multi-Layer, Translucent or Strauss material are read from Blinn's map slots, so one can land in another input (a Strauss glossiness map as the diffuse map) |
| Physical Material | **Imported**: base, reflectivity, roughness, metalness, transparency, IOR, thin-walled, emission (luminance in cd/m²), coating, bump, cutout |
| Multi/Sub-Object | **Imported**: one material slot per material ID the faces use; nested ones too. A face ID past the list wraps as in 3ds Max: the list repeats every *highest ID* IDs (with IDs 3 and 7, face ID 10 takes 3 and 14 takes 7); a face whose ID still has no entry, or whose entry is switched off or empty, gets no material (3ds Max renders it black) |
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
| Bitmap | **Imported** as an Image Texture: tiling, offset, the U, V and W angles (about the map's center, as 3ds Max turns it), tile and mirror (one setting for both directions in Blender; a cropped or placed image tiles, mirrors or clips per direction), cropping and placing, the map channel (a UV Map node; channel 0, the vertex colors, is drawn on channel 1 and named in the report), the Output's invert, level, offset and amount, its alpha. Color maps in sRGB, data maps (roughness, metallic, opacity, normal, bump) Non-Color; a color map read as linear (an EXR or HDR file, gamma 1.0) or with a gamma override other than 2.2 in Linear Rec.709, so Blender converts it into the scene's working space (Non-Color where Blender's color management config lacks it), the override applied as a gamma; automatic gamma reads an EXR or HDR file as linear, as 3ds Max does |
| CoronaBitmap | **Imported** like a Bitmap: UVW scale and offset, W angle, tiling or mirror per direction, cropping and placing, the map channel, gamma (automatic reads an EXR or HDR file as linear, as Corona does), alpha output |
| VRayBitmap (VRayHDRI) | **Imported** like a Bitmap: its coordinates, cropping and placing, alpha output; its transfer function on color maps (None as linear, Inverse gamma applied, sRGB; Auto and From 3ds Max as sRGB, as linear for an EXR or HDR file; data maps are read as they are, as for a Bitmap); its overall and render multipliers scale it. The environment mapping types (spherical, angular, cubic, mirrored ball) are drawn with the UVs |
| CoronaColor | **Imported** as a color: RGB, HDR, temperature (an approximate curve) or hex, times its multiplier |
| VRayColor | **Imported** as a color: RGB or temperature, times its RGB multiplier, with its color gamma. Its alpha and RGB primaries are not converted |
| CoronaMix | **Imported** as nodes for the Mix and Multiply operations (with the mix map as mask); the other operations are **simplified** to the first bitmap below; layer multipliers and offsets are not converted; the blend is linear (Corona's "mix in sRGB" is not read) |
| Mix, RGB Multiply, Color Correction | **Imported** as nodes (Mix, Hue/Saturation, Bright/Contrast, Gamma), Color Correction's rewiring too (monochrome, invert, custom channels; an alpha source is drawn as opaque). A Mix curve and the tint, pivot and lift of Color Correction are not converted |
| Composite | **Imported** as nodes: each layer's blend mode drawn at full strength, then mixed in by its opacity times its mask (the mean of the mask's color), as 3ds Max renders it. Linear burn, soft light, pin light and hard mix are not drawn: such a Composite is **simplified** to the first bitmap below |
| Falloff | **Imported** as nodes for the types Perpendicular / Parallel (Layer Weight, Facing), Fresnel (a Fresnel node at its IOR; 3ds Max's ramp is up to 0.025 darker facing the camera) and Towards / Away in the viewing direction, each side its color, its map, or the two mixed by the map amount; its own Output too. Its mix curve is not read (drawn linear). Other types (Shadow / Light, Distance Blend) and directions are **simplified** to map 1, or color 1 without it |
| Output, RGB Tint | **Imported** as nodes: the Output's invert, level, offset and amount (its clamp and color map curve are not read); the RGB Tint's three colors as a channel mix |
| A map MaxDrop cannot convert below a map that wraps it | Named in the report. Never drawn as the wrapper's own color for that map: under a Color Correction, VRayDirt, Output, RGB Tint or VRayColor2Bump the material keeps its own color or value; a Falloff, whose sides show at every angle, is **simplified** to its other map (or the material keeps its own). A Mix or CoronaMix whose amount hides that map is imported as it is; one whose amount shows only that map leaves the material its own color; otherwise it is **simplified** to its other map (or the material keeps its own), as an RGB Multiply always is. A mask it cannot convert leaves the mix amount, a Composite layer is left out, a normal map class keeps its other map |
| VRayNormalMap, Normal Bump, CoronaNormal | **Imported**: a Normal Map node with its strength and flips, its additional bump map as a Bump node |
| Bump (height) maps | **Imported** as a Bump node |
| VRayDirt, VRayColor2Bump | **Simplified** to the map below them (VRayDirt without a map: its color; VRayColor2Bump without a map: named in the report, and the material keeps its own value) |
| Output, RGB Tint without a map, or with it off | Named in the report; the material keeps its own color or value |
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
Each place is searched once per import, at most 8 folders deep and 200,000 files and folders read, however
large the folders are (for place 2, the listing of the `.max` file's folder and its parent counts too; the report
says where a search stopped); links and junctions are not followed. A file that is not found keeps its Image
Texture node, without an image and not connected, so the channel keeps its plain value (no black or magenta
surface, in EEVEE or Cycles), and is named in the import report. A file that is found but holds no image (empty,
or not starting as its format does) is left out the same way and named in the report. Each file is loaded once per
color space; an image of the same file and color space already in the `.blend` (an earlier import's) is used
again, unless it was painted on, packed, linked from a library or given another alpha mode. A material that fails
to convert or build is named in the report and the scene comes in without it (its faces without a material) instead
of failing.

From a scene pack, the image and `.ies` files the scene names are unpacked flat into the folder of the `.max`, so
the lookup above finds them wherever they were in the archive; the pack's other images are left out (all of them
are unpacked when the scene's asset list cannot be read). Of two maps with the same file name, the one nearest to
the scene in the archive is kept.

## Files

- `.max` files as 3ds Max writes them (OLE compound files), also streams 3ds Max compressed.
- The 3ds Max version of the file:

  | The file | This version |
  |---|---|
  | Saved by 3ds Max 2020 | Tested: every test file. |
  | Saved by 3ds Max 2020 in the 2017, 2018 or 2019 format (Save As) | Tested: a test file in each format, names with accents and Chinese characters included. |
  | Saved by 3ds Max 2013 to 2019, 2021 or later, in any format they offer | Expected to work: the same layout as far as seen. Imported whole: a scene saved by 3ds Max 2015 in the 2012 format and one saved by 3ds Max 2020 in the 2018 format. |
  | Saved by 3ds Max 2012 or older | Not verified: no such file has been imported yet. Names are read in the code page the file records, else as UTF-8, else Western (1252); **Text Encoding** (Include) picks another code page (Central European, Cyrillic, Greek, Turkish, Japanese, Chinese, Korean). Checked only on made-up data. |
  | A file with the older `ClassDirectory` stream instead of `ClassDirectory3` | Not supported: it is read as the newer layout, which no file has confirmed; what comes out is not known. |

  Text Encoding changes nothing for a file of 3ds Max 2013 or later: its names are Unicode.
- When a `.max` is dropped, the options popup shows a **File** line: the 3ds Max version, the renderer, the
  number of objects and the unit, read in a fraction of a second even from a large scene; for a file with 8-bit
  names (3ds Max 2012 or older), the code page Auto reads them in.
- A very large scene works but needs time and memory: see [BASELINE.md](BASELINE.md) (the performance budget
  of 1.0.0, and each version since the inherited engine). The two commercial scenes measured there take about 13 s
  and 1.3 GB, and 17 s and 1.2 GB (wall time and peak memory of the whole Blender run).
- **Scene packs**: a `.zip`, `.rar` or `.7z` holding the scene, chosen in *File › Import*; a `.rar` or `.7z` can
  also be dropped (a dropped `.zip` goes to Blender's extension installer). The format is recognised by the file's
  content. The chosen `.max` and the image and `.ies` files it names are unpacked into a folder named after the
  archive, next to it or in the folder set in the preferences, and the scene is imported from there; a pack with
  several scenes asks which one. Everything else in the pack is skipped.
- `.zip` is read by Python's own `zipfile`: stored, Deflate, bzip2 and LZMA entries; not encrypted entries,
  Deflate64 or archives split into parts. File names without the UTF-8 flag are decoded as UTF-8, then GBK,
  Shift-JIS, cp1252, cp437.
- `.rar` (RAR 5; RAR 4 through UnRAR or 7-Zip only) and `.7z` need a program already installed: UnRAR 7.23 or
  newer, 7-Zip 26.02 or newer, or bsdtar 3.8.8 or newer (the `tar` of the system on macOS and Linux is taken
  whatever version it prints). Not readable: password-protected archives and archives split into volumes.
- Limits for one pack: 20,000 entries listed, 5,000 files and 16 GiB written, 4 GiB per file, 15 minutes, and
  512 MiB left free on the disk.

## What comes next

Not imported yet, and not scheduled: V-Ray mesh proxies (`.vrmesh`), the dome light, sky and Skylight as the World,
Corona lights, V-Ray mesh lights, IES distributions, camera exposure, procedural maps drawn as nodes (they are
simplified to the image below them), animation, and the modifiers that still leave an object as its base object
(Edit Poly, Edit Mesh, FFD…). A file of 3ds Max 2012 or older has not been imported yet: tell us in an issue when
one does not open.
