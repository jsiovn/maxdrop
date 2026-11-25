# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shell rims and Mirror seams: the rim faces under a Mirror, lowered, welded and named."""
import math

from ...reader import geometry
from .. import modifiers as rules
from .descriptions import (
    BISECT_DISTANCE, MAX_MIRROR_IMAGES, MAX_MIRRORED_CORNERS, NORMAL_TOLERANCE, PLANE_TOLERANCE, SEAM_STAYS,
    SEAM_UNTESTED,
)
from .meshes import _open_loops, _reversed_loops, open_edges, rim_corners


def _shading(converted):
    """What the lowest converted smoother that changes the shading does to it: convert.modifiers SMOOTH, CREASE or
    None."""
    return next((m.shading for m in converted if m.kind == rules.SUBSURF and m.shading), None)


def _rim(converted):
    """The lowest converted Shell (a ModifierDescription) whose rim MaxDrop hardens as 3ds Max does (the mesh's open
    edges sharp): one without a smoother with Smooth Result above it (which smooths the rim too). None otherwise. A
    Shell above another meets a closed mesh: only the lowest makes a rim. The Mirrors below it: _mirrors."""
    for k, m in enumerate(converted):
        if m.kind == rules.SOLIDIFY:
            above = converted[k + 1:]
            return None if any(x.kind == rules.SUBSURF and x.shading == rules.SMOOTH for x in above) else m
    return None


def _mirrors(converted, shell):
    """The Mirrors (ModifierDescriptions) below Shell shell in converted, bottom first: the open edges they weld shut
    make no rim (welded())."""
    out = []
    for m in converted:
        if m is shell:
            break
        if m.kind == rules.MIRROR:
            out.append(m)
    return tuple(out)


def _seam(converted):
    """(shell, above): the lowest converted Shell (a ModifierDescription) when only Mirrors are converted below it, and
    the run of Mirrors right above it, bottom first: those lowered() may move below it. (None, ()) otherwise."""
    for k, m in enumerate(converted):
        if m.kind == rules.SOLIDIFY:
            above = []
            for x in converted[k + 1:]:
                if x.kind != rules.MIRROR:
                    break
                above.append(x)
            return m, tuple(above)
        if m.kind != rules.MIRROR:
            break
    return None, ()


def _lowered(converted, shell, moved):
    """converted with the Mirrors moved (the first of those right above Shell shell, lowered()) just below it."""
    if not moved:
        return converted
    k = converted.index(shell)
    return converted[:k] + tuple(moved) + (shell,) + converted[k + 1 + len(moved):]


def _unit(offset, meters):
    """Meters per system unit of the object's space with the object offset (a reader matrix or None) baked: the mean
    length of its axes, times meters."""
    if offset is None:
        return meters
    return meters * sum(math.sqrt(sum(offset[r][c] ** 2 for c in range(3))) for r in range(3)) / 3.0


def _reflection(mirror):
    """The 4x4 matrix (numpy, Blender's columns) that mirrors a point of the object's space as Mirror
    ModifierDescription mirror does: F S inverse(F), F the mirror object's matrix (the identity without one), S the
    flip of its axis."""
    import numpy
    f = numpy.identity(4) if mirror.mirror is None else numpy.asarray(mirror.mirror, dtype=numpy.float64)
    flip = numpy.diag([-1.0 if on else 1.0 for on in dict(mirror.settings)["use_axis"]] + [1.0])
    return f @ flip @ numpy.linalg.inv(f)


def welded(positions, mirror):
    """Whether each vertex (positions (V, 3), meters) merges with its copy under Mirror ModifierDescription mirror,
    bool (V,): with its weld on, Blender's Mirror welds a vertex closer than merge_threshold to its mirror image
    (half that to the plane)."""
    import numpy
    p = numpy.asarray(positions, dtype=numpy.float64).reshape(-1, 3)
    threshold = max(float(dict(mirror.settings)["merge_threshold"]), 0.0)  # Blender's hard minimum
    if not dict(mirror.settings)["use_mirror_merge"] or not threshold:
        return numpy.zeros(len(p), dtype=bool)
    r = _reflection(mirror)
    d = p - (p @ r[:3, :3].T + r[:3, 3])
    return numpy.einsum("ij,ij->i", d, d) < threshold * threshold


