# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/materials.py: no Blender. RAW-PARAM PARITY: every committed fixture's material graph
against its 3ds Max oracle (tests/fixtures/<name>.oracle.json, `material_graph`): the same materials and maps
reached from the nodes, and every stored parameter of every block, looked up by parameter id (ParamBlock2) or
index (ParamBlock), equal to what 3ds Max reports. Synthetic scenes for the walk: cycles, damaged references,
objects that are not materials.

    python -I -m unittest discover tests
"""
import glob
import importlib.util
import json
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
FIXTURES = sorted(glob.glob(os.path.join(FIXTURE_DIR, "*.max")))
TOLERANCE = 1e-5  # relative above 1: the oracle prints 6 significant digits
# compared values per V-Ray fixture: guards against a parity test that compares nothing
FLOORS = {"vray_basic": 190, "vray_maps": 630, "vray_wrappers": 2000, "standard_physical": 290}


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
chunks = _load("maxdrop_reader.chunks", os.path.join(_READER, "chunks.py"))
classdir = _load("maxdrop_reader.classdir", os.path.join(_READER, "classdir.py"))
classids = _load("maxdrop_reader.classids", os.path.join(_READER, "classids.py"))
scene = _load("maxdrop_reader.scene", os.path.join(_READER, "scene.py"))
pblock = _load("maxdrop_reader.pblock", os.path.join(_READER, "pblock.py"))
materials = _load("maxdrop_reader.materials", os.path.join(_READER, "materials.py"))
ChunkError = chunks.ChunkError


def _oracle(path):
    with open(path[:-len(".max")] + ".oracle.json", encoding="ascii") as f:
        return json.load(f)


def _cid(hex_pair):
    return tuple(int(h, 16) for h in hex_pair)


def _key(entry):
    return _cid(entry["class_id"]), entry["name"]


class Parity:
    """Compares one fixture's reader graph with its oracle graph and counts what it compared."""

    def __init__(self, case, graph, oracle_graph, by_key):
        self.case, self.graph, self.oracle_graph, self.by_key = case, graph, oracle_graph, by_key
        self.compared, self.skipped, self.not_stored = 0, 0, 0

    def number(self, ours, theirs, what):
        self.case.assertIsInstance(ours, (int, float), what)
        self.case.assertLessEqual(abs(ours - theirs), TOLERANCE * max(1.0, abs(theirs)), what)
        self.compared += 1

    def value(self, base, ours, theirs, what):
        self.case.assertNotIsInstance(ours, pblock.Animated, what)  # no fixture animates a parameter
        if base in pblock.FLOAT_TYPES:
            self.number(ours, theirs, what)
        elif base in pblock.INT_TYPES:
            self.case.assertEqual(ours, theirs, what)
            self.compared += 1
        elif base in pblock.VECTOR_SIZES:
            self.case.assertEqual(len(ours), len(theirs), what)
            for k, (a, b) in enumerate(zip(ours, theirs)):
                self.number(a, b, "%s[%d]" % (what, k))
        elif base == pblock.STRING:
            if ours is None and theirs is not None:  # computed when asked (Standard's shaderByName), saved as none
                self.skipped += 1
                return
            self.case.assertEqual(ours, theirs, what)
            self.compared += 1
        elif base in (pblock.MATERIAL, pblock.TEXMAP):
            self.case.assertIsInstance(ours, pblock.Reference, what)
            want = None if theirs is None else self.by_key[_key(self.oracle_graph[theirs])]
            self.case.assertEqual(ours.index, want, what)
            self.compared += 1
        else:  # file names are asset ids in the file (resolved by a later reader); nodes, bitmaps: oracle null
            self.skipped += 1

    def blocks(self, oracle_blocks, blocks, legacy, where):
        for b in oracle_blocks:
            if b["kind"] == "pb2":
                ours = blocks.get(b["ref"])
                self.case.assertIsNotNone(ours, "%s: ParamBlock2 at slot %d" % (where, b["ref"]))
                self.case.assertEqual(ours.block_id, b["block_id"], where)
                self.case.assertEqual(ours.issues, (), where)  # also: as many entries as the header announces
                self.case.assertTrue(set(ours.ids()) <= {p["id"] for p in b["params"]}, where)
                for p in b["params"]:
                    what = "%s block %d param %d %s" % (where, b["block_id"], p["id"], p["name"])
                    rp = ours.param(p["id"])
                    if rp is None:  # transient (mostly), a block that saves nothing (Standard's dynamics) or an
                        # empty table (Composite's unnamed parameters 0, 2 and 4)
                        empty = p["type"] & pblock.TABLE and p["value"] == []
                        self.case.assertTrue(p["transient"] or len(ours) == 0 or empty, what + ": not stored")
                        self.not_stored += 1
                        continue
                    if p["transient"]:  # an alias saved anyway (VRayBlendMtl coatMtl_0, blend_0): Max computes it
                        self.skipped += 1  # from the table, the saved value is stale and a reference slot empty
                        continue
                    self.case.assertEqual(rp.type, p["type"], what)
                    self.case.assertIsNone(rp.error, what)
                    base = p["type"] & ~pblock.TABLE
                    if rp.table:
                        self.case.assertEqual(len(rp.values), len(p["value"]), what)
                        for k, (a, t) in enumerate(zip(rp.values, p["value"])):
                            self.value(base, a, t, "%s[%d]" % (what, k))
                    else:
                        self.value(base, rp.values[0], p["value"], what)
            else:
                ours = legacy.get(b["ref"])
                self.case.assertIsNotNone(ours, "%s: ParamBlock at slot %d" % (where, b["ref"]))
                self.case.assertEqual(ours.issues, (), where)
                self.case.assertEqual(ours.indices(), [p["index"] for p in b["params"]], where)
                for p in b["params"]:
                    what = "%s old block param %d" % (where, p["index"])
                    self.case.assertEqual(ours.type(p["index"]), p["type"], what)
                    self.value({0: 0, 1: 1, 2: 2, 3: 3, 4: 4}[p["type"]], ours.get(p["index"]), p["value"], what)


