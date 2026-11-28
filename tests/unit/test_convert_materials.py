# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/materials/, the material rules: no Blender. vray_basic's IR against values computed by
hand from its authoring script (tools/fixtures/vray_basic.ms), vray_maps' map slots, vray_wrappers' peels, vray_more's
VRayLightMtl, VRayFastSSS2, car paints and other wrappers, and each rule on synthetic parameters. standard_physical's
Standard and Physical Material, box_poly_standard's Standard, standard_shaders' Standard shaders and Physical map slots
against values computed by hand from their scripts (and the ids by the names the oracle gives them); vray_wrappers'
Multi/Sub-Object by material ID and the slot plan of its box. standard_maps' Standard map slots per shader by the
names of the maps its script puts in each channel.

    python -I -m unittest discover tests
"""
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
    _build_constant, _convert, _map, _vray, _wrapper, classids, Close, colors, FakeGraph, FakeMtl, GREY,
    mat, pblock, Ref, texmaps,
)


class _NamedScene:
    """The class directory of a _NamedGraph: {object index: class name}."""

    def __init__(self, names):
        self.names = names

    def entry(self, i):
        return types.SimpleNamespace(name=self.names[i]) if i in self.names else None


class _NamedGraph(FakeGraph):
    """A FakeGraph whose scene names each object's class as the class directory does."""

    def __init__(self, names, *objects):
        super().__init__(*objects)
        self.scene = _NamedScene(names)


class Helpers(unittest.TestCase, Close):
    def test_swatch_rule(self):
        """A synthetic graph has no scene: its swatches are linear (UNKNOWN); a given rule wins, and the converter
        takes its texmaps converter's rule."""
        self.assertIs(mat.MaterialConverter(FakeGraph()).swatches, colors.UNKNOWN)
        diffuse = {1: {1: (128 / 255,) * 3}}
        for rule, want in ((colors.GAMMA_ON, 0.501961), (colors.GAMMA_OFF, 0.215861), (colors.UNKNOWN, 0.501961)):
            with self.subTest(rule):
                conv = mat.MaterialConverter(FakeGraph(_vray(0, **{"b%d" % k: v for k, v in diffuse.items()})),
                                             swatches=rule)
                self.close(conv.convert(0).base_color.value, (want,) * 3)
        tex = texmaps.TexmapConverter(FakeGraph(), swatches=colors.GAMMA_OFF)
        self.assertIs(mat.MaterialConverter(FakeGraph(), texmaps=tex).swatches, colors.GAMMA_OFF)

    def test_rules_use_the_swatch_rule(self):
        """Every rule's swatches go through it: a gamma-off scene decodes each one with the sRGB curve."""
        light = FakeMtl(0, classids.VRAY_LIGHT_MTL, "Glow", {0: {0: (1.0, 0.5, 0.0)}})
        conv = mat.MaterialConverter(FakeGraph(light), swatches=colors.GAMMA_OFF)
        self.close(conv.convert(0).emission_color.value, (1.0, 0.214041, 0.0))
        std = FakeMtl(0, classids.STANDARD_MTL, "Std")  # no shader: the default diffuse 150
        conv = mat.MaterialConverter(FakeGraph(std), swatches=colors.GAMMA_OFF)
        self.close(conv.convert(0).base_color.value, (0.304987,) * 3)
        conv = mat.MaterialConverter(FakeGraph(std), swatches=colors.GAMMA_ON)
        self.close(conv.convert(0).base_color.value, (150 / 255,) * 3)

    def test_ior_from_reflectance(self):
        self.close(mat.ior_from_reflectance(0.04), 1.5)
        self.close(mat.ior_from_reflectance(0.0), 1.0)
        self.assertTrue(math.isfinite(mat.ior_from_reflectance(1.0)))
        self.close(mat.ior_from_reflectance(mat.CORONA_MAX_F0), mat.CORONA_MAX_IOR, "the cap's IOR and F0 agree")

    def test_class_name(self):
        self.assertEqual(mat.class_name(classids.SC_MATERIAL, classids.VRAY_MTL), "VRayMtl")
        self.assertEqual(mat.class_name(classids.SC_MATERIAL, classids.VRAY_LIGHT_MTL), "VRayLightMtl")
        self.assertEqual(mat.class_name(classids.SC_MATERIAL, (1, 2)), "ClassID(0x00000001, 0x00000002)")

    def test_class_name_of_the_class_directory(self):
        """A class without a classids entry is named by the file's class directory, cut and cleaned (the name comes
        from the file); a known class keeps its own name; ClassID only without a usable directory name."""
        sc, odd = classids.SC_MATERIAL, "ClassID(0x00000001, 0x00000002)"
        self.assertEqual(mat.class_name(sc, (0x250, 0), "Blend"), "Blend")
        self.assertEqual(mat.class_name(sc, classids.VRAY_MTL, "Something else"), "VRayMtl")
        self.assertEqual(mat.class_name(sc, (1, 2), ""), odd)
        self.assertEqual(mat.class_name(sc, (1, 2), "\r\n\x00 "), odd)
        self.assertEqual(mat.class_name(sc, (1, 2), " Foo\r\nBar\x00‮ "), "Foo Bar")
        long = mat.class_name(sc, (1, 2), "x" * 500)
        self.assertEqual((len(long), long), (mat.MAX_CLASS_NAME, "x" * (mat.MAX_CLASS_NAME - 3) + "..."))
        self.assertEqual(mat.class_label("y" * mat.MAX_CLASS_NAME), "y" * mat.MAX_CLASS_NAME, "at the limit: kept")

    def test_not_a_material(self):
        conv, ir = _convert(_map(0))
        self.assertIsNone(ir)
        self.assertIsNone(mat.MaterialConverter(FakeGraph()).convert(5))
        self.assertIsNone(mat.MaterialConverter(FakeGraph()).convert(None))  # a node without a material


