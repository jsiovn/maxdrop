# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/texmaps/ on the scene gamma: swatches, images on color, data, mask, normal and
bump inputs, no Blender.

    python -I -m unittest discover tests
"""
import dataclasses
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
    _bitmap, _cbitmap, _ccolor, _cmix, _decodes, _falloff, _info, _lin, _placed, _table, _tex, _vbitmap,
    _vnormal, _wtint, assets, Checks, classids, colors, FakeGraph, FakeMap, G1, mat, MEAN, pblock, Ref,
    tx,
)


class SwatchRule(Checks):
    """Every swatch of a map goes through the scene's rule: linear with the gamma on (or unknown), sRGB with it off;
    the HDR color is decoded only with the gamma off (maxdrop-em3.165), CoronaColor's temperature too."""

    def _root(self, swatches, *objects, kind=tx.COLOR):
        tex = tx.TexmapConverter(FakeGraph(*objects), _table(), swatches=swatches)
        return tex.convert(mat.MapRef(objects[0].index), kind).root

    def test_default_is_unknown(self):
        self.assertIs(_tex().swatches, colors.UNKNOWN)

    def test_each_swatch_by_the_rule(self):
        g = 128 / 255
        mix = FakeMap(1, tx.MIX, {4: (g,) * 3, 5: (g,) * 3}, cls="Mix")
        falloff = FakeMap(1, tx.FALLOFF, {0: (g,) * 3}, cls="Falloff")
        dirt = FakeMap(1, tx.VRAY_DIRT, {13: (g,) * 3}, cls="VRayDirt")
        cc = FakeMap(1, tx.COLOR_CORRECTION, {0: (g,) * 3}, cls="Color Correction")
        vc = FakeMap(1, classids.VRAY_COLOR, {5: (g,) * 3}, cls="VRayColor")
        cco = _ccolor(1, p52=(g,) * 3)
        hexed = _ccolor(1, p50=3, p59="#808080")
        for rule, want in ((colors.GAMMA_ON, 0.501961), (colors.GAMMA_OFF, 0.215861), (colors.UNKNOWN, 0.501961)):
            with self.subTest(rule):
                root = self._root(rule, mix)
                if rule is colors.GAMMA_OFF:  # mixed as stored, shown decoded: folded (em3.158)
                    self.close(root.value, (want,) * 3)
                else:
                    self.close(root.a.value, (want,) * 3)
                    self.close(root.b.value, (want,) * 3)
                held = rule is colors.GAMMA_OFF  # a Falloff or Color Correction on the held values (6n0.6.18)
                fo, c = self._root(rule, falloff), self._root(rule, cc)
                self.close((self.held(fo) if held else fo).a.value, (g if held else want,) * 3)
                self.close(self._root(rule, dirt).value, (want,) * 3)
                self.close((self.held(c) if held else c).input.value, (g if held else want,) * 3)
                for m in (vc, cco, hexed):
                    self.close(self._root(rule, m).value, (want,) * 3, m.cls)
                self.close(self._root(rule, vc, kind=tx.MASK).value, want, "a mask: the rule of the mean")
                self.close(self._root(rule, vc, kind=tx.DATA).value, g, "a data input: the mean as stored")

    def test_mask_constants_are_the_rule_of_the_mean_swatch(self):
        # V-Ray 5.2 render of a Mix black -> white by a VRayColor mask (maxdrop-em3.36, plan in docs/plans/): red
        # 255 0 0 renders 0.333 linear with the gamma on and byte 85 with it off, which a linear
        # srgb_to_linear(1 / 3) = 0.0908 shows; grey 64 renders 0.251 linear on, byte 64 off. On a data input
        # the mean as stored (maxdrop-em3.122): 1 / 3 and 64 / 255 whatever the rule.
        red, grey = (1.0, 0.0, 0.0), (64 / 255,) * 3
        cases = ((colors.GAMMA_ON, red, 1 / 3), (colors.UNKNOWN, red, 1 / 3), (colors.GAMMA_OFF, red, 0.0908417),
                 (colors.GAMMA_ON, grey, 64 / 255), (colors.GAMMA_OFF, grey, _lin(64)))
        for rule, rgb, want in cases:
            maps = (FakeMap(1, tx.MIX, {4: rgb, 5: rgb}, cls="Mix"),
                    FakeMap(1, classids.VRAY_COLOR, {5: rgb}, cls="VRayColor"),
                    _ccolor(1, p52=rgb),
                    _ccolor(1, p50=3, p59="#%02X%02X%02X" % tuple(round(c * 255) for c in rgb)))
            for m in maps:
                with self.subTest(rule=rule, rgb=rgb, cls=m.cls, method=m.param(50, 0)):
                    mask, color = self._root(rule, m, kind=tx.MASK), self._root(rule, m, kind=tx.COLOR)
                    data = self._root(rule, m, kind=tx.DATA)
                    if m.cls == "Mix":  # a Mix of two constants with the gamma off: folded (em3.158, 6n0.6.18)
                        mask, data = mask.a if isinstance(mask, tx.Mix) else mask, data.a
                        color = color.a if isinstance(color, tx.Mix) else color
                    self.close(mask.value, want)
                    self.close(data.value, sum(rgb) / 3.0, "a data input: as stored")
                    self.close(color.value, rule.color(rgb), "a color input: the linear color")

    def test_hdr_color_by_the_gamma(self):
        # maxdrop-em3.165, Corona 12 renders: the HDR color renders as stored (0.25 / 0.5 / 2.0; 0.5 x multiplier 2:
        # 1.0) with the gamma on and off, linear with it on; with it off the display-referred scene shows it decoded,
        # above 1 on the extended curve (2.0: 4.954), as V-Ray 5.2 renders it too; a data input takes the mean as stored
        hdr = _ccolor(1, p50=1, p58=(0.25, 0.5, 2.0))
        for rule in (colors.GAMMA_ON, colors.UNKNOWN):
            with self.subTest(rule):
                self.close(self._root(rule, hdr).value, (0.25, 0.5, 2.0))
                self.close(self._root(rule, hdr, kind=tx.MASK).value, 2.75 / 3.0)
        self.close(self._root(colors.GAMMA_OFF, hdr).value, (0.0508760, 0.2140411, 4.9538457))
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=1, p57=2.0, p58=(0.5, 0.5, 0.5))).value,
                   (1.0, 1.0, 1.0), "the multiplier before the decode")
        self.close(self._root(colors.GAMMA_OFF, hdr, kind=tx.MASK).value, colors.srgb_to_linear(2.75 / 3.0),
                   "a mask: the mean decoded, as a swatch's")
        for rule in (colors.GAMMA_ON, colors.GAMMA_OFF):
            with self.subTest(rule):
                self.close(self._root(rule, _ccolor(1, p50=1, p58=(1.5, 0.0, 0.0)), kind=tx.DATA).value, 0.5)

    def test_kelvin_by_the_rule(self):
        # maxdrop-em3.38: VRayColor and CoronaColor at 3000 K render the same values with the gamma on and off
        # (V-Ray 5.2, renderMap): with it off the scene is display-referred, so both are decoded from sRGB; with it
        # on Corona's linear color times the multiplier, not clamped
        k = tx.corona_kelvin(3000.0)
        self.close(self._root(colors.GAMMA_ON, _ccolor(1, p50=2, p51=3000.0)).value, k)
        self.close(self._root(colors.UNKNOWN, _ccolor(1, p50=2, p51=3000.0, p57=2.0)).value, tuple(2 * c for c in k))
        self.close(self._root(colors.GAMMA_ON, _ccolor(1, p50=2, p51=3000.0), kind=tx.DATA).value, sum(k) / 3.0)
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=2, p51=3000.0)).value, colors.GAMMA_OFF.color(k))
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=2, p51=3000.0, p57=2.0)).value,
                   colors.GAMMA_OFF.color(tuple(2 * c for c in k)), "clamped, then decoded")
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=2, p51=3000.0), kind=tx.MASK).value,
                   colors.GAMMA_OFF.channel(sum(k) / 3.0), "a mask: the rule of the mean")
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=2, p51=3000.0), kind=tx.DATA).value,
                   sum(min(1.0, c) for c in k) / 3.0, "a data input: the mean as stored")
        self.close(self._root(colors.GAMMA_OFF, _ccolor(1, p50=2, p51=3000.0)).value,
                   (1.0, _lin(121.607), _lin(39.1868)), "3ds Max's 255 121.6 39.2 through Blender's sRGB display")


