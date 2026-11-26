# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/materials/ on the Corona fixtures: Corona materials and their classes, media,
legacy glossiness and opacity, no Blender.

    python -I -m unittest discover tests
"""
import importlib
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
from maxdrop_unit_tests.convert_materials_support import (  # noqa: E402 (after the loader)
    _close_medium, _convert, _corona, _fixture, _hair_color, _lin, _lins, _map, _medium, _PKG, classids,
    Close, GREY, mat, numpy, reader_scene, Ref, texmaps,
)


class Corona(unittest.TestCase, Close):
    """tools/fixtures/corona_physical.ms, corona_legacy.ms, corona_layered.ms and corona_light.ms, by hand."""

    def convert(self, fixture, *names):
        cf, graph, by_name = _fixture(fixture)
        with cf:
            conv = mat.MaterialConverter(graph)
            irs = [conv.convert(by_name[n]) for n in names]
        return conv, irs

    def test_physical(self):
        conv, (rough, gloss, glass) = self.convert("corona_physical", "FixtureCoronaPhysRough",
                                                   "FixtureCoronaPhysGloss", "FixtureCoronaPhysGlass")
        self.assertEqual((rough.source, rough.unknown), ("CoronaPhysicalMtl", False))  # the leading CR stripped
        self.close(rough.base_color.value, tuple(c * 0.9 for c in _lins(200, 120, 60)), "base x level 0.9")
        self.close(rough.roughness.value, 0.35, "roughness mode")
        self.close(rough.metallic.value, 0.0)
        self.close(rough.ior, 1.45)
        self.close(rough.coat_weight, 0.4)
        self.close(rough.coat_ior, 1.6)
        self.close(rough.coat_roughness, 0.2)
        self.close(rough.coat_color, _lins(230, 210, 190), "clearcoat absorption color")
        self.close(rough.emission_color.value, _lins(255, 128, 0))
        self.close(rough.emission_strength, 2.5)
        self.close(rough.alpha.value, 200 / 255.0 * 0.8, "mean opacity color as stored x level (em3.122)")
        self.close(rough.specular.value, 1.0, "the IOR's own Fresnel: no level parameter")
        self.close(gloss.base_color.value, _lins(220, 180, 90))
        self.close(gloss.metallic.value, 1.0, "metalness mode metal")
        self.close(gloss.roughness.value, 0.3, "glossiness 0.7")
        self.close(gloss.coat_roughness, 0.1, "the clearcoat roughness is a glossiness too")
        tint = _lins(150, 200, 255)
        self.close(glass.base_color.value, tuple(_lin(40) * 0.1 + c * 0.9 for c in tint), "toward the thin tint")
        self.close(glass.transmission.value, 0.9)
        self.assertTrue(glass.thin_walled)
        self.close(glass.ior, 1.52)
        self.close(glass.roughness.value, 0.05)
        self.assertEqual((conv.stats.issues, dict(conv.stats.unknown)), ([], {}))

    def test_physical_ior_mode_and_thin_translucency(self):
        """Corona 12 renders (maxdrop-em3.115): IOR mode 1 holds specular levels, F0 = 0.08 x level, in the base and
        clearcoat IORs; translucency renders only in thin mode."""
        conv, (spec, thin) = self.convert("corona_physical", "FixtureCoronaPhysSpec", "FixtureCoronaPhysTranslThin")
        self.close(spec.ior, mat.ior_from_reflectance(0.08 * 1.2), "specular 1.2")
        self.close(spec.coat_ior, mat.ior_from_reflectance(0.08 * 0.8), "specular 0.8")
        self.close(spec.coat_weight, 0.5)
        self.assertEqual(spec.issues, [])
        self.close(thin.ior, 1.5, "IOR mode 0")
        self.assertTrue(thin.thin_walled)
        self.assertEqual(thin.issues, ["CoronaPhysicalMtl 'FixtureCoronaPhysTranslThin': translucency not converted"])

    def test_legacy(self):
        conv, (pbr, old, metal) = self.convert("corona_legacy", "FixtureCoronaLegacyPbr", "FixtureCoronaLegacyGloss",
                                               "FixtureCoronaLegacyMetal")
        self.assertEqual(pbr.source, "CoronaLegacyMtl")
        self.close(pbr.base_color.value, tuple(c * 0.85 for c in _lins(180, 60, 40)), "diffuse x level")
        self.close(pbr.specular.value, _lin(220) * 0.6, "mean reflection x level")
        self.close(pbr.roughness.value, 0.28, "1 - glossiness 0.72")
        self.close(pbr.metallic.value, 0.0)
        self.close(pbr.ior, 1.6, "Fresnel IOR without refraction")
        self.close(pbr.emission_color.value, _lins(0, 128, 255))
        self.close(pbr.emission_strength, 1.5)
        self.close(pbr.alpha.value, 230 / 255.0 * 0.9)  # a data input: the swatch as stored
        refract = _lins(200, 230, 255)
        t = sum(refract) / 3 * 0.75
        self.close(old.transmission.value, t, "mean refraction x level")
        self.close(old.base_color.value, tuple(d * (1 - t) + r * t for d, r in zip(_lins(90, 110, 130), refract)))
        self.close(old.roughness.value, 0.324, "PBR mode off: glossiness 0.4 renders as PBR glossiness 0.676")
        self.close(old.specular.value, 1.0)
        self.close(old.ior, 1.33, "the refraction IOR")
        self.assertTrue(old.thin_walled)
        self.close(metal.metallic.value, 1.0, "Fresnel IOR 999 and a bright reflection")
        self.close(metal.base_color.value, _lins(250, 200, 120), "the reflection color")
        self.close(metal.roughness.value, 0.1)
        self.assertEqual(conv.stats.issues, [], "PBR mode off without a glossiness map: measured (maxdrop-em3.115)")

    def test_layered_mixes_its_layer_or_peels_without_a_base(self):
        cf, graph, by_name = _fixture("corona_layered")
        with cf:
            conv = mat.MaterialConverter(graph)
            layered = conv.convert(by_name["FixtureCoronaLayered"])
            base = conv.convert(by_name["FixtureCoronaLayerBase"])
            coat = conv.convert(by_name["FixtureCoronaLayerCoat"])
            nobase = conv.convert(by_name["FixtureCoronaLayeredNoBase"])
            only = by_name["FixtureCoronaLayerOnly"]
            self.assertEqual(conv.peel(by_name["FixtureCoronaLayered"]), (by_name["FixtureCoronaLayered"], None))
            self.assertEqual(conv.peel(by_name["FixtureCoronaLayeredNoBase"]), (only, None))
        self.assertIsNot(layered, base)
        self.assertEqual((layered.name, layered.source), ("FixtureCoronaLayered", "CoronaLayeredMtl"))
        self.close(layered.base_color.value, _lins(90, 160, 70), "the base's inputs")
        self.close(layered.roughness.value, 0.45)
        self.assertEqual(len(layered.layers), 1)
        layer = layered.layers[0]
        self.assertIs(layer.ir, coat)
        self.close(layer.amount, 0.5)
        self.assertEqual(layer.mask.index, by_name["FixtureCLayerMask"])
        self.close(layer.mask.amount, 1.0, "mask amount")
        self.assertIsNone(layer.graph, "no TexmapConverter")
        self.assertEqual(base.layers, [], "the base itself is untouched")
        self.assertEqual(nobase.name, "FixtureCoronaLayerOnly")
        self.close(nobase.base_color.value, _lins(70, 80, 200))
        self.assertEqual(conv.stats.peeled, {"CoronaLayeredMtl": 1}, "only the one without a base")

    def test_light(self):
        cf, graph, by_name = _fixture("corona_light")
        with cf:
            conv = mat.MaterialConverter(graph)
            light, plain = conv.convert(by_name["FixtureCoronaLight"]), conv.convert(by_name["FixtureCoronaLightPlain"])
        self.close(light.base_color.value, (0.0, 0.0, 0.0))
        self.close(light.specular.value, 0.0)
        self.close(light.emission_color.value, _lins(255, 200, 150))
        self.close(light.emission_strength, 12.5)
        self.assertEqual(light.emission_color.map, mat.MapRef(by_name["FixtureCLightTex"]))
        self.assertEqual(light.alpha.map, mat.MapRef(by_name["FixtureCLightAlpha"]))
        self.close(plain.emission_color.value, _lins(100, 150, 255))
        self.close(plain.emission_strength, 3.0)
        self.assertIsNone(plain.emission_color.map, "texmapOn off")

    def test_map_slots(self):
        cf, graph, by_name = _fixture("corona_maps")
        with cf:
            conv = mat.MaterialConverter(graph)
            ir, legacy = conv.convert(by_name["FixtureCoronaMaps"]), conv.convert(by_name["FixtureCoronaLegacyMaps"])
        self.assertEqual(ir.base_color.map.index, by_name["FixtureCBase"])
        self.close(ir.base_color.map.amount, 0.75, "a fraction")
        self.assertEqual(ir.roughness.map.index, by_name["FixtureCGloss"])
        self.assertTrue(ir.roughness.map.invert, "glossiness mode")
        self.close(ir.roughness.map.amount, 0.6)
        self.close(ir.roughness.value, 0.4)
        self.assertEqual(ir.alpha.map, mat.MapRef(by_name["FixtureCOpacity"]))
        self.assertEqual(ir.normal.index, by_name["FixtureCNormal"])
        self.close(ir.normal.amount, 0.9)
        self.assertEqual(ir.metallic.map, mat.MapRef(by_name["FixtureCColor"]))
        self.assertEqual(ir.emission_color.map, mat.MapRef(by_name["FixtureCMix"]))
        self.assertEqual(legacy.base_color.map, mat.MapRef(by_name["FixtureCMultiply"]))
        self.assertEqual(legacy.specular.map, mat.MapRef(by_name["FixtureCAdd"], scale=0.5), "levelReflect 0.5")
        self.assertEqual(legacy.roughness.map, mat.MapRef(by_name["FixtureCLegacyGloss"], 1.0, True))
        self.assertEqual(legacy.bump, mat.MapRef(by_name["FixtureCLegacyBump"], 0.5))
        self.assertEqual(legacy.alpha.map, mat.MapRef(by_name["FixtureCHdr"]))
        self.assertIsNone(legacy.emission_color.map, "slot switched off")
        self.assertEqual(conv.stats.issues, [])


class CoronaMore(unittest.TestCase, Close):
    """tools/fixtures/corona_more.ms, by hand (millimeters, gamma off)."""

    @classmethod
    def setUpClass(cls):
        cls.cf, cls.graph, cls.by_name = _fixture("corona_more")
        cls.conv = mat.MaterialConverter(cls.graph)
        cls.irs = {n: cls.conv.convert(i) for n, i in cls.by_name.items()}

    @classmethod
    def tearDownClass(cls):
        cls.cf.close()

    def ir(self, name):
        return self.irs["FixtureCorona" + name]

    def test_meters_from_the_file(self):
        self.close(self.conv.meters, 0.001)

    def test_physical_sss(self):
        ir = self.ir("PhysSss")
        self.close(ir.subsurface_weight, 0.6)
        self.close(ir.subsurface_radius, 0.0025, "2.5 mm")
        self.close(ir.subsurface_color, _lins(220, 80, 50))
        self.close(ir.base_color.value, _lins(230, 190, 170))
        self.assertEqual(ir.issues, [])

    def test_physical_sheen(self):
        ir = self.ir("PhysSheen")
        self.close(ir.sheen_weight, 0.7)
        self.close(ir.sheen_color, _lins(250, 200, 230))
        self.close(ir.sheen_roughness, 0.4)
        self.assertEqual(ir.issues, ["CoronaPhysicalMtl 'FixtureCoronaPhysSheen': sheen amount map not converted"])

    def test_physical_named_issues(self):
        self.assertEqual(self.ir("PhysTransl").issues, [], "translucency without thin mode: none in Corona 12")
        absorb = self.ir("PhysAbsorb")
        self.close(absorb.transmission.value, 1.0)
        self.assertEqual(absorb.issues, [], "volumetric absorption and scattering: a medium (maxdrop-em3.163)")
        self.assertEqual(self.ir("PhysEdge").issues,
                         ["CoronaPhysicalMtl 'FixtureCoronaPhysEdge': metal edge color not converted"])
        spec = self.ir("PhysIorMode")
        self.assertEqual(spec.issues, [], "IOR mode 1, a specular level: measured (maxdrop-em3.115)")
        self.close((spec.ior, spec.coat_ior), (1.5, 1.5), "specular 0.5 is F0 0.04, IOR 1.5 (the stored 0.5s)")

    def test_physical_complex_ior(self):
        ir = self.ir("PhysComplex")
        want = tuple(mat.f0_from_complex_ior(n, k) for n, k in ((0.2, 3.9), (0.9, 2.4), (1.1, 2.2)))
        self.close(ir.base_color.value, want)
        self.close(ir.metallic.value, 1.0)
        self.close(ir.roughness.value, 0.3)
        self.assertEqual(ir.issues, [], "no edge color issue: the complex IOR stands for it")

    def test_legacy_sss(self):
        ir = self.ir("LegacySss")
        self.close(ir.subsurface_weight, 0.8)
        self.close(ir.subsurface_radius, 0.0015)
        self.close(ir.subsurface_color, _lins(200, 60, 40))
        self.assertEqual(ir.issues, [])

    def test_legacy_without_pbr(self):
        ir = self.ir("LegacyNoPbr")
        self.close(ir.roughness.value, 0.165, "glossiness 0.6, PBR mode off: CORONA_LEGACY_GLOSS")
        self.close(ir.transmission.value, 0.5)
        self.assertEqual(ir.issues, ["CoronaLegacyMtl 'FixtureCoronaLegacyNoPbr': translucency not converted"])

    def test_physical_medium(self):
        """FixtureCoronaPhysAbsorb: absorption 100 / 180 / 255 at 5 mm, scattering 40 grey (gamma off: decoded)."""
        got = self.ir("PhysAbsorb").medium
        self.assertIsNotNone(got)
        _close_medium(self, got, _medium(_lins(100, 180, 255), 0.005, _lins(40, 40, 40)))

    def test_legacy_medium(self):
        """FixtureCoronaLegacyNoPbr: absorption 90 / 150 / 60 at 3 mm, no scattering (the default black)."""
        got = self.ir("LegacyNoPbr").medium
        self.assertIsNotNone(got)
        _close_medium(self, got, _medium(_lins(90, 150, 60), 0.003, (0.0, 0.0, 0.0)))

    def test_layered(self):
        ir = self.ir("Layers")
        self.assertEqual(ir.source, "CoronaLayeredMtl")
        self.close(ir.base_color.value, _lins(90, 160, 70), "the base")
        self.assertEqual([la.ir.name for la in ir.layers], ["FixtureCoronaLayersOne", "FixtureCoronaLayersTwo"],
                         "the switched-off third layer left out")
        one, two = ir.layers
        self.close((one.amount, two.amount), (0.3, 0.6))
        self.assertIsNone(one.mask)
        self.assertEqual(two.mask, mat.MapRef(self.by_name["FixtureCLayersMask"], 0.5))
        self.assertIs(two.ir, self.ir("LayersTwo"))
        self.close(two.ir.base_color.value, _lins(200, 60, 40))
        self.assertEqual(ir.issues, [])
        self.assertNotIn("CoronaLayeredMtl", self.conv.stats.peeled)

    def test_layered_mask_graph(self):
        cf, graph, by_name = _fixture("corona_more")
        with cf:
            tex = texmaps.TexmapConverter(graph)
            conv = mat.MaterialConverter(graph, texmaps=tex)
            two = conv.convert(by_name["FixtureCoronaLayers"]).layers[1]
        root = two.graph.root
        self.assertIsInstance(root, texmaps.Mix, "lerp(1, mask, mask amount): Corona 12 renders it (em3.115)")
        self.close(root.a.value, 1.0)
        self.close(root.b.value, _lin(64))
        self.close(root.factor, 0.5)

    def test_skin(self):
        ir = self.ir("Skin")
        self.close(ir.base_color.value, tuple(c * 0.9 for c in _lins(200, 150, 120)))
        self.close(ir.subsurface_weight, 0.8)
        colors_ = [(0.521569, 0.635294, 0.666667), (0.439216, 0.156863, 0.0784314), (0.439216, 0.0784314, 0.0196078)]
        lin = [tuple(_lin(round(c * 255)) for c in col) for col in colors_]
        self.close(ir.subsurface_color, tuple(sum(c[i] for c in lin) / 3 for i in range(3)), "equal weights")
        self.close(ir.subsurface_radius, 2.0 * (0.75 + 1.5 + 4.0) / 3 * 0.001)
        self.close(ir.specular.value, 0.6)
        self.close(ir.roughness.value, 0.3)
        self.close(ir.ior, 1.45)
        self.close(ir.alpha.value, 0.9)
        self.assertEqual(ir.issues, [])

    def test_hair_defaults(self):
        ir = self.ir("Hair")
        self.assertFalse(ir.unknown)
        self.assertEqual(self.conv.stats.unknown["CoronaHairMtl"], 0)
        self.close(ir.base_color.value, _hair_color(0.5, 0.0, (1.0, 1.0, 1.0)))
        self.close(ir.roughness.value, 0.5)
        self.close(ir.ior, 1.55)
        self.close(ir.alpha.value, 1.0)
        self.assertEqual(ir.issues, [])

    def test_ray_switch_and_select_peel(self):
        self.assertIs(self.ir("RaySwitch"), self.ir("RaySwitchDirect"), "what the camera sees")
        self.assertIs(self.ir("Select"), self.ir("SelectB"), "selected 1, zero-based")
        self.assertEqual(self.conv.stats.peeled["CoronaRaySwitchMtl"], 1)
        self.assertEqual(self.conv.stats.peeled["CoronaSelectMtl"], 1)


class CoronaClasses(unittest.TestCase, Close):
    """tools/fixtures/corona_classes.ms, by hand (millimeters, gamma off)."""

    @classmethod
    def setUpClass(cls):
        cls.cf, cls.graph, cls.by_name = _fixture("corona_classes")
        cls.conv = mat.MaterialConverter(cls.graph)
        cls.irs = {n: cls.conv.convert(i) for n, i in cls.by_name.items()}

    @classmethod
    def tearDownClass(cls):
        cls.cf.close()

    def ir(self, name):
        return self.irs["FixtureCorona" + name]

    def test_hair(self):
        ir = self.ir("HairSet")
        self.assertFalse(ir.unknown)
        self.assertEqual(ir.source, "CoronaHairMtl")
        tint = tuple(0.9 * c for c in _lins(230, 200, 180))
        diffuse = tuple(0.5 * c for c in _lins(40, 30, 20))
        self.close(ir.base_color.value, _hair_color(0.3, 0.6, tint, diffuse))
        self.assertIsNone(ir.base_color.map, "Corona adds a tint map to the melanin's absorption: not drawn")
        self.close(ir.roughness.value, 0.3, "1 - glossiness 0.7")
        self.close(ir.ior, 1.6)
        self.close(ir.specular.value, 1.0)
        self.close(ir.alpha.value, 200 / 255 * 0.8, "the opacity swatch as stored times its level")
        self.assertEqual(ir.issues, ["CoronaHairMtl 'FixtureCoronaHairSet': tint map not converted",
                                     "CoronaHairMtl 'FixtureCoronaHairSet': melanin map not converted"])

    def test_shadow_catchers(self):
        plain, refl = self.ir("ShadowCatcher"), self.ir("ShadowCatcherRefl")
        for ir in (plain, refl):
            self.assertTrue(ir.shadow_catcher)
            self.assertFalse(ir.unknown)
            self.close(ir.base_color.value, GREY)
        self.assertEqual(plain.issues, [])
        self.assertEqual(refl.issues, ["CoronaShadowCatcherMtl 'FixtureCoronaShadowCatcherRefl': backplate map not "
                                       "converted", "CoronaShadowCatcherMtl 'FixtureCoronaShadowCatcherRefl': "
                                       "reflection not converted"])
        self.assertFalse(self.ir("CatcherMixedPhys").shadow_catcher)
        self.assertFalse(self.ir("HairSet").shadow_catcher)

    def test_named_greys(self):
        for name, cls, what in (("Scanned", "CoronaScannedMtl", "scanned material (.ctf) not read"),
                                ("Slicer", "CoronaSlicerMtl", "slicing not converted")):
            ir = self.ir(name)
            self.assertTrue(ir.unknown, name)
            self.assertEqual(ir.source, cls)
            self.close(ir.base_color.value, GREY)
            self.assertEqual(ir.issues, ["%s 'FixtureCorona%s': %s, grey" % (cls, name, what)])

    def test_no_class_without_a_rule(self):
        self.assertEqual(dict(self.conv.stats.unknown), {})

    def test_volume(self):
        """FixtureCoronaVolume (maxdrop-em3.163): no surface (alpha 0), the medium of absorption 200 / 150 / 100 at
        10 mm, scattering 120 grey, directionality 0.3, emission 255 / 128 / 0 at 5 mm (gamma off: decoded)."""
        ir = self.ir("Volume")
        self.assertFalse(ir.unknown)
        self.assertEqual(ir.source, "CoronaVolumeMtl")
        self.assertEqual(ir.issues, [])
        self.close(ir.alpha.value, 0.0)
        want = _medium(_lins(200, 150, 100), 0.01, _lins(120, 120, 120), 0.3,
                       tuple(c / 0.005 for c in _lins(255, 128, 0)))
        _close_medium(self, ir.medium, want)

    @unittest.skipIf(numpy is None, "numpy missing")  # assign() needs it
    def test_shadow_catcher_users(self):
        s = reader_scene.Scene.from_file(self.cf)
        desc = importlib.import_module(_PKG + ".convert.scene").describe(s, 0.001, None)
        plan = mat.assign(desc, mat.node_materials(s, desc), self.conv)
        names = {n.index: n.name for n in desc.nodes}
        got = sorted(names[u] for ms in plan.values() for u in mat.shadow_catcher_users(ms))
        self.assertEqual(got, ["FixtureCoronaShadowCatcherBox", "FixtureCoronaShadowCatcherReflBox"])
        mixed = next(ms for ms in plan.values() if names[ms.users[0]] == "FixtureCoronaCatcherMixedBox")
        self.assertEqual(len(mixed.slots), 2, "the catcher and the physical material, one slot each")


class CoronaMedia(unittest.TestCase, Close):
    """corona_medium and the three rules that make one (Corona 12 renders, maxdrop-em3.163): the absorption color is
    reached at its distance, the scattering color is the albedo of that extinction, emission is its color over its
    distance per unit length; distances in world units."""

    def volume(self, **params):
        return _convert(_corona(0, classids.CORONA_VOLUME_MTL, **params), *[_map(i) for i in range(1, 4)])

    def test_volume_defaults_are_empty(self):
        """As created: absorption distance 0 (off), scattering black, emission distance 0: no medium, nothing."""
        _conv, ir = self.volume()
        self.assertIsNone(ir.medium)
        self.close(ir.alpha.value, 0.0, "no surface whatever the medium")
        self.assertFalse(ir.unknown)
        self.assertEqual(ir.issues, [])

    def test_volume_in_world_units(self):
        conv, ir = self.volume(p101=10.0, p102=(0.5, 0.25, 1.0), p203=(1.0, 0.5, 0.0), p204=-0.4)
        _close_medium(self, ir.medium, _medium((0.5, 0.25, 1.0), 10.0 * conv.meters, (1.0, 0.5, 0.0), -0.4))
        self.close(ir.medium.absorption[2], 0.0, "a white channel neither absorbs nor scatters")
        self.close(ir.medium.scattering[2], 0.0)

    def test_emission_without_absorption(self):
        """Emission distance 10 with the absorption off: emission alone (Corona: 1.0 / 0.502 / 0.251 at h 10)."""
        conv, ir = self.volume(p201=10.0, p202=(1.0, 0.5, 0.25))
        self.close(ir.medium.scattering + ir.medium.absorption, (0.0,) * 6)
        self.close(ir.medium.emission, tuple(c / (10.0 * conv.meters) for c in (1.0, 0.5, 0.25)))

    def test_white_absorption_is_no_medium(self):
        """Absorption white: no extinction, nothing to scatter (Corona: the slab is invisible)."""
        _conv, ir = self.volume(p101=10.0, p102=(1.0, 1.0, 1.0), p203=(0.5, 0.5, 0.5))
        self.assertIsNone(ir.medium)

    def test_untrusted_numbers(self):
        """A black channel, a tiny or non-finite distance, a directionality past 1: finite coefficients at most
        MAX_MEDIUM_DENSITY, g inside (-1, 1)."""
        for params in (dict(p101=10.0, p102=(0.0, 0.0, 0.0), p204=5.0), dict(p101=1e-30, p102=(0.5, 0.5, 0.5)),
                       dict(p101=float("inf"), p102=(0.5, 0.5, 0.5), p204=float("nan")),
                       dict(p101=-3.0, p102=(0.5, 0.5, 0.5), p201=1e-30, p202=(1.0, 1.0, 1.0))):
            _conv, ir = self.volume(**params)
            m = ir.medium
            if m is None:
                continue
            values = m.scattering + m.absorption + m.emission
            self.assertTrue(all(math.isfinite(v) and 0.0 <= v <= mat.MAX_MEDIUM_DENSITY for v in values), str(params))
            self.assertTrue(math.isfinite(m.anisotropy) and -1.0 < m.anisotropy < 1.0, str(params))

    def test_volume_named(self):
        _conv, ir = self.volume(p101=10.0, p102=(0.5, 0.5, 0.5), p205=Ref(1), p207=1, p206=Ref(2), p208=1,
                                p201=5.0, p210=Ref(3), p211=1, p209=1)
        self.assertIsNotNone(ir.medium)
        self.assertEqual(ir.issues, ["CoronaVolumeMtl 'C': absorption map not converted",
                                     "CoronaVolumeMtl 'C': scattering map not converted",
                                     "CoronaVolumeMtl 'C': single bounce not converted",
                                     "CoronaVolumeMtl 'C': emission map not converted"])
        self.assertTrue(ir.medium.single, "single bounce on: the builder names no Volume Bounces (maxdrop-6n0.6.33)")
        _conv, off = self.volume(p101=10.0, p102=(0.5, 0.5, 0.5), p205=Ref(1), p207=0, p206=Ref(2), p208=0)
        self.assertEqual(off.issues, [], "maps switched off")

    def test_map_alone_is_named(self):
        """A white swatch under a map that is on: no medium from the swatch, the map named all the same (Corona
        renders the mapped absorption)."""
        _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p191=1.0, p261=(1.0, 1.0, 1.0), p281=4.0,
                                     p262=Ref(1), p263=1), _map(1))
        self.assertIsNone(ir.medium)
        self.assertEqual(ir.issues, ["CoronaPhysicalMtl 'C': absorption map not converted"])
        _conv, vol = self.volume(p201=5.0, p202=(0.0, 0.0, 0.0), p210=Ref(3), p211=1)
        self.assertIsNone(vol.medium)
        self.assertEqual(vol.issues, ["CoronaVolumeMtl 'C': emission map not converted"])
        _conv, off = self.volume(p101=0.0, p205=Ref(1), p207=1, p209=1)
        self.assertEqual(off.issues, [], "absorption distance 0: the medium is off, its maps with it")

    def test_white_channel_is_zero_not_negative(self):
        _conv, ir = self.volume(p101=10.0, p102=(0.5, 1.0, 1.0))
        self.assertEqual([math.copysign(1.0, v) for v in ir.medium.absorption], [1.0, 1.0, 1.0])

    def test_physical(self):
        conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p191=1.0, p261=(0.5, 0.5, 0.5), p281=4.0,
                                    p271=(0.25, 0.25, 0.25), p282=0.6))
        _close_medium(self, ir.medium, _medium((0.5,) * 3, 4.0 * conv.meters, (0.25,) * 3, 0.6))
        self.assertEqual(ir.issues, [])
        self.assertFalse(ir.medium.single)

    def test_physical_needs_refraction_and_solid(self):
        """No refraction: nothing enters; thin mode: Corona renders no medium (probe: 1.0 through a thin slab)."""
        for params in (dict(p191=0.0), dict(p191=1.0, p203=1), dict(p191=1.0, p281=0.0)):
            full = dict(dict(p261=(0.5, 0.5, 0.5), p281=4.0), **params)
            _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, **full))
            self.assertIsNone(ir.medium, str(params))
            self.assertEqual(ir.issues, [], str(params))

    def test_physical_named(self):
        _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p191=1.0, p261=(0.5, 0.5, 0.5), p281=4.0,
                                     p262=Ref(1), p263=1, p272=Ref(2), p273=1, p283=1), _map(1), _map(2))
        self.assertIsNotNone(ir.medium)
        self.assertEqual(ir.issues, ["CoronaPhysicalMtl 'C': absorption map not converted",
                                     "CoronaPhysicalMtl 'C': scattering map not converted",
                                     "CoronaPhysicalMtl 'C': single bounce not converted"])
        self.assertTrue(ir.medium.single)

    def test_legacy(self):
        conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, p123=1.0, p188=2.0, p190=(0.5, 0.25, 0.5),
                                    p215=(1.0, 1.0, 1.0), p216=0.2, p427=1))
        _close_medium(self, ir.medium, _medium((0.5, 0.25, 0.5), 2.0 * conv.meters, (1.0,) * 3, 0.2))
        self.assertEqual(ir.issues, [])

    def test_legacy_media_mode(self):
        """mediaMode 1 is the medium, also when the file does not store it (an older Corona); 0 renders the slab
        black in Corona 12: named, no medium."""
        base = dict(p123=1.0, p188=2.0, p190=(0.5, 0.5, 0.5))
        _conv, missing = _convert(_corona(0, classids.CORONA_LEGACY_MTL, **base))
        self.assertIsNotNone(missing.medium)
        _conv, zero = _convert(_corona(0, classids.CORONA_LEGACY_MTL, p427=0, **base))
        self.assertIsNone(zero.medium)
        self.assertEqual(zero.issues, ["CoronaLegacyMtl 'C': media mode 0 not converted (Corona 12 renders it black)"])

    def test_legacy_needs_refraction_and_solid(self):
        for params in (dict(p123=0.0), dict(p123=1.0, p210=1)):
            _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, p188=2.0, p190=(0.5, 0.5, 0.5), **params))
            self.assertIsNone(ir.medium, str(params))
            self.assertEqual(ir.issues, [], str(params))

    def test_legacy_named(self):
        _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, p123=1.0, p188=2.0, p190=(0.5, 0.5, 0.5),
                                     p305=Ref(1), p306=1, p308=Ref(2), p309=1, p315=1), _map(1), _map(2))
        self.assertIsNotNone(ir.medium)
        self.assertEqual(ir.issues, ["CoronaLegacyMtl 'C': absorption map not converted",
                                     "CoronaLegacyMtl 'C': scattering map not converted",
                                     "CoronaLegacyMtl 'C': single bounce not converted"])
        self.assertTrue(ir.medium.single)

    def test_layered(self):
        """The base's medium is the material's (one Volume socket); a layer's is named."""
        absorb = dict(p191=1.0, p261=(0.5, 0.5, 0.5), p281=4.0)
        layered = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(2)])
        _conv, ir = _convert(layered, _corona(1, classids.CORONA_PHYSICAL_MTL, **absorb),
                             _corona(2, classids.CORONA_PHYSICAL_MTL, **absorb))
        self.assertIsNotNone(ir.medium, "the base's")
        self.assertEqual(ir.issues, ["C: layer 2's medium not converted"])


