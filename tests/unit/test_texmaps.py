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
import struct
import sys
import time
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
colors = importlib.import_module(_PKG + ".convert.colors")
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
    """A swatch 0..255 of a fixture (saved with the gamma off) as linear: the sRGB curve."""
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
        self.close(g.root.a.value, (0.0, 0.0, 0.0))  # the float input's value, as RGB in a color graph
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
        self.close(cc.brightness, 0.0)  # brightness 10 and contrast 5 are set, but lightness is advanced
        self.close(cc.contrast, 0.0)
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
    def __init__(self, objects, chunk_map=None):
        self.objects, self.chunks = objects, chunk_map or {}

    def entry(self, i):
        o = self.objects.get(i)
        return FakeEntry(o.cls) if o is not None else None

    def chunk(self, i):
        if i not in self.chunks:
            raise chunks.ChunkError("no chunks here")
        return self.chunks[i]


class FakeChunk:
    """A chunk: a leaf with a payload, or a container with children."""

    def __init__(self, cid, payload=None, children=None):
        self.id, self.container = cid, children is not None
        self.children, self._payload = list(children or ()), payload or b""
        self.payload_size = len(self._payload)

    def tobytes(self):
        return self._payload

    def unpack(self, fmt):
        return struct.unpack_from(fmt, self._payload)

    def first(self, cid):
        return next((c for c in self.children if c.id == cid), None)


