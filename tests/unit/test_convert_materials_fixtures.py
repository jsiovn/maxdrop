# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/materials/ on the V-Ray fixtures: vray_basic, vray_maps, vray_wrappers and
vray_more against their authoring scripts, no Blender.

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
    _fixture, _lins, Close, mat, TOLERANCE,
)


class FresnelOn:
    """A MtlBase whose reflection_fresnel (block 1, parameter 8) reads on."""

    def __init__(self, m):
        self._m = m

    def __getattr__(self, name):
        return getattr(self._m, name)

    def param(self, pid, block_id=None, tab=0, default=None):
        return 1 if (pid, block_id) == (8, 1) else self._m.param(pid, block_id, tab, default)


class VRayBasic(unittest.TestCase, Close):
    """tools/fixtures/vray_basic.ms, by hand: sRGB s/255 -> linear ((s/255 + 0.055) / 1.055) ** 2.4."""

    def test_every_channel(self):
        cf, graph, by_name = _fixture("vray_basic")
        with cf:
            conv = mat.MaterialConverter(graph)
            ir = conv.convert(by_name["FixtureVRay"])
            self.assertIsNone(conv.convert(None))  # the real graph: a node without a material
        reflection = (0.309469, 0.361307, 0.417885)  # 151 162 173; mean 0.362887 >= 0.25, below 1, Fresnel off:
        # the tinted mirror (maxdrop-6n0.6.16), weight the brightest channel
        self.assertEqual((ir.name, ir.source, ir.unknown), ("FixtureVRay", "VRayMtl", False))
        self.close(ir.base_color.value, (0.549691, 0.016857, 0.02602), "201 31 41 mixed with 61 71 81 by 0.063986")
        self.close(ir.metallic.value, 0.37, "reflection_metalness")
        self.close(ir.roughness.value, 0.83, "roughness = glossiness 0.83 (useRoughness on)")
        self.close(ir.specular.value, 0.417885, "specular = the brightest reflection channel")
        self.close(ir.mirror_color, tuple(c / 0.417885 for c in reflection), "the mirror tinted R / max(R)")
        self.close(ir.transmission.value, 0.063986, "transmission = mean of 61 71 81")
        self.close(ir.ior, 1.61, "ior = refraction_ior (refracts)")
        self.assertTrue(ir.thin_walled)
        self.close(ir.emission_color.value, (0.003677, 0.008023, 0.014444), "self-illumination 12 22 32")
        self.close(ir.emission_strength, 1.7, "multiplier")
        self.close(ir.alpha.value, 1.0)
        self.close(ir.coat_weight, 0.29)
        self.close(ir.coat_color, (0.226966, 0.266356, 0.309469), "coat 131 141 151")
        self.close(ir.coat_roughness, 0.67, "coat glossiness 0.67 as roughness")
        self.close(ir.coat_ior, 1.57)
        for name in ("base_color", "metallic", "roughness", "specular", "transmission", "emission_color", "alpha"):
            self.assertIsNone(getattr(ir, name).map, name)  # no map in vray_basic
        self.assertIsNone(ir.normal)
        self.assertIsNone(ir.bump)
        self.assertEqual((ir.subsurface_weight, ir.issues, conv.stats.issues), (0.0, [], []))

    def test_without_the_metal_rule(self):
        """The same parameters with Fresnel on: the diffuse, mixed with the refraction color (glass rule)."""
        cf, graph, by_name = _fixture("vray_basic")
        with cf:
            m = FresnelOn(graph.get(by_name["FixtureVRay"]))
            ir = mat.MaterialIR(m.index, m.name)
            mat.vray_mtl(mat.MaterialConverter(graph), m, ir)
        self.close(ir.base_color.value, (0.549691, 0.016857, 0.02602), "201 31 41 mixed with 61 71 81 by 0.063986")
        self.close(ir.metallic.value, 0.37, "reflection_metalness")


class VRayMaps(unittest.TestCase):
    def test_map_slots(self):
        cf, graph, by_name = _fixture("vray_maps")
        with cf:
            conv = mat.MaterialConverter(graph)
            ir = conv.convert(by_name["FixtureVRayMaps"])
            normal = conv.convert(by_name["FixtureVRayNormal"])
        self.assertEqual(ir.base_color.map, mat.MapRef(by_name["FixtureDiffuseMap"], 0.91, False))
        self.assertEqual(ir.specular.map.index, by_name["FixtureReflectMap"])
        self.assertAlmostEqual(ir.specular.map.amount, 0.82, delta=TOLERANCE)
        self.assertEqual(ir.roughness.map.index, by_name["FixtureGlossMap"])
        self.assertTrue(ir.roughness.map.invert)  # a glossiness map, useRoughness off
        self.assertAlmostEqual(ir.roughness.map.amount, 0.73, delta=TOLERANCE)
        self.assertEqual(ir.bump.index, by_name["FixtureBumpMap"])
        self.assertAlmostEqual(ir.bump.amount, 0.64, delta=TOLERANCE)
        self.assertEqual(ir.alpha.map.index, by_name["FixtureOpacityMap"])
        self.assertAlmostEqual(ir.alpha.map.amount, 0.55, delta=TOLERANCE)
        self.assertEqual(normal.normal, mat.MapRef(by_name["FixtureNormalWrap"], 1.0, False))
        self.assertIsNone(normal.bump)
        self.assertEqual(conv.stats.issues, [])


