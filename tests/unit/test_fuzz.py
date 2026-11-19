# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The plain suite's slice of the .max fuzz harness (tests/unit/fuzz.py): the first CASES cases of every fixture
through the operator's reader path, without Blender. Each must read, be refused with a MaxFileError, or fail
only inside the material stage the operator guards; within fuzz.CASE_SECONDS each, the process under
fuzz.MEMORY_LIMIT. The slice runs in a child process (`fuzz.py slice`): its peak memory is the slice's own, and
a case past CASE_SECONDS ends it with the stack of that case (faulthandler). A failure names the case as
<fixture>:<k>; `python -I tests/unit/fuzz.py replay <fixture>:<k>` runs it again.

    python -I -m unittest discover tests
    MAXDROP_FUZZ_CASES=200 python -I -m unittest discover tests -p test_fuzz.py     # a longer slice
"""
import importlib.util
import json
import os
import subprocess
import sys
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

CASES = int(os.environ.get("MAXDROP_FUZZ_CASES", "16"))
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

    def test_structures_are_found(self):
        seed = fuzz.seeds("max", {"box_poly_standard.max"})[0]
        self.assertGreater(len(seed.heads), 100)
        self.assertGreater(len(seed.counts), 50)
        self.assertTrue(seed.dir_entries and seed.fat_entries)
        for region in ("header", "fat", "directory", "Scene", "ClassDirectory3", "DllDirectory"):
            self.assertIn(region, seed.regions)


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
        self.assertEqual(sum(r["counts"].values()), CASES * len(fuzz.FIXTURES))
        self.assertGreater(r["counts"].get("ok", 0), 0)
        self.assertGreater(r["counts"].get("refused", 0), 0)


if __name__ == "__main__":
    unittest.main()
