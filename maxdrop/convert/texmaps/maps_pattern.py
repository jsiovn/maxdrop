# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rules of the pattern maps (Checker): a float pattern leaf as the mask of a Mix of the map's two sides, and the
pattern's own evaluator, the formula the builder draws with Math nodes."""
import dataclasses
import math

from ...reader import classids
from .ids import BUMP, CK_COLOR1, CK_COLOR2, CK_MAP1, CK_MAP2, CK_ON1, CK_ON2, CK_SOFTEN, NORMAL
from .ir import Checker, Mix
from .maps import _other_side, _sides, WHITE
from .values import _num, _vec


BLACK = (0.0, 0.0, 0.0)
# Not measured (maxdrop-o53.3.9 calibrates them): the squares per tile and axis, and color 1 on the square at the
# placed origin (floor(2x) + floor(2y) even), as the 3ds Max viewport shows a Checker at tiling 1.
CHECKER_SQUARES = 2


def _rotation(angle):
    """The 3 x 3 rotation of Euler angles (radians) in XYZ order, as Blender's Mapping node turns: Rz Ry Rx."""
    (ca, sa), (cb, sb), (cc, sc) = ((math.cos(a), math.sin(a)) for a in angle)
    return ((cc * cb, cc * sb * sa - sc * ca, cc * sb * ca + sc * sa),
            (sc * cb, sc * sb * sa + cc * ca, sc * sb * ca - cc * sa),
            (-sb, cb * sa, cb * ca))


def placed_uv(mapping, u, v):
    """The (x, y) a Mapping's tiling, offset and angles place UV (u, v) at, as a Bitmap's placement (the builder's
    uv_transform: tiled and turned about the tile center, (0.5, 0.5) + R S ((u, v) - (0.5 + offset)))."""
    p = (mapping.tiling[0] * (u - 0.5 - mapping.offset[0]), mapping.tiling[1] * (v - 0.5 - mapping.offset[1]), 0.0)
    r = _rotation(mapping.angle)
    return tuple(0.5 + sum(r[i][k] * p[k] for k in range(3)) for i in range(2))


def checker_value(checker, u, v):
    """The pattern of a Checker leaf at UV (u, v): 0.0 on color 1's squares, 1.0 on color 2's (floor(2x) + floor(2y)
    wrapped to 0..2, as the builder's Math WRAP does)."""
    x, y = placed_uv(checker.mapping, u, v)
    s = math.floor(CHECKER_SQUARES * x) + math.floor(CHECKER_SQUARES * y)
    return float(s - 2 * math.floor(s / 2.0))


def _pattern_mapping(conv, m, walk, cls):
    """A pattern map's UVGen as a Mapping (a Bitmap's rules); what the pattern cannot draw is an issue: tile off and
    mirror (the pattern repeats), map channel 0 (UV channel 1), environment, planar XYZ and real-world scale."""
    uv = next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_UVGEN), None)
    mapping = conv._mapping(uv, m)
    conv._placement_issues(m, walk, cls, mapping)
    if not all(mapping.tile) or any(mapping.mirror):
        conv._issue(walk, m.index, "%s %r: tile off or mirror not converted: the pattern repeats" % (cls, m.name))
        mapping = dataclasses.replace(mapping, tile=(True, True), mirror=(False, False))
    if mapping.channel == 0:
        conv._issue(walk, m.index, "%s %r: map channel 0 (vertex color) not imported: drawn on UV channel 1"
                    % (cls, m.name))
        mapping = dataclasses.replace(mapping, channel=1)
    return mapping


def _checker(conv, m, kind, walk, depth, chain):
    """0 soften, 1 / 2 color1 / 2, 3 / 4 map1 / 2, 5 / 6 their switches, 7 coords: Mix(side 1, side 2) by the Checker
    leaf (side k: map k when used, else color k). Exact: the mask is 0 or 1, so the sides stay in the input's kind
    also with the gamma off (decoding before or after picking one side is the same; not so once soften is drawn).
    A soften above 0 is drawn as 0 (an issue). In a bump input the Bump of the pattern itself, its sides a line when
    they are not black and white; in a normal map's normal slot nothing (an issue). A used map that converts to
    nothing: the other side's map (a peel)."""
    if kind == NORMAL:
        conv._issue(walk, m.index, "Checker %r: a pattern in a normal map's normal slot not converted" % (m.name,))
        return None
    soften = _num(m, CK_SOFTEN, 0.0)
    if soften > 0.0:
        conv._issue(walk, m.index, "Checker %r: soften %g not converted: hard edges" % (m.name, soften))
    pattern = Checker(_pattern_mapping(conv, m, walk, "Checker"), soften)
    ids = ((CK_MAP1, CK_ON1), (CK_MAP2, CK_ON2))
    if kind == BUMP:
        if (any(conv._on(m, pid, on) is not None for pid, on in ids) or _vec(m, CK_COLOR1, BLACK) != BLACK
                or _vec(m, CK_COLOR2, WHITE) != WHITE):
            conv._issue(walk, m.index, "Checker %r: its sides in a bump input not converted: drawn black to white"
                        % (m.name,))
        return pattern
    (a, b), lost = _sides(conv, m, ids, kind, walk, depth, chain)
    if any(lost):
        return _other_side(conv, m, (a, b), walk)
    a = a or conv._constant(m, CK_COLOR1, kind, BLACK)
    b = b or conv._constant(m, CK_COLOR2, kind, WHITE)
    return Mix(a, b, 0.0, pattern)
