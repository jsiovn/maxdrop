# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dome light and its texture (describe_dome(), dome_texture())."""
import math

from ...reader import classids
from ...reader import materials as reader_materials
from .. import colors, params, texmaps
from ..params import finite
from .ids import (
    DOME_AXIAL, DOME_CORONA, DOME_CROP, DOME_FLAT, DOME_FLOAT_OFF, DOME_GAMMA, DOME_MIRRORED, DOME_NO_TEXTURE,
    DOME_NOT_FOUND, DOME_OUTPUT, DOME_PLACEMENT, DOME_PROJECTION, DOME_RADIANCE, DOME_ROOT, DOME_SHADOW, DOME_SWITCH,
    DOME_VERTICAL, GLOSSY, MAX_POWER, OUT_OF_RANGE, P_AFFECT_DIFFUSE, P_AFFECT_REFLECTIONS, P_AFFECT_SPECULAR,
    P_DOME_LOCKED, P_DOME_SPHERICAL, P_INVISIBLE, P_MULTIPLIER, P_SHADOW, P_TEXMAP, P_TEXMAP_ON, P_UNITS, UNITS_DEFAULT,
)
from .families import _nonnegative, light_color


class DomeDescription:
    """A dome light as the World: node (object index) and name; color linear RGB; radiance in W/m^2/sr (the World's
    strength before the Light Strength); hemisphere: only the half above the dome's local XY plane shines; rotation
    the dome node's world rotation (3 rows of 3, Blender's convention: the columns are its local axes in world space,
    in the file's frame); locked: its texture turns with the node; texmap the object index of its texture map, None
    without one (or switched off); camera, diffuse, glossy: which rays see it; texture: the DomeTexture ops sets
    (dome_texture), None: the color; shown: the scene's gamma is off, so camera rays see the color's value (the
    swatch as stored times the strength) through the sRGB curve, as V-Ray 5.2 shows it (maxdrop-6n0.6.21: an
    untextured dome at multiplier 0.5, sky 0.5, target 0.214)."""
    __slots__ = ("node", "name", "color", "radiance", "hemisphere", "rotation", "locked", "texmap", "camera",
                 "diffuse", "glossy", "texture", "shown")

    def __init__(self, node, name, color=(1.0, 1.0, 1.0), radiance=0.0, hemisphere=False,
                 rotation=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), locked=False, texmap=None,
                 camera=True, diffuse=True, glossy=True):
        self.node, self.name, self.color, self.radiance = node, name, color, radiance
        self.hemisphere, self.rotation, self.locked, self.texmap = hemisphere, rotation, locked, texmap
        self.camera, self.diffuse, self.glossy = camera, diffuse, glossy
        self.texture, self.shown = None, False

    def __repr__(self):
        return "DomeDescription(%r, %g W/m2/sr%s)" % (self.name, self.radiance, ", texture" if self.texture else "")


class DomeTexture:
    """The image of a dome's texture: image (convert.texmaps.Image, its file found), turn (radians: what V-Ray adds to
    phi before u = 0.5 + phi / 2 pi, its horizontal rotation; a Bitmap's spherical environment pi / 2), amount (its
    Output's amount, a VRayBitmap's multipliers: a factor on the strength) and shown (a float image of a gamma-off
    scene: camera rays see the sky's value, the image times the strength, through the sRGB curve, as V-Ray 5.2 shows
    it; other rays the image as it is, maxdrop-6n0.6.21)."""
    __slots__ = ("image", "turn", "amount", "shown")

    def __init__(self, image, turn=0.0, amount=1.0, shown=False):
        self.image, self.turn, self.amount, self.shown = image, turn, amount, shown

    def __repr__(self):
        return "DomeTexture(%r, %g rad, x %g%s)" % (self.image.name, self.turn, self.amount,
                                                   ", shown" if self.shown else "")


def _rotation(world, issues):
    """The rotation of a reader world matrix (rows: local axes in world space) as Blender rows (columns = the axes):
    Gram-Schmidt of X and Y, Z their cross product (a mirror an issue); identity for a degenerate matrix."""
    x, y = [list(map(float, world[r][:3])) for r in (0, 1)]
    z0 = list(map(float, world[2][:3]))

    def norm(v):
        n = math.sqrt(sum(c * c for c in v))
        return [c / n for c in v] if math.isfinite(n) and n > 0 else None

    def cross(a, b):
        return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]

    x = norm(x)
    if x is not None:
        d = sum(a * b for a, b in zip(x, y))
        y = norm([b - d * a for a, b in zip(x, y)])
    if x is None or y is None:
        issues.append(DOME_FLAT)
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    z = cross(x, y)
    if sum(a * b for a, b in zip(z, z0)) < 0:
        issues.append(DOME_MIRRORED)
    return tuple(tuple(axis[r] for axis in (x, y, z)) for r in range(3))


def describe_dome(node, name, values, swatches, world):
    """(DomeDescription of a dome light's values on node (world: its reader world matrix), issues)."""
    issues = []
    m = _nonnegative("multiplier", values[P_MULTIPLIER], issues)
    radiance = m * DOME_RADIANCE.get(values[P_UNITS], DOME_RADIANCE[UNITS_DEFAULT])
    if not radiance <= MAX_POWER:
        issues.append(OUT_OF_RANGE)
        radiance = 0.0
    diffuse, spec, refl = (bool(values[p]) for p in (P_AFFECT_DIFFUSE, P_AFFECT_SPECULAR, P_AFFECT_REFLECTIONS))
    if spec != refl:
        issues.append(GLOSSY % ("on" if spec else "off", "on" if refl else "off"))
    if not values[P_SHADOW]:
        issues.append(DOME_SHADOW)
    texmap = values[P_TEXMAP] if values[P_TEXMAP_ON] else None
    dd = DomeDescription(node, name, light_color(values, swatches), radiance, not values[P_DOME_SPHERICAL],
                         _rotation(world, issues), bool(values[P_DOME_LOCKED]), texmap, not values[P_INVISIBLE],
                         diffuse, spec or refl)
    dd.shown = not swatches.linear
    return dd, issues


