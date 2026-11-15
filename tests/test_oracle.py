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
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
TOP_KEYS = ["file", "file_version", "layers", "materials", "max_version", "node_count", "nodes", "oracle_version",
            "renderer", "units"]
NODE_KEYS = ["base_class_id", "base_class_name", "base_faces", "base_superclass", "base_verts", "bbox_max",
             "bbox_min", "eval_faces", "eval_verts", "frozen", "handle", "hidden", "index", "instances", "layer",
             "material", "modifiers", "name", "object_transform", "offset_pos", "offset_rot", "offset_scale",
             "parent", "renderable", "transform"]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stem(path, suffix):
    return os.path.basename(path)[:-len(suffix)]


def _sorted_pairs(pairs):
    keys = [k for k, _ in pairs]
    if keys != sorted(keys):
        raise AssertionError("keys not sorted: %r" % keys)
    return dict(pairs)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


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
                self.assertEqual(o["oracle_version"], 1)
                self.assertEqual(o["file"], name + ".max")
                self.assertEqual(o["node_count"], len(o["nodes"]))
                handles = {n["handle"] for n in o["nodes"]}
                self.assertEqual(len(handles), len(o["nodes"]))
                for i, n in enumerate(o["nodes"]):
                    self.assertEqual(list(n), NODE_KEYS)
                    self.assertEqual(n["index"], i)
                    self.assertEqual(len(n["transform"]), 12)
                    self.assertEqual(len(n["object_transform"]), 12)
                    self.assertTrue(n["parent"] is None or n["parent"] in handles)
                    self.assertTrue(n["material"] is None or 0 <= n["material"] < len(o["materials"]))
                    self.assertIn(n["handle"], n["instances"])
                    self.assertTrue(set(n["instances"]) <= handles)
                    self.assertIn(n["layer"], [layer["name"] for layer in o["layers"]])
                self.assertEqual([m["index"] for m in o["materials"]], list(range(len(o["materials"]))))

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

    def test_no_private_strings(self):
        check_fixture = _load("check_fixture")
        for path in self.oracles:
            with self.subTest(os.path.basename(path)):
                self.assertEqual(check_fixture.problems(_read(path)), [])


if __name__ == "__main__":
    unittest.main()
