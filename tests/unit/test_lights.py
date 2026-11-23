# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/lights.py: VRayLights as light descriptions, no Blender.

The ported formulas (watts per units mode and type, the Kelvin color) against values computed by hand; the
vray_lights fixture (tools/fixtures/vray_lights.ms) read through convert.scene against what 3ds Max 2020 + V-Ray 5.2
said of it: the watts its rules source's own ocbaby_exsVrayLightWatts computed in 3ds Max on each light, the Kelvin
color of ocbaby_exsKelvinRGB, sizes, flags and the instance sharing one light; hand-made parameter values and blocks
for the issues (animated, texture, directional, the glossy switch, contributions, a missing block). The vray_dome
fixture (tools/fixtures/vray_dome.ms): the dome that is the World, its texture's projection, the second dome, the
mesh light's emitter, the scaled spheres as V-Ray 5.2 renders them (X scale only); hand-made texture graphs for the
rules of dome_texture. Mesh lights: the radiance of emitter_radiance against the V-Ray 5.2 renders of
docs/FORMAT.md "VRayLight" (a 200 x 200 mm source), describe_emitter's issues on hand-made values, and the
vray_mesh_light fixture (tools/fixtures/vray_mesh_light.ms): a picked source, a scaled double-sided flipped one with
an object offset, one holding its own mesh (Replace mesh with light) with a Shell, one without a mesh.
"""
import importlib
import math
import os
import sys
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "vray_lights.max")
DOME_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "vray_dome.max")
MESH_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "vray_mesh_light.max")

# A package named apart from the add-on whose path is maxdrop/: relative imports resolve, maxdrop/__init__.py (which
# imports bpy) never runs.
_PKG = "maxdrop_lights_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
lights = importlib.import_module(_PKG + ".convert.lights")
colors = importlib.import_module(_PKG + ".convert.colors")
texmaps = importlib.import_module(_PKG + ".convert.texmaps")
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
             "FixtureOff": 0.00439238735, "FixtureInvisible": 20.0, "FixtureTargeted": 25.0,
             "FixtureDiscScaled": 0.00975400303,  # the rules source ignores the node's scale
             "FixtureNoShadow": 15.0}  # by hand, not run in 3ds Max: in W the rules give the multiplier
# what MaxDrop changes: the disc in lm/m2/sr (V-Ray's (2 r)^2), the scaled one's area (2 x 1.5, measured)
FACTORS = {"FixtureDisc": 4.0 / math.pi, "FixtureDiscScaled": 4.0 / math.pi * 3.0}
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
        for kind, reason in ((L.MESH, L.EMITTER), (L.DOME, "a dome light is the World, not a light"),
                             (7, "type 7 is not a VRayLight type")):
            self.assertEqual(L.describe(1, "x", values(type=kind), MM, colors.GAMMA_ON), (None, [reason]))

    def test_a_mesh_light_is_left_to_the_scene(self):
        """Whether a mesh light has a mesh is convert.scene's to find (_emitter_mesh): not_built does not refuse it."""
        v = values(type=L.MESH, mesh_source=7)
        self.assertIsNone(L.not_built(v))
        self.assertIsNone(L.not_built(values(type=L.MESH, mesh_source=None)))
        self.assertTrue(L.is_mesh_light(v))
        self.assertFalse(L.is_mesh_light(values(type=L.DOME)))
        self.assertIsNone(L.not_built(values(type=L.DOME)))

    def test_shadow_switch(self):
        """Cast shadows (32) off: no shadows, no issue (Blender does the same); V-Ray's default on."""
        ld, issues = L.describe(1, "x", values(), MM, colors.GAMMA_ON)
        self.assertEqual((ld.shadow, issues), (True, []))
        for kind in (L.PLANE, L.DISC, L.SPHERE):
            ld, issues = L.describe(1, "x", values(type=kind, shadow=0), MM, colors.GAMMA_ON)
            self.assertEqual((ld.shadow, issues), (False, []), kind)

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


