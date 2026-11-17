# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/primitives.py: the standard primitives built from their parameter blocks, no Blender.

The primitives fixture (tools/fixtures/primitives.ms): each node's parameters as the script set them; each mesh equal
to the TriMesh 3ds Max built for it (tests/fixtures/primitives.mesh.jsonl, written by the same script): the same
points (order aside), its triangles merged across hidden edges into the same polygons with the same winding, material
IDs, smoothing groups and channel 1 UVs; through convert.scene, the vertex and triangle counts and the world box of
the oracle (tests/fixtures/primitives.oracle.json). Hand-made blocks: defaults, a minimum, an animated parameter, a
parameter that is no number, too many faces, the options not built (Slice, hemispheres), the Plane's render scale.

    python -I -m unittest discover tests
"""
import collections
import importlib
import json
import math
import os
import sys
import types
import unittest

try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "primitives.max")
DUMP = os.path.join(ROOT, "tests", "fixtures", "primitives.mesh.jsonl")
ORACLE = os.path.join(ROOT, "tests", "fixtures", "primitives.oracle.json")
POSITION_TOLERANCE = 2e-4  # relative to the object's size: 3ds Max builds in single precision
UV_TOLERANCE = 2e-4

_PKG = "maxdrop_convert_test"  # the same package as test_convert_scene: the add-on's __init__ never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
prim = importlib.import_module(_PKG + ".convert.primitives")
conv = importlib.import_module(_PKG + ".convert.scene")
classids = importlib.import_module(_PKG + ".reader.classids")
cfb = importlib.import_module(_PKG + ".reader.cfb")
reader_scene = importlib.import_module(_PKG + ".reader.scene")
pblock = importlib.import_module(_PKG + ".reader.pblock")

DEG = math.pi / 180.0
# what tools/fixtures/primitives.ms sets, by node (lengths in the file's units, angles in radians)
EXPECTED = {
    "FixtureBox": ("Box", dict(length=20.0, width=30.0, height=40.0, width_segs=3, length_segs=2, height_segs=4,
                               mapping=True), False),
    "FixtureBoxDown": ("Box", dict(length=10.0, width=12.0, height=-15.0, width_segs=1, length_segs=1,
                                   height_segs=1, mapping=True), True),
    "FixtureBoxNoMap": ("Box", dict(length=10.0, width=10.0, height=10.0, mapping=False), False),
    "FixturePlane": ("Plane", dict(length=20.0, width=30.0, width_segs=3, length_segs=2, density=1.0,
                                   render_scale=1.0, mapping=True), False),
    "FixturePyramid": ("Pyramid", dict(width=20.0, depth=30.0, height=25.0, width_segs=2, depth_segs=3,
                                       height_segs=2), False),
    "FixtureSphere": ("Sphere", dict(radius=10.0, segs=12, smooth=True, hemisphere=0.0, base_to_pivot=False,
                                     slice=False), False),
    "FixtureGeoSphere": ("GeoSphere", dict(radius=10.0, segs=3, base_type=2, smooth=True, hemisphere=False), False),
    "FixtureGeoOcta": ("GeoSphere", dict(radius=8.0, segs=2, base_type=1, smooth=False, base_to_pivot=True), False),
    "FixtureCylinder": ("Cylinder", dict(radius=10.0, height=20.0, height_segs=3, cap_segs=2, sides=10,
                                         smooth=True, slice=False), False),
    "FixtureCone": ("Cone", dict(radius1=8.0, radius2=3.0, height=20.0, height_segs=2, cap_segs=2, sides=9),
                    True),
    "FixtureTube": ("Tube", dict(radius1=10.0, radius2=6.0, height=20.0, height_segs=2, cap_segs=2, sides=8),
                    False),
    "FixtureTorus": ("Torus", dict(radius1=10.0, radius2=3.0, segs=12, sides=8, rotation=20 * DEG, twist=30 * DEG,
                                   smooth=1), False),
    "FixtureTorusOdd": ("Torus", dict(radius1=8.0, radius2=2.0, segs=7, sides=5, smooth=3), True),
}


def _load_dump():
    with open(DUMP, encoding="ascii") as f:
        return {d["name"]: d for d in (json.loads(line) for line in f if line.strip())}


def max_polygons(d):
    """3ds Max's triangles as the polygons it shows: two triangles that share an edge hidden in both, each with only
    that edge hidden and the same material ID, are one quad (the first triangle's loop with the other's far corner
    put in at the hidden edge). [(points, uvs or None, material ID, smoothing groups)]."""
    faces = d["faces"]
    hidden = collections.defaultdict(list)
    for fi, f in enumerate(faces):
        for k in range(3):
            if not f["vis"][k]:
                hidden[frozenset((f["v"][k], f["v"][(k + 1) % 3]))].append(fi)
    used, out = set(), []
    for fi, f in enumerate(faces):
        if fi in used:
            continue
        used.add(fi)
        v, uv = f["v"], f.get("uv")
        loop, loop_uv = list(v), list(uv) if uv else None
        ks = [k for k in range(3) if not f["vis"][k]]
        if len(ks) == 1:
            k = ks[0]
            a, b, c = v[k], v[(k + 1) % 3], v[(k + 2) % 3]
            for gi in hidden[frozenset((a, b))]:
                g = faces[gi]
                if gi in used or sum(1 for x in g["vis"] if not x) != 1 or g["mat"] != f["mat"]:
                    continue
                far = next(x for x in g["v"] if x not in (a, b))
                loop = [a, far, b, c]
                if uv:
                    mine = dict(zip(v, uv))
                    loop_uv = [mine[a], g["uv"][g["v"].index(far)], mine[b], mine[c]]
                used.add(gi)
                break
        out.append(([d["verts"][x] for x in loop], [u[:2] for u in loop_uv] if loop_uv else None, f["mat"], f["sg"]))
    return out


def our_polygons(data):
    lv = data.loop_vertices.tolist()
    starts = data.loop_starts.tolist() + [len(lv)]
    pos = data.positions.tolist()
    uvw = data.maps[1].uvw[data.maps[1].indices].tolist() if 1 in data.maps else None
    out = []
    for f in range(len(starts) - 1):
        loops = range(starts[f], starts[f + 1])
        out.append(([pos[lv[k]] for k in loops], [uvw[k][:2] for k in loops] if uvw else None,
                    int(data.material_ids[f]) + 1, int(data.smoothing_groups[f])))
    return out


def _near(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _on_meridian(p, size):
    """A point on GeoSphere's -X meridian: 3ds Max's single-precision rounding gives it U 0 in some faces and 1 in
    others, which is not reproduced."""
    return p[0] < 0 and abs(p[1]) <= 1e-5 * size


def compare(name, data, d):
    """The differences between MaxDrop's MeshData and 3ds Max's dump d, [] when they agree."""
    size = max(1.0, max(abs(x) for v in d["verts"] for x in v))
    tol = POSITION_TOLERANCE * size
    problems = []
    if len(data.positions) != len(d["verts"]):
        problems.append("%d vertices, 3ds Max %d" % (len(data.positions), len(d["verts"])))
    ours = our_polygons(data)
    left = list(range(len(ours)))
    for pts, uv, mat, sg in max_polygons(d):
        hit = None
        for k in left:
            o = ours[k]
            if len(o[0]) != len(pts):
                continue
            n = len(pts)
            shift = next((r for r in range(n) if all(_near(o[0][(j + r) % n], pts[j], tol) for j in range(n))), None)
            if shift is not None:
                hit = (k, shift)
                break
        if hit is None:
            problems.append("no polygon at %s" % [[round(x, 3) for x in p] for p in pts])
            continue
        k, r = hit
        left.remove(k)
        o = ours[k]
        n = len(pts)
        if (o[2], o[3]) != (mat, sg):
            problems.append("polygon at %s: ID %d group %d, 3ds Max %d %d" % (pts[0], o[2], o[3], mat, sg))
        if (uv is None) != (o[1] is None):
            problems.append("polygon at %s: UVs %s, 3ds Max %s" % (pts[0], o[1] is not None, uv is not None))
        elif uv is not None:
            seam = d["class"] == "GeoSphere" and any(_on_meridian(p, size) for p in pts)
            utol = UV_TOLERANCE * max(1.0, max(abs(x) for c in uv for x in c))
            for j in range(n):
                got, want = o[1][(j + r) % n], uv[j]
                if abs(got[1] - want[1]) > utol or (not seam and abs(got[0] - want[0]) > utol):
                    problems.append("polygon at %s: UV %s, 3ds Max %s" % (pts[0], got, want))
                    break
    if left:
        problems.append("%d polygons 3ds Max does not have" % len(left))
    return ["%s: %s" % (name, p) for p in problems]


@unittest.skipUnless(numpy is not None, "numpy is missing")
class FixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cf = cfb.CompoundFile(FIXTURE)
        cls.scene = reader_scene.Scene.from_file(cls.cf)
        cls.bases = {}
        for i in cls.scene.walk():
            node = cls.scene.node(i)
            cls.bases[node.name] = cls.scene.object_stack(node.object).base
        cls.dump = _load_dump()
        with open(ORACLE, encoding="ascii") as f:
            cls.oracle = {o["name"]: o for o in json.load(f)["nodes"]}

    @classmethod
    def tearDownClass(cls):
        cls.cf.close()

    def test_every_node_is_a_primitive(self):
        self.assertEqual(len(self.bases), 20)
        for name, base in self.bases.items():
            self.assertTrue(prim.is_primitive(self.scene, base), name)

    def test_parameters_as_the_script_set_them(self):
        for name, (cls_name, values, real_world) in EXPECTED.items():
            p, issues = prim.read_params(self.scene, self.bases[name])
            self.assertEqual((p.name, p.real_world, issues), (cls_name, real_world, []), name)
            for key, want in values.items():
                if isinstance(want, float):
                    self.assertAlmostEqual(p.values[key], want, places=5, msg="%s %s" % (name, key))
                else:
                    self.assertEqual(p.values[key], want, "%s %s" % (name, key))

    def test_meshes_equal_3ds_max(self):
        self.assertEqual(sorted(self.dump), sorted(n for n in self.bases if n != "FixtureBoxCopy"))
        problems = []
        for name, d in self.dump.items():
            data, issues = prim.mesh(self.scene, self.bases[name])
            self.assertEqual(issues, [], name)
            problems += compare(name, data, d)
        self.assertEqual(problems, [])

    def test_mapping_off_has_no_channel(self):
        data, _issues = prim.mesh(self.scene, self.bases["FixtureBoxNoMap"])
        self.assertEqual(data.maps, {})

    def test_counts_and_world_boxes_equal_the_oracle(self):
        desc = conv.read(FIXTURE, meters=1.0)
        self.assertEqual((dict(desc.placeholders), desc.issues), ({}, []))
        self.assertEqual(len(desc.meshes), 19)  # FixtureBoxCopy shares FixtureBox's
        for node in desc.nodes:
            o = self.oracle[node.name]
            md = desc.meshes[node.mesh]
            self.assertEqual(node.kind, conv.MESH, node.name)
            if o["modifiers"]:  # the oracle's counts and box are after the TurboSmooth
                self.assertEqual([m.kind for m in node.converted], ["SUBSURF"], node.name)
                continue
            triangles = int((md.loop_totals - 2).sum())
            self.assertEqual((len(md.positions), triangles), (o["eval_verts"], o["eval_faces"]), node.name)
            m = numpy.asarray(node.world, dtype=numpy.float64)
            world = md.positions.astype(numpy.float64) @ m[:3, :3].T + m[:3, 3]
            numpy.testing.assert_allclose(world.min(axis=0), o["bbox_min"], atol=1e-3, err_msg=node.name)
            numpy.testing.assert_allclose(world.max(axis=0), o["bbox_max"], atol=1e-3, err_msg=node.name)

    def test_instances_share_one_mesh(self):
        desc = conv.read(FIXTURE)
        by_name = {n.name: n for n in desc.nodes}
        self.assertEqual(by_name["FixtureBox"].mesh, by_name["FixtureBoxCopy"].mesh)


class Block:
    """A stand-in ParamBlock2: get(pid) from a dict."""

    def __init__(self, values, issues=()):
        self.values, self.issues = values, tuple(issues)

    def get(self, pid, tab=0, default=None):
        return self.values.get(pid, default)


@unittest.skipUnless(numpy is not None, "numpy is missing")
class HandMadeTest(unittest.TestCase):
    def test_defaults_for_parameters_not_stored(self):
        p, issues = prim.params_of(classids.BOX, Block({0: 2.0, 1: 3.0, 2: 4.0}))
        self.assertEqual(issues, [])
        self.assertEqual((p.width_segs, p.length_segs, p.height_segs, p.mapping), (1, 1, 1, True))
        data, _ = prim.build(p)
        self.assertEqual((len(data.positions), len(data.loop_starts)), (8, 6))

    def test_segments_below_the_minimum_are_raised(self):
        p, issues = prim.params_of(classids.SPHERE, Block({0: 1.0, 1: 2}))
        self.assertEqual((p.segs, issues), (4, ["segs 2, made 4"]))
        p, issues = prim.params_of(classids.CYLINDER, Block({0: 1.0, 1: 1.0, 4: 0, 2: -3}))
        self.assertEqual((p.sides, p.height_segs), (3, 1))
        self.assertEqual(issues, ["height segs -3, made 1", "sides 0, made 3"])

    def test_refused_parameters(self):
        with self.assertRaisesRegex(prim.PrimitiveError, "animated"):
            prim.params_of(classids.BOX, Block({0: pblock.Animated(7)}))
        for bad in (float("nan"), float("inf"), "ten", True, (1.0, 2.0)):
            with self.assertRaisesRegex(prim.PrimitiveError, "not a number"):
                prim.params_of(classids.BOX, Block({0: bad}))

    def test_block_issues_are_kept(self):
        _p, issues = prim.params_of(classids.PLANE, Block({}, ["parameter 9 damaged"]))
        self.assertEqual(issues, ["parameter 9 damaged"])

    def test_too_many_faces_refused(self):
        p, _ = prim.params_of(classids.BOX, Block({0: 1.0, 1: 1.0, 2: 1.0, 3: 2000, 4: 2000, 5: 1}))
        with self.assertRaisesRegex(prim.PrimitiveError, "refused"):
            prim.build(p)
        p, _ = prim.params_of(classids.GEOSPHERE, Block({0: 1.0, 1: 400}))
        with self.assertRaisesRegex(prim.PrimitiveError, "refused"):
            prim.build(p)

    def test_options_not_built(self):
        cases = ((classids.SPHERE, {0: 1.0, 7: 1}, "Slice"), (classids.SPHERE, {0: 1.0, 3: 0.5}, "hemisphere"),
                 (classids.GEOSPHERE, {0: 1.0, 3: 1}, "hemisphere"), (classids.CYLINDER, {0: 1.0, 6: 1}, "Slice"),
                 (classids.CONE, {0: 1.0, 7: 1}, "Slice"), (classids.TUBE, {0: 1.0, 7: 1}, "Slice"),
                 (classids.TORUS, {0: 1.0, 7: 1}, "Slice"))
        for class_id, values, word in cases:
            p, _ = prim.params_of(class_id, Block(values))
            with self.assertRaisesRegex(prim.PrimitiveError, word):
                prim.build(p)

    def test_plane_render_scale_and_density_are_named(self):
        p, _ = prim.params_of(classids.PLANE, Block({0: 2.0, 1: 2.0, 4: 2.0, 5: 3.0}))
        data, issues = prim.build(p)
        self.assertEqual(len(data.loop_starts), 16)  # 4 x 4 segments, the viewport's
        self.assertEqual(issues, ["render scale 3 and density 2 act at render time: built at the viewport size"])

    def test_every_class_builds_closed_or_flat_with_its_defaults(self):
        """Each class with only its sizes set: a mesh whose every edge has two faces (one for the Plane's border)."""
        sizes = {classids.BOX: {0: 1.0, 1: 1.0, 2: 1.0}, classids.PLANE: {0: 1.0, 1: 1.0},
                 classids.PYRAMID: {0: 1.0, 1: 1.0, 2: 1.0}, classids.SPHERE: {0: 1.0},
                 classids.GEOSPHERE: {0: 1.0}, classids.CYLINDER: {0: 1.0, 1: 1.0},
                 classids.CONE: {0: 1.0, 1: 0.5, 2: 1.0}, classids.TUBE: {0: 1.0, 1: 0.5, 2: 1.0},
                 classids.TORUS: {0: 1.0, 1: 0.25}}
        for class_id, values in sizes.items():
            p, _ = prim.params_of(class_id, Block(values))
            data, _ = prim.build(p)
            lv = data.loop_vertices.tolist()
            starts = data.loop_starts.tolist() + [len(lv)]
            edges = collections.Counter()
            for f in range(len(starts) - 1):
                loop = lv[starts[f]:starts[f + 1]]
                for a, b in zip(loop, loop[1:] + loop[:1]):
                    edges[(a, b)] += 1
            directed = set(edges)
            open_edges = [e for e in directed if (e[1], e[0]) not in directed]
            self.assertTrue(all(n == 1 for n in edges.values()), p.name)  # consistent winding
            if class_id == classids.PLANE:
                self.assertEqual(len(open_edges), 16, p.name)
            else:
                self.assertEqual(open_edges, [], p.name)


if __name__ == "__main__":
    unittest.main()
