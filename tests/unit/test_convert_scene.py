# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/scene.py, the scene description: no Blender. The smoothing-group rule, the loop reversal
of a mirrored object offset, and every committed fixture against its 3ds Max oracle (order, parents, world
matrices, world bounding boxes, counts, shared meshes, units) and its authoring script (UV channels, smoothing
groups), the shapes' curves against the oracle's knots and segment midpoints.

    python -I -m unittest discover tests
"""
import ast
import collections
import glob
import importlib
import json
import math
import os
import sys
import types
import unittest
from unittest import mock

try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
MATRIX_TOLERANCE = 1e-4  # file units, per element (the oracle prints 6 significant digits)
BBOX_TOLERANCE = 1e-3

# A package named apart from the add-on whose path is maxdrop/: convert's relative imports of ..reader resolve,
# and maxdrop/__init__.py (which imports bpy) never runs.
_PKG = "maxdrop_convert_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
conv = importlib.import_module(_PKG + ".convert.scene")
geometry = importlib.import_module(_PKG + ".reader.geometry")
cfb = importlib.import_module(_PKG + ".reader.cfb")
reader_scene = importlib.import_module(_PKG + ".reader.scene")
shapes = importlib.import_module(_PKG + ".reader.shapes")

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
    "extrude": {"FixtureExtRect": ["UVMap"], "FixtureExtAdaptive": ["UVMap"]},
    "gamma_swatches": ["UVMap"],
    "hierarchy": [],
    "instances": ["UVMap"],
    "layers_flags": [],
    "layers_more": [],
    "layers_nested": [],
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
                     "FixtureShellSymHalf": 6 + 4, "FixtureShellSymClosed": 10, "FixtureShellSymQuarter": 3 + 2}
# extrude: the vertical edges at corner knots (one per level) and both rims of every capped outline
SHARP_EDGES_EXTRUDE = {"FixtureExtRect": 4 * 2 + 8, "FixtureExtL": 6 + 12, "FixtureExtHole": 4 + 8 + 56,
                       "FixtureExtIsland": 12 + 24, "FixtureExtOpen": 0, "FixtureExtMirror": 8 + 64,
                       "FixtureExtAdaptive": 256, "FixtureExtShapeIDs": 11 + 30, "FixtureExtShapeIDsRect": 4 + 8,
                       "FixtureUVWExtrude": 4 + 8,
                       # grid caps: as above (the circle smooth, one rim: Cap End off)
                       "FixtureExtGrid": 10 + 8 + 18, "FixtureExtGridCircle": 16,
                       # arc_pie_reverse: both rims of a pie's 23 columns and the side broken at from, the
                       # center and to in 2 segments (maxdrop-em3.111); the open arc none; the clockwise Line and
                       # the holed cap as above
                       "FixturePieRevExt": 46 + 6, "FixturePieRevWrapExt": 46 + 6, "FixturePieExt": 46 + 6,
                       "FixtureArcRevExt": 0, "FixtureClockwiseExt": 4 * 2 + 8, "FixtureHoleExt": 4 * 2 + 8 + 56}
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
# the oracle's base_class_id of the primitives MaxDrop builds (convert/primitives.py)
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
          # the plane's rim corners (auto smooth), the open box's override group (auto smooth off)
          "stack_shell": ["modifiers: Shell: auto smooth: 4 corners of the rim sharper than 45 degrees shade smooth "
                          "(3ds Max splits the rim there)",
                          "modifiers: Shell: smoothing group override (group 4) not converted: 3ds Max merges the rim "
                          "into the faces along it of that group"],
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
                              "imported",
                              "light: the modifiers of its mesh (Shell) are not applied: the emitter is the base mesh "
                              "(V-Ray emits the evaluated mesh, and in lm and W spreads the flux over that one's "
                              "area)"]}
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
                        "FixtureOrder": 0}


def _shading(node):
    """The ("shading", ...) a converted smoother adds to a node's mesh key, else None."""
    last = node.mesh[-1] if node.mesh else None
    return last if isinstance(last, tuple) and len(last) == 2 and last[0] == "shading" else None


def _oracle(path):
    with open(path[:-4] + ".oracle.json", encoding="utf-8") as f:
        return json.load(f)


def _name(path):
    return os.path.splitext(os.path.basename(path))[0]


def _world_points(node, md):
    m = numpy.asarray(node.world, dtype=numpy.float64)
    return numpy.asarray(md.positions, dtype=numpy.float64) @ m[:3, :3].T + m[:3, 3]


def _quad_strip(groups):
    """Two quads sharing the edge (1, 4): 0-1-4-3 and 1-2-5-4."""
    return ([0, 1, 4, 3, 1, 2, 5, 4], [0, 4], [4, 4], groups)


@unittest.skipIf(numpy is None, "numpy missing")
class SharpEdges(unittest.TestCase):
    def pairs(self, groups):
        return [tuple(int(v) for v in e) for e in conv.sharp_edges(*_quad_strip(groups))]

    def test_a_shared_group_keeps_the_edge_smooth(self):
        self.assertEqual(self.pairs([1, 1]), [])
        self.assertEqual(self.pairs([3, 6]), [])

    def test_no_shared_group_makes_the_shared_edge_sharp(self):
        self.assertEqual(self.pairs([1, 2]), [(1, 4)])

    def test_faces_without_a_group_meet_at_a_sharp_edge(self):
        self.assertEqual(self.pairs([0, 0]), [(1, 4)])
        self.assertEqual(self.pairs([0, 1]), [(1, 4)])

    def test_three_faces_on_one_edge(self):
        lv = [0, 1, 2, 1, 0, 3, 0, 1, 4]
        starts, totals = [0, 3, 6], [3, 3, 3]
        self.assertEqual([tuple(e) for e in conv.sharp_edges(lv, starts, totals, [1, 1, 1]).tolist()], [])
        self.assertEqual([tuple(e) for e in conv.sharp_edges(lv, starts, totals, [1, 1, 2]).tolist()], [(0, 1)])

    def test_empty_mesh(self):
        self.assertEqual(conv.sharp_edges([], [], [], []).shape, (0, 2))


