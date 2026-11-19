# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Texture-map rules: the map that drives a material input, turned into a small renderer-neutral graph.

    tex = TexmapConverter(graph, assets, textures=index, swatches=sw)   # MaterialGraph, AssetTable, optional
                                        # TextureIndex, colors.Swatches (default: read from graph's scene)
    g = tex.convert(map_ref, kind, value)   # TextureGraphIR, None when nothing usable drives the input
    g.root, g.kind, g.approximated, g.issues
    graphs = texture_graphs(ir, tex)        # {MaterialIR input name: TextureGraphIR}
    tex.stats.peeled, tex.stats.unsupported, tex.stats.issues

kind says what the input is: COLOR (base color, specular and transmission, which V-Ray and Standard drive with the
reflection and refraction colors, emission), DATA (roughness, metallic, opacity), NORMAL or BUMP. It sets the color
space of every image below: sRGB for COLOR, Non-Color for the others (a Mix mask is always Non-Color). A Bitmap's
gamma override (None: automatic, the default; 1.0 for an EXR or HDR file) is kept on its Image: on a color input, an
override of 2.2 is sRGB, any other is Linear Rec.709 (sRGB primaries: Blender converts them into the scene's working
space; the builder falls back to Non-Color where the color space is missing) and the builder applies the override as
a gamma (1.0: none); on the other inputs an image is data and the override is not applied. Constants are linear, a
swatch made so by the scene's swatch rule (convert/colors.py: linear with the gamma on, the sRGB curve with it off):
in a COLOR graph always linear RGB (also when the input itself is a float, as specular and transmission are: the
builder takes the mean of the graph's color there, the measure materials.py uses), elsewhere a float, the mean of the
linear color.

The graph's nodes (frozen dataclasses): Image (an image map: the file as the scene stores it, the one the texture lookup
found, Mapping, Crop, TexOutput, color space, gamma, alpha), Constant, Invert, Mix(a, b, factor, mask), Multiply,
ColorCorrect, Composite (layers bottom first, each with its opacity), NormalMap (an image, its strength, flips, the
map channel of its tangents, an additional Bump) and Bump (a height input and its strength). A map reached by
several paths is converted once per kind and depth, so a graph is a DAG of shared nodes; a graph larger than
MAX_NODES when drawn as a tree is cut down to its first image (an issue).

Rules, by ClassID (the decisions of an earlier 3ds Max -> FBX exporter, made native: node graphs instead of baked
files, the map angle kept, a height map in a bump slot a Bump node instead of dropped):

- Bitmap -> Image. Its Placement: tiling, offset, U / V / W angles, tile and mirror per axis, the map channel (the
  vertex color channel is channel 0), the axis (UV, VW, WU) and the coordinate source; environment mapping and the
  object or world XYZ sources are described and named as an issue (no UVs drive them), real-world scale too (its
  tiling is in scene units). Cropping or placement when applied and not the whole image; the Output (invert,
  amount, RGB level and offset) when it changes anything; alpha when the Bitmap gives its alpha to a mono input
  (mono output Alpha) or as its color (RGB output Alpha). A Bitmap without a file is no image (an issue).
- CoronaBitmap -> Image the same way, from its own parameters: UVW scale and offset, W angle, tiling (none, repeat,
  mirror) per axis, map channel, blur, clipping (crop or place), gamma (-1 automatic, as a Bitmap's), mono / RGB
  output alpha, real-world scale (an issue); its Output part as a Bitmap's.
- VRayBitmap (VRayHDRI before V-Ray 5: the same class) -> Image the same way: its Placement and Output parts as a
  Bitmap's, its own crop / place and mono / RGB output alpha; its transfer function as the gamma (none: 1.0, inverse
  gamma g: 1 / g, sRGB: automatic, from 3ds Max and auto: automatic, linear for an EXR or HDR file), its overall
  times render multiplier times the Output's amount (the order against the Output's invert and offset is assumed,
  not measured). An environment mapping type (angular, cubic, spherical, mirrored ball), a map source, ACEScg
  primaries, RGB output intensity, an unusable transfer function or multiplier are issues.
- CoronaColor -> Constant (color and hex as swatches, the HDR color linear, the temperature through kelvin_rgb and
  the sRGB curve, times the multiplier). VRayColor -> Constant: its swatch times its RGB multiplier, then to the
  power of its color gamma (that order measured), made linear as a swatch; in temperature mode its color holds
  V-Ray's temperature color. Its
  alpha below 1, RGB primaries other than sRGB and unusable values are issues. CoronaMix: operation mix ->
  Mix(bottom, top, amount, mask), multiply -> Multiply (under a Mix for an amount below 1 or a mask), any other
  operation peeled to its first bitmap (an issue); layer multipliers and offsets are an issue.
- Kept as nodes (the allow-list): Mix (color 1 / 2 where a map is off or missing, the mask, the mix amount; its
  curve is not converted: an issue), RGB Multiply, Color Correction (hue shift in turns, saturation as a factor;
  lightness either standard, brightness and contrast as fractions, or advanced, gain and gamma, whichever is chosen;
  rewiring, tint and the advanced pivot and lift are not converted: an issue) and a simple Composite (normal blend
  mode, no mask; any other is peeled).
- Peeled to the first usable map below, an approximation counted by class: Falloff (map 1 when on, else color 1),
  VRayDirt (the unoccluded map when on, else the unoccluded color), Output (map 1; its own Output's invert kept),
  RGB Tint (map 1), VRayColor2Bump (its map). An Output, RGB Tint or VRayColor2Bump without a map (or an Output or
  RGB Tint with it off; VRayColor2Bump has no switch) gives no graph and is an issue on it, counted nowhere: what
  3ds Max draws there is not measured, so nothing stands in for it (at the top the input keeps its own value). Any
  other map class with maps below gives the first image below it (depth first, in reference order), counted the
  same way; one without is unsupported (counted, no graph).
- Normal maps (VRayNormalMap, Normal Bump, CoronaNormal) in a normal or bump input -> NormalMap: the normal image
  with the class's multiplier as its strength, flip red / green and swap, and the additional bump map as a Bump with
  its multiplier; a normal map class with only its bump map is that Bump. In any other input it is peeled to its
  normal image (or its bump image).
- A map that is set (and switched on) but converts to nothing (an unsupported class with no bitmap below, a
  Bitmap without a file, an empty Output, RGB Tint or VRayColor2Bump, a cut branch) is an issue on its wrapper
  naming its class, and never stands in as the wrapper's own color for it (3ds Max uses that color only without a
  map or with the map off): a Color Correction, Falloff, VRayDirt, Output, RGB Tint or VRayColor2Bump over it gives
  no graph and is not counted (the lost map is reported), so the input keeps its own value.
  A Mix or CoronaMix weighs it by its amount: a side that does not show is drawn as its color (exact), a side that
  fills the result gives no graph, any other weight (or a mask) peels the wrapper to its other side's map, or no
  graph; an RGB Multiply is always peeled that way. A lost mask leaves the mix amount, a lost Composite layer is
  left out (both approximations); a normal map class keeps its other map.
