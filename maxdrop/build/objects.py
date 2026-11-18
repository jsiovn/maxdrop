# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender objects and meshes from a convert.scene.SceneDescription.

    built = build(desc, collection)
    built.objects[node.index]           # the Object of each node
    built.meshes[node.mesh]             # the Mesh, one per MeshDescription: instances share it
    built.curves[node.curve]            # the Curve of a shape node, one per CurveDescription (build.curves)
    built.lights[node.light]            # the Light of a light node, one per LightDescription (build.lights)
    built.roots()                       # every object without a parent, the shear helper included
    built = build(desc, collection, slots=assign(...), material=make)   # with material slots
    built.materials[ir.index]           # the Material make(ir) returned, once per Max material
                                        # (make: build.materials.MaterialBuilder().make)

Meshes are made with vertices.add / loops.add / polygons.add and foreach_set, then the edges are computed from the
polygons. Flat faces and sharp edges go to the sharp_face and sharp_edge attributes, which Blender 4.1 and later
use in place of auto smooth: the same result on 4.2, 4.5 and 5.2 without a modifier. Each UV layer is written
through its own layer, not the active one; Blender keeps at most MAX_UV_LAYERS, the channels past it are counted
in dropped_uv_layers. Without slots, the faces keep 3ds Max's material IDs and get no material slot. With slots
(convert.materials.assign: {mesh key: MeshSlots}), each face goes to its slot; a slot holds the same material for
every object sharing the mesh, or each object's own (the slot linked to the object); an empty slot holds none.

Objects are made in walk order, so a parent exists before its children. The parent is set by node index with an
identity matrix_parent_inverse and matrix_basis = the node's local matrix, so Blender's world matrix is 3ds Max's
node transform. Blender decomposes matrix_basis into location, rotation and scale, which drops a shear (a scale
along a rotated axis, node.sheared): for such a node the rest, local @ basis^-1, goes into matrix_parent_inverse,
so world = parent world @ local again and the children inherit the shear. Blender ignores matrix_parent_inverse
without a parent, so a sheared top-level node gets one: the empty SHEAR_HELPER at the identity, one per build,
made only when needed and listed in built.helpers. It is not baked into the mesh instead because most such nodes
are empties (placeholders) and the object's own world matrix would stay off.
An EMPTY node becomes a plain-axes empty with the custom property maxdrop_class; a CURVE node an object of its
Curve, which gets no material; a LIGHT node an object of its Light (build.lights, power times light_strength), with
the light's object flags.

With collections (build.collections.make), each object goes into its layer's collection, else into collection.
A node hidden in 3ds Max gets hide_viewport and is hidden in view_layer (hide_set), one that does not render
hide_render, a frozen one hide_select.

    kept = track_targets(desc, built)   # "Keep Targets": a Track To to each look-at's target, [(node, reason)]

