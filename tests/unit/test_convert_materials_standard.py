# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/materials/ on Standard and Physical materials, their shaders and maps, and
Multi/Sub-Object, no Blender.

    python -I -m unittest discover tests
"""
import os
import sys
import types
import unittest

_TESTS = "maxdrop_unit_tests"  # tests/unit as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_unit_tests.convert_materials_support import (  # noqa: E402 (after the loader)
    _convert, _fixture, _lin, _lins, _map, _multi, _names, _oracle_graph, _srgb, _standard, _vray,
    _wrapper, classdir, classids, Close, colors, FakeGraph, FakeMtl, mat, reader_materials, Ref,
)


class Standard(unittest.TestCase, Close):
    """tools/fixtures/standard_physical.ms and box_poly_standard.ms, by hand (saved with the gamma off: sRGB
    s/255 -> linear); synthetic shaders: no gamma, linear swatches."""

    def test_fixture(self):
        cf, graph, by_name = _fixture("standard_physical")
        with cf:
            conv = mat.MaterialConverter(graph)
            ir = conv.convert(by_name["FixtureStandard"])
        self.assertEqual((ir.name, ir.source, ir.unknown), ("FixtureStandard", "Standard", False))
        self.close(ir.base_color.value, (0.40724, 0.082283, 0.022174), "diffuse 171 81 41")
        self.assertEqual(ir.base_color.map.index, by_name["FixtureStandardMap"])
        self.close(ir.base_color.map.amount, 0.71, "diffuseMapAmount 71")
        self.close(ir.roughness.value, 0.77, "1 - glossiness 0.23")
        self.close(ir.specular.value, 0.268073, "level 0.37 x mean of 231 221 211")
        self.close(ir.metallic.value, 0.0, "Blinn")
        self.close(ir.alpha.value, 0.83, "opacity 83")
        self.close(ir.ior, 1.33)
        self.assertTrue(ir.two_sided)
        self.close(ir.emission_color.value, (0.40724, 0.082283, 0.022174), "self-illumination: the diffuse")
        self.close(ir.emission_strength, 0.13, "selfIllumAmount 13")
        for name in ("roughness", "specular", "alpha", "emission_color", "metallic"):
            self.assertIsNone(getattr(ir, name).map, name)
        self.assertIsNone(ir.bump)
        self.assertEqual(conv.stats.issues, [])

    def test_box_poly_standard(self):
        cf, graph, by_name = _fixture("box_poly_standard")
        with cf:
            ir = mat.MaterialConverter(graph).convert(by_name["FixtureRed"])
        self.close(ir.base_color.value, (0.57758, 0.021219, 0.012983), "diffuse 200 40 30")

    def test_each_shader_reads_its_own_ids(self):
        diffuse = (0.5, 0.25, 0.75)
        for sid, ids in mat.SHADERS.items():
            with self.subTest(sid):
                shader = {ids.diffuse: diffuse, ids.specular: (1.0, 1.0, 1.0), ids.level: 0.4, ids.glossiness: 0.3,
                          ids.si_amount: 0.0, ids.use_si_color: 1, ids.si_color: (0.0, 1.0, 0.0)}
                if ids.diffuse_level is not None:
                    shader[ids.diffuse_level] = 1.0
                conv, ir = _convert(_standard(0, sid, shader))
                self.close(ir.base_color.value, diffuse)
                self.close(ir.roughness.value, 0.7)
                self.close(ir.specular.value, 0.4)
                self.close(ir.emission_color.value, (0.0, 1.0, 0.0), "self-illumination color")
                self.close(ir.emission_strength, 1.0)
                self.close(ir.metallic.value, 1.0 if sid == classids.METAL_SHADER else 0.0)
                self.assertEqual(conv.stats.issues, [])

    def test_strauss(self):
        conv, ir = _convert(_standard(0, classids.STRAUSS_SHADER, {0: (1.0, 0.0, 0.0), 1: 0.8, 2: 0.6}))
        self.close(ir.base_color.value, (1.0, 0.0, 0.0))
        self.close(ir.roughness.value, 0.2)
        self.close(ir.metallic.value, 0.6)

    def test_unknown_or_missing_shader_takes_the_defaults(self):
        for sid in ((0x1234, 0), None):
            with self.subTest(sid):
                conv, ir = _convert(_standard(0, sid, {1: (1.0, 0.0, 0.0)}))
                self.close(ir.base_color.value, (150 / 255,) * 3)
                self.assertFalse(ir.unknown)
                self.assertIn("Standard: shader", ir.issues[0])

    # Diffuse Level ids (a fraction; measured in 3ds Max 2020, docs/FORMAT.md); the other shaders have none.
    DIFFUSE_LEVEL = {classids.ANISOTROPIC_SHADER: 4, classids.MULTI_LAYER_SHADER: 4,
                     classids.OREN_NAYAR_BLINN_SHADER: 8, classids.TRANSLUCENT_SHADER: 7}

    def test_diffuse_level_scales_the_swatch(self):
        """The level scales the swatch (clamped per channel after the product), not the self-illumination, which
        lights with the diffuse as set (Default Scanline renders, docs/FORMAT.md)."""
        for sid, pid in self.DIFFUSE_LEVEL.items():
            ids = mat.SHADERS[sid]
            for level, want in ((0.5, (0.4, 0.2, 0.1)), (1.5, (1.0, 0.6, 0.3)), (-1.0, (0.0, 0.0, 0.0))):
                with self.subTest(sid=sid, level=level):
                    shader = {ids.diffuse: (0.8, 0.4, 0.2), pid: level, ids.si_amount: 0.3, ids.use_si_color: 0}
                    conv, ir = _convert(_standard(0, sid, shader))
                    self.close(ir.base_color.value, want)
                    self.close(ir.emission_color.value, (0.8, 0.4, 0.2), "self-illumination: the unscaled diffuse")
                    self.close(ir.emission_strength, 0.3)

    def test_diffuse_level_decoys(self):
        """A value at another shader's Diffuse Level id scales nothing: Phong, Blinn and Metal have none, and
        id 4, 7 or 8 is another parameter on the shaders that have one elsewhere (Multi-Layer, which reads 7 and 8:
        5, its diffuse roughness)."""
        for sid in (classids.PHONG_SHADER, classids.BLINN_SHADER, classids.METAL_SHADER):
            with self.subTest(sid):
                conv, ir = _convert(_standard(0, sid, {1: (0.8, 0.4, 0.2), 4: 0.5, 7: 0.0, 8: (0.0, 0.0, 0.0)}))
                self.close(ir.base_color.value, (0.8, 0.4, 0.2))
        for sid, pid in self.DIFFUSE_LEVEL.items():
            shader = {1: (0.8, 0.4, 0.2), pid: 1.0}
            shader.update({k: 0.5 for k in (4, 5, 7, 8) if k != pid and k not in mat.SHADERS[sid][:7]})
            self.assertGreater(len(shader), 2, "at least one decoy")
            with self.subTest(sid):
                conv, ir = _convert(_standard(0, sid, shader))
                self.close(ir.base_color.value, (0.8, 0.4, 0.2))

    # Diffuse Level map channels (zero-based, docs/FORMAT.md; fixture standard_maps).
    LEVEL_CHANNEL = {classids.ANISOTROPIC_SHADER: 3, classids.MULTI_LAYER_SHADER: 2,
                     classids.OREN_NAYAR_BLINN_SHADER: 8, classids.TRANSLUCENT_SHADER: 8}

    def test_diffuse_map_takes_the_level(self):
        """3ds Max scales the mapped diffuse by the level too (Default Scanline, maxdrop-em3.150): the diffuse
        MapRef's scale is the level as the swatch rule makes it (the level itself with the gamma on, its sRGB decode,
        not clamped, with it off); 1 at level 1 (the MapRef of a material without a level) and on Blinn."""
        for sid, pid in self.DIFFUSE_LEVEL.items():
            ids = mat.SHADERS[sid]
            for sw in (colors.GAMMA_ON, colors.GAMMA_OFF):
                for level in (0.5, 1.5, 1.0):
                    with self.subTest(sid=sid, linear=sw.linear, level=level):
                        m = _standard(0, sid, {ids.diffuse: (0.8, 0.4, 0.2), pid: level},
                                      maps={1: (Ref(1), 1, 0.7)})
                        conv = mat.MaterialConverter(FakeGraph(m, _map(1)), swatches=sw)
                        ir = conv.convert(0)
                        want = level if sw.linear else colors.srgb_to_linear(level)
                        self.assertEqual((ir.base_color.map.index, ir.base_color.map.invert), (1, False))
                        self.close(ir.base_color.map.amount, 0.7)
                        self.close(ir.base_color.map.scale, want)
                        if level == 1.0:
                            self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.7, False))
                        self.assertIsNone(ir.diffuse_level, "no Diffuse Level map")
        conv, ir = _convert(_standard(0, classids.BLINN_SHADER, {1: (0.8, 0.4, 0.2), 4: 0.5, 7: 0.5, 8: 0.5},
                                      maps={1: (Ref(1), 1, 0.7)}), _map(1))
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.7, False))

    def test_diffuse_map_level_with_the_gamma_off(self):
        """With the gamma off 3ds Max scales the stored value, Blender's map is decoded: the decoded map times the
        decoded level stays within 0.006 linear of the decoded product for levels up to 100 % (a plain x level is
        up to 0.29 too bright), so a flat diffuse map equal to the swatch imports about as the swatch does."""
        worst = 0.0
        for p in range(1, 101):
            for level in range(5, 101, 5):
                p_, l_ = p / 100.0, level / 100.0
                worst = max(worst, abs(colors.srgb_to_linear(p_) * colors.srgb_to_linear(l_)
                                       - colors.srgb_to_linear(p_ * l_)))
        self.assertLess(worst, 0.006)
        sid = classids.OREN_NAYAR_BLINN_SHADER
        m = _standard(0, sid, {1: (0.6, 0.4, 0.2), 8: 0.5}, maps={1: (Ref(1), 1, 1.0)})
        ir = mat.MaterialConverter(FakeGraph(m, _map(1)), swatches=colors.GAMMA_OFF).convert(0)
        flat = tuple(colors.srgb_to_linear(c) * ir.base_color.map.scale for c in (0.6, 0.4, 0.2))
        for a, b in zip(flat, ir.base_color.value):
            self.assertAlmostEqual(a, b, delta=0.006)

    def test_diffuse_level_map(self):
        """A Diffuse Level map replaces the level by its amount (lerp(level, map, amount), Default Scanline,
        maxdrop-em3.150): ir.diffuse_level holds the swatch at level 1, the level as the swatch rule makes it and the
        map; the base color's value and its map's scale stay what they are without it (the fallback)."""
        for sid, channel in self.LEVEL_CHANNEL.items():
            ids = mat.SHADERS[sid]
            pid = self.DIFFUSE_LEVEL[sid]
            for sw in (colors.GAMMA_ON, colors.GAMMA_OFF):
                with self.subTest(sid=sid, linear=sw.linear):
                    m = _standard(0, sid, {ids.diffuse: (0.8, 0.4, 0.2), pid: 0.5},
                                  maps={1: (Ref(1), 1, 0.7), channel: (Ref(2), 1, 0.6)})
                    conv = mat.MaterialConverter(FakeGraph(m, _map(1), _map(2)), swatches=sw)
                    ir = conv.convert(0)
                    k = 0.5 if sw.linear else colors.srgb_to_linear(0.5)
                    self.close(ir.base_color.value, sw.color((0.4, 0.2, 0.1)))
                    self.close(ir.base_color.map.scale, k)
                    lv = ir.diffuse_level
                    self.assertIsNotNone(lv)
                    self.close(lv.color, sw.color((0.8, 0.4, 0.2)), "the swatch at level 1")
                    self.close(lv.level, k)
                    self.assertEqual((lv.map.index, lv.map.invert, lv.map.scale), (2, False, 1.0))
                    self.close(lv.map.amount, 0.6)
                    self.assertEqual(conv.stats.issues, [])
        sid = classids.OREN_NAYAR_BLINN_SHADER
        for maps in ({8: (Ref(2), 0, 1.0)}, {}):  # switched off, empty: no level map, no diffuse map either
            with self.subTest(maps=maps):
                conv, ir = _convert(_standard(0, sid, {1: (0.8, 0.4, 0.2), 8: 0.5}, maps=maps), _map(2))
                self.assertIsNone(ir.diffuse_level)
                self.assertIsNone(ir.base_color.map)
        conv, ir = _convert(_standard(0, sid, {1: (0.8, 0.4, 0.2), 8: 0.5}, maps={8: (Ref(2), 1, 1.0)}), _map(2))
        self.assertIsNone(ir.base_color.map)
        self.assertEqual(ir.diffuse_level.map, mat.MapRef(2, 1.0, False))  # a level map alone
        conv, ir = _convert(_standard(0, classids.BLINN_SHADER, {1: (0.8, 0.4, 0.2)}, maps={8: (Ref(2), 1, 1.0)}),
                            _map(2))
        self.assertIsNone(ir.diffuse_level, "Blinn has no Diffuse Level channel: 8 is its bump")

    def test_shader_defaults(self):
        """A shader block without its values: each shader's own defaults, as 3ds Max 2020 creates them (diffuse
        150 / 255 or 127.5 / 255 grey, glossiness, specular level times the 0.9 specular color)."""
        blinn = ((150 / 255,) * 3, 0.9, 0.0)
        want = {  # base color, roughness (1 - glossiness), specular
            classids.PHONG_SHADER: blinn, classids.BLINN_SHADER: blinn, classids.METAL_SHADER: blinn,
            classids.ANISOTROPIC_SHADER: ((0.5,) * 3, 0.75, 0.05 * 0.9),
            classids.MULTI_LAYER_SHADER: ((0.5,) * 3, 0.5, 0.05 * 0.9),
            classids.OREN_NAYAR_BLINN_SHADER: ((0.5,) * 3, 0.75, 0.0),
            classids.TRANSLUCENT_SHADER: ((0.5,) * 3, 0.7, 0.0),
            classids.STRAUSS_SHADER: ((0.5,) * 3, 0.8, 1.0),  # no specular level: the IOR's own Fresnel
        }
        self.assertEqual(set(want), set(mat.SHADER_DEFAULTS))
        for sid, (base, rough, spec) in want.items():
            with self.subTest(sid):
                conv, ir = _convert(_standard(0, sid, {}))
                self.close(ir.base_color.value, base)
                self.close(ir.roughness.value, rough)
                self.close(ir.specular.value, spec)
                self.assertEqual(conv.stats.issues, [])

    # Each shader's map channels (zero-based, measured in 3ds Max 2020, docs/FORMAT.md): diffuse, specular color,
    # specular level, glossiness, self-illumination, opacity, bump, reflection, metalness, diffuse level; None: no
    # such channel.
    CHANNELS = {
        classids.BLINN_SHADER: (1, 2, 3, 4, 5, 6, 8, 9, None, None),
        classids.PHONG_SHADER: (1, 2, 3, 4, 5, 6, 8, 9, None, None),
        classids.METAL_SHADER: (1, 2, 3, 4, 5, 6, 8, 9, None, None),
        classids.ANISOTROPIC_SHADER: (1, 2, 4, 5, 8, 9, 11, 12, None, 3),
        classids.MULTI_LAYER_SHADER: (1, 4, 5, 6, 14, 15, 17, 18, None, 2),  # the first specular layer
        classids.OREN_NAYAR_BLINN_SHADER: (1, 2, 4, 3, 5, 6, 10, 11, None, 8),
        classids.TRANSLUCENT_SHADER: (1, 2, 4, 3, 5, 6, 10, 11, None, 8),
        classids.STRAUSS_SHADER: (0, None, None, 1, None, 3, 5, 6, 2, None),
    }

    def test_slot_table(self):
        """mat.STD_SLOTS is the table above, field by field."""
        self.assertEqual(set(mat.STD_SLOTS), set(self.CHANNELS))
        for sid, channels in self.CHANNELS.items():
            self.assertEqual(tuple(mat.STD_SLOTS[sid]), channels, sid)

    def test_map_slots(self):
        """Every shader reads its own channels: a map in each read channel (object = its field's number + 1, at
        an amount of its own), every other channel holds a map no input may take (object 50 + the channel)."""
        for sid, channels in self.CHANNELS.items():
            with self.subTest(sid):
                maps = {k: (Ref(50 + k), 1, 0.25) for k in range(21)}
                for field, k in enumerate(channels):
                    if k is not None:
                        maps[k] = (Ref(field + 1), 1, 0.5 + field / 100.0)
                objs = [_map(i) for i in range(1, 11)] + [_map(50 + k) for k in range(21)]
                conv, ir = _convert(_standard(0, sid, {}, maps=maps), *objs)
                diffuse, spec, level, gloss, emit, opacity, bump, refl, metal, diffuse_level = channels
                self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.50, False))
                self.assertEqual(ir.roughness.map, mat.MapRef(4, 0.53, True))  # a glossiness map: inverted
                self.assertEqual(ir.specular.map, None if level is None else mat.MapRef(3, 0.52, False))
                self.close(ir.specular.value, 1.0 if sid == classids.STRAUSS_SHADER else 0.57,
                           "the reflection amount over level 0")
                self.assertEqual(ir.alpha.map, mat.MapRef(6, 0.55, False))
                if emit is None:
                    self.assertIsNone(ir.emission_color.map)
                    self.close(ir.emission_strength, 0.0)
                else:
                    self.assertEqual(ir.emission_color.map, mat.MapRef(5, 0.54, False))
                    self.close(ir.emission_strength, 1.0, "a self-illumination map drives the emission")
                self.assertEqual(ir.bump, mat.MapRef(7, 0.56, False))
                self.assertEqual(ir.metallic.map, None if metal is None else mat.MapRef(9, 0.58, False))
                self.assertEqual(None if ir.diffuse_level is None else ir.diffuse_level.map,
                                 None if diffuse_level is None else mat.MapRef(10, 0.59, False))
                self.assertEqual(conv.stats.issues, [])

    def test_specular_color_map_without_a_level_map(self):
        for sid, channels in self.CHANNELS.items():
            if channels[1] is None:
                continue
            with self.subTest(sid):
                conv, ir = _convert(_standard(0, sid, {}, maps={channels[1]: (Ref(1), 1, 0.4)}), _map(1))
                self.assertEqual(ir.specular.map, mat.MapRef(1, 0.4, False))

    def test_switched_off_slots_and_the_specular_color_map(self):
        maps = {1: (Ref(1), 0, 1.0), 2: (Ref(2), 1, 0.4), 9: (Ref(3), 0, 1.0), 8: (Ref(9), 1, 1.0)}
        conv, ir = _convert(_standard(0, classids.BLINN_SHADER, {9: 0.2, 2: (1.0, 1.0, 1.0)}, maps=maps),
                            _map(1), _map(2), _map(3), _vray(9))
        self.assertIsNone(ir.base_color.map)
        self.assertEqual(ir.specular.map, mat.MapRef(2, 0.4, False))  # no level map: the specular color's
        self.close(ir.specular.value, 0.2, "reflection slot off")
        self.assertIsNone(ir.bump)
        self.assertIn("map slot 8: object 9 is not a map", ir.issues[0])

    def test_texmaps_channels(self):
        """_std_map from a Texmaps object's channels (reader.materials.StdMaps): its map, switch and amount, a
        channel that holds something else than a map named as the table's."""
        conv = mat.MaterialConverter(FakeGraph(_map(1), _vray(9)))
        m, ir = _standard(0, classids.BLINN_SHADER, {}), mat.MaterialIR(0, "S")
        std = reader_materials.StdMaps({1: 1, 2: 1, 8: 9, 9: 1}, 0b100001110, {1: 0.4})
        self.assertEqual(mat._std_map(conv, m, 1, ir, channels=std), mat.MapRef(1, 0.4, False))
        self.assertIsNone(mat._std_map(conv, m, 3, ir, channels=std))  # on, no map
        self.assertEqual(mat._std_map(conv, m, 2, ir, invert=True, channels=std), mat.MapRef(1, 1.0, True))
        self.assertIsNone(mat._std_map(conv, m, 8, ir, channels=std))
        self.assertIn("map channel 8: object 9 is not a map", ir.issues[0])
        self.assertIsNone(mat._std_map(conv, m, 9, ir, channels=std))  # a map, switched off


