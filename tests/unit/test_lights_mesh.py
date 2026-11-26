# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/lights/ for emitters: the rules of a self-illuminated material's light and the
mesh lights of vray_mesh_light, no Blender.

    python -I -m unittest discover tests
"""
import importlib
import importlib.util
import math
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
    _PKG, colors, conv, EXTRUDE_FIXTURE, L, MESH_FIXTURE, MM, patching, values,
)


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

    def test_spread(self):
        """The radiance over another area (the evaluated mesh's) as describe_emitter gives it for that area: in lm and
        W; the radiance units and the default keep theirs (the area is still recorded). The strength issues that change
        with the area: gone and added; those that stay (a negative multiplier) neither."""
        for units in (L.UNITS_W, L.UNITS_LM, L.UNITS_DEFAULT, L.UNITS_W_M2_SR, L.UNITS_LM_M2_SR):
            for double in (False, True):
                v = values(type=L.MESH, units=units, multiplier=3.0, double_sided=int(double))
                ed, _issues = L.describe_emitter(1, "e", v, colors.GAMMA_ON, self.A)
                want, _issues = L.describe_emitter(1, "e", v, colors.GAMMA_ON, 2.1 * self.A)
                before = ed.radiance
                self.assertEqual(L.spread(ed, 2.1 * self.A), ([], []), units)
                self.assertAlmostEqual(ed.radiance, want.radiance, delta=want.radiance * 1e-12, msg=units)
                self.assertEqual(ed.area, 2.1 * self.A)
                if units in (L.UNITS_W, L.UNITS_LM):
                    self.assertAlmostEqual(ed.radiance, before / 2.1, delta=before * 1e-12)
                else:
                    self.assertEqual(ed.radiance, before)
        ed, _issues = L.describe_emitter(1, "e", values(type=L.MESH, units=L.UNITS_W, multiplier=1.0), colors.GAMMA_ON,
                                         self.A)
        self.assertEqual((L.spread(ed, 0.0), ed.radiance), (([], [L.EMITTER_FLAT % "watts"]), 0.0))
        self.assertEqual(L.spread(ed, self.A), ([L.EMITTER_FLAT % "watts"], []))  # a flat mesh under a Shell
        self.assertAlmostEqual(ed.radiance, 1.0 / (math.pi * self.A), delta=1e-9)
        ed, issues = L.describe_emitter(1, "e", values(type=L.MESH, units=L.UNITS_W, multiplier=-1.0),
                                        colors.GAMMA_ON, self.A)
        self.assertEqual((issues, L.spread(ed, 2.0 * self.A), ed.radiance),
                         ([L.NEGATIVE % ("multiplier", -1.0)], ([], []), 0.0))


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
        """Replace mesh with light: reference 1 holds the plane (30 x 10) under a Shell (inner 2): the plane, the
        Shell a Solidify of 2 mm on the light node (build spreads lm 100 over the shelled area; here the plane's);
        affect specular and reflections off: no glossy rays; no line."""
        node, ed, md = self.emitter("FixtureEmitterOwn")
        self.assertAlmostEqual(ed.area, 0.0003, delta=1e-9)
        self.assertAlmostEqual(ed.radiance, 100.0 / 683.0 / (math.pi * 0.0003), delta=1e-4)
        self.assertEqual((ed.units, ed.multiplier), (L.UNITS_LM, 100.0))
        self.assertFalse(ed.glossy_rays)
        self.assertNotIn(node.index, self.issues)
        self.assertEqual(len(md.loop_starts), 1)
        self.assertEqual([(m.kind, m.class_name) for m in node.converted], [(conv.rules.SOLIDIFY, "Shell")])
        settings = dict(node.converted[0].settings)
        self.assertAlmostEqual(settings["thickness"], 0.002, delta=1e-12)
        self.assertEqual((settings["offset"], settings["use_rim"]), (-1.0, True))
        self.assertEqual((node.modifiers, node.applied), ((), ()))  # the light's own stack: none
        for name in ("FixtureEmitter", "FixtureEmitterW"):  # a picked Plane without modifiers
            self.assertEqual(self.by_name[name].converted, (), name)

    def test_own_mesh_creased_by_its_smoother(self):
        """A converted smoother that separates by smoothing groups (CREASE) creases the emitter's mesh, as a mesh
        node's (md.creases): only FixtureEmitterOwn's, whose node has converted modifiers."""
        with patching.patch_all(conv, "_shading", lambda converted: conv.rules.CREASE if converted else None):
            desc = conv.read(MESH_FIXTURE)
        creased = sorted(n.name for n in desc.nodes if n.emitter is not None and desc.meshes[n.mesh].creases)
        self.assertEqual(creased, ["FixtureEmitterOwn"])

    def test_a_refused_shell_is_named_once(self):
        """A Shell the rules refuse: _converted's line names it, the line of the modifiers left out does not."""
        def refuse(scene, modifier, meters=1.0, offset=None):
            raise conv.rules.ModifierError("refused here")
        with mock.patch.object(conv.rules, "convert", refuse):
            desc = conv.read(MESH_FIXTURE)
        node = next(n for n in desc.nodes if n.name == "FixtureEmitterOwn")
        self.assertEqual(node.converted, ())
        self.assertEqual([r for i, r in desc.issues if i == node.index], ["modifiers: Shell not converted: refused here"])

    def test_own_mesh_with_conversion_off(self):
        """Modifiers: Ignore: nothing converted, the Shell named in the line."""
        desc = conv.read(MESH_FIXTURE, convert_modifiers=False)
        node = next(n for n in desc.nodes if n.name == "FixtureEmitterOwn")
        self.assertEqual(node.converted, ())
        self.assertEqual([r for i, r in desc.issues if i == node.index], ["light: " + L.EMITTER_MODIFIERS % "Shell"])

    def test_an_extruded_shape_source(self):
        """A shape under an Extrude as the emitter's mesh (FixtureExtRect: a Rectangle 30 x 20 extruded 10, capped):
        the extruded mesh, its area 2 x 600 + 100 x 10 mm^2, nothing above it; without the reader's modifiers or
        past the scene's corner budget, not made."""
        cfb = importlib.import_module(_PKG + ".reader.cfb")
        reader_scene = importlib.import_module(_PKG + ".reader.scene")
        reader_modifiers = importlib.import_module(_PKG + ".reader.modifiers")
        with cfb.CompoundFile(EXTRUDE_FIXTURE) as cf:
            sc = reader_scene.Scene.from_file(cf)
            node = next(i for i in sc.walk() if sc.node(i).name == "FixtureExtRect")
            v = {L.MESH_OBJECT: sc.node(node).object, L.P_MESH_SOURCE: None}
            desc = conv.SceneDescription(MM)
            built = [0]
            found = conv._emitter_mesh(sc, desc, v, node, MM, built, None, reader_modifiers.Modifiers(sc))
            self.assertNotIsInstance(found, str, found)
            _base, data, area, rest, unread = found
            self.assertAlmostEqual(area, 2200.0 * MM * MM, delta=1e-12)
            self.assertEqual((rest, unread, built[0]), ((), (), len(data.loop_vertices)))
            self.assertEqual(conv._emitter_mesh(sc, desc, v, node, MM, [0]), L.EMITTER_CLASS % "Rectangle")
            spent = conv._emitter_mesh(sc, desc, v, node, MM, [conv.MAX_BUILT_CORNERS], None,
                                       reader_modifiers.Modifiers(sc))
            self.assertTrue(isinstance(spent, str) and "Extrude is not made" in spent, spent)
            ext = importlib.import_module(_PKG + ".convert.extrude")
            built = [0]
            with mock.patch.object(ext, "extrude", side_effect=ext.ExtrudeError("more than 1 vertices", 5)):
                refused = conv._emitter_mesh(sc, desc, v, node, MM, built, None, reader_modifiers.Modifiers(sc))
            self.assertEqual((refused, built[0]), (L.EMITTER_UNREAD % "more than 1 vertices", 5))  # charged

    def test_one_extrusion_for_a_shape_and_its_mesh_light(self):
        """FixtureExtRect's shape under its Extrude as a mesh node's mesh and as a mesh light's picked mesh, in either
        walk order: extruded once, its face corners counted once, its Extrude issues named once (on the node that
        made it); after the shape's last node (drop) the light gets it made again, naming and counting nothing."""
        cfb = importlib.import_module(_PKG + ".reader.cfb")
        reader_scene = importlib.import_module(_PKG + ".reader.scene")
        reader_modifiers = importlib.import_module(_PKG + ".reader.modifiers")
        real, calls = conv.extrude.extrude, []

        def counted(sh, params):
            calls.append(1)
            data, issues = real(sh, params)
            return data, issues + ["counted"]

        with cfb.CompoundFile(EXTRUDE_FIXTURE) as cf, mock.patch.object(conv.extrude, "extrude", counted):
            sc = reader_scene.Scene.from_file(cf)
            stacks = reader_modifiers.Modifiers(sc)
            node = next(i for i in sc.walk() if sc.node(i).name == "FixtureExtRect")
            obj = sc.node(node).object
            base = sc.object_stack(obj).base
            ext = [m for m in stacks.object_stack(obj).modifiers if m.renders][0]
            v = {L.MESH_OBJECT: None, L.P_MESH_SOURCE: node}
            for order in ("mesh, light", "light, mesh", "mesh, drop, light"):
                calls.clear()
                desc, built = conv.SceneDescription(MM), [0]
                ex = conv._Extrusions(sc, desc, {}, built)
                found = key = None
                for step in order.split(", "):
                    if step == "mesh":
                        key, _done = conv._extruded(sc, desc, ex, {}, base, ext, (), node, "FixtureExtRect", None, MM)
                    elif step == "drop":
                        ex.drop(base)
                    else:
                        found = conv._emitter_mesh(sc, desc, v, "light", MM, built, None, stacks, ex)
                self.assertNotIsInstance(found, str, (order, found))
                self.assertIsNotNone(key, order)
                corners = len(found[1].loop_vertices)
                first = "light" if order.startswith("light") else node
                self.assertEqual((len(calls), built[0]), (2 if "drop" in order else 1, corners), order)
                self.assertEqual([(i, r) for i, r in desc.issues if r == "extrude: counted"],
                                 [(first, "extrude: counted")], order)

    def test_a_refused_adaptive_extrude_charged_once_for_a_shape_and_its_mesh_light(self):
        """FixtureExtRect's Extrude refused after its points are made (ExtrudeError.spent): met by the shape's node and
        by a mesh light in either walk order, it is tried once and its spent corners charged to built once."""
        cfb = importlib.import_module(_PKG + ".reader.cfb")
        reader_scene = importlib.import_module(_PKG + ".reader.scene")
        reader_modifiers = importlib.import_module(_PKG + ".reader.modifiers")
        calls = []

        def refused(sh, params):
            calls.append(1)
            raise conv.extrude.ExtrudeError("more than 1 vertices", 5)

        with cfb.CompoundFile(EXTRUDE_FIXTURE) as cf, mock.patch.object(conv.extrude, "extrude", refused):
            sc = reader_scene.Scene.from_file(cf)
            stacks = reader_modifiers.Modifiers(sc)
            node = next(i for i in sc.walk() if sc.node(i).name == "FixtureExtRect")
            obj = sc.node(node).object
            base = sc.object_stack(obj).base
            ext = [m for m in stacks.object_stack(obj).modifiers if m.renders][0]
            v = {L.MESH_OBJECT: None, L.P_MESH_SOURCE: node}
            for order in ("mesh, light", "light, mesh"):
                calls.clear()
                desc, built = conv.SceneDescription(MM), [0]
                ex = conv._Extrusions(sc, desc, {}, built)
                for step in order.split(", "):
                    if step == "mesh":
                        key, _done = conv._extruded(sc, desc, ex, {}, base, ext, (), node, "FixtureExtRect", None, MM)
                        self.assertIsNone(key, order)
                    else:
                        found = conv._emitter_mesh(sc, desc, v, "light", MM, built, None, stacks, ex)
                        self.assertIsInstance(found, str, order)
                self.assertEqual((len(calls), built[0]), (1, 5), order)

    def test_a_refused_shape_or_extrude_named_on_the_shapes_node_in_either_order(self):
        """FixtureExtRect's shape refused by the reader, or its Extrude: in either walk order the shape's own node
        names it once ("shape: ..." through _curve as describe() falls back to it, or "extrude: ..."), the light gets
        it as its reason and no shape or extrude line of its own."""
        cfb = importlib.import_module(_PKG + ".reader.cfb")
        reader_scene = importlib.import_module(_PKG + ".reader.scene")
        reader_modifiers = importlib.import_module(_PKG + ".reader.modifiers")
        shapes = importlib.import_module(_PKG + ".reader.shapes")
        cases = (("shape", mock.patch.object(conv.shapes, "read_shape", side_effect=shapes.ShapeError("bad"))),
                 ("extrude", mock.patch.object(conv.extrude, "read_params",
                                               side_effect=conv.extrude.ExtrudeError("bad"))))
        with cfb.CompoundFile(EXTRUDE_FIXTURE) as cf:
            sc = reader_scene.Scene.from_file(cf)
            stacks = reader_modifiers.Modifiers(sc)
            node = next(i for i in sc.walk() if sc.node(i).name == "FixtureExtRect")
            obj = sc.node(node).object
            base = sc.object_stack(obj).base
            ext = [m for m in stacks.object_stack(obj).modifiers if m.renders][0]
            v = {L.MESH_OBJECT: None, L.P_MESH_SOURCE: node}
            for kind, patch in cases:
                for order in (("mesh", "light"), ("light", "mesh")):
                    desc, built, shape_of = conv.SceneDescription(MM), [0], {}
                    ex = conv._Extrusions(sc, desc, shape_of, built)
                    reason = None
                    with patch:
                        for step in order:
                            if step == "mesh":
                                key, _done = conv._extruded(sc, desc, ex, {}, base, ext, (), node, "FixtureExtRect",
                                                            None, MM)
                                self.assertIsNone(key)
                                conv._curve(sc, desc, shape_of, set(), base, node, "FixtureExtRect", None, MM)
                            else:
                                reason = conv._emitter_mesh(sc, desc, v, "light", MM, built, None, stacks, ex)
                    self.assertEqual(reason, L.EMITTER_UNREAD % "bad", (kind, order))
                    self.assertEqual(desc.issues, [(node, "%s: bad" % kind)], (kind, order))
                    self.assertEqual(built[0], 0, (kind, order))

    def test_a_refused_extrusion_named_once_for_the_shape_and_on_each_light(self):
        """The scene's corner budget spent before FixtureExtRect's Extrude: the light that meets it first gets its
        "Extrude is not made" reason, the shape's node its own "extrude: not made" line, once; nothing is made."""
        cfb = importlib.import_module(_PKG + ".reader.cfb")
        reader_scene = importlib.import_module(_PKG + ".reader.scene")
        reader_modifiers = importlib.import_module(_PKG + ".reader.modifiers")
        with cfb.CompoundFile(EXTRUDE_FIXTURE) as cf:
            sc = reader_scene.Scene.from_file(cf)
            stacks = reader_modifiers.Modifiers(sc)
            node = next(i for i in sc.walk() if sc.node(i).name == "FixtureExtRect")
            obj = sc.node(node).object
            base = sc.object_stack(obj).base
            ext = [m for m in stacks.object_stack(obj).modifiers if m.renders][0]
            v = {L.MESH_OBJECT: None, L.P_MESH_SOURCE: node}
            desc, built = conv.SceneDescription(MM), [conv.MAX_BUILT_CORNERS]
            ex = conv._Extrusions(sc, desc, {}, built)
            spent = conv._emitter_mesh(sc, desc, v, "light", MM, built, None, stacks, ex)
            for _ in range(2):
                key, _done = conv._extruded(sc, desc, ex, {}, base, ext, (), node, "FixtureExtRect", None, MM)
                self.assertIsNone(key)
            self.assertTrue(isinstance(spent, str) and "Extrude is not made" in spent, spent)
            lines = [(i, r) for i, r in desc.issues if r.startswith("extrude: ")]
            self.assertEqual(lines, [(node, "extrude: not made: " + conv._SPENT % conv.MAX_BUILT_CORNERS)])
            self.assertEqual(built[0], conv.MAX_BUILT_CORNERS)

    def test_shared_extrusion_dropped_at_the_last_node_of_the_shape_and_of_the_light(self):
        """describe() of the extrude fixture with FixtureExtL turned into a mesh light (shape test, light class and
        parameters patched: FixtureEmitter's values with FixtureExtRect's node as its mesh source) and the walk order
        patched (FixtureExtRect's node twice: a shape of two nodes): the extrusion is dropped at the shape's last
        node and at the light's last node only once no node of the shape is left (maxdrop-6n0.8.1). Per order: the
        extrude calls, the face corners counted (one extrusion's), its Extrude issue once on the node that made it."""
        cfb = importlib.import_module(_PKG + ".reader.cfb")
        reader_scene = importlib.import_module(_PKG + ".reader.scene")
        reader_modifiers = importlib.import_module(_PKG + ".reader.modifiers")
        with cfb.CompoundFile(MESH_FIXTURE) as cf:
            msc = reader_scene.Scene.from_file(cf)
            emitter = next(i for i in msc.walk() if msc.node(i).name == "FixtureEmitter")
            values, _issues = L.read_params(msc, msc.object_stack(msc.node(emitter).object).base)
        real_extrude, real_cls = conv.extrude.extrude, conv._Extrusions
        real_is_shape, real_class, real_read = conv.shapes.is_shape, L.light_class, L.read_params
        with cfb.CompoundFile(EXTRUDE_FIXTURE) as cf:
            sc = reader_scene.Scene.from_file(cf)
            by_name = {sc.node(i).name: i for i in sc.walk()}
            rect, light = by_name["FixtureExtRect"], by_name["FixtureExtL"]
            rect_base = sc.object_stack(sc.node(rect).object).base
            light_base = sc.object_stack(sc.node(light).object).base
            ext = [m for m in reader_modifiers.Modifiers(sc).object_stack(sc.node(rect).object).modifiers
                   if m.renders][0]
            data, _more = real_extrude(conv.shapes.read_shape(sc, rect_base), conv.extrude.read_params(sc, ext)[0])
            corners = len(data.loop_vertices)
            light_values = dict(values)
            light_values[L.MESH_OBJECT], light_values[L.P_MESH_SOURCE] = None, rect
            calls, made = [], []

            def counted(sh, params):
                calls.append(1)
                found, issues = real_extrude(sh, params)
                return found, issues + ["counted"]

            def captured(*args, **kw):
                made.append(real_cls(*args, **kw))
                return made[-1]

            patches = (mock.patch.object(conv.extrude, "extrude", counted),
                       patching.patch_all(conv, "_Extrusions", captured),
                       mock.patch.object(conv.shapes, "is_shape", lambda s, i: i != light_base and real_is_shape(s, i)),
                       patching.patch_all(L, "light_class", lambda s, i: L.VRAY if i == light_base else
                                          real_class(s, i)),
                       mock.patch.object(L, "read_params", lambda s, i, *a, **kw: (dict(light_values), [])
                                         if i == light_base else real_read(s, i, *a, **kw)))
            wants = {(light, rect): (1, light), (rect, light): (2, rect), (rect, light, rect): (1, rect),
                     (light, rect, rect): (1, light)}
            for order, (n_calls, first) in wants.items():
                calls.clear()
                made.clear()
                with patches[0], patches[1], patches[2], patches[3], patches[4], \
                        mock.patch.object(sc, "walk", return_value=list(order)):
                    desc = conv.describe(sc, MM)
                names = [sc.node(i).name for i in order]
                described = [n for n in desc.nodes if n.index == light]
                self.assertTrue(described and described[0].kind == conv.MESH and described[0].emitter is not None,
                                names)
                self.assertEqual((len(calls), len(made), made[0].built[0]), (n_calls, 1, corners), names)
                self.assertEqual([(i, r) for i, r in desc.issues if r == "extrude: counted"],
                                 [(first, "extrude: counted")], names)

    def test_a_refused_shape_a_mesh_light_meets_first_named_on_the_shapes_node_by_describe(self):
        """describe() with FixtureExtL a mesh light picking FixtureExtRect (patched as in the test above) and the reader
        refusing FixtureExtRect's shape: whichever node meets it first, the shape's node names the refusal once
        ("shape: bad": the light does not keep it in shape_of, the shape's _curve reads it again), the light gets it
        as its reason, both stay empties."""
        cfb = importlib.import_module(_PKG + ".reader.cfb")
        reader_scene = importlib.import_module(_PKG + ".reader.scene")
        shapes = importlib.import_module(_PKG + ".reader.shapes")
        with cfb.CompoundFile(MESH_FIXTURE) as cf:
            msc = reader_scene.Scene.from_file(cf)
            emitter = next(i for i in msc.walk() if msc.node(i).name == "FixtureEmitter")
            values, _issues = L.read_params(msc, msc.object_stack(msc.node(emitter).object).base)
        real_is_shape, real_class, real_read, real_shape = (conv.shapes.is_shape, L.light_class, L.read_params,
                                                            conv.shapes.read_shape)
        with cfb.CompoundFile(EXTRUDE_FIXTURE) as cf:
            sc = reader_scene.Scene.from_file(cf)
            by_name = {sc.node(i).name: i for i in sc.walk()}
            rect, light = by_name["FixtureExtRect"], by_name["FixtureExtL"]
            rect_base = sc.object_stack(sc.node(rect).object).base
            light_base = sc.object_stack(sc.node(light).object).base
            light_values = dict(values)
            light_values[L.MESH_OBJECT], light_values[L.P_MESH_SOURCE] = None, rect

            def refused(s, i):
                if i == rect_base:
                    raise shapes.ShapeError("bad")
                return real_shape(s, i)

            for order in ((light, rect), (rect, light), (light, rect, rect)):
                names = [sc.node(i).name for i in order]
                with mock.patch.object(conv.shapes, "read_shape", refused), \
                        mock.patch.object(conv.shapes, "is_shape",
                                          lambda s, i: i != light_base and real_is_shape(s, i)), \
                        patching.patch_all(L, "light_class", lambda s, i: L.VRAY if i == light_base else
                                           real_class(s, i)), \
                        mock.patch.object(L, "read_params", lambda s, i, *a, **kw: (dict(light_values), [])
                                          if i == light_base else real_read(s, i, *a, **kw)), \
                        mock.patch.object(sc, "walk", return_value=list(order)):
                    desc = conv.describe(sc, MM)
                self.assertEqual([(i, r) for i, r in desc.issues if r.startswith(("shape: ", "extrude: "))],
                                 [(rect, "shape: bad")], names)
                self.assertEqual([(i, r) for i, r in desc.issues if r.startswith("light: not built")],
                                 [(light, "light: not built: " + L.EMITTER_UNREAD % "bad")], names)
                self.assertEqual({n.index: n.kind for n in desc.nodes if n.index in (rect, light)},
                                 {rect: conv.EMPTY, light: conv.EMPTY}, names)

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


if __name__ == "__main__":
    unittest.main()
