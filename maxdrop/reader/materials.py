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
and through reference cycles, each object visited once, bounded by the object count. No bpy.
"""
import collections

from . import chunks, classids, pblock

ChunkError = chunks.ChunkError

PART_SUPERCLASSES = frozenset((classids.SC_UVGEN, classids.SC_XYZGEN, classids.SC_TEXOUTPUT, classids.SC_SHADER,
                               classids.SC_SAMPLER))
MTLBASE_SUPERCLASSES = frozenset((classids.SC_MATERIAL, classids.SC_TEXMAP))
_NAME = 0x4001


class Part(collections.namedtuple("Part", "index class_id superclass blocks legacy")):
    """A reference of a material or map that carries parameter blocks of its own."""
    __slots__ = ()


class Issue(collections.namedtuple("Issue", "index reason")):
    __slots__ = ()


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
        for slot, target in sorted(refs.items()):
            sc = self.superclass(target)
            try:
                if sc == classids.SC_PARAMETER_BLOCK2:
                    b = pblock.ParamBlock2.from_chunk(self.scene.chunk(target), self.scene.refs(target), refs,
                                                      len(self.scene))
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
        try:
            entry = self.scene.entry(i)
        except IndexError as e:
            raise ChunkError(str(e))
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
