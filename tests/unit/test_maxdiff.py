# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of tools/maxdiff.py, the stream and chunk diff of .max files: no Blender. Synthetic chunk trees and byte
strings, the units_* fixtures (the system-unit chunk differs, noise filtering drops it when A2 differs there too)
and the command line.

    python -I -m unittest discover tests
"""
import contextlib
import importlib.util
import io
import os
import struct
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UNITS = {k: os.path.join(ROOT, "tests", "fixtures", "units_%s.max" % k) for k in ("mm", "cm", "in")}
HAVE_FIXTURES = all(os.path.isfile(p) for p in UNITS.values())


def _load_tool():
    spec = importlib.util.spec_from_file_location("maxdrop_maxdiff", os.path.join(ROOT, "tools", "maxdiff.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


maxdiff = _load_tool()


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def _run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = maxdiff.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestLeaves(unittest.TestCase):
    def test_paths_count_siblings_by_id(self):
        data = node(0x2025, node(0x10, leaf(0x1, b"a")), leaf(0x20, b"b"), node(0x10, leaf(0x1, b"c"), leaf(0x1, b"d")))
        found, kids = maxdiff.leaves(data)
        self.assertEqual(found, {"2025#0/0010#0/0001#0": b"a", "2025#0/0020#0": b"b",
                                 "2025#0/0010#1/0001#0": b"c", "2025#0/0010#1/0001#1": b"d"})
        self.assertEqual(kids, {"2025#0": 3, "2025#0/0010#0": 1, "2025#0/0010#1": 2})

    def test_not_chunked(self):
        self.assertIsNone(maxdiff.leaves(b"\xfe\xff\x00\x00 not chunks"))


class TestByteRanges(unittest.TestCase):
    def test_ranges(self):
        a = bytes(64)
        b = bytearray(a)
        b[3] = 1
        b[5] = 1  # within the gap: one range with 3
        b[40] = 1
        self.assertEqual(maxdiff.byte_ranges(a, bytes(b)), [(3, 6), (40, 41)])
        self.assertEqual(maxdiff.byte_ranges(a, a), [])

    def test_length_difference(self):
        self.assertEqual(maxdiff.byte_ranges(bytes(32), bytes(40)), [(32, 40)])
        b = bytearray(40)
        b[30] = 1
        self.assertEqual(maxdiff.byte_ranges(bytes(32), bytes(b)), [(30, 40)])


@unittest.skipUnless(HAVE_FIXTURES, "no units fixtures")
class TestFixtures(unittest.TestCase):
    def _unit_diffs(self, diffs):
        return [d for d in diffs if d.stream == "Scene" and d.where.endswith("/8520#0")]

    def test_units_chunk_found(self):
        found = self._unit_diffs(maxdiff.diff(UNITS["mm"], UNITS["cm"]))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].a, struct.pack("<if", 3, 1.0))
        self.assertEqual(found[0].b, struct.pack("<if", 4, 1.0))

    def test_noise_filter(self):
        # A2 = units_in differs from units_mm in the same chunk, so it counts as noise and drops out.
        self.assertEqual(self._unit_diffs(maxdiff.diff(UNITS["mm"], UNITS["cm"], UNITS["in"])), [])
        self.assertEqual(len(self._unit_diffs(maxdiff.diff(UNITS["mm"], UNITS["cm"], UNITS["mm"]))), 1)

    def test_same_file(self):
        self.assertEqual(maxdiff.diff(UNITS["mm"], UNITS["mm"]), [])

    def test_command_line(self):
        code, out, err = _run(UNITS["mm"], UNITS["cm"], "--stream", "Scene", "--bytes", "8")
        self.assertEqual(code, 0, err)
        self.assertIn("8520#0", out)
        self.assertIn("A: 03 00 00 00 00 00 80 3f", out)
        self.assertIn("B: 04 00 00 00 00 00 80 3f", out)
        self.assertNotIn("Config", out)
        code, out, _ = _run(UNITS["mm"], UNITS["mm"])
        self.assertEqual((code, out), (0, "no difference\n"))


class TestUsage(unittest.TestCase):
    def test_usage_errors(self):
        self.assertEqual(_run("a.max")[0], 2)
        self.assertEqual(_run("a", "b", "c", "d")[0], 2)
        self.assertEqual(_run(os.path.join(ROOT, "no-such.max"), os.path.join(ROOT, "no-such-2.max"))[0], 2)

    def test_unreadable_file(self):
        bad = os.path.join(ROOT, "tests", "unit", "__init__.py")
        code, _, err = _run(bad, bad)
        self.assertEqual(code, 1)
        self.assertNotIn(ROOT, err)


if __name__ == "__main__":
    unittest.main()
