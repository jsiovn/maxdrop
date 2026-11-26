# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/texmaps/, the texture-map rules: no Blender. vray_maps' slots against the values its
authoring script sets (tools/fixtures/vray_maps.ms), texmap_rules' peels, kept wrappers, normal maps and Bitmap
placement against tools/fixtures/texmap_rules.ms, the ClassIDs against that fixture's class directory, the wiring
into materials/, and the guards on synthetic maps.

    python -I -m unittest discover tests
"""
import collections
import os
import struct
import sys
import time
import types
import unittest

_TESTS = "maxdrop_unit_tests"  # tests/unit as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_unit_tests.texmaps_support import (  # noqa: E402 (after the loader)
    _bitmap, _falloff, _image, _info, _lin, _noise, _placed, _table, _tex, assets, Checks, chunks,
    classids, colors, DEG, FakeChunk, FakeGraph, FakeMap, Fixture, G1, mat, reader_materials, Ref, tx,
)


class VRayMaps(Checks):
    """vray_maps.ms: FixtureVRayMaps' five bitmaps (tile, tile + 0.5, offset, offset + 0.05, angle) and multipliers
    91 / 82 / 73 / 64 / 55 %; FixtureVRayNormal's VRayNormalMap."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("vray_maps")

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def test_diffuse(self):
        ir = self.f.irs["FixtureVRayMaps"]
        g = ir.textures["base_color"]
        self.assertEqual(g.kind, tx.COLOR)
        self.assertFalse(g.approximated)
        held = self.held(g.root, "gamma off: the slot's amount mixes the stored values (maxdrop-6n0.6.18)")
        self.assertIsInstance(held, tx.Mix)
        self.close(held.factor, 0.91)
        self.close(held.a.value, tuple(c / 255 for c in (180, 120, 60)))
        self.image(held.b, "fixture_diffuse.png", tx.NON_COLOR, (2.0, 2.5), (0.1, 0.15), 15.0)
        self.close(held.b.mapping.blur, 1.1)
        self.assertIsNone(held.b.crop)
        self.assertIsNone(held.b.gamma)

    def test_reflection_is_the_specular(self):
        held = self.held(self.f.irs["FixtureVRayMaps"].textures["specular"].root)
        self.close(held.factor, 0.82)
        self.close(held.a.value, (0.0, 0.0, 0.0))  # the float input's value, as RGB in a color graph
        self.image(held.b, "fixture_reflect.png", tx.NON_COLOR, (3.0, 3.5), (0.2, 0.25), 25.0)

    def test_glossiness_is_inverted(self):
        g = self.f.irs["FixtureVRayMaps"].textures["roughness"]
        self.assertEqual(g.kind, tx.DATA)
        self.close(g.root.factor, 0.73)
        self.close(g.root.a.value, 0.0)  # glossiness 1.0
        self.assertIsInstance(g.root.b, tx.Invert)
        self.image(g.root.b.input, "fixture_gloss.png", tx.NON_COLOR, (4.0, 4.5), (0.3, 0.35), 35.0)

    def test_bump(self):
        g = self.f.irs["FixtureVRayMaps"].textures["bump"]
        self.assertIsInstance(g.root, tx.Bump)
        self.close(g.root.strength, 0.64)
        self.image(g.root.input, "fixture_bump.png", tx.NON_COLOR, (5.0, 5.5), (0.4, 0.45), 45.0)

    def test_opacity(self):
        g = self.f.irs["FixtureVRayMaps"].textures["alpha"]
        self.close(g.root.factor, 0.55)
        self.close(g.root.a.value, 1.0)
        self.image(g.root.b, "fixture_opacity.png", tx.NON_COLOR, (6.0, 6.5), (0.5, 0.55), 55.0)

    def test_only_the_slots_with_maps(self):
        self.assertEqual(sorted(self.f.irs["FixtureVRayMaps"].textures),
                         ["alpha", "base_color", "bump", "roughness", "specular"])

    def test_vray_normal_map(self):
        ir = self.f.irs["FixtureVRayNormal"]
        self.assertEqual(sorted(ir.textures), ["normal"])
        n = ir.textures["normal"].root
        self.assertIsInstance(n, tx.NormalMap)
        self.close(n.strength, 0.85)  # material bump 100 % x normal_map_multiplier 0.85
        self.assertTrue(n.flip_green)
        self.assertFalse(n.flip_red)
        self.image(n.input, "fixture_normal.png", tx.NON_COLOR, (1.5, 2.0), (0.05, 0.1), 5.0)
        self.close(n.bump.strength, 0.35)
        self.image(n.bump.input, "fixture_normal_bump.png", tx.NON_COLOR, (2.5, 3.0), (0.15, 0.2), 65.0)

    def test_nothing_peeled_or_reported(self):
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter())
        self.assertEqual(self.f.tex.stats.unsupported, collections.Counter())
        self.assertEqual(self.f.tex.stats.issues, [])