class StandardMaps(unittest.TestCase, Close):
    """tools/fixtures/standard_maps.ms: a Standard material per shader with a Checker in every channel the rule
    reads, named after the input it drives ("FixtureMap" + shader + field) and put into the channel 3ds Max names
    that way on that shader; amounts 0.51 (diffuse) to 0.59 (metalness). Three Anisotropic materials whose block 3
    tables are stale (created as Blinn, docs/FORMAT.md): FixtureMapsUnsetAmounts, FixtureMapsSwitchedAfter,
    FixtureMapsSwitchedOff."""

    LABELS = {"Blinn": "BLINN_SHADER", "Anisotropic": "ANISOTROPIC_SHADER", "MultiLayer": "MULTI_LAYER_SHADER",
              "OrenNayarBlinn": "OREN_NAYAR_BLINN_SHADER", "Translucent": "TRANSLUCENT_SHADER",
              "Strauss": "STRAUSS_SHADER"}
    FIELDS = {"diffuse": "Diffuse", "specular": "Specular", "level": "Level", "glossiness": "Glossiness",
              "self_illum": "SelfIllum", "opacity": "Opacity", "bump": "Bump", "reflection": "Reflection",
              "metalness": "Metalness"}
    # The Diffuse Level materials (maxdrop-em3.150): shader, Diffuse Level, diffuse map amount, Diffuse Level map
    # amount (None: none or switched off), as the script sets them.
    LEVEL = {"LevelAnisotropic": ("ANISOTROPIC_SHADER", 0.40, 0.61, 0.62),
             "LevelMultiLayer": ("MULTI_LAYER_SHADER", 1.50, 0.63, 1.0),
             "LevelOrenNayarBlinn": ("OREN_NAYAR_BLINN_SHADER", 0.65, 0.65, None),  # its level map switched off
             "LevelTranslucent": ("TRANSLUCENT_SHADER", 0.80, 0.66, None)}

    @classmethod
    def setUpClass(cls):
        cf, cls.graph, cls.by_name = _fixture("standard_maps")
        with cf:
            cls.conv = mat.MaterialConverter(cls.graph)
            cls.irs = {n: cls.conv.convert(cls.by_name["FixtureMaps" + n])
                       for n in list(cls.LABELS) + ["UnsetAmounts", "SwitchedAfter", "SwitchedOff"] + list(cls.LEVEL)}

    def map(self, label, field, amount, invert=False):
        return mat.MapRef(self.by_name["FixtureMap" + label + field], amount, invert)

    def same_map(self, got, want, what):
        """The same map and invert; the amount within float precision (stored as a 32-bit float)."""
        self.assertIsNotNone(got, what)
        self.assertEqual((got.index, got.invert), (want.index, want.invert), what)
        self.close(got.amount, want.amount, what + " amount")

    def test_each_shader_reads_its_maps(self):
        for label in self.LABELS:
            with self.subTest(label):
                ir, strauss = self.irs[label], label == "Strauss"
                self.same_map(ir.base_color.map, self.map(label, "Diffuse", 0.51), "diffuse")
                self.same_map(ir.roughness.map, self.map(label, "Glossiness", 0.54, invert=True), "glossiness")
                if strauss:
                    self.assertIsNone(ir.specular.map)
                else:
                    self.same_map(ir.specular.map, self.map(label, "Level", 0.53), "specular level")
                self.close(ir.specular.value, 1.0 if strauss else 0.58, "the reflection slot's amount")
                self.same_map(ir.alpha.map, self.map(label, "Opacity", 0.56), "opacity")
                self.same_map(ir.bump, self.map(label, "Bump", 0.57), "bump")
                if strauss:
                    self.assertIsNone(ir.emission_color.map)
                    self.close(ir.emission_strength, 0.0)
                    self.same_map(ir.metallic.map, self.map(label, "Metalness", 0.59), "metalness")
                    self.close(ir.metallic.value, 0.40)
                else:
                    self.same_map(ir.emission_color.map, self.map(label, "SelfIllum", 0.55), "self-illumination")
                    self.close(ir.emission_strength, 1.0)
                    self.assertIsNone(ir.metallic.map)

    def test_the_slot_table_names_the_maps(self):
        """mat.STD_SLOTS against the channel 3ds Max put each named map into (the specular color map, which
        the level map hides, included)."""
        for label, shader in self.LABELS.items():
            m = self.graph.get(self.by_name["FixtureMaps" + label])
            sid = getattr(classids, shader)
            slots = mat.STD_SLOTS[sid]
            with self.subTest(label):
                for field, suffix in self.FIELDS.items():
                    want = self.by_name.get("FixtureMap" + label + suffix)
                    k = getattr(slots, field)
                    self.assertEqual(want is None, k is None, field)
                    if k is not None:
                        self.assertEqual(m.param(1, 3, tab=k).index, want, field)
        self.assertEqual(set(mat.STD_SLOTS), set(mat.SHADERS) | {classids.STRAUSS_SHADER})

    def table(self, label, pid):
        """Block 3's table pid (0 mapEnables, 1 maps, 2 mapAmounts) of FixtureMaps + label, a map as its index."""
        values = self.graph.get(self.by_name["FixtureMaps" + label]).block(3).param(pid).values
        return [getattr(v, "index", v) for v in values]

    def test_amounts_never_set_after_the_shader_switch(self):
        """FixtureMapsUnsetAmounts (Anisotropic, created as Blinn, maps set after the switch without touching their
        amounts): the table keeps Blinn's amounts (0.3 at 8, 1.0 at 11), 3ds Max answers its shader's from the
        Texmaps object: self-illumination (8) 1.0, bump (11) 0.3 (maxdrop-em3.148)."""
        amounts = self.table("UnsetAmounts", 2)
        self.close((amounts[8], amounts[11]), (0.3, 1.0), "the table is still stale")
        ir = self.irs["UnsetAmounts"]
        self.same_map(ir.emission_color.map, self.map("UnsetAmounts", "SelfIllum", 1.0), "self-illumination")
        self.same_map(ir.bump, self.map("UnsetAmounts", "Bump", 0.3), "bump")
        self.assertIsNone(ir.base_color.map)

    def test_maps_set_before_the_shader_switch(self):
        """FixtureMapsSwitchedAfter (Blinn with diffuse and bump maps, then switched to Anisotropic): 3ds Max moves
        the bump map to Anisotropic's channel 11 at 0.3, the table keeps it and its switch at Blinn's 8, which is
        Anisotropic's self-illumination."""
        bump = self.by_name["FixtureMapSwitchedAfterBump"]
        self.assertEqual((self.table("SwitchedAfter", 1)[8], self.table("SwitchedAfter", 0)[8]), (bump, 1),
                         "the table is still stale")
        ir = self.irs["SwitchedAfter"]
        self.same_map(ir.base_color.map, self.map("SwitchedAfter", "Diffuse", 1.0), "diffuse")
        self.same_map(ir.bump, self.map("SwitchedAfter", "Bump", 0.3), "bump")
        self.assertIsNone(ir.emission_color.map)
        self.close(ir.emission_strength, 0.0)

    def test_a_map_switched_off(self):
        """FixtureMapsSwitchedOff (Anisotropic, self-illumination and bump maps, the bump switched off): no bump."""
        ir = self.irs["SwitchedOff"]
        self.same_map(ir.emission_color.map, self.map("SwitchedOff", "SelfIllum", 1.0), "self-illumination")
        self.assertIsNone(ir.bump)

    def test_diffuse_level_maps(self):
        """The Level materials by hand (saved with the gamma off): the diffuse swatch 150 120 90 times the level
        (clamped, then decoded), the diffuse map scaled by the decoded level, the Diffuse Level map with its amount
        and the swatch at level 1; none where it is switched off or missing."""
        for name, (shader, level, diffuse_amount, level_amount) in self.LEVEL.items():
            with self.subTest(name):
                ir = self.irs[name]
                k = colors.srgb_to_linear(level)
                self.close(ir.base_color.value, _srgb(*(min(255.0, c * level) for c in (150, 120, 90))))
                self.same_map(ir.base_color.map, self.map(name, "Diffuse", diffuse_amount), "diffuse")
                self.close(ir.base_color.map.scale, k, "the decoded level")
                level_map = self.by_name.get("FixtureMap" + name + "DiffuseLevel")
                if level_map is not None:  # the channel 3ds Max put it into, in the table and the Texmaps object
                    m = self.graph.get(self.by_name["FixtureMaps" + name])
                    slot = mat.STD_SLOTS[getattr(classids, shader)].diffuse_level
                    self.assertEqual(m.param(1, 3, tab=slot).index, level_map, "the slot table's channel")
                    index, on, amount = reader_materials.standard_maps(self.graph.scene, m).channel(slot)
                    self.assertEqual((index, on), (level_map, level_amount is not None), "the Texmaps channel")
                    self.close(amount, 0.64 if level_amount is None else level_amount)
                if level_amount is None:
                    self.assertIsNone(ir.diffuse_level)
                    continue
                lv = ir.diffuse_level
                self.same_map(lv.map, self.map(name, "DiffuseLevel", level_amount), "Diffuse Level map")
                self.assertEqual(lv.map.scale, 1.0)
                self.close(lv.level, k)
                self.close(lv.color, _srgb(150, 120, 90), "the swatch at level 1")
        self.assertIn("FixtureMapLevelOrenNayarBlinnDiffuseLevel", self.by_name, "the switched-off map is saved")
        self.assertNotIn("FixtureMapLevelTranslucentDiffuseLevel", self.by_name)

    def test_no_issues(self):
        self.assertEqual((self.conv.stats.issues, dict(self.conv.stats.unknown)), ([], {}))


