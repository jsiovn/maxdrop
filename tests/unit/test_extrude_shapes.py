# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/extrude/ on shapes: interpolation against 3ds Max's points, triangulation and
the synthetic shapes and budgets, no Blender.

    python -I -m unittest discover tests
"""
import math
import os
import sys
import types
import unittest

_TESTS = "maxdrop_unit_tests"  # tests/unit as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_unit_tests.extrude_support import (  # noqa: E402 (after the loader)
    _face_area_z, _knots, _mats, _off, _points, _segment, _shape, _volume, extrude, FakeBlock, numpy,
    patching, shapes,
)


_T = 10 / 3.0

# One curve segment probed in 3ds Max 2020 (open SplineShape of two Bezier-corner knots, steps 6, optimize, under an
# Extrude; 3,359 segments): name, p0, c1, c2, p3, points. One probe step on either side of each boundary of its
# straight test (at t 0.4 and 0.6 the curve turns p0 -> point -> p3 by at most 2 degrees; maxdrop-em3.142).
STRAIGHT_PROBES = [
    # c1 off the chord by 10^-e chords at a third of it (near p0: at 0.001 of it; at p3), c2 on it at two thirds; the
    # pairs are the probe's own (its grid: 0.25 in e for other chords, 0.01 out of the plane and on the diagonal)
    ("third 1.72", (0, 0, 0), (_T, _off(1.72), 0), (2 * _T, 0, 0), (10, 0, 0), 2),
    ("third 1.70", (0, 0, 0), (_T, _off(1.70), 0), (2 * _T, 0, 0), (10, 0, 0), 8),
    ("near p0 1.82", (0, 0, 0), (0.01, _off(1.82), 0), (2 * _T, 0, 0), (10, 0, 0), 2),
    ("near p0 1.80", (0, 0, 0), (0.01, _off(1.80), 0), (2 * _T, 0, 0), (10, 0, 0), 8),
    ("at p3 1.78", (0, 0, 0), (10, _off(1.78), 0), (2 * _T, 0, 0), (10, 0, 0), 2),
    ("at p3 1.76", (0, 0, 0), (10, _off(1.76), 0), (2 * _T, 0, 0), (10, 0, 0), 8),
    ("in z 1.72", (0, 0, 0), (_T, 0, _off(1.72)), (2 * _T, 0, 0), (10, 0, 0), 2),
    ("in z 1.71", (0, 0, 0), (_T, 0, _off(1.71)), (2 * _T, 0, 0), (10, 0, 0), 8),
    ("chord 1000 1.75", (0, 0, 0), (1000 / 3.0, _off(1.75, 1000), 0), (2000 / 3.0, 0, 0), (1000, 0, 0), 2),
    ("chord 1000 1.5", (0, 0, 0), (1000 / 3.0, _off(1.5, 1000), 0), (2000 / 3.0, 0, 0), (1000, 0, 0), 8),
    ("chord 0.1 1.75", (0, 0, 0), (0.1 / 3, _off(1.75, 0.1), 0), (0.2 / 3, 0, 0), (0.1, 0, 0), 2),
    ("chord 0.1 1.5", (0, 0, 0), (0.1 / 3, _off(1.5, 0.1), 0), (0.2 / 3, 0, 0), (0.1, 0, 0), 8),
    ("diagonal 1.54", (5, -3, 1), (8 - 0.8 * _off(1.54), 1 + 0.6 * _off(1.54), 1), (11, 5, 1), (14, 9, 1), 2),
    ("diagonal 1.53", (5, -3, 1), (8 - 0.8 * _off(1.53), 1 + 0.6 * _off(1.53), 1), (11, 5, 1), (14, 9, 1), 8),
    # both vectors off: on one side, on opposite sides (an S, its middle on the chord)
    ("same side 1.94", (0, 0, 0), (_T, _off(1.94), 0), (2 * _T, _off(1.94), 0), (10, 0, 0), 2),
    ("same side 1.92", (0, 0, 0), (_T, _off(1.92), 0), (2 * _T, _off(1.92), 0), (10, 0, 0), 8),
    ("S 1.24", (0, 0, 0), (_T, _off(1.24), 0), (2 * _T, -_off(1.24), 0), (10, 0, 0), 2),
    ("S 1.23", (0, 0, 0), (_T, _off(1.23), 0), (2 * _T, -_off(1.23), 0), (10, 0, 0), 8),
    # on the chord's line: straight until the curve folds back past an end at t 0.4 or 0.6
    ("past p3 1.72", (0, 0, 0), (17.2, 0, 0), (2 * _T, 0, 0), (10, 0, 0), 2),
    ("past p3 1.74", (0, 0, 0), (17.4, 0, 0), (2 * _T, 0, 0), (10, 0, 0), 8),
    ("both past 4.49", (0, 0, 0), (44.9, 0, 0), (-34.9, 0, 0), (10, 0, 0), 2),
    ("both past 4.51", (0, 0, 0), (45.1, 0, 0), (-35.1, 0, 0), (10, 0, 0), 8),
    ("behind p0 -0.59", (0, 0, 0), (-5.9, 0, 0), (2 * _T, 0, 0), (10, 0, 0), 2),
    ("behind p0 -0.60", (0, 0, 0), (-6.0, 0, 0), (2 * _T, 0, 0), (10, 0, 0), 8),
    ("in vector 0 1.2", (0, 0, 0), (12, 0, 0), (10, 0, 0), (10, 0, 0), 2),
    ("in vector 0 1.25", (0, 0, 0), (12.5, 0, 0), (10, 0, 0), (10, 0, 0), 8),
    ("in vector on p0 2.1", (0, 0, 0), (21, 0, 0), (0, 0, 0), (10, 0, 0), 2),
    ("in vector on p0 2.2", (0, 0, 0), (22, 0, 0), (0, 0, 0), (10, 0, 0), 8),
    ("in vector behind 0.7", (0, 0, 0), (7, 0, 0), (-10, 0, 0), (10, 0, 0), 8),
    ("in vector behind 0.8", (0, 0, 0), (8, 0, 0), (-10, 0, 0), (10, 0, 0), 2),
    ("in vector behind 2.8", (0, 0, 0), (28, 0, 0), (-10, 0, 0), (10, 0, 0), 2),
    ("in vector behind 2.9", (0, 0, 0), (29, 0, 0), (-10, 0, 0), (10, 0, 0), 8),
]


_F3, _F6 = 3.33299994, 6.66699982  # 3.333 and 6.667 as float32, the vectors 3ds Max stored

# One curve segment probed in 3ds Max 2020 under Adaptive (an open SplineShape of two Bezier-corner knots under an
# Extrude; maxdrop-6n0.6.11): name, p0, c1, c2, p3, steps between the knots. Every point sits where a recursive split
# at the middle puts it, each piece split while its points at 0.4 and 0.6 of it turn the path by more than 2 degrees
# and it is wider than 1/2048 of the segment (cusp13: a cusp at t 1/3, kept in a piece of that width).
ADAPTIVE_PROBES = [
    ("collinear 1.75", (0, 0, 0), (17.5, 0, 0), (_F6, 0, 0), (10, 0, 0), 5),
    ("collinear 2", (0, 0, 0), (20, 0, 0), (_F6, 0, 0), (10, 0, 0), 3),
    ("collinear -0.7", (0, 0, 0), (-7, 0, 0), (_F6, 0, 0), (10, 0, 0), 4),
    ("both past", (0, 0, 0), (46, 0, 0), (-36, 0, 0), (10, 0, 0), 3),
    ("off 0.2", (0, 0, 0), (_F3, 0.200000003, 0), (_F6, 0, 0), (10, 0, 0), 2),
    ("off 1", (0, 0, 0), (_F3, 1, 0), (_F6, 0, 0), (10, 0, 0), 9),
    ("S 1", (0, 0, 0), (_F3, 1, 0), (_F6, -1, 0), (10, 0, 0), 19),
    ("S 2", (0, 0, 0), (_F3, 2, 0), (_F6, -2, 0), (10, 0, 0), 35),
    ("loop", (0, 0, 0), (10, 30, 0), (0, 30, 0), (10, 0, 0), 15),
    ("xloop", (0, 0, 0), (30, 30, 0), (-20, 30, 0), (10, 0, 0), 97),
    ("cusp", (0, 0, 0), (10, 10, 0), (0, 10, 0), (10, 0, 0), 29),
    ("hook", (0, 0, 0), (0, 40, 0), (10, 0, 0), (10, 0, 0), 60),
    ("big", (0, 0, 0), (100, 100, 0), (-90, 100, 0), (10, 0, 0), 103),
    ("knee", (0, 0, 0), (5, 0, 0), (10, 10, 0), (10, 0, 0), 55),
    ("cusp13", (0, 0, 0), (4, 6, 0), (-3, 0, 0), (9, 0, 0), 49),
]
# 3ds Max computes in float32: next to a cusp, or far from the origin, its rounding splits pieces the test keeps
# (and the other way round by a hair at 2 degrees); MaxDrop computes in double. These got 129, 73 and 50 steps in 3ds
# Max (cusp13 x1000: one more piece split next to the cusp); the double rule's own counts are pinned.
ADAPTIVE_FLOAT32 = [
    ("zz", (0, 0, 0), (40, 20, 0), (-30, -20, 0), (10, 0, 0), 131),
    ("tight", (0, 0, 0), (10, 1, 0), (0, 1, 0), (10, 0, 0), 63),
    ("cusp13 x1000", (0, 0, 0), (4000, 6000, 0), (-3000, 0, 0), (9000, 0, 0), 49),
]


class Interpolation(unittest.TestCase):
    """Point counts 3ds Max 2020's Extrude makes (half its vertex count on one segment)."""

    def circle(self, **kw):
        return _shape([shapes.Spline(tuple(shapes._circle(4, 10.0)), True)], **kw)

    def rounded(self, **kw):
        params = shapes._Params(FakeBlock({0: 20.0, 1: 30.0, 2: 3.0}))
        return _shape(shapes._rectangle(params, []), **kw)

    def test_steps(self):
        self.assertEqual([_points(self.circle(steps=s)) for s in (0, 1, 6)], [4, 8, 28])

    def test_optimize_skips_straight_segments(self):
        self.assertEqual(_points(self.rounded(steps=2)), 16)
        self.assertEqual(_points(self.rounded(steps=2, optimize=False)), 24)
        sharp = _shape([shapes.Spline(_knots([(0, 0, 0), (30, 0, 0), (30, 20, 0), (0, 20, 0)]), True)],
                       steps=2, optimize=False)
        self.assertEqual(_points(sharp), 12)  # even a line segment gets its steps

    def test_adaptive(self):
        self.assertEqual(_points(self.circle(adaptive=True)), 128)
        self.assertEqual(_points(self.rounded(adaptive=True)), 132)  # the straight sides get none
        for degrees, want in ((30, 13), (90, 25), (180, 49), (300, 97)):
            knots = shapes._arc_knots(10.0, 0.0, math.radians(degrees) / 3.0, 4)
            arc = _shape([shapes.Spline(tuple(knots), False)], adaptive=True)
            self.assertEqual(_points(arc), want, degrees)

    def test_straight_bezier_and_duplicate_points(self):
        k = shapes.Knot
        straight = (k(shapes.BEZIER, shapes.CURVE, (0, 0, 0), (-1, 0, 0), (1, 0, 0)),
                    k(shapes.BEZIER, shapes.CURVE, (10, 0, 0), (9, 0, 0), (11, 0, 0)))
        self.assertEqual(_points(_shape([shapes.Spline(straight, False)], steps=3)), 2)
        twice = _knots([(0, 0, 0), (0, 0, 0), (5, 0, 0), (5, 5, 0)])
        pl = extrude.polylines(_shape([shapes.Spline(twice, True)]))[0]
        self.assertEqual(len(pl.points), 3)
        two = extrude.polylines(_shape([shapes.Spline(_knots([(0, 0, 0), (5, 0, 0)]), True)]))[0]
        self.assertFalse(two.closed)  # a closed spline of two points has no inside

    def test_straight_equals_3ds_max(self):
        for name, p0, c1, c2, p3, points in STRAIGHT_PROBES:
            self.assertEqual(_points(_shape([_segment(p0, c1, c2, p3)])), points, name)
            self.assertEqual(_points(_shape([_segment(p0, c1, c2, p3)], optimize=False)), 8, name)

    def test_a_vector_just_off_the_chord(self):
        """maxdrop-em3.111's probe: a 20 x 20 square of corner knots with a Bezier knot at (10, -4) whose in vector
        lies d off the chord from the corner at the origin; 3ds Max makes 11 points for d = 1e-3 .. 1e-6 (only the
        segment out of the Bezier knot gets its 6 steps). The vectors of the origin and the Bezier knot are the ones
        3ds Max stored; the other corners' lie on their straight sides."""
        k = shapes.Knot
        for d in (1e-3, 1e-4, 1e-5, 1e-6):
            knots = (k(shapes.CORNER, shapes.CURVE, (0, 0, 0), (0, 20 / 3.0, 0), ((10 - d) / 2, -2, 0)),
                     k(shapes.BEZIER, shapes.CURVE, (10, -4, 0), (10 - d, -4, 0), (14, -4, 0)),
                     k(shapes.CORNER, shapes.CURVE, (20, 0, 0), (17, -2, 0), (20, 20 / 3.0, 0)),
                     k(shapes.CORNER, shapes.CURVE, (20, 20, 0), (20, 40 / 3.0, 0), (40 / 3.0, 20, 0)),
                     k(shapes.CORNER, shapes.CURVE, (0, 20, 0), (20 / 3.0, 20, 0), (0, 40 / 3.0, 0)))
            self.assertEqual(_points(_shape([shapes.Spline(knots, True)])), 11, d)

    def test_adaptive_takes_the_same_straight_test(self):
        """3ds Max 2020, Adaptive: a segment straight for Optimize gets no steps, also one whose vectors run past
        the chord's end or lie a little off it; a curved one gets at least one."""
        for name, p0, c1, c2, p3, points in STRAIGHT_PROBES:
            got = _points(_shape([_segment(p0, c1, c2, p3)], adaptive=True))
            if points == 2:
                self.assertEqual(got, 2, name)
            else:
                self.assertGreater(got, 2, name)

    def test_adaptive_equals_3ds_max(self):
        for name, p0, c1, c2, p3, steps in ADAPTIVE_PROBES + ADAPTIVE_FLOAT32:
            for optimize in (True, False):  # Adaptive ignores Optimize (3ds Max: the same counts)
                got = _points(_shape([_segment(p0, c1, c2, p3)], optimize=optimize, adaptive=True))
                self.assertEqual(got, steps + 2, (name, optimize))

    def test_adaptive_puts_the_points_where_3ds_max_does(self):
        """The parameters of 3ds Max's points on the segment (read back from its vertices): not uniform steps."""
        cases = (("off 1", [1, 2, 3, 4, 5, 6, 8, 12, 14], 16),
                 ("S 1", [1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 22, 24, 26, 27, 28, 29, 30, 31], 32))
        probes = {c[0]: c for c in ADAPTIVE_PROBES}
        for name, numerators, denominator in cases:
            _n, p0, c1, c2, p3, _steps = probes[name]
            want = [extrude._bezier(p0, c1, c2, p3, k / float(denominator)) for k in numerators]
            pl = extrude.polylines(_shape([_segment(p0, c1, c2, p3)], adaptive=True))[0]
            self.assertEqual(pl.points[1:-1], want, name)

    def test_adaptive_is_counted_against_a_budget(self):
        """2047 steps a segment at most: an adaptive shape is counted as it is made, and one whose points pass the
        budget is refused: an open spline (its last knot too), the room left after another spline, a closed one."""
        many = _shape([shapes.Spline(_knots([(k, k % 2, 0) for k in range(1000)]), False)], adaptive=True)
        self.assertEqual(sum(len(pl.points) for pl in extrude.polylines(many, 1000)), 1000)
        with self.assertRaises(extrude.ExtrudeError):
            extrude.polylines(many, 999)
        loop = _segment((0, 0, 0), (10, 30, 0), (0, 30, 0), (10, 0, 0))  # 15 steps: 17 points
        for most, splines in ((17, [loop]), (34, [loop, loop])):
            shape = _shape(splines, adaptive=True)
            self.assertEqual(sum(len(pl.points) for pl in extrude.polylines(shape, most)), most)
            with self.assertRaises(extrude.ExtrudeError):
                extrude.polylines(shape, most - 1)
        k = shapes.Knot
        drop = shapes.Spline((k(shapes.BEZIER_CORNER, shapes.CURVE, (0, 0, 0), (0, 0, 0), (10, 30, 0)),
                              k(shapes.BEZIER_CORNER, shapes.CURVE, (10, 0, 0), (0, 30, 0), (10, 0, 0))), True)
        closed = _shape([drop], adaptive=True)  # the loop, then a straight line back: 17 points
        self.assertEqual([len(pl.points) for pl in extrude.polylines(closed, 17)], [17])
        with self.assertRaises(extrude.ExtrudeError):
            extrude.polylines(closed, 16)

    def test_a_doubled_knot_with_its_vectors_on_it(self):
        """A zero-length curve segment whose vectors lie on its point is straight under Adaptive too (no steps from
        rounding), so the doubled knot stays one point and the spline touches itself, as under Optimize."""
        k = shapes.Knot
        p = (0.1, 0.7, 0.3)
        knots = (k(shapes.BEZIER_CORNER, shapes.CURVE, (-5, -5, 0.3), (-5, -5, 0.3), (-5, -5, 0.3)),
                 k(shapes.BEZIER_CORNER, shapes.CURVE, p, p, p), k(shapes.BEZIER_CORNER, shapes.CURVE, p, p, p),
                 k(shapes.BEZIER_CORNER, shapes.CURVE, (5, 5, 0.3), (5, 5, 0.3), (5, 5, 0.3)))
        for adaptive in (False, True):
            pl = extrude.polylines(_shape([shapes.Spline(knots, True)], adaptive=adaptive))[0]
            self.assertEqual((len(pl.points), pl.doubled), (3, True), adaptive)


