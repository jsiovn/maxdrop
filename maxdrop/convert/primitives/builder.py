# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mesh builder of a primitive and the helpers every primitive shares (stacks, corners, grids)."""
from ...reader import geometry
from .specs import PrimitiveError


class _Builder:
    """Points, polygons and their corners' UVs, gathered as numpy blocks in the order they are made."""

    def __init__(self, numpy):
        self.np = numpy
        self.count = 0
        self.positions, self.loops, self.uvs, self.sizes, self.mats, self.groups = [], [], [], [], [], []
        self.flip = False  # reverse every face made from now on (with its corners' UVs)

    def points(self, xyz):
        """The indices of new points xyz (an array whose last axis is x, y, z), shaped like xyz without that axis."""
        np = self.np
        xyz = np.asarray(xyz, dtype=np.float64)
        first = self.count
        self.positions.append(xyz.reshape(-1, 3))
        self.count += len(self.positions[-1])
        return np.arange(first, self.count, dtype=np.int64).reshape(xyz.shape[:-1])

    def faces(self, verts, mat, group, uvs):
        """F faces of n corners: verts (F, n) point indices, uvs (F, n, 2); mat and group one value or one per face."""
        np = self.np
        verts = np.asarray(verts)
        self.columns((verts[:, None], np.reshape(mat, (-1, 1)), np.reshape(group, (-1, 1)),
                      np.broadcast_to(uvs, verts.shape + (2,))[:, None]))

    def columns(self, *parts):
        """Faces in C columns, made column after column: each part (verts (C, F, n), mat, group, uvs (C, F, n, 2))
        puts F faces of n corners in every column, after those of the parts before it; mat and group broadcast to
        (C, F). 3ds Max's own order where one column mixes triangles and quads."""
        np = self.np
        c = len(parts[0][0])
        loops, uvs, sizes, mats, groups = [], [], [], [], []
        for verts, mat, group, uv in parts:
            verts = np.asarray(verts, dtype=np.int64)
            uv = np.asarray(uv, dtype=np.float64)
            _c, f, n = verts.shape
            if self.flip:
                verts, uv = verts[..., ::-1], uv[..., ::-1, :]
            loops.append(verts.reshape(c, f * n))
            # UVs that do not vary along an axis (a size of 0) come with that axis 1, also when F is 0
            uvs.append(np.broadcast_to(uv, (c, f, n, 2)).reshape(c, f * n * 2))
            sizes.append(np.full((c, f), n, dtype=np.int64))
            mats.append(np.broadcast_to(np.asarray(mat, dtype=np.int64), (c, f)))
            groups.append(np.broadcast_to(np.asarray(group, dtype=np.int64), (c, f)))
        for out, blocks in ((self.loops, loops), (self.uvs, uvs), (self.sizes, sizes), (self.mats, mats),
                            (self.groups, groups)):
            out.append(np.concatenate(blocks, axis=1).reshape(-1))

    def data(self, mapping):
        """The MeshData; run under build()'s errstate: values past the float range become inf, refused here."""
        np = self.np
        positions = np.concatenate(self.positions).astype(np.float32)
        uvw = None
        if mapping:
            uv = np.concatenate(self.uvs).reshape(-1, 2)
            uvw = np.zeros((len(uv), 3), dtype=np.float32)
            uvw[:, :2] = uv
        if not np.isfinite(positions).all() or (uvw is not None and not np.isfinite(uvw).all()):
            raise PrimitiveError("its sizes give points or UVs past the float range")
        loops = np.concatenate(self.loops).astype(np.int32)
        sizes = np.concatenate(self.sizes)
        maps = {}
        if mapping:
            maps[1] = geometry.MapChannel(1, uvw, np.arange(len(loops), dtype=np.int32))
        return geometry.MeshData(positions, loops, (np.cumsum(sizes) - sizes).astype(np.int32),
                                 np.concatenate(self.groups).astype(np.uint32),
                                 np.concatenate(self.mats).astype(np.uint16), maps)


def _stack(np, *arrays, dtype=None):
    """arrays broadcast against each other and stacked along a new last axis."""
    arrays = [np.asarray(x, dtype=dtype) for x in arrays]
    out = np.empty(np.broadcast(*arrays).shape + (len(arrays),), dtype=dtype or np.result_type(*arrays))
    for k, x in enumerate(arrays):
        out[..., k] = x
    return out


def _corners(np, *uvs):
    """(..., corners, 2): the (u, v) pair of each corner, all broadcast against each other."""
    out = np.empty(np.broadcast(*(np.asarray(x) for uv in uvs for x in uv)).shape + (len(uvs), 2), dtype=np.float64)
    for k, (u, v) in enumerate(uvs):
        out[..., k, 0] = u
        out[..., k, 1] = v
    return out


def _first_use(np, keys):
    """(where in keys each distinct key first appears, in that order; for each key its rank in that order): points
    made the first time a face corner needs them, numbered in that order. keys are below 2^31 and there are at most
    MAX_CORNERS of them, so key * len + position fits int64 and one unstable sort finds each first appearance."""
    keys = np.asarray(keys, dtype=np.int64).reshape(-1)
    n = len(keys)
    order = np.argsort(keys * n + np.arange(n, dtype=np.int64))
    ordered = keys[order]
    new = np.ones(n, dtype=bool)
    np.not_equal(ordered[1:], ordered[:-1], out=new[1:])
    first = order[new]  # in key order
    by_use = np.argsort(first)
    rank = np.empty(len(first), dtype=np.int64)
    rank[by_use] = np.arange(len(first), dtype=np.int64)
    ids = np.empty(n, dtype=np.int64)
    ids[order] = rank[np.cumsum(new) - 1]
    return first[by_use], ids


def _grid(np, nu, nv, flip=False):
    """(a, c) of the corners of a grid's quads, (nu * nv, 4) each, a in 0..nu along U and c in 0..nv along V, row c
    after row c: the quad (a, c), (a+1, c), (a+1, c+1), (a, c+1) faces U x V, the other way with flip. Its UV is
    (a / nu, c / nv) times the grid's scale."""
    a = np.arange(nu, dtype=np.int64)[None, :, None] + np.array([0, 1, 1, 0], dtype=np.int64)
    c = np.arange(nv, dtype=np.int64)[:, None, None] + np.array([0, 0, 1, 1], dtype=np.int64)
    a, c = np.broadcast_arrays(a, c)
    if flip:
        a, c = a[..., ::-1], c[..., ::-1]
    return a.reshape(-1, 4), c.reshape(-1, 4)


def _sign(x):
    return -1.0 if x < 0 else 1.0
