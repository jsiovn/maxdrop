# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/cameras.py. No Blender.

Every camera of every fixture against its oracle: the horizontal field of view 3ds Max renders with (the oracle's
EvalCameraState, docs/ORACLE.md) within 0.05 degrees. The cameras fixture (tools/fixtures/cameras.ms) against what its
script sets: sensor, lens, shift, clipping, orthographic width, the render size and the scene camera (the oracle's
render camera). The rules against values 3ds Max computed while probing (docs/FORMAT.md, "Cameras"); hand-made
values, blocks and chunks for the issues and damaged input.
"""
import importlib
import json
import math
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

_PKG = "maxdrop_lights_test"  # the package test_lights.py makes: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
cameras = importlib.import_module(_PKG + ".convert.cameras")
report = importlib.import_module(_PKG + ".convert.report")
cfb = importlib.import_module(_PKG + ".reader.cfb")
classids = importlib.import_module(_PKG + ".reader.classids")
pblock = importlib.import_module(_PKG + ".reader.pblock")
try:
    import numpy  # noqa: F401  convert.scene needs it for meshes
    conv = importlib.import_module(_PKG + ".convert.scene")
except ImportError:
    conv = None

C = cameras
FOV_TOLERANCE = 0.05  # degrees


def physical(**changes):
    v = {C.CLASS: C.PHYSICAL, "ortho": False}
    v.update({name: default for name, (_pid, default) in C._PHYSICAL.items()})
    v.update(changes)
    return v


def vray(**changes):
    v = {C.CLASS: C.VRAY, "ortho": False, "breathing": 1.0}
    v.update({name: default for name, (_pid, default) in C._VRAY.items()})
    v.update(changes)
    return v


def standard(family=C.FREE, **changes):
    v = {C.CLASS: family, "ortho": False, "clip": False}
    v.update({name: default for name, (_index, default) in C._OLD.items()})
    v.update(changes)
    return v


def degrees(values, mm=1.0, target=None):
    return math.degrees(C.horizontal_fov(values, mm, target))


class Rules(unittest.TestCase):
    """Fields of view 3ds Max 2020 reported (Physical's fov, EvalCameraState) while probing."""

    def test_physical_lens_breathing(self):
        self.assertAlmostEqual(degrees(physical()), 48.112, places=3)  # 40 mm at 5000 mm, breathing 1
        self.assertAlmostEqual(degrees(physical(breathing=0.5)), 48.2832, places=3)
        self.assertAlmostEqual(degrees(physical(breathing=0.0)), 48.4555, places=3)
        self.assertAlmostEqual(degrees(physical(target_distance=1000.0)), 46.7287, places=3)
        self.assertAlmostEqual(degrees(physical(target_distance=1000.0, zoom=1.5)), 32.1328, places=3)
        self.assertAlmostEqual(degrees(physical(specify_focus=1, focus=2000.0)), 47.595, places=3)

    def test_the_focus_distance_is_in_file_units(self):
        # 100 cm = 1000 mm: as 1000 in a millimeter scene
        self.assertAlmostEqual(degrees(physical(target_distance=100.0), mm=10.0), 46.7287, places=3)
        self.assertAlmostEqual(degrees(vray(target_distance=100.0), mm=10.0), 46.7287, places=3)

    def test_a_specified_fov_takes_no_zoom_or_breathing(self):
        self.assertAlmostEqual(degrees(physical(specify_fov=1, fov_degrees=70.0, zoom=1.5)), 70.0)
        self.assertAlmostEqual(degrees(vray(specify_fov=1, fov_degrees=60.0, zoom=1.5)), 60.0)

    def test_vray_renders_the_focused_image_distance(self):
        self.assertAlmostEqual(degrees(vray()), 39.5977, places=3)  # 40 mm at the default 200 mm
        self.assertAlmostEqual(degrees(vray(target_distance=1000.0)), 46.7287, places=3)
        self.assertAlmostEqual(degrees(vray(target_distance=100000.0)), 48.4383, places=3)

    def test_a_targeted_camera_focuses_at_its_target(self):
        values = physical(targeted=1, target_distance=2376.92, focal=24.0)
        self.assertAlmostEqual(degrees(values, target=2922.33), 73.2867, places=3)
        self.assertAlmostEqual(degrees(physical(targeted=0, target_distance=2922.33, focal=24.0), target=10.0),
                               73.2867, places=3)

    def test_a_focus_inside_the_focal_length_takes_no_breathing(self):
        issues = []
        fov = C.horizontal_fov(physical(target_distance=30.0), 1.0, None, issues)
        self.assertAlmostEqual(math.degrees(fov), 48.4555, places=3)
        self.assertEqual(issues, [C.NO_FOCUS % (30.0, 40.0)])

    def test_lens_sensor_and_shift(self):
        cd, issues = C.describe("k", "Cam", physical(specify_fov=1, fov_degrees=90.0, shift_x=0.1, shift_y=-0.15))
        self.assertEqual(issues, [])
        self.assertAlmostEqual(cd.lens, 18.0)
        self.assertEqual((cd.sensor, cd.shift_x, cd.shift_y, cd.kind), (36.0, -0.1, 0.15, C.PERSP))
        cd, _issues = C.describe("k", "Cam", standard(fov=math.radians(60.0)))
        self.assertAlmostEqual(cd.lens, 18.0 / math.tan(math.radians(30.0)))
        self.assertEqual((cd.sensor, cd.shift_x, cd.clip_start), (36.0, 0.0, None))

    def test_orthographic_width(self):
        cd, _issues = C.describe("k", "Cam", standard(fov=math.radians(45.0), ortho=True, target_distance=2500.0),
                                 meters=0.001)
        self.assertEqual(cd.kind, C.ORTHO)
        self.assertAlmostEqual(cd.ortho_scale, 2 * 2.5 * math.tan(math.radians(22.5)))
        cd, _issues = C.describe("k", "Cam", standard(C.TARGET, fov=math.radians(50.0), ortho=True), meters=0.001,
                                 target=4000.0)
        self.assertAlmostEqual(cd.ortho_scale, 8.0 * math.tan(math.radians(25.0)))
        self.assertTrue(C.uses_target(standard(ortho=True)))
        self.assertFalse(C.uses_target(standard()))
        self.assertTrue(C.uses_target(vray()))
        self.assertFalse(C.uses_target(vray(specify_fov=1)))

    def test_clipping_in_meters(self):
        cd, _issues = C.describe("k", "Cam", standard(clip=True, near=120.0, far=4500.0), meters=0.001)
        self.assertAlmostEqual(cd.clip_start, 0.12)
        self.assertAlmostEqual(cd.clip_end, 4.5)
        cd, _issues = C.describe("k", "Cam", vray(clip=1, near=0.0, far=0.0))
        self.assertEqual(cd.clip_start, C.MIN_CLIP)
        self.assertGreater(cd.clip_end, cd.clip_start)

    def test_issues(self):
        _cd, issues = C.describe("k", "Cam", physical(dof=1, tilt_x=2.0, distortion=1))
        self.assertEqual(issues, [C.TILT % (2.0, 0.0), C.DOF, C.DISTORTION])
        _cd, issues = C.describe("k", "Cam", vray(exposure=0, distortion=0.0))
        self.assertEqual(issues, [])
        _cd, issues = C.describe("k", "Cam", vray())
        self.assertEqual(issues, [C.EXPOSURE])
        _cd, issues = C.describe("k", "Cam", standard(multipass=1))
        self.assertEqual(issues, [C.MULTIPASS])

    def test_out_of_range_values_are_kept_in_blenders_range(self):
        cd, issues = C.describe("k", "Cam", standard(fov=math.radians(179.9)))
        self.assertEqual(cd.lens, C.MIN_LENS)
        self.assertTrue(issues and issues[0].startswith("its field of view (179.9 degrees) needs a lens of "), issues)
        cd, _issues = C.describe("k", "Cam", standard(fov=math.radians(0.1)))  # past Blender's 5000 mm slider: kept
        self.assertAlmostEqual(cd.lens, 18.0 / math.tan(math.radians(0.05)), places=3)
        self.assertEqual(_issues, [])
        cd, issues = C.describe("k", "Cam", standard(fov=0.0))
        self.assertAlmostEqual(math.degrees(cd.fov), 45.0)
        self.assertEqual(len(issues), 1)
        cd, issues = C.describe("k", "Cam", physical(film=0.5, specify_fov=1, fov_degrees=40.0))
        self.assertEqual((cd.sensor, issues), (C.MIN_SENSOR, [C.SENSOR % (0.5, 1.0)]))
        cd, issues = C.describe("k", "Cam", physical(film=float("inf"), specify_fov=1, fov_degrees=40.0))
        self.assertEqual((cd.sensor, issues), (C.STANDARD_SENSOR, [C.SENSOR % (float("inf"), 36.0)]))
        cd, issues = C.describe("k", "Cam", physical(focal=0.0))  # no focal length: no division by zero
        self.assertAlmostEqual(math.degrees(cd.fov), 45.0)
        self.assertEqual(issues, [C.NO_LENS % (0.0, 1.0)])
        cd, issues = C.describe("k", "Cam", vray(zoom=-2.0))
        self.assertEqual(issues, [C.NO_LENS % (40.0, -2.0), C.EXPOSURE])
        cd, issues = C.describe("k", "Cam", standard(C.TARGET, ortho=True))  # a target camera without its target
        self.assertEqual((cd.kind, cd.ortho_scale, issues), (C.ORTHO, 1.0, [C.NO_TARGET]))
        cd, issues = C.describe("k", "Cam", standard(ortho=True, target_distance=0.0))
        self.assertEqual((cd.kind, cd.ortho_scale, issues), (C.ORTHO, 1.0, [C.NO_WIDTH % (0.0,)]))


class _Chunk:
    def __init__(self, children=(), cid=0, payload=b""):
        self.id, self.children, self.payload = cid, list(children), payload
        self.container = bool(children) or not payload
        self.offset = 0

    @property
    def payload_size(self):
        return len(self.payload)

    def first(self, cid):
        return next((c for c in self.children if c.id == cid), None)

    def unpack(self, fmt, offset=0):
        import struct
        return struct.unpack_from(fmt, self.payload, offset)


class _Scene:
    def __init__(self, entries, refs=None, chunks=None):
        self.entries, self._refs, self._chunks = entries, refs or {}, chunks or {}
        self.classes = [e for e in entries if e is not None]

    def __len__(self):
        return len(self.entries)

    def entry(self, i):
        return self.entries[i]

    def refs(self, i):
        return self._refs.get(i, {})

    def chunk(self, i):
        return self._chunks.get(i, _Chunk())

    def is_a(self, i, superclass, class_id):
        e = self.entries[i]
        return e is not None and e.superclass == superclass and e.class_id == class_id

    def class_index(self, i):
        return self.entries[i].index if self.entries[i] is not None else -1


def _entry(superclass, class_id, index=0):
    return types.SimpleNamespace(superclass=superclass, class_id=class_id, index=index)


def _render_env(*leaves):
    import struct
    kids = [_Chunk(cid=cid, payload=struct.pack(fmt, v)) for cid, fmt, v in leaves]
    return _Chunk([_Chunk([_Chunk(kids, cid=C._RENDER_DATA)], cid=C._RENDER)])


class Malformed(unittest.TestCase):
    def test_not_a_camera_or_no_block_raises(self):
        box = _entry(classids.SC_GEOMOBJECT, classids.BOX)
        with self.assertRaises(C.CameraError):
            C.read_params(_Scene([box]), 0)
        for family in (classids.FREE_CAMERA, classids.PHYSICAL_CAMERA):
            cam = _entry(classids.SC_CAMERA, family)
            for refs in ({}, {0: 5}, {0: 1}):  # no slot 0, past the objects, not a parameter block
                with self.assertRaises(C.CameraError, msg=refs):
                    C.read_params(_Scene([cam, box], {0: refs}), 0)

    def test_render_settings(self):
        env = _entry(classids.SC_RENDER_ENVIRONMENT, classids.RENDER_ENVIRONMENT, 0)
        self.assertEqual(C.render_settings(_Scene([])), (None, []))
        rs, issues = C.render_settings(_Scene([env], chunks={0: _render_env(
            (C._WIDTH, "<i", 800), (C._HEIGHT, "<i", 450), (C._ASPECT, "<f", 1.5), (C._LOCKED_VIEW, "<i", 2))}))
        self.assertEqual((rs.width, rs.height, rs.pixel_aspect, rs.view, rs.index, issues), (800, 450, 1.5, 2, 0, []))
        rs, issues = C.render_settings(_Scene([env], chunks={0: _render_env(
            (C._WIDTH, "<i", -3), (C._HEIGHT, "<i", 450), (C._ASPECT, "<f", float("nan")),
            (C._LOCKED_VIEW, "<i", 99))}))
        self.assertEqual((rs.width, rs.height, rs.pixel_aspect, rs.view), (None, None, None, None))
        self.assertEqual(issues, [C.BAD_SIZE % "-3 x 450", C.BAD_ASPECT % float("nan")])
        rs, issues = C.render_settings(_Scene([env], chunks={0: _render_env(
            (C._WIDTH, "<i", 3), (C._HEIGHT, "<i", 450), (C._ASPECT, "<f", 250.0))}))  # Blender: 4.., 1..200
        self.assertEqual((rs.width, rs.pixel_aspect, issues), (None, None, [C.BAD_SIZE % "3 x 450",
                                                                            C.BAD_ASPECT % 250.0]))
        rs, issues = C.render_settings(_Scene([env], chunks={0: _render_env((C._WIDTH, "<i", 800))}))
        # not stored: the report says Blender's is kept
        self.assertEqual((rs.width, rs.height, rs.pixel_aspect, issues), (None, None, None, []))

    def test_render_camera(self):
        views = C.SavedViews([(2, None), (C.CAMERA_VIEW, 7), (C.CAMERA_VIEW, 9)], 0)
        settings = C.RenderSettings(10, 10, 1.0, None, 0)
        names = {5: "First"}
        self.assertEqual(C.render_camera(settings, views, []), (None, None, None))
        # the view was read and looks through no camera: a note, no issue
        self.assertEqual(C.render_camera(settings, views, [5, 7], names), (5, None, C.NOT_A_CAMERA % 1))
        self.assertEqual(C.render_camera(settings._replace(view=1), views, [5, 7], names), (7, None, None))
        self.assertEqual(C.render_camera(settings, views._replace(active=2), [5, 9], names), (9, None, None))
        # a camera node that was not built (an empty) is no scene camera: an issue
        self.assertEqual(C.render_camera(settings._replace(view=2), views, [5, 7], names),
                         (5, C.UNBUILT_VIEW % (3, "First"), None))
        # the views cannot be read: an issue
        self.assertEqual(C.render_camera(None, None, [5], names), (5, C.NO_VIEW % "First", None))
        self.assertEqual(C.render_camera(settings._replace(view=8), views, [5]), (5, C.NO_VIEW % "object 5", None))
        self.assertEqual(C.render_camera(settings, views._replace(active=None), [5], names),
                         (5, C.NO_VIEW % "First", None))
        damaged = C.SavedViews([], None, "bad chunk")
        self.assertEqual(C.render_camera(settings._replace(view=1), damaged, [5, 7], names),
                         (5, C.DAMAGED_VIEWS % ("bad chunk", "First"), None))
        self.assertIsNone(views.damaged)
        # the view's own record cannot be read (views_of: (None, None)): an issue, not a note
        self.assertEqual(C.render_camera(settings, views._replace(viewports=[(None, None)]), [5], names),
                         (5, C.BAD_VIEW % (1, "First"), None))

    def test_views_of_layout_tabs_and_of_a_flat_layout(self):
        import struct

        def viewport(k, kind, node=0):
            payload = struct.pack("<II", 0, kind) + bytes(68) + struct.pack("<i", node)
            return _Chunk(cid=C._VIEWPORT + k, payload=payload)

        def layout(active, *ports):
            return _Chunk(list(ports) + [_Chunk(cid=C._ACTIVE, payload=struct.pack("<i", active))], cid=C._LAYOUT)

        def index(value):  # 0x8240 before each layout: not its position (0 on every tab of corpus scene B)
            return _Chunk(cid=0x8240, payload=struct.pack("<i", value))

        other = layout(-1, viewport(0, 2), viewport(1, C.CAMERA_VIEW, 3))
        current = layout(0, viewport(0, C.CAMERA_VIEW, 42), viewport(1, 7))
        tabs = _Chunk([_Chunk(cid=C._CURRENT, payload=struct.pack("<i", 1)), index(0), other, index(0), current],
                      cid=C._LAYOUT_SET)
        self.assertEqual(C.views_of(_Chunk([tabs], cid=C._LAYOUTS)),
                         C.SavedViews([(C.CAMERA_VIEW, 42), (7, None)], 0))
        # a file saved as 3ds Max 2012: 0x2080 is the layout; an active index past the viewports
        flat = _Chunk([viewport(0, C.CAMERA_VIEW, 5), viewport(1, 4),
                       _Chunk(cid=C._ACTIVE, payload=struct.pack("<i", 9))], cid=C._LAYOUTS)
        self.assertEqual(C.views_of(flat), C.SavedViews([(C.CAMERA_VIEW, 5), (4, None)], None))
        tabs.children[0] = _Chunk(cid=C._CURRENT, payload=struct.pack("<i", 5))  # past the layouts
        self.assertIsNone(C.views_of(_Chunk([tabs], cid=C._LAYOUTS)))
        short = _Chunk([_Chunk(cid=C._VIEWPORT, payload=bytes(12))], cid=C._LAYOUTS)
        self.assertEqual(C.views_of(short), C.SavedViews([(None, None)], None))
        self.assertIsNone(C.views_of(None))

    def test_saved_views_of_a_file_without_them(self):
        class NoConfig:
            def exists(self, name):
                return False

        class Broken:
            def exists(self, name):
                return True

            def open(self, name, **kw):
                raise cfb.CfbError("damaged")
        class Garbage(Broken):  # a Config stream that is no chunk tree
            def open(self, name, **kw):
                return b"\x00\x20\xff\xff\xff\x7f"
        self.assertIsNone(C.saved_views(NoConfig()))
        # a damaged Config stream is told apart from a missing one
        self.assertEqual(C.saved_views(Broken()), C.SavedViews([], None, "damaged"))
        damaged = C.saved_views(Garbage())
        self.assertEqual((damaged.viewports, damaged.active), ([], None))
        self.assertTrue(damaged.damaged)


class _Block:
    def __init__(self, stored):
        self.stored, self.issues = stored, ()

    def get(self, pid, default=None):
        return self.stored.get(pid, default)


class Params(unittest.TestCase):
    def test_animated_or_no_number_takes_the_default(self):
        cam = _entry(classids.SC_CAMERA, classids.PHYSICAL_CAMERA)
        stored = {5: pblock.Animated(2), 4: float("nan"), 39: True, 7: 1.25}  # focal, film, shift_x, zoom
        orig = C._block
        C._block = lambda scene, i, kind: _Block(stored)
        try:
            values, issues = C.read_params(_Scene([cam]), 0)
        finally:
            C._block = orig
        self.assertEqual((values["focal"], values["film"], values["shift_x"], values["zoom"]), (40.0, 36.0, 0.0, 1.25))
        # a bool is no number; a missing one that the framing needs is named, the others take their default quietly
        self.assertEqual(issues, [C.MISSING % ("film", 36.0), C.MISSING % ("focal", 40.0),
                                  C.MISSING % ("fov_degrees", 45.0), C.MISSING % ("shift_x", 0.0)])

    def test_a_standard_camera_without_a_value(self):
        cam = _entry(classids.SC_CAMERA, classids.FREE_CAMERA)
        orig = C._block
        C._block = lambda scene, i, kind: _Block({0: 0.5})
        try:
            values, issues = C.read_params(_Scene([cam]), 0)
        finally:
            C._block = orig
        self.assertEqual((values["fov"], values["ortho"], values["clip"]), (0.5, False, False))
        self.assertEqual(issues, [C.MISSING % (name, default) for name, (_i, default) in C._OLD.items()
                                  if name != "fov"])


class _T:
    """convert.scene's Transforms for _camera: world translations, a Look At target per node, offsets."""
    IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))

    def __init__(self, positions, targets, offsets=()):
        self.positions, self.targets, self.offsets = positions, targets, set(offsets)

    def world(self, i):
        return self.IDENTITY[:3] + (self.positions[i],)

    def look_at(self, i):
        t = self.targets.get(i)
        return None if t is None else types.SimpleNamespace(target=t)

    def offset(self, i):
        return ((2.0, 0.0, 0.0),) + self.IDENTITY[1:] if i in self.offsets else conv.controllers.IDENTITY


