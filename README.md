# MaxDrop

A free Blender extension that imports 3ds Max `.max` scenes, meshes and materials, **without 3ds Max**: drop the
file onto Blender, or use *File › Import › MaxDrop*. It also takes the `.zip`, `.rar` or `.7z` scene pack the
scene was downloaded as. Blender 4.2 or newer; tested on 4.2 LTS, 4.5 LTS and 5.2 LTS.

> **Stable, not complete.** MaxDrop is a fork of [io_scene_max](https://github.com/nrgsille76/io_scene_max). It
> imports editable meshes with their UVs, smoothing, instances, hierarchy, layers and scene units, the room shell
> (shapes, Extrude, UVW Map), nine of the standard primitives, V-Ray, Corona, Standard and Physical materials with
> their texture maps, and the lights and cameras: a dropped V-Ray interior scene opens through its own camera, lit by
> its own lights. An import shows its progress and Esc cancels it. Most modifiers are not applied yet and some lights
> and maps are simplified.
> [docs/SUPPORT.md](docs/SUPPORT.md) is the honest list.

> **Independent.** Not affiliated with, endorsed by or supported by Autodesk or Chaos. Autodesk and 3ds Max are
> trademarks of Autodesk, Inc.; V-Ray and Corona are trademarks of Chaos.

## What it imports

- **Editable Mesh and Editable Poly** objects: vertices, faces, material IDs, UV channels, smoothing groups (as
  sharp edges), instances as shared meshes.
- **Primitives** (Box, Plane, Pyramid, Sphere, GeoSphere, Cylinder, Cone, Tube, Torus) as the meshes 3ds Max builds
  from their parameters.
- **Shapes** (Line, Editable Spline, Rectangle, Circle, Ellipse, Arc, NGon) as curves, and **Extrude** on a shape as
  the mesh 3ds Max makes of it: walls, floors and ceilings drawn as outlines arrive closed, with their caps.
- **UVW Map** (planar, box, cylindrical, spherical) applied to its map channel, and **TurboSmooth, MeshSmooth, Shell
  and Symmetry** kept as Subdivision Surface, Solidify and Mirror modifiers.
- **Position, rotation, scale and the whole hierarchy**, matched by the file's own object references (two objects
  with the same name stay apart); groups and Dummy helpers become empties.
- **Scene units**: a scene saved in millimeters, centimeters, inches or feet arrives at its real size in meters.
- **Layers** as collections, nested like the layers; hidden, frozen and non-rendering layers and objects keep
  those flags.
- **Materials** as a Principled BSDF with their maps as nodes (tiling, offset, rotation, cropping, Mix, Color
  Correction, Falloff, Composite, normal and bump maps): VRayMtl and the other V-Ray materials and wrappers, Standard, Physical,
  Multi/Sub-Object, CoronaPhysicalMtl, CoronaMtl, CoronaLightMtl and CoronaLayeredMtl.
- **Textures** that are plain image files, next to the `.max` file, in a `maps` or `textures` folder beside it, or
  in folders you add in the preferences.
- **Lights**: V-Ray plane, disc and sphere lights, standard and photometric lights, VRaySun and VRayIES as Blender
  area, point, spot and sun lights, as bright as V-Ray renders them (the import option **Light Strength** scales
  them all).
- **Cameras** (Free, Target, Physical, VRayPhysicalCamera) with 3ds Max's framing; the camera the file renders
  becomes the scene camera and the file's render size Blender's.

Not yet: Corona lights, V-Ray mesh and dome lights, the sky (the World stays as it was), IES distributions, the other
modifiers (Edit Poly, Edit Mesh, FFD, Noise…: the object arrives as it was before them), Teapot, sliced primitives
and hemispheres, other shapes (Star, Text, Helix, Donut…), animation, procedural maps (simplified to the image below
them). See [docs/SUPPORT.md](docs/SUPPORT.md).

## Install

Install it from its repository so Blender can update it later. The install page has the button to drag onto
Blender and every step: **<https://jsiovn.github.io/maxdrop/>**

By drag and drop:

1. With Blender open, drag the button of the install page onto the Blender window.
2. The first time, Blender says the extension comes from an unknown repository: click **Add Repository…**, tick
   **Check for Updates on Startup**, click **Create**.
3. Drag the button onto Blender again and click **OK**. Allow online access if Blender asks.

Or by repository URL:

1. *Edit › Preferences › Get Extensions › Repositories ›* **+** *› Add Remote Repository*.
2. URL `https://jsiovn.github.io/maxdrop/index.json`, tick **Check for Updates on Startup**.
3. Search **MaxDrop** in Get Extensions and click **Install**.

