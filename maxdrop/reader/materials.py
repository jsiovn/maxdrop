# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The materials and maps of a scene: class, name, parameter blocks, parts, sub-materials and maps, by object index.

    graph = MaterialGraph(scene)
    m = graph.get(node.material)        # MtlBase of a material or map object
    m.class_id, m.superclass, m.name, m.is_material
    m.blocks                            # {reference slot: ParamBlock2}
    m.block(1)                          # the ParamBlock2 with descriptor id 1 (VRayMtl: basic parameters)
    m.param(1)                          # parameter 1's value from the first block that stores it
    m.legacy, m.parts                   # {slot: ParamBlock}, {slot: Part} (a map's coordinates and output,
                                        # a Standard material's shader and sampler, each with its own blocks)
    m.children                          # object indices of the sub-materials and maps, each once
    graph.walk([node.material, ...])    # every material and map reachable, depth first, each once

A material (superclass 0x0C00) or map (0x0C10) keeps its name in 0x4001 inside a container whose id depends on
the class (0x4000; VRayMtl 0x5431, Physical Material 0x0100): the first container child holding a 0x4001. Its
parameters in the ParamBlock2 and ParamBlock objects it references. Its sub-materials and maps are referenced
either by the material itself (a VRayMtl's maps, a Multi/Sub-Object's materials: parameters with P_OWNERS_REF) or
by one of its ParamBlock2 objects (a VRayBlendMtl's coats, a VRayNormalMap's maps), or, for a Standard material,
by its Texmaps object (superclass 0x1080): children takes them all, in reference order, the references of a
block or of the Texmaps object at its slot. A reference of superclass UVGen (0x0C20), XYZGen
(0x0C30), TexOutput (0x0C40), Shader (0x10B0) or Sampler (0x1110) is a part: its blocks belong to the material.

Dispatch is on superclass, never on a class name. The file comes from anywhere: a reference that leaves the object
list raises in Scene.refs and makes get() raise ChunkError for that object only; a block that cannot be read is
left out and named in the MtlBase's issues; walk() keeps going past objects that cannot be read (graph.issues)
and through reference cycles, each object visited once, bounded by the object count.

Some parts keep settings in chunks of their own, read into values here (3ds Max 2020 layout, docs/FORMAT.md):

    placement(scene, uv.index)          # Placement: tile, mirror, real-world scale, axis, environment, source,
                                        # channel of a Placement (UVGen) object
    output_invert(scene, out.index)     # an Output (TexOutput) part's invert flag
    bitmap_gamma(scene, m)              # a Bitmap's gamma override as stored, None for automatic
    mix_curve(scene, m)                 # the CurvePoints of the Custom Curve Control m references (a Falloff's
                                        # mix curve), None without one
    standard_maps(scene, m)             # a Standard material's map channels (map, on, amount) from its Texmaps
                                        # object, as 3ds Max answers them; None without a readable one

