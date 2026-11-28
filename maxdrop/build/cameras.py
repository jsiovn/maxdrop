# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender cameras and render settings from convert.cameras descriptions.

    camera = make_camera(cd)            # a Camera datablock: PERSP or ORTHO, sensor fit HORIZONTAL
    applied = set_render(scene, desc, built)   # scene.camera, render size, view exposure: for a file with a camera

One Camera per CameraDescription: the nodes of one camera object share it. sensor_fit HORIZONTAL keeps 3ds Max's
horizontal field of view for any render aspect: Blender's is 2 atan(sensor_width / (2 lens)). Depth of field is on
when the description has a focus distance (dof_distance, with its fstop when given), off otherwise. A camera's
exposure (stops) is also kept as the custom property maxdrop_exposure on the Camera. Clipping is set only when 3ds Max
clips; Blender's own range stays otherwise.

set_render applies only to a file that brings a camera (desc.camera): it makes that camera's object scene.camera and
sets the scene's resolution (at 100 %) and pixel aspect when the file stores them (Blender's are kept otherwise), so
the camera frames what 3ds Max renders. A file without a camera (a model dropped into a scene) leaves the scene's
render settings alone. A pixel aspect below 1 goes to pixel_aspect_y (Blender takes both at 1 or more). The scene
camera's exposure becomes scene.view_settings.exposure (Blender has one per scene); a scene camera without one leaves
it.
"""
import bpy


def make_camera(cd):
    """A Camera named after the description's first node."""
    camera = bpy.data.cameras.new(cd.name)
    camera.type = cd.kind
    camera.sensor_fit = 'HORIZONTAL'
    camera.sensor_width = cd.sensor
    camera.lens = cd.lens
    camera.shift_x = cd.shift_x
    camera.shift_y = cd.shift_y
    if cd.kind == 'ORTHO':
        camera.ortho_scale = cd.ortho_scale
    if cd.clip_start is not None:
        camera.clip_start = cd.clip_start
        camera.clip_end = cd.clip_end
    camera.dof.use_dof = cd.dof_distance is not None
    if cd.dof_distance is not None:
        camera.dof.focus_distance = cd.dof_distance
        if cd.fstop is not None:
            camera.dof.aperture_fstop = cd.fstop
    if cd.exposure is not None:
        camera["maxdrop_exposure"] = cd.exposure
    return camera


def set_render(scene, desc, built):
    """scene.camera = the object of desc.camera, the render size and pixel aspect of desc.render and the view exposure
    of that camera; nothing without a scene camera. Whether it applied them."""
    ob = built.objects.get(desc.camera) if desc.camera is not None else None
    if ob is None or ob.type != 'CAMERA':
        return False
    scene.camera = ob
    render = desc.render
    if render is not None and render.width is not None:
        scene.render.resolution_x = render.width
        scene.render.resolution_y = render.height
        scene.render.resolution_percentage = 100
    if render is not None and render.pixel_aspect is not None:
        aspect = render.pixel_aspect
        scene.render.pixel_aspect_x = aspect if aspect >= 1.0 else 1.0
        scene.render.pixel_aspect_y = 1.0 if aspect >= 1.0 else 1.0 / aspect
    exposure = ob.data.get("maxdrop_exposure")
    if exposure is not None:
        scene.view_settings.exposure = exposure
    return True
