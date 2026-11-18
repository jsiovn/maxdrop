# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender cameras and render settings from convert.cameras descriptions.

    camera = make_camera(cd)            # a Camera datablock: PERSP or ORTHO, sensor fit HORIZONTAL
    set_render(scene, desc, built)      # the render size and scene.camera of a convert.scene.SceneDescription

One Camera per CameraDescription: the nodes of one camera object share it. sensor_fit HORIZONTAL keeps 3ds Max's
horizontal field of view for any render aspect: Blender's is 2 atan(sensor_width / (2 lens)). Depth of field stays
off (convert.cameras names it in the report). Clipping is set only when 3ds Max clips; Blender's own range stays
otherwise.

set_render sets the scene's resolution (at 100 %) and pixel aspect when the file stores them (Blender's are kept
otherwise) and makes the scene camera's object scene.camera. A pixel aspect below 1 goes to pixel_aspect_y (Blender
takes both at 1 or more).
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
    camera.dof.use_dof = False
    return camera


def set_render(scene, desc, built):
    """The render size and pixel aspect of desc.render, and scene.camera = the object of desc.camera."""
    render = desc.render
    if render is not None and render.width is not None:
        scene.render.resolution_x = render.width
        scene.render.resolution_y = render.height
        scene.render.resolution_percentage = 100
    if render is not None:
        aspect = render.pixel_aspect
        scene.render.pixel_aspect_x = aspect if aspect >= 1.0 else 1.0
        scene.render.pixel_aspect_y = 1.0 if aspect >= 1.0 else 1.0 / aspect
    ob = built.objects.get(desc.camera) if desc.camera is not None else None
    if ob is not None and ob.type == 'CAMERA':
        scene.camera = ob
