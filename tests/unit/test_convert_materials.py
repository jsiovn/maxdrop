# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/materials.py, the material rules: no Blender. vray_basic's IR against values computed by
hand from its authoring script (tools/fixtures/vray_basic.ms), vray_maps' map slots, vray_wrappers' peels, and each
rule on synthetic parameters (the classes no fixture has: VRayLightMtl, VRayFastSSS2, the car paints, the other
wrappers, the Standard shaders but Blinn). standard_physical's Standard and Physical Material and box_poly_standard's
Standard against values computed by hand from their scripts; vray_wrappers' Multi/Sub-Object by material ID and the
slot plan of its box.

    python -I -m unittest discover tests
"""
import importlib
import math
import os
import sys
import types
import unittest

try:
    import numpy
except ImportError:  # the plain CI job has no numpy; Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
TOLERANCE = 1e-5

# A package named apart from the add-on (see test_convert_scene.py): maxdrop/__init__.py, which imports bpy, never
# runs.
_PKG = "maxdrop_convert_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
mat = importlib.import_module(_PKG + ".convert.materials")
colors = importlib.import_module(_PKG + ".convert.colors")
texmaps = importlib.import_module(_PKG + ".convert.texmaps")
cfb = importlib.import_module(_PKG + ".reader.cfb")
chunks = importlib.import_module(_PKG + ".reader.chunks")
classids = importlib.import_module(_PKG + ".reader.classids")
pblock = importlib.import_module(_PKG + ".reader.pblock")
reader_materials = importlib.import_module(_PKG + ".reader.materials")
reader_scene = importlib.import_module(_PKG + ".reader.scene")

Ref = pblock.Reference
GREY = (0.215861,) * 3  # sRGB 128 grey, linear


class FakeBlock:
    def __init__(self, block_id, params):
        self.block_id, self._params = block_id, params

    def __contains__(self, pid):
        return pid in self._params

    def value(self, pid, default=None):
        v = self._params.get(pid, default)
        return list(v) if isinstance(v, list) else v

    def get(self, pid, tab=0, default=None):
        v = self._params.get(pid, default)
        return (v[tab] if 0 <= tab < len(v) else default) if isinstance(v, list) else v


class FakeMtl:
    """A MtlBase stand-in: blocks {block id: {param id: value}}, a list for a table."""

    def __init__(self, index, class_id, name="", blocks=None, superclass=classids.SC_MATERIAL, parts=None):
        self.index, self.class_id, self.name, self.superclass = index, class_id, name, superclass
        self._blocks = [FakeBlock(b, p) for b, p in sorted((blocks or {}).items())]
        self.parts = parts or {}

    def block(self, block_id):
        return next((b for b in self._blocks if b.block_id == block_id), None)

    def param(self, pid, block_id=None, tab=0, default=None):
        for b in [self.block(block_id)] if block_id is not None else self._blocks:
            if b is not None and pid in b:
                return b.get(pid, tab, default)
        return default


class FakeGraph:
    def __init__(self, *objects):
        self.objects = {o.index: o for o in objects}

    def get(self, i):
        if i not in self.objects:
            raise chunks.ChunkError("object %d is not a material or map" % i)
        return self.objects[i]

    def superclass(self, i):
        if not 0 <= i:  # as MaterialGraph.superclass: an int index, TypeError for None
            return None
        o = self.objects.get(i)
        return None if o is None else o.superclass


def _map(index, class_id=classids.BITMAP_TEX, name="map"):
    return FakeMtl(index, class_id, name, superclass=classids.SC_TEXMAP)


def _vray(index, name="V", **blocks):
    return FakeMtl(index, classids.VRAY_MTL, name, {int(k[1:]): v for k, v in blocks.items()})


def _convert(*objects, index=0):
    conv = mat.MaterialConverter(FakeGraph(*objects))
    return conv, conv.convert(index)


class Close:
    def close(self, ours, theirs, what=""):
        if isinstance(theirs, tuple):
            self.assertEqual(len(ours), len(theirs), what)
            for a, b in zip(ours, theirs):
                self.assertAlmostEqual(a, b, delta=TOLERANCE, msg=what)
        else:
            self.assertAlmostEqual(ours, theirs, delta=TOLERANCE, msg=what)


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
        light = FakeMtl(0, mat.VRAY_LIGHT_MTL, "Glow", {0: {0: (1.0, 0.5, 0.0)}})
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

    def test_class_name(self):
        self.assertEqual(mat.class_name(classids.SC_MATERIAL, classids.VRAY_MTL), "VRayMtl")
        self.assertEqual(mat.class_name(classids.SC_MATERIAL, mat.VRAY_LIGHT_MTL), "VRayLightMtl")
        self.assertEqual(mat.class_name(classids.SC_MATERIAL, (1, 2)), "ClassID(0x00000001, 0x00000002)")

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

    def test_fresnel_on_or_dark_reflection_keeps_diffuse(self):
        for b1 in ({1: (1.0, 0.0, 0.0), 2: (0.8, 0.8, 0.8), 8: 1, 91: 0.2},
                   {1: (1.0, 0.0, 0.0), 2: (0.2, 0.2, 0.2), 8: 0, 91: 0.2}):  # 0.2 < METAL_REFLECTION
            conv, ir = _convert(_vray(0, b1=b1))
            self.close(ir.metallic.value, 0.2)
            self.close(ir.base_color.value, (1.0, 0.0, 0.0))

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
        light = FakeMtl(0, mat.VRAY_LIGHT_MTL, "Glow",
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
        sss = FakeMtl(0, mat.VRAY_FAST_SSS2, "Skin", {0: {
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
        self.assertEqual(ir.bump, mat.MapRef(2, 1.0, False))
        self.assertEqual(ir.alpha.map, mat.MapRef(3, 1.0, False))

    def test_car_paints(self):
        common = {0: (0.5, 0.0, 0.0), 1: Ref(1), 2: 1, 4: 0.4, 8: 0.9, 27: (1.0, 1.0, 1.0), 39: 0.95}
        paint = {**common, 31: 0.05, 55: Ref(2), 56: 1}  # coat_strength: reflectance at normal incidence
        conv, ir = _convert(FakeMtl(0, mat.VRAY_CAR_PAINT_MTL, "Paint", {0: paint}), _map(1), _map(2))
        self.close(ir.base_color.value, (0.5, 0.0, 0.0))
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 1.0, False))
        self.close(ir.roughness.value, 0.1)
        self.close(ir.metallic.value, 1.0)
        self.close(ir.specular.value, 0.4)
        self.close(ir.coat_weight, 1.0)
        self.close(ir.coat_ior, 1.576014)  # (1 + sqrt 0.05) / (1 - sqrt 0.05)
        self.close(ir.coat_roughness, 0.05)
        self.close(ir.coat_color, (1.0, 1.0, 1.0))
        self.assertEqual(ir.bump, mat.MapRef(2, 1.0, False))
        conv, ir = _convert(FakeMtl(0, mat.VRAY_CAR_PAINT_MTL, "Bare", {0: {**common, 31: 0.0}}), _map(1))
        self.close(ir.coat_weight, 0.0)
        conv, ir = _convert(FakeMtl(0, mat.VRAY_CAR_PAINT_MTL, "Mirror", {0: {**common, 31: 1.0}}), _map(1))
        self.close(ir.coat_ior, 100.0)  # reflectance 1 is an IOR near 400: clamped like every IOR
        conv, ir = _convert(FakeMtl(0, mat.VRAY_CAR_PAINT_MTL, "Default", {0: {}}))
        self.close((ir.coat_weight, ir.roughness.value), (1.0, 0.4))  # coat_strength 0.05, base_glossiness 0.6
        conv, ir = _convert(FakeMtl(0, mat.VRAY_CAR_PAINT_MTL2, "Paint2",
                                    {0: {**common, 31: 0.8, 81: 1.7, 54: Ref(2), 55: 1}}), _map(1), _map(2))
        self.close(ir.coat_weight, 0.8)
        self.close(ir.coat_ior, 1.7)
        self.close(ir.roughness.value, 0.1)
        self.assertEqual(ir.bump, mat.MapRef(2, 1.0, False))
        self.assertEqual(ir.source, "VRayCarPaintMtl2")
        conv, ir = _convert(FakeMtl(0, mat.VRAY_CAR_PAINT_MTL2, "Default2", {0: {}}))
        self.close((ir.coat_weight, ir.coat_ior, ir.roughness.value), (1.0, 1.5, 0.6))

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
        self.assertEqual(dict(conv.stats.unknown), {"ClassID(0x00001234, 0x00005678)": 2})
        self.assertIs(conv.convert(0), ir)


def _wrapper(index, class_id, params, name="W"):
    return FakeMtl(index, class_id, name, {0: params})


class Wrappers(unittest.TestCase):
    def test_each_wrapper_peels_to_its_first_set_sub_material(self):
        cases = [
            (mat.VRAY_OVERRIDE_MTL, {0: Ref(None), 2: Ref(1), 4: Ref(2)}, 1),  # empty base: the next slot
            (mat.VRAY_MTL_WRAPPER, {0: Ref(1)}, 1),
            (mat.DOUBLE_SIDED_MTL, {0: Ref(2), 1: Ref(1)}, 2),
            (mat.SHELLAC_MTL, {0: Ref(1), 1: Ref(2)}, 1),
            (classids.VRAY_2SIDED_MTL, {0: Ref(None), 1: Ref(2)}, 2),
            (classids.VRAY_BLEND_MTL, {0: Ref(None), 1: [Ref(None), Ref(2), Ref(1)]}, 2),  # coat table
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

    def test_nested_wrappers_count_each_once(self):
        objs = (_wrapper(0, mat.VRAY_MTL_WRAPPER, {0: Ref(1)}), _wrapper(1, classids.VRAY_2SIDED_MTL, {0: Ref(2)}),
                _vray(2, "Base"), _wrapper(3, mat.VRAY_MTL_WRAPPER, {0: Ref(1)}))
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
                conv = mat.MaterialConverter(FakeGraph(_wrapper(0, mat.VRAY_MTL_WRAPPER, params, "Wrap"), _map(5)))
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
        objs = [_wrapper(i, mat.VRAY_MTL_WRAPPER, {0: Ref(i + 1)}) for i in range(mat.MAX_PEEL + 1)]
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


def _fixture(name):
    cf = cfb.CompoundFile(os.path.join(FIXTURE_DIR, name + ".max"))
    s = reader_scene.Scene.from_file(cf)
    graph = reader_materials.MaterialGraph(s)
    by_name = {graph.get(i).name: i for i in graph.walk(s.node(n).material for n in s.walk())}
    return cf, graph, by_name


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
        reflection = (0.309469, 0.361307, 0.417885)  # 151 162 173; mean 0.362887 >= 0.25, Fresnel off: metal
        self.assertEqual((ir.name, ir.source, ir.unknown), ("FixtureVRay", "VRayMtl", False))
        self.close(ir.base_color.value, reflection, "base color = reflection (metal rule)")
        self.close(ir.metallic.value, 1.0, "metallic")
        self.close(ir.roughness.value, 0.83, "roughness = glossiness 0.83 (useRoughness on)")
        self.close(ir.specular.value, 0.362887, "specular = mean reflection")
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


def _standard(index, shader_class, shader, blocks=None, maps=None, name="S"):
    """A Standard material with its shader part (block 0 of the part = shader) and maps {slot: (ref, on, amount)}."""
    blocks = {k: dict(v) for k, v in (blocks or {}).items()}
    if maps:
        enables, refs, amounts = [0] * 24, [Ref(None)] * 24, [1.0] * 24
        for slot, (ref, on, amount) in maps.items():
            refs[slot], enables[slot], amounts[slot] = ref, on, amount
        blocks[3] = {0: enables, 1: refs, 2: amounts}
    parts = {}
    if shader_class is not None:
        parts[2] = reader_materials.Part(50, shader_class, classids.SC_SHADER, {0: FakeBlock(0, shader)}, {})
    return FakeMtl(index, classids.STANDARD_MTL, name, blocks, parts=parts)


def _srgb(*rgb):
    return tuple(colors.srgb_to_linear(c / 255.0) for c in rgb)


class Standard(unittest.TestCase, Close):
    """tools/fixtures/standard_physical.ms and box_poly_standard.ms, by hand (saved with the gamma off: sRGB
    s/255 -> linear); synthetic shaders: no gamma, linear swatches."""

    def test_fixture(self):
        cf, graph, by_name = _fixture("standard_physical")
        with cf:
            conv = mat.MaterialConverter(graph)
            ir = conv.convert(by_name["FixtureStandard"])
        self.assertEqual((ir.name, ir.source, ir.unknown), ("FixtureStandard", "Standard", False))
        self.close(ir.base_color.value, (0.40724, 0.082283, 0.022174), "diffuse 171 81 41")
        self.assertEqual(ir.base_color.map.index, by_name["FixtureStandardMap"])
        self.close(ir.base_color.map.amount, 0.71, "diffuseMapAmount 71")
        self.close(ir.roughness.value, 0.77, "1 - glossiness 0.23")
        self.close(ir.specular.value, 0.268073, "level 0.37 x mean of 231 221 211")
        self.close(ir.metallic.value, 0.0, "Blinn")
        self.close(ir.alpha.value, 0.83, "opacity 83")
        self.close(ir.ior, 1.33)
        self.assertTrue(ir.two_sided)
        self.close(ir.emission_color.value, (0.40724, 0.082283, 0.022174), "self-illumination: the diffuse")
        self.close(ir.emission_strength, 0.13, "selfIllumAmount 13")
        for name in ("roughness", "specular", "alpha", "emission_color", "metallic"):
            self.assertIsNone(getattr(ir, name).map, name)
        self.assertIsNone(ir.bump)
        self.assertEqual(conv.stats.issues, [])

    def test_box_poly_standard(self):
        cf, graph, by_name = _fixture("box_poly_standard")
        with cf:
            ir = mat.MaterialConverter(graph).convert(by_name["FixtureRed"])
        self.close(ir.base_color.value, (0.57758, 0.021219, 0.012983), "diffuse 200 40 30")

    def test_each_shader_reads_its_own_ids(self):
        diffuse = (0.5, 0.25, 0.75)
        for sid, ids in mat.SHADERS.items():
            with self.subTest(sid):
                shader = {ids.diffuse: diffuse, ids.specular: (1.0, 1.0, 1.0), ids.level: 0.4, ids.glossiness: 0.3,
                          ids.si_amount: 0.0, ids.use_si_color: 1, ids.si_color: (0.0, 1.0, 0.0)}
                conv, ir = _convert(_standard(0, sid, shader))
                self.close(ir.base_color.value, diffuse)
                self.close(ir.roughness.value, 0.7)
                self.close(ir.specular.value, 0.4)
                self.close(ir.emission_color.value, (0.0, 1.0, 0.0), "self-illumination color")
                self.close(ir.emission_strength, 1.0)
                self.close(ir.metallic.value, 1.0 if sid == mat.METAL_SHADER else 0.0)
                self.assertEqual(conv.stats.issues, [])

    def test_strauss(self):
        conv, ir = _convert(_standard(0, mat.STRAUSS_SHADER, {0: (1.0, 0.0, 0.0), 1: 0.8, 2: 0.6}))
        self.close(ir.base_color.value, (1.0, 0.0, 0.0))
        self.close(ir.roughness.value, 0.2)
        self.close(ir.metallic.value, 0.6)

    def test_unknown_or_missing_shader_takes_the_defaults(self):
        for sid in ((0x1234, 0), None):
            with self.subTest(sid):
                conv, ir = _convert(_standard(0, sid, {1: (1.0, 0.0, 0.0)}))
                self.close(ir.base_color.value, (150 / 255,) * 3)
                self.assertFalse(ir.unknown)
                self.assertIn("Standard: shader", ir.issues[0])

    def test_map_slots(self):
        maps = {
            mat.STD_DIFFUSE: (Ref(1), 1, 0.5), mat.STD_GLOSSINESS: (Ref(2), 1, 0.8), mat.STD_LEVEL: (Ref(3), 1, 1.0),
            mat.STD_OPACITY: (Ref(4), 1, 0.9), mat.STD_SELF_ILLUM: (Ref(5), 1, 1.0), mat.STD_BUMP: (Ref(6), 1, 0.3),
            mat.STD_REFLECTION: (Ref(7), 1, 0.6),
        }
        objs = [_map(i) for i in range(1, 8)]
        conv, ir = _convert(_standard(0, classids.BLINN_SHADER, {1: (1.0, 1.0, 1.0), 9: 0.1}, maps=maps), *objs)
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.5, False))
        self.assertEqual(ir.roughness.map, mat.MapRef(2, 0.8, True))  # a glossiness map: inverted
        self.assertEqual(ir.specular.map, mat.MapRef(3, 1.0, False))
        self.close(ir.specular.value, 0.6, "reflection amount 0.6 over level 0.1")
        self.assertEqual(ir.alpha.map, mat.MapRef(4, 0.9, False))
        self.assertEqual(ir.emission_color.map, mat.MapRef(5, 1.0, False))
        self.close(ir.emission_strength, 1.0, "a self-illumination map drives the emission")
        self.assertEqual(ir.bump, mat.MapRef(6, 0.3, False))
        self.assertEqual(conv.stats.issues, [])

    def test_switched_off_slots_and_the_specular_color_map(self):
        maps = {mat.STD_DIFFUSE: (Ref(1), 0, 1.0), mat.STD_SPECULAR: (Ref(2), 1, 0.4),
                mat.STD_REFLECTION: (Ref(3), 0, 1.0), mat.STD_BUMP: (Ref(9), 1, 1.0)}
        conv, ir = _convert(_standard(0, classids.BLINN_SHADER, {9: 0.2, 2: (1.0, 1.0, 1.0)}, maps=maps),
                            _map(1), _map(2), _map(3), _vray(9))
        self.assertIsNone(ir.base_color.map)
        self.assertEqual(ir.specular.map, mat.MapRef(2, 0.4, False))  # no level map: the specular color's
        self.close(ir.specular.value, 0.2, "reflection slot off")
        self.assertIsNone(ir.bump)
        self.assertIn("map slot 8: object 9 is not a map", ir.issues[0])


class Physical(unittest.TestCase, Close):
    def test_fixture(self):
        cf, graph, by_name = _fixture("standard_physical")
        with cf:
            conv = mat.MaterialConverter(graph)
            ir = conv.convert(by_name["FixturePhysical"])
        self.assertEqual((ir.name, ir.source, ir.unknown), ("FixturePhysical", "Physical Material", False))
        # base 181 79 28 x weight 0.91, mixed with transparency color 51 102 153 by transparency 0.12
        self.close(ir.base_color.value, (0.374004, 0.078557, 0.047525), "base color")
        self.close(ir.roughness.value, 0.27)
        self.close(ir.metallic.value, 0.43)
        self.close(ir.specular.value, 0.498396, "reflectivity 0.81 x mean of 230 204 179")
        self.close(ir.transmission.value, 0.12)
        self.close(ir.ior, 1.47)
        self.assertFalse(ir.thin_walled)
        self.close(ir.emission_color.value, (0.318547, 0.215861, 0.132868), "emit color 153 128 102")
        self.close(ir.emission_strength, 0.05 * 1500.0 / 683.0, "weight x luminance / 683")
        self.close((ir.coat_weight, ir.coat_roughness, ir.coat_ior), (0.33, 0.21, 1.61))
        self.close(ir.coat_color, (1.0, 1.0, 1.0))
        for name in ("base_color", "roughness", "metallic", "specular", "transmission", "emission_color", "alpha"):
            self.assertIsNone(getattr(ir, name).map, name)
        self.assertEqual((ir.bump, ir.normal, conv.stats.issues), (None, None, []))

    def test_inverted_roughness_and_maps(self):
        params = {4: 0.3, 5: 1, 63: 1, 62: 0.25, 50: 0.0, 101: Ref(1), 104: Ref(2), 105: Ref(3), 154: 1,
                  109: Ref(4), 159: 0, 116: Ref(5), 130: Ref(6), 230: 0.7, 133: Ref(7)}
        conv, ir = _convert(FakeMtl(0, classids.PHYSICAL_MTL, "P", {0: params}), *[_map(i) for i in range(1, 8)])
        self.close(ir.roughness.value, 0.7, "roughness_inv: 1 - 0.3")
        self.assertEqual(ir.roughness.map, mat.MapRef(2, 1.0, True))
        self.close(ir.coat_roughness, 0.75)
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 1.0, False))
        self.assertEqual(ir.metallic.map, mat.MapRef(3, 1.0, False))
        self.assertIsNone(ir.transmission.map)  # switched off
        self.assertEqual(ir.emission_color.map, mat.MapRef(5, 1.0, False))  # the weight map, no color map
        self.close(ir.emission_strength, 1500.0 / 683.0, "a map with weight 0: full weight")
        self.assertEqual(ir.bump, mat.MapRef(6, 0.7, False))
        self.assertEqual(ir.alpha.map, mat.MapRef(7, 1.0, False))

    def test_emission_maps(self):
        conv, ir = _convert(FakeMtl(0, classids.PHYSICAL_MTL, "ColorOnly", {0: {50: 0.0, 117: Ref(1)}}), _map(1))
        self.close(ir.emission_strength, 0.0, "weight 0 with a color map: no emission")
        self.assertIsNone(ir.emission_color.map)
        conv, ir = _convert(FakeMtl(0, classids.PHYSICAL_MTL, "Both",
                                    {0: {50: 0.2, 52: 683.0, 116: Ref(1), 117: Ref(2)}}), _map(1), _map(2))
        self.assertEqual(ir.emission_color.map, mat.MapRef(2, 1.0, False))
        self.close(ir.emission_strength, 1.0, "the weight map stands for the weight")
        self.assertIn("weight map 1 not used", ir.issues[0])
        conv, ir = _convert(FakeMtl(0, classids.PHYSICAL_MTL, "Lit", {0: {50: 0.5, 52: 3000.0}}))
        self.close(ir.emission_strength, 0.5 * 3000.0 / 683.0)

    def test_defaults(self):
        conv, ir = _convert(FakeMtl(0, classids.PHYSICAL_MTL, "Empty", {0: {}}))
        self.close(ir.base_color.value, (0.5,) * 3)
        self.close((ir.roughness.value, ir.metallic.value, ir.specular.value, ir.ior), (0.0, 0.0, 1.0, 1.52))
        self.close(ir.emission_strength, 0.0)


def _multi(index, entries, name="Multi", ids=True):
    """A Multi/Sub-Object of entries [(material id, ref, on)]."""
    block = {0: [r for _i, r, _on in entries], 1: [on for _i, _r, on in entries]}
    if ids:
        block[3] = [i for i, _r, _on in entries]
    return FakeMtl(index, classids.MULTI_SUB_MTL, name, {0: block})


class MultiSub(unittest.TestCase):
    def test_fixture_by_material_id(self):
        cf, graph, by_name = _fixture("vray_wrappers")
        with cf:
            conv = mat.MaterialConverter(graph)
            multi = by_name["FixtureMulti"]
            got = {mid: (lambda ir: ir and ir.name)(conv.material_for(multi, mid)) for mid in range(8)}
            default = conv.convert(multi)
        # IDs 1, 3, 7 (zero-based 0, 2, 6); 3 is switched off
        self.assertEqual(got, {0: "FixtureSubOne", 1: None, 2: None, 3: None, 4: None, 5: None, 6: "FixtureSubSeven",
                               7: None})
        self.assertEqual(default.name, "FixtureSubOne")
        self.assertEqual((dict(conv.stats.unknown), conv.stats.issues), ({}, []))

    def test_wrappers_around_and_inside(self):
        objs = (
            _wrapper(0, mat.VRAY_MTL_WRAPPER, {0: Ref(1)}),  # wrapper -> Multi
            _multi(1, [(4, Ref(2), 1), (5, Ref(3), 1), (6, Ref(4), 1)]),
            _wrapper(2, classids.VRAY_2SIDED_MTL, {0: Ref(5)}),  # Multi -> wrapper
            _multi(3, [(5, Ref(6), 1)]),  # nested Multi: the same ID
            _multi(4, [(0, Ref(6), 1)]),  # nested Multi without ID 6
            _vray(5, "Front"), _vray(6, "Deep"),
        )
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertEqual(conv.material_for(0, 4).name, "Front")
        self.assertEqual(conv.material_for(0, 5).name, "Deep")
        self.assertIsNone(conv.material_for(0, 6))
        self.assertIsNone(conv.material_for(0, 9))
        self.assertIsNone(conv.material_for(None, 0))
        self.assertEqual(conv.material_for(5, 3).name, "Front")  # not a Multi: whatever the ID
        self.assertEqual(conv.convert(0).name, "Front")

    def test_missing_ids_list_duplicates_and_bad_entries(self):
        objs = (_multi(0, [(None, Ref(1), 1), (None, Ref(2), 1)], ids=False), _vray(1, "A"), _vray(2, "B"),
                _multi(3, [(2, Ref(1), 1), (2, Ref(2), 1), (-1, Ref(2), 1), (True, Ref(2), 1)]),
                _multi(4, [(0, Ref(None), 1), (1, Ref(1), 0)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertEqual((conv.material_for(0, 0).name, conv.material_for(0, 1).name), ("A", "B"))  # IDs = k
        self.assertEqual(conv.material_for(3, 2).name, "A")  # the first entry of an ID wins
        self.assertIsNone(conv.material_for(3, 1))
        default = conv.convert(4)  # every entry empty or off
        self.assertTrue(default.unknown)
        self.assertEqual(default.name, "Multi")
        self.assertIn("no sub-material", default.issues[0])
        self.assertEqual(dict(conv.stats.unknown), {})

    def test_cycle_and_depth(self):
        conv = mat.MaterialConverter(FakeGraph(_multi(0, [(1, Ref(1), 1), (2, Ref(1), 1)]),
                                               _multi(1, [(1, Ref(0), 1), (2, Ref(0), 1)])))
        self.assertIsNone(conv.material_for(0, 1))
        self.assertIsNone(conv.material_for(0, 2))
        self.assertEqual(len(conv.stats.issues), 1)  # once, whatever the number of face IDs
        self.assertIn("cycle", conv.stats.issues[0][1])
        conv = mat.MaterialConverter(FakeGraph(_multi(0, [(1, Ref(5), 1)]), _map(5)))
        self.assertIsNone(conv.material_for(0, 1))
        self.assertEqual(conv.stats.issues, [(0, "Multi/Sub-Object 0: sub-material 5 is not a material")])
        objs = [_multi(i, [(0, Ref(i + 1), 1)]) for i in range(mat.MAX_PEEL + 1)] + [_vray(mat.MAX_PEEL + 1, "Deep")]
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertIsNone(conv.material_for(0, 0))
        self.assertIn("nested", conv.stats.issues[0][1])
        self.assertEqual(conv.material_for(1, 0).name, "Deep")


def _desc(**meshes):
    """A SceneDescription stand-in: meshes {key: (users, face material IDs)}."""
    return types.SimpleNamespace(meshes={k: types.SimpleNamespace(users=u, material_indices=numpy.array(f,
                                                                                                      dtype=numpy.int32))
                                         for k, (u, f) in meshes.items()})


def _lin(s):
    c = s / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lins(*s):
    return tuple(_lin(c) for c in s)


class Corona(unittest.TestCase, Close):
    """tools/fixtures/corona_physical.ms, corona_legacy.ms, corona_layered.ms and corona_light.ms, by hand."""

    def convert(self, fixture, *names):
        cf, graph, by_name = _fixture(fixture)
        with cf:
            conv = mat.MaterialConverter(graph)
            irs = [conv.convert(by_name[n]) for n in names]
        return conv, irs

    def test_physical(self):
        conv, (rough, gloss, glass) = self.convert("corona_physical", "FixtureCoronaPhysRough",
                                                   "FixtureCoronaPhysGloss", "FixtureCoronaPhysGlass")
        self.assertEqual((rough.source, rough.unknown), ("CoronaPhysicalMtl", False))  # the leading CR stripped
        self.close(rough.base_color.value, tuple(c * 0.9 for c in _lins(200, 120, 60)), "base x level 0.9")
        self.close(rough.roughness.value, 0.35, "roughness mode")
        self.close(rough.metallic.value, 0.0)
        self.close(rough.ior, 1.45)
        self.close(rough.coat_weight, 0.4)
        self.close(rough.coat_ior, 1.6)
        self.close(rough.coat_roughness, 0.2)
        self.close(rough.coat_color, _lins(230, 210, 190), "clearcoat absorption color")
        self.close(rough.emission_color.value, _lins(255, 128, 0))
        self.close(rough.emission_strength, 2.5)
        self.close(rough.alpha.value, _lin(200) * 0.8, "mean opacity color x level")
        self.close(rough.specular.value, 0.5, "from the IOR")
        self.close(gloss.base_color.value, _lins(220, 180, 90))
        self.close(gloss.metallic.value, 1.0, "metalness mode metal")
        self.close(gloss.roughness.value, 0.3, "glossiness 0.7")
        self.close(gloss.coat_roughness, 0.1, "the clearcoat roughness is a glossiness too")
        tint = _lins(150, 200, 255)
        self.close(glass.base_color.value, tuple(_lin(40) * 0.1 + c * 0.9 for c in tint), "toward the thin tint")
        self.close(glass.transmission.value, 0.9)
        self.assertTrue(glass.thin_walled)
        self.close(glass.ior, 1.52)
        self.close(glass.roughness.value, 0.05)
        self.assertEqual((conv.stats.issues, dict(conv.stats.unknown)), ([], {}))

    def test_legacy(self):
        conv, (pbr, old, metal) = self.convert("corona_legacy", "FixtureCoronaLegacyPbr", "FixtureCoronaLegacyGloss",
                                               "FixtureCoronaLegacyMetal")
        self.assertEqual(pbr.source, "CoronaLegacyMtl")
        self.close(pbr.base_color.value, tuple(c * 0.85 for c in _lins(180, 60, 40)), "diffuse x level")
        self.close(pbr.specular.value, _lin(220) * 0.6, "mean reflection x level")
        self.close(pbr.roughness.value, 0.28, "1 - glossiness 0.72")
        self.close(pbr.metallic.value, 0.0)
        self.close(pbr.ior, 1.6, "Fresnel IOR without refraction")
        self.close(pbr.emission_color.value, _lins(0, 128, 255))
        self.close(pbr.emission_strength, 1.5)
        self.close(pbr.alpha.value, _lin(230) * 0.9)
        refract = _lins(200, 230, 255)
        t = sum(refract) / 3 * 0.75
        self.close(old.transmission.value, t, "mean refraction x level")
        self.close(old.base_color.value, tuple(d * (1 - t) + r * t for d, r in zip(_lins(90, 110, 130), refract)))
        self.close(old.roughness.value, 0.6, "PBR mode off: 1 - glossiness all the same")
        self.close(old.specular.value, 1.0)
        self.close(old.ior, 1.33, "the refraction IOR")
        self.assertTrue(old.thin_walled)
        self.close(metal.metallic.value, 1.0, "Fresnel IOR 999 and a bright reflection")
        self.close(metal.base_color.value, _lins(250, 200, 120), "the reflection color")
        self.close(metal.roughness.value, 0.1)
        self.assertEqual(conv.stats.issues, [])

    def test_layered_peels_to_its_base_or_first_layer(self):
        cf, graph, by_name = _fixture("corona_layered")
        with cf:
            conv = mat.MaterialConverter(graph)
            layered = conv.convert(by_name["FixtureCoronaLayered"])
            base = conv.convert(by_name["FixtureCoronaLayerBase"])
            nobase = conv.convert(by_name["FixtureCoronaLayeredNoBase"])
            only = by_name["FixtureCoronaLayerOnly"]
            self.assertEqual(conv.peel(by_name["FixtureCoronaLayeredNoBase"]), (only, None))
        self.assertIs(layered, base)
        self.close(base.base_color.value, _lins(90, 160, 70))
        self.close(base.roughness.value, 0.45)
        self.assertEqual(nobase.name, "FixtureCoronaLayerOnly")
        self.close(nobase.base_color.value, _lins(70, 80, 200))
        self.assertEqual(conv.stats.peeled, {"CoronaLayeredMtl": 2})

    def test_light(self):
        cf, graph, by_name = _fixture("corona_light")
        with cf:
            conv = mat.MaterialConverter(graph)
            light, plain = conv.convert(by_name["FixtureCoronaLight"]), conv.convert(by_name["FixtureCoronaLightPlain"])
        self.close(light.base_color.value, (0.0, 0.0, 0.0))
        self.close(light.specular.value, 0.0)
        self.close(light.emission_color.value, _lins(255, 200, 150))
        self.close(light.emission_strength, 12.5)
        self.assertEqual(light.emission_color.map, mat.MapRef(by_name["FixtureCLightTex"]))
        self.assertEqual(light.alpha.map, mat.MapRef(by_name["FixtureCLightAlpha"]))
        self.close(plain.emission_color.value, _lins(100, 150, 255))
        self.close(plain.emission_strength, 3.0)
        self.assertIsNone(plain.emission_color.map, "texmapOn off")

    def test_map_slots(self):
        cf, graph, by_name = _fixture("corona_maps")
        with cf:
            conv = mat.MaterialConverter(graph)
            ir, legacy = conv.convert(by_name["FixtureCoronaMaps"]), conv.convert(by_name["FixtureCoronaLegacyMaps"])
        self.assertEqual(ir.base_color.map.index, by_name["FixtureCBase"])
        self.close(ir.base_color.map.amount, 0.75, "a fraction")
        self.assertEqual(ir.roughness.map.index, by_name["FixtureCGloss"])
        self.assertTrue(ir.roughness.map.invert, "glossiness mode")
        self.close(ir.roughness.map.amount, 0.6)
        self.close(ir.roughness.value, 0.4)
        self.assertEqual(ir.alpha.map, mat.MapRef(by_name["FixtureCOpacity"]))
        self.assertEqual(ir.normal.index, by_name["FixtureCNormal"])
        self.close(ir.normal.amount, 0.9)
        self.assertEqual(ir.metallic.map, mat.MapRef(by_name["FixtureCColor"]))
        self.assertEqual(ir.emission_color.map, mat.MapRef(by_name["FixtureCMix"]))
        self.assertEqual(legacy.base_color.map, mat.MapRef(by_name["FixtureCMultiply"]))
        self.assertEqual(legacy.specular.map, mat.MapRef(by_name["FixtureCAdd"]))
        self.assertEqual(legacy.roughness.map, mat.MapRef(by_name["FixtureCLegacyGloss"], 1.0, True))
        self.assertEqual(legacy.bump, mat.MapRef(by_name["FixtureCLegacyBump"], 0.5))
        self.assertEqual(legacy.alpha.map, mat.MapRef(by_name["FixtureCHdr"]))
        self.assertIsNone(legacy.emission_color.map, "slot switched off")
        self.assertEqual(conv.stats.issues, [])


def _corona(index, class_id, **params):
    return FakeMtl(index, class_id, "C", {0: {int(k[1:]): v for k, v in params.items()}})


class CoronaSynthetic(unittest.TestCase, Close):
    def test_physical_defaults(self):
        _conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL))
        self.close(ir.base_color.value, (0.5,) * 3)
        self.close(ir.roughness.value, 0.75)
        self.close(ir.ior, 1.5)
        self.close(ir.alpha.value, 1.0)
        self.close(ir.emission_strength, 0.0)
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

    def test_physical_ior_mode_is_an_issue(self):
        conv, ir = _convert(_corona(0, classids.CORONA_PHYSICAL_MTL, p461=1, p171=2.0))
        self.close(ir.ior, 2.0)
        self.assertIn("IOR mode 1", ir.issues[0])

    def test_layered_with_nothing_set_is_grey(self):
        conv, ir = _convert(_corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(None), p1001=[Ref(None)] * 3))
        self.assertTrue(ir.unknown)
        self.close(ir.base_color.value, GREY)
        self.assertTrue(any("no sub-material" in r for _i, r in conv.stats.issues))


@unittest.skipIf(numpy is None, "numpy missing")  # assign() and the mesh reader need it
class Assign(unittest.TestCase):
    def names(self, slots):
        return [[ir and ir.name for ir in s] for s in slots]

    def test_fixture_multi_box(self):
        cf, graph, by_name = _fixture("vray_wrappers")
        with cf:
            s = reader_scene.Scene.from_file(cf)
            desc = importlib.import_module(_PKG + ".convert.scene").describe(s, 0.001, None)
            conv = mat.MaterialConverter(graph)
            materials = mat.node_materials(s, desc)
            plan = mat.assign(desc, materials, conv)
        box = next(n for n in desc.nodes if n.name == "FixtureMultiBox")
        ms = plan[box.mesh]
        self.assertEqual(ms.users, [box.index])
        self.assertEqual(self.names(ms.slots), [["FixtureSubOne"], [None]])
        self.assertEqual(ms.indices.tolist(), [1, 0, 1, 1, 1, 1])  # face IDs 2 1 5 4 6 3: only ID 1 has a material
        two = next(n for n in desc.nodes if n.name == "FixtureTwoSidedBox")
        self.assertEqual(self.names(plan[two.mesh].slots), [["FixtureFront"]])
        self.assertEqual(plan[two.mesh].indices.tolist(), [0] * 6)
        self.assertEqual(plan[two.mesh].indices.dtype.name, "int32")

    def test_users_with_different_materials(self):
        objs = (_multi(0, [(0, Ref(1), 1), (2, Ref(2), 1), (6, Ref(3), 1)]), _vray(1, "One"), _vray(2, "Three"),
                _vray(3, "Seven"), _vray(4, "Plain"))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        plan = mat.assign(_desc(m=([10, 11], [6, 0, 2, 0, 5])), {10: 0, 11: 4}, conv)["m"]
        self.assertEqual(plan.users, [10, 11])
        self.assertEqual(self.names(plan.slots), [["One", "Plain"], ["Three", "Plain"], [None, "Plain"],
                                                  ["Seven", "Plain"]])
        self.assertEqual(plan.indices.tolist(), [3, 0, 1, 0, 2])

    def test_one_material_and_no_material(self):
        conv = mat.MaterialConverter(FakeGraph(_vray(4, "Plain")))
        plan = mat.assign(_desc(a=([1, 2], [3, 1, 2]), b=([3], [0, 5]), c=([5], [])), {1: 4, 2: 4, 3: None, 5: 4},
                          conv)
        self.assertEqual((self.names(plan["a"].slots), plan["a"].indices.tolist()), ([["Plain", "Plain"]], [0, 0, 0]))
        self.assertEqual((plan["b"].slots, plan["b"].indices.tolist()), ([], [0, 0]))
        self.assertEqual((self.names(plan["c"].slots), plan["c"].indices.tolist()), ([], []))


if __name__ == "__main__":
    unittest.main()
