# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hostile scene packs: the plain suite's slice of the zip fuzz harness (tests/unit/fuzz.py) and a property test of
the name policy (archive.refused_reason) on random names. No Blender, no network, no program started (the .rar and
.7z backends are not registered here).

    python -I -m unittest discover tests
    MAXDROP_FUZZ_ZIP_CASES=2000 python -I -m unittest discover tests -p test_intake_fuzz.py
"""
import errno
import importlib.util
import os
import random
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("maxdrop_fuzz_harness", os.path.join(ROOT, "tests", "unit", "fuzz.py"))
if _spec.name in sys.modules:
    fuzz = sys.modules[_spec.name]
else:
    fuzz = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = fuzz
    _spec.loader.exec_module(fuzz)
archive = fuzz._archive()
_spec = importlib.util.spec_from_file_location("maxdrop_test_fuzz", os.path.join(ROOT, "tests", "unit", "test_fuzz.py"))
_test_fuzz = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_test_fuzz)
run_slice = _test_fuzz.run_slice

CASES = int(os.environ.get("MAXDROP_FUZZ_ZIP_CASES", "100"))
NAMES = 4000
CREATED = 300  # of them, created on disk
WINDOWS = os.name == "nt"
SEPARATORS = ("/", "\\")
# Pieces that make a name dangerous somewhere: separators, drive and stream colons, device names, dots and spaces at
# the end, control characters, look-alike slashes and dots, bidi overrides, lone surrogates, characters Windows
# cannot store, very long runs.
TOKENS = ("/", "\\", ":", ".", "..", " ", "\x00", "\x1f", "\x7f", "con", "CON", "aux", "nul", "PRN", "com1", "LPT9",
          "COM¹", "lpt³", "／", "＼", "∕", "․", "‮", "​", "\ud800", "\udfff",
          "<", ">", '"', "|", "?", "*", ".jpg", ".max", ".ies", "a", "Z", "é", "文", "~1", "$", "x" * 120)


def _random_names(rng):
    for _ in range(NAMES):
        r = rng.random()
        if r < 0.4:
            raw = bytes(rng.getrandbits(8) for _ in range(rng.randint(0, 40)))
            for codec in ("utf-8", "cp437", "cp932", "utf-16-le"):
                yield raw.decode(codec, "replace" if codec != "cp437" else "strict")
        else:
            yield "".join(rng.choice(TOKENS) for _ in range(rng.randint(1, 6)))


class ZipFuzzSliceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="maxdrop-fuzz-")
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_packs_survive_their_first_cases(self):
        r = run_slice(self, "zip", CASES)
        self.assertEqual(sum(r["counts"].values()), CASES * len(fuzz.ZIP_SEEDS))
        self.assertEqual(set(r["counts"]), {"ok", "refused"})

    def test_the_seed_packs_unpack(self):
        for seed in fuzz.seeds("zip"):
            sandbox = os.path.join(self.folder, "seed")
            os.mkdir(sandbox)
            self.assertEqual(fuzz.read_zip(seed.raw, sandbox), "ok")
            written = [p for p in fuzz._tree(sandbox) if p.startswith("out" + os.sep) and not p.endswith(os.sep)]
            self.assertTrue(any(p.endswith(".max") for p in written), written)
            self.assertTrue(any(p.endswith("wood.jpg") for p in written), written)
            self.assertFalse(any(p.endswith("readme.txt") for p in written), written)
            fuzz._remove(sandbox)


def _bases(rng):
    """The base name archive.Entry keeps of each random stored name: the policy judges what is left after the
    split at both separators."""
    for name in _random_names(rng):
        base = archive.Entry(name=name).base
        yield name, base


class NamePolicyPropertyTest(unittest.TestCase):
    """What refused_reason(base) is None promises, on random stored names: a plain file name of the folder it is
    written into, the same name read back, nothing else touched."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="maxdrop-names-")
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_an_accepted_name_is_a_plain_file_name(self):
        rng = random.Random(fuzz.SEED)
        accepted = refused = 0
        for stored, name in _bases(rng):
            self.assertFalse(any(c in name for c in SEPARATORS), stored)
            reason = archive.refused_reason(name)
            if reason is not None:
                refused += 1
                continue
            accepted += 1
            with self.subTest(name=name):
                self.assertTrue(name and name not in (".", ".."))
                self.assertFalse(any(c in name for c in SEPARATORS + (":",)))
                self.assertFalse(any(ord(c) < 32 or ord(c) == 127 for c in name))
                self.assertNotIn(name[-1], ". ")
                self.assertFalse(any(c in name for c in '<>"|?*'))
                self.assertLessEqual(len(name), archive.MAX_NAME_LENGTH)
                stem = name.split(".")[0].rstrip(" ").upper()
                self.assertNotIn(stem, ("CON", "PRN", "AUX", "NUL") + tuple("COM%d" % i for i in range(10))
                                 + tuple("LPT%d" % i for i in range(10)))
        self.assertGreater(accepted, 100)
        self.assertGreater(refused, 100)

    def test_an_accepted_name_creates_exactly_that_file(self):
        rng = random.Random(fuzz.SEED + 1)
        names = [n for _, n in _bases(rng) if archive.refused_reason(n) is None]
        rng.shuffle(names)
        created = 0
        for i, name in enumerate(names[:CREATED]):
            folder = os.path.join(self.folder, "n%d" % i)
            os.mkdir(folder)
            target = os.path.join(folder, name)
            with self.subTest(name=name):
                self.assertEqual(os.path.dirname(target), folder)
                try:
                    with open(target, "xb") as f:
                        f.write(b"x")
                except UnicodeEncodeError:  # a lone surrogate off Windows: the file system API refuses it
                    self.assertEqual(os.listdir(folder), [])
                    continue
                except OSError as e:
                    # macOS (APFS) refuses a name with an unassigned code point or bytes that are not UTF-8
                    # (EILSEQ); nothing is created, as above.
                    if e.errno != errno.EILSEQ or sys.platform != "darwin":
                        raise
                    self.assertEqual(os.listdir(folder), [])
                    continue
                listed = os.listdir(folder)
                self.assertEqual(len(listed), 1)
                self.assertEqual(archive.name_key(listed[0]), archive.name_key(name))
                self.assertEqual(os.listdir(self.folder).count("n%d" % i), 1)
            created += 1
        self.assertGreater(created, CREATED // 2)
        self.assertEqual(sorted(os.listdir(self.folder)), sorted("n%d" % i for i in range(min(CREATED, len(names)))))


if __name__ == "__main__":
    unittest.main()