class FakeOld:
    """An old ParamBlock: values by index."""

    def __init__(self, values):
        self._values = values

    def get(self, i, default=None):
        return self._values.get(i, default)


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
    def __init__(self, *objects, chunk_map=None):
        self.objects = {o.index: o for o in objects}
        self.scene = FakeScene(self.objects, chunk_map)

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

    def test_float_files_under_automatic_gamma_are_linear(self):
        for path in ("maps\\sky.EXR", "maps\\sky.hdr"):
            table = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", path, "")])
            g = _tex(_bitmap(1), table=table).convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual((g.root.gamma, g.root.colorspace), (1.0, tx.NON_COLOR), path)
        table = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.exr", "")])
        for info, gamma, space in ((_info(2.2, 5), 2.2, tx.SRGB), (_info(1.8, 5), 1.8, tx.NON_COLOR),
                                   (_info(2.2, 4), 1.0, tx.NON_COLOR),  # an override is kept; no flag: automatic
                                   (_info(50.0, 5), 1.0, tx.NON_COLOR)):  # out of range: automatic
            b, chunk_map = _placed(info=info)
            g = tx.TexmapConverter(FakeGraph(b, chunk_map=chunk_map), table).convert(mat.MapRef(1), tx.COLOR)
            self.close(g.root.gamma, gamma)
            self.assertEqual(g.root.colorspace, space, info.hex())
        g = _tex(_bitmap(1), table=table).convert(mat.MapRef(1), tx.DATA)
        self.assertEqual(g.root.colorspace, tx.NON_COLOR)
        g = _tex(_bitmap(1)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual((g.root.gamma, g.root.colorspace), (None, tx.SRGB), "an 8-bit file: still automatic")

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

    def test_first_image_issues_reach_every_graph_that_peels_to_it(self):
        shared = FakeMap(5, (0x1234, 0), children=[6, 7], cls="Noise")  # its first bitmap has no file
        tex = _tex(FakeMap(10, (0x1235, 0), children=[5], cls="Cellular"),
                   FakeMap(20, (0x1236, 0), children=[5], cls="Smoke"), shared, _bitmap(6, guid=b"\xff" * 16),
                   _bitmap(7))
        for i in (10, 20):
            g = tex.convert(mat.MapRef(i), tx.COLOR)
            self.assertEqual(g.root.name, "a.png")
            self.assertTrue(any("no file" in r for r in g.issues), i)

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


UVGEN_OBJECT, INFO_BLOCK = 50, 60


def _placed(index=1, uv=None, old=None, info=None):
    """A Bitmap with a Placement part (its chunk uv, its old ParamBlock old) and BitmapInfo bytes info; and the
    chunk map of its scene."""
    b = _bitmap(index)
    b.parts = {0: reader_materials.Part(UVGEN_OBJECT, classids.STD_UVGEN, classids.SC_UVGEN, {},
                                        {0: FakeOld(old or {})})}
    chunk_map = {UVGEN_OBJECT: uv} if uv is not None else {}
    if info is not None:
        b.refs = {0: INFO_BLOCK}
        chunk_map[INFO_BLOCK] = FakeChunk(0x82, children=[FakeChunk(0x0003, children=[FakeChunk(0x1201, info)])])
    return b, chunk_map


def _info(gamma, flags):
    return bytes(56) + struct.pack("<fI", gamma, flags) + bytes(6)  # 70 bytes, the gamma tail 14 from the end


def _image(b, chunk_map, kind=tx.COLOR):
    tex = tx.TexmapConverter(FakeGraph(b, chunk_map=chunk_map), _table())
    return tex, tex.convert(mat.MapRef(b.index), kind)


class CoronaMaps(Checks):
    """corona_maps.ms and corona_light.ms."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("corona_maps")

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def test_class_ids_match_the_class_directory(self):
        names = {(e.superclass, e.class_id): e.name for e in (self.f.scene.entry(i) for i in range(len(self.f.scene)))
                 if e is not None}
        for cid, name in ((classids.CORONA_BITMAP, "CoronaBitmap"), (classids.CORONA_NORMAL, "CoronaNormal"),
                          (classids.CORONA_COLOR, "CoronaColor"), (classids.CORONA_MIX, "CoronaMix")):
            self.assertEqual(names.get((classids.SC_TEXMAP, cid)), name, name)

    def test_base_bitmap_placement(self):
        g = self.f.irs["FixtureCoronaMaps"].textures["base_color"]
        self.assertIsInstance(g.root, tx.Mix)
        self.close(g.root.factor, 0.75)
        self.close(g.root.a.value, tuple(_lin(c) for c in (150, 140, 130)))
        image = g.root.b
        self.image(image, "fixture_c_base.png", tx.SRGB, tiling=(2.0, 3.0), offset=(0.1, 0.2), w_angle=30.0,
                   channel=2)
        self.assertEqual((image.mapping.tile, image.mapping.mirror), ((True, False), (True, False)))
        self.close(image.mapping.blur, 0.8)
        self.assertEqual((image.gamma, image.crop, image.output, image.alpha), (None, None, None, False))
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def test_glossiness_bitmap_with_gamma_1(self):
        g = self.f.irs["FixtureCoronaMaps"].textures["roughness"]
        self.close(g.root.factor, 0.6)
        self.close(g.root.a.value, 0.4)
        self.assertIsInstance(g.root.b, tx.Invert)
        self.image(g.root.b.input, "fixture_c_gloss.png", tx.NON_COLOR)
        self.close(g.root.b.input.gamma, 1.0)

    def test_placed_opacity_gives_its_alpha(self):
        image = self.f.irs["FixtureCoronaMaps"].textures["alpha"].root
        self.image(image, "fixture_c_opacity.png", tx.NON_COLOR)
        self.close((image.crop.u, image.crop.v, image.crop.w, image.crop.h), (0.1, 0.2, 0.5, 0.6))
        self.assertTrue(image.crop.place)
        self.assertTrue(image.alpha)

    def test_corona_normal_in_bump(self):
        n = self.f.irs["FixtureCoronaMaps"].textures["normal"].root
        self.assertIsInstance(n, tx.NormalMap)
        self.close(n.strength, 0.8 * 0.9)
        self.assertTrue(n.flip_green)
        self.image(n.input, "fixture_c_normal.png", tx.NON_COLOR)
        self.close(n.bump.strength, 0.3 * 0.9)
        self.image(n.bump.input, "fixture_c_normal_bump.png", tx.NON_COLOR)

    def test_corona_color_is_a_constant(self):
        root = self.f.irs["FixtureCoronaMaps"].textures["metallic"].root
        self.close(root.value, sum(_lin(c) for c in (100, 150, 200)) / 3, "a data input: the mean")

    def test_corona_mix_with_a_mask(self):
        root = self.f.irs["FixtureCoronaMaps"].textures["emission_color"].root
        self.assertIsInstance(root, tx.Mix)
        self.close(root.factor, 0.4)
        self.close(root.a.value, tuple(_lin(c) for c in (10, 20, 30)), "the bottom color")
        self.image(root.b, "fixture_c_top.png", tx.SRGB)
        self.image(root.mask, "fixture_c_mask.png", tx.NON_COLOR)

    def test_legacy_slots(self):
        t = self.f.irs["FixtureCoronaLegacyMaps"].textures
        self.assertIsInstance(t["base_color"].root, tx.Multiply)
        self.image(t["base_color"].root.a, "fixture_c_mul_bottom.png", tx.SRGB)
        self.image(t["base_color"].root.b, "fixture_c_mul_top.png", tx.SRGB)
        self.assertIsInstance(t["roughness"].root, tx.Invert)
        self.image(t["roughness"].root.input, "fixture_c_legacy_gloss.png", tx.NON_COLOR)
        self.assertIsInstance(t["bump"].root, tx.Bump)
        self.close(t["bump"].root.strength, 0.5)
        self.close(t["alpha"].root.value, 0.5, "HDR color 0.25 0.5 0.75, linear: the mean")
        self.assertNotIn("emission_color", t)

    def test_add_is_peeled_to_its_bitmap(self):
        g = self.f.irs["FixtureCoronaLegacyMaps"].textures["specular"]
        self.image(g.root, "fixture_c_add_top.png", tx.SRGB)
        self.assertTrue(g.approximated)
        self.assertEqual(len(g.issues), 1)
        self.assertIn("operation 0", g.issues[0])
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter({"CoronaMix": 1}))
        self.assertEqual(self.f.tex.stats.unsupported, collections.Counter())
        self.assertEqual(len(self.f.tex.stats.issues), 1)

    def test_light_maps(self):
        f = Fixture("corona_light")
        try:
            t = f.irs["FixtureCoronaLight"].textures
            self.image(t["emission_color"].root, "fixture_c_light.png", tx.SRGB)
            self.image(t["alpha"].root, "fixture_c_light_alpha.png", tx.NON_COLOR)
            self.assertEqual(f.irs["FixtureCoronaLightPlain"].textures, {})
        finally:
            f.close()


G2 = bytes(range(16, 32))


def _cbitmap(index, guid=G1, **params):
    p = {101: pblock.Asset(guid)}
    p.update({int(k[1:]): v for k, v in params.items()})
    return FakeMap(index, classids.CORONA_BITMAP, p, cls="CoronaBitmap")


def _ccolor(index, **params):
    return FakeMap(index, classids.CORONA_COLOR, {int(k[1:]): v for k, v in params.items()}, cls="CoronaColor")


def _cmix(index, children=(), **params):
    return FakeMap(index, classids.CORONA_MIX, {int(k[1:]): v for k, v in params.items()}, children,
                   cls="CoronaMix")


class CoronaSynthetic(Checks):
    def test_kelvin(self):
        self.close(tx.kelvin_rgb(6600.0), (1.0, 1.0, 1.0), "about white")
        r, g, b = tx.kelvin_rgb(3000.0)
        self.close((r, g, b), (1.0, 177.20027 / 255, 109.91725 / 255))
        # Corona's own 3000 K, measured with renderMap: (255, 121.6, 39.2) linear
        for ours, corona in zip(colors.GAMMA_OFF.color((r, g, b)), (1.0, 121.607 / 255, 39.1868 / 255)):
            self.assertAlmostEqual(ours, corona, delta=0.04)
        self.assertEqual(tx.kelvin_rgb(100.0), tx.kelvin_rgb(1000.0))

    def test_corona_color_methods(self):
        cases = (
            (dict(p50=0, p52=(0.5, 0.5, 0.5), p57=2.0), (1.0, 1.0, 1.0)),
            (dict(p50=1, p58=(2.0, 0.5, 0.25), p57=1.0), (2.0, 0.5, 0.25)),
            (dict(p50=2, p51=3000.0), colors.GAMMA_OFF.color(tx.kelvin_rgb(3000.0))),  # sRGB whatever the gamma
            (dict(p50=3, p59="#FF8000"), (1.0, 128 / 255, 0.0)),  # a synthetic graph: no gamma, linear swatches
        )
        for params, want in cases:
            tex = _tex(_ccolor(1, **params))
            self.close(tex.convert(mat.MapRef(1), tx.COLOR).root.value, want, str(params))
            self.assertEqual(tex.stats.issues, [])
        tex = _tex(_ccolor(1, p50=3, p59="#12", p52=(1.0, 0.0, 0.0)))
        self.close(tex.convert(mat.MapRef(1), tx.COLOR).root.value, (1.0, 0.0, 0.0), "a bad hex: the color")
        self.assertIn("hex color", tex.stats.issues[0][1])
        tex = _tex(_ccolor(1, p50=9))
        self.close(tex.convert(mat.MapRef(1), tx.DATA).root.value, 1.0)
        self.assertIn("method 9", tex.stats.issues[0][1])

    def test_corona_mix_multiply_and_its_amount(self):
        objects = (_cmix(1, [2, 3], p200=2, p201=0.5, p206=Ref(2), p207=Ref(3)), _cbitmap(2), _cbitmap(3))
        root = _tex(*objects).convert(mat.MapRef(1), tx.COLOR).root
        self.assertIsInstance(root, tx.Mix)
        self.close(root.factor, 0.5)
        self.assertIsInstance(root.b, tx.Multiply)
        self.assertIs(root.a, root.b.a, "the bottom, shared")

    def test_corona_mix_switched_off_layers_and_multipliers(self):
        tex = _tex(_cmix(1, [2], p200=6, p201=0.3, p206=Ref(2), p212=0, p202=2.0), _cbitmap(2))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.b.value, (1.0, 1.0, 1.0), "top map off: the top color")
        self.close(g.root.a.value, (0.0, 0.0, 0.0), "the bottom color")
        self.assertTrue(g.approximated)
        self.assertIn("multipliers", g.issues[0])

    def test_corona_mix_peeled_does_not_convert_its_layers_first(self):
        tex = _tex(_cmix(1, [2, 3], p200=0, p206=Ref(2), p207=Ref(3)), _cbitmap(2), FakeMap(3, (0x1234, 0), cls="Noise"))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertEqual(tex.stats.unsupported, collections.Counter(), "the bottom Noise is never drawn")

    def test_corona_mix_other_operation_without_a_bitmap(self):
        tex = _tex(_cmix(1, p200=4))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertEqual(tex.stats.unsupported, collections.Counter({"CoronaMix": 1}))

    def test_corona_bitmap_defaults_gamma_and_real_world(self):
        g = _tex(_cbitmap(1)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.mapping, tx.Mapping())
        self.assertIsNone(g.root.gamma)
        tex = _tex(_cbitmap(1, p125=2.2, p114=1, p108=7, p103=-3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.gamma, 2.2)
        self.assertEqual(g.root.colorspace, tx.SRGB)
        self.assertTrue(g.root.mapping.real_world)
        self.assertEqual((g.root.mapping.tile, g.root.mapping.channel), ((True, True), 1), "bad values: defaults")
        self.assertIn("real-world", g.issues[0])

    def test_float_files_under_automatic_gamma_are_linear(self):
        table = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.HDR", "")])
        for params in ({}, {"p125": -1.0}, {"p125": 50.0}):  # automatic: -1 or outside 0.1 to 10
            g = _tex(_cbitmap(1, **params), table=table).convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual((g.root.gamma, g.root.colorspace), (1.0, tx.NON_COLOR), params)
        g = _tex(_cbitmap(1, p125=2.2), table=table).convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.gamma, 2.2)
        self.assertEqual(g.root.colorspace, tx.SRGB, "an override is kept")
        g = _tex(_cbitmap(1), table=table).convert(mat.MapRef(1), tx.DATA)
        self.assertEqual(g.root.colorspace, tx.NON_COLOR)
        g = _tex(_cbitmap(1)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual((g.root.gamma, g.root.colorspace), (None, tx.SRGB), "an 8-bit file: still automatic")

    def test_corona_bitmap_without_a_file(self):
        tex = _tex(_cbitmap(1, guid=G2))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertIn("CoronaBitmap", tex.stats.issues[0][1])

    def test_corona_bitmap_found_below_an_unknown_class(self):
        tex = _tex(FakeMap(1, (0x1234, 0), children=[2], cls="Noise"), _cbitmap(2, p105=(4.0, 4.0, 1.0)))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.mapping.tiling, (4.0, 4.0))
        self.assertTrue(g.approximated)

    def test_corona_bitmap_file_in_the_asset_helpers(self):
        m = _cbitmap(1)
        self.assertEqual(assets.bitmap_file(_table(), m).name, "a.png")


class Guards(Checks):
    def test_unreadable_placement_takes_the_defaults(self):
        _tex_, g = _image(*_placed(old={2: float("nan"), 3: 2.0}))  # no chunk for the Placement object
        self.assertEqual(g.root.mapping.tiling, (1.0, 2.0))
        self.assertEqual(g.root.mapping.tile, (True, True))
        self.assertEqual(g.root.mapping.channel, 1)

    def test_short_and_out_of_range_placement_chunks(self):
        uv = FakeChunk(0x0009, children=[FakeChunk(0x9002, b"\x01\x00"), FakeChunk(0x900B, struct.pack("<I", 1000)),
                                         FakeChunk(0x9006, struct.pack("<I", 9)), FakeChunk(0x9003, b"\x07\0\0\0")])
        _tex_, g = _image(*_placed(uv=uv))
        self.assertEqual(g.root.mapping, tx.Mapping())

    def test_placement_chunks(self):
        uv = FakeChunk(0x0009, children=[FakeChunk(0x9002, struct.pack("<I", 0x48000008)),
                                         FakeChunk(0x900B, struct.pack("<I", 4))])
        tex, g = _image(*_placed(uv=uv))
        self.assertEqual(g.root.mapping.tile, (False, False))
        self.assertEqual(g.root.mapping.mirror, (False, True))
        self.assertTrue(g.root.mapping.real_world)
        self.assertEqual(g.root.mapping.channel, 4)
        self.assertTrue(any("real-world" in r for r in g.issues))

    def test_gamma(self):
        cases = ((_info(1.8, 5), 1.8, tx.NON_COLOR), (_info(2.2, 5), 2.2, tx.SRGB), (_info(1.0, 20), None, tx.SRGB),
                 (_info(float("nan"), 5), None, tx.SRGB), (_info(50.0, 5), None, tx.SRGB), (b"\x05" * 10, None, tx.SRGB))
        for info, gamma, space in cases:
            with self.subTest(info=info.hex()):
                _tex_, g = _image(*_placed(info=info))
                if gamma is None:
                    self.assertIsNone(g.root.gamma)
                else:
                    self.close(g.root.gamma, gamma)
                self.assertEqual(g.root.colorspace, space)

    def test_shared_maps_do_not_blow_up(self):
        layers, depth = 10, tx.MAX_DEPTH
        objects = [FakeMap(k, tx.COMPOSITE, {9: [Ref(k + 1)] * layers}, [k + 1], cls="Composite")
                   for k in range(1, depth)] + [_bitmap(depth)]
        tex = _tex(*objects)
        start = time.perf_counter()
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertLess(time.perf_counter() - start, 2.0)
        self.assertIsInstance(g.root, tx.Image)  # 10 ** 7 nodes as a tree: cut down to its first image
        self.assertTrue(g.approximated)
        self.assertTrue(any("cut down" in r for r in g.issues))

    def test_composite_with_a_blend_mode_is_peeled(self):
        comp = FakeMap(1, tx.COMPOSITE, {5: [0, 2], 9: [Ref(2), Ref(3)]}, [2, 3], cls="Composite")
        tex = _tex(comp, _bitmap(2), _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Image)
        self.assertTrue(any("blend modes" in r for r in g.issues))

    def test_color_correction_modes(self):
        standard = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 11: 0, 12: 10.0, 13: -20.0, 22: 2.0}, [2])
        g = _tex(standard, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual((g.root.brightness, g.root.contrast, g.root.gamma), (0.1, -0.2, 1.0))
        self.assertFalse(g.approximated)
        lifted = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 11: 1, 30: 0.2, 2: 1}, [2])
        g = _tex(lifted, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertTrue(g.approximated)
        self.assertTrue(any("pivot and lift" in r for r in g.issues))
        self.assertTrue(any("rewiring" in r for r in g.issues))

    def test_mix_curve_is_an_issue(self):
        mix = FakeMap(1, tx.MIX, {3: 1, 6: Ref(2)}, [2])
        g = _tex(mix, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertTrue(g.approximated)
        self.assertTrue(any("mix curve" in r for r in g.issues))

    def test_normal_bump_method_and_channel(self):
        nb = FakeMap(1, tx.NORMAL_BUMP, {2: Ref(2), 6: 2}, [2])
        g = _tex(nb, _bitmap(2)).convert(mat.MapRef(1), tx.NORMAL)
        self.assertTrue(any("method" in r for r in g.issues))
        vn = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(2), 1: 2}, [2])
        self.assertEqual(_tex(vn, _bitmap(2)).convert(mat.MapRef(1), tx.NORMAL).root.channel, 2)

    def test_an_issue_is_reported_once(self):
        uv = FakeChunk(0x0009, children=[FakeChunk(0x9005, struct.pack("<I", 1))])
        b, chunk_map = _placed(uv=uv)
        tex = tx.TexmapConverter(FakeGraph(b, chunk_map=chunk_map), _table())
        tex.convert(mat.MapRef(1), tx.COLOR)
        tex.convert(mat.MapRef(1, 0.5), tx.COLOR, (0.1, 0.1, 0.1))
        tex.convert(mat.MapRef(1), tx.DATA)
        self.assertEqual(len(tex.stats.issues), 1)

    def test_normal_map_without_images_in_a_color_input(self):
        n = FakeMap(1, classids.VRAY_NORMAL_MAP, {}, cls="VRayNormalMap")
        tex = _tex(n)
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertEqual(tex.stats.unsupported, collections.Counter({"VRayNormalMap": 1}))
        self.assertEqual(tex.stats.peeled, collections.Counter())


class VRayTexmaps(Checks):
    """vray_texmaps.ms: VRayBitmap in every kind of input, with its own placement, transfer functions, multipliers
    and alpha, below a VRayNormalMap, a Composite and a Mix."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("vray_texmaps")

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def test_class_ids_match_the_class_directory(self):
        names = {(e.superclass, e.class_id): e.name for e in (self.f.scene.entry(i) for i in range(len(self.f.scene)))
                 if e is not None}
        for cid, name in ((classids.VRAY_BITMAP, "VRayBitmap"), (classids.NOISE, "Noise"),
                          (classids.VRAY_COLOR, "VRayColor")):
            self.assertEqual(names.get((classids.SC_TEXMAP, cid)), name, name)

    def test_defaults_in_diffuse(self):
        g = self.f.irs["FixtureVBDiffuse"].textures["base_color"]
        self.image(g.root, "vtx_diffuse.png", tx.SRGB)  # transfer function Auto: sRGB for an 8-bit file
        self.assertEqual((g.root.gamma, g.root.crop, g.root.output, g.root.alpha), (None, None, None, False))
        self.assertEqual(g.root.path, "vtx_diffuse.png")
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def test_spherical_mapping_is_an_issue(self):
        g = self.f.irs["FixtureVBDiffuse"].textures["specular"]
        self.image(g.root, "vtx_sphere.png", tx.SRGB)
        self.assertTrue(g.root.mapping.environment)
        self.assertTrue(any("environment mapping" in r for r in g.issues), g.issues)

    def test_own_placement_and_multipliers(self):
        g = self.f.irs["FixtureVBPlace"].textures["base_color"]
        self.image(g.root, "vtx_place.png", tx.SRGB, tiling=(2.0, 3.0), offset=(0.1, 0.2), w_angle=30.0)
        self.close(g.root.mapping.blur, 0.8)
        self.assertFalse(g.root.mapping.environment)
        self.close(g.root.output.amount, 3.0)  # overall 1.5 x render 2
        self.assertEqual((g.root.output.invert, g.root.output.level, g.root.output.offset), (False, 1.0, 0.0))
        self.assertEqual(g.issues, ())

    def test_transfer_functions(self):
        t = self.f.irs["FixtureVBPlace"].textures
        self.image(t["specular"].root, "vtx_linear.png", tx.NON_COLOR)  # None: linear
        self.close(t["specular"].root.gamma, 1.0)
        self.image(t["transmission"].root, "vtx_invgamma.png", tx.NON_COLOR)  # inverse gamma 2: pixel ^ 0.5
        self.close(t["transmission"].root.gamma, 0.5)
        self.assertIsInstance(t["roughness"].root, tx.Invert)
        self.image(t["roughness"].root.input, "vtx_gloss.png", tx.NON_COLOR)  # sRGB, but a data input
        self.assertIsNone(t["roughness"].root.input.gamma)

    def test_mono_output_alpha(self):
        image = self.f.irs["FixtureVBPlace"].textures["alpha"].root
        self.image(image, "vtx_alpha.png", tx.NON_COLOR)
        self.assertTrue(image.alpha)

    def test_bump_and_normal(self):
        b = self.f.irs["FixtureVBBump"].textures["bump"].root
        self.assertIsInstance(b, tx.Bump)
        self.close(b.strength, 0.5)
        self.image(b.input, "vtx_bump.png", tx.NON_COLOR)
        n = self.f.irs["FixtureVBNormal"].textures["normal"].root
        self.assertIsInstance(n, tx.NormalMap)
        self.close(n.strength, 0.9)
        self.image(n.input, "vtx_normal.png", tx.NON_COLOR)
        self.close(n.input.gamma, 1.0)

    def test_below_a_color_correction_composite_and_mix(self):
        cc = self.f.irs["FixtureCCComposite"].textures["base_color"].root
        self.assertIsInstance(cc, tx.ColorCorrect)
        self.close(cc.brightness, 0.1)
        self.assertIsInstance(cc.input, tx.Composite)
        (a, oa), (b, ob) = cc.input.layers
        self.image(a, "vtx_layer_a.png", tx.SRGB)
        self.image(b, "vtx_layer_b.png", tx.SRGB)
        self.close((oa, ob), (1.0, 0.5))
        mix = self.f.irs["FixtureMixMask"].textures["base_color"].root
        self.assertIsInstance(mix, tx.Mix)
        self.image(mix.a, "vtx_mix_a.png", tx.SRGB)

    def test_vray_color(self):
        t = self.f.irs["FixtureVColor"].textures
        self.assertEqual((t["base_color"].approximated, t["base_color"].issues), (False, ()))
        self.close(t["base_color"].root.value, (1.0, _lin(150), _lin(75)))  # 200 100 50 times 1.5, clamped
        self.close(t["specular"].root.value, (_lin(255 * (128 / 255) ** 2.2),) * 3)  # color gamma 2.2

    def test_vray_color_below_falloff_color_correction_and_mix(self):
        g = self.f.irs["FixtureVFalloff"].textures["base_color"]
        self.assertIsInstance(g.root, tx.Constant)
        self.close(g.root.value, (_lin(50), _lin(150), _lin(250)))
        self.assertTrue(g.approximated)  # the Falloff is peeled
        cc = self.f.irs["FixtureCCColor"].textures["base_color"].root
        self.assertIsInstance(cc, tx.ColorCorrect)
        self.close(cc.saturation, 1.2)
        self.close(cc.input.value, (_lin(100), _lin(200), _lin(50)))
        mix = self.f.irs["FixtureMixMask"].textures["base_color"].root
        self.assertIsInstance(mix.mask, tx.Constant)
        self.close(mix.mask.value, _lin(64))  # a mask is data: a float

    def test_color_correction_over_an_unsupported_map(self):
        ir = self.f.irs["FixtureCCNoise"]
        self.assertNotIn("base_color", ir.textures, "the material's own diffuse, not the Color Correction's black")
        issues = [r for i, r in self.f.tex.stats.issues if "converts to nothing" in r]
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("Color Correction", issues[0])
        self.assertIn("Noise", issues[0])

    def test_peeled_and_unsupported_classes(self):
        # the Noise below a Color Correction converts to nothing
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter({"Falloff": 1}))
        self.assertEqual(self.f.tex.stats.unsupported, collections.Counter({"Noise": 1}))

    def test_rgb_color_space_is_read_from_block_3(self):
        m = self.f.graph.get(self.f.irs["FixtureVBNormal"].textures["normal"].root.input.index)
        self.assertEqual(m.param(tx.VB_RGB_SPACE, tx.VB_RGB_SPACE_BLOCK), 3)  # raw: no ACEScg issue
        self.assertIsNone(m.param(tx.VB_RGB_SPACE, 0))


