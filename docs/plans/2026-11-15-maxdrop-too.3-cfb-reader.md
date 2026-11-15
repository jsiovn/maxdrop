# maxdrop-too.3 CFB Reader Implementation Plan

> **For agentic workers:** Use subagents when appropriate to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `maxdrop/reader/cfb.py` opens the OLE compound file of a `.max` through `mmap`, lists its streams and
hands out any stream as bytes or a zero-copy view, in milliseconds, also for an 800 MB file.

**Architecture:** `CompoundFile(source)` (a path, or a bytes-like for tests) parses the header, the DIFAT, the
FAT (an `array('I')`), the directory (tree walk from the root, iterative, visited set) and the mini FAT. Nothing
else is read at open. `open(name)` resolves the stream's sector chain into *runs* of file offsets (consecutive
sectors merged; mini sectors mapped through the root chain to file offsets too) and returns a `Stream` that reads
ranges straight from the mapping. A stream that starts with `1F 8B` is gzip: `open()` inflates it by default,
member by member, with a size cap (4 GiB, argument), and returns the same `Stream` interface over the result.
Every malformed structure raises `CfbError` (a `ValueError`): sector index out of range, chain cycle (more steps
than FAT entries), chain shorter than the size, directory cycle, entry count over the cap, runs past the end of
the file.

**Tech Stack:** Python 3.11 syntax (runs on the local 3.9 too), standard library only (`mmap`, `array`,
`struct`, `zlib`). No `bpy`, no `mathutils`, no numpy needed.

**Not in scope:** the chunk index (maxdrop-too.4), merging `tools/cfb.py` into the reader (the fixture tools
load it by path and stay as they are), wiring the reader into the engine.

---

## File Structure

| File | Responsibility |
|---|---|
| `maxdrop/reader/__init__.py` | package docstring only; nothing imported at load (sub-packages are imported on demand) |
| `maxdrop/reader/cfb.py` | `CfbError`, `MAGIC`, `is_cfb()`, `CompoundFile`, `Entry`, `Stream` |
| `tests/unit/__init__.py` | makes `tests/unit` a package so `unittest discover tests` finds it (3.11+ no longer discovers namespace dirs) |
| `tests/unit/test_cfb.py` | a CFB builder inside the test (v3, v4, DIFAT, fragmented, mini stream, storage, gzip) and the hostile cases; every `tests/fixtures/*.max` against the independent `tools/cfb.py` |
| `tests/unit/test_reader_no_bpy.py` | AST scan: no module under `maxdrop/reader` (and `maxdrop/convert` once it exists) imports `bpy` or `mathutils` |

Tests load the reader as a package by path (`spec_from_file_location("maxdrop_reader", .../__init__.py,
submodule_search_locations=[...])`): `import maxdrop` would pull `bpy`.

## Public interface

```python
class CfbError(ValueError): ...
MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
def is_cfb(head) -> bool
DEFAULT_MAX_ENTRIES = 65536
DEFAULT_MAX_DECOMPRESSED = 4 << 30

class CompoundFile:
    def __init__(self, source, max_entries=DEFAULT_MAX_ENTRIES)   # path or bytes-like
    version: int; sector_size: int; size: int
    def names(self) -> list[str]          # stream paths in tree order, "Storage/Child" below a storage
    def entries(self) -> list[Entry]       # streams and storages: path, kind, size, start
    def exists(self, name) -> bool         # case-insensitive, like CFB itself
    def open(self, name, decompress=True, max_size=DEFAULT_MAX_DECOMPRESSED) -> Stream
    def close(self); __enter__/__exit__

class Stream:
    name: str; size: int; runs: tuple[(file_offset, length), ...]; compressed: bool (was gzip in the file)
    def read(self, offset=0, size=-1) -> bytes
    def view(self, offset=0, size=-1) -> memoryview   # zero-copy inside one run, a copy across runs
    def buffer(self) -> memoryview                    # the whole stream contiguous (zero-copy for one run)
    def __len__
```

## Tasks

### Task 1: Package and guard test

