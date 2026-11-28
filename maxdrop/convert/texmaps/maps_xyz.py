# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rules of the 3D maps an XYZGen part places (Noise): a float pattern leaf, drawn with Blender's own Noise
Texture, as the mask of a Mix of the map's two sides; and the numbers the builder copies onto its nodes
(noise_placement, noise_detail), so that the plain tests pin them."""
from ...reader import classids
from .ids import (
    BUMP, NOISE_TYPES, NORMAL, NZ_COLOR1, NZ_COLOR2, NZ_HIGH, NZ_LEVELS, NZ_LOW, NZ_MAP1, NZ_MAP2, NZ_ON1,
    NZ_ON2, NZ_PHASE, NZ_SIZE, NZ_TYPE, OBJECT_XYZ, REGULAR, XYZ_ANGLE, XYZ_OFFSET, XYZ_TILING,
)
from .ir import Coordinates, Mix, Noise
from .maps import _other_side, _own_output, _own_part, _sides, WHITE
from .maps_pattern import _rotation, BLACK
from .values import _num, _vec


# Not measured (maxdrop-o53.3.10 fits them): 3ds Max's noise lattice per size against the Noise Texture's per unit
# of its vector (NOISE_SCALE), the XYZGen's order (offset, then tiling, then angle, about the object's origin), a
# level as one octave (Detail = levels - 1), turbulence as the folded fBm and the thresholds as a clamped ramp.
NOISE_SCALE = 1.0
DEFAULT_SIZE = 0.635  # meters: 3ds Max's default, 25 inches (635 in a millimeter file); a size not read takes it
MIN_SIZE = 1e-6  # meters
MAX_DETAIL = 15.0  # the Noise Texture's Detail range is 0..15
THRESHOLD_SPAN = 1e-3  # high threshold at least this above the low one: a step stays a ramp the Map Range can draw


def noise_placement(noise):
    """The (location, rotation, scale) of the POINT Mapping node that takes Blender's object coordinate p (meters) to
    the Noise Texture's vector q = NOISE_SCALE R(angle) (tiling * (p - offset)) / size (R as the Mapping node turns,
    XYZ Euler): scale NOISE_SCALE tiling / size, location -R (scale * offset)."""
    c = noise.coords
    scale = tuple(NOISE_SCALE * t / noise.size for t in c.tiling)
    r = _rotation(c.angle)
    shift = tuple(-s * o for s, o in zip(scale, c.offset))
    return tuple(sum(r[i][k] * shift[k] for k in range(3)) for i in range(3)), c.angle, scale


def noise_detail(noise):
    """The Noise Texture's Detail: 0 for a regular noise (3ds Max uses levels only for fractal and turbulence), else
    the octaves past the first, levels - 1, within 0..MAX_DETAIL."""
    return 0.0 if noise.kind == REGULAR else min(MAX_DETAIL, max(0.0, noise.levels - 1.0))


def _coordinates(conv, m):
    """The map's XYZGen part as Coordinates, its offset in meters. Its coordinate source and map channel are not
    decoded (maxdrop-o53.2.6): drawn as Object XYZ (maxdrop-o53.3.3 applies the others)."""
    xyz = next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_XYZGEN), None)
    if xyz is None:
        return Coordinates()

    def vec(index, default):
        return conv._old_vec(xyz, index, default, m, "Coordinates")
    offset = vec(XYZ_OFFSET, (0.0, 0.0, 0.0))
    return Coordinates(OBJECT_XYZ, 1, tuple(c * conv.meters for c in offset), vec(XYZ_TILING, (1.0, 1.0, 1.0)),
                       vec(XYZ_ANGLE, (0.0, 0.0, 0.0)))


def _noise_leaf(conv, m, walk):
    """The Noise leaf of map m: size in meters (a controller's at frame 0, else DEFAULT_SIZE, as every parameter),
    phase, levels, its type (another than 0 to 2: regular, an issue) and thresholds within 0..1."""
    stored = m.param(NZ_SIZE, 0)
    size = _num(m, NZ_SIZE, 0.0) * conv.meters
    if not size >= MIN_SIZE:
        if isinstance(stored, (int, float)) and not isinstance(stored, bool):  # a controller's has its own line
            conv._issue(walk, m.index, "Noise %r: size %r not converted: %g m" % (m.name, stored, DEFAULT_SIZE))
        size = DEFAULT_SIZE
    ntype = m.param(NZ_TYPE, 0)
    kind = NOISE_TYPES.get(ntype, REGULAR) if isinstance(ntype, int) and not isinstance(ntype, bool) else REGULAR
    if ntype is not None and kind == REGULAR and ntype != 0:
        conv._issue(walk, m.index, "Noise %r: type %r drawn as regular" % (m.name, ntype))
    low, high = (min(1.0, max(0.0, _num(m, pid, d))) for pid, d in ((NZ_LOW, 0.0), (NZ_HIGH, 1.0)))
    if high < low + THRESHOLD_SPAN:
        high = min(1.0, low + THRESHOLD_SPAN)
        low = high - THRESHOLD_SPAN
    return Noise(_coordinates(conv, m), size, _num(m, NZ_PHASE, 0.0), _num(m, NZ_LEVELS, 3.0), low, high, kind)


def _noise(conv, m, kind, walk, depth, chain):
    """0 / 1 color1 / 2, 2 / 3 map1 / 2, 4 / 5 their switches, 6 size, 7 phase, 8 levels, 9 / 10 thresholds, 11 type,
    12 coords: Mix(side 1, side 2) by the Noise leaf (side k: map k when used, else color k) under its Output part
    (as a Falloff's), approximated (Blender's noise is another than 3ds Max's: only its scale, octaves and contrast
    are matched), counted by class. In a bump input with black and white sides and no Output part the Bump of the
    leaf itself; in a normal map's normal slot nothing (an issue). A used map that converts to nothing: the other
    side's map (a peel)."""
    if kind == NORMAL:
        conv._issue(walk, m.index, "Noise %r: a pattern in a normal map's normal slot not converted" % (m.name,))
        return None
    pattern = _noise_leaf(conv, m, walk)
    ids = ((NZ_MAP1, NZ_ON1), (NZ_MAP2, NZ_ON2))
    if (kind == BUMP and _own_part(conv, m) is None and all(conv._on(m, pid, on) is None for pid, on in ids)
            and _vec(m, NZ_COLOR1, BLACK) == BLACK and _vec(m, NZ_COLOR2, WHITE) == WHITE):
        node = pattern  # black to white: the height is the pattern itself (the Mix of 0 and 1 by it)
    else:
        (a, b), lost = _sides(conv, m, ids, kind, walk, depth, chain)
        if any(lost):
            return _other_side(conv, m, (a, b), walk)
        a = a or conv._constant(m, NZ_COLOR1, kind, BLACK)
        b = b or conv._constant(m, NZ_COLOR2, kind, WHITE)
        node = _own_output(conv, m, Mix(a, b, 0.0, pattern))
    walk.approximated = True
    conv._count(conv.stats.approximated, m)
    return node

