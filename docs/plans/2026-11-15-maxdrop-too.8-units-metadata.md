# maxdrop-too.8 System units and pre-flight info Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read a .max file's system unit and the summary properties that say what the user is about to import,
and give the format work a diff tool that isolates where a setting is stored.

**Architecture:** `tools/maxdiff.py` compares two or three files stream by stream (chunk leaves by path, other
streams byte by byte) on `maxdrop/reader/cfb` + `chunks`. It located the unit in the Scene stream: the object of
class Scene `(0x2222, 0)`, superclass `0x100`, holds `0x8520` = `i32` unit type + `f32` scale (units_mm 3,
units_cm 4, units_in 0; every other fixture 3; scale 1.0). `maxdrop/reader/units.py` reads that chunk through
`scene.Scene`; `maxdrop/reader/metadata.py` parses the OLE property sets with a bounded parser and returns only
whitelisted facts (never user, computer, author, object or material names, dependency paths).

**Tech Stack:** Python 3.11 standard library; plain `unittest`.

---

## Findings already made (exploration before the plan)

- `python -I tools/maxdiff.py units_mm.max units_cm.max` lists `Scene 2025#0/0034#0/8520#0`
  `03 00 00 00 00 00 80 3f` -> `04 00 00 00 ...`; units_in: `00 00 00 00 ...`. Codes match the SDK's
  `UNITS_INCHES 0, FEET 1, MILES 2, MILLIMETERS 3, CENTIMETERS 4, METERS 5, KILOMETERS 6`; the float is
  `units.SystemScale`. Feet, miles, meters, kilometers and a scale other than 1 are from the SDK, not a fixture.
- `Config` also differs (`21A0/1A02/100E` entries: grid and snap preferences in system units), and the Scene's
  `0x0000` object and `0x0015` viewport chunks: derived values, not the setting.
- `DocumentSummaryInformation` (code page 65001) section `D5CDD502-...`: property 12 heading pairs (vector of
  variant string + i4 count) partition property 13 (vector of LPSTR): `General` (`3ds Max Version: 22.00`,
  `Uncompressed`, `Build: 22.2.0.2176`, `Saved As Version: 22.00`), `Mesh Totals` (`Vertices: n`, `Faces: n`),
  `Scene Totals` (`Objects`, `Shapes`, `Lights`, `Cameras`, `Helpers`, `Space Warps`, `Total`), `External
  Dependencies` (paths), `Objects` (names), `Materials` (names), `Used Plug-Ins` (dll names), `Render Data`
  (`User Name=`, `Computer Name=`, `Renderer ClassIDA/B=`, `Renderer Name=`, size, animation range, flags).
- `SummaryInformation`: thumbnail, dates, last author and property 34 (the user name), revision; nothing taken.

## Task 1: tools/maxdiff.py

**Files:** Create `tools/maxdiff.py`, test `tests/unit/test_maxdiff.py`.

- `leaves(stream_bytes)` -> `({path: payload}, {container path: child count})` or None when not chunked.
  Path = `ID#n` per level (n-th sibling with that id).
- `byte_ranges(a, b)` -> merged `(start, end)` ranges (gap 8), length difference at the end.
- `diff(a, b, a2=None)` -> `Difference(stream, where, a, b, note)` list; A-vs-A2 paths / overlapping byte ranges
  are noise and dropped.
- `main(argv)`: 2 or 3 files, `--bytes N`, `--stream NAME`; exit 0 / 1 unreadable / 2 usage.
- Tests: `byte_ranges` on synthetic bytes; `leaves` on synthetic chunks; `diff(units_mm, units_cm)` contains the
  `8520` leaf with the two payloads; `diff(mm, cm, a2=units_in)` drops it (it differs mm vs in too);
  `diff(mm, mm)` empty; `main` usage errors -> 2.

## Task 2: maxdrop/reader/units.py

**Files:** Create `maxdrop/reader/units.py`, test `tests/unit/test_units.py`.

```python
SystemUnit = namedtuple("SystemUnit", "name meters")
UNITS = {0: ("inches", 0.0254), 1: ("feet", 0.3048), 2: ("miles", 1609.344), 3: ("millimeters", 0.001),
         4: ("centimeters", 0.01), 5: ("meters", 1.0), 6: ("kilometers", 1000.0)}
def decode(payload) -> SystemUnit | None   # i32 type + f32 scale; unknown type, non-finite or <= 0 scale -> None
def system_unit(source) -> SystemUnit | None   # source: cfb.CompoundFile or scene.Scene
```

- Scale 1: name = the unit; other scale: `"%g %s" % (scale, unit)`, meters = unit meters * scale (scale rounded
  to 7 significant digits, the precision of the f32).
- Tests: units_mm 0.001, units_cm 0.01, units_in 0.0254, box_poly_standard millimeters, every fixture equal to the
  oracle's `units.system_type`; synthetic payloads for feet/miles/meters/kilometers, a custom scale, unknown type,
  NaN / zero / negative scale, short payload -> None; a scene without a Scene object -> None.

## Task 3: maxdrop/reader/metadata.py

**Files:** Create `maxdrop/reader/metadata.py`, test `tests/unit/test_metadata.py`.

- `property_sets(data)` -> `{fmtid: {pid: value}}` for VT_I2/I4/UI4/LPSTR/LPWSTR/BOOL/FILETIME and vectors of
  LPSTR/LPWSTR/VARIANT; others skipped. Bounded: section offsets/sizes inside the stream, property count capped,
  every value inside its section; malformed -> `MetadataError` (ValueError).
- `read(cf)` -> dict: `max_version` (`"22.00"`), `max_release` (2020 = major + 1998 for major >= 10),
  `saved_as_version`, `build`, `compressed` (bool), `renderer` `{name, class_id: (a, b)}`, `counts`
  (objects, shapes, lights, cameras, helpers, space_warps, total, vertices, faces, materials; only those present),
  `plugins` (list). Keys absent when the file lacks them; `{}` without the stream.
- Never: `User Name`, `Computer Name`, author fields, object or material names, External Dependencies.
- Tests: every fixture: max_version 22.00, release 2020, renderer Scanline with class (1, 0) = oracle renderer
  class id, objects count = oracle node_count, materials count = len(oracle materials), not compressed, plugins
  include `epoly.dlo`; no key or value (recursively) contains `xxxxx`, `user`, `computer`, `author`, a node or
  material name of the oracle; synthetic damaged streams -> MetadataError.

## Task 4: docs/FORMAT.md

- New section "System unit" (Scene object, `0x8520`, codes, which fixtures) and "Summary properties"; drop
  "The system unit" from Open; SDK-only codes listed under Open.

## Verification

**Working directory:** repo root `D:\www\maxdrop`.

1. `python -I -m unittest discover tests` -> OK (includes units_mm 0.001, units_cm 0.01, units_in 0.0254,
   box_poly_standard millimeters; metadata 2020 / 22.00 / renderer; no identity strings).
2. `python -I tools/maxdiff.py tests/fixtures/units_mm.max tests/fixtures/units_cm.max --stream Scene` lists the
   `8520` leaf.
3. `powershell -ExecutionPolicy Bypass -File build.ps1` builds (reader modules are packed but not imported by
   the add-on yet); register + import smoke on Blender 4.2, 4.5, 5.2 headless with an isolated profile
   (build-and-test skill), unchanged behaviour expected.
4. Corpus, local only (scratch script outside the repo): `system_unit` and `read` on scene A and B without error;
   values go into the bead notes as counts/units only (no names).
