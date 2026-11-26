# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/extrude/ on caps: grid caps and self-crossing outlines, no Blender.

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
    _edges, _face_area_z, _knots, _mats, _points, _shape, _volume, extrude, numpy, patching, shapes,
)


def _f32(v):
    """v as a MAXScript float (single precision): its point arithmetic rounds each result so."""
    return float(numpy.float32(v))


def _sub32(a, b):
    return float(numpy.float32(a) - numpy.float32(b))


def _add32(a, b):
    return float(numpy.float32(a) + numpy.float32(b))


def _poly(points):
    return shapes.Spline(_knots([(_f32(x), _f32(y), _f32(z)) for x, y, z in points]), True)


def _rect(w, h, cx=0.0, cy=0.0):
    """A Rectangle w across and h up about (cx, cy), its knots as 3ds Max lays them."""
    x, y = _f32(w) / 2, _f32(h) / 2
    return _poly([(cx + x, cy + y, 0), (cx - x, cy + y, 0), (cx - x, cy - y, 0), (cx + x, cy - y, 0)])


def _box(x0, y0, x1, y1):
    return _poly([(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)])


def _hole(cx, cy, hw, hh):
    """The probes' square holes: drawn clockwise, each corner a MAXScript sum (cx - hw ...)."""
    hw, hh = _f32(hw), _f32(hh)
    x0, x1, y0, y1 = _sub32(cx, hw), _add32(cx, hw), _sub32(cy, hh), _add32(cy, hh)
    return _poly([(x0, y0, 0), (x0, y1, 0), (x1, y1, 0), (x1, y0, 0)])


def _circle_at(radius, cx=0.0, cy=0.0):
    knots = []
    for k in shapes._circle(4, radius):
        knots.append(k._replace(**{f: (getattr(k, f)[0] + cx, getattr(k, f)[1] + cy, getattr(k, f)[2])
                                   for f in ("point", "in_vec", "out_vec")}))
    return shapes.Spline(tuple(knots), True)


def _turned_circle(radius, cx=0.0, cy=0.0):
    """A circle whose knots lie on the diagonals (the probes' Circle45), the usual 4 / 3 (sqrt 2 - 1) vectors."""
    k = 4 * (math.sqrt(2) - 1) / 3 * radius
    knots = []
    for a in (45, 135, 225, 315):
        r = math.radians(a)
        p = (cx + radius * math.cos(r), cy + radius * math.sin(r), 0.0)
        t = (-math.sin(r) * k, math.cos(r) * k, 0.0)
        knots.append(shapes.Knot(shapes.BEZIER, shapes.CURVE, p, tuple(a - b for a, b in zip(p, t)),
                                 tuple(a + b for a, b in zip(p, t))))
    return shapes.Spline(tuple(knots), True)


def _square40(*holes):
    return [_box(-20, -20, 20, 20)] + list(holes)


