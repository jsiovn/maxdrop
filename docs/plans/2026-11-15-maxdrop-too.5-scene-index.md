# maxdrop-too.5 Scene Index, References, Node Records and Class Census Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** know every object of the Scene stream by its object index: its class, its references, and for nodes
their name, parent, flags, pivot offset and what they point to; plus `tools/census.py`, a class census of a
`.max` that names classes only.

**Architecture:** `maxdrop/reader/scene.py` wraps the first top-level chunk of the Scene stream (the root
container) and its `chunks.ChunkList` of objects: object index = position in that list, class index = chunk id.
References are read on demand from `0x2034` / `0x2035`; node records are built on demand and cached; the parent
map is built once for all nodes, with parent cycles cut deterministically; a reference walk through derived
objects (special id `0x2032`) gives a node's base object and modifier stack, guarded against cycles. Nodes are
keyed by object index everywhere. `tools/census.py` loads the reader by path (no Blender, no bpy) and prints or
emits JSON counts.

**Tech Stack:** Python 3.11 syntax, standard library only (`struct`, `collections`, `json`, `argparse`), the
existing `chunks.py`, `classdir.py`, `classids.py`. No `bpy`, no `mathutils`, no numpy.

**Not in scope:** controllers and world transforms (maxdrop-too.6), geometry (maxdrop-too.7), wiring the reader
into the engine, new fixtures (tests/fixtures is outside this bead's Files list).

---

## Format facts used

Verified on the committed fixtures (all nine saved by 3ds Max 2020, file version 22000) with
`tests/fixtures/*.max` and their oracles:

- Scene stream: one top-level container, id `0x2025` in every fixture. Its children are the objects; object
  index = position, chunk id = class index into ClassDirectory3. Two objects per fixture are leaf chunks (no
  children): they have no references.
- `0x2034` (in e.g. ViewportManager, Editable Poly, Layer Manager, Scene): i32 array, position = reference slot,
  -1 = empty slot (ViewportManager in hierarchy.max: `[0, -1]`).
- `0x2035` (Node, RootNode, Texmaps, Bezier Float/Scale/Color, Boolean Controller, Grid Reference): u32 first
  value (16 for Node and RootNode, 48 for Texmaps, 2 for the controllers; meaning unknown, kept raw), then
  `(u32 slot, i32 index)` pairs. Node in hierarchy.max: slots 0 (Position/Rotation/Scale), 1 (Editable Poly),
  3 (Standard), 6 (Base Layer). The group head of layers_flags.max (no material) has three pairs.
- Node (class `(1, 0)`, superclass 1): `0x0962` UTF-16LE name; `0x0960` = i32 parent object index + u32 flags;
  a top-level node's parent is the RootNode (class `(2, 0)`, superclass 1). `0x096A` 3 x f32 pivot offset
  position; `0x096B` 4 x f32 offset rotation; `0x096C` 7 x f32 = offset scale (3) + scale axis quaternion (4).
  FixtureRoot of hierarchy.max: position `[5, 5, 0]`, rotation `[0, 0, 0, 1]`, scale `[1, 1, 1]`, as the
  oracle's offset_pos / offset_rot / offset_scale.
- Flags seen in `0x0960`: `0x800` (most nodes), `0` (the three instances and the copy of instances.max), `0x100800` (the
  hidden node of layers_flags.max), `0x40` (the group head), `0x900` (the two group members).
- Hierarchy order: the oracle's node order (pre-order from the root) equals a pre-order walk whose children are
  sorted by object index, on every fixture. hierarchy.max holds two nodes named `FixtureTwin` with different
  parents; layers_flags.max a group head whose handle (6) is higher than its members' (4, 5) but whose object
  index is lower.

Seen on the corpus while planning (2026-11-15; class names and counts only, no fixture shows them yet):

- Root container id `0x2014` (scene A) and `0x2023` (scene B, 64-bit header).
- Derived object: special id `0x2032` (past the class directory), children `0x2034`, `0x204B`, `0x2501`,
  one `0x2500` per modifier. `0x2034` = `[modifier, ..., base]`: modifiers top of the stack first (TurboSmooth
  above Edit Poly), the base object last. A derived object can be the base of another (scene B, once).
- No object other than Node has a `0x0960` chunk in either scene.

## File Structure

| File | Responsibility |
|---|---|
| `maxdrop/reader/scene.py` (new) | `Scene`, `Node`, `Stack`, `ROOT_IDS`, `DERIVED_OBJECT`, `NODE_SLOTS`; reads only through `chunks` / `classdir` |
| `tools/census.py` (new) | `census(path) -> dict`, `format_text(dict)`, `main(argv)`; `--json` |
| `tests/unit/test_scene.py` (new) | synthetic streams (refs, node records, cycles, derived objects, hostile input); fixtures vs oracle |
| `tests/unit/test_census.py` (new) | census of the fixtures (counts vs oracle, JSON and text forms, no object names) |
| `docs/FORMAT.md` (new) | format facts verified on a fixture, each with its fixture |

## Public interface

```python
# maxdrop/reader/scene.py
ROOT_IDS = {0x2014: ..., 0x2023: ..., 0x2025: ...}   # known root container ids (others still read)
DERIVED_OBJECT = 0x2032
SLOT_TM, SLOT_OBJECT, SLOT_MATERIAL, SLOT_LAYER = 0, 1, 3, 6

class Node:          # __slots__: index, name, parent, parent_index, flags, pivot_position, pivot_rotation,
                     # pivot_scale, pivot_scale_axis, refs; properties tm, object, material, layer
class Stack(namedtuple("Stack", "base modifiers derived")):   # object indices; modifiers top first

class Scene:
    def __init__(self, data, classes): ...           # data: bytes-like | cfb.Stream; classes: ClassDirectory
    @classmethod
    def from_file(cls, cf, classes=None): ...
    root_id: int
    classes: ClassDirectory
    def __len__(self): ...                           # number of objects
    def class_index(self, i) -> int
    def entry(self, i) -> ClassEntry | None           # None for a special id
    def chunk(self, i) -> chunks.Chunk
    def span(self, i) -> tuple[int, int]               # (offset, size) of the object chunk in the stream
    def is_a(self, i, superclass, class_id) -> bool
    def refs(self, i) -> dict[int, int]                # slot -> object index; empty slots left out
    def ref_list(self, i) -> list[int | None]           # the 0x2034 form, None = -1
    node_indices: tuple[int, ...]                      # every Node, object index order
    root_node: int | None                              # the RootNode's object index
    def node(self, i) -> Node                          # ChunkError if i is not a Node
    def nodes(self) -> list[Node]
    def parent(self, i) -> int | None                  # after cycle cutting; None = top level
    def children(self, i=None) -> tuple[int, ...]       # None = top level; sorted by object index
    def walk(self) -> list[int]                         # pre-order, children by object index
    cut_cycles: tuple[int, ...]                        # nodes whose stored parent closed a cycle
    def object_stack(self, i) -> Stack                 # follows derived objects; cycle -> ChunkError
```

Rules: a parent index that is not a Node (the RootNode, another class, a special id, out of range) means top
level. A parent cycle is cut at its member with the lowest object index (that node becomes top level and is
listed in `cut_cycles`). A reference index outside the object list raises `ChunkError`; so do payloads of the
wrong size. All loops are iterative (no recursion), each bounded by the object count.

## Chunk 1: scene.py

### Task 1: references and the object index

**Files:** Create `maxdrop/reader/scene.py`, `tests/unit/test_scene.py`

- [ ] Write tests with a synthetic class directory (ClassDirectory.parse of `0x2040` entries: ParamBlock2,
      Node, RootNode, Editable Poly, Base Layer, Standard, an OSM modifier) and a Scene stream built from
      `leaf()` / `node()` helpers: `root_id`, `len`, `class_index`, `entry` (None for `0x2032`), `span`,
      `refs` for `0x2034` (with -1) and `0x2035`, `ref_list`, out-of-range ref -> ChunkError, odd payload sizes
      -> ChunkError, leaf object -> `{}`, non-container first top-level chunk -> ChunkError, empty stream ->
      ChunkError.
- [ ] Run `python -I -m unittest tests.unit.test_scene` -> fails (no module).
- [ ] Implement `Scene.__init__`, `from_file`, `__len__`, `class_index`, `entry`, `chunk`, `span`, `is_a`,
      `refs`, `ref_list`.
- [ ] Run again -> pass.

### Task 2: node records and the hierarchy

- [ ] Tests: `node_indices`, `root_node`, `node()` fields (name, parent_index, flags, pivot values and their
      defaults when a chunk is missing, slot properties), `node()` on a non-node -> ChunkError, two nodes with
      the same name are two records, `parent` (RootNode -> None, non-node -> None), cycle of two and a self
      parent cut at the lowest index (`cut_cycles`), `children`, `walk` pre-order by object index, a parent
      chain of 10 000 nodes (no recursion limit).
- [ ] Implement; run; pass.

### Task 3: derived objects

- [ ] Tests: node -> Editable Poly directly (`Stack(base, (), ())`); node -> derived `[mod2, mod1, base]`;
      nested derived `[modA, derived2]`, derived2 `[modB, base]` -> modifiers `(modA, modB)`; base slot -1 ->
      base None; derived cycle -> ChunkError; non-derived start returns itself as base.
- [ ] Implement `object_stack`; run; pass.

### Task 4: fixtures vs oracle

- [ ] Tests over every `tests/fixtures/*.max` with its `.oracle.json`: node count; names in `walk()` order;
      parent links (oracle parent handle -> oracle index, ours -> position in walk); pivot offset position and
      scale within 1e-5; base object class id and superclass of `object_stack(node.object).base` equal
      `base_class_id` / `base_superclass`; nodes sharing a slot-1 object = oracle `instances`; material slot
      present iff oracle `material` is not null; layer slot points to a class of superclass `SC_LAYER`.
      hierarchy.max: the two `FixtureTwin` are distinct nodes, parents FixtureRoot and top level.
- [ ] Run; pass. Commit `Add the scene index and node records of the reader`.

## Chunk 2: census and docs

### Task 5: tools/census.py

**Files:** Create `tools/census.py`, `tests/unit/test_census.py`

- [ ] Tests: `census(fixture)` -> `nodes.total == oracle node_count`; `nodes.by_base_class` sums to the total and
      names Editable Poly for box_poly_standard; `classes` counts sum to `objects`; `--json` output parses and
      equals `census()` without `seconds`; text output contains no node name of the fixture (all oracle names
      absent) and no file path; `main` returns 0, 2 for a missing file.
- [ ] Implement: open with `cfb.CompoundFile`, `ClassDirectory.from_file`, `Scene`; count per class index and
      special id; per node base class through `object_stack` (`(none)` without an object; a ChunkError on a
      node counts as `unreadable`, never aborts); modifier classes (occurrences and number of derived objects
      holding each) and stack depths; top level count, cut cycles; elapsed seconds.
- [ ] Run; pass. Commit `Add the class census tool`.

### Task 6: docs/FORMAT.md, corpus census, bead notes

- [ ] Write `docs/FORMAT.md`: the fixture-verified facts above, each with its fixture; what is still open.
- [ ] Run the census on scene A and scene B (paths from the bead notes; output stays in the scratchpad), time
      each, compare node totals with 746 / 2,251.
- [ ] Classify the nodes upstream's engine leaves without a message (BASELINE: 29 and 418) by the class of
      their slot-1 object and of their base object, using upstream's dispatch (`create_mesh`, `SKIPPABLE`) as
      the rule; write the result into the bead notes (class names and counts only).
- [ ] Commit `Start docs/FORMAT.md with the scene index facts`.

## Verification

**Working directory:** the repo root. No Blender API is touched by this bead (no add-on module imports
`reader/scene.py` yet), but `maxdrop/reader/` is in the package, so the build and smoke rows of
`build-and-test` apply.

1. Plain tests: `python -I -m unittest discover tests` -> exit 0, `OK` (skips only for absent numpy / tools).
2. Build: `powershell -ExecutionPolicy Bypass -File build.ps1` -> `dist\maxdrop-<version>.zip`, index.json,
   index.html; `python -I tools/check_zip.py dist/maxdrop-*.zip` passes if build.ps1 does not already run it.
3. Smoke on Blender 5.2, 4.2, 4.5 (paths in the bead notes), each with its own profile in the scratchpad:
   `BLENDER_USER_RESOURCES=<S>\profile-<v> <blender> --background --factory-startup --python-exit-code 1
   --python tests/smoke_register.py` and `... --python tests/smoke_import.py` -> exit 0 on all three.
4. Census timing (corpus, output only in the scratchpad):
   `python -I tools/census.py "<scene A>"` and `"<scene B>"` -> exit 0, each under 10 s (`seconds` in the
   output and `Measure-Command`), node totals 746 and 2,251 or the difference explained in the bead notes.
5. `python -I tools/census.py --json tests/fixtures/hierarchy.max` -> JSON with `nodes.total` 5.

**Success criteria:** all of the above pass; the bead notes name the classes behind the 29 and 418 nodes.
