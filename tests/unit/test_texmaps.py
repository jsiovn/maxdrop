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
import dataclasses
import importlib
import json
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
classdir = importlib.import_module(_PKG + ".reader.classdir")
classids = importlib.import_module(_PKG + ".reader.classids")
pblock = importlib.import_module(_PKG + ".reader.pblock")
reader_materials = importlib.import_module(_PKG + ".reader.materials")
reader_scene = importlib.import_module(_PKG + ".reader.scene")
controllers_mod = importlib.import_module(_PKG + ".reader.controllers")
params_mod = importlib.import_module(_PKG + ".convert.params")

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


class _Swatch:
    """A material whose parameter (pid, block id) reads value, the rest as saved."""

    def __init__(self, m, key, value):
        self._m, self._key, self._value = m, key, value

    def __getattr__(self, name):
        return getattr(self._m, name)

    def param(self, pid, block_id=None, tab=0, default=None):
        return self._value if (pid, block_id) == self._key else self._m.param(pid, block_id, tab, default)


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
        fo = t["base_color"].root  # Falloff, perpendicular / parallel: map 1 to color 2
        self.assertIsInstance(fo, tx.Mix)
        self.assertEqual(fo.mask, tx.Facing(tx.PERPENDICULAR, 1.6))
        self.image(fo.a, "peel_diffuse.png", tx.SRGB)
        self.close(fo.b.value, tuple(_lin(c) for c in (10, 20, 30)))
        self.image(t["specular"].root.b, "peel_reflect.png", tx.SRGB)  # VRayDirt, at 80 %
        self.close(t["specular"].root.factor, 0.8)
        self.assertIsInstance(t["roughness"].root, tx.Invert)  # Output, a glossiness map
        self.image(t["roughness"].root.input, "peel_gloss.png", tx.NON_COLOR)
        self.assertIsInstance(t["bump"].root, tx.Bump)  # VRayColor2Bump: a height map
        self.close(t["bump"].root.strength, 0.4)
        self.image(t["bump"].root.input, "peel_height.png", tx.NON_COLOR)
        self.image(t["alpha"].root, "peel_opacity.png", tx.NON_COLOR)  # RGB Tint, its identity
        for name in ("specular", "bump"):
            self.assertTrue(t[name].approximated, name)
        for name in ("base_color", "roughness", "alpha", "metallic", "emission_color"):
            self.assertFalse(t[name].approximated, name)

    def test_peels_are_counted_once_per_map(self):
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter({"VRayDirt": 1, "VRayColor2Bump": 1}))
        self.assertEqual(self.f.tex.stats.unsupported, collections.Counter())

    def test_falloff_without_a_map_is_its_colors(self):
        t = self.f.irs["FixtureTexPeel"].textures
        g = t["metallic"].root  # a data input: the mean of each swatch as stored, the gamma is off (em3.122)
        self.close((g.a.value, g.b.value), ((200 + 100 + 50) / 3.0 / 255.0, 1.0))
        g = t["emission_color"].root  # map1 switched off: color1
        self.close(g.a.value, (1.0, 0.0, 0.0))
        self.close(g.b.value, (1.0, 1.0, 1.0))
        self.assertIsInstance(g.mask, tx.Facing)

    def test_kept_wrappers(self):
        t = self.f.irs["FixtureTexKeep"].textures
        decoded = t["base_color"].root  # gamma off: mixed on the stored values, shown decoded (em3.158)
        self.assertIsInstance(decoded, tx.Decode)
        mix = decoded.input
        self.assertIsInstance(mix, tx.Mix)
        self.close(mix.factor, 0.3)
        self.image(mix.a, "keep_mix_a.png", tx.NON_COLOR)  # Bitmaps as stored
        self.image(mix.b, "keep_mix_b.png", tx.NON_COLOR)
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
        self.close(reader_materials.bitmap_gamma(self.f.scene, self.f.graph.get(g.input.index)), 1.0)
        self.assertIsNone(g.input.gamma, "saved with the gamma off: read as stored whatever the override")

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
        self.assertIsInstance(c, tx.Decode)  # gamma off: composited on the stored values (em3.158)
        c = c.input
        self.assertIsInstance(c, tx.Composite)
        self.assertEqual([la.node.name for la in c.layers], ["place_comp_a.png", "place_comp_b.png"])
        self.close(tuple(la.opacity for la in c.layers), (1.0, 0.6))
        self.assertEqual([(la.blend, la.mask) for la in c.layers], [(0, None), (0, None)])

    def test_crop_channel_mirror_angles_gamma(self):
        i = self.f.irs["FixtureTexPlace"].textures["specular"].root
        self.image(i, "place_crop.png", tx.SRGB, (2.0, 3.0), (0.0, 0.0), 30.0, channel=3)
        self.close(i.mapping.angle, (10.0 * DEG, 20.0 * DEG, 30.0 * DEG))
        self.assertEqual(i.mapping.tile, (False, False))  # U mirrors (not tiles), V tiling off
        self.assertEqual(i.mapping.mirror, (True, False))
        self.assertEqual(i.mapping.source, tx.EXPLICIT)
        self.close((i.crop.u, i.crop.v, i.crop.w, i.crop.h), (0.1, 0.2, 0.5, 0.6))
        self.assertFalse(i.crop.place)
        self.close(reader_materials.bitmap_gamma(self.f.scene, self.f.graph.get(i.index)), 2.2)
        self.assertIsNone(i.gamma, "saved with the gamma off: read as stored whatever the override")

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

    def __len__(self):
        return max(list(self.objects) + list(self.chunks), default=-1) + 1

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

    def controller(self, i):
        return None


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


def _falloff(index, map1=None, color1=(0.5, 0.5, 0.5), ftype=1, name="map"):
    return FakeMap(index, tx.FALLOFF, {0: color1, 2: Ref(map1), 3: 1, 8: ftype}, [map1] if map1 is not None else [],
                   cls="Falloff", name=name)


def _table():
    return assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\a.png", "")])


def _tex(*objects, table=None):
    return tx.TexmapConverter(FakeGraph(*objects), _table() if table is None else table)


class Synthetic(Checks):
    def test_colorspace(self):
        self.assertEqual(tx.colorspace(tx.COLOR, None), tx.SRGB)
        self.assertEqual(tx.colorspace(tx.COLOR, 2.2), tx.SRGB)
        self.assertEqual(tx.colorspace(tx.COLOR, 1.0), tx.LINEAR)  # linear: the builder applies no gamma
        self.assertEqual(tx.colorspace(tx.COLOR, 1.8), tx.LINEAR)  # the builder applies 1.8
        self.assertEqual(tx.LINEAR, "Linear Rec.709")  # a Blender color space name: the builder sets it
        for kind in (tx.NORMAL, tx.BUMP):  # as a data input (maxdrop-em3.159)
            for gamma in (None, 2.2, 1.0, 1.8):
                self.assertEqual(tx.colorspace(kind, gamma, True), tx.NON_COLOR)
                self.assertEqual(tx.colorspace(kind, gamma), tx.colorspace(tx.DATA, gamma))
            self.assertEqual(tx.colorspace(kind, None), tx.SRGB)
            self.assertEqual(tx.colorspace(kind, 1.0), tx.NON_COLOR)
        for kind in (tx.DATA, tx.MASK):  # decoded by its gamma, as a color; read as linear: Non-Color
            for gamma in (None, 2.2, 1.8):
                self.assertEqual(tx.colorspace(kind, gamma), tx.colorspace(tx.COLOR, gamma))
            self.assertEqual(tx.colorspace(kind, 1.0), tx.NON_COLOR)
        self.assertEqual(tx.colorspace(tx.DATA, None, True), tx.NON_COLOR, "pixels as stored: data as they are")
        self.assertEqual(tx.colorspace(tx.MASK, None, True), tx.SRGB, "a mask in a color graph: decoded")

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
            self.assertEqual((g.root.gamma, g.root.colorspace), (1.0, tx.LINEAR), path)
        table = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.exr", "")])
        for info, gamma, space in ((_info(2.2, 5), 2.2, tx.SRGB), (_info(1.8, 5), 1.8, tx.LINEAR),
                                   (_info(2.2, 4), 1.0, tx.LINEAR),  # an override is kept; no flag: automatic
                                   (_info(50.0, 5), 1.0, tx.LINEAR)):  # out of range: automatic
            b, chunk_map = _placed(info=info)
            g = tx.TexmapConverter(FakeGraph(b, chunk_map=chunk_map), table).convert(mat.MapRef(1), tx.COLOR)
            self.close(g.root.gamma, gamma)
            self.assertEqual(g.root.colorspace, space, info.hex())
        g = _tex(_bitmap(1), table=table).convert(mat.MapRef(1), tx.DATA)
        self.assertEqual(g.root.colorspace, tx.NON_COLOR)  # read as linear: a data input takes it as it is
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

    def test_composite_with_a_mask(self):
        comp = FakeMap(1, tx.COMPOSITE, {1: [1, 1], 3: [1, 1], 5: [0, 0], 8: [100.0, 50.0], 9: [Ref(2), Ref(3)],
                                         10: [Ref(None), Ref(4)]}, [2, 3, 4], cls="Composite")
        tex = _tex(comp, _bitmap(2), _bitmap(3), _bitmap(4))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Composite)
        self.assertFalse(g.approximated)
        bottom, top = g.root.layers
        self.assertIsNone(bottom.mask)
        self.assertEqual((top.opacity, top.blend), (0.5, 0))
        self.assertEqual(top.mask.colorspace, tx.SRGB, "a mask in a color graph: decoded by its gamma")
        self.assertEqual(tex.stats.peeled, collections.Counter())
        comp = FakeMap(1, tx.COMPOSITE, {3: [1, 0], 9: [Ref(2), Ref(3)], 10: [Ref(None), Ref(4)]}, [2, 3, 4])
        g = _tex(comp, _bitmap(2), _bitmap(3), _bitmap(4)).convert(mat.MapRef(1), tx.COLOR)
        self.assertIsNone(g.root.layers[1].mask, "mask switched off")
        comp = FakeMap(1, tx.COMPOSITE, {9: [Ref(2), Ref(3)], 10: [Ref(None), Ref(5)]}, [2, 3, 5], cls="Composite",
                       name="cp")
        tex = _tex(comp, _bitmap(2), _bitmap(3), _noise(5))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsNone(g.root.layers[1].mask, "a lost mask: the opacity alone")
        self.assertTrue(g.approximated)
        self.assertTrue(any("converts to nothing" in r for _i, r in tex.stats.issues))

    def test_composite_blend_modes(self):
        for mode in sorted(tx.BLENDS):
            comp = FakeMap(1, tx.COMPOSITE, {5: [14, mode], 9: [Ref(2), Ref(3)]}, [2, 3], cls="Composite")
            tex = _tex(comp, _bitmap(2), _bitmap(3))
            g = tex.convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual([la.blend for la in g.root.layers], [tx.NORMAL_BLEND, mode], "the bottom one is normal")
            self.assertEqual(tex.stats.peeled, collections.Counter())
        for mode in (tx.LINEAR_BURN, tx.SOFT_LIGHT, tx.PIN_LIGHT, tx.HARD_MIX, 25):
            comp = FakeMap(1, tx.COMPOSITE, {5: [0, mode], 9: [Ref(2), Ref(3)]}, [2, 3], cls="Composite")
            tex = _tex(comp, _bitmap(2), _bitmap(3))
            g = tex.convert(mat.MapRef(1), tx.COLOR)
            self.assertIsInstance(g.root, tx.Image, mode)
            self.assertEqual(tex.stats.peeled, collections.Counter({"Composite": 1}))

    def test_falloff_types_and_amounts(self):
        fo = FakeMap(1, tx.FALLOFF, {0: (0.0, 0.0, 0.0), 1: 60.0, 2: Ref(2), 3: 1, 4: (1.0, 1.0, 1.0), 5: 100.0,
                                     6: Ref(3), 7: 1, 8: 2, 9: 0, 11: 1, 12: 1.5}, [2, 3], cls="Falloff")
        tex = _tex(fo, _bitmap(2), _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertFalse(g.approximated)
        self.assertEqual(g.root.mask, tx.Facing(tx.FRESNEL, 1.5))
        self.close(g.root.factor, 0.0)
        side1, side2 = g.root.a, g.root.b
        self.assertIsInstance(side1, tx.Mix, "map amount 60: lerp(color 1, map 1, 0.6)")
        self.close(side1.factor, 0.6)
        self.close(side1.a.value, (0.0, 0.0, 0.0))
        self.assertIsInstance(side1.b, tx.Image)
        self.assertIsInstance(side2, tx.Image, "map amount 100: the map")
        for ftype, mode in ((0, tx.TOWARDS), (1, tx.PERPENDICULAR), (None, tx.PERPENDICULAR)):
            fo = FakeMap(1, tx.FALLOFF, {8: ftype}, cls="Falloff")
            self.assertEqual(_tex(fo).convert(mat.MapRef(1), tx.COLOR).root.mask, tx.Facing(mode, 1.6))
        fo = FakeMap(1, tx.FALLOFF, {8: 2, 11: 0, 12: 1.3}, cls="Falloff", name="f")
        tex = _tex(fo)
        self.assertEqual(tex.convert(mat.MapRef(1), tx.COLOR).root.mask, tx.Facing(tx.FRESNEL, 1.3))
        self.assertEqual([r for _i, r in tex.stats.issues], ["Falloff 'f': the material's IOR not read: its own, 1.3"])
        fo = FakeMap(1, tx.FALLOFF, {8: 2, 12: float("nan")}, cls="Falloff")
        self.assertEqual(_tex(fo).convert(mat.MapRef(1), tx.COLOR).root.mask, tx.Facing(tx.FRESNEL, 1.6))

    def test_falloff_in_a_reflection_slot(self):
        # the usual Fresnel-like reflection: a default Falloff, black to white, no maps, converted as texture_graphs
        # converts a specular input (a color graph, the input's own value a float)
        tex = _tex(FakeMap(1, tx.FALLOFF, {}, cls="Falloff"))
        g = tex.convert(mat.MapRef(1), tx.COLOR, 0.0)
        black, white = tx.Constant((0.0, 0.0, 0.0)), tx.Constant((1.0, 1.0, 1.0))
        self.assertEqual(g.root, tx.Mix(black, white, 0.0, tx.Facing(tx.PERPENDICULAR)))
        self.assertEqual((g.approximated, g.issues), (False, ()))
        self.assertEqual((tex.stats.peeled, tex.stats.unsupported), (collections.Counter(), collections.Counter()))
        tex = _tex(FakeMap(1, tx.FALLOFF, {8: 2, 11: 1, 12: 1.5}, cls="Falloff"))
        g = tex.convert(mat.MapRef(1, amount=0.5), tx.COLOR, 0.0)
        self.assertEqual(g.root, tx.Mix(black, tx.Mix(black, white, 0.0, tx.Facing(tx.FRESNEL, 1.5)), 0.5))
        self.assertEqual((g.approximated, g.issues, tex.stats.peeled), (False, (), collections.Counter()))

    def test_falloff_other_types_and_directions_are_peeled(self):
        for params in ({8: 3}, {8: 4}, {8: 1, 9: 1}, {8: 7}):
            fo = FakeMap(1, tx.FALLOFF, {**params, 0: (1.0, 0.0, 0.0), 2: Ref(2), 3: 1}, [2], cls="Falloff")
            tex = _tex(fo, _bitmap(2))
            g = tex.convert(mat.MapRef(1), tx.COLOR)
            self.assertIsInstance(g.root, tx.Image, params)
            self.assertTrue(g.approximated)
            self.assertEqual(tex.stats.peeled, collections.Counter({"Falloff": 1}))
            self.assertTrue(any("drawn as its first side" in r for r in g.issues))
            fo = FakeMap(1, tx.FALLOFF, {**params, 0: (1.0, 0.0, 0.0)}, cls="Falloff")
            self.close(_tex(fo).convert(mat.MapRef(1), tx.COLOR).root.value, (1.0, 0.0, 0.0), "no map: color 1")

    def test_falloff_as_a_mask(self):
        fo = FakeMap(2, tx.FALLOFF, {}, cls="Falloff")
        mix = FakeMap(1, tx.MIX, {6: Ref(3), 7: Ref(4), 8: Ref(2)}, [2, 3, 4], cls="Mix")
        g = _tex(mix, fo, _bitmap(3), _bitmap(4)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.mask, tx.Mix(tx.Constant(0.0), tx.Constant(1.0), 0.0, tx.Facing()))

    def test_color_correction_rewiring(self):
        for params, want in (({2: 1}, tx.REWIRE_MONO), ({2: 2}, tx.REWIRE_INVERT), ({2: 0, 3: 2}, tx.REWIRE_NONE),
                             ({2: 3, 3: 2, 4: 1, 5: 0}, (2, 1, 0)), ({2: 3, 3: 8, 4: 9, 5: 10}, (8, 9, 10))):
            cc = FakeMap(1, tx.COLOR_CORRECTION, {**params, 1: Ref(2)}, [2], cls="Color Correction")
            g = _tex(cc, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual(g.root.rewire, want, params)
            self.assertFalse(g.approximated, params)
        cc = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 2: 3, 3: 3, 4: 7, 5: 2}, [2], name="cc")
        g = _tex(cc, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.rewire, (9, 10, 2), "alpha drawn as one, its inverse as zero")
        self.assertTrue(g.approximated)
        self.assertTrue(any("from alpha" in r for r in g.issues))
        for params in ({2: 3, 3: (2872,), 4: 1, 5: 2}, {2: 3, 3: 11, 4: 1, 5: 2}, {2: 5}):
            cc = FakeMap(1, tx.COLOR_CORRECTION, {**params, 1: Ref(2)}, [2], name="cc")
            g = _tex(cc, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual(g.root.rewire, tx.REWIRE_NONE, params)
            self.assertTrue(any("rewiring" in r for r in g.issues), params)

    def test_output_and_rgb_tint(self):
        out = FakeMap(1, tx.OUTPUT, {0: Ref(2)}, [2], cls="Output")
        part = FakeMap(5, (0x100, 0), superclass=classids.SC_TEXOUTPUT)
        part.legacy = {0: {0: 2.0, 1: 0.1, 2: 0.5}}
        out.parts = {2: part}
        g = _tex(out, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Adjust)
        self.assertEqual(g.root.output, tx.TexOutput(False, 0.5, 2.0, 0.1))
        self.assertFalse(g.approximated)
        tint = FakeMap(1, tx.RGB_TINT, {0: (1.0, 0.5, 0.0), 3: Ref(2)}, [2], cls="RGB Tint")
        tex = tx.TexmapConverter(FakeGraph(tint, _bitmap(2)), _table(), swatches=colors.GAMMA_ON)
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root, tx.Tint(g.root.input, (1.0, 0.5, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
        self.assertEqual((g.approximated, tex.stats.peeled), (False, collections.Counter()))
        tint = FakeMap(1, tx.RGB_TINT, {3: Ref(2)}, [2], cls="RGB Tint")
        self.assertIsInstance(_tex(tint, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR).root, tx.Image,
                              "the identity: the map")

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

    def test_slot_scale(self):
        """MapRef.scale (Standard's Diffuse Level on a diffuse map) multiplies the map before the amount mixes it with
        the input's value; 1 leaves the graph as it was."""
        tex = _tex(_bitmap(1))
        g = tex.convert(mat.MapRef(1, 1.0, False, 0.5), tx.COLOR, (0.4, 0.2, 0.1))
        self.assertEqual(g.root, tx.Multiply(g.root.a, tx.Constant((0.5, 0.5, 0.5))))
        self.assertIsInstance(g.root.a, tx.Image)
        g = tex.convert(mat.MapRef(1, 0.25, False, 0.5), tx.COLOR, (0.4, 0.2, 0.1))
        self.assertEqual((g.root.a, g.root.factor), (tx.Constant((0.4, 0.2, 0.1)), 0.25))
        self.assertEqual(g.root.b, tx.Multiply(g.root.b.a, tx.Constant((0.5, 0.5, 0.5))))
        self.assertEqual(tex.convert(mat.MapRef(1, 0.25, False, 1.0), tx.COLOR, (0.4, 0.2, 0.1)),
                         tex.convert(mat.MapRef(1, 0.25), tx.COLOR, (0.4, 0.2, 0.1)))

    def level_ir(self, diffuse, level_map, level=0.25, color=(0.8, 0.4, 0.2)):
        ir = mat.MaterialIR(0, "S", base_color=mat.Input(tuple(c * level for c in color), diffuse))
        ir.diffuse_level = mat.DiffuseLevel(color, level, level_map)
        return ir

    def test_diffuse_level_map(self):
        """A Diffuse Level map (maxdrop-em3.150): base color = the diffuse at level 1 times the mean of
        lerp(level, the map, its amount); each side kept over its constant where its images are missing."""
        mean = (1.0 / 3.0,) * 3
        tex = _tex(_bitmap(1), _bitmap(2, G1))
        ir = self.level_ir(mat.MapRef(1, 0.5, False, 0.25), mat.MapRef(2, 0.6))
        g = tx.texture_graphs(ir, tex)["base_color"]
        self.assertEqual(g.kind, tx.COLOR)
        d, f = g.root.a, g.root.b
        self.assertIsInstance(g.root, tx.Multiply)
        self.assertEqual((d.a, d.factor), (tx.Constant((0.8, 0.4, 0.2)), 0.5), "the diffuse at level 1")
        self.assertIsInstance(d.b, tx.Image, "no scale under the level map")
        self.assertEqual((f.red, f.green, f.blue), (mean, mean, mean))
        self.assertEqual((f.input.a, f.input.factor), (tx.Constant(0.25), 0.6))
        self.assertIsInstance(f.input.b, tx.Image)
        self.assertEqual(f.input.b.colorspace, tx.SRGB, "a mask: decoded with the gamma off")
        # full amounts: each bare map kept over its constant by a Mix at factor 1
        ir = self.level_ir(mat.MapRef(1, 1.0, False, 0.25), mat.MapRef(2, 1.0))
        g = tx.texture_graphs(ir, tex)["base_color"]
        self.assertEqual((g.root.a.a, g.root.a.factor), (tx.Constant((0.8, 0.4, 0.2)), 1.0))
        self.assertEqual((g.root.b.input.a, g.root.b.input.factor), (tx.Constant(0.25), 1.0))
        # no diffuse map: the swatch at level 1
        g = tx.texture_graphs(self.level_ir(None, mat.MapRef(2, 1.0)), tex)["base_color"]
        self.assertEqual(g.root.a, tx.Constant((0.8, 0.4, 0.2)))
        # a level map that gives no graph: the diffuse map times the level, as without it
        tex = _tex(_bitmap(1), FakeMap(2, (0x1234, 0), cls="Unknown"))
        ir = self.level_ir(mat.MapRef(1, 0.5, False, 0.25), mat.MapRef(2, 1.0))
        self.assertEqual(tx.texture_graphs(ir, tex)["base_color"], tex.convert(ir.base_color.map, tx.COLOR,
                                                                               ir.base_color.value))
        self.assertNotIn("base_color", tx.texture_graphs(self.level_ir(None, mat.MapRef(2, 1.0)), tex))

    def test_diffuse_level_map_past_max_nodes(self):
        """A product past MAX_NODES keeps the diffuse graph without the level map, with an issue (on the graph and
        once in stats)."""
        tex = _tex(_bitmap(1), _bitmap(2))
        big = tx.Image(1, "a.png")
        for _ in range(tx.MAX_NODES - 2):
            big = tx.Invert(big)
        plain = tx.TextureGraphIR(big, tx.COLOR)
        real = tex.convert

        def convert(ref, kind, value=None):
            return plain if kind == tx.COLOR else real(ref, kind, value)

        tex.convert = convert
        ir = self.level_ir(mat.MapRef(1, 1.0), mat.MapRef(2, 1.0))
        g = tx.texture_graphs(ir, tex)["base_color"]
        self.assertIs(g.root, big, "the diffuse alone")
        reason = "map 2: Diffuse Level map left out: the base color graph would be past %d nodes" % tx.MAX_NODES
        self.assertEqual(g.issues, (reason,))
        tx.texture_graphs(ir, tex)
        self.assertEqual(tex.stats.issues.count((2, reason)), 1)

    def test_normal_map_in_a_color_input_is_its_image(self):
        n = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(2), 2: 1, 3: 1.0}, [2], cls="VRayNormalMap")
        tex = _tex(n, _bitmap(2))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Image)
        self.assertEqual(g.root.colorspace, tx.SRGB)  # read as a normal image below its class: decoded, gamma on
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
        tex = _tex(_falloff(1, 2, ftype=3), _bitmap(2))
        tex.convert(mat.MapRef(1), tx.COLOR)
        tex.convert(mat.MapRef(1, 0.5), tx.DATA, 0.0)
        self.assertEqual(tex.stats.peeled, collections.Counter({"Falloff": 1}))

    def test_texture_graphs_of_an_ir(self):
        tex = _tex(_bitmap(1))
        ir = mat.MaterialIR(0, "M", base_color=mat.Input((0.1, 0.2, 0.3), mat.MapRef(1)), bump=mat.MapRef(1, 0.3))
        graphs = tx.texture_graphs(ir, tex)
        self.assertEqual(sorted(graphs), ["base_color", "bump"])
        self.assertEqual(graphs["base_color"].root.colorspace, tx.SRGB)
        self.assertEqual(graphs["bump"].root.input.colorspace, tx.SRGB)  # gamma on: decoded (maxdrop-em3.159)


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
        self.assertIsInstance(g.root, tx.Mix)  # the material's map amount over its color
        self.close(g.root.factor, 0.75)
        self.close(g.root.a.value, tuple(_lin(c) for c in (150, 140, 130)))
        image = g.root.b
        self.image(image, "fixture_c_base.png", tx.LINEAR, tiling=(2.0, 3.0), offset=(0.1, 0.2), w_angle=30.0,
                   channel=2)
        self.assertEqual((image.mapping.tile, image.mapping.mirror), ((True, False), (True, False)))
        self.close(image.mapping.blur, 0.8)
        self.assertEqual((image.crop, image.output, image.alpha), (None, None, False))
        self.close(image.gamma, tx.SRGB_TWICE, "gamma off: its own decode shown decoded (maxdrop-em3.165)")
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def test_glossiness_bitmap_with_gamma_1(self):
        g = self.f.irs["FixtureCoronaMaps"].textures["roughness"]
        self.close(g.root.factor, 0.6)
        self.close(g.root.a.value, 0.4)
        self.assertIsInstance(g.root.b, tx.Invert)
        self.image(g.root.b.input, "fixture_c_gloss.png", tx.NON_COLOR)  # gamma 1.0: as stored
        self.close(g.root.b.input.gamma, 1.0)

    def test_placed_opacity_gives_its_alpha(self):
        image = self.f.irs["FixtureCoronaMaps"].textures["alpha"].root
        self.image(image, "fixture_c_opacity.png", tx.SRGB)  # CoronaBitmap: its own 2.2 also with the gamma off
        self.close((image.crop.u, image.crop.v, image.crop.w, image.crop.h), (0.1, 0.2, 0.5, 0.6))
        self.assertTrue(image.crop.place)
        self.assertTrue(image.alpha)

    def test_corona_normal_in_bump(self):
        n = self.f.irs["FixtureCoronaMaps"].textures["normal"].root
        self.assertIsInstance(n, tx.NormalMap)
        self.close(n.strength, 0.8 * 0.9)
        self.assertTrue(n.flip_green)
        self.image(n.input, "fixture_c_normal.png", tx.SRGB)  # CoronaBitmap auto: its own 2.2 (maxdrop-em3.159)
        self.close(n.bump.strength, 0.3 * 0.9)
        self.image(n.bump.input, "fixture_c_normal_bump.png", tx.SRGB)

    def test_corona_color_is_a_constant(self):
        root = self.f.irs["FixtureCoronaMaps"].textures["metallic"].root
        self.close(root.value, 150 / 255.0, "a data input: the mean of the swatch as stored")

    def test_corona_mix_with_a_mask(self):
        root = self.f.irs["FixtureCoronaMaps"].textures["emission_color"].root
        self.assertIsInstance(root, tx.Decode)
        root = root.input
        self.assertIsInstance(root, tx.Mix)
        self.close(root.factor, 0.4)
        self.close(root.a.value, tuple(c / 255.0 for c in (10, 20, 30)), "the bottom color as stored")
        self.image(root.b, "fixture_c_top.png", tx.SRGB)  # its own decode
        self.image(root.mask, "fixture_c_mask.png", tx.SRGB)  # a data mask: its own decode

    def test_legacy_slots(self):
        t = self.f.irs["FixtureCoronaLegacyMaps"].textures
        self.assertIsInstance(t["base_color"].root, tx.Decode)
        self.assertIsInstance(t["base_color"].root.input, tx.Multiply)
        self.image(t["base_color"].root.input.a, "fixture_c_mul_bottom.png", tx.SRGB)
        self.image(t["base_color"].root.input.b, "fixture_c_mul_top.png", tx.SRGB)
        self.assertIsInstance(t["roughness"].root, tx.Invert)
        self.image(t["roughness"].root.input, "fixture_c_legacy_gloss.png", tx.SRGB)
        self.assertIsInstance(t["bump"].root, tx.Bump)
        self.close(t["bump"].root.strength, 0.5)
        self.close(t["alpha"].root.value, 0.5, "HDR color 0.25 0.5 0.75, linear: the mean")
        self.assertNotIn("emission_color", t)

    def test_add_is_a_blend_in_gamma_space(self):
        g = self.f.irs["FixtureCoronaLegacyMaps"].textures["specular"]
        self.assertIsInstance(g.root, tx.Decode)
        blend = g.root.input
        self.assertIsInstance(blend, tx.Blend)
        self.assertEqual((blend.op, blend.gamma), (tx.BLEND_ADD, 2.2), "mix in sRGB: on by default")
        self.close(blend.a.value, (0.0, 0.0, 0.0), "the bottom color, black")
        self.image(blend.b, "fixture_c_add_top.png", tx.SRGB)
        self.assertFalse(g.approximated)
        self.assertEqual(g.issues, ())
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter())
        self.assertEqual(self.f.tex.stats.unsupported, collections.Counter())
        self.assertEqual(self.f.tex.stats.issues, [])

    def test_light_maps(self):
        f = Fixture("corona_light")
        try:
            t = f.irs["FixtureCoronaLight"].textures
            self.image(t["emission_color"].root, "fixture_c_light.png", tx.LINEAR)  # gamma off: shown decoded
            self.close(t["emission_color"].root.gamma, tx.SRGB_TWICE)
            self.image(t["alpha"].root, "fixture_c_light_alpha.png", tx.SRGB)
            self.assertEqual(f.irs["FixtureCoronaLightPlain"].textures, {})
        finally:
            f.close()


