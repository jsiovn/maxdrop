# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/ies.py: the rated lumens and the integrated flux of self-authored LM-63 files. No
Blender."""
import importlib
import math
import os
import shutil
import sys
import tempfile
import tracemalloc
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PKG = "maxdrop_ies_test"  # maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
ies = importlib.import_module(_PKG + ".convert.ies")

ISOTROPIC = 4.0 * math.pi * 100.0  # lumens of 100 cd in every direction


def ies_file(vertical=(0, 90, 180), horizontal=(0,), candela=100.0, rated=500, multiplier=1, lamps=1, kind=1,
             tilt="NONE", candelas=None, header="IESNA:LM-63-2002\n[TEST] self-authored\n[MANUFAC] none\n",
             ballast=1.0, ballast_lamp=1.0):
    """An LM-63 file as bytes: candela everywhere, or candelas (one run per horizontal angle)."""
    values = candelas if candelas is not None else [candela] * (len(vertical) * len(horizontal))
    text = header + "TILT=%s\n" % tilt
    if tilt == "INCLUDE":
        text += "1\n2\n0 90\n1.0 0.5\n"
    text += "%d %s %s %d %d %d 2 0.1 0.1 0.1\n%s %s 50\n" % (lamps, rated, multiplier, len(vertical),
                                                             len(horizontal), kind, ballast, ballast_lamp)
    text += " ".join(str(v) for v in vertical) + "\n" + " ".join(str(h) for h in horizontal) + "\n"
    text += " ".join(str(c) for c in values) + "\n"
    return text.encode("latin-1")


class Parse(unittest.TestCase):
    def test_isotropic_flux_and_header(self):
        p = ies.parse(ies_file())
        self.assertEqual((p.lamps, p.rated, p.multiplier), (1, 500.0, 1.0))
        self.assertAlmostEqual(p.flux, ISOTROPIC, delta=1e-9)
        self.assertAlmostEqual(p.scale, ISOTROPIC / 500.0, delta=1e-12)

    def test_absolute_photometry_keeps_the_power(self):
        for rated in (-1, 0):
            self.assertEqual(ies.parse(ies_file(rated=rated)).scale, 1.0, rated)

    def test_the_multiplier_scales_the_candelas(self):
        self.assertAlmostEqual(ies.parse(ies_file(multiplier=2.5)).flux, 2.5 * ISOTROPIC, delta=1e-9)

    def test_symmetries_give_one_flux(self):
        for horizontal in ((0,), (0, 45, 90), (0, 90, 180), (0, 90, 180, 270, 360), (90, 180, 270)):
            p = ies.parse(ies_file(vertical=(0, 30, 60, 90, 120, 150, 180), horizontal=horizontal))
            self.assertAlmostEqual(p.flux, ISOTROPIC, delta=1e-9, msg=horizontal)

    def test_a_lower_hemisphere_gives_half(self):
        self.assertAlmostEqual(ies.parse(ies_file(vertical=(0, 45, 90))).flux, ISOTROPIC / 2.0, delta=1e-9)

    def test_varying_planes_by_the_trapezoid(self):
        # 100 cd in plane 0, 300 cd in plane 90: their mean over the quadrant, 200 cd everywhere
        p = ies.parse(ies_file(horizontal=(0, 90), candelas=[100, 100, 100, 300, 300, 300]))
        self.assertAlmostEqual(p.flux, 4.0 * math.pi * 200.0, delta=1e-9)

    def test_a_cosine_distribution_down(self):
        """I = I0 cos(theta) over the lower hemisphere: flux pi I0, approached as the steps get finer."""
        vertical = [i * 0.5 for i in range(181)]
        p = ies.parse(ies_file(vertical=vertical, candelas=[1000.0 * math.cos(math.radians(a)) for a in vertical]))
        self.assertAlmostEqual(p.flux, math.pi * 1000.0, delta=0.05)

    def test_tilt_include_and_tilt_file(self):
        self.assertAlmostEqual(ies.parse(ies_file(tilt="INCLUDE")).flux, ISOTROPIC, delta=1e-9)
        self.assertAlmostEqual(ies.parse(ies_file(tilt="lamp.tlt")).flux, ISOTROPIC, delta=1e-9)

    def test_lm_63_1986_commas_and_crlf(self):
        data = ies_file(header="").replace(b" ", b",").replace(b"\n", b"\r\n")
        self.assertAlmostEqual(ies.parse(data).flux, ISOTROPIC, delta=1e-9)

    def test_lone_cr_line_ends(self):
        self.assertAlmostEqual(ies.parse(ies_file().replace(b"\n", b"\r")).flux, ISOTROPIC, delta=1e-9)

    def test_no_symmetry_short_of_360_is_closed(self):
        # planes 0, 120, 240 of 100, 200, 300 cd; closed with plane 0 at 360: the mean over the circle, 200 cd
        p = ies.parse(ies_file(horizontal=(0, 120, 240), candelas=[100] * 3 + [200] * 3 + [300] * 3))
        self.assertAlmostEqual(p.flux, 4.0 * math.pi * 200.0, delta=1e-9)

    def test_lamps_are_read(self):
        self.assertEqual(ies.parse(ies_file(lamps=2)).lamps, 2)

    def test_dark_file(self):
        p = ies.parse(ies_file(candela=0))
        self.assertEqual((p.flux, p.scale), (0.0, 0.0))


class VRayRules(unittest.TestCase):
    """What V-Ray 5.2 renders, measured with self-authored files (docs/FORMAT.md, "VRayIES header, measured")."""

    def test_the_ballast_factor_scales_the_flux(self):
        p = ies.parse(ies_file(ballast=0.5))
        self.assertAlmostEqual(p.flux, ISOTROPIC / 2.0, delta=1e-9)
        self.assertAlmostEqual(p.scale, ISOTROPIC / 2.0 / 500.0, delta=1e-12)
        self.assertEqual(ies.parse(ies_file(ballast=0)).flux, 0.0)

    def test_the_ballast_lamp_factor_does_not(self):
        self.assertAlmostEqual(ies.parse(ies_file(ballast_lamp=0.5)).flux, ISOTROPIC, delta=1e-9)

    def test_rated_lumens_are_lamps_times_lumens_per_lamp(self):
        p = ies.parse(ies_file(lamps=2, rated=500))
        self.assertAlmostEqual(p.scale, ISOTROPIC / 1000.0, delta=1e-12)
        self.assertEqual(ies.parse(ies_file(lamps=2, rated=-1)).scale, 1.0)

    def test_candelas_linear_in_angle(self):
        """100, 0, 0 cd at 0, 90, 180: V-Ray's flux 228.96 lm; linear in angle 2 pi (100 - 200 / pi)."""
        p = ies.parse(ies_file(candelas=[100, 0, 0]))
        self.assertAlmostEqual(p.flux, 2.0 * math.pi * (100.0 - 200.0 / math.pi), delta=1e-9)

    def test_a_cosine_in_10_degree_steps(self):
        vertical = list(range(0, 181, 10))
        p = ies.parse(ies_file(vertical=vertical, candelas=[100.0 * max(0.0, math.cos(math.radians(a)))
                                                            for a in vertical]))
        # linear in angle 313.359 (V-Ray 313.99); the zone mean x (cos a - cos b) gave exactly pi x 100 = 314.159
        self.assertAlmostEqual(p.flux, 313.359, delta=0.01)

    def test_type_b_isotropic(self):
        """100 cd over the hemisphere a type B file covers: 2 pi 100, also with V or H from 0 (mirrored)."""
        iso = 2.0 * math.pi * 100.0
        for v, h in (((-90, 0, 90), (-90, 0, 90)), ((-90, 0, 90), (0, 90)), ((0, 90), (-90, 0, 90)),
                     ((0, 45, 90), (0, 30, 90))):
            p = ies.parse(ies_file(kind=2, vertical=v, horizontal=h, rated=-1))
            self.assertAlmostEqual(p.flux, iso, delta=1e-9, msg=(v, h))
        p = ies.parse(ies_file(kind=2, vertical=(-90, 0, 90), horizontal=(-90, 0, 90), rated=628.3))
        self.assertAlmostEqual(p.scale, iso / 628.3, delta=1e-12)

    def test_type_b_peaks(self):
        """0, 100, 0 cd at V -90, 0, 90 in every plane: 400 lm (V-Ray 400.95); the same across H: 100 pi."""
        p = ies.parse(ies_file(kind=2, vertical=(-90, 0, 90), horizontal=(-90, 0, 90), candelas=[0, 100, 0] * 3))
        self.assertAlmostEqual(p.flux, 400.0, delta=1e-9)
        p = ies.parse(ies_file(kind=2, vertical=(-90, 0, 90), horizontal=(-90, 0, 90),
                               candelas=[0, 0, 0, 100, 100, 100, 0, 0, 0]))
        self.assertAlmostEqual(p.flux, 100.0 * math.pi, delta=1e-9)

    def test_type_a(self):
        """Read as type B (V-Ray 629.58 lm isotropic, vertical angles from 0 mirrored); horizontal from 0 refused."""
        for v in ((-90, 0, 90), (0, 90)):
            p = ies.parse(ies_file(kind=3, vertical=v, horizontal=(-90, 0, 90), rated=628.3, multiplier=2))
            self.assertAlmostEqual(p.flux, 4.0 * math.pi * 100.0, delta=1e-9, msg=v)
            self.assertAlmostEqual(p.scale, 4.0 * math.pi * 100.0 / 628.3, delta=1e-12, msg=v)
        p = ies.parse(ies_file(kind=3, vertical=(-90, 90), horizontal=(-90, 90), ballast=0.5, lamps=2))
        self.assertAlmostEqual(p.scale, math.pi * 100.0 / 1000.0, delta=1e-12)

    def test_type_b_mirrored_both_ways(self):
        p = ies.parse(ies_file(kind=2, vertical=(0, 90), horizontal=(0, 90), rated=500, ballast=0.5))
        self.assertAlmostEqual(p.scale, math.pi * 100.0 / 500.0, delta=1e-12)  # V-Ray 629.57 lm before ballast


