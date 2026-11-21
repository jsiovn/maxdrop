# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The objects of the Scene stream by object index: class, references, and node records with their hierarchy.

    with CompoundFile(path) as cf:
        scene = Scene.from_file(cf)
        scene.entry(i)                  # ClassEntry of object i, None for a special id (0x2032, 0x2033)
        scene.refs(i)                   # {slot: object index}
        node = scene.node(scene.node_indices[0])
        node.name, node.parent, node.flags, node.pivot_position, node.object
        scene.walk()                    # every node, pre-order from the top level
        scene.object_stack(node.object) # Stack(base, modifiers top first, derived objects)
        node.hidden, node.frozen, node.renderable, node.group_head, node.group_member
        scene.layers()                  # Layer records in the Layer Manager's order
        scene.layer(node.layer)         # name, hidden, frozen, renderable, parent (a layer's object index)

The Scene stream holds one root container (0x2014, 0x2022, 0x2023 or 0x2025 so far); its children are the objects. The
object index is a child's position, its chunk id the class index into the class directory. References: 0x2034
is an i32 array (position = slot, -1 = empty); 0x2035 is a u32 (meaning unknown) then (u32 slot, i32 index)
pairs. A Node (class (1, 0), superclass 1) has 0x0962 name, 0x0960 i32 parent + u32 flags, 0x096A/B/C pivot
offset position, rotation and scale (+ scale axis), and reference slots 0 = transform controller, 1 = object,
3 = material, 6 = layer. The 0x0960 flags hold hidden (0x100000), frozen (0x200000), group head (0x40) and group
member (0x100); bit 0x8000 of the u32 in 0x099C is renderable. A layer is a Base Layer: 0x1010 its name (UTF-8),
0x1020 the same hidden and frozen bits, bit 0x8000 of 0x1050 renderable and, when the byte 0x1090 is not 0, 0x10B0
the i32 object index of its parent layer. The Layer Manager references the layers in its order (slot 0 = layer
"0"). A derived object (special id 0x2032) references [modifier, ..., base object], the top
of the stack first; its base can be another derived object. A world-space modifier sits in a derived object of its
own (special id 0x2033), [world-space modifiers, the object's 0x2032 derived object or its base object], read the
same way. docs/FORMAT.md says which fixture shows what.

Nodes are keyed by object index, never by name: two nodes with the same name are two nodes. A parent that is not
a Node (the RootNode, another class, out of range) means top level. A parent cycle is cut at its member with the
lowest object index, which becomes top level and is listed in cut_cycles; a layer's parent cycle is cut the same
way, and a parent layer that is not a layer or cannot be read means top level. A reference past the object list,
more than MAX_REFS references in one object, more than MAX_NODES nodes, a payload of the wrong size, a
derived-object cycle or a file without a Scene stream raise ChunkError (a MaxFileError). One damaged record poisons
only itself: a node whose 0x0960 cannot be read is top level for the hierarchy (listed in bad_parents) while node()
on it raises. Every walk is iterative
and bounded by the object count. No bpy.
"""
import collections
import struct

from . import chunks, classdir, classids, strings as strings_mod

ChunkError = chunks.ChunkError

ROOT_IDS = frozenset((0x2014, 0x2022, 0x2023, 0x2025))  # root container ids seen so far; others are read the same way
DERIVED_OBJECT, WSM_DERIVED_OBJECT = 0x2032, 0x2033
DERIVED_IDS = (DERIVED_OBJECT, WSM_DERIVED_OBJECT)
MAX_REFS = 1 << 20  # per object and chunk: a hostile payload must not become millions of Python ints
MAX_NODES = 1 << 20  # scene B, the largest corpus scene, has 2 251; Blender is unusable long before this
SLOT_TM, SLOT_OBJECT, SLOT_MATERIAL, SLOT_LAYER = 0, 1, 3, 6
GROUP_HEAD, GROUP_MEMBER, HIDDEN, FROZEN = 0x40, 0x100, 0x100000, 0x200000  # node 0x0960, layer 0x1020
RENDERABLE = 0x8000  # node 0x099C, layer 0x1050

_REFS, _REF_PAIRS = 0x2034, 0x2035
_NODE_PARENT, _NODE_NAME = 0x0960, 0x0962
_PIVOT_POSITION, _PIVOT_ROTATION, _PIVOT_SCALE = 0x096A, 0x096B, 0x096C
_NODE_RENDER = 0x099C
_LAYER_NAME, _LAYER_FLAGS, _LAYER_RENDER, _LAYER_HAS_PARENT, _LAYER_PARENT = 0x1010, 0x1020, 0x1050, 0x1090, 0x10B0
_PAIR = struct.Struct("<Ii")


class Stack(collections.namedtuple("Stack", "base modifiers derived")):
    """What an object reference stands for: the base object's index (None when a derived object has an empty base
    slot), the modifiers from the top of the stack down, and the derived objects passed through, outermost
    first."""
    __slots__ = ()


class Node:
    """One node. parent is the parent node's object index after cycle cutting (None = top level); parent_index is
    the index as stored."""
    __slots__ = ("index", "name", "parent", "parent_index", "flags", "pivot_position", "pivot_rotation",
                 "pivot_scale", "pivot_scale_axis", "refs", "render_flags")

    def __init__(self, index, name, parent, parent_index, flags, pivot_position, pivot_rotation, pivot_scale,
                 pivot_scale_axis, refs, render_flags=RENDERABLE):
        self.index, self.name, self.parent, self.parent_index, self.flags = index, name, parent, parent_index, flags
        self.pivot_position, self.pivot_rotation = pivot_position, pivot_rotation
        self.pivot_scale, self.pivot_scale_axis, self.refs = pivot_scale, pivot_scale_axis, refs
        self.render_flags = render_flags

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

    @property
    def hidden(self):
        return bool(self.flags & HIDDEN)

    @property
    def frozen(self):
        return bool(self.flags & FROZEN)

    @property
    def renderable(self):
        return bool(self.render_flags & RENDERABLE)

    @property
    def group_head(self):
        return bool(self.flags & GROUP_HEAD)

    @property
    def group_member(self):
        return bool(self.flags & GROUP_MEMBER)


class Layer:
    """One layer: parent is the parent layer's object index after cycle cutting (None = top level)."""
    __slots__ = ("index", "name", "flags", "render_flags", "parent")

    def __init__(self, index, name, flags, render_flags, parent):
        self.index, self.name, self.flags, self.render_flags, self.parent = index, name, flags, render_flags, parent

    def __repr__(self):
        return "Layer(%d, %r, parent=%r)" % (self.index, self.name, self.parent)

    @property
    def hidden(self):
        return bool(self.flags & HIDDEN)

    @property
    def frozen(self):
        return bool(self.flags & FROZEN)

    @property
    def renderable(self):
        return bool(self.render_flags & RENDERABLE)


