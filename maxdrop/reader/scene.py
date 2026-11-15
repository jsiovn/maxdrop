# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The objects of the Scene stream by object index: class, references, and node records with their hierarchy.

    with CompoundFile(path) as cf:
        scene = Scene.from_file(cf)
        scene.entry(i)                  # ClassEntry of object i, None for a special id (0x2032)
        scene.refs(i)                   # {slot: object index}
        node = scene.node(scene.node_indices[0])
        node.name, node.parent, node.flags, node.pivot_position, node.object
        scene.walk()                    # every node, pre-order from the top level
        scene.object_stack(node.object) # Stack(base, modifiers top first, derived objects)

The Scene stream holds one root container (0x2014, 0x2023 or 0x2025 so far); its children are the objects. The
object index is a child's position, its chunk id the class index into the class directory. References: 0x2034
is an i32 array (position = slot, -1 = empty); 0x2035 is a u32 (meaning unknown) then (u32 slot, i32 index)
pairs. A Node (class (1, 0), superclass 1) has 0x0962 name, 0x0960 i32 parent + u32 flags, 0x096A/B/C pivot
offset position, rotation and scale (+ scale axis), and reference slots 0 = transform controller, 1 = object,
3 = material, 6 = layer. A derived object (special id 0x2032) references [modifier, ..., base object], the top
of the stack first; its base can be another derived object. docs/FORMAT.md says which fixture shows what.

