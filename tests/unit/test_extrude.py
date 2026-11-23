# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/extrude.py, the Extrude modifier on a shape: no Blender. Every extruded node of the
extrude fixture against its 3ds Max oracle (world bounding box within 1e-3, vertex count, triangle count), closed
manifolds with outward normals for the capped ones, the hole of the holed cap, the open one without caps; material
IDs by the way a face looks and map channel 1's vertex count, range and every corner against the oracle's eval_mesh;
mapping coordinates; 3ds Max's interpolation counts (found with its own Extrude: steps, optimize, adaptive); the ear
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
          "FixtureExtAdaptive", "FixtureExtShapeIDs", "FixtureExtShapeIDsRect", "FixtureExtGrid")
UNCAPPED = ("FixtureExtOpen", "FixtureExtGridCircle")  # no cap; Cap End off (a grid cap at the start)
# V - E + F of each mesh: a box-like solid 2, a solid with a tunnel (the round hole) 0, the island's ring and its
# core 0 + 2
EULER = {"FixtureExtRect": 2, "FixtureExtL": 2, "FixtureExtHole": 0, "FixtureExtIsland": 2, "FixtureExtMirror": 2,
         "FixtureExtAdaptive": 2, "FixtureExtShapeIDs": 0, "FixtureExtShapeIDsRect": 2, "FixtureExtGrid": 0}


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


def _check_eval_mesh(test, data, md, want, name):
    """data (the reader MeshData: object space, before the object offset, as the oracle takes it back to) and md
    (its MeshDescription) against the oracle's eval_mesh of the node."""
    hist = {}
    for f in range(len(data.loop_starts)):
        z = _face_area_z(data, f)  # the winding normal's z, times the polygon's area
        if abs(z) <= 1e-4 * _face_area(data, f):
            side = 3
        else:
            side = 1 if z > 0 else 2
        row = hist.setdefault(int(_mats(data)[f]) + 1, [0, 0, 0])
        row[side - 1] += int(data.loop_totals[f]) - 2  # 3ds Max counts triangles
    test.assertEqual([[i] + hist[i] for i in sorted(hist)], want["material_ids"], name)
    channel = data.maps.get(1)
    test.assertEqual(channel is None, want["map_channel_1"] is None, name)
    if channel is None:
        return
    uvw = numpy.asarray(channel.uvw, dtype=numpy.float64)
    used = uvw[numpy.unique(channel.indices)]
    test.assertEqual(len(uvw), want["map_channel_1"]["count"], name)
    for got, key in ((used.min(axis=0), "min"), (used.max(axis=0), "max")):  # 6 significant digits
        numpy.testing.assert_allclose(got, want["map_channel_1"][key], rtol=1e-5, atol=1e-6, err_msg=name)
    uv = dict(md.uv_layers)["UVMap"]  # what Blender gets: u and v of the same vertices
    for got, key in ((uv.min(axis=0), "min"), (uv.max(axis=0), "max")):
        numpy.testing.assert_allclose(got, want["map_channel_1"][key][:2], rtol=1e-5, atol=1e-6, err_msg=name)


def _read_meshes(path):
    """(scene description, {node name: reader MeshData}) of a fixture: the MeshData keeps its map vertices."""
    data = {}
    real = conv.mesh_description

    def describing(key, name, d, *args, **kw):
        data[name] = d
        return real(key, name, d, *args, **kw)

    with mock.patch.object(conv, "mesh_description", describing):
        desc = conv.read(path)
    return desc, data