def _vbitmap(index, guid=G1, **params):
    p = {0: pblock.Asset(guid)}
    p.update({int(k[1:]): v for k, v in params.items()})
    return FakeMap(index, classids.VRAY_BITMAP, p, cls="VRayBitmap", name="vb")


def _vb(kind=tx.COLOR, **params):
    tex = _tex(_vbitmap(1, **params))
    return tex, tex.convert(mat.MapRef(1), kind)


class VRayBitmapSynthetic(Checks):
    def test_defaults(self):
        _t, g = _vb()
        self.assertEqual(g.root.name, "a.png")
        self.assertEqual(g.root.mapping, tx.Mapping())  # no Placement part: its defaults
        self.assertEqual((g.root.gamma, g.root.colorspace, g.root.output, g.root.crop), (None, tx.SRGB, None, None))
        self.assertEqual(g.issues, ())

    def test_without_a_file(self):
        tex, g = _vb(guid=G2)
        self.assertIsNone(g)
        self.assertEqual(tex.stats.issues, [(1, "VRayBitmap 'vb': no file")])
        tex = tx.TexmapConverter(FakeGraph(_vbitmap(1)))  # no asset table at all
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        tex = _tex(FakeMap(1, classids.VRAY_BITMAP, {}, cls="VRayBitmap"))  # no file parameter
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))

    def test_transfer_functions(self):
        for params, gamma, space in (({"p25": 0}, 1.0, tx.NON_COLOR), ({"p25": 1, "p8": 2.0}, 0.5, tx.NON_COLOR),
                                     ({"p25": 1, "p8": 0.4545}, 2.2002, tx.SRGB), ({"p25": 2}, None, tx.SRGB),
                                     ({"p25": 3}, None, tx.SRGB), ({"p25": 4}, None, tx.SRGB)):
            _t, g = _vb(**params)
            self.assertEqual(g.root.colorspace, space, params)
            if gamma is None:
                self.assertIsNone(g.root.gamma, params)
            else:
                self.assertAlmostEqual(g.root.gamma, gamma, delta=1e-3, msg=params)
            self.assertEqual(g.issues, (), params)
        _t, g = _vb(tx.DATA, p25=1, p8=0.4545)
        self.assertEqual(g.root.colorspace, tx.NON_COLOR)

    def test_float_files_under_auto_are_linear(self):
        table = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.EXR", "")])
        for params, gamma in (({}, 1.0), ({"p25": 4}, 1.0), ({"p25": 3}, 1.0), ({"p25": 2}, None),
                              ({"p25": 1, "p8": 2.0}, 0.5)):
            g = _tex(_vbitmap(1, **params), table=table).convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual(g.root.gamma, gamma, params)
            self.assertEqual(g.root.colorspace, tx.SRGB if gamma is None else tx.NON_COLOR, params)

    def test_unusable_transfer_function(self):
        for params in ({"p25": 1, "p8": 0.0}, {"p25": 1, "p8": float("nan")}, {"p25": 9}, {"p25": "x"}):
            _t, g = _vb(**params)
            self.assertIsNone(g.root.gamma, params)
            self.assertEqual(g.root.colorspace, tx.SRGB, params)
            self.assertEqual(len(g.issues), 1, params)
            self.assertIn("transfer function", g.issues[0], params)

    def test_multipliers(self):
        _t, g = _vb(p1=1.5, p9=2.0)
        self.assertEqual(g.root.output, tx.TexOutput(amount=3.0))
        _t, g = _vb(p1=float("nan"), p9="x")
        self.assertIsNone(g.root.output)
        _t, g = _vb(p1=-2.0)
        self.assertEqual(g.root.output, tx.TexOutput(amount=0.0))
        _t, g = _vb(p1=1e200, p9=1e200)  # overflows to inf
        self.assertIsNone(g.root.output)
        self.assertIn("multiplier", g.issues[0])

    def test_environment_mapping_types(self):
        for t in (0, 1, 2, 3):
            _t, g = _vb(p2=t)
            self.assertTrue(g.root.mapping.environment, t)
            self.assertIn("environment mapping", g.issues[0])
        _t, g = _vb(p2=4)
        self.assertFalse(g.root.mapping.environment)
        self.assertEqual(g.issues, ())

    def test_crop_place_and_alpha(self):
        _t, g = _vb(p16=1, p17=1, p18=0.1, p19=0.2, p20=0.5, p21=0.6, p22=1)
        self.assertEqual(g.root.crop, tx.Crop(0.1, 0.2, 0.5, 0.6, place=True))
        self.assertTrue(g.root.alpha)  # RGB output: alpha as gray
        _t, g = _vb(tx.DATA, p23=1)
        self.assertTrue(g.root.alpha)
        _t, g = _vb(tx.DATA, p22=1)
        self.assertFalse(g.root.alpha)  # a data input reads the mono output

    def test_issues(self):
        for params, words in (({"p22": 2}, "intensity"), ({"p38": Ref(5), "p39": 1}, "map source"),
                              ({"p41": 2}, "ACEScg")):
            _t, g = _vb(**params)
            self.assertEqual(len(g.issues), 1, params)
            self.assertIn(words, g.issues[0], params)
        _t, g = _vb(p38=Ref(5), p39=0)
        self.assertEqual(g.issues, ())

    def test_found_below_an_unknown_class(self):
        tex = _tex(FakeMap(1, (0x1234, 0), children=[2], cls="Noise"), _vbitmap(2, p25=0))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.close(g.root.gamma, 1.0)
        self.assertTrue(g.approximated)

    def test_file_in_the_asset_helpers(self):
        self.assertEqual(assets.bitmap_file(_table(), _vbitmap(1)).name, "a.png")