@unittest.skipIf(conv is None, "numpy missing")
class SceneHook(unittest.TestCase):
    """convert.scene._camera: the reasons, issues and keys of the nodes of one camera object (0)."""

    def hook(self, read, t, nodes):
        desc = conv.SceneDescription(0.001)
        unseen, params = {}, {}
        sc = _Scene([_entry(classids.SC_CAMERA, classids.PHYSICAL_CAMERA)])
        orig = C.read_params
        C.read_params = read
        try:
            keys = [conv._camera(sc, t, desc, unseen, params, 0, node, "n%d" % node, 0.001, 1.0) for node in nodes]
        finally:
            C.read_params = orig
        return desc, keys

    def test_a_damaged_camera_is_named_on_every_node(self):
        def read(scene, i):
            raise C.CameraError("damaged")
        desc, keys = self.hook(read, _T({}, {}), [10, 11])
        self.assertEqual(keys, [None, None])
        self.assertEqual(desc.issues, [(10, "camera: not built: parameters cannot be read: damaged"),
                                       (11, "camera: not built: parameters cannot be read: damaged")])
        self.assertEqual((desc.cameras, dict(desc.placeholders)), ({}, {}))

    def test_instances_share_a_camera_unless_their_target_distances_differ(self):
        positions = {10: (0.0, 0.0, 0.0), 11: (5.0, 0.0, 0.0), 12: (9.0, 0.0, 0.0), 20: (0.0, 3000.0, 0.0),
                     21: (5.0, 3000.0, 0.0), 22: (9.0, 5000.0, 0.0)}
        t = _T(positions, {10: 20, 11: 21, 12: 22})
        desc, keys = self.hook(lambda scene, i: (physical(targeted=1), ["read"]), t, [10, 11, 12])
        self.assertEqual(keys, [(0, 3000.0), (0, 3000.0), (0, 5000.0)])
        self.assertEqual([desc.cameras[k].users for k in sorted(desc.cameras)], [[10, 11], [12]])
        self.assertEqual(desc.issues, [(10, "camera: read")])
        # a specified FOV does not depend on the target: one camera
        desc, keys = self.hook(lambda scene, i: (physical(targeted=1, specify_fov=1), []), t, [10, 11, 12])
        self.assertEqual(keys, [(0, None)] * 3)

    def test_an_object_offset_is_named(self):
        t = _T({10: (0.0, 0.0, 0.0)}, {}, offsets=[10])
        desc, keys = self.hook(lambda scene, i: (physical(), []), t, [10])
        self.assertEqual(keys, [(0, None)])
        self.assertEqual(desc.issues, [(10, "camera: " + conv.OFFSET)])


