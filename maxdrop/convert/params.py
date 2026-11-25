# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parameter values as the rules use them: a number only when it is a finite int or float (a bool, None, NaN or
a damaged value is not), else the rule's default. Shared by materials/ and texmaps/ (materials imports texmaps,
so neither can hold them for the other). No bpy.

    num(m, pid, block, default)     # float of parameter pid of MtlBase m (block None: the first that stores it)
    flag(m, pid, block, default)    # bool of the same
    graph = at_frame_zero(graph, report)    # a MaterialGraph whose materials and maps read an animated parameter at
                                            # frame 0; report(object index, line) hears what that met
    frame_zero(scene, block, pid, v, heard) # v, or an Animated's value at frame 0 in the shape of the parameter's type
    old_value(scene, part, index, heard)    # a part's old ParamBlock value, or its controller's at frame 0

A parameter a controller holds (reader.pblock.Animated) is read as its controller's value at frame 0
(reader.controllers.parameter_value) when the rules' graph went through at_frame_zero, as the converters' does: a
float parameter a float, an integer one (int, bool, time, radio button, index) a whole number only, a color a
Bezier Color's three channels (an hsv parameter not: not measured). Anything else stays the Animated, which no reader takes for a value: the rule's
default, as before. A float controller on an integer parameter is not measured (no fixture holds one): 3ds Max's
rounding of a fraction is not known, so a fraction is not read. Percent and angle parameters take the controller's
value as it is, like their stored values (not measured either).

