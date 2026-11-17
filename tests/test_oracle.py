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
            "oracle_version", "renderer", "time", "units"]
NODE_KEYS = ["base_class_id", "base_class_name", "base_faces", "base_superclass", "base_verts", "bbox_max",
             "bbox_min", "eval_faces", "eval_verts", "frozen", "handle", "hidden", "index", "instances", "layer",
             "material", "modifiers", "name", "object_transform", "offset_pos", "offset_rot", "offset_scale",
             "parent", "renderable", "transform"]
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
                self.assertEqual(o["oracle_version"], 2)
                self.assertEqual(o["file"], name + ".max")
                self.assertEqual(o["node_count"], len(o["nodes"]))
                handles = {n["handle"] for n in o["nodes"]}
                self.assertEqual(len(handles), len(o["nodes"]))
                groups = {n["handle"]: n["instances"] for n in o["nodes"]}
                for i, n in enumerate(o["nodes"]):
                    self.assertEqual(list(n), NODE_KEYS)
                    for cid in [n["base_class_id"]] + [m["class_id"] for m in n["modifiers"]]:
                        self.assertEqual(len(cid), 2)
                        self.assertTrue(all(CLASS_ID.match(c) for c in cid), cid)
                    for h in n["instances"]:
                        self.assertEqual(groups[h], n["instances"])
                    self.assertEqual(n["index"], i)
                    self.assertEqual(len(n["transform"]), 12)
                    self.assertEqual(len(n["object_transform"]), 12)
                    self.assertTrue(n["parent"] is None or n["parent"] in handles)
                    self.assertTrue(n["material"] is None or 0 <= n["material"] < len(o["materials"]))
                    self.assertIn(n["handle"], n["instances"])
                    self.assertTrue(set(n["instances"]) <= handles)
                    self.assertIn(n["layer"], [layer["name"] for layer in o["layers"]])
                self.assertEqual([m["index"] for m in o["materials"]], list(range(len(o["materials"]))))

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
        self.assertEqual(bent["modifiers"], [{"class_id": ["0x00000010", "0x00000000"], "class_name": "Bend"},
                                             {"class_id": ["0x000f72b1", "0x00000000"], "class_name": "Uvwmap"}])
        self.assertEqual(smooth["modifiers"], [{"class_id": ["0x0d727b3e", "0x491d29a7"],
                                                "class_name": "TurboSmooth"}])
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
