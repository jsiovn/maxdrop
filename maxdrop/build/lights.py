# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender lights from convert.lights LightDescriptions.

    light = make_light(ld, strength, texts)   # a Light datablock: AREA (RECTANGLE or DISK), POINT, SPOT or SUN
    set_object(ob, ld)                  # the flags of one object of it: off, invisible, ray visibility

One Light per LightDescription: the nodes of one light object share it. Its energy is the description's power in
watts (a sun's strength in W/m^2) times strength, the import's Light Strength (the calibration against V-Ray is in
docs/FORMAT.md, "VRayLight" and "Standard and photometric lights"). A spot gets its cone and radius, a sun its
angle.
Light.diffuse_factor and specular_factor take the affect diffuse / specular contributions (EEVEE only), use_shadow
the description's shadow switch (Cycles and EEVEE, the same on 4.2 and 5.2). Per object:
a light that is off is hidden in the viewport and in renders; the camera sees the light unless it is invisible
(Blender makes a light object unseen by the camera, V-Ray the other way round); diffuse and glossy rays see it as
the description says (Object.visible_camera / visible_diffuse / visible_glossy, the same on 4.2 and 5.2).
A light with a profile (an IES file, convert.lights: a POINT light) gets a node tree (compat.light_nodes): an IES
Texture node in internal mode, its Text the profile's text, into the Strength of the Emission; its energy is divided
by the gain at which Blender 4.x reads the file (compat.ies_gain). One Text per file: texts, a dict the build keeps
({(file name, text): Text}), gives it to every light of that file. EEVEE ignores a light's nodes and draws the plain
light (measured: docs/FORMAT.md, "The IES Texture node in Blender, measured").
"""
import bpy

from .. import compat


def make_light(ld, strength=1.0, texts=None):
    """A Light named after the description's first node; texts: the build's Texts of IES files (a new dict when
    None)."""
    light = bpy.data.lights.new(ld.name, ld.kind)
    if ld.kind == 'AREA':
        light.shape = ld.shape
        light.size = ld.size
        if ld.shape == 'RECTANGLE':
            light.size_y = ld.size_y
    elif ld.kind == 'SUN':
        light.angle = ld.angle
    else:
        light.shadow_soft_size = ld.radius
        if ld.kind == 'SPOT':
            light.spot_size = ld.spot_size
            light.spot_blend = ld.spot_blend
    light.energy = ld.power * strength
    if ld.profile is not None:
        light.energy /= compat.ies_gain(ld.profile.photometry.horizontal)
        tree, emission, _output = compat.light_nodes(light)
        node = tree.nodes.new("ShaderNodeTexIES")
        node.mode = 'INTERNAL'
        node.ies = _text(ld.profile, {} if texts is None else texts)
        tree.links.new(node.outputs[0], emission.inputs["Strength"])  # Fac on 4.x, Factor on 5.x
    light.color = ld.color
    light.diffuse_factor = ld.diffuse
    light.specular_factor = ld.specular
    light.use_shadow = ld.shadow
    return light


def _text(profile, texts):
    """The Text of profile's file in texts, made once. A NUL would end the Text (a C string): it becomes a space."""
    key = (profile.file, profile.text)
    text = texts.get(key)
    if text is None:
        text = texts[key] = bpy.data.texts.new(profile.file or "IES")
        text.from_string(profile.text.replace("\0", " "))
    return text


def set_object(ob, ld):
    """The per-object flags of an object of ld's light."""
    if not ld.on:
        ob.hide_viewport = True
        ob.hide_render = True
    ob.visible_camera = not ld.invisible  # a Blender light object starts unseen by the camera, a V-Ray light seen
    ob.visible_diffuse = ld.diffuse_rays
    ob.visible_glossy = ld.glossy_rays
