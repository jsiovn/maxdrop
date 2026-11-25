# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/materials/ on the Corona rules with synthetic materials, no Blender.

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
    _convert, _corona, _hair_color, _map, classids, Close, FakeGraph, FakeMtl, GREY, mat, Ref,
)


class CoronaSynthetic(unittest.TestCase, Close):
    def test_physical_defaults(self):
        _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL))
        self.close(ir.base_color.value, (0.5,) * 3)
        self.close(ir.roughness.value, 0.75)
        self.close(ir.ior, 1.5)
        self.close(ir.alpha.value, 1.0)
        self.close(ir.emission_strength, 0.0)
        self.close(ir.specular.value, 1.0, "the IOR's own Fresnel")
        self.assertIsNone(ir.base_color.map)

    def test_physical_maps_and_switches(self):
        objects = [_map(i) for i in range(1, 6)]
        _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p103=Ref(1), p105=0.5, p132=Ref(2), p421=1,
                                     p192=Ref(3), p193=0, p351=Ref(4), p353=2.0, p411=Ref(5), p412=1), *objects)
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.5))
        self.assertEqual(ir.roughness.map, mat.MapRef(2, 1.0, True))
        self.assertIsNone(ir.transmission.map, "switched off")
        self.assertEqual(ir.bump, mat.MapRef(4, 2.0))
        self.assertEqual(ir.metallic.map, mat.MapRef(5))

    def test_legacy_metal_needs_both_ior_and_reflection(self):
        bright = dict(p102=(1.0, 1.0, 1.0), p122=1.0)
        for params, metal in ((dict(bright, p182=999.0), 1.0), (dict(bright, p182=9.0), 0.0),
                              (dict(p102=(0.2, 0.2, 0.2), p122=1.0, p182=999.0), 0.0)):
            _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, **params))
            self.close(ir.metallic.value, metal, str(params))

    def test_legacy_reflection_map_at_full_amount_keeps_diffuse(self):
        """A reflection map at full amount hides the swatch (maxdrop-em3.133, as VRayMtl's): no metal however high
        the Fresnel IOR and bright the swatch; the specular follows the map, the base color is the diffuse."""
        for amount in (1.0, 1.5):
            _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, p101=(1.0, 0.0, 0.0), p102=(1.0, 1.0, 1.0),
                                         p122=1.0, p182=999.0, p142=Ref(1), p291=amount), _map(1))
            self.close(ir.metallic.value, 0.0, str(amount))
            self.close(ir.base_color.value, (1.0, 0.0, 0.0), str(amount))
            self.assertIsNone(ir.base_color.map)
            self.assertEqual(ir.specular.map, mat.MapRef(1, amount, False))

    def test_legacy_swatch_shows_in_proportion_below_full_amount(self):
        """Below full amount the swatch counts by its share, mean x (1 - amount); the level is in that mean (Corona's
        documentation: the level multiplies the color and the map alike)."""
        def metal(color, level, **slot):
            return _convert(_corona(0, classids.CORONA_LEGACY_MTL, p101=(1.0, 0.0, 0.0), p102=color, p122=level,
                                    p182=999.0, p142=Ref(1), **slot), _map(1))[1]
        ir = metal((0.8,) * 3, 1.0, p291=0.75)
        self.close(ir.metallic.value, 0.0, "0.8 x 0.25 = 0.2 shown")
        self.close(ir.base_color.value, (1.0, 0.0, 0.0), "0.8 x 0.25 = 0.2 shown")
        ir = metal((1.0,) * 3, 1.0, p291=0.75)
        self.close(ir.metallic.value, 1.0, "1 x 0.25: the threshold")
        self.close(ir.base_color.value, (1.0,) * 3, "1 x 0.25: the threshold")
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.75, False))
        ir = metal((1.0,) * 3, 0.5, p291=0.5)
        self.close(ir.metallic.value, 1.0, "level 0.5 x 0.5 = 0.25 shown")
        ir = metal((1.0,) * 3, 0.5, p291=0.6)
        self.close(ir.metallic.value, 0.0, "level 0.5 x 0.4 = 0.2 shown")
        ir = metal((0.8,) * 3, 1.0, p162=0, p291=1.0)
        self.close(ir.metallic.value, 1.0, "the map switched off: the whole swatch")
        self.assertIsNone(ir.base_color.map)

    def test_legacy_levels_scale_their_maps(self):
        """The diffuse, reflection, refraction and opacity levels multiply the map in their slot as well as the color
        (Corona's documentation): the MapRef's scale, the amount kept (maxdrop-6n0.6.6)."""
        slots = (("base_color", "p121", "p141", "p290"), ("specular", "p122", "p142", "p291"),
                 ("transmission", "p123", "p144", "p293"), ("alpha", "p127", "p146", "p295"))
        for name, level_pid, map_pid, amount_pid in slots:
            for level, want in ((0.5, mat.MapRef(1, 0.75, False, 0.5)), (1.0, mat.MapRef(1, 0.75)),
                                (2.0, mat.MapRef(1, 0.75, False, 2.0))):
                _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, **{level_pid: level, map_pid: Ref(1),
                                                                                amount_pid: 0.75}), _map(1))
                self.assertEqual(getattr(ir, name).map, want, "%s level %g" % (name, level))
            _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, **{level_pid: 0.0, map_pid: Ref(1)}),
                                 _map(1))
            self.assertIsNone(getattr(ir, name).map, "%s level 0: no map" % name)
        _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, p142=Ref(1)), _map(1))
        self.assertIsNone(ir.specular.map, "levelReflect not stored: 0, no reflection")
        _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, p102=(1.0,) * 3, p122=0.5, p182=999.0,
                                     p142=Ref(1), p291=0.5), _map(1))
        self.close(ir.metallic.value, 1.0, "level 0.5 x 0.5 = 0.25 shown: the metal")
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.5, False, 0.5), "the metal's map scaled too")
        _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, p128=0.5, p158=Ref(1)), _map(1))
        self.assertEqual(ir.emission_color.map, mat.MapRef(1), "self-illumination: the strength scales the map")
        self.close(ir.emission_strength, 0.5)

    def test_legacy_defaults_reflect_nothing(self):
        _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL))
        self.close(ir.specular.value, 0.0, "levelReflect 0")
        self.close(ir.transmission.value, 0.0)
        self.close(ir.ior, 1.52)

    def test_damaged_values_take_defaults(self):
        _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p101=(float("nan"), 0, 0), p131="x",
                                     p171=float("inf")))
        self.close(ir.base_color.value, (0.5,) * 3)
        self.close(ir.roughness.value, 0.75)
        self.close(ir.ior, 1.5)

    def test_light_defaults(self):
        _conv, ir = _convert(_corona(0, classids.CORONA_LIGHT_MTL))
        self.close(ir.emission_color.value, (1.0, 1.0, 1.0))
        self.close(ir.emission_strength, 1.0)

    def test_layered_skips_layers_switched_off(self):
        layered = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(None), p1001=[Ref(1), Ref(2)], p1004=[0, 1])
        conv, ir = _convert(layered, _corona(1, classids.CORONA_LIGHT_MTL), _corona(2, classids.CORONA_LEGACY_MTL))
        self.assertEqual(conv.peel(0), (2, None))
        self.assertEqual(ir.source, "CoronaLegacyMtl")

    def test_physical_ior_mode_specular(self):
        """iorMode 1: the base and clearcoat IORs hold a specular level, F0 = 0.08 x level, never above 0.25 (IOR 3);
        other modes than 0 and 1 render as an IOR (2, measured) and stay named (maxdrop-em3.115)."""
        _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p461=1, p171=2.0, p221=1.0))
        self.close(ir.ior, mat.ior_from_reflectance(0.16))
        self.close(ir.coat_ior, mat.ior_from_reflectance(0.08))
        self.assertEqual(ir.issues, [])
        _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p461=1, p171=4.0, p221=0.0))
        self.close((ir.ior, ir.coat_ior), (3.0, 1.0), "F0 0.32 renders as 0.25; specular 0 reflects nothing")
        _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p461=1))
        self.close(ir.ior, 1.5, "no value: the IOR default")
        _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p461=2, p171=2.0))
        self.close(ir.ior, 2.0)
        self.assertIn("IOR mode 2", ir.issues[0])

    def test_physical_base_ior_outside_1_to_3(self):
        """IOR mode 0: a base IOR below 1 reflects as its reciprocal, none more than IOR 3 (Corona 12 renders,
        maxdrop-em3.115); the clearcoat IOR is left as it is (not measured); 0 or below never divides."""
        for ior, want in ((0.5, 2.0), (4.0, 3.0), (10.0, 3.0), (2.5, 2.5), (1.0, 1.0), (3.0, 3.0), (0.0, 1.0),
                          (-1.0, 1.0), (0.01, 3.0)):
            for mode in ({}, {"p461": 0}):
                _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p171=ior, p221=4.0, **mode))
                self.close(ir.ior, want, "%r %r" % (ior, mode))
                self.close(ir.coat_ior, 4.0, "the coat as it is")
                self.assertEqual(ir.issues, [], str(ior))

    def test_physical_refracting_base_ior_outside_1_to_3_is_named(self):
        """A refracting material keeps its IOR (its refraction through such an IOR was not measured), named when it
        is outside 1..3; a transmission map counts as refracting."""
        for ior, want, named in ((4.0, 4.0, True), (0.5, 1.0, True), (1.5, 1.5, False), (3.0, 3.0, False)):
            _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p171=ior, p191=0.5))
            self.close(ir.ior, want, str(ior))
            self.assertEqual(len(ir.issues), int(named), str(ir.issues))
            if named:
                self.assertIn("base IOR %g" % ior, ir.issues[0])
                self.assertIn("drawn as IOR %g" % want, ir.issues[0])
        _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p171=4.0, p192=Ref(1)), _map(1))
        self.close(ir.ior, 4.0, "a transmission map refracts")
        self.assertEqual(len(ir.issues), 1)

    def test_physical_translucency_needs_thin_mode(self):
        for thin, issues in ((0, 0), (1, 1)):
            _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p203=thin, p371=0.4))
            self.assertEqual(len(ir.issues), issues, "thin %d" % thin)

    def test_legacy_pbr_off_glossiness_map_stays_named(self):
        _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, p102=(1.0,) * 3, p122=1.0, p180=0.6, p402=0,
                                     p143=Ref(1)), _map(1))
        self.close(ir.roughness.value, 0.165, "the swatch through the table")
        self.assertEqual(ir.roughness.map, mat.MapRef(1, 1.0, True))
        self.assertIn("glossiness map of PBR mode off read as in PBR mode", ir.issues[0])

    def test_layered_cycle_and_a_layer_that_is_not_a_material(self):
        a = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(2), Ref(3)])
        b = _corona(1, classids.CORONA_PHYSICAL_MTL)
        c = _corona(2, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(0)])  # back to a
        conv, ir = _convert(a, b, c, _map(3))
        self.assertEqual([la.ir.index for la in ir.layers], [2])
        inner = ir.layers[0].ir
        self.assertEqual(len(inner.layers), 1)
        self.assertTrue(inner.layers[0].ir.unknown, "the cycle back to a: grey")
        self.assertTrue(any("material cycle" in r for _i, r in conv.stats.issues))
        self.assertTrue(any("is not a material" in r for _i, r in conv.stats.issues), "the map in layer 2")

    def test_layered_with_an_empty_wrapper_or_a_dangling_layer(self):
        layered = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(2), Ref(9)])
        empty = FakeMtl(2, classids.VRAY_2SIDED_MTL, "Empty", {0: {0: Ref(None), 1: Ref(None)}})
        conv, ir = _convert(layered, _corona(1, classids.CORONA_PHYSICAL_MTL), empty)
        self.assertEqual(ir.source, "CoronaLayeredMtl")
        self.assertTrue(all(la.ir.unknown for la in ir.layers), "the empty wrapper: grey, no exception")

    def test_layered_fan_out_is_bounded(self):
        objects = [_corona(i, classids.CORONA_LAYERED_MTL, p1000=Ref(20), p1001=[Ref(i + 1)] * 16) for i in range(9)]
        objects.append(_corona(9, classids.CORONA_PHYSICAL_MTL))
        objects.append(_corona(20, classids.CORONA_PHYSICAL_MTL))
        conv, ir = _convert(*objects)
        self.assertLessEqual(conv.bsdf_count(ir), mat.MAX_LAYER_BSDFS)
        self.assertTrue(any("Principled BSDFs not mixed" in r for _i, r in conv.stats.issues))

    def test_complex_ior_extremes(self):
        for n, k in ((-1.0, 0.0), (1e200, 1e200), (0.0, 0.0)):
            f0 = mat.f0_from_complex_ior(n, k)
            self.assertTrue(0.0 <= f0 <= 1.0, (n, k, f0))

    def test_layered_caps_its_layers(self):
        n = mat.MAX_LAYERS + 2
        layered = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(1)] * n, p1002=[0.5] * n)
        conv, ir = _convert(layered, _corona(1, classids.CORONA_PHYSICAL_MTL))
        self.assertEqual(len(ir.layers), mat.MAX_LAYERS)
        self.assertTrue(any("only the first" in r for r in ir.issues))

    def test_layered_mask_switched_off_and_amounts(self):
        layered = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(1), Ref(1)], p1002=[0.25, 2.0],
                          p1003=[Ref(2), Ref(2)], p1005=[0, 1], p1006=[1.0, 0.4])
        conv, ir = _convert(layered, _corona(1, classids.CORONA_PHYSICAL_MTL), _map(2))
        self.assertEqual([(la.amount, la.mask) for la in ir.layers],
                         [(0.25, None), (2.0, mat.MapRef(2, 0.4))])

    def test_ray_switch_and_select(self):
        rs = _corona(0, classids.CORONA_RAY_SWITCH_MTL, p1600=Ref(1), p1603=Ref(2), p1613=0)
        conv, ir = _convert(rs, _corona(1, classids.CORONA_PHYSICAL_MTL), _corona(2, classids.CORONA_LEGACY_MTL))
        self.assertEqual(conv.peel(0), (None, "C: direct material switched off: Corona renders nothing to the camera"))
        sel = _corona(0, classids.CORONA_SELECT_MTL, p312=[Ref(1), Ref(None)], p313=1)
        conv, ir = _convert(sel, _corona(1, classids.CORONA_PHYSICAL_MTL))
        self.assertTrue(ir.unknown)
        self.assertIn("selected 1 is empty", ir.issues[0])
        conv, ir = _convert(_corona(0, classids.CORONA_SELECT_MTL, p312=[Ref(1)], p313=5),
                            _corona(1, classids.CORONA_PHYSICAL_MTL))
        self.assertIn("selected 5 has no material", ir.issues[0])

    def test_complex_ior_f0(self):
        self.close(mat.f0_from_complex_ior(1.5, 0.0), 0.04)
        self.close(mat.f0_from_complex_ior(0.2, 3.9), ((0.8 ** 2) + 3.9 ** 2) / (1.2 ** 2 + 3.9 ** 2))

    def test_meters_default_and_given(self):
        conv = mat.MaterialConverter(FakeGraph(_corona(0, classids.CORONA_PHYSICAL_MTL, p291=0.5, p301=2.0)))
        self.close(conv.meters, mat.DEFAULT_METERS, "a graph without a scene")
        self.close(conv.convert(0).subsurface_radius, 2.0 * 0.0254)
        conv = mat.MaterialConverter(FakeGraph(_corona(0, classids.CORONA_PHYSICAL_MTL, p291=0.5, p301=2.0)),
                                     meters=0.01)
        self.close(conv.convert(0).subsurface_radius, 0.02)

    def test_layered_with_nothing_set_is_grey(self):
        conv, ir = _convert(_corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(None), p1001=[Ref(None)] * 3))
        self.assertTrue(ir.unknown)
        self.close(ir.base_color.value, GREY)
        self.assertTrue(any("no sub-material" in r for _i, r in conv.stats.issues))

    def test_hair_defaults(self):
        conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL))
        self.close(ir.base_color.value, _hair_color(0.5, 0.0, (1.0, 1.0, 1.0)))
        self.close(ir.roughness.value, 0.5)
        self.close(ir.ior, 1.55)
        self.assertEqual((ir.issues, dict(conv.stats.unknown)), ([], {}))

    def test_hair_color_measured(self):
        """Literal numbers, apart from _hair_color: Corona 12 renders of CoronaHairMtl on a plane in a white furnace
        (maxdrop-em3.164) read R + P0 x color per channel, R = 0.070 (the colorless floor), P0 = 0.929; the color is
        (read - R) / P0. The default (melanin 0.5) is a mid brown, not the near black of Principled Hair's
        parametrization (0.031 / 0.011 / 0.002)."""
        def measured(*read):
            return tuple(max(0.0, (r - 0.070) / 0.929) for r in read)
        cases = (((0.5, 0.0, (1.0, 1.0, 1.0)), measured(0.3960, 0.2317, 0.0993), "the default"),
                 ((0.3, 0.0, (1.0, 1.0, 1.0)), measured(0.7098, 0.5675, 0.3480), "melanin 0.3"),
                 ((0.8, 0.0, (1.0, 1.0, 1.0)), measured(0.1281, 0.0791, 0.0690), "melanin 0.8"),
                 ((0.5, 0.6, (1.0, 1.0, 1.0)), measured(0.5302, 0.3170, 0.1164), "pheomelanin 0.6 (held out)"),
                 ((0.3, 0.3, (1.0, 1.0, 1.0)), measured(0.7521, 0.6087, 0.3725), "pheomelanin 0.3 (held out)"),
                 ((0.8, 1.0, (1.0, 1.0, 1.0)), measured(0.3259, 0.1271, 0.0647), "pheomelanin 1"),
                 ((0.0, 0.0, (0.25, 0.5, 1.0)), (0.837 / 0.929, 0.905 / 0.929, 1.0), "a tint at melanin 0"),
                 ((0.0, 0.6, (1.0, 1.0, 1.0)), (1.0, 1.0, 1.0), "pheomelanin is a share of the melanin"))
        for args, want, what in cases:
            for g, w in zip(mat.hair_color(*args), want):
                self.assertAlmostEqual(g, w, delta=0.012, msg=what)

    def test_hair_tint_map_named(self):
        """A tint map renders as its swatch would (added to the melanin's absorption): the swatch tint is used and the
        map named, at any melanin."""
        for melanin in (0.0, 0.5):
            conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=melanin, p112=Ref(1)), _map(1))
            self.assertIsNone(ir.base_color.map)
            self.close(ir.base_color.value, _hair_color(melanin, 0.0, (1.0, 1.0, 1.0)))
            self.assertEqual(ir.issues, ["CoronaHairMtl 'C': tint map not converted"])

    def test_hair_randomize_melanin_named(self):
        _conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, p143=0.5))
        self.close(ir.base_color.value, _hair_color(0.5, 0.0, (1.0, 1.0, 1.0)))
        self.assertEqual(ir.issues, ["CoronaHairMtl 'C': randomize melanin not converted"])

    def test_layered_over_a_shadow_catcher_is_no_shadow_catcher(self):
        layered = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(2)], p1004=[1])
        conv, ir = _convert(layered, _corona(1, classids.CORONA_SHADOW_CATCHER_MTL),
                            _corona(2, classids.CORONA_PHYSICAL_MTL))
        self.assertEqual(len(ir.layers), 1)
        self.assertFalse(ir.shadow_catcher)
        self.assertTrue(conv.convert(1).shadow_catcher, "the catcher itself still is one")

    def test_hair_melanin_bounds(self):
        _conv, black = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=1.0, p142=0.5))
        self.close(black.base_color.value, _hair_color(1.0, 0.5, (1.0, 1.0, 1.0)), "melanin 1: finite")
        _conv, past = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=3.0, p142=-1.0))
        self.close(past.base_color.value, _hair_color(1.0, 0.0, (1.0, 1.0, 1.0)),
                   "melanin and pheomelanin clamped to 0..1")
        _conv, white = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=0.0))
        self.close(white.base_color.value, _hair_color(0.0, 0.0, (1.0, 1.0, 1.0)), "no pigment, a white tint")
        self.assertTrue(all(c > 0.998 for c in white.base_color.value), "Corona: 0.995, the furnace 1")
        _conv, inked = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=0.0, p101=(0.0, 0.0, 0.0)))
        self.close(inked.base_color.value, _hair_color(0.0, 0.0, (0.0, 0.0, 0.0)), "a black tint floored at 1e-4")
        self.assertTrue(all(0.02 < c < 0.05 for c in inked.base_color.value), "Corona: only the colorless floor")

    def test_hair_base_renders_as_corona(self):
        """The base color a Principled BSDF (Cycles 5.2, IOR 1.55, roughness 0.5) needs to read what Corona 12 reads
        in a white furnace: the Principled reads 0.043 + 0.957 x its base, so the base is (read - 0.043) / 0.957
        (the default read 0.396 / 0.232 / 0.099, melanin 1 0.081 / 0.070 / 0.070)."""
        for params, read in (({}, (0.3960, 0.2317, 0.0993)), ({"p141": 1.0}, (0.0813, 0.0704, 0.0700)),
                             ({"p141": 0.3}, (0.7098, 0.5675, 0.3480))):
            _conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, **params))
            for g, r in zip(ir.base_color.value, read):
                self.assertAlmostEqual(g, (r - 0.043) / 0.957, delta=0.012, msg=params)

    def test_hair_diffuse_mixed(self):
        """Corona 12 renders: a grey diffuse d gives d + (1 - d) x the hair, exactly (0.5 at melanin 0.5 read 0.699 /
        0.617 / 0.551; 0.5 at level 0.5 read 0.551 / 0.427 / 0.328); a colored one weighs the hair by about 1 - its
        largest channel."""
        def measured(*read):
            return tuple((r - 0.043) / 0.957 for r in read)
        for params, read in (({"p102": (0.5, 0.5, 0.5)}, (0.6988, 0.6171, 0.5513)),
                             ({"p102": (0.5, 0.5, 0.5), "p105": 0.5}, (0.5505, 0.4272, 0.3277))):
            _conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, **params))
            for g, w in zip(ir.base_color.value, measured(*read)):
                self.assertAlmostEqual(g, w, delta=0.012, msg=params)
        _conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=0.0, p102=(1.0, 0.5, 0.0), p105=0.5))
        self.close(ir.base_color.value, _hair_color(0.0, 0.0, (1.0, 1.0, 1.0), (0.5, 0.25, 0.0)),
                   "white hair under half the weight")
        for g, w in zip(ir.base_color.value, (1.0, 0.75, 0.5)):
            self.assertAlmostEqual(g, w, delta=1e-3)
        _conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, p102=(1.0, 0.5, 0.0), p105=0.5))
        self.close(ir.base_color.value, _hair_color(0.5, 0.0, (1.0, 1.0, 1.0), (0.5, 0.25, 0.0)))
        _conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, p102=(0.8, 128 / 255, 0.2)))
        for g, w in zip(ir.base_color.value, measured(0.9264, 0.5760, 0.2317)):
            self.assertAlmostEqual(g, w, delta=0.06, msg="a colored diffuse: approximately")

    def test_hair_transmission(self):
        """Corona 12 renders: the transmission color multiplies the pigment part (0.5 grey at melanin 0.5 read 0.237 /
        0.152 / 0.085 against 0.396 / 0.232 / 0.099)."""
        _conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, p152=(0.5, 0.5, 0.5)))
        self.close(ir.base_color.value, _hair_color(0.5, 0.0, (1.0, 1.0, 1.0), transmission=(0.5, 0.5, 0.5)))
        for g, read in zip(ir.base_color.value, (0.2372, 0.1521, 0.0848)):
            self.assertAlmostEqual(g, (read - 0.043) / 0.957, delta=0.012)
        _conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=0.0, p152=(1.0, 0.5, 0.25)))
        self.close(ir.base_color.value, _hair_color(0.0, 0.0, (1.0, 1.0, 1.0), transmission=(1.0, 0.5, 0.25)))
        for g, read in zip(ir.base_color.value, (0.9956, 0.5676, 0.3497)):
            self.assertAlmostEqual(g, (read - 0.043) / 0.957, delta=0.06, msg="at melanin 0: approximately")
        self.assertEqual(ir.issues, [])

    def test_hair_maps(self):
        maps = [_map(i) for i in range(1, 6)]
        hair = _corona(0, classids.CORONA_HAIR_MTL, p114=Ref(1), p132=0.4, p116=Ref(2), p120=Ref(3), p138=0.5,
                       p155=Ref(4), p163=Ref(5), p164=0)
        conv, ir = _convert(hair, *maps)
        self.assertEqual(ir.alpha.map, mat.MapRef(1, 0.4))
        self.assertEqual(ir.roughness.map, mat.MapRef(2, 1.0, True))
        self.assertEqual(ir.bump, mat.MapRef(3, 0.5))
        self.assertEqual(ir.issues, ["CoronaHairMtl 'C': transmission map not converted"], "the glint map is off")

    def test_scanned_slicer_named(self):
        """CoronaVolumeMtl has a rule since maxdrop-em3.163 (CoronaMedia)."""
        for key, what in ((classids.CORONA_SCANNED_MTL, "scanned"), (classids.CORONA_SLICER_MTL, "slicing")):
            conv, ir = _convert(_corona(0, key))
            self.assertTrue(ir.unknown)
            self.close(ir.base_color.value, GREY)
            self.assertEqual(len(ir.issues), 1)
            self.assertIn(what, ir.issues[0])
            self.assertEqual(dict(conv.stats.unknown), {})

    def test_shadow_catcher_defaults(self):
        conv, ir = _convert(_corona(0, classids.CORONA_SHADOW_CATCHER_MTL))
        self.assertTrue(ir.shadow_catcher)
        self.assertEqual((ir.issues, dict(conv.stats.unknown)), ([], {}))
        _conv, off = _convert(_corona(0, classids.CORONA_SHADOW_CATCHER_MTL, p302=Ref(1), p360=0),
                              _map(1))
        self.assertEqual(off.issues, [], "a backplate map switched off")

    def test_shadow_catcher_users(self):
        catcher, other = mat.MaterialIR(0, "a", shadow_catcher=True), mat.MaterialIR(1, "b")
        plan = mat.MeshSlots([10, 11, 12], [[catcher, catcher, catcher], [catcher, other, None]], None)
        self.assertEqual(mat.shadow_catcher_users(plan), [10], "every slot of the user a catcher")
        self.assertEqual(mat.shadow_catcher_users(mat.MeshSlots([10], [], None)), [], "no slot, no catcher")


if __name__ == "__main__":
    unittest.main()
