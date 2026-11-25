# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A primitive's mesh: the corner budget, build() and mesh()."""
import math

from ...reader import classids
from .specs import MAX_CORNERS, PrimitiveError, read_params
from .builder import _Builder
from .flat import _box, _plane, _pyramid
from .revolved import _cylinder, _cylinder_pie, _sphere, _sphere_rings, _torus, _tube
from .geosphere import _geosphere, _solid


def _faces(p):
    """How many polygons p makes."""
    v = p.values
    c = p.class_id
    if c == classids.BOX:
        x, y, z = v["width_segs"], v["length_segs"], v["height_segs"]
        return 2 * (x * y + x * z + y * z)
    if c == classids.PLANE:
        return v["width_segs"] * v["length_segs"]
    if c == classids.PYRAMID:
        return 2 * (v["width_segs"] + v["depth_segs"]) * (v["height_segs"] + 1)
    if c == classids.SPHERE:
        if v["segs"] > MAX_CORNERS:  # refused on its segments alone (a file may store them as a huge float)
            return v["segs"] * v["segs"]
        rows, _angle, cut = _sphere_rings(p)
        caps = (2 * rows + (0 if cut != math.pi else 2)) if v["slice"] else 0
        return v["segs"] * (rows + 1) + caps
    if c == classids.GEOSPHERE:
        if v["hemisphere"]:  # the faces above the equator, then the base's fan
            per = {0: (3, 3), 1: (4, 4)}.get(v["base_type"], (40, 10))
            return per[0] * v["segs"] * v["segs"] + per[1] * v["segs"]
        return len(_solid(v["base_type"])[1]) * v["segs"] * v["segs"]
    if c in (classids.CYLINDER, classids.CONE):
        rings = v["height_segs"] + 2 * v["cap_segs"] - 1
        return v["sides"] * (rings + 1) + (4 * (rings - 1) if v["slice"] else 0)
    if c == classids.TUBE:
        profile = 2 * (v["height_segs"] + v["cap_segs"])
        return v["sides"] * profile + (2 * profile if v["slice"] else 0)
    return v["segs"] * v["sides"] + (2 * v["sides"] if v["slice"] else 0)


def build(p):
    """(MeshData of Params p, issues); PrimitiveError for what is not built."""
    issues = []
    faces = _faces(p)
    if faces * 4 > MAX_CORNERS:  # four corners per face at most
        raise PrimitiveError("%s of %d faces refused (more than %d)" % (p.name, faces, MAX_CORNERS // 4))
    import numpy
    b = _Builder(numpy)
    with numpy.errstate(all="ignore"):  # sizes that overflow give points or UVs data() refuses
        _make(b, p, issues)
        return b.data(p.mapping), issues


def _make(b, p, issues):
    """Fill builder b with the mesh of Params p (its issues added to issues)."""
    c = p.class_id
    if c == classids.BOX:
        _box(b, p)
    elif c == classids.PLANE:
        if p.render_scale != 1.0 or p.density != 1.0:
            issues.append("render scale %g and density %g act at render time: built at the viewport size"
                          % (p.render_scale, p.density))
        _plane(b, p)
    elif c == classids.PYRAMID:
        b.flip = p.height < 0
        _pyramid(b, p)
    elif c == classids.SPHERE:
        _sphere(b, p)
    elif c == classids.GEOSPHERE:
        _geosphere(b, p)
    elif c in (classids.CYLINDER, classids.CONE):
        b.flip = p.height < 0 and not p.slice
        r1, r2 = (p.radius, p.radius) if c == classids.CYLINDER else (p.radius1, p.radius2)
        (_cylinder_pie if p.slice else _cylinder)(b, p, r1, r2)
    elif c == classids.TUBE:  # under a negative height the radii trade sides: the faces point out unflipped
        _tube(b, p)
    else:
        _torus(b, p)


def mesh(scene, i):
    """(MeshData of primitive object i, issues); PrimitiveError when it is not built."""
    params, issues = read_params(scene, i)
    data, more = build(params)
    return data, issues + more
