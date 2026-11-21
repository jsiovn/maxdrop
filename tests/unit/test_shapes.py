# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/shapes.py, the splines of shape objects: no Blender. Every shape node of every committed
fixture against its 3ds Max oracle (knot types, segment types, positions and vectors within 1e-4, closed flags,
interpolation and rendering settings), and synthetic Scene streams for damaged input and the parameters no fixture
sets (odd side counts, Arc angles past the probed ones).

    python -I -m unittest discover tests
"""
import glob
import importlib
import json
import math
import os
import struct
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
SHAPES = os.path.join(ROOT, "tests", "fixtures", "shapes.max")
SHAPES_MORE = os.path.join(ROOT, "tests", "fixtures", "shapes_more.max")


_PKG = "maxdrop_convert_test"  # the package the convert tests make: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
cfb = importlib.import_module(_PKG + ".reader.cfb")
chunks = importlib.import_module(_PKG + ".reader.chunks")
classdir = importlib.import_module(_PKG + ".reader.classdir")
scene = importlib.import_module(_PKG + ".reader.scene")
shapes = importlib.import_module(_PKG + ".reader.shapes")
TOLERANCE = 1e-4


def _oracle(path):
    with open(path[:-4] + ".oracle.json", encoding="ascii") as f:
        return json.load(f)


def _close(test, got, want, msg):
    test.assertEqual(len(got), len(want), msg)
    for g, w in zip(got, want):
        test.assertTrue(math.isclose(g, w, rel_tol=1e-5, abs_tol=TOLERANCE), "%s: %r vs %r" % (msg, got, want))


def read_fixture(path):
    """{node name: Shape or None} of a fixture, the base object of each node's stack."""
    with cfb.CompoundFile(path) as cf:
        s = scene.Scene.from_file(cf)
        out = {}
        for n in s.nodes():
            base = s.object_stack(n.object).base if n.object is not None else None
            out[n.name] = shapes.read_shape(s, base) if base is not None else None
        return out