class CoronaMixOps(Checks):
    """tools/fixtures/corona_mix_ops.ms: top 200 100 50, bottom 60 120 180. The gamma is off: Corona 12 computes a
    CoronaMix on the swatches as stored, the same in both modes, and the scene shows the result decoded (a folded
    constant decoded exactly; maxdrop-em3.165)."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("corona_mix_ops")
        cls.top = tuple(c / 255.0 for c in (200, 100, 50))
        cls.bottom = tuple(c / 255.0 for c in (60, 120, 180))

    @staticmethod
    def shown(rgb):
        return tuple(colors.srgb_to_linear(c) for c in rgb)

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def root(self, name):
        g = self.f.irs["FixtureCoronaMix" + name].textures["base_color"]
        self.assertFalse(g.approximated, name)
        self.assertEqual(g.issues, (), name)
        return g.root

    def test_operations(self):
        for name, op, gamma in (("Add", tx.BLEND_ADD, 2.2), ("Subtract", tx.BLEND_SUBTRACT, 2.2),
                                ("Divide", tx.BLEND_DIVIDE, 1.0), ("Min", tx.BLEND_MIN, 1.0),
                                ("Max", tx.BLEND_MAX, 1.0), ("Difference", tx.BLEND_DIFFERENCE, 2.2),
                                ("AddLinear", tx.BLEND_ADD, 1.0)):
            with self.subTest(name):
                self.close(self.root(name).value, self.shown(tx.blend_value(op, self.bottom, self.top, gamma)))

    def test_layer_multipliers_and_offsets(self):
        root = self.root("Scaled")
        self.assertIsInstance(root, tx.Constant, "a Mix of constants, folded")
        a = tuple(c * 2.0 + 0.01 for c in self.bottom)  # x 2, offset -0.1
        b = tuple(c * 0.5 - 0.02 for c in self.top)  # x 0.5, offset 0.2
        self.close(root.value, self.shown(tuple(x + (y - x) * 0.75 for x, y in zip(a, b))))

    def test_masked_subtract(self):
        root = self.root("Masked")
        self.assertIsInstance(root, tx.Constant, "a Mix of constants by a constant mask, folded")
        f = 64 / 255.0  # the mask replaces the amount: its stored value, a data mask
        sub = tx.blend_value(tx.BLEND_SUBTRACT, self.bottom, self.top, 2.2)
        self.close(root.value, self.shown(tuple(x + (y - x) * f for x, y in zip(self.bottom, sub))))

    def test_temperatures(self):
        for k in (2000, 3000, 9000):
            g = self.f.irs["FixtureCoronaKelvin%d" % k].textures["base_color"]
            self.close(g.root.value, colors.GAMMA_OFF.color(tx.corona_kelvin(k)), "saved with the gamma off: %d" % k)
        self.close(tx.corona_kelvin(3000), (1.0, 121.607 / 255, 39.1868 / 255))

    def test_nothing_peeled(self):
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter())
        self.assertEqual(self.f.tex.stats.issues, [])


class CoronaMixBlends(Checks):
    """tools/fixtures/corona_mix_blends.ms: CoronaColor HDR layers (no swatch decode), so the IR is compared with
    renderMap of the saved file in 3ds Max 2020 + Corona 12 (maxdrop-em3.117, read through (v + 4) x 0.05: within
    3e-4; Corona's sRGB mode renders 1 as 0.998): the value Corona holds, the same with the gamma on and off, which
    the gamma-off fixture shows decoded (maxdrop-em3.165)."""
    RENDERMAP = {  # box -> renderMap of its base map
        "Screen": (0.691844, 0.651865, 0.987258), "Overlay": (0.137636, 0.383001, 0.974746),
        "ColorDodge": (0.999771, 0.999771, 0.999771), "ColorBurn": (0.00213623, 0.0665293, 0.886549),
        "LinearBurn": (0.0012207, 0.0131226, 0.664988), "LinearLight": (0.68452, 0.351263, 3.24804),
        "HardLight": (0.444343, 0.367437, 0.974746), "Exclusion": (0.378119, 0.223392, 0.0170903),
        "LinearLightLinear": (0.249943, -0.200198, 1.39986), "LinearBurnLinear": (0.0, 0.0, 0.649729),
        "LinearLightDark": (0.998245, 0.000915527, 0.0), "Gamma": (0.01648, 0.284733, 0.865491)}

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("corona_mix_blends")

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def root(self, name):
        g = self.f.irs["FixtureCoronaMix" + name].textures["base_color"]
        self.assertFalse(g.approximated, name)
        self.assertEqual(g.issues, (), name)
        return g.root

    def test_folded_as_renderMap(self):
        for name, want in self.RENDERMAP.items():
            with self.subTest(name):
                root = self.root(name)
                self.assertIsInstance(root, tx.Constant)
                for ours, theirs in zip(root.value, want):  # ours encoded back: the value Corona holds
                    self.assertAlmostEqual(colors.linear_to_srgb(ours), theirs, delta=2e-3, msg=name)

    def test_gamma_at_half_amount(self):
        root = self.root("GammaHalf")
        self.assertIsInstance(root, tx.Constant, "a Mix of constants, folded")
        for ours, theirs in zip(root.value, (0.0329595, 0.342412, 0.882582)):  # renderMap, shown decoded
            self.assertAlmostEqual(ours, colors.srgb_to_linear(theirs), delta=1e-3)

    def test_nothing_peeled(self):
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter())
        self.assertEqual(self.f.tex.stats.issues, [])


G2 = bytes(range(16, 32))


def _cbitmap(index, guid=G1, **params):
    p = {101: pblock.Asset(guid)}
    p.update({int(k[1:]): v for k, v in params.items()})
    return FakeMap(index, classids.CORONA_BITMAP, p, cls="CoronaBitmap")


def _ccolor(index, **params):
    return FakeMap(index, classids.CORONA_COLOR, {int(k[1:]): v for k, v in params.items()}, cls="CoronaColor")


# probe1's P5 layers (maxdrop-em3.117): bottom (0.2, 0.6, 0.3) and top (0.8, 0.1, 1.1), each with offset 3 (-0.3)
P5_BOTTOM, P5_TOP = (-0.1, 0.3, 0.0), (0.5, -0.2, 0.8)


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

    def test_corona_kelvin_is_coronas_own_table(self):
        self.close(tx.corona_kelvin(3000.0), (1.0, 121.607 / 255, 39.1868 / 255), "a measured point")
        self.close(tx.corona_kelvin(2750.0), (1.0, (94.9066 + 121.607) / 510, (17.214 + 39.1868) / 510), "between")
        self.assertEqual(tx.corona_kelvin(100.0), tx.corona_kelvin(1000.0))
        self.assertEqual(tx.corona_kelvin(1e6), tx.corona_kelvin(40000.0))
        for k, _rgb in tx.CORONA_KELVIN:
            self.close(max(tx.corona_kelvin(k)), 1.0, "the brightest channel 1 at %d K" % k)

    def test_corona_color_methods(self):
        cases = (
            (dict(p50=0, p52=(0.5, 0.5, 0.5), p57=2.0), (1.0, 1.0, 1.0)),
            (dict(p50=1, p58=(2.0, 0.5, 0.25), p57=1.0), (2.0, 0.5, 0.25)),
            (dict(p50=2, p51=3000.0, p57=0.5), tuple(0.5 * c for c in tx.corona_kelvin(3000.0))),  # linear
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
        tex = _tex(_cmix(1, [2], p200=6, p201=0.3, p206=Ref(2), p212=0, p202=2.0, p205=0.5), _cbitmap(2))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.b.value, (2.0, 2.0, 2.0), "top map off: the top color times its multiplier")
        self.close(g.root.a.value, (-0.05,) * 3, "the bottom color plus offset 0.5 x -0.1")
        self.assertFalse(g.approximated)
        self.assertEqual(g.issues, ())

    def test_corona_mix_layer_map_multiplier_is_an_adjust(self):
        tex = _tex(_cmix(1, [2], p200=6, p206=Ref(2), p202=0.5, p204=0.2), _cbitmap(2))
        root = tex.convert(mat.MapRef(1), tx.COLOR).root
        self.assertIsInstance(root.b, tx.Adjust)
        self.assertEqual(root.b.output, tx.TexOutput(level=0.5, offset=0.2 * tx.CM_OFFSET_SCALE))
        self.assertEqual(root.b.input.name, "a.png")

    def test_corona_mix_blends(self):
        top, bottom = (0.8, 0.4, 0.2), (0.25, 0.5, 0.75)
        self.assertEqual(sorted(tx.CM_BLENDS), [0, 1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14, 16, 20])
        self.assertEqual(set(tx.CM_BLENDS.values()) - set(tx.CM_GAMMA_OPS),
                         {tx.BLEND_DIVIDE, tx.BLEND_MIN, tx.BLEND_MAX}, "the same in both modes")
        for op, blend in tx.CM_BLENDS.items():
            for srgb in (1, 0):
                with self.subTest(op=op, srgb=srgb):
                    tex = _tex(_cmix(1, p200=op, p208=top, p209=bottom, p214=srgb))
                    gamma = 2.2 if srgb and blend in tx.CM_GAMMA_OPS else 1.0
                    root = tex.convert(mat.MapRef(1), tx.COLOR).root
                    self.close(root.value, tx.blend_value(blend, bottom, top, gamma), "two colors: folded")
                    tex = _tex(_cmix(1, [2], p200=op, p206=Ref(2), p209=bottom, p214=srgb), _cbitmap(2))
                    g = tex.convert(mat.MapRef(1), tx.COLOR)
                    self.assertIsInstance(g.root, tx.Blend)
                    self.assertEqual((g.root.op, g.root.gamma), (blend, gamma))
                    self.assertEqual(g.root.b.name, "a.png", "the top")
                    self.assertFalse(g.approximated)
                    self.assertEqual(g.issues, ())
        tex = _tex(_cmix(1, [2], p200=1, p201=0.5, p206=Ref(2), p209=bottom), _cbitmap(2))
        root = tex.convert(mat.MapRef(1), tx.COLOR).root
        self.assertIsInstance(root, tx.Mix)
        self.close(root.factor, 0.5)
        self.assertEqual((root.b.op, root.b.gamma), (tx.BLEND_SUBTRACT, 2.2))
        self.assertIs(root.a, root.b.a, "the bottom, shared")

    def test_blend_value(self):
        self.close(tx.blend_value(tx.BLEND_ADD, 50 / 255, 40 / 255, 2.2), 206.067 / 255, "renderMap: 206.086")
        self.close(tx.blend_value(tx.BLEND_ADD, 50 / 255, 40 / 255), 90 / 255)
        self.close(tx.blend_value(tx.BLEND_SUBTRACT, 0.2, 0.5, 2.2), 0.0, "floored at 0")
        self.close(tx.blend_value(tx.BLEND_DIVIDE, (0.4, 0.3), (0.5, 0.0)), (0.8, 0.3), "a where b is 0")
        self.close(tx.blend_value(tx.BLEND_DIFFERENCE, 0.2, 0.5), 0.3)
        self.close(tx.blend_value(tx.BLEND_MIN, 0.2, 0.5), 0.2)
        self.close(tx.blend_value(tx.BLEND_MAX, 0.2, 0.5), 0.5)
        self.close(tx.blend_value(tx.BLEND_ADD, -0.1, 0.25, 2.2), (0.1 ** (1 / 2.2) + 0.25 ** (1 / 2.2)) ** 2.2,
                   "Corona raises a negative layer's magnitude in sRGB mode (maxdrop-em3.161)")
        self.close(tx.blend_value(tx.BLEND_ADD, -0.1, 0.25), 0.15, "linear mode: the sign kept")
        self.assertTrue(math.isfinite(tx.blend_value(tx.BLEND_ADD, 1e308, 1e308, 2.2)), "no overflow")
        for op in tx.BLEND_OPS:
            for a, b in ((1e308, 1e-308), (-1e308, 1.0), (1.0, 1.0), (0.0, 0.0), (1e-320, -1e-320)):
                for gamma in (1.0, 2.2):
                    self.assertTrue(math.isfinite(tx.blend_value(op, a, b, gamma)), (op, a, b, gamma))

    def test_blend_value_as_renderMap(self):
        """renderMap of CoronaMix in 3ds Max 2020 + Corona 12 (maxdrop-em3.117): CoronaColor HDR layers bottom / top
        per channel, mixInSRgb on (2.2) and off; within 2e-3 (the probe reads within 3e-4, Corona's sRGB mode
        renders 1 as 0.998)."""
        cases = (
            (tx.BLEND_SCREEN, (0.25, 0.5, 1.5), (2.0, 0.5, 0.25), 1.0, (1.7499, 0.749828, 1.37484)),
            (tx.BLEND_SCREEN, (0.25, 0.5, 1.5), (2.0, 0.5, 0.25), 2.2, (1.42062, 0.846265, 1.21981)),
            (tx.BLEND_OVERLAY, (3.0, 2.0, 0.0), (1.5, 3.0, 2.0), 1.0, (-1.00008, -3.00023, 0.0)),
            (tx.BLEND_OVERLAY, (0.05, 0.4, 0.9), (0.6, 0.2, 0.75), 2.2, (0.137636, 0.383001, 0.974746)),
            (tx.BLEND_HARD_LIGHT, (0.25, 0.5, 1.5), (2.0, 0.5, 0.25), 1.0, (2.49973, 0.499886, 0.749828)),
            (tx.BLEND_DODGE, (0.25, 0.3, 0.0), (2.0, 1.0, 0.0), 1.0, (-0.250248, 0.999771, 0.0)),
            (tx.BLEND_DODGE, (0.25, 0.5, 1.5), (2.0, 0.5, 0.25), 2.2, (2.22507, 0.999771, 0.999771)),
            (tx.BLEND_BURN, (0.25, 0.5, 1.5), (2.0, 0.5, 0.25), 1.0, (0.624704, 0.0, 2.99992)),
            (tx.BLEND_BURN, (0.5, 0.2, 0.05), (0.0, 1.0, 0.6), 1.0, (0.0, 0.199893, 0.0)),
            (tx.BLEND_LINEAR_BURN, (0.05, 0.4, 0.9), (0.6, 0.2, 0.75), 1.0, (0.0, 0.0, 0.649729)),
            (tx.BLEND_LINEAR_BURN, (3.0, 2.0, 0.0), (1.5, 3.0, 2.0), 2.2, (3.87091, 4.68635, 0.112307)),
            (tx.BLEND_LINEAR_LIGHT, (3.0, 2.0, 0.0), (1.5, 3.0, 2.0), 1.0, (4.99977, 6.99992, 2.99992)),
            (tx.BLEND_LINEAR_LIGHT, (0.0, 0.05, 0.2), (0.0, 0.1, 0.05), 2.2, (0.998245, 0.000915527, 0.0)),
            (tx.BLEND_EXCLUSION, (2.0, 1.0, 0.0), (2.0, 1.0, 0.0), 2.2, (1.03243, 0.0, 0.0)),
            (tx.BLEND_EXCLUSION, (0.25, 0.5, 1.5), (2.0, 0.5, 0.25), 1.0, (1.24971, 0.499886, 0.999771)),
            # P5: negative layers (offset 3 on both), magnitudes in sRGB mode (maxdrop-em3.161)
            (tx.BLEND_ADD, P5_BOTTOM, P5_TOP, 2.2, (1.18624, 1.13619, 0.799878)),
            (tx.BLEND_SUBTRACT, P5_BOTTOM, P5_TOP, 2.2, (0.0, 0.00579834, 0.0)),
            (tx.BLEND_DIFFERENCE, P5_BOTTOM, P5_TOP, 2.2, (0.1178, 0.00579834, 0.799878)),
            (tx.BLEND_SCREEN, P5_BOTTOM, P5_TOP, 2.2, (0.654002, 0.581064, 0.799878)),
            (tx.BLEND_OVERLAY, P5_BOTTOM, P5_TOP, 2.2, (0.229496, 0.281987, 0.0)),
            (tx.BLEND_DODGE, P5_BOTTOM, P5_TOP, 2.2, (0.999771, 0.999771, 0.0)),
            (tx.BLEND_BURN, P5_BOTTOM, P5_TOP, 2.2, (0.00762939, 0.0100708, 0.0)),
            (tx.BLEND_LINEAR_LIGHT, P5_BOTTOM, P5_TOP, 2.2, (0.629587, 0.258488, 0.624094)),
            (tx.BLEND_HARD_LIGHT, P5_BOTTOM, P5_TOP, 2.2, (0.386358, 0.275578, 0.624094)),
            (tx.BLEND_EXCLUSION, P5_BOTTOM, P5_TOP, 2.2, (0.288395, 0.22034, 0.799878)),
            (tx.BLEND_DODGE, P5_BOTTOM, P5_TOP, 1.0, (-0.200198, 0.249943, 0.0)),
            (tx.BLEND_BURN, P5_BOTTOM, P5_TOP, 1.0, (0.0, 4.49989, 0.0)),
        )
        for op, bottom, top, gamma, want in cases:
            with self.subTest(op=op, gamma=gamma):
                for ours, theirs in zip(tx.blend_value(op, bottom, top, gamma), want):
                    self.assertAlmostEqual(ours, theirs, delta=2e-3)

    def test_corona_mix_gamma(self):
        bottom = (0.05, 0.4, 0.9)
        # two colors: folded per channel; renderMap of bottom 0.05 0.4 0.9 under a top of 0.5 in sRGB mode
        tex = _tex(_cmix(1, p200=7, p208=(1.0, 1.0, 1.0), p202=0.5, p209=bottom))
        for ours, theirs in zip(tex.convert(mat.MapRef(1), tx.COLOR).root.value, (0.01648, 0.284733, 0.865491)):
            self.assertAlmostEqual(ours, theirs, delta=1e-3)
        tex = _tex(_cmix(1, p200=7, p208=(0.5, 0.25, 1.0), p209=bottom, p214=0))
        self.close(tex.convert(mat.MapRef(1), tx.COLOR).root.value, (0.05 ** 2, 0.4 ** 4, 0.9),
                   "linear mode, a colored top")
        # a grey top color over a map: a ColorCorrect gamma, under a Mix for an amount below 1
        for srgb, want in ((1, 0.5 ** (1 / 2.2)), (0, 0.5)):
            tex = _tex(_cmix(1, [2], p200=7, p207=Ref(2), p208=(1.0, 1.0, 1.0), p202=0.5, p214=srgb), _cbitmap(2))
            g = tex.convert(mat.MapRef(1), tx.COLOR)
            self.assertIsInstance(g.root, tx.ColorCorrect)
            self.close(g.root.gamma, want)
            self.assertEqual(g.root.input.name, "a.png")
            self.assertEqual((g.approximated, g.issues), (False, ()))
        tex = _tex(_cmix(1, [2], p200=7, p201=0.5, p207=Ref(2), p208=(0.5, 0.5, 0.5)), _cbitmap(2))
        root = tex.convert(mat.MapRef(1), tx.COLOR).root
        self.assertIsInstance(root, tx.Mix)
        self.assertIs(root.a, root.b.input, "the bottom, shared")
        # a colored top over a map, a top map, a top of 0: peeled to the first bitmap, the operation named
        for params in (dict(p208=(0.5, 0.25, 1.0)), dict(p206=Ref(3)), dict(p208=(0.0, 0.0, 0.0))):
            with self.subTest(params=params):
                tex = _tex(_cmix(1, [2, 3], p200=7, p207=Ref(2), **params), _cbitmap(2), _cbitmap(3, G2))
                g = tex.convert(mat.MapRef(1), tx.COLOR)
                self.assertEqual(g.root.name, "a.png")
                self.assertTrue(g.approximated)
                self.assertIn("operation gamma drawn as its first bitmap", tex.stats.issues[0][1])
        self.close(tx._gamma_value(1e6, 0.01), tx.MAX_MULTIPLIER, "held")

    def test_corona_mix_negative_layers(self):
        """renderMap of probe1's P5 (maxdrop-em3.117): CoronaColor HDR layers below 0 by their offsets; in sRGB mode
        Corona raises each layer's magnitude (maxdrop-em3.161), the gamma operation's top exponent and bottom too."""
        for op, srgb, want in ((0, 1, (1.18624, 1.13619, 0.799878)), (0, 0, (0.399786, 0.0997939, 0.799878)),
                               (14, 1, (0.629587, 0.258488, 0.624094)), (20, 1, (0.288395, 0.22034, 0.799878)),
                               (11, 0, (-0.200198, 0.249943, 0.0))):
            with self.subTest(op=op, srgb=srgb):
                tex = _tex(_cmix(1, [2, 3], p200=op, p214=srgb, p206=Ref(2), p207=Ref(3), p204=3.0, p205=3.0),
                           _ccolor(2, p50=1, p58=(0.8, 0.1, 1.1)), _ccolor(3, p50=1, p58=(0.2, 0.6, 0.3)))
                root = tex.convert(mat.MapRef(1), tx.COLOR).root
                self.assertIsInstance(root, tx.Constant)
                for ours, theirs in zip(root.value, want):
                    self.assertAlmostEqual(ours, theirs, delta=2e-3)
        # gamma: two swatches (P5's, the top's blue 0.9: the bottom's blue is 0 either way)
        tex = _tex(_cmix(1, p200=7, p208=(0.8, 0.1, 0.9), p209=(0.2, 0.6, 0.3), p204=3.0, p205=3.0))
        for ours, theirs in zip(tex.convert(mat.MapRef(1), tx.COLOR).root.value, (0.0424199, 0.0817881, 0.0)):
            self.assertAlmostEqual(ours, theirs, delta=2e-3)
        # a top of -0.2 over a map in sRGB mode: the exponent 0.2^(1 / 2.2), drawn
        tex = _tex(_cmix(1, [2], p200=7, p207=Ref(2), p208=(0.1, 0.1, 0.1), p204=3.0), _cbitmap(2))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.ColorCorrect)
        self.close(g.root.gamma, 0.2 ** (1 / 2.2))

    def test_corona_mix_peeled_operations_named(self):
        for op, name in ((15, "soft light"), (17, "vivid light"), (18, "pin light"), (19, "hard mix")):
            with self.subTest(op=op):
                tex = _tex(_cmix(1, [2], p200=op, p206=Ref(2)), _cbitmap(2))
                g = tex.convert(mat.MapRef(1), tx.COLOR)
                self.assertEqual(g.root.name, "a.png")
                self.assertIn("operation %s drawn as its first bitmap" % name, tex.stats.issues[0][1])

    def test_corona_mix_huge_multiplier_folds(self):
        tex = _tex(_cmix(1, p200=0, p202=1e300, p203=1e300, p208=(1.0, 1.0, 1.0), p209=(1.0, 1.0, 1.0)))
        root = tex.convert(mat.MapRef(1), tx.COLOR).root
        self.assertTrue(all(math.isfinite(c) for c in root.value))

    def test_corona_mix_peeled_does_not_convert_its_layers_first(self):
        tex = _tex(_cmix(1, [2, 3], p200=15, p206=Ref(2), p207=Ref(3)), _cbitmap(2),
                   FakeMap(3, (0x1234, 0), cls="Noise"))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertEqual(tex.stats.unsupported, collections.Counter(), "the bottom Noise is never drawn")

    def test_corona_mix_other_operation_without_a_bitmap(self):
        tex = _tex(_cmix(1, p200=17))
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
            self.assertEqual((g.root.gamma, g.root.colorspace), (1.0, tx.LINEAR), params)
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
        cases = ((_info(1.8, 5), 1.8, tx.LINEAR), (_info(2.2, 5), 2.2, tx.SRGB), (_info(1.0, 20), None, tx.SRGB),
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

    def test_composite_with_an_unknown_blend_mode_is_peeled(self):
        comp = FakeMap(1, tx.COMPOSITE, {5: [0, 15], 9: [Ref(2), Ref(3)]}, [2, 3], cls="Composite")
        tex = _tex(comp, _bitmap(2), _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Image)
        self.assertTrue(any("blend modes [15]" in r for r in g.issues))

    def test_color_correction_modes(self):
        standard = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 11: 0, 12: 10.0, 13: -20.0, 22: 2.0}, [2])
        g = _tex(standard, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual((g.root.brightness, g.root.contrast, g.root.gamma), (0.1, -0.2, 1.0))
        self.assertFalse(g.approximated)
        lifted = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 11: 1, 30: 0.2, 10: 0.5}, [2])
        g = _tex(lifted, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertTrue(g.approximated)
        self.assertTrue(any("pivot and lift" in r for r in g.issues))
        self.assertTrue(any("tint not converted" in r for r in g.issues))

    def test_mix_curve(self):
        """Use Curve folds the mix amount through mix_factor, or puts a Smoothstep over the mask; no issue."""
        mix = FakeMap(1, tx.MIX, {0: 0.4, 1: 0.3, 2: 0.7, 3: 1, 6: Ref(2)}, [2])
        g = _tex(mix, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.factor, 0.15625)  # u = 0.25: 3u^2 - 2u^3
        self.assertFalse(g.approximated)
        self.assertEqual(g.issues, ())
        mix = FakeMap(1, tx.MIX, {0: 0.4, 1: 0.2, 2: 0.9, 3: 1, 6: Ref(2), 8: Ref(3)}, [2, 3])
        g = _tex(mix, _bitmap(2), _bitmap(3)).convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root.mask, tx.Smoothstep)
        self.assertIsInstance(g.root.mask.input, tx.Image)
        self.assertEqual((g.root.mask.lower, g.root.mask.upper), (0.2, 0.9))
        self.close(g.root.factor, tx.mix_factor(0.4, 0.2, 0.9))  # the builder's fallback when the mask is missing
        self.assertEqual(g.issues, ())
        mix = FakeMap(1, tx.MIX, {0: 0.4, 6: Ref(2), 8: Ref(3)}, [2, 3])  # without Use Curve: the mask itself
        self.assertIsInstance(_tex(mix, _bitmap(2), _bitmap(3)).convert(mat.MapRef(1), tx.COLOR).root.mask, tx.Image)

    def test_mix_factor(self):
        """The measured rule (renderMap, 3ds Max 2020): lower 0.3, upper 0.7 and lower 0.2, upper 0.9."""
        measured = {(0.3, 0.7): [0.0] * 7 + [0.0429541, 0.156237, 0.316396, 0.499992, 0.683589, 0.843748, 0.957031]
                    + [1.0] * 7,
                    (0.2, 0.9): [0.0] * 5 + [0.0145724, 0.0553902, 0.118074, 0.198245, 0.291539, 0.393576, 0.499992,
                                             0.606409, 0.708446, 0.80174, 0.88191, 0.944595, 0.985412, 1.0, 1.0, 1.0]}
        for (lower, upper), ys in measured.items():
            for k, y in enumerate(ys):
                self.assertAlmostEqual(tx.mix_factor(k / 20.0, lower, upper), y, delta=1e-4, msg=(lower, upper, k))
        self.assertEqual([tx.mix_factor(x, 0.5, 0.5) for x in (0.4999, 0.5, 0.6)], [0.0, 1.0, 1.0])  # a step
        self.assertEqual([tx.mix_factor(x, 0.7, 0.3) for x in (0.5, 0.69, 0.7)], [0.0, 0.0, 1.0])  # a step at lower

    def test_edited_mix_curve_in_every_kind(self):
        """An edited curve puts the Facing under a Remap whatever the input (a VRayMtl reflection is a data input,
        the case of a bent reflection ramp), and the Remap is the curve's polyline."""
        P = reader_materials.CurvePoint
        points = (P((0, 0), (0, 0), (0, 0), 0x102), P((0.5, 0.2), (0.5, 0.2), (0.5, 0.2), 4),
                  P((1, 1), (1, 1), (1, 1), 0x100))
        old = reader_materials.mix_curve
        reader_materials.mix_curve = lambda _scene, _m: points
        try:
            for kind in (tx.COLOR, tx.DATA):
                g = _tex(_falloff(1, name="fo")).convert(mat.MapRef(1), kind)
                self.assertEqual(g.root.mask, tx.Remap(tx.Facing(tx.PERPENDICULAR, 1.6), ((0, 0), (0.5, 0.2), (1, 1))),
                                 kind)
                self.assertEqual(g.issues, ())
        finally:
            reader_materials.mix_curve = old

    def test_unreadable_mix_curve_is_drawn_linear(self):
        def broken(_scene, _m):
            raise chunks.ChunkError("the curve control at object 9: no point count")
        old = reader_materials.mix_curve
        reader_materials.mix_curve = broken
        try:
            fo = _falloff(1, name="fo")
            g = _tex(fo).convert(mat.MapRef(1), tx.COLOR)
        finally:
            reader_materials.mix_curve = old
        self.assertEqual(g.root.mask, tx.Facing(tx.PERPENDICULAR, 1.6))
        self.assertTrue(g.approximated)
        self.assertTrue(any(r.startswith("Falloff 'fo': its mix curve could not be read") and "drawn linear" in r
                            for r in g.issues), g.issues)

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
    and alpha, below a VRayNormalMap, a Composite and a Mix; a Falloff in a VRayMtl's reflection."""

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
        # transfer function Auto: the sRGB curve for an 8-bit file, which the gamma-off fixture shows decoded once
        # more (maxdrop-em3.123)
        self.image(g.root, "vtx_diffuse.png", tx.LINEAR)
        self.assertEqual((g.root.gamma, g.root.crop, g.root.output, g.root.alpha), (tx.SRGB_TWICE, None, None, False))
        self.assertEqual(g.root.path, "vtx_diffuse.png")
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def test_spherical_mapping_is_an_issue(self):
        g = self.f.irs["FixtureVBDiffuse"].textures["specular"]
        self.image(g.root, "vtx_sphere.png", tx.LINEAR)
        self.assertTrue(g.root.mapping.environment)
        self.assertTrue(any("environment mapping" in r for r in g.issues), g.issues)

    def test_own_placement_and_multipliers(self):
        g = self.f.irs["FixtureVBPlace"].textures["base_color"]
        self.image(g.root, "vtx_place.png", tx.LINEAR, tiling=(2.0, 3.0), offset=(0.1, 0.2), w_angle=30.0)
        self.close(g.root.mapping.blur, 0.8)
        self.assertFalse(g.root.mapping.environment)
        self.close(g.root.output.amount, 3.0)  # overall 1.5 x render 2
        self.assertEqual((g.root.output.invert, g.root.output.level, g.root.output.offset), (False, 1.0, 0.0))
        self.assertEqual(g.issues, ())

    def test_transfer_functions(self):
        t = self.f.irs["FixtureVBPlace"].textures
        # the gamma-off fixture shows V-Ray's own decode decoded once more (maxdrop-em3.123)
        self.image(t["specular"].root, "vtx_linear.png", tx.SRGB)  # None: as stored, so sRGB
        self.close(t["specular"].root.gamma, 2.2)
        self.image(t["transmission"].root, "vtx_invgamma.png", tx.LINEAR)  # inverse gamma 2: pixel ^ 0.5, x 2.2
        self.close(t["transmission"].root.gamma, 1.1)
        self.assertIsInstance(t["roughness"].root, tx.Invert)
        self.image(t["roughness"].root.input, "vtx_gloss.png", tx.SRGB)  # sRGB: V-Ray's curve on any input
        self.assertIsNone(t["roughness"].root.input.gamma)

    def test_mono_output_alpha(self):
        image = self.f.irs["FixtureVBPlace"].textures["alpha"].root
        self.image(image, "vtx_alpha.png", tx.SRGB)  # its alpha is used: the color space changes nothing
        self.assertTrue(image.alpha)

    def test_bump_and_normal(self):
        b = self.f.irs["FixtureVBBump"].textures["bump"].root
        self.assertIsInstance(b, tx.Bump)
        self.close(b.strength, 0.5)
        self.image(b.input, "vtx_bump.png", tx.SRGB)  # a height by V-Ray's own curve (maxdrop-em3.159)
        n = self.f.irs["FixtureVBNormal"].textures["normal"].root
        self.assertIsInstance(n, tx.NormalMap)
        self.close(n.strength, 0.9)
        self.image(n.input, "vtx_normal.png", tx.NON_COLOR)
        self.close(n.input.gamma, 1.0)

    def test_below_a_color_correction_composite_and_mix(self):
        cc = self.f.irs["FixtureCCComposite"].textures["base_color"].root
        self.assertIsInstance(cc, tx.ColorCorrect)
        self.close(cc.brightness, 0.1)
        self.assertIsInstance(cc.input, tx.Decode)  # gamma off: composited on the stored values (em3.158)
        a, b = cc.input.input.layers
        self.image(a.node, "vtx_layer_a.png", tx.SRGB)  # Auto: V-Ray's own decode, the Decode shows it once more
        self.image(b.node, "vtx_layer_b.png", tx.SRGB)
        self.close((a.opacity, b.opacity), (1.0, 0.5))
        mix = self.f.irs["FixtureMixMask"].textures["base_color"].root.input
        self.assertIsInstance(mix, tx.Mix)
        self.image(mix.a, "vtx_mix_a.png", tx.SRGB)

    def test_vray_color(self):
        t = self.f.irs["FixtureVColor"].textures
        self.assertEqual((t["base_color"].approximated, t["base_color"].issues), (False, ()))
        self.close(t["base_color"].root.value, (1.0, _lin(150), _lin(75)))  # 200 100 50 times 1.5, clamped
        self.close(t["specular"].root.value, (_lin(255 * (128 / 255) ** 2.2),) * 3)  # color gamma 2.2

    def test_vray_color_below_falloff_color_correction_and_mix(self):
        g = self.f.irs["FixtureVFalloff"].textures["base_color"]
        self.assertIsInstance(g.root, tx.Mix)  # the Falloff: its map 1 to its color 2
        self.close(g.root.a.value, (_lin(50), _lin(150), _lin(250)))
        self.assertIsInstance(g.root.mask, tx.Facing)
        self.assertFalse(g.approximated)
        cc = self.f.irs["FixtureCCColor"].textures["base_color"].root
        self.assertIsInstance(cc, tx.ColorCorrect)
        self.close(cc.saturation, 1.2)
        self.close(cc.input.value, (_lin(100), _lin(200), _lin(50)))
        mix = self.f.irs["FixtureMixMask"].textures["base_color"].root.input
        self.assertIsInstance(mix.mask, tx.Constant)
        self.close(mix.mask.value, 64 / 255)  # a float, as stored: V-Ray mixes the stored colors by it (em3.158)

    def test_falloff_in_reflection(self):
        black, white = tx.Constant((0.0, 0.0, 0.0)), tx.Constant((1.0, 1.0, 1.0))
        ir = self.f.irs["FixtureVReflPerp"]
        g = ir.textures["specular"]  # the default Falloff: black facing the viewer, white at grazing
        self.assertEqual(g.root, tx.Mix(black, white, 0.0, tx.Facing(tx.PERPENDICULAR)))
        self.assertEqual((g.approximated, g.issues), (False, ()))
        self.assertEqual((ir.metallic.value, ir.metallic.map), (0.0, None), "Fresnel off, a dark swatch: no metal")
        self.assertFalse(ir.fresnel, "Fresnel off: the Falloff is the reflection at every angle, no Fresnel on it")
        self.assertNotIn("base_color", ir.textures)
        g = self.f.irs["FixtureVReflFresnel"].textures["specular"]  # map amount 50: half the swatch (black)
        self.assertEqual(g.root, tx.Mix(black, tx.Mix(black, white, 0.0, tx.Facing(tx.FRESNEL, 1.5)), 0.5))
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def test_falloff_in_reflection_over_a_white_swatch(self):
        """Fresnel off, a white swatch the Falloff at full amount hides: a dielectric, not a metal in the Falloff."""
        black, white = tx.Constant((0.0, 0.0, 0.0)), tx.Constant((1.0, 1.0, 1.0))
        dark = self.f.irs["FixtureVReflPerp"]
        m = _Swatch(self.f.graph.get(dark.index), (2, 1), (1.0, 1.0, 1.0))  # reflection, block 1
        ir = mat.MaterialIR(m.index, m.name)
        mat.vray_mtl(self.f.conv, m, ir)
        self.close(ir.specular.value, 1.0, "the hidden swatch")
        self.assertEqual((ir.metallic.value, ir.metallic.map), (0.0, None))
        self.assertEqual(ir.base_color, dark.base_color, "the diffuse")
        textures = tx.texture_graphs(ir, self.f.tex)
        self.assertNotIn("base_color", textures)
        self.assertEqual(textures["specular"].root, tx.Mix(black, white, 0.0, tx.Facing(tx.PERPENDICULAR)))

    def test_color_correction_over_an_unsupported_map(self):
        ir = self.f.irs["FixtureCCNoise"]
        self.assertNotIn("base_color", ir.textures, "the material's own diffuse, not the Color Correction's black")
        issues = [r for i, r in self.f.tex.stats.issues if "converts to nothing" in r]
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("Color Correction", issues[0])
        self.assertIn("Noise", issues[0])

    def test_peeled_and_unsupported_classes(self):
        # the Noise below a Color Correction converts to nothing
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter())
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
        for params, gamma, space in (({"p25": 0}, 1.0, tx.LINEAR), ({"p25": 1, "p8": 2.0}, 0.5, tx.LINEAR),
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
        self.assertEqual(g.root.colorspace, tx.SRGB, "a data input: decoded by its gamma too (2.2)")
        _t, g = _vb(tx.DATA, p25=1, p8=2.0)
        self.assertEqual(g.root.colorspace, tx.LINEAR)

    def test_float_files_under_auto_are_linear(self):
        table = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.EXR", "")])
        for params, gamma in (({}, 1.0), ({"p25": 4}, 1.0), ({"p25": 3}, 1.0), ({"p25": 2}, None),
                              ({"p25": 1, "p8": 2.0}, 0.5)):
            g = _tex(_vbitmap(1, **params), table=table).convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual(g.root.gamma, gamma, params)
            self.assertEqual(g.root.colorspace, tx.SRGB if gamma is None else tx.LINEAR, params)

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
        # Use Curve weighs by the amount through the curve (lower 0.3, upper 0.7 by default): 0.5 stays 0.5
        tex = _tex(FakeMap(1, tx.MIX, {0: 0.5, 3: 1, 6: Ref(2), 7: Ref(3)}, [2, 3], cls="Mix"), _noise(2),
                   _bitmap(3))
        self.assertEqual(tex.convert(mat.MapRef(1), tx.COLOR).root.name, "a.png", "a curve at 0.5: map 1 shows")
        tex = _tex(FakeMap(1, tx.MIX, {0: 0.75, 3: 1, 5: (1.0, 0.0, 0.0), 6: Ref(2)}, [2], cls="Mix"), _noise(2))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix, "a curve at 0.75 gives 1: map 1 does not show")
        self.close(g.root.factor, 1.0)
        self.assertFalse(g.approximated)
        tex = _tex(FakeMap(1, tx.MIX, {0: 1.0, 3: 1, 6: Ref(2), 7: Ref(3), 8: Ref(4)}, [2, 3, 4], cls="Mix"),
                   _noise(2), _bitmap(3), _bitmap(4))
        self.assertEqual(tex.convert(mat.MapRef(1), tx.COLOR).root.name, "a.png", "a curve on a mask: unknown")

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
        self.close(tex.convert(mat.MapRef(1), tx.COLOR).root.a.value, (1.0, 0.0, 0.0), "no map: color 1")
        self.assertEqual(tex.stats.peeled, collections.Counter())
        tex = _tex(FakeMap(1, tx.FALLOFF, {2: Ref(2), 6: Ref(3)}, [2, 3], cls="Falloff", name="f"), _noise(2),
                   _bitmap(3))
        self.assertEqual(tex.convert(mat.MapRef(1), tx.COLOR).root.name, "a.png", "a lost side: the other map")
        self.assertEqual(tex.stats.peeled, collections.Counter({"Falloff": 1}))
        tex = _tex(FakeMap(1, tx.VRAY_DIRT, {13: (1.0, 0.0, 0.0), 17: Ref(2), 18: 0}, [2], cls="VRayDirt"),
                   _noise(2))
        self.close(tex.convert(mat.MapRef(1), tx.COLOR).root.value, (1.0, 0.0, 0.0), "map off: its color")
        self.assertEqual(tex.stats.peeled, collections.Counter({"VRayDirt": 1}))

    # (class, class name, map pid, switch pid or None, what it draws without a used map, as a swatch): measured in
    # 3ds Max 2020 (renderMap) and V-Ray 5.2 with the gamma off (maxdrop-em3.76)
    EMPTY_WRAPPERS = ((tx.OUTPUT, "Output", 0, 1, (1.0, 1.0, 1.0)), (tx.RGB_TINT, "RGB Tint", 3, 4, (1.0, 1.0, 1.0)),
                      (tx.VRAY_COLOR2BUMP, "VRayColor2Bump", 0, None, (0.5, 0.5, 1.0)))

    def test_empty_wrappers_draw_a_constant(self):
        for class_id, cls, pid, on, rgb in self.EMPTY_WRAPPERS:
            for swatches in (colors.GAMMA_OFF, colors.GAMMA_ON):
                cases = [("map unset", (FakeMap(1, class_id, {pid: Ref(None)}, cls=cls, name="w"),))]
                if on is not None:  # map off: the bitmap below is not used
                    cases.append(("map off", (FakeMap(1, class_id, {pid: Ref(2), on: 0}, [2], cls=cls, name="w"),
                                              _bitmap(2))))
                for case, objects in cases:
                    with self.subTest(cls=cls, case=case, linear=swatches.linear):
                        tex = tx.TexmapConverter(FakeGraph(*objects), _table(), swatches=swatches)
                        g = tex.convert(mat.MapRef(1), tx.COLOR)
                        self.assertEqual(g.root, tx.Constant(swatches.color(rgb)))
                        self.assertFalse(g.approximated)
                        g = tex.convert(mat.MapRef(1), tx.DATA)
                        mean = sum(min(1.0, max(0.0, c)) for c in rgb) / 3.0
                        self.assertEqual(g.root, tx.Constant(mean), "the mean, as stored")
                        self.assertFalse(g.approximated)
                        self.assertEqual(tex.stats.issues, [])
                        self.assertEqual(tex.stats.peeled, collections.Counter())
                        self.assertEqual(tex.stats.unsupported, collections.Counter())
        tex = tx.TexmapConverter(FakeGraph(FakeMap(1, tx.VRAY_COLOR2BUMP, {0: Ref(None)}, cls="VRayColor2Bump")),
                                 _table(), swatches=colors.GAMMA_ON)
        self.close(tex.convert(mat.MapRef(1), tx.COLOR).root.value, (0.5, 0.5, 1.0))
        self.close(tex.convert(mat.MapRef(1), tx.DATA).root.value, 2.0 / 3.0)

    def test_empty_wrapper_keeps_its_own_output_and_tint(self):
        out = FakeMap(1, tx.OUTPUT, {0: Ref(None)}, cls="Output")
        part = FakeMap(5, (0x100, 0), superclass=classids.SC_TEXOUTPUT)
        part.legacy = {0: {0: 0.8, 1: 0.1, 2: 0.5}}
        out.parts = {2: part}
        tex = _tex(out)
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root, tx.Adjust(tx.Constant((1.0, 1.0, 1.0)), tx.TexOutput(False, 0.5, 0.8, 0.1)),
                         "as over a white map")
        self.assertEqual(tex.stats.issues, [])
        tint = FakeMap(1, tx.RGB_TINT, {0: (0.5, 0.0, 0.0), 1: (0.0, 0.25, 0.0), 2: (0.0, 0.0, 0.125),
                                        3: Ref(None)}, cls="RGB Tint")
        tex = tx.TexmapConverter(FakeGraph(tint), _table(), swatches=colors.GAMMA_ON)
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root, tx.Tint(tx.Constant((1.0, 1.0, 1.0)), (0.5, 0.0, 0.0), (0.0, 0.25, 0.0),
                                         (0.0, 0.0, 0.125)))
        self.assertEqual(tex.stats.issues, [])
        g = tex.convert(mat.MapRef(1), tx.DATA)  # the builder takes the mean of the Tint's color (maxdrop-em3.128)
        self.assertEqual(g.root, tx.Tint(tx.Constant((1.0, 1.0, 1.0)), (0.5, 0.0, 0.0), (0.0, 0.25, 0.0),
                                         (0.0, 0.0, 0.125)))

    def test_empty_wrapper_in_a_normal_input_is_drawn(self):
        """In a normal map's normal slot V-Ray tilts the normal by an empty Output's or RGB Tint's white (as by a white
        map) and leaves it flat for VRayColor2Bump's (0.5, 0.5, 1): the color as stored, drawn by the builder
        (maxdrop-em3.128), also below another wrapper."""
        for class_id, cls, pid, _on, rgb in self.EMPTY_WRAPPERS:
            for swatches in (colors.GAMMA_OFF, colors.GAMMA_ON):
                with self.subTest(cls=cls, linear=swatches.linear):
                    tex = tx.TexmapConverter(FakeGraph(FakeMap(1, class_id, {pid: Ref(None)}, cls=cls, name="w")),
                                             _table(), swatches=swatches)
                    self.assertEqual(tex.convert(mat.MapRef(1), tx.NORMAL).root, tx.NormalMap(tx.Constant(rgb)))
                    self.assertEqual(tex.stats.issues, [])
        out = FakeMap(1, tx.OUTPUT, {0: Ref(2)}, [2], cls="Output", name="out")
        part = FakeMap(5, (0x100, 0), superclass=classids.SC_TEXOUTPUT)
        part.legacy = {0: {0: 0.8, 1: 0.1, 2: 0.5}}
        out.parts = {2: part}
        tex = _tex(out, FakeMap(2, tx.VRAY_COLOR2BUMP, {0: Ref(None)}, cls="VRayColor2Bump", name="c2b"))
        g = tex.convert(mat.MapRef(1), tx.NORMAL)
        self.assertEqual(g.root.input, tx.Adjust(tx.Constant((0.5, 0.5, 1.0)), tx.TexOutput(False, 0.5, 0.8, 0.1)))
        self.assertEqual(tex.stats.issues, [])

    def test_empty_wrapper_in_a_normal_map_class(self):
        empty = FakeMap(2, tx.OUTPUT, {0: Ref(None)}, cls="Output", name="out")
        nm = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(2), 2: 1, 3: 1.0, 4: Ref(3), 5: 1, 6: 1.0}, [2, 3],
                     cls="VRayNormalMap")
        g = _tex(nm, empty, _bitmap(3)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png", "in a color input: the bump image, not the empty normal slot")
        g = _tex(nm, empty, _bitmap(3)).convert(mat.MapRef(1), tx.NORMAL)
        self.assertIsInstance(g.root, tx.NormalMap, "the normal slot drawn: its white, with the bump map")
        self.assertEqual(g.root.input, tx.Constant((1.0, 1.0, 1.0)))
        self.assertEqual(g.root.bump.input.name, "a.png")
        nm = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(None), 4: Ref(2), 5: 1, 6: 1.0}, [2], cls="VRayNormalMap")
        tex = _tex(nm, empty)
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR), "an empty Output in its bump slot is no image")
        self.assertEqual(tex.stats.unsupported, collections.Counter({"VRayNormalMap": 1}))
        g = _tex(nm, empty).convert(mat.MapRef(1), tx.BUMP)
        self.assertEqual(g.root, tx.Bump(tx.Constant(1.0)), "a constant height: flat")

    def test_empty_wrapper_below_a_mix(self):
        empty = FakeMap(2, tx.OUTPUT, {0: Ref(None)}, cls="Output", name="out")
        tex = _tex(FakeMap(1, tx.MIX, {0: 0.5, 6: Ref(2), 7: Ref(3)}, [2, 3], cls="Mix", name="mx"), empty,
                   _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix)
        self.assertEqual(g.root.a, tx.Constant((1.0, 1.0, 1.0)), "the empty side: white")
        self.assertEqual(g.root.b.name, "a.png")
        self.assertFalse(g.approximated)
        self.assertEqual(tex.stats.issues, [])

    def test_empty_wrapper_elsewhere(self):
        tint = FakeMap(2, tx.RGB_TINT, {3: Ref(None)}, cls="RGB Tint", name="t")
        tex = _tex(FakeMap(1, tx.COMPOSITE, {9: [Ref(3), Ref(2)]}, [3, 2], cls="Composite", name="cp"), tint,
                   _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Composite, "the empty layer is white")
        self.assertIn(tx.Constant((1.0, 1.0, 1.0)), [layer.node for layer in g.root.layers])
        self.assertEqual(tex.stats.issues, [])
        c2b = FakeMap(1, tx.VRAY_COLOR2BUMP, {0: Ref(None)}, cls="VRayColor2Bump", name="c2b")
        tex = _tex(c2b)
        g = tex.convert(mat.MapRef(1), tx.BUMP)
        self.assertIsInstance(g.root, tx.Bump)
        self.assertIsInstance(g.root.input, tx.Constant, "a constant height: flat, as V-Ray renders it")
        self.assertEqual((tex.stats.issues, tex.stats.peeled), ([], collections.Counter()))
        tex = _tex(FakeMap(1, tx.OUTPUT, {0: Ref(2)}, [2], cls="Output", name="out"), tint)
        self.assertEqual(tex.convert(mat.MapRef(1), tx.COLOR).root, tx.Constant((1.0, 1.0, 1.0)))
        self.assertEqual(tex.stats.issues, [])
        self.assertEqual(tex.stats.peeled, collections.Counter())

    def test_empty_wrapper_under_corona(self):
        """Corona 12 renders an Output's map with map1Enabled off (V-Ray 5.2 and renderMap: white); it honors RGB
        Tint's switch and draws an unset Output white (maxdrop-em3.127)."""
        vray, corona = classdir.ClassId(0x73BAB286, 0x77F8FD0C), classdir.ClassId(0x62A85DCC, 0x523C3604)
        for renderer, used in ((corona, True), ((0x62A85DCC, 0x523C3604), True), (None, False), (vray, False)):
            with self.subTest(renderer=renderer):
                out = FakeMap(1, tx.OUTPUT, {0: Ref(2), 1: 0}, [2], cls="Output", name="out")
                tex = tx.TexmapConverter(FakeGraph(out, _bitmap(2)), _table(), renderer=renderer)
                g = tex.convert(mat.MapRef(1), tx.COLOR)
                d = tex.convert(mat.MapRef(1), tx.DATA)
                if used:
                    self.assertEqual(g.root.name, "a.png", "the map, its switch ignored")
                    self.assertEqual(d.root.name, "a.png", "on a data input too")
                else:
                    self.assertEqual(g.root, tx.Constant((1.0, 1.0, 1.0)))
                    self.assertEqual(d.root, tx.Constant(1.0))
                self.assertEqual(tex.stats.issues, [])
        out = FakeMap(1, tx.OUTPUT, {0: Ref(2), 1: 0}, [2], cls="Output", name="out")
        part = FakeMap(5, (0x100, 0), superclass=classids.SC_TEXOUTPUT)
        part.legacy = {0: {0: 0.8, 1: 0.1, 2: 0.5}}
        out.parts = {2: part}
        tex = tx.TexmapConverter(FakeGraph(out, _bitmap(2)), _table(), renderer=tx.CORONA_RENDERER)
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Adjust, "its Output part over its map")
        self.assertEqual(g.root.input.name, "a.png")
        for wrapper in (FakeMap(1, tx.OUTPUT, {0: Ref(None)}, cls="Output"),
                        FakeMap(1, tx.RGB_TINT, {3: Ref(2), 4: 0}, [2], cls="RGB Tint")):
            with self.subTest(wrapper=wrapper.cls):
                tex = tx.TexmapConverter(FakeGraph(wrapper, _bitmap(2)), _table(), renderer=tx.CORONA_RENDERER)
                self.assertEqual(tex.convert(mat.MapRef(1), tx.COLOR).root, tx.Constant((1.0, 1.0, 1.0)))

    def test_color2bump_with_a_map_is_still_peeled(self):
        tex = _tex(FakeMap(1, tx.VRAY_COLOR2BUMP, {0: Ref(2)}, [2], cls="VRayColor2Bump"), _bitmap(2))
        g = tex.convert(mat.MapRef(1), tx.BUMP)
        self.assertEqual(g.root.input.name, "a.png")
        self.assertTrue(g.approximated)
        self.assertEqual(tex.stats.peeled, collections.Counter({"VRayColor2Bump": 1}))
        tex = _tex(FakeMap(1, tx.VRAY_COLOR2BUMP, {0: Ref(2)}, [2], cls="VRayColor2Bump", name="c2b"), _noise(2))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.BUMP), "a lost map: no graph")
        self.assertEqual([r for _i, r in tex.stats.issues if "converts to nothing" in r],
                         ["VRayColor2Bump 'c2b': its map Noise 'n' converts to nothing"])
        self.assertEqual(tex.stats.peeled, collections.Counter())

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