- [ ] Create `maxdrop/reader/__init__.py` (SPDX GPL-3.0-or-later header, docstring).
- [ ] Write `tests/unit/__init__.py` and `tests/unit/test_reader_no_bpy.py`: walk `maxdrop/reader/**/*.py`
  (and `maxdrop/convert/**/*.py` if present), parse with `ast`, fail on `import bpy`, `import mathutils`,
  `from bpy...`, `from mathutils...`; also assert the scan found `cfb.py` (no vacuous pass).

### Task 2: Test builder and failing tests

- [ ] `tests/unit/test_cfb.py`: a `Builder(version)` that allocates sectors, writes chains into a FAT, puts
  streams under 4096 bytes into the mini stream, writes the directory as a right-sibling list (one storage with a
  child), places FAT sectors (and DIFAT sectors past 109) and the header. Exposes the first sector of each
  stream and a `fat_patch` / `dir_patch` hook for hostile cases.
- [ ] Cases: v3 and v4 round trip of every stream; a fragmented stream (two streams interleaved, and a chain
  that runs backwards) -> `runs` merged correctly and bytes equal; mini stream; storage child path;
  case-insensitive lookup; `view()` of one run is zero-copy (`obj` is the mapping's buffer) and across runs
  equal bytes; `buffer()`; v3 file with 110 FAT sectors (DIFAT); gzip stream inflated, cap exceeded ->
  `CfbError`, `decompress=False` returns the raw bytes; two gzip members; a path on disk through `mmap` and
  `close()` / context manager; chain cycle, out-of-range sector, chain shorter than its size, directory cycle,
  entry cap, bad magic, bad sector shift, truncated file -> `CfbError`, never `IndexError` or a hang.
- [ ] Fixtures: every `tests/fixtures/*.max` (skip when none): same stream names and bytes as `tools/cfb.py`
  (independent implementation), `Scene` and `ClassDirectory3` present.
- [ ] Run `python -I -m unittest discover tests` -> the new tests fail (module missing).

### Task 3: Implementation

- [ ] `maxdrop/reader/cfb.py` per the interface above until the tests pass.
- [ ] Commit: `Add the memory-mapped CFB reader` (body: what and why, `Bead: maxdrop-too.3`).

## Verification

Working directory: the repo root. `S` = this session's scratchpad. Paths of the portable Blenders and the corpus
are in the bead notes (never committed).

1. Plain tests: `python -I -m unittest discover tests` -> exit 0, `OK` (or `OK (skipped=N)` with only the
   known real-tool skips), and the run lists the `unit.test_cfb` and `unit.test_reader_no_bpy` cases
   (`python -I -m unittest discover tests -v 2>&1 | grep -c "unit\."` > 0).
2. Build: `powershell -ExecutionPolicy Bypass -File build.ps1` -> `Built ...` (the zip carries
   `maxdrop/reader/`: `python -I -c "import zipfile,glob;print([n for n in zipfile.ZipFile(glob.glob('dist/*.zip')[0]).namelist() if 'reader' in n])"`).
3. Register smoke (block 3 of build-and-test) on Blender 5.2, 4.2.23, 4.5.16 -> `SMOKE PASSED` each.
4. Import smoke (block 4) on the three versions, no argument (the committed fixtures) -> `IMPORT PASSED`
   (the engine is unchanged; proves the new sub-package does not disturb the add-on).
5. Corpus (local, read-only, results stay in `S`):
   - plain Python `$S\cfb_time.py <scene>`: time `CompoundFile(path)` + `names()` + `open()` of every stream
     (headers only, no full read) -> under 1 s per scene; print counts and timings only.
   - Blender 5.2 headless `$S\cfb_vs_engine.py -- <scene>`: the old engine's `ImportMaxFile` directory names
     (`root.kids`) and the byte length of each stream it reads (`ClassData`, `Config`, `ClassDirectory3`,
     `VideoPostQueue`, `Scene`: what it prints as `reading '<name>'... <len>`) equal the reader's names and
     `len(open(name, decompress=False))`; prints `MATCH` or the differing counts, never names of the scene.
   - Write the two timings into the bead notes (`bd update maxdrop-too.3 --append-notes`).

**Success criteria:** blocks 1-4 pass on all three versions, both corpus scenes `MATCH` and open + list under
1 s.
