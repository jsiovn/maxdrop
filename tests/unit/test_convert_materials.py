# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/materials.py, the material rules: no Blender. vray_basic's IR against values computed by
hand from its authoring script (tools/fixtures/vray_basic.ms), vray_maps' map slots, vray_wrappers' peels, vray_more's
VRayLightMtl, VRayFastSSS2, car paints and other wrappers, and each rule on synthetic parameters. standard_physical's
Standard and Physical Material, box_poly_standard's Standard, standard_shaders' Standard shaders and Physical map slots
against values computed by hand from their scripts (and the ids by the names the oracle gives them); vray_wrappers'
Multi/Sub-Object by material ID and the slot plan of its box. standard_maps' Standard map slots per shader by the
names of the maps its script puts in each channel.

    python -I -m unittest discover tests
"""
import ast
import importlib
import json
import math
import os
import sys
import types
import unittest

try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
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
classdir = importlib.import_module(_PKG + ".reader.classdir")
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
        if not 0 <= i:  # as MaterialGraph.get: TypeError for None
            raise chunks.ChunkError("object %d is not a material or map" % i)
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


def _build_constant(name):
    """A module-level constant of maxdrop/build/materials.py, which imports bpy: read from its source."""
    path = os.path.join(ROOT, "maxdrop", "build", "materials.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets):
            return ast.literal_eval(stmt.value)
    raise AssertionError("no %s in maxdrop/build/materials.py" % name)


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
        light = FakeMtl(0, classids.VRAY_LIGHT_MTL, "Glow", {0: {0: (1.0, 0.5, 0.0)}})
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
        self.assertEqual(mat.class_name(classids.SC_MATERIAL, classids.VRAY_LIGHT_MTL), "VRayLightMtl")
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

    def test_reflection_color_is_the_specular_weight(self):
        """A white reflection is 1, the full Fresnel reflection at the IOR, which build/materials.py halves into
        Blender's Specular IOR Level 0.5 (the IOR unchanged): V-Ray 5.2 and Cycles both reflect 0.053 facing the
        camera at IOR 1.6 (maxdrop-em3.34). A grey reflection is its linear mean."""
        for refl, want in (((1.0, 1.0, 1.0), 1.0), ((0.502, 0.502, 0.502), 0.502), ((0.2, 0.4, 0.9), 0.5),
                           ((0.0, 0.0, 0.0), 0.0)):
            conv, ir = _convert(_vray(0, b1={2: refl}))
            self.close(ir.specular.value, want, str(refl))
            self.close(ir.metallic.value, 0.0)  # Fresnel on: never the metal rule
        self.assertEqual(_build_constant("SPECULAR_LEVEL"), 0.5)

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

    def test_fresnel_off_reflection_map_at_full_amount_keeps_diffuse(self):
        """A reflection map at full amount hides the swatch in V-Ray: no metal however bright the swatch; the
        specular follows the map, the base color is the diffuse."""
        b1 = {1: (1.0, 0.0, 0.0), 2: (1.0, 1.0, 1.0), 8: 0, 91: 0.2}
        for amount in (100.0, 150.0):
            conv, ir = _convert(_vray(0, b1=b1, b4={101: Ref(1), 201: amount}), _map(1))
            self.close(ir.metallic.value, 0.2, str(amount))
            self.close(ir.base_color.value, (1.0, 0.0, 0.0), str(amount))
            self.assertIsNone(ir.base_color.map)
            self.assertEqual(ir.specular.map, mat.MapRef(1, amount / 100.0, False))

    def test_fresnel_off_swatch_shows_in_proportion_below_full_amount(self):
        b1 = {1: (1.0, 0.0, 0.0), 2: (0.8, 0.8, 0.8), 8: 0, 91: 0.2}
        conv, ir = _convert(_vray(0, b1=b1, b4={101: Ref(1), 201: 75.0}), _map(1))  # 0.8 x 0.25 = 0.2 shown
        self.close(ir.metallic.value, 0.2)
        self.close(ir.base_color.value, (1.0, 0.0, 0.0))
        conv, ir = _convert(_vray(0, b1=b1, b4={101: Ref(1), 151: 0, 201: 100.0}), _map(1))  # map switched off
        self.close(ir.metallic.value, 1.0)
        self.close(ir.base_color.value, (0.8,) * 3)
        self.assertIsNone(ir.base_color.map)
        white = {**b1, 2: (1.0, 1.0, 1.0)}
        conv, ir = _convert(_vray(0, b1=white, b4={101: Ref(1), 201: 75.0}), _map(1))  # 1 x 0.25: the threshold
        self.close(ir.metallic.value, 1.0)

    def test_fresnel_flag(self):
        """reflection_fresnel reaches the IR: off, the weight is a mirror's at every angle (build/materials.py draws
        a white metal mixed by it, maxdrop-em3.120); a dim swatch keeps its mean as the weight, no metal."""
        conv, ir = _convert(_vray(0, b1={1: (1.0, 0.0, 0.0), 2: (0.2, 0.2, 0.2), 8: 0}))
        self.assertFalse(ir.fresnel)
        self.close(ir.specular.value, 0.2)
        self.close(ir.metallic.value, 0.0)
        self.close(ir.base_color.value, (1.0, 0.0, 0.0))
        conv, ir = _convert(_vray(0, b1={2: (0.2, 0.2, 0.2), 8: 1}))
        self.assertTrue(ir.fresnel)
        conv, ir = _convert(_vray(0, b1={2: (0.8, 0.8, 0.8), 8: 0}))  # the metal rule: Metallic 1 wins in build
        self.assertFalse(ir.fresnel)
        self.close(ir.metallic.value, 1.0)
        self.assertTrue(mat.MaterialIR(0, "x").fresnel, "every other rule: the IOR's Fresnel")

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
        light = FakeMtl(0, classids.VRAY_LIGHT_MTL, "Glow",
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
        sss = FakeMtl(0, classids.VRAY_FAST_SSS2, "Skin", {0: {
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
        self.assertEqual(ir.bump, mat.MapRef(2, 0.3, False))  # no texmap_bump_multiplier: its default, 30
        self.assertEqual(ir.alpha.map, mat.MapRef(3, 1.0, False))
        sss2 = FakeMtl(0, classids.VRAY_FAST_SSS2, "Dim", {0: {
            27: Ref(1), 28: 1, 29: 25.0, 40: (0.5, 0.5, 0.5), 44: 1.5, 3: Ref(2), 4: 1, 5: 150.0, 85: Ref(3), 86: 1,
            87: 60.0}})
        conv, ir = _convert(sss2, _map(1), _map(2), _map(3))
        self.assertEqual((ir.base_color.map, ir.bump, ir.alpha.map),
                         (mat.MapRef(1, 0.25, False), mat.MapRef(2, 1.5, False), mat.MapRef(3, 0.6, False)))
        self.close(ir.specular.value, 0.75, "specular_amount 1.5 x mean 0.5")
        sss2 = FakeMtl(0, classids.VRAY_FAST_SSS2, "Bright", {0: {40: (1.0, 1.0, 1.0), 44: 3.0}})
        self.close(_convert(sss2)[1].specular.value, 1.0, "a reflection weight: at most 1")
        conv, ir = _convert(FakeMtl(0, classids.VRAY_FAST_SSS2, "Default", {0: {}}))
        self.close(ir.subsurface_color, (0.5,) * 3)  # sub_surface_color's default: 127.5 grey
        self.close((ir.subsurface_radius, ir.subsurface_weight, ir.ior), (0.01, 1.0, 1.3))

    def test_car_paints(self):
        common = {0: (0.5, 0.0, 0.0), 1: Ref(1), 2: 1, 4: 0.4, 8: 0.9, 27: (1.0, 1.0, 1.0), 39: 0.95}
        paint = {**common, 31: 0.05, 55: Ref(2), 56: 1}  # coat_strength: reflectance at normal incidence
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL, "Paint", {0: paint}), _map(1), _map(2))
        self.close(ir.base_color.value, (0.5, 0.0, 0.0))
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 1.0, False))
        self.close(ir.roughness.value, 0.1)
        self.close(ir.metallic.value, 1.0)
        self.close(ir.specular.value, 0.4)
        self.close(ir.coat_weight, 1.0)
        self.close(ir.coat_ior, 1.576014)  # (1 + sqrt 0.05) / (1 - sqrt 0.05)
        self.close(ir.coat_roughness, 0.05)
        self.close(ir.coat_color, (1.0, 1.0, 1.0))
        self.assertEqual(ir.bump, mat.MapRef(2, 1.0, False))  # no multipliers: full amount
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL, "Dim", {0: {**paint, 3: 40.0, 57: 20.0}}),
                            _map(1), _map(2))
        self.assertEqual((ir.base_color.map, ir.bump), (mat.MapRef(1, 0.4, False), mat.MapRef(2, 0.2, False)))
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL, "Bare", {0: {**common, 31: 0.0}}), _map(1))
        self.close(ir.coat_weight, 0.0)
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL, "Mirror", {0: {**common, 31: 1.0}}), _map(1))
        self.close(ir.coat_ior, 100.0)  # reflectance 1 is an IOR near 400: clamped like every IOR
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL, "Default", {0: {}}))
        self.close((ir.coat_weight, ir.roughness.value), (1.0, 0.4))  # coat_strength 0.05, base_glossiness 0.6
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL2, "Paint2",
                                    {0: {**common, 31: 0.8, 81: 1.7, 54: Ref(2), 55: 1}}), _map(1), _map(2))
        self.close(ir.coat_weight, 0.8)
        self.close(ir.coat_ior, 1.7)
        self.close(ir.roughness.value, 0.1)
        self.assertEqual(ir.bump, mat.MapRef(2, 1.0, False))
        self.assertEqual(ir.source, "VRayCarPaintMtl2")
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL2, "Dim2",
                                    {0: {**common, 3: 30.0, 54: Ref(2), 55: 1, 56: 70.0}}), _map(1), _map(2))
        self.assertEqual((ir.base_color.map, ir.bump), (mat.MapRef(1, 0.3, False), mat.MapRef(2, 0.7, False)))
        conv, ir = _convert(FakeMtl(0, classids.VRAY_CAR_PAINT_MTL2, "Default2", {0: {}}))
        self.close((ir.coat_weight, ir.coat_ior, ir.roughness.value), (1.0, 1.5, 0.6))

    def test_ir_default_specular_is_the_iors_own_fresnel(self):
        self.close(mat.MaterialIR(0, "x").specular.value, 1.0, "a reflection weight, drawn as Blender's 0.5")

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
        self.close(ir.specular.value, 1.0, "the IOR's own Fresnel, Blender's default 0.5")
        self.assertEqual(dict(conv.stats.unknown), {"ClassID(0x00001234, 0x00005678)": 2})
        self.assertIs(conv.convert(0), ir)


def _wrapper(index, class_id, params, name="W"):
    return FakeMtl(index, class_id, name, {0: params})


class Wrappers(unittest.TestCase):
    def test_each_wrapper_peels_to_its_first_set_sub_material(self):
        cases = [
            (classids.VRAY_OVERRIDE_MTL, {0: Ref(None), 2: Ref(1), 4: Ref(2)}, 1),  # empty base: the next slot
            (classids.VRAY_MTL_WRAPPER, {0: Ref(1)}, 1),
            (classids.DOUBLE_SIDED_MTL, {0: Ref(2), 1: Ref(1)}, 2),
            (classids.SHELLAC_MTL, {0: Ref(1), 1: Ref(2)}, 1),
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

    def test_a_sub_material_switched_off_is_still_used(self):
        """V-Ray 5.2 renders a VRayOverrideMtl's base and a Double Sided's facing material whatever their switches say
        (maxdrop-em3.136); the scanline renders a Double Sided side switched off black: an issue when it is the
        facing one, reported once per wrapper object."""
        OV, DS = classids.VRAY_OVERRIDE_MTL, classids.DOUBLE_SIDED_MTL
        override = {0: Ref(1), 2: Ref(2), 4: Ref(3), 6: Ref(4), 8: Ref(5)}
        off = ("Wrap: facing material switched off: drawn all the same, as V-Ray renders it (the scanline renders it "
               "black)")
        cases = [
            (OV, override, False),  # no switches stored: on
            (OV, {**override, 1: 1, 3: 1}, False),
            (OV, {**override, 1: 0}, False),  # baseMtl_on off
            (OV, {**override, 1: 0, 3: 0}, False),  # and giMtl_on
            (OV, {**override, 1: 0, 3: 0, 5: 0, 7: 0, 9: 0}, False),
            (OV, {0: Ref(1), 1: 0, 2: Ref(None), 4: Ref(3)}, False),
            (DS, {0: Ref(1), 1: Ref(2)}, False),
            (DS, {0: Ref(1), 1: Ref(2), 2: 0}, True),  # map1Enabled off
            (DS, {0: Ref(1), 1: Ref(2), 2: 1, 3: 0}, False),  # map2Enabled off: the back is not drawn anyway
            (DS, {0: Ref(1), 1: Ref(2), 2: 0, 3: 0}, True),
        ]
        for class_id, params, issue in cases:
            with self.subTest((class_id, params)):
                subs = [_vray(i, "V%d" % i) for i in range(1, 6)]
                outer = _wrapper(6, classids.VRAY_MTL_WRAPPER, {0: Ref(0)}, "Outer")
                conv = mat.MaterialConverter(FakeGraph(_wrapper(0, class_id, params, "Wrap"), outer, *subs))
                self.assertEqual(conv.peel(6), (1, None))
                self.assertEqual(conv.peel(0), (1, None))  # _sub runs again on the same wrapper
                self.assertEqual(conv.convert(0).name, "V1")
                self.assertEqual(conv.stats.issues, [(0, off)] if issue else [])

    def test_a_facing_slot_switched_off_and_unused_is_no_issue(self):
        """The facing-material line names only a facing material that is drawn: an empty one (the back is drawn) or
        one that is not a material (the peel fails) gives none."""
        DS = classids.DOUBLE_SIDED_MTL
        for params, want in [({0: Ref(None), 1: Ref(2), 2: 0}, (2, None)),
                             ({0: Ref(7), 1: Ref(2), 2: 0}, (None, "Wrap: sub-material 7 is not a material"))]:
            with self.subTest(params):
                conv = mat.MaterialConverter(FakeGraph(_wrapper(0, DS, params, "Wrap"), _vray(2, "V2"), _map(7)))
                self.assertEqual(conv.peel(0), want)
                self.assertEqual(conv.stats.issues, [])

    def test_nested_wrappers_count_each_once(self):
        objs = (_wrapper(0, classids.VRAY_MTL_WRAPPER, {0: Ref(1)}), _wrapper(1, classids.VRAY_2SIDED_MTL, {0: Ref(2)}),
                _vray(2, "Base"), _wrapper(3, classids.VRAY_MTL_WRAPPER, {0: Ref(1)}))
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
                conv = mat.MaterialConverter(FakeGraph(_wrapper(0, classids.VRAY_MTL_WRAPPER, params, "Wrap"), _map(5)))
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
        objs = [_wrapper(i, classids.VRAY_MTL_WRAPPER, {0: Ref(i + 1)}) for i in range(mat.MAX_PEEL + 1)]
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
                if ids.diffuse_level is not None:
                    shader[ids.diffuse_level] = 1.0
                conv, ir = _convert(_standard(0, sid, shader))
                self.close(ir.base_color.value, diffuse)
                self.close(ir.roughness.value, 0.7)
                self.close(ir.specular.value, 0.4)
                self.close(ir.emission_color.value, (0.0, 1.0, 0.0), "self-illumination color")
                self.close(ir.emission_strength, 1.0)
                self.close(ir.metallic.value, 1.0 if sid == classids.METAL_SHADER else 0.0)
                self.assertEqual(conv.stats.issues, [])

    def test_strauss(self):
        conv, ir = _convert(_standard(0, classids.STRAUSS_SHADER, {0: (1.0, 0.0, 0.0), 1: 0.8, 2: 0.6}))
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

    # Diffuse Level ids (a fraction; measured in 3ds Max 2020, docs/FORMAT.md); the other shaders have none.
    DIFFUSE_LEVEL = {classids.ANISOTROPIC_SHADER: 4, classids.MULTI_LAYER_SHADER: 4,
                     classids.OREN_NAYAR_BLINN_SHADER: 8, classids.TRANSLUCENT_SHADER: 7}

    def test_diffuse_level_scales_the_swatch(self):
        """The level scales the swatch (clamped per channel after the product), not the self-illumination, which
        lights with the diffuse as set (Default Scanline renders, docs/FORMAT.md)."""
        for sid, pid in self.DIFFUSE_LEVEL.items():
            ids = mat.SHADERS[sid]
            for level, want in ((0.5, (0.4, 0.2, 0.1)), (1.5, (1.0, 0.6, 0.3)), (-1.0, (0.0, 0.0, 0.0))):
                with self.subTest(sid=sid, level=level):
                    shader = {ids.diffuse: (0.8, 0.4, 0.2), pid: level, ids.si_amount: 0.3, ids.use_si_color: 0}
                    conv, ir = _convert(_standard(0, sid, shader))
                    self.close(ir.base_color.value, want)
                    self.close(ir.emission_color.value, (0.8, 0.4, 0.2), "self-illumination: the unscaled diffuse")
                    self.close(ir.emission_strength, 0.3)

    def test_diffuse_level_decoys(self):
        """A value at another shader's Diffuse Level id scales nothing: Phong, Blinn and Metal have none, and
        id 4, 7 or 8 is another parameter on the shaders that have one elsewhere (Multi-Layer, which reads 7 and 8:
        5, its diffuse roughness)."""
        for sid in (classids.PHONG_SHADER, classids.BLINN_SHADER, classids.METAL_SHADER):
            with self.subTest(sid):
                conv, ir = _convert(_standard(0, sid, {1: (0.8, 0.4, 0.2), 4: 0.5, 7: 0.0, 8: (0.0, 0.0, 0.0)}))
                self.close(ir.base_color.value, (0.8, 0.4, 0.2))
        for sid, pid in self.DIFFUSE_LEVEL.items():
            shader = {1: (0.8, 0.4, 0.2), pid: 1.0}
            shader.update({k: 0.5 for k in (4, 5, 7, 8) if k != pid and k not in mat.SHADERS[sid][:7]})
            self.assertGreater(len(shader), 2, "at least one decoy")
            with self.subTest(sid):
                conv, ir = _convert(_standard(0, sid, shader))
                self.close(ir.base_color.value, (0.8, 0.4, 0.2))

    def test_shader_defaults(self):
        """A shader block without its values: each shader's own defaults, as 3ds Max 2020 creates them (diffuse
        150 / 255 or 127.5 / 255 grey, glossiness, specular level times the 0.9 specular color)."""
        blinn = ((150 / 255,) * 3, 0.9, 0.0)
        want = {  # base color, roughness (1 - glossiness), specular
            classids.PHONG_SHADER: blinn, classids.BLINN_SHADER: blinn, classids.METAL_SHADER: blinn,
            classids.ANISOTROPIC_SHADER: ((0.5,) * 3, 0.75, 0.05 * 0.9),
            classids.MULTI_LAYER_SHADER: ((0.5,) * 3, 0.5, 0.05 * 0.9),
            classids.OREN_NAYAR_BLINN_SHADER: ((0.5,) * 3, 0.75, 0.0),
            classids.TRANSLUCENT_SHADER: ((0.5,) * 3, 0.7, 0.0),
            classids.STRAUSS_SHADER: ((0.5,) * 3, 0.8, 1.0),  # no specular level: the IOR's own Fresnel
        }
        self.assertEqual(set(want), set(mat.SHADER_DEFAULTS))
        for sid, (base, rough, spec) in want.items():
            with self.subTest(sid):
                conv, ir = _convert(_standard(0, sid, {}))
                self.close(ir.base_color.value, base)
                self.close(ir.roughness.value, rough)
                self.close(ir.specular.value, spec)
                self.assertEqual(conv.stats.issues, [])

    # Each shader's map channels (zero-based, measured in 3ds Max 2020, docs/FORMAT.md): diffuse, specular color,
    # specular level, glossiness, self-illumination, opacity, bump, reflection, metalness; None: no such channel.
    CHANNELS = {
        classids.BLINN_SHADER: (1, 2, 3, 4, 5, 6, 8, 9, None),
        classids.PHONG_SHADER: (1, 2, 3, 4, 5, 6, 8, 9, None),
        classids.METAL_SHADER: (1, 2, 3, 4, 5, 6, 8, 9, None),
        classids.ANISOTROPIC_SHADER: (1, 2, 4, 5, 8, 9, 11, 12, None),
        classids.MULTI_LAYER_SHADER: (1, 4, 5, 6, 14, 15, 17, 18, None),  # the first specular layer
        classids.OREN_NAYAR_BLINN_SHADER: (1, 2, 4, 3, 5, 6, 10, 11, None),
        classids.TRANSLUCENT_SHADER: (1, 2, 4, 3, 5, 6, 10, 11, None),
        classids.STRAUSS_SHADER: (0, None, None, 1, None, 3, 5, 6, 2),
    }

    def test_map_slots(self):
        """Every shader reads its own channels: a map in each read channel (object = its field's number + 1, at
        an amount of its own), every other channel holds a map no input may take (object 50 + the channel)."""
        for sid, channels in self.CHANNELS.items():
            with self.subTest(sid):
                maps = {k: (Ref(50 + k), 1, 0.25) for k in range(21)}
                for field, k in enumerate(channels):
                    if k is not None:
                        maps[k] = (Ref(field + 1), 1, 0.5 + field / 100.0)
                objs = [_map(i) for i in range(1, 10)] + [_map(50 + k) for k in range(21)]
                conv, ir = _convert(_standard(0, sid, {}, maps=maps), *objs)
                diffuse, spec, level, gloss, emit, opacity, bump, refl, metal = channels
                self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.50, False))
                self.assertEqual(ir.roughness.map, mat.MapRef(4, 0.53, True))  # a glossiness map: inverted
                self.assertEqual(ir.specular.map, None if level is None else mat.MapRef(3, 0.52, False))
                self.close(ir.specular.value, 1.0 if sid == classids.STRAUSS_SHADER else 0.57,
                           "the reflection amount over level 0")
                self.assertEqual(ir.alpha.map, mat.MapRef(6, 0.55, False))
                if emit is None:
                    self.assertIsNone(ir.emission_color.map)
                    self.close(ir.emission_strength, 0.0)
                else:
                    self.assertEqual(ir.emission_color.map, mat.MapRef(5, 0.54, False))
                    self.close(ir.emission_strength, 1.0, "a self-illumination map drives the emission")
                self.assertEqual(ir.bump, mat.MapRef(7, 0.56, False))
                self.assertEqual(ir.metallic.map, None if metal is None else mat.MapRef(9, 0.58, False))
                self.assertEqual(conv.stats.issues, [])

    def test_specular_color_map_without_a_level_map(self):
        for sid, channels in self.CHANNELS.items():
            if channels[1] is None:
                continue
            with self.subTest(sid):
                conv, ir = _convert(_standard(0, sid, {}, maps={channels[1]: (Ref(1), 1, 0.4)}), _map(1))
                self.assertEqual(ir.specular.map, mat.MapRef(1, 0.4, False))

    def test_switched_off_slots_and_the_specular_color_map(self):
        maps = {1: (Ref(1), 0, 1.0), 2: (Ref(2), 1, 0.4), 9: (Ref(3), 0, 1.0), 8: (Ref(9), 1, 1.0)}
        conv, ir = _convert(_standard(0, classids.BLINN_SHADER, {9: 0.2, 2: (1.0, 1.0, 1.0)}, maps=maps),
                            _map(1), _map(2), _map(3), _vray(9))
        self.assertIsNone(ir.base_color.map)
        self.assertEqual(ir.specular.map, mat.MapRef(2, 0.4, False))  # no level map: the specular color's
        self.close(ir.specular.value, 0.2, "reflection slot off")
        self.assertIsNone(ir.bump)
        self.assertIn("map slot 8: object 9 is not a map", ir.issues[0])

    def test_texmaps_channels(self):
        """_std_map from a Texmaps object's channels (reader.materials.StdMaps): its map, switch and amount, a
        channel that holds something else than a map named as the table's."""
        conv = mat.MaterialConverter(FakeGraph(_map(1), _vray(9)))
        m, ir = _standard(0, classids.BLINN_SHADER, {}), mat.MaterialIR(0, "S")
        std = reader_materials.StdMaps({1: 1, 2: 1, 8: 9, 9: 1}, 0b100001110, {1: 0.4})
        self.assertEqual(mat._std_map(conv, m, 1, ir, channels=std), mat.MapRef(1, 0.4, False))
        self.assertIsNone(mat._std_map(conv, m, 3, ir, channels=std))  # on, no map
        self.assertEqual(mat._std_map(conv, m, 2, ir, invert=True, channels=std), mat.MapRef(1, 1.0, True))
        self.assertIsNone(mat._std_map(conv, m, 8, ir, channels=std))
        self.assertIn("map channel 8: object 9 is not a map", ir.issues[0])
        self.assertIsNone(mat._std_map(conv, m, 9, ir, channels=std))  # a map, switched off