class Physical(unittest.TestCase, Close):
    def test_fixture(self):
        cf, graph, by_name = _fixture("standard_physical")
        with cf:
            conv = mat.MaterialConverter(graph)
            ir = conv.convert(by_name["FixturePhysical"])
        self.assertEqual((ir.name, ir.source, ir.unknown), ("FixturePhysical", "Physical Material", False))
        # base 181 79 28 x weight 0.91, mixed with transparency color 51 102 153 by transparency 0.12
        self.close(ir.base_color.value, (0.374004, 0.078557, 0.047525), "base color")
        self.close(ir.roughness.value, 0.27)
        self.close(ir.metallic.value, 0.43)
        self.close(ir.specular.value, 0.498396, "reflectivity 0.81 x mean of 230 204 179")
        self.close(ir.transmission.value, 0.12)
        self.close(ir.ior, 1.47)
        self.assertFalse(ir.thin_walled)
        self.close(ir.emission_color.value, (0.318547, 0.215861, 0.132868), "emit color 153 128 102")
        self.close(ir.emission_strength, 0.05 * 1500.0 / 683.0, "weight x luminance / 683")
        self.close((ir.coat_weight, ir.coat_roughness, ir.coat_ior), (0.33, 0.21, 1.61))
        self.close(ir.coat_color, (1.0, 1.0, 1.0))
        for name in ("base_color", "roughness", "metallic", "specular", "transmission", "emission_color", "alpha"):
            self.assertIsNone(getattr(ir, name).map, name)
        self.assertEqual((ir.bump, ir.normal, conv.stats.issues), (None, None, []))

    def test_inverted_roughness_and_maps(self):
        params = {4: 0.3, 5: 1, 63: 1, 62: 0.25, 50: 0.0, 101: Ref(1), 104: Ref(2), 105: Ref(3), 154: 1,
                  109: Ref(4), 159: 0, 116: Ref(5), 130: Ref(6), 230: 0.7, 133: Ref(7)}
        conv, ir = _convert(FakeMtl(0, classids.PHYSICAL_MTL, "P", {0: params}), *[_map(i) for i in range(1, 8)])
        self.close(ir.roughness.value, 0.7, "roughness_inv: 1 - 0.3")
        self.assertEqual(ir.roughness.map, mat.MapRef(2, 1.0, True))
        self.close(ir.coat_roughness, 0.75)
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 1.0, False))
        self.assertEqual(ir.metallic.map, mat.MapRef(3, 1.0, False))
        self.assertIsNone(ir.transmission.map)  # switched off
        self.assertEqual(ir.emission_color.map, mat.MapRef(5, 1.0, False))  # the weight map, no color map
        self.close(ir.emission_strength, 1500.0 / 683.0, "a map with weight 0: full weight")
        self.assertEqual(ir.bump, mat.MapRef(6, 0.7, False))
        self.assertEqual(ir.alpha.map, mat.MapRef(7, 1.0, False))

    def test_emission_maps(self):
        conv, ir = _convert(FakeMtl(0, classids.PHYSICAL_MTL, "ColorOnly", {0: {50: 0.0, 117: Ref(1)}}), _map(1))
        self.close(ir.emission_strength, 0.0, "weight 0 with a color map: no emission")
        self.assertIsNone(ir.emission_color.map)
        conv, ir = _convert(FakeMtl(0, classids.PHYSICAL_MTL, "Both",
                                    {0: {50: 0.2, 52: 683.0, 116: Ref(1), 117: Ref(2)}}), _map(1), _map(2))
        self.assertEqual(ir.emission_color.map, mat.MapRef(2, 1.0, False))
        self.close(ir.emission_strength, 1.0, "the weight map stands for the weight")
        self.assertIn("weight map 1 not used", ir.issues[0])
        conv, ir = _convert(FakeMtl(0, classids.PHYSICAL_MTL, "Lit", {0: {50: 0.5, 52: 3000.0}}))
        self.close(ir.emission_strength, 0.5 * 3000.0 / 683.0)

    def test_defaults(self):
        conv, ir = _convert(FakeMtl(0, classids.PHYSICAL_MTL, "Empty", {0: {}}))
        self.close(ir.base_color.value, (0.5,) * 3)
        self.close((ir.roughness.value, ir.metallic.value, ir.specular.value, ir.ior), (0.0, 0.0, 1.0, 1.52))
        self.close(ir.emission_strength, 0.0)