def _vc(kind=tx.COLOR, **params):
    tex = _tex(FakeMap(1, classids.VRAY_COLOR, {int(k[1:]): v for k, v in params.items()}, cls="VRayColor",
                       name="vc"))
    return tex, tex.convert(mat.MapRef(1), kind)


class VRayColorSynthetic(Checks):
    def test_defaults(self):
        _t, g = _vc()
        self.assertEqual(g.root, tx.Constant((1.0, 1.0, 1.0)))
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def test_multiplier_before_color_gamma(self):
        # measured with renderMap: (100 gray, multiplier 2, color gamma 2) -> 156.86
        _t, g = _vc(p5=(100 / 255,) * 3, p4=2.0, p10=2.0)
        self.close(g.root.value, ((200 / 255) ** 2.0,) * 3)  # linear: a synthetic graph has no gamma
        self.assertAlmostEqual(255 * (200 / 255) ** 2.0, 156.86, delta=0.01)  # not (100 / 255) ^ 2 x 2 = 78.4

    def test_channels_when_the_color_is_unreadable(self):
        _t, g = _vc(p5="x", p0=0.5, p1=0.25, p2=1.0)
        self.close(g.root.value, (0.5, 0.25, 1.0))
        _t, g = _vc(p5=(0.5, float("nan"), 0.5), p0=0.5, p1=None, p2=0.5)
        self.close(g.root.value, (1.0, 1.0, 1.0))  # neither is usable: white

    def test_data_input_is_the_mean(self):
        _t, g = _vc(tx.DATA, p5=(1.0, 0.0, 0.0))
        self.close(g.root.value, 1.0 / 3.0)

    def test_temperature_mode_reads_the_color(self):
        _t, g = _vc(p9=1, p8=3000.0, p5=(1.0, 123.906 / 255, 38.3965 / 255))  # V-Ray's own 3000 K
        self.close(g.root.value, (1.0, 123.906 / 255, 38.3965 / 255))
        self.assertEqual(g.issues, ())

    def test_unusable_values_are_issues(self):
        for params, words, want in (
                ({"p4": float("inf")}, "multiplier", (1.0, 1.0, 1.0)),
                ({"p4": -1.0, "p5": (0.5,) * 3}, "multiplier", (0.5,) * 3),
                ({"p10": 0.0, "p5": (0.5,) * 3}, "color gamma", (0.5,) * 3),
                ({"p10": "x", "p5": (0.5,) * 3}, "color gamma", (0.5,) * 3),
                ({"p9": 7}, "color mode", (1.0, 1.0, 1.0)),
                ({"p9": 1, "p5": None}, "temperature color", (1.0, 1.0, 1.0)),
                ({"p3": 0.5}, "alpha", (1.0, 1.0, 1.0)),
                ({"p11": 1}, "primaries", (1.0, 1.0, 1.0))):
            _t, g = _vc(**params)
            self.close(g.root.value, want, str(params))
            self.assertEqual(len(g.issues), 1, params)
            self.assertIn(words, g.issues[0], params)
        _t, g = _vc(p4=0.0, p3=1.0, p11=0, p9=0)
        self.close(g.root.value, (0.0, 0.0, 0.0))
        self.assertEqual(g.issues, ())