- The slot itself: a glossiness map feeding roughness (MapRef.invert) is under an Invert; a slot amount below 1 mixes
  the input's value with the map (Mix(Constant(value), map, amount)), above 1 multiplies the map; in a bump input the
  amount is the Bump's strength, in a normal input it scales the NormalMap's strengths.

Each map object counts at most once in stats.peeled or stats.unsupported, each issue once in stats.issues. The file
comes from anywhere: a reference cycle, a chain deeper than MAX_DEPTH, a reference to an object that is not a map or
a damaged object end that branch (an issue), a shared map is converted once (no blow-up through repeated
references), and unreadable Placement, Output or BitmapInfo chunks take the defaults. Those chunks are read by
reader/materials.py (placement, output_invert, bitmap_gamma); what they hold is judged here. No bpy, no mathutils.
"""
import collections
import dataclasses
import math

from ..reader import chunks, classids, pblock
from ..reader import materials as reader_materials
from ..reader.classdir import ClassId
from . import colors, params
from .params import finite as _finite

ChunkError = chunks.ChunkError

COLOR, DATA, NORMAL, BUMP = "color", "data", "normal", "bump"
SRGB, NON_COLOR, LINEAR = "sRGB", "Non-Color", "Linear Rec.709"  # Blender color space names
EXPLICIT, OBJECT_XYZ, VERTEX_COLOR, WORLD_XYZ = (  # Placement coordinate source
    reader_materials.UV_EXPLICIT, reader_materials.UV_OBJECT_XYZ, reader_materials.UV_VERTEX_COLOR,
    reader_materials.UV_WORLD_XYZ)
MAX_DEPTH = 8
MAX_NODES = 256  # nodes of one graph drawn as a tree
SRGB_GAMMA, GAMMA_TOLERANCE = 2.2, 0.05

# ClassIDs (texmap superclass), aliased from reader/classids.py.
FALLOFF = classids.FALLOFF
VRAY_DIRT = classids.VRAY_DIRT
VRAY_COLOR2BUMP = classids.VRAY_COLOR2BUMP
OUTPUT = classids.OUTPUT_MAP
RGB_TINT = classids.RGB_TINT
MIX = classids.MIX
RGB_MULTIPLY = classids.RGB_MULTIPLY
COLOR_CORRECTION = classids.COLOR_CORRECTION
COMPOSITE = classids.COMPOSITE
NORMAL_BUMP = classids.NORMAL_BUMP
CORONA_NORMAL = classids.CORONA_NORMAL
IMAGES = (classids.BITMAP_TEX, classids.CORONA_BITMAP, classids.VRAY_BITMAP)  # map classes that are an image file

# normal map class -> parameter ids in block 0: normal map, its switch, multiplier, bump map, its switch, multiplier,
# flip red, flip green, swap red and green, the tangents' map channel (None: the class has no such parameter)
_NormalIds = collections.namedtuple("_NormalIds", "normal normal_on strength bump bump_on bump_strength flip_red "
                                                  "flip_green swap channel")
NORMAL_MAPS = {
    classids.VRAY_NORMAL_MAP: _NormalIds(0, 2, 3, 4, 5, 6, 7, 8, 9, 1),
    NORMAL_BUMP: _NormalIds(2, 4, 0, 3, 5, 1, 7, 8, 9, None),
    CORONA_NORMAL: _NormalIds(500, None, 501, 507, 509, 508, 503, 504, 505, None),
}
NORMAL_BUMP_METHOD, CORONA_ADD_GAMMA = 6, 502

# CoronaBitmap, block 0: tiling 0 none, 1 repeat, 2 mirror; wAngle in radians. uAngle (130) is the U offset times
# 2 pi (Corona keeps the two in step, for an environment map's turn): not read
CB_FILE, CB_CHANNEL, CB_SCALE, CB_OFFSET, CB_BLUR, CB_TILE_U, CB_TILE_V, CB_REAL_WORLD = (
    101, 103, 105, 106, 107, 108, 109, 114)
CB_MONO, CB_RGB, CB_CLIP_ON, CB_CLIP_MODE, CB_CLIP_U, CB_CLIP_V, CB_CLIP_W, CB_CLIP_H = (
    117, 118, 119, 120, 121, 122, 123, 124)
CB_GAMMA, CB_W_ANGLE = 125, 129
CB_NO_TILE, CB_MIRROR = 0, 2
# VRayBitmap (VRayHDRI), block 0 (rgbColorSpace: block 3); its Placement is a standard UVGen, read as a Bitmap's.
# mapType 4 is 3ds Max standard mapping (the UVGen), 0 to 3 environment projections; its own mapChannel (7) only
# serves those: the UVGen's channel is the one used
VB_FILE, VB_MULT, VB_MAP_TYPE, VB_GAMMA, VB_RENDER_MULT = 0, 1, 2, 8, 9
VB_CROP_ON, VB_CROP_MODE, VB_CROP_U, VB_CROP_V, VB_CROP_W, VB_CROP_H = 16, 17, 18, 19, 20, 21
VB_RGB, VB_MONO, VB_COLOR_SPACE, VB_SOURCE, VB_SOURCE_ON, VB_RGB_SPACE, VB_RGB_SPACE_BLOCK = (
    22, 23, 25, 38, 39, 41, 3)
VB_STANDARD, VB_INTENSITY, VB_ACESCG = 4, 2, 2
# color_space (transfer function), measured with renderMap: 0 none (linear), 1 inverse gamma (pixel ^ (1 / gamma)),
# 2 sRGB, 3 from 3ds Max (the input gamma, as a Bitmap's automatic), 4 auto (sRGB for an 8-bit file, the default)
VB_LINEAR, VB_INVERSE_GAMMA, VB_SRGB, VB_AUTOMATIC = 0, 1, 2, (2, 3, 4)
FLOAT_IMAGES = (".exr", ".hdr")  # files an automatic gamma (Bitmap, CoronaBitmap, VRayBitmap auto) reads as linear
MAX_MULTIPLIER = 1e6
# image class -> (class name in issues, its file parameter in block 0); any other image class is a Bitmap
_IMAGE_FILES = {classids.CORONA_BITMAP: ("CoronaBitmap", CB_FILE), classids.VRAY_BITMAP: ("VRayBitmap", VB_FILE)}
# CoronaColor, block 0: method 0 color, 1 HDR color (linear), 2 temperature, 3 hex
CC_METHOD, CC_TEMPERATURE, CC_COLOR, CC_MULTIPLIER, CC_HDR, CC_HEX = 50, 51, 52, 57, 58, 59
# VRayColor, block 0: color_mode 0 RGB, 1 temperature (V-Ray writes the temperature's color into color, measured);
# red / green / blue are color again; rgb_primaries 0 sRGB. Block 1 (gamma_correction, gamma_value) is transient
VC_RED, VC_GREEN, VC_BLUE, VC_ALPHA, VC_MULTIPLIER, VC_COLOR, VC_MODE, VC_GAMMA, VC_PRIMARIES = (
    0, 1, 2, 3, 4, 5, 9, 10, 11)
# CoronaMix, block 0: result = mix(bottom, operation(bottom, top), amount), the mask map replacing the amount
CM_OPERATION, CM_AMOUNT, CM_MULT_TOP, CM_MULT_BOTTOM, CM_OFFSET_TOP, CM_OFFSET_BOTTOM = 200, 201, 202, 203, 204, 205
CM_MAP_TOP, CM_MAP_BOTTOM, CM_COLOR_TOP, CM_COLOR_BOTTOM, CM_MASK, CM_MASK_ON, CM_TOP_ON, CM_BOTTOM_ON = (
    206, 207, 208, 209, 210, 211, 212, 213)
CM_MULTIPLY, CM_MIX = 2, 6

# Bitmap, block 0
BM_CLIP_U, BM_CLIP_V, BM_CLIP_W, BM_CLIP_H, BM_APPLY, BM_CROP_PLACE, BM_MONO, BM_RGB, BM_FILE = (
    0, 1, 2, 3, 6, 7, 9, 10, 13)
# Placement (UVGen) old ParamBlock indices (its chunks: reader_materials.placement)
UV_U_OFFSET, UV_V_OFFSET, UV_U_TILING, UV_V_TILING, UV_U_ANGLE, UV_V_ANGLE, UV_W_ANGLE, UV_BLUR = range(8)
# Output (TexOutput) old ParamBlock indices (its flags: reader_materials.output_invert)
OUT_LEVEL, OUT_OFFSET, OUT_AMOUNT = 0, 1, 2


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
    """A map's Output: the color is inverted, then times level plus offset, then times amount."""
    invert: bool = False
    amount: float = 1.0
    level: float = 1.0
    offset: float = 0.0


