# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the tests of maxdrop/convert/extrude/ share: numpy when present, the fixture, the package loaded
without Blender, patch_all, the mesh measures and the shape builders."""
import importlib
import importlib.util
import os
import sys
import types


try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "extrude.max")
BBOX_TOLERANCE = 1e-3

_PKG = "maxdrop_convert_test"  # the same package as test_convert_scene: the add-on's __init__ never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
conv = importlib.import_module(_PKG + ".convert.scene")
extrude = importlib.import_module(_PKG + ".convert.extrude")
shapes = importlib.import_module(_PKG + ".reader.shapes")
pblock = importlib.import_module(_PKG + ".reader.pblock")
classids = importlib.import_module(_PKG + ".reader.classids")
reader_modifiers = importlib.import_module(_PKG + ".reader.modifiers")
rules = importlib.import_module(_PKG + ".convert.modifiers")
_spec_patching = importlib.util.spec_from_file_location("maxdrop_test_patching",
                                                        os.path.join(ROOT, "tests", "patching.py"))
patching = importlib.util.module_from_spec(_spec_patching)
_spec_patching.loader.exec_module(patching)  # patch_all(): a split package's modules read their own names

CAPPED = ("FixtureExtRect", "FixtureExtL", "FixtureExtHole", "FixtureExtIsland", "FixtureExtMirror",
          "FixtureExtAdaptive", "FixtureExtShapeIDs", "FixtureExtShapeIDsRect", "FixtureExtGrid")
UNCAPPED = ("FixtureExtOpen", "FixtureExtGridCircle",  # no cap; Cap End off (a grid cap at the start)
            "FixtureExtDownStart", "FixtureExtDownEndReal")  # downwards, one cap each
# V - E + F of each mesh: a box-like solid 2, a solid with a tunnel (the round hole) 0, the island's ring and its
# core 0 + 2
EULER = {"FixtureExtRect": 2, "FixtureExtL": 2, "FixtureExtHole": 0, "FixtureExtIsland": 2, "FixtureExtMirror": 2,
         "FixtureExtAdaptive": 2, "FixtureExtShapeIDs": 0, "FixtureExtShapeIDsRect": 2, "FixtureExtGrid": 0}


def _edges(md):
    """{(a, b): count} of directed edges."""
    out = {}
    for s, t in zip(md.loop_starts.tolist(), md.loop_totals.tolist()):
        loop = md.loop_vertices[s:s + t].tolist()
        for k in range(t):
            e = (loop[k], loop[(k + 1) % t])
            out[e] = out.get(e, 0) + 1
    return out


def _volume(positions, md):
    p = numpy.asarray(positions, dtype=numpy.float64)
    total = 0.0
    for s, t in zip(md.loop_starts.tolist(), md.loop_totals.tolist()):
        loop = md.loop_vertices[s:s + t].tolist()
        for k in range(1, t - 1):
            total += numpy.dot(p[loop[0]], numpy.cross(p[loop[k]], p[loop[k + 1]])) / 6.0
    return total


def _mats(md):
    """Material indices of a MeshDescription or a reader MeshData."""
    return md.material_indices if hasattr(md, "material_indices") else md.material_ids


def _face_area_z(md, f):
    """The signed area of face f projected on XY (positive: it faces +Z)."""
    s, t = int(md.loop_starts[f]), int(md.loop_totals[f])
    p = md.positions[md.loop_vertices[s:s + t]].astype(numpy.float64)
    return 0.5 * float(numpy.sum(p[:, 0] * numpy.roll(p[:, 1], -1) - numpy.roll(p[:, 0], -1) * p[:, 1]))


def _face_area(md, f):
    """The area of face f (half the length of its Newell normal)."""
    s, t = int(md.loop_starts[f]), int(md.loop_totals[f])
    p = md.positions[md.loop_vertices[s:s + t]].astype(numpy.float64)
    return 0.5 * float(numpy.linalg.norm(numpy.cross(p, numpy.roll(p, -1, axis=0)).sum(axis=0)))


def _check_eval_mesh(test, data, md, want, name):
    """data (the reader MeshData: object space, before the object offset, as the oracle takes it back to) and md
    (its MeshDescription) against the oracle's eval_mesh of the node."""
    hist = {}
    for f in range(len(data.loop_starts)):
        z = _face_area_z(data, f)  # the winding normal's z, times the polygon's area
        if abs(z) <= 1e-4 * _face_area(data, f):
            side = 3
        else:
            side = 1 if z > 0 else 2
        row = hist.setdefault(int(_mats(data)[f]) + 1, [0, 0, 0])
        row[side - 1] += int(data.loop_totals[f]) - 2  # 3ds Max counts triangles
    test.assertEqual([[i] + hist[i] for i in sorted(hist)], want["material_ids"], name)
    channel = data.maps.get(1)
    test.assertEqual(channel is None, want["map_channel_1"] is None, name)
    if channel is None:
        return
    uvw = numpy.asarray(channel.uvw, dtype=numpy.float64)
    used = uvw[numpy.unique(channel.indices)]
    test.assertEqual(len(uvw), want["map_channel_1"]["count"], name)
    for got, key in ((used.min(axis=0), "min"), (used.max(axis=0), "max")):  # 6 significant digits
        numpy.testing.assert_allclose(got, want["map_channel_1"][key], rtol=1e-5, atol=1e-6, err_msg=name)
    uv = dict(md.uv_layers)["UVMap"]  # what Blender gets: u and v of the same vertices
    for got, key in ((uv.min(axis=0), "min"), (uv.max(axis=0), "max")):
        numpy.testing.assert_allclose(got, want["map_channel_1"][key][:2], rtol=1e-5, atol=1e-6, err_msg=name)


def _read_meshes(path):
    """(scene description, {node name: reader MeshData}) of a fixture: the MeshData keeps its map vertices."""
    data = {}
    real = conv.mesh_description

    def describing(key, name, d, *args, **kw):
        data[name] = d
        return real(key, name, d, *args, **kw)

    with patching.patch_all(conv, "mesh_description", describing):
        desc = conv.read(path)
    return desc, data


def _knots(points, kind=shapes.CORNER):
    return tuple(shapes.Knot(kind, shapes.LINE, p, p, p) for p in points)


def _shape(splines, steps=6, optimize=True, adaptive=False):
    return shapes.Shape(shapes.classids.SPLINE_SHAPE, tuple(splines), steps, optimize, adaptive,
                        shapes.DEFAULT_RENDER, ())


def _points(shape):
    return sum(len(pl.points) for pl in extrude.polylines(shape))


def _segment(p0, c1, c2, p3):
    """An open spline of one curve segment between two Bezier-corner knots: c1 the out vector, c2 the in vector."""
    k = shapes.Knot
    return shapes.Spline((k(shapes.BEZIER_CORNER, shapes.CURVE, p0, p0, c1),
                          k(shapes.BEZIER_CORNER, shapes.CURVE, p3, c2, p3)), False)


def _off(e, chord=10.0):
    return chord * 10 ** -e


class FakeBlock:
    def __init__(self, values):
        self.values = values

    def get(self, i, default=None):
        return self.values.get(i, default)
