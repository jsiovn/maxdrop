# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deterministic fuzzing of the .max reader and of the zip intake, without Blender.

Case k of a seed is a pure function of (SEED, the seed's name, k): a failure names `<seed>:<k>` and replays
anywhere. A .max case mutates a committed fixture (bits and bytes flipped in the header, the FAT, the directory and
the streams the reader opens, the file cut short, chunk sizes and leading counts set to extremes, container bits
toggled, directory entries and header fields bent, FAT entries redirected, sectors swapped) and runs it through what
the operator runs: the pre-flight (summary, Scene, unit), then the reading (Scene, unit, asset table, scene
description with the saved views, the material and texture-map conversion and the swatch note). A seed named
`<fixture>+gzip` (GZIP_SEEDS) is that fixture with its Scene stream rewritten here as gzip members, as 3ds Max's
Compress on Save writes it: a compressed stream is not walked for chunks; its cases bend the deflate bytes and the
gzip framing instead (headers, trailers, block types, member boundaries, members dropped or repeated, the stream
cut, a member that inflates to megabytes). Deflate output depends on the zlib build, so such a seed replays on the
same zlib only. A zip case mutates a scene pack built here (central directory, local headers, end record, names,
sizes, flags, methods, attributes, truncation) and runs list_pack and unpack in a sandbox of its own.

A case passes when it reads (`ok`), is refused with a MaxFileError (`refused`; PackError for a pack), or, for a
.max, fails inside the material stage, which the operator turns into a report line (`materials`: counted, not a
failure). Anything else is `escaped`: a defect. Every case must end within CASE_SECONDS and the process stay under
MEMORY_LIMIT. A pack case also checks the sandbox afterwards: nothing outside the destination, no staging folder.

    python -I tests/unit/fuzz.py max --cases 100000 --jobs 18 --out <results.jsonl> [--minutes 9]
    python -I tests/unit/fuzz.py zip --cases 100000 --jobs 18 --out <results.jsonl>
    python -I tests/unit/fuzz.py summary --out <results.jsonl>
    python -I tests/unit/fuzz.py replay box_poly_standard.max:4711
    python -I tests/unit/fuzz.py max --seeds box_poly_standard.max+gzip --cases 100000 --out <results.jsonl>
    python -I tests/unit/fuzz.py slice --target max --cases 16           # one JSON line: what the plain suite runs

The campaign runs shards of cases in worker processes; a case that runs past CASE_SECONDS ends its worker
(faulthandler) and is recorded as a hang. Results are appended to the --out file, one JSON line per shard, so a
campaign stopped by --minutes resumes where it was. tests/unit/test_fuzz.py and tests/test_intake_fuzz.py run a
bounded slice in the plain test suite.
"""
import argparse
import faulthandler
import glob
import importlib
import json
import os
import random
import shutil
import stat
import struct
import sys
import tempfile
import time
import types
import zipfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
SEED = 20261119
CASE_SECONDS = 5.0
MEMORY_LIMIT = 1 << 30
# One thread for numpy's BLAS: otherwise it reserves buffers per core at import, hundreds of MB on a 20-core
# machine, which the peak memory of a worker would count against MEMORY_LIMIT.
_BLAS_THREADS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")

# A package of its own whose path is maxdrop/: relative imports resolve and maxdrop/__init__.py (bpy) never runs.
_PKG = "maxdrop_fuzz"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg


def _mod(name):
    return importlib.import_module(_PKG + "." + name)


errors = _mod("reader.errors")
cfb = _mod("reader.cfb")
chunks = _mod("reader.chunks")
MaxFileError = errors.MaxFileError

EXTREMES = (0, 1, 2, 3, 4, 5, 6, 7, 8, 13, 14, 15, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFFFF, 0x10000,
            0x7FFFFFFF, 0x80000000, 0x80000006, 0x8000000E, 0xFFFFFFF0, 0xFFFFFFFA, 0xFFFFFFFB, 0xFFFFFFFC,
            0xFFFFFFFD, 0xFFFFFFFE, 0xFFFFFFFF)
BYTES = (0x00, 0x01, 0x7F, 0x80, 0xFE, 0xFF)


def _rng(name, k, seed=SEED):
    return random.Random("%d/%s/%d" % (seed, name, k))  # a str seed hashes with SHA-512: the same in every process


def peak_memory():
    """The peak memory of this process in bytes (the larger of peak working set and peak private bytes on Windows,
    the peak resident set elsewhere); None when the system does not say."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
        c = Counters()
        c.cb = ctypes.sizeof(c)
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return None
        return max(c.PeakWorkingSetSize, c.PeakPagefileUsage)
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


class Escaped(AssertionError):
    """A case that ended in something other than ok / refused: the replay id, the mutation and the exception."""


# --- .max ----------------------------------------------------------------------------------------------------------

_STREAMS = ("Scene", "ClassDirectory3", "ClassDirectory", "DllDirectory", "FileAssetMetaData3", "Config",
            "\x05SummaryInformation", "\x05DocumentSummaryInformation", "SummaryInformation",
            "DocumentSummaryInformation")
_CHUNKED = ("Scene", "ClassDirectory3", "ClassDirectory", "DllDirectory")
# Where flips land: the streams the reader opens, weighted by what parses them.
_REGION_WEIGHTS = {"header": 2, "fat": 1, "directory": 3, "minifat": 1, "Scene": 10, "ClassDirectory3": 3,
                   "ClassDirectory": 3, "DllDirectory": 2, "FileAssetMetaData3": 2, "Config": 1,
                   "SummaryInformation": 2, "DocumentSummaryInformation": 2}
_KINDS = (("flip", 20), ("bytes", 8), ("cut", 5), ("chunk_size", 14), ("container", 5), ("count", 14),
          ("shrink", 10), ("dir", 7), ("header", 4), ("fat", 5), ("swap", 5), ("multi", 5))
_HEADER_FIELDS = ((26, 2), (30, 2), (32, 2), (44, 4), (48, 4), (56, 4), (60, 4), (64, 4), (68, 4), (72, 4),
                  (76, 4), (80, 4))
_DIR_FIELDS = ((66, 1), (68, 4), (72, 4), (76, 4), (116, 4), (120, 4), (124, 4), (64, 2))

# Seeds with a gzip-compressed Scene, built from these fixtures by gzip_scene(); named <fixture>+gzip.
GZIP_SEEDS = ("box_poly_standard.max",)
GZIP_SUFFIX = "+gzip"
_GZIP_PARTS = 3  # members: two boundaries between them
_GZIP_PADDING = 24  # zero bytes after the last member
# The kinds of a seed with a compressed stream: those of _KINDS (chunk kinds reach the streams still walked) and
# these, which aim at the compressed stream's deflate bytes and gzip framing.
_GZIP_KINDS = (("gz_flip", 12), ("gz_header", 7), ("gz_trailer", 6), ("gz_block", 5), ("gz_boundary", 6),
               ("gz_members", 6), ("gz_cut", 7), ("gz_expand", 2))
_GZIP_REWRITES = ("gz_members", "gz_expand")
_GZIP_FLG = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1E, 0xE0, 0xFF)
_EXPAND = (1 << 20, 4 << 20, 16 << 20)  # inflated sizes of an expanding member: well under MEMORY_LIMIT


