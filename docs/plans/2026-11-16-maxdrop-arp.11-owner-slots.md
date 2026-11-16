# Owner Slots Without 0x0013 Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a ParamBlock2 block without a 0x0013 owner-reference table resolves its owner-held references
(P_OWNERS_REF, stored index -1) through a fixed per-class owner-slot table, so materials of format-14000 files
keep their maps.

**Architecture:** a new `maxdrop/reader/owner_slots.py` holds `{(superclass, ClassId): {block id: {param id:
owner slot}}}` and one lookup function. `ParamBlock2.from_chunk` takes the owner's class as a new keyword
`owner_class=(superclass, ClassId)`; only when the block has no 0x0013 chunk at all and a P_OWNERS_REF element's
stored index is -1 does it read `owner_refs.get(slot + k)`. `MaterialGraph._blocks` passes the owner's class
(one argument: the only caller; `materials.py` is the caller the bead lists under Read).

**Tech Stack:** plain Python 3.11, no bpy, unittest.

---

## Survey (2026-11-16, scratch script outside the repo)

Every committed fixture block uses the 0x0009 header (no ClassID in the block), so the owner's class must come
from the caller. 0x0013 entries of P_OWNERS_REF parameters in the committed fixtures (superclass, ClassId, block):

| Class | block | pid -> slot | in bead table |
|---|---|---|---|
| Multi/Sub-Object (0xC00, 0x200) | 0 | 0->1 | yes, equal |
| Shell Material (0xC00, 0x255) | 0 | 2->1, 3->2 | no (fixture-backed) |
| VRay2SidedMtl | 0 | 0->1, 1->2 | no (fixture-backed) |
| VRayMtl | 4 | 100+k -> 7+k, k = 0..26 | yes, equal |
| RGB Tint (0xC10, 0x224) | 0 | 3->1 | no (fixture-backed) |
| Mix (0x230) | 0 | 6->1, 7->2, 8->3, 12->4 | yes, equal |
| Bitmap (0x240) | 0 | 15->2 | no (fixture-backed) |
| RGB Multiply (0x290) | 0 | 2->1, 3->2 | no (fixture-backed) |
| Output (0x2B0) | 0 | 2->1 | yes, equal |
| Color Correction (0x2D0) | 0 | 1->1 | yes, equal |
| Normal Bump | 0 | 2->1, 3->2 | no (fixture-backed) |
| Falloff | 0 | 2->4, 6->5 | yes, equal |

No contradiction. Gate-measured only (scene B's 0x0013, no fixture): VRayOverrideMtl 0,2,4,6,8 -> 1..5; Composite
(0x280) 0->1, 2->1 (obsolete empty tables in scene B; texmap_rules' Composite holds its maps itself); VRayLightMtl
2->1, 5->2, 9->3; class (0xC10, 0xC90017A5:0x111940BB) 21->1, 22->2, 3->3, 4->4, 5->5. The fixture-backed extras
are needed: the bead's test blanks every fixture block with a 0x0013 table.

## Chunk 1: table, reader, tests

### Task 1: owner_slots.py + classids constants

**Files:** Create `maxdrop/reader/owner_slots.py`; Modify `maxdrop/reader/classids.py` (fixture-backed texmap and
material ClassIds + their `CLASSES` names, checked by `tests/unit/test_classdir.py`).

- [ ] Add to classids.py: `RGB_TINT (0x224)`, `MIX (0x230)`, `RGB_MULTIPLY (0x290)`, `OUTPUT_MAP (0x2B0)`,
  `COLOR_CORRECTION (0x2D0)`, `COMPOSITE (0x280)`, `FALLOFF (0x6EC3730C, 0)`, `NORMAL_BUMP (0x243E22C6,
  0x63F6A014)` with `CLASSES` names `RGB Tint`, `Mix`, `RGB Multiply`, `Output`, `Color Correction`, `Composite`,
  `Falloff`, `Normal Bump` (superclass SC_TEXMAP).
- [ ] owner_slots.py: `TABLE = {(superclass, ClassId): {block_id: {pid: slot}}}`; classes without a fixture are
  local constants with a comment "measured by the M2 gate (scene B's 0x0013), no fixture";
  `def slots(owner_class, block_id)` -> `{pid: slot}` (empty dict for None or unknown).

### Task 2: from_chunk fallback (TDD)

**Files:** Modify `maxdrop/reader/pblock.py`, `maxdrop/reader/materials.py` (pass `owner_class`),
`tests/unit/test_pblock.py`.

- [ ] Tests first (synthetic): a Mix block (owner class (0xC10, (0x230, 0)), block 0) with no 0x0013, pid 6 stored
  -1 -> `Reference(owner_refs[1])`; stored index >= 0 kept; unknown ClassID -> `Reference(None)`; no owner_class ->
  `Reference(None)`; table slot past the owner's references -> `Reference(None)`, no exception; a block WITH a
  0x0013 ignores the fixed table (0x0013 says slot 3, fixed says 1 -> slot 3); a damaged 0x0013 keeps today's
  behavior (no fallback); a table parameter (VRayBlendMtl-like) element k uses slot + k.
- [ ] Fixture test: for every committed fixture, every material/map block with a 0x0013: rebuild the block chunk
  without 0x0013 and with every P_OWNERS_REF reference element's stored i32 set to -1; parse with the owner's
  class -> the same `values` for every parameter as the original parse. At least one block per bead-table
  fixture class is exercised (assert the count of blanked blocks > 0 and the classes seen include Mix, Falloff,
  Color Correction, Output, VRayMtl, Multi/Sub-Object).
- [ ] Run, see red (`owner_class` unknown keyword).
- [ ] Implement: in `from_chunk(..., object_count=None, owner_class=None)`, `fixed = owner_slots.slots(owner_class,
  block_id) if table is None else {}`; in the owner-ref branch: `elif flags & P_OWNERS_REF and v[1] == -1 and pid in
  fixed: values[k] = Reference(owner_refs.get(fixed[pid] + k))`.
- [ ] materials.py `_blocks`: pass `owner_class=(entry.superclass, entry.class_id)` of object i (parts: the part's
  own class).
- [ ] Green: `python -I -m unittest discover tests` (incl. test_malformed.py).
- [ ] Commit `Fill owner references of blocks without an owner table`.

### Task 3: docs

- [ ] docs/FORMAT.md ParamBlock2 section: the format-14000 gap and the fixed table; pblock.py docstring line.
- [ ] Commit (or fold into Task 2's commit).

## Verification

**Plain:** `python -I -m unittest discover tests` -> `OK` (skips allowed as before).
**Build:** `powershell -ExecutionPolicy Bypass -File build.ps1` -> zip + index in `dist\`.
**Blender (headless, isolated profile, each of 5.2 installed, 4.2.23 and 4.5.16 portable):**
`BLENDER_USER_RESOURCES=<scratch> <blender> --background --factory-startup --python-exit-code 1 --python
tests/smoke_register.py` -> pass line; `... --python tests/smoke_import.py` -> `IMPORT PASSED`.
**Gate rerun (local only, evidence folder `C:\maxdrop_fixtures\oracle\m2gate\`, counts only):** from that folder
`python -I matparity.py D:\www\maxdrop <scene A> scene_a.v2.oracle.json "scene A"` -> about 213/214, at least
95 %; same for scene B -> 220/220; `python -I matparity.py D:\www\maxdrop --fixtures` -> 49/49.
**Success:** all of the above; close reason records scene A and B numbers; `bd update maxdrop-arp.9 --status open`
when scene A >= 95 %.