def _rim_edges(md, mirrors, check=None):
    """The open edges of MeshDescription md that make a rim above the Mirrors mirrors (_mirrors): all but those
    whose two ends a Mirror welds to their copies, the edge's own or one of its copies under the Mirrors below that
    one (the edge and its copy become one, with a face on each side; a copy carries the sharp mark). The copies
    tested stop doubling past MAX_MIRROR_IMAGES, or MAX_MIRRORED_CORNERS positions; check() between the Mirrors."""
    import numpy
    edges = open_edges(md.loop_vertices, md.loop_starts, md.loop_totals, check)
    if not mirrors or not len(edges):
        return edges
    ends = numpy.unique(edges)
    a, b = numpy.searchsorted(ends, edges[:, 0]), numpy.searchsorted(ends, edges[:, 1])
    images = numpy.asarray(md.positions, dtype=numpy.float64)[ends][None]  # (copies, ends, 3) made so far
    keep = numpy.ones(len(edges), dtype=bool)
    for m in mirrors:
        if check is not None:
            check()
        w = welded(images.reshape(-1, 3), m).reshape(len(images), len(ends))
        keep &= ~(w[:, a] & w[:, b]).any(axis=0)
        if 2 * len(images) <= MAX_MIRROR_IMAGES and 2 * images.size <= 3 * MAX_MIRRORED_CORNERS:
            r = _reflection(m)
            images = numpy.concatenate((images, images @ r[:3, :3].T + r[:3, 3]))
    return edges[keep]


def _mirrored(md, mirrors, check=None):
    """(positions, loop_vertices, loop_starts, loop_totals) of MeshDescription md and its copy under each Mirror of
    mirrors (_mirrors) in turn, the vertices it welds shared, each copy's faces reversed: the mesh the Shell above
    them meets, as far as its rim goes (no slice is made: md is taken as the part each Mirror keeps; a welded vertex
    stays where it is, Blender moves it half its distance to the plane). check() between the Mirrors."""
    import numpy
    p = numpy.asarray(md.positions, dtype=numpy.float64)
    lv = numpy.asarray(md.loop_vertices, dtype=numpy.int64)
    starts = numpy.asarray(md.loop_starts, dtype=numpy.int64)
    totals = numpy.asarray(md.loop_totals, dtype=numpy.int64)
    for m in mirrors:
        if check is not None:
            check()
        p, lv, starts, totals = _mirror_once(p, lv, starts, totals, m)
    return p, lv, starts, totals


def _mirror_once(p, lv, starts, totals, m):
    """_mirrored's step: the mesh (float64 positions, int64 loop arrays) and its copy under Mirror m."""
    import numpy
    n = len(p)
    r = _reflection(m)
    index = numpy.where(welded(p, m), numpy.arange(n), n + numpy.arange(n))
    copy = index[lv[_reversed_loops(starts, totals)]]
    return (numpy.concatenate((p, p @ r[:3, :3].T + r[:3, 3])), numpy.concatenate((lv, copy)),
            numpy.concatenate((starts, starts + len(lv))), numpy.concatenate((totals, totals)))


