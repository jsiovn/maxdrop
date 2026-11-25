# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/extrude/, the Extrude modifier on a shape: no Blender. Every extruded node of the
extrude fixture against its 3ds Max oracle (world bounding box within 1e-3, vertex count, triangle count), closed
manifolds with outward normals for the capped ones, the hole of the holed cap, the open one without caps; material
IDs by the way a face looks and map channel 1's vertex count, range and every corner against the oracle's eval_mesh;
mapping coordinates; 3ds Max's interpolation counts (found with its own Extrude: steps, optimize, adaptive); the ear
clipping of outlines with holes; damaged and hostile parameters.

    python -I -m unittest discover tests
"""
import importlib
import importlib.util
import json
import math
import os
import sys
import types
import unittest
import weakref
from unittest import mock

_TESTS = "maxdrop_unit_tests"  # tests/unit as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_unit_tests.extrude_support import (  # noqa: E402 (after the loader)
    _check_eval_mesh, _edges, _face_area_z, _knots, _PKG, _read_meshes, _shape, _volume, BBOX_TOLERANCE,
    CAPPED, classids, conv, EULER, extrude, FakeBlock, FIXTURE, numpy, patching, pblock,
    reader_modifiers, ROOT, rules, shapes, UNCAPPED,
)


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
        self.assertEqual(mapped, ["FixtureExtAdaptive", "FixtureExtDownEndReal", "FixtureExtDownStart",
                                  "FixtureExtRect"])  # the four with mapping coordinates
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
        self.assertEqual(dict(rep.modifiers_applied), {"Extrude": 13})
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
        self.assertEqual([n.kind for n in desc.nodes], [conv.CURVE] * 14)
        self.assertEqual(len([r for _i, r in desc.issues if r.startswith("extrude: an Extrude above ")]), 13)

    def test_an_extrude_that_cannot_be_read_keeps_the_curve(self):
        with mock.patch.object(extrude, "read_params", side_effect=extrude.ExtrudeError("refused")):
            desc = conv.read(FIXTURE)
        self.assertEqual([n.kind for n in desc.nodes], [conv.CURVE] * 14)
        self.assertEqual([r for _i, r in desc.issues], ["extrude: refused"] * 13)
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

        with mock.patch.object(extrude, "extrude", extruding), patching.patch_all(conv, "mesh_description",
                                                                                  describing):
            conv.read(FIXTURE)
        self.assertEqual(len(made), 13)
        self.assertEqual(alive, [1] * 13)  # only the extrusion being described

    def test_a_scene_wide_budget_keeps_the_rest_curves(self):
        with patching.patch_all(conv, "MAX_BUILT_CORNERS", 1):
            desc = conv.read(FIXTURE)
        self.assertEqual(sorted(n.kind for n in desc.nodes), [conv.CURVE] * 13 + [conv.MESH])
        spent = [r for _i, r in desc.issues if r.startswith("extrude: not made: the primitives and extrusions ")]
        self.assertEqual(len(spent), 12)

    def test_a_refused_extrude_is_charged_to_the_scene_budget(self):
        """An Extrude refused after its work (Adaptive's points) counts against MAX_BUILT_CORNERS: the next ones
        are not made."""
        refused = extrude.ExtrudeError("more than 1 vertices", conv.MAX_BUILT_CORNERS)
        with mock.patch.object(extrude, "extrude", side_effect=refused):
            desc = conv.read(FIXTURE)
        self.assertEqual([n.kind for n in desc.nodes], [conv.CURVE] * 14)
        self.assertEqual(len([r for _i, r in desc.issues if r == "extrude: more than 1 vertices"]), 1)
        spent = [r for _i, r in desc.issues if r.startswith("extrude: not made: the primitives and extrusions ")]
        self.assertEqual(len(spent), 12)

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

        patches = (patching.patch_all(conv, "_evaluated", evaluated),
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

        with patching.patch_all(conv, "_evaluated", evaluated),                 mock.patch.object(rules, "is_convertible", lambda m: m is shared),                 mock.patch.object(rules, "convert", converting):
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


_RECT = [(0, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0)]
_NEG_SHAPES = {
    "rect": lambda: [shapes.Spline(_knots(_RECT), True)],
    "open": lambda: [shapes.Spline(_knots(_RECT[:3]), False)],
    "z3": lambda: [shapes.Spline(_knots([(x, y, 3) for x, y, _z in _RECT]), True)],
    "cw": lambda: [shapes.Spline(_knots(_RECT[::-1]), True)],
    "hole": lambda: [shapes.Spline(_knots(_RECT), True),
                     shapes.Spline(_knots([(5, 3, 0), (15, 3, 0), (15, 7, 0), (5, 7, 0)]), True)],
}
# maxdrop-6n0.6.10, 3ds Max 2020 (3dsmaxbatch, snapshotAsMesh, object space): node: (shape, amount, segments,
# cap start, cap end, Real-World Map Size); every corner as "x y z u v" (W 0), then each triangle as "ID:corners".
NEG_PROBES = {
    "PosS3RW": ("rect", 5.0, 3, True, True, True),
    "NegS1": ("rect", -5.0, 1, True, True, False),
    "NegS3RW": ("rect", -5.0, 3, True, True, True),
    "NegS3Start": ("rect", -5.0, 3, True, False, False),
    "NegS3EndRW": ("rect", -5.0, 3, False, True, True),
    "NegS2Open": ("open", -5.0, 2, True, True, False),
    "NegS2Z3RW": ("z3", -5.0, 2, True, True, True),
    "NegS2CW": ("cw", -5.0, 2, True, True, False),
    "MNegHoleStart": ("hole", -5.0, 1, True, False, False),
}
NEG_MESHES = {
    'PosS3RW': (
        '0 0 0 0 0, 20 0 0 20 0, 20 0 1.66667 20 1.66667, 0 0 1.66667 0 1.66667, 20 10 0 30 0, '
        '20 10 1.66667 30 1.66667, 0 10 0 50 0, 0 10 1.66667 50 1.66667, 0 0 0 60 0, 0 0 1.66667 60 1.66667, '
        '20 0 3.33333 20 3.33333, 0 0 3.33333 0 3.33333, 20 10 3.33333 30 3.33333, 0 10 3.33333 50 3.33333, '
        '0 0 3.33333 60 3.33333, 20 0 5 20 5, 0 0 5 0 5, 20 10 5 30 5, 0 10 5 50 5, 0 0 5 60 5, 20 10 0 20 10, '
        '0 10 0 0 10, 20 10 5 20 10, 0 10 5 0 10, 0 0 5 0 0, 20 0 5 20 0',
        '3:0,1,2 3:0,2,3 3:1,4,5 3:1,5,2 3:4,6,7 3:4,7,5 3:6,8,9 3:6,9,7 3:3,2,10 3:3,10,11 3:2,5,12 3:2,12,10 '
        '3:5,7,13 3:5,13,12 3:7,9,14 3:7,14,13 3:11,10,15 3:11,15,16 3:10,12,17 3:10,17,15 3:12,13,18 3:12,18,17 '
        '3:13,14,19 3:13,19,18 2:20,0,21 2:20,1,0 1:22,23,24 1:22,24,25'),
    'NegS1': (
        '0 0 -5 0 0, 20 0 -5 0.333333 0, 20 0 0 0.333333 1, 0 0 0 0 1, 20 10 -5 0.5 0, 20 10 0 0.5 1, '
        '0 10 -5 0.833333 0, 0 10 0 0.833333 1, 0 0 -5 1 0, 0 0 0 1 1, 20 10 -5 1 1, 0 10 -5 0 1, 20 0 -5 1 0, '
        '20 10 0 1 1, 0 10 0 0 1, 0 0 0 0 0, 20 0 0 1 0',
        '3:0,1,2 3:0,2,3 3:1,4,5 3:1,5,2 3:4,6,7 3:4,7,5 3:6,8,9 3:6,9,7 2:10,0,11 2:10,12,0 1:13,14,15 1:13,15,16'),
    'NegS3RW': (
        '0 0 -5 0 0, 20 0 -5 20 0, 20 0 -3.33333 20 -1.66667, 0 0 -3.33333 0 -1.66667, 20 10 -5 30 0, '
        '20 10 -3.33333 30 -1.66667, 0 10 -5 50 0, 0 10 -3.33333 50 -1.66667, 0 0 -5 60 0, 0 0 -3.33333 60 -1.66667, '
        '20 0 -1.66667 20 -3.33333, 0 0 -1.66667 0 -3.33333, 20 10 -1.66667 30 -3.33333, 0 10 -1.66667 50 -3.33333, '
        '0 0 -1.66667 60 -3.33333, 20 0 0 20 -5, 0 0 0 0 -5, 20 10 0 30 -5, 0 10 0 50 -5, 0 0 0 60 -5, 20 10 -5 20 10, '
        '0 10 -5 0 10, 20 10 0 20 10, 0 10 0 0 10, 0 0 0 0 0, 20 0 0 20 0',
        '3:0,1,2 3:0,2,3 3:1,4,5 3:1,5,2 3:4,6,7 3:4,7,5 3:6,8,9 3:6,9,7 3:3,2,10 3:3,10,11 3:2,5,12 3:2,12,10 '
        '3:5,7,13 3:5,13,12 3:7,9,14 3:7,14,13 3:11,10,15 3:11,15,16 3:10,12,17 3:10,17,15 3:12,13,18 3:12,18,17 '
        '3:13,14,19 3:13,19,18 2:20,0,21 2:20,1,0 1:22,23,24 1:22,24,25'),
    'NegS3Start': (
        '0 0 -5 0 0, 20 0 -5 0.333333 0, 20 0 -3.33333 0.333333 0.333333, 0 0 -3.33333 0 0.333333, 20 10 -5 0.5 0, '
        '20 10 -3.33333 0.5 0.333333, 0 10 -5 0.833333 0, 0 10 -3.33333 0.833333 0.333333, 0 0 -5 1 0, '
        '0 0 -3.33333 1 0.333333, 20 0 -1.66667 0.333333 0.666667, 0 0 -1.66667 0 0.666667, '
        '20 10 -1.66667 0.5 0.666667, 0 10 -1.66667 0.833333 0.666667, 0 0 -1.66667 1 0.666667, 20 0 0 0.333333 1, '
        '0 0 0 0 1, 20 10 0 0.5 1, 0 10 0 0.833333 1, 0 0 0 1 1, 20 10 -5 1 1, 0 10 -5 0 1, 20 0 -5 1 0',
        '3:0,1,2 3:0,2,3 3:1,4,5 3:1,5,2 3:4,6,7 3:4,7,5 3:6,8,9 3:6,9,7 3:3,2,10 3:3,10,11 3:2,5,12 3:2,12,10 '
        '3:5,7,13 3:5,13,12 3:7,9,14 3:7,14,13 3:11,10,15 3:11,15,16 3:10,12,17 3:10,17,15 3:12,13,18 3:12,18,17 '
        '3:13,14,19 3:13,19,18 2:20,0,21 2:20,22,0'),
    'NegS3EndRW': (
        '0 0 -5 0 0, 20 0 -5 20 0, 20 0 -3.33333 20 -1.66667, 0 0 -3.33333 0 -1.66667, 20 10 -5 30 0, '
        '20 10 -3.33333 30 -1.66667, 0 10 -5 50 0, 0 10 -3.33333 50 -1.66667, 0 0 -5 60 0, 0 0 -3.33333 60 -1.66667, '
        '20 0 -1.66667 20 -3.33333, 0 0 -1.66667 0 -3.33333, 20 10 -1.66667 30 -3.33333, 0 10 -1.66667 50 -3.33333, '
        '0 0 -1.66667 60 -3.33333, 20 0 0 20 -5, 0 0 0 0 -5, 20 10 0 30 -5, 0 10 0 50 -5, 0 0 0 60 -5, 20 10 0 20 10, '
        '0 10 0 0 10, 0 0 0 0 0, 20 0 0 20 0',
        '3:0,1,2 3:0,2,3 3:1,4,5 3:1,5,2 3:4,6,7 3:4,7,5 3:6,8,9 3:6,9,7 3:3,2,10 3:3,10,11 3:2,5,12 3:2,12,10 '
        '3:5,7,13 3:5,13,12 3:7,9,14 3:7,14,13 3:11,10,15 3:11,15,16 3:10,12,17 3:10,17,15 3:12,13,18 3:12,18,17 '
        '3:13,14,19 3:13,19,18 1:20,21,22 1:20,22,23'),
    'NegS2Open': (
        '0 0 -5 0 0, 20 0 -5 0.666667 0, 20 0 -2.5 0.666667 0.5, 0 0 -2.5 0 0.5, 20 10 -5 1 0, 20 10 -2.5 1 0.5, '
        '20 0 0 0.666667 1, 0 0 0 0 1, 20 10 0 1 1',
        '3:0,1,2 3:0,2,3 3:1,4,5 3:1,5,2 3:3,2,6 3:3,6,7 3:2,5,8 3:2,8,6'),
    'NegS2Z3RW': (
        '0 0 -2 0 0, 20 0 -2 20 0, 20 0 0.5 20 -2.5, 0 0 0.5 0 -2.5, 20 10 -2 30 0, 20 10 0.5 30 -2.5, 0 10 -2 50 0, '
        '0 10 0.5 50 -2.5, 0 0 -2 60 0, 0 0 0.5 60 -2.5, 20 0 3 20 -5, 0 0 3 0 -5, 20 10 3 30 -5, 0 10 3 50 -5, '
        '0 0 3 60 -5, 20 10 -2 20 10, 0 10 -2 0 10, 20 10 3 20 10, 0 10 3 0 10, 0 0 3 0 0, 20 0 3 20 0',
        '3:0,1,2 3:0,2,3 3:1,4,5 3:1,5,2 3:4,6,7 3:4,7,5 3:6,8,9 3:6,9,7 3:3,2,10 3:3,10,11 3:2,5,12 3:2,12,10 '
        '3:5,7,13 3:5,13,12 3:7,9,14 3:7,14,13 2:15,0,16 2:15,1,0 1:17,18,19 1:17,19,20'),
    'NegS2CW': (
        '0 0 -5 0 0, 20 0 -5 0.333333 0, 20 0 -2.5 0.333333 0.5, 0 0 -2.5 0 0.5, 20 10 -5 0.5 0, 20 10 -2.5 0.5 0.5, '
        '0 10 -5 0.833333 0, 0 10 -2.5 0.833333 0.5, 0 0 -5 1 0, 0 0 -2.5 1 0.5, 20 0 0 0.333333 1, 0 0 0 0 1, '
        '20 10 0 0.5 1, 0 10 0 0.833333 1, 0 0 0 1 1, 20 10 -5 1 1, 0 10 -5 0 1, 20 0 -5 1 0, 20 10 0 1 1, 0 10 0 0 1, '
        '0 0 0 0 0, 20 0 0 1 0',
        '3:0,1,2 3:0,2,3 3:1,4,5 3:1,5,2 3:4,6,7 3:4,7,5 3:6,8,9 3:6,9,7 3:3,2,10 3:3,10,11 3:2,5,12 3:2,12,10 '
        '3:5,7,13 3:5,13,12 3:7,9,14 3:7,14,13 2:15,0,16 2:15,17,0 1:18,19,20 1:18,20,21'),
    'MNegHoleStart': (
        '0 0 -5 0 0, 20 0 -5 0.333333 0, 20 0 0 0.333333 1, 0 0 0 0 1, 20 10 -5 0.5 0, 20 10 0 0.5 1, '
        '0 10 -5 0.833333 0, 0 10 0 0.833333 1, 0 0 -5 1 0, 0 0 0 1 1, 5 7 -5 0 0, 15 7 -5 0.357143 0, '
        '15 7 0 0.357143 1, 5 7 0 0 1, 15 3 -5 0.5 0, 15 3 0 0.5 1, 5 3 -5 0.857143 0, 5 3 0 0.857143 1, 5 7 -5 1 0, '
        '5 7 0 1 1, 5 3 -5 0.25 0.3, 5 7 -5 0.25 0.7, 20 0 -5 1 0, 15 3 -5 0.75 0.3, 0 10 -5 0 1, 20 10 -5 1 1, '
        '15 7 -5 0.75 0.7',
        '3:0,1,2 3:0,2,3 3:1,4,5 3:1,5,2 3:4,6,7 3:4,7,5 3:6,8,9 3:6,9,7 3:10,11,12 3:10,12,13 3:11,14,15 3:11,15,12 '
        '3:14,16,17 3:14,17,15 3:16,18,19 3:16,19,17 2:20,0,21 2:20,22,0 2:23,22,20 2:24,21,0 2:25,21,24 2:25,26,21 '
        '2:22,26,25 2:23,26,22'),
}


def _probe_faces(corners, triangles):
    """[(positions, uvws, material ID)] of a NEG_MESHES entry: 3ds Max's triangles."""
    pts = [[float(x) for x in c.split()] for c in corners.split(", ")]
    out = []
    for t in triangles.split():
        mat, ids = t.split(":")
        cs = [pts[int(i)] for i in ids.split(",")]
        out.append(([c[:3] for c in cs], [c[3:5] + [0.0] for c in cs], int(mat)))
    return out


@unittest.skipIf(numpy is None, "numpy missing")
class NegativeAmount(unittest.TestCase):
    """An Extrude downwards (maxdrop-6n0.6.10): the sides' V runs from the far level, with Real-World Map Size times
    the signed amount, and Cap Start lies at the far level, lone or not."""

    def test_every_corner_equals_3ds_max(self):
        """Position, facing, UVW and material ID of every corner, both ways, against 3ds Max 2020's triangles."""
        for name, (shape, amount, segs, start, end, real) in NEG_PROBES.items():
            params = extrude.DEFAULT._replace(amount=amount, segments=segs, cap_start=start, cap_end=end,
                                              mapping=True, material_ids=True, real_world=real)
            data, issues = extrude.extrude(_shape(_NEG_SHAPES[shape]()), params)
            self.assertEqual(issues, [], name)
            self.assertEqual(int((data.loop_totals - 2).sum()), len(NEG_MESHES[name][1].split()), name)
            theirs = _corners(_probe_faces(*NEG_MESHES[name]))
            got = _corners(_reader_faces(data))
            self.assertEqual(_unmatched(theirs, got), [], name)
            self.assertEqual(_unmatched(got, theirs), [], name)

    def test_side_v_by_level(self):
        """V of each level from the shape (level 0) to the far one, as the probes give it (amount -0.75 in 4
        segments: 1, 0.75, 0.5, 0.25, 0; Real-World -0.75 .. 0)."""
        for amount, real, want in ((-0.75, False, [1, 0.75, 0.5, 0.25, 0]), (-0.75, True, [-0.75, -0.5625, -0.375,
                                                                                           -0.1875, 0]),
                                   (0.75, False, [0, 0.25, 0.5, 0.75, 1]), (0.75, True, [0, 0.1875, 0.375, 0.5625,
                                                                                         0.75])):
            params = extrude.DEFAULT._replace(amount=amount, segments=4, mapping=True, real_world=real)
            data, _issues = extrude.extrude(_shape(_NEG_SHAPES["rect"]()), params)
            ch = data.maps[1]
            vs = {}
            for f in range(len(data.loop_starts)):
                s, t = int(data.loop_starts[f]), int(data.loop_totals[f])
                if int(data.material_ids[f]) != extrude.SIDE_ID:
                    continue
                for v, i in zip(data.loop_vertices[s:s + t].tolist(), ch.indices[s:s + t].tolist()):
                    level = round(float(data.positions[v][2]) / amount * 4)
                    vs.setdefault(level, set()).add(round(float(ch.uvw[i][1]), 6))
            self.assertEqual([sorted(vs[k]) for k in range(5)], [[w] for w in want], (amount, real))


if __name__ == "__main__":
    unittest.main()