@unittest.skipIf(numpy is None, "numpy missing")
class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.desc, cls.data = _read_meshes(FIXTURE)  # the reader MeshData of each mesh, by name
        with open(FIXTURE[:-4] + ".oracle.json", encoding="utf-8") as f:
            cls.oracle = {n["name"]: n for n in json.load(f)["nodes"]}
        cls.nodes = {n.name: n for n in cls.desc.nodes}

    def mesh(self, name):
        node = self.nodes[name]
        self.assertEqual(node.kind, conv.MESH, name)
        return node, self.desc.meshes[node.mesh]

    def test_counts_and_world_box_equal_the_oracle(self):
        for name in CAPPED + UNCAPPED:
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
        for name in CAPPED + UNCAPPED:
            _check_eval_mesh(self, self.data[name], self.mesh(name)[1], self.oracle[name]["eval_mesh"], name)

    def test_every_mapped_corner_equals_the_oracle(self):
        """Position, face normal and map vertex of every corner of map channel 1, both ways, against the oracle's
        eval_mesh corners (object space): the side U runs along each spline the way 3ds Max runs it."""
        mapped = sorted(name for name, o in self.oracle.items()
                        if o["eval_mesh"] and o["eval_mesh"]["map_channel_1"]
                        and o["eval_mesh"]["map_channel_1"]["corners"] is not None)
        self.assertEqual(mapped, ["FixtureExtAdaptive", "FixtureExtRect"])  # the two with mapping coordinates
        for name in mapped:
            _check_corners(self, self.data[name], self.oracle[name], name)

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
        for name in CAPPED + UNCAPPED:
            self.assertEqual((self.nodes[name].applied, self.nodes[name].modifiers), (("Extrude",), ()), name)
        off = self.nodes["FixtureExtOff"]  # switched off: the curve, the modifier not applied
        self.assertEqual((off.kind, off.applied, off.modifiers), (conv.CURVE, (), ("Extrude",)))
        rep = importlib.import_module(_PKG + ".convert.report").gather(self.desc)
        self.assertEqual(dict(rep.modifiers_applied), {"Extrude": 11})
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
        self.assertEqual([n.kind for n in desc.nodes], [conv.CURVE] * 12)
        self.assertEqual(len([r for _i, r in desc.issues if r.startswith("extrude: an Extrude above ")]), 11)

    def test_an_extrude_that_cannot_be_read_keeps_the_curve(self):
        with mock.patch.object(extrude, "read_params", side_effect=extrude.ExtrudeError("refused")):
            desc = conv.read(FIXTURE)
        self.assertEqual([n.kind for n in desc.nodes], [conv.CURVE] * 12)
        self.assertEqual([r for _i, r in desc.issues], ["extrude: refused"] * 11)
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
        self.assertEqual(len(made), 11)
        self.assertEqual(alive, [1] * 11)  # only the extrusion being described

    def test_a_scene_wide_budget_keeps_the_rest_curves(self):
        with mock.patch.object(conv, "MAX_BUILT_CORNERS", 1):
            desc = conv.read(FIXTURE)
        self.assertEqual(sorted(n.kind for n in desc.nodes), [conv.CURVE] * 11 + [conv.MESH])
        spent = [r for _i, r in desc.issues if r.startswith("extrude: not made: the primitives and extrusions ")]
        self.assertEqual(len(spent), 10)

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

    def test_a_shell_hardens_the_rim_of_an_open_extrusion(self):
        """A converted Shell above an Extrude: the mesh key ends with ("rim", True), the open edges of an extrusion
        without caps join its sharp edges (convert.scene._rim on the extruded path)."""
        real_evaluated = conv._evaluated
        shared = types.SimpleNamespace(index=None)

        def evaluated(*args):
            ext, maps, rest = real_evaluated(*args)
            if ext is not None:
                if shared.index is None:
                    shared.index = ext.index  # one Shell instanced on every extruded shape
                rest = rest + (shared,)
            return ext, maps, rest

        def converting(_scene, m, _meters=1.0, _offset=None):
            return rules.ModifierDescription(m.index, rules.SOLIDIFY, "Shell", "Shell", True, (), None, None,
                                             rules.RimRule(False, 45.0, None)), []

        with mock.patch.object(conv, "_evaluated", evaluated),                 mock.patch.object(rules, "is_convertible", lambda m: m is shared),                 mock.patch.object(rules, "convert", converting):
            desc = conv.read(FIXTURE)
        meshes = [n for n in desc.nodes if n.kind == conv.MESH]
        self.assertTrue(meshes)
        opened = 0
        for node in meshes:
            self.assertEqual(node.mesh[-1], ("rim", True), node.name)
            md = desc.meshes[node.mesh]
            boundary = {tuple(e) for e in conv.open_edges(md.loop_vertices, md.loop_starts,
                                                          md.loop_totals).tolist()}
            self.assertLessEqual(boundary, {tuple(e) for e in md.sharp_edges.tolist()}, node.name)
            opened += bool(boundary)
        self.assertGreater(opened, 0)  # FixtureExtOpen: no caps


PIES = os.path.join(ROOT, "tests", "fixtures", "arc_pie_reverse.max")


def _corners(faces):
    """[(position, unit face normal, uvw, material ID)] of every corner of [(positions, uvws, material ID)]."""
    out = []
    for p, uvw, mat in faces:
        p = numpy.asarray(p, dtype=numpy.float64)
        normal = numpy.cross(p, numpy.roll(p, -1, axis=0)).sum(axis=0)  # Newell: a triangle or a flat polygon
        normal /= numpy.linalg.norm(normal)
        out.extend((q, normal, numpy.asarray(w, dtype=numpy.float64), mat) for q, w in zip(p, uvw))
    return out