def _rgb(value):
    return tuple(value) if isinstance(value, tuple) else (value,) * 3


def _tinted_mean(tint):
    """What V-Ray gives a data input from a Tint over a Constant (maxdrop-em3.76): the tint of its color, then the
    mean; what the builder draws (tint() in color, the mean on the float input)."""
    r, g, b = _rgb(tint.input.value)
    return sum(r * tint.red[k] + g * tint.green[k] + b * tint.blue[k] for k in range(3)) / 3.0


# rows 128 / 64 / 32 of em3.76's measured RGB Tint, as stored
ROWS = {0: (128 / 255, 0.0, 0.0), 1: (0.0, 64 / 255, 0.0), 2: (0.0, 0.0, 32 / 255)}
STORED_ROWS = ((128 / 255, 0.0, 0.0), (0.0, 64 / 255, 0.0), (0.0, 0.0, 32 / 255))
RULES = (colors.GAMMA_OFF, colors.GAMMA_ON)


def _wtint(index, map_ref=None, rows=ROWS):
    params = dict(rows)
    params[3] = Ref(map_ref)
    return FakeMap(index, tx.RGB_TINT, params, [map_ref] if map_ref is not None else [], cls="RGB Tint", name="t")


def _vcolor(index, rgb):
    return FakeMap(index, classids.VRAY_COLOR, {tx.VC_COLOR: rgb}, cls="VRayColor", name="vc")


