# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/modifiers.py and its place in convert/scene.py: TurboSmooth, MeshSmooth, Shell and
Symmetry as Blender modifiers, no Blender. The stack_convert fixture: each node's converted modifiers in order with
the settings its script set (tools/fixtures/stack_convert.ms), the mirror frames, the mesh shading a smoother sets,
a TurboSmooth above a Bend not converted, nothing converted with the option off, the report's counts; stack_basic's
TurboSmooth above its applied UVW Map. Hand-made blocks: defaults, clamps, refusals and the Solidify arithmetic.
tests/blender/run.py checks the built modifiers against 3ds Max's evaluated meshes.

    python -I -m unittest discover tests
"""
import importlib
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
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "stack_convert.max")
STACK_BASIC = os.path.join(ROOT, "tests", "fixtures", "stack_basic.max")
MM = 0.001  # the fixture's unit

_PKG = "maxdrop_convert_test"  # the same package as test_convert_scene: the add-on's __init__ never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
conv = importlib.import_module(_PKG + ".convert.scene")
rules = importlib.import_module(_PKG + ".convert.modifiers")
report = importlib.import_module(_PKG + ".convert.report")
classids = importlib.import_module(_PKG + ".reader.classids")
controllers = importlib.import_module(_PKG + ".reader.controllers")
pblock = importlib.import_module(_PKG + ".reader.pblock")

SUBSURF, SOLIDIFY, MIRROR = rules.SUBSURF, rules.SOLIDIFY, rules.MIRROR
X, Y, Z = (True, False, False), (False, True, False), (False, False, True)
NONE = (False, False, False)


def _subsurf(levels, render):
    return (SUBSURF, {"subdivision_type": "CATMULL_CLARK", "levels": levels, "render_levels": render,
                      "use_limit_surface": False, "use_creases": True})


def _solidify(inner, outer):
    return (SOLIDIFY, {"solidify_mode": "EXTRUDE", "thickness": (inner + outer) * MM,
                       "offset": (outer - inner) / (outer + inner), "use_even_offset": False, "use_rim": True})


def _mirror(axis, flip, slice_, weld, threshold):
    return (MIRROR, {"use_axis": axis, "use_bisect_axis": axis if slice_ else NONE,
                     "use_bisect_flip_axis": axis if flip and slice_ else NONE, "use_mirror_merge": weld,
                     "merge_threshold": threshold * MM})


# From tools/fixtures/stack_convert.ms, bottom first.
CONVERTED = {
    "FixtureTurboOne": [_subsurf(1, 1)],
    "FixtureTurboRender": [_subsurf(1, 2)],
    "FixtureMeshSmooth": [_subsurf(2, 2)],
    "FixtureShell": [_solidify(1.0, 2.0)],
    "FixtureSymmetry": [_mirror(X, False, True, True, 0.1)],
    "FixtureSymmetryTurned": [_mirror(Y, True, True, True, 0.2)],
    "FixtureSymmetryNoSlice": [_mirror(Z, False, False, False, 0.1)],
    "FixtureOrder": [_solidify(0.0, 1.0), _mirror(X, False, True, True, 0.1), _subsurf(1, 1)],
    "FixtureBlocked": [],
}
SHADING = {"FixtureTurboOne": rules.SMOOTH, "FixtureTurboRender": rules.CREASE, "FixtureMeshSmooth": rules.SMOOTH,
           "FixtureOrder": rules.SMOOTH}
SHARP_EDGES_BOX = 12  # a poly box: a smoothing group per side


def _frame(rows):
    """A reader (row-vector) matrix in file units as the Blender columns in meters that convert.modifiers makes."""
    return tuple(tuple(rows[r][c] * (MM if r == 3 else 1.0) for r in range(4)) for c in range(3)) + \
        ((0.0, 0.0, 0.0, 1.0),)


C30, S30 = math.cos(math.radians(30)), math.sin(math.radians(30))
MIRRORS = {
    "FixtureSymmetry": _frame(((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (5, 0, 0, 1))),
    # MAXScript's gizmo rotation of 30 degrees about Z is stored as the turn the other way, as a node's would be
    "FixtureSymmetryTurned": _frame(((C30, -S30, 0, 0), (S30, C30, 0, 0), (0, 0, 1, 0), (2, 3, 0, 1))),
}


def _close(a, b, tol=1e-6):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return abs(a - b) <= tol
    return a == b


@unittest.skipIf(numpy is None, "numpy missing")
class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.desc = conv.read(FIXTURE)
        cls.nodes = {n.name: n for n in cls.desc.nodes}

    def test_every_node(self):
        self.assertEqual(sorted(self.nodes), sorted(CONVERTED))

    def test_kinds_order_and_settings_as_the_script_set_them(self):
        for name, want in CONVERTED.items():
            got = self.nodes[name].converted
            self.assertEqual([m.kind for m in got], [k for k, _s in want], name)
            for m, (_kind, settings) in zip(got, want):
                self.assertEqual([a for a, _v in m.settings], list(settings), name)
                for attr, value in m.settings:
                    self.assertTrue(_close(value, settings[attr]), "%s %s: %r vs %r" % (name, attr, value,
                                                                                      settings[attr]))
                self.assertTrue(m.show_viewport, name)

    def test_names_and_classes(self):
        node = self.nodes["FixtureOrder"]
        self.assertEqual([m.class_name for m in node.converted], ["Shell", "Symmetry", "TurboSmooth"])
        self.assertEqual([m.name for m in node.converted], ["Shell", "Symmetry", "TurboSmooth"])
        self.assertEqual((node.applied, node.modifiers), ((), ()))
        self.assertEqual(self.nodes["FixtureMeshSmooth"].converted[0].class_name, "MeshSmooth")

    def test_mirror_frames(self):
        for name in ("FixtureSymmetry", "FixtureSymmetryTurned", "FixtureSymmetryNoSlice", "FixtureOrder"):
            mirrors = [m.mirror for m in self.nodes[name].converted if m.kind == MIRROR]
            want = MIRRORS.get(name)
            if want is None:
                self.assertEqual(mirrors, [None], name)
            else:
                self.assertTrue(_close(mirrors[0], want, 1e-6), "%s: %r" % (name, mirrors[0]))

    def test_shading_of_the_lowest_smoother(self):
        for name, node in self.nodes.items():
            md = self.desc.meshes[node.mesh]
            shading = SHADING.get(name)
            self.assertEqual(node.mesh[-1] == ("shading", shading), shading is not None, name)
            self.assertEqual(md.creases, shading == rules.CREASE, name)
            self.assertEqual(len(md.sharp_edges), 0 if shading == rules.SMOOTH else SHARP_EDGES_BOX, name)
            self.assertFalse(md.sharp_faces.any(), name)

    def test_a_turbosmooth_above_a_bend_is_not_converted(self):
        node = self.nodes["FixtureBlocked"]
        self.assertEqual((node.converted, node.modifiers), ((), ("TurboSmooth", "Bend")))
        self.assertEqual([r for _i, r in self.desc.issues], ["modifiers: TurboSmooth above Bend is not converted"])

    def test_the_report_counts_them_as_converted(self):
        rep = report.gather(self.desc)
        self.assertEqual(dict(rep.modifiers_converted), {"Symmetry": 4, "TurboSmooth": 3, "Shell": 2,
                                                         "MeshSmooth": 1})
        self.assertEqual(dict(rep.modifiers), {"TurboSmooth": 1, "Bend": 1})
        self.assertEqual(dict(rep.modifiers_applied), {})
        self.assertIn("Modifiers converted to a Blender modifier, nodes by class: Symmetry 4, TurboSmooth 3, "
                      "Shell 2, MeshSmooth 1", rep.text())

    def test_option_off_converts_nothing(self):
        desc = conv.read(FIXTURE, convert_modifiers=False)
        self.assertTrue(all(not n.converted for n in desc.nodes))
        self.assertEqual(desc.issues, [])
        self.assertEqual({n.name: n.modifiers for n in desc.nodes}["FixtureOrder"],
                         ("TurboSmooth", "Symmetry", "Shell"))
        self.assertTrue(all(len(md.sharp_edges) == SHARP_EDGES_BOX and not md.creases
                            for md in desc.meshes.values()))
        self.assertEqual(sum(report.gather(desc).modifiers.values()), 12)

    def test_stack_basic_turbosmooth_above_its_uvw_map(self):
        desc = conv.read(STACK_BASIC)
        node = next(n for n in desc.nodes if n.name == "FixtureTurbo")
        self.assertEqual((node.applied, node.modifiers), (("UVW Map",), ()))
        self.assertEqual([(m.kind, dict(m.settings)["levels"]) for m in node.converted], [(SUBSURF, 2)])
        self.assertEqual(node.mesh[-1], ("shading", rules.SMOOTH))


class FakeBlock:
    def __init__(self, values):
        self.values = values

    def get(self, i, default=None):
        return self.values.get(i, default)


class FakeScene:
    def entry(self, i):
        return types.SimpleNamespace(name="Fake")

    def __len__(self):
        return 0


IDENTITY = controllers.IDENTITY


def _modifier(class_id, values, context=IDENTITY, refs=None):
    return types.SimpleNamespace(index=7, class_id=class_id, superclass=classids.SC_OSMODIFIER, name="",
                                 blocks={0: FakeBlock(values)} if values is not None else {}, enabled_in_views=False,
                                 context=None if context is None else types.SimpleNamespace(tm=context),
                                 refs=refs or {}, gizmo=None)


def _convert(class_id, values, **kw):
    return rules.convert(FakeScene(), _modifier(class_id, values, **kw), 0.5)


def _translate(x, y, z):
    return ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (x, y, z, 1.0))


class Rules(unittest.TestCase):
    def test_is_convertible(self):
        for cid in (classids.TURBOSMOOTH, classids.MESHSMOOTH, classids.SHELL, classids.SYMMETRY):
            self.assertTrue(rules.is_convertible(_modifier(cid, {})))
        self.assertFalse(rules.is_convertible(_modifier(classids.UVW_MAP, {})))
        self.assertFalse(rules.is_convertible(types.SimpleNamespace(class_id=classids.SHELL,
                                                                    superclass=classids.SC_WSMODIFIER)))
        with self.assertRaises(rules.ModifierError):
            _convert(classids.EXTRUDE, {})

    def test_defaults(self):
        md, issues = _convert(classids.TURBOSMOOTH, {})
        self.assertEqual((md.kind, dict(md.settings)["levels"], dict(md.settings)["render_levels"], md.shading,
                          md.show_viewport, md.name, md.class_name, md.index, issues),
                         (SUBSURF, 1, 1, rules.SMOOTH, False, "Fake", "Fake", 7, []))
        md, issues = _convert(classids.SHELL, {})
        self.assertEqual((dict(md.settings)["thickness"], dict(md.settings)["offset"], issues), (0.5, 1.0, []))

    def test_render_iterations_and_shading(self):
        md, _i = _convert(classids.TURBOSMOOTH, {0: 2, 1: 1, 2: 3, 4: 0})
        self.assertEqual((dict(md.settings)["levels"], dict(md.settings)["render_levels"], md.shading), (2, 3, None))
        md, _i = _convert(classids.TURBOSMOOTH, {6: 1})
        self.assertEqual(md.shading, rules.CREASE)
        md, _i = _convert(classids.MESHSMOOTH, {4: 3, 13: 1, 14: 4, 5: 0, 7: 1})
        self.assertEqual((dict(md.settings)["levels"], dict(md.settings)["render_levels"], md.shading),
                         (3, 4, rules.CREASE))

    def test_iterations_are_clamped(self):
        md, issues = _convert(classids.TURBOSMOOTH, {0: 12, 1: 1, 2: -1})
        self.assertEqual((dict(md.settings)["levels"], dict(md.settings)["render_levels"], len(issues)), (10, 0, 2))

    def test_what_is_not_converted_is_an_issue(self):
        cases = ((classids.MESHSMOOTH, {9: rules.CLASSIC}), (classids.MESHSMOOTH, {9: 5}),
                 (classids.MESHSMOOTH, {2: 0.5}), (classids.MESHSMOOTH, {6: 1}), (classids.TURBOSMOOTH, {5: 1}),
                 (classids.SHELL, {12: 3}), (classids.SHELL, {19: 1}), (classids.SHELL, {2: 1}),
                 (classids.SHELL, {8: 1}), (classids.SHELL, {17: 1}), (classids.SHELL, {4: 1}))
        for cid, values in cases:
            _md, issues = _convert(cid, values)
            self.assertEqual(len(issues), 1, repr(values))
        _md, issues = _convert(classids.MESHSMOOTH, {9: rules.QUAD_OUTPUT})
        self.assertEqual(issues, [])

    def test_shell_surfaces(self):
        for (inner, outer), (thickness, offset) in (((1.0, 2.0), (1.5, 1.0 / 3.0)), ((0.0, 1.0), (0.5, 1.0)),
                                                    ((1.0, 0.0), (0.5, -1.0)), ((1.0, 1.0), (1.0, 0.0))):
            md, _i = _convert(classids.SHELL, {0: inner, 1: outer})
            s = dict(md.settings)
            self.assertAlmostEqual(s["thickness"], thickness, msg=repr((inner, outer)))
            self.assertAlmostEqual(s["offset"], offset, msg=repr((inner, outer)))

    def test_refused(self):
        cases = ((classids.TURBOSMOOTH, None), (classids.TURBOSMOOTH, {0: pblock.Animated(3)}),
                 (classids.TURBOSMOOTH, {0: "two"}), (classids.TURBOSMOOTH, {0: float("nan")}),
                 (classids.TURBOSMOOTH, {0: True}), (classids.SHELL, {0: 0.0, 1: 0.0}),
                 (classids.SHELL, {0: -1.0, 1: 1.0}), (classids.SHELL, {0: 2.0, 1: -1.0}),
                 (classids.SHELL, {1: float("inf")}), (classids.SYMMETRY, {0: 3}), (classids.SYMMETRY, {3: (1, 2)}))
        for cid, values in cases:
            with self.assertRaises(rules.ModifierError, msg=repr(values)):
                _convert(cid, values)
        with self.assertRaises(rules.ModifierError):
            _convert(classids.SYMMETRY, {}, context=None)

    def test_symmetry_without_a_gizmo_mirrors_in_the_object_axes(self):
        md, issues = _convert(classids.SYMMETRY, {0: 1, 4: 1, 2: 0})
        s = dict(md.settings)
        self.assertEqual((md.mirror, s["use_axis"], s["use_bisect_axis"], s["use_bisect_flip_axis"],
                          s["use_mirror_merge"], len(issues)), (None, Y, Y, Y, False, 1))
        self.assertAlmostEqual(s["merge_threshold"], 0.05)

    def test_mirror_frame(self):
        e = rules.mirror_frame(_translate(5, 0, 0), _translate(2, 0, 0), _translate(1, 0, 0))
        self.assertEqual(e[3][:3], (4.0, 0.0, 0.0))
        self.assertEqual(rules.mirror_frame(IDENTITY, IDENTITY, None), IDENTITY)
        zero = ((0.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        for gizmo, context in ((zero, IDENTITY), (IDENTITY, zero)):
            with self.assertRaises(rules.ModifierError):
                rules.mirror_frame(gizmo, context, None)


if __name__ == "__main__":
    unittest.main()
