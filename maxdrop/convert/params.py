# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parameter values as the rules use them: a number only when it is a finite int or float (a bool, None, NaN or
a damaged value is not), else the rule's default. Shared by materials.py and texmaps.py (materials imports texmaps,
so neither can hold them for the other). No bpy.

    num(m, pid, block, default)     # float of parameter pid of MtlBase m (block None: the first that stores it)
    flag(m, pid, block, default)    # bool of the same
    graph = at_frame_zero(graph)    # a MaterialGraph whose materials and maps read an animated parameter at frame 0
    frame_zero(scene, block, pid, v)    # v, or an Animated's value at frame 0 in the shape of the parameter's type

A parameter a controller holds (reader.pblock.Animated) is read as its controller's value at frame 0
(reader.controllers.parameter_value) when the rules' graph went through at_frame_zero, as the converters' does: a
float parameter a float, an integer one (int, bool, time, radio button, index) a whole number only, a color a
Bezier Color's three channels. Anything else stays the Animated, which no reader takes for a value: the rule's
default, as before. A float controller on an integer parameter is not measured (no fixture holds one): 3ds Max's
rounding of a fraction is not known, so a fraction is not read. Percent and angle parameters take the controller's
value as it is, like their stored values (not measured either).
"""
import math

from ..reader import controllers, pblock

# ParamType2 base types (docs/FORMAT.md, Parameter blocks) by the value they hold
_FLOATS = frozenset((0, 5, 6, 7, 11))  # float, angle, percent, world, color channel
_INTS = frozenset((1, 4, 12, 13, 19))  # int, bool, time, radio button, index
_COLORS = frozenset((2, 3, 10))  # color, point3, hsv


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def num(m, pid, block, default):
    v = m.param(pid, block)
    return float(v) if finite(v) else default


def flag(m, pid, block, default):
    v = m.param(pid, block)
    return bool(v) if finite(v) else default


def frame_zero(scene, block, pid, v):
    """v as it is, or for an Animated in block's parameter pid its controller's value at frame 0 in the shape of the
    parameter's type (a float, a whole number as an int, a 3-tuple of floats); the Animated itself where that
    cannot be had (no scene or controller, the controller not evaluated, a value of another shape, a fraction for
    an integer)."""
    if not isinstance(v, pblock.Animated) or v.index is None or scene is None or block is None:
        return v
    param = block.param(pid)
    kind = param.base_type if param is not None else None
    value, _issues = controllers.parameter_value(scene, v.index)
    if isinstance(value, tuple):
        return value if kind in _COLORS else v
    if value is None:
        return v
    if kind in _FLOATS:
        return value
    if kind in _INTS and value.is_integer():
        return int(value)
    return v


class FrameZero:
    """A MtlBase whose param() reads an animated parameter at frame 0 (frame_zero); the rest is the MtlBase's."""
    __slots__ = ("_m", "_scene")

    def __init__(self, m, scene):
        self._m, self._scene = m, scene

    def __getattr__(self, name):
        return getattr(self._m, name)

    def __repr__(self):
        return "FrameZero(%r)" % (self._m,)

    def param(self, pid, block_id=None, tab=0, default=None):
        v = self._m.param(pid, block_id, tab, default)
        if not isinstance(v, pblock.Animated):
            return v
        # the block that answered, found as MtlBase.param finds it: the given one, else the first in slot order
        blocks = [self._m.block(block_id)] if block_id is not None else [b for _s, b in sorted(self._m.blocks.items())]
        block = next((b for b in blocks if b is not None and pid in b), None)
        return frame_zero(self._scene, block, pid, v)


class FrameZeroGraph:
    """A MaterialGraph whose get() hands out FrameZero materials and maps (one per object); the rest is the
    graph's."""

    def __init__(self, graph):
        self._graph, self._wrapped = graph, {}

    def __getattr__(self, name):
        return getattr(self._graph, name)

    def get(self, i):
        m = self._wrapped.get(i)
        if m is None:
            m = self._wrapped[i] = FrameZero(self._graph.get(i), self._graph.scene)
        return m


def at_frame_zero(graph):
    """graph read at frame 0 (FrameZeroGraph); as it is when it has no scene to read controllers from or already is
    one."""
    if isinstance(graph, FrameZeroGraph) or getattr(graph, "scene", None) is None:
        return graph
    return FrameZeroGraph(graph)