An unreadable flags chunk gives 3ds Max's defaults (both axes tiled, nothing mirrored, not inverted); a Placement's
axis, source and channel are None without their chunk, for convert to default. No bpy.
"""
import collections
import math
import struct

from . import chunks, classids, pblock
from .errors import MaxFileError

ChunkError = chunks.ChunkError

PART_SUPERCLASSES = frozenset((classids.SC_UVGEN, classids.SC_XYZGEN, classids.SC_TEXOUTPUT, classids.SC_SHADER,
                               classids.SC_SAMPLER))
MTLBASE_SUPERCLASSES = frozenset((classids.SC_MATERIAL, classids.SC_TEXMAP))
_NAME = 0x4001

# Placement (UVGen) object: u32 leaves; flags bits; coordinate source values
_UV_FLAGS, _UV_AXIS, _UV_MAPPING_TYPE, _UV_SOURCE, _UV_CHANNEL = 0x9002, 0x9003, 0x9005, 0x9006, 0x900B
_UV_ENVIRONMENT = 0x9009
_U_TILE, _V_TILE, _U_MIRROR, _V_MIRROR, _REAL_WORLD = 0x1, 0x2, 0x4, 0x8, 0x08000000
UV_EXPLICIT, UV_OBJECT_XYZ, UV_VERTEX_COLOR, UV_WORLD_XYZ = 0, 1, 2, 3
# Output (TexOutput) part: its flags leaf
_OUT_FLAGS, _OUT_INVERT = 0x0002, 0x2
# BitmapInfo: the 0x0003 sibling of the bitmap entry holds 0x1201; its last 14 bytes start with gamma, flags
_BITMAP_DATA, _BITMAP_INFO, _BI_TAIL, _BI_GAMMA_OVERRIDE = 0x0003, 0x1201, 14, 0x1
# Custom Curve Control: reference 0 its curve, which holds 0x1000 its point count, then per point a 0x1030 holding a
# 0x1000 of 28 bytes: x, y, in handle x, y, out handle x, y (each handle as a position, not an offset), u32 flags
_CURVE_COUNT, _CURVE_POINT, _POINT_DATA = 0x1000, 0x1030, 0x1000
_POINT = struct.Struct("<6fI")
MAX_CURVE_POINTS = 1000  # a curve drawn by hand has a handful; the cap keeps a hostile count from costing time
# A Standard material's Texmaps object: u32 leaf, its on mask; f32 leaves at _STD_AMOUNT + channel; channel k's map at
# its reference 2k + 1 (2k: the amount's controller)
_STD_ON, _STD_AMOUNT, STD_CHANNELS = 0x5003, 0x5100, 32


class CurvePoint(collections.namedtuple("CurvePoint", "point in_handle out_handle flags")):
    """A curve point: point, in_handle and out_handle as (x, y) positions, its u32 flags as stored."""
    __slots__ = ()


class Part(collections.namedtuple("Part", "index class_id superclass blocks legacy")):
    """A reference of a material or map that carries parameter blocks of its own."""
    __slots__ = ()


class Issue(collections.namedtuple("Issue", "index reason")):
    __slots__ = ()


class Placement(collections.namedtuple("Placement", "tile mirror real_world axis environment source channel "
                                                    "env_mapping")):
    """A Placement object's chunk settings. tile, mirror: (u, v); real_world: real-world map size; axis (0 UV, 1 VW,
    2 WU), source (UV_*) and channel: as stored, None without their chunk; environment: a mapping type other than
    texture; env_mapping: the environment projection (1 spherical, 2 cylindrical, 3 shrink-wrap, 4 screen, kept
    also in texture mode; None without its chunk)."""
    __slots__ = ()


Placement.__new__.__defaults__ = (None,)


class StdMaps(collections.namedtuple("StdMaps", "maps enabled amounts")):
    """A Standard material's map channels as 3ds Max answers them (its Texmaps object): maps {channel: object index of
    the map}, enabled the on mask (bit k = channel k), amounts {channel: amount as stored, 1 = full} where not 1."""
    __slots__ = ()

    def channel(self, k):
        """(map object index or None, switched on, amount) of channel k."""
        return self.maps.get(k), bool(self.enabled >> k & 1), self.amounts.get(k, 1.0)


class MtlBase:
    """One material or map."""
    __slots__ = ("index", "class_id", "superclass", "name", "refs", "blocks", "legacy", "parts", "children",
                 "issues", "_ordered")

    def __init__(self, index, class_id, superclass, name, refs, blocks, legacy, parts, children, issues):
        self.index, self.class_id, self.superclass, self.name, self.refs = index, class_id, superclass, name, refs
        self.blocks, self.legacy, self.parts, self.children = blocks, legacy, parts, children
        self.issues = tuple(issues)
        self._ordered = [b for _slot, b in sorted(blocks.items())]

    def __repr__(self):
        return "MtlBase(%d, %s, %r)" % (self.index, self.class_id, self.name)

    @property
    def is_material(self):
        return self.superclass == classids.SC_MATERIAL

    def block(self, block_id):
        """The ParamBlock2 with that descriptor id (the first in reference order), None without one."""
        return next((b for b in self._ordered if b.block_id == block_id), None)

    def param(self, pid, block_id=None, tab=0, default=None):
        """Parameter pid's value from the given block, or from the first block (reference order) that stores it."""
        blocks = [self.block(block_id)] if block_id is not None else self._ordered
        for b in blocks:
            if b is not None and pid in b:
                return b.get(pid, tab, default)
        return default


