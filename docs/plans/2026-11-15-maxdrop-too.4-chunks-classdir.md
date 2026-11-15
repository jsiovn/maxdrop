# maxdrop-too.4 Chunk Index and Class Directory Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** walk the chunk tree of a `.max` stream without building an object per chunk, and resolve the class
index of a Scene chunk to its ClassID, superclass, class name and DLL.

**Architecture:** `chunks.py` reads chunk headers straight from the stream's pieces (a bytes-like object, or
the zero-copy run views of a `cfb.Stream`, so an 800 MB Scene stream is never joined into one copy). A level of
the tree is a `ChunkList`: offsets, ids, sizes and header lengths in `array`s, with a `Chunk` made only when one
is asked for; a chunk's children are indexed the first time `children` is read. `classdir.py` parses
`ClassDirectory3` (fallback `ClassDirectory`) and `DllDirectory` through `chunks.py` into `ClassEntry` records;
`ClassId` is a `(classA, classB)` tuple subclass that prints as hex. `classids.py` names the ClassIDs and
superclass ids the project knows, each one verified against a fixture's class directory by a test.

**Tech Stack:** Python 3.11 syntax (runs on the local 3.9), standard library (`struct`, `array`, `bisect`);
numpy only inside `Chunk.as_array()`, imported there (Blender ships it; the plain CI job has none, so the numpy
tests skip there). No `bpy`, no `mathutils`.

**Not in scope:** the scene index, references and node records (maxdrop-too.5), wiring the reader into the
engine, a `ClassData` parser.

---

## Format facts used (verified on the fixtures and on the two corpus scenes while planning)

- Chunk header: `u16 id`, `u32 size`; bit 31 = container, the low 31 bits are the size **including** the
  header. `size == 0` -> a `u64` size follows (bit 63 = container), 14-byte header. Scene B's root (`0x2023`)
  uses the 64-bit form; its stream is 811 716 203 bytes in 167 runs, 35 825 top-level objects.
- `ClassDirectory3`: only `0x2040` containers at the top (120 in scene A, 140 in scene B, 53 in
  box_poly_standard); each has `0x2060` (16 bytes: `i32 dll index, u32 classA, u32 classB, u32 superclass`) and
  `0x2042` (UTF-16LE name, no terminator). The class index of a Scene child is its chunk id = position among the
  `0x2040` entries.
- `DllDirectory`: one `0x21C0` header chunk, then `0x2038` containers with `0x2039` (description) and `0x2037`
  (file name). A class's dll index counts `0x2038` entries from 0 (`ViewportManager`, dll 0 ->
  `viewportmanager.gup`, the first `0x2038`); -1 = built into the core, -2 also occurs (no DLL). Upstream's
  `get_dll` indexes the list including `0x21C0`, one off.
- Editable Poly in box_poly_standard: `ClassId(0x1BF8338D, 0x192F6098)`, superclass `0x10`, `epoly.dlo`.

## File Structure

| File | Responsibility |
|---|---|
| `maxdrop/reader/chunks.py` | `ChunkError`, `Source`, `Chunk`, `ChunkList`, `iter_chunks()`, `index()`, `DEFAULT_MAX_DEPTH` |
| `maxdrop/reader/classdir.py` | `ClassId`, `DllEntry`, `ClassEntry`, `ClassDirectory` (`from_file(cf)`, `parse(classdir, dlldir)`) |
| `maxdrop/reader/classids.py` | superclass ids (`SC_*`), ClassId constants by name, `CLASSES` ((superclass, ClassId) -> 3ds Max class name; a ClassId alone is not unique), `name_of()` |
| `tests/unit/test_chunks.py` | synthetic buffers (32/64-bit headers, nesting, hostile sizes, depth, pieces), every fixture stream |
| `tests/unit/test_classdir.py` | `ClassId`, synthetic directories, the fixtures (Editable Poly; every `classids` constant found) |

Tests load the reader by path as `maxdrop_reader` (like `test_cfb.py`): `import maxdrop` would pull bpy.

## Public interface

```python
# chunks.py
DEFAULT_MAX_DEPTH = 64; DEFAULT_MAX_CHUNKS = 1 << 22   # per level
class ChunkError(ValueError)
class Source:                       # Source(bytes-like | cfb.Stream | Source); .size; .view(off, n) -> memoryview
def index(data, max_depth=..., max_chunks=...) -> ChunkList        # top level, depth 0, must cover the stream
def iter_chunks(data, max_depth=..., max_chunks=...) -> Iterator[Chunk]   # same, without the arrays
class Chunk:
    id, offset, size, header, container, depth, end, payload_offset, payload_size
    view() -> memoryview            # zero-copy inside one piece
    tobytes(); text(); unpack(fmt, offset=0)
    as_array(dtype, offset=0, count=-1)   # numpy.frombuffer, little-endian forced, read-only
    children -> ChunkList           # indexed once, on first read, kept by the chunk; empty for a leaf
    first(cid) -> Chunk | None; find_all(cid) -> list[Chunk]
class ChunkList:                    # Sequence of Chunk: len, [i], [a:b], iter
    ids -> read-only memoryview of the u16 ids; first(cid); find_all(cid)

# classdir.py
class ClassId(tuple)                # ClassId(a, b); .a, .b; == (a, b); hash((a, b)); int() / from_int(); hex str
DllEntry(index, file, description)
ClassEntry(index, class_id, superclass, name, dll_index, dll)   # .class_a, .class_b, .dll_name
class ClassDirectory:               # len, [index] -> ClassEntry, iter, get(index), find(class_id) -> list
    from_file(cf); parse(classdir_data, dlldir_data=None); .dlls; .stream
```