def _face_normals(p, lv, starts, totals, faces):
    """The unit normals of the faces (bool (F,)) of a mesh (numpy arrays), float64 (k, 3): each face's area vector, a
    fan of cross products from its first vertex; a face of no area gets (0, 0, 0)."""
    import numpy
    face_of = numpy.repeat(numpy.arange(len(starts)), totals)
    following = numpy.arange(1, len(lv) + 1)
    following[starts + totals - 1] = starts
    loops = numpy.flatnonzero(faces[face_of])
    first = numpy.zeros(int(faces.sum()), dtype=numpy.int64)
    numpy.cumsum(totals[faces][:-1], out=first[1:])
    origin = p[lv[starts[face_of[loops]]]]  # each face's first vertex: the cross products stay small
    n = numpy.add.reduceat(numpy.cross(p[lv[loops]] - origin, p[lv[following[loops]]] - origin), first, axis=0)
    length = numpy.sqrt(numpy.einsum("ij,ij->i", n, n))
    return n / numpy.where(length > 0, length, 1.0)[:, None]


def lowered(md, below, above, unit, check=None):
    """(moved, issue) for a Shell above the Mirrors below and below the Mirrors above (_seam), on MeshDescription md
    (meters; unit meters per system unit, _unit): how many of above, bottom first, Blender's Mirror makes as 3ds Max
    2020's Symmetry does from below the Solidify, and why the next one is not moved when it may leave a rim on its
    plane (None otherwise). Above a Shell, 3ds Max's slice drops the rim faces on its plane (within PLANE_TOLERANCE,
    at most BISECT_DISTANCE) and the weld shuts the cut; Blender's bisect keeps them. On the mesh with its copies
    under the Mirrors below and those moved (_mirrored), a Mirror whose plane holds no open edge (both ends on it)
    ends the run; one that slices and welds those ends, every face at them square to the plane (NORMAL_TOLERANCE: the
    rim then lies on the plane), is moved; another ends it with SEAM_STAYS. Only the open edges on the plane decide:
    others within the weld threshold of it are welded too once the Mirror is moved, where 3ds Max keeps their rim.
    The mesh with its copies tested is at most MAX_MIRRORED_CORNERS face corners (past it: SEAM_UNTESTED). check()
    between the Mirrors."""
    import numpy
    if not above:
        return 0, None
    if len(md.loop_vertices) << len(below) > MAX_MIRRORED_CORNERS:
        return 0, SEAM_UNTESTED
    p, lv, starts, totals = _mirrored(md, below, check)
    tolerance = 2.0 * min(PLANE_TOLERANCE * unit, BISECT_DISTANCE)  # |p - R p|, twice the distance to the plane
    for k, m in enumerate(above):
        if check is not None:
            check()
        edges = open_edges(lv, starts, totals)
        r = _reflection(m)
        d = p - (p @ r[:3, :3].T + r[:3, 3])
        on = numpy.einsum("ij,ij->i", d, d) <= tolerance * tolerance
        edges = edges[on[edges[:, 0]] & on[edges[:, 1]]]
        if not len(edges):
            return k, None
        ends = numpy.unique(edges)
        settings = dict(m.settings)
        square = any(settings["use_bisect_axis"]) and welded(p[ends], m).all()
        if square:
            at = numpy.zeros(len(p), dtype=bool)
            at[ends] = True
            faces = numpy.zeros(len(starts), dtype=bool)
            faces[numpy.repeat(numpy.arange(len(starts)), totals)[at[lv]]] = True
            n = _face_normals(p, lv, starts, totals, faces)
            tilt = n - n @ r[:3, :3].T  # twice the normal's part along the axis
            square = bool((numpy.einsum("ij,ij->i", tilt, tilt) <= 4.0 * NORMAL_TOLERANCE ** 2).all())
        if not square:
            return k, SEAM_STAYS
        if k + 1 < len(above):
            if 2 * len(lv) > MAX_MIRRORED_CORNERS:
                return k + 1, SEAM_UNTESTED
            p, lv, starts, totals = _mirror_once(p, lv, starts, totals, m)
    return len(above), None