@unittest.skipUnless(FIXTURES, "no fixtures")
class TestFixtures(unittest.TestCase):
    def test_every_fixture_against_the_oracle(self):
        """What 3ds Max's own conversion to an Editable Spline gives (the oracle) equals what the reader reads or
        makes, knot by knot; a node that is no shape reads as None."""
        for path in FIXTURES:
            oracle = _oracle(path)
            with self.subTest(fixture=os.path.basename(path)):
                got = read_fixture(path)
                for n in oracle["nodes"]:
                    sh, want, label = got[n["name"]], n["shape"], n["name"]
                    self.assertEqual(sh is None, want is None, label)
                    if sh is None:
                        continue
                    self.assertEqual(sh.issues, (), label)
                    self.assertEqual("0x%08x" % sh.class_id[0], n["base_class_id"][0], label)
                    self.assertEqual((sh.steps, sh.optimize, sh.adaptive),
                                     (want["steps"], want["optimize"], want["adaptive"]), label)
                    r = sh.render
                    self.assertEqual((r.renderable, r.viewport, r.sides, r.rectangular),
                                     (want["renderable"], want["display_render_mesh"], want["sides"],
                                      want["rectangular"]), label)
                    _close(self, [r.thickness, r.angle, r.width, r.length],
                           [want["thickness"], want["angle"], want["width"], want["length"]], label)
                    self.assertEqual(len(sh.splines), len(want["splines"]), label)
                    for k, (sp, w) in enumerate(zip(sh.splines, want["splines"])):
                        where = "%s spline %d" % (label, k)
                        self.assertEqual(sp.closed, w["closed"], where)
                        self.assertEqual([shapes.KNOT_NAMES[x.kind] for x in sp.knots],
                                         [x["type"] for x in w["knots"]], where)
                        # the oracle names no segment after the last knot of an open spline
                        self.assertEqual([shapes.SEGMENT_NAMES[x.segment] for x in sp.knots][:len(w["knots"]) - 1
                                         + sp.closed], [x["segment"] for x in w["knots"] if x["segment"]], where)
                        for j, (x, y) in enumerate(zip(sp.knots, w["knots"])):
                            _close(self, x.point + x.in_vec + x.out_vec, y["pos"] + y["in"] + y["out"],
                                   "%s knot %d" % (where, j))

    @unittest.skipUnless(os.path.exists(SHAPES), "no shapes fixture")
    def test_shapes(self):
        got = read_fixture(SHAPES)
        line = got["FixtureLine"]
        self.assertEqual([len(sp.knots) for sp in line.splines], [4, 3])
        self.assertEqual(line.splines[1].knots[1].segment, shapes.LINE)  # straight, its vectors kept as stored
        self.assertEqual(line.render.thickness, 2.0)
        self.assertEqual(got["FixtureNGon"].class_id, shapes.classids.NGON)

    @unittest.skipUnless(os.path.exists(SHAPES_MORE), "no shapes_more fixture")
    def test_shapes_more(self):
        """The settings shapes.max leaves out; the rectangular angle (block index 14) is not in the oracle: the
        script's values, apart from the round angle's so that swapped indices fail."""
        got = read_fixture(SHAPES_MORE)
        r = got["FixtureSection"].render
        self.assertEqual((r.renderable, r.rectangular, r.width, r.length, r.section_angle, r.angle),
                         (True, True, 4.0, 1.0, 30.0, 15.0))
        self.assertEqual(got["FixtureSectionLoop"].render.section_angle, 0.0)
        self.assertEqual(len(got["FixtureEllOutline"].splines), 2)
        self.assertEqual(len(got["FixtureNGonCorner"].splines[0].knots), 12)
        self.assertEqual(len(got["FixtureNGonCornerRound"].splines[0].knots), 5)  # circular: no corner radius
        self.assertTrue(all(k.point == got["FixtureArcSame"].splines[0].knots[0].point
                            for k in got["FixtureArcSame"].splines[0].knots))

    def test_veccalc(self):
        """3ds Max's vector for a quarter circle, not the textbook 4/3 tan(a/4) = 0.552285; float32 like the SDK's
        loop, which stops at 1.5 / 1024 for a zero angle and at 0.0010986 for a sixth of a degree."""
        self.assertAlmostEqual(shapes.veccalc(math.pi / 2), 0.5517862, places=6)
        self.assertAlmostEqual(shapes.veccalc(math.radians(72)) * 12.3607, 5.35303, places=4)
        self.assertEqual(shapes.veccalc(0.0), 1.5 / 1024)
        self.assertAlmostEqual(shapes.veccalc(math.radians(0.5) / 3) * 10, 0.01098, places=4)  # the double: 0.0097


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def _entry(a, b, superclass, name):
    return node(0x2040, leaf(0x2060, struct.pack("<iIII", -1, a, b, superclass)),
                leaf(0x2042, name.encode("utf-16-le")))


def _refs(*values):
    return leaf(0x2034, struct.pack("<%di" % len(values), *values))


def _old_block(*values):
    """An old ParamBlock: index k holds values[k] (a float, an int, a bool or a point3 tuple)."""
    entries = []
    for k, v in enumerate(values):
        if isinstance(v, tuple):
            value = leaf(0x0103, struct.pack("<3f", *v))
        elif isinstance(v, float):
            value = leaf(0x0100, struct.pack("<f", v))
        else:
            value = leaf(0x0101, struct.pack("<i", int(v)))
        entries.append(node(0x0002, leaf(0x0003, struct.pack("<I", k)), value))
    return node(0, leaf(0x0001, struct.pack("<I", len(values))), leaf(0x0005, b"\x02\x00"), *entries)


def _knot(kind, segment, point, in_vec, out_vec, flags=0):
    return struct.pack("<iif9fI", kind, segment, 0.5, *point, *in_vec, *out_vec, flags)