class Scale(unittest.TestCase):
    ROWS = ((2.0, 0.0, 0.0), (0.0, 0.0, 1.5), (0.0, -1.0, 0.0), (5.0, 6.0, 7.0))  # turned about X, scaled 2, 1.5, 1

    def test_area_scale(self):
        self.assertEqual(L.area_scale(values(), self.ROWS), 3.0)
        self.assertEqual(L.area_scale(values(type=L.DISC, units=L.UNITS_W_M2_SR), self.ROWS), 3.0)
        self.assertEqual(L.area_scale(values(type=L.SPHERE, units=L.UNITS_LM_M2_SR), self.ROWS), 4.0)
        for units in (L.UNITS_LM, L.UNITS_W):
            self.assertEqual(L.area_scale(values(units=units), self.ROWS), 1.0)
            # a sphere's radius follows its X scale in every units mode: its key holds it
            self.assertEqual(L.area_scale(values(type=L.SPHERE, units=units), self.ROWS), 4.0)
        self.assertEqual(L.area_scale(values(), ((0.0,) * 3,) * 4), 1.0)  # a zero scale
        self.assertEqual(L.area_scale(values(), ((float("inf"), 0.0, 0.0),) * 4), 1.0)

    def test_the_power_takes_the_scale(self):
        a, _ = L.describe(1, "a", values(units=L.UNITS_W_M2_SR), MM, colors.GAMMA_ON)
        b, _ = L.describe(1, "b", values(units=L.UNITS_W_M2_SR), MM, colors.GAMMA_ON, 3.0)
        self.assertAlmostEqual(b.watts, 3.0 * a.watts, delta=1e-12)
        self.assertEqual((a.size, a.size_y), (b.size, b.size_y))  # Blender scales the object's light itself

    def test_a_sphere_takes_its_x_scale_only(self):
        """V-Ray 5.2 renders: (1, 2, 1), (1, 1, 2) and (1, 2, 3) leave a sphere as it is, (2, 1, 1) quadruples its
        flux in the area units and doubles its radius (in lm and W the flux stays)."""
        def rows(sx, sy, sz):
            return ((sx, 0.0, 0.0), (0.0, sy, 0.0), (0.0, 0.0, sz), (0.0, 0.0, 0.0))
        for units in (L.UNITS_W_M2_SR, L.UNITS_W):
            v = values(type=L.SPHERE, size0=5.0, units=units)
            one, _ = L.describe(1, "a", v, MM, colors.GAMMA_ON)
            for scale in ((1.0, 2.0, 1.0), (1.0, 1.0, 2.0), (1.0, 2.0, 3.0)):
                self.assertEqual(L.area_scale(v, rows(*scale)), 1.0, scale)
            s = L.area_scale(v, rows(2.0, 1.0, 1.0))
            wide, _ = L.describe(1, "b", v, MM, colors.GAMMA_ON, s)
            self.assertAlmostEqual(wide.radius, 2.0 * one.radius, delta=1e-12)
            self.assertAlmostEqual(wide.watts, (4.0 if units == L.UNITS_W_M2_SR else 1.0) * one.watts, delta=1e-12)

    def test_a_power_out_of_range_is_zero(self):
        ld, issues = L.describe(1, "x", values(size0=1e30, size1=1e30, multiplier=1e30, units=L.UNITS_W_M2_SR),
                                1.0, colors.GAMMA_ON, 1e200)
        self.assertEqual((ld.watts, ld.power, issues), (0.0, 0.0, [L.NOT_FINITE % (1e30, 1e30)]))


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

    def test_shadow_switch_not_stored_or_animated_is_on(self):
        issues = []
        self.assertEqual(L._value(_Block({}), L.P_SHADOW, issues), 1)
        self.assertEqual(L._value(_Block({L.P_SHADOW: pblock.Animated(2)}), L.P_SHADOW, issues), 1)
        self.assertEqual(L._value(_Block({L.P_SHADOW: 0}), L.P_SHADOW, issues), 0)
        self.assertEqual(issues, ["castShadows is animated: 1 is used"])

    def test_no_block_raises(self):
        light = _Entry(classids.SC_LIGHT, classids.VRAY_LIGHT)
        sc = _Scene([light, _Entry(classids.SC_LIGHT, classids.VRAY_LIGHT)], {0: {0: 1}})
        with self.assertRaises(L.LightError):
            L.read_params(sc, 0)
        with self.assertRaises(L.LightError):
            L.read_params(_Scene([light], {}), 0)