class CoronaLegacyGloss(unittest.TestCase, Close):
    """CORONA_LEGACY_GLOSS: CoronaLegacyMtl glossiness with PBR mode off as the roughness of the PBR-mode glossiness
    whose highlight Corona 12 renders alike (maxdrop-em3.115)."""

    def test_measured_points(self):
        for g, r in ((0.0, 0.618), (0.4, 0.324), (0.6, 0.165), (0.9, 0.051), (1.0, 0.0)):
            self.close(mat.corona_legacy_roughness(g), r, str(g))

    def test_interpolates_and_clamps(self):
        self.close(mat.corona_legacy_roughness(0.425), (0.324 + 0.272) / 2)
        self.close(mat.corona_legacy_roughness(-1.0), 0.618)
        self.close(mat.corona_legacy_roughness(2.0), 0.0)
        self.close(mat.corona_legacy_roughness(float("nan")), mat.corona_legacy_roughness(1.0), "the default")

    def test_monotonic(self):
        rs = [mat.corona_legacy_roughness(i / 200.0) for i in range(201)]
        self.assertTrue(all(a >= b for a, b in zip(rs, rs[1:])))


class CoronaOpacityColor(unittest.TestCase, Close):
    """Corona 12 renders an opacity color per channel, as stored in both gamma modes (maxdrop-6n0.6.35:
    CoronaLegacyMtl and CoronaPhysicalMtl, grey 64 -> 0.251, red -> 1 0 0, 200 100 50 -> 0.784 0.392 0.196): a
    float alpha keeps the mean, a colored one is an issue."""
    CASES = ((classids.CORONA_LEGACY_MTL, "p105"), (classids.CORONA_PHYSICAL_MTL, "p121"),
             (classids.CORONA_SKIN_MTL, "p122"), (classids.CORONA_HAIR_MTL, "p103"))
    HIDDEN = ((classids.CORONA_LEGACY_MTL, "p105", dict(p146=Ref(1), p166=1, p295=1.0)),
              (classids.CORONA_LEGACY_MTL, "p105", dict(p127=0.0)),
              (classids.CORONA_PHYSICAL_MTL, "p121", dict(p123=Ref(1), p124=1, p125=1.0)),
              (classids.CORONA_PHYSICAL_MTL, "p121", dict(p122=0.0)))

    def test_colored_opacity_color_is_an_issue(self):
        for cid, pid in self.CASES:
            with self.subTest(cid=cid):
                conv, ir = _convert(_corona(0, cid, **{pid: (1.0, 0.0, 0.0)}))
                self.close(ir.alpha.value, 1.0 / 3.0, "the mean")
                found = [r for r in ir.issues if "opacity color" in r]
                self.assertEqual(len(found), 1, ir.issues)
                self.assertIn("per channel", found[0])
                self.assertIn(found[0], [r for _i, r in conv.stats.issues])

    def test_grey_opacity_color_is_exact(self):
        for cid, pid in self.CASES:
            for v in (64 / 255, 1.0, 0.0):
                with self.subTest(cid=cid, v=v):
                    _conv, ir = _convert(_corona(0, cid, **{pid: (v, v + 0.4 / 255 if v < 1 else v, v)}))
                    self.assertAlmostEqual(ir.alpha.value, v, delta=1e-3, msg="as stored, whatever the gamma")
                    self.assertEqual([r for r in ir.issues if "opacity color" in r], [])

    def test_hidden_opacity_color_is_no_issue(self):
        """A map at full amount over the swatch, or a level of 0: the swatch does not show, so no issue."""
        for cid, pid, params in self.HIDDEN:
            with self.subTest(cid=cid, params=sorted(params)):
                _conv, ir = _convert(_corona(0, cid, **{pid: (1.0, 0.0, 0.0)}, **params), _map(1))
                self.assertEqual([r for r in ir.issues if "opacity color" in r], [], ir.issues)


if __name__ == "__main__":
    unittest.main()
