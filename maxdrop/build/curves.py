# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender curves from the shapes of a convert.scene.SceneDescription.

    curve = make_curve(cd, collection)  # a Curve datablock of a CurveDescription, its section in collection
    set_material_indices(curve, indices)  # each spline on its material slot, once the slots exist

One Bezier spline per SplineDescription, its points and handles set with foreach_set, the handles FREE at Max's
in and out vectors (convert.scene has already put a straight segment's handles on its chord), so each segment is
the cubic 3ds Max draws. The curve is 3D and
FULL (Blender's default for 3D) so a bevel is a closed tube; resolution_u is the description's resolution;
bevel_depth and bevel_resolution give a renderable shape its thickness, a shape that does not render in 3ds Max
has none (a curve without a bevel does not render in Blender either). A bevel's caps are filled, round or a
section, as 3ds Max caps the render mesh of an open spline (a closed spline has no ends to cap). Each spline's
material_index is set from the material plan (convert.materials.MeshSlots.indices, one per spline) after the curve
has its slots: Blender clamps a spline's index to the curve's materials, so a curve without slots keeps every spline
at 0.

A rectangular section (cd.section) is a bevel object: a closed 2D poly curve "<name> section" through the four
corners, no fill, its object hidden in the viewport and the render, not selectable, marked maxdrop_helper =
"section" and linked into collection. A bevel object is no user of its object: an unlinked one is dropped when
the file is saved, and the import's cleanup removes what is in its collections.
"""
import bpy

HELPER_PROPERTY = "maxdrop_helper"  # build.objects' name for objects that are no node
SECTION = "section"


def make_curve(cd, collection):
    """A Curve datablock of a CurveDescription; its section object, if any, linked into collection (the import's,
    which its cleanup removes)."""
    curve = bpy.data.curves.new(cd.name, 'CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = max(1, min(int(cd.resolution), 1024))
    curve.bevel_depth = cd.bevel_depth
    curve.bevel_resolution = max(0, min(int(cd.bevel_resolution), 32))
    for sd in cd.splines:
        spline = curve.splines.new('BEZIER')
        points = spline.bezier_points
        points.add(len(sd.points) - 1)  # a new spline has one point
        for bp in points:  # before the coordinates: a type change moves AUTO and VECTOR handles
            bp.handle_left_type = bp.handle_right_type = 'FREE'
        for attr, values in (("co", sd.points), ("handle_left", sd.left), ("handle_right", sd.right)):
            points.foreach_set(attr, [c for p in values for c in p])
        spline.use_cyclic_u = sd.cyclic
        spline.resolution_u = curve.resolution_u
    if cd.section:
        curve.bevel_mode = 'OBJECT'
        curve.bevel_object = _section(cd, collection)
    curve.use_fill_caps = bool(cd.section) or cd.bevel_depth > 0  # 3ds Max caps an open spline's render mesh
    return curve


def set_material_indices(curve, indices):
    """Each spline of curve on its slot: indices, one per spline in order (a curve's slots must exist first)."""
    for spline, index in zip(curve.splines, indices):
        spline.material_index = int(index)


def _section(cd, collection):
    name = cd.name + " section"
    profile = bpy.data.curves.new(name, 'CURVE')
    profile.dimensions = '2D'
    profile.fill_mode = 'NONE'
    spline = profile.splines.new('POLY')
    spline.points.add(len(cd.section) - 1)
    spline.points.foreach_set("co", [c for x, y in cd.section for c in (x, y, 0.0, 1.0)])
    spline.use_cyclic_u = True
    ob = bpy.data.objects.new(name, profile)
    ob.hide_viewport = ob.hide_render = ob.hide_select = True
    ob[HELPER_PROPERTY] = SECTION
    collection.objects.link(ob)
    return ob
