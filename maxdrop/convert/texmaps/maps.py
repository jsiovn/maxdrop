# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rules of the wrapper maps: Falloff, VRayDirt, Output, RGB Tint, Color2Bump, Mix, RGB Multiply, Color Correction and Composite."""
from ...reader import classids, pblock
from ...reader import materials as reader_materials
from ...reader.classdir import ClassId
from ...reader.errors import MaxFileError
from ..params import finite as _finite
from .ids import (
    BLENDS, CC_REWIRE, CC_REWIRE_MODE, COLOR, CURVE_IDENTITY, CURVE_STEPS, DATA, FALLOFF_TYPES, FO_AMOUNT1, FO_AMOUNT2,
    FO_COLOR1, FO_COLOR2, FO_DIRECTION, FO_IOR, FO_IOR_OVERRIDE, FO_MAP1, FO_MAP2, FO_ON1, FO_ON2, FO_TYPE, FRESNEL,
    MASK, MAX_CURVE_SAMPLES, MIX, MIX_LOWER, MIX_UPPER, NORMAL_BLEND, REWIRE_INVERT, REWIRE_MONO, REWIRE_NONE, RW_ALPHA,
    RW_INV_ALPHA, RW_ONE, RW_ZERO, STORED, TINT_BLUE, TINT_GREEN, TINT_RED,
)
from .ir import (
    Adjust, ColorCorrect, Composite, CompositeLayer, Constant, Decode, Facing, Mix, Multiply, Remap, Smoothstep, Tint,
)
from .values import _constant_value, _flag, _num, _ref, _vec, rgb_kind


def _falloff_peel(conv, m, kind, walk, depth, chain):
    """A Falloff of a type or direction not drawn: map 1 when used, else color 1; counted as a peel."""
    if conv._on(m, FO_MAP1, FO_ON1) is not None:
        node = conv._sub(m, FO_MAP1, FO_ON1, kind, walk, depth, chain)
    else:
        node = conv._constant(m, FO_COLOR1, kind, (0.0, 0.0, 0.0))
    if node is not None:
        walk.approximated = True
        conv._count(conv.stats.peeled, m)
    return node


def _bezier_y(p0, c1, c2, p3, x):
    """y of the cubic Bezier p0, c1, c2, p3 where its x is x (bisection on the curve parameter, which assumes x(t)
    rises: handles far past the neighbouring points make it fold back, and y is then only near; a fixed 40 steps)."""
    def at(t, i):
        s = 1.0 - t
        return s * s * s * p0[i] + 3.0 * s * s * t * c1[i] + 3.0 * s * t * t * c2[i] + t * t * t * p3[i]
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if at(mid, 0) < x:
            lo = mid
        else:
            hi = mid
    return at(0.5 * (lo + hi), 1)