def _reader_faces(data, ids=True):
    """[(positions, uvws, material ID)] of every polygon of a reader MeshData with map channel 1 (ID None without
    ids)."""
    starts = data.loop_starts.tolist() + [len(data.loop_vertices)]
    ch = data.maps[1]
    return [(data.positions[data.loop_vertices[s:e]], [ch.uvw[i] for i in ch.indices[s:e]],
             int(data.material_ids[f]) + 1 if ids else None) for f, (s, e) in enumerate(zip(starts, starts[1:]))]


def _tolerance(v):
    """1e-4, relative (2e-5) above 5: the oracle's values have 6 significant digits (a real-world U reaches tens of
    units)."""
    return max(1e-4, 2e-5 * float(numpy.abs(v).max()))


def _unmatched(a, b):
    """The corners of a with none of b at the same position, facing the same way, with the same map vertex and
    material ID: independent of the face order and of how a polygon is cut into triangles."""
    if not b:
        return list(a)
    pos, nrm, uvw = (numpy.asarray([d[k] for d in b], dtype=numpy.float64) for k in range(3))
    mats = [d[3] for d in b]
    flat = ~nrm.any(axis=1)  # a degenerate triangle has no normal: [0, 0, 0] in the oracle
    out = []
    for c in a:
        facing = (nrm @ c[1] > 0.9999) | flat if c[1].any() else numpy.ones(len(b), dtype=bool)
        ok = ((numpy.abs(pos - c[0]).max(axis=1) < _tolerance(c[0])) & facing
              & (numpy.abs(uvw - c[2]).max(axis=1) < _tolerance(c[2])))
        if not any(ok[k] and mats[k] == c[3] for k in numpy.flatnonzero(ok)):
            out.append(c)
    return out


def _check_corners(test, data, node, name):
    """Every corner of map channel 1 of a reader MeshData against the oracle's eval_mesh corners (object space),
    both ways: position, face normal, map vertex."""
    want = node["eval_mesh"]["map_channel_1"]["corners"]
    theirs = [(numpy.asarray(c[0:3], dtype=numpy.float64), numpy.asarray(c[3:6], dtype=numpy.float64),
               numpy.asarray(c[6:9], dtype=numpy.float64), None) for c in want]
    test.assertTrue(all(abs(numpy.linalg.norm(c[1]) - 1.0) < 1e-4 or not c[1].any() for c in theirs), name)
    got = _corners(_reader_faces(data, ids=False))
    test.assertEqual(_unmatched(theirs, got), [], name)
    test.assertEqual(_unmatched(got, theirs), [], name)


