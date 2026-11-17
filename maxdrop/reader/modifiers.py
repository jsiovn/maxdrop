# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The modifier stack of a node: every modifier from the bottom of the stack up, down to the base object.

    reader = Modifiers(scene)
    st = reader.stack(node)             # ModifierStack(base, modifiers bottom first, derived objects, issues)
    st = reader.object_stack(i)         # the same from an object reference (a node's slot 1)
    m = st.modifiers[0]
    m.class_id, m.superclass, m.name    # name: the one the user gave, else the class directory's
    m.enabled, m.enabled_in_views, m.enabled_in_renders, m.active, m.renders
    m.context.tm, m.context.box         # the modifier context on this node: 4x4 rows, ((min), (max)) or None
    m.blocks, m.legacy, m.gizmo         # {slot: ParamBlock2}, {slot: ParamBlock}, the gizmo controller's index
    stack(scene, node)                  # one-off, without the cache

A derived object (special id 0x2032, past the class directory) references [modifier, ..., object], the top of the
stack first; the object can be another derived object (a reference: the modifiers above the reference line wrap
the shared ones). Its k-th 0x2500 is the modifier context of reference slot k: 0x2510 = a Matrix3 (12 x f32, rows
1 to 4, then u32 flags) and 0x2511 = the context's box (min, max), +1e30 .. -1e30 when Max had not computed it
before saving. A world-space modifier sits in a 0x2033 derived object, [world-space modifiers, the object's derived
object], so it comes above every object-space modifier. A modifier keeps 0x39BF{0x0100: UTF-16 name, empty = the
class name; 0x0110 present: off; 0x0120: off in the viewport; 0x0130: off in the renderer}. Its parameter blocks
and gizmo controller (superclass 0x9008) are among its references. docs/FORMAT.md says which fixture shows what.

