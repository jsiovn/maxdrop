# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/texmaps/ on the Noise map: a Mix of its two sides by a Noise leaf on its XYZGen
coordinates, lengths in meters, approximated, by input kind, and the numbers the builder copies, no Blender.

    python -I -m unittest discover tests
"""
import collections
import math
import os
import sys
import types
import unittest

_TESTS = "maxdrop_unit_tests"  # tests/unit as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_unit_tests.texmaps_support import (  # noqa: E402 (after the loader)
    _bitmap, _bw_mix, _decodes, _noise, _table, _vnormal, Checks, classids, colors, FakeMap, FakeOld, FakeGraph, Fixture, mat,
    reader_materials, Ref, tx,
)

RED, BLUE = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
XYZGEN_OBJECT, OUTPUT_OBJECT = 70, 71
CM = 0.01  # meters per file unit of a centimeter scene


def _nz(index=1, coords=None, level=None, **params):
    """A Noise (block 0 as params, p<id>=value) with an XYZGen part whose old ParamBlock holds coords ({index:
    Point3}; None: no part) and an Output part of that RGB level (None: none)."""
    p = {int(k[1:]): v for k, v in params.items()}
    children = [r.index for r in p.values() if isinstance(r, Ref) and r.index is not None]
    m = FakeMap(index, classids.NOISE, p, children, cls="Noise", name="nz")
    if coords is not None:
        m.parts[0] = reader_materials.Part(XYZGEN_OBJECT, (0x100, 0), classids.SC_XYZGEN, {}, {0: FakeOld(coords)})
    if level is not None:
        m.parts[4] = reader_materials.Part(OUTPUT_OBJECT, classids.STD_TEXOUTPUT, classids.SC_TEXOUTPUT, {},
                                           {0: FakeOld({tx.OUT_LEVEL: level})})
    return m


def _conv(*objects, meters=CM, swatches=None):
    return tx.TexmapConverter(FakeGraph(*objects), _table(), swatches=swatches, meters=meters)


class NoiseRule(Checks):
    """Noise (0x234, 0): block 0 colors 0 / 1, maps 2 / 3, switches 4 / 5, size 6, phase 7, levels 8, thresholds 9 /
    10, type 11 (the pblock_animated oracle); its XYZGen part's old ParamBlock 0 offset, 1 tiling, 2 angle."""

    def test_class(self):
        self.assertEqual(classids.name_of(classids.SC_TEXMAP, classids.NOISE), "Noise")
        self.assertIn(classids.NOISE, tx._KEEP)
        self.assertIn(classids.NOISE, tx.MASK_MIXES)
        self.assertIn(classids.NOISE, tx.DISPLAY_MIXES)

    def test_size_25_in_a_centimeter_scene(self):
        """Size 25 in a centimeter scene is 0.25 m: a Mapping scale of 4 per meter (1 / 0.25), no shift; black and
        white sides; approximated, counted by class."""
        tex = _conv(_nz(p6=25.0))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix)
        self.close((g.root.a.value, g.root.b.value), ((0.0,) * 3, (1.0,) * 3))
        noise = g.root.mask
        self.assertIsInstance(noise, tx.Noise)
        self.close(noise.size, 0.25)
        location, rotation, scale = tx.noise_placement(noise)
        self.close(scale, (4.0, 4.0, 4.0))
        self.close(location, (0.0, 0.0, 0.0))
        self.close(rotation, (0.0, 0.0, 0.0))
        self.assertTrue(g.approximated)
        self.assertEqual(g.issues, ())
        self.assertEqual(tex.stats.approximated, collections.Counter({"Noise": 1}))
        self.assertEqual((tex.stats.peeled, tex.stats.unsupported), (collections.Counter(),) * 2)

    def test_parameters(self):
        """Phase, levels, type and thresholds as stored; type 1 fractal, 2 turbulence; the defaults without them
        (size 25 file units, phase 0, levels 3, regular, thresholds 0 and 1)."""
        n = _conv(_nz(p6=10.0, p7=1.5, p8=4.0, p9=0.2, p10=0.7, p11=1)).convert(mat.MapRef(1), tx.COLOR).root.mask
        self.assertEqual(n, tx.Noise(tx.Coordinates(), 0.1, 1.5, 4.0, 0.2, 0.7, tx.FRACTAL))
        n = _conv(_nz(p11=2)).convert(mat.MapRef(1), tx.COLOR).root.mask
        self.assertEqual(n.kind, tx.TURBULENCE)
        n = _conv(_nz()).convert(mat.MapRef(1), tx.COLOR).root.mask
        self.assertEqual(n, tx.Noise(tx.Coordinates(), 0.25, 0.0, 3.0, 0.0, 1.0, tx.REGULAR))

    def test_detail(self):
        """Levels drive only fractal and turbulence noise (one octave a level): Detail levels - 1 within 0..15."""
        def detail(kind, levels):
            return tx.noise_detail(tx.Noise(levels=levels, kind=kind))
        self.close(detail(tx.REGULAR, 6.0), 0.0)
        self.close(detail(tx.FRACTAL, 3.0), 2.0)
        self.close(detail(tx.TURBULENCE, 2.5), 1.5)
        self.close(detail(tx.FRACTAL, 0.5), 0.0)
        self.close(detail(tx.FRACTAL, 40.0), 15.0)

    def test_coordinates(self):
        """The XYZGen's offset (file units, so in meters), tiling and angle (radians): q = R (tiling * (p - offset))
        / size, which the Mapping node draws as scale tiling / size and location -R (scale * offset)."""
        coords = {tx.XYZ_OFFSET: (10.0, 0.0, -20.0), tx.XYZ_TILING: (2.0, 1.0, 0.5),
                  tx.XYZ_ANGLE: (0.0, 0.0, math.pi / 2)}
        n = _conv(_nz(coords=coords, p6=50.0)).convert(mat.MapRef(1), tx.COLOR).root.mask
        self.assertEqual(n.coords.source, tx.OBJECT_XYZ)
        self.close(n.coords.offset, (0.1, 0.0, -0.2))
        self.close(n.coords.tiling, (2.0, 1.0, 0.5))
        self.close(n.coords.angle, (0.0, 0.0, math.pi / 2))
        location, rotation, scale = tx.noise_placement(n)
        self.close(scale, (4.0, 2.0, 1.0))
        self.close(rotation, (0.0, 0.0, math.pi / 2))
        # scale * offset = (0.4, 0, -0.2); turned 90 degrees about Z: (0, 0.4, -0.2); negated
        self.close(location, (0.0, -0.4, 0.2))
        for p in ((0.3, -0.1, 0.05), (0.1, 0.0, -0.2)):
            want = tuple(s * (c - o) for s, c, o in zip(scale, p, n.coords.offset))
            want = (-want[1], want[0], want[2])  # turned 90 degrees about Z
            r = tx._rotation(rotation)
            got = tuple(location[i] + sum(r[i][k] * scale[k] * p[k] for k in range(3)) for i in range(3))
            self.close(got, want, str(p))

    def test_unusable_coordinates_take_the_defaults(self):
        n = _conv(_nz(coords={tx.XYZ_OFFSET: (1.0, float("nan"), 0.0), tx.XYZ_TILING: 3.0})).convert(
            mat.MapRef(1), tx.COLOR).root.mask
        self.assertEqual(n.coords, tx.Coordinates())

    def test_thresholds(self):
        """Clamped to 0..1; a high threshold not above the low one is a step: a ramp of THRESHOLD_SPAN."""
        n = _conv(_nz(p9=-0.5, p10=2.0)).convert(mat.MapRef(1), tx.COLOR).root.mask
        self.close((n.low, n.high), (0.0, 1.0))
        n = _conv(_nz(p9=0.5, p10=0.5)).convert(mat.MapRef(1), tx.COLOR).root.mask
        self.close((n.low, n.high), (0.5, 0.5 + tx.THRESHOLD_SPAN))
        n = _conv(_nz(p9=1.0, p10=0.2)).convert(mat.MapRef(1), tx.COLOR).root.mask
        self.close((n.low, n.high), (1.0 - tx.THRESHOLD_SPAN, 1.0))

    def test_unusable_size_and_type(self):
        """A size not above 0 (or too small in meters) is the default, a type outside 0..2 regular: each a line."""
        for size in (0.0, -3.0, 1e-9):
            with self.subTest(size):
                g = _conv(_nz(p6=size)).convert(mat.MapRef(1), tx.COLOR)
                self.close(g.root.mask.size, 0.25)
                self.assertEqual(g.issues, ("Noise 'nz': size %r not converted: 25" % size,))
        g = _conv(_nz(p11=7)).convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.mask.kind, tx.REGULAR)
        self.assertEqual(g.issues, ("Noise 'nz': type 7 drawn as regular",))

    def test_meters_default_to_the_file(self):
        """Without meters the file's own unit; a scene that does not say is in inches (3ds Max's default)."""
        tex = tx.TexmapConverter(FakeGraph(_nz(p6=25.0)), _table())
        self.close(tex.meters, 0.0254)
        self.close(tex.convert(mat.MapRef(1), tx.COLOR).root.mask.size, 0.635)

    def test_sides(self):
        """Red and blue sides; map 2 used: the converted map on that side; switched off: its color. A data input:
        each side the mean of its swatch."""
        g = _conv(_nz(p0=RED, p1=BLUE)).convert(mat.MapRef(1), tx.COLOR)
        self.close((g.root.a.value, g.root.b.value), (RED, BLUE))
        g = _conv(_nz(p0=RED, p3=Ref(2)), _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root.b, tx.Image)
        self.assertTrue(g.approximated)
        g = _conv(_nz(p1=BLUE, p3=Ref(2), p5=0), _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.b.value, BLUE, "map 2 off")
        g = _conv(_nz(p0=RED, p1=BLUE)).convert(mat.MapRef(1), tx.DATA)
        self.close((g.root.a.value, g.root.b.value), (1 / 3, 1 / 3))
        self.assertIsInstance(g.root.mask, tx.Noise)

    def test_a_lost_side_peels_to_the_other(self):
        """A used side map that converts to nothing: the other side's map, counted as peeled, not approximated."""
        tex = _conv(_nz(p2=Ref(2), p3=Ref(3)), _bitmap(2), _noise(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Image)
        self.assertEqual(tex.stats.peeled, collections.Counter({"Noise": 1}))
        self.assertEqual(tex.stats.approximated, collections.Counter())

    def test_output_part(self):
        """Its Output part, when it changes anything, as an Adjust over the Mix (as a Falloff's)."""
        g = _conv(_nz(level=0.5)).convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Adjust)
        self.close(g.root.output.level, 0.5)
        self.assertIsInstance(g.root.input.mask, tx.Noise)
        g = _conv(_nz(level=1.0)).convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix, "an Output that changes nothing")

    def test_bump_input(self):
        """A bump input: black to white the Bump of the leaf itself; other sides, or an Output part, the Mix."""
        tex = _conv(_nz())
        g = tex.convert(mat.MapRef(1, 0.3), tx.BUMP)
        self.assertIsInstance(g.root, tx.Bump)
        self.assertIsInstance(g.root.input, tx.Noise)
        self.close(g.root.strength, 0.3)
        self.assertTrue(g.approximated)
        self.assertEqual(tex.stats.approximated, collections.Counter({"Noise": 1}))
        g = _conv(_nz(p0=RED)).convert(mat.MapRef(1), tx.BUMP)
        self.assertIsInstance(g.root.input, tx.Mix)
        self.close((g.root.input.a.value, g.root.input.b.value), (1 / 3, 1.0))
        g = _conv(_nz(level=0.5)).convert(mat.MapRef(1), tx.BUMP)
        self.assertIsInstance(g.root.input, tx.Adjust)

    def test_normal_slot(self):
        """In a normal map's normal slot: left out with an issue, no graph, not counted."""
        tex = _conv(_vnormal(1, 2), _nz(2))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.NORMAL))
        self.assertIn("Noise 'nz': a pattern in a normal map's normal slot not converted",
                      [r for _i, r in tex.stats.issues])
        self.assertEqual((tex.stats.unsupported, tex.stats.approximated), (collections.Counter(),) * 2)

    def test_mask_of_a_mix(self):
        """As a Mix's mask in a color graph (gamma on): the Mix of its sides as masks, by the leaf."""
        tex = _conv(FakeMap(1, tx.MIX, {0: 0.0, 4: RED, 5: BLUE, 8: Ref(2)}, [2], cls="Mix"), _nz(2))
        mask = tex.convert(mat.MapRef(1), tx.COLOR).root.mask
        self.assertIsInstance(mask, tx.Mix)
        self.assertIsInstance(mask.mask, tx.Noise)

    def test_gamma_off(self):
        """With the gamma off a Noise is computed on the stored values, as a Falloff: at a color root under one
        Decode, its sides as stored; as a mask the mean decoded."""
        g40, g220 = (40 / 255,) * 3, (220 / 255,) * 3
        root = _conv(_nz(p0=g40, p1=g220), swatches=colors.GAMMA_OFF).convert(mat.MapRef(1), tx.COLOR).root
        self.assertEqual(len(_decodes(root)), 1)
        held = self.held(root)
        self.close((held.a.value, held.b.value), (g40, g220), "its sides as stored")
        self.assertIsInstance(held.mask, tx.Noise)
        mask = _conv(_bw_mix(1, 2), _nz(2, p0=g40, p1=g220), swatches=colors.GAMMA_OFF).convert(
            mat.MapRef(1), tx.COLOR).root.mask
        self.assertIsInstance(mask, tx.Decode)
        self.assertTrue(mask.mean)
        self.assertIsInstance(mask.input.mask, tx.Noise)


