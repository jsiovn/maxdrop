# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/geometry.py, Editable Mesh and Editable Poly as numpy arrays: no Blender. Synthetic
geometry chunks (every optional face field, dead vertices and faces, map channels, damaged input) and every
committed fixture against its 3ds Max oracle (vertex and face counts) and its authoring script (smoothing groups,
material IDs, map channels).

    python -I -m unittest discover tests
"""
import glob
import importlib
import json
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
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))


def _fixture(name):
    return os.path.join(ROOT, "tests", "fixtures", name + ".max")


_PKG = "maxdrop_convert_test"  # the package the convert tests make: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
cfb = importlib.import_module(_PKG + ".reader.cfb")
chunks = importlib.import_module(_PKG + ".reader.chunks")
classdir = importlib.import_module(_PKG + ".reader.classdir")
classids = importlib.import_module(_PKG + ".reader.classids")
scene = importlib.import_module(_PKG + ".reader.scene")
geometry = importlib.import_module(_PKG + ".reader.geometry")
GeometryError = geometry.GeometryError


def leaf(cid, payload=b""):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def chunk_of(data):
    return chunks.index(data)[0]


# Editable Poly records

def poly_verts(points, dead=()):
    out = struct.pack("<I", len(points))
    for i, p in enumerate(points):
        out += struct.pack("<I", geometry.DEAD) if i in dead else struct.pack("<I3f", 0, *p)
    return leaf(0x0100, out)


def poly_face(verts, flags=None, material=None, smoothing=None, diagonals=True):
    mask, tail = 0, b""
    if flags is not None:
        mask |= 0x01
        tail += struct.pack("<I", flags)
    if material is not None:
        mask |= 0x08
        tail += struct.pack("<H", material)
    if smoothing is not None:
        mask |= 0x10
        tail += struct.pack("<I", smoothing)
    if diagonals and len(verts) > 3:
        mask |= 0x20
        tail += struct.pack("<%dI" % (2 * (len(verts) - 3)), *([0, 2] * (len(verts) - 3)))
    return struct.pack("<I%dI" % len(verts), len(verts), *verts) + struct.pack("<H", mask) + tail


def poly_faces(*faces):
    return leaf(0x011A, struct.pack("<I", len(faces)) + b"".join(faces))


def poly_map(channel, uvw, faces):
    body = b"".join(struct.pack("<I%dI" % len(f), len(f), *f) for f in faces)
    return (leaf(0x0124, struct.pack("<i", channel)) +
            leaf(0x0128, struct.pack("<I", len(uvw)) + b"".join(struct.pack("<3f", *p) for p in uvw)) +
            leaf(0x012B, body))


def poly(*children):
    return chunk_of(node(0x0013, node(geometry.GEOMETRY, *children)))


QUAD = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0)]


# Editable Mesh records

def mesh_verts(points):
    return leaf(0x0914, struct.pack("<I", len(points)) + b"".join(struct.pack("<3f", *p) for p in points))


def mesh_faces(*faces):  # (a, b, c, smoothing, material)
    return leaf(0x0912, struct.pack("<I", len(faces)) + b"".join(
        struct.pack("<3III", a, b, c, sg, (mat << 16) | 0x7) for a, b, c, sg, mat in faces))


def mesh_map(channel, uvw, faces):
    return (leaf(0x0959, struct.pack("<i", channel)) + leaf(0x2398, struct.pack("<I", 1)) +
            leaf(0x2394, struct.pack("<I", len(uvw)) + b"".join(struct.pack("<3f", *p) for p in uvw)) +
            leaf(0x2396, struct.pack("<I", len(faces)) + b"".join(struct.pack("<3I", *f) for f in faces)))


def mesh(*children):
    return chunk_of(node(0x0014, node(geometry.GEOMETRY, *children)))


TRI = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]


@unittest.skipIf(numpy is None, "numpy missing")
class EditablePolyTest(unittest.TestCase):
    def test_every_face_field(self):
        m = geometry.read_editable_poly(poly(
            poly_verts(QUAD),
            poly_faces(poly_face([0, 1, 2, 3]),
                       poly_face([1, 4, 2], flags=1, material=4, smoothing=0x80000001),
                       poly_face([0, 1, 2, 3], material=2, diagonals=False),
                       poly_face([3, 2, 1, 0], smoothing=6))))
        self.assertEqual(m.positions.dtype, numpy.float32)
        self.assertEqual(m.positions.shape, (5, 3))
        self.assertEqual(m.loop_vertices.dtype, numpy.int32)
        self.assertEqual(m.loop_vertices.tolist(), [0, 1, 2, 3, 1, 4, 2, 0, 1, 2, 3, 3, 2, 1, 0])
        self.assertEqual(m.loop_starts.tolist(), [0, 4, 7, 11])
        self.assertEqual(m.loop_starts.dtype, numpy.int32)
        self.assertEqual(m.loop_totals.tolist(), [4, 3, 4, 4])
        self.assertEqual(m.smoothing_groups.dtype, numpy.uint32)
        self.assertEqual(m.smoothing_groups.tolist(), [0, 0x80000001, 0, 6])
        self.assertEqual(m.material_ids.dtype, numpy.uint16)
        self.assertEqual(m.material_ids.tolist(), [0, 4, 2, 0])
        self.assertEqual(m.maps, {})
        self.assertEqual((m.stored_vertices, m.stored_faces), (5, 4))

    def test_map_channels_keep_their_numbers(self):
        faces = [[0, 1, 2, 3], [1, 4, 2]]
        m = geometry.read_editable_poly(poly(
            poly_verts(QUAD), poly_faces(*(poly_face(f) for f in faces)), leaf(0x0120, struct.pack("<I", 4)),
            poly_map(0, [(1, 0, 0)], [[0, 0, 0, 0], [0, 0, 0]]),
            poly_map(3, [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 2, 2)], [[3, 2, 1, 0], [4, 1, 2]])))
        self.assertEqual(list(m.maps), [0, 3])
        self.assertEqual(m.maps[0].indices.tolist(), [0] * 7)
        self.assertEqual(m.maps[3].channel, 3)
        self.assertEqual(m.maps[3].uvw.dtype, numpy.float32)
        self.assertEqual(m.maps[3].uvw.shape, (5, 3))
        self.assertEqual(m.maps[3].indices.dtype, numpy.int32)
        self.assertEqual(m.maps[3].indices.tolist(), [3, 2, 1, 0, 4, 1, 2])

    def test_dead_vertices_and_faces_are_left_out(self):
        # vertex 1 is dead; face 1 is dead (degree 0, as stored); face 2 is dead by its flags but keeps its
        # vertices; the map face of a dead face keeps its old length
        m = geometry.read_editable_poly(poly(
            poly_verts(QUAD, dead=(1,)),
            poly_faces(poly_face([0, 2, 3]), poly_face([], flags=0x10026), poly_face([0, 1, 2], flags=2),
                       poly_face([4, 2, 3, 0], material=1)),
            poly_map(1, [(0, 0, 0)] * 6, [[0, 1, 2], [3, 4, 5, 0], [1, 1, 1], [5, 4, 3, 2]])))
        self.assertEqual(m.positions.tolist(), [[0, 0, 0], [1, 1, 0], [0, 1, 0], [2, 0, 0]])
        self.assertEqual(m.loop_vertices.tolist(), [0, 1, 2, 3, 1, 2, 0])
        self.assertEqual(m.loop_starts.tolist(), [0, 3])
        self.assertEqual(m.material_ids.tolist(), [0, 1])
        self.assertEqual(m.maps[1].indices.tolist(), [0, 1, 2, 5, 4, 3, 2])
        self.assertEqual((m.stored_vertices, m.stored_faces), (5, 4))

    def test_map_faces_aligned_with_dead_face_of_degree_zero(self):
        m = geometry.read_editable_poly(poly(
            poly_verts(QUAD), poly_faces(poly_face([], flags=2), poly_face([0, 1, 2])),
            poly_map(1, [(0, 0, 0)] * 3, [[], [2, 1, 0]])))
        self.assertEqual(m.maps[1].indices.tolist(), [2, 1, 0])

    def test_empty_mesh(self):
        m = geometry.read_editable_poly(poly(poly_verts([]), poly_faces()))
        self.assertEqual(m.positions.shape, (0, 3))
        self.assertEqual(len(m.loop_vertices), 0)
        self.assertEqual(len(m.loop_starts), 0)
        self.assertEqual(len(m.loop_totals), 0)

    def test_arrays_do_not_share_the_file_memory(self):
        data = bytearray(node(0x0013, node(geometry.GEOMETRY, poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])),
                                           poly_map(1, [(0, 0, 0)] * 3, [[0, 1, 2]]))))
        m = geometry.read_editable_poly(chunks.index(data)[0])
        buf = numpy.frombuffer(data, dtype=numpy.uint8)
        for a in (m.positions, m.loop_vertices, m.loop_starts, m.smoothing_groups, m.material_ids, m.maps[1].uvw,
                  m.maps[1].indices):
            self.assertFalse(numpy.shares_memory(a, buf))

    def test_damaged(self):
        cases = {
            "no geometry container": chunk_of(node(0x0013, leaf(0x2034, b"\0" * 4))),
            "a leaf object": chunk_of(leaf(0x0013, b"")),
            "no vertices": poly(poly_faces(poly_face([0, 1, 2]))),
            "no faces": poly(poly_verts(QUAD)),
            "vertex index past the end": poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 5]))),
            "face on a dead vertex": poly(poly_verts(QUAD, dead=(2,)), poly_faces(poly_face([0, 1, 2]))),
            "unknown face field": poly(poly_verts(QUAD), poly_faces(
                struct.pack("<I3IH", 3, 0, 1, 2, 0x02) + struct.pack("<H", 0))),
            "face cut short": poly(poly_verts(QUAD), leaf(0x011A, struct.pack("<II", 1, 3) + struct.pack("<2I", 0, 1))),
            "face fields cut short": poly(poly_verts(QUAD), leaf(0x011A, struct.pack("<II3IH", 1, 3, 0, 1, 2, 0x10))),
            "bytes after the faces": poly(poly_verts(QUAD), leaf(0x011A, struct.pack("<I", 1) +
                                                                 poly_face([0, 1, 2]) + b"\0\0")),
            "more faces counted than stored": poly(poly_verts(QUAD), leaf(0x011A, struct.pack("<I", 2) +
                                                                          poly_face([0, 1, 2]))),
            "a live face of two vertices": poly(poly_verts(QUAD), poly_faces(poly_face([0, 1]))),
            "diagonals of a face of two vertices": poly(poly_verts(QUAD), poly_faces(
                struct.pack("<I2IH", 2, 0, 1, 0x20))),
            "vertex records cut short": poly(leaf(0x0100, struct.pack("<II3f", 2, 0, 0, 0, 0) + b"\0\0"),
                                             poly_faces()),
            "vertex count without records": poly(leaf(0x0100, struct.pack("<I", 1000)), poly_faces()),
            "a dead vertex with a position": poly(leaf(0x0100, struct.pack("<II3f", 1, 2, 0, 0, 0)), poly_faces()),
            "vertices without a count": poly(leaf(0x0100, b"\0"), poly_faces()),
            "map vertex index past the end": poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])),
                                                  poly_map(1, [(0, 0, 0)] * 2, [[0, 1, 2]])),
            "map face of another degree": poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])),
                                               poly_map(1, [(0, 0, 0)] * 4, [[0, 1, 2, 3]])),
            "fewer map faces than faces": poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 2]), poly_face([0, 2, 3])),
                                               poly_map(1, [(0, 0, 0)] * 3, [[0, 1, 2]])),
            "more map faces than faces": poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])),
                                              poly_map(1, [(0, 0, 0)] * 3, [[0, 1, 2], [0, 1, 2]])),
            "map faces without map vertices": poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])),
                                                   leaf(0x0124, struct.pack("<i", 1)), leaf(0x012B, b"\0" * 16)),
            "map vertices without a channel": poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])),
                                                   leaf(0x0128, struct.pack("<I3f", 1, 0, 0, 0))),
            "map vertex count and size disagree": poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])),
                                                       leaf(0x0124, struct.pack("<i", 1)),
                                                       leaf(0x0128, struct.pack("<I3f", 2, 0, 0, 0))),
            "map vertices without map faces": poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])),
                                                   leaf(0x0124, struct.pack("<i", 1)),
                                                   leaf(0x0128, struct.pack("<I3f", 1, 0, 0, 0))),
            "map vertices without map faces, then a channel": poly(
                poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])), leaf(0x0124, struct.pack("<i", 1)),
                leaf(0x0128, struct.pack("<I3f", 1, 0, 0, 0)), poly_map(2, [(0, 0, 0)] * 3, [[0, 1, 2]])),
            "map vertices twice in a channel": poly(
                poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])), leaf(0x0124, struct.pack("<i", 1)),
                leaf(0x0128, struct.pack("<I3f", 1, 0, 0, 0)), poly_map(1, [(0, 0, 0)] * 3, [[0, 1, 2]])[10:]),
            "a channel twice": poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])),
                                    poly_map(1, [(0, 0, 0)] * 3, [[0, 1, 2]]),
                                    poly_map(1, [(0, 0, 0)] * 3, [[0, 1, 2]])),
        }
        for name, c in cases.items():
            with self.subTest(name), self.assertRaises(GeometryError):
                geometry.read_editable_poly(c)

    def test_face_flags_alone(self):
        m = geometry.read_editable_poly(poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 2], flags=0x40001))))
        self.assertEqual(m.loop_vertices.tolist(), [0, 1, 2])
        self.assertEqual((m.material_ids.tolist(), m.smoothing_groups.tolist()), ([0], [0]))

    def test_huge_counts_are_refused_before_allocating(self):
        # a 14-byte chunk must not make the reader allocate gigabytes
        for c in (poly(leaf(0x0100, struct.pack("<II", 0xFFFFFFFF, 0)), poly_faces()),
                  poly(poly_verts(QUAD), leaf(0x011A, struct.pack("<II", 0xFFFFFFFF, 0)))):
            with self.subTest(c), self.assertRaisesRegex(GeometryError, "counted in"):
                geometry.read_editable_poly(c)

    def test_huge_face_degree_is_refused_before_reading(self):
        c = poly(poly_verts(QUAD), leaf(0x011A, struct.pack("<II", 1, 0x7FFFFFFF) + b"\0" * 16))
        with self.assertRaisesRegex(GeometryError, "past the end"):
            geometry.read_editable_poly(c)

    def test_caps_per_mesh(self):
        two = poly_faces(poly_face([0, 1, 2]), poly_face([0, 2, 3]))
        cases = (
            ("MAX_VERTICES", 4, poly(poly_verts(QUAD), two), "5 vertices, more than the 4"),
            ("MAX_VERTICES", 4, poly(poly_verts(QUAD, dead={4}), two), "5 vertices, more than the 4"),
            ("MAX_LOOPS", 5, poly(poly_verts(QUAD), two), "6 face corners, more than the 5"),
            ("MAX_VERTICES", 5, poly(poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])),
                                     poly_map(1, QUAD + [(3, 0, 0)], [[0, 1, 2]])), "6 map vertices, more than the 5"),
        )
        for cap, value, c, message in cases:
            with self.subTest(cap=cap, value=value), mock.patch.object(geometry, cap, value), \
                    self.assertRaisesRegex(GeometryError, message):
                geometry.read_editable_poly(c)
        with mock.patch.object(geometry, "MAX_VERTICES", 5), mock.patch.object(geometry, "MAX_LOOPS", 6):
            self.assertEqual(len(geometry.read_editable_poly(poly(poly_verts(QUAD), two)).loop_vertices), 6)


@unittest.skipIf(numpy is None, "numpy missing")
class EditableMeshTest(unittest.TestCase):
    def test_faces_smoothing_materials_maps(self):
        m = geometry.read_editable_mesh(mesh(
            leaf(0x0906, struct.pack("<I", 2)), mesh_verts(TRI), mesh_faces((0, 1, 2, 1, 0), (1, 3, 2, 6, 65535)),
            leaf(0x0924, struct.pack("<I", 0)),
            mesh_map(-2, [(1, 1, 1)], [(0, 0, 0), (0, 0, 0)]),
            mesh_map(1, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2), (2, 1, 0)]),
            leaf(0x23A0, b"\0" * 8)))
        self.assertEqual(m.positions.dtype, numpy.float32)
        self.assertEqual(m.positions.tolist(), [list(map(float, p)) for p in TRI])
        self.assertEqual(m.loop_vertices.tolist(), [0, 1, 2, 1, 3, 2])
        self.assertEqual(m.loop_vertices.dtype, numpy.int32)
        self.assertEqual(m.loop_starts.tolist(), [0, 3])
        self.assertEqual(m.loop_totals.tolist(), [3, 3])
        self.assertEqual(m.smoothing_groups.tolist(), [1, 6])
        self.assertEqual(m.smoothing_groups.dtype, numpy.uint32)
        self.assertEqual(m.material_ids.tolist(), [0, 65535])
        self.assertEqual(m.material_ids.dtype, numpy.uint16)
        self.assertEqual(list(m.maps), [-2, 1])
        self.assertEqual(m.maps[1].indices.tolist(), [0, 1, 2, 2, 1, 0])
        self.assertEqual(m.maps[1].indices.dtype, numpy.int32)
        self.assertEqual(m.maps[1].uvw.shape, (3, 3))
        self.assertEqual((m.stored_vertices, m.stored_faces), (4, 2))

    def test_caps_per_mesh(self):
        two = mesh_faces((0, 1, 2, 0, 0), (1, 3, 2, 0, 0))
        for cap, value, message in (("MAX_VERTICES", 3, "4 vertices, more than the 3"),
                                    ("MAX_LOOPS", 5, "6 face corners, more than the 5")):
            with self.subTest(cap=cap), mock.patch.object(geometry, cap, value),                     self.assertRaisesRegex(GeometryError, message):
                geometry.read_editable_mesh(mesh(mesh_verts(TRI), two))

    def test_empty_mesh(self):
        m = geometry.read_editable_mesh(mesh(mesh_verts([]), mesh_faces()))
        self.assertEqual(m.positions.shape, (0, 3))
        self.assertEqual(len(m.loop_starts), 0)

    def test_damaged(self):
        ok_faces = mesh_faces((0, 1, 2, 0, 0))
        cases = {
            "no geometry container": chunk_of(node(0x0014, leaf(0x2034, b"\0" * 4))),
            "no vertices": mesh(ok_faces),
            "no faces": mesh(mesh_verts(TRI)),
            "vertex count and size disagree": mesh(leaf(0x0914, struct.pack("<I3f", 2, 0, 0, 0)), ok_faces),
            "face count and size disagree": mesh(mesh_verts(TRI), leaf(0x0912, struct.pack("<I", 2) + b"\0" * 20)),
            "faces without a count": mesh(mesh_verts(TRI), leaf(0x0912, b"\0\0")),
            "vertex index past the end": mesh(mesh_verts(TRI), mesh_faces((0, 1, 4, 0, 0))),
            "map vertex index past the end": mesh(mesh_verts(TRI), ok_faces, mesh_map(1, [(0, 0, 0)], [(0, 0, 1)])),
            "fewer map faces than faces": mesh(mesh_verts(TRI), mesh_faces((0, 1, 2, 0, 0), (1, 2, 3, 0, 0)),
                                               mesh_map(1, [(0, 0, 0)], [(0, 0, 0)])),
            "map faces without a channel": mesh(mesh_verts(TRI), ok_faces,
                                                leaf(0x2396, struct.pack("<I3I", 1, 0, 0, 0))),
        }
        for name, c in cases.items():
            with self.subTest(name), self.assertRaises(GeometryError):
                geometry.read_editable_mesh(c)


_CLASSES = [
    (1, 0, 0x1, "Node"), (0xE44F10B3, 0, 0x10, "Editable Mesh"), (0x1BF8338D, 0x192F6098, 0x10, "Editable Poly"),
    (0x876234, 0, 0x50, "Dummy"), (0x1BF8338D, 0x192F6098, 0x50, "Not geometry"),
]


def class_entry(a, b, superclass, name):
    return node(0x2040, leaf(0x2060, struct.pack("<iIII", -1, a, b, superclass)),
                leaf(0x2042, name.encode("utf-16-le")))


@unittest.skipIf(numpy is None, "numpy missing")
class ReadMeshTest(unittest.TestCase):
    def setUp(self):
        classes = classdir.ClassDirectory.parse(b"".join(class_entry(*c) for c in _CLASSES))
        good_poly = node(geometry.GEOMETRY, poly_verts(QUAD), poly_faces(poly_face([0, 1, 2])))
        objects = [
            node(0, leaf(0x0962, b"")),                                         # 0 a node
            node(1, node(geometry.GEOMETRY, mesh_verts(TRI), mesh_faces((0, 1, 2, 0, 0)))),  # 1 Editable Mesh
            node(2, good_poly),                                                 # 2 Editable Poly
            node(3, leaf(0x0100, b"")),                                         # 3 Dummy
            node(4, good_poly),                                                 # 4 Poly's ClassId, another superclass
            node(2, node(geometry.GEOMETRY, poly_verts(QUAD), poly_faces(poly_face([0, 1, 9])))),  # 5 broken
            leaf(0x2032, b""),                                                  # 6 a special id
        ]
        self.scene = scene.Scene(node(0x2025, *objects), classes)

    def test_dispatch(self):
        self.assertEqual(len(geometry.read_mesh(self.scene, 1).loop_starts), 1)
        self.assertEqual(len(geometry.read_mesh(self.scene, 2).loop_starts), 1)
        for i in (0, 3, 4, 6):
            self.assertIsNone(geometry.read_mesh(self.scene, i))

    def test_a_broken_mesh_names_its_object(self):
        with self.assertRaisesRegex(GeometryError, r"object 5 \(Editable Poly\)"):
            geometry.read_mesh(self.scene, 5)
        self.assertIsInstance(GeometryError("x"), chunks.ChunkError)


def _oracle(path):
    with open(path[:-4] + ".oracle.json", encoding="utf-8") as f:
        return json.load(f)


def _meshes(path):
    """[(oracle node, MeshData or None)] in the oracle's node order."""
    out = []
    with cfb.CompoundFile(path) as cf:
        sc = scene.Scene.from_file(cf)
        oracle = _oracle(path)
        for i, entry in zip(sc.walk(), oracle["nodes"]):
            n = sc.node(i)
            base = sc.object_stack(n.object).base if n.object is not None else None
            out.append((entry, None if base is None else geometry.read_mesh(sc, base)))
    return out


