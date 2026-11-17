# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/shapes.py, the splines of shape objects: no Blender. Every shape node of every committed
fixture against its 3ds Max oracle (knot types, segment types, positions and vectors within 1e-4, closed flags,
interpolation and rendering settings), and synthetic Scene streams for damaged input and the parameters no fixture
sets (NGon corner radius, Ellipse outline, odd side counts).

    python -I -m unittest discover tests
"""
import glob
import importlib.util
import json
import math
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
SHAPES = os.path.join(ROOT, "tests", "fixtures", "shapes.max")


def _load(name, path, package_dir=None):
    if name in sys.modules:
        return sys.modules[name]
    kw = {"submodule_search_locations": [package_dir]} if package_dir else {}
    spec = importlib.util.spec_from_file_location(name, path, **kw)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_READER = os.path.join(ROOT, "maxdrop", "reader")
_load("maxdrop_reader", os.path.join(_READER, "__init__.py"), _READER)
cfb = _load("maxdrop_reader.cfb", os.path.join(_READER, "cfb.py"))
chunks = _load("maxdrop_reader.chunks", os.path.join(_READER, "chunks.py"))
classdir = _load("maxdrop_reader.classdir", os.path.join(_READER, "classdir.py"))
scene = _load("maxdrop_reader.scene", os.path.join(_READER, "scene.py"))
shapes = _load("maxdrop_reader.shapes", os.path.join(_READER, "shapes.py"))
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

    def test_veccalc(self):
        """3ds Max's vector for a quarter circle, not the textbook 4/3 tan(a/4) = 0.552285."""
        self.assertAlmostEqual(shapes.veccalc(math.pi / 2), 0.5517862, places=6)
        self.assertAlmostEqual(shapes.veccalc(math.radians(72)) * 12.3607, 5.35303, places=4)


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
    """An old ParamBlock: index k holds values[k] (a float, an int or a bool)."""
    entries = []
    for k, v in enumerate(values):
        if isinstance(v, float):
            value = leaf(0x0100, struct.pack("<f", v))
        else:
            value = leaf(0x0101, struct.pack("<i", int(v)))
        entries.append(node(0x0002, leaf(0x0003, struct.pack("<I", k)), value))
    return node(0, leaf(0x0001, struct.pack("<I", len(values))), leaf(0x0005, b"\x02\x00"), *entries)


def _knot(kind, segment, point, in_vec, out_vec):
    return struct.pack("<iif9fI", kind, segment, 0.5, *point, *in_vec, *out_vec, 0)


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
        sh = shapes.read_shape(_parametric(3, (10.0, 4, 0, 2.0, 1)), 3)
        self.assertEqual(len(sh.issues), 1)  # sharp corners drawn
        _close(self, [c for k in sh.splines[0].knots for c in k.point[:2]], [10, 0, 0, 10, -10, 0, 0, -10], "square")
        sh = shapes.read_shape(_parametric(3, (10.0, 2, 0, 0.0, 1)), 3)
        self.assertEqual((len(sh.splines[0].knots), len(sh.issues)), (3, 1))
        sh = shapes.read_shape(_parametric(3, (10.0, 1 << 30, 0, 0.0, 1)), 3)
        self.assertEqual((len(sh.splines[0].knots), len(sh.issues)), (shapes.MAX_SIDES, 1))

    def test_ellipse_outline(self):
        sh = shapes.read_shape(_parametric(4, (20.0, 40.0, 1.0, 1)), 3)
        self.assertEqual((len(sh.splines), len(sh.issues)), (1, 1))
        _close(self, sh.splines[0].knots[0].point, (20, 0, 0), "ellipse")

    def test_steps_clamped(self):
        sh = shapes.read_shape(_parametric(7, (5.0,), interp=(1000, 1, 0)), 3)
        self.assertEqual(sh.steps, shapes.MAX_STEPS)

    def test_arc_wraps_and_pie_reversed(self):
        """to below from runs on past 360 degrees; a reversed pie keeps its center and is closed."""
        sh = shapes.read_shape(_parametric(6, (10.0, 270.0, 90.0, 1, 1)), 3)
        sp = sh.splines[0]
        self.assertTrue(sp.closed)
        _close(self, [c for k in sp.knots for c in k.point[:2]],
                   [0, 10, 10 * math.cos(math.radians(30)), 5, 10 * math.cos(math.radians(30)), -5, 0, -10, 0, 0],
                   "pie")
        self.assertEqual(sp.knots[0].in_vec, sp.knots[0].point)
        self.assertEqual(sp.knots[3].out_vec, sp.knots[3].point)


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