class Refused(unittest.TestCase):
    def refused(self, data, start):
        with self.assertRaises(ies.IesError) as cm:
            ies.parse(data)
        self.assertTrue(str(cm.exception).startswith(start), str(cm.exception))

    def test_type_a_and_b(self):
        self.refused(ies_file(kind=4), "its photometric type 4")
        self.refused(ies_file(kind=2), "its vertical angles run from 0 to 180 degrees: not one of type B's")
        self.refused(ies_file(kind=2, vertical=(-60, 0, 90)), "its vertical angles run from -60 to 90 degrees")
        self.refused(ies_file(kind=2, vertical=(-90, 0, 60)), "its vertical angles run from -90 to 60 degrees")
        self.refused(ies_file(kind=2, vertical=(-90, 90), horizontal=(-180, 0, 180)),
                     "its horizontal angles run from -180 to 180 degrees: not one of type B's")
        self.refused(ies_file(kind=2, vertical=(-90, 90), horizontal=(0,)), "its horizontal angles run from 0 to 0")
        self.refused(ies_file(kind=2, vertical=(-90, 90), horizontal=(-90, 0)),
                     "its horizontal angles run from -90 to 0")
        self.refused(ies_file(kind=3, vertical=(-90, 90), horizontal=(0, 90)),
                     "its horizontal angles run from 0 to 90 degrees: not one of type A's")
        self.refused(ies_file(kind=2, vertical=(-90, 90, 0), horizontal=(0, 90)),
                     "its vertical angles are not in order")
        self.refused(ies_file(kind=2, vertical=(-90, 90), horizontal=(90, 0)), "its horizontal angles are not in order")

    def test_no_tilt_line(self):
        self.refused(b"IESNA:LM-63-2002\n1 500 1 3 1 1 2 0 0 0\n", "no TILT line")

    def test_truncated(self):
        data = ies_file()
        self.refused(data[:data.rindex(b" ")], "the file ends inside its angles or candelas")
        self.refused(b"TILT=NONE\n1 500", "the file ends before its candela multiplier")
        self.refused(b"TILT=INCLUDE\n1 4000 0 90", "the file ends inside its tilt angles and factors")

    def test_tokens_are_read_lazily(self):
        # numbers past the table are never split off: the parse costs far less memory than the file
        data = ies_file() + b"1 " * (1 << 19)
        tracemalloc.start()
        try:
            p = ies.parse(data)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertAlmostEqual(p.flux, ISOTROPIC, delta=1e-9)
        self.assertLess(peak, len(data) // 4)
        many = b"TILT=NONE\n1 500 1 1024 1024 1 2 0 0 0\n1 1 0\n" + b"1 " * (1 << 19)
        tracemalloc.start()
        try:
            with self.assertRaises(ies.IesError) as cm:
                ies.parse(many)  # half a million numbers, a million candelas counted: refused before any list
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(str(cm.exception), "the file ends inside its angles or candelas")
        self.assertLess(peak, len(many) // 4)

    def test_not_numbers(self):
        for bad in (b"nan", b"inf", b"1_0", b"0x10", b"--1"):
            self.refused(ies_file().replace(b" 500 ", b" " + bad + b" ", 1), "its lumens per lamp: not a number")
        self.refused(ies_file().replace(b" 500 ", b" 1e999 ", 1), "its lumens per lamp: a number out of range")

    def test_counts(self):
        self.refused(ies_file(lamps=0), "its number of lamps 0")
        self.refused(ies_file(vertical=(0,)), "its number of vertical angles 1")
        self.refused(ies_file(horizontal=()), "its number of horizontal angles 0")
        self.refused(ies_file().replace(b"1 500 1 3", b"1 500 1 3.5", 1), "its number of vertical angles 3.5")
        many = ies.MAX_ANGLES + 1
        self.refused(b"TILT=NONE\n1 500 1 %d 1 1 2 0 0 0\n1 1 0\n" % many, "its number of vertical angles %d" % many)
        n = 2048
        self.refused(b"TILT=NONE\n1 500 1 %d %d 1 2 0 0 0\n1 1 0\n" % (n, n), "%d x %d candelas" % (n, n))

    def test_angles(self):
        self.refused(ies_file(vertical=(0, 90, 45)), "its vertical angles are not in order")
        self.refused(ies_file(vertical=(0, 90, 190)), "its vertical angles are not in order")
        self.refused(ies_file(vertical=(-10, 90)), "its vertical angles are not in order")
        self.refused(ies_file(horizontal=(0, 90, 45)), "its horizontal angles are not in order")
        self.refused(ies_file(horizontal=(0, 120)), "its horizontal angles run from 0 to 120 degrees")
        self.refused(ies_file(horizontal=(0, 0)), "its horizontal angles run from 0 to 0 degrees")
        self.refused(ies_file(horizontal=(45, 135)), "its horizontal angles run from 45 to 135 degrees")
        self.refused(ies_file(horizontal=(90, 200)), "its horizontal angles run from 90 to 200 degrees")

    def test_negative_values(self):
        self.refused(ies_file(multiplier=-1), "its candela multiplier -1 is negative")
        self.refused(ies_file(ballast=-0.5), "its ballast factor -0.5 is negative")
        self.refused(ies_file(candelas=[100, -1, 100]), "a candela value is negative")

    def test_flux_out_of_range(self):
        self.refused(ies_file(candela="1e300", multiplier="1e300"), "its flux is out of range")
        self.refused(ies_file(lamps=10, rated="1e308"), "its rated lumens are out of range")


class Read(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="maxdrop-ies-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_read_a_file(self):
        self.assertAlmostEqual(ies.read(self.write("a.ies", ies_file())).flux, ISOTROPIC, delta=1e-9)

    def test_a_file_past_the_cap_is_refused(self):
        path = self.write("big.ies", ies_file() + b" " * ies.MAX_BYTES)
        with self.assertRaises(ies.IesError) as cm:
            ies.read(path)
        self.assertEqual(str(cm.exception), "larger than 4 MiB")

    def test_a_missing_file(self):
        with self.assertRaises(ies.IesError) as cm:
            ies.read(os.path.join(self.dir, "none.ies"))
        self.assertTrue(str(cm.exception).startswith("cannot be opened: "), str(cm.exception))

    def test_lookup_reads_each_file_once(self):
        good, bad = self.write("good.ies", ies_file()), self.write("bad.ies", b"TILT=NONE\n")
        found = {"good.ies": good, "bad.ies": bad}
        asked = []

        class Index:
            def stopped_for(self, path, resolved=""):
                return []

            def find(self, path, resolved=""):
                asked.append(path)
                return types.SimpleNamespace(path=found[path], rule=1) if path in found else None
        lookup = ies.Lookup(Index())
        reads = []
        original = ies.read
        ies.read = lambda path: reads.append(path) or original(path)
        try:
            p, why = lookup.photometry("good.ies")
            self.assertEqual((round(p.flux, 6), why), (round(ISOTROPIC, 6), None))
            self.assertEqual(lookup.photometry("good.ies")[0], p)
            self.assertEqual(lookup.photometry("bad.ies"), (None, "the file ends before its number of lamps"))
            self.assertEqual(lookup.photometry("gone.ies"), (None, None))
        finally:
            ies.read = original
        self.assertEqual(reads, [good, bad])

    def test_lookup_says_where_the_search_stopped(self):
        textures = importlib.import_module(_PKG + ".convert.textures")
        scene = self.write("scene.max", b"")
        for n in range(4):
            self.write("a%d.txt" % n, b"")
        # in maps/, not beside the scene: the scene's folder is read in the file system's order (hashed on ext4),
        # so a lamp beside it could be among the 2 entries taken; maps/ is entered only after that listing
        os.mkdir(os.path.join(self.dir, "maps"))
        self.write(os.path.join("maps", "lamp.ies"), ies_file())
        lookup = ies.Lookup(textures.TextureIndex(scene, max_entries=2, is_local_drive=lambda path: False))
        self.assertEqual(lookup.photometry("lamp.ies"), (None, "not found: texture search of the scene's folder "
                                                         "stopped after 2 files and folders, in {0}; texture search of "
                                                         "maps or textures folders stopped after 2 files and folders, "
                                                         "in {0}".format(os.path.abspath(self.dir))))
        self.assertEqual(lookup.photometry("a:b.ies"), (None, None))  # a refused name is not searched
        roomy = ies.Lookup(textures.TextureIndex(scene, is_local_drive=lambda path: False))
        self.assertAlmostEqual(roomy.photometry("lamp.ies")[0].flux, ISOTROPIC, delta=1e-9)
        self.assertEqual(roomy.photometry("gone.ies"), (None, None))


if __name__ == "__main__":
    unittest.main()