class StandardMaps(unittest.TestCase, Close):
    """tools/fixtures/standard_maps.ms: a Standard material per shader with a Checker in every channel the rule
    reads, named after the input it drives ("FixtureMap" + shader + field) and put into the channel 3ds Max names
    that way on that shader; amounts 0.51 (diffuse) to 0.59 (metalness). Three Anisotropic materials whose block 3
    tables are stale (created as Blinn, docs/FORMAT.md): FixtureMapsUnsetAmounts, FixtureMapsSwitchedAfter,
    FixtureMapsSwitchedOff."""

    LABELS = {"Blinn": "BLINN_SHADER", "Anisotropic": "ANISOTROPIC_SHADER", "MultiLayer": "MULTI_LAYER_SHADER",
              "OrenNayarBlinn": "OREN_NAYAR_BLINN_SHADER", "Translucent": "TRANSLUCENT_SHADER",
              "Strauss": "STRAUSS_SHADER"}
    FIELDS = {"diffuse": "Diffuse", "specular": "Specular", "level": "Level", "glossiness": "Glossiness",
              "self_illum": "SelfIllum", "opacity": "Opacity", "bump": "Bump", "reflection": "Reflection",
              "metalness": "Metalness"}

    @classmethod
    def setUpClass(cls):
        cf, cls.graph, cls.by_name = _fixture("standard_maps")
        with cf:
            cls.conv = mat.MaterialConverter(cls.graph)
            cls.irs = {n: cls.conv.convert(cls.by_name["FixtureMaps" + n])
                       for n in list(cls.LABELS) + ["UnsetAmounts", "SwitchedAfter", "SwitchedOff"]}

    def map(self, label, field, amount, invert=False):
        return mat.MapRef(self.by_name["FixtureMap" + label + field], amount, invert)

    def same_map(self, got, want, what):
        """The same map and invert; the amount within float precision (stored as a 32-bit float)."""
        self.assertIsNotNone(got, what)
        self.assertEqual((got.index, got.invert), (want.index, want.invert), what)
        self.close(got.amount, want.amount, what + " amount")

    def test_each_shader_reads_its_maps(self):
        for label in self.LABELS:
            with self.subTest(label):
                ir, strauss = self.irs[label], label == "Strauss"
                self.same_map(ir.base_color.map, self.map(label, "Diffuse", 0.51), "diffuse")
                self.same_map(ir.roughness.map, self.map(label, "Glossiness", 0.54, invert=True), "glossiness")
                if strauss:
                    self.assertIsNone(ir.specular.map)
                else:
                    self.same_map(ir.specular.map, self.map(label, "Level", 0.53), "specular level")
                self.close(ir.specular.value, 1.0 if strauss else 0.58, "the reflection slot's amount")
                self.same_map(ir.alpha.map, self.map(label, "Opacity", 0.56), "opacity")
                self.same_map(ir.bump, self.map(label, "Bump", 0.57), "bump")
                if strauss:
                    self.assertIsNone(ir.emission_color.map)
                    self.close(ir.emission_strength, 0.0)
                    self.same_map(ir.metallic.map, self.map(label, "Metalness", 0.59), "metalness")
                    self.close(ir.metallic.value, 0.40)
                else:
                    self.same_map(ir.emission_color.map, self.map(label, "SelfIllum", 0.55), "self-illumination")
                    self.close(ir.emission_strength, 1.0)
                    self.assertIsNone(ir.metallic.map)

    def test_the_slot_table_names_the_maps(self):
        """mat.STD_SLOTS against the channel 3ds Max put each named map into (the specular color map, which
        the level map hides, included)."""
        for label, shader in self.LABELS.items():
            m = self.graph.get(self.by_name["FixtureMaps" + label])
            sid = getattr(classids, shader)
            slots = mat.STD_SLOTS[sid]
            with self.subTest(label):
                for field, suffix in self.FIELDS.items():
                    want = self.by_name.get("FixtureMap" + label + suffix)
                    k = getattr(slots, field)
                    self.assertEqual(want is None, k is None, field)
                    if k is not None:
                        self.assertEqual(m.param(1, 3, tab=k).index, want, field)
        self.assertEqual(set(mat.STD_SLOTS), set(mat.SHADERS) | {classids.STRAUSS_SHADER})

    def table(self, label, pid):
        """Block 3's table pid (0 mapEnables, 1 maps, 2 mapAmounts) of FixtureMaps + label, a map as its index."""
        values = self.graph.get(self.by_name["FixtureMaps" + label]).block(3).param(pid).values
        return [getattr(v, "index", v) for v in values]

    def test_amounts_never_set_after_the_shader_switch(self):
        """FixtureMapsUnsetAmounts (Anisotropic, created as Blinn, maps set after the switch without touching their
        amounts): the table keeps Blinn's amounts (0.3 at 8, 1.0 at 11), 3ds Max answers its shader's from the
        Texmaps object: self-illumination (8) 1.0, bump (11) 0.3 (maxdrop-em3.148)."""
        amounts = self.table("UnsetAmounts", 2)
        self.close((amounts[8], amounts[11]), (0.3, 1.0), "the table is still stale")
        ir = self.irs["UnsetAmounts"]
        self.same_map(ir.emission_color.map, self.map("UnsetAmounts", "SelfIllum", 1.0), "self-illumination")
        self.same_map(ir.bump, self.map("UnsetAmounts", "Bump", 0.3), "bump")
        self.assertIsNone(ir.base_color.map)

    def test_maps_set_before_the_shader_switch(self):
        """FixtureMapsSwitchedAfter (Blinn with diffuse and bump maps, then switched to Anisotropic): 3ds Max moves
        the bump map to Anisotropic's channel 11 at 0.3, the table keeps it and its switch at Blinn's 8, which is
        Anisotropic's self-illumination."""
        bump = self.by_name["FixtureMapSwitchedAfterBump"]
        self.assertEqual((self.table("SwitchedAfter", 1)[8], self.table("SwitchedAfter", 0)[8]), (bump, 1),
                         "the table is still stale")
        ir = self.irs["SwitchedAfter"]
        self.same_map(ir.base_color.map, self.map("SwitchedAfter", "Diffuse", 1.0), "diffuse")
        self.same_map(ir.bump, self.map("SwitchedAfter", "Bump", 0.3), "bump")
        self.assertIsNone(ir.emission_color.map)
        self.close(ir.emission_strength, 0.0)

    def test_a_map_switched_off(self):
        """FixtureMapsSwitchedOff (Anisotropic, self-illumination and bump maps, the bump switched off): no bump."""
        ir = self.irs["SwitchedOff"]
        self.same_map(ir.emission_color.map, self.map("SwitchedOff", "SelfIllum", 1.0), "self-illumination")
        self.assertIsNone(ir.bump)

    def test_no_issues(self):
        self.assertEqual((self.conv.stats.issues, dict(self.conv.stats.unknown)), ([], {}))


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


