# What MaxDrop imports

**This page describes version 0.0.1.** It is the first release of the fork and converts exactly what
[io_scene_max](https://github.com/nrgsille76/io_scene_max) 1.9.2 converts: the engine (`maxdrop/import_max.py`)
is that importer's, unchanged.

How far to trust the list: it says what the code does. Checked against 3ds Max so far, on MaxDrop's own test
file, are an Editable Poly object, its first UV channel, its transform and a Standard material. Everything else
is read from the code and has not been compared with 3ds Max yet. The page is updated with every version.

"Not yet" means the importer skips it. Part of what is skipped is named in the system console (on Windows:
*Window › Toggle System Console*).

## Objects

| In the `.max` file | Version 0.0.1 |
|---|---|
| Editable Poly, Editable Mesh | **Imported**: vertices, faces (polygons stay polygons), material IDs |
| UV channels of those meshes | **Imported**, one UV layer per channel found (`UVMap`, `UVMap_1`, …) |
| Box, Sphere, Cylinder, Cone, Torus, Plane | **Imported** as Blender primitives of the same size, not as the 3ds Max mesh: segments and UVs are Blender's |
| Dummy helper | **Imported** as an empty |
| Biped object | **Imported** as an empty; no armature |
| Object with modifiers | **Base object only**: the stack is not evaluated, so Extrude, UVW Map, TurboSmooth, Shell, Symmetry, Edit Poly and the others have no effect |
| Boolean compound object | Its operands |
| Line, Rectangle, Ellipse, Circle, NURBS surface | Not yet (named in the console) |
| Standard lights, V-Ray lights, sky | Not yet (named in the console) |
| Cameras and their targets | Not yet (named in the console) |
| Bones, particle systems, point helpers | Not yet (named in the console) |
| Everything else: other lights, hair, proxies (`.vrmesh`, Corona proxy), XRefs… | Not yet, skipped without a message |

## Scene structure

| | Version 0.0.1 |
|---|---|
| Position, rotation, scale | **Imported** as static values of a Position / Rotation / Scale controller (Position XYZ, Bezier, TCB, Euler XYZ, the first entry of a list controller). Pivot offsets are applied to meshes. An object driven by another controller (LookAt, constraints…) arrives untransformed |
| Parent and child | **Imported**, matched by object name: two objects with the same name can end up under the wrong parent |
| Scene units | Not yet: one 3ds Max unit becomes one Blender unit, a meter. Set **Scale** when importing (`0.001` for millimeters, `0.01` for centimeters, `0.0254` for inches) |
| Instances | Imported as separate copies of the mesh, not as shared mesh data |
| Smoothing groups | Not yet: every mesh arrives flat-shaded |
| Layers, groups, selection sets | Not yet (the **Collection** option puts everything into one new collection) |
| Hidden and renderable flags | Not yet |
| Animation | Not yet |

## Materials

A material becomes a Principled BSDF through Blender's `PrincipledBSDFWrapper`. Values are copied as they are
stored in the file: colors are not converted between 3ds Max's and Blender's color spaces.

| Material | Version 0.0.1 |
|---|---|
| Standard, Physical Material | **Imported** |
| VRayMtl | **Imported** |
| CoronaMtl, CoronaPhysicalMtl, Corona Skin and Hair | **Imported**; parameters are read by their position in the file, so a Corona version that stores them differently gives wrong values |
| Arnold Standard Surface | **Imported** |
| Raytrace, Architectural | **Imported**, colors and a few values only |
| Multi/Sub-Object | **Imported**: each sub-material becomes a material slot, faces keep their material ID |
| VRay2SidedMtl, Shellac, CoronaLayeredMtl | Their sub-materials, as slots |
| VRayLightMtl, VRayFastSSS2, VRayCarPaintMtl, VRayBlendMtl, other wrappers and every other material | Not yet: the object gets no material from it |

| Channel | Version 0.0.1 |
|---|---|
| Base color, roughness, metallic, IOR, opacity (alpha), specular level and tint | **Imported** as plain values |
| Emission | The color only; its strength stays at Blender's default |
| Image textures | **One Bitmap per channel**, for base color, roughness, specular tint, normal (with its strength) and opacity, when the Bitmap is plugged straight into the material |
| Tiling, offset, rotation and cropping of a Bitmap | Not yet |
| Color Correction, Falloff, Mix, Composite, VRayColor, VRayDirt, noise and every other procedural or nested map | Not yet: the channel keeps its plain value |
| Bump (height) maps, displacement | Not yet |

## Textures

A `.max` file stores the paths of its texture files, not the images. Version 0.0.1 takes only the **file name**
of each path and looks for it in the folder of the `.max` file, and with **Image Search** on in its subfolders.
A file that is not found is skipped; the material keeps its plain color. The texture search folders of the
add-on preferences are stored but not used by this version.

## Files

- `.max` files as 3ds Max writes them (OLE compound files). A scene whose streams 3ds Max compressed is only
  partly supported.
- MaxDrop's own test file comes from 3ds Max 2020. The reader inherited from io_scene_max is written for many
  versions, which this project has not verified one by one yet.
- A very large scene works but needs time and memory: see [BASELINE.md](BASELINE.md).

## What comes next

In this order: a reader that loads whole scenes (units, instances, smoothing groups, layers, every node), the
material and texture-map conversion for V-Ray, Corona, Standard and Physical materials, room shells (splines,
Extrude, UVW Map), then lights and cameras.
