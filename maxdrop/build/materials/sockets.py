# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Labels, limits and blend tables of the node trees; UV, image and socket helpers."""
import os

from mathutils import Euler, Matrix, Vector

from ...convert import scene as convert_scene
from ...convert import texmaps as tx


SPECULAR_LEVEL = 0.5
TWIN_LABEL, WEIGHT_LABEL = "Without reflection", "Reflection weight"  # reflection_weight()'s nodes
MIRROR_LABEL = "Mirror reflection"  # reflection_weight()'s copy for a weight without Fresnel (Base Color: its color)
MIRROR_INPUTS = {"Metallic": 1.0, "Base Color": (1.0, 1.0, 1.0, 1.0), "Specular IOR Level": SPECULAR_LEVEL}
REFRACTION_LABEL = "Refraction without reflection"  # reflection_weight()'s twin of refracting glass
TIR_LABEL = "Total internal reflection"  # tir_weight()'s nodes
TIR_FRESNEL = 0.9999  # a Fresnel above it: the glass reflects totally (the Fresnel node gives 1 there)
CLIP_LABEL = "Clip"  # the node that masks an image's output (clip_axes)
MAX_LAYER_DEPTH = 8  # layers within layers drawn (convert/materials/ already stops a deeper or cyclic chain)
SRGB_CURVE_COLUMNS = 3  # srgb_curve's node columns: its Mix at depth, its Math nodes at depth + 1 and depth + 2
VOLUME_VIEWPORT_ALPHA = 0.1  # a volume-only material's viewport color alpha: Solid view shows what is inside
VOLUME_BOUNCES = ("its medium scatters: Cycles scatters once at its default Volume Bounces of 0 (Render Properties > "
                  "Light Paths); raise them for multiple scattering, as Corona renders it")
X_STEP, Y_STEP = 300, 280
COLOR, FLOAT = "color", "float"
# Blend op -> the Mix node's blend type drawn at factor 1 (A the bottom; hard light swaps them, linear burn is an
# add minus 1, floored at 0). Dodge, burn and exclusion are Vector Math forms (arith): Blender's DODGE, BURN and
# EXCLUSION clamp where Corona does not, and DODGE leaves black under white at 0 (maxdrop-em3.161).
BLEND_OPS = {tx.BLEND_ADD: 'ADD', tx.BLEND_SUBTRACT: 'SUBTRACT', tx.BLEND_DIVIDE: 'DIVIDE', tx.BLEND_MIN: 'DARKEN',
             tx.BLEND_MAX: 'LIGHTEN', tx.BLEND_DIFFERENCE: 'DIFFERENCE', tx.BLEND_SCREEN: 'SCREEN',
             tx.BLEND_OVERLAY: 'OVERLAY', tx.BLEND_HARD_LIGHT: 'OVERLAY', tx.BLEND_LINEAR_BURN: 'ADD',
             tx.BLEND_LINEAR_LIGHT: 'LINEAR_LIGHT'}
# never below 0 on the layers' magnitudes: no closing ABSOLUTE
NON_NEGATIVE_BLENDS = (tx.BLEND_ADD, tx.BLEND_SUBTRACT, tx.BLEND_DIFFERENCE, tx.BLEND_LINEAR_BURN, tx.BLEND_BURN)
# Composite blend mode -> the Mix node's blend type drawn at factor 1 (texmaps: AVERAGE, SPOTLIGHT, SPOTLIGHT_BLEND
# and HARD_LIGHT have forms of their own, LINEAR_DODGE is ADD clamped before the opacity, as measured)
BLEND_TYPES = {tx.ADDITION: 'ADD', tx.SUBTRACT: 'SUBTRACT', tx.DARKEN: 'DARKEN', tx.MULTIPLY_BLEND: 'MULTIPLY',
               tx.COLOR_BURN: 'BURN', tx.LIGHTEN: 'LIGHTEN', tx.SCREEN: 'SCREEN', tx.COLOR_DODGE: 'DODGE',
               tx.LINEAR_DODGE: 'ADD', tx.OVERLAY: 'OVERLAY', tx.HARD_LIGHT: 'OVERLAY', tx.DIFFERENCE: 'DIFFERENCE',
               tx.EXCLUSION: 'EXCLUSION', tx.HUE: 'HUE', tx.SATURATION: 'SATURATION', tx.COLOR_BLEND: 'COLOR',
               tx.VALUE: 'VALUE', tx.AVERAGE: 'MIX', tx.SPOTLIGHT: 'MULTIPLY', tx.SPOTLIGHT_BLEND: 'MULTIPLY'}
_EPS = 1e-6
MISSING = object()  # what a graph gives where its image is missing


def uv_transform(mapping):
    """(location, rotation, scale) of the Mapping node (POINT) that places a texmaps.Mapping; None for the identity."""
    tiling, offset, angle = tuple(mapping.tiling), tuple(mapping.offset), tuple(mapping.angle)
    if tiling == (1.0, 1.0) and offset == (0.0, 0.0) and angle == (0.0, 0.0, 0.0):
        return None
    rs = Euler(angle, 'XYZ').to_matrix() @ Matrix.Diagonal((tiling[0], tiling[1], 1.0))
    location = Vector((0.5, 0.5, 0.0)) - rs @ Vector((0.5 + offset[0], 0.5 + offset[1], 0.0))
    return tuple(location), angle, (tiling[0], tiling[1], 1.0)


