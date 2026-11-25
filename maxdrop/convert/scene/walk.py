# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""describe() and read(): the scene walked node by node into a SceneDescription."""
import collections
import math

from ...reader import assets as reader_assets
from ...reader import cfb, classids, controllers, geometry, modifiers as reader_modifiers, shapes, units
from ...reader import scene as reader_scene
from .. import cameras, colors, ies, lights, modifiers as rules, primitives
from .descriptions import (
    _raising, blender_matrix, CAMERA, ChunkError, CURVE, determinant3, EMPTY, ENVIRONMENT, LIGHT, look_at_description,
    MESH, MeshError, NO_RECEIVE, NodeDescription, SceneDescription,
)
from .curves import sheared
from .nodes import _camera, _curve, _light, _primitive
from .emitters import _emitter
from .stack import (
    _class_name, _converted, _evaluated, _extruded, _Extrusions, _layer, _layer_descriptions, _mapped_mesh,
    _name_zeroed, _offset, _split,
)
from .rims import _lowered, _mirrors, _name_rim, _name_seam, _rim, _rim_mirrors, _seam, _shading, _unit


def describe(scene, meters=1.0, unit=None, convert_modifiers=True, assets=None, views=None, cancel=None,
             files=None):
    """The SceneDescription of a reader.scene.Scene; meters is the length of one file unit; convert_modifiers False
    leaves the modifiers Blender has an equivalent for in node.modifiers, unconverted and unreported; assets, the
    scene's reader.assets.AssetTable, names the files of web and IES lights (None: not named); views, the file's
    convert.cameras.SavedViews, picks the scene camera (None: the first camera); cancel, a callable asked before each
    node of both walks and inside the read and description of a large mesh, ends it with Cancelled once it returns
    true; files, a convert.textures.TextureIndex, finds the IES files of VRayIES lights (None: not looked up)."""
    if not (math.isfinite(meters) and meters > 0):
        raise ValueError("meters per unit must be a positive number, not %r" % (meters,))
    check = _raising(cancel)
    t = controllers.Transforms(scene)
    stacks = reader_modifiers.Modifiers(scene)
    desc = SceneDescription(meters, unit)
    order = scene.walk()
    found = {}  # node -> (reader Node, Stack or None), or the ChunkError its record or object stack raised
    shape_of = {}  # base object index -> reader Shape, or the text of the reader's refusal (_shape)
    unbuilt = set()  # curve keys refused for their range (CurveError), named on their first node
    remaining = collections.Counter()  # base object -> nodes still to build: its MeshData goes with the last
    for i in order:
        if check is not None:
            check()
        try:
            node = scene.node(i)
            stack = scene.object_stack(node.object) if node.object is not None else None
            found[i] = (node, stack)
            if stack is not None and stack.base is not None:
                remaining[stack.base] += 1
        except ChunkError as exc:
            found[i] = exc
    data_of = {}  # base object index -> MeshData, or None when the reader refused or does not read it
    built = [0]  # face corners the primitives and extrusions made so far
    extrusions = _Extrusions(scene, desc, shape_of, built)  # shared by the shapes' nodes and the mesh lights
    mapped = {}  # UVW Map modifier index -> (Params, gizmo matrix), or None when it is not evaluated
    told = set()  # modifier indices whose conversion issues were named (on the first node only)
    rims = set()  # (Shell modifier index, mesh key) whose rim issues were named
    ranges = {}  # mesh key before its maps -> whether its positions fit single precision (_mapped_mesh)
    layers = {}  # layer object index -> reader Layer, or None when its record cannot be read
    unlit = {}  # light base object index -> why it is not built
    light_params = {}  # light base object index -> its values (convert.lights.read_params)
    emitter_meshes = {}  # mesh light base -> its mesh (_emitter_mesh) or why it has none, until its last node
    emitter_refused = {}  # (mesh light base, node offset) -> why its emitter mesh does not fit single precision
    ies_files = ies.Lookup(files) if files is not None else None
    swatches = None  # the scene's swatch rule, read for the first light
    unseen = {}  # camera base object index -> why it is not built
    camera_params = {}  # camera base object index -> its values (convert.cameras.read_params)
    mm = unit.meters * 1000.0 if unit is not None else meters * 1000.0  # the thin lens is in the file's own unit
    for i in order:
        if check is not None:
            check()
        local, world = t.local(i), t.world(i)
        kind, key, class_name, modifiers, name, node, layer, base = EMPTY, None, "", (), "", None, None, None
        curve, applied, converted, light, camera, emitter = None, (), (), None, None, None
        if isinstance(found[i], ChunkError):  # a damaged node record or object stack: an empty, children placed
            desc.issues.append((i, "node: %s" % found[i]))
        else:
            node, stack = found[i]
            name = node.name
            layer = _layer(scene, node.layer, layers, desc.issues, i)
            base = stack.base if stack is not None else None
            if stack is not None:
                modifiers = tuple(_class_name(scene, m) for m in stack.modifiers)
            if base is not None and shapes.is_shape(scene, base):
                class_name = _class_name(scene, base)
                ext, maps, rest = _evaluated(scene, stacks, node, desc.issues, i, True) if stack.modifiers else \
                    (None, (), ())
                if ext is not None:
                    fresh = {m.index for m in rest} - told  # named on this node only if its Extrude is made
                    conv, conv_issues = _converted(scene, rest, meters, _offset(t, i), told, convert_modifiers)
                    shell, (seam, above) = _rim(conv), _seam(conv)
                    mirrors = _mirrors(conv, seam if shell is None else shell)
                    key, done = _extruded(scene, desc, extrusions, mapped, base, ext, maps, i, name, t.offset(i),
                                          meters, _shading(conv), check, shell is not None, mirrors, ranges, above)
                    if key is None:
                        told.difference_update(fresh)
                if key is not None:
                    kind = MESH
                    moved = above[:desc.meshes[key].lowered]
                    conv = _lowered(conv, seam, moved)
                    converted, more = rules.budget(conv, len(desc.meshes[key].loop_vertices))
                    desc.issues.extend((i, x) for x in conv_issues + more)
                    _name_seam(desc, rims, above, key, i)
                    _name_rim(desc, rims, shell, key, i, check,
                              _rim_mirrors(desc.meshes[key], mirrors, above, _unit(_offset(t, i), meters)))
                    applied, modifiers = _split(scene, stack.modifiers, (ext,) + done, conv)
                else:
                    kind, curve = _curve(scene, desc, shape_of, unbuilt, base, i, name, t.offset(i), meters)
                remaining[base] -= 1
                if not remaining[base]:
                    extrusions.drop(base)
            elif base is not None and lights.light_class(scene, base) is not None:
                class_name = _class_name(scene, base)
                if swatches is None:
                    swatches = colors.of_scene(scene)
                light = _light(scene, desc, unlit, light_params, base, i, name, meters, swatches, world, assets,
                               ies_files)
                kind = LIGHT if light is not None else EMPTY
                if light is None and base in light_params and lights.is_mesh_light(light_params[base]):
                    refused = (base, _offset(t, i))
                    if refused in emitter_refused:  # not described again for each node
                        desc.issues.append((i, "light: not built: %s" % emitter_refused[refused]))
                    else:
                        try:
                            key, emitter, converted = _emitter(scene, t, desc, emitter_meshes, light_params[base],
                                                               base, i, name, meters, swatches, built, check, stacks,
                                                               told, convert_modifiers, extrusions)
                        except MeshError as exc:  # its mesh with the node's offset: nothing of it is written yet
                            emitter_refused[refused] = str(exc)
                            desc.issues.append((i, "light: not built: %s" % exc))
                        else:
                            if key is not None:
                                kind = MESH
                                if desc.meshes[key].users == [i]:
                                    _name_zeroed(desc, desc.meshes[key], i)
                remaining[base] -= 1
                if not remaining[base]:
                    mesh = emitter_meshes.pop(base, None)
                    if isinstance(mesh, tuple) and not remaining[mesh[0]]:  # a picked shape no node still needs
                        extrusions.drop(mesh[0])
            elif base is not None and cameras.camera_class(scene, base) is not None:
                class_name = _class_name(scene, base)
                camera = _camera(scene, t, desc, unseen, camera_params, base, i, name, meters, mm)
                kind = CAMERA if camera is not None else EMPTY
            elif base is not None:
                class_name = _class_name(scene, base)
                if base not in data_of:
                    try:
                        data_of[base] = geometry.read_mesh(scene, base, check)
                    except geometry.GeometryError as exc:
                        data_of[base] = None
                        desc.issues.append((i, "geometry: %s" % exc))
                    else:
                        if data_of[base] is None and primitives.is_primitive(scene, base):
                            data_of[base] = _primitive(scene, base, desc.issues, i, built)
                data = data_of[base]
                if data is not None:
                    _ext, maps, rest = _evaluated(scene, stacks, node, desc.issues, i, False) if stack.modifiers \
                        else (None, (), ())
                    offset = _offset(t, i)
                    fresh = {m.index for m in rest} - told  # named on this node only if its mesh is made
                    converted, conv_issues = _converted(scene, rest, meters, offset, told, convert_modifiers)
                    shell, (seam, above) = _rim(converted), _seam(converted)
                    mirrors = _mirrors(converted, seam if shell is None else shell)
                    key, done = _mapped_mesh(scene, desc, mapped, (base, offset), data, maps, i, name, offset,
                                             meters, _shading(converted), check, shell is not None, mirrors, ranges,
                                             above=above)
                    if key is None:  # its positions do not fit single precision: a placeholder
                        told.difference_update(fresh)
                        converted = ()
                    else:
                        desc.issues.extend((i, x) for x in conv_issues)
                        moved = above[:desc.meshes[key].lowered]
                        converted = _lowered(converted, seam, moved)
                        converted, more = rules.budget(converted, len(desc.meshes[key].loop_vertices))
                        desc.issues.extend((i, x) for x in more)
                        _name_seam(desc, rims, above, key, i)
                        _name_rim(desc, rims, shell, key, i, check,
                                  _rim_mirrors(desc.meshes[key], mirrors, above, _unit(offset, meters)))
                        if done or converted:
                            applied, modifiers = _split(scene, stack.modifiers, done, converted)
                        kind = MESH
                remaining[base] -= 1
                if not remaining[base]:
                    del data_of[base]
        if kind == EMPTY and not (base is not None and (scene.is_a(base, classids.SC_HELPER, classids.DUMMY) or
                                                        scene.is_a(base, classids.SC_GEOMOBJECT,
                                                                   classids.TARGET_OBJECT) or base in unlit
                                                        or base in light_params or base in unseen)):
            desc.placeholders[class_name] += 1
        flags = {}
        if node is not None:
            render = reader_scene.render_flags(node, None if layer is None else layers[layer])
            flags = dict(hidden=node.hidden, frozen=node.frozen, renderable=bool(render & reader_scene.RENDERABLE),
                         group_head=node.group_head, group_member=node.group_member,
                         cast_shadows=bool(render & reader_scene.CAST_SHADOWS),
                         receive_shadows=bool(render & reader_scene.RECEIVE_SHADOWS))
            if not flags["receive_shadows"] and kind in (MESH, CURVE):
                desc.issues.append((i, NO_RECEIVE))
        desc.nodes.append(NodeDescription(i, name, scene.parent(i), blender_matrix(local, meters),
                                          blender_matrix(world, meters), kind, key, class_name,
                                          determinant3(world) < 0, modifiers, layer, sheared=sheared(local),
                                          curve=curve, applied=applied, converted=converted,
                                          look_at=look_at_description(t.look_at(i)), light=light, camera=camera,
                                          emitter=emitter, **flags))
    desc.render, issues = cameras.render_settings(scene)
    desc.issues.extend((None, "render: %s" % x) for x in issues)
    names = {node.index: node.name or "object %d" % node.index for node in desc.nodes}
    desc.camera, reason, desc.camera_note = cameras.render_camera(
        desc.render, views, [n.index for n in desc.nodes if n.kind == CAMERA], names)
    if reason is not None:
        desc.issues.append((desc.camera, "camera: %s" % reason))
    if lights.environment_sky(scene) is not None:
        desc.issues.append((ENVIRONMENT, "light: %s" % lights.SKY))
    desc.issues.extend((issue.node, "transform: %s" % issue.reason) for issue in t.issues)
    desc.unknown_controllers.update(
        _class_name(scene, issue.controller) if issue.controller is not None else ""
        for issue in t.issues if issue.reason == controllers.UNKNOWN_CLASS)
    desc.layers = _layer_descriptions(scene, layers)
    return desc


def read(path, meters=None, convert_modifiers=True, files=None):
    """The SceneDescription of a .max file. meters None: the file's system unit, 1.0 when it does not say;
    convert_modifiers and files as describe's."""
    with cfb.CompoundFile(path) as cf:
        sc = reader_scene.Scene.from_file(cf)
        unit = units.system_unit(sc)
        if meters is None:
            meters = unit.meters if unit is not None else 1.0
        return describe(sc, meters, unit, convert_modifiers, reader_assets.AssetTable.from_file(cf),
                        cameras.saved_views(cf), files=files)