@unittest.skipIf(numpy is None, "numpy missing")
@unittest.skipUnless(os.path.exists(PIES), "no arc_pie_reverse fixture")
class ReversedPies(unittest.TestCase):
    """arc_pie_reverse: reversed pie Arcs (their outline runs clockwise), a pie, a reversed open arc, a clockwise
    Line and a Circle hole under an Extrude with mapping coordinates, against 3ds Max's evaluated meshes
    (arc_pie_reverse.maps.jsonl, written by tools/fixtures/arc_pie_reverse.ms) and the oracle's eval_mesh."""

    @classmethod
    def setUpClass(cls):
        cls.desc, cls.data = _read_meshes(PIES)
        with open(PIES[:-4] + ".oracle.json", encoding="utf-8") as f:
            cls.oracle = {n["name"]: n for n in json.load(f)["nodes"]}
        with open(PIES[:-4] + ".maps.jsonl", encoding="ascii") as f:
            cls.dump = {d["name"]: d for d in (json.loads(line) for line in f if line.strip())}

    def test_the_dump_names_every_extruded_node(self):
        self.assertEqual(sorted(self.dump), sorted(n for n in self.data if n.endswith("Ext")))
        self.assertEqual(len(self.dump), 6)

    def test_eval_mesh_equals_the_oracle(self):
        nodes = {n.name: n for n in self.desc.nodes}
        for name, data in self.data.items():
            md = self.desc.meshes[nodes[name].mesh]
            _check_eval_mesh(self, data, md, self.oracle[name]["eval_mesh"], name)

    def test_hard_edges_equal_the_oracle(self):
        """The smoothing groups' hard edges, as the oracle's eval_mesh.smoothing counts them: a pie's side also
        breaks at from, the center and to (Bezier knots with a vector on the point, maxdrop-em3.111)."""
        nodes = {n.name: n for n in self.desc.nodes}
        for name in self.data:
            md = self.desc.meshes[nodes[name].mesh]
            self.assertEqual(len(md.sharp_edges), self.oracle[name]["eval_mesh"]["smoothing"]["hard_edges"], name)

    def test_hard_edges_lie_where_3ds_max_puts_them(self):
        """The hard edges by position, both ways, against those of the dump's triangles (their smoothing groups,
        the vertices welded by position): 3ds Max's group bits differ, the edges between them do not."""
        for name, want in self.dump.items():
            theirs = _dump_hard_edges(want["faces"])
            self.assertEqual(len(theirs), self.oracle[name]["eval_mesh"]["smoothing"]["hard_edges"], name)
            data = self.data[name]
            p = numpy.asarray(data.positions, dtype=numpy.float64)
            got = [(p[a], p[b]) for a, b in conv.sharp_edges(data.loop_vertices, data.loop_starts,
                                                              data.loop_totals, data.smoothing_groups).tolist()]
            self.assertEqual(_unmatched_edges(theirs, got), [], name)
            self.assertEqual(_unmatched_edges(got, theirs), [], name)

    def test_every_corner_equals_the_oracle(self):
        """The oracle's eval_mesh corners of every extruded node, as the dump's."""
        self.assertEqual(sorted(n for n, o in self.oracle.items() if o["eval_mesh"]), sorted(self.dump))
        for name in self.dump:
            _check_corners(self, self.data[name], self.oracle[name], name)

    def test_every_corner_equals_3ds_max(self):
        """Position, face normal, map vertex and material ID of every corner, both ways: the side U starts where
        3ds Max starts it (a reversed pie at the arc point after from, a turned outline at its last point)."""
        for name, want in self.dump.items():
            got = _corners(_reader_faces(self.data[name]))
            theirs = _corners([(f["p"], f["uv"], f["mat"]) for f in want["faces"]])
            self.assertEqual(len(theirs), 3 * len(want["faces"]), name)
            self.assertEqual(_unmatched(theirs, got), [], name)
            self.assertEqual(_unmatched(got, theirs), [], name)


def _dump_hard_edges(faces):
    """[(p, q)] of the edges of exactly two triangles of a dump (positions and sg per face), both smoothed, that
    share no group; the corners welded by position, as the oracle welds them by vertex index."""
    points, corner = [], []
    for f in faces:
        for q in f["p"]:
            q = numpy.asarray(q, dtype=numpy.float64)
            at = next((k for k, r in enumerate(points) if numpy.abs(r - q).max() < _tolerance(q)), None)
            if at is None:
                at = len(points)
                points.append(q)
            corner.append(at)
    edges = {}
    for f in range(len(faces)):
        vs = corner[3 * f:3 * f + 3]
        for k in range(3):
            edges.setdefault(tuple(sorted((vs[k], vs[(k + 1) % 3]))), []).append(f)
    out = []
    for (a, b), fs in edges.items():
        if len(fs) == 2:
            g1, g2 = (faces[f]["sg"] for f in fs)
            if g1 and g2 and not g1 & g2:
                out.append((points[a], points[b]))
    return out


def _unmatched_edges(a, b):
    """The edges of a with no edge of b between the same two positions."""
    def same(e, f):
        return all(numpy.abs(x - y).max() < _tolerance(x) for x, y in zip(e, f))
    return [e for e in a if not any(same(e, f) or same(e, f[::-1]) for f in b)]


def _knots(points, kind=shapes.CORNER):
    return tuple(shapes.Knot(kind, shapes.LINE, p, p, p) for p in points)


def _shape(splines, steps=6, optimize=True, adaptive=False):
    return shapes.Shape(shapes.classids.SPLINE_SHAPE, tuple(splines), steps, optimize, adaptive,
                        shapes.DEFAULT_RENDER, ())


def _points(shape):
    return sum(len(pl.points) for pl in extrude.polylines(shape))


def _segment(p0, c1, c2, p3):
    """An open spline of one curve segment between two Bezier-corner knots: c1 the out vector, c2 the in vector."""
    k = shapes.Knot
    return shapes.Spline((k(shapes.BEZIER_CORNER, shapes.CURVE, p0, p0, c1),
                          k(shapes.BEZIER_CORNER, shapes.CURVE, p3, c2, p3)), False)


def _off(e, chord=10.0):
    return chord * 10 ** -e


_T = 10 / 3.0