@unittest.skipIf(conv is None, "numpy missing")
class SceneHook(unittest.TestCase):
    """convert.scene._light: the reasons and issues of instances of one VRayLight."""
    IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
    BIG = ((2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))

    def hook(self, read, worlds):
        desc = conv.SceneDescription(MM)
        unlit, params = {}, {}
        sc = _Scene([_Entry(classids.SC_LIGHT, classids.VRAY_LIGHT)], {})
        with mock.patch.object(L, "read_params", read):
            keys = [conv._light(sc, desc, unlit, params, 0, node, "n%d" % node, MM, colors.GAMMA_ON, world)
                    for node, world in enumerate(worlds, 10)]
        return desc, keys

    def test_a_damaged_light_is_named_on_every_node(self):
        def read(scene, i, assets=None, ies_files=None):
            raise L.LightError("damaged")
        desc, keys = self.hook(read, [self.IDENTITY, self.IDENTITY])
        self.assertEqual(keys, [None, None])
        self.assertEqual(desc.issues, [(10, "light: not built: parameters cannot be read: damaged"),
                                       (11, "light: not built: parameters cannot be read: damaged")])
        self.assertEqual((desc.lights, dict(desc.placeholders)), ({}, {}))

    def test_the_first_dome_is_the_world_the_others_are_named(self):
        desc, keys = self.hook(lambda scene, i, assets=None, ies_files=None: (values(type=L.DOME), ["read"]),
                               [self.IDENTITY, self.IDENTITY])
        self.assertEqual(keys, [None, None])
        self.assertEqual((desc.dome.node, desc.dome.name, desc.lights, dict(desc.placeholders)), (10, "n10", {}, {}))
        self.assertEqual(desc.issues, [(10, "light: read"), (11, "light: " + L.SECOND_DOME % "n10")])

    def test_a_dome_that_is_off_is_not_the_world(self):
        desc, keys = self.hook(lambda scene, i, assets=None, ies_files=None: (values(type=L.DOME, on=0), []),
                               [self.IDENTITY])
        self.assertEqual((keys, desc.dome, desc.issues), ([None], None, [(10, "light: " + L.DOME_OFF)]))

    def test_issues_once_per_light_and_per_scale(self):
        desc, keys = self.hook(lambda scene, i, assets=None, ies_files=None: (values(double_sided=1), ["read"]),
                               [self.IDENTITY, self.IDENTITY, self.BIG])
        self.assertEqual(keys, [(0, 1.0), (0, 1.0), (0, 4.0)])
        self.assertEqual(desc.issues, [(10, "light: read"), (10, "light: " + L.DOUBLE_SIDED),
                                       (12, "light: " + L.DOUBLE_SIDED)])
        self.assertEqual([desc.lights[k].users for k in sorted(desc.lights)], [[10, 11], [12]])
        self.assertAlmostEqual(desc.lights[(0, 4.0)].watts, 4.0 * desc.lights[(0, 1.0)].watts, delta=1e-12)


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
        """The rules source's own function, run in 3ds Max on each light, times FACTORS."""
        for name, want in MAX_WATTS.items():
            want *= FACTORS.get(name, 1.0)
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
            "FixtureTargeted": ("AREA", "RECTANGLE", 0.02, 0.01, 0.0, True, False, True, True, 1.0, 1.0),
            "FixtureDiscScaled": ("AREA", "DISK", 0.03, 0.03, 0.0, True, False, True, True, 1.0, 1.0),
            "FixtureNoShadow": ("AREA", "RECTANGLE", 0.02, 0.02, 0.0, True, False, True, True, 1.0, 1.0)})

    def test_shadows(self):
        """FixtureNoShadow's own Cast shadows is off (parameter 32 as saved); the others keep V-Ray's default on."""
        got = {n: self.light(n).shadow for n in MAX_WATTS}
        self.assertEqual(got, {n: n != "FixtureNoShadow" for n in MAX_WATTS})

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
        self.assertEqual(len(self.desc.lights), 10)

    def test_a_scaled_instance_gets_its_own_light(self):
        disc, big = self.by_name["FixtureDisc"], self.by_name["FixtureDiscScaled"]
        self.assertEqual((disc.light, big.light[0]), ((big.light[0], 1.0), disc.light[0]))
        self.assertAlmostEqual(big.light[1], 3.0, delta=1e-6)

    def test_mesh_and_dome_are_empties_not_placeholders(self):
        for name in ("FixtureMesh", "FixtureDome", "FixtureTargeted.Target"):
            self.assertEqual(self.by_name[name].kind, conv.EMPTY, name)
        self.assertEqual(dict(self.desc.placeholders), {})
        dome = self.desc.dome  # type 1, multiplier 1 in the default units, white
        self.assertEqual((dome.name, dome.color, dome.hemisphere, dome.texmap), ("FixtureDome", (1.0, 1.0, 1.0),
                                                                                 False, None))
        self.assertAlmostEqual(dome.radiance, L.DOME_RADIANCE[L.UNITS_DEFAULT], delta=1e-12)