class VRayWrappers(unittest.TestCase, Close):
    def test_each_wrapper_resolves_to_its_sub_material(self):
        cf, graph, by_name = _fixture("vray_wrappers")
        with cf:
            conv = mat.MaterialConverter(graph)
            expect = {"FixtureTwoSided": "FixtureFront", "FixtureBlend": "FixtureBlendBase",
                      "FixtureShell": "FixtureShellOriginal"}  # Shell renderMtlIndex 0: the original
            for wrapper, sub in expect.items():
                with self.subTest(wrapper):
                    self.assertEqual(conv.peel(by_name[wrapper]), (by_name[sub], None))
                    ir = conv.convert(by_name[wrapper])
                    self.assertIs(ir, conv.convert(by_name[sub]))
                    self.assertEqual((ir.name, ir.index, ir.source), (sub, by_name[sub], "VRayMtl"))
            self.assertEqual(conv.peel(by_name["FixtureMulti"]), (by_name["FixtureMulti"], None))
            front = conv.convert(by_name["FixtureTwoSided"])
            self.close(front.base_color.value, (0.64448, 0.006995, 0.006995), "FixtureFront diffuse 210 20 20")
            self.close(front.roughness.value, 1.0 - 0.61, "glossiness 0.61")
        self.assertEqual(dict(conv.stats.peeled), {"VRay2SidedMtl": 1, "VRayBlendMtl": 1, "Shell Material": 1})
        self.assertEqual(conv.stats.issues, [])


