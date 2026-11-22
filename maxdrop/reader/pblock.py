# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parameter blocks: a material's or map's parameters by parameter id (ParamBlock2) or by index (the old
ParamBlock).

    pb = ParamBlock2.from_chunk(scene.chunk(i), scene.refs(i), scene.refs(owner))
    pb.block_id, pb.owner, pb.version   # descriptor id (VRayMtl: 1..6), owner's object index, descriptor version
    pb.get(1)                           # parameter 1's value (a table's first element), None when not stored
    pb.value(0)                         # a table's elements as a list, a scalar as itself
    pb.param(1)                         # Param(id, type, flags, values, raw, error)
    old = ParamBlock.from_chunk(chunk)  # old.get(6): by index

A ParamBlock2 object holds a 0x0009 header (u32 the owner's class index, u16 block id, u32 descriptor version, u16
number of entries, u32 the owner's object index; 0x000B is the owner's ClassID, 8 bytes, then the same with the
owner's superclass for its class index) and one 0x100E
chunk per stored parameter (0x000E in a file saved as 3ds Max 2012): u16 id, u32 type (the SDK's ParamType2, bit
0x800 = table), u32 the definition's flags, u32 unknown, then a scalar (u8 tag, value) or a table (u8 0, u32
count, then a tag and a value per element). Tag 0x40 = a stored value, 0xC0 = the stored value of an animatable
parameter, 0x80 = a controller and no value. Transient parameters are mostly not stored (an alias sometimes is,
with a stale value); a block may store nothing at all (the header says how many entries it holds).

Values by type: float, angle (radians), fraction, world and color channel f32; int, bool, time, radio button and
index i32; color, hsv and point3 3 x f32; point4 and float color with alpha 4 x f32; point2 2 x f32; string u32
byte count (0xFFFFFFFF: none) then UTF-16LE (with a NUL); file name i32, -2 when the asset follows as the next
sibling chunk 0x000F{0x0002: 16-byte asset id}; bitmap u8, its data following as the next sibling 0x0003 (asset
id in 0x1260{0x0002}). Reference types (material, map, node, reference target, ParamBlock2) with P_OWNERS_REF
(0x200) or P_NO_REF (0x100) store an i32 object index (-1: none). With P_OWNERS_REF the owner holds the reference
and the index is often -1 although it is set: the owner's slot of each such parameter is in 0x0013 (u32 count,
then u16 param id, u16 slot, u16 unknown; a table's element k is at slot + k), which wins. A file in the 3ds Max
2012 format has no 0x0013: an index of -1 then takes the slot of owner_slots.py for the owner's class (owner_class),
and so does a stored index that is none of the owner's references when the owner holds one at that slot (the index
can be stale: another map's, or a controller's).
Without either flag there is no value: the elements take the block's own reference slots 0, 1, 2 ... in entry
order, tables and transient entries included. A controller (an animated parameter, or one table element) takes the
next slot in the same sequence: a VRayBlendMtl with base, coats 1-9 and blend maps 10-18 keeps an animated second
blend color at 10 and the blend maps at 11-19 (pblock_animated). docs/FORMAT.md says which fixture shows what.

The old ParamBlock: 0x0001 u32 count, then per parameter a 0x0002 container: 0x0003 u32 index, optionally 0x0004,
and the value in chunk 0x0100 + ParamType (0 float, 1 int, 2 color, 3 point3, 4 bool).

