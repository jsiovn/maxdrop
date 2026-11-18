# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender lights from convert.lights LightDescriptions.

    light = make_light(ld, strength)    # a Light datablock: AREA (RECTANGLE or DISK), POINT, SPOT or SUN
    set_object(ob, ld)                  # the flags of one object of it: off, invisible, ray visibility

One Light per LightDescription: the nodes of one light object share it. Its energy is the description's power in
watts (a sun's strength in W/m^2) times strength, the import's Light Strength (the calibration against V-Ray is in
docs/FORMAT.md, "VRayLight" and "Standard and photometric lights"). A spot gets its cone and radius, a sun its
angle.
Light.diffuse_factor and specular_factor take the affect diffuse / specular contributions (EEVEE only). Per object:
a light that is off is hidden in the viewport and in renders; the camera sees the light unless it is invisible
(Blender makes a light object unseen by the camera, V-Ray the other way round); diffuse and glossy rays see it as
the description says (Object.visible_camera / visible_diffuse / visible_glossy, the same on 4.2 and 5.2).
"""
import bpy


def make_light(ld, strength=1.0):
    """A Light named after the description's first node."""
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
    light.color = ld.color
    light.diffuse_factor = ld.diffuse
    light.specular_factor = ld.specular
    return light


def set_object(ob, ld):
    """The per-object flags of an object of ld's light."""
    if not ld.on:
        ob.hide_viewport = True
        ob.hide_render = True
    ob.visible_camera = not ld.invisible  # a Blender light object starts unseen by the camera, a V-Ray light seen
    ob.visible_diffuse = ld.diffuse_rays
    ob.visible_glossy = ld.glossy_rays
