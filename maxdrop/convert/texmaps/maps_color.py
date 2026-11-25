# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rules of CoronaColor, VRayColor and CoronaMix."""
import math

from .. import colors
from ..params import finite as _finite
from .ids import (
    CC_COLOR, CC_HDR, CC_HEX, CC_METHOD, CC_MULTIPLIER, CC_TEMPERATURE, CM_AMOUNT, CM_BLENDS, CM_BOTTOM_ON,
    CM_COLOR_BOTTOM, CM_COLOR_TOP, CM_GAMMA, CM_GAMMA_OPS, CM_GAMMA_RANGE, CM_MAP_BOTTOM, CM_MAP_TOP, CM_MASK,
    CM_MASK_ON, CM_MIX, CM_MULT_BOTTOM, CM_MULT_TOP, CM_MULTIPLY, CM_OFFSET_BOTTOM, CM_OFFSET_SCALE, CM_OFFSET_TOP,
    CM_OP_NAMES, CM_OPERATION, CM_SRGB, CM_SRGB_GAMMA, CM_TOP_ON, COLOR, MASK, MAX_MULTIPLIER, VC_ALPHA, VC_BLUE,
    VC_COLOR, VC_GAMMA, VC_GREEN, VC_MODE, VC_MULTIPLIER, VC_PRIMARIES, VC_RED,
)
from .ir import Adjust, Blend, ColorCorrect, Constant, Mix, Multiply, TexOutput
from .values import _flag, _linear, _num, _vec, blend_value, corona_kelvin
from .maps import _lost_weight, _mask, _other_side, _sides


def _hex_rgb(text):
    """'#RRGGBB' as a swatch (0..1), None when it is not one."""
    s = text.strip().lstrip("#") if isinstance(text, str) else ""
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[k:k + 2], 16) / 255.0 for k in (0, 2, 4))
    except ValueError:
        return None


def _corona_color(conv, m, kind, walk, depth, chain):
    """50 method (0 color 52, 1 HDR color 58, 2 temperature 51, 3 hex 59), 57 multiplier. Color and hex are swatches,
    made linear by the scene's rule after the multiplier (a renderMap render in 3ds Max showed the multiplier
    scaling the swatch value: 2 x 128 = 255); the temperature is Corona's own linear color (corona_kelvin) times the
    multiplier with the gamma on, decoded as a swatch (clamped) with it off: VRayColor's and CoronaColor's 3000 K
    render the same values with the gamma on and off (V-Ray 5.2, renderMap; maxdrop-em3.38), which a gamma-off
    scene shows as stored. The HDR color times the multiplier is rendered as stored, unclamped, with the gamma on and
    off (V-Ray 5.2 and Corona 12, maxdrop-em3.165): linear with the gamma on; with it off the scene shows it decoded,
    above 1 on the extended curve (2.0: 4.954), on a color input per channel, on a mask the mean (a swatch's rule);
    in STORED as stored (the Decode above shows it); on a data input as stored. colorSpace (61) changed nothing in
    renderMap: not read."""
    method, mult = m.param(CC_METHOD, 0), max(0.0, _num(m, CC_MULTIPLIER, 1.0))
    if method == 1:
        rgb = tuple(max(0.0, c) * mult for c in _vec(m, CC_HDR, (1.0, 1.0, 1.0)))
        if not conv.swatches.linear and kind == COLOR:
            return Constant(tuple(colors.srgb_to_linear(c) for c in rgb))
        if not conv.swatches.linear and kind == MASK:
            return Constant(colors.srgb_to_linear(sum(rgb) / 3.0))
        return _linear(rgb, kind)
    swatch = None
    if method == 2:
        lin = tuple(c * mult for c in corona_kelvin(_num(m, CC_TEMPERATURE, 6500.0)))
        if not conv.swatches.linear:
            return conv._swatch(lin, kind)
        return _linear(lin, kind)
    if method == 3:
        swatch = _hex_rgb(m.param(CC_HEX, 0))
        if swatch is None:
            conv._issue(walk, m.index, "CoronaColor %r: hex color %r not read: its color" % (
                m.name, m.param(CC_HEX, 0)))
    elif method not in (None, 0):
        conv._issue(walk, m.index, "CoronaColor %r: method %r not converted: its color" % (m.name, method))
    if swatch is None:
        v = m.param(CC_COLOR, 0)
        swatch = v[:3] if isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3]) else (1.0,) * 3
    return conv._swatch(tuple(c * mult for c in swatch), kind)