def curve_samples(points):
    """A Custom Curve Control's curve (reader CurvePoints) as 3ds Max 2020 evaluates it (measured, ICurve.GetValue
    and Falloff renders): segment i the cubic Bezier point i, its out handle, the in handle of point i + 1, point
    i + 1, its y at x; the flags do not change it; a point's y outside 0..1 is taken at the nearest bound, its handles
    moved with it; between the points the curve is not clamped. As a polyline, (x, y) pairs x ascending: a segment
    whose handles lie on its points is straight (its ends), any other one CURVE_STEPS steps of x (fewer, and the
    result resampled, past MAX_CURVE_SAMPLES). None when it is y = x (the default curve): no node. points: two or more
    (reader mix_curve's bound; an empty one raises IndexError)."""
    pts = []
    for p in points:
        (x, y), (ix, iy), (ox, oy) = p.point, p.in_handle, p.out_handle
        shift = min(1.0, max(0.0, y)) - y
        pts.append(((x, y + shift), (ix, iy + shift), (ox, oy + shift)))
    segments = list(zip(pts, pts[1:]))
    curved = sum(1 for (p0, _i0, o0), (p1, i1, _o1) in segments if p1[0] > p0[0] and not (o0 == p0 and i1 == p1))
    steps = max(1, min(CURVE_STEPS, (MAX_CURVE_SAMPLES - len(pts)) // max(1, curved)))
    out = [pts[0][0]]
    for (p0, _in0, out0), (p1, in1, _out1) in segments:
        if p1[0] <= p0[0] or (out0 == p0 and in1 == p1):
            out.append(p1)
            continue
        for k in range(1, steps + 1):
            x = p0[0] + (p1[0] - p0[0]) * k / steps
            out.append((x, p1[1] if k == steps else _bezier_y(p0, out0, in1, p1, x)))
    if len(out) > MAX_CURVE_SAMPLES:
        out = _resampled(out, MAX_CURVE_SAMPLES)
    if out[0][0] <= 0.0 and out[-1][0] >= 1.0 and all(abs(y - x) <= CURVE_IDENTITY for x, y in out) and \
            abs(out[0][1]) <= CURVE_IDENTITY and abs(out[-1][1] - 1.0) <= CURVE_IDENTITY:
        return None
    return tuple(out)


def _resampled(points, n):
    """The polyline points (x ascending) at n even steps of x from its first x to its last."""
    x0, x1 = points[0][0], points[-1][0]
    out, k = [], 0
    for j in range(n):
        x = x0 + (x1 - x0) * j / (n - 1)
        while k < len(points) - 2 and points[k + 1][0] <= x:
            k += 1
        (xa, ya), (xb, yb) = points[k], points[k + 1]
        out.append((x, yb if xb <= xa else ya + (yb - ya) * min(1.0, max(0.0, (x - xa) / (xb - xa)))))
    return out


def mix_factor(x, lower, upper):
    """A Mix's factor under Use Curve (measured with renderMap, by the mix amount and by a mask alike): 0 below lower,
    1 from upper on, between them smoothstep of (x - lower) / (upper - lower); lower >= upper: a step at lower."""
    if x < lower:
        return 0.0
    if x >= upper:
        return 1.0
    u = (x - lower) / (upper - lower)
    return u * u * (3.0 - 2.0 * u)


def _mix_curve(conv, m, walk):
    """The Remap points of Falloff m's MixCurve; None when it is linear, has none, or cannot be read (an issue)."""
    try:
        points = reader_materials.mix_curve(conv.graph.scene, m)
    except MaxFileError as e:
        walk.approximated = True
        conv._issue(walk, m.index, "Falloff %r: its mix curve could not be read (%s): drawn linear" % (m.name, e))
        return None
    return curve_samples(points) if points is not None else None


def _own_part(conv, m):
    """The TexOutput of the map's own Output part, None when it changes nothing."""
    return conv._output(next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_TEXOUTPUT), None),
                        m)


def _own_output(conv, m, node):
    """node under the map's own Output part (Adjust) when that changes anything."""
    out = _own_part(conv, m)
    return node if node is None or out is None else Adjust(node, out)


def _falloff(conv, m, kind, walk, depth, chain):
    """Types 0, 1 and 2 in the viewing direction: Mix(side 1, side 2) by a Facing; side k is lerp(color k, map k,
    amount k) when map k is used, else color k (measured). An edited MixCurve: the Facing under a Remap (_mix_curve;
    3ds Max applies it to the ratio of all three types, unclamped, measured). Any other type or direction: peeled
    (_falloff_peel). A used map that converts to nothing: the other side's map (a peel)."""
    ftype, direction = m.param(FO_TYPE, 0), m.param(FO_DIRECTION, 0)
    ftype = 1 if ftype is None else ftype
    if ftype not in FALLOFF_TYPES or direction not in (None, 0):
        node = _falloff_peel(conv, m, kind, walk, depth, chain)
        if node is not None:
            conv._issue(walk, m.index, "Falloff %r: type %r, direction %r drawn as its first side"
                        % (m.name, ftype, direction))
        return node
    ids = ((FO_MAP1, FO_ON1), (FO_MAP2, FO_ON2))
    (a, b), lost = _sides(conv, m, ids, kind, walk, depth, chain)
    if any(lost):
        return _other_side(conv, m, (a, b), walk)
    sides = []
    for node, color, amount_pid, default in ((a, FO_COLOR1, FO_AMOUNT1, (0.0, 0.0, 0.0)),
                                              (b, FO_COLOR2, FO_AMOUNT2, (1.0, 1.0, 1.0))):
        constant = conv._constant(m, color, kind, default)
        if node is None:
            sides.append(constant)
            continue
        amount = min(1.0, max(0.0, _num(m, amount_pid, 100.0) / 100.0))
        sides.append(node if amount >= 1.0 else Mix(constant, node, amount))
    mode, ior = FALLOFF_TYPES[ftype], 1.6
    if mode == FRESNEL:
        ior = _num(m, FO_IOR, 1.6)
        if not 1.0 <= ior <= 10.0:
            conv._issue(walk, m.index, "Falloff %r: IOR %r not converted: 1.6" % (m.name, ior))
            ior = 1.6
        if not _flag(m, FO_IOR_OVERRIDE, True):
            conv._issue(walk, m.index, "Falloff %r: the material's IOR not read: its own, %g" % (m.name, ior))
    ratio = Facing(mode, ior)
    curve = _mix_curve(conv, m, walk)
    return _own_output(conv, m, Mix(sides[0], sides[1], 0.0, ratio if curve is None else Remap(ratio, curve)))