# One curve segment probed in 3ds Max 2020 (open SplineShape of two Bezier-corner knots, steps 6, optimize, under an
# Extrude; 3,359 segments): name, p0, c1, c2, p3, points. One probe step on either side of each boundary of its
# straight test (at t 0.4 and 0.6 the curve turns p0 -> point -> p3 by at most 2 degrees; maxdrop-em3.142).
STRAIGHT_PROBES = [
    # c1 off the chord by 10^-e chords at a third (at 0.001, at the far end), c2 on the chord at two thirds
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
        segment out of the Bezier knot gets its 6 steps); the vectors are the ones 3ds Max stored."""
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
        the chord's end or lie a little off it (a curved one gets steps, counted by a rule MaxDrop only
        approximates: maxdrop-6n0.6.11)."""
        for name, p0, c1, c2, p3, points in STRAIGHT_PROBES:
            if points == 2:
                self.assertEqual(_points(_shape([_segment(p0, c1, c2, p3)], adaptive=True)), 2, name)


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
        self.assertEqual(len(issues), 2)  # segments, patch output (grid caps and shape IDs are made)
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

    def test_a_lone_cap_of_a_downward_extrusion_faces_as_upwards(self):
        """3ds Max 2020 (a Circle extruded -4): Cap Start alone faces -Z (ID 2), Cap End alone +Z (ID 1), into the
        solid; with both on they face out (ID 1 at the shape); the sides face out in every case."""
        for start, end, want in ((True, False, [(extrude.BOTTOM_ID, False)]), (False, True, [(extrude.TOP_ID, True)]),
                                 (True, True, [(extrude.TOP_ID, True), (extrude.BOTTOM_ID, False)])):
            data, _issues = extrude.extrude(_shape([self.square(4)]), self.params(amount=-4.0, cap_start=start,
                                                                                  cap_end=end))
            caps = sorted({(int(_mats(data)[f]), _face_area_z(data, f) > 0) for f in range(len(data.loop_starts))
                           if int(_mats(data)[f]) != extrude.SIDE_ID})
            self.assertEqual(caps, sorted(want), (start, end))
            sides = [f for f in range(len(data.loop_starts)) if int(_mats(data)[f]) == extrude.SIDE_ID]
            p = data.positions.astype(numpy.float64)
            for f in sides:  # outward: the face normal points away from the square's center
                s, t = int(data.loop_starts[f]), int(data.loop_totals[f])
                q = p[data.loop_vertices[s:s + t]]
                n = numpy.cross(q[1] - q[0], q[2] - q[0])
                self.assertGreater(float(numpy.dot(n[:2], q.mean(axis=0)[:2] - (2.0, 2.0))), 0, (start, end))

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
            with mock.patch.object(extrude, patch, value):
                data, issues = self.make("Rect30x20")
            self.assertEqual(len(data.positions), len(morph.positions), patch)
            self.assertEqual(len(issues), 1, patch)
            self.assertIn("1 grid cap made as morph cap: " + reason, issues[0], patch)
        with mock.patch.object(extrude, "MAX_GRID_TESTS", 10):
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

        with mock.patch.object(extrude, "triangulate", folded):
            data, issues = self.make("Rect30x20")
        self.assertEqual(len(data.positions), 8)
        self.assertEqual(issues, ["1 grid cap made as morph cap: its band does not triangulate"])

    def test_a_refused_grid_on_a_holed_cap_left_open_is_named_once(self):
        with mock.patch.object(extrude, "MAX_CAP_POINTS", 5):
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
            with mock.patch.object(extrude, "CROSS_CHUNK", chunk):
                self.assertIs(extrude._crosses(numpy, ring, [10 ** 9]), False, chunk)
                for at in (3, n // 2, n - 2):  # a knot pulled across the far side
                    bent = list(ring)
                    bent[at] = (-ring[at][0] * 1.01, -ring[at][1] * 1.01)
                    self.assertIs(extrude._crosses(numpy, bent, [10 ** 9]), True, (chunk, at))
        self.assertIs(extrude._crosses(numpy, [(0, 0), (4, 0), (8, 0)], [0]), False)  # every edge adjacent

    def test_past_the_budget_the_cap_is_made_unchecked(self):
        with mock.patch.object(extrude, "MAX_CROSS_TESTS", 1):
            data, issues = self.make([_bowtie()])
        self.assertEqual(issues, ["1 closed spline not checked for crossings (more than 1 tests): capped"])
        self.assertEqual(len(data.loop_totals), 6)  # four sides, two caps as before
        tests = [5]
        self.assertIsNone(extrude._crosses(numpy, [(0, 0), (10, 10), (10, 0), (0, 10)], [0]))
        self.assertIs(extrude._crosses(numpy, [(0, 0), (10, 10), (10, 0), (0, 10)], tests), True)
        self.assertLess(tests[0], 5)


if __name__ == "__main__":
    unittest.main()
