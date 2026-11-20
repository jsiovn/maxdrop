# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of the committed 3ds Max oracle files (tests/fixtures/<name>.oracle.json, written by
tools/oracle/dump_scene.ms, docs/ORACLE.md): one per fixture, canonical, consistent, free of private strings.
No Blender, no 3ds Max.

    python -I -m unittest discover tests
"""
import glob
import importlib.util
import json
import math
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
TOP_KEYS = ["file", "file_version", "layers", "material_graph", "materials", "max_version", "node_count", "nodes",
            "oracle_version", "render", "renderer", "time", "units"]
NODE_KEYS = ["base_class_id", "base_class_name", "base_faces", "base_superclass", "base_verts", "bbox_max",
             "bbox_min", "camera", "eval_faces", "eval_maps", "eval_verts", "frozen", "handle", "hidden", "index",
             "instances", "layer", "material", "modifiers", "name", "object_transform", "offset_pos", "offset_rot",
             "offset_scale", "parent", "renderable", "shape", "transform"]
MODIFIER_KEYS = ["class_id", "class_name", "context_bbox_max", "context_bbox_min", "context_tm", "enabled",
                 "enabled_in_renders", "enabled_in_views", "name"]
LAYER_KEYS = ["frozen", "hidden", "name", "parent", "renderable"]
CAMERA_KEYS = ["fov", "hither", "manual_clip", "ortho", "tdist", "yon"]
RENDER_KEYS = ["camera", "height", "pixel_aspect", "width"]
SHAPE_KEYS = ["adaptive", "angle", "display_render_mesh", "length", "optimize", "rectangular", "renderable", "sides",
              "splines", "steps", "thickness", "width"]
KNOT_KEYS = ["in", "mid", "out", "pos", "segment", "type"]
KNOT_TYPES = ("corner", "smooth", "bezier", "bezierCorner")
GRAPH_KEYS = ["blocks", "class_id", "class_name", "index", "name", "parts", "subs", "superclass"]
BLOCK_KEYS = ["block_id", "kind", "params", "ref"]
PB2_PARAM_KEYS = ["id", "name", "transient", "type", "value"]
PB1_PARAM_KEYS = ["index", "type", "value"]
REF_TYPES = (14, 15)  # mtl, texmap: the value is an index into material_graph


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stem(path, suffix):
    return os.path.basename(path)[:-len(suffix)]


CLASS_ID = re.compile(r"^0x[0-9a-f]{8}$")
check_fixture = _load("check_fixture")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def private_problems(data, names=None):
    """check_fixture's findings on the raw bytes and on every decoded string: JSON doubles each backslash of a path
    and turns a non-ASCII name into a \\u escape, so the raw scan alone sees neither."""
    decoded = "\n".join(_strings(json.loads(data))).encode("utf-8")
    return check_fixture.problems(data, names) + check_fixture.problems(decoded, names)


def _sorted_pairs(pairs):
    keys = [k for k, _ in pairs]
    if keys != sorted(keys):
        raise AssertionError("keys not sorted: %r" % keys)
    return dict(pairs)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _close(test, got, want, places=5):
    test.assertEqual(len(got), len(want))
    for g, e in zip(got, want):
        test.assertAlmostEqual(g, e, places=places, msg="%r vs %r" % (got, want))


def _oracle(name):
    return json.loads(_read(os.path.join(FIXTURE_DIR, name + ".oracle.json")).decode("ascii"),
                      object_pairs_hook=_sorted_pairs)


class OracleFiles(unittest.TestCase):
    maxes = sorted(glob.glob(os.path.join(FIXTURE_DIR, "*.max")))
    oracles = sorted(glob.glob(os.path.join(FIXTURE_DIR, "*.oracle.json")))

    def test_one_oracle_per_fixture(self):
        self.assertTrue(self.maxes)
        self.assertEqual([_stem(p, ".max") for p in self.maxes], [_stem(p, ".oracle.json") for p in self.oracles])

    def test_canonical_text(self):
        for path in self.oracles:
            with self.subTest(os.path.basename(path)):
                data = _read(path)
                self.assertNotIn(b"\r", data)
                self.assertTrue(data.endswith(b"}\n"))
                data.decode("ascii")  # every other character is escaped
                json.loads(data, object_pairs_hook=_sorted_pairs)  # keys sorted at every level

    def test_structure(self):
        for path in self.oracles:
            name = _stem(path, ".oracle.json")
            with self.subTest(name):
                o = _oracle(name)
                self.assertEqual(list(o), TOP_KEYS)
                self.assertEqual(o["oracle_version"], 7)
                self.assertEqual(list(o["render"]), RENDER_KEYS)
                self.assertTrue(o["render"]["width"] > 0 and o["render"]["height"] > 0)
                self.assertEqual(o["file"], name + ".max")
                self.assertEqual(o["node_count"], len(o["nodes"]))
                handles = {n["handle"] for n in o["nodes"]}
                self.assertEqual(len(handles), len(o["nodes"]))
                groups = {n["handle"]: n["instances"] for n in o["nodes"]}
                for i, n in enumerate(o["nodes"]):
                    self.assertEqual(list(n), NODE_KEYS)
                    for m in n["modifiers"]:
                        self.assertEqual(list(m), MODIFIER_KEYS)
                        self.assertEqual(len(m["context_tm"]), 12)
                        self.assertEqual((len(m["context_bbox_min"]), len(m["context_bbox_max"])), (3, 3))
                    for cid in [n["base_class_id"]] + [m["class_id"] for m in n["modifiers"]]:
                        self.assertEqual(len(cid), 2)
                        self.assertTrue(all(CLASS_ID.match(c) for c in cid), cid)
                    for h in n["instances"]:
                        self.assertEqual(groups[h], n["instances"])
                    self.assertEqual(n["shape"] is not None, n["base_superclass"] == 64, n["name"])
                    self.assertEqual(n["camera"] is not None, n["base_superclass"] == 32, n["name"])
                    if n["camera"] is not None:
                        self.assertEqual(list(n["camera"]), CAMERA_KEYS)
                        self.assertTrue(0 < n["camera"]["fov"] < 180, n["camera"])
                    if n["shape"] is not None:
                        self._check_shape(n["shape"])
                    uvw = any(m["class_name"] == "Uvwmap" for m in n["modifiers"])
                    self.assertEqual(n["eval_maps"] is not None, uvw, n["name"])
                    if n["eval_maps"] is not None:
                        self._check_maps(n["eval_maps"], n["eval_faces"])
                    self.assertEqual(n["index"], i)
                    self.assertEqual(len(n["transform"]), 12)
                    self.assertEqual(len(n["object_transform"]), 12)
                    self.assertTrue(n["parent"] is None or n["parent"] in handles)
                    self.assertTrue(n["material"] is None or 0 <= n["material"] < len(o["materials"]))
                    self.assertIn(n["handle"], n["instances"])
                    self.assertTrue(set(n["instances"]) <= handles)
                    self.assertIn(n["layer"], [layer["name"] for layer in o["layers"]])
                layer_names = [layer["name"] for layer in o["layers"]]
                self.assertEqual(len(set(layer_names)), len(layer_names))
                for layer in o["layers"]:
                    self.assertEqual(list(layer), LAYER_KEYS)
                    self.assertTrue(layer["parent"] is None or layer["parent"] in layer_names, layer)
                self.assertEqual([m["index"] for m in o["materials"]], list(range(len(o["materials"]))))
                camera = o["render"]["camera"]
                self.assertTrue(camera is None or any(n["handle"] == camera and n["camera"] is not None
                                                      for n in o["nodes"]), camera)

    def _check_shape(self, shape):
        self.assertEqual(list(shape), SHAPE_KEYS)
        for sp in shape["splines"]:
            self.assertEqual(list(sp), ["closed", "knots"])
            knots = sp["knots"]
            for k, knot in enumerate(knots):
                self.assertEqual(list(knot), KNOT_KEYS)
                self.assertIn(knot["type"], KNOT_TYPES)
                # a closed spline has a segment after every knot, an open one none after its last
                last = k == len(knots) - 1 and not sp["closed"]
                self.assertEqual(knot["segment"] is None, last)
                self.assertEqual(knot["mid"] is None, last)
                self.assertIn(knot["segment"], (None, "curve", "line"))

    def _check_maps(self, maps, faces):
        """Per channel a UVW Map writes, ascending: per triangle corner position, normal and map vertex."""
        self.assertEqual([m["channel"] for m in maps], sorted({m["channel"] for m in maps}))
        for m in maps:
            self.assertEqual(list(m), ["channel", "corners"])
            self.assertEqual(len(m["corners"]), 3 * faces)
            self.assertTrue(all(len(c) == 9 and all(isinstance(v, (int, float)) for v in c) for c in m["corners"]))

    def _check_block(self, b, size):
        self.assertEqual(list(b), BLOCK_KEYS)
        self.assertIsInstance(b["ref"], int)
        if b["kind"] == "pb2":
            self.assertIsInstance(b["block_id"], int)
            ids = [p["id"] for p in b["params"]]
            self.assertEqual(len(ids), len(set(ids)))
            for p in b["params"]:
                self.assertEqual(list(p), PB2_PARAM_KEYS)
                if p["type"] & 0x7FF in REF_TYPES:
                    values = p["value"] if p["type"] & 0x800 else [p["value"]]
                    self.assertTrue(all(v is None or 0 <= v < size for v in values), p)
        else:
            self.assertEqual(b["kind"], "pb1")
            self.assertIsNone(b["block_id"])
            self.assertEqual([p["index"] for p in b["params"]], list(range(len(b["params"]))))
            for p in b["params"]:
                self.assertEqual(list(p), PB1_PARAM_KEYS)

    def test_material_graph(self):
        for path in self.oracles:
            name = _stem(path, ".oracle.json")
            with self.subTest(name):
                o = _oracle(name)
                graph = o["material_graph"]
                self.assertEqual([e["index"] for e in graph], list(range(len(graph))))
                # depth first from the node materials: the first entry is the first one, each one is in it
                entries = [(e["name"], tuple(e["class_id"])) for e in graph]
                mats = [(m["name"], tuple(m["class_id"])) for m in o["materials"]]
                self.assertEqual(entries[:1], mats[:1])
                self.assertTrue(set(mats) <= set(entries))
                for e in graph:
                    self.assertEqual(list(e), GRAPH_KEYS)
                    self.assertIn(e["superclass"], (0xC00, 0xC10))
                    for b in e["blocks"]:
                        self._check_block(b, len(graph))
                    for part in e["parts"]:
                        self.assertEqual(list(part), ["blocks", "class_id", "ref"])
                        for b in part["blocks"]:
                            self._check_block(b, len(graph))
                    for sub in e["subs"]:
                        self.assertEqual(list(sub), ["kind", "slot", "target"])
                        self.assertIn(sub["kind"], ("material", "map"))
                        self.assertTrue(0 <= sub["target"] < len(graph))

    def test_parents_come_first(self):
        for path in self.oracles:
            o = _oracle(_stem(path, ".oracle.json"))
            seen = set()
            for n in o["nodes"]:
                self.assertTrue(n["parent"] is None or n["parent"] in seen, n["name"])
                seen.add(n["handle"])

    def test_box_poly_standard(self):
        o = _oracle("box_poly_standard")
        self.assertEqual(o["node_count"], 1)
        box = o["nodes"][0]
        self.assertEqual(box["transform"][9:], [10, 20, 0])
        self.assertEqual(box["bbox_min"], [0, 5, 0])
        self.assertEqual(box["bbox_max"], [20, 35, 40])
        self.assertEqual((box["base_verts"], box["base_faces"]), (8, 6))
        self.assertEqual(box["base_class_id"], ["0x1bf8338d", "0x192f6098"])

    def test_units(self):
        for name, unit in (("units_mm", "millimeters"), ("units_cm", "centimeters"), ("units_in", "inches")):
            o = _oracle(name)
            self.assertEqual((o["units"]["system_type"], o["units"]["system_scale"]), (unit, 1))
            self.assertEqual(o["nodes"][0]["bbox_min"], [0, -10, 0])
            self.assertEqual(o["nodes"][0]["bbox_max"], [10, 10, 30])

    def test_instances(self):
        o = _oracle("instances")
        groups = sorted({tuple(n["instances"]) for n in o["nodes"]})
        self.assertEqual(groups, [(1, 2, 3, 4), (5,)])

    def test_hierarchy(self):
        o = _oracle("hierarchy")
        by_name = {}
        for n in o["nodes"]:
            by_name.setdefault(n["name"], []).append(n)
        self.assertEqual(len(by_name["FixtureTwin"]), 2)
        root, child, leaf = by_name["FixtureRoot"][0], by_name["FixtureChild"][0], by_name["FixtureLeaf"][0]
        self.assertIsNone(root["parent"])
        self.assertEqual((child["parent"], leaf["parent"]), (root["handle"], child["handle"]))
        self.assertEqual(sorted(t["parent"] is None for t in by_name["FixtureTwin"]), [False, True])
        t = leaf["transform"]  # negative scale: the rotation part has determinant -1
        det = (t[0] * (t[4] * t[8] - t[5] * t[7]) - t[1] * (t[3] * t[8] - t[5] * t[6])
               + t[2] * (t[3] * t[7] - t[4] * t[6]))
        self.assertAlmostEqual(det, -1, places=4)

    def test_modifier_pivot(self):
        o = _oracle("modifier_pivot")
        by_name = {n["name"]: n for n in o["nodes"]}
        src, bent, smooth = by_name["FixtureSource"], by_name["FixtureBent"], by_name["FixtureSmooth"]
        # three nodes on one base object, each with a stack of its own (references, not instances)
        handles = sorted(n["handle"] for n in (src, bent, smooth))
        for n in (src, bent, smooth):
            self.assertEqual(n["instances"], handles, n["name"])
            self.assertEqual((n["base_verts"], n["base_faces"]), (20, 18), n["name"])
        # top to bottom: the Bend was added last, over the UVW Map
        self.assertEqual(src["modifiers"], [])
        self.assertEqual([(m["class_id"], m["class_name"], m["name"]) for m in bent["modifiers"]],
                         [(["0x00000010", "0x00000000"], "Bend", "Bend"),
                          (["0x000f72b1", "0x00000000"], "Uvwmap", "UVW Map")])
        self.assertEqual([(m["class_id"], m["class_name"]) for m in smooth["modifiers"]],
                         [(["0x0d727b3e", "0x491d29a7"], "TurboSmooth")])
        for m in bent["modifiers"] + smooth["modifiers"]:  # added to one node each: an identity context
            self.assertEqual(m["context_tm"], [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0])
            self.assertEqual((m["context_bbox_min"], m["context_bbox_max"]), ([-5, -5, 0], [5, 5, 40]))
            self.assertEqual((m["enabled"], m["enabled_in_views"], m["enabled_in_renders"]), (True, True, True))
        # eval counts are triangles after the stack: 18 quads = 36 triangles; one TurboSmooth iteration on a
        # closed quad mesh gives V + E + F vertices (E = V + F - 2) and four quads per quad
        v, f = 20, 18
        self.assertEqual((src["eval_verts"], src["eval_faces"]), (v, 2 * f))
        self.assertEqual((bent["eval_verts"], bent["eval_faces"]), (v, 2 * f))  # Bend moves, UVW Map maps
        self.assertEqual((smooth["eval_verts"], smooth["eval_faces"]), (v + (v + f - 2) + f, 2 * 4 * f))
        # the Bend shows in the box: unbent, the base box is 10 x 10 x 40
        self.assertGreater(bent["bbox_max"][0] - bent["bbox_min"][0], 20)
        self.assertLess(bent["bbox_max"][2], 40)

        # the pivot alone is turned +30 degrees about Z: row 1 = [cos 30, sin 30, 0], the object stays put
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        _close(self, bent["transform"], [c, s, 0, -s, c, 0, 0, 0, 1, 30, 0, 0])
        _close(self, bent["object_transform"], [1, 0, 0, 0, 1, 0, 0, 0, 1, 30, 0, 0])
        # so the offset is a -30 degree turn, which MAXScript prints with +z: the conjugate of the standard
        # quaternion (docs/ORACLE.md)
        _close(self, bent["offset_rot"], [0, 0, math.sin(math.radians(15)), math.cos(math.radians(15))])
        qx, qy, qz, w = bent["offset_rot"]
        x, y, z = -qx, -qy, -qz
        # a standard quaternion as a row-vector matrix: row 1 = [1 - 2(y2 + z2), 2(xy + zw), 2(xz - yw)]
        offset_row1 = [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)]
        _close(self, offset_row1, [c, -s, 0])
        # offset times node transform = object transform: [c, -s] times the node rotation is the identity row
        t = bent["transform"]
        _close(self, [offset_row1[0] * t[0] + offset_row1[1] * t[3], offset_row1[0] * t[1] + offset_row1[1] * t[4]],
               [1, 0])
        for n in (src, smooth):
            self.assertEqual(n["offset_rot"], [0, 0, 0, 1])

    def test_stack_basic(self):
        by_name = {n["name"]: n for n in _oracle("stack_basic")["nodes"]}

        def stack(name):  # top to bottom, as the oracle lists it
            return [(m["name"], m["enabled"], m["enabled_in_views"], m["enabled_in_renders"])
                    for m in by_name[name]["modifiers"]]

        self.assertEqual(stack("FixtureTurbo"), [("TurboSmooth", True, True, True), ("FixtureUVW", True, True, True)])
        # two TurboSmooth iterations of a cube: 8 + 12 + 6 = 26 vertices and 24 quads, then 26 + 48 + 24
        self.assertEqual(by_name["FixtureTurbo"]["eval_verts"], 98)
        self.assertEqual(stack("FixtureFlags"), [("Twist", True, True, False), ("Taper", True, False, True),
                                                 ("Bend", False, True, True)])
        # one Noise on both boxes: one gizmo around the two, so each context is moved to the gizmo's centre
        a, b = by_name["FixtureSharedA"]["modifiers"], by_name["FixtureSharedB"]["modifiers"]
        self.assertEqual([m["name"] for m in a + b], ["FixtureNoise", "FixtureNoise"])
        self.assertEqual((a[0]["context_tm"][9:], b[0]["context_tm"][9:]), ([-10, 0, -10], [10, 0, -10]))
        self.assertEqual((a[0]["context_bbox_min"], a[0]["context_bbox_max"]), ([-15, -5, -10], [15, 5, 10]))
        # the reference shows the shared Taper under its own Twist
        self.assertEqual(stack("FixtureNested"), [("Taper", True, True, True)])
        self.assertEqual(stack("FixtureNestedRef"), [("Twist", True, True, True), ("Taper", True, True, True)])
        self.assertEqual(by_name["FixtureNested"]["instances"], by_name["FixtureNestedRef"]["instances"])

    def test_shapes(self):
        by_name = {n["name"]: n for n in _oracle("shapes")["nodes"]}
        self.assertEqual(len(by_name), 14)
        self.assertIsNone(by_name["FixtureBox"]["shape"])  # the one mesh
        line = by_name["FixtureLine"]["shape"]
        self.assertEqual([(sp["closed"], [k["type"] for k in sp["knots"]]) for sp in line["splines"]],
                         [(True, ["corner", "smooth", "bezier", "bezierCorner"]),
                          (False, ["corner", "bezier", "corner"])])
        self.assertEqual((line["renderable"], line["display_render_mesh"], line["thickness"], line["sides"],
                          line["steps"]), (True, True, 2, 8, 4))
        # a straight segment stays straight although its knots have vectors off the chord
        a, b = line["splines"][1]["knots"][1:]
        self.assertEqual(a["segment"], "line")
        _close(self, a["mid"], [(x + y) / 2 for x, y in zip(a["pos"], b["pos"])])
        curved = [(p + 3 * o + 3 * i + q) / 8 for p, o, i, q in zip(a["pos"], a["out"], b["in"], b["pos"])]
        self.assertGreater(max(abs(x - y) for x, y in zip(curved, a["mid"])), 1)
        # stood up: the knots are in object space, the transform turns them
        arc = by_name["FixtureArc"]
        self.assertTrue(all(k["pos"][2] == 0 for k in arc["shape"]["splines"][0]["knots"]))
        _close(self, arc["transform"][6:9], [0, -1, 0])
        self.assertEqual(by_name["FixtureOpen"]["parent"], by_name["FixtureRect"]["handle"])
        counts = {name: [len(sp["knots"]) for sp in n["shape"]["splines"]] for name, n in by_name.items()
                  if n["shape"] is not None}
        self.assertEqual(counts, {"FixtureLine": [4, 3], "FixtureEditable": [4], "FixtureRect": [8],
                                  "FixtureOpen": [3], "FixtureRectSharp": [4], "FixtureCircle": [4],
                                  "FixtureEllipse": [4], "FixtureArc": [4], "FixturePie": [5],
                                  "FixtureArcWide": [4], "FixtureNGon": [6], "FixtureNGonRound": [5],
                                  "FixtureNGonIn": [3]})
        self.assertEqual((by_name["FixtureCircle"]["shape"]["steps"], by_name["FixtureNGon"]["shape"]["adaptive"]),
                         (3, True))

    def test_layers_flags(self):
        o = _oracle("layers_flags")
        flags = {n["name"]: (n["hidden"], n["renderable"], n["layer"]) for n in o["nodes"]}
        self.assertEqual(flags["FixtureHidden"][:2], (True, True))
        self.assertEqual(flags["FixtureNoRender"][:2], (False, False))
        self.assertEqual(flags["FixtureVisible"][:2], (False, True))
        self.assertEqual({layer["name"] for layer in o["layers"]}, {"0", "FixtureLayerA", "FixtureLayerB"})
        head = next(n for n in o["nodes"] if n["name"] == "FixtureGroup")
        self.assertEqual(sorted(n["name"] for n in o["nodes"] if n["parent"] == head["handle"]),
                         ["FixtureGroupA", "FixtureGroupB"])

    def test_no_private_strings(self):
        for path in self.oracles:
            with self.subTest(os.path.basename(path)):
                self.assertEqual(private_problems(_read(path)), [])

    def test_private_scan_sees_escaped_text(self):
        names = {"user name": ["caf\u00e9name"], "computer name": ["box-7731"]}
        for value in ("C:\\Users\\someone\\scene.max", "D:\\projects\\maps\\wood.png", "x caf\u00e9name y"):
            data = json.dumps({"name": value}).encode("ascii")
            self.assertEqual(check_fixture.problems(data, names), [], value)  # what the raw scan misses
            self.assertTrue(private_problems(data, names), value)


if __name__ == "__main__":
    unittest.main()
