# Standard, Physical and Multi/Sub-Object materials (maxdrop-arp.4) Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `convert/materials.py` converts Standard and Physical Material to a `MaterialIR` and resolves a
Multi/Sub-Object by material ID; a slot plan per mesh tells `build/objects.py` which material slot each face
lands on, and which material each slot holds per object.

**Architecture:** Two more entries in `RULES` (Standard, Physical). `MaterialConverter.material_for(index,
material_id)` resolves wrappers and Multi/Sub-Objects (nested either way) down to one `MaterialIR` or None (an
empty slot). `assign(desc, node_materials, conv)` groups each mesh's distinct face IDs by the tuple of materials
its users get for them: one Blender slot per group, faces remapped with numpy. `build.objects.build(...,
slots=, material=)` applies the plan: indices remapped, slots on the mesh when every user agrees, linked to the
object otherwise; without `slots` the build is unchanged (the operator's old-engine bridge keeps raw IDs until
maxdrop-arp.6 wires the plan in).

**Tech Stack:** Python 3.11 stdlib + numpy (as convert/scene.py), unittest; bpy only in build/.

---

## Facts this plan rests on

- Fixtures: `standard_physical` (FixtureStandard: Blinn, diffuse 171 81 41, specular 231 221 211, level 0.37,
  glossiness 0.23, self-illum amount 0.13, opacity 0.83, ior 1.33, twoSided, diffuse Bitmap at 71 %;
  FixturePhysical: every value channel set, see `tools/fixtures/standard_physical.ms`), `vray_wrappers`
  (FixtureMulti: `materialIDList` stored zero-based `[0, 2, 6]`, `mapEnabled [1, 0, 1]`), `box_poly_standard`
  (FixtureRed diffuse 200 40 30). Every box has face material IDs (zero-based) `[1, 0, 4, 3, 5, 2]`.
- Standard (2, 0): block 0 `shaderType` 0, `twoSided` 2; block 1 `opacity` 1 (fraction), `ior` 6; block 3
  `mapEnables` 0, `maps` 1, `mapAmounts` 2 (tables of 24; values are `Reference`s and fractions).
- Standard map slot index (3ds Max 2020 probe, `3dsmaxbatch`, one map per named slot): 0 ambient, 1 diffuse, 2
  specular color, 3 specular level, 4 glossiness, 5 self-illumination, 6 opacity, 7 filter, 8 bump, 9 reflection,
  10 refraction, 11 displacement.
- Shader part (superclass Shader `0x10B0`, slot 2), block 0, ids per shader ClassID (probe: scenes saved by
  3ds Max 2020 with every shader, read back with reader/materials.py):

  | Shader | ClassID A | diffuse | specular | level | glossiness | SI amount | SI color | use SI color |
  |---|---|---|---|---|---|---|---|---|
  | Phong / Blinn / Metal | 0x37 / 0x38 / 0x39 | 1 | 2 | 9 | 10 | 7 | 8 | 6 |
  | Anisotropic | 0x2857F460 | 1 | 2 | 5 | 7 | 6 | 3 | 14 |
  | Oren-Nayar-Blinn | 0x2857F421 | 1 | 2 | 6 | 5 | 4 | 3 | 13 |
  | Multi-Layer | 0x2857F470 | 1 | 6 | 7 | 8 | 3 | 2 | 19 |
  | Translucent | 0x2857F480 | 1 | 2 | 6 | 5 | 4 | 3 | 14 |

  Strauss 0x2857F450: 0 color, 1 glossiness, 2 metalness. Only Blinn is in a fixture.
- Physical Material block 0 (oracle names): 1 base_weight, 2 base_color, 3 reflectivity, 4 roughness, 5
  roughness_inv, 6 metalness, 10 refl_color, 30 transparency, 31 trans_color, 33 trans_ior, 37 thin_walled, 50
  emission, 51 emit_color, 52 emit_luminance (cd/m²), 60 coating, 61 coat_color, 62 coat_roughness, 63
  coat_roughness_inv, 66 coat_ior; maps 100 base_weight, 101 base_color, 102 reflectivity, 104 roughness, 105
  metalness, 109 transparency, 116 emission, 117 emit_color, 130 bump, 133 cutout, each switched by id + 50;
  230 bump_map_amt (a factor, not percent).
- Gamma: not located in the file. Swatches stay decoded with the sRGB curve (the standard form of display gamma
  2.2, the same curve Blender applies to sRGB textures); `GAMMA_NOTE` says so for the report (maxdrop-arp.8).
  Follow-up debt bead: find the file's gamma.