The file comes from anywhere: a missing or short header raises ChunkError; a damaged entry or table poisons its
own parameter (values None, raw bytes and error kept) and, when it may have taken a slot (a block reference or a
controller), leaves every later one empty instead of shifted; a damaged 0x0013 only spoils the owner
references; an asset chunk is taken only right after its entry; a stored object index past the object count is
an empty reference. Each of these is named in issues. Tables are bounded by their payload. No bpy, no numpy.
"""
import collections
import struct

from . import chunks, owner_slots

ChunkError = chunks.ChunkError

TABLE = 0x800
P_ANIMATABLE, P_TRANSIENT, P_NO_REF, P_OWNERS_REF = 0x1, 0x2, 0x100, 0x200
TAG_VALUE, TAG_CONTROLLER = 0x40, 0x80

FLOAT_TYPES = frozenset((0, 5, 6, 7, 11))  # float, angle, percent fraction, world, color channel
INT_TYPES = frozenset((1, 4, 12, 13, 19))  # int, bool, time value, radio button index, index
VECTOR_SIZES = {2: 3, 3: 3, 10: 3, 22: 4, 23: 4, 30: 2}  # rgba, point3, hsv, point4, frgba, point2: floats
STRING, FILENAME, BITMAP = 8, 9, 16
REFERENCE_TYPES = frozenset((14, 15, 17, 18, 21))  # mtl, texmap, inode, reftarg, pblock2
MATERIAL, TEXMAP = 14, 15

_HEADER, _CLASS_HEADER, _OWNER_REFS = 0x0009, 0x000B, 0x0013
_ENTRIES = (0x100E, 0x000E)
_ASSET, _BITMAP_DATA, _ASSET_ID, _ASSET_HOLDER = 0x000F, 0x0003, 0x0002, 0x1260
_ENTRY_HEAD = struct.Struct("<HIII")  # id, type, flags, unknown: 14 bytes
_HEAD = struct.Struct("<IHIHI")  # owner class index, block id, version, count, owner: 16 bytes
_OLD_COUNT, _OLD_PARAM, _OLD_INDEX, _OLD_VALUE = 0x0001, 0x0002, 0x0003, 0x0100
_NEEDS_ASSET = -2


class Reference(collections.namedtuple("Reference", "index")):
    """A reference parameter's target: an object index, None for an empty one."""
    __slots__ = ()


class Animated(collections.namedtuple("Animated", "index")):
    """A parameter driven by a controller: the controller's object index (None when the slot is empty)."""
    __slots__ = ()


class Asset(collections.namedtuple("Asset", "guid")):
    """A file name or bitmap stored as an asset id (16 bytes), resolved through the asset metadata stream."""
    __slots__ = ()


class Param(collections.namedtuple("Param", "id type flags values raw error")):
    """One stored parameter. values: a tuple, one element for a scalar, every element for a table; None when
    damaged (raw then holds the entry's bytes and error why)."""
    __slots__ = ()

    @property
    def table(self):
        return bool(self.type & TABLE)

    @property
    def base_type(self):
        return self.type & ~TABLE

    @property
    def transient(self):
        return bool(self.flags & P_TRANSIENT)

    @property
    def owners_ref(self):
        return bool(self.flags & P_OWNERS_REF)


# what an element stands for before references and controllers are resolved
_BLOCK_REF, _OWNER_REF, _CONTROLLER = object(), object(), object()


class _Damaged(Exception):
    pass


def _element(buf, pos, tag, base, stored_ref, strings=chunks.WIDE):
    """(value, next position) of one element; _Damaged when it does not fit or cannot be sized."""
    if tag & TAG_CONTROLLER and not tag & TAG_VALUE:
        return _CONTROLLER, pos
    if base in REFERENCE_TYPES:
        if not stored_ref:
            return _BLOCK_REF, pos
        return (_OWNER_REF, _unpack(buf, pos, "<i")[0]), pos + 4
    if base in FLOAT_TYPES:
        return _unpack(buf, pos, "<f")[0], pos + 4
    if base in INT_TYPES:
        return _unpack(buf, pos, "<i")[0], pos + 4
    n = VECTOR_SIZES.get(base)
    if n is not None:
        return _unpack(buf, pos, "<%df" % n), pos + 4 * n
    if base == STRING:
        size = _unpack(buf, pos, "<I")[0]
        pos += 4
        if size == 0xFFFFFFFF:
            return None, pos
        if size > len(buf) - pos:
            raise _Damaged("string of %d bytes, %d left" % (size, len(buf) - pos))
        text = strings.text(buf[pos:pos + size])
        return text[:-1] if text.endswith("\x00") else text, pos + size
    if base == FILENAME:
        return _unpack(buf, pos, "<i")[0], pos + 4
    if base == BITMAP:
        return _unpack(buf, pos, "<B")[0], pos + 1
    raise _Damaged("type %d: element size unknown" % base)


