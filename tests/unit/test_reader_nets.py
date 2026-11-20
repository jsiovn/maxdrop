# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The per-object nets of reader/ and convert/ catch the reader's errors (MaxFileError, and the arithmetic or
allocation errors named where file values need them), nothing else: a defect behind a net (IndexError, struct.error,
TypeError, a stray ValueError) comes out, so the fuzz harness (tests/unit/fuzz.py) counts it as escaped instead of
an issue line. Each net is checked both ways: a mocked defect propagates, a MaxFileError still costs only its object.
Also the inputs those nets used to hide: math on an infinite file value gives a non-finite matrix (the NON_FINITE
issue), not a "math domain error". No Blender.

    python -I -m unittest discover tests
"""
import importlib
import math
import os
import struct
import sys
import types
import unittest
from unittest import mock

try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

_PKG = "maxdrop_convert_test"  # the package the convert tests make: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg


def _mod(name):
    return importlib.import_module(_PKG + "." + name)


cfb = _mod("reader.cfb")
chunks = _mod("reader.chunks")
classids = _mod("reader.classids")
ct = _mod("reader.controllers")
errors = _mod("reader.errors")
metadata = _mod("reader.metadata")
rmaterials = _mod("reader.materials")
reader_scene = _mod("reader.scene")
shapes = _mod("reader.shapes")
strings = _mod("reader.strings")
cameras = _mod("convert.cameras")
cmaterials = _mod("convert.materials")
ChunkError = chunks.ChunkError
MaxFileError = errors.MaxFileError
INF = float("inf")
DEFECTS = (IndexError("defect"), struct.error("defect"), TypeError("defect"), ValueError("defect"),
           KeyError("defect"))


def _scene(name):
    with cfb.CompoundFile(os.path.join(FIXTURES, name)) as cf:
        return reader_scene.Scene.from_file(cf)


def _raise(exc):
    def f(*_a, **_k):
        raise exc
    return f


class InfiniteValues(unittest.TestCase):
    """cos / sin of an infinite angle raise ValueError: the controllers' math gives NaN instead, and the node's
    non-finite matrix is the NON_FINITE issue."""

    def test_euler_angle(self):
        for order in ct.EULER_ORDERS:
            self.assertFalse(ct._finite(ct.euler_matrix((INF, 0.0, 0.0), order)))
            self.assertFalse(ct._finite(ct.euler_matrix((0.0, -INF, 0.0), order)))

    def test_look_at_roll(self):
        rows = ct.look_frame((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), roll=INF)
        self.assertFalse(all(math.isfinite(v) for row in rows for v in row))

    def test_list_weight(self):
        m = ct.euler_matrix((0.5, 0.25, 0.0))
        for w in (INF, -INF, float("nan")):
            self.assertFalse(ct._finite(ct._weighted_quat(m, w)), w)
        self.assertTrue(ct._finite(ct._weighted_quat(m, 0.5)))

    def test_finite_angles_unchanged(self):
        m = ct.euler_matrix((0.5, 0.25, -1.0), 3)
        self.assertTrue(ct._finite(m))
        self.assertEqual(ct._cos_sin(0.5), (math.cos(0.5), math.sin(0.5)))

    def test_node_with_an_infinite_angle_is_an_issue(self):
        sc = _scene("hierarchy.max")
        i = next(n.index for n in sc.nodes() if n.tm is not None)
        t = ct.Transforms(sc)
        with mock.patch.object(ct._Eval, "matrix", lambda ev, c: ct.euler_matrix((INF, 0.0, 0.0))):
            self.assertEqual(t.local(i), ct.IDENTITY)
        self.assertEqual([x.reason for x in t.issues if x.node == i], [ct.NON_FINITE])


class ControllerNets(unittest.TestCase):

    def setUp(self):
        self.sc = _scene("hierarchy.max")
        self.node = next(n.index for n in self.sc.nodes() if n.tm is not None)

    def test_node_defect_propagates(self):
        for exc in DEFECTS:
            with mock.patch.object(ct._Eval, "matrix", _raise(exc)), self.assertRaises(type(exc)):
                ct.Transforms(self.sc).local(self.node)

    def test_node_damage_is_an_issue(self):
        for exc in (ChunkError("damaged"), MaxFileError("damaged"), OverflowError("big")):
            t = ct.Transforms(self.sc)
            with mock.patch.object(ct._Eval, "matrix", _raise(exc)):
                self.assertEqual(t.local(self.node), ct.IDENTITY)
            self.assertTrue(any(x.node == self.node and str(exc) in x.reason for x in t.issues), exc)

    def test_gizmo_defect_propagates(self):
        tm = self.sc.node(self.node).tm
        for exc in DEFECTS:
            with mock.patch.object(ct._Eval, "matrix", _raise(exc)), self.assertRaises(type(exc)):
                ct.matrix(self.sc, tm)

    def test_gizmo_damage_is_an_issue(self):
        tm = self.sc.node(self.node).tm
        with mock.patch.object(ct._Eval, "matrix", _raise(ChunkError("damaged"))):
            m, issues = ct.matrix(self.sc, tm)
        self.assertEqual(m, ct.IDENTITY)
        self.assertEqual(len(issues), 1)
        self.assertIn("damaged", issues[0].reason)


class ShapeNets(unittest.TestCase):

    def setUp(self):
        self.sc = _scene("shapes.max")
        self.objects = [i for i in range(len(self.sc)) if shapes.is_shape(self.sc, i)]
        self.stored = [i for i in self.objects if self.sc.entry(i).class_id in shapes._STORED]
        self.assertTrue(self.objects and self.stored)

    def test_shape_defect_propagates(self):
        for exc in DEFECTS:
            with mock.patch.object(shapes, "_render", _raise(exc)), self.assertRaises(type(exc)):
                shapes.read_shape(self.sc, self.objects[0])

    def test_shape_damage_is_a_shape_error(self):
        for exc in (ChunkError("damaged"), MaxFileError("damaged"), OverflowError("big"), MemoryError()):
            with mock.patch.object(shapes, "_render", _raise(exc)), self.assertRaises(shapes.ShapeError):
                shapes.read_shape(self.sc, self.objects[0])

    def test_spline_defect_propagates(self):
        for exc in DEFECTS:
            with mock.patch.object(shapes, "_spline", _raise(exc)), self.assertRaises(type(exc)):
                shapes.read_shape(self.sc, self.stored[0])

    def test_spline_damage_leaves_it_out(self):
        with mock.patch.object(shapes, "_spline", _raise(ChunkError("damaged"))):
            sh = shapes.read_shape(self.sc, self.stored[0])
        self.assertEqual(sh.splines, ())
        self.assertTrue(any("left out: damaged" in x for x in sh.issues))


@unittest.skipIf(numpy is None, "numpy is not installed")
class MeshNet(unittest.TestCase):

    def setUp(self):
        self.geometry = _mod("reader.geometry")
        self.sc = _scene("box_poly_standard.max")
        g = self.geometry
        self.mesh = next(i for i in range(len(self.sc)) if self.sc.entry(i) is not None
                         and self.sc.entry(i).superclass == classids.SC_GEOMOBJECT
                         and self.sc.entry(i).class_id in g._READERS)

    def _patched(self, exc):
        return mock.patch.dict(self.geometry._READERS, {self.sc.entry(self.mesh).class_id: _raise(exc)})

    def test_defect_propagates(self):
        for exc in DEFECTS:
            with self._patched(exc), self.assertRaises(type(exc)):
                self.geometry.read_mesh(self.sc, self.mesh)

    def test_damage_is_a_geometry_error(self):
        for exc in (ChunkError("damaged"), MaxFileError("damaged"), OverflowError("big"), MemoryError()):
            with self._patched(exc), self.assertRaises(self.geometry.GeometryError):
                self.geometry.read_mesh(self.sc, self.mesh)


class _Scene:
    """A scene of 10 objects whose chunk() and node() raise exc."""

    def __init__(self, exc):
        self.exc = exc

    def __len__(self):
        return 10

    def chunk(self, _i):
        raise self.exc

    def node(self, _i):
        raise self.exc


class MaterialNets(unittest.TestCase):

    def test_leaf_u32s(self):
        for exc in DEFECTS:
            with self.assertRaises(type(exc)):
                rmaterials._leaf_u32s(_Scene(exc), 1, (1,))
        self.assertEqual(rmaterials._leaf_u32s(_Scene(ChunkError("damaged")), 1, (1,)), {})

    def test_bitmap_gamma(self):
        m = types.SimpleNamespace(blocks={0: types.SimpleNamespace(block_id=0)}, refs={0: 1})
        for exc in DEFECTS:
            with self.assertRaises(type(exc)):
                rmaterials.bitmap_gamma(_Scene(exc), m)
        self.assertIsNone(rmaterials.bitmap_gamma(_Scene(ChunkError("damaged")), m))

    def test_node_materials(self):
        desc = types.SimpleNamespace(nodes=[types.SimpleNamespace(index=3)])
        for exc in DEFECTS:
            with self.assertRaises(type(exc)):
                cmaterials.node_materials(_Scene(exc), desc)
        self.assertEqual(cmaterials.node_materials(_Scene(ChunkError("damaged")), desc), {3: None})

    def test_get_past_the_scene_is_a_chunk_error(self):
        sc = _scene("standard_physical.max")
        graph = rmaterials.MaterialGraph(sc)
        for i in (len(sc), len(sc) + 7, -1):
            with self.assertRaises(ChunkError):
                graph.get(i)

    def test_past_the_scene_reads_as_nothing(self):
        sc = _scene("standard_physical.max")
        m = types.SimpleNamespace(blocks={0: types.SimpleNamespace(block_id=0)}, refs={0: len(sc)})
        self.assertIsNone(rmaterials.bitmap_gamma(sc, m))
        for i in (len(sc), -1):
            self.assertEqual(rmaterials._leaf_u32s(sc, i, (1,)), {})


class _Cf:
    """A compound file with every stream, each empty."""

    def exists(self, _name):
        return True

    def open(self, _name, **_k):
        return types.SimpleNamespace(size=0, read=lambda: b"")


class CameraNet(unittest.TestCase):

    def test_saved_views(self):
        for exc in DEFECTS:
            with mock.patch.object(cameras.chunks, "index", _raise(exc)), self.assertRaises(type(exc)):
                cameras.saved_views(_Cf())
        for exc in (ChunkError("damaged"), cfb.CfbError("damaged"), OSError("io")):
            with mock.patch.object(cameras.chunks, "index", _raise(exc)):
                views = cameras.saved_views(_Cf())
            self.assertEqual((views.viewports, views.damaged), ([], str(exc)))


class StringsNets(unittest.TestCase):

    def test_writer_version(self):
        for exc in DEFECTS:
            with mock.patch.object(strings.metadata, "read", _raise(exc)), self.assertRaises(type(exc)):
                strings.writer_version(_Cf())
        with mock.patch.object(strings.metadata, "read", _raise(metadata.MetadataError("damaged"))):
            self.assertIsNone(strings.writer_version(_Cf()))

    def test_code_page(self):
        for exc in DEFECTS:
            with mock.patch.object(strings.metadata, "code_page", _raise(exc)), self.assertRaises(type(exc)):
                strings.code_page(_Cf())
        with mock.patch.object(strings.metadata, "code_page", _raise(cfb.CfbError("damaged"))):
            self.assertIsNone(strings.code_page(_Cf()))

    def test_directory_names(self):
        with mock.patch.object(strings, "writer_version", lambda cf: None), \
                mock.patch.object(strings, "code_page", lambda cf: None):
            for exc in DEFECTS:
                with mock.patch.object(strings, "_directory_names", _raise(exc)), self.assertRaises(type(exc)):
                    strings.of_file(_Cf())
            with mock.patch.object(strings, "_directory_names", _raise(ChunkError("damaged"))):
                self.assertIs(strings.of_file(_Cf()), strings.UNICODE)  # no vote, no version: wide


@unittest.skipIf(numpy is None, "numpy is not installed")
class PrimitiveNet(unittest.TestCase):

    def test_primitive(self):
        conv = _mod("convert.scene")
        for exc in DEFECTS:
            with mock.patch.object(conv.primitives, "mesh", _raise(exc)), self.assertRaises(type(exc)):
                conv._primitive(None, 1, [], 2, [0])
        for exc in (ChunkError("damaged"), ZeroDivisionError("zero"), OverflowError("big")):
            issues = []
            with mock.patch.object(conv.primitives, "mesh", _raise(exc)):
                self.assertIsNone(conv._primitive(None, 1, issues, 2, [0]))
            self.assertEqual(len(issues), 1)
            self.assertIn(str(exc), issues[0][1])


if __name__ == "__main__":
    unittest.main()
