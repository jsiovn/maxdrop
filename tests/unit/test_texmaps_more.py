# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/texmaps/: texmap_wrappers, gamma_swatches, a truncated class directory,
falloff_curve, animated parameters and the Corona group, no Blender.

    python -I -m unittest discover tests
"""
import collections
import importlib
import json
import math
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
    _bitmap, _cbitmap, _cmix, _falloff, _PKG, _table, _tex, _vbitmap, cfb, Checks, chunks, classdir,
    classids, colors, controllers_mod, FakeGraph, FakeMap, FakeOld, FakeScene,
    Fixture, FIXTURE_DIR, mat, params_mod, pblock, reader_materials, reader_scene, Ref, tx,
    UVGEN_OBJECT, _ControllerEntry, _ControllerScene, _TypedBlock,
)


class TexmapWrappers(Checks):
    """tools/fixtures/texmap_wrappers.ms, against the parameters its oracle (3ds Max) reports for each map."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("texmap_wrappers")
        with open(os.path.join(FIXTURE_DIR, "texmap_wrappers.oracle.json"), encoding="utf-8") as fh:
            graph = json.load(fh)["material_graph"]
        cls.oracle = collections.defaultdict(list)  # class name -> [{param name: value}] in graph order
        for item in graph:
            params = {p["name"]: p["value"] for b in item["blocks"] for p in b["params"] if p["name"]}
            cls.oracle[item["class_name"]].append(dict(params, _name=item["name"]))

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def params(self, cls, name):
        return next(p for p in self.oracle[cls] if p["_name"] == name)

    def test_falloff_perpendicular_with_a_map_amount(self):
        o = self.params("falloff", "FixtureFoPerp")
        self.assertEqual((o["type"], o["direction"]), (1, 0))
        g = self.f.irs["FixtureWrapFalloff"].textures["base_color"]
        self.assertFalse(g.approximated)
        root = self.held(g.root)  # gamma off: on the held values (maxdrop-6n0.6.18)
        self.assertEqual(root.mask, tx.Facing(tx.PERPENDICULAR, 1.6))
        side1 = root.a
        self.close(side1.factor, o["map1Amount"] / 100.0)
        self.close(side1.a.value, tuple(o["color1"]))
        self.image(side1.b, "wrap_fo_map.png", tx.NON_COLOR)
        self.close(root.b.value, tuple(o["color2"]))

    def test_falloff_fresnel_and_towards(self):
        o = self.params("falloff", "FixtureFoFresnel")
        t = self.f.irs["FixtureWrapFalloff"].textures
        self.assertEqual(self.held(t["specular"].root).mask.mode, tx.FRESNEL)
        self.close(self.held(t["specular"].root).mask.ior, o["ior"])
        o = self.params("falloff", "FixtureFoTowards")
        self.assertEqual(o["type"], 0)
        g = self.held(t["emission_color"].root)
        self.assertEqual(g.mask, tx.Facing(tx.TOWARDS, 1.6))
        self.close((g.a.value, g.b.value), (tuple(o["color1"]), tuple(o["color2"])))

    def test_falloff_other_type_and_direction_are_peeled(self):
        t = self.f.irs["FixtureWrapFalloff"].textures
        self.assertEqual((self.params("falloff", "FixtureFoLocalX")["direction"],
                          self.params("falloff", "FixtureFoShadow")["type"]), (1, 3))
        self.image(t["alpha"].root, "wrap_fo_dir.png", tx.NON_COLOR)
        self.assertTrue(t["alpha"].approximated)
        g = t["roughness"]  # a glossiness map: inverted; shadow / light without a map: its color 1
        self.close(g.root.input.value, 100 / 255.0)  # a data input: as stored
        self.assertTrue(g.approximated)

    def test_composite_blend_modes_and_mask(self):
        o = self.oracle["CompositeTexturemap"][0]
        g = self.f.irs["FixtureWrapComposite"].textures["base_color"]
        self.assertFalse(g.approximated)
        self.assertIsInstance(g.root, tx.Decode)  # gamma off: composited on the stored values (em3.158)
        layers = g.root.input.layers
        self.assertEqual([la.node.name for la in layers], ["wrap_comp_base.png", "wrap_comp_mul.png",
                                                           "wrap_comp_over.png", "wrap_comp_screen.png"])
        self.assertEqual([la.blend for la in layers], o["blendMode"])
        self.close(tuple(la.opacity for la in layers), tuple(v / 100.0 for v in o["opacity"]))
        self.assertEqual([la.mask is not None for la in layers], [False, False, True, False])
        self.assertEqual(layers[2].mask.mask, tx.Facing(), "the mask Falloff, a data Mix by its Facing")
        g = self.f.irs["FixtureWrapComposite"].textures["emission_color"]
        top = g.root.input.layers[1]
        self.assertEqual(top.blend, tx.SPOTLIGHT_BLEND)
        self.image(top.mask, "wrap_spot_mask.png", tx.NON_COLOR)  # as stored

    def test_composite_soft_light_is_peeled(self):
        self.assertEqual(self.oracle["CompositeTexturemap"][1]["blendMode"], [0, 15])
        g = self.f.irs["FixtureWrapComposite"].textures["specular"]
        self.image(g.root, "wrap_soft_base.png", tx.SRGB)
        self.assertTrue(g.approximated)

    def test_color_correction_rewiring(self):
        t = self.f.irs["FixtureWrapColor"].textures
        for slot, name in (("base_color", "FixtureCCMono"), ("specular", "FixtureCCInvert"),
                           ("emission_color", "FixtureCCCustom")):
            o = self.params("Color_Correction", name)
            self.assertEqual(self.held(t[slot].root).rewire, (o["rewireR"], o["rewireG"], o["rewireB"]), name)
            self.assertFalse(t[slot].approximated, name)
        self.close(self.held(t["specular"].root).brightness, 0.2)

    def test_output_and_tint(self):
        t = self.f.irs["FixtureWrapOutput"].textures
        adjust = self.held(t["base_color"].root)  # gamma off: on the held values (maxdrop-6n0.6.18)
        out = adjust.output
        self.assertTrue(out.invert)
        self.close((out.amount, out.level, out.offset), (0.5, 2.0, 0.1))
        self.image(adjust.input, "wrap_out.png", tx.NON_COLOR)
        o = self.params("RGB_Tint", "FixtureTint")
        tint = self.held(t["specular"].root)
        self.assertIsInstance(tint, tx.Tint)
        self.close(tint.red, tuple(o["red"]), "the rows as stored")
        self.close((tint.green, tint.blue), ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
        self.image(t["emission_color"].root, "wrap_out_plain.png", tx.SRGB)  # an Output with its defaults

    def test_counts(self):
        self.assertEqual(self.f.tex.stats.peeled, collections.Counter({"Falloff": 2, "Composite": 1}))
        self.assertEqual(self.f.tex.stats.unsupported, collections.Counter())
        self.assertEqual(len(self.f.tex.stats.issues), 3, self.f.tex.stats.issues)


class GammaSwatchesFixture(Checks):
    """tools/fixtures/gamma_swatches.ms, saved with the gamma on: every swatch is its value, linear (s / 255)."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("gamma_swatches")

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def test_the_rule_is_read(self):
        self.assertIs(self.f.tex.swatches, colors.GAMMA_ON)
        self.assertIs(self.f.conv.swatches, colors.GAMMA_ON)

    def test_flat_swatches(self):
        ir = self.f.irs["FixtureGammaFlat"]
        self.close(ir.base_color.value, (128 / 255,) * 3, "diffuse 128 -> 0.502")
        self.close(ir.specular.value, 64 / 255, "reflection 64: its mean")
        self.close(ir.emission_color.value, (128 / 255,) * 3, "self-illumination 128")

    def test_map_swatches(self):
        ir = self.f.irs["FixtureGammaMapped"]
        self.close(ir.base_color.value, (10 / 255, 20 / 255, 30 / 255))
        mix = ir.textures["base_color"].root
        self.assertIsInstance(mix, tx.Mix)
        self.close(mix.a.value, (128 / 255,) * 3, "Mix color 1")
        self.close(mix.b.value, (64 / 255, 128 / 255, 192 / 255), "Mix color 2")
        self.close(mix.factor, 0.25)
        self.close(ir.textures["specular"].root.value, (128 / 255,) * 3, "VRayColor 128 -> 0.502")

    def test_standard(self):
        self.close(self.f.irs["FixtureGammaStandard"].base_color.value, (200 / 255, 40 / 255, 30 / 255))


class TruncatedClassDirectory(unittest.TestCase):
    """A class directory cut short: the objects whose class index is past its end have no entry. graph.get turns
    them away (a ChunkError), as it does an index past the objects, so every map it hands the converter is an object
    of the scene with an entry, and _class_name, which has no IndexError net, cannot raise."""

    def test_class_name_of_every_map_graph_get_returns(self):
        with cfb.CompoundFile(os.path.join(FIXTURE_DIR, "texmap_rules.max")) as cf:
            full = classdir.ClassDirectory.from_file(cf)
            counts = []
            for keep in sorted({0, len(full) // 4, len(full) // 2, len(full) - 1, len(full)}):
                scene = reader_scene.Scene.from_file(cf, classdir.ClassDirectory(list(full)[:keep], full.dlls))
                graph = reader_materials.MaterialGraph(scene)
                tex = tx.TexmapConverter(graph)
                got = 0
                for i in range(len(scene) + 2):
                    try:
                        m = graph.get(i)
                    except chunks.ChunkError:
                        continue
                    self.assertLess(scene.class_index(i), keep, "object %d kept %d classes" % (i, keep))
                    self.assertTrue(tex._class_name(m), "object %d kept %d classes" % (i, keep))
                    got += 1
                counts.append(got)
            self.assertEqual(counts[0], 0)
            self.assertGreater(counts[-1], counts[0])


def _polyline_at(points, x):
    """A Remap's polyline at x: straight between the points, flat past the ends (as the Float Curve draws it)."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y1 if x1 <= x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


class FalloffCurve(Checks):
    """falloff_curve: each Falloff's MixCurve and each Mix's Use Curve against 3ds Max 2020's own values
    (tests/fixtures/falloff_curve.curves.jsonl, written by tools/fixtures/falloff_curve.ms from the saved file: 65
    values at x = k / 64)."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture("falloff_curve")
        with open(os.path.join(FIXTURE_DIR, "falloff_curve.curves.jsonl"), encoding="ascii") as f:
            cls.records = {r["name"]: r for r in map(json.loads, f)}
        cls.rows = {name: r["y"] for name, r in cls.records.items()}

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def root(self, name):
        ir = self.f.irs[name]
        self.assertEqual(list(ir.issues), [], name)
        return self.held(ir.textures["base_color"].root, name)  # the fixture's gamma is off (maxdrop-6n0.6.18)

    def test_every_map_has_a_row(self):
        self.assertEqual(set(self.rows), set(self.f.irs))
        self.assertTrue(all(len(y) == 65 for y in self.rows.values()))

    def test_falloff_curves_match_3ds_max(self):
        modes = {"FixtureCurveBezier": tx.PERPENDICULAR, "FixtureCurveCorner": tx.TOWARDS,
                 "FixtureCurveOvershoot": tx.FRESNEL, "FixtureCurveClamped": tx.PERPENDICULAR,
                 "FixtureCurveJump": tx.PERPENDICULAR}
        for name, mode in modes.items():
            with self.subTest(name):
                root = self.root(name)
                self.assertIsInstance(root, tx.Mix)
                self.assertIsInstance(root.mask, tx.Remap)
                self.assertEqual(root.mask.input.mode, mode)
                points = root.mask.points
                self.assertEqual([x for x, _y in points], sorted(x for x, _y in points))
                for k, y in enumerate(self.rows[name]):
                    self.assertAlmostEqual(_polyline_at(points, k / 64.0), y, delta=1e-3, msg=(name, k))
        self.assertEqual(len(self.root("FixtureCurveCorner").mask.points), 4, "corner points: straight segments")
        self.assertGreater(max(self.rows["FixtureCurveOvershoot"]), 1.19, "3ds Max does not clamp the curve")
        self.assertGreater(max(y for _x, y in self.root("FixtureCurveOvershoot").mask.points), 1.19)

    def test_jump(self):
        """FixtureCurveJump: two points at x = 32.5 / 64 (a falling jump) stay in 3ds Max's order, one beside the
        other, and 3ds Max's curve is on either side of the jump at the samples next to it."""
        x = 32.5 / 64
        points = list(self.root("FixtureCurveJump").mask.points)
        at = [k for k, p in enumerate(points) if p[0] == x]
        self.assertEqual(len(at), 2, points)
        self.assertEqual(at[1], at[0] + 1)
        self.assertAlmostEqual(points[at[0]][1], 0.8, places=6)
        self.assertAlmostEqual(points[at[1]][1], 0.3, places=6)
        y = self.rows["FixtureCurveJump"]
        self.assertGreater(y[32], 0.7)
        self.assertLess(y[33], 0.4)

    def test_linear_curve_makes_no_node(self):
        self.assertEqual(self.root("FixtureCurveLinear").mask, tx.Facing(tx.PERPENDICULAR, 1.6))
        self.assertTrue(all(abs(y - k / 64.0) < 1e-5 for k, y in enumerate(self.rows["FixtureCurveLinear"])))

    def test_mix_curves_match_3ds_max(self):
        for name in ("FixtureMixCurve", "FixtureMixCurveStep"):
            with self.subTest(name):
                root = self.f.irs[name].textures["base_color"].root
                self.assertIsInstance(root, tx.Decode)  # gamma off: mixed on the stored values (em3.158)
                mask = root.input.mask
                self.assertIsInstance(mask, tx.Smoothstep)
                self.assertIsInstance(mask.input, tx.Image)
                for k, y in enumerate(self.rows[name]):
                    self.assertAlmostEqual(tx.mix_factor(k / 64.0, mask.lower, mask.upper), y, delta=1e-4,
                                           msg=(name, k))
                # without the mask's image the builder mixes by the factor: the mix amount through the curve,
                # as 3ds Max mixes a Mix without a mask at that amount ("amount")
                factor = root.input.factor
                self.assertGreater(factor, 0.0)
                amount = {"FixtureMixCurve": 0.5, "FixtureMixCurveStep": 0.7}[name]  # tools/fixtures/falloff_curve.ms
                self.assertAlmostEqual(factor, tx.mix_factor(amount, mask.lower, mask.upper), places=6)
                self.assertAlmostEqual(factor, self.records[name]["amount"], delta=1e-4)
        root = self.f.irs["FixtureMixCurveAmount"].textures["base_color"].root  # black to white through the
        # curve: folded, shown decoded
        self.assertIsInstance(root, tx.Constant)
        self.close(root.value, (colors.srgb_to_linear(self.rows["FixtureMixCurveAmount"][0]),) * 3)

    def test_curve_samples(self):
        P = reader_materials.CurvePoint
        self.assertIsNone(tx.curve_samples((P((0, 0), (0, 0), (0, 0), 0x102), P((1, 1), (1, 1), (1, 1), 0x100))))
        line = tx.curve_samples((P((0, 0), (0, 0), (0, 0), 0), P((0.5, 0.8), (0.5, 0.8), (0.5, 0.8), 4),
                                 P((1, 1), (1, 1), (1, 1), 0)))
        self.assertEqual(line, ((0, 0), (0.5, 0.8), (1, 1)))
        # a point above 1 is taken at 1, its handles moved with it
        high = tx.curve_samples((P((0, 0), (0, 0), (0, 0), 0), P((0.5, 1.3), (0.3, 1.3), (0.7, 1.3), 2),
                                 P((1, 1), (1, 1), (1, 1), 0)))
        self.assertEqual(max(y for _x, y in high), 1.0)
        self.assertEqual(high[-1], (1, 1))
        # many points: at most MAX_CURVE_SAMPLES, still the curve (a sine through 1000 Bezier points)
        many = [P((k / 999.0, 0.5 + 0.4 * math.sin(k / 50.0)), (k / 999.0 - 3e-4, 0.5 + 0.4 * math.sin(k / 50.0)),
                  (k / 999.0 + 3e-4, 0.5 + 0.4 * math.sin(k / 50.0)), 2) for k in range(1000)]
        start = time.perf_counter()
        dense = tx.curve_samples(many)
        self.assertLess(time.perf_counter() - start, 0.1)
        self.assertLessEqual(len(dense), tx.MAX_CURVE_SAMPLES)
        self.assertEqual((dense[0][0], dense[-1][0]), (0.0, 1.0))
        for x, y in dense:
            self.assertAlmostEqual(y, 0.5 + 0.4 * math.sin(x * 999.0 / 50.0), delta=0.02)
        jump = tx.curve_samples((P((0, 0), (0, 0), (0, 0), 0), P((0.5, 0.2), (0.5, 0.2), (0.5, 0.2), 0),
                                 P((0.5, 0.9), (0.5, 0.9), (0.5, 0.9), 0), P((1, 1), (1, 1), (1, 1), 0)))
        self.assertEqual(jump, ((0, 0), (0.5, 0.2), (0.5, 0.9), (1, 1)))


class AnimatedRewiring(Checks):
    """A Color Correction whose custom rewiring (rewireMode 3, channels 3 to 5, radio buttons) a controller holds
    converts its rewiring at frame 0 (maxdrop-em3.152); a fraction (3ds Max's rounding not measured) keeps the
    issue."""

    def convert(self, values):
        channels = {pid: pblock.Animated(10 + k) for k, pid in enumerate(tx.CC_REWIRE)}
        cc = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 2: pblock.Animated(20), **channels}, [2],
                     cls="Color Correction", name="cc")
        cc.blocks = {0: _TypedBlock(0, cc.blocks[0]._params, {2: 13, 3: 13, 4: 13, 5: 13})}
        graph = FakeGraph(cc, _bitmap(2))
        graph.scene = _ControllerScene(graph.objects, values)
        return tx.TexmapConverter(graph, _table()).convert(mat.MapRef(1), tx.COLOR)

    def test_rewiring_held_by_controllers(self):
        g = self.convert({20: 3.0, 10: 2.0, 11: 1.0, 12: 0.0})
        self.assertEqual(g.root.rewire, (2, 1, 0))
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def test_mode_held_by_a_controller(self):
        self.assertEqual(self.convert({20: 1.0}).root.rewire, tx.REWIRE_MONO)

    def test_fraction_keeps_the_issue(self):
        g = self.convert({20: 3.0, 10: 2.5, 11: 1.0, 12: 0.0})
        self.assertEqual(g.root.rewire, tx.REWIRE_NONE)
        self.assertTrue(g.approximated)
        self.assertTrue(any("rewiring" in r for r in g.issues), g.issues)