Errors: a header cut short, a size smaller than its header, a chunk that ends after its parent (or after the
stream), a level deeper than `max_depth`, a payload too short for `unpack`/`as_array` -> `ChunkError`. A
`0x2040` without a 16-byte `0x2060` -> `ChunkError`. An unknown dll index -> `dll = None` (not fatal).

## Tasks

### Task 1: chunks.py

- [ ] Write `tests/unit/test_chunks.py`: builder `chunk(cid, payload=b"", children=None, big=False)`; cases:
  leaf fields and payload; container children lazy (`_children is None` before access) and cached; 64-bit
  header with bit 63; nested depth values; `first`/`find_all`/`ids`/negative index/slice/IndexError; size <
  header (32 and 64) -> ChunkError; child past parent -> ChunkError; top-level past stream; 1..5 trailing bytes;
  `max_depth` reached -> ChunkError, one less passes; `unpack` short -> ChunkError; `text`; `as_array` (f4 with
  offset and count, shares memory with the source, misaligned -> ChunkError, skipped without numpy); a fake
  stream whose pieces split a header and a payload; `iter_chunks` = `index`; every chunked stream of every
  fixture (Scene, ClassDirectory3, DllDirectory, Config, ClassData, VideoPostQueue) indexes to its full length
  recursively.
- [ ] Run, see the import fail; implement `chunks.py`; run until green.
- [ ] Commit `Add the lazy chunk index of the reader`.

### Task 2: classdir.py and classids.py

- [ ] Write `tests/unit/test_classdir.py`: `ClassId` (eq tuple, hash, int round trip, str/repr hex, range
  check); synthetic `ClassDirectory3` + `DllDirectory` (entries, dll -1/-2/out of range -> None, `0x21C0`
  skipped, missing `0x2060` -> ChunkError, missing name -> ""); `from_file` falls back to `ClassDirectory`;
  fixtures: box_poly_standard lists Editable Poly with `ClassId(0x1BF8338D, 0x192F6098)`, superclass 0x10, dll
  `epoly.dlo`; every Scene top-level child id < len(directory); every child of class `NODE` has a `0x0962` name
  chunk; every `classids` constant appears in some fixture with its `CLASSES` name.
- [ ] Dump the union of the fixtures' class directories (scratch script) and seed `classids.py` with the
  constants of `import_max.py` and the notes that a fixture confirms; leads no fixture has stay out (listed
  in the bead notes).
- [ ] Implement, run until green, commit `Add the class directory and the ClassID table`.

## Verification

Working directory: the repo root. `$S` = this session's scratchpad. Corpus paths from the bead notes, never
committed.

1. Plain tests: `python -I -m unittest discover tests` -> `OK` (numpy tests run locally: numpy 1.26 present).
2. Ruff, as CI: `python -m pip install ruff==0.17.5` into a scratch venv if `ruff` is missing, then
   `ruff check .` -> `All checks passed!`.
3. Build: `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...` (the zip carries the new modules).
4. Register and import smoke (build-and-test blocks 3 and 4) on Blender 5.2, 4.2 and 4.5 with the local fixture
   -> `SMOKE PASSED`, `IMPORT PASSED` on each (the reader is not wired into the engine yet; this proves the zip
   still registers and imports).
5. Scene B measurement: `$S\measure_top.py <scene B>` (scratch, not committed) opens the file with
   `cfb.CompoundFile`, `index(cf.open("Scene"))`, reads `root.children` (no descent), prints the count, the
   wall time and the process's peak working set and peak commit (psapi). Pass: under 2 s and under 300 MB peak;
   the numbers go into the bead notes (`bd update maxdrop-too.4 --append-notes`), the scene named "scene B".
6. Class directory: a scratch run of `ClassDirectory.from_file` on box_poly_standard prints the Editable Poly
   entry -> `ClassId(0x1BF8338D, 0x192F6098)`, the id of the notes (`0x192F60981BF8338D`); also covered by the
   fixture test of step 1.

## Review changes

The code review asked for bounded memory on hostile input: `ChunkList` caches the Chunks it makes in a
`WeakValueDictionary` (iterating a level no longer keeps an object per chunk), derives sizes from the next
sibling's offset instead of storing them, and refuses a level wider than `max_chunks`. `Source` makes a run's view
when first touched and hands out read-only views; `unpack` and `as_array` view only the bytes they read.
Superclass constants carry an `SC_` prefix so an int superclass cannot be mistaken for a ClassId constant.
