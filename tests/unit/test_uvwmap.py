# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/uvwmap.py, the UVW Map modifier: no Blender. Every node of every fixture whose oracle
dumps an evaluated map channel (eval_maps) and whose whole stack MaxDrop evaluates: per triangle corner of 3ds Max's
mesh, matched to the face corner of the built mesh by world position and face normal, U and V within 1e-4 (planar,
box) or 1e-3 (cylindrical, spherical: U up to a whole turn per face, the poles left out), and W the same way through
the modifier alone; the parameters as the fixture script set them; what is not evaluated (shrink-wrap, a UVW Map
above a Bend, a switched-off one) keeps the stored channel; damaged and hostile parameters.

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
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
FIXTURE = os.path.join(FIXTURES, "uvwmap.max")
TOLERANCE = {"planar": 1e-4, "box": 1e-4, "cylindrical": 1e-3, "spherical": 1e-3}
POSITION_TOLERANCE = 1e-3  # the oracle keeps 6 significant digits
POLE = 1e-3  # a spherical corner this close to v = 0 or 1 (before tiling) has no angle to compare

_PKG = "maxdrop_convert_test"  # the same package as test_convert_scene: the add-on's __init__ never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
conv = importlib.import_module(_PKG + ".convert.scene")
uvwmap = importlib.import_module(_PKG + ".convert.uvwmap")
report = importlib.import_module(_PKG + ".convert.report")
cfb = importlib.import_module(_PKG + ".reader.cfb")
classids = importlib.import_module(_PKG + ".reader.classids")
controllers = importlib.import_module(_PKG + ".reader.controllers")
geometry = importlib.import_module(_PKG + ".reader.geometry")
pblock = importlib.import_module(_PKG + ".reader.pblock")
reader_modifiers = importlib.import_module(_PKG + ".reader.modifiers")
reader_scene = importlib.import_module(_PKG + ".reader.scene")

# From tools/fixtures/uvwmap.ms: (type, U V W tile, U V W flip, cap, length width height, alignment, channel,
# real-world) of each node's UVW Maps, bottom first.
PARAMS = {
    "FixtureUVWPlanar": [("planar", (1, 1, 1), (0, 0, 0), 0, (20, 30, 10), 2, 1, 0)],
    "FixtureUVWGizmo": [("planar", (2, 3, 1.5), (1, 0, 0), 0, (17, 23, 13), 2, 2, 0)],
    "FixtureUVWBox": [("box", (1, 1, 1), (0, 1, 0), 0, (17, 23, 13), 2, 1, 0)],
    "FixtureUVWCyl": [("cylindrical", (1, 1, 2), (0, 0, 1), 1, (16, 16, 16), 2, 1, 0)],
    "FixtureUVWCylAxisX": [("cylindrical", (1, 1, 1), (0, 0, 0), 1, (17, 23, 13), 0, 1, 0)],
    "FixtureUVWSphere": [("spherical", (2, 1, 1), (0, 0, 0), 0, (16, 16, 16), 2, 1, 0)],
    "FixtureUVWAxisY": [("planar", (1, 1, 1), (0, 0, 0), 0, (20, 30, 10), 1, 1, 0)],
    "FixtureUVWRealWorld": [("planar", (1, 4, 1), (0, 0, 0), 0, (7, 60, 3), 2, 1, 1)],
    "FixtureUVWSharedA": [("planar", (1, 1, 1), (0, 0, 0), 0, (25, 65, 25), 2, 1, 0)],
    "FixtureUVWSharedB": [("planar", (1, 1, 1), (0, 0, 0), 0, (25, 65, 25), 2, 1, 0)],
    "FixtureUVWExtrude": [("box", (1, 1, 1), (0, 0, 0), 0, (30, 40, 25), 2, 1, 0)],
    "FixtureUVWTwo": [("planar", (1, 1, 1), (0, 0, 0), 0, (20, 30, 10), 2, 1, 0),
                      ("spherical", (1, 1, 1), (0, 0, 0), 0, (20, 30, 10), 0, 3, 0)],
    "FixtureUVWShrink": [("shrink-wrap", (1, 1, 1), (0, 0, 0), 0, (20, 30, 10), 2, 1, 0)],
    "FixtureUVWOff": [("planar", (1, 1, 1), (0, 0, 0), 0, (5, 5, 10), 2, 1, 0)],
    "FixtureUVWAboveBend": [("cylindrical", (1, 1, 1), (0, 0, 0), 0, (20, 34.835, 11.696), 2, 1, 0)],
}
NOT_EVALUATED = ("FixtureUVWShrink", "FixtureUVWOff", "FixtureUVWAboveBend")