@unittest.skipIf(numpy is None, "numpy missing")
class HostileEdges(unittest.TestCase):
    """A file can put any number of faces on one edge: the work stays linear."""

    def fan(self, groups):
        n = len(groups)
        lv = numpy.stack((numpy.zeros(n), numpy.ones(n), numpy.arange(2, n + 2)), axis=1).astype(numpy.int32).ravel()
        return lv, numpy.arange(0, 3 * n, 3, dtype=numpy.int32), numpy.full(n, 3, dtype=numpy.int32), groups

    def test_a_fan_on_one_edge_sharing_a_group_is_fast_and_smooth(self):
        import time
        start = time.perf_counter()
        edges = conv.sharp_edges(*self.fan(numpy.ones(100000, dtype=numpy.uint32)))
        self.assertLess(time.perf_counter() - start, 5.0)
        self.assertEqual(len(edges), 0)

    def test_a_fan_with_two_disjoint_groups_is_sharp(self):
        groups = numpy.ones(1000, dtype=numpy.uint32)
        groups[500] = 2
        self.assertEqual([tuple(e) for e in conv.sharp_edges(*self.fan(groups)).tolist()], [(0, 1)])

    def test_too_many_distinct_masks_make_the_edge_sharp(self):
        # all share group 1, all distinct
        groups = (numpy.arange(1, conv.MAX_EDGE_MASKS + 2, dtype=numpy.uint32) << 1) | 1
        self.assertGreater(len(groups), conv.MAX_EDGE_MASKS)
        self.assertEqual([tuple(e) for e in conv.sharp_edges(*self.fan(groups)).tolist()], [(0, 1)])
        few = groups[:conv.MAX_EDGE_MASKS]
        self.assertEqual(len(conv.sharp_edges(*self.fan(few))), 0)


def _sharp_edges_by_unique(lv, starts, totals, groups):
    """sharp_edges as it was before it found the runs of the sorted keys itself (numpy.unique), for the comparison."""
    lv, starts, totals = (numpy.asarray(x, dtype=numpy.int64) for x in (lv, starts, totals))
    face = numpy.repeat(numpy.arange(len(starts)), totals)
    following = numpy.arange(1, len(lv) + 1)
    following[starts + totals - 1] = starts
    lo, hi = numpy.minimum(lv, lv[following]), numpy.maximum(lv, lv[following])
    key = lo * (int(lv.max()) + 1) + hi
    order = numpy.argsort(key, kind="stable")
    key, face = key[order], face[order]
    groups = numpy.asarray(groups, dtype=numpy.uint32)
    _keys, first, counts = numpy.unique(key, return_index=True, return_counts=True)
    two = first[counts == 2]
    sharp = two[(groups[face[two]] & groups[face[two + 1]]) == 0]
    more = [s for s, n in zip(first[counts > 2], counts[counts > 2]) if conv._disjoint(groups[face[s:s + n]])]
    if more:
        sharp = numpy.sort(numpy.concatenate((sharp, numpy.asarray(more, dtype=sharp.dtype))))
    src = order[sharp]
    return numpy.stack((lo[src], hi[src]), axis=1).astype(numpy.int32)


def _valid_faces_by_unique(lv, starts, totals):
    """valid_faces as it was before it found doubled faces with a lexsort (numpy.unique(axis=0))."""
    lv, starts, totals = (numpy.asarray(x, dtype=numpy.int64) for x in (lv, starts, totals))
    keep = numpy.ones(len(starts), dtype=bool)
    for total in numpy.unique(totals):
        faces = numpy.flatnonzero(totals == total)
        rows = numpy.sort(lv[starts[faces][:, None] + numpy.arange(total)], axis=1)
        repeated = (numpy.diff(rows, axis=1) == 0).any(axis=1)
        keep[faces[repeated]] = False
        good = faces[~repeated]
        if not len(good):
            continue
        _rows, first = numpy.unique(rows[~repeated], axis=0, return_index=True)
        doubled = numpy.ones(len(good), dtype=bool)
        doubled[first] = False
        keep[good[doubled]] = False
    return keep


@unittest.skipIf(numpy is None, "numpy missing")
class SameAsUnique(unittest.TestCase):
    """sharp_edges and valid_faces give what their numpy.unique versions gave, on random meshes full of shared
    edges, doubled faces, repeated vertices and edges with many faces."""

    def meshes(self):
        rng = numpy.random.default_rng(7)
        for _ in range(200):
            nv = int(rng.integers(3, 12))
            totals = rng.integers(3, 6, size=int(rng.integers(1, 40)))
            starts = numpy.concatenate(([0], numpy.cumsum(totals)[:-1]))
            lv = rng.integers(0, nv, size=int(totals.sum())).astype(numpy.int32)
            groups = (rng.integers(0, 4, size=len(totals)) * rng.integers(0, 2, size=len(totals))).astype(numpy.uint32)
            yield lv, starts.astype(numpy.int32), totals.astype(numpy.int32), groups

    def test_valid_faces(self):
        for lv, starts, totals, _groups in self.meshes():
            self.assertEqual(conv.valid_faces(lv, starts, totals).tolist(),
                             _valid_faces_by_unique(lv, starts, totals).tolist())

    def test_sharp_edges_of_the_valid_faces(self):
        for lv, starts, totals, groups in self.meshes():
            keep = conv.valid_faces(lv, starts, totals)
            loops = numpy.repeat(keep, totals)
            lv, totals, groups = lv[loops], totals[keep], groups[keep]
            starts = numpy.concatenate(([0], numpy.cumsum(totals)[:-1])).astype(numpy.int32)
            if not len(totals):
                continue
            self.assertEqual(conv.sharp_edges(lv, starts, totals, groups).tolist(),
                             _sharp_edges_by_unique(lv, starts, totals, groups).tolist())


@unittest.skipIf(numpy is None, "numpy missing")
class InvalidFaces(unittest.TestCase):
    def test_repeated_vertex_and_doubled_faces_are_refused(self):
        # 0: good tri; 1: repeated vertex; 2: same vertex set as 0, other order; 3: good quad; 4: quad repeating 5
        lv = [0, 1, 2, 3, 3, 4, 2, 0, 1, 0, 1, 5, 4, 1, 5, 6, 5]
        keep = conv.valid_faces(lv, [0, 3, 6, 9, 13], [3, 3, 3, 4, 4])
        self.assertEqual(keep.tolist(), [True, False, False, True, False])

    def test_the_earliest_of_doubled_faces_is_kept(self):
        # 0: quad; 1: triangle; 2: face 0 turned; 3: face 1 reversed; 4: face 0 again, reversed
        lv = [4, 5, 6, 7, 0, 1, 2, 5, 6, 7, 4, 2, 1, 0, 7, 6, 5, 4]
        keep = conv.valid_faces(lv, [0, 4, 7, 11, 14], [4, 3, 4, 3, 4])
        self.assertEqual(keep.tolist(), [True, True, False, False, False])

    def test_faces_of_fewer_than_three_vertices_are_refused(self):
        keep = conv.valid_faces([0, 1, 2, 3, 3, 4], [0, 3, 3, 4], [3, 0, 1, 2])
        self.assertEqual(keep.tolist(), [True, False, False, False])

    def test_dropped_faces_keep_uvs_materials_and_groups_aligned(self):
        lv = numpy.asarray([0, 1, 2, 2, 2, 3, 1, 3, 2], dtype=numpy.int32)
        uv = geometry.MapChannel(1, numpy.arange(27, dtype=numpy.float32).reshape(9, 3),
                                 numpy.arange(9, dtype=numpy.int32))
        data = geometry.MeshData(numpy.zeros((4, 3), dtype=numpy.float32), lv,
                                 numpy.asarray([0, 3, 6], dtype=numpy.int32),
                                 numpy.asarray([1, 2, 0], dtype=numpy.uint32),
                                 numpy.asarray([4, 5, 6], dtype=numpy.uint16), {1: uv})
        md = conv.mesh_description((0, None), "m", data, None, 1.0)
        self.assertEqual(md.dropped_faces, 1)
        self.assertEqual(md.loop_vertices.tolist(), [0, 1, 2, 1, 3, 2])
        self.assertEqual(md.loop_starts.tolist(), [0, 3])
        self.assertEqual(md.material_indices.tolist(), [4, 6])
        self.assertEqual(md.sharp_faces.tolist(), [False, True])
        self.assertEqual(md.uv_layers[0][1][:, 0].tolist(), [0.0, 3.0, 6.0, 18.0, 21.0, 24.0])
        self.assertEqual([tuple(e) for e in md.sharp_edges.tolist()], [(1, 2)])


