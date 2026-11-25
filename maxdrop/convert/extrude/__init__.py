# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Extrude modifier evaluated on a shape: a reader Shape and the modifier's parameters become a MeshData.

    is_extrude(modifier)                # a reader.modifiers.Modifier of class Extrude
    params, issues = read_params(scene, modifier)   # Params; ExtrudeError when they cannot be read
    lines = polylines(shape)            # [Polyline]: each spline as 3ds Max interpolates it
    data, issues = extrude(shape, params)           # reader.geometry.MeshData in the shape's object space
    triangles = triangulate(points, outer, holes)   # ear clipping of a polygon with holes, in 2D

The parameters are an old ParamBlock in reference slot 0 (0 amount, 1 segments, 2 cap start, 3 cap end, 4 cap
type 0 morph / 1 grid, 5 output 0 patch / 1 mesh / 2 NURBS, 6 generate mapping coordinates, 7 generate material
IDs, 8 use shape IDs, 9 smooth); Real-World Map Size is the u32 0x0130 of the 0x0110 entry in the modifier's 0x2150
whose 0x0120 names the Extrude class (reader.realworld; another class's entry is not this flag).

Interpolation (3ds Max's, fitted to its own counts): each segment gets steps points between its knots; with
optimize a straight segment (segment type line, or a curve whose points at t 0.4 and 0.6 turn the path from knot to
knot by at most 2 degrees) or one back to the same spot gets none;
adaptive gives a straight segment none and splits a curved one at its middle, again and again, each piece while it
fails the same test and is wider than 1/2048 of the segment: a point at every split (3ds Max computes in float32, which
next to a cusp or far from the origin splits pieces this double test keeps). Without optimize even a straight segment
gets its steps.

The sides join segments + 1 copies of each polyline along the object's Z, one per level, amount * level / segments
up; a closed polyline also gets a cap at the bottom (Cap Start: level 0, downwards the last level) and at the top
(Cap End: the last level, downwards level 0). Closed polylines nest even-odd: one inside an even number of others is
a solid, inside an odd number a hole of its innermost container.
A closed polyline with two edges that do not follow each other and meet (cross, touch or run over each other, on XY,
without a tolerance) or that lost a zero-length segment after a straight edge gets no cap and is left out of the
nesting (no hole, no container, not turned), as 3ds Max 2020 does. Every solid is turned counter-clockwise and every hole
clockwise seen from +Z (a turned polyline starts at its last point) before the sides are made, and a negative amount
reverses the sides, so the normals point out whatever way the splines run; an open polyline keeps its own direction
(its faces look to the right of it). A cap without holes is one n-gon, a cap with holes is ear-clipped after a bridge
to each hole, which gives the triangle count 3ds Max gives.
Grid caps (cap type 1) add 3ds Max's grid points inside each solid: a grid over the box of its outline, 20 divisions
per axis, more for a small hole (floor(0.95 x size / half the hole's extent), at most 50), the points at 2.5 % from
the box plus a thousandth of a division; the cells that lie wholly inside the solid are quads and the band between
them and the outline is ear-clipped like a cap with holes (a cap of n outline points, k grid points and h holes:
n + 2k + 2h - 2 triangles, as 3ds Max). The grid points lie at z 0 and the levels' heights whatever the shape's z,
as 3ds Max puts them; a solid without a whole cell gets the morph cap. Every cap faces out, a lone one too. The cap
facing +Z gets material ID 1, the one facing -Z ID 2, the sides ID 3 (zero-based here: 0, 1, 2) when Generate
Material IDs is on, else every face ID 1; with Use Shape IDs too each side face takes the material ID of the spline
segment it comes from (the caps keep 1 and 2). Smooth gives the sides smoothing groups that change only at a
corner or Bezier corner knot or at a Bezier knot with a vector on its point (a pie Arc's corners), the caps group 16;
without it the sides have none. Mapping: the sides' U runs along each polyline from its first point (0 to 1, or its
length with Real-World Map Size), V up the levels (0 to 1, or times the amount), downwards from the far level (1 at
the shape, or the amount there); the caps map the shape's XY box (0 to 1, or its size).

The file comes from anywhere: a parameter that is animated or no number raises ExtrudeError; segments are clamped
to 1 .. MAX_SEGMENTS; a mesh past MAX_VERTICES raises ExtrudeError; a holed cap past MAX_CAP_POINTS or one that
cannot be bridged is left open, and outlines that take more than MAX_NEST_TESTS to nest get no caps (an issue
each); closed polylines past the mesh's MAX_CROSS_TESTS edge pairs are capped without the crossing test (an issue);
the holed cap that passes the mesh's MAX_CLIP_STEPS and those after it are left open (an issue, and one
more that counts the rest); a grid cap past MAX_CAP_POINTS, the mesh's MAX_GRID_TESTS, its grid bands'
MAX_GRID_CLIP_STEPS or MAX_VERTICES, or whose band does not triangulate into its area is made as a morph cap (an issue
per reason; a holed one the morph cap's own limits leave open is named as open). docs/FORMAT.md says which fixture
shows what.
No bpy; numpy is imported when a mesh is made.
"""

import collections
import math

from ...reader import chunks, classids, geometry, pblock, realworld, shapes

from .params import (
    ChunkError, P_AMOUNT, P_SEGMENTS, P_CAP_START, P_CAP_END, P_CAP_TYPE, P_OUTPUT, P_MAPPING, P_MATERIAL_IDS,
    P_SHAPE_IDS, P_SMOOTH, CAP_MORPH, CAP_GRID, OUTPUT_PATCH, OUTPUT_MESH, OUTPUT_NURBS, SLOT_PARAMS, ADAPTIVE_ANGLE,
    ADAPTIVE_DEPTH, TOP_ID, BOTTOM_ID, SIDE_ID, CAP_GROUP, MAX_SEGMENTS, MAX_VERTICES, MAX_CAP_POINTS, MAX_CLIP_STEPS,
    MAX_LOOPS, MAX_NEST_TESTS, MAX_CROSS_TESTS, CROSS_CHUNK, MAX_GRID_TESTS, MAX_GRID_CLIP_STEPS, GRID_DIVISIONS,
    GRID_MAX_DIVISIONS, GRID_MARGIN, GRID_SPAN, GRID_SHIFT, GRID, STRAIGHT_AT, ExtrudeError, CapError, Params, DEFAULT,
    Polyline, is_extrude, _number, read_params,
)
from .interpolation import _sub, _lerp, _bezier, _norm, _turn, _bent, _straight, _adaptive, _hard, _polyline, polylines
from .planar import _area, _inside, _cross, _in_triangle, _locally_inside, _bridge, _charge, _earclip, triangulate
from .mesh import (
    _nest, _turn_sign, _crosses, _crossed, _side_groups, _estimate, _sides, _divisions, _charge_grid, _grid,
    _cell_loops, _splice, _grid_cap, _morph_cap, _caps, extrude,
)