def _spline(knots, closed=True, count=None):
    data = b"".join(knots)
    return node(0x1010, leaf(0x2900, struct.pack("<I", len(knots) if count is None else count)),
                leaf(0x2904, b"\0\0\0\0"), leaf(0x290A, data), leaf(0x290D, struct.pack("<I", int(closed))))


def _spline_shape(cls, splines, steps=6, inner=6, optimize=1):
    body = node(0x1010, *splines, leaf(0x1050, struct.pack("<i", inner)), leaf(0x1060, struct.pack("<I", optimize)))
    return node(cls, _refs(0, -1), leaf(0x204B, b"\x2e"), body, leaf(0x1060, struct.pack("<i", steps)))


RENDER = (1.0, 12, 0.0, 1.0, 12, 0.0, 0, 0, 0, 0, 1, 0, 2.0, 6.0)
CLASSES = ("ParamBlock", "SplineShape", "Line", "NGon", "Ellipse", "Rectangle", "Arc", "Circle")


def _scene(*objects):
    """Class indices: 0 ParamBlock, 1 SplineShape, 2 Line, 3 NGon, 4 Ellipse (here with an old block), 5 Rectangle,
    6 Arc, 7 Circle. Object 0 is a rendering block."""
    classes = classdir.ClassDirectory.parse(
        _entry(8, 0, 8, "ParamBlock") + _entry(0xA, 0, 0x40, "SplineShape") + _entry(0x1040, 0, 0x40, "Line") +
        _entry(0x1050, 0, 0x40, "NGon") + _entry(0x1097, 0, 0x40, "Ellipse") + _entry(0x1065, 0, 0x40, "Rectangle") +
        _entry(0x1996, 0, 0x40, "Arc") + _entry(0x1999, 0, 0x40, "Circle"))
    return scene.Scene(node(0x2025, _old_block(*RENDER), *objects), classes)


def _parametric(cls, params, interp=(6, 1, 0)):
    """Objects 1, 2, 3: the parameter block, the interpolation block, the shape (class cls)."""
    return _scene(_old_block(*params), _old_block(*interp), node(cls, _refs(0, 1, 2), leaf(0x204B, b"\x2e")))


GOOD = _knot(1, 0, (0, 0, 0), (0, 0, 0), (1, 0, 0))


