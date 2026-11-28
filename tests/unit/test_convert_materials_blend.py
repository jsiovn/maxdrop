# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/materials/ on VRayBlendMtl as layers (maxdrop-o53.1.6): the fixtures vray_wrappers and
pblock_animated against their authoring scripts, and synthetic materials, no Blender.

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
    _fixture, _map, _vray, _wrapper, classids, Close, colors, FakeGraph, mat, Ref, texmaps,
)

BLEND = classids.VRAY_BLEND_MTL


def _weight(rule, *rgb):
    """The weight of a blend color of bytes rgb: the scene's swatch rule on the mean of the channels."""
    return rule.channel(sum(rgb) / 3.0 / 255.0)


class FakeTexmaps:
    """A TexmapConverter stand-in: records each convert(ref, kind, value) and gives a graph, None for map 9."""

    class Graph:
        issues = ("a map line",)

    def __init__(self):
        self.calls = []

    def convert(self, ref, kind, value=None):
        self.calls.append((ref, kind, value))
        return None if ref.index == 9 else self.Graph()


def _blend(params, *subs, texmaps_=None, swatches=colors.GAMMA_ON):
    conv = mat.MaterialConverter(FakeGraph(_wrapper(0, BLEND, params, "Blend"), *subs), texmaps=texmaps_,
                                 swatches=swatches)
    return conv, conv.convert(0)


class BlendFixtures(unittest.TestCase, Close):
    def test_additive_constants(self):
        """vray_wrappers' FixtureBlend: additive mode, coats A and B at blend 40 50 60 and 70 80 90 (gamma off: the
        weights decoded from sRGB, not the raw means); its base's inputs, named after the blend material."""
        cf, graph, by_name = _fixture("vray_wrappers")
        with cf:
            conv = mat.MaterialConverter(graph, texmaps=texmaps.TexmapConverter(graph))
            ir = conv.convert(by_name["FixtureBlend"])
            base = conv.convert(by_name["FixtureBlendBase"])
            self.assertEqual(conv.peel(by_name["FixtureBlend"]), (by_name["FixtureBlend"], None))
        self.assertFalse(conv.swatches.linear, "the fixture is saved with the gamma off")
        self.assertEqual((ir.name, ir.source, ir.unknown), ("FixtureBlend", "VRayBlendMtl", False))
        self.close(ir.base_color.value, base.base_color.value, "the base's inputs")
        self.assertEqual([la.ir.name for la in ir.layers], ["FixtureCoatA", "FixtureCoatB"])
        self.assertEqual([la.mode for la in ir.layers], [mat.ADD, mat.ADD])
        one, two = ir.layers
        self.close((one.amount, two.amount), (_weight(colors.GAMMA_OFF, 40, 50, 60), _weight(colors.GAMMA_OFF, 70, 80,
                                                                                               90)))
        self.assertNotAlmostEqual(one.amount, 50 / 255, places=3)
        self.assertEqual((one.mask, one.graph, two.mask, two.graph), (None, None, None, None))
        self.assertEqual(base.layers, [], "the base itself is untouched")
        self.assertNotIn("VRayBlendMtl", conv.stats.peeled)
        self.assertEqual(ir.issues, ["FixtureBlend: coat 1's blend color (0.157, 0.196, 0.235) drawn as its mean: V-Ray "
                                     "blends per channel",
                                     "FixtureBlend: coat 2's blend color (0.275, 0.314, 0.353) drawn as its mean: V-Ray "
                                     "blends per channel"])

    def test_checker_mask(self):
        """pblock_animated's FixtureAnimBlend: mixed (not additive); coat A's blend map a Checker at its multiplier 37 %
        (a controller's frame-0 value), mixed with the blend color's weight; coat B's blend color animated, at its
        frame-0 70 80 90."""
        cf, graph, by_name = _fixture("pblock_animated")
        with cf:
            conv = mat.MaterialConverter(graph, texmaps=texmaps.TexmapConverter(graph))
            ir = conv.convert(by_name["FixtureAnimBlend"])
        rule = conv.swatches
        self.assertEqual([la.ir.name for la in ir.layers], ["FixtureAnimCoatA", "FixtureAnimCoatB"])
        self.assertEqual([la.mode for la in ir.layers], [mat.MIX, mat.MIX])
        one, two = ir.layers
        self.assertEqual(one.mask, mat.MapRef(by_name["FixtureAnimBlendMap"], 0.37))
        self.assertEqual(one.amount, 1.0)
        root = one.graph.root
        self.assertEqual(one.graph.kind, texmaps.MASK)
        self.assertIsInstance(root, texmaps.Mix, "lerp(blend weight, the map, the multiplier)")
        self.close(root.a.value, _weight(rule, 40, 50, 60))
        self.close(root.factor, 0.37)
        found = []
        stack = [root.b]
        while stack:
            n = stack.pop()
            found.append(type(n).__name__)
            stack.extend(getattr(n, f) for f in ("a", "b", "mask", "input") if hasattr(n, f))
        self.assertIn("Checker", found, "the weight graph holds the Checker")
        self.assertIsNone(two.graph)
        self.close(two.amount, _weight(rule, 70, 80, 90))