# Grid caps probed in 3ds Max 2020 (snapshotAsMesh of each shape under an Extrude with Cap Type Grid, Cap Start and
# Cap End, 1 segment unless named): name -> (splines, shape steps, extra parameters, vertices, faces). Hole_s: a
# square hole s wide at (3.3, 3.3) in a 40-wide square, the grid refined by it (s = 2 and 1.9: 37 and 39 divisions).
GRID_PROBES = {
    "Rect30x20": (lambda: [_rect(30, 20)], 6, {}, 890, 1776),
    "Rect300x200": (lambda: [_rect(300, 200)], 6, {}, 890, 1776),
    "Rect3x2": (lambda: [_rect(3, 2)], 6, {}, 890, 1776),
    "Circle10": (lambda: [_circle_at(10)], 2, {}, 690, 1376),
    "Circle45": (lambda: [_turned_circle(10)], 2, {}, 738, 1472),
    "Thin100x1": (lambda: [_rect(100, 1)], 6, {}, 890, 1776),
    "CircleSteps20": (lambda: [_circle_at(10)], 20, {}, 866, 1728),
    "TwoSquares": (lambda: [_rect(10, 10), _rect(4, 4, 30, 0)], 6, {}, 1780, 3552),
    "HoleRect": (lambda: [_rect(40, 40), _circle_at(8, 4, 2)], 6, {}, 836, 1672),
    "Island": (lambda: [_rect(40, 40), _rect(24, 24), _rect(10, 10)], 6, {}, 1450, 2896),
    "Triangle": (lambda: [_poly([(0, 0, 0), (20, 0, 0), (5, 15, 0)])], 6, {}, 442, 880),
    "LShape": (lambda: [_poly([(0, 0, 0), (20, 0, 0), (20, 8, 0), (8, 8, 0), (8, 25, 0), (0, 25, 0)])], 6,
               {"amount": -15.0, "segments": 3}, 542, 1080),
    "Clockwise": (lambda: [_poly([(0, 0, 0), (0, 20, 0), (30, 20, 0), (30, 0, 0)])], 6, {}, 890, 1776),
    "Diamond": (lambda: [_poly([(10, 0, 0), (0, 10, 0), (-10, 0, 0), (0, -10, 0)])], 6, {}, 442, 880),
    "RectAndOpen": (lambda: [_rect(10, 10), shapes.Spline(_knots([(20, 0, 0), (40, 10, 0)]), False)], 6, {},
                    894, 1778),
    "TinyHole": (lambda: _square40(_poly([(0.5, 0.5, 0), (0.5, 1.2, 0), (1.2, 1.2, 0), (1.2, 0.5, 0)])), 6, {},
                 5216, 10432),
    "CapStartOnly": (lambda: [_rect(30, 20)], 6, {"cap_end": False}, 449, 892),
    "CapEndOnly": (lambda: [_rect(30, 20)], 6, {"cap_start": False, "segments": 2}, 453, 900),
    "Pinch": (lambda: [_poly([(0, 0, 0), (10, 0, 0), (10, 10, 0), (20, 10, 0), (20, 20, 0), (10, 20, 0),
                              (10, 10.0001, 0), (0, 10.0001, 0)])], 6, {}, 458, 912),
    "Sliver": (lambda: [_poly([(0, 0, 0), (40, 0, 0), (40, 0.5, 0), (0, 30, 0)])], 6, {}, 466, 928),
    "Overlap": (lambda: [_box(0, 0, 20, 20), _box(10, 10, 30, 30)], 6, {}, 1780, 3552),
    "HoleWide": (lambda: _square40(_hole(3.3, 3.3, 5, 0.35)), 6, {}, 2148, 4296),
    "HoleTall": (lambda: _square40(_hole(3.3, 3.3, 0.35, 5)), 6, {}, 2148, 4296),
    "Big400Hole7": (lambda: [_box(-200, -200, 200, 200), _hole(33, 33, 3.5, 3.5)], 6, {}, 5216, 10432),
    "SmallSolidBeside": (lambda: _square40(_box(30, 0, 30.7, 0.7)), 6, {}, 1780, 3552),
    "HoleCircle45": (lambda: _square40(_turned_circle(1.0, 3.3, 3.3)), 2, {}, 3226, 6452),
    "TwoHoles": (lambda: _square40(_poly([(-11.5, -11.5, 0), (-11.5, -8.5, 0), (-8.5, -8.5, 0), (-8.5, -11.5, 0)]),
                                   _poly([(9.1, 9.1, 0), (9.1, 10.9, 0), (10.9, 10.9, 0), (10.9, 9.1, 0)])), 6, {},
                 3696, 7396),
    "Notch": (lambda: [_poly([(-20, -20, 0), (20, -20, 0), (20, 20, 0), (1.0, 20, 0), (0.8, 0.6, 0), (0.6, 20, 0),
                              (-20, 20, 0)])], 6, {}, 896, 1788),
    "IslandInHole": (lambda: _square40(_box(-10, -10, 10, 10), _box(2.8, 2.8, 3.8, 3.8)), 6, {}, 1546, 3088),
    "RaisedZ3": (lambda: [_poly([(0, 0, 3), (30, 0, 3), (30, 20, 3), (0, 20, 3)])], 6, {}, 890, 1776),
    "Wide60x20Hole3": (lambda: [_box(0, 0, 60, 20), _hole(20.3, 7.3, 1.5, 1.5)], 6, {}, 1642, 3284),
    "Tall20x60Hole3": (lambda: [_box(0, 0, 20, 60), _hole(7.3, 20.3, 1.5, 1.5)], 6, {}, 1642, 3284),
    "Wide60x20Hole1x5": (lambda: [_box(0, 0, 60, 20), _hole(20.3, 7.3, 0.5, 2.5)], 6, {}, 2158, 4316),
    "Straddle": (lambda: _square40(_hole(3.05, 3.45, 0.15, 0.15)), 6, {}, 5218, 10436),
    "ThinDiagonal": (lambda: [_poly([(0, 0, 0), (1, 0, 0), (41, 40, 0), (40, 40, 0)])], 6, {}, 8, 12),
    # groups of filled cells that touch only at corners (band holes sharing a grid point)
    "Corners": (lambda: [_poly([(22, 30, 0), (20, 15, 0), (23, 12, 0), (26, 2, 0)])], 6, {}, 254, 504),
}
for _s, _v, _f in ((20.0, 698, 1396), (12.0, 826, 1652), (8.0, 866, 1732), (5.0, 880, 1760), (4.0, 890, 1780),
                   (3.0, 1360, 2720), (2.5, 1930, 3860), (2.375, 2056, 4112), (2.0, 2896, 5792), (1.9, 3208, 6416),
                   (1.8, 3706, 7412), (1.5, 5210, 10420), (1.2, 5210, 10420), (1.0, 5216, 10432),
                   (0.8, 5216, 10432), (0.7, 5216, 10432), (0.5, 5218, 10436), (0.3, 5218, 10436)):
    GRID_PROBES["Hole_%g" % _s] = ((lambda s=_s: _square40(_hole(3.3, 3.3, _f32(s) / 2, _f32(s) / 2))), 6, {}, _v,
                                   _f)