@dataclasses.dataclass(frozen=True)
class Image:
    """An image map (Bitmap, CoronaBitmap, VRayBitmap). path / resolved: as the scene stores them (resolved:
    FileAssetMetaData3's); found: the textures.Found of the lookup, None without a lookup or when the file was not
    found; gamma: the override (linear = pixel ^ gamma), None for automatic (1.0 for an EXR or HDR file); alpha: the
    image's alpha is used, not its color."""
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
class ColorCorrect:
    """hue: shift in turns; saturation: factor (1 = unchanged); brightness, contrast: added fractions; gain: factor;
    gamma: the advanced mode's (1 = none)."""
    input: object
    hue: float = 0.0
    saturation: float = 1.0
    brightness: float = 0.0
    contrast: float = 0.0
    gain: float = 1.0
    gamma: float = 1.0


@dataclasses.dataclass(frozen=True)
class Composite:
    """layers: ((node, opacity 0..1), ...), bottom first, each over the ones below in the normal blend mode."""
    layers: tuple


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
    issues [(object index, reason)]."""
    __slots__ = ("peeled", "unsupported", "issues")

    def __init__(self):
        self.peeled, self.unsupported, self.issues = collections.Counter(), collections.Counter(), []


class _Walk:
    """The state of one map's conversion: approximated and the issues of its subtree."""
    __slots__ = ("approximated", "issues")

    def __init__(self):
        self.approximated, self.issues = False, []

    def merge(self, approximated, issues):
        self.approximated = self.approximated or approximated
        self.issues.extend(r for r in issues if r not in self.issues)


def _children(node):
    if isinstance(node, (Invert, Bump, ColorCorrect)):
        return (node.input,)
    if isinstance(node, Mix):
        return tuple(n for n in (node.a, node.b, node.mask) if n is not None)
    if isinstance(node, Multiply):
        return (node.a, node.b)
    if isinstance(node, Composite):
        return tuple(n for n, _o in node.layers)
    if isinstance(node, NormalMap):
        return (node.input,) if node.bump is None else (node.input, node.bump)
    return ()


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


def _ref(m, pid, tab=0):
    """The object index of a reference parameter, None when it is empty or not a reference."""
    v = m.param(pid, 0, tab=tab)
    return v.index if isinstance(v, pblock.Reference) else None


def _old(part, index, default):
    """A value of a part's old ParamBlock (slot order: the first one)."""
    if part is None or not part.legacy:
        return default
    v = part.legacy[min(part.legacy)].get(index)
    return float(v) if _finite(v) else default


def colorspace(kind, gamma):
    """The color space of an image in an input of that kind with that gamma override (None: automatic)."""
    if kind != COLOR:
        return NON_COLOR
    if gamma is None or abs(gamma - SRGB_GAMMA) <= GAMMA_TOLERANCE:
        return SRGB
    return LINEAR


def _auto_gamma(gamma, name):
    """A Bitmap's or CoronaBitmap's gamma: automatic (None) reads a float file (EXR, HDR) as linear, as 3ds Max and
    Corona do; an override is kept."""
    return 1.0 if gamma is None and name.lower().endswith(FLOAT_IMAGES) else gamma


