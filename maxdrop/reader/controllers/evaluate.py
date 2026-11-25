# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""_Eval: a controller evaluated at a frame (keyframes, lists, Euler, constraints, look-at)."""
import math

from .. import classids, pblock
from .ids import (
    _AUTO_IN, _AUTO_OUT, _EULER_ORDER, _EULER_ORDER_BASE, _INTERVAL, _INTERVAL_FORMAT, _KEY_IDS, _KEYFRAMED, _LC_AXIS,
    _LC_AXIS_FLIP, _LC_INITIAL_FRAME, _LC_INITIAL_LOCAL, _LC_RELATIVE, _LC_SET_ORIENTATION, _LC_SOURCE_UP,
    _LC_SOURCE_UP_FLIP, _LC_TARGETS, _LC_UP_AXIS, _LC_UP_CONTROL, _LC_UP_NODE, _LC_UP_WORLD, _LC_USER,
    _LC_WEIGHT_DEFAULT, _LC_WEIGHTS, _LIST_AVERAGE, _LIST_COUNT, _LIST_WEIGHTS, _LOOK_AXIS, _LOOK_FLIP, _LOOK_TARGET_UP,
    _NO_TIME, _ORT, _ORT_AFTER, _ORT_BEFORE, _ORT_CONSTANT, _ORT_OFF, _RANGE, _SCALE_VALUE, _TIME, _TINY, _WRAP,
    ANIMATED, ChunkError, CONSTRAINT_BLOCK, CONSTRAINT_DEGENERATE, CONSTRAINT_EMPTY, CONSTRAINT_OFFSET,
    CONSTRAINT_SETTING, EULER_ORDER, IDENTITY, Issue, KEYS_INTERPOLATED, KEYS_UNKNOWN, LIST_AVERAGE, LIST_BLOCK,
    LIST_WEIGHT, LOOK_AT_AXIS, LOOK_AT_NODE, LookAt, MAX_DEPTH, MAX_KEYS, ORT_APPROXIMATED, SCALE_LIST_WEIGHT,
    UNKNOWN_CLASS,
)
from .math3d import (
    _bits, _diagonal, _dot, _mat3, _matrix_quat, _near_identity, _point, _rows3, _sub, _transpose3, _unit,
    _weighted_quat, constraint_frame, euler_matrix, EULER_ORDERS, look_frame, multiply, quat_matrix, scale_matrix,
    slerp, translation,
)
from .keys import _Keys, _scale_value, out_of_range


class _At:
    __slots__ = ("ev", "i")

    def __init__(self, ev, i):
        self.ev, self.i = ev, i

    def __enter__(self):
        ev, i = self.ev, self.i
        if i in ev.path or len(ev.path) >= MAX_DEPTH:
            ev.failed = i
            if i in ev.path:
                raise ChunkError("controller %d references itself" % i)
            raise ChunkError("controllers deeper than %d below %s" % (MAX_DEPTH, ev.where()))
        ev.path.append(i)

    def __exit__(self, exc_type, exc, tb):
        self.ev.path.pop()
        if exc_type is not None and self.ev.failed is None:
            self.ev.failed = self.i
        return False