@unittest.skipIf(numpy is None, "numpy missing")
class DamagedInput(unittest.TestCase):
    def scene(self, name):
        cf = cfb.CompoundFile(os.path.join(ROOT, "tests", "fixtures", name + ".max"))
        self.addCleanup(cf.close)
        return reader_scene.Scene.from_file(cf)

    def test_refused_geometry_becomes_a_placeholder_with_an_issue(self):
        sc = self.scene("instances")
        real = conv.geometry.read_mesh

        def refuse(scene, i, check=None):
            raise geometry.GeometryError("object %d: refused" % i)

        conv.geometry.read_mesh = refuse
        try:
            desc = conv.describe(sc, 0.001)
        finally:
            conv.geometry.read_mesh = real
        self.assertEqual([n.kind for n in desc.nodes], [conv.EMPTY] * 5)
        self.assertEqual(sum(desc.placeholders.values()), 5)
        self.assertEqual(len(desc.meshes), 0)
        self.assertEqual(len(desc.issues), 2)  # once per base object: the shared one and the copy's
        self.assertTrue(all(r.startswith("geometry: ") for _n, r in desc.issues))

    def test_a_damaged_node_record_is_an_empty_and_its_children_are_still_placed(self):
        sc = self.scene("hierarchy")
        child = next(i for i in sc.node_indices if sc.node(i).name == "FixtureChild")
        sc._nodes.clear()
        real = sc.node

        def node(i):
            if i == child:
                raise reader_scene.ChunkError("damaged")
            return real(i)

        sc.node = node
        desc = conv.describe(sc, 1.0)
        by_index = {n.index: n for n in desc.nodes}
        self.assertEqual((by_index[child].kind, by_index[child].name), (conv.EMPTY, ""))
        self.assertIn((child, "node: damaged"), desc.issues)
        leaf = next(n for n in desc.nodes if n.name == "FixtureLeaf")
        self.assertEqual((leaf.parent, leaf.kind), (child, conv.MESH))

    def layered(self, parents=None, broken=()):
        """layers_flags with parent layers set by name and some layer records refused."""
        sc = self.scene("layers_flags")
        by_name = {sc.layer(i).name: i for i in sc.layer_indices}
        real = sc.layer

        def layer(i):
            if i in [by_name[b] for b in broken]:
                raise reader_scene.ChunkError("layer %d: refused" % i)
            la = real(i)
            parent = (parents or {}).get(la.name)
            if parent is None:
                return la
            return reader_scene.Layer(la.index, la.name, la.flags, la.render_flags, by_name[parent])

        sc.layer = layer
        return sc, by_name

    def test_a_parent_layer_without_nodes_is_kept_and_comes_first(self):
        sc, by_name = self.layered({"FixtureLayerB": "0"})
        desc = conv.describe(sc, 1.0)
        self.assertEqual([(la.name, la.parent) for la in desc.layers],
                         [("0", None), ("FixtureLayerA", None), ("FixtureLayerB", by_name["0"])])

    def test_a_parent_listed_later_is_moved_before_its_child(self):
        sc, by_name = self.layered({"FixtureLayerA": "FixtureLayerB"})
        desc = conv.describe(sc, 1.0)
        self.assertEqual([(la.name, la.parent) for la in desc.layers],
                         [("FixtureLayerB", None), ("FixtureLayerA", by_name["FixtureLayerB"])])

    def test_an_unreadable_layer_is_an_issue_and_its_nodes_have_none(self):
        sc, _by_name = self.layered(broken=("FixtureLayerB",))
        desc = conv.describe(sc, 1.0)
        self.assertEqual([la.name for la in desc.layers], ["FixtureLayerA"])
        lost = [n.name for n in desc.nodes if n.layer is None]
        self.assertEqual(sorted(lost), ["FixtureHidden", "FixtureNoRender"])
        layer_issues = [r for _n, r in desc.issues if r != conv.NO_RECEIVE]
        self.assertEqual(len(layer_issues), 2)
        self.assertTrue(all(r.startswith("layer: ") for r in layer_issues))

    def test_unknown_controllers_are_counted_by_class(self):
        sc = self.scene("hierarchy")
        real = conv.controllers.Transforms

        class Fake(real):
            def local(self, i):
                m = super().local(i)
                node = self.scene.node(i)
                if not any(issue.node == i for issue in self.issues):
                    self.issues.append(conv.controllers.Issue(i, node.tm, None, None, conv.controllers.UNKNOWN_CLASS))
                return m

        conv.controllers.Transforms = Fake
        try:
            desc = conv.describe(sc, 1.0)
        finally:
            conv.controllers.Transforms = real
        self.assertEqual(dict(desc.unknown_controllers), {"Position/Rotation/Scale": len(desc.nodes)})