def _vnormal(index, normal):
    return FakeMap(index, classids.VRAY_NORMAL_MAP, {0: Ref(normal), 2: 1, 3: 1.0}, [normal], cls="VRayNormalMap")


class WrapperConstants(Checks):
    """A constant below a wrapper that works on color (RGB Tint, Output, Color Correction) in a data, bump or normal
    input keeps its channels as stored, and so do the Tint's rows (maxdrop-em3.128): V-Ray tints the color and takes
    the mean after (em3.76: 0.293 for the rows 128 / 64 / 32 over white, gamma off), and a data input takes swatches
    as stored in both modes (em3.122). Every case runs under GAMMA_OFF, where stored and decoded differ."""

    def convert(self, swatches, kind, *objects):
        tex = tx.TexmapConverter(FakeGraph(*objects), _table(), swatches=swatches)
        return tex, tex.convert(mat.MapRef(1), kind)

    def test_tint_rows_stored_in_data(self):
        for rule in RULES:
            with self.subTest(linear=rule.linear):
                tex, g = self.convert(rule, tx.DATA, _wtint(1))
                self.assertEqual(g.root.input, tx.Constant((1.0, 1.0, 1.0)))
                self.close((g.root.red, g.root.green, g.root.blue), STORED_ROWS)
                self.close(_tinted_mean(g.root), 224 / 3 / 255, "em3.76: 0.293 measured on opacity")
                self.assertAlmostEqual(_tinted_mean(g.root), 0.293, delta=0.001)
                self.assertEqual(tex.stats.issues, [])
                _t, g = self.convert(rule, tx.COLOR, _wtint(1))
                self.close(g.root.red, rule.color(STORED_ROWS[0]), "a color input: the rows decoded by the rule")
                _t, g = self.convert(rule, tx.BUMP, _wtint(1))
                self.close(g.root.input.input.value, (1.0, 1.0, 1.0), "a height: the same rule")

    def test_tint_over_a_color_constant(self):
        for rule in RULES:
            for below, rgb in ((FakeMap(2, tx.VRAY_COLOR2BUMP, {0: Ref(None)}, cls="VRayColor2Bump"),
                                (0.5, 0.5, 1.0)), (_vcolor(2, (1.0, 0.0, 0.0)), (1.0, 0.0, 0.0))):
                with self.subTest(linear=rule.linear, below=below.cls):
                    tex, g = self.convert(rule, tx.DATA, _wtint(1, 2), below)
                    self.assertEqual(g.root.input, tx.Constant(rgb), "the color below the Tint, as stored")
                    want = sum(rgb[0] * STORED_ROWS[0][k] + rgb[1] * STORED_ROWS[1][k] + rgb[2] * STORED_ROWS[2][k]
                               for k in range(3)) / 3.0
                    self.close(_tinted_mean(g.root), want, "tinted, then the mean")
                    grey = sum(rgb) / 3.0 * sum(map(sum, STORED_ROWS)) / 3.0
                    self.assertGreater(abs(want - grey), 0.01, "not the tint of the grey")
                    self.assertEqual(tex.stats.issues, [])
                    _t, g = self.convert(rule, tx.NORMAL, _vnormal(1, 3), _wtint(3, 2), below)
                    self.assertIsInstance(g.root, tx.NormalMap)
                    self.assertEqual(g.root.input.input, tx.Constant(rgb), "a normal input: the color as stored")
                    self.close((g.root.input.red, g.root.input.green, g.root.input.blue), STORED_ROWS)

    def test_identity_wrapper_keeps_the_bare_rule(self):
        identity = {0: (1.0, 0.0, 0.0), 1: (0.0, 1.0, 0.0), 2: (0.0, 0.0, 1.0)}
        for rule in RULES:
            for kind in (tx.DATA, tx.BUMP):
                with self.subTest(linear=rule.linear, kind=kind):
                    bare = self.convert(rule, kind, _vcolor(1, (0.25, 0.5, 1.0)))[1].root
                    tint = self.convert(rule, kind, _wtint(1, 2, identity), _vcolor(2, (0.25, 0.5, 1.0)))[1].root
                    out = self.convert(rule, kind, FakeMap(1, tx.OUTPUT, {0: Ref(2)}, [2], cls="Output"),
                                       _vcolor(2, (0.25, 0.5, 1.0)))[1].root
                    self.assertEqual(tint, bare, "an identity Tint is no wrapper between")
                    self.assertEqual(out, bare, "an Output that changes nothing is no wrapper between")
                    want = tx.Bump(tx.Constant(1.75 / 3.0)) if kind == tx.BUMP else tx.Constant(1.75 / 3.0)
                    self.assertEqual(bare, want)
        for rule in RULES:
            with self.subTest(linear=rule.linear, output="levels"):
                out = FakeMap(1, tx.OUTPUT, {0: Ref(2)}, [2], cls="Output")
                part = FakeMap(5, (0x100, 0), superclass=classids.SC_TEXOUTPUT)
                part.legacy = {0: {0: 0.8, 1: 0.1, 2: 0.5}}
                out.parts = {2: part}
                g = self.convert(rule, tx.DATA, out, _vcolor(2, (0.25, 0.5, 1.0)))[1]
                self.assertEqual(g.root, tx.Adjust(tx.Constant((0.25, 0.5, 1.0)), tx.TexOutput(False, 0.5, 0.8, 0.1)))

    def test_color_correction_constant_keeps_color(self):
        for rule in RULES:
            with self.subTest(linear=rule.linear):
                cc = FakeMap(1, tx.COLOR_CORRECTION, {0: (1.0, 0.0, 0.0), 8: -100.0}, cls="Color Correction")
                g = self.convert(rule, tx.DATA, cc)[1]
                self.assertEqual(g.root, tx.ColorCorrect(tx.Constant((1.0, 0.0, 0.0)), saturation=0.0))
                cc = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 8: -100.0}, [2], cls="Color Correction")
                g = self.convert(rule, tx.DATA, cc, _vcolor(2, (1.0, 0.0, 0.0)))[1]
                self.assertEqual(g.root.input, tx.Constant((1.0, 0.0, 0.0)))
                g = self.convert(rule, tx.COLOR, cc, _vcolor(2, (1.0, 0.0, 0.0)))[1]
                self.assertEqual(g.root.input, tx.Constant(rule.color((1.0, 0.0, 0.0))), "a color input: unchanged")

    def test_nested_maps_below_a_tint(self):
        # a Mix of two colors below the Tint: both sides colors, the mask a mono value (DATA)
        mix = FakeMap(2, tx.MIX, {0: 0.5, 4: (1.0, 0.0, 0.0), 5: (0.0, 0.0, 1.0), 8: Ref(3)}, [3], cls="Mix")
        tex, g = self.convert(colors.GAMMA_OFF, tx.DATA, _wtint(1, 2), mix, _vcolor(3, (64 / 255,) * 3))
        self.assertEqual((g.root.input.a, g.root.input.b), (tx.Constant((1.0, 0.0, 0.0)), tx.Constant((0.0, 0.0, 1.0))))
        self.assertEqual(g.root.input.mask, tx.Constant(64 / 255), "a mask: the mean as stored (DATA)")

    def test_shared_map_bare_and_tinted(self):
        # one VRayColor on a Mix side at the data root and below a Tint on the other side
        mix = FakeMap(1, tx.MIX, {0: 0.5, 6: Ref(2), 7: Ref(3)}, [2, 3], cls="Mix")
        tex, g = self.convert(colors.GAMMA_OFF, tx.DATA, mix, _vcolor(2, (1.0, 0.0, 0.0)), _wtint(3, 2))
        self.assertEqual(g.root.a, tx.Constant(1.0 / 3.0), "bare: the mean")
        self.assertEqual(g.root.b.input, tx.Constant((1.0, 0.0, 0.0)), "below the Tint: the color")

    def test_image_below_a_tint_in_data(self):
        for rule, space in ((colors.GAMMA_OFF, tx.NON_COLOR), (colors.GAMMA_ON, tx.SRGB)):
            with self.subTest(linear=rule.linear):
                g = self.convert(rule, tx.DATA, _wtint(1, 2), _bitmap(2))[1]
                self.image(g.root.input, "a.png", space)  # as a bare data image (em3.122)
                tex = tx.TexmapConverter(FakeGraph(_bitmap(2)), _table(), swatches=rule)
                self.assertEqual(g.root.input, tex.convert(mat.MapRef(2), tx.DATA).root, "the same Image")

    def test_linear_color_below_a_tint(self):
        # CoronaColor's HDR color is linear already: its channels below a Tint in DATA and in a normal input
        hdr = _ccolor(2, p50=1, p58=(2.0, 0.5, 0.0))
        g = self.convert(colors.GAMMA_OFF, tx.DATA, _wtint(1, 2), hdr)[1]
        self.assertEqual(g.root.input, tx.Constant((2.0, 0.5, 0.0)))
        self.assertEqual(self.convert(colors.GAMMA_OFF, tx.DATA, _ccolor(1, p50=1, p58=(2.0, 0.5, 0.0)))[1].root,
                         tx.Constant(2.5 / 3.0), "bare: the mean")
        g = self.convert(colors.GAMMA_OFF, tx.NORMAL, _vnormal(1, 2), _ccolor(2, p50=1, p58=(0.5, 0.5, 1.0)))[1]
        self.assertEqual(g.root.input, tx.Constant((0.5, 0.5, 1.0)))

    def test_imageless_normal_slot_is_no_image(self):
        """A normal map class in a color or data input gives its image; an empty wrapper in its normal slot (a Tint
        of white, an Output with levels) has none, so the bump image stands for it, or nothing."""
        out = FakeMap(2, tx.OUTPUT, {0: Ref(None)}, cls="Output", name="out")
        part = FakeMap(5, (0x100, 0), superclass=classids.SC_TEXOUTPUT)
        part.legacy = {0: {0: 0.8, 1: 0.1, 2: 0.5}}
        out.parts = {2: part}
        for empty in (_wtint(2), out):
            for kind in (tx.COLOR, tx.DATA):
                with self.subTest(empty=empty.cls, kind=kind):
                    nm = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(2), 2: 1, 3: 1.0, 4: Ref(3), 5: 1, 6: 1.0},
                                 [2, 3], cls="VRayNormalMap")
                    g = self.convert(colors.GAMMA_OFF, kind, nm, empty, _bitmap(3))[1]
                    self.assertEqual(g.root.name, "a.png", "the bump image")
                    nm = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(2), 2: 1, 3: 1.0}, [2], cls="VRayNormalMap")
                    tex, g = self.convert(colors.GAMMA_OFF, kind, nm, empty)
                    self.assertIsNone(g, "no image: unsupported")
                    self.assertEqual(tex.stats.unsupported, collections.Counter({"VRayNormalMap": 1}))

    def test_normal_constant_is_rgb(self):
        for rule in RULES:
            with self.subTest(linear=rule.linear):
                g = self.convert(rule, tx.NORMAL, _vnormal(1, 2), _vcolor(2, (0.75, 0.5, 1.0)))[1]
                self.assertEqual(g.root, tx.NormalMap(tx.Constant((0.75, 0.5, 1.0))), "drawn: V-Ray tilts by it")
                g = self.convert(rule, tx.NORMAL, _vnormal(1, 2), _wtint(2, None))[1]
                self.assertEqual(g.root.input.input, tx.Constant((1.0, 1.0, 1.0)))