def _oracle_graph(name):
    with open(os.path.join(FIXTURE_DIR, name + ".oracle.json"), encoding="ascii") as f:
        return {e["name"]: e for e in json.load(f)["material_graph"]}


def _names(block):
    return {p["id"]: p["name"] for p in block["params"]}


class StandardShaders(unittest.TestCase, Close):
    """tools/fixtures/standard_shaders.ms, by hand (gamma off: sRGB s/255 -> linear): one Standard material per
    shader. The ids are also checked by the names 3ds Max gives them in the oracle, apart from SHADERS."""

    # material: (shader, diffuse, specular, level %, glossiness %, self-illumination amount %, its color, color on)
    VALUES = {
        "FixtureBlinn": ("BLINN_SHADER", (200, 60, 40), (220, 210, 200), 41, 31, 17, (30, 90, 200), True),
        "FixturePhong": ("PHONG_SHADER", (60, 180, 90), (210, 220, 230), 52, 42, 19, (200, 30, 90), False),
        "FixtureMetal": ("METAL_SHADER", (180, 140, 60), (240, 230, 200), 63, 53, 21, (90, 200, 30), True),
        "FixtureAnisotropic": ("ANISOTROPIC_SHADER", (90, 60, 200), (190, 200, 210), 74, 64, 23, (40, 160, 220),
                               False),
        "FixtureOrenNayarBlinn": ("OREN_NAYAR_BLINN_SHADER", (150, 90, 120), (230, 220, 210), 35, 45, 27,
                                  (220, 120, 40), True),
        "FixtureMultiLayer": ("MULTI_LAYER_SHADER", (100, 170, 160), (200, 190, 180), 46, 56, 29, (160, 40, 220),
                              False),
        "FixtureTranslucent": ("TRANSLUCENT_SHADER", (170, 110, 80), (215, 225, 235), 57, 67, 31, (30, 220, 160),
                               True),
    }
    FIELDS = {"diffuse": "diffuse", "specular": "specular", "level": "specularLevel", "glossiness": "glossiness",
              "si_amount": "selfIllumAmount", "si_color": "selfIllumColor", "use_si_color": "useSelfIllumColor"}
    # material: (shader, diffuse, Diffuse Level %, self-illumination amount %); glossiness and specular level as
    # created
    LEVELS = {
        "FixtureAnisotropicLevel": ("ANISOTROPIC_SHADER", (200, 120, 60), 40, 35),
        "FixtureMultiLayerLevel": ("MULTI_LAYER_SHADER", (60, 200, 140), 150, 0),
        "FixtureOrenNayarBlinnLevel": ("OREN_NAYAR_BLINN_SHADER", (120, 80, 220), 65, 0),
        "FixtureTranslucentLevel": ("TRANSLUCENT_SHADER", (90, 180, 50), 80, 0),
    }

    @classmethod
    def setUpClass(cls):
        cf, graph, cls.by_name = _fixture("standard_shaders")
        with cf:
            cls.conv = mat.MaterialConverter(graph)
            cls.irs = {n: cls.conv.convert(cls.by_name[n])
                       for n in list(cls.VALUES) + list(cls.LEVELS) + ["FixtureStrauss"]}
        cls.oracle = _oracle_graph("standard_shaders")

    def shader_block(self, name):
        """(ClassId, parameter names by id) of the shader part of a Standard material in the oracle."""
        parts = [(classdir.ClassId(*(int(h, 16) for h in p["class_id"])), p) for p in self.oracle[name]["parts"]]
        parts = [(cid, p) for cid, p in parts if cid != classids.STAR_SAMPLER]  # the other part: the sampler
        self.assertEqual(len(parts), 1, name)
        return parts[0][0], _names(parts[0][1]["blocks"][0])

    def test_each_shader_by_hand(self):
        for name, (shader, diffuse, spec, level, gloss, amount, si_color, si_on) in self.VALUES.items():
            with self.subTest(name):
                ir = self.irs[name]
                self.assertEqual((ir.name, ir.source, ir.unknown), (name, "Standard", False))
                self.close(ir.base_color.value, _lins(*diffuse))
                self.close(ir.roughness.value, 1.0 - gloss / 100.0)
                self.close(ir.specular.value, level / 100.0 * sum(_lins(*spec)) / 3)
                if si_on:  # its own color at strength 1
                    self.close(ir.emission_color.value, _lins(*si_color))
                    self.close(ir.emission_strength, 1.0)
                else:  # the diffuse at the amount
                    self.close(ir.emission_color.value, _lins(*diffuse))
                    self.close(ir.emission_strength, amount / 100.0)
                self.close(ir.metallic.value, 1.0 if shader == "METAL_SHADER" else 0.0)
                self.assertIsNone(ir.base_color.map)

    def test_strauss(self):
        ir = self.irs["FixtureStrauss"]
        self.close(ir.base_color.value, _lins(120, 130, 210))
        self.close((ir.roughness.value, ir.metallic.value, ir.specular.value), (1.0 - 0.37, 0.48, 1.0))
        self.close(ir.emission_strength, 0.0)

    def test_ids_name_the_parameters(self):
        for name, values in self.VALUES.items():
            with self.subTest(name):
                sid, names = self.shader_block(name)
                self.assertEqual(sid, getattr(classids, values[0]))
                ids = mat.SHADERS[sid]
                self.assertEqual({field: names[getattr(ids, field)] for field in self.FIELDS}, self.FIELDS)
        sid, names = self.shader_block("FixtureStrauss")
        self.assertEqual(sid, classids.STRAUSS_SHADER)
        self.assertEqual((names[0], names[1], names[2]), ("diffuse", "glossiness", "metalness"))
        self.assertEqual(set(mat.SHADERS), {getattr(classids, v[0]) for v in self.VALUES.values()})

    def test_diffuse_level_by_hand(self):
        """The swatch times the level, clamped to 255, then decoded (Multi-Layer's green 200 x 1.5 is white); the
        self-illumination keeps the diffuse as set; glossiness and specular level are the shader's as created."""
        for name, (shader, diffuse, level, amount) in self.LEVELS.items():
            with self.subTest(name):
                sid, names = self.shader_block(name)
                self.assertEqual(sid, getattr(classids, shader))
                ids, d = mat.SHADERS[sid], mat.SHADER_DEFAULTS[sid]
                self.assertEqual(names[ids.diffuse_level], "diffuseLevel")
                block = self.oracle[name]["parts"]
                stored = [p["value"] for part in block for b in part["blocks"][:1] for p in b["params"]
                          if p.get("name") == "diffuseLevel"]
                self.assertEqual(len(stored), 1)
                self.close(stored[0], level / 100.0, "stored as a fraction")
                ir = self.irs[name]
                self.close(ir.base_color.value, _lins(*(min(255.0, c * level / 100.0) for c in diffuse)))
                self.close(ir.roughness.value, 1.0 - d.glossiness)
                self.close(ir.specular.value, d.level * _lin(229.5), "level as created times the 0.9 grey specular")
                if amount:
                    self.close(ir.emission_color.value, _lins(*diffuse), "the unscaled diffuse")
                self.close(ir.emission_strength, amount / 100.0)
        self.close(self.irs["FixtureMultiLayerLevel"].base_color.value[1], 1.0, "past white: clamped")

    def test_no_issues(self):
        self.assertEqual((self.conv.stats.issues, dict(self.conv.stats.unknown)), ([], {}))


