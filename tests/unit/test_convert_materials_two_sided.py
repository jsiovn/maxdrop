# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/materials/ on VRay2SidedMtl translucency and its back material (maxdrop-o53.1.7): the
fixture vray_wrappers against its authoring script, and synthetic materials, no Blender.

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
    _fixture, _map, _multi, _vray, _wrapper, classids, Close, colors, FakeGraph, mat, Ref, texmaps,
)

TWO = classids.VRAY_2SIDED_MTL
RED, GREEN = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)


class FakeTexmaps:
    """A TexmapConverter stand-in: records each convert(ref, kind, value) and gives a graph, None for map 9."""

    class Graph:
        issues = ("a map line",)

    def __init__(self):
        self.calls = []

    def convert(self, ref, kind, value=None):
        self.calls.append((ref, kind, value))
        return None if ref.index == 9 else self.Graph()


def _two(params, *subs, texmaps_=None, swatches=colors.GAMMA_ON):
    conv = mat.MaterialConverter(FakeGraph(_wrapper(0, TWO, params, "Two"), *subs), texmaps=texmaps_,
                                 swatches=swatches)
    return conv, conv.convert(0)


def _front_back():
    return _vray(1, "Front", b1={1: RED}), _vray(2, "Back", b1={1: GREEN})


class TwoSidedFixture(unittest.TestCase, Close):
    def test_fixture_translucency(self):
        """vray_wrappers' FixtureTwoSided: translucency 64 96 128, its back material off, gamma off: the weight is the
        mean decoded by the sRGB curve (about 0.117), not the raw mean 0.376; no layer; the front's color."""
        cf, graph, by_name = _fixture("vray_wrappers")
        with cf:
            conv = mat.MaterialConverter(graph)
            ir = conv.convert(by_name["FixtureTwoSided"])
            front = conv.convert(by_name["FixtureFront"])
        self.assertEqual(conv.peel(by_name["FixtureTwoSided"]), (by_name["FixtureTwoSided"], None))
        self.assertEqual((ir.name, ir.index, ir.source), ("FixtureTwoSided", by_name["FixtureTwoSided"],
                                                          "VRay2SidedMtl"))
        weight = colors.srgb_to_linear((64 + 96 + 128) / 3.0 / 255.0)
        self.close(ir.translucency.value, weight)
        self.assertLess(ir.translucency.value, 0.2, "not the raw mean 0.376")
        self.assertIsNone(ir.translucency.map)
        self.assertEqual(ir.layers, [])
        self.assertEqual(ir.translucency_color, front.base_color, "no back shown: the front's own color")
        self.close(ir.base_color.value, front.base_color.value)
        self.close(front.translucency.value, 0.0, "the front's own IR is left alone")
        self.assertEqual(ir.issues, ["FixtureTwoSided: translucency color (0.251, 0.376, 0.502) drawn as its mean, "
                                     "not per channel"])


