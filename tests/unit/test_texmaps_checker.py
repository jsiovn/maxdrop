# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/texmaps/ on the Checker map: a Mix of its two sides by a 0 / 1 pattern leaf on its
placement, by input kind, and the pattern's evaluator, no Blender.

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
    _bitmap, _noise, _tex, _vnormal, Checks, classids, FakeMap, FakeOld, FakeGraph, Fixture, mat, reader_materials,
    Ref, tx, UVGEN_OBJECT,
)

RED, BLUE = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
GRID = 12


def _checker(index=1, tiling=None, **params):
    """A Checker (block 0 as params, p<id>=value) with a Placement part of that U / V tiling (None: none)."""
    p = {int(k[1:]): v for k, v in params.items()}
    children = [r.index for r in p.values() if isinstance(r, Ref) and r.index is not None]
    m = FakeMap(index, classids.CHECKER, p, children, cls="Checker", name="ck")
    if tiling is not None:
        m.parts = {0: reader_materials.Part(UVGEN_OBJECT, classids.STD_UVGEN, classids.SC_UVGEN, {},
                                            {0: FakeOld({tx.UV_U_TILING: tiling[0], tx.UV_V_TILING: tiling[1]})})}
    return m


class CheckerRule(Checks):
    """Checker (0x200, 0): block 0 soften 0, colors 1 / 2, maps 3 / 4, their switches 5 / 6 (the fixtures' oracles)."""

    def test_class(self):
        self.assertEqual(classids.name_of(classids.SC_TEXMAP, classids.CHECKER), "Checker")
        self.assertIn(classids.CHECKER, tx._KEEP)

    def test_tiling_2_by_3_red_and_blue(self):
        """The Mix of the two colors by the pattern; on a 12 x 12 grid of UVs the pattern is 0 or 1, a checker of
        4 x 6 squares: tiled about the tile center, x = 2u - 0.5 and y = 3v - 1, 2 squares a tile, so square
        (floor(4u) - 1, floor(6v) - 2), color 1 (0) where their sum is even."""
        tex = _tex(_checker(tiling=(2.0, 3.0), p1=RED, p2=BLUE))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Mix)
        self.close(g.root.a.value, RED, "color 1")
        self.close(g.root.b.value, BLUE, "color 2")
        pattern = g.root.mask
        self.assertIsInstance(pattern, tx.Checker)
        self.close(pattern.mapping.tiling, (2.0, 3.0))
        for i in range(GRID):
            for j in range(GRID):
                u, v = (i + 0.5) / GRID, (j + 0.5) / GRID
                want = float((math.floor(4 * u) - 1 + math.floor(6 * v) - 2) % 2)
                self.assertEqual(tx.checker_value(pattern, u, v), want, (i, j))
        row = [tx.checker_value(pattern, (i + 0.5) / GRID, 0.5 / GRID) for i in range(GRID)]
        self.assertEqual(row, [1.0] * 3 + [0.0] * 3 + [1.0] * 3 + [0.0] * 3, "3 samples a square along U")
        col = [tx.checker_value(pattern, 0.5 / GRID, (j + 0.5) / GRID) for j in range(GRID)]
        self.assertEqual(col, [1.0, 1.0, 0.0, 0.0] * 3, "2 samples a square along V")
        self.assertFalse(g.approximated, "exact")
        self.assertEqual(g.issues, ())
        self.assertEqual((tex.stats.peeled, tex.stats.unsupported, tex.stats.approximated),
                         (collections.Counter(),) * 3)

    def test_default_colors_and_placement(self):
        """Without a Placement part the pattern is on the UVs; black and white sides by default."""
        g = _tex(_checker()).convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.a.value, (0.0, 0.0, 0.0))
        self.close(g.root.b.value, (1.0, 1.0, 1.0))
        self.assertEqual(g.root.mask.mapping, tx.Mapping())
        self.assertEqual(tx.checker_value(g.root.mask, 0.25, 0.25), 0.0, "color 1 on the origin square")
        self.assertEqual(tx.checker_value(g.root.mask, 0.75, 0.25), 1.0)
        self.assertEqual(tx.checker_value(g.root.mask, 0.75, 0.75), 0.0)
        self.assertEqual(tx.checker_value(g.root.mask, -0.25, 0.25), 1.0, "negative UVs keep the parity")

    def test_placed_uv(self):
        """The placement a Bitmap has: offset (0.1, 0) and W 90 degrees turn (u, v) about the tile center."""
        m = tx.Mapping(offset=(0.1, 0.0), angle=(0.0, 0.0, math.pi / 2))
        self.close(tx.placed_uv(m, 0.2, 0.7), (0.3, 0.1))
        self.close(tx.placed_uv(tx.Mapping(tiling=(2.0, 1.0)), 0.75, 0.25), (1.0, 0.25))
        self.close(tx.placed_uv(tx.Mapping(), 0.3, 0.6), (0.3, 0.6))

    def test_data_input(self):
        """A data input: each side the mean of its swatch, the same pattern."""
        g = _tex(_checker(p1=RED, p2=BLUE)).convert(mat.MapRef(1), tx.DATA)
        self.assertIsInstance(g.root, tx.Mix)
        self.close((g.root.a.value, g.root.b.value), (1 / 3, 1 / 3))
        self.assertIsInstance(g.root.mask, tx.Checker)

    def test_side_maps(self):
        """Map 2 used: the converted map on that side; switched off: its color."""
        tex = _tex(_checker(p1=RED, p4=Ref(2)), _bitmap(2))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.a.value, RED)
        self.assertIsInstance(g.root.b, tx.Image)
        self.assertFalse(g.approximated)
        g = _tex(_checker(p2=BLUE, p4=Ref(2), p6=0), _bitmap(2)).convert(mat.MapRef(1), tx.COLOR)
        self.close(g.root.b.value, BLUE, "map 2 off")

    def test_a_lost_side_peels_to_the_other(self):
        tex = _tex(_checker(p3=Ref(2), p4=Ref(3)), _bitmap(2), _noise(3))
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root, tx.Image)
        self.assertTrue(g.approximated)
        self.assertEqual(tex.stats.peeled, collections.Counter({"Checker": 1}))
        self.assertTrue(any("its map Noise 'n' converts to nothing" in r for _i, r in tex.stats.issues))
        self.assertIsNone(_tex(_checker(p4=Ref(3)), _noise(3)).convert(mat.MapRef(1), tx.COLOR),
                          "color 1 is not the lost map's stand-in")

    def test_mask_of_a_mix(self):
        """As a Mix's mask in a color graph: the Mix of its sides as masks (the scene's rule on their means)."""
        tex = _tex(FakeMap(1, tx.MIX, {0: 0.0, 4: RED, 5: BLUE, 8: Ref(2)}, [2], cls="Mix"), _checker(2))
        mask = tex.convert(mat.MapRef(1), tx.COLOR).root.mask
        self.assertIsInstance(mask, tx.Mix)
        self.close((mask.a.value, mask.b.value), (0.0, 1.0))
        self.assertIsInstance(mask.mask, tx.Checker)

    def test_bump_input(self):
        """A bump input: the Bump of the pattern itself; sides other than black and white are a line."""
        tex = _tex(_checker())
        g = tex.convert(mat.MapRef(1, 0.4), tx.BUMP)
        self.assertIsInstance(g.root, tx.Bump)
        self.assertIsInstance(g.root.input, tx.Checker)
        self.close(g.root.strength, 0.4)
        self.assertEqual(g.issues, ())
        for params in (dict(p1=RED), dict(p2=BLUE), dict(p3=Ref(2))):
            with self.subTest(params):
                tex = _tex(_checker(**params), _bitmap(2))
                g = tex.convert(mat.MapRef(1), tx.BUMP)
                self.assertIsInstance(g.root.input, tx.Checker)
                self.assertEqual(g.issues, ("Checker 'ck': its sides in a bump input not converted: drawn black to "
                                            "white",))

    def test_normal_slot(self):
        """In a normal map's normal slot: left out with an issue, no graph, not counted as without a rule."""
        tex = _tex(_vnormal(1, 2), _checker(2))
        self.assertIsNone(tex.convert(mat.MapRef(1), tx.NORMAL))
        reasons = [r for _i, r in tex.stats.issues]
        self.assertIn("Checker 'ck': a pattern in a normal map's normal slot not converted", reasons)
        self.assertTrue(any(r.startswith("VRayNormalMap") and "converts to nothing" in r for r in reasons), reasons)
        self.assertEqual(tex.stats.unsupported, collections.Counter())

    def test_soften(self):
        """A soften above 0 is drawn as 0: a line, the pattern exact otherwise."""
        g = _tex(_checker(p0=0.5)).convert(mat.MapRef(1), tx.COLOR)
        self.assertIsInstance(g.root.mask, tx.Checker)
        self.close(g.root.mask.soften, 0.5)
        self.assertEqual(g.issues, ("Checker 'ck': soften 0.5 not converted: hard edges",))
        self.assertFalse(g.approximated)

    def test_placement_issues(self):
        """Tile off or mirror: the pattern repeats; map channel 0: UV channel 1; planar XYZ: drawn with the UVs."""
        tex = tx.TexmapConverter(FakeGraph(_checker()), None)
        tex._mapping = lambda uv, m: tx.Mapping(tile=(False, True), mirror=(True, False), channel=0,
                                                source=tx.OBJECT_XYZ)
        g = tex.convert(mat.MapRef(1), tx.COLOR)
        self.assertEqual(g.root.mask.mapping, tx.Mapping(source=tx.OBJECT_XYZ))
        self.assertEqual(g.issues, (
            "Checker 'ck': planar object XYZ mapping, drawn with the UVs",
            "Checker 'ck': tile off or mirror not converted: the pattern repeats",
            "Checker 'ck': map channel 0 (vertex color) not imported: drawn on UV channel 1"))