PROBE_COLOR = (200 / 255, 100 / 255, 50 / 255)  # maxdrop-6n0.6.2's VRayColor


def _wout(index, map_ref=None, level=0.5):
    """An Output whose Output part has that RGB level."""
    out = FakeMap(index, tx.OUTPUT, {0: Ref(map_ref)}, [map_ref] if map_ref is not None else [], cls="Output",
                  name="out")
    part = FakeMap(index + 40, (0x100, 0), superclass=classids.SC_TEXOUTPUT)
    part.legacy = {0: {0: level}}
    out.parts = {2: part}
    return out


def _bw_mix(index, mask):
    """A Mix black -> white at amount 0 whose mask is map mask: what V-Ray renders is the mask's value."""
    return FakeMap(index, tx.MIX, {0: 0.0, 8: Ref(mask)}, [mask], cls="Mix", name="mix")


class MaskWrapperConstants(Checks):
    """An RGB Tint or an Output that changes anything, as the mask of a color graph, acts on the color below it, and
    the mask is the mean of its output (maxdrop-6n0.6.2): V-Ray 5.2 renders the same internal value with the gamma on
    and off (swatches, rows and a Bitmap as it holds them), which the gamma-off scene shows decoded. Measured on a Mix
    black -> white: a Tint of rows 128 / 64 / 32 over a VRayColor (200, 100, 50) renders 0.1722, over white 0.2928;
    an Output of level 0.5 over that VRayColor 0.2287, over white 0.5."""

    def mask(self, swatches, *objects):
        tex = tx.TexmapConverter(FakeGraph(*objects), _table(), swatches=swatches)
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix)
        return tex, g.root.mask

    def test_tint_over_a_color_constant_in_a_mask(self):
        want = (PROBE_COLOR[0] * 128 + PROBE_COLOR[1] * 64 + PROBE_COLOR[2] * 32) / 255 / 3.0
        self.assertAlmostEqual(want, 0.1722, delta=0.0001, msg="V-Ray 5.2, both modes")
        grey = sum(PROBE_COLOR) / 3.0 * (128 + 64 + 32) / 255 / 3.0
        self.assertGreater(abs(want - grey), 0.03, "not the tint of the grey")
        tex, mask = self.mask(colors.GAMMA_OFF, _bw_mix(1, 2), _wtint(2, 3), _vcolor(3, PROBE_COLOR))
        self.assertIsInstance(mask, tx.Constant, "gamma off: folded")
        self.close(mask.value, colors.srgb_to_linear(want), "gamma off: the mean decoded")
        self.assertEqual(tex.stats.issues, [])
        tex, mask = self.mask(colors.GAMMA_ON, _bw_mix(1, 2), _wtint(2, 3), _vcolor(3, PROBE_COLOR))
        self.assertEqual(mask.input, tx.Constant(PROBE_COLOR), "gamma on: the color, linear")
        self.close((mask.red, mask.green, mask.blue), STORED_ROWS)
        self.close(_tinted_mean(mask), want, "the builder's mean of the tinted color")

    def test_empty_tint_in_a_mask(self):
        want = 224 / 255 / 3.0  # 0.2928 measured
        _t, mask = self.mask(colors.GAMMA_OFF, _bw_mix(1, 2), _wtint(2))
        self.close(mask.value, colors.srgb_to_linear(want))
        _t, mask = self.mask(colors.GAMMA_ON, _bw_mix(1, 2), _wtint(2))
        self.close(_tinted_mean(mask), want)

    def test_output_in_a_mask(self):
        for below in (None, 3):
            with self.subTest(below=below):
                objects = (_bw_mix(1, 2), _wout(2, below)) + ((_vcolor(3, PROBE_COLOR),) if below else ())
                stored = PROBE_COLOR if below else (1.0, 1.0, 1.0)
                adjust = tx.Adjust(tx.Constant(stored), tx.TexOutput(level=0.5))
                _t, mask = self.mask(colors.GAMMA_OFF, *objects)
                self.assertEqual(mask, tx.Decode(tx.Tint(adjust, *(tx.MEAN_ROW,) * 3)), "the mean, then the decode")
                _t, mask = self.mask(colors.GAMMA_ON, *objects)
                self.assertEqual(mask, adjust, "gamma on: the color; the builder takes the mean")

    def test_image_below_a_tint_in_a_mask(self):
        _t, mask = self.mask(colors.GAMMA_OFF, _bw_mix(1, 2), _wtint(2, 3), _bitmap(3))
        self.assertIsInstance(mask, tx.Decode)
        self.assertEqual(mask.input.red, mask.input.green)  # MEAN_ROW rows
        self.close(mask.input.red, (1 / 3.0,) * 3)
        self.image(mask.input.input.input, "a.png", tx.NON_COLOR)  # V-Ray holds a gamma-off Bitmap as stored
        self.close(mask.input.input.red, STORED_ROWS[0])
        _t, mask = self.mask(colors.GAMMA_ON, _bw_mix(1, 2), _wtint(2, 3), _bitmap(3))
        self.assertIsInstance(mask, tx.Tint)
        self.image(mask.input, "a.png", tx.SRGB)

    def test_color_correction_in_a_mask_keeps_the_mean(self):
        # V-Ray's saturation is not the builder's HSV one: a colored input would draw further off (debt)
        cc = FakeMap(2, tx.COLOR_CORRECTION, {1: Ref(3), 8: -50.0}, [3], cls="Color Correction")
        for rule in RULES:
            with self.subTest(linear=rule.linear):
                _t, mask = self.mask(rule, _bw_mix(1, 2), cc, _vcolor(3, PROBE_COLOR))
                self.assertEqual(mask, tx.ColorCorrect(tx.Constant(rule.channel(sum(PROBE_COLOR) / 3.0)),
                                                       saturation=0.5))

    def test_identity_wrapper_in_a_mask(self):
        identity = {0: (1.0, 0.0, 0.0), 1: (0.0, 1.0, 0.0), 2: (0.0, 0.0, 1.0)}
        for rule in RULES:
            with self.subTest(linear=rule.linear):
                _t, bare = self.mask(rule, _bw_mix(1, 3), _vcolor(3, PROBE_COLOR))
                _t, tint = self.mask(rule, _bw_mix(1, 2), _wtint(2, 3, identity), _vcolor(3, PROBE_COLOR))
                _t, out = self.mask(rule, _bw_mix(1, 2), _wout(2, 3, 1.0), _vcolor(3, PROBE_COLOR))
                self.assertEqual(bare, tx.Constant(rule.channel(sum(PROBE_COLOR) / 3.0)))
                self.assertEqual(tint, bare)
                self.assertEqual(out, bare)

    def test_composite_layer_mask(self):
        # gamma on: a Composite stays a Composite in a color graph, its layer mask a MASK graph
        comp = FakeMap(1, tx.COMPOSITE, {9: [Ref(5), Ref(6)], 10: [Ref(None), Ref(2)]}, [5, 6, 2], cls="Composite")
        tex = tx.TexmapConverter(FakeGraph(comp, _vcolor(5, (0.0,) * 3), _vcolor(6, (1.0,) * 3), _wtint(2, 3),
                                           _vcolor(3, PROBE_COLOR)), _table(), swatches=colors.GAMMA_ON)
        mask = tex.convert(mat.MapRef(1), tx.COLOR).root.layers[1].mask
        self.assertEqual(mask.input, tx.Constant(PROBE_COLOR))
        self.assertAlmostEqual(_tinted_mean(mask), 0.1722, delta=0.0001, msg="V-Ray 5.2")
        self.close((mask.red, mask.green, mask.blue), STORED_ROWS)

    def test_color_correction_below_a_wrapper_in_a_mask(self):
        # below a Tint or Output in a mask a Color Correction gets the color (the wrapper's kind): its saturation is
        # then drawn as the builder's HSV one, not V-Ray's (maxdrop-6n0.6.38)
        cc = FakeMap(3, tx.COLOR_CORRECTION, {1: Ref(4), 8: -50.0}, [4], cls="Color Correction")
        _t, mask = self.mask(colors.GAMMA_ON, _bw_mix(1, 2), _wout(2, 3), cc, _vcolor(4, PROBE_COLOR))
        self.assertEqual(mask, tx.Adjust(tx.ColorCorrect(tx.Constant(PROBE_COLOR), saturation=0.5),
                                         tx.TexOutput(level=0.5)))

    def test_data_graph_is_unchanged(self):
        # em3.128: a data input keeps the Tint's stored channels with no Decode, in both modes
        for rule in RULES:
            with self.subTest(linear=rule.linear):
                tex = tx.TexmapConverter(FakeGraph(_wtint(1, 2), _vcolor(2, PROBE_COLOR)), _table(), swatches=rule)
                root = tex.convert(mat.MapRef(1), tx.DATA).root
                self.assertEqual(root.input, tx.Constant(PROBE_COLOR))


class SwatchRule(Checks):
    """Every swatch of a map goes through the scene's rule: linear with the gamma on (or unknown), sRGB with it off;
    the HDR color is decoded only with the gamma off (maxdrop-em3.165), CoronaColor's temperature too."""

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
                if rule is colors.GAMMA_OFF:  # mixed as stored, shown decoded: folded (em3.158)
                    self.close(root.value, (want,) * 3)
                else:
                    self.close(root.a.value, (want,) * 3)
                    self.close(root.b.value, (want,) * 3)
                self.close(self._root(rule, falloff).a.value, (want,) * 3)
                self.close(self._root(rule, dirt).value, (want,) * 3)
                self.close(self._root(rule, cc).input.value, (want,) * 3)
                for m in (vc, cco, hexed):
                    self.close(self._root(rule, m).value, (want,) * 3, m.cls)
                self.close(self._root(rule, vc, kind=tx.MASK).value, want, "a mask: the rule of the mean")
                self.close(self._root(rule, vc, kind=tx.DATA).value, g, "a data input: the mean as stored")

    def test_mask_constants_are_the_rule_of_the_mean_swatch(self):
        # V-Ray 5.2 render of a Mix black -> white by a VRayColor mask (maxdrop-em3.36, plan in docs/plans/): red
        # 255 0 0 renders 0.333 linear with the gamma on and byte 85 with it off, which a linear
        # srgb_to_linear(1 / 3) = 0.0908 shows; grey 64 renders 0.251 linear on, byte 64 off. On a data input
        # the mean as stored (maxdrop-em3.122): 1 / 3 and 64 / 255 whatever the rule.
        red, grey = (1.0, 0.0, 0.0), (64 / 255,) * 3
        cases = ((colors.GAMMA_ON, red, 1 / 3), (colors.UNKNOWN, red, 1 / 3), (colors.GAMMA_OFF, red, 0.0908417),
                 (colors.GAMMA_ON, grey, 64 / 255), (colors.GAMMA_OFF, grey, _lin(64)))
        for rule, rgb, want in cases:
            maps = (FakeMap(1, tx.MIX, {4: rgb, 5: rgb}, cls="Mix"),
                    FakeMap(1, classids.VRAY_COLOR, {5: rgb}, cls="VRayColor"),
                    _ccolor(1, p52=rgb),
                    _ccolor(1, p50=3, p59="#%02X%02X%02X" % tuple(round(c * 255) for c in rgb)))
            for m in maps:
                with self.subTest(rule=rule, rgb=rgb, cls=m.cls, method=m.param(50, 0)):
                    mask, color = self._root(rule, m, kind=tx.MASK), self._root(rule, m, kind=tx.COLOR)
                    data = self._root(rule, m, kind=tx.DATA)
                    if m.cls == "Mix":  # a color Mix of two constants with the gamma off: folded (em3.158)
                        mask, data = mask.a, data.a
                        color = color.a if isinstance(color, tx.Mix) else color
                    self.close(mask.value, want)
                    self.close(data.value, sum(rgb) / 3.0, "a data input: as stored")
                    self.close(color.value, rule.color(rgb), "a color input: the linear color")

    def test_hdr_color_by_the_gamma(self):
        # maxdrop-em3.165, Corona 12 renders: the HDR color renders as stored (0.25 / 0.5 / 2.0; 0.5 x multiplier 2:
        # 1.0) with the gamma on and off, linear with it on; with it off the display-referred scene shows it decoded,
        # above 1 on the extended curve (2.0: 4.954), as V-Ray 5.2 renders it too; a data input takes the mean as stored
        hdr = _ccolor(1, p50=1, p58=(0.25, 0.5, 2.0))
        for rule in (colors.GAMMA_ON, colors.UNKNOWN):
            with self.subTest(rule):
                self.close(self._root(rule, hdr).value, (0.25, 0.5, 2.0))
                self.close(self._root(rule, hdr, kind=tx.MASK).value, 2.75 / 3.0)
        self.close(self._root(colors.GAMMA_OFF, hdr).value, (0.0508760, 0.2140411, 4.9538457))
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=1, p57=2.0, p58=(0.5, 0.5, 0.5))).value,
                   (1.0, 1.0, 1.0), "the multiplier before the decode")
        self.close(self._root(colors.GAMMA_OFF, hdr, kind=tx.MASK).value, colors.srgb_to_linear(2.75 / 3.0),
                   "a mask: the mean decoded, as a swatch's")
        for rule in (colors.GAMMA_ON, colors.GAMMA_OFF):
            with self.subTest(rule):
                self.close(self._root(rule, _ccolor(1, p50=1, p58=(1.5, 0.0, 0.0)), kind=tx.DATA).value, 0.5)

    def test_kelvin_by_the_rule(self):
        # maxdrop-em3.38: VRayColor and CoronaColor at 3000 K render the same values with the gamma on and off
        # (V-Ray 5.2, renderMap): with it off the scene is display-referred, so both are decoded from sRGB; with it
        # on Corona's linear color times the multiplier, not clamped
        k = tx.corona_kelvin(3000.0)
        self.close(self._root(colors.GAMMA_ON, _ccolor(1, p50=2, p51=3000.0)).value, k)
        self.close(self._root(colors.UNKNOWN, _ccolor(1, p50=2, p51=3000.0, p57=2.0)).value, tuple(2 * c for c in k))
        self.close(self._root(colors.GAMMA_ON, _ccolor(1, p50=2, p51=3000.0), kind=tx.DATA).value, sum(k) / 3.0)
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=2, p51=3000.0)).value, colors.GAMMA_OFF.color(k))
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=2, p51=3000.0, p57=2.0)).value,
                   colors.GAMMA_OFF.color(tuple(2 * c for c in k)), "clamped, then decoded")
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=2, p51=3000.0), kind=tx.MASK).value,
                   colors.GAMMA_OFF.channel(sum(k) / 3.0), "a mask: the rule of the mean")
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=2, p51=3000.0), kind=tx.DATA).value,
                   sum(min(1.0, c) for c in k) / 3.0, "a data input: the mean as stored")
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=2, p51=3000.0)).value,
                   (1.0, _lin(121.607), _lin(39.1868)), "3ds Max's 255 121.6 39.2 through Blender's sRGB display")


