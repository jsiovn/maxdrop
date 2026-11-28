# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What every part of the fixture tests uses: the repo root, the arguments, check() and its failures, the scene
helpers."""
import collections
import os
import sys

import bpy

from .tables import KEPT_EXPOSURE, KEPT_SIZE, MIRROR_INPUTS, USER_WORLD


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


failures = []


def _mirror_inputs(color):
    """MIRROR_INPUTS with the Base Color of the IR's mirror_color (a VRayMtl's tinted mirror, maxdrop-6n0.6.16)."""
    return dict(MIRROR_INPUTS, **{"Base Color": tuple(color[:3]) + (1.0,)})


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  [%s]" % detail if detail else ""))
    if not cond:
        failures.append(name)


def empty_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for curve in list(bpy.data.curves):
        bpy.data.curves.remove(curve)
    for light in list(bpy.data.lights):
        bpy.data.lights.remove(light)
    for camera in list(bpy.data.cameras):
        bpy.data.cameras.remove(camera)
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)
    for text in list(bpy.data.texts):
        bpy.data.texts.remove(text)
    r = bpy.context.scene.render  # a size no fixture has: a file without a camera must leave it
    r.resolution_x, r.resolution_y, r.resolution_percentage = KEPT_SIZE
    r.pixel_aspect_x = r.pixel_aspect_y = 1.0
    bpy.context.scene.view_settings.exposure = KEPT_EXPOSURE
    bpy.context.scene.camera = None
    for material in list(bpy.data.materials):
        bpy.data.materials.remove(material)
    world = bpy.data.worlds.get(USER_WORLD) or bpy.data.worlds.new(USER_WORLD)  # a dome replaces the scene's World
    world.use_fake_user = False
    bpy.context.scene.world = world
    for other in [w for w in bpy.data.worlds if w != world]:
        bpy.data.worlds.remove(other)


def close(a, b, tolerance):
    return len(a) == len(b) and all(abs(x - y) <= tolerance for x, y in zip(a, b))


def world_of(ob):
    """ob's world matrix: matrix_world, or for an object hidden in the viewport or out of the view layer (an excluded
    collection's, layers_nested) the same product Blender evaluates, up the parent chain: such an object is left out
    of the evaluated scene, so its matrix_world is never updated. A visible child of a hidden parent is read from
    matrix_world: Blender must place it."""
    if not ob.hide_viewport and ob.name in bpy.context.view_layer.objects:
        return ob.matrix_world
    m = ob.matrix_basis.copy()
    while ob.parent is not None:
        m = ob.parent.matrix_basis @ ob.matrix_parent_inverse @ m
        ob = ob.parent
    return m


def max_rows(m, meters):
    """A Blender world matrix as the oracle's 12 floats: Max's rows, translation in file units."""
    out = []
    for r in range(3):
        out += [m[c][r] for c in range(3)]
    return out + [m[c][3] / meters for c in range(3)]


def objects_of(desc):
    """The object of each node of desc after an import into an emptied scene."""
    seen = collections.Counter()
    out = []
    for node in desc.nodes:
        k = seen[node.name]
        seen[node.name] += 1
        out.append(bpy.data.objects[node.name if not k else "%s.%03d" % (node.name, k)])
    return out


def build_scene(desc, name, modules, **slots):
    _cs, _cr, build_objects, build_collections, _br = modules
    view_layer = bpy.context.view_layer
    cols = build_collections.make(desc, bpy.context.scene.collection, name)
    built = build_objects.build(desc, cols.root, cols, view_layer, **slots)
    build_collections.finish(cols, view_layer)
    view_layer.update()
    return cols, built, view_layer
