# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Swatch colors: how a 3ds Max color swatch becomes linear RGB, by the gamma setting the scene was saved with.

    sw = of_scene(scene)                # GAMMA_ON, GAMMA_OFF or UNKNOWN (a reader Scene or an open CompoundFile)
    sw.color((0.5, 0.5, 0.5))           # linear RGB, each channel clamped to 0..1 first
    sw.channel(0.5)                     # one channel
    sw.line(), sw.note                  # the report's line; the issue when the file does not say

With the gamma on (2.2, 3ds Max's default since 2014) 3ds Max and its renderers use a swatch's value as linear: a
128 grey swatch renders as 0.502 linear (V-Ray 5.2 writes byte 187). With the gamma off the scene is display-
referred: the swatch renders as stored (byte 128), which Blender's sRGB display shows only from 0.216 linear, so it
is decoded with the sRGB curve, as image files are in both cases. A file that does not say is taken as gamma on,
with a note. Measured in 3ds Max 2020 + V-Ray 5.2 (docs/FORMAT.md, Scene gamma); Corona's swatches are assumed to
follow 3ds Max's rule (a Corona render does not run here). LUT mode belongs to the session, not the file: a file
saved in it opens with the gamma on, as its chunk says.

file_in is the file input gamma with the gamma on: a Bitmap with automatic gamma (and a VRayBitmap whose transfer
function is From 3ds Max) is read with it (texmaps). With the gamma off 3ds Max reads a Bitmap as stored whatever
its gamma, and file_in stays 2.2. A rule with file_in 2.2 is GAMMA_ON itself.

CoronaColor's HDR color (linear, not measured with the gamma off) and colors made by a curve fit in sRGB
(kelvin_rgb, the lights') do not go through the rule. No bpy.
"""
import dataclasses

from ..reader import gamma as _gamma
from ..reader import scene as _scene

FILE_IN_RANGE = (0.1, 10.0)  # a file input gamma outside it is taken as 2.2, as a Bitmap's override outside it
GAMMA_NOTE = "the scene's gamma setting was not found in the file: color swatches taken as linear (gamma on)"


SRGB_FILE_GAMMA = 2.2  # 3ds Max's default file input gamma: an automatic image stays sRGB


def srgb_to_linear(c):
    """One sRGB-encoded channel (0..1) to linear."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


@dataclasses.dataclass(frozen=True)
class Swatches:
    """The swatch rule of one scene: linear (the value is linear) or not (the sRGB curve); note: the issue to report
    when the scene did not say; file_in: the gamma a Bitmap with automatic gamma is read with when linear."""
    linear: bool
    note: str = ""
    file_in: float = SRGB_FILE_GAMMA

    def channel(self, c):
        c = min(1.0, max(0.0, c))
        return c if self.linear else srgb_to_linear(c)

    def color(self, rgb):
        """A swatch (0..1 per channel) as linear RGB, clamped to 0..1 first."""
        return tuple(self.channel(c) for c in rgb[:3])

    def line(self):
        if self.note:
            return "Color swatches: linear (the scene's gamma setting not found)"
        line = "Color swatches: %s" % ("linear (the scene's gamma is on)" if self.linear else
                                       "decoded from sRGB (the scene's gamma is off)")
        if self.linear and self.file_in != SRGB_FILE_GAMMA:
            line += "; images with automatic gamma read with input gamma %s" % round(self.file_in, 3)
        return line


GAMMA_ON = Swatches(True)
GAMMA_OFF = Swatches(False)
UNKNOWN = Swatches(True, GAMMA_NOTE)


def for_gamma(g):
    """The rule for a reader.gamma.SceneGamma, UNKNOWN for None."""
    if g is None:
        return UNKNOWN
    if not g.enabled:
        return GAMMA_OFF
    lo, hi = FILE_IN_RANGE
    if g.file_in is None or not lo <= g.file_in <= hi or abs(g.file_in - SRGB_FILE_GAMMA) < 1e-6:
        return GAMMA_ON
    return Swatches(True, file_in=g.file_in)


def of_scene(source):
    """The rule of a reader Scene or an open cfb.CompoundFile; UNKNOWN when the file does not say."""
    return for_gamma(_gamma.scene_gamma(source))


def of_graph(graph):
    """The rule of a MaterialGraph's scene; UNKNOWN for a graph without a reader Scene."""
    s = getattr(graph, "scene", None)
    return of_scene(s) if isinstance(s, _scene.Scene) else UNKNOWN