The stack is read, never evaluated: the file holds no result of it. The file comes from anywhere: a derived-object
cycle or a damaged derived object raises ChunkError (as Scene.object_stack does); a missing or damaged context
poisons only that modifier's context, a modifier whose chunk or references cannot be read only that modifier (the
class name, every switch on, no blocks), and an object that is not a modifier (superclass 0x810 or 0x820) in a
modifier slot is kept (class_id None for a special id): each is named in issues. A modifier object shared by
several stacks is read once and its issues are named in every stack holding it; its blocks, legacy and refs dicts
are shared too, so they are read-only. No bpy.
"""
import collections
import math
import struct

from . import chunks, classids, pblock

ChunkError = chunks.ChunkError

DERIVED_OBJECT, WSM_DERIVED_OBJECT = 0x2032, 0x2033
DERIVED_IDS = (DERIVED_OBJECT, WSM_DERIVED_OBJECT)
_CONTEXT, _CONTEXT_TM, _CONTEXT_BOX = 0x2500, 0x2510, 0x2511
_INFO, _NAME, _OFF, _OFF_IN_VIEWS, _OFF_IN_RENDERS = 0x39BF, 0x0100, 0x0110, 0x0120, 0x0130
MODIFIER_SUPERCLASSES = (classids.SC_OSMODIFIER, classids.SC_WSMODIFIER)
_TM = struct.Struct("<12f")
_BOX = struct.Struct("<6f")


class Context(collections.namedtuple("Context", "tm box")):
    """A modifier's context on one node: tm, a 4x4 tuple of row tuples (row-vector convention, row 4 = the
    translation), and box ((min x, y, z), (max x, y, z)) in the space of tm, None when the file holds none."""
    __slots__ = ()


class Modifier(collections.namedtuple("Modifier", "index class_id superclass name enabled enabled_in_views "
                                                  "enabled_in_renders context blocks legacy refs gizmo derived "
                                                  "world_space")):
    """One modifier of a stack. index is the modifier object's (the same in every stack it is instanced in),
    refs its references {slot: object index}, gizmo the object index of its gizmo's transform controller (None
    without one), derived the derived object holding it here, world_space whether it is a world-space modifier;
    context is None when its matrix could not be read."""
    __slots__ = ()

    @property
    def active(self):
        """Whether it changes the object in the viewport."""
        return self.enabled and self.enabled_in_views

    @property
    def renders(self):
        """Whether it changes the object in a render."""
        return self.enabled and self.enabled_in_renders


class ModifierStack(collections.namedtuple("ModifierStack", "base modifiers derived issues")):
    """base: the base object's index (None for no object or an empty base slot); modifiers: bottom of the stack
    first; derived: the derived objects passed through, outermost first; issues: (object index, reason)."""
    __slots__ = ()


class _Info(collections.namedtuple("_Info", "class_id superclass name flags blocks legacy refs gizmo issues")):
    __slots__ = ()


def _matrix(chunk):
    if chunk is None:
        raise ChunkError("no matrix (0x2510)")
    if chunk.payload_size < _TM.size:
        raise ChunkError("0x2510 of %d bytes" % chunk.payload_size)
    v = _TM.unpack(chunk.view()[:_TM.size])
    if not all(math.isfinite(x) for x in v):
        raise ChunkError("the matrix is not finite")
    return tuple(tuple(float(x) for x in v[r * 3:r * 3 + 3]) + (1.0 if r == 3 else 0.0,) for r in range(4))


def _box(chunk):
    if chunk is None:
        return None
    if chunk.payload_size < _BOX.size:
        raise ChunkError("0x2511 of %d bytes" % chunk.payload_size)
    v = tuple(float(x) for x in _BOX.unpack(chunk.view()[:_BOX.size]))
    if not all(math.isfinite(x) for x in v):
        raise ChunkError("the box is not finite")
    lo, hi = v[:3], v[3:]
    if any(a > b for a, b in zip(lo, hi)):  # the empty box: not computed when the file was saved
        return None
    return lo, hi


class Modifiers:
    """The modifier stacks of a scene.Scene, each modifier object read once."""

    def __init__(self, scene):
        self.scene = scene
        self._info = {}

    def _derived_kind(self, i):
        """0x2032 or 0x2033 when object i is a derived object (a special id no class claims), else None."""
        cid = self.scene.class_index(i)
        return cid if cid in DERIVED_IDS and self.scene.entry(i) is None else None

    def _superclass(self, i):
        entry = self.scene.entry(i) if 0 <= i < len(self.scene) else None
        return None if entry is None else entry.superclass

    def _blocks(self, i, refs, owner, issues):
        s = self.scene
        blocks, legacy = {}, {}
        for slot, target in sorted(refs.items()):
            sc = self._superclass(target)
            try:
                if sc == classids.SC_PARAMETER_BLOCK2:
                    b = pblock.ParamBlock2.from_chunk(s.chunk(target), s.refs(target), refs, len(s), owner)
                    blocks[slot] = b
                    issues.extend((i, "block at slot %d: %s" % (slot, x)) for x in b.issues)
                elif sc == classids.SC_PARAMETER_BLOCK:
                    b = pblock.ParamBlock.from_chunk(s.chunk(target))
                    legacy[slot] = b
                    issues.extend((i, "old block at slot %d: %s" % (slot, x)) for x in b.issues)
            except ChunkError as e:
                issues.append((i, "block at slot %d (object %d) left out: %s" % (slot, target, e)))
        return blocks, legacy

    def _read_info(self, i):
        """The _Info of modifier object i, read once; its issues go to every stack holding it."""
        info = self._info.get(i)
        if info is not None:
            return info
        entry = self.scene.entry(i)
        class_id, superclass = (None, None) if entry is None else (entry.class_id, entry.superclass)
        name, issues = ("" if entry is None else entry.name), []
        if superclass not in MODIFIER_SUPERCLASSES:
            issues.append((i, "not a modifier (superclass %s) in a modifier slot" %
                           ("none" if superclass is None else "0x%X" % superclass)))
        try:
            chunk = self.scene.chunk(i)
            flags = frozenset()
            held = chunk.first(_INFO) if chunk.container else None
            if held is not None and held.container:
                text = held.first(_NAME)
                if text is not None:
                    name = text.text() or name
                flags = frozenset(c for c in (_OFF, _OFF_IN_VIEWS, _OFF_IN_RENDERS) if held.first(c) is not None)
            refs = self.scene.refs(i) if chunk.container else {}
        except ChunkError as e:
            issues.append((i, "modifier left out of its stack's reading (class name, every switch on): %s" % e))
            info = _Info(class_id, superclass, name, frozenset(), {}, {}, {}, None, tuple(issues))
        else:
            owner = None if entry is None else (superclass, class_id)
            blocks, legacy = self._blocks(i, refs, owner, issues)
            gizmo = next((t for _s, t in sorted(refs.items()) if self._superclass(t) == classids.SC_CTRL_MATRIX3),
                         None)
            info = _Info(class_id, superclass, name, flags, blocks, legacy, refs, gizmo, tuple(issues))
        self._info[i] = info
        return info

    @staticmethod
    def _context(d, k, contexts, issues):
        if k >= len(contexts) or not contexts[k].container:
            issues.append((d, "no modifier context for reference slot %d" % k))
            return None
        c = contexts[k]
        tm = box = None
        try:
            tm = _matrix(c.first(_CONTEXT_TM))
        except ChunkError as e:
            issues.append((d, "modifier context %d: %s" % (k, e)))
        try:
            box = _box(c.first(_CONTEXT_BOX))
        except ChunkError as e:
            issues.append((d, "modifier context %d: %s" % (k, e)))
        return None if tm is None else Context(tm, box)

    def object_stack(self, i):
        """The ModifierStack behind object reference i (None: no object); IndexError outside the objects."""
        if i is None:
            return ModifierStack(None, (), (), ())
        self.scene.class_index(i)
        levels, derived, issues, seen = [], [], [], set()
        while i is not None:
            kind = self._derived_kind(i)
            if kind is None:
                break
            if i in seen:
                raise ChunkError("derived object %d references itself through its stack" % i)
            seen.add(i)
            derived.append(i)
            refs = self.scene.ref_list(i)
            chunk = self.scene.chunk(i)
            contexts = chunk.find_all(_CONTEXT) if chunk.container else []
            level = []
            for k, m in enumerate(refs[:-1]):
                if m is None:
                    continue
                info = self._read_info(m)
                issues.extend(info.issues)
                level.append(Modifier(m, info.class_id, info.superclass, info.name, _OFF not in info.flags,
                                      _OFF_IN_VIEWS not in info.flags, _OFF_IN_RENDERS not in info.flags,
                                      self._context(i, k, contexts, issues), info.blocks, info.legacy, info.refs,
                                      info.gizmo, i, kind == WSM_DERIVED_OBJECT))
            levels.append(level)
            i = refs[-1] if refs else None
        mods = [m for level in levels for m in level]  # top first: an outer derived object's modifiers are on top
        mods.reverse()
        return ModifierStack(i, tuple(mods), tuple(derived), tuple(issues))

    def stack(self, node):
        """The ModifierStack of a scene.Node."""
        return self.object_stack(node.object)


def stack(scene, node):
    """The ModifierStack of a scene.Node, read without a cache."""
    return Modifiers(scene).stack(node)
