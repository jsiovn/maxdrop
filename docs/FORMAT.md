# The .max format, as far as MaxDrop has verified it

What MaxDrop's reader (`maxdrop/reader/`) relies on, written down only once a committed fixture shows it. Each fact
names the fixture (`tests/fixtures/<name>.max`, whose 3ds Max oracle is `<name>.oracle.json`, see
[ORACLE.md](ORACLE.md)); the tests named here keep the facts true. Every fixture was saved by 3ds Max 2020 (file
version 22000), in its own format but saved_as_2017, saved_as_2018 and saved_as_2019 (formats 19000, 20000,
21000). What only other files have shown is listed under [Open](#open), not here.

## Chunks

- A chunk is a `u16` id and a `u32` size that counts the 6-byte header; bit 31 of the size marks a container,
  whose payload is more chunks. Every chunked stream of every fixture (`Scene`, `ClassDirectory3`,
  `DllDirectory`, `Config`, `ClassData`, `VideoPostQueue`) indexes to the bottom with this rule
  (`tests/unit/test_chunks.py`).
- Strings are UTF-16LE without a terminator (node names: `0x0962`, below). A file of 3ds Max 2012 or older
  writes the same chunks as 8-bit text: see [Strings of older files](#strings-of-older-files).

## Class directory

- `ClassDirectory3` holds one `0x2040` container per class: `0x2060` = `i32` dll index, `u32` classA, `u32`
  classB, `u32` superclass; `0x2042` = the class name. The class index counts the `0x2040` entries from 0.
  box_poly_standard: Editable Poly = `(0x1BF8338D, 0x192F6098)`, superclass `0x10`, `epoly.dlo`
  (`tests/unit/test_classdir.py`).
- A ClassID is unique only with its superclass: Standard (material, `0xC00`) and RootNode (`0x1`) are both
  `(2, 0)` in every fixture.

## Scene stream: the object index

- The `Scene` stream is one top-level container, id `0x2025` in every fixture of the 2020 format (the others:
  below). Its children are the objects of
  the scene: the **object index** is a child's position, the child's chunk id is its **class index** into the
  class directory. Every child id of every fixture is a valid class index (`test_classdir.py`,
  `tests/unit/test_scene.py`).
- The root container's id follows the format the file was saved in: `0x2022` saved_as_2017, `0x2023`
  saved_as_2018 and saved_as_2019, `0x2025` 3ds Max 2020 (the oracle's `file_version`; `tests/unit/test_census.py`).
  The children read the same way under all three (every check of `test_scene.py` runs on the saved_as fixtures).
- Most objects are containers. Two per fixture are empty leaf chunks (TVNode and Reaction Manager in
  hierarchy): they hold no references.

## References

An object points to others by object index.

- `0x2034`: an `i32` array; the position is the reference slot, `-1` an empty slot. ViewportManager in
  hierarchy: `[0, -1]`; a node's Position/Rotation/Scale: three entries in every fixture, its Editable Poly two,
  the Editable Mesh of editable_mesh one.
- `0x2035`: a `u32`, then `(u32 slot, i32 index)` pairs. The first value is the number of reference slots: 16
  for Node and RootNode, 48 for Texmaps and 2 for Bezier Float, Bezier Scale, Bezier Color, Boolean Controller and
  Grid Reference in every fixture, 2 for MtlBaseLib in stack_basic, the point count for the curve of a Custom
  Curve Control (nameless in the class directory: 2 for a default Falloff curve, 3 and 4 in falloff_curve; see
  [The Falloff mix curve](#the-falloff-mix-curve)), 34 for VRayMtl (vray_basic,
  vray_maps, vray_wrappers: what the SDK's `NumRefs` reports for a VRayMtl), and for a ParamBlock2 the number of
  its reference slots (25 and 37 in
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
| `0x099C` | `u32`, bit `0x8000` = renderable, `0x200` = Cast Shadows, `0x400` = Receive Shadows | layers_flags, below |
| `0x0A28` | 2 x `u32` By Layer masks: the first of the display flags, the second of the `0x099C` bits taken from the node's layer | layers_render: `0x3040C600` in the second on its By Layer nodes; `0` and `0` on every other node of every fixture, below |
| `0x096A` | 3 x `f32` object offset position | hierarchy: `[5, 5, 0]` for FixtureRoot and FixtureChild = oracle `offset_pos` |
| `0x096B` | 4 x `f32` object offset rotation | modifier_pivot: FixtureBent `[0, 0, 0.258819, 0.965926]` = oracle `offset_rot` (stored as MAXScript prints it); every other node `[0, 0, 0, 1]` |
| `0x096C` | 7 x `f32`: object offset scale (3), then a scale axis rotation (4) | every fixture: `[1, 1, 1]`, `[0, 0, 0, 1]` |
| `0x2035` | slots 0, 1, 3, 6 | below |

Reference slots of a node, checked on every node of every fixture (`test_scene.py`):

- slot 0: the transform controller, a Position/Rotation/Scale (`(0x2005, 0)`, superclass `0x9008`);
- slot 1: the object. With no modifier it is the base object, whose ClassID and superclass equal the oracle's
  `base_class_id` and `base_superclass`. With modifiers it is a derived object: special id `0x2032`, past the
  class directory, whose references are its modifiers top to bottom and then the base object (modifier_pivot:
  Bend, UVW Map, Editable Poly, the oracle's order; `Scene.object_stack` follows them, also through a
  world-space derived object `0x2033` above it or above the base object, stack_wsm; see [Modifiers](#modifiers)).
  Nodes whose stacks end in the same base object are exactly the oracle's `instances`
  (instances: three instances share the source's object, the copy has its own; modifier_pivot: a bare source and two references with modifiers of their own,
  three slot-1 objects on one base object);
- slot 3: the material, present exactly when the oracle names one (the group head of layers_flags has no
  material and three pairs instead of four);
- slot 6: the layer, a Base Layer (superclass `0x10F0`).

Flags in `0x0960` seen so far: `0x800` on most nodes, `0` on the three instances and the copy in instances (the
source has `0x800`) and on the two references in modifier_pivot, `0x100800` on the hidden node of layers_flags
and on FixtureHiddenParent of layers_more, `0x200800` on FixtureFrozen of layers_more, `0x40` on the group head of
layers_flags, `0x900` on the two group members and `0x4800` on the six nodes of lookat a Look At controller aims at
(`test_scene.py`, `test_flags_and_pair_heads`, which also checks the first `0x2035` values above). Decoded from
layers_flags, layers_more and lookat:

| Bit | Meaning |
|---|---|
| `0x100000` | hidden (FixtureHidden, FixtureHiddenParent; such a node also has an empty `0x0975` chunk). The node's own flag: a hidden parent leaves its child visible (FixtureVisibleChild, `0x800`) |
| `0x200000` | frozen (FixtureFrozen, which also has an empty `0x0976` chunk) |
| `0x40` | group head (FixtureGroup, a Dummy whose children are the members) |
| `0x100` | group member (FixtureGroupA and FixtureGroupB) |
| `0x4000` | the target of a Look At controller (the five Target objects and FixtureAim; not on a node only a LookAt Constraint aims at). Not read: the controller names its target |

`0x800` is not decoded. Renderable is not in `0x0960` (FixtureNoRender has `0x800`) but in `0x099C`, a `u32` on
every node of every fixture: `0x0F00D600` on each node, `0x0F005600` on FixtureNoRender (and the two shadow
values below, and layers_render's FixtureByLayerOwnOff, `0x0F005000`, set By Layer), so bit `0x8000` is
renderable. A layer's flags stay on the layer: the nodes of layers_more's hidden, frozen and non-rendering layers
have `0x800` and `0x0F00D600`, no `0x0975` or `0x0976` (MAXScript's `isHidden` and `isFrozen` still answer true
for them; the oracle writes the node's own flags, see [ORACLE.md](ORACLE.md)). `test_scene.py` checks every node's
hidden, frozen and renderable flags against the oracle (renderable merged with its layer's for a node set By
Layer, below).
Cast Shadows and Receive Shadows (Object Properties, Rendering Control) are bits of the same `u32`: saves of a Box
with one change each (maxdiff) give `0x0F00D400` with Cast Shadows off, `0x0F00D200` with Receive Shadows off and
`0x0F00D000` with both (layers_flags: FixtureNoCastShadow, FixtureNoReceiveShadow; `test_scene.py` checks both
flags of every node against the oracle). On a light node the bit `0x200` is the node's `castShadows` in MAXScript,
not the light's shadow switch `baseObject.castShadows` (Lights, below). A layer's `0x1050` has the same two bits, used only by a node set to By
Layer.
Rendering Control By Layer (Object Properties) is the second `u32` of the node's `0x0A28`, a mask over the bits of
its `0x099C` that come from its layer's `0x1050` instead (maxdrop-em3.145, saves of one change each with maxdiff):
`renderByLayer` sets `0x3040C600` there (the three bits read, `0x8000`, `0x400` and `0x200`, among others) and
leaves `0x099C` as it was; `displayByLayer` sets `0xF9F80000` in the first `u32` and `0x00030000` in the second,
`motionByLayer` `0x00040800` in the second (neither read). Setting a render flag of the node after `renderByLayer`
turns By Layer off again (the save keeps the mask `0`). The reader merges the masked bits from the node's own
layer (`reader.scene.render_flags`), which is what MAXScript answers for such a node and so what the oracle writes
(layers_render). Scanline renders of probe scenes (3ds Max 2020) show what the mask does: a By Layer box on a
layer with Renderable off is not rendered, on a layer with Cast Shadows off casts no shadow, and a By Layer ground
on a layer with Receive Shadows off shows none; with its own flag off on a layer that has it on, it renders,
casts and receives. A By Object node keeps its own flags whatever its layer says, rendered on a layer with
Renderable off too, and a parent layer's flags reach no node below it (a By Layer box on a rendering, casting
child layer of a parent with both off renders and casts). Every fixture's node has `0x0A28`, 8 bytes; in scene A
23 of 746 nodes are By Layer (the second `u32` `0xB044CE00` or `0xB047CE00`, the three bits always together), on
layers with all three on; scene B has none.

## Modifiers

A node's slot 1 with modifiers is a derived object `0x2032` (`reader/modifiers.py`, `tests/unit/test_modifiers.py`
against the oracle's `modifiers` on every fixture; stack_basic, modifier_pivot and stack_wsm have stacks):

| Chunk | Content | Shown by |
|---|---|---|
| `0x2034` | references: the modifiers from the top of the stack down, then the object below them | every stack |
| `0x204B` | 1 byte, `0x2e` | every derived object and modifier; not decoded |
| `0x2500` | one container per modifier reference slot, in slot order: that modifier's context on this node | below |
| `0x2501`, `0x2502` | empty; `0x2502` only on the derived objects of references (modifier_pivot's two, FixtureNestedRef) | not decoded |

The object below the modifiers is the base object or another derived object. A reference (`reference` in MAXScript)
wraps the shared derived object: stack_basic's FixtureNestedRef references `[Twist, FixtureNested's derived object]`
and that one `[Taper, Editable Poly]`, so the reference's stack, bottom first, is Taper, Twist (the oracle lists
Twist, Taper). An instanced modifier is one modifier object referenced by several derived objects, each with its
own context: FixtureSharedA and FixtureSharedB (one Noise added to both selected boxes).

A modifier context `0x2500`:

| Chunk | Content | Shown by |
|---|---|---|
| `0x2510` | 12 x `f32`, rows 1 to 4 (row 4 = translation), then a `u32`: the Matrix3 flags (7 = identity, 6 = translated only) | `getModContextTM`: identity on every node but FixtureSharedA `[-10, 0, -10]` and FixtureSharedB `[10, 0, -10]` (flags 6) |
| `0x2511` | 6 x `f32`: the context's box, min then max; `+1e30` x 3, `-1e30` x 3 = not computed when saved | `getModContextBBoxMin/Max` where stored; FixtureSharedA/B `[-15, -5, -10]..[15, 5, 10]` |
| `0x2513` | 4 bytes: `00 01 04 00` on most, `00 00 04 04` and `00 00 04 00` on the shared contexts | not decoded |
| `0x2512` | empty in stack_basic (FixtureTurbo's TurboSmooth); in 29 of 126 contexts of scene A, 80 of 121 of scene B | not decoded |

Max computes a context's box when the modifier first needs it: modifier_pivot, built by script and saved before
anything evaluated its stacks, holds empty boxes for its Bend and its TurboSmooth, while the oracle, dumped after
evaluating the scene, reports one. A box is read only where stored.

A modifier keeps its name and its three switches in `0x39BF`:

| Chunk in `0x39BF` | Meaning | Shown by |
|---|---|---|
| `0x0100` | UTF-16 name; empty = the class directory's name | FixtureUVW, FixtureNoise (`m.name` in the oracle) |
| `0x0110` | present: off (`enabled` false) | FixtureFlags' Bend |
| `0x0120` | present: off in the viewport (`enabledInViews` false) | FixtureFlags' Taper |
| `0x0130` | present: off in the renderer (`enabledInRenders` false) | FixtureFlags' Twist |

Its references: UVW Map `[gizmo Position/Rotation/Scale, old ParamBlock]`; Bend, Taper, Twist, Noise `[gizmo
Position/Rotation/Scale, center Position XYZ, block]`; TurboSmooth `[ParamBlock2]`. Bend and TurboSmooth keep a
ParamBlock2, UVW Map, Taper, Twist and Noise the old ParamBlock (UVW Map: index 0 map type, 9 to 11 length, width,
height, see [UVW Map](#uvw-map); TurboSmooth: parameter 0 iterations).

A world-space modifier (a "binding", superclass `0x820`) sits in a derived object of its own, special id `0x2033`,
past the class directory like `0x2032` (stack_wsm, `test_modifiers.py`, `test_scene.py`): FixtureWSM (a UVW Map, then
a Map Scaler binding) has node slot 1 = `0x2033` with references `[Map Scaler, the 0x2032 derived object]`, that one
`[UVW Map, Editable Poly]`; FixtureWSMOnly (a Map Scaler binding alone) `0x2033` with `[Map Scaler, Editable Poly]`.
The same chunks as a `0x2032`: `0x2034`, `0x204B`, one `0x2500` per modifier slot (an identity `0x2510`, the box of
the stack below in `0x2511`, a `0x2513` of `00 01 04 00`), an empty `0x2501`. So the world-space modifiers come above
every object-space one; `modifiers.py` marks them `world_space` and `Scene.object_stack` follows both ids. The
binding keeps an empty `0x0100` name: MaxDrop names it by the class directory (MapScaler), 3ds Max shows "Map Scaler
Binding" (the oracle's `name`), and the oracle's context of it is `null` (`getModContextTM` answers `undefined` for
a world-space modifier). Its references: `[-1, -1, a Map Scaler object]`. Neither corpus scene has one.

## Layers

A layer is an object of class Base Layer `(0x7E9858FE, 0x1DBA1DF0)`, superclass `0x10F0`; a node's slot 6 points
to it. layers_flags has three (`0`, FixtureLayerA, FixtureLayerB), layers_more seven (`0`, FixtureHiddenLayer,
FixtureFrozenLayer, FixtureNoRenderLayer, FixtureParentLayer, FixtureChildLayer, `FixtureLäyer中`), layers_nested
eight (`0`, FixtureHiddenParentLayer, FixtureHiddenChildLayer, FixtureFrozenParentLayer, FixtureFrozenChildLayer,
FixtureTopLayer, FixtureMiddleLayer, FixtureBottomLayer), layers_render seven (`0`, FixtureNoCastLayer,
FixtureNoReceiveLayer, FixtureNoRenderLayer, FixtureOnLayer, FixtureNoRenderParent, FixtureChildLayer), the saved_as
fixtures two (`0`, `FixtureLäyer中`), the other fixtures one (`0`):

| Chunk | Content | Shown by |
|---|---|---|
| `0x1010` | the layer name, no terminator: UTF-8 in every file 3ds Max 2020 saves (saved_as included), unlike the UTF-16 node names | layers_flags: `46 69 78 ...` (`FixtureLayerA`), `30` (`0`); layers_more: `46 69 78 74 75 72 65 4c c3 a4 79 65 72 e4 b8 ad` (`FixtureLäyer中`) |
| `0x1020` | `u32` flags: `0x100000` hidden, `0x200000` frozen (the node's bits) | layers_more: `0x100000` on FixtureHiddenLayer, `0x200000` on FixtureFrozenLayer; layers_nested: `0x100000` on FixtureHiddenParentLayer and FixtureTopLayer, `0x200000` on FixtureFrozenParentLayer, `0` on the layers below them; `0` on every other layer of every fixture |
| `0x1050` | `u32`, bit `0x8000` = renderable, `0x200` = Cast Shadows, `0x400` = Receive Shadows: the layout of a node's `0x099C`, read for its By Layer nodes (all on without the chunk) | `0x0B00D600` on every layer but layers_more's FixtureNoRenderLayer, `0x0B005600`, and layers_render's FixtureNoCastLayer `0x0B00D400`, FixtureNoReceiveLayer `0x0B00D200`, FixtureNoRenderLayer `0x0B005600`, FixtureNoRenderParent `0x0B005000` |
| `0x1090` | `u8`, not `0` = the layer has a parent layer | layers_more: `1` on FixtureChildLayer; layers_nested: `1` on FixtureHiddenChildLayer, FixtureFrozenChildLayer, FixtureMiddleLayer and FixtureBottomLayer; `0` on every other layer of every fixture |
| `0x10A0` | the parent layer's name, UTF-16LE (not read: `0x10B0` names it) | layers_more: `FixtureParentLayer` on FixtureChildLayer; layers_nested: `FixtureMiddleLayer` on FixtureBottomLayer, `FixtureTopLayer` on FixtureMiddleLayer |
| `0x10B0` | `i32` the parent layer's object index | layers_more: FixtureChildLayer's is FixtureParentLayer's (`0x236`), a higher index than its own; layers_nested: FixtureBottomLayer's is FixtureMiddleLayer's, whose is FixtureTopLayer's |

A layer's flags are not copied to its nodes (see [Nodes](#nodes)); a parent layer may hold no node
(FixtureParentLayer).
Nor are they copied to the layers below: layers_nested's hidden and frozen parent layers carry the bit, their child
layers (and the middle and bottom layers of its three-level nest) have `0x1020` = `0` and `0x0B00D600`, their
nodes `0x800`. 3ds Max still treats them as hidden or frozen: MAXScript's `isHidden` / `isFrozen` of those layers
and of their nodes answer true (the oracle's layer flags; .NET `ILayer.IsHidden(true)`, while `IsHidden(false)`
is the layer's own bit), and in a probe's scanline render a node below a hidden parent layer shows nothing. The
importer follows that: a hidden layer's collection is excluded, which leaves out the collections below it, and a
frozen layer's `hide_select` reaches the objects of the collections below.
The one Layer Manager `(0x0D7374FC, 0x51FF028E)`, superclass `0x200`, references the layers
in `0x2034`: slot 0 is layer `0`, then the others in the order the fixture scripts made them, the order of the
oracle's `layers` (`test_scene.py` checks names, order, flags and parent of every fixture's layers against the
oracle).

## Hierarchy

- Parents are object indices, so nodes with the same name stay apart: in hierarchy one `FixtureTwin` is a
  child of FixtureRoot and the other is top level.
- The oracle lists nodes pre-order from the root, children in 3ds Max's order. On every fixture that equals a
  pre-order walk with each node's children sorted by object index. In layers_flags the group head has a higher
  node handle (6) than its members (4, 5) but a lower object index, and comes first in both orders.

## Transform controllers

`maxdrop/reader/controllers/` turns a node's slot-0 controller into matrices at frame 0;
`tests/unit/test_controllers_fixtures.py` checks every node of every fixture against the oracle's `transform` and
`object_transform` (within 1e-4, per element).

- Matrices are in Max's row-vector convention: a point times the matrix, row 4 = translation, `A * B` applies `A`
  first; this is the oracle's 12-float layout.
- Every fixture node's controller is a Position/Rotation/Scale `(0x2005, 0)` (but lookat's and the controllers
  fixture's camera, see [Look At](#look-at)) with reference slots 0 = position, 1 = rotation, 2 = scale; by default
  Position XYZ `(0x118F7E02, 0xFFEE238A)`, Euler XYZ `(0x2012, 0)` and Bezier Scale `(0x2010, 0)`. Position XYZ,
  Euler XYZ and ScaleXYZ `(0x118F7C01, 0xFEEE238B)` reference three float controllers in slots 0, 1, 2 (x, y, z;
  ScaleXYZ's in percent in MAXScript, stored as factors).
- Euler angles are radians. hierarchy: FixtureRoot's Z angle `0.5236` gives row 1 = `[0.866025, 0.5, 0]`, a
  standard row-vector rotation. `0x1003` = `i32` axis order: 0 for XYZ (X applied first; also after switching
  another order back to XYZ), 101, 102, 103, 104, 105 for XZY, YZX, YXZ, ZXY, ZYX (the first letter applied first),
  106, 107, 108 for XYX, YZY, ZXZ (not read: an issue, XYZ used). controllers: FixtureEulerMulti and one node per
  other Tait-Bryan order, each with three angles.
- Bezier Scale holds `0x2505`: 3 x `f32` scale, then the scale axis as a 4 x `f32` quaternion, scale matrix =
  `Q^-1 * S * Q`. hierarchy: FixtureLeaf (`scale = [-1,1,1]` in the script) stores `[-1, -1, -1]`; with that, the
  oracle's rotation rows (`[-0.866025, -0.5, 0]`, ..., `[0, 0, -1]`) come out exactly. controllers:
  FixtureScaleAxis (scale `[2, 0.5, 1]` along a turned axis) matches the oracle; the other order, `Q * S * Q^-1`,
  misses by 1.2.

Keyframe controllers (controllers fixture; every class read here is a 3ds Max 2020 class id it shows):

| Class | ClassId | Value chunk | Key chunk, bytes per key |
|---|---|---|---|
| Linear Float | `(0x2001, 0)` | `0x2501` f32 | `0x2511`, 12 |
| TCB Float | `(0x442311, 0)` | `0x2501` | `0x2520`, 40 |
| Bezier Float | `(0x2007, 0)` | `0x2501`, in `0x7127` | `0x2525`, 28 |
| Linear Position | `(0x2002, 0)` | `0x2503` 3 x f32 | `0x2513`, 20 |
| TCB Position | `(0x442312, 0)` | `0x2503` | `0x2521`, 64 |
| Bezier Position | `(0x2008, 0)` | `0x2503` | `0x2526`, 80 |
| Linear Rotation | `(0x2003, 0)` | `0x2504` quaternion | `0x2514`, 24 |
| TCB Rotation | `(0x442313, 0)` | `0x2504` | `0x2522`, 92 |
| Smooth Rotation (MAXScript `Bezier_Rotation`) | `(0x2009, 0)` | `0x2504` | `0x2527`, 88 |
| Linear Scale | `(0x2004, 0)` | `0x2505` | `0x2515`, 36 |
| TCB Scale | `(0x442315, 0)` | `0x2505` | `0x2523`, 112 |
| Bezier Scale | `(0x2010, 0)` | `0x2505` | `0x2528`, 148 |

- The value chunk is the value at the time slider when the file was saved, and `0x2500` (2 x `i32` ticks) the
  interval it holds for: `(-2^31, 2^31-1)` (forever) without keys, `(4800, 4800)` (frame 30) on every keyed
  controller of the controllers fixture, saved at frame 30. FixtureLinearKeyed's `0x2503` is `[-48, 64, 13]`, 60 %
  of the way between its keys at frames 0 and 50, while the oracle at frame 0 has the frame-0 key. So the value
  chunk is used when its interval holds time 0, the keys otherwise (FixtureBezierKeys: keys at frames 0, 20 and 50,
  `0x2501` = 36.6667, oracle -20, the frame-0 key).
- A key record: `i32` time (ticks, 160 per frame at 30 fps), `u32` flags, the value (1, 3, 4 or 7 floats as the
  value chunk), then the class's tangents or TCB parameters. TCB Rotation keeps the absolute quaternion there and
  an angle-axis relative to the previous key later in the record. `0x3003` = the range, the first and last key's
  time unless the range bar was moved (`(-2^31, -2^31)` without keys), `0x3002` 0 for Linear and 4 for TCB and
  Bezier when keyed.
- Out-of-range types (controllers_ranges; probes of every keyframe class, maxdrop-6n0.6.12): a container `0x8499`
  beside the keys (in `0x7127` for a Bezier Float) holds `0x3000` (before) and `0x3001` (after), `i32` 2 Cycle, 3
  Loop, 4 Ping Pong, 5 Linear, 7 Relative Repeat (MAXScript's #identity is 0, and the whole controller then reads
  zero, a scale too, inside the keys as well: not followed, an issue wherever frame 0 is), and `0x3003` = 1 when they are switched off (Enable ORTs; then
  Constant). Without `0x8499` both are Constant. Setting them on a Position XYZ writes them on its three floats too.
  They apply outside the range `[r0, r1]` (span `T`): Constant the value at the range end; Cycle and Loop the time
  `r1 - (r0 - t) mod T` before and `r0 + (t - r1) mod T` after (a time a whole range before the start lands on the
  end); Ping Pong mirrored; Relative Repeat that plus `k (v(r1) - v(r0))`, `k` the ranges crossed (a rotation:
  `v * (v0^-1 v1)^k`, a scale its components); Linear the slope of one tick at the range end, `v(r0 + 1) - v(r0)`
  per tick (a rotation turned by `(a^-1 b)` per tick). Inside the range the keys (the nearest key's value outside
  them): a range of frames 20 to 40 over keys at 10 to 50 gives frame 20's value at frame 0 with Constant
  (FixtureFloatRanges). Loop over a range wider than the keys repeats them every range and goes in a straight line
  from the last key's value to the first's across the gap, inside the range too (FixtureFloatRanges' X: 2.5 at
  frame 0, halfway from 5 at frame 50 to 0 at frame 70; a probe of a Bezier Float within 2.4e-7 at every frame of
  three gaps; other classes are not probed: the same line, an issue). 3ds Max takes the one-tick values of Linear in single
  precision through its own time curve: the reader is within 2e-4 ten frames out on probes of every class, more
  further out or past a curved end (8e-4 at one frame from a custom key), exact past a straight end
  (FixtureFloatAfter's Z).
- At time 0: a key at 0 gives its value (FixtureBezierKeys, the keyed nodes, the lists' animated entries); before
  the first key, the first key's value (FixtureTCBBefore, keys at frames 10 and 50); between two Linear keys, linear
  (FixtureLinearBetween, keys at -10 and 40: position `[-56, 93, 11]`, scale rows of length 1.1, 1.0, 1.4) and the
  rotation by slerp, the way the stored signs give (controllers_tangents' FixtureLinearRotationWide: 270 degrees about
  Z between keys at -10 and 40 is 54 degrees on at frame 0, not -18; the later key is stored as `[0, 0, -0.707107,
  -0.707107]`). Opposite quaternions (1 + their dot below 5e-7: a whole revolution) turn a whole turn about the
  earlier key's local Z, whatever axis the turn was made about: `q(f) = cos(pi f) q0 + sin(pi f) (-y0, x0, -w0,
  z0)` (FixtureLinearRotationTurn, 360 degrees about `[1, 1, 0]`; probes from the identity and from a turned key,
  turns of 359.9 to 360 degrees); from 1 + dot of 4e-7 to 4e-5 the probes switch between that and the slerp, so a
  pair with 1 + dot below 1e-3 (within about 5 degrees of a revolution) stays linear with an issue (359 degrees:
  the slerp is 1.4e-4 off). Between two Bezier, TCB or Smooth Rotation keys, the curve below.
- Between two Bezier, TCB or Smooth Rotation keys (controllers_tangents, every node within the oracle's 6 digits;
  three probes sampled every 2.5 frames, outside the repo), the record after time and flags (n = the value's
  floats; a step key's value saved at frame 30 holds for its whole segment, so its `0x2500` can hold time 0, a
  probe):

  | Class | Record after the flags |
  |---|---|
  | Bezier Float, Position, Scale | value, in tangent, out tangent, in length, out length, n floats each (Position: 3 more, zero) |
  | TCB Float, Position, Scale | value, tension, continuity, bias, ease to, ease from (the UI's (x - 25) / 25 and x / 50), in tangent, out tangent |
  | TCB Rotation | quaternion, the five TCB values, the axis and angle turned from the previous key, the in and the out control quaternion |
  | Smooth Rotation | quaternion, the in and the out control quaternion (equal), two identity quaternions |

  - Bezier: tangents in value per tick (MAXScript shows them times the frame rate, a scale's times 100 more), the in
    tangent pointing back; smooth, fast, slow and auto tangents store the tangent 3ds Max computed when it last
    evaluated the controller (a smooth key between keys `dt_in` and `dt_out` away: the chords' slopes weighted
    `(s_in dt_out + s_out dt_in) / (dt_in + dt_out)`; auto: `(v[k+1] - v[k-1]) / (t[k+1] - t[k-1])`, flat at an
    extreme). Flags: the in
    tangent's type in bits 7-9, the out tangent's in bits 10-12 (0 smooth, 1 linear, 2 step, 3 fast, 4 slow, 5 custom
    and auto), `0x8000` constant velocity, `0x100000` free handle. A length is a fraction of the segment, -1 a third.
    `0x2533` and `0x2534` beside the keys are bit arrays of the keys whose in and out tangent is auto (`0x2700`:
    `i32` count, then a bit per key, the first key's the lowest bit; `0x2532` their union). Only a custom tangent
    (type 5 without its auto bit) and a free handle are drawn with their stored length: every other type is a third
    long, though they store 0.3333 or 0.333 (up to 8.7e-3 off in the probes; controllers_ranges' FixtureSmoothAuto).
    A Linear tangent facing a custom or auto tangent across its segment is the chord's slope (it stores a stale one,
    1.5 off: FixtureLinearTangents, FixtureLinearPosition); facing a smooth, fast, slow or Linear one its stored
    tangent, `2 s - ` the neighbour's (the chord's slope `s` between two Linear keys), is right.
    The segment is the cubic through `(t0, v0)`, `(t0 + lo dt, v0 + out lo dt)`, `(t1 - li dt, v1 + in li dt)`,
    `(t1, v1)`, its time curve solved for the time (FixtureBezierFloats, FixtureBezierCustom with lengths 0.6 and
    0.15, FixtureBezierPosition and FixtureBezierScale with a length per axis); in the probes this curve and
    3ds Max's differ by up to 8.5e-4 next to a steep key and by ~1e-4 between auto keys, cause not known. A step
    out of the earlier key or into the later holds the earlier key's value
    (FixtureBezierFloats' Z). Constant velocity changes nothing on a Bezier Float (a probe).
  - A free handle (the flag on the key whose handle it is: a free middle key between custom keys fits only so)
    has its length in frames, measured along the handle in (ticks, stored value) space: its time extent is
    `L * ticks_per_frame / sqrt(1 + tangent^2)` (FixtureFreeHandles: steep, a free middle key, a handle of 60 frames
    on a 50-frame segment; FixtureFreePosition, a length per axis; probes on a Bezier Scale, an Euler X in radians,
    a ScaleXYZ factor, tangents up to 0.2 per tick, all within 5e-6, the handle longer than its segment 1.6e-5).
    Freeing a handle turns its length into frames (a third of 50 frames: 16.6675). `ticks_per_frame` is 4800 / the
    frames per second, an `i32` in Config `0x20B0/0x0010` (four saves of an empty scene at 24, 25, 30 and 60 fps
    differ only there); a probe at 25 fps fits 192 ticks per frame, and 160 misses by 0.95. Every fixture is at
    30 fps: the frame rate is shown by that probe, not by a fixture.
  - Constant velocity counts only on a Bezier Position and only on the earlier key of a segment (on the later key
    alone, on a Bezier Scale, on a Bezier Float: the plain curve): the cubic of values and tangents with handles of a
    third (the stored lengths and a free handle do not count), cut into 40 chords of equal parameter; at the
    fraction f of the segment's time the point f of the polyline's length along it, linearly between two chord ends
    (FixtureConstantVelocity, whose later key has lengths 0.6, 0.1 and 0.3; probes within 1e-5). The three floats
    after the lengths are 3ds Max's last length lookup (total, parameter, length there), not read.
  - Scale keys whose axes differ (Bezier, TCB and Linear Scale): the components by the class's curve, the axis by
    slerp at the plain fraction of the time, not the eased one (FixtureScaleAxesBezier, FixtureScaleAxesTCB with
    tension, continuity and ease, FixtureScaleAxesLinear; the eased fraction misses by 0.35). Every axis pair the
    probes stored has a positive dot.
  - TCB: the Hermite cubic of the stored tangents (value per segment; with two keys `(p1 - p0) (1 - tension)`) at
    the fraction of the segment eased by the earlier key's ease from and the later key's ease to (3D Studio's ease:
    both scaled to a sum of 1 when larger), per component (FixtureTCBFloats, FixtureTCBPosition, FixtureTCBScale).
    The stored tangents and control quaternions already allow for segments of unequal length (a probe with keys at
    frames -30, 10, 20 and 50, TCB and Smooth Rotation alike).
  - TCB Rotation: squad of the two quaternions with the earlier key's out control and the later key's in control,
    at the eased fraction (FixtureTCBRotation, a turn of 200 degrees); Smooth Rotation the same without ease
    (FixtureSmoothRotation). Their slerps keep the stored signs, unlike the shorter arc.
  - A TCB Rotation turn of A >= 2 pi (the record's angle; a whole turn is stored as the f32 6.2831855, above 2 pi):
    with `p(x) = q0 * AngAxis(axis, x)` (the quaternion product of the stored Max quaternions, axis in q0's frame),
    U the eased fraction and `h = pi / A`, `U < h` gives squad(q0, q0's out control, p(pi), p(pi), U / h), `U > 1 -
    h` squad(p(A - pi), p(A - pi), q1's in control, p(A), (U - 1 + h) / h) (the control on p(A)'s side), and the
    turn between p(A U) (FixtureTCBSpinStart, 450 degrees, frame 0 in the first half-turn; FixtureTCBSpinEnd, 400,
    the last; FixtureTCBSpinMiddle, 760 after 400, between; FixtureTCBTurn, exactly 360; probes of 360 to 800
    degrees over two to four keys within 2e-6). 3ds Max stores other controls for a key past a revolution than
    for one just short of it. Between 350 and 360 degrees neither squad nor this fits (359: squad 3.8e-4 off;
    359.9: both miss): a turn within 10 degrees of a revolution stays linear with an issue.
  - Smooth Rotation stores both keys of a revolution in one hemisphere and its controls carry the turn: squad as
    above (probes of 350 to 359.999 degrees within 3e-7).
- Linear and TCB Float hold `0x2501` directly in the object; Bezier Float in `0x7127` in every fixture.

List controllers: Float List `(0x4B4B1000, 0)`, Position List `(0x4B4B1002, 0)`, Rotation List `(0x4B4B1003, 0)`,
Scale List `(0x4B4B1004, 0)`. `0x1010` = entry count, `0x1020` = active entry, entries at reference slots 0..n-1,
a ParamBlock2 at a later slot (4) whose parameter 0 is the weights, a float table: stored values (0.5, 0.5 on
FixturePosList, FixtureRotList, FixtureScaleList; 0.5, 1.0 on FixtureFloats' Float List), a controller in the
block's reference slots where animated. Each entry weighs as the oracle shows:

- Position and Float List: the weighted sum (FixturePosList `0.5 * [40, 40, 0] + 0.5 * [10, 20, 30]` =
  `[25, 30, 15]`; FixtureFloats `0.5 * 30 + 1.0 * 7` = 22).
- Scale List: the product of `I + (S - I) * weight` per entry (FixtureScaleList `[1.5, 2, 0.75]` from `[2, 1, 1]`
  and `[1, 3, 0.5]` at 50 %), a later entry applied first (controllers_tangents' FixtureScaleListAxes: two scales
  along turned axes at 100 %; the other order misses by 1.28). One entry along a turned axis at any weight
  (controllers_ranges' FixtureScaleListTurned at 60 %; probes at 30, 150 and -50 %) and plain scales at any weights
  fit it; a weight other than 100 % on an entry applied after a turned one fits none of the rules tried (0.2 to
  0.5 off): an issue.
- Average (parameter 1 of the block, an `i32`, 1 when on; controllers_ranges' FixtureListAverages and
  FixtureFloatListAverage, probes of 3 to 11 lists of each class): a Float, Position and Scale List divide the
  weighted sum by the weights' sum (0, the origin or identity when they add up to 0; one entry at 40 %: its value),
  a Rotation List slerps from no rotation towards each entry in turn by its weight, `q = slerp(q, q_k, w_k)`
  (X 30 deg at 50 % and Z 80 deg at 100 %: Z 80 deg). A Scale List average of turned scales fits none of the rules
  tried (0.59 off): the weighted mean of the matrices, an issue.
- Rotation List: each entry's rotation turned by its weight along its own axis, a later entry applied first
  (FixtureRotList: 30 deg about X and 80 deg about Z at 50 % give Z 40 deg, then X 15 deg; controllers_tangents'
  FixtureRotListMulti: two turns about all three axes at 50 % and 30 %).
- Local = scale * rotation * position; world = local * parent world, up the whole chain. hierarchy: FixtureLeaf
  (position `[25, 5, 0]` under FixtureChild under the rotated FixtureRoot) lands on `[40.1314, 26.8301, 0]`.
- Object offset = scale (`0x096C`, along its axis) * rotation (`0x096B`) * position (`0x096A`); the object's world
  transform = offset * world. hierarchy: FixtureRoot and FixtureChild (offset `[5, 5, 0]`) match the oracle's
  `object_transform`. The stored rotation is the conjugate of the standard quaternion, as MAXScript prints it:
  modifier_pivot's FixtureBent (pivot alone turned +30° about Z) stores `[0, 0, 0.258819, 0.965926]`, a -30° turn
  read as row 1 = `[0.866025, -0.5, 0]` (`controllers.quat_matrix`), and offset * world is then the identity
  rotation of the oracle's `object_transform`.

## Look At

lookat (`tools/fixtures/lookat.ms`): target cameras (one rolled 30°, one straight above its target, one under a
Dummy turned 40° and scaled 1.5), a target spot, boxes with a Look At controller (X axis flipped with the target as
up node and a scale of its own; Y axis rolled 15°) and boxes with a LookAt Constraint (two weighted targets and the
Y axis flipped with a scale of its own; an up node looked at; an up node's X axis aligned with, under the Dummy;
Keep Initial Offset under the Dummy, Set Orientation, both, Set Orientation turned off after the box was turned;
an animated weight, the second of two and the one of a constraint with an up node).
Every node's world and object transform equals the oracle within 1e-4 (`test_controllers_fixtures.py`). The frames
were found on scratch files saved by 3ds Max 2020 (one setting changed per file, compared with `tools/maxdiff.py`,
and `node.transform` read in MAXScript); `look_frame` and `constraint_frame` are tested against those numbers
(`test_controllers_aim.py`).

**Look At controller** `(0x2006, 0)`, superclass `0x9008`, a target camera's or light's transform controller (and a
node's whose controller is set to `lookat()`):

| Reference slot | Content |
|---|---|
| 0 | the target node (empty: none) |
| 1 | the position controller (Position XYZ) |
| 2 | the roll: a Bezier Float, radians (FixtureCamRoll: `0.523599`) |
| 3 | the scale controller (Bezier Scale) |

| Chunk | Content |
|---|---|
| `0x0100` | `u32` axis: 0 X, 1 Y, 2 Z (2 on every camera and light) |
| `0x0110` | present: flip |
| `0x0201` | `u8` 1: the target's Z axis is the up direction (FixtureLooker) |

The world position `P` is the position controller's value times the parent's world matrix; the parent's rotation and
scale do not reach the frame (FixtureCamChild's rows have unit length under a Dummy scaled 1.5, its own scale
stored 1). With `n` the unit vector from `P` to the target's world position (the world origin without a target):
`z = -n`, `x = normalize(up x z)`, `y = z x x`, `up` = world Z or the target's world Z axis. Then flip turns the
frame half round `y` (`x, z -> -x, -z`), roll turns it about `z` (`x' = cos r x + sin r y`, `y' = -sin r x +
cos r y`), and the axis picks the rows: Z `(x, y, z)`, X `(z, y, -x)`, Y `(x, z, -y)`. So `-Z` (or `-X`, `-Y`)
looks at the target, `+` when flipped. Degenerate, as 3ds Max computes it: `z` along `up` gives `x = +X`
(FixtureCamDown, straight above its target, has the identity rotation); on the target `z = +X`. World matrix =
scale (along its axis) * frame * translation(`P`); the local matrix is that times the parent's inverse.

**LookAt Constraint** `(0x2021, 0)`, superclass `0x900C`, in a Position/Rotation/Scale's rotation slot. Its one
reference is a ParamBlock2:

| Id | Parameter (MAXScript) | Type |
|---|---|---|
| 0 | `weight` | float table, one per target; an animated element is a controller (tag `0x80`) in the block's next reference slot ([Parameter blocks](#parameter-blocks)), before the targets' (lookat: FixtureWeightAnimated's second weight, a Bezier Float, at slot 0, its targets at 1 and 2; FixtureWeightUp's one weight at 0, the up node at 2): its value at frame 0; 50 (`appendTarget`'s default) when the slot is empty, the controller gives none or is of an unknown class (a Float List none of whose entries gives a value too: under Position XYZ or ScaleXYZ such a list adds nothing), or a stored weight is not finite or missing, reported |
| 1 | targets (`appendTarget`) | node table, no value: the block's reference slots, after the weights' controllers |
| 2 | `relative` (Keep Initial Offset) | bool |
| 3 | `lookat_vector_length` | float (display) |
| 4 | `set_orientation` | bool |
| 5 | `target_axis` (0 X, 1 Y, 2 Z) | int |
| 6 | `target_axisFlip` | bool |
| 7 | `upnode_axis` | int |
| 8 | `upnode_world` | bool |
| 9 | `pickUpNode` | node, no value: the next reference slot |
| 10 | `StoUP_axis` (the source's up axis) | int |
| 11 | `StoUP_axisFlip` | bool |
| 12 | `viewline_length_abs` | bool (display) |
| 13 | `upnode_ctrl`: 0 look at, 1 axis alignment | int |

The ids were matched by the values of the three constraints and by saves that set `relative` or `set_orientation`
alone. The constraint's own chunks hold its offsets, each a quaternion (4 x `f32`, read as a keyframe rotation's):

| Chunk | Content |
|---|---|
| `0x1001` | the node's world rotation when the constraint was assigned (not read) |
| `0x1002` | the node's local rotation (relative to its parent) when the constraint was assigned |
| `0x1003` | the aimed frame when the constraint was first evaluated (a target moved before that is already in it) |
| `0x1004` | the Set Orientation rotation: identity until the node is turned with `set_orientation` on |
| `0x1005` | `u32`, the number of targets in every probe (not read) |

They are stored values: a save after the target moved or the parent turned writes the same ones. With `L` the aimed
frame (below) and `Qn` the matrix of chunk `0x100n`: `relative` on gives the frame `Q2 * Q3^-1 * L` (the Set
Orientation rotation is not applied, also when it is set and `set_orientation` on), `relative` off gives
`L * Q4`, whether `set_orientation` is on or not (a rotation set with it on stays after it is turned off). Found on
24 boxes of scratch files (turned before the constraint or after with Set Orientation, top level and under parents
turned and scaled, uniformly or not, the target moved and the parents turned after), each within `1e-5` of
`node.transform`; in lookat FixtureKeepOffset (under the Dummy), FixtureSetOrientation, FixtureBothOffsets and
FixtureOrientationOff, the target moved after all four were set. A chunk the offset needs that is missing or
shorter than 16 bytes: the plain frame and an issue. The target point is the weighted average
of the targets' world positions. Row `target_axis` = `n` (`-n` flipped). The up vector: axis alignment = row
`upnode_axis` of the up node's world matrix (the world's: that unit axis); look at = from `P` to the up node's world
position (the world's: the origin). Row `StoUP_axis` = the up vector without its part along `n`, normalized
(negated when flipped); the third row completes a right-handed frame (`row[t] = row[t+1] x row[t+2]`). Unlike the
controller's, the scale is relative: world = own scale * the lengths of the parent's rows (a probe: a Dummy scaled
`[1, 2, 3]` and turned gives rows of length 1, 2, 3) * frame * translation(`P`). FixtureConstrainedAxis (own scale
stored `0.6667` under the Dummy scaled 1.5) has unit rows.

Look-ats that depend on one another in a cycle (3ds Max refuses such a loop) are all damaged, whichever is asked
for first: each node of the cycle (one aimed at itself is a cycle of one) gets identity and an issue; a look-at
outside the cycle that aims at one of them aims at its identity. The node at which a chain waits on more than 64
others gets identity and an issue too. A constraint outside a Position/Rotation/Scale's rotation slot is an unknown
class; a damaged constraint block uses the defaults of what it cannot read (an issue).

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

## Shapes

`maxdrop/reader/shapes.py` reads them; `tests/unit/test_shapes.py` checks every shape node of every fixture against
the oracle's `shape`: what 3ds Max's own conversion to an Editable Spline gives (knot types, segment types,
positions and vectors within 1e-4, closed flags, interpolation and rendering settings). shapes has one node per
case below; shapes_more the settings shapes leaves out (NGon corner radius, Ellipse outline, Arc angles out of
range, a Rectangle's corner radius past half a side, rectangular sections); arc_pie_reverse reversed pie Arcs, plain
and extruded, beside an extruded pie, reversed arc, clockwise Line and holed Rectangle. The classes, superclass `0x40` (shape):

| Class (ClassID) | Kept as |
|---|---|
| SplineShape `(0xA, 0)` (Editable Spline) | its knots: FixtureEditable (a Circle collapsed, a knot moved), FixtureOpen |
| Line `(0x1040, 0)` | its knots, the same chunks inside a `0x2000` container: FixtureLine |
| Rectangle `(0x1065, 0)` | old ParamBlock at slot 1: 0 length, 1 width, 2 corner radius |
| Circle `(0x1999, 0)` | old ParamBlock at slot 1: 0 radius |
| Ellipse `(0x1097, 0)` | ParamBlock2 at slot 1: 0 length, 1 width, 2 outline thickness, 3 outline (on / off) |
| Arc `(0x1996, 0)` | old ParamBlock at slot 1: 0 radius, 1 from, 2 to (degrees), 3 pie, 4 reverse |
| NGon `(0x1050, 0)` | old ParamBlock at slot 1: 0 radius, 1 sides, 2 circular, 3 corner radius, 4 scribe |

Every shape has the rendering block at reference slot 0, an old ParamBlock of 28 entries; the parametric ones keep
their interpolation in another at slot 2 (0 steps, 1 optimize, 2 adaptive). Of the rendering block, set to distinct
values in a scratch file of 3ds Max 2020 and in FixtureLine: 0 thickness (the diameter), 1 sides, 2 angle (degrees),
3 to 5 the same for the viewport, 6 Enable In Renderer, 7 generate mapping coordinates, 8 Enable In Viewport, 9 use
viewport settings, 11 rectangular, 12 width, 13 length, 14 the rectangular angle (degrees; shapes_more's
FixtureSection: 30 beside a round angle of 15), 21 the auto-smooth threshold (radians).

A rectangular section, as 3ds Max renders it (`snapshotAsMesh renderMesh:true`, shapes_more and probes): the width
lies across the curve in its plane, the length along the plane's normal (a line along X: Y +-width / 2, Z +-length /
2; along Z: X and Y; a Circle: radial and Z), turned by the angle (FixtureSection, at its first point: (Y, Z) =
(-1.48205, 1.43301), (1.98205, -0.566987) and their opposites), capped at the ends of an open spline. Blender's bevel
object maps profile x to the line's -Y and y to Z: the rectangle turned by +angle in the profile gives the same
corners on FixtureSection, and FixtureSectionLoop spans what 3ds Max's does (convert.scene `rectangular_section`;
the angle's sign is checked on that line along +X only), with the caps filled.
A round section is capped too at the ends of an open spline (a Line, round, 4 sides: 8 vertices, 12 triangles);
Blender's filled caps are the polygon of its sides at each end (shapes: FixtureLine's open spline).

An Editable Spline keeps a BezierShape `0x1010`:

| Chunk | Content |
|---|---|
| `0x1010` | one container per spline, below |
| `0x1050` | `i32` steps; `-1` when adaptive (the probe: steps 7 and adaptive gave `-1` here and 7 below) |
| `0x1060` | `u32` optimize (`0` off) |
| `0x1020`, `0x1030`, `0x1040` | selections; not read |

and beside it `0x1060`, an `i32`: the steps. A spline:

| Chunk | Content |
|---|---|
| `0x2900` | `u32` knot count |
| `0x2904` | `u32`, `0` in every file; not decoded |
| `0x290A` | the knots, 52 bytes each: `i32` knot type (0 smooth, 1 corner, 2 Bezier, 3 Bezier corner), `i32` type of the segment that starts at the knot (0 curve, 1 line), an `f32` (not decoded), then the point, the in vector and the out vector as 3 x `f32` each, in object space, and a `u32` whose high 16 bits are the zero-based material ID of the segment that starts at the knot (a Line probed with IDs 1, 4, 7, 2: `0x0`, `0x30000`, `0x60000`, `0x10000`; the low 16 bits `0`, the last knot of an open spline `0`; the extrude fixture's FixtureExtShapeIDs) |
| `0x290D` | `u32` closed |

The vectors are positions, not offsets, and the file holds them for every knot type: what 3ds Max computed for a
corner or smooth knot is what it shows. A segment of type line is straight whatever the vectors (FixtureLine's
open spline: the oracle's segment middle is the middle of the chord, the Bezier through the vectors is not).
Corpus scene A (format 14000): the same layout on all 255 splines of its 18 Editable Splines and 4 Lines, 434
segments of type line; every shape node of the scene (29, with Rectangles) equals its oracle within 1e-5 of the
knot's magnitude.

The segments' material IDs equal the oracle's (`getMaterialID`, oracle layout 12) on every shape node of the
fixtures: the parametric shapes give every segment ID 1 (zero-based 0, as the reader makes them), the extrude
fixture's FixtureExtShapeIDs and shapes_more's FixtureCurveIds and FixtureCurveMixed the IDs their scripts set. A
Blender curve has one material per spline: the importer draws a spline with its first segment's ID.

The parametric shapes are made by the reader the way 3ds Max makes them, fitted to the oracle:

- a circular arc of angle *a* gets vectors of radius times `veccalc(a)` along its tangents, where `veccalc` is the
  3ds Max SDK's float32 bisection that makes the mean distance of 10 points of the segment from the center equal
  the radius: 0.5517862 for 90 degrees (the SDK's CIRCLE_VECTOR_LENGTH; the textbook 4/3 tan(a/4) is 0.552285). In
  float32 the loop stops early on small angles: 1.5 / 1024 for 0 (a zero-length Arc, radius 10 and 1000), 0.0010986
  for a sixth of a degree (a double bisection gives about 0 and 0.00097);
- Circle: 4 Bezier knots from angle 0, counter-clockwise; Ellipse: the same scaled to width / 2 and length / 2;
  with its outline on (ParamBlock2 id 3, the flag alone: thickness 0 gives two coincident splines) a second spline,
  the same with both semi-axes plus the thickness (id 2), each clamped at 0 (FixtureEllOutline 3, FixtureEllInset
  -15: semi-axes 5 and 0), same start and direction;
- Rectangle: without a corner radius 4 Bezier-corner knots from (width / 2, length / 2), counter-clockwise, each
  vector a third of the way to its neighbour; with one 8, each pair at the ends of a side, both vectors along that
  side, radius x `veccalc(90 degrees)` long; a radius past half a side is not clamped (the knots cross:
  FixtureRectOver, 10 x 30 with 8; a probe with 10 x 12 and 20);
- Arc: always 4 Bezier knots, 3 equal segments (FixtureArc 170 degrees, FixturePie 90, FixtureArcWide 350), the
  first in vector and the last out vector at their knot; pie adds the center and closes the spline; reverse runs
  from `to` back to `from`, every knot's vectors swapped; pie and reverse together reverse the closed pie but keep
  its first knot first: `from` (its out vector now at the knot), the center, `to`, then back along the arc
  (arc_pie_reverse's FixturePieRev 20 -> 130 and FixturePieRevWrap 300 -> 60; probes 30 -> 150, from = to, 0 -> 360
  and 10 -> 350 alike). `from` and `to` are clamped to [0, 360] first, then a `to` below `from` adds 360:
  from = to is a zero-length arc, its knots at `from` (FixtureArcSame; also 400 -> 500 at 360, 0 -> -90 at 0),
  10 -> 370 ends at 360 (FixtureArcOver), -30 -> 60 starts at 0 (FixtureArcUnder), 100 -> 50 runs 310 degrees
  (FixtureArcWrap), 0 -> 360 and 0 -> 720 are a full turn;
- NGon: scribe 0 puts the corners at radius / cos(180 degrees / sides) (the radius is the apothem), scribe 1 at the
  radius, the first at angle 0; Bezier-corner knots with vectors a third of the way to the neighbours, or with
  circular a Bezier knot per corner with vectors of the arc between them. A corner radius *c* (not circular, which
  ignores it) makes two Bezier knots per corner, at *c* x tan(180 degrees / sides) from it along the sides to the
  previous and the next corner (the one before corner 0 first), both vectors along their side, that distance x
  `veccalc(90 degrees)` long, whatever the corner's angle; not clamped (FixtureNGonCorner, FixtureNGonCornerIn,
  FixtureNGonCornerRound, FixtureNGonCornerBig: 4 sides with 30, the knots cross).

## Extrude

The Extrude modifier (ClassID `(0xA0, 0)`, superclass `0x810`; `convert/extrude/`, `tests/unit/test_extrude.py`
against the extrude fixture's oracle) keeps its parameters in an old ParamBlock at reference slot 0:

| Index | Parameter | extrude fixture |
|---|---|---|
| 0 | amount (`f32`) | FixtureExtRect 10, FixtureExtL -15, FixtureExtDownStart and FixtureExtDownEndReal -6 |
| 1 | segments | FixtureExtRect 2, FixtureExtDownStart 3, FixtureExtDownEndReal 2, the others 1 |
| 2, 3 | cap start, cap end | 1 everywhere but FixtureExtGridCircle's and FixtureExtDownStart's cap end 0 and FixtureExtDownEndReal's cap start 0 |
| 4 | cap type: 0 morph, 1 grid | FixtureExtGrid and FixtureExtGridCircle 1, the others 0 |
| 5 | output: 0 patch, 1 mesh, 2 NURBS | 1 |
| 6 | generate mapping coordinates | FixtureExtRect, FixtureExtAdaptive, FixtureExtDownStart and FixtureExtDownEndReal 1 |
| 7 | generate material IDs | FixtureExtAdaptive 0, the others 1 |
| 8 | use shape IDs | FixtureExtShapeIDs and FixtureExtShapeIDsRect 1, the others 0 |
| 9 | smooth | 1 |

Real-World Map Size is not in the block: the modifier's own chunk holds `0x2150 {0x0100 u32 1, 0x0110 {0x0120: 20
bytes naming the class, 0x0130 u32}}`, and that `u32` is 1 on FixtureExtAdaptive and FixtureExtDownEndReal, 0 on
the others. `0x2150` can hold
several `0x0110` entries: the flag is the one whose `0x0120` names Extrude's ClassID (another class's entry is not it).
`maxdrop/reader/realworld.py` reads it for Extrude, UVW Map and the primitives alike. A damaged one is off, never an
error (the flag only changes UVs): a chunk or a `0x2150` whose children do not parse, or a `0x0130` shorter
than a `u32`; an entry that does not parse or whose `0x0120` is shorter than a ClassID is skipped.

What 3ds Max 2020 makes of it (`snapshotAsMesh`, probed on scratch scenes and checked on the fixture: the oracle's
`eval_verts`, `eval_faces` and `bbox_*`; `tests/unit/test_extrude.py` holds the counts):

- **Interpolation**: each segment gets `steps` points between its knots; with optimize, a straight segment (type
  line, or a curve whose points at t 0.4 and 0.6 each turn the path from knot to knot by at most 2 degrees) gets
  none; without optimize even a line segment gets its steps (a sharp Rectangle, steps 2: 12 points). The straight
  test (maxdrop-em3.142; 3,359 two-knot segments under 3dsmaxbatch, steps 1 to 12, chords 0.1 to 1000, no
  mismatch): a vector off the chord by up to about 2 % of it at a third is straight (10^-1.72 chords straight,
  10^-1.70 curved; 10^-1.82 with the vector's end next to its knot), an S with both vectors off on opposite sides
  up to 10^-1.24, vectors on the chord's line until the curve at t 0.4 or 0.6 lies past an end (out vector 1.72
  chords along with the in vector at two thirds; both vectors 4.49 chords long, 3.49 past the far ends). Adaptive:
  a straight segment (the same test) gets none; a curved one is split at its middle, and each piece again while
  its own points at 0.4 and 0.6 of it turn the path from its start to its end by more than 2 degrees and it is wider
  than 1/2048 of the segment, a point at every split (a Circle: 31 per quarter, 128 points; Arcs of 30, 90, 180, 300
  degrees: 13, 25, 49, 97 points). The probe (maxdrop-6n0.6.11; two-knot segments under 3dsmaxbatch, every point
  read back to its parameter): each point sits at a dyadic t, the split tree of 14 of 16 curves (an S, a hook, loops,
  collinear vectors past the ends) is exactly this rule, and a cusp at t 1/3 is kept in a piece of 1/2048 (49 steps;
  50 at 1000 and 0.01 times the size, float32), so 2047 steps a segment at most. 3ds Max computes in float32: next to a cusp, or far from the
  object's origin, its rounding splits pieces the test keeps (a cusp at t 0.5, chord 10: 73 steps, the rule 63; a
  zigzag 129, the rule 131; an S: 19 steps at the origin and 1000 units off, 81 at 10000). MaxDrop
  computes in double. Adaptive's points are counted as they are made against the mesh's MAX_VERTICES.
- **Vertices**: per spline, one copy of its points per level (segments + 1), nothing more: the caps reuse them.
- **Faces**: the sides two triangles per segment and level; a cap of n points with h holes n + 2h - 2 triangles,
  without extra vertices (FixtureExtHole: 32 + 2 - 2 = 32 per cap). Nested closed splines alternate solid / hole
  (FixtureExtIsland: a square, a hole, an island in it). An open spline gets no cap (FixtureExtOpen).
- **Normals**: outward whatever the splines' direction and the sign of the amount, a lone cap too; the side faces
  of an open spline look to the right of it.
- **Material IDs**: the cap facing +Z gets ID 1, the one facing -Z ID 2, the sides ID 3 (FixtureExtRect: the cap at
  the shape faces down and is ID 2; FixtureExtL, amount -15: the cap at the shape faces up and is ID 1); without
  Generate Material IDs every face is ID 1. Use Shape IDs (with Generate Material IDs; without it every face is still
  ID 1): each side face takes the material ID of the spline segment it comes from, its interpolated steps too, on a
  clockwise outline and a hole alike; the caps keep 1 and 2 (FixtureExtShapeIDs: side triangles 2, 6, 10, 4, 8 on IDs
  4, 5, 7, 11, 12). A parametric shape's segments are ID 1 (FixtureExtShapeIDsRect). Cap Start is the bottom cap
  and Cap End the top one: downwards (a negative amount) Cap Start lies at the far level (z = amount), faces -Z and
  is ID 2, Cap End lies at the shape, faces +Z and is ID 1, alone or together (FixtureExtGridCircle, amount -4, Cap
  End off: its grid cap at z -4, facing -Z, ID 2; FixtureExtDownStart, amount -6, Cap End off: at z -6;
  FixtureExtDownEndReal, Cap Start off: at z 0). The maxdrop-6n0.6.10 probe (3ds Max 2020, a 20 x 10 rectangle at
  -5, its hole, clockwise and at z 3, morph and grid caps; the grid points at the cap's level too).
- **Grid caps** (cap type 1; probed on about 60 shapes, `test_extrude_caps.py` GRID_PROBES holds their counts;
  FixtureExtGrid, FixtureExtGridCircle): each solid (an outline with its holes; an island and an overlapping outline
  are solids of their own) gets a grid over the box of its outline's interpolated points, W x H. Divisions per axis:
  20, raised by each hole of the solid to floor(0.95 x W / (s / 2)), s the hole's extent on that axis, at most 50 (a
  3-wide hole in a 40-wide square: 25; a hole 10 x 0.7: 20 across, 50 up; 60 x 20 with a 3 x 3 hole: 38 x 20); on
  the points' float32 values, so an exact ratio falls by its float noise (2.3f .. 4.3f in 40: 37; 18.8f .. 21.8f in
  60: 38). The grid points: x0 + 0.025 W + (0.95 W / N)(i + 0.001), i = 0 .. N, the same for y, whatever the size. A
  cell is filled when it lies wholly inside the solid (its corners inside, no outline or hole edge across it, no
  hole within it); the cap's interior vertices are exactly the corners of the filled cells (a grid point in no
  filled cell is dropped), each filled cell two triangles (top-left to bottom-right; MaxDrop: a quad), and the band
  to the outline is triangulated without more points: n + 2k + 2h - 2 triangles per cap of n outline and hole
  points, k grid points and h holes (Rect 30 x 20: 890 vertices, 1776 faces). A solid without a filled cell gets the
  morph cap. MaxDrop joins band holes whose cells touch only at a corner into one at that point (a four-point Line
  whose cells touch so: 254 vertices, 504 faces, as 3ds Max) and makes a band whose triangles do not tile its area,
  or a grid past a guard, a morph cap with a line in the report. Only the caps that are on get grid points. The grid
  points lie at z 0 and the levels' heights whatever the shape's z (a rectangle at z 3: its outline at 3 and 5, its
  grid at 0 and 2); their map is the cap's box mapping. Every interior edge is hidden: 3ds Max shows the cap as one
  polygon. No local scene has grid caps (443 scenes, 95 Extrudes, the corpus included, 2026-11-21).
- **Self-crossing outlines** (maxdrop-em3.140; 3ds Max 2020 probes, `test_extrude_caps.py` CROSS_PROBES holds
  their counts): a closed spline with two edges that do not follow each other and meet (cross, touch at a knot or
  on an edge, or run over each other: a bowtie, a pentagram, a slit whose edges overlap along the top, an edge back
  over the one before, a Bezier rectangle whose knot moved without its vectors) gets no cap, morph or grid: the
  sides alone (Bowtie 8 vertices, 8 faces). Adjacent edges never count (a closed outline of three points on one
  line is capped). The test is on the interpolated points in XY (edges crossing at other heights count), exact: a
  knot 1e-6 off an edge at x 10 is capped, 1e-6 across it is not. The other splines keep their caps; the crossing
  one is neither a hole nor a container (a bowtie inside a square: the square capped whole, its grid as without a
  hole; a square in a bowtie's lobe: a solid) and is not turned: its sides run from its first knot its own way, as
  an open spline's. Crossings between two splines change nothing. Two knots on one spot one after the other (a
  zero-length segment): 3ds Max keeps both points (a rectangle with a doubled corner: 10 vertices, MaxDrop merges
  them: 8) and between straight edges gives no cap at any coordinates (also the last knot on the first, and a
  rounded Rectangle whose corner radius is half a side, at steps 0); between interpolated curves its rounding
  decides (radius half the short side, steps 6: 10 x 20 capped, 7.3 x 19.1, 3 x 4 and 100 x 250 not; the 10 x 20
  one at steps 1 to 7 and 12 capped, 10 not), and MaxDrop caps it. Under Optimize a curve segment from a knot to
  another on the same spot gets no steps (that pill: 32 points), without it its steps (56). The edge pairs tested
  are bounded (`MAX_CROSS_TESTS`): past them a spline is capped unchecked, a line in the report.
  Wherever the spline starts: a doubled first knot (DupFirst), a doubled pair before the last (DupSecondLast), the
  last on the first, all without a cap. Not probed, assumed as above: an Extrude with both caps off (MaxDrop leaves
  a crossing spline unturned there too), a segment from a knot back to itself with its handles pulled out
  (MaxDrop: no steps under Optimize), two
  points on one XY spot at different heights (MaxDrop: a touch on XY, no cap).
  Rounded Rectangles with short straight sides (10 x 20, corner radius 4.8, 4.9, 4.99; 13 x 12.5, radius 6 and
  6.25): 3ds Max gives the short sides their 6 steps (their handles run so far past the ends that the curve folds
  back: not straight, 44 points) and no cap (the steps fold back over the side); radius 3, 4, 4.5: 32 points and a
  cap. MaxDrop the same since maxdrop-em3.142 (the straight test above; radius 6.25 with its zero-length sides
  merged, 42 points).
  Zero-length segments (maxdrop-6n0.6.9, 3ds Max 2020 probes, steps 6 unless named): what decides is the edge
  into the doubled spot. After a straight edge it gets no cap whatever leaves it (a line into (20, 0) and a curve
  out, two or three knots on the spot: no cap at scales 1, 0.1, 1.37, 3.3 and 1000 with offsets, with the line
  tilted, at steps 1, 6 and 10, without Optimize; three line knots: no cap). After a curve's step 3ds Max's
  rounding decides, a line out or not (a curve in and a line out: capped at scales 1.37, 3.3 and 1000 and at steps
  10, not at scales 1 and 0.1, steps 1 or without Optimize; the last knot on the first after a curve: capped at
  1.37 and 1000 only; curves on both sides: the two shapes probed capped, also with three knots on the spot), and
  MaxDrop caps it, as the pills. Without Optimize the straight cases the same, whatever the steps (DupCorner
  70 / 70, DupMid 84 / 84, the last knot on the first 70 / 70, every point kept; steps 0: 10 / 10, 12 / 12,
  10 / 10). A curve whose vectors lie 1 % of its chord off it counted as straight in the one shape probed, with and
  without Optimize (no cap). MaxDrop: an edge is straight when its segment is a line or passes Optimize's test, or
  is a curve without steps (one chord); a zero-length straight segment's steps sit on its point.
  MaxDrop keeps merging a zero-length segment's points, a default taken in an unattended run and open to the
  owner's word: 3ds Max's extra vertices only make faces of no area (DupCorner 10 / 10, DupMid 12 / 12, the
  10 x 20 r 5 pill 64 / 124 with a degenerate triangle per doubled spot in each cap; MaxDrop 8 / 8, 10 / 10,
  60 / 116). Keeping them would change the crossing test (it would find a touch at every merged point between
  curves and uncap the pills 3ds Max caps), the ear clipping and the grid bands (two ring points on one spot) and
  the caps' polygons. The pill's cap stays as it is: its knots are bit-equal to MaxDrop's (the two on each doubled
  spot too, capped or not), its interpolated steps 1 to 4 float32 ulps off MaxDrop's (3ds Max's are not even
  mirror-symmetric), so whatever 3ds Max tests at the spot turns on bits MaxDrop does not reproduce (Pill 10 x 20
  and Full 14.6 capped, Pill 7.3 x 19.1, 3 x 4 and Full 10 not, the 10 x 20 one at steps 7 capped, 10 not: MaxDrop
  caps them all).
- **Smoothing**: caps group 16; the sides change group only at a corner or Bezier-corner knot (FixtureExtMirror's
  rounded Rectangle: sharp at its 8 Bezier-corner knots) or a Bezier knot with a vector on its point, the groups
  alternating 1, 2 (4 where three runs meet, 1, 3, 2 ... along a spline with no corner). A Bezier knot breaks the
  side when its in or out vector is exactly its point (float32 equal), such as a pie Arc's from (in), center (both)
  and to (out): arc_pie_reverse's extruded pies, 52 hard edges. The 3ds Max 2020 probe (maxdrop-em3.111, a square
  with a fifth knot on one side, kinked or straight): a corner or Bezier-corner knot breaks whatever the angle (also
  on a straight side, also at a 2.3 degree kink); a smooth knot never (also where line segments kink the spline); a
  Bezier knot with both vectors off its point never (also kinked by line segments); one with a vector on its point
  always (kinked or straight, curve or line segments, an open spline too), a vector 1e-6 off at x 10 or 1e-9 off at
  the origin is not on it. 3ds Max keeps a Bezier knot's vectors in line (`setInVec` / `setOutVec` out of line come
  back in line): a Bezier knot with its vectors out of line is not made there. `test_extrude_shapes.py` has the
  cases. The group bits differ (a pie's sides: MaxDrop 1, 2, 4; 3ds Max 1 to 4 or 5, overlapping along the arc), the
  hard edges do not: `tests/unit/test_extrude.py` compares them by position with `arc_pie_reverse.maps.jsonl`.
- **Mapping**: the sides U along each spline by length (0 to 1, the seam at its first point), V up the levels; the
  caps the shape's XY box, 0 to 1. Real-World Map Size: the lengths and sizes in file units instead. Downwards (a
  negative amount; maxdrop-6n0.6.10, 3ds Max 2020: segments 1 to 4, amounts -5 and -0.75, open, closed, clockwise,
  holed, at z 3, a Circle, every cap setting) V is 0 at the far level and 1 at the shape ((segments - level) /
  segments, the level counted from the shape), and with Real-World Map Size that V times the signed amount: the
  amount at the shape, 0 at the far level (FixtureExtDownStart, FixtureExtDownEndReal); V follows the levels, not
  z (a shape at z 3 alike). U and the caps' box mapping are as upwards; `tests/unit/test_extrude.py` NEG_PROBES
  holds every corner of nine probed shapes. A closed spline
  that runs the other way than its role (a clockwise solid, a counter-clockwise hole) is turned whole: its U starts
  at its last interpolated point and runs back (arc_pie_reverse: FixtureClockwiseExt, FixtureHoleExt's Circle, the
  reversed pies; `tests/unit/test_extrude.py` compares every corner with `arc_pie_reverse.maps.jsonl`, the
  evaluated meshes 3ds Max gave, which the fixture's script writes).

Scene A: 20 shapes with an Extrude (the census), all evaluated: vertex and triangle counts equal 3ds Max's on all
20, the world box within 1e-3 plus the oracle's 6 significant digits on 16; the other 4 have an Edit Mesh or an FFD
above the Extrude, which are not evaluated.

## UVW Map

The UVW Map modifier (ClassID `(0xF72B1, 0)`, superclass `0x810`; `convert/uvwmap.py`, `tests/unit/test_uvwmap.py`
against the oracle's `eval_maps` of the uvwmap, uvwmap_oblique and uvwmap_pole fixtures, and of modifier_pivot and
stack_basic)
references
`[gizmo Position/Rotation/Scale, old ParamBlock]`:

| Index | Parameter | uvwmap fixture |
|---|---|---|
| 0 | map type: 0 planar, 1 cylindrical, 2 spherical, 3 shrink-wrap, 4 box, 5 face, 6 XYZ to UVW | every type but face and XYZ to UVW |
| 1, 2, 3 | U, V, W tile (`f32`) | FixtureUVWGizmo 2, 3, 1.5 |
| 4, 5, 6 | U, V, W flip | FixtureUVWGizmo U, FixtureUVWBox V, FixtureUVWCyl W |
| 7 | cap (cylindrical) | FixtureUVWCyl, FixtureUVWCylAxisX |
| 8 | 0 map channel, 1 vertex color channel (not applied by MaxDrop: no UV layer) | 0 |
| 9, 10, 11 | length, width, height (`f32`) | as 3ds Max fits them, or set: FixtureUVWGizmo 17, 23, 13 |
| 12 | alignment: 0 X, 1 Y, 2 Z | FixtureUVWCylAxisX and FixtureUVWTwo's spherical 0, FixtureUVWAxisY 1 |
| 13 | map channel | FixtureUVWGizmo 2, FixtureUVWTwo's spherical 3 |
| 14, 15 | not known; 0 everywhere | |

Real-World Map Size is not in the block: as on Extrude, `0x2150` holds `0x0110` entries, each a `0x0120` naming a
class (the first 8 bytes its ClassID) and a `0x0130` `u32`; the entry naming the modifier's own class holds the flag
(1 on FixtureUVWRealWorld). An instanced UVW Map (FixtureUVWSharedA/B) holds three entries. Read by
`maxdrop/reader/realworld.py`.

What 3ds Max 2020 computes (fitted to `meshop.getMapVert` on scratch scenes, then checked on the fixture: U and V
within 1e-4 for planar and box, 1e-3 for the round types):

- **Space**: a point p of the object goes to q = p * context * inverse(gizmo) (row vectors; the gizmo's matrix holds
  its scale; FixtureUVWSharedA/B have two contexts). Then a frame (a, b, c): planar and box `(-qx, -qy, qz)` for
  alignment Z, `(qz, -qy, qx)` for X, `(-qx, qz, qy)` for Y; cylindrical and spherical `(-qx, -qy, qz)` for Z,
  `(-qx, -qz, -qy)` for X, `(qz, -qy, qx)` for Y. Setting the alignment does not change the gizmo's matrix.
- **Planar**: u = a / width + 0.5, v = b / length + 0.5, w = c / height + 0.5. Real-World Map Size drops the 0.5 of
  u and v; it changes nothing on the other types.
- **Box**: the face normal, transformed like the points (not by the inverse transpose; uvwmap_oblique's spheres
  under turned, unevenly scaled and mirrored gizmos tell the two apart) and divided by (width, length, height), picks
  the axis k of its largest component, s its sign; with x, y, z = a / width, b / length, c / height: on ±a
  u = 0.5 + s·y, v = z + 0.5; on ±b u = 0.5 - s·x, v = z + 0.5; on ±c u = 0.5 + s·x, v = y + 0.5; w = the coordinate
  along k + 0.5.
- **Cylindrical**: X = a / (length / 2), Y = b / (width / 2); u = 0.5 + atan2(X, -Y) / 2π, v = c / height + 0.5,
  w = |(X, Y)|. Cap: a face whose normal, divided by (length / 2, width / 2, height), is largest along c gets
  u = 0.5 - Y / 2, v = 0.5 + X / 2, w = c / height / 2.
- **Spherical**: Z = c / (height / 2), r = |(X, Y, Z)|; u as cylindrical, v = 0.5 + asin(Z / r) / π, w = r.
- **Flip, tile**: per component, flipped (1 - value), then times its tile.
- **Seam**: a face with an edge across the seam (X = 0, Y > 0) between two corners off the axis: 3ds Max moves its
  corners above 0.5 down a turn (0.97 to -0.03), and so does MaxDrop. Another turn would show the same image only
  with a whole-number U tile: with U tile 2.5 (uvwmap_pole's FixtureUVWPoleTile, FixtureUVWPoleSphereTile, also
  flipped; scratch probes with -1.5) a turn is 2.5 units, half an image off; MaxDrop's earlier +1 below 0.5 was. On
  the other fixtures, which have whole-number tiles, a face may still differ from 3ds Max's by whole units. A face
  that goes around the axis (FixtureUVWCylAxisX: 4 triangles; uvwmap_pole's 8 at a vertex pushed past the bound)
  has no single U; there the two differ.
- **Axis**: a corner on the axis has no angle. Cylindrical: U 0.5 (times the tile), one map vertex shared by every
  face, also across the seam and also with cap on (a cone's apex on its side faces: FixtureUVWPoleCone). Spherical:
  the mean U of the face's other corners. On the axis means within about 1e-4 of it, so that a turned gizmo's float
  residue (about 1e-7) is a pole: cylindrical |(X, Y)| < 1e-4, spherical |X| and |Y| each < 1e-4 · r. Found by
  pushing an axis vertex off on scratch scenes (9.5e-5 still a pole, 1.05e-4 not; (7.5e-5, 7.5e-5) not on a
  cylinder, (9.5e-5, 9.5e-5) still on a sphere; a sphere's bound halves where Z at the pole is 0.5:
  FixtureUVWPoleSphereTall, pushed 6e-5 under a gizmo of height 32, has the angle); exactly at 1e-4 3ds Max's
  single-precision results disagree with each other. uvwmap_pole: the axis vertices of cylinders, spheres and a cone
  under turned gizmos, also pushed just inside and past the bound; every corner equals 3ds Max's, in its own turn.
- **Center**: a corner at a spherical gizmo's center gets V 0.5 and the mean U of its face's other corners
  (FixtureUVWPoleCenter: a cylinder's cap center under a turned gizmo). 3ds Max does so only where its
  single-precision point is exactly zero: on scratch scenes a push of 1e-20 radii already gives the angle (a push
  smaller than half a float ulp of the vertex's coordinates is lost when the vertex is stored, and is zero).
  MaxDrop's float64 point of the same vertex is a residue of about 2e-16 radii: below 1e-9 radii it is the center.
  Under a turned gizmo, a vertex 1e-7 to 1e-5 radii off the center gets an angle from 3ds Max's own
  single-precision noise, which MaxDrop does not match.
  On purpose: that close to the center the rounding of a single-precision point is not negligible against its
  distance from the center, so 3ds Max's angle there comes from its rounding, not from the scene; matching it would
  need a single-precision copy of the gizmo transform in 3ds Max's operation order, which the probes did not
  determine, and could move the pole and center cases uvwmap_pole pins. What it costs: a few corners of the fan
  around such a vertex (U off by up to about 0.1, V by up to about 0.15, as the em3.110 probes reported), rare.
  test_uvwmap pins the cut-off under an unturned gizmo: a corner 1e-7 radii off has the angle.

Evaluated: the UVW Maps that render right above the base object or above an applied Extrude (FixtureUVWExtrude;
FixtureUVWTwo, two in a row). One above another modifier (FixtureUVWAboveBend), a switched-off one (FixtureUVWOff)
and shrink-wrap (FixtureUVWShrink) leave the stored channel.

Scene A: 29 UVW Map modifiers (the census), 27 box and 2 planar, on 66 nodes; 23 evaluated, on 51 nodes; the other
6 sit above an Edit Mesh or an FFD, which are not evaluated.

## Modifiers converted to Blender modifiers

TurboSmooth `(0x0D727B3E, 0x491D29A7)`, MeshSmooth `(0x32, 0x7F9E)`, Shell `(0x3B9B1A16, 0x6D84E8D0)` and Symmetry
`(0x2D7E702B, 0x0BE41A6E)`, superclass `0x810`, each keep one ParamBlock2 in reference slot 0; Symmetry's mirror
gizmo is a Position/Rotation/Scale controller in slot 1 (`convert/modifiers.py`; read on two scratch scenes of 3ds
Max 2020 with every parameter set apart from its default, then the stack_convert fixture):

| Class | Parameter id: parameter |
|---|---|
| TurboSmooth | 0 iterations, 1 use render iterations, 2 render iterations, 3 isoline display, 4 smooth result, 5 separate by materials, 6 separate by smoothing groups, 7 update (radio), 8 explicit normals |
| MeshSmooth | 9 method (0 classic, 1 quad output, 2 NURMS), 4 iterations, 2 smoothness, 13 use render iterations, 14 render iterations, 15 use render smoothness, 16 render smoothness, 5 smooth result, 6 separate by materials, 7 separate by smoothing groups (and about twenty others: soft selection, cage, local control) |
| Shell | 0 inner amount, 1 outer amount, 2 override material ID (edges), 3 its ID, 4 override smoothing group, 5 the group, 6 edge mapping, 7 TV offset, 8 override inner material ID, 9 its ID, 10 and 11 select edge / inner faces, 12 segments, 13 straighten corners, 14 auto smooth, 15 its angle, 16 select outer faces, 17 override outer material ID, 18 its ID, 19 bevel edges, 20 bevel shape |
| Symmetry | 0 axis (0 X, 1 Y, 2 Z), 1 slice along mirror, 2 weld seam, 3 threshold, 4 flip |

What 3ds Max 2020 makes, against Blender's evaluated meshes (`tests/blender/run.py`, the oracle's `eval_verts`,
`eval_faces`, box and `eval_mesh.smoothing` after the stack):

- **TurboSmooth, MeshSmooth NURMS**: Catmull-Clark on the control points, not the limit surface: a
  box gives 26 vertices after one iteration, 98 after two, and Blender's Subdivision Surface with
  `use_limit_surface` off has the same vertices (the limit surface shrinks the box to 8.4 of 10). MeshSmooth classic
  is another scheme (80 vertices after two iterations). Separate by smoothing groups keeps the vertex count and
  hardens the edges between groups (a crease of 1 in Blender).
  An open mesh's boundary is smoothed along itself (1/8, 6/8, 1/8 of a vertex and its two boundary neighbours), but a
  corner (a boundary vertex of one face) stays where it is: Subdivision Surface's `boundary_smooth` PRESERVE_CORNERS
  (ALL, Blender's default, moves it). It shows under a Symmetry: an open half box (its top and half deleted) keeps
  the corner where the cut meets the top on the mirror plane, which welds it; with ALL it moves 1.25 of 10 off the
  plane and stays unwelded (FixtureTurboSymHalf: 39 vertices, 64 triangles in 3ds Max and Blender 4.2, 4.5 and 5.2;
  41 with ALL; probed, not in a fixture: a Shell above, 78 and 152, (0, 3, 24), as 3ds Max). MeshSmooth quad output
  is another scheme: the same counts, but every boundary vertex stays and the half box's corner (10, -10, 0) goes to
  the mean of its edges' midpoints (8.33, -6.67, 3.33), not Catmull-Clark's (7.78, -5.56, 4.44): a line in the
  report.
- **Shell**: the new surfaces lie at -inner and +outer amount along the vertex normals, not at an even thickness: a
  box with outer amount 2 grows by 2 / √3 along each axis (Solidify with `use_even_offset` off). Both may lie on
  one side of the original (inner -1, outer 2; inner 3, outer -1): Solidify's offset (hi + lo) / (hi - lo) past
  -1 .. 1 places them alike (no hard range). The outer surface faces out and the inner one in wherever they lie, so
  inner + outer < 0 turns the shell inside out (negative signed volume): Solidify with `use_flip_normals`
  (stack_shell, checked by the facing of the open boxes' triangles). The rim of an open mesh: 3ds Max gives it
  smoothing groups of its own, hard against both surfaces; auto smooth (id 14, on by default, angle id 15, 45°)
  also splits it where two rim faces meet at a sharper angle, and with auto smooth off the rim is one group, the
  override's (ids 4, 5) when set, which merges into a surface face of that group (an open box: 11 regions and 24
  hard edges; a plane with auto smooth 6 and 12, without 3 and 8). Solidify smooths the rim into both surfaces (the
  open box: 3 regions, 16 hard edges); MaxDrop marks the mesh's open edges sharp before it, which gives 3ds Max's
  open box on Blender 4.2, 4.5 and 5.2, also below a TurboSmooth with Smooth Result (3 regions, 16 hard edges: the
  Subdivision Surface keeps the sharp open edges). Not with a smoother with Smooth Result above the Shell (3ds Max
  smooths the rim too: 1 region). A Symmetry (weld on) below the Shell welds the open edges on its plane shut: 3ds
  Max makes no rim there, and marked sharp they would become a hard seam in Blender, so MaxDrop leaves out the open
  edges whose two ends Blender's Mirror merges with their copies (closer than the threshold to the copy, half that to
  the plane: 0.049 off the plane welds at 0.1, 0.051 does not). Measured on half and quarter boxes (FixtureShellSymHalf
  (0, 11, 40), FixtureShellSymClosed (0, 12, 40), FixtureShellSymQuarter with two Symmetries (0, 11, 40); also a
  TurboSmooth between the Symmetry and the Shell, the cut 0.04 off the plane, the rim crossing the plane) Blender 4.2,
  4.5 and 5.2 give 3ds Max's counts; all open edges sharp give a seam (FixtureShellSymHalf 17 regions, 48 hard edges), none
  the smooth rim (the probe's half box of 2 segments along X: 3 and 20, 3ds Max 11 and 32). With the weld off the plane's open edges make a rim in both, whose corners against the
  top's are auto smooth's (a line in the report). A Symmetry above the Shell cuts the hardened rim as 3ds Max does
  (the open box: (0, 11, 32) in both, 3ds Max leaving the seam unwelded). What stays different is a line in the
  report, only for a mesh with open edges: auto smooth on and rim corners sharper than its angle (the rim face of
  open edge a -> b has the normal (pb - pa) x (na + nb), n the sum of the unit face normals at a vertex, on the
  mesh below the modifiers: a plane keeps its 4 corners under 1 to 3 TurboSmooth iterations below the Shell, 6
  regions; FixtureShellPlane: 4 corners; above Symmetries, counted on the mesh with its welded copies, unless that
  mesh would pass 4M face corners), or the
  override group with auto smooth off (the group is a number, 1 .. 32: group 4 is the side of mask 8;
  FixtureShellOverride). A crease on an open edge (a smoother that separates by smoothing groups) is left out.
  A Shell below a Symmetry (slice and weld on) whose rim along the cut lies on the slice plane: 3ds Max 2020's slice
  drops that rim (faces within 1e-4 system units of the plane; 1e-3 off they stay, doubled) and the weld shuts the
  cut, where Blender's bisect keeps them (the open half box of 2 x 2 segments: 34 vertices, 64 triangles, (0, 11, 40)
  in 3ds Max; 72 triangles, (0, 19, 40) and two false rim corners in Blender with the Mirror above the Solidify).
  MaxDrop moves such a Mirror below the Solidify, which welds the cut before the shell is made: 3ds Max's counts and
  shading on Blender 4.2, 4.5 and 5.2 (FixtureShellUnderSym; FixtureShellUnderSymTurbo, a TurboSmooth above: 130
  vertices, 256 triangles, (0, 1, 0); FixtureShellBetweenSym, a Symmetry on each side; FixtureShellUnderSymExtrude, an
  open Line under an Extrude: 24, 48, (0, 10, 32); the probe also: inner 1 outer 0, a closed half, a quarter under two
  Symmetries, the gizmo 1e-5 off or turned 1e-4 degrees). The rule (convert/scene/rims.py lowered()): per Symmetry right
  above the lowest Shell (only Symmetries below it), on the mesh with the copies of those below, the open edges with
  both ends within 1e-4 units of its plane (at most 1 mm, Blender's bisect distance; float32 positions some 1000 units
  from the origin along the axis pass 1e-4, and keep the order); none: it stays; moved when it slices and welds those
  ends and every face at them is square to the plane (|cos| <= 1e-5), else a line in the report: weld off (3ds Max
  leaves the cut open: FixtureShellUnderSymNoWeld 64 triangles, Blender 80), slice off (3ds Max keeps both copies of
  the rim: 80, Blender 72), the cut's faces slanting across the plane (3ds Max slices the shell: 37 vertices, Blender
  34). With the slice on, the rim's corners are counted there as if the cut were welded (3ds Max has none there). Only
  the open edges on the plane decide: others within the weld threshold of it are welded too once the Mirror is moved,
  where 3ds Max keeps their rim. A mesh that with its copies would pass 4M face corners is not tested (a line). A
  gizmo 1e-3 to 0.04 units off the cut, or turned 1e-3 degrees, keeps the rim in 3ds Max too (80 or 72 triangles,
  Blender 72): no line. A mesh light's emitter keeps 3ds Max's order.
- **Symmetry**: the mirror plane is in the gizmo's space, q = p * context * inverse(gizmo), as UVW Map's; without
  flip the side where q along the axis is positive stays, sliced at the plane; without slice the whole object is
  mirrored and both copies stay (FixtureSymmetryNoSlice: 16 vertices). Weld seam: 3ds Max slices beside a vertex
  that lies within the threshold of the plane, Blender's Mirror merges it with its copy onto the plane
  (FixtureSymmetryTurned, a corner 0.062 off the plane, threshold 0.2: boxes 0.031 apart). On a shelled box (FixtureOrder)
  3ds Max leaves the seam unwelded (32 vertices, 100 after a TurboSmooth; Blender 84): the same surface.

Scene A: of its 2 TurboSmooth, 1 Shell and 1 Symmetry (the census), 1 TurboSmooth is converted; the rest sit on a
shape without an Extrude below them (a curve). Scene B: TurboSmooth on 105 nodes, MeshSmooth on 51, Shell on 2
converted; 6 TurboSmooth sit above an FFD(box).

## Primitives

The standard primitives, superclass `0x10`, keep one ParamBlock2 in reference slot 0 and no mesh: 3ds Max builds
the mesh from the parameters each time (`convert/primitives/`; ids read on scratch scenes of 3ds Max 2020 with
every parameter set apart, the meshes compared vertex for vertex with `o.baseObject.mesh` on about 80 of them, then
the primitives fixture and its `primitives.mesh.jsonl`). Lengths in file units, angles in radians:

| Class (ClassId) | Parameter id: parameter |
|---|---|
| Box `(0x10, 0)` | 0 length (Y), 1 width (X), 2 height (Z), 3 width segments, 4 length segments, 5 height segments, 6 generate mapping coords |
| Plane `(0x081F1DFC, 0x77566F65)` | 0 length, 1 width, 2 width segments, 3 length segments, 4 density, 5 render scale, 6 mapping |
| Pyramid `(0x76BF318A, 0x4BF37B10)` | 0 width, 1 depth, 2 height, 3 width, 4 depth, 5 height segments, 6 mapping |
| Sphere `(0x11, 0)` | 0 radius, 1 segments, 2 smooth, 3 hemisphere (0 .. 1), 4 squash (0 chop), 5 base to pivot, 6 mapping, 7 slice, 8 slice from, 9 slice to |
| GeoSphere `(0, 0x7F9E)` | 0 radius, 1 segments, 2 base type (0 tetra, 1 octa, 2 icosa), 3 hemisphere (a switch), 4 smooth, 5 base to pivot, 6 mapping |
| Cylinder `(0x12, 0)` | 0 radius, 1 height, 2 height segments, 3 cap segments, 4 sides, 5 smooth, 6 slice, 7 slice from, 8 slice to, 9 mapping |
| Cone `(0xA86C23DD, 0)` | 0 radius 1, 1 radius 2, 2 height, 3 height segments, 4 cap segments, 5 sides, 6 smooth, 7 slice, 8 slice from, 9 slice to, 10 mapping |
| Tube `(0x7B21, 0)` | 0 radius 1, 1 radius 2, 2 height, 3 sides, 4 cap segments, 5 height segments, 6 smooth, 7 slice, 8 slice from, 9 slice to, 10 mapping |
| Torus `(0x20, 0)` | 0 radius 1, 1 radius 2, 2 rotation, 3 twist, 4 segments, 5 sides, 6 smooth (0 none, 1 groups alternating by side, 2 all, 3 alternating by segment), 7 slice, **8 slice to, 9 slice from** (the other way round from the rest), 10 mapping |

Real-World Map Size is not in the block: `0x2150{0x0100 u32 1, 0x0110{0x0120 the class (classA, classB,
superclass, 4), 0x0130 u32 flag}}` in the object's chunk; there is no `0x2150` while mapping is off. Read by
`maxdrop/reader/realworld.py`, as on Extrude and UVW Map.

What 3ds Max builds (the TriMesh; MaxDrop merges two triangles that share an edge hidden in both, each with only that
edge hidden, into the quad 3ds Max shows, and keeps every other triangle, so a cap's fan stays triangles around its
center vertex and the vertex and triangle counts are 3ds Max's, which the oracle's `eval_verts` / `eval_faces` are):

- **Box**: a lattice of segments, each side a grid. IDs (one-based) bottom 2, top 1, front (-Y) 5, right (+X) 4,
  back 6, left 3; smoothing groups 2, 4, 8, 16, 32, 64 in that order; each side's UV 0..1 (U along +X on top and
  front, -X on bottom and back, +Y right, -Y left; V along +Y on top and bottom, up on the sides). The sizes are
  signed: a negative size hands the role of a side (its ID and UVs) to the opposite one (top and bottom when an odd
  number of sizes is negative, front and back when the width is, left and right when the length is), while the
  smoothing group stays with the side's place; the faces point in when width and length differ in sign (3ds Max's
  own box: FixtureBoxInside). Plane: one grid, ID 1, group 1, facing up when width and length have one sign, else
  down with ID 2 and U running back.
- **Pyramid**: the apex, rings of the base outline scaled by k / segments, the base center. Groups front 4, right 2,
  back 16, left 32, base 8; ID 1. Side UVs: apex (0.5, 1), V = z / height, U = 0.5 + x / width on the front (back:
  minus), U = 1 - width / (2 depth) + y / depth on the right (left: minus); base U = 0.5 + x / width, V = 0.5 - y /
  depth.
- **Sphere**: poles at ±radius, rings at polar angles k · 360° / segments for k below segments / 2 (an odd count
  leaves a wider last row), each from +Y turning towards -X. ID 2, group 1 (0 unsmoothed). UV: U = j / segments, V =
  1 - 2k / segments (the south pole at 1 - 2 · floor(segments / 2) / segments). Base To Pivot raises it by the radius.
- **GeoSphere**: the base solid (tetrahedron with a vertex on +Z, octahedron, icosahedron with a vertex on +Z and
  its upper ring from +X), each face subdivided in rows of equal angles (a slerp along both edges, then along the
  row), the apex of each face the first of its corners (the icosahedron's band: the lone corner). Smooth: ID 2, group
  1; else ID 1, group 0. UV per face: U = 0.5 + atan2(y, x) / 360°, V = 1 - polar angle / 180°; a face spanning more
  than half a turn brings its corners past 3/4 down by one; a pole takes the mean of the face's other corners. A
  point on the -X meridian sits a rounding error to either side of it in 3ds Max (U 0 in some faces, 1 in others):
  MaxDrop's float rounding decides that differently, a whole turn on a few faces near that meridian.
- **Cylinder, Cone**: center fans and cap rings, the side in height segments; vertices from +X counterclockwise.
  IDs: bottom fan 2, bottom cap rings 1, side 3, top cap rings 2, top fan 1 (the rings take the other cap's ID);
  groups caps 1, side 8 (0 unsmoothed). UV: U = 0.75 + j / sides, each face shifted down a whole turn while its end
  would reach 1; V = z / height on the side; the caps take the side's U with V 0 or 1 (degenerate), and a ring of
  radius 0 (a cone's tip) U 0.5, the face below it without the seam's shift. Real-World Map Size: the side in file
  units (U by 2π · radius 1), each cap flat over its rim's extent (U = x - min x, V = max y - y below, y - min y on
  top). A negative height flips every face so that they point out.
- **Tube**: the profile (outer side up, top inwards, inner side down, bottom outwards) swept from +Y turning towards
  +X; the outer side's role (ID 3, the profile's start) is the larger radius's, the smaller one's under a negative
  height (the faces then point out without a flip). IDs outer 3, top 1, inner 4, bottom 2; groups sides 2, caps 4
  (all 0 unsmoothed). UV: U along the profile (q / profile points), V = j / sides; Real-World Map Size: U = (1 - j /
  sides) · 2π · the larger radius, V the distance along the profile (the height signed, the caps' widths).
- **Torus**: segments around Z from +Y towards +X, each ring of sides from the outer equator upwards, turned by
  rotation + twist · (segment + 1) / segments. ID 1. Groups: smooth 0 none, 2 all 1, 1 alternating 2 / 1 by side
  (4 on the last of an odd count), 3 the same by segment. UV: U = side / sides, V = segment / segments; Real-World
  Map Size: U = (1 - segment / segments) · 2π · radius 1, V = side / sides · 2π · radius 2.

**Slice and hemispheres** (probed on about 300 meshes of a headless 3ds Max 2020, then the primitives fixture's
eleven nodes for them). Slice keeps the arc From - To (in 0 .. 360 degrees, 0 a whole turn) and builds it with as many
steps as the full turn has segments or sides:

- **Sphere hemisphere**: the cut at polar angle (1 - hemisphere) · 180° (hemisphere at most 0.9999). Chopped, the
  rings keep their places every 360° / segments down to the cut, counted in single precision (k · Δ ≤ cut), then a
  ring at the cut: a ring that falls on the cut is doubled there, a row of flat faces. Squashed, segments // 2 - 1
  rings spread over the cut (Δ = cut / (segments / 2 - 1)), the last on it. A base fan to a center on the cut plane,
  ID 1, group 2 (0 unsmoothed); V by row, 1 - 2k / segments as on the full sphere, the base center one row further;
  the base flat in real-world mode (U = x - min x, V = max y - y over its rim). Base To Pivot raises it by -radius ·
  cos(cut), which puts the base on the pivot. Two of the 187 chopped cases probed (20 segments, hemisphere 0.1 and
  0.3, a ring exactly on the cut) round the other way in 3ds Max: MaxDrop has a row of flat faces more or fewer.
- **Sphere Slice**: segments + 1 points per ring from To (measured from +Y towards -X), then a point on the axis
  per ring; each row ends with the faces of its two cut planes, the end's ID 3 group 4, the start's ID 4 group 8 (0
  unsmoothed); a hemisphere's base fan centers on its last ring's axis point. U across the arc as a fraction of the
  whole turn; the planes U 1 at the rim, 0 on the axis. Real-world: the planes flat, U from the axis (from the widest
  ring on the end's plane), V up from the lowest ring; the bottom pole's two plane faces keep the sphere's UVs.
- **GeoSphere hemisphere**: the faces above the equator of a tetrahedron whose three lower corners are raised onto
  the equator, of the octahedron, or of the icosahedron split in four at its edges' midpoints (the corner triangles
  from their corner of the face, the middle one from the midpoint across from the face's first corner), each split
  in segments as before; a fan from the equator to the center, ID 1, group 2. It stands on the pivot, Base To Pivot
  or not; the center takes U as a pole does, V 0.5.
- **Cylinder, Cone Slice**: the profile's rings (bottom cap inside out, side, top cap outside in) from To (from
  +X, counterclockwise), sides + 1 points each, every ring after a point on the axis, those spread evenly from the
  bottom center to the top center. Per pair of rings: the start's plane (two triangles, ID 4, group 2), the quads,
  the end's plane (ID 5, group 4); fans and IDs otherwise as without Slice. A negative height walks the arc back from
  From instead of flipping the faces, and its U runs down (a face shifted down a turn while its larger U passes 1).
  The planes' U 0.5 on the axis, V up it; real-world: the start's U from the axis, the end's back from its rim along
  the direction of the last side step's start, both V up from the lowest point.
- **Tube Slice**: sides + 1 columns of the profile from From (from +Y towards +X), V = column / (sides + 1); a fan
  around the profile's middle at each end, the start's ID 5, the end's ID 6, group 1 also unsmoothed; real-world U
  around the arc times the larger radius, the planes flat (U in from the outer radius at the start, out from the
  inner one at the end, V up from the lowest point).
- **Torus Slice**: segments + 1 columns from From, Twist spread over the columns (twist · (column + 1) / (segments +
  1)); smoothing by segment alternates without a last row apart; a fan around the tube's center at each end, the
  start's ID 2, the end's ID 3, group 8; real-world as the Tube's.

A Slice whose end lands a float's rounding from U 1 (From 0 To 360, an arc of 0.01°) can give one face's U a whole
turn from 3ds Max's. Plane's render scale and density act at render time only (built at the viewport size, a line in
the report). Teapot is not built. A primitive past 2^21 face corners (`MAX_CORNERS`) is refused: a file can ask for
any number of segments.

## VRayLight

VRayLight `(0x3C5575A1, 0x5FD602DF)`, superclass `0x30` (light), V-Ray 5.2 in 3ds Max 2020 (`convert/lights/`;
ids read through the SDK's .NET wrapper on a scratch scene, then the vray_lights fixture read back by the reader).
Reference 0 is a ParamBlock2 (block id 0), reference 2 the viewport icon object. Parameter ids, lengths in file
units:

| Id | Parameter |
|---|---|
| 0, 1 | on; type: 0 plane, 1 dome, 2 sphere, 3 mesh, 4 disc |
| 2, 3, 4 | size0, size1, size2: a plane's HALF length along its local X and half width along local Y (a V-Ray render of size0 10, size1 30 from below is 20 by 60); a disc's and a sphere's radius in size0 |
| 7, 8, 12 | color; multiplier; units (`normalizeColor`): 0 default (image), 1 lm, 2 lm/m²/sr, 3 W, 4 W/m²/sr |
| 9, 10 | double-sided; invisible |
| 18, 19 | texmap (a map reference), texmap on |
| 25, 26, 30 | affect diffuse, affect specular, affect reflections |
| 27 | dome spherical (`dome_spherical`; V-Ray 5.2's default on; off: the half above the dome's local XY plane) |
| 32 | cast shadows (`castShadows`, the light's own switch; default 1, also for a VRayLight MAXScript makes) |
| 34 | mesh source (`mesh_source`, a node reference) |
| 35 | flip normals (`mesh_flip`): a mesh light emits on the other side |
| 36 | directional (`lightDistribution`) |
| 38, 39 | color temperature (K); color mode: 0 color, 1 temperature |
| 43 | targeted (the node has a Look At controller and a Target, [Look At](#look-at)) |
| 49 | texture locked to the dome (`texmap_locktodome`; default 0) |
| 53, 54 | diffuse contribution, specular contribution |

In temperature mode V-Ray also stores its own color of that temperature in 7 (3500 K: 1.0, 0.584, 0.256); MaxDrop
takes the curve of the rules source instead (3500 K: 255, 192.5, 140.8 as an sRGB swatch). `on:false` given to the
MAXScript constructor does not stick (the fixture script sets it afterwards), and `targeted:true` there makes no
target.

**Shadows.** Parameter 32 off: the light casts no shadows (`Light.use_shadow` off; not stored: on). Read with a
VRayLight's block dumped before and after `baseObject.castShadows = false` (3dsmaxbatch, the .NET wrapper): 32 is
the only parameter that changes. MAXScript's `light.castShadows` is the node's Cast Shadows render flag, not this
switch. The vray_lights fixture's FixtureNoShadow has it off. A dome with it off is a line in the report: Blender's
World has no such switch.

**Power.** The rules source's watts (its `ocbaby_exsVrayLightWatts`): emitting area `a` = plane 2 size0 × 2 size1,
disc π size0², sphere 4π size0² (m², doubled for a double-sided plane or disc); 1 lm: `m / 683`, 2 lm/m²/sr:
`π m a / 683`, 3 W: `m`, 4 W/m²/sr: `π m a`, default: `m a · 1500 / 683`. Compared with V-Ray 5.2 renders (below),
one change: in lm/m²/sr and W/m²/sr V-Ray lights a disc as if `a` were (2 size0)², 4/π more than its area; in the
default units it does not. Blender's area light shines on one side: a double-sided plane or disc gets half.

**A scaled node.** V-Ray grows the emitting area with the node's scale; in the units that follow the area (default,
lm/m²/sr, W/m²/sr) the flux grows with it, in lm and W it does not. Measured on lights scaled 2, 1.5, 1 (the scratch
scene below): plane and disc 3 × the unscaled flux (X × Y scale). A sphere takes its X scale alone and stays round
(a W/m²/sr sphere above a white floor: 4 × at (2, 2, 2) and (2, 1.5, 1), 1 × at (1, 2, 1), (1, 1, 2) and
(1, 2, 3); seen by the camera, twice as wide at (2, 1, 1), half at (0.5, 1, 1), unchanged at (1, 3, 1)): radius
size0 × X scale, area × X². Blender scales an area light's size with its object and keeps its power, so the power
takes that factor (`area_scale`), and instances of one light with different scales get a light each. Blender's
point light keeps its radius whatever its object's scale (Blender 4.2.23, 4.5.16 and 5.2: a camera-visible light in
Cycles 0.48 m across at every scale, EEVEE's penumbra unchanged), so a sphere's radius takes the X scale, in every
units mode (its key holds X² there too). The vray_lights fixture's FixtureDiscScaled and the vray_dome fixture's
FixtureSphereWide (2, 1, 1, in W: radius twice, flux the same) and FixtureSphereTall (1, 1, 2.5: as unscaled) are
such nodes.

**Mesh light → emissive mesh.** The light's mesh object is its reference 1 when that holds one, else the object of
the node parameter 34 names. V-Ray's Pick mesh with "Replace mesh with light" on (picked in V-Ray's panel in 3ds Max
2020) deletes the picked node, gives the light node its transform, leaves parameter 34 empty and keeps the node's
object in the light's reference 1 (the base object itself, or its DerivedObject when it has modifiers); a
`mesh_source` set by a script leaves reference 1 empty, and `refs.replaceReference` of reference 1 writes the
first structure (the vray_mesh_light fixture's FixtureEmitterOwn). Measured (V-Ray 5.2, the calibration below with
a mesh light 1 m above the floor, its mesh a Plane 200 × 200 mm far away):

- V-Ray emits the mesh object's mesh in its **object space**, placed at the light node's object transform: the
  footprint follows the light's position, turn and object offset; the source node's position, turn, scale and
  object offset do not matter; a later change of the mesh shows; with the node deleted (parameter 34 empty) it emits
  nothing.
- One side, along the faces' normals (turned away: 0); Flip normals (35) the other side; the camera sees the back
  black, and an invisible one not at all. Double-sided: both sides, each with half the radiance in W (0.0715
  against 0.143).
- The flux of the units mode spread over the **object-space** area `a` of the mesh as a Lambertian emitter (flux = π
  L a): W 1 0.143013 (a plane VRayLight of 1 W and the same size: 0.142992), lm 683 the same (683 lm/W, not the
  dome's 671.8), default 1 0.0125633 (m a 1500 / 683 W), W/m²/sr 1 0.0179715 (π m a); the light node scaled (2, 2,
  1) gives 4 × the floor of a 400 × 400 mesh in W too: the node's scale does not change the radiance. A Shell on the
  mesh (5 mm) halves it in W: the area is the evaluated mesh's.
- Seen by the camera (W 1): 11.3833 = the radiance (1 / (π 0.04)) × π 683 / 1500.
- A visible mesh light shadows other lights (multiplier 1e-6 between a large plane light and the floor: 1.56
  against 2.73); an invisible one, or one that is off, does not.

So the radiance is: default m 1500 / (683 π), lm/m²/sr m / 683, W/m²/sr m, W m / (π a), lm m / (683 π a), with `a`
doubled for a double-sided one in W and lm. MaxDrop makes the mesh object's base mesh (Editable Mesh, Editable Poly,
a primitive it builds) in object space with the light node's offset, the light node a mesh object of it, and an
Emission of that radiance × Light Strength (Cycles renders an Emission of strength S as S): one side through a Mix
by Geometry Backfacing with a black Emission (flipped for 35), both sides when double-sided; invisible: camera and
shadow off. The `calib_*` scenes of the calibration (W, default, lm, double-sided, flipped, seen by the camera)
imported and rendered in Cycles (Blender 5.2, 512 samples, the floor a Diffuse BSDF of 1.0, Light Strength 1.43):
V-Ray / Cycles 1.0003 to 1.0004. The modifiers of the mesh are those of any mesh (maxdrop-em3.162): a shape under
an Extrude right above it is extruded; its UVW Maps are left out (an emitter has no texture); the TurboSmooth,
MeshSmooth, Shell and Symmetry above it become Blender modifiers on the emitter (with the light node's offset), and
in W and lm the radiance is spread over the mesh under them: build.emitters measures a copy of the emitter object
(shown, a Subdivision Surface at its render levels within the viewport budget) and scales the object-space area by
the evaluated over the unmodified area. The 30 × 10 mm plane under a 2 mm Shell of the vray_mesh_light fixture
(FixtureEmitterOwn) emits over 2 × 300 + 80 × 2 = 760 mm² (Blender's Solidify), as the 5 mm Shell above (0.143 →
0.0679 in W: 0.04 / 0.084 m²) says V-Ray does. Not measured against V-Ray: a TurboSmooth or Symmetry under a mesh
light (Blender's evaluated area is taken). Any other modifier is left out (a line in the report: the mesh below it
emits); no mesh object, or a class MaxDrop does not build, is an empty with a line in the report. A mirrored light node follows the rules of every mesh (an offset with a negative determinant
reverses the loops, a mirrored node is left to Blender), so the lit side is the mesh's front as Blender sees it: not
measured against V-Ray.

**Dome light → World.** The first dome node that is on becomes the scene's World (a new World, assigned to the
scene; the one before is kept, with a fake user when it has no other, and the report says so; in an import of
several files the first file's dome); another dome node, an instance of it too, or one that is off is a line in the
report; dome nodes stay empties (not placeholders). A World that cannot be built is a line in the report, the scene
is imported all the same. Measured in V-Ray 5.2 (scratch scenes): a white
floor under a white dome of multiplier 1 renders 1.00018 in the default units, 0.00213024 in lm and lm/m²/sr, 1.43109
in W and W/m²/sr (a dome has no area: the flux and the radiance units agree); Cycles renders a white floor under a
white World of strength S at S (1.00002 for 1). So the World's strength is the multiplier × 1500 / (683 π), ×
1 / 671.8 (0.00213024 / 1.43109) or × 1 in the three pairs, times Light Strength: in the default units 0.9995 of
V-Ray's at 1.43. A texture replaces the color (a dome color 255, 64, 64 leaves a white texel white) and takes the
same multiplier and units. With spherical off only the half above the dome's local XY plane shines (a downward-facing
white plane gets 0; the camera sees 0 below; turned 180° about X the lower half shines; the position does not
matter): a Math node masks the strength by the local Z of the direction. Invisible: World camera rays off (Cycles'
`cycles_visibility`); affect diffuse / specular / reflections as a light's.

The texture: a VRayBitmap in spherical mapping (`mapType` 2; block 0: 3 horizontal rotation, 4 vertical rotation, 36
axial rotation, in radians; 5 horizontal flip, 6 vertical flip, 26 ground projection, read from a probe scene) gives u = 0.5 + φ / 2π + h / 360 (φ = atan2(y, x) of the direction in the texture's frame, h the horizontal
rotation in degrees) and v up the image; a Bitmap in spherical environment mapping (UVGen `0x9005` 1, `0x9009` 1, see
[Materials and maps](#materials-and-maps)) u = 0.75 + φ / 2π, as a VRayBitmap of h = 90. Lock to dome 0: the world's frame; 1: the dome
node's rotation (turned 90° about Z, the texture turns with it). Measured with a self-authored image of eight
colored blocks seen through cameras at ±X, ±Y and ±20° elevation. Blender's Environment Texture runs the other way
round (u = 0.5 − φ / 2π): the direction (Texture Coordinate Generated) goes through a Mapping node of scale
(1, −1, 1) and rotation Rz(−h) F T F (F the mirror in Y, T the axis conversion and lock turn into the texture's
frame). The vray_dome fixture (h 30, locked, its node turned 90° about Z, a hemisphere) and a tilted copy imported
with Y up give the same texels as V-Ray's renders. Other projections are drawn as spherical. A CoronaBitmap on a
dome is too, with a line in the report: V-Ray 5.2 does not project it (a camera at the dome's center sees one flat
color in every direction, for every `enviroMapping`, a U offset and a filtering blur of 0.01: 0.5 grey with the
eight-block image, its mean; W angle 30°: 0.65, 0.41, 0.41). The vertical and axial
rotation, the flips, the ground projection, an Output other than its amount, crop or placement and a Bitmap's offset, tiling
or angle are left out (a line each); a root other than an image map or a file not found leaves the World its color
(a line).

**Calibration of Light Strength (1.43).** A scratch scene (not committed): a white Lambert floor (VRayMtl diffuse
255, no reflection; in Blender a Diffuse BSDF of 1.0), an invisible VRayLight 1 m above it, plane, disc and sphere
of 100 mm size0 in each of the five units modes, each rendered alone through an orthographic camera looking down at
the floor below it, V-Ray 5.2 with color mapping linear, gamma 1, no clamp, no GI, 3ds Max's gamma off, into a float
bitmap, and the same `.max` imported by MaxDrop (Light Strength 1) and rendered in Cycles (512 samples, Standard view
transform): the mean of the 8 × 8 pixels at the center, V-Ray / Cycles, is 1.4313 to 1.4319 for every plane and disc
in every units mode (with the disc rule above; 1.822 without it in lm/m²/sr and W/m²/sr) and 1.4456 for the spheres.
The vray_lights fixture's own lights the same way, 0.05 to 0.09 m above the floor: 1.430 to 1.433 for its planes and
discs, 1.448 and 1.470 for its two small spheres. The default Light Strength is 1.43. Cycles ignores a light's
diffuse and specular factors (EEVEE uses them): the fixture's disc with diffuse contribution 0.5 is half as bright in
V-Ray as in Cycles.

## Standard and photometric lights

`convert/lights/`, 3ds Max 2020 + V-Ray 5.2; ids read through the SDK's .NET wrapper (ParamBlock2 descriptors) and
by changing one setting at a time on scratch scenes, then the lights_standard and lights_photometric fixtures read
back by the reader. All superclass `0x30`; every one shines along its local -Z.

**Standard lights.** Omni `(0x1011, 0)`, Target Spot `(0x1012, 0)`, Free Direct `(0x1013, 0)`, Free Spot `(0x1014,
0)`, Target Direct `(0x1015, 0)`. Reference 0 is an old ParamBlock, by index (colors 0..1): Omni 0 color, 1
multiplier, 2 contrast, 3 soften diffuse edge, 4 to 7 near and far attenuation start and end, 8 decay start; Spot
and Direct 0 color, 1 multiplier, 2, 3 the same, 4 hotspot, 5 falloff (a Spot's in degrees, a Direct's a radius in
world units), 6 aspect, 7 to 10 attenuation, 11 decay start. Reference 3 is the shadow generator, 4 an old
ParamBlock of shadow settings (color, density, ...; not the switch). The light object's own chunks:

| Chunk | Meaning |
|---|---|
| `0x2580` u16 | on |
| `0x2570` u16 | shadows on (1) or off (0); written in both states (absent: on, as MaxDrop read every light before) |
| `0x25D0` u16 | decay: 0 none, 1 inverse, 2 inverse square (absent: none) |
| `0x2573` u16 | cone shape (Spot, Direct): 1 circle, 0 rectangle |
| `0x2575` (empty) | overshoot |
| `0x25B0`, `0x25B1` (empty) | affect diffuse off, affect specular off |
| `0x2600` (empty) | ambient only |

**Photometric lights.** One class per shape (MAXScript's `type` changes the class): Free Light (point)
`(0x32375FCC, 0x0B025CF0)`, Free Line `(0x78207401, 0x357F1D58)`, Free Rectangle `(0x36507D92, 0x105A1A47)`, Free
Disc `(0x5BCC6D42, 0x0C4F430E)`, Free Sphere `(0x7CA93582, 0x1ABB6B32)`, Free Cylinder `(0x46F634E3, 0x0A327AAF)`;
Target Light (point) `(0x658D4F97, 0x72CD4259)`, Target Line `(0x45076885, 0x40791449)`, Target Rectangle
`(0x71794F9D, 0x70AE52F2)`, Target Disc `(0x38732348, 0x201758B3)`, Target Sphere `(0x33FC7AE9, 0x54433DC5)`,
Target Cylinder `(0x7C8B5B10, 0x4BD33E86)`. ParamBlock2s by block id (references 0, 1, 2, 3, 5; 4 is the shadow
generator):

| Block | Parameters |
|---|---|
| 0 | 1 distribution (0 isotropic, 1 spotlight, 2 uniform diffuse, 3 photometric web), 2 on, 3 cast shadows, 5 filter color, 6 intensity (always cd, whatever the units the panel shows: 2000 lm is stored as 159.15), 8 Kelvin, 10 use Kelvin, 13 intensity at (lux distance), 14 units shown, 18 use dimmer, 19 dimmer (%), 21 use far attenuation, 23 / 24 far start / end |
| 1 | shadows (atmosphere, color, ...) |
| 2 | 0 hotspot, 1 falloff (degrees) |
| 3 | 0 web file (an asset of type `Photometric`), 1 to 3 its X, Y, Z rotation |
| 4 | 4 affect diffuse, 5 affect specular, 6 ambient only, 11 length (a line and a rectangle along local Y, a cylinder), 12 width (a rectangle, along local X), 13 radius (disc, sphere, cylinder) |

The lamp color without Kelvin is a preset MAXScript does not reach and the fixtures do not store: white is taken.
MAXScript's `light.castShadows` is the **node's** Cast Shadows render flag (the node's `0x099C`, bit `0x200`), not the
light's switch, which is `light.baseObject.castShadows` (saves of one change each, maxdiff); a standard or photometric
light MAXScript makes has its shadows off, the two scenes of the corpus have them on.
3ds Max 2020 refuses a spotlight distribution on a cylinder.

**VRaySun** `(0x732C0383, 0x7D993776)`, block 0: 0 enabled, 1 turbidity, 2 intensity multiplier, 3 size multiplier, 5
ozone, 9 invisible, 12 sky model, 14 / 19 affect diffuse / its contribution, 15 / 20 affect specular / its contribution,
17 filter color, 18 color mode (0 filter, 1 direct, 2 override); no shadow switch in V-Ray 5.2 (16
`cast_atmospheric_shadows` only). A targeted VRaySun is a Look At node. **VRayIES** `(0x2EAF2F07, 0x7EC44F31)`, block 0:
0 enabled, 1 IES file (an asset of type `Photometric`), 7 color temperature, 8 color, 9 color mode (1 temperature), 10
power, 11 targeted, 14 / 30 affect diffuse / contribution, 15 / 31 affect specular / contribution, 32 intensity type (0
lm, 1 cd), 34 override intensity. 10 is lumens in both units of the override (the panel converts a cd value with
the IES file: an isotropic 100 cd file rated 500 lm stores 100 cd as 500; the photometric fixture, whose file does
not exist, stored its 300 cd as 300); 33 (`intensity_value`) is stored stale (0). 4 cast shadows; 5 use light shape
(0 no, 1 for shadows only, 2 for illumination and shadows), 21 override shape (off: the IES file's shape), 22 shape, 23 height, 24 width, 25 length, 26 diameter
(world units), 35 `shape_actual` (-1 without a file). The shapes, in the order of the panel's list (the stored value),
with the sizes the panel enables (H W L D): 0 point; 1 rectangle H W L; 2 circle D; 3 sphere D; 4 vertical cylinder H D;
5 / 6 horizontal cylinder along the length / width L D / W D; 7 / 8 ellipse, 9 / 10 ellipsoid (length / width), 11
elliptic cylinder, 12 / 13 horizontal elliptic cylinder (length / width) H W L; 14 vertical circle W; 15 vertical
ellipse H W; 16 cuboid H W L. MaxDrop gives the spot the radius of half the largest of those sizes when the shape is
used and overridden (a sphere's exactly, another shape a line in the report). A VRayIES's reference 1 is a Target Light
object of its own (no node). **Skylight** `(0x7BF61478, 0x522E4705)`: not built. **VRaySky** `(0x48480B4E, 0x62FF5A90)`
(superclass Texmap): the environment map is RenderEnvironment's reference 5 (the lights_standard fixture).

**Power, measured.** The calibration scene of [VRayLight](#vraylight) (a white VRayMtl floor, one light 1 m above it
pointing down, V-Ray linear, gamma off, no GI, the mean of the 8 × 8 center pixels): V-Ray's pixel is the floor's
illuminance in lx / 1500 for every class: a 1 W VRayLight sphere 0.0362 (683 / 4π lx); a Free Light of 1000 cd,
isotropic, spotlight or uniform diffuse, 0.667; a Free Rectangle 100 × 100 mm of 1000 cd 0.651; a VRayIES of 1000
lm with an isotropic IES file 0.0531; an Omni, a Free Spot and a Direct of multiplier 1 without decay 1.0 (the same
at any distance), an Omni with inverse-square decay from 1 m 1.0, from 0.5 m 0.25, with inverse decay from 0.5 m
0.5; a VRaySun of multiplier 1 at the zenith 68.5 (102.7 klx). Cycles (Blender 5.2, a Diffuse BSDF of 1.0): a
point or spot light of 1 W at 1 m 0.02526 (1 / 4π²), a disk area light of 1 W 0.1010 (1 / π² on its axis), a sun
of strength 1 0.3176 (1 / π). So Light Strength 1.43 is π · 683 / 1500 (1.4305), and with it these powers render
as bright as V-Ray:

- a point or spot light of on-axis intensity I cd: 4π I / 683 W (the rules source's for photometric lights); a
  uniform diffuse one: π I / 683 W on an area light;
- a standard Omni or Spot of multiplier m: I = 1500 m d², d the decay start with inverse-square decay (exact past
  it) or inverse decay (exact at it), 1 m without decay;
- a standard Direct: a sun of 1500 m / 683 W/m²; a VRaySun: 146.4 m W/m² (the rules source's 100 klx / 683);
- a VRayIES: its lumens / 683 W, on a spot of 170° and hotspot 100° (the rules source's wide spot), as a
  photometric web.

**VRayIES power, measured** (the same scene, an isotropic LM-63 file of 100 cd, whose flux is 1256.6 lm, with rated
lumens of 1256.6, 500 or -1 in its header): with the intensity override off V-Ray scales the file's candelas by power /
rated lumens. Rated 1256.6: power 1256.6 (what loading the file sets) 0.0667 (100 cd), power 1000 0.0531 (1000 lm).
Rated 500: power 500 (set on load) 0.0667, power 1000 0.1334 (200 cd, not 1000 lm). Rated -1: loading sets the
power to the file's flux, 1256.64 (0.0667); power 1000 0.0531. With the override on, the power is the flux whatever the header says: rated 500,
1000 lm 0.0531; 100 cd (the panel stores 500 lm) 0.0265; rated 1256.6, 100 cd (stored 1256.6) 0.0667. Power 0 renders
black, override on or off, with every file. So the power is the light's flux with the override on, and without it only
when the file's rated lumens are its flux (an absolute file's -1, or a relative one of a luminaire without losses).
MaxDrop reads the file when the texture lookup finds it (`convert/ies.py`) and gives the light power x the file's
flux / its rated lumens (the power for rated lumens of -1); a file not found or not read keeps the power as the flux,
a line in the report. A file V-Ray cannot find renders the power as an isotropic flux, override on or off (power
1000 lm 0.0531, 500 lm 0.0265; targeted or not, no file at all, a saved scene reopened without its file): what
MaxDrop does with a file it does not find. The 1.689 an earlier note gave for it shows when a light, targeted or
not, has rendered with its file and is then switched to a missing path in the same session (not modeled); switched
before any render, it renders 0.0531.

**VRayIES header, measured** (the same scene in millimeters: in meters it renders 0.0829 for 0.0531, the light's shadow
bias of 0.2 world units moving the shaded point toward it; with the bias 0, 0.0530; isotropic 100 cd files, type C, one plane, rated
1256.6, one lamp, ballast factors 1, power 1000, override off, one field changed at a time; the power loading the file
sets in brackets): the base file 0.0531 (1256.6); candela multiplier 2 0.1061 (1256.6): applied; ballast factor 0.5
0.0265 (1256.6): applied; ballast-lamp photometric factor 0.5 0.0531: not applied; 2 lamps of 500 lm 0.0667 (1000):
the rated lumens are lamps × lumens per lamp; rated 0 0.0531 (1256.64) and rated −1 0.0531 (1256.64): the power is
the flux. Type B (vertical −90 to 90, horizontal −90 to 90 or 0 to 90), rated 628.3, 0.1061 (628.3), rated 1256.6
0.0531; type A (horizontal −90 to 90), rated 628.3, 0.1061: read, the same power / rated lumens. V-Ray's own flux
(the power loading a file rated −1 sets): type C 100, 0, 0 cd at 0, 90, 180° 228.96 lm (the candelas linear in angle:
228.32; the zone mean × (cos a − cos b) 314.16); a cosine in 10° steps 313.99; planes of 100, 50, 100, 50, 100 cd at
0 to 360° 942.16; type B isotropic 629.57 (2π · 100 = 628.32), the same with vertical or horizontal angles from 0
and with horizontal angles from −180 to 180 (only −90 to 90 counts); type B 0, 100, 0 cd at vertical −90,
0, 90° 400.95 (linear 400.00), the same across the horizontal angles 314.80 (314.16); type A isotropic 629.58,
the same with vertical angles from 0, but type A with horizontal angles from 0 to 90 1.26 lm (also with
vertical ones from 0): dark (below). Ballast 0.5 halves that flux, 2 lamps leave it, a multiplier of 2 doubles it; a
rated −1 file of ballast 0.5 at power 1000 renders 0.0531.

**VRayIES type A and B ranges, measured** (the same scene in millimeters, power 1000, override off, 64 × 64 renders,
the mean of the 8 × 8 center pixels; the light turned about X or Y so that the center pixel samples another direction
of the file (type B: X turns the horizontal angle, Y the vertical one; type A the other way round); each file rated
628.3, where 100 cd gives 0.1048, and rated −1, V-Ray's own flux in brackets; 100 cd unless given). Horizontal angles
from −180 to 180, isotropic, type B (629.574) and A (629.575): as −90 to 90; turned 135° or 180° 0 (the back half
dark); type B 0, 0, 100, 100, 100, 0, 0 cd at −180, −120, −60, 0, 60, 120, 180° (576.90; the table cut at ±90°, 50
cd there, 575.96): 75 cd turned 75°. Type A with horizontal angles from 0 to 90, vertical ones from −90 or from 0
(1.257): black in the whole frame turned to each of the six cube faces, rated or not. Vertical angles from 0 are not
mirrored: type B 100, 50, 0 cd at 0, 45, 90° (629.58; mirrored 400.00) gives 150 cd at −45° and 183 at −75°, the
first segment going on below 0; 0, 50, 100 (114.31) and 40, 100, 100 at 0, 30, 90 (288.19) are black at −45°, the
line floored at 0 cd; 100, 70, 0 at 0, 60, 90 (621.76) gives 121 cd at −45° and 136 at −75°; 100, 0 at 0, 90 as
100, 50, 0; type A 100, 50, 0 the same. V-Ray's own flux is 1.002 × that table's (as for an isotropic file) in every
file here, but with 4 or more vertical angles from 0 and a run that varies the render is black below 0 where the
flux goes on: 120, 100, 60, 0 at 0, 30, 60, 90 (730.87), 120, 80, 40, 0 (755.49), 100, 100, 60, 0 (583.17), 100,
50, 20, 0 (652.78), 120, 110, 90, 50, 0 in 22.5° steps (721.75), and with planes that differ, from −180 to 180 too
(583.78); with only the middle plane constant (680.19) 83 cd at −45° in it, neither 100 nor 0. Constant runs from 0
render as isotropic with 2 to 5 angles (629.57). Horizontal angles from 0 (type B) are mirrored: 100, 50, 0 at 0,
45, 90° (314.80) gives 50 cd at ±45° and 17 at ±75°. Partial ranges follow no rule found: vertical −60 to 60 of 50,
100, 100, 100, 50 (527.77, types A and B) gives 298 cd at −75° and 50 at 75°, horizontal −60 to 60 the same
(445.84) 67 and 93 cd at +45° and −45°; isotropic files of vertical −60 to 60, 0 to 60, −90 to 60 or 30 to 90 and of
horizontal −60 to 60 or 0 to 60 render as the full range (629.57). A table of 0 cd (types B and C) loads a power of
0 at rated −1 and renders black, rated or not. Next to a change V-Ray's render rises up to 3 % over the table's
linear value (the front of a file whose back half is 50 cd): its flux, not its render, is linear in angle.

**IES files** (IESNA LM-63, `convert/ies.py`): after the keyword lines, `TILT=NONE`, `TILT=<file>` (nothing inline)
or `TILT=INCLUDE` (lamp-to-luminaire geometry, the number of pairs n, n angles, n factors); then the number of lamps,
lumens per lamp (-1: absolute photometry), candela multiplier, the numbers of vertical and horizontal angles,
photometric type (1 C, 2 B, 3 A), units type, width, length, height; ballast factor, ballast-lamp photometric
factor, input watts; the vertical angles, the horizontal angles, then one run of vertical candelas per horizontal
angle, separated by white space or commas. As V-Ray renders it (measured, "VRayIES header, measured"): the candelas
interpolated linearly in angle; the flux of a type C file per horizontal plane the integral of I(θ) sin θ over the
vertical angles (a zone [a, b]: Ia cos a − Ib cos b + (Ib − Ia)(sin b − sin a) / (b − a)), the trapezoid over the
planes in radians, times 360 / their span (one plane 2π; the spans 90, 180 and 360 of LM-63's symmetries from 0 or
90, 90 to 270 included; planes from 0 to past 180 but short of 360 closed with the first plane at 360); of a type A or
B file, whose vertical angles are a latitude, the integral of I(θ) cos θ (Ib sin b − Ia sin a + (Ib − Ia)(cos b −
cos a) / (b − a)) and the same trapezoid, vertical angles from −90 or 0 to 90, horizontal ones from −90
to 90, from −180 to 180 (only −90 to 90 counts, the planes at ±90 interpolated), or for type B from 0 to 90 doubled.
Vertical angles from 0 are not doubled: each run goes on below 0 along its first segment, floored at 0 cd (a constant
run: doubled), read with 2 or 3 vertical angles or constant runs ("VRayIES type A and B ranges, measured"); with 4 or
more and a run that varies, V-Ray renders the lower half black while its own flux goes on: not read; nor a run that
varies with a first segment shorter than 30° (the shortest measured), 0 included. A type A file
with horizontal angles from 0 to 90 renders nothing: its flux is 0. An isotropic file of I cd gives 4π I exactly
(type C), 2π I (A and B).
The flux is times the candela multiplier and the ballast factor (not the ballast-lamp factor); the rated lumens are
the number of lamps times the lumens per lamp; rated lumens of 0 or below count as -1 (a flux of 0 is dark then too,
as V-Ray renders it). Other ranges of type A and B (partial: V-Ray renders them by no rule found),
and a file larger than 4 MiB, of more than 4096 angles per axis or 2^20 candelas, or with a
number out of range or out of order, are not read (a line in the report).

**Spot cones.** Blender's spot size is the falloff; its blend is set so that full intensity ends at the hotspot, as in
3ds Max: Blender blends in cosine space (full intensity where cos θ ≥ cos(size / 2) + (1 − cos(size / 2)) · blend),
so blend = (cos(hotspot / 2) − cos(falloff / 2)) / (1 − cos(falloff / 2)), 0.636 for 30° in 50°.

## Cameras

`convert/cameras.py`, 3ds Max 2020 + V-Ray 5.2; ids read through the SDK's .NET wrapper and by changing one setting at
a time on scratch scenes (maxdiff), the field of view from 3ds Max's own camera state (`EvalCameraState`, the oracle's
`camera`), and lens shift, orthographic width and V-Ray's focus from renders of a marker scene (small self-lit spheres
at known points, their image centroids). Superclass `0x20`; every camera looks down its local -Z with +Y up, as
Blender's: the node transform stays (the cameras fixture: -Z and +Y of each camera object equal the oracle's).

**Free** `(0x1001, 0)` and **Target** `(0x1002, 0)` (its class directory names it "Target", like the Target object).
Reference 0 is an old ParamBlock, by index: 0 FOV (radians, horizontal, whatever FOV type the panel shows), 1 target
distance (a Free camera's; 0 on a Target camera), 2 near clip, 3 far clip, 4 / 5 near / far environment range, 6
multi-pass effect on, 7 effect per pass, 8 FOV type (0 horizontal, 1 vertical, 2 diagonal: shown only). The camera
object's own chunks: `0x268C` (empty) orthographic, `0x2686` (empty) clip manually, `0x2684` (empty) show cone.
Orthographic (render): the view is 2 · tdist · tan(FOV / 2) wide at any depth, tdist a Free camera's target distance
or a Target camera's distance to its target.

**Physical** `(0x46697218, 0x28E8008D)`, ParamBlock2 block 0 at reference 0: 0 targeted, 8 target distance (world), 4
film width (mm), 5 focal length (mm), 19 specify FOV, 20 FOV (degrees), 7 zoom, 54 lens breathing, 10 specify focus,
9 focus distance (world), 11 use depth of field, 39 / 40 horizontal / vertical shift (a fraction of the film width;
the panel shows percent), 41 / 42 horizontal / vertical tilt correction, 44 distortion type, 47 clip on, 48 / 49
near / far clip (world).

**VRayPhysicalCamera** `(0x405E3FEE, 0x4F6513BE)`, ParamBlock2 block 0 at reference 0: 8 targeted, 5 target distance,
0 film gate (mm), 1 focal length (mm), 3 zoom, 47 specify FOV, 48 FOV (degrees), 7 specify focus, 6 focus distance,
25 use depth of field, 41 / 42 horizontal / vertical shift (a fraction of the film width), 18 / 40 vertical /
horizontal tilt, 4 distortion, 10 exposure (0 off), 32 clip on, 33 / 34 near / far clip (world). The film gate and
focal length are typed as world units but stay millimeters in a centimeter scene (probed).

**Exposure and f-number** (3ds Max 2020 + V-Ray 5.2: the ParamBlock2 descriptors through the .NET wrapper, maxdiff of
saves that change one setting, V-Ray renders of a self-lit white plane filling a 32 x 32 view, linear color mapping,
gamma off, no GI, the mean of the 8 x 8 center pixels: a camera-side ratio, not the calibration floor). VRayPhysicalCamera,
block 0: 10 exposure (int: 0 off, 1 physical exposure, 2 exposure value; default 1), 2 f-number (float, 8), 12 shutter
speed (float, the denominator in 1/s: 200 = 1/200 s), 16 ISO (float, 100), 56 exposure value (float, EV; default 13),
11 vignetting (bool, off), 39 vignetting amount (float, 1), 37 white balance preset (int, default 4), 19 white balance
(the color, stored as floats 0..1; default 0.999149 0.999506 1), 46 temperature (float, kelvin, 6500). Also in the
block, not read: 14 shutter angle, 17 shutter offset, 15 latency, 36 legacy ISO, 38 system lighting units. V-Ray keeps
the exposure value and the three settings in step: setting the f-number, the shutter speed or the ISO stores EV =
log2(N² · shutter · 100 / ISO) again (maxdiff: param 56 changes with each), setting the exposure value stores a new
ISO, and in mode 2 a new f-number or shutter speed keeps the exposure value and stores a new ISO. A new camera stores
EV 13, not the 13.6439 of its defaults, until one of them is set. Mode 1 renders from the f-number, shutter speed and
ISO, mode 2 from the stored exposure value (the defaults render 0.0199 in mode 1, 0.0311 in mode 2 at EV 13: 2^0.644
apart; 3 EV lower renders 8 times brighter); mode 0 renders as if there were no exposure. The factor: **Exposure
factor** below. A white balance preset stores its color in 19 (FixtureExpTint's preset 5 stores its own). Set one after the
other from the default 4: 1 white, 2 0.75 0.886365 1, 3 0.816122 0.889125 1, 4 the color above, 5 1 0.890094 0.755618, 6
1 0.825353 0.628004, 7 white; 0 (after 4), 8 and 9 (after 7) left the color as it was, whether they set or keep one is
not measured (maxdiff of 4 -> 0 changes 37 only). What each preset stands for is not read. **Physical**, block 0: 6 f-number (float, 8); its exposure (22 exposure gain
type, 23 ISO, 24 exposure value: descriptor names only, not checked by maxdiff) is for the exposure control of the
RenderEnvironment, not read. The exposure fixture
(`tools/fixtures/exposure.ms`, system unit millimeters; values read back through `maxdrop/reader`; the column heads
are VRayPhysicalCamera's ids, the Physical row names its own):

| Camera | 10 | 2 | 12 | 16 | 56 | Other |
|---|---|---|---|---|---|---|
| FixtureExpPhysical (targeted; the render view) | 1 | 5.6 | 125 | 200 | 10.9366 | |
| FixtureExpOff | 0 | 2.8 | 200 | 100 | 10.6147 | |
| FixtureExpValue | 2 | 4 | 100 | 110.485 | 10.5 | |
| FixtureExpTint | 1 | 8 | 200 | 100 | 13 | 11 on, 39 0.5, 37 5, 19 1 0.890094 0.755618 |
| FixtureExpStored | 2 | 8 | 200 | 100 | 13 | |
| FixturePhysDof (Physical) | | 6: 2.8 | | | | 11 depth of field on, 10 specify focus 1, 9 focus distance 2500, 8 target distance 5000 |

**Exposure factor** (maxdrop-o53.2.2; 3dsmaxbatch, V-Ray 5.2). The calibration floor of [VRayLight](#vraylight) in
meters: a white VRayMtl floor (diffuse 255, no reflection) 20 m square, a standard Omni of multiplier 1 without decay
1 m above it, V-Ray color mapping linear, gamma 1, clamp output off, no GI, no default lights, 3ds Max's gamma off;
a free VRayPhysicalCamera 0.9 m above the floor looking down (FOV 60° specified, target distance 200 m, vignetting
off, white balance 255 255 255, the still camera type), rendered into a 64 × 64 float bitmap; the mean of the 8 × 8
center pixels. Exposure off renders 0.704897, as a Target camera does (the Omni at multiplier 2: 1.40979, so nothing
clamps; "Power, measured" gives this Omni 1.0: maxdrop-o53.2.9). The ratio on / off does not depend on the light: a
1 W VRayLight sphere (0.0360797 off; "Power, measured" says 0.0362) and a self-lit plane (1.0 off) give the Omni's
ratio in meters, centimeters and inches, the plane also in millimeters (the sphere there: "Not measured" below). In
centimeters and inches the ratio (0.030138, 0.0307069) is the formula's at the default target distance, 200 cm and
200 in (2000 and 5080 mm). Mode 1 unless the row says otherwise:

| Setting (f-number, shutter speed, ISO) | Pixel | On / off | Formula | Stops |
|---|---|---|---|---|
| exposure off (mode 0) | 0.704897 | 1 | 1 | 0 |
| 8, 200, 100 (the defaults) | 0.0219049 | 0.0310753 | 0.0310753 | −5.0081 |
| 8, 200, 200 | 0.0438097 | 0.0621505 | 0.0621505 | −4.0081 |
| 8, 200, 400 | 0.0876194 | 0.124301 | 0.124301 | −3.0081 |
| 8, 200, 1600 | 0.350478 | 0.497205 | 0.497204 | −1.0081 |
| 8, 50, 100 | 0.0876194 | 0.124301 | 0.124301 | −3.0081 |
| 8, 400, 100 | 0.0109524 | 0.0155376 | 0.0155376 | −6.0081 |
| 8, 30, 100 | 0.146032 | 0.207168 | 0.207168 | −2.2711 |
| 8, 4, 100 | 1.09524 | 1.55376 | 1.55376 | +0.6358 |
| 4, 200, 100 | 0.0876194 | 0.124301 | 0.124301 | −3.0081 |
| 5.6, 200, 100 | 0.0447038 | 0.0634189 | 0.0634189 | −3.9789 |
| 16, 200, 100 | 0.00547621 | 0.00776881 | 0.00776882 | −7.0081 |
| 1.4, 200, 100 | 0.715261 | 1.0147 | 1.0147 | +0.0211 |
| 5.6, 125, 200 (FixtureExpPhysical's) | 0.143052 | 0.20294 | 0.20294 | −2.3009 |
| 2.8, 30, 800 | 9.53658 | 13.529 | 13.5294 | +3.7580 |
| mode 2, EV 10.5 | 0.193613 | 0.274668 | 0.274669 | −1.8642 |
| mode 2, EV 9 | 0.547621 | 0.776881 | 0.776882 | −0.3642 |
| mode 2, EV 0 | 280.376 | 397.755 | 397.763 | +8.6358 |
| mode 2, EV −2 | 1121.5 | 1591.01 | 1591.05 | +10.6358 |
| 8, 200, 100 in millimeters (target distance 200 mm) | 0.0164001 | 0.023266 | 0.023266 | −5.4256 |
| 5.6, 125, 200 in millimeters | 0.107103 | 0.151941 | 0.151941 | −2.7184 |

The formula: factor = (12.5 / π) · ISO · t / N² · (f / v)² in mode 1, (1250 / π) · 2^−EV · (f / v)² in mode 2 (EV the
stored 56), 1 in mode 0. N is the f-number as stored (5.6², not 32); t the exposure time in seconds: for the still
camera (MAXScript `type` 0; its block id is not read) 1 / shutter speed, the cinematic one (1) shutter angle / 360 /
the scene's frame rate (180° at 30 fps: 1/60 s), the video one (2) 1 / frame rate + latency (s). (f / v)² is the thin
lens of the next paragraph: f the focal length, d the focus distance (the specified focus distance, else the target
distance, for a targeted camera its distance to its target node), in millimeters through the system unit, v = 1 /
(1/f − 1/d), so (f / v)² = (1 − f / d)²; with a specified FOV v = film / (2 tan(FOV / 2)) and f / v = d / (d + v).
Zoom, and the film width at a given focal length, leave it as it is. Mode 1 reads the three settings and ignores 56
(FixtureExpTint renders from its 8, 200, 100, not from its stale 13), mode 2 reads 56 and ignores them; for the still
camera mode 1 is mode 2 at EV = log2(N² · shutter speed · 100 / ISO). Every row above and below is within 0.01 % of
the formula. The lens and camera type, measured on a self-lit plane at the defaults 8, 200, 100 (pixel = factor):

| Lens (millimeters) | Pixel | (f / v)² |
|---|---|---|
| focal 20, 40, 80 at d 200 000 | 0.0310787, 0.0310725, 0.0310601 | 0.9998, 0.9996, 0.9992 |
| specified FOV 30°, 90° at d 200 000 | 0.0310641, 0.0310793 | 0.99933, 0.99982 |
| focal 17.9963 at d 200, 500, 1000, 5000 (target distance; a specified focus at 200 and 1000 the same) | 0.0257425, 0.0288876, 0.0299762, 0.0308616 | 0.8281, 0.9293, 0.9643, 0.9928 |
| specified FOV 60° at d 200 | 0.0232675 | 0.7485 |
| focal 20, 40, 80 at d 200 | 0.0251788, 0.0198944, 0.0111906 | 0.81, 0.64, 0.36 |
| focal 40, targeted, 1000 and 5000 from the target (stored target distance 200) | 0.0286479, 0.0305896 | 0.9216, 0.9841 |
| focal 40 at d 1000: cinematic 180° at 30 fps, 90° at 30 fps, 180° at 60 fps | 0.095493, 0.0477465, 0.0477465 | 0.9216 |
| focal 40 at d 1000: video at 30 fps, latency 0 and 0.01 | 0.190986, 0.248282 | 0.9216 |

**In Blender.** MaxDrop's lights render as bright as V-Ray's unexposed pixel (Light Strength 1.43, "Power, measured";
for the standard Omni, Spot and Direct see maxdrop-o53.2.9), so the camera's exposure is
`scene.view_settings.exposure` = log2(factor) = 1.9924 + log2(ISO · t / N²) + 2 log2(f / v), in mode 2 8.6362 − EV +
2 log2(f / v), in mode 0 0 stops. The exposure fixture: FixtureExpPhysical −2.3308 (focused at its target, 3816.08
mm), FixtureExpValue −2.5076, FixtureExpTint −5.6515, FixtureExpStored −5.0076 (these three at the 200 mm target
distance), FixtureExpOff 0; renders of the fixture's box under V-Ray's default lights, on / off, give these factors
within 0.7 % (FixtureExpOff's view misses the box).

Left out of the factor:

- Vignetting (11, 39): a pixel θ off the axis is multiplied by 1 − amount · (1 − cos⁴ θ) (amount 1 and 0.5, four
  pixels from the center to the corner of the 60° view, within 0.3 %; the 8 × 8 center mean is 0.993 of the
  unvignetted one at amount 1, 0.997 at 0.5).
- White balance (19): with exposure on, channel c is multiplied by (1 / wb_c) / the mean of the three 1 / wb, so a
  grey keeps its mean (preset 5: 0.870, 0.978, 1.152; 255 128 64: 0.430, 0.857, 1.713; the default preset 4's color
  within 0.05 %); with exposure off it does nothing.

Not measured: legacy ISO (36) at an ISO other than 100 (at 100 it changes nothing), system lighting units (38) other
than in this setup (off changes nothing), shutter offset, optical vignetting, the bitmap aperture's affect exposure,
distortion, a lens file. A 1 W VRayLight sphere 1 m above the floor of a millimeter scene renders 0 exposed at the
defaults (0.0361 off; 0.00112 exposed in meters): consistent with V-Ray's light cut-off threshold (0.001 by default)
applied to the exposed contribution, not checked.

**The field of view they render with.** Free / Target: the FOV parameter. Physical with a specified FOV: that FOV
(neither zoom nor breathing; 74.9996° for 75° at zoom 1.25). Otherwise a thin lens focused at d, the focus distance
when specified, else the target distance, in millimeters through the system unit (100 cm and 1000 mm give the same):
v = 1 / (1/f − 1/d), effective focal length zoom · (f + breathing · (v − f)), FOV = 2 atan(film / (2 · f_eff)) (40
mm, 36 mm film at 5000 mm: 48.112°; breathing 0.5: 48.2832°; at 1000 mm 46.7287°, with zoom 1.5 32.1328°).
VRayPhysicalCamera: the same with a breathing of 1 (its default 200 mm target distance gives 39.598°, not the
48.455° of 2 atan(film / (2 f · zoom)) the 3ds Max to FBX rules source computes), a specified FOV without the zoom.
A targeted Physical or V-Ray camera focuses at its distance to its target node, whatever its stored target distance
(2376.92 stored, 2922.33 used in the fixture). A lens shift moves the image by that fraction of its width (20 % up:
the image content 0.2 widths up) and leaves the rendered FOV as it is, but changes the FOV of `EvalCameraState`
(73.29° renders, the state says 71.39°): the oracle reads the state with the shift at 0. The tilt corrections warp
the image (keystone): Blender has nothing like it.

**Blender.** sensor_fit HORIZONTAL, so Blender's horizontal FOV is 2 atan(sensor / (2 · lens)) at any render aspect;
sensor 36 mm for Free and Target (3ds Max's render aperture width), the film width for the others; lens = sensor /
(2 tan(FOV / 2)). shift_x / shift_y = minus the shift fractions (Blender moves the frame, both in image widths with
a horizontal fit). Clipping when 3ds Max clips. Depth of field, distortion, tilt, a multi-pass effect and V-Ray's
exposure are lines in the report. The render size and pixel aspect go to the Blender scene, with the scene camera,
only for a file that has a camera (build/cameras.py).

## Render settings and saved views

**Render settings** live in the RenderEnvironment object `(0xEE448B23, 0)`, chunk `0x0110` / `0x2000` (maxdiff of
saves that change one setting):

| Chunk | Meaning |
|---|---|
| `0x0190` i32 | render width (pixels) |
| `0x0200` i32 | render height |
| `0x0210` f32 | pixel aspect |
| `0x05F0` i32 | present when the render view is locked (`rendUseActiveView` off): the 0-based viewport index it renders |

**Saved views** are in the `Config` stream, `0x2080` / `0x8200`: `0x8210` i32 the current layout tab, its position
among the `0x8220` layouts that follow, each after an `0x8240` i32 (0, 1, 2, 3 in the fixtures, 0 on every tab of
corpus scene B, whose current tab is the fifth: not the tab's index). A layout: `0x2800` the layout type, `0x2810` + k
viewport k (80 bytes: u32 at byte 4 the view type, 8 = a camera view; i32 at byte 76 the object index of the node a
camera view looks through), `0x2820` i32 the active viewport (−1 on a tab that is not current). In a file saved as
3ds Max 2012 (corpus scene A) `0x2080` holds the layout itself, without `0x8200`. The view 3ds Max renders is the
locked one, else the active viewport; the cameras fixture locks it on viewport 2 (CamTarget) while viewport 1
(CamFree) is active, and the oracle's `render.camera` (3ds Max's `viewport.getCamera`) is CamTarget. Both corpus
scenes are saved looking through their one camera; their cameras' fields of view equal 3ds Max's (EvalCameraState).
A view through no camera (a Perspective viewport active, the render view unlocked: the lookat fixture) makes the
first camera the scene camera, a note of the report's render line; no Config stream or layout, a damaged one,
no view index in range, an unreadable viewport record or a view through a camera not built is an issue.

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
- Images, the input gamma and the temperature colors (maxdrop-em3.38), V-Ray 5.2 renders of VRayLightMtl planes
  with 128 grey 8-bit images, read as V-Ray's internal linear value (`getPixels ... linear:true`, the EXR):

  | Map | on, input 2.2 | on, input 1.0 | off (input 2.2 or 1.0) |
  |---|---|---|---|
  | Bitmap, automatic gamma | 0.219 | 0.502 | 0.502 |
  | Bitmap, override 2.2 / 1.0 | 0.219 / 0.502 | 0.219 / 0.502 | 0.502 / 0.502 |
  | VRayBitmap From 3ds Max / Auto, sRGB / None | 0.219 / 0.216 / 0.502 | 0.502 / 0.216 / 0.502 | 0.502 / 0.216 / 0.502 |
  | CoronaBitmap automatic / 2.2 / 1.0 | 0.219 / 0.219 / 0.502 | the same | the same |
  | Bitmap of a 0.5 EXR, automatic | 0.5 | 0.5 | 0.5 |
  | VRayColor / CoronaColor 3000 K | (1, 0.486, 0.151) / (1, 0.477, 0.154) | the same | the same |

  The 8-bit output gets the output gamma with the gamma on (swatch 128 -> byte 186) and the internal value as it is
  with it off (128): a gamma-off scene is display-referred, its internal value v is srgb_to_linear(v) in Blender.
  So with the gamma on an automatic Bitmap (and VRayBitmap From 3ds Max) takes the file input gamma; with it off a
  Bitmap is read as stored whatever its override, and a temperature color is decoded as a swatch is. CoronaBitmap
  and VRayBitmap Auto / sRGB apply their own curve in every case, so with the gamma off V-Ray shows them darker
  than an sRGB image (and an EXR shows its value as stored), and VRayBitmap None shows as stored: converted since
  maxdrop-em3.123, CoronaBitmap since maxdrop-em3.165 (below). Reopening the saved scenes from disk renders the same.
- LUT mode belongs to the session: a scene saved in it (Scene `1`, Config `0`) opens as `#gamma` from a `#none` or
  `#gamma` session and renders as gamma on (swatch 186, the PNG 128); a `#lut` session stays in LUT mode for a file
  whose chunk says `1` (and renders as gamma off there: 128, 128). MaxDrop reads the file's `1` as gamma on.
- Corona's own swatches: Corona 12 renders a 128 swatch 0.502 with the gamma on and off, as V-Ray (maxdrop-em3.165,
  below; Corona renders run here since 2026-11-23).
- Data inputs and masks (maxdrop-em3.122), V-Ray 5.2 renders of the same 128 grey PNG and of swatches: VRayMtl
  glossiness through the VRayMtlReflectGlossiness element, VRayMtl opacity as the render alpha, a Mix black -> white
  mask on a VRayLightMtl (its internal value, `getPixels ... linear:true`):

  | Map | on | off |
  |---|---|---|
  | glossiness or opacity: VRayColor grey 64 / red; Mix black -> white by VRayColor 64 | 0.251 / 0.333; 0.251 | the same |
  | glossiness, opacity or mask: Bitmap automatic / 2.2 / 1.0 | 0.2195 / 0.2195 / 0.502 | 0.502 / 0.502 / 0.502 |
  | glossiness or mask: CoronaBitmap automatic / 2.2 / 1.0 | 0.2195 / 0.2195 / 0.502 | the same |
  | glossiness or mask: VRayBitmap sRGB / From 3ds Max / None | 0.2159 / 0.2195 / 0.502 | 0.2159 / 0.502 / 0.502 |
  | opacity, emission: Mix grey 40 -> 220 by VRayColor 128 | 0.511 | 0.511 |
  | emission: Mix grey 40 -> 220 by the Bitmap automatic | 0.312 | 0.511 |

  A map's value does not depend on the slot it drives, and a data input uses it as it is: a swatch as stored in
  both modes, an image decoded by its gamma with the gamma on. In a color graph with the gamma off the result is
  display-referred (Blender needs `srgb_to_linear` of it): a mask between black and white is the decoded number,
  a mask between two colors mixes display values (target 0.225 linear for the 0.511 above, a decoded mask gives
  0.171). The rules are in `maxdrop/convert/texmaps/` (MASK, colorspace, `_swatch`).
- A Corona opacity color (maxdrop-6n0.6.35), Corona 12 renders of a self-illuminated white CoronaLegacyMtl and
  CoronaPhysicalMtl over black, 64 passes, gamma on and off alike: white 1.0, grey 64 0.251, red (255, 0, 0)
  1.0 / 0.0 / 0.0, (200, 100, 50) 0.784 / 0.392 / 0.196 (0.785 / 0.393 / 0.197 for the physical one), black 0:
  the swatch as stored, per channel, not its mean. A Blender alpha is one number: MaxDrop keeps the mean and names
  a colored opacity color in the report (`MaterialConverter.mono_swatch`; CoronaSkinMtl and CoronaHairMtl assumed
  alike).
- Maps with their own decode (maxdrop-em3.123), V-Ray 5.2 renders of VRayLightMtl planes, each rendered alone, its
  internal value (`getPixels ... linear:true` of an HDR bitmap); greys 64 / 128 / 192 as 8-bit PNGs, EXRs of 0.25 /
  0.5 / 2.0. Gamma on (input 2.2) and off give the same internal value for every row:

  | Map | internal value | shown with the gamma off (Blender linear) |
  |---|---|---|
  | VRayBitmap sRGB / Auto, 64 / 128 / 192 | 0.0513 / 0.2159 / 0.5271 | 0.0042 / 0.0383 / 0.2397 |
  | VRayBitmap None, 64 / 192 | 0.251 / 0.753 | 0.0513 / 0.527 |
  | VRayBitmap Inverse gamma 2.0 / 0.5, 128 | 0.7085 / 0.2520 | 0.4598 / 0.0516 |
  | Bitmap automatic, EXR 0.25 / 0.5 / 2.0 | 0.25 / 0.5 / 2.0 | 0.0509 / 0.214 / 4.954 |
  | VRayBitmap Auto / None / From 3ds Max, EXR 0.5; sRGB, EXR 0.5 | 0.5; 0.2140 | 0.214; 0.0376 |
  | CoronaBitmap automatic 64 / 192, 1.0 192, automatic EXR 0.5 | 0.0478 / 0.5356, 0.753, 0.5 | 0.0037 / 0.2483, 0.527, 0.214 (Corona 12 alike, below) |
  | CoronaColor HDR 0.25 / 0.5 / 2.0, 0.5 x multiplier 2 | 0.25 / 0.5 / 2.0, 1.0 | 0.0509 / 0.214 / 4.954, 1.0 (Corona 12 alike, below) |

  Inverse gamma g is pixel ^ (1 / g). With the gamma off a color input or mask gets the gamma the scene shows: 2.2 x
  the map's own (2.2: the sRGB color space, which Blender 4.2 to 5.2 applies to an EXR with the extended curve,
  2.0 -> 4.954), 5.0 for the sRGB curve (`SRGB_TWICE`: twice the curve is within 0.008 of x ^ 5 over 0..1); a
  Bitmap and From 3ds Max read any file as stored, sRGB. Data inputs keep the map's own curve. Blender 5.2 and 4.2
  renders of the probe scenes agree within 0.02 (2 % above 1). CoronaBitmap and CoronaColor HDR follow the same
  rule since Corona 12 renders them so (maxdrop-em3.165, below). A dome's texture
  gamma is drawn as a material's (a Gamma node in the World), but a float dome texture in a gamma-off scene keeps
  its own decode (a line in the report): measured as a light below (maxdrop-em3.166).
- Color mixes (maxdrop-em3.158), V-Ray 5.2 renders of VRayLightMtl planes, each plane's internal value; greys are
  swatches, Bm a 128 grey 8-bit PNG (automatic gamma). With the gamma on and off the internal value is the same (a
  Bm plane with the gamma on: the image decoded first):

  | Map | internal value | shown with the gamma off (Blender linear) |
  |---|---|---|
  | Mix grey 40 -> 220, amount 25 / 50 / 75 % | 0.333 / 0.510 / 0.686 | 0.091 / 0.223 / 0.429 |
  | the same by VRayColor 64 / 128 / 192, by Bm | 0.334 / 0.511 / 0.688, 0.511 | 0.091 / 0.225 / 0.432, 0.225 |
  | Mix (200, 40, 40) -> (40, 60, 220) by VRayColor 128 | (0.469, 0.196, 0.511) | (0.187, 0.032, 0.225) |
  | Mix Bm -> white at 50 %; black -> white by VRayColor 128 / by Bm | 0.751; 0.502 / 0.502 | 0.524; 0.216 / 0.216 |
  | RGB Multiply 128 x 128, Bm x 128, 64 x 200 | 0.252, 0.252, 0.197 | 0.052, 0.052, 0.032 |
  | Composite 40 under 220 at 50 % / by a VRayColor 128 mask | 0.510 / 0.511 | 0.223 / 0.225 |
  | Composite 64 + 64 in Addition at 100 / 50 %; Multiply 128 x 128; Screen 64 64 | 0.502 / 0.376; 0.252; 0.439 | 0.216 / 0.117; 0.052; 0.162 |

  So with the gamma off V-Ray computes a Mix or Composite on the stored values (the swatch as stored, an image by its
  own decode, the mask as stored) and the display shows the result decoded; decoded sides mixed in Blender were off
  by up to 0.27 (the colored pair), 16 of 24 planes by more than 0.02. A product commutes with a power law, so a
  decoded RGB Multiply is within 0.005. The rule is in `maxdrop/convert/texmaps/` (STORED, Decode); Blender 5.2
  renders of the probe scenes agree with V-Ray within 0.0085 on every plane. Falloff and the wrappers: below
  (maxdrop-6n0.6.18); CoronaMix in Corona 12: below (maxdrop-em3.165).
- Corona maps with the gamma off (maxdrop-em3.165), Corona 12 renders of CoronaLightMtl planes (color white,
  intensity 1, the map as texmap), tone mapping off, a pass and a time limit, an orthographic camera over a grid,
  each plane's internal value (`getPixels ... linear:true` of an HDR bitmap, a 9 x 9 pixel mean); the em3.123 greys
  and EXRs. Gamma on (input 2.2) and off give the same internal value for every row:

  | Map | internal value | shown with the gamma off (Blender linear) |
  |---|---|---|
  | swatch 128 (CoronaLightMtl color; CoronaColor color) | 0.502 | 0.216 |
  | CoronaBitmap automatic or 2.2, 64 / 128 / 192 | 0.0478 / 0.2195 / 0.5356 | 0.0037 / 0.0395 / 0.2483 |
  | CoronaBitmap 1.0, 64 / 128 / 192 | 0.251 / 0.502 / 0.753 | 0.0513 / 0.216 / 0.527 |
  | CoronaBitmap automatic, EXR 0.25 / 0.5 / 2.0; 2.2, EXR 0.5 | 0.25 / 0.5 / 2.0; 0.2177 | 0.0509 / 0.214 / 4.954; 0.0389 |
  | CoronaColor HDR 0.25 / 0.5 / 2.0; 0.5 x multiplier 2 | 0.25 / 0.5 / 2.0; 1.0 | 0.0509 / 0.214 / 4.954; 1.0 |
  | Mix and CoronaMix (mix) black -> white by a CoronaBitmap automatic 128 | 0.2195 | 0.0395 |
  | Mix 50 % of CoronaBitmaps automatic 64 and 192; CoronaMix mix 50 % of them | 0.2917; 0.2917 | 0.0692 |
  | CoronaMix of CoronaColor HDR (0.05, 0.4, 0.9) under (0.6, 0.2, 0.75): screen, overlay, hard light, exclusion, add, multiply | renderMap's values (em3.117) | them decoded |

  So Corona holds a CoronaBitmap's own decode, the HDR color (unclamped) and a swatch as V-Ray holds its maps, and
  computes a Mix and a CoronaMix on those values: with the gamma off a CoronaBitmap on a color input or a mask gets
  `_shown`, the HDR color is decoded with the extended curve (the mean on a mask), and a CoronaMix at a color root
  joins `DISPLAY_MIXES` (STORED under a Decode; a folded constant decoded exactly). A float CoronaBitmap dome texture
  keeps its own decode, as the other float dome textures do. Data, normal and bump inputs are unchanged. A value
  above 1 under a Decode that does not fold (a CoronaMix of an HDR color over a map) follows the Decode's power of
  2.2, not the extended curve (3.78: 18.6 against 22.2). Blender 5.2
  renders of the saved probe scenes agree within 0.0092 on every CoronaBitmap, CoronaColor, swatch and mask plane,
  gamma on and off. A first pass that rendered to an EXR output file clamped the bitmap at 1.0 and gave a Bitmap
  automatic 128 0.2195 with the gamma off (0.502 in the passes rendered into an HDR bitmap, as V-Ray): not used.
- Normal and bump images (maxdrop-em3.159), V-Ray 5.2 renders read through VRayBumpNormals and Corona 12 renders
  through CGeometry_NormalsShading (both store (n + 1) / 2; an orthographic top camera), 8-bit PNGs: a flat
  (128, 128, 255) and a tilted (180, 100, 220) normal map under VRayNormalMap, Normal Bump and CoronaNormal, a
  grey ramp tiled 10 times as a height (in the bump slot and as a normal map's bump), its slope read at 0.25 and
  0.75 of a tooth (as stored equal; decoded by 2.2 about 1 : 3.3):

  | Image | gamma on | gamma off |
  |---|---|---|
  | Bitmap automatic / 2.2 | decoded: flat (-0.44, -0.44, 0.78), 38.5 degrees; height 0.015 / 0.050 | as stored: (0, 0, 1); 0.030 / 0.030 |
  | Bitmap 1.0 | as stored | as stored |
  | CoronaBitmap automatic / 2.2; 1.0 | decoded; as stored | decoded; as stored |
  | VRayBitmap None / sRGB / From 3ds Max below a normal map | as stored | as stored |
  | VRayBitmap height None / sRGB / From 3ds Max | stored / decoded / decoded | stored / decoded / stored |
  | CoronaNormal Add gamma to input over Bitmap or CoronaBitmap automatic; 1.0 | as stored; raised to 1 / 2.2 | no effect |

  So a normal or bump input takes an image as a data input does (the same rule for Bitmap and CoronaBitmap in
  Corona 12), except a VRayBitmap below a normal map, which V-Ray reads as stored (below a CoronaNormal assumed
  alike: not probed). A scene whose gamma setting is not found is taken as gamma on, as for swatches. CoronaNormal's
  Add gamma is folded into its image's gamma only for an image without an Output and not read for its alpha (else
  a line in the report). A first reading of a
  VRayBitmap From 3ds Max directly in a VRayMtl bump slot with the gamma off (decoded) does not reproduce: it is
  stored there too (maxdrop-6n0.6.19, below). V-Ray bends a normal tilted over
  about 44 degrees back toward the surface: the tilted map decoded renders 44.2 degrees for 59.2, and so does that
  decoded normal stored in a file read at 1.0 (V-Ray's limit, not the decode; MaxDrop draws it unbent). The rule is
  in `maxdrop/convert/texmaps/` (colorspace, `_vray_image`, `_add_gamma`). Blender 5.2 renders (EEVEE and Cycles)
  of the V-Ray probe scenes imported by MaxDrop: every normal plane within 0.32 degrees of V-Ray except those tilted
  past that limit; every height plane with V-Ray's stored or decoded slope pattern except the one above.
- A dome texture as a light (maxdrop-em3.166), V-Ray 5.2 renders of a scene lit only by a VRayLight dome (multiplier
  1, default units, spherical): a white floor (VRayMtl diffuse 255) and a grey plane (128) side by side, facing up, GI
  off, and the sky seen directly; each a 32 x 32 render averaged, V-Ray's internal value. Skies: VRayBitmap Auto
  (spherical) of self-authored EXRs, one value 0.5 or 4.0, and a sky of 0.2 with a block of 2000 at 40 to 50 degrees
  elevation (0.0208 sr: the floor's analytic 9.551 is V-Ray's 9.551); a Bitmap of the 0.5 EXR in spherical
  environment mapping (as the VRayBitmap); a 128 grey PNG; no texture at multiplier 0.5. With the gamma on, Blender
  5.2 (Cycles) renders of the import agree with V-Ray within 0.007 on every floor, plane and sky (0.07 % on the sun's
  floor). With the gamma off the target is srgb_to_linear of V-Ray's value (floor / plane / sky):

  | Dome | V-Ray | target | its own decode (kept) | the material rule |
  |---|---|---|---|---|
  | EXR 0.5 (VRayBitmap or Bitmap) | 0.500 / 0.251 / 0.500 | 0.214 / 0.051 / 0.214 | 0.500 / 0.108 / 0.500 | 0.214 / 0.046 / 0.214 |
  | EXR 4.0 | 3.999 / 2.008 / 4.0 | 25.30 / 5.00 / 25.31 | 3.999 / 0.863 / 3.999 | 25.31 / 5.46 / 25.31 |
  | EXR sky 0.2, sun 2000 | 9.551 / 4.794 / 0.2 | 200.6 / 38.9 / 0.033 | 9.545 / 2.060 / 0.200 | 333 803 / 72 055 / 0.033 |
  | no texture, multiplier 0.5 | 0.5005 / 0.251 / 0.5 | 0.215 / 0.051 / 0.214 | 0.500 / 0.108 / 0.500 (as imported) | |
  | PNG 128, VRayBitmap Auto | 0.216 / 0.108 / 0.216 | 0.038 / 0.011 / 0.038 | | 0.032 / 0.007 / 0.032 (as imported) |

  V-Ray lights a gamma-off scene on its internal values and the display shows the sum: srgb_to_linear of a sum is
  not the sum of srgb_to_linear, so no decode of each texel matches a sky that is not one value, and a decoded albedo
  times a decoded light is not the decoded product (the grey plane). The material rule is exact for one value but
  lights the sun's floor 1664 times the target; its own decode is 2.3 times the target at 0.5, 0.16 times at 4.0 and
  0.05 times with the sun, as a dome's multiplier already is (the untextured row). Neither is within a factor 2 of
  the target on every float row (the plan's gate); a float dome texture keeps its own decode, the smaller worst case
  (about 21 times against 1664; `convert/lights/`, `dome_texture`; a line in the report), and the display-referred
  light is maxdrop-6n0.6.20 (below). On an 8-bit display a value above 1 is white
  in both. An 8-bit dome texture keeps the material rule (within 0.007 of the target). A rule that sees the sky
  decoded only from the camera needs the World's nodes (a Light Path): drawn since maxdrop-6n0.6.21 (below).
- Maps at a color root and in a mask (maxdrop-6n0.6.18), V-Ray 5.2 renders of VRayLightMtl planes (a VRayMtl's
  self-illumination for the slot amounts) under an orthographic camera (a Falloff plane tilted 60 degrees: facing
  ratio 0.5), each plane's internal value, a 9 x 9 pixel mean; greys and colors are swatches (VRayColor), Bm a 128
  grey 8-bit PNG and CBm a (200, 100, 50) PNG (Bitmaps, automatic gamma). With the gamma on and off the internal value
  is the same on every swatch row (a Bm row with the gamma on: the image decoded first):

  | Map | internal value | shown with the gamma off (Blender linear) |
  |---|---|---|
  | Falloff 40 -> 220, Towards / Away, Perpendicular / Parallel; (200, 40, 40) -> (40, 60, 220) | 0.333 / 0.510; (0.471, 0.196, 0.510) | 0.091 / 0.223; (0.188, 0.032, 0.223) |
  | Falloff of map 1 Bm and color 2 220 | off 0.682, on 0.541 | 0.423 |
  | Color Correction: brightness 20 over 128; contrast 30 over 100; gamma 2.0 over 128; gain 50 % over 200 | 0.702; 0.360; 0.708; 0.392 | 0.451; 0.106; 0.460; 0.127 |
  | Color Correction over (200, 100, 50): saturation -50 %; hue 120 | (0.637, 0.441, 0.343); (0.196, 0.784, 0.392) | (0.364, 0.164, 0.096); (0.032, 0.578, 0.127) |
  | Output: level 0.5 over 200; offset 0.2 over 100; level 0.5 over Bm | 0.392; 0.592; off 0.251, on 0.110 | 0.127; 0.310; 0.051 |
  | RGB Tint (200, 50, 0) / (0, 150, 100) / (30, 0, 255) over (200, 100, 50) | (0.638, 0.384, 0.350) | (0.365, 0.122, 0.100) |
  | self-illumination 40, its map VRayColor 220 / Bm at 50 %; (200, 40, 40), its map (40, 60, 220) at 25 % | 0.510 / off 0.329, on 0.188; (0.627, 0.176, 0.333) | 0.223 / 0.089; (0.351, 0.026, 0.091) |
  | Mix black -> white by a Mix 40 -> 220 at 50 % / by VRayColor 128 / by Bm; by a Composite 40 under 220 at 50 %; by the Falloff | 0.510 / 0.511 / off 0.511, on 0.312; 0.510; 0.510 | 0.223 / 0.225 / 0.225; 0.223; 0.223 |
  | Mix black -> white by a Color Correction: brightness 20 over 128; monochrome / invert / red to all over (200, 100, 50) or CBm | 0.702; 0.458 / 0.542 / 0.784 | 0.451; 0.177 / 0.256 / 0.578 |

  So with the gamma off V-Ray computes each of them on the values it holds (a swatch and a Bitmap as stored) and the
  display shows the result decoded, as em3.158's Mix: at a color root converted in STORED under one Decode (a Tint or
  an Output over a constant folded exactly), a slot's amount below 1 mixing the input's own value as stored with its
  map (a Standard's Diffuse Level other than 1 on its diffuse map keeps the decoded mix, while with a Diffuse Level
  map the diffuse at level 1 takes the stored one: neither measured with an amount); in a mask the mean
  of it decoded (a Mix, Composite, CoronaMix or Falloff: Decode mean; a Color Correction, Tint or Output: the mean
  after the color, `_mask_mean`). Corona 12 renders (CoronaLightMtl planes, a pass and a time limit) give the same
  internal values for a Mix, Composite, Falloff, Color Correction, Output, Tint, CoronaMix and a Mix in a mask, gamma
  on and off. Two gamma-on differences the probe showed are fixed with it: a Color Correction's saturation is HSL
  (towards (max + min) / 2, which the builder draws in Math nodes; the Hue / Saturation / Value node's HSV gave
  (0.784, 0.588, 0.490)), and a custom rewiring in a mask picks its channel (red to all 0.784; the mask rule's grey
  gave 0.457). Before, 26 of the 36 gamma-off planes were off by more than 0.02 (worst 0.327); Blender 5.2 renders of
  the probe scenes now agree with V-Ray within 0.0084 on every plane, gamma on and off, and with the Corona renders
  within 0.0082. A first Corona pass in a 3dsmaxbatch session whose earlier scripts had failed rendered a Bitmap
  automatic decoded with the gamma off (0.2195, both modes alike): run again in a session of its own it gave 0.502.
  Such a pass is caught by a control row (a Bitmap automatic) rendered in both modes.
- A VRayBitmap From 3ds Max height (maxdrop-6n0.6.19), V-Ray 5.2 through VRayBumpNormals, em3.159's ramp: with the
  gamma off it is read as stored in every slot tried (VRayMtl bump directly, under an Output, under a Mix, Normal
  Bump's and VRayNormalMap's bump input), with it on decoded, as a Bitmap automatic (slope ratio about 1 against
  3.3; VRayBitmap None stored and sRGB decoded in both modes). em3.159's reading of the bump slot (decoded with the
  gamma off) does not reproduce: its own probe script run again in a fresh 3dsmaxbatch session gives stored (1.73 /
  1.73 degrees at 0.25 / 0.75 of a tooth), as the em3.159 table row says. A Standard material's bump does not reach
  VRayBumpNormals (flat in both modes): not measured. Blender 5.2 renders of the probe scenes show V-Ray's stored or
  decoded pattern on every plane; the rule is unchanged.
- The sky and the light of a gamma-off dome (maxdrop-6n0.6.21, maxdrop-6n0.6.20), V-Ray 5.2, em3.166's scenes again
  and mirrors (VRayMtl reflection 255 / 128, Fresnel off, glossiness 1) beside a white floor under a VRayBitmap Auto
  of a uniform EXR, each camera's 32 x 32 render averaged:

  | Dome | white / grey mirror | floor | sky |
  |---|---|---|---|
  | EXR 0.5 | 0.500 / 0.251 | 0.4995 | 0.500 |
  | EXR 4.0 | 4.000 / 2.008 | 3.9995 | 4.000 |
  | EXR 0.5, multiplier 2 | 1.000 / 0.502 | 0.9997 | 1.000 |

  The gamma on gives the same. The sky is the multiplier times the texel, a mirror the sky times its reflection. With
  the gamma off camera rays now see the sky's value decoded (`build/world.py`: a second Background, the sRGB curve of
  texture x strength, picked by the Light Path's Is Camera Ray; an untextured dome its color as stored x strength,
  decoded): Blender 5.2 renders (Cycles and EEVEE) of every float and untextured sky of em3.166's scenes and these
  within 0.02 of srgb_to_linear(V-Ray) (2 % above 1); floors and planes as em3.166 measured. Other rays keep the
  texture's own decode: a mirror of the 0.5 sky would be exact with the camera's reading (0.214; the light's gives
  0.5) and the grey one nearer (0.046 against 0.051; 0.108), but a rough reflection of the sun's 2000 would take the
  camera's reading as the material rule's floor does (1664 times the target): reflections follow the light, and so
  does the sky seen through glass (transmission rays: 0.5 for a target of 0.214; not rendered). The camera's sky is the
  value at the import's Light Strength, V-Ray's at the default one. An 8-bit
  dome texture keeps the material rule for every ray (exact at multiplier 1, em3.166). The display-referred light
  (maxdrop-6n0.6.20): V-Ray's internal value is the same with the gamma on and off on every probe row (em3.123,
  em3.158, em3.165, em3.166 and the rows above), and the gamma-on import matches it within 0.007 to 0.0092, so a
  gamma-off scene imported on those values (the gamma-on rules, a Bitmap read as stored) and shown through Blender's
  Raw view, which puts the value on the display as it is (checked on 4.2, 4.5 and 5.2: a 0.5 emission saves byte 128,
  Standard 188), would match V-Ray's display on every floor, plane and sky. Not done: the view belongs to the whole
  Blender scene (an import into a file with other content, or a gamma-on scene imported with it, cannot both be
  right), and as an option it needs image rules of its own (a Bitmap's gamma override read as stored, CoronaNormal's
  Add gamma) across the gamma-off rules. The cost stays as em3.166's table measures it (a dome at 0.5 lights a white
  floor 2.3 times the target).

## Summary properties

`maxdrop/reader/metadata.py` reads them; `tests/unit/test_metadata.py` checks every fixture against its oracle.

- `\x05DocumentSummaryInformation` is an OLE property set ([MS-OLEPS]) of code page 65001 in every fixture. Its
  section `D5CDD502-2E9C-101B-9397-08002B2CF9AE` holds the heading pairs (property 12: a vector of variants, a
  heading string then an `i4` count) that cut the document parts (property 13: a vector of strings) into groups:

  | Group | Parts (box_poly_standard) |
  |---|---|
  | General | `3ds Max Version: 22.00`, `Uncompressed`, `Build: 22.2.0.2176`, `Saved As Version: 22.00` |
  | Mesh Totals | `Vertices: 8`, `Faces: 6` (`Vertices` = the sum of the oracle's `eval_verts`, after the modifiers: 114 in modifier_pivot, whose nodes' `base_verts` add up to 60) |
  | Scene Totals | `Objects`, `Shapes`, `Lights`, `Cameras`, `Helpers`, `Space Warps`, `Total` (`Total` = the oracle's `node_count`: layers_flags has 7 objects and 1 helper, its group head) |
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
parameter id, within 1e-5 (relative above 1), and holds each fixture's count of compared values at or above its
`FLOORS` entry (as of 2026-11-22: 193 values in vray_basic, 637 in vray_maps, 2,024 in vray_wrappers, 295 in
standard_physical). An animated parameter is checked against the oracle's `controllers`: the reader's
controller is the block reference 3ds Max holds it at, of the same class, and its saved value is the value at frame 0
(pblock_animated: 6 controllers). `tests/unit/test_pblock.py` covers each rule on synthetic bytes.

A ParamBlock2 is an object of class `(0x82, 0)`, superclass `0x82`, referenced by its owner (the material, map or
part whose parameters it holds):

| Chunk | Content |
|---|---|
| `0x0009` | 16 bytes: `u32` the owner's class index (its chunk id in the Scene stream), `u16` block id (the descriptor's: VRayMtl 1 to 6, Bitmap 0 and 1), `u32` descriptor version (`0x55F03700` in most blocks: as of 2026-11-22 in 869 of the 991 blocks of the 54 fixtures' material graphs, other values in the rest), `u16` number of entries, `u32` the owner's object index (an object that references the block). `tests/unit/test_pblock.py` checks the owner and its class index on every block of every fixture |
| `0x000B` | instead of `0x0009`: the owner's ClassID (8 bytes, the descriptor's class), then the same 16 bytes with the owner's superclass in place of its class index (checked the same way). As of 2026-11-22 no material-graph block of the fixtures has it, and every owner is of superclass `0x1160` (ViewportManager, Properties, ParameterCollectorCA, Area Light Sampling Custom Attribute, VRayPhysCamAttributes) |
| `0x100E` | one per stored parameter, below |
| `0x0013` | the owner references, below |
| `0x000F`, `0x0003` | the asset of the file-name or bitmap entry before it, below |
| `0x000C`, `0x0011`, `0x1005` | not read (rollout state and names) |

An entry (`0x100E`): `u16` parameter id, `u32` type (the SDK's ParamType2; bit `0x800` = a table), `u32` the
parameter definition's flags (the same bits the SDK's `ParamDef.Flags` reports: `0x1` animatable, `0x2`
transient, `0x100` P_NO_REF, `0x200` P_OWNERS_REF), `u32` unknown, then:

- a scalar: a `u8` tag and the value. Tag `0x40` = a stored value, `0xC0` = the stored value of an animatable
  parameter, `0x80` = a controller, no value (pblock_animated: VRayMtl `diffuse` and `reflection_glossiness`,
  VRayBlendMtl `blend` element 1 and `texmap_blend_multiplier` element 0, VRayNormalMap `normal_map_multiplier` and
  `bump_map_multiplier`). The controller is a reference of the block, below; a Bezier Float keeps its saved value
  in `0x7127{0x2501: f32}`, a Bezier Color in `0x7127{0x2501: 3 x f32}` (0..1), the value at frame 0 when saved
  there;
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
  from the fixtures' `0x0013` tables (vray_more's: VRayOverrideMtl at 1 to 5, VRayLightMtl `texmap`,
  `opacity_texmap`, `displacement_texmap` at 1, 2, 3, as corpus scene B has them; VRayMtlWrapper, Double Sided and
  Shellac at 1, 2) and, for Composite and class `0xC90017A5` (no fixture `0x0013` entry: texmap_rules' Composite
  keeps its maps as block references), from corpus scene B's (format 20000); every object of scene A agrees.
  Output `map1` (0) at slot 0 comes from scene A alone (maxdrop-6n0.6.3): its 8 Output maps hold the map at owner
  slot 0 (1 the TexOutput, 2 the block), the map 3ds Max reports, and 2 of them store -1; the fixtures (3ds Max
  2020) store that index directly and list only `output` (2) at 1 in `0x0013`.
  `test_materials.py` checks each entry against the fixtures' tables. Only a block without
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
- A controller takes the next slot of the same sequence, in entry order, whichever was animated first
  (pblock_animated, slots from 3ds Max's `GetControllerByID` and the block's references): VRayBlendMtl `baseMtl`
  0, `coatMtl` 1-9, the controller of `blend` element 1 at 10, `texmap_blend` 11-19, the controller of
  `texmap_blend_multiplier` element 0 at 20 (39 slots); VRayNormalMap `normal_map` 0, the controller of
  `normal_map_multiplier` 1, `bump_map` 2, the controller of `bump_map_multiplier` 3; VRayMtl block 1 (no block
  references) `diffuse` 0, `reflection_glossiness` 1. A parameter without a controller takes no slot. A damaged
  entry that may have taken slots (head unreadable, a block-held reference type, any table, a scalar cut before
  its tag) leaves every later slot unresolved.

The material and map rules read such a parameter as its controller's value at frame 0
(`reader.controllers.parameter_value`, through `convert/params.py`; maxdrop-em3.152): a float controller as a
transform's float axis is read (keyframes, Float List), a Bezier Color (superclass `0x9005`, ClassID `(0x2011, 0)`)
from its saved `0x2501` color when its `0x2500` interval holds frame 0, else from its keys `0x2526`, 80 bytes each
(`i32` time, `u32` flags, the color at byte 8, then tangents as Bezier Position's; pblock_animated: two keys, key 0
the saved color), linearly between two keys (its curve not measured). Checked against the oracle's frame-0 values
of pblock_animated's 6 controllers. A Float List with an entry of another class gives no value (the default), not the
sum of the rest. Not measured: an hsv parameter (not read); a float controller on an integer parameter (int, bool, radio
button...; no fixture has one): a whole number is read as that integer, a fraction not (the class default); a
percent or angle parameter takes the controller's value as stored, like its stored value.
What a read meets is a line in the import report, under the material or map (maxdrop-6n0.6.32): each issue
`parameter_value` gives (between two Bezier Color keys, a saved value beside several keys without its interval,
keys of an unknown layout, a list weight not stored, another class, a damaged controller), and a parameter left at
its default; in a map's graph it marks the graph approximated. A dome light's VRayBitmap reads its rotation and
switches the same way.

Transient parameters are mostly not stored (VRayMtl: 25 of the 80 parameters of block 1, among them
`bump_multiplier` 102 and the `texmap_*` 109-128 that mirror block 4). Some are stored anyway with a stale value
(VRayMtl's alias 56 in block 5, VRayBlendMtl `blend_0`...): the parity test does not compare transient
parameters. A block may store no entry at all (Standard's dynamics block, 4).

The old ParamBlock (class `(8, 0)`): `0x0001` `u32` count, `0x0005` `u16` (unknown: 2, 3 or 6), then per
parameter a `0x0002` container: `0x0003` `u32` index, an empty `0x0004` on some (unknown), and the value chunk
`0x0100` + ParamType: `0x0100` float, `0x0101` int, `0x0104` bool (fixtures: the Bitmap's Placement and Output,
the Standard material's sampler); `0x0102` color and `0x0103` point3 follow the SDK's ParamType, no fixture has
them.
A parameter a controller holds has an empty `0x0200` + ParamType instead (no value), and the block's own
references (`0x2034`) hold the controllers, one per such parameter in index order: stack_basic's Noise block
animates entry 7 alone, a Bezier Float at slot 0; the Standard shader blocks of standard_physical and
standard_shaders animate 22 entries (0, 2, 4 to 10, 21 to 33), entry 2 (`0x0202`, a color) a Bezier Color at slot 1,
the bools On/Off controllers. A map's Coordinates and Output parameters held by a controller are read at frame 0
as a ParamBlock2's are (`convert/params.py` `old_value`; maxdrop-6n0.6.32); no fixture animates a Placement or an
Output, so that path is not measured.

## Materials and maps

`maxdrop/reader/materials.py` reads them; `test_materials.py` checks on every fixture that the materials and maps
reached from the nodes are those of the oracle's graph, and that each one's sub-materials and maps are among the
reader's children.

- A material has superclass `0x0C00`, a map `0x0C10`. The name is a `0x4001` string inside a container whose id
  depends on the class: `0x4000` (Standard, Bitmap, Multi/Sub-Object, Shell, VRay2SidedMtl, VRayBlendMtl,
  VRayNormalMap, VRayFastSSS2, both car paints, VRayOverrideMtl, VRayMtlWrapper, Double Sided, Shellac), `0x5431`
  (VRayMtl, VRayLightMtl), `0x0100` (Physical Material). The reader takes the first container child
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
  planar from object XYZ, 2 vertex color channel, 3 planar from world XYZ), `0x900B` the map channel, `0x9009` the
  environment projection (1 spherical, 2 cylindrical, 3 shrink-wrap, 4 screen; kept in texture mode too, 4 there by
  default: a probe scene with one Bitmap per projection). Its old
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
| VRay2SidedMtl `(0x6066686A, 0x11731B4B)` | 0 | 0 frontMtl, 1 backMtl, 7 translucency, 3 backMtlOn, 4 texmap_translucency, 8 force1SidedSubMtls; V-Ray 5.2 renders an empty frontMtl's side not at all at translucency black (the back shows backMtl when backMtlOn, nothing otherwise); at the default translucency (0.5) the front is half transparent, with no front or back color (maxdrop-6n0.6.4) |
| VRayBlendMtl `(0x3DA0041B, 0x0F436E31)` | 0 | 0 baseMtl, 1 coatMtl (table), 2 blend (color table), 3 texmap_blend, 4 texmap_blend_multiplier, 6 coatMtl_enable, 5 additiveMode; V-Ray 5.2 renders an empty baseMtl as nothing below the coats (a coat at blend grey: alpha 0.5; blend black: not rendered) (maxdrop-6n0.6.4) |
| Shell Material `(0x255, 0)` | 0 | 2 originalMaterial, 3 bakedMaterial, 0 viewportMtlIndex, 1 renderMtlIndex |
| VRayOverrideMtl `(0x15D20E6B, 0x54E217EB)` | 0 | 0 baseMtl, 2 giMtl, 4 reflectMtl, 6 refractMtl, 8 shadowMtl (getSubMtl order), each followed by its switch (1 baseMtl_on ... 9 shadowMtl_on); V-Ray 5.2 renders baseMtl for the camera whatever baseMtl_on says, and an empty baseMtl black (maxdrop-em3.136) (vray_more) |
| VRayMtlWrapper `(0x409517DF, 0x3A5F44B6)` | 0 | 0 baseMtl, 2 generateGIMult (vray_more) |
| Double Sided `(0x210, 0)` | 0 | 0 material1 (facing), 1 material2 (back), 2 / 3 map1Enabled / map2Enabled, 4 translucency (percent); V-Ray 5.2 renders both sides whatever the switches say, an empty material1 not at all (the front is not rendered), the scanline renders a side switched off black, and an empty material1 too (an empty material2: not measured) (maxdrop-em3.136) (vray_more) |
| Shellac `(0x46EE536A, 0)` | 0 | 0 shellacMtl1 (base), 1 shellacMtl2, 2 shellacColorBlend (percent); V-Ray 5.2 and the scanline render an empty shellacMtl1 as shellacMtl2, at blend 0 too (maxdrop-6n0.6.4) (vray_more) |
| VRayLightMtl `(0x7CCF263E, 0x3F5B39B9)` | 0 | 0 color, 1 multiplier, 2 / 3 texmap (on), 5 / 6 opacity_texmap (on), 9 displacement_texmap (vray_more) |
| VRayFastSSS2 `(0x3F2C5FAA, 0x750008BC)` | 0 | 26 diffuse_color, 27 / 28 / 29 texmap_diffuse_color (on, multiplier), 36 diffuse_amount, 2 sub_surface_color, 16 scatter_color, 57 overall_color, 0 scatter_radius (a plain float in centimeters whatever the system unit), 22 scale, 31 IOR, 40 specular_color, 44 specular_amount, 51 specular_glossiness, 3 / 4 / 5 texmap_bump (on, multiplier), 85 / 86 / 87 texmap_opacity (on, multiplier) (vray_more) |
| VRayCarPaintMtl `(0x38312C74, 0x47280883)` | 0 | 0 base_color, 1 / 2 / 3 texmap_base_color (on, multiplier), 4 base_reflection, 8 base_glossiness, 12 flake_color, 16 flake_glossiness, 27 coat_color, 31 coat_strength, 39 coat_glossiness, 55 / 56 / 57 texmap_base_bump (on, multiplier: 30 as created, V-Ray 5.2) (vray_more) |
| VRayCarPaintMtl2 `(0x56BC47E2, 0x03E008C7)` | 0 | 0 base_color, 1 / 2 / 3 texmap_base_color (on, multiplier), 4 base_reflection, 8 base_glossiness, 12 flake_color, 16 flake_glossiness, 27 coat_color, 31 coat_amount, 81 coat_ior, 39 coat_glossiness, 54 / 55 / 56 texmap_base_bump (on, multiplier: 30 as created, V-Ray 5.2) (vray_more) |
| Multi/Sub-Object `(0x200, 0)` | 0 | 0 materialList, 1 mapEnabled, 2 names, 3 materialIDList (zero-based) |
| Standard `(2, 0)` | 0 shader | 0 shaderType, 2 twoSided |
| | 1 extended | 1 opacity (fraction), 6 ior |
| | 3 maps | 0 mapEnables, 1 maps, 2 mapAmounts (fractions), one element per map channel of the shader, in the shader's order (below) |
| Its shader (a part at reference 2, superclass Shader `0x10B0`) | 0 | Phong `(0x37, 0)`, Blinn `(0x38, 0)`, Metal `(0x39, 0)`: 0 ambient, 1 diffuse, 2 specular, 6 useSelfIllumColor, 7 selfIllumAmount, 8 selfIllumColor, 9 specularLevel, 10 glossiness, 11 soften (standard_physical, standard_shaders) |
| | | Anisotropic `(0x2857F460, 0)`: 0 ambient, 1 diffuse, 2 specular, 3 selfIllumColor, 4 diffuseLevel, 5 specularLevel, 6 selfIllumAmount, 7 glossiness, 8 anisotropy, 9 orientation, 14 useSelfIllumColor |
| | | Oren-Nayar-Blinn `(0x2857F421, 0)`: 0 ambient, 1 diffuse, 2 specular, 3 selfIllumColor, 4 selfIllumAmount, 5 glossiness, 6 specularLevel, 7 soften, 8 diffuseLevel, 9 diffuseRoughness, 13 useSelfIllumColor |
| | | Multi-Layer `(0x2857F470, 0)`: 0 ambient, 1 diffuse, 2 selfIllumColor, 3 selfIllumAmount, 4 diffuseLevel, 5 diffuseRoughness, 6 / 7 / 8 / 9 / 10 specular, specularLevel, glossiness, anisotropy, orientation of the first layer, 11-15 the same of the second, 19 useSelfIllumColor |
| | | Translucent Shader `(0x2857F480, 0)`: 0 ambient, 1 diffuse, 2 specular, 3 selfIllumColor, 4 selfIllumAmount, 5 glossiness, 6 specularLevel, 7 diffuseLevel, 8 filter, 9 translucentColor, 10 backsideSpecular, 14 useSelfIllumColor |
| | | Strauss `(0x2857F450, 0)`: 0 diffuse, 1 glossiness, 2 metalness (standard_shaders). Ambient is not read: one save of standard_shaders held the diffuse there for Anisotropic, Oren-Nayar-Blinn, Multi-Layer and Translucent whatever was set, a later save of the same script (maxdrop-em3.105) the ambient as set |
| Physical Material `(0x3D6B1CEC, 0xDEADC001)` | 0 | 1 base_weight, 2 base_color (float color with alpha), 3 reflectivity, 4 roughness, 5 roughness_inv, 6 metalness, 10 refl_color, 11 diff_roughness, 30 transparency, 31 trans_color, 33 trans_ior, 37 thin_walled, 50 emission, 51 emit_color, 52 emit_luminance (cd/m2), 60 coating, 61 coat_color, 62 coat_roughness, 63 coat_roughness_inv, 66 coat_ior; maps 100-120 (`*_map`: 101 base_color, 102 reflectivity, 103 refl_color, 104 roughness, 105 metalness, 109 transparency, 116 emission, 117 emit_color, ...), 130 bump_map, 131 coat_bump_map, 132 displacement_map, 133 cutout_map, each switched on by its id + 50 (`*_map_on`, default on), 230 bump_map_amt (a factor, default 0.3); 250-270 mapM0 ... mapM20 are saved empty, 3ds Max answers the map of id - 150 (standard_physical, standard_shaders) |
| Bitmap `(0x240, 0)` | 0 | 0-3 clip u, v, w, h, 7 cropPlace, 8 filtering, 12 preMultAlpha, 13 bitmap (asset), 14 coords, 15 output |
| VRayNormalMap `(0x71FA6E51, 0x72057C2F)` | 0 | 0 normal_map, 2 normal_map_on, 3 normal_map_multiplier, 4 bump_map, 5 bump_map_on, 6 bump_map_multiplier, 1 map_channel, 7 flip_red, 8 flip_green, 9 swap_red_and_green |

A Standard material's map tables follow its shader's map channels (3ds Max 2020, zero-based; `getSubTexmapSlotName`
and the saved table agree on a probe scene with a map in each channel; standard_maps puts a named map into every
channel MaxDrop reads by the name 3ds Max gives it, on Blinn, Anisotropic, Multi-Layer, Oren-Nayar-Blinn, Translucent
and Strauss). Blinn, Phong, Metal: 0 ambient, 1 diffuse, 2 specular color, 3 specular level, 4
glossiness, 5 self-illumination, 6 opacity, 7 filter color, 8 bump, 9 reflection, 10 refraction, 11 displacement.
Anisotropic: 0 ambient, 1 diffuse, 2 specular color, 3 diffuse level, 4 specular level, 5 glossiness, 6 anisotropy,
7 orientation, 8 self-illumination, 9 opacity, 10 filter color, 11 bump, 12 reflection, 13 refraction, 14
displacement. Oren-Nayar-Blinn and Translucent Shader: 0 ambient, 1 diffuse, 2 specular color, 3 glossiness, 4
specular level, 5 self-illumination, 6 opacity, 7 filter color, 8 diffuse level, 9 diffuse roughness (Translucent:
translucent color), 10 bump, 11 reflection, 12 refraction, 13 displacement. Multi-Layer: 0 ambient, 1 diffuse, 2
diffuse level, 3 diffuse roughness, 4-8 specular color, level, glossiness, anisotropy, orientation of the first
layer, 9-13 of the second, 14 self-illumination, 15 opacity, 16 filter color, 17 bump, 18 reflection, 19 refraction,
20 displacement. Strauss: 0 color, 1 glossiness, 2 metalness, 3 opacity, 4 refraction filter, 5 bump, 6 reflection,
7 refraction, 8 displacement. MaxDrop reads each shader's own channels (`STD_SLOTS` in
`convert/materials/standard.py`; a shader without a rule with Blinn's); on Strauss the metalness map drives the
metallic input.

The tables (maps, mapEnables, mapAmounts) can keep the layout the material was created with (Blinn's: bump 0.3 at 8)
while 3ds Max answers its shader's: an amount not set after the shader switch, with or without a map (standard_maps
FixtureMapsUnsetAmounts, Anisotropic created as Blinn, maps set without touching their amounts: self-illumination at
8 stored 0.3, bump at 11 stored 1.0; 3ds Max answers 1.0 and 0.3), and a map set before the switch, with its switch
(FixtureMapsSwitchedAfter: a Blinn bump map moved by 3ds Max to Anisotropic's bump at 11, stored at 8, Anisotropic's
self-illumination). A channel read before the save (MAXScript `mapAmounts[i]`) is written back into the table, the
others stay as they were (3ds Max 2020). 3ds Max answers from the material's Texmaps object (class `(0x1200, 0)`,
superclass `0x1080`, the Standard material's reference 1), whose leaves sit directly in its chunk: `0x5100 +
channel` a channel's amount (`f32`) where it is not 1.0 (absent: 1.0), `0x5003` a `u32` mask of the switches (bit k
= channel k: the on switch, not the occupancy; a map switched off clears its bit, a channel switched on without a
map sets it), and its reference `2k + 1` the map of channel k (`2k`: a Bezier Float holding the amount). On every
channel of the six shaders with a map in each, the Texmaps object holds what 3ds Max answers; an empty channel's
amount can differ (an empty Multi-Layer bump, 17: 0.3 stored, 1.0 answered), which nothing uses. MaxDrop reads map,
switch and amount from the Texmaps object (`reader.materials.standard_maps`) and the tables only for a material
without a readable one (maxdrop-em3.148).

Diffuse Level (Anisotropic, Multi-Layer, Oren-Nayar-Blinn, Translucent Shader; a fraction, 1 = 100 %), measured
with Default Scanline renders of a plane lit head-on, gamma off, swatch (200, 100, 50): the pixel is linear in the
level on all four (50 % half, 200 % exactly double: the product is not clamped), Blinn has none; with
self-illumination the lit part is scaled and the self-lit part is the swatch as set (amount 100 % renders the swatch
at level 50 and 100); a diffuse map (amount 100 or 50) is scaled too. So the shader's diffuse is swatch times level
in the stored value, and MaxDrop applies the level before the swatch rule, which clamps to 0..1 (standard_shaders
FixtureMultiLayerLevel: green 200 at 150 % is white), the opposite order of CoronaLegacyMtl's levels and Physical's
base weight; the emission keeps the unscaled diffuse; a diffuse map is scaled too (the next paragraph). A missing or
animated diffuse, glossiness or specular level takes the shader's value
as created (3ds Max 2020): diffuse 149.94 grey (Blinn, Phong, Metal; MaxDrop 150) or 127.5 (the others, Strauss included);
glossiness 10 % (Blinn, Phong, Metal), Anisotropic 25, Multi-Layer 50, Oren-Nayar-Blinn 25, Translucent 30,
Strauss 20; specular level 5 % (Anisotropic, Multi-Layer), 0 the others (`SHADER_DEFAULTS`).

The Diffuse Level map (channels: Anisotropic 3, Multi-Layer 2, Oren-Nayar-Blinn and Translucent 8;
`StdSlots.diffuse_level`), measured the same way with flat Checker maps (swatch 100 60 30, maxdrop-em3.150), the same
numbers on the four shaders: a grey 128 map at amount 100 renders 0.502 of the level-100 pixel at level 50, 100 and
150 (it replaces the level), grey 255 1.0, grey 64 0.25, black 0; at amount 50 grey 128 at level 50 0.5006 and grey
255 at level 150 1.25; switched off, the level alone; a pure red, green or blue map 1/3, yellow 2/3 (the mean of its
channels). A flat diffuse map with it: grey 128 at level 50 renders 64; at amount 50 lerp(swatch, 128, 0.5) x 0.5,
and with the level map lerp(0.5, map, its amount) in place of 0.5. So the diffuse is lerp(swatch, diffuse map,
amount) x lerp(level, mean(level map), amount), on stored values with the gamma off, and the same product on linear
values with the gamma on (maxdrop-6n0.6.14, gamma 2.2, files in 2.2, the four shaders alike: a swatch and a Checker
grey as stored, 128 grey as a level map 0.502 of the level-100 pixel as with the gamma off; a 128 grey PNG level map
0.2192 (decoded: (128 / 255)^2.2 = 0.2195); a 64 grey PNG 0.0470 (0.0476); the 128 PNG at amount 50 and level 50 0.3594; a
(200, 100, 50) PNG level map 0.2470, the mean of its decoded channels; the 128 PNG as the diffuse map at level 50
0.1096 linear; the color PNG at 61 % with a 64 grey PNG level map at 62 % and level 40 0.0925 0.0307 0.0113 linear,
the product of lerp(swatch, decoded map, 0.61) and lerp(0.4, 0.0476, 0.62)): what MaxDrop draws with the gamma on,
the level as is and the level map a mask read linear.
MaxDrop scales the diffuse map by the level as the swatch rule makes it
(`MapRef.scale`, before the amount mixes it with the swatch times the level; gamma off: the sRGB curve, not clamped,
since Blender decodes the map: the decoded map times the decoded level is within 0.006 linear of the decoded product
for levels up to 100 %, where a plain x level is up to 0.29 too bright). With a Diffuse Level map the base color is
the diffuse at level 1 times the mean (a Tint of rows 1/3) of lerp(level, the map as a mask, its amount): decoded
with the gamma off as the level is, and mixed on decoded values, the approximation of the gamma-off mixes (the
slot amount's mix of a diffuse map with its swatch has it too): up to 0.29 linear off at a mid amount (level 0, a
white map at amount 0.55: 0.55 where the decoded mix is 0.26), none at amount 0 or 100. A grey
or constant level map at amount 100 gives the decoded level exactly (a constant mask is the decoded mean of its
swatch); a colored image is decoded per channel before the mean, so a saturated one is too bright with the gamma
off (pure red: 1/3, where the decoded mean is 0.09), as an image mask between two colors already is.

The maps of texmap_rules (block 0 each; `convert/texmaps/`):

| Class (ClassID) | Parameters |
|---|---|
| Bitmap `(0x240, 0)` | 6 apply (cropping / placement on), 9 monoOutput (1 alpha), 10 rgbOutput (1 alpha as gray), 11 alphaSource |
| Falloff `(0x6EC3730C, 0)` | 0 color1, 1 map1Amount, 2 map1, 3 map1On, 4 color2, 5 map2Amount, 6 map2, 7 map2On, 8 type (0 towards / away, 1 perpendicular / parallel, the default, 2 Fresnel, 3 shadow / light, 4 distance blend), 9 direction (0 viewing), 10 node, 11 mtlIOROverride, 12 ior, 13 extrapolateOn, 14 nearDistance, 15 farDistance (texmap_wrappers); its Output part; the MixCurve is a Curve Control reference, not in the block (below) |
| VRayDirt `(0x2F567899, 0x090D5EA4)` | 12 occluded_color, 13 unoccluded_color, 17 texmap_unoccluded_color, 18 its on, 19 its multiplier |
| VRayColor2Bump `(0x31E15D1D, 0x7D7E2810)` | 0 map, 1 height (world units), 2 bump delta scale |
| VRayColor `(0x58F82B74, 0x73B75D7F)` (vray_texmaps) | 9 color_mode (0 RGB, 1 temperature: V-Ray writes the temperature's color into color), 8 temperature, 0 / 1 / 2 red / green / blue (color again), 4 rgb_multiplier, 3 alpha, 5 color, 10 color_gamma (applied after the multiplier), 11 rgb_primaries; block 1 (6 gamma_correction, 7 gamma_value) is transient |
| Output `(0x2B0, 0)` | 0 map1, 1 map1Enabled, 2 output (its Output part) |
| RGB Tint `(0x224, 0)` | 0 red, 1 green, 2 blue, 3 map1, 4 map1Enabled |
| Mix `(0x230, 0)` | 0 mixAmount (fraction), 1 lower, 2 upper (fractions, the defaults 0.3 and 0.7), 3 useCurve, 4 color1, 5 color2, 6 map1, 7 map2, 8 mask, 9 / 10 / 11 their switches; Use Curve below |
| RGB Multiply `(0x290, 0)` | 0 color1, 1 color2, 2 map1, 3 map2, 4 / 5 their switches, 6 alphaFrom |
| Color Correction `(0x2D0, 0)` | 0 color, 1 map, 2 rewireMode (0 normal, 1 monochrome, 2 invert, 3 custom), 3..6 rewireR, G, B, A (0..2 R, G, B, 3 A, 4..7 their inverse, 8 monochrome, 9 one, 10 zero; modes 1 and 2 store (8, 8, 8, 3) and (4, 5, 6, 3): texmap_wrappers), 7 hueShift (degrees), 8 saturation (%), 9 tint, 10 tintStrength, 11 lightnessMode (1 advanced), 12 brightness, 13 contrast, 14 exposureMode, 15..17 enableR, G, B, 18 gainRGB (%), 22 gammaRGB |
| Composite `(0x280, 0)` | tables: 1 mapEnabled, 3 maskEnabled, 5 blendMode (0 normal, 1 average, 2 addition, 3 subtract, 4 darken, 5 multiply, 6 color burn, 7 linear burn, 8 lighten, 9 screen, 10 color dodge, 11 linear dodge, 12 spotlight, 13 spotlight blend, 14 overlay, 15 soft light, 16 hard light, 17 pin light, 18 hard mix, 19 difference, 20 exclusion, 21 hue, 22 saturation, 23 color, 24 value: measured with renderMap), 6 layerName, 8 opacity (%), 9 mapList, 10 mask; 0, 2 and 4 have no name and are empty tables, not saved. As a constructor keyword `name` is the layer names; assigned afterwards it is the map's name (texmap_wrappers names its three) |
| Normal Bump `(0x243E22C6, 0x63F6A014)` | 0 mult_spin, 1 bump_spin, 2 normal_map, 3 bump_map, 4 / 5 their switches, 6 method (0 tangent), 7 flipred, 8 flipgreen, 9 swap_rg |
| CoronaNormal `(0x2870CEAA, 0xCC18437C)` | 500 normalMap, 501 multiplier, 502 addGamma, 503 flipRed, 504 flipGreen, 505 swapRedGreen, 507 additionalBump, 508 additionalBumpStrength, 509 additionalBumpOn |

Empty wrappers, measured (maxdrop-em3.76; 3ds Max 2020, gamma off, renderMap and V-Ray 5.2 renders with linear
color mapping, a plane under an orthographic camera). An Output or RGB Tint with map1 unset or map1Enabled off renders
exactly as the same map over an opaque white map: white through its Output part (level 0.8, offset 0.1, amount 0.5
gave the same pixel as over white) or its tint ((128, 0, 0), (0, 64, 0), (0, 0, 32) gave 0.502, 0.251, 0.125). A
VRayColor2Bump without a map renders (0.5, 0.5, 1), opaque, in a color slot (over a white map: white); it has no map
switch. On an opacity input V-Ray takes the mean (1, 0.293, 0.667). In a VRayMtl bump slot each one is flat; inside
a VRayNormalMap's normal slot the white of an empty Output or RGB Tint tilts the normal as a white map does, the
VRayColor2Bump's color is flat. Corona and the gamma on: below, after the 0.293 note. MAXScript
`copy` of an Output map loses map1Enabled (the copy renders its map).
The 0.293 is the mean of the tint rows as stored (128 / 255, 64 / 255, 32 / 255), not decoded by the gamma-off
swatch rule (0.094): in a data, bump or normal input MaxDrop takes a wrapper's rows and a swatch below a wrapper
that works on color (RGB Tint, an Output part, Color Correction) as stored, keeps its three channels, and takes the
mean at the float input (maxdrop-em3.128); a constant color in a normal map's normal slot is drawn as that color.
That a colored constant keeps its color below the wrapper, Color Correction, and the rows in a normal input
follow the same rule by assumption, not by measurement.
The same cases with the gamma on and in Corona (maxdrop-em3.127; 3ds Max 2020, V-Ray 5.2 and Corona 12 with tone
mapping off, each with the gamma off and on, a VRayLightMtl / CoronaLightMtl texmap and the opacity of a
self-illuminated VRayMtl / CoronaLegacyMtl, black background): V-Ray with the gamma on renders every case as with it
off (white, 0.725 for the Output part above, 0.502 / 0.251 / 0.125 for the tint, (0.5, 0.5, 1) for VRayColor2Bump,
0.293 and 0.667 on opacity), so (0.5, 0.5, 1) is the swatch as stored in both modes. Corona renders the same for an
unset Output or RGB Tint, an RGB Tint switched off and an unset VRayColor2Bump, but an Output with map1Enabled off
renders its map1 through its Output part (a red (200, 50, 50) map: 0.784, 0.196, 0.196 with an Output part that
changes nothing, 0.682, 0.564, 0.564 with the one above; opacity 0.392 and 0.207); the file stores the switch off. MaxDrop ignores an Output's map1Enabled when the scene's renderer (Renderer ClassIDA / B of the summary stream)
is Corona's, `(0x62A85DCC, 0x523C3604)` (Corona 12); measured with Corona's own materials, assumed for others.
Corona's opacity with few passes is noisy (up to 0.006 at 4 passes, the mean at 64).
Other materials and maps under Corona (maxdrop-6n0.6.23; Corona 12, gamma off, 32 passes, the furnace 64): in a Standard
diffuse slot (white furnace, no light, specular level 0) an Output switched off over the red Checker renders its
map too, 0.784, 0.196, 0.196, as switched on and as the Checker directly (a white Standard reads 1.0), and in a
CoronaPhysicalMtl base slot the same (0.745, 0.191, 0.194 in all three). A VRayMtl does not render under Corona 12
(white diffuse: 1.0, 0.125, 0.125; the Checker in it 1.0, 0.201, 0.201), so an Output in it cannot be read: the
scene-wide rule stands. The map switches of Mix (map1, map2, mask), RGB Multiply (map1, map2), Composite (a
layer and a layer mask) and Falloff (map1, map2), off and on over the red Checker beside green and blue own
colors in a CoronaLightMtl / VRayLightMtl texmap: Corona renders each exactly as V-Ray 5.2 (off: the own color, or
the amount for a mask). Color Correction has no map switch. A VRayDirt renders white in Corona 12 with its
unoccluded map on or off (V-Ray: the map, or the unoccluded color), so MaxDrop draws a VRayDirt white in a Corona
scene (measured in a light material's texmap; other slots, a normal map's normal slot among them, assumed).
The renderer ClassID of another Corona version: none at hand; the 371 local `.max` files name one Corona
renderer, Corona 12's. V-Ray keeps one renderer ClassID, `(0x73BAB286, 0x77F8FD0C)`, from a 3.60 save (3ds Max
2015) to 5.2: assumed for Corona.
A wrapper as a mask in a color graph, measured (maxdrop-6n0.6.2; 3ds Max 2020, V-Ray 5.2 with linear color mapping,
GI and default lights off, a VRayLightMtl texmap Mix black -> white at amount 0 whose mask is the map, V-Ray's
internal value): a VRayColor (200, 100, 50) gives 0.4575; an RGB Tint of rows (128, 0, 0), (0, 64, 0), (0, 0, 32)
over it 0.1722, the empty Tint 0.2928; an Output of RGB level 0.5 over it 0.2287, the empty Output 0.5; the Tint
over a 128 grey PNG 0.1470 with the gamma off and 0.0643 with it on, an Output of 0.5 over a (200, 100, 50) PNG
0.2287 and 0.1235. Every constant row is the same with the gamma on and off. So a mask below a Tint or an Output is
the mean of the wrapper's output on the values V-Ray holds (swatches and the Tint's rows as stored, an image by the
scene's input rule), which a gamma-off scene shows decoded: MaxDrop converts the wrapper's map as a color with the
gamma on and as stored with it off, and there takes the mean first and decodes it after (a Tint over a constant
folded exactly; otherwise a power of 2.2, within 0.005 of V-Ray on these planes). A Color Correction's saturation of
-50 over the VRayColor gives 0.4739, over the PNG 0.4739 off and 0.2770 on: not Blender's HSV saturation, so a
Color Correction directly as a mask keeps its input's mean (a grey). The same rule is assumed for Corona, a Corona
layer mask and a Diffuse Level map (not measured). With the gamma off a colored PNG as the mask itself gives
the decoded mean (0.4575 shown as 0.1768), where MaxDrop drew the mean of the decoded channels (0.2456), and an RGB
Tint on a color input renders the tint of the stored color, decoded ((0.638, 0.384, 0.350) shown as (0.365, 0.122,
0.100); MaxDrop draws (0.334, 0.057, 0.048)): the Tint left as it is.
Since maxdrop-6n0.6.36 an image read as stored (a Bitmap, a VRayBitmap From 3ds Max) as a gamma-off mask is that
image as Non-Color, the mean of its channels, then the sRGB curve in Math nodes (exact; a grey as before): the PNG
mask renders 0.1768 in Blender 5.2 (EEVEE, the 6n0.6.2 probe), and the Color Correction of saturation -50 over it
0.1768 where V-Ray gives 0.1906 (was 0.4119); every other row of the probe unchanged. Assumed, not measured: the
same for such an image anywhere in a mask graph (below an RGB Multiply, a Falloff, a Color Correction), a Corona
layer mask and a Diffuse Level map, as a swatch there is the rule of its mean; a Color Correction that rewires
channels in a gamma-off mask picks them from the stored color, the mean decoded after it, as an RGB Tint.
Since maxdrop-6n0.6.18 (measured there) a Color Correction in a mask, rewired or not, takes the color V-Ray holds (the
color with the gamma on, STORED with it off), its saturation drawn in HSL, and the mask is the mean after it, decoded
with the gamma off through the exact sRGB curve (Decode mean, as an RGB Tint's and an Output's now; they were a power
of 2.2): no longer its input's grey. A Mix, Composite, CoronaMix or Falloff in a gamma-off mask is computed on the
stored values too, an image below it read as stored.
At a gamma-off color root a Mix of two colors, a Composite and a CoronaMix take their masks as stored (em3.158):
unchanged.
Color Correction's saturation and hue, measured on V-Ray 5.2 (maxdrop-6n0.6.38; VRayLightMtl planes, gamma on, the
internal values): six VRayColors ((200, 100, 50), (230, 128, 26), (40, 80, 200), 128 grey, (250, 20, 120), (20, 200,
120)) and a (200, 100, 50) PNG, saturation -100 / -50 / +50 / +100 %, hue 30 / 120 and hue 30 with saturation +50.
Every channel is lerp(L, c, 1 + saturation), L = (max + min) / 2 (HSL), after the hue shift (HSV's rotation, which
keeps max and min, so the order does not matter), and a channel below 0 is 0, while above 1 it is kept: (200, 100,
50) at +100 % gives 1.078 0.294 0 (the light at multiplier 0.5 renders 0.539; getPixels reads any value above 1 as 1,
a VRayColor 0.6 at multiplier 2 included), and an Output offset of +0.2 over it gives 0.2 on blue (a Mix and an Output
keep a negative input: an offset of -0.5 over 0.2 mixed 50 % with white gives 0.35). The PNG is decoded first (2.2).
The builder's HSL step (maxdrop-6n0.6.18) renders every row within 0.0005 of V-Ray (EEVEE 5.2) where no channel leaves
0..1; with a saturation above 0 % it now ends in a Vector Math MAXIMUM of 0, so a channel that would fall below 0 is 0
in the graph as in 3ds Max (an emission showed a negative channel as 0 already). The hue is the Hue / Saturation /
Value node's (equal on every row).

### The Falloff mix curve

A Falloff references a Custom Curve Control `(0x14585773, 0x483A7DCF)`, superclass `0x100`, DLL
`curvecontrol.dlu` (slot 6 in the fixtures; MaxDrop finds it by its ClassID). Its reference 0 is its curve
`(0x5F2D3A0A, 0x4BE75269)`, superclass `0x100`, nameless in the class directory (falloff_curve; maxdrop-em3.84):

| Chunk | Content |
|---|---|
| `0x1000` | `u32` the point count (2 for the default curve); the head of the curve's `0x2035` is the same number |
| `0x1030` | one per point, in x order: a container holding `0x1000`, 28 bytes: `f32` x, y of the point, x, y of its in handle, x, y of its out handle (each handle as a position: the point plus the offset MAXScript and the SDK give), `u32` flags (seen: `0x102` the first point, `0x100` the last, `2` and `4` for points set as Bezier and corner) |
| `0x1020`, `0x1040` | not decoded (a `u32` 0; 28 bytes, the same in every falloff_curve curve) |

The same layout in files saved in older formats is under [Open](#open) (the Falloff mix curve in other formats).

The default curve is (0, 0) to (1, 1), its handles on its points: linear. How 3ds Max 2020 evaluates it
(`ICurve.GetValue` through .NET, matched to 1e-6; falloff_curve's `.curves.jsonl`): segment i is the cubic Bezier
of point i, its out handle, the in handle of point i + 1 and point i + 1, taken at its x. The flags do not change
it (0, 1, 2, 3, 4, 8 and 16 give the same values). A point whose y is outside 0..1 is evaluated at the nearest
bound, its handles moved with it (also after the file is loaded again); between the points the curve is not
clamped (a handle took it to 1.195). The Falloff renders lerp(color 1, color 2, curve(ratio)), not clamped either
(Scanline: 152.8 where color 2 is 128 and the curve 1.195), for Perpendicular / Parallel, Towards / Away and Fresnel
alike (within 8-bit rounding of the renders without the curve put through it). MAXScript reaches the control only
as `mixCurve.Curve_1` without its points; the fixture's script sets them through the .NET `ICurve` (`Insert`,
`SetPoint`; `GetPoint`'s point fails to cast in 3ds Max 2020, its handles and flags read).

Two points at one x (falloff_curve's FixtureCurveJump, maxdrop-em3.129): `ICurve.Insert` keeps both, in the order
inserted, also after the file is saved and loaded again, and `0x1030` stores them in that order. `GetValue`
gives the first point's y at that x itself and the second's just past it: a vertical jump (corner points from 0.8
to 0.3 at x = 32.5 / 64: 0.79998 at 0.5078, 0.300011 at 0.50782). MaxDrop draws it as two Float Curve points at one x,
kept in that order (Blender's table of 256 steps over 0..1 draws the jump across one step).

A Mix's Use Curve has no curve control: renderMap of a Mix of black and white gives, by the mix amount and by a mask
alike, 0 below lower, 1 from upper on and smoothstep of (x - lower) / (upper - lower) between (lower 0.3, upper 0.7:
0.04295 at 0.35, 0.15624 at 0.4); with lower at or above upper it is a step at lower.

The Corona classes of corona_physical, corona_legacy, corona_maps, corona_layered, corona_light, corona_more,
corona_mix_ops, corona_mix_blends and corona_classes (3ds Max 2020 + Corona 12, DLL `coronamaxutils2020.dlt`; block 0 each). CoronaPhysicalMtl's class-directory name starts with a
carriage return (`"\rCoronaPhysicalMtl"`); MAXScript's `CoronaMtl` is CoronaLegacyMtl. Corona names its obsolete
parameters `removedParam`: they are not saved. A Corona map amount is a fraction (CoronaPhysicalMtl's base and
roughness amounts and CoronaLayeredMtl's amounts are percent in MAXScript: 75.0 there is 0.75 here). One older scene
(Corona's 2015-era DLL `coronamaxutils2015.dlt`) has the same ClassIDs and the same parameter ids for
CoronaLegacyMtl, CoronaBitmap and CoronaNormal.

| Class (ClassID) | Parameters |
|---|---|
| CoronaPhysicalMtl `(0x6912AB89, 0x87151720)` | 101 baseColor, 102 baseLevel, 103 / 104 / 105 baseTexmap (on, amount), 111 metalnessMode (1 metal), 121 opacityColor, 122 opacityLevel, 123 / 124 / 125 opacity map, 131 baseRoughness, 132 / 133 / 134 its map, 171 baseIor, 191 refractionAmount, 192 / 193 / 194 its map, 203 useThinMode, 211 clearcoatAmount, 221 clearcoatIor, 231 clearcoatRoughness, 331 selfIllumColor, 332 selfIllumLevel, 333 / 334 / 335 its map, 351 / 352 / 353 baseBumpTexmap, 381 thinAbsorptionColor, 391 clearcoatAbsorptionColor, 411 / 412 metalnessTexmap (on; no amount), 421 roughnessMode (0 roughness, 1 glossiness), 461 iorMode (0 IOR, 1 171 and 221 hold a specular level, F0 = 0.08 x level); 161 edgeColor (default 0.75 grey), 241 sheenAmount, 245 sheenColor, 251 sheenRoughness (each with its map, switch and amount at + 1, + 2, + 3), 261 volumetricAbsorptionColor, 271 volumetricScatteringColor, 281 attenuationDistance (world units; 0 off), 291 sssAmount, 301 sssRadius (world units), 311 sssScatterColor (maps at + 1 .. + 3), 371 translucencyFraction, 375 translucencyColor, 451 useComplexIor, 452-454 complexIorN R, G, B, 455-457 complexIorK R, G, B |
| CoronaLegacyMtl `(0x70BE6506, 0x448931DD)` | colors 101 diffuse, 102 reflect, 103 refract, 105 opacity, 107 selfIllum; levels 121, 122, 123, 127, 128; maps 141 diffuse, 142 reflect, 143 reflectGlossiness, 144 refract, 146 opacity, 147 bump, 158 selfIllum, each switched on by its id + 20, amounts 290, 291, 292, 293, 295, 296, 303; 180 reflectGlossiness, 182 fresnelIor, 183 ior, 210 thin, 402 pbrMode; 106 colorTranslucency, 126 levelTranslucency (map 148, switch 168, amount 297), 188 absorptionDistance (world units), 190 absorptionColor, 410 levelSss, 411 sssRadius (world units), 412 sssScatterColor, 414 / 417 / 421 SSS amount map |
| CoronaLayeredMtl `(0x65486584, 0x8425554E)` | 1000 baseMtl, 1001 layers (table of 10), 1002 amounts, 1003 mixmaps (masks), 1004 layersOn, 1005 masksOn, 1006 maskAmounts (percent in MAXScript); getSubMtl answers the base, then the layers |
| CoronaSkinMtl `(0xBEC41C73, 0x44CFDE95)` | 101 skinColor, 102 skinLevel, 103 sssAmount, 104 sssRadiusScale, 105 / 106 / 107 sss1 color, radius (world units), weight, 108-110 sss2, 111-113 sss3, 114 reflection1Color, 115 reflection1Level, 116 reflection1Glossiness, 117 reflection1Ior, 118-121 the second reflection, 122 opacityColor, 123 opacityLevel; maps 124-144 (skin color 124 ... bump 144), each switched on by its id + 21, amounts at its id + 42 |
| CoronaHairMtl `(0x22C05DD6, 0xCA41F546)` | 101 colorTint, 102 colorDiffuse (black), 103 colorOpacity, 104 / 105 / 106 their levels, 107 ior, 108 glossiness, 109 softness, 110 colorlessGlossiness, 111 highlightShift; maps 112-120 (tint, diffuse, opacity, ior, glossiness, softness, colorless glossiness, highlight shift, bump), each switched on by its id + 9, amounts at its id + 18 (fractions; MAXScript shows percent but for bump); 141 melanin, 142 pheomelanin, 143 randomizeMelanin, maps 144 / 145 (switches 146 / 147, amounts 148 / 149); 150 colorlessSpecular, 151 coloredSpecular, 152 transmission (maps 153-155, switches 156-158, amounts 159-161); 162 glintStrength (163 / 164 / 165); 166 giSimplification |
| CoronaVolumeMtl `(0x39874782, 0x378CDE97)` | 101 absorptionDist (world units; 0 off), 102 absorptionColor, 201 emissionDist, 202 emissionColor, 203 scatteringColor, 204 scatteringDirectionality, 205 / 207 scattering map (on), 206 / 208 absorption map (on), 209 singleBounce, 210 / 211 emission map (on), 212 mappingMode, 213 stepSize, 214 allowMixing, 215 alphaMode |
| CoronaPhysicalMtl and CoronaLegacyMtl media (maxdrop-em3.163) | CoronaPhysicalMtl: 262 / 263 volumetricAbsorptionTexmap (on), 264 its amount, 272 / 273 volumetricScatteringTexmap (on), 274 its amount, 282 scatterDirectionality, 283 scatterSingleBounce. CoronaLegacyMtl: 215 scatterColor, 216 scatterDirectionality, 305 / 306 / 307 absorption map (on, amount), 308 / 309 / 310 scatter map (on, amount), 315 singleBounceOnly, 427 mediaMode (1 volumetric, the default) |
| CoronaShadowCatcherMtl `(0x398ACEAD, 0xACDC3625)` | 301 backplateColor, 302 / 360 backplateTexmap (on), 303 alphaMode, 304 shadowAmount, 306 reflectLevel, 307 colorReflect, 308 reflectIor, 309 reflectGlossiness, 310 projectionMode, 311 preserveAspectRatio, 312 useEnviroOffscreen, 313 offscreenColor, 350 / 361 offscreen map, 351 / 362 Fresnel IOR map, 352 / 363 glossiness map, 353 / 364 bump (355 bumpAmount), 354 / 365 reflection color map, 356 projectReflectionMaps, 357 legacyReflect, 358 legacyEnable |
| CoronaScannedMtl `(0x766665AA, 0x448ADEBB)` | 0 filename (the `.ctf` file), 1 twoSided, 7 tilingFactor, 10-19 filter and paint colors, 20 gamma, 21 saturation, 40-48 clear coat, 64 alphaMode; its uvgen a nameless part at slot 1 |
| CoronaSlicerMtl `(0x90ACB313, 0x394847CD)` | 500 capMaterial, 501 capMtlOn, 502 createCaps, 503 excludeList (node table), 504 excludeListIncludeMode |
| CoronaRaySwitchMtl `(0x6816116A, 0xABE651DE)` | 1600 giMtl, 1601 reflectMtl, 1602 refractMtl, 1603 directMtl, 1610-1613 their switches; Corona 12 renders nothing to the camera (alpha 0) for a directMtl empty or switched off, whatever giMtl holds (maxdrop-6n0.6.4) |
| CoronaSelectMtl `(0xC74E9F94, 0xC319F213)` | 311 mtlCount, 312 materials (table), 313 selected (zero-based: its default is 0) |
| CoronaLightMtl `(0x53B7717A, 0x500D5093)` | 110 intensity, 111 texmap, 112 texmapOn, 113 color, 150 opacityTexmap, 151 opacityTexmapOn, 168 twosidedEmission |
| CoronaBitmap `(0xABBA5784, 0x65484244)` | 101 filename (asset), 103 uvwChannel, 105 uvwScale, 106 uvwOffset (point3), 107 filteringBlur, 108 / 109 tilingU / V (0 none, 1 repeat, 2 mirror), 114 realWorldScale, 117 monoChannelOutput, 118 rgbChannelOutput (1 alpha as gray), 119 clippingOn, 120 clippingMode (0 crop, 1 place), 121-124 clipping u, v, width, height, 125 gamma (-1 automatic), 129 wAngle (radians), 130 uAngle (the U offset times 2 pi, kept in step by Corona); its Output part at slot 1 |
| CoronaColor `(0x68426DCA, 0x372362D4)` | 50 method (0 color, 1 HDR color, 2 temperature, 3 hex), 51 temperature (K), 52 color, 56 alpha, 57 multiplier, 58 colorHdr, 59 hexColor |
| CoronaMix `(0x6847286F, 0x3FFFAAB4)` | 200 mixOperation (0 add, 1 subtract, 2 multiply, 3 divide, 4 minimum, 5 maximum, 6 mix, 7 gamma, 8 difference, 9 screen, 10 overlay, 11 color dodge, 12 color burn, 13 linear burn, 14 linear light, 15 soft light, 16 hard light, 17 vivid light, 18 pin light, 19 hard mix, 20 exclusion: Corona's Mix Operation list), 201 mixAmount, 202 / 203 multiplierTop / Bottom, 204 / 205 offsetTop / Bottom, 206 / 207 texmapTop / Bottom, 208 / 209 colorTop / Bottom, 210 texmapMix, 211 / 212 / 213 switches of the mix, top and bottom maps, 214 mixInSRgb |

What the Corona maps do was measured with `renderMap` in 3ds Max 2020: a CoronaBitmap's UVW scale, offset and W
angle place the image exactly as a Bitmap's tiling, offset and W angle; CoronaMix gives mix(bottom, operation(bottom,
top), amount), the mix map replacing the amount when it is on (the operation numbers above come from that), the mix
always linear. Subtract is bottom - top floored at 0, divide bottom / top, difference |bottom - top|. With mixInSRgb
on (the default) the operation runs on each layer raised to 1 / 2.2 and its result is raised to 2.2 (top 50, bottom
40 of 255: add 206.1, off 90.0; the sRGB curve would give 207.2); multiply, divide, min and max come out the same
either way; results are not clamped (an add's 2.14 shows through a 0.25 mask). Each layer is its map or color times
its multiplier, plus its offset times -0.1 (offset 1.0 lowers it by 25.5 of 255, -1.0 raises it; the multiplier
first). Operations 7 and 9-20 (maxdrop-em3.117, CoronaColor HDR layers read through (v + 4) x 0.05, so -4 to 16
show), a the bottom and b the top per channel: gamma a^(1 / b) (in sRGB mode b^(1 / 2.2), the 2.2s of a cancel; no
number at b = 0), screen 1 - (1 - a)(1 - b), overlay 2ab for a below 0.5 else 1 - 2(1 - a)(1 - b), hard light the
overlay with a and b swapped, color dodge a / (1 - b) at most 1 (1 at b = 1; a top above 1 gives a negative), color
burn 1 - (1 - a) / b at least 0 (0 at b = 0; not clamped above), linear burn a + b - 1 at least 0, linear light
a + 2b - 1, exclusion a + b - 2ab, none of them clamped otherwise; soft light is Photoshop's (not Blender's Pegtop
form), vivid light, pin light and hard mix have no Mix node type. In sRGB mode Corona raises the magnitude of a
result to 2.2 (linear light of black over black gives 0.998, |-1|^2.2) and takes the magnitude of a negative layer
(an add of -0.1 and 0.5 gives 1.186), and renders 1 as about 0.998. The amount lerp is linear in both modes for
these operations too. CoronaColor's temperature is Corona's own linear color, the
brightest channel 1 (`texmaps.CORONA_KELVIN`, 24 points from 1000 K to 40000 K; 3000 K = (255, 121.6, 39.2));
colorSpace (61) changed nothing for a color, a hex value or a temperature.

MaxDrop draws a CoronaMix in sRGB mode with a Vector Math ABSOLUTE before each map layer's Gamma node of 1 / 2.2 (a
constant layer's magnitude folded), and color dodge, color burn and exclusion with Vector Math nodes in the forms
above (maxdrop-em3.161): Blender's Mix types for them clamp to 0..1 (exclusion floored at 0) and its Dodge leaves a
bottom of 0 at 0 under a top of 1. Vector Math's Divide gives 0 for a divisor of 0, so burn is max(0, nz - (1 - a) / b)
and dodge 1 - max(0, nz - a / (1 - b)), nz = ceil(min(|divisor|, 1)), 0 for a divisor of 0. Checked by a Cycles
emission bake against `texmaps.blend_value` (every operation, both modes, layers -0.5 to 3, exactly 0 and 1 too).
The gamma operation over a bottom map draws a ColorCorrect gamma; in sRGB mode with a Vector Math ABSOLUTE before
its Gamma node (`ColorCorrect.magnitude`), as Corona raises a negative bottom map's magnitude too (maxdrop-6n0.6.40,
renderMap: a flat 64 / 128 / 192 CoronaBitmap under a 128 top swatch gives 0.015595, 0.125628, 0.425696, gamma on
and off alike, and the same with multiplierBottom -1; the exponent 0.7310 is the top as stored, (128 / 255)^(1 /
2.2), pinned by the fixture box FixtureCoronaMixGammaGrey). In linear mode a negative bottom gives no number in
Corona (NaN, shown 0); MaxDrop leaves it negative.
A Mix node's color input clamps its own value at 0: a constant layer below 0 goes in through a Combine XYZ node.
So does every Mix node's (maxdrop-6n0.6.26: Mix maps, CoronaMix mix and multiply, RGB Multiply, Composite layers) and
an RGB node standing for a constant (`_Tree.socket`); a Cycles emission bake of a Mix (0.5) and a Multiply of a white
image with a constant side of -0.5 gives 0.25 and -0.5 (was 0.5 and 0, the constant taken as 0). The other users
of that stand-in (Color Correction, an Output or RGB Tint over a constant, a normal map's constant color) now get
the negative value too, where they got 0: not measured against a renderer.

Corona 12 renders (maxdrop-em3.115): `3dsmaxbatch`, CoronaRenderer with tone mapping off (`colorMap_enabled`) and a
pass and a time limit, read with `getPixels ... linear:true` (a CoronaLightMtl patch at 0.5 / 1.0 reads 0.49999 /
1.0, a white diffuse plane under a white background 0.99999):

- CoronaLayeredMtl over a black base, the layer self-illuminated white: amount 0.6 with a constant mask 0.25 at mask
  amount 0.5 gives 0.375, amount x lerp(1, mask, mask amount) (lerp(amount, mask, mask amount) would be 0.425); amount
  0.4, mask 0.75, mask amount 0.5: 0.35; mask amount 0 or masksOn off: the amount. The mask takes the value the same
  map gives as a self-illumination color in both gamma modes (gamma off: a CoronaColor swatch 64 0.251, a Bitmap of a
  128 grey PNG 0.502; gamma on: swatch 128 0.502, the Bitmap 0.2195; a CoronaBitmap of it 0.2195 in both).
- A CoronaLegacyMtl and a CoronaPhysicalMtl opacity color 128 grey, gamma on: alpha 0.502, the swatch as stored.
- CoronaPhysicalMtl iorMode (461): 0, the IOR parameters (171 baseIor, 221 clearcoatIor) are IORs; 1, they hold a
  specular level, F0 = 0.08 x level (0.5 is F0 0.04, IOR 1.5), and the file stores the level (MAXScript's setter
  converts both on a mode change: set the mode before the values); 2 renders as an IOR (not a mode the UI offers).
  No base IOR reflects more than F0 0.25 (IOR 3: an IOR of 4 or 10 and a specular of 4 all give 0.25), and an IOR
  below 1 reflects as its reciprocal (0.5 as 2); MaxDrop takes the base IOR of a material that does not refract so
  (maxdrop-6n0.6.22) and keeps a refracting one's (clamped to 1..100, named outside 1..3: its refraction through such
  an IOR was not measured), the clearcoat IOR as it is. The renderer's `defautIorMode` (Corona's spelling) only picks
  a new material's mode.
- CoronaPhysicalMtl edgeColor (161) on a metal (spheres under a white background, roughness 0, read along a row):
  per channel, a white edge brightens the grazing reflection above Schlick's and a black one darkens it (base 230 /
  153 / 77 at 82 degrees: Schlick 0.947 / 0.785 / 0.625; edge black 0.741 / 0.513 / 0.521, the default 0.75 0.938 /
  0.838 / 0.756, white 0.981 / 0.912 / 0.816). The default is close to Schlick (rms 0.006 / 0.016 / 0.05). No model
  fits every sphere: Blender's F82 tint (best tint 0.98 to 1.32 for the default edge, 0.64 to 0.82 for black, above
  1 for white), Gulbrandsen's edge tint with the edge color as g, a conductor of free n and k (rms up to 0.04): not
  converted, a named issue.
- Translucency: a CoronaPhysicalMtl plane lit from below lets nothing through without thin mode (fraction 0.5 and
  1.0: 0), 0.48 and 0.96 in thin mode; a CoronaLegacyMtl's (levelTranslucency) works without thin: 0.49 and 0.99, a
  diffuse transmission of the fraction. Blender's Principled BSDF has none, and a Translucent BSDF under a Mix Shader
  would scale the specular and coat by the fraction too: not converted, a named issue (CoronaPhysicalMtl: in thin
  mode only).
- CoronaLegacyMtl pbrMode (402) off: a mirror plane (Fresnel IOR 999) under a small emitter seen only in reflections,
  the radial profile of its highlight matched against a PBR-mode sweep (glossiness step 0.025, 0.01 above 0.9). The
  PBR-off glossiness 0, 0.05 ... 1 renders as the PBR-mode roughness 0.618, 0.617, 0.612, 0.600, 0.5745, 0.525,
  0.4555, 0.386, 0.324, 0.272, 0.2295, 0.1945, 0.165, 0.140, 0.1185, 0.099, 0.082, 0.0665, 0.051, 0.035, 0
  (`materials.CORONA_LEGACY_GLOSS`). From 0.35 up the profiles agree (log rms 0.005 to 0.02, 0.038 at 0.85); below
  0.3 no PBR-mode glossiness gives the same lobe (log rms 0.05 at 0.3, 0.24 at 0): the closest one.

Corona 12 media (maxdrop-em3.163; `3dsmaxbatch`, tone mapping off, the gamma off, read with `getPixels ... linear:true`,
the swatch's 0-255 value / 255 rendered as the linear color: MaxDrop decodes a gamma-off swatch from sRGB as every
other color, so the numbers below are in the renderer's space). Boxes 30 x 30 x h world units over a CoronaLightMtl
plane of intensity 1 in a black environment, an orthographic camera looking down through them, and in a white
furnace:

- Absorption (CoronaVolumeMtl, and CoronaPhysicalMtl and CoronaLegacyMtl refracting at IOR 1: the same numbers):
  the transmission is the absorption color at the distance and color^(h / distance) for a grey at every thickness
  (128 grey at distance 10, h 1 / 2.5 / 5 / 7.5 / 10 / 15 / 20 / 30 / 40: 0.93339, 0.84172, 0.70849, 0.59634, 0.50195,
  0.35563, 0.25196, 0.12647, 0.06348; distance 20 at h 20 and 40 as distance 10 at 10 and 20; stepSize 0.1 the
  same). A tinted color couples its channels a little away from its distance (204 / 128 / 51 at distance 10: h 5
  0.899 / 0.714 / 0.455 for 0.894 / 0.709 / 0.447, h 20 0.614 / 0.238 / 0.030 for 0.640 / 0.252 / 0.040; the law
  applied in AP1 or Rec. 2020 primaries does not fit either). MaxDrop uses the per-channel law, exact at the distance.
- Scattering: the scattering color is the albedo of the extinction the absorption makes. Absorption white, or its
  distance 0, and nothing scatters (the box is invisible); absorption 128 grey with scattering white gives 0.997 in
  the furnace. So per channel sigma_t = -ln(absorption color) / distance, sigma_s = scattering color x sigma_t,
  sigma_a the rest; the directionality is a Henyey-Greenstein g. Over the emitter at h 10 (absorption 128 grey,
  distance 10): scattering white 0.683 (0.674 in a second render), 128 grey 0.570, white with directionality 0.6 /
  -0.6 0.863 / 0.6075, single bounce on 0.598; in the furnace: white 0.997, 128 grey 0.6775, 128 grey at 0.6 0.691.
- Emission: its color over its distance per unit length, absorbed as any light (255 / 128 / 64 at distance 10, no
  absorption: h 5 0.5 / 0.251 / 0.125, h 10 1.0 / 0.502 / 0.251; distance 20 at h 10 half; with absorption 128 grey
  at distance 10: h 10 0.7226 / 0.3627 / 0.1814, e / sigma (1 - e^(-sigma h))). Distance 0: none.
- CoronaVolumeMtl renders no surface (1.0 over the emitter and in the furnace with everything off).
- No medium in thin mode (CoronaPhysicalMtl useThinMode, CoronaLegacyMtl thin: 1.0 through the slab), and a
  CoronaLegacyMtl in mediaMode 0 renders the slab black. A CoronaPhysicalMtl at refraction 0.5 lets about 0.25 x the
  absorbed color through (0.2205 / 0.1288 / 0.0497): the medium whatever the amount.

Cycles (Blender 5.2, 256 samples, Volume Bounces and Max Bounces 64) with the same slabs, the coefficients per meter on
a Volume Scatter (density the largest sigma_s, color each channel's share), a Volume Absorption (density the largest
sigma_a, color 1 - the share) and an Emission (strength 1 / distance) on the Volume socket: absorption and emission
exact; scattering white 0.681, 128 grey 0.566, directionality 0.6 / -0.6 0.868 / 0.603; furnace 0.992, 0.677, 0.692.
Blender's default Volume Bounces of 0 scatters once (as Corona's single bounce): MaxDrop does not change it. An unlinked Surface with nothing
on the Volume socket renders black there: a volume-only material keeps its Principled BSDF at Alpha 0.
Since maxdrop-6n0.6.29 that holds only without a medium. With one on Volume, a volume-only material (alpha 0, no
alpha map, no layers) leaves Surface unlinked: an Alpha-0 Principled BSDF spends two of Cycles' 8 transparent bounces
per box (Blender 4.2.23 and 5.2, 20 m boxes over an emitter of 1: one box 1.0, six or twelve stacked 0.0 in Cycles,
EEVEE 1.0), the unlinked Surface 1.0 at any count, and a camera inside an absorbing box (0.05 / m, 19.5 m) reads 0.379
both ways in Cycles and EEVEE (e^-0.975 = 0.377). Its viewport color is 0.1 opaque, so Solid view shows the scene in
it. The em3.163 scattering slab (128 grey at 10, scattering white, h 10, the emitter the slab's footprint) renders
0.601 at Volume Bounces 0 (Corona single bounce 0.598) and 0.678 at 64 (Corona 0.683): the import names a medium that
scatters in the report and leaves the setting as it is (owner, 2026-11-24), but one with single bounce on, which
Blender's default renders as Corona does.

Corona 12 CoronaHairMtl on a mesh (maxdrop-em3.164; `3dsmaxbatch`, tone mapping off, the gamma off, read with
`getPixels ... linear:true` as a mean of 31 x 31 pixels, the swatch's 0-255 value / 255 rendered as the linear color as
for the media above). Planes 40 x 40 in a white furnace (white environment, no light: 1.0 everywhere), seen from the
top by an orthographic camera:

- Every channel reads R + P0 x exp(-u): R = 0.070, the colorless specular (colorlessSpecular black removes it:
  melanin 0 then 0.929, melanin 1 0.011 / 0 / 0), P0 = 0.929. A plane turned 90 degrees about its normal reads the
  same, one tilted 60 degrees 1% darker. The default (melanin 0.5) reads 0.396 / 0.232 / 0.099; melanin 0, 0.1 ...
  1 at pheomelanin 0: 0.995, 0.961 / 0.937 / 0.881, 0.858 / 0.775 / 0.613, 0.710 / 0.567 / 0.348, 0.548 / 0.375 /
  0.178, 0.396 / 0.232 / 0.099, 0.272 / 0.144 / 0.074, 0.184 / 0.098 / 0.069, 0.128 / 0.079 / 0.069, 0.097 / 0.072
  / 0.070, 0.081 / 0.070 / 0.070; at pheomelanin 1: 0.995, 0.983 / 0.964 / 0.908, 0.934 / 0.862 / 0.684, 0.857 /
  0.715 / 0.436, 0.761 / 0.551 / 0.244, 0.651 / 0.398 / 0.133, 0.535 / 0.274 / 0.083, 0.424 / 0.184 / 0.067, 0.326
  / 0.127 / 0.065, 0.245 / 0.095 / 0.066, 0.183 / 0.079 / 0.068.
- u has the channel shape of the absorption Blender's Principled Hair BSDF uses (Cycles' eumelanin 0.506 / 0.841 /
  1.653, ratios 1 : 1.66 : 3.27, read 1 : 1.67 : 3.25; pheomelanin 0.343 / 0.733 / 1.924, 1 : 2.14 : 5.61, read
  1 : 2.2 : 5.7), the same at every melanin. Pheomelanin is the share of the melanin that is red, as Blender's
  Melanin Redness (melanin 0 with pheomelanin 0.6 reads as melanin 0; u mixes linearly in it), but Corona's absorbs
  0.685 x Cycles' coefficients. Fit: u = (7.68 m^2 + 1.2 m^3) x ((1 - p) eumelanin + 0.685 p pheomelanin), largest
  error 0.009 over both sweeps; nine held-out mixes (pheomelanin 0.2 ... 0.8, melanin 0.3 ... 0.8) within 0.006
  (`materials.hair_color`). Not the color Principled Hair's parametrization gives the same melanin (0.031 / 0.011 /
  0.002 at the default).
- Tint (colorTint x levelTint): a grey t adds 0.054 ln(t)^2 to u (0.25: 0.837, 0.5: 0.905 of 0.929; black: the
  floor only). A CoronaColor in the tint slot renders as the same swatch would (melanin 0, 204 / 128 / 51: 0.995 /
  0.981 / 0.887, not 0.8 / 0.5 / 0.2), added to the melanin's u at any melanin.
- Diffuse (colorDiffuse x levelDiffuse): a grey d gives d + (1 - d) x the hair, exactly (0.5 at melanin 0.5: 0.699 /
  0.617 / 0.551; 0.25 by levelDiffuse 0.5: 0.551 / 0.427 / 0.328; 0.25 at melanin 0.8: 0.350 / 0.313 / 0.305). A
  colored d weighs the hair less than 1 - its mean: 204 / 128 / 51 by 0.32 at melanin 0.5 (0.926 / 0.576 / 0.232)
  and 0.39 at 0.8, pure red by 0.39, pure blue by 0.09, 51 / 128 / 204 by about 0.25; MaxDrop uses 1 - its largest
  channel.
- Transmission color: multiplies the hair's TT part (0.5 grey: melanin 0.5 0.237 / 0.152 / 0.085, melanin 0 0.567;
  255 / 128 / 64 at melanin 0: 0.996 / 0.568 / 0.350; black: 0.078 / 0.072 / 0.070 at melanin 0.5). Colored specular
  black: 0.945 at melanin 0 (TRT is small on a plane). IOR 1.3 / 2.0: 0.398 / 0.223 / 0.074 and 0.412 / 0.267 /
  0.156 (the floor and the transmitted part both move). Glossiness 0.2 / 0.9, softness 0 / 0.5, colorless
  glossiness 0.5 / 1, highlight shift 0 / 5 and GI simplification 0: within 0.01 of the default (no change of
  the furnace albedo; a lit highlight was not compared). Glint strength 1: 0.433 / 0.278 / 0.149 (0: 0.396 / 0.234 / 0.103); randomizeMelanin 0.5: 0.447 /
  0.368 / 0.293.
- Hair and Fur strands (maxdrop-6n0.6.30): Corona 12 does not shade them with a CoronaHairMtl. Strands grown on a
  plane whose own faces are black (a window mean of 0.027 without the modifier), tip and root colors white, seen
  from the side in the furnace, read 0.494 with or without a Hair and Fur render effect and in each of its
  `hairMode` values (0, 1, 2). They take Hair and Fur's own tip and root colors (red: 0.685 / 0.098 / 0.026, grey
  128: 0.424), not the growth object's material: a Multi/Sub whose sub-material at the strands' MaterialGeomMtlID
  is a red CoronaLightMtl, a CoronaHairMtl at melanin 0 or one at melanin 1 reads 0.494 alike. MAXScript refuses
  `MR_Shader` set to a CoronaColor or a CoronaHairMtl (an exception; an access violation in em3.164). A Corona
  forum answer of 2016 points to instanced geometry with a material of its own instead (a mesh: the rule above).
  An earlier end-on view followed the melanin only because its window held the growth plane, which carried the
  material.

Cycles (Blender 5.2, 256 samples) with the same planes: a Principled BSDF at IOR 1.55, roughness 0.5 reads 0.043 +
0.957 x its base color in that furnace. MaxDrop's base (0.070 + 0.929 x hair - 0.043) / 0.957 reads Corona's numbers
within 0.009 over the sweeps, the tints, a grey diffuse and a 0.5 grey transmission at melanin 0.5; a colored diffuse
(204 / 128 / 51: 0.879 / 0.561 / 0.246 for 0.926 / 0.576 / 0.232) and a transmission color at melanin 0 (0.5 grey:
0.535 for 0.567; 255 / 128 / 64: 0.535 / 0.302 for 0.568 / 0.350 in green and blue: the rule scales the TRT part too)
within 0.05. Other IORs were not checked in the furnace (Corona's floor and the Principled's both rise with the IOR).

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

### The mix rules of VRayBlendMtl, VRay2SidedMtl and Blend, measured

maxdrop-o53.2.4, V-Ray 5.2 in `3dsmaxbatch` (probe scenes, not committed). A 20 m Plane carries the material under
test; standard Omnis of multiplier 1 without decay sit 1 m in front of it (+Z, the side the camera sees) and 1 m
behind it, each switched on as the case says; a Freecamera at 0.9 m looks down. Color mapping linear, gamma 1, clamp
output off, no GI, no default lights, a black background; an HDR bitmap read with `getPixels ... linear:true`, the
mean of the 8 x 8 center pixels. Every sub-material is a VRayMtl of reflection 0. A white one lit from the front
reads E = 0.704897 (the Omni's floor, maxdrop-o53.2.9); the controls are a VRayLightMtl white at 1.0 and one at grey
128 at 0.502. The table gives shares of E as R / G / B (one number: a grey). Each case was rendered twice, with the
scene's gamma off (as the fixtures are saved) and on (input 2.2). Both modes give the same internal value on every
row except those with an image, a self-authored 8-bit 128 grey PNG as a Bitmap with automatic gamma: 0.502 with the
gamma off and 0.2195 with it on, as for a mask ([Scene gamma](#scene-gamma)). GI on (the renderer's defaults)
changes nothing on this one plane (translucency 128 from the front and from behind, a coat at 128).

| Case | Internal value (shares of E) |
|---|---|
| VRayBlendMtl, red base, green coat, blend grey 64 / 128 / 191 | (0.749, 0.251, 0) / (0.498, 0.502, 0) / (0.251, 0.749, 0) |
| blend (255, 128, 0): black base under a white coat; white base under a black coat; red under green | (1, 0.502, 0); (0, 0.498, 1); (0, 0.502, 0) |
| black base, white coat, blend 51 (0.2) with a VRayColor 230 (0.902) blend map, multiplier 0 / 60 / 100 / 150 % | 0.2 / 0.6212 / 0.902 / 1.0 |
| the same, blend 0 / 255 with that map at 60 %; 255 with a black map at 60 % | 0.5412 / 0.9412; 0.4 |
| blend 230 with a black map at 150 % (lerp -0.451): black base under white; white base under black | 0; 1 |
| blend 51 with the PNG at 60 %; blend 0 with the PNG at 100 % | gamma off 0.3812, on 0.2117; off 0.502, on 0.2195 |
| additive, blend 128: red under green; grey 128 under grey 128 (normal mode: 0.502); white under white, at 255 | (1, 0.502, 0); 0.754; 1.502, 2.0 |
| two coats over a red base: green at 128, then blue at 64 | (0.373, 0.376, 0.251) |
| vray_wrappers' FixtureBlend stack (base 20 / 20 / 210; coats 200 / 200 / 20 at 40 / 50 / 60 and 20 / 200 / 200 at 70 / 80 / 90), additive; normal | (0.2230, 0.4783, 1.1188); (0.1588, 0.3949, 0.6963) |
| a coat with coatMtl_enable off | the base |
| VRay2SidedMtl, white front, no back material, translucency grey t = 0 / 0.251 / 0.502 / 0.749 / 1: front light only; back light only; both | 1 - t; t; 1 |
| green front, red back material (backMtlOn), t = 0.251 / 0.502 / 0.749: front light; back light | (0, 1 - t, 0); (t, 0, 0) |
| white front, translucency (64, 96, 128) (vray_wrappers' FixtureTwoSided): front light; back light | (0.749, 0.624, 0.498); (0.251, 0.376, 0.502) |
| mult_by_front_diffuse on (default off), back light, t 128: front (128, 255, 64) over a white back; the same front without a back material; green over red | (0.252, 0.502, 0.126); (0.127, 0.502, 0.0316); 0 |
| force1SidedSubMtls off (default on; FixtureTwoSided has it off), t 128, white VRayMtl double-sided (its default): back light; front light | 0; 0.498 |
| the same with the VRayMtl's Double-sided option off: back light; front light | 0.502; 0.498 |
| translucency white with the PNG as its map, multiplier 60 / 0 %; translucency black with the PNG at 100 %; texmap_translucency_on off, white with the PNG at 100 %; all back light | off 0.7012, on 0.5317 / 1; off 0.502, on 0.2195; off 0.502, on 0.2195 |
| Blend (material1 red, material2 green), mix amount 0 / 30 / 100 % | (1, 0, 0) / (0.7, 0.3, 0) / (0, 1, 0) |
| amount 30 % with a mask: VRayColor 64 / 255 / 0; the PNG; a VRayColor 64 mask with maskEnabled off | green 0.251 / 1 / 0; off 0.502, on 0.2195; green 0.3 |
| Use Curve, lower 0.3, upper 0.7: amount 20 / 35 / 40 / 50 / 65 / 80 %; a mask of 0.349 / 0.4 / 0.502 / 0.651 at amount 0 (without the curve: as stored) | green 0.2 / 0.35 / 0.4 / 0.5 / 0.65 / 0.8; green 0.0414 / 0.1563 / 0.5074 / 0.9586 |
| Use Curve, lower 0.7, upper 0.3: a mask of 0.502 / 0.651 / 0.749 | green 0 / 0 / 1 |
| amount 30 % with map1Enabled off; with map2Enabled off | (0, 1, 0); (1, 0, 0) |

The rules, per channel, each in V-Ray's internal values. A scratch script recomputes all 104 rows of each gamma mode
from them within 0.01 %.

- **VRayBlendMtl.** Start from the base material's shading. Then, for each coat k in table order (coat 1 first, the
  last one on top) that is set and enabled, w_k = clamp(lerp(blend_k, map_k, multiplier_k / 100), 0, 1), or blend_k
  when it has no map. The multiplier is the percent as stored, the blend color is each of its channels as stored
  (not their mean), and the map is its value. Normal mode: out = out (1 - w_k) + coat_k w_k. Additive: out = out +
  coat_k w_k, not clamped (a white coat over a white base at 255: 2.0).
- **VRay2SidedMtl,** seen from the front: (1 - t) x the front material's shading of the light on its own side + t x
  the back's shading of the light on the other side. The back is backMtl when backMtlOn is set, else frontMtl; with
  mult_by_front_diffuse on it is multiplied by the front's diffuse. Here t = lerp(translucency, map,
  multiplier / 100), the translucency's channels as stored. V-Ray 5.2 renders the map whatever
  texmap_translucency_on says. With force1SidedSubMtls off, a double-sided sub-material lets no light through from
  the other side, so with VRayMtl's default the back light is lost while the front keeps its 1 - t. From behind and
  with GI from other objects: not measured.
- **Blend** `(0x250, 0)`, 3ds Max's Blend material rendered by V-Ray: w = the mask's value when a mask is set and
  maskEnabled is on, else the mix amount (a fraction). Use Curve runs the mask through smoothstep of (w - lower) /
  (upper - lower), a step at lower when lower is at or above upper (the Mix map's curve, above); it leaves the mix
  amount alone. out = material1 (1 - w) + material2 w, so a white mask is material2. With map1Enabled or
  map2Enabled off, the other material is rendered whole.

**The weight and the scene's gamma.** V-Ray takes a blend color, a translucency and a swatch-valued mask as stored,
per channel, in both gamma modes, and an image by its own decode (0.2195 with the gamma on, 0.502 off). With the
gamma on, a swatch is linear (`colors.GAMMA_ON`), so the stored value is also the scene's rule. With the gamma off
the scene is display-referred: Blender shows srgb_to_linear of the internal value, here of the material's mix, not
of its sides. Red under green at a grey 128 blend shows (0.212, 0.216, 0). A mix of the decoded sides (1, 0, 0)
and (0, 1, 0) by one weight w gives (1 - w, w, 0), so no weight shows both channels: the stored 0.502 gives a red
of 0.498, and the scene's rule on it (0.216) gives 0.784. Only with one side black is one weight exact:
srgb_to_linear(w) on a white side, and on another color c within 0.0052 (srgb_to_linear(w c) against
srgb_to_linear(w) srgb_to_linear(c) over 0..1, computed, as for an RGB Multiply above). The
grey-64 and grey-191 blends show (0.521, 0.0513, 0) and (0.0513, 0.521, 0). So the assumption that a coat's
weight is the scene's rule on the mean of its blend color holds for a grey blend with the gamma on, and with the
gamma off only for a coat over a black base (or a black coat). A colored blend weighs each channel by its own
value. vray_wrappers' FixtureTwoSided translucency (64, 96, 128) has a stored mean of 0.376 and a mean of 0.117 under
the scene's rule. V-Ray weighs its channels 0.251 / 0.376 / 0.502, and with the gamma off its back light shows
(0.0513, 0.117, 0.216) and its front light (0.521, 0.347, 0.212). Its force1SidedSubMtls is off and its VRayMtl
sub-materials are double-sided, so V-Ray lets none of the back light through there.

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

## Strings of older files

`maxdrop/reader/strings.py`; `tests/unit/test_strings.py`.

- saved_as_2017, saved_as_2018 and saved_as_2019 (3ds Max 2020, Save As 2017, 2018, 2019) hold their node,
  material and layer names with U+00F6, U+00E4 and U+4E2D as every 3ds Max 2020 file does: `0x0962` and `0x4001`
  UTF-16LE, the layer's `0x1010` UTF-8. Their summary says `3ds Max Version: 22.00` and `Saved As Version` 19.00,
  20.00, 21.00; both summary streams record code page 65001.
- Corpus scene A (3ds Max 2015 saving in the 2012 format) has UTF-16 names too (every `0x0962`, `0x2042` and DLL
  name has a zero in each odd byte), and the root container `0x2014`: the saved-as version and the root id do not
  tell an 8-bit file, the version that wrote it does.
- The reader decides by the writer's `3ds Max Version`: 15 (3ds Max 2013, the first Unicode version) or more is
  UTF-16, whatever the names look like. Below 15, or without a version, the DLL file names (`0x2037`) and class
  names (`0x2042`) vote: an 8-bit name ends with its only NUL, an ASCII name in UTF-16 has a 0 second byte and an
  even size, any other name (not ASCII, one letter) abstains. Below 15 the file is 8-bit unless the names say
  UTF-16; without a version, UTF-16 unless they say 8-bit.
- An 8-bit string is cut at its first NUL and decoded with the code page the summary records (property 1 of
  DocumentSummaryInformation, else SummaryInformation) when it is a Windows ANSI code page, else as UTF-8 when it
  is valid UTF-8, else as cp1252; the import option Text Encoding overrides it. The layer name and the ParamBlock2
  string values follow the same rule in an 8-bit file.

## Open

Not shown by any fixture yet, so not stated above:

- Of VRayLight ([VRayLight](#vraylight)): the dome's parameters, size2, the texmap's use, the light units of a
  scene unit other than millimeters (the rules
  scale lengths by the unit; the fixture is in millimeters), an animated parameter (its default is taken); a sphere
  scaled with Y or Z larger than X (taken as the largest scale), and whether a scaled sphere's radius in Blender
  follows the object's scale as V-Ray's does.

- Asset metadata seen only in the corpus (`assets.py` relies on it): scene A (saved as 3ds Max 2012) has
  `FileAssetMetaData2` instead, its records without the third string (155 records: `Bitmap` and `Photometric`);
  in scene B's `FileAssetMetaData3` the third string is the absolute path 3ds Max found the file at when saving
  (167 of 168 records, the same file name as the stored path, which is a bare file name there; empty for the one
  stored as an absolute path).
- Parameter blocks seen only elsewhere (`pblock.py` relies on them):
  - entries in `0x000E` instead of `0x100E`, same layout, in corpus scene A (saved as 3ds Max 2012); scenes A and
    B walk without an issue: 726 and 560 materials and maps, 33,543 and 41,274 stored parameters;
  - not known: the fourth `u32` of an entry, the third `u16` of a `0x0013` record,
    `0x0005` and `0x0004` of the old ParamBlock, and the value layout of the types no file has shown (matrix3,
    and the others the reader keeps as raw bytes).
- Other root container ids: `0x2014` (the 2012 format, corpus scene A) occurs in the corpus, and the 64-bit
  chunk header (size 0, then a `u64`) in large ones.
- Files of 3ds Max 2012 and older: no such file has been read. Taken from the 3ds Max SDK of those versions and
  checked only on synthetic chunks: the 8-bit strings and their NUL, the ParamBlock2 string as a byte count then
  8-bit text, the code page the summary records (the machine's ANSI code page is assumed), the layer name in the
  same code page. Their FileAssetMetaData strings are still read as UTF-16, and an older `ClassDirectory` stream
  as `ClassDirectory3`.
- Of shapes ([Shapes](#shapes)): a rectangular section on a
  curve that is not flat in XY (Blender's twist and 3ds Max's may differ: an issue), the section angle's sign on
  other directions than +X, a rectangular section of width or length 0 (not drawn, an issue), the angle of a round
  section (not drawn); the `f32` and the last `u32` of a knot, `0x2904`, `0x1070` of the
  BezierShape and `0x2150` (on some Editable Splines and Lines); the other shape classes (Star, Text, Helix, Donut,
  Section, NURBS curves...), which stay placeholders.
- Of a modifier stack ([Modifiers](#modifiers)): `0x204B`, `0x2501`, `0x2502`, `0x2512` and `0x2513`; how the
  gizmo controller combines with the context matrix; a modifier without `0x39BF` (4 of 74 modifier objects in scene
  A, 3 of 46 in scene B: read with every switch on and the class name).
- The meaning of bit `0x800` and the other flag bits in `0x0960`.
- Of a node's `0x0A28`: the display mask (its first `u32`) and the bits of the render mask other than `0x8000`,
  `0x400` and `0x200`.
- Layers: the layer name's encoding in a version other than 3ds Max 2020 (the reader replaces bytes that are not
  UTF-8).
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
- Controllers seen only in the corpus (scenes A and B, compared with their oracle; `reader/controllers/` relies on
  them):
  - a Bezier Float with its `0x2501` directly in the object, not in `0x7127` (under ScaleXYZ, list weights);
  - list weights held by controllers (Bezier Float) in the list block's reference slots, with weights 1 and 0;
  - every keyed controller of a transform has a `0x2500` interval holding time 0 (scene A 259, scene B 326, and 450
    forever with one key). Three Bezier Scales, interval `(0, 0)`, have a key at time 0 whose value differs from the
    saved value (by under 2 %): the oracle agrees with the saved value, which the interval rule picks. One Bezier
    Float with the empty interval `(-2^31, -2^31)` and its one key at 16000 is a Noise modifier's, not a
    transform's: what 3ds Max makes of it is not known;
  - Look At `(0x2006, 0)` on a camera and a light of each scene: evaluated as [Look At](#look-at) says, their
    world matrices equal the oracle's (all 662 nodes without modifiers of scene A, all 2,042 of scene B).
- Controllers no file shows yet (`reader/controllers/` assumes them): a controller without `0x2500` (none in the corpus
  or the fixtures; its value chunk is used, with an issue when several keys animate it); a free Bezier handle of a
  negative length (3ds Max turns a third into frames when a handle is freed: linear, an issue); a frame rate other
  than 30 fps in a fixture (a probe at 25 fps shows it) and one that does not divide 4800 (seen: 24, 25, 30 and 60;
  ticks per frame taken as 4800 // fps); scale keys whose axis quaternions point apart (no probe
  stored such a pair: linear, an issue); between two TCB Rotation keys a turn within 10 degrees short of a
  revolution, a turn about no axis or a negative stored angle (none stored: squad up to the gap, past it an issue),
  between two Linear Rotation keys a pair within about 5 degrees of a
  revolution (1 + dot from 5e-7 to 1e-3), between two Smooth Rotation keys opposite quaternions or controls (3ds Max
  stored none: linear, an issue each); the bare Euler orders 1 to 5 and 100 (read as the SDK numbers
  them: 1 = XZY ... 5 = ZYX, 100 = XYZ); the Euler orders 106 to 108 (an issue).
- Controllers the probes of maxdrop-6n0.6.12 left open (3ds Max 2020): a Scale List weight other than 100 % after an
  entry along a turned axis, and a Scale List average of turned scales (no rule tried fits: an issue each); Loop
  that reads a time outside the keys over a range moved off them other than wider on both sides (Loop on one side
  only, a range shifted past a key), and the types switched off beside a moved range (not probed: as Cycle and
  Constant, an issue); MAXScript's #identity type (0: the controller reads zero; an issue); an animated or
  unreadable Average switch (read as off, no issue) and an animated weight of a list with Average on (not probed:
  read as the stored ones).
  A file saved by a script that never evaluated a Bezier controller after its keys changed keeps stale smooth and
  auto tangents (a smooth key read as flat, 0.31 off at frame 0 in a dry run); 3ds Max computes them on evaluation,
  so a file saved from the user interface holds current ones, and the fixtures evaluate every node before saving.
- The Falloff mix curve in other formats ([The Falloff mix curve](#the-falloff-mix-curve); maxdrop-em3.130), seen
  only in files not committed: falloff_curve's script saved by 3ds Max 2020 as 2017, 2018 and 2019 (formats 19000,
  20000, 21000) stores every curve as its 3ds Max 2020 file does (`0x2035`, `0x204B` (not decoded), `0x1000`, one
  `0x1030` per point holding a 28-byte `0x1000`, `0x1020`, `0x1040`), the same points, handles and flags; loaded
  again in 3ds Max, `ICurve.GetValue` gives the same values in all four. Corpus scene A (3ds Max 2015 saving in the
  2012 format, 60 Falloffs, 34 with an edited curve of up to 5 points) and scene B (3ds Max 2020 saving as 2018, 23
  Falloffs) read with the same layout, every curve; scene A saved again by 3ds Max 2020 gives the same points.
  Point flags seen there besides the fixture's: `0x1`, `0x11`, `0x103`, `0x110`, `0x113` (MaxDrop does not use the
  flags). Not known: the layout written by a 3ds Max newer than 2020.
