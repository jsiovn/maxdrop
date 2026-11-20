# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Synthetic Editable Poly objects for the benchmarks (tests/unit/test_perf.py, tests/blender/bench.py): no 3ds Max,
no scene of anyone's.

    data = poly_object(1_000_000)       # bytes: one object chunk holding a 0x08FE geometry container
    chunk = chunks.index(data)[0]       # what reader.geometry.read_editable_poly takes

A grid of quads, every third one split into two triangles, written the way 3ds Max writes Editable Poly records
(reader/geometry.py): every face with its flags, material ID and smoothing groups, the quads with their diagonals.
Smoothing groups change every few rows (sharp edges between the bands, a flat row now and then), material IDs cycle
over four, one map channel with a map vertex per vertex. Every DOUBLED-th face comes again at the end with its
vertices turned, and the first two vertices of every DEGENERATE-th face as a triangle (a, a, b): faces
convert.scene.valid_faces leaves out. The records are laid out with numpy, so a million faces take a fraction of a second; the same arguments
give the same bytes.

timed(work, reference) is how the benchmarks time a ratio. reference_loop() and describe_reference() are the
reference workloads they divide the read and the description by: plain Python record walking of the kind
reader.geometry._poly_faces does, and the numpy calls convert.scene.mesh_description makes (sorts and allocations
included, on the mesh's own loop vertices), timed on the same machine in the same process. Importing this module
needs numpy.
"""
import array
import struct
import time

import numpy

OBJECT = 0x0013  # any container id: read_editable_poly only looks for the geometry container inside
GEOMETRY = 0x08FE
VERTS, FACES, MAP_CHANNEL, MAP_VERTS, MAP_FACES = 0x0100, 0x011A, 0x0124, 0x0128, 0x012B
MASK = 0x01 | 0x08 | 0x10  # flags, material ID, smoothing groups
DIAGONALS = 0x20
DOUBLED = 1000
DEGENERATE = 5000
BAND = 8  # rows per smoothing-group band


def _leaf(cid, payload):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def _node(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def _put(buf, offsets, values, dtype):
    """Write values (one per offset) as dtype at byte offsets of buf (uint8)."""
    raw = numpy.ascontiguousarray(values, dtype=dtype).view(numpy.uint8).reshape(len(offsets), -1)
    buf[offsets[:, None] + numpy.arange(raw.shape[1])] = raw


def faces_of(n):
    """(positions float32 (V, 3), degrees int64 (F,), loop vertices int64 (L,), smoothing uint32 (F,), material IDs
    uint16 (F,)) of about n faces, the doubled and degenerate ones included."""
    quads = max(1, -(-3 * n // 4))
    cols = max(1, int(quads ** 0.5))
    rows = -(-quads // cols)
    k = numpy.arange(quads)
    r, c = k // cols, k % cols
    v0 = r * (cols + 1) + c
    corners = numpy.stack((v0, v0 + 1, v0 + cols + 2, v0 + cols + 1), axis=1)
    split = k % 3 == 2
    whole = corners[~split]
    tri = corners[split]
    tris = numpy.concatenate((tri[:, [0, 1, 2]], tri[:, [0, 2, 3]]))
    # in grid order, so that the smoothing bands follow the rows
    face_rows = numpy.concatenate((r[~split], r[split], r[split]))
    face_cols = numpy.concatenate((c[~split], c[split], c[split]))
    order = numpy.lexsort((face_cols, face_rows))
    src_deg = numpy.concatenate((numpy.full(len(whole), 4), numpy.full(len(tris), 3)))
    deg = src_deg[order]
    src_starts = numpy.concatenate((numpy.zeros(1, numpy.int64), numpy.cumsum(src_deg)[:-1]))
    src_loops = numpy.concatenate((whole.ravel(), tris.ravel()))
    lv = src_loops[numpy.repeat(src_starts[order], deg) + _within(deg)]
    face_rows, face_cols = face_rows[order], face_cols[order]
    smoothing = (numpy.uint32(1) << (face_rows // BAND % 4).astype(numpy.uint32)).astype(numpy.uint32)
    smoothing[face_rows % 50 == 0] = 0
    materials = (face_cols % 4).astype(numpy.uint16)
    # doubled faces: the same vertices, turned by one
    first = numpy.concatenate((numpy.zeros(1, numpy.int64), numpy.cumsum(deg)[:-1]))
    again = numpy.arange(0, len(deg), DOUBLED)
    turned = numpy.concatenate([numpy.roll(lv[first[f]:first[f] + deg[f]], 1) for f in again])
    # degenerate triangles (a, a, b) from the first two vertices of a face
    bad = numpy.arange(0, len(deg), DEGENERATE)
    broken = numpy.stack((lv[first[bad]], lv[first[bad]], lv[first[bad] + 1]), axis=1).ravel()
    deg = numpy.concatenate((deg, deg[again], numpy.full(len(bad), 3)))
    lv = numpy.concatenate((lv, turned, broken))
    smoothing = numpy.concatenate((smoothing, smoothing[again], smoothing[bad]))
    materials = numpy.concatenate((materials, materials[again], materials[bad]))
    gy, gx = numpy.divmod(numpy.arange((rows + 1) * (cols + 1)), cols + 1)
    positions = numpy.stack((gx, gy, (gx * 7 + gy * 3) % 5 * 0.1), axis=1).astype(numpy.float32)
    return positions, deg.astype(numpy.int64), lv.astype(numpy.int64), smoothing, materials


def _within(deg):
    """0, 1, .. deg[i] - 1 for each face, concatenated."""
    starts = numpy.concatenate((numpy.zeros(1, numpy.int64), numpy.cumsum(deg)[:-1]))
    return numpy.arange(int(deg.sum())) - numpy.repeat(starts, deg)


def _face_records(deg, lv, smoothing, materials):
    """The 0x011A payload: u32 count, then per face u32 degree, the vertices, u16 mask, u32 flags, u16 material ID,
    u32 smoothing groups and, for a quad, its two diagonals."""
    quad = deg > 3
    sizes = 4 + 4 * deg + 2 + 4 + 2 + 4 + numpy.where(quad, 8 * (deg - 3), 0)
    offsets = 4 + numpy.concatenate((numpy.zeros(1, numpy.int64), numpy.cumsum(sizes)[:-1]))
    buf = numpy.zeros(4 + int(sizes.sum()), dtype=numpy.uint8)
    buf[:4] = numpy.frombuffer(struct.pack("<I", len(deg)), dtype=numpy.uint8)
    _put(buf, offsets, deg, "<u4")
    _put(buf, numpy.repeat(offsets + 4, deg) + 4 * _within(deg), lv, "<u4")
    mask_at = offsets + 4 + 4 * deg
    _put(buf, mask_at, numpy.where(quad, MASK | DIAGONALS, MASK), "<u2")
    _put(buf, mask_at + 2, numpy.zeros(len(deg)), "<u4")
    _put(buf, mask_at + 6, materials, "<u2")
    _put(buf, mask_at + 8, smoothing, "<u4")
    q = numpy.flatnonzero(quad)
    _put(buf, mask_at[q] + 12, numpy.zeros(len(q)), "<u4")
    _put(buf, mask_at[q] + 16, numpy.full(len(q), 2), "<u4")
    return buf.tobytes()


def poly_object(n, seed=0):
    """The bytes of an Editable Poly object chunk of about n faces (see the module docstring). seed shifts the
    vertex heights, so different seeds give different bytes of the same layout."""
    positions, deg, lv, smoothing, materials = faces_of(n)
    positions[:, 2] += numpy.float32(seed * 0.01)
    nv = len(positions)
    verts = numpy.zeros(nv, dtype=[("flags", "<u4"), ("p", "<f4", (3,))])
    verts["p"] = positions
    uvw = numpy.zeros((nv, 3), dtype="<f4")
    span = max(1.0, float(positions[:, :2].max()))
    uvw[:, :2] = positions[:, :2] / span
    words = numpy.zeros(int(deg.sum()) + len(deg), dtype="<u4")
    heads = numpy.concatenate((numpy.zeros(1, numpy.int64), numpy.cumsum(deg + 1)[:-1]))
    words[heads] = deg
    keep = numpy.ones(len(words), dtype=bool)
    keep[heads] = False
    words[keep] = lv
    return _node(OBJECT, _node(
        GEOMETRY,
        _leaf(VERTS, struct.pack("<I", nv) + verts.tobytes()),
        _leaf(FACES, _face_records(deg, lv, smoothing, materials)),
        _leaf(MAP_CHANNEL, struct.pack("<i", 1)),
        _leaf(MAP_VERTS, struct.pack("<I", nv) + uvw.tobytes()),
        _leaf(MAP_FACES, words.tobytes())))


def reference_loop(n):
    """Plain Python record walking: n records of 28 bytes, two u32 unpacked and appended, 12 bytes collected from a
    memoryview, as _poly_faces does per face. Returns what it collected (so nothing is optimised away)."""
    data = memoryview(bytes(range(256)) * (28 * n // 256 + 1))
    unpack = struct.Struct("<I").unpack_from
    out, acc = bytearray(), array.array("I")
    off = 0
    for _ in range(n):
        a, = unpack(data, off)
        b, = unpack(data, off + 16)
        out += data[off + 4:off + 16]
        acc.append(a)
        acc.append(b)
        off += 28
    return len(out) + len(acc)


def numpy_reference(values):
    """The streaming part of describe_reference, on values (a mesh's loop vertices, so the data has the same order
    in it): a function that runs int64 arithmetic, a gather and a comparison of neighbours over them, three times,
    into arrays made here, and returns a checksum. Nothing is allocated and nothing sorted while it runs. Alone it
    was the describe benchmark's reference until CI showed that it scales with the machine differently from
    describe (describe_reference)."""
    keys = numpy.asarray(values, dtype=numpy.int64)
    n = len(keys)
    following = numpy.roll(keys, -1)
    index = keys[::-1] % n
    lo, hi, pair, picked = (numpy.empty(n, dtype=numpy.int64) for _ in range(4))
    same = numpy.empty(max(0, n - 1), dtype=bool)
    scale = int(keys.max()) + 1 if n else 1

    def run():
        total = 0
        for _ in range(3):
            numpy.minimum(keys, following, out=lo)
            numpy.maximum(keys, following, out=hi)
            numpy.multiply(lo, scale, out=pair)
            numpy.add(pair, hi, out=pair)
            numpy.take(pair, index, out=picked)
            numpy.not_equal(picked[1:], picked[:-1], out=same)
            total += int(numpy.count_nonzero(same)) + int(numpy.cumsum(lo, out=hi)[-1])
        return total
    return run


def describe_reference(values):
    """The describe benchmark's reference: convert.scene.mesh_description's mix of numpy calls, no MaxDrop code, on
    values (a mesh's loop vertices, kept in mesh order: how long a stable sort takes depends on how sorted its input
    already is). On the first three fifths of them: a pass per face size (numpy.unique), rows sorted along axis 1, a
    repeated-vertex test and a stable lexsort of the rows, the loops of the faces kept (repeat, flatnonzero); int64
    keys of neighbouring vertices, a stable argsort, the runs of equal keys (concatenate, diff), the edges stacked; a
    gather of float32 rows per loop. On the first sixth, numpy_reference's streaming work. Each of these calls
    allocates its result, as describe's do: a reference without sorting and allocation (numpy_reference alone)
    sped up with the runner's vector units and numpy 2.x while describe hardly did, and their ratio ranged from 3 to
    8 on CI (docs/BASELINE.md). Returns a function that runs it once and returns a checksum."""
    keys = numpy.asarray(values, dtype=numpy.int64)
    part = keys[:len(keys) * 3 // 5]
    stream = numpy_reference(keys[:len(keys) // 6])
    lv = part.astype(numpy.int32)
    n = len(lv)
    scale = int(lv.max()) + 1 if n else 1
    per_vertex = numpy.zeros((scale, 3), dtype=numpy.float32)
    split = n // 8 * 4  # the first half as rows of four, the rest as rows of three

    def run():
        total = stream()
        if not n:
            return total
        sizes = 3 + (part[::4] & 1)
        keep = numpy.ones(len(sizes), dtype=bool)
        for size in numpy.unique(sizes):
            loops = part[:split] if size == 4 else part[split:]
            rows = numpy.sort(loops[:len(loops) // size * size].reshape(-1, size), axis=1)
            repeated = (numpy.diff(rows, axis=1) == 0).any(axis=1)
            rows = rows[~repeated]
            order = numpy.lexsort(rows.T)
            rows = rows[order]
            later = order[1:][(rows[1:] == rows[:-1]).all(axis=1)]
            keep[later[later < len(keep)]] = False
        kept = numpy.flatnonzero(numpy.repeat(keep, sizes))
        following = numpy.roll(lv, -1)
        lo, hi = numpy.minimum(lv, following), numpy.maximum(lv, following)
        key = lo.astype(numpy.int64)
        key *= scale
        key += hi
        order = numpy.argsort(key, kind="stable")
        key = key[order]
        first = numpy.flatnonzero(numpy.concatenate(([True], key[1:] != key[:-1])))
        counts = numpy.diff(numpy.append(first, n))
        src = order[first[counts == 2]]
        edges = numpy.stack((lo[src], hi[src]), axis=1).astype(numpy.int32)
        rows = numpy.ascontiguousarray(per_vertex[numpy.take(lv, kept, mode="clip")][:, :2])
        return total + len(edges) + len(rows)
    return run


def timed(work, reference, runs=5, reference_runs=None, after=None):
    """(best time of work(), best time of reference()) in seconds, over runs (reference_runs) calls each. The calls
    alternate, so a slow moment of a shared machine hits both rather than skewing their ratio; after(result) runs
    outside the timing (to free what a call made)."""
    reference_runs = runs if reference_runs is None else reference_runs
    best = [float("inf"), float("inf")]
    for i in range(max(runs, reference_runs)):
        for k, fn, n in ((0, work, runs), (1, reference, reference_runs)):
            if i >= n:
                continue
            start = time.perf_counter()
            result = fn()
            best[k] = min(best[k], time.perf_counter() - start)
            if after is not None:
                after(result)
    return best[0], best[1]
