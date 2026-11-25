# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Value helpers: numbers, Kelvin colors, blend values, kinds, color spaces and gamma, constant values."""
import dataclasses
import math

from ...reader import pblock
from .. import colors, params
from ..params import finite as _finite
from .ids import (
    _AS_STORED, _BASE_KINDS, _RGB_KINDS, BLEND_ADD, BLEND_BURN, BLEND_DIFFERENCE, BLEND_DIVIDE, BLEND_DODGE,
    BLEND_EXCLUSION, BLEND_HARD_LIGHT, BLEND_LINEAR_BURN, BLEND_LINEAR_LIGHT, BLEND_MAX, BLEND_MIN, BLEND_OVERLAY,
    BLEND_SCREEN, BLEND_SUBTRACT, COLOR, CORONA_KELVIN, FLOAT_IMAGES, GAMMA_TOLERANCE, LINEAR, MASK, MAX_MULTIPLIER,
    NON_COLOR, SRGB, SRGB_GAMMA, SRGB_TWICE, STORED_RGB,
)
from .ir import Adjust, Constant, Decode, Mix, Tint


def _num(m, pid, default):
    return params.num(m, pid, 0, default)


def _flag(m, pid, default):
    return params.flag(m, pid, 0, default)


def _vec(m, pid, default):
    """A point3 parameter as a tuple of floats, default when it is unusable."""
    v = m.param(pid, 0)
    n = len(default)
    if isinstance(v, tuple) and len(v) >= n and all(_finite(c) for c in v[:n]):
        return tuple(float(c) for c in v[:n])
    return default


def kelvin_rgb(kelvin):
    """A color temperature as an sRGB swatch (0..1): the curve fit of the rules source, 1000 K to 40000 K."""
    t = min(40000.0, max(1000.0, kelvin)) / 100.0
    r = 255.0 if t <= 66.0 else 329.698727446 * (t - 60.0) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66.0 else 288.1221695283 * (t - 60.0) ** -0.0755148492
    b = 255.0 if t >= 66.0 else 0.0 if t <= 19.0 else 138.5177312231 * math.log(t - 10.0) - 305.0447927307
    return tuple(min(255.0, max(0.0, c)) / 255.0 for c in (r, g, b))


def corona_kelvin(kelvin):
    """Corona's color of a temperature, linear RGB 0..1: CORONA_KELVIN, clamped to its 1000 K to 40000 K."""
    pts = CORONA_KELVIN
    k = min(float(pts[-1][0]), max(float(pts[0][0]), kelvin))
    for (k0, c0), (k1, c1) in zip(pts, pts[1:]):
        if k <= k1:
            t = (k - k0) / (k1 - k0)
            return tuple((a + (b - a) * t) / 255.0 for a, b in zip(c0, c1))
    return tuple(c / 255.0 for c in pts[-1][1])


def _overlay(x, y):
    return 2.0 * x * y if x < 0.5 else 1.0 - 2.0 * (1.0 - x) * (1.0 - y)


def blend_value(op, a, b, gamma=1.0):
    """Blend's result for two constants (linear RGB tuples or floats), CoronaMix's formulas (Blend): with a gamma
    the magnitude of each input channel and of the result raised (renderMap, maxdrop-em3.161). Inputs held within
    +-MAX_MULTIPLIER (no overflow), the result before its gamma too."""
    def power(v, p):
        return abs(v) ** p

    def one(x, y):
        x, y = (min(MAX_MULTIPLIER, max(-MAX_MULTIPLIER, v)) for v in (x, y))
        if gamma != 1.0:
            x, y = power(x, 1.0 / gamma), power(y, 1.0 / gamma)
        r = {BLEND_ADD: lambda: x + y, BLEND_SUBTRACT: lambda: max(0.0, x - y),
             BLEND_DIVIDE: lambda: x / y if y != 0.0 else x, BLEND_MIN: lambda: min(x, y),
             BLEND_MAX: lambda: max(x, y), BLEND_DIFFERENCE: lambda: abs(x - y),
             BLEND_SCREEN: lambda: 1.0 - (1.0 - x) * (1.0 - y), BLEND_OVERLAY: lambda: _overlay(x, y),
             BLEND_HARD_LIGHT: lambda: _overlay(y, x),
             BLEND_DODGE: lambda: 1.0 if y == 1.0 else min(1.0, x / (1.0 - y)),
             BLEND_BURN: lambda: 0.0 if y == 0.0 else max(0.0, 1.0 - (1.0 - x) / y),
             BLEND_LINEAR_BURN: lambda: max(0.0, x + y - 1.0), BLEND_LINEAR_LIGHT: lambda: x + 2.0 * y - 1.0,
             BLEND_EXCLUSION: lambda: x + y - 2.0 * x * y}[op]()
        r = min(MAX_MULTIPLIER, max(-MAX_MULTIPLIER, r))
        return abs(r) ** gamma if gamma != 1.0 else r
    if isinstance(a, tuple):
        return tuple(one(x, y) for x, y in zip(a, b))
    return one(a, b)


def _ref(m, pid, tab=0):
    """The object index of a reference parameter, None when it is empty or not a reference."""
    v = m.param(pid, 0, tab=tab)
    return v.index if isinstance(v, pblock.Reference) else None


def rgb_kind(kind):
    """The kind of a color wrapper's input below a map of that kind: DATA_RGB in a data graph, BUMP_RGB in a height,
    the kind itself elsewhere (a color, a normal, a mask: see _wrapper_input for a Tint's or Output's in a mask)."""
    return _RGB_KINDS.get(kind, kind)


def base_kind(kind):
    """The kind an image or a normal map class below takes: DATA for DATA_RGB, BUMP for BUMP_RGB."""
    return _BASE_KINDS.get(kind, kind)