def _name(chunk):
    """The 0x4001 name inside the first container child that holds one (0x4000; VRayMtl 0x5431, Physical 0x0100)."""
    if not chunk.container:
        return ""
    for holder in chunk.children:
        if holder.container:
            name = holder.first(_NAME)
            if name is not None:
                return name.text()
    return ""


class MaterialGraph:
    """The materials and maps of a Scene, read on demand and cached."""

    def __init__(self, scene):
        self.scene = scene
        self._cache = {}
        self.issues = []

    def superclass(self, i):
        """Object i's superclass; None for a special id or an index outside the objects."""
        if not 0 <= i < len(self.scene):
            return None
        entry = self.scene.entry(i)
        return None if entry is None else entry.superclass

    def is_mtlbase(self, i):
        return self.superclass(i) in MTLBASE_SUPERCLASSES

    def _blocks(self, i, refs, issues):
        """{slot: ParamBlock2}, {slot: ParamBlock} among the references of object i."""
        blocks, legacy = {}, {}
        entry = self.scene.entry(i)
        owner_class = None if entry is None else (entry.superclass, entry.class_id)
        for slot, target in sorted(refs.items()):
            sc = self.superclass(target)
            try:
                if sc == classids.SC_PARAMETER_BLOCK2:
                    b = pblock.ParamBlock2.from_chunk(self.scene.chunk(target), self.scene.refs(target), refs,
                                                      len(self.scene), owner_class)
                    blocks[slot] = b
                    issues.extend("block at slot %d: %s" % (slot, x) for x in b.issues)
                elif sc == classids.SC_PARAMETER_BLOCK:
                    b = pblock.ParamBlock.from_chunk(self.scene.chunk(target))
                    legacy[slot] = b
                    issues.extend("old block at slot %d: %s" % (slot, x) for x in b.issues)
            except ChunkError as e:
                issues.append("block at slot %d (object %d) left out: %s" % (slot, target, e))
        return blocks, legacy

    def get(self, i):
        """The MtlBase of object i; ChunkError when it is not a material or map, or its references are damaged."""
        m = self._cache.get(i)
        if m is not None:
            return m
        if not 0 <= i < len(self.scene):
            raise ChunkError("object index %d outside the %d objects" % (i, len(self.scene)))
        entry = self.scene.entry(i)
        if entry is None or entry.superclass not in MTLBASE_SUPERCLASSES:
            raise ChunkError("object %d is not a material or map" % i)
        chunk = self.scene.chunk(i)
        refs = self.scene.refs(i) if chunk.container else {}
        issues = []
        blocks, legacy = self._blocks(i, refs, issues)
        parts, children = {}, []
        for slot, target in sorted(refs.items()):
            sc = self.superclass(target)
            if sc in MTLBASE_SUPERCLASSES:
                children.append(target)
            elif sc in PART_SUPERCLASSES:
                try:
                    part_refs = self.scene.refs(target) if self.scene.chunk(target).container else {}
                except ChunkError as e:
                    issues.append("part at slot %d (object %d) left out: %s" % (slot, target, e))
                    continue
                pb2, pb1 = self._blocks(target, part_refs, issues)
                parts[slot] = Part(target, self.scene.entry(target).class_id, sc, pb2, pb1)
            elif (sc == classids.SC_PARAMETER_BLOCK2 and slot in blocks) or sc == classids.SC_TEXMAP_CONTAINER:
                try:
                    held = self.scene.refs(target)
                except ChunkError as e:
                    issues.append("references of object %d (slot %d) left out: %s" % (target, slot, e))
                    continue
                children.extend(t for _s, t in sorted(held.items()) if self.superclass(t) in MTLBASE_SUPERCLASSES)
        seen = set()
        children = [c for c in children if not (c in seen or seen.add(c)) and c != i]
        m = MtlBase(i, entry.class_id, entry.superclass, _name(chunk), refs, blocks, legacy, parts, children, issues)
        self._cache[i] = m
        return m

    def walk(self, roots):
        """Object indices of every material and map reachable from roots, depth first (a material, then its
        children in order), each once. Roots that are not materials or maps are skipped; an object that cannot be
        read is listed in issues and its children are not followed."""
        out, seen = [], set()
        stack = [r for r in reversed(list(roots)) if r is not None]
        while stack:
            i = stack.pop()
            if i in seen:
                continue
            seen.add(i)
            try:
                if not 0 <= i < len(self.scene):
                    raise ChunkError("object index %d outside the %d objects" % (i, len(self.scene)))
                if not self.is_mtlbase(i):
                    continue
                m = self.get(i)
            except ChunkError as e:
                self.issues.append(Issue(i, str(e)))
                continue
            out.append(i)
            stack.extend(c for c in reversed(m.children) if c not in seen)
        return out