class TexmapRules(Checks):
    """texmap_rules.ms."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("texmap_rules")

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def test_class_ids_match_the_class_directory(self):
        names = {(e.superclass, e.class_id): e.name for e in (self.f.scene.entry(i) for i in range(len(self.f.scene)))
                 if e is not None}
        expected = {tx.FALLOFF: "Falloff", tx.VRAY_DIRT: "VRayDirt", tx.VRAY_COLOR2BUMP: "VRayColor2Bump",
                    tx.OUTPUT: "Output", tx.RGB_TINT: "RGB Tint", tx.MIX: "Mix", tx.RGB_MULTIPLY: "RGB Multiply",
                    tx.COLOR_CORRECTION: "Color Correction", tx.COMPOSITE: "Composite",
                    tx.NORMAL_BUMP: "Normal Bump", tx.CORONA_NORMAL: "CoronaNormal"}
        for cid, name in expected.items():
            self.assertEqual(names.get((classids.SC_TEXMAP, cid)), name, name)

    def test_peeled_to_the_bitmap_below(self):
        t = self.f.irs["FixtureTexPeel"].textures
        fo = self.held(t["base_color"].root)  # Falloff, perpendicular / parallel: map 1 to color 2, as held
        self.assertIsInstance(fo, tx.Mix)
        self.assertEqual(fo.mask, tx.Facing(tx.PERPENDICULAR, 1.6))
        self.image(fo.a, "peel_diffuse.png", tx.NON_COLOR)
        self.close(fo.b.value, tuple(c / 255 for c in (10, 20, 30)))
        spec = self.held(t["specular"].root)  # VRayDirt, at 80 %: the slot's amount on the held values
        self.image(spec.b, "peel_reflect.png", tx.NON_COLOR)
        self.close(spec.factor, 0.8)
        self.assertIsInstance(t["roughness"].root, tx.Invert)  # Output, a glossiness map
        self.image(t["roughness"].root.input, "peel_gloss.png", tx.NON_COLOR)
        self.assertIsInstance(t["bump"].root, tx.Bump)  # VRayColor2Bump: a height map
        self.close(t["bump"].root.strength, 0.4)
        self.image(t["bump"].root.input, "peel_height.png", tx.NON_COLOR)
        self.image(t["alpha"].root, "peel_opacity.png", tx.NON_COLOR)  # RGB Tint, its identity
        for name in ("specular", "bump"):
            self.assertTrue(t[name].approximated, name)
        for name in ("base_color", "roughness", "alpha", "metallic", "emission_color"):
            self.assertFalse(t[name].approximated, name)

    def test_peels_are_counted_once_per_map(self):
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter({"VRayDirt": 1, "VRayColor2Bump": 1}))
        self.assertEqual(self.f.tex.stats.unsupported, collections.Counter())

    def test_falloff_without_a_map_is_its_colors(self):
        t = self.f.irs["FixtureTexPeel"].textures
        g = t["metallic"].root  # a data input: the mean of each swatch as stored, the gamma is off (em3.122)
        self.close((g.a.value, g.b.value), ((200 + 100 + 50) / 3.0 / 255.0, 1.0))
        g = self.held(t["emission_color"].root)  # map1 switched off: color1
        self.close(g.a.value, (1.0, 0.0, 0.0))
        self.close(g.b.value, (1.0, 1.0, 1.0))
        self.assertIsInstance(g.mask, tx.Facing)

    def test_kept_wrappers(self):
        t = self.f.irs["FixtureTexKeep"].textures
        decoded = t["base_color"].root  # gamma off: mixed on the stored values, shown decoded (em3.158)
        self.assertIsInstance(decoded, tx.Decode)
        mix = decoded.input
        self.assertIsInstance(mix, tx.Mix)
        self.close(mix.factor, 0.3)
        self.image(mix.a, "keep_mix_a.png", tx.NON_COLOR)  # Bitmaps as stored
        self.image(mix.b, "keep_mix_b.png", tx.NON_COLOR)
        self.image(mix.mask, "keep_mix_mask.png", tx.NON_COLOR)
        mul = t["specular"].root
        self.assertIsInstance(mul, tx.Multiply)
        self.image(mul.a, "keep_mul.png", tx.SRGB)
        self.close(mul.b.value, tuple(_lin(c) for c in (200, 150, 100)))
        cc = self.held(t["emission_color"].root)  # on the held values (maxdrop-6n0.6.18)
        self.assertIsInstance(cc, tx.ColorCorrect)
        self.close(cc.hue, 30.0 / 360.0)
        self.close(cc.saturation, 1.2)
        self.close(cc.brightness, 0.0)  # brightness 10 and contrast 5 are set, but lightness is advanced
        self.close(cc.contrast, 0.0)
        self.close(cc.gain, 1.0)
        self.close(cc.gamma, 1.2)
        self.image(cc.input, "keep_cc.png", tx.NON_COLOR)
        for name in ("base_color", "specular", "emission_color"):
            self.assertFalse(t[name].approximated, name)

    def test_gamma_override_on_a_data_input(self):
        g = self.f.irs["FixtureTexKeep"].textures["roughness"].root
        self.assertIsInstance(g, tx.Invert)
        self.image(g.input, "keep_gloss.png", tx.NON_COLOR)
        self.close(reader_materials.bitmap_gamma(self.f.scene, self.f.graph.get(g.input.index)), 1.0)
        self.assertIsNone(g.input.gamma, "saved with the gamma off: read as stored whatever the override")

    def test_normal_bump_is_the_normal_input(self):
        ir = self.f.irs["FixtureTexKeep"]
        self.assertIsNotNone(ir.normal)
        self.assertIsNone(ir.bump)
        n = ir.textures["normal"].root
        self.assertIsInstance(n, tx.NormalMap)
        self.close(n.strength, 0.8 * 0.3)  # mult_spin x the material's default bump amount, 30 %
        self.assertTrue(n.flip_green)
        self.image(n.input, "keep_normal.png", tx.NON_COLOR)
        self.close(n.bump.strength, 0.4 * 0.3)
        self.image(n.bump.input, "keep_nb_bump.png", tx.NON_COLOR)

    def test_composite(self):
        c = self.f.irs["FixtureTexPlace"].textures["base_color"].root
        self.assertIsInstance(c, tx.Decode)  # gamma off: composited on the stored values (em3.158)
        c = c.input
        self.assertIsInstance(c, tx.Composite)
        self.assertEqual([la.node.name for la in c.layers], ["place_comp_a.png", "place_comp_b.png"])
        self.close(tuple(la.opacity for la in c.layers), (1.0, 0.6))
        self.assertEqual([(la.blend, la.mask) for la in c.layers], [(0, None), (0, None)])

    def test_crop_channel_mirror_angles_gamma(self):
        i = self.f.irs["FixtureTexPlace"].textures["specular"].root
        self.image(i, "place_crop.png", tx.SRGB, (2.0, 3.0), (0.0, 0.0), 30.0, channel=3)
        self.close(i.mapping.angle, (10.0 * DEG, 20.0 * DEG, 30.0 * DEG))
        self.assertEqual(i.mapping.tile, (False, False))  # U mirrors (not tiles), V tiling off
        self.assertEqual(i.mapping.mirror, (True, False))
        self.assertEqual(i.mapping.source, tx.EXPLICIT)
        self.close((i.crop.u, i.crop.v, i.crop.w, i.crop.h), (0.1, 0.2, 0.5, 0.6))
        self.assertFalse(i.crop.place)
        self.close(reader_materials.bitmap_gamma(self.f.scene, self.f.graph.get(i.index)), 2.2)
        self.assertIsNone(i.gamma, "saved with the gamma off: read as stored whatever the override")

    def test_placement_on_the_vertex_color_channel(self):
        i = self.f.irs["FixtureTexPlace"].textures["alpha"].root
        self.assertTrue(i.crop.place)
        self.close((i.crop.u, i.crop.v, i.crop.w, i.crop.h), (0.25, 0.25, 0.5, 0.5))
        self.assertEqual(i.mapping.source, tx.VERTEX_COLOR)
        self.assertEqual(i.mapping.channel, 0)

    def test_environment_mapping_is_an_issue(self):
        g = self.f.irs["FixtureTexPlace"].textures["emission_color"]
        self.assertTrue(g.root.mapping.environment)
        self.assertEqual(len(g.issues), 1)
        self.assertIn("environment mapping", g.issues[0])
        self.assertIn(g.issues[0], self.f.irs["FixtureTexPlace"].issues)

    def test_inverted_output(self):
        i = self.f.irs["FixtureTexPlace"].textures["metallic"].root
        self.assertEqual(i.output, tx.TexOutput(invert=True))

    def test_corona_normal(self):
        ir = self.f.irs["FixtureTexPlace"]
        self.assertIsNone(ir.bump)
        n = ir.textures["normal"].root
        self.close(n.strength, 0.9 * 0.3)
        self.assertTrue(n.flip_green)
        self.image(n.input, "place_cnormal.png", tx.NON_COLOR)
        self.close(n.bump.strength, 0.5 * 0.3)
        self.image(n.bump.input, "place_cbump.png", tx.NON_COLOR)

    def test_without_a_texmap_converter(self):
        conv = mat.MaterialConverter(self.f.graph)
        for n in self.f.scene.walk():
            ir = conv.convert(self.f.scene.node(n).material)
            self.assertEqual(ir.textures, {})


class Synthetic(Checks):
    def test_colorspace(self):
        self.assertEqual(tx.colorspace(tx.COLOR, None), tx.SRGB)
        self.assertEqual(tx.colorspace(tx.COLOR, 2.2), tx.SRGB)
        self.assertEqual(tx.colorspace(tx.COLOR, 1.0), tx.LINEAR)  # linear: the builder applies no gamma
        self.assertEqual(tx.colorspace(tx.COLOR, 1.8), tx.LINEAR)  # the builder applies 1.8
        self.assertEqual(tx.LINEAR, "Linear Rec.709")  # a Blender color space name: the builder sets it
        for kind in (tx.NORMAL, tx.BUMP):  # as a data input (maxdrop-em3.159)
            for gamma in (None, 2.2, 1.0, 1.8):
                self.assertEqual(tx.colorspace(kind, gamma, True), tx.NON_COLOR)
                self.assertEqual(tx.colorspace(kind, gamma), tx.colorspace(tx.DATA, gamma))
            self.assertEqual(tx.colorspace(kind, None), tx.SRGB)
            self.assertEqual(tx.colorspace(kind, 1.0), tx.NON_COLOR)
        for kind in (tx.DATA, tx.MASK):  # decoded by its gamma, as a color; read as linear: Non-Color
            for gamma in (None, 2.2, 1.8):
                self.assertEqual(tx.colorspace(kind, gamma), tx.colorspace(tx.COLOR, gamma))
            self.assertEqual(tx.colorspace(kind, 1.0), tx.NON_COLOR)
        self.assertEqual(tx.colorspace(tx.DATA, None, True), tx.NON_COLOR, "pixels as stored: data as they are")
        self.assertEqual(tx.colorspace(tx.MASK, None, True), tx.SRGB, "a mask in a color graph: decoded")

    def test_bitmap_without_chunks_takes_the_defaults(self):
        g = _tex(_bitmap(1)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertEqual(g.root.path, "maps\\a.png")
        self.assertEqual(g.root.mapping, tx.Mapping())
        self.assertIsNone(g.root.output)
        self.assertIsNone(g.root.gamma)

    def test_float_files_under_automatic_gamma_are_linear(self):
        for path in ("maps\\sky.EXR", "maps\\sky.hdr"):
            table = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", path, "")])
            g = _tex(_bitmap(1), table=table).convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual((g.root.gamma, g.root.colorspace), (1.0, tx.LINEAR), path)
        table = assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\sky.exr", "")])
        for info, gamma, space in ((_info(2.2, 5), 2.2, tx.SRGB), (_info(1.8, 5), 1.8, tx.LINEAR),
                                   (_info(2.2, 4), 1.0, tx.LINEAR),  # an override is kept; no flag: automatic
                                   (_info(50.0, 5), 1.0, tx.LINEAR)):  # out of range: automatic
            b, chunk_map = _placed(info=info)
            g = tx.TexmapConverter(FakeGraph(b, chunk_map=chunk_map), table).convert(mat.MapRef(1), tx.COLOR)
            self.close(g.root.gamma, gamma)
            self.assertEqual(g.root.colorspace, space, info.hex())
        g = _tex(_bitmap(1), table=table).convert(mat.MapRef(1), tx.DATA)
        self.assertEqual(g.root.colorspace, tx.NON_COLOR)  # read as linear: a data input takes it as it is
        g = _tex(_bitmap(1)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual((g.root.gamma, g.root.colorspace), (None, tx.SRGB), "an 8-bit file: still automatic")

    def test_bitmap_without_a_file(self):
        tex = _tex(_bitmap(1, guid=b"\xff" * 16))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertIn("no file", tex.stats.issues[0][1])
        tex = tx.TexmapConverter(FakeGraph(_bitmap(1)))  # no asset table at all
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))

    def test_texture_lookup(self):
        class Index:
            def find(self, path, resolved=""):
                return ("found", path, resolved)
        tex = tx.TexmapConverter(FakeGraph(_bitmap(1)), _table(), textures=Index())
        self.assertEqual(tex.convert(mat.MapRef(1), tx.COLOR).root.found, ("found", "maps\\a.png", ""))

    def test_cycle(self):
        tex = _tex(_falloff(1, 2), _falloff(2, 1, color1=(1.0, 1.0, 1.0)))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))  # 2's map1 is 1 again: the branch ends there
        self.assertTrue(any("cycle" in r for _i, r in tex.stats.issues))

    def test_depth_guard(self):
        objects = [_falloff(i, i + 1) for i in range(1, tx.MAX_DEPTH + 3)] + [_bitmap(tx.MAX_DEPTH + 3)]
        tex = _tex(*objects)
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertTrue(any("deeper than" in r for _i, r in tex.stats.issues))

    def test_reference_to_a_material(self):
        tex = _tex(_falloff(1, 2), FakeMap(2, classids.VRAY_MTL, superclass=classids.SC_MATERIAL))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertTrue(any("not a map" in r for _i, r in tex.stats.issues))

    def test_unknown_class_gives_the_first_bitmap_below(self):
        tex = _tex(FakeMap(1, (0x1234, 0), children=[2, 3], cls="Noise"), _falloff(2), _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.name, "a.png")
        self.assertTrue(g.approximated)
        self.assertEqual(tex.stats.peeled, collections.Counter({"Noise": 1}))

    def test_first_image_issues_reach_every_graph_that_peels_to_it(self):
        shared = FakeMap(5, (0x1234, 0), children=[6, 7], cls="Noise")  # its first bitmap has no file
        tex = _tex(FakeMap(10, (0x1235, 0), children=[5], cls="Cellular"),
                   FakeMap(20, (0x1236, 0), children=[5], cls="Smoke"), shared, _bitmap(6, guid=b"\xff" * 16),
                   _bitmap(7))
        for i in (10, 20):
            g = tex.convert(mat.MapRef(i), tx.COLOR)
            self.assertEqual(g.root.name, "a.png")
            self.assertTrue(any("no file" in r for r in g.issues), i)

    def test_unknown_class_without_a_bitmap(self):
        tex = _tex(FakeMap(1, (0x1234, 0), cls="Noise"))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertEqual(tex.stats.unsupported, collections.Counter({"Noise": 1}))

    def test_composite_with_a_mask(self):
        comp = FakeMap(1, tx.COMPOSITE, {1: [1, 1], 3: [1, 1], 5: [0, 0], 8: [100.0, 50.0], 9: [Ref(2), Ref(3)],
                                         10: [Ref(None), Ref(4)]}, [2, 3, 4], cls="Composite")
        tex = _tex(comp, _bitmap(2), _bitmap(3), _bitmap(4))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Composite)
        self.assertFalse(g.approximated)
        bottom, top = g.root.layers
        self.assertIsNone(bottom.mask)
        self.assertEqual((top.opacity, top.blend), (0.5, 0))
        self.assertEqual(top.mask.colorspace, tx.SRGB, "a mask in a color graph: decoded by its gamma")
        self.assertEqual(tex.stats.peeled, collections.Counter())
        comp = FakeMap(1, tx.COMPOSITE, {3: [1, 0], 9: [Ref(2), Ref(3)], 10: [Ref(None), Ref(4)]}, [2, 3, 4])
        g = _tex(comp, _bitmap(2), _bitmap(3), _bitmap(4)).convert(mat.MapRef(1), tx.COLOR)
        self.assertIsNone(g.root.layers[1].mask, "mask switched off")
        comp = FakeMap(1, tx.COMPOSITE, {9: [Ref(2), Ref(3)], 10: [Ref(None), Ref(5)]}, [2, 3, 5], cls="Composite",
                       name="cp")
        tex = _tex(comp, _bitmap(2), _bitmap(3), _noise(5))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsNone(g.root.layers[1].mask, "a lost mask: the opacity alone")
        self.assertTrue(g.approximated)
        self.assertTrue(any("converts to nothing" in r for _i, r in tex.stats.issues))

    def test_composite_blend_modes(self):
        for mode in sorted(tx.BLENDS):
            comp = FakeMap(1, tx.COMPOSITE, {5: [14, mode], 9: [Ref(2), Ref(3)]}, [2, 3], cls="Composite")
            tex = _tex(comp, _bitmap(2), _bitmap(3))
            g = tex.convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual([la.blend for la in g.root.layers], [tx.NORMAL_BLEND, mode], "the bottom one is normal")
            self.assertEqual(tex.stats.peeled, collections.Counter())
        for mode in (tx.LINEAR_BURN, tx.SOFT_LIGHT, tx.PIN_LIGHT, tx.HARD_MIX, 25):
            comp = FakeMap(1, tx.COMPOSITE, {5: [0, mode], 9: [Ref(2), Ref(3)]}, [2, 3], cls="Composite")
            tex = _tex(comp, _bitmap(2), _bitmap(3))
            g = tex.convert(mat.MapRef(1), tx.COLOR)
            self.assertIsInstance(g.root, tx.Image, mode)
            self.assertEqual(tex.stats.peeled, collections.Counter({"Composite": 1}))

    def test_falloff_types_and_amounts(self):
        fo = FakeMap(1, tx.FALLOFF, {0: (0.0, 0.0, 0.0), 1: 60.0, 2: Ref(2), 3: 1, 4: (1.0, 1.0, 1.0), 5: 100.0,
                                     6: Ref(3), 7: 1, 8: 2, 9: 0, 11: 1, 12: 1.5}, [2, 3], cls="Falloff")
        tex = _tex(fo, _bitmap(2), _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertFalse(g.approximated)
        self.assertEqual(g.root.mask, tx.Facing(tx.FRESNEL, 1.5))
        self.close(g.root.factor, 0.0)
        side1, side2 = g.root.a, g.root.b
        self.assertIsInstance(side1, tx.Mix, "map amount 60: lerp(color 1, map 1, 0.6)")
        self.close(side1.factor, 0.6)
        self.close(side1.a.value, (0.0, 0.0, 0.0))
        self.assertIsInstance(side1.b, tx.Image)
        self.assertIsInstance(side2, tx.Image, "map amount 100: the map")
        for ftype, mode in ((0, tx.TOWARDS), (1, tx.PERPENDICULAR), (None, tx.PERPENDICULAR)):
            fo = FakeMap(1, tx.FALLOFF, {8: ftype}, cls="Falloff")
            self.assertEqual(_tex(fo).convert(mat.MapRef(1), tx.COLOR).root.mask, tx.Facing(mode, 1.6))
        fo = FakeMap(1, tx.FALLOFF, {8: 2, 11: 0, 12: 1.3}, cls="Falloff", name="f")
        tex = _tex(fo)
        self.assertEqual(tex.convert(mat.MapRef(1), tx.COLOR).root.mask, tx.Facing(tx.FRESNEL, 1.3))
        self.assertEqual([r for _i, r in tex.stats.issues], ["Falloff 'f': the material's IOR not read: its own, 1.3"])
        fo = FakeMap(1, tx.FALLOFF, {8: 2, 12: float("nan")}, cls="Falloff")
        self.assertEqual(_tex(fo).convert(mat.MapRef(1), tx.COLOR).root.mask, tx.Facing(tx.FRESNEL, 1.6))

    def test_falloff_in_a_reflection_slot(self):
        # the usual Fresnel-like reflection: a default Falloff, black to white, no maps, converted as texture_graphs
        # converts a specular input (a color graph, the input's own value a float)
        tex = _tex(FakeMap(1, tx.FALLOFF, {}, cls="Falloff"))
        g = tex.convert(mat.MapRef(1), tx.COLOR, 0.0)
        black, white = tx.Constant((0.0, 0.0, 0.0)), tx.Constant((1.0, 1.0, 1.0))
        self.assertEqual(g.root, tx.Mix(black, white, 0.0, tx.Facing(tx.PERPENDICULAR)))
        self.assertEqual((g.approximated, g.issues), (False, ()))
        self.assertEqual((tex.stats.peeled, tex.stats.unsupported), (collections.Counter(), collections.Counter()))
        tex = _tex(FakeMap(1, tx.FALLOFF, {8: 2, 11: 1, 12: 1.5}, cls="Falloff"))
        g = tex.convert(mat.MapRef(1, amount=0.5), tx.COLOR, 0.0)
        self.assertEqual(g.root, tx.Mix(black, tx.Mix(black, white, 0.0, tx.Facing(tx.FRESNEL, 1.5)), 0.5))
        self.assertEqual((g.approximated, g.issues, tex.stats.peeled), (False, (), collections.Counter()))

    def test_falloff_other_types_and_directions_are_peeled(self):
        for params in ({8: 3}, {8: 4}, {8: 1, 9: 1}, {8: 7}):
            fo = FakeMap(1, tx.FALLOFF, {**params, 0: (1.0, 0.0, 0.0), 2: Ref(2), 3: 1}, [2], cls="Falloff")
            tex = _tex(fo, _bitmap(2))
            g = tex.convert(mat.MapRef(1), tx.COLOR)
            self.assertIsInstance(g.root, tx.Image, params)
            self.assertTrue(g.approximated)
            self.assertEqual(tex.stats.peeled, collections.Counter({"Falloff": 1}))
            self.assertTrue(any("drawn as its first side" in r for r in g.issues))
            fo = FakeMap(1, tx.FALLOFF, {**params, 0: (1.0, 0.0, 0.0)}, cls="Falloff")
            self.close(_tex(fo).convert(mat.MapRef(1), tx.COLOR).root.value, (1.0, 0.0, 0.0), "no map: color 1")

    def test_falloff_as_a_mask(self):
        fo = FakeMap(2, tx.FALLOFF, {}, cls="Falloff")
        mix = FakeMap(1, tx.MIX, {6: Ref(3), 7: Ref(4), 8: Ref(2)}, [2, 3, 4], cls="Mix")
        g = _tex(mix, fo, _bitmap(3), _bitmap(4)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.mask, tx.Mix(tx.Constant(0.0), tx.Constant(1.0), 0.0, tx.Facing()))

    def test_color_correction_rewiring(self):
        for params, want in (({2: 1}, tx.REWIRE_MONO), ({2: 2}, tx.REWIRE_INVERT), ({2: 0, 3: 2}, tx.REWIRE_NONE),
                             ({2: 3, 3: 2, 4: 1, 5: 0}, (2, 1, 0)), ({2: 3, 3: 8, 4: 9, 5: 10}, (8, 9, 10))):
            cc = FakeMap(1, tx.COLOR_CORRECTION, {**params, 1: Ref(2)}, [2], cls="Color Correction")
            g = _tex(cc, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual(g.root.rewire, want, params)
            self.assertFalse(g.approximated, params)
        cc = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 2: 3, 3: 3, 4: 7, 5: 2}, [2], name="cc")
        g = _tex(cc, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.rewire, (9, 10, 2), "alpha drawn as one, its inverse as zero")
        self.assertTrue(g.approximated)
        self.assertTrue(any("from alpha" in r for r in g.issues))
        for params in ({2: 3, 3: (2872,), 4: 1, 5: 2}, {2: 3, 3: 11, 4: 1, 5: 2}, {2: 5}):
            cc = FakeMap(1, tx.COLOR_CORRECTION, {**params, 1: Ref(2)}, [2], name="cc")
            g = _tex(cc, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual(g.root.rewire, tx.REWIRE_NONE, params)
            self.assertTrue(any("rewiring" in r for r in g.issues), params)

    def test_output_and_rgb_tint(self):
        out = FakeMap(1, tx.OUTPUT, {0: Ref(2)}, [2], cls="Output")
        part = FakeMap(5, (0x100, 0), superclass=classids.SC_TEXOUTPUT)
        part.legacy = {0: {0: 2.0, 1: 0.1, 2: 0.5}}
        out.parts = {2: part}
        g = _tex(out, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Adjust)
        self.assertEqual(g.root.output, tx.TexOutput(False, 0.5, 2.0, 0.1))
        self.assertFalse(g.approximated)
        tint = FakeMap(1, tx.RGB_TINT, {0: (1.0, 0.5, 0.0), 3: Ref(2)}, [2], cls="RGB Tint")
        tex = tx.TexmapConverter(FakeGraph(tint, _bitmap(2)), _table(), swatches=colors.GAMMA_ON)
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root, tx.Tint(g.root.input, (1.0, 0.5, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
        self.assertEqual((g.approximated, tex.stats.peeled), (False, collections.Counter()))
        tint = FakeMap(1, tx.RGB_TINT, {3: Ref(2)}, [2], cls="RGB Tint")
        self.assertIsInstance(_tex(tint, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR).root, tx.Image,
                              "the identity: the map")

    def test_slot_amounts(self):
        tex = _tex(_bitmap(1))
        g = tex.convert(mat.MapRef(1, 1.5), tx.DATA, 0.2)
        self.assertEqual(g.root, tx.Multiply(g.root.a, tx.Constant(1.5)))
        g = tex.convert(mat.MapRef(1, 0.25, invert=True), tx.DATA, 0.7)
        self.assertIsInstance(g.root, tx.Mix)
        self.assertEqual(g.root.a, tx.Constant(0.7))
        self.assertIsInstance(g.root.b, tx.Invert)
        self.close(g.root.factor, 0.25)
        g = tex.convert(mat.MapRef(1, 0.25), tx.BUMP)
        self.assertEqual(g.root.strength, 0.25)

    def test_slot_scale(self):
        """MapRef.scale (Standard's Diffuse Level on a diffuse map) multiplies the map before the amount mixes it with
        the input's value; 1 leaves the graph as it was."""
        tex = _tex(_bitmap(1))
        g = tex.convert(mat.MapRef(1, 1.0, False, 0.5), tx.COLOR, (0.4, 0.2, 0.1))
        self.assertEqual(g.root, tx.Multiply(g.root.a, tx.Constant((0.5, 0.5, 0.5))))
        self.assertIsInstance(g.root.a, tx.Image)
        g = tex.convert(mat.MapRef(1, 0.25, False, 0.5), tx.COLOR, (0.4, 0.2, 0.1))
        self.assertEqual((g.root.a, g.root.factor), (tx.Constant((0.4, 0.2, 0.1)), 0.25))
        self.assertEqual(g.root.b, tx.Multiply(g.root.b.a, tx.Constant((0.5, 0.5, 0.5))))
        self.assertEqual(tex.convert(mat.MapRef(1, 0.25, False, 1.0), tx.COLOR, (0.4, 0.2, 0.1)),
                         tex.convert(mat.MapRef(1, 0.25), tx.COLOR, (0.4, 0.2, 0.1)))

    def level_ir(self, diffuse, level_map, level=0.25, color=(0.8, 0.4, 0.2)):
        ir = mat.MaterialIR(0, "S", base_color=mat.Input(tuple(c * level for c in color), diffuse))
        ir.diffuse_level = mat.DiffuseLevel(color, level, level_map)
        return ir

    def test_diffuse_level_map(self):
        """A Diffuse Level map (maxdrop-em3.150): base color = the diffuse at level 1 times the mean of
        lerp(level, the map, its amount); each side kept over its constant where its images are missing."""
        mean = (1.0 / 3.0,) * 3
        tex = _tex(_bitmap(1), _bitmap(2, G1))
        ir = self.level_ir(mat.MapRef(1, 0.5, False, 0.25), mat.MapRef(2, 0.6))
        g = tx.texture_graphs(ir, tex)["base_color"]
        self.assertEqual(g.kind, tx.COLOR)
        d, f = g.root.a, g.root.b
        self.assertIsInstance(g.root, tx.Multiply)
        self.assertEqual((d.a, d.factor), (tx.Constant((0.8, 0.4, 0.2)), 0.5), "the diffuse at level 1")
        self.assertIsInstance(d.b, tx.Image, "no scale under the level map")
        self.assertEqual((f.red, f.green, f.blue), (mean, mean, mean))
        self.assertEqual((f.input.a, f.input.factor), (tx.Constant(0.25), 0.6))
        self.assertIsInstance(f.input.b, tx.Image)
        self.assertEqual(f.input.b.colorspace, tx.SRGB, "a mask: decoded with the gamma off")
        # full amounts: each bare map kept over its constant by a Mix at factor 1
        ir = self.level_ir(mat.MapRef(1, 1.0, False, 0.25), mat.MapRef(2, 1.0))
        g = tx.texture_graphs(ir, tex)["base_color"]
        self.assertEqual((g.root.a.a, g.root.a.factor), (tx.Constant((0.8, 0.4, 0.2)), 1.0))
        self.assertEqual((g.root.b.input.a, g.root.b.input.factor), (tx.Constant(0.25), 1.0))
        # no diffuse map: the swatch at level 1
        g = tx.texture_graphs(self.level_ir(None, mat.MapRef(2, 1.0)), tex)["base_color"]
        self.assertEqual(g.root.a, tx.Constant((0.8, 0.4, 0.2)))
        # a level map that gives no graph: the diffuse map times the level, as without it
        tex = _tex(_bitmap(1), FakeMap(2, (0x1234, 0), cls="Unknown"))
        ir = self.level_ir(mat.MapRef(1, 0.5, False, 0.25), mat.MapRef(2, 1.0))
        self.assertEqual(tx.texture_graphs(ir, tex)["base_color"], tex.convert(ir.base_color.map, tx.COLOR,
                                                                               ir.base_color.value))
        self.assertNotIn("base_color", tx.texture_graphs(self.level_ir(None, mat.MapRef(2, 1.0)), tex))

    def test_diffuse_level_map_past_max_nodes(self):
        """A product past MAX_NODES keeps the diffuse graph without the level map, with an issue (on the graph and
        once in stats)."""
        tex = _tex(_bitmap(1), _bitmap(2))
        big = tx.Image(1, "a.png")
        for _ in range(tx.MAX_NODES - 2):
            big = tx.Invert(big)
        plain = tx.TextureGraphIR(big, tx.COLOR)
        real = tex.convert

        def convert(ref, kind, value=None):
            return plain if kind == tx.COLOR else real(ref, kind, value)

        tex.convert = convert
        ir = self.level_ir(mat.MapRef(1, 1.0), mat.MapRef(2, 1.0))
        g = tx.texture_graphs(ir, tex)["base_color"]
        self.assertIs(g.root, big, "the diffuse alone")
        reason = "map 2: Diffuse Level map left out: the base color graph would be past %d nodes" % tx.MAX_NODES
        self.assertEqual(g.issues, (reason,))
        tx.texture_graphs(ir, tex)
        self.assertEqual(tex.stats.issues.count((2, reason)), 1)

    def test_normal_map_in_a_color_input_is_its_image(self):
        n = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(2), 2: 1, 3: 1.0}, [2], cls="VRayNormalMap")
        tex = _tex(n, _bitmap(2))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Image)
        self.assertEqual(g.root.colorspace, tx.SRGB)  # read as a normal image below its class: decoded, gamma on
        self.assertTrue(g.approximated)

    def test_normal_map_with_only_a_bump_map(self):
        n = FakeMap(1, tx.NORMAL_BUMP, {3: Ref(2), 5: 1, 1: 0.5}, [2], cls="Normal Bump")
        g = _tex(n, _bitmap(2)).convert(mat.MapRef(1, 0.5), tx.NORMAL)
        self.assertIsInstance(g.root, tx.Bump)
        self.close(g.root.strength, 0.25)

    def test_switched_off_normal_map(self):
        n = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(2), 2: 0}, [2], cls="VRayNormalMap")
        self.assertIsNone(_tex(n, _bitmap(2)).convert(mat.MapRef(1), tx.NORMAL))

    def test_same_wrapper_in_two_slots_counts_once(self):
        tex = _tex(_falloff(1, 2, ftype=3), _bitmap(2))
        tex.convert(mat.MapRef(1), tx.COLOR)
        tex.convert(mat.MapRef(1, 0.5), tx.DATA, 0.0)
        self.assertEqual(tex.stats.peeled, collections.Counter({"Falloff": 1}))

    def test_texture_graphs_of_an_ir(self):
        tex = _tex(_bitmap(1))
        ir = mat.MaterialIR(0, "M", base_color=mat.Input((0.1, 0.2, 0.3), mat.MapRef(1)), bump=mat.MapRef(1, 0.3))
        graphs = tx.texture_graphs(ir, tex)
        self.assertEqual(sorted(graphs), ["base_color", "bump"])
        self.assertEqual(graphs["base_color"].root.colorspace, tx.SRGB)
        self.assertEqual(graphs["bump"].root.input.colorspace, tx.SRGB)  # gamma on: decoded (maxdrop-em3.159)


