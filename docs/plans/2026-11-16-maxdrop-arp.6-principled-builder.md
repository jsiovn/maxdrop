# Principled node builder Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn each MaterialIR (convert/materials.py) and its TextureGraphIRs (convert/texmaps.py) into a Blender
material that renders the same on Blender 4.2, 4.5 and 5.2, wire it into the operator, and delete the upstream
engine (`maxdrop/import_max.py`), whose last live code was the material bridge.

**Architecture:** `maxdrop/build/materials.py` holds a `MaterialBuilder`: `make(ir)` makes one material per IR
(build/objects.py already calls it once per Max material index), a Principled BSDF fed by sockets looked up by name
with an existence check, the texture graphs drawn as nodes (Image Texture + Mapping + UV Map, Invert, Mix, Multiply,
Hue/Saturation, Bright/Contrast, Gamma, Normal Map, Bump), images reused per (file, color space). Missing textures
and sockets skipped on this Blender become `(label, reason)` lines that the operator appends to the import report.
The operator converts the materials inside the reader's `with` block (`MaterialConverter` + `TexmapConverter` +
`TextureIndex` + `assign`) and passes the slots and `builder.make` to `build_objects.build`.

**Tech Stack:** Blender Python API (bpy, mathutils) in build/ only; plain Python convert/ and reader/.

---

## Decisions (verified against the three Blender versions with a probe script)

- Principled socket names = identifiers on 4.2.23, 4.5.16, 5.2.0. `Thin Wall` exists only in 5.2, `Diffuse
  Roughness` from 4.5. Utility node inputs differ by name (`Fac` / `Factor`, `Bright` / `Brightness`): those are
  looked up by **identifier** (`Fac`, `Bright`, `A_Color`, `Factor_Float`, `Result_Color`, ...), identical on all three.
- `Material.use_nodes` is False after `materials.new` on 4.x and True on 5.2: a helper in `compat.py` turns the node
  tree on only when needed (CLAUDE.md: any version difference goes there).