class TexmapConverter:
    """Converts the maps of one MaterialGraph; assets: the scene's reader.assets.AssetTable (None: no file is
    known); textures: a convert.textures.TextureIndex to look each file up (None: no lookup); swatches: the
    colors.Swatches rule of the scene (None: read from graph's scene)."""

    def __init__(self, graph, assets=None, textures=None, swatches=None):
        self.graph, self.assets, self.textures = graph, assets, textures
        self.swatches = swatches if swatches is not None else colors.of_graph(graph)
        self.stats = TexmapStats()
        self._counted, self._done, self._reported = set(), {}, set()
        self._nodes, self._firsts = {}, {}  # keyed (object, kind, depth)

    def _issue(self, walk, index, reason):
        if (index, reason) not in self._reported:
            self._reported.add((index, reason))
            self.stats.issues.append((index, reason))
        if reason not in walk.issues:
            walk.issues.append(reason)

    def _class_name(self, m):
        try:
            entry = self.graph.scene.entry(m.index)
        except IndexError:
            entry = None
        return (entry.name if entry is not None else "") or classids.name_of(m.superclass, m.class_id) or \
            "ClassID%s" % (ClassId(*m.class_id),)

    def _count(self, counter, m):
        if m.index not in self._counted:
            self._counted.add(m.index)
            counter[self._class_name(m)] += 1

    def convert(self, ref, kind, value=None):
        """The TextureGraphIR of a materials.MapRef in an input of that kind whose own value is value; None when no
        usable map drives it."""
        key = (ref, kind, value)
        if key in self._done:
            return self._done[key]
        walk = _Walk()
        root = self._node(ref.index, kind, walk, 0, ())
        out = None
        if root is not None:
            root = self._slot(root, ref, kind, value, walk)
            if tree_size(root) > MAX_NODES:
                image = first_image(root)
                self._issue(walk, ref.index, "map %d: graph of more than %d nodes cut down to its first image"
                            % (ref.index, MAX_NODES))
                walk.approximated = True
                root = self._slot(image, ref, kind, value, walk) if image is not None else None
            if root is not None:
                out = TextureGraphIR(root, kind, walk.approximated, tuple(walk.issues))
        self._done[key] = out
        return out

    def _slot(self, root, ref, kind, value, walk):
        amount = ref.amount
        if ref.invert:
            root = Invert(root)
        if kind == BUMP:
            if isinstance(root, NormalMap):
                return _scaled(root, amount)
            if isinstance(root, Bump):
                return Bump(root.input, root.strength * amount)
            return Bump(root, amount)
        if kind == NORMAL:
            if isinstance(root, NormalMap):
                return _scaled(root, amount)
            if isinstance(root, Bump):
                return Bump(root.input, root.strength * amount)
            return NormalMap(root, amount)
        if kind == COLOR and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = (float(value),) * 3  # a color graph is RGB throughout, also on a float input
        if amount < 1.0 and value is not None:
            return Mix(Constant(value), root, amount)
        if amount > 1.0:
            return Multiply(root, Constant(amount if kind != COLOR else (amount,) * 3))
        return root

    def _get(self, i, walk, depth, chain):
        """The MtlBase of map object i, None (an issue) when the branch ends there."""
        if depth > MAX_DEPTH:
            self._issue(walk, i, "maps deeper than %d below object %d" % (MAX_DEPTH, chain[0] if chain else i))
            return None
        if i in chain:
            self._issue(walk, i, "map cycle through object %d" % i)
            return None
        if self.graph.superclass(i) != classids.SC_TEXMAP:
            self._issue(walk, chain[-1] if chain else i, "object %d is not a map" % i)
            return None
        try:
            return self.graph.get(i)
        except ChunkError as e:
            self._issue(walk, i, "map %d: %s" % (i, e))
            return None

    def _node(self, i, kind, walk, depth, chain):
        """The node of map object i in an input of that kind, None when nothing usable is there. Converted once per
        (object, kind, depth): the same map reached again shares the node, its issues and its approximation."""
        # The key leaves out the chain, so a map met first through a cycle keeps the branch the cycle cut, also where
        # it is reached again without one: order-dependent, and only in a scene that has a cycle. Keying on the chain
        # (or not caching a cut) would make a shared map cost one conversion per path to it, not one in all
        # (test_shared_maps_do_not_blow_up).
        if i is None:
            return None
        key = (i, kind, depth)
        hit = self._nodes.get(key)
        if hit is None:
            sub = _Walk()
            node = self._convert_node(i, kind, sub, depth, chain)
            hit = self._nodes[key] = (node, sub.approximated, tuple(sub.issues))
        walk.merge(hit[1], hit[2])
        return hit[0]

    def _convert_node(self, i, kind, walk, depth, chain):
        m = self._get(i, walk, depth, chain)
        if m is None:
            return None
        key, chain, depth = ClassId(*m.class_id), chain + (i,), depth + 1
        if key in IMAGES:
            return self._image(m, kind, walk)
        if key in NORMAL_MAPS:
            return self._normal(m, NORMAL_MAPS[key], kind, walk, depth, chain)
        rule = _KEEP.get(key)
        if rule is not None:
            return rule(self, m, kind, walk, depth, chain)
        rule = _PEEL.get(key)
        if rule is not None:
            node = rule(self, m, kind, walk, depth, chain)
            if node is not None:
                walk.approximated = True
                self._count(self.stats.peeled, m)
            return node
        return self._peel_to_image(m, kind, walk, depth, chain, "no bitmap below")

    def _peel_to_image(self, m, kind, walk, depth, chain, why):
        """The first image below map m, counted as a peel; None (unsupported, an issue) without one."""
        image = self._first_image(m, kind, walk, depth, chain)
        if image is None:
            self._count(self.stats.unsupported, m)
            self._issue(walk, m.index, "%s %r: %s" % (self._class_name(m), m.name, why))
            return None
        walk.approximated = True
        self._count(self.stats.peeled, m)
        return image

    def _first_image(self, m, kind, walk, depth, chain):
        """The first image below map m, depth first in reference order, None without one; looked for once per
        (map, kind, depth), its issues replayed into every walk that finds it."""
        key = (m.index, kind, depth)
        if key not in self._firsts:
            self._firsts[key] = (None, False, ())  # a cycle back to here finds nothing
            sub = _Walk()
            image = self._first_image_walk(m, kind, sub, depth, chain)
            self._firsts[key] = (image, sub.approximated, tuple(sub.issues))
        image, approximated, issues = self._firsts[key]
        walk.merge(approximated, issues)
        return image

    def _first_image_walk(self, m, kind, walk, depth, chain):
        for c in m.children:
            if depth > MAX_DEPTH or c in chain or self.graph.superclass(c) != classids.SC_TEXMAP:
                continue
            try:
                sub = self.graph.get(c)
            except ChunkError:
                continue
            if ClassId(*sub.class_id) in IMAGES:
                image = self._image(sub, kind, walk)
                if image is not None:
                    return image
                continue
            image = self._first_image(sub, kind, walk, depth + 1, chain + (c,))
            if image is not None:
                return image
        return None

    def _constant(self, m, pid, kind, default):
        """A color parameter as a Constant of the input's kind."""
        v = m.param(pid, 0)
        rgb = v if isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3]) else default
        lin = self.swatches.color(rgb)
        return Constant(lin if kind == COLOR else sum(lin) / 3.0)

    def _on(self, m, map_pid, on_pid, tab=0):
        """The object index of the map a parameter uses: set and its switch (on_pid, None: none) on; else None."""
        if on_pid is not None and not _flag(m, on_pid, True):
            return None
        return _ref(m, map_pid, tab)

    def _lost(self, m, i, walk):
        """The issue of a map i that wrapper m uses and that converts to nothing, naming its class. None for an
        object that is no readable map: _get has named it already."""
        try:
            sub = self.graph.get(i) if self.graph.superclass(i) == classids.SC_TEXMAP else None
        except ChunkError:
            sub = None
        if sub is not None:
            self._issue(walk, m.index, "%s %r: its map %s %r converts to nothing" % (
                self._class_name(m), m.name, self._class_name(sub), sub.name))

    def _sub(self, m, map_pid, on_pid, kind, walk, depth, chain, tab=0):
        """The node of the map a parameter uses (see _on), None without one. A used map that converts to nothing is
        an issue on m: the caller never draws m's own color in its place."""
        i = self._on(m, map_pid, on_pid, tab)
        node = self._node(i, kind, walk, depth, chain)
        if i is not None and node is None:
            self._lost(m, i, walk)
        return node

    def _image(self, m, kind, walk):
        """The Image of a Bitmap, CoronaBitmap or VRayBitmap, None (an issue) without a file."""
        key = ClassId(*m.class_id)
        cls, pid = _IMAGE_FILES.get(key, ("Bitmap", BM_FILE))
        entry = self.assets.entry(m.param(pid, 0)) if self.assets is not None else None
        if entry is None:
            self._issue(walk, m.index, "%s %r: no file" % (cls, m.name))
            return None
        found = self.textures.find(entry.path, entry.resolved) if self.textures is not None else None
        out = next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_TEXOUTPUT), None)
        if key == classids.CORONA_BITMAP:
            return self._corona_image(m, kind, walk, entry, found, out)
        uv = next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_UVGEN), None)
        mapping = self._mapping(uv)
        if key == classids.VRAY_BITMAP:
            return self._vray_image(m, kind, walk, entry, found, out, mapping)
        self._placement_issues(m, walk, "Bitmap", mapping)
        crop = None
        clip = tuple(_num(m, pid, d) for pid, d in ((BM_CLIP_U, 0.0), (BM_CLIP_V, 0.0), (BM_CLIP_W, 1.0),
                                                     (BM_CLIP_H, 1.0)))
        if _flag(m, BM_APPLY, False) and clip != (0.0, 0.0, 1.0, 1.0):
            crop = Crop(*clip, place=m.param(BM_CROP_PLACE, 0) == 1)
        gamma = _auto_gamma(self._gamma(m), entry.name)
        alpha = m.param(BM_MONO if kind == DATA else BM_RGB, 0) == 1
        return Image(m.index, entry.name, entry.path, entry.resolved, found, mapping, crop, self._output(out),
                     colorspace(kind, gamma), gamma, alpha)

    def _placement_issues(self, m, walk, cls, mapping):
        """The issues of a UVGen's mapping that no UVs can draw."""
        if mapping.environment:
            self._issue(walk, m.index, "%s %r: environment mapping, drawn with the UVs" % (cls, m.name))
        elif mapping.source in (OBJECT_XYZ, WORLD_XYZ):
            self._issue(walk, m.index, "%s %r: planar %s XYZ mapping, drawn with the UVs" % (
                cls, m.name, "object" if mapping.source == OBJECT_XYZ else "world"))
        if mapping.real_world:
            self._issue(walk, m.index, "%s %r: real-world scale, its tiling in scene units not converted"
                        % (cls, m.name))

    def _vray_image(self, m, kind, walk, entry, found, out, mapping):
        """A VRayBitmap's Image: its Placement as a Bitmap's, its transfer function as a gamma (a Bitmap's
        meaning: linear = pixel ^ gamma), overall times render multiplier times its Output's amount (renderMap
        scales by the overall one; the render one applies when V-Ray renders)."""
        map_type = m.param(VB_MAP_TYPE, 0)
        if map_type not in (None, VB_STANDARD):
            mapping = dataclasses.replace(mapping, environment=True)
            self._issue(walk, m.index, "VRayBitmap %r: environment mapping (type %r), drawn with the UVs"
                        % (m.name, map_type))
        else:
            self._placement_issues(m, walk, "VRayBitmap", mapping)
        if _flag(m, VB_SOURCE_ON, True) and _ref(m, VB_SOURCE) is not None:
            self._issue(walk, m.index, "VRayBitmap %r: the placement of its map source not converted" % (m.name,))
        gamma = self._vray_gamma(m, walk, entry.name)
        if m.param(VB_RGB_SPACE, VB_RGB_SPACE_BLOCK) == VB_ACESCG:
            self._issue(walk, m.index, "VRayBitmap %r: ACEScg primaries drawn as sRGB" % (m.name,))
        if kind != DATA and m.param(VB_RGB, 0) == VB_INTENSITY:
            self._issue(walk, m.index, "VRayBitmap %r: RGB output intensity as gray drawn as its color" % (m.name,))
        crop = None
        clip = tuple(_num(m, pid, d) for pid, d in ((VB_CROP_U, 0.0), (VB_CROP_V, 0.0), (VB_CROP_W, 1.0),
                                                     (VB_CROP_H, 1.0)))
        if _flag(m, VB_CROP_ON, False) and clip != (0.0, 0.0, 1.0, 1.0):
            crop = Crop(*clip, place=m.param(VB_CROP_MODE, 0) == 1)
        mult = max(0.0, _num(m, VB_MULT, 1.0)) * max(0.0, _num(m, VB_RENDER_MULT, 1.0))
        if not mult <= MAX_MULTIPLIER:
            self._issue(walk, m.index, "VRayBitmap %r: multiplier %r not converted: 1" % (m.name, mult))
            mult = 1.0
        output = self._output(out) or TexOutput()
        output = dataclasses.replace(output, amount=output.amount * mult)
        alpha = m.param(VB_MONO if kind == DATA else VB_RGB, 0) == 1
        return Image(m.index, entry.name, entry.path, entry.resolved, found, mapping, crop,
                     None if output == TexOutput() else output, colorspace(kind, gamma), gamma, alpha)

    def _vray_gamma(self, m, walk, name):
        """A VRayBitmap's transfer function as a Bitmap gamma, None for automatic. Auto and From 3ds Max read a float
        file (EXR, HDR) as linear, as V-Ray and 3ds Max do."""
        space = m.param(VB_COLOR_SPACE, 0)
        if space == VB_LINEAR:
            return 1.0
        if space == VB_INVERSE_GAMMA:
            inverse = _num(m, VB_GAMMA, 0.0)
            if 0.1 <= inverse <= 10.0:
                return 1.0 / inverse
            self._issue(walk, m.index, "VRayBitmap %r: transfer function inverse gamma %r not converted: automatic"
                        % (m.name, m.param(VB_GAMMA, 0)))
        elif space is not None and space not in VB_AUTOMATIC:
            self._issue(walk, m.index, "VRayBitmap %r: transfer function %r not converted: automatic"
                        % (m.name, space))
        elif space != VB_SRGB and name.lower().endswith(FLOAT_IMAGES):
            return 1.0
        return None

    def _corona_image(self, m, kind, walk, entry, found, out):
        """A CoronaBitmap's Image. Its tiling, offset and W angle place the image as a Bitmap's do (measured in
        3ds Max); its environment mode applies only to an environment map."""
        def mode(pid):
            v = m.param(pid, 0)
            return v if v in (0, 1, 2) else 1
        tile_u, tile_v = mode(CB_TILE_U), mode(CB_TILE_V)
        channel = m.param(CB_CHANNEL, 0)
        if not (isinstance(channel, int) and not isinstance(channel, bool) and 0 <= channel <= 99):
            channel = 1
        mapping = Mapping(
            channel=channel, tiling=_vec(m, CB_SCALE, (1.0, 1.0, 1.0))[:2],
            offset=_vec(m, CB_OFFSET, (0.0, 0.0, 0.0))[:2],
            angle=(0.0, 0.0, _num(m, CB_W_ANGLE, 0.0)),
            tile=(tile_u != CB_NO_TILE, tile_v != CB_NO_TILE), mirror=(tile_u == CB_MIRROR, tile_v == CB_MIRROR),
            real_world=_flag(m, CB_REAL_WORLD, False), blur=_num(m, CB_BLUR, 1.0))
        if mapping.real_world:
            self._issue(walk, m.index, "CoronaBitmap %r: real-world scale, its tiling in scene units not converted"
                        % (m.name,))
        crop = None
        clip = tuple(_num(m, pid, d) for pid, d in ((CB_CLIP_U, 0.0), (CB_CLIP_V, 0.0), (CB_CLIP_W, 1.0),
                                                     (CB_CLIP_H, 1.0)))
        if _flag(m, CB_CLIP_ON, False) and clip != (0.0, 0.0, 1.0, 1.0):
            crop = Crop(*clip, place=m.param(CB_CLIP_MODE, 0) == 1)
        gamma = _num(m, CB_GAMMA, -1.0)  # -1: automatic
        gamma = _auto_gamma(gamma if 0.1 <= gamma <= 10.0 else None, entry.name)
        alpha = m.param(CB_MONO if kind == DATA else CB_RGB, 0) == 1
        return Image(m.index, entry.name, entry.path, entry.resolved, found, mapping, crop, self._output(out),
                     colorspace(kind, gamma), gamma, alpha)

    def _mapping(self, uv):
        if uv is None:
            return Mapping()
        p = reader_materials.placement(self.graph.scene, uv.index)
        source = p.source if p.source in (EXPLICIT, OBJECT_XYZ, VERTEX_COLOR, WORLD_XYZ) else EXPLICIT
        channel = 1 if p.channel is None else p.channel
        channel = 0 if source == VERTEX_COLOR else (channel if 0 <= channel <= 99 else 1)
        return Mapping(
            channel=channel,
            tiling=(_old(uv, UV_U_TILING, 1.0), _old(uv, UV_V_TILING, 1.0)),
            offset=(_old(uv, UV_U_OFFSET, 0.0), _old(uv, UV_V_OFFSET, 0.0)),
            angle=(_old(uv, UV_U_ANGLE, 0.0), _old(uv, UV_V_ANGLE, 0.0), _old(uv, UV_W_ANGLE, 0.0)),
            tile=p.tile,
            mirror=p.mirror,
            axis=p.axis if p.axis in (0, 1, 2) else 0,
            source=source,
            environment=p.environment,
            real_world=p.real_world,
            blur=_old(uv, UV_BLUR, 1.0))

    def _output(self, part):
        """The TexOutput of a map's Output part, None when it changes nothing."""
        if part is None:
            return None
        out = TexOutput(reader_materials.output_invert(self.graph.scene, part.index), _old(part, OUT_AMOUNT, 1.0),
                        _old(part, OUT_LEVEL, 1.0), _old(part, OUT_OFFSET, 0.0))
        return None if out == TexOutput() else out

    def _gamma(self, m):
        """The Bitmap's gamma override, None for automatic, when it cannot be read or is outside 0.1 to 10."""
        gamma = reader_materials.bitmap_gamma(self.graph.scene, m)
        return gamma if gamma is not None and math.isfinite(gamma) and 0.1 <= gamma <= 10.0 else None

    def _normal(self, m, ids, kind, walk, depth, chain):
        normal = self._sub(m, ids.normal, ids.normal_on, NORMAL, walk, depth, chain)
        bump = self._sub(m, ids.bump, ids.bump_on, BUMP, walk, depth, chain)
        if kind not in (NORMAL, BUMP):  # a normal map in a color or data input: its image only
            image = _peeled_image(normal) or _peeled_image(bump)
            if image is None:
                self._count(self.stats.unsupported, m)
                return None
            walk.approximated = True
            self._count(self.stats.peeled, m)
            return image
        key = ClassId(*m.class_id)
        if key == NORMAL_BUMP and m.param(NORMAL_BUMP_METHOD, 0) not in (None, 0):
            self._issue(walk, m.index, "Normal Bump %r: method %r drawn as tangent space" % (
                m.name, m.param(NORMAL_BUMP_METHOD, 0)))
        if key == CORONA_NORMAL and _flag(m, CORONA_ADD_GAMMA, False):
            self._issue(walk, m.index, "CoronaNormal %r: 'add gamma to input' not converted" % (m.name,))
        bump = Bump(_bump_input(bump), max(0.0, _num(m, ids.bump_strength, 1.0))) if bump is not None else None
        if normal is None:
            return bump
        channel = m.param(ids.channel, 0) if ids.channel is not None else None
        channel = channel if isinstance(channel, int) and not isinstance(channel, bool) and 0 <= channel <= 99 else 1
        return NormalMap(normal, max(0.0, _num(m, ids.strength, 1.0)), _flag(m, ids.flip_red, False),
                         _flag(m, ids.flip_green, False), _flag(m, ids.swap, False), bump, channel)


