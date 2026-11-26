# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/scene/ on meshes: sharp edges (hostile ones too), the rim corners and their
peak memory, the unique-based rules and invalid faces, no Blender.

    python -I -m unittest discover tests
"""
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
from maxdrop_unit_tests.convert_scene_support import _quad_strip, conv, geometry, numpy  # noqa: E402 (after the loader)


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


def _rim_corners_whole(positions, loop_vertices, loop_starts, loop_totals, angle):
    """rim_corners as it was before it went in chunks (int64 and float64 arrays per corner of every boundary face),
    for the comparison."""
    loops, nxt = conv._open_loops(loop_vertices, loop_starts, loop_totals)
    if not len(loops):
        return 0
    lv = numpy.asarray(loop_vertices, dtype=numpy.int32)
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    p = numpy.asarray(positions, dtype=numpy.float64)
    oa, ob = lv[loops].astype(numpy.int64), lv[nxt].astype(numpy.int64)
    boundary = numpy.unique(numpy.concatenate((oa, ob)))
    slot = numpy.full(len(p), -1, dtype=numpy.int64)
    slot[boundary] = numpy.arange(len(boundary))
    touching = numpy.flatnonzero(slot[lv] >= 0)
    faces = numpy.unique(numpy.searchsorted(starts, touching, side="right") - 1)
    sizes = totals[faces]
    own = numpy.repeat(numpy.arange(len(faces)), sizes)
    first = numpy.repeat(starts[faces], sizes)
    fl = first + numpy.arange(int(sizes.sum())) - numpy.repeat(numpy.cumsum(sizes) - sizes, sizes)
    fn = fl + 1
    wrap = fn == first + sizes[own]
    fn[wrap] = first[wrap]
    normals = numpy.zeros((len(faces), 3))
    numpy.add.at(normals, own, numpy.cross(p[lv[fl]], p[lv[fn]]))
    length = numpy.linalg.norm(normals, axis=1)
    normals = numpy.divide(normals, length[:, None], out=numpy.zeros_like(normals), where=length[:, None] > 0)
    at = slot[lv[fl]]
    hit = at >= 0
    at_vertex = numpy.zeros((len(boundary), 3))
    numpy.add.at(at_vertex, at[hit], normals[own[hit]])
    rim = numpy.cross(p[ob] - p[oa], at_vertex[slot[oa]] + at_vertex[slot[ob]])
    length = numpy.linalg.norm(rim, axis=1)
    good = length > 0
    rim = numpy.divide(rim, length[:, None], out=numpy.zeros_like(rim), where=good[:, None])
    order = numpy.argsort(oa, kind="stable")
    at = numpy.minimum(numpy.searchsorted(oa[order], ob), len(oa) - 1)
    found = oa[order][at] == ob
    following = order[at]
    turn = numpy.einsum("ij,ij->i", rim, rim[following])
    sharp = found & good & good[following] & (turn < math.cos(math.radians(angle)))
    return int(sharp.sum())


def _rim_mesh(positions, faces):
    """A mesh in the reader's dtypes (float32 positions, int32 indices) from a list of faces."""
    sizes = numpy.asarray([len(f) for f in faces], dtype=numpy.int32)
    lv = numpy.asarray([v for f in faces for v in f], dtype=numpy.int32)
    starts = (numpy.cumsum(sizes) - sizes).astype(numpy.int32)
    return numpy.asarray(positions, dtype=numpy.float32), lv, starts, sizes


def _rim_grid(nx, ny, skip=()):
    positions = [(x, y, 0) for y in range(ny + 1) for x in range(nx + 1)]
    return _rim_mesh(positions, [[y * (nx + 1) + x, y * (nx + 1) + x + 1, (y + 1) * (nx + 1) + x + 1,
                                  (y + 1) * (nx + 1) + x] for y in range(ny) for x in range(nx) if (x, y) not in skip])


def _rim_strip(n):
    """A 1 x n strip of unit quads: every face on the boundary, four rim corners."""
    x = numpy.arange(n + 1, dtype=numpy.float32)
    positions = numpy.concatenate((numpy.stack((x, numpy.zeros_like(x), numpy.zeros_like(x)), axis=1),
                                   numpy.stack((x, numpy.ones_like(x), numpy.zeros_like(x)), axis=1)))
    k = numpy.arange(n, dtype=numpy.int32)
    lv = numpy.stack((k, k + 1, n + 2 + k, n + 1 + k), axis=1).ravel()
    return positions, lv, numpy.arange(0, 4 * n, 4, dtype=numpy.int32), numpy.full(n, 4, dtype=numpy.int32)


def _rim_soup(n, seed=1):
    """n loose triangles at random places: every edge open, every vertex its own."""
    positions = numpy.random.default_rng(seed).random((3 * n, 3)).astype(numpy.float32)
    return (positions, numpy.arange(3 * n, dtype=numpy.int32), numpy.arange(0, 3 * n, 3, dtype=numpy.int32),
            numpy.full(n, 3, dtype=numpy.int32))


def _rim_pool(n, vertices, seed=2):
    """n faces of 3 to 7 corners over a small pool of random vertices: shared and non-manifold edges, several open
    edges leaving one vertex, faces across the chunks of rim_corners."""
    rng = numpy.random.default_rng(seed)
    positions = rng.random((vertices, 3)).astype(numpy.float32)
    sizes = rng.integers(3, 8, n).astype(numpy.int32)
    lv = numpy.concatenate([rng.choice(vertices, s, replace=False) for s in sizes]).astype(numpy.int32)
    return positions, lv, (numpy.cumsum(sizes) - sizes).astype(numpy.int32), sizes


