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
import importlib
import json
import math
import os
import struct
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
FIXTURES = sorted(glob.glob(os.path.join(FIXTURE_DIR, "*.max")))
TOLERANCE = 1e-5  # relative above 1: the oracle prints 6 significant digits
# compared values per fixture, every fixture listed (test_every_fixture_has_a_floor): guards against a parity test
# that compares nothing. A fixture whose graph is one Standard material compares 125; the light fixtures have no
# material.
FLOORS = {"vray_lights": 0, "lights_standard": 0, "lights_photometric": 0, "box_poly_standard": 120, "cameras": 120,
          "arc_pie_reverse": 120, "controllers": 120,
          "corona_layered": 630, "corona_legacy": 370, "corona_light": 180,
          "corona_maps": 950, "corona_physical": 500, "editable_mesh": 380, "extrude": 120, "gamma_swatches": 540,
          "hierarchy": 120, "instances": 120, "layers_flags": 120,
          "layers_more": 120, "lookat": 120, "modifier_pivot": 120,
          "multi_uv": 120, "pblock_animated": 920, "primitives": 120, "saved_as_2017": 120,
          "saved_as_2018": 120, "saved_as_2019": 120, "shapes": 120, "shapes_more": 120, "stack_basic": 120,
          "stack_convert": 120, "stack_shell": 120, "stack_wsm": 120, "standard_physical": 290, "standard_shaders": 1600,
          "texmap_rules": 1570, "texmap_wrappers": 1690, "units_cm": 120, "units_in": 120, "units_mm": 120, "uvwmap": 120,
          "uvwmap_oblique": 120, "uvwmap_pole": 120, "vray_basic": 190, "vray_maps": 630, "vray_more": 2500,
          "vray_texmaps": 2900, "vray_wrappers": 2000}


_PKG = "maxdrop_convert_test"  # the package the convert tests make: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
cfb = importlib.import_module(_PKG + ".reader.cfb")
chunks = importlib.import_module(_PKG + ".reader.chunks")
classdir = importlib.import_module(_PKG + ".reader.classdir")
classids = importlib.import_module(_PKG + ".reader.classids")
scene = importlib.import_module(_PKG + ".reader.scene")
pblock = importlib.import_module(_PKG + ".reader.pblock")
materials = importlib.import_module(_PKG + ".reader.materials")
owner_slots = importlib.import_module(_PKG + ".reader.owner_slots")
STANDARD_SHADER_SLOT = 2  # a Standard material's reference to its shader
BLINN_LAYOUT = {classids.PHONG_SHADER, classids.BLINN_SHADER, classids.METAL_SHADER}  # map channels as created
ChunkError = chunks.ChunkError


def _oracle(path):
    with open(path[:-len(".max")] + ".oracle.json", encoding="ascii") as f:
        return json.load(f)


def _cid(hex_pair):
    return tuple(int(h, 16) for h in hex_pair)


def _key(entry):
    return _cid(entry["class_id"]), entry["name"]