class SceneGammaImages(Checks):
    """maxdrop-em3.38: an image on a color input as 3ds Max 2020 + V-Ray 5.2 read a 128 grey PNG (docs/FORMAT.md,
    Scene gamma): with the gamma on a Bitmap with automatic gamma (and a VRayBitmap From 3ds Max) takes the file
    input gamma; with it off a Bitmap is read as stored whatever its gamma; CoronaBitmap applies its own in both.
    maxdrop-em3.123 (the same renders, greys 64 / 128 / 192, EXRs 0.25 / 0.5 / 2.0): with the gamma off V-Ray shows a
    VRayBitmap's own decode, and a float file read as stored, decoded once more on a color input or a mask (the
    internal value v as srgb_to_linear(v)); maxdrop-em3.165: Corona 12 a CoronaBitmap's alike."""

    ON_10 = colors.Swatches(True, file_in=1.0)
    ON_18 = colors.Swatches(True, file_in=1.8)

    def _bitmap(self, rule, info=None, kind=tx.COLOR, table=None):
        b, chunk_map = _placed(info=info)
        tex = tx.TexmapConverter(FakeGraph(b, chunk_map=chunk_map), _table() if table is None else table,
                                 swatches=rule)
        return tex.convert(mat.MapRef(1), kind).root

    def _map(self, rule, m, kind=tx.COLOR):
        return tx.TexmapConverter(FakeGraph(m), _table(), swatches=rule).convert(mat.MapRef(1), kind).root

    def check(self, image, gamma, space, msg=None):
        self.assertEqual(image.colorspace, space, msg)
        if gamma is None:
            self.assertIsNone(image.gamma, msg)
        else:
            self.close(image.gamma, gamma, msg)

    def test_bitmap_automatic(self):
        for rule, gamma, space in ((colors.GAMMA_ON, None, tx.SRGB), (colors.UNKNOWN, None, tx.SRGB),
                                   (self.ON_10, 1.0, tx.LINEAR), (self.ON_18, 1.8, tx.LINEAR),
                                   (colors.GAMMA_OFF, None, tx.SRGB)):
            with self.subTest(rule):
                self.check(self._bitmap(rule), gamma, space)
                self.check(self._bitmap(rule, info=_info(1.0, 20)), gamma, space, "no override flag: automatic")

    def test_bitmap_override(self):
        for rule in (colors.GAMMA_ON, self.ON_10, colors.UNKNOWN):
            with self.subTest(rule):
                self.check(self._bitmap(rule, info=_info(1.0, 5)), 1.0, tx.LINEAR, "the override wins")
                self.check(self._bitmap(rule, info=_info(2.2, 5)), 2.2, tx.SRGB)
        for info in (_info(1.0, 5), _info(1.8, 5), _info(2.2, 5)):
            self.check(self._bitmap(colors.GAMMA_OFF, info=info), None, tx.SRGB, "gamma off: read as stored")

    def test_float_files_and_data_inputs(self):
        table = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.exr", "")])
        for rule in (colors.GAMMA_ON, self.ON_10, colors.GAMMA_OFF, colors.UNKNOWN):
            with self.subTest(rule):
                # gamma off: as stored, which the scene shows decoded (an EXR of 0.5 renders 0.5, shown 0.214)
                self.check(self._bitmap(rule, table=table), 1.0 if rule.linear else None,
                           tx.LINEAR if rule.linear else tx.SRGB, "an EXR: linear")
                self.check(self._bitmap(rule, table=table, kind=tx.MASK), 1.0 if rule.linear else None,
                           tx.NON_COLOR if rule.linear else tx.SRGB, "an EXR as a mask: the color rule")
                self.check(self._bitmap(rule, table=table, kind=tx.DATA), 1.0 if rule.linear else None,
                           tx.NON_COLOR, "an EXR: as stored")
                # a data input: decoded as a color input with the gamma on, as stored with it off (em3.122)
                for info in (None, _info(1.0, 5)):
                    color, data = self._bitmap(rule, info=info), self._bitmap(rule, info=info, kind=tx.DATA)
                    want = tx.colorspace(tx.DATA, color.gamma) if rule.linear else tx.NON_COLOR
                    self.assertEqual(data.colorspace, want, info)
                    if rule.linear and color.colorspace == tx.SRGB:
                        self.assertEqual(data.colorspace, tx.SRGB, info)
        self.check(self._bitmap(colors.GAMMA_ON, info=_info(1.8, 5), table=table), 1.8, tx.LINEAR,
                   "gamma on: an EXR's override is kept")
        self.check(self._bitmap(colors.GAMMA_OFF, info=_info(1.8, 5), table=table), None, tx.SRGB,
                   "gamma off: an EXR's override does nothing (the rule's; only an automatic EXR was measured)")

    def test_vray_bitmap(self):
        for rule, gamma, space in ((colors.GAMMA_ON, None, tx.SRGB), (self.ON_10, 1.0, tx.LINEAR),
                                   (self.ON_18, 1.8, tx.LINEAR), (colors.GAMMA_OFF, None, tx.SRGB),
                                   (colors.UNKNOWN, None, tx.SRGB)):
            with self.subTest(rule):
                self.check(self._map(rule, _vbitmap(1, p25=3)), gamma, space, "From 3ds Max: the input gamma")
                for cs in (2, 4):  # V-Ray's own curve; with the gamma off shown decoded once more
                    self.check(self._map(rule, _vbitmap(1, p25=cs)), None if rule.linear else tx.SRGB_TWICE,
                               tx.SRGB if rule.linear else tx.LINEAR, "sRGB, Auto: V-Ray's own")
                self.check(self._map(rule, _vbitmap(1, p25=0)), 1.0 if rule.linear else 2.2,
                           tx.LINEAR if rule.linear else tx.SRGB, "None: as stored, shown decoded with the gamma off")
                self.assertEqual(self._map(rule, _vbitmap(1, p25=3), kind=tx.DATA).colorspace,
                                 tx.colorspace(tx.DATA, gamma) if rule.linear else tx.NON_COLOR,
                                 "From 3ds Max on a data input")
                self.assertEqual(self._map(rule, _vbitmap(1, p25=2), kind=tx.DATA).colorspace, tx.SRGB)

    def test_vray_bitmap_gamma_off_is_shown_decoded(self):
        # (params, file, color / mask gamma and space with the gamma off, the data input's)
        exr = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.exr", "")])
        cases = (({"p25": 1, "p8": 2.0}, None, (1.1, tx.LINEAR), (1.1, tx.LINEAR), (0.5, tx.LINEAR)),
                 ({"p25": 1, "p8": 2.2}, None, (1.0, tx.LINEAR), (1.0, tx.NON_COLOR), (1 / 2.2, tx.LINEAR)),
                 ({"p25": 2}, None, (tx.SRGB_TWICE, tx.LINEAR), (tx.SRGB_TWICE, tx.LINEAR), (None, tx.SRGB)),
                 ({"p25": 0}, None, (2.2, tx.SRGB), (2.2, tx.SRGB), (1.0, tx.NON_COLOR)),
                 ({"p25": 3}, None, (None, tx.SRGB), (None, tx.SRGB), (None, tx.NON_COLOR)),
                 ({"p25": 4}, exr, (2.2, tx.SRGB), (2.2, tx.SRGB), (1.0, tx.NON_COLOR)),
                 ({"p25": 0}, exr, (2.2, tx.SRGB), (2.2, tx.SRGB), (1.0, tx.NON_COLOR)),
                 ({"p25": 3}, exr, (None, tx.SRGB), (None, tx.SRGB), (1.0, tx.NON_COLOR)),
                 ({"p25": 2}, exr, (tx.SRGB_TWICE, tx.LINEAR), (tx.SRGB_TWICE, tx.LINEAR), (None, tx.SRGB)))
        for params, table, color, mask, data in cases:
            with self.subTest(params=params, exr=table is not None):
                for kind, (gamma, space) in ((tx.COLOR, color), (tx.MASK, mask), (tx.DATA, data)):
                    tex = tx.TexmapConverter(FakeGraph(_vbitmap(1, **params)), _table() if table is None else table,
                                             swatches=colors.GAMMA_OFF)
                    self.check(tex.convert(mat.MapRef(1), kind).root, gamma, space, kind)

    def test_unshown_and_drawn_gamma(self):
        img = tx.Image(1, "sky.exr")
        for shown, own, space in ((None, 1.0, tx.LINEAR), (2.2, 1.0, tx.LINEAR), (tx.SRGB_TWICE, None, tx.SRGB),
                                  (1.1, 0.5, tx.LINEAR)):
            back = tx.unshown(dataclasses.replace(img, gamma=shown, colorspace=tx.colorspace(tx.COLOR, shown)))
            self.check(back, own, space, shown)
        for gamma, space, drawn in ((None, tx.SRGB, None), (2.2, tx.SRGB, None), (1.0, tx.LINEAR, None),
                                    (tx.SRGB_TWICE, tx.LINEAR, tx.SRGB_TWICE), (0.5, tx.LINEAR, 0.5),
                                    (0.5, tx.NON_COLOR, None), (1.8, tx.SRGB, None)):
            self.assertEqual(tx.drawn_gamma(dataclasses.replace(img, gamma=gamma, colorspace=space)), drawn,
                             (gamma, space))

    def test_shown_values_agree_with_v_ray(self):
        # V-Ray 5.2 internal values with the gamma off (on: the same), shown as srgb_to_linear in Blender: what
        # Blender draws (pixel ^ gamma, sRGB for 2.2) is within 0.02 of it
        def drawn(pixel, gamma):
            return colors.srgb_to_linear(pixel) if gamma is None or abs(gamma - 2.2) < 1e-9 else pixel ** gamma
        cases = ((2, 64, 0.0512696), (2, 128, 0.215861), (2, 192, 0.527115), (0, 64, 0.25098), (0, 192, 0.752941),
                 (1, 128, 0.708492), (1, 192, 0.867722))
        for cs, grey, internal in cases:
            with self.subTest(cs=cs, grey=grey):
                params = {"p25": cs, "p8": 2.0} if cs == 1 else {"p25": cs}
                image = self._map(colors.GAMMA_OFF, _vbitmap(1, **params))
                self.assertLess(abs(drawn(grey / 255.0, image.gamma) - colors.srgb_to_linear(internal)), 0.02)
        inverse = self._map(colors.GAMMA_OFF, _vbitmap(1, p25=1, p8=0.5))  # inverse gamma 0.5: 128 -> 0.252
        self.assertLess(abs(drawn(128 / 255.0, inverse.gamma) - colors.srgb_to_linear(0.251965)), 0.02)

    def test_corona_bitmap_keeps_its_own_with_the_gamma_on(self):
        for rule in (colors.GAMMA_ON, self.ON_10, colors.UNKNOWN):
            with self.subTest(rule):
                self.check(self._map(rule, _cbitmap(1)), None, tx.SRGB, "automatic: 2.2 whatever the input gamma")
                self.check(self._map(rule, _cbitmap(1, p125=1.0)), 1.0, tx.LINEAR)
                self.check(self._map(rule, _cbitmap(1), kind=tx.MASK), None, tx.SRGB)

    def test_corona_bitmap_gamma_off_is_shown_decoded(self):
        # maxdrop-em3.165, Corona 12 renders: a CoronaBitmap's internal value is its own decode with the gamma on and
        # off, as a VRayBitmap's in V-Ray: shown decoded once more on a color input or a mask; data keeps its own
        exr = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.exr", "")])
        cases = (({}, None, (tx.SRGB_TWICE, tx.LINEAR), (None, tx.SRGB)),
                 ({"p125": 2.2}, None, (2.2 * 2.2, tx.LINEAR), (2.2, tx.SRGB)),
                 ({"p125": 1.0}, None, (2.2, tx.SRGB), (1.0, tx.NON_COLOR)),
                 ({}, exr, (2.2, tx.SRGB), (1.0, tx.NON_COLOR)),
                 ({"p125": 2.2}, exr, (2.2 * 2.2, tx.LINEAR), (2.2, tx.SRGB)))
        for params, table, shown, data in cases:
            with self.subTest(params=params, exr=table is not None):
                for kind, (gamma, space) in ((tx.COLOR, shown), (tx.MASK, shown), (tx.DATA, data)):
                    tex = tx.TexmapConverter(FakeGraph(_cbitmap(1, **params)), _table() if table is None else table,
                                             swatches=colors.GAMMA_OFF)
                    self.check(tex.convert(mat.MapRef(1), kind).root, gamma, space, kind)

    def test_corona_shown_values_agree_with_corona(self):
        # Corona 12 internal values (gamma on and off alike), shown as srgb_to_linear in Blender with the gamma off:
        # what Blender draws (pixel ^ gamma, the sRGB curve for 2.2, extended above 1) is within 0.02 of it
        def drawn(pixel, gamma):
            return colors.srgb_to_linear(pixel) if gamma is None or abs(gamma - 2.2) < 1e-9 else pixel ** gamma
        exr = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.exr", "")])
        cases = (({}, None, 64, 0.0477758), ({}, None, 128, 0.21952), ({}, None, 192, 0.535642),
                 ({"p125": 2.2}, None, 128, 0.21952), ({"p125": 1.0}, None, 64, 0.25098),
                 ({"p125": 1.0}, None, 192, 0.752941), ({}, exr, 0.25 * 255, 0.25), ({}, exr, 0.5 * 255, 0.5),
                 ({"p125": 2.2}, exr, 0.5 * 255, 0.217653))
        for params, table, grey, internal in cases:
            with self.subTest(params=params, grey=grey):
                tex = tx.TexmapConverter(FakeGraph(_cbitmap(1, **params)), _table() if table is None else table,
                                         swatches=colors.GAMMA_OFF)
                image = tex.convert(mat.MapRef(1), tx.COLOR).root
                self.assertLess(abs(drawn(grey / 255.0, image.gamma) - colors.srgb_to_linear(internal)), 0.02)
        tex = tx.TexmapConverter(FakeGraph(_cbitmap(1)), exr, swatches=colors.GAMMA_OFF)
        self.assertAlmostEqual(drawn(2.0, tex.convert(mat.MapRef(1), tx.COLOR).root.gamma),
                               colors.srgb_to_linear(2.0), delta=1e-9, msg="an EXR of 2.0: the extended curve")


class DataAndMaskRule(Checks):
    """maxdrop-em3.122, V-Ray 5.2 renders of a 128 grey PNG and grey 64 / red swatches (docs/FORMAT.md, Scene gamma):
    a map's value does not depend on its slot; a data input (glossiness, opacity) takes it as it is, a mask inside a
    color graph is decoded with the gamma off, as the color it mixes is. Gamma on: a Bitmap renders 0.2195 (auto,
    2.2) or 0.502 (1.0) on glossiness, opacity and as a mask; off: 0.502 whatever its override (Non-Color on a data
    input, decoded in a color graph). VRayColor 64 / red: 0.251 / 0.333 on glossiness and opacity in both modes."""

    ON_18 = colors.Swatches(True, file_in=1.8)
    RULES = (colors.GAMMA_ON, colors.GAMMA_OFF, colors.UNKNOWN)

    def _root(self, rule, *objects, kind=tx.COLOR, chunk_map=None):
        tex = tx.TexmapConverter(FakeGraph(*objects, chunk_map=chunk_map), _table(), swatches=rule)
        return tex.convert(mat.MapRef(objects[0].index), kind).root

    def test_data_constant_is_the_stored_mean(self):
        red, grey = (1.0, 0.0, 0.0), (64 / 255,) * 3
        for rule in self.RULES:
            for rgb, want in ((red, 1 / 3), (grey, 64 / 255), ((2.0, 0.5, 0.5), 2 / 3)):
                with self.subTest(rule=rule, rgb=rgb):
                    vc = FakeMap(1, classids.VRAY_COLOR, {5: rgb}, cls="VRayColor")
                    self.close(self._root(rule, vc, kind=tx.DATA).value, want, "glossiness, opacity: as stored")
                    self.close(self._root(rule, vc, kind=tx.BUMP).input.value, want, "a height: as stored")
                    own = FakeMap(1, tx.MIX, {4: rgb, 5: rgb}, cls="Mix")
                    self.close(self._root(rule, own, kind=tx.DATA).a.value, want)

    def test_mask_constant_by_the_graph(self):
        grey = (64 / 255,) * 3
        mix = FakeMap(1, tx.MIX, {8: Ref(2)}, [2], cls="Mix")
        vc = FakeMap(2, classids.VRAY_COLOR, {5: grey}, cls="VRayColor")
        for rule in self.RULES:
            with self.subTest(rule):
                self.close(self._root(rule, mix, vc).mask.value, rule.channel(64 / 255),
                           "in a color graph: the rule (maxdrop-em3.36)")
                self.close(self._root(rule, mix, vc, kind=tx.DATA).mask.value, 64 / 255, "in a data graph: stored")

    def test_bitmap_on_a_data_input(self):
        cases = ((colors.GAMMA_ON, None, None, tx.SRGB), (colors.UNKNOWN, None, None, tx.SRGB),
                 (colors.GAMMA_ON, _info(2.2, 5), 2.2, tx.SRGB), (colors.GAMMA_ON, _info(1.0, 5), 1.0, tx.NON_COLOR),
                 (self.ON_18, None, 1.8, tx.LINEAR),
                 (colors.GAMMA_OFF, None, None, tx.NON_COLOR), (colors.GAMMA_OFF, _info(2.2, 5), None, tx.NON_COLOR),
                 (colors.GAMMA_OFF, _info(1.0, 5), None, tx.NON_COLOR))
        for rule, info, gamma, space in cases:
            with self.subTest(rule=rule, info=info):
                b, chunk_map = _placed(info=info)
                image = self._root(rule, b, kind=tx.DATA, chunk_map=chunk_map)
                self.assertEqual(image.colorspace, space)
                self.assertEqual(image.gamma is None, gamma is None)
                if gamma is not None:
                    self.close(image.gamma, gamma)

    def test_bitmap_mask(self):
        mix = FakeMap(1, tx.MIX, {8: Ref(2)}, [2], cls="Mix")
        for rule, info, space in ((colors.GAMMA_ON, None, tx.SRGB), (colors.GAMMA_ON, _info(1.0, 5), tx.NON_COLOR),
                                  (colors.GAMMA_OFF, None, tx.SRGB), (colors.GAMMA_OFF, _info(1.0, 5), tx.SRGB)):
            with self.subTest(rule=rule, info=info):
                b, chunk_map = _placed(index=2, info=info)
                self.assertEqual(self._root(rule, mix, b, chunk_map=chunk_map).mask.colorspace, space)
        b, chunk_map = _placed(index=2)
        self.assertEqual(self._root(colors.GAMMA_OFF, mix, b, kind=tx.DATA, chunk_map=chunk_map).mask.colorspace,
                         tx.NON_COLOR, "a mask in a data graph: data")
        cmix = _cmix(1, [2], p200=6, p210=Ref(2))
        for kind in (tx.COLOR, tx.DATA):  # COLOR: on stored values under a Decode, the mask as data (em3.165)
            root = self._root(colors.GAMMA_OFF, cmix, _bitmap(2), kind=kind)
            root = root.input if kind == tx.COLOR else root
            self.assertEqual(tx.first_image(root.mask).colorspace, tx.NON_COLOR, "CoronaMix mask")
        root = self._root(colors.GAMMA_ON, cmix, _bitmap(2))
        self.assertEqual(tx.first_image(root.mask).colorspace, tx.SRGB, "gamma on: decoded")

    def test_composite_mask_follows_the_graph(self):
        comp = FakeMap(1, tx.COMPOSITE, {9: [Ref(2), Ref(3)], 10: [Ref(None), Ref(4)]}, [2, 3, 4], cls="Composite")
        for rule, kind, space in ((colors.GAMMA_ON, tx.COLOR, tx.SRGB), (colors.GAMMA_OFF, tx.DATA, tx.NON_COLOR),
                                  (colors.GAMMA_OFF, tx.COLOR, tx.NON_COLOR)):  # off: as stored (em3.158)
            root = self._root(rule, comp, _bitmap(2), _bitmap(3), _bitmap(4), kind=kind)
            root = root.input if isinstance(root, tx.Decode) else root
            self.assertEqual(root.layers[1].mask.colorspace, space, (rule, kind))

    def test_vray_and_corona_bitmaps_on_a_data_input(self):
        # gamma off: CoronaBitmap auto / 2.2 renders 0.2195, VRayBitmap sRGB 0.2159 (their own curve), VRayBitmap
        # From 3ds Max and None 0.502; gamma on: From 3ds Max 0.2195, the others as off
        cases = ((_vbitmap(1, p25=2), tx.SRGB, tx.SRGB), (_vbitmap(1, p25=3), tx.NON_COLOR, tx.SRGB),
                 (_vbitmap(1, p25=0), tx.NON_COLOR, tx.NON_COLOR), (_cbitmap(1), tx.SRGB, tx.SRGB),
                 (_cbitmap(1, p125=2.2), tx.SRGB, tx.SRGB), (_cbitmap(1, p125=1.0), tx.NON_COLOR, tx.NON_COLOR),
                 (_vbitmap(1, p25=1, p8=2.0), tx.LINEAR, tx.LINEAR))  # inverse gamma 2: pixel ^ 0.5
        for m, off, on in cases:
            with self.subTest(cls=m.cls, params=m.blocks[0]._params):
                self.assertEqual(self._root(colors.GAMMA_OFF, m, kind=tx.DATA).colorspace, off)
                self.assertEqual(self._root(colors.GAMMA_ON, m, kind=tx.DATA).colorspace, on)


class NormalAndBumpImages(Checks):
    """maxdrop-em3.159, V-Ray 5.2 and Corona 12 renders of 8-bit normal and height PNGs (docs/FORMAT.md, Scene
    gamma): a normal or bump input takes an image as a data input does (em3.122). A Bitmap is decoded by its gamma
    with the gamma on (a flat (128, 128, 255) under auto or 2.2 renders (-0.44, -0.44, 0.78)) and as stored with 1.0
    or with the gamma off; a CoronaBitmap by its own gamma in both modes; a VRayBitmap under a normal map as stored
    whatever its transfer function, as a height by it (From 3ds Max as stored with the gamma off). CoronaNormal's add
    gamma re-encodes its input by 1 / 2.2 with the gamma on and does nothing with it off."""

    ON_18 = colors.Swatches(True, file_in=1.8)
    NORMAL_MAPS = (lambda n: _vnormal(1, n),
                   lambda n: FakeMap(1, tx.NORMAL_BUMP, {2: Ref(n), 4: 1, 0: 1.0}, [n], cls="Normal Bump"))

    def _convert(self, rule, *objects, kind=tx.NORMAL, chunk_map=None):
        tex = tx.TexmapConverter(FakeGraph(*objects, chunk_map=chunk_map), _table(), swatches=rule)
        return tex.convert(mat.MapRef(objects[0].index), kind)

    def _image(self, rule, *objects, kind=tx.NORMAL, chunk_map=None):
        return tx.first_image(self._convert(rule, *objects, kind=kind, chunk_map=chunk_map).root)

    def test_bitmap_takes_the_data_rule(self):
        cases = ((colors.GAMMA_ON, None, None, tx.SRGB), (colors.UNKNOWN, None, None, tx.SRGB),
                 (colors.GAMMA_ON, _info(2.2, 5), 2.2, tx.SRGB), (colors.GAMMA_ON, _info(1.0, 5), 1.0, tx.NON_COLOR),
                 (self.ON_18, None, 1.8, tx.LINEAR),
                 (colors.GAMMA_OFF, None, None, tx.NON_COLOR), (colors.GAMMA_OFF, _info(2.2, 5), None, tx.NON_COLOR),
                 (colors.GAMMA_OFF, _info(1.0, 5), None, tx.NON_COLOR))
        for rule, info, gamma, space in cases:
            for kind in (tx.BUMP, tx.NORMAL):
                for wrap in self.NORMAL_MAPS if kind == tx.NORMAL else (None,):
                    with self.subTest(rule=rule, info=info, kind=kind, wrap=wrap):
                        b, chunk_map = _placed(index=2 if wrap else 1, info=info)
                        objects = (wrap(2), b) if wrap else (b,)
                        image = self._image(rule, *objects, kind=kind, chunk_map=chunk_map)
                        self.assertEqual(image.colorspace, space)
                        self.assertEqual(image.gamma is None, gamma is None)
                        if gamma is not None:
                            self.close(image.gamma, gamma)

    def test_bitmap_below_a_normal_map_in_a_bump_input(self):
        b, chunk_map = _placed(index=2)
        vn = FakeMap(1, classids.VRAY_NORMAL_MAP, {4: Ref(2), 5: 1, 6: 1.0}, [2], cls="VRayNormalMap")
        for rule, space in ((colors.GAMMA_ON, tx.SRGB), (colors.GAMMA_OFF, tx.NON_COLOR)):
            with self.subTest(rule=rule):
                self.assertEqual(self._image(rule, vn, b, chunk_map=chunk_map).colorspace, space)

    def test_corona_bitmap_by_its_own_gamma(self):
        for rule in (colors.GAMMA_ON, colors.GAMMA_OFF):
            for params, space in (({}, tx.SRGB), ({"p125": 2.2}, tx.SRGB), ({"p125": 1.0}, tx.NON_COLOR)):
                for kind in (tx.NORMAL, tx.BUMP):
                    with self.subTest(rule=rule, params=params, kind=kind):
                        image = _cbitmap(2 if kind == tx.NORMAL else 1, **params)
                        objects = (_vnormal(1, 2), image) if kind == tx.NORMAL else (image,)
                        self.assertEqual(self._image(rule, *objects, kind=kind).colorspace, space)

    def test_vray_bitmap_under_a_normal_map_as_stored(self):
        for rule in (colors.GAMMA_ON, colors.GAMMA_OFF):
            for space in (0, 1, 2, 3, 4):
                for wrap in self.NORMAL_MAPS:
                    with self.subTest(rule=rule, space=space, wrap=wrap):
                        g = self._convert(rule, wrap(2), _vbitmap(2, p25=space, p8=0.5))
                        image = tx.first_image(g.root)
                        self.assertEqual(image.colorspace, tx.NON_COLOR)
                        self.assertEqual(image.gamma, 1.0)
                        self.assertEqual(g.issues, (), "its transfer function is not used: no issue")

    def test_vray_bitmap_height_by_its_transfer_function(self):
        cases = ((2, tx.SRGB, tx.SRGB), (3, tx.NON_COLOR, tx.SRGB), (0, tx.NON_COLOR, tx.NON_COLOR))
        for space, off, on in cases:
            with self.subTest(space=space):
                self.assertEqual(self._image(colors.GAMMA_OFF, _vbitmap(1, p25=space), kind=tx.BUMP).colorspace, off)
                self.assertEqual(self._image(colors.GAMMA_ON, _vbitmap(1, p25=space), kind=tx.BUMP).colorspace, on)

    def _cnormal(self, add, child=2):
        return FakeMap(1, tx.CORONA_NORMAL, {500: Ref(child), 501: 1.0, 502: int(add)}, [child], cls="CoronaNormal")

    def test_corona_normal_add_gamma_with_the_gamma_on(self):
        b, chunk_map = _placed(index=2)
        cases = (((b,), chunk_map, tx.NON_COLOR, 1.0), ((_cbitmap(2),), None, tx.NON_COLOR, 1.0),
                 ((_cbitmap(2, p125=1.0),), None, tx.LINEAR, 1 / 2.2),
                 ((_cbitmap(2, p125=2.2),), None, tx.NON_COLOR, 1.0))
        for objects, cm, space, gamma in cases:
            with self.subTest(cls=objects[0].cls, params=objects[0].blocks[0]._params):
                g = self._convert(colors.GAMMA_ON, self._cnormal(True), *objects, chunk_map=cm)
                self.assertEqual(g.root.input.colorspace, space)
                self.close(g.root.input.gamma, gamma)
                self.assertEqual(g.issues, ())
                self.assertIs(tx.drawn_gamma(g.root.input) is not None, space == tx.LINEAR)
        b1, cm1 = _placed(index=2, info=_info(1.0, 5))
        g = self._convert(colors.GAMMA_ON, self._cnormal(True), b1, chunk_map=cm1)
        self.assertEqual((g.root.input.colorspace, g.root.input.gamma), (tx.LINEAR, 1 / 2.2), "1.0: brighter")
        g = self._convert(colors.GAMMA_ON, self._cnormal(False), _cbitmap(2))
        self.assertEqual(g.root.input.colorspace, tx.SRGB, "add gamma off: decoded")

    def test_corona_normal_add_gamma_with_the_gamma_off_does_nothing(self):
        b, chunk_map = _placed(index=2)
        for objects, cm, space in (((b,), chunk_map, tx.NON_COLOR), ((_cbitmap(2),), None, tx.SRGB)):
            with self.subTest(cls=objects[0].cls):
                g = self._convert(colors.GAMMA_OFF, self._cnormal(True), *objects, chunk_map=cm)
                self.assertEqual(g.root.input.colorspace, space)
                self.assertEqual(g.issues, ())

    def test_corona_normal_add_gamma_over_a_graph_is_reported(self):
        mix = FakeMap(2, tx.MIX, {6: Ref(3)}, [3], cls="Mix")
        g = self._convert(colors.GAMMA_ON, self._cnormal(True), mix, _cbitmap(3))
        self.assertTrue(any("add gamma" in r for r in g.issues), g.issues)

    def test_corona_normal_add_gamma_not_folded_past_an_output_or_alpha(self):
        # the builder applies an image's gamma before its Output and not to its alpha: Corona's re-encode comes after
        for child in (_vbitmap(2, p25=2, p1=2.0), _cbitmap(2, p118=1)):
            with self.subTest(cls=child.cls):
                g = self._convert(colors.GAMMA_ON, self._cnormal(True), child)
                self.assertIn(g.root.input.gamma, (None, 1.0), "left as without add gamma")
                self.assertTrue(any("add gamma" in r for r in g.issues), g.issues)

    def test_vray_bitmap_below_a_corona_normal_that_adds_gamma(self):
        g = self._convert(colors.GAMMA_ON, self._cnormal(True), _vbitmap(2, p25=2))
        self.assertEqual((g.root.input.colorspace, g.root.input.gamma), (tx.LINEAR, 1 / 2.2), "stored, raised")
        self.assertEqual(g.issues, ())