class EmitterRules(unittest.TestCase):
    """Mesh lights: V-Ray 5.2 renders of a 200 x 200 mm source 1 m above a white floor (docs/FORMAT.md, "VRayLight")
    fit one radiance per light, the flux spread over the object-space mesh area (pi L a)."""
    A = 0.04  # m^2

    def test_radiance_each_units_mode(self):
        a = self.A
        for units, m, want in ((L.UNITS_W, 1.0, 1.0 / (math.pi * a)), (L.UNITS_LM, 683.0, 1.0 / (math.pi * a)),
                               (L.UNITS_W_M2_SR, 1.0, 1.0), (L.UNITS_LM_M2_SR, 683.0, 1.0),
                               (L.UNITS_DEFAULT, 1.0, 1500.0 / (683.0 * math.pi))):
            self.assertAlmostEqual(L.emitter_radiance(units, m, a), want, delta=want * 1e-12, msg=units)

    def test_the_renders_fit(self):
        """Floor pixels (V-Ray): W 1 0.143013, default 1 0.0125633, W/m2/sr 1 0.0179715: in the ratio of the
        radiances; W 1 seen by the camera 11.3833 = its radiance x 1.4305 (Light Strength 1.43, pi 683 / 1500)."""
        w, d, r = (L.emitter_radiance(u, 1.0, self.A) for u in (L.UNITS_W, L.UNITS_DEFAULT, L.UNITS_W_M2_SR))
        self.assertAlmostEqual(d / w, 0.0125633 / 0.143013, delta=1e-4)
        self.assertAlmostEqual(r / w, 0.0179715 / 0.143013, delta=1e-4)
        self.assertAlmostEqual(w * math.pi * 683.0 / 1500.0, 11.3833, delta=1e-3)

    def test_double_sided(self):
        """W: half the radiance on each side (floor 0.0715 against 0.143, seen 5.69 against 11.38); the radiance
        units keep theirs."""
        self.assertAlmostEqual(L.emitter_radiance(L.UNITS_W, 1.0, self.A, True),
                               L.emitter_radiance(L.UNITS_W, 1.0, self.A) / 2.0, delta=1e-12)
        self.assertEqual(L.emitter_radiance(L.UNITS_W_M2_SR, 3.0, self.A, True), 3.0)

    def test_issues(self):
        ed, issues = L.describe_emitter(1, "e", values(type=L.MESH), colors.GAMMA_ON, self.A)
        self.assertEqual((ed.camera, ed.occluder, ed.on, ed.diffuse_rays, ed.glossy_rays, issues),
                         (True, True, True, True, True, []))
        v = values(type=L.MESH, texmap=5, directional=0.5, shadow=0, affect_reflections=0, diffuse=0.5, invisible=1,
                   mesh_flip=1, on=0)
        ed, issues = L.describe_emitter(1, "e", v, colors.GAMMA_ON, self.A)
        self.assertEqual(issues, [L.EMITTER_TEXMAP, L.DIRECTIONAL % 0.5, L.EMITTER_SHADOW,
                                  L.EMITTER_GLOSSY % ("on", "off"), L.EMITTER_CONTRIBUTION % ("diffuse", 0.5)])
        self.assertEqual((ed.camera, ed.occluder, ed.on, ed.flip, ed.glossy_rays), (False, False, False, True, True))

    def test_no_area_and_bad_values(self):
        ed, issues = L.describe_emitter(1, "e", values(type=L.MESH, units=L.UNITS_W), colors.GAMMA_ON, 0.0)
        self.assertEqual((ed.radiance, issues), (0.0, [L.EMITTER_FLAT % "watts"]))
        ed, issues = L.describe_emitter(1, "e", values(type=L.MESH, units=L.UNITS_LM), colors.GAMMA_ON, 0.0)
        self.assertEqual((ed.radiance, issues), (0.0, [L.EMITTER_FLAT % "lumens"]))
        ed, issues = L.describe_emitter(1, "e", values(type=L.MESH), colors.GAMMA_ON, 0.0)  # default: no area needed
        self.assertGreater(ed.radiance, 0.0)
        ed, issues = L.describe_emitter(1, "e", values(type=L.MESH, multiplier=-2.0), colors.GAMMA_ON, self.A)
        self.assertEqual((ed.radiance, issues), (0.0, [L.NEGATIVE % ("multiplier", -2.0)]))
        ed, issues = L.describe_emitter(1, "e", values(type=L.MESH, units=L.UNITS_W, multiplier=1e300),
                                        colors.GAMMA_ON, 1e-300)
        self.assertEqual((ed.radiance, issues), (0.0, [L.OUT_OF_RANGE]))


