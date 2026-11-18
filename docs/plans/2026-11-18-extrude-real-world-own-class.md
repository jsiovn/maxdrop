# Extrude: Real-World Map Size from its own class's entry Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `convert/extrude._real_world` reads the 0x0130 flag only from the `0x2150 {0x0110}` entry whose 0x0120
names the Extrude class, as `primitives._real_world` and `uvwmap._real_world` do (bead maxdrop-em3.56).

**Architecture:** Same rule as `uvwmap._real_world`: walk every 0x0110 entry, skip those whose 0x0120's first 8
bytes are not the modifier's ClassID, read the u32 of the first match; no match is off. `read_params` passes
`modifier.class_id`.

**Tech Stack:** plain Python (`maxdrop/convert/`, no bpy), unittest.

---

### Task 1: entry chosen by class id

**Files:**

- Modify: `maxdrop/convert/extrude.py` (`_REAL_WORLD*` constants, `_real_world`, `read_params`, docstring)
- Test: `tests/unit/test_extrude.py` (`Parameters`)

- [ ] **Step 1: failing test** `Parameters.test_real_world_is_the_entry_of_its_own_class`: hand-made chunks as in
  `test_primitives.HandMadeTest.test_real_world_is_the_entry_of_its_own_class`: another class's entry set ->
  False; other set + own clear -> False; other clear + own set -> True; no entry -> False.
- [ ] **Step 2:** `python -I -m unittest discover tests -p test_extrude.py -k real_world` -> FAIL (signature / first entry).
- [ ] **Step 3:** implement `_real_world(chunk, class_id)` like uvwmap's; `read_params` passes `modifier.class_id`.
- [ ] **Step 4:** rerun -> PASS; whole `test_extrude` (fixture: FixtureExtAdaptive still real-world) -> OK.
- [ ] **Step 5:** commit (`Bead: maxdrop-em3.56`).

## Verification

- `python -I -m unittest discover tests` -> OK
- `tests/blender/run.py` FIXTURES PASSED on Blender 5.2, 4.2.23 and 4.5.16 (headless, isolated profile;
  see the build-and-test skill)