def _leaf_u32s(scene, index, ids):
    """{chunk id: u32} of the leaf children of object index with those ids, the first of each; {} when unreadable."""
    out = {}
    if not 0 <= index < len(scene):  # a reference past the objects reads as no chunk
        return out
    try:
        chunk = scene.chunk(index)
        if not chunk.container:
            return out
        for c in chunk.children:
            if c.id in ids and not c.container and c.payload_size >= 4 and c.id not in out:
                out[c.id] = c.unpack("<I")[0]
    except MaxFileError:
        return {}
    return out


def placement(scene, index):
    """The Placement of the UVGen object index; a missing flags chunk means both axes tiled, nothing mirrored."""
    raw = _leaf_u32s(scene, index, (_UV_FLAGS, _UV_AXIS, _UV_MAPPING_TYPE, _UV_SOURCE, _UV_CHANNEL, _UV_ENVIRONMENT))
    flags = raw.get(_UV_FLAGS, _U_TILE | _V_TILE)
    return Placement(tile=(bool(flags & _U_TILE), bool(flags & _V_TILE)),
                     mirror=(bool(flags & _U_MIRROR), bool(flags & _V_MIRROR)),
                     real_world=bool(flags & _REAL_WORLD), axis=raw.get(_UV_AXIS),
                     environment=raw.get(_UV_MAPPING_TYPE, 0) != 0, source=raw.get(_UV_SOURCE),
                     channel=raw.get(_UV_CHANNEL), env_mapping=raw.get(_UV_ENVIRONMENT))


def output_invert(scene, index):
    """Whether the Output (TexOutput) object index inverts its map; False when its flags cannot be read."""
    return bool(_leaf_u32s(scene, index, (_OUT_FLAGS,)).get(_OUT_FLAGS, 0) & _OUT_INVERT)


def bitmap_gamma(scene, m):
    """The gamma override of Bitmap m as stored (any float, NaN included), None for automatic or when its
    BitmapInfo cannot be read: read from the chunk of the first reference that holds a block with id 0."""
    for slot, block in sorted(m.blocks.items()):
        if block.block_id != 0 or slot not in m.refs:
            continue
        if not 0 <= m.refs[slot] < len(scene):
            return None
        try:
            chunk = scene.chunk(m.refs[slot])
            holders = [c for c in chunk.children if c.id == _BITMAP_DATA and c.container] if chunk.container else []
            info = holders[0].first(_BITMAP_INFO) if holders else None
            if info is None or info.container or info.payload_size < _BI_TAIL:
                return None
            data = info.tobytes()
        except MaxFileError:
            return None
        gamma, flags = struct.unpack_from("<fI", data, len(data) - _BI_TAIL)
        return gamma if flags & _BI_GAMMA_OVERRIDE else None
    return None