def _bump_input(node):
    return node.input if isinstance(node, Bump) else node


def _peeled_image(node):
    """The image of a normal map's sub-node, else the node itself."""
    if isinstance(node, NormalMap):
        return node.input
    if isinstance(node, Bump):
        return node.input
    return node


def _scaled(n, amount):
    bump = Bump(n.bump.input, n.bump.strength * amount) if n.bump is not None else None
    return dataclasses.replace(n, strength=n.strength * amount, bump=bump)


def _falloff(conv, m, kind, walk, depth, chain):
    """0 color1, 2 map1, 3 map1On. Color 1 only when map 1 is not used."""
    if conv._on(m, 2, 3) is not None:
        return conv._sub(m, 2, 3, kind, walk, depth, chain)
    return conv._constant(m, 0, kind, (0.0, 0.0, 0.0))


def _vray_dirt(conv, m, kind, walk, depth, chain):
    """13 unoccluded_color, 17 texmap_unoccluded_color, 18 its switch. The color only when the map is not used."""
    if conv._on(m, 17, 18) is not None:
        return conv._sub(m, 17, 18, kind, walk, depth, chain)
    return conv._constant(m, 13, kind, (1.0, 1.0, 1.0))


def _wrapped(conv, m, map_pid, on_pid, kind, walk, depth, chain):
    """The map of a wrapper that has no color of its own (Output, RGB Tint, VRayColor2Bump). Without a used map it
    gives no graph and is an issue: what 3ds Max draws there was not measured, so nothing stands in for it."""
    if conv._on(m, map_pid, on_pid) is None:
        conv._issue(walk, m.index, "%s %r: %s, not drawn" % (
            conv._class_name(m), m.name, "no map" if on_pid is None else "no map (or its map off)"))
        return None
    return conv._sub(m, map_pid, on_pid, kind, walk, depth, chain)