def _fixtures():
    out = []
    for path in sorted(glob.glob(os.path.join(FIXTURES, "*.max"))):
        with open(path[:-4] + ".oracle.json", encoding="utf-8") as f:
            oracle = json.load(f)
        if any(n["eval_maps"] for n in oracle["nodes"]):
            out.append((path, oracle))
    return out


def _match(tri_points, tri_normal, corners, normals, faces):
    """The face corners (loop indices) of the built mesh at the three oracle corners, all on one face whose normal
    agrees; None when no face holds them."""
    picks = []
    for p in tri_points:
        near = numpy.flatnonzero(numpy.abs(corners - p).max(axis=1) <= POSITION_TOLERANCE * max(1.0, abs(p).max()))
        picks.append(near)
    common = set(faces[picks[0]].tolist())
    for near in picks[1:]:
        common &= set(faces[near].tolist())
    common = [f for f in common if numpy.dot(normals[f], tri_normal) > 0.99]
    if len(common) != 1:
        return None
    f = common[0]
    return [int(near[faces[near] == f][0]) for near in picks]


def _around_the_axis(u, tile):
    """Whether the U values of one face of a round map need more than half a turn whichever way round: the face goes
    around the map's axis, where U has no single answer (3ds Max's own then depends on how it shares map vertices)."""
    raw = numpy.sort((u / tile) % 1.0)
    gaps = numpy.diff(numpy.concatenate((raw, raw[:1] + 1.0)))
    return 1.0 - float(gaps.max()) > 0.5


def _compare(case, label, kind, tile, ours, theirs, poles, face_u):
    """ours, theirs: (3, k) coordinates of one triangle; U may differ by a whole turn (times its tile) for the round
    types, and is not compared on a face around the axis (face_u: the U of every corner of the built face)."""
    tolerance = TOLERANCE[kind]
    d = ours - theirs
    if kind in ("cylindrical", "spherical"):
        keep = ~poles
        if not keep.any():
            return
        turn = round(float(d[keep, 0].mean()) / tile)
        d[:, 0] -= turn * tile
        d = d[keep]
        if numpy.abs(d[:, 0]).max() > tolerance and _around_the_axis(face_u, tile):
            d = d[:, 1:]
    case.assertLessEqual(float(numpy.abs(d).max()), tolerance, "%s: %s vs %s" % (label, ours.tolist(),
                                                                                theirs.tolist()))


def _face_normals(p, md):
    out = numpy.zeros((len(md.loop_starts), 3))
    for f, (s, t) in enumerate(zip(md.loop_starts.tolist(), md.loop_totals.tolist())):
        q = p[md.loop_vertices[s:s + t]]
        n = numpy.cross(q[1] - q[0], q[2] - q[0]) if t == 3 else \
            sum(numpy.cross(q[k], q[(k + 1) % t]) for k in range(t))
        out[f] = n / (numpy.linalg.norm(n) or 1.0)
    return out


