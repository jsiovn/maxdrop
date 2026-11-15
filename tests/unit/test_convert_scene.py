# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/scene.py, the scene description: no Blender. The smoothing-group rule, the loop reversal
of a mirrored object offset, and every committed fixture against its 3ds Max oracle (order, parents, world
matrices, world bounding boxes, counts, shared meshes, units) and its authoring script (UV channels, smoothing
groups).

    python -I -m unittest discover tests
"""
import glob
import importlib
import json
import os
import sys
import types
import unittest

try:
    import numpy
except ImportError:  # the plain CI job has no numpy; Blender ships it
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

# From the fixture scripts (tools/fixtures/*.ms: mapcoords:true gives channel 1); the oracle has no map channels or
# smoothing groups.
UV_LAYERS = {
    "box_poly_standard": ["UVMap"],
    "editable_mesh": ["UVMap"],
    "hierarchy": [],
    "instances": ["UVMap"],
    "layers_flags": [],
    "multi_uv": ["UVMap", "UVChannel_2", "UVChannel_3"],
    "units_cm": ["UVMap"],
    "units_in": ["UVMap"],
    "units_mm": ["UVMap"],
}
SHARP_EDGES_POLY_BOX = 12  # one smoothing group per side: every edge of the box
SHARP_EDGES_EDITABLE_MESH = 8  # group 1 on top and bottom, 2 on the sides: the rims of top and bottom


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
        self.assertEqual(len(self.cases), 9)

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
                if node.kind != conv.MESH:
                    continue
                p = _world_points(node, desc.meshes[node.mesh]) / desc.meters
                numpy.testing.assert_allclose(p.min(axis=0), o["bbox_min"], atol=BBOX_TOLERANCE,
                                              err_msg="%s %s" % (name, node.name))
                numpy.testing.assert_allclose(p.max(axis=0), o["bbox_max"], atol=BBOX_TOLERANCE,
                                              err_msg="%s %s" % (name, node.name))

    def test_counts_equal_the_oracle(self):
        for name, desc, oracle in self.cases:
            for node, o in zip(desc.nodes, oracle["nodes"]):
                self.assertEqual(node.kind, conv.MESH if o["base_verts"] is not None else conv.EMPTY, name)
                if node.kind == conv.MESH:
                    md = desc.meshes[node.mesh]
                    self.assertEqual((len(md.positions), len(md.loop_starts)), (o["base_verts"], o["base_faces"]),
                                     "%s %s" % (name, node.name))
                    self.assertEqual(int(md.loop_totals.sum()), len(md.loop_vertices))

    def test_shared_meshes_equal_the_oracle_instances(self):
        for name, desc, oracle in self.cases:
            handle = {node.index: o["handle"] for node, o in zip(desc.nodes, oracle["nodes"])}
            for node, o in zip(desc.nodes, oracle["nodes"]):
                if node.kind == conv.MESH:
                    self.assertEqual(sorted(handle[u] for u in desc.meshes[node.mesh].users), o["instances"],
                                     "%s %s" % (name, node.name))

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
                self.assertEqual([n for n, _uv in md.uv_layers], UV_LAYERS[name], name)
                for _n, uv in md.uv_layers:
                    self.assertEqual(uv.shape, (len(md.loop_vertices), 2))
                    self.assertEqual(uv.dtype, numpy.float32)

    def test_sharp_edges_from_smoothing_groups(self):
        for name, desc, _o in self.cases:
            want = SHARP_EDGES_EDITABLE_MESH if name == "editable_mesh" else SHARP_EDGES_POLY_BOX
            for md in desc.meshes.values():
                self.assertEqual(len(md.sharp_edges), want, name)
                self.assertFalse(md.sharp_faces.any(), name)

    def test_placeholders(self):
        for name, desc, _o in self.cases:
            expected = {"Dummy": 1} if name == "layers_flags" else {}
            self.assertEqual(dict(desc.placeholders), expected, name)
            self.assertEqual(desc.issues, [], name)
        desc = dict((n, d) for n, d, _o in self.cases)["layers_flags"]
        head = next(n for n in desc.nodes if n.kind == conv.EMPTY)
        self.assertEqual((head.name, head.class_name, head.mesh), ("FixtureGroup", "Dummy", None))

    def test_material_indices_from_the_reader(self):
        desc = dict((n, d) for n, d, _o in self.cases)["box_poly_standard"]
        md = next(iter(desc.meshes.values()))
        self.assertEqual(sorted(md.material_indices.tolist()), [0, 1, 2, 3, 4, 5])
        self.assertEqual(md.material_indices.dtype, numpy.int32)


if __name__ == "__main__":
    unittest.main()