def _unpack(buf, pos, fmt):
    n = struct.calcsize(fmt)
    if pos + n > len(buf):
        raise _Damaged("%d bytes at %d do not fit in %d" % (n, pos, len(buf)))
    return struct.unpack_from(fmt, buf, pos)


def _entry(buf, strings=chunks.WIDE):
    """(id, type, flags, elements) of one entry payload; _Damaged when it cannot be read."""
    if len(buf) < _ENTRY_HEAD.size + 1:
        raise _Damaged("entry of %d bytes" % len(buf))
    pid, ptype, flags, _unknown = _ENTRY_HEAD.unpack_from(buf)
    base, stored_ref, pos = ptype & ~TABLE, bool(flags & (P_OWNERS_REF | P_NO_REF)), _ENTRY_HEAD.size
    if not ptype & TABLE:
        value, pos = _element(buf, pos + 1, buf[pos], base, stored_ref, strings)
        return pid, ptype, flags, [value]
    count = _unpack(buf, pos + 1, "<I")[0]
    pos += 5
    if count > len(buf) - pos:  # every element has at least its tag
        raise _Damaged("table of %d elements in %d bytes" % (count, len(buf) - pos))
    out = []
    for _ in range(count):
        tag = _unpack(buf, pos, "<B")[0]
        value, pos = _element(buf, pos + 1, tag, base, stored_ref, strings)
        out.append(value)
    return pid, ptype, flags, out


def _may_take_slots(ptype, flags, data):
    """Whether a damaged entry may have held block references or controllers: its head unreadable, a reference type
    without a stored index, any table (a controller tag counts whatever the flags say), or a scalar cut before its
    tag. A scalar's tag is read before its value, and a controller has no value, so a scalar damaged after its tag
    holds a value."""
    if ptype is None or ptype & TABLE or len(data) <= _ENTRY_HEAD.size:
        return True
    return ptype & ~TABLE in REFERENCE_TYPES and not flags & (P_OWNERS_REF | P_NO_REF)


def _asset_id(chunk):
    """The 16-byte asset id of a 0x000F or 0x0003 sibling, None when it has none; _Damaged when it is broken."""
    if not chunk.container:
        return None
    try:
        holder = chunk if chunk.id == _ASSET else chunk.first(_ASSET_HOLDER)
        guid = holder.first(_ASSET_ID) if holder is not None and holder.container else None
    except ChunkError as e:
        raise _Damaged(str(e))
    return Asset(guid.tobytes()) if guid is not None and guid.payload_size == 16 else None


