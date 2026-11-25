# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/texmaps/ on the V-Ray maps: vray_texmaps and the synthetic VRayBitmap and
VRayColor rules, no Blender.

    python -I -m unittest discover tests
"""
import collections
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
    _lin, _Swatch, _table, _tex, _vbitmap, assets, Checks, classids, FakeGraph, FakeMap, Fixture, G1,
    G2, mat, Ref, tx,
)


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
        cc = self.held(self.f.irs["FixtureCCComposite"].textures["base_color"].root)
        self.assertIsInstance(cc, tx.ColorCorrect)  # gamma off: corrected and composited on the held values
        self.close(cc.brightness, 0.1)
        self.assertIsInstance(cc.input, tx.Composite, "one Decode, at the root (em3.158, 6n0.6.18)")
        a, b = cc.input.layers
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
        fo = self.held(g.root)  # gamma off: on the held values (maxdrop-6n0.6.18)
        self.assertIsInstance(fo, tx.Mix)  # the Falloff: its map 1 to its color 2
        self.close(fo.a.value, (50 / 255, 150 / 255, 250 / 255))
        self.assertIsInstance(fo.mask, tx.Facing)
        self.assertFalse(g.approximated)
        cc = self.held(self.f.irs["FixtureCCColor"].textures["base_color"].root)
        self.assertIsInstance(cc, tx.ColorCorrect)
        self.close(cc.saturation, 1.2)
        self.close(cc.input.value, (100 / 255, 200 / 255, 50 / 255))
        mix = self.f.irs["FixtureMixMask"].textures["base_color"].root.input
        self.assertIsInstance(mix.mask, tx.Constant)
        self.close(mix.mask.value, 64 / 255)  # a float, as stored: V-Ray mixes the stored colors by it (em3.158)

    def test_falloff_in_reflection(self):
        black, white = tx.Constant((0.0, 0.0, 0.0)), tx.Constant((1.0, 1.0, 1.0))
        ir = self.f.irs["FixtureVReflPerp"]
        g = ir.textures["specular"]  # the default Falloff: black facing the viewer, white at grazing; gamma off:
        # the ratio V-Ray holds, shown decoded (maxdrop-6n0.6.18)
        self.assertEqual(g.root, tx.Decode(tx.Mix(black, white, 0.0, tx.Facing(tx.PERPENDICULAR))))
        self.assertEqual((g.approximated, g.issues), (False, ()))
        self.assertEqual((ir.metallic.value, ir.metallic.map), (0.0, None), "Fresnel off, a dark swatch: no metal")
        self.assertFalse(ir.fresnel, "Fresnel off: the Falloff is the reflection at every angle, no Fresnel on it")
        self.assertNotIn("base_color", ir.textures)
        g = self.f.irs["FixtureVReflFresnel"].textures["specular"]  # map amount 50: half the swatch (black)
        self.assertEqual(g.root, tx.Decode(tx.Mix(black, tx.Mix(black, white, 0.0, tx.Facing(tx.FRESNEL, 1.5)),
                                                  0.5)))
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
        self.assertEqual(textures["specular"].root,
                         tx.Decode(tx.Mix(black, white, 0.0, tx.Facing(tx.PERPENDICULAR))))

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


if __name__ == "__main__":
    unittest.main()