class FixtureNoises(unittest.TestCase):
    """The committed fixtures that hold a Noise (pblock_animated, standard_shaders, vray_more, vray_texmaps): each one
    reached converts (approximated, never unsupported), stored size 635 in millimeters 0.635 m, regular, levels 3,
    thresholds 0 and 1, on its stored coordinates (no offset, tiling 1, no angle)."""

    def test_fixtures(self):
        for name in ("pblock_animated", "standard_shaders", "vray_more", "vray_texmaps"):
            with self.subTest(name):
                f = Fixture(name)
                try:
                    self.assertNotIn("Noise", f.tex.stats.unsupported)
                    self.assertNotIn("Noise", f.tex.stats.peeled)
                    leaves = [leaf for ir in f.irs.values() for g in ir.textures.values()
                              for leaf in _noises(g.root)]
                    self.assertTrue(leaves)
                    self.assertIn("Noise", f.tex.stats.approximated)
                    for leaf in leaves:
                        self.assertEqual((leaf.coords, leaf.phase, leaf.levels, leaf.low, leaf.high, leaf.kind),
                                         (tx.Coordinates(), 0.0, 3.0, 0.0, 1.0, tx.REGULAR))
                        self.assertAlmostEqual(leaf.size, 635.0 * f.tex.meters)
                    self.assertFalse([r for _i, r in f.tex.stats.issues if r.startswith("Noise")])
                finally:
                    f.close()


def _noises(root):
    """The Noise leaves of a graph."""
    seen, stack, leaves = set(), [root], []
    while stack:
        n = stack.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        if isinstance(n, tx.Noise):
            leaves.append(n)
        stack.extend(tx._children(n))
    return leaves


if __name__ == "__main__":
    unittest.main()