Nodes are keyed by object index, never by name: two nodes with the same name are two nodes. A parent that is not
a Node (the RootNode, another class, out of range) means top level. A parent cycle is cut at its member with the
lowest object index, which becomes top level and is listed in cut_cycles. A reference past the object list, a
payload of the wrong size or a derived-object cycle raises ChunkError (a ValueError). Every walk is iterative and
bounded by the object count. No bpy.
"""
import collections
import struct

from . import chunks, classdir, classids

ChunkError = chunks.ChunkError

ROOT_IDS = {0x2014: "3ds Max 2012 format", 0x2023: "3ds Max 2018 format", 0x2025: "3ds Max 2020 format"}
DERIVED_OBJECT = 0x2032
SLOT_TM, SLOT_OBJECT, SLOT_MATERIAL, SLOT_LAYER = 0, 1, 3, 6

_REFS, _REF_PAIRS = 0x2034, 0x2035
_NODE_PARENT, _NODE_NAME = 0x0960, 0x0962
_PIVOT_POSITION, _PIVOT_ROTATION, _PIVOT_SCALE = 0x096A, 0x096B, 0x096C
_I32 = struct.Struct("<i")


class Stack(collections.namedtuple("Stack", "base modifiers derived")):
    """What an object reference stands for: the base object's index (None when a derived object has an empty base
    slot), the modifiers from the top of the stack down, and the derived objects passed through, outermost
    first."""
    __slots__ = ()


class Node:
    """One node. parent is the parent node's object index after cycle cutting (None = top level); parent_index is
    the index as stored."""
    __slots__ = ("index", "name", "parent", "parent_index", "flags", "pivot_position", "pivot_rotation",
                 "pivot_scale", "pivot_scale_axis", "refs")

    def __init__(self, index, name, parent, parent_index, flags, pivot_position, pivot_rotation, pivot_scale,
                 pivot_scale_axis, refs):
        self.index, self.name, self.parent, self.parent_index, self.flags = index, name, parent, parent_index, flags
        self.pivot_position, self.pivot_rotation = pivot_position, pivot_rotation
        self.pivot_scale, self.pivot_scale_axis, self.refs = pivot_scale, pivot_scale_axis, refs

    def __repr__(self):
        return "Node(%d, %r, parent=%r)" % (self.index, self.name, self.parent)

    @property
    def tm(self):
        return self.refs.get(SLOT_TM)

    @property
    def object(self):
        return self.refs.get(SLOT_OBJECT)

    @property
    def material(self):
        return self.refs.get(SLOT_MATERIAL)

    @property
    def layer(self):
        return self.refs.get(SLOT_LAYER)


def _floats(chunk, count, default):
    if chunk is None:
        return default
    return chunk.unpack("<%df" % count)


class Scene:
    """The objects of a Scene stream (bytes-like or cfb.Stream) with the file's ClassDirectory."""

    def __init__(self, data, classes, max_depth=chunks.DEFAULT_MAX_DEPTH, max_chunks=chunks.DEFAULT_MAX_CHUNKS):
        top = chunks.index(data, max_depth, max_chunks)
        if not len(top):
            raise ChunkError("the Scene stream is empty")
        root = top[0]
        if not root.container:
            raise ChunkError("the Scene stream starts with a leaf chunk %04X, not a container" % root.id)
        self.classes = classes
        self.root_id = root.id
        self._root = root
        self._objects = root.children
        self._ids = self._objects.ids
        self._nodes = {}
        self._parents = None
        self._children = None
        self._cut = ()
        node_classes, root_classes = set(), set()
        for entry in classes:
            if entry.superclass == classids.SC_BASENODE:
                if entry.class_id == classids.NODE:
                    node_classes.add(entry.index)
                elif entry.class_id == classids.ROOT_NODE:
                    root_classes.add(entry.index)
        self.node_indices = tuple(i for i, cid in enumerate(self._ids) if cid in node_classes)
        self._node_set = frozenset(self.node_indices)
        self.root_node = next((i for i, cid in enumerate(self._ids) if cid in root_classes), None)

    @classmethod
    def from_file(cls, cf, classes=None):
        """From an open cfb.CompoundFile; the class directory is read from it unless given."""
        if classes is None:
            classes = classdir.ClassDirectory.from_file(cf)
        return cls(cf.open("Scene"), classes)

    def __len__(self):
        return len(self._ids)

    def __repr__(self):
        return "Scene(root 0x%04X, %d objects, %d nodes)" % (self.root_id, len(self._ids), len(self.node_indices))

    def _check(self, i):
        if not 0 <= i < len(self._ids):
            raise IndexError("object index %d out of range (%d objects)" % (i, len(self._ids)))

    def class_index(self, i):
        self._check(i)
        return self._ids[i]

    def entry(self, i):
        """The ClassEntry of object i, None when its id is not a class index (a derived object)."""
        return self.classes.get(self.class_index(i))

    def chunk(self, i):
        self._check(i)
        return self._objects[i]

    def span(self, i):
        """(offset, size) of object i's chunk in the stream, header included."""
        chunk = self.chunk(i)
        return chunk.offset, chunk.size

    def is_a(self, i, superclass, class_id):
        entry = self.entry(i)
        return entry is not None and entry.superclass == superclass and entry.class_id == class_id

    def _target(self, i, value):
        if not 0 <= value < len(self._ids):
            raise ChunkError("object %d references %d, outside the %d objects" % (i, value, len(self._ids)))
        return value

    def ref_list(self, i):
        """The 0x2034 references of object i in slot order, None for an empty slot ([] without the chunk)."""
        chunk = self.chunk(i)
        refs = chunk.first(_REFS) if chunk.container else None
        if refs is None:
            return []
        n, rest = divmod(refs.payload_size, 4)
        if rest:
            raise ChunkError("object %d: 0x2034 of %d bytes is not a whole number of i32" % (i, refs.payload_size))
        return [None if v == -1 else self._target(i, v) for v in refs.unpack("<%di" % n)]

    def refs(self, i):
        """{slot: object index} of object i, from 0x2034 and 0x2035; empty slots are left out."""
        out = {slot: v for slot, v in enumerate(self.ref_list(i)) if v is not None}
        chunk = self.chunk(i)
        pairs = chunk.first(_REF_PAIRS) if chunk.container else None
        if pairs is not None:
            n, rest = divmod(pairs.payload_size - 4, 8)
            if pairs.payload_size < 4 or rest:
                raise ChunkError("object %d: 0x2035 of %d bytes is not a u32 and (slot, index) pairs" %
                                 (i, pairs.payload_size))
            values = pairs.unpack("<I" + "Ii" * n, 0)
            for k in range(1, len(values), 2):
                if values[k + 1] != -1:
                    out[values[k]] = self._target(i, values[k + 1])
        return out

    def _raw_parent(self, i):
        chunk = self.chunk(i)
        parent = chunk.first(_NODE_PARENT)
        if parent is None:
            return None, 0
        if parent.payload_size < 4:
            raise ChunkError("node %d: 0x0960 of %d bytes" % (i, parent.payload_size))
        index, = parent.unpack("<i")
        flags, = parent.unpack("<I", 4) if parent.payload_size >= 8 else (0,)
        return index, flags

    def _hierarchy(self):
        if self._parents is not None:
            return
        parents = {}
        for i in self.node_indices:
            p, _flags = self._raw_parent(i)
            parents[i] = p if p in self._node_set else None
        state, cut = {}, []  # state: 1 = on the current chain, 2 = settled
        for start in self.node_indices:
            chain, i = [], start
            while i is not None and i not in state:
                state[i] = 1
                chain.append(i)
                i = parents[i]
            if i is not None and state[i] == 1:  # the chain ran into itself: i..chain[-1] is a cycle
                loop = chain[chain.index(i):]
                low = min(loop)
                parents[low] = None
                cut.append(low)
            for j in chain:
                state[j] = 2
        children = collections.defaultdict(list)
        for i in self.node_indices:  # object index order, so every child list is sorted
            children[parents[i]].append(i)
        self._parents = parents
        self._children = {k: tuple(v) for k, v in children.items()}
        self._cut = tuple(sorted(cut))

    @property
    def cut_cycles(self):
        """The nodes whose stored parent closed a cycle, now top level."""
        self._hierarchy()
        return self._cut

    def parent(self, i):
        """The parent node of node i, None at the top level."""
        if i not in self._node_set:
            raise ChunkError("object %d is not a node" % i)
        self._hierarchy()
        return self._parents[i]

    def children(self, i=None):
        """The child nodes of node i in object index order; i = None gives the top-level nodes."""
        if i is not None and i not in self._node_set:
            raise ChunkError("object %d is not a node" % i)
        self._hierarchy()
        return self._children.get(i, ())

    def walk(self):
        """Every node once, pre-order from the top level, children in object index order."""
        self._hierarchy()
        out, stack = [], list(reversed(self.children()))
        while stack:
            i = stack.pop()
            out.append(i)
            stack.extend(reversed(self._children.get(i, ())))
        return out

    def node(self, i):
        node = self._nodes.get(i)
        if node is not None:
            return node
        self._check(i)
        if i not in self._node_set:
            raise ChunkError("object %d is not a node" % i)
        chunk = self.chunk(i)
        name = chunk.first(_NODE_NAME)
        parent_index, flags = self._raw_parent(i)
        scale = chunk.first(_PIVOT_SCALE)
        if scale is None:
            scale = (1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        elif scale.payload_size < 28:  # no scale axis
            scale = scale.unpack("<3f") + (0.0, 0.0, 0.0, 1.0)
        else:
            scale = scale.unpack("<7f")
        node = Node(i, name.text() if name is not None else "", self.parent(i), parent_index, flags,
                    _floats(chunk.first(_PIVOT_POSITION), 3, (0.0, 0.0, 0.0)),
                    _floats(chunk.first(_PIVOT_ROTATION), 4, (0.0, 0.0, 0.0, 1.0)), scale[:3], scale[3:],
                    self.refs(i))
        self._nodes[i] = node
        return node

    def nodes(self):
        """Every node record in object index order."""
        return [self.node(i) for i in self.node_indices]

    def object_stack(self, i):
        """The object behind reference i: through derived objects down to the base object."""
        self._check(i)
        modifiers, derived, seen = [], [], set()
        while i is not None and self._ids[i] == DERIVED_OBJECT:
            if i in seen:
                raise ChunkError("derived object %d references itself through its stack" % i)
            seen.add(i)
            derived.append(i)
            refs = self.ref_list(i)
            if not refs:
                i = None
                break
            modifiers.extend(r for r in refs[:-1] if r is not None)
            i = refs[-1]
        return Stack(i, tuple(modifiers), tuple(derived))
