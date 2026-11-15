# The .max format, as far as MaxDrop has verified it

What MaxDrop's reader (`maxdrop/reader/`) relies on, written down only once a committed fixture shows it. Each fact
names the fixture (`tests/fixtures/<name>.max`, whose 3ds Max oracle is `<name>.oracle.json`, see
[ORACLE.md](ORACLE.md)); the tests named here keep the facts true. All nine fixtures were saved by 3ds Max 2020 (file
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
- `0x2035`: a `u32`, then `(u32 slot, i32 index)` pairs. The first value is 16 for Node and RootNode, 48 for
  Texmaps and 2 for Bezier Float, Bezier Scale, Bezier Color, Boolean Controller and Grid Reference in every
  fixture; its meaning is unknown and the reader ignores it. RootNode and the controllers have no pairs.

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

## Open

Not shown by any fixture yet, so not stated above:

- Other root container ids: `0x2014` and `0x2023` occur in older files, and the 64-bit chunk header (size 0,
  then a `u64`) in large ones.
- Derived objects (an object with modifiers): special id `0x2032`, past the class directory, referencing its
  modifiers and then its base object. The reader follows them (`Scene.object_stack`), but no fixture has a
  modifier.
- The sign convention of the offset rotation: every fixture's is the identity.
- The meaning of bit `0x800` and the other flag bits in `0x0960`, and of the first `u32` of `0x2035`.
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
