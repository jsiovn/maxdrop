# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/modifiers.py and its place in convert/scene.py: TurboSmooth, MeshSmooth, Shell and
Symmetry as Blender modifiers, no Blender. The stack_convert fixture: each node's converted modifiers in order with
the settings its script set (tools/fixtures/stack_convert.ms), the mirror frames, the mesh shading a smoother sets,
a TurboSmooth above a Bend not converted, nothing converted with the option off, the report's counts; stack_basic's
TurboSmooth above its applied UVW Map; stack_shell's one-sided and inside-out Shells and their rims (the open edges
sharp, the mesh key, the report; above a Symmetry the open edges it welds shut stay smooth). Hand-made
blocks: defaults, clamps, refusals, the Solidify arithmetic and the Shell's rim rule.
tests/blender/run.py checks the built modifiers against 3ds Max's evaluated meshes.

    python -I -m unittest discover tests
"""
import importlib
import math
import os
import sys
import time
import types
import unittest

try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "stack_convert.max")
STACK_BASIC = os.path.join(ROOT, "tests", "fixtures", "stack_basic.max")
STACK_SHELL = os.path.join(ROOT, "tests", "fixtures", "stack_shell.max")
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
geometry = importlib.import_module(_PKG + ".reader.geometry")

SUBSURF, SOLIDIFY, MIRROR = rules.SUBSURF, rules.SOLIDIFY, rules.MIRROR
X, Y, Z = (True, False, False), (False, True, False), (False, False, True)
NONE = (False, False, False)


def _subsurf(levels, render):
    return (SUBSURF, {"subdivision_type": "CATMULL_CLARK", "levels": levels, "render_levels": render,
                      "use_limit_surface": False, "boundary_smooth": "PRESERVE_CORNERS", "use_creases": True})


def _solidify(inner, outer):
    lo, hi = min(-inner, outer), max(-inner, outer)  # the surfaces along the normal
    return (SOLIDIFY, {"solidify_mode": "EXTRUDE", "thickness": (hi - lo) * MM, "offset": (hi + lo) / (hi - lo),
                       "use_even_offset": False, "use_rim": True, "use_flip_normals": inner + outer < 0})


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
    "FixtureTurboSymHalf": [_subsurf(1, 1), _mirror(X, False, True, True, 0.1)],
}
# From tools/fixtures/stack_shell.ms: (inner, outer) of each open box's Shell
SHELLS = {"FixtureShellOut": (-1.0, 2.0), "FixtureShellIn": (3.0, -1.0), "FixtureShellCrossed": (-2.0, 1.0),
          "FixtureShellNegative": (-1.0, -2.0), "FixtureShellRim": (0.0, 1.0)}
# stack_shell's rim nodes: the converted kinds, bottom first, and whether the rim is hardened (the mesh key)
SHELL_RIMS = {"FixtureShellPlane": ([SOLIDIFY], True), "FixtureShellOverride": ([SOLIDIFY], True),
              "FixtureShellTurbo": ([SUBSURF, SOLIDIFY], True), "FixtureShellSmoothed": ([SOLIDIFY, SUBSURF], False),
              "FixtureShellSymHalf": ([MIRROR, SOLIDIFY], True), "FixtureShellSymClosed": ([MIRROR, SOLIDIFY], True),
              "FixtureShellSymQuarter": ([MIRROR, MIRROR, SOLIDIFY], True),
              # a Shell below a Symmetry whose slice plane holds its rim: the Mirror moved below the Solidify; with a
              # smoother (Smooth Result) above, the rim is not hardened; weld off: not moved (a line)
              "FixtureShellUnderSym": ([MIRROR, SOLIDIFY], True),
              "FixtureShellUnderSymTurbo": ([MIRROR, SOLIDIFY, SUBSURF], False),
              "FixtureShellBetweenSym": ([MIRROR, MIRROR, SOLIDIFY], True),
              "FixtureShellUnderSymNoWeld": ([SOLIDIFY, MIRROR], True),
              "FixtureShellUnderSymExtrude": ([MIRROR, SOLIDIFY], True)}  # an open Line under an Extrude
# (open edges of the base mesh, those of them sharp) where not (4, 4) hardened or (4, 0): the half and quarter boxes
# below a Symmetry, their cut's open edges on the mirror plane welded shut (not sharp), the top's sharp
SHELL_RIM_EDGES = {"FixtureShellSymHalf": (8, 4), "FixtureShellSymClosed": (6, 0), "FixtureShellSymQuarter": (6, 2),
                   "FixtureShellUnderSym": (8, 4), "FixtureShellUnderSymTurbo": (8, 0),
                   "FixtureShellBetweenSym": (6, 2), "FixtureShellUnderSymNoWeld": (8, 8),
                   "FixtureShellUnderSymExtrude": (8, 6)}
# the report lines stack_shell is made to raise: the plane's four rim corners of 90 degrees, the override group 4
SHELL_ISSUES = [("FixtureShellPlane", "modifiers: Shell: auto smooth: 4 corners of the rim sharper than 45 degrees "
                 "shade smooth (3ds Max splits the rim there)"),
                ("FixtureShellOverride", "modifiers: Shell: smoothing group override (group 4) not converted: 3ds "
                 "Max merges the rim into the faces along it of that group"),
                # its Symmetry's weld is off: 3ds Max's slice drops the rim on the plane and leaves the cut open
                ("FixtureShellUnderSymNoWeld", "modifiers: Symmetry: the rim of the Shell below it along the mirror "
                 "plane differs from 3ds Max's: the Mirror is moved below the Solidify only for a rim lying on the "
                 "plane, with slice and weld on")]
SHADING = {"FixtureTurboOne": rules.SMOOTH, "FixtureTurboRender": rules.CREASE, "FixtureMeshSmooth": rules.SMOOTH,
           "FixtureOrder": rules.SMOOTH, "FixtureTurboSymHalf": rules.SMOOTH}
SHARP_EDGES_BOX = 12  # a poly box: a smoothing group per side
# FixtureTurboSymHalf's open half box: the five edges between its four sides
SHARP_EDGES_HALF_BOX = {"FixtureTurboSymHalf": 5}


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
        self.assertEqual(dict(rep.modifiers_converted), {"Symmetry": 5, "TurboSmooth": 4, "Shell": 2,
                                                         "MeshSmooth": 1})
        self.assertEqual(dict(rep.modifiers), {"TurboSmooth": 1, "Bend": 1})
        self.assertEqual(dict(rep.modifiers_applied), {})
        self.assertIn("Modifiers converted to a Blender modifier, nodes by class: Symmetry 5, TurboSmooth 4, "
                      "Shell 2, MeshSmooth 1", rep.text())

    def test_option_off_converts_nothing(self):
        desc = conv.read(FIXTURE, convert_modifiers=False)
        self.assertTrue(all(not n.converted for n in desc.nodes))
        self.assertEqual(desc.issues, [])
        self.assertEqual({n.name: n.modifiers for n in desc.nodes}["FixtureOrder"],
                         ("TurboSmooth", "Symmetry", "Shell"))
        for node in desc.nodes:
            md = desc.meshes[node.mesh]
            self.assertEqual(len(md.sharp_edges), SHARP_EDGES_HALF_BOX.get(node.name, SHARP_EDGES_BOX), node.name)
            self.assertFalse(md.creases, node.name)
        self.assertEqual(sum(report.gather(desc).modifiers.values()), 14)

    def test_stack_shell_one_sided_and_inside_out(self):
        desc = conv.read(STACK_SHELL)
        self.assertEqual(sorted(n.name for n in desc.nodes), sorted(list(SHELLS) + list(SHELL_RIMS)))
        for node in (n for n in desc.nodes if n.name in SHELLS):
            want = dict(_solidify(*SHELLS[node.name])[1])
            self.assertEqual([m.kind for m in node.converted], [SOLIDIFY], node.name)
            got = dict(node.converted[0].settings)
            self.assertEqual(sorted(got), sorted(want), node.name)
            self.assertTrue(all(_close(got[a], want[a]) for a in want), "%s: %r" % (node.name, got))
            self.assertEqual(node.modifiers, (), node.name)
        flips = {n.name: dict(n.converted[0].settings)["use_flip_normals"] for n in desc.nodes if n.name in SHELLS}
        self.assertEqual(flips, {"FixtureShellOut": False, "FixtureShellIn": False, "FixtureShellCrossed": True,
                                 "FixtureShellNegative": True, "FixtureShellRim": False})

    def test_stack_shell_rims(self):
        desc = conv.read(STACK_SHELL)
        names = {n.index: n.name for n in desc.nodes}
        # the open boxes' rims match 3ds Max's (coplanar, auto smooth on): no line for them
        self.assertEqual(sorted((names[i], x) for i, x in desc.issues), sorted(SHELL_ISSUES))
        for node in desc.nodes:
            kinds, hardened = SHELL_RIMS.get(node.name, ([SOLIDIFY], True))
            self.assertEqual([m.kind for m in node.converted], kinds, node.name)
            rim = node.mesh[-1] if node.mesh[-1][0] == "rim" else None
            self.assertEqual(rim is not None, hardened, node.name)
            seam = next((x for x in node.mesh if isinstance(x, tuple) and x and x[0] == "seam"), None)
            # the rim entry holds the Mirrors below the Shell in 3ds Max's stack, True without one; the seam entry
            # those below it and those right above it
            mirrors = tuple((m.settings, m.mirror) for m in node.converted if m.kind == MIRROR)
            mirrors = tuple(m for m in mirrors if not (seam and m in seam[2]))
            self.assertEqual(rim and rim[1], mirrors or True if hardened else None, node.name)
            md = desc.meshes[node.mesh]
            boundary = conv.open_edges(md.loop_vertices, md.loop_starts, md.loop_totals)
            sharp = {tuple(e) for e in md.sharp_edges.tolist()}
            got = (len(boundary), sum(tuple(e) in sharp for e in boundary.tolist()))
            # every other base mesh: the top's (the plane's) 4 edges
            self.assertEqual(got, SHELL_RIM_EDGES.get(node.name, (4, 4 if hardened else 0)), node.name)
            self.assertEqual([tuple(e) for e in md.sharp_edges.tolist()], sorted(sharp), node.name)  # sorted, no repeats
        # without a hardened rim the key's seam entry holds the Mirrors right above the Shell
        turbo = next(n for n in desc.nodes if n.name == "FixtureShellUnderSymTurbo")
        mirror = turbo.converted[0]
        self.assertIn(("seam", (), ((mirror.settings, mirror.mirror),)), turbo.mesh)
        self.assertEqual(desc.meshes[turbo.mesh].lowered, 1)
        shell = next(n for n in desc.nodes if n.name == "FixtureShellOverride").converted[0]
        self.assertEqual(shell.rim, rules.RimRule(False, 45.0, 4))

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
        cases = ((classids.MESHSMOOTH, {9: rules.CLASSIC}), (classids.MESHSMOOTH, {9: rules.QUAD_OUTPUT}),
                 (classids.MESHSMOOTH, {9: 5}),
                 (classids.MESHSMOOTH, {2: 0.5}), (classids.MESHSMOOTH, {6: 1}), (classids.TURBOSMOOTH, {5: 1}),
                 (classids.SHELL, {12: 3}), (classids.SHELL, {19: 1}), (classids.SHELL, {2: 1}),
                 (classids.SHELL, {8: 1}), (classids.SHELL, {17: 1}))
        for cid, values in cases:
            _md, issues = _convert(cid, values)
            self.assertEqual(len(issues), 1, repr(values))
        # with auto smooth on (the default) 3ds Max ignores the override; with it off the override depends on the
        # mesh: convert.scene names it (test_rim_rule)
        for cid, values in ((classids.MESHSMOOTH, {9: rules.NURMS}), (classids.SHELL, {4: 1}),
                            (classids.SHELL, {4: 1, 14: 1}), (classids.SHELL, {14: 0}),
                            (classids.SHELL, {4: 1, 14: 0})):
            _md, issues = _convert(cid, values)
            self.assertEqual(issues, [], repr(values))

    def test_rim_rule(self):
        for values, want in (({}, (True, 45.0, None)), ({14: 0}, (False, 45.0, None)), ({15: 30.0}, (True, 30.0, None)),
                             ({4: 1, 5: 4}, (True, 45.0, None)), ({4: 1, 5: 4, 14: 0}, (False, 45.0, 4)),
                             ({5: 4, 14: 0}, (False, 45.0, None))):
            md, _issues = _convert(classids.SHELL, values)
            self.assertEqual(md.rim, rules.RimRule(*want), repr(values))
        md, _issues = _convert(classids.TURBOSMOOTH, {})
        self.assertIsNone(md.rim)
        # an animated auto smooth refuses nothing: the Shell converts, its rim unreported (an issue)
        md, issues = _convert(classids.SHELL, {14: pblock.Animated(3)})
        self.assertEqual((md.kind, md.rim, len(issues)), (SOLIDIFY, None, 1))

    def test_shell_surfaces(self):
        # (inner, outer) -> thickness (0.5 m per unit, _convert), offset, flip. Both surfaces outside (-1, 2) or inside
        # (3, -1): an offset past -1 .. 1, which Solidify takes as it is (no hard range; 3ds Max's boxes and
        # volumes, the stack_shell fixture). Inner + outer < 0 turns 3ds Max's shell inside out: Solidify flips.
        for (inner, outer), want in (((1.0, 2.0), (1.5, 1.0 / 3.0, False)), ((0.0, 1.0), (0.5, 1.0, False)),
                                     ((1.0, 0.0), (0.5, -1.0, False)), ((1.0, 1.0), (1.0, 0.0, False)),
                                     ((-1.0, 2.0), (0.5, 3.0, False)), ((3.0, -1.0), (1.0, -2.0, False)),
                                     ((-2.0, 1.0), (0.5, 3.0, True)),
                                     ((1.0, -2.0), (0.5, -3.0, True)), ((-1.0, -2.0), (1.5, -1.0 / 3.0, True))):
            md, issues = _convert(classids.SHELL, {0: inner, 1: outer})
            s = dict(md.settings)
            self.assertAlmostEqual(s["thickness"], want[0], msg=repr((inner, outer)))
            self.assertAlmostEqual(s["offset"], want[1], msg=repr((inner, outer)))
            self.assertIs(s["use_flip_normals"], want[2], repr((inner, outer)))
            self.assertEqual(issues, [], repr((inner, outer)))

    @unittest.skipIf(numpy is None, "numpy missing")  # a Symmetry's frame
    def test_refused(self):
        cases = ((classids.TURBOSMOOTH, None), (classids.TURBOSMOOTH, {0: pblock.Animated(3)}),
                 (classids.TURBOSMOOTH, {0: "two"}), (classids.TURBOSMOOTH, {0: float("nan")}),
                 (classids.TURBOSMOOTH, {0: True}), (classids.SHELL, {0: 0.0, 1: 0.0}),
                 (classids.SHELL, {0: -1.0, 1: 1.0}), (classids.SHELL, {0: 2.0, 1: -2.0}),
                 (classids.SHELL, {1: float("inf")}), (classids.SYMMETRY, {0: 3}), (classids.SYMMETRY, {3: (1, 2)}))
        for cid, values in cases:
            with self.assertRaises(rules.ModifierError, msg=repr(values)):
                _convert(cid, values)
        with self.assertRaises(rules.ModifierError):
            _convert(classids.SYMMETRY, {}, context=None)

    @unittest.skipIf(numpy is None, "numpy missing")  # a Symmetry's frame
    def test_symmetry_without_a_gizmo_mirrors_in_the_object_axes(self):
        md, issues = _convert(classids.SYMMETRY, {0: 1, 4: 1, 2: 0})
        s = dict(md.settings)
        self.assertEqual((md.mirror, s["use_axis"], s["use_bisect_axis"], s["use_bisect_flip_axis"],
                          s["use_mirror_merge"], len(issues)), (None, Y, Y, Y, False, 1))
        self.assertAlmostEqual(s["merge_threshold"], 0.05)

    def test_offset_scale_scales_shell_and_threshold(self):
        scaled = ((2.0, 0.0, 0.0, 0.0), (0.0, 2.0, 0.0, 0.0), (0.0, 0.0, 2.0, 0.0), (1.0, 2.0, 3.0, 1.0))
        md, issues = rules.convert(FakeScene(), _modifier(classids.SHELL, {0: 1.0, 1: 2.0}), 0.5, scaled)
        self.assertEqual((dict(md.settings)["thickness"], issues), (3.0, []))
        uneven = ((2.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 3.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        md, issues = rules.convert(FakeScene(), _modifier(classids.SHELL, {0: 0.0, 1: 1.0}), 1.0, uneven)
        self.assertEqual((dict(md.settings)["thickness"], len(issues)), (2.0, 1))

    @unittest.skipIf(numpy is None, "numpy missing")  # a Symmetry's frame
    def test_offset_scale_scales_the_weld_threshold(self):
        scaled = ((2.0, 0.0, 0.0, 0.0), (0.0, 2.0, 0.0, 0.0), (0.0, 0.0, 2.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        md, _issues = rules.convert(FakeScene(), _modifier(classids.SYMMETRY, {3: 0.25}), 0.5, scaled)
        self.assertAlmostEqual(dict(md.settings)["merge_threshold"], 0.25)
        self.assertIsNotNone(md.mirror)  # the offset's scale is part of the frame too

    def test_budget_lowers_viewport_levels_only(self):
        smooth, _i = _convert(classids.TURBOSMOOTH, {0: 10, 1: 1, 2: 10})
        shell, _i = _convert(classids.SHELL, {})
        out, issues = rules.budget((smooth,), 24)  # a box: 24 corners; 24 * 4 ** 8 <= 4e6 < 24 * 4 ** 9
        self.assertEqual((dict(out[0].settings)["levels"], dict(out[0].settings)["render_levels"], len(issues)),
                         (8, 10, 1))
        out, issues = rules.budget((shell, smooth), 24)  # tripled first: 72 * 4 ** 7 <= 4e6 < 72 * 4 ** 8
        self.assertEqual((dict(out[1].settings)["levels"], len(issues)), (7, 1))
        out, issues = rules.budget((smooth, smooth), 24)  # the second gets what the first left: none
        self.assertEqual(([dict(m.settings)["levels"] for m in out], len(issues)), ([8, 0], 2))
        stack = (smooth, shell, smooth)  # one out per modifier in, in order: build.emitters pairs them by position
        out, _issues = rules.budget(stack, 24)
        self.assertEqual([(m.index, m.kind) for m in out], [(m.index, m.kind) for m in stack])
        small, _i = _convert(classids.TURBOSMOOTH, {0: 2})
        self.assertEqual(rules.budget((small,), 24), ((small,), []))
        self.assertEqual(rules.budget((), 10 ** 9), ((), []))

    def test_the_lowest_smoother_that_changes_the_shading_decides(self):
        plain, _i = _convert(classids.TURBOSMOOTH, {4: 0})
        crease, _i = _convert(classids.TURBOSMOOTH, {6: 1})
        smooth, _i = _convert(classids.TURBOSMOOTH, {})
        self.assertEqual(conv._shading((plain, crease, smooth)), rules.CREASE)
        self.assertEqual(conv._shading((smooth, crease)), rules.SMOOTH)
        self.assertIsNone(conv._shading((plain,)))

    @unittest.skipIf(numpy is None, "numpy missing")  # a Symmetry's frame
    def test_mirror_frame(self):
        e = rules.mirror_frame(_translate(5, 0, 0), _translate(2, 0, 0), _translate(1, 0, 0))
        self.assertEqual(e[3][:3], (4.0, 0.0, 0.0))
        self.assertEqual(rules.mirror_frame(IDENTITY, IDENTITY, None), IDENTITY)
        zero = ((0.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        for gizmo, context in ((zero, IDENTITY), (IDENTITY, zero)):
            with self.assertRaises(rules.ModifierError):
                rules.mirror_frame(gizmo, context, None)


def _md(kind, shading=None, index=0):
    return rules.ModifierDescription(index, kind, kind, kind, True, (), None, shading,
                                     rules.RimRule(True, 45.0, None) if kind == SOLIDIFY else None)


def _mirror_md(axis=0, merge=True, threshold=0.1, frame=None, slice_=True, index=3):
    on = tuple(k == axis for k in range(3))
    settings = (("use_axis", on), ("use_bisect_axis", on if slice_ else (False,) * 3),
                ("use_bisect_flip_axis", (False,) * 3),
                ("use_mirror_merge", merge), ("merge_threshold", threshold))
    return rules.ModifierDescription(index, MIRROR, "Symmetry", "Symmetry", True, settings, frame, None)


# a unit quad (the plane), a cube without its top (counter-clockwise from outside), a closed cube
QUAD = ([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [0, 1, 2, 3], [0], [4])
_CUBE = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
_SIDES = [[0, 3, 2, 1], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]


def _faces(positions, faces):
    lv = [v for f in faces for v in f]
    return (positions, lv, [4 * k for k in range(len(faces))], [4] * len(faces))


def _grid(nx, ny, skip=()):
    """A flat grid of nx x ny unit quads, counter-clockwise from above, without the cells in skip."""
    positions = [(x, y, 0) for y in range(ny + 1) for x in range(nx + 1)]
    faces = [[y * (nx + 1) + x, y * (nx + 1) + x + 1, (y + 1) * (nx + 1) + x + 1, (y + 1) * (nx + 1) + x]
             for y in range(ny) for x in range(nx) if (x, y) not in skip]
    return _faces(positions, faces)


OPEN_CUBE = _faces(_CUBE, _SIDES)
CUBE = _faces(_CUBE, _SIDES + [[4, 5, 6, 7]])
# the cube without its side on the plane x = 0, as if cut there: open (its top too) and closed (with the top)
HALF_OPEN_BOX = _faces(_CUBE, [f for f in _SIDES if f != [3, 0, 4, 7]])
HALF_BOX = _faces(_CUBE, [f for f in _SIDES if f != [3, 0, 4, 7]] + [[4, 5, 6, 7]])
# the open cube without its sides on x = 0 and y = 0: a quarter
QUARTER_OPEN_BOX = _faces(_CUBE, [f for f in _SIDES if f not in ([3, 0, 4, 7], [0, 1, 5, 4])])


def _at_x(x):
    """A mirror frame (Blender's columns) moved x along X: the plane x = x."""
    return ((1.0, 0.0, 0.0, x), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))