VB_H_ROTATION, VB_V_ROTATION, VB_SPHERICAL = 3, 4, 2  # VRayBitmap block 0: radians; mapType spherical
# VRayBitmap block 0, read from a probe scene: horizontal and vertical flip, ground projection, axial rotation (radians)
VB_H_FLIP, VB_V_FLIP, VB_GROUND, VB_AXIAL = 5, 6, 26, 36
_VB_PROJECTIONS = {0: "angular", 1: "cubic", 3: "mirrored ball", 4: "3ds Max standard"}
ENV_SPHERICAL = 1  # a Placement's env_mapping: 1 spherical, 2 cylindrical, 3 shrink-wrap, 4 screen
_ENV_PROJECTIONS = {2: "cylindrical environment", 3: "shrink-wrap environment", 4: "screen environment"}


def dome_texture(graph_ir, material_graph, swatches=None):
    """(DomeTexture of a dome's converted texture map (convert.texmaps.TextureGraphIR of kind COLOR, None when it
    converts to nothing), or None: the World keeps the color, issues). material_graph (reader.materials
    MaterialGraph) reads the map's projection, a parameter a controller holds at frame 0 (params.at_frame_zero; what
    that meets in the issues, a line the conversion gave already not again); swatches: the scene's colors.Swatches
    (None: read from material_graph's scene)."""
    if graph_ir is None:
        return None, [DOME_NO_TEXTURE]
    issues = list(graph_ir.issues)

    def heard(_index, line):
        if line not in issues:
            issues.append(line)
    material_graph = params.at_frame_zero(material_graph, heard) if material_graph is not None else None
    img = graph_ir.root
    if not isinstance(img, texmaps.Image):  # a gamma-off Mix, Composite or CoronaMix is named, not its Decode
        return None, issues + [DOME_ROOT % type(img.input if isinstance(img, texmaps.Decode) else img).__name__]
    m = material_graph.get(img.index) if material_graph is not None else None
    if m is not None:  # the converter names the root's environment mapping: wrong for a material, expected here
        own = tuple("%s %r: environment mapping" % (cls, m.name) for cls in ("Bitmap", "VRayBitmap"))
        issues = [x for x in issues if not x.startswith(own)]
    if img.found is None or m is None:
        return None, issues + [DOME_NOT_FOUND % img.name]
    cid = classids.ClassId(*m.class_id)
    turn = 0.0
    if cid == classids.VRAY_BITMAP:
        kind = m.param(texmaps.VB_MAP_TYPE, 0)
        if kind != VB_SPHERICAL:
            issues.append(DOME_PROJECTION % (img.name, _VB_PROJECTIONS.get(kind, "type %r" % (kind,))))
        h, v = (m.param(pid, 0) for pid in (VB_H_ROTATION, VB_V_ROTATION))
        turn = float(h) if finite(h) else 0.0
        if finite(v) and v != 0:
            issues.append(DOME_VERTICAL % (img.name, math.degrees(v)))
        axial = m.param(VB_AXIAL, 0)
        if finite(axial) and axial != 0:
            issues.append(DOME_AXIAL % (img.name, math.degrees(axial)))
        for pid, what in ((VB_H_FLIP, "horizontal flip"), (VB_V_FLIP, "vertical flip"),
                          (VB_GROUND, "ground projection")):
            if m.param(pid, 0) not in (0, None, False):
                issues.append(DOME_SWITCH % (img.name, what))
    elif cid == classids.CORONA_BITMAP:
        issues.append(DOME_CORONA % img.name)
    else:
        uv = next((p for _s, p in sorted(m.parts.items()) if p.superclass == classids.SC_UVGEN), None)
        env = reader_materials.placement(material_graph.scene, uv.index).env_mapping if uv is not None else None
        if not img.mapping.environment or env != ENV_SPHERICAL:
            issues.append(DOME_PROJECTION % (img.name, _ENV_PROJECTIONS.get(env, "an unknown environment mapping") if
                                             img.mapping.environment else "texture"))
        turn = math.pi / 2.0
        mp = img.mapping
        if (mp.tiling, mp.offset, mp.angle) != ((1.0, 1.0), (0.0, 0.0), (0.0, 0.0, 0.0)):
            issues.append(DOME_PLACEMENT % img.name)
    out = img.output
    amount, shown = 1.0, False
    if out is not None:
        amount = max(0.0, out.amount)
        if out.invert or out.level != 1.0 or out.offset != 0.0:
            issues.append(DOME_OUTPUT % img.name)
    if img.name.lower().endswith(texmaps.FLOAT_IMAGES) \
            and not (swatches if swatches is not None else colors.of_graph(material_graph)).linear:
        img, shown = texmaps.unshown(img), True
        issues.append(DOME_FLOAT_OFF % img.name)
    # a guard: the converter's images always have the color space of their gamma (drawn by it or a Gamma node)
    if img.gamma not in (None, 1.0) and img.colorspace != texmaps.colorspace(texmaps.COLOR, img.gamma):
        issues.append(DOME_GAMMA % (img.name, img.gamma))
    if img.crop is not None:
        issues.append(DOME_CROP % img.name)
    return DomeTexture(img, turn, amount, shown), issues
