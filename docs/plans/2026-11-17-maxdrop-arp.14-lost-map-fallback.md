# A set map that converts to nothing is not the wrapper's color — Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a texmap wrapper whose map is set (and switched on) but converts to nothing never draws its own color for
that map: the slot keeps the material's own value, or (two-map wrappers) the wrapper gives its other map.

**Architecture:** `maxdrop/convert/texmaps.py` only. `_on` says which map a parameter really uses (set, switch on);
`_sub` names a used map that converts to nothing in an issue on the wrapper. Each rule then decides what a lost map
gives instead of its fallback color.

**Tech Stack:** plain Python 3.11, unittest; Blender 4.2 / 4.5 / 5.2 for the smokes.

---

## Behavior per rule (what 3ds Max does vs what MaxDrop drew)

3ds Max uses a wrapper's own color for a map only when no map is assigned or the map is switched off. A set map that
MaxDrop cannot convert (an unsupported class with no bitmap below, a Bitmap without file, a cycle...) is unknown,
not that color.

| Rule | Before | After |
|---|---|---|
| Color Correction (kept) | `color` (black by default) | no graph: the slot keeps the material's own value; issue `Color Correction 'x': its map Noise 'y' converts to nothing` |
| Mix color 1 / 2 (kept) | `color1` / `color2` in its place | the Mix is peeled to its other side's map (approximated, counted peeled) when that side is a map that converts; else no graph |
| RGB Multiply (kept) | `color1` / `color2` (white) | same as Mix |
| CoronaMix bottom / top (kept) | bottom / top color | same as Mix |
| Mix / CoronaMix mask | the mix amount | unchanged (the amount), now approximated + issue: a lost mask has no other side to fall back on |
| Falloff map 1, VRayDirt unoccluded map (peeled) | already no graph (the `_node` result is returned) | unchanged; the naming issue added |
| Output, RGB Tint, VRayColor2Bump (peeled) | already no graph (`_sub`) | unchanged; the naming issue added |
| Composite layers | a lost layer is dropped (no color drawn for it) | unchanged |
| Normal map classes | a lost normal map leaves the bump map (no color) | unchanged; the naming issue added |

## Files

- Modify: `maxdrop/convert/texmaps.py` (docstring, `_on`, `_below`, `_sub`, `_falloff`, `_vray_dirt`, `_mix`,
  `_rgb_multiply`, `_color_correction`, `_corona_mix`, helpers `_sides` / `_other_side`).
- Modify: `tests/unit/test_texmaps.py` (fixture case FixtureCCNoise, synthetic cases per rule).
- Modify: `docs/SUPPORT.md` (Mix / RGB Multiply / CC / Composite row, CoronaMix row), `CHANGELOG.md` (`## [0.0.4]`).

### Task 1: failing tests

- [ ] `VRayTexmaps.test_color_correction_over_an_unsupported_map`: `FixtureCCNoise` has no `base_color` texture
  (its own diffuse stays), one issue on the Color Correction naming `Noise`; `stats.unsupported` stays
  `{"Noise": 1}`.
- [ ] `LostMaps` synthetic class with a `_noise(i)` (unknown class, no bitmap below):
  - CC over Noise -> `None`; issue names `Color Correction` and `Noise`; CC without a map -> its color.
  - Mix(bitmap, Noise) -> the bitmap, approximated, `peeled == {"Mix": 1}` plus the Noise unsupported; Mix(color1,
    Noise) -> `None`; Mix(Noise, bitmap) with map 1 switched off -> a Mix with color1 (off is not lost).
  - Mix mask Noise -> a Mix with the amount, approximated, issue names the mask's class.
  - RGB Multiply(Noise, bitmap) -> the bitmap; both lost -> `None`.
  - CoronaMix mix(bottom Noise, top bitmap) -> the bitmap; multiply with bottom color and top Noise -> `None`.
  - Falloff(map1 Noise) -> `None` (not color1); VRayDirt(unoccluded map Noise) -> `None`; Output / RGB Tint over
    Noise -> `None`; each with the naming issue.
- [ ] `python -I -m unittest tests.unit.test_texmaps` -> the new cases FAIL (CC gives a ColorCorrect of black, Mix
  a Mix with color2...).

### Task 2: the rules

- [ ] `_on(m, map_pid, on_pid, tab)`: the index when set and switched on; `_sub` uses it, issues
  `"%s %r: its map %s converts to nothing"` (`_below(i)`: `"<class> '<name>'"`, `object <i>` when not a readable
  map) when a used map gives `None`.
- [ ] `_sides(conv, m, ids, ...)` -> `(nodes, lost)`; `_other_side(conv, m, nodes, walk)` -> the first converted
  side (approximated, counted peeled) or `None`.
- [ ] `_color_correction`: lost -> `None`; `_mix`, `_rgb_multiply`, `_corona_mix`: lost side -> `_other_side`;
  mask lost -> approximated; `_falloff`, `_vray_dirt` via `_sub` (fallback color only when the map is not used).
- [ ] Module docstring: the rule in one paragraph.
- [ ] `python -I -m unittest discover tests` -> OK.

### Task 3: docs

- [ ] `docs/SUPPORT.md`: a set map MaxDrop cannot convert below a Color Correction leaves the material's own color;
  below a Mix, RGB Multiply or CoronaMix the other map is used.
- [ ] `CHANGELOG.md` under `## [0.0.4]` (version unchanged): the fix line.
- [ ] Commit: `Keep the slot's color over a map that converts to nothing` (body: per-rule decisions, Composite and
  the masks keep theirs and why; `Bead: maxdrop-arp.14`).

## Verification

- `python -I -m unittest discover tests` -> `OK`; again with a venv without numpy (`python -m venv <scratch>\venv`,
  `<scratch>\venv\Scripts\python -I -m unittest discover tests`) -> `OK`.
- `powershell -ExecutionPolicy Bypass -File build.ps1` -> `dist\maxdrop-0.0.4.zip`, `index.json`, `index.html`;
  then the build-and-test skill: `tests/smoke_register.py` and `tests/smoke_import.py` (fixtures) headless with an
  isolated `BLENDER_USER_RESOURCES` on Blender 4.2.23, 4.5.16 (portable) and 5.2 (installed) -> exit 0,
  `FIXTURES PASSED`.
- Local only (never committed), from `C:\maxdrop_fixtures\oracle\m2gate`:
  `python -I matparity.py D:\www\maxdrop <scene A .max> scene_a.v2.oracle.json "scene A"` -> >= 213/214;
  same for scene B -> 220/220; `python -I matparity.py D:\www\maxdrop --fixtures` -> all pass.