class VRayMtlRules(unittest.TestCase, Close):
    def test_defaults(self):
        conv, ir = _convert(_vray(0))
        self.close(ir.base_color.value, (0.5,) * 3)  # diffuse 0.5, linear (a synthetic graph: no gamma, so on)
        self.close(ir.roughness.value, 0.0)  # glossiness 1, useRoughness off
        self.close(ir.metallic.value, 0.0)
        self.close(ir.transmission.value, 0.0)
        self.close(ir.ior, 1.6)
        self.assertEqual(ir.emission_strength, 0.0)
        self.assertIsNone(ir.base_color.map)
        self.assertFalse(ir.unknown)
        self.assertEqual(ir.source, "VRayMtl")

    def test_reflection_color_is_the_specular_weight(self):
        """A white reflection is 1, the full Fresnel reflection at the IOR, which build/materials/ halves into
        Blender's Specular IOR Level 0.5 (the IOR unchanged): V-Ray 5.2 and Cycles both reflect 0.053 facing the
        camera at IOR 1.6 (maxdrop-em3.34). A grey reflection is its linear mean."""
        for refl, want in (((1.0, 1.0, 1.0), 1.0), ((0.502, 0.502, 0.502), 0.502), ((0.2, 0.4, 0.9), 0.5),
                           ((0.0, 0.0, 0.0), 0.0)):
            conv, ir = _convert(_vray(0, b1={2: refl}))
            self.close(ir.specular.value, want, str(refl))
            self.close(ir.metallic.value, 0.0)  # Fresnel on: never the metal rule
        self.assertEqual(_build_constant("SPECULAR_LEVEL"), 0.5)

    def test_glossiness_flip_and_inverted_map(self):
        objs = (_map(1),)
        conv, ir = _convert(_vray(0, b1={3: 0.8}, b4={104: Ref(1), 204: 69.0}), *objs)
        self.close(ir.roughness.value, 0.2)
        self.assertEqual(ir.roughness.map, mat.MapRef(1, 0.69, True))
        conv, ir = _convert(_vray(0, b1={3: 0.3}, b2={89: 1}, b4={104: Ref(1), 154: 1}), *objs)
        self.close(ir.roughness.value, 0.3)
        self.assertEqual(ir.roughness.map, mat.MapRef(1, 1.0, False))

    def test_diffuse_roughness_map_is_not_reflection_roughness(self):
        conv, ir = _convert(_vray(0, b4={113: Ref(1), 163: 1}), _map(1))
        self.assertIsNone(ir.roughness.map)

    def test_map_switched_off_or_not_a_map(self):
        conv, ir = _convert(_vray(0, b4={100: Ref(1), 150: 0}), _map(1))
        self.assertIsNone(ir.base_color.map)
        conv, ir = _convert(_vray(0, b4={100: Ref(1)}), _vray(1))
        self.assertIsNone(ir.base_color.map)
        self.assertEqual(len(ir.issues), 1)
        self.assertEqual(conv.stats.issues, [(0, ir.issues[0])])

    def test_glass_base_color_from_refraction(self):
        conv, ir = _convert(_vray(0, b1={1: (1.0, 0.0, 0.0), 5: (1.0, 1.0, 1.0), 9: 1.45}))
        self.close(ir.base_color.value, (1.0, 1.0, 1.0))
        self.close(ir.transmission.value, 1.0)
        self.close(ir.ior, 1.45)
        conv, ir = _convert(_vray(0, b1={1: (1.0, 0.0, 0.0), 5: (0.5, 0.5, 0.5)}))
        t = 0.5
        self.close(ir.transmission.value, t)
        self.close(ir.base_color.value, (1.0 - t + t * t, t * t, t * t))

    def test_fresnel_off_bright_reflection_is_metal(self):
        b1 = {1: (1.0, 0.0, 0.0), 2: (0.8, 0.8, 0.8), 8: 0, 91: 0.2}
        conv, ir = _convert(_vray(0, b1=b1, b4={101: Ref(1), 201: 50.0}), _map(1))
        self.close(ir.metallic.value, 1.0)
        self.close(ir.base_color.value, (0.8,) * 3)
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.5, False))
        self.assertEqual(ir.specular.map, mat.MapRef(1, 0.5, False))

    def test_fresnel_off_grey_reflection_keeps_diffuse(self):
        """A grey swatch below 1 without a reflection map is the mirror drawing, not a metal: V-Ray 5.2 renders R +
        (1 - R) x the diffuse (maxdrop-em3.153, 128 grey over 200 40 40: 0.8925 0.5801 0.5801 facing the camera);
        the weight is the brightest channel, the mirror white for grey (maxdrop-6n0.6.16: no cliff near grey)."""
        for swatch in ((0.5, 0.5, 0.5), (0.99, 0.99, 0.99), (0.25, 0.25, 0.25), (0.509, 0.5, 0.491)):
            b1 = {1: (1.0, 0.0, 0.0), 2: swatch, 8: 0, 91: 0.2}
            conv, ir = _convert(_vray(0, b1=b1))
            self.assertFalse(ir.fresnel, str(swatch))
            self.close(ir.metallic.value, 0.0, str(swatch))
            self.close(ir.base_color.value, (0.8, 0.0, 0.0), str(swatch))
            self.close(ir.specular.value, max(swatch), str(swatch))
            self.close(ir.mirror_color, tuple(c / max(swatch) for c in swatch), str(swatch))
            self.assertIsNone(ir.specular.map)
        conv, ir = _convert(_vray(0, b1={2: (0.5, 0.5, 0.5), 5: (1.0, 1.0, 1.0), 8: 0}))  # glass stays glass
        self.close(ir.metallic.value, 0.0)
        self.close(ir.transmission.value, 1.0)
        self.close(ir.base_color.value, (1.0, 1.0, 1.0))

    def test_fresnel_off_full_reflection_is_metal(self):
        """A reflection whose brightest channel is 1 or more keeps the metal in the reflection color: what the
        tinted mirror gives at weight 1 (build draws no mirror there)."""
        for swatch in ((1.0, 1.0, 1.0), (1.0, 0.6, 0.2), (1.0, 0.3, 0.3)):
            b1 = {1: (1.0, 0.0, 0.0), 2: swatch, 8: 0, 91: 0.2}
            conv, ir = _convert(_vray(0, b1=b1))
            self.close(ir.metallic.value, 1.0, str(swatch))
            self.close(ir.base_color.value, swatch, str(swatch))
            self.close(ir.mirror_color, (1.0, 1.0, 1.0), str(swatch))
        b1 = {1: (1.0, 0.0, 0.0), 2: (0.2, 0.1, 0.05), 8: 0, 91: 0.2}  # colored, below METAL_REFLECTION
        conv, ir = _convert(_vray(0, b1=b1))
        self.close(ir.metallic.value, 0.0)
        self.close(ir.base_color.value, (0.8, 0.0, 0.0))
        self.close(ir.specular.value, 0.35 / 3.0, "the mean: a dim one stays the white mirror")
        self.close(ir.mirror_color, (1.0, 1.0, 1.0))

    def test_fresnel_off_colored_reflection_is_a_tinted_mirror(self):
        """A colored swatch from METAL_REFLECTION up, below 1, without a reflection map: the mirror by its brightest
        channel, its copy tinted R / max(R): R_c + (1 - max R) d_c per channel, between the metal and V-Ray's R_c +
        (1 - R_c) d_c (maxdrop-6n0.6.16; em3.153's probe: 230 128 26 over 40 80 200 renders 0.9175 0.6582 0.8060,
        the copy 0.917 0.533 0.179, the metal 0.900 0.503 0.102)."""
        for swatch in ((0.55, 0.5, 0.45), (0.9, 0.5, 0.1), (0.3, 0.2, 0.25), (0.902, 0.502, 0.102)):
            b1 = {1: (1.0, 0.0, 0.0), 2: swatch, 8: 0, 91: 0.2}
            conv, ir = _convert(_vray(0, b1=b1))
            self.assertFalse(ir.fresnel, str(swatch))
            self.close(ir.metallic.value, 0.0, str(swatch))
            self.close(ir.base_color.value, (0.8, 0.0, 0.0), str(swatch))
            self.close(ir.specular.value, max(swatch), str(swatch))
            self.assertIsNone(ir.specular.map)
            self.close(ir.mirror_color, tuple(c / max(swatch) for c in swatch), str(swatch))
        b1 = {1: (1.0, 0.0, 0.0), 2: (0.9, 0.5, 0.1), 8: 0, 91: 1.0}
        conv, ir = _convert(_vray(0, b1=b1))
        self.close((ir.metallic.value, ir.specular.value), (0.0, 0.9), "metalness 1: the tinted mirror alone")
        self.close(ir.base_color.value, (0.0, 0.0, 0.0), "no diffuse (maxdrop-6n0.6.39: V-Ray renders R)")
        self.assertEqual(mat.MaterialIR(0, "x").mirror_color, (1.0, 1.0, 1.0), "every other rule: white")

    def test_fresnel_off_reflection_map_at_zero_amount_is_the_swatch(self):
        """A reflection map at 0 % amount shows nothing of itself: the swatch alone, as with the map switched off
        (V-Ray renders both alike): no MapRef left, so build never takes the twin for an unconverted map."""
        for swatch, metal in (((0.8, 0.8, 0.8), 0.0), ((0.9, 0.5, 0.1), 0.0), ((1.0, 1.0, 1.0), 1.0)):
            b1 = {1: (1.0, 0.0, 0.0), 2: swatch, 8: 0, 91: 0.2}
            conv, ir = _convert(_vray(0, b1=b1, b4={101: Ref(1), 201: 0.0}), _map(1))
            self.assertIsNone(ir.specular.map, str(swatch))
            self.assertIsNone(ir.base_color.map, str(swatch))
            self.close(ir.metallic.value, metal, str(swatch))
            self.close(ir.specular.value, max(swatch) if metal < 1 else 1.0, str(swatch))

    def test_fresnel_off_reflection_map_at_full_amount_keeps_diffuse(self):
        """A reflection map at full amount hides the swatch in V-Ray: no metal however bright the swatch; the
        specular follows the map, the base color is the diffuse."""
        b1 = {1: (1.0, 0.0, 0.0), 2: (1.0, 1.0, 1.0), 8: 0, 91: 0.2}
        for amount in (100.0, 150.0):
            conv, ir = _convert(_vray(0, b1=b1, b4={101: Ref(1), 201: amount}), _map(1))
            self.close(ir.metallic.value, 0.0, str(amount))
            self.close(ir.base_color.value, (0.8, 0.0, 0.0), str(amount))
            self.assertIsNone(ir.base_color.map)
            self.assertEqual(ir.specular.map, mat.MapRef(1, amount / 100.0, False))

    def test_fresnel_off_swatch_shows_in_proportion_below_full_amount(self):
        b1 = {1: (1.0, 0.0, 0.0), 2: (0.8, 0.8, 0.8), 8: 0, 91: 0.2}
        conv, ir = _convert(_vray(0, b1=b1, b4={101: Ref(1), 201: 75.0}), _map(1))  # 0.8 x 0.25 = 0.2 shown
        self.close(ir.metallic.value, 0.0)
        self.close(ir.base_color.value, (0.8, 0.0, 0.0))
        conv, ir = _convert(_vray(0, b1=b1, b4={101: Ref(1), 151: 0, 201: 100.0}), _map(1))  # map switched off
        self.close(ir.metallic.value, 0.0, "a grey swatch alone: the mirror drawing")
        self.close(ir.base_color.value, (0.8, 0.0, 0.0))
        tinted = {**b1, 2: (0.85, 0.8, 0.75)}
        conv, ir = _convert(_vray(0, b1=tinted, b4={101: Ref(1), 151: 0, 201: 100.0}), _map(1))
        self.close(ir.metallic.value, 0.0, "a tinted swatch alone: the tinted mirror")
        self.close(ir.mirror_color, (1.0, 0.8 / 0.85, 0.75 / 0.85))
        self.assertIsNone(ir.base_color.map)
        white = {**b1, 2: (1.0, 1.0, 1.0)}
        conv, ir = _convert(_vray(0, b1=white, b4={101: Ref(1), 201: 75.0}), _map(1))  # 1 x 0.25: the threshold
        self.close(ir.metallic.value, 1.0)

    def test_fresnel_flag(self):
        """reflection_fresnel reaches the IR: off, the weight is a mirror's at every angle (build/materials/ draws
        a white metal mixed by it, maxdrop-em3.120); a dim swatch keeps its mean as the weight, no metal."""
        conv, ir = _convert(_vray(0, b1={1: (1.0, 0.0, 0.0), 2: (0.2, 0.2, 0.2), 8: 0}))
        self.assertFalse(ir.fresnel)
        self.close(ir.specular.value, 0.2)
        self.close(ir.metallic.value, 0.0)
        self.close(ir.base_color.value, (1.0, 0.0, 0.0))
        conv, ir = _convert(_vray(0, b1={2: (0.2, 0.2, 0.2), 8: 1}))
        self.assertTrue(ir.fresnel)
        conv, ir = _convert(_vray(0, b1={2: (0.9, 0.8, 0.7), 8: 0}))  # bright, colored: the tinted mirror
        self.assertFalse(ir.fresnel)
        self.close((ir.metallic.value, ir.specular.value), (0.0, 0.9))
        conv, ir = _convert(_vray(0, b1={2: (1.0, 0.8, 0.7), 8: 0}))  # full: the metal rule, Metallic 1 wins in build
        self.close(ir.metallic.value, 1.0)
        self.assertTrue(mat.MaterialIR(0, "x").fresnel, "every other rule: the IOR's Fresnel")

    def test_fresnel_on_or_dark_reflection_keeps_diffuse(self):
        for b1, metal, red in (({1: (1.0, 0.0, 0.0), 2: (0.8, 0.8, 0.8), 8: 1, 91: 0.2}, 0.2, 1.0),
                               ({1: (1.0, 0.0, 0.0), 2: (0.2, 0.2, 0.2), 8: 0, 91: 0.2}, 0.0, 0.8)):  # dim, off
            conv, ir = _convert(_vray(0, b1=b1))
            self.close(ir.metallic.value, metal)
            self.close(ir.base_color.value, (red, 0.0, 0.0))

    def test_fresnel_off_metalness_scales_the_diffuse(self):
        """Fresnel off outside the metal rule: V-Ray 5.2 renders R_c + (1 - m)(1 - R_c) d_c for a metalness m
        (maxdrop-6n0.6.39, white environment: 128 grey over 40 80 200 at m 1 0.502, at 0.5 0.541 0.580 0.697; 40
        grey at m 1 0.157, black at m 1 0): Metallic 0 and the diffuse times 1 - m (its map by MapRef.scale, dropped
        at m 1), the mirror drawing as at m 0; k through the swatch rule."""
        for metal, k in ((1.0, 0.0), (0.5, 0.5), (0.2, 0.8)):
            for refl in ((0.502,) * 3, (0.902, 0.502, 0.102), (0.157,) * 3, (0.0,) * 3):
                with self.subTest(metal=metal, refl=refl):
                    b1 = {1: (0.157, 0.314, 0.784), 2: refl, 8: 0, 91: metal}
                    conv, ir = _convert(_vray(0, b1=b1, b4={100: Ref(1), 200: 60.0}), _map(1))
                    self.close(ir.metallic.value, 0.0)
                    self.close(ir.base_color.value, tuple(k * c for c in (0.157, 0.314, 0.784)))
                    top, shown = max(refl), sum(refl) / 3.0
                    bright = shown >= mat.METAL_REFLECTION
                    self.close(ir.specular.value, top if bright else shown)
                    self.close(ir.mirror_color, tuple(c / top for c in refl) if bright else (1.0, 1.0, 1.0),
                               "the mirror as at m 0")
                    if k == 0.0:
                        self.assertIsNone(ir.base_color.map, "nothing of the diffuse shows")
                    else:
                        self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.6, False, k))
        for sw in (colors.GAMMA_ON, colors.GAMMA_OFF):
            with self.subTest(linear=sw.linear):
                b1 = {1: (0.5, 0.5, 0.5), 2: (0.502,) * 3, 8: 0, 91: 0.5}
                conv = mat.MaterialConverter(FakeGraph(_vray(0, b1=b1, b4={100: Ref(1)}), _map(1)), swatches=sw)
                ir = conv.convert(0)
                self.close(ir.base_color.value, sw.color((0.25, 0.25, 0.25)), "scaled before the swatch rule")
                self.close(ir.base_color.map.scale, sw.channel(0.5), "the map by the rule's factor")

    def test_fresnel_off_metalness_left_as_is(self):
        """Not measured, so as before: the metal rule (Metallic 1 in the reflection color), a metalness map, a
        refracting material, and Fresnel on."""
        b1 = {1: (1.0, 0.0, 0.0), 2: (1.0, 1.0, 1.0), 8: 0, 91: 0.5}
        conv, ir = _convert(_vray(0, b1=b1))
        self.close((ir.metallic.value, *ir.base_color.value), (1.0, 1.0, 1.0, 1.0))
        b1 = {1: (1.0, 0.0, 0.0), 2: (0.502,) * 3, 8: 0, 91: 0.5}
        conv, ir = _convert(_vray(0, b1=b1, b4={119: Ref(1)}), _map(1))
        self.close(ir.metallic.value, 0.5)
        self.assertEqual(ir.metallic.map, mat.MapRef(1))
        self.close(ir.base_color.value, (1.0, 0.0, 0.0))
        conv, ir = _convert(_vray(0, b1={**b1, 5: (0.5, 0.5, 0.5)}))
        self.close(ir.metallic.value, 0.5)
        self.close(ir.transmission.value, 0.5)
        conv, ir = _convert(_vray(0, b1=b1, b4={102: Ref(1)}), _map(1))  # refracting by its map alone
        self.close((ir.metallic.value, *ir.base_color.value), (0.5, 1.0, 0.0, 0.0))
        self.assertEqual(ir.transmission.map, mat.MapRef(1))
        conv, ir = _convert(_vray(0, b1={**b1, 8: 1}))
        self.close((ir.metallic.value, *ir.base_color.value), (0.5, 1.0, 0.0, 0.0))

    def test_ior_without_refraction(self):
        conv, ir = _convert(_vray(0, b1={9: 1.4, 63: 2.2, 65: 0}))
        self.close(ir.ior, 2.2)
        conv, ir = _convert(_vray(0, b1={9: 1.4, 63: 2.2, 65: 1}))
        self.close(ir.ior, 1.4)

    def test_emission(self):
        conv, ir = _convert(_vray(0, b1={83: 3.0}))
        self.assertEqual(ir.emission_strength, 0.0)  # black, no map
        conv, ir = _convert(_vray(0, b1={83: 3.0}, b4={117: Ref(1), 217: 40.0}), _map(1))
        self.close(ir.emission_strength, 3.0)
        self.assertEqual(ir.emission_color.map, mat.MapRef(1, 0.4, False))

    def test_bump_slot(self):
        conv, ir = _convert(_vray(0, b4={103: Ref(1), 203: 30.0}), _map(1))
        self.assertEqual(ir.bump, mat.MapRef(1, 0.3, False))
        self.assertIsNone(ir.normal)
        conv, ir = _convert(_vray(0, b4={103: Ref(1)}), _map(1, classids.VRAY_NORMAL_MAP))
        self.assertEqual(ir.normal, mat.MapRef(1, 1.0, False))
        self.assertIsNone(ir.bump)

    def test_damaged_values_take_defaults(self):
        nan = float("nan")
        conv, ir = _convert(_vray(0, b1={1: (nan, 0.0, 0.0), 3: nan, 9: float("inf"), 83: nan},
                                  b4={200: nan, 100: Ref(1)}), _map(1))
        self.close(ir.base_color.value, (0.5,) * 3)
        self.close(ir.roughness.value, 0.0)
        self.close(ir.ior, 1.6)
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 1.0, False))

    def test_ior_is_clamped(self):
        conv, ir = _convert(_vray(0, b1={5: (1.0, 1.0, 1.0), 9: 0.0, 99: 1e30}))
        self.close(ir.ior, 1.0)
        self.close(ir.coat_ior, 100.0)

    def test_animated_parameter_takes_default(self):
        conv, ir = _convert(_vray(0, b1={3: pblock.Animated(4), 1: pblock.Animated(5)}))
        self.close(ir.roughness.value, 0.0)
        self.close(ir.base_color.value, (0.5,) * 3)