class BlendSynthetic(unittest.TestCase, Close):
    def test_without_a_coat_it_stays_a_wrapper(self):
        for params in ({0: Ref(1), 1: [Ref(None), Ref(None)]}, {0: Ref(1), 1: [Ref(2)], 6: [0]}, {0: Ref(1)}):
            with self.subTest(params):
                conv, ir = _blend(params, _vray(1, "Base"), _vray(2, "Coat"))
                self.assertEqual(conv.peel(0), (1, None))
                self.assertIs(ir, conv.convert(1))
                self.assertEqual(dict(conv.stats.peeled), {"VRayBlendMtl": 1})

    def test_without_a_base_it_still_peels_to_its_coat(self):
        conv, ir = _blend({0: Ref(None), 1: [Ref(2)]}, _vray(2, "Coat"))
        self.assertEqual((conv.peel(0), ir.name), ((2, None), "Coat"))

    def test_mix_and_switches(self):
        """Coats 1 and 3 on (2 switched off), mixed: the default blend color 0.5 for a missing one."""
        conv, ir = _blend({0: Ref(1), 1: [Ref(2), Ref(3), Ref(2)], 2: [(1.0, 1.0, 1.0)], 6: [1, 0, 1], 5: 0},
                          _vray(1, "Base"), _vray(2, "A"), _vray(3, "B"))
        self.assertEqual(conv.peel(0), (0, None))
        self.assertEqual([(la.ir.name, la.mode) for la in ir.layers], [("A", mat.MIX), ("A", mat.MIX)])
        self.close(tuple(la.amount for la in ir.layers), (1.0, 0.5))
        self.assertEqual(ir.issues, [])

    def test_map_hand_off(self):
        """A blend map: the TexmapConverter gets a MASK MapRef at the multiplier with the weight as its value; the
        graph's issues go to the IR. No graph back: the weight alone."""
        fake = FakeTexmaps()
        params = {0: Ref(1), 1: [Ref(2), Ref(2), Ref(2)], 2: [(0.2, 0.4, 0.6), (0.2, 0.2, 0.2), (0.3, 0.3, 0.3)],
                  3: [Ref(5), Ref(9), Ref(5)], 4: [100.0, 40.0, 150.0], 5: 1}
        conv, ir = _blend(params, _vray(1, "Base"), _vray(2, "A"), _map(5), _map(9), texmaps_=fake)
        self.assertEqual([(r.index, r.amount, kind) for r, kind, _v in fake.calls],
                         [(5, 1.0, texmaps.MASK), (9, 0.4, texmaps.MASK), (5, 1.5, texmaps.MASK)])
        self.close(tuple(v for _r, _k, v in fake.calls), (0.4, 0.2, 0.3))
        one, two, three = ir.layers
        self.close((one.amount, two.amount, three.amount), (1.0, 0.2, 1.0))
        self.assertIsInstance(one.graph, FakeTexmaps.Graph)
        self.assertIsNone(two.graph)
        self.assertEqual(two.mask, mat.MapRef(9, 0.4))
        self.assertEqual({la.mode for la in ir.layers}, {mat.ADD})
        self.assertIn("a map line", ir.issues)
        self.assertFalse(any("coat 1's blend color" in r for r in ir.issues), "the map at 100 % hides the color")

    def test_without_texmaps_the_weight_is_the_color(self):
        conv, ir = _blend({0: Ref(1), 1: [Ref(2)], 2: [(0.6, 0.6, 0.6)], 3: [Ref(5)], 4: [100.0]},
                          _vray(1, "Base"), _vray(2, "A"), _map(5), swatches=colors.GAMMA_OFF)
        layer = ir.layers[0]
        self.assertEqual((layer.mask, layer.graph), (mat.MapRef(5, 1.0), None))
        self.close(layer.amount, colors.srgb_to_linear(0.6))

    def test_odd_values(self):
        """A blend color out of 0..1 clamped first, a negative multiplier 0, a coat that is not a material an issue."""
        conv, ir = _blend({0: Ref(1), 1: [Ref(2), Ref(5)], 2: [(2.0, -1.0, 0.5), (0.5, 0.5, 0.5)], 3: [Ref(5)],
                           4: [-50.0]}, _vray(1, "Base"), _vray(2, "A"), _map(5), texmaps_=FakeTexmaps())
        self.assertEqual(len(ir.layers), 1)
        self.close(ir.layers[0].mask.amount, 0.0)
        self.assertIn("Blend: layer 5 is not a material", ir.issues)
        self.assertIn("Blend: coat 1's blend color (1.000, 0.000, 0.500) drawn as its mean: V-Ray blends per channel",
                      ir.issues)

    def test_caps_its_coats(self):
        n = mat.MAX_LAYERS + 2
        conv, ir = _blend({0: Ref(1), 1: [Ref(1)] * n}, _vray(1, "Base"))
        self.assertEqual(len(ir.layers), mat.MAX_LAYERS)
        self.assertTrue(any("only the first" in r for r in ir.issues))

    def test_base_not_a_material(self):
        conv, ir = _blend({0: Ref(5), 1: [Ref(2)]}, _vray(2, "A"), _map(5))
        self.assertTrue(ir.unknown)
        self.assertIn("Blend: base is not a material", ir.issues)


if __name__ == "__main__":
    unittest.main()
