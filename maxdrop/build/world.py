# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scene's World from a dome light (convert.lights DomeDescription).

    world = make_world(dd, image, strength, axis)   # a new World; image: the bpy Image of dd.texture, or None

The World's Background has the dome's color, or with a texture an Environment Texture of its image, and the
strength dd.radiance x strength (the import's Light Strength) x the texture's amount; an image the converter made
Linear Rec.709 for its gamma gets a Gamma node, as a material's image does (texmaps.drawn_gamma). Directions:
Texture Coordinate Generated is the direction in Blender's world; axis (a 3x3 mathutils Matrix: the import's axis
conversion, file to Blender) and dd.rotation take it into the dome's frame. A hemisphere multiplies the strength by (local Z > 0). The
texture is looked up as V-Ray does (convert.lights, "A dome light"): V-Ray's u = 0.5 + (phi + turn) / 2 pi runs the
other way round from Blender's equirectangular u = 0.5 - phi / 2 pi, so the direction is mirrored in Y and turned
by -turn about Z: a Mapping node of scale (1, -1, 1), whose rotation R' = Rz(-turn) F T F (F the mirror, T the
direction's turn into the texture's frame) makes R' (F d) = Rz(-turn) F T d (checked against V-Ray renders at
+-X, +-Y, +-20 degrees). Camera, diffuse and glossy rays see it as the dome says (World.cycles_visibility: Cycles).
A texture whose values a gamma-off scene shows decoded (DomeTexture.shown): camera rays see a second Background,
the sRGB curve of the texture times the strength (SRGB_A x + SRGB_B in a Vector Math node, then a Gamma node of
SRGB_POWER: the curve's power segment, within 0.001 of it below its knee) at strength 1, picked by a Mix Shader on
the Light Path's Is Camera Ray; every other ray (reflections too) the texture as it is (maxdrop-6n0.6.21). An
untextured dome of a gamma-off scene (DomeDescription.shown) alike, its camera color computed exactly.
"""
import bpy
from mathutils import Matrix

from .. import compat
from ..convert import colors
from ..convert import texmaps as tx

X_STEP = 220.0
MIRROR = Matrix.Diagonal((1.0, -1.0, 1.0))
SRGB_A, SRGB_B, SRGB_POWER = 1.0 / 1.055, 0.055 / 1.055, 2.4  # the sRGB curve above its knee: (a x + b) ^ power
CAMERA_BACKGROUND = "Camera Background"  # the Background camera rays see (DomeTexture.shown)


def _turn_z(angle):
    return Matrix.Rotation(angle, 3, 'Z')


def make_world(dd, image=None, strength=1.0, axis=None):
    """A new World named after the dome (not assigned to any scene)."""
    world = bpy.data.worlds.new(dd.name or "Dome")
    tree = compat.node_tree(world)
    nodes, links = tree.nodes, tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputWorld")
    out.location = (X_STEP, 0.0)
    bg = nodes.new("ShaderNodeBackground")
    links.new(bg.outputs["Background"], out.inputs["Surface"])
    dome = Matrix(dd.rotation)  # the dome's axes in the file's frame
    to_file = (axis if axis is not None else Matrix.Identity(3)).transposed()  # a rotation: its inverse
    texture = dd.texture if image is not None else None
    value = dd.radiance * strength * (texture.amount if texture is not None else 1.0)
    coords = None
    if texture is not None or dd.hemisphere:
        coords = nodes.new("ShaderNodeTexCoord")
        coords.location = (-4 * X_STEP, 0.0)
    if texture is not None:
        frame = (dome.transposed() if dd.locked else Matrix.Identity(3)) @ to_file
        mapping = nodes.new("ShaderNodeMapping")
        mapping.vector_type = 'VECTOR'
        mapping.location = (-3 * X_STEP, 0.0)
        mapping.inputs["Scale"].default_value = (1.0, -1.0, 1.0)
        mapping.inputs["Rotation"].default_value = (_turn_z(-texture.turn) @ MIRROR @ frame @ MIRROR).to_euler('XYZ')
        env = nodes.new("ShaderNodeTexEnvironment")
        env.location = (-2 * X_STEP, 0.0)
        env.image = image
        links.new(coords.outputs["Generated"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], env.inputs["Vector"])
        color = env.outputs["Color"]
        gamma = tx.drawn_gamma(texture.image)
        if gamma is not None:
            power = nodes.new("ShaderNodeGamma")
            power.location = (-X_STEP, X_STEP)
            power.inputs["Gamma"].default_value = gamma
            links.new(color, power.inputs["Color"])
            color = power.outputs["Color"]
        links.new(color, bg.inputs["Color"])
        if texture.shown:
            _camera_split(nodes, links, out, bg, color, value)
    else:
        bg.inputs["Color"].default_value = tuple(dd.color) + (1.0,)
        if dd.shown:
            _camera_split(nodes, links, out, bg, tuple(dd.color), value)
    if dd.hemisphere:
        up = nodes.new("ShaderNodeMapping")
        up.vector_type = 'VECTOR'
        up.location = (-3 * X_STEP, -2 * X_STEP)
        up.inputs["Rotation"].default_value = (dome.transposed() @ to_file).to_euler('XYZ')
        split = nodes.new("ShaderNodeSeparateXYZ")
        split.location = (-2 * X_STEP, -2 * X_STEP)
        above = nodes.new("ShaderNodeMath")
        above.operation = 'GREATER_THAN'
        above.location = (-X_STEP, -2 * X_STEP)
        above.inputs[1].default_value = 0.0
        times = nodes.new("ShaderNodeMath")
        times.operation = 'MULTIPLY'
        times.location = (-X_STEP, -X_STEP)
        times.inputs[1].default_value = value
        links.new(coords.outputs["Generated"], up.inputs["Vector"])
        links.new(up.outputs["Vector"], split.inputs["Vector"])
        links.new(split.outputs["Z"], above.inputs[0])
        links.new(above.outputs["Value"], times.inputs[0])
        links.new(times.outputs["Value"], bg.inputs["Strength"])
        seen = nodes.get(CAMERA_BACKGROUND)
        if seen is not None:  # the camera's sky has the value in its color: the mask alone
            links.new(above.outputs["Value"], seen.inputs["Strength"])
    else:
        bg.inputs["Strength"].default_value = value
    rays = getattr(world, "cycles_visibility", None)  # Cycles' property group: not there without Cycles
    if rays is not None:
        rays.camera, rays.diffuse, rays.glossy = dd.camera, dd.diffuse, dd.glossy
    return world


def _camera_split(nodes, links, out, bg, color, value):
    """The World's output a Mix Shader of bg (every ray but the camera's) and a Background named CAMERA_BACKGROUND
    of color x value through the sRGB curve (camera rays) at strength 1. color: a socket (the texture's), or the
    dome's linear color (a swatch made so by the sRGB curve: as stored again first, then exact)."""
    seen = nodes.new("ShaderNodeBackground")
    seen.name = seen.label = CAMERA_BACKGROUND
    seen.location = (0.0, 2 * X_STEP)
    if isinstance(color, tuple):
        seen.inputs["Color"].default_value = tuple(
            colors.srgb_to_linear(colors.linear_to_srgb(c) * value) for c in color[:3]) + (1.0,)
    else:
        curve = nodes.new("ShaderNodeVectorMath")
        curve.operation = 'MULTIPLY_ADD'
        curve.location = (-X_STEP, 3 * X_STEP)
        links.new(color, curve.inputs[0])
        curve.inputs[1].default_value = (value * SRGB_A,) * 3
        curve.inputs[2].default_value = (SRGB_B,) * 3
        power = nodes.new("ShaderNodeGamma")
        power.location = (0.0, 3 * X_STEP)
        links.new(curve.outputs["Vector"], power.inputs["Color"])
        power.inputs["Gamma"].default_value = SRGB_POWER
        links.new(power.outputs["Color"], seen.inputs["Color"])
    seen.inputs["Strength"].default_value = 1.0
    path = nodes.new("ShaderNodeLightPath")
    path.location = (0.0, 4 * X_STEP)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (X_STEP, X_STEP)
    links.new(path.outputs["Is Camera Ray"], mix.inputs[0])
    links.new(bg.outputs["Background"], mix.inputs[1])
    links.new(seen.outputs["Background"], mix.inputs[2])
    out.location = (2 * X_STEP, 0.0)
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
