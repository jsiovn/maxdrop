# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/texmaps/ on the Corona maps: the fixtures and the synthetic CoronaBitmap,
CoronaColor and CoronaMix rules, no Blender.

    python -I -m unittest discover tests
"""
import collections
import math
import os
import sys
import types
import unittest

_TESTS = "maxdrop_unit_tests"  # tests/unit as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_unit_tests.texmaps_support import (  # noqa: E402 (after the loader)
    _cbitmap, _ccolor, _cmix, _noise, _table, _tex, assets, Checks, classids, colors, FakeMap, Fixture,
    G1, G2, mat, P5_BOTTOM, P5_TOP, Ref, tx,
)


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
        held = self.held(g.root)  # the material's map amount over its color, on the held values (maxdrop-6n0.6.18)
        self.assertIsInstance(held, tx.Mix)
        self.close(held.factor, 0.75)
        self.close(held.a.value, tuple(c / 255 for c in (150, 140, 130)))
        image = held.b
        self.image(image, "fixture_c_base.png", tx.SRGB, tiling=(2.0, 3.0), offset=(0.1, 0.2), w_angle=30.0,
                   channel=2)
        self.assertEqual((image.mapping.tile, image.mapping.mirror), ((True, False), (True, False)))
        self.close(image.mapping.blur, 0.8)
        self.assertEqual((image.crop, image.output, image.alpha), (None, None, False))
        self.assertIsNone(image.gamma, "gamma off: its own decode, held (maxdrop-em3.165), the Decode shows it")
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
        self.assertIsInstance(g.root, tx.Multiply, "levelReflect 0.5 scales the map (maxdrop-6n0.6.6)")
        self.close(g.root.b.value, (0.5, 0.5, 0.5))
        self.assertIsInstance(g.root.a, tx.Decode)
        blend = g.root.a.input
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

    def test_gamma_under_a_grey_swatch_over_a_map(self):
        """FixtureCoronaMixGammaGrey: gamma, colorTop 128, a CoronaBitmap bottom, mix in sRGB on (maxdrop-6n0.6.40).
        renderMap with a flat 64 / 128 / 192 PNG as the bottom, gamma off and on alike: bottom (0.04776, 0.21953,
        0.53567), the mix (0.015595, 0.125628, 0.425696): one exponent ln(bottom) / ln(mix) = 0.7310, the top
        swatch as stored, (128 / 255)^(1 / 2.2) (decoded it would be 0.498)."""
        root = self.root("GammaGrey")
        self.assertIsInstance(root, tx.Decode)
        cc = root.input
        self.assertIsInstance(cc, tx.ColorCorrect)
        self.assertEqual(cc.input.name, "cmix_gamma_bottom.png")
        self.assertTrue(cc.magnitude, "sRGB mode: the magnitude of a negative bottom")
        for b, r in zip((0.0477607, 0.219532, 0.535668), (0.0155947, 0.125628, 0.425696)):
            self.assertAlmostEqual(cc.gamma, math.log(b) / math.log(r), delta=1e-3)
            self.assertAlmostEqual(b ** (1.0 / cc.gamma), r, delta=1e-4)

    def test_gamma_at_half_amount(self):
        root = self.root("GammaHalf")
        self.assertIsInstance(root, tx.Constant, "a Mix of constants, folded")
        for ours, theirs in zip(root.value, (0.0329595, 0.342412, 0.882582)):  # renderMap, shown decoded
            self.assertAlmostEqual(ours, colors.srgb_to_linear(theirs), delta=1e-3)

    def test_nothing_peeled(self):
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter())
        self.assertEqual(self.f.tex.stats.issues, [])


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
        # a colored top over a map, a top image map, a top of 0: peeled to the first bitmap, the operation named
        table = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\a.png", ""),
                                   assets.AssetEntry(G2, "Bitmap", "maps\\b.png", "")])
        for params in (dict(p208=(0.5, 0.25, 1.0)), dict(p206=Ref(3)), dict(p208=(0.0, 0.0, 0.0))):
            with self.subTest(params=params):
                tex = _tex(_cmix(1, [2, 3], p200=7, p207=Ref(2), **params), _cbitmap(2), _cbitmap(3, G2),
                           table=table)
                g = tex.convert(mat.MapRef(1), tx.COLOR)
                self.assertEqual(g.root.name, "a.png")
                self.assertTrue(g.approximated)
                self.assertEqual([r for _i, r in tex.stats.issues],
                                 ["CoronaMix 'map': operation gamma drawn as its first bitmap"])
        # a top map that converts to nothing: the lost-side rule, its other side (maxdrop-6n0.6.24: sides first)
        tex = _tex(_cmix(1, [2, 3], p200=7, p206=Ref(3), p207=Ref(2)), _cbitmap(2), _cbitmap(3, G2))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual((g.root.name, g.approximated), ("a.png", True))
        self.assertTrue(any("converts to nothing" in r for _i, r in tex.stats.issues), tex.stats.issues)
        self.close(tx._gamma_value(1e6, 0.01), tx.MAX_MULTIPLIER, "held")

    def test_corona_mix_gamma_on_converted_sides(self):
        """maxdrop-6n0.6.24 (a): the gamma operation is decided on the converted sides: a top map that converts to a
        constant (CoronaColor) is a top color, and a colored top folds per channel over a bottom map that does."""
        grey = _ccolor(3, p50=1, p58=(0.5, 0.5, 0.5))  # HDR color: linear as stored with the gamma on
        for srgb, want in ((1, 0.5 ** (1 / 2.2)), (0, 0.5)):
            with self.subTest(srgb=srgb):
                tex = _tex(_cmix(1, [2, 3], p200=7, p206=Ref(3), p207=Ref(2), p214=srgb), _cbitmap(2), grey)
                g = tex.convert(mat.MapRef(1), tx.COLOR)
                self.assertIsInstance(g.root, tx.ColorCorrect)
                self.close(g.root.gamma, want)
                self.assertEqual(g.root.input.name, "a.png")
                self.assertEqual((g.approximated, g.issues, tex.stats.issues), (False, (), []))
        # a colored top color over a CoronaColor bottom map: folded per channel (linear mode: bottom ^ (1 / top))
        tex = _tex(_cmix(1, [2], p200=7, p207=Ref(2), p208=(0.5, 0.25, 1.0), p214=0),
                   _ccolor(2, p50=1, p58=(0.05, 0.4, 0.9)))
        root = tex.convert(mat.MapRef(1), tx.COLOR).root
        self.assertIsInstance(root, tx.Constant)
        self.close(root.value, (0.05 ** 2, 0.4 ** 4, 0.9))
        # a colored CoronaColor top map over a bitmap: one exponent per channel, no node: peeled, the operation named,
        # once
        tex = _tex(_cmix(1, [2, 3], p200=7, p206=Ref(3), p207=Ref(2)), _cbitmap(2),
                   _ccolor(3, p50=1, p58=(0.5, 0.25, 1.0)))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual((g.root.name, g.approximated), ("a.png", True))
        self.assertEqual(g.issues, ("CoronaMix 'map': operation gamma drawn as its first bitmap",))
        self.assertEqual(tex.stats.issues, [(1, "CoronaMix 'map': operation gamma drawn as its first bitmap")])
        self.assertEqual(tex.stats.peeled, collections.Counter({"CoronaMix": 1}))

    def test_corona_mix_gamma_converts_each_layer_once(self):
        """The layers the gamma decision converted are the ones drawn: no layer is asked for twice."""
        for name, bottom, top, want in (
                ("grey top over a bitmap", _cbitmap(2), (0.5, 0.5, 0.5), tx.ColorCorrect),
                ("colored top over a constant", _ccolor(2, p50=1, p58=(0.2, 0.4, 0.6)), (0.5, 0.25, 1.0), tx.Constant)):
            with self.subTest(name):
                tex = _tex(_cmix(1, [2, 3], p200=7, p206=Ref(3), p207=Ref(2)), bottom, _ccolor(3, p50=1, p58=top))
                calls, sub = collections.Counter(), tex._sub
                tex._sub = lambda m, pid, *a, **k: (calls.update([(m.index, pid)]), sub(m, pid, *a, **k))[1]
                self.assertIsInstance(tex.convert(mat.MapRef(1), tx.COLOR).root, want)
                self.assertEqual({k: n for k, n in calls.items() if k[1] in (206, 207)}, {(1, 206): 1, (1, 207): 1})

    def test_corona_mix_negative_layers(self):
        """renderMap of probe1's P5 (maxdrop-em3.117): CoronaColor HDR layers below 0 by their offsets; in sRGB mode
        Corona raises each layer's magnitude (maxdrop-em3.161), the gamma operation's top exponent and bottom too."""
        for op, srgb, want in ((0, 1, (1.18624, 1.13619, 0.799878)), (0, 0, (0.399786, 0.0997939, 0.799878)),
                               (14, 1, (0.629587, 0.258488, 0.624094)), (20, 1, (0.288395, 0.22034, 0.799878)),
                               (11, 0, (-0.200198, 0.249943, 0.0)),
                               # gamma: P5's renderMap through its CoronaColor maps (maxdrop-6n0.6.24: the top map
                               # is a constant); the bottom's blue is 0, so the top's 1.1 (0.9 below) changes nothing
                               (7, 1, (0.0424199, 0.0817881, 0.0))):
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

    def test_corona_mix_gamma_peeled_on_its_top_converts_nothing_else(self):
        # maxdrop-6n0.6.24: the top decides first; an image top peels before the bottom and the mask are converted
        tex = _tex(_cmix(1, [2, 3, 4], p200=7, p206=Ref(2), p207=Ref(3), p210=Ref(4)), _cbitmap(2), _noise(3),
                   _noise(4))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertEqual(tex.stats.unsupported, collections.Counter(), "the bottom and mask Noise are never drawn")
        self.assertEqual([r for _i, r in tex.stats.issues], ["CoronaMix 'map': operation gamma drawn as its first "
                                                             "bitmap"])
        # a colored constant top: the bottom decides, the mask is not converted
        tex = _tex(_cmix(1, [2, 3], p200=7, p208=(0.5, 0.25, 1.0), p207=Ref(2), p210=Ref(3)), _cbitmap(2),
                   _noise(3))
        self.assertEqual(tex.convert(mat.MapRef(1), tx.COLOR).root.name, "a.png")
        self.assertEqual(tex.stats.unsupported, collections.Counter(), "the mask Noise is never drawn")

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


if __name__ == "__main__":
    unittest.main()
