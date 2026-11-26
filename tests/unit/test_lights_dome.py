# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/lights/ for the dome light: its rules, its texture's rules and vray_dome, no
Blender.

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
    _PKG, classids, colors, conv, DOME_FIXTURE, L, pblock, texmaps, values,
)


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

    def test_a_gamma_off_dome_is_shown_to_the_camera(self):
        """maxdrop-6n0.6.21: an untextured dome of a gamma-off scene (multiplier 0.5: V-Ray's sky 0.5, target 0.214)
        asks the World for the camera's decoded reading; gamma on or unknown does not."""
        for rule, shown in ((colors.GAMMA_OFF, True), (colors.GAMMA_ON, False), (colors.UNKNOWN, False)):
            with self.subTest(rule):
                dd, _ = L.describe_dome(1, "d", values(type=L.DOME, multiplier=0.5), rule, self.ROWS)
                self.assertIs(dd.shown, shown)
        self.assertFalse(L.DomeDescription(1, "d").shown, "none by default")

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

    def test_a_rotation_held_by_a_controller(self):
        """A VRayBitmap's horizontal rotation a controller holds is its value at frame 0 (maxdrop-6n0.6.32); what the
        read meets is in the issues, once also when the conversion reported it already."""
        params = importlib.import_module(_PKG + ".convert.params")
        controllers = importlib.import_module(_PKG + ".reader.controllers")

        class Block:
            block_id = 0

            def __init__(self, values):
                self.values = values

            def __contains__(self, pid):
                return pid in self.values

            def get(self, pid, tab=0, default=None):
                return self.values.get(pid, default)

            def param(self, pid):
                return types.SimpleNamespace(base_type=5 if pid == L.VB_H_ROTATION else 1)

        class Map(_Map):
            index = 3

            def __init__(self, values):
                super().__init__(tuple(classids.VRAY_BITMAP), values)
                self.blocks = {0: Block(values)}

            def block(self, block_id):
                return self.blocks.get(block_id)

        graph = _Graph({3: Map({texmaps.VB_MAP_TYPE: L.VB_SPHERICAL, L.VB_H_ROTATION: pblock.Animated(40)})})
        graph.scene = object()
        line = "'sky': parameter %d at frame 0 (controller 40): %s" % (L.VB_H_ROTATION, controllers.ANIMATED)
        issue = controllers.Issue(None, 40, None, None, controllers.ANIMATED)
        with mock.patch.object(params.controllers, "parameter_value", return_value=(0.7, [issue])):
            dt, issues = L.dome_texture(self.ir(self.image()), graph)
            self.assertEqual((dt.turn, issues), (0.7, [line]))
            dt, issues = L.dome_texture(self.ir(self.image(), [line]), graph)
            self.assertEqual(issues, [line])
        with mock.patch.object(params.controllers, "parameter_value", return_value=(None, [])):
            dt, issues = L.dome_texture(self.ir(self.image()), graph)
        self.assertEqual(dt.turn, 0.0)
        self.assertEqual(issues, ["'sky': parameter %d at frame 0 (controller 40): %s, %s" % (
            L.VB_H_ROTATION, params.NOT_READ, params.DEFAULT_USED)])

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

    def test_the_camera_sees_a_gamma_off_float_texture_decoded(self):
        """maxdrop-6n0.6.21: V-Ray 5.2 shows a gamma-off float dome's sky display-referred (a uniform 0.5 EXR: sky
        0.5, target 0.214; at multiplier 2: 1.0): DomeTexture.shown asks the World for the camera's reading; a
        gamma-on or 8-bit texture has none."""
        for gamma, space in ((2.2, texmaps.SRGB), (None, texmaps.SRGB), (texmaps.SRGB_TWICE, texmaps.LINEAR)):
            with self.subTest(gamma=gamma):
                dt, _issues = L.dome_texture(self.ir(self.image(gamma=gamma, colorspace=space)), self.vray({}),
                                             colors.GAMMA_OFF)
                self.assertTrue(dt.shown)
                self.assertIn("shown", repr(dt))
        lin = self.image(gamma=1.0, colorspace=texmaps.LINEAR)
        self.assertFalse(L.dome_texture(self.ir(lin), self.vray({}), colors.GAMMA_ON)[0].shown, "gamma on")
        png = texmaps.Image(3, "sky.png", found=self.FOUND, gamma=texmaps.SRGB_TWICE, colorspace=texmaps.LINEAR)
        self.assertFalse(L.dome_texture(self.ir(png), self.vray({}), colors.GAMMA_OFF)[0].shown, "an 8-bit file")
        self.assertIn("the camera sees the sky decoded", L.DOME_FLOAT_OFF)
        self.assertFalse(L.DomeTexture(lin).shown, "none by default")

    def test_a_float_texture_keeps_its_own_decode_whatever_the_case_a_corona_bitmap_too(self):
        """Measured as a light (maxdrop-em3.166; docs/FORMAT.md, Scene gamma): the line says so. The extension's case
        does not matter; a CoronaBitmap, shown decoded once more on a material with the gamma off as a VRayBitmap is
        (maxdrop-em3.165), keeps its own decode too."""
        self.assertNotIn("not measured", L.DOME_FLOAT_OFF)
        shown = dict(gamma=2.2, colorspace=texmaps.SRGB)
        upper = texmaps.Image(3, "SKY.EXR", found=self.FOUND, **shown)
        dt, issues = L.dome_texture(self.ir(upper), self.vray({}), colors.GAMMA_OFF)
        self.assertEqual((dt.image.gamma, dt.image.colorspace, issues),
                         (1.0, texmaps.LINEAR, [L.DOME_FLOAT_OFF % "SKY.EXR"]))
        corona = self.image(**shown)
        dt, issues = L.dome_texture(self.ir(corona), _Graph({3: _Map(tuple(classids.CORONA_BITMAP), {})}),
                                    colors.GAMMA_OFF)
        self.assertEqual((dt.image.gamma, dt.image.colorspace, issues),
                         (1.0, texmaps.LINEAR, [L.DOME_CORONA % "sky.hdr", L.DOME_FLOAT_OFF % "sky.hdr"]))
        dt, issues = L.dome_texture(self.ir(corona), _Graph({3: _Map(tuple(classids.CORONA_BITMAP), {})}),
                                    colors.GAMMA_ON)
        self.assertEqual((dt.image, issues), (corona, [L.DOME_CORONA % "sky.hdr"]), "gamma on: as converted")

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
