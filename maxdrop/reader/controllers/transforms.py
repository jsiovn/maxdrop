# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transforms (a node's matrices at frame 0), parameter_value() and matrix()."""
import math

from .. import classids
from ..errors import MaxFileError
from .ids import (
    _KEYFRAMED, ChunkError, DAMAGED, IDENTITY, Issue, LOOK_AT_PARENT, MAX_LOOK_AT_DEPTH, NO_CONTROLLER, NON_FINITE,
    UNKNOWN_CLASS,
)
from .math3d import _finite, _inverse, multiply, quat_matrix, scale_matrix, translation
from .evaluate import _Eval


class Transforms:
    """The matrices of a reader.scene.Scene's nodes at frame 0, computed on demand and kept."""

    def __init__(self, scene):
        self.scene = scene
        self.issues = []
        self._local = {}
        self._world = {}
        self._offset = {}
        self._direct = {}  # node -> world matrix of a look-at node, which its local matrix only approximates
        self._look = {}  # node -> LookAt
        self._busy = []  # nodes whose local matrix is being computed: a look-at waits on other nodes
        self._cycle = set()  # nodes found on a look-at cycle: each one is damaged, not only where it closed

    def local(self, i):
        """Node i's transform relative to its parent: scale * rotation * position (a look-at node: its world
        matrix times the parent's inverse)."""
        m = self._local.get(i)
        if m is not None:
            return m
        if i in self._busy:  # only reached from a look-at below local(i): every node from i on waits on i
            self._cycle.update(self._busy[self._busy.index(i):])
            raise ChunkError("node %d: its look-at depends on itself" % i)
        if len(self._busy) >= MAX_LOOK_AT_DEPTH:
            raise ChunkError("look-at nodes waiting on more than %d others" % MAX_LOOK_AT_DEPTH)
        self._busy.append(i)
        try:
            m = self._evaluate(i)
        finally:
            self._busy.pop()
        self._local[i] = m
        return m

    def _evaluate(self, i):
        ev = _Eval(self.scene, i, self.issues, self)
        try:
            node = self.scene.node(i)
        except ChunkError as exc:  # a damaged node record: identity, its children still placed
            ev.issue(None, "%s: %s" % (DAMAGED, exc))
            return IDENTITY
        if node.tm is None:
            ev.issue(None, NO_CONTROLLER)
            return IDENTITY
        mark = len(self.issues)
        try:
            m = ev.matrix(node.tm)
            if i in self._cycle:  # it completed, aimed at a node the cycle left at identity
                raise ChunkError("node %d: its look-at depends on itself" % i)
            if ev.world and _finite(m):
                inverse = _inverse(self.parent_world(i))
                if inverse is None:
                    ev.issue(node.tm, LOOK_AT_PARENT)
                    return IDENTITY
                world, m = m, multiply(m, inverse)
                if _finite(m):
                    self._direct[i] = world
        except (MaxFileError, OverflowError) as exc:  # anything else is a defect: the fuzz harness sees it
            # this node's issues only: a look-at may have evaluated other nodes, whose issues stay
            self.issues[mark:] = [x for x in self.issues[mark:] if x.node != i]
            bad = ev.failed if ev.failed is not None else node.tm
            ev.issue(bad, "%s: %s" % (DAMAGED, exc))
            return IDENTITY
        if not _finite(m):
            ev.issue(node.tm, NON_FINITE)
            return IDENTITY
        if ev.look is not None:
            self._look[i] = ev.look
        return m

    def parent_world(self, i):
        """The world matrix of node i's parent, identity at the top level."""
        p = self.scene.parent(i)
        return self.world(p) if p is not None else IDENTITY

    def look_at(self, i):
        """The LookAt of node i's Look At controller; None when its controller is none or cannot be evaluated."""
        self.local(i)
        return self._look.get(i)

    def world(self, i):
        """Node i's world transform: its local matrix times every parent's, up to the top level (a look-at node:
        the world matrix its controller gives)."""
        m = self._world.get(i)
        if m is not None:
            return m
        chain = []
        j = i
        while j is not None and j not in self._world:  # bounded: the scene's parents have no cycle
            chain.append(j)
            j = self.scene.parent(j)
        parent = self._world[j] if j is not None else IDENTITY
        for j in reversed(chain):
            local = self.local(j)  # a look-at may have computed this world matrix meanwhile
            parent = self._direct.get(j) or self._world.get(j) or multiply(local, parent)
            self._world[j] = parent
        return self._world[i]

    def offset(self, i):
        """Node i's object offset: scale (along its axis) * rotation * position, from the node record (identity
        when that record is damaged; identity and an issue when it is not finite)."""
        m = self._offset.get(i)
        if m is not None:
            return m
        try:
            node = self.scene.node(i)
            m = multiply(multiply(scale_matrix(node.pivot_scale, node.pivot_scale_axis),
                                  quat_matrix(node.pivot_rotation)), translation(node.pivot_position))
        except ChunkError:
            m = IDENTITY
        if not _finite(m):
            self.issues.append(Issue(i, None, None, None, NON_FINITE))
            m = IDENTITY
        self._offset[i] = m
        return m

    def object_world(self, i):
        """offset * world: where node i's object-space vertices land in the world."""
        return multiply(self.offset(i), self.world(i))