def _vray_dirt(conv, m, kind, walk, depth, chain):
    """13 unoccluded_color, 17 texmap_unoccluded_color, 18 its switch. The color only when the map is not used. Corona
    12 does not render a VRayDirt: white, its map on or off (maxdrop-6n0.6.23), so white in a Corona scene, exact
    (TexmapConverter._node; measured in a light material's texmap, assumed for other slots)."""
    if conv._on(m, 17, 18) is not None:
        return conv._sub(m, 17, 18, kind, walk, depth, chain)
    return conv._constant(m, 13, kind, (1.0, 1.0, 1.0))


WHITE = (1.0, 1.0, 1.0)
C2B_EMPTY = (0.5, 0.5, 1.0)  # what a VRayColor2Bump without a map renders: a flat normal's color
# Corona's renderer ClassID (Corona 12), as the summary stream names a scene's renderer (Renderer ClassIDA / B,
# reader.metadata); not a class of the class directory, so not in reader.classids
CORONA_RENDERER = (0x62A85DCC, 0x523C3604)


def _wrapped(conv, m, map_pid, on_pid, kind, walk, depth, chain, empty=WHITE):
    """The map of a wrapper that has no color of its own (Output, RGB Tint, VRayColor2Bump), in kind (the caller's
    _wrapper_input when the wrapper changes the color); without a used map the swatch empty: an Output or RGB Tint
    renders as over a white map, a VRayColor2Bump the color C2B_EMPTY (3ds Max 2020 renderMap and V-Ray 5.2 renders with the
    gamma off, maxdrop-em3.76; V-Ray with the gamma on and Corona 12 with it off and on render the same,
    maxdrop-em3.127, but for an Output switched off in Corona: _output_map). In a normal input (a normal map's normal
    slot) that color as stored: V-Ray tilts the normal by an Output's or RGB Tint's white as by a white map, and
    leaves it flat for C2B_EMPTY, which the builder draws the same (maxdrop-em3.128)."""
    if conv._on(m, map_pid, on_pid) is None:
        return conv._swatch(empty, kind)
    return conv._sub(m, map_pid, on_pid, kind, walk, depth, chain)


def _wrapper_input(conv, kind):
    """The kind of the map below a wrapper that changes the color (an RGB Tint other than the identity, an Output
    part that changes anything, a Color Correction in a mask) in a graph of that kind: rgb_kind; in a mask the color
    V-Ray holds, COLOR with the gamma on (linear), STORED with it off (swatches, the Tint's rows and a Bitmap as
    stored), the mean taken after it (_mask_mean; maxdrop-6n0.6.2, maxdrop-6n0.6.18)."""
    if kind == MASK:
        return COLOR if conv.swatches.linear else STORED
    return rgb_kind(kind)


def _mask_mean(conv, node, kind):
    """A color wrapper's node as a mask in a gamma-off scene: V-Ray mixes by the mean of the color it holds, the same
    value as with the gamma on, which the display-referred scene shows decoded (maxdrop-6n0.6.2: a Tint of rows
    128 / 64 / 32 over a VRayColor (200, 100, 50) renders 0.1722 in both modes, decoded 0.0251), so the mean through
    the exact sRGB curve (Decode mean), as _decoded_mask draws a mix; a Tint or an Adjust over a Constant folded.
    Elsewhere the node: the builder takes the mean of a color socket on a float input."""
    if node is None or kind != MASK or conv.swatches.linear:
        return node
    value = _constant_value(node)
    if value is not None:
        return Constant(conv.swatches.channel(sum(value) / 3.0))
    return Decode(node, mean=True)