class OtherRules(unittest.TestCase, Close):
    def test_vray_light_mtl(self):
        light = FakeMtl(0, classids.VRAY_LIGHT_MTL, "Glow",
                        {0: {0: (1.0, 0.5, 0.0), 1: 7.5, 2: Ref(1), 3: 1, 5: Ref(2), 6: 0}})
        conv, ir = _convert(light, _map(1), _map(2))
        self.close(ir.base_color.value, (0.0, 0.0, 0.0))
        self.close(ir.roughness.value, 1.0)
        self.close(ir.specular.value, 0.0)
        self.close(ir.emission_color.value, (1.0, 0.5, 0.0))
        self.close(ir.emission_strength, 7.5)
        self.assertEqual(ir.emission_color.map, mat.MapRef(1, 1.0, False))
        self.assertIsNone(ir.alpha.map)  # opacity map switched off
        self.assertEqual((ir.name, ir.source), ("Glow", "VRayLightMtl"))

    def test_vray_fast_sss2(self):
        sss = FakeMtl(0, classids.VRAY_FAST_SSS2, "Skin", {0: {
            26: (0.5, 0.5, 0.5), 27: Ref(1), 28: 1, 36: 0.25, 2: (1.0, 0.5, 0.5), 0: 4.0, 22: 2.0, 31: 1.4,
            40: (1.0, 1.0, 1.0), 51: 0.7, 3: Ref(2), 4: 1, 85: Ref(3), 86: 1}})
        conv, ir = _convert(sss, _map(1), _map(2), _map(3))
        self.close(ir.base_color.value, (0.5,) * 3)
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 1.0, False))
        self.close(ir.roughness.value, 0.3)
        self.close(ir.specular.value, 1.0)
        self.close(ir.ior, 1.4)
        self.close(ir.subsurface_weight, 0.75)
        self.close(ir.subsurface_color, (1.0, 0.5, 0.5))
        self.close(ir.subsurface_radius, 0.08)  # 4 cm x scale 2, in meters
        self.assertEqual(ir.bump, mat.MapRef(2, 0.3, False))  # no texmap_bump_multiplier: its default, 30
        self.assertEqual(ir.alpha.map, mat.MapRef(3, 1.0, False))
        sss2 = FakeMtl(0, classids.VRAY_FAST_SSS2, "Dim", {0: {
            27: Ref(1), 28: 1, 29: 25.0, 40: (0.5, 0.5, 0.5), 44: 1.5, 3: Ref(2), 4: 1, 5: 150.0, 85: Ref(3), 86: 1,
            87: 60.0}})
        conv, ir = _convert(sss2, _map(1), _map(2), _map(3))
        self.assertEqual((ir.base_color.map, ir.bump, ir.alpha.map),
                         (mat.MapRef(1, 0.25, False), mat.MapRef(2, 1.5, False), mat.MapRef(3, 0.6, False)))
        self.close(ir.specular.value, 0.75, "specular_amount 1.5 x mean 0.5")
        sss2 = FakeMtl(0, classids.VRAY_FAST_SSS2, "Bright", {0: {40: (1.0, 1.0, 1.0), 44: 3.0}})
        self.close(_convert(sss2)[1].specular.value, 1.0, "a reflection weight: at most 1")
        conv, ir = _convert(FakeMtl(0, classids.VRAY_FAST_SSS2, "Default", {0: {}}))
        self.close(ir.subsurface_color, (0.5,) * 3)  # sub_surface_color's default: 127.5 grey
        self.close((ir.subsurface_radius, ir.subsurface_weight, ir.ior), (0.01, 1.0, 1.3))

    def test_car_paints(self):
        common = {0: (0.5, 0.0, 0.0), 1: Ref(1), 2: 1, 4: 0.4, 8: 0.9, 27: (1.0, 1.0, 1.0), 39: 0.95}
        paint = {**common, 31: 0.05, 55: Ref(2), 56: 1}  # coat_strength: reflectance at normal incidence
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL, "Paint", {0: paint}), _map(1), _map(2))
        self.close(ir.base_color.value, (0.5, 0.0, 0.0))
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 1.0, False))
        self.close(ir.roughness.value, 0.1)
        self.close(ir.metallic.value, 1.0)
        self.close(ir.specular.value, 0.4)
        self.close(ir.coat_weight, 1.0)
        self.close(ir.coat_ior, 1.576014)  # (1 + sqrt 0.05) / (1 - sqrt 0.05)
        self.close(ir.coat_roughness, 0.05)
        self.close(ir.coat_color, (1.0, 1.0, 1.0))
        self.assertEqual(ir.bump, mat.MapRef(2, 1.0, False))  # no multipliers: full amount
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL, "Dim", {0: {**paint, 3: 40.0, 57: 20.0}}),
                            _map(1), _map(2))
        self.assertEqual((ir.base_color.map, ir.bump), (mat.MapRef(1, 0.4, False), mat.MapRef(2, 0.2, False)))
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL, "Bare", {0: {**common, 31: 0.0}}), _map(1))
        self.close(ir.coat_weight, 0.0)
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL, "Mirror", {0: {**common, 31: 1.0}}), _map(1))
        self.close(ir.coat_ior, 100.0)  # reflectance 1 is an IOR near 400: clamped like every IOR
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL, "Default", {0: {}}))
        self.close((ir.coat_weight, ir.roughness.value), (1.0, 0.4))  # coat_strength 0.05, base_glossiness 0.6
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL2, "Paint2",
                                    {0: {**common, 31: 0.8, 81: 1.7, 54: Ref(2), 55: 1}}), _map(1), _map(2))
        self.close(ir.coat_weight, 0.8)
        self.close(ir.coat_ior, 1.7)
        self.close(ir.roughness.value, 0.1)
        self.assertEqual(ir.bump, mat.MapRef(2, 1.0, False))
        self.assertEqual(ir.source, "VRayCarPaintMtl2")
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL2, "Dim2",
                                    {0: {**common, 3: 30.0, 54: Ref(2), 55: 1, 56: 70.0}}), _map(1), _map(2))
        self.assertEqual((ir.base_color.map, ir.bump), (mat.MapRef(1, 0.3, False), mat.MapRef(2, 0.7, False)))
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL2, "Default2", {0: {}}))
        self.close((ir.coat_weight, ir.coat_ior, ir.roughness.value), (1.0, 1.5, 0.6))

    def test_ir_default_specular_is_the_iors_own_fresnel(self):
        self.close(mat.MaterialIR(0, "x").specular.value, 1.0, "a reflection weight, drawn as Blender's 0.5")

    def test_unknown_class_is_grey_and_counted(self):
        odd = FakeMtl(0, (0x1234, 0x5678), "Odd")
        odd2 = FakeMtl(1, (0x1234, 0x5678), "Odd2")
        conv = mat.MaterialConverter(FakeGraph(odd, odd2))
        ir = conv.convert(0)
        conv.convert(1)
        conv.convert(0)  # cached: counted once
        self.assertTrue(ir.unknown)
        self.assertEqual(ir.name, "Odd")
        self.close(ir.base_color.value, GREY)
        self.close(ir.specular.value, 1.0, "the IOR's own Fresnel, Blender's default 0.5")
        self.assertEqual(dict(conv.stats.unknown), {"ClassID(0x00001234, 0x00005678)": 2})
        self.assertIs(conv.convert(0), ir)

    def test_unknown_class_is_named_by_its_class_directory(self):
        """A grey material and its count take the class-directory name of the object's class (Blend, ClassID
        (0x250, 0), has no rule yet); a name of 500 characters or with a line break is cut and cleaned."""
        for name, want in (("Blend", "Blend"), ("Bl\nend", "Bl end"),
                           ("z" * 500, "z" * (mat.MAX_CLASS_NAME - 3) + "..."),
                           ("", "ClassID(0x00000250, 0x00000000)")):
            with self.subTest(name=name[:8]):
                conv = mat.MaterialConverter(_NamedGraph({0: name}, FakeMtl(0, (0x250, 0), "Mix")))
                ir = conv.convert(0)
                self.assertTrue(ir.unknown)
                self.assertEqual((ir.source, dict(conv.stats.unknown)), (want, {want: 1}))

    def test_wrapper_peeled_is_named_by_its_class(self):
        """The wrappers peeled are counted under the class's own name, whatever the class directory says."""
        shell = _wrapper(0, classids.SHELL_MTL, {1: 0, 2: Ref(1)})
        conv = mat.MaterialConverter(_NamedGraph({0: "\rshell", 1: "VRayMtl"}, shell, _vray(1)))
        self.assertFalse(conv.convert(0).unknown)
        self.assertEqual(dict(conv.stats.peeled), {"Shell Material": 1})