_dec = colors.srgb_to_linear


def _drawn(n, pixel=128 / 255):
    """What the builder draws for a leaf of a stored graph or a color root at one pixel value: an Image by its color
    space and gamma, a Constant's mean."""
    if isinstance(n, tx.Constant):
        return sum(_rgb(n.value)) / 3.0
    if n.colorspace == tx.SRGB:
        return _dec(pixel)
    return pixel ** (n.gamma or 1.0) if n.colorspace == tx.LINEAR else pixel


def _decodes(root):
    """The Decode nodes of a graph."""
    seen, stack, out = set(), [root], []
    while stack:
        n = stack.pop()
        if n is None or id(n) in seen:
            continue
        seen.add(id(n))
        if isinstance(n, tx.Decode):
            out.append(n)
        stack.extend(tx._children(n))
    return out


class GammaOffMixes(Checks):
    """maxdrop-em3.158, V-Ray 5.2 renders (docs/FORMAT.md, Scene gamma): with the gamma off V-Ray computes a Mix or
    Composite on the stored values (its internal value is the gamma-on one: a Mix of greys 40 -> 220 at 50 % renders
    0.510 in both modes) and the display-referred scene shows it decoded (0.223 linear). In a color graph such a map
    is converted in the kind STORED under one Decode; a Mix between its colors black and white stays as before."""

    G40, G220 = (40 / 255,) * 3, (220 / 255,) * 3

    def _root(self, rule, *objects, kind=tx.COLOR, table=None):
        tex = tx.TexmapConverter(FakeGraph(*objects), _table() if table is None else table, swatches=rule)
        g = tex.convert(mat.MapRef(objects[0].index), kind)
        return None if g is None else g.root

    def _mix(self, **params):
        return FakeMap(1, tx.MIX, {int(k[1:]): v for k, v in params.items()},
                       [v.index for v in params.values() if isinstance(v, Ref) and v.index is not None], cls="Mix")

    def test_constant_mix_is_folded_decoded(self):
        # Mix 40 -> 220 at 50 % renders 0.5098 with the gamma off: srgb_to_linear of it; by a VRayColor 128 mask 0.5112
        mix = self._mix(p0=0.5, p4=self.G40, p5=self.G220)
        self.close(self._root(colors.GAMMA_OFF, mix).value, (_dec(0.509804),) * 3)
        masked = self._mix(p0=0.0, p4=self.G40, p5=self.G220, p8=Ref(2))
        vc = _vcolor(2, (128 / 255,) * 3)
        t = 128 / 255

        def lerp(a, b):
            return _dec((a + (b - a) * t) / 255)
        self.close(self._root(colors.GAMMA_OFF, masked, vc).value, (lerp(40, 220),) * 3, "mask taken as stored")
        self.assertAlmostEqual(lerp(40, 220), _dec(0.511177), delta=1e-4)
        rb = self._mix(p0=0.0, p4=(200 / 255, 40 / 255, 40 / 255), p5=(40 / 255, 60 / 255, 220 / 255), p8=Ref(2))
        want = (lerp(200, 40), lerp(40, 60), lerp(40, 220))  # V-Ray: 0.469352, 0.196231, 0.511177
        self.close(self._root(colors.GAMMA_OFF, rb, vc).value, want, "per channel")

    def test_gamma_on_and_unknown_are_unchanged(self):
        mix = self._mix(p0=0.5, p4=self.G40, p5=self.G220, p6=Ref(2), p8=Ref(3))
        comp = FakeMap(1, tx.COMPOSITE, {8: [100.0, 50.0], 9: [Ref(2), Ref(3)]}, [2, 3], cls="Composite")
        for rule in (colors.GAMMA_ON, colors.UNKNOWN):
            with self.subTest(rule):
                root = self._root(rule, mix, _bitmap(2), _vcolor(3, (0.5,) * 3))
                self.assertIsInstance(root, tx.Mix)
                self.close(root.b.value, self.G220)
                self.close(root.mask.value, 0.5)
                self.assertEqual(_decodes(root), [])
                self.assertIsInstance(self._root(rule, comp, _bitmap(2), _vcolor(3, (0.5,) * 3)), tx.Composite)

    def test_data_and_mask_graphs_are_unchanged(self):
        mix = self._mix(p0=0.5, p4=self.G40, p5=self.G220, p6=Ref(2))
        for kind in (tx.DATA, tx.MASK):
            with self.subTest(kind):
                root = self._root(colors.GAMMA_OFF, mix, _bitmap(2), kind=kind)
                self.assertIsInstance(root, tx.Mix)
                self.assertEqual(_decodes(root), [])

    def test_mix_with_a_map_is_decoded_once(self):
        mix = self._mix(p0=0.25, p4=self.G40, p5=self.G220, p6=Ref(2), p8=Ref(3))
        root = self._root(colors.GAMMA_OFF, mix, _bitmap(2), _bitmap(3))
        self.assertIsInstance(root, tx.Decode)
        inner = root.input
        self.assertIsInstance(inner, tx.Mix)
        self.assertEqual(inner.a.colorspace, tx.NON_COLOR, "a Bitmap as stored")
        self.assertIsNone(inner.a.gamma)
        self.assertFalse(inner.a.alpha)
        self.close(inner.b.value, self.G220, "a swatch as stored")
        self.assertEqual(inner.mask.colorspace, tx.NON_COLOR, "the mask as stored (a data mask)")
        self.close(inner.factor, 0.25)

    def test_nested_mix_is_not_decoded_again(self):
        outer = self._mix(p0=0.5, p4=self.G40, p6=Ref(2))
        inner = FakeMap(2, tx.MIX, {0: 0.5, 5: self.G220, 6: Ref(3)}, [3], cls="Mix")
        root = self._root(colors.GAMMA_OFF, outer, inner, _bitmap(3))
        self.assertIsInstance(root, tx.Decode)
        self.assertEqual(len(_decodes(root)), 1)
        self.assertIsInstance(root.input.a, tx.Mix)
        self.close(root.input.a.b.value, self.G220)
        self.assertEqual(root.input.a.a.colorspace, tx.NON_COLOR)

    def test_black_to_white_stays_exact(self):
        # maxdrop-em3.36: a mask between black and white is the decoded number (byte 64 renders 64): unchanged; the
        # mix amount the same way (V-Ray renders 0.502 at 50 %, shown from 0.2159)
        by_mask = self._mix(p8=Ref(2))
        root = self._root(colors.GAMMA_OFF, by_mask, _vcolor(2, (128 / 255,) * 3))
        self.assertIsInstance(root, tx.Mix)
        self.close(root.a.value, (0.0,) * 3)
        self.close(root.b.value, (1.0,) * 3)
        self.close(root.mask.value, _lin(128))
        root = self._root(colors.GAMMA_OFF, self._mix(p8=Ref(2)), _bitmap(2))
        self.assertEqual(root.mask.colorspace, tx.SRGB)
        root = self._root(colors.GAMMA_OFF, self._mix(p0=0.5))
        self.assertIsInstance(root, tx.Mix)
        self.close(root.factor, _lin(127.5))
        self.close(self._root(colors.GAMMA_ON, self._mix(p0=0.5)).factor, 0.5)

    def test_a_map_mixed_with_itself_shows_as_alone(self):
        exr = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\a.exr", "")])
        cases = (("Bitmap", _bitmap(2), None, tx.NON_COLOR), ("Bitmap EXR", _bitmap(2), exr, tx.NON_COLOR),
                 ("VRayBitmap sRGB", _vbitmap(2, p25=2), None, tx.SRGB),
                 ("VRayBitmap From 3ds Max", _vbitmap(2, p25=3), None, tx.NON_COLOR),
                 ("VRayBitmap None", _vbitmap(2, p25=0), None, tx.NON_COLOR),
                 ("CoronaBitmap auto", _cbitmap(2), None, tx.SRGB),  # its own decode (maxdrop-em3.165)
                 ("CoronaBitmap 1.0", _cbitmap(2, p125=1.0), None, tx.NON_COLOR))
        for what, leaf, table, space in cases:
            with self.subTest(what):
                mix = self._mix(p0=0.5, p6=Ref(2), p7=Ref(2))
                root = self._root(colors.GAMMA_OFF, mix, leaf, table=table)
                self.assertIsInstance(root, tx.Decode)
                stored = root.input.a
                self.assertEqual(stored.colorspace, space)
                alone = self._root(colors.GAMMA_OFF, leaf, table=table)
                for pixel in (0.25, 128 / 255, 0.75):
                    self.assertAlmostEqual(_drawn(stored, pixel) ** tx.SRGB_GAMMA, _drawn(alone, pixel), delta=0.01,
                                           msg="%s at %g" % (what, pixel))
        hdr = _ccolor(2, p50=1, p58=(0.5, 2.0, 0.0))
        self.close(self._root(colors.GAMMA_OFF, self._mix(p0=0.5, p6=Ref(2), p7=Ref(2)), hdr).value,
                   (0.2140411, 4.9538458, 0.0), "CoronaColor HDR: as at a color root (decoded, maxdrop-em3.165)")
        self.close(self._root(colors.GAMMA_OFF, hdr).value, (0.2140411, 4.9538458, 0.0))
        vc = _vcolor(2, (128 / 255,) * 3)
        self.close(self._root(colors.GAMMA_OFF, self._mix(p0=0.5, p6=Ref(2), p7=Ref(2)), vc).value,
                   (_lin(128),) * 3)

    def test_collapsed_results(self):
        lost = self._mix(p0=0.5, p6=Ref(2), p7=Ref(3))
        root = self._root(colors.GAMMA_OFF, lost, _bitmap(2), _noise(3))
        self.assertIsInstance(root, tx.Image, "peeled to its other side: that image as a color")
        self.assertEqual(root.colorspace, tx.SRGB)
        single = FakeMap(1, tx.COMPOSITE, {9: [Ref(2)]}, [2], cls="Composite")
        self.close(self._root(colors.GAMMA_OFF, single, _vcolor(2, (128 / 255,) * 3)).value, (_lin(128),) * 3)
        self.assertEqual(self._root(colors.GAMMA_OFF, single, _bitmap(2)).colorspace, tx.SRGB)

    def test_composite_on_stored_values(self):
        # Composite 64 + 64 in Addition renders 0.502 (both modes): shown from 0.2159 with the gamma off
        comp = FakeMap(1, tx.COMPOSITE, {5: [0, tx.ADDITION], 8: [100.0, 50.0], 9: [Ref(2), Ref(3)],
                                         10: [Ref(None), Ref(4)]}, [2, 3, 4], cls="Composite")
        root = self._root(colors.GAMMA_OFF, comp, _bitmap(2), _vcolor(3, (64 / 255,) * 3), _bitmap(4))
        self.assertIsInstance(root, tx.Decode)
        layers = root.input.layers
        self.assertEqual(layers[0].node.colorspace, tx.NON_COLOR)
        self.close(layers[1].node.value, (64 / 255,) * 3)
        self.assertEqual(layers[1].blend, tx.ADDITION)
        self.close(layers[1].opacity, 0.5)
        self.assertEqual(layers[1].mask.colorspace, tx.NON_COLOR)

    def test_hdr_mask_is_clamped_when_folded(self):
        hdr = _ccolor(2, p50=1, p58=(2.0, 2.0, 2.0))  # a data mask above 1: a Mix node clamps its factor
        mix = self._mix(p4=self.G40, p5=self.G220, p8=Ref(2))
        self.close(self._root(colors.GAMMA_OFF, mix, hdr).value, (_lin(220),) * 3)

    def test_corona_mix_on_stored_values(self):
        # maxdrop-em3.165, Corona 12 renders: a CoronaMix is computed on the values Corona holds, the same in both
        # modes (a 50 % mix of CoronaBitmaps 64 and 192 renders 0.2917): STORED under a Decode with the gamma off
        both = _cmix(1, [2, 3], p200=6, p201=0.5, p206=Ref(2), p207=Ref(3))
        root = self._root(colors.GAMMA_OFF, both, _cbitmap(2), _cbitmap(3))
        self.assertIsInstance(root, tx.Decode)
        self.assertIsInstance(root.input, tx.Mix)
        self.assertEqual([(i.gamma, i.colorspace) for i in (root.input.a, root.input.b)], [(None, tx.SRGB)] * 2,
                         "each CoronaBitmap by its own decode")
        self.assertIsInstance(self._root(colors.GAMMA_ON, both, _cbitmap(2), _cbitmap(3)), tx.Mix, "gamma on: as is")
        hdr = _cmix(1, [2, 3], p200=10, p206=Ref(2), p207=Ref(3))  # overlay of two HDR colors, folded
        value = self._root(colors.GAMMA_OFF, hdr, _ccolor(2, p50=1, p58=(0.6, 0.2, 0.75)),
                           _ccolor(3, p50=1, p58=(0.05, 0.4, 0.9))).value
        held = tx.blend_value(tx.BLEND_OVERLAY, (0.05, 0.4, 0.9), (0.6, 0.2, 0.75), tx.CM_SRGB_GAMMA)
        self.close(value, tuple(colors.srgb_to_linear(c) for c in held))
        # a peel (an operation not drawn) and a lost side give the image again as a color: shown decoded once more
        peel = _cmix(1, [2, 3], p200=15, p206=Ref(2), p207=Ref(3))
        lost = _cmix(1, [2, 3], p200=6, p201=0.5, p207=Ref(2), p206=Ref(3))
        for what, objects in (("peel", (peel, _cbitmap(2), _noise(3))), ("lost", (lost, _noise(2), _cbitmap(3)))):
            with self.subTest(what):
                image = self._root(colors.GAMMA_OFF, *objects)
                self.assertIsInstance(image, tx.Image)
                self.assertEqual((image.gamma, image.colorspace), (tx.SRGB_TWICE, tx.LINEAR))

    def test_maps_below_a_gamma_off_mix_compute_on_stored_values(self):
        # not measured (maxdrop-6n0.6.18): pinned so a change is deliberate
        g = (128 / 255,) * 3
        falloff = _falloff(2, color1=g)
        cmix = _cmix(3, p200=0, p208=g, p209=g)  # an add in sRGB mode of two greys 128
        mix = self._mix(p0=0.5, p6=Ref(2), p7=Ref(3))
        root = self._root(colors.GAMMA_OFF, mix, falloff, cmix)
        self.assertIsInstance(root, tx.Decode)
        self.close(root.input.a.a.value, g, "the Falloff's color 1 as stored")
        self.close(root.input.b.value, tx.blend_value(tx.BLEND_ADD, g, g, tx.CM_SRGB_GAMMA), "Corona's add, as stored")

    def test_cut_graph_takes_its_image_as_a_color(self):
        layers, depth = 10, tx.MAX_DEPTH
        objects = [FakeMap(k, tx.COMPOSITE, {9: [Ref(k + 1)] * layers}, [k + 1], cls="Composite")
                   for k in range(1, depth)] + [_bitmap(depth)]
        root = self._root(colors.GAMMA_OFF, *objects)
        self.assertIsInstance(root, tx.Image)
        self.assertEqual(root.colorspace, tx.SRGB)


