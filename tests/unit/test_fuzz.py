# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The plain suite's slice of the .max fuzz harness (tests/unit/fuzz.py): the first CASES cases of every seed (the
fixtures and the gzip variant the harness builds) through the operator's reader path, without Blender. Each must
read, be refused with a MaxFileError, or fail only inside the material stage the operator guards; within
fuzz.CASE_SECONDS each, the process under fuzz.MEMORY_LIMIT. The slice runs in a child process (`fuzz.py
slice`): its peak memory is the slice's own, and a case past CASE_SECONDS ends it with the stack of that case
(faulthandler). A failure names the case as <seed>:<k>; `python -I tests/unit/fuzz.py replay <seed>:<k>` runs it
again.

    python -I -m unittest discover tests
    MAXDROP_FUZZ_CASES=200 python -I -m unittest discover tests -p test_fuzz.py     # a longer slice
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("maxdrop_fuzz_harness", os.path.join(ROOT, "tests", "unit", "fuzz.py"))
fuzz = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fuzz
_spec.loader.exec_module(fuzz)

CASES = int(os.environ.get("MAXDROP_FUZZ_CASES", "10"))
TIMEOUT = 600  # seconds for a whole slice: a hang is caught per case first, by fuzz.CASE_SECONDS


class CasesTest(unittest.TestCase):
    def test_a_case_is_a_function_of_seed_fixture_and_index(self):
        seed = fuzz.seeds("max", {"box_poly_standard.max"})[0]
        self.assertEqual(fuzz.max_case(seed, 7), fuzz.max_case(seed, 7))
        self.assertNotEqual(fuzz.max_case(seed, 7)[0], fuzz.max_case(seed, 8)[0])
        self.assertNotEqual(fuzz.max_case(seed, 7)[0], fuzz.max_case(seed, 7, base=fuzz.SEED + 1)[0])

    def test_every_kind_of_mutation_changes_the_file(self):
        seed = fuzz.seeds("max", {"box_poly_standard.max"})[0]
        seen = {}
        for k in range(400):
            data, spec = fuzz.max_case(seed, k)
            kind = spec.split(" ", 1)[0]
            seen[kind] = seen.get(kind, 0) + (data != seed.raw)
        for kind in ("flip", "bytes", "cut", "chunk_size", "container", "count", "shrink", "dir", "header", "fat",
                     "swap"):
            with self.subTest(kind=kind):
                self.assertGreater(seen.get(kind, 0), 0)

    def test_a_reader_defect_escapes(self):
        """The operator reports a TypeError, KeyError or AttributeError of the reading as not imported
        (ops._DEFECTS); the harness's reader path does not mirror that net: such an error raised inside the reader
        leaves _Reader.read and is a case that escapes."""
        seed = fuzz.seeds("max", {"box_poly_standard.max"})[0]
        reader = fuzz._Reader()
        table = reader.assets.AssetTable
        original = table.__dict__["from_file"]  # the classmethod itself, put back as it was
        try:
            for error in (TypeError("maxdrop test"), KeyError("maxdrop test"), AttributeError("maxdrop test")):
                def defective(cls, cf, error=error):
                    raise error

                table.from_file = classmethod(defective)
                with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as folder:
                    with self.assertRaises(type(error)) as caught:
                        reader.read(seed.raw, folder)
                    self.assertIs(caught.exception, error)
        finally:
            table.from_file = original

    def test_structures_are_found(self):
        seed = fuzz.seeds("max", {"box_poly_standard.max"})[0]
        self.assertGreater(len(seed.heads), 100)
        self.assertGreater(len(seed.counts), 50)
        self.assertTrue(seed.dir_entries and seed.fat_entries)
        for region in ("header", "fat", "directory", "Scene", "ClassDirectory3", "DllDirectory"):
            self.assertIn(region, seed.regions)
        self.assertEqual(seed.gzip, {})
        self.assertIs(seed.kinds, fuzz._KINDS)