class TwoSidedSynthetic(unittest.TestCase, Close):
    def test_black_without_a_back_stays_a_wrapper(self):
        for params in ({0: Ref(1)}, {0: Ref(1), 7: (0.0, 0.0, 0.0)}, {0: Ref(1), 1: Ref(2), 3: 0, 7: (0.0,) * 3},
                       {0: Ref(1), 7: "bad"}, {0: Ref(1), 1: Ref(1), 3: 1}, {0: Ref(1), 4: Ref(5), 6: 0.0},
                       {0: Ref(1), 4: Ref(5), 5: 0}):
            with self.subTest(params):
                conv, ir = _two(params, *_front_back(), _map(5))
                self.assertEqual(conv.peel(0), (1, None))
                self.assertIs(ir, conv.convert(1))
                self.assertEqual(dict(conv.stats.peeled), {"VRay2SidedMtl": 1})

    def test_translucency_without_a_back(self):
        conv, ir = _two({0: Ref(1), 1: Ref(2), 3: 0, 7: (0.5, 0.5, 0.5)}, *_front_back(), swatches=colors.GAMMA_OFF)
        self.assertEqual(conv.peel(0), (0, None))
        self.close(ir.translucency.value, colors.srgb_to_linear(0.5))
        self.close(ir.translucency_color.value, RED)
        self.assertEqual((ir.layers, ir.issues), ([], []))
        self.assertEqual(dict(conv.stats.peeled), {})

    def test_back_material(self):
        """A back material that is on: a BACK layer of its IR, both sides letting through the same share in the other
        side's base color."""
        conv, ir = _two({0: Ref(1), 1: Ref(2), 3: 1, 7: (0.25, 0.25, 0.25)}, *_front_back())
        self.assertEqual(ir.name, "Two")
        self.close(ir.base_color.value, RED)
        self.close(ir.translucency.value, 0.25)
        self.close(ir.translucency_color.value, GREEN, "the back's color through the front")
        self.assertEqual(len(ir.layers), 1)
        back = ir.layers[0]
        self.assertEqual((back.mode, back.amount, back.graph, back.ir.name), (mat.BACK, 1.0, None, "Back"))
        self.close(back.ir.translucency.value, 0.25)
        self.close(back.ir.translucency_color.value, RED, "the front's color through the back")
        self.close(conv.convert(2).translucency.value, 0.0, "the back's own IR is left alone")

    def test_back_without_translucency(self):
        conv, ir = _two({0: Ref(1), 1: Ref(2), 3: 1, 7: (0.0, 0.0, 0.0)}, *_front_back())
        self.assertEqual(conv.peel(0), (0, None))
        self.assertEqual([la.mode for la in ir.layers], [mat.BACK])
        self.close((ir.translucency.value, ir.layers[0].ir.translucency.value), (0.0, 0.0))

    def test_back_not_a_material(self):
        conv, ir = _two({0: Ref(1), 1: Ref(5), 3: 1, 7: (0.5, 0.5, 0.5)}, _vray(1, "Front"), _map(5))
        self.assertEqual(ir.layers, [])

    def test_map_hand_off(self):
        """A translucency map: the TexmapConverter gets a DATA MapRef at the multiplier with the weight as its value;
        the graph is the translucency's on both sides, its issues the IR's. No graph back: the weight alone."""
        fake = FakeTexmaps()
        conv, ir = _two({0: Ref(1), 1: Ref(2), 3: 1, 7: (0.2, 0.4, 0.6), 4: Ref(5), 6: 40.0}, *_front_back(),
                        _map(5), texmaps_=fake)
        self.assertEqual([(r.index, r.amount, kind) for r, kind, _v in fake.calls], [(5, 0.4, texmaps.DATA)])
        self.close(fake.calls[0][2], 0.4, "the weight, the slot's own value")
        self.assertEqual(ir.translucency.map, mat.MapRef(5, 0.4))
        self.assertIsInstance(ir.textures["translucency"], FakeTexmaps.Graph)
        self.assertIs(ir.layers[0].ir.textures["translucency"], ir.textures["translucency"])
        self.assertIn("a map line", ir.issues)
        self.assertIn("Two: translucency color (0.200, 0.400, 0.600) drawn as its mean, not per channel", ir.issues,
                      "the map at 40 % leaves the color its share")
        conv, ir = _two({0: Ref(1), 7: (0.2, 0.4, 0.6), 4: Ref(5)}, *_front_back(), _map(5), texmaps_=FakeTexmaps())
        self.assertFalse(any("translucency color" in r for r in ir.issues), "the map at 100 % hides the color")
        conv, ir = _two({0: Ref(1), 7: (0.3, 0.3, 0.3), 4: Ref(9)}, *_front_back(), _map(9), texmaps_=FakeTexmaps())
        self.assertNotIn("translucency", ir.textures)
        self.close(ir.translucency.value, 0.3)

    def test_map_alone_leaves_the_peel(self):
        conv, ir = _two({0: Ref(1), 7: (0.0, 0.0, 0.0), 4: Ref(5), 5: 1, 6: 100.0}, *_front_back(), _map(5),
                        texmaps_=FakeTexmaps())
        self.assertEqual(conv.peel(0), (0, None))
        self.assertIn("translucency", ir.textures)
        self.close(ir.translucency.value, 0.0)

    def test_colored_textures(self):
        """The other side's base color graph is the translucency color's."""
        conv, ir = _two({0: Ref(1), 1: Ref(2), 3: 1, 7: (0.5, 0.5, 0.5)},
                        _vray(1, "Front", b1={1: RED}, b4={100: Ref(5)}), _vray(2, "Back"), _map(5),
                        texmaps_=FakeTexmaps())
        self.assertIs(ir.layers[0].ir.textures["translucency_color"], ir.textures["base_color"])
        self.assertNotIn("translucency_color", ir.textures, "the back has no base color map")

    def test_multi_front(self):
        """A front that is a Multi/Sub-Object keeps the peel (its face IDs), with a line; one below a wrapper is
        drawn as its first entry, with a line."""
        multi = _multi(1, [(0, Ref(2), 1)])
        conv, ir = _two({0: Ref(1), 7: (0.5, 0.5, 0.5)}, multi, _vray(2, "Sub"))
        self.assertEqual(conv.peel(0), (1, None))
        self.assertIn("Two: front material is a Multi/Sub-Object: drawn by face ID, its translucency and back "
                      "material not drawn", [r for _i, r in conv.stats.issues])
        conv, ir = _two({0: Ref(3), 7: (0.5, 0.5, 0.5)}, multi, _vray(2, "Sub"),
                        _wrapper(3, classids.VRAY_MTL_WRAPPER, {0: Ref(1)}))
        self.assertEqual(conv.peel(0), (0, None))
        self.assertEqual(ir.name, "Two")
        self.assertIn("Two: Multi/Sub-Object 3 drawn as its first entry", ir.issues)

    def test_front_not_a_material(self):
        conv, ir = _two({0: Ref(5), 7: (0.5, 0.5, 0.5)}, _map(5))
        self.assertTrue(ir.unknown)

    def test_mult_by_front_diffuse(self):
        conv, ir = _two({0: Ref(1), 7: (0.5, 0.5, 0.5), 9: 1}, *_front_back())
        self.assertIn("Two: Mult by front diffuse not drawn: the translucency is not tinted by the front's diffuse",
                      ir.issues)

    def test_bsdf_cap(self):
        """A back that would take the material past MAX_LAYER_BSDFS Principled BSDFs is left out, with a line."""
        n = mat.MAX_LAYER_BSDFS
        heavy = _wrapper(2, classids.VRAY_BLEND_MTL, {0: Ref(3), 1: [Ref(3)] * mat.MAX_LAYERS}, "Heavy")  # 17
        front = _wrapper(1, classids.VRAY_BLEND_MTL, {0: Ref(3), 1: [Ref(2)]}, "Front")  # 18
        back = _wrapper(4, classids.VRAY_BLEND_MTL, {0: Ref(3), 1: [Ref(2)] * 3}, "Back")  # 52
        conv, ir = _two({0: Ref(1), 1: Ref(4), 3: 1, 7: (0.5, 0.5, 0.5)}, front, heavy, back, _vray(3, "C"))
        self.assertEqual((conv.bsdf_count(conv.convert(1)), conv.bsdf_count(conv.convert(4))), (18, 52))
        self.assertEqual([la.mode for la in ir.layers], [mat.MIX], "the front's coat, no back")
        self.assertIn("Two: back material not drawn: past %d Principled BSDFs" % n, ir.issues)


if __name__ == "__main__":
    unittest.main()