def _noise(index):
    """An unsupported map class with no bitmap below: converts to nothing."""
    return FakeMap(index, (0x1234, 0), cls="Noise", name="n")


class LostMaps(Checks):
    """A wrapper whose map is set and on but converts to nothing never draws its own color for it."""

    def lost_issue(self, tex, wrapper):
        issues = [r for _i, r in tex.stats.issues if "converts to nothing" in r]
        self.assertEqual(len(issues), 1, tex.stats.issues)
        self.assertTrue(issues[0].startswith(wrapper), issues[0])
        self.assertIn("Noise 'n'", issues[0])

    def test_color_correction(self):
        tex = _tex(FakeMap(1, tx.COLOR_CORRECTION, {0: (1.0, 0.0, 0.0), 1: Ref(2)}, [2], cls="Color Correction",
                           name="cc"), _noise(2))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.lost_issue(tex, "Color Correction 'cc'")
        self.assertEqual(tex.stats.unsupported, collections.Counter({"Noise": 1}))
        tex = _tex(FakeMap(1, tx.COLOR_CORRECTION, {0: (1.0, 0.0, 0.0), 1: Ref(None)}, cls="Color Correction"))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.input.value, (1.0, 0.0, 0.0), "no map: its color, as 3ds Max")
        self.assertEqual(tex.stats.issues, [])

    def test_mix_gives_its_other_map(self):
        tex = _tex(FakeMap(1, tx.MIX, {0: 0.5, 6: Ref(2), 7: Ref(3)}, [2, 3], cls="Mix", name="mx"), _bitmap(2),
                   _noise(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertTrue(g.approximated)
        self.assertEqual(tex.stats.peeled, collections.Counter({"Mix": 1}))
        self.assertEqual(tex.stats.unsupported, collections.Counter({"Noise": 1}))
        self.lost_issue(tex, "Mix 'mx'")
        tex = _tex(FakeMap(1, tx.MIX, {0: 0.5, 6: Ref(None), 7: Ref(3)}, [3], cls="Mix", name="mx"), _noise(3))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR), "color 1 is not the Noise's stand-in")
        self.lost_issue(tex, "Mix 'mx'")
        tex = _tex(FakeMap(1, tx.MIX, {0: 0.5, 6: Ref(2), 7: Ref(3)}, [2, 3], cls="Mix"), _noise(2), _noise(3))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR), "both sides lost")

    def test_mix_weighs_a_lost_map_by_its_amount(self):
        tex = _tex(FakeMap(1, tx.MIX, {0: 0.0, 6: Ref(2), 7: Ref(3)}, [2, 3], cls="Mix"), _noise(2), _bitmap(3))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR), "amount 0: map 1 fills the result")
        tex = _tex(FakeMap(1, tx.MIX, {0: 1.0, 5: (1.0, 0.0, 0.0), 6: Ref(2)}, [2], cls="Mix", name="mx"),
                   _noise(2))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix, "amount 1: map 1 does not show")
        self.close(g.root.factor, 1.0)
        self.close(g.root.b.value, (1.0, 0.0, 0.0))
        self.assertFalse(g.approximated)
        self.lost_issue(tex, "Mix 'mx'")
        tex = _tex(FakeMap(1, tx.MIX, {0: 1.0, 3: 1, 6: Ref(2), 7: Ref(3)}, [2, 3], cls="Mix"), _noise(2),
                   _bitmap(3))
        self.assertEqual(tex.convert(mat.MapRef(1), tx.COLOR).root.name, "a.png", "a curve: weights unknown")

    def test_lost_map_below_a_lost_wrapper(self):
        cc = FakeMap(2, tx.COLOR_CORRECTION, {1: Ref(3)}, [3], cls="Color Correction", name="cc")
        mix = FakeMap(1, tx.MIX, {0: 0.5, 6: Ref(2), 7: Ref(4)}, [2, 4], cls="Mix", name="mx")
        tex = _tex(mix, cc, _noise(3), _bitmap(4))
        first = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(first.root.name, "a.png")
        second = tex.convert(mat.MapRef(1, 0.5), tx.COLOR, (0.0, 0.0, 0.0))  # the Mix node again, from the cache
        self.assertIs(second.root.b, first.root)
        for g in (first, second):
            self.assertTrue(g.approximated)
            self.assertTrue(any(r.startswith("Color Correction 'cc'") for r in g.issues), g.issues)
            self.assertTrue(any(r.startswith("Mix 'mx'") for r in g.issues), g.issues)
        self.assertEqual(len([r for _i, r in tex.stats.issues if "converts to nothing" in r]), 2)

    def test_normal_map_names_its_lost_normal_map(self):
        n = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(2), 2: 1, 4: Ref(3), 5: 1}, [2, 3], cls="VRayNormalMap")
        tex = _tex(n, _noise(2), _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.NORMAL)
        self.assertIsInstance(g.root, tx.Bump, "its bump map stays")
        self.lost_issue(tex, "VRayNormalMap")

    def test_composite_names_a_lost_layer(self):
        comp = FakeMap(1, tx.COMPOSITE, {9: [Ref(2), Ref(3)]}, [2, 3], cls="Composite", name="cp")
        tex = _tex(comp, _bitmap(2), _noise(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertTrue(g.approximated)
        self.lost_issue(tex, "Composite 'cp'")

    def test_mix_with_a_switched_off_map_is_its_color(self):
        tex = _tex(FakeMap(1, tx.MIX, {4: (1.0, 0.0, 0.0), 6: Ref(2), 9: 0, 7: Ref(3)}, [2, 3], cls="Mix"),
                   _noise(2), _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix)
        self.close(g.root.a.value, (1.0, 0.0, 0.0))
        self.assertEqual(g.root.b.name, "a.png")
        self.assertEqual(tex.stats.issues, [])

    def test_mix_lost_mask_keeps_the_amount(self):
        tex = _tex(FakeMap(1, tx.MIX, {0: 0.3, 6: Ref(2), 8: Ref(3)}, [2, 3], cls="Mix", name="mx"), _bitmap(2),
                   _noise(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix)
        self.close(g.root.factor, 0.3)
        self.assertIsNone(g.root.mask)
        self.assertTrue(g.approximated)
        self.lost_issue(tex, "Mix 'mx'")

    def test_rgb_multiply(self):
        tex = _tex(FakeMap(1, tx.RGB_MULTIPLY, {2: Ref(2), 3: Ref(3)}, [2, 3], cls="RGB Multiply", name="rm"),
                   _noise(2), _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertTrue(g.approximated)
        self.assertEqual(tex.stats.unsupported, collections.Counter({"Noise": 1}))
        self.lost_issue(tex, "RGB Multiply 'rm'")
        tex = _tex(FakeMap(1, tx.RGB_MULTIPLY, {2: Ref(2), 3: Ref(3)}, [2, 3], cls="RGB Multiply"), _noise(2),
                   _noise(3))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))

    def test_corona_mix(self):
        tex = _tex(_cmix(1, [2, 3], p200=6, p201=0.5, p207=Ref(2), p206=Ref(3)), _noise(2), _cbitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertTrue(g.approximated)
        self.lost_issue(tex, "CoronaMix 'map'")
        tex = _tex(_cmix(1, [2, 3], p200=6, p207=Ref(2), p206=Ref(3)), _noise(2), _cbitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix, "amount 1 (its default): the lost bottom does not show")
        self.assertEqual(g.root.b.name, "a.png")
        self.assertFalse(g.approximated)
        tex = _tex(_cmix(1, [2, 3], p200=6, p207=Ref(2), p206=Ref(3)), _cbitmap(2), _noise(3))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR), "amount 1: the lost top fills the result")
        tex = _tex(_cmix(1, [3], p200=2, p206=Ref(3)), _noise(3))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR), "the bottom color alone is not the product")
        tex = _tex(_cmix(1, [2, 3], p200=2, p201=0.0, p207=Ref(2), p206=Ref(3)), _cbitmap(2), _noise(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix, "multiply at amount 0: the bottom alone")
        self.assertEqual(g.root.a.name, "a.png")
        tex = _tex(_cmix(1, [2, 3], p200=6, p201=0.4, p207=Ref(2), p210=Ref(3)), _cbitmap(2), _noise(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix)
        self.close(g.root.factor, 0.4)
        self.assertTrue(g.approximated, "a lost mask: the amount")

    def test_peeled_wrappers_give_nothing(self):
        for wrapper, cls in ((_falloff(1, 2, color1=(1.0, 0.0, 0.0)), "Falloff"),
                             (FakeMap(1, tx.VRAY_DIRT, {13: (1.0, 0.0, 0.0), 17: Ref(2)}, [2], cls="VRayDirt"),
                              "VRayDirt"),
                             (FakeMap(1, tx.OUTPUT, {0: Ref(2)}, [2], cls="Output"), "Output"),
                             (FakeMap(1, tx.RGB_TINT, {3: Ref(2)}, [2], cls="RGB Tint"), "RGB Tint"),
                             (FakeMap(1, tx.VRAY_COLOR2BUMP, {0: Ref(2)}, [2], cls="VRayColor2Bump"),
                              "VRayColor2Bump")):
            tex = _tex(wrapper, _noise(2))
            self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR), cls)
            self.lost_issue(tex, cls)
            self.assertEqual(tex.stats.peeled, collections.Counter(), "%s drew nothing: not a peel" % cls)
            self.assertEqual(tex.stats.unsupported, collections.Counter({"Noise": 1}), "the lost map only")
            self.assertEqual(len(tex.stats.issues), 2, "the Noise and the lost map: %s" % tex.stats.issues)
        tex = _tex(_falloff(1, color1=(1.0, 0.0, 0.0)))
        self.close(tex.convert(mat.MapRef(1), tx.COLOR).root.value, (1.0, 0.0, 0.0), "no map: color 1")
        self.assertEqual(tex.stats.peeled, collections.Counter({"Falloff": 1}))
        tex = _tex(FakeMap(1, tx.VRAY_DIRT, {13: (1.0, 0.0, 0.0), 17: Ref(2), 18: 0}, [2], cls="VRayDirt"),
                   _noise(2))
        self.close(tex.convert(mat.MapRef(1), tx.COLOR).root.value, (1.0, 0.0, 0.0), "map off: its color")
        self.assertEqual(tex.stats.peeled, collections.Counter({"VRayDirt": 1}))

    # (class, class name, map pid, switch pid or None): the wrappers that have no color of their own
    EMPTY_WRAPPERS = ((tx.OUTPUT, "Output", 0, 1), (tx.RGB_TINT, "RGB Tint", 3, 4),
                      (tx.VRAY_COLOR2BUMP, "VRayColor2Bump", 0, None))

    def empty_issue(self, tex, wrapper):
        issues = [r for _i, r in tex.stats.issues if "no map" in r]
        self.assertEqual(len(issues), 1, tex.stats.issues)
        self.assertTrue(issues[0].startswith(wrapper), issues[0])

    def test_empty_wrappers_are_named(self):
        for class_id, cls, pid, on in self.EMPTY_WRAPPERS:
            cases = [("map unset", _tex(FakeMap(1, class_id, {pid: Ref(None)}, cls=cls, name="w")))]
            if on is not None:  # map off: the bitmap below is not used
                cases.append(("map off", _tex(FakeMap(1, class_id, {pid: Ref(2), on: 0}, [2], cls=cls, name="w"),
                                              _bitmap(2))))
            for case, tex in cases:
                with self.subTest(cls=cls, case=case):
                    self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
                    self.assertEqual(len(tex.stats.issues), 1, tex.stats.issues)
                    self.empty_issue(tex, "%s 'w'" % cls)
                    self.assertEqual(tex.stats.peeled, collections.Counter())
                    self.assertEqual(tex.stats.unsupported, collections.Counter())
                    self.assertIsNone(tex.convert(mat.MapRef(1), tx.DATA))
                    self.assertEqual(len(tex.stats.issues), 1, "named once: %s" % tex.stats.issues)

    def test_empty_wrapper_below_a_mix(self):
        empty = FakeMap(2, tx.OUTPUT, {0: Ref(None)}, cls="Output", name="out")
        tex = _tex(FakeMap(1, tx.MIX, {0: 0.5, 6: Ref(2), 7: Ref(3)}, [2, 3], cls="Mix", name="mx"), empty,
                   _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertTrue(g.approximated)
        self.empty_issue(tex, "Output 'out'")
        self.lost_issue_of(tex, "Mix 'mx'", "Output 'out'")
        tex = _tex(FakeMap(1, tx.MIX, {0: 1.0, 6: Ref(2), 7: Ref(3)}, [2, 3], cls="Mix", name="mx"), empty,
                   _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix, "amount 1: map 1 does not show")
        self.assertFalse(g.approximated)
        self.empty_issue(tex, "Output 'out'")

    def test_empty_wrapper_elsewhere(self):
        tint = FakeMap(2, tx.RGB_TINT, {3: Ref(None)}, cls="RGB Tint", name="t")
        tex = _tex(FakeMap(1, tx.COMPOSITE, {9: [Ref(3), Ref(2)]}, [3, 2], cls="Composite", name="cp"), tint,
                   _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png", "the empty layer is left out")
        self.empty_issue(tex, "RGB Tint 't'")
        self.lost_issue_of(tex, "Composite 'cp'", "RGB Tint 't'")
        c2b = FakeMap(1, tx.VRAY_COLOR2BUMP, {0: Ref(None)}, cls="VRayColor2Bump", name="c2b")
        tex = _tex(c2b)
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.BUMP))
        self.assertEqual([r for _i, r in tex.stats.issues], ["VRayColor2Bump 'c2b': no map, not drawn"])
        tex = _tex(FakeMap(1, tx.OUTPUT, {0: Ref(2)}, [2], cls="Output", name="out"), tint)
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.empty_issue(tex, "RGB Tint 't'")
        self.lost_issue_of(tex, "Output 'out'", "RGB Tint 't'")
        self.assertEqual(tex.stats.peeled, collections.Counter())

    def lost_issue_of(self, tex, wrapper, lost):
        issues = [r for _i, r in tex.stats.issues if "converts to nothing" in r]
        self.assertEqual(len(issues), 1, tex.stats.issues)
        self.assertTrue(issues[0].startswith(wrapper), issues[0])
        self.assertIn(lost, issues[0])

    def test_hidden_peeled_wrapper_is_exact(self):
        # mix amount 1: map 1 (a Falloff over a lost map) does not show and is drawn as color 1
        tex = _tex(FakeMap(1, tx.MIX, {0: 1.0, 6: Ref(2), 7: Ref(3)}, [2, 3], cls="Mix", name="mx"),
                   _falloff(2, 4), _bitmap(3), _noise(4))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix)
        self.assertFalse(g.approximated)
        self.assertEqual(tex.stats.peeled, collections.Counter())
        self.assertEqual(tex.stats.unsupported, collections.Counter({"Noise": 1}))

    def test_lost_map_that_is_not_a_map(self):
        tex = _tex(FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(7)}, [7], cls="Color Correction", name="cc"))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        reasons = [r for _i, r in tex.stats.issues]
        self.assertTrue(any("object 7 is not a map" in r for r in reasons), reasons)
        self.assertFalse(any("converts to nothing" in r for r in reasons), "named once, by the reference")


