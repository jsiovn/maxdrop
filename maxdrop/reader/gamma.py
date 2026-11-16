# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Gamma/LUT setting a .max file was saved with: whether 3ds Max's gamma was on, and its file gammas.

    with CompoundFile(path) as cf:
        g = scene_gamma(cf)             # SceneGamma(enabled=True, file_in=2.2, file_out=2.2), or None
        g.enabled                       # the gamma was on: a color swatch's value is linear

The Scene stream holds one RenderEnvironment object ((0xEE448B23, 0), superclass 0x1010); its 0x6010 chunk is a
u32 (1: gamma on, 0: off) and two f32, the input and output gamma of files (Preferences > Gamma and LUT). The
display gamma is not in the file. docs/FORMAT.md says which probe showed what.

An enabled value other than 0 or 1, a payload too short, a file without the chunk and a Scene stream or class
directory that cannot be read give None: the caller then takes 3ds Max's default. A file gamma that is not a
positive finite number is None in the SceneGamma, the switch is kept. No bpy.
"""
import collections
import math
import struct

from . import cfb, chunks, classids, scene as scene_mod

GAMMA_CHUNK = 0x6010

_PAYLOAD = struct.Struct("<Iff")


class SceneGamma(collections.namedtuple("SceneGamma", "enabled file_in file_out")):
    """enabled: the gamma was on; file_in, file_out: the file input and output gammas, None when unusable."""
    __slots__ = ()


def _gamma(v):
    return float("%.7g" % v) if math.isfinite(v) and v > 0 else None  # the f32's precision: 2.2, not 2.2000000477


def decode(payload):
    """The SceneGamma of a 0x6010 payload (bytes-like), None when it cannot be one."""
    if len(payload) < _PAYLOAD.size:
        return None
    enabled, file_in, file_out = _PAYLOAD.unpack_from(payload)
    if enabled not in (0, 1):
        return None
    return SceneGamma(bool(enabled), _gamma(file_in), _gamma(file_out))


def scene_gamma(source):
    """The SceneGamma of an open cfb.CompoundFile or a scene.Scene; None when the file does not say."""
    try:
        return _find(source if isinstance(source, scene_mod.Scene) else scene_mod.Scene.from_file(source))
    except (cfb.CfbError, chunks.ChunkError):
        return None


def _find(scene):
    holders = {e.index for e in scene.classes
               if e.superclass == classids.SC_RENDER_ENVIRONMENT and e.class_id == classids.RENDER_ENVIRONMENT}
    if not holders:
        return None
    for i in range(len(scene)):
        if scene.class_index(i) in holders:
            chunk = scene.chunk(i)
            found = chunk.first(GAMMA_CHUNK) if chunk.container else None
            if found is not None and not found.container:
                return decode(found.view())
    return None