class SceneGammaImages(Checks):
    """maxdrop-em3.38: an image on a color input as 3ds Max 2020 + V-Ray 5.2 read a 128 grey PNG (docs/FORMAT.md,
    Scene gamma): with the gamma on a Bitmap with automatic gamma (and a VRayBitmap From 3ds Max) takes the file
    input gamma; with it off a Bitmap is read as stored whatever its gamma; CoronaBitmap applies its own in both.
    maxdrop-em3.123 (the same renders, greys 64 / 128 / 192, EXRs 0.25 / 0.5 / 2.0): with the gamma off V-Ray shows a
    VRayBitmap's own decode, and a float file read as stored, decoded once more on a color input or a mask (the
    internal value v as srgb_to_linear(v)); maxdrop-em3.165: Corona 12 a CoronaBitmap's alike."""

    ON_10 = colors.Swatches(True, file_in=1.0)
    ON_18 = colors.Swatches(True, file_in=1.8)

    def _bitmap(self, rule, info=None, kind=tx.COLOR, table=None):
        b, chunk_map = _placed(info=info)
        tex = tx.TexmapConverter(FakeGraph(b, chunk_map=chunk_map), _table() if table is None else table,
                                 swatches=rule)
        return tex.convert(mat.MapRef(1), kind).root

    def _map(self, rule, m, kind=tx.COLOR):
        return tx.TexmapConverter(FakeGraph(m), _table(), swatches=rule).convert(mat.MapRef(1), kind).root

    def check(self, image, gamma, space, msg=None):
        if space == MEAN:  # an image read as stored as a gamma-off mask: its mean decoded (maxdrop-6n0.6.36)
            self.assertIsInstance(image, tx.Decode, msg)
            self.assertTrue(image.mean, msg)
            image, space = image.input, tx.NON_COLOR
        self.assertEqual(image.colorspace, space, msg)
        if gamma is None:
            self.assertIsNone(image.gamma, msg)
        else:
            self.close(image.gamma, gamma, msg)

    def test_bitmap_automatic(self):
        for rule, gamma, space in ((colors.GAMMA_ON, None, tx.SRGB), (colors.UNKNOWN, None, tx.SRGB),
                                   (self.ON_10, 1.0, tx.LINEAR), (self.ON_18, 1.8, tx.LINEAR),
                                   (colors.GAMMA_OFF, None, tx.SRGB)):
            with self.subTest(rule):
                self.check(self._bitmap(rule), gamma, space)
                self.check(self._bitmap(rule, info=_info(1.0, 20)), gamma, space, "no override flag: automatic")

    def test_bitmap_override(self):
        for rule in (colors.GAMMA_ON, self.ON_10, colors.UNKNOWN):
            with self.subTest(rule):
                self.check(self._bitmap(rule, info=_info(1.0, 5)), 1.0, tx.LINEAR, "the override wins")
                self.check(self._bitmap(rule, info=_info(2.2, 5)), 2.2, tx.SRGB)
        for info in (_info(1.0, 5), _info(1.8, 5), _info(2.2, 5)):
            self.check(self._bitmap(colors.GAMMA_OFF, info=info), None, tx.SRGB, "gamma off: read as stored")

    def test_float_files_and_data_inputs(self):
        table = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.exr", "")])
        for rule in (colors.GAMMA_ON, self.ON_10, colors.GAMMA_OFF, colors.UNKNOWN):
            with self.subTest(rule):
                # gamma off: as stored, which the scene shows decoded (an EXR of 0.5 renders 0.5, shown 0.214)
                self.check(self._bitmap(rule, table=table), 1.0 if rule.linear else None,
                           tx.LINEAR if rule.linear else tx.SRGB, "an EXR: linear")
                self.check(self._bitmap(rule, table=table, kind=tx.MASK), 1.0 if rule.linear else None,
                           tx.NON_COLOR if rule.linear else MEAN, "an EXR as a mask: the color rule")
                self.check(self._bitmap(rule, table=table, kind=tx.DATA), 1.0 if rule.linear else None,
                           tx.NON_COLOR, "an EXR: as stored")
                # a data input: decoded as a color input with the gamma on, as stored with it off (em3.122)
                for info in (None, _info(1.0, 5)):
                    color, data = self._bitmap(rule, info=info), self._bitmap(rule, info=info, kind=tx.DATA)
                    want = tx.colorspace(tx.DATA, color.gamma) if rule.linear else tx.NON_COLOR
                    self.assertEqual(data.colorspace, want, info)
                    if rule.linear and color.colorspace == tx.SRGB:
                        self.assertEqual(data.colorspace, tx.SRGB, info)
        self.check(self._bitmap(colors.GAMMA_ON, info=_info(1.8, 5), table=table), 1.8, tx.LINEAR,
                   "gamma on: an EXR's override is kept")
        self.check(self._bitmap(colors.GAMMA_OFF, info=_info(1.8, 5), table=table), None, tx.SRGB,
                   "gamma off: an EXR's override does nothing (the rule's; only an automatic EXR was measured)")

    def test_vray_bitmap(self):
        for rule, gamma, space in ((colors.GAMMA_ON, None, tx.SRGB), (self.ON_10, 1.0, tx.LINEAR),
                                   (self.ON_18, 1.8, tx.LINEAR), (colors.GAMMA_OFF, None, tx.SRGB),
                                   (colors.UNKNOWN, None, tx.SRGB)):
            with self.subTest(rule):
                self.check(self._map(rule, _vbitmap(1, p25=3)), gamma, space, "From 3ds Max: the input gamma")
                for cs in (2, 4):  # V-Ray's own curve; with the gamma off shown decoded once more
                    self.check(self._map(rule, _vbitmap(1, p25=cs)), None if rule.linear else tx.SRGB_TWICE,
                               tx.SRGB if rule.linear else tx.LINEAR, "sRGB, Auto: V-Ray's own")
                self.check(self._map(rule, _vbitmap(1, p25=0)), 1.0 if rule.linear else 2.2,
                           tx.LINEAR if rule.linear else tx.SRGB, "None: as stored, shown decoded with the gamma off")
                self.assertEqual(self._map(rule, _vbitmap(1, p25=3), kind=tx.DATA).colorspace,
                                 tx.colorspace(tx.DATA, gamma) if rule.linear else tx.NON_COLOR,
                                 "From 3ds Max on a data input")
                self.assertEqual(self._map(rule, _vbitmap(1, p25=2), kind=tx.DATA).colorspace, tx.SRGB)

    def test_vray_bitmap_gamma_off_is_shown_decoded(self):
        # (params, file, color / mask gamma and space with the gamma off, the data input's)
        exr = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.exr", "")])
        cases = (({"p25": 1, "p8": 2.0}, None, (1.1, tx.LINEAR), (1.1, tx.LINEAR), (0.5, tx.LINEAR)),
                 ({"p25": 1, "p8": 2.2}, None, (1.0, tx.LINEAR), (1.0, tx.NON_COLOR), (1 / 2.2, tx.LINEAR)),
                 ({"p25": 2}, None, (tx.SRGB_TWICE, tx.LINEAR), (tx.SRGB_TWICE, tx.LINEAR), (None, tx.SRGB)),
                 ({"p25": 0}, None, (2.2, tx.SRGB), (2.2, tx.SRGB), (1.0, tx.NON_COLOR)),
                 ({"p25": 3}, None, (None, tx.SRGB), (None, MEAN), (None, tx.NON_COLOR)),
                 ({"p25": 4}, exr, (2.2, tx.SRGB), (2.2, tx.SRGB), (1.0, tx.NON_COLOR)),
                 ({"p25": 0}, exr, (2.2, tx.SRGB), (2.2, tx.SRGB), (1.0, tx.NON_COLOR)),
                 ({"p25": 3}, exr, (None, tx.SRGB), (None, MEAN), (1.0, tx.NON_COLOR)),
                 ({"p25": 2}, exr, (tx.SRGB_TWICE, tx.LINEAR), (tx.SRGB_TWICE, tx.LINEAR), (None, tx.SRGB)))
        for params, table, color, mask, data in cases:
            with self.subTest(params=params, exr=table is not None):
                for kind, (gamma, space) in ((tx.COLOR, color), (tx.MASK, mask), (tx.DATA, data)):
                    tex = tx.TexmapConverter(FakeGraph(_vbitmap(1, **params)), _table() if table is None else table,
                                             swatches=colors.GAMMA_OFF)
                    self.check(tex.convert(mat.MapRef(1), kind).root, gamma, space, kind)

    def test_unshown_and_drawn_gamma(self):
        img = tx.Image(1, "sky.exr")
        for shown, own, space in ((None, 1.0, tx.LINEAR), (2.2, 1.0, tx.LINEAR), (tx.SRGB_TWICE, None, tx.SRGB),
                                  (1.1, 0.5, tx.LINEAR)):
            back = tx.unshown(dataclasses.replace(img, gamma=shown, colorspace=tx.colorspace(tx.COLOR, shown)))
            self.check(back, own, space, shown)
        for gamma, space, drawn in ((None, tx.SRGB, None), (2.2, tx.SRGB, None), (1.0, tx.LINEAR, None),
                                    (tx.SRGB_TWICE, tx.LINEAR, tx.SRGB_TWICE), (0.5, tx.LINEAR, 0.5),
                                    (0.5, tx.NON_COLOR, None), (1.8, tx.SRGB, None)):
            self.assertEqual(tx.drawn_gamma(dataclasses.replace(img, gamma=gamma, colorspace=space)), drawn,
                             (gamma, space))

    def test_shown_values_agree_with_v_ray(self):
        # V-Ray 5.2 internal values with the gamma off (on: the same), shown as srgb_to_linear in Blender: what
        # Blender draws (pixel ^ gamma, sRGB for 2.2) is within 0.02 of it
        def drawn(pixel, gamma):
            return colors.srgb_to_linear(pixel) if gamma is None or abs(gamma - 2.2) < 1e-9 else pixel ** gamma
        cases = ((2, 64, 0.0512696), (2, 128, 0.215861), (2, 192, 0.527115), (0, 64, 0.25098), (0, 192, 0.752941),
                 (1, 128, 0.708492), (1, 192, 0.867722))
        for cs, grey, internal in cases:
            with self.subTest(cs=cs, grey=grey):
                params = {"p25": cs, "p8": 2.0} if cs == 1 else {"p25": cs}
                image = self._map(colors.GAMMA_OFF, _vbitmap(1, **params))
                self.assertLess(abs(drawn(grey / 255.0, image.gamma) - colors.srgb_to_linear(internal)), 0.02)
        inverse = self._map(colors.GAMMA_OFF, _vbitmap(1, p25=1, p8=0.5))  # inverse gamma 0.5: 128 -> 0.252
        self.assertLess(abs(drawn(128 / 255.0, inverse.gamma) - colors.srgb_to_linear(0.251965)), 0.02)

    def test_corona_bitmap_keeps_its_own_with_the_gamma_on(self):
        for rule in (colors.GAMMA_ON, self.ON_10, colors.UNKNOWN):
            with self.subTest(rule):
                self.check(self._map(rule, _cbitmap(1)), None, tx.SRGB, "automatic: 2.2 whatever the input gamma")
                self.check(self._map(rule, _cbitmap(1, p125=1.0)), 1.0, tx.LINEAR)
                self.check(self._map(rule, _cbitmap(1), kind=tx.MASK), None, tx.SRGB)

    def test_corona_bitmap_gamma_off_is_shown_decoded(self):
        # maxdrop-em3.165, Corona 12 renders: a CoronaBitmap's internal value is its own decode with the gamma on and
        # off, as a VRayBitmap's in V-Ray: shown decoded once more on a color input or a mask; data keeps its own
        exr = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.exr", "")])
        cases = (({}, None, (tx.SRGB_TWICE, tx.LINEAR), (None, tx.SRGB)),
                 ({"p125": 2.2}, None, (2.2 * 2.2, tx.LINEAR), (2.2, tx.SRGB)),
                 ({"p125": 1.0}, None, (2.2, tx.SRGB), (1.0, tx.NON_COLOR)),
                 ({}, exr, (2.2, tx.SRGB), (1.0, tx.NON_COLOR)),
                 ({"p125": 2.2}, exr, (2.2 * 2.2, tx.LINEAR), (2.2, tx.SRGB)))
        for params, table, shown, data in cases:
            with self.subTest(params=params, exr=table is not None):
                for kind, (gamma, space) in ((tx.COLOR, shown), (tx.MASK, shown), (tx.DATA, data)):
                    tex = tx.TexmapConverter(FakeGraph(_cbitmap(1, **params)), _table() if table is None else table,
                                             swatches=colors.GAMMA_OFF)
                    self.check(tex.convert(mat.MapRef(1), kind).root, gamma, space, kind)

    def test_corona_shown_values_agree_with_corona(self):
        # Corona 12 internal values (gamma on and off alike), shown as srgb_to_linear in Blender with the gamma off:
        # what Blender draws (pixel ^ gamma, the sRGB curve for 2.2, extended above 1) is within 0.02 of it
        def drawn(pixel, gamma):
            return colors.srgb_to_linear(pixel) if gamma is None or abs(gamma - 2.2) < 1e-9 else pixel ** gamma
        exr = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.exr", "")])
        cases = (({}, None, 64, 0.0477758), ({}, None, 128, 0.21952), ({}, None, 192, 0.535642),
                 ({"p125": 2.2}, None, 128, 0.21952), ({"p125": 1.0}, None, 64, 0.25098),
                 ({"p125": 1.0}, None, 192, 0.752941), ({}, exr, 0.25 * 255, 0.25), ({}, exr, 0.5 * 255, 0.5),
                 ({"p125": 2.2}, exr, 0.5 * 255, 0.217653))
        for params, table, grey, internal in cases:
            with self.subTest(params=params, grey=grey):
                tex = tx.TexmapConverter(FakeGraph(_cbitmap(1, **params)), _table() if table is None else table,
                                         swatches=colors.GAMMA_OFF)
                image = tex.convert(mat.MapRef(1), tx.COLOR).root
                self.assertLess(abs(drawn(grey / 255.0, image.gamma) - colors.srgb_to_linear(internal)), 0.02)
        tex = tx.TexmapConverter(FakeGraph(_cbitmap(1)), exr, swatches=colors.GAMMA_OFF)
        self.assertAlmostEqual(drawn(2.0, tex.convert(mat.MapRef(1), tx.COLOR).root.gamma),
                               colors.srgb_to_linear(2.0), delta=1e-9, msg="an EXR of 2.0: the extended curve")