def rim_issues(md, rim, check=None, mirrors=()):
    """What Blender's Solidify does not do of a Shell's RimRule on MeshDescription md (none when md has no open
    edge): auto smooth splitting the rim's sharper corners (rim_corners, on the mesh below the modifiers: a
    TurboSmooth below the Shell keeps a plane's four corners, 1 to 3 iterations in 3ds Max 2020), the override group
    with auto smooth off (3ds Max merges the rim into faces along it of that group; named whatever the groups of
    those faces). Above the Mirrors mirrors (_mirrors) the open edges they weld shut make no rim (_rim_edges) and
    the corners are counted on md with its copies (_mirrored), unless that mesh would pass MAX_MIRRORED_CORNERS face
    corners (a line instead). check() between the passes."""
    if rim is None:
        return []
    if mirrors and not len(_rim_edges(md, mirrors, check)):
        return []
    if rim.auto_smooth:
        if mirrors and len(md.loop_vertices) << len(mirrors) > MAX_MIRRORED_CORNERS:
            return ["auto smooth: the rim's corners not counted: with its copies under %d Symmetries the mesh would "
                    "pass %d face corners" % (len(mirrors), MAX_MIRRORED_CORNERS)]
        mesh = _mirrored(md, mirrors, check) if mirrors else (md.positions, md.loop_vertices, md.loop_starts,
                                                               md.loop_totals)
        n = rim_corners(*mesh, rim.angle, check)
        return ["auto smooth: %d corners of the rim sharper than %g degrees shade smooth (3ds Max splits the rim "
                "there)" % (n, rim.angle)] if n else []
    if rim.override is None or not (mirrors or len(_open_loops(md.loop_vertices, md.loop_starts, md.loop_totals,
                                                                check)[0])):
        return []
    return ["smoothing group override (group %d) not converted: 3ds Max merges the rim into the faces along it of "
            "that group" % rim.override]


def _name_rim(desc, rims, shell, key, node, check=None, mirrors=()):
    """The rim issues of Shell shell (a ModifierDescription or None) above the Mirrors mirrors (_mirrors) on mesh
    key, on node: once per Shell and mesh."""
    if shell is None or (shell.index, key) in rims:
        return
    rims.add((shell.index, key))
    md = desc.meshes[key]
    desc.issues.extend((node, "modifiers: %s: %s" % (shell.class_name or "Shell", x))
                       for x in rim_issues(md, shell.rim, _large(md, check), mirrors))


def _rim_mirrors(md, mirrors, above, unit):
    """The Mirrors (ModifierDescriptions) the corners of the rim on MeshDescription md are counted with (rim_issues):
    mirrors (below the Shell) and those of above lowered() moves; when the next one leaves a rim on its plane
    (md.seam_issue SEAM_STAYS) and slices, that one too, welding what lies on its plane (3ds Max's slice drops the
    rim there: no corner; without the slice 3ds Max keeps it, corners and all)."""
    out = tuple(mirrors) + tuple(above[:md.lowered])
    if md.seam_issue == SEAM_STAYS and any(dict(above[md.lowered].settings)["use_bisect_axis"]):
        m = above[md.lowered]
        weld = (("use_mirror_merge", True), ("merge_threshold", 2.0 * PLANE_TOLERANCE * unit * (1.0 + 1e-6)))
        out += (m._replace(settings=tuple(x for x in m.settings if x[0] not in dict(weld)) + weld),)
    return out


def _name_seam(desc, rims, above, key, node):
    """The issue of the Mirror of above (_seam) that may leave a rim on its plane on mesh key (md.seam_issue), on
    node: once per Mirror and mesh."""
    md = desc.meshes[key]
    if md.seam_issue is None:
        return
    m = above[md.lowered]
    if ("seam", m.index, key) not in rims:
        rims.add(("seam", m.index, key))
        desc.issues.append((node, "modifiers: %s: %s" % (m.class_name or "Symmetry", md.seam_issue)))


def _large(md, check):
    """check for the passes over md when it has more than reader.geometry.CHECK_EVERY face corners, else None (the
    call counts of a small mesh stay once per node, as in mesh_description)."""
    return check if check is not None and len(md.loop_vertices) > geometry.CHECK_EVERY else None
