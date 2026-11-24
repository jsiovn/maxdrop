# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender modifiers on the built objects, from the convert.modifiers ModifierDescriptions of a SceneDescription.

    add(desc, built)                    # after build.objects.build(desc, ...): every node.converted on its object

Each node's converted modifiers are added in their order (3ds Max's, bottom first, but a Symmetry convert.scene moves
below a Shell whose rim lies on its plane), named as in 3ds Max, with their settings; a setting this Blender lacks
is skipped and counted in the result. A Mirror whose plane is not the object's own gets an empty as its mirror
object: a child of the object (identity parent inverse, so it follows the
object), placed at the description's frame (a shear kept in its parent inverse, as build.objects keeps a node's),
in the object's collection, hidden and frozen with the object, not rendered. It is no node and no root: not in
built.objects or built.helpers. A mesh whose description asks for creases (a converted smoother separates by
smoothing groups) gets crease_edge 1.0 on its sharp edges, the generic attribute Blender 4.0 and later read for edge
creases; not on its open edges (one face): those are sharp only for a Shell's rim (convert.scene), and a crease on a
boundary would change how Subdivision Surface rounds it.
"""
import bpy
from mathutils import Matrix

from ..convert import scene as convert_scene
from .objects import HELPER_PROPERTY, _keep_shear

MIRROR_HELPER = "mirror"
CREASE_ATTRIBUTE = "crease_edge"
EMPTY_SIZE = 0.25


def _crease(mesh):
    import numpy
    sharp = mesh.attributes.get("sharp_edge")
    flags = numpy.zeros(len(mesh.edges), dtype=bool)
    if sharp is not None and len(flags):
        sharp.data.foreach_get("value", flags)
        if flags.any():
            edge_of_loop = numpy.empty(len(mesh.loops), dtype=numpy.int32)
            mesh.loops.foreach_get("edge_index", edge_of_loop)
            flags &= numpy.bincount(edge_of_loop, minlength=len(flags)) != 1
    crease = mesh.attributes.get(CREASE_ATTRIBUTE)
    if crease is None:
        crease = mesh.attributes.new(CREASE_ATTRIBUTE, 'FLOAT', 'EDGE')
    crease.data.foreach_set("value", flags.astype(numpy.float32))


def _mirror_object(ob, frame):
    empty = bpy.data.objects.new(ob.name + " Mirror", None)
    empty.empty_display_type = 'ARROWS'
    empty.empty_display_size = EMPTY_SIZE
    empty[HELPER_PROPERTY] = MIRROR_HELPER
    for col in ob.users_collection:
        col.objects.link(empty)
    empty.parent = ob
    empty.matrix_parent_inverse = Matrix.Identity(4)
    empty.matrix_basis = Matrix(frame)
    rows = tuple(tuple(frame[c][r] for c in range(4)) for r in range(4))  # sheared() reads row vectors
    if convert_scene.sheared(rows):
        _keep_shear(empty, frame)
    empty.hide_render = True
    empty.hide_viewport = ob.hide_viewport
    empty.hide_select = ob.hide_select
    return empty


def add(desc, built):
    """Add every node's converted modifiers to its object in built (a build.objects.Built); the number of settings
    skipped because this Blender has no such attribute."""
    skipped = 0
    for node in desc.nodes:
        ob = built.objects.get(node.index) if node.converted else None
        if ob is None:
            continue
        for md in node.converted:
            mod = ob.modifiers.new(md.name, md.kind)
            for attr, value in md.settings:
                if hasattr(mod, attr):
                    setattr(mod, attr, value)
                else:
                    skipped += 1
            mod.show_viewport = md.show_viewport
            if md.mirror is not None:
                mod.mirror_object = _mirror_object(ob, md.mirror)
    for key, md in desc.meshes.items():
        mesh = built.meshes.get(key)
        if md.creases and mesh is not None:
            _crease(mesh)
    return skipped