def _output_map(conv, m, kind, walk, depth, chain):
    """0 map1, 1 map1Enabled; its own Output part's invert is kept."""
    node = _wrapped(conv, m, 0, 1, kind, walk, depth, chain)
    part = next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_TEXOUTPUT), None)
    out = conv._output(part)
    return Invert(node) if node is not None and out is not None and out.invert else node


def _rgb_tint(conv, m, kind, walk, depth, chain):
    """3 map1, 4 map1Enabled."""
    return _wrapped(conv, m, 3, 4, kind, walk, depth, chain)


def _color2bump(conv, m, kind, walk, depth, chain):
    """0 map (no switch)."""
    return _wrapped(conv, m, 0, None, kind, walk, depth, chain)


def _sides(conv, m, ids, kind, walk, depth, chain):
    """The nodes of a two-map wrapper's sides ((map pid, switch pid) each), None where no map is used, and per side
    whether a used map converted to nothing."""
    nodes = tuple(conv._sub(m, pid, on, kind, walk, depth, chain) for pid, on in ids)
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


def _mask(conv, m, pid, on_pid, walk, depth, chain):
    """A mask map; a used one that converts to nothing leaves the mix amount (an approximation)."""
    mask = conv._sub(m, pid, on_pid, DATA, walk, depth, chain)
    if mask is None and conv._on(m, pid, on_pid) is not None:
        walk.approximated = True
    return mask