@unittest.skipIf(numpy is None, "numpy missing")
class GridCaps(unittest.TestCase):
    """Cap Type Grid: 3ds Max 2020's vertex and face counts of the probed shapes, closed meshes that enclose what
    the morph caps enclose, the grid's divisions, its points' height and mapping, and the guards."""

    def make(self, name, **kw):
        splines, steps, extra, _v, _f = GRID_PROBES[name]
        params = extrude.DEFAULT._replace(**dict(dict(amount=2.0, cap_type=extrude.CAP_GRID), **dict(extra, **kw)))
        return extrude.extrude(_shape(splines(), steps=steps), params)

    def test_counts_equal_3ds_max(self):
        for name, (_splines, _steps, _extra, verts, faces) in GRID_PROBES.items():
            data, issues = self.make(name)
            self.assertEqual(issues, [], name)
            self.assertEqual((len(data.positions), int((data.loop_totals - 2).sum())), (verts, faces), name)

    def test_caps_are_closed_and_enclose_the_morph_caps_volume(self):
        for name in GRID_PROBES:
            data, _issues = self.make(name)
            morph, _issues = self.make(name, cap_type=extrude.CAP_MORPH)
            want = _volume(morph.positions, morph)
            self.assertAlmostEqual(_volume(data.positions, data), want, delta=1e-4 * max(1.0, abs(want)), msg=name)
            if name in ("RectAndOpen", "Overlap", "CapStartOnly", "CapEndOnly", "RaisedZ3"):
                continue  # an open side, overlapping solids, one cap, the grid off the outline's height
            edges = _edges(data)
            self.assertTrue(all(c == 1 for c in edges.values()), name)
            self.assertTrue(all((b, a) in edges for a, b in edges), name)

    def test_divisions(self):
        """20, raised by a hole to floor(0.95 x span / (s / 2)), at most 50: on the float32 values of the points, so
        exact ratios fall either way (2.3f .. 4.3f in 40: 37.99999 -> 37; 18.8f .. 21.8f in 60: 38 -> 38)."""
        div = extrude._divisions
        self.assertEqual([div(40.0, []), div(40.0, [5.0]), div(40.0, [3.0]), div(40.0, [1.8]), div(40.0, [0.1])],
                         [20, 20, 25, 42, 50])
        self.assertEqual(div(40.0, [3.0, 1.8]), 42)
        self.assertEqual(div(40.0, [_add32(3.3, 1.0) - _sub32(3.3, 1.0)]), 37)
        self.assertEqual(div(60.0, [_add32(20.3, 1.5) - _sub32(20.3, 1.5)]), 38)
        self.assertEqual(div(40.0, [0.0, float("nan")]), 20)
        self.assertEqual(div(1e30, [1e-30]), 50)

    def test_grid_points(self):
        """21 x 21 points from 2.5 % of the box plus a thousandth of a division, at z 0 and the amount whatever the
        shape's z (3ds Max's RaisedZ3: its outline at 3 and 5, its grid at 0 and 2); the cap maps them like its
        other points (3ds Max: u 0.02505 at the first grid point of a 30-wide box)."""
        data, _issues = self.make("RaisedZ3")
        grid = data.positions[8:].astype(numpy.float64)
        self.assertEqual(sorted(set(grid[:, 2].tolist())), [0.0, 2.0])
        self.assertAlmostEqual(float(grid[:, 0].min()), 0.751425, places=5)
        self.assertAlmostEqual(float(grid[:, 1].max()), 19.50095, places=5)
        data, _issues = self.make("Rect30x20", mapping=True)
        ch = data.maps[1]
        uvw = numpy.asarray(ch.uvw, dtype=numpy.float64)
        us = sorted(set(numpy.round(uvw[numpy.unique(ch.indices)][:, 0], 5).tolist()))
        self.assertIn(0.02505, us)
        self.assertEqual((us[0], us[-1]), (0.0, 1.0))

    def test_without_a_whole_cell_the_cap_is_a_morph_cap(self):
        data, _issues = self.make("ThinDiagonal")
        self.assertEqual(sorted(data.loop_totals.tolist()), [4, 4, 4, 4, 4, 4])  # two n-gons, four sides

    def test_a_grid_cap_past_a_guard_is_a_morph_cap(self):
        morph, _issues = self.make("Rect30x20", cap_type=extrude.CAP_MORPH)
        for patch, value, reason in (("MAX_GRID_TESTS", 10, "more than 10 tests"),
                                     ("MAX_VERTICES", 200, "past 200 vertices"),
                                     ("MAX_CAP_POINTS", 3, "more than 3 outline points")):
            with patching.patch_all(extrude, patch, value):
                data, issues = self.make("Rect30x20")
            self.assertEqual(len(data.positions), len(morph.positions), patch)
            self.assertEqual(len(issues), 1, patch)
            self.assertIn("1 grid cap made as morph cap: " + reason, issues[0], patch)
        with patching.patch_all(extrude, "MAX_GRID_TESTS", 10):
            data, issues = self.make("TwoSquares")
        self.assertEqual(issues, ["2 grid caps made as morph caps: more than 10 tests to lay out the grids"])

    def test_only_cap_type_1_is_grid(self):
        for cap_type in (0, 2, -1):
            data, _issues = self.make("Rect30x20", cap_type=cap_type)
            self.assertEqual(len(data.positions), 8, cap_type)

    def test_cells_touching_only_at_a_corner(self):
        """Two cells that share one corner: two band loops through it, each round its own cell, which the band
        takes as one hole joined there."""
        filled = numpy.array([[True, False], [False, True]])
        index = numpy.arange(9).reshape(3, 3)
        loops = extrude._cell_loops(filled, index)
        self.assertEqual(sorted(sorted(lp) for lp in loops), [[0, 1, 3, 4], [4, 5, 7, 8]])
        joined = extrude._splice(loops)
        self.assertEqual(len(joined), 1)
        self.assertEqual(sorted(joined[0]), [0, 1, 3, 4, 4, 5, 7, 8])
        self.assertEqual(extrude._splice([[1, 2, 3], [7, 8, 9]]), [[1, 2, 3], [7, 8, 9]])

    def faces_face_their_ids(self, data, name):
        """Every cap face faces the way its material ID says, but for slivers (Triangle's grid points that float32
        puts in a row: 1.4e-6 the wrong way; Pinch's own 0.0001 gap)."""
        for f in range(len(data.loop_starts)):
            mat = int(_mats(data)[f])
            if mat == extrude.SIDE_ID:
                continue
            z = _face_area_z(data, f) * (1 if mat == extrude.TOP_ID else -1)
            self.assertGreater(z, -1e-5, "%s face %d: %g" % (name, f, z))

    def test_every_cap_face_faces_its_way(self):
        for name in GRID_PROBES:
            data, _issues = self.make(name)
            self.faces_face_their_ids(data, name)

    def test_groups_of_cells_touching_at_a_corner_give_a_clean_cap(self):
        """A four-point outline whose filled cells fall into groups that touch only at corners: their band
        loops share grid points; the cap still tiles its area, no face turned or doubled."""
        shape = _shape([_poly([(22, 30, 0), (20, 15, 0), (23, 12, 0), (26, 2, 0)])])
        params = extrude.DEFAULT._replace(amount=2.0, cap_type=extrude.CAP_GRID)
        data, issues = extrude.extrude(shape, params)
        self.assertEqual(issues, [])
        self.assertGreater(len(data.positions), 8)
        self.faces_face_their_ids(data, "corners")
        edges = _edges(data)
        self.assertTrue(all(c == 1 for c in edges.values()))
        self.assertTrue(all((b, a) in edges for a, b in edges))
        morph, _issues = extrude.extrude(shape, params._replace(cap_type=extrude.CAP_MORPH))
        self.assertAlmostEqual(_volume(data.positions, data), _volume(morph.positions, morph), places=4)

    def test_a_band_that_does_not_tile_its_area_is_a_morph_cap(self):
        real = extrude.triangulate

        def folded(xy, outer, holes=(), budget=None):
            tris = real(xy, outer, holes, budget)
            return tris[:-1] + [tris[-1][::-1]]

        with patching.patch_all(extrude, "triangulate", folded):
            data, issues = self.make("Rect30x20")
        self.assertEqual(len(data.positions), 8)
        self.assertEqual(issues, ["1 grid cap made as morph cap: its band does not triangulate"])

    def test_a_refused_grid_on_a_holed_cap_left_open_is_named_once(self):
        with patching.patch_all(extrude, "MAX_CAP_POINTS", 5):
            _data, issues = self.make("HoleRect")
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("left open", issues[0])


