# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The modifiers Blender has an equivalent for: TurboSmooth and MeshSmooth as Subdivision Surface, Shell as
Solidify, Symmetry as Mirror.

    is_convertible(modifier)            # a reader.modifiers.Modifier of one of the four classes
    md, issues = convert(scene, modifier, meters, offset)   # a ModifierDescription; ModifierError when refused
    md.kind, md.settings                # Blender's modifier type, ((attribute, value), ...) to set on it
    md.mirror                           # Mirror: the mirror object's matrix in the object's space, or None
    md.shading                          # a smoother: SMOOTH, CREASE or None (what it does to the mesh's shading)

Each keeps one ParamBlock2 in reference slot 0 (docs/FORMAT.md, "Modifiers converted to Blender modifiers"):
TurboSmooth 0 iterations, 1 use render iterations, 2 render iterations, 4 smooth result, 5 separate by materials, 6
separate by smoothing groups; MeshSmooth 9 method (0 classic, 1 quad output, 2 NURMS), 4 iterations, 2 smoothness,
13 use render iterations, 14 render iterations, 5 smooth result, 6 separate by materials, 7 separate by smoothing
groups; Shell 0 inner amount, 1 outer amount, 2 / 8 / 17 override material ID (edges, inner, outer), 4 override
smoothing group, 12 segments, 19 bevel edges; Symmetry 0 axis, 1 slice along mirror, 2 weld seam, 3 threshold, 4
flip, its mirror gizmo the PRS controller in reference slot 1.

What 3ds Max 2020 makes (tests/blender/run.py against the stack_convert fixture's oracle): a smoother refines the
control points as Catmull-Clark does (not the limit surface); Shell moves the new surfaces along the vertex normals
by the inner and outer amounts (not an even thickness); Symmetry mirrors in its gizmo's space, q = p * context *
inverse(gizmo) for a point p of the object, keeps the side where q along the axis is positive (flip: negative) and
slices there, or mirrors all of the object without slice. In Blender's object space (the object offset baked, x = p *
offset) the gizmo's frame is gizmo * inverse(context) * offset: build/ puts an empty there as the mirror object when
that is not the identity.

The lowest converted smoother decides the shading: separate by smoothing groups keeps the sharp edges and creases
them (CREASE), else Smooth Result smooths every face and edge (SMOOTH). Lengths are in meters.

The file comes from anywhere: a missing block, an animated parameter or one that is no number, an axis outside X / Y
/ Z, a gizmo that cannot be evaluated or a mirror frame that cannot be inverted raise ModifierError; iterations
outside 0 .. MAX_ITERATIONS are clamped (an issue). No bpy; numpy is imported for a Symmetry.
"""
import collections
import math

from ..reader import chunks, classids, controllers, pblock

ChunkError = chunks.ChunkError

SUBSURF, SOLIDIFY, MIRROR = "SUBSURF", "SOLIDIFY", "MIRROR"
SMOOTH, CREASE = "smooth", "crease"
MAX_ITERATIONS = 10  # 3ds Max's own limit for TurboSmooth and MeshSmooth
SLOT_BLOCK, SLOT_GIZMO = 0, 1
CLASSIC, QUAD_OUTPUT, NURMS = 0, 1, 2
IDENTITY_TOLERANCE = 1e-6
_FATAL = (controllers.UNKNOWN_CLASS, controllers.DAMAGED, controllers.NON_FINITE)
_KINDS = {classids.TURBOSMOOTH: SUBSURF, classids.MESHSMOOTH: SUBSURF, classids.SHELL: SOLIDIFY,
          classids.SYMMETRY: MIRROR}


class ModifierError(ChunkError):
    """A modifier that cannot be converted; it stays in the stack's list of modifiers not applied."""