def repeat_axes(mapping):
    """Per axis (U, V), how an image repeats: 'MIRROR' (mirror on, which tiles too, as in 3ds Max), 'REPEAT'
    (tile) or 'CLIP'."""
    return tuple('MIRROR' if m else 'REPEAT' if t else 'CLIP' for t, m in zip(mapping.tile, mapping.mirror))


def mirror_scale(mapping):
    """The Vector Math MULTIPLY factor after the placement: 2 on a mirrored axis (two copies per tile), 1 on the
    other; None when no axis mirrors."""
    if not any(mapping.mirror):
        return None
    return tuple(2.0 if m else 1.0 for m in mapping.mirror) + (1.0,)


def per_axis(mapping, crop):
    """Whether the nodes repeat the image per axis (repeat_cell): always with a crop, else when the axes differ."""
    axes = repeat_axes(mapping)
    return crop is not None or axes[0] != axes[1]


def clip_axes(mapping, crop=None):
    """The axes (0 U, 1 V) a mask clips (texture_node): where an axis repeats, the CLIP extension would fade the
    image's border half-texel toward transparent black at every tile and mirror line (rendered: EEVEE and Cycles),
    so the image is drawn EXTEND and the mask cuts what clips: a placed image's rectangle on both axes, else each
    clipped axis. Empty when nothing repeats: the CLIP extension does it."""
    axes = repeat_axes(mapping)
    if axes == ('CLIP', 'CLIP'):
        return ()
    if crop is not None and crop.place:
        return (0, 1)
    return tuple(i for i, how in enumerate(axes) if how == 'CLIP')


def extension(mapping, crop=None):
    """The Image Texture extension of a placement: Blender has one for both axes. Both axes alike without a crop:
    theirs. Nothing repeats: CLIP. Otherwise the nodes repeat per axis and keep the coordinates inside the image or
    its crop rectangle, EXTEND (no bleed from its opposite edge, which REPEAT draws along a mirror line in EEVEE and
    Cycles; the wrap node's jump drew no seam in either, rendered), and clip_axes() masks what clips."""
    axes = repeat_axes(mapping)
    if not per_axis(mapping, crop):
        return axes[0]
    return 'CLIP' if axes == ('CLIP', 'CLIP') else 'EXTEND'


# the first bytes of every image format Blender reads that has a signature (TGA has none: _targa; WebP apart)
_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"BM", b"BA", b"CI", b"CP", b"IC", b"PT", b"II*\x00",
               b"MM\x00*", b"II+\x00", b"MM\x00+", b"v/1\x01", b"#?", b"DDS ", b"8BPS",
               b"\x00\x00\x00\x0cjP  \r\n\x87\n", b"\xffO\xffQ", b"\x01\xda", b"\xda\x01", b"\x80\x2a\x5f\xd7",
               b"\xd7\x5f\x2a\x80", b"SDPX", b"XPDS")


def _targa(head):
    """A plausible TGA header (color map type, image type, pixel depth): Blender reads a Targa whatever its name."""
    return (len(head) >= 18 and head[1] in (0, 1) and head[2] in (1, 2, 3, 9, 10, 11)
            and head[16] in (8, 15, 16, 24, 32))


_SIGNED = frozenset((".png", ".jpg", ".jpeg", ".jpe", ".bmp", ".tif", ".tiff", ".exr", ".hdr", ".dds", ".psd",
                     ".webp", ".jp2", ".j2k", ".j2c", ".sgi", ".rgb", ".rgba", ".bw", ".cin", ".dpx"))


def image_has_data(path):
    """False when the file at path cannot hold an image: empty, or named as a format with a signature but starting
    with none Blender reads. Only the first bytes are read: Blender loads images lazily, and asking it
    (Image.has_data) would decode every image during the import. A file that cannot be opened passes: its load
    reports it."""
    try:
        with open(path, "rb") as f:
            head = f.read(18)
    except OSError:
        return True
    if not head:
        return False
    if os.path.splitext(path)[1].lower() not in _SIGNED:
        return True
    return head.startswith(_SIGNATURES) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP") or _targa(head)


def uv_layer_name(channel):
    """The UV layer build.objects made for a 3ds Max map channel (convert.scene's names)."""
    return convert_scene.UV_FIRST if channel == 1 else convert_scene.UV_NAME % channel


def _mean(v):
    return sum(v[:3]) / 3.0 if isinstance(v, (tuple, list)) else float(v)


def _on(node, name):
    """node's input of that name is linked, or above 0 (a color: in any channel); False when it lacks one."""
    s = node.inputs.get(name)
    if s is None:
        return False
    v = s.default_value
    return s.is_linked or max(tuple(v)[:3] if hasattr(v, "__len__") else (v,)) > 0.0


def _as(value, space):
    """A constant in a space: an RGB tuple for COLOR, a float for FLOAT."""
    if space == COLOR:
        return tuple(value[:3]) if isinstance(value, (tuple, list)) else (float(value),) * 3
    return _mean(value)


def _default(socket, value):
    """Set an unlinked input from a constant, whatever its type."""
    if socket.type == 'RGBA':
        socket.default_value = _as(value, COLOR) + (1.0,)
    elif socket.type == 'VECTOR':
        socket.default_value = _as(value, COLOR)
    elif socket.type == 'BOOLEAN':
        socket.default_value = bool(value)
    else:
        socket.default_value = _mean(value)


def _in(node, identifier):
    """A node's input by identifier: names change between Blender versions (Fac / Factor), identifiers do not."""
    return next(s for s in node.inputs if s.identifier == identifier)


def _out(node, identifier):
    return next(s for s in node.outputs if s.identifier == identifier)
