# ParamBlock2 by parameter id and the material graph Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read any parameter of a material or texture map by its parameter id, and know the tree of materials and
maps of a scene, checked value by value against what 3ds Max reports (bead maxdrop-arp.1).

**Architecture:** `maxdrop/reader/pblock.py` decodes one ParamBlock2 object (and the old ParamBlock) from its
chunk plus the reference maps of the block and of its owner; it knows nothing else of the scene.
`maxdrop/reader/materials.py` walks from an object index through references: class, name, parameter blocks,
parts (coordinates, output, shader, sampler), sub-materials and maps, iteratively with a cycle guard. The oracle
(`tools/oracle/dump_scene.ms`, layout version 2) dumps every material and map reachable from a node with every
parameter by id through the SDK's .NET wrapper; `tests/unit/test_materials.py` holds the reader to it on every
fixture (RAW-PARAM PARITY). No bpy, no numpy.

**Tech Stack:** Python 3.11 stdlib (`struct`), 3ds Max 2020 + V-Ray 5 through the 3dsmax-mcp bridge (fixtures and
oracle only), `unittest`.

---

## What the probes established (3ds Max 2020, V-Ray 5; re-checked by the tests)

ParamBlock2 object (class `(0x82, 0)`, superclass `0x82`):

- `0x0009` header, 16 bytes: `u32` (9..15, meaning unknown), `u16` block id (the descriptor's id: VRayMtl 1..6,
  Bitmap 0 and 1), `u32` descriptor version, `u16` number of entries, `u32` object index of the owner.
- `0x100E` per stored parameter: `u16` param id, `u32` type (ParamType2; bit `0x800` = table), `u32` the
  parameter definition's flags (`0x1` animatable, `0x2` transient, `0x200` P_OWNERS_REF), `u32` unknown, then:
  - scalar: `u8` tag, then the value. Tag `0x40` = stored value, `0xC0` = stored value of an animatable
    parameter, `0x80` = a controller, no value;
  - table: `u8` 0, `u32` count, then per element a tag and a value as above.
  - Value by type: float types (0 float, 5 angle in radians, 6 fraction, 7 world, 11 color channel) `f32`; int
    types (1 int, 4 bool, 12 time, 13 radio button, 19 index) `i32`; 2 rgba and 10 hsv 3 x `f32`; 3 point3 3 x
    `f32`; 22 point4 and 23 frgba 4 x `f32`; 30 point2 2 x `f32`; 8 string `u32` byte count + UTF-16LE with a NUL;
    9 filename `i32` (-2: the asset follows as the next sibling `0x000F{0x0002 GUID}`); 16 bitmap `u8`, the
    bitmap data follows as the next sibling `0x0003`; reference types (14 mtl, 15 texmap, 17 node, 18 reftarg,
    21 pblock2): with P_OWNERS_REF an `i32` object index (or -1, also when a map is assigned), else no value.
- Transient parameters are not stored. Every other parameter is, defaults included.
- References held by the block (reference-type elements without P_OWNERS_REF) take the block's reference slots
  0, 1, 2 ... in entry order, tables expanded (VRayBlendMtl: baseMtl 0, coatMtl 1-9, texmap_blend 10-18;
  VRayNormalMap: normal_map 0, bump_map 1). Controllers take the slots after them, in entry order (probe only:
  VRayMtl with three animated parameters had slots 0, 1, 2 in entry order).
- `0x0013`, P_OWNERS_REF parameters: `u32` count, then `u16` param id, `u16` owner reference slot, `u16` unknown.
  The target is the owner's reference at slot (+ table index). VRayMtl `texmap_diffuse` (100) -> owner slot 7.
- Old ParamBlock (class `(8, 0)`): `0x0001` `u32` count, `0x0005` `u16` (unknown), per parameter a `0x0002`
  container: `0x0003` `u32` index, optional `0x0004` (empty seen), value chunk `0x0100` + ParamType: `0x0100`
  float, `0x0101` int, `0x0102` rgba (3 x f32), `0x0103` point3, `0x0104` bool.
- Material / map name: `0x4000{0x4001}` (VRayMtl: `0x5431{0x4001}`).

## Files

- Create: `maxdrop/reader/pblock.py`, `maxdrop/reader/materials.py`
- Modify: `maxdrop/reader/classids.py` (superclasses and the classes the fixtures prove)
- Create: `tools/fixtures/vray_basic.ms`, `vray_maps.ms`, `vray_wrappers.ms`, `standard_physical.ms`
- Create: `tests/fixtures/{vray_basic,vray_maps,vray_wrappers,standard_physical}.max` + `.oracle.json`
- Modify: `tests/fixtures/*.oracle.json` (regenerated: layout version 2, `material_graph`; nothing else changes)
- Modify: `tools/oracle/dump_scene.ms` (version 2, `material_graph`)
- Modify: `tests/test_oracle.py` (top keys, version, graph structure)
- Create: `tests/unit/test_pblock.py` (synthetic bytes: every value type, tables, refs, malformed input)
- Create: `tests/unit/test_materials.py` (RAW-PARAM PARITY and graph equality on every fixture)
- Modify: `docs/FORMAT.md` (ParamBlock2, ParamBlock, material graph, the ids per class with the fixture),
  `docs/ORACLE.md` (the new key), `CONTRIBUTING.md` only if the fixture flow changes (it does not)

## Chunk 1: fixtures and oracle (done during exploration)

- [x] Write the four fixture scripts, run them in 3ds Max 2020 + V-Ray, `sanitize_fixture.py`, `check_fixture.py`
  -> clean, copy into `tests/fixtures/`.