@unittest.skipIf(numpy is None, "numpy missing")
class RimCornersPeak(unittest.TestCase):
    """rim_corners in chunks: the same count as the whole-mesh arrays, int32 indices, a peak at _open_loops' level
    (maxdrop-em3.146)."""

    def same(self, mesh, angles=(30.0, 45.0, 100.0)):
        for angle in angles:
            self.assertEqual(conv.rim_corners(*mesh, angle), _rim_corners_whole(*mesh, angle), angle)

    def test_small_meshes_as_before(self):
        quad = _rim_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [[0, 1, 2, 3]])
        cube = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
        sides = [[0, 3, 2, 1], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
        for mesh, want in ((quad, 4), (_rim_mesh(quad[0], [[0, 3, 2, 1]]), 4), (_rim_mesh(cube, sides), 0),
                           (_rim_mesh(cube, sides + [[4, 5, 6, 7]]), 0), (_rim_grid(3, 3), 4),
                           (_rim_grid(3, 3, skip={(1, 1)}), 8), (_rim_grid(2, 2, skip={(1, 1)}), 6)):
            self.assertEqual(conv.rim_corners(*mesh, 45.0), want)
            self.same(mesh)
        self.assertEqual(conv.rim_corners(*quad, 100.0), 0)
        # as lists, as the callers' tests pass them
        self.assertEqual(conv.rim_corners([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [0, 1, 2, 3], [0], [4], 45.0),
                         4)

    def test_shared_vertices_and_flat_faces_as_before(self):
        # a bow tie: two open edges leave vertex 0
        bow = _rim_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (-1, 0, 0), (-1, -1, 0)], [[0, 1, 2], [0, 3, 4]])
        # a face of no area on the boundary beside a quad
        flat = _rim_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0)], [[0, 1, 2, 3], [0, 1, 4]])
        for mesh in (bow, flat, _rim_pool(2000, 300)):
            self.same(mesh, (10.0, 30.0, 45.0, 100.0, 170.0))

    def test_meshes_over_several_chunks_as_before(self):
        chunk = conv.geometry.CHECK_EVERY
        self.same(_rim_pool(chunk // 2, 5000))  # about 2.5 chunks of corners, faces across the chunk edges
        self.same(_rim_soup(chunk))  # 3 chunks of corners and of open edges
        strip = _rim_strip(chunk)
        self.assertEqual(conv.rim_corners(*strip, 45.0), 4)
        self.same(strip)
        # one face longer than a chunk, a polygon around a circle, with a quad on one of its edges
        n = chunk + 1000
        t = numpy.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
        ring = [(math.cos(a), math.sin(a), 0.0) for a in t] + [(1.0, 0.0, 1.0), (math.cos(t[1]), math.sin(t[1]), 1.0)]
        self.same(_rim_mesh(ring, [list(range(n)), [1, 0, n, n + 1]]))

    def test_indices_int32_and_floats_per_face_or_vertex(self):
        chunk = conv.geometry.CHECK_EVERY
        seen = []

        def check():
            frame = sys._getframe(1)
            if frame.f_code.co_name != "rim_corners":
                return
            given = frame.f_code.co_varnames[:frame.f_code.co_argcount]  # the mesh as passed
            for name, value in frame.f_locals.items():
                if name in given or not isinstance(value, numpy.ndarray):
                    continue
                seen.append(name)
                if value.dtype.kind in "iu" and value.size > chunk:
                    self.assertEqual(value.dtype, numpy.int32, name)
                elif value.dtype.kind == "b":
                    self.assertLessEqual(value.size, chunk, name)
                elif value.dtype.kind == "f" and value.size > 3 * chunk:
                    self.assertIn(name, ("p", "normals", "at_vertex"), name)

        for mesh in (_rim_strip(2 * chunk), _rim_soup(chunk)):
            self.assertEqual(conv.rim_corners(*mesh, 45.0, check=check), _rim_corners_whole(*mesh, 45.0))
        self.assertTrue({"slot", "oa", "ob", "faces"} <= set(seen), seen)

    def test_corner_cap_fits_int32(self):
        # rim_corners and _open_loops count face corners in int32 (ends, following), which wraps silently past 2**31
        self.assertLess(conv.geometry.MAX_LOOPS, 2 ** 31)

    def test_peak_at_open_loops_level(self):
        # rim_corners calls _open_loops, so the peak is at least its own; past it, at_vertex (24 bytes per boundary
        # vertex) and one chunk's temporaries reach about 1.02 x at this size: 1.25 leaves room for numpy versions,
        # the old body was 3.5 to 4.7 x
        import tracemalloc
        for mesh in (_rim_strip(200000), _rim_soup(200000)):
            lv, starts, totals = mesh[1:]
            tracemalloc.start()
            try:
                conv._open_loops(lv, starts, totals)
                base = tracemalloc.get_traced_memory()[1]
                tracemalloc.reset_peak()
                conv.rim_corners(*mesh, 45.0)
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            self.assertLessEqual(peak, 1.25 * base, (len(lv), peak, base))


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


if __name__ == "__main__":
    unittest.main()