Do not use *Install from Disk*: Blender never updates that copy. If you did, uninstall it and install again as
above.

## Use

1. Drag a `.max` file from your file manager onto the 3D Viewport, or choose *File › Import › MaxDrop (.max,
   .zip, .rar, .7z)*. A scene pack works too: choose its `.zip`, `.rar` or `.7z` in *File › Import*, or drop the
   `.rar` or `.7z` (a `.zip` cannot be dropped, see the FAQ).
2. Check the options:
   - **Scene**: only for a pack that holds several `.max` files. Pick the one to import; the popup also says how
     many texture files come with it and where it will be unpacked.
   - The **File** panel of a dropped `.max` says which 3ds Max saved it, its renderer, how many objects it holds
     and its unit.
   - **Units**: **Auto** takes the unit the scene was saved with; pick Millimeters, Centimeters, Meters, Inches or
     Feet to override it. A file that does not state its unit is imported at one meter per unit, times Scale.
   - **Scale**: an extra factor on top of Units; leave it at `1`.
   - **Image Search** also looks for the textures in the subfolders of the scene's folder.
   - **Object Filter** picks whether materials and UV maps come along; **Forward** and **Up** turn the scene.
   - **Modifiers**: **Keep as Blender Modifiers** turns TurboSmooth, MeshSmooth, Shell and Symmetry into Subdivision
     Surface, Solidify and Mirror; **Ignore** leaves them out.
   - **Light Strength** scales every light (default 1.43: Cycles then renders them as bright as V-Ray).
   - **Keep Targets** aims target cameras and lights at their targets with a Track To constraint, so they follow
     when a target moves; off, they keep the rotation 3ds Max gives them.
   - Every import makes a collection named after the file, with one collection per 3ds Max layer below it.
3. Click **Import**. A large scene takes a while and Blender does not respond until it is done
   ([docs/BASELINE.md](docs/BASELINE.md) has measured times).
4. The status bar sums up the import in one line. The text **MaxDrop Report** in the Text Editor (and the
   system console) lists what arrived and what did not, such as light settings Blender has no place for, and
   what became of the materials: converted by class, wrappers and maps approximated, textures found and the
   ones not found by file name. The report names your scene's objects and files: it stays on your computer. A
   bug report asks for it.

