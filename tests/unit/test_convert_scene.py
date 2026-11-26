# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/scene/, the scene description: no Blender. The smoothing-group rule, the loop reversal
of a mirrored object offset, and every committed fixture against its 3ds Max oracle (order, parents, world
matrices, world bounding boxes, counts, shared meshes, units) and its authoring script (UV channels, smoothing
groups), the shapes' curves against the oracle's knots and segment midpoints.

    python -I -m unittest discover tests
"""
import ast
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
from maxdrop_unit_tests.convert_scene_support import (  # noqa: E402 (after the loader)
    _name, _oracle, _shading, _world_points, BBOX_TOLERANCE, conv, FIXTURES, MATRIX_TOLERANCE, numpy,
    ROOT,
)


# From the fixture scripts (tools/fixtures/*.ms: mapcoords:true gives channel 1); the oracle has no map channels or
# smoothing groups.
UV_LAYERS = {
    "arc_pie_reverse": ["UVMap"],  # every Extrude with Generate Mapping Coords; the two plain arcs are curves
    "box_poly_standard": ["UVMap"],
    "corona_layered": ["UVMap"],
    "corona_classes": ["UVMap"],
    "corona_mix_blends": ["UVMap"],
    "corona_mix_ops": ["UVMap"],
    "corona_more": ["UVMap"],
    "corona_legacy": ["UVMap"],
    "corona_light": ["UVMap"],
    "corona_maps": ["UVMap"],
    "corona_physical": ["UVMap"],
    "editable_mesh": ["UVMap"],
    # per mesh (named after its first node): Extrude makes channel 1 only with Generate Mapping Coords.
    "falloff_curve": ["UVMap"],
    "extrude": {"FixtureExtRect": ["UVMap"], "FixtureExtAdaptive": ["UVMap"], "FixtureExtDownStart": ["UVMap"],
                "FixtureExtDownEndReal": ["UVMap"]},
    "gamma_swatches": ["UVMap"],
    "hierarchy": [],
    "instances": ["UVMap"],
    "layers_flags": [],
    "layers_more": [],
    "layers_nested": [],
    "layers_render": [],
    "lookat": [],  # boxes without Generate Mapping Coords
    "modifier_pivot": ["UVMap"],  # FixtureBent's UVW Map writes channel 1 (applied, the Bend above it is not)
    "multi_uv": ["UVMap", "UVChannel_2", "UVChannel_3"],
    "pblock_animated": ["UVMap"],
    "primitives": collections.defaultdict(lambda: ["UVMap"], {"FixtureBoxNoMap": []}),  # Generate Mapping Coords
    "shapes": ["UVMap"],  # FixtureBox; the shapes are curves
    "shapes_more": ["UVMap"],  # FixtureBox; the shapes are curves
    "stack_basic": ["UVMap"],  # FixtureTurbo's UVW Map writes channel 1; no other modifier is applied
    "stack_convert": ["UVMap"],  # its modifiers become Blender modifiers: the base meshes are built
    "stack_shell": ["UVMap"],  # its Shells become Solidify: the base meshes (open boxes) are built
    "stack_wsm": ["UVMap"],  # FixtureWSM's UVW Map writes channel 1; the Map Scaler bindings are not applied
    "standard_physical": ["UVMap"],
    "standard_shaders": ["UVMap"],
    "standard_maps": ["UVMap"],
    "saved_as_2017": ["UVMap"],
    "saved_as_2018": ["UVMap"],
    "saved_as_2019": ["UVMap"],
    "texmap_rules": ["UVMap"],
    "texmap_wrappers": ["UVMap"],
    "units_cm": ["UVMap"],
    "units_in": ["UVMap"],
    "units_mm": ["UVMap"],
    "vray_basic": ["UVMap"],
    "vray_maps": ["UVMap"],
    "vray_texmaps": ["UVMap"],
    "vray_more": ["UVMap"],
    "vray_lights": [],  # lights and a target: no mesh
    "vray_dome": [],  # lights and a box without Generate Mapping Coords
    "vray_mesh_light": ["UVMap"],  # Planes, also as the emitters' meshes
    "lights_standard": [],
    "lights_photometric": [],
    "cameras": [],  # its box, without Generate Mapping Coords; the cameras are no mesh
    "controllers": [],  # boxes without Generate Mapping Coords
    "controllers_tangents": [],  # boxes without Generate Mapping Coords
    "controllers_ranges": [],  # boxes without Generate Mapping Coords
    "vray_wrappers": ["UVMap"],
    # per mesh: every box, the cylinder and the sphere have channel 1; two UVW Maps write channels 2 and 3
    "uvwmap": collections.defaultdict(lambda: ["UVMap"], {"FixtureUVWGizmo": ["UVMap", "UVChannel_2"],
                                                          "FixtureUVWTwo": ["UVMap", "UVChannel_3"]}),
    "uvwmap_oblique": ["UVMap"],
    "uvwmap_pole": ["UVMap"],
}
SHARP_EDGES_POLY_BOX = 12  # one smoothing group per side: every edge of the box
SHARP_EDGES_EDITABLE_MESH = 8  # group 1 on top and bottom, 2 on the sides: the rims of top and bottom
SHARP_EDGES_TALL_BOX = 24  # modifier_pivot's four height segments: 4 x 4 vertical side edges and both rims
# stack_shell's boxes without their top: the 4 vertical and the 4 bottom edges, and the 4 open edges a hardened Shell
# rim makes sharp
SHARP_EDGES_OPEN_BOX = 12
# stack_shell's other meshes: the plane's open edges; a TurboSmooth below the Shell clears the box's groups but its open
# edges stay sharp; above the Shell it smooths the rim too (no sharp edge)
SHARP_EDGES_SHELL = {"FixtureShellPlane": 4, "FixtureShellTurbo": 4, "FixtureShellSmoothed": 0,
                     # the half and quarter boxes below a Symmetry (2 x 2 segments): the edges between their sides
                     # and the top's open edges, not those of the cut, which the Mirror welds shut
                     "FixtureShellSymHalf": 6 + 4, "FixtureShellSymClosed": 10, "FixtureShellSymQuarter": 3 + 2,
                     # Shells below a Symmetry whose plane holds their cut: the Mirror moved below them welds it; a
                     # TurboSmooth (Smooth Result) above smooths everything; weld off: the cut's open edges sharp too
                     "FixtureShellUnderSym": 6 + 4, "FixtureShellUnderSymTurbo": 0, "FixtureShellBetweenSym": 3 + 2,
                     "FixtureShellUnderSymNoWeld": 6 + 8}
# extrude: the vertical edges at corner knots (one per level) and both rims of every capped outline
SHARP_EDGES_EXTRUDE = {"FixtureExtRect": 4 * 2 + 8, "FixtureExtL": 6 + 12, "FixtureExtHole": 4 + 8 + 56,
                       "FixtureExtIsland": 12 + 24, "FixtureExtOpen": 0, "FixtureExtMirror": 8 + 64,
                       "FixtureExtAdaptive": 256, "FixtureExtShapeIDs": 11 + 30, "FixtureExtShapeIDsRect": 4 + 8,
                       "FixtureUVWExtrude": 4 + 8,
                       # grid caps: as above (the circle smooth, one rim: Cap End off)
                       "FixtureExtGrid": 10 + 8 + 18, "FixtureExtGridCircle": 16,
                       # downwards, one cap each: 3 and 2 levels of corner columns, one rim
                       "FixtureExtDownStart": 4 * 3 + 4, "FixtureExtDownEndReal": 4 * 2 + 4,
                       # arc_pie_reverse: both rims of a pie's 23 columns and the side broken at from, the
                       # center and to in 2 segments (maxdrop-em3.111); the open arc none; the clockwise Line and
                       # the holed cap as above
                       "FixturePieRevExt": 46 + 6, "FixturePieRevWrapExt": 46 + 6, "FixturePieExt": 46 + 6,
                       "FixtureArcRevExt": 0, "FixtureClockwiseExt": 4 * 2 + 8, "FixtureHoleExt": 4 * 2 + 8 + 56,
                       # stack_shell: an open Line's two corner columns, the hardened rim but its ends on the plane
                       "FixtureShellUnderSymExtrude": 2 + 6}
# uvwmap: boxes of 3 x 2 x 2 segments, a group per side: 28 edges; the cylinder's two rims; the sphere is smooth
SHARP_EDGES_UVWMAP = {"FixtureUVWCyl": 32, "FixtureUVWSphere": 0, "FixtureUVWSharedB": SHARP_EDGES_POLY_BOX,
                      # uvwmap_oblique: smooth spheres, the rims of a 10-sided cylinder
                      "FixtureUVWObliqueBox": 0, "FixtureUVWObliqueMirror": 0, "FixtureUVWObliqueCap": 20,
                      "FixtureUVWObliqueBoxX": 0, "FixtureUVWObliquePlanarX": 0,
                      # uvwmap_pole: the rims of 10-sided cylinders, smooth spheres
                      "FixtureUVWPoleCylinder": 20, "FixtureUVWPoleNear": 20, "FixtureUVWPoleOff": 20,
                      "FixtureUVWPoleDiagonal": 20, "FixtureUVWPoleSphere": 0, "FixtureUVWPoleSphereCyl": 0,
                      "FixtureUVWPoleSphereNear": 0, "FixtureUVWPoleSphereOff": 0,
                      "FixtureUVWPoleCone": 10,  # its base rim
                      "FixtureUVWPoleSphereTall": 0, "FixtureUVWPoleTile": 20, "FixtureUVWPoleSphereTile": 0,
                      "FixtureUVWPoleCenter": 20}
# primitives: a group per side of a box (FixtureBox's edges in segments: 4 x 3 + 4 x 2 + 4 x 4), the rims of
# cylinders, cones and tubes, the pyramid's four ridges of 2 segments and its base outline of 10, the torus's
# alternating groups (every edge between two sides; on the odd one every edge between two segments), every edge of
# the unsmoothed GeoSphere; spheres, smooth GeoSpheres and planes have none. Slice and the hemispheres: the base's
# rim, the rims of the cut planes (their profile and the edges to the fans) and the axis between the two, and the
# torus's rows of a smoothing group each by segment
SHARP_EDGES_PRIMITIVES = {"FixtureBox": 36, "FixtureBoxDown": 12, "FixtureBoxNoMap": 12, "FixtureBoxSmooth": 0,
                          "FixturePlane": 0, "FixturePyramid": 4 * 2 + 10, "FixtureSphere": 0, "FixtureGeoSphere": 0,
                          "FixtureGeoOcta": 48, "FixtureCylinder": 20, "FixtureCone": 18, "FixtureTube": 32,
                          "FixtureTorus": 96, "FixtureBoxInside": 16, "FixturePlaneDown": 0,
                          "FixtureCylinderDown": 14, "FixtureConeTip": 14, "FixtureTubeSwap": 28,
                          "FixtureTorusOdd": 35, "FixturePlaneReal": 0, "FixturePyramidDown": 4 * 2 + 6,
                          "FixtureSphereOdd": 0, "FixtureGeoReal": 0, "FixtureCylinderReal": 14,
                          "FixtureTubeDown": 28, "FixtureSphereHemi": 12, "FixtureSphereSquash": 13,
                          "FixtureSphereSlice": 12,
                          "FixtureSphereSliceHemi": 29, "FixtureGeoHemi": 30, "FixtureGeoHemiTetra": 6,
                          "FixtureCylinderSlice": 30, "FixtureCylinderSliceDown": 19, "FixtureConeSlice": 26,
                          "FixtureTubeSlice": 36, "FixtureTorusSlice": 60}
FLAT_MESHES = {"FixtureGeoOcta"}
# the oracle's base_class_id of the primitives MaxDrop builds (convert/primitives/)
PRIMITIVE_CLASSES = {("0x00000010", "0x00000000"), ("0x00000011", "0x00000000"), ("0x00000012", "0x00000000"),
                     ("0x00000020", "0x00000000"), ("0xa86c23dd", "0x00000000"), ("0x00007b21", "0x00000000"),
                     ("0x00000000", "0x00007f9e"), ("0x081f1dfc", "0x77566f65"), ("0x76bf318a", "0x4bf37b10")}
# placeholders the fixtures hold: lookat's Point helper
PLACEHOLDERS = {"lookat": {"Point": 1}}
NO_DECAY = "light: no decay: Blender's light falls off with the square of the distance; as bright as in 3ds Max at 1 m"
# the issues the fixtures are made to raise
ISSUES = {"uvwmap": ["uvw map: a UVW Map above Bend is not evaluated",
                     "uvw map: shrink-wrap mapping is not evaluated: the stored channel stays"],
          "stack_convert": ["modifiers: TurboSmooth above Bend is not converted"],
          # FixtureNoReceiveShadow (FixtureNoCastShadow is an object flag, no issue)
          "layers_flags": ["shadows: Receive Shadows is off: Blender has no such switch per object, it receives "
                           "shadows"],
          # FixtureByLayerNoReceive, By Layer on a layer with Receive Shadows off
          "layers_render": ["shadows: Receive Shadows is off: Blender has no such switch per object, it receives "
                            "shadows"],
          # the plane's rim corners (auto smooth), the open box's override group (auto smooth off)
          "stack_shell": ["modifiers: Shell: auto smooth: 4 corners of the rim sharper than 45 degrees shade smooth "
                          "(3ds Max splits the rim there)",
                          "modifiers: Shell: smoothing group override (group 4) not converted: 3ds Max merges the rim "
                          "into the faces along it of that group",
                          # FixtureShellUnderSymNoWeld: a Symmetry with its weld off above the Shell
                          "modifiers: Symmetry: the rim of the Shell below it along the mirror plane differs from 3ds "
                          "Max's: the Mirror is moved below the Solidify only for a rim lying on the plane, with slice "
                          "and weld on"],
          "lookat": [NO_DECAY],  # its target spot (its Perspective viewport is a note of the report, no issue)
          "cameras": ["camera: depth of field is not imported"] * 2 + [
              "camera: its exposure is not imported: Blender renders as if the camera had none"] * 3 + [
              "camera: its tilt correction (0, 5) is not imported: Blender has no keystone correction"],
          "lights_standard": [
              "light: ambient only is not imported: it lights as any light",
              "light: inverse decay: Blender's light falls off with the square of the distance; as bright as in 3ds "
              "Max at 0.5 m",
              "light: its beam (0.8 m across) is not imported: the sun lights the whole scene",
              "light: its beam (1.4 m across) is not imported: the sun lights the whole scene",
              "light: its color is its filter color: the sky model's sun color is not imported",
              "light: its rectangular cone is drawn round",
              "light: its strength is the sun's at the zenith: the sky model's dimming toward the horizon is not "
              "imported",
              "light: multiplier -1 is negative: 0 W"] + [NO_DECAY] * 6 + [
              "light: not built: a Skylight is not imported yet (Skylight -> World is later work)",
              "light: overshoot is not imported: the spot lights its cone only",
              "light: the environment map is a VRaySky: not imported yet (environment -> World is later work)"],
          "lights_photometric": [
              "light: its IES file fixture_web.ies is approximated by a spot of 170 degrees",
              "light: its IES file fixture_web.ies is approximated by a spot of 170 degrees",
              "light: its cylinder shape is a sphere of its radius",
              "light: its cylinder shape is a sphere of its radius",
              "light: its disc shape is a sphere of its radius",
              "light: its line shape is a rectangle 0.01 m wide",
              "light: its line shape is not imported: a point",
              "light: its photometric web fixture_web.ies is approximated by a spot of 170 degrees",
              "light: its power is taken as its flux: V-Ray scales the IES file's candelas by the power over "
              "the file's rated lumens, which are not read (the file is not found: beside the scene, in its maps "
              "or textures folder or a texture search folder it would be)",
              "light: its rectangle light shape is a sphere 0.4 m across",
              "light: its rectangle shape is not imported: a point"],
          "vray_lights": ["light: diffuse contribution 0.5: Blender's diffuse factor, which only EEVEE uses",
                          "light: double-sided: Blender's area light shines on one side, with half the power",
                          "light: not built: a mesh light without a mesh (none picked, or its node deleted): not "
                          "imported"],
          "vray_dome": ["light: a second dome light: not imported (Blender has one World, FixtureDome's)"],
          "vray_mesh_light": ["light: not built: a mesh light without a mesh (none picked, or its node deleted): not "
                              "imported"]}  # FixtureEmitterOwn's Shell: a Solidify on its emitter
# the oracle's base_class_id of the lights MaxDrop builds: VRayLight, VRaySun, VRayIES, the standard and the
# photometric lights
LIGHT_CLASSES = {("0x3c5575a1", "0x5fd602df"), ("0x732c0383", "0x7d993776"), ("0x2eaf2f07", "0x7ec44f31"),
                 ("0x00001011", "0x00000000"), ("0x00001012", "0x00000000"), ("0x00001013", "0x00000000"),
                 ("0x00001014", "0x00000000"), ("0x00001015", "0x00000000"), ("0x32375fcc", "0x0b025cf0"),
                 ("0x78207401", "0x357f1d58"), ("0x36507d92", "0x105a1a47"), ("0x5bcc6d42", "0x0c4f430e"),
                 ("0x7ca93582", "0x1abb6b32"), ("0x46f634e3", "0x0a327aaf"), ("0x658d4f97", "0x72cd4259"),
                 ("0x45076885", "0x40791449"), ("0x71794f9d", "0x70ae52f2"), ("0x38732348", "0x201758b3"),
                 ("0x33fc7ae9", "0x54433dc5"), ("0x7c8b5b10", "0x4bd33e86")}
# not built as lights: vray_lights' mesh light without a mesh and the domes (a dome is the World), vray_mesh_light's
# mesh light without a mesh, lights_standard's Skylight (not in LIGHT_CLASSES)
UNBUILT_LIGHTS = {"FixtureMesh", "FixtureDome", "FixtureDomeColor", "FixtureEmitterNone"}
# mesh lights built as emitters: MESH nodes whose 3ds Max counts and box are the light's icon, not the mesh
EMITTERS = {"FixtureMeshLight", "FixtureEmitter", "FixtureEmitterW", "FixtureEmitterOwn"}
# meshes under a converted smoother with Smooth Result: no sharp edge (modifier_pivot's reference, stack_basic's box)
SHARP_EDGES_SMOOTHED = {"FixtureSmooth": 0, "FixtureTurbo": 0, "FixtureTurboOne": 0, "FixtureMeshSmooth": 0,
                        "FixtureOrder": 0, "FixtureTurboSymHalf": 0}


def _run_py_table(name):
    """A module-level table of tests/blender/tables.py, whose package imports bpy: read from its source."""
    path = os.path.join(ROOT, "tests", "blender", "tables.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets):
            return ast.literal_eval(stmt.value)
    raise AssertionError("no %s in tests/blender/tables.py" % name)


def _uv_layers(fixture, mesh):
    """UV_LAYERS of one mesh: a fixture's list, or its table per mesh (a mesh not in a plain dict has none)."""
    want = UV_LAYERS[fixture]
    if isinstance(want, collections.defaultdict):
        return want[mesh]
    return want.get(mesh, []) if isinstance(want, dict) else want