def _description(mesh):
    positions, lv, starts, totals = mesh
    n = len(starts)
    return conv.MeshDescription("k", "m", numpy.asarray(positions, dtype=numpy.float32),
                                numpy.asarray(lv, dtype=numpy.int32), numpy.asarray(starts, dtype=numpy.int32),
                                numpy.asarray(totals, dtype=numpy.int32), numpy.zeros(n, dtype=numpy.int32),
                                numpy.zeros(n, dtype=bool), numpy.zeros((0, 2), dtype=numpy.int32), [])


@unittest.skipIf(numpy is None, "numpy missing")
class Rim(unittest.TestCase):
    def test_open_edges(self):
        self.assertEqual(conv.open_edges(*QUAD[1:]).tolist(), [[0, 1], [0, 3], [1, 2], [2, 3]])
        self.assertEqual(conv.open_edges(*OPEN_CUBE[1:]).tolist(), [[4, 5], [4, 7], [5, 6], [6, 7]])
        self.assertEqual(conv.open_edges(*CUBE[1:]).shape, (0, 2))
        self.assertEqual(conv.open_edges([], [], []).shape, (0, 2))
        # two quads sharing the edge 1-2: the other six
        self.assertEqual(len(conv.open_edges([0, 1, 2, 3, 1, 4, 5, 2], [0, 4], [4, 4])), 6)

    def test_merged_edges_sorted_without_repeats(self):
        got = conv._merged_edges(numpy.array([[0, 1], [2, 3]]), numpy.array([[0, 3], [2, 3], [1, 5]]))
        self.assertEqual(got.tolist(), [[0, 1], [0, 3], [1, 5], [2, 3]])
        self.assertEqual(got.dtype, numpy.int32)
        self.assertEqual(conv._merged_edges(numpy.zeros((0, 2)), numpy.zeros((0, 2))).shape, (0, 2))

    def test_rim_corners(self):
        # the plane's rim turns 90 degrees at each corner; the open cube's lies flat (no corner)
        self.assertEqual(conv.rim_corners(*QUAD, 45.0), 4)
        self.assertEqual(conv.rim_corners(*QUAD, 100.0), 0)
        self.assertEqual(conv.rim_corners(*OPEN_CUBE, 45.0), 0)
        self.assertEqual(conv.rim_corners(*CUBE, 45.0), 0)
        reversed_quad = (QUAD[0], [0, 3, 2, 1], [0], [4])  # the other winding: the same corners
        self.assertEqual(conv.rim_corners(*reversed_quad, 45.0), 4)
        # a 3 x 3 grid of quads: its 4 corners; without its middle quad (a hole) 4 more; an L of three quads: 6
        grid = _grid(3, 3)
        self.assertEqual(conv.rim_corners(*grid, 45.0), 4)
        self.assertEqual(conv.rim_corners(*_grid(3, 3, skip={(1, 1)}), 45.0), 8)
        self.assertEqual(conv.rim_corners(*_grid(2, 2, skip={(1, 1)}), 45.0), 6)
        calls = []
        self.assertEqual(conv.rim_corners(*grid, 45.0, check=lambda: calls.append(1)), 4)
        self.assertTrue(calls)
        self.assertEqual(len(conv.open_edges(*grid[1:])), 12)

    def test_which_shell_makes_the_rim(self):
        shell, smooth, crease = _md(SOLIDIFY, index=1), _md(SUBSURF, rules.SMOOTH), _md(SUBSURF, rules.CREASE)
        plain, mirror = _md(SUBSURF), _md(MIRROR)
        for run, want in (((shell,), shell), ((smooth, shell), shell), ((shell, smooth), None),
                          ((crease, shell), shell), ((shell, crease), shell), ((shell, plain), shell),
                          ((mirror, shell), shell), ((shell, mirror), shell), ((shell, smooth, _md(SOLIDIFY)), None),
                          ((smooth,), None), ((), None)):
            self.assertIs(conv._rim(run), want, repr([m.kind for m in run]))

    def test_mirrors_below_the_shell(self):
        shell, other = _md(SOLIDIFY, index=1), _md(SOLIDIFY, index=2)
        low, high = _mirror_md(), _mirror_md(axis=1)
        self.assertEqual(conv._mirrors((low, _md(SUBSURF), high, shell, _mirror_md(axis=2)), shell), (low, high))
        self.assertEqual(conv._mirrors((shell, low), shell), ())
        self.assertEqual(conv._mirrors((low, shell, other), other), (low,))  # the weld off counts too (no weld)

    def test_welded_as_blenders_mirror(self):
        # Blender welds a vertex whose copy is closer than the threshold: 0.049 off the plane at 0.1, not 0.051
        # (measured on 4.2.23 and 5.2)
        p = [(0.049, 0, 0), (0.051, 0, 0), (-0.049, 3, 2), (0.0, 0, 0), (5.0, 0, 0)]
        self.assertEqual(conv.welded(p, _mirror_md()).tolist(), [True, False, True, True, False])
        self.assertEqual(conv.welded(p, _mirror_md(merge=False)).tolist(), [False] * 5)
        self.assertEqual(conv.welded(p, _mirror_md(axis=1)).tolist(), [True, True, False, True, True])
        # a mirror object 5 along X, turned 90 degrees about Z: its X axis is the object's Y, the plane y = 0 ...
        turned = ((0.0, -1.0, 0.0, 5.0), (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        self.assertEqual(conv.welded(p, _mirror_md(frame=turned)).tolist(), [True, True, False, True, True])
        # ... and moved: the plane x = 5
        moved = ((1.0, 0.0, 0.0, 5.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        self.assertEqual(conv.welded(p, _mirror_md(frame=moved)).tolist(), [False, False, False, False, True])
        # turned 45 degrees and off the plane: welds 0.04 from the plane along its X axis, not 0.06, and a point of
        # the plane far along its Y axis (a transposed matrix would put that point 5 off its plane)
        c = math.sqrt(0.5)
        frame = ((c, -c, 0.0, 3.0), (c, c, 0.0, 1.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        q = [(3 + 0.04 * c, 1 + 0.04 * c, 0), (3 + 0.06 * c, 1 + 0.06 * c, 0), (3 - 5 * c, 1 + 5 * c, 2)]
        self.assertEqual(conv.welded(q, _mirror_md(frame=frame)).tolist(), [True, False, True])
        # a negative threshold (a crafted file) welds nothing, as Blender's minimum of 0
        self.assertEqual(conv.welded(p, _mirror_md(threshold=-0.1)).tolist(), [False] * 5)

    def test_rim_edges_above_a_mirror(self):
        half, closed = _description(HALF_OPEN_BOX), _description(HALF_BOX)
        top = {(4, 5), (5, 6), (6, 7)}  # the open box's top but the edge on the plane x = 0 (4-7)
        self.assertEqual({tuple(e) for e in conv._rim_edges(half, (_mirror_md(),)).tolist()}, top)
        self.assertEqual(len(conv._rim_edges(half, ())), 6)
        self.assertEqual(len(conv._rim_edges(half, (_mirror_md(merge=False),))), 6)  # no weld: every open edge
        # the plane y = 0: the front's 0-4 and 4-5 weld
        self.assertEqual(len(conv._rim_edges(half, (_mirror_md(axis=1),))), 4)
        self.assertEqual(len(conv._rim_edges(closed, (_mirror_md(),))), 0)  # all on the plane
        # a strip from x = 0 to 5, mirrored at x = 5, then at x = 10: the second Mirror welds the first one's copy of
        # the edge at x = 0, which would carry its sharp mark into the seam
        strip = _description(([(0, 0, 0), (5, 0, 0), (5, 1, 0), (0, 1, 0)], [0, 1, 2, 3], [0], [4]))
        at = [((1.0, 0.0, 0.0, x), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)) for x in (5, 10)]
        got = conv._rim_edges(strip, tuple(_mirror_md(frame=f) for f in at))
        self.assertEqual(got.tolist(), [[0, 1], [2, 3]])

    def test_mirrored_mesh(self):
        p, lv, starts, totals = conv._mirrored(_description(HALF_OPEN_BOX), (_mirror_md(),))
        # the copy shares the four vertices on the plane; its faces reversed: no edge on the plane is open
        self.assertEqual((len(p), len(lv), len(starts)), (16, 32, 8))
        self.assertEqual(len(conv.open_edges(lv, starts, totals)), 6)  # the whole open box's top, split at x = 0
        p, lv, starts, totals = conv._mirrored(_description(HALF_OPEN_BOX), (_mirror_md(merge=False),))
        self.assertEqual(len(conv.open_edges(lv, starts, totals)), 12)  # two halves, each open

    def test_seam_run(self):
        shell, smooth = _md(SOLIDIFY, index=1), _md(SUBSURF, rules.SMOOTH)
        low, a, b = _mirror_md(index=4), _mirror_md(axis=1, index=5), _mirror_md(axis=2, index=6)
        self.assertEqual(conv._seam((shell, a, b, smooth)), (shell, (a, b)))
        self.assertEqual(conv._seam((low, shell, a, smooth, b)), (shell, (a,)))
        self.assertEqual(conv._seam((shell, smooth, a)), (shell, ()))
        self.assertEqual(conv._seam((smooth, shell, a)), (None, ()))  # a smoother below the Shell: not measured
        self.assertEqual(conv._seam((a, b)), (None, ()))
        self.assertEqual(conv._seam(()), (None, ()))
        run = (low, shell, a, b, smooth)
        self.assertEqual(conv._lowered(run, shell, (a,)), (low, a, shell, b, smooth))
        self.assertEqual(conv._lowered(run, shell, (a, b)), (low, a, b, shell, smooth))
        self.assertIs(conv._lowered(run, shell, ()), run)

    def test_lowered_where_the_rim_lies_on_the_plane(self):
        half, closed = _description(HALF_OPEN_BOX), _description(HALF_BOX)
        sym = _mirror_md()
        # the cut's open edges on x = 0, every face at them square to it: 3ds Max's slice drops the rim there
        self.assertEqual(conv.lowered(half, (), (sym,), 1.0), (1, None))
        self.assertEqual(conv.lowered(closed, (), (sym,), 1.0), (1, None))
        self.assertEqual(conv.lowered(half, (), (), 1.0), (0, None))
        # the plane 1e-5 off the cut: still on it (3ds Max: within 1e-4 units dropped, 1e-3 kept); 1e-3 off: not,
        # no line (no open edge on the plane); the tolerance scales with the unit (meters per system unit)
        self.assertEqual(conv.lowered(half, (), (_mirror_md(frame=_at_x(1e-5)),), 1.0), (1, None))
        self.assertEqual(conv.lowered(half, (), (_mirror_md(frame=_at_x(1e-3)),), 1.0), (0, None))
        self.assertEqual(conv.lowered(half, (), (_mirror_md(frame=_at_x(1e-3)),), 10.0), (1, None))
        # in files of large units the test stays within Blender's bisect distance (1 mm)
        self.assertEqual(conv.lowered(half, (), (_mirror_md(frame=_at_x(2e-3)),), 100.0), (0, None))
        self.assertEqual(conv.lowered(half, (), (_mirror_md(frame=_at_x(4e-4)),), 100.0), (1, None))
        self.assertEqual(conv.lowered(half, (), (_mirror_md(frame=_at_x(5.0)),), 1.0), (0, None))
        # weld off, slice off: on the plane, not converted (a line)
        self.assertEqual(conv.lowered(half, (), (_mirror_md(merge=False),), 1.0), (0, conv.SEAM_STAYS))
        self.assertEqual(conv.lowered(half, (), (_mirror_md(slice_=False),), 1.0), (0, conv.SEAM_STAYS))
        self.assertEqual(conv.lowered(half, (), (_mirror_md(threshold=0.0),), 1.0), (0, conv.SEAM_STAYS))
        # the cut's bottom lowered: its faces slant across the plane, the rim leaves it (a line)
        slant = ([(x, y, z - 0.5 if x == 0 and z == 0 else z) for x, y, z in _CUBE],) + HALF_OPEN_BOX[1:]
        self.assertEqual(conv.lowered(_description(slant), (), (sym,), 1.0), (0, conv.SEAM_STAYS))
        # a quarter: Symmetry X then Y above the Shell, or X below it and Y above
        quarter, y = _description(QUARTER_OPEN_BOX), _mirror_md(axis=1)
        self.assertEqual(conv.lowered(quarter, (), (sym, y), 1.0), (2, None))
        self.assertEqual(conv.lowered(quarter, (sym,), (y,), 1.0), (1, None))
        self.assertEqual(conv.lowered(quarter, (), (sym, _mirror_md(axis=1, merge=False)), 1.0), (1, conv.SEAM_STAYS))
        self.assertEqual(conv.lowered(quarter, (), (sym, _mirror_md(frame=_at_x(5.0))), 1.0), (1, None))
        calls = []
        self.assertEqual(conv.lowered(quarter, (), (sym, y), 1.0, check=lambda: calls.append(1)), (2, None))
        self.assertGreaterEqual(len(calls), 2)
        # past MAX_MIRRORED_CORNERS with the copies: not tested, a line
        cap = conv.MAX_MIRRORED_CORNERS
        conv.MAX_MIRRORED_CORNERS = 16
        try:
            self.assertEqual(conv.lowered(quarter, (), (sym, y), 1.0), (1, conv.SEAM_UNTESTED))
            self.assertEqual(conv.lowered(quarter, (sym,), (y,), 1.0), (0, conv.SEAM_UNTESTED))
        finally:
            conv.MAX_MIRRORED_CORNERS = cap

    def test_face_normals(self):
        # a triangle, a non-planar quad (its area vector), a face of no area
        p = numpy.array([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 1), (2, 0, 0)], dtype=numpy.float64)
        lv = numpy.array([0, 1, 2, 0, 1, 3, 2, 0, 1, 4])
        starts, totals = numpy.array([0, 3, 7]), numpy.array([3, 4, 3])
        n = conv._face_normals(p, lv, starts, totals, numpy.array([True, True, True]))
        self.assertTrue(numpy.allclose(n[0], (0, 0, 1)))
        self.assertTrue(numpy.allclose(n[1], numpy.array((-1, -1, 2)) / math.sqrt(6)))
        self.assertTrue(numpy.allclose(n[2], (0, 0, 0)))
        only = conv._face_normals(p, lv, starts, totals, numpy.array([False, True, False]))
        self.assertTrue(numpy.allclose(only, n[1:2]))

    def test_opposite_orders_on_one_base_keep_their_own_decision(self):
        # instances of one half box, one with Symmetry (weld off) then Shell, the other with Shell then Symmetry:
        # their meshes are keyed apart, each with its own decision (one key crashed the second node)
        pos, lv, starts, totals = HALF_OPEN_BOX
        data = geometry.MeshData(numpy.asarray(pos, dtype=numpy.float32), numpy.asarray(lv, dtype=numpy.int32),
                                 numpy.asarray(starts, dtype=numpy.int32), numpy.ones(len(starts), dtype=numpy.uint32),
                                 numpy.zeros(len(starts), dtype=numpy.int32), {})
        sym, shell = _mirror_md(merge=False), _md(SOLIDIFY, index=1)
        for first in (0, 1):
            desc = types.SimpleNamespace(meshes={}, issues=[])
            orders = ((shell, sym), (sym, shell))
            got = {}
            for order in orders[first:] + orders[:first]:
                rim, (seam, above) = conv._rim(order), conv._seam(order)
                mirrors = conv._mirrors(order, seam if rim is None else rim)
                key, _done = conv._mapped_mesh(None, desc, {}, (7, None), data, (), 0, "n", None, 1.0, None, None,
                                               True, mirrors, None, above=above)
                md = desc.meshes[key]
                conv._name_seam(desc, set(), above, key, 0)
                got[order] = (md.lowered, md.seam_issue, len(conv._rim_mirrors(md, mirrors, above, 1.0)))
            self.assertEqual(len(desc.meshes), 2)
            self.assertEqual(got, {(shell, sym): (0, conv.SEAM_STAYS, 1), (sym, shell): (0, None, 1)})
            self.assertEqual([x for _n, x in desc.issues], ["modifiers: Symmetry: " + conv.SEAM_STAYS])

    def test_rim_mirrors(self):
        half, sym, y = _description(HALF_OPEN_BOX), _mirror_md(), _mirror_md(axis=1)
        half.lowered, half.seam_issue = 1, None
        self.assertEqual(conv._rim_mirrors(half, (y,), (sym,), 1.0), (y, sym))
        # a Mirror that stays above: counted welding what lies on its plane, where 3ds Max's slice drops the rim
        half.lowered, half.seam_issue = 0, conv.SEAM_STAYS
        off = _mirror_md(merge=False)
        got = conv._rim_mirrors(half, (), (off,), 2.0)
        self.assertEqual(len(got), 1)
        settings = dict(got[0].settings)
        self.assertTrue(settings["use_mirror_merge"])
        self.assertAlmostEqual(settings["merge_threshold"], 4e-4)
        self.assertEqual(settings["use_axis"], dict(off.settings)["use_axis"])
        auto = rules.RimRule(True, 45.0, None)
        self.assertEqual(conv.rim_issues(half, auto, mirrors=conv._rim_mirrors(half, (), (off,), 1.0)), [])
        # without the slice 3ds Max keeps the rim on the plane, corners and all: counted on the mesh as it is
        self.assertEqual(conv._rim_mirrors(half, (), (_mirror_md(slice_=False),), 1.0), ())
        self.assertEqual(len(conv.rim_issues(half, auto, mirrors=())), 1)

    def test_rim_issues(self):
        plane, box, cube = _description(QUAD), _description(OPEN_CUBE), _description(CUBE)
        auto, off, over = rules.RimRule(True, 45.0, None), rules.RimRule(False, 45.0, None), rules.RimRule(False, 45.0, 4)
        self.assertEqual(conv.rim_issues(plane, auto), [
            "auto smooth: 4 corners of the rim sharper than 45 degrees shade smooth (3ds Max splits the rim there)"])
        self.assertEqual(conv.rim_issues(plane, rules.RimRule(True, 95.0, None)), [])
        self.assertEqual(conv.rim_issues(box, auto), [])
        self.assertEqual(conv.rim_issues(plane, off), [])
        want = ["smoothing group override (group 4) not converted: 3ds Max merges the rim into the faces along it of "
                "that group"]
        self.assertEqual(conv.rim_issues(box, over), want)
        self.assertEqual(conv.rim_issues(cube, over), [])  # no open edge: no rim
        self.assertEqual(conv.rim_issues(cube, auto), [])
        self.assertEqual(conv.rim_issues(plane, None), [])
        # the half box's top meets the cut at two corners of 90 degrees; welded to its copy, the rim lies flat
        half = _description(HALF_OPEN_BOX)
        self.assertEqual(conv.rim_issues(half, auto), [
            "auto smooth: 2 corners of the rim sharper than 45 degrees shade smooth (3ds Max splits the rim there)"])
        self.assertEqual(conv.rim_issues(half, auto, mirrors=(_mirror_md(),)), [])
        self.assertEqual(conv.rim_issues(half, auto, mirrors=(_mirror_md(merge=False),)), [
            "auto smooth: 4 corners of the rim sharper than 45 degrees shade smooth (3ds Max splits the rim there)"])
        self.assertEqual(conv.rim_issues(_description(HALF_BOX), over, mirrors=(_mirror_md(),)), [])  # welded shut
        self.assertEqual(len(conv.rim_issues(_description(HALF_BOX), over)), 1)
        self.assertEqual(conv.rim_issues(half, over, mirrors=(_mirror_md(),)), want)  # the top's rim stays
        # the mesh with its copies past MAX_MIRRORED_CORNERS: not counted, a line instead
        cap = conv.MAX_MIRRORED_CORNERS
        conv.MAX_MIRRORED_CORNERS = 8
        try:
            got = conv.rim_issues(half, auto, mirrors=(_mirror_md(), _mirror_md(axis=1)))
        finally:
            conv.MAX_MIRRORED_CORNERS = cap
        self.assertEqual(got, ["auto smooth: the rim's corners not counted: with its copies under 2 Symmetries the "
                               "mesh would pass 8 face corners"])
        # forty Symmetries at distinct planes: the copies tested stop doubling (MAX_MIRROR_IMAGES), quickly
        many = tuple(_mirror_md(frame=((1.0, 0.0, 0.0, 7.0 + k), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0),
                                       (0.0, 0.0, 0.0, 1.0))) for k in range(40))
        start = time.perf_counter()
        got = conv._rim_edges(plane, many)  # copies of the quad's sides land on later planes: some weld
        calls = []
        self.assertEqual(conv._rim_edges(plane, many, check=lambda: calls.append(1)).tolist(), got.tolist())
        self.assertGreaterEqual(len(calls), 40)
        self.assertLess(time.perf_counter() - start, 5.0)


if __name__ == "__main__":
    unittest.main()