def _linear(rgb, kind):
    """A color as the renderer holds it (not a swatch) as a Constant of the input's kind: its channels in a color
    input and where a swatch keeps its channels (STORED_RGB: in STORED the Decode above shows it decoded, as a
    gamma-off color root does CoronaColor's HDR color, maxdrop-em3.165), else their mean."""
    return Constant(tuple(rgb) if kind == COLOR or kind in STORED_RGB else sum(rgb) / 3.0)


def colorspace(kind, gamma, stored=False):
    """The color space of an image in an input of that kind read with that gamma (None: automatic, sRGB); stored:
    the map reads its pixels as stored in this scene (a Bitmap, or a VRayBitmap From 3ds Max, with the gamma off),
    which a data, normal or bump input takes as they are. A normal or bump input takes an image as a data input does
    (V-Ray 5.2 and Corona 12 renders, maxdrop-em3.159). An image read as linear (gamma 1.0) on any but a color input
    is Non-Color too: the same numbers, and one Blender image for the file's data, normal and bump uses."""
    if kind in _AS_STORED and stored:
        return NON_COLOR
    if kind in _AS_STORED + (MASK,) and gamma is not None and abs(gamma - 1.0) <= GAMMA_TOLERANCE:
        return NON_COLOR
    if gamma is None or abs(gamma - SRGB_GAMMA) <= GAMMA_TOLERANCE:
        return SRGB
    return LINEAR


def _auto_gamma(gamma, name):
    """A Bitmap's or CoronaBitmap's gamma: automatic (None) reads a float file (EXR, HDR) as linear, as 3ds Max and
    Corona do; an override is kept."""
    return 1.0 if gamma is None and name.lower().endswith(FLOAT_IMAGES) else gamma


def _shown(gamma):
    """The gamma Blender reads an image with when a gamma-off scene shows the map's own decode (gamma: linear =
    pixel ^ gamma; None: the sRGB curve) decoded once more, as V-Ray 5.2 shows a VRayBitmap and a float file there
    (maxdrop-em3.123) and Corona 12 a CoronaBitmap (maxdrop-em3.165): 2.2 x its own (2.2 itself: sRGB, exact),
    SRGB_TWICE for the sRGB curve."""
    return SRGB_TWICE if gamma is None else gamma * SRGB_GAMMA


def _stored_mask(image, kind, stored):
    """An image read as stored (a Bitmap, a VRayBitmap From 3ds Max, with the gamma off) as a mask in a color graph:
    V-Ray mixes by the mean of the stored pixel, which the display-referred scene shows decoded (maxdrop-6n0.6.36,
    measured in maxdrop-6n0.6.2: a (200, 100, 50) PNG renders 0.4575, shown 0.1768; the mean of the decoded channels
    is 0.2456), so the image as stored (Non-Color) under a Decode of its mean through the exact sRGB curve, which
    leaves a grey as the sRGB image gave it. An image whose mono output is its alpha stays as it is: Blender never
    decodes an alpha (not measured)."""
    if kind != MASK or not stored or image.alpha:
        return image
    return Decode(dataclasses.replace(image, colorspace=NON_COLOR), mean=True)


def unshown(image):
    """A Bitmap's, VRayBitmap's or CoronaBitmap's color Image made in a gamma-off scene with its own decode again
    (_shown undone; None, an image read as stored, gives linear): for a float file lighting a scene, where the display
    decode of a sun's values far above 1 lights it orders of magnitude too bright (convert.lights.dome_texture;
    measured in maxdrop-em3.166 with V-Ray; a CoronaBitmap's alike, maxdrop-em3.165)."""
    g = image.gamma
    own = 1.0 if g is None else (None if abs(g - SRGB_TWICE) <= GAMMA_TOLERANCE else g / SRGB_GAMMA)
    return dataclasses.replace(image, gamma=own, colorspace=colorspace(COLOR, own))


def drawn_gamma(image):
    """The power a builder applies after an Image's texture, None for none: its gamma when the image is Linear
    Rec.709 for it (any other gamma is its color space's, or 1.0)."""
    g = image.gamma
    if g is not None and abs(g - 1.0) > 1e-6 and image.colorspace == LINEAR == colorspace(COLOR, g):
        return g
    return None


def _constant_value(node):
    """The RGB value of a Constant, of a Mix of Constants by its amount or a Constant mask, or of a Tint or an Adjust
    over a Constant (the builder's math); None otherwise."""
    if isinstance(node, Constant):
        return _rgb3(node.value)
    if isinstance(node, Tint) and isinstance(node.input, Constant):
        c, rows = _rgb3(node.input.value), (node.red, node.green, node.blue)
        return tuple(sum(c[k] * rows[k][i] for k in range(3)) for i in range(3))
    if isinstance(node, Adjust) and isinstance(node.input, Constant):
        o = node.output
        return tuple(o.amount * (o.level * (1.0 - c) - o.offset if o.invert else o.level * c + o.offset)
                     for c in _rgb3(node.input.value))
    if not (isinstance(node, Mix) and isinstance(node.a, Constant) and isinstance(node.b, Constant)
            and (node.mask is None or isinstance(node.mask, Constant))):
        return None
    f = min(1.0, max(0.0, node.factor if node.mask is None else sum(_rgb3(node.mask.value)) / 3.0))  # as a Mix node
    return tuple(a + (b - a) * f for a, b in zip(_rgb3(node.a.value), _rgb3(node.b.value)))


def _rgb3(v):
    return tuple(v[:3]) if isinstance(v, tuple) else (v,) * 3


def _stored_value(value):
    """A gamma-off input's own value (linear: a swatch made so by the sRGB curve) as the renderer holds it, RGB."""
    return tuple(colors.linear_to_srgb(c) for c in _rgb3(value))