class StandardShaders(unittest.TestCase, Close):
    """tools/fixtures/standard_shaders.ms, by hand (gamma off: sRGB s/255 -> linear): one Standard material per
    shader. The ids are also checked by the names 3ds Max gives them in the oracle, apart from SHADERS."""

    # material: (shader, diffuse, specular, level %, glossiness %, self-illumination amount %, its color, color on)
    VALUES = {
        "FixtureBlinn": ("BLINN_SHADER", (200, 60, 40), (220, 210, 200), 41, 31, 17, (30, 90, 200), True),
        "FixturePhong": ("PHONG_SHADER", (60, 180, 90), (210, 220, 230), 52, 42, 19, (200, 30, 90), False),
        "FixtureMetal": ("METAL_SHADER", (180, 140, 60), (240, 230, 200), 63, 53, 21, (90, 200, 30), True),
        "FixtureAnisotropic": ("ANISOTROPIC_SHADER", (90, 60, 200), (190, 200, 210), 74, 64, 23, (40, 160, 220),
                               False),
        "FixtureOrenNayarBlinn": ("OREN_NAYAR_BLINN_SHADER", (150, 90, 120), (230, 220, 210), 35, 45, 27,
                                  (220, 120, 40), True),
        "FixtureMultiLayer": ("MULTI_LAYER_SHADER", (100, 170, 160), (200, 190, 180), 46, 56, 29, (160, 40, 220),
                              False),
        "FixtureTranslucent": ("TRANSLUCENT_SHADER", (170, 110, 80), (215, 225, 235), 57, 67, 31, (30, 220, 160),
                               True),
    }
    FIELDS = {"diffuse": "diffuse", "specular": "specular", "level": "specularLevel", "glossiness": "glossiness",
              "si_amount": "selfIllumAmount", "si_color": "selfIllumColor", "use_si_color": "useSelfIllumColor"}
    # material: (shader, diffuse, Diffuse Level %, self-illumination amount %); glossiness and specular level as
    # created
    LEVELS = {
        "FixtureAnisotropicLevel": ("ANISOTROPIC_SHADER", (200, 120, 60), 40, 35),
        "FixtureMultiLayerLevel": ("MULTI_LAYER_SHADER", (60, 200, 140), 150, 0),
        "FixtureOrenNayarBlinnLevel": ("OREN_NAYAR_BLINN_SHADER", (120, 80, 220), 65, 0),
        "FixtureTranslucentLevel": ("TRANSLUCENT_SHADER", (90, 180, 50), 80, 0),
    }

    @classmethod
    def setUpClass(cls):
        cf, graph, cls.by_name = _fixture("standard_shaders")
        with cf:
            cls.conv = mat.MaterialConverter(graph)
            cls.irs = {n: cls.conv.convert(cls.by_name[n])
                       for n in list(cls.VALUES) + list(cls.LEVELS) + ["FixtureStrauss"]}
        cls.oracle = _oracle_graph("standard_shaders")

    def shader_block(self, name):
        """(ClassId, parameter names by id) of the shader part of a Standard material in the oracle."""
        parts = [(classdir.ClassId(*(int(h, 16) for h in p["class_id"])), p) for p in self.oracle[name]["parts"]]
        parts = [(cid, p) for cid, p in parts if cid != classids.STAR_SAMPLER]  # the other part: the sampler
        self.assertEqual(len(parts), 1, name)
        return parts[0][0], _names(parts[0][1]["blocks"][0])

    def test_each_shader_by_hand(self):
        for name, (shader, diffuse, spec, level, gloss, amount, si_color, si_on) in self.VALUES.items():
            with self.subTest(name):
                ir = self.irs[name]
                self.assertEqual((ir.name, ir.source, ir.unknown), (name, "Standard", False))
                self.close(ir.base_color.value, _lins(*diffuse))
                self.close(ir.roughness.value, 1.0 - gloss / 100.0)
                self.close(ir.specular.value, level / 100.0 * sum(_lins(*spec)) / 3)
                if si_on:  # its own color at strength 1
                    self.close(ir.emission_color.value, _lins(*si_color))
                    self.close(ir.emission_strength, 1.0)
                else:  # the diffuse at the amount
                    self.close(ir.emission_color.value, _lins(*diffuse))
                    self.close(ir.emission_strength, amount / 100.0)
                self.close(ir.metallic.value, 1.0 if shader == "METAL_SHADER" else 0.0)
                self.assertIsNone(ir.base_color.map)

    def test_strauss(self):
        ir = self.irs["FixtureStrauss"]
        self.close(ir.base_color.value, _lins(120, 130, 210))
        self.close((ir.roughness.value, ir.metallic.value, ir.specular.value), (1.0 - 0.37, 0.48, 1.0))
        self.close(ir.emission_strength, 0.0)

    def test_ids_name_the_parameters(self):
        for name, values in self.VALUES.items():
            with self.subTest(name):
                sid, names = self.shader_block(name)
                self.assertEqual(sid, getattr(classids, values[0]))
                ids = mat.SHADERS[sid]
                self.assertEqual({field: names[getattr(ids, field)] for field in self.FIELDS}, self.FIELDS)
        sid, names = self.shader_block("FixtureStrauss")
        self.assertEqual(sid, classids.STRAUSS_SHADER)
        self.assertEqual((names[0], names[1], names[2]), ("diffuse", "glossiness", "metalness"))
        self.assertEqual(set(mat.SHADERS), {getattr(classids, v[0]) for v in self.VALUES.values()})

    def test_diffuse_level_by_hand(self):
        """The swatch times the level, clamped to 255, then decoded (Multi-Layer's green 200 x 1.5 is white); the
        self-illumination keeps the diffuse as set; glossiness and specular level are the shader's as created."""
        for name, (shader, diffuse, level, amount) in self.LEVELS.items():
            with self.subTest(name):
                sid, names = self.shader_block(name)
                self.assertEqual(sid, getattr(classids, shader))
                ids, d = mat.SHADERS[sid], mat.SHADER_DEFAULTS[sid]
                self.assertEqual(names[ids.diffuse_level], "diffuseLevel")
                block = self.oracle[name]["parts"]
                stored = [p["value"] for part in block for b in part["blocks"][:1] for p in b["params"]
                          if p.get("name") == "diffuseLevel"]
                self.assertEqual(len(stored), 1)
                self.close(stored[0], level / 100.0, "stored as a fraction")
                ir = self.irs[name]
                self.close(ir.base_color.value, _lins(*(min(255.0, c * level / 100.0) for c in diffuse)))
                self.close(ir.roughness.value, 1.0 - d.glossiness)
                self.close(ir.specular.value, d.level * _lin(229.5), "level as created times the 0.9 grey specular")
                if amount:
                    self.close(ir.emission_color.value, _lins(*diffuse), "the unscaled diffuse")
                self.close(ir.emission_strength, amount / 100.0)
        self.close(self.irs["FixtureMultiLayerLevel"].base_color.value[1], 1.0, "past white: clamped")

    def test_no_issues(self):
        self.assertEqual((self.conv.stats.issues, dict(self.conv.stats.unknown)), ([], {}))


