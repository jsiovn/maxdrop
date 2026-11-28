# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The texture-graph IR (the node dataclasses) and its walkers."""
import collections
import dataclasses

from .ids import EXPLICIT, NORMAL_BLEND, PERPENDICULAR, REWIRE_NONE, SRGB


@dataclasses.dataclass(frozen=True)
class Mapping:
    """How a Bitmap is laid on the surface. angle: U, V, W in radians; axis 0 UV, 1 VW, 2 WU; source EXPLICIT (the
    map channel), OBJECT_XYZ, VERTEX_COLOR (channel 0) or WORLD_XYZ."""
    channel: int = 1
    tiling: tuple = (1.0, 1.0)
    offset: tuple = (0.0, 0.0)
    angle: tuple = (0.0, 0.0, 0.0)
    tile: tuple = (True, True)
    mirror: tuple = (False, False)
    axis: int = 0
    source: int = EXPLICIT
    environment: bool = False
    real_world: bool = False
    blur: float = 1.0


@dataclasses.dataclass(frozen=True)
class Crop:
    """The part of the image used (u, v from the top left, width, height, 0..1): cropped, or placed (place: the
    whole image shrunk into that rectangle)."""
    u: float
    v: float
    w: float
    h: float
    place: bool = False


@dataclasses.dataclass(frozen=True)
class TexOutput:
    """A map's Output: level times the color plus offset (inverted: level times (1 - color) minus offset, measured),
    then times amount."""
    invert: bool = False
    amount: float = 1.0
    level: float = 1.0
    offset: float = 0.0


@dataclasses.dataclass(frozen=True)
class Image:
    """An image map (Bitmap, CoronaBitmap, VRayBitmap). path / resolved: as the scene stores them (resolved:
    FileAssetMetaData3's); found: the textures.Found of the lookup, None without a lookup or when the file was not
    found; gamma: the gamma 3ds Max reads it with in this scene (linear = pixel ^ gamma: its override, or the file
    input gamma), None for automatic (sRGB; 1.0 for an EXR or HDR file); with the gamma off on a color input or a
    mask the one the display-referred scene shows it with (None, sRGB, for an image read as stored; _shown, a
    CoronaBitmap's too); 1.0 for a VRayBitmap below a normal map (read as stored), its
    decode over 2.2 below a CoronaNormal that adds gamma (_add_gamma); alpha: the image's alpha is used, not its
    color."""
    index: int
    name: str
    path: str = ""
    resolved: str = ""
    found: object = None
    mapping: Mapping = Mapping()
    crop: object = None
    output: object = None
    colorspace: str = SRGB
    gamma: object = None
    alpha: bool = False


@dataclasses.dataclass(frozen=True)
class Constant:
    """A swatch: linear RGB in a color input, a float elsewhere."""
    value: object


@dataclasses.dataclass(frozen=True)
class Invert:
    input: object


@dataclasses.dataclass(frozen=True)
class Decode:
    """A gamma-off scene's display-referred color (a graph of kind STORED) as linear, what the display shows of it:
    the sRGB curve, drawn as a power of SRGB_GAMMA (a constant folded exactly). mean: the mean of the input's channels
    through the exact sRGB curve, a float (an image read as stored as a gamma-off mask: _stored_mask)."""
    input: object
    mean: bool = False


@dataclasses.dataclass(frozen=True)
class Mix:
    """a where factor (or the mask) is 0, b where it is 1."""
    a: object
    b: object
    factor: float = 0.5
    mask: object = None


@dataclasses.dataclass(frozen=True)
class Multiply:
    a: object
    b: object


@dataclasses.dataclass(frozen=True)
class Blend:
    """op (BLEND_OPS) per channel on |a|^(1 / gamma) and |b|^(1 / gamma), the magnitude of the result raised to gamma:
    add a + b, subtract a - b floored at 0, divide a / b (a where b is 0, as Blender divides), min, max, difference
    |a - b|, screen 1 - (1 - a)(1 - b), overlay 2ab where a < 0.5 else 1 - 2(1 - a)(1 - b), hard light overlay(b, a),
    dodge a / (1 - b) at most 1 (1 where b is 1), burn 1 - (1 - a) / b at least 0 (0 where b is 0), linear burn
    a + b - 1 at least 0, linear light a + 2b - 1, exclusion a + b - 2ab. Not clamped otherwise (CoronaMix's
    formulas, drawn as they are: maxdrop-em3.161). A CoronaMix in sRGB mode is gamma 2.2 (the magnitudes of a
    negative layer, as Corona takes them: renderMap, maxdrop-em3.161)."""
    op: str
    a: object
    b: object
    gamma: float = 1.0


@dataclasses.dataclass(frozen=True)
class ColorCorrect:
    """rewire: the source of the red, green and blue outputs (REWIRE_NONE: unchanged; codes as CC_REWIRE's), applied
    first; hue: shift in turns; saturation: factor (1 = unchanged); brightness, contrast: added fractions; gain:
    factor; gamma: the advanced mode's (1 = none); magnitude: the gamma takes each channel's magnitude, so a negative
    one comes out positive (a CoronaMix gamma in sRGB mode, maxdrop-6n0.6.40), else a channel at or below 0 stays."""
    input: object
    rewire: tuple = REWIRE_NONE
    hue: float = 0.0
    saturation: float = 1.0
    brightness: float = 0.0
    contrast: float = 0.0
    gain: float = 1.0
    gamma: float = 1.0
    magnitude: bool = False