class PhysicalMaps(unittest.TestCase, Close):
    """tools/fixtures/standard_shaders.ms's two Physical Materials, by hand (gamma off): the same nine map slots in
    both, each switched off in one of them. The ids are checked by the names the oracle gives them (mat.PHYSICAL,
    which physical_mtl reads; the switches at a fixed offset): the values alone cannot tell apart two ids that
    hold the same value in both materials."""

    @classmethod
    def setUpClass(cls):
        cf, graph, cls.by_name = _fixture("standard_shaders")
        with cf:
            cls.conv = mat.MaterialConverter(graph)
            cls.maps = cls.conv.convert(cls.by_name["FixturePhysicalMaps"])
            cls.off = cls.conv.convert(cls.by_name["FixturePhysicalOff"])
        cls.oracle = _oracle_graph("standard_shaders")

    def map(self, name, invert=False):
        return mat.MapRef(self.by_name["FixturePhys" + name + "Map"], 1.0, invert)

    def test_maps(self):
        ir = self.maps
        self.assertEqual((ir.source, ir.unknown, ir.issues), ("Physical Material", False, []))
        base = tuple(c * 0.8 for c in _lins(200, 100, 50))
        self.close(ir.base_color.value, tuple(b * 0.8 + t * 0.2 for b, t in zip(base, _lins(60, 120, 180))))
        self.assertEqual(ir.base_color.map, self.map("MapsBase"))
        self.close(ir.specular.value, 0.7 * sum(_lins(210, 200, 190)) / 3)
        self.assertEqual(ir.specular.map, self.map("MapsReflectivity"))
        self.close(ir.roughness.value, 1.0 - 0.35, "roughness_inv")
        self.assertEqual(ir.roughness.map, self.map("MapsRoughness", invert=True))
        self.close(ir.metallic.value, 0.25)
        self.assertEqual(ir.metallic.map, self.map("MapsMetalness"))
        self.close(ir.transmission.value, 0.2)
        self.assertIsNone(ir.transmission.map)  # transparency_map_on off
        self.close(ir.ior, 1.4)
        self.assertTrue(ir.thin_walled)
        self.close(ir.emission_color.value, _lins(220, 180, 140))
        self.assertEqual(ir.emission_color.map, self.map("MapsEmitColor"))  # emission_map_on off: the color map
        self.close(ir.emission_strength, 0.6 * 900.0 / 683.0)
        self.close((ir.coat_weight, ir.coat_roughness, ir.coat_ior), (0.45, 1.0 - 0.15, 1.7))
        self.close(ir.coat_color, _lins(230, 200, 170))
        self.assertEqual((ir.bump.index, ir.bump.invert), (self.map("MapsBump").index, False))
        self.close(ir.bump.amount, 0.55, "bump_map_amt")
        self.assertIsNone(ir.normal)
        self.assertEqual(ir.alpha.map, self.map("MapsCutout"))

    def test_off(self):
        ir = self.off
        self.assertEqual(ir.issues, [])
        base = tuple(c * 0.9 for c in _lins(70, 140, 210))
        self.close(ir.base_color.value, tuple(b * 0.7 + t * 0.3 for b, t in zip(base, _lins(200, 150, 100))))
        self.close(ir.specular.value, 0.55 * sum(_lins(180, 190, 200)) / 3)
        self.close((ir.roughness.value, ir.metallic.value, ir.transmission.value, ir.ior), (0.4, 0.6, 0.3, 1.6))
        for name in ("base_color", "specular", "roughness", "metallic", "alpha"):
            self.assertIsNone(getattr(ir, name).map, name)
        self.assertEqual(ir.transmission.map, self.map("OffTransparency"))
        self.assertFalse(ir.thin_walled)
        self.close(ir.emission_color.value, _lins(100, 150, 250))
        self.assertEqual(ir.emission_color.map, self.map("OffEmission"))  # the weight map, the color map off
        self.close(ir.emission_strength, 2400.0 / 683.0, "the weight map stands for the weight")
        self.close((ir.coat_weight, ir.coat_roughness, ir.coat_ior), (0.2, 0.3, 1.55))
        self.close(ir.coat_color, _lins(150, 200, 250))
        self.assertEqual((ir.bump, ir.normal), (None, None))  # bump_map_on off

    def test_ids_name_the_parameters(self):
        """Every id of mat.PHYSICAL, which physical_mtl reads, and each map's switch name their parameters."""
        for name in ("FixturePhysicalMaps", "FixturePhysicalOff"):
            with self.subTest(name):
                names = _names(self.oracle[name]["blocks"][0])
                self.assertEqual({key: names[pid] for key, pid in mat.PHYSICAL.items()},
                                 {key: key for key in mat.PHYSICAL})
                maps = [key for key in mat.PHYSICAL if key.endswith("_map")]
                self.assertEqual(len(maps), 9)
                for key in maps:
                    self.assertEqual(names[mat.PHYSICAL[key] + mat.PHYSICAL_SWITCH], key + "_on")

    def test_no_issues(self):
        self.assertEqual(self.conv.stats.issues, [])


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
            got = {mid: (lambda ir: ir and ir.name)(conv.material_for(multi, mid)) for mid in range(16)}
            default = conv.convert(multi)
        # IDs 1, 3, 7 (zero-based 0, 2, 6); 3 is switched off. Past the list an ID wraps modulo 7
        self.assertEqual(got, {0: "FixtureSubOne", 1: None, 2: None, 3: None, 4: None, 5: None, 6: "FixtureSubSeven",
                               7: "FixtureSubOne", 8: None, 9: None, 10: None, 11: None, 12: None,
                               13: "FixtureSubSeven", 14: "FixtureSubOne", 15: None})
        self.assertEqual(default.name, "FixtureSubOne")
        self.assertEqual((dict(conv.stats.unknown), conv.stats.issues), ({}, []))

    def test_wrappers_around_and_inside(self):
        objs = (
            _wrapper(0, classids.VRAY_MTL_WRAPPER, {0: Ref(1)}),  # wrapper -> Multi
            _multi(1, [(4, Ref(2), 1), (5, Ref(3), 1), (6, Ref(4), 1)]),
            _wrapper(2, classids.VRAY_2SIDED_MTL, {0: Ref(5)}),  # Multi -> wrapper
            _multi(3, [(5, Ref(6), 1)]),  # nested Multi: the same ID
            _multi(4, [(0, Ref(6), 1)]),  # nested Multi without ID 6
            _vray(5, "Front"), _vray(6, "Deep"),
        )
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertEqual(conv.material_for(0, 4).name, "Front")
        self.assertEqual(conv.material_for(0, 5).name, "Deep")
        self.assertEqual(conv.material_for(0, 6).name, "Deep")  # the nested Multi without ID 6 wraps it to 0
        self.assertIsNone(conv.material_for(0, 9))  # 9 mod 7 = 2: no entry either
        self.assertEqual(conv.material_for(0, 11).name, "Front")  # 11 mod 7 = 4
        self.assertIsNone(conv.material_for(0, 12))  # 12 mod 7 = 5, then 12 mod 6 = 0: no entry in the nested one
        self.assertIsNone(conv.material_for(None, 0))
        self.assertEqual(conv.material_for(5, 3).name, "Front")  # not a Multi: whatever the ID
        self.assertEqual(conv.convert(0).name, "Front")

    def test_wrap_past_the_list(self):
        # what 3ds Max 2020 renders (one face per ID): an ID without an entry takes the entry of ID modulo the
        # highest ID of the list plus one, every entry counted; IDs below are zero-based
        def names(index, ids):
            return [(lambda ir: ir and ir.name)(conv.material_for(index, mid)) for mid in ids]
        objs = (_multi(0, [(0, Ref(10), 1), (1, Ref(11), 1)]),
                _multi(1, [(2, Ref(10), 1), (6, Ref(11), 1)]),
                _multi(2, [(6, Ref(10), 1), (2, Ref(11), 1)]),
                _multi(3, [(0, Ref(10), 1), (4, Ref(11), 1), (4, Ref(12), 1)]),
                _multi(4, [(0, Ref(10), 1), (1, Ref(11), 1), (2, Ref(12), 0)]),
                _multi(5, [(0, Ref(10), 1), (1, Ref(11), 1), (2, Ref(None), 1)]),
                _multi(6, [(0, Ref(10), 1), (1, Ref(7), 1)]),
                _multi(7, [(0, Ref(12), 1), (1, Ref(13), 1), (2, Ref(14), 1)]),
                _vray(10, "R"), _vray(11, "G"), _vray(12, "B"), _vray(13, "Y"), _vray(14, "C"))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertEqual(names(0, [2, 3, 10, 13]), ["R", "G", "R", "G"])
        self.assertEqual(names(0, [-1, -2]), [None, None])  # Python's % would map -1 to 1
        self.assertEqual(names(1, [9, 13, 16]), ["R", "G", "R"])  # modulo 7, not the entry count
        self.assertEqual(names(1, [0, 1, 3, 4, 5, 7, 8, 10, 14]), [None] * 9)  # no entry after the wrap
        self.assertEqual(names(2, [9, 13]), ["G", "R"])  # by ID, not by list position
        self.assertEqual(names(3, [4, 5, 9, 10]), ["G", "R", "G", "R"])  # the first of a duplicate ID wins
        self.assertEqual(names(4, [3, 5]), ["R", None])  # the highest entry switched off still counts
        self.assertEqual(names(5, [3, 5]), ["R", None])  # and an empty one
        # nested: the inner Multi gets the face's own ID and wraps it by its own list
        self.assertEqual(names(6, [1, 3, 5, 7, 9, 11, 2]), ["Y", "B", "C", "Y", "B", "C", "R"])
        self.assertEqual(conv.stats.issues, [])

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