def _cleaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def _cnode(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


_BEZIER_FLOAT = (classids.SC_CTRL_FLOAT, classids.BEZIER_FLOAT, "Bezier Float")
_BEZIER_COLOR = (classids.SC_CTRL_POINT3, classids.BEZIER_COLOR, "Bezier Color")
_OTHER_FLOAT = (classids.SC_CTRL_FLOAT, (0x7778, 0), "Some Float")


class _KeyedScene(FakeScene):
    """A FakeScene that also holds controllers as real chunks: {object index: ((superclass, ClassId, name), bytes)},
    and references {object index: {slot: object index}}."""
    ticks_per_frame = 160

    def __init__(self, objects, controllers, refs=None):
        super().__init__(objects, {i: chunks.index(data)[0] for i, (_kind, data) in controllers.items()})
        self.kinds = {i: kind for i, (kind, _data) in controllers.items()}
        self._refs = refs or {}

    def entry(self, i):
        if i in self.kinds:
            return _ControllerEntry(*self.kinds[i])
        return super().entry(i)

    def refs(self, i):
        return dict(self._refs.get(i, {}))


def _color_keys(before, after, times=(-10, 10)):
    """A Bezier Color without a saved value at frame 0: its two keys (80 bytes each) around it."""
    keys = b"".join(struct.pack("<iI3f", t, 0, *v).ljust(80, bytes(1)) for t, v in zip(times, (before, after)))
    return _cnode(0x9005, _cnode(0x7127, _cleaf(0x2501, struct.pack("<3f", 9, 9, 9)),
                                 _cleaf(0x2500, struct.pack("<ii", 5, 5)), _cleaf(0x2526, keys)))


def _float_saved(value, keys=0):
    """A Bezier Float whose saved value holds forever, or (keys > 1) has no interval beside that many keys."""
    if not keys:
        return _cnode(0x9003, _cnode(0x7127, _cleaf(0x2501, struct.pack("<f", value)),
                                     _cleaf(0x2500, struct.pack("<ii", -2 ** 31, 2 ** 31 - 1))))
    body = b"".join(struct.pack("<iIf4f", 160 * k, 0x1690, value, 0, 0, 1 / 3, 1 / 3) for k in range(keys))
    return _cnode(0x9003, _cnode(0x7127, _cleaf(0x2501, struct.pack("<f", value)), _cleaf(0x2525, body)))


class _OldWithControllers(FakeOld):
    def __init__(self, values, controllers, color=False):
        super().__init__(values)
        self._controllers, self._color = controllers, color

    def controller(self, i):
        return self._controllers.get(i)

    def controller_slots(self):
        return len(self._controllers)

    def type(self, i):
        return 2 if self._controllers.get(i) is not None and self._color else 0


class ControllerLines(Checks):
    """What reading a parameter through its controller meets goes to the report and marks the graph approximated
    (maxdrop-6n0.6.32), once per map and line in stats however many walks read it; a map's Coordinates and Output
    (old ParamBlock) are read through their controllers too."""

    def falloff(self, controller):
        fo = _falloff(1, color1=pblock.Animated(20), name="fo")
        fo.blocks = {0: _TypedBlock(0, fo.blocks[0]._params, {tx.FO_COLOR1: 2})}
        graph = FakeGraph(fo)
        graph.scene = _KeyedScene(graph.objects, {20: controller})
        return tx.TexmapConverter(graph, _table())

    def test_color_between_two_keys(self):
        tex = self.falloff((_BEZIER_COLOR, _color_keys((0.2, 0.4, 0.6), (0.6, 0.8, 1.0))))
        color = tex.convert(mat.MapRef(1), tx.COLOR)
        mask = tex.convert(mat.MapRef(1), tx.MASK)
        for g in (color, mask):
            self.assertTrue(g.approximated)
            lines = [r for r in g.issues if "parameter 0 at frame 0 (controller 20)" in r]
            self.assertEqual(len(lines), 1, g.issues)
            self.assertIn(controllers_mod.KEYS_INTERPOLATED, lines[0])
            self.assertTrue(lines[0].startswith("'fo': "), lines[0])
            self.assertNotIn("default", lines[0])
        self.assertEqual([r for _i, r in tex.stats.issues if "controller 20" in r], [lines[0]])
        self.assertEqual([i for i, r in tex.stats.issues if "controller 20" in r], [1])

    def test_a_cached_map_replays_its_line(self):
        """The same map in the same kind for another slot value: a second graph from the cached node, which carries
        the line and the approximation too."""
        tex = self.falloff((_BEZIER_COLOR, _color_keys((0.2, 0.4, 0.6), (0.6, 0.8, 1.0))))
        graphs = [tex.convert(mat.MapRef(1), tx.COLOR, value) for value in ((1.0, 1.0, 1.0), (0.5, 0.5, 0.5))]
        self.assertIsNot(graphs[0], graphs[1])
        for g in graphs:
            self.assertTrue(g.approximated)
            self.assertEqual(len([r for r in g.issues if "controller 20" in r]), 1, g.issues)
        self.assertEqual(len([r for _i, r in tex.stats.issues if "controller 20" in r]), 1)

    def test_coordinates_of_another_shape(self):
        """A Coordinates parameter whose block says color: a controller's color is no tiling (the default, a
        line)."""
        tex, g = self.placed({30: (_BEZIER_COLOR, _color_keys((1, 2, 3), (1, 2, 3), times=(0, 10)))},
                             {"uv": {tx.UV_U_TILING: 0}}, {"uv": {0: 30}}, color=True)
        self.assertEqual(g.root.mapping.tiling, (1.0, 1.0))
        self.assertTrue(any(params_mod.DEFAULT_USED in r for r in g.issues), g.issues)

    def test_unknown_class_keeps_the_default(self):
        tex = self.falloff((_OTHER_FLOAT, _cnode(0x7778, _cleaf(0x2501, struct.pack("<f", 9)))))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertTrue(g.approximated)
        lines = [r for r in g.issues if "controller 20" in r]
        self.assertEqual(lines, ["'fo': parameter 0 at frame 0 (controller 20): %s, %s"
                                 % (controllers_mod.UNKNOWN_CLASS, params_mod.DEFAULT_USED)])

    def test_a_value_read_without_an_issue_gives_no_line(self):
        tex = self.falloff((_BEZIER_COLOR, _color_keys((0.2, 0.4, 0.6), (0.6, 0.8, 1.0), times=(0, 10))))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def test_a_dome_map_line_heard_by_the_converter_and_the_dome_once(self):
        """A VRayBitmap whose mapping type and horizontal rotation controllers hold, as a dome's map: the converter
        reads the type (its line in the TextureGraphIR's issues), dome_texture reads it again and the rotation, which
        the converter does not read. Given its own graph or the converter's FrameZeroGraph (rewrapped): the type's
        line once, the rotation's in the dome's issues, nothing told to the converter's stats."""
        lights = importlib.import_module(_PKG + ".convert.lights")

        class Index:
            def find(self, path, resolved=""):
                return ("found", path)

        vb = _vbitmap(1, p2=pblock.Animated(20), p3=pblock.Animated(21))
        vb.blocks = {0: _TypedBlock(0, vb.blocks[0]._params, {tx.VB_MAP_TYPE: 1, lights.VB_H_ROTATION: 0})}
        graph = FakeGraph(vb)
        graph.scene = _KeyedScene(graph.objects, {20: (_BEZIER_FLOAT, _float_saved(float(lights.VB_SPHERICAL), 2)),
                                                  21: (_BEZIER_FLOAT, _float_saved(0.5, 2))})
        head = "'vb': parameter %d at frame 0 (controller %d): " + controllers_mod.ANIMATED
        kind, turn = head % (tx.VB_MAP_TYPE, 20), head % (lights.VB_H_ROTATION, 21)
        for which in ("raw", "converter's"):
            tex = tx.TexmapConverter(graph, _table(), textures=Index())
            g = tex.convert(mat.MapRef(1), tx.COLOR)
            self.assertEqual([r for r in g.issues if "at frame 0" in r], [kind], which)
            told = list(tex.stats.issues)
            dt, issues = lights.dome_texture(g, graph if which == "raw" else tex.graph)
            self.assertEqual((dt.turn, issues), (0.5, [kind, turn]), which)
            self.assertEqual(tex.stats.issues, told, which)

    def placed(self, controllers, old, owned=None, color=False):
        """A Bitmap with Coordinates (UVGen 50) and Output (70) parts, each an old block (object 51, 71) whose
        controllers are {parameter index: reference slot}; the blocks' references {slot: controller}."""
        b = _bitmap(1)
        b.parts = {0: reader_materials.Part(UVGEN_OBJECT, classids.STD_UVGEN, classids.SC_UVGEN, {},
                                            {0: _OldWithControllers({}, old.get("uv", {}), color)}),
                   1: reader_materials.Part(70, classids.STD_TEXOUTPUT, classids.SC_TEXOUTPUT, {},
                                            {1: _OldWithControllers({}, old.get("out", {}))})}
        refs = {UVGEN_OBJECT: {0: 51}, 70: {1: 71}, 51: owned.get("uv", {}) if owned else {},
                71: owned.get("out", {}) if owned else {}}
        graph = FakeGraph(b)
        graph.scene = _KeyedScene(graph.objects, controllers, refs)
        tex = tx.TexmapConverter(graph, _table())
        return tex, tex.convert(mat.MapRef(1), tx.COLOR)

    def test_coordinates_and_output_held_by_controllers(self):
        tex, g = self.placed({30: (_BEZIER_FLOAT, _float_saved(4.0)), 31: (_BEZIER_FLOAT, _float_saved(0.5))},
                             {"uv": {tx.UV_U_TILING: 0}, "out": {tx.OUT_AMOUNT: 0}},
                             {"uv": {0: 30}, "out": {0: 31}})
        self.assertEqual(g.root.mapping.tiling, (4.0, 1.0))
        self.assertEqual(g.root.output.amount, 0.5)
        self.assertEqual((g.approximated, g.issues), (False, ()))

    def test_coordinates_with_an_approximation_or_no_value(self):
        tex, g = self.placed({30: (_BEZIER_FLOAT, _float_saved(4.0, keys=2)),
                              31: (_OTHER_FLOAT, _cnode(0x7778)), 32: (_BEZIER_FLOAT, _float_saved(0.25))},
                             {"uv": {tx.UV_U_TILING: 0, tx.UV_V_TILING: 1, tx.UV_U_OFFSET: 2}},
                             {"uv": {0: 30, 1: 31, 2: 32}})
        self.assertEqual(g.root.mapping.tiling, (4.0, 1.0))  # the saved value (maybe another frame's); unknown: 1
        self.assertEqual(g.root.mapping.offset, (0.25, 0.0))
        self.assertTrue(g.approximated)
        head = "'map' Coordinates: parameter %d at frame 0 (controller %s): "
        self.assertEqual(sorted(r for r in g.issues if "at frame 0" in r), sorted([
            head % (tx.UV_U_TILING, 30) + controllers_mod.ANIMATED,
            head % (tx.UV_V_TILING, 31) + controllers_mod.UNKNOWN_CLASS + ", " + params_mod.DEFAULT_USED]))
        self.assertEqual({i for i, r in tex.stats.issues if "at frame 0" in r}, {1})  # under the map

    def test_coordinates_whose_block_misses_a_controller_slot(self):
        """Three animated Coordinates parameters and two references: which parameter lost its slot is not known (a
        later one would read another's controller), so none is read: each at its default, a line naming the
        mismatch."""
        tex, g = self.placed({30: (_BEZIER_FLOAT, _float_saved(4.0)), 31: (_BEZIER_FLOAT, _float_saved(2.0))},
                             {"uv": {tx.UV_U_TILING: 0, tx.UV_V_TILING: 1, tx.UV_U_OFFSET: 2}},
                             {"uv": {0: 30, 1: 31}})
        self.assertEqual((g.root.mapping.tiling, g.root.mapping.offset), ((1.0, 1.0), (0.0, 0.0)))
        self.assertTrue(g.approximated)
        line = "'map' Coordinates: parameter %d at frame 0 (controller missing): %s, %s"
        self.assertEqual(sorted(r for r in g.issues if "at frame 0" in r), sorted(
            line % (pid, params_mod.SLOTS % (2, 3), params_mod.DEFAULT_USED)
            for pid in (tx.UV_U_TILING, tx.UV_V_TILING, tx.UV_U_OFFSET)))


class CoronaGroup(Checks):
    """maxdrop-6n0.6.23 and maxdrop-6n0.6.40: Corona 12 renders (local probes, docs/FORMAT.md)."""

    def test_vray_dirt_is_white_under_corona(self):
        """V-Ray 5.2 renders a VRayDirt's unoccluded map, or its color with the map off; Corona 12 white either way."""
        for switch in (1, 0):
            for renderer, want in ((tx.CORONA_RENDERER, None), (None, "map")):
                with self.subTest(switch=switch, renderer=renderer):
                    dirt = FakeMap(1, tx.VRAY_DIRT, {13: (0.2, 0.8, 0.2), 17: Ref(2), 18: switch}, [2], cls="VRayDirt")
                    tex = tx.TexmapConverter(FakeGraph(dirt, _bitmap(2)), _table(), renderer=renderer)
                    g = tex.convert(mat.MapRef(1), tx.COLOR)
                    d = tex.convert(mat.MapRef(1), tx.DATA)
                    if want is None:
                        self.assertEqual(g.root, tx.Constant((1.0, 1.0, 1.0)))
                        self.assertEqual(d.root, tx.Constant(1.0))
                        self.assertFalse(g.approximated, "what Corona renders: exact")
                        self.assertEqual(tex.stats.peeled, collections.Counter())
                    elif switch:
                        self.assertEqual(g.root.name, "a.png")
                    else:
                        self.close(g.root.value, (0.2, 0.8, 0.2), "the unoccluded color")
                    self.assertEqual(tex.stats.issues, [])

    def test_map_switches_are_read_under_corona(self):
        """Corona honors Mix, RGB Multiply and Falloff switches as V-Ray (6n0.6.23): a switched-off map leaves the
        map's own color under Corona too (Composite's are table switches, read by the same code in any scene)."""
        green = (0.2, 0.8, 0.2)
        cases = (FakeMap(1, tx.MIX, {0: 0.0, 4: green, 5: (0.2, 0.2, 0.8), 6: Ref(2), 9: 0}, [2], cls="Mix"),
                 FakeMap(1, tx.RGB_MULTIPLY, {0: green, 1: (1.0, 1.0, 1.0), 2: Ref(2), 4: 0}, [2],
                         cls="RGB Multiply"),
                 FakeMap(1, tx.FALLOFF, {tx.FO_TYPE: 1, 0: green, 4: green, 2: Ref(2), 3: 0, 6: Ref(2), 7: 0},
                         [2], cls="Falloff"))
        for m in cases:
            with self.subTest(m.cls):
                tex = tx.TexmapConverter(FakeGraph(m, _bitmap(2)), _table(), renderer=tx.CORONA_RENDERER)
                root = tex.convert(mat.MapRef(1), tx.COLOR).root
                self.assertNotIn("a.png", repr(root), "the switched-off map is not drawn")
                self.assertIn(repr(green), repr(root), "its own color")

    def test_corona_mix_gamma_magnitude(self):
        """A CoronaMix gamma over a bottom map: in sRGB mode Corona raises the bottom's magnitude (renderMap:
        multiplierBottom -1 renders the positive bottom's values, 6n0.6.40), so the ColorCorrect takes it; with
        mix in sRGB off the sign is left as it is. A Color Correction map's own gamma never takes it."""
        for srgb in (1, 0):
            with self.subTest(srgb=srgb):
                cm = _cmix(1, [2], p200=7, p207=Ref(2), p208=(0.5, 0.5, 0.5), p214=srgb)
                root = _tex(cm, _cbitmap(2)).convert(mat.MapRef(1), tx.COLOR).root
                self.assertIsInstance(root, tx.ColorCorrect)
                self.assertEqual(root.magnitude, bool(srgb))
                self.close(root.gamma, 0.5 ** (1 / 2.2) if srgb else 0.5)
        cc = FakeMap(1, tx.COLOR_CORRECTION, {1: Ref(2), 11: 1, 22: 2.0}, [2], cls="Color Correction")
        root = _tex(cc, _bitmap(2)).convert(mat.MapRef(1), tx.COLOR).root
        self.assertIsInstance(root, tx.ColorCorrect)
        self.assertFalse(root.magnitude)


if __name__ == "__main__":
    unittest.main()