What a read meets goes to the report (maxdrop-6n0.6.32), one line per read naming the parameter and its
controller: each issue of the controller's evaluation (a color between two keys interpolated linearly, a saved
value of another frame, keys of an unknown layout, a list weight not stored, another class, a damaged controller),
and a parameter left at its default. A map's Coordinates and Output (an old ParamBlock: old_value) are read the
same way; no fixture animates one (not measured: the old block's layout is the one of stack_basic's Noise block and
the Standard shader blocks). An old block whose references are not one slot per animated parameter (slots 0 to n - 1,
the measured layout) is read for none of them: a line names the mismatch (SLOTS), the default is used.
"""
import math

from ..reader import controllers, pblock
from ..reader.errors import MaxFileError

_COLORS = frozenset((2, 3))  # ParamType2 color, point3 (an hsv one, 10, is not measured: not read)
DEFAULT_USED = "its default used"
_NON_FINITE = "non-finite value"  # controllers.NON_FINITE names a transform
NOT_READ = "not read at frame 0"
SLOTS = "the block's %d controller references do not match its %d animated parameters, not read"


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def num(m, pid, block, default):
    v = m.param(pid, block)
    return float(v) if finite(v) else default


def flag(m, pid, block, default):
    v = m.param(pid, block)
    return bool(v) if finite(v) else default


def _shaped(value, kind, fallback):
    """A controller's value in the shape of a parameter of type kind (ParamType2; an old block's types 0 to 4 are
    the same numbers), fallback where it has another shape."""
    if isinstance(value, tuple):
        return value if kind in _COLORS else fallback
    if value is None:
        return fallback
    if kind in pblock.FLOAT_TYPES:
        return value
    if kind in pblock.INT_TYPES and value.is_integer():
        return int(value)
    return fallback


def lines(what, pid, controller, read, issues):
    """The report lines of parameter pid of what (a name) held by controller (an object index; None: missing):
    each issue, else that it was not read; read False adds that the default is used."""
    head = "%s: parameter %d at frame 0 (controller %s)" % (what, pid, "missing" if controller is None else controller)
    tail = "" if read else ", " + DEFAULT_USED
    out = ["%s: %s%s" % (head, _NON_FINITE if x.reason == controllers.NON_FINITE else x.reason, tail)
           for x in issues]
    if not out and not read:
        out.append("%s: %s%s" % (head, NOT_READ, tail))
    return out


def hearing(report, index, what):
    """The heard callback of frame_zero / old_value for object index named what: its lines to report(index, line);
    None without a report."""
    if report is None:
        return None

    def heard(pid, controller, read, issues):
        for line in lines(what, pid, controller, read, issues):
            report(index, line)
    return heard


def frame_zero(scene, block, pid, v, heard=None):
    """v as it is, or for an Animated in block's parameter pid its controller's value at frame 0 in the shape of the
    parameter's type (a float, a whole number as an int, a 3-tuple of floats); the Animated itself where that
    cannot be had (no scene or controller, the controller not evaluated, a value of another shape, a fraction for
    an integer). heard(pid, controller, read, issues) is told what the read met (with a scene and a block)."""
    if not isinstance(v, pblock.Animated) or scene is None or block is None:
        return v
    if v.index is None:
        if heard is not None:
            heard(pid, None, False, [])
        return v
    param = block.param(pid)
    value, issues = controllers.parameter_value(scene, v.index)
    out = _shaped(value, param.base_type if param is not None else None, v)
    if heard is not None:
        heard(pid, v.index, out is not v, issues)
    return out


def old_value(scene, part, index, heard=None, number=False):
    """Parameter index of a part's old ParamBlock (a map's Coordinates or Output; the first in slot order): its
    stored value, or its controller's at frame 0 in the shape of its type (as frame_zero); None when it has neither.
    The controller is the block object's reference at the block's controller(index), read only when the block's
    references are exactly its controller slots (SLOTS otherwise). number: only a finite number counts as read (a
    color the block's type gives is not)."""
    if part is None or not part.legacy:
        return None
    slot = min(part.legacy)
    block = part.legacy[slot]
    v = block.get(index)
    ref = block.controller(index) if v is None else None
    if ref is None or scene is None:
        return v
    try:
        holder = scene.refs(part.index).get(slot)
        refs = scene.refs(holder) if holder is not None else None
    except MaxFileError:
        refs = None
    n = block.controller_slots()
    if refs is not None and sorted(refs) != list(range(n)):
        if heard is not None:
            heard(index, None, False, [controllers.Issue(None, None, None, None, SLOTS % (len(refs), n))])
        return None
    controller = refs.get(ref) if refs is not None else None
    if controller is None:
        if heard is not None:
            heard(index, None, False, [])
        return None
    value, issues = controllers.parameter_value(scene, controller)
    out = _shaped(value, block.type(index), None)
    if number and not finite(out):
        out = None
    if heard is not None:
        heard(index, controller, out is not None, issues)
    return out


class FrameZero:
    """A MtlBase whose param() reads an animated parameter at frame 0 (frame_zero), telling report(its index, line)
    what that met; the rest is the MtlBase's."""
    __slots__ = ("_m", "_scene", "_heard")

    def __init__(self, m, scene, report=None):
        self._m, self._scene = m, scene
        self._heard = hearing(report, m.index, "%r" % (m.name,))

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
        return frame_zero(self._scene, block, pid, v, self._heard)


class FrameZeroGraph:
    """A MaterialGraph whose get() hands out FrameZero materials and maps (one per object), each telling report
    (None: nobody) what its reads met; the rest is the graph's."""

    def __init__(self, graph, report=None):
        self._graph, self._wrapped, self.report = graph, {}, report

    def __getattr__(self, name):
        return getattr(self._graph, name)

    def get(self, i):
        m = self._wrapped.get(i)
        if m is None:
            m = self._wrapped[i] = FrameZero(self._graph.get(i), self._graph.scene, self.report)
        return m


def at_frame_zero(graph, report=None):
    """graph read at frame 0 (FrameZeroGraph), what its reads meet told to report(object index, line); as it is
    when it has no scene to read controllers from, or already is one and no other report is given."""
    if isinstance(graph, FrameZeroGraph):
        return graph if report is None or report == graph.report else FrameZeroGraph(graph._graph, report)
    if getattr(graph, "scene", None) is None:
        return graph
    return FrameZeroGraph(graph, report)