class Fixtures(unittest.TestCase):
    def test_raw_param_parity(self):
        for path in FIXTURES:
            name = os.path.basename(path)[:-4]
            with self.subTest(name), cfb.CompoundFile(path) as cf:
                oracle = _oracle(path)["material_graph"]
                s = scene.Scene.from_file(cf)
                g = materials.MaterialGraph(s)
                order = g.walk(s.node(i).material for i in s.walk())
                self.assertEqual(g.issues, [])
                by_key = {}
                for i in order:
                    m = g.get(i)
                    key = (tuple(m.class_id), m.name)
                    self.assertNotIn(key, by_key, "names are unique in the fixtures")
                    by_key[key] = i
                self.assertEqual(sorted(by_key), sorted(_key(e) for e in oracle))
                parity = Parity(self, g, oracle, by_key)
                for e in oracle:
                    m = g.get(by_key[_key(e)])
                    where = "%s %s" % (name, e["name"])
                    self.assertEqual(m.superclass, e["superclass"], where)
                    self.assertEqual(m.is_material, e["superclass"] == classids.SC_MATERIAL, where)
                    self.assertEqual(m.issues, (), where)
                    parity.blocks(e["blocks"], m.blocks, m.legacy, where)
                    for part in e["parts"]:
                        ours = m.parts.get(part["ref"])
                        self.assertIsNotNone(ours, "%s: part at slot %d" % (where, part["ref"]))
                        self.assertEqual(tuple(ours.class_id), _cid(part["class_id"]), where)
                        parity.blocks(part["blocks"], ours.blocks, ours.legacy, "%s part %d" % (where, part["ref"]))
                    self.assertEqual(len(m.parts), len(e["parts"]), where)
                    children = {(tuple(g.get(c).class_id), g.get(c).name) for c in m.children}
                    for sub in e["subs"]:
                        self.assertIn(_key(oracle[sub["target"]]), children, where)
                if name in FLOORS:
                    self.assertGreaterEqual(parity.compared, FLOORS[name], name)
                del cf

    def test_vray_values_by_id(self):
        """A few values docs/FORMAT.md quotes, read by parameter id as the converters will."""
        path = os.path.join(FIXTURE_DIR, "vray_basic.max")
        with cfb.CompoundFile(path) as cf:
            s = scene.Scene.from_file(cf)
            g = materials.MaterialGraph(s)
            m = g.get(s.node(s.walk()[0]).material)
            self.assertEqual(m.class_id, classids.VRAY_MTL)
            self.assertEqual(m.name, "FixtureVRay")
            basic, brdf, maps = m.block(1), m.block(2), m.block(4)
            self.assertEqual([round(c * 255) for c in basic.get(1)], [201, 31, 41])  # diffuse
            self.assertAlmostEqual(basic.get(3), 0.83, places=6)  # reflection_glossiness
            self.assertEqual(basic.get(4), 9)  # reflection_subdivs
            self.assertEqual(basic.get(8), 0)  # reflection_fresnel off
            self.assertAlmostEqual(basic.get(9), 1.61, places=6)  # refraction_ior
            self.assertEqual(brdf.get(10), 4)  # brdf_type GGX
            self.assertAlmostEqual(brdf.get(58), 33.0, places=5)  # anisotropy_rotation: stored as shown
            self.assertAlmostEqual(maps.get(200), 63.0, places=5)  # texmap_diffuse_multiplier
            self.assertEqual(m.param(3), basic.get(3))
            self.assertIsNone(basic.get(102))  # bump_multiplier: transient, not stored
            self.assertEqual(maps.get(100), pblock.Reference(None))  # texmap_diffuse: empty

    def test_wrappers_by_id(self):
        path = os.path.join(FIXTURE_DIR, "vray_wrappers.max")
        with cfb.CompoundFile(path) as cf:
            s = scene.Scene.from_file(cf)
            g = materials.MaterialGraph(s)
            mats = {g.get(s.node(i).material).name: g.get(s.node(i).material) for i in s.walk()}
            name = lambda ref: g.get(ref.index).name if ref.index is not None else None  # noqa: E731
            multi = mats["FixtureMulti"]
            self.assertEqual(multi.class_id, classids.MULTI_SUB_MTL)
            self.assertEqual([name(r) for r in multi.block(0).value(0)],
                             ["FixtureSubOne", "FixtureSubThree", "FixtureSubSeven"])
            self.assertEqual(multi.block(0).value(3), [0, 2, 6])  # material IDs 1, 3, 7, stored zero-based
            self.assertEqual(multi.block(0).value(2), ["SlotOne", "SlotThree", "SlotSeven"])
            blend = mats["FixtureBlend"]
            self.assertEqual(name(blend.block(0).get(0)), "FixtureBlendBase")  # held by the block
            self.assertEqual([name(r) for r in blend.block(0).value(1)][:3], ["FixtureCoatA", "FixtureCoatB", None])
            two = mats["FixtureTwoSided"]
            self.assertEqual((name(two.block(0).get(0)), name(two.block(0).get(1))), ("FixtureFront", "FixtureBack"))
            shell = mats["FixtureShell"]
            self.assertEqual((name(shell.block(0).get(2)), name(shell.block(0).get(3)), shell.block(0).get(1)),
                             ("FixtureShellOriginal", "FixtureShellBaked", 0))

    def test_maps_by_id(self):
        path = os.path.join(FIXTURE_DIR, "vray_maps.max")
        with cfb.CompoundFile(path) as cf:
            s = scene.Scene.from_file(cf)
            g = materials.MaterialGraph(s)
            mats = {g.get(s.node(i).material).name: g.get(s.node(i).material) for i in s.walk()}
            maps = mats["FixtureVRayMaps"].block(4)
            slots = {pid: g.get(maps.get(pid).index).name for pid in (100, 101, 103, 104, 112)}
            self.assertEqual(slots, {100: "FixtureDiffuseMap", 101: "FixtureReflectMap", 103: "FixtureBumpMap",
                                     104: "FixtureGlossMap", 112: "FixtureOpacityMap"})
            diffuse = g.get(maps.get(100).index)
            self.assertEqual(diffuse.class_id, classids.BITMAP_TEX)
            coords = diffuse.parts[0]
            self.assertEqual(coords.superclass, classids.SC_UVGEN)
            old = coords.legacy[0]
            self.assertEqual((old.get(2), old.get(3)), (2.0, 2.5))  # U, V tiling
            self.assertAlmostEqual(old.get(6), 0.261799, places=6)  # W angle 15 degrees, in radians
            self.assertIsInstance(diffuse.block(0).get(13), pblock.Asset)  # the bitmap: an asset id
            normal = g.get(mats["FixtureVRayNormal"].block(4).get(103).index)
            self.assertEqual(normal.class_id, classids.VRAY_NORMAL_MAP)
            self.assertEqual((g.get(normal.block(0).get(0).index).name, g.get(normal.block(0).get(4).index).name),
                             ("FixtureNormalMap", "FixtureNormalBumpMap"))  # held by the block, slots 0 and 1


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def container(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def refs(*indices):
    return leaf(0x2034, struct.pack("<%di" % len(indices), *indices))


MTL, MAP, PB2, OTHER = 0, 1, 2, 3
CLASSES = classdir.ClassDirectory([
    classdir.ClassEntry(MTL, classdir.ClassId(0x10, 0), classids.SC_MATERIAL, "m", -1, None),
    classdir.ClassEntry(MAP, classdir.ClassId(0x20, 0), classids.SC_TEXMAP, "t", -1, None),
    classdir.ClassEntry(PB2, classids.PARAM_BLOCK2, classids.SC_PARAMETER_BLOCK2, "ParamBlock2", -1, None),
    classdir.ClassEntry(OTHER, classdir.ClassId(0x30, 0), classids.SC_REF_TARGET, "o", -1, None)])


def name_chunk(text):
    return container(0x4000, leaf(0x4001, text.encode("utf-16-le")))


def make_scene(*objects):
    return scene.Scene(container(0x2025, *objects), CLASSES)


class Synthetic(unittest.TestCase):
    def test_cycle_is_walked_once(self):
        s = make_scene(container(MTL, refs(1), name_chunk("A")), container(MAP, refs(0), name_chunk("B")))
        g = materials.MaterialGraph(s)
        self.assertEqual(g.walk([0]), [0, 1])
        self.assertEqual(g.get(1).children, [0])
        self.assertEqual((g.get(0).name, g.get(1).name), ("A", "B"))

    def test_self_reference_is_not_a_child(self):
        s = make_scene(container(MTL, refs(0)))
        g = materials.MaterialGraph(s)
        self.assertEqual(g.get(0).children, [])
        self.assertEqual(g.walk([0, 0, None]), [0])

    def test_not_a_material(self):
        s = make_scene(container(OTHER), container(MTL, refs(0)))
        g = materials.MaterialGraph(s)
        with self.assertRaises(ChunkError):
            g.get(0)
        self.assertEqual(g.walk([0, 1]), [1])
        self.assertEqual(g.get(1).children, [])

    def test_damaged_reference_poisons_only_its_object(self):
        s = make_scene(container(MTL, refs(1, 2)), container(MAP, refs(99)), container(MAP))
        g = materials.MaterialGraph(s)
        self.assertEqual(g.walk([0]), [0, 2])
        self.assertEqual([i.index for i in g.issues], [1])

    def test_damaged_block_is_left_out_with_an_issue(self):
        s = make_scene(container(MTL, refs(1, 2)), container(PB2, leaf(0x100E, b"\x01")), container(MAP))
        g = materials.MaterialGraph(s)
        m = g.get(0)
        self.assertEqual(m.blocks, {})
        self.assertEqual(m.children, [2])
        self.assertEqual(len(m.issues), 1)
        self.assertIn("left out", m.issues[0])

    def test_index_outside_the_objects_is_a_chunk_error(self):
        g = materials.MaterialGraph(make_scene(container(MTL)))
        with self.assertRaises(ChunkError):
            g.get(5)
        self.assertEqual(g.walk([5, 0]), [0])
        self.assertEqual([i.index for i in g.issues], [5])

    def test_long_chain_is_iterative(self):
        n = 5000
        s = make_scene(*[container(MAP, refs(i + 1)) for i in range(n - 1)], container(MAP))
        self.assertEqual(len(materials.MaterialGraph(s).walk([0])), n)


if __name__ == "__main__":
    unittest.main()