def _bezier_spline(knots):
    """A closed spline of Bezier-corner knots, each (point, in vector, out vector) in XY."""
    return shapes.Spline(tuple(shapes.Knot(shapes.BEZIER_CORNER, shapes.CURVE, (_f32(p[0]), _f32(p[1]), 0.0),
                                           (_f32(i[0]), _f32(i[1]), 0.0), (_f32(o[0]), _f32(o[1]), 0.0))
                               for p, i, o in knots), True)


def _bowtie(x=0.0):
    return _poly([(x, 0, 0), (x + 10, 10, 0), (x + 10, 0, 0), (x, 10, 0)])


_SLIT = [(0, 0, 0), (20, 0, 0), (20, 10, 0), (4, 10, 0), (10, 6, 0), (14, 10, 0), (0, 10, 0)]

# Closed splines that cross, touch or run over themselves, probed in 3ds Max 2020 (snapshotAsMesh under an Extrude:
# amount 2, 1 segment, both caps, steps 6): name -> (splines, (vertices, faces) with morph caps, the same with grid
# caps or None where only morph was probed, the splines left uncapped as crossing).
CROSS_PROBES = {
    # crossing edges
    "Bowtie": (lambda: [_bowtie()], (8, 8), (8, 8), 1),
    "BowtieCW": (lambda: [_poly([(0, 10, 0), (10, 0, 0), (10, 10, 0), (0, 0, 0)])], (8, 8), (8, 8), 1),
    "Pentagram": (lambda: [_poly([(0, 10, 0), (5.878, -8.09, 0), (-9.511, 3.09, 0), (9.511, 3.09, 0),
                                  (-5.878, -8.09, 0)])], (10, 10), (10, 10), 1),
    # two edges run over each other along the top; an edge back over the one before; the base past a knot and back
    "Slit": (lambda: [_poly(_SLIT)], (14, 14), (14, 14), 1),
    "SpikeBack": (lambda: [_poly([(0, 0, 0), (20, 0, 0), (20, 10, 0), (10, 10, 0), (10, 15, 0), (10, 10, 0),
                                  (0, 10, 0)])], (14, 14), (14, 14), 1),
    "BaseBack": (lambda: [_poly([(0, 0, 0), (20, 0, 0), (15, 0, 0), (15, 10, 0), (0, 10, 0)])], (10, 10), (10, 10),
                 1),
    # touching: a knot on another knot, on another edge, 1e-6 across it
    "PinchExact": (lambda: [_poly([(0, 0, 0), (10, 0, 0), (10, 10, 0), (20, 10, 0), (20, 20, 0), (10, 20, 0),
                                   (10, 10, 0), (0, 10, 0)])], (16, 16), (16, 16), 1),
    "TouchEdge": (lambda: [_poly([(0, 0, 0), (20, 0, 0), (20, 10, 0), (10, 0, 0), (0, 10, 0)])], (10, 10), (10, 10),
                  1),
    "TouchAcross": (lambda: [_poly([(0, 0, 0), (20, 0, 0), (20, 10, 0), (10, -1e-6, 0), (0, 10, 0)])], (10, 10), None,
                    1),
    # in XY only: the crossing edges at other heights
    "Bowtie3D": (lambda: [_poly([(0, 0, 0), (10, 10, 0), (10, 0, 5), (0, 10, 5)])], (8, 8), None, 1),
    "TouchEdge3D": (lambda: [_poly([(0, 0, 0), (20, 0, 0), (20, 10, 0), (10, 0, 3), (0, 10, 0)])], (10, 10), None, 1),
    # a Bezier rectangle whose third knot moved without its vectors: its curves cross
    "BezierMoved": (lambda: [_bezier_spline([((0, 0), (0, 3.333), (6.667, 0)), ((20, 0), (13.333, 0), (20, 3.333)),
                                             ((-5, 15), (20, 6.667), (13.333, 10)),
                                             ((0, 10), (6.667, 10), (0, 6.667))])], (32, 32), (32, 32), 1),
    # the other splines keep their caps; a crossing spline is no hole and no container
    "BowtieAndSquare": (lambda: [_bowtie(), _box(20, 0, 30, 10)], (16, 20), (898, 1784), 1),
    "SquareBowtieHole": (lambda: [_box(-20, -20, 20, 20), _bowtie()], (16, 20), (898, 1784), 1),
    "HoledAndBowtie": (lambda: [_box(-20, -20, 20, 20), _box(-5, -5, 5, 5), _bowtie(40)], (24, 40), (856, 1704), 1),
    "BowtieAroundSquare": (lambda: [_poly([(0, 0, 0), (40, 40, 0), (40, 0, 0), (0, 40, 0)]), _box(30, 15, 35, 25)],
                           (16, 20), (898, 1784), 1),
    # capped: near misses, adjacent edges only, crossings between splines, open splines
    "NearMiss": (lambda: [_poly([(0, 0, 0), (20, 0, 0), (20, 10, 0), (10, 0.01, 0), (0, 10, 0)])], (10, 16),
                 (442, 880), 0),
    "TouchGap1e-6": (lambda: [_poly([(0, 0, 0), (20, 0, 0), (20, 10, 0), (10, 1e-6, 0), (0, 10, 0)])], (10, 16), None,
                     0),
    "PinchGap1e-6": (lambda: [_poly([(0, 0, 0), (10, 0, 0), (10, 10, 0), (20, 10, 0), (20, 20, 0), (10, 20, 0),
                                     (10, 10.000001, 0), (0, 10, 0)])], (16, 28), None, 0),
    "TouchGapBig": (lambda: [_poly([(0, 0, 0), (20000, 0, 0), (20000, 10000, 0), (10000, 1e-3, 0),
                                    (0, 10000, 0)])], (10, 16), None, 0),
    "Collinear": (lambda: [_poly([(0, 0, 0), (10, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0)])], (10, 16), None, 0),
    "Flat3": (lambda: [_poly([(0, 0, 0), (4, 0, 0), (8, 0, 0)])], (6, 8), None, 0),
    "TwoCrossing": (lambda: [_box(0, 0, 20, 20), _box(10, 10, 30, 30)], (16, 24), (1780, 3552), 0),
    "OpenAcross": (lambda: [_box(0, 0, 20, 20), shapes.Spline(_knots([(-5, 10, 0), (25, 10, 0)]), False)], (12, 14),
                   (894, 1778), 0),
    "OpenSelfCross": (lambda: [_box(0, 0, 20, 20), shapes.Spline(_knots([(30, 0, 0), (40, 10, 0), (40, 0, 0),
                                                                          (30, 10, 0)]), False)], (16, 18),
                      (898, 1782), 0),
    "BezierBulge": (lambda: [_bezier_spline([((0, 0), (-3, 3), (3, -3)), ((20, 0), (17, -3), (23, 3)),
                                             ((20, 20), (23, 17), (17, 23)), ((0, 20), (3, 23), (-3, 17))])],
                    (56, 108), (842, 1680), 0),
}