class Curves(unittest.TestCase):
    def _shape(self, knots, closed=False, **kw):
        render = shapes.DEFAULT_RENDER._replace(**kw)
        return shapes.Shape(shapes.classids.LINE, (shapes.Spline(tuple(knots), closed),), 6, True, False, render, ())

    def test_straight_segment_and_offset(self):
        """A segment of type line gets its handles on the chord; the offset and meters apply to every handle."""
        k = shapes.Knot
        knots = [k(shapes.BEZIER, shapes.LINE, (0, 0, 0), (0, -5, 0), (0, 5, 0)),
                 k(shapes.BEZIER, shapes.CURVE, (9, 0, 0), (9, 5, 0), (9, -5, 0)),
                 k(shapes.CORNER, shapes.LINE, (9, 9, 0), (9, 9, 0), (9, 9, 0))]
        offset = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (1, 2, 3, 1))
        cd, issues = conv.curve_description("k", "n", self._shape(knots), offset, 0.5)
        sp = cd.splines[0]
        self.assertEqual(issues, [])
        self.assertEqual(sp.points, [(0.5, 1, 1.5), (5, 1, 1.5), (5, 5.5, 1.5)])
        self.assertEqual(sp.right[0], (2, 1, 1.5))  # a third of the chord, not the stored (0, 5)
        self.assertEqual(sp.left[1], (3.5, 1, 1.5))
        self.assertEqual(sp.right[1], (5, -1.5, 1.5))  # a curve segment keeps its vector
        self.assertEqual(sp.right[2], (5, 5.5, 1.5))  # open: no segment after the last knot
        self.assertEqual((cd.resolution, cd.bevel_depth), (7, 0.0))

    def test_segment_material_ids(self):
        """A spline's material IDs are its segments': the last knot of an open spline starts none, a closed one's
        does; distinct, in segment order, the first one the spline's; a spline without a segment its knot's."""
        def knots(*ids):
            return [shapes.Knot(shapes.CORNER, shapes.LINE, (float(i), 0, 0), (float(i), 0, 0), (float(i), 0, 0), m)
                    for i, m in enumerate(ids)]
        self.assertEqual(conv.segment_ids(knots(1, 1, 5), False), (1,))
        self.assertEqual(conv.segment_ids(knots(1, 1, 5), True), (1, 5))
        self.assertEqual(conv.segment_ids(knots(2, 0, 0, 2, 3), False), (2, 0))
        self.assertEqual(conv.segment_ids(knots(4), False), (4,))
        self.assertEqual(conv.segment_ids(knots(4), True), (4,))
        cd, _issues = conv.curve_description("k", "n", self._shape(knots(3, 1, 3, 9)), None, 1.0)
        self.assertEqual((cd.splines[0].material, cd.splines[0].material_ids), (3, (3, 1)))

    def test_closing_straight_segment_and_bevel(self):
        k = shapes.Knot
        knots = [k(shapes.CORNER, shapes.CURVE, (0, 0, 0), (0, 0, 0), (0, 0, 0)),
                 k(shapes.CORNER, shapes.LINE, (3, 0, 0), (3, 0, 0), (3, 0, 0))]
        cd, issues = conv.curve_description("k", "n", self._shape(knots, closed=True, renderable=True, thickness=4.0,
                                                                  sides=3), None, 1.0)
        self.assertEqual((cd.splines[0].right[1], cd.splines[0].left[0]), ((2, 0, 0), (1, 0, 0)))
        self.assertEqual((cd.bevel_depth, cd.bevel_resolution, cd.section), (2.0, 0, None))
        self.assertEqual(issues, [])

    def test_rectangular_section_off_the_plane(self):
        """A section on a curve that is not flat in XY is drawn, with an issue; width or length 0 draws none."""
        k = shapes.Knot

        def section(z, **kw):
            knots = [k(shapes.CORNER, shapes.LINE, (0, 0, 0), (0, 0, 0), (0, 0, 0)),
                     k(shapes.CORNER, shapes.LINE, (10, 0, z), (10, 0, z), (10, 0, z))]
            render = dict(renderable=True, rectangular=True, width=4.0, length=1.0)
            render.update(kw)
            return conv.curve_description("k", "n", self._shape(knots, **render), None, 1.0)

        cd, issues = section(0)
        self.assertEqual((len(cd.section), issues, cd.bevel_depth), (4, [], 0.0))
        cd, issues = section(5)
        self.assertEqual((len(cd.section), len(issues)), (4, 1))
        self.assertIn("not flat", issues[0])
        cd, issues = section(0, width=0.0)
        self.assertEqual((cd.section, cd.bevel_depth, len(issues)), (None, 0.0, 1))
        self.assertIn("not drawn", issues[0])
        cd, issues = section(0, renderable=False)
        self.assertEqual((cd.section, issues), (None, []))

    @staticmethod
    def _ngon(radius, sides, corner=0.0):
        """The splines reader.shapes draws for an NGon (inscribed, not circular)."""
        splines = shapes._ngon(shapes._Params({0: radius, 1: sides, 2: 0, 3: corner, 4: 0}), [])
        return shapes.Shape(shapes.classids.NGON, tuple(splines), 6, True, False, shapes.DEFAULT_RENDER, ())

    def test_ngon_past_single_precision_is_refused(self):
        """An NGon of radius 1e308: 3 sides gives inf and NaN, 6 sides finite doubles past the largest float32,
        a corner radius of 1e308 the same; each is refused (Blender holds curve points in single precision). The
        same NGon at radius 10 is a curve."""
        for sides, radius, corner in ((3, 1e308, 0.0), (6, 1e308, 0.0), (6, 10.0, 1e308)):
            with self.subTest(sides=sides, radius=radius, corner=corner):
                with self.assertRaises(conv.CurveError) as caught:
                    conv.curve_description("k", "n", self._ngon(radius, sides, corner), None, 1.0)
                self.assertIn("single precision", str(caught.exception))
        cd, issues = conv.curve_description("k", "n", self._ngon(10.0, 3), None, 1.0)
        self.assertEqual((len(cd.splines[0].points), issues), (3, []))

    def test_points_past_single_precision_after_offset_and_meters(self):
        """The range is checked on what Blender gets: after the offset and meters, the handles too."""
        k = shapes.Knot

        def line(x, handle=0.0):
            return self._shape([k(shapes.BEZIER, shapes.CURVE, (0, 0, 0), (0, 0, 0), (handle, 0, 0)),
                                k(shapes.BEZIER, shapes.CURVE, (x, 0, 0), (x, 0, 0), (x, 0, 0))])

        cd, _issues = conv.curve_description("k", "n", line(1e30), None, 1.0)
        self.assertEqual(cd.splines[0].points[1], (1e30, 0, 0))
        for shape, meters, offset in ((line(1e39), 1.0, None), (line(1e36), 1000.0, None),
                                      (line(1.0, handle=-1e39), 1.0, None),
                                      (line(1.0), 1.0, ((1e39, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))):
            with self.subTest(meters=meters, offset=offset is not None), self.assertRaises(conv.CurveError):
                conv.curve_description("k", "n", shape, offset, meters)

    def test_refused_curve_key_is_named_once(self):
        """Two nodes sharing a curve key that does not fit: both EMPTY, one issue (on the first), described once."""
        desc = types.SimpleNamespace(curves={}, issues=[])
        shape_of, unbuilt = {7: self._ngon(1e308, 6)}, set()
        with mock.patch.object(conv, "curve_description", wraps=conv.curve_description) as described:
            got = [conv._curve(None, desc, shape_of, unbuilt, 7, node, "n", conv.controllers.IDENTITY, 1.0)
                   for node in (3, 4)]
        self.assertEqual(got, [(conv.EMPTY, None)] * 2)
        self.assertEqual((desc.curves, len(desc.issues), desc.issues[0][0], described.call_count), ({}, 1, 3, 1))
        self.assertTrue(desc.issues[0][1].startswith("shape: not built: "))

    def test_section_or_bevel_past_single_precision_is_not_drawn(self):
        """A rectangular section of width 1e308 at a large meters factor, or a round bevel of thickness 1e308, is
        not drawn (an issue); the curve is."""
        k = shapes.Knot
        knots = [k(shapes.CORNER, shapes.LINE, (0, 0, 0), (0, 0, 0), (0, 0, 0)),
                 k(shapes.CORNER, shapes.LINE, (10, 0, 0), (10, 0, 0), (10, 0, 0))]
        cd, issues = conv.curve_description("k", "n", self._shape(knots, renderable=True, rectangular=True,
                                                                  width=1e308, length=1.0), None, 1000.0)
        self.assertEqual((cd.section, cd.bevel_depth, len(issues)), (None, 0.0, 1))
        self.assertIn("single precision", issues[0])
        self.assertEqual(cd.splines[0].points[1], (10000.0, 0, 0))
        cd, issues = conv.curve_description("k", "n", self._shape(knots, renderable=True, thickness=1e308), None,
                                            1000.0)
        self.assertEqual((cd.section, cd.bevel_depth, len(issues)), (None, 0.0, 1))
        self.assertIn("single precision", issues[0])

    @unittest.skipIf(numpy is None, "numpy missing")  # shapes.max has a box: its mesh is read with numpy
    def test_refused_curve_is_a_placeholder_named_once(self):
        """A curve refused for its range makes its nodes placeholders, its issue named on the first node of each
        curve key only."""
        path = os.path.join(ROOT, "tests", "fixtures", "shapes.max")
        fresh = conv.read(path)
        with mock.patch.object(conv, "curve_description", side_effect=conv.CurveError("its points do not fit")):
            desc = conv.read(path)
        self.assertEqual(desc.curves, {})
        users = sum(len(cd.users) for cd in fresh.curves.values())
        self.assertEqual(sum(desc.placeholders.values()) - sum(fresh.placeholders.values()), users)
        refused = [reason for _i, reason in desc.issues if reason == "shape: not built: its points do not fit"]
        self.assertEqual(len(refused), len(fresh.curves))

    @unittest.skipIf(numpy is None, "numpy missing")  # shapes.max has a box: its mesh is read with numpy
    def test_refused_shape_is_a_placeholder_with_an_issue(self):
        path = os.path.join(ROOT, "tests", "fixtures", "shapes.max")
        with mock.patch.object(shapes, "read_shape", side_effect=shapes.ShapeError("object 1 (Line): damaged")):
            desc = conv.read(path)
        self.assertEqual(desc.curves, {})
        self.assertEqual(sum(desc.placeholders.values()), 13)
        self.assertEqual(len(desc.issues), 13)
        self.assertTrue(all(reason.startswith("shape: ") for _i, reason in desc.issues))


class Shear(unittest.TestCase):
    def test_rotation_and_axis_scale_are_not_shear(self):
        c, s = 0.6, 0.8
        self.assertFalse(conv.sheared(((2 * c, 2 * s, 0, 0), (-3 * s, 3 * c, 0, 0), (0, 0, -1, 0), (5, 6, 7, 1))))

    def test_shear_is_found(self):
        self.assertTrue(conv.sheared(((1, 0, 0, 0), (0.5, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))))

    @unittest.skipIf(numpy is None, "numpy missing")
    def test_a_sheared_node_is_flagged_not_reported(self):
        sc = DamagedInput.scene(self, "hierarchy")
        real = conv.controllers.Transforms
        target = sc.walk()[1]

        class Fake(real):
            def local(self, i):
                m = super().local(i)
                if i != target:
                    return m
                return ((m[0][0], m[0][1], m[0][2], 0.0), (m[1][0] + 0.5 * m[0][0], m[1][1] + 0.5 * m[0][1],
                                                           m[1][2] + 0.5 * m[0][2], 0.0), m[2], m[3])

        conv.controllers.Transforms = Fake
        try:
            desc = conv.describe(sc, 1.0)
        finally:
            conv.controllers.Transforms = real
        self.assertEqual([n.index for n in desc.nodes if n.sheared], [target])
        self.assertFalse([r for _n, r in desc.issues if "shear" in r], desc.issues)


@unittest.skipIf(numpy is None, "numpy missing")
class DescribeCancel(unittest.TestCase):
    """describe(cancel=): the check is asked once per node of each walk, and inside a large mesh; the first True
    ends it with Cancelled at once (the modal import's Esc during reading), keeping nothing; the Scene stays
    usable."""

    @staticmethod
    def tripping(after):
        calls = []

        def cancel():
            calls.append(None)
            return len(calls) > after
        return cancel, calls

    @staticmethod
    def summary(desc):
        return [(n.index, n.name, n.kind, n.mesh) for n in desc.nodes], sorted(desc.meshes, key=repr)

    def test_a_tripped_check_raises_at_once_and_keeps_nothing(self):
        import gc

        def alive():  # other tests may keep descriptions of their own
            gc.collect()
            return {id(o) for o in gc.get_objects() if isinstance(o, conv.SceneDescription)}

        sc = DamagedInput.scene(self, "hierarchy")
        before = alive()
        nodes = len(sc.walk())
        self.assertGreater(nodes, 3)
        for after in (0, 2, nodes, nodes + 2):  # in the first walk, at its end, in the second walk
            cancel, calls = self.tripping(after)
            with self.assertRaises(conv.Cancelled):
                conv.describe(sc, 1.0, cancel=cancel)
            self.assertEqual(len(calls), after + 1)
        self.assertEqual(alive() - before, set())
        self.assertFalse(issubclass(conv.Cancelled, ValueError))  # ops reports a ValueError as an unreadable file

    def test_a_check_that_never_trips_changes_nothing(self):
        sc = DamagedInput.scene(self, "hierarchy")
        fresh = self.summary(conv.describe(DamagedInput.scene(self, "hierarchy"), 1.0))
        cancel, calls = self.tripping(1)
        with self.assertRaises(conv.Cancelled):
            conv.describe(sc, 1.0, cancel=cancel)
        cancel, calls = self.tripping(10 ** 9)
        self.assertEqual(self.summary(conv.describe(sc, 1.0, cancel=cancel)), fresh)
        self.assertEqual(len(calls), 2 * len(sc.walk()))
        self.assertEqual(self.summary(conv.describe(sc, 1.0)), fresh)

    def test_the_check_is_asked_inside_a_large_mesh(self):
        """With reader.geometry.CHECK_EVERY at 1 every mesh is large: the check is also asked inside a node, in the
        Editable Poly's record loops and between the passes of mesh_description (an extrusion's too); tripped at any
        of those calls, describe ends with Cancelled, keeping nothing."""
        import gc

        def alive():
            gc.collect()
            return {id(o) for o in gc.get_objects() if isinstance(o, conv.SceneDescription)}

        for name in ("box_poly_standard", "extrude"):
            sc = DamagedInput.scene(self, name)
            nodes = len(sc.walk())
            fresh = self.summary(conv.describe(DamagedInput.scene(self, name), 1.0))
            cancel, calls = self.tripping(10 ** 9)
            conv.describe(sc, 1.0, cancel=cancel)
            self.assertEqual(len(calls), 2 * nodes)  # a small mesh: once per node and walk
            before = alive()
            real_read, in_reader = geometry.read_mesh, []

            def reading(scene, i, check=None):  # counts the calls the reader itself makes
                def counted():
                    in_reader.append(None)
                    check()
                return real_read(scene, i, None if check is None else counted)

            with mock.patch.object(geometry, "CHECK_EVERY", 1), mock.patch.object(geometry, "read_mesh", reading):
                cancel, calls = self.tripping(10 ** 9)
                self.assertEqual(self.summary(conv.describe(sc, 1.0, cancel=cancel)), fresh)
                total = len(calls)
                self.assertGreater(total, 2 * nodes + len(in_reader), name)  # mesh_description asks it too
                if name == "box_poly_standard":  # an Editable Poly: its record loops ask it
                    self.assertGreater(len(in_reader), 0)
                for after in range(nodes, total):  # from the second walk's first node to the last call
                    cancel, calls = self.tripping(after)
                    with self.subTest(fixture=name, trip=after):
                        with self.assertRaises(conv.Cancelled):
                            conv.describe(sc, 1.0, cancel=cancel)
                        self.assertEqual(len(calls), after + 1)
            self.assertEqual(alive() - before, set())
            self.assertEqual(self.summary(conv.describe(sc, 1.0)), fresh)


@unittest.skipIf(numpy is None, "numpy missing")
class MirroredOffset(unittest.TestCase):
    def data(self):
        lv, starts, _totals, groups = _quad_strip([1, 2])
        uv = geometry.MapChannel(1, numpy.arange(24, dtype=numpy.float32).reshape(8, 3),
                                 numpy.arange(8, dtype=numpy.int32))
        return geometry.MeshData(numpy.zeros((6, 3), dtype=numpy.float32), numpy.asarray(lv, dtype=numpy.int32),
                                 numpy.asarray(starts, dtype=numpy.int32), numpy.asarray(groups, dtype=numpy.uint32),
                                 numpy.zeros(2, dtype=numpy.uint16), {1: uv})

    def test_negative_determinant_reverses_every_polygon_with_its_uvs(self):
        mirror = ((-1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (2.0, 0.0, 0.0, 1.0))
        md = conv.mesh_description((0, mirror), "m", self.data(), mirror, 0.5)
        self.assertEqual(md.loop_vertices.tolist(), [3, 4, 1, 0, 4, 5, 2, 1])
        self.assertEqual(md.uv_layers[0][1][:, 0].tolist(), [9.0, 6.0, 3.0, 0.0, 21.0, 18.0, 15.0, 12.0])
        self.assertEqual(md.positions[0].tolist(), [1.0, 0.0, 0.0])  # (0 * -1 + 2) * 0.5
        self.assertEqual([tuple(e) for e in md.sharp_edges.tolist()], [(1, 4)])

    def test_positive_offset_keeps_the_loop_order(self):
        shift = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 3.0, 1.0))
        md = conv.mesh_description((0, shift), "m", self.data(), shift, 1.0)
        self.assertEqual(md.loop_vertices.tolist(), [0, 1, 4, 3, 1, 2, 5, 4])
        self.assertEqual(md.positions[:, 2].tolist(), [3.0] * 6)


