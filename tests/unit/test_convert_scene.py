# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/scene.py, the scene description: no Blender. The smoothing-group rule, the loop reversal
of a mirrored object offset, and every committed fixture against its 3ds Max oracle (order, parents, world
matrices, world bounding boxes, counts, shared meshes, units) and its authoring script (UV channels, smoothing
groups), the shapes' curves against the oracle's knots and segment midpoints.

    python -I -m unittest discover tests
"""
import glob
import importlib
import json
import os
import sys
import types
import unittest
from unittest import mock

try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
MATRIX_TOLERANCE = 1e-4  # file units, per element (the oracle prints 6 significant digits)
BBOX_TOLERANCE = 1e-3

# A package named apart from the add-on whose path is maxdrop/: convert's relative imports of ..reader resolve,
# and maxdrop/__init__.py (which imports bpy) never runs.
_PKG = "maxdrop_convert_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
conv = importlib.import_module(_PKG + ".convert.scene")
geometry = importlib.import_module(_PKG + ".reader.geometry")
cfb = importlib.import_module(_PKG + ".reader.cfb")
reader_scene = importlib.import_module(_PKG + ".reader.scene")
shapes = importlib.import_module(_PKG + ".reader.shapes")

# From the fixture scripts (tools/fixtures/*.ms: mapcoords:true gives channel 1); the oracle has no map channels or
# smoothing groups.
UV_LAYERS = {
    "box_poly_standard": ["UVMap"],
    "corona_layered": ["UVMap"],
    "corona_legacy": ["UVMap"],
    "corona_light": ["UVMap"],
    "corona_maps": ["UVMap"],
    "corona_physical": ["UVMap"],
    "editable_mesh": ["UVMap"],
    # per mesh (named after its first node): Extrude makes channel 1 only with Generate Mapping Coords.
    "extrude": {"FixtureExtRect": ["UVMap"], "FixtureExtAdaptive": ["UVMap"]},
    "gamma_swatches": ["UVMap"],
    "hierarchy": [],
    "instances": ["UVMap"],
    "layers_flags": [],
    "modifier_pivot": ["UVMap"],  # the base mesh's channel: the UVW Map modifier is not applied
    "multi_uv": ["UVMap", "UVChannel_2", "UVChannel_3"],
    "shapes": ["UVMap"],  # FixtureBox; the shapes are curves
    "stack_basic": ["UVMap"],  # the base meshes' channel: no modifier is applied
    "standard_physical": ["UVMap"],
    "texmap_rules": ["UVMap"],
    "units_cm": ["UVMap"],
    "units_in": ["UVMap"],
    "units_mm": ["UVMap"],
    "vray_basic": ["UVMap"],
    "vray_maps": ["UVMap"],
    "vray_texmaps": ["UVMap"],
    "vray_wrappers": ["UVMap"],
}
SHARP_EDGES_POLY_BOX = 12  # one smoothing group per side: every edge of the box
SHARP_EDGES_EDITABLE_MESH = 8  # group 1 on top and bottom, 2 on the sides: the rims of top and bottom
SHARP_EDGES_TALL_BOX = 24  # modifier_pivot's four height segments: 4 x 4 vertical side edges and both rims
# extrude: the vertical edges at corner knots (one per level) and both rims of every capped outline
SHARP_EDGES_EXTRUDE = {"FixtureExtRect": 4 * 2 + 8, "FixtureExtL": 6 + 12, "FixtureExtHole": 4 + 8 + 56,
                       "FixtureExtIsland": 12 + 24, "FixtureExtOpen": 0, "FixtureExtMirror": 8 + 64,
                       "FixtureExtAdaptive": 256}


def _oracle(path):
    with open(path[:-4] + ".oracle.json", encoding="utf-8") as f:
        return json.load(f)


def _name(path):
    return os.path.splitext(os.path.basename(path))[0]


def _world_points(node, md):
    m = numpy.asarray(node.world, dtype=numpy.float64)
    return numpy.asarray(md.positions, dtype=numpy.float64) @ m[:3, :3].T + m[:3, 3]


def _quad_strip(groups):
    """Two quads sharing the edge (1, 4): 0-1-4-3 and 1-2-5-4."""
    return ([0, 1, 4, 3, 1, 2, 5, 4], [0, 4], [4, 4], groups)


@unittest.skipIf(numpy is None, "numpy missing")
class SharpEdges(unittest.TestCase):
    def pairs(self, groups):
        return [tuple(int(v) for v in e) for e in conv.sharp_edges(*_quad_strip(groups))]

    def test_a_shared_group_keeps_the_edge_smooth(self):
        self.assertEqual(self.pairs([1, 1]), [])
        self.assertEqual(self.pairs([3, 6]), [])

    def test_no_shared_group_makes_the_shared_edge_sharp(self):
        self.assertEqual(self.pairs([1, 2]), [(1, 4)])

    def test_faces_without_a_group_meet_at_a_sharp_edge(self):
        self.assertEqual(self.pairs([0, 0]), [(1, 4)])
        self.assertEqual(self.pairs([0, 1]), [(1, 4)])

    def test_three_faces_on_one_edge(self):
        lv = [0, 1, 2, 1, 0, 3, 0, 1, 4]
        starts, totals = [0, 3, 6], [3, 3, 3]
        self.assertEqual([tuple(e) for e in conv.sharp_edges(lv, starts, totals, [1, 1, 1]).tolist()], [])
        self.assertEqual([tuple(e) for e in conv.sharp_edges(lv, starts, totals, [1, 1, 2]).tolist()], [(0, 1)])

    def test_empty_mesh(self):
        self.assertEqual(conv.sharp_edges([], [], [], []).shape, (0, 2))


@unittest.skipIf(numpy is None, "numpy missing")
class HostileEdges(unittest.TestCase):
    """A file can put any number of faces on one edge: the work stays linear."""

    def fan(self, groups):
        n = len(groups)
        lv = numpy.stack((numpy.zeros(n), numpy.ones(n), numpy.arange(2, n + 2)), axis=1).astype(numpy.int32).ravel()
        return lv, numpy.arange(0, 3 * n, 3, dtype=numpy.int32), numpy.full(n, 3, dtype=numpy.int32), groups

    def test_a_fan_on_one_edge_sharing_a_group_is_fast_and_smooth(self):
        import time
        start = time.perf_counter()
        edges = conv.sharp_edges(*self.fan(numpy.ones(100000, dtype=numpy.uint32)))
        self.assertLess(time.perf_counter() - start, 5.0)
        self.assertEqual(len(edges), 0)

    def test_a_fan_with_two_disjoint_groups_is_sharp(self):
        groups = numpy.ones(1000, dtype=numpy.uint32)
        groups[500] = 2
        self.assertEqual([tuple(e) for e in conv.sharp_edges(*self.fan(groups)).tolist()], [(0, 1)])

    def test_too_many_distinct_masks_make_the_edge_sharp(self):
        # all share group 1, all distinct
        groups = (numpy.arange(1, conv.MAX_EDGE_MASKS + 2, dtype=numpy.uint32) << 1) | 1
        self.assertGreater(len(groups), conv.MAX_EDGE_MASKS)
        self.assertEqual([tuple(e) for e in conv.sharp_edges(*self.fan(groups)).tolist()], [(0, 1)])
        few = groups[:conv.MAX_EDGE_MASKS]
        self.assertEqual(len(conv.sharp_edges(*self.fan(few))), 0)


@unittest.skipIf(numpy is None, "numpy missing")
class InvalidFaces(unittest.TestCase):
    def test_repeated_vertex_and_doubled_faces_are_refused(self):
        # 0: good tri; 1: repeated vertex; 2: same vertex set as 0, other order; 3: good quad; 4: quad repeating 5
        lv = [0, 1, 2, 3, 3, 4, 2, 0, 1, 0, 1, 5, 4, 1, 5, 6, 5]
        keep = conv.valid_faces(lv, [0, 3, 6, 9, 13], [3, 3, 3, 4, 4])
        self.assertEqual(keep.tolist(), [True, False, False, True, False])

    def test_dropped_faces_keep_uvs_materials_and_groups_aligned(self):
        lv = numpy.asarray([0, 1, 2, 2, 2, 3, 1, 3, 2], dtype=numpy.int32)
        uv = geometry.MapChannel(1, numpy.arange(27, dtype=numpy.float32).reshape(9, 3),
                                 numpy.arange(9, dtype=numpy.int32))
        data = geometry.MeshData(numpy.zeros((4, 3), dtype=numpy.float32), lv,
                                 numpy.asarray([0, 3, 6], dtype=numpy.int32),
                                 numpy.asarray([1, 2, 0], dtype=numpy.uint32),
                                 numpy.asarray([4, 5, 6], dtype=numpy.uint16), {1: uv})
        md = conv.mesh_description((0, None), "m", data, None, 1.0)
        self.assertEqual(md.dropped_faces, 1)
        self.assertEqual(md.loop_vertices.tolist(), [0, 1, 2, 1, 3, 2])
        self.assertEqual(md.loop_starts.tolist(), [0, 3])
        self.assertEqual(md.material_indices.tolist(), [4, 6])
        self.assertEqual(md.sharp_faces.tolist(), [False, True])
        self.assertEqual(md.uv_layers[0][1][:, 0].tolist(), [0.0, 3.0, 6.0, 18.0, 21.0, 24.0])
        self.assertEqual([tuple(e) for e in md.sharp_edges.tolist()], [(1, 2)])


@unittest.skipIf(numpy is None, "numpy missing")
class DamagedInput(unittest.TestCase):
    def scene(self, name):
        cf = cfb.CompoundFile(os.path.join(ROOT, "tests", "fixtures", name + ".max"))
        self.addCleanup(cf.close)
        return reader_scene.Scene.from_file(cf)

    def test_refused_geometry_becomes_a_placeholder_with_an_issue(self):
        sc = self.scene("instances")
        real = conv.geometry.read_mesh

        def refuse(scene, i):
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
        self.assertEqual(len(desc.issues), 2)
        self.assertTrue(all(r.startswith("layer: ") for _n, r in desc.issues))

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

    def test_closing_straight_segment_and_bevel(self):
        k = shapes.Knot
        knots = [k(shapes.CORNER, shapes.CURVE, (0, 0, 0), (0, 0, 0), (0, 0, 0)),
                 k(shapes.CORNER, shapes.LINE, (3, 0, 0), (3, 0, 0), (3, 0, 0))]
        cd, issues = conv.curve_description("k", "n", self._shape(knots, closed=True, renderable=True, thickness=4.0,
                                                                  sides=3, rectangular=True), None, 1.0)
        self.assertEqual((cd.splines[0].right[1], cd.splines[0].left[0]), ((2, 0, 0), (1, 0, 0)))
        self.assertEqual((cd.bevel_depth, cd.bevel_resolution), (2.0, 0))
        self.assertEqual(len(issues), 1)  # the rectangular section is drawn round

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


@unittest.skipIf(numpy is None, "numpy missing")
class Fixtures(unittest.TestCase):
    """Every committed fixture against its 3ds Max oracle."""

    @classmethod
    def setUpClass(cls):
        cls.cases = [(_name(p), conv.read(p), _oracle(p)) for p in FIXTURES]

    def test_every_fixture_is_described(self):
        self.assertEqual(sorted(name for name, _d, _o in self.cases), sorted(UV_LAYERS))

    def test_units_follow_the_file(self):
        meters = {name: desc.meters for name, desc, _o in self.cases}
        self.assertEqual(meters["units_mm"], 0.001)
        self.assertEqual(meters["units_cm"], 0.01)
        self.assertEqual(meters["units_in"], 0.0254)
        self.assertEqual(meters["box_poly_standard"], 0.001)

    def test_order_names_and_parents_equal_the_oracle(self):
        for name, desc, oracle in self.cases:
            position = {n["handle"]: n["index"] for n in oracle["nodes"]}
            ours = {node.index: k for k, node in enumerate(desc.nodes)}
            self.assertEqual([n.name for n in desc.nodes], [n["name"] for n in oracle["nodes"]], name)
            self.assertEqual([None if n.parent is None else ours[n.parent] for n in desc.nodes],
                             [None if n["parent"] is None else position[n["parent"]] for n in oracle["nodes"]],
                             name)

    def test_world_matrices_equal_the_oracle(self):
        for name, desc, oracle in self.cases:
            for node, o in zip(desc.nodes, oracle["nodes"]):
                w = node.world
                rows = [[w[c][r] for c in range(3)] for r in range(3)] + [[w[c][3] / desc.meters for c in range(3)]]
                expected = [o["transform"][k:k + 3] for k in range(0, 12, 3)]
                for got_row, want_row in zip(rows, expected):
                    for got, want in zip(got_row, want_row):
                        self.assertAlmostEqual(got, want, delta=MATRIX_TOLERANCE, msg="%s %s" % (name, node.name))

    def test_local_matrices_compose_to_the_world(self):
        for name, desc, _o in self.cases:
            by_index = {n.index: n for n in desc.nodes}
            for node in desc.nodes:
                m = numpy.asarray(node.matrix)
                if node.parent is not None:
                    m = numpy.asarray(by_index[node.parent].world) @ m
                numpy.testing.assert_allclose(m, numpy.asarray(node.world), atol=1e-9, err_msg=name)

    def test_world_bounding_boxes_equal_the_oracle(self):
        for name, desc, oracle in self.cases:
            for node, o in zip(desc.nodes, oracle["nodes"]):
                if node.kind != conv.MESH or (o["modifiers"] and not node.applied):  # the box is after the modifiers
                    continue
                p = _world_points(node, desc.meshes[node.mesh]) / desc.meters
                numpy.testing.assert_allclose(p.min(axis=0), o["bbox_min"], atol=BBOX_TOLERANCE,
                                              err_msg="%s %s" % (name, node.name))
                numpy.testing.assert_allclose(p.max(axis=0), o["bbox_max"], atol=BBOX_TOLERANCE,
                                              err_msg="%s %s" % (name, node.name))

    def test_counts_equal_the_oracle(self):
        for name, desc, oracle in self.cases:
            for node, o in zip(desc.nodes, oracle["nodes"]):
                extruded = o["shape"] is not None and o["eval_verts"] is not None  # an Extrude on the shape
                kind = conv.MESH if o["base_verts"] is not None or extruded else conv.CURVE if o["shape"] else                     conv.EMPTY
                self.assertEqual(node.kind, kind, "%s %s" % (name, node.name))
                if node.kind == conv.MESH:
                    md = desc.meshes[node.mesh]
                    if extruded:  # 3ds Max's counts are of triangles
                        self.assertEqual((len(md.positions), int((md.loop_totals - 2).sum())),
                                         (o["eval_verts"], o["eval_faces"]), "%s %s" % (name, node.name))
                    else:
                        self.assertEqual((len(md.positions), len(md.loop_starts)), (o["base_verts"], o["base_faces"]),
                                         "%s %s" % (name, node.name))
                    self.assertEqual(int(md.loop_totals.sum()), len(md.loop_vertices))

    def test_shared_meshes_equal_the_oracle_instances(self):
        """The nodes sharing a base object and the same object offset share one mesh (the offset is baked)."""
        for name, desc, oracle in self.cases:
            handle = {node.index: o["handle"] for node, o in zip(desc.nodes, oracle["nodes"])}
            by_handle = {o["handle"]: o for o in oracle["nodes"]}

            def offset(o):
                return o["offset_pos"], o["offset_rot"], o["offset_scale"]

            for node, o in zip(desc.nodes, oracle["nodes"]):
                if node.kind == conv.MESH:
                    want = [h for h in o["instances"] if offset(by_handle[h]) == offset(o)]
                    self.assertEqual(sorted(handle[u] for u in desc.meshes[node.mesh].users), want,
                                     "%s %s" % (name, node.name))

    def test_rotated_pivot_leaves_the_object_in_place(self):
        """modifier_pivot: FixtureBent's pivot alone is turned 30 degrees about Z. Its baked base mesh is the
        source's, moved by the 30 units between the two nodes: the offset rotation undoes the pivot's."""
        desc = dict((n, d) for n, d, _o in self.cases)["modifier_pivot"]
        by_name = {n.name: n for n in desc.nodes}
        src, bent = by_name["FixtureSource"], by_name["FixtureBent"]
        self.assertNotEqual(src.mesh, bent.mesh)
        self.assertIsNotNone(bent.mesh[1])
        a = _world_points(src, desc.meshes[src.mesh]) / desc.meters
        b = _world_points(bent, desc.meshes[bent.mesh]) / desc.meters - [30, 0, 0]
        numpy.testing.assert_allclose(b, a, atol=BBOX_TOLERANCE)

    def test_instances_share_one_mesh_and_the_copy_has_its_own(self):
        desc = dict((n, d) for n, d, _o in self.cases)["instances"]
        self.assertEqual(len(desc.meshes), 2)
        self.assertEqual(sorted(len(md.users) for md in desc.meshes.values()), [1, 4])

    def test_mirrored_flag(self):
        desc = dict((n, d) for n, d, _o in self.cases)["hierarchy"]
        self.assertEqual([n.name for n in desc.nodes if n.mirrored], ["FixtureLeaf"])

    def test_object_offset_is_baked_into_the_mesh(self):
        desc = dict((n, d) for n, d, _o in self.cases)["hierarchy"]
        root = desc.nodes[0]
        self.assertEqual(root.name, "FixtureRoot")
        self.assertIsNotNone(root.mesh[1])
        self.assertIsNone(desc.nodes[2].mesh[1])  # FixtureLeaf: no offset

    def test_uv_layers_follow_the_map_channels(self):
        for name, desc, _o in self.cases:
            for md in desc.meshes.values():
                want = UV_LAYERS[name]
                want = want.get(md.name, []) if isinstance(want, dict) else want
                self.assertEqual([n for n, _uv in md.uv_layers], want, name)
                for _n, uv in md.uv_layers:
                    self.assertEqual(uv.shape, (len(md.loop_vertices), 2))
                    self.assertEqual(uv.dtype, numpy.float32)

    def test_sharp_edges_from_smoothing_groups(self):
        for name, desc, _o in self.cases:
            want = {"editable_mesh": SHARP_EDGES_EDITABLE_MESH,
                    "modifier_pivot": SHARP_EDGES_TALL_BOX}.get(name, SHARP_EDGES_POLY_BOX)
            for md in desc.meshes.values():
                self.assertEqual(len(md.sharp_edges), SHARP_EDGES_EXTRUDE.get(md.name, want), "%s %s" % (name, md.name))
                self.assertFalse(md.sharp_faces.any(), name)

    def test_placeholders(self):
        for name, desc, _o in self.cases:
            self.assertEqual(dict(desc.placeholders), {}, name)  # the group head is a Dummy: converted, an empty
            self.assertEqual(desc.issues, [], name)
            self.assertEqual(dict(desc.unknown_controllers), {}, name)
        desc = dict((n, d) for n, d, _o in self.cases)["layers_flags"]
        head = next(n for n in desc.nodes if n.kind == conv.EMPTY)
        self.assertEqual((head.name, head.class_name, head.mesh), ("FixtureGroup", "Dummy", None))

    def test_flags_and_layers_equal_the_oracle(self):
        for name, desc, oracle in self.cases:
            names = {la.index: la.name for la in desc.layers}
            used = []
            for node, o in zip(desc.nodes, oracle["nodes"]):
                self.assertEqual((node.hidden, node.frozen, node.renderable, names[node.layer]),
                                 (o["hidden"], o["frozen"], o["renderable"], o["layer"]), o["name"])
                if o["layer"] not in used:
                    used.append(o["layer"])
            order = [la["name"] for la in oracle["layers"]]
            self.assertEqual([la.name for la in desc.layers], sorted(used, key=order.index), name)
            flags = {la["name"]: (la["hidden"], la["frozen"], la["renderable"]) for la in oracle["layers"]}
            for la in desc.layers:
                self.assertEqual((la.hidden, la.frozen, la.renderable), flags[la.name])
                self.assertIsNone(la.parent)

    def test_layers_flags_organisation(self):
        desc = dict((n, d) for n, d, _o in self.cases)["layers_flags"]
        self.assertEqual([la.name for la in desc.layers], ["FixtureLayerA", "FixtureLayerB"])
        by_name = {n.name: n for n in desc.nodes}
        self.assertEqual([k for k, n in by_name.items() if n.hidden], ["FixtureHidden"])
        self.assertEqual([k for k, n in by_name.items() if not n.renderable], ["FixtureNoRender"])
        self.assertEqual([k for k, n in by_name.items() if n.group_head], ["FixtureGroup"])
        head = by_name["FixtureGroup"].index
        self.assertEqual(sorted(k for k, n in by_name.items() if n.group_member),
                         sorted(k for k, n in by_name.items() if n.parent == head))
        self.assertEqual(len([n for n in desc.nodes if n.parent == head]), 2)

    def test_curves_equal_the_oracle(self):
        """Every shape node's curve: splines, points and cyclic flags as 3ds Max converts the shape, each segment's
        Bezier midpoint where 3ds Max interpolates it (straight segments included), resolution and bevel."""
        for name, desc, oracle in self.cases:
            for node, o in zip(desc.nodes, oracle["nodes"]):
                if o["shape"] is None or node.kind == conv.MESH:  # an extruded shape is a mesh
                    self.assertIsNone(node.curve)
                    continue
                label = "%s %s" % (name, node.name)
                cd = desc.curves[node.curve]
                self.assertIn(node.index, cd.users, label)
                self.assertIsNone(node.curve[1], label)  # no object offset in the fixtures: object space = curve's
                want = o["shape"]["splines"]
                self.assertEqual([(len(sp.points), sp.cyclic) for sp in cd.splines],
                                 [(len(w["knots"]), w["closed"]) for w in want], label)
                for sp, w in zip(cd.splines, want):
                    n = len(sp.points)
                    for k, knot in enumerate(w["knots"]):
                        numpy.testing.assert_allclose(numpy.asarray(sp.points[k]) / desc.meters, knot["pos"],
                                                      atol=1e-4, err_msg=label)
                        if knot["mid"] is None:
                            continue
                        j = (k + 1) % n
                        mid = (numpy.asarray(sp.points[k]) + 3 * numpy.asarray(sp.right[k]) +
                               3 * numpy.asarray(sp.left[j]) + numpy.asarray(sp.points[j])) / 8 / desc.meters
                        numpy.testing.assert_allclose(mid, knot["mid"], atol=1e-4, err_msg="%s knot %d" % (label, k))
                s = o["shape"]
                self.assertEqual(cd.resolution, conv.ADAPTIVE if s["adaptive"] else s["steps"] + 1, label)
                if s["renderable"]:
                    self.assertAlmostEqual(cd.bevel_depth, s["thickness"] / 2 * desc.meters, places=9)
                    self.assertEqual(cd.bevel_resolution, (s["sides"] - 4) // 2, label)
                else:
                    self.assertEqual(cd.bevel_depth, 0.0, label)

    def test_shapes_are_not_placeholders(self):
        desc = dict((n, d) for n, d, _o in self.cases)["shapes"]
        self.assertEqual([n.kind for n in desc.nodes], [conv.CURVE] * 13 + [conv.MESH])
        self.assertEqual(len(desc.curves), 13)
        line = next(n for n in desc.nodes if n.name == "FixtureLine")
        self.assertEqual(desc.curves[line.curve].bevel_resolution, 2)  # 8 sides

    def test_material_indices_from_the_reader(self):
        desc = dict((n, d) for n, d, _o in self.cases)["box_poly_standard"]
        md = next(iter(desc.meshes.values()))
        self.assertEqual(sorted(md.material_indices.tolist()), [0, 1, 2, 3, 4, 5])
        self.assertEqual(md.material_indices.dtype, numpy.int32)


if __name__ == "__main__":
    unittest.main()
