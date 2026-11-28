# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/lights/ for the lights other than VRayLight: standard, photometric, VRaySun, VRayIES,
Skylight. No Blender.

The rules against values computed by hand from the measured V-Ray constants (docs/FORMAT.md, "Standard and
photometric lights"); the lights_standard and lights_photometric fixtures (tools/fixtures/*.ms) read through
convert.scene against what their scripts set and the Kelvin colors 3ds Max computed with the rules source's
ocbaby_exsKelvinRGB; hand-made values and blocks for the issues.
"""
import importlib
import math
import os
import shutil
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

_PKG = "maxdrop_lights_test"  # the package lights_support.py makes: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
lights = importlib.import_module(_PKG + ".convert.lights")
colors = importlib.import_module(_PKG + ".convert.colors")
pblock = importlib.import_module(_PKG + ".reader.pblock")
ies_mod = importlib.import_module(_PKG + ".convert.ies")
textures = importlib.import_module(_PKG + ".convert.textures")
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
         "ambient": False, "hotspot": 43.0, "falloff": 45.0, "shadow": 1}
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


def ies_bytes(rated=500, candela=100, lamps=1, ballast=1):
    """A self-authored isotropic LM-63 file: candela cd in every direction (4 pi candela lm), rated lumens rated."""
    return ("IESNA:LM-63-2002\n[TEST] MaxDrop unit test\nTILT=NONE\n%d %s 1 3 1 1 2 0 0 0\n%s 1 0\n0 90 180\n0\n"
            "%s %s %s\n" % (lamps, rated, ballast, candela, candela, candela)).encode("ascii")


def downlight_bytes(ballast_lamp=1, planes=1):
    """A self-authored absolute type C file that sends nothing upward: 100, 50, 0, 0, 0 cd at 0, 45, 90, 135, 180
    degrees (peak 100 at the nadir), in planes 0 (one), 0 and 180 (two) or 0 to 360 by 90 (five); CRLF lines."""
    horizontal = {1: "0", 2: "0 180", 5: "0 90 180 270 360"}[planes]
    return ("IESNA:LM-63-2002\r\n[TEST] MaxDrop unit test\r\nTILT=NONE\r\n1 -1 1 5 %d 1 2 0 0 0\r\n1 %s 0\r\n"
            "0 45 90 135 180\r\n%s\r\n%s\r\n" % (planes, ballast_lamp, horizontal,
                                                 "\r\n".join(["100 50 0 0 0"] * planes))).encode("ascii")


UPLIGHT = b"IESNA:LM-63-2002\nTILT=NONE\n1 -1 1 3 1 1 2 0 0 0\n1 1 0\n0 90 180\n0\n100 100 50\n"


def shines(line, file, up="50"):
    """The issue line of a light that shines with its profile; up: the UPWARD share (an isotropic file's 50)."""
    return line % file + (L.UPWARD % up if up else "")


ISO = shines(L.IES_PROFILE, "a.ies")  # a VRayIES of a.ies shining with an isotropic file


def shining(issue):
    """A light's (who, line) issue with its WEB_FILE or IES_FILE line as the light shining with an isotropic file
    says it (the others as they are)."""
    who, line = issue
    for old, new in ((L.IES_FILE, L.IES_PROFILE), (L.WEB_FILE, L.WEB_PROFILE)):
        head, tail = ("light: " + old).split("%s")
        if line.startswith(head) and line.endswith(tail):
            return who, "light: " + shines(new, line[len(head):len(line) - len(tail)])
    return issue


def with_file(v, data=None, issue=None):
    """VRayIES values with the photometry read_params gives for an IES file of these bytes (or why it is not read)."""
    v["photometry"] = ies_mod.parse(data) if data is not None else None
    v["ies_name"] = "found.ies" if data is not None or issue is not None else None
    v["photometry_issue"] = issue
    return v


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

    def test_shadow_switch(self):
        for shape in (L.OMNI, L.SPOTLIGHT, L.DIRECT):
            self.assertTrue(describe(standard(shape=shape))[0].shadow, shape)
            ld, issues = describe(standard(shape=shape, shadow=0, overshoot=True))
            self.assertFalse(ld.shadow, shape)
            self.assertNotIn("shadow", " ".join(issues), shape)

    def test_shadow_chunk(self):
        class Leaf:
            container, payload_size = False, 2

            def __init__(self, value):
                self.value = value

            def unpack(self, fmt):
                return (self.value,)

        class Holder:
            container = True

            def __init__(self, value):
                self.value = value

            def first(self, cid):
                return Leaf(self.value) if cid == L._SHADOW else None

        self.assertEqual((L._u16(Holder(0), L._SHADOW, 1), L._u16(Holder(1), L._SHADOW, 1)), (0, 1))
        self.assertEqual(L._u16(_Chunk(), L._SHADOW, 1), 1)  # not stored: on, as before it was read


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

    def test_web_profile(self):
        """A web light whose file is read has its profile with its stored rotation and shines with it; one whose
        file is missing or not read has none, the wide spot and its line. Another distribution has none."""
        found = dict(distribution=L.WEB, file="lamp.ies", rotation=(10.0, 20.0, 30.0), ies_name="Lamp.IES",
                     photometry=ies_mod.parse(ies_bytes()), photometry_issue=None)
        ld, issues = describe(photometric(**found))
        self.assertEqual((ld.profile.file, ld.profile.rotation, ld.profile.photometry), ("Lamp.IES", (10.0, 20.0, 30.0),
                                                                                         found["photometry"]))
        rotated = L.WEB_PROFILE % "lamp.ies" + L.ROTATION % (10.0, 20.0, 30.0) + L.UPWARD % "50"
        self.assertEqual((ld.kind, ld.spot_size, issues), ("POINT", 0.0, [rotated]))
        self.assertIn("rotation (10, 20, 30) is not applied", rotated)
        for missing in ({"photometry": None, "ies_name": None}, {"photometry": None, "photometry_issue": "bad"}):
            ld, issues = describe(photometric(**dict(found, **missing)))
            self.assertEqual((ld.profile, ld.spot_size, issues), (None, L.WEB_CONE, [L.WEB_FILE % "lamp.ies"]))
        ld, _issues = describe(photometric(distribution=L.WEB, file="lamp.ies"))  # read without a lookup
        self.assertIsNone(ld.profile)
        for dist in (L.ISOTROPIC, L.SPOT_DISTRIBUTION, L.DIFFUSE_DISTRIBUTION):
            self.assertIsNone(describe(photometric(**dict(found, distribution=dist)))[0].profile, dist)

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

    def test_shadow_switch(self):
        self.assertEqual(L._PHOTOMETRIC_PARAMS["shadow"], (0, 3, 1))
        for dist in (L.ISOTROPIC, L.SPOT_DISTRIBUTION, L.DIFFUSE_DISTRIBUTION, L.WEB):
            self.assertTrue(describe(photometric(distribution=dist))[0].shadow, dist)
            self.assertFalse(describe(photometric(distribution=dist, shadow=0))[0].shadow, dist)

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
        self.assertEqual((ld.kind, ld.spot_size, issues), ("SPOT", L.WEB_CONE, [L.IES_RATED, L.IES_FILE % "a.ies"]))
        self.assertAlmostEqual(ld.watts, 1500.0 / 683.0, delta=1e-12)
        for intensity_type in (1, 0):  # the stored power is lumens in both units (V-Ray's panel converts cd)
            ld, issues = describe(ies(power=300.0, override=1, intensity_type=intensity_type))
            self.assertAlmostEqual(ld.watts, 300.0 / 683.0, delta=1e-12)
            self.assertEqual(issues, [L.IES_FILE % "a.ies"])
        for override in (0, 1):
            ld, issues = describe(ies(power=0.0, override=override))
            self.assertEqual((ld.watts, issues), (0.0, [L.IES_ZERO, L.IES_FILE % "a.ies"]), override)
        ld, issues = describe(ies(power=-5.0))
        self.assertEqual((ld.watts, issues), (0.0, [L.NEGATIVE % ("power", -5.0), L.IES_FILE % "a.ies"]))

    def test_ies_header_scales_the_power(self):
        """V-Ray renders power x the file's flux / its rated lumens with the override off (docs/FORMAT.md, "VRayIES
        power, measured"): a rated-500 isotropic 100 cd file at power 1000 is 200 cd."""
        ld, issues = describe(with_file(ies(power=1000.0), ies_bytes()))
        self.assertAlmostEqual(ld.watts, 4.0 * math.pi * 200.0 / 683.0, delta=1e-9)
        self.assertEqual(issues, [ISO])
        ld, issues = describe(with_file(ies(power=1000.0), ies_bytes(rated=-1)))  # absolute: the power is the flux
        self.assertAlmostEqual(ld.watts, 1000.0 / 683.0, delta=1e-12)
        self.assertEqual(issues, [ISO])
        ld, issues = describe(with_file(ies(power=1000.0), ies_bytes(lamps=2)))  # rated 2 x 500 lm (measured)
        self.assertAlmostEqual(ld.watts, 4.0 * math.pi * 100.0 / 683.0, delta=1e-9)
        self.assertEqual(issues, [ISO])
        ld, issues = describe(with_file(ies(power=1000.0), ies_bytes(rated=-1, lamps=2)))  # lumens per lamp unused
        self.assertAlmostEqual(ld.watts, 1000.0 / 683.0, delta=1e-12)
        self.assertEqual(issues, [ISO])
        ld, issues = describe(with_file(ies(power=1000.0), ies_bytes(ballast=0.5)))  # the ballast factor applies
        self.assertAlmostEqual(ld.watts, 4.0 * math.pi * 100.0 / 683.0, delta=1e-9)
        self.assertEqual(issues, [ISO])
        ld, issues = describe(with_file(ies(power=1000.0), ies_bytes(rated=0)))  # 0 lm: the power is the flux
        self.assertAlmostEqual(ld.watts, 1000.0 / 683.0, delta=1e-12)
        for rated in (500, -1):  # V-Ray renders a table without light black, also when absolute (measured)
            ld, issues = describe(with_file(ies(power=1000.0), ies_bytes(candela=0, rated=rated)))
            self.assertEqual((ld.watts, issues), (0.0, [L.IES_DARK % "a.ies", L.IES_PROFILE % "a.ies"]), rated)
        ld, issues = describe(with_file(ies(power=1000.0), ies_bytes(rated="1e-300")))
        self.assertEqual((ld.watts, ld.power, issues), (0.0, 0.0, [ISO, L.OUT_OF_RANGE]))

    def test_ies_file_not_read(self):
        ld, issues = describe(with_file(ies(power=1000.0), issue="a candela value is negative"))
        self.assertAlmostEqual(ld.watts, 1000.0 / 683.0, delta=1e-12)
        self.assertEqual(issues, [L.IES_UNREAD % ("a.ies", "a candela value is negative"), L.IES_FILE % "a.ies"])
        ld, issues = describe(with_file(ies(power=1000.0)))  # not found
        self.assertEqual(issues, [L.IES_RATED, L.IES_FILE % "a.ies"])

    def test_ies_profile(self):
        """A VRayIES whose file is read has its profile whatever its override and power, with the issue lines it has
        without one; a file not found or not read gives none."""
        for changes in ({"power": 1000.0}, {"power": 300.0, "override": 1}, {"power": 0.0}, {"power": -5.0}):
            ld, issues = describe(with_file(ies(**changes), ies_bytes()))
            p = ld.profile
            self.assertEqual((p.file, p.rotation, p.photometry.rated, round(p.peak, 9), round(p.nadir, 9),
                              round(p.up, 9)), ("found.ies", (0.0, 0.0, 0.0), 500.0, 100.0, 100.0, 0.5), changes)
            self.assertEqual(p.text, ies_bytes().rstrip(b"\n").decode("ascii"), changes)
            self.assertAlmostEqual(p.flux, 4.0 * math.pi * 100.0, delta=1e-9)
            _ld, plain = describe(ies(**changes))
            self.assertEqual(issues, [ISO if x == L.IES_FILE % "a.ies" else x for x in plain if x != L.IES_RATED],
                             changes)
        self.assertNotIn("TILT", repr(ld.profile))  # the repr leaves the text out: it can be megabytes
        for v in (ies(power=1000.0), with_file(ies(power=1000.0)), with_file(ies(), issue="a candela value is "
                                                                                          "negative")):
            self.assertIsNone(describe(v)[0].profile)

    def test_ies_override_ignores_the_file(self):
        ld, issues = describe(with_file(ies(power=300.0, override=1), ies_bytes()))
        self.assertAlmostEqual(ld.watts, 300.0 / 683.0, delta=1e-12)
        self.assertEqual(issues, [ISO])

    def test_ies_profile_light(self):
        """A VRayIES shining with its profile (docs/FORMAT.md, "The IES Texture node in Blender, measured") is a point
        light of s x IES_WATTS over the file's ballast-lamp factor, s = its lumens over the file's flux; its watts stay
        its lumens / 683; its line is IES_PROFILE, with UPWARD for a file that sends light upward."""
        self.assertAlmostEqual(L.IES_WATTS, 4.0 * math.pi / (683.0 * 0.070665), delta=1e-12)
        self.assertAlmostEqual(L.IES_WATTS, 0.2604, delta=5e-5)
        ld, issues = describe(with_file(ies(power=1000.0), ies_bytes()))  # rated 500: 200 cd, s = 2
        self.assertEqual((ld.kind, ld.spot_size, ld.spot_blend, issues), ("POINT", 0.0, 0.0, [ISO]))
        self.assertAlmostEqual(ld.power, 2.0 * L.IES_WATTS, delta=1e-12)
        self.assertAlmostEqual(ld.watts, 4.0 * math.pi * 200.0 / 683.0, delta=1e-9)
        ld, issues = describe(with_file(ies(power=300.0, override=1), ies_bytes()))  # the power is the flux
        self.assertAlmostEqual(ld.power, 300.0 / (400.0 * math.pi) * L.IES_WATTS, delta=1e-12)
        down = ies_mod.parse(downlight_bytes())  # absolute: power 1000 is the flux
        ld, issues = describe(with_file(ies(power=1000.0), downlight_bytes()))
        self.assertEqual((ld.kind, issues, ld.profile.up), ("POINT", [L.IES_PROFILE % "a.ies"], 0.0))
        self.assertAlmostEqual(ld.power, 1000.0 / down.flux * L.IES_WATTS, delta=1e-12)
        ld, _ = describe(with_file(ies(power=1000.0), downlight_bytes(ballast_lamp=0.5)))  # Cycles applies it
        self.assertAlmostEqual(ld.power, 2000.0 / down.flux * L.IES_WATTS, delta=1e-12)
        for factor in (0, -1):  # Cycles would render it dark or negative: no profile, the wide spot
            ld, issues = describe(with_file(ies(power=1000.0), downlight_bytes(ballast_lamp=factor)))
            self.assertEqual((ld.profile, ld.kind, ld.spot_size, issues),
                             (None, "SPOT", L.WEB_CONE, [L.IES_FILE % "a.ies"]), factor)
            self.assertAlmostEqual(ld.power, 1000.0 / 683.0, delta=1e-12)
        ld, issues = describe(with_file(ies(power=1000.0), ies_bytes(candela=0)))  # no light: 0 W, no upward share
        self.assertEqual((ld.kind, ld.power, issues), ("POINT", 0.0, [L.IES_DARK % "a.ies", L.IES_PROFILE % "a.ies"]))
        ld, issues = describe(with_file(ies(power=300.0, override=1), ies_bytes(candela=0)))  # the node gives none
        self.assertEqual((ld.kind, ld.watts, ld.power, issues),
                         ("POINT", 0.0, 0.0, [L.IES_DARK % "a.ies", L.IES_PROFILE % "a.ies"]))
        ld, issues = describe(with_file(ies(power=1000.0), downlight_bytes(ballast_lamp="1e-320")))  # past the range
        self.assertEqual((ld.watts, ld.power, issues), (0.0, 0.0, [L.IES_PROFILE % "a.ies", L.OUT_OF_RANGE]))
        ld, issues = describe(with_file(ies(power=1000.0, override_shape=1, shape_type=L.IES_SPHERE, use_shape=2,
                                            diameter=100.0), ies_bytes()))  # the radius stays, on the point light
        self.assertEqual((ld.kind, ld.radius), ("POINT", 0.05))
        up = ies_mod.parse(UPLIGHT).up  # 100, 100, 50 cd at 0, 90, 180 degrees: neither 0 nor half upward
        self.assertTrue(0.0 < up < 0.5, up)
        _ld, issues = describe(with_file(ies(power=1000.0), UPLIGHT))
        self.assertEqual(issues, [shines(L.IES_PROFILE, "a.ies", "%.3g" % (100.0 * up))])

    def test_web_shines_with_its_profile(self):
        """A web light of 400 cd with a file read is a point light whose intensity is the file's peak (not measured:
        maxdrop-o53.3.5): s = 400 / the peak, power s x IES_WATTS over the ballast-lamp factor, watts s x the file's
        flux / 683; its line is WEB_PROFILE, with UPWARD for a file that sends light upward; a file without light
        0 W."""
        for data, factor in ((downlight_bytes(), 1.0), (downlight_bytes(ballast_lamp=0.5), 0.5),
                             (ies_bytes(candela=40), 1.0)):
            photometry = ies_mod.parse(data)
            ld, issues = describe(photometric(distribution=L.WEB, intensity=400.0, file="lamp.ies",
                                              ies_name="Lamp.ies", photometry=photometry, photometry_issue=None))
            s = 400.0 / photometry.peak
            self.assertEqual(ld.kind, "POINT")
            self.assertAlmostEqual(ld.power, s * L.IES_WATTS / factor, delta=1e-12)
            self.assertAlmostEqual(ld.watts, s * photometry.flux / 683.0, delta=1e-9)
            self.assertEqual(issues, [shines(L.WEB_PROFILE, "lamp.ies", "50" if photometry.up else None)])
        down = ies_mod.parse(downlight_bytes())
        self.assertNotAlmostEqual(down.flux / (4.0 * math.pi), down.peak, delta=1.0)  # the peak, not a mean
        ld, issues = describe(photometric(distribution=L.WEB, intensity=400.0, file="lamp.ies", ies_name="Lamp.ies",
                                          photometry=ies_mod.parse(ies_bytes(candela=0)), photometry_issue=None))
        self.assertEqual((ld.kind, ld.power, ld.watts, issues), ("POINT", 0.0, 0.0, [L.WEB_PROFILE % "lamp.ies"]))

    def test_ies_shadow_switch(self):
        self.assertEqual(L._IES_PARAMS["shadow"], (0, 4, 1))
        self.assertEqual((describe(ies())[0].shadow, describe(ies(shadow=0))[0].shadow), (True, False))
        self.assertTrue(describe(sun())[0].shadow)  # V-Ray 5.2's VRaySun has no switch

    def test_ies_light_shape(self):
        sizes = {"height": 300.0, "width": 200.0, "length": 400.0, "diameter": 100.0}
        file = [L.IES_RATED, L.IES_FILE % "a.ies"]  # no override: IES_RATED too
        ld, issues = describe(ies(**sizes))  # no override: the IES file's shape, not read
        self.assertEqual((ld.radius, issues), (0.0, file))
        ld, issues = describe(ies(override_shape=1, shape_type=L.IES_SPHERE, use_shape=0, **sizes))
        self.assertEqual((ld.radius, issues), (0.0, file))
        for use in (1, 2):  # for shadows only, for illumination and shadows
            ld, issues = describe(ies(override_shape=1, shape_type=L.IES_SPHERE, use_shape=use, **sizes))
            self.assertEqual((ld.radius, issues), (0.05, file), use)
        for shape, across, name in ((0, 0.0, None), (1, 0.4, "rectangle"), (2, 0.1, "circle"),
                                    (4, 0.3, "vertical cylinder"), (5, 0.4, "horizontal cylinder"),
                                    (6, 0.2, "horizontal cylinder"), (14, 0.2, "vertical circle"),
                                    (15, 0.3, "vertical ellipse"), (16, 0.4, "cuboid"), (99, 0.0, None)):
            ld, issues = describe(ies(override_shape=1, shape_type=shape, **sizes))
            self.assertAlmostEqual(ld.radius, across / 2.0, delta=1e-12, msg=shape)
            want = [L.IES_SHAPE % (name, across)] if name else []
            self.assertEqual(issues, file + want, shape)
        ld, _ = describe(ies(override_shape=1, shape_type=L.IES_SPHERE, diameter=-100.0))
        self.assertAlmostEqual(ld.radius, 0.05, delta=1e-12)
        ld, issues = describe(ies(override_shape=1, shape_type=1))  # every size 0
        self.assertEqual((ld.radius, issues), (0.0, file))
        ld, issues = describe(ies(override_shape=1, shape_type=1, width=math.inf))
        self.assertEqual((ld.radius, issues), (0.0, file))
        self.assertEqual(set(L.IES_SHAPES), set(range(17)))

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
        L.reading._blocks = lambda scene, i: (blocks, [])
        try:
            values, issues = L._read_blocks(Scene(), 0, L.PHOTOMETRIC, None)
        finally:
            L.reading._blocks = orig
        self.assertEqual((values["intensity"], values["distribution"], values["shape"], values["file"]),
                         (1500.0, 2, L.SHAPE_DISC, None))
        self.assertEqual(issues, ["intensity is animated: 1500.0 is used",
                                  "parameter block 2 is missing: its defaults are used",
                                  "parameter block 4 is missing: its defaults are used"])
        L.reading._blocks = lambda scene, i: ({}, ["damaged"])
        try:
            with self.assertRaises(L.LightError):
                L._read_blocks(Scene(), 0, L.SUN, None)
        finally:
            L.reading._blocks = orig

    def test_the_lookup_runs_for_every_web_and_vrayies(self):
        """A web light's file (block 3 parameter 0) and rotation (1 to 3, as stored; an animated one 0, without a
        line: not applied yet) and a VRayIES's file whatever its override and power go to the lookup; a photometric
        light of another distribution is not looked up."""
        asked = []

        class Lookup:
            def found(self, path, resolved=""):
                asked.append((path, resolved))
                return "lamp.ies", "photometry", None

        class Assets:
            def entry(self, ref):
                return types.SimpleNamespace(path="maps\\lamp.ies", resolved="C:\\x\\lamp.ies") if ref == 7 else None

        class Scene:
            def entry(self, i):
                return types.SimpleNamespace(class_id=classids.FREE_DISC_LIGHT)

        orig = L._blocks
        try:
            for dist, looked_up in ((L.WEB, True), (7, True), (L.ISOTROPIC, False), (L.SPOT_DISTRIBUTION, False),
                                    (L.DIFFUSE_DISTRIBUTION, False)):
                blocks = {0: _Block(0, {1: dist}), 2: _Block(2, {}), 4: _Block(4, {}),
                          3: _Block(3, {0: 7, 1: 10.0, 2: pblock.Animated(3), 3: 30})}
                L.reading._blocks = lambda scene, i: (blocks, [])
                del asked[:]
                values, issues = L._read_blocks(Scene(), 0, L.PHOTOMETRIC, Assets(), Lookup())
                self.assertEqual((values["file"], issues), ("lamp.ies", []), dist)
                if looked_up:
                    self.assertEqual((values["rotation"], values["ies_name"], values["photometry"], asked),
                                     ((10.0, 0.0, 30.0), "lamp.ies", "photometry",
                                      [("maps\\lamp.ies", "C:\\x\\lamp.ies")]), dist)
                else:
                    self.assertEqual((asked, "rotation" in values, "photometry" in values), ([], False, False), dist)
            blocks = {0: _Block(0, {1: L.WEB})}  # no block 3: no file, rotation 0, nothing to look up
            L.reading._blocks = lambda scene, i: (blocks, [])
            values, _issues = L._read_blocks(Scene(), 0, L.PHOTOMETRIC, Assets(), Lookup())
            self.assertEqual((values["rotation"], values["photometry"], asked), ((0.0, 0.0, 0.0), None, []))
            for override, power in ((0, 1000.0), (1, 1000.0), (0, 0.0), (0, -5.0)):
                blocks = {0: _Block(0, {1: 7, 10: power, 34: override})}
                L.reading._blocks = lambda scene, i: (blocks, [])
                del asked[:]
                values, _issues = L._read_blocks(Scene(), 0, L.IES, Assets(), Lookup())
                self.assertEqual((values["ies_name"], len(asked), "rotation" in values), ("lamp.ies", 1, False),
                                 (override, power))
        finally:
            L.reading._blocks = orig


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
            "IesPower": ("SPOT", None, 0.0, 0.0, 0.2) + web + (1500.0 / 683.0, True, both),
            "IesOverride": ("SPOT", None, 0.0, 0.0, 0.05) + web + (300.0 / 683.0, True, (True, False)),
            "PhTPoint": point + (0.0, 0.0, 0.0, 100.0 * CD, True, both),
            "PhTSphere": point + (0.13, 0.0, 0.0, 100.0 * CD, True, both)})

    def test_photometric_colors(self):
        for name, want in (("PhPoint", decoded(KELVIN[3000])), ("IesOverride", decoded(KELVIN[4000])),
                           ("PhOff", decoded((255, 128, 0))), ("PhRect", (1.0, 1.0, 1.0))):
            for got, w in zip(self.light("lights_photometric", name).color, want):
                self.assertAlmostEqual(got, w, delta=1e-5, msg=name)

    def test_shadow_switches(self):
        """MAXScript makes a standard or photometric light without shadows; the scripts switch some on, a VRayIES
        has them on but IesOverride; a VRaySun has no switch."""
        on = {"StdOmni", "StdOmniInst", "StdSpot", "StdTargetDirect", "StdSun", "PhPoint", "PhPointInst", "PhSpot",
              "IesPower"}
        for fixture, desc in self.descs.items():
            for node in desc.nodes:
                if node.kind == conv.LIGHT:
                    self.assertEqual(desc.lights[node.light].shadow, node.name in on, node.name)

    def test_instances_share_a_light_and_the_skylight_is_an_empty(self):
        desc = self.descs["lights_standard"]
        by_name = {n.name: n for n in desc.nodes}
        self.assertEqual(by_name["StdOmni"].light, by_name["StdOmniInst"].light)
        self.assertEqual((len(desc.lights), by_name["StdSky"].kind, dict(desc.placeholders)), (12, conv.EMPTY, {}))
        self.assertEqual(len(self.descs["lights_photometric"].lights), 16)

    def test_a_found_ies_file_scales_the_power(self):
        """lights_photometric copied beside a self-authored fixture_web.ies rated 500 lm, 100 cd everywhere: IesPower
        (1500, override off) gets 1500 x 400 pi / 500 lm, looked up once; IesOverride (300 lm, override on) keeps its
        power; the file is read once. IesPower, IesOverride and PhWeb (the same file) share its profile, PhWeb with
        its rotation as stored, and shine with it: point lights, their lines reworded one for one; the report keeps
        its other lines but the rated-lumens one. Without the file the issues are
        those of a read without a lookup and no light has a profile."""
        scratch = tempfile.mkdtemp(prefix="maxdrop-ies-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        dst = os.path.join(scratch, "lights_photometric.max")
        shutil.copy(os.path.join(FIXTURES, "lights_photometric.max"), dst)
        plain = self.descs["lights_photometric"]
        missing = conv.read(dst, files=textures.TextureIndex(dst))
        self.assertEqual(missing.issues, plain.issues)
        self.assertEqual([ld.profile for ld in missing.lights.values()], [None] * len(missing.lights))
        with open(os.path.join(scratch, "fixture_web.ies"), "wb") as f:
            f.write(ies_bytes())
        reads = []
        read = ies_mod.read
        ies_mod.read = lambda path: reads.append(path) or read(path)
        try:
            desc = conv.read(dst, files=textures.TextureIndex(dst))
        finally:
            ies_mod.read = read
        by_name = {n.name: desc.lights[n.light] for n in desc.nodes if n.kind == conv.LIGHT}
        self.assertAlmostEqual(by_name["IesPower"].watts, 1500.0 * 400.0 * math.pi / 500.0 / 683.0, delta=1e-9)
        self.assertAlmostEqual(by_name["IesOverride"].watts, 300.0 / 683.0, delta=1e-12)
        self.assertAlmostEqual(by_name["PhWeb"].watts, 400.0 * CD, delta=1e-9)
        self.assertEqual(len(reads), 1, reads)
        self.assertEqual(desc.issues, [shining(x) for x in plain.issues if x[1] != "light: " + L.IES_RATED])
        self.assertEqual(sum(shining(x) != x for x in plain.issues), 3)  # one line each, reworded
        self.assertEqual({by_name[n].kind for n in ("IesPower", "IesOverride", "PhWeb")}, {"POINT"})
        with_profile = {name for name, ld in by_name.items() if ld.profile is not None}
        self.assertEqual(with_profile, {"IesPower", "IesOverride", "PhWeb"})
        profiles = [by_name[name].profile for name in sorted(with_profile)]
        self.assertEqual({(p.file, p.photometry) for p in profiles}, {("fixture_web.ies", profiles[0].photometry)})
        self.assertEqual([p.rotation for p in profiles], [(0.0, 0.0, 0.0)] * 3)  # the script leaves the web's at 0

    def test_the_vraysky_is_named(self):
        desc = self.descs["lights_standard"]
        self.assertIn((conv.ENVIRONMENT, "light: " + L.SKY), desc.issues)  # not on the map's object index
        self.assertNotIn("light: " + L.SKY, [r for _i, r in self.descs["lights_photometric"].issues])


if __name__ == "__main__":
    unittest.main()