def gzip_member(data, level=9):
    """One gzip member of data with a fixed header (no flags, mtime 0, XFL 0, OS 0): gzip.compress writes header
    bytes that differ between Python versions."""
    c = zlib.compressobj(level, zlib.DEFLATED, -zlib.MAX_WBITS)
    body = c.compress(data) + c.flush()
    return cfb.GZIP_MAGIC + bytes(7) + body + struct.pack("<II", zlib.crc32(data), len(data) & 0xFFFFFFFF)


def gzip_members(data):
    """([(start, deflate start, deflate end, end)] of the gzip members at the start of data, where the bytes after
    the last one start)."""
    out, at = [], 0
    while data[at:at + 3] == cfb.GZIP_MAGIC and at + 10 <= len(data):
        flg, p = data[at + 3], at + 10
        try:
            if flg & 4:  # FEXTRA
                p += 2 + struct.unpack_from("<H", data, p)[0]
            for bit in (8, 16):  # FNAME, FCOMMENT
                if flg & bit:
                    p = data.index(b"\0", p) + 1
        except (struct.error, ValueError):
            break
        if flg & 2:  # FHCRC
            p += 2
        d = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            d.decompress(data[p:])
        except zlib.error:
            break
        if not d.eof or len(d.unused_data) < 8:
            break
        end = len(data) - len(d.unused_data)
        out.append((at, p, end, end + 8))
        at = end + 8
    return out, at


def _chain_runs(cf, name):
    """(file offset, length) of every sector of the chain of stream name (a stream in regular sectors)."""
    ss = cf.sector_size
    return [((s + 1) * ss, ss) for s in MaxSeed._chain(cf._fat, cf._by_path[name.lower()].start) if s < cf._nsect]