def _extruded_nodes():
    """(fixture, node name) of every oracle node check_extruded (tests/blender/checks_objects.py) runs on: a shape
    under an Extrude (an Extrude that is off leaves no eval_verts; test_counts_equal_the_oracle holds that rule to the
    node kinds). The tables are keyed by node name: an extruded object with instances would need its mesh's name."""
    return [(_name(p), o["name"]) for p in FIXTURES for o in _oracle(p)["nodes"]
            if o["shape"] is not None and o["eval_verts"] is not None]


class FixtureTables(unittest.TestCase):
    """Every committed fixture has an entry in the per-fixture tables, here and in tests/blender/tables.py, and every
    extruded object one in tables.py's per-object extrude tables, so a new fixture or object fails the plain suite
    instead of only the Blender run."""

    def _same_names(self, table, where):
        names = {_name(p) for p in FIXTURES}
        self.assertTrue(names)
        self.assertEqual(sorted(names - set(table)), [], "fixtures without an entry in " + where)
        self.assertEqual(sorted(set(table) - names), [], "entries without a fixture in " + where)

    def test_uv_layers_lists_every_fixture(self):
        self._same_names(UV_LAYERS, "UV_LAYERS of tests/unit/test_convert_scene.py")

    def test_blender_run_uv_layers_lists_every_fixture(self):
        self._same_names(_run_py_table("UV_LAYERS"), "UV_LAYERS of tests/blender/tables.py")

    def test_blender_run_extrude_tables_list_every_extruded_object(self):
        nodes = _extruded_nodes()
        names = {n for _f, n in nodes}
        self.assertTrue(names)
        self.assertEqual(len(names), len(nodes), "extruded node names repeat across fixtures: " + str(nodes))
        for table in ("EXTRUDE_EULER", "EXTRUDE_SHARP_EDGES"):  # indexed by check_extruded
            keys = set(_run_py_table(table))
            self.assertEqual(sorted(names - keys), [], "extruded objects without an entry in %s of "
                             "tests/blender/tables.py" % table)
            self.assertEqual(sorted(keys - names), [], "entries without an extruded object in %s of "
                             "tests/blender/tables.py" % table)
        self.assertEqual(_run_py_table("EXTRUDE_SHARP_EDGES"), SHARP_EDGES_EXTRUDE,
                         "EXTRUDE_SHARP_EDGES of tests/blender/tables.py differs from SHARP_EDGES_EXTRUDE")
        uv = _run_py_table("EXTRUDE_UV_LAYERS")  # read with .get(name, []): no entry is no UV layer
        self.assertEqual(sorted(set(uv) - names), [], "entries without an extruded object in EXTRUDE_UV_LAYERS "
                         "of tests/blender/tables.py")
        for fixture, name in nodes:
            self.assertEqual(uv.get(name, []), _uv_layers(fixture, name),
                             "%s: EXTRUDE_UV_LAYERS of tests/blender/tables.py differs from UV_LAYERS" % name)