- [x] Extend `dump_scene.ms` (version 2): graph walk (sub-materials, sub-maps, then every material or map a
  property holds: `getSubMtl` of a Multi/Sub-Object answers by material ID and skips ID 3 of 1, 3, 7), every pb2
  parameter by id (`IndextoID`, `GetParamDef`, typed getters at time 0, tables element-wise), pb1 blocks, parts
  of superclass UVGen / XYZGen / TexOutput / Shader / Sampler.
- [x] `MaxDropOracle.dumpFolder` over `tests/fixtures`: 13 files, 0 failed; the nine old oracles equal their
  committed version once `material_graph` is removed and the version reset.
- [ ] `tests/test_oracle.py`: `TOP_KEYS` gains `material_graph`, version 2, a structure test for the graph (keys
  sorted, indices in range, targets valid). Run `python -I -m unittest tests.test_oracle tests.test_fixtures`.
- [ ] Commit: `Add V-Ray material fixtures and the material-graph oracle`.

## Chunk 2: pblock.py

- [ ] `tests/unit/test_pblock.py` first: build entries with a helper (`entry(id, type, flags, tag, value)`,
  `table(...)`, a ParamBlock2 container with header, `0x0013`, and siblings) and check: every value type;
  tag `0x80` -> `Animated(slot -> object index)`; block-held refs in entry order with tables; owner refs through
  `0x0013` (+ table index) and the stored index without a table entry; string tables; filename followed by
  `0x000F` (asset GUID kept as bytes); bitmap followed by `0x0003`; transient absence; unknown type kept raw;
  malformed: entry shorter than its header, table count larger than the payload, element of an unknown size in a
  table (the rest of that parameter is dropped, the parameter is kept as raw), header missing, `0x0013` cut.
- [ ] Implement `pblock.py`: `ParamBlock2.from_chunk(chunk, block_refs, owner_refs)` -> `block_id`, `version`,
  `owner`, `params` {id: `Param(id, type, flags, values, raw)`}, `get(id, tab=0)`, `value(id)` (list for a
  table), `Reference(index)` / `Animated(index)` values; `ParamBlock.from_chunk(chunk, refs)` for the old block,
  `get(index)`. Bounded: at most `MAX_TABLE` elements per table, ChunkError on damage of the block itself, a bad
  entry only poisons its parameter.
- [ ] Run `python -I -m unittest tests.unit.test_pblock`, commit `Read ParamBlock2 parameters by id`.

## Chunk 3: materials.py and the parity test

- [ ] `tests/unit/test_materials.py`: for each fixture, oracle graph vs reader graph: same entries (class id,
  superclass, name) reached from the node materials; for each oracle block (pb2 by block id and reference slot,
  pb1 by reference slot, in parts by part reference slot) each non-transient parameter is stored, and every
  numeric / color / bool value equals within 1e-5 (tables element-wise), strings equal, mtl / texmap values point
  to the entry the oracle names. Count the compared values and require a floor per V-Ray fixture.
- [ ] Implement `materials.py`: `MaterialGraph(scene)`, `graph.get(i)` -> `MtlBase(index, class_id, superclass,
  name, blocks {block_id: ParamBlock2}, legacy {ref slot: ParamBlock}, parts {ref slot: Part}, children [(ref
  slot or param, index)])`, `graph.walk(roots)` -> object indices depth first, each once (cycle guard, bounded by
  the object count), `MtlBase.param(param_id, block_id=None)`; `graph.issues` for objects that cannot be read.
- [ ] Add the proven classes to `classids.py` (VRayMtl, VRay2SidedMtl, VRayBlendMtl, Shell, Multi/Sub, Bitmap,
  VRayNormalMap, PhysicalMaterial, UVGen, TexOutput, Blinn shader, ...) and check them in `test_classdir.py`'s
  table (it already checks every entry against a fixture).
- [ ] Run all unit tests, commit `Walk the material graph of a scene`.

## Chunk 4: docs and corpus

- [ ] `docs/FORMAT.md`: ParamBlock2, ParamBlock, material graph, the ids used per class with the fixture.
- [ ] `docs/ORACLE.md`: `material_graph`, version 2.
- [ ] Corpus (local, scratch script, results only in the bead notes: classes and counts, no names): walk the
  material graph of scenes A and B from every node's material, count classes, objects that fail.
- [ ] Commit `Document ParamBlock2 and the material graph`.

## Verification

**Working directory:** `D:\www\maxdrop`. Python: `python -I` (any 3.9+; CI uses 3.11).

1. `python -I -m unittest discover tests` -> `OK` (skips only for absent Blender/archivers as before), including
   `tests.unit.test_materials` RAW-PARAM PARITY on vray_basic, vray_maps, vray_wrappers, standard_physical and the
   nine older fixtures.
2. `python -I tools/check_fixture.py tests/fixtures/*.max` -> every file `clean`.
3. `tests/smoke_register.py` and `tests/smoke_import.py` (no arguments: every fixture) headless with an isolated
   profile on Blender 5.2, 4.2.23 and 4.5.16 (the build-and-test skill's commands): exit 0. The new fixtures
   must import without error through the current pipeline (materials are still the old engine's or none).
4. `powershell -ExecutionPolicy Bypass -File build.ps1` -> zip + index; `tools/check_zip.py` passes.
5. Corpus (local, not in the repo): the scratch walk over scenes A and B ends without an exception; classes and
   counts recorded in the bead notes.

**Success:** all of the above; no bpy import under `maxdrop/reader` (`test_reader_no_bpy`).