def _output_map(conv, m, kind, walk, depth, chain):
    """0 map1, 1 map1Enabled; its Output part as an Adjust (its clamp and color map curve are not read) over its map
    as a color (_wrapper_input; in a gamma-off mask the mean decoded after it, _mask_mean); an Output part that
    changes nothing leaves the map in its own kind, as with no wrapper. Corona 12 renders map1 with map1Enabled off
    (Corona's own materials measured, maxdrop-em3.127): in a scene that renders with Corona the switch is not read."""
    out = _own_part(conv, m)
    node = _wrapped(conv, m, 0, None if conv.corona else 1, kind if out is None else _wrapper_input(conv, kind),
                    walk, depth, chain)
    return node if node is None or out is None else _mask_mean(conv, Adjust(node, out), kind)


def _rgb_tint(conv, m, kind, walk, depth, chain):
    """0 / 1 / 2 red / green / blue (swatches: made linear in a color graph, as stored in a data graph, a height, a
    normal and a gamma-off mask, as every swatch there; em3.76 measured 0.293 on opacity for rows 128 / 64 / 32 over
    white, gamma off), 3 map1, 4 map1Enabled: a Tint over its map as a color (_wrapper_input; in a gamma-off mask
    the mean decoded after it, _mask_mean) unless the identity, which leaves the map in its own kind."""
    inner = _wrapper_input(conv, kind)
    rows = COLOR if kind == COLOR else inner
    tint = tuple(conv._constant(m, pid, rows, d).value
                 for pid, d in ((TINT_RED, (1.0, 0.0, 0.0)), (TINT_GREEN, (0.0, 1.0, 0.0)),
                                (TINT_BLUE, (0.0, 0.0, 1.0))))
    if all(abs(c - (1.0 if i == j else 0.0)) <= 1e-6 for j, row in enumerate(tint) for i, c in enumerate(row)):
        return _wrapped(conv, m, 3, 4, kind, walk, depth, chain)
    node = _wrapped(conv, m, 3, 4, inner, walk, depth, chain)
    return None if node is None else _mask_mean(conv, Tint(node, *tint), kind)


def _color2bump(conv, m, kind, walk, depth, chain):
    """0 map (no switch): peeled to it, counted; without one the constant C2B_EMPTY, exact (not counted)."""
    if conv._on(m, 0, None) is None:
        return _wrapped(conv, m, 0, None, kind, walk, depth, chain, C2B_EMPTY)
    node = conv._sub(m, 0, None, kind, walk, depth, chain)
    if node is not None:
        walk.approximated = True
        conv._count(conv.stats.peeled, m)
    return node


def _sides(conv, m, ids, kind, walk, depth, chain, known=None):
    """The nodes of a two-map wrapper's sides ((map pid, switch pid) each), None where no map is used, and per side
    whether a used map converted to nothing. known: {map pid: node} of sides the caller converted already."""
    known = known or {}
    nodes = tuple(known[pid] if pid in known else conv._sub(m, pid, on, kind, walk, depth, chain) for pid, on in ids)
    lost = tuple(n is None and conv._on(m, pid, on) is not None for n, (pid, on) in zip(nodes, ids))
    return nodes, lost


def _lost_weight(lost, weights):
    """How much the lost sides show in the result, from each side's weight (0, 1, or None: partly or unknown, as
    under a mask): 0.0 none of them shows (their colors are drawn and stay invisible, exact), 1.0 one fills it (no
    graph), None partly (the wrapper is peeled to its other map)."""
    ws = [w for gone, w in zip(lost, weights) if gone]
    if any(w == 1.0 for w in ws):
        return 1.0
    return 0.0 if all(w == 0.0 for w in ws) else None


def _other_side(conv, m, nodes, walk):
    """A two-map wrapper with a lost map: its other side's map (a peel), else nothing; never its own color for the
    lost one, which 3ds Max uses only when no map is set or the map is off."""
    node = next((n for n in nodes if n is not None), None)
    if node is not None:
        walk.approximated = True
        conv._count(conv.stats.peeled, m)
    return node


def mask_kind(kind):
    """The kind of a mask below a map of that kind: MASK in a color graph (and below a mask), DATA elsewhere (in
    STORED too: V-Ray mixes by the mask's own value there)."""
    return MASK if kind in (COLOR, MASK) else DATA