def _oracle(name):
    with open(os.path.join(FIXTURES, name + ".oracle.json"), encoding="utf-8") as f:
        return json.load(f)


@unittest.skipIf(conv is None, "numpy missing")
class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {}
        for name in sorted(os.listdir(FIXTURES)):
            if name.endswith(".max"):
                oracle = _oracle(name[:-4])
                if any(n["camera"] for n in oracle["nodes"]):
                    cls.cases[name[:-4]] = (conv.read(os.path.join(FIXTURES, name)), oracle)

    def test_every_camera_has_the_oracles_fov(self):
        self.assertEqual(sorted(self.cases), ["cameras", "lookat"])
        for name, (desc, oracle) in self.cases.items():
            for node, o in zip(desc.nodes, oracle["nodes"]):
                if o["camera"] is None:
                    self.assertNotEqual(node.kind, conv.CAMERA, node.name)
                    continue
                self.assertEqual(node.kind, conv.CAMERA, node.name)
                cd = desc.cameras[node.camera]
                self.assertLess(abs(math.degrees(cd.fov) - o["camera"]["fov"]), FOV_TOLERANCE,
                                "%s %s: %g vs %g" % (name, node.name, math.degrees(cd.fov), o["camera"]["fov"]))
                # Blender's horizontal FOV with sensor fit HORIZONTAL
                self.assertAlmostEqual(math.degrees(2 * math.atan(cd.sensor / (2 * cd.lens))), o["camera"]["fov"],
                                       delta=FOV_TOLERANCE)
                self.assertEqual(cd.kind == C.ORTHO, o["camera"]["ortho"], node.name)
                if o["camera"]["manual_clip"]:
                    self.assertAlmostEqual(cd.clip_start, o["camera"]["hither"] * desc.meters, places=6)
                    self.assertAlmostEqual(cd.clip_end, o["camera"]["yon"] * desc.meters, places=6)
                else:
                    self.assertIsNone(cd.clip_start, node.name)

    def test_cameras_fixture(self):
        desc, oracle = self.cases["cameras"]
        by_name = {n.name: desc.cameras[n.camera] for n in desc.nodes if n.kind == conv.CAMERA}
        want = {  # sensor, shift_x, shift_y (from tools/fixtures/cameras.ms)
            "CamFree": (36.0, 0.0, 0.0), "CamPhysShift": (36.0, -0.1, 0.15), "CamVRayShift": (36.0, -0.1, -0.25),
            "CamVRayTarget": (30.0, 0.0, 0.0), "CamPhysical": (36.0, 0.0, 0.0), "CamVRay": (36.0, 0.0, 0.0)}
        for name, (sensor, sx, sy) in want.items():
            cd = by_name[name]
            self.assertAlmostEqual(cd.sensor, sensor, places=5, msg=name)
            self.assertAlmostEqual(cd.shift_x, sx, places=6, msg=name)
            self.assertAlmostEqual(cd.shift_y, sy, places=6, msg=name)
        self.assertAlmostEqual(by_name["CamFreeOrtho"].ortho_scale, 5.0 * math.tan(math.radians(22.5)), places=6)
        self.assertAlmostEqual(by_name["CamTargetOrtho"].ortho_scale,
                               2 * math.hypot(4.0, 0.01) * math.tan(math.radians(25.0)), places=6)
        self.assertEqual((by_name["CamVRayShift"].clip_start, by_name["CamVRayShift"].clip_end), (0.2, 6.0))
        self.assertEqual(len(desc.cameras), 11)
        r = oracle["render"]
        self.assertEqual((desc.render.width, desc.render.height, desc.render.pixel_aspect, desc.render.view),
                         (r["width"], r["height"], r["pixel_aspect"], 1))
        handle = {n["name"]: n["handle"] for n in oracle["nodes"]}
        scene_camera = next(n.name for n in desc.nodes if n.index == desc.camera)
        self.assertEqual((scene_camera, handle[scene_camera]), ("CamTarget", r["camera"]))
        with cfb.CompoundFile(os.path.join(FIXTURES, "cameras.max")) as cf:
            views = C.saved_views(cf)
        names = {n.index: n.name for n in desc.nodes}
        self.assertEqual([(kind, names.get(node)) for kind, node in views.viewports[:2]],
                         [(C.CAMERA_VIEW, "CamFree"), (C.CAMERA_VIEW, "CamTarget")])
        self.assertEqual(views.active, 0)

    def test_lookat_scene_camera_is_the_first(self):
        desc, oracle = self.cases["lookat"]
        self.assertIsNone(oracle["render"]["camera"])
        self.assertEqual(next(n.name for n in desc.nodes if n.index == desc.camera), "FixtureCam")
        self.assertEqual(len(desc.cameras), 4)
        # saved with a Perspective viewport active: nothing is left out, the render line says why
        self.assertEqual(desc.camera_note, C.NOT_A_CAMERA % 4)
        self.assertFalse([r for _i, r in desc.issues if r.startswith("camera: ")])
        rep = report.gather(desc, source="lookat.max")
        self.assertIn("; scene camera: FixtureCam, the first camera: the view 3ds Max renders (viewport 4) looks "
                      "through no camera", rep.text())

    def test_report(self):
        desc, _oracle = self.cases["cameras"]
        lines = report.gather(desc, source="cameras.max").text().split("\n")
        self.assertIn("Objects built: 17, meshes: 1, cameras: 11", lines)
        self.assertIn("Render size: 800 x 450; scene camera: CamTarget", lines)


if __name__ == "__main__":
    unittest.main()