- IR -> sockets: Base Color, Metallic, Roughness, IOR, Alpha, Normal, `Specular IOR Level` = 0.5 x specular (the IR's
  specular is a reflection weight, 1 = full Fresnel reflection at the IOR = Blender's 0.5), `Transmission Weight`,
  `Emission Color` + `Emission Strength`, `Coat Weight / Roughness / IOR / Tint`, `Subsurface Weight`, `Subsurface
  Radius` = subsurface color, `Subsurface Scale` = radius (m), `Thin Wall` when thin_walled (missing socket -> skipped +
  report line). A COLOR graph on a float socket (specular, transmission) goes through Vector Math Dot Product with
  (k, k, k): k = 1/3 (the mean, the measure materials.py uses), 1/6 for the specular (mean x 0.5).
- Alpha: `surface_render_method` only: `BLENDED` for a constant alpha below 1, `DITHERED` (Blender's default) for an
  alpha map. `blend_method` and `shadow_method` are never touched.
- Bitmap placement (3ds Max StdUVGen convention, scaled and rotated about the map's center, offset in UV fractions):
  `sample = R(u, v, w angles) * S(tiling) * (uv - 0.5 - offset) + 0.5`, as a Mapping node (POINT): Scale = tiling,
  Rotation = (u, v, w) angles, Location = (0.5, 0.5, 0) - R S (0.5 + offset_u, 0.5 + offset_v, 0). No Mapping node
  for the identity. Crop: Vector Math Fraction then a Mapping POINT (crop) or TEXTURE (place, image CLIP). The sign
  convention is checked against 3ds Max by the A/B render of the M2 gate (maxdrop-arp.9).
- Extension: both axes tile -> REPEAT, any mirror -> MIRROR, any tile -> REPEAT, else CLIP.
- Map channel 1 -> the UV coordinates (Texture Coordinate UV); another channel -> UV Map node named as
  convert/scene.py names the layer (`UVChannel_<n>`).
- Image: `bpy.data.images.load(path, check_existing=False)`, one datablock per (normalized path, color space),
  colorspace_settings.name = the IR's (`sRGB` / `Non-Color`); a gamma override on a COLOR input that made the image
  Non-Color adds a Gamma node with that gamma. Not found -> the Image Texture node without an image and a report line
  `texture not found: <file>`; a load error -> `texture not loaded: <file> (<error>)`.
- TexOutput: Invert, then Vector Math Multiply Add (level, offset), then Scale (amount), only the parts that change.
- ColorCorrect: Hue/Saturation/Value (hue 0.5 + turns), Bright/Contrast, a gain Scale, Gamma 1 / gamma.
- Composite: layers bottom first, each a Mix over the result with factor = opacity (x the image's alpha for an image).
- Normal map: Normal Map node (tangent, its strength, its UV map), red/green flip and swap through Separate /
  Combine Color and 1 - x; its additional bump a Bump node (Height, Strength = min(1, s), Distance = max(1, s)) fed by
  the normal map's output.
- One material per Max material index (build/objects.py); names kept, Blender suffixes a clash (`.001`), so two
  different Max materials with one name both stay. Unknown classes: their grey IR, named.
- Viewport display: `diffuse_color`, `metallic`, `roughness` from the IR.

## Files

- Create: `maxdrop/build/materials.py` (builder)
- Modify: `maxdrop/compat.py` (node tree on), `maxdrop/ops.py` (pipeline, drop `_materials`), `maxdrop/__init__.py`
  (comment), `maxdrop/build/objects.py` (docstring), `tests/blender/run.py`, `tests/smoke_register.py`,
  `tests/smoke_import.py`, `CLAUDE.md`, `CONTRIBUTING.md`, `pyproject.toml` (ruff exclude of the deleted file),
  `docs/SUPPORT.md`, `CHANGELOG.md`, `README.md` (materials line: stays true)
- Delete: `maxdrop/import_max.py` (only the material bridge was live)
- `tools/baseline_import.py`: already uses the new reader only, no change.

### Task 1: build/materials.py

- [ ] Write `MaterialBuilder` (decisions above), `uv_transform(mapping) -> (location, rotation, scale)`, `issues()`.
- [ ] `compat.material_node_tree(mat)`.

### Task 2: operator

- [ ] In `_import_scene`, with 'MATERIAL' on: inside the `with` block build `MaterialGraph`, `AssetTable.from_file`,
  `TextureIndex(max_path, prefs.texture_dirs(context), scene_subfolders=use_image_search)`, `TexmapConverter`,
  `MaterialConverter`, `slots = assign(desc, node_materials(sc, desc), conv)`; drop the converters before the build.
- [ ] `build_objects.build(..., slots=slots, material=builder.make)`; the materials line counts `built.materials`;
  `rep.issues.extend(builder.issues())` before publishing. Delete `_materials` and the import of import_max.

### Task 3: delete the engine

- [ ] `git rm maxdrop/import_max.py`; drop it from pyproject's ruff exclude, `__init__._purge`'s comment, CLAUDE.md,
  CONTRIBUTING.md; the register smoke checks `maxdrop.build` instead of the engine for the lazy-load / purge check.

### Task 4: tests

- [ ] run.py: every mesh gets a material (no more old-engine gaps); per fixture, every material's Principled inputs
  equal the IR converted from the same file (values, linked or not); vray_maps and texmap_rules images by file name,
  color space and Mapping values (hand-computed from the formula); a synthetic part with hand-made IRs: one file in
  two color spaces -> two images, twice in one -> one; a missing file -> node without image + report line; a found
  file loads; Thin Wall set on 5.2, skipped with a line on 4.x; name clash keeps both; BLENDED / DITHERED.
- [ ] smoke_import: a fixture's summary is INFO "nothing left out", or WARNING when every listed issue is a missing
  texture (the fixtures carry no image files).

### Task 5: docs

- [ ] SUPPORT.md Materials / Textures sections, CHANGELOG [Unreleased], README materials line.

## Verification

Environment (machine paths from the bead notes, never committed): `$S` = session scratchpad, `B52` = installed
5.2, `B42` / `B45` = portable 4.2.23 / 4.5.16. Every Blender run headless with `BLENDER_USER_RESOURCES=$S\profile-<tag>`.

1. `python -I -m unittest discover tests` -> `OK`.
2. `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...maxdrop-<version>.zip ...`.
3. On each of B52, B42, B45:
   - `& $B --background --factory-startup --python-exit-code 1 --python tests\smoke_register.py` -> `SMOKE PASSED`
   - `& $B --background --factory-startup --python-exit-code 1 --python tests\smoke_import.py` -> `IMPORT PASSED`
   - `& $B --background --factory-startup --python-exit-code 1 --python tests\blender\run.py` -> `FIXTURES PASSED`
4. Render check (scratch script `$S\render_check.py`, not committed): import vray_maps.max as it is and a copy in
   `$S` with generated PNGs of every texture name, set EEVEE (`BLENDER_EEVEE_NEXT` on 4.x, `BLENDER_EEVEE` on 5.x),
   a camera framing the objects, a sun, render 64 x 64, read the pixels: mean not black (> 0.02) and not magenta
   (not r and b > 0.4 with g < r / 3) -> `RENDER PASSED` on all three versions.
5. Ruff (`uvx ruff@0.17.5 check .`, the version the workflow pins) -> no error, when uvx can fetch it.

Success: all of the above green on all three versions; failures fail the bead.
