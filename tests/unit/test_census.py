# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of tools/census.py, the class census of a .max: no Blender. Every committed fixture against its oracle
(node total, base classes), the JSON and text forms, and that the output names no node and no path.

    python -I -m unittest discover tests
"""
import contextlib
import glob
import importlib.util
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
BOX = os.path.join(ROOT, "tests", "fixtures", "box_poly_standard.max")


def _load_tool():
    spec = importlib.util.spec_from_file_location("maxdrop_census", os.path.join(ROOT, "tools", "census.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = _load_tool()


def _oracle(path):
    with open(path[:-4] + ".oracle.json", encoding="ascii") as f:
        return json.load(f)


def _run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = census.main(list(argv))
    return code, out.getvalue(), err.getvalue()


@unittest.skipUnless(FIXTURES, "no fixtures")
class TestFixtures(unittest.TestCase):
    def test_counts_against_the_oracle(self):
        for path in FIXTURES:
            oracle = _oracle(path)
            with self.subTest(fixture=os.path.basename(path)):
                result = census.census(path)
                nodes = result["nodes"]
                self.assertEqual(nodes["total"], oracle["node_count"])
                self.assertEqual((nodes["unreadable"], nodes["cycles_cut"], nodes["with_modifiers"]), (0, 0, 0))
                self.assertEqual(nodes["top_level"], sum(1 for n in oracle["nodes"] if n["parent"] is None))
                self.assertEqual(sum(r["count"] for r in nodes["by_base_class"]), nodes["total"])
                self.assertEqual(sum(r["count"] for r in result["classes"]), result["objects"])
                want = {}
                for n in oracle["nodes"]:
                    cid = tuple("0x" + x[2:].upper() for x in n["base_class_id"])
                    key = cid, "0x%X" % n["base_superclass"]
                    want[key] = want.get(key, 0) + 1
                got = {(tuple(r["class_id"]), r["superclass"]): r["count"] for r in nodes["by_base_class"]}
                self.assertEqual(got, want)
                node_rows = [r for r in result["classes"] if r["name"] == "Node"]
                self.assertEqual([r["count"] for r in node_rows], [oracle["node_count"]])
                self.assertEqual(result["modifiers"], {"stacks": 0, "stack_depths": {}, "by_class": []})
                self.assertEqual(result["root_id"], "0x2025")

    def test_box(self):
        rows = census.census(BOX)["nodes"]["by_base_class"]
        self.assertEqual([(r["name"], r["class_id"], r["superclass"], r["count"]) for r in rows],
                         [("Editable Poly", ["0x1BF8338D", "0x192F6098"], "0x10", 1)])

    def test_json_and_text(self):
        for path in FIXTURES:
            names = {n["name"] for n in _oracle(path)["nodes"]}
            names |= {m["name"] for m in _oracle(path)["materials"]}
            with self.subTest(fixture=os.path.basename(path)):
                code, out, err = _run("--json", path)
                self.assertEqual((code, err), (0, ""))
                data = json.loads(out)
                expected = census.census(path)
                del data["seconds"], expected["seconds"]
                self.assertEqual(data, expected)
                code, text, err = _run(path)
                self.assertEqual((code, err), (0, ""))
                self.assertIn("Nodes: %d" % len(_oracle(path)["nodes"]), text)
                for output in (out, text):
                    for name in names:
                        self.assertNotIn(name, output)
                    self.assertNotIn(os.path.basename(path), output)
                    self.assertNotIn(ROOT, output)


class TestUsage(unittest.TestCase):
    def test_missing_file(self):
        code, out, err = _run(os.path.join(ROOT, "tests", "fixtures", "no_such_file.max"))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no such file", err)

    def test_not_a_max_file(self):
        code, out, err = _run(os.path.join(ROOT, "LICENSE"))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("cannot read", err)


if __name__ == "__main__":
    unittest.main()