def _spline(ids):
    """A SplineDescription stand-in: ids, one segment material ID or the distinct ones in segment order."""
    ids = (ids,) if isinstance(ids, int) else tuple(ids)
    return types.SimpleNamespace(material=ids[0], material_ids=ids)


def _desc(curves=None, **meshes):
    """A SceneDescription stand-in: meshes {key: (users, face material IDs)}, curves {key: users, or (users, the
    material IDs of each spline: an int, or a tuple for a spline that mixes them)} (a list of users alone: one spline
    at ID 0)."""
    def curve(v):
        users, splines = (v, [0]) if isinstance(v, list) else v
        return types.SimpleNamespace(users=users, splines=[_spline(x) for x in splines])
    return types.SimpleNamespace(meshes={k: types.SimpleNamespace(users=u, material_indices=numpy.array(f,
                                                                                                      dtype=numpy.int32))
                                         for k, (u, f) in meshes.items()},
                                 curves={k: curve(v) for k, v in (curves or {}).items()}, issues=[])


def _lin(s):
    c = s / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lins(*s):
    return tuple(_lin(c) for c in s)


def _hair_color(melanin, redness, tint, diffuse=(0.0, 0.0, 0.0)):
    """CoronaHairMtl's base color as Blender's Principled Hair BSDF colors a strand (Cycles 4.2, svm/closure.h and
    closure/bsdf_util.h: melanin remapped by -ln(1 - m), the eumelanin and pheomelanin absorption, the tint's
    absorption at Radial Roughness 0.3), plus the diffuse color."""
    x = 0.3
    scale = (((((0.245 * x) + 5.574) * x - 10.73) * x + 2.532) * x - 0.215) * x + 5.969
    c = -math.log(max(1.0 - melanin, 1e-4))
    out = []
    for eu, pheo, t, d in zip((0.506, 0.841, 1.653), (0.343, 0.733, 1.924), tint, diffuse):
        sigma = c * (1.0 - redness) * eu + c * redness * pheo + (math.log(min(1.0, max(1e-4, t))) / scale) ** 2
        out.append(min(1.0, math.exp(-math.sqrt(sigma) * scale) + d))
    return tuple(out)


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
        self.close(rough.alpha.value, 200 / 255.0 * 0.8, "mean opacity color as stored x level (em3.122)")
        self.close(rough.specular.value, 1.0, "the IOR's own Fresnel: no level parameter")
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
        self.close(pbr.alpha.value, 230 / 255.0 * 0.9)  # a data input: the swatch as stored
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
        self.assertEqual([r for _i, r in conv.stats.issues],
                         ["CoronaLegacyMtl 'FixtureCoronaLegacyGloss': glossiness of PBR mode off read as in PBR mode"])

    def test_layered_mixes_its_layer_or_peels_without_a_base(self):
        cf, graph, by_name = _fixture("corona_layered")
        with cf:
            conv = mat.MaterialConverter(graph)
            layered = conv.convert(by_name["FixtureCoronaLayered"])
            base = conv.convert(by_name["FixtureCoronaLayerBase"])
            coat = conv.convert(by_name["FixtureCoronaLayerCoat"])
            nobase = conv.convert(by_name["FixtureCoronaLayeredNoBase"])
            only = by_name["FixtureCoronaLayerOnly"]
            self.assertEqual(conv.peel(by_name["FixtureCoronaLayered"]), (by_name["FixtureCoronaLayered"], None))
            self.assertEqual(conv.peel(by_name["FixtureCoronaLayeredNoBase"]), (only, None))
        self.assertIsNot(layered, base)
        self.assertEqual((layered.name, layered.source), ("FixtureCoronaLayered", "CoronaLayeredMtl"))
        self.close(layered.base_color.value, _lins(90, 160, 70), "the base's inputs")
        self.close(layered.roughness.value, 0.45)
        self.assertEqual(len(layered.layers), 1)
        layer = layered.layers[0]
        self.assertIs(layer.ir, coat)
        self.close(layer.amount, 0.5)
        self.assertEqual(layer.mask.index, by_name["FixtureCLayerMask"])
        self.close(layer.mask.amount, 1.0, "mask amount")
        self.assertIsNone(layer.graph, "no TexmapConverter")
        self.assertEqual(base.layers, [], "the base itself is untouched")
        self.assertEqual(nobase.name, "FixtureCoronaLayerOnly")
        self.close(nobase.base_color.value, _lins(70, 80, 200))
        self.assertEqual(conv.stats.peeled, {"CoronaLayeredMtl": 1}, "only the one without a base")

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