def _u32(chunk, default, what):
    if chunk is None:
        return default
    if chunk.payload_size < 4:
        raise ChunkError("%s: %04X of %d bytes" % (what, chunk.id, chunk.payload_size))
    return chunk.unpack("<I")[0]


def _floats(chunk, count, default):
    if chunk is None:
        return default
    return chunk.unpack("<%df" % count)


class Scene:
    """The objects of a Scene stream (bytes-like or cfb.Stream) with the file's ClassDirectory."""

    def __init__(self, data, classes, max_depth=chunks.DEFAULT_MAX_DEPTH, max_chunks=chunks.DEFAULT_MAX_CHUNKS,
                 strings=None):
        top = chunks.index(data, max_depth, max_chunks, strings)
        if not len(top):
            raise ChunkError("the Scene stream is empty")
        root = top[0]
        if not root.container:
            raise ChunkError("the Scene stream starts with a leaf chunk %04X, not a container" % root.id)
        self.classes = classes
        self.strings = root.strings  # how the names decode: chunks.WIDE or a strings.Strings
        self.root_id = root.id
        self._root = root
        self._objects = root.children
        self._ids = self._objects.ids
        self._nodes = {}
        self._parents = None
        self._children = None
        self._cut = ()
        self._bad_parents = ()
        self._layers = {}
        self._layer_parents = None
        # 0x2032 and 0x2033 stand for derived objects only past the class directory, where no class can claim them
        self._derived = frozenset(x for x in DERIVED_IDS if classes.get(x) is None)
        node_classes, root_classes, layer_classes, manager_classes = set(), set(), set(), set()
        for entry in classes:
            if entry.superclass == classids.SC_BASENODE:
                if entry.class_id == classids.NODE:
                    node_classes.add(entry.index)
                elif entry.class_id == classids.ROOT_NODE:
                    root_classes.add(entry.index)
            elif entry.superclass == classids.SC_LAYER and entry.class_id == classids.BASE_LAYER:
                layer_classes.add(entry.index)
            elif entry.superclass == classids.SC_REF_TARGET and entry.class_id == classids.LAYER_MANAGER:
                manager_classes.add(entry.index)
        self.node_indices = tuple(i for i, cid in enumerate(self._ids) if cid in node_classes)
        if len(self.node_indices) > MAX_NODES:
            raise ChunkError("the scene has %d objects, more than the %d MaxDrop imports"
                             % (len(self.node_indices), MAX_NODES))
        self._node_set = frozenset(self.node_indices)
        self.root_node = next((i for i, cid in enumerate(self._ids) if cid in root_classes), None)
        self.layer_indices = tuple(i for i, cid in enumerate(self._ids) if cid in layer_classes)
        self._layer_set = frozenset(self.layer_indices)
        self._managers = tuple(i for i, cid in enumerate(self._ids) if cid in manager_classes)

    @classmethod
    def from_file(cls, cf, classes=None, encoding="AUTO"):
        """From an open cfb.CompoundFile; the class directory is read from it unless given. encoding: how the
        8-bit strings of a file of 3ds Max 2012 or older decode ("AUTO" or a codec of strings.CODECS)."""
        if not cf.exists("Scene"):
            raise ChunkError("the file has no Scene stream")
        strings = strings_mod.of_file(cf, encoding)
        if classes is None:
            classes = classdir.ClassDirectory.from_file(cf, strings)
        return cls(cf.open("Scene"), classes, strings=strings)

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

    def is_derived(self, i):
        """Whether object i is a derived object (an object with its modifier stack, 0x2032, or its world-space
        modifiers, 0x2033)."""
        return self.class_index(i) in self._derived

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
        if n > MAX_REFS:
            raise ChunkError("object %d: %d references, more than %d" % (i, n, MAX_REFS))
        # Unpacked whole, never through struct.iter_unpack: an iterator over the view holds a buffer export of it,
        # and left in a traceback's frame when _target raises, it crashes Python <= 3.11's garbage collector.
        values = struct.unpack("<%di" % n, refs.view())
        return [None if v == -1 else self._target(i, v) for v in values]

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
            if n > MAX_REFS:
                raise ChunkError("object %d: %d reference pairs, more than %d" % (i, n, MAX_REFS))
            view = pairs.view()
            for k in range(n):  # unpack_from like ref_list: no iterator over the view
                slot, value = _PAIR.unpack_from(view, 4 + 8 * k)
                if value != -1:
                    out[slot] = self._target(i, value)
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
        parents, bad = {}, []
        for i in self.node_indices:
            try:
                p, _flags = self._raw_parent(i)
            except ChunkError:
                p = None
                bad.append(i)
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
        self._bad_parents = tuple(bad)

    @property
    def cut_cycles(self):
        """The nodes whose stored parent closed a cycle, now top level."""
        self._hierarchy()
        return self._cut

    @property
    def bad_parents(self):
        """The nodes whose 0x0960 could not be read, top level in the hierarchy."""
        self._hierarchy()
        return self._bad_parents

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
                    self.refs(i), _u32(chunk.first(_NODE_RENDER), RENDERABLE, "node %d" % i))
        self._nodes[i] = node
        return node

    def nodes(self):
        """Every node record in object index order."""
        return [self.node(i) for i in self.node_indices]

    def _raw_layer_parent(self, i):
        chunk = self.chunk(i)
        if not chunk.container:
            return None
        has = chunk.first(_LAYER_HAS_PARENT)
        if has is None or not has.payload_size or not has.unpack("<B")[0]:
            return None
        parent = chunk.first(_LAYER_PARENT)
        if parent is None:
            return None
        if parent.payload_size < 4:
            raise ChunkError("layer %d: %04X of %d bytes" % (i, parent.id, parent.payload_size))
        return parent.unpack("<i")[0]

    def _layer_hierarchy(self):
        if self._layer_parents is not None:
            return self._layer_parents
        parents = {}
        for i in self.layer_indices:
            try:
                p = self._raw_layer_parent(i)
            except ChunkError:
                p = None
            parents[i] = p if p in self._layer_set else None
        state = {}  # the cycle cut of _hierarchy
        for start in self.layer_indices:
            chain, i = [], start
            while i is not None and i not in state:
                state[i] = 1
                chain.append(i)
                i = parents[i]
            if i is not None and state[i] == 1:
                parents[min(chain[chain.index(i):])] = None
            for j in chain:
                state[j] = 2
        self._layer_parents = parents
        return parents

    def layer(self, i):
        """The Layer record of Base Layer object i; ChunkError when it is not one or cannot be read."""
        layer = self._layers.get(i)
        if layer is not None:
            return layer
        self._check(i)
        if i not in self._layer_set:
            raise ChunkError("object %d is not a layer" % i)
        chunk = self.chunk(i)
        if not chunk.container:
            raise ChunkError("layer %d is a leaf chunk" % i)
        name = chunk.first(_LAYER_NAME)
        if name is None:
            name = ""
        elif self.strings.wide:  # UTF-8 in a file of 3ds Max 2013 or later, unlike its other names
            name = name.tobytes().decode("utf-8", "replace").rstrip("\x00")
        else:
            name = name.text()
        what = "layer %d" % i
        layer = Layer(i, name, _u32(chunk.first(_LAYER_FLAGS), 0, what),
                      _u32(chunk.first(_LAYER_RENDER), RENDERABLE, what), self._layer_hierarchy()[i])
        self._layers[i] = layer
        return layer

    def layer_order(self):
        """Every layer's object index: the Layer Manager's order, then the layers it does not list."""
        order, seen = [], set()
        for m in self._managers:
            try:
                refs = self.refs(m)
            except ChunkError:
                continue
            for _slot, i in sorted(refs.items()):
                if i in self._layer_set and i not in seen:
                    seen.add(i)
                    order.append(i)
        order.extend(i for i in self.layer_indices if i not in seen)
        return order

    def layers(self):
        """Every Layer record in layer_order(); a layer that cannot be read is left out."""
        out = []
        for i in self.layer_order():
            try:
                out.append(self.layer(i))
            except ChunkError:
                pass
        return out

    def object_stack(self, i):
        """The object behind reference i: through derived objects down to the base object."""
        self._check(i)
        modifiers, derived, seen = [], [], set()
        while i is not None and self._ids[i] in self._derived:
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
