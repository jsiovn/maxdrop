# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Extrude's parameters: the parameter ids, the limits, the errors and read_params()."""
import collections
import math

from ...reader import chunks, classids, pblock, realworld


ChunkError = chunks.ChunkError

(P_AMOUNT, P_SEGMENTS, P_CAP_START, P_CAP_END, P_CAP_TYPE, P_OUTPUT, P_MAPPING, P_MATERIAL_IDS, P_SHAPE_IDS,
 P_SMOOTH) = range(10)
CAP_MORPH, CAP_GRID = 0, 1
OUTPUT_PATCH, OUTPUT_MESH, OUTPUT_NURBS = 0, 1, 2
SLOT_PARAMS = 0

ADAPTIVE_ANGLE = math.radians(2.0)
ADAPTIVE_DEPTH = 11  # a piece of 1/2048 of its segment is never split: at most 2047 steps a segment
TOP_ID, BOTTOM_ID, SIDE_ID = 0, 1, 2  # zero-based: 3ds Max shows 1, 2, 3
CAP_GROUP = 1 << 4
MAX_SEGMENTS = 10000
MAX_VERTICES = 1 << 21  # about 2 million: about a second and 500 MB at most (Adaptive's points: several seconds)
MAX_CAP_POINTS = 5000  # a holed cap is ear-clipped in Python: quadratic
MAX_CLIP_STEPS = 1 << 25  # the holed caps of one mesh: a 5000-point cap takes up to about 8 million, 3 s
MAX_LOOPS = 4000  # closed polylines nested against each other: quadratic
MAX_NEST_TESTS = 1 << 24  # point-edge tests telling which outline lies in which: about 2 s in Python
MAX_CROSS_TESTS = 1 << 24  # edge pairs of one mesh tested for a self-crossing outline (numpy): about a second
CROSS_CHUNK = 1 << 20  # edge pairs tested at once: bounds the arrays
MAX_GRID_TESTS = 1 << 25  # point-edge and cell-edge tests of the grid caps of one mesh (numpy): about a second
MAX_GRID_CLIP_STEPS = 1 << 23  # the grid bands of one mesh, beside MAX_CLIP_STEPS: a few seconds
GRID_DIVISIONS, GRID_MAX_DIVISIONS = 20, 50
GRID_MARGIN, GRID_SPAN, GRID_SHIFT = 0.025, 0.95, 0.001  # of the box; of a division
GRID = -1  # the polyline of a grid point's key (GRID, i): point i of the mesh's grid points
STRAIGHT_AT = (0.4, 0.6)  # where _straight looks at the curve


class ExtrudeError(ChunkError):
    """An Extrude that cannot be evaluated; the shape stays a curve. spent: the face corners the work done before
    the refusal stands for, charged against the scene's budget (convert.scene.MAX_BUILT_CORNERS)."""

    def __init__(self, message, spent=0):
        super().__init__(message)
        self.spent = spent


class CapError(ValueError):
    """A cap that cannot be triangulated."""


class Params(collections.namedtuple("Params", "amount segments cap_start cap_end cap_type output mapping "
                                              "material_ids shape_ids smooth real_world")):
    __slots__ = ()


DEFAULT = Params(0.0, 1, True, True, CAP_MORPH, OUTPUT_MESH, False, True, False, True, False)


class Polyline(collections.namedtuple("Polyline", "points hard closed ids doubled")):
    """A spline as points (x, y, z); hard[k]: point k is a knot where the sides' smoothing changes (_hard);
    ids[k]: the zero-based material ID of the segment the column from point k belongs to (Use Shape IDs); doubled:
    a closed spline that lost a zero-length segment after a straight edge, with or without Optimize
    (3ds Max keeps both points and finds the spline touching itself there)."""
    __slots__ = ()


def is_extrude(modifier):
    return modifier.superclass == classids.SC_OSMODIFIER and modifier.class_id == classids.EXTRUDE


def _number(block, i, default):
    v = block.get(i)
    if v is None:
        return default
    if isinstance(v, pblock.Animated):
        raise ExtrudeError("parameter %d is animated (a controller)" % i)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ExtrudeError("parameter %d is not a number: %r" % (i, v))
    return v


def read_params(scene, modifier):
    """(Params, issues) of an Extrude modifier (reader.modifiers.Modifier); ExtrudeError when they cannot be
    read."""
    block = modifier.legacy.get(SLOT_PARAMS)
    if block is None:
        raise ExtrudeError("no parameter block (reference slot 0)")
    d, issues = DEFAULT, []

    def flag(i, default):
        return _number(block, i, int(default)) != 0

    segments = _number(block, P_SEGMENTS, d.segments)
    clamped = int(min(max(segments, 1), MAX_SEGMENTS))
    if clamped != segments:
        issues.append("%g segments, made with %d" % (segments, clamped))
    real_world = realworld.flag(scene.chunk(modifier.index), modifier.class_id)
    p = Params(float(_number(block, P_AMOUNT, d.amount)), clamped, flag(P_CAP_START, d.cap_start),
               flag(P_CAP_END, d.cap_end), int(_number(block, P_CAP_TYPE, d.cap_type)),
               int(_number(block, P_OUTPUT, d.output)), flag(P_MAPPING, d.mapping),
               flag(P_MATERIAL_IDS, d.material_ids), flag(P_SHAPE_IDS, d.shape_ids), flag(P_SMOOTH, d.smooth),
               real_world)
    if p.output != OUTPUT_MESH:
        issues.append("%s output is made as a mesh" % ("patch" if p.output == OUTPUT_PATCH else "NURBS"))
    return p, issues
