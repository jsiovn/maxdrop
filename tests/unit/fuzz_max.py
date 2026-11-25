# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The .max side of the fuzz harness: seeds (plain and gzip-compressed), mutations, cases and the reader
path run on them."""
import os
import random
import struct
import time
import zlib

from .fuzz_common import (
    _extreme, _mod, _pick, _put32, _region_offset, _rng, BYTES, cfb, chunks, Escaped, MaxFileError, SEED,
)


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
    """The reader path of the operator (packs._preflight, then pipeline._read_scene) on bytes, without Blender. Not
    its net for a reader defect: what ops reports as not imported for a TypeError, KeyError or AttributeError
    (packs._DEFECTS) escapes here."""

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