def _black_white(conv, m):
    """A Mix between its colors black and white (no map on a side, no curve): in a gamma-off color graph it stays a
    Mix of decoded colors by a decoded mask or amount, exact (maxdrop-em3.36), not a Decode."""
    if ClassId(*m.class_id) != MIX or _flag(m, 3, False):
        return False
    if conv._on(m, 6, 9) is not None or conv._on(m, 7, 10) is not None:
        return False
    return _vec(m, 4, (0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0) and _vec(m, 5, (1.0, 1.0, 1.0)) == (1.0, 1.0, 1.0)


def _mask(conv, m, pid, on_pid, kind, walk, depth, chain):
    """A mask map below a map of that kind; a used one that converts to nothing leaves the mix amount (an
    approximation)."""
    mask = conv._sub(m, pid, on_pid, mask_kind(kind), walk, depth, chain)
    if mask is None and conv._on(m, pid, on_pid) is not None:
        walk.approximated = True
    return mask


def _mix(conv, m, kind, walk, depth, chain):
    """0 mixAmount (fraction), 1 lower, 2 upper, 3 useCurve, 4 / 5 color1 / 2, 6 / 7 map1 / 2, 8 mask, 9 / 10 / 11
    their switches. Use Curve (mix_factor): the mix amount through it, or the mask under a Smoothstep."""
    (a, b), lost = _sides(conv, m, ((6, 9), (7, 10)), kind, walk, depth, chain)
    mask = _mask(conv, m, 8, 11, kind, walk, depth, chain)
    factor, curve = min(1.0, max(0.0, _num(m, 0, 0.0))), _flag(m, 3, False)
    if curve:
        lower, upper = _num(m, MIX_LOWER, 0.3), _num(m, MIX_UPPER, 0.7)
        factor = mix_factor(factor, lower, upper)  # also with a mask: what the builder takes when its image is missing
        mask = Smoothstep(mask, lower, upper) if mask is not None else None
    if any(lost):
        w = _lost_weight(lost, (None, None) if mask is not None else (1.0 - factor, factor))
        if w == 1.0:
            return None
        if w is None:
            return _other_side(conv, m, (a, b), walk)
    a = a or conv._constant(m, 4, kind, (0.0, 0.0, 0.0))
    b = b or conv._constant(m, 5, kind, (1.0, 1.0, 1.0))
    if kind in (COLOR, MASK) and not conv.swatches.linear:  # only black to white: _convert_node sends the rest
        factor = conv.swatches.channel(factor)  # to STORED
    return Mix(a, b, factor, mask)


def _rgb_multiply(conv, m, kind, walk, depth, chain):
    """0 / 1 color1 / 2, 2 / 3 map1 / 2, 4 / 5 their switches."""
    (a, b), lost = _sides(conv, m, ((2, 4), (3, 5)), kind, walk, depth, chain)
    if any(lost):
        return _other_side(conv, m, (a, b), walk)
    a = a or conv._constant(m, 0, kind, (1.0, 1.0, 1.0))
    b = b or conv._constant(m, 1, kind, (1.0, 1.0, 1.0))
    return Multiply(a, b)


def _color_correction(conv, m, kind, walk, depth, chain):
    """0 color, 1 map, 2 rewireMode, 7 hueShift (degrees), 8 saturation (%), 10 tintStrength, 11 lightnessMode
    (0 standard: 12 brightness, 13 contrast; 1 advanced: 18 gainRGB (%), 22 gammaRGB, 26 pivotRGB, 30 liftRGB).
    Its color only without a map (3ds Max's rule): a map that converts to nothing leaves the input its own value.
    The map and the color are a color (rgb_kind): the correction acts on it, a float input takes the mean after. In
    a mask they are the color V-Ray holds (_wrapper_input: COLOR with the gamma on, STORED with it off), the mean
    taken after the correction, decoded with the gamma off (_mask_mean), as a Tint's or Output's (V-Ray 5.2 renders,
    maxdrop-6n0.6.18: brightness 20 over a VRayColor 128 as a mask 0.702 in both modes; a rewiring picks from that
    color, red to all over (200, 100, 50) 0.784, monochrome 0.4575, as maxdrop-6n0.6.36 assumed; saturation -50 % the
    mean of the builder's HSL saturation, 0.4739, maxdrop-6n0.6.2)."""
    inner = _wrapper_input(conv, kind)
    node = conv._sub(m, 1, None, inner, walk, depth, chain)
    if node is None:
        if conv._on(m, 1, None) is not None:
            return None
        node = conv._constant(m, 0, inner, (0.0, 0.0, 0.0))
    if _num(m, 10, 0.0) != 0.0:
        walk.approximated = True
        conv._issue(walk, m.index, "Color Correction %r: tint not converted" % (m.name,))
    rewire = _rewire(conv, m, walk)
    hue, saturation = _num(m, 7, 0.0) / 360.0, 1.0 + _num(m, 8, 0.0) / 100.0
    if m.param(11, 0) != 1:
        cc = ColorCorrect(node, rewire, hue, saturation, _num(m, 12, 0.0) / 100.0, _num(m, 13, 0.0) / 100.0)
    else:
        if _num(m, 26, 1.0) != 1.0 or _num(m, 30, 0.0) != 0.0:
            walk.approximated = True
            conv._issue(walk, m.index, "Color Correction %r: pivot and lift not converted" % (m.name,))
        cc = ColorCorrect(node, rewire, hue, saturation, gain=_num(m, 18, 100.0) / 100.0,
                          gamma=max(0.01, _num(m, 22, 1.0)))
    return _mask_mean(conv, cc, kind)


def _rewire(conv, m, walk):
    """The rewiring of a Color Correction (rewireMode 2; channels 3 to 5 in custom mode, 3). An alpha source is
    drawn as one (alpha) or zero (its inverse): the map's alpha is not carried; an unreadable channel or mode
    leaves the color unchanged. Both are issues. A channel or mode a controller holds is its whole value at frame 0
    (params.frame_zero); a fraction is unreadable."""
    mode = m.param(CC_REWIRE_MODE, 0)
    if mode in (None, 0):
        return REWIRE_NONE
    if mode == 1:
        return REWIRE_MONO
    if mode == 2:
        return REWIRE_INVERT
    channels = tuple(m.param(pid, 0) for pid in CC_REWIRE) if mode == 3 else None
    if channels is None or not all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= RW_ZERO
                                   for c in channels):
        walk.approximated = True
        conv._issue(walk, m.index, "Color Correction %r: rewiring %r not converted" % (
            m.name, channels if channels is not None else mode))
        return REWIRE_NONE
    if RW_ALPHA in channels or RW_INV_ALPHA in channels:
        walk.approximated = True
        conv._issue(walk, m.index, "Color Correction %r: rewired from alpha, drawn as opaque" % (m.name,))
        channels = tuple(RW_ONE if c == RW_ALPHA else RW_ZERO if c == RW_INV_ALPHA else c for c in channels)
    return channels


