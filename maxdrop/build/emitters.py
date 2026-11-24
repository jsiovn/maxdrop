# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Emissive meshes from convert.lights EmitterDescriptions (VRayLight mesh lights).

    material = make_material(ed, strength)  # an Emission material: ed.radiance x strength, one side or both
    set_object(ob, ed)                      # the flags of one object of it: off, camera, shadow, ray visibility
    spread(desc, built, collection, view_layer, strength)  # after build.modifiers.add: over the evaluated area

One Material per EmitterDescription; build.objects gives it to every face of the emitter's mesh. Its Emission
strength is the radiance in W/m^2/sr times strength, the import's Light Strength (Cycles renders an Emission of
strength S as S, as a World; the calibration against V-Ray is in docs/FORMAT.md, "VRayLight"). V-Ray emits a
single-sided mesh light along its faces' normals and shows the other side black (measured): a Mix Shader by
Geometry Backfacing between the Emission and a black Emission (Flip normals: the other way round). A double-sided one
emits on both sides. Per object: off hides it in the viewport and in renders; invisible makes it unseen by the
camera and no shadow caster (V-Ray: a visible mesh light shadows other lights, an invisible one does not; the
node's own Cast Shadows flag is not used, as for any light); diffuse and glossy rays see it as the description says
(Object.visible_*, the same on 4.2 and 5.2).

V-Ray spreads a mesh light's flux (lm, W) over its evaluated mesh, and the description's area is the mesh's below
the modifiers convert.scene turns into Blender modifiers (node.converted). spread measures the mesh under them: a
throwaway copy of the emitter's object, in the scene's own collection and shown (an emitter that is off, or a hidden
node's, is evaluated too), its modifiers on in the viewport and a Subdivision Surface at its render levels as far as
convert.modifiers' viewport budget allows (V-Ray emits the render mesh); the area the description holds (object
space) times the evaluated mesh's over the unmodified mesh's (both of the object: the baked object offset stays out
of it, as in convert.scene), then lights.spread and the Emission strength again.
"""
import bpy

from .. import compat
from ..convert import lights
from ..convert import modifiers as rules

X_STEP = 220.0
EMISSION = "Emission"  # the node that emits (make_material); the black back is BLACK
BLACK = "Black"


def make_material(ed, strength=1.0):
    """A Material named after the emitter's first node."""
    material = bpy.data.materials.new(ed.name or "Emitter")
    tree = compat.node_tree(material)
    nodes, links = tree.nodes, tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (2 * X_STEP, 0.0)
    emission = nodes.new("ShaderNodeEmission")
    emission.name = EMISSION
    emission.inputs["Color"].default_value = tuple(ed.color) + (1.0,)
    emission.inputs["Strength"].default_value = ed.radiance * strength
    if ed.double_sided:
        links.new(emission.outputs["Emission"], out.inputs["Surface"])
        return material
    dark = nodes.new("ShaderNodeEmission")
    dark.name = BLACK
    dark.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    dark.inputs["Strength"].default_value = 0.0
    dark.location = (0.0, -X_STEP)
    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = (0.0, 2 * X_STEP)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (X_STEP, 0.0)
    links.new(geometry.outputs["Backfacing"], mix.inputs["Fac"])
    front, back = (dark, emission) if ed.flip else (emission, dark)
    links.new(front.outputs["Emission"], mix.inputs[1])
    links.new(back.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return material


def set_object(ob, ed):
    """The per-object flags of an object of ed's emitter."""
    if not ed.on:
        ob.hide_viewport = True
        ob.hide_render = True
    ob.visible_camera = ed.camera
    ob.visible_shadow = ed.occluder
    ob.visible_diffuse = ed.diffuse_rays
    ob.visible_glossy = ed.glossy_rays


def _area(mesh):
    """The area of a Blender mesh's faces, in its own units squared."""
    import numpy
    areas = numpy.zeros(len(mesh.polygons), dtype=numpy.float64)
    if len(areas):
        mesh.polygons.foreach_get("area", areas)
    return float(areas.sum())


def _render_levels(converted, corners):
    """The viewport levels a mesh of corners face corners gets for its area under converted (ModifierDescriptions):
    each Subdivision Surface's render levels, lowered as convert.modifiers.budget lowers viewport levels."""
    wanted = tuple(m._replace(settings=tuple((a, dict(m.settings)["render_levels"] if a == "levels" else v)
                                             for a, v in m.settings)) if m.kind == rules.SUBSURF else m
                   for m in converted)
    out, _issues = rules.budget(wanted, corners)
    return [dict(m.settings)["levels"] if m.kind == rules.SUBSURF else None for m in out]


def evaluated_area(ob, converted, collection, view_layer):
    """(the area of object ob's mesh, of that mesh under ob's modifiers) in Blender units squared, measured on a copy
    of ob linked to collection (one of view_layer's that is never excluded: the scene's own) and removed again: shown,
    its modifiers on in the viewport, each Subdivision Surface at its render levels within the viewport budget
    (_render_levels; converted: the ModifierDescriptions ob's modifiers were made from, in their order)."""
    copy = ob.copy()
    try:
        collection.objects.link(copy)
        copy.hide_viewport = False
        for mod, levels in zip(copy.modifiers, _render_levels(converted, len(ob.data.loops))):
            mod.show_viewport = True
            if levels is not None:
                mod.levels = levels
        view_layer.update()
        ev = copy.evaluated_get(view_layer.depsgraph)
        mesh = ev.to_mesh()
        try:
            under = _area(mesh)
        finally:
            ev.to_mesh_clear()
    finally:
        bpy.data.objects.remove(copy)
    return _area(ob.data), under


def spread(desc, built, collection, view_layer, strength=1.0):
    """After build.modifiers.add: each emitter in built (a build.objects.Built) whose first node with an object has
    converted modifiers gets the evaluated area of that object's mesh (evaluated_area) through lights.spread, and its
    Emission material the new strength (radiance x strength); the issues named on that node. The others stay."""
    nodes = {n.index: n for n in desc.nodes if n.emitter is not None}
    for key, ed in desc.emitters.items():
        node = next((nodes[i] for i in ed.users if i in nodes and built.objects.get(i) is not None), None)
        if node is None or not node.converted:
            continue
        base, under = evaluated_area(built.objects[node.index], node.converted, collection, view_layer)
        issues = lights.spread(ed, ed.area * under / base if base > 0 else under)
        desc.issues.extend((node.index, "light: %s" % x) for x in issues)
        material = built.emitters.get(key)
        if material is not None:
            compat.node_tree(material).nodes[EMISSION].inputs["Strength"].default_value = ed.radiance * strength
