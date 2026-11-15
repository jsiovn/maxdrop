# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender objects and meshes from a convert.scene.SceneDescription.

    built = build(desc, collection)
    built.objects[node.index]           # the Object of each node
    built.meshes[node.mesh]             # the Mesh, one per MeshDescription: instances share it

Meshes are made with vertices.add / loops.add / polygons.add and foreach_set, then the edges are computed from the
polygons. Flat faces and sharp edges go to the sharp_face and sharp_edge attributes, which Blender 4.1 and later
use in place of auto smooth: the same result on 4.2, 4.5 and 5.2 without a modifier. Each UV layer is written
through its own layer, not the active one; Blender keeps at most MAX_UV_LAYERS, the channels past it are counted
in dropped_uv_layers. Material indices are set without material slots (those come with the materials).

Objects are made in walk order, so a parent exists before its children. The parent is set by node index with an
identity matrix_parent_inverse and matrix_basis = the node's local matrix, so Blender's world matrix is 3ds Max's
node transform. A shear inside one local matrix (a scale along a rotated axis) is not kept, since Blender
decomposes matrix_basis; convert reports it.
An EMPTY node becomes a plain-axes empty with the custom property maxdrop_class.

With collections (build.collections.make), each object goes into its layer's collection, else into collection.
A node hidden in 3ds Max gets hide_viewport and is hidden in view_layer (hide_set), one that does not render
hide_render, a frozen one hide_select.
"""
import bpy
from mathutils import Matrix

from ..convert import scene as convert_scene

MAX_UV_LAYERS = 8
CLASS_PROPERTY = "maxdrop_class"


class Built:
    """objects {node index: Object}, meshes {mesh key: Mesh}, dropped_uv_layers (channels Blender had no room
    for)."""
    __slots__ = ("objects", "meshes", "dropped_uv_layers")

    def __init__(self):
        self.objects, self.meshes, self.dropped_uv_layers = {}, {}, 0


def _attribute(mesh, name, domain):
    attr = mesh.attributes.get(name)
    if attr is None:
        attr = mesh.attributes.new(name, 'BOOLEAN', domain)
    return attr


def _sharp_edge_flags(mesh, pairs):
    """One bool per Blender edge: whether its vertex pair is in pairs (int32 (E, 2), sorted)."""
    import numpy
    edges = numpy.empty(len(mesh.edges) * 2, dtype=numpy.int32)
    mesh.edges.foreach_get("vertices", edges)
    edges = edges.reshape(-1, 2).astype(numpy.int64)
    n = len(mesh.vertices)
    keys = numpy.minimum(edges[:, 0], edges[:, 1]) * n + numpy.maximum(edges[:, 0], edges[:, 1])
    pairs = numpy.asarray(pairs, dtype=numpy.int64).reshape(-1, 2)
    return numpy.isin(keys, pairs[:, 0] * n + pairs[:, 1])


def make_mesh(md):
    """A Mesh of a MeshDescription; the number of UV layers that did not fit."""
    import numpy
    mesh = bpy.data.meshes.new(md.name)
    mesh.vertices.add(len(md.positions))
    mesh.loops.add(len(md.loop_vertices))
    mesh.polygons.add(len(md.loop_starts))
    mesh.vertices.foreach_set("co", numpy.ascontiguousarray(md.positions, dtype=numpy.float32).ravel())
    mesh.loops.foreach_set("vertex_index", numpy.ascontiguousarray(md.loop_vertices, dtype=numpy.int32))
    mesh.polygons.foreach_set("loop_start", numpy.ascontiguousarray(md.loop_starts, dtype=numpy.int32))
    mesh.polygons.foreach_set("material_index", numpy.ascontiguousarray(md.material_indices, dtype=numpy.int32))
    mesh.update(calc_edges=True)
    _attribute(mesh, "sharp_face", 'FACE').data.foreach_set("value", numpy.asarray(md.sharp_faces, dtype=bool))
    _attribute(mesh, "sharp_edge", 'EDGE').data.foreach_set("value", _sharp_edge_flags(mesh, md.sharp_edges))
    dropped = 0
    for name, uv in md.uv_layers:
        layer = mesh.uv_layers.new(name=name, do_init=False) if len(mesh.uv_layers) < MAX_UV_LAYERS else None
        if layer is None:
            dropped += 1
            continue
        layer.data.foreach_set("uv", numpy.ascontiguousarray(uv, dtype=numpy.float32).ravel())
    mesh.update()
    return mesh, dropped


def build(desc, collection, collections=None, view_layer=None):
    """Every node of desc as an Object linked to collection, or to its layer's collection of collections; the
    Built result. view_layer: where a hidden node is hidden (hide_set), the context's when None."""
    built = Built()
    for key, md in desc.meshes.items():
        built.meshes[key], dropped = make_mesh(md)
        built.dropped_uv_layers += dropped
    identity = Matrix.Identity(4)
    hidden = []
    for node in desc.nodes:
        data = built.meshes[node.mesh] if node.kind == convert_scene.MESH else None
        ob = bpy.data.objects.new(node.name, data)
        (collections.of(node) if collections is not None else collection).objects.link(ob)
        if data is None:
            ob.empty_display_type = 'PLAIN_AXES'
            ob[CLASS_PROPERTY] = node.class_name
        parent = built.objects.get(node.parent) if node.parent is not None else None
        if parent is not None:
            ob.parent = parent
            ob.matrix_parent_inverse = identity
        ob.matrix_basis = Matrix(node.matrix)
        ob.hide_render = not node.renderable
        ob.hide_select = node.frozen
        if node.hidden:
            ob.hide_viewport = True
            hidden.append(ob)
        built.objects[node.index] = ob
    view_layer = view_layer or bpy.context.view_layer
    for ob in hidden:
        try:
            ob.hide_set(True, view_layer=view_layer)
        except RuntimeError:  # not in that view layer (collection not linked there): hide_viewport still holds
            pass
    return built
