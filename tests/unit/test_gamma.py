# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/gamma.py, the Gamma/LUT setting of a .max: no Blender. Every committed fixture (saved
with the gamma off, but gamma_swatches: on), and synthetic 0x6010 payloads and scenes for what no fixture has.

    python -I -m unittest discover tests
"""
import glob
import importlib.util
import math
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
GAMMA_ON = {"gamma_swatches"}  # the fixtures saved with the gamma on; every other one has it off


def _load(name, path, package_dir=None):
    if name in sys.modules:
        return sys.modules[name]
    kw = {"submodule_search_locations": [package_dir]} if package_dir else {}
    spec = importlib.util.spec_from_file_location(name, path, **kw)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_READER = os.path.join(ROOT, "maxdrop", "reader")
_load("maxdrop_reader", os.path.join(_READER, "__init__.py"), _READER)
cfb = _load("maxdrop_reader.cfb", os.path.join(_READER, "cfb.py"))
classdir = _load("maxdrop_reader.classdir", os.path.join(_READER, "classdir.py"))
scene = _load("maxdrop_reader.scene", os.path.join(_READER, "scene.py"))
gamma = _load("maxdrop_reader.gamma", os.path.join(_READER, "gamma.py"))


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def _classes(*entries):
    """A ClassDirectory of (class_a, class_b, superclass) entries, index = position."""
    return classdir.ClassDirectory([classdir.ClassEntry(i, classdir.ClassId(a, b), sc, "c%d" % i, -1, None)
                                    for i, (a, b, sc) in enumerate(entries)])


ENV_CLASS = (0xEE448B23, 0, 0x1010)
ON = struct.pack("<Iff", 1, 2.2, 2.2)


@unittest.skipUnless(FIXTURES, "no fixtures")
class TestFixtures(unittest.TestCase):
    def test_every_fixture(self):
        for path in FIXTURES:
            name = os.path.basename(path)[:-4]
            with self.subTest(name), cfb.CompoundFile(path) as cf:
                self.assertEqual(gamma.scene_gamma(cf), (name in GAMMA_ON, 2.2, 2.2))

    def test_scene_works_as_source(self):
        with cfb.CompoundFile(FIXTURES[0]) as cf:
            s = scene.Scene.from_file(cf)
            self.assertIsNotNone(gamma.scene_gamma(s))
            del s


class TestDecode(unittest.TestCase):
    def test_on_and_off(self):
        self.assertEqual(gamma.decode(ON), (True, 2.2, 2.2))
        self.assertEqual(gamma.decode(struct.pack("<Iff", 0, 1.0, 1.8)), (False, 1.0, 1.8))

    def test_refused(self):
        for payload in (struct.pack("<Iff", 2, 2.2, 2.2), struct.pack("<Iff", 0xFFFFFFFF, 2.2, 2.2), ON[:11], b""):
            with self.subTest(payload.hex()):
                self.assertIsNone(gamma.decode(payload))

    def test_unusable_gammas_keep_the_switch(self):
        for bad in (math.nan, math.inf, 0.0, -2.2):
            with self.subTest(bad):
                self.assertEqual(gamma.decode(struct.pack("<Iff", 1, bad, bad)), (True, None, None))

    def test_longer_payload_reads_its_head(self):
        self.assertEqual(gamma.decode(ON + b"\x01\x02"), (True, 2.2, 2.2))


class TestSyntheticScene(unittest.TestCase):
    def _gamma(self, classes, *objects):
        return gamma.scene_gamma(scene.Scene(node(0x2025, *objects), classes))

    def test_found_in_the_render_environment(self):
        classes = _classes((1, 0, 1), ENV_CLASS)
        self.assertEqual(self._gamma(classes, node(0, leaf(0x0962)), node(1, leaf(0x6010, ON))), (True, 2.2, 2.2))

    def test_no_render_environment(self):
        self.assertIsNone(self._gamma(_classes((1, 0, 1)), node(0, leaf(0x6010, ON))))

    def test_same_class_id_other_superclass(self):
        self.assertIsNone(self._gamma(_classes((0xEE448B23, 0, 0x200)), node(0, leaf(0x6010, ON))))

    def test_without_the_chunk_as_a_container_or_as_a_leaf(self):
        classes = _classes(ENV_CLASS)
        self.assertIsNone(self._gamma(classes, node(0, leaf(0x0100, b"\0" * 4))))
        self.assertIsNone(self._gamma(classes, node(0, node(0x6010, leaf(1, ON)))))
        self.assertIsNone(self._gamma(classes, leaf(0, ON)))

    def test_unreadable_file(self):
        class Broken:
            def exists(self, name):
                return False
        self.assertIsNone(gamma.scene_gamma(Broken()))


if __name__ == "__main__":
    unittest.main()
