# Peeled wrapper over a lost map Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `_PEEL` wrapper (Falloff, VRayDirt, Output, RGB Tint, VRayColor2Bump) is counted in `stats.peeled`
and marks its walk approximated only when its rule returns a node.

**Architecture:** In `TexmapConverter._convert_node` (`maxdrop/convert/texmaps.py`), run the `_PEEL` rule first,
then count and flag only for a non-None result. A wrapper over a lost map already carries the "converts to
nothing" issue (`_sub` -> `_lost`) and its lost map is counted where it belongs (an unsupported class in
`stats.unsupported`, a Bitmap without a file as an issue), so the wrapper is counted nowhere: counting it under
unsupported too would count one loss twice in the report's material problems. Not setting `approximated` keeps a
Mix whose lost side has weight 0 exact, as the module docstring already says.

**Tech Stack:** Python 3.11, unittest (no Blender for the unit tests); Blender 4.2 / 4.5 / 5.2 smokes.

Bead: maxdrop-em3.37

---

### Task 1: Count a peel only when it gives a node

**Files:**

- Modify: `maxdrop/convert/texmaps.py` (`_convert_node`, the `_PEEL` branch; module docstring line on peels)
- Test: `tests/unit/test_texmaps.py` (`LostMaps.test_peeled_wrappers_give_nothing`, a new Mix test)

- [ ] **Step 1: Write the failing tests**

In `test_peeled_wrappers_give_nothing`, inside the loop after `self.lost_issue(tex, cls)`:

```python
            self.assertEqual(tex.stats.peeled, collections.Counter(), cls)
            self.assertEqual(tex.stats.unsupported, collections.Counter({"Noise": 1}), cls)
```

and add VRayColor2Bump (`FakeMap(1, tx.VRAY_COLOR2BUMP, {0: Ref(2)}, [2], cls="VRayColor2Bump")`) to the loop.
After the "no map: color 1" and "map off: its color" checks, assert those still count `{"Falloff": 1}` /
`{"VRayDirt": 1}` in `stats.peeled` (a real peel).

New test in `LostMaps`, `test_hidden_peeled_wrapper_is_exact`: a Mix with amount 1.0, map 1 a Falloff over a
Noise and map 2 a Bitmap. Side 1 has weight 0, so it is drawn as color 1 (exact): the graph is a Mix,
`g.approximated` is False, `stats.peeled` is empty, `stats.unsupported` is `{"Noise": 1}`.

- [ ] **Step 2: Run them, expect FAIL** (`stats.peeled` holds the wrapper; `approximated` True)

`python -I -m unittest tests.unit.test_texmaps -k LostMaps`

- [ ] **Step 3: Implement**

```python
        rule = _PEEL.get(key)
        if rule is not None:
            node = rule(self, m, kind, walk, depth, chain)
            if node is not None:
                walk.approximated = True
                self._count(self.stats.peeled, m)
            return node
```

Docstring: "Peeled to the first usable map below, an approximation counted by class" -> add that a wrapper over a
lost map is counted nowhere (its lost map is).

- [ ] **Step 4: Run, expect PASS**; then `python -I -m unittest discover tests` -> OK

- [ ] **Step 5: Commit** (`Count a peeled map wrapper only when it gives a node`, body with `Bead: maxdrop-em3.37`)

## Verification

- Working directory: `D:\www\maxdrop`.
- `python -I -m unittest discover tests` -> `OK`.
- `powershell -ExecutionPolicy Bypass -File build.ps1` -> zip, index.json, index.html in `dist\`.
- Smokes on Blender 5.2 (installed), 4.2 and 4.5 (portable, paths in the local test setup memory), each headless
  with an isolated profile (`BLENDER_USER_RESOURCES=<scratch>`, `--background --factory-startup
  --python-exit-code 1`): `tests/smoke_register.py` and `tests/smoke_import.py` (fixtures) -> exit 0.
- Success: all of the above pass; no install / upgrade flow needed (no manifest, prefs or update change).
