# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Emitters: a mesh light's source mesh or shape, made as the light's own mesh."""
from ...reader import geometry, shapes
from .. import extrude, lights, modifiers as rules, primitives, uvwmap
from .descriptions import ChunkError, EMITTER, MeshError
from .meshes import _positions, mesh_area, mesh_description, valid_faces
from .nodes import _primitive
from .stack import _class_name, _converted, _Extrusions, _offset, _SPENT_KIND
from .rims import _shading


def _emitter(scene, t, desc, meshes, values, base, node, name, meters, swatches, built, check=None, stacks=None,
             told=None, convert=True, extrusions=None):
    """(the key in desc.meshes of mesh light base's emitter mesh on node, its key in desc.emitters, the converted
    modifiers of its mesh object as on node (ModifierDescriptions, budgeted)), or (None, None, ()) when it has no mesh
    MaxDrop builds (meshes caches the reason, an issue on every node). The mesh is the mesh object's mesh below its
    modifiers (_emitter_mesh) in its object space with the light node's offset baked (V-Ray places it at the light's
    object transform); the modifiers above it are converted with that offset (_converted: told and convert as there;
    their issues as a mesh node's), a converted smoother that separates by smoothing groups creasing the mesh's sharp
    edges (md.creases, as _mapped_mesh does: the shape and so the area depend on it; a smoother's SMOOTH shading and a
    Shell's rim change the shading only, which an emitter does not show). The description's issues, and the line
    naming the modifiers neither evaluated nor converted (but those _converted names), are named on the first
    node. extrusions: as _emitter_mesh's."""
    if base not in meshes:
        meshes[base] = _emitter_mesh(scene, desc, values, node, meters, built, check, stacks, extrusions)
    found = meshes[base]
    if isinstance(found, str):
        desc.issues.append((node, "light: not built: %s" % found))
        return None, None, ()
    mesh_base, data, area, rest, unread = found
    offset = _offset(t, node)
    key = (EMITTER, base, mesh_base, offset)
    md = desc.meshes.get(key)
    if md is None:
        md = desc.meshes[key] = mesh_description(key, name, data, offset, meters, check)
        if md.dropped_faces:
            desc.issues.append((node, "geometry: %d faces with a repeated vertex or doubled, left out"
                                % md.dropped_faces))
    md.users.append(node)
    converted, issues = _converted(scene, rest, meters, offset, set() if told is None else told, convert)
    converted, more = rules.budget(converted, len(md.loop_vertices))
    desc.issues.extend((node, x) for x in issues + more)
    if _shading(converted) == rules.CREASE:
        md.creases = True
    if base not in desc.emitters:
        ed, issues = lights.describe_emitter(base, name, values, swatches, area)
        desc.emitters[base] = ed
        done = {m.index for m in converted}
        left = unread + tuple(_class_name(scene, m.index) or "a modifier" for m in reversed(rest)
                              if m.index not in done and not (convert and rules.is_convertible(m)))
        if left:
            issues.append(lights.EMITTER_MODIFIERS % ", ".join(left))
        desc.issues.extend((node, "light: %s" % x) for x in issues)
    desc.emitters[base].users.append(node)
    return key, base, converted


def _emitter_mesh(scene, desc, values, node, meters, built, check=None, stacks=None, extrusions=None):
    """(mesh base object index, reader MeshData, its object-space area in m^2 (the faces Blender holds), the reader
    Modifiers above it that render (bottom first, its UVW Maps left out: _emitter_rest), the class names of the
    modifiers of a stack the reader cannot read (top first)) of a mesh light's mesh: its own mesh object
    (lights.MESH_OBJECT: what V-Ray's Replace mesh with light keeps), else (none, or not a mesh read here) the object
    of the node its mesh source (parameter 34) names; or why it has none (the own object's reason when both fail).
    The mesh is the object's base mesh (_mesh_of), or its shape under the Extrude right above it (_emitter_shape).
    stacks: the scene's reader.modifiers Modifiers (None: none read, every modifier named); extrusions: the scene's
    _Extrusions, shared with the shape's own nodes (None: one of its own, counting into built)."""
    if extrusions is None:
        extrusions = _Extrusions(scene, desc, {}, built)
    reasons = []
    for obj in (values.get(lights.MESH_OBJECT), _source_object(scene, values.get(lights.P_MESH_SOURCE))):
        if obj is None:
            continue
        found = _emitter_shape(scene, desc, stacks, obj, node, extrusions)
        if found is None:
            found = _mesh_of(scene, desc, obj, node, built, check)
            if not isinstance(found, str):
                found = found + (None,)
        if not isinstance(found, str):
            mesh_base, data, stack, ext = found
            keep = valid_faces(data.loop_vertices, data.loop_starts, data.loop_totals)
            area = mesh_area(data.positions, data.loop_vertices, data.loop_starts, data.loop_totals, keep)
            rest, unread = _emitter_rest(scene, desc, stacks, obj, stack, ext, node)
            return mesh_base, data, area * meters * meters, rest, unread
        reasons.append(found)
    return reasons[0] if reasons else lights.NO_MESH