def _composite(conv, m, kind, walk, depth, chain):
    """Tables: 1 mapEnabled, 3 maskEnabled, 5 blendMode, 8 opacity (%), 9 mapList, 10 mask. Kept when every used
    layer above the bottom one has a blend mode in BLENDS (the bottom one is over black whatever its mode); else
    peeled to its first Bitmap. A layer's mask (on and set) is a float node of mask_kind(kind); one that converts to
    nothing leaves the opacity (an approximation)."""
    block = m.block(0)
    maps = block.value(9) if block is not None else None
    maps = maps if isinstance(maps, list) else []

    def at(pid, k, default):
        v = m.param(pid, 0, tab=k)
        return v if _finite(v) else default

    used = [k for k, r in enumerate(maps) if isinstance(r, pblock.Reference) and r.index is not None
            and at(1, k, 1)]
    modes = [at(5, k, 0) for k in used[1:]]
    if not all(mode in BLENDS for mode in modes):
        bad = sorted({mode for mode in modes if mode not in BLENDS})
        image = conv._peel_to_image(m, kind, walk, depth, chain, "blend modes %s, and no bitmap below" % (bad,))
        if image is not None:
            conv._issue(walk, m.index, "Composite %r: blend modes %s not converted" % (m.name, bad))
        return image
    layers = []
    for k in used:
        node = conv._node(maps[k].index, kind, walk, depth, chain)
        if node is None:
            walk.approximated = True
            conv._lost(m, maps[k].index, walk)
            continue
        mask = None
        if at(3, k, 1) and _ref(m, 10, k) is not None:
            mask = conv._node(_ref(m, 10, k), mask_kind(kind), walk, depth, chain)
            if mask is None:
                walk.approximated = True
                conv._lost(m, _ref(m, 10, k), walk)
        blend = at(5, k, 0) if layers else NORMAL_BLEND
        layers.append(CompositeLayer(node, min(1.0, max(0.0, at(8, k, 100.0) / 100.0)), blend, mask))
    if not layers:
        return None
    if len(layers) == 1 and layers[0].opacity == 1.0 and layers[0].mask is None:
        return layers[0].node
    return Composite(tuple(layers))