class ParamBlock2:
    """One ParamBlock2 object, its references resolved to object indices."""

    def __init__(self, block_id, version, owner, params, issues=(), count=None):
        self.block_id, self.version, self.owner, self._params = block_id, version, owner, params
        self.issues = tuple(issues)
        self.count = len(params) if count is None else count  # the entries the header announces

    def __repr__(self):
        return "ParamBlock2(block %d, %d params)" % (self.block_id, len(self._params))

    @classmethod
    def from_chunk(cls, chunk, block_refs=None, owner_refs=None, object_count=None, owner_class=None):
        """From the block's chunk, its own references and its owner's ({slot: object index}, as Scene.refs). A
        stored object index at or past object_count (when given) becomes an empty reference and an issue.
        owner_class, the owner's (superclass, ClassId), finds the owner slots of a block without 0x0013."""
        block_refs, owner_refs = block_refs or {}, owner_refs or {}
        head, skip = (chunk.first(_HEADER), 0) if chunk.container else (None, 0)
        if head is None and chunk.container:
            head, skip = chunk.first(_CLASS_HEADER), 8  # the descriptor's class id first: classA, classB
        if head is None:
            raise ChunkError("ParamBlock2 at %d without a 0x0009 or 0x000B header" % chunk.offset)
        if head.payload_size < skip + _HEAD.size:
            raise ChunkError("ParamBlock2 at %d: header of %d bytes" % (chunk.offset, head.payload_size))
        _owner_class_index, block_id, version, count, owner = _HEAD.unpack(head.view()[skip:skip + _HEAD.size])
        issues, slots = [], {}
        table = chunk.first(_OWNER_REFS)
        if table is not None:
            try:
                buf = table.view()
                n = _unpack(buf, 0, "<I")[0]
                if 4 + 6 * n > len(buf):
                    raise _Damaged("%d owner references in %d bytes" % (n, len(buf)))
                for k in range(n):
                    pid, slot, _unknown = struct.unpack_from("<HHH", buf, 4 + 6 * k)
                    slots.setdefault(pid, slot)
            except _Damaged as e:
                issues.append("0x0013: %s" % e)
                slots = {}
        fixed = owner_slots.slots(owner_class, block_id) if table is None else {}
        held = set(owner_refs.values()) if fixed else set()  # a stored index the owner holds is trusted
        raw = []
        # the elements of the entry just read that expect their asset in the chunks right after it
        waiting, want = collections.deque(), None

        def missing():
            issues.append("parameter %d: asset chunk missing" % waiting[0][0][0])
            waiting.clear()

        for child in chunk.children:
            if child.id in _ENTRIES:
                if waiting:
                    missing()
                buf = child.view()
                try:
                    pid, ptype, flags, values = _entry(buf, chunk.strings)
                except _Damaged as e:
                    pid = struct.unpack_from("<H", buf)[0] if len(buf) >= 2 else -1
                    ptype, flags = struct.unpack_from("<II", buf, 2) if len(buf) >= 10 else (None, 0)
                    raw.append([pid, ptype, flags, None, bytes(buf), str(e)])
                    continue
                raw.append([pid, ptype, flags, values, None, None])
                base = ptype & ~TABLE
                if base in (FILENAME, BITMAP):
                    want = _ASSET if base == FILENAME else _BITMAP_DATA
                    waiting.extend((raw[-1], k) for k, v in enumerate(values)
                                   if (base == BITMAP and v) or (base == FILENAME and v == _NEEDS_ASSET))
            elif waiting and child.id == want:
                entry, k = waiting.popleft()
                try:
                    entry[3][k] = _asset_id(child)
                except _Damaged as e:
                    issues.append("parameter %d: asset chunk damaged: %s" % (entry[0], e))
            else:
                if child.id in (_ASSET, _BITMAP_DATA):
                    issues.append("asset chunk %04X at %d belongs to no entry" % (child.id, child.offset))
                if waiting:
                    missing()
        if waiting:
            missing()

        def target(index, what):
            if index < 0:
                return Reference(None)
            if object_count is not None and index >= object_count:
                issues.append("%s: object index %d outside the %d objects" % (what, index, object_count))
                return Reference(None)
            return Reference(index)

        # Block-held references and controllers share one slot sequence, in entry order. A damaged entry that may have
        # taken slots leaves the slots of every later one unknown: they stay empty rather than take a neighbour's
        # target.
        params, next_slot, slots_lost = {}, 0, None
        for pid, ptype, flags, values, data, error in raw:
            if values is None:
                if slots_lost is None and _may_take_slots(ptype, flags, data):
                    slots_lost = pid
            else:
                for k, v in enumerate(values):
                    if v is _BLOCK_REF or v is _CONTROLLER:
                        index = None if slots_lost is not None else block_refs.get(next_slot)
                        values[k] = Reference(index) if v is _BLOCK_REF else Animated(index)
                        next_slot += 1
                    elif isinstance(v, tuple) and v and v[0] is _OWNER_REF:
                        if pid in slots and flags & P_OWNERS_REF:
                            values[k] = Reference(owner_refs.get(slots[pid] + k))
                        elif pid in fixed and flags & P_OWNERS_REF and (v[1] == -1 or (
                                v[1] not in held and owner_refs.get(fixed[pid] + k) is not None)):
                            values[k] = Reference(owner_refs.get(fixed[pid] + k))
                        else:
                            values[k] = target(v[1], "parameter %d" % pid)
                    elif ptype & ~TABLE in (FILENAME, BITMAP) and not isinstance(v, Asset):
                        values[k] = None  # no asset, or its chunk is missing
            if pid in params:
                issues.append("parameter %d stored twice, the first kept" % pid)
                continue
            params[pid] = (ptype if ptype is not None else 0, flags, values, data, error)
        if slots_lost is not None:
            issues.append("block references and controllers after parameter %d unresolved" % slots_lost)
        out = {}
        for pid, (ptype, flags, values, data, error) in params.items():
            out[pid] = Param(pid, ptype, flags, None if values is None else tuple(values), data, error)
            if error:
                issues.append("parameter %d: %s" % (pid, error))
        if count != len(raw):
            issues.append("header announces %d entries, %d found" % (count, len(raw)))
        return cls(block_id, version, owner, out, issues, count)

    def __contains__(self, pid):
        return pid in self._params

    def __iter__(self):
        return iter(self._params.values())

    def __len__(self):
        return len(self._params)

    def ids(self):
        return list(self._params)

    def param(self, pid):
        """The Param record of parameter pid, None when it is not stored."""
        return self._params.get(pid)

    def get(self, pid, tab=0, default=None):
        """One value: element tab of a table (0 of a scalar); default when not stored, damaged or out of range."""
        p = self._params.get(pid)
        if p is None or p.values is None or not 0 <= tab < len(p.values):
            return default
        return p.values[tab]

    def value(self, pid, default=None):
        """A table's elements as a list, a scalar's value; default when not stored or damaged."""
        p = self._params.get(pid)
        if p is None or p.values is None:
            return default
        return list(p.values) if p.table else p.values[0]


