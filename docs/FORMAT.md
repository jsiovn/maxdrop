# The .max format, as far as MaxDrop has verified it

What MaxDrop's reader (`maxdrop/reader/`) relies on, written down only once a committed fixture shows it. Each fact
names the fixture (`tests/fixtures/<name>.max`, whose 3ds Max oracle is `<name>.oracle.json`, see
[ORACLE.md](ORACLE.md)) and the test that keeps it true. All nine fixtures were saved by 3ds Max 2020 (file
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

Flags in `0x0960` seen so far (their bits are not decoded yet): `0x800` on most nodes, `0` on the three
instances and the copy in instances (the source has `0x800`), `0x100800` on the hidden node of layers_flags,
`0x40` on its group head and `0x900` on the two group members. The oracle's `renderable` flag does not show in this field (FixtureNoRender has `0x800`).

## Hierarchy

- Parents are object indices, so nodes with the same name stay apart: in hierarchy one `FixtureTwin` is a
  child of FixtureRoot and the other is top level.
- The oracle lists nodes pre-order from the root, children in 3ds Max's order. On every fixture that equals a
  pre-order walk with each node's children sorted by object index. In layers_flags the group head has a higher
  node handle (6) than its members (4, 5) but a lower object index, and comes first in both orders.

## Open

Not shown by any fixture yet, so not stated above:

- Other root container ids: `0x2014` and `0x2023` occur in older files, and the 64-bit chunk header (size 0,
  then a `u64`) in large ones.
- Derived objects (an object with modifiers): special id `0x2032`, past the class directory, referencing its
  modifiers and then its base object. The reader follows them (`Scene.object_stack`), but no fixture has a
  modifier.
- The sign convention of the offset rotation: every fixture's is the identity.
- The meaning of the flag bits in `0x0960` and of the first `u32` of `0x2035`.
- The system unit, the optional fields of Editable Poly faces, the LookAt controller.