class _Eval:
    """Evaluation of one node's controller tree, with its issues; references are followed with a depth and a
    cycle guard."""

    def __init__(self, scene, node, issues, transforms=None):
        self.scene, self.node, self.issues, self.transforms = scene, node, issues, transforms
        self.path = []
        self.failed = None
        self.memo = {}  # (kind, controller) -> value: a shared sub-controller is evaluated once per node
        self.world = False  # matrix() gave the node's world matrix (a look-at), not its local one
        self.look = None  # the LookAt of a Look At controller node
        # controllers reported as UNKNOWN_CLASS (and a Float List of only such entries): still known when the memo
        # answers
        self.unknown = set()

    def where(self):
        return "node %d" % self.node if self.node is not None else "the controller"

    def issue(self, i, reason):
        if reason == UNKNOWN_CLASS:
            self.unknown.add(i)
        entry = self.scene.entry(i) if i is not None else None
        self.issues.append(Issue(self.node, i, entry.superclass if entry else None,
                                 entry.class_id if entry else None, reason))

    def at(self, i):
        """with self.at(i): evaluating controller i; failed is set to the innermost controller an error left."""
        return _At(self, i)

    def kind(self, i):
        entry = self.scene.entry(i)
        return (entry.superclass, entry.class_id) if entry is not None else (None, None)

    def _keys(self, i, holder, known):
        for child in holder.children:
            if child.id in _KEY_IDS and child.id != known:
                self.issue(i, KEYS_UNKNOWN)
                return

    def _keyframe(self, i):
        """Keyframe controller i's value at time 0 as a tuple of floats; None without a saved value or keys."""
        sc, cid = self.kind(i)
        value_id, count, key_id, size = _KEYFRAMED[(sc, cid)]
        chunk = self.scene.chunk(i)
        if not chunk.container:
            return None
        saved = interval = keys = None
        holders = [h for h in (chunk, chunk.first(_WRAP)) if h is not None and h.container]
        for holder in tuple(holders):
            self._keys(i, holder, key_id)
            value = holder.first(value_id)
            if saved is None and value is not None:
                saved = _scale_value(value) if value_id == _SCALE_VALUE else value.unpack("<%df" % count)
                held = holder.first(_INTERVAL)
                interval = held.unpack(_INTERVAL_FORMAT) if held is not None else None
            if keys is None and holder.first(key_id) is not None:
                keys = holder.first(key_id)
                holders.remove(holder)
                holders.insert(0, holder)  # the chunks beside the keys first
        if keys is None or saved is not None and interval is not None and interval[0] <= 0 <= interval[1]:
            return saved
        n, rest = divmod(keys.payload_size, size)
        if saved is not None and (rest or n == 0 or interval is None):
            if rest:
                self.issue(i, KEYS_UNKNOWN)
            elif n > 1:
                self.issue(i, ANIMATED)
            return saved
        if rest:
            raise ChunkError("object %d: keys %04X of %d bytes, not a multiple of %d" %
                             (i, keys.id, keys.payload_size, size))
        if n == 0:
            return None
        if n > MAX_KEYS:
            raise ChunkError("object %d: %d keys, more than %d" % (i, n, MAX_KEYS))
        view = keys.view()
        times = [_TIME.unpack_from(view, k * size)[0] for k in range(n)]
        if any(b < a for a, b in zip(times, times[1:])):
            raise ChunkError("object %d: key times out of order" % i)
        beside = holders[0]  # the holder of the keys: its out-of-range types, range and auto bits
        track = _Keys(cid, value_id, count, size, view, times, _bits(beside, _AUTO_IN, n), _bits(beside, _AUTO_OUT, n),
                      self.scene.ticks_per_frame)
        before, after, off = self._ort(holders)
        start, end = times[0], times[-1]
        held = next((c for c in (h.first(_RANGE) for h in holders) if c is not None), None)
        if held is not None:
            r0, r1 = held.unpack(_INTERVAL_FORMAT)
            if r0 != _NO_TIME and r0 <= r1:
                start, end = r0, r1
        if off:  # switched off: Constant (probed with the range on the keys only)
            before = after = _ORT_CONSTANT
        value, reason = out_of_range(track, 0, before, after, start, end)
        if off and (start, end) != (times[0], times[-1]) and not start <= 0 <= end:
            reason = ORT_APPROXIMATED
        if not track.known:
            self.issue(i, KEYS_INTERPOLATED)
        if reason is not None:
            self.issue(i, reason)
        return value

    @staticmethod
    def _ort(holders):
        """(before, after, switched off) of a keyframe controller: its 0x8499, Constant without one."""
        ort = next((h.first(_ORT) for h in holders if h.first(_ORT) is not None), None)
        if ort is None:
            return _ORT_CONSTANT, _ORT_CONSTANT, False
        if not ort.container:
            raise ChunkError("out-of-range types of %d bytes, not a container" % ort.payload_size)
        types = []
        for chunk_id in (_ORT_BEFORE, _ORT_AFTER, _ORT_OFF):
            value = ort.first(chunk_id)
            types.append(value.unpack("<i")[0] if value is not None else 0 if chunk_id == _ORT_OFF else _ORT_CONSTANT)
        return types[0], types[1], types[2] != 0

    def scalar(self, i, default):
        if i is None:
            return default
        key = ("scalar", i, default)
        if key not in self.memo:
            self.memo[key] = self._scalar(i, default)
        return self.memo[key]

    def _scalar(self, i, default):
        with self.at(i):
            sc, cid = self.kind(i)
            if (sc, cid) in _KEYFRAMED and sc == classids.SC_CTRL_FLOAT:
                value = self._keyframe(i)
                return default if value is None else float(value[0])
            if sc == classids.SC_CTRL_FLOAT and cid == classids.FLOAT_LIST:
                entries, average = self._list(i)
                if not entries:
                    return default
                # an entry that cannot be read adds nothing: the axis default (1 under ScaleXYZ) is the list's own
                values = [(w, self.scalar(entry, None)) for entry, w in entries]
                if default is None and all(v is None for _w, v in values):
                    # no value to a caller that asks for none (a LookAt weight: 50); reported once, as their class
                    if all(entry in self.unknown for entry, _w in entries):
                        self.unknown.add(i)
                    return None
                total = sum((w * v for w, v in values if v is not None), 0.0)
                if average:  # divided by the weights' sum; 0 when they add up to 0
                    weights = sum((w for w, v in values if v is not None), 0.0)
                    return total / weights if weights != 0.0 else 0.0
                return total
            self.issue(i, UNKNOWN_CLASS)
            return default

    def _floats3(self, i, default):
        refs = self.scene.refs(i)
        return tuple(self.scalar(refs.get(k), default) for k in range(3))

    def _weights(self, i, refs):
        """(block, weights, average) of list controller i: parameter 0 of its ParamBlock2, each element a number or
        an Animated, and whether its Average (parameter 1) is on; (None, [], False) without a block."""
        block = next((r for r in refs.values() if self.kind(r)[0] == classids.SC_PARAMETER_BLOCK2), None)
        if block is None:
            return None, [], False
        pb = pblock.ParamBlock2.from_chunk(self.scene.chunk(block), self.scene.refs(block), refs, len(self.scene),
                                           self.kind(i))
        param = pb.param(_LIST_WEIGHTS)
        if param is not None and param.error:  # damaged weights read as missing: 1.0
            self.issue(i, "%s: %s" % (LIST_BLOCK, param.error))
        weights = pb.value(_LIST_WEIGHTS, [])
        average = pb.value(_LIST_AVERAGE, 0)
        average = isinstance(average, (int, float)) and average != 0  # unreadable or animated: off
        return block, weights if isinstance(weights, list) else [weights], average

    def _list(self, i):
        """([(entry index, weight)], average) of a list controller."""
        chunk = self.scene.chunk(i)
        refs = self.scene.refs(i)
        count = chunk.first(_LIST_COUNT) if chunk.container else None
        if count is not None:
            n = count.unpack("<i")[0]
            if not 0 <= n <= len(self.scene):
                raise ChunkError("list controller %d: %d entries" % (i, n))
            slots = range(n)
        else:
            slots = sorted(k for k, r in refs.items() if self.kind(r)[0] != classids.SC_PARAMETER_BLOCK2)
        block, weights, average = self._weights(i, refs)
        out = []
        for k in slots:
            entry = refs.get(k)
            if entry is None:
                continue
            w = weights[k] if k < len(weights) else None
            if isinstance(w, pblock.Animated) and w.index is not None:
                with self.at(block):
                    w = self.scalar(w.index, 1.0)
            if isinstance(w, bool) or not isinstance(w, (int, float)):
                self.issue(i, LIST_WEIGHT)
                w = 1.0
            out.append((entry, float(w)))
        return out, average

    def position(self, i):
        if i is None:
            return (0.0, 0.0, 0.0)
        key = ("position", i)
        if key not in self.memo:
            self.memo[key] = self._position(i)
        return self.memo[key]

    def _position(self, i):
        with self.at(i):
            sc, cid = self.kind(i)
            if sc == classids.SC_CTRL_POSITION:
                if cid == classids.POSITION_XYZ:
                    return self._floats3(i, 0.0)
                if (sc, cid) in _KEYFRAMED:
                    return self._keyframe(i) or (0.0, 0.0, 0.0)
                if cid == classids.POSITION_LIST:
                    total = [0.0, 0.0, 0.0]
                    entries, average = self._list(i)
                    for entry, w in entries:
                        p = self.position(entry)
                        for k in range(3):
                            total[k] += w * p[k]
                    weights = sum((w for _e, w in entries), 0.0)
                    if average:  # divided by the weights' sum; the origin when they add up to 0
                        return tuple(v / weights for v in total) if weights != 0.0 else (0.0, 0.0, 0.0)
                    return tuple(total)
            self.issue(i, UNKNOWN_CLASS)
            return (0.0, 0.0, 0.0)

    def rotation(self, i):
        if i is None:
            return IDENTITY
        key = ("rotation", i)
        if key not in self.memo:
            self.memo[key] = self._rotation(i)
        return self.memo[key]

    def _rotation(self, i):
        with self.at(i):
            sc, cid = self.kind(i)
            if sc == classids.SC_CTRL_ROTATION:
                if cid == classids.EULER_XYZ:
                    chunk = self.scene.chunk(i)
                    order = chunk.first(_EULER_ORDER) if chunk.container else None
                    order = order.unpack("<i")[0] if order is not None else 0
                    if order >= _EULER_ORDER_BASE:
                        order -= _EULER_ORDER_BASE
                    if order not in EULER_ORDERS:
                        self.issue(i, EULER_ORDER)
                        order = 0
                    return euler_matrix(self._floats3(i, 0.0), order)
                if (sc, cid) in _KEYFRAMED:
                    q = self._keyframe(i)
                    return quat_matrix(q) if q is not None else IDENTITY
                if cid == classids.ROTATION_LIST:
                    entries, average = self._list(i)
                    if average:  # from no rotation, a slerp towards each entry in turn by its weight
                        q = (0.0, 0.0, 0.0, 1.0)
                        for entry, w in entries:
                            q = slerp(q, _matrix_quat(self.rotation(entry)), w)
                        return quat_matrix(q)
                    # each entry pre-rotates what came before, as a relative controller does
                    m = IDENTITY
                    for entry, w in entries:
                        m = multiply(_weighted_quat(self.rotation(entry), w), m)
                    return m
            self.issue(i, UNKNOWN_CLASS)
            return IDENTITY

    def scale(self, i):
        if i is None:
            return IDENTITY
        key = ("scale", i)
        if key not in self.memo:
            self.memo[key] = self._scale(i)
        return self.memo[key]

    def _scale(self, i):
        with self.at(i):
            sc, cid = self.kind(i)
            if sc == classids.SC_CTRL_SCALE:
                if (sc, cid) in _KEYFRAMED:
                    v = self._keyframe(i)
                    return scale_matrix(v[:3], v[3:]) if v is not None else IDENTITY
                if cid == classids.SCALE_XYZ:
                    return scale_matrix(self._floats3(i, 1.0))
                if cid == classids.SCALE_LIST:
                    entries, average = self._list(i)
                    if average:
                        return self._scale_average(i, entries)
                    m = IDENTITY
                    warned = False
                    for entry, w in entries:
                        s = self.scale(entry)
                        if w != 1.0:
                            # measured: an entry alone or among plain scales; after a turned one no rule fits
                            if not (warned or _near_identity(m) or _near_identity(s) or
                                    _diagonal(m) and _diagonal(s)):
                                self.issue(i, SCALE_LIST_WEIGHT)
                                warned = True
                            s = tuple(tuple(IDENTITY[r][c] + (s[r][c] - IDENTITY[r][c]) * w for c in range(4))
                                      for r in range(4))
                        m = multiply(s, m)
                    return m
            self.issue(i, UNKNOWN_CLASS)
            return IDENTITY

    def _scale_average(self, i, entries):
        """A Scale List with Average on: the weighted mean of its entries' scales, identity when the weights add up
        to 0; entries along turned axes fit no measured rule (an issue, the mean of the matrices)."""
        scales = [(self.scale(entry), w) for entry, w in entries]
        weights = sum((w for _s, w in scales), 0.0)
        if not all(_diagonal(s) for s, _w in scales):
            self.issue(i, LIST_AVERAGE)
        if weights == 0.0:
            return IDENTITY
        return tuple(tuple(sum(s[r][c] * w for s, w in scales) / weights for c in range(4)) for r in range(4))

    def matrix(self, i):
        with self.at(i):
            sc, cid = self.kind(i)
            in_node = self.transforms is not None and self.node is not None
            if in_node and sc == classids.SC_CTRL_MATRIX3 and cid == classids.LOOK_AT:
                return self._look_at(i)
            if sc == classids.SC_CTRL_MATRIX3 and cid == classids.PRS:
                refs = self.scene.refs(i)
                if in_node and refs.get(1) is not None and \
                        self.kind(refs[1]) == (classids.SC_CTRL_ROTATION, classids.LOOKAT_CONSTRAINT):
                    return self._constrained(refs)
                rot = self.rotation(refs.get(1))
                rot_pos = _mat3([row[:3] for row in rot[:3]], self.position(refs.get(0)))
                return multiply(self.scale(refs.get(2)), rot_pos)
            self.issue(i, UNKNOWN_CLASS)
            return IDENTITY

    def _node_world(self, i, j):
        """The world matrix of node j, which controller i aims with; None when j is empty or no node (an issue)."""
        if j is None:
            return None
        if not self.scene.is_a(j, classids.SC_BASENODE, classids.NODE):
            self.issue(i, LOOK_AT_NODE)
            return None
        return self.transforms.world(j)

    def _world_position(self, i):
        """Position controller i's value placed by the node's parent: where the node is in the world."""
        return _point(self.position(i), self.transforms.parent_world(self.node))

    def _look_at(self, i):
        # the parent's scale is intentionally dropped: 3ds Max's Look At frame is absolute (_constrained keeps it)
        chunk = self.scene.chunk(i)
        refs = self.scene.refs(i)
        axis, flip, target_up = 2, False, False
        if chunk.container:
            value = chunk.first(_LOOK_AXIS)
            if value is not None:
                axis = value.unpack("<I")[0]
            flip = chunk.first(_LOOK_FLIP) is not None
            value = chunk.first(_LOOK_TARGET_UP)
            target_up = value is not None and value.unpack("<B")[0] != 0
        if axis not in (0, 1, 2):
            self.issue(i, LOOK_AT_AXIS)
            axis = 2
        position = self._world_position(refs.get(1))
        target = refs.get(0)
        tw = self._node_world(i, target)
        if tw is None:
            target = None  # 3ds Max aims at the world origin then
        up = (_unit(tw[2][:3]) if tw is not None and target_up else None) or (0.0, 0.0, 1.0)
        roll = self.scalar(refs.get(2), 0.0)
        frame = look_frame(position, tw[3][:3] if tw is not None else (0.0, 0.0, 0.0), up, axis, flip, roll)
        self.world = True
        self.look = LookAt(target, axis, flip, roll, target_up)
        return multiply(self.scale(refs.get(3)), _mat3(frame, position))

    def _constrained(self, refs):
        """A PRS whose rotation is a LookAt Constraint: the world matrix. Unlike a Look At controller's, its
        scale is relative: the parent's (the lengths of its rows) still scales it."""
        position = self._world_position(refs.get(0))
        with self.at(refs[1]):
            frame = self._constraint(refs[1], position)
        self.world = True
        parent = self.transforms.parent_world(self.node)
        inherited = scale_matrix([math.sqrt(_dot(row[:3], row[:3])) for row in parent[:3]])
        rotation = _mat3(frame, position) if frame is not None else translation(position)
        return multiply(multiply(self.scale(refs.get(2)), inherited), rotation)

    def _setting(self, c, pb, pid, default):
        """An int or bool setting of constraint c's block; its default (and an issue) when animated or damaged."""
        value = pb.get(pid)
        if value is None:
            return default
        if isinstance(value, (int, float)) and math.isfinite(value):
            return int(value)
        self.issue(c, CONSTRAINT_SETTING)
        return default

    def _constraint(self, c, position):
        """The frame of LookAt Constraint c at position, None (and an issue) when it has none."""
        block = self.scene.refs(c).get(0)
        if block is None or self.kind(block)[0] != classids.SC_PARAMETER_BLOCK2:
            self.issue(c, CONSTRAINT_EMPTY)
            return None
        pb = pblock.ParamBlock2.from_chunk(self.scene.chunk(block), self.scene.refs(block), self.scene.refs(c),
                                           len(self.scene), self.kind(c))
        if pb.issues:  # a damaged entry reads as missing: its default is used
            self.issue(c, "%s: %s" % (CONSTRAINT_BLOCK, pb.issues[0]))
        relative = self._setting(c, pb, _LC_RELATIVE, 0)
        set_orientation = self._setting(c, pb, _LC_SET_ORIENTATION, 0)
        weights = pb.value(_LC_WEIGHTS, [])
        weights = weights if isinstance(weights, list) else [weights]
        targets = pb.value(_LC_TARGETS, [])
        targets = targets if isinstance(targets, list) else [targets]
        total, point = 0.0, [0.0, 0.0, 0.0]
        for k, ref in enumerate(targets):
            w = weights[k] if k < len(weights) else None
            if isinstance(w, pblock.Animated):
                index = w.index
                w = self.scalar(index, None)
                if w is None and index is not None and index in self.unknown:  # reported once, as its class
                    w = _LC_WEIGHT_DEFAULT
            if not (isinstance(w, (int, float)) and math.isfinite(w)):
                self.issue(c, CONSTRAINT_SETTING)
                w = _LC_WEIGHT_DEFAULT
            tw = self._node_world(c, ref.index if isinstance(ref, pblock.Reference) else None)
            if tw is None or w == 0.0:
                continue
            total += w
            for a in range(3):
                point[a] += w * tw[3][a]
        if not abs(total) > _TINY:
            self.issue(c, CONSTRAINT_EMPTY)
            return None
        target = tuple(v / total for v in point)
        up_axis = self._setting(c, pb, _LC_UP_AXIS, 2)
        if up_axis not in (0, 1, 2):
            self.issue(c, CONSTRAINT_SETTING)
            up_axis = 2
        up_node = IDENTITY  # the world: its axes, its origin
        if not self._setting(c, pb, _LC_UP_WORLD, 1):
            ref = pb.get(_LC_UP_NODE)
            j = ref.index if isinstance(ref, pblock.Reference) else None
            if j is None:
                self.issue(c, LOOK_AT_NODE)
            up_node = self._node_world(c, j) or IDENTITY
        if self._setting(c, pb, _LC_UP_CONTROL, 1):  # axis alignment
            up = up_node[up_axis][:3]
        else:  # the up axis looks at the up node
            up = _sub(up_node[3][:3], position)
        frame = constraint_frame(position, target, up, self._setting(c, pb, _LC_AXIS, 0),
                                 bool(self._setting(c, pb, _LC_AXIS_FLIP, 0)), self._setting(c, pb, _LC_SOURCE_UP, 2),
                                 bool(self._setting(c, pb, _LC_SOURCE_UP_FLIP, 0)))
        if frame is None:
            self.issue(c, CONSTRAINT_DEGENERATE)
            return None
        if relative:  # the rotation at assignment, kept relative to the frame then; Set Orientation's is ignored
            local, initial = self._quat(c, _LC_INITIAL_LOCAL), self._quat(c, _LC_INITIAL_FRAME)
            if local is None or initial is None:
                self.issue(c, CONSTRAINT_OFFSET)
                return frame
            return _rows3(multiply(multiply(local, _transpose3(initial)), _mat3(frame)))
        # Set Orientation's rotation, also after it is turned off; identity until the node is turned with it on
        user = self._quat(c, _LC_USER)
        if user is None:
            if set_orientation:
                self.issue(c, CONSTRAINT_OFFSET)
            return frame
        return _rows3(multiply(_mat3(frame), user))

    def _quat(self, c, cid):
        """The matrix of constraint c's quaternion chunk cid, None when it is missing or short."""
        chunk = self.scene.chunk(c)
        value = chunk.first(cid) if chunk.container else None
        if value is None or value.payload_size < 16:
            return None
        return quat_matrix(value.unpack("<4f"))
