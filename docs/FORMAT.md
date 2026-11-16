# The .max format, as far as MaxDrop has verified it

What MaxDrop's reader (`maxdrop/reader/`) relies on, written down only once a committed fixture shows it. Each fact
names the fixture (`tests/fixtures/<name>.max`, whose 3ds Max oracle is `<name>.oracle.json`, see
[ORACLE.md](ORACLE.md)); the tests named here keep the facts true. Every fixture was saved by 3ds Max 2020 (file
version 22000). What only other files have shown is listed under [Open](#open), not here.

## Chunks

- A chunk is a `u16` id and a `u32` size that counts the 6-byte header; bit 31 of the size marks a container,
  whose payload is more chunks. Every chunked stream of every fixture (`Scene`, `ClassDirectory3`,
  `DllDirectory`, `Config`, `ClassData`, `VideoPostQueue`) indexes to the bottom with this rule
  (`tests/unit/test_chunks.py`).
- Strings are UTF-16LE without a terminator (node names: `0x0962`, below).

## Class directory

- `ClassDirectory3` holds one `0x2040` container per class: `0x2060` = `i32` dll index, `u32` classA, `u32`
  classB, `u32` superclass; `0x2042` = the class name. The class index counts the `0x2040` entries from 0.
  box_poly_standard: Editable Poly = `(0x1BF8338D, 0x192F6098)`, superclass `0x10`, `epoly.dlo`
  (`tests/unit/test_classdir.py`).
- A ClassID is unique only with its superclass: Standard (material, `0xC00`) and RootNode (`0x1`) are both
  `(2, 0)` in every fixture.

## Scene stream: the object index

- The `Scene` stream is one top-level container, id `0x2025` in every fixture. Its children are the objects of
  the scene: the **object index** is a child's position, the child's chunk id is its **class index** into the
  class directory. Every child id of every fixture is a valid class index (`test_classdir.py`,
  `tests/unit/test_scene.py`).
- Most objects are containers. Two per fixture are empty leaf chunks (TVNode and Reaction Manager in
  hierarchy): they hold no references.

## References

An object points to others by object index.

- `0x2034`: an `i32` array; the position is the reference slot, `-1` an empty slot. ViewportManager in
  hierarchy: `[0, -1]`; a node's Position/Rotation/Scale: three entries in every fixture, its Editable Poly two,
  the Editable Mesh of editable_mesh one.
- `0x2035`: a `u32`, then `(u32 slot, i32 index)` pairs. The first value is the number of reference slots: 16
  for Node and RootNode, 48 for Texmaps and 2 for Bezier Float, Bezier Scale, Bezier Color, Boolean Controller and
  Grid Reference in every fixture (and for the point class of Custom Curve Control, nameless in the class directory:
  texmap_rules' Falloff curves), 34 for VRayMtl (vray_basic, vray_maps, vray_wrappers: what the SDK's
  `NumRefs` reports for a VRayMtl), and for a ParamBlock2 the number of its reference slots (25 and 37 in
  standard_physical and vray_wrappers; 37 for the VRayBlendMtl block, see [Parameter blocks](#parameter-blocks)).
  Every pair's slot is below it (`test_scene.py`). The reader does not need it. RootNode and the controllers have
  no pairs.

## Nodes

A node is an object of class `(1, 0)` with superclass `0x1` (Node); the scene root is the one object of class
`(2, 0)` with superclass `0x1` (RootNode). The oracle's node count equals the number of Node objects in every
fixture.

| Chunk | Content | Shown by |
|---|---|---|
| `0x0962` | node name | every fixture; hierarchy has two nodes named `FixtureTwin` |
| `0x0960` | `i32` parent object index, `u32` flags | every fixture; a top-level node's parent is the RootNode |
| `0x099C` | `u32`, bit `0x8000` = renderable | layers_flags, below |
| `0x096A` | 3 x `f32` object offset position | hierarchy: `[5, 5, 0]` for FixtureRoot and FixtureChild = oracle `offset_pos` |
| `0x096B` | 4 x `f32` object offset rotation | every fixture: `[0, 0, 0, 1]` = oracle `offset_rot` |
| `0x096C` | 7 x `f32`: object offset scale (3), then a scale axis rotation (4) | every fixture: `[1, 1, 1]`, `[0, 0, 0, 1]` |
| `0x2035` | slots 0, 1, 3, 6 | below |

Reference slots of a node, checked on every node of every fixture (`test_scene.py`):

- slot 0: the transform controller, a Position/Rotation/Scale (`(0x2005, 0)`, superclass `0x9008`);
- slot 1: the object. With no modifier it is the base object, whose ClassID and superclass equal the oracle's
  `base_class_id` and `base_superclass`. Nodes that share their slot-1 object are exactly the oracle's
  `instances` (instances: three instances share the source's object, the copy has its own);
- slot 3: the material, present exactly when the oracle names one (the group head of layers_flags has no
  material and three pairs instead of four);
- slot 6: the layer, a Base Layer (superclass `0x10F0`).

Flags in `0x0960` seen so far: `0x800` on most nodes, `0` on the three instances and the copy in instances (the
source has `0x800`), `0x100800` on the hidden node of layers_flags, `0x40` on its group head and `0x900` on the
two group members (`test_scene.py`, `test_flags_and_pair_heads`, which also checks the first `0x2035` values
above). Decoded from layers_flags:

| Bit | Meaning |
|---|---|
| `0x100000` | hidden (FixtureHidden; that node also has an empty `0x0975` chunk) |
| `0x40` | group head (FixtureGroup, a Dummy whose children are the members) |
| `0x100` | group member (FixtureGroupA and FixtureGroupB) |

`0x800` is not decoded. Renderable is not in `0x0960` (FixtureNoRender has `0x800`) but in `0x099C`, a `u32` on
every node of every fixture: `0x0F00D600` on each node, `0x0F005600` on FixtureNoRender, so bit `0x8000` is
renderable. `test_scene.py` checks every node's hidden, frozen and renderable flags against the oracle.

## Layers

A layer is an object of class Base Layer `(0x7E9858FE, 0x1DBA1DF0)`, superclass `0x10F0`; a node's slot 6 points
to it. layers_flags has three (`0`, FixtureLayerA, FixtureLayerB), the other fixtures one (`0`):

| Chunk | Content | Shown by |
|---|---|---|
| `0x1010` | the layer name, 8-bit, no terminator | layers_flags: `46 69 78 ...` (`FixtureLayerA`), `30` (`0`) |
| `0x1020` | `u32` flags | `0` on every layer of every fixture (none is hidden or frozen) |
| `0x1050` | `u32` | `0x0B00D600` on every layer (all render): the layout of a node's `0x099C` |
| `0x1090` | `u8` | `0` on every layer (none has a parent layer) |

The one Layer Manager `(0x0D7374FC, 0x51FF028E)`, superclass `0x200`, references the layers in `0x2034`: slot 0
is layer `0`, then FixtureLayerA and FixtureLayerB, the order of the oracle's `layers` (`test_scene.py` checks
names, order and flags of every fixture's layers against the oracle).

## Hierarchy

- Parents are object indices, so nodes with the same name stay apart: in hierarchy one `FixtureTwin` is a
  child of FixtureRoot and the other is top level.
- The oracle lists nodes pre-order from the root, children in 3ds Max's order. On every fixture that equals a
  pre-order walk with each node's children sorted by object index. In layers_flags the group head has a higher
  node handle (6) than its members (4, 5) but a lower object index, and comes first in both orders.

## Transform controllers

`maxdrop/reader/controllers.py` turns a node's slot-0 controller into matrices at frame 0;
`tests/unit/test_controllers.py` checks every node of every fixture against the oracle's `transform` and
`object_transform` (within 1e-4, per element).

- Matrices are in Max's row-vector convention: a point times the matrix, row 4 = translation, `A * B` applies `A`
  first; this is the oracle's 12-float layout.
- Every fixture node's controller is a Position/Rotation/Scale `(0x2005, 0)` with reference slots 0 = Position XYZ
  `(0x118F7E02, 0xFFEE238A)`, 1 = Euler XYZ `(0x2012, 0)`, 2 = Bezier Scale `(0x2010, 0)`. Position XYZ and Euler
  XYZ reference three Bezier Float `(0x2007, 0)` in slots 0, 1, 2 (x, y, z).
- A Bezier Float's value is an `f32` in `0x2501`, inside a `0x7127` container in every fixture.
- Euler angles are radians. Euler XYZ has `0x1003` = `i32` 0 in every fixture (the axis order; 0 = XYZ).
  hierarchy: FixtureRoot's Z angle `0.5236` gives row 1 = `[0.866025, 0.5, 0]`, a standard row-vector rotation.
- Bezier Scale holds `0x2505`: 3 x `f32` scale, then the scale axis as a 4 x `f32` quaternion. hierarchy:
  FixtureLeaf (`scale = [-1,1,1]` in the script) stores `[-1, -1, -1]`; with that, the oracle's rotation rows
  (`[-0.866025, -0.5, 0]`, ..., `[0, 0, -1]`) come out exactly.
- Local = scale * rotation * position; world = local * parent world, up the whole chain. hierarchy: FixtureLeaf
  (position `[25, 5, 0]` under FixtureChild under the rotated FixtureRoot) lands on `[40.1314, 26.8301, 0]`.
- Object offset = scale (`0x096C`, along its axis) * rotation (`0x096B`) * position (`0x096A`); the object's world
  transform = offset * world. hierarchy: FixtureRoot and FixtureChild (offset `[5, 5, 0]`) match the oracle's
  `object_transform`.

## Geometry

`maxdrop/reader/geometry.py` reads an Editable Mesh or Editable Poly base object into arrays;
`tests/unit/test_geometry.py` checks every fixture's vertex and face counts against the oracle's `base_verts` and
`base_faces`, and the smoothing groups, material IDs and map channels against the fixture scripts. Both classes keep
their mesh in a `0x08FE` container. Counts are `u32`, indices `u32`, coordinates `f32`; material IDs are stored
zero-based (3ds Max shows ID 1 for 0), smoothing groups as a bit set (bit 0 = group 1).

Editable Mesh `(0xE44F10B3, 0)` (editable_mesh: 8 vertices, 12 triangles):

| Chunk | Content |
|---|---|
| `0x0914` | count, then 3 x `f32` per vertex |
| `0x0912` | count, then 20 bytes per triangle: 3 vertex indices, smoothing groups, flags. The flags' high 16 bits are the material ID: editable_mesh has 0, 0, 0, 0, 1, 1, 2, 2, 1, 1, 2, 2 (Max IDs 1-3 as the script sets them); its low bits are `0x3` there |
| `0x0959` | `i32` map channel; its `0x2394` and `0x2396` follow (editable_mesh: channel 1, after `0x2398` = 1) |
| `0x2394` | map vertices: count, then 3 x `f32` (editable_mesh: 12) |
| `0x2396` | map faces: count (= the face count), then 3 map vertex indices per face |

editable_mesh: smoothing groups `1` on faces 1-4 (bottom and top) and `2` on the sides, as the script sets them.

Editable Poly `(0x1BF8338D, 0x192F6098)` (box_poly_standard, multi_uv and the boxes of every other fixture: 8
vertices, 6 quads):

| Chunk | Content |
|---|---|
| `0x0100` | count, then per vertex `u32` flags + 3 x `f32` (16 bytes; flags `0` in every fixture) |
| `0x010A` | edges: count, then `u32` flags + 2 vertex indices (12 bytes); not needed for the mesh, not read |
| `0x011A` | faces: count, then per face a variable record, below |
| `0x0120` | number of map channels, unused ones included: box_poly_standard `2` (channel 1 only), multi_uv `4` (channels 1, 2, 3), `0` in hierarchy and layers_flags (no channel) |
| `0x0124` | `i32` map channel; its `0x0128` and `0x012B` follow |
| `0x0128` | map vertices: count, then 3 x `f32` (box_poly_standard: 24 in channel 1; multi_uv: 12, 8, 13 in channels 1, 2, 3) |
| `0x012B` | map faces, no count: per face of `0x011A` a `u32` degree and that many map vertex indices |

A face record of `0x011A`: `u32` degree, the vertex indices, a `u16` field mask, then each field the mask names, in
this order:

| Mask bit | Field | Shown by |
|---|---|---|
| `0x08` | `u16` material ID | every box: `1, -, 4, 3, 5, 2` = Max IDs 2, 1, 5, 4, 6, 3 (bottom, top, front, right, back, left: a Box's own IDs); absent on the top, whose ID is 1 |
| `0x10` | `u32` smoothing groups | every box: `2, 4, 8, 16, 32, 64`, one group per side |
| `0x20` | `2 * (degree - 3)` x `u32`: the triangulation diagonals, as vertex positions within the face | every quad: `[0, 2]`, in multi_uv `[2, 0]` |

A field whose value is zero is left out: the top of every box has mask `0x30`, the other faces `0x38`.

## System unit

`maxdrop/reader/units.py` reads it; `tests/unit/test_units.py` checks every fixture against the oracle's
`units.system_type`. Found with `tools/maxdiff.py` on units_mm, units_cm and units_in, which differ only in the
system unit: of the Scene stream, only one leaf holds the setting itself.

- The Scene stream has one object of class Scene `(0x2222, 0)`, superclass `0x100`. Its `0x8520` chunk is an
  `i32` unit type and an `f32` scale: units_mm `3`, units_cm `4`, units_in `0`, every other fixture `3`; the
  scale is `1.0` in all of them (the oracle's `system_scale`). 1 system unit = scale x the unit type.
- The unit types are those of the 3ds Max SDK: 0 inches, 1 feet, 2 miles, 3 millimeters, 4 centimeters,
  5 meters, 6 kilometers. Inches, millimeters and centimeters are what the fixtures show.
- What also changes with the unit, and is not the setting: grid and snap values in `Config`
  (`0x21A0/0x1A02/0x100E` entries), two `0x100E` parameter entries of another object of the Scene stream, and
  the viewports (`0x0015`): values measured in system units.
- Corpus scenes A and B (Max 2015 and 2020): `3`, scale `1.0` (millimeters).

## Scene gamma

`maxdrop/reader/gamma.py` reads it; `tests/unit/test_gamma.py` checks every fixture. Found with `tools/maxdiff.py`
on probe scenes saved by 3ds Max 2020 (a box; the same scene saved again; then one Gamma/LUT setting changed per
file: gamma off, display gamma 1.8 and 1.0, file input gamma 1.0, file output gamma 1.0, LUT mode, the color
picker and Material Editor switches off).

- The Scene stream has one object of class RenderEnvironment `(0xEE448B23, 0)`, superclass `0x1010`. Its `0x6010`
  chunk is a `u32` (1: gamma on, 0: off), then two `f32`: the file input gamma and the file output gamma. Every
  fixture: `0`, `2.2`, `2.2` (saved with the gamma off), but gamma_swatches: `1`, `2.2`, `2.2`. The probes: off
  `0`; input gamma 1.0 changes the first `f32`, output gamma 1.0 the second.
- The display gamma and the two switches are not in the file: those probes differ from the first save only in the
  thumbnail. LUT mode left the Scene chunk at `1` (`Config` `0x2160/0x0100`, which otherwise repeats the 12 bytes,
  said `0`); MaxDrop reads the Scene stream.
- What it means for a swatch, measured with V-Ray 5.2 renders of a VRayLightMtl plane (multiplier 1) beside a
  Bitmap of a 128 grey sRGB JPEG: gamma on, the 128 swatch renders byte 187 (0.502 linear) and the JPEG 128; gamma
  off, both 128. The rule is in `maxdrop/convert/colors.py`.
- Corpus scenes A (saved as 3ds Max 2012) and B: the same chunk and layout; A `0`, B `1`.

## Summary properties

`maxdrop/reader/metadata.py` reads them; `tests/unit/test_metadata.py` checks every fixture against its oracle.

- `\x05DocumentSummaryInformation` is an OLE property set ([MS-OLEPS]) of code page 65001 in every fixture. Its
  section `D5CDD502-2E9C-101B-9397-08002B2CF9AE` holds the heading pairs (property 12: a vector of variants, a
  heading string then an `i4` count) that cut the document parts (property 13: a vector of strings) into groups:

  | Group | Parts (box_poly_standard) |
  |---|---|
  | General | `3ds Max Version: 22.00`, `Uncompressed`, `Build: 22.2.0.2176`, `Saved As Version: 22.00` |
  | Mesh Totals | `Vertices: 8`, `Faces: 6` (the sum of the oracle's `base_verts` in every fixture) |
  | Scene Totals | `Objects`, `Shapes`, `Lights`, `Cameras`, `Helpers`, `Space Warps`, `Total` (`Total` = the oracle's `node_count`: layers_flags has 5 objects and 1 helper, its group head) |
  | External Dependencies | file paths (none in the fixtures) |
  | Objects, Materials | node and material names (Materials: as many as the oracle's materials) |
  | Used Plug-Ins | DLL file names (`epoly.dlo`, `ctrl.dlc`, ...) |
  | Render Data | `User Name=`, `Computer Name=`, render size and aspect, `Renderer ClassIDA=1`, `Renderer ClassIDB=0` (the oracle's renderer class), `Renderer Name=Scanline Renderer`, animation range, flags |

- `3ds Max Version` 22 is 3ds Max 2020 (the oracle's `max_version`); the release year is the major version + 1998
  from version 10 (3ds Max 2008) on. Corpus scene A: `17.00` saved as `14.00`, scene B: `22.00` saved as `20.00`.
- `\x05SummaryInformation` holds the thumbnail (property 17), the dates, the last author (8) and property 34,
  both the user name, and a revision. The reader takes nothing from it.
- The user and computer name (Render Data, the author fields), the names and the paths are never returned by the
  reader; the fixtures hold them blanked (`tools/sanitize_fixture.py`).

## Parameter blocks

`maxdrop/reader/pblock.py` reads them; `tests/unit/test_materials.py` (RAW-PARAM PARITY) checks every stored
parameter of every block of every material and map in every fixture against the oracle's `material_graph`, by
parameter id, within 1e-5 (relative above 1): 193 values in vray_basic, 637 in vray_maps, 2,024 in vray_wrappers,
295 in standard_physical. `tests/unit/test_pblock.py` covers each rule on synthetic bytes.

A ParamBlock2 is an object of class `(0x82, 0)`, superclass `0x82`, referenced by its owner (the material, map or
part whose parameters it holds):

| Chunk | Content |
|---|---|
| `0x0009` | 16 bytes: `u32` (4 to 43 in the fixtures, unknown), `u16` block id (the descriptor's: VRayMtl 1 to 6, Bitmap 0 and 1), `u32` descriptor version (`0x55F03700` in all but one of the fixtures' 2,253 blocks), `u16` number of entries, `u32` the owner's object index (the referencing object in every fixture) |
| `0x000B` | instead of `0x0009` (ViewportManager's block in every fixture): the descriptor's ClassID (8 bytes), then the same 16 bytes |
| `0x100E` | one per stored parameter, below |
| `0x0013` | the owner references, below |
| `0x000F`, `0x0003` | the asset of the file-name or bitmap entry before it, below |
| `0x000C`, `0x0011`, `0x1005` | not read (rollout state and names) |

An entry (`0x100E`): `u16` parameter id, `u32` type (the SDK's ParamType2; bit `0x800` = a table), `u32` the
parameter definition's flags (the same bits the SDK's `ParamDef.Flags` reports: `0x1` animatable, `0x2`
transient, `0x100` P_NO_REF, `0x200` P_OWNERS_REF), `u32` unknown, then:

- a scalar: a `u8` tag and the value. Tag `0x40` = a stored value, `0xC0` = the stored value of an animatable
  parameter, `0x80` = a controller, no value (a probe saved by 3ds Max 2020 with three animated VRayMtl
  parameters; no fixture);
- a table: a `u8` 0, a `u32` element count, then a tag and a value per element. vray_wrappers: Multi/Sub-Object
  `materialList`, `mapEnabled`, `names`, `materialIDList` (3 each); VRayBlendMtl `coatMtl`, `blend`,
  `texmap_blend`, `texmap_blend_multiplier` (9 each); Standard `maps`, `mapAmounts` (24 each).

| Type | Value | Shown by |
|---|---|---|
| 0 float, 5 angle, 6 percent, 7 world, 11 color channel | `f32` as stored: radians, a fraction (Standard `opacity` 83 % = 0.83) | every fixture |
| 1 int, 4 bool, 12 time, 13 radio button, 19 index | `i32` | every fixture |
| 2 color, 3 point3, 10 hsv | 3 x `f32` (colors 0..1) | every fixture |
| 22 point4, 23 float color with alpha | 4 x `f32` | standard_physical (Physical Material colors) |
| 8 string | `u32` byte count, UTF-16LE with a terminating NUL; count `0xFFFFFFFF` = none | vray_wrappers `names`; Standard's `shaderByName` is stored as none (3ds Max reports it from the shader) |
| 9 file name | `i32`: -1 none, -2 the asset follows as the next sibling `0x000F{0x0002: 16-byte asset id}` | vray_maps (the Bitmap's `fileName` is transient; its file is the bitmap's asset) |
| 16 bitmap | `u8` (1: set), the data follows as the next sibling `0x0003{0x1201, 0x1260{0x0002: asset id}}` | vray_maps, standard_physical (Bitmap parameter 13) |
| 14 material, 15 map, 17 node, 18 reference target, 21 ParamBlock2 | with P_OWNERS_REF or P_NO_REF an `i32` object index (-1: none); otherwise no value | below |

Reference parameters, checked against the oracle's targets on every fixture:

- P_OWNERS_REF (the owner holds the reference): the stored index is often -1 although the map is set (every map
  of FixtureVRayMaps but its opacity map). `0x0013` holds `u32` count, then `u16` parameter id, `u16` the owner's
  reference slot, `u16` (unknown) per parameter: VRayMtl `texmap_diffuse` (100) is at the VRayMtl's slot 7,
  `texmap_reflection` (101) at 8, `texmap_bump` (103) at 10, `texmap_reflectionGlossiness` (104) at 11,
  `texmap_opacity` (112) at 19; Multi/Sub-Object `materialList` (0) at 1, element k at 1 + k; VRay2SidedMtl
  `frontMtl` / `backMtl` at 1 / 2; Shell `originalMaterial` / `bakedMaterial` at 1 / 2; Bitmap `output` (15) at 2.
  A parameter missing from `0x0013` uses its stored index (Bitmap `coords`, 14: the Placement object).
  A file saved in the 3ds Max 2012 format (format 14000, corpus scene A) has no `0x0013` in any block, and some
  stored indices are -1 although 3ds Max reports the map set (Color Correction `map`, Mix `map1` / `map2` /
  `mask`, Falloff `map1` / `map2`, VRayMtl `texmap_diffuse` ...). The slot is the parameter definition's reference
  number, a constant of the class: `maxdrop/reader/owner_slots.py` keeps it per (superclass, ClassID, block id),
  from the fixtures' `0x0013` tables and, for VRayOverrideMtl, VRayLightMtl, Composite and class `0xC90017A5`
  (no fixture `0x0013` entry: texmap_rules' Composite keeps its maps as block references), from corpus scene B's
  (format 20000); every object of scene A agrees. Only a block without
  `0x0013` uses it: for a stored -1, and for a stored index that is none of the owner's references when the owner
  holds one at that slot (scene A stores 3704 such indices: 3702 equal the slot's, 2 are stale, a Normal Bump's
  `normal_map` naming another Normal Bump's Bitmap and a Falloff's `map1` naming a controller, where 3ds Max
  reports the slot's map; this rests on scene A alone, the only format-14000 scene measured);
  a slot past the owner's references is an empty reference.
  `tests/unit/test_pblock.py` drops the table and the indices of every fixture block that has one and gets the
  same references.
- P_NO_REF: the stored index is the target (Standard `maps`: the diffuse Bitmap, which the material's Texmaps
  object references).
- Neither flag: the elements take the block's own reference slots 0, 1, 2 ... in entry order, tables expanded
  and transient entries included: VRayBlendMtl `baseMtl` 0, `coatMtl` 1-9, `texmap_blend` 10-18, its transient
  aliases `coatMtl_0`... and `texmap_blend_0`... 19-36 (37 slots, the block's `0x2035` count; the aliases' slots
  are empty); VRayNormalMap `normal_map` 0, `bump_map` 1.

Transient parameters are mostly not stored (VRayMtl: 25 of the 80 parameters of block 1, among them
`bump_multiplier` 102 and the `texmap_*` 109-128 that mirror block 4). Some are stored anyway with a stale value
(VRayMtl's alias 56 in block 5, VRayBlendMtl `blend_0`...): the parity test does not compare transient
parameters. A block may store no entry at all (Standard's dynamics block, 4).

The old ParamBlock (class `(8, 0)`): `0x0001` `u32` count, `0x0005` `u16` (unknown: 2, 3 or 6), then per
parameter a `0x0002` container: `0x0003` `u32` index, an empty `0x0004` on some (unknown), and the value chunk
`0x0100` + ParamType: `0x0100` float, `0x0101` int, `0x0104` bool (fixtures: the Bitmap's Placement and Output,
the Standard material's sampler); `0x0102` color and `0x0103` point3 follow the SDK's ParamType, no fixture has
them.

## Materials and maps

`maxdrop/reader/materials.py` reads them; `test_materials.py` checks on every fixture that the materials and maps
reached from the nodes are those of the oracle's graph, and that each one's sub-materials and maps are among the
reader's children.

- A material has superclass `0x0C00`, a map `0x0C10`. The name is a `0x4001` string inside a container whose id
  depends on the class: `0x4000` (Standard, Bitmap, Multi/Sub-Object, Shell, VRay2SidedMtl, VRayBlendMtl,
  VRayNormalMap), `0x5431` (VRayMtl), `0x0100` (Physical Material). The reader takes the first container child
  holding a `0x4001`.
- The parameter blocks are among the material's references (VRayMtl: slots 1 to 6 = blocks 1 to 6; Standard:
  slots 3 to 7 = blocks 0 to 4). References of superclass UVGen (`0x0C20`), XYZGen (`0x0C30`), TexOutput
  (`0x0C40`), Shader (`0x10B0`) and Sampler (`0x1110`) are parts with blocks of their own: a Bitmap's Placement
  (slot 0, an old ParamBlock: 0 U offset, 1 V offset, 2 U tiling, 3 V tiling, 6 W angle in radians, 7 blur, set
  by vray_maps' script) and Output (slot 2), a Standard material's Blinn shader (slot 2, a ParamBlock2 with the
  colors: 0 ambient, 1 diffuse, 2 specular, 9 specular level, 10 glossiness, 11 soften) and sampler (slot 8).
- Sub-materials and maps are referenced by the material (P_OWNERS_REF parameters), by one of its blocks
  (VRayBlendMtl, VRayNormalMap) or, for a Standard material, by its Texmaps object (class `(0x1200, 0)`,
  superclass `0x1080`, slot 1).
- A Bitmap's Placement object (superclass UVGen, class `(0x100, 0)`) also has leaf chunks of its own, each a `u32`
  (texmap_rules and probe scenes saved by 3ds Max 2020, one setting changed per Bitmap): `0x9002` flags (bit 0 U
  tile, 1 V tile, 2 U mirror, 3 V mirror, 27 real-world scale; bit 30 set in every file), `0x9003` axis (0 UV, 1 VW,
  2 WU), `0x9005` mapping type (0 texture, 1 environment), `0x9006` coordinate source (0 explicit map channel, 1
  planar from object XYZ, 2 vertex color channel, 3 planar from world XYZ), `0x900B` the map channel. Its old
  ParamBlock adds 4 U angle and 5 V angle (radians). A mirrored axis has its tile bit clear.
- The Output part (superclass TexOutput, class `(0x100, 0)`): an old ParamBlock, 0 RGB level, 1 RGB offset, 2 output
  amount, 3 bump amount, and a leaf `0x0002` `u32` flags, bit 1 (`2`) invert.
- A Bitmap's gamma: the `0x0003` sibling of its `bitmap` entry holds the BitmapInfo in `0x1201` (70 bytes in every
  file seen). Its last 14 bytes start with an `f32` gamma and a `u32` flags: bit 0 set (`5` seen) is an override
  and the gamma its value (texmap_rules: 1.0 and 2.2); `20` is automatic, the default, with gamma 1.0. The override
  survives renaming the file after loading it (that is how the fixture names a bare file with an override).
- 3ds Max's own `getSubMtl` of a Multi/Sub-Object answers by material ID and skipped ID 3 of 1, 3, 7: the IDs are
  `materialIDList` (stored zero-based: `[0, 2, 6]`), the materials `materialList` in the same order.

Parameter ids used so far, per class and block (the oracle names every one of them; these are set to distinct
values by the fixture scripts or read by the tests):

| Class (ClassID) | Block | Parameters |
|---|---|---|
| VRayMtl `(0x37BF3F2F, 0x7034695C)` | 1 basic | 1 diffuse, 68 diffuse_roughness, 81 selfIllumination, 83 selfIllumination_multiplier, 2 reflection, 3 reflection_glossiness, 62 hilight_glossiness, 4 reflection_subdivs, 8 reflection_fresnel, 63 reflection_ior, 64 / 65 lock glossiness / IOR, 91 reflection_metalness, 5 refraction, 6 refraction_glossiness, 9 refraction_ior, 23 refraction_fogColor, 24 refraction_fogMult, 107 refraction_thinWalled, 25 translucency_on, 37 translucency_color, 94 sheen_color, 95 sheen_glossiness, 96 coat_amount, 97 coat_color, 98 coat_glossiness, 99 coat_ior (vray_basic) |
| | 2 BRDF | 10 brdf_type (4 = GGX), 54 anisotropy, 58 anisotropy_rotation (stored in degrees, as shown), 69 soften, 86 gtr_gamma, 89 brdf_useRoughness |
| | 3 options | 11 option_traceReflection, 13 option_doubleSided, 22 option_cutOff, 84 option_opacityMode |
| | 4 maps | map, on, multiplier: 100 / 150 / 200 diffuse, 101 / 151 / 201 reflection, 102 / 152 / 202 refraction, 103 / 153 / 203 bump, 104 / 154 / 204 reflectionGlossiness, 105 refractionGlossiness, 106 displacement, 109 refractionIOR, 110 hilightGlossiness, 111 reflectionIOR, 112 / 162 / 212 opacity, 113 roughness, 117 self_illumination, 119 metalness (multipliers in percent: 63.0 = 63 %) |
| VRay2SidedMtl `(0x6066686A, 0x11731B4B)` | 0 | 0 frontMtl, 1 backMtl, 7 translucency, 3 backMtlOn, 4 texmap_translucency, 8 force1SidedSubMtls |
| VRayBlendMtl `(0x3DA0041B, 0x0F436E31)` | 0 | 0 baseMtl, 1 coatMtl (table), 2 blend (color table), 3 texmap_blend, 4 texmap_blend_multiplier, 6 coatMtl_enable, 5 additiveMode |
| Shell Material `(0x255, 0)` | 0 | 2 originalMaterial, 3 bakedMaterial, 0 viewportMtlIndex, 1 renderMtlIndex |
| Multi/Sub-Object `(0x200, 0)` | 0 | 0 materialList, 1 mapEnabled, 2 names, 3 materialIDList (zero-based) |
| Standard `(2, 0)` | 0 shader | 0 shaderType, 2 twoSided |
| | 1 extended | 1 opacity (fraction), 6 ior |
| | 3 maps | 0 mapEnables, 1 maps, 2 mapAmounts (fractions; slot 1 = diffuse) |
| Physical Material `(0x3D6B1CEC, 0xDEADC001)` | 0 | 1 base_weight, 2 base_color (float color with alpha), 3 reflectivity, 4 roughness, 6 metalness, 10 refl_color, 11 diff_roughness, 30 transparency, 31 trans_color, 33 trans_ior, 50 emission, 51 emit_color, 60 coating, 62 coat_roughness |
| Bitmap `(0x240, 0)` | 0 | 0-3 clip u, v, w, h, 7 cropPlace, 8 filtering, 12 preMultAlpha, 13 bitmap (asset), 14 coords, 15 output |
| VRayNormalMap `(0x71FA6E51, 0x72057C2F)` | 0 | 0 normal_map, 2 normal_map_on, 3 normal_map_multiplier, 4 bump_map, 5 bump_map_on, 6 bump_map_multiplier, 1 map_channel, 7 flip_red, 8 flip_green, 9 swap_red_and_green |

The maps of texmap_rules (block 0 each; `convert/texmaps.py`):

| Class (ClassID) | Parameters |
|---|---|
| Bitmap `(0x240, 0)` | 6 apply (cropping / placement on), 9 monoOutput (1 alpha), 10 rgbOutput (1 alpha as gray), 11 alphaSource |
| Falloff `(0x6EC3730C, 0)` | 0 color1, 1 map1Amount, 2 map1, 3 map1On, 4 color2, 5 map2Amount, 6 map2, 7 map2On, 8 type, 9 direction |
| VRayDirt `(0x2F567899, 0x090D5EA4)` | 12 occluded_color, 13 unoccluded_color, 17 texmap_unoccluded_color, 18 its on, 19 its multiplier |
| VRayColor2Bump `(0x31E15D1D, 0x7D7E2810)` | 0 map, 1 height (world units), 2 bump delta scale |
| VRayColor `(0x58F82B74, 0x73B75D7F)` (vray_texmaps) | 9 color_mode (0 RGB, 1 temperature: V-Ray writes the temperature's color into color), 8 temperature, 0 / 1 / 2 red / green / blue (color again), 4 rgb_multiplier, 3 alpha, 5 color, 10 color_gamma (applied after the multiplier), 11 rgb_primaries; block 1 (6 gamma_correction, 7 gamma_value) is transient |
| Output `(0x2B0, 0)` | 0 map1, 1 map1Enabled, 2 output (its Output part) |
| RGB Tint `(0x224, 0)` | 0 red, 1 green, 2 blue, 3 map1, 4 map1Enabled |
| Mix `(0x230, 0)` | 0 mixAmount (fraction), 1 lower, 2 upper, 3 useCurve, 4 color1, 5 color2, 6 map1, 7 map2, 8 mask, 9 / 10 / 11 their switches |
| RGB Multiply `(0x290, 0)` | 0 color1, 1 color2, 2 map1, 3 map2, 4 / 5 their switches, 6 alphaFrom |
| Color Correction `(0x2D0, 0)` | 0 color, 1 map, 2 rewireMode, 7 hueShift (degrees), 8 saturation (%), 10 tintStrength, 11 lightnessMode (1 advanced), 12 brightness, 13 contrast, 18 gainRGB (%), 22 gammaRGB |
| Composite `(0x280, 0)` | tables: 1 mapEnabled, 3 maskEnabled, 5 blendMode (0 normal), 6 layerName, 8 opacity (%), 9 mapList, 10 mask; 0, 2 and 4 have no name and are empty tables, not saved. Its `name` is the layer names: the fixture's Composite keeps its default name |
| Normal Bump `(0x243E22C6, 0x63F6A014)` | 0 mult_spin, 1 bump_spin, 2 normal_map, 3 bump_map, 4 / 5 their switches, 6 method (0 tangent), 7 flipred, 8 flipgreen, 9 swap_rg |
| CoronaNormal `(0x2870CEAA, 0xCC18437C)` | 500 normalMap, 501 multiplier, 502 addGamma, 503 flipRed, 504 flipGreen, 505 swapRedGreen, 507 additionalBump, 508 additionalBumpStrength, 509 additionalBumpOn |

The Corona classes of corona_physical, corona_legacy, corona_maps, corona_layered and corona_light (3ds Max 2020 +
Corona 12, DLL `coronamaxutils2020.dlt`; block 0 each). CoronaPhysicalMtl's class-directory name starts with a
carriage return (`"\rCoronaPhysicalMtl"`); MAXScript's `CoronaMtl` is CoronaLegacyMtl. Corona names its obsolete
parameters `removedParam`: they are not saved. A Corona map amount is a fraction (CoronaPhysicalMtl's base and
roughness amounts and CoronaLayeredMtl's amounts are percent in MAXScript: 75.0 there is 0.75 here). One older scene
(Corona's 2015-era DLL `coronamaxutils2015.dlt`) has the same ClassIDs and the same parameter ids for
CoronaLegacyMtl, CoronaBitmap and CoronaNormal.

| Class (ClassID) | Parameters |
|---|---|
| CoronaPhysicalMtl `(0x6912AB89, 0x87151720)` | 101 baseColor, 102 baseLevel, 103 / 104 / 105 baseTexmap (on, amount), 111 metalnessMode (1 metal), 121 opacityColor, 122 opacityLevel, 123 / 124 / 125 opacity map, 131 baseRoughness, 132 / 133 / 134 its map, 171 baseIor, 191 refractionAmount, 192 / 193 / 194 its map, 203 useThinMode, 211 clearcoatAmount, 221 clearcoatIor, 231 clearcoatRoughness, 331 selfIllumColor, 332 selfIllumLevel, 333 / 334 / 335 its map, 351 / 352 / 353 baseBumpTexmap, 381 thinAbsorptionColor, 391 clearcoatAbsorptionColor, 411 / 412 metalnessTexmap (on; no amount), 421 roughnessMode (0 roughness, 1 glossiness), 461 iorMode |
| CoronaLegacyMtl `(0x70BE6506, 0x448931DD)` | colors 101 diffuse, 102 reflect, 103 refract, 105 opacity, 107 selfIllum; levels 121, 122, 123, 127, 128; maps 141 diffuse, 142 reflect, 143 reflectGlossiness, 144 refract, 146 opacity, 147 bump, 158 selfIllum, each switched on by its id + 20, amounts 290, 291, 292, 293, 295, 296, 303; 180 reflectGlossiness, 182 fresnelIor, 183 ior, 210 thin, 402 pbrMode |
| CoronaLayeredMtl `(0x65486584, 0x8425554E)` | 1000 baseMtl, 1001 layers (table of 10), 1002 amounts, 1003 mixmaps, 1004 layersOn; getSubMtl answers the base, then the layers |
| CoronaLightMtl `(0x53B7717A, 0x500D5093)` | 110 intensity, 111 texmap, 112 texmapOn, 113 color, 150 opacityTexmap, 151 opacityTexmapOn, 168 twosidedEmission |
| CoronaBitmap `(0xABBA5784, 0x65484244)` | 101 filename (asset), 103 uvwChannel, 105 uvwScale, 106 uvwOffset (point3), 107 filteringBlur, 108 / 109 tilingU / V (0 none, 1 repeat, 2 mirror), 114 realWorldScale, 117 monoChannelOutput, 118 rgbChannelOutput (1 alpha as gray), 119 clippingOn, 120 clippingMode (0 crop, 1 place), 121-124 clipping u, v, width, height, 125 gamma (-1 automatic), 129 wAngle (radians), 130 uAngle (the U offset times 2 pi, kept in step by Corona); its Output part at slot 1 |
| CoronaColor `(0x68426DCA, 0x372362D4)` | 50 method (0 color, 1 HDR color, 2 temperature, 3 hex), 51 temperature (K), 52 color, 56 alpha, 57 multiplier, 58 colorHdr, 59 hexColor |
| CoronaMix `(0x6847286F, 0x3FFFAAB4)` | 200 mixOperation (0 add, 1 subtract, 2 multiply, 3 divide, 4 minimum, 5 maximum, 6 mix, 7 gamma, 8 difference), 201 mixAmount, 202 / 203 multiplierTop / Bottom, 204 / 205 offsetTop / Bottom, 206 / 207 texmapTop / Bottom, 208 / 209 colorTop / Bottom, 210 texmapMix, 211 / 212 / 213 switches of the mix, top and bottom maps, 214 mixInSRgb |

What the Corona maps do was measured with `renderMap` in 3ds Max 2020: a CoronaBitmap's UVW scale, offset and W
angle place the image exactly as a Bitmap's tiling, offset and W angle; CoronaMix gives mix(bottom, operation(bottom,
top), amount), the mix map replacing the amount when it is on (the operation numbers above come from that).

VRayBitmap `(0x6769144B, 0x02C1017D)` (vray_texmaps, 3ds Max 2020 + V-Ray 5.2; the V-Ray SDK's
`pb2vrayhdri.h`). MAXScript's `VRayHDRI`, its name before V-Ray 5, is the same class. References: 0 block 0, 1
block 1, 2 its Placement (a standard UVGen, the same chunks as a Bitmap's), 3 block 2, 4 its Output, 5 block 3.
Block 0: 0 HDRIMapName (file name, the asset id), 1 multiplier, 2 mapType (0 angular, 1 cubic, 2 spherical, 3
mirrored ball, 4 3ds Max standard: the Placement), 7 mapChannel (for the environment types only; the Placement has
its own), 8 gamma, 9 renderMultiplier, 16 cropplace_on, 17 cropplace_mode (1 place), 18-21 u, v, width, height,
22 rgbOutput (1 alpha as gray, 2 intensity as gray), 23 monoOutput (1 alpha), 25 color_space, 31 coords (owner
slot 2), 38 / 39 mapSource and its switch. Block 3: 41 rgbColorSpace (0 default, 1 sRGB, 2 ACEScg, 3 raw).
Measured with `renderMap` on a mid-gray 8-bit image: color_space 0 (None) leaves the pixel as it is, 1 (Inverse
gamma) gives pixel ^ (1 / gamma), 2 (sRGB) the sRGB curve, 3 (From 3ds Max) the scene's input gamma (2.2), 4 (Auto,
the default) the sRGB curve; multiplier scales the color, renderMultiplier does not change renderMap (it applies
when V-Ray renders). Not measured: whether the multipliers come before or after the Output's invert and offset
(MaxDrop folds them into its amount), Auto on a float file (taken as linear) and V-Ray's crop origin (taken as a
Bitmap's).

## Asset metadata

- The files a scene names are listed in the stream `FileAssetMetaData3` (every fixture; empty, 0 bytes, when the
  scene names no file). Records follow each other with no header and no count; a string is a `u32` count of
  UTF-16 units (the NUL not counted), the units, then a UTF-16 NUL, present also for count 0. A record: the
  16-byte asset id, the asset type (`Bitmap`), the path as stored, and a third string, empty in every fixture.
  vray_maps: 7 records, standard_physical: 1, texmap_rules: 22, corona_maps: 13, corona_light: 3, corona_layered: 1,
  vray_texmaps: 12 (`reader/assets.py`, `tests/unit/test_assets.py`). A CoronaBitmap's file is the asset id in its
  parameter 101 (`filename`, type 9), a VRayBitmap's in its parameter 0 (`HDRIMapName`, type 9).
- A Bitmap's file is the asset id in its parameter 13 (`bitmap`, type 16, block 0, see the ParamBlock2 value
  types above); its `fileName` (16) is transient and not stored. The id's record holds the file name 3ds Max
  reports as `fileName` (oracle) for every Bitmap of vray_maps and standard_physical.

## Open

Not shown by any fixture yet, so not stated above:

- Asset metadata seen only in the corpus (`assets.py` relies on it): scene A (saved as 3ds Max 2012) has
  `FileAssetMetaData2` instead, its records without the third string (155 records: `Bitmap` and `Photometric`);
  in scene B's `FileAssetMetaData3` the third string is the absolute path 3ds Max found the file at when saving
  (167 of 168 records, the same file name as the stored path, which is a bare file name there; empty for the one
  stored as an absolute path).
- Parameter blocks seen only elsewhere (`pblock.py` relies on them):
  - entries in `0x000E` instead of `0x100E`, same layout, in corpus scene A (saved as 3ds Max 2012); scenes A and
    B walk without an issue: 726 and 560 materials and maps, 33,543 and 41,274 stored parameters;
  - a controller on a parameter (tag `0x80`, no value): a probe with three animated VRayMtl parameters had them at
    the block's reference slots 0, 1, 2 in entry order (`Animated(index)` in the reader). Where controllers go
    when the block also holds references is assumed (after those), not shown; corpus scene A has 4 such values.
  - not known: the first `u32` of `0x0009`, the fourth `u32` of an entry, the third `u16` of a `0x0013` record,
    `0x0005` and `0x0004` of the old ParamBlock, and the value layout of the types no file has shown (matrix3,
    and the others the reader keeps as raw bytes).
- Other root container ids: `0x2014` and `0x2023` occur in older files, and the 64-bit chunk header (size 0,
  then a `u64`) in large ones.
- Derived objects (an object with modifiers): special id `0x2032`, past the class directory, referencing its
  modifiers and then its base object. The reader follows them (`Scene.object_stack`), but no fixture has a
  modifier.
- The sign convention of the offset rotation: every fixture's is the identity.
- The meaning of bit `0x800` and the other flag bits in `0x0960`.
- Layer and node flags no fixture has, found with `tools/maxdiff.py` on scratch files saved by 3ds Max 2020 (three
  boxes on two layers; the same scene saved again; then one change per file). `reader/scene.py` relies on them:
  - node frozen: `0x0960` bit `0x200000`, plus an empty `0x0976` chunk; node not renderable: `0x099C` bit
    `0x8000` cleared (as in layers_flags);
  - layer hidden: `0x1020` bit `0x100000`, layer frozen: bit `0x200000` (the node's bits); layer not
    renderable: `0x1050` bit `0x8000` cleared;
  - a nested layer: `0x1090` = `1`, `0x10A0` = the parent layer's name (UTF-16), `0x10B0` = `i32` the parent
    layer's object index;
  - the layer name `0x1010` is UTF-8 (a name with U+00E4 and U+4E2D is stored `4c c3 a4 e4 b8 ad`) in 3ds Max
    2020; the encoding other versions write is not known (the reader replaces bytes that are not UTF-8).
- System unit types 1, 2, 5, 6 (feet, miles, meters, kilometers) and a scale other than 1: taken from the 3ds Max
  SDK, no fixture has them. A `Compressed` part in General (instead of `Uncompressed`) is assumed for a compressed
  file.
- Geometry seen only in the corpus (scenes A and B, every Editable Mesh and Poly decoded, vertex and face counts
  equal to the oracle on every node; `geometry.py` relies on them):
  - dead Editable Poly records: a vertex or edge whose flags have bit `0x2` is stored as its flags alone (4 bytes);
    a dead face has degree 0 and the face-flags field (mask `0x01`) with bit `0x2`. polyop.getNumVerts and
    getNumFaces count them, so `MeshData.stored_vertices` / `stored_faces` do; the arrays leave them out. The map
    face of a dead face keeps its old degree;
  - mask bit `0x01`: a `u32` of face flags, the first field after the mask (before `0x08`). Values on live faces
    `0x1`, `0x8`, `0x20`, `0x40000`, ...: not decoded, only bit `0x2` is used. No mask bit other than `0x01`,
    `0x08`, `0x10`, `0x20` occurs: `geometry.py` refuses one;
  - Editable Mesh map channels `-2`, `-1`, `0` (alpha, illumination, vertex color) besides `1` and up, `0x0956`
    before several channels and `0x23A0` after them (not map data), and triangle flags `0x0`-`0x7` and `0x40`-`0x47`
    in the low bits (edge visibility 1/2/4; not decoded);
  - other Editable Poly chunks (`0x0200`, `0x0210`, `0x0300`) and Editable Mesh selection chunks (`0x092C`-`0x092E`):
    not read.
- Controllers seen only in the corpus (scenes A and B, compared with their oracle; `controllers.py` relies on
  them):
  - a Bezier Float with its `0x2501` directly in the object, not in `0x7127` (under ScaleXYZ, list weights);
  - keys: `0x2525` in a Bezier Float (28 bytes per key: `i32` time, `u32` flags, `f32` value, four `f32`), `0x2528`
    in a Bezier Scale (148 bytes, the 7-float value at byte 8). Every key chunk holds one key (at time 0, 200 or
    16000). Where the key's value differs from the saved value chunk (1 float, 3 scales), the oracle at frame 0
    agrees with the saved value;
  - the scale axis of Bezier Scale (`Q^-1 * S * Q` with the stored quaternion; the other order misses 10 nodes of
    scene B) and the Euler order XYZ = X applied first (ZYX misses over half of scene B);
  - ScaleXYZ `(0x118F7C01, 0xFEEE238B)`: three Bezier Float, x, y, z;
  - Position List `(0x4B4B1002, 0)` and Rotation List `(0x4B4B1003, 0)`: `0x1010` = entry count, `0x1020` = active
    entry, entries at reference slots 0..n-1, a ParamBlock2 at a later slot whose reference slots 0..n-1 are the
    weights (Bezier Float); only weights 1 and 0 occur, so how entries combine is not pinned down;
  - Look At `(0x2006, 0)` on the camera nodes: not evaluated (identity and an issue) until M4.
- Controllers taken from the 3ds Max SDK without any file showing them: Linear Position, Rotation and Scale
  (`0x2002`, `0x2003`, `0x2004`), Bezier Position and Rotation (`0x2008`, `0x2009`), TCB Position, Rotation and
  Scale (`0x442312`, `0x442313`, `0x442315`), their value chunks (`0x2503` point, `0x2504` quaternion, `0x2505`
  scale), and the Euler orders 1 to 5. Scale List `(0x4B4B1004, 0)` is in a fixture's class directory, but no
  file has one on a node: how its entries and weights combine is taken from the other lists.
