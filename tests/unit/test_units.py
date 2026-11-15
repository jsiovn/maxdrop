# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/units.py, the system unit of a .max: no Blender. Every committed fixture against its
3ds Max oracle (units.system_type), the three units_* fixtures by meters per unit, and synthetic 0x8520 payloads
for the unit types and scales no fixture has.

    python -I -m unittest discover tests
"""
import glob
import importlib.util
import json
import math
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))


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
units = _load("maxdrop_reader.units", os.path.join(_READER, "units.py"))


def _fixture(name):
    return os.path.join(ROOT, "tests", "fixtures", name + ".max")


def _unit_of(path):
    with cfb.CompoundFile(path) as cf:
        return units.system_unit(cf)


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def _classes(*entries):
    """A ClassDirectory of (class_a, class_b, superclass) entries, index = position."""
    return classdir.ClassDirectory([classdir.ClassEntry(i, classdir.ClassId(a, b), sc, "c%d" % i, -1, None)
                                    for i, (a, b, sc) in enumerate(entries)])


SCENE_CLASS = (0x2222, 0, 0x100)


@unittest.skipUnless(FIXTURES, "no fixtures")
class TestFixtures(unittest.TestCase):
    def test_units_fixtures_by_meters(self):
        for name, meters in (("units_mm", 0.001), ("units_cm", 0.01), ("units_in", 0.0254)):
            with self.subTest(name):
                unit = _unit_of(_fixture(name))
                self.assertIsNotNone(unit)
                self.assertEqual(unit.meters, meters)

    def test_box_is_millimeters(self):
        self.assertEqual(_unit_of(_fixture("box_poly_standard")), ("millimeters", 0.001))

    def test_every_fixture_against_the_oracle(self):
        for path in FIXTURES:
            with self.subTest(os.path.basename(path)):
                with open(path[:-4] + ".oracle.json", encoding="ascii") as f:
                    oracle = json.load(f)["units"]
                self.assertEqual(oracle["system_scale"], 1)
                self.assertEqual(_unit_of(path).name, oracle["system_type"])

    def test_scene_works_as_source(self):
        with cfb.CompoundFile(_fixture("units_in")) as cf:
            s = scene.Scene.from_file(cf)
            self.assertEqual(units.system_unit(s), ("inches", 0.0254))
            del s


class TestDecode(unittest.TestCase):
    def test_every_unit_type(self):
        expect = {0: ("inches", 0.0254), 1: ("feet", 0.3048), 2: ("miles", 1609.344), 3: ("millimeters", 0.001),
                  4: ("centimeters", 0.01), 5: ("meters", 1.0), 6: ("kilometers", 1000.0)}
        for code, unit in expect.items():
            with self.subTest(code):
                self.assertEqual(units.decode(struct.pack("<if", code, 1.0)), unit)

    def test_custom_scale(self):
        unit = units.decode(struct.pack("<if", 4, 2.54))
        self.assertEqual(unit.name, "2.54 centimeters")
        self.assertAlmostEqual(unit.meters, 0.0254, places=12)
        self.assertEqual(units.decode(struct.pack("<if", 5, 0.5)), ("0.5 meters", 0.5))

    def test_refused(self):
        for payload in (struct.pack("<if", 7, 1.0), struct.pack("<if", -1, 1.0), struct.pack("<if", 3, 0.0),
                        struct.pack("<if", 3, -1.0), struct.pack("<if", 3, math.nan), struct.pack("<if", 3, math.inf),
                        struct.pack("<i", 3), b""):
            with self.subTest(payload.hex()):
                self.assertIsNone(units.decode(payload))

    def test_longer_payload_reads_its_head(self):
        self.assertEqual(units.decode(struct.pack("<ifI", 5, 1.0, 99)), ("meters", 1.0))


class TestSyntheticScene(unittest.TestCase):
    def _unit(self, classes, *objects):
        return units.system_unit(scene.Scene(node(0x2025, *objects), classes))

    def test_found_in_the_scene_object(self):
        classes = _classes((1, 0, 1), SCENE_CLASS)
        unit = self._unit(classes, node(0, leaf(0x0962, b"")), node(1, leaf(0x8520, struct.pack("<if", 5, 1.0))))
        self.assertEqual(unit, ("meters", 1.0))

    def test_no_scene_class(self):
        classes = _classes((1, 0, 1))
        self.assertIsNone(self._unit(classes, node(0, leaf(0x8520, struct.pack("<if", 5, 1.0)))))

    def test_same_class_id_other_superclass_is_not_the_scene(self):
        classes = _classes((0x2222, 0, 0x200))
        self.assertIsNone(self._unit(classes, node(0, leaf(0x8520, struct.pack("<if", 5, 1.0)))))

    def test_scene_without_the_chunk_or_as_a_leaf(self):
        classes = _classes(SCENE_CLASS)
        self.assertIsNone(self._unit(classes, node(0, leaf(0x8500, b"\0" * 8))))
        self.assertIsNone(self._unit(classes, leaf(0)))

    def test_damaged_payload(self):
        classes = _classes(SCENE_CLASS)
        self.assertIsNone(self._unit(classes, node(0, leaf(0x8520, b"\x05\0"))))

    def test_damaged_scene_object(self):
        classes = _classes(SCENE_CLASS)
        cut = struct.pack("<HI", 0, 6 + 4 | 0x80000000) + b"\x20\x85\0\0"  # its child header is cut short
        self.assertIsNone(self._unit(classes, cut))

    def test_file_without_a_scene_stream(self):
        class NoScene:
            def exists(self, name):
                return False

        self.assertIsNone(units.system_unit(NoScene()))


if __name__ == "__main__":
    unittest.main()