class PhysicalMaps(unittest.TestCase, Close):
    """tools/fixtures/standard_shaders.ms's two Physical Materials, by hand (gamma off): the same nine map slots in
    both, each switched off in one of them. The ids are checked by the names the oracle gives them (mat.PHYSICAL,
    which physical_mtl reads; the switches at a fixed offset): the values alone cannot tell apart two ids that
    hold the same value in both materials."""

    @classmethod
    def setUpClass(cls):
        cf, graph, cls.by_name = _fixture("standard_shaders")
        with cf:
            cls.conv = mat.MaterialConverter(graph)
            cls.maps = cls.conv.convert(cls.by_name["FixturePhysicalMaps"])
            cls.off = cls.conv.convert(cls.by_name["FixturePhysicalOff"])
        cls.oracle = _oracle_graph("standard_shaders")

    def map(self, name, invert=False):
        return mat.MapRef(self.by_name["FixturePhys" + name + "Map"], 1.0, invert)

    def test_maps(self):
        ir = self.maps
        self.assertEqual((ir.source, ir.unknown, ir.issues), ("Physical Material", False, []))
        base = tuple(c * 0.8 for c in _lins(200, 100, 50))
        self.close(ir.base_color.value, tuple(b * 0.8 + t * 0.2 for b, t in zip(base, _lins(60, 120, 180))))
        self.assertEqual(ir.base_color.map, self.map("MapsBase"))
        self.close(ir.specular.value, 0.7 * sum(_lins(210, 200, 190)) / 3)
        self.assertEqual(ir.specular.map, self.map("MapsReflectivity"))
        self.close(ir.roughness.value, 1.0 - 0.35, "roughness_inv")
        self.assertEqual(ir.roughness.map, self.map("MapsRoughness", invert=True))
        self.close(ir.metallic.value, 0.25)
        self.assertEqual(ir.metallic.map, self.map("MapsMetalness"))
        self.close(ir.transmission.value, 0.2)
        self.assertIsNone(ir.transmission.map)  # transparency_map_on off
        self.close(ir.ior, 1.4)
        self.assertTrue(ir.thin_walled)
        self.close(ir.emission_color.value, _lins(220, 180, 140))
        self.assertEqual(ir.emission_color.map, self.map("MapsEmitColor"))  # emission_map_on off: the color map
        self.close(ir.emission_strength, 0.6 * 900.0 / 683.0)
        self.close((ir.coat_weight, ir.coat_roughness, ir.coat_ior), (0.45, 1.0 - 0.15, 1.7))
        self.close(ir.coat_color, _lins(230, 200, 170))
        self.assertEqual((ir.bump.index, ir.bump.invert), (self.map("MapsBump").index, False))
        self.close(ir.bump.amount, 0.55, "bump_map_amt")
        self.assertIsNone(ir.normal)
        self.assertEqual(ir.alpha.map, self.map("MapsCutout"))

    def test_off(self):
        ir = self.off
        self.assertEqual(ir.issues, [])
        base = tuple(c * 0.9 for c in _lins(70, 140, 210))
        self.close(ir.base_color.value, tuple(b * 0.7 + t * 0.3 for b, t in zip(base, _lins(200, 150, 100))))
        self.close(ir.specular.value, 0.55 * sum(_lins(180, 190, 200)) / 3)
        self.close((ir.roughness.value, ir.metallic.value, ir.transmission.value, ir.ior), (0.4, 0.6, 0.3, 1.6))
        for name in ("base_color", "specular", "roughness", "metallic", "alpha"):
            self.assertIsNone(getattr(ir, name).map, name)
        self.assertEqual(ir.transmission.map, self.map("OffTransparency"))
        self.assertFalse(ir.thin_walled)
        self.close(ir.emission_color.value, _lins(100, 150, 250))
        self.assertEqual(ir.emission_color.map, self.map("OffEmission"))  # the weight map, the color map off
        self.close(ir.emission_strength, 2400.0 / 683.0, "the weight map stands for the weight")
        self.close((ir.coat_weight, ir.coat_roughness, ir.coat_ior), (0.2, 0.3, 1.55))
        self.close(ir.coat_color, _lins(150, 200, 250))
        self.assertEqual((ir.bump, ir.normal), (None, None))  # bump_map_on off

    def test_ids_name_the_parameters(self):
        """Every id of mat.PHYSICAL, which physical_mtl reads, and each map's switch name their parameters."""
        for name in ("FixturePhysicalMaps", "FixturePhysicalOff"):
            with self.subTest(name):
                names = _names(self.oracle[name]["blocks"][0])
                self.assertEqual({key: names[pid] for key, pid in mat.PHYSICAL.items()},
                                 {key: key for key in mat.PHYSICAL})
                maps = [key for key in mat.PHYSICAL if key.endswith("_map")]
                self.assertEqual(len(maps), 9)
                for key in maps:
                    self.assertEqual(names[mat.PHYSICAL[key] + mat.PHYSICAL_SWITCH], key + "_on")

    def test_no_issues(self):
        self.assertEqual(self.conv.stats.issues, [])