def _mix(conv, m, kind, walk, depth, chain):
    """0 mixAmount (fraction), 3 useCurve, 4 / 5 color1 / 2, 6 / 7 map1 / 2, 8 mask, 9 / 10 / 11 their switches."""
    (a, b), lost = _sides(conv, m, ((6, 9), (7, 10)), kind, walk, depth, chain)
    mask = _mask(conv, m, 8, 11, walk, depth, chain)
    factor, curve = min(1.0, max(0.0, _num(m, 0, 0.0))), _flag(m, 3, False)
    if any(lost):
        w = _lost_weight(lost, (None, None) if mask is not None or curve else (1.0 - factor, factor))
        if w == 1.0:
            return None
        if w is None:
            return _other_side(conv, m, (a, b), walk)
    if curve:
        walk.approximated = True
        conv._issue(walk, m.index, "Mix %r: its mix curve not converted" % (m.name,))
    a = a or conv._constant(m, 4, kind, (0.0, 0.0, 0.0))
    b = b or conv._constant(m, 5, kind, (1.0, 1.0, 1.0))
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
    Its color only without a map (3ds Max's rule): a map that converts to nothing leaves the input its own value."""
    node = conv._sub(m, 1, None, kind, walk, depth, chain)
    if node is None:
        if conv._on(m, 1, None) is not None:
            return None
        node = conv._constant(m, 0, kind, (0.0, 0.0, 0.0))
    if m.param(2, 0) not in (None, 0) or _num(m, 10, 0.0) != 0.0:
        walk.approximated = True
        conv._issue(walk, m.index, "Color Correction %r: rewiring and tint not converted" % (m.name,))
    hue, saturation = _num(m, 7, 0.0) / 360.0, 1.0 + _num(m, 8, 0.0) / 100.0
    if m.param(11, 0) != 1:
        return ColorCorrect(node, hue, saturation, _num(m, 12, 0.0) / 100.0, _num(m, 13, 0.0) / 100.0)
    if _num(m, 26, 1.0) != 1.0 or _num(m, 30, 0.0) != 0.0:
        walk.approximated = True
        conv._issue(walk, m.index, "Color Correction %r: pivot and lift not converted" % (m.name,))
    return ColorCorrect(node, hue, saturation, gain=_num(m, 18, 100.0) / 100.0, gamma=max(0.01, _num(m, 22, 1.0)))


def _composite(conv, m, kind, walk, depth, chain):
    """Tables: 1 mapEnabled, 3 maskEnabled, 5 blendMode (0 normal), 8 opacity (%), 9 mapList, 10 mask. Simple (every
    used layer normal, no mask): kept; else peeled to its first Bitmap."""
    block = m.block(0)
    maps = block.value(9) if block is not None else None
    maps = maps if isinstance(maps, list) else []

    def at(pid, k, default):
        v = m.param(pid, 0, tab=k)
        return v if _finite(v) else default

    used = [k for k, r in enumerate(maps) if isinstance(r, pblock.Reference) and r.index is not None
            and at(1, k, 1)]
    simple = all(at(5, k, 0) == 0 and not (at(3, k, 1) and _ref(m, 10, k) is not None) for k in used)
    if not simple:
        image = conv._peel_to_image(m, kind, walk, depth, chain, "blend modes or masks, and no bitmap below")
        if image is not None:
            conv._issue(walk, m.index, "Composite %r: blend modes or masks not converted" % (m.name,))
        return image
    layers = []
    for k in used:
        node = conv._node(maps[k].index, kind, walk, depth, chain)
        if node is None:
            walk.approximated = True
            conv._lost(m, maps[k].index, walk)
        else:
            layers.append((node, min(1.0, max(0.0, at(8, k, 100.0) / 100.0))))
    if not layers:
        return None
    if len(layers) == 1 and layers[0][1] == 1.0:
        return layers[0][0]
    return Composite(tuple(layers))


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
    scaling the swatch value: 2 x 128 = 255); the temperature is kelvin_rgb's sRGB color, decoded with the sRGB
    curve whatever the gamma (it matched Corona's own 3000 K that way); the HDR color is linear already."""
    method, mult = m.param(CC_METHOD, 0), max(0.0, _num(m, CC_MULTIPLIER, 1.0))
    if method == 1:
        rgb = tuple(max(0.0, c) * mult for c in _vec(m, CC_HDR, (1.0, 1.0, 1.0)))
        return Constant(rgb if kind == COLOR else sum(rgb) / 3.0)
    swatch = None
    if method == 2:
        lin = colors.GAMMA_OFF.color(tuple(c * mult for c in kelvin_rgb(_num(m, CC_TEMPERATURE, 6500.0))))
        return Constant(lin if kind == COLOR else sum(lin) / 3.0)
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
    lin = conv.swatches.color(tuple(c * mult for c in swatch))
    return Constant(lin if kind == COLOR else sum(lin) / 3.0)


def _vray_color(conv, m, kind, walk, depth, chain):
    """VRayColor: its swatch (color, else red / green / blue) times rgb_multiplier, then to the power color_gamma
    (renderMap in 3ds Max: (100 gray, multiplier 2, gamma 2) -> 255 * (200 / 255) ^ 2), then made linear by the
    scene's rule like every swatch. In temperature mode color holds V-Ray's own temperature color, taken through
    the same rule (not measured with the gamma off, where it is decoded from sRGB unlike CoronaColor's kelvin). A
    mono input takes the color, not the alpha (measured with a Mix mask); on a data input the Constant is the mean
    of the linear color, as every constant's."""
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
    lin = conv.swatches.color(tuple(c ** float(gamma) for c in scaled))
    return Constant(lin if kind == COLOR else sum(lin) / 3.0)


def _corona_mix(conv, m, kind, walk, depth, chain):
    """Operation mix -> Mix(bottom, top, amount, mask), multiply -> Multiply (under a Mix when the amount is below 1
    or a mask is set); any other operation is peeled to its first bitmap. A layer without a map (or with its map
    switched off) is its color. mixInSRgb (214, on by default) changed nothing in renderMap renders of a 50 % mix
    of black and white in 3ds Max (the Corona render itself was not measured): not read."""
    op = m.param(CM_OPERATION, 0)
    if op not in (CM_MIX, CM_MULTIPLY):
        image = conv._peel_to_image(m, kind, walk, depth, chain, "operation %r and no bitmap below" % (op,))
        if image is not None:
            conv._issue(walk, m.index, "CoronaMix %r: operation %r drawn as its first bitmap" % (m.name, op))
        return image
    (bottom, top), lost = _sides(conv, m, ((CM_MAP_BOTTOM, CM_BOTTOM_ON), (CM_MAP_TOP, CM_TOP_ON)), kind, walk,
                                 depth, chain)
    mask = _mask(conv, m, CM_MASK, CM_MASK_ON, walk, depth, chain)
    amount = min(1.0, max(0.0, _num(m, CM_AMOUNT, 1.0)))
    if any(lost):
        if mask is not None:
            weights = (None, None)
        elif op == CM_MIX:
            weights = (1.0 - amount, amount)
        else:  # bottom times top: either factor shows unless the amount is 0 (the bottom alone)
            weights = (1.0, 0.0) if amount == 0.0 else (None, None)
        w = _lost_weight(lost, weights)
        if w == 1.0:
            return None
        if w is None:
            return _other_side(conv, m, (bottom, top), walk)
    bottom = bottom or conv._constant(m, CM_COLOR_BOTTOM, kind, (0.0, 0.0, 0.0))
    top = top or conv._constant(m, CM_COLOR_TOP, kind, (1.0, 1.0, 1.0))
    if (_num(m, CM_MULT_TOP, 1.0), _num(m, CM_MULT_BOTTOM, 1.0), _num(m, CM_OFFSET_TOP, 0.0),
            _num(m, CM_OFFSET_BOTTOM, 0.0)) != (1.0, 1.0, 0.0, 0.0):
        walk.approximated = True
        conv._issue(walk, m.index, "CoronaMix %r: layer multipliers and offsets not converted" % (m.name,))
    if op == CM_MIX:
        return Mix(bottom, top, amount, mask)
    product = Multiply(bottom, top)
    return product if mask is None and amount == 1.0 else Mix(bottom, product, amount, mask)


_KEEP = {MIX: _mix, RGB_MULTIPLY: _rgb_multiply, COLOR_CORRECTION: _color_correction, COMPOSITE: _composite,
         classids.CORONA_COLOR: _corona_color, classids.CORONA_MIX: _corona_mix, classids.VRAY_COLOR: _vray_color}
_PEEL = {FALLOFF: _falloff, VRAY_DIRT: _vray_dirt, OUTPUT: _output_map, RGB_TINT: _rgb_tint,
         VRAY_COLOR2BUMP: _color2bump}

# MaterialIR input -> its kind (normal and bump: MapRefs of their own)
SLOT_KINDS = (("base_color", COLOR), ("metallic", DATA), ("roughness", DATA), ("specular", COLOR),
              ("transmission", COLOR), ("emission_color", COLOR), ("alpha", DATA))


def texture_graphs(ir, tex):
    """{input name: TextureGraphIR} for the inputs of a MaterialIR that a usable map drives."""
    out = {}
    for name, kind in SLOT_KINDS:
        inp = getattr(ir, name)
        if inp.map is not None:
            g = tex.convert(inp.map, kind, inp.value)
            if g is not None:
                out[name] = g
    for name, kind in (("normal", NORMAL), ("bump", BUMP)):
        ref = getattr(ir, name)
        if ref is not None:
            g = tex.convert(ref, kind)
            if g is not None:
                out[name] = g
    return out
