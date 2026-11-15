# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only access to a Compound File (CFB, the container of a .max) for the fixture tools.

    from cfb import Compound
    c = Compound(open(path, "rb").read())
    c.names(); c.read("\\x05SummaryInformation"); c.runs("Scene")

`runs(name)` lists the (file offset, length) pieces that hold a stream, in stream order, so a tool can overwrite
bytes of a stream in place without rewriting the container; `streams()` yields every stream entry put back
together, so a scan also sees the strings that cross a sector boundary. Streams are found by scanning the
directory, not by walking its tree: the fixture tools only need the top-level streams 3ds Max writes. Every
sector chain is checked for range and cycles; anything malformed raises CfbError. Standard library only, no bpy.
"""
import struct

MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_LAST = 0xFFFFFFFA  # sector numbers from here up are markers (end of chain, free, FAT, DIFAT)
_END = 0xFFFFFFFE
_STREAM, _ROOT = 2, 5


class CfbError(ValueError):
    pass


def is_cfb(data):
    return data[:8] == MAGIC


class Compound:
    def __init__(self, data):
        if len(data) < 512 or not is_cfb(data):
            raise CfbError("not a compound file")
        self._data = data
        major, _order, shift, mini_shift = struct.unpack_from("<HHHH", data, 26)
        if major not in (3, 4) or shift not in (9, 12) or mini_shift != 6:
            raise CfbError("unsupported compound file header")
        self._ss = 1 << shift
        self._mss = 1 << mini_shift
        self._major = major
        self._count = (len(data) - self._ss) // self._ss  # sectors present after the header
        nfat, first_dir = struct.unpack_from("<II", data, 44)
        self._cutoff, first_minifat, _nminifat, first_difat, ndifat = struct.unpack_from("<IIIII", data, 56)
        fat_sectors = self._difat(struct.unpack_from("<109I", data, 76), first_difat, ndifat)[:nfat]
        if len(fat_sectors) != nfat:
            raise CfbError("FAT shorter than the header says")
        self._fat = []
        for s in fat_sectors:
            self._fat.extend(struct.unpack("<%dI" % (self._ss // 4), self._sector(s)))
        self._entries = self._directory(first_dir)
        root = next((e for e in self._entries if e[1] == _ROOT), None)
        if root is None:
            raise CfbError("no root entry")
        self._mini_chain = self._chain(root[2]) if root[3] else []
        if root[3] > len(self._mini_chain) * self._ss:
            raise CfbError("mini stream shorter than its size")
        self._minifat = []
        for s in self._chain(first_minifat):
            self._minifat.extend(struct.unpack("<%dI" % (self._ss // 4), self._sector(s)))
        self._all = [(name, start, size) for name, kind, start, size in self._entries if kind == _STREAM]
        self._streams = {}
        for name, start, size in self._all:
            self._streams.setdefault(name, (start, size))

    def names(self):
        return list(self._streams)

    def read(self, name):
        return self._join(self.runs(name))

    def runs(self, name):
        return self._runs(name, *self._streams[name])

    def streams(self):
        """(name, bytes) of every stream entry, duplicate names included, each put back together in order."""
        for name, start, size in self._all:
            yield name, self._join(self._runs(name, start, size))

    def _join(self, runs):
        return b"".join(self._data[o:o + n] for o, n in runs)

    def _runs(self, name, start, size):
        if size == 0:
            return []
        if size < self._cutoff:
            chain, step = self._chain(start, self._minifat, self._mini_count()), self._mss
            offsets = [self._mini_offset(m) for m in chain]
        else:
            chain, step = self._chain(start), self._ss
            offsets = [(s + 1) * self._ss for s in chain]
        if size > len(chain) * step:
            raise CfbError("stream %r shorter than its size" % name)
        out, left = [], size
        for off in offsets:
            n = min(step, left)
            if out and out[-1][0] + out[-1][1] == off:
                out[-1] = (out[-1][0], out[-1][1] + n)
            else:
                out.append((off, n))
            left -= n
            if not left:
                break
        return out

    def _sector(self, s):
        if s >= self._count:
            raise CfbError("sector %d outside the file" % s)
        return self._data[(s + 1) * self._ss:(s + 2) * self._ss]

    def _difat(self, head, first, count):
        out = [s for s in head if s < _LAST]
        seen, s = set(), first
        while s < _LAST and len(seen) < count:
            if s in seen:
                raise CfbError("DIFAT cycle")
            seen.add(s)
            entries = struct.unpack("<%dI" % (self._ss // 4), self._sector(s))
            out += [x for x in entries[:-1] if x < _LAST]
            s = entries[-1]
        return out

    def _chain(self, start, table=None, limit=None):
        table = self._fat if table is None else table
        limit = self._count if limit is None else limit
        out, seen, s = [], set(), start
        while s < _LAST:
            if s >= limit or s >= len(table) or s in seen:
                raise CfbError("broken sector chain")
            seen.add(s)
            out.append(s)
            s = table[s]
        if s != _END:
            raise CfbError("sector chain does not end")
        return out

    def _mini_count(self):
        return len(self._mini_chain) * (self._ss // self._mss)

    def _mini_offset(self, m):
        pos = m * self._mss
        return (self._mini_chain[pos // self._ss] + 1) * self._ss + pos % self._ss

    def _directory(self, first):
        raw = b"".join(self._sector(s) for s in self._chain(first))
        entries = []
        for i in range(len(raw) // 128):
            e = raw[i * 128:(i + 1) * 128]
            name_len, kind = struct.unpack_from("<HB", e, 64)
            start, size_lo, size_hi = struct.unpack_from("<III", e, 116)
            size = size_lo if self._major == 3 else size_lo | size_hi << 32
            name = e[:max(0, min(name_len, 64) - 2)].decode("utf-16-le", "replace")
            entries.append((name, kind, start, size))
        return entries
