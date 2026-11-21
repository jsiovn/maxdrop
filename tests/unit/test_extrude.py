# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/extrude.py, the Extrude modifier on a shape: no Blender. Every extruded node of the
extrude fixture against its 3ds Max oracle (world bounding box within 1e-3, vertex count, triangle count), closed
manifolds with outward normals for the capped ones, the hole of the holed cap, the open one without caps; material
IDs by the way a face looks and map channel 1's vertex count and range against the oracle's eval_mesh; mapping
coordinates; 3ds Max's interpolation counts (found with its own Extrude: steps, optimize, adaptive); the ear
clipping of outlines with holes; damaged and hostile parameters.

    python -I -m unittest discover tests
"""
import importlib
import json
import math
import os
import sys
import types
import unittest
import weakref
from unittest import mock

try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "extrude.max")
BBOX_TOLERANCE = 1e-3

_PKG = "maxdrop_convert_test"  # the same package as test_convert_scene: the add-on's __init__ never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
conv = importlib.import_module(_PKG + ".convert.scene")
extrude = importlib.import_module(_PKG + ".convert.extrude")
shapes = importlib.import_module(_PKG + ".reader.shapes")
pblock = importlib.import_module(_PKG + ".reader.pblock")
classids = importlib.import_module(_PKG + ".reader.classids")
reader_modifiers = importlib.import_module(_PKG + ".reader.modifiers")
rules = importlib.import_module(_PKG + ".convert.modifiers")

CAPPED = ("FixtureExtRect", "FixtureExtL", "FixtureExtHole", "FixtureExtIsland", "FixtureExtMirror",
          "FixtureExtAdaptive", "FixtureExtShapeIDs", "FixtureExtShapeIDsRect")
# V - E + F of each mesh: a box-like solid 2, a solid with a tunnel (the round hole) 0, the island's ring and its
# core 0 + 2
EULER = {"FixtureExtRect": 2, "FixtureExtL": 2, "FixtureExtHole": 0, "FixtureExtIsland": 2, "FixtureExtMirror": 2,
         "FixtureExtAdaptive": 2, "FixtureExtShapeIDs": 0, "FixtureExtShapeIDsRect": 2}


def _edges(md):
    """{(a, b): count} of directed edges."""
    out = {}
    for s, t in zip(md.loop_starts.tolist(), md.loop_totals.tolist()):
        loop = md.loop_vertices[s:s + t].tolist()
        for k in range(t):
            e = (loop[k], loop[(k + 1) % t])
            out[e] = out.get(e, 0) + 1
    return out


def _volume(positions, md):
    p = numpy.asarray(positions, dtype=numpy.float64)
    total = 0.0
    for s, t in zip(md.loop_starts.tolist(), md.loop_totals.tolist()):
        loop = md.loop_vertices[s:s + t].tolist()
        for k in range(1, t - 1):
            total += numpy.dot(p[loop[0]], numpy.cross(p[loop[k]], p[loop[k + 1]])) / 6.0
    return total


def _mats(md):
    """Material indices of a MeshDescription or a reader MeshData."""
    return md.material_indices if hasattr(md, "material_indices") else md.material_ids


def _face_area_z(md, f):
    """The signed area of face f projected on XY (positive: it faces +Z)."""
    s, t = int(md.loop_starts[f]), int(md.loop_totals[f])
    p = md.positions[md.loop_vertices[s:s + t]].astype(numpy.float64)
    return 0.5 * float(numpy.sum(p[:, 0] * numpy.roll(p[:, 1], -1) - numpy.roll(p[:, 0], -1) * p[:, 1]))


def _face_area(md, f):
    """The area of face f (half the length of its Newell normal)."""
    s, t = int(md.loop_starts[f]), int(md.loop_totals[f])
    p = md.positions[md.loop_vertices[s:s + t]].astype(numpy.float64)
    return 0.5 * float(numpy.linalg.norm(numpy.cross(p, numpy.roll(p, -1, axis=0)).sum(axis=0)))


@unittest.skipIf(numpy is None, "numpy missing")
class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = {}  # the reader MeshData of each mesh, by name: its map channels keep their map vertices
        real = conv.mesh_description

        def describing(key, name, data, *args, **kw):
            cls.data[name] = data
            return real(key, name, data, *args, **kw)

        with mock.patch.object(conv, "mesh_description", describing):
            cls.desc = conv.read(FIXTURE)
        with open(FIXTURE[:-4] + ".oracle.json", encoding="utf-8") as f:
            cls.oracle = {n["name"]: n for n in json.load(f)["nodes"]}
        cls.nodes = {n.name: n for n in cls.desc.nodes}

    def mesh(self, name):
        node = self.nodes[name]
        self.assertEqual(node.kind, conv.MESH, name)
        return node, self.desc.meshes[node.mesh]

    def test_counts_and_world_box_equal_the_oracle(self):
        for name in CAPPED + ("FixtureExtOpen",):
            node, md = self.mesh(name)
            o = self.oracle[name]
            self.assertEqual(len(md.positions), o["eval_verts"], name)
            self.assertEqual(int((md.loop_totals - 2).sum()), o["eval_faces"], name)  # 3ds Max counts triangles
            m = numpy.asarray(node.world, dtype=numpy.float64)
            p = (numpy.asarray(md.positions, dtype=numpy.float64) @ m[:3, :3].T + m[:3, 3]) / self.desc.meters
            numpy.testing.assert_allclose(p.min(axis=0), o["bbox_min"], atol=BBOX_TOLERANCE, err_msg=name)
            numpy.testing.assert_allclose(p.max(axis=0), o["bbox_max"], atol=BBOX_TOLERANCE, err_msg=name)

    def test_capped_meshes_are_closed_with_outward_normals(self):
        for name in CAPPED:
            node, md = self.mesh(name)
            edges = _edges(md)
            self.assertTrue(all(c == 1 for c in edges.values()), name)  # no edge twice the same way round
            self.assertTrue(all((b, a) in edges for a, b in edges), name)  # every edge has two faces
            self.assertGreater(_volume(md.positions, md), 0, name)  # outward in object space
            undirected = len(edges) // 2
            self.assertEqual(len(md.positions) - undirected + len(md.loop_starts), EULER[name], name)
            world = numpy.asarray(node.world, dtype=numpy.float64)
            # as rendered: Blender turns a mirrored object's normals back, so volume * det is what shows
            p = numpy.asarray(md.positions, dtype=numpy.float64) @ world[:3, :3].T + world[:3, 3]
            self.assertGreater(_volume(p, md) * numpy.linalg.det(world[:3, :3]), 0, name)

    def test_the_holed_cap_has_its_hole(self):
        _node, md = self.mesh("FixtureExtHole")
        top = [f for f in range(len(md.loop_starts)) if md.material_indices[f] == extrude.TOP_ID]
        area = sum(_face_area_z(md, f) for f in top) / self.desc.meters ** 2
        circle = 0.5 * 28 * 8 * 8 * math.sin(2 * math.pi / 28)  # the hole: 28 points on a radius of 8
        self.assertAlmostEqual(area, 40 * 40 - circle, delta=0.5)  # the polyline lies within the circle
        self.assertLess(area, 40 * 40 - 190)
        self.assertTrue(all(_face_area_z(md, f) > 0 for f in top))

    def test_the_island_is_solid_again(self):
        _node, md = self.mesh("FixtureExtIsland")
        top = [f for f in range(len(md.loop_starts)) if md.material_indices[f] == extrude.TOP_ID]
        area = sum(_face_area_z(md, f) for f in top) / self.desc.meters ** 2
        self.assertAlmostEqual(area, 40 * 40 - 24 * 24 + 10 * 10, places=3)

    def test_the_open_line_has_no_cap(self):
        _node, md = self.mesh("FixtureExtOpen")
        self.assertEqual(set(md.material_indices.tolist()), {extrude.SIDE_ID})
        self.assertEqual(len(md.loop_starts), 8)  # 8 polyline segments (2 x 4 steps), one level

    def test_material_ids_by_the_way_a_cap_faces(self):
        """3ds Max gives the cap facing +Z ID 1 and the one facing -Z ID 2, whatever the sign of the amount."""
        for name in ("FixtureExtRect", "FixtureExtL"):
            _node, md = self.mesh(name)
            for f in range(len(md.loop_starts)):
                mat = int(md.material_indices[f])
                if mat == extrude.SIDE_ID:
                    continue
                self.assertEqual(_face_area_z(md, f) > 0, mat == extrude.TOP_ID, name)
        _node, md = self.mesh("FixtureExtAdaptive")  # Generate Material IDs off
        self.assertEqual(set(md.material_indices.tolist()), {0})

    def test_material_ids_and_map_channel_1_equal_the_oracle(self):
        """Per material ID the triangles facing +Z, -Z and sideways in object space, and map channel 1's vertex
        count and range, as 3ds Max's evaluated mesh has them (docs/ORACLE.md, eval_mesh)."""
        for name in CAPPED + ("FixtureExtOpen",):
            _node, md = self.mesh(name)
            data = self.data[name]  # object space, before the object offset, as the oracle takes it back to
            want = self.oracle[name]["eval_mesh"]
            hist = {}
            for f in range(len(data.loop_starts)):
                z = _face_area_z(data, f)  # the winding normal's z, times the polygon's area
                if abs(z) <= 1e-4 * _face_area(data, f):
                    side = 3
                else:
                    side = 1 if z > 0 else 2
                row = hist.setdefault(int(_mats(data)[f]) + 1, [0, 0, 0])
                row[side - 1] += int(data.loop_totals[f]) - 2  # 3ds Max counts triangles
            self.assertEqual([[i] + hist[i] for i in sorted(hist)], want["material_ids"], name)
            channel = data.maps.get(1)
            self.assertEqual(channel is None, want["map_channel_1"] is None, name)
            if channel is None:
                continue
            uvw = numpy.asarray(channel.uvw, dtype=numpy.float64)
            used = uvw[numpy.unique(channel.indices)]
            self.assertEqual(len(uvw), want["map_channel_1"]["count"], name)
            for got, key in ((used.min(axis=0), "min"), (used.max(axis=0), "max")):  # 6 significant digits
                numpy.testing.assert_allclose(got, want["map_channel_1"][key], rtol=1e-5, atol=1e-6, err_msg=name)
            uv = dict(md.uv_layers)["UVMap"]  # what Blender gets: u and v of the same vertices
            for got, key in ((uv.min(axis=0), "min"), (uv.max(axis=0), "max")):
                numpy.testing.assert_allclose(got, want["map_channel_1"][key][:2], rtol=1e-5, atol=1e-6, err_msg=name)

    def test_mapping_coordinates(self):
        _node, md = self.mesh("FixtureExtRect")
        uv = dict(md.uv_layers)["UVMap"]
        self.assertGreaterEqual(float(uv.min()), 0.0)
        self.assertLessEqual(float(uv.max()), 1.0)
        _node, md = self.mesh("FixtureExtAdaptive")  # Real-World Map Size: units, not 0 to 1
        uv = dict(md.uv_layers)["UVMap"]  # in file units, as 3ds Max keeps them
        self.assertAlmostEqual(float(uv[:, 0].max()), 128 * 2 * 6 * math.sin(math.pi / 128), delta=0.05)
        self.assertAlmostEqual(float(uv[:, 1].max()), 12.0, places=3)  # the cap's box, 12 across
        self.assertNotIn("UVMap", dict(self.mesh("FixtureExtL")[1].uv_layers))

    def test_the_report_counts_extrude_as_applied(self):
        for name in CAPPED + ("FixtureExtOpen",):
            self.assertEqual((self.nodes[name].applied, self.nodes[name].modifiers), (("Extrude",), ()), name)
        off = self.nodes["FixtureExtOff"]  # switched off: the curve, the modifier not applied
        self.assertEqual((off.kind, off.applied, off.modifiers), (conv.CURVE, (), ("Extrude",)))
        rep = importlib.import_module(_PKG + ".convert.report").gather(self.desc)
        self.assertEqual(dict(rep.modifiers_applied), {"Extrude": 9})
        self.assertEqual(dict(rep.modifiers), {"Extrude": 1})

    def test_a_modifier_below_the_extrude_keeps_the_curve(self):
        real = reader_modifiers.Modifiers.object_stack

        def below(self, i):
            st = real(self, i)
            if not st.modifiers:
                return st
            other = st.modifiers[0]._replace(class_id=classids.EDITABLE_POLY, index=st.base)
            return st._replace(modifiers=(other,) + st.modifiers)

        with mock.patch.object(reader_modifiers.Modifiers, "object_stack", below):
            desc = conv.read(FIXTURE)
        self.assertEqual([n.kind for n in desc.nodes], [conv.CURVE] * 10)
        self.assertEqual(len([r for _i, r in desc.issues if r.startswith("extrude: an Extrude above ")]), 9)

    def test_an_extrude_that_cannot_be_read_keeps_the_curve(self):
        with mock.patch.object(extrude, "read_params", side_effect=extrude.ExtrudeError("refused")):
            desc = conv.read(FIXTURE)
        self.assertEqual([n.kind for n in desc.nodes], [conv.CURVE] * 10)
        self.assertEqual([r for _i, r in desc.issues], ["extrude: refused"] * 9)
        self.assertEqual(desc.meshes, {})

    def test_extruded_data_is_released_after_its_last_node(self):
        """An extruded shape's MeshData goes once its base object's last node is described, like a mesh's."""
        made, alive = [], []
        real_extrude, real_description = extrude.extrude, conv.mesh_description

        def extruding(shape, params):
            data, issues = real_extrude(shape, params)
            made.append(weakref.ref(data.positions))
            return data, issues

        def describing(*args, **kw):
            alive.append(sum(r() is not None for r in made))
            return real_description(*args, **kw)

        with mock.patch.object(extrude, "extrude", extruding), mock.patch.object(conv, "mesh_description",
                                                                                 describing):
            conv.read(FIXTURE)
        self.assertEqual(len(made), 9)
        self.assertEqual(alive, [1] * 9)  # only the extrusion being described

    def test_a_scene_wide_budget_keeps_the_rest_curves(self):
        with mock.patch.object(conv, "MAX_BUILT_CORNERS", 1):
            desc = conv.read(FIXTURE)
        self.assertEqual(sorted(n.kind for n in desc.nodes), [conv.CURVE] * 9 + [conv.MESH])
        spent = [r for _i, r in desc.issues if r.startswith("extrude: not made: the primitives and extrusions ")]
        self.assertEqual(len(spent), 8)

    def test_conversion_issues_wait_for_a_made_extrude(self):
        """A converted modifier's issues are named on the first node whose Extrude is made: one whose Extrude
        fails is a curve, its modifiers not converted."""
        real_evaluated, real_read = conv._evaluated, extrude.read_params
        shared = types.SimpleNamespace(index=None)
        calls = []

        def evaluated(*args):
            ext, maps, rest = real_evaluated(*args)
            if ext is not None:
                if shared.index is None:
                    shared.index = ext.index
                rest = rest + (shared,)  # one modifier instanced on every extruded shape
            return ext, maps, rest

        def converting(_scene, m, _meters=1.0, _offset=None):
            md = rules.ModifierDescription(m.index, rules.SOLIDIFY, "Shell", "Shell", True, (), None, None)
            return md, ["a rule issue"]

        def failing_first(scene, m):
            calls.append(m.index)
            if len(calls) == 1:
                raise extrude.ExtrudeError("refused")
            return real_read(scene, m)

        patches = (mock.patch.object(conv, "_evaluated", evaluated),
                   mock.patch.object(rules, "is_convertible", lambda m: m is shared),
                   mock.patch.object(rules, "convert", converting),
                   mock.patch.object(extrude, "read_params", failing_first))
        for p in patches:
            p.start()
        try:
            desc = conv.read(FIXTURE)
        finally:
            for p in patches:
                p.stop()
        named = [i for i, r in desc.issues if r.endswith(": a rule issue")]
        self.assertEqual(len(named), 1)
        kinds = {n.index: n.kind for n in desc.nodes}
        self.assertEqual(kinds[named[0]], conv.MESH)