class Matrices(unittest.TestCase):
    def test_reader_matrix_becomes_blender_convention_with_scaled_translation(self):
        m = ((0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 2.0, 0.0), (10.0, 20.0, 30.0, 1.0))
        self.assertEqual(conv.blender_matrix(m, 0.01),
                         ((0.0, -1.0, 0.0, 0.1), (1.0, 0.0, 0.0, 0.2), (0.0, 0.0, 2.0, 0.3), (0.0, 0.0, 0.0, 1.0)))

    def test_determinant_sign(self):
        self.assertGreater(conv.determinant3(conv.blender_matrix(((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0),
                                                                  (0, 0, 0, 1)))), 0)
        self.assertLess(conv.determinant3(((-1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))), 0)

    def test_meters_must_be_positive(self):
        for bad in (0.0, -1.0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                conv.describe(None, bad)


def _run_py_table(name):
    """A module-level table of tests/blender/run.py, which imports bpy: read from its source."""
    path = os.path.join(ROOT, "tests", "blender", "run.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets):
            return ast.literal_eval(stmt.value)
    raise AssertionError("no %s in tests/blender/run.py" % name)


def _uv_layers(fixture, mesh):
    """UV_LAYERS of one mesh: a fixture's list, or its table per mesh (a mesh not in a plain dict has none)."""
    want = UV_LAYERS[fixture]
    if isinstance(want, collections.defaultdict):
        return want[mesh]
    return want.get(mesh, []) if isinstance(want, dict) else want


def _extruded_nodes():
    """(fixture, node name) of every oracle node tests/blender/run.py's check_extruded runs on: a shape under an
    Extrude (an Extrude that is off leaves no eval_verts; test_counts_equal_the_oracle holds that rule to the node
    kinds). The tables are keyed by node name: an extruded object with instances would need its mesh's name."""
    return [(_name(p), o["name"]) for p in FIXTURES for o in _oracle(p)["nodes"]
            if o["shape"] is not None and o["eval_verts"] is not None]


class LookAt(unittest.TestCase):
    def test_track_to_of_each_look_at(self):
        look_at = importlib.import_module(_PKG + ".reader.controllers").LookAt
        describe = conv.look_at_description
        self.assertIsNone(describe(None))
        self.assertIsNone(describe(look_at(None, 2, False, 0.0, False)))  # aims at the origin: nothing to track
        self.assertEqual(describe(look_at(7, 2, False, 0.0, False)),
                         conv.LookAtDescription(7, "TRACK_NEGATIVE_Z", "UP_Y", False, None))
        self.assertEqual(describe(look_at(7, 2, True, 0.0, True)),
                         conv.LookAtDescription(7, "TRACK_Z", "UP_Y", True, None))
        self.assertEqual(describe(look_at(7, 0, False, 0.0, False)).track, "TRACK_NEGATIVE_X")
        self.assertEqual(describe(look_at(7, 0, True, 0.0, False)).track, "TRACK_X")
        for look, reason in ((look_at(7, 1, False, 0.0, False), conv.NO_TRACK_AXIS),
                             (look_at(7, 1, True, 0.0, False), conv.NO_TRACK_AXIS),
                             (look_at(7, 2, False, 0.1, False), conv.NO_TRACK_ROLL)):
            self.assertEqual(describe(look), conv.LookAtDescription(7, None, None, False, reason))

    @unittest.skipIf(numpy is None, "numpy missing")  # lookat.max has boxes: their meshes are built with numpy
    def test_lookat_fixture(self):
        desc = conv.read(os.path.join(ROOT, "tests", "fixtures", "lookat.max"))
        index = {n.index: n.name for n in desc.nodes}
        looks = {n.name: (index[n.look_at.target], n.look_at.track, n.look_at.up, n.look_at.target_z,
                          n.look_at.reason) for n in desc.nodes if n.look_at is not None}
        self.assertEqual(looks, {  # the boxes with a LookAt Constraint have none
            "FixtureCam": ("FixtureCam.Target", "TRACK_NEGATIVE_Z", "UP_Y", False, None),
            "FixtureCamRoll": ("FixtureCamRoll.Target", None, None, False, conv.NO_TRACK_ROLL),
            "FixtureCamDown": ("FixtureCamDown.Target", "TRACK_NEGATIVE_Z", "UP_Y", False, None),
            "FixtureSpot": ("FixtureSpot.Target", "TRACK_NEGATIVE_Z", "UP_Y", False, None),
            "FixtureCamChild": ("FixtureCamChild.Target", "TRACK_NEGATIVE_Z", "UP_Y", False, None),
            "FixtureLooker": ("FixtureAim", "TRACK_X", "UP_Y", True, None),
            "FixtureLookerY": ("FixtureAim", None, None, False, conv.NO_TRACK_AXIS)})
        targets = [n for n in desc.nodes if n.name.endswith(".Target")]
        self.assertEqual([(n.kind, n.class_name) for n in targets], [(conv.EMPTY, "Target")] * 5)


class FixtureTables(unittest.TestCase):
    """Every committed fixture has an entry in the per-fixture tables, here and in tests/blender/run.py, and every
    extruded object one in run.py's per-object extrude tables, so a new fixture or object fails the plain suite
    instead of only the Blender run."""

    def _same_names(self, table, where):
        names = {_name(p) for p in FIXTURES}
        self.assertTrue(names)
        self.assertEqual(sorted(names - set(table)), [], "fixtures without an entry in " + where)
        self.assertEqual(sorted(set(table) - names), [], "entries without a fixture in " + where)

    def test_uv_layers_lists_every_fixture(self):
        self._same_names(UV_LAYERS, "UV_LAYERS of tests/unit/test_convert_scene.py")

    def test_blender_run_uv_layers_lists_every_fixture(self):
        self._same_names(_run_py_table("UV_LAYERS"), "UV_LAYERS of tests/blender/run.py")

    def test_blender_run_extrude_tables_list_every_extruded_object(self):
        nodes = _extruded_nodes()
        names = {n for _f, n in nodes}
        self.assertTrue(names)
        self.assertEqual(len(names), len(nodes), "extruded node names repeat across fixtures: " + str(nodes))
        for table in ("EXTRUDE_EULER", "EXTRUDE_SHARP_EDGES"):  # indexed by check_extruded
            keys = set(_run_py_table(table))
            self.assertEqual(sorted(names - keys), [], "extruded objects without an entry in %s of "
                             "tests/blender/run.py" % table)
            self.assertEqual(sorted(keys - names), [], "entries without an extruded object in %s of "
                             "tests/blender/run.py" % table)
        self.assertEqual(_run_py_table("EXTRUDE_SHARP_EDGES"), SHARP_EDGES_EXTRUDE,
                         "EXTRUDE_SHARP_EDGES of tests/blender/run.py differs from SHARP_EDGES_EXTRUDE")
        uv = _run_py_table("EXTRUDE_UV_LAYERS")  # read with .get(name, []): no entry is no UV layer
        self.assertEqual(sorted(set(uv) - names), [], "entries without an extruded object in EXTRUDE_UV_LAYERS "
                         "of tests/blender/run.py")
        for fixture, name in nodes:
            self.assertEqual(uv.get(name, []), _uv_layers(fixture, name),
                             "%s: EXTRUDE_UV_LAYERS of tests/blender/run.py differs from UV_LAYERS" % name)


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
                    elif extruded or primitive:  # 3ds Max's counts are of triangles
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


@unittest.skipIf(numpy is None, "numpy missing")
class MeshRange(unittest.TestCase):
    """Stored mesh positions past single precision (offset and meters applied), inf or NaN: the mesh is refused,
    its nodes placeholders with an issue, as a curve or a primitive; UVs that are not numbers become 0."""

    @staticmethod
    def data(corner=(1.0, 0.0, 0.0), uv=None):
        """A MeshData of one triangle, its second vertex at corner (float32, as reader.geometry stores it)."""
        positions = numpy.asarray([(0.0, 0.0, 0.0), corner, (0.0, 1.0, 0.0)], dtype=numpy.float32)
        uvw = numpy.zeros((3, 3), dtype=numpy.float32) if uv is None else numpy.asarray(uv, dtype=numpy.float32)
        maps = {1: geometry.MapChannel(1, uvw, numpy.arange(3, dtype=numpy.int32))}
        return geometry.MeshData(positions, numpy.arange(3, dtype=numpy.int32), numpy.zeros(1, dtype=numpy.int32),
                                 numpy.ones(1, dtype=numpy.uint32), numpy.zeros(1, dtype=numpy.uint16), maps)

    def test_positions_that_do_not_fit_are_refused(self):
        big = ((1e39, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
        for corner, offset, meters in (((float("nan"), 0.0, 0.0), None, 1.0), ((float("inf"), 0.0, 0.0), None, 1.0),
                                       ((1e36, 0.0, 0.0), None, 1000.0), ((1.0, 0.0, 0.0), big, 1.0)):
            with self.subTest(corner=corner, meters=meters, offset=offset is not None):
                with self.assertRaises(conv.MeshError) as caught:
                    conv.mesh_description((0, offset), "m", self.data(corner), offset, meters)
                self.assertIn("single precision", str(caught.exception))
        md = conv.mesh_description((0, None), "m", self.data((1e30, 0.0, 0.0)), None, 1.0)
        self.assertEqual(md.positions[1, 0], numpy.float32(1e30))
        self.assertTrue(numpy.isfinite(md.positions).all())

    def test_uvs_that_are_not_numbers_become_zero(self):
        uv = [(0.25, float("nan"), 7.0), (float("inf"), 0.5, float("nan")), (1.0, 1.0, 0.0)]
        data = self.data(uv=uv)
        md = conv.mesh_description((0, None), "m", data, None, 1.0)
        self.assertEqual(md.uv_layers[0][1].tolist(), [[0.25, 0.0], [0.0, 0.5], [1.0, 1.0]])
        self.assertEqual(md.zeroed_uvs, 2)  # the w coordinate is dropped, not counted
        self.assertTrue(numpy.isnan(data.maps[1].uvw[0, 1]))  # the reader's array is not written
        self.assertEqual(conv.mesh_description((0, None), "m", self.data(), None, 1.0).zeroed_uvs, 0)

    def scene(self, name):
        cf = cfb.CompoundFile(os.path.join(ROOT, "tests", "fixtures", name + ".max"))
        self.addCleanup(cf.close)
        return reader_scene.Scene.from_file(cf)

    def described(self, name, meters, corner, uv=None):
        """The fixture described with every stored mesh replaced by self.data(corner, uv)."""
        sc = self.scene(name)
        with mock.patch.object(conv.geometry, "read_mesh", lambda scene, i, check=None: self.data(corner, uv)):
            return conv.describe(sc, meters)

    def test_a_refused_mesh_is_a_placeholder_named_once_per_key(self):
        """instances: four nodes share one base object, a copy has its own; every node an EMPTY placeholder, one
        issue per mesh key (the shared one and the copy's), no mesh, no modifier or UV issue."""
        for corner, meters in (((float("nan"), 0.0, 0.0), 1.0), ((1e36, 0.0, 0.0), 1000.0)):
            with self.subTest(corner=corner, meters=meters):
                desc = self.described("instances", meters, corner)
                self.assertEqual([n.kind for n in desc.nodes], [conv.EMPTY] * 5)
                self.assertEqual(sum(desc.placeholders.values()), 5)
                self.assertEqual(desc.meshes, {})
                self.assertEqual(len(desc.issues), 2)
                self.assertTrue(all(r.startswith("geometry: not built: ") and "single precision" in r
                                    for _n, r in desc.issues), desc.issues)
        desc = self.described("instances", 1.0, (1e30, 0.0, 0.0))
        self.assertEqual([n.kind for n in desc.nodes], [conv.MESH] * 5)
        self.assertEqual(desc.issues, [])

    def test_zeroed_uvs_are_named_once_per_key(self):
        desc = self.described("instances", 1.0, (1.0, 0.0, 0.0), uv=[(float("nan"), 0, 0), (0, 0, 0), (0, 0, 0)])
        self.assertEqual([n.kind for n in desc.nodes], [conv.MESH] * 5)
        self.assertEqual([r for _n, r in desc.issues], ["geometry: 1 UV coordinates that are not numbers set to 0"]
                         * 2)
        desc = self.described("vray_mesh_light", 0.001, (1.0, 0.0, 0.0), uv=[(float("nan"), 0, 0), (0, 0, 0),
                                                                             (0, 0, 0)])
        zeroed = [i for i, r in desc.issues if r == "geometry: 1 UV coordinates that are not numbers set to 0"]
        self.assertEqual(len(zeroed), len(desc.meshes))  # the mesh and the three emitters, once each
        self.assertEqual(sorted(zeroed), sorted(md.users[0] for md in desc.meshes.values()))

    def test_a_mesh_light_whose_mesh_does_not_fit_is_not_built(self):
        """vray_mesh_light at meters 1000 with every mesh at 1e36: the mesh light's mesh objects are refused
        (_mesh_of), the emitters not built, an issue on each; describe does not raise."""
        desc = self.described("vray_mesh_light", 1000.0, (1e36, 0.0, 0.0))
        self.assertEqual(desc.meshes, {})
        self.assertEqual(desc.emitters, {})
        self.assertNotIn(conv.MESH, [n.kind for n in desc.nodes])
        unbuilt = [r for _n, r in desc.issues if r.startswith("light: not built: its mesh cannot be read: ")]
        self.assertEqual(len(unbuilt), 3)
        self.assertTrue(all("single precision" in r for r in unbuilt), unbuilt)

    def test_a_mesh_light_refused_after_its_offset_is_not_built(self):
        """A refusal raised once the light node's offset is applied (in _emitter) costs the emitter, not the
        import: no mesh or emitter written, a light issue on each of its nodes."""
        sc = self.scene("vray_mesh_light")
        real = conv.mesh_description

        def refuse(key, *args, **kwargs):
            if key[0] == conv.EMITTER:
                raise conv.MeshError("its points do not fit single precision")
            return real(key, *args, **kwargs)

        with mock.patch.object(conv, "mesh_description", refuse):
            desc = conv.describe(sc, 0.001)
        self.assertEqual(desc.emitters, {})
        self.assertFalse(any(k[0] == conv.EMITTER for k in desc.meshes if isinstance(k, tuple)))
        emitters = [n for n in desc.nodes if n.name.startswith("FixtureEmitter") and n.name != "FixtureEmitterSource"]
        self.assertEqual([n.kind for n in emitters], [conv.EMPTY] * 4)
        refused = [r for _n, r in desc.issues if r == "light: not built: its points do not fit single precision"]
        self.assertEqual(len(refused), 3)

    def test_a_refused_mesh_converts_no_modifier(self):
        """stack_convert with FixtureTurboOne's mesh refused: that node a placeholder without converted modifiers or
        their issues, its TurboSmooth taken back from the modifiers whose issues were named (told); the others
        as before."""
        sc = self.scene("stack_convert")
        fresh = conv.describe(sc, 0.001)
        turbo = next(n for n in fresh.nodes if n.name == "FixtureTurboOne")
        refused_base = turbo.mesh[0]
        real = conv.geometry.read_mesh

        def read(scene, i, check=None):
            return self.data((float("nan"), 0.0, 0.0)) if i == refused_base else real(scene, i, check)

        with mock.patch.object(conv.geometry, "read_mesh", read), \
                mock.patch.object(conv, "_converted", wraps=conv._converted) as converted:
            desc = conv.describe(self.scene("stack_convert"), 0.001)
        told = converted.call_args_list[0].args[4]
        node = next(n for n in desc.nodes if n.name == "FixtureTurboOne")
        self.assertEqual((node.kind, node.converted, node.applied), (conv.EMPTY, (), ()))
        self.assertNotIn(turbo.converted[0].index, told)
        self.assertTrue(all(m.index in told for n in fresh.nodes if n.name != "FixtureTurboOne"
                            for m in n.converted))
        self.assertEqual([r for i, r in desc.issues if i == node.index],
                         ["geometry: not built: its points do not fit single precision (Blender's meshes hold no "
                          "larger value)"])
        others = [(n.name, n.kind, n.converted) for n in desc.nodes if n.name != "FixtureTurboOne"]
        self.assertEqual(others, [(n.name, n.kind, n.converted) for n in fresh.nodes if n.name != "FixtureTurboOne"])

    def test_a_refused_extrusion_falls_back_to_its_curve(self):
        """extrude with every extruded mesh refused: each extruded node a curve (as when its Extrude cannot be
        read), one issue per mesh key before its maps."""
        path = os.path.join(ROOT, "tests", "fixtures", "extrude.max")
        fresh = conv.read(path)
        extruded = {n.index: n.mesh[:3] for n in fresh.nodes if n.kind == conv.MESH and "Extrude" in n.applied}
        self.assertTrue(extruded)
        with mock.patch.object(conv, "_positions", side_effect=conv.MeshError("its points do not fit")):
            desc = conv.read(path)
        self.assertEqual({n.kind for n in desc.nodes if n.index in extruded}, {conv.CURVE})
        refused = [i for i, r in desc.issues if r == "extrude: not made: its points do not fit"]
        self.assertEqual(len(refused), len(set(extruded.values())))
        self.assertTrue(set(refused) <= set(extruded))


if __name__ == "__main__":
    unittest.main()
