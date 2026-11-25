# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/texmaps/ with the gamma off: mixes and wrappers computed on the stored values,
no Blender.

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
from maxdrop_unit_tests.texmaps_support import (  # noqa: E402 (after the loader)
    _bitmap, _bw_mix, _cbitmap, _ccolor, _cmix, _decodes, _falloff, _lin, _noise, _rgb, _table,
    _vbitmap, _vcolor, _wout, _wtint, assets, Checks, colors, FakeGraph, FakeMap, G1, mat, PROBE_COLOR,
    Ref, tx,
)


_dec = colors.srgb_to_linear


def _drawn(n, pixel=128 / 255):
    """What the builder draws for a leaf of a stored graph or a color root at one pixel value: an Image by its color
    space and gamma, a Constant's mean."""
    if isinstance(n, tx.Constant):
        return sum(_rgb(n.value)) / 3.0
    if n.colorspace == tx.SRGB:
        return _dec(pixel)
    return pixel ** (n.gamma or 1.0) if n.colorspace == tx.LINEAR else pixel


class GammaOffMixes(Checks):
    """maxdrop-em3.158, V-Ray 5.2 renders (docs/FORMAT.md, Scene gamma): with the gamma off V-Ray computes a Mix or
    Composite on the stored values (its internal value is the gamma-on one: a Mix of greys 40 -> 220 at 50 % renders
    0.510 in both modes) and the display-referred scene shows it decoded (0.223 linear). In a color graph such a map
    is converted in the kind STORED under one Decode; a Mix between its colors black and white stays as before."""

    G40, G220 = (40 / 255,) * 3, (220 / 255,) * 3

    def _root(self, rule, *objects, kind=tx.COLOR, table=None):
        tex = tx.TexmapConverter(FakeGraph(*objects), _table() if table is None else table, swatches=rule)
        g = tex.convert(mat.MapRef(objects[0].index), kind)
        return None if g is None else g.root

    def _mix(self, **params):
        return FakeMap(1, tx.MIX, {int(k[1:]): v for k, v in params.items()},
                       [v.index for v in params.values() if isinstance(v, Ref) and v.index is not None], cls="Mix")

    def test_constant_mix_is_folded_decoded(self):
        # Mix 40 -> 220 at 50 % renders 0.5098 with the gamma off: srgb_to_linear of it; by a VRayColor 128 mask 0.5112
        mix = self._mix(p0=0.5, p4=self.G40, p5=self.G220)
        self.close(self._root(colors.GAMMA_OFF, mix).value, (_dec(0.509804),) * 3)
        masked = self._mix(p0=0.0, p4=self.G40, p5=self.G220, p8=Ref(2))
        vc = _vcolor(2, (128 / 255,) * 3)
        t = 128 / 255

        def lerp(a, b):
            return _dec((a + (b - a) * t) / 255)
        self.close(self._root(colors.GAMMA_OFF, masked, vc).value, (lerp(40, 220),) * 3, "mask taken as stored")
        self.assertAlmostEqual(lerp(40, 220), _dec(0.511177), delta=1e-4)
        rb = self._mix(p0=0.0, p4=(200 / 255, 40 / 255, 40 / 255), p5=(40 / 255, 60 / 255, 220 / 255), p8=Ref(2))
        want = (lerp(200, 40), lerp(40, 60), lerp(40, 220))  # V-Ray: 0.469352, 0.196231, 0.511177
        self.close(self._root(colors.GAMMA_OFF, rb, vc).value, want, "per channel")

    def test_gamma_on_and_unknown_are_unchanged(self):
        mix = self._mix(p0=0.5, p4=self.G40, p5=self.G220, p6=Ref(2), p8=Ref(3))
        comp = FakeMap(1, tx.COMPOSITE, {8: [100.0, 50.0], 9: [Ref(2), Ref(3)]}, [2, 3], cls="Composite")
        for rule in (colors.GAMMA_ON, colors.UNKNOWN):
            with self.subTest(rule):
                root = self._root(rule, mix, _bitmap(2), _vcolor(3, (0.5,) * 3))
                self.assertIsInstance(root, tx.Mix)
                self.close(root.b.value, self.G220)
                self.close(root.mask.value, 0.5)
                self.assertEqual(_decodes(root), [])
                self.assertIsInstance(self._root(rule, comp, _bitmap(2), _vcolor(3, (0.5,) * 3)), tx.Composite)

    def test_data_graph_is_unchanged_and_a_mask_holds(self):
        mix = self._mix(p0=0.5, p4=self.G40, p5=self.G220, p6=Ref(2))
        root = self._root(colors.GAMMA_OFF, mix, _bitmap(2), kind=tx.DATA)
        self.assertIsInstance(root, tx.Mix)
        self.assertEqual(_decodes(root), [])
        # in a mask the Mix is computed on the held values and its mean decoded (maxdrop-6n0.6.18)
        root = self._root(colors.GAMMA_OFF, mix, _bitmap(2), kind=tx.MASK)
        self.assertTrue(isinstance(root, tx.Decode) and root.mean, root)
        self.assertEqual(root.input.a.colorspace, tx.NON_COLOR)
        self.close(root.input.b.value, self.G220)
        self.assertEqual(len(_decodes(root)), 1)

    def test_mix_with_a_map_is_decoded_once(self):
        mix = self._mix(p0=0.25, p4=self.G40, p5=self.G220, p6=Ref(2), p8=Ref(3))
        root = self._root(colors.GAMMA_OFF, mix, _bitmap(2), _bitmap(3))
        self.assertIsInstance(root, tx.Decode)
        inner = root.input
        self.assertIsInstance(inner, tx.Mix)
        self.assertEqual(inner.a.colorspace, tx.NON_COLOR, "a Bitmap as stored")
        self.assertIsNone(inner.a.gamma)
        self.assertFalse(inner.a.alpha)
        self.close(inner.b.value, self.G220, "a swatch as stored")
        self.assertEqual(inner.mask.colorspace, tx.NON_COLOR, "the mask as stored (a data mask)")
        self.close(inner.factor, 0.25)

    def test_nested_mix_is_not_decoded_again(self):
        outer = self._mix(p0=0.5, p4=self.G40, p6=Ref(2))
        inner = FakeMap(2, tx.MIX, {0: 0.5, 5: self.G220, 6: Ref(3)}, [3], cls="Mix")
        root = self._root(colors.GAMMA_OFF, outer, inner, _bitmap(3))
        self.assertIsInstance(root, tx.Decode)
        self.assertEqual(len(_decodes(root)), 1)
        self.assertIsInstance(root.input.a, tx.Mix)
        self.close(root.input.a.b.value, self.G220)
        self.assertEqual(root.input.a.a.colorspace, tx.NON_COLOR)

    def test_black_to_white_stays_exact(self):
        # maxdrop-em3.36: a mask between black and white is the decoded number (byte 64 renders 64): unchanged; the
        # mix amount the same way (V-Ray renders 0.502 at 50 %, shown from 0.2159)
        by_mask = self._mix(p8=Ref(2))
        root = self._root(colors.GAMMA_OFF, by_mask, _vcolor(2, (128 / 255,) * 3))
        self.assertIsInstance(root, tx.Mix)
        self.close(root.a.value, (0.0,) * 3)
        self.close(root.b.value, (1.0,) * 3)
        self.close(root.mask.value, _lin(128))
        root = self._root(colors.GAMMA_OFF, self._mix(p8=Ref(2)), _bitmap(2))
        self.assertTrue(isinstance(root.mask, tx.Decode) and root.mask.mean, "its stored mean decoded (6n0.6.36)")
        self.assertEqual(root.mask.input.colorspace, tx.NON_COLOR)
        root = self._root(colors.GAMMA_OFF, self._mix(p0=0.5))
        self.assertIsInstance(root, tx.Mix)
        self.close(root.factor, _lin(127.5))
        self.close(self._root(colors.GAMMA_ON, self._mix(p0=0.5)).factor, 0.5)

    def test_a_map_mixed_with_itself_shows_as_alone(self):
        exr = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\a.exr", "")])
        cases = (("Bitmap", _bitmap(2), None, tx.NON_COLOR), ("Bitmap EXR", _bitmap(2), exr, tx.NON_COLOR),
                 ("VRayBitmap sRGB", _vbitmap(2, p25=2), None, tx.SRGB),
                 ("VRayBitmap From 3ds Max", _vbitmap(2, p25=3), None, tx.NON_COLOR),
                 ("VRayBitmap None", _vbitmap(2, p25=0), None, tx.NON_COLOR),
                 ("CoronaBitmap auto", _cbitmap(2), None, tx.SRGB),  # its own decode (maxdrop-em3.165)
                 ("CoronaBitmap 1.0", _cbitmap(2, p125=1.0), None, tx.NON_COLOR))
        for what, leaf, table, space in cases:
            with self.subTest(what):
                mix = self._mix(p0=0.5, p6=Ref(2), p7=Ref(2))
                root = self._root(colors.GAMMA_OFF, mix, leaf, table=table)
                self.assertIsInstance(root, tx.Decode)
                stored = root.input.a
                self.assertEqual(stored.colorspace, space)
                alone = self._root(colors.GAMMA_OFF, leaf, table=table)
                for pixel in (0.25, 128 / 255, 0.75):
                    self.assertAlmostEqual(_drawn(stored, pixel) ** tx.SRGB_GAMMA, _drawn(alone, pixel), delta=0.01,
                                           msg="%s at %g" % (what, pixel))
        hdr = _ccolor(2, p50=1, p58=(0.5, 2.0, 0.0))
        self.close(self._root(colors.GAMMA_OFF, self._mix(p0=0.5, p6=Ref(2), p7=Ref(2)), hdr).value,
                   (0.2140411, 4.9538458, 0.0), "CoronaColor HDR: as at a color root (decoded, maxdrop-em3.165)")
        self.close(self._root(colors.GAMMA_OFF, hdr).value, (0.2140411, 4.9538458, 0.0))
        vc = _vcolor(2, (128 / 255,) * 3)
        self.close(self._root(colors.GAMMA_OFF, self._mix(p0=0.5, p6=Ref(2), p7=Ref(2)), vc).value,
                   (_lin(128),) * 3)

    def test_collapsed_results(self):
        lost = self._mix(p0=0.5, p6=Ref(2), p7=Ref(3))
        root = self._root(colors.GAMMA_OFF, lost, _bitmap(2), _noise(3))
        self.assertIsInstance(root, tx.Image, "peeled to its other side: that image as a color")
        self.assertEqual(root.colorspace, tx.SRGB)
        single = FakeMap(1, tx.COMPOSITE, {9: [Ref(2)]}, [2], cls="Composite")
        self.close(self._root(colors.GAMMA_OFF, single, _vcolor(2, (128 / 255,) * 3)).value, (_lin(128),) * 3)
        self.assertEqual(self._root(colors.GAMMA_OFF, single, _bitmap(2)).colorspace, tx.SRGB)

    def test_composite_on_stored_values(self):
        # Composite 64 + 64 in Addition renders 0.502 (both modes): shown from 0.2159 with the gamma off
        comp = FakeMap(1, tx.COMPOSITE, {5: [0, tx.ADDITION], 8: [100.0, 50.0], 9: [Ref(2), Ref(3)],
                                         10: [Ref(None), Ref(4)]}, [2, 3, 4], cls="Composite")
        root = self._root(colors.GAMMA_OFF, comp, _bitmap(2), _vcolor(3, (64 / 255,) * 3), _bitmap(4))
        self.assertIsInstance(root, tx.Decode)
        layers = root.input.layers
        self.assertEqual(layers[0].node.colorspace, tx.NON_COLOR)
        self.close(layers[1].node.value, (64 / 255,) * 3)
        self.assertEqual(layers[1].blend, tx.ADDITION)
        self.close(layers[1].opacity, 0.5)
        self.assertEqual(layers[1].mask.colorspace, tx.NON_COLOR)

    def test_hdr_mask_is_clamped_when_folded(self):
        hdr = _ccolor(2, p50=1, p58=(2.0, 2.0, 2.0))  # a data mask above 1: a Mix node clamps its factor
        mix = self._mix(p4=self.G40, p5=self.G220, p8=Ref(2))
        self.close(self._root(colors.GAMMA_OFF, mix, hdr).value, (_lin(220),) * 3)

    def test_corona_mix_on_stored_values(self):
        # maxdrop-em3.165, Corona 12 renders: a CoronaMix is computed on the values Corona holds, the same in both
        # modes (a 50 % mix of CoronaBitmaps 64 and 192 renders 0.2917): STORED under a Decode with the gamma off
        both = _cmix(1, [2, 3], p200=6, p201=0.5, p206=Ref(2), p207=Ref(3))
        root = self._root(colors.GAMMA_OFF, both, _cbitmap(2), _cbitmap(3))
        self.assertIsInstance(root, tx.Decode)
        self.assertIsInstance(root.input, tx.Mix)
        self.assertEqual([(i.gamma, i.colorspace) for i in (root.input.a, root.input.b)], [(None, tx.SRGB)] * 2,
                         "each CoronaBitmap by its own decode")
        self.assertIsInstance(self._root(colors.GAMMA_ON, both, _cbitmap(2), _cbitmap(3)), tx.Mix, "gamma on: as is")
        hdr = _cmix(1, [2, 3], p200=10, p206=Ref(2), p207=Ref(3))  # overlay of two HDR colors, folded
        value = self._root(colors.GAMMA_OFF, hdr, _ccolor(2, p50=1, p58=(0.6, 0.2, 0.75)),
                           _ccolor(3, p50=1, p58=(0.05, 0.4, 0.9))).value
        held = tx.blend_value(tx.BLEND_OVERLAY, (0.05, 0.4, 0.9), (0.6, 0.2, 0.75), tx.CM_SRGB_GAMMA)
        self.close(value, tuple(colors.srgb_to_linear(c) for c in held))
        # a peel (an operation not drawn) and a lost side give the image again as a color: shown decoded once more
        peel = _cmix(1, [2, 3], p200=15, p206=Ref(2), p207=Ref(3))
        lost = _cmix(1, [2, 3], p200=6, p201=0.5, p207=Ref(2), p206=Ref(3))
        for what, objects in (("peel", (peel, _cbitmap(2), _noise(3))), ("lost", (lost, _noise(2), _cbitmap(3)))):
            with self.subTest(what):
                image = self._root(colors.GAMMA_OFF, *objects)
                self.assertIsInstance(image, tx.Image)
                self.assertEqual((image.gamma, image.colorspace), (tx.SRGB_TWICE, tx.LINEAR))

    def test_maps_below_a_gamma_off_mix_compute_on_stored_values(self):
        # measured since maxdrop-6n0.6.18 (a Falloff on the stored values; Corona 12 a CoronaMix, em3.165)
        g = (128 / 255,) * 3
        falloff = _falloff(2, color1=g)
        cmix = _cmix(3, p200=0, p208=g, p209=g)  # an add in sRGB mode of two greys 128
        mix = self._mix(p0=0.5, p6=Ref(2), p7=Ref(3))
        root = self._root(colors.GAMMA_OFF, mix, falloff, cmix)
        self.assertIsInstance(root, tx.Decode)
        self.close(root.input.a.a.value, g, "the Falloff's color 1 as stored")
        self.close(root.input.b.value, tx.blend_value(tx.BLEND_ADD, g, g, tx.CM_SRGB_GAMMA), "Corona's add, as stored")

    def test_cut_graph_takes_its_image_as_a_color(self):
        layers, depth = 10, tx.MAX_DEPTH
        objects = [FakeMap(k, tx.COMPOSITE, {9: [Ref(k + 1)] * layers}, [k + 1], cls="Composite")
                   for k in range(1, depth)] + [_bitmap(depth)]
        root = self._root(colors.GAMMA_OFF, *objects)
        self.assertIsInstance(root, tx.Image)
        self.assertEqual(root.colorspace, tx.SRGB)