@unittest.skipIf(numpy is None, "numpy missing")
class FixtureTest(unittest.TestCase):
    def test_counts_equal_the_oracle(self):
        self.assertTrue(FIXTURES)
        for path in FIXTURES:
            for entry, m in _meshes(path):
                with self.subTest(fixture=os.path.basename(path), node=entry["name"]):
                    if entry["base_class_name"] in ("Editable_Poly", "Editable_mesh"):
                        self.assertIsNotNone(m)
                        self.assertEqual(m.stored_vertices, entry["base_verts"])
                        self.assertEqual(m.stored_faces, entry["base_faces"])
                        self.assertEqual(len(m.positions), entry["base_verts"])
                        self.assertEqual(len(m.loop_starts), entry["base_faces"])
                        self.assertEqual(int(m.loop_totals.sum()), len(m.loop_vertices))
                        for channel in m.maps.values():
                            self.assertEqual(len(channel.indices), len(m.loop_vertices))
                    else:
                        self.assertIsNone(m)

    def test_box_poly_standard(self):
        (entry, m), = _meshes(_fixture("box_poly_standard"))
        self.assertEqual(len(m.positions), 8)
        self.assertEqual(m.loop_totals.tolist(), [4] * 6)
        self.assertEqual(list(m.maps), [1])
        self.assertEqual(len(m.maps[1].uvw), 24)
        # 20 x 30 x 40 box, pivot at the bottom centre: object space
        self.assertEqual(m.positions.min(axis=0).tolist(), [-10, -15, 0])
        self.assertEqual(m.positions.max(axis=0).tolist(), [10, 15, 40])
        # a Box's own IDs (bottom, top, front, right, back, left) and one smoothing group per side
        self.assertEqual((m.material_ids + 1).tolist(), [2, 1, 5, 4, 6, 3])
        self.assertEqual(m.smoothing_groups.tolist(), [2, 4, 8, 16, 32, 64])
        # every face of a box is planar: its loops use 4 distinct vertices
        for s in m.loop_starts:
            self.assertEqual(len(set(m.loop_vertices[s:s + 4].tolist())), 4)

    def test_editable_mesh(self):
        (entry, m), = _meshes(_fixture("editable_mesh"))
        self.assertEqual(m.loop_totals.tolist(), [3] * 12)
        # tools/fixtures/editable_mesh.ms: group 1 on bottom and top (faces 1-4), group 2 on the sides
        self.assertEqual(m.smoothing_groups.tolist(), [1] * 4 + [2] * 8)
        self.assertEqual((m.material_ids + 1).tolist(), [1, 1, 1, 1, 2, 2, 3, 3, 2, 2, 3, 3])
        self.assertEqual(list(m.maps), [1])

    def test_multi_uv(self):
        (entry, m), = _meshes(_fixture("multi_uv"))
        self.assertEqual(list(m.maps), [1, 2, 3])
        self.assertEqual([len(m.maps[c].uvw) for c in (1, 2, 3)], [12, 8, 13])
        for c in (1, 2, 3):
            self.assertEqual(len(m.maps[c].indices), 24)
        # channel 2 is a planar map 40 x 40 over a 20 x 20 box: u and v span half the unit square
        uv = m.maps[2].uvw[m.maps[2].indices]
        self.assertAlmostEqual(float(uv[:, 0].max() - uv[:, 0].min()), 0.5, places=4)
        self.assertAlmostEqual(float(uv[:, 1].max() - uv[:, 1].min()), 0.5, places=4)


if __name__ == "__main__":
    unittest.main()