def _vray_color(conv, m, kind, walk, depth, chain):
    """VRayColor: its swatch (color, else red / green / blue) times rgb_multiplier, then to the power color_gamma
    (renderMap in 3ds Max: (100 gray, multiplier 2, gamma 2) -> 255 * (200 / 255) ^ 2), then made linear by the
    scene's rule like every swatch. In temperature mode color holds V-Ray's own temperature color, taken through
    the same rule (V-Ray 5.2 renders it the same with the gamma on and off: decoded with it off, as CoronaColor's
    temperature). A mono input takes the color, not the alpha (measured with a Mix mask); on a mask in a color
    graph the Constant is the scene's rule applied to the mean of the swatch, on a data input the mean as stored
    (V-Ray 5.2: glossiness 0.251 for grey 64 in both modes), as every swatch constant's (_swatch)."""
    mode = m.param(VC_MODE, 0)
    v = m.param(VC_COLOR, 0)
    if not (isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3])):
        v = tuple(m.param(pid, 0) for pid in (VC_RED, VC_GREEN, VC_BLUE))
    swatch = tuple(float(c) for c in v[:3]) if all(_finite(c) for c in v[:3]) else None
    if swatch is None:
        swatch = (1.0, 1.0, 1.0)
        if mode == 1:
            conv._issue(walk, m.index, "VRayColor %r: temperature color not read: white" % (m.name,))
    mult = m.param(VC_MULTIPLIER, 0)
    if mult is None:
        mult = 1.0
    elif not (_finite(mult) and mult >= 0.0):
        conv._issue(walk, m.index, "VRayColor %r: RGB multiplier %r not converted: 1" % (m.name, mult))
        mult = 1.0
    gamma = m.param(VC_GAMMA, 0)
    if gamma is None:
        gamma = 1.0
    elif not (_finite(gamma) and 0.01 <= gamma <= 100.0):
        conv._issue(walk, m.index, "VRayColor %r: color gamma %r not converted: 1" % (m.name, gamma))
        gamma = 1.0
    if mode not in (None, 0, 1):
        conv._issue(walk, m.index, "VRayColor %r: color mode %r not converted: its color" % (m.name, mode))
    alpha = m.param(VC_ALPHA, 0)
    if _finite(alpha) and alpha != 1.0:
        conv._issue(walk, m.index, "VRayColor %r: alpha %r not converted: 1" % (m.name, alpha))
    primaries = m.param(VC_PRIMARIES, 0)
    if primaries not in (None, 0):
        conv._issue(walk, m.index, "VRayColor %r: RGB primaries %r drawn as sRGB" % (m.name, primaries))
    scaled = tuple(min(1.0, max(0.0, c * float(mult))) for c in swatch)
    return conv._swatch(tuple(c ** float(gamma) for c in scaled), kind)


def _corona_layer(node, mult, offset):
    """A CoronaMix layer times its multiplier plus its offset (CM_OFFSET_SCALE): a Constant folded, a map under an
    Adjust; the node itself when they change nothing."""
    if mult == 1.0 and offset == 0.0:
        return node
    mult, offset = (min(MAX_MULTIPLIER, max(-MAX_MULTIPLIER, v)) for v in (mult, offset))
    add = offset * CM_OFFSET_SCALE
    if isinstance(node, Constant):
        v = node.value
        return Constant(tuple(c * mult + add for c in v) if isinstance(v, tuple) else v * mult + add)
    return Adjust(node, TexOutput(level=mult, offset=add))


