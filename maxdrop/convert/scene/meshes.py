# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Meshes: edges, rims of open borders, areas, valid faces and mesh_description()."""
import math

from ...reader import geometry
from .. import lights
from .descriptions import determinant3, MAX_EDGE_MASKS, MeshDescription, MeshError, UV_FIRST, UV_NAME


def sharp_edges(loop_vertices, loop_starts, loop_totals, groups):
    """The edges, as sorted vertex pairs int32 (E, 2), where two faces meet that share no smoothing group."""
    import numpy
    # int32 per loop where it fits (indices are int32, reader.geometry), int64 only for the key: the arrays per loop
    # are the peak of a mesh's conversion
    lv = numpy.asarray(loop_vertices, dtype=numpy.int32)
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    if not len(lv):
        return numpy.zeros((0, 2), dtype=numpy.int32)
    face = numpy.repeat(numpy.arange(len(starts), dtype=numpy.int32), totals)
    following = numpy.arange(1, len(lv) + 1, dtype=numpy.int32)
    following[starts + totals - 1] = starts  # the last loop of a face closes it
    b = lv[following]
    del following
    lo, hi = numpy.minimum(lv, b), numpy.maximum(lv, b)
    del b
    key = lo.astype(numpy.int64)
    key *= int(lv.max()) + 1
    key += hi
    order = numpy.argsort(key, kind="stable")
    key, face = key[order], face[order]
    groups = numpy.asarray(groups, dtype=numpy.uint32)
    first = numpy.flatnonzero(numpy.concatenate(([True], key[1:] != key[:-1])))  # key is sorted: its runs
    counts = numpy.diff(numpy.append(first, len(key)))
    two = first[counts == 2]
    sharp = two[(groups[face[two]] & groups[face[two + 1]]) == 0]
    more = [start for start, n in zip(first[counts > 2], counts[counts > 2])
            if _disjoint(groups[face[start:start + n]])]
    if more:
        sharp = numpy.sort(numpy.concatenate((sharp, numpy.asarray(more, dtype=sharp.dtype))))
    src = order[sharp]
    return numpy.stack((lo[src], hi[src]), axis=1).astype(numpy.int32)


def open_edges(loop_vertices, loop_starts, loop_totals, check=None):
    """The edges only one face uses (the mesh's boundary), as sorted vertex pairs int32 (E, 2) in sharp_edges()'s
    order. check() between the passes."""
    import numpy
    loops, following = _open_loops(loop_vertices, loop_starts, loop_totals, check)
    lv = numpy.asarray(loop_vertices, dtype=numpy.int32)
    a, b = lv[loops], lv[following]
    return _merged_edges(numpy.stack((numpy.minimum(a, b), numpy.maximum(a, b)), axis=1), numpy.zeros((0, 2)))


def _open_loops(loop_vertices, loop_starts, loop_totals, check=None):
    """(loops, following): the loops whose edge to the next loop of their face no other loop has (the open edges, in
    their face's winding) and those next loops, int64 arrays as long as the boundary. Per loop only an int32 and the
    int64 edge key, as in sharp_edges(): the arrays per loop are the peak of a mesh's conversion."""
    import numpy
    lv = numpy.asarray(loop_vertices, dtype=numpy.int32)
    empty = numpy.zeros(0, dtype=numpy.int64)
    if not len(lv):
        return empty, empty
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    following = numpy.arange(1, len(lv) + 1, dtype=numpy.int32)
    following[starts + totals - 1] = starts  # the last loop of a face closes it
    b = lv[following]
    del following
    key = numpy.minimum(lv, b).astype(numpy.int64)
    key *= int(lv.max()) + 1
    key += numpy.maximum(lv, b)
    del b
    order = numpy.argsort(key, kind="stable")
    key = key[order]
    if check is not None:
        check()
    first = numpy.flatnonzero(numpy.concatenate(([True], key[1:] != key[:-1])))
    counts = numpy.diff(numpy.append(first, len(key)))
    del key
    loops = numpy.sort(order[first[counts == 1]]).astype(numpy.int64)
    face = numpy.searchsorted(starts, loops, side="right") - 1
    nxt = loops + 1
    wrap = nxt == starts[face] + totals[face]
    nxt[wrap] = starts[face[wrap]]
    return loops, nxt