def parameter_value(scene, i):
    """(the value of controller i at frame 0, issues) for a parameter of a material or map that a controller holds
    (reader.pblock.Animated): a float from a float controller (as a transform's: keyframes and Float List), a tuple of
    3 floats from a Bezier Color (between two keys linear, with an issue: its curve is not measured); None where it
    cannot be evaluated (another class, also as a Float List's entry, where a transform's list adds nothing: a
    parameter keeps its default instead; no saved value or keys, also in every entry of a Float List; a damaged
    controller, a non-finite value), with an Issue (node None) as matrix() gives."""
    issues = []
    ev = _Eval(scene, None, issues)
    if not 0 <= i < len(scene):
        issues.append(Issue(None, None, None, None, "%s: object %d past the scene" % (DAMAGED, i)))
        return None, issues
    try:
        sc, cid = ev.kind(i)
        if sc == classids.SC_CTRL_FLOAT:
            value = ev.scalar(i, None)
        elif sc == classids.SC_CTRL_POINT3 and (sc, cid) in _KEYFRAMED:
            with ev.at(i):
                v = ev._keyframe(i)
            value = None if v is None else tuple(float(c) for c in v)
        else:
            ev.issue(i, UNKNOWN_CLASS)
            return None, issues
    except (MaxFileError, OverflowError) as exc:
        del issues[:]
        ev.issue(ev.failed if ev.failed is not None else i, "%s: %s" % (DAMAGED, exc))
        return None, issues
    if value is None or any(x.reason == UNKNOWN_CLASS for x in issues):
        return None, issues
    if not all(math.isfinite(c) for c in (value if isinstance(value, tuple) else (value,))):
        ev.issue(i, NON_FINITE)
        return None, issues
    return value, issues


def matrix(scene, i):
    """(the matrix of Matrix3 controller i at frame 0, issues), outside any node: a modifier's gizmo. The same
    rules as a node's local matrix: identity and an issue (node None) when it cannot be evaluated."""
    issues = []
    ev = _Eval(scene, None, issues)
    if not 0 <= i < len(scene):
        issues.append(Issue(None, None, None, None, "%s: object %d past the scene" % (DAMAGED, i)))
        return IDENTITY, issues
    try:
        m = ev.matrix(i)
    except (MaxFileError, OverflowError) as exc:
        del issues[:]
        ev.issue(ev.failed if ev.failed is not None else i, "%s: %s" % (DAMAGED, exc))
        return IDENTITY, issues
    if not _finite(m):
        ev.issue(i, NON_FINITE)
        return IDENTITY, issues
    return m, issues
