# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender curves from the shapes of a convert.scene.SceneDescription.

    curve = make_curve(cd)              # a Curve datablock of a CurveDescription

One Bezier spline per SplineDescription, its handles FREE at Max's in and out vectors (convert.scene has already
put a straight segment's handles on its chord), so each segment is the cubic 3ds Max draws. The curve is 3D and
FULL (Blender's default for 3D) so a bevel is a closed tube; resolution_u is the description's resolution;
bevel_depth and bevel_resolution give a renderable shape its thickness, a shape that does not render in 3ds Max
has none (a curve without a bevel does not render in Blender either).
"""
import bpy


def make_curve(cd):
    """A Curve datablock of a CurveDescription."""
    curve = bpy.data.curves.new(cd.name, 'CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = max(1, min(int(cd.resolution), 1024))
    curve.bevel_depth = cd.bevel_depth
    curve.bevel_resolution = max(0, min(int(cd.bevel_resolution), 32))
    for sd in cd.splines:
        spline = curve.splines.new('BEZIER')
        points = spline.bezier_points
        points.add(len(sd.points) - 1)  # a new spline has one point
        for bp, co, left, right in zip(points, sd.points, sd.left, sd.right):
            bp.handle_left_type = bp.handle_right_type = 'FREE'
            bp.co, bp.handle_left, bp.handle_right = co, left, right
        spline.use_cyclic_u = sd.cyclic
        spline.resolution_u = curve.resolution_u
    return curve
