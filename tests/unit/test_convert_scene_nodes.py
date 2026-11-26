# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/scene/ on nodes: damaged input, curves, shear, a cancelled describe, mirrored
offsets, matrices, Look At and the mesh range, no Blender.

    python -I -m unittest discover tests
"""
import importlib
import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

_TESTS = "maxdrop_unit_tests"  # tests/unit as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_unit_tests.convert_scene_support import (  # noqa: E402 (after the loader)
    _PKG, _quad_strip, cfb, conv, geometry, numpy, patching, reader_scene, ROOT, shapes,
)


@unittest.skipIf(numpy is None, "numpy missing")
class DamagedInput(unittest.TestCase):
    def scene(self, name):
        cf = cfb.CompoundFile(os.path.join(ROOT, "tests", "fixtures", name + ".max"))
        self.addCleanup(cf.close)
        return reader_scene.Scene.from_file(cf)

    def test_refused_geometry_becomes_a_placeholder_with_an_issue(self):
        sc = self.scene("instances")
        real = conv.geometry.read_mesh

        def refuse(scene, i, check=None):
            raise geometry.GeometryError("object %d: refused" % i)

        conv.geometry.read_mesh = refuse
        try:
            desc = conv.describe(sc, 0.001)
        finally:
            conv.geometry.read_mesh = real
        self.assertEqual([n.kind for n in desc.nodes], [conv.EMPTY] * 5)
        self.assertEqual(sum(desc.placeholders.values()), 5)
        self.assertEqual(len(desc.meshes), 0)
        self.assertEqual(len(desc.issues), 2)  # once per base object: the shared one and the copy's
        self.assertTrue(all(r.startswith("geometry: ") for _n, r in desc.issues))

    def test_a_damaged_node_record_is_an_empty_and_its_children_are_still_placed(self):
        sc = self.scene("hierarchy")
        child = next(i for i in sc.node_indices if sc.node(i).name == "FixtureChild")
        sc._nodes.clear()
        real = sc.node

        def node(i):
            if i == child:
                raise reader_scene.ChunkError("damaged")
            return real(i)

        sc.node = node
        desc = conv.describe(sc, 1.0)
        by_index = {n.index: n for n in desc.nodes}
        self.assertEqual((by_index[child].kind, by_index[child].name), (conv.EMPTY, ""))
        self.assertIn((child, "node: damaged"), desc.issues)
        leaf = next(n for n in desc.nodes if n.name == "FixtureLeaf")
        self.assertEqual((leaf.parent, leaf.kind), (child, conv.MESH))

    def layered(self, parents=None, broken=()):
        """layers_flags with parent layers set by name and some layer records refused."""
        sc = self.scene("layers_flags")
        by_name = {sc.layer(i).name: i for i in sc.layer_indices}
        real = sc.layer

        def layer(i):
            if i in [by_name[b] for b in broken]:
                raise reader_scene.ChunkError("layer %d: refused" % i)
            la = real(i)
            parent = (parents or {}).get(la.name)
            if parent is None:
                return la
            return reader_scene.Layer(la.index, la.name, la.flags, la.render_flags, by_name[parent])

        sc.layer = layer
        return sc, by_name

    def test_a_parent_layer_without_nodes_is_kept_and_comes_first(self):
        sc, by_name = self.layered({"FixtureLayerB": "0"})
        desc = conv.describe(sc, 1.0)
        self.assertEqual([(la.name, la.parent) for la in desc.layers],
                         [("0", None), ("FixtureLayerA", None), ("FixtureLayerB", by_name["0"])])

    def test_a_parent_listed_later_is_moved_before_its_child(self):
        sc, by_name = self.layered({"FixtureLayerA": "FixtureLayerB"})
        desc = conv.describe(sc, 1.0)
        self.assertEqual([(la.name, la.parent) for la in desc.layers],
                         [("FixtureLayerB", None), ("FixtureLayerA", by_name["FixtureLayerB"])])

    def test_an_unreadable_layer_is_an_issue_and_its_nodes_have_none(self):
        sc, _by_name = self.layered(broken=("FixtureLayerB",))
        desc = conv.describe(sc, 1.0)
        self.assertEqual([la.name for la in desc.layers], ["FixtureLayerA"])
        lost = [n.name for n in desc.nodes if n.layer is None]
        self.assertEqual(sorted(lost), ["FixtureHidden", "FixtureNoRender"])
        layer_issues = [r for _n, r in desc.issues if r != conv.NO_RECEIVE]
        self.assertEqual(len(layer_issues), 2)
        self.assertTrue(all(r.startswith("layer: ") for r in layer_issues))

    def test_a_by_layer_node_without_a_readable_layer_renders_by_its_own_flags(self):
        """layers_render with FixtureNoRenderLayer's record refused and FixtureByLayerOwnOff's layer slot on an
        object that is not a layer (a slot past the objects is refused with the node, test_scene's test_damaged):
        no collection hides them from the render (build/collections.py), so their own flags must."""
        sc = self.scene("layers_render")
        by_name = {sc.layer(i).name: i for i in sc.layer_indices}
        real = sc.layer

        def layer(i):
            if i == by_name["FixtureNoRenderLayer"]:
                raise reader_scene.ChunkError("layer %d: refused" % i)
            return real(i)

        sc.layer = layer
        own_off = next(i for i in sc.node_indices if sc.node(i).name == "FixtureByLayerOwnOff")
        sc.node(own_off).refs[reader_scene.SLOT_LAYER] = own_off
        desc = conv.describe(sc, 1.0)
        got = {n.name: (n.layer, n.renderable, n.cast_shadows, n.receive_shadows) for n in desc.nodes
               if n.layer is None}
        self.assertEqual(got, {"FixtureByLayerNoRender": (None, True, True, True),
                               "FixtureByObjectOnNoRender": (None, True, True, True),
                               "FixtureByLayerOwnOff": (None, False, False, False)})
        lost = {by_name["FixtureNoRenderLayer"], by_name["FixtureOnLayer"]}
        self.assertFalse(lost & {la.index for la in desc.layers})
        by_index = {n.index: n.name for n in desc.nodes}
        self.assertEqual(sorted(by_index[i] for i, r in desc.issues if r.startswith("layer: ")),
                         ["FixtureByLayerNoRender", "FixtureByLayerOwnOff", "FixtureByObjectOnNoRender"])

    def test_unknown_controllers_are_counted_by_class(self):
        sc = self.scene("hierarchy")
        real = conv.controllers.Transforms

        class Fake(real):
            def local(self, i):
                m = super().local(i)
                node = self.scene.node(i)
                if not any(issue.node == i for issue in self.issues):
                    self.issues.append(conv.controllers.Issue(i, node.tm, None, None, conv.controllers.UNKNOWN_CLASS))
                return m

        conv.controllers.Transforms = Fake
        try:
            desc = conv.describe(sc, 1.0)
        finally:
            conv.controllers.Transforms = real
        self.assertEqual(dict(desc.unknown_controllers), {"Position/Rotation/Scale": len(desc.nodes)})


class Curves(unittest.TestCase):
    def _shape(self, knots, closed=False, **kw):
        render = shapes.DEFAULT_RENDER._replace(**kw)
        return shapes.Shape(shapes.classids.LINE, (shapes.Spline(tuple(knots), closed),), 6, True, False, render, ())

    def test_straight_segment_and_offset(self):
        """A segment of type line gets its handles on the chord; the offset and meters apply to every handle."""
        k = shapes.Knot
        knots = [k(shapes.BEZIER, shapes.LINE, (0, 0, 0), (0, -5, 0), (0, 5, 0)),
                 k(shapes.BEZIER, shapes.CURVE, (9, 0, 0), (9, 5, 0), (9, -5, 0)),
                 k(shapes.CORNER, shapes.LINE, (9, 9, 0), (9, 9, 0), (9, 9, 0))]
        offset = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (1, 2, 3, 1))
        cd, issues = conv.curve_description("k", "n", self._shape(knots), offset, 0.5)
        sp = cd.splines[0]
        self.assertEqual(issues, [])
        self.assertEqual(sp.points, [(0.5, 1, 1.5), (5, 1, 1.5), (5, 5.5, 1.5)])
        self.assertEqual(sp.right[0], (2, 1, 1.5))  # a third of the chord, not the stored (0, 5)
        self.assertEqual(sp.left[1], (3.5, 1, 1.5))
        self.assertEqual(sp.right[1], (5, -1.5, 1.5))  # a curve segment keeps its vector
        self.assertEqual(sp.right[2], (5, 5.5, 1.5))  # open: no segment after the last knot
        self.assertEqual((cd.resolution, cd.bevel_depth), (7, 0.0))

    def test_segment_material_ids(self):
        """A spline's material IDs are its segments': the last knot of an open spline starts none, a closed one's
        does; distinct, in segment order, the first one the spline's; a spline without a segment its knot's."""
        def knots(*ids):
            return [shapes.Knot(shapes.CORNER, shapes.LINE, (float(i), 0, 0), (float(i), 0, 0), (float(i), 0, 0), m)
                    for i, m in enumerate(ids)]
        self.assertEqual(conv.segment_ids(knots(1, 1, 5), False), (1,))
        self.assertEqual(conv.segment_ids(knots(1, 1, 5), True), (1, 5))
        self.assertEqual(conv.segment_ids(knots(2, 0, 0, 2, 3), False), (2, 0))
        self.assertEqual(conv.segment_ids(knots(4), False), (4,))
        self.assertEqual(conv.segment_ids(knots(4), True), (4,))
        cd, _issues = conv.curve_description("k", "n", self._shape(knots(3, 1, 3, 9)), None, 1.0)
        self.assertEqual((cd.splines[0].material, cd.splines[0].material_ids), (3, (3, 1)))

    def test_closing_straight_segment_and_bevel(self):
        k = shapes.Knot
        knots = [k(shapes.CORNER, shapes.CURVE, (0, 0, 0), (0, 0, 0), (0, 0, 0)),
                 k(shapes.CORNER, shapes.LINE, (3, 0, 0), (3, 0, 0), (3, 0, 0))]
        cd, issues = conv.curve_description("k", "n", self._shape(knots, closed=True, renderable=True, thickness=4.0,
                                                                  sides=3), None, 1.0)
        self.assertEqual((cd.splines[0].right[1], cd.splines[0].left[0]), ((2, 0, 0), (1, 0, 0)))
        self.assertEqual((cd.bevel_depth, cd.bevel_resolution, cd.section), (2.0, 0, None))
        self.assertEqual(issues, [])

    def test_rectangular_section_off_the_plane(self):
        """A section on a curve that is not flat in XY is drawn, with an issue; width or length 0 draws none."""
        k = shapes.Knot

        def section(z, **kw):
            knots = [k(shapes.CORNER, shapes.LINE, (0, 0, 0), (0, 0, 0), (0, 0, 0)),
                     k(shapes.CORNER, shapes.LINE, (10, 0, z), (10, 0, z), (10, 0, z))]
            render = dict(renderable=True, rectangular=True, width=4.0, length=1.0)
            render.update(kw)
            return conv.curve_description("k", "n", self._shape(knots, **render), None, 1.0)

        cd, issues = section(0)
        self.assertEqual((len(cd.section), issues, cd.bevel_depth), (4, [], 0.0))
        cd, issues = section(5)
        self.assertEqual((len(cd.section), len(issues)), (4, 1))
        self.assertIn("not flat", issues[0])
        cd, issues = section(0, width=0.0)
        self.assertEqual((cd.section, cd.bevel_depth, len(issues)), (None, 0.0, 1))
        self.assertIn("not drawn", issues[0])
        cd, issues = section(0, renderable=False)
        self.assertEqual((cd.section, issues), (None, []))

    @staticmethod
    def _ngon(radius, sides, corner=0.0):
        """The splines reader.shapes draws for an NGon (inscribed, not circular)."""
        splines = shapes._ngon(shapes._Params({0: radius, 1: sides, 2: 0, 3: corner, 4: 0}), [])
        return shapes.Shape(shapes.classids.NGON, tuple(splines), 6, True, False, shapes.DEFAULT_RENDER, ())

    def test_ngon_past_single_precision_is_refused(self):
        """An NGon of radius 1e308: 3 sides gives inf and NaN, 6 sides finite doubles past the largest float32,
        a corner radius of 1e308 the same; each is refused (Blender holds curve points in single precision). The
        same NGon at radius 10 is a curve."""
        for sides, radius, corner in ((3, 1e308, 0.0), (6, 1e308, 0.0), (6, 10.0, 1e308)):
            with self.subTest(sides=sides, radius=radius, corner=corner):
                with self.assertRaises(conv.CurveError) as caught:
                    conv.curve_description("k", "n", self._ngon(radius, sides, corner), None, 1.0)
                self.assertIn("single precision", str(caught.exception))
        cd, issues = conv.curve_description("k", "n", self._ngon(10.0, 3), None, 1.0)
        self.assertEqual((len(cd.splines[0].points), issues), (3, []))

    def test_points_past_single_precision_after_offset_and_meters(self):
        """The range is checked on what Blender gets: after the offset and meters, the handles too."""
        k = shapes.Knot

        def line(x, handle=0.0):
            return self._shape([k(shapes.BEZIER, shapes.CURVE, (0, 0, 0), (0, 0, 0), (handle, 0, 0)),
                                k(shapes.BEZIER, shapes.CURVE, (x, 0, 0), (x, 0, 0), (x, 0, 0))])

        cd, _issues = conv.curve_description("k", "n", line(1e30), None, 1.0)
        self.assertEqual(cd.splines[0].points[1], (1e30, 0, 0))
        for shape, meters, offset in ((line(1e39), 1.0, None), (line(1e36), 1000.0, None),
                                      (line(1.0, handle=-1e39), 1.0, None),
                                      (line(1.0), 1.0, ((1e39, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))):
            with self.subTest(meters=meters, offset=offset is not None), self.assertRaises(conv.CurveError):
                conv.curve_description("k", "n", shape, offset, meters)

    def test_refused_curve_key_is_named_once(self):
        """Two nodes sharing a curve key that does not fit: both EMPTY, one issue (on the first), described once."""
        desc = types.SimpleNamespace(curves={}, issues=[])
        shape_of, unbuilt = {7: self._ngon(1e308, 6)}, set()
        with patching.patch_all(conv, "curve_description", wraps=conv.curve_description) as described:
            got = [conv._curve(None, desc, shape_of, unbuilt, 7, node, "n", conv.controllers.IDENTITY, 1.0)
                   for node in (3, 4)]
        self.assertEqual(got, [(conv.EMPTY, None)] * 2)
        self.assertEqual((desc.curves, len(desc.issues), desc.issues[0][0], described.call_count), ({}, 1, 3, 1))
        self.assertTrue(desc.issues[0][1].startswith("shape: not built: "))

    def test_section_or_bevel_past_single_precision_is_not_drawn(self):
        """A rectangular section of width 1e308 at a large meters factor, or a round bevel of thickness 1e308, is
        not drawn (an issue); the curve is."""
        k = shapes.Knot
        knots = [k(shapes.CORNER, shapes.LINE, (0, 0, 0), (0, 0, 0), (0, 0, 0)),
                 k(shapes.CORNER, shapes.LINE, (10, 0, 0), (10, 0, 0), (10, 0, 0))]
        cd, issues = conv.curve_description("k", "n", self._shape(knots, renderable=True, rectangular=True,
                                                                  width=1e308, length=1.0), None, 1000.0)
        self.assertEqual((cd.section, cd.bevel_depth, len(issues)), (None, 0.0, 1))
        self.assertIn("single precision", issues[0])
        self.assertEqual(cd.splines[0].points[1], (10000.0, 0, 0))
        cd, issues = conv.curve_description("k", "n", self._shape(knots, renderable=True, thickness=1e308), None,
                                            1000.0)
        self.assertEqual((cd.section, cd.bevel_depth, len(issues)), (None, 0.0, 1))
        self.assertIn("single precision", issues[0])

    @unittest.skipIf(numpy is None, "numpy missing")  # shapes.max has a box: its mesh is read with numpy
    def test_refused_curve_is_a_placeholder_named_once(self):
        """A curve refused for its range makes its nodes placeholders, its issue named on the first node of each
        curve key only."""
        path = os.path.join(ROOT, "tests", "fixtures", "shapes.max")
        fresh = conv.read(path)
        with patching.patch_all(conv, "curve_description", side_effect=conv.CurveError("its points do not fit")):
            desc = conv.read(path)
        self.assertEqual(desc.curves, {})
        users = sum(len(cd.users) for cd in fresh.curves.values())
        self.assertEqual(sum(desc.placeholders.values()) - sum(fresh.placeholders.values()), users)
        refused = [reason for _i, reason in desc.issues if reason == "shape: not built: its points do not fit"]
        self.assertEqual(len(refused), len(fresh.curves))

    @unittest.skipIf(numpy is None, "numpy missing")  # shapes.max has a box: its mesh is read with numpy
    def test_refused_shape_is_a_placeholder_with_an_issue(self):
        path = os.path.join(ROOT, "tests", "fixtures", "shapes.max")
        with mock.patch.object(shapes, "read_shape", side_effect=shapes.ShapeError("object 1 (Line): damaged")):
            desc = conv.read(path)
        self.assertEqual(desc.curves, {})
        self.assertEqual(sum(desc.placeholders.values()), 13)
        self.assertEqual(len(desc.issues), 13)
        self.assertTrue(all(reason.startswith("shape: ") for _i, reason in desc.issues))


class Shear(unittest.TestCase):
    def test_rotation_and_axis_scale_are_not_shear(self):
        c, s = 0.6, 0.8
        self.assertFalse(conv.sheared(((2 * c, 2 * s, 0, 0), (-3 * s, 3 * c, 0, 0), (0, 0, -1, 0), (5, 6, 7, 1))))

    def test_shear_is_found(self):
        self.assertTrue(conv.sheared(((1, 0, 0, 0), (0.5, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))))

    @unittest.skipIf(numpy is None, "numpy missing")
    def test_a_sheared_node_is_flagged_not_reported(self):
        sc = DamagedInput.scene(self, "hierarchy")
        real = conv.controllers.Transforms
        target = sc.walk()[1]

        class Fake(real):
            def local(self, i):
                m = super().local(i)
                if i != target:
                    return m
                return ((m[0][0], m[0][1], m[0][2], 0.0), (m[1][0] + 0.5 * m[0][0], m[1][1] + 0.5 * m[0][1],
                                                           m[1][2] + 0.5 * m[0][2], 0.0), m[2], m[3])

        conv.controllers.Transforms = Fake
        try:
            desc = conv.describe(sc, 1.0)
        finally:
            conv.controllers.Transforms = real
        self.assertEqual([n.index for n in desc.nodes if n.sheared], [target])
        self.assertFalse([r for _n, r in desc.issues if "shear" in r], desc.issues)


@unittest.skipIf(numpy is None, "numpy missing")
class DescribeCancel(unittest.TestCase):
    """describe(cancel=): the check is asked once per node of each walk, and inside a large mesh; the first True
    ends it with Cancelled at once (the modal import's Esc during reading), keeping nothing; the Scene stays
    usable."""

    @staticmethod
    def tripping(after):
        calls = []

        def cancel():
            calls.append(None)
            return len(calls) > after
        return cancel, calls

    @staticmethod
    def summary(desc):
        return [(n.index, n.name, n.kind, n.mesh) for n in desc.nodes], sorted(desc.meshes, key=repr)

    def test_a_tripped_check_raises_at_once_and_keeps_nothing(self):
        import gc

        def alive():  # other tests may keep descriptions of their own
            gc.collect()
            return {id(o) for o in gc.get_objects() if isinstance(o, conv.SceneDescription)}

        sc = DamagedInput.scene(self, "hierarchy")
        before = alive()
        nodes = len(sc.walk())
        self.assertGreater(nodes, 3)
        for after in (0, 2, nodes, nodes + 2):  # in the first walk, at its end, in the second walk
            cancel, calls = self.tripping(after)
            with self.assertRaises(conv.Cancelled):
                conv.describe(sc, 1.0, cancel=cancel)
            self.assertEqual(len(calls), after + 1)
        self.assertEqual(alive() - before, set())
        self.assertFalse(issubclass(conv.Cancelled, ValueError))  # ops reports a ValueError as an unreadable file

    def test_a_check_that_never_trips_changes_nothing(self):
        sc = DamagedInput.scene(self, "hierarchy")
        fresh = self.summary(conv.describe(DamagedInput.scene(self, "hierarchy"), 1.0))
        cancel, calls = self.tripping(1)
        with self.assertRaises(conv.Cancelled):
            conv.describe(sc, 1.0, cancel=cancel)
        cancel, calls = self.tripping(10 ** 9)
        self.assertEqual(self.summary(conv.describe(sc, 1.0, cancel=cancel)), fresh)
        self.assertEqual(len(calls), 2 * len(sc.walk()))
        self.assertEqual(self.summary(conv.describe(sc, 1.0)), fresh)

    def test_the_check_is_asked_inside_a_large_mesh(self):
        """With reader.geometry.CHECK_EVERY at 1 every mesh is large: the check is also asked inside a node, in the
        Editable Poly's record loops and between the passes of mesh_description (an extrusion's too); tripped at any
        of those calls, describe ends with Cancelled, keeping nothing."""
        import gc

        def alive():
            gc.collect()
            return {id(o) for o in gc.get_objects() if isinstance(o, conv.SceneDescription)}

        for name in ("box_poly_standard", "extrude"):
            sc = DamagedInput.scene(self, name)
            nodes = len(sc.walk())
            fresh = self.summary(conv.describe(DamagedInput.scene(self, name), 1.0))
            cancel, calls = self.tripping(10 ** 9)
            conv.describe(sc, 1.0, cancel=cancel)
            self.assertEqual(len(calls), 2 * nodes)  # a small mesh: once per node and walk
            before = alive()
            real_read, in_reader = geometry.read_mesh, []

            def reading(scene, i, check=None):  # counts the calls the reader itself makes
                def counted():
                    in_reader.append(None)
                    check()
                return real_read(scene, i, None if check is None else counted)

            with mock.patch.object(geometry, "CHECK_EVERY", 1), mock.patch.object(geometry, "read_mesh", reading):
                cancel, calls = self.tripping(10 ** 9)
                self.assertEqual(self.summary(conv.describe(sc, 1.0, cancel=cancel)), fresh)
                total = len(calls)
                self.assertGreater(total, 2 * nodes + len(in_reader), name)  # mesh_description asks it too
                if name == "box_poly_standard":  # an Editable Poly: its record loops ask it
                    self.assertGreater(len(in_reader), 0)
                for after in range(nodes, total):  # from the second walk's first node to the last call
                    cancel, calls = self.tripping(after)
                    with self.subTest(fixture=name, trip=after):
                        with self.assertRaises(conv.Cancelled):
                            conv.describe(sc, 1.0, cancel=cancel)
                        self.assertEqual(len(calls), after + 1)
            self.assertEqual(alive() - before, set())
            self.assertEqual(self.summary(conv.describe(sc, 1.0)), fresh)


@unittest.skipIf(numpy is None, "numpy missing")
class MirroredOffset(unittest.TestCase):
    def data(self):
        lv, starts, _totals, groups = _quad_strip([1, 2])
        uv = geometry.MapChannel(1, numpy.arange(24, dtype=numpy.float32).reshape(8, 3),
                                 numpy.arange(8, dtype=numpy.int32))
        return geometry.MeshData(numpy.zeros((6, 3), dtype=numpy.float32), numpy.asarray(lv, dtype=numpy.int32),
                                 numpy.asarray(starts, dtype=numpy.int32), numpy.asarray(groups, dtype=numpy.uint32),
                                 numpy.zeros(2, dtype=numpy.uint16), {1: uv})

    def test_negative_determinant_reverses_every_polygon_with_its_uvs(self):
        mirror = ((-1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (2.0, 0.0, 0.0, 1.0))
        md = conv.mesh_description((0, mirror), "m", self.data(), mirror, 0.5)
        self.assertEqual(md.loop_vertices.tolist(), [3, 4, 1, 0, 4, 5, 2, 1])
        self.assertEqual(md.uv_layers[0][1][:, 0].tolist(), [9.0, 6.0, 3.0, 0.0, 21.0, 18.0, 15.0, 12.0])
        self.assertEqual(md.positions[0].tolist(), [1.0, 0.0, 0.0])  # (0 * -1 + 2) * 0.5
        self.assertEqual([tuple(e) for e in md.sharp_edges.tolist()], [(1, 4)])

    def test_positive_offset_keeps_the_loop_order(self):
        shift = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 3.0, 1.0))
        md = conv.mesh_description((0, shift), "m", self.data(), shift, 1.0)
        self.assertEqual(md.loop_vertices.tolist(), [0, 1, 4, 3, 1, 2, 5, 4])
        self.assertEqual(md.positions[:, 2].tolist(), [3.0] * 6)


class Matrices(unittest.TestCase):
    def test_reader_matrix_becomes_blender_convention_with_scaled_translation(self):
        m = ((0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 2.0, 0.0), (10.0, 20.0, 30.0, 1.0))
        self.assertEqual(conv.blender_matrix(m, 0.01),
                         ((0.0, -1.0, 0.0, 0.1), (1.0, 0.0, 0.0, 0.2), (0.0, 0.0, 2.0, 0.3), (0.0, 0.0, 0.0, 1.0)))

    def test_determinant_sign(self):
        self.assertGreater(conv.determinant3(conv.blender_matrix(((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0),
                                                                  (0, 0, 0, 1)))), 0)
        self.assertLess(conv.determinant3(((-1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))), 0)

    def test_meters_must_be_positive(self):
        for bad in (0.0, -1.0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                conv.describe(None, bad)


class LookAt(unittest.TestCase):
    def test_track_to_of_each_look_at(self):
        look_at = importlib.import_module(_PKG + ".reader.controllers").LookAt
        describe = conv.look_at_description
        self.assertIsNone(describe(None))
        self.assertIsNone(describe(look_at(None, 2, False, 0.0, False)))  # aims at the origin: nothing to track
        self.assertEqual(describe(look_at(7, 2, False, 0.0, False)),
                         conv.LookAtDescription(7, "TRACK_NEGATIVE_Z", "UP_Y", False, None))
        self.assertEqual(describe(look_at(7, 2, True, 0.0, True)),
                         conv.LookAtDescription(7, "TRACK_Z", "UP_Y", True, None))
        self.assertEqual(describe(look_at(7, 0, False, 0.0, False)).track, "TRACK_NEGATIVE_X")
        self.assertEqual(describe(look_at(7, 0, True, 0.0, False)).track, "TRACK_X")
        for look, reason in ((look_at(7, 1, False, 0.0, False), conv.NO_TRACK_AXIS),
                             (look_at(7, 1, True, 0.0, False), conv.NO_TRACK_AXIS),
                             (look_at(7, 2, False, 0.1, False), conv.NO_TRACK_ROLL)):
            self.assertEqual(describe(look), conv.LookAtDescription(7, None, None, False, reason))

    @unittest.skipIf(numpy is None, "numpy missing")  # lookat.max has boxes: their meshes are built with numpy
    def test_lookat_fixture(self):
        desc = conv.read(os.path.join(ROOT, "tests", "fixtures", "lookat.max"))
        index = {n.index: n.name for n in desc.nodes}
        looks = {n.name: (index[n.look_at.target], n.look_at.track, n.look_at.up, n.look_at.target_z,
                          n.look_at.reason) for n in desc.nodes if n.look_at is not None}
        self.assertEqual(looks, {  # the boxes with a LookAt Constraint have none
            "FixtureCam": ("FixtureCam.Target", "TRACK_NEGATIVE_Z", "UP_Y", False, None),
            "FixtureCamRoll": ("FixtureCamRoll.Target", None, None, False, conv.NO_TRACK_ROLL),
            "FixtureCamDown": ("FixtureCamDown.Target", "TRACK_NEGATIVE_Z", "UP_Y", False, None),
            "FixtureSpot": ("FixtureSpot.Target", "TRACK_NEGATIVE_Z", "UP_Y", False, None),
            "FixtureCamChild": ("FixtureCamChild.Target", "TRACK_NEGATIVE_Z", "UP_Y", False, None),
            "FixtureLooker": ("FixtureAim", "TRACK_X", "UP_Y", True, None),
            "FixtureLookerY": ("FixtureAim", None, None, False, conv.NO_TRACK_AXIS)})
        targets = [n for n in desc.nodes if n.name.endswith(".Target")]
        self.assertEqual([(n.kind, n.class_name) for n in targets], [(conv.EMPTY, "Target")] * 5)


@unittest.skipIf(numpy is None, "numpy missing")
class MeshRange(unittest.TestCase):
    """Stored mesh positions past single precision (offset and meters applied), inf or NaN: the mesh is refused,
    its nodes placeholders with an issue, as a curve or a primitive; UVs that are not numbers become 0."""

    @staticmethod
    def data(corner=(1.0, 0.0, 0.0), uv=None):
        """A MeshData of one triangle, its second vertex at corner (float32, as reader.geometry stores it)."""
        positions = numpy.asarray([(0.0, 0.0, 0.0), corner, (0.0, 1.0, 0.0)], dtype=numpy.float32)
        uvw = numpy.zeros((3, 3), dtype=numpy.float32) if uv is None else numpy.asarray(uv, dtype=numpy.float32)
        maps = {1: geometry.MapChannel(1, uvw, numpy.arange(3, dtype=numpy.int32))}
        return geometry.MeshData(positions, numpy.arange(3, dtype=numpy.int32), numpy.zeros(1, dtype=numpy.int32),
                                 numpy.ones(1, dtype=numpy.uint32), numpy.zeros(1, dtype=numpy.uint16), maps)

    def test_positions_that_do_not_fit_are_refused(self):
        big = ((1e39, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
        for corner, offset, meters in (((float("nan"), 0.0, 0.0), None, 1.0), ((float("inf"), 0.0, 0.0), None, 1.0),
                                       ((1e36, 0.0, 0.0), None, 1000.0), ((1.0, 0.0, 0.0), big, 1.0)):
            with self.subTest(corner=corner, meters=meters, offset=offset is not None):
                with self.assertRaises(conv.MeshError) as caught:
                    conv.mesh_description((0, offset), "m", self.data(corner), offset, meters)
                self.assertIn("single precision", str(caught.exception))
        md = conv.mesh_description((0, None), "m", self.data((1e30, 0.0, 0.0)), None, 1.0)
        self.assertEqual(md.positions[1, 0], numpy.float32(1e30))
        self.assertTrue(numpy.isfinite(md.positions).all())

    def test_uvs_that_are_not_numbers_become_zero(self):
        uv = [(0.25, float("nan"), 7.0), (float("inf"), 0.5, float("nan")), (1.0, 1.0, 0.0)]
        data = self.data(uv=uv)
        md = conv.mesh_description((0, None), "m", data, None, 1.0)
        self.assertEqual(md.uv_layers[0][1].tolist(), [[0.25, 0.0], [0.0, 0.5], [1.0, 1.0]])
        self.assertEqual(md.zeroed_uvs, 2)  # the w coordinate is dropped, not counted
        self.assertTrue(numpy.isnan(data.maps[1].uvw[0, 1]))  # the reader's array is not written
        self.assertEqual(conv.mesh_description((0, None), "m", self.data(), None, 1.0).zeroed_uvs, 0)

    def scene(self, name):
        cf = cfb.CompoundFile(os.path.join(ROOT, "tests", "fixtures", name + ".max"))
        self.addCleanup(cf.close)
        return reader_scene.Scene.from_file(cf)

    def described(self, name, meters, corner, uv=None):
        """The fixture described with every stored mesh replaced by self.data(corner, uv)."""
        sc = self.scene(name)
        with mock.patch.object(conv.geometry, "read_mesh", lambda scene, i, check=None: self.data(corner, uv)):
            return conv.describe(sc, meters)

    def test_a_refused_mesh_is_a_placeholder_named_once_per_key(self):
        """instances: four nodes share one base object, a copy has its own; every node an EMPTY placeholder, one
        issue per mesh key (the shared one and the copy's), no mesh, no modifier or UV issue."""
        for corner, meters in (((float("nan"), 0.0, 0.0), 1.0), ((1e36, 0.0, 0.0), 1000.0)):
            with self.subTest(corner=corner, meters=meters):
                desc = self.described("instances", meters, corner)
                self.assertEqual([n.kind for n in desc.nodes], [conv.EMPTY] * 5)
                self.assertEqual(sum(desc.placeholders.values()), 5)
                self.assertEqual(desc.meshes, {})
                self.assertEqual(len(desc.issues), 2)
                self.assertTrue(all(r.startswith("geometry: not built: ") and "single precision" in r
                                    for _n, r in desc.issues), desc.issues)
        desc = self.described("instances", 1.0, (1e30, 0.0, 0.0))
        self.assertEqual([n.kind for n in desc.nodes], [conv.MESH] * 5)
        self.assertEqual(desc.issues, [])

    def test_zeroed_uvs_are_named_once_per_key(self):
        desc = self.described("instances", 1.0, (1.0, 0.0, 0.0), uv=[(float("nan"), 0, 0), (0, 0, 0), (0, 0, 0)])
        self.assertEqual([n.kind for n in desc.nodes], [conv.MESH] * 5)
        self.assertEqual([r for _n, r in desc.issues], ["geometry: 1 UV coordinates that are not numbers set to 0"]
                         * 2)
        desc = self.described("vray_mesh_light", 0.001, (1.0, 0.0, 0.0), uv=[(float("nan"), 0, 0), (0, 0, 0),
                                                                             (0, 0, 0)])
        zeroed = [i for i, r in desc.issues if r == "geometry: 1 UV coordinates that are not numbers set to 0"]
        self.assertEqual(len(zeroed), len(desc.meshes))  # the mesh and the three emitters, once each
        self.assertEqual(sorted(zeroed), sorted(md.users[0] for md in desc.meshes.values()))

    def test_a_mesh_light_whose_mesh_does_not_fit_is_not_built(self):
        """vray_mesh_light at meters 1000 with every mesh at 1e36: the mesh light's mesh objects are refused
        (_mesh_of), the emitters not built, an issue on each; describe does not raise."""
        desc = self.described("vray_mesh_light", 1000.0, (1e36, 0.0, 0.0))
        self.assertEqual(desc.meshes, {})
        self.assertEqual(desc.emitters, {})
        self.assertNotIn(conv.MESH, [n.kind for n in desc.nodes])
        unbuilt = [r for _n, r in desc.issues if r.startswith("light: not built: its mesh cannot be read: ")]
        self.assertEqual(len(unbuilt), 3)
        self.assertTrue(all("single precision" in r for r in unbuilt), unbuilt)

    def test_a_mesh_light_refused_after_its_offset_is_not_built(self):
        """A refusal raised once the light node's offset is applied (in _emitter) costs the emitter, not the
        import: no mesh or emitter written, a light issue on each of its nodes."""
        sc = self.scene("vray_mesh_light")
        real = conv.mesh_description

        def refuse(key, *args, **kwargs):
            if key[0] == conv.EMITTER:
                raise conv.MeshError("its points do not fit single precision")
            return real(key, *args, **kwargs)

        with patching.patch_all(conv, "mesh_description", refuse):
            desc = conv.describe(sc, 0.001)
        self.assertEqual(desc.emitters, {})
        self.assertFalse(any(k[0] == conv.EMITTER for k in desc.meshes if isinstance(k, tuple)))
        emitters = [n for n in desc.nodes if n.name.startswith("FixtureEmitter") and n.name != "FixtureEmitterSource"]
        self.assertEqual([n.kind for n in emitters], [conv.EMPTY] * 4)
        refused = [r for _n, r in desc.issues if r == "light: not built: its points do not fit single precision"]
        self.assertEqual(len(refused), 3)

    def test_a_refused_mesh_converts_no_modifier(self):
        """stack_convert with FixtureTurboOne's mesh refused: that node a placeholder without converted modifiers or
        their issues, its TurboSmooth taken back from the modifiers whose issues were named (told); the others
        as before."""
        sc = self.scene("stack_convert")
        fresh = conv.describe(sc, 0.001)
        turbo = next(n for n in fresh.nodes if n.name == "FixtureTurboOne")
        refused_base = turbo.mesh[0]
        real = conv.geometry.read_mesh

        def read(scene, i, check=None):
            return self.data((float("nan"), 0.0, 0.0)) if i == refused_base else real(scene, i, check)

        with mock.patch.object(conv.geometry, "read_mesh", read), \
                patching.patch_all(conv, "_converted", wraps=conv._converted) as converted:
            desc = conv.describe(self.scene("stack_convert"), 0.001)
        told = converted.call_args_list[0].args[4]
        node = next(n for n in desc.nodes if n.name == "FixtureTurboOne")
        self.assertEqual((node.kind, node.converted, node.applied), (conv.EMPTY, (), ()))
        self.assertNotIn(turbo.converted[0].index, told)
        self.assertTrue(all(m.index in told for n in fresh.nodes if n.name != "FixtureTurboOne"
                            for m in n.converted))
        self.assertEqual([r for i, r in desc.issues if i == node.index],
                         ["geometry: not built: its points do not fit single precision (Blender's meshes hold no "
                          "larger value)"])
        others = [(n.name, n.kind, n.converted) for n in desc.nodes if n.name != "FixtureTurboOne"]
        self.assertEqual(others, [(n.name, n.kind, n.converted) for n in fresh.nodes if n.name != "FixtureTurboOne"])

    def test_a_refused_extrusion_falls_back_to_its_curve(self):
        """extrude with every extruded mesh refused: each extruded node a curve (as when its Extrude cannot be
        read), one issue per mesh key before its maps."""
        path = os.path.join(ROOT, "tests", "fixtures", "extrude.max")
        fresh = conv.read(path)
        extruded = {n.index: n.mesh[:3] for n in fresh.nodes if n.kind == conv.MESH and "Extrude" in n.applied}
        self.assertTrue(extruded)
        with patching.patch_all(conv, "_positions", side_effect=conv.MeshError("its points do not fit")):
            desc = conv.read(path)
        self.assertEqual({n.kind for n in desc.nodes if n.index in extruded}, {conv.CURVE})
        refused = [i for i, r in desc.issues if r == "extrude: not made: its points do not fit"]
        self.assertEqual(len(refused), len(set(extruded.values())))
        self.assertTrue(set(refused) <= set(extruded))

    def test_an_offset_past_single_precision_refuses_that_node_only(self):
        """instances with FixtureInstance02's object offset scaled by 1e42 (its mesh key apart): that node a
        placeholder with one issue, the others meshes as before."""
        sc = self.scene("instances")
        target = next(i for i in sc.node_indices if sc.node(i).name == "FixtureInstance02")
        big = ((1e42, 0, 0, 0), (0, 1e42, 0, 0), (0, 0, 1e42, 0), (0, 0, 0, 1))
        real = conv._offset
        with patching.patch_all(conv, "_offset", lambda t, i: big if i == target else real(t, i)):
            desc = conv.describe(sc, 0.001)
        self.assertEqual([(n.name, n.kind) for n in desc.nodes],
                         [(n, conv.EMPTY if n == "FixtureInstance02" else conv.MESH) for n in
                          ("FixtureSource", "FixtureInstance01", "FixtureInstance02", "FixtureInstance03",
                           "FixtureCopy")])
        self.assertEqual([(i, r.split(":")[0]) for i, r in desc.issues], [(target, "geometry")])
        self.assertEqual(len(desc.meshes), 2)

    def test_a_refused_emitter_is_described_once_per_offset(self):
        """A refusal raised once the light node's offset is applied is remembered per light and offset: a second
        node of the light (FixtureEmitter walked twice) is not described again, its issue named on both."""
        sc = self.scene("vray_mesh_light")
        light = next(i for i in sc.node_indices if sc.node(i).name == "FixtureEmitter")
        order = sc.walk()
        sc.walk = lambda: list(order) + [light]
        real, calls = conv.mesh_description, []

        def refuse(key, *args, **kwargs):
            if key[0] == conv.EMITTER:
                calls.append(key)
                raise conv.MeshError("its points do not fit single precision")
            return real(key, *args, **kwargs)

        with patching.patch_all(conv, "mesh_description", refuse):
            desc = conv.describe(sc, 0.001)
        self.assertEqual(len(calls), len(set(calls)))  # each light and offset described once
        self.assertEqual([r for i, r in desc.issues if i == light],
                         ["light: not built: its points do not fit single precision"] * 2)


if __name__ == "__main__":
    unittest.main()