class Guards(Checks):
    def test_unreadable_placement_takes_the_defaults(self):
        _tex_, g = _image(*_placed(old={2: float("nan"), 3: 2.0}))  # no chunk for the Placement object
        self.assertEqual(g.root.mapping.tiling, (1.0, 2.0))
        self.assertEqual(g.root.mapping.tile, (True, True))
        self.assertEqual(g.root.mapping.channel, 1)

    def test_short_and_out_of_range_placement_chunks(self):
        uv = FakeChunk(0x0009, children=[FakeChunk(0x9002, b"\x01\x00"), FakeChunk(0x900B, struct.pack("<I", 1000)),
                                         FakeChunk(0x9006, struct.pack("<I", 9)), FakeChunk(0x9003, b"\x07\0\0\0")])
        _tex_, g = _image(*_placed(uv=uv))
        self.assertEqual(g.root.mapping, tx.Mapping())

    def test_placement_chunks(self):
        uv = FakeChunk(0x0009, children=[FakeChunk(0x9002, struct.pack("<I", 0x48000008)),
                                         FakeChunk(0x900B, struct.pack("<I", 4))])
        tex, g = _image(*_placed(uv=uv))
        self.assertEqual(g.root.mapping.tile, (False, False))
        self.assertEqual(g.root.mapping.mirror, (False, True))
        self.assertTrue(g.root.mapping.real_world)
        self.assertEqual(g.root.mapping.channel, 4)
        self.assertTrue(any("real-world" in r for r in g.issues))

    def test_gamma(self):
        cases = ((_info(1.8, 5), 1.8, tx.LINEAR), (_info(2.2, 5), 2.2, tx.SRGB), (_info(1.0, 20), None, tx.SRGB),
                 (_info(float("nan"), 5), None, tx.SRGB), (_info(50.0, 5), None, tx.SRGB), (b"\x05" * 10, None, tx.SRGB))
        for info, gamma, space in cases:
            with self.subTest(info=info.hex()):
                _tex_, g = _image(*_placed(info=info))
                if gamma is None:
                    self.assertIsNone(g.root.gamma)
                else:
                    self.close(g.root.gamma, gamma)
                self.assertEqual(g.root.colorspace, space)

    def test_shared_maps_do_not_blow_up(self):
        layers, depth = 10, tx.MAX_DEPTH
        objects = [FakeMap(k, tx.COMPOSITE, {9: [Ref(k + 1)] * layers}, [k + 1], cls="Composite")
                   for k in range(1, depth)] + [_bitmap(depth)]
        tex = _tex(*objects)
        start = time.perf_counter()
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertLess(time.perf_counter() - start, 2.0)
        self.assertIsInstance(g.root, tx.Image)  # 10 ** 7 nodes as a tree: cut down to its first image
        self.assertTrue(g.approximated)
        self.assertTrue(any("cut down" in r for r in g.issues))

    def test_composite_with_an_unknown_blend_mode_is_peeled(self):
        comp = FakeMap(1, tx.COMPOSITE, {5: [0, 15], 9: [Ref(2), Ref(3)]}, [2, 3], cls="Composite")
        tex = _tex(comp, _bitmap(2), _bitmap(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Image)
        self.assertTrue(any("blend modes [15]" in r for r in g.issues))

    def test_color_correction_modes(self):
        standard = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 11: 0, 12: 10.0, 13: -20.0, 22: 2.0}, [2])
        g = _tex(standard, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual((g.root.brightness, g.root.contrast, g.root.gamma), (0.1, -0.2, 1.0))
        self.assertFalse(g.approximated)
        lifted = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 11: 1, 30: 0.2, 10: 0.5}, [2])
        g = _tex(lifted, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertTrue(g.approximated)
        self.assertTrue(any("pivot and lift" in r for r in g.issues))
        self.assertTrue(any("tint not converted" in r for r in g.issues))

    def test_mix_curve(self):
        """Use Curve folds the mix amount through mix_factor, or puts a Smoothstep over the mask; no issue."""
        mix = FakeMap(1, tx.MIX, {0: 0.4, 1: 0.3, 2: 0.7, 3: 1, 6: Ref(2)}, [2])
        g = _tex(mix, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.factor, 0.15625)  # u = 0.25: 3u^2 - 2u^3
        self.assertFalse(g.approximated)
        self.assertEqual(g.issues, ())
        mix = FakeMap(1, tx.MIX, {0: 0.4, 1: 0.2, 2: 0.9, 3: 1, 6: Ref(2), 8: Ref(3)}, [2, 3])
        g = _tex(mix, _bitmap(2), _bitmap(3)).convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root.mask, tx.Smoothstep)
        self.assertIsInstance(g.root.mask.input, tx.Image)
        self.assertEqual((g.root.mask.lower, g.root.mask.upper), (0.2, 0.9))
        self.close(g.root.factor, tx.mix_factor(0.4, 0.2, 0.9))  # the builder's fallback when the mask is missing
        self.assertEqual(g.issues, ())
        mix = FakeMap(1, tx.MIX, {0: 0.4, 6: Ref(2), 8: Ref(3)}, [2, 3])  # without Use Curve: the mask itself
        self.assertIsInstance(_tex(mix, _bitmap(2), _bitmap(3)).convert(mat.MapRef(1), tx.COLOR).root.mask, tx.Image)

    def test_mix_factor(self):
        """The measured rule (renderMap, 3ds Max 2020): lower 0.3, upper 0.7 and lower 0.2, upper 0.9."""
        measured = {(0.3, 0.7): [0.0] * 7 + [0.0429541, 0.156237, 0.316396, 0.499992, 0.683589, 0.843748, 0.957031]
                    + [1.0] * 7,
                    (0.2, 0.9): [0.0] * 5 + [0.0145724, 0.0553902, 0.118074, 0.198245, 0.291539, 0.393576, 0.499992,
                                             0.606409, 0.708446, 0.80174, 0.88191, 0.944595, 0.985412, 1.0, 1.0, 1.0]}
        for (lower, upper), ys in measured.items():
            for k, y in enumerate(ys):
                self.assertAlmostEqual(tx.mix_factor(k / 20.0, lower, upper), y, delta=1e-4, msg=(lower, upper, k))
        self.assertEqual([tx.mix_factor(x, 0.5, 0.5) for x in (0.4999, 0.5, 0.6)], [0.0, 1.0, 1.0])  # a step
        self.assertEqual([tx.mix_factor(x, 0.7, 0.3) for x in (0.5, 0.69, 0.7)], [0.0, 0.0, 1.0])  # a step at lower

    def test_edited_mix_curve_in_every_kind(self):
        """An edited curve puts the Facing under a Remap whatever the input (a VRayMtl reflection is a data input,
        the case of a bent reflection ramp), and the Remap is the curve's polyline."""
        P = reader_materials.CurvePoint
        points = (P((0, 0), (0, 0), (0, 0), 0x102), P((0.5, 0.2), (0.5, 0.2), (0.5, 0.2), 4),
                  P((1, 1), (1, 1), (1, 1), 0x100))
        old = reader_materials.mix_curve
        reader_materials.mix_curve = lambda _scene, _m: points
        try:
            for kind in (tx.COLOR, tx.DATA):
                g = _tex(_falloff(1, name="fo")).convert(mat.MapRef(1), kind)
                self.assertEqual(g.root.mask, tx.Remap(tx.Facing(tx.PERPENDICULAR, 1.6), ((0, 0), (0.5, 0.2), (1, 1))),
                                 kind)
                self.assertEqual(g.issues, ())
        finally:
            reader_materials.mix_curve = old

    def test_unreadable_mix_curve_is_drawn_linear(self):
        def broken(_scene, _m):
            raise chunks.ChunkError("the curve control at object 9: no point count")
        old = reader_materials.mix_curve
        reader_materials.mix_curve = broken
        try:
            fo = _falloff(1, name="fo")
            g = _tex(fo).convert(mat.MapRef(1), tx.COLOR)
        finally:
            reader_materials.mix_curve = old
        self.assertEqual(g.root.mask, tx.Facing(tx.PERPENDICULAR, 1.6))
        self.assertTrue(g.approximated)
        self.assertTrue(any(r.startswith("Falloff 'fo': its mix curve could not be read") and "drawn linear" in r
                            for r in g.issues), g.issues)

    def test_normal_bump_method_and_channel(self):
        nb = FakeMap(1, tx.NORMAL_BUMP, {2: Ref(2), 6: 2}, [2])
        g = _tex(nb, _bitmap(2)).convert(mat.MapRef(1), tx.NORMAL)
        self.assertTrue(any("method" in r for r in g.issues))
        vn = FakeMap(1, classids.VRAY_NORMAL_MAP, {0: Ref(2), 1: 2}, [2])
        self.assertEqual(_tex(vn, _bitmap(2)).convert(mat.MapRef(1), tx.NORMAL).root.channel, 2)

    def test_an_issue_is_reported_once(self):
        uv = FakeChunk(0x0009, children=[FakeChunk(0x9005, struct.pack("<I", 1))])
        b, chunk_map = _placed(uv=uv)
        tex = tx.TexmapConverter(FakeGraph(b, chunk_map=chunk_map), _table())
        tex.convert(mat.MapRef(1), tx.COLOR)
        tex.convert(mat.MapRef(1, 0.5), tx.COLOR, (0.1, 0.1, 0.1))
        tex.convert(mat.MapRef(1), tx.DATA)
        self.assertEqual(len(tex.stats.issues), 1)

    def test_normal_map_without_images_in_a_color_input(self):
        n = FakeMap(1, classids.VRAY_NORMAL_MAP, {}, cls="VRayNormalMap")
        tex = _tex(n)
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.COLOR))
        self.assertEqual(tex.stats.unsupported, collections.Counter({"VRayNormalMap": 1}))
        self.assertEqual(tex.stats.peeled, collections.Counter())


if __name__ == "__main__":
    unittest.main()