def _ccw_area(pts, tris):
    return sum(extrude._cross(pts[a], pts[b], pts[c]) / 2.0 for a, b, c in tris)


class Triangulate(unittest.TestCase):
    def check(self, pts, outer, holes=(), area=None):
        tris = extrude.triangulate(pts, outer, holes)
        n = len(outer) + sum(len(h) for h in holes)
        self.assertEqual(len(tris), n + 2 * len(holes) - 2)
        self.assertTrue(all(extrude._cross(pts[a], pts[b], pts[c]) > 0 for a, b, c in tris), tris)
        if area is not None:
            self.assertAlmostEqual(_ccw_area(pts, tris), area, places=6)
        return tris

    def test_concave_comb(self):
        pts = [(0, 0), (10, 0), (10, 10), (8, 10), (8, 2), (6, 2), (6, 10), (4, 10), (4, 2), (2, 2), (2, 10),
               (0, 10)]
        self.check(pts, list(range(len(pts))), area=100 - 3 * 2 * 8 + 2 * 8)

    def test_two_holes(self):
        pts = [(0, 0), (20, 0), (20, 10), (0, 10),
               (2, 2), (2, 8), (8, 8), (8, 2),  # clockwise
               (12, 2), (12, 8), (18, 8), (18, 2)]
        self.check(pts, [0, 1, 2, 3], [[4, 5, 6, 7], [8, 9, 10, 11]], area=200 - 72)

    def test_holes_side_by_side_on_one_ray(self):
        pts = [(0, 0), (30, 0), (30, 10), (0, 10),
               (2, 4), (2, 6), (6, 6), (6, 4),
               (10, 4), (10, 6), (14, 6), (14, 4),
               (20, 3), (20, 7), (25, 7), (25, 3)]
        self.check(pts, [0, 1, 2, 3], [[4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]],
                   area=300 - 8 - 8 - 20)

    def test_holes_bridged_to_one_vertex(self):
        """Three holes in a column bridge to the same corner of the hole to their right: each bridge must leave
        from the copy of that corner whose angle faces it, or the ring crosses itself (a wardrobe front)."""
        rects = [(1, 15, 7, 22), (1, 8, 7, 14), (1, 1, 7, 7), (9, 1, 17, 22), (19, 15, 25, 22), (19, 8, 25, 14),
                 (19, 1, 25, 7)]
        pts, holes = [(0, 0), (26, 0), (26, 23), (0, 23)], []
        for x0, y0, x1, y1 in rects:
            holes.append(list(range(len(pts), len(pts) + 4)))
            pts += [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]  # clockwise
        area = 26 * 23 - sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
        self.check(pts, [0, 1, 2, 3], holes, area=area)

    def test_hole_behind_a_notch(self):
        # the notch's reflex corner (10, 6) hides the first ring vertex the ray from the hole reaches
        pts = [(0, 0), (20, 0), (20, 12), (10, 12), (10, 6), (14, 6), (14, 4), (8, 4), (8, 12), (0, 12),
               (2, 6), (2, 9), (5, 9), (5, 6)]
        self.check(pts, list(range(10)), [[10, 11, 12, 13]])

    def test_collinear_points(self):
        pts = [(0, 0), (1, 0), (2, 0), (3, 0), (3, 1), (2, 1), (1, 1), (0, 1)]
        tris = extrude.triangulate(pts, list(range(8)))
        self.assertEqual(len(tris), 6)
        self.assertAlmostEqual(_ccw_area(pts, tris), 3.0)

    def test_a_hole_outside_cannot_be_bridged(self):
        pts = [(0, 0), (1, 0), (1, 1), (0, 1), (5, 5), (5, 6), (6, 6), (6, 5)]
        with self.assertRaises(extrude.CapError):
            extrude.triangulate(pts, [0, 1, 2, 3], [[4, 5, 6, 7]])

    def test_a_spent_budget_is_a_cap_error(self):
        pts = [(0, 0), (20, 0), (20, 10), (0, 10), (2, 2), (2, 8), (8, 8), (8, 2)]
        budget = [10 ** 9]
        extrude.triangulate(pts, [0, 1, 2, 3], [[4, 5, 6, 7]], budget)
        used = 10 ** 9 - budget[0]
        self.assertGreater(used, 0)
        with self.assertRaises(extrude.CapError):
            extrude.triangulate(pts, [0, 1, 2, 3], [[4, 5, 6, 7]], [used - 1])

    def test_a_self_crossing_outline_still_ends(self):
        pts = [(0, 0), (10, 10), (10, 0), (0, 10), (5, 12), (-2, 6)]
        tris = extrude.triangulate(pts, list(range(len(pts))))
        self.assertLessEqual(len(tris), 4)
        self.assertTrue(all(len(set(t)) == 3 for t in tris))