def standard_maps(scene, m):
    """The StdMaps of Standard material m, read from the first Texmaps object (superclass 0x1080, STD_TEXMAPS) it
    references: its leaves _STD_ON (u32) and _STD_AMOUNT + channel (f32, as stored), channel k's map at its reference
    2k + 1 (a reference that is not a map is none), channels below STD_CHANNELS. None when m references no Texmaps
    object or it cannot be read: no on mask, a leaf not of 4 bytes, damaged references."""
    for _slot, target in sorted(m.refs.items()):
        if not 0 <= target < len(scene):
            continue
        entry = scene.entry(target)
        if entry is None or entry.superclass != classids.SC_TEXMAP_CONTAINER or \
                entry.class_id != classids.STD_TEXMAPS:
            continue
        try:
            chunk = scene.chunk(target)
            if not chunk.container:
                return None
            enabled, amounts = None, {}
            for c in chunk.children:
                k = c.id - _STD_AMOUNT
                if c.id == _STD_ON or 0 <= k < STD_CHANNELS:
                    if c.container or c.payload_size != 4:
                        return None
                    if c.id == _STD_ON:
                        enabled = c.unpack("<I")[0]
                    else:
                        amounts.setdefault(k, c.unpack("<f")[0])
            if enabled is None:
                return None
            maps = {}
            for slot, ref in scene.refs(target).items():  # raises for a reference past the objects
                k, held = (slot - 1) // 2, scene.entry(ref)
                if slot % 2 == 1 and k < STD_CHANNELS and held is not None and held.superclass == classids.SC_TEXMAP:
                    maps[k] = ref
        except MaxFileError:
            return None
        return StdMaps(maps, enabled, amounts)
    return None


def _curve_error(index, why):
    return ChunkError("the curve control at object %d: %s" % (index, why))


def mix_curve(scene, m):
    """The CurvePoints, x ascending, of the curve of the first Custom Curve Control m references (a Falloff's
    MixCurve); None when it references none. ChunkError when that curve cannot be read: no curve, a point count
    outside 2..MAX_CURVE_POINTS or other than the points stored, a point record not of 28 bytes, a value that is
    not finite, x going back."""
    control = None
    for _slot, target in sorted(m.refs.items()):
        if not 0 <= target < len(scene):
            continue
        entry = scene.entry(target)
        if entry is not None and entry.superclass == classids.SC_REF_MAKER and \
                entry.class_id == classids.CURVE_CONTROL:
            control = target
            break
    if control is None:
        return None
    curve = scene.refs(control).get(0)
    entry = scene.entry(curve) if curve is not None else None
    if entry is None or entry.superclass != classids.SC_REF_MAKER or entry.class_id != classids.CURVE:
        raise _curve_error(control, "no curve at its reference 0")
    chunk = scene.chunk(curve)
    count = chunk.first(_CURVE_COUNT) if chunk.container else None
    if count is None or count.container or count.payload_size != 4:
        raise _curve_error(control, "no point count")
    n = count.unpack("<I")[0]
    if not 2 <= n <= MAX_CURVE_POINTS:
        raise _curve_error(control, "%d points, not 2 to %d" % (n, MAX_CURVE_POINTS))
    holders = [c for c in chunk.children if c.id == _CURVE_POINT]
    if len(holders) != n:
        raise _curve_error(control, "%d points stored for a count of %d" % (len(holders), n))
    points = []
    for h in holders:
        data = h.first(_POINT_DATA) if h.container else None
        if data is None or data.container or data.payload_size != _POINT.size:
            raise _curve_error(control, "a point record not of %d bytes" % _POINT.size)
        x, y, ix, iy, ox, oy, flags = data.unpack(_POINT.format)
        if not all(math.isfinite(v) for v in (x, y, ix, iy, ox, oy)):
            raise _curve_error(control, "a value that is not finite")
        if points and x < points[-1].point[0]:
            raise _curve_error(control, "points out of order")
        points.append(CurvePoint((x, y), (ix, iy), (ox, oy), flags))
    return tuple(points)