def _knots(points, kind=shapes.CORNER):
    return tuple(shapes.Knot(kind, shapes.LINE, p, p, p) for p in points)


def _shape(splines, steps=6, optimize=True, adaptive=False):
    return shapes.Shape(shapes.classids.SPLINE_SHAPE, tuple(splines), steps, optimize, adaptive,
                        shapes.DEFAULT_RENDER, ())


def _points(shape):
    return sum(len(pl.points) for pl in extrude.polylines(shape))


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


class FakeBlock:
    def __init__(self, values):
        self.values = values

    def get(self, i, default=None):
        return self.values.get(i, default)


# An object chunk 0x0001 holding a 0x2150 whose children do not parse (a cut-short chunk header): Real-World Map
# Size off (reader.realworld), the rest of the object read.
DAMAGED_REAL_WORLD = bytes.fromhex("01000f000080" "502109000080" "300107")


class FakeScene:
    def chunk(self, i):
        return extrude.chunks.index(DAMAGED_REAL_WORLD)[0]


def _modifier(values):
    return types.SimpleNamespace(index=1, legacy={0: FakeBlock(values)} if values is not None else {},
                                 class_id=classids.EXTRUDE, superclass=classids.SC_OSMODIFIER)


class Parameters(unittest.TestCase):
    def test_values_and_defaults(self):
        p, issues = extrude.read_params(FakeScene(), _modifier({0: -3.5, 1: 2, 6: 1, 7: 0}))
        self.assertEqual((p.amount, p.segments, p.mapping, p.material_ids, p.cap_start, p.smooth, p.real_world),
                         (-3.5, 2, True, False, True, True, False))
        self.assertEqual(issues, [])

    def test_refused(self):
        for values in (None, {0: pblock.Animated(3)}, {0: float("nan")}, {1: "two"}, {0: (1.0, 2.0, 3.0)}):
            with self.assertRaises(extrude.ExtrudeError, msg=repr(values)):
                extrude.read_params(FakeScene(), _modifier(values))

    def test_clamped_and_approximated(self):
        p, issues = extrude.read_params(FakeScene(), _modifier({1: 0, 4: 1, 5: 0, 7: 1, 8: 1}))
        self.assertEqual(p.segments, 1)
        self.assertEqual(len(issues), 3)  # segments, grid caps, patch output (shape IDs are read)
        self.assertTrue(p.shape_ids)
        p, _issues = extrude.read_params(FakeScene(), _modifier({1: 10 ** 9}))
        self.assertEqual(p.segments, extrude.MAX_SEGMENTS)

    def test_real_world_is_read_from_its_own_chunk_and_class(self):
        """Real-World Map Size comes from reader.realworld (tests/unit/test_realworld.py has its cases), asked
        for the modifier's own chunk and the Extrude class; a damaged 0x2150 is off."""
        own = object()
        scene = types.SimpleNamespace(chunk=lambda i: own if i == 1 else None)
        with mock.patch.object(extrude.realworld, "flag", return_value=True) as flag:
            p, _issues = extrude.read_params(scene, _modifier({}))
        self.assertTrue(p.real_world)
        flag.assert_called_once_with(own, classids.EXTRUDE)
        p, _issues = extrude.read_params(FakeScene(), _modifier({}))
        self.assertFalse(p.real_world)

    def test_is_extrude(self):
        self.assertTrue(extrude.is_extrude(_modifier({})))
        self.assertFalse(extrude.is_extrude(types.SimpleNamespace(class_id=classids.EXTRUDE,
                                                                  superclass=classids.SC_SHAPE)))


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

    def test_negative_amount_and_segments(self):
        data, _issues = extrude.extrude(_shape([self.square(4)]), self.params(amount=-5.0, segments=3))
        self.assertEqual(len(data.positions), 16)
        self.assertAlmostEqual(_volume(data.positions, data), 80.0, places=4)
        self.assertAlmostEqual(float(data.positions[:, 2].min()), -5.0)

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

    def test_flat_amount_is_an_issue(self):
        _data, issues = extrude.extrude(_shape([self.square(4)]), self.params(amount=0.0))
        self.assertEqual(len(issues), 1)

    def test_hostile_sizes(self):
        with mock.patch.object(extrude, "MAX_VERTICES", 10):
            with self.assertRaises(extrude.ExtrudeError):
                extrude.extrude(_shape([self.square(4), self.square(2)]), self.params(segments=2))
        holed = _shape([self.square(10), shapes.Spline(_knots([(2, 2, 0), (2, 4, 0), (4, 4, 0), (4, 2, 0)]),
                                                       True)])
        with mock.patch.object(extrude, "MAX_CAP_POINTS", 6):
            data, issues = extrude.extrude(holed, self.params())
        self.assertEqual(len(issues), 1)
        self.assertEqual(set(_mats(data).tolist()), {extrude.SIDE_ID})  # the cap is left open
        with mock.patch.object(extrude, "MAX_LOOPS", 1):
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

        with mock.patch.object(extrude, "MAX_NEST_TESTS", 1000), mock.patch.object(extrude, "_inside", inside):
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
        with mock.patch.object(extrude, "MAX_CLIP_STEPS", one + one // 2):
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
        with mock.patch.object(extrude, "MAX_CLIP_STEPS", one + one // 2), \
                mock.patch.object(extrude, "triangulate", wraps=extrude.triangulate) as tried:
            data, issues = extrude.extrude(_shape(rings), self.params())
        self.assertEqual(tried.call_count, 2)
        self.assertEqual(issues, ["a cap with holes is left open: more than %d steps to triangulate the caps" %
                                  (one + one // 2), "2 more caps with holes left open: no steps left"])
        self.assertEqual(int((_mats(data) == extrude.TOP_ID).sum()), 8)

    def test_too_many_points_are_refused_before_any_is_made(self):
        knots = _knots([(k, k % 3, 0) for k in range(3000)], kind=shapes.CORNER)
        many = shapes.Shape(shapes.classids.LINE, (shapes.Spline(knots, False),), 100, False, False,
                            shapes.DEFAULT_RENDER, ())
        with mock.patch.object(extrude, "_polyline", side_effect=AssertionError("interpolated")):
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