@unittest.skipIf(numpy is None, "numpy missing")
class Synthetic(unittest.TestCase):
    def params(self, **kw):
        return extrude.DEFAULT._replace(**dict(dict(amount=5.0), **kw))

    def square(self, size, clockwise=False, z=0.0):
        pts = [(0, 0, z), (size, 0, z), (size, size, z), (0, size, z)]
        return shapes.Spline(_knots(pts[::-1] if clockwise else pts), True)

    def test_a_clockwise_outline_is_turned(self):
        data, issues = extrude.extrude(_shape([self.square(4, clockwise=True)]), self.params())
        self.assertEqual(issues, [])
        self.assertAlmostEqual(_volume(data.positions, data), 80.0, places=4)

    def test_a_turned_outline_starts_at_its_last_point(self):
        """3ds Max turns the whole polyline: the side U starts at the last point of a clockwise outline
        (arc_pie_reverse's FixtureClockwiseExt), then runs counter-clockwise."""
        data, _issues = extrude.extrude(_shape([self.square(4, clockwise=True)]), self.params(mapping=True))
        ch = data.maps[1]
        us = {}
        for f in range(len(data.loop_starts)):
            s, t = int(data.loop_starts[f]), int(data.loop_totals[f])
            p = data.positions[data.loop_vertices[s:s + t]]
            if numpy.ptp(p[:, 2]) == 0:  # a cap
                continue
            for v, i in zip(data.loop_vertices[s:s + t].tolist(), ch.indices[s:s + t].tolist()):
                if data.positions[v][2] == 0:
                    at = tuple(float(c) for c in data.positions[v][:2])
                    us.setdefault(at, set()).add(round(float(ch.uvw[i][0]), 6))
        self.assertEqual(us, {(0.0, 0.0): {0.0, 1.0}, (4.0, 0.0): {0.25}, (4.0, 4.0): {0.5}, (0.0, 4.0): {0.75}})

    def test_negative_amount_and_segments(self):
        data, _issues = extrude.extrude(_shape([self.square(4)]), self.params(amount=-5.0, segments=3))
        self.assertEqual(len(data.positions), 16)
        self.assertAlmostEqual(_volume(data.positions, data), 80.0, places=4)
        self.assertAlmostEqual(float(data.positions[:, 2].min()), -5.0)

    def test_a_lone_cap_of_a_downward_extrusion_faces_out(self):
        """3ds Max 2020 (a Circle extruded -4; maxdrop-6n0.6.10's rectangles at -5): Cap Start lies at the far level
        (z = amount) facing -Z (ID 2), Cap End at the shape facing +Z (ID 1), alone or together; the sides face
        out in every case."""
        for start, end, want in ((True, False, [(extrude.BOTTOM_ID, False, -4.0)]),
                                 (False, True, [(extrude.TOP_ID, True, 0.0)]),
                                 (True, True, [(extrude.TOP_ID, True, 0.0), (extrude.BOTTOM_ID, False, -4.0)])):
            data, _issues = extrude.extrude(_shape([self.square(4)]), self.params(amount=-4.0, cap_start=start,
                                                                                  cap_end=end))
            caps = sorted({(int(_mats(data)[f]), _face_area_z(data, f) > 0,
                            float(data.positions[data.loop_vertices[int(data.loop_starts[f])]][2]))
                           for f in range(len(data.loop_starts)) if int(_mats(data)[f]) != extrude.SIDE_ID})
            self.assertEqual(caps, sorted(want), (start, end))
            sides = [f for f in range(len(data.loop_starts)) if int(_mats(data)[f]) == extrude.SIDE_ID]
            p = data.positions.astype(numpy.float64)
            for f in sides:  # outward: the face normal points away from the square's center
                s, t = int(data.loop_starts[f]), int(data.loop_totals[f])
                q = p[data.loop_vertices[s:s + t]]
                n = numpy.cross(q[1] - q[0], q[2] - q[0])
                self.assertGreater(float(numpy.dot(n[:2], q.mean(axis=0)[:2] - (2.0, 2.0))), 0, (start, end))

    def test_a_lone_grid_cap_of_a_downward_extrusion_lies_at_its_level(self):
        """Grid caps alike (maxdrop-6n0.6.10's probe, amount -5 in 2 segments): every cap vertex, the grid points
        too, lies at z -5 for Cap Start and z 0 for Cap End, with the cap's ID and facing."""
        for start, end, want in ((True, False, {(extrude.BOTTOM_ID, False, -5.0)}),
                                 (False, True, {(extrude.TOP_ID, True, 0.0)}),
                                 (True, True, {(extrude.TOP_ID, True, 0.0), (extrude.BOTTOM_ID, False, -5.0)})):
            data, issues = extrude.extrude(_shape([self.square(20)]), self.params(
                amount=-5.0, segments=2, cap_start=start, cap_end=end, cap_type=extrude.CAP_GRID))
            self.assertEqual(issues, [], (start, end))
            got, grid = set(), 0
            for f in range(len(data.loop_starts)):
                if int(_mats(data)[f]) == extrude.SIDE_ID:
                    continue
                s, t = int(data.loop_starts[f]), int(data.loop_totals[f])
                zs = {float(data.positions[v][2]) for v in data.loop_vertices[s:s + t].tolist()}
                self.assertEqual(len(zs), 1, (start, end))
                got.add((int(_mats(data)[f]), _face_area_z(data, f) > 0, zs.pop()))
                grid = max(grid, int(data.loop_vertices[s:s + t].max()))
            self.assertEqual(got, want, (start, end))
            self.assertGreaterEqual(grid, 4 * 3)  # the caps use grid points, past the sides' 4 x 3 vertices

    def test_no_caps_and_flat_sides(self):
        data, _issues = extrude.extrude(_shape([self.square(4)]), self.params(cap_start=False, cap_end=False,
                                                                              smooth=False))
        self.assertEqual(len(data.loop_starts), 4)
        self.assertEqual(set(data.smoothing_groups.tolist()), {0})
        data, _issues = extrude.extrude(_shape([self.square(4)]), self.params(cap_start=False))
        self.assertEqual(sorted(set(_mats(data).tolist())), [extrude.TOP_ID, extrude.SIDE_ID])

    def side_ids(self, data):
        """{(axis, coordinate): {material IDs}} of the side faces of an axis-aligned square mesh, by the vertical
        plane each lies in (x = c or y = c)."""
        out = {}
        for f in range(len(data.loop_starts)):
            s, t = int(data.loop_starts[f]), int(data.loop_totals[f])
            p = data.positions[data.loop_vertices[s:s + t]].astype(numpy.float64)
            for axis in (0, 1):
                if numpy.ptp(p[:, axis]) < 1e-6 and numpy.ptp(p[:, 2]) > 0:
                    out.setdefault((axis, round(float(p[0, axis]), 4)), set()).add(int(_mats(data)[f]))
        return out

    def id_square(self, pts, ids, kind=shapes.CORNER):
        return shapes.Spline(tuple(shapes.Knot(kind, shapes.LINE, p, p, p, i) for p, i in zip(pts, ids)), True)

    def test_use_shape_ids(self):
        """3ds Max 2020 (probe): with Generate Material IDs and Use Shape IDs each side face takes its segment's ID
        (3ds Max IDs 1 4 7 2 on a counter-clockwise square: y=0 1, x=10 4, y=10 7, x=0 2); the caps keep 1 and 2."""
        sq = self.id_square([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], (0, 3, 6, 1))
        data, issues = extrude.extrude(_shape([sq]), self.params(shape_ids=True))
        self.assertEqual(issues, [])
        self.assertEqual(self.side_ids(data), {(1, 0.0): {0}, (0, 10.0): {3}, (1, 10.0): {6}, (0, 0.0): {1}})
        for f in range(len(data.loop_starts)):
            z = _face_area_z(data, f)
            if abs(z) > 1e-6:
                self.assertEqual(int(_mats(data)[f]), extrude.TOP_ID if z > 0 else extrude.BOTTOM_ID)
        data, _issues = extrude.extrude(_shape([sq]), self.params(amount=-5.0, shape_ids=True))  # probe E
        self.assertEqual(self.side_ids(data), {(1, 0.0): {0}, (0, 10.0): {3}, (1, 10.0): {6}, (0, 0.0): {1}})
        self.assertAlmostEqual(_volume(data.positions, data), 500.0, places=3)

    def test_use_shape_ids_on_a_turned_outline(self):
        """A clockwise outline is turned before the sides are made: each face keeps the ID of the segment it lies
        on (probe C: IDs 3 5 6 9 from (0,0) up to (0,10), across, down: x=0 3, y=10 5, x=10 6, y=0 9)."""
        sq = self.id_square([(0, 0, 0), (0, 10, 0), (10, 10, 0), (10, 0, 0)], (2, 4, 5, 8))
        data, _issues = extrude.extrude(_shape([sq]), self.params(shape_ids=True, segments=2))
        self.assertEqual(self.side_ids(data), {(0, 0.0): {2}, (1, 10.0): {4}, (0, 10.0): {5}, (1, 0.0): {8}})
        self.assertAlmostEqual(_volume(data.positions, data), 500.0, places=3)

    def test_use_shape_ids_on_a_hole(self):
        """A hole drawn counter-clockwise is turned clockwise: its faces keep their segments' IDs."""
        outer = self.id_square([(0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 20, 0)], (1, 1, 1, 1))
        hole = self.id_square([(5, 5, 0), (15, 5, 0), (15, 15, 0), (5, 15, 0)], (10, 11, 12, 13))
        data, _issues = extrude.extrude(_shape([outer, hole]), self.params(shape_ids=True))
        got = self.side_ids(data)
        self.assertEqual({k: got[k] for k in ((1, 5.0), (0, 15.0), (1, 15.0), (0, 5.0))},
                         {(1, 5.0): {10}, (0, 15.0): {11}, (1, 15.0): {12}, (0, 5.0): {13}})
        self.assertAlmostEqual(_volume(data.positions, data), (400 - 100) * 5.0, places=3)

    def test_use_shape_ids_on_interpolated_and_open_splines(self):
        """Probe D: an open line of two curved segments (IDs 2, 3), steps 2: every face of a segment takes its ID;
        a zero-length segment leaves its column to the next segment's ID."""
        k = shapes.Knot
        line = shapes.Spline((k(shapes.CORNER, shapes.CURVE, (0, 0, 0), (0, 0, 0), (3, 4, 0), 1),
                              k(shapes.SMOOTH, shapes.CURVE, (10, 5, 0), (6, 5, 0), (14, 5, 0), 2),
                              k(shapes.CORNER, shapes.CURVE, (20, 0, 0), (17, 4, 0), (20, 0, 0), 0)), False)
        data, _issues = extrude.extrude(_shape([line], steps=2), self.params(shape_ids=True))
        mats = _mats(data).tolist()
        self.assertEqual(mats, [1, 1, 1, 2, 2, 2])
        pts = [(0, 0, 0), (4, 0, 0), (4, 0, 0), (4, 4, 0)]
        sq = shapes.Spline(tuple(k(shapes.CORNER, shapes.LINE, p, p, p, i) for p, i in zip(pts, (5, 6, 7, 8))), True)
        lines = extrude.polylines(_shape([sq]))
        self.assertEqual((lines[0].points, lines[0].ids), ([(0, 0, 0), (4, 0, 0), (4, 4, 0)], [5, 7, 8]))

    def test_use_shape_ids_on_a_turned_outline_with_a_closing_knot_and_steps(self):
        """A clockwise outline whose last knot lies on its first (a zero-length closing segment), with a curved
        segment in steps: the closing column goes, every other face keeps its segment's ID after the turn."""
        k = shapes.Knot
        c, ln = shapes.CURVE, shapes.LINE
        outline = shapes.Spline((k(shapes.CORNER, ln, (0, 0, 0), (0, 0, 0), (0, 0, 0), 4),
                                 k(shapes.BEZIER_CORNER, c, (0, 10, 0), (0, 10, 0), (4, 14, 0), 5),
                                 k(shapes.BEZIER_CORNER, ln, (10, 10, 0), (6, 14, 0), (10, 10, 0), 6),
                                 k(shapes.CORNER, ln, (10, 0, 0), (10, 0, 0), (10, 0, 0), 7),
                                 k(shapes.CORNER, ln, (0, 0, 0), (0, 0, 0), (0, 0, 0), 9)), True)
        lines = extrude.polylines(_shape([outline], steps=3))
        self.assertEqual(len(lines[0].points), 7)  # 4 knots and 3 steps, the closing knot dropped
        self.assertEqual(lines[0].ids, [4, 5, 5, 5, 5, 6, 7])
        data, _issues = extrude.extrude(_shape([outline], steps=3), self.params(shape_ids=True))
        got = self.side_ids(data)
        self.assertEqual({key: got[key] for key in ((0, 0.0), (0, 10.0), (1, 0.0))},
                         {(0, 0.0): {4}, (0, 10.0): {6}, (1, 0.0): {7}})
        curved = [int(_mats(data)[f]) for f in range(len(data.loop_starts))
                  if abs(_face_area_z(data, f)) <= 1e-6 and data.positions[data.loop_vertices[
                      int(data.loop_starts[f]):int(data.loop_starts[f]) + 4]][:, 1].min() > 10.0 - 1e-6
                  and data.positions[data.loop_vertices[
                      int(data.loop_starts[f]):int(data.loop_starts[f]) + 4]][:, 1].max() > 10.0 + 1e-6]
        self.assertEqual(curved, [5] * 4)
        self.assertNotIn(9, set(_mats(data).tolist()))

    def test_shape_ids_need_generated_material_ids(self):
        """Probe B: Use Shape IDs without Generate Material IDs gives every face ID 1; Generate Material IDs alone
        gives the sides ID 3."""
        sq = self.id_square([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], (0, 3, 6, 1))
        data, _issues = extrude.extrude(_shape([sq]), self.params(shape_ids=True, material_ids=False))
        self.assertEqual(set(_mats(data).tolist()), {0})
        data, _issues = extrude.extrude(_shape([sq]), self.params())
        self.assertEqual({i for ids in self.side_ids(data).values() for i in ids}, {extrude.SIDE_ID})

    def test_smoothing_changes_only_at_corners(self):
        k = shapes.Knot
        one_corner = (k(shapes.CORNER, shapes.LINE, (0, 0, 0), (0, 0, 0), (0, 0, 0)),
                      k(shapes.SMOOTH, shapes.LINE, (4, 0, 0), (4, 0, 0), (4, 0, 0)),
                      k(shapes.SMOOTH, shapes.LINE, (4, 4, 0), (4, 4, 0), (4, 4, 0)),
                      k(shapes.SMOOTH, shapes.LINE, (0, 4, 0), (0, 4, 0), (0, 4, 0)))
        data, _issues = extrude.extrude(_shape([shapes.Spline(one_corner, True)]), self.params(cap_start=False,
                                                                                              cap_end=False))
        g = data.smoothing_groups.tolist()
        self.assertEqual([g[k] & g[(k + 1) % 4] != 0 for k in range(4)], [True, True, True, False])
        for runs in (2, 3, 5):
            pts = [(math.cos(2 * math.pi * k / runs), math.sin(2 * math.pi * k / runs), 0) for k in range(runs)]
            groups = extrude._side_groups([True] * runs, True, runs, True)
            self.assertTrue(all(groups[k] & groups[(k + 1) % runs] == 0 for k in range(runs)), (runs, groups, pts))

    def test_smoothing_breaks_where_3ds_max_breaks_it(self):
        """The 3ds Max 2020 probe of maxdrop-em3.111: a 20 x 20 square of corner knots with a fifth knot A on its
        bottom edge, kinked at (10, -4) or straight at (10, 0), under Extrude: the side breaks at a corner or
        Bezier-corner knot whatever the angle, never at a smooth knot (also where line segments kink the spline)
        or a Bezier knot with both vectors off its point (also kinked by lines), and at a Bezier knot whose in or
        out vector is its point (kinked or straight, curve or line segments): exactly, a vector 1e-6 off (float32
        apart at 10) or 1e-9 off at the origin is not on it."""
        k, c, b, bc, sm = shapes.Knot, shapes.CORNER, shapes.BEZIER, shapes.BEZIER_CORNER, shapes.SMOOTH
        kink, flat = (10.0, -4.0, 0.0), (10.0, 0.0, 0.0)
        left, right = (6.0, -4.0, 0.0), (14.0, -4.0, 0.0)
        line, curve = shapes.LINE, shapes.CURVE
        cases = (  # (name, knot A, the segment to A, breaks)
            ("corner, kinked", k(c, line, kink, kink, kink), line, True),
            ("corner, straight", k(c, line, flat, flat, flat), line, True),
            ("corner, 2.3 degrees", k(c, line, (10.0, -0.2, 0.0), (10.0, -0.2, 0.0), (10.0, -0.2, 0.0)), line, True),
            ("smooth, kinked by lines", k(sm, line, kink, (6.666666, -4.0, 0.0), (13.33333, -4.0, 0.0)), line,
             False),
            ("smooth, curved", k(sm, curve, kink, (6.666666, -4.0, 0.0), (13.33333, -4.0, 0.0)), curve, False),
            ("Bezier", k(b, curve, kink, left, right), curve, False),
            ("Bezier, kinked by lines", k(b, line, kink, left, right), line, False),
            ("Bezier, a line into it", k(b, curve, kink, left, right), line, False),
            ("Bezier, in on the point", k(b, curve, kink, kink, right), curve, True),
            ("Bezier, out on the point", k(b, curve, kink, left, kink), curve, True),
            ("Bezier, both on the point", k(b, curve, kink, kink, kink), curve, True),
            ("Bezier, in on the point, straight", k(b, curve, flat, flat, (14.0, 0.0, 0.0)), curve, True),
            ("Bezier, both on the point, lines", k(b, line, kink, kink, kink), line, True),
            ("Bezier, in 1e-6 off", k(b, curve, kink, (9.999999, -4.0, 0.0), right), curve, False),
            ("Bezier corner", k(bc, curve, kink, left, right), curve, True),
        )
        for name, a, into, breaks in cases:
            ks = (k(c, into, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)), a,
                  k(c, line, (20.0, 0.0, 0.0), (20.0, 0.0, 0.0), (20.0, 0.0, 0.0)),
                  k(c, line, (20.0, 20.0, 0.0), (20.0, 20.0, 0.0), (20.0, 20.0, 0.0)),
                  k(c, line, (0.0, 20.0, 0.0), (0.0, 20.0, 0.0), (0.0, 20.0, 0.0)))
            pl = extrude.polylines(_shape([shapes.Spline(ks, True)]))[0]
            self.assertEqual(pl.hard[pl.points.index(a.point)], breaks, name)
            data, _issues = extrude.extrude(_shape([shapes.Spline(ks, True)]),
                                            self.params(cap_start=False, cap_end=False))
            g = data.smoothing_groups.tolist()
            self.assertEqual(sum(g[j] & g[(j + 1) % len(g)] == 0 for j in range(len(g))), 5 if breaks else 4, name)
        at_origin = k(b, curve, (0.0, 0.0, 0.0), (-1e-9, 0.0, 0.0), (4.0, 0.0, 0.0))
        self.assertFalse(extrude._hard(at_origin))
        self.assertTrue(extrude._hard(at_origin._replace(in_vec=at_origin.point)))
        opened = (k(c, curve, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)), k(b, curve, kink, kink, kink),
                  k(c, curve, (20.0, 0.0, 0.0), (20.0, 0.0, 0.0), (20.0, 0.0, 0.0)))
        data, _issues = extrude.extrude(_shape([shapes.Spline(opened, False)]), self.params())
        g = data.smoothing_groups.tolist()
        self.assertEqual([g[j] & g[j + 1] == 0 for j in range(len(g) - 1)], [True], "open")

    def rect(self, x0, y0, x1, y1):
        return shapes.Spline(_knots([(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)]), True)

    def test_nested_holes_and_islands(self):
        """A solid, a hole touching its side, an island in that hole, a second hole: even-odd."""
        data, issues = extrude.extrude(_shape([self.square(10), self.square(4), self.rect(1, 1, 3, 3),
                                               self.rect(5, 5, 9, 9)]), self.params())
        self.assertEqual(issues, [])
        top = [f for f in range(len(data.loop_starts)) if _mats(data)[f] == extrude.TOP_ID]
        self.assertAlmostEqual(sum(_face_area_z(data, f) for f in top), 100 - 16 + 4 - 16, places=4)
        self.assertAlmostEqual(_volume(data.positions, data), (100 - 16 + 4 - 16) * 5.0, places=3)

    def test_overlapping_outlines_leave_a_hole_open(self):
        """Two holes that overlap, a third outline inside both: its innermost container is a hole."""
        data, issues = extrude.extrude(_shape([self.square(10), self.rect(1, 1, 6, 6), self.rect(4, 4, 9, 9),
                                               self.rect(4.5, 4.5, 5.5, 5.5)]), self.params())
        self.assertEqual(issues, ["an outline overlaps another: its hole is left open"])
        self.assertGreater(len(data.loop_starts), 0)

    def test_adaptive_points_past_the_budget(self):
        """An adaptive shape the up-front estimate lets through (one point a knot) is refused once its points are
        made, and the refusal is charged like the sides it would have made; 1,000 knots of 2047 steps at most each
        are not refused up front."""
        many = _shape([shapes.Spline(_knots([(k, k % 2, 0) for k in range(1000)]), False)], adaptive=True)
        data, _issues = extrude.extrude(many, self.params())
        self.assertEqual(len(data.positions), 2000)
        loop = _shape([_segment((0, 0, 0), (10, 30, 0), (0, 30, 0), (10, 0, 0))], adaptive=True)  # 17 points
        with patching.patch_all(extrude, "MAX_VERTICES", 33):
            with self.assertRaises(extrude.ExtrudeError) as caught:
                extrude.extrude(loop, self.params(segments=2))
        self.assertEqual((str(caught.exception), caught.exception.spent), ("more than 33 vertices", 11 * 2 * 4))
        with patching.patch_all(extrude, "MAX_VERTICES", 34):
            data, _issues = extrude.extrude(loop, self.params())
        self.assertEqual(len(data.positions), 34)

    def test_flat_amount_is_an_issue(self):
        _data, issues = extrude.extrude(_shape([self.square(4)]), self.params(amount=0.0))
        self.assertEqual(len(issues), 1)

    def test_hostile_sizes(self):
        with patching.patch_all(extrude, "MAX_VERTICES", 10):
            with self.assertRaises(extrude.ExtrudeError):
                extrude.extrude(_shape([self.square(4), self.square(2)]), self.params(segments=2))
        holed = _shape([self.square(10), shapes.Spline(_knots([(2, 2, 0), (2, 4, 0), (4, 4, 0), (4, 2, 0)]),
                                                       True)])
        with patching.patch_all(extrude, "MAX_CAP_POINTS", 6):
            data, issues = extrude.extrude(holed, self.params())
        self.assertEqual(len(issues), 1)
        self.assertEqual(set(_mats(data).tolist()), {extrude.SIDE_ID})  # the cap is left open
        with patching.patch_all(extrude, "MAX_LOOPS", 1):
            _data, issues = extrude.extrude(holed, self.params())
        self.assertEqual(len(issues), 1)

    def test_a_hostile_loop_set_is_refused_by_the_nesting_budget(self):
        """Concentric outlines make every pair a candidate: the point-edge tests are counted, not the loops."""
        rings = [shapes.Spline(_knots([(r * math.cos(2 * math.pi * k / 64), r * math.sin(2 * math.pi * k / 64), 0)
                                       for k in range(64)]), True) for r in range(1, 31)]
        data, issues = extrude.extrude(_shape(rings), self.params())
        self.assertEqual(issues, [])
        self.assertIn(extrude.TOP_ID, set(_mats(data).tolist()))
        tested = []
        real = extrude._inside

        def inside(p, poly):
            tested.append(len(poly))
            return real(p, poly)

        with patching.patch_all(extrude, "MAX_NEST_TESTS", 1000), patching.patch_all(extrude, "_inside", inside):
            data, issues = extrude.extrude(_shape(rings), self.params())
        self.assertLessEqual(sum(tested), 1000)
        self.assertEqual(issues, ["30 closed splines take more than 1000 tests to nest: no caps"])
        self.assertEqual(set(_mats(data).tolist()), {extrude.SIDE_ID})

    def test_the_holed_caps_of_one_mesh_share_a_step_budget(self):
        """Two solids with a hole each: a budget that one cap fits in leaves the second open."""
        pts = [(0, 0), (10, 0), (10, 10), (0, 10), (2, 2), (2, 4), (4, 4), (4, 2)]
        budget = [10 ** 9]
        extrude.triangulate(pts, [0, 1, 2, 3], [[4, 5, 6, 7]], budget)
        one = 10 ** 9 - budget[0]
        two = _shape([self.square(10), self.rect(2, 2, 4, 4), self.rect(20, 0, 30, 10), self.rect(22, 2, 24, 4)])
        with patching.patch_all(extrude, "MAX_CLIP_STEPS", one + one // 2):
            data, issues = extrude.extrude(two, self.params())
        self.assertEqual(issues, ["a cap with holes is left open: more than %d steps to triangulate the caps" %
                                  (one + one // 2)])
        self.assertEqual(int((_mats(data) == extrude.TOP_ID).sum()), 8)  # one holed cap: 8 + 2 - 2 triangles

    def test_the_holed_caps_after_a_spent_budget_share_one_issue(self):
        """Once the budget is spent the rest are not tried: one issue counts them, not one each."""
        pts = [(0, 0), (10, 0), (10, 10), (0, 10), (2, 2), (2, 4), (4, 4), (4, 2)]
        budget = [10 ** 9]
        extrude.triangulate(pts, [0, 1, 2, 3], [[4, 5, 6, 7]], budget)
        one = 10 ** 9 - budget[0]
        rings = [self.square(10), self.rect(2, 2, 4, 4)]
        for x in (20, 40, 60):
            rings += [self.rect(x, 0, x + 10, 10), self.rect(x + 2, 2, x + 4, 4)]
        with patching.patch_all(extrude, "MAX_CLIP_STEPS", one + one // 2), \
                patching.patch_all(extrude, "triangulate", wraps=extrude.triangulate) as tried:
            data, issues = extrude.extrude(_shape(rings), self.params())
        self.assertEqual(tried.call_count, 2)
        self.assertEqual(issues, ["a cap with holes is left open: more than %d steps to triangulate the caps" %
                                  (one + one // 2), "2 more caps with holes left open: no steps left"])
        self.assertEqual(int((_mats(data) == extrude.TOP_ID).sum()), 8)

    def test_too_many_points_are_refused_before_any_is_made(self):
        knots = _knots([(k, k % 3, 0) for k in range(3000)], kind=shapes.CORNER)
        many = shapes.Shape(shapes.classids.LINE, (shapes.Spline(knots, False),), 100, False, False,
                            shapes.DEFAULT_RENDER, ())
        with patching.patch_all(extrude, "_polyline", side_effect=AssertionError("interpolated")):
            with self.assertRaises(extrude.ExtrudeError):
                extrude.extrude(many, self.params(segments=10))

    def test_an_amount_past_single_precision_is_refused(self):
        with self.assertRaises(extrude.ExtrudeError):
            extrude.extrude(_shape([self.square(4)]), self.params(amount=1e300))

    def test_a_zero_area_outline_gets_sides_and_a_flat_cap(self):
        flat = shapes.Spline(_knots([(0, 0, 0), (4, 0, 0), (8, 0, 0)]), True)
        data, _issues = extrude.extrude(_shape([flat]), self.params())
        self.assertEqual(len(data.positions), 6)
        self.assertEqual(int((data.loop_totals == 4).sum()), 3)

    def test_a_self_touching_outline_ends(self):
        bow = shapes.Spline(_knots([(0, 0, 0), (10, 10, 0), (10, 0, 0), (0, 10, 0)]), True)
        data, _issues = extrude.extrude(_shape([bow]), self.params())
        self.assertEqual(len(data.positions), 8)
        self.assertTrue(numpy.isfinite(data.positions).all())

    def test_a_hole_left_open_keeps_its_sides_facing_out(self):
        """An outline inside two overlapping holes is a hole without a solid: no cap, but its sides still face
        out of the material, into it (clockwise, like any hole)."""
        data, _issues = extrude.extrude(_shape([self.square(10), self.rect(1, 1, 6, 6), self.rect(4, 4, 9, 9),
                                                self.rect(4.5, 4.5, 5.5, 5.5)]), self.params(cap_start=False,
                                                                                           cap_end=False))
        last = data.loop_vertices[-16:].reshape(4, 4)  # the island's four side quads
        p = data.positions.astype(numpy.float64)
        for quad in last:
            a, b = p[quad[0]], p[quad[1]]
            mid = (a + b) / 2.0
            normal = numpy.array([b[1] - a[1], a[0] - b[0]])  # the right of a -> b: where the face looks
            self.assertLess(numpy.dot(normal, mid[:2] - (5.0, 5.0)), 0)  # towards the center of the small square


if __name__ == "__main__":
    unittest.main()
