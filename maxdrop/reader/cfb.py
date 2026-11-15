# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The OLE compound file (CFB, [MS-CFB]) that holds the streams of a .max, read through a memory map.

    with CompoundFile(path) as cf:
        cf.names()                      # stream paths, "Storage/Child" below a storage
        scene = cf.open("Scene")        # a Stream: nothing is read yet
        scene.read(0, 6); scene.view(); scene.buffer()

Opening reads the header, the FAT, the directory and nothing else, so it takes milliseconds also for a file of
hundreds of megabytes. A stream is described by its runs, the (file offset, length) pieces that hold it in order
with consecutive sectors merged; reads go straight to the mapping, and a range inside one run comes back as a
zero-copy memoryview. A stream that starts with a gzip header is inflated by open() with a size cap.

The file comes from anywhere: every sector number is range-checked, every chain is checked for cycles and for
covering its size, the directory has an entry cap, and anything malformed raises CfbError, never IndexError or a
loop that does not end. Views keep the mapping alive: release them before close(), or the mapping is only freed
when the last one goes. Standard library only, no bpy.
"""
import array
import bisect
import mmap
import os
import struct
import sys
import zlib

MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
GZIP_MAGIC = b"\x1f\x8b\x08"  # ID1 ID2 and CM = deflate, the only method gzip defines

DEFAULT_MAX_ENTRIES = 65536
DEFAULT_MAX_DECOMPRESSED = 4 << 30

_MAXREGSECT = 0xFFFFFFFA  # sector numbers above this are markers
_ENDOFCHAIN = 0xFFFFFFFE
_NOSTREAM = 0xFFFFFFFF
_MINI_SHIFT = 6
_CUTOFF = 4096
_ENTRY_SIZE = 128
_INFLATE_PIECE = 1 << 20

STORAGE, STREAM, ROOT = 1, 2, 5

_HEADER = struct.Struct("<8s16sHHHHH6sIIIIIIIII")
_ENTRY = struct.Struct("<64sHBBIII16sIQQIQ")


class CfbError(ValueError):
    pass


def is_cfb(head):
    return bytes(head[:8]) == MAGIC


class Entry:
    """A stream or storage of the directory. path joins storage names with "/"."""
    __slots__ = ("sid", "path", "kind", "start", "size")

    def __init__(self, sid, path, kind, start, size):
        self.sid, self.path, self.kind, self.start, self.size = sid, path, kind, start, size

    def __repr__(self):
        return "Entry(%r, kind=%d, size=%d)" % (self.path, self.kind, self.size)


class Stream:
    """One stream as runs over a buffer (the file's mapping, or the inflated bytes of a gzip stream)."""

    def __init__(self, name, buf, runs, size, compressed=False):
        self.name = name
        self.size = size
        self.runs = tuple(runs)
        self.compressed = compressed
        self._buf = buf
        starts, pos = [], 0
        for _, n in self.runs:
            starts.append(pos)
            pos += n
        self._starts = starts

    def __len__(self):
        return self.size

    def __repr__(self):
        return "Stream(%r, size=%d, runs=%d)" % (self.name, self.size, len(self.runs))

    def _range(self, offset, size):
        if offset < 0:
            raise CfbError("negative offset into stream %r" % self.name)
        offset = min(offset, self.size)
        end = self.size if size is None or size < 0 else min(self.size, offset + size)
        return offset, end

    def _pieces(self, offset, end):
        i = bisect.bisect_right(self._starts, offset) - 1
        while offset < end:
            run_off, run_len = self.runs[i]
            skip = offset - self._starts[i]
            n = min(run_len - skip, end - offset)
            yield self._buf[run_off + skip:run_off + skip + n]
            offset += n
            i += 1

    def view(self, offset=0, size=-1):
        """A memoryview of the range: zero-copy when it lies in one run, a copy when it crosses runs."""
        offset, end = self._range(offset, size)
        pieces = list(self._pieces(offset, end))
        if len(pieces) == 1:
            return pieces[0]
        return memoryview(b"".join(pieces))

    def read(self, offset=0, size=-1):
        offset, end = self._range(offset, size)
        return b"".join(self._pieces(offset, end))

    def buffer(self):
        """The whole stream as one contiguous buffer."""
        return self.view()


class CompoundFile:
    """A compound file opened from a path (memory-mapped) or from a bytes-like object."""

    def __init__(self, source, max_entries=DEFAULT_MAX_ENTRIES):
        self._file = self._map = None
        if isinstance(source, (bytes, bytearray, memoryview)):
            self._view = memoryview(source).cast("B")
        else:
            self._file = open(source, "rb")
            try:
                if os.fstat(self._file.fileno()).st_size < 512:
                    raise CfbError("not a compound file: too small")
                self._map = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
            except BaseException:
                self._file.close()
                raise
            self._view = memoryview(self._map)
        try:
            self._parse(max_entries)
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        view, self._view = getattr(self, "_view", None), None
        if view is not None:
            view.release()
        if self._map is not None:
            try:
                self._map.close()
            except BufferError:
                pass  # a view the caller holds still uses it; it goes with the last view
            self._map = None
        if self._file is not None:
            self._file.close()
            self._file = None

    # Header, FAT, directory.

    def _parse(self, max_entries):
        data = self._view
        self.size = len(data)
        if self.size < 512 or not is_cfb(data):
            raise CfbError("not a compound file")
        (_magic, _clsid, _minor, major, order, shift, mini_shift, _res, _ndir, nfat, first_dir, _txn, cutoff,
         first_minifat, _nminifat, first_difat, _ndifat) = _HEADER.unpack_from(data, 0)
        if order != 0xFFFE:
            raise CfbError("compound file is not little-endian")
        if (major, shift) not in ((3, 9), (4, 12)) or mini_shift != _MINI_SHIFT or cutoff != _CUTOFF:
            raise CfbError("unsupported compound file header (version %d, sector shift %d)" % (major, shift))
        self.version = major
        self.sector_size = ss = 1 << shift
        if self.size < ss:
            raise CfbError("compound file shorter than its header")
        # A last sector may be cut short; a stream that needs its missing part fails in _runs.
        self._nsect = (self.size - ss + ss - 1) // ss
        self._per_sector = ss // 4
        if nfat > self._nsect:
            raise CfbError("FAT larger than the file")
        fat_sectors = self._fat_sectors(nfat, first_difat)
        self._fat = self._table(fat_sectors)
        self._limit = min(len(self._fat), self._nsect)
        self._entries = self._directory(first_dir, max_entries)
        self._first_minifat = first_minifat
        self._minifat = self._mini_chain = None
        self._tree()

    def _sector(self, s):
        if s >= self._nsect:
            raise CfbError("sector %d outside the file" % s)
        start = (s + 1) * self.sector_size
        if start + self.sector_size > self.size:
            raise CfbError("sector %d cut short by the end of the file" % s)
        return self._view[start:start + self.sector_size]

    def _table(self, sectors):
        table = array.array("I")
        for s in sectors:
            table.frombytes(self._sector(s))
        if sys.byteorder == "big":
            table.byteswap()
        return table

    def _fat_sectors(self, nfat, first_difat):
        head = struct.unpack_from("<109I", self._view, 76)
        out = list(head[:min(nfat, 109)])
        seen, s = set(), first_difat
        while len(out) < nfat:
            if s > _MAXREGSECT:
                raise CfbError("FAT shorter than the header says")
            if s in seen:
                raise CfbError("DIFAT chain has a cycle")
            seen.add(s)
            entries = struct.unpack("<%dI" % self._per_sector, self._sector(s))
            out.extend(entries[:-1][:nfat - len(out)])
            s = entries[-1]
        for s in out:
            if s > _MAXREGSECT:
                raise CfbError("FAT sector list has a hole")
        return out

    def _chain(self, start, table, limit, needed=None, what="stream"):
        """Sector numbers of a chain: `needed` of them when given, else up to ENDOFCHAIN."""
        out, seen, s = [], bytearray(limit), start
        while needed is None or len(out) < needed:
            if s == _ENDOFCHAIN:
                if needed is None:
                    break
                raise CfbError("%s ends before its size" % what)
            if s >= limit:
                raise CfbError("%s points to sector %d, outside the table" % (what, s))
            if seen[s]:
                raise CfbError("%s chain has a cycle" % what)
            seen[s] = 1
            out.append(s)
            s = table[s]
        return out

    def _directory(self, first, max_entries):
        per = self.sector_size // _ENTRY_SIZE
        out, seen, s = [], bytearray(self._limit), first
        while s != _ENDOFCHAIN:
            if s >= self._limit:
                raise CfbError("directory points to sector %d, outside the table" % s)
            if seen[s]:
                raise CfbError("directory chain has a cycle")
            seen[s] = 1
            if (len(out) + 1) * per > max_entries:
                raise CfbError("directory has more than %d entries" % max_entries)
            out.append(s)
            s = self._fat[s]
        if not out:
            raise CfbError("empty directory")
        entries = []
        for s in out:
            raw = self._sector(s)
            for i in range(per):
                name, name_len, kind, _color, left, right, child, _clsid, _state, _ct, _mt, start, size = \
                    _ENTRY.unpack_from(raw, i * _ENTRY_SIZE)
                if self.version == 3:
                    size &= 0xFFFFFFFF  # the high half is undefined in version 3
                name_len = min(name_len, 64)
                text = name[:max(0, name_len - 2)].decode("utf-16-le", "replace")
                entries.append((text, kind, left, right, child, start, size))
        if entries[0][1] != ROOT:
            raise CfbError("the first directory entry is not the root")
        return entries

    def _tree(self):
        """Walk the directory tree from the root: storages and streams by path, in tree order."""
        raw = self._entries
        root = raw[0]
        self.root = Entry(0, "", ROOT, root[5], root[6])
        self._list, self._by_path = [], {}
        seen = bytearray(len(raw))
        seen[0] = 1
        stack = [(True, root[4], "")]
        while stack:
            visit, sid, prefix = stack.pop()
            if visit:
                if sid == _NOSTREAM:
                    continue
                if sid >= len(raw):
                    raise CfbError("directory entry %d does not exist" % sid)
                if seen[sid]:
                    raise CfbError("directory tree has a cycle at entry %d" % sid)
                seen[sid] = 1
                _name, _kind, left, right, _child, _start, _size = raw[sid]
                stack += [(True, right, prefix), (False, sid, prefix), (True, left, prefix)]
                continue
            name, kind, _left, _right, child, start, size = raw[sid]
            if kind not in (STORAGE, STREAM):
                continue
            entry = Entry(sid, prefix + name, kind, start, size)
            self._list.append(entry)
            self._by_path.setdefault(entry.path.lower(), entry)
            if kind == STORAGE:
                stack.append((True, child, entry.path + "/"))

    # Streams.

    def entries(self):
        return list(self._list)

    def names(self):
        return [e.path for e in self._list if e.kind == STREAM]

    def exists(self, name):
        entry = self._by_path.get(self._key(name))
        return entry is not None and entry.kind == STREAM

    @staticmethod
    def _key(name):
        if not isinstance(name, str):
            name = "/".join(name)
        return name.lower()

    def open(self, name, decompress=True, max_size=DEFAULT_MAX_DECOMPRESSED):
        if self._view is None:
            raise CfbError("compound file is closed")
        entry = self._by_path.get(self._key(name))
        if entry is None or entry.kind != STREAM:
            raise KeyError(name)
        stream = Stream(entry.path, self._view, self._runs(entry), entry.size)
        if bytes(stream.read(0, 3)) == GZIP_MAGIC:
            if not decompress:
                stream.compressed = True
                return stream
            data = _inflate(stream, max_size)
            return Stream(entry.path, memoryview(data), ((0, len(data)),), len(data), compressed=True)
        return stream

    def _runs(self, entry):
        size = entry.size
        if size == 0:
            return []
        if size < _CUTOFF:
            step = 1 << _MINI_SHIFT
            chain = self._chain(entry.start, self._minifat_table(), self._mini_count(),
                                (size + step - 1) // step, "stream %r" % entry.path)
            ss, mini = self.sector_size, self._mini_sectors()
            offsets = [(mini[(m << _MINI_SHIFT) // ss] + 1) * ss + (m << _MINI_SHIFT) % ss for m in chain]
        else:
            step = self.sector_size
            chain = self._chain(entry.start, self._fat, self._limit, (size + step - 1) // step,
                                "stream %r" % entry.path)
            offsets = [(s + 1) * step for s in chain]
        runs, left = [], size
        for off in offsets:
            n = min(step, left)
            if runs and runs[-1][0] + runs[-1][1] == off:
                runs[-1][1] += n
            else:
                runs.append([off, n])
            left -= n
        for off, n in runs:
            if off + n > self.size:
                raise CfbError("stream %r runs past the end of the file" % entry.path)
        return [(off, n) for off, n in runs]

    def _mini_sectors(self):
        if self._mini_chain is None:
            ss = self.sector_size
            self._mini_chain = self._chain(self.root.start, self._fat, self._limit,
                                           (self.root.size + ss - 1) // ss, "mini stream")
        return self._mini_chain

    def _mini_count(self):
        return min(len(self._minifat_table()), (self.root.size + (1 << _MINI_SHIFT) - 1) >> _MINI_SHIFT)

    def _minifat_table(self):
        if self._minifat is None:
            if self._first_minifat == _ENDOFCHAIN:
                self._minifat = array.array("I")
            else:
                self._minifat = self._table(self._chain(self._first_minifat, self._fat, self._limit,
                                                        what="mini FAT"))
        return self._minifat


def _inflate(stream, max_size):
    """Inflate gzip members one after another; bytes after the last member that do not start a new one are
    padding. More than max_size bytes of output raise CfbError."""
    out = bytearray()
    pieces = (stream.view(o, _INFLATE_PIECE) for o in range(0, stream.size, _INFLATE_PIECE))
    d, buf = zlib.decompressobj(16 + zlib.MAX_WBITS), b""
    try:
        while True:
            if not buf:
                buf = next(pieces, None)
                if buf is None:
                    break
            out += d.decompress(buf, max_size + 1 - len(out))
            if len(out) > max_size:
                raise CfbError("compressed stream %r inflates to more than %d bytes" % (stream.name, max_size))
            buf = d.unconsumed_tail
            if d.eof:
                rest = d.unused_data + bytes(buf)
                while len(rest) < len(GZIP_MAGIC):
                    more = next(pieces, None)
                    if more is None:
                        break
                    rest += bytes(more)
                if rest[:len(GZIP_MAGIC)] != GZIP_MAGIC:
                    return out
                d, buf = zlib.decompressobj(16 + zlib.MAX_WBITS), rest
    except zlib.error as exc:
        raise CfbError("compressed stream %r is damaged: %s" % (stream.name, exc)) from None
    if not d.eof:
        raise CfbError("compressed stream %r is cut short" % stream.name)
    return out