class CoronaMore(unittest.TestCase, Close):
    """tools/fixtures/corona_more.ms, by hand (millimeters, gamma off)."""

    @classmethod
    def setUpClass(cls):
        cls.cf, cls.graph, cls.by_name = _fixture("corona_more")
        cls.conv = mat.MaterialConverter(cls.graph)
        cls.irs = {n: cls.conv.convert(i) for n, i in cls.by_name.items()}

    @classmethod
    def tearDownClass(cls):
        cls.cf.close()

    def ir(self, name):
        return self.irs["FixtureCorona" + name]

    def test_meters_from_the_file(self):
        self.close(self.conv.meters, 0.001)

    def test_physical_sss(self):
        ir = self.ir("PhysSss")
        self.close(ir.subsurface_weight, 0.6)
        self.close(ir.subsurface_radius, 0.0025, "2.5 mm")
        self.close(ir.subsurface_color, _lins(220, 80, 50))
        self.close(ir.base_color.value, _lins(230, 190, 170))
        self.assertEqual(ir.issues, [])

    def test_physical_sheen(self):
        ir = self.ir("PhysSheen")
        self.close(ir.sheen_weight, 0.7)
        self.close(ir.sheen_color, _lins(250, 200, 230))
        self.close(ir.sheen_roughness, 0.4)
        self.assertEqual(ir.issues, ["CoronaPhysicalMtl 'FixtureCoronaPhysSheen': sheen amount map not converted"])

    def test_physical_named_issues(self):
        self.assertEqual(self.ir("PhysTransl").issues,
                         ["CoronaPhysicalMtl 'FixtureCoronaPhysTransl': translucency not converted"])
        absorb = self.ir("PhysAbsorb")
        self.close(absorb.transmission.value, 1.0)
        self.assertEqual(absorb.issues, ["CoronaPhysicalMtl 'FixtureCoronaPhysAbsorb': volumetric absorption and "
                                         "scattering not converted"])
        self.assertEqual(self.ir("PhysEdge").issues,
                         ["CoronaPhysicalMtl 'FixtureCoronaPhysEdge': metal edge color not converted"])
        self.assertEqual(self.ir("PhysIorMode").issues,
                         ["CoronaPhysicalMtl 'FixtureCoronaPhysIorMode': IOR mode 1 read as an IOR"])

    def test_physical_complex_ior(self):
        ir = self.ir("PhysComplex")
        want = tuple(mat.f0_from_complex_ior(n, k) for n, k in ((0.2, 3.9), (0.9, 2.4), (1.1, 2.2)))
        self.close(ir.base_color.value, want)
        self.close(ir.metallic.value, 1.0)
        self.close(ir.roughness.value, 0.3)
        self.assertEqual(ir.issues, [], "no edge color issue: the complex IOR stands for it")

    def test_legacy_sss(self):
        ir = self.ir("LegacySss")
        self.close(ir.subsurface_weight, 0.8)
        self.close(ir.subsurface_radius, 0.0015)
        self.close(ir.subsurface_color, _lins(200, 60, 40))
        self.assertEqual(ir.issues, [])

    def test_legacy_without_pbr(self):
        ir = self.ir("LegacyNoPbr")
        self.close(ir.roughness.value, 0.4)
        self.close(ir.transmission.value, 0.5)
        self.assertEqual(ir.issues, [
            "CoronaLegacyMtl 'FixtureCoronaLegacyNoPbr': glossiness of PBR mode off read as in PBR mode",
            "CoronaLegacyMtl 'FixtureCoronaLegacyNoPbr': translucency not converted",
            "CoronaLegacyMtl 'FixtureCoronaLegacyNoPbr': absorption not converted"])

    def test_layered(self):
        ir = self.ir("Layers")
        self.assertEqual(ir.source, "CoronaLayeredMtl")
        self.close(ir.base_color.value, _lins(90, 160, 70), "the base")
        self.assertEqual([la.ir.name for la in ir.layers], ["FixtureCoronaLayersOne", "FixtureCoronaLayersTwo"],
                         "the switched-off third layer left out")
        one, two = ir.layers
        self.close((one.amount, two.amount), (0.3, 0.6))
        self.assertIsNone(one.mask)
        self.assertEqual(two.mask, mat.MapRef(self.by_name["FixtureCLayersMask"], 0.5))
        self.assertIs(two.ir, self.ir("LayersTwo"))
        self.close(two.ir.base_color.value, _lins(200, 60, 40))
        self.assertEqual(ir.issues, [])
        self.assertNotIn("CoronaLayeredMtl", self.conv.stats.peeled)

    def test_layered_mask_graph(self):
        cf, graph, by_name = _fixture("corona_more")
        with cf:
            tex = texmaps.TexmapConverter(graph)
            conv = mat.MaterialConverter(graph, texmaps=tex)
            two = conv.convert(by_name["FixtureCoronaLayers"]).layers[1]
        root = two.graph.root
        self.assertIsInstance(root, texmaps.Mix, "lerp(1, mask, mask amount)")
        self.close(root.a.value, 1.0)
        self.close(root.b.value, _lin(64))
        self.close(root.factor, 0.5)

    def test_skin(self):
        ir = self.ir("Skin")
        self.close(ir.base_color.value, tuple(c * 0.9 for c in _lins(200, 150, 120)))
        self.close(ir.subsurface_weight, 0.8)
        colors_ = [(0.521569, 0.635294, 0.666667), (0.439216, 0.156863, 0.0784314), (0.439216, 0.0784314, 0.0196078)]
        lin = [tuple(_lin(round(c * 255)) for c in col) for col in colors_]
        self.close(ir.subsurface_color, tuple(sum(c[i] for c in lin) / 3 for i in range(3)), "equal weights")
        self.close(ir.subsurface_radius, 2.0 * (0.75 + 1.5 + 4.0) / 3 * 0.001)
        self.close(ir.specular.value, 0.6)
        self.close(ir.roughness.value, 0.3)
        self.close(ir.ior, 1.45)
        self.close(ir.alpha.value, 0.9)
        self.assertEqual(ir.issues, [])

    def test_hair_defaults(self):
        ir = self.ir("Hair")
        self.assertFalse(ir.unknown)
        self.assertEqual(self.conv.stats.unknown["CoronaHairMtl"], 0)
        self.close(ir.base_color.value, _hair_color(0.5, 0.0, (1.0, 1.0, 1.0)))
        self.close(ir.roughness.value, 0.5)
        self.close(ir.ior, 1.55)
        self.close(ir.alpha.value, 1.0)
        self.assertEqual(ir.issues, [])

    def test_ray_switch_and_select_peel(self):
        self.assertIs(self.ir("RaySwitch"), self.ir("RaySwitchDirect"), "what the camera sees")
        self.assertIs(self.ir("Select"), self.ir("SelectB"), "selected 1, zero-based")
        self.assertEqual(self.conv.stats.peeled["CoronaRaySwitchMtl"], 1)
        self.assertEqual(self.conv.stats.peeled["CoronaSelectMtl"], 1)