@unittest.skipIf(numpy is None, "numpy missing")
class Fixtures(unittest.TestCase):
    """Every committed fixture against its 3ds Max oracle."""

    @classmethod
    def setUpClass(cls):
        cls.cases = [(_name(p), conv.read(p), _oracle(p)) for p in FIXTURES]

    def test_units_follow_the_file(self):
        meters = {name: desc.meters for name, desc, _o in self.cases}
        self.assertEqual(meters["units_mm"], 0.001)
        self.assertEqual(meters["units_cm"], 0.01)
        self.assertEqual(meters["units_in"], 0.0254)
        self.assertEqual(meters["box_poly_standard"], 0.001)

    def test_order_names_and_parents_equal_the_oracle(self):
        for name, desc, oracle in self.cases:
            position = {n["handle"]: n["index"] for n in oracle["nodes"]}
            ours = {node.index: k for k, node in enumerate(desc.nodes)}
            self.assertEqual([n.name for n in desc.nodes], [n["name"] for n in oracle["nodes"]], name)
            self.assertEqual([None if n.parent is None else ours[n.parent] for n in desc.nodes],
                             [None if n["parent"] is None else position[n["parent"]] for n in oracle["nodes"]],
                             name)

    def test_world_matrices_equal_the_oracle(self):
        for name, desc, oracle in self.cases:
            for node, o in zip(desc.nodes, oracle["nodes"]):
                w = node.world
                rows = [[w[c][r] for c in range(3)] for r in range(3)] + [[w[c][3] / desc.meters for c in range(3)]]
                expected = [o["transform"][k:k + 3] for k in range(0, 12, 3)]
                for got_row, want_row in zip(rows, expected):
                    for got, want in zip(got_row, want_row):
                        self.assertAlmostEqual(got, want, delta=MATRIX_TOLERANCE, msg="%s %s" % (name, node.name))

    def test_local_matrices_compose_to_the_world(self):
        for name, desc, _o in self.cases:
            by_index = {n.index: n for n in desc.nodes}
            for node in desc.nodes:
                m = numpy.asarray(node.matrix)
                if node.parent is not None:
                    m = numpy.asarray(by_index[node.parent].world) @ m
                numpy.testing.assert_allclose(m, numpy.asarray(node.world), atol=1e-9, err_msg=name)

    def test_world_bounding_boxes_equal_the_oracle(self):
        for name, desc, oracle in self.cases:
            for node, o in zip(desc.nodes, oracle["nodes"]):
                # the oracle's box is after every modifier: a UVW Map left as it is moves nothing
                if node.kind != conv.MESH or any(m != "UVW Map" for m in node.modifiers) or node.converted or \
                        (o["modifiers"] and not node.applied) or node.emitter is not None:
                    continue
                p = _world_points(node, desc.meshes[node.mesh]) / desc.meters
                numpy.testing.assert_allclose(p.min(axis=0), o["bbox_min"], atol=BBOX_TOLERANCE,
                                              err_msg="%s %s" % (name, node.name))
                numpy.testing.assert_allclose(p.max(axis=0), o["bbox_max"], atol=BBOX_TOLERANCE,
                                              err_msg="%s %s" % (name, node.name))

    def test_counts_equal_the_oracle(self):
        for name, desc, oracle in self.cases:
            for node, o in zip(desc.nodes, oracle["nodes"]):
                extruded = o["shape"] is not None and o["eval_verts"] is not None  # an Extrude on the shape
                primitive = tuple(o["base_class_id"]) in PRIMITIVE_CLASSES
                light = tuple(o["base_class_id"] or ()) in LIGHT_CLASSES and o["name"] not in UNBUILT_LIGHTS | EMITTERS
                kind = conv.MESH if o["base_verts"] is not None or extruded or primitive or o["name"] in EMITTERS else \
                    conv.CURVE if o["shape"] else conv.LIGHT if light else \
                    conv.CAMERA if o["camera"] is not None else conv.EMPTY
                self.assertEqual(node.kind, kind, "%s %s" % (name, node.name))
                self.assertEqual(node.emitter is not None, o["name"] in EMITTERS, "%s %s" % (name, node.name))
                if node.kind == conv.MESH and node.emitter is None:
                    md = desc.meshes[node.mesh]
                    if primitive and o["modifiers"]:  # 3ds Max's counts are after the TurboSmooth
                        self.assertTrue(node.converted, "%s %s" % (name, node.name))
                    elif extruded or primitive:  # 3ds Max's counts are of triangles, after converted modifiers
                        if not node.converted:
                            self.assertEqual((len(md.positions), int((md.loop_totals - 2).sum())),
                                             (o["eval_verts"], o["eval_faces"]), "%s %s" % (name, node.name))
                    else:
                        self.assertEqual((len(md.positions), len(md.loop_starts)), (o["base_verts"], o["base_faces"]),
                                         "%s %s" % (name, node.name))
                    self.assertEqual(int(md.loop_totals.sum()), len(md.loop_vertices))

    def test_shared_meshes_equal_the_oracle_instances(self):
        """The nodes sharing a base object and the same object offset share one mesh (the offset is baked)."""
        for name, desc, oracle in self.cases:
            handle = {node.index: o["handle"] for node, o in zip(desc.nodes, oracle["nodes"])}
            by_handle = {o["handle"]: o for o in oracle["nodes"]}

            def offset(o):
                return o["offset_pos"], o["offset_rot"], o["offset_scale"]

            shading = {o["handle"]: _shading(node) for node, o in zip(desc.nodes, oracle["nodes"])}
            for node, o in zip(desc.nodes, oracle["nodes"]):
                if node.kind == conv.MESH:
                    # a converted smoother's shading is the mesh's own: an instance without it has another mesh
                    want = [h for h in o["instances"] if offset(by_handle[h]) == offset(o)
                            and shading[h] == shading[o["handle"]]]
                    self.assertEqual(sorted(handle[u] for u in desc.meshes[node.mesh].users), want,
                                     "%s %s" % (name, node.name))

    def test_rotated_pivot_leaves_the_object_in_place(self):
        """modifier_pivot: FixtureBent's pivot alone is turned 30 degrees about Z. Its baked base mesh is the
        source's, moved by the 30 units between the two nodes: the offset rotation undoes the pivot's."""
        desc = dict((n, d) for n, d, _o in self.cases)["modifier_pivot"]
        by_name = {n.name: n for n in desc.nodes}
        src, bent = by_name["FixtureSource"], by_name["FixtureBent"]
        self.assertNotEqual(src.mesh, bent.mesh)
        self.assertIsNotNone(bent.mesh[1])
        a = _world_points(src, desc.meshes[src.mesh]) / desc.meters
        b = _world_points(bent, desc.meshes[bent.mesh]) / desc.meters - [30, 0, 0]
        numpy.testing.assert_allclose(b, a, atol=BBOX_TOLERANCE)

    def test_instances_share_one_mesh_and_the_copy_has_its_own(self):
        desc = dict((n, d) for n, d, _o in self.cases)["instances"]
        self.assertEqual(len(desc.meshes), 2)
        self.assertEqual(sorted(len(md.users) for md in desc.meshes.values()), [1, 4])

    def test_mirrored_flag(self):
        desc = dict((n, d) for n, d, _o in self.cases)["hierarchy"]
        self.assertEqual([n.name for n in desc.nodes if n.mirrored], ["FixtureLeaf"])

    def test_object_offset_is_baked_into_the_mesh(self):
        desc = dict((n, d) for n, d, _o in self.cases)["hierarchy"]
        root = desc.nodes[0]
        self.assertEqual(root.name, "FixtureRoot")
        self.assertIsNotNone(root.mesh[1])
        self.assertIsNone(desc.nodes[2].mesh[1])  # FixtureLeaf: no offset

    def test_uv_layers_follow_the_map_channels(self):
        for name, desc, _o in self.cases:
            for md in desc.meshes.values():
                want = _uv_layers(name, md.name)
                self.assertEqual([n for n, _uv in md.uv_layers], want, name)
                for _n, uv in md.uv_layers:
                    self.assertEqual(uv.shape, (len(md.loop_vertices), 2))
                    self.assertEqual(uv.dtype, numpy.float32)

    def test_sharp_edges_from_smoothing_groups(self):
        for name, desc, _o in self.cases:
            want = {"editable_mesh": SHARP_EDGES_EDITABLE_MESH,
                    "modifier_pivot": SHARP_EDGES_TALL_BOX, "uvwmap": 28,
                    "stack_shell": SHARP_EDGES_OPEN_BOX, "vray_mesh_light": 0}.get(name, SHARP_EDGES_POLY_BOX)
            for md in desc.meshes.values():
                if name == "primitives":  # FixtureBox is a name of other fixtures too
                    want = SHARP_EDGES_PRIMITIVES[md.name]
                want_here = SHARP_EDGES_SMOOTHED.get(md.name, SHARP_EDGES_EXTRUDE.get(
                    md.name, SHARP_EDGES_UVWMAP.get(md.name, want)))
                if name == "stack_shell":
                    want_here = SHARP_EDGES_SHELL.get(md.name, want_here)
                self.assertEqual(len(md.sharp_edges), want_here, "%s %s" % (name, md.name))
                # an unsmoothed GeoSphere has no smoothing group: every face flat
                self.assertEqual(bool(md.sharp_faces.any()), md.name in FLAT_MESHES, "%s %s" % (name, md.name))
                if md.name in FLAT_MESHES:
                    self.assertTrue(md.sharp_faces.all(), name)

    def test_placeholders(self):
        for name, desc, _o in self.cases:
            # the group head is a Dummy: converted, an empty
            self.assertEqual(dict(desc.placeholders), PLACEHOLDERS.get(name, {}), name)
            self.assertEqual(sorted(r for _i, r in desc.issues), ISSUES.get(name, []), name)
            self.assertEqual(dict(desc.unknown_controllers), {}, name)
        desc = dict((n, d) for n, d, _o in self.cases)["layers_flags"]
        head = next(n for n in desc.nodes if n.kind == conv.EMPTY)
        self.assertEqual((head.name, head.class_name, head.mesh), ("FixtureGroup", "Dummy", None))

    def test_flags_and_layers_equal_the_oracle(self):
        for name, desc, oracle in self.cases:
            names = {la.index: la.name for la in desc.layers}
            used = []
            for node, o in zip(desc.nodes, oracle["nodes"]):
                self.assertEqual((node.hidden, node.frozen, node.renderable, names[node.layer]),
                                 (o["hidden"], o["frozen"], o["renderable"], o["layer"]), o["name"])
                self.assertEqual((node.cast_shadows, node.receive_shadows), (o["cast_shadows"], o["receive_shadows"]),
                                 o["name"])
                if o["layer"] not in used:
                    used.append(o["layer"])
            parents = {la["name"]: la["parent"] for la in oracle["layers"]}
            for layer in list(used):  # a parent layer is kept, nodes or not
                while parents[layer] is not None and parents[layer] not in used:
                    layer = parents[layer]
                    used.append(layer)
            # the Layer Manager's order: every fixture makes a parent layer before its children, so it is also the
            # converter's parents-first order (test_a_parent_listed_later_is_moved_before_its_child covers the other)
            order = [la["name"] for la in oracle["layers"]]
            self.assertEqual([la.name for la in desc.layers], sorted(used, key=order.index), name)
            flags = {la["name"]: (la["hidden"], la["frozen"], la["renderable"], la["parent"])
                     for la in oracle["layers"]}
            by_index = {la.index: la for la in desc.layers}

            def inherited(la, flag):  # the oracle's hidden and frozen hold for the layers below too (layers_nested)
                while la is not None:
                    if getattr(la, flag):
                        return True
                    la = by_index.get(la.parent)
                return False
            for la in desc.layers:
                parent = None if la.parent is None else names[la.parent]
                self.assertEqual((inherited(la, "hidden"), inherited(la, "frozen"), la.renderable, parent),
                                 flags[la.name], la.name)

    def test_layers_flags_organisation(self):
        desc = dict((n, d) for n, d, _o in self.cases)["layers_flags"]
        self.assertEqual([la.name for la in desc.layers], ["FixtureLayerA", "FixtureLayerB"])
        by_name = {n.name: n for n in desc.nodes}
        self.assertEqual([k for k, n in by_name.items() if n.hidden], ["FixtureHidden"])
        self.assertEqual([k for k, n in by_name.items() if not n.renderable], ["FixtureNoRender"])
        self.assertEqual([k for k, n in by_name.items() if not n.cast_shadows], ["FixtureNoCastShadow"])
        self.assertEqual([k for k, n in by_name.items() if not n.receive_shadows], ["FixtureNoReceiveShadow"])
        self.assertEqual(desc.issues, [(by_name["FixtureNoReceiveShadow"].index, conv.NO_RECEIVE)])
        self.assertEqual([k for k, n in by_name.items() if n.group_head], ["FixtureGroup"])
        head = by_name["FixtureGroup"].index
        self.assertEqual(sorted(k for k, n in by_name.items() if n.group_member),
                         sorted(k for k, n in by_name.items() if n.parent == head))
        self.assertEqual(len([n for n in desc.nodes if n.parent == head]), 2)

    def test_layers_more_organisation(self):
        """The layer flags live on the layers, not on their nodes; a parent layer without a node is kept."""
        desc = dict((n, d) for n, d, _o in self.cases)["layers_more"]
        names = {la.index: la.name for la in desc.layers}
        self.assertEqual([(la.name, la.hidden, la.frozen, la.renderable, names.get(la.parent)) for la in desc.layers],
                         [("0", False, False, True, None), ("FixtureHiddenLayer", True, False, True, None),
                          ("FixtureFrozenLayer", False, True, True, None),
                          ("FixtureNoRenderLayer", False, False, False, None),
                          ("FixtureParentLayer", False, False, True, None),
                          ("FixtureChildLayer", False, False, True, "FixtureParentLayer"),
                          ("FixtureLäyer中", False, False, True, None)])
        by_name = {n.name: n for n in desc.nodes}
        self.assertEqual([k for k, n in by_name.items() if n.hidden], ["FixtureHiddenParent"])
        self.assertEqual([k for k, n in by_name.items() if n.frozen], ["FixtureFrozen"])
        self.assertTrue(all(n.renderable for n in desc.nodes))
        self.assertEqual(by_name["FixtureVisibleChild"].parent, by_name["FixtureHiddenParent"].index)
        self.assertEqual(names[by_name["FixtureNested"].layer], "FixtureChildLayer")

    def test_layers_render_organisation(self):
        """Rendering Control By Layer: a By Layer node renders, casts and receives as its own layer says (its own
        flags off on FixtureByLayerOwnOff, a parent layer with all three off above FixtureByLayerChild); a By Object
        node on the same layer keeps its own."""
        desc = dict((n, d) for n, d, _o in self.cases)["layers_render"]
        by_name = {n.name: n for n in desc.nodes}
        got = {k: (n.renderable, n.cast_shadows, n.receive_shadows) for k, n in by_name.items()}
        self.assertEqual(got, {"FixtureByLayerNoCast": (True, False, True),
                               "FixtureByObjectOnNoCast": (True, True, True),
                               "FixtureByLayerNoReceive": (True, True, False),
                               "FixtureByLayerNoRender": (False, True, True),
                               "FixtureByObjectOnNoRender": (True, True, True),
                               "FixtureByLayerOwnOff": (True, True, True),
                               "FixtureByLayerChild": (True, True, True)})
        self.assertEqual(desc.issues, [(by_name["FixtureByLayerNoReceive"].index, conv.NO_RECEIVE)])

    def test_curves_equal_the_oracle(self):
        """Every shape node's curve: splines, points and cyclic flags as 3ds Max converts the shape, each segment's
        Bezier midpoint where 3ds Max interpolates it (straight segments included), resolution and bevel."""
        for name, desc, oracle in self.cases:
            for node, o in zip(desc.nodes, oracle["nodes"]):
                if o["shape"] is None or node.kind == conv.MESH:  # an extruded shape is a mesh
                    self.assertIsNone(node.curve)
                    continue
                label = "%s %s" % (name, node.name)
                cd = desc.curves[node.curve]
                self.assertIn(node.index, cd.users, label)
                self.assertIsNone(node.curve[1], label)  # no object offset in the fixtures: object space = curve's
                want = o["shape"]["splines"]
                self.assertEqual([(len(sp.points), sp.cyclic) for sp in cd.splines],
                                 [(len(w["knots"]), w["closed"]) for w in want], label)
                for sp, w in zip(cd.splines, want):
                    n = len(sp.points)
                    for k, knot in enumerate(w["knots"]):
                        numpy.testing.assert_allclose(numpy.asarray(sp.points[k]) / desc.meters, knot["pos"],
                                                      atol=1e-4, err_msg=label)
                        if knot["mid"] is None:
                            continue
                        j = (k + 1) % n
                        mid = (numpy.asarray(sp.points[k]) + 3 * numpy.asarray(sp.right[k]) +
                               3 * numpy.asarray(sp.left[j]) + numpy.asarray(sp.points[j])) / 8 / desc.meters
                        numpy.testing.assert_allclose(mid, knot["mid"], atol=1e-4, err_msg="%s knot %d" % (label, k))
                s = o["shape"]
                self.assertEqual(cd.resolution, conv.ADAPTIVE if s["adaptive"] else s["steps"] + 1, label)
                if s["renderable"] and s["rectangular"]:
                    self.assertEqual(cd.bevel_depth, 0.0, label)
                    x, y = s["width"] / 2 * desc.meters, s["length"] / 2 * desc.meters
                    numpy.testing.assert_allclose(sorted(numpy.hypot(*numpy.transpose(cd.section))),
                                                  [math.hypot(x, y)] * 4, rtol=1e-9, err_msg=label)
                elif s["renderable"]:
                    self.assertAlmostEqual(cd.bevel_depth, s["thickness"] / 2 * desc.meters, places=9)
                    self.assertEqual(cd.bevel_resolution, (s["sides"] - 4) // 2, label)
                    self.assertIsNone(cd.section, label)
                else:
                    self.assertEqual((cd.bevel_depth, cd.section), (0.0, None), label)

    def test_shapes_are_not_placeholders(self):
        desc = dict((n, d) for n, d, _o in self.cases)["shapes"]
        self.assertEqual([n.kind for n in desc.nodes], [conv.CURVE] * 13 + [conv.MESH])
        self.assertEqual(len(desc.curves), 13)
        line = next(n for n in desc.nodes if n.name == "FixtureLine")
        self.assertEqual(desc.curves[line.curve].bevel_resolution, 2)  # 8 sides

    def test_rectangular_sections(self):
        """FixtureSection (width 4, length 1, angle 30): the corners of 3ds Max's render mesh at its first point,
        (Y, Z) = (-1.48205, 1.43301), (1.98205, -0.566987), ..., in Blender's profile, whose x is the line's -Y."""
        desc = dict((n, d) for n, d, _o in self.cases)["shapes_more"]
        by_name = {n.name: desc.curves[n.curve] for n in desc.nodes if n.kind == conv.CURVE}
        m = desc.meters
        numpy.testing.assert_allclose(by_name["FixtureSection"].section,
                                      numpy.array([(1.48205, 1.43301), (-1.98205, -0.566987), (-1.48205, -1.43301),
                                                   (1.98205, 0.566987)]) * m, atol=1e-5 * m)
        loop = by_name["FixtureSectionLoop"].section
        numpy.testing.assert_allclose(loop, numpy.array([(1.5, 0.75), (-1.5, 0.75), (-1.5, -0.75), (1.5, -0.75)]) * m,
                                      atol=1e-12)
        self.assertEqual(sum(1 for cd in desc.curves.values() if cd.section is not None), 2)

    def test_fixture_spline_material_ids(self):
        """shapes_more: FixtureCurveIds' splines at IDs 2 and 1, FixtureCurveMixed's at 2, 1, 1 (zero-based 1 and 0);
        every other curve at ID 1."""
        desc = dict((n, d) for n, d, _o in self.cases)["shapes_more"]
        got = {n.name: [(sd.material, sd.material_ids) for sd in desc.curves[n.curve].splines]
               for n in desc.nodes if n.kind == conv.CURVE}
        self.assertEqual(got.pop("FixtureCurveIds"), [(1, (1,)), (0, (0,))])
        self.assertEqual(got.pop("FixtureCurveMixed"), [(1, (1, 0))])
        names = {n.index: n.name for n in desc.nodes}  # the mixed spline's issue comes from convert.materials
        self.assertEqual([r for i, r in desc.issues if names.get(i, "").startswith("FixtureCurve")], [])
        self.assertEqual({sp for v in got.values() for sp in v}, {(0, (0,))})

    def test_material_indices_from_the_reader(self):
        desc = dict((n, d) for n, d, _o in self.cases)["box_poly_standard"]
        md = next(iter(desc.meshes.values()))
        self.assertEqual(sorted(md.material_indices.tolist()), [0, 1, 2, 3, 4, 5])
        self.assertEqual(md.material_indices.dtype, numpy.int32)


if __name__ == "__main__":
    unittest.main()