def _corona_gamma_exponent(top, srgb):
    """The exponents of a CoronaMix gamma (bottom^(1 / e) per channel, renderMap: e is the top, in sRGB mode
    |top|^(1 / 2.2)) from its converted top layer: a float or a tuple. None when the top is not a Constant (a map that
    converts to one, CoronaColor or VRayColor, is; maxdrop-6n0.6.24) or a channel's exponent is outside
    CM_GAMMA_RANGE (Corona's result is no number at a top of 0)."""
    if not isinstance(top, Constant):
        return None
    v = top.value
    es = tuple((abs(t) ** (1.0 / CM_SRGB_GAMMA) if srgb else t) for t in (v if isinstance(v, tuple) else (v,)))
    if not all(CM_GAMMA_RANGE[0] <= e <= CM_GAMMA_RANGE[1] for e in es):
        return None
    return es if isinstance(v, tuple) else es[0]


def _cm_top(conv, m, kind, node):
    """A CoronaMix's top layer: its map's node, else its color, times its multiplier plus its offset."""
    return _corona_layer(node or conv._constant(m, CM_COLOR_TOP, kind, (1.0, 1.0, 1.0)), _num(m, CM_MULT_TOP, 1.0),
                         _num(m, CM_OFFSET_TOP, 0.0))


def _cm_bottom(conv, m, kind, node):
    """A CoronaMix's bottom layer, as _cm_top."""
    return _corona_layer(node or conv._constant(m, CM_COLOR_BOTTOM, kind, (0.0, 0.0, 0.0)),
                         _num(m, CM_MULT_BOTTOM, 1.0), _num(m, CM_OFFSET_BOTTOM, 0.0))


def _gamma_layers(conv, m, kind, walk, depth, chain):
    """Whether a CoronaMix gamma can be drawn, decided layer by layer before the rest is converted, so a peeled one
    converts no more than it must: its top first (drawable only as a constant, a map that converts to one included),
    then, for one exponent per channel, its bottom (a constant). A map that converts to nothing leaves the decision
    to the lost-side rule (drawable). None when it cannot be drawn, else {map pid: node} of the layers it converted,
    which _corona_mix draws without converting them again."""
    top = conv._sub(m, CM_MAP_TOP, CM_TOP_ON, kind, walk, depth, chain)
    layers = {CM_MAP_TOP: top}
    if top is None and conv._on(m, CM_MAP_TOP, CM_TOP_ON) is not None:
        return layers
    exponent = _corona_gamma_exponent(_cm_top(conv, m, kind, top), _flag(m, CM_SRGB, True))
    if exponent is None:
        return None
    if not isinstance(exponent, tuple) or len(set(exponent)) == 1:
        return layers
    bottom = layers[CM_MAP_BOTTOM] = conv._sub(m, CM_MAP_BOTTOM, CM_BOTTOM_ON, kind, walk, depth, chain)
    return layers if bottom is None or isinstance(_cm_bottom(conv, m, kind, bottom), Constant) else None


def _corona_peel(conv, m, op, kind, walk, depth, chain):
    """A CoronaMix whose operation is not drawn: its first bitmap (an issue naming the operation), else nothing."""
    name = CM_OP_NAMES.get(op, repr(op))
    image = conv._peel_to_image(m, kind, walk, depth, chain, "operation %s and no bitmap below" % (name,))
    if image is not None:
        conv._issue(walk, m.index, "CoronaMix %r: operation %s drawn as its first bitmap" % (m.name, name))
    return image


def _gamma_value(v, e):
    """v^(1 / e) as a Gamma node draws it (a channel at or below 0 as it is), held within MAX_MULTIPLIER."""
    def one(x, p):
        return math.exp(min(math.log(MAX_MULTIPLIER), math.log(x) / p)) if x > 0.0 else x
    if isinstance(v, tuple):
        es = e if isinstance(e, tuple) else (e,) * len(v)
        return tuple(one(x, p) for x, p in zip(v, es))
    return one(v, e)