class ParamBlock:
    """The old ParamBlock: values by index."""

    def __init__(self, params, issues=()):
        self._params, self.issues = params, tuple(issues)

    def __repr__(self):
        return "ParamBlock(%d params)" % len(self._params)

    @classmethod
    def from_chunk(cls, chunk):
        if not chunk.container:
            raise ChunkError("ParamBlock at %d is a leaf chunk" % chunk.offset)
        params, issues = {}, []
        for entry in chunk.find_all(_OLD_PARAM):
            if not entry.container:
                issues.append("parameter entry at %d is a leaf" % entry.offset)
                continue
            index = entry.first(_OLD_INDEX)
            if index is None or index.payload_size < 4:
                issues.append("parameter entry at %d without an index" % entry.offset)
                continue
            i = index.unpack("<I")[0]
            ptype, value = None, None
            for c in entry.children:
                if _OLD_VALUE <= c.id <= _OLD_VALUE + 4:
                    ptype = c.id - _OLD_VALUE
                    fmt = ("<f", "<i", "<3f", "<3f", "<i")[ptype]
                    if c.payload_size < struct.calcsize(fmt):
                        issues.append("parameter %d: value of %d bytes" % (i, c.payload_size))
                        break
                    value = c.unpack(fmt)
                    value = value[0] if len(value) == 1 else value
                    break
            params.setdefault(i, (ptype, value))
        declared = chunk.first(_OLD_COUNT)
        if declared is not None and declared.payload_size >= 4 and declared.unpack("<I")[0] != len(params):
            issues.append("0x0001 announces %d parameters, %d found" % (declared.unpack("<I")[0], len(params)))
        return cls(params, issues)

    def __len__(self):
        return len(self._params)

    def __contains__(self, i):
        return i in self._params

    def indices(self):
        return sorted(self._params)

    def type(self, i):
        """The ParamType of parameter i (0 float, 1 int, 2 color, 3 point3, 4 bool), None when unknown."""
        return self._params.get(i, (None, None))[0]

    def get(self, i, default=None):
        value = self._params.get(i, (None, None))[1]
        return default if value is None else value