class VRayMore(unittest.TestCase, Close):
    """tools/fixtures/vray_more.ms, by hand (gamma off: sRGB s/255 -> linear). Each map's amount is its slot's
    multiplier / 100."""

    @classmethod
    def setUpClass(cls):
        cf, graph, cls.by_name = _fixture("vray_more")
        with cf:
            cls.conv = mat.MaterialConverter(graph)
            cls.irs = {n: cls.conv.convert(cls.by_name[n]) for n in (
                "FixtureLightMtl", "FixtureFastSSS2", "FixtureCarPaint", "FixtureCarPaint2", "FixtureOverride",
                "FixtureMtlWrapper", "FixtureDoubleSided", "FixtureShellac")}
            cls.peels = {n: cls.conv.peel(cls.by_name[n]) for n in cls.irs}
            # parameters behind a switch that is off, or a default switch: the ids the rules read
            cls.raw = {(n, pid): graph.get(cls.by_name[n]).param(pid, 0) for n, pid in (
                ("FixtureFastSSS2", 87), ("FixtureCarPaint2", 3), ("FixtureFastSSS2", 44),
                *(("FixtureOverride", pid) for pid in (1, 3, 5, 7, 9)),
                *(("FixtureDoubleSided", pid) for pid in (2, 3)))}

    def map(self, name, amount=1.0):
        return mat.MapRef(self.by_name[name], amount, False)

    def test_light_mtl(self):
        ir = self.irs["FixtureLightMtl"]
        self.assertEqual((ir.source, ir.unknown), ("VRayLightMtl", False))
        self.close(ir.emission_color.value, _lins(250, 120, 30))
        self.assertEqual(ir.emission_color.map, self.map("FixtureLightMap"))
        self.close(ir.emission_strength, 3.7)
        self.assertIsNone(ir.alpha.map)  # opacity_texmap_on off
        self.close((ir.base_color.value, ir.roughness.value, ir.specular.value), ((0.0,) * 3, 1.0, 0.0))

    def test_fast_sss2(self):
        ir = self.irs["FixtureFastSSS2"]
        self.assertEqual(ir.source, "VRayFastSSS2")
        self.close(ir.base_color.value, _lins(180, 120, 90))
        self.assertEqual(ir.base_color.map.index, self.by_name["FixtureSSSDiffuseMap"])
        self.close(ir.base_color.map.amount, 0.71, "texmap_diffuse_color_multiplier 71")
        self.close(ir.roughness.value, 1.0 - 0.72)
        self.close(ir.specular.value, 0.8 * sum(_lins(200, 210, 220)) / 3, "specular_amount 0.8 x the color")
        self.close(ir.ior, 1.45)
        self.close(ir.subsurface_weight, 1.0 - 0.35)
        self.close(ir.subsurface_color, _lins(220, 90, 70))
        self.close(ir.subsurface_radius, 3.0 * 0.7 / 100, "scatter_radius 3 cm times scale 0.7, in meters")
        self.assertEqual(ir.bump.index, self.by_name["FixtureSSSBumpMap"])
        self.close(ir.bump.amount, 0.47, "texmap_bump_multiplier 47")
        self.assertIsNone(ir.normal)
        self.assertIsNone(ir.alpha.map)  # texmap_opacity_on off
        self.close(self.raw[("FixtureFastSSS2", 87)], 83.0, "texmap_opacity_multiplier, behind its switch")
        self.close(self.raw[("FixtureFastSSS2", 44)], 0.8, "specular_amount")

    def test_car_paint(self):
        ir = self.irs["FixtureCarPaint"]
        self.assertEqual(ir.source, "VRayCarPaintMtl")
        self.close(ir.base_color.value, _lins(150, 20, 30))
        self.assertEqual(ir.base_color.map.index, self.by_name["FixtureCarPaintColorMap"])
        self.close(ir.base_color.map.amount, 0.66, "texmap_base_color_multiplier 66")
        self.close((ir.roughness.value, ir.metallic.value, ir.specular.value), (1.0 - 0.77, 1.0, 0.45))
        self.close(ir.coat_color, _lins(240, 230, 220))
        self.close(ir.coat_roughness, 1.0 - 0.93)
        self.close(ir.coat_weight, 1.0)
        self.close(ir.coat_ior, 1.3 / 0.7, "coat_strength 0.09: (1 + 0.3) / (1 - 0.3)")
        self.assertEqual(ir.bump.index, self.by_name["FixtureCarPaintBumpMap"])
        self.close(ir.bump.amount, 0.44, "texmap_base_bump_multiplier 44")

    def test_car_paint2(self):
        ir = self.irs["FixtureCarPaint2"]
        self.assertEqual(ir.source, "VRayCarPaintMtl2")
        self.close(ir.base_color.value, _lins(20, 60, 150))
        self.assertIsNone(ir.base_color.map)  # texmap_base_color_on off
        self.close((ir.roughness.value, ir.metallic.value, ir.specular.value), (1.0 - 0.66, 1.0, 0.35))
        self.close(ir.coat_color, _lins(230, 240, 250))
        self.close(ir.coat_roughness, 1.0 - 0.88)
        self.close((ir.coat_weight, ir.coat_ior), (0.82, 1.62))
        self.assertEqual(ir.bump.index, self.by_name["FixtureCarPaint2BumpMap"])
        self.close(ir.bump.amount, 0.39, "texmap_base_bump_multiplier 39")
        self.close(self.raw[("FixtureCarPaint2", 3)], 58.0, "texmap_base_color_multiplier, behind its switch")

    def test_wrappers_peel_to_their_base(self):
        expect = {"FixtureOverride": ("FixtureOverrideBase", (200, 40, 40), 0.51),
                  "FixtureMtlWrapper": ("FixtureWrapperBase", (160, 90, 200), 0.56),
                  "FixtureDoubleSided": ("FixtureFacing", (210, 150, 60), 0.57),
                  "FixtureShellac": ("FixtureShellacBase", (120, 200, 160), 0.59)}
        for wrapper, (sub, diffuse, gloss) in expect.items():
            with self.subTest(wrapper):
                self.assertEqual(self.peels[wrapper], (self.by_name[sub], None))
                ir = self.irs[wrapper]
                self.assertEqual((ir.name, ir.index, ir.source), (sub, self.by_name[sub], "VRayMtl"))
                self.close(ir.base_color.value, _lins(*diffuse))
                self.close(ir.roughness.value, 1.0 - gloss)
        self.assertEqual(dict(self.conv.stats.peeled),
                         {"VRayOverrideMtl": 1, "VRayMtlWrapper": 1, "Double Sided": 1, "Shellac": 1})

    def test_wrapper_switches_are_stored_on(self):
        # the peel reads a missing switch as on: the fixture must hold each one, on (its default)
        for (name, pid), v in self.raw.items():
            if name in ("FixtureOverride", "FixtureDoubleSided"):
                with self.subTest((name, pid)):
                    self.assertTrue(isinstance(v, int) and not isinstance(v, bool) and v == 1, v)

    def test_no_issues(self):
        self.assertEqual((self.conv.stats.issues, dict(self.conv.stats.unknown)), ([], {}))
        for name, ir in self.irs.items():
            self.assertEqual(ir.issues, [], name)


if __name__ == "__main__":
    unittest.main()