A node aimed by a Look At controller is built with the rotation 3ds Max computed (convert.scene); track_targets
adds a Track To constraint (named TRACK_TO_NAME) aiming it at its target's object instead, so it follows when the
target moves. The ones no Track To can aim as 3ds Max does keep the baked rotation and are returned with the reason.
"""
import bpy
from mathutils import Matrix

from ..convert import scene as convert_scene
from . import curves as build_curves
from . import lights as build_lights

MAX_UV_LAYERS = 8
CLASS_PROPERTY = "maxdrop_class"
HELPER_PROPERTY = "maxdrop_helper"
SHEAR_HELPER = "MaxDrop Shear"
TRACK_TO_NAME = "MaxDrop Target"


class Built:
    """objects {node index: Object}, meshes {mesh key: Mesh}, curves {curve key: Curve}, lights {light key:
    Light}, dropped_uv_layers
    (channels Blender had no room for), helpers (objects that are no node: the shear helper), materials {Max
    material object index: Material}."""
    __slots__ = ("objects", "meshes", "curves", "lights", "dropped_uv_layers", "helpers", "materials")

    def __init__(self):
        self.objects, self.meshes, self.dropped_uv_layers, self.helpers = {}, {}, 0, []
        self.curves, self.materials, self.lights = {}, {}, {}

    def roots(self):
        """The objects without a parent, helpers included: what a change of axes turns."""
        return [ob for ob in list(self.objects.values()) + self.helpers if ob.parent is None]


def _keep_shear(ob, local):
    """Give ob (parented, matrix_basis already set to local) the shear Blender's decomposition of matrix_basis
    dropped: matrix_parent_inverse = local @ basis^-1, in doubles. A basis that cannot be inverted (a zero scale)
    becomes the identity, and local all of the parent inverse."""
    import numpy
    m = numpy.array(local, dtype=numpy.float64)
    basis = numpy.array(ob.matrix_basis, dtype=numpy.float64)
    if abs(numpy.linalg.det(basis[:3, :3])) < 1e-12:
        ob.matrix_basis = Matrix.Identity(4)
        rest = m
    else:
        rest = m @ numpy.linalg.inv(basis)
    ob.matrix_parent_inverse = Matrix(rest.tolist())


def _shear_helper(built, collection):
    if not built.helpers:
        helper = bpy.data.objects.new(SHEAR_HELPER, None)
        helper.empty_display_type = 'PLAIN_AXES'
        helper[HELPER_PROPERTY] = "shear"
        collection.objects.link(helper)
        built.helpers.append(helper)
    return built.helpers[0]


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


def make_mesh(md, indices=None):
    """A Mesh of a MeshDescription; the number of UV layers that did not fit. indices: each face's material index,
    md.material_indices when None."""
    import numpy
    mesh = bpy.data.meshes.new(md.name)
    mesh.vertices.add(len(md.positions))
    mesh.loops.add(len(md.loop_vertices))
    mesh.polygons.add(len(md.loop_starts))
    mesh.vertices.foreach_set("co", numpy.ascontiguousarray(md.positions, dtype=numpy.float32).ravel())
    mesh.loops.foreach_set("vertex_index", numpy.ascontiguousarray(md.loop_vertices, dtype=numpy.int32))
    mesh.polygons.foreach_set("loop_start", numpy.ascontiguousarray(md.loop_starts, dtype=numpy.int32))
    mesh.polygons.foreach_set("material_index", numpy.ascontiguousarray(
        md.material_indices if indices is None else indices, dtype=numpy.int32))
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


def _material(built, ir, make):
    """The Material of a MaterialIR (None for an empty slot or without make), made once per Max material."""
    if ir is None or make is None:
        return None
    if ir.index not in built.materials:
        built.materials[ir.index] = make(ir)
    return built.materials[ir.index]


def _slots(built, slots, make):
    """The material slots of each mesh: on the mesh when every user has the same material there, else empty on
    the mesh and linked to each object with its own."""
    for key, plan in slots.items():
        mesh = built.meshes.get(key)
        if mesh is None:
            continue
        for s, irs in enumerate(plan.slots):
            if all(ir is irs[0] for ir in irs):
                mesh.materials.append(_material(built, irs[0], make))
                continue
            mesh.materials.append(None)
            for node, ir in zip(plan.users, irs):
                ob = built.objects.get(node)
                if ob is not None:
                    slot = ob.material_slots[s]
                    slot.link = 'OBJECT'
                    slot.material = _material(built, ir, make)


def build(desc, collection, collections=None, view_layer=None, slots=None, material=None, light_strength=1.0):
    """Every node of desc as an Object linked to collection, or to its layer's collection of collections; the
    Built result. view_layer: where a hidden node is hidden (hide_set), the context's when None. slots: {mesh key:
    convert.materials.MeshSlots}, each face's slot and each slot's materials; material: make(MaterialIR) -> a
    Material, called once per Max material (no material in the slots without it); light_strength: the factor on
    every light's power."""
    built = Built()
    slots = slots or {}
    for key, md in desc.meshes.items():
        plan = slots.get(key)
        built.meshes[key], dropped = make_mesh(md, plan.indices if plan is not None else None)
        built.dropped_uv_layers += dropped
    for key, cd in desc.curves.items():
        built.curves[key] = build_curves.make_curve(cd)
    for key, ld in desc.lights.items():
        built.lights[key] = build_lights.make_light(ld, light_strength)
    identity = Matrix.Identity(4)
    hidden = []
    for node in desc.nodes:
        data = (built.meshes[node.mesh] if node.kind == convert_scene.MESH else
                built.curves[node.curve] if node.kind == convert_scene.CURVE else
                built.lights[node.light] if node.kind == convert_scene.LIGHT else None)
        ob = bpy.data.objects.new(node.name, data)
        (collections.of(node) if collections is not None else collection).objects.link(ob)
        if data is None:
            ob.empty_display_type = 'PLAIN_AXES'
            ob[CLASS_PROPERTY] = node.class_name
        parent = built.objects.get(node.parent) if node.parent is not None else None
        if parent is None and node.sheared:
            parent = _shear_helper(built, collection)
        if parent is not None:
            ob.parent = parent
            ob.matrix_parent_inverse = identity
        ob.matrix_basis = Matrix(node.matrix)
        if parent is not None and node.sheared:
            _keep_shear(ob, node.matrix)
        ob.hide_render = not node.renderable
        ob.hide_select = node.frozen
        if node.hidden:
            ob.hide_viewport = True
            hidden.append(ob)
        if node.kind == convert_scene.LIGHT:
            build_lights.set_object(ob, desc.lights[node.light])
        built.objects[node.index] = ob
    _slots(built, slots, material)
    view_layer = view_layer or bpy.context.view_layer
    for ob in hidden:
        try:
            ob.hide_set(True, view_layer=view_layer)
        except RuntimeError:  # not in that view layer (collection not linked there): hide_viewport still holds
            pass
    return built


def track_targets(desc, built):
    """A Track To constraint on the object of every node with a look_at, aiming at its target's object; the
    [(node index, reason)] of those left with their baked rotation."""
    kept = []
    for node in desc.nodes:
        look = node.look_at
        if look is None:
            continue
        ob, target = built.objects.get(node.index), built.objects.get(look.target)
        if ob is None or target is None or target is ob:
            continue
        if look.track is None:
            kept.append((node.index, look.reason))
            continue
        c = ob.constraints.new('TRACK_TO')
        c.name = TRACK_TO_NAME
        c.target = target
        c.track_axis = look.track
        c.up_axis = look.up
        c.use_target_z = look.target_z
    return kept