class _RectParams:
    """The parameter block of a Rectangle for reader.shapes._rectangle: length, width, corner radius."""

    def __init__(self, *values):
        self.values = values

    def number(self, i, default=0.0):
        return self.values[i]


def _pill(length, width, radius):
    return shapes._rectangle(_RectParams(length, width, radius), [])[0]


@unittest.skipIf(numpy is None, "numpy missing")
class SelfCrossing(unittest.TestCase):
    """A closed spline whose own edges cross, touch or run over each other: no cap, morph or grid, as in 3ds Max
    2020; no hole or container for the others; its own direction (maxdrop-em3.140)."""

    def make(self, splines, steps=6, optimize=True, **kw):
        params = extrude.DEFAULT._replace(**dict(dict(amount=2.0), **kw))
        return extrude.extrude(_shape(splines, steps=steps, optimize=optimize), params)

    def test_counts_equal_3ds_max(self):
        for name, (splines, morph, grid, crossed) in CROSS_PROBES.items():
            for cap_type, want in ((extrude.CAP_MORPH, morph), (extrude.CAP_GRID, grid)):
                if want is None:
                    continue
                data, issues = self.make(splines(), cap_type=cap_type)
                self.assertEqual((len(data.positions), int((data.loop_totals - 2).sum())), want, (name, cap_type))
                crossing = [i for i in issues if "cross" in i]
                self.assertEqual(len(crossing), 1 if crossed else 0, (name, issues))
                if crossed:
                    self.assertTrue(crossing[0].startswith("%d closed spline" % crossed), crossing)

    def test_the_report_line(self):
        _data, issues = self.make([_bowtie()])
        self.assertEqual(issues, ["1 closed spline that crosses or touches itself: no cap, as in 3ds Max"])
        _data, issues = self.make([_bowtie(), _bowtie(20), _box(40, 0, 50, 10)])
        self.assertEqual(issues, ["2 closed splines that cross or touch themselves: no cap, as in 3ds Max"])
        _data, issues = self.make([_bowtie()], cap_start=False, cap_end=False)
        self.assertEqual(issues, [])

    def test_a_crossing_spline_keeps_its_own_direction(self):
        """3ds Max's SlitCW (the slit drawn the other way round, clockwise): its sides start at its first knot and
        run its own way, each looking to the right of it, U from 0 there (14 / 82.868 at the second knot)."""
        data, _issues = self.make([_poly(_SLIT[::-1])], mapping=True)
        p = data.positions.astype(numpy.float64)
        first = data.loop_vertices[:4].tolist()
        numpy.testing.assert_allclose(p[first], [(0, 10, 0), (14, 10, 0), (14, 10, 2), (0, 10, 2)], atol=1e-6)
        uv = data.maps[1].uvw[data.maps[1].indices[:4]].astype(numpy.float64)
        numpy.testing.assert_allclose(uv[:, :2], [(0, 0), (0.168943, 0), (0.168943, 1), (0, 1)], atol=1e-6)
        for cw, amount in ((False, 2.0), (True, 2.0), (False, -2.0), (True, -2.0)):
            pts = _SLIT[::-1] if cw else _SLIT
            data, _issues = self.make([_poly(pts)], amount=amount)
            q = data.positions.astype(numpy.float64)[data.loop_vertices[:4]]
            self.assertEqual(tuple(q[0][:2]), pts[0][:2], (cw, amount))  # never turned: its first knot first
            normal = numpy.cross(q, numpy.roll(q, -1, axis=0)).sum(axis=0)
            (x0, y0, _z0), (x1, y1, _z1) = pts[0], pts[1]
            right = numpy.array([y1 - y0, x0 - x1, 0.0])
            self.assertGreater(numpy.dot(normal, right), 0, (cw, amount))  # out of the side it runs along

    def test_the_cap_mapping_box_leaves_a_crossing_spline_out(self):
        """BowtieAroundSquare: the square alone is capped, mapped over its own box (3ds Max: every corner)."""
        data, _issues = self.make([_poly([(0, 0, 0), (40, 40, 0), (40, 0, 0), (0, 40, 0)]), _box(30, 15, 35, 25)],
                                  mapping=True)
        caps = [f for f in range(len(data.loop_starts)) if abs(_face_area_z(data, f)) > 1e-6]
        self.assertEqual(len(caps), 2)
        ch = data.maps[1]
        for f in caps:
            s, t = int(data.loop_starts[f]), int(data.loop_totals[f])
            xy = data.positions[data.loop_vertices[s:s + t], :2].astype(numpy.float64)
            uv = ch.uvw[ch.indices[s:s + t], :2].astype(numpy.float64)
            numpy.testing.assert_allclose(uv, (xy - (30, 15)) / (5, 10), atol=1e-6)

    def test_zero_length_segments_between_straight_edges(self):
        """Two knots on one spot one after the other between straight edges: no cap in 3ds Max at any coordinates
        (it keeps both points: 10 vertices where MaxDrop merges them into 8); a rounded Rectangle whose corner
        radius is half its side, at steps 0, too. Between interpolated curves 3ds Max's rounding decides (the
        10 x 20 r 5 pill at steps 6 capped): MaxDrop caps it."""
        cases = {
            "DupCorner": ([_poly([(0, 0, 0), (20, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0)])], 6, 4),
            "DupCornerOdd": ([_poly([(0.123, 4.56, 0), (27.523, 4.56, 0), (27.523, 4.56, 0), (27.523, 18.26, 0),
                                     (0.123, 18.26, 0)])], 6, 4),
            # 3ds Max's DupFirst and DupSecondLast: the same corner doubled wherever the spline starts
            "DupFirst": ([_poly([(20, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0), (0, 0, 0)])], 6, 4),
            "DupSecondLast": ([_poly([(0, 10, 0), (0, 0, 0), (20, 0, 0), (20, 0, 0), (20, 10, 0)])], 6, 4),
            "TripleFirst": ([_poly([(20, 0, 0), (20, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0), (0, 0, 0)])], 6, 4),
            "DupMid": ([_poly([(0, 0, 0), (10, 0, 0), (10, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0)])], 6, 5),
            "CloseDup": ([_poly([(0, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0), (0, 0, 0)])], 6, 4),
            "DupTriangle": ([_poly([(0, 0, 0), (20, 0, 0), (20, 0, 0), (10, 15, 0)])], 6, 3),
            "PillSteps0": ([_pill(10, 20, 5)], 0, 6),
            "FullSteps0": ([_pill(20, 20, 10)], 0, 4),
        }
        for name, (splines, steps, points) in cases.items():
            data, issues = self.make(splines, steps=steps)
            self.assertEqual(len(data.positions), 2 * points, name)
            self.assertTrue((data.loop_totals == 4).all(), name)  # the sides alone
            self.assertEqual(issues, ["1 closed spline that crosses or touches itself: no cap, as in 3ds Max"], name)
        data, issues = self.make([_pill(10, 20, 5)])
        self.assertEqual(issues, [])
        self.assertEqual(len(data.positions), 60)  # 3ds Max: 64, both copies of the two doubled knots
        self.assertEqual(int((data.loop_totals - 2).sum()), 60 + 2 * 28)

    def test_zero_length_segments_without_optimize(self):
        """maxdrop-6n0.6.9's 3ds Max 2020 probe: a doubled knot between line segments without Optimize, steps 6 and
        0, gets no cap either (DupCorner 70 / 70, DupMid 84 / 84, CloseDup 70 / 70 at steps 6: every point kept).
        MaxDrop merges the zero-length segment's steps, which lie exactly on its point, and finds the touch from the
        straight segments on either side, whatever their steps."""
        cases = {
            "DupCorner": ([(0, 0, 0), (20, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0)], 4),
            "DupMid": ([(0, 0, 0), (10, 0, 0), (10, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0)], 5),
            "CloseDup": ([(0, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0), (0, 0, 0)], 4),
            "CloseDupOff": ([(3.3, -7.77, 0), (23.3, -7.77, 0), (23.3, 2.23, 0), (3.3, 2.23, 0), (3.3, -7.77, 0)], 4),
        }
        for name, (pts, corners) in cases.items():
            for steps in (6, 0):
                shape = _shape([_poly(pts)], steps=steps, optimize=False)
                pl = extrude.polylines(shape)[0]
                self.assertEqual((len(pl.points), pl.doubled), (corners * (steps + 1), True), (name, steps))
                data, issues = self.make([_poly(pts)], steps=steps, optimize=False)
                self.assertTrue((data.loop_totals == 4).all(), (name, steps))  # the sides alone
                self.assertEqual(issues, ["1 closed spline that crosses or touches itself: no cap, as in 3ds Max"],
                                 (name, steps))

    def test_a_straight_edge_into_a_doubled_knot(self):
        """maxdrop-6n0.6.9's later 3ds Max 2020 probes: two or three knots on one spot after a straight edge get no
        cap whatever leaves them (a line into (20, 0) and a curve out: no cap at four scales and offsets, tilted, at
        steps 1, 6 and 10, without Optimize). After a curve's step 3ds Max's rounding decides, a line out or not:
        a curve in and a line out capped at scales 1.37, 3.3 and 1000 and at steps 10, not at scales 1 and 0.1, steps
        1 or without Optimize; the last knot on the first after a curve likewise; curves on both sides capped in the
        two shapes probed, also with three knots. MaxDrop caps those. Curves 1 % of their chord off it count as
        straight (no cap in 3ds Max with and without Optimize). Knots as 3ds Max gave them back: (type, the segment
        leaving it, point, in, out)."""
        bc, c, ln, cv = shapes.BEZIER_CORNER, shapes.CORNER, shapes.LINE, shapes.CURVE
        a = (20.0, 0.0, 0.0)
        top = ((c, ln, (20, 10, 0), (23, 7, 0), (13.3333, 10, 0)), (c, ln, (0, 10, 0), (6.66667, 10, 0), (0, 5, 0)))
        line_in = ((c, ln, (0, 0, 0), (0, 3.33333, 0), (10, 0, 0)),)
        curve_in = ((bc, cv, (0, 0, 0), (0, 0, 0), (6, -4, 0)), (bc, ln, a, (14, -4, 0), a))
        curve_out = ((bc, cv, a, a, (26, 4, 0)),)
        line_out = ((bc, ln, a, a, a), (c, ln, (20, 10, 0), (20, 5, 0), (13.3333, 10, 0)), top[1])
        mix = line_in + ((bc, ln, a, a, a),) + curve_out + top
        rev = curve_in + line_out
        near = ((bc, cv, (0, 0, 0), (0, 0, 0), (6.6667, 0.2, 0)), (bc, ln, a, (13.3333, 0.2, 0), a),
                (bc, cv, a, a, (20.2, 3.3333, 0)), (c, ln, (20, 10, 0), (20.1, 6.66665, 0), (13.3333, 10, 0)), top[1])
        close_mix = ((c, ln, (0, 0, 0), (0, 0, 0), (0, 0, 0)), (c, ln, a, a, a), (c, ln, (20, 10, 0),) + ((20, 10, 0),) * 2,
                     (bc, cv, (0, 10, 0), (0, 10, 0), (-3, 7, 0)), (bc, ln, (0, 0, 0), (-3, 3, 0), (0, 0, 0)))
        cases = [  # (name, knots, steps, Optimize, scale, offset, capped by MaxDrop)
            ("Mix", mix, 6, True, 1, (0, 0), False),
            ("Mix_1.37", mix, 6, True, 1.37, (0.123, 4.56), False),
            ("Mix_1000", mix, 6, True, 1000, (3, 7), False),
            ("Mix_steps1", mix, 1, True, 1, (0, 0), False),
            ("Mix_steps10", mix, 10, True, 1, (0, 0), False),
            ("Mix_noopt", mix, 6, False, 1, (0, 0), False),
            ("Tilt", ((c, ln, (0, -3, 0), (0, -3, 0), (0, -3, 0)),) + mix[1:], 6, True, 1, (0, 0), False),
            ("TripleLines", line_in + ((c, ln, a, a, a),) * 3 + ((c, ln) + ((20, 10, 0),) * 3, top[1]), 6, True, 1,
             (0, 0), False),
            ("TripleCurveOpt", line_in + ((bc, cv, a, a, (21, 3, 0)), (bc, cv, a, (19, -3, 0), a)) + curve_out + top,
             6, True, 1, (0, 0), False),
            ("NearNoOpt", near, 6, False, 1, (0, 0), False),
            ("NearOpt", near, 6, True, 1, (0, 0), False),
            # 3ds Max's rounding decides: a cap in MaxDrop
            ("Rev", rev, 6, True, 1, (0, 0), True),
            ("Rev_1.37", rev, 6, True, 1.37, (0.123, 4.56), True),
            ("CloseMix", close_mix, 6, True, 1, (0, 0), True),
            ("DoubleCurves", curve_in + curve_out + top, 6, True, 1, (0, 0), True),
            ("TripleCurves", curve_in + ((bc, ln, a, a, a),) + curve_out + top, 6, True, 1, (0, 0), True),
        ]
        for name, knots, steps, optimize, f, (ox, oy), capped in cases:
            def put(p):
                return (_f32(p[0] * f + ox), _f32(p[1] * f + oy), 0.0)
            spline = shapes.Spline(tuple(shapes.Knot(k, g, put(p), put(i), put(o)) for k, g, p, i, o in knots), True)
            shape = _shape([spline], steps=steps, optimize=optimize)
            self.assertEqual(extrude.polylines(shape)[0].doubled, not capped, name)
            data, issues = self.make([spline], steps=steps, optimize=optimize)
            self.assertEqual(bool((data.loop_totals != 4).any()), capped, (name, issues))

    def test_optimize_gives_a_segment_back_to_its_knot_no_steps(self):
        """The 10 x 20 r 5 pill: its short sides run from a knot to another on the same spot, curve segments with
        their vectors off it. 3ds Max: no steps under Optimize (32 points with both copies, 30 merged), its steps
        without (56 points, the loops crossing the curves: no cap)."""
        self.assertEqual(_points(_shape([_pill(10, 20, 5)])), 30)
        data, issues = self.make([_pill(10, 20, 5)], optimize=False)
        self.assertEqual(len(data.positions), 112)
        self.assertTrue((data.loop_totals == 4).all())
        self.assertEqual(len(issues), 1, issues)

    def test_short_sides_whose_vectors_run_far_past_them(self):
        """Rounded Rectangles in 3ds Max 2020 (em3.140's probe): a short straight side whose corner vectors run far
        past its ends is curved for Optimize (6 steps folding back over the side: no cap); radius 3, 4, 4.5 keep
        their straight sides and their caps. 12.5 x 13 radius 6.25: 3ds Max 88 / 88, keeping both points of its two
        zero-length sides, which MaxDrop merges."""
        for length, width, radius, want in ((10, 20, 4.8, (88, 88)), (10, 20, 4.9, (88, 88)),
                                            (10, 20, 4.99, (88, 88)), (12.5, 13, 6, (88, 88)),
                                            (12.5, 13, 6.25, (84, 84)), (10, 20, 4.5, (64, 124)),
                                            (10, 20, 4.0, (64, 124)), (10, 20, 3.0, (64, 124))):
            data, issues = self.make([_pill(length, width, radius)])
            got = (len(data.positions), int((data.loop_totals - 2).sum()))
            self.assertEqual(got, want, (length, width, radius, issues))

    def test_the_sweep_finds_crossings_in_any_chunk(self):
        n = 2000
        ring = [(100 * math.cos(2 * math.pi * k / n), 100 * math.sin(2 * math.pi * k / n)) for k in range(n)]
        for chunk in (1, 7, extrude.CROSS_CHUNK):
            with patching.patch_all(extrude, "CROSS_CHUNK", chunk):
                self.assertIs(extrude._crosses(numpy, ring, [10 ** 9]), False, chunk)
                for at in (3, n // 2, n - 2):  # a knot pulled across the far side
                    bent = list(ring)
                    bent[at] = (-ring[at][0] * 1.01, -ring[at][1] * 1.01)
                    self.assertIs(extrude._crosses(numpy, bent, [10 ** 9]), True, (chunk, at))
        self.assertIs(extrude._crosses(numpy, [(0, 0), (4, 0), (8, 0)], [0]), False)  # every edge adjacent

    def test_past_the_budget_the_cap_is_made_unchecked(self):
        with patching.patch_all(extrude, "MAX_CROSS_TESTS", 1):
            data, issues = self.make([_bowtie()])
        self.assertEqual(issues, ["1 closed spline not checked for crossings (more than 1 tests): capped"])
        self.assertEqual(len(data.loop_totals), 6)  # four sides, two caps as before
        tests = [5]
        self.assertIsNone(extrude._crosses(numpy, [(0, 0), (10, 10), (10, 0), (0, 10)], [0]))
        self.assertIs(extrude._crosses(numpy, [(0, 0), (10, 10), (10, 0), (0, 10)], tests), True)
        self.assertLess(tests[0], 5)


if __name__ == "__main__":
    unittest.main()
