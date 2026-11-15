# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The chunk tree of a .max stream, indexed level by level on demand.

    top = index(cf.open("Scene"))       # the top level: one entry per chunk, nothing below it read
    root = top[0]
    objects = root.children             # indexed now, once; a ChunkList, not a list of objects
    objects.ids                         # u16 ids (in Scene: class indices), as a read-only memoryview
    node = objects[5]                   # a Chunk is made when one is asked for
    node.first(0x0962).text(); node.view(); node.as_array("<f4", offset=4)

A chunk is a u16 id and a u32 size that counts the 6-byte header; bit 31 of the size marks a container, whose
payload is more chunks. A size of 0 means a u64 size follows (bit 63 = container, 14-byte header).

Headers are read straight from the stream's pieces: a bytes-like object, or the runs of a cfb.Stream as zero-copy
views made when first touched, so a stream of hundreds of megabytes is never joined into one copy. A ChunkList
keeps a level as arrays of offsets, ids and header lengths (siblings are contiguous: a size is the distance to the
next one). The Chunks it makes are cached weakly: the same object while someone holds it, freed after, so walking
a whole tree does not keep an object per chunk. A Chunk keeps its children's index as long as it lives.

The file comes from anywhere: a header cut short, a size smaller than its header, a chunk that ends after its
parent or after the stream, a level deeper than max_depth or wider than max_chunks, and a payload too short for
what is asked of it raise ChunkError. Views (and numpy arrays from as_array) keep the compound file's mapping
alive: release them before closing it. No bpy; numpy only inside as_array().
"""
import array
import bisect
import struct
import weakref

DEFAULT_MAX_DEPTH = 64
DEFAULT_MAX_CHUNKS = 1 << 22  # per level; the widest level of the 811 MB corpus scene has 35 825

_H32 = struct.Struct("<HI")
_U64 = struct.Struct("<Q")
_SIZE32 = 0x7FFFFFFF
_CONTAINER32 = 0x80000000
_SIZE64 = (1 << 63) - 1
_CONTAINER = 0x80  # flag next to the header length in ChunkList._heads


class ChunkError(ValueError):
    pass


class Source:
    """The bytes of a stream as contiguous read-only pieces: one for a bytes-like object, one per run of a
    cfb.Stream (its view made when first touched)."""
    __slots__ = ("size", "_starts", "_pieces", "_stream")

    def __init__(self, data):
        if isinstance(data, Source):
            self.size, self._starts, self._pieces, self._stream = data.size, data._starts, data._pieces, data._stream
            return
        if hasattr(data, "runs") and hasattr(data, "view"):  # cfb.Stream
            starts, pos = array.array("q"), 0
            for _offset, n in data.runs:
                starts.append(pos)
                pos += n
            if pos != data.size:
                raise ChunkError("stream %r: runs cover %d of %d bytes" % (getattr(data, "name", ""), pos, data.size))
            starts.append(pos)
            self._stream, self._pieces = data, [None] * (len(starts) - 1)
        else:
            view = memoryview(data).cast("B").toreadonly()
            starts, pos = array.array("q", (0, len(view))), len(view)
            self._stream, self._pieces = None, [view]
        self.size, self._starts = pos, starts

    def _piece(self, i):
        piece = self._pieces[i]
        if piece is None:
            start = self._starts[i]
            piece = self._pieces[i] = self._stream.view(start, self._starts[i + 1] - start)
        return piece

    def view(self, offset, size):
        """size bytes at offset: zero-copy inside one piece, a copy across pieces."""
        if offset < 0 or size < 0 or offset + size > self.size:
            raise ChunkError("range %d+%d outside the stream (%d bytes)" % (offset, size, self.size))
        if size == 0:
            return memoryview(b"")
        i = bisect.bisect_right(self._starts, offset) - 1
        local = offset - self._starts[i]
        piece = self._piece(i)
        if local + size <= len(piece):
            return piece[local:local + size]
        out = bytearray()
        while len(out) < size:
            piece = self._piece(i)
            out += piece[local:local + size - len(out)]
            i, local = i + 1, 0
        return memoryview(bytes(out))


def _scan(src, offset, end):
    """(offset, id, size, header length, container) of each chunk in [offset, end)."""
    while offset < end:
        left = end - offset
        if left < 6:
            raise ChunkError("chunk header at %d cut short (%d bytes left)" % (offset, left))
        head = src.view(offset, min(14, left))
        cid, raw = _H32.unpack_from(head)
        if raw == 0:
            if left < 14:
                raise ChunkError("64-bit chunk header at %d cut short (%d bytes left)" % (offset, left))
            raw64, = _U64.unpack_from(head, 6)
            size, header, container = raw64 & _SIZE64, 14, bool(raw64 >> 63)
        else:
            size, header, container = raw & _SIZE32, 6, bool(raw & _CONTAINER32)
        if size < header:
            raise ChunkError("chunk %04X at %d: size %d smaller than its header" % (cid, offset, size))
        if size > left:
            raise ChunkError("chunk %04X at %d (size %d) ends after its parent, %d bytes past" %
                             (cid, offset, size, size - left))
        yield offset, cid, size, header, container
        offset += size


class Chunk:
    """One chunk. Its children are indexed the first time `children` is read."""
    __slots__ = ("_src", "offset", "id", "size", "header", "container", "depth", "_limits", "_children",
                 "__weakref__")

    def __init__(self, src, offset, cid, size, header, container, depth, limits):
        self._src, self.offset, self.id, self.size = src, offset, cid, size
        self.header, self.container, self.depth, self._limits = header, container, depth, limits
        self._children = None

    def __repr__(self):
        return "Chunk(0x%04X, offset=%d, size=%d%s)" % (self.id, self.offset, self.size,
                                                        ", container" if self.container else "")

    @property
    def end(self):
        return self.offset + self.size

    @property
    def payload_offset(self):
        return self.offset + self.header

    @property
    def payload_size(self):
        return self.size - self.header

    def view(self):
        """The payload as a read-only memoryview, zero-copy unless it crosses two runs of the stream."""
        return self._src.view(self.payload_offset, self.payload_size)

    def tobytes(self):
        return self.view().tobytes()

    def text(self):
        """The payload as UTF-16LE text (3ds Max strings carry no terminator)."""
        view = self.view()
        return view[:len(view) & ~1].tobytes().decode("utf-16-le", "replace")

    def _check(self, offset, n):
        if offset < 0 or n < 0 or offset + n > self.payload_size:
            raise ChunkError("chunk %04X at %d: %d bytes at %d do not fit in its %d-byte payload" %
                             (self.id, self.offset, n, offset, self.payload_size))

    def unpack(self, fmt, offset=0):
        """struct.unpack_from on the payload; fmt should name its byte order ("<")."""
        n = struct.calcsize(fmt)
        self._check(offset, n)
        return struct.unpack(fmt, self._src.view(self.payload_offset + offset, n))

    def as_array(self, dtype, offset=0, count=-1):
        """The payload from offset as a read-only numpy array of dtype, little-endian, sharing the stream's memory
        (count items, or as many as the rest holds, which must be a whole number of them)."""
        import numpy
        dt = numpy.dtype(dtype).newbyteorder("<")
        self._check(offset, 0)
        rest = self.payload_size - offset
        if count < 0:
            if rest % dt.itemsize:
                raise ChunkError("chunk %04X at %d: %d bytes are not a whole number of %d-byte items" %
                                 (self.id, self.offset, rest, dt.itemsize))
            count = rest // dt.itemsize
        else:
            self._check(offset, count * dt.itemsize)
        out = numpy.frombuffer(self._src.view(self.payload_offset + offset, count * dt.itemsize), dtype=dt,
                               count=count)
        out.flags.writeable = False
        return out

    @property
    def children(self):
        if self._children is None:
            if not self.container:
                self._children = ChunkList(self._src, (), self.end, self.depth + 1, self._limits)
            else:
                if self.depth + 1 > self._limits[0]:
                    raise ChunkError("chunk %04X at %d: nesting deeper than %d levels" %
                                     (self.id, self.offset, self._limits[0]))
                self._children = ChunkList(self._src, _scan(self._src, self.payload_offset, self.end), self.end,
                                           self.depth + 1, self._limits)
        return self._children

    def first(self, cid):
        return self.children.first(cid)

    def find_all(self, cid):
        return self.children.find_all(cid)


class ChunkList:
    """One level of the tree as arrays; a Chunk is made when one is asked for and cached only while it is held."""
    __slots__ = ("_src", "_end", "_depth", "_limits", "_offsets", "_ids", "_heads", "_made")

    def __init__(self, src, scan, end, depth, limits):
        self._src, self._end, self._depth, self._limits = src, end, depth, limits
        offsets, ids, heads = array.array("q"), array.array("H"), bytearray()
        max_chunks = limits[1]
        for offset, cid, _size, header, container in scan:
            if len(ids) == max_chunks:
                raise ChunkError("more than %d chunks in one level (at %d)" % (max_chunks, offset))
            offsets.append(offset)
            ids.append(cid)
            heads.append(header | (_CONTAINER if container else 0))
        self._offsets, self._ids, self._heads = offsets, ids, heads
        self._made = weakref.WeakValueDictionary()

    def __len__(self):
        return len(self._ids)

    def __repr__(self):
        return "ChunkList(%d chunks, depth %d)" % (len(self._ids), self._depth)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[j] for j in range(*i.indices(len(self._ids)))]
        n = len(self._ids)
        if i < 0:
            i += n
        if not 0 <= i < n:
            raise IndexError("chunk index out of range")
        chunk = self._made.get(i)
        if chunk is None:
            head, offset = self._heads[i], self._offsets[i]
            end = self._offsets[i + 1] if i + 1 < n else self._end
            chunk = Chunk(self._src, offset, self._ids[i], end - offset, head & ~_CONTAINER, bool(head & _CONTAINER),
                          self._depth, self._limits)
            self._made[i] = chunk
        return chunk

    def __iter__(self):
        for i in range(len(self._ids)):
            yield self[i]

    @property
    def ids(self):
        return memoryview(self._ids).toreadonly()

    def first(self, cid):
        try:
            return self[self._ids.index(cid)]
        except ValueError:
            return None

    def find_all(self, cid):
        return [self[i] for i, x in enumerate(self._ids) if x == cid]


def index(data, max_depth=DEFAULT_MAX_DEPTH, max_chunks=DEFAULT_MAX_CHUNKS):
    """The top level of a stream (bytes-like, cfb.Stream or Source) as a ChunkList; it must cover the stream."""
    src = Source(data)
    return ChunkList(src, _scan(src, 0, src.size), src.size, 0, (max_depth, max_chunks))


def iter_chunks(data, max_depth=DEFAULT_MAX_DEPTH, max_chunks=DEFAULT_MAX_CHUNKS):
    """The top level of a stream, one Chunk at a time, without keeping an index."""
    src = Source(data)
    for offset, cid, size, header, container in _scan(src, 0, src.size):
        yield Chunk(src, offset, cid, size, header, container, 0, (max_depth, max_chunks))