def _checkers(root):
    """The Checker leaves of a graph and the Mix nodes masked by one."""
    seen, stack, leaves, mixes = set(), [root], [], []
    while stack:
        n = stack.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        if isinstance(n, tx.Checker):
            leaves.append(n)
        if isinstance(n, tx.Mix) and isinstance(n.mask, tx.Checker):
            mixes.append(n)
        stack.extend(tx._children(n))
    return leaves, mixes


class FixtureCheckers(unittest.TestCase):
    """The committed fixtures that hold a Checker (pblock_animated, standard_shaders, standard_maps, vray_more): each
    one reached converts (no class without a rule but Noise), on its stored placement (tiling 1, no offset or angle)
    and black / white sides; pblock_animated's in a VRayNormalMap's normal slot is left out with its line."""

    def test_fixtures(self):
        for name in ("pblock_animated", "standard_shaders", "standard_maps", "vray_more"):
            with self.subTest(name):
                f = Fixture(name)
                try:
                    self.assertNotIn("Checker", f.tex.stats.unsupported)
                    self.assertNotIn("Checker", f.tex.stats.peeled)
                    leaves = [leaf for ir in f.irs.values() for g in ir.textures.values()
                              for leaf in _checkers(g.root)[0]]
                    if name == "pblock_animated":
                        self.assertIn("Checker 'FixtureAnimNormalMap': a pattern in a normal map's normal slot not "
                                      "converted", [r for _i, r in f.tex.stats.issues])
                        continue
                    self.assertTrue(leaves)
                    for leaf in leaves:
                        self.assertEqual(leaf, tx.Checker(tx.Mapping()))
                    self.assertFalse([r for _i, r in f.tex.stats.issues if r.startswith("Checker")])
                finally:
                    f.close()


if __name__ == "__main__":
    unittest.main()
