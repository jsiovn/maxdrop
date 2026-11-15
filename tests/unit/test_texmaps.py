# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/texmaps.py, the texture-map rules: no Blender. vray_maps' slots against the values its
authoring script sets (tools/fixtures/vray_maps.ms), texmap_rules' peels, kept wrappers, normal maps and Bitmap
placement against tools/fixtures/texmap_rules.ms, the ClassIDs against that fixture's class directory, the wiring
into materials.py, and the guards on synthetic maps.

    python -I -m unittest discover tests
"""
import collections
import importlib
import math
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
TOLERANCE = 1e-5

_PKG = "maxdrop_convert_test"  # the package test_convert_materials.py makes: maxdrop/__init__.py never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
tx = importlib.import_module(_PKG + ".convert.texmaps")
mat = importlib.import_module(_PKG + ".convert.materials")
assets = importlib.import_module(_PKG + ".reader.assets")
cfb = importlib.import_module(_PKG + ".reader.cfb")
chunks = importlib.import_module(_PKG + ".reader.chunks")
classids = importlib.import_module(_PKG + ".reader.classids")
pblock = importlib.import_module(_PKG + ".reader.pblock")
reader_materials = importlib.import_module(_PKG + ".reader.materials")
reader_scene = importlib.import_module(_PKG + ".reader.scene")

Ref = pblock.Reference
DEG = math.pi / 180.0


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


class Fixture:
    """A fixture's converters, its materials by name and its nodes' IRs."""

    def __init__(self, name):
        self.cf = cfb.CompoundFile(os.path.join(FIXTURE_DIR, name + ".max"))
        self.scene = reader_scene.Scene.from_file(self.cf)
        self.graph = reader_materials.MaterialGraph(self.scene)
        self.tex = tx.TexmapConverter(self.graph, assets.AssetTable.from_file(self.cf))
        self.conv = mat.MaterialConverter(self.graph, texmaps=self.tex)
        self.irs = {}
        for n in self.scene.walk():
            ir = self.conv.convert(self.scene.node(n).material)
            if ir is not None:
                self.irs[ir.name] = ir

    def close(self):
        self.cf.close()


class Checks(unittest.TestCase):
    def close(self, ours, theirs, what=""):
        if isinstance(theirs, tuple):
            self.assertEqual(len(ours), len(theirs), what)
            for a, b in zip(ours, theirs):
                self.assertAlmostEqual(a, b, delta=TOLERANCE, msg=what)
        else:
            self.assertAlmostEqual(ours, theirs, delta=TOLERANCE, msg=what)

    def image(self, node, name, colorspace, tiling=(1.0, 1.0), offset=(0.0, 0.0), w_angle=0.0, channel=1):
        self.assertIsInstance(node, tx.Image, name)
        self.assertEqual(node.name, name)
        self.assertEqual(node.colorspace, colorspace, name)
        self.close(node.mapping.tiling, tiling, name)
        self.close(node.mapping.offset, offset, name)
        self.close(node.mapping.angle[2], w_angle * DEG, name)
        self.assertEqual(node.mapping.channel, channel, name)


class VRayMaps(Checks):
    """vray_maps.ms: FixtureVRayMaps' five bitmaps (tile, tile + 0.5, offset, offset + 0.05, angle) and multipliers
    91 / 82 / 73 / 64 / 55 %; FixtureVRayNormal's VRayNormalMap."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("vray_maps")

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def test_diffuse(self):
        ir = self.f.irs["FixtureVRayMaps"]
        g = ir.textures["base_color"]
        self.assertEqual(g.kind, tx.COLOR)
        self.assertFalse(g.approximated)
        self.assertIsInstance(g.root, tx.Mix)
        self.close(g.root.factor, 0.91)
        self.close(g.root.a.value, tuple(_lin(c) for c in (180, 120, 60)))
        self.image(g.root.b, "fixture_diffuse.png", tx.SRGB, (2.0, 2.5), (0.1, 0.15), 15.0)
        self.close(g.root.b.mapping.blur, 1.1)
        self.assertIsNone(g.root.b.crop)
        self.assertIsNone(g.root.b.gamma)

    def test_reflection_is_the_specular(self):
        g = self.f.irs["FixtureVRayMaps"].textures["specular"]
        self.close(g.root.factor, 0.82)
        self.image(g.root.b, "fixture_reflect.png", tx.SRGB, (3.0, 3.5), (0.2, 0.25), 25.0)

    def test_glossiness_is_inverted(self):
        g = self.f.irs["FixtureVRayMaps"].textures["roughness"]
        self.assertEqual(g.kind, tx.DATA)
        self.close(g.root.factor, 0.73)
        self.close(g.root.a.value, 0.0)  # glossiness 1.0
        self.assertIsInstance(g.root.b, tx.Invert)
        self.image(g.root.b.input, "fixture_gloss.png", tx.NON_COLOR, (4.0, 4.5), (0.3, 0.35), 35.0)

    def test_bump(self):
        g = self.f.irs["FixtureVRayMaps"].textures["bump"]
        self.assertIsInstance(g.root, tx.Bump)
        self.close(g.root.strength, 0.64)
        self.image(g.root.input, "fixture_bump.png", tx.NON_COLOR, (5.0, 5.5), (0.4, 0.45), 45.0)

    def test_opacity(self):
        g = self.f.irs["FixtureVRayMaps"].textures["alpha"]
        self.close(g.root.factor, 0.55)
        self.close(g.root.a.value, 1.0)
        self.image(g.root.b, "fixture_opacity.png", tx.NON_COLOR, (6.0, 6.5), (0.5, 0.55), 55.0)

    def test_only_the_slots_with_maps(self):
        self.assertEqual(sorted(self.f.irs["FixtureVRayMaps"].textures),
                         ["alpha", "base_color", "bump", "roughness", "specular"])

    def test_vray_normal_map(self):
        ir = self.f.irs["FixtureVRayNormal"]
        self.assertEqual(sorted(ir.textures), ["normal"])
        n = ir.textures["normal"].root
        self.assertIsInstance(n, tx.NormalMap)
        self.close(n.strength, 0.85)  # material bump 100 % x normal_map_multiplier 0.85
        self.assertTrue(n.flip_green)
        self.assertFalse(n.flip_red)
        self.image(n.input, "fixture_normal.png", tx.NON_COLOR, (1.5, 2.0), (0.05, 0.1), 5.0)
        self.close(n.bump.strength, 0.35)
        self.image(n.bump.input, "fixture_normal_bump.png", tx.NON_COLOR, (2.5, 3.0), (0.15, 0.2), 65.0)

    def test_nothing_peeled_or_reported(self):
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter())
        self.assertEqual(self.f.tex.stats.unsupported, collections.Counter())
        self.assertEqual(self.f.tex.stats.issues, [])