class ModifierDescription(collections.namedtuple("ModifierDescription",
                                                 "index kind name class_name show_viewport settings mirror shading")):
    """One Blender modifier: index the 3ds Max modifier's object index, kind SUBSURF / SOLIDIFY / MIRROR, name the
    modifier's name in 3ds Max, class_name its class directory's name, show_viewport whether it is on in the
    viewport, settings ((attribute, value), ...) in the order to set them, mirror a 4x4 Blender
    matrix (columns, translation in meters) of the mirror object in the object's space or None, shading SMOOTH,
    CREASE or None."""
    __slots__ = ()


def is_convertible(modifier):
    return modifier.superclass == classids.SC_OSMODIFIER and modifier.class_id in _KINDS


def _value(block, pid, default):
    v = block.get(pid)
    if v is None:
        return default
    if isinstance(v, pblock.Animated):
        raise ModifierError("parameter %d is animated (a controller)" % pid)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ModifierError("parameter %d is not a number: %r" % (pid, v))
    return v


def _block(modifier):
    block = modifier.blocks.get(SLOT_BLOCK)
    if block is None:
        raise ModifierError("no parameter block (reference slot 0)")
    return block


def _iterations(block, pid, default, issues, what):
    n = int(_value(block, pid, default))
    if not 0 <= n <= MAX_ITERATIONS:
        issues.append("%s %d, made %d" % (what, n, min(max(n, 0), MAX_ITERATIONS)))
        n = min(max(n, 0), MAX_ITERATIONS)
    return n


def _smoother(modifier):
    """(settings, shading, issues) of a TurboSmooth or MeshSmooth."""
    b, issues = _block(modifier), []
    mesh_smooth = modifier.class_id == classids.MESHSMOOTH
    if mesh_smooth:
        iterations, use_render, render, smooth, by_mats, by_groups = 4, 13, 14, 5, 6, 7
        method = int(_value(b, 9, NURMS))
        if method == CLASSIC:
            issues.append("classic subdivision made as Catmull-Clark")
        elif method not in (QUAD_OUTPUT, NURMS):
            issues.append("subdivision method %d made as Catmull-Clark" % method)
        smoothness = float(_value(b, 2, 1.0))
        if smoothness < 1.0:
            issues.append("smoothness %g not converted (made 1)" % smoothness)
    else:
        iterations, use_render, render, smooth, by_mats, by_groups = 0, 1, 2, 4, 5, 6
    levels = _iterations(b, iterations, 1, issues, "iterations")
    render_levels = _iterations(b, render, 0, issues, "render iterations") if _value(b, use_render, 0) else levels
    if _value(b, by_mats, 0):
        issues.append("separate by materials not converted")
    shading = CREASE if _value(b, by_groups, 0) else SMOOTH if _value(b, smooth, 1) else None
    settings = (("subdivision_type", "CATMULL_CLARK"), ("levels", levels), ("render_levels", render_levels),
                ("use_limit_surface", False), ("use_creases", True))
    return settings, shading, issues


def _shell(modifier, meters):
    b, issues = _block(modifier), []
    inner, outer = float(_value(b, 0, 0.0)), float(_value(b, 1, 1.0))
    lo, hi = min(-inner, outer), max(-inner, outer)  # the two surfaces along the normal
    if hi - lo <= 0:
        raise ModifierError("a shell of no thickness (inner %g, outer %g)" % (inner, outer))
    if lo > 0 or hi < 0:  # Solidify keeps the original surface between its two
        raise ModifierError("both surfaces on one side (inner %g, outer %g)" % (inner, outer))
    if int(_value(b, 12, 1)) > 1:
        issues.append("%d segments made as one" % int(_value(b, 12, 1)))
    if _value(b, 19, 0):
        issues.append("bevel edges not converted")
    if _value(b, 2, 0) or _value(b, 8, 0) or _value(b, 17, 0):
        issues.append("material ID overrides not converted")
    if _value(b, 4, 0):
        issues.append("smoothing group override not converted")
    settings = (("solidify_mode", "EXTRUDE"), ("thickness", (hi - lo) * meters), ("offset", (hi + lo) / (hi - lo)),
                ("use_even_offset", False), ("use_rim", True))
    return settings, issues


