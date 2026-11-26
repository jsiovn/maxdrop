# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/lights/: VRayLights as light descriptions, no Blender.

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
an object offset, one holding its own mesh (Replace mesh with light) with a Shell, one without a mesh; spread on
hand-made areas, an Extrude on a shape source (the extrude fixture, tools/fixtures/extrude.ms).
"""
import os
import sys
import types
import unittest
from unittest import mock

_TESTS = "maxdrop_unit_tests"  # tests/unit as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_unit_tests.lights_support import (  # noqa: E402 (after the loader)
    classids, colors, conv, FACTORS, FIXTURE, L, MAX_KELVIN_3500, MAX_WATTS, MM, pblock, values,
)


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


if __name__ == "__main__":
    unittest.main()