class MultiSub(unittest.TestCase):
    def test_fixture_by_material_id(self):
        cf, graph, by_name = _fixture("vray_wrappers")
        with cf:
            conv = mat.MaterialConverter(graph)
            multi = by_name["FixtureMulti"]
            got = {mid: (lambda ir: ir and ir.name)(conv.material_for(multi, mid)) for mid in range(16)}
            default = conv.convert(multi)
        # IDs 1, 3, 7 (zero-based 0, 2, 6); 3 is switched off. Past the list an ID wraps modulo 7
        self.assertEqual(got, {0: "FixtureSubOne", 1: None, 2: None, 3: None, 4: None, 5: None, 6: "FixtureSubSeven",
                               7: "FixtureSubOne", 8: None, 9: None, 10: None, 11: None, 12: None,
                               13: "FixtureSubSeven", 14: "FixtureSubOne", 15: None})
        self.assertEqual(default.name, "FixtureSubOne")
        self.assertEqual((dict(conv.stats.unknown), conv.stats.issues), ({}, []))

    def test_wrappers_around_and_inside(self):
        objs = (
            _wrapper(0, classids.VRAY_MTL_WRAPPER, {0: Ref(1)}),  # wrapper -> Multi
            _multi(1, [(4, Ref(2), 1), (5, Ref(3), 1), (6, Ref(4), 1)]),
            _wrapper(2, classids.VRAY_2SIDED_MTL, {0: Ref(5)}),  # Multi -> wrapper
            _multi(3, [(5, Ref(6), 1)]),  # nested Multi: the same ID
            _multi(4, [(0, Ref(6), 1)]),  # nested Multi without ID 6
            _vray(5, "Front"), _vray(6, "Deep"),
        )
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertEqual(conv.material_for(0, 4).name, "Front")
        self.assertEqual(conv.material_for(0, 5).name, "Deep")
        self.assertEqual(conv.material_for(0, 6).name, "Deep")  # the nested Multi without ID 6 wraps it to 0
        self.assertIsNone(conv.material_for(0, 9))  # 9 mod 7 = 2: no entry either
        self.assertEqual(conv.material_for(0, 11).name, "Front")  # 11 mod 7 = 4
        self.assertIsNone(conv.material_for(0, 12))  # 12 mod 7 = 5, then 12 mod 6 = 0: no entry in the nested one
        self.assertIsNone(conv.material_for(None, 0))
        self.assertEqual(conv.material_for(5, 3).name, "Front")  # not a Multi: whatever the ID
        self.assertEqual(conv.convert(0).name, "Front")

    def test_wrap_past_the_list(self):
        # what 3ds Max 2020 renders (one face per ID): an ID without an entry takes the entry of ID modulo the
        # highest ID of the list plus one, every entry counted; IDs below are zero-based
        def names(index, ids):
            return [(lambda ir: ir and ir.name)(conv.material_for(index, mid)) for mid in ids]
        objs = (_multi(0, [(0, Ref(10), 1), (1, Ref(11), 1)]),
                _multi(1, [(2, Ref(10), 1), (6, Ref(11), 1)]),
                _multi(2, [(6, Ref(10), 1), (2, Ref(11), 1)]),
                _multi(3, [(0, Ref(10), 1), (4, Ref(11), 1), (4, Ref(12), 1)]),
                _multi(4, [(0, Ref(10), 1), (1, Ref(11), 1), (2, Ref(12), 0)]),
                _multi(5, [(0, Ref(10), 1), (1, Ref(11), 1), (2, Ref(None), 1)]),
                _multi(6, [(0, Ref(10), 1), (1, Ref(7), 1)]),
                _multi(7, [(0, Ref(12), 1), (1, Ref(13), 1), (2, Ref(14), 1)]),
                _vray(10, "R"), _vray(11, "G"), _vray(12, "B"), _vray(13, "Y"), _vray(14, "C"))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertEqual(names(0, [2, 3, 10, 13]), ["R", "G", "R", "G"])
        self.assertEqual(names(0, [-1, -2]), [None, None])  # Python's % would map -1 to 1
        self.assertEqual(names(1, [9, 13, 16]), ["R", "G", "R"])  # modulo 7, not the entry count
        self.assertEqual(names(1, [0, 1, 3, 4, 5, 7, 8, 10, 14]), [None] * 9)  # no entry after the wrap
        self.assertEqual(names(2, [9, 13]), ["G", "R"])  # by ID, not by list position
        self.assertEqual(names(3, [4, 5, 9, 10]), ["G", "R", "G", "R"])  # the first of a duplicate ID wins
        self.assertEqual(names(4, [3, 5]), ["R", None])  # the highest entry switched off still counts
        self.assertEqual(names(5, [3, 5]), ["R", None])  # and an empty one
        # nested: the inner Multi gets the face's own ID and wraps it by its own list
        self.assertEqual(names(6, [1, 3, 5, 7, 9, 11, 2]), ["Y", "B", "C", "Y", "B", "C", "R"])
        self.assertEqual(conv.stats.issues, [])

    def test_missing_ids_list_duplicates_and_bad_entries(self):
        objs = (_multi(0, [(None, Ref(1), 1), (None, Ref(2), 1)], ids=False), _vray(1, "A"), _vray(2, "B"),
                _multi(3, [(2, Ref(1), 1), (2, Ref(2), 1), (-1, Ref(2), 1), (True, Ref(2), 1)]),
                _multi(4, [(0, Ref(None), 1), (1, Ref(1), 0)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertEqual((conv.material_for(0, 0).name, conv.material_for(0, 1).name), ("A", "B"))  # IDs = k
        self.assertEqual(conv.material_for(3, 2).name, "A")  # the first entry of an ID wins
        self.assertIsNone(conv.material_for(3, 1))
        default = conv.convert(4)  # every entry empty or off
        self.assertTrue(default.unknown)
        self.assertEqual(default.name, "Multi")
        self.assertIn("no sub-material", default.issues[0])
        self.assertEqual(dict(conv.stats.unknown), {})

    def test_cycle_and_depth(self):
        conv = mat.MaterialConverter(FakeGraph(_multi(0, [(1, Ref(1), 1), (2, Ref(1), 1)]),
                                               _multi(1, [(1, Ref(0), 1), (2, Ref(0), 1)])))
        self.assertIsNone(conv.material_for(0, 1))
        self.assertIsNone(conv.material_for(0, 2))
        self.assertEqual(len(conv.stats.issues), 1)  # once, whatever the number of face IDs
        self.assertIn("cycle", conv.stats.issues[0][1])
        conv = mat.MaterialConverter(FakeGraph(_multi(0, [(1, Ref(5), 1)]), _map(5)))
        self.assertIsNone(conv.material_for(0, 1))
        self.assertEqual(conv.stats.issues, [(0, "Multi/Sub-Object 0: sub-material 5 is not a material")])
        objs = [_multi(i, [(0, Ref(i + 1), 1)]) for i in range(mat.MAX_PEEL + 1)] + [_vray(mat.MAX_PEEL + 1, "Deep")]
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertIsNone(conv.material_for(0, 0))
        self.assertIn("nested", conv.stats.issues[0][1])
        self.assertEqual(conv.material_for(1, 0).name, "Deep")


if __name__ == "__main__":
    unittest.main()
