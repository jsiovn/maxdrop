# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/lights.py for the lights other than VRayLight: standard, photometric, VRaySun, VRayIES,
Skylight. No Blender.

The rules against values computed by hand from the measured V-Ray constants (docs/FORMAT.md, "Standard and
photometric lights"); the lights_standard and lights_photometric fixtures (tools/fixtures/*.ms) read through
convert.scene against what their scripts set and the Kelvin colors 3ds Max computed with the rules source's
ocbaby_exsKelvinRGB; hand-made values and blocks for the issues.
"""
import importlib
import math
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

_PKG = "maxdrop_lights_test"  # the package test_lights.py makes: maxdrop/__init__.py (bpy) never runs
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
CD = 4.0 * math.pi / 683.0  # watts per cd of a point or spot light
LAMBERT = math.pi / 683.0  # watts per cd of a uniform diffuse light
KELVIN = {3000: (255.0, 177.2, 109.917), 4000: (255.0, 205.816, 166.081)}  # ocbaby_exsKelvinRGB in 3ds Max


def blend(falloff, hotspot):
    """Blender's spot blend whose full intensity ends at the hotspot: it blends in cosine space."""
    edge = math.cos(math.radians(falloff) / 2.0)
    return (math.cos(math.radians(hotspot) / 2.0) - edge) / (1.0 - edge)


def decoded(rgb):
    return tuple(colors.srgb_to_linear(c / 255.0) for c in rgb)


def standard(**changes):
    v = {L.CLASS: L.STANDARD, "shape": L.OMNI, "on": 1, "decay": L.DECAY_NONE, "color": (1.0, 1.0, 1.0),
         "multiplier": 1.0, "start": 40.0, "rectangle": False, "overshoot": False, "diffuse": True, "specular": True,
         "ambient": False, "hotspot": 43.0, "falloff": 45.0}
    v.update(changes)
    return v


def photometric(**changes):
    v = {L.CLASS: L.PHOTOMETRIC, "shape": L.SHAPE_POINT, "file": None}
    v.update({name: default for name, (_b, _p, default) in L._PHOTOMETRIC_PARAMS.items()})
    v.update(changes)
    return v


def sun(**changes):
    v = {L.CLASS: L.SUN, "file": None}
    v.update({name: default for name, (_b, _p, default) in L._SUN_PARAMS.items()})
    v.update(changes)
    return v


def ies(**changes):
    v = {L.CLASS: L.IES, "file": "a.ies"}
    v.update({name: default for name, (_b, _p, default) in L._IES_PARAMS.items()})
    v.update(changes)
    return v


def describe(v):
    return L.describe(1, "x", v, MM, colors.GAMMA_ON)


class Calibration(unittest.TestCase):
    def test_light_strength_is_pi_683_over_1500(self):
        """V-Ray's lx / 1500 against Cycles' 1 / (4 pi^2) per watt at 1 m: the factor the VRayLights measured."""
        self.assertAlmostEqual(math.pi * L.LUMENS_PER_WATT / L.LUX_PER_UNIT, 1.43, delta=0.001)

    def test_a_point_light_is_its_isotropic_flux(self):
        self.assertAlmostEqual(L.point_watts(1000.0), 1000.0 * CD, delta=1e-12)


class Standard(unittest.TestCase):
    def test_omni_without_decay_is_as_bright_at_one_meter(self):
        ld, issues = describe(standard(multiplier=2.0))
        self.assertEqual((ld.kind, ld.radius, issues), ("POINT", 0.0, [L.NO_DECAY % 1.0]))
        self.assertAlmostEqual(ld.watts, 1500.0 * 2.0 * CD, delta=1e-9)

    def test_inverse_square_decay_from_its_start(self):
        ld, issues = describe(standard(decay=L.DECAY_SQUARE, start=800.0, multiplier=2.0))
        self.assertAlmostEqual(ld.watts, 1500.0 * 2.0 * 0.64 * CD, delta=1e-9)
        self.assertEqual(issues, [])

    def test_inverse_decay_matches_at_its_start(self):
        ld, issues = describe(standard(decay=L.DECAY_INVERSE, start=500.0))
        self.assertAlmostEqual(ld.watts, 1500.0 * 0.25 * CD, delta=1e-9)
        self.assertEqual(issues, [L.INVERSE % 0.5])

    def test_decay_from_a_start_of_zero_is_reported(self):
        for decay in (L.DECAY_SQUARE, L.DECAY_INVERSE):
            ld, issues = describe(standard(decay=decay, start=0.0, multiplier=2.0))
            self.assertEqual((ld.watts, issues), (0.0, [L.ZERO_START]))

    def test_spot_cone(self):
        ld, issues = describe(standard(shape=L.SPOTLIGHT, hotspot=30.0, falloff=50.0, decay=L.DECAY_SQUARE,
                                       start=1000.0))
        self.assertEqual((ld.kind, issues), ("SPOT", []))
        self.assertAlmostEqual(ld.spot_size, math.radians(50.0), delta=1e-12)
        self.assertAlmostEqual(ld.spot_blend, blend(50.0, 30.0), delta=1e-12)
        self.assertAlmostEqual(ld.spot_blend, 0.636318, delta=1e-6)

    def test_cone_limits(self):
        self.assertEqual(L._cone(200.0, 10.0)[0], math.pi)
        size, b = L._cone(0.5, 0.5)  # below Blender's smallest spot: a hotspot half of it
        self.assertEqual(size, L.MIN_CONE)
        self.assertAlmostEqual(b, blend(1.0, 0.5), delta=1e-9)
        self.assertEqual(L._cone(0.0, 10.0), (L.MIN_CONE, 0.0))
        self.assertEqual(L._cone(40.0, 60.0)[1], 0.0)  # a hotspot past the falloff

    def test_direct_is_a_sun_of_1500_lx_per_unit(self):
        ld, issues = describe(standard(shape=L.DIRECT, multiplier=1.2, falloff=400.0))
        self.assertEqual((ld.kind, ld.angle), ("SUN", 0.0))
        self.assertAlmostEqual(ld.watts, 1500.0 * 1.2 / 683.0, delta=1e-12)
        self.assertEqual(issues, [L.BEAM % 0.8])
        _ld, issues = describe(standard(shape=L.DIRECT, overshoot=True))
        self.assertEqual(issues, [])

    def test_issues_and_flags(self):
        ld, issues = describe(standard(shape=L.SPOTLIGHT, rectangle=True, overshoot=True, specular=False, on=0,
                                       ambient=True, multiplier=-1.0, decay=L.DECAY_SQUARE))
        self.assertEqual((ld.watts, ld.on, ld.diffuse_rays, ld.glossy_rays, ld.diffuse, ld.specular),
                         (0.0, False, True, False, 1.0, 0.0))
        self.assertEqual(issues, [L.NEGATIVE % ("multiplier", -1.0), L.AMBIENT, L.RECTANGLE_CONE, L.OVERSHOOT])


class Photometric(unittest.TestCase):
    def test_distributions(self):
        cases = ((L.ISOTROPIC, "POINT", None, 1000.0 * CD), (L.SPOT_DISTRIBUTION, "SPOT", None, 1000.0 * CD),
                 (L.DIFFUSE_DISTRIBUTION, "AREA", "DISK", 1000.0 * LAMBERT), (L.WEB, "SPOT", None, 1000.0 * CD))
        for dist, kind, shape, watts in cases:
            ld, _issues = describe(photometric(distribution=dist, intensity=1000.0))
            self.assertEqual((ld.kind, ld.shape), (kind, shape), dist)
            self.assertAlmostEqual(ld.watts, watts, delta=1e-9, msg=dist)

    def test_dimmer_and_negative(self):
        ld, _ = describe(photometric(intensity=1000.0, use_dimmer=1, dimmer=25.0))
        self.assertAlmostEqual(ld.watts, 250.0 * CD, delta=1e-9)
        ld, issues = describe(photometric(intensity=-5.0))
        self.assertEqual((ld.watts, issues), (0.0, [L.NEGATIVE % ("intensity", -5.0)]))

    def test_diffuse_shapes(self):
        for shape, want, issue in (
                (L.SHAPE_RECTANGLE, ("RECTANGLE", 0.2, 0.6), []),
                (L.SHAPE_DISC, ("DISK", 0.3, 0.3), []),
                (L.SHAPE_LINE, ("RECTANGLE", L.LINE_WIDTH, 1.0), [L.SHAPE % ("line", "a rectangle 0.01 m wide")]),
                (L.SHAPE_POINT, ("DISK", L.LINE_WIDTH, L.LINE_WIDTH), []),
                (L.SHAPE_SPHERE, ("DISK", 0.3, 0.3), [L.SHAPE % ("sphere", "a disc of its diameter")])):
            ld, issues = describe(photometric(shape=shape, distribution=L.DIFFUSE_DISTRIBUTION, width=200.0,
                                              length=1000.0 if shape == L.SHAPE_LINE else 600.0, radius=150.0))
            self.assertEqual((ld.shape, round(ld.size, 9), round(ld.size_y, 9)), want, shape)
            self.assertEqual(issues, issue, shape)

    def test_point_shapes(self):
        for shape, radius, issue in ((L.SHAPE_SPHERE, 0.05, []),
                                     (L.SHAPE_CYLINDER, 0.05, [L.SHAPE % ("cylinder", "a sphere of its radius")]),
                                     (L.SHAPE_DISC, 0.05, [L.SHAPE % ("disc", "a sphere of its radius")]),
                                     (L.SHAPE_LINE, 0.0, [L.SHAPE % ("line", "not imported: a point")]),
                                     (L.SHAPE_RECTANGLE, 0.0, [L.SHAPE % ("rectangle", "not imported: a point")])):
            ld, issues = describe(photometric(shape=shape, radius=50.0))
            self.assertEqual((ld.kind, ld.radius, issues), ("POINT", radius, issue), shape)

    def test_web_names_its_file(self):
        ld, issues = describe(photometric(distribution=L.WEB, file="lamp.ies"))
        self.assertEqual((ld.spot_size, issues), (L.WEB_CONE, [L.WEB_FILE % "lamp.ies"]))
        self.assertAlmostEqual(ld.spot_blend, blend(170.0, 100.0), delta=1e-12)
        _ld, issues = describe(photometric(distribution=L.WEB))
        self.assertEqual(issues, [L.WEB_FILE % L.NO_FILE])

    def test_color_is_kelvin_or_white_times_the_filter(self):
        ld, _ = describe(photometric(use_kelvin=1, kelvin=3000.0, filter=(1.0, 0.5, 1.0)))
        want = decoded(KELVIN[3000])
        for got, w, f in zip(ld.color, want, (1.0, 0.5, 1.0)):
            self.assertAlmostEqual(got, w * f, delta=1e-5)
        ld, _ = describe(photometric(filter=(0.25, 1.0, 1.0)))
        self.assertEqual(ld.color, (0.25, 1.0, 1.0))

    def test_flags_and_issues(self):
        ld, issues = describe(photometric(on=0, diffuse=0, specular=0, far=1, ambient=1))
        self.assertEqual((ld.on, ld.diffuse_rays, ld.glossy_rays, ld.diffuse, ld.specular),
                         (False, False, False, 0.0, 0.0))
        self.assertEqual(issues, [L.FAR, L.AMBIENT])

    def test_a_power_out_of_range_is_zero(self):
        ld, issues = describe(photometric(intensity=1e308, use_dimmer=1, dimmer=1e10))
        self.assertEqual((ld.watts, ld.power, issues), (0.0, 0.0, [L.OUT_OF_RANGE]))


class SunAndIes(unittest.TestCase):
    def test_sun(self):
        ld, issues = describe(sun(multiplier=0.5, size=3.0, filter=(1.0, 0.5, 0.25), color_mode=1))
        self.assertEqual((ld.kind, ld.watts, ld.color, issues), ("SUN", 73.2, (1.0, 0.5, 0.25), [L.SUN_ZENITH]))
        self.assertAlmostEqual(ld.angle, math.radians(1.59), delta=1e-12)
        _ld, issues = describe(sun(diffuse_contribution=0.5))
        self.assertEqual(issues, [L.CONTRIBUTION % ("diffuse", 0.5, "diffuse"), L.SUN_ZENITH, L.SUN_COLOR])
        ld, _ = describe(sun(size=1e9, specular=0, invisible=1))
        self.assertEqual((ld.angle, ld.glossy_rays, ld.specular, ld.invisible), (math.pi, False, 0.0, True))

    def test_ies_power_and_override(self):
        ld, issues = describe(ies(power=1500.0))
        self.assertEqual((ld.kind, ld.spot_size, issues), ("SPOT", L.WEB_CONE, [L.IES_FILE % "a.ies"]))
        self.assertAlmostEqual(ld.watts, 1500.0 / 683.0, delta=1e-12)
        ld, _ = describe(ies(power=300.0, override=1, intensity_type=1))
        self.assertAlmostEqual(ld.watts, 300.0 * CD, delta=1e-12)
        ld, _ = describe(ies(power=300.0, override=1, intensity_type=0))
        self.assertAlmostEqual(ld.watts, 300.0 / 683.0, delta=1e-12)
        ld, issues = describe(ies(power=0.0))
        self.assertEqual((ld.watts, issues), (0.0, [L.IES_ZERO, L.IES_FILE % "a.ies"]))

    def test_ies_color(self):
        ld, _ = describe(ies(color_mode=1, temperature=4000.0))
        for got, want in zip(ld.color, decoded(KELVIN[4000])):
            self.assertAlmostEqual(got, want, delta=1e-5)
        ld, _ = describe(ies(color=(0.5, 0.5, 0.5)))
        self.assertEqual(ld.color, (0.5, 0.5, 0.5))

    def test_skylight_is_not_built(self):
        self.assertEqual(describe({L.CLASS: L.SKYLIGHT}), (None, [L.NOT_SKYLIGHT]))
        self.assertEqual(L.area_scale({L.CLASS: L.SKYLIGHT}, ((2.0, 0.0, 0.0),) * 4), 1.0)


class _Block:
    def __init__(self, block_id, stored):
        self.block_id, self.stored, self.issues = block_id, stored, ()

    def get(self, pid, tab=0, default=None):
        return self.stored.get(pid, default)


class Params(unittest.TestCase):
    def test_animated_values_and_missing_blocks_take_the_default(self):
        blocks = {0: _Block(0, {6: pblock.Animated(3), 1: 2})}

        class Scene:
            def entry(self, i):
                return types.SimpleNamespace(class_id=classids.FREE_DISC_LIGHT)

        orig = L._blocks
        L._blocks = lambda scene, i: (blocks, [])
        try:
            values, issues = L._read_blocks(Scene(), 0, L.PHOTOMETRIC, None)
        finally:
            L._blocks = orig
        self.assertEqual((values["intensity"], values["distribution"], values["shape"], values["file"]),
                         (1500.0, 2, L.SHAPE_DISC, None))
        self.assertEqual(issues, ["intensity is animated: 1500.0 is used",
                                  "parameter block 2 is missing: its defaults are used",
                                  "parameter block 4 is missing: its defaults are used"])
        L._blocks = lambda scene, i: ({}, ["damaged"])
        try:
            with self.assertRaises(L.LightError):
                L._read_blocks(Scene(), 0, L.SUN, None)
        finally:
            L._blocks = orig


class _Chunk:
    container, offset = False, 0

    def first(self, cid):
        return None


class _Scene:
    """A light object 0 whose references are given; objects past 0 are of the given entries."""

    def __init__(self, entries, refs, bad_refs=()):
        self.entries, self._refs, self.bad_refs = entries, refs, bad_refs
        self.classes = []

    def __len__(self):
        return len(self.entries)

    def entry(self, i):
        return self.entries[i]

    def refs(self, i):
        if i in self.bad_refs:
            raise L.ChunkError("damaged references")
        return self._refs.get(i, {})

    def chunk(self, i):
        return _Chunk()

    def is_a(self, i, superclass, class_id):
        e = self.entries[i]
        return e.superclass == superclass and e.class_id == class_id

    def class_index(self, i):
        return i


def _entry(superclass, class_id, index=0):
    return types.SimpleNamespace(superclass=superclass, class_id=class_id, index=index)


class Malformed(unittest.TestCase):
    def test_damaged_environment_references_are_skipped(self):
        env = _entry(classids.SC_RENDER_ENVIRONMENT, classids.RENDER_ENVIRONMENT, 0)
        sky = _entry(classids.SC_TEXMAP, classids.VRAY_SKY, 1)
        sc = _Scene([env, sky], {0: {L.ENVIRONMENT_MAP_SLOT: 1}})
        sc.classes = [env]
        self.assertEqual(L.environment_sky(sc), 1)
        sc.bad_refs = (0,)
        self.assertIsNone(L.environment_sky(sc))
        sc = _Scene([env, sky], {0: {L.ENVIRONMENT_MAP_SLOT: 7}})  # past the objects
        sc.classes = [env]
        self.assertIsNone(L.environment_sky(sc))

    def test_a_standard_light_without_its_block_raises(self):
        omni = _entry(classids.SC_LIGHT, classids.OMNI)
        for refs in ({}, {0: 5}, {0: 1}):  # no slot 0, past the objects, not an old ParamBlock
            sc = _Scene([omni, _entry(classids.SC_LIGHT, classids.OMNI)], {0: refs})
            with self.assertRaises(L.LightError, msg=refs):
                L.read_params(sc, 0)

    def test_a_short_chunk_takes_the_default(self):
        class Leaf:
            container, payload_size = False, 1
        class Holder:
            container = True

            def first(self, cid):
                return Leaf()
        self.assertEqual(L._u16(Holder(), L._DECAY, 7), 7)
        self.assertEqual(L._u16(_Chunk(), L._DECAY, 7), 7)

    def test_a_damaged_block_is_skipped(self):
        light = _entry(classids.SC_LIGHT, classids.VRAY_SUN)
        block = _entry(classids.SC_PARAMETER_BLOCK2, classids.PARAM_BLOCK2)
        sc = _Scene([light, block], {0: {0: 1}})
        blocks, issues = L._blocks(sc, 0)
        self.assertEqual(blocks, {})
        self.assertEqual(len(issues), 1)
        self.assertTrue(issues[0].startswith("the parameter block of reference 0 cannot be read: "), issues)
        with self.assertRaises(L.LightError):
            L.read_params(sc, 0)


@unittest.skipIf(conv is None, "numpy missing")
class Fixtures(unittest.TestCase):
    """What the fixture scripts set, through the rules (meters 0.001)."""

    @classmethod
    def setUpClass(cls):
        cls.descs = {name: conv.read(os.path.join(FIXTURES, name + ".max"))
                     for name in ("lights_standard", "lights_photometric")}

    def light(self, fixture, name):
        desc = self.descs[fixture]
        node = next(n for n in desc.nodes if n.name == name)
        self.assertEqual(node.kind, conv.LIGHT, name)
        return desc.lights[node.light]

    def check(self, fixture, want):
        for name, (kind, shape, size, size_y, radius, cone, blend, watts, on, rays) in want.items():
            ld = self.light(fixture, name)
            got = (ld.kind, ld.shape, round(ld.size, 9), round(ld.size_y, 9), round(ld.radius, 9),
                   round(math.degrees(ld.spot_size), 6), round(ld.spot_blend, 6), ld.on,
                   (ld.diffuse_rays, ld.glossy_rays))
            self.assertEqual(got, (kind, shape, size, size_y, radius, cone, round(blend, 6), on, rays), name)
            self.assertAlmostEqual(ld.watts, watts, delta=watts * 1e-6, msg=name)

    def test_standard(self):
        both = (True, True)
        self.check("lights_standard", {
            "StdOmni": ("POINT", None, 0.0, 0.0, 0.0, 0.0, 0.0, 2250.0 * CD, True, both),
            "StdOmniInst": ("POINT", None, 0.0, 0.0, 0.0, 0.0, 0.0, 2250.0 * CD, True, both),
            "StdOmniSquare": ("POINT", None, 0.0, 0.0, 0.0, 0.0, 0.0, 1920.0 * CD, True, both),
            "StdOmniInverse": ("POINT", None, 0.0, 0.0, 0.0, 0.0, 0.0, 375.0 * CD, False, both),
            "StdOmniNoDiffuse": ("POINT", None, 0.0, 0.0, 0.0, 0.0, 0.0, 1500.0 * CD, True, (False, True)),
            "StdOmniAmbient": ("POINT", None, 0.0, 0.0, 0.0, 0.0, 0.0, 750.0 * CD, True, both),
            "StdSpot": ("SPOT", None, 0.0, 0.0, 0.0, 50.0, blend(50, 30), 4500.0 * CD, True, both),
            "StdSpotRect": ("SPOT", None, 0.0, 0.0, 0.0, 45.0, blend(45, 40), 1500.0 * CD, True, (True, False)),
            "StdTargetSpot": ("SPOT", None, 0.0, 0.0, 0.0, 60.0, blend(60, 20), 3000.0 * CD, True, both),
            "StdTargetDirect": ("SUN", None, 0.0, 0.0, 0.0, 0.0, 0.0, 1500.0 * 0.8 / 683.0, True, both),
            "StdDirect": ("SUN", None, 0.0, 0.0, 0.0, 0.0, 0.0, 1500.0 * 1.2 / 683.0, True, both),
            "StdSun": ("SUN", None, 0.0, 0.0, 0.0, 0.0, 0.0, 73.2, True, both)})
        self.assertEqual(self.light("lights_standard", "StdOmniNegative").watts, 0.0)
        self.assertAlmostEqual(self.light("lights_standard", "StdSun").angle, math.radians(0.53 * 3), delta=1e-9)

    def test_standard_colors(self):
        for name, rgb in (("StdOmni", (255, 200, 150)), ("StdSpot", (120, 160, 255)), ("StdDirect", (255, 240, 220)),
                          ("StdSun", (255, 230, 200)), ("StdOmniSquare", (180, 180, 180))):
            for got, want in zip(self.light("lights_standard", name).color, decoded(rgb)):
                self.assertAlmostEqual(got, want, delta=1e-5, msg=name)

    def test_photometric(self):
        both = (True, True)
        point = ("POINT", None, 0.0, 0.0)
        web = (170.0, blend(170, 100))
        self.check("lights_photometric", {
            "PhPoint": point + (0.0, 0.0, 0.0, 1200.0 * CD, True, both),
            "PhPointInst": point + (0.0, 0.0, 0.0, 1200.0 * CD, True, both),
            "PhSpot": ("SPOT", None, 0.0, 0.0, 0.0, 70.0, blend(70, 40), 1000.0 * CD, True, both),
            "PhRect": ("AREA", "RECTANGLE", 0.2, 0.6, 0.0, 0.0, 0.0, 800.0 * LAMBERT, True, both),
            "PhDisc": ("AREA", "DISK", 0.3, 0.3, 0.0, 0.0, 0.0, 500.0 * LAMBERT, True, both),
            "PhLine": ("AREA", "RECTANGLE", 0.01, 1.0, 0.0, 0.0, 0.0, 300.0 * LAMBERT, True, both),
            "PhSphere": point + (0.05, 0.0, 0.0, 900.0 * CD, True, both),
            "PhCylinder": point + (0.03, 0.0, 0.0, 700.0 * CD, True, (True, False)),
            "PhWeb": ("SPOT", None, 0.0, 0.0, 0.08) + web + (400.0 * CD, True, both),
            "PhOff": point + (0.0, 0.0, 0.0, 1000.0 * CD, False, both),
            "IesPower": ("SPOT", None, 0.0, 0.0, 0.0) + web + (1500.0 / 683.0, True, both),
            "IesOverride": ("SPOT", None, 0.0, 0.0, 0.0) + web + (300.0 * CD, True, (True, False)),
            "PhTPoint": point + (0.0, 0.0, 0.0, 100.0 * CD, True, both),
            "PhTSphere": point + (0.13, 0.0, 0.0, 100.0 * CD, True, both)})

    def test_photometric_colors(self):
        for name, want in (("PhPoint", decoded(KELVIN[3000])), ("IesOverride", decoded(KELVIN[4000])),
                           ("PhOff", decoded((255, 128, 0))), ("PhRect", (1.0, 1.0, 1.0))):
            for got, w in zip(self.light("lights_photometric", name).color, want):
                self.assertAlmostEqual(got, w, delta=1e-5, msg=name)

    def test_instances_share_a_light_and_the_skylight_is_an_empty(self):
        desc = self.descs["lights_standard"]
        by_name = {n.name: n for n in desc.nodes}
        self.assertEqual(by_name["StdOmni"].light, by_name["StdOmniInst"].light)
        self.assertEqual((len(desc.lights), by_name["StdSky"].kind, dict(desc.placeholders)), (12, conv.EMPTY, {}))
        self.assertEqual(len(self.descs["lights_photometric"].lights), 16)

    def test_the_vraysky_is_named(self):
        desc = self.descs["lights_standard"]
        self.assertIn((conv.ENVIRONMENT, "light: " + L.SKY), desc.issues)  # not on the map's object index
        self.assertNotIn("light: " + L.SKY, [r for _i, r in self.descs["lights_photometric"].issues])


if __name__ == "__main__":
    unittest.main()