@unittest.skipIf(conv is None, "numpy is not installed")
class MeshLightFixture(unittest.TestCase):
    """tools/fixtures/vray_mesh_light.ms in millimeters: the Plane source 40 x 20 at (0, -80, 0)."""

    @classmethod
    def setUpClass(cls):
        cls.desc = conv.read(MESH_FIXTURE)
        cls.by_name = {n.name: n for n in cls.desc.nodes}
        cls.issues = {}
        for node, reason in cls.desc.issues:
            cls.issues.setdefault(node, []).append(reason)

    def emitter(self, name):
        node = self.by_name[name]
        return node, self.desc.emitters[node.emitter], self.desc.meshes[node.mesh]

    def test_picked_source(self):
        """Default units, multiplier 2: 2 x 1500 / (683 pi); the source's object-space mesh at the light's place."""
        node, ed, md = self.emitter("FixtureEmitter")
        self.assertEqual((node.kind, ed.double_sided, ed.flip, ed.camera, ed.occluder), (conv.MESH, False, False,
                                                                                        True, True))
        self.assertAlmostEqual(ed.radiance, 2.0 * 1500.0 / (683.0 * math.pi), delta=1e-9)
        self.assertAlmostEqual(ed.area, 0.0008, delta=1e-9)
        lo, hi = md.positions.min(axis=0).tolist(), md.positions.max(axis=0).tolist()
        for got, want in zip(lo + hi, [-0.02, -0.01, 0.0, 0.02, 0.01, 0.0]):
            self.assertAlmostEqual(got, want, delta=1e-7)
        self.assertEqual(md.users, [node.index])
        self.assertNotIn(node.index, self.issues)
        self.assertEqual(self.by_name["FixtureEmitterSource"].kind, conv.MESH)  # the source stays itself

    def test_scaled_double_sided_flipped_with_an_offset(self):
        """W, multiplier 5, double-sided: 5 / (2 pi a), a the unscaled area; the offset (10, 0, 0) in the mesh."""
        node, ed, md = self.emitter("FixtureEmitterW")
        self.assertEqual((ed.double_sided, ed.flip, ed.camera, ed.occluder), (True, True, False, False))
        self.assertAlmostEqual(ed.radiance, 5.0 / (2.0 * math.pi * 0.0008), delta=1e-3)
        lo, hi = md.positions.min(axis=0).tolist(), md.positions.max(axis=0).tolist()
        for got, want in zip(lo + hi, [-0.01, -0.01, 0.0, 0.03, 0.01, 0.0]):
            self.assertAlmostEqual(got, want, delta=1e-7)
        self.assertNotEqual(node.mesh, self.by_name["FixtureEmitter"].mesh)  # another light: a mesh of its own

    def test_own_mesh_with_a_shell(self):
        """Replace mesh with light: reference 1 holds the plane (30 x 10) under a Shell; lm 100 over its area; the
        Shell named, not applied; affect specular and reflections off: no glossy rays."""
        node, ed, md = self.emitter("FixtureEmitterOwn")
        self.assertAlmostEqual(ed.area, 0.0003, delta=1e-9)
        self.assertAlmostEqual(ed.radiance, 100.0 / 683.0 / (math.pi * 0.0003), delta=1e-4)
        self.assertFalse(ed.glossy_rays)
        self.assertEqual(self.issues[node.index], ["light: " + L.EMITTER_MODIFIERS % "Shell"])
        self.assertEqual(len(md.loop_starts), 1)

    def described(self, change):
        """The fixture described with change(values) applied to the values of every mesh light read."""
        read = conv.lights.read_params

        def patched(scene, i, *args, **kw):
            values, issues = read(scene, i, *args, **kw)
            if L.is_mesh_light(values):
                change(scene, i, values)
            return values, issues

        with mock.patch.object(conv.lights, "read_params", patched):
            desc = conv.read(MESH_FIXTURE)
        by_name = {n.name: n for n in desc.nodes}
        issues = {}
        for node, reason in desc.issues:
            issues.setdefault(node, []).append(reason)
        return desc, by_name, issues

    def test_an_own_mesh_object_that_is_no_mesh_falls_back_to_the_picked_node(self):
        """Reference 1 holding something else (its parameter block, the light itself): the node of 34 still emits."""
        for target in ("block", "self"):
            def change(scene, i, values):
                values[L.MESH_OBJECT] = scene.refs(i)[0] if target == "block" else i
            _desc, by_name, issues = self.described(change)
            node = by_name["FixtureEmitter"]
            self.assertEqual((node.kind, node.index in issues), (conv.MESH, False), target)

    def test_hostile_mesh_references_leave_an_empty(self):
        """The light itself as its own mesh and as its picked node, an index out of range: an empty, a line."""
        nodes = {}

        def change(scene, i, values):
            values[L.MESH_OBJECT] = i
            values[L.P_MESH_SOURCE] = nodes.setdefault(i, next(n for n in scene.walk() if scene.node(n).object
                                                               is not None and scene.object_stack(
                                                                   scene.node(n).object).base == i))
        _desc, by_name, issues = self.described(change)
        node = by_name["FixtureEmitter"]
        self.assertEqual(node.kind, conv.EMPTY)
        self.assertEqual(issues[node.index], ["light: not built: " + L.EMITTER_CLASS % "VRayLight"])

        def far(scene, i, values):
            values[L.MESH_OBJECT] = None
            values[L.P_MESH_SOURCE] = len(scene) + 5
        _desc, by_name, issues = self.described(far)
        node = by_name["FixtureEmitter"]
        self.assertEqual((node.kind, issues[node.index]), (conv.EMPTY, ["light: not built: " + L.NO_MESH]))

    def test_off(self):
        """A mesh light that is off: built, its description off (build hides it)."""
        def change(scene, i, values):
            values[L.P_ON] = 0
        desc, by_name, _issues = self.described(change)
        node = by_name["FixtureEmitter"]
        self.assertEqual((node.kind, desc.emitters[node.emitter].on), (conv.MESH, False))

    def test_no_mesh(self):
        node = self.by_name["FixtureEmitterNone"]
        self.assertEqual((node.kind, node.emitter), (conv.EMPTY, None))
        self.assertEqual(self.issues[node.index], ["light: not built: " + L.NO_MESH])
        self.assertEqual(dict(self.desc.placeholders), {})
        self.assertEqual(len(self.desc.emitters), 3)


