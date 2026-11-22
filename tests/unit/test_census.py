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
import struct
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
BOX = os.path.join(ROOT, "tests", "fixtures", "box_poly_standard.max")
# The Scene root container id by the format a fixture was saved in (the oracle's file_version): saved_as_2017,
# saved_as_2018 and saved_as_2019 are 3ds Max 2020 files saved as 2017, 2018 and 2019.
ROOT_IDS = {19000: "0x2022", 20000: "0x2023", 21000: "0x2023", 22000: "0x2025"}
STACK_BASIC = os.path.join(ROOT, "tests", "fixtures", "stack_basic.max")
# derived objects no node holds: vray_mesh_light's light keeps its own mesh under a Shell (Replace mesh with light)
OWN_DERIVED = {"vray_mesh_light.max": 1}


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
                stacks = [n["modifiers"] for n in oracle["nodes"] if n["modifiers"]]
                self.assertEqual((nodes["unreadable"], nodes["cycles_cut"], nodes["with_modifiers"]),
                                 (0, 0, len(stacks)))
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
                # no fixture shares a whole stack: one outermost derived object per node with modifiers, and one
                # more under it when world-space modifiers (no context in the oracle) sit above object-space ones
                mods = result["modifiers"]
                depths = {}
                for stack in stacks:
                    depths[str(len(stack))] = depths.get(str(len(stack)), 0) + 1
                both = sum(1 for stack in stacks if len({m["context_tm"] is None for m in stack}) == 2)
                own = OWN_DERIVED.get(os.path.basename(path), 0)
                self.assertEqual((mods["stacks"], mods["stack_depths"], mods["derived_objects"], mods["unreadable"],
                                  mods["nodes_with_issues"]), (len(stacks), depths, len(stacks) + both + own, 0, 0))
                # nodes per modifier class, each class once per node
                by_class = {}
                for stack in stacks:
                    for cid in {tuple("0x" + x[2:].upper() for x in m["class_id"]) for m in stack}:
                        by_class[cid] = by_class.get(cid, 0) + 1
                # a modifier of a stack no node holds (OWN_DERIVED) is counted on no node
                self.assertEqual({tuple(r["class_id"]): r["nodes"] for r in mods["by_class"] if r["nodes"] or not own},
                                 by_class)
                for r in mods["by_class"]:
                    self.assertLessEqual(r["objects"], r["count"])
                    self.assertLessEqual(r["derived_objects"], r["count"])
                self.assertEqual(nodes["bad_parents"], 0)
                self.assertEqual(result["root_id"], ROOT_IDS[oracle["file_version"][0]])

    def test_stack_basic(self):
        """An instanced Noise (one object, two stacks), a Taper shared by a reference's stack, the switches."""
        rows = {r["name"]: r for r in census.census(STACK_BASIC)["modifiers"]["by_class"]}
        got = {k: (r["count"], r["derived_objects"], r["objects"], r["nodes"], r["off"], r["off_in_views"],
                   r["off_in_renders"]) for k, r in rows.items()}
        self.assertEqual(got, {"Noise": (2, 2, 1, 2, 0, 0, 0), "Taper": (2, 2, 2, 3, 0, 1, 0),
                               "Twist": (2, 2, 2, 2, 0, 0, 1), "Bend": (1, 1, 1, 1, 1, 0, 0),
                               "TurboSmooth": (1, 1, 1, 1, 0, 0, 0), "UVW Map": (1, 1, 1, 1, 0, 0, 0)})
        self.assertIn("in 2, objects 1, nodes 2, off 0/0/0", census.format_text(census.census(STACK_BASIC)))

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


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def _entry(a, b, superclass, name):
    return node(0x2040, leaf(0x2060, struct.pack("<iIII", -1, a, b, superclass)),
                leaf(0x2042, name.encode("utf-16-le")))


def _refs(*values):
    return leaf(0x2034, struct.pack("<%di" % len(values), *values))


def _node(parent, *pairs):
    flat = [v for pair in pairs for v in pair]
    return node(1, leaf(0x2035, struct.pack("<I" + "Ii" * len(pairs), 16, *flat)),
                leaf(0x0960, struct.pack("<iI", parent, 0)))


def _synthetic():
    """Class indices: 0 Editable Poly, 1 Node, 2 RootNode, 3 UVW Map, 4 Edit Mesh. Objects: 0 root, 1 poly, 2 uvw,
    3 edit mesh, 4 derived [uvw, poly], 5 derived [edit mesh, 4] (nested), 6 node on 5, 7 node on 5 (an instance,
    child of 6), 8 node on the poly, 9 node on nothing, 10 node with an unreadable 0x0960."""
    classes = census.scene.classdir.ClassDirectory.parse(
        _entry(0x1BF8338D, 0x192F6098, 0x10, "Editable Poly") + _entry(1, 0, 1, "Node") + _entry(2, 0, 1, "RootNode") +
        _entry(0xF72B1, 0, 0x810, "UVW Map") + _entry(0x50, 0, 0x810, "Edit Mesh"))
    objects = [node(2), node(0), node(3), node(4), node(0x2032, _refs(2, 1)), node(0x2032, _refs(3, 4)),
               _node(0, (1, 5)), _node(6, (1, 5)), _node(0, (1, 1)), _node(0), node(1, leaf(0x0960, b"\x00"))]
    return census.scene.Scene(node(0x2025, *objects), classes)


class TestSynthetic(unittest.TestCase):
    def test_counts(self):
        r = census.census_scene(_synthetic())
        nodes = r["nodes"]
        self.assertEqual((nodes["total"], nodes["unreadable"], nodes["bad_parents"], nodes["with_modifiers"]),
                         (5, 1, 1, 2))
        self.assertEqual(nodes["top_level"], 4)  # 6, 8, 9 and the unreadable one; 7 is under 6
        self.assertEqual({row["name"]: row["count"] for row in nodes["by_base_class"]},
                         {"Editable Poly": 3, "(none)": 1})
        mods = r["modifiers"]
        self.assertEqual((mods["stacks"], mods["stack_depths"], mods["derived_objects"], mods["unreadable"]),
                         (1, {"2": 1}, 2, 0))
        self.assertEqual({row["name"]: (row["count"], row["derived_objects"], row["objects"], row["nodes"])
                          for row in mods["by_class"]},
                         {"UVW Map": (1, 1, 1, 2), "Edit Mesh": (1, 1, 1, 2)})
        derived = [row for row in r["classes"] if row["name"] == "(derived object)"]
        self.assertEqual([(row["count"], row["special_id"]) for row in derived], [(2, "0x2032")])
        self.assertIn("Derived objects: 2", census.format_text(dict(r, seconds=0)))


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