@unittest.skipIf(numpy is None, "numpy missing")
class Fixtures(unittest.TestCase):
    """Every fixture with a UVW Map, against its oracle."""

    @classmethod
    def setUpClass(cls):
        cls.cases = [(path, oracle, conv.read(path)) for path, oracle in _fixtures()]

    def test_the_fixtures_with_a_uvw_map(self):
        self.assertEqual(sorted(os.path.basename(p) for p, _o, _d in self.cases),
                         ["modifier_pivot.max", "stack_basic.max", "uvwmap.max", "uvwmap_oblique.max"])

    def test_uv_of_every_corner_equals_the_oracle(self):
        compared = 0
        for path, oracle, desc in self.cases:
            kinds = self.kinds(path)
            for node, o in zip(desc.nodes, oracle["nodes"]):
                # a converted modifier changes the mesh in Blender, after the UVs MaxDrop makes
                if not o["eval_maps"] or node.kind != conv.MESH or node.modifiers or node.converted:
                    continue
                md = desc.meshes[node.mesh]
                m = numpy.asarray(node.world, dtype=numpy.float64)
                p = (numpy.asarray(md.positions, dtype=numpy.float64) @ m[:3, :3].T + m[:3, 3]) / desc.meters
                if numpy.linalg.det(m[:3, :3]) < 0:
                    self.fail("a mirrored node in a UVW Map fixture: the normals below would be turned")
                normals = _face_normals(p, md)
                faces = numpy.repeat(numpy.arange(len(md.loop_starts)), md.loop_totals)
                corners = p[md.loop_vertices]
                layers = dict(md.uv_layers)
                for channel in o["eval_maps"]:
                    ch = channel["channel"]
                    kind, tile = kinds[(o["name"], ch)]
                    uv = layers[conv.UV_FIRST if ch == 1 else conv.UV_NAME % ch]
                    c = numpy.asarray(channel["corners"], dtype=numpy.float64)
                    for t in range(0, len(c), 3):
                        tri = c[t:t + 3]
                        loops = _match(tri[:, :3], tri[0, 3:6], corners, normals, faces)
                        label = "%s %s channel %d triangle %d" % (os.path.basename(path), o["name"], ch, t // 3)
                        self.assertIsNotNone(loops, label)
                        poles = numpy.abs(tri[:, 7] / tile[1] - 0.5) > 0.5 - POLE if kind == "spherical" else \
                            numpy.zeros(3, dtype=bool)
                        f = faces[loops[0]]
                        face_u = uv[md.loop_starts[f]:md.loop_starts[f] + md.loop_totals[f], 0]
                        _compare(self, label, kind, tile[0], uv[loops].astype(numpy.float64), tri[:, 6:8], poles,
                                 face_u)
                        compared += 1
        self.assertEqual(compared, 1168)  # the triangles of the 17 nodes whose stack is evaluated

    def kinds(self, path):
        """{(node name, channel): (type name, (u tile, v tile))} of the UVW Maps evaluated in path."""
        out = {}
        with cfb.CompoundFile(path) as cf:
            sc = reader_scene.Scene.from_file(cf)
            stacks = reader_modifiers.Modifiers(sc)
            for i in sc.walk():
                node = sc.node(i)
                for m in stacks.stack(node).modifiers:
                    if uvwmap.is_uvwmap(m):
                        p, _issues = uvwmap.read_params(sc, m)
                        out[(node.name, p.channel)] = (p.type_name, (p.utile, p.vtile))
        return out

    def test_w_of_every_corner_equals_the_oracle(self):
        """The whole UVW, the modifiers applied to the reader's mesh in object space (W is not a UV layer)."""
        compared = 0
        with cfb.CompoundFile(FIXTURE) as cf:
            sc = reader_scene.Scene.from_file(cf)
            stacks = reader_modifiers.Modifiers(sc)
            oracle = {n["name"]: n for n in dict((os.path.basename(p), o) for p, o, _d in self.cases)[
                "uvwmap.max"]["nodes"]}
            for i in sc.walk():
                node = sc.node(i)
                o = oracle[node.name]
                st = stacks.stack(node)
                mesh = sc.entry(st.base).superclass == classids.SC_GEOMOBJECT  # not the extruded shape
                if node.name in NOT_EVALUATED or not o["eval_maps"] or not mesh:
                    continue
                data = geometry.read_mesh(sc, st.base)
                kinds = {}
                for m in st.modifiers:
                    p, _issues = uvwmap.read_params(sc, m)
                    tm, _issues = uvwmap.gizmo(sc, m)
                    data = uvwmap.apply(data, p, tm, m.context.tm)
                    kinds[p.channel] = (p.type_name, (p.utile, p.vtile, p.wtile))
                ot = numpy.asarray(o["object_transform"], dtype=numpy.float64).reshape(4, 3)
                inv = numpy.linalg.inv(numpy.vstack((numpy.hstack((ot, [[0], [0], [0], [1]])))))
                pos = numpy.asarray(data.positions, dtype=numpy.float64)
                md = types.SimpleNamespace(loop_starts=data.loop_starts, loop_totals=data.loop_totals,
                                           loop_vertices=data.loop_vertices)
                normals = _face_normals(pos, md)
                faces = numpy.repeat(numpy.arange(len(data.loop_starts)), data.loop_totals)
                corners = pos[data.loop_vertices]
                for channel in o["eval_maps"]:
                    kind, tile = kinds[channel["channel"]]
                    mc = data.maps[channel["channel"]]
                    uvw = mc.uvw[mc.indices].astype(numpy.float64)
                    c = numpy.asarray(channel["corners"], dtype=numpy.float64)
                    local = numpy.hstack((c[:, :3], numpy.ones((len(c), 1)))) @ inv
                    local_n = c[:, 3:6] @ ot[:3].T  # the fixture's nodes are not scaled: rotation only
                    for t in range(0, len(c), 3):
                        tri = c[t:t + 3]
                        loops = _match(local[t:t + 3, :3], local_n[t], corners, normals, faces)
                        label = "%s triangle %d" % (node.name, t // 3)
                        self.assertIsNotNone(loops, label)
                        poles = numpy.abs(tri[:, 7] / tile[1] - 0.5) > 0.5 - POLE if kind == "spherical" else \
                            numpy.zeros(3, dtype=bool)
                        f = faces[loops[0]]
                        face_u = uvw[data.loop_starts[f]:data.loop_starts[f] + md.loop_totals[f], 0]
                        _compare(self, label, kind, tile[0], uvw[loops], tri[:, 6:9], poles, face_u)
                        compared += 1
        self.assertEqual(compared, 800)  # the same, but FixtureUVWExtrude (a shape)

    def test_parameters_as_the_script_set_them(self):
        with cfb.CompoundFile(FIXTURE) as cf:
            sc = reader_scene.Scene.from_file(cf)
            stacks = reader_modifiers.Modifiers(sc)
            seen = {}
            for i in sc.walk():
                node = sc.node(i)
                got = []
                for m in stacks.stack(node).modifiers:
                    if not uvwmap.is_uvwmap(m):
                        continue
                    p, issues = uvwmap.read_params(sc, m)
                    self.assertEqual(issues, [], node.name)
                    got.append((p.type_name, (p.utile, p.vtile, p.wtile), (p.uflip, p.vflip, p.wflip), p.cap,
                tuple(round(x, 3) for x in (p.length, p.width, p.height)), p.axis, p.channel,
                                p.real_world))
                seen[node.name] = got
        want = {k: [(t, tuple(map(float, tl)), tuple(map(bool, fl)), bool(cap), tuple(map(float, size)), axis, ch,
                     bool(rw)) for t, tl, fl, cap, size, axis, ch, rw in v] for k, v in PARAMS.items()}
        self.assertEqual(seen, want)

    def test_what_is_not_evaluated_keeps_the_stored_channel(self):
        _path, oracle, desc = next(c for c in self.cases if c[0] == FIXTURE)
        nodes = {n.name: n for n in desc.nodes}
        planar = desc.meshes[nodes["FixtureUVWPlanar"].mesh]
        for name in NOT_EVALUATED:
            node = nodes[name]
            self.assertEqual(node.applied, (), name)
            self.assertIn("UVW Map", node.modifiers, name)
            self.assertEqual(len(node.mesh), 2, name)  # (base, offset): the base mesh as stored
            md = desc.meshes[node.mesh]
            # the stored channel of a box with mapcoords: each side 0..1, not the planar projection of the box
            self.assertFalse(numpy.allclose(md.uv_layers[0][1], planar.uv_layers[0][1]), name)
        self.assertEqual(sorted(r for _i, r in desc.issues),
                         ["uvw map: a UVW Map above Bend is not evaluated",
                          "uvw map: shrink-wrap mapping is not evaluated: the stored channel stays"])

    def test_the_report_counts_uvw_map_as_applied(self):
        _path, _oracle, desc = next(c for c in self.cases if c[0] == FIXTURE)
        nodes = {n.name: n for n in desc.nodes}
        self.assertEqual(nodes["FixtureUVWExtrude"].applied, ("Extrude", "UVW Map"))
        self.assertEqual(nodes["FixtureUVWTwo"].applied, ("UVW Map", "UVW Map"))
        rep = report.gather(desc)
        self.assertEqual(dict(rep.modifiers_applied), {"UVW Map": 12, "Extrude": 1})
        self.assertEqual(dict(rep.modifiers), {"UVW Map": 3, "Bend": 1})

    def test_the_shared_modifier_keys_a_mesh_per_context(self):
        _path, _oracle, desc = next(c for c in self.cases if c[0] == FIXTURE)
        nodes = {n.name: n for n in desc.nodes}
        a, b = nodes["FixtureUVWSharedA"].mesh, nodes["FixtureUVWSharedB"].mesh
        self.assertEqual(a[2][0], b[2][0])  # one modifier
        self.assertNotEqual(a[2][1], b[2][1])  # two contexts

    def test_a_uvw_map_that_cannot_be_read_keeps_the_stored_channel(self):
        with mock.patch.object(uvwmap, "read_params", side_effect=uvwmap.UVWMapError("refused")):
            desc = conv.read(FIXTURE)
        self.assertTrue(all(n.applied in ((), ("Extrude",)) for n in desc.nodes))
        self.assertEqual(len([r for _i, r in desc.issues if r == "uvw map: refused: the stored channel stays"]), 13)

    def test_a_gizmo_that_cannot_be_evaluated_keeps_the_stored_channel(self):
        bad = controllers.Issue(None, 1, None, None, controllers.UNKNOWN_CLASS)
        with mock.patch.object(controllers, "matrix", return_value=(controllers.IDENTITY, [bad])):
            desc = conv.read(FIXTURE)
        self.assertTrue(all("UVW Map" not in n.applied for n in desc.nodes))

    def test_a_vertex_color_uvw_map_is_not_applied(self):
        real = uvwmap.read_params

        def to_vertex_color(scene, m):
            p, issues = real(scene, m)
            return p._replace(vertex_color=True), issues

        with mock.patch.object(uvwmap, "read_params", to_vertex_color):
            desc = conv.read(FIXTURE)
        self.assertTrue(all("UVW Map" not in n.applied for n in desc.nodes))
        self.assertEqual(len([r for _i, r in desc.issues
                              if r == "uvw map: the vertex color channel is not imported: not applied"]), 12)


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
        return uvwmap.chunks.index(DAMAGED_REAL_WORLD)[0]


def _modifier(values):
    return types.SimpleNamespace(index=1, legacy={1: FakeBlock(values)} if values is not None else {},
                                 class_id=classids.UVW_MAP, superclass=classids.SC_OSMODIFIER, refs={}, gizmo=None)


class Parameters(unittest.TestCase):
    def test_values_and_defaults(self):
        p, issues = uvwmap.read_params(FakeScene(), _modifier({0: 4, 1: 2.0, 5: 1, 9: 3.0, 13: 4}))
        self.assertEqual((p.maptype, p.utile, p.vflip, p.length, p.width, p.channel, p.axis, p.real_world),
                         (uvwmap.BOX, 2.0, True, 3.0, 1.0, 4, uvwmap.AXIS_Z, False))
        self.assertEqual(issues, [])
        p, _issues = uvwmap.read_params(FakeScene(), _modifier({8: 1, 13: 4}))
        self.assertEqual(p.channel, 0)  # vertex color

    def test_refused(self):
        for values in (None, {0: pblock.Animated(3)}, {1: float("nan")}, {9: "two"}, {10: (1.0, 2.0, 3.0)},
                       {11: 0.0}, {13: 100}, {13: -1}, {9: float("inf")}):
            with self.assertRaises(uvwmap.UVWMapError, msg=repr(values)):
                uvwmap.read_params(FakeScene(), _modifier(values))

    def test_real_world_is_read_from_its_own_chunk_and_class(self):
        """Real-World Map Size comes from reader.realworld (tests/unit/test_realworld.py has its cases), asked
        for the modifier's own chunk and the UVW Map class; a damaged 0x2150 is off."""
        own = object()
        scene = types.SimpleNamespace(chunk=lambda i: own if i == 1 else None)
        with mock.patch.object(uvwmap.realworld, "flag", return_value=True) as flag:
            p, _issues = uvwmap.read_params(scene, _modifier({}))
        self.assertTrue(p.real_world)
        flag.assert_called_once_with(own, classids.UVW_MAP)
        p, _issues = uvwmap.read_params(FakeScene(), _modifier({}))
        self.assertFalse(p.real_world)

    def test_an_unknown_alignment_is_made_as_z(self):
        p, issues = uvwmap.read_params(FakeScene(), _modifier({12: 7}))
        self.assertEqual((p.axis, len(issues)), (uvwmap.AXIS_Z, 1))

    def test_unsupported_types(self):
        for t in (uvwmap.SHRINK_WRAP, uvwmap.FACE, uvwmap.XYZ_TO_UVW, 42):
            p, _issues = uvwmap.read_params(FakeScene(), _modifier({0: t}))
            self.assertFalse(p.supported, t)
        self.assertEqual(uvwmap.read_params(FakeScene(), _modifier({0: 42}))[0].type_name, "type 42")

    def test_no_gizmo(self):
        with self.assertRaises(uvwmap.UVWMapError):
            uvwmap.gizmo(FakeScene(), _modifier({}))

    def test_is_uvwmap(self):
        self.assertTrue(uvwmap.is_uvwmap(_modifier({})))
        self.assertFalse(uvwmap.is_uvwmap(types.SimpleNamespace(class_id=classids.UVW_MAP,
                                                                superclass=classids.SC_SHAPE)))


def _quad_mesh(points, faces):
    starts, lv = [], []
    for f in faces:
        starts.append(len(lv))
        lv.extend(f)
    return geometry.MeshData(numpy.asarray(points, dtype=numpy.float32), numpy.asarray(lv, dtype=numpy.int32),
                             numpy.asarray(starts, dtype=numpy.int32), numpy.zeros(len(faces), dtype=numpy.uint32),
                             numpy.zeros(len(faces), dtype=numpy.uint16), {})


IDENTITY = controllers.IDENTITY


@unittest.skipIf(numpy is None, "numpy missing")
class Synthetic(unittest.TestCase):
    def params(self, **kw):
        return uvwmap.DEFAULT._replace(**dict(dict(length=2.0, width=2.0, height=2.0), **kw))

    def test_planar_under_identity(self):
        data = _quad_mesh([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [(0, 1, 2, 3)])
        out = uvwmap.apply(data, self.params(), IDENTITY, IDENTITY)
        mc = out.maps[1]
        # the frame turns the gizmo half a turn: -x maps to u = 1
        numpy.testing.assert_allclose(mc.uvw[mc.indices], [(1, 1, 0.5), (0, 1, 0.5), (0, 0, 0.5), (1, 0, 0.5)])
        self.assertEqual(out.maps.keys(), {1})
        self.assertIs(out.positions, data.positions)

    def test_other_channels_stay(self):
        data = _quad_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [(0, 1, 2)])
        data.maps[2] = geometry.MapChannel(2, numpy.zeros((3, 3), dtype=numpy.float32),
                                           numpy.arange(3, dtype=numpy.int32))
        out = uvwmap.apply(data, self.params(map_channel=5), IDENTITY, IDENTITY)
        self.assertEqual(sorted(out.maps), [2, 5])
        self.assertEqual(sorted(data.maps), [2])  # the input is left alone

    def test_a_cylinder_seam_does_not_smear(self):
        # a quad straddling the seam (object -Y: the frame's +Y, where u wraps): U runs on past 1
        data = _quad_mesh([(0.2, -1, -0.5), (-0.2, -1, -0.5), (-0.2, -1, 0.5), (0.2, -1, 0.5)], [(0, 1, 2, 3)])
        out = uvwmap.apply(data, self.params(maptype=uvwmap.CYLINDRICAL), IDENTITY, IDENTITY)
        u = out.maps[1].uvw[:, 0]
        self.assertLess(float(u.max() - u.min()), 0.5)
        self.assertGreater(float(u.max()), 1.0)

    def test_a_pole_takes_the_face_mean(self):
        data = _quad_mesh([(0, 0, 1), (1, -1, 0.5), (1, 1, 0.5)], [(0, 1, 2)])
        out = uvwmap.apply(data, self.params(maptype=uvwmap.SPHERICAL), IDENTITY, IDENTITY)
        u = out.maps[1].uvw[:, 0]
        self.assertAlmostEqual(float(u[0]), float((u[1] + u[2]) / 2), places=6)
        self.assertAlmostEqual(float(out.maps[1].uvw[0, 1]), 1.0, places=6)

    def test_flip_then_tile(self):
        data = _quad_mesh([(-1, -1, 0), (1, -1, 0), (1, 1, 0)], [(0, 1, 2)])
        out = uvwmap.apply(data, self.params(uflip=True, utile=3.0), IDENTITY, IDENTITY)
        numpy.testing.assert_allclose(out.maps[1].uvw[:, 0], [0.0, 3.0, 3.0])

    def test_refused(self):
        data = _quad_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [(0, 1, 2)])
        flat = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        with self.assertRaises(uvwmap.UVWMapError):
            uvwmap.apply(data, self.params(), flat, IDENTITY)
        with self.assertRaises(uvwmap.UVWMapError):
            uvwmap.apply(data, self.params(maptype=uvwmap.FACE), IDENTITY, IDENTITY)
        tiny = self.params(length=1e-300)
        with self.assertRaises(uvwmap.UVWMapError):
            uvwmap.apply(data, tiny, IDENTITY, IDENTITY)

    def test_a_gizmo_is_refused_by_its_shape_not_its_size(self):
        """A uniformly tiny gizmo inverts; one squashed flat relative to its other axes does not."""
        data = _quad_mesh([(-1, -1, 0), (1, -1, 0), (1, 1, 0)], [(0, 1, 2)])

        def scaled(x, y, z):
            return ((x, 0.0, 0.0, 0.0), (0.0, y, 0.0, 0.0), (0.0, 0.0, z, 0.0), (0.0, 0.0, 0.0, 1.0))

        out = uvwmap.apply(data, self.params(), scaled(1e-5, 1e-5, 1e-5), IDENTITY)
        numpy.testing.assert_allclose(out.maps[1].uvw[:, 0], [0.5 + 1e5 / 2, 0.5 - 1e5 / 2, 0.5 - 1e5 / 2], rtol=1e-6)
        for bad in (scaled(1.0, 1.0, 1e-13), scaled(1.0, float("nan"), 1.0), scaled(0.0, 0.0, 0.0)):
            with self.assertRaises(uvwmap.UVWMapError):
                uvwmap.apply(data, self.params(), bad, IDENTITY)

    def test_an_empty_mesh(self):
        data = _quad_mesh([], [])
        data = geometry.MeshData(numpy.zeros((0, 3), dtype=numpy.float32), numpy.zeros(0, dtype=numpy.int32),
                                 numpy.zeros(0, dtype=numpy.int32), numpy.zeros(0, dtype=numpy.uint32),
                                 numpy.zeros(0, dtype=numpy.uint16), {})
        for t in uvwmap.SUPPORTED:
            out = uvwmap.apply(data, self.params(maptype=t, cap=True), IDENTITY, IDENTITY)
            self.assertEqual(out.maps[1].uvw.shape, (0, 3))


if __name__ == "__main__":
    unittest.main()