class Wrappers(unittest.TestCase):
    def test_each_wrapper_peels_to_its_first_set_sub_material(self):
        cases = [
            (classids.VRAY_OVERRIDE_MTL, {0: Ref(2), 2: Ref(1), 4: Ref(1)}, 2),
            (classids.VRAY_MTL_WRAPPER, {0: Ref(1)}, 1),
            (classids.DOUBLE_SIDED_MTL, {0: Ref(2), 1: Ref(1)}, 2),
            (classids.SHELLAC_MTL, {0: Ref(1), 1: Ref(2)}, 1),
            (classids.SHELLAC_MTL, {0: Ref(None), 1: Ref(2)}, 2),  # an empty base: V-Ray and the scanline draw the coat
            (classids.VRAY_2SIDED_MTL, {0: Ref(2), 1: Ref(1)}, 2),
            (classids.VRAY_BLEND_MTL, {0: Ref(1), 1: [Ref(None), Ref(2)]}, 1),
            (classids.CORONA_RAY_SWITCH_MTL, {1600: Ref(1), 1603: Ref(2), 1613: 1}, 2),  # directMtl
            (classids.CORONA_RAY_SWITCH_MTL, {1600: Ref(None), 1603: Ref(2)}, 2),
            (classids.SHELL_MTL, {1: 1, 2: Ref(1), 3: Ref(2)}, 2),  # render index 1: baked
            (classids.SHELL_MTL, {1: 0, 2: Ref(1), 3: Ref(2)}, 1),
        ]
        for class_id, params, want in cases:
            with self.subTest(class_id):
                conv = mat.MaterialConverter(FakeGraph(_wrapper(0, class_id, params), _vray(1, "A"), _vray(2, "B")))
                self.assertEqual(conv.peel(0), (want, None))
                ir = conv.convert(0)
                self.assertIs(ir, conv.convert(want))
                self.assertEqual(ir.name, "AB"[want - 1])
                self.assertEqual(sum(conv.stats.peeled.values()), 1)

    def test_a_sub_material_switched_off_is_still_used(self):
        """V-Ray 5.2 renders a VRayOverrideMtl's base and a Double Sided's facing material whatever their switches say
        (maxdrop-em3.136); the scanline renders a Double Sided side switched off black: an issue when it is the
        facing one, reported once per wrapper object."""
        OV, DS = classids.VRAY_OVERRIDE_MTL, classids.DOUBLE_SIDED_MTL
        override = {0: Ref(1), 2: Ref(2), 4: Ref(3), 6: Ref(4), 8: Ref(5)}
        off = ("Wrap: facing material switched off: drawn all the same, as V-Ray renders it (the scanline renders it "
               "black)")
        cases = [
            (OV, override, False),  # no switches stored: on
            (OV, {**override, 1: 1, 3: 1}, False),
            (OV, {**override, 1: 0}, False),  # baseMtl_on off
            (OV, {**override, 1: 0, 3: 0}, False),  # and giMtl_on
            (OV, {**override, 1: 0, 3: 0, 5: 0, 7: 0, 9: 0}, False),
            (OV, {0: Ref(1), 1: 0, 2: Ref(None), 4: Ref(3)}, False),
            (DS, {0: Ref(1), 1: Ref(2)}, False),
            (DS, {0: Ref(1), 1: Ref(2), 2: 0}, True),  # map1Enabled off
            (DS, {0: Ref(1), 1: Ref(2), 2: 1, 3: 0}, False),  # map2Enabled off: the back is not drawn anyway
            (DS, {0: Ref(1), 1: Ref(2), 2: 0, 3: 0}, True),
        ]
        for class_id, params, issue in cases:
            with self.subTest((class_id, params)):
                subs = [_vray(i, "V%d" % i) for i in range(1, 6)]
                outer = _wrapper(6, classids.VRAY_MTL_WRAPPER, {0: Ref(0)}, "Outer")
                conv = mat.MaterialConverter(FakeGraph(_wrapper(0, class_id, params, "Wrap"), outer, *subs))
                self.assertEqual(conv.peel(6), (1, None))
                self.assertEqual(conv.peel(0), (1, None))  # _sub runs again on the same wrapper
                self.assertEqual(conv.convert(0).name, "V1")
                self.assertEqual(conv.stats.issues, [(0, off)] if issue else [])

    def test_an_empty_first_slot_stops_where_the_renderer_does(self):
        """Rendered in maxdrop-em3.136 (V-Ray 5.2) and maxdrop-6n0.6.4 (V-Ray 5.2, Corona 12): an empty VRayOverrideMtl
        base renders black, an empty Double Sided facing material or VRay2SidedMtl front renders that side not at all,
        a CoronaRaySwitchMtl's direct material empty or switched off renders nothing to the camera: the peel ends there
        (the grey material, the reason in the report) instead of taking the next sub-material."""
        OV, DS, TS, RS = (classids.VRAY_OVERRIDE_MTL, classids.DOUBLE_SIDED_MTL, classids.VRAY_2SIDED_MTL,
                          classids.CORONA_RAY_SWITCH_MTL)
        cases = [
            (OV, {0: Ref(None), 2: Ref(1), 4: Ref(2)}, "Wrap: base material empty: V-Ray renders it black"),
            (OV, {1: 1, 2: Ref(1)}, "Wrap: base material empty: V-Ray renders it black"),  # no base stored
            (DS, {0: Ref(None), 1: Ref(2)},
             "Wrap: facing material empty: V-Ray renders that side not at all, the scanline black"),
            (DS, {0: Ref(None), 1: Ref(2), 2: 0},
             "Wrap: facing material empty: V-Ray renders that side not at all, the scanline black"),
            (TS, {0: Ref(None), 1: Ref(2), 3: 1}, "Wrap: front material empty: V-Ray renders that side not at all"),
            (RS, {1600: Ref(1), 1601: Ref(2), 1603: Ref(None), 1613: 1},
             "Wrap: direct material empty: Corona renders nothing to the camera"),
            (RS, {1600: Ref(1), 1603: Ref(2), 1613: 0},
             "Wrap: direct material switched off: Corona renders nothing to the camera"),
            (RS, {1600: Ref(1), 1603: Ref(None), 1610: 0, 1613: 0},
             "Wrap: direct material switched off: Corona renders nothing to the camera"),
        ]
        for class_id, params, reason in cases:
            with self.subTest((class_id, params)):
                conv = mat.MaterialConverter(FakeGraph(_wrapper(0, class_id, params, "Wrap"), _vray(1, "A"),
                                                       _vray(2, "B")))
                self.assertEqual(conv.peel(0), (None, reason))
                ir = conv.convert(0)
                self.assertTrue(ir.unknown)
                self.assertEqual(ir.name, "Wrap")
                self.assertEqual(conv.stats.issues, [(0, reason)])
                self.assertEqual(conv.source_for(0, 0), 0, "a failed peel is its own answer")

    def test_an_unnamed_wrapper_is_named_by_its_class(self):
        cases = [(classids.VRAY_OVERRIDE_MTL, {2: Ref(1)}, "VRayOverrideMtl: base material empty: V-Ray renders it black"),
                 (classids.VRAY_MTL_WRAPPER, {0: Ref(None)}, "VRayMtlWrapper: no sub-material"),
                 (classids.DOUBLE_SIDED_MTL, {0: Ref(5)}, "Double Sided: sub-material 5 is not a material")]
        for class_id, params, reason in cases:
            with self.subTest(reason):
                conv = mat.MaterialConverter(FakeGraph(_wrapper(0, class_id, params, ""), _vray(1), _map(5)))
                self.assertEqual(conv.peel(0), (None, reason))
        conv = mat.MaterialConverter(FakeGraph(_wrapper(0, classids.DOUBLE_SIDED_MTL, {0: Ref(1), 2: 0}, ""), _vray(1)))
        self.assertEqual(conv.peel(0), (1, None))
        self.assertEqual(conv.stats.issues, [(0, "Double Sided: facing material switched off: drawn all the same, as "
                                                 "V-Ray renders it (the scanline renders it black)")])

    def test_an_empty_blend_base_draws_its_coat_with_an_issue(self):
        """V-Ray 5.2 renders a VRayBlendMtl without a base as its coats over nothing (transparent where the blend is
        below white, maxdrop-6n0.6.4): the first set coat is drawn, a report line says so, once per wrapper object."""
        line = ("Wrap: base material empty: drawn as its coat, which V-Ray renders over nothing (transparent where the "
                "blend is below white)")
        cases = [({0: Ref(None), 1: [Ref(None), Ref(2), Ref(1)]}, 2, [(0, line)]),
                 ({1: [Ref(1)]}, 1, [(0, line)]),  # no base stored
                 ({0: Ref(None), 1: [Ref(None)]}, None, [(0, "Wrap: no sub-material")])]
        for params, want, issues in cases:
            with self.subTest(params):
                outer = _wrapper(6, classids.VRAY_MTL_WRAPPER, {0: Ref(0)}, "Outer")
                conv = mat.MaterialConverter(FakeGraph(_wrapper(0, classids.VRAY_BLEND_MTL, params, "Wrap"), outer,
                                                       _vray(1, "A"), _vray(2, "B")))
                self.assertEqual(conv.peel(6)[0], want)
                self.assertEqual(conv.peel(0)[0], want)  # _sub runs again on the same wrapper
                conv.convert(0)
                self.assertEqual(conv.stats.issues, issues)

    def test_a_facing_slot_switched_off_and_unused_is_no_issue(self):
        """The facing-material line names only a facing material that is drawn: an empty one (the peel ends there)
        or one that is not a material (the peel fails) gives none."""
        DS = classids.DOUBLE_SIDED_MTL
        for params, want in [({0: Ref(None), 1: Ref(2), 2: 0}, (None, "Wrap: facing material empty: V-Ray renders that "
                                                                     "side not at all, the scanline black")),
                             ({0: Ref(7), 1: Ref(2), 2: 0}, (None, "Wrap: sub-material 7 is not a material"))]:
            with self.subTest(params):
                conv = mat.MaterialConverter(FakeGraph(_wrapper(0, DS, params, "Wrap"), _vray(2, "V2"), _map(7)))
                self.assertEqual(conv.peel(0), want)
                self.assertEqual(conv.stats.issues, [])

    def test_nested_wrappers_count_each_once(self):
        objs = (_wrapper(0, classids.VRAY_MTL_WRAPPER, {0: Ref(1)}), _wrapper(1, classids.VRAY_2SIDED_MTL, {0: Ref(2)}),
                _vray(2, "Base"), _wrapper(3, classids.VRAY_MTL_WRAPPER, {0: Ref(1)}))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertEqual(conv.convert(0).name, "Base")
        self.assertEqual(conv.convert(3).name, "Base")
        self.assertEqual(dict(conv.stats.peeled), {"VRayMtlWrapper": 2, "VRay2SidedMtl": 1})

    def test_empty_or_broken_wrappers_give_a_grey_material_named_after_the_wrapper(self):
        cases = [
            ({0: Ref(None)}, "no sub-material"),
            ({0: Ref(5)}, "not a material"),  # a map
            ({0: Ref(9)}, "not a material"),  # outside the graph
            ({0: Ref(0)}, "cycle"),
        ]
        for params, reason in cases:
            with self.subTest(reason):
                conv = mat.MaterialConverter(FakeGraph(_wrapper(0, classids.VRAY_MTL_WRAPPER, params, "Wrap"), _map(5)))
                ir = conv.convert(0)
                self.assertTrue(ir.unknown)
                self.assertEqual(ir.name, "Wrap")
                self.assertIn(reason, ir.issues[0])
                self.assertEqual(conv.stats.issues, [(0, ir.issues[0])])
                self.assertEqual(sum(conv.stats.unknown.values()), 0)

    def test_shell_with_a_bad_render_index(self):
        conv = mat.MaterialConverter(FakeGraph(_wrapper(0, classids.SHELL_MTL, {1: 4, 2: Ref(1)}), _vray(1)))
        base, reason = conv.peel(0)
        self.assertIsNone(base)
        self.assertIn("render index", reason)

    def test_depth_guard(self):
        objs = [_wrapper(i, classids.VRAY_MTL_WRAPPER, {0: Ref(i + 1)}) for i in range(mat.MAX_PEEL + 1)]
        objs.append(_vray(mat.MAX_PEEL + 1, "Deep"))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        base, reason = conv.peel(0)
        self.assertIsNone(base)
        self.assertIn("more than", reason)
        self.assertEqual(conv.peel(1), (mat.MAX_PEEL + 1, None))  # exactly MAX_PEEL wrappers: fine

    def test_multi_sub_object_is_not_peeled(self):
        multi = FakeMtl(0, classids.MULTI_SUB_MTL, "Multi", {0: {0: [Ref(1)]}})
        conv = mat.MaterialConverter(FakeGraph(multi, _vray(1)))
        self.assertEqual(conv.peel(0), (0, None))


if __name__ == "__main__":
    unittest.main()