class DataAndMaskRule(Checks):
    """maxdrop-em3.122, V-Ray 5.2 renders of a 128 grey PNG and grey 64 / red swatches (docs/FORMAT.md, Scene gamma):
    a map's value does not depend on its slot; a data input (glossiness, opacity) takes it as it is, a mask inside a
    color graph is decoded with the gamma off, as the color it mixes is. Gamma on: a Bitmap renders 0.2195 (auto,
    2.2) or 0.502 (1.0) on glossiness, opacity and as a mask; off: 0.502 whatever its override (Non-Color on a data
    input, decoded in a color graph). VRayColor 64 / red: 0.251 / 0.333 on glossiness and opacity in both modes."""

    ON_18 = colors.Swatches(True, file_in=1.8)
    RULES = (colors.GAMMA_ON, colors.GAMMA_OFF, colors.UNKNOWN)

    def _root(self, rule, *objects, kind=tx.COLOR, chunk_map=None):
        tex = tx.TexmapConverter(FakeGraph(*objects, chunk_map=chunk_map), _table(), swatches=rule)
        return tex.convert(mat.MapRef(objects[0].index), kind).root

    def test_data_constant_is_the_stored_mean(self):
        red, grey = (1.0, 0.0, 0.0), (64 / 255,) * 3
        for rule in self.RULES:
            for rgb, want in ((red, 1 / 3), (grey, 64 / 255), ((2.0, 0.5, 0.5), 2 / 3)):
                with self.subTest(rule=rule, rgb=rgb):
                    vc = FakeMap(1, classids.VRAY_COLOR, {5: rgb}, cls="VRayColor")
                    self.close(self._root(rule, vc, kind=tx.DATA).value, want, "glossiness, opacity: as stored")
                    self.close(self._root(rule, vc, kind=tx.BUMP).input.value, want, "a height: as stored")
                    own = FakeMap(1, tx.MIX, {4: rgb, 5: rgb}, cls="Mix")
                    self.close(self._root(rule, own, kind=tx.DATA).a.value, want)

    def test_mask_constant_by_the_graph(self):
        grey = (64 / 255,) * 3
        mix = FakeMap(1, tx.MIX, {8: Ref(2)}, [2], cls="Mix")
        vc = FakeMap(2, classids.VRAY_COLOR, {5: grey}, cls="VRayColor")
        for rule in self.RULES:
            with self.subTest(rule):
                self.close(self._root(rule, mix, vc).mask.value, rule.channel(64 / 255),
                           "in a color graph: the rule (maxdrop-em3.36)")
                self.close(self._root(rule, mix, vc, kind=tx.DATA).mask.value, 64 / 255, "in a data graph: stored")

    def test_bitmap_on_a_data_input(self):
        cases = ((colors.GAMMA_ON, None, None, tx.SRGB), (colors.UNKNOWN, None, None, tx.SRGB),
                 (colors.GAMMA_ON, _info(2.2, 5), 2.2, tx.SRGB), (colors.GAMMA_ON, _info(1.0, 5), 1.0, tx.NON_COLOR),
                 (self.ON_18, None, 1.8, tx.LINEAR),
                 (colors.GAMMA_OFF, None, None, tx.NON_COLOR), (colors.GAMMA_OFF, _info(2.2, 5), None, tx.NON_COLOR),
                 (colors.GAMMA_OFF, _info(1.0, 5), None, tx.NON_COLOR))
        for rule, info, gamma, space in cases:
            with self.subTest(rule=rule, info=info):
                b, chunk_map = _placed(info=info)
                image = self._root(rule, b, kind=tx.DATA, chunk_map=chunk_map)
                self.assertEqual(image.colorspace, space)
                self.assertEqual(image.gamma is None, gamma is None)
                if gamma is not None:
                    self.close(image.gamma, gamma)

    def test_bitmap_mask(self):
        mix = FakeMap(1, tx.MIX, {8: Ref(2)}, [2], cls="Mix")
        for rule, info, space in ((colors.GAMMA_ON, None, tx.SRGB), (colors.GAMMA_ON, _info(1.0, 5), tx.NON_COLOR),
                                  (colors.GAMMA_OFF, None, MEAN), (colors.GAMMA_OFF, _info(1.0, 5), MEAN)):
            with self.subTest(rule=rule, info=info):
                b, chunk_map = _placed(index=2, info=info)
                mask = self._root(rule, mix, b, chunk_map=chunk_map).mask
                if space == MEAN:  # gamma off: its stored mean, decoded (maxdrop-6n0.6.36)
                    self.assertTrue(isinstance(mask, tx.Decode) and mask.mean)
                    mask, space = mask.input, tx.NON_COLOR
                self.assertEqual(mask.colorspace, space)
        b, chunk_map = _placed(index=2)
        self.assertEqual(self._root(colors.GAMMA_OFF, mix, b, kind=tx.DATA, chunk_map=chunk_map).mask.colorspace,
                         tx.NON_COLOR, "a mask in a data graph: data")
        cmix = _cmix(1, [2], p200=6, p210=Ref(2))
        for kind in (tx.COLOR, tx.DATA):  # COLOR: on stored values under a Decode, the mask as data (em3.165)
            root = self._root(colors.GAMMA_OFF, cmix, _bitmap(2), kind=kind)
            root = root.input if kind == tx.COLOR else root
            self.assertEqual(tx.first_image(root.mask).colorspace, tx.NON_COLOR, "CoronaMix mask")
        root = self._root(colors.GAMMA_ON, cmix, _bitmap(2))
        self.assertEqual(tx.first_image(root.mask).colorspace, tx.SRGB, "gamma on: decoded")

    def test_colored_image_as_a_gamma_off_mask_is_its_decoded_mean(self):
        """maxdrop-6n0.6.36 (measured in maxdrop-6n0.6.2, V-Ray 5.2): with the gamma off a (200, 100, 50) PNG as the
        mask of a Mix black -> white renders 0.4575 internal (the mean of the stored pixel), shown 0.1768 linear; the
        mean of its decoded channels (0.2456) masked too much. Gamma on: the decoded mean (0.2456 vs 0.2471)."""
        mix = FakeMap(1, tx.MIX, {8: Ref(2)}, [2], cls="Mix")
        stored = (_bitmap(2), _vbitmap(2, p25=3))  # a Bitmap, a VRayBitmap From 3ds Max: read as stored
        for leaf in stored:
            with self.subTest(leaf.cls):
                mask = self._root(colors.GAMMA_OFF, mix, leaf).mask
                self.assertIsInstance(mask, tx.Decode)
                self.assertTrue(mask.mean)
                self.assertEqual((mask.input.colorspace, mask.input.gamma, mask.input.name), (tx.NON_COLOR, None,
                                                                                            "a.png"))
                self.assertIsInstance(self._root(colors.GAMMA_ON, mix, leaf).mask, tx.Image, "gamma on: as before")
                self.assertIsInstance(self._root(colors.GAMMA_OFF, mix, leaf, kind=tx.DATA).mask, tx.Image,
                                      "a mask in a data graph: data")
        # their own decode, shown decoded once more (_shown), is kept: no mean
        for leaf in (_vbitmap(2, p25=2), _vbitmap(2, p25=0), _cbitmap(2)):
            with self.subTest(leaf.cls, params=leaf.blocks[0]._params):
                self.assertIsInstance(self._root(colors.GAMMA_OFF, mix, leaf).mask, tx.Image)
        # a mono output of alpha: Blender never decodes an alpha, left as it was
        alpha = FakeMap(2, classids.BITMAP_TEX, {13: pblock.Asset(G1), tx.BM_MONO: 1}, cls="Bitmap")
        mask = self._root(colors.GAMMA_OFF, mix, alpha).mask
        self.assertIsInstance(mask, tx.Image)
        self.assertTrue(mask.alpha)

    def test_image_below_a_mask_wrapper_is_unchanged(self):
        # below an RGB Tint or an Output in a gamma-off mask the image is STORED (_wrapper_input) and the wrapper's
        # mean decoded (_mask_mean): one mean, the wrapper's
        mix = FakeMap(1, tx.MIX, {8: Ref(2)}, [2], cls="Mix")
        mask = self._root(colors.GAMMA_OFF, mix, _wtint(2, 3), _bitmap(3)).mask
        self.assertTrue(isinstance(mask, tx.Decode) and mask.mean)
        self.assertIsInstance(mask.input, tx.Tint)
        self.assertIsInstance(tx.first_image(mask), tx.Image)
        self.assertEqual(len(_decodes(mask)), 1)

    def test_stored_image_inside_a_mask_graph(self):
        """maxdrop-6n0.6.36 inside a mask: with the gamma off a stored image below a map that keeps the MASK kind
        (RGB Multiply) is its decoded mean, as a swatch there is the rule of its mean (not measured); a Falloff is
        computed on the held values, the mean of it decoded, and a Color Correction picks from the stored color
        (STORED), its mean decoded after it, as a Tint does (V-Ray 5.2, maxdrop-6n0.6.18); with the gamma on each is
        as before (the image sRGB)."""
        mix = FakeMap(1, tx.MIX, {8: Ref(2)}, [2], cls="Mix")

        def cc(rewire):
            params = {1: Ref(3)}
            if rewire:
                params.update({tx.CC_REWIRE_MODE: 3, 3: 0, 4: 0, 5: 0})  # custom: red, red, red
            return FakeMap(2, tx.COLOR_CORRECTION, params, [3], cls="Color Correction", name="cc")
        mul = FakeMap(2, tx.RGB_MULTIPLY, {2: Ref(3), 4: 1}, [3], cls="RGB Multiply")
        off = self._root(colors.GAMMA_OFF, mix, mul, _bitmap(3)).mask.a
        self.assertTrue(isinstance(off, tx.Decode) and off.mean, off)
        self.assertEqual(off.input.colorspace, tx.NON_COLOR)
        off = self._root(colors.GAMMA_OFF, mix, _falloff(2, 3), _bitmap(3)).mask
        self.assertTrue(isinstance(off, tx.Decode) and off.mean, off)
        self.assertEqual((type(off.input.a), off.input.a.colorspace), (tx.Image, tx.NON_COLOR), "as stored")
        off = self._root(colors.GAMMA_OFF, mix, cc(False), _bitmap(3)).mask
        self.assertTrue(isinstance(off, tx.Decode) and off.mean, off)
        self.assertEqual(off.input.input.colorspace, tx.NON_COLOR, "the mean of the held color, decoded")
        for what, wrapper, field in (("RGB Multiply", mul, "a"), ("Falloff", _falloff(2, 3), "a"),
                                     ("Color Correction", cc(False), "input")):
            with self.subTest(what):
                on = getattr(self._root(colors.GAMMA_ON, mix, wrapper, _bitmap(3)).mask, field)
                self.assertEqual((type(on), on.colorspace), (tx.Image, tx.SRGB))
        off = self._root(colors.GAMMA_OFF, mix, cc(True), _bitmap(3)).mask
        self.assertTrue(isinstance(off, tx.Decode) and off.mean, off)
        picked = off.input
        self.assertEqual((type(picked), picked.rewire), (tx.ColorCorrect, (0, 0, 0)))
        self.assertEqual((type(picked.input), picked.input.colorspace), (tx.Image, tx.NON_COLOR), "as stored")
        on = self._root(colors.GAMMA_ON, mix, cc(True), _bitmap(3)).mask
        self.assertEqual((type(on), on.rewire, on.input.colorspace), (tx.ColorCorrect, (0, 0, 0), tx.SRGB))

    def test_composite_mask_follows_the_graph(self):
        comp = FakeMap(1, tx.COMPOSITE, {9: [Ref(2), Ref(3)], 10: [Ref(None), Ref(4)]}, [2, 3, 4], cls="Composite")
        for rule, kind, space in ((colors.GAMMA_ON, tx.COLOR, tx.SRGB), (colors.GAMMA_OFF, tx.DATA, tx.NON_COLOR),
                                  (colors.GAMMA_OFF, tx.COLOR, tx.NON_COLOR)):  # off: as stored (em3.158)
            root = self._root(rule, comp, _bitmap(2), _bitmap(3), _bitmap(4), kind=kind)
            root = root.input if isinstance(root, tx.Decode) else root
            self.assertEqual(root.layers[1].mask.colorspace, space, (rule, kind))

    def test_vray_and_corona_bitmaps_on_a_data_input(self):
        # gamma off: CoronaBitmap auto / 2.2 renders 0.2195, VRayBitmap sRGB 0.2159 (their own curve), VRayBitmap
        # From 3ds Max and None 0.502; gamma on: From 3ds Max 0.2195, the others as off
        cases = ((_vbitmap(1, p25=2), tx.SRGB, tx.SRGB), (_vbitmap(1, p25=3), tx.NON_COLOR, tx.SRGB),
                 (_vbitmap(1, p25=0), tx.NON_COLOR, tx.NON_COLOR), (_cbitmap(1), tx.SRGB, tx.SRGB),
                 (_cbitmap(1, p125=2.2), tx.SRGB, tx.SRGB), (_cbitmap(1, p125=1.0), tx.NON_COLOR, tx.NON_COLOR),
                 (_vbitmap(1, p25=1, p8=2.0), tx.LINEAR, tx.LINEAR))  # inverse gamma 2: pixel ^ 0.5
        for m, off, on in cases:
            with self.subTest(cls=m.cls, params=m.blocks[0]._params):
                self.assertEqual(self._root(colors.GAMMA_OFF, m, kind=tx.DATA).colorspace, off)
                self.assertEqual(self._root(colors.GAMMA_ON, m, kind=tx.DATA).colorspace, on)