class SwatchRule(Checks):
    """Every swatch of a map goes through the scene's rule: linear with the gamma on (or unknown), sRGB with it off;
    the kelvin fit and the HDR color do not."""

    def _root(self, swatches, *objects, kind=tx.COLOR):
        tex = tx.TexmapConverter(FakeGraph(*objects), _table(), swatches=swatches)
        return tex.convert(mat.MapRef(objects[0].index), kind).root

    def test_default_is_unknown(self):
        self.assertIs(_tex().swatches, colors.UNKNOWN)

    def test_each_swatch_by_the_rule(self):
        g = 128 / 255
        mix = FakeMap(1, tx.MIX, {4: (g,) * 3, 5: (g,) * 3}, cls="Mix")
        falloff = FakeMap(1, tx.FALLOFF, {0: (g,) * 3}, cls="Falloff")
        dirt = FakeMap(1, tx.VRAY_DIRT, {13: (g,) * 3}, cls="VRayDirt")
        cc = FakeMap(1, tx.COLOR_CORRECTION, {0: (g,) * 3}, cls="Color Correction")
        vc = FakeMap(1, classids.VRAY_COLOR, {5: (g,) * 3}, cls="VRayColor")
        cco = _ccolor(1, p52=(g,) * 3)
        hexed = _ccolor(1, p50=3, p59="#808080")
        for rule, want in ((colors.GAMMA_ON, 0.501961), (colors.GAMMA_OFF, 0.215861), (colors.UNKNOWN, 0.501961)):
            with self.subTest(rule):
                root = self._root(rule, mix)
                self.close(root.a.value, (want,) * 3)
                self.close(root.b.value, (want,) * 3)
                self.close(self._root(rule, falloff).value, (want,) * 3)
                self.close(self._root(rule, dirt).value, (want,) * 3)
                self.close(self._root(rule, cc).input.value, (want,) * 3)
                for m in (vc, cco, hexed):
                    self.close(self._root(rule, m).value, (want,) * 3, m.cls)
                self.close(self._root(rule, vc, kind=tx.DATA).value, want, "a data input: the mean")

    def test_kelvin_and_hdr_whatever_the_rule(self):
        kelvin, hdr = _ccolor(1, p50=2, p51=3000.0), _ccolor(1, p50=1, p58=(0.25, 0.5, 2.0))
        for rule in (colors.GAMMA_ON, colors.GAMMA_OFF):
            with self.subTest(rule):
                self.close(self._root(rule, kelvin).value, colors.GAMMA_OFF.color(tx.kelvin_rgb(3000.0)))
                self.close(self._root(rule, hdr).value, (0.25, 0.5, 2.0))