A `.max` file names its texture files but does not contain them. MaxDrop looks for each file name in the scene's
folder, then in `maps` or `textures` folders beside it, then in the **Texture Search Folders** of the add-on
preferences, and last at the path stored in the scene, only when that is on a local drive (never a network path).
A texture that is not found is skipped and the material keeps its color. See
[docs/SUPPORT.md](docs/SUPPORT.md#textures).

### Scene packs

From a `.zip`, `.rar` or `.7z`, MaxDrop writes the chosen `.max` and the pack's image and `.ies` files it uses,
side by side, into a folder named after the archive next to it, then imports the scene from there. Nothing else in
the pack is written, and nothing in it is run. Importing the same pack again uses that folder again; a folder you
extracted yourself next to the archive, named after it, is used as it is. To unpack somewhere else, set **Unpack
Scene Packs Into** in *Preferences › Add-ons › MaxDrop*; that folder is also used when the archive's own folder
cannot be written.

A `.zip` is read by MaxDrop itself. A `.rar` or `.7z` is unpacked by a program already on your computer: UnRAR
(installed with WinRAR), 7-Zip, or a recent bsdtar (the `tar` of an up-to-date Windows 11, and of macOS).
MaxDrop brings none of them and refuses versions with known extraction problems (a bsdtar of macOS or Linux
itself excepted, see [SECURITY.md](SECURITY.md)); without one, extract the archive yourself and import the `.max`.

## Update

With **Check for Updates on Startup** ticked for the repository, Blender offers new versions in *Get Extensions*.
Or press **Check for Updates** in *Preferences › Add-ons › MaxDrop*: a newer version is downloaded and installed
right away.

## FAQ

**Do I need 3ds Max, V-Ray or Corona?** No. MaxDrop reads the `.max` file itself.

**Can I keep io_scene_max installed?** Yes. MaxDrop has its own id, operator and file handler. When both are
enabled and you drop a `.max` file, Blender asks which importer to use: pick **MaxDrop (.max, .rar, .7z)**.

**Can I give it the archive I downloaded?** Yes: choose the `.zip`, `.rar` or `.7z` in *File › Import › MaxDrop*,
or drop a `.rar` or `.7z` onto the 3D Viewport (see *Scene packs* above). A dropped `.zip` opens Blender's own
extension installer instead, because Blender takes every dropped `.zip` for an extension to install before it asks
any importer; it then complains about a missing manifest. Import a `.zip` through *File › Import*.

**The scene arrives at the wrong size.** The file states its unit and **Units: Auto** uses it. If the scene was
modelled in another unit than it was saved with, pick that unit in **Units**; **Scale** is an extra factor.

**Objects are missing or misshapen.** A modifier MaxDrop does not apply (Edit Poly, Edit Mesh, FFD…) leaves the object as it was below it; an object MaxDrop cannot convert arrives
as an empty with its 3ds Max class in the custom property `maxdrop_class`.
The text **MaxDrop Report** (Text Editor) lists them, and what became of the materials.

**Which 3ds Max versions?** MaxDrop's own test files are saved by 3ds Max 2020, also in the 2017, 2018 and 2019
formats, and scenes of 3ds Max 2015 and 2020 have been imported; files of 3ds Max 2013 and later are expected to
work. A file of 3ds Max 2012 or older has not been tried yet: **Text Encoding** picks the code page of its names.
The table in [docs/SUPPORT.md](docs/SUPPORT.md#files) has the details. Tell us in an issue when a file does not open.

**Can it export `.max`?** No, and that is not planned.

## Privacy

The importer reads the file you give it and the textures beside it, on your computer; from a scene pack it writes
the scene and its maps into a folder next to the archive (or the folder you chose). The add-on goes online for
one thing only, when you press **Check for Updates**: it reads the version list on `jsiovn.github.io`. No
telemetry, no account.

## Credits

MaxDrop is a fork of **[io_scene_max](https://github.com/nrgsille76/io_scene_max)** ("Import Autodesk MAX") by
**Sebastian Schrand**, taken at version 1.9.2 (`git describe --tags`: `v1.9.2`, commit
`37db107126f956f7219152671443080360565691`). That importer builds on
**[Importer3D](https://github.com/jmplonka/Importer3D)** by **Jens M. Plonka** (the FreeCAD 3ds Max importer) and
on **[olefile](https://github.com/decalage2/olefile)** by **Philippe Lagadec**. Reading `.max` files without
3ds Max is their work; this repository keeps the complete upstream history, and the upstream copyright lines stay
in the files and in the manifest.

It is a separate project rather than a pull request because it is heading somewhere else: whole V-Ray and Corona
interior scenes, with their room, lights and cameras. Fixes that make sense for io_scene_max are welcome there
too.

## Develop

```powershell
python -I -m unittest discover tests                  # the tools, the landing page, the license files: no Blender
python -I tools/lint.py                               # ruff, at the version CI runs (CONTRIBUTING.md)
powershell -ExecutionPolicy Bypass -File build.ps1    # dist\: the zip, index.json and the landing page

# Inside Blender, headless, with a profile of its own so your preferences are never touched:
$env:BLENDER_USER_RESOURCES = "$env:TEMP\maxdrop-profile"
& blender --background --factory-startup --python-exit-code 1 --python tests\smoke_register.py
& blender --background --factory-startup --python-exit-code 1 --python tests\smoke_import.py -- <a .max file>
```

To try an install or an update, serve `dist\` (`python -m http.server --directory dist`) and add
`http://127.0.0.1:8000/index.json` as a remote repository. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Release

1. Bump `version` in `maxdrop/blender_manifest.toml`.
2. Add a `## [x.y.z] - YYYY-MM-DD` section to `CHANGELOG.md`.
3. Push to `main`. The **Publish** workflow runs the tests, builds the zip, deploys the repository index and the
   landing page to GitHub Pages and creates release `v<x.y.z>`. A push without a version bump publishes nothing.

A change to the landing page alone (`site/`) ships by running the **Publish** workflow by hand with **redeploy**
ticked: it republishes the released zip with the new page.

One-time owner setup (enables Pages with the Actions source):

```bash
gh api repos/jsiovn/maxdrop/pages -X POST -f build_type=workflow
```

## License

Copyright © 2023-2026 Sebastian Schrand, 2017-2022 Jens M. Plonka, 2005-2018 Philippe Lagadec, 2026 jsiovn.

MaxDrop is free software: you can redistribute it and/or modify it under the terms of the
[GNU General Public License](LICENSE) as published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version (`GPL-3.0-or-later`). The files that come from io_scene_max say
`GPL-2.0-or-later` in their headers, which allows exactly that.

It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details. Its
text is [`LICENSE`](LICENSE), and it is inside the extension zip as well.