class NormalAndBumpImages(Checks):
    """maxdrop-em3.159, V-Ray 5.2 and Corona 12 renders of 8-bit normal and height PNGs (docs/FORMAT.md, Scene
    gamma): a normal or bump input takes an image as a data input does (em3.122). A Bitmap is decoded by its gamma
    with the gamma on (a flat (128, 128, 255) under auto or 2.2 renders (-0.44, -0.44, 0.78)) and as stored with 1.0
    or with the gamma off; a CoronaBitmap by its own gamma in both modes; a VRayBitmap under a normal map as stored
    whatever its transfer function, as a height by it (From 3ds Max as stored with the gamma off). CoronaNormal's add
    gamma re-encodes its input by 1 / 2.2 with the gamma on and does nothing with it off."""

    ON_18 = colors.Swatches(True, file_in=1.8)
    NORMAL_MAPS = (lambda n: _vnormal(1, n),
                   lambda n: FakeMap(1, tx.NORMAL_BUMP, {2: Ref(n), 4: 1, 0: 1.0}, [n], cls="Normal Bump"))

    def _convert(self, rule, *objects, kind=tx.NORMAL, chunk_map=None):
        tex = tx.TexmapConverter(FakeGraph(*objects, chunk_map=chunk_map), _table(), swatches=rule)
        return tex.convert(mat.MapRef(objects[0].index), kind)

    def _image(self, rule, *objects, kind=tx.NORMAL, chunk_map=None):
        return tx.first_image(self._convert(rule, *objects, kind=kind, chunk_map=chunk_map).root)

    def test_bitmap_takes_the_data_rule(self):
        cases = ((colors.GAMMA_ON, None, None, tx.SRGB), (colors.UNKNOWN, None, None, tx.SRGB),
                 (colors.GAMMA_ON, _info(2.2, 5), 2.2, tx.SRGB), (colors.GAMMA_ON, _info(1.0, 5), 1.0, tx.NON_COLOR),
                 (self.ON_18, None, 1.8, tx.LINEAR),
                 (colors.GAMMA_OFF, None, None, tx.NON_COLOR), (colors.GAMMA_OFF, _info(2.2, 5), None, tx.NON_COLOR),
                 (colors.GAMMA_OFF, _info(1.0, 5), None, tx.NON_COLOR))
        for rule, info, gamma, space in cases:
            for kind in (tx.BUMP, tx.NORMAL):
                for wrap in self.NORMAL_MAPS if kind == tx.NORMAL else (None,):
                    with self.subTest(rule=rule, info=info, kind=kind, wrap=wrap):
                        b, chunk_map = _placed(index=2 if wrap else 1, info=info)
                        objects = (wrap(2), b) if wrap else (b,)
                        image = self._image(rule, *objects, kind=kind, chunk_map=chunk_map)
                        self.assertEqual(image.colorspace, space)
                        self.assertEqual(image.gamma is None, gamma is None)
                        if gamma is not None:
                            self.close(image.gamma, gamma)

    def test_bitmap_below_a_normal_map_in_a_bump_input(self):
        b, chunk_map = _placed(index=2)
        vn = FakeMap(1, classids.VRAY_NORMAL_MAP, {4: Ref(2), 5: 1, 6: 1.0}, [2], cls="VRayNormalMap")
        for rule, space in ((colors.GAMMA_ON, tx.SRGB), (colors.GAMMA_OFF, tx.NON_COLOR)):
            with self.subTest(rule=rule):
                self.assertEqual(self._image(rule, vn, b, chunk_map=chunk_map).colorspace, space)

    def test_corona_bitmap_by_its_own_gamma(self):
        for rule in (colors.GAMMA_ON, colors.GAMMA_OFF):
            for params, space in (({}, tx.SRGB), ({"p125": 2.2}, tx.SRGB), ({"p125": 1.0}, tx.NON_COLOR)):
                for kind in (tx.NORMAL, tx.BUMP):
                    with self.subTest(rule=rule, params=params, kind=kind):
                        image = _cbitmap(2 if kind == tx.NORMAL else 1, **params)
                        objects = (_vnormal(1, 2), image) if kind == tx.NORMAL else (image,)
                        self.assertEqual(self._image(rule, *objects, kind=kind).colorspace, space)

    def test_vray_bitmap_under_a_normal_map_as_stored(self):
        for rule in (colors.GAMMA_ON, colors.GAMMA_OFF):
            for space in (0, 1, 2, 3, 4):
                for wrap in self.NORMAL_MAPS:
                    with self.subTest(rule=rule, space=space, wrap=wrap):
                        g = self._convert(rule, wrap(2), _vbitmap(2, p25=space, p8=0.5))
                        image = tx.first_image(g.root)
                        self.assertEqual(image.colorspace, tx.NON_COLOR)
                        self.assertEqual(image.gamma, 1.0)
                        self.assertEqual(g.issues, (), "its transfer function is not used: no issue")

    def test_vray_bitmap_height_by_its_transfer_function(self):
        cases = ((2, tx.SRGB, tx.SRGB), (3, tx.NON_COLOR, tx.SRGB), (0, tx.NON_COLOR, tx.NON_COLOR))
        for space, off, on in cases:
            with self.subTest(space=space):
                self.assertEqual(self._image(colors.GAMMA_OFF, _vbitmap(1, p25=space), kind=tx.BUMP).colorspace, off)
                self.assertEqual(self._image(colors.GAMMA_ON, _vbitmap(1, p25=space), kind=tx.BUMP).colorspace, on)

    def _cnormal(self, add, child=2):
        return FakeMap(1, tx.CORONA_NORMAL, {500: Ref(child), 501: 1.0, 502: int(add)}, [child], cls="CoronaNormal")

    def test_corona_normal_add_gamma_with_the_gamma_on(self):
        b, chunk_map = _placed(index=2)
        cases = (((b,), chunk_map, tx.NON_COLOR, 1.0), ((_cbitmap(2),), None, tx.NON_COLOR, 1.0),
                 ((_cbitmap(2, p125=1.0),), None, tx.LINEAR, 1 / 2.2),
                 ((_cbitmap(2, p125=2.2),), None, tx.NON_COLOR, 1.0))
        for objects, cm, space, gamma in cases:
            with self.subTest(cls=objects[0].cls, params=objects[0].blocks[0]._params):
                g = self._convert(colors.GAMMA_ON, self._cnormal(True), *objects, chunk_map=cm)
                self.assertEqual(g.root.input.colorspace, space)
                self.close(g.root.input.gamma, gamma)
                self.assertEqual(g.issues, ())
                self.assertIs(tx.drawn_gamma(g.root.input) is not None, space == tx.LINEAR)
        b1, cm1 = _placed(index=2, info=_info(1.0, 5))
        g = self._convert(colors.GAMMA_ON, self._cnormal(True), b1, chunk_map=cm1)
        self.assertEqual((g.root.input.colorspace, g.root.input.gamma), (tx.LINEAR, 1 / 2.2), "1.0: brighter")
        g = self._convert(colors.GAMMA_ON, self._cnormal(False), _cbitmap(2))
        self.assertEqual(g.root.input.colorspace, tx.SRGB, "add gamma off: decoded")

    def test_corona_normal_add_gamma_with_the_gamma_off_does_nothing(self):
        b, chunk_map = _placed(index=2)
        for objects, cm, space in (((b,), chunk_map, tx.NON_COLOR), ((_cbitmap(2),), None, tx.SRGB)):
            with self.subTest(cls=objects[0].cls):
                g = self._convert(colors.GAMMA_OFF, self._cnormal(True), *objects, chunk_map=cm)
                self.assertEqual(g.root.input.colorspace, space)
                self.assertEqual(g.issues, ())

    def test_corona_normal_add_gamma_over_a_graph_is_reported(self):
        mix = FakeMap(2, tx.MIX, {6: Ref(3)}, [3], cls="Mix")
        g = self._convert(colors.GAMMA_ON, self._cnormal(True), mix, _cbitmap(3))
        self.assertTrue(any("add gamma" in r for r in g.issues), g.issues)

    def test_corona_normal_add_gamma_not_folded_past_an_output_or_alpha(self):
        # the builder applies an image's gamma before its Output and not to its alpha: Corona's re-encode comes after
        for child in (_vbitmap(2, p25=2, p1=2.0), _cbitmap(2, p118=1)):
            with self.subTest(cls=child.cls):
                g = self._convert(colors.GAMMA_ON, self._cnormal(True), child)
                self.assertIn(g.root.input.gamma, (None, 1.0), "left as without add gamma")
                self.assertTrue(any("add gamma" in r for r in g.issues), g.issues)

    def test_vray_bitmap_below_a_corona_normal_that_adds_gamma(self):
        g = self._convert(colors.GAMMA_ON, self._cnormal(True), _vbitmap(2, p25=2))
        self.assertEqual((g.root.input.colorspace, g.root.input.gamma), (tx.LINEAR, 1 / 2.2), "stored, raised")
        self.assertEqual(g.issues, ())


if __name__ == "__main__":
    unittest.main()