class GzipSeedTest(unittest.TestCase):
    """The seed whose Scene is gzip-compressed (3ds Max's Compress on Save), built from a fixture by the harness.
    Deflate output depends on the zlib build: nothing here pins a compressed length, a digest or outcome counts."""

    NAME = fuzz.GZIP_SEEDS[0]

    @classmethod
    def setUpClass(cls):
        cls.plain = fuzz.seeds("max", {cls.NAME})[0]
        cls.seed = fuzz.seeds("max", {cls.NAME + fuzz.GZIP_SUFFIX})[0]

    def test_it_is_a_seed_of_the_harness(self):
        self.assertIn(self.NAME + fuzz.GZIP_SUFFIX, fuzz.seed_names("max"))
        self.assertEqual(self.seed.name, self.NAME + fuzz.GZIP_SUFFIX)

    def test_the_scene_inflates_to_the_fixtures(self):
        with fuzz.cfb.CompoundFile(self.seed.raw) as cf, fuzz.cfb.CompoundFile(self.plain.raw) as plain:
            raw = cf.open("Scene", decompress=False)
            self.assertTrue(raw.compressed)
            self.assertGreaterEqual(raw.size, 4096)  # regular sectors, not the mini stream
            self.assertEqual(cf.open("Scene").read(), plain.open("Scene").read())
            for name in plain.names():
                if name != "Scene":
                    self.assertEqual(cf.open(name).read(), plain.open(name).read(), name)

    @unittest.skipIf(numpy is None, "numpy missing: the read reaches the geometry reader")
    def test_it_reads_like_its_fixture(self):
        reader = fuzz._Reader()

        def described(raw):
            with fuzz.cfb.CompoundFile(raw) as cf:
                sc = reader.scene.Scene.from_file(cf, encoding="AUTO")
                unit = reader.units.system_unit(sc)
                desc = reader.convert.describe(sc, unit.meters if unit else 1.0, unit,
                                               assets=reader.assets.AssetTable.from_file(cf),
                                               views=reader.cameras.saved_views(cf))
                return (repr(desc), [repr(n) for n in desc.nodes], [repr(m) for m in desc.meshes.values()],
                        [str(i) for i in desc.issues])

        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(reader.read(self.seed.raw, folder), "ok")
        self.assertEqual(described(self.seed.raw), described(self.plain.raw))

    def test_its_structures_are_found(self):
        g = self.seed.gzip["Scene"]
        self.assertGreaterEqual(len(g.members), 2)
        self.assertEqual([m[3] for m in g.members[:-1]], [m[0] for m in g.members[1:]])  # back to back
        self.assertLess(g.padding, len(g.data))
        self.assertEqual(g.data[g.padding:], bytes(len(g.data) - g.padding))
        # The compressed Scene is not walked for chunks; the streams beside it are.
        self.assertEqual({name for name, _ in self.seed.heads}, {"ClassDirectory3", "DllDirectory"})
        self.assertNotIn("Scene", {name for name, _, _, _ in self.seed.leaves})
        self.assertEqual(self.seed.kinds[-1][0], "multi")
        self.assertEqual(self.seed.kinds[:len(fuzz._KINDS) - 1], fuzz._KINDS[:-1])

    def test_every_gzip_kind_changes_the_file(self):
        seen = {}
        for k in range(600):
            data, spec = fuzz.max_case(self.seed, k)
            kind = spec.split(" ", 1)[0]
            seen[kind] = seen.get(kind, 0) + (data != self.seed.raw)
        for kind, _ in fuzz._GZIP_KINDS:
            with self.subTest(kind=kind):
                self.assertGreater(seen.get(kind, 0), 0)
        self.assertEqual(fuzz.max_case(self.seed, 7), fuzz.max_case(self.seed, 7))

    def test_cases_reach_the_inflate(self):
        refused = 0
        for k in range(300):
            data, spec = fuzz.max_case(self.seed, k)
            if not spec.startswith("gz_") or "; " in spec:  # one gzip kind alone: no other kind decides the outcome
                continue
            try:
                with fuzz.cfb.CompoundFile(data) as cf:
                    cf.open("Scene")
            except fuzz.cfb.CfbError as e:
                refused += str(e).startswith("compressed stream")
        self.assertGreater(refused, 0)


def run_slice(test, target, cases):
    """The slice in a child process (its peak memory is the slice's alone; a hang ends it, not the suite)."""
    env = dict(os.environ, **{name: "1" for name in fuzz._BLAS_THREADS})
    proc = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tests", "unit", "fuzz.py"), "slice",
                           "--target", target, "--cases", str(cases)], capture_output=True, text=True,
                          timeout=TIMEOUT, env=env)
    test.assertEqual(proc.returncode, 0, "the slice ended early (a case ran past %.0f s, or a crash): %s"
                     % (fuzz.CASE_SECONDS, proc.stderr[-4000:]))
    r = json.loads(proc.stdout.strip().splitlines()[-1])
    test.assertEqual(r["escapes"], [], "escaped: replay with tests/unit/fuzz.py replay <seed>:<k>")
    # The operator forgives a failure of the material stage, the harness counts it: in the slice it is a defect.
    test.assertEqual(r["materials"], {})
    test.assertLess(r["slowest"], fuzz.CASE_SECONDS, r["slowest_case"])
    if r["peak_memory"] is not None:
        test.assertLess(r["peak_memory"], fuzz.MEMORY_LIMIT)
    return r


@unittest.skipIf(numpy is None, "numpy missing")
class FuzzSliceTest(unittest.TestCase):
    def test_fixtures_survive_their_first_cases(self):
        self.assertTrue(fuzz.FIXTURES)
        r = run_slice(self, "max", CASES)
        self.assertEqual(sum(r["counts"].values()), CASES * len(fuzz.seed_names("max")))
        self.assertGreater(r["counts"].get("ok", 0), 0)
        self.assertGreater(r["counts"].get("refused", 0), 0)


if __name__ == "__main__":
    unittest.main()
