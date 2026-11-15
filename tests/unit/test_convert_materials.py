# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/materials.py, the material rules: no Blender. vray_basic's IR against values computed by
hand from its authoring script (tools/fixtures/vray_basic.ms), vray_maps' map slots, vray_wrappers' peels, and each
rule on synthetic parameters (the classes no fixture has: VRayLightMtl, VRayFastSSS2, the car paints, the other
wrappers).

    python -I -m unittest discover tests
"""
import importlib
import math
import os
import sys
import types
import unittest

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

    def __init__(self, index, class_id, name="", blocks=None, superclass=classids.SC_MATERIAL):
        self.index, self.class_id, self.name, self.superclass = index, class_id, name, superclass
        self._blocks = [FakeBlock(b, p) for b, p in sorted((blocks or {}).items())]

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
        o = self.objects.get(i)
        return None if o is None else o.superclass


def _map(index, class_id=classids.BITMAP_TEX, name="map"):
    return FakeMtl(index, class_id, name, superclass=classids.SC_TEXMAP)


def _vray(index, name="V", **blocks):
    return FakeMtl(index, classids.VRAY_MTL, name, {int(k[1:]): v for k, v in blocks.items()})


def _convert(*objects, index=0, meters=1.0):
    conv = mat.MaterialConverter(FakeGraph(*objects), meters)
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
    def test_srgb_to_linear(self):
        self.assertEqual(mat.srgb_to_linear(0.0), 0.0)
        self.close(mat.srgb_to_linear(1.0), 1.0)
        self.close(mat.srgb_to_linear(0.5), 0.214041)
        self.close(mat.srgb_to_linear(0.04), 0.04 / 12.92)  # below the knee: linear segment

    def test_linear_color_clamps(self):
        self.close(mat.linear_color((-1.0, 2.0, 0.5)), (0.0, 1.0, 0.214041))

    def test_meters_must_be_positive(self):
        for bad in (0, -1.0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                mat.MaterialConverter(FakeGraph(), bad)

    def test_class_name(self):
        self.assertEqual(mat.class_name(classids.SC_MATERIAL, classids.VRAY_MTL), "VRayMtl")
        self.assertEqual(mat.class_name(classids.SC_MATERIAL, mat.VRAY_LIGHT_MTL), "VRayLightMtl")
        self.assertEqual(mat.class_name(classids.SC_MATERIAL, (1, 2)), "ClassID(0x00000001, 0x00000002)")

    def test_not_a_material(self):
        conv, ir = _convert(_map(0))
        self.assertIsNone(ir)
        self.assertIsNone(mat.MaterialConverter(FakeGraph()).convert(5))


class VRayMtlRules(unittest.TestCase, Close):
    def test_defaults(self):
        conv, ir = _convert(_vray(0))
        self.close(ir.base_color.value, (0.214041,) * 3)  # diffuse 0.5 sRGB
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
        t = 0.214041
        self.close(ir.transmission.value, t)
        self.close(ir.base_color.value, (1.0 - t + t * t, t * t, t * t))

    def test_fresnel_off_bright_reflection_is_metal(self):
        b1 = {1: (1.0, 0.0, 0.0), 2: (0.8, 0.8, 0.8), 8: 0, 91: 0.2}
        conv, ir = _convert(_vray(0, b1=b1, b4={101: Ref(1), 201: 50.0}), _map(1))
        self.close(ir.metallic.value, 1.0)
        self.close(ir.base_color.value, (0.603827,) * 3)
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.5, False))
        self.assertEqual(ir.specular.map, mat.MapRef(1, 0.5, False))

    def test_fresnel_on_or_dark_reflection_keeps_diffuse(self):
        for b1 in ({1: (1.0, 0.0, 0.0), 2: (0.8, 0.8, 0.8), 8: 1, 91: 0.2},
                   {1: (1.0, 0.0, 0.0), 2: (0.5, 0.5, 0.5), 8: 0, 91: 0.2}):  # 0.214 < METAL_REFLECTION
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
        self.close(ir.base_color.value, (0.214041,) * 3)
        self.close(ir.roughness.value, 0.0)
        self.close(ir.ior, 1.6)
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 1.0, False))

    def test_animated_parameter_takes_default(self):
        conv, ir = _convert(_vray(0, b1={3: pblock.Animated(4), 1: pblock.Animated(5)}))
        self.close(ir.roughness.value, 0.0)
        self.close(ir.base_color.value, (0.214041,) * 3)


class OtherRules(unittest.TestCase, Close):
    def test_vray_light_mtl(self):
        light = FakeMtl(0, mat.VRAY_LIGHT_MTL, "Glow",
                        {0: {0: (1.0, 0.5, 0.0), 1: 7.5, 2: Ref(1), 3: 1, 5: Ref(2), 6: 0}})
        conv, ir = _convert(light, _map(1), _map(2))
        self.close(ir.base_color.value, (0.0, 0.0, 0.0))
        self.close(ir.roughness.value, 1.0)
        self.close(ir.specular.value, 0.0)
        self.close(ir.emission_color.value, (1.0, 0.214041, 0.0))
        self.close(ir.emission_strength, 7.5)
        self.assertEqual(ir.emission_color.map, mat.MapRef(1, 1.0, False))
        self.assertIsNone(ir.alpha.map)  # opacity map switched off
        self.assertEqual((ir.name, ir.source), ("Glow", "VRayLightMtl"))

    def test_vray_fast_sss2(self):
        sss = FakeMtl(0, mat.VRAY_FAST_SSS2, "Skin", {0: {
            26: (0.5, 0.5, 0.5), 27: Ref(1), 28: 1, 36: 0.25, 2: (1.0, 0.5, 0.5), 0: 4.0, 22: 2.0, 31: 1.4,
            40: (1.0, 1.0, 1.0), 51: 0.7, 3: Ref(2), 4: 1, 85: Ref(3), 86: 1}})
        conv, ir = _convert(sss, _map(1), _map(2), _map(3), meters=0.001)
        self.close(ir.base_color.value, (0.214041,) * 3)
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 1.0, False))
        self.close(ir.roughness.value, 0.3)
        self.close(ir.specular.value, 1.0)
        self.close(ir.ior, 1.4)
        self.close(ir.subsurface_weight, 0.75)
        self.close(ir.subsurface_color, (1.0, 0.214041, 0.214041))
        self.close(ir.subsurface_radius, 0.008)  # 4 x 2 mm
        self.assertEqual(ir.bump, mat.MapRef(2, 1.0, False))
        self.assertEqual(ir.alpha.map, mat.MapRef(3, 1.0, False))

    def test_car_paints(self):
        common = {0: (0.5, 0.0, 0.0), 1: Ref(1), 2: 1, 4: 0.4, 8: 0.9, 27: (1.0, 1.0, 1.0), 31: 0.8, 39: 0.95}
        conv, ir = _convert(FakeMtl(0, mat.VRAY_CAR_PAINT_MTL, "Paint", {0: {**common, 55: Ref(2), 56: 1}}),
                            _map(1), _map(2))
        self.close(ir.base_color.value, (0.214041, 0.0, 0.0))
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 1.0, False))
        self.close(ir.roughness.value, 0.1)
        self.close(ir.metallic.value, 1.0)
        self.close(ir.specular.value, 0.4)
        self.close(ir.coat_weight, 0.8)
        self.close(ir.coat_roughness, 0.05)
        self.close(ir.coat_color, (1.0, 1.0, 1.0))
        self.close(ir.coat_ior, 1.5)
        self.assertEqual(ir.bump, mat.MapRef(2, 1.0, False))
        conv, ir = _convert(FakeMtl(0, mat.VRAY_CAR_PAINT_MTL2, "Paint2",
                                    {0: {**common, 81: 1.7, 54: Ref(2), 55: 1}}), _map(1), _map(2))
        self.close(ir.coat_ior, 1.7)
        self.close(ir.coat_weight, 0.8)
        self.assertEqual(ir.bump, mat.MapRef(2, 1.0, False))
        self.assertEqual(ir.source, "VRayCarPaintMtl2")

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
            conv = mat.MaterialConverter(graph, 0.001)
            ir = conv.convert(by_name["FixtureVRay"])
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


if __name__ == "__main__":
    unittest.main()