class TexmapWrappers(Checks):
    """tools/fixtures/texmap_wrappers.ms, against the parameters its oracle (3ds Max) reports for each map."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("texmap_wrappers")
        with open(os.path.join(FIXTURE_DIR, "texmap_wrappers.oracle.json"), encoding="utf-8") as fh:
            graph = json.load(fh)["material_graph"]
        cls.oracle = collections.defaultdict(list)  # class name -> [{param name: value}] in graph order
        for item in graph:
            params = {p["name"]: p["value"] for b in item["blocks"] for p in b["params"] if p["name"]}
            cls.oracle[item["class_name"]].append(dict(params, _name=item["name"]))

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def params(self, cls, name):
        return next(p for p in self.oracle[cls] if p["_name"] == name)

    def test_falloff_perpendicular_with_a_map_amount(self):
        o = self.params("falloff", "FixtureFoPerp")
        self.assertEqual((o["type"], o["direction"]), (1, 0))
        g = self.f.irs["FixtureWrapFalloff"].textures["base_color"]
        self.assertFalse(g.approximated)
        self.assertEqual(g.root.mask, tx.Facing(tx.PERPENDICULAR, 1.6))
        side1 = g.root.a
        self.close(side1.factor, o["map1Amount"] / 100.0)
        self.close(side1.a.value, tuple(_lin(c * 255) for c in o["color1"]))
        self.image(side1.b, "wrap_fo_map.png", tx.SRGB)
        self.close(g.root.b.value, tuple(_lin(c * 255) for c in o["color2"]))

    def test_falloff_fresnel_and_towards(self):
        o = self.params("falloff", "FixtureFoFresnel")
        t = self.f.irs["FixtureWrapFalloff"].textures
        self.assertEqual(t["specular"].root.mask.mode, tx.FRESNEL)
        self.close(t["specular"].root.mask.ior, o["ior"])
        o = self.params("falloff", "FixtureFoTowards")
        self.assertEqual(o["type"], 0)
        g = t["emission_color"].root
        self.assertEqual(g.mask, tx.Facing(tx.TOWARDS, 1.6))
        self.close((g.a.value, g.b.value), (tuple(o["color1"]), tuple(o["color2"])))

    def test_falloff_other_type_and_direction_are_peeled(self):
        t = self.f.irs["FixtureWrapFalloff"].textures
        self.assertEqual((self.params("falloff", "FixtureFoLocalX")["direction"],
                          self.params("falloff", "FixtureFoShadow")["type"]), (1, 3))
        self.image(t["alpha"].root, "wrap_fo_dir.png", tx.NON_COLOR)
        self.assertTrue(t["alpha"].approximated)
        g = t["roughness"]  # a glossiness map: inverted; shadow / light without a map: its color 1
        self.close(g.root.input.value, 100 / 255.0)  # a data input: as stored
        self.assertTrue(g.approximated)

    def test_composite_blend_modes_and_mask(self):
        o = self.oracle["CompositeTexturemap"][0]
        g = self.f.irs["FixtureWrapComposite"].textures["base_color"]
        self.assertFalse(g.approximated)
        self.assertIsInstance(g.root, tx.Decode)  # gamma off: composited on the stored values (em3.158)
        layers = g.root.input.layers
        self.assertEqual([la.node.name for la in layers], ["wrap_comp_base.png", "wrap_comp_mul.png",
                                                           "wrap_comp_over.png", "wrap_comp_screen.png"])
        self.assertEqual([la.blend for la in layers], o["blendMode"])
        self.close(tuple(la.opacity for la in layers), tuple(v / 100.0 for v in o["opacity"]))
        self.assertEqual([la.mask is not None for la in layers], [False, False, True, False])
        self.assertEqual(layers[2].mask.mask, tx.Facing(), "the mask Falloff, a data Mix by its Facing")
        g = self.f.irs["FixtureWrapComposite"].textures["emission_color"]
        top = g.root.input.layers[1]
        self.assertEqual(top.blend, tx.SPOTLIGHT_BLEND)
        self.image(top.mask, "wrap_spot_mask.png", tx.NON_COLOR)  # as stored

    def test_composite_soft_light_is_peeled(self):
        self.assertEqual(self.oracle["CompositeTexturemap"][1]["blendMode"], [0, 15])
        g = self.f.irs["FixtureWrapComposite"].textures["specular"]
        self.image(g.root, "wrap_soft_base.png", tx.SRGB)
        self.assertTrue(g.approximated)

    def test_color_correction_rewiring(self):
        t = self.f.irs["FixtureWrapColor"].textures
        for slot, name in (("base_color", "FixtureCCMono"), ("specular", "FixtureCCInvert"),
                           ("emission_color", "FixtureCCCustom")):
            o = self.params("Color_Correction", name)
            self.assertEqual(t[slot].root.rewire, (o["rewireR"], o["rewireG"], o["rewireB"]), name)
            self.assertFalse(t[slot].approximated, name)
        self.close(t["specular"].root.brightness, 0.2)

    def test_output_and_tint(self):
        t = self.f.irs["FixtureWrapOutput"].textures
        out = t["base_color"].root.output
        self.assertTrue(out.invert)
        self.close((out.amount, out.level, out.offset), (0.5, 2.0, 0.1))
        self.image(t["base_color"].root.input, "wrap_out.png", tx.SRGB)
        o = self.params("RGB_Tint", "FixtureTint")
        tint = t["specular"].root
        self.assertIsInstance(tint, tx.Tint)
        self.close(tint.red, tuple(_lin(c * 255) for c in o["red"]))
        self.close((tint.green, tint.blue), ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
        self.image(t["emission_color"].root, "wrap_out_plain.png", tx.SRGB)  # an Output with its defaults

    def test_counts(self):
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter({"Falloff": 2, "Composite": 1}))
        self.assertEqual(self.f.tex.stats.unsupported, collections.Counter())
        self.assertEqual(len(self.f.tex.stats.issues), 3, self.f.tex.stats.issues)


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


class TruncatedClassDirectory(unittest.TestCase):
    """A class directory cut short: the objects whose class index is past its end have no entry. graph.get turns
    them away (a ChunkError), as it does an index past the objects, so every map it hands the converter is an object
    of the scene with an entry, and _class_name, which has no IndexError net, cannot raise."""

    def test_class_name_of_every_map_graph_get_returns(self):
        with cfb.CompoundFile(os.path.join(FIXTURE_DIR, "texmap_rules.max")) as cf:
            full = classdir.ClassDirectory.from_file(cf)
            counts = []
            for keep in sorted({0, len(full) // 4, len(full) // 2, len(full) - 1, len(full)}):
                scene = reader_scene.Scene.from_file(cf, classdir.ClassDirectory(list(full)[:keep], full.dlls))
                graph = reader_materials.MaterialGraph(scene)
                tex = tx.TexmapConverter(graph)
                got = 0
                for i in range(len(scene) + 2):
                    try:
                        m = graph.get(i)
                    except chunks.ChunkError:
                        continue
                    self.assertLess(scene.class_index(i), keep, "object %d kept %d classes" % (i, keep))
                    self.assertTrue(tex._class_name(m), "object %d kept %d classes" % (i, keep))
                    got += 1
                counts.append(got)
            self.assertEqual(counts[0], 0)
            self.assertGreater(counts[-1], counts[0])


def _polyline_at(points, x):
    """A Remap's polyline at x: straight between the points, flat past the ends (as the Float Curve draws it)."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y1 if x1 <= x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


class FalloffCurve(Checks):
    """falloff_curve: each Falloff's MixCurve and each Mix's Use Curve against 3ds Max 2020's own values
    (tests/fixtures/falloff_curve.curves.jsonl, written by tools/fixtures/falloff_curve.ms from the saved file: 65
    values at x = k / 64)."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("falloff_curve")
        with open(os.path.join(FIXTURE_DIR, "falloff_curve.curves.jsonl"), encoding="ascii") as f:
            cls.records = {r["name"]: r for r in map(json.loads, f)}
        cls.rows = {name: r["y"] for name, r in cls.records.items()}

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def root(self, name):
        ir = self.f.irs[name]
        self.assertEqual(list(ir.issues), [], name)
        return ir.textures["base_color"].root

    def test_every_map_has_a_row(self):
        self.assertEqual(set(self.rows), set(self.f.irs))
        self.assertTrue(all(len(y) == 65 for y in self.rows.values()))

    def test_falloff_curves_match_3ds_max(self):
        modes = {"FixtureCurveBezier": tx.PERPENDICULAR, "FixtureCurveCorner": tx.TOWARDS,
                 "FixtureCurveOvershoot": tx.FRESNEL, "FixtureCurveClamped": tx.PERPENDICULAR,
                 "FixtureCurveJump": tx.PERPENDICULAR}
        for name, mode in modes.items():
            with self.subTest(name):
                root = self.root(name)
                self.assertIsInstance(root, tx.Mix)
                self.assertIsInstance(root.mask, tx.Remap)
                self.assertEqual(root.mask.input.mode, mode)
                points = root.mask.points
                self.assertEqual([x for x, _y in points], sorted(x for x, _y in points))
                for k, y in enumerate(self.rows[name]):
                    self.assertAlmostEqual(_polyline_at(points, k / 64.0), y, delta=1e-3, msg=(name, k))
        self.assertEqual(len(self.root("FixtureCurveCorner").mask.points), 4, "corner points: straight segments")
        self.assertGreater(max(self.rows["FixtureCurveOvershoot"]), 1.19, "3ds Max does not clamp the curve")
        self.assertGreater(max(y for _x, y in self.root("FixtureCurveOvershoot").mask.points), 1.19)

    def test_jump(self):
        """FixtureCurveJump: two points at x = 32.5 / 64 (a falling jump) stay in 3ds Max's order, one beside the
        other, and 3ds Max's curve is on either side of the jump at the samples next to it."""
        x = 32.5 / 64
        points = list(self.root("FixtureCurveJump").mask.points)
        at = [k for k, p in enumerate(points) if p[0] == x]
        self.assertEqual(len(at), 2, points)
        self.assertEqual(at[1], at[0] + 1)
        self.assertAlmostEqual(points[at[0]][1], 0.8, places=6)
        self.assertAlmostEqual(points[at[1]][1], 0.3, places=6)
        y = self.rows["FixtureCurveJump"]
        self.assertGreater(y[32], 0.7)
        self.assertLess(y[33], 0.4)

    def test_linear_curve_makes_no_node(self):
        self.assertEqual(self.root("FixtureCurveLinear").mask, tx.Facing(tx.PERPENDICULAR, 1.6))
        self.assertTrue(all(abs(y - k / 64.0) < 1e-5 for k, y in enumerate(self.rows["FixtureCurveLinear"])))

    def test_mix_curves_match_3ds_max(self):
        for name in ("FixtureMixCurve", "FixtureMixCurveStep"):
            with self.subTest(name):
                root = self.root(name)
                self.assertIsInstance(root, tx.Decode)  # gamma off: mixed on the stored values (em3.158)
                mask = root.input.mask
                self.assertIsInstance(mask, tx.Smoothstep)
                self.assertIsInstance(mask.input, tx.Image)
                for k, y in enumerate(self.rows[name]):
                    self.assertAlmostEqual(tx.mix_factor(k / 64.0, mask.lower, mask.upper), y, delta=1e-4,
                                           msg=(name, k))
                # without the mask's image the builder mixes by the factor: the mix amount through the curve,
                # as 3ds Max mixes a Mix without a mask at that amount ("amount")
                factor = root.input.factor
                self.assertGreater(factor, 0.0)
                amount = {"FixtureMixCurve": 0.5, "FixtureMixCurveStep": 0.7}[name]  # tools/fixtures/falloff_curve.ms
                self.assertAlmostEqual(factor, tx.mix_factor(amount, mask.lower, mask.upper), places=6)
                self.assertAlmostEqual(factor, self.records[name]["amount"], delta=1e-4)
        root = self.root("FixtureMixCurveAmount")  # black to white through the curve: folded, shown decoded
        self.assertIsInstance(root, tx.Constant)
        self.close(root.value, (colors.srgb_to_linear(self.rows["FixtureMixCurveAmount"][0]),) * 3)

    def test_curve_samples(self):
        P = reader_materials.CurvePoint
        self.assertIsNone(tx.curve_samples((P((0, 0), (0, 0), (0, 0), 0x102), P((1, 1), (1, 1), (1, 1), 0x100))))
        line = tx.curve_samples((P((0, 0), (0, 0), (0, 0), 0), P((0.5, 0.8), (0.5, 0.8), (0.5, 0.8), 4),
                                 P((1, 1), (1, 1), (1, 1), 0)))
        self.assertEqual(line, ((0, 0), (0.5, 0.8), (1, 1)))
        # a point above 1 is taken at 1, its handles moved with it
        high = tx.curve_samples((P((0, 0), (0, 0), (0, 0), 0), P((0.5, 1.3), (0.3, 1.3), (0.7, 1.3), 2),
                                 P((1, 1), (1, 1), (1, 1), 0)))
        self.assertEqual(max(y for _x, y in high), 1.0)
        self.assertEqual(high[-1], (1, 1))
        # many points: at most MAX_CURVE_SAMPLES, still the curve (a sine through 1000 Bezier points)
        many = [P((k / 999.0, 0.5 + 0.4 * math.sin(k / 50.0)), (k / 999.0 - 3e-4, 0.5 + 0.4 * math.sin(k / 50.0)),
                  (k / 999.0 + 3e-4, 0.5 + 0.4 * math.sin(k / 50.0)), 2) for k in range(1000)]
        start = time.perf_counter()
        dense = tx.curve_samples(many)
        self.assertLess(time.perf_counter() - start, 0.1)
        self.assertLessEqual(len(dense), tx.MAX_CURVE_SAMPLES)
        self.assertEqual((dense[0][0], dense[-1][0]), (0.0, 1.0))
        for x, y in dense:
            self.assertAlmostEqual(y, 0.5 + 0.4 * math.sin(x * 999.0 / 50.0), delta=0.02)
        jump = tx.curve_samples((P((0, 0), (0, 0), (0, 0), 0), P((0.5, 0.2), (0.5, 0.2), (0.5, 0.2), 0),
                                 P((0.5, 0.9), (0.5, 0.9), (0.5, 0.9), 0), P((1, 1), (1, 1), (1, 1), 0)))
        self.assertEqual(jump, ((0, 0), (0.5, 0.2), (0.5, 0.9), (1, 1)))


class _Typed(collections.namedtuple("_Typed", "base_type")):
    pass


class _TypedBlock(FakeBlock):
    """A block whose parameters answer a ParamType2 (param(pid).base_type), as a ParamBlock2's do."""

    def __init__(self, block_id, params, types_):
        super().__init__(block_id, params)
        self._types = types_

    def param(self, pid):
        return _Typed(self._types[pid]) if pid in self._types else None


class _ControllerEntry(collections.namedtuple("_ControllerEntry", "superclass class_id name")):
    pass


class _ControllerScene(FakeScene):
    """A FakeScene that also holds Bezier Float controllers: {object index: value saved at frame 0}."""

    def __init__(self, objects, values):
        super().__init__(objects, {i: self._bezier(v) for i, v in values.items()})
        self.values = values

    @staticmethod
    def _bezier(value):
        return FakeChunk(0x9003, children=[FakeChunk(0x7127, children=[
            FakeChunk(0x2501, struct.pack("<f", value)), FakeChunk(0x2500, struct.pack("<ii", 0, 0))])])

    def entry(self, i):
        if i in self.values:
            return _ControllerEntry(classids.SC_CTRL_FLOAT, classids.BEZIER_FLOAT, "Bezier Float")
        return super().entry(i)


class AnimatedRewiring(Checks):
    """A Color Correction whose custom rewiring (rewireMode 3, channels 3 to 5, radio buttons) a controller holds
    converts its rewiring at frame 0 (maxdrop-em3.152); a fraction (3ds Max's rounding not measured) keeps the
    issue."""

    def convert(self, values):
        channels = {pid: pblock.Animated(10 + k) for k, pid in enumerate(tx.CC_REWIRE)}
        cc = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 2: pblock.Animated(20), **channels}, [2],
                     cls="Color Correction", name="cc")
        cc.blocks = {0: _TypedBlock(0, cc.blocks[0]._params, {2: 13, 3: 13, 4: 13, 5: 13})}
        graph = FakeGraph(cc, _bitmap(2))
        graph.scene = _ControllerScene(graph.objects, values)
        return tx.TexmapConverter(graph, _table()).convert(mat.MapRef(1), tx.COLOR)

    def test_rewiring_held_by_controllers(self):
        g = self.convert({20: 3.0, 10: 2.0, 11: 1.0, 12: 0.0})
        self.assertEqual(g.root.rewire, (2, 1, 0))
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def test_mode_held_by_a_controller(self):
        self.assertEqual(self.convert({20: 1.0}).root.rewire, tx.REWIRE_MONO)

    def test_fraction_keeps_the_issue(self):
        g = self.convert({20: 3.0, 10: 2.5, 11: 1.0, 12: 0.0})
        self.assertEqual(g.root.rewire, tx.REWIRE_NONE)
        self.assertTrue(g.approximated)
        self.assertTrue(any("rewiring" in r for r in g.issues), g.issues)


def _cleaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def _cnode(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


_BEZIER_FLOAT = (classids.SC_CTRL_FLOAT, classids.BEZIER_FLOAT, "Bezier Float")
_BEZIER_COLOR = (classids.SC_CTRL_POINT3, classids.BEZIER_COLOR, "Bezier Color")
_OTHER_FLOAT = (classids.SC_CTRL_FLOAT, (0x7778, 0), "Some Float")


class _KeyedScene(FakeScene):
    """A FakeScene that also holds controllers as real chunks: {object index: ((superclass, ClassId, name), bytes)},
    and references {object index: {slot: object index}}."""
    ticks_per_frame = 160

    def __init__(self, objects, controllers, refs=None):
        super().__init__(objects, {i: chunks.index(data)[0] for i, (_kind, data) in controllers.items()})
        self.kinds = {i: kind for i, (kind, _data) in controllers.items()}
        self._refs = refs or {}

    def entry(self, i):
        if i in self.kinds:
            return _ControllerEntry(*self.kinds[i])
        return super().entry(i)

    def refs(self, i):
        return dict(self._refs.get(i, {}))


def _color_keys(before, after, times=(-10, 10)):
    """A Bezier Color without a saved value at frame 0: its two keys (80 bytes each) around it."""
    keys = b"".join(struct.pack("<iI3f", t, 0, *v).ljust(80, bytes(1)) for t, v in zip(times, (before, after)))
    return _cnode(0x9005, _cnode(0x7127, _cleaf(0x2501, struct.pack("<3f", 9, 9, 9)),
                                 _cleaf(0x2500, struct.pack("<ii", 5, 5)), _cleaf(0x2526, keys)))


def _float_saved(value, keys=0):
    """A Bezier Float whose saved value holds forever, or (keys > 1) has no interval beside that many keys."""
    if not keys:
        return _cnode(0x9003, _cnode(0x7127, _cleaf(0x2501, struct.pack("<f", value)),
                                     _cleaf(0x2500, struct.pack("<ii", -2 ** 31, 2 ** 31 - 1))))
    body = b"".join(struct.pack("<iIf4f", 160 * k, 0x1690, value, 0, 0, 1 / 3, 1 / 3) for k in range(keys))
    return _cnode(0x9003, _cnode(0x7127, _cleaf(0x2501, struct.pack("<f", value)), _cleaf(0x2525, body)))


class _OldWithControllers(FakeOld):
    def __init__(self, values, controllers, color=False):
        super().__init__(values)
        self._controllers, self._color = controllers, color

    def controller(self, i):
        return self._controllers.get(i)

    def type(self, i):
        return 2 if self._controllers.get(i) is not None and self._color else 0


class ControllerLines(Checks):
    """What reading a parameter through its controller meets goes to the report and marks the graph approximated
    (maxdrop-6n0.6.32), once per map and line in stats however many walks read it; a map's Coordinates and Output
    (old ParamBlock) are read through their controllers too."""

    def falloff(self, controller):
        fo = _falloff(1, color1=pblock.Animated(20), name="fo")
        fo.blocks = {0: _TypedBlock(0, fo.blocks[0]._params, {tx.FO_COLOR1: 2})}
        graph = FakeGraph(fo)
        graph.scene = _KeyedScene(graph.objects, {20: controller})
        return tx.TexmapConverter(graph, _table())

    def test_color_between_two_keys(self):
        tex = self.falloff((_BEZIER_COLOR, _color_keys((0.2, 0.4, 0.6), (0.6, 0.8, 1.0))))
        color = tex.convert(mat.MapRef(1), tx.COLOR)
        mask = tex.convert(mat.MapRef(1), tx.MASK)
        for g in (color, mask):
            self.assertTrue(g.approximated)
            lines = [r for r in g.issues if "parameter 0 at frame 0 (controller 20)" in r]
            self.assertEqual(len(lines), 1, g.issues)
            self.assertIn(controllers_mod.KEYS_INTERPOLATED, lines[0])
            self.assertTrue(lines[0].startswith("'fo': "), lines[0])
            self.assertNotIn("default", lines[0])
        self.assertEqual([r for _i, r in tex.stats.issues if "controller 20" in r], [lines[0]])
        self.assertEqual([i for i, r in tex.stats.issues if "controller 20" in r], [1])

    def test_a_cached_map_replays_its_line(self):
        """The same map in the same kind for another slot value: a second graph from the cached node, which carries
        the line and the approximation too."""
        tex = self.falloff((_BEZIER_COLOR, _color_keys((0.2, 0.4, 0.6), (0.6, 0.8, 1.0))))
        graphs = [tex.convert(mat.MapRef(1), tx.COLOR, value) for value in ((1.0, 1.0, 1.0), (0.5, 0.5, 0.5))]
        self.assertIsNot(graphs[0], graphs[1])
        for g in graphs:
            self.assertTrue(g.approximated)
            self.assertEqual(len([r for r in g.issues if "controller 20" in r]), 1, g.issues)
        self.assertEqual(len([r for _i, r in tex.stats.issues if "controller 20" in r]), 1)

    def test_coordinates_of_another_shape(self):
        """A Coordinates parameter whose block says color: a controller's color is no tiling (the default, a
        line)."""
        tex, g = self.placed({30: (_BEZIER_COLOR, _color_keys((1, 2, 3), (1, 2, 3), times=(0, 10)))},
                             {"uv": {tx.UV_U_TILING: 0}}, {"uv": {0: 30}}, color=True)
        self.assertEqual(g.root.mapping.tiling, (1.0, 1.0))
        self.assertTrue(any(params_mod.DEFAULT_USED in r for r in g.issues), g.issues)

    def test_unknown_class_keeps_the_default(self):
        tex = self.falloff((_OTHER_FLOAT, _cnode(0x7778, _cleaf(0x2501, struct.pack("<f", 9)))))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertTrue(g.approximated)
        lines = [r for r in g.issues if "controller 20" in r]
        self.assertEqual(lines, ["'fo': parameter 0 at frame 0 (controller 20): %s, %s"
                                 % (controllers_mod.UNKNOWN_CLASS, params_mod.DEFAULT_USED)])

    def test_a_value_read_without_an_issue_gives_no_line(self):
        tex = self.falloff((_BEZIER_COLOR, _color_keys((0.2, 0.4, 0.6), (0.6, 0.8, 1.0), times=(0, 10))))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def placed(self, controllers, old, owned=None, color=False):
        """A Bitmap with Coordinates (UVGen 50) and Output (70) parts, each an old block (object 51, 71) whose
        controllers are {parameter index: reference slot}; the blocks' references {slot: controller}."""
        b = _bitmap(1)
        b.parts = {0: reader_materials.Part(UVGEN_OBJECT, classids.STD_UVGEN, classids.SC_UVGEN, {},
                                            {0: _OldWithControllers({}, old.get("uv", {}), color)}),
                   1: reader_materials.Part(70, classids.STD_TEXOUTPUT, classids.SC_TEXOUTPUT, {},
                                            {1: _OldWithControllers({}, old.get("out", {}))})}
        refs = {UVGEN_OBJECT: {0: 51}, 70: {1: 71}, 51: owned.get("uv", {}) if owned else {},
                71: owned.get("out", {}) if owned else {}}
        graph = FakeGraph(b)
        graph.scene = _KeyedScene(graph.objects, controllers, refs)
        tex = tx.TexmapConverter(graph, _table())
        return tex, tex.convert(mat.MapRef(1), tx.COLOR)

    def test_coordinates_and_output_held_by_controllers(self):
        tex, g = self.placed({30: (_BEZIER_FLOAT, _float_saved(4.0)), 31: (_BEZIER_FLOAT, _float_saved(0.5))},
                             {"uv": {tx.UV_U_TILING: 0}, "out": {tx.OUT_AMOUNT: 0}},
                             {"uv": {0: 30}, "out": {0: 31}})
        self.assertEqual(g.root.mapping.tiling, (4.0, 1.0))
        self.assertEqual(g.root.output.amount, 0.5)
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def test_coordinates_with_an_approximation_or_no_value(self):
        tex, g = self.placed({30: (_BEZIER_FLOAT, _float_saved(4.0, keys=2)),
                              31: (_OTHER_FLOAT, _cnode(0x7778))},
                             {"uv": {tx.UV_U_TILING: 0, tx.UV_V_TILING: 1, tx.UV_U_OFFSET: 2}},
                             {"uv": {0: 30, 1: 31}})
        self.assertEqual(g.root.mapping.tiling, (4.0, 1.0))  # the saved value (maybe another frame's); unknown: 1
        self.assertEqual(g.root.mapping.offset, (0.0, 0.0))  # its controller missing: the default
        self.assertTrue(g.approximated)
        head = "'map' Coordinates: parameter %d at frame 0 (controller %s): "
        self.assertEqual(sorted(r for r in g.issues if "at frame 0" in r), sorted([
            head % (tx.UV_U_TILING, 30) + controllers_mod.ANIMATED,
            head % (tx.UV_V_TILING, 31) + controllers_mod.UNKNOWN_CLASS + ", " + params_mod.DEFAULT_USED,
            head % (tx.UV_U_OFFSET, "missing") + params_mod.NOT_READ + ", " + params_mod.DEFAULT_USED]))
        self.assertEqual({i for i, r in tex.stats.issues if "at frame 0" in r}, {1})  # under the map


if __name__ == "__main__":
    unittest.main()