def _corona_mix(conv, m, kind, walk, depth, chain):
    """result = mix(bottom, operation(bottom, top), amount), the mask map replacing the amount (renderMap: an add at
    amount 0.8 under a 0.25 mask weighs 0.25), always a linear mix. Operation mix -> Mix(bottom, top, amount, mask),
    multiply -> Multiply, the operations of CM_BLENDS -> Blend (gamma 2.2 for CM_GAMMA_OPS with mixInSRgb on), gamma
    -> a ColorCorrect gamma of the bottom for a grey top (its color, or a map that converts to a constant; two
    constants folded per channel; in sRGB mode of the bottom's magnitude, maxdrop-6n0.6.40), each under a Mix when the amount is below 1 or a mask is set; any other operation
    (and a gamma over another top) is peeled to its first bitmap, a gamma as decided on its converted layers
    (_gamma_layers, maxdrop-6n0.6.24). Each layer is its map, or its color where the map is missing or switched off,
    times its multiplier plus its offset times CM_OFFSET_SCALE (measured, the multiplier first)."""
    op = m.param(CM_OPERATION, 0)
    if op not in (CM_MIX, CM_MULTIPLY, CM_GAMMA) and op not in CM_BLENDS:
        return _corona_peel(conv, m, op, kind, walk, depth, chain)
    layers = _gamma_layers(conv, m, kind, walk, depth, chain) if op == CM_GAMMA else {}
    if layers is None:
        return _corona_peel(conv, m, op, kind, walk, depth, chain)
    (bottom, top), lost = _sides(conv, m, ((CM_MAP_BOTTOM, CM_BOTTOM_ON), (CM_MAP_TOP, CM_TOP_ON)), kind, walk,
                                 depth, chain, layers)
    mask = _mask(conv, m, CM_MASK, CM_MASK_ON, kind, walk, depth, chain)
    amount = min(1.0, max(0.0, _num(m, CM_AMOUNT, 1.0)))
    if any(lost):
        if mask is not None:
            weights = (None, None)
        elif op == CM_MIX:
            weights = (1.0 - amount, amount)
        else:  # bottom op top: either side shows unless the amount is 0 (the bottom alone)
            weights = (1.0, 0.0) if amount == 0.0 else (None, None)
        w = _lost_weight(lost, weights)
        if w == 1.0:
            return None
        if w is None:
            return _other_side(conv, m, (bottom, top), walk)
    bottom, top = _cm_bottom(conv, m, kind, bottom), _cm_top(conv, m, kind, top)
    exponent = _corona_gamma_exponent(top, _flag(m, CM_SRGB, True)) if op == CM_GAMMA else None
    if isinstance(exponent, tuple) and len(set(exponent)) > 1 and not isinstance(bottom, Constant):
        exponent = None  # a colored top over a map: one exponent per channel, which no node draws
    if op == CM_GAMMA and exponent is None:  # a lost map's color in its place (amount 0) and still not drawable
        return _corona_peel(conv, m, op, kind, walk, depth, chain)
    if op == CM_MIX:
        return Mix(bottom, top, amount, mask)
    if op == CM_MULTIPLY:
        result = Multiply(bottom, top)
    elif op == CM_GAMMA:
        if isinstance(bottom, Constant):  # in sRGB mode |bottom|^(1 / e) (renderMap: P5, maxdrop-em3.161)
            v = bottom.value
            if _flag(m, CM_SRGB, True):
                v = tuple(abs(c) for c in v) if isinstance(v, tuple) else abs(v)
            result = Constant(_gamma_value(v, exponent))
        else:  # a map bottom too (renderMap: multiplierBottom -1 gives the positive one's values, 6n0.6.40)
            result = ColorCorrect(bottom, gamma=exponent if isinstance(exponent, float) else exponent[0],
                                  magnitude=_flag(m, CM_SRGB, True))
    else:
        blend = CM_BLENDS[op]
        gamma = CM_SRGB_GAMMA if blend in CM_GAMMA_OPS and _flag(m, CM_SRGB, True) else 1.0
        if isinstance(bottom, Constant) and isinstance(top, Constant):
            result = Constant(blend_value(blend, bottom.value, top.value, gamma))
        else:
            result = Blend(blend, bottom, top, gamma)
    return result if mask is None and amount == 1.0 else Mix(bottom, result, amount, mask)
