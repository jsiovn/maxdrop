# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The nodes that are not meshes: lights (and the dome), cameras, primitives and shapes."""
import math

from ...reader import controllers, shapes
from .. import cameras, lights, primitives
from .descriptions import _SPENT, ChunkError, CURVE, CurveError, EMPTY, MAX_BUILT_CORNERS, OFFSET
from .curves import curve_description


def _dome(desc, values, node, name, swatches, world):
    """A dome light's node: desc.dome when it is the first that is on, else an issue."""
    if not values[lights.P_ON]:
        desc.issues.append((node, "light: " + lights.DOME_OFF))
    elif desc.dome is not None:
        desc.issues.append((node, "light: " + lights.SECOND_DOME % (desc.dome.name or "object %d" % desc.dome.node)))
    else:
        desc.dome, issues = lights.describe_dome(node, name, values, swatches, world)
        desc.issues.extend((node, "light: %s" % x) for x in issues)


def _light(scene, desc, unlit, params, base, node, name, meters, swatches, world, assets=None, ies_files=None):
    """The key in desc.lights of light base on node (world: its reader world matrix), made on first use; None when it
    is not built (unlit caches the reason, an issue on every node) and for a dome (_dome). params caches the light's
    values, whose issues are named on the first node; a description's on the first node of its key."""
    if base not in params and base not in unlit:
        try:
            values, issues = lights.read_params(scene, base, assets, ies_files)
            reason = lights.not_built(values)
        except ChunkError as exc:
            values, issues, reason = None, [], "parameters cannot be read: %s" % exc
        desc.issues.extend((node, "light: %s" % x) for x in issues)
        if reason is None:
            params[base] = values
        else:
            unlit[base] = reason
    if base in unlit:
        desc.issues.append((node, "light: not built: %s" % unlit[base]))
        return None
    if lights.is_dome(params[base]):
        _dome(desc, params[base], node, name, swatches, world)
        return None
    if lights.is_mesh_light(params[base]):  # an emitter (_emitter)
        return None
    scale = lights.area_scale(params[base], world)
    key = (base, scale)
    if key not in desc.lights:
        ld, issues = lights.describe(key, name, params[base], meters, swatches, scale)
        desc.lights[key] = ld
        desc.issues.extend((node, "light: %s" % x) for x in issues)
    desc.lights[key].users.append(node)
    return key


def _camera(scene, t, desc, unseen, params, base, node, name, meters, mm):
    """The key in desc.cameras of camera base on node, made on first use; None when its parameters cannot be read
    (unseen caches the reason, an issue on every node). params caches the camera's values, whose issues are named
    on the first node; a description's on the first node of its key. The key holds the distance to the node's
    target when the camera's framing depends on it."""
    if base not in params and base not in unseen:
        try:
            values, issues = cameras.read_params(scene, base)
            params[base] = values
        except ChunkError as exc:
            issues = []
            unseen[base] = "parameters cannot be read: %s" % exc
        desc.issues.extend((node, "camera: %s" % x) for x in issues)
    if base in unseen:
        desc.issues.append((node, "camera: not built: %s" % unseen[base]))
        return None
    values = params[base]
    look = t.look_at(node)
    target = None
    if look is not None and look.target is not None:
        a, b = t.world(node)[3], t.world(look.target)[3]
        target = float("%.9g" % math.sqrt(sum((a[k] - b[k]) ** 2 for k in range(3))))
    used = cameras.focus_target(values, target)
    key = (base, used if target is not None and used == target and cameras.uses_target(values) else None)
    if key not in desc.cameras:
        cd, issues = cameras.describe(key, name, values, meters, mm, target)
        desc.cameras[key] = cd
        desc.issues.extend((node, "camera: %s" % x) for x in issues)
    desc.cameras[key].users.append(node)
    if t.offset(node) != controllers.IDENTITY:
        desc.issues.append((node, "camera: " + OFFSET))
    return key


def _primitive(scene, base, issues, node, built):
    """The MeshData convert.primitives builds for primitive base, or None when it is not built (an issue); its
    issues are named on the first node only (the caller caches the result). built: [face corners made so far]."""
    if built[0] >= MAX_BUILT_CORNERS:
        issues.append((node, "primitive: not built: " + _SPENT % MAX_BUILT_CORNERS))
        return None
    try:
        data, more = primitives.mesh(scene, base)
    except ChunkError as exc:  # PrimitiveError, or a block the reader refuses
        issues.append((node, "primitive: %s" % exc))
        return None
    except ArithmeticError as exc:  # a formula the sizes break costs the object, not the import
        issues.append((node, "primitive: not built: %s" % exc))
        return None
    built[0] += len(data.loop_vertices)
    issues.extend((node, "primitive: %s" % x) for x in more)
    return data


def _shape(scene, desc, shape_of, base, node):
    """The reader Shape of base, read once (shape_of caches it, or the text of its refusal), None when refused; its
    issues, or the refusal, are named on the first node only."""
    if base not in shape_of:
        try:
            shape_of[base] = shapes.read_shape(scene, base)
            desc.issues.extend((node, "shape: %s" % x) for x in shape_of[base].issues)
        except ChunkError as exc:  # ShapeError, or a block the reader refuses
            shape_of[base] = str(exc)
            desc.issues.append((node, "shape: %s" % exc))
    sh = shape_of[base]
    return None if isinstance(sh, str) else sh


def _curve(scene, desc, shape_of, unbuilt, base, node, name, offset, meters):
    """(kind, curve key) of a node whose base object is a shape: CURVE and its key in desc.curves, made on first
    use; EMPTY and None when the reader refuses the shape or its curve does not fit single precision (an issue,
    named on the first node of the key: unbuilt holds the keys refused). shape_of caches the reader's Shapes
    (small: knots, no arrays), whose issues are named once, on the first node."""
    sh = _shape(scene, desc, shape_of, base, node)
    if sh is None:
        return EMPTY, None
    offset = None if offset == controllers.IDENTITY else offset
    key = (base, offset)
    if key in unbuilt:
        return EMPTY, None
    cd = desc.curves.get(key)
    if cd is None:
        try:
            cd, issues = curve_description(key, name, sh, offset, meters)
        except CurveError as exc:
            unbuilt.add(key)
            desc.issues.append((node, "shape: not built: %s" % exc))
            return EMPTY, None
        desc.curves[key] = cd
        desc.issues.extend((node, "shape: %s" % x) for x in issues)
    cd.users.append(node)
    return CURVE, key