@dataclasses.dataclass(frozen=True)
class CompositeLayer:
    """A Composite layer: its node, opacity 0..1, blend mode (BLENDS) and mask (a data node, None: none). The result
    is lerp(below, blend(below, node), opacity x mask); the bottom layer is over black whatever its mode."""
    node: object
    opacity: float = 1.0
    blend: int = NORMAL_BLEND
    mask: object = None


@dataclasses.dataclass(frozen=True)
class Composite:
    """layers: CompositeLayers, bottom first."""
    layers: tuple


@dataclasses.dataclass(frozen=True)
class Facing:
    """A Falloff's ratio, 0 facing the viewer and 1 at grazing (PERPENDICULAR: 1 - |N.V|), away from it (TOWARDS:
    (1 - N.V) / 2), or the dielectric Fresnel reflectance of ior (FRESNEL)."""
    mode: str = PERPENDICULAR
    ior: float = 1.6


@dataclasses.dataclass(frozen=True)
class Checker:
    """A Checker map's pattern, a float: 0 on the squares of its color 1, 1 on those of color 2 (checker_value), on
    the UV its Mapping places; soften as stored (drawn as 0). A leaf: the Mix above it holds the two sides."""
    mapping: Mapping = Mapping()
    soften: float = 0.0


@dataclasses.dataclass(frozen=True)
class Remap:
    """A float input through a curve: points, (x, y) pairs with x ascending, joined by straight lines and flat past
    the ends (a Falloff's mix curve, curve_samples; flat is assumed, a Falloff's ratio stays within 0..1). Its result
    is not clamped."""
    input: object
    points: tuple


@dataclasses.dataclass(frozen=True)
class Smoothstep:
    """Mix's Use Curve on a float input (mix_factor): 0 below lower, 1 from upper, smoothstep between; a step at
    lower when lower >= upper."""
    input: object
    lower: float = 0.3
    upper: float = 0.7


@dataclasses.dataclass(frozen=True)
class Adjust:
    """A wrapper's Output (TexOutput) over its input."""
    input: object
    output: TexOutput


@dataclasses.dataclass(frozen=True)
class Tint:
    """RGB Tint: input R x red + G x green + B x blue, each a linear RGB."""
    input: object
    red: tuple = (1.0, 0.0, 0.0)
    green: tuple = (0.0, 1.0, 0.0)
    blue: tuple = (0.0, 0.0, 1.0)


@dataclasses.dataclass(frozen=True)
class Bump:
    """A height input and its strength."""
    input: object
    strength: float = 1.0


@dataclasses.dataclass(frozen=True)
class NormalMap:
    """A tangent-space normal image, its strength, its channel flips, the map channel of its tangents and an
    additional Bump (or None)."""
    input: object
    strength: float = 1.0
    flip_red: bool = False
    flip_green: bool = False
    swap: bool = False
    bump: object = None
    channel: int = 1


@dataclasses.dataclass(frozen=True)
class TextureGraphIR:
    """What drives one input: root node, the input's kind, approximated (a map was peeled below a class whose own
    effect is lost), and the issues met on the way, each once. Shared by every material using the same slot."""
    root: object
    kind: str
    approximated: bool = False
    issues: tuple = ()


class TexmapStats:
    """peeled {class name: map objects peeled}, unsupported {class name: map objects without a usable map below},
    approximated {class name: procedural map objects drawn with Blender's own pattern}, issues [(object index,
    reason)]."""
    __slots__ = ("peeled", "unsupported", "approximated", "issues")

    def __init__(self):
        self.peeled, self.unsupported, self.issues = collections.Counter(), collections.Counter(), []
        self.approximated = collections.Counter()


class _Walk:
    """The state of one map's conversion: approximated and the issues of its subtree."""
    __slots__ = ("approximated", "issues")

    def __init__(self):
        self.approximated, self.issues = False, []

    def merge(self, approximated, issues):
        self.approximated = self.approximated or approximated
        self.issues.extend(r for r in issues if r not in self.issues)


def _children(node):
    if isinstance(node, (Invert, Decode, Bump, ColorCorrect, Adjust, Tint, Remap, Smoothstep)):
        return (node.input,)
    if isinstance(node, Mix):
        return tuple(n for n in (node.a, node.b, node.mask) if n is not None)
    if isinstance(node, (Multiply, Blend)):
        return (node.a, node.b)
    if isinstance(node, Composite):
        return tuple(n for layer in node.layers for n in (layer.node, layer.mask) if n is not None)
    if isinstance(node, NormalMap):
        return (node.input,) if node.bump is None else (node.input, node.bump)
    return ()


def _has_decode(node):
    """Whether a graph has a Decode node (a DAG walked once per node)."""
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        if id(n) not in seen:
            seen.add(id(n))
            if isinstance(n, Decode):
                return True
            stack.extend(_children(n))
    return False


def tree_size(node):
    """The number of nodes of a graph drawn as a tree (a shared node counted at each use), in linear time."""
    sizes = {}

    def size(n):
        k = id(n)
        if k not in sizes:
            sizes[k] = 1 + sum(size(c) for c in _children(n))
        return sizes[k]
    return size(node)


def first_image(node):
    """The first Image of a graph, depth first, None without one."""
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        if isinstance(n, Image):
            return n
        stack.extend(reversed(_children(n)))
    return None