class DomeRules(unittest.TestCase):
    ROWS = ((0.0, 2.0, 0.0), (-2.0, 0.0, 0.0), (0.0, 0.0, 2.0), (1.0, 2.0, 3.0))  # turned 90 about Z, scaled 2

    def test_strength_per_units_mode(self):
        """V-Ray 5.2 white floor under a white dome of multiplier 1: 1.00018 (default), 0.00213024 (lm modes),
        1.43109 (W modes); Cycles 1.0 per unit of World strength: so radiance x Light Strength 1.43."""
        for units, pixel in ((0, 1.00018), (1, 0.00213024), (2, 0.00213024), (3, 1.43109), (4, 1.43109)):
            dd, issues = L.describe_dome(1, "d", values(type=L.DOME, units=units, multiplier=2.0), colors.GAMMA_ON,
                                         self.ROWS)
            self.assertEqual(issues, [])
            self.assertAlmostEqual(dd.radiance * 1.43 / 2.0, pixel, delta=pixel * 0.001, msg=units)

    def test_flags_rotation_and_texture_switch(self):
        dd, issues = L.describe_dome(4, "d", values(type=L.DOME, dome_spherical=0, dome_locked=1, invisible=1,
                                                    affect_diffuse=0, affect_reflections=0, texmap=9),
                                     colors.GAMMA_ON, self.ROWS)
        self.assertEqual((dd.node, dd.hemisphere, dd.locked, dd.camera, dd.diffuse, dd.glossy, dd.texmap),
                         (4, True, True, False, False, True, 9))
        self.assertEqual(issues, [L.GLOSSY % ("on", "off")])
        for got, want in zip(dd.rotation, ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))):
            for a, b in zip(got, want):
                self.assertAlmostEqual(a, b, delta=1e-12)
        dd, _ = L.describe_dome(4, "d", values(type=L.DOME, texmap=9, texmap_on=0), colors.GAMMA_ON, self.ROWS)
        self.assertIsNone(dd.texmap)

    def test_shadows_off_is_a_line(self):
        """A World has no shadow switch: a dome with cast shadows off is a line, built as before."""
        on, _ = L.describe_dome(1, "d", values(type=L.DOME), colors.GAMMA_ON, self.ROWS)
        dd, issues = L.describe_dome(1, "d", values(type=L.DOME, shadow=0), colors.GAMMA_ON, self.ROWS)
        self.assertEqual(issues, [L.DOME_SHADOW])
        self.assertEqual((dd.radiance, dd.color, dd.camera, dd.diffuse, dd.glossy), (on.radiance, on.color, on.camera,
                                                                                    on.diffuse, on.glossy))

    def test_a_mirrored_or_flat_node_and_a_negative_multiplier(self):
        mirrored = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0), (0.0, 0.0, 0.0))
        dd, issues = L.describe_dome(1, "d", values(type=L.DOME), colors.GAMMA_ON, mirrored)
        self.assertEqual((dd.rotation[2][2], issues), (1.0, [L.DOME_MIRRORED]))
        flat = ((0.0, 0.0, 0.0),) * 4
        dd, issues = L.describe_dome(1, "d", values(type=L.DOME, multiplier=-1.0), colors.GAMMA_ON, flat)
        self.assertEqual((dd.radiance, dd.rotation[0], issues), (0.0, (1.0, 0.0, 0.0),
                                                                 [L.NEGATIVE % ("multiplier", -1.0), L.DOME_FLAT]))


class _Map:
    def __init__(self, class_id, params, parts=None, name="sky"):
        self.class_id, self.params, self.parts, self.name = class_id, params, parts or {}, name

    def param(self, pid, block_id=None, tab=0, default=None):
        return self.params.get(pid, default)


class _Graph:
    scene = None

    def __init__(self, maps):
        self.maps = maps

    def get(self, i):
        return self.maps[i]