class TestSynthetic(unittest.TestCase):
    def test_line_wrapper_and_steps(self):
        """A Line keeps the Editable Spline's chunks in a 0x2000 container; inner steps -1 = adaptive."""
        sp = _spline_shape(2, [_spline([GOOD, GOOD])], steps=9, inner=-1, optimize=0)
        body = sp[6:]  # the children of the class-2 container
        s = _scene(node(2, _refs(0, -1), leaf(0x204B, b"\x2e"), node(0x2000, *_children(body))))
        sh = shapes.read_shape(s, 1)
        self.assertEqual((sh.steps, sh.optimize, sh.adaptive, len(sh.splines)), (9, False, True, 1))

    def test_segment_material_ids(self):
        """The knot record's last u32 holds the zero-based material ID of the segment from that knot in its high 16
        bits (3ds Max 2020: IDs 1, 4, 7, 2 -> 0x0, 0x30000, 0x60000, 0x10000); parametric knots are ID 1."""
        ids = (0, 3, 6, 1, 0xFFFF)
        s = _scene(_spline_shape(1, [_spline([_knot(1, 0, (k, 0, 0), (k, 0, 0), (k, 0, 0), i << 16 | 0x5)
                                              for k, i in enumerate(ids)])]))
        sh = shapes.read_shape(s, 1)
        self.assertEqual([k.material for k in sh.splines[0].knots], list(ids))
        self.assertEqual({k.material for sp in shapes._rectangle(shapes._Params(None), []) for k in sp.knots}, {0})

    def test_damaged_spline_poisons_itself(self):
        bad_type = _knot(7, 0, (0, 0, 0), (0, 0, 0), (0, 0, 0))
        nan = _knot(1, 0, (float("nan"), 0, 0), (0, 0, 0), (0, 0, 0))
        s = _scene(_spline_shape(1, [_spline([GOOD]), _spline([GOOD], count=9), _spline([bad_type]),
                                     _spline([nan]), node(0x1010, leaf(0x2900, b"\1\0\0\0")), leaf(0x1010)]))
        sh = shapes.read_shape(s, 1)
        self.assertEqual(len(sh.splines), 1)
        self.assertEqual(len(sh.issues), 5)
        self.assertTrue(all(i.startswith("spline %d left out" % k) for i, k in zip(sh.issues, range(1, 6))))

    def test_no_bezier_shape_raises(self):
        s = _scene(node(1, _refs(0, -1), leaf(0x204B, b"\x2e")))
        with self.assertRaises(shapes.ShapeError):
            shapes.read_shape(s, 1)
        s = _scene(leaf(1))
        with self.assertRaises(shapes.ShapeError):
            shapes.read_shape(s, 1)

    def test_not_a_shape(self):
        s = _scene(_old_block(1.0))
        self.assertIsNone(shapes.read_shape(s, 1))
        self.assertFalse(shapes.is_shape(s, 0))

    def test_missing_rendering_block(self):
        s = _scene(node(1, _refs(-1, -1), node(0x1010, _spline([GOOD]))))
        sh = shapes.read_shape(s, 1)
        self.assertEqual(sh.render, shapes.DEFAULT_RENDER)
        self.assertEqual(len(sh.issues), 1)

    def test_missing_parameters_raise(self):
        s = _scene(node(3, _refs(0, -1, -1)))
        with self.assertRaises(shapes.ShapeError):
            shapes.read_shape(s, 1)
        with self.assertRaises(shapes.ShapeError):  # a radius that is not a number
            shapes.read_shape(_parametric(7, (float("inf"),)), 3)

    def test_ngon_corner_radius_and_sides(self):
        """A corner radius makes two knots per corner, at radius * tan(180 / sides) along the sides (no clamp)."""
        sh = shapes.read_shape(_parametric(3, (10.0, 4, 0, 2.0, 1)), 3)
        self.assertEqual(sh.issues, ())
        pts = [c for k in sh.splines[0].knots for c in k.point[:2]]
        d = 2.0 * math.tan(math.pi / 4) / math.sqrt(2)
        _close(self, pts[:4], [10 - d, -d, 10 - d, d], "square, corner 0")
        self.assertEqual(len(pts), 16)
        k = sh.splines[0].knots[1]
        _close(self, [k.out_vec[0] - k.point[0], k.out_vec[1] - k.point[1]],
               [-2.0 * shapes.veccalc(math.pi / 2) / math.sqrt(2), 2.0 * shapes.veccalc(math.pi / 2) / math.sqrt(2)],
               "out vector along the side")
        sh = shapes.read_shape(_parametric(3, (10.0, 5, 1, 2.0, 1)), 3)  # circular: the corner radius is ignored
        self.assertEqual(len(sh.splines[0].knots), 5)
        sh = shapes.read_shape(_parametric(3, (10.0, 2, 0, 0.0, 1)), 3)
        self.assertEqual((len(sh.splines[0].knots), len(sh.issues)), (3, 1))
        sh = shapes.read_shape(_parametric(3, (10.0, 1 << 30, 0, 0.0, 1)), 3)
        self.assertEqual((len(sh.splines[0].knots), len(sh.issues)), (shapes.MAX_SIDES, 1))
        sh = shapes.read_shape(_parametric(3, (10.0, 4, 0, (1.0, 2.0, 3.0), 1)), 3)  # no number: sharp corners
        self.assertEqual((len(sh.splines[0].knots), len(sh.issues)), (4, 1))
        self.assertIn("corner radius", sh.issues[0])

    def test_ellipse_outline(self):
        """The outline is a second spline with both semi-axes plus the thickness, each clamped at 0."""
        sh = shapes.read_shape(_parametric(4, (20.0, 40.0, 3.0, 1)), 3)
        self.assertEqual((len(sh.splines), sh.issues), (2, ()))
        _close(self, sh.splines[0].knots[0].point, (20, 0, 0), "ellipse")
        _close(self, sh.splines[1].knots[0].point + sh.splines[1].knots[1].point, (23, 0, 0, 0, 13, 0), "outline")
        sh = shapes.read_shape(_parametric(4, (20.0, 40.0, -15.0, 1)), 3)
        _close(self, sh.splines[1].knots[1].point + sh.splines[1].knots[1].in_vec, (0, 0, 0, 5 * 0.5517862, 0, 0),
               "inset")
        sh = shapes.read_shape(_parametric(4, (20.0, 40.0, 3.0, 0)), 3)
        self.assertEqual(len(sh.splines), 1)
        sh = shapes.read_shape(_parametric(4, (20.0, 40.0, (1.0, 2.0, 3.0), 1)), 3)  # the ellipse kept, an issue
        self.assertEqual((len(sh.splines), len(sh.issues)), (1, 1))
        self.assertIn("outline", sh.issues[0])

    def test_arc_angles_clamped(self):
        """from and to are clamped to [0, 360] first: 400 -> 500 is a zero-length arc at 360, 0 -> 720 a full turn
        ending at 360, 0 -> -90 a zero-length arc at 0."""
        for start, end, first, span in ((400.0, 500.0, 360, 0), (0.0, 720.0, 0, 360), (0.0, -90.0, 0, 0),
                                        (40.0, 40.0, 40, 0), (100.0, 50.0, 100, 310), (-30.0, 60.0, 0, 60)):
            with self.subTest(start=start, end=end):
                sp = shapes.read_shape(_parametric(6, (10.0, start, end, 0, 0)), 3).splines[0]
                angles = [math.degrees(math.atan2(k.point[1], k.point[0])) % 360 for k in sp.knots]
                want = [(first + span * j / 3.0) % 360 for j in range(4)]
                _close(self, [math.cos(math.radians(a)) for a in angles], [math.cos(math.radians(a)) for a in want],
                       "cos")
                _close(self, [math.sin(math.radians(a)) for a in angles], [math.sin(math.radians(a)) for a in want],
                       "sin")
        k = shapes.read_shape(_parametric(6, (1000.0, 0.0, 0.0, 0, 0)), 3).splines[0].knots[0]
        _close(self, k.out_vec, (1000, 1.46484375, 0), "zero-length arc vector")

    def test_steps_clamped(self):
        sh = shapes.read_shape(_parametric(7, (5.0,), interp=(1000, 1, 0)), 3)
        self.assertEqual(sh.steps, shapes.MAX_STEPS)

    def test_parameters_of_any_type(self):
        """Every parameter of every parametric class stored as a float, an int, a point3 or NaN gives a Shape or a
        ShapeError, never another exception: the file decides each value's type."""
        defaults = {5: (20.0, 30.0, 3.0), 7: (10.0,), 3: (10.0, 6, 0, 0.0, 0), 4: (20.0, 40.0, 0.0, 0),
                    6: (15.0, 30.0, 200.0, 0, 0)}
        for cls, params in defaults.items():
            for k in range(len(params)):
                for bad in (6.5, 7, (1.0, 2.0, 3.0), float("nan"), -1e30, 1e30):
                    values = list(params)
                    values[k] = bad
                    with self.subTest(cls=cls, index=k, value=bad):
                        try:
                            sh = shapes.read_shape(_parametric(cls, tuple(values)), 3)
                        except shapes.ShapeError:
                            continue
                        self.assertTrue(all(math.isfinite(c) for sp in sh.splines for kn in sp.knots
                                            for c in kn.point + kn.in_vec + kn.out_vec) or bad in (1e30, -1e30))
        for interp in ((float("nan"), 1, 0), ((1.0, 2.0, 3.0), 1, 0), (6, (1.0, 2.0, 3.0), 2.5)):
            with self.subTest(interp=interp):
                try:
                    sh = shapes.read_shape(_parametric(7, (5.0,), interp=interp), 3)
                except shapes.ShapeError:
                    continue
                self.assertTrue(0 <= sh.steps <= shapes.MAX_STEPS)

    def test_float_sides_and_point3_radius(self):
        sh = shapes.read_shape(_parametric(3, (10.0, 6.5, 0, 0.0, 1)), 3)
        self.assertEqual((len(sh.splines[0].knots), len(sh.issues)), (6, 1))
        with self.assertRaises(shapes.ShapeError):
            shapes.read_shape(_parametric(7, ((1.0, 2.0, 3.0),)), 3)
        with self.assertRaises(shapes.ShapeError):  # NaN steps
            shapes.read_shape(_parametric(7, (5.0,), interp=(float("nan"), 1, 0)), 3)

    def test_animated_parameter_is_refused(self):
        """An animated ParamBlock2 parameter (an Ellipse's length) has a controller, no value: the shape is
        refused with a reason instead of failing on the controller."""
        class Block:
            def get(self, i, default=None):
                return shapes.pblock.Animated(9) if i == 0 else 20.0

        with self.assertRaises(shapes.ChunkError) as caught:
            shapes._ellipse(shapes._Params(Block()), [])
        self.assertIn("animated", str(caught.exception))

    def test_rendering_values_of_any_type(self):
        """A rendering value that is no number keeps 3ds Max's default: the shape is still read."""
        s = scene.Scene(node(0x2025, _old_block((1.0, 2.0, 3.0), float("nan"), 0.0, 1.0, 12, 0.0, (1.0, 1.0, 1.0)),
                             _spline_shape(1, [_spline([GOOD])])), _scene().classes)
        sh = shapes.read_shape(s, 1)
        self.assertEqual(sh.render, shapes.DEFAULT_RENDER)

    def test_arc_wraps_and_pie_reversed(self):
        """to below from runs on past 360 degrees; a reversed pie is the closed pie reversed with its first knot
        kept first: from, the center, to, back to from (arc_pie_reverse, as 3ds Max orders it)."""
        sh = shapes.read_shape(_parametric(6, (10.0, 270.0, 90.0, 1, 1)), 3)
        sp = sh.splines[0]
        self.assertTrue(sp.closed)
        _close(self, [c for k in sp.knots for c in k.point[:2]],
                   [0, -10, 0, 0, 0, 10, 10 * math.cos(math.radians(30)), 5, 10 * math.cos(math.radians(30)), -5],
                   "pie")
        self.assertEqual(sp.knots[0].out_vec, sp.knots[0].point)
        self.assertNotEqual(sp.knots[0].in_vec, sp.knots[0].point)
        self.assertEqual(sp.knots[2].in_vec, sp.knots[2].point)
        sh = shapes.read_shape(_parametric(6, (10.0, 270.0, 90.0, 0, 1)), 3)  # reverse alone: to back to from
        _close(self, [c for k in sh.splines[0].knots for c in k.point[:2]],
               [0, 10, 10 * math.cos(math.radians(30)), 5, 10 * math.cos(math.radians(30)), -5, 0, -10], "reversed")
        self.assertFalse(sh.splines[0].closed)


def _children(body):
    """The chunks of a container payload, as bytes, in order."""
    out, pos = [], 0
    while pos < len(body):
        size = struct.unpack_from("<I", body, pos + 2)[0] & 0x7FFFFFFF
        out.append(body[pos:pos + size])
        pos += size
    return out


if __name__ == "__main__":
    unittest.main()