def _blender(m, meters):
    """A reader (row-vector) matrix as Blender's columns, the translation in meters."""
    return tuple(tuple(m[r][c] * (meters if r == 3 else 1.0) for r in range(4)) for c in range(3)) + \
        ((0.0, 0.0, 0.0, 1.0),)


def mirror_frame(gizmo_tm, context_tm, offset):
    """The gizmo's frame in Blender's object space (row vectors, file units): gizmo * inverse(context) * offset;
    ModifierError when the context or the frame cannot be inverted."""
    import numpy
    g, c = numpy.asarray(gizmo_tm, dtype=numpy.float64), numpy.asarray(context_tm, dtype=numpy.float64)
    o = numpy.identity(4) if offset is None else numpy.asarray(offset, dtype=numpy.float64)
    for what, m in (("the modifier context", c), ("the gizmo", g)):
        det = numpy.linalg.det(m[:3, :3])
        if not math.isfinite(det) or abs(det) < 1e-12 * max(1.0, float(numpy.abs(m[:3, :3]).max()) ** 3):
            raise ModifierError("%s cannot be inverted" % what)
    e = g @ numpy.linalg.inv(c) @ o
    if not numpy.isfinite(e).all():
        raise ModifierError("the mirror frame is not finite")
    return tuple(tuple(float(x) for x in row) for row in e)


def _symmetry(scene, modifier, meters, offset):
    b, issues = _block(modifier), []
    axis = int(_value(b, 0, 0))
    if axis not in (0, 1, 2):
        raise ModifierError("axis %d" % axis)
    if modifier.context is None:
        raise ModifierError("no modifier context")
    i = modifier.refs.get(SLOT_GIZMO, modifier.gizmo)
    if i is None:
        gizmo = controllers.IDENTITY
        issues.append("no mirror gizmo: the object's own axes")
    else:
        gizmo, found = controllers.matrix(scene, i)
        fatal = [x.reason for x in found if x.reason.startswith(_FATAL)]
        if fatal:
            raise ModifierError("gizmo: %s" % fatal[0])
        issues += ["gizmo: %s" % x.reason for x in found]
    frame = mirror_frame(gizmo, modifier.context.tm, offset)
    identity = all(abs(frame[r][c] - (1.0 if r == c else 0.0)) <= IDENTITY_TOLERANCE for r in range(4)
                   for c in range(4))
    on = tuple(k == axis for k in range(3))
    slice_ = bool(_value(b, 1, 1))
    settings = (("use_axis", on), ("use_bisect_axis", on if slice_ else (False,) * 3),
                ("use_bisect_flip_axis", tuple(k == axis and bool(_value(b, 4, 0)) for k in range(3))
                 if slice_ else (False,) * 3),
                ("use_mirror_merge", bool(_value(b, 2, 1))), ("merge_threshold", float(_value(b, 3, 0.1)) * meters))
    return settings, None if identity else _blender(frame, meters), issues


def convert(scene, modifier, meters=1.0, offset=None):
    """(ModifierDescription, issues) of a modifier is_convertible() accepts; offset is the node's object offset (a
    reader matrix, None for the identity), meters the length of one file unit. ModifierError when refused."""
    kind = _KINDS.get(modifier.class_id) if is_convertible(modifier) else None
    if kind is None:
        raise ModifierError("not a modifier converted here")
    mirror = shading = None
    if kind == SUBSURF:
        settings, shading, issues = _smoother(modifier)
    elif kind == SOLIDIFY:
        settings, issues = _shell(modifier, meters)
    else:
        settings, mirror, issues = _symmetry(scene, modifier, meters, offset)
    entry = scene.entry(modifier.index)
    class_name = entry.name if entry is not None else ""
    return ModifierDescription(modifier.index, kind, modifier.name or class_name, class_name,
                               modifier.enabled_in_views, settings, mirror, shading), issues
