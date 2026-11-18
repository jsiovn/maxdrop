# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/lights.py: VRayLights as light descriptions, no Blender.

The ported formulas (watts per units mode and type, the Kelvin color) against values computed by hand; the
vray_lights fixture (tools/fixtures/vray_lights.ms) read through convert.scene against what 3ds Max 2020 + V-Ray 5.2
said of it: the watts its rules source's own ocbaby_exsVrayLightWatts computed in 3ds Max on each light, the Kelvin
color of ocbaby_exsKelvinRGB, sizes, flags and the instance sharing one light; hand-made parameter values and blocks
for the issues (animated, texture, directional, the glossy switch, contributions, a missing block).
"""
import importlib
import math
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "vray_lights.max")

# A package named apart from the add-on whose path is maxdrop/: relative imports resolve, maxdrop/__init__.py (which
# imports bpy) never runs.
_PKG = "maxdrop_lights_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
lights = importlib.import_module(_PKG + ".convert.lights")
colors = importlib.import_module(_PKG + ".convert.colors")
pblock = importlib.import_module(_PKG + ".reader.pblock")
classids = importlib.import_module(_PKG + ".reader.classids")
try:
    import numpy  # noqa: F401  convert.scene needs it for meshes
    conv = importlib.import_module(_PKG + ".convert.scene")
except ImportError:
    conv = None

L = lights
MM = 0.001
# 3ds Max 2020, the fixture loaded, the rules source's ocbaby_exsVrayLightWatts per light (toM 0.001)
MAX_WATTS = {"FixturePlane": 0.0527086444, "FixturePlaneInst": 0.0527086444, "FixturePlaneLm": 2.19619322,
             "FixtureDisc": 0.00975400303, "FixtureSphere": 40.0, "FixtureSphereKelvin": 0.252661914,
             "FixtureOff": 0.00439238735, "FixtureInvisible": 20.0, "FixtureTargeted": 25.0}
MAX_KELVIN_3500 = (255.0, 192.534, 140.827)  # ocbaby_exsKelvinRGB 3500 in 3ds Max


def values(**changes):
    """A VRayLight's parameter values: V-Ray's defaults, then changes by parameter name (P_* without P_)."""
    v = dict(L.DEFAULTS)
    v[L.P_TEXMAP] = None
    for key, value in changes.items():
        v[getattr(L, "P_" + key.upper())] = value
    return v


class Formulas(unittest.TestCase):
    """A plane 100 x 50 mm (size0 50, size1 25), a disc and a sphere of radius 50 mm, multiplier 10."""

    def watts(self, kind, units, double=False):
        return L.watts(units, 10.0, L.area(kind, 50.0, 25.0, double, MM, units))

    def test_plane_each_units_mode(self):
        for units, want in ((L.UNITS_DEFAULT, 0.10980966325036605), (L.UNITS_LM, 0.014641288433382138),
                            (L.UNITS_LM_M2_SR, 0.00022998482090701272), (L.UNITS_W, 10.0),
                            (L.UNITS_W_M2_SR, 0.15707963267948968)):
            self.assertAlmostEqual(self.watts(L.PLANE, units), want, delta=want * 1e-12, msg=units)

    def test_disc_each_units_mode(self):
        """pi r^2 in the default units; (2 r)^2 in the radiance units, as V-Ray 5.2 renders it."""
        for units, want in ((L.UNITS_DEFAULT, 0.1724886156802595), (L.UNITS_LM, 0.014641288433382138),
                            (L.UNITS_LM_M2_SR, 0.00045996964181402533), (L.UNITS_W, 10.0),
                            (L.UNITS_W_M2_SR, 0.3141592653589793)):
            self.assertAlmostEqual(self.watts(L.DISC, units), want, delta=want * 1e-12, msg=units)

    def test_sphere_each_units_mode(self):
        for units, want in ((L.UNITS_DEFAULT, 0.689954462721038), (L.UNITS_LM, 0.014641288433382138),
                            (L.UNITS_LM_M2_SR, 0.0014450372475972707), (L.UNITS_W, 10.0),
                            (L.UNITS_W_M2_SR, 0.9869604401089359)):
            self.assertAlmostEqual(self.watts(L.SPHERE, units), want, delta=want * 1e-12, msg=units)

    def test_double_sided_doubles_the_area_of_a_plane_or_disc_only(self):
        self.assertAlmostEqual(self.watts(L.PLANE, L.UNITS_W_M2_SR, True), 0.31415926535897937, delta=1e-12)
        self.assertEqual(self.watts(L.SPHERE, L.UNITS_W_M2_SR, True), self.watts(L.SPHERE, L.UNITS_W_M2_SR))
        self.assertEqual(L.area(L.MESH, 50.0, 25.0, True, MM), 1.0)

    def test_kelvin_is_the_rules_source_curve_decoded_from_srgb(self):
        lin = L.light_color(values(color_mode=1, temperature=3500.0), colors.GAMMA_ON)
        for got, byte in zip(lin, MAX_KELVIN_3500):
            c = byte / 255.0
            want = c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
            self.assertAlmostEqual(got, want, delta=1e-5)

    def test_color_mode_uses_the_swatch_rule(self):
        v = values(color=(1.0, 200 / 255.0, 150 / 255.0))
        self.assertEqual(L.light_color(v, colors.GAMMA_ON), (1.0, 200 / 255.0, 150 / 255.0))
        off = L.light_color(v, colors.GAMMA_OFF)
        self.assertAlmostEqual(off[1], 0.5775804404296506, delta=1e-9)


class Describe(unittest.TestCase):
    def test_shapes_sizes_and_power(self):
        ld, issues = L.describe(1, "plane", values(size0=50.0, size1=25.0, units=L.UNITS_W, multiplier=7.0), MM,
                                colors.GAMMA_ON)
        self.assertEqual((ld.kind, ld.shape, ld.size, ld.size_y, ld.power, issues), ("AREA", "RECTANGLE", 0.1, 0.05,
                                                                                     7.0, []))
        ld, _ = L.describe(1, "disc", values(type=L.DISC, size0=50.0), MM, colors.GAMMA_ON)
        self.assertEqual((ld.kind, ld.shape, ld.size, ld.size_y), ("AREA", "DISK", 0.1, 0.1))
        ld, _ = L.describe(1, "sphere", values(type=L.SPHERE, size0=50.0), MM, colors.GAMMA_ON)
        self.assertEqual((ld.kind, ld.shape, ld.radius), ("POINT", None, 0.05))

    def test_negative_sizes_count_as_their_size(self):
        a, _ = L.describe(1, "a", values(size0=-50.0, size1=25.0), MM, colors.GAMMA_ON)
        b, _ = L.describe(1, "b", values(size0=50.0, size1=25.0), MM, colors.GAMMA_ON)
        self.assertEqual((a.size, a.power), (b.size, b.power))

    def test_double_sided_halves_the_power(self):
        ld, issues = L.describe(1, "d", values(units=L.UNITS_W, multiplier=8.0, double_sided=1), MM, colors.GAMMA_ON)
        self.assertEqual((ld.watts, ld.power, issues), (8.0, 4.0, [L.DOUBLE_SIDED]))
        ld, issues = L.describe(1, "s", values(type=L.SPHERE, units=L.UNITS_W, multiplier=8.0, double_sided=1), MM,
                                colors.GAMMA_ON)
        self.assertEqual((ld.power, issues), (8.0, []))

    def test_not_built(self):
        for kind, reason in ((L.MESH, L.NOT_YET[L.MESH]), (L.DOME, L.NOT_YET[L.DOME]),
                             (7, "type 7 is not a VRayLight type")):
            self.assertEqual(L.describe(1, "x", values(type=kind), MM, colors.GAMMA_ON), (None, [reason]))

    def test_flags_and_issues(self):
        ld, issues = L.describe(1, "x", values(on=0, invisible=1, texmap=5, directional=0.4, affect_specular=0,
                                               diffuse=0.25), MM, colors.GAMMA_ON)
        self.assertEqual((ld.on, ld.invisible, ld.diffuse_rays, ld.glossy_rays, ld.diffuse, ld.specular),
                         (False, True, True, True, 0.25, 0.0))
        self.assertEqual(issues, [L.TEXMAP, L.DIRECTIONAL % 0.4, L.GLOSSY % ("off", "on"),
                                  L.CONTRIBUTION % ("diffuse", 0.25, "diffuse")])
        ld, issues = L.describe(1, "x", values(texmap=5, texmap_on=0, affect_diffuse=0, diffuse=0.5,
                                               affect_specular=0, affect_reflections=0), MM, colors.GAMMA_ON)
        self.assertEqual((ld.diffuse_rays, ld.glossy_rays, ld.diffuse, ld.specular, issues), (False, False, 0.0, 0.0,
                                                                                               []))


class _Block:
    def __init__(self, stored):
        self.stored = stored

    def get(self, pid, tab=0, default=None):
        return self.stored.get(pid, default)


class _Entry:
    def __init__(self, superclass, class_id):
        self.superclass, self.class_id = superclass, class_id


class _Scene:
    def __init__(self, entries, refs):
        self.entries, self._refs = entries, refs

    def __len__(self):
        return len(self.entries)

    def entry(self, i):
        return self.entries[i]

    def refs(self, i):
        return self._refs.get(i, {})


class Params(unittest.TestCase):
    def test_animated_missing_and_damaged_values_take_the_default(self):
        issues = []
        block = _Block({L.P_MULTIPLIER: pblock.Animated(4), L.P_SIZE0: float("nan"), L.P_COLOR: (1.0, None, 0.0),
                        L.P_TYPE: True})
        self.assertEqual(L._value(block, L.P_MULTIPLIER, issues), L.DEFAULTS[L.P_MULTIPLIER])
        self.assertEqual(L._value(block, L.P_SIZE0, issues), L.DEFAULTS[L.P_SIZE0])
        self.assertEqual(L._value(block, L.P_COLOR, issues), L.DEFAULTS[L.P_COLOR])
        self.assertEqual(L._value(block, L.P_TYPE, issues), L.DEFAULTS[L.P_TYPE])  # a bool is no number
        self.assertEqual(L._value(block, L.P_SIZE1, issues), L.DEFAULTS[L.P_SIZE1])
        self.assertEqual(issues, ["multiplier is animated: 30.0 is used"])

    def test_no_block_raises(self):
        light = _Entry(classids.SC_LIGHT, classids.VRAY_LIGHT)
        sc = _Scene([light, _Entry(classids.SC_LIGHT, classids.VRAY_LIGHT)], {0: {0: 1}})
        self.assertTrue(L.is_vray_light(sc, 0))
        with self.assertRaises(L.LightError):
            L.read_params(sc, 0)
        with self.assertRaises(L.LightError):
            L.read_params(_Scene([light], {}), 0)


@unittest.skipIf(conv is None, "numpy missing")
class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.desc = conv.read(FIXTURE)
        cls.by_name = {n.name: n for n in cls.desc.nodes}

    def light(self, name):
        node = self.by_name[name]
        self.assertEqual(node.kind, conv.LIGHT, name)
        return self.desc.lights[node.light]

    def test_watts_equal_3ds_max(self):
        """The rules source's own function, run in 3ds Max on each light; the disc in lm/m2/sr 4 / pi times it."""
        for name, want in MAX_WATTS.items():
            if name == "FixtureDisc":
                want *= 4.0 / math.pi
            self.assertAlmostEqual(self.light(name).watts, want, delta=want * 1e-6, msg=name)
        self.assertAlmostEqual(self.light("FixturePlaneLm").power, MAX_WATTS["FixturePlaneLm"] / 2.0, delta=1e-6)

    def test_shapes_sizes_flags(self):
        got = {n: (ld.kind, ld.shape, round(ld.size, 9), round(ld.size_y, 9), round(ld.radius, 9), ld.on,
                   ld.invisible, ld.diffuse_rays, ld.glossy_rays, ld.diffuse, ld.specular)
               for n, ld in ((n, self.light(n)) for n in MAX_WATTS)}
        self.assertEqual(got, {
            "FixturePlane": ("AREA", "RECTANGLE", 0.04, 0.02, 0.0, True, False, True, True, 1.0, 1.0),
            "FixturePlaneInst": ("AREA", "RECTANGLE", 0.04, 0.02, 0.0, True, False, True, True, 1.0, 1.0),
            "FixturePlaneLm": ("AREA", "RECTANGLE", 0.03, 0.03, 0.0, True, False, True, True, 1.0, 1.0),
            "FixtureDisc": ("AREA", "DISK", 0.03, 0.03, 0.0, True, False, True, True, 1.0, 1.0),
            "FixtureSphere": ("POINT", None, 0.0, 0.0, 0.005, True, False, True, True, 1.0, 1.0),
            "FixtureSphereKelvin": ("POINT", None, 0.0, 0.0, 0.008, True, False, True, True, 1.0, 1.0),
            "FixtureOff": ("AREA", "RECTANGLE", 0.02, 0.02, 0.0, False, False, True, True, 1.0, 1.0),
            "FixtureInvisible": ("AREA", "DISK", 0.02, 0.02, 0.0, True, True, True, False, 0.5, 0.0),
            "FixtureTargeted": ("AREA", "RECTANGLE", 0.02, 0.01, 0.0, True, False, True, True, 1.0, 1.0)})

    def test_colors(self):
        """The fixture is saved with the gamma off: swatches decoded from sRGB."""
        plane = self.light("FixturePlane").color
        self.assertAlmostEqual(plane[1], 0.5775804404296506, delta=1e-6)
        kelvin = self.light("FixtureSphereKelvin").color
        for got, want in zip(kelvin, (1.0, 0.5304000515606031, 0.2656427877066154)):
            self.assertAlmostEqual(got, want, delta=1e-5)

    def test_instances_share_one_light(self):
        plane, inst = self.by_name["FixturePlane"], self.by_name["FixturePlaneInst"]
        self.assertEqual(plane.light, inst.light)
        self.assertEqual(self.desc.lights[plane.light].users, [plane.index, inst.index])
        self.assertEqual(len(self.desc.lights), 8)

    def test_mesh_and_dome_are_empties_not_placeholders(self):
        for name in ("FixtureMesh", "FixtureDome", "FixtureTargeted.Target"):
            self.assertEqual(self.by_name[name].kind, conv.EMPTY, name)
        self.assertEqual(dict(self.desc.placeholders), {})


if __name__ == "__main__":
    unittest.main()
