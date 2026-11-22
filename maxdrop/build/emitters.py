# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Emissive meshes from convert.lights EmitterDescriptions (VRayLight mesh lights).

    material = make_material(ed, strength)  # an Emission material: ed.radiance x strength, one side or both
    set_object(ob, ed)                      # the flags of one object of it: off, camera, shadow, ray visibility

One Material per EmitterDescription; build.objects gives it to every face of the emitter's mesh. Its Emission
strength is the radiance in W/m^2/sr times strength, the import's Light Strength (Cycles renders an Emission of
strength S as S, as a World; the calibration against V-Ray is in docs/FORMAT.md, "VRayLight"). V-Ray emits a
single-sided mesh light along its faces' normals and shows the other side black (measured): a Mix Shader by
Geometry Backfacing between the Emission and a black Emission (Flip normals: the other way round). A double-sided one
emits on both sides. Per object: off hides it in the viewport and in renders; invisible makes it unseen by the
camera and no shadow caster (V-Ray: a visible mesh light shadows other lights, an invisible one does not; the
node's own Cast Shadows flag is not used, as for any light); diffuse and glossy rays see it as the description says
(Object.visible_*, the same on 4.2 and 5.2).
"""
import bpy

from .. import compat

X_STEP = 220.0


def make_material(ed, strength=1.0):
    """A Material named after the emitter's first node."""
    material = bpy.data.materials.new(ed.name or "Emitter")
    tree = compat.node_tree(material)
    nodes, links = tree.nodes, tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (2 * X_STEP, 0.0)
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = tuple(ed.color) + (1.0,)
    emission.inputs["Strength"].default_value = ed.radiance * strength
    if ed.double_sided:
        links.new(emission.outputs["Emission"], out.inputs["Surface"])
        return material
    dark = nodes.new("ShaderNodeEmission")
    dark.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    dark.inputs["Strength"].default_value = 0.0
    dark.location = (0.0, -X_STEP)
    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = (0.0, 2 * X_STEP)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (X_STEP, 0.0)
    links.new(geometry.outputs["Backfacing"], mix.inputs["Fac"])
    front, back = (dark, emission) if ed.flip else (emission, dark)
    links.new(front.outputs["Emission"], mix.inputs[1])
    links.new(back.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return material


def set_object(ob, ed):
    """The per-object flags of an object of ed's emitter."""
    if not ed.on:
        ob.hide_viewport = True
        ob.hide_render = True
    ob.visible_camera = ed.camera
    ob.visible_shadow = ed.occluder
    ob.visible_diffuse = ed.diffuse_rays
    ob.visible_glossy = ed.glossy_rays