class GammaOffWrappers(Checks):
    """maxdrop-6n0.6.18, V-Ray 5.2 renders (docs/FORMAT.md, Scene gamma): with the gamma off V-Ray computes a Falloff,
    a Color Correction, an Output, an RGB Tint, a slot's amount and a mix inside a mask on the stored values too (the
    same internal value as with the gamma on), which the display-referred scene shows decoded. At a color root such a
    map is converted in STORED under one Decode; in a mask the mean of it is decoded; a slot's amount mixes the
    stored value."""

    G40, G220 = (40 / 255,) * 3, (220 / 255,) * 3
    X_ROWS = {0: (200 / 255, 50 / 255, 0.0), 1: (0.0, 150 / 255, 100 / 255), 2: (30 / 255, 0.0, 1.0)}

    def _root(self, rule, *objects, kind=tx.COLOR, ref=None, value=None):
        tex = tx.TexmapConverter(FakeGraph(*objects), _table(), swatches=rule)
        g = tex.convert(ref or mat.MapRef(objects[0].index), kind, value)
        return None if g is None else g.root

    def _cc(self, index, below, **params):
        p = {1: Ref(below)}
        p.update({int(k[1:]): v for k, v in params.items()})
        return FakeMap(index, tx.COLOR_CORRECTION, p, [below], cls="Color Correction")

    def test_falloff_on_stored_values(self):
        # Falloff Perpendicular / Parallel of greys 40 / 220 on a plane at facing ratio 0.5: 0.5098 in both modes
        fo = FakeMap(1, tx.FALLOFF, {0: self.G40, 4: self.G220, 8: 1}, cls="Falloff")
        root = self._root(colors.GAMMA_OFF, fo)
        self.assertIsInstance(root, tx.Decode)
        mix = root.input
        self.assertIsInstance(mix.mask, tx.Facing)
        self.close(mix.a.value, self.G40, "color 1 as stored")
        self.close(mix.b.value, self.G220, "color 2 as stored")
        held = 40 / 255 + (220 - 40) / 255 * 0.5
        self.assertAlmostEqual(held, 0.509804, delta=1e-5, msg="V-Ray 5.2 at ratio 0.5")
        self.assertAlmostEqual(held ** tx.SRGB_GAMMA, _dec(0.509804), delta=0.005, msg="the Decode's power")
        on = self._root(colors.GAMMA_ON, fo)
        self.assertIsInstance(on, tx.Mix, "gamma on: as before")
        self.close(on.a.value, self.G40)

    def test_color_correction_on_stored_values(self):
        # brightness 20 over a VRayColor 128 renders 0.702 in both modes; over a Bitmap of 128 grey with the gamma off
        # 0.702 too (the Bitmap as stored)
        root = self._root(colors.GAMMA_OFF, self._cc(1, 2, p11=0, p12=20.0), _vcolor(2, (128 / 255,) * 3))
        self.assertEqual(root, tx.Decode(tx.ColorCorrect(tx.Constant((128 / 255,) * 3), brightness=0.2)))
        root = self._root(colors.GAMMA_OFF, self._cc(1, 2, p11=0, p12=20.0), _bitmap(2))
        self.assertIsInstance(root, tx.Decode)
        self.image(root.input.input, "a.png", tx.NON_COLOR)
        on = self._root(colors.GAMMA_ON, self._cc(1, 2, p11=0, p12=20.0), _bitmap(2))
        self.assertIsInstance(on, tx.ColorCorrect)
        self.image(on.input, "a.png", tx.SRGB)

    def test_wrappers_over_constants_fold(self):
        # Output level 0.5 over a VRayColor 200 renders 0.392 (shown 0.1274); RGB Tint of rows (200, 50, 0) /
        # (0, 150, 100) / (30, 0, 255) over a VRayColor (200, 100, 50) (0.638, 0.384, 0.350): both modes
        root = self._root(colors.GAMMA_OFF, _wout(1, 2), _vcolor(2, (200 / 255,) * 3))
        self.assertIsInstance(root, tx.Constant)
        self.close(root.value, (_dec(0.392157),) * 3)
        root = self._root(colors.GAMMA_OFF, _wtint(1, 2, self.X_ROWS), _vcolor(2, PROBE_COLOR))
        self.assertIsInstance(root, tx.Constant)
        for got, held in zip(root.value, (0.638216, 0.384467, 0.349866)):
            self.assertAlmostEqual(got, _dec(held), delta=0.001)
        for rule in (colors.GAMMA_ON, colors.UNKNOWN):
            with self.subTest(rule):
                self.assertIsInstance(self._root(rule, _wout(1, 2), _vcolor(2, (200 / 255,) * 3)), tx.Adjust)
                self.assertIsInstance(self._root(rule, _wtint(1, 2, self.X_ROWS), _vcolor(2, PROBE_COLOR)), tx.Tint)

    def test_wrapper_over_an_image(self):
        root = self._root(colors.GAMMA_OFF, _wout(1, 2), _bitmap(2))
        self.assertIsInstance(root, tx.Decode)
        self.assertIsInstance(root.input, tx.Adjust)
        self.image(root.input.input, "a.png", tx.NON_COLOR)
        root = self._root(colors.GAMMA_OFF, _wtint(1, 2, self.X_ROWS), _bitmap(2))
        self.assertIsInstance(root, tx.Decode)
        self.close(root.input.red, self.X_ROWS[0], "the rows as stored")

    def test_mix_in_a_mask(self):
        # a Mix black -> white whose mask is a Mix of greys 40 / 220 at 50 % renders 0.5098 (both modes)
        inner = FakeMap(2, tx.MIX, {0: 0.5, 4: self.G40, 5: self.G220}, cls="Mix")
        root = self._root(colors.GAMMA_OFF, _bw_mix(1, 2), inner)
        self.assertIsInstance(root.mask, tx.Constant)
        self.close(root.mask.value, _dec(0.509804), "the held value decoded")
        by_image = FakeMap(2, tx.MIX, {0: 0.0, 4: self.G40, 5: self.G220, 8: Ref(3)}, [3], cls="Mix")
        root = self._root(colors.GAMMA_OFF, _bw_mix(1, 2), by_image, _bitmap(3))
        mask = root.mask
        self.assertTrue(isinstance(mask, tx.Decode) and mask.mean, "the mean decoded")
        self.close(mask.input.a.value, self.G40, "as stored")
        self.image(mask.input.mask, "a.png", tx.NON_COLOR)
        on = self._root(colors.GAMMA_ON, _bw_mix(1, 2), inner)
        self.assertIsInstance(on.mask, tx.Mix, "gamma on: as before")
        self.assertEqual(_decodes(on), [])

    def test_composite_and_falloff_in_a_mask(self):
        comp = FakeMap(2, tx.COMPOSITE, {8: [100.0, 50.0], 9: [Ref(3), Ref(4)]}, [3, 4], cls="Composite")
        root = self._root(colors.GAMMA_OFF, _bw_mix(1, 2), comp, _vcolor(3, self.G40), _vcolor(4, self.G220))
        self.assertTrue(isinstance(root.mask, tx.Decode) and root.mask.mean)
        self.close(root.mask.input.layers[1].node.value, self.G220, "as stored")
        fo = FakeMap(2, tx.FALLOFF, {0: self.G40, 4: self.G220, 8: 1}, cls="Falloff")
        root = self._root(colors.GAMMA_OFF, _bw_mix(1, 2), fo)
        self.assertTrue(isinstance(root.mask, tx.Decode) and root.mask.mean)
        self.assertIsInstance(root.mask.input.mask, tx.Facing)

    def test_black_to_white_in_a_mask_stays(self):
        # em3.36's exact rule holds inside a mask too: the decoded mask of a decoded mask, or its decoded amount
        root = self._root(colors.GAMMA_OFF, _bw_mix(1, 2), _bw_mix(2, 3), _vcolor(3, (128 / 255,) * 3))
        self.assertIsInstance(root.mask, tx.Mix)
        self.close(root.mask.mask.value, _lin(128))
        by_amount = FakeMap(2, tx.MIX, {0: 0.5}, cls="Mix")
        self.close(self._root(colors.GAMMA_OFF, _bw_mix(1, 2), by_amount).mask.factor, _lin(127.5))
        self.close(self._root(colors.GAMMA_ON, _bw_mix(1, 2), by_amount).mask.factor, 0.5)

    def test_color_correction_in_a_mask(self):
        # brightness 20 over a VRayColor 128 as a mask renders 0.702 in both modes; red to all over (200, 100, 50)
        # 0.784 in both modes
        bright = self._cc(2, 3, p11=0, p12=20.0)
        root = self._root(colors.GAMMA_OFF, _bw_mix(1, 2), bright, _vcolor(3, (128 / 255,) * 3))
        self.assertEqual(root.mask, tx.Decode(tx.ColorCorrect(tx.Constant((128 / 255,) * 3), brightness=0.2),
                                              mean=True))
        red = self._cc(2, 3, p2=3, p3=0, p4=0, p5=0)
        root = self._root(colors.GAMMA_ON, _bw_mix(1, 2), red, _vcolor(3, PROBE_COLOR))
        self.assertEqual(root.mask, tx.ColorCorrect(tx.Constant(PROBE_COLOR), (0, 0, 0)),
                         "gamma on: the color, red picked; the builder's mean of it is 0.784")

    def test_slot_amount_on_stored_values(self):
        # a VRayMtl self-illumination of color 40 with a VRayColor 220 at amount 50 % renders 0.5098 in both modes;
        # with a Bitmap of 128 grey 0.329 with the gamma off
        value = (_lin(40),) * 3
        ref = mat.MapRef(1, amount=0.5)
        root = self._root(colors.GAMMA_OFF, _vcolor(1, self.G220), ref=ref, value=value)
        self.assertIsInstance(root, tx.Constant)
        self.close(root.value, (_dec(0.509804),) * 3)
        root = self._root(colors.GAMMA_OFF, _bitmap(1), ref=ref, value=value)
        self.assertIsInstance(root, tx.Decode)
        self.close(root.input.a.value, self.G40, "the input's own value as stored")
        self.image(root.input.b, "a.png", tx.NON_COLOR)
        self.close(root.input.factor, 0.5)
        on = self._root(colors.GAMMA_ON, _bitmap(1), ref=ref, value=self.G40)
        self.assertIsInstance(on, tx.Mix, "gamma on: as before")
        self.assertEqual(_decodes(on), [])
        self.close(on.a.value, self.G40)
        full = self._root(colors.GAMMA_OFF, _bitmap(1), ref=mat.MapRef(1), value=value)
        self.image(full, "a.png", tx.SRGB)
        scaled = self._root(colors.GAMMA_OFF, _bitmap(1), ref=mat.MapRef(1, amount=0.5, scale=0.8), value=value)
        self.assertIsInstance(scaled, tx.Mix, "a scale keeps the decoded mix (not measured)")
        none = self._root(colors.GAMMA_OFF, _bitmap(1), ref=mat.MapRef(1, amount=0.0), value=value)
        self.assertEqual(_decodes(none), [], "an amount of 0: the value alone, exact")
        self.close(none.a.value, value)


if __name__ == "__main__":
    unittest.main()