class DomeTextureRules(unittest.TestCase):
    FOUND = object()

    def image(self, **changes):
        return texmaps.Image(3, "sky.hdr", found=self.FOUND, **changes)

    def ir(self, root, issues=()):
        return texmaps.TextureGraphIR(root, texmaps.COLOR, False, tuple(issues))

    def vray(self, params):
        p = {L.texmaps.VB_MAP_TYPE: L.VB_SPHERICAL}
        p.update(params)
        return _Graph({3: _Map(tuple(classids.VRAY_BITMAP), p)})

    def test_a_vray_bitmap_in_spherical_mapping(self):
        env = "VRayBitmap 'sky': environment mapping (type 2), drawn with the UVs"
        other = "VRayBitmap 'sky2': environment mapping (type 2), drawn with the UVs"  # not the root's: kept
        dt, issues = L.dome_texture(self.ir(self.image(), [env, other]), self.vray({L.VB_H_ROTATION: 0.5}))
        self.assertEqual((dt.image.name, dt.turn, dt.amount, issues), ("sky.hdr", 0.5, 1.0, [other]))

    def test_its_amount_and_the_issues_of_what_is_not_imported(self):
        img = self.image(output=texmaps.TexOutput(invert=True, amount=3.0), gamma=1.8,  # in sRGB: not drawn
                         crop=texmaps.Crop(0.0, 0.0, 0.5, 0.5))
        dt, issues = L.dome_texture(self.ir(img), self.vray({texmaps.VB_MAP_TYPE: 0, L.VB_V_ROTATION: math.pi,
                                                             L.VB_AXIAL: math.pi / 2.0, L.VB_H_FLIP: 1,
                                                             L.VB_V_FLIP: 1, L.VB_GROUND: 1}))
        self.assertEqual(dt.amount, 3.0)
        self.assertEqual(issues, [L.DOME_PROJECTION % ("sky.hdr", "angular"), L.DOME_VERTICAL % ("sky.hdr", 180.0),
                                  L.DOME_AXIAL % ("sky.hdr", 90.0), L.DOME_SWITCH % ("sky.hdr", "horizontal flip"),
                                  L.DOME_SWITCH % ("sky.hdr", "vertical flip"),
                                  L.DOME_SWITCH % ("sky.hdr", "ground projection"), L.DOME_OUTPUT % "sky.hdr",
                                  L.DOME_GAMMA % ("sky.hdr", 1.8), L.DOME_CROP % "sky.hdr"])

    def test_a_gamma_the_world_draws_is_no_issue(self):
        for gamma, space in ((2.2, texmaps.SRGB), (texmaps.SRGB_TWICE, texmaps.LINEAR), (0.5, texmaps.LINEAR)):
            dt, issues = L.dome_texture(self.ir(self.image(gamma=gamma, colorspace=space)), self.vray({}))
            self.assertEqual(issues, [], gamma)

    def test_a_float_texture_in_a_gamma_off_scene_keeps_its_own_decode(self):
        # the converter's gamma-off images of sky.hdr: Auto / None (2.2), sRGB (SRGB_TWICE), From 3ds Max or a Bitmap
        # (None, read as stored), inverse gamma 2 (1.1); a light keeps the map's own decode (maxdrop-em3.123)
        for gamma, space, own, own_space in ((2.2, texmaps.SRGB, 1.0, texmaps.LINEAR),
                                             (texmaps.SRGB_TWICE, texmaps.LINEAR, None, texmaps.SRGB),
                                             (None, texmaps.SRGB, 1.0, texmaps.LINEAR),
                                             (1.1, texmaps.LINEAR, 0.5, texmaps.LINEAR)):
            with self.subTest(gamma=gamma):
                dt, issues = L.dome_texture(self.ir(self.image(gamma=gamma, colorspace=space)), self.vray({}),
                                            colors.GAMMA_OFF)
                self.assertEqual(dt.image.colorspace, own_space)
                if own is None:
                    self.assertIsNone(dt.image.gamma)
                else:
                    self.assertAlmostEqual(dt.image.gamma, own, delta=1e-9)
                self.assertEqual(issues, [L.DOME_FLOAT_OFF % "sky.hdr"])
        lin = self.image(gamma=1.0, colorspace=texmaps.LINEAR)
        dt, issues = L.dome_texture(self.ir(lin), self.vray({}), colors.GAMMA_ON)
        self.assertEqual((dt.image, issues), (lin, []), "gamma on: as converted")
        png = texmaps.Image(3, "sky.png", found=self.FOUND, gamma=texmaps.SRGB_TWICE, colorspace=texmaps.LINEAR)
        dt, issues = L.dome_texture(self.ir(png), self.vray({}), colors.GAMMA_OFF)
        self.assertEqual((dt.image, issues), (png, []), "an 8-bit file: decoded once more, as on a material")

    def test_a_bitmap_is_turned_a_quarter(self):
        graph = _Graph({3: _Map(tuple(classids.BITMAP_TEX), {})})  # no Placement part: texture mapping
        dt, issues = L.dome_texture(self.ir(self.image()), graph)
        self.assertEqual((dt.turn, issues), (math.pi / 2.0, [L.DOME_PROJECTION % ("sky.hdr", "texture")]))
        tiled = self.image(mapping=texmaps.Mapping(tiling=(2.0, 1.0), environment=True))
        dt, issues = L.dome_texture(self.ir(tiled), graph)
        self.assertEqual(issues, [L.DOME_PROJECTION % ("sky.hdr", "an unknown environment mapping"),
                                  L.DOME_PLACEMENT % "sky.hdr"])

    def test_a_corona_bitmap_is_drawn_spherical_with_a_line(self):
        """V-Ray 5.2 renders a CoronaBitmap on a dome as one flat color (measured): drawn as V-Ray's spherical, the
        line says so."""
        dt, issues = L.dome_texture(self.ir(self.image()), _Graph({3: _Map(tuple(classids.CORONA_BITMAP), {})}))
        self.assertEqual((dt.turn, issues), (0.0, [L.DOME_CORONA % "sky.hdr"]))

    def test_no_texture_the_color(self):
        self.assertEqual(L.dome_texture(None, None), (None, [L.DOME_NO_TEXTURE]))
        self.assertEqual(L.dome_texture(self.ir(texmaps.Constant((1.0, 0.0, 0.0)), ["x"]), None),
                         (None, ["x", L.DOME_ROOT % "Constant"]))
        mix = texmaps.Decode(texmaps.Mix(texmaps.Constant((0.0,) * 3), texmaps.Image(3, "sky.hdr")))
        self.assertEqual(L.dome_texture(self.ir(mix), None), (None, [L.DOME_ROOT % "Mix"]), "gamma off: the Mix named")
        lost = texmaps.Image(3, "gone.png")
        self.assertEqual(L.dome_texture(self.ir(lost), None), (None, [L.DOME_NOT_FOUND % "gone.png"]))
        env = "VRayBitmap 'sky': environment mapping (type 2), drawn with the UVs"  # the root's: not named
        self.assertEqual(L.dome_texture(self.ir(lost, [env]), self.vray({})), (None, [L.DOME_NOT_FOUND % "gone.png"]))


