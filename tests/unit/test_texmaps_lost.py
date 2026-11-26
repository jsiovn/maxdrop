# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/texmaps/ on what a graph loses (maps without a rule, peeled wrappers) and on
constants below wrappers, no Blender.

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
    _bitmap, _bw_mix, _cbitmap, _ccolor, _cmix, _falloff, _lin, _noise, _rgb, _table, _tex, _vcolor,
    _vnormal, _wout, _wtint, Checks, classdir, classids, colors, FakeGraph, FakeMap, mat, PROBE_COLOR,
    Ref, tx,
)


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


def _tinted_mean(tint):
    """What V-Ray gives a data input from a Tint over a Constant (maxdrop-em3.76): the tint of its color, then the
    mean; what the builder draws (tint() in color, the mean on the float input)."""
    r, g, b = _rgb(tint.input.value)
    return sum(r * tint.red[k] + g * tint.green[k] + b * tint.blue[k] for k in range(3)) / 3.0


STORED_ROWS = ((128 / 255, 0.0, 0.0), (0.0, 64 / 255, 0.0), (0.0, 0.0, 32 / 255))
RULES = (colors.GAMMA_OFF, colors.GAMMA_ON)


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
                if rule.linear:
                    self.close(g.root.red, rule.color(STORED_ROWS[0]), "a color input: the rows linear")
                else:  # tinted with the rows as stored, the result decoded (folded; maxdrop-6n0.6.18)
                    self.close(g.root.value, tuple(_lin(c) for c in (128, 64, 32)))
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
                root = g.root if rule.linear else self.held(g.root)  # gamma off: on the held values (6n0.6.18)
                self.assertEqual(root.input, tx.Constant((1.0, 0.0, 0.0)), "a color input: unchanged")

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
                want = sum(0.5 * c for c in stored) / 3.0  # the Output folded: its mean, then the decode
                self.assertEqual(mask, tx.Constant(colors.srgb_to_linear(want)), "the mean, then the decode")
                _t, mask = self.mask(colors.GAMMA_ON, *objects)
                self.assertEqual(mask, adjust, "gamma on: the color; the builder takes the mean")

    def test_image_below_a_tint_in_a_mask(self):
        _t, mask = self.mask(colors.GAMMA_OFF, _bw_mix(1, 2), _wtint(2, 3), _bitmap(3))
        self.assertTrue(isinstance(mask, tx.Decode) and mask.mean, "the mean through the exact sRGB curve")
        self.image(mask.input.input, "a.png", tx.NON_COLOR)  # V-Ray holds a gamma-off Bitmap as stored
        self.close(mask.input.red, STORED_ROWS[0])
        _t, mask = self.mask(colors.GAMMA_ON, _bw_mix(1, 2), _wtint(2, 3), _bitmap(3))
        self.assertIsInstance(mask, tx.Tint)
        self.image(mask.input, "a.png", tx.SRGB)

    def test_color_correction_in_a_mask_takes_the_color(self):
        # maxdrop-6n0.6.18: a Color Correction in a mask acts on the color V-Ray holds, the mask the mean of it, as a
        # Tint's (saturation -50 % over that VRayColor renders 0.4739 in both modes: the mean of the HSL saturation
        # the builder draws, (0.637 + 0.441 + 0.343) / 3)
        cc = FakeMap(2, tx.COLOR_CORRECTION, {1: Ref(3), 8: -50.0}, [3], cls="Color Correction")
        corrected = tx.ColorCorrect(tx.Constant(PROBE_COLOR), saturation=0.5)
        _t, mask = self.mask(colors.GAMMA_OFF, _bw_mix(1, 2), cc, _vcolor(3, PROBE_COLOR))
        self.assertEqual(mask, tx.Decode(corrected, mean=True), "the mean, then the decode")
        _t, mask = self.mask(colors.GAMMA_ON, _bw_mix(1, 2), cc, _vcolor(3, PROBE_COLOR))
        self.assertEqual(mask, corrected, "gamma on: the color; the builder takes the mean")

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
        # below a Tint or Output in a mask a Color Correction gets the color (the wrapper's kind, maxdrop-6n0.6.38)
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


if __name__ == "__main__":
    unittest.main()