class TexmapRules(Checks):
    """texmap_rules.ms."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("texmap_rules")

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def test_class_ids_match_the_class_directory(self):
        names = {(e.superclass, e.class_id): e.name for e in (self.f.scene.entry(i) for i in range(len(self.f.scene)))
                 if e is not None}
        expected = {tx.FALLOFF: "Falloff", tx.VRAY_DIRT: "VRayDirt", tx.VRAY_COLOR2BUMP: "VRayColor2Bump",
                    tx.OUTPUT: "Output", tx.RGB_TINT: "RGB Tint", tx.MIX: "Mix", tx.RGB_MULTIPLY: "RGB Multiply",
                    tx.COLOR_CORRECTION: "Color Correction", tx.COMPOSITE: "Composite",
                    tx.NORMAL_BUMP: "Normal Bump", tx.CORONA_NORMAL: "CoronaNormal"}
        for cid, name in expected.items():
            self.assertEqual(names.get((classids.SC_TEXMAP, cid)), name, name)

    def test_peeled_to_the_bitmap_below(self):
        t = self.f.irs["FixtureTexPeel"].textures
        self.image(t["base_color"].root, "peel_diffuse.png", tx.SRGB)  # Falloff
        self.image(t["specular"].root.b, "peel_reflect.png", tx.SRGB)  # VRayDirt, at 80 %
        self.close(t["specular"].root.factor, 0.8)
        self.assertIsInstance(t["roughness"].root, tx.Invert)  # Output, a glossiness map
        self.image(t["roughness"].root.input, "peel_gloss.png", tx.NON_COLOR)
        self.assertIsInstance(t["bump"].root, tx.Bump)  # VRayColor2Bump: a height map
        self.close(t["bump"].root.strength, 0.4)
        self.image(t["bump"].root.input, "peel_height.png", tx.NON_COLOR)
        self.image(t["alpha"].root, "peel_opacity.png", tx.NON_COLOR)  # RGB Tint
        for name in ("base_color", "specular", "roughness", "bump", "alpha", "metallic", "emission_color"):
            self.assertTrue(t[name].approximated, name)

    def test_peels_are_counted_once_per_map(self):
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter(
            {"Falloff": 3, "VRayDirt": 1, "Output": 1, "VRayColor2Bump": 1, "RGB Tint": 1}))
        self.assertEqual(self.f.tex.stats.unsupported, collections.Counter())

    def test_falloff_without_a_map_is_its_color(self):
        t = self.f.irs["FixtureTexPeel"].textures
        self.close(t["metallic"].root.value, sum(_lin(c) for c in (200, 100, 50)) / 3.0)  # a data input: the mean
        self.close(t["emission_color"].root.value, (1.0, 0.0, 0.0))  # map1 switched off: color1

    def test_kept_wrappers(self):
        t = self.f.irs["FixtureTexKeep"].textures
        mix = t["base_color"].root
        self.assertIsInstance(mix, tx.Mix)
        self.close(mix.factor, 0.3)
        self.image(mix.a, "keep_mix_a.png", tx.SRGB)
        self.image(mix.b, "keep_mix_b.png", tx.SRGB)
        self.image(mix.mask, "keep_mix_mask.png", tx.NON_COLOR)
        mul = t["specular"].root
        self.assertIsInstance(mul, tx.Multiply)
        self.image(mul.a, "keep_mul.png", tx.SRGB)
        self.close(mul.b.value, tuple(_lin(c) for c in (200, 150, 100)))
        cc = t["emission_color"].root
        self.assertIsInstance(cc, tx.ColorCorrect)
        self.close(cc.hue, 30.0 / 360.0)
        self.close(cc.saturation, 1.2)
        self.close(cc.brightness, 0.1)
        self.close(cc.contrast, 0.05)
        self.close(cc.gain, 1.0)
        self.close(cc.gamma, 1.2)
        self.image(cc.input, "keep_cc.png", tx.SRGB)
        for name in ("base_color", "specular", "emission_color"):
            self.assertFalse(t[name].approximated, name)

    def test_gamma_override_on_a_data_input(self):
        g = self.f.irs["FixtureTexKeep"].textures["roughness"].root
        self.assertIsInstance(g, tx.Invert)
        self.image(g.input, "keep_gloss.png", tx.NON_COLOR)
        self.close(g.input.gamma, 1.0)

    def test_normal_bump_is_the_normal_input(self):
        ir = self.f.irs["FixtureTexKeep"]
        self.assertIsNotNone(ir.normal)
        self.assertIsNone(ir.bump)
        n = ir.textures["normal"].root
        self.assertIsInstance(n, tx.NormalMap)
        self.close(n.strength, 0.8 * 0.3)  # mult_spin x the material's default bump amount, 30 %
        self.assertTrue(n.flip_green)
        self.image(n.input, "keep_normal.png", tx.NON_COLOR)
        self.close(n.bump.strength, 0.4 * 0.3)
        self.image(n.bump.input, "keep_nb_bump.png", tx.NON_COLOR)

    def test_composite(self):
        c = self.f.irs["FixtureTexPlace"].textures["base_color"].root
        self.assertIsInstance(c, tx.Composite)
        self.assertEqual([n.name for n, _o in c.layers], ["place_comp_a.png", "place_comp_b.png"])
        self.close(tuple(o for _n, o in c.layers), (1.0, 0.6))

    def test_crop_channel_mirror_angles_gamma(self):
        i = self.f.irs["FixtureTexPlace"].textures["specular"].root
        self.image(i, "place_crop.png", tx.SRGB, (2.0, 3.0), (0.0, 0.0), 30.0, channel=3)
        self.close(i.mapping.angle, (10.0 * DEG, 20.0 * DEG, 30.0 * DEG))
        self.assertEqual(i.mapping.tile, (False, False))  # U mirrors (not tiles), V tiling off
        self.assertEqual(i.mapping.mirror, (True, False))
        self.assertEqual(i.mapping.source, tx.EXPLICIT)
        self.close((i.crop.u, i.crop.v, i.crop.w, i.crop.h), (0.1, 0.2, 0.5, 0.6))
        self.assertFalse(i.crop.place)
        self.close(i.gamma, 2.2)

    def test_placement_on_the_vertex_color_channel(self):
        i = self.f.irs["FixtureTexPlace"].textures["alpha"].root
        self.assertTrue(i.crop.place)
        self.close((i.crop.u, i.crop.v, i.crop.w, i.crop.h), (0.25, 0.25, 0.5, 0.5))
        self.assertEqual(i.mapping.source, tx.VERTEX_COLOR)
        self.assertEqual(i.mapping.channel, 0)

    def test_environment_mapping_is_an_issue(self):
        g = self.f.irs["FixtureTexPlace"].textures["emission_color"]
        self.assertTrue(g.root.mapping.environment)
        self.assertEqual(len(g.issues), 1)
        self.assertIn("environment mapping", g.issues[0])
        self.assertIn(g.issues[0], self.f.irs["FixtureTexPlace"].issues)

    def test_inverted_output(self):
        i = self.f.irs["FixtureTexPlace"].textures["metallic"].root
        self.assertEqual(i.output, tx.TexOutput(invert=True))

    def test_corona_normal(self):
        ir = self.f.irs["FixtureTexPlace"]
        self.assertIsNone(ir.bump)
        n = ir.textures["normal"].root
        self.close(n.strength, 0.9 * 0.3)
        self.assertTrue(n.flip_green)
        self.image(n.input, "place_cnormal.png", tx.NON_COLOR)
        self.close(n.bump.strength, 0.5 * 0.3)
        self.image(n.bump.input, "place_cbump.png", tx.NON_COLOR)

    def test_without_a_texmap_converter(self):
        conv = mat.MaterialConverter(self.f.graph)
        for n in self.f.scene.walk():
            ir = conv.convert(self.f.scene.node(n).material)
            self.assertEqual(ir.textures, {})


# Synthetic maps: a MaterialGraph stand-in whose scene has no chunks (every Placement and Output takes its defaults).

G1 = bytes(range(16))


class FakeEntry(collections.namedtuple("FakeEntry", "name")):
    pass


class FakeScene:
    def __init__(self, objects):
        self.objects = objects

    def entry(self, i):
        o = self.objects.get(i)
        return FakeEntry(o.cls) if o is not None else None

    def chunk(self, i):
        raise chunks.ChunkError("no chunks here")


class FakeBlock:
    def __init__(self, block_id, params):
        self.block_id, self._params = block_id, params

    def __contains__(self, pid):
        return pid in self._params

    def value(self, pid, default=None):
        v = self._params.get(pid, default)
        return list(v) if isinstance(v, list) else v

    def get(self, pid, tab=0, default=None):
        v = self._params.get(pid, default)
        return (v[tab] if 0 <= tab < len(v) else default) if isinstance(v, list) else v


class FakeMap:
    def __init__(self, index, class_id, params=None, children=(), cls="", superclass=classids.SC_TEXMAP,
                 name="map"):
        self.index, self.class_id, self.superclass, self.name, self.cls = index, class_id, superclass, name, cls
        self.blocks = {0: FakeBlock(0, params or {})}
        self.refs, self.parts, self.children = {}, {}, list(children)

    def block(self, block_id):
        return self.blocks.get(0) if block_id == 0 else None

    def param(self, pid, block_id=None, tab=0, default=None):
        b = self.blocks[0]
        return b.get(pid, tab, default) if pid in b else default


class FakeGraph:
    def __init__(self, *objects):
        self.objects = {o.index: o for o in objects}
        self.scene = FakeScene(self.objects)

    def get(self, i):
        if i not in self.objects:
            raise chunks.ChunkError("object %d is not a material or map" % i)
        return self.objects[i]

    def superclass(self, i):
        o = self.objects.get(i)
        return None if o is None else o.superclass


def _bitmap(index, guid=G1):
    return FakeMap(index, classids.BITMAP_TEX, {13: pblock.Asset(guid)}, cls="Bitmap")


def _falloff(index, map1=None, color1=(0.5, 0.5, 0.5)):
    return FakeMap(index, tx.FALLOFF, {0: color1, 2: Ref(map1), 3: 1}, [map1] if map1 is not None else [],
                   cls="Falloff")


def _table():
    return assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\a.png", "")])


def _tex(*objects, table=None):
    return tx.TexmapConverter(FakeGraph(*objects), _table() if table is None else table)


class Synthetic(Checks):
    def test_colorspace(self):
        self.assertEqual(tx.colorspace(tx.COLOR, None), tx.SRGB)
        self.assertEqual(tx.colorspace(tx.COLOR, 2.2), tx.SRGB)
        self.assertEqual(tx.colorspace(tx.COLOR, 1.0), tx.NON_COLOR)  # linear: the builder applies no gamma
        self.assertEqual(tx.colorspace(tx.COLOR, 1.8), tx.NON_COLOR)  # the builder applies 1.8
        for kind in (tx.DATA, tx.NORMAL, tx.BUMP):
            self.assertEqual(tx.colorspace(kind, None), tx.NON_COLOR)
            self.assertEqual(tx.colorspace(kind, 2.2), tx.NON_COLOR)

    def test_bitmap_without_chunks_takes_the_defaults(self):
        g = _tex(_bitmap(1)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertEqual(g.root.path, "maps\\a.png")
        self.assertEqual(g.root.mapping, tx.Mapping())
        self.assertIsNone(g.root.output)
        self.assertIsNone(g.root.gamma)

    def test_bitmap_without_a_file(self):
        tex = _tex(_bitmap(1, guid=b"\xff" * 16))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertIn("no file", tex.stats.issues[0][1])
        tex = tx.TexmapConverter(FakeGraph(_bitmap(1)))  # no asset table at all
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))

    def test_texture_lookup(self):
        class Index:
            def find(self, path, resolved=""):
                return ("found", path, resolved)
        tex = tx.TexmapConverter(FakeGraph(_bitmap(1)), _table(), textures=Index())
        self.assertEqual(tex.convert(mat.MapRef(1), tx.COLOR).root.found, ("found", "maps\\a.png", ""))

    def test_cycle(self):
        tex = _tex(_falloff(1, 2), _falloff(2, 1, color1=(1.0, 1.0, 1.0)))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))  # 2's map1 is 1 again: the branch ends there
        self.assertTrue(any("cycle" in r for _i, r in tex.stats.issues))

    def test_depth_guard(self):
        objects = [_falloff(i, i + 1) for i in range(1, tx.MAX_DEPTH + 3)] + [_bitmap(tx.MAX_DEPTH + 3)]
        tex = _tex(*objects)
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertTrue(any("deeper than" in r for _i, r in tex.stats.issues))

    def test_reference_to_a_material(self):
        tex = _tex(_falloff(1, 2), FakeMap(2, classids.VRAY_MTL, superclass=classids.SC_MATERIAL))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertTrue(any("not a map" in r for _i, r in tex.stats.issues))

    def test_unknown_class_gives_the_first_bitmap_below(self):
        tex = _tex(FakeMap(1, (0x1234, 0), children=[2, 3], cls="Noise"), _falloff(2), _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertTrue(g.approximated)
        self.assertEqual(tex.stats.peeled, collections.Counter({"Noise": 1}))

    def test_unknown_class_without_a_bitmap(self):
        tex = _tex(FakeMap(1, (0x1234, 0), cls="Noise"))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertEqual(tex.stats.unsupported, collections.Counter({"Noise": 1}))

    def test_composite_with_a_mask_is_peeled(self):
        comp = FakeMap(1, tx.COMPOSITE, {1: [1, 1], 3: [1, 1], 5: [0, 0], 8: [100.0, 50.0], 9: [Ref(2), Ref(3)],
                                         10: [Ref(None), Ref(3)]}, [2, 3], cls="Composite")
        tex = _tex(comp, _bitmap(2), _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Image)
        self.assertTrue(g.approximated)
        self.assertEqual(tex.stats.peeled, collections.Counter({"Composite": 1}))

    def test_slot_amounts(self):
        tex = _tex(_bitmap(1))
        g = tex.convert(mat.MapRef(1, 1.5), tx.DATA, 0.2)
        self.assertEqual(g.root, tx.Multiply(g.root.a, tx.Constant(1.5)))
        g = tex.convert(mat.MapRef(1, 0.25, invert=True), tx.DATA, 0.7)
        self.assertIsInstance(g.root, tx.Mix)
        self.assertEqual(g.root.a, tx.Constant(0.7))
        self.assertIsInstance(g.root.b, tx.Invert)
        self.close(g.root.factor, 0.25)
        g = tex.convert(mat.MapRef(1, 0.25), tx.BUMP)
        self.assertEqual(g.root.strength, 0.25)

    def test_normal_map_in_a_color_input_is_its_image(self):
        n = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(2), 2: 1, 3: 1.0}, [2], cls="VRayNormalMap")
        tex = _tex(n, _bitmap(2))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Image)
        self.assertEqual(g.root.colorspace, tx.NON_COLOR)  # read as a normal image below its class
        self.assertTrue(g.approximated)

    def test_normal_map_with_only_a_bump_map(self):
        n = FakeMap(1, tx.NORMAL_BUMP, {3: Ref(2), 5: 1, 1: 0.5}, [2], cls="Normal Bump")
        g = _tex(n, _bitmap(2)).convert(mat.MapRef(1, 0.5), tx.NORMAL)
        self.assertIsInstance(g.root, tx.Bump)
        self.close(g.root.strength, 0.25)

    def test_switched_off_normal_map(self):
        n = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(2), 2: 0}, [2], cls="VRayNormalMap")
        self.assertIsNone(_tex(n, _bitmap(2)).convert(mat.MapRef(1), tx.NORMAL))

    def test_same_wrapper_in_two_slots_counts_once(self):
        tex = _tex(_falloff(1, 2), _bitmap(2))
        tex.convert(mat.MapRef(1), tx.COLOR)
        tex.convert(mat.MapRef(1, 0.5), tx.DATA, 0.0)
        self.assertEqual(tex.stats.peeled, collections.Counter({"Falloff": 1}))

    def test_texture_graphs_of_an_ir(self):
        tex = _tex(_bitmap(1))
        ir = mat.MaterialIR(0, "M", base_color=mat.Input((0.1, 0.2, 0.3), mat.MapRef(1)), bump=mat.MapRef(1, 0.3))
        graphs = tx.texture_graphs(ir, tex)
        self.assertEqual(sorted(graphs), ["base_color", "bump"])
        self.assertEqual(graphs["base_color"].root.colorspace, tx.SRGB)
        self.assertEqual(graphs["bump"].root.input.colorspace, tx.NON_COLOR)


if __name__ == "__main__":
    unittest.main()
