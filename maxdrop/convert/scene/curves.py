# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Curves: segments, curve_description() and the rectangular sections."""
import math

from ...reader import shapes
from .. import lights
from .descriptions import ADAPTIVE, CurveDescription, CurveError, SHEAR_TOLERANCE, SplineDescription


def _straight(knots, closed):
    """(left, right) handle lists of reader knots, those of each straight segment (segment type line) moved to a
    third and two thirds of its chord."""
    left = [k.in_vec for k in knots]
    right = [k.out_vec for k in knots]
    n = len(knots)
    for k, knot in enumerate(knots):
        if knot.segment != shapes.LINE or n < 2 or (k == n - 1 and not closed):
            continue
        a, b = knot.point, knots[(k + 1) % n].point
        right[k] = tuple(x + (y - x) / 3.0 for x, y in zip(a, b))
        left[(k + 1) % n] = tuple(x + (y - x) * 2.0 / 3.0 for x, y in zip(a, b))
    return left, right


def segment_ids(knots, closed):
    """The distinct material IDs of a spline's segments (reader knots) in segment order: the segment from a knot to
    the next carries the knot's; the last knot of an open spline starts none (its ID is left out), a spline without
    a segment has its first knot's."""
    count = len(knots) if closed else len(knots) - 1
    ids = [k.material for k in knots[:max(count, 1)]]
    return tuple(dict.fromkeys(ids))


def curve_description(key, name, shape, offset, meters):
    """(a CurveDescription of a reader Shape, issues): straight segments as straight handles, the offset (a reader
    matrix) applied, then meters; issues name what this drawing changes (the reader's own are the Shape's)."""
    issues = []

    def place(p):
        if offset is not None:
            p = tuple(p[0] * offset[0][c] + p[1] * offset[1][c] + p[2] * offset[2][c] + offset[3][c]
                      for c in range(3))
        return tuple(x * meters for x in p)

    splines = []
    for sp in shape.splines:
        if not sp.knots:
            continue
        left, right = _straight(sp.knots, sp.closed)
        splines.append(SplineDescription([place(k.point) for k in sp.knots], [place(p) for p in left],
                                         [place(p) for p in right], sp.closed, segment_ids(sp.knots, sp.closed)))
    if not all(_fits(p) for sd in splines for ps in (sd.points, sd.left, sd.right) for p in ps):
        raise CurveError("its points do not fit single precision (Blender's curves hold no larger value)")
    resolution = ADAPTIVE if shape.adaptive else shape.steps + 1
    depth, profile, section = 0.0, 0, None
    r = shape.render
    if r.renderable and r.rectangular:
        if r.width > 0 and r.length > 0:
            section = rectangular_section(r.width * meters, r.length * meters, r.section_angle)
            if not all(_fits(c) for c in section):
                section = None
                issues.append("a rectangular section of %g x %g does not fit single precision: not drawn"
                              % (r.width, r.length))
            elif not _flat(splines):
                issues.append("a rectangular section on a curve that is not flat in XY may turn otherwise than in "
                              "3ds Max")
        else:
            issues.append("a rectangular section of %g x %g is not drawn" % (r.width, r.length))
    elif r.renderable and r.thickness > 0:
        depth = r.thickness / 2.0 * meters
        profile = max(0, (r.sides - 4) // 2)  # Blender's round profile has 4 + 2 * resolution sides
        if not _fits((depth,)):
            depth, profile = 0.0, 0
            issues.append("a thickness of %g does not fit single precision: not drawn" % r.thickness)
    return CurveDescription(key, name, splines, resolution, depth, profile, section), issues


def rectangular_section(width, length, angle):
    """The corners of 3ds Max's rectangular section in Blender's bevel profile: width across the curve (profile x),
    length up (y), turned by angle degrees counter-clockwise in the profile, which is 3ds Max's angle (the
    shapes_more fixture's render mesh)."""
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    x, y = width / 2.0, length / 2.0
    return [(px * c - py * s, px * s + py * c) for px, py in ((x, y), (-x, y), (-x, -y), (x, -y))]


def _fits(p):
    """Whether every coordinate of p is a number Blender's single precision holds (not inf, not NaN)."""
    return all(abs(c) < lights.MAX_FLOAT for c in p)


def _flat(splines):
    """Whether every point and handle of splines (meters) lies in one plane of constant z."""
    zs = [p[2] for sd in splines for ps in (sd.points, sd.left, sd.right) for p in ps]
    if not zs:
        return True
    extent = max(abs(c) for sd in splines for p in sd.points for c in p)
    return max(zs) - min(zs) <= 1e-6 * (1.0 + extent)


def sheared(m):
    """Whether the 3x3 of a reader matrix is more than a rotation and a scale along its own axes (its rows are not
    orthogonal): Blender's matrix_basis cannot hold that."""
    rows = [m[r][:3] for r in range(3)]
    for x in range(3):
        for y in range(x + 1, 3):
            a, b = rows[x], rows[y]
            dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
            size = math.sqrt((a[0] ** 2 + a[1] ** 2 + a[2] ** 2) * (b[0] ** 2 + b[1] ** 2 + b[2] ** 2))
            if abs(dot) > SHEAR_TOLERANCE * size:
                return True
    return False