def _active(stacks, obj):
    """The reader Modifiers of object obj that render, bottom first (ChunkError when its stack cannot be read)."""
    return [m for m in stacks.object_stack(obj).modifiers if m.renders]


def _emitter_rest(scene, desc, stacks, obj, stack, ext, node):
    """(rest, unread) of _emitter_mesh: the modifiers of object obj that render above its mesh (the Extrude ext made
    it, or None), but the UVW Maps (an emitter has no texture), bottom first, and (); or, without stacks or when the
    reader cannot read them (an issue on node), () and the class names of reader Stack stack's modifiers."""
    if stacks is not None:
        try:
            active = _active(stacks, obj)
        except ChunkError as exc:
            desc.issues.append((node, "modifiers: the modifier stack cannot be read: %s" % exc))
        else:
            return tuple(m for m in active if not uvwmap.is_uvwmap(m) and (ext is None or m.index != ext.index)), ()
    return (), tuple(_class_name(scene, m) or "a modifier" for m in stack.modifiers)


def _emitter_shape(scene, desc, stacks, obj, node, extrusions):
    """(shape base object index, reader MeshData of the Extrude, reader Stack, the Extrude's reader Modifier) of object
    obj when it is a shape whose lowest modifier that renders is an Extrude (convert.extrude), made once with the
    shape's own nodes (_Extrusions); why it has no mesh when the shape, the Extrude or the positions cannot be made,
    or the scene's MAX_BUILT_CORNERS are spent; None when obj is no such shape (_mesh_of then says why)."""
    if stacks is None:
        return None
    try:
        stack = scene.object_stack(obj)
    except ChunkError:  # _mesh_of names the stack it cannot read
        return None
    if stack.base is None or not shapes.is_shape(scene, stack.base):
        return None
    try:
        active = _active(stacks, obj)
    except ChunkError as exc:  # whether an Extrude makes it a mesh is not known
        return lights.EMITTER_UNREAD % ("the modifier stack cannot be read: %s" % exc)
    if not (active and extrude.is_extrude(active[0])):
        return None
    ext = active[0]
    data = extrusions.get(stack.base, ext, node, light=True)
    if isinstance(data, tuple):
        kind, text = data
        return lights.EMITTER_UNREAD % ("its Extrude is not made: " + text if kind == _SPENT_KIND else text)
    try:
        _positions(data, None, desc.meters)  # before the light node's offset, applied in _emitter (describe)
    except MeshError as exc:
        return lights.EMITTER_UNREAD % exc
    return stack.base, data, stack, ext


def _source_object(scene, source):
    """The object of node source (a mesh light's parameter 34), None when it is no node or has none."""
    if source is None or not 0 <= source < len(scene):
        return None
    try:
        return scene.node(source).object
    except ChunkError:  # not a node, or its record cannot be read
        return None


def _mesh_of(scene, desc, obj, node, built, check=None):
    """(base object index, reader MeshData, reader Stack) of object obj's base mesh, or why there is none (also a
    mesh whose positions in meters do not fit single precision)."""
    try:
        stack = scene.object_stack(obj)
    except ChunkError as exc:
        return lights.EMITTER_UNREAD % exc
    mesh_base = stack.base
    if mesh_base is None:
        return lights.EMITTER_UNREAD % "no base object"
    data = None
    if not shapes.is_shape(scene, mesh_base):
        try:
            data = geometry.read_mesh(scene, mesh_base, check)
        except geometry.GeometryError as exc:
            return lights.EMITTER_UNREAD % exc
        if data is None and primitives.is_primitive(scene, mesh_base):
            data = _primitive(scene, mesh_base, desc.issues, node, built)
    if data is None:
        return lights.EMITTER_CLASS % (_class_name(scene, mesh_base) or "an unknown class")
    try:
        _positions(data, None, desc.meters)  # before the light node's offset, applied in _emitter (describe)
    except MeshError as exc:
        return lights.EMITTER_UNREAD % exc
    return mesh_base, data, stack