def _dir_entry(cf, raw, name):
    """The file offset of the directory entry of stream name."""
    ss, sid = cf.sector_size, cf._by_path[name.lower()].sid
    sectors = MaxSeed._chain(cf._fat, struct.unpack_from("<I", raw, 48)[0])
    return (sectors[sid // (ss // 128)] + 1) * ss + (sid % (ss // 128)) * 128


def _put(buf, cap, offset, data):
    """data written in place at offset of a stream whose chain covers cap (cut to it)."""
    for o, b in zip(_file_offsets(cap, offset, len(data)), data):
        if o < len(buf):
            buf[o] = b


def _set_size(buf, entry, size):
    if entry + 128 <= len(buf):
        buf[entry + 120:entry + 128] = struct.pack("<Q", size)


def _write_stream(buf, cap, entry, data):
    """data as the whole content of a stream whose chain covers cap (cut to it) and whose directory entry is at
    entry: written in place, the entry's size set to its length, which is returned."""
    data = data[:sum(n for _, n in cap)]
    _put(buf, cap, 0, data)
    _set_size(buf, entry, len(data))
    return len(data)


def gzip_scene(raw):
    """raw with its Scene stream rewritten in place as _GZIP_PARTS gzip members and zero padding (at least 4096
    bytes in all, so that it stays in regular sectors). The chain keeps all its sectors, zeroed past the new size:
    room for cases that grow the stream."""
    buf = bytearray(raw)
    with cfb.CompoundFile(raw) as cf:
        stream = cf.open("Scene")
        if stream.compressed:
            raise ValueError("the Scene stream is compressed already")
        scene = stream.read()
        cap, entry = _chain_runs(cf, "Scene"), _dir_entry(cf, raw, "Scene")
    cuts = [len(scene) * i // _GZIP_PARTS for i in range(_GZIP_PARTS + 1)]
    body = b"".join(gzip_member(scene[a:b]) for a, b in zip(cuts, cuts[1:]))
    body += bytes(max(_GZIP_PADDING, 4096 - len(body)))
    total = sum(n for _, n in cap)
    if len(body) > total:
        raise ValueError("the compressed Scene does not fit its sectors")
    _put(buf, cap, 0, body + bytes(total - len(body)))
    _set_size(buf, entry, len(body))
    return bytes(buf)


class GzipStream:
    """A compressed stream of a seed: its raw bytes, its members (gzip_members), where its padding starts, cap the
    runs of all the sectors of its chain and entry the file offset of its directory entry."""

    def __init__(self, name, data, cap, entry):
        self.name, self.data, self.cap, self.entry = name, data, cap, entry
        self.members, self.padding = gzip_members(data)


def _file_offsets(runs, offset, n):
    """The file offsets of n bytes from offset of a stream made of runs [(file offset, length)]."""
    out, pos = [], 0
    for start, length in runs:
        while n and pos <= offset < pos + length:
            out.append(start + offset - pos)
            offset += 1
            n -= 1
        pos += length
        if not n:
            break
    return out


class MaxSeed:
    """A .max file (a fixture, or one built from it) and where its structures lie in the file. kinds: the mutation
    kinds of its cases."""

    def __init__(self, name, raw):
        self.name, self.raw = name, raw
        with cfb.CompoundFile(self.raw) as cf:
            self.sector_size = ss = cf.sector_size
            self.nsect = (len(self.raw) - 1) // ss
            fat = cf._fat
            self.regions = {"header": [(0, 512)]}
            nfat, first_dir, first_minifat = struct.unpack_from("<I", self.raw, 44)[0], \
                struct.unpack_from("<I", self.raw, 48)[0], struct.unpack_from("<I", self.raw, 60)[0]
            fat_sectors = list(struct.unpack_from("<%dI" % min(nfat, 109), self.raw, 76))
            self.regions["fat"] = [((s + 1) * ss, ss) for s in fat_sectors if s < self.nsect]
            self.fat_entries = [(s + 1) * ss + 4 * i for s in fat_sectors if s < self.nsect for i in range(ss // 4)]
            self.dir_sectors = self._chain(fat, first_dir)
            self.regions["directory"] = [((s + 1) * ss, ss) for s in self.dir_sectors]
            self.regions["minifat"] = [((s + 1) * ss, ss) for s in self._chain(fat, first_minifat)]
            self.dir_entries = []
            for s in self.dir_sectors:
                for i in range(ss // 128):
                    at = (s + 1) * ss + i * 128
                    if self.raw[at + 66] in (1, 2, 5):
                        self.dir_entries.append(at)
            self.stream_runs, self.gzip = {}, {}
            for name in _STREAMS:
                if cf.exists(name):
                    raw_stream = cf.open(name, decompress=False)
                    self.stream_runs[name] = raw_stream.runs
                    self.regions[name.lstrip("\x05")] = list(raw_stream.runs)
                    if raw_stream.compressed and raw_stream.size >= cfb._CUTOFF:
                        self.gzip[name] = GzipStream(name, raw_stream.read(), _chain_runs(cf, name),
                                                     _dir_entry(cf, self.raw, name))
            self.heads, self.counts = [], []  # file offsets of 4-byte fields: chunk size fields, leading u32s
            self.leaves = []  # (stream, offset, payload size, id) of the leaves with a 6-byte header
            for name in _CHUNKED:
                # The chunk offsets of a compressed stream lie in its inflated bytes, not in the file.
                if name in self.stream_runs and not cf.open(name, decompress=False).compressed:
                    self._walk(name, cf.open(name))
        self.regions = {k: v for k, v in self.regions.items() if v}
        self.gzip = {k: g for k, g in self.gzip.items() if g.members}
        self.kinds = _KINDS[:-1] + _GZIP_KINDS + _KINDS[-1:] if self.gzip else _KINDS
        # A stream rewrite starts from the seed's bytes and members: alone, never among the kinds of a multi case.
        self.multi_kinds = tuple(kw for kw in self.kinds[:-1] if kw[0] not in _GZIP_REWRITES)

    @staticmethod
    def _chain(fat, start):
        out, seen = [], set()
        while start < len(fat) and start not in seen:
            seen.add(start)
            out.append(start)
            start = fat[start]
        return out

    def _walk(self, name, stream):
        runs = self.stream_runs[name]
        try:
            stack = list(chunks.index(stream))
        except MaxFileError:
            return
        while stack:
            c = stack.pop()
            offs = _file_offsets(runs, c.offset + 2, 4)
            if len(offs) == 4:
                self.heads.append((name, offs))
            if c.container:
                try:
                    stack.extend(c.children)
                except MaxFileError:
                    pass
            else:
                if c.header == 6 and c.payload_size >= 6:
                    self.leaves.append((name, c.offset, c.payload_size, c.id))
                if c.payload_size < 4:
                    continue
                at = c.payload_offset + 4 * random.Random(c.offset).randrange(max(1, min(c.payload_size // 4, 4)))
                offs = _file_offsets(runs, at, 4)
                if len(offs) == 4:
                    self.counts.append((name, offs))


def _pick(rng, weighted):
    total = sum(w for _, w in weighted)
    r = rng.uniform(0, total)
    for item, w in weighted:
        r -= w
        if r <= 0:
            return item
    return weighted[-1][0]


def _region_offset(rng, runs):
    total = sum(n for _, n in runs)
    r = rng.randrange(total)
    for start, n in runs:
        if r < n:
            return start + r
        r -= n
    raise AssertionError("empty region")


def _put32(buf, offsets, value):
    for off, b in zip(offsets, struct.pack("<I", value & 0xFFFFFFFF)):
        if off < len(buf):
            buf[off] = b


def _extreme(rng, old=None):
    if old is not None and rng.random() < 0.25:
        return (old + rng.choice((-7, -6, -1, 1, 6, 7, 1 << 16, 1 << 24))) & 0xFFFFFFFF
    if rng.random() < 0.15:
        return rng.getrandbits(32)
    return rng.choice(EXTREMES)


_EXPANDED = {}


def _expanded(n, value):
    """A gzip member that inflates to n bytes of value (cached: built once per process)."""
    if (n, value) not in _EXPANDED:
        _EXPANDED[(n, value)] = gzip_member(bytes([value]) * n)
    return _EXPANDED[(n, value)]


def _mutate_gzip(seed, buf, rng, kind):
    g = seed.gzip[rng.choice(sorted(seed.gzip))]
    if kind == "gz_flip":
        offs = []
        for _ in range(rng.randint(1, 8)):
            _, d0, d1, _ = rng.choice(g.members)
            offs.append(rng.randrange(d0, d1))
        for o in offs:
            at = _file_offsets(g.cap, o, 1)[0]
            buf[at] ^= 1 << rng.randrange(8)
        return "gz_flip %s %s" % (g.name, offs)
    if kind == "gz_header":
        m = rng.randrange(len(g.members))
        field = rng.choice((0, 1, 2, 3, 3, 3, 4, 8, 9))
        if field == 4:  # MTIME
            data = struct.pack("<I", _extreme(rng))
        elif field == 3:  # FLG: FTEXT, FHCRC, FEXTRA, FNAME, FCOMMENT, the reserved bits
            data = bytes([rng.choice(_GZIP_FLG + (rng.randrange(256),))])
        elif field == 2:  # CM
            data = bytes([rng.choice((0, 7, 9, 0xFF, rng.randrange(256)))])
        else:  # ID1, ID2, XFL, OS
            data = bytes([g.data[g.members[m][0] + field] ^ rng.randrange(1, 256)])
        _put(buf, g.cap, g.members[m][0] + field, data)
        return "gz_header %s member %d +%d=%s" % (g.name, m, field, data.hex())
    if kind == "gz_trailer":
        m = rng.randrange(len(g.members))
        at = g.members[m][2] + rng.choice((0, 4))  # CRC32, ISIZE
        value = _extreme(rng, struct.unpack_from("<I", g.data, at)[0])
        _put(buf, g.cap, at, struct.pack("<I", value))
        return "gz_trailer %s member %d @%d=0x%X" % (g.name, m, at, value)
    if kind == "gz_block":
        m = rng.randrange(len(g.members))
        _, d0, d1, _ = g.members[m]
        if rng.random() < 0.5:  # BFINAL and BTYPE of the first block, the reserved type 3 among them
            at = d0
            value = (g.data[d0] & 0xF8) | rng.randrange(8)
            if value == g.data[d0]:
                value ^= 1
        else:  # a bit of the block header and the code lengths that follow it
            at = rng.randrange(d0, min(d1, d0 + 16))
            value = g.data[at] ^ (1 << rng.randrange(8))
        _put(buf, g.cap, at, bytes([value]))
        return "gz_block %s member %d @%d=0x%02X" % (g.name, m, at, value)
    if kind == "gz_boundary":
        if len(g.members) > 1 and rng.random() < 0.6:  # a later member no longer starts one: read as padding
            m = rng.randrange(1, len(g.members))
            at = g.members[m][0] + rng.randrange(3)
            data = bytes([g.data[at] ^ rng.randrange(1, 256)])
        else:  # a member started in the padding
            at = g.padding
            junk = bytes(rng.getrandbits(8) for _ in range(rng.choice((0, 1, 7, 12))))
            data = cfb.GZIP_MAGIC[:rng.randint(1, 3)] + junk
        _put(buf, g.cap, at, data)
        return "gz_boundary %s @%d=%s" % (g.name, at, data.hex())
    if kind == "gz_members":
        parts = [g.data[s:e] for s, _, _, e in g.members]
        op = rng.choice(("drop", "dup", "swap", "garbage"))
        if op == "drop":
            del parts[rng.randrange(len(parts))]
        elif op == "dup":
            parts.insert(rng.randrange(len(parts) + 1), parts[rng.randrange(len(parts))])
        elif op == "swap" and len(parts) > 1:
            i, j = rng.sample(range(len(parts)), 2)
            parts[i], parts[j] = parts[j], parts[i]
        else:
            op = "garbage"
            junk = bytes(rng.getrandbits(8) for _ in range(rng.choice((1, 7, 10, 64))))
            parts.append(rng.choice((junk, cfb.GZIP_MAGIC + junk)))
        data = b"".join(parts) + g.data[g.padding:]
        size = _write_stream(buf, g.cap, g.entry, data.ljust(len(g.data), b"\0"))  # shorter: more zero padding
        return "gz_members %s %s size %d" % (g.name, op, size)
    if kind == "gz_cut":
        s, d0, d1, e = rng.choice(g.members)
        point = rng.choice((rng.randrange(s, d0), rng.randrange(d0, d1), rng.randrange(d1, e), e,
                            rng.randrange(cfb._CUTOFF)))
        if rng.random() < 0.6:  # the stream ends there (below 4096 bytes the reader looks in the mini stream)
            _set_size(buf, g.entry, point)
            return "gz_cut %s size %d" % (g.name, point)
        point = min(point, g.padding - 5)  # the padding and the last ISIZE's top bytes are zero already
        _put(buf, g.cap, point, bytes(len(g.data) - point))
        return "gz_cut %s zeroed from %d" % (g.name, point)
    if kind == "gz_expand":
        m = rng.randrange(len(g.members))
        n, value = rng.choice(_EXPAND), rng.choice((0x00, 0xFF, 0x20))
        parts = [g.data[s:e] for s, _, _, e in g.members]
        parts[m] = _expanded(n, value)
        size = _write_stream(buf, g.cap, g.entry, b"".join(parts) + g.data[g.padding:])
        return "gz_expand %s member %d %d x 0x%02X size %d" % (g.name, m, n, value, size)
    raise ValueError(kind)


def _mutate_max(seed, buf, rng, kind):
    if kind.startswith("gz_"):
        return _mutate_gzip(seed, buf, rng, kind)
    ss = seed.sector_size
    if kind == "flip":
        region = _pick(rng, [(r, _REGION_WEIGHTS.get(r, 1)) for r in seed.regions])
        offs = [_region_offset(rng, seed.regions[region]) for _ in range(rng.randint(1, 8))]
        for off in offs:
            buf[off] ^= 1 << rng.randrange(8)
        return "flip %s %s" % (region, offs)
    if kind == "bytes":
        region = _pick(rng, [(r, _REGION_WEIGHTS.get(r, 1)) for r in seed.regions])
        offs = [_region_offset(rng, seed.regions[region]) for _ in range(rng.randint(1, 4))]
        for off in offs:
            buf[off] = rng.choice(BYTES) if rng.random() < 0.7 else rng.randrange(256)
        return "bytes %s %s" % (region, offs)
    if kind == "cut":
        if rng.random() < 0.5:
            region = rng.choice(list(seed.regions))
            n = _region_offset(rng, seed.regions[region])
        else:
            n = rng.randrange(len(buf))
        del buf[n:]
        return "cut %d" % n
    if kind in ("chunk_size", "container"):
        if not seed.heads:
            return _mutate_max(seed, buf, rng, "flip")
        name, offs = rng.choice(seed.heads)
        old = struct.unpack("<I", bytes(seed.raw[o] for o in offs))[0]
        value = old ^ 0x80000000 if kind == "container" else _extreme(rng, old)
        _put32(buf, offs, value)
        return "%s %s@%d=0x%X" % (kind, name, offs[0], value)
    if kind == "count":
        if not seed.counts:
            return _mutate_max(seed, buf, rng, "flip")
        name, offs = rng.choice(seed.counts)
        old = struct.unpack("<I", bytes(seed.raw[o] for o in offs))[0]
        value = _extreme(rng, old)
        _put32(buf, offs, value)
        return "count %s@%d=0x%X" % (name, offs[0], value)
    if kind == "shrink":
        # A record cut short in place: the leaf keeps n bytes of its payload and the rest becomes a sibling chunk
        # (an unknown id, or the leaf's own), so every container around it keeps its size.
        if not seed.leaves:
            return _mutate_max(seed, buf, rng, "flip")
        name, offset, size, cid = rng.choice(seed.leaves)
        n = rng.choice((0, 1, 2, 3, 4, rng.randrange(size - 5), size // 2, size - 7 if size > 6 else 0, size - 6))
        n = max(0, min(n, size - 6))
        filler = rng.choice((0x0000, 0xFFFF, cid, rng.randrange(1 << 16)))
        runs = seed.stream_runs[name]
        offs = _file_offsets(runs, offset, 6 + n + 6)
        if len(offs) == 12 + n:
            new = struct.pack("<HI", cid, 6 + n)
            for o, b in zip(offs[:6], new):
                buf[o] = b
            for o, b in zip(offs[6 + n:], struct.pack("<HI", filler, size - n)):
                buf[o] = b
        return "shrink %s@%d %d->%d +%04X" % (name, offset, size, n, filler)
    if kind == "dir":
        at = rng.choice(seed.dir_entries)
        field, size = rng.choice(_DIR_FIELDS)
        if size == 4:
            value = rng.choice((rng.randrange(seed.nsect + 2), _extreme(rng)))
            _put32(buf, range(at + field, at + field + 4), value)
        else:
            value = rng.randrange(1 << (8 * size))
            buf[at + field:at + field + size] = value.to_bytes(size, "little")
        return "dir %d+%d=0x%X" % (at, field, value)
    if kind == "header":
        field, size = rng.choice(_HEADER_FIELDS)
        if size == 4:
            value = rng.choice((rng.randrange(seed.nsect + 2), _extreme(rng)))
            _put32(buf, range(field, field + 4), value)
        else:
            value = rng.choice((0, 1, 3, 4, 6, 9, 12, 16, 0xFFFF, rng.randrange(1 << 16)))
            buf[field:field + 2] = value.to_bytes(2, "little")
        return "header %d=0x%X" % (field, value)
    if kind == "fat":
        at = rng.choice(seed.fat_entries)
        value = rng.choice((0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFC, 0, rng.randrange(seed.nsect + 2),
                            _extreme(rng)))
        _put32(buf, range(at, at + 4), value)
        return "fat %d=0x%X" % (at, value)
    if kind == "swap":
        if rng.random() < 0.5 and "Scene" in seed.stream_runs:
            a = _region_offset(rng, seed.stream_runs["Scene"]) // ss
        else:
            a = rng.randrange(1, seed.nsect + 1)
        b = rng.randrange(1, seed.nsect + 1)
        a, b = max(a, 1), max(b, 1)
        if a != b and (max(a, b) + 1) * ss <= len(buf):
            sa, sb = bytes(buf[a * ss:(a + 1) * ss]), bytes(buf[b * ss:(b + 1) * ss])
            buf[a * ss:(a + 1) * ss], buf[b * ss:(b + 1) * ss] = sb, sa
        return "swap sectors %d %d" % (a - 1, b - 1)
    raise ValueError(kind)


def max_case(seed, k, base=SEED):
    """(the bytes of case k of seed, what was done to them)."""
    rng = _rng(seed.name, k, base)
    buf = bytearray(seed.raw)
    kind = _pick(rng, seed.kinds)
    if kind == "multi":
        kinds = [_pick(rng, seed.multi_kinds) for _ in range(rng.randint(2, 4))]
        kinds.sort(key=lambda x: x == "cut")  # a cut last: the other offsets point into the whole file
        spec = "; ".join(_mutate_max(seed, buf, rng, kd) for kd in kinds)
    else:
        spec = _mutate_max(seed, buf, rng, kind)
    return bytes(buf), spec


class _Reader:
    """The reader path of the operator (ops._preflight, then ops._read_scene) on bytes, without Blender. Not its net
    for a reader defect: what ops reports as not imported for a TypeError, KeyError or AttributeError (ops._DEFECTS)
    escapes here."""

    def __init__(self):
        self.metadata = _mod("reader.metadata")
        self.scene = _mod("reader.scene")
        self.units = _mod("reader.units")
        self.assets = _mod("reader.assets")
        self.rmaterials = _mod("reader.materials")
        self.convert = _mod("convert.scene")
        self.cameras = _mod("convert.cameras")
        self.colors = _mod("convert.colors")
        self.materials = _mod("convert.materials")
        self.texmaps = _mod("convert.texmaps")
        self.textures = _mod("convert.textures")

    def read(self, data, folder):
        """'ok', 'refused' or ('materials', the exception); anything else raises."""
        try:
            with cfb.CompoundFile(data) as cf:  # the pre-flight line
                try:
                    self.metadata.read(cf)
                except self.metadata.MetadataError:
                    pass
                sc = self.scene.Scene.from_file(cf)
                self.units.system_unit(sc)
                len(sc.node_indices)
                sc.strings.wide, getattr(sc.strings, "codec", None)  # what the line says of an 8-bit file
            del sc
            with cfb.CompoundFile(data) as cf:  # the reading
                sc = self.scene.Scene.from_file(cf, encoding="AUTO")
                unit = self.units.system_unit(sc)
                meters = unit.meters if unit is not None else 1.0
                table = self.assets.AssetTable.from_file(cf)
                desc = self.convert.describe(sc, meters, unit, convert_modifiers=True, assets=table,
                                             views=self.cameras.saved_views(cf))
                outcome = "ok"
                try:  # the material stage: ops catches any Exception here
                    graph = self.rmaterials.MaterialGraph(sc)
                    index = self.textures.TextureIndex(os.path.join(folder, "scene.max"), (), scene_subfolders=True)
                    swatches = self.colors.of_scene(sc)
                    tex = self.texmaps.TexmapConverter(graph, table, textures=index, swatches=swatches)
                    conv = self.materials.MaterialConverter(graph, texmaps=tex, swatches=swatches)
                    self.materials.assign(desc, self.materials.node_materials(sc, desc), conv)
                except Exception as e:
                    outcome = ("materials", e)
                if desc.lights:
                    self.colors.of_scene(sc).note
                del sc, desc, table
        except MaxFileError:
            return "refused"
        return outcome


_READER = None


def run_max(seed, k, folder, base=SEED):
    """(outcome, seconds) of case k; Escaped when the case escapes."""
    global _READER
    if _READER is None:
        _READER = _Reader()
    data, spec = max_case(seed, k, base)
    start = time.perf_counter()
    try:
        outcome = _READER.read(data, folder)
    except Exception as e:
        raise Escaped("%s:%d (%s): %s: %s" % (seed.name, k, spec, type(e).__name__, e)) from e
    return outcome, time.perf_counter() - start


# --- zip -----------------------------------------------------------------------------------------------------------

_ZIP_KINDS = (("flip", 20), ("field", 25), ("names", 15), ("cut", 6), ("method", 8), ("flags", 8), ("attr", 6),
              ("eocd", 8), ("multi", 4))
_RISKY_NAMES = ("../evil.jpg", "..\\evil.jpg", "/abs.png", "\\abs.png", "C:\\x\\a.jpg", "C:a.jpg", "\\\\host\\s\\a.jpg",
                "a/../../b.png", "con.jpg", "AUX", "nul.max", "COM1.tga", "lpt9.png", "a:b.jpg", "a\x00b.jpg",
                "x\x01.png", "dots....", "space .jpg ", "tail.", "", ".", "..", "/", "a/", "maps/./c.jpg",
                "\u202egpj.exe", "\uff0e\uff0e\uff0fx.jpg", "x" * 300 + ".jpg", "\ud800.jpg", "scene.MAX",
                "sub/scene.max", "Scene Pack/scene.max", "a\\b\\c.ies", "COM\u00b9.png", "\u00e9t\u00e9.jpg",
                "\u6587\u4ef6.png", "?.jpg", "*.png", "a|b.jpg", "<x>.png", "q\".jpg", "trail/ ")
_ZIP_FIELDS_LOCAL = ((4, 2), (6, 2), (8, 2), (14, 4), (18, 4), (22, 4), (26, 2), (28, 2))
_ZIP_FIELDS_CENTRAL = ((4, 2), (6, 2), (8, 2), (10, 2), (16, 4), (20, 4), (24, 4), (28, 2), (30, 2), (32, 2),
                       (34, 2), (36, 2), (38, 4), (42, 4))
_ZIP_FIELDS_EOCD = ((4, 2), (6, 2), (8, 2), (10, 2), (12, 4), (16, 4), (20, 2))


def _zip_bytes(files):
    """A zip of (name, data, compression, external_attr) built in memory with fixed dates."""
    import io
    import warnings
    out = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(out, "w") as z:
        warnings.simplefilter("ignore")  # a duplicate name is a case, not a mistake
        for name, data, method, attr in files:
            info = zipfile.ZipInfo("placeholder", date_time=(2020, 1, 1, 0, 0, 0))
            info.filename = name
            info.compress_type = method
            info.external_attr = attr
            z.writestr(info, data)
    return out.getvalue()


def _payload(rng, n):
    return bytes(rng.getrandbits(8) for _ in range(n // 2)) + b"MaxDrop fuzz " * (n // 26)


class ZipSeed:
    """A scene pack built here: its files and where its structures lie."""

    def __init__(self, name):
        self.name = name
        rng = random.Random(name)
        regular = 0o100644 << 16
        files = [("Scene Pack/scene.max", _payload(rng, 4000), zipfile.ZIP_DEFLATED, regular),
                 ("Scene Pack/maps/", b"", zipfile.ZIP_STORED, (0o40755 << 16) | 0x10),
                 ("Scene Pack/maps/wood.jpg", _payload(rng, 1500), zipfile.ZIP_STORED, regular),
                 ("Scene Pack/maps/sub/stone.png", _payload(rng, 2000), zipfile.ZIP_DEFLATED, regular),
                 ("Scene Pack/light.ies", b"IESNA:LM-63-2002\n" * 20, zipfile.ZIP_DEFLATED, regular),
                 ("readme.txt", b"read me\n" * 30, zipfile.ZIP_DEFLATED, regular)]
        if name == "zip:two":
            files += [("Other/second.max", _payload(rng, 3000), zipfile.ZIP_DEFLATED, regular),
                      ("Other/maps/wood.jpg", _payload(rng, 800), zipfile.ZIP_STORED, regular)]
        self.files = files
        self.raw = _zip_bytes(files)
        self._index()

    def _index(self):
        raw = self.raw
        eocd = raw.rindex(b"PK\x05\x06")
        self.eocd = eocd
        count, size, start = struct.unpack_from("<HII", raw, eocd + 10)
        self.central, self.local, self.names = [], [], []
        pos = start
        for _ in range(count):
            nlen, xlen, clen = struct.unpack_from("<HHH", raw, pos + 28)
            local = struct.unpack_from("<I", raw, pos + 42)[0]
            self.central.append(pos)
            self.local.append(local)
            self.names.append((pos + 46, nlen))
            lnlen = struct.unpack_from("<H", raw, local + 26)[0]
            self.names.append((local + 30, lnlen))
            pos += 46 + nlen + xlen + clen
        self.regions = {"local": [(0, start)], "central": [(start, size)], "eocd": [(eocd, len(raw) - eocd)]}


def _mutate_zip(seed, buf, rng, kind):
    if kind == "flip":
        region = _pick(rng, [("local", 2), ("central", 5), ("eocd", 1)])
        offs = [_region_offset(rng, seed.regions[region]) for _ in range(rng.randint(1, 6))]
        for off in offs:
            buf[off] ^= 1 << rng.randrange(8)
        return "flip %s %s" % (region, offs)
    if kind == "field":
        if rng.random() < 0.6:
            at, (field, size) = rng.choice(seed.central), rng.choice(_ZIP_FIELDS_CENTRAL)
        else:
            at, (field, size) = rng.choice(seed.local), rng.choice(_ZIP_FIELDS_LOCAL)
        value = _extreme(rng) if size == 4 else rng.choice((0, 1, 0x7FFF, 0x8000, 0xFFFF, rng.randrange(1 << 16)))
        buf[at + field:at + field + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
        return "field %d+%d=0x%X" % (at, field, value)
    if kind == "eocd":
        field, size = rng.choice(_ZIP_FIELDS_EOCD)
        value = _extreme(rng) if size == 4 else rng.choice((0, 1, 2, 0xFFFF, rng.randrange(1 << 16)))
        at = seed.eocd + field
        buf[at:at + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
        return "eocd +%d=0x%X" % (field, value)
    if kind == "cut":
        n = rng.randrange(len(buf))
        del buf[n:]
        return "cut %d" % n
    if kind == "method":
        at = rng.choice(seed.central + seed.local)
        value = rng.choice((0, 1, 6, 8, 9, 12, 14, 19, 93, 95, 98, 99, 0xFFFF))
        field = at + (10 if at in seed.central else 8)
        buf[field:field + 2] = value.to_bytes(2, "little")
        return "method %d=%d" % (field, value)
    if kind == "flags":
        at = rng.choice(seed.central + seed.local)
        field = at + (8 if at in seed.central else 6)
        value = rng.choice((0x1, 0x8, 0x20, 0x40, 0x800, 0x2000, 0xFFFF, rng.randrange(1 << 16)))
        buf[field:field + 2] = value.to_bytes(2, "little")
        return "flags %d=0x%X" % (field, value)
    if kind == "attr":
        at = rng.choice(seed.central)
        value = rng.choice((0o120777 << 16, 0o20644 << 16, 0o60644 << 16, 0o10644 << 16, 0o140644 << 16, 0x10,
                            0x400, 0x410, 0xFFFFFFFF, 0))
        _put32(buf, range(at + 38, at + 42), value)
        return "attr %d=0x%X" % (at + 38, value)
    if kind == "names":
        files = list(seed.files)
        picks = []
        for _ in range(rng.randint(1, 3)):
            i = rng.randrange(len(files))
            name, data, method, attr = files[i]
            new = rng.choice(_RISKY_NAMES)
            if rng.random() < 0.5 and "/" not in new and "\\" not in new:
                new = name.rsplit("/", 1)[0] + "/" + new
            files[i] = (new, data, method, attr)
            picks.append(new)
        if rng.random() < 0.3:  # a name twice
            files.append(files[rng.randrange(len(files))])
        try:
            buf[:] = _zip_bytes(files)
        except (UnicodeEncodeError, ValueError, struct.error):
            return "names %r (not writable)" % picks
        return "names %r" % picks
    raise ValueError(kind)


def zip_case(seed, k, base=SEED):
    rng = _rng(seed.name, k, base)
    buf = bytearray(seed.raw)
    kind = _pick(rng, _ZIP_KINDS)
    if kind == "multi":
        kinds = [_pick(rng, [kw for kw in _ZIP_KINDS[:-1] if kw[0] not in ("names", "cut")])
                 for _ in range(rng.randint(2, 4))]
        spec = "; ".join(_mutate_zip(seed, buf, rng, kd) for kd in kinds)
    else:
        spec = _mutate_zip(seed, buf, rng, kind)
    return bytes(buf), spec


_ARCHIVE = None


def _archive():
    global _ARCHIVE
    if _ARCHIVE is None:
        _ARCHIVE = _mod("intake.archive")
        for k in (_ARCHIVE.KIND_RAR, _ARCHIVE.KIND_7Z):  # no program is ever started
            _ARCHIVE._BACKENDS.pop(k, None)
    return _ARCHIVE


def _remove(path):
    def retry(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    for _ in range(5):
        shutil.rmtree(path, onerror=retry)
        if not os.path.exists(path):
            return
        time.sleep(0.05)
    raise AssertionError("could not remove %s" % path)


def _tree(folder):
    out = []
    for parent, dirs, files in os.walk(folder):
        rel = os.path.relpath(parent, folder)
        out += [os.path.normpath(os.path.join(rel, d)) + os.sep for d in dirs]
        out += [os.path.normpath(os.path.join(rel, f)) for f in files]
    return sorted(out)


def read_zip(data, sandbox):
    """'ok' or 'refused' for one pack in sandbox (an empty folder); anything else raises. Checks afterwards that
    nothing was written outside sandbox/out and that no staging folder is left."""
    archive = _archive()
    pack, out = os.path.join(sandbox, "pack.zip"), os.path.join(sandbox, "out")
    os.mkdir(out)
    with open(pack, "wb") as f:
        f.write(data)
    outcome, result = "ok", None
    try:
        listing = archive.list_pack(pack)
        if listing.scenes:
            result = archive.unpack(pack, listing.scenes[0], out)
    except archive.PackError:
        outcome = "refused"
    if result is not None and not (os.path.isfile(result.max_path) and os.path.commonpath(
            [os.path.abspath(result.max_path), os.path.abspath(out)]) == os.path.abspath(out)):
        raise AssertionError("unpacked, but its scene is not in the destination: %r" % result.max_path)
    entries = _tree(sandbox)
    stray = [p for p in entries if p not in ("pack.zip", "out" + os.sep) and not p.startswith("out" + os.sep)]
    if stray:
        raise AssertionError("written outside the destination: %r" % stray)
    staging = [p for p in entries if os.path.basename(p.rstrip(os.sep)).startswith(
        (archive.STAGING_PREFIX, archive.RECLAIM_PREFIX))]
    if staging:
        raise AssertionError("staging left behind: %r" % staging)
    for p in entries:
        if p.startswith("out" + os.sep) and not p.endswith(os.sep):
            depth = p.count(os.sep)
            if depth not in (2, 3):  # out/<pack>/<file>, or out/<pack>/<scene>/<file> for a pack of several scenes
                raise AssertionError("a file outside the flat pack folder: %r" % p)
    return outcome


def run_zip(seed, k, folder, base=SEED):
    """(outcome, seconds) of pack case k in a sandbox under folder; Escaped when the case escapes."""
    data, spec = zip_case(seed, k, base)
    sandbox = os.path.join(folder, "case")
    os.mkdir(sandbox)
    start = time.perf_counter()
    try:
        outcome = read_zip(data, sandbox)
    except Exception as e:
        raise Escaped("%s:%d (%s): %s: %s" % (seed.name, k, spec, type(e).__name__, e)) from e
    finally:
        seconds = time.perf_counter() - start
        _remove(sandbox)
    if os.listdir(folder):
        raise Escaped("%s:%d (%s): left %r beside its sandbox" % (seed.name, k, spec, os.listdir(folder)))
    return outcome, seconds


ZIP_SEEDS = ("zip:one", "zip:two")


def seed_names(target):
    """The names of the seeds of target: the fixtures and their gzip variants, or the packs."""
    if target == "max":
        names = [os.path.basename(p) for p in FIXTURES]
        return names + [n + GZIP_SUFFIX for n in GZIP_SEEDS if n in names]
    return list(ZIP_SEEDS)


def max_seed(name):
    fixture = name[:-len(GZIP_SUFFIX)] if name.endswith(GZIP_SUFFIX) else name
    with open(os.path.join(ROOT, "tests", "fixtures", fixture), "rb") as f:
        raw = f.read()
    return MaxSeed(name, gzip_scene(raw) if fixture != name else raw)


def seeds(target, names=None):
    picked = [n for n in seed_names(target) if names is None or n in names]
    if target == "max":
        return [max_seed(n) for n in picked]
    return [ZipSeed(n) for n in picked]


def run_case(target, seed, k, folder, base=SEED):
    return (run_max if target == "max" else run_zip)(seed, k, folder, base)


# --- campaign ------------------------------------------------------------------------------------------------------

def run_range(target, seed, start, stop, current=None, announce=False):
    """Cases [start, stop) of seed, each under the faulthandler watchdog (a case past CASE_SECONDS ends the
    process with its stack): {"counts", "materials", "escapes", "slowest", "slowest_case"}. current: a
    multiprocessing.Value told the case being run."""
    folder = tempfile.mkdtemp(prefix="maxdrop-fuzz-")
    counts, materials, escapes = {}, {}, []
    slowest = (0.0, None)
    try:
        for k in range(start, stop):
            if current is not None:
                current.value = k
            if announce:  # the last line before a faulthandler stack names the case that hung
                sys.stderr.write("%s:%d\n" % (seed.name, k))
                sys.stderr.flush()
            faulthandler.dump_traceback_later(CASE_SECONDS, exit=True)
            try:
                outcome, seconds = run_case(target, seed, k, folder)
            except Escaped as e:
                outcome, seconds = "escaped", 0.0
                if len(escapes) < 50:
                    escapes.append(str(e)[:600])
            finally:
                faulthandler.cancel_dump_traceback_later()
            if isinstance(outcome, tuple):
                kind = type(outcome[1]).__name__
                materials[kind] = materials.get(kind, 0) + 1
                outcome = "materials"
            counts[outcome] = counts.get(outcome, 0) + 1
            if seconds > slowest[0]:
                slowest = (seconds, k)
    finally:
        _remove(folder)
    return {"counts": counts, "materials": materials, "escapes": escapes, "slowest": slowest[0],
            "slowest_case": slowest[1]}


def run_slice(target, cases):
    """Cases [0, cases) of every seed of target in this process: the summed counts, the escapes, the slowest case
    and this process's peak memory, for the plain suite (which runs it in a child process of its own, so that the
    peak is the slice's alone)."""
    total = {"counts": {}, "materials": {}, "escapes": [], "slowest": 0.0, "slowest_case": None}
    for seed in seeds(target):
        r = run_range(target, seed, 0, cases, announce=True)
        for key in ("counts", "materials"):
            for k, v in r[key].items():
                total[key][k] = total[key].get(k, 0) + v
        total["escapes"] += r["escapes"]
        if r["slowest"] >= total["slowest"]:
            total["slowest"], total["slowest_case"] = r["slowest"], "%s:%s" % (seed.name, r["slowest_case"])
    total["peak_memory"] = peak_memory()
    return total


def _worker(target, name, start, stop, current, results):
    r = run_range(target, seeds(target, {name})[0], start, stop, current)
    r.update({"target": target, "seed": name, "start": start, "stop": stop, "peak_memory": peak_memory()})
    results.put(r)


def _covered(out):
    """{(target, seed): [(start, stop)]}: the case ranges the --out file already holds (a shard split by a hang
    is held as its pieces)."""
    done = {}
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                done.setdefault((r["target"], r["seed"]), []).append((r["start"], r["stop"]))
    return done


def _missing(ranges, start, stop):
    """The pieces of [start, stop) that ranges do not cover."""
    out, at = [], start
    for a, b in sorted(ranges):
        if b <= at or a >= stop:
            continue
        if a > at:
            out.append((at, a))
        at = max(at, b)
    if at < stop:
        out.append((at, stop))
    return out


def _write(out, record):
    with open(out, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def campaign(target, cases, jobs, out, shard, minutes, names=None, first=0):
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    all_names = seed_names(target)
    if names:
        all_names = [n for n in all_names if n in names]
    covered = _covered(out)
    todo = [(n, a, b) for s in range(first, cases, shard) for n in all_names
            for a, b in _missing(covered.get((target, n), ()), s, min(s + shard, cases))]
    for name in _BLAS_THREADS:  # spawned workers inherit it: numpy then reserves no buffers per core
        os.environ[name] = "1"
    results = ctx.Queue()
    running = {}  # process -> (shard, current)
    deadline = time.time() + 60 * minutes if minutes else None
    finished = 0
    pending = {}
    while todo or running:
        while todo and len(running) < jobs and (deadline is None or time.time() < deadline):
            name, start, stop = todo.pop(0)
            current = ctx.Value("q", start)
            p = ctx.Process(target=_worker, args=(target, name, start, stop, current, results), daemon=True)
            p.start()
            running[p] = ((name, start, stop), current)
        if not running:
            break
        try:
            r = results.get(timeout=0.5)
            pending[(r["seed"], r["start"], r["stop"])] = r
        except Exception:
            pass
        for p in [p for p in running if not p.is_alive()]:
            (name, start, stop), current = running[p]
            key = (name, start, stop)
            if p.exitcode == 0:
                r = pending.pop(key, None)
                if r is None:
                    t = time.time() + 30
                    while key not in pending and time.time() < t:
                        try:
                            r2 = results.get(timeout=0.5)
                            pending[(r2["seed"], r2["start"], r2["stop"])] = r2
                        except Exception:
                            pass
                    r = pending.pop(key, None)
                if r is None:  # ended cleanly without a result: recorded, never run again on its own
                    r = {"target": target, "seed": name, "start": start, "stop": stop,
                         "counts": {"lost": stop - start}, "materials": {},
                         "escapes": ["%s:%d-%d: worker ended without a result" % (name, start, stop)],
                         "slowest": 0.0, "slowest_case": None, "peak_memory": None}
                _write(out, r)
                finished += 1
            else:
                k = current.value
                _write(out, {"target": target, "seed": name, "start": k, "stop": k + 1, "counts": {"hang": 1},
                             "materials": {}, "escapes": ["%s:%d: worker ended with code %s (over %.0f s, or a crash)"
                                                          % (name, k, p.exitcode, CASE_SECONDS)],
                             "slowest": CASE_SECONDS, "slowest_case": k, "peak_memory": None})
                if start < k:
                    todo.insert(0, (name, start, k))
                if k + 1 < stop:
                    todo.insert(0, (name, k + 1, stop))
            p.join()
            del running[p]
        if deadline is not None and time.time() >= deadline and not running:
            break
    print("%d shards done, %d left" % (finished, len(todo)))
    return len(todo)


def summary(out):
    totals, per_seed, escapes, materials = {}, {}, [], {}
    slowest, peak = (0.0, None), 0
    with open(out, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            s = per_seed.setdefault((r["target"], r["seed"]), {})
            for k, v in r["counts"].items():
                totals[k] = totals.get(k, 0) + v
                s[k] = s.get(k, 0) + v
            for k, v in r["materials"].items():
                materials[k] = materials.get(k, 0) + v
            escapes += r["escapes"]
            if r["slowest"] > slowest[0]:
                slowest = (r["slowest"], "%s:%s" % (r["seed"], r["slowest_case"]))
            peak = max(peak, r["peak_memory"] or 0)
    cases = sum(totals.values())
    print("cases %d: %s" % (cases, ", ".join("%s %d" % kv for kv in sorted(totals.items()))))
    print("material-stage failures by type: %s" % (materials or "none"))
    print("slowest case %.3f s (%s); peak worker memory %.1f MB" % (slowest[0], slowest[1], peak / 1e6))
    print("seeds: %d, cases per seed: %s" % (len(per_seed), sorted({sum(v.values()) for v in per_seed.values()})))
    for e in escapes[:20]:
        print("ESCAPED " + e)
    return totals, escapes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("max", "zip", "summary", "replay", "slice"))
    ap.add_argument("case", nargs="?", help="replay: <seed>:<k>")
    ap.add_argument("--cases", type=int, default=100000, help="cases [--first, --cases) of each seed")
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--shard", type=int, default=2000)
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--seeds", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--target", choices=("max", "zip"), default="max", help="slice: which harness")
    a = ap.parse_args(argv)
    if a.command == "slice":
        print(json.dumps(run_slice(a.target, a.cases)))
        return 0
    if a.command == "summary":
        totals, escapes = summary(a.out)
        return 1 if escapes or totals.get("hang") or totals.get("lost") else 0
    if a.command == "replay":
        name, k = a.case.rsplit(":", 1)
        target = "zip" if name.startswith("zip:") else "max"
        folder = tempfile.mkdtemp(prefix="maxdrop-fuzz-")
        try:
            seed = seeds(target, {name})[0]
            spec = (max_case if target == "max" else zip_case)(seed, int(k))[1]
            print("%s:%s %s" % (name, k, spec))
            print(run_case(target, seed, int(k), folder))
        finally:
            _remove(folder)
        return 0
    left = campaign(a.command, a.cases, a.jobs, a.out, a.shard, a.minutes, set(a.seeds) if a.seeds else None,
                    a.first)
    return 2 if left else 0


if __name__ == "__main__":
    sys.exit(main())