class CoronaClasses(unittest.TestCase, Close):
    """tools/fixtures/corona_classes.ms, by hand (millimeters, gamma off)."""

    @classmethod
    def setUpClass(cls):
        cls.cf, cls.graph, cls.by_name = _fixture("corona_classes")
        cls.conv = mat.MaterialConverter(cls.graph)
        cls.irs = {n: cls.conv.convert(i) for n, i in cls.by_name.items()}

    @classmethod
    def tearDownClass(cls):
        cls.cf.close()

    def ir(self, name):
        return self.irs["FixtureCorona" + name]

    def test_hair(self):
        ir = self.ir("HairSet")
        self.assertFalse(ir.unknown)
        self.assertEqual(ir.source, "CoronaHairMtl")
        tint = tuple(0.9 * c for c in _lins(230, 200, 180))
        diffuse = tuple(0.5 * c for c in _lins(40, 30, 20))
        self.close(ir.base_color.value, _hair_color(0.3, 0.6, tint, diffuse))
        tint_map = self.graph.get(ir.base_color.map.index)
        self.assertEqual((tint_map.name, ir.base_color.map.amount), ("FixtureCHairTint", 0.5))
        self.close(ir.roughness.value, 0.3, "1 - glossiness 0.7")
        self.close(ir.ior, 1.6)
        self.close(ir.specular.value, 1.0)
        self.close(ir.alpha.value, 200 / 255 * 0.8, "the opacity swatch as stored times its level")
        self.assertEqual(ir.issues, ["CoronaHairMtl 'FixtureCoronaHairSet': tint map drawn without the melanin color",
                                     "CoronaHairMtl 'FixtureCoronaHairSet': melanin map not converted"])

    def test_shadow_catchers(self):
        plain, refl = self.ir("ShadowCatcher"), self.ir("ShadowCatcherRefl")
        for ir in (plain, refl):
            self.assertTrue(ir.shadow_catcher)
            self.assertFalse(ir.unknown)
            self.close(ir.base_color.value, GREY)
        self.assertEqual(plain.issues, [])
        self.assertEqual(refl.issues, ["CoronaShadowCatcherMtl 'FixtureCoronaShadowCatcherRefl': backplate map not "
                                       "converted", "CoronaShadowCatcherMtl 'FixtureCoronaShadowCatcherRefl': "
                                       "reflection not converted"])
        self.assertFalse(self.ir("CatcherMixedPhys").shadow_catcher)
        self.assertFalse(self.ir("HairSet").shadow_catcher)

    def test_named_greys(self):
        for name, cls, what in (("Volume", "CoronaVolumeMtl", "volume not converted"),
                                ("Scanned", "CoronaScannedMtl", "scanned material (.ctf) not read"),
                                ("Slicer", "CoronaSlicerMtl", "slicing not converted")):
            ir = self.ir(name)
            self.assertTrue(ir.unknown, name)
            self.assertEqual(ir.source, cls)
            self.close(ir.base_color.value, GREY)
            self.assertEqual(ir.issues, ["%s 'FixtureCorona%s': %s, grey" % (cls, name, what)])

    def test_no_class_without_a_rule(self):
        self.assertEqual(dict(self.conv.stats.unknown), {})

    @unittest.skipIf(numpy is None, "numpy missing")  # assign() needs it
    def test_shadow_catcher_users(self):
        s = reader_scene.Scene.from_file(self.cf)
        desc = importlib.import_module(_PKG + ".convert.scene").describe(s, 0.001, None)
        plan = mat.assign(desc, mat.node_materials(s, desc), self.conv)
        names = {n.index: n.name for n in desc.nodes}
        got = sorted(names[u] for ms in plan.values() for u in mat.shadow_catcher_users(ms))
        self.assertEqual(got, ["FixtureCoronaShadowCatcherBox", "FixtureCoronaShadowCatcherReflBox"])
        mixed = next(ms for ms in plan.values() if names[ms.users[0]] == "FixtureCoronaCatcherMixedBox")
        self.assertEqual(len(mixed.slots), 2, "the catcher and the physical material, one slot each")


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
        self.close(ir.specular.value, 1.0, "the IOR's own Fresnel")
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

    def test_legacy_reflection_map_at_full_amount_keeps_diffuse(self):
        """A reflection map at full amount hides the swatch (maxdrop-em3.133, as VRayMtl's): no metal however high
        the Fresnel IOR and bright the swatch; the specular follows the map, the base color is the diffuse."""
        for amount in (1.0, 1.5):
            _conv, ir = _convert(_corona(0, classids.CORONA_LEGACY_MTL, p101=(1.0, 0.0, 0.0), p102=(1.0, 1.0, 1.0),
                                         p122=1.0, p182=999.0, p142=Ref(1), p291=amount), _map(1))
            self.close(ir.metallic.value, 0.0, str(amount))
            self.close(ir.base_color.value, (1.0, 0.0, 0.0), str(amount))
            self.assertIsNone(ir.base_color.map)
            self.assertEqual(ir.specular.map, mat.MapRef(1, amount, False))

    def test_legacy_swatch_shows_in_proportion_below_full_amount(self):
        """Below full amount the swatch counts by its share, mean x (1 - amount); the level is in that mean (Corona's
        documentation: the level multiplies the color and the map alike)."""
        def metal(color, level, **slot):
            return _convert(_corona(0, classids.CORONA_LEGACY_MTL, p101=(1.0, 0.0, 0.0), p102=color, p122=level,
                                    p182=999.0, p142=Ref(1), **slot), _map(1))[1]
        ir = metal((0.8,) * 3, 1.0, p291=0.75)  # 0.8 x 0.25 = 0.2 shown
        self.close(ir.metallic.value, 0.0)
        self.close(ir.base_color.value, (1.0, 0.0, 0.0))
        ir = metal((1.0,) * 3, 1.0, p291=0.75)  # 1 x 0.25: the threshold
        self.close(ir.metallic.value, 1.0)
        self.close(ir.base_color.value, (1.0,) * 3)
        self.assertEqual(ir.base_color.map, mat.MapRef(1, 0.75, False))
        ir = metal((1.0,) * 3, 0.5, p291=0.5)  # 0.5 x 0.5 = 0.25 shown
        self.close(ir.metallic.value, 1.0)
        ir = metal((1.0,) * 3, 0.5, p291=0.6)  # 0.5 x 0.4 = 0.2 shown
        self.close(ir.metallic.value, 0.0)
        ir = metal((0.8,) * 3, 1.0, p162=0, p291=1.0)  # the map switched off: the whole swatch
        self.close(ir.metallic.value, 1.0)
        self.assertIsNone(ir.base_color.map)

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

    def test_layered_cycle_and_a_layer_that_is_not_a_material(self):
        a = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(2), Ref(3)])
        b = _corona(1, classids.CORONA_PHYSICAL_MTL)
        c = _corona(2, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(0)])  # back to a
        conv, ir = _convert(a, b, c, _map(3))
        self.assertEqual([la.ir.index for la in ir.layers], [2])
        inner = ir.layers[0].ir
        self.assertEqual(len(inner.layers), 1)
        self.assertTrue(inner.layers[0].ir.unknown, "the cycle back to a: grey")
        self.assertTrue(any("material cycle" in r for _i, r in conv.stats.issues))
        self.assertTrue(any("is not a material" in r for _i, r in conv.stats.issues), "the map in layer 2")

    def test_layered_with_an_empty_wrapper_or_a_dangling_layer(self):
        layered = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(2), Ref(9)])
        empty = FakeMtl(2, classids.VRAY_2SIDED_MTL, "Empty", {0: {0: Ref(None), 1: Ref(None)}})
        conv, ir = _convert(layered, _corona(1, classids.CORONA_PHYSICAL_MTL), empty)
        self.assertEqual(ir.source, "CoronaLayeredMtl")
        self.assertTrue(all(la.ir.unknown for la in ir.layers), "the empty wrapper: grey, no exception")

    def test_layered_fan_out_is_bounded(self):
        objects = [_corona(i, classids.CORONA_LAYERED_MTL, p1000=Ref(20), p1001=[Ref(i + 1)] * 16) for i in range(9)]
        objects.append(_corona(9, classids.CORONA_PHYSICAL_MTL))
        objects.append(_corona(20, classids.CORONA_PHYSICAL_MTL))
        conv, ir = _convert(*objects)
        self.assertLessEqual(conv.bsdf_count(ir), mat.MAX_LAYER_BSDFS)
        self.assertTrue(any("Principled BSDFs not mixed" in r for _i, r in conv.stats.issues))

    def test_complex_ior_extremes(self):
        for n, k in ((-1.0, 0.0), (1e200, 1e200), (0.0, 0.0)):
            f0 = mat.f0_from_complex_ior(n, k)
            self.assertTrue(0.0 <= f0 <= 1.0, (n, k, f0))

    def test_layered_caps_its_layers(self):
        n = mat.MAX_LAYERS + 2
        layered = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(1)] * n, p1002=[0.5] * n)
        conv, ir = _convert(layered, _corona(1, classids.CORONA_PHYSICAL_MTL))
        self.assertEqual(len(ir.layers), mat.MAX_LAYERS)
        self.assertTrue(any("only the first" in r for r in ir.issues))

    def test_layered_mask_switched_off_and_amounts(self):
        layered = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(1), Ref(1)], p1002=[0.25, 2.0],
                          p1003=[Ref(2), Ref(2)], p1005=[0, 1], p1006=[1.0, 0.4])
        conv, ir = _convert(layered, _corona(1, classids.CORONA_PHYSICAL_MTL), _map(2))
        self.assertEqual([(la.amount, la.mask) for la in ir.layers],
                         [(0.25, None), (2.0, mat.MapRef(2, 0.4))])

    def test_ray_switch_and_select(self):
        rs = _corona(0, classids.CORONA_RAY_SWITCH_MTL, p1600=Ref(1), p1603=Ref(2), p1613=0)
        conv, ir = _convert(rs, _corona(1, classids.CORONA_PHYSICAL_MTL), _corona(2, classids.CORONA_LEGACY_MTL))
        self.assertEqual(conv.peel(0), (1, None), "direct switched off: the GI material")
        sel = _corona(0, classids.CORONA_SELECT_MTL, p312=[Ref(1), Ref(None)], p313=1)
        conv, ir = _convert(sel, _corona(1, classids.CORONA_PHYSICAL_MTL))
        self.assertTrue(ir.unknown)
        self.assertIn("selected 1 is empty", ir.issues[0])
        conv, ir = _convert(_corona(0, classids.CORONA_SELECT_MTL, p312=[Ref(1)], p313=5),
                            _corona(1, classids.CORONA_PHYSICAL_MTL))
        self.assertIn("selected 5 has no material", ir.issues[0])

    def test_complex_ior_f0(self):
        self.close(mat.f0_from_complex_ior(1.5, 0.0), 0.04)
        self.close(mat.f0_from_complex_ior(0.2, 3.9), ((0.8 ** 2) + 3.9 ** 2) / (1.2 ** 2 + 3.9 ** 2))

    def test_meters_default_and_given(self):
        conv = mat.MaterialConverter(FakeGraph(_corona(0, classids.CORONA_PHYSICAL_MTL, p291=0.5, p301=2.0)))
        self.close(conv.meters, mat.DEFAULT_METERS, "a graph without a scene")
        self.close(conv.convert(0).subsurface_radius, 2.0 * 0.0254)
        conv = mat.MaterialConverter(FakeGraph(_corona(0, classids.CORONA_PHYSICAL_MTL, p291=0.5, p301=2.0)),
                                     meters=0.01)
        self.close(conv.convert(0).subsurface_radius, 0.02)

    def test_layered_with_nothing_set_is_grey(self):
        conv, ir = _convert(_corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(None), p1001=[Ref(None)] * 3))
        self.assertTrue(ir.unknown)
        self.close(ir.base_color.value, GREY)
        self.assertTrue(any("no sub-material" in r for _i, r in conv.stats.issues))

    def test_hair_defaults(self):
        conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL))
        self.close(ir.base_color.value, _hair_color(0.5, 0.0, (1.0, 1.0, 1.0)))
        self.close(ir.roughness.value, 0.5)
        self.close(ir.ior, 1.55)
        self.assertEqual((ir.issues, dict(conv.stats.unknown)), ([], {}))

    def test_hair_color_numbers(self):
        """Literal numbers, apart from _hair_color: Corona's default (melanin 0.5) is a dark brown."""
        self.close(mat.HAIR_ROUGHNESS_SCALE, 5.888415, "Cycles' polynomial at 0.3")
        got = mat.hair_color(0.5, 0.0, (1.0, 1.0, 1.0))
        for g, want in zip(got, (0.030584, 0.011156, 0.001831)):
            self.assertAlmostEqual(g, want, delta=2e-6)
        self.close(mat.hair_color(0.0, 0.0, (0.5, 0.25, 1.0)), (0.5, 0.25, 1.0), "no melanin: the tint itself")

    def test_hair_tint_map_without_melanin_is_no_issue(self):
        conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=0.0, p112=Ref(1)), _map(1))
        self.assertEqual((ir.base_color.map, ir.issues), (mat.MapRef(1, 1.0), []))

    def test_layered_over_a_shadow_catcher_is_no_shadow_catcher(self):
        layered = _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(2)], p1004=[1])
        conv, ir = _convert(layered, _corona(1, classids.CORONA_SHADOW_CATCHER_MTL),
                            _corona(2, classids.CORONA_PHYSICAL_MTL))
        self.assertEqual(len(ir.layers), 1)
        self.assertFalse(ir.shadow_catcher)
        self.assertTrue(conv.convert(1).shadow_catcher, "the catcher itself still is one")

    def test_hair_melanin_bounds(self):
        _conv, black = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=1.0, p142=0.5))
        self.close(black.base_color.value, _hair_color(1.0, 0.5, (1.0, 1.0, 1.0)), "1 - melanin floored at 1e-4")
        _conv, white = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=0.0))
        self.close(white.base_color.value, (1.0, 1.0, 1.0), "no pigment, a white tint")
        _conv, inked = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=0.0, p101=(0.0, 0.0, 0.0)))
        self.close(inked.base_color.value, _hair_color(0.0, 0.0, (0.0, 0.0, 0.0)), "a black tint floored at 1e-4")
        self.assertTrue(all(c > 0 for c in inked.base_color.value))

    def test_hair_diffuse_added_and_clamped(self):
        _conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, p141=0.0, p102=(1.0, 0.5, 0.0), p105=0.5))
        self.close(ir.base_color.value, (1.0, 1.0, 1.0), "white plus the diffuse, at most 1")
        _conv, ir = _convert(_corona(0, classids.CORONA_HAIR_MTL, p102=(1.0, 0.5, 0.0), p105=0.5))
        self.close(ir.base_color.value, _hair_color(0.5, 0.0, (1.0, 1.0, 1.0), (0.5, 0.25, 0.0)))

    def test_hair_maps(self):
        maps = [_map(i) for i in range(1, 6)]
        hair = _corona(0, classids.CORONA_HAIR_MTL, p114=Ref(1), p132=0.4, p116=Ref(2), p120=Ref(3), p138=0.5,
                       p155=Ref(4), p163=Ref(5), p164=0)
        conv, ir = _convert(hair, *maps)
        self.assertEqual(ir.alpha.map, mat.MapRef(1, 0.4))
        self.assertEqual(ir.roughness.map, mat.MapRef(2, 1.0, True))
        self.assertEqual(ir.bump, mat.MapRef(3, 0.5))
        self.assertEqual(ir.issues, ["CoronaHairMtl 'C': transmission map not converted"], "the glint map is off")

    def test_volume_scanned_slicer_named(self):
        for key, what in ((classids.CORONA_VOLUME_MTL, "volume"), (classids.CORONA_SCANNED_MTL, "scanned"),
                          (classids.CORONA_SLICER_MTL, "slicing")):
            conv, ir = _convert(_corona(0, key))
            self.assertTrue(ir.unknown)
            self.close(ir.base_color.value, GREY)
            self.assertEqual(len(ir.issues), 1)
            self.assertIn(what, ir.issues[0])
            self.assertEqual(dict(conv.stats.unknown), {})

    def test_shadow_catcher_defaults(self):
        conv, ir = _convert(_corona(0, classids.CORONA_SHADOW_CATCHER_MTL))
        self.assertTrue(ir.shadow_catcher)
        self.assertEqual((ir.issues, dict(conv.stats.unknown)), ([], {}))
        _conv, off = _convert(_corona(0, classids.CORONA_SHADOW_CATCHER_MTL, p302=Ref(1), p360=0),
                              _map(1))
        self.assertEqual(off.issues, [], "a backplate map switched off")

    def test_shadow_catcher_users(self):
        catcher, other = mat.MaterialIR(0, "a", shadow_catcher=True), mat.MaterialIR(1, "b")
        plan = mat.MeshSlots([10, 11, 12], [[catcher, catcher, catcher], [catcher, other, None]], None)
        self.assertEqual(mat.shadow_catcher_users(plan), [10], "every slot of the user a catcher")
        self.assertEqual(mat.shadow_catcher_users(mat.MeshSlots([10], [], None)), [], "no slot, no catcher")


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
        self.assertEqual(plan.curves, {})

    def test_curves(self):
        """One slot: what each user gets for material ID 1 (a Multi/Sub-Object by that ID, none when its entry is
        off); no plan when no user has a material. The same key for a mesh and a curve: two dicts."""
        objs = (_vray(4, "Plain"), _vray(5, "Other"), _multi(6, [(0, Ref(5), 1), (1, Ref(4), 1)]),
                _multi(7, [(0, Ref(4), 0), (1, Ref(5), 1)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        curves = {"one": [1, 2], "two": [3, 4], "multi": [5], "off": [6], "bare": [7], "k": [8]}
        plan = mat.assign(_desc(curves=curves, k=([1], [0])), {1: 4, 2: 4, 3: 4, 4: 5, 5: 6, 6: 7, 7: None, 8: 5},
                          conv)
        self.assertIsInstance(plan, mat.Slots)
        got = {k: (p.users, self.names(p.slots), p.indices.tolist()) for k, p in plan.curves.items()}
        self.assertEqual(got, {"one": ([1, 2], [["Plain", "Plain"]], [0]), "two": ([3, 4], [["Plain", "Other"]], [0]),
                               "multi": ([5], [["Other"]], [0]), "k": ([8], [["Other"]], [0])})
        self.assertEqual(plan.curves["k"].indices.dtype.name, "int32")
        self.assertEqual(self.names(plan["k"].slots), [["Plain"]])

    def test_curve_splines(self):
        """Each spline on the slot of its material ID: slots in ID order, indices per spline; IDs a plain material
        gives alike share one slot; an ID whose entry is off is an empty slot beside the others."""
        objs = (_vray(4, "Plain"), _vray(5, "Other"), _multi(6, [(0, Ref(4), 1), (1, Ref(5), 1)]),
                _multi(7, [(0, Ref(4), 1), (1, Ref(5), 0)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        desc = _desc(curves={"multi": ([1], [1, 0, 1]), "plain": ([2], [1, 0]), "gap": ([3], [0, 1]),
                             "both": ([1, 2], [1, 0])})
        plan = mat.assign(desc, {1: 6, 2: 4, 3: 7}, conv)
        got = {k: (self.names(p.slots), p.indices.tolist()) for k, p in plan.curves.items()}
        self.assertEqual(got, {"multi": ([["Plain"], ["Other"]], [1, 0, 1]), "plain": ([["Plain"]], [0, 0]),
                               "gap": ([["Plain"], [None]], [0, 1]),
                               "both": ([["Plain", "Plain"], ["Other", "Plain"]], [1, 0])})
        self.assertEqual(plan.curves["multi"].indices.dtype.name, "int32")
        self.assertEqual(desc.issues, [])

    def test_curve_mixed_ids(self):
        """A spline mixing IDs is drawn with its first segment's: an issue (once, on the curve's first user) only
        when a user gets another material for one of its other IDs."""
        objs = (_vray(4, "Plain"), _vray(5, "Other"), _multi(6, [(0, Ref(4), 1), (1, Ref(5), 1)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        desc = _desc(curves={"multi": ([1, 2], [0, (1, 0), (1, 0, 2)]), "plain": ([3], [(1, 0)])})
        plan = mat.assign(desc, {1: 4, 2: 6, 3: 4}, conv)
        got = {k: (self.names(p.slots), p.indices.tolist()) for k, p in plan.curves.items()}
        self.assertEqual(got, {"multi": ([["Plain", "Plain"], ["Plain", "Other"]], [0, 1, 1]),
                               "plain": ([["Plain"]], [0])})
        self.assertEqual(desc.issues, [(1, "shape: spline 2 mixes material IDs 2, 1: drawn with ID 2's material "
                                           "(its first segment's)")])

    def test_curve_mixed_ids_convert_no_unused_material(self):
        """The mixed-ID check converts nothing: a sub-material only a mixed spline's other ID picks is not converted
        (no IR, no counts), the issue is named all the same."""
        objs = (_vray(4, "Used"), FakeMtl(5, classdir.ClassId(0x1234, 0x5678), "Unused", {}),
                _multi(6, [(0, Ref(4), 1), (1, Ref(5), 1)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        desc = _desc(curves={"c": ([1], [(0, 1)])})
        plan = mat.assign(desc, {1: 6}, conv)
        self.assertEqual(self.names(plan.curves["c"].slots), [["Used"]])
        self.assertNotIn(5, conv._done)
        self.assertEqual(dict(conv.stats.unknown), {})
        self.assertEqual(len(desc.issues), 1)
        self.assertEqual(conv.source_for(6, 1), 5)
        self.assertEqual(conv.source_for(6, 0), 4)
        self.assertIsNone(conv.source_for(None, 0))

    def test_fixture_curves(self):
        """shapes_more: FixtureCurveStd has a Standard material, FixtureCurveMulti a Multi/Sub-Object (ID 1:
        FixtureCurveSubOne); FixtureCurveIds the same Multi/Sub-Object on splines at IDs 2 and 1, FixtureCurveMixed
        on one spline at IDs 2, 1, 1; the other shapes none."""
        cf, graph, _by_name = _fixture("shapes_more")
        with cf:
            s = reader_scene.Scene.from_file(cf)
            desc = importlib.import_module(_PKG + ".convert.scene").describe(s, 0.001, None)
            plan = mat.assign(desc, mat.node_materials(s, desc), mat.MaterialConverter(graph))
        names = {n.index: n.name for n in desc.nodes}
        got = {names[p.users[0]]: (self.names(p.slots), p.indices.tolist()) for p in plan.curves.values()}
        self.assertEqual(got, {"FixtureCurveStd": ([["FixtureCurveRed"]], [0]),
                               "FixtureCurveMulti": ([["FixtureCurveSubOne"]], [0]),
                               "FixtureCurveIds": ([["FixtureCurveSubOne"], ["FixtureCurveSubTwo"]], [1, 0]),
                               "FixtureCurveMixed": ([["FixtureCurveSubTwo"]], [0])})
        mixed = [r for i, r in desc.issues if names.get(i) == "FixtureCurveMixed"]
        self.assertEqual(mixed, ["shape: spline 1 mixes material IDs 2, 1: drawn with ID 2's material (its first "
                                 "segment's)"])


if __name__ == "__main__":
    unittest.main()