## Rules

Standard: base = diffuse (map 1); roughness = 1 - glossiness (map 4, inverted); specular = level × mean(linear
specular color) clamped (map 3, else map 2); Metal shader metallic 1, Strauss metallic = metalness; alpha =
opacity (map 6); emission: use-SI-color → that color, strength 1 when not black; else diffuse × amount
(strength = amount); a self-illumination map (5) drives the color at strength 1; ior; two_sided (new IR field);
bump map 8 through `bump_slot`; reflection map 9 enabled with amount a → specular at least a (the map itself is
an environment, not used). Map amounts are the `mapAmounts` fractions; a disabled slot is no map. Unknown shader
→ defaults + an issue.

Physical: base = base_color × base_weight (map 101); glass mix as VRayMtl: t = transparency, base = mix(base,
trans_color, t) (map 109 on transmission); roughness = r or 1 - r with roughness_inv (map 104, inverted with
it); metallic (map 105); specular = reflectivity × mean(refl_color) (map 102); ior = trans_ior; thin_walled;
emission color = emit_color (map 117, else 116), strength = emission × luminance / 683 (cd/m² to W/(m²·sr));
coat weight / color / roughness (inv) / ior; bump 130 amount 230; alpha map 133.

Multi/Sub-Object: entry k has ID `materialIDList[k]` (zero-based; missing list → k), material `materialList[k]`,
switch `mapEnabled[k]`; first entry of an ID wins. `material_for(index, id)`: no index → None; peel wrappers; a
failed peel → the grey IR; a Multi/Sub → its entry for id (absent, switched off or empty → None), resolved again
(nested Multi/Sub uses the same id), at most MAX_PEEL levels with a cycle guard; otherwise `convert()`.
`convert(multi)` = the material of its first enabled entry (for callers without face IDs), grey with an issue
when none; never counted unknown.

Slot plan per mesh (`MeshSlots`: users, slots [[IR or None per user]], indices int32 per face): distinct face
IDs ascending, key = (material_for(user material, id) per user) by identity; one slot per key in order of first
appearance; a key that is all None is the empty slot, dropped when it is the only key (no slot at all).

Build: `make_mesh(md, indices)`; after the objects: per slot, the same material for every user → on the mesh,
else `None` on the mesh and the object's slot linked to `OBJECT` with its own material. `material(ir)` is called
once per Max material object (`built.materials`).

## Tasks

1. Tests first (`tests/unit/test_convert_materials.py`): Standard on standard_physical and box_poly_standard
   (200 40 30 → linear), each shader table row and Strauss on synthetic parts, map slots with amounts and
   switches; Physical on standard_physical (hand-computed), roughness_inv, maps; Multi/Sub: material_for on
   vray_wrappers (ids 0 → SubOne, 2 → None (off), 6 → SubSeven, 1 → None), nested Multi in wrapper and
   wrapper in Multi, cycle/depth, convert(multi); assign(): single material one slot, Multi fixture box →
   `[SubOne, None]` with indices `[1, 0, 1, 1, 1, 1]`, two users with different materials, no material → no slot.
2. Implement in `maxdrop/convert/materials.py`; run tests.
3. `build/objects.py`: `slots`, `material` parameters; `tests/blender/run.py`: `check_material_slots` (Multi box
   with face IDs 1, 3, 7 → slots SubOne, empty, SubSeven; the same mesh shared with the Shell box → object-linked
   slots; the Standard box → one slot).
4. Commit; build-and-test on 4.2.23, 4.5.16, 5.2.

## Verification

**Working directory:** `D:\www\maxdrop`.

1. `python -I -m unittest discover tests` → `OK` (standard_physical IR equals the expectations; box_poly_standard
   base color = linear(200/255, 40/255, 30/255) = (0.577580, 0.021219, 0.012983)).
2. `powershell -ExecutionPolicy Bypass -File build.ps1` → dist zip, index.json, index.html.
3. For each of Blender 5.2, 4.2.23 and 4.5.16 (paths in the bead notes' environment block), with `BLENDER_USER_RESOURCES=<scratch>\profile-<v>`: `--background --factory-startup --python-exit-code 1
   --python tests/blender/run.py` → `FIXTURES PASSED` (includes `material slots: ...` checks),
   `tests/smoke_register.py` → `SMOKE PASSED`, `tests/smoke_import.py` → `IMPORT PASSED`.

**Success criteria:** all pass on the three versions; no commercial name or user path in the diff.