class GammaSwatchesFixture(Checks):
    """tools/fixtures/gamma_swatches.ms, saved with the gamma on: every swatch is its value, linear (s / 255)."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("gamma_swatches")

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def test_the_rule_is_read(self):
        self.assertIs(self.f.tex.swatches, colors.GAMMA_ON)
        self.assertIs(self.f.conv.swatches, colors.GAMMA_ON)

    def test_flat_swatches(self):
        ir = self.f.irs["FixtureGammaFlat"]
        self.close(ir.base_color.value, (128 / 255,) * 3, "diffuse 128 -> 0.502")
        self.close(ir.specular.value, 64 / 255, "reflection 64: its mean")
        self.close(ir.emission_color.value, (128 / 255,) * 3, "self-illumination 128")

    def test_map_swatches(self):
        ir = self.f.irs["FixtureGammaMapped"]
        self.close(ir.base_color.value, (10 / 255, 20 / 255, 30 / 255))
        mix = ir.textures["base_color"].root
        self.assertIsInstance(mix, tx.Mix)
        self.close(mix.a.value, (128 / 255,) * 3, "Mix color 1")
        self.close(mix.b.value, (64 / 255, 128 / 255, 192 / 255), "Mix color 2")
        self.close(mix.factor, 0.25)
        self.close(ir.textures["specular"].root.value, (128 / 255,) * 3, "VRayColor 128 -> 0.502")

    def test_standard(self):
        self.close(self.f.irs["FixtureGammaStandard"].base_color.value, (200 / 255, 40 / 255, 30 / 255))


if __name__ == "__main__":
    unittest.main()