@unittest.skipIf(conv is None, "numpy missing")
class DomeFixture(unittest.TestCase):
    """vray_dome: what 3ds Max 2020 + V-Ray 5.2 stored and rendered."""

    @classmethod
    def setUpClass(cls):
        cls.desc = conv.read(DOME_FIXTURE)
        cls.by_name = {n.name: n for n in cls.desc.nodes}

    def test_the_dome(self):
        dd = self.desc.dome
        self.assertEqual((dd.name, dd.node, dd.hemisphere, dd.locked, dd.camera, dd.diffuse, dd.glossy),
                         ("FixtureDome", self.by_name["FixtureDome"].index, True, True, False, True, True))
        self.assertAlmostEqual(dd.radiance, 2.0 * L.DOME_RADIANCE[L.UNITS_DEFAULT], delta=1e-9)
        self.assertIsNotNone(dd.texmap)
        for got, want in zip(dd.rotation, ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))):  # 90 about Z
            for a, b in zip(got, want):
                self.assertAlmostEqual(a, b, delta=1e-6)

    def test_domes_are_empties_not_placeholders(self):
        for name in ("FixtureDome", "FixtureDomeColor"):
            self.assertEqual(self.by_name[name].kind, conv.EMPTY, name)
        self.assertEqual(dict(self.desc.placeholders), {})

    def test_the_mesh_light_is_an_emitter_of_its_box(self):
        """W, multiplier 10, the 20 x 20 x 10 box: its flux over the box's 1600 mm^2."""
        node, box = self.by_name["FixtureMeshLight"], self.by_name["FixtureMeshSource"]
        self.assertEqual((node.kind, node.light), (conv.MESH, None))
        ed = self.desc.emitters[node.emitter]
        self.assertEqual((ed.name, ed.users, ed.double_sided, ed.flip, ed.camera), ("FixtureMeshLight", [node.index],
                                                                                  False, False, True))
        self.assertAlmostEqual(ed.area, 0.0016, delta=1e-9)
        self.assertAlmostEqual(ed.radiance, 10.0 / (math.pi * 0.0016), delta=1e-3)  # float32 vertices
        self.assertNotEqual(node.mesh, box.mesh)  # a mesh of its own, the box's vertices
        a, b = self.desc.meshes[node.mesh], self.desc.meshes[box.mesh]
        self.assertEqual(a.positions.tolist(), b.positions.tolist())

    def test_spheres_take_the_x_scale(self):
        tall, wide, inst = (self.desc.lights[self.by_name[n].light] for n in
                            ("FixtureSphereTall", "FixtureSphereWide", "FixtureSphereWideInst"))
        # tall: W/m2/sr, multiplier 2, radius 5 mm, scale 1, 1, 2.5: as unscaled
        self.assertAlmostEqual(tall.watts, math.pi * 2.0 * 4.0 * math.pi * 0.005 ** 2, delta=1e-12)
        self.assertEqual(tall.radius, 0.005)
        self.assertEqual((wide.watts, inst.watts), (40.0, 40.0))  # W: the flux stays
        self.assertAlmostEqual(wide.radius, 0.01, delta=1e-12)
        self.assertEqual(inst.radius, 0.005)

    def test_the_texture_rules_on_the_fixture(self):
        reader_materials = importlib.import_module(_PKG + ".reader.materials")
        cfb = importlib.import_module(_PKG + ".reader.cfb")
        reader_scene = importlib.import_module(_PKG + ".reader.scene")
        assets = importlib.import_module(_PKG + ".reader.assets")
        materials = importlib.import_module(_PKG + ".convert.materials")

        class _Found:
            def find(self, path, resolved):
                return ("found", path)

        with cfb.CompoundFile(DOME_FIXTURE) as cf:
            sc = reader_scene.Scene.from_file(cf)
            graph = reader_materials.MaterialGraph(sc)
            tex = texmaps.TexmapConverter(graph, assets.AssetTable.from_file(cf), textures=_Found(),
                                          swatches=colors.of_scene(sc))
            dd = self.desc.dome
            dt, issues = L.dome_texture(tex.convert(materials.MapRef(dd.texmap), texmaps.COLOR, dd.color), graph)
        self.assertEqual((dt.image.name, issues), ("fixture_dome.png", []))
        self.assertAlmostEqual(dt.turn, math.radians(30.0), delta=1e-6)
        self.assertEqual(dt.amount, 1.0)


if __name__ == "__main__":
    unittest.main()