def _saved_value(chunk):
    """A Bezier Float's or Bezier Color's saved value (0x2501, directly or inside 0x7127): a float or a tuple."""
    holder = chunk.first(0x7127) or chunk
    value = holder.first(0x2501)
    if value is None:
        raise AssertionError("controller at %d without a saved value (0x2501)" % chunk.offset)
    floats = value.unpack("<%df" % (value.payload_size // 4))
    return floats[0] if len(floats) == 1 else floats


class Parity:
    """Compares one fixture's reader graph with its oracle graph and counts what it compared."""

    def __init__(self, case, graph, oracle_graph, by_key, scene_):
        self.case, self.graph, self.oracle_graph, self.by_key, self.scene = case, graph, oracle_graph, by_key, scene_
        self.compared, self.skipped, self.not_stored, self.animated = 0, 0, 0, 0

    def controller(self, ours, theirs, block_index, what):
        """An animated parameter: the controller the reader names is the block reference the oracle found it at,
        of the oracle's class, and its saved value is the oracle's value at frame 0."""
        self.case.assertIsInstance(ours, pblock.Animated, what)
        self.case.assertIsNotNone(ours.index, what)
        self.case.assertEqual(ours.index, self.scene.refs(block_index).get(theirs["slot"]), what + ": slot")
        self.case.assertEqual(tuple(self.scene.entry(ours.index).class_id), _cid(theirs["class_id"]), what)
        saved = _saved_value(self.scene.chunk(ours.index))
        if isinstance(theirs["value"], list):
            self.case.assertEqual(len(saved), len(theirs["value"]), what)
            for k, (a, b) in enumerate(zip(saved, theirs["value"])):
                self.number(a, b, "%s saved[%d]" % (what, k))
        else:
            self.number(saved, theirs["value"], what + " saved")
        self.animated += 1

    def number(self, ours, theirs, what):
        self.case.assertIsInstance(ours, (int, float), what)
        self.case.assertLessEqual(abs(ours - theirs), TOLERANCE * max(1.0, abs(theirs)), what)
        self.compared += 1

    def value(self, base, ours, theirs, what):
        self.case.assertNotIsInstance(ours, pblock.Animated, what)  # the oracle names no controller here
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

    def stale(self, owner, oracle_block):
        """skip(pid, k, ours): whether a value of this block is one the file keeps stale while 3ds Max computes its
        own (standard_shaders):
        - a Standard material whose shader is not Blinn, Phong or Metal, block 3 mapAmounts at a slot without a
          map: the file keeps the amounts of the material as created (Blinn's map channels, bump 0.3 at slot 8),
          3ds Max answers those of its shader's channels (Anisotropic: 0.3 at slot 11). Every amount without a
          map is skipped (only those two slots differ): none is used.
        - a Physical Material's mapM0 ... mapM20 (block 0, 250-270): saved empty, 3ds Max answers the map of
          parameter id - 150 (mapM1 = base_color_map)."""
        entry = self.scene.entry(owner)
        params = {p["id"]: p["value"] for p in oracle_block["params"]}
        if entry is None or entry.superclass != classids.SC_MATERIAL:
            return lambda pid, k, ours: False
        if entry.class_id == classids.STANDARD_MTL and oracle_block["block_id"] == 3:
            slot = self.scene.refs(owner).get(STANDARD_SHADER_SLOT)
            shader = self.scene.entry(slot) if slot is not None else None
            if shader is not None and shader.class_id not in BLINN_LAYOUT:
                return lambda pid, k, ours: pid == 2 and params[1][k] is None
        if entry.class_id == classids.PHYSICAL_MTL and oracle_block["block_id"] == 0:
            return lambda pid, k, ours: (250 <= pid <= 270 and isinstance(ours, pblock.Reference)
                                         and ours.index is None and params.get(pid) is not None
                                         and params.get(pid) == params.get(pid - 150))
        return lambda pid, k, ours: False

    def blocks(self, oracle_blocks, blocks, legacy, owner, where):
        for b in oracle_blocks:
            if b["kind"] == "pb2":
                ours = blocks.get(b["ref"])
                controllers = {(c["id"], c["tab"]): c for c in b["controllers"]}
                block_index = self.scene.refs(owner).get(b["ref"])
                self.case.assertIsNotNone(ours, "%s: ParamBlock2 at slot %d" % (where, b["ref"]))
                self.case.assertEqual(ours.block_id, b["block_id"], where)
                self.case.assertEqual(ours.issues, (), where)  # also: as many entries as the header announces
                self.case.assertTrue(set(ours.ids()) <= {p["id"] for p in b["params"]}, where)
                skip = self.stale(owner, b)
                for p in b["params"]:
                    what = "%s block %d param %d %s" % (where, b["block_id"], p["id"], p["name"])
                    rp = ours.param(p["id"])
                    if rp is None:  # transient (mostly), a block that saves nothing (Standard's dynamics) or an
                        # empty table (Composite's unnamed parameters 0, 2 and 4); Corona names its obsolete
                        # parameters (P_OBSOLETE, never saved) "removedParam"
                        empty = p["type"] & pblock.TABLE and p["value"] == []
                        obsolete = p["name"] == "removedParam"
                        self.case.assertTrue(p["transient"] or len(ours) == 0 or empty or obsolete,
                                             what + ": not stored")
                        self.not_stored += 1
                        continue
                    if p["transient"]:  # an alias saved anyway (VRayBlendMtl coatMtl_0, blend_0): Max computes it
                        self.skipped += 1  # from the table, the saved value is stale and a reference slot empty
                        continue
                    self.case.assertEqual(rp.type, p["type"], what)
                    self.case.assertIsNone(rp.error, what)
                    base = p["type"] & ~pblock.TABLE
                    values = rp.values if rp.table else rp.values[:1]
                    theirs = p["value"] if rp.table else [p["value"]]
                    self.case.assertEqual(len(values), len(theirs), what)
                    for k, (a, t) in enumerate(zip(values, theirs)):
                        at = "%s[%d]" % (what, k) if rp.table else what
                        if skip(p["id"], k, a):
                            self.skipped += 1
                        elif (p["id"], k) in controllers:
                            self.controller(a, controllers[(p["id"], k)], block_index, at)
                        else:
                            self.value(base, a, t, at)
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
    def test_every_fixture_has_a_floor(self):
        names = {os.path.basename(p)[:-4] for p in FIXTURES}
        self.assertTrue(names)
        self.assertEqual(sorted(names - set(FLOORS)), [], "fixtures without a FLOORS entry")
        self.assertEqual(sorted(set(FLOORS) - names), [], "FLOORS entries without a fixture")

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
                parity = Parity(self, g, oracle, by_key, s)
                for e in oracle:
                    m = g.get(by_key[_key(e)])
                    where = "%s %s" % (name, e["name"])
                    self.assertEqual(m.superclass, e["superclass"], where)
                    self.assertEqual(m.is_material, e["superclass"] == classids.SC_MATERIAL, where)
                    self.assertEqual(m.issues, (), where)
                    parity.blocks(e["blocks"], m.blocks, m.legacy, m.index, where)
                    for part in e["parts"]:
                        ours = m.parts.get(part["ref"])
                        self.assertIsNotNone(ours, "%s: part at slot %d" % (where, part["ref"]))
                        self.assertEqual(tuple(ours.class_id), _cid(part["class_id"]), where)
                        parity.blocks(part["blocks"], ours.blocks, ours.legacy, ours.index,
                                      "%s part %d" % (where, part["ref"]))
                    self.assertEqual(len(m.parts), len(e["parts"]), where)
                    children = {(tuple(g.get(c).class_id), g.get(c).name) for c in m.children}
                    for sub in e["subs"]:
                        self.assertIn(_key(oracle[sub["target"]]), children, where)
                self.assertIn(name, FLOORS, "no FLOORS entry in tests/unit/test_materials.py")
                self.assertGreaterEqual(parity.compared, FLOORS[name], name)
                want = sum(len(b["controllers"]) for e in oracle for b in e["blocks"] + [
                    x for part in e["parts"] for x in part["blocks"]])
                self.assertEqual(parity.animated, want, name)
                del cf

    def test_owner_slots_match_the_fixtures(self):
        """Each owner_slots.py entry a fixture's 0x0013 lists says what that table says; every entry has one but the
        two measured on corpus scene B only."""
        tables = {}
        for path in FIXTURES:
            with cfb.CompoundFile(path) as cf:
                s = scene.Scene.from_file(cf)
                for i in range(len(s)):
                    entry = s.entry(i)
                    if entry is None or entry.superclass not in (classids.SC_MATERIAL, classids.SC_TEXMAP):
                        continue
                    for target in s.refs(i).values():
                        t = s.entry(target)
                        if t is None or t.superclass != classids.SC_PARAMETER_BLOCK2:
                            continue
                        chunk = s.chunk(target)
                        table = chunk.first(0x0013)
                        if table is None:
                            continue
                        buf = table.view()
                        found = {}
                        for k in range(struct.unpack_from("<I", buf)[0]):
                            pid, slot, _unknown = struct.unpack_from("<HHH", buf, 4 + 6 * k)
                            found.setdefault(pid, slot)
                        key = (entry.superclass, entry.class_id, pblock.ParamBlock2.from_chunk(chunk).block_id)
                        self.assertEqual(tables.setdefault(key, found), found, os.path.basename(path))
                del cf
        corpus_only = {classids.COMPOSITE, owner_slots.LAYERED_TEXMAP}
        for (superclass, class_id), blocks in owner_slots.TABLE.items():
            for block_id, want in blocks.items():
                with self.subTest(class_id=class_id, block=block_id):
                    found = tables.get((superclass, class_id, block_id))
                    if class_id in corpus_only:
                        self.assertIsNone(found)
                        continue
                    self.assertIsNotNone(found, "no fixture 0x0013 for this entry")
                    self.assertEqual({pid: found.get(pid) for pid in want}, want)

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

    def test_animated_by_id(self):
        """pblock_animated: a controller takes the next reference slot of its block in entry order, between the
        block's own references (docs/FORMAT.md, Parameter blocks)."""
        path = os.path.join(FIXTURE_DIR, "pblock_animated.max")
        with cfb.CompoundFile(path) as cf:
            s = scene.Scene.from_file(cf)
            g = materials.MaterialGraph(s)
            order = g.walk(s.node(i).material for i in s.walk())
            mats = {g.get(i).name: g.get(i) for i in order}
            name = lambda ref: g.get(ref.index).name if ref.index is not None else None  # noqa: E731

            def slot(m, block_id, ref):  # the block's reference slot that holds ref's target
                refs = s.refs(s.refs(m.index)[next(k for k, b in m.blocks.items() if b.block_id == block_id)])
                return next(k for k, v in refs.items() if v == ref.index)

            def controller(ref):  # class name and saved value of an Animated target
                return s.entry(ref.index).name, _saved_value(s.chunk(ref.index))

            blend = mats["FixtureAnimBlend"].block(0)
            self.assertEqual(name(blend.get(0)), "FixtureAnimBase")
            self.assertEqual([name(r) for r in blend.value(1)][:3], ["FixtureAnimCoatA", "FixtureAnimCoatB", None])
            colors = blend.value(2)  # blend: the second color animated, the first stored
            self.assertEqual([round(c * 255) for c in colors[0]], [40, 50, 60])
            self.assertIsInstance(colors[1], pblock.Animated)
            name_, value = controller(colors[1])
            self.assertEqual((name_, [round(c * 255) for c in value]), ("Bezier Color", [70, 80, 90]))
            self.assertEqual(slot(mats["FixtureAnimBlend"], 0, colors[1]), 10)  # after the coats (1-9)
            self.assertEqual(name(blend.get(3)), "FixtureAnimBlendMap")  # texmap_blend[0]: slot 11, not 10
            self.assertEqual(slot(mats["FixtureAnimBlend"], 0, blend.get(3)), 11)
            mult = blend.value(4)[0]
            self.assertEqual(controller(mult), ("Bezier Float", 37.0))
            self.assertEqual(slot(mats["FixtureAnimBlend"], 0, mult), 20)  # after the blend maps (11-19)

            vray = mats["FixtureAnimVRay"].block(1)
            self.assertEqual(controller(vray.get(1))[0], "Bezier Color")  # diffuse
            self.assertEqual([round(c * 255) for c in controller(vray.get(1))[1]], [10, 20, 30])
            self.assertEqual(controller(vray.get(3))[0], "Bezier Float")  # reflection_glossiness, animated first
            self.assertAlmostEqual(controller(vray.get(3))[1], 0.41, places=6)
            self.assertEqual((slot(mats["FixtureAnimVRay"], 1, vray.get(1)), slot(mats["FixtureAnimVRay"], 1,
                                                                                 vray.get(3))), (0, 1))

            normal = mats["FixtureAnimNormal"]
            nb = normal.block(0)
            self.assertEqual((name(nb.get(0)), name(nb.get(4))), ("FixtureAnimNormalMap", "FixtureAnimBumpMap"))
            self.assertAlmostEqual(controller(nb.get(3))[1], 0.55, places=6)  # normal_map_multiplier
            self.assertAlmostEqual(controller(nb.get(6))[1], 0.35, places=6)  # bump_map_multiplier
            self.assertEqual([slot(normal, 0, nb.get(pid)) for pid in (0, 3, 4, 6)], [0, 1, 2, 3])

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


def u32(cid, v):
    return leaf(cid, struct.pack("<I", v))


class _Block:
    def __init__(self, block_id):
        self.block_id = block_id


class _Map:
    """What bitmap_gamma reads of a MtlBase: its blocks by slot and its references."""

    def __init__(self, blocks, refs_):
        self.blocks, self.refs = blocks, refs_


def info(gamma, flags, size=70):
    """A BitmapInfo payload: the gamma tail (f32 gamma, u32 flags, 6 bytes) at its end."""
    return bytes(size - 14) + struct.pack("<fI", gamma, flags) + bytes(6)


class MapParts(unittest.TestCase):
    """The Placement, Output and BitmapInfo chunks read into values (docs/FORMAT.md)."""

    def test_placement_defaults_without_chunks(self):
        s = make_scene(container(OTHER), leaf(OTHER))
        default = materials.Placement((True, True), (False, False), False, None, False, None, None)
        self.assertEqual(materials.placement(s, 0), default)
        self.assertEqual(materials.placement(s, 1), default)  # a leaf object
        self.assertEqual(materials.placement(s, 9), default)  # outside the objects

    def test_placement_chunks(self):
        s = make_scene(container(OTHER, u32(0x9002, 0x48000008), u32(0x9003, 2), u32(0x9005, 1), u32(0x9006, 3),
                                 u32(0x900B, 4)))
        p = materials.placement(s, 0)
        self.assertEqual((p.tile, p.mirror, p.real_world), ((False, False), (False, True), True))
        self.assertEqual((p.axis, p.environment, p.source, p.channel), (2, True, 3, 4))

    def test_short_placement_chunk_is_skipped(self):
        s = make_scene(container(OTHER, leaf(0x9002, b"\x01\x00"), u32(0x900B, 1000)))
        p = materials.placement(s, 0)
        self.assertEqual((p.tile, p.channel), ((True, True), 1000))  # out of range values are convert's to judge

    def test_output_invert(self):
        s = make_scene(container(OTHER, u32(0x0002, 2)), container(OTHER, u32(0x0002, 1)), container(OTHER))
        self.assertEqual([materials.output_invert(s, i) for i in (0, 1, 2, 7)], [True, False, False, False])

    def test_bitmap_gamma(self):
        def gamma(payload, blocks=None):
            s = make_scene(container(OTHER, container(0x0003, leaf(0x1201, payload))))
            return materials.bitmap_gamma(s, _Map({0: _Block(0)} if blocks is None else blocks, {0: 0}))
        self.assertAlmostEqual(gamma(info(1.8, 5)), 1.8, places=6)
        self.assertIsNone(gamma(info(1.0, 20)))  # automatic
        self.assertIsNone(gamma(b"\x05" * 10))  # shorter than the tail
        self.assertIsNone(gamma(info(1.8, 5), {0: _Block(1)}))  # no block 0
        self.assertTrue(math.isnan(gamma(info(float("nan"), 5))))  # as stored: convert judges it

    def test_bitmap_gamma_unreadable(self):
        s = make_scene(container(OTHER, container(0x0003)))
        self.assertIsNone(materials.bitmap_gamma(s, _Map({0: _Block(0)}, {0: 0})))
        self.assertIsNone(materials.bitmap_gamma(s, _Map({0: _Block(0)}, {0: 9})))

    def test_no_chunk_ids_in_convert(self):
        ids = ("0x9002", "0x9003", "0x9005", "0x9006", "0x900b", "0x1201")
        for path in glob.glob(os.path.join(ROOT, "maxdrop", "convert", "*.py")):
            with open(path, encoding="utf-8") as f:
                text = f.read().lower()
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual([i for i in ids if i in text], [])


if __name__ == "__main__":
    unittest.main()