def _merged_edges(a, b):
    """The union of two arrays of sorted vertex pairs (E, 2), sorted and without repeats."""
    import numpy
    pairs = numpy.concatenate((numpy.asarray(a, dtype=numpy.int64).reshape(-1, 2),
                               numpy.asarray(b, dtype=numpy.int64).reshape(-1, 2)))
    if not len(pairs):
        return numpy.zeros((0, 2), dtype=numpy.int32)
    n = int(pairs.max()) + 1
    keys = numpy.unique(pairs[:, 0] * n + pairs[:, 1])
    return numpy.stack((keys // n, keys % n), axis=1).astype(numpy.int32)


def rim_corners(positions, loop_vertices, loop_starts, loop_totals, angle, check=None):
    """How many corners of the rim a Shell builds on this mesh turn by more than angle degrees: at each boundary
    vertex two rim faces meet, each along an open edge a -> b (its face's winding) and the shell's offset direction
    at its ends, so its normal is (pb - pa) x (na + nb), n the sum of the unit face normals at a vertex. 3ds Max's
    auto smooth splits the rim there; with the open edges sharp, Blender's Solidify keeps it smooth. Only the faces
    at the boundary are measured; check() between the passes and their chunks.

    Kept at _open_loops()' peak: int32 indices (vertex indices are int32 and face corners below
    reader.geometry.MAX_LOOPS), the work per face corner and per open edge in chunks of geometry.CHECK_EVERY, kept
    only as sums per boundary face and per boundary vertex; a chunk may split a face (numpy.add.at sums in corner
    order, as one pass would)."""
    import numpy
    loops, nxt = _open_loops(loop_vertices, loop_starts, loop_totals, check)
    if not len(loops):
        return 0
    chunk = geometry.CHECK_EVERY
    lv = numpy.asarray(loop_vertices, dtype=numpy.int32)
    starts = numpy.asarray(loop_starts, dtype=numpy.int32)
    totals = numpy.asarray(loop_totals, dtype=numpy.int32)
    p = numpy.asarray(positions)  # float32 from the reader: each chunk takes float64 (exact)
    oa, ob = lv[loops], lv[nxt]
    del loops, nxt
    boundary = numpy.unique(numpy.concatenate((oa, ob)))
    slot = numpy.full(len(p), -1, dtype=numpy.int32)  # vertex -> its place in boundary, -1 off the boundary
    slot[boundary] = numpy.arange(len(boundary), dtype=numpy.int32)
    n_boundary = len(boundary)
    del boundary
    if check is not None:
        check()
    parts = []
    for a in range(0, len(lv), chunk):
        # int32 like starts: searchsorted would copy starts to int64 on every chunk
        touching = (numpy.flatnonzero(slot[lv[a:a + chunk]] >= 0) + a).astype(numpy.int32)
        parts.append(numpy.unique(numpy.searchsorted(starts, touching, side="right") - 1).astype(numpy.int32))
        if check is not None:
            check()
    faces = numpy.unique(numpy.concatenate(parts))
    del parts
    sizes = totals[faces]
    ends = numpy.cumsum(sizes, dtype=numpy.int32)  # those faces' corners one after the other: where each ends

    def corners(a):
        """(own, fl, fn) of the corners a to a + chunk of the boundary faces: the face among them, the loop and the
        next loop of its face."""
        k = numpy.arange(a, min(a + chunk, int(ends[-1])), dtype=numpy.int32)  # as ends, for searchsorted
        own = numpy.searchsorted(ends, k, side="right")
        first = starts[faces[own]].astype(numpy.int64)
        fl = first + (k - (ends[own] - sizes[own]))
        fn = fl + 1
        wrap = fn == first + sizes[own]
        fn[wrap] = first[wrap]
        return own, fl, fn

    normals = numpy.zeros((len(faces), 3))
    for a in range(0, int(ends[-1]), chunk):
        own, fl, fn = corners(a)
        # Newell: twice the area along the normal
        numpy.add.at(normals, own, numpy.cross(p[lv[fl]].astype(numpy.float64), p[lv[fn]].astype(numpy.float64)))
        if check is not None:
            check()
    length = numpy.linalg.norm(normals, axis=1)
    normals = numpy.divide(normals, length[:, None], out=numpy.zeros_like(normals), where=length[:, None] > 0)
    del length
    at_vertex = numpy.zeros((n_boundary, 3))
    for a in range(0, int(ends[-1]), chunk):
        own, fl, _fn = corners(a)
        at = slot[lv[fl]]
        hit = at >= 0
        numpy.add.at(at_vertex, at[hit], normals[own[hit]])
        if check is not None:
            check()
    del normals

    def rim(e):
        """(unit rim normals, nonzero) of the open edges e."""
        pa, pb = p[oa[e]].astype(numpy.float64), p[ob[e]].astype(numpy.float64)
        r = numpy.cross(pb - pa, at_vertex[slot[oa[e]]] + at_vertex[slot[ob[e]]])
        length = numpy.linalg.norm(r, axis=1)
        good = length > 0
        return numpy.divide(r, length[:, None], out=numpy.zeros_like(r), where=good[:, None]), good

    order = numpy.argsort(oa, kind="stable").astype(numpy.int32)
    ordered = oa[order]
    cos = math.cos(math.radians(angle))
    sharp = 0
    for a in range(0, len(oa), chunk):
        e = numpy.arange(a, min(a + chunk, len(oa)), dtype=numpy.int64)
        at = numpy.minimum(numpy.searchsorted(ordered, ob[e]), len(oa) - 1)
        found = ordered[at] == ob[e]  # the open edge leaving the vertex this one ends at
        following = order[at]
        here, good = rim(e)
        there, good_there = rim(following)
        turn = numpy.einsum("ij,ij->i", here, there)
        sharp += int((found & good & good_there & (turn < cos)).sum())
        if check is not None:
            check()
    return sharp


def _disjoint(masks):
    """Whether two of the smoothing-group masks of one non-manifold edge share no group. Equal non-zero masks always
    share one, so only the distinct masks are paired, at most MAX_EDGE_MASKS of them: a file can put any number of
    faces on one edge, and an edge past the cap is taken as sharp."""
    distinct = {int(v) for v in masks}
    if 0 in distinct or len(distinct) > MAX_EDGE_MASKS:
        return True
    distinct = sorted(distinct)
    return any(x & y == 0 for k, x in enumerate(distinct) for y in distinct[k + 1:])


def mesh_area(positions, loop_vertices, loop_starts, loop_totals, keep=None):
    """The total area of a mesh's polygons (Newell's vector of each, so a polygon that is not flat counts its
    projected area), in the square of the positions' unit; keep (bool (F,)): only those polygons."""
    import numpy
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    some = totals > 0
    if keep is not None:
        keep = numpy.asarray(keep, dtype=bool)[some]
    starts, totals = starts[some], totals[some]
    if not len(starts):
        return 0.0
    p = numpy.asarray(positions, dtype=numpy.float64)[numpy.asarray(loop_vertices, dtype=numpy.int64)]
    following = numpy.arange(1, len(p) + 1)
    following[starts + totals - 1] = starts
    newell = numpy.add.reduceat(numpy.cross(p, p[following]), starts, axis=0)
    areas = numpy.sqrt((newell * newell).sum(axis=1))
    return float((areas[keep] if keep is not None else areas).sum() / 2.0)


def valid_faces(loop_vertices, loop_starts, loop_totals):
    """bool (F,): False for a face Blender cannot hold, one of fewer than three vertices, one that uses a vertex twice
    or has the vertex set of an earlier face (3ds Max keeps both: degenerate and doubled triangles occur in files)."""
    import numpy
    lv = numpy.asarray(loop_vertices, dtype=numpy.int64)
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    keep = totals >= 3
    for total in numpy.unique(totals[keep]):  # one numpy pass per face size
        faces = numpy.flatnonzero(totals == total)
        rows = numpy.sort(lv[starts[faces][:, None] + numpy.arange(total)], axis=1)
        repeated = (numpy.diff(rows, axis=1) == 0).any(axis=1)
        keep[faces[repeated]] = False
        good = faces[~repeated]
        if not len(good):
            continue
        rows = rows[~repeated]
        order = numpy.lexsort(rows.T)  # stable: the earliest face of equal rows comes first
        rows = rows[order]
        later = order[1:][(rows[1:] == rows[:-1]).all(axis=1)]
        keep[good[later]] = False
    return keep


def _reversed_loops(loop_starts, loop_totals):
    """The loop permutation that reverses every polygon in place."""
    import numpy
    starts = numpy.asarray(loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(loop_totals, dtype=numpy.int64)
    face = numpy.repeat(numpy.arange(len(starts)), totals)
    return 2 * starts[face] + totals[face] - 1 - numpy.arange(int(totals.sum()))


def _positions(data, offset, meters):
    """The float64 positions (V, 3) of reader MeshData data, the offset (a reader matrix, or None) applied, then
    meters; MeshError when one is not a number Blender's single precision holds (inf, NaN, past the largest
    float32)."""
    import numpy
    with numpy.errstate(over="ignore", invalid="ignore"):  # inf and NaN are refused below
        p = numpy.asarray(data.positions, dtype=numpy.float64)
        if offset is not None:
            m = numpy.asarray(offset, dtype=numpy.float64)
            p = p @ m[:3, :3] + m[3, :3]
        p = p * meters
    if not (numpy.abs(p) < lights.MAX_FLOAT).all():  # False for NaN too
        raise MeshError("its points do not fit single precision (Blender's meshes hold no larger value)")
    return p


def mesh_description(key, name, data, offset, meters, check=None):
    """A MeshDescription of reader MeshData: faces Blender cannot hold left out (counted in dropped_faces), the
    offset (a reader matrix) applied, then meters; MeshError when a position does not fit single precision
    (_positions). U and V coordinates that are not numbers become 0 (counted in zeroed_uvs). check() between the
    numpy passes of a mesh of more than reader.geometry.CHECK_EVERY face corners; what it raises passes
    unchanged."""
    import numpy
    if check is not None and len(data.loop_vertices) <= geometry.CHECK_EVERY:
        check = None  # one pass of a small mesh is quick: the call counts stay once per node
    positions = _positions(data, offset, meters).astype(numpy.float32)
    starts = numpy.asarray(data.loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(data.loop_totals, dtype=numpy.int64)
    lv = numpy.asarray(data.loop_vertices, dtype=numpy.int32)
    groups, materials = data.smoothing_groups, data.material_ids
    loops = None  # the loops kept, in their new order; None = all, unchanged
    if check is not None:
        check()
    keep = valid_faces(lv, starts, totals)
    dropped = int(len(keep) - keep.sum())
    if dropped:
        loops = numpy.flatnonzero(numpy.repeat(keep, totals))
        totals, groups, materials = totals[keep], groups[keep], materials[keep]
        starts = numpy.zeros(len(totals), dtype=numpy.int64)
        if len(totals):
            numpy.cumsum(totals[:-1], out=starts[1:])
    if offset is not None and determinant3(offset) < 0:
        perm = _reversed_loops(starts, totals)
        loops = perm if loops is None else loops[perm]
    if loops is not None:
        lv = lv[loops]
    uv_layers = []
    zeroed = 0
    for channel in sorted(c for c in data.maps if c >= 1):
        if check is not None:
            check()
        mc = data.maps[channel]
        indices = mc.indices if loops is None else mc.indices[loops]
        uv = numpy.ascontiguousarray(mc.uvw[indices][:, :2], dtype=numpy.float32)  # a copy: mc.uvw is the reader's
        bad = ~numpy.isfinite(uv)
        if bad.any():
            zeroed += int(bad.sum())
            uv[bad] = 0.0
        uv_layers.append((UV_FIRST if channel == 1 else UV_NAME % channel, uv))
    if check is not None:
        check()
    sharp = sharp_edges(lv, starts, totals, groups)
    return MeshDescription(key, name, positions, lv, starts.astype(numpy.int32), totals.astype(numpy.int32),
                           materials.astype(numpy.int32), groups == 0, sharp, uv_layers, dropped, zeroed)
