# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of lights: emitters spread over their meshes, VRayLights, standard lights, the dome and its undo,
Light Strength."""
import math
import os

import bpy
from mathutils import Vector

from .core import check, close, empty_scene, world_of
from .tables import (
    EMITTER_BOXES, EMITTER_FLAGS, EMITTER_RADIANCE, EMITTER_SHELLED, EMITTER_SOLIDIFY, STOCK_COLORS, STOCK_FLAGS,
    STOCK_GREY, STOCK_LIGHTS, STOCK_SHADOWS, USER_WORLD, VRAY_LIGHT_COLORS, VRAY_LIGHT_FLAGS, VRAY_LIGHT_POWER,
    VRAY_LIGHT_SHAPES, VRAY_LIGHT_WATTS, VRAY_NO_SHADOWS,
)
from .nodes import _advance, _cancel_run, _state


def check_spread(desc, meters):
    """vray_mesh_light's FixtureEmitterOwn: its Shell a Solidify of 2 mm on the emitter (EMITTER_SOLIDIFY), the mesh
    under it measured at 760 mm^2 by build.emitters.evaluated_area, the same with the emitter hidden (an emitter that
    is off) and with its collection excluded, and no object left behind. Then a bench of the other modifiers: a
    1 x 1 plane beside a hidden mirror empty under a Subdivision Surface off in the viewport at level 0 (render level
    2) and a Mirror, measured as Blender renders it (check_spread_bench)."""
    from maxdrop.build import emitters as build_emitters
    name = "FixtureEmitterOwn"
    ob = bpy.data.objects.get(name)
    node = next((n for n in desc.nodes if n.name == name), None)
    mods = [(m.type, m.thickness / meters) for m in ob.modifiers if m.type == 'SOLIDIFY'] if ob is not None else []
    check("vray_mesh_light: %s's Shell a Solidify of %g mm on its emitter" % (name, EMITTER_SOLIDIFY[name]),
          ob is not None and len(ob.modifiers) == 1 and len(mods) == 1 and
          abs(mods[0][1] - EMITTER_SOLIDIFY[name]) < 1e-6, str(mods))
    if ob is None or node is None:
        return
    scene, view_layer = bpy.context.scene, bpy.context.view_layer
    count = len(bpy.data.objects)
    areas = [build_emitters.evaluated_area(ob, node.converted, scene.collection, view_layer)]
    ob.hide_viewport = True
    areas.append(build_emitters.evaluated_area(ob, node.converted, scene.collection, view_layer))
    ob.hide_viewport = False
    layer = next(lc for lc in _layer_collections(view_layer.layer_collection) if lc.collection in ob.users_collection)
    layer.exclude = True
    areas.append(build_emitters.evaluated_area(ob, node.converted, scene.collection, view_layer))
    layer.exclude = False
    got = [(base / meters ** 2, under / meters ** 2) for base, under in areas]
    check("vray_mesh_light: %s's mesh 300 mm^2, under its Solidify %g, shown, hidden or excluded" % (
        name, EMITTER_SHELLED), all(abs(b - 300.0) < 1e-3 and abs(u - EMITTER_SHELLED) < 1e-3 for b, u in got) and
        len(bpy.data.objects) == count, "%s, %d objects (%d before)" % (got, len(bpy.data.objects), count))
    check_spread_bench(scene, view_layer)
    check_spread_steps(scene, view_layer)


def check_spread_bench(scene, view_layer):
    """build.emitters.evaluated_area of a Subdivision Surface at its render levels (2; viewport 0 and hidden there)
    and a Mirror whose mirror empty is hidden: the area Blender evaluates at level 2 with the copy shown (1 < a < 2:
    the plane shrunk by the subdivision, its copy counted), no object left behind."""
    from maxdrop.build import emitters as build_emitters
    from maxdrop.convert import modifiers as rules
    mesh = bpy.data.meshes.new("SpreadBench")
    mesh.from_pydata([(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 1.0, 0.0), (1.0, 1.0, 0.0)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new("SpreadBench", mesh)
    empty = bpy.data.objects.new("SpreadBenchMirror", None)
    for x in (ob, empty):
        scene.collection.objects.link(x)
    empty.hide_viewport = True
    smooth = ob.modifiers.new("TurboSmooth", 'SUBSURF')
    smooth.levels, smooth.render_levels, smooth.show_viewport = 0, 2, False
    mirror = ob.modifiers.new("Symmetry", 'MIRROR')
    mirror.mirror_object, mirror.use_mirror_merge = empty, False
    converted = (rules.ModifierDescription(1, rules.SUBSURF, "TurboSmooth", "TurboSmooth", False,
                                           (("levels", 0), ("render_levels", 2)), None, None),
                 rules.ModifierDescription(2, rules.MIRROR, "Symmetry", "Symmetry", True, (), None, None))
    count = len(bpy.data.objects)
    _base, under = build_emitters.evaluated_area(ob, converted, scene.collection, view_layer)
    left = len(bpy.data.objects)
    smooth.levels, smooth.show_viewport, empty.hide_viewport = 2, True, False
    view_layer.update()
    ev = ob.evaluated_get(view_layer.depsgraph)
    want = build_emitters._area(ev.to_mesh())
    ev.to_mesh_clear()
    for x in (ob, empty):
        bpy.data.objects.remove(x)
    bpy.data.meshes.remove(mesh)
    check("evaluated_area: a Subdivision Surface at its render levels and a Mirror by a hidden empty",
          1.0 < under < 2.0 and abs(under - want) < 1e-6 and left == count, "%r vs %r, %d objects (%d before)" % (
              under, want, left, count))


class _CountedViewLayer:
    """A view layer whose update() calls are counted."""

    def __init__(self, view_layer):
        self.view_layer, self.updates = view_layer, 0

    def update(self):
        self.updates += 1
        self.view_layer.update()

    @property
    def depsgraph(self):
        return self.view_layer.depsgraph


def check_spread_steps(scene, view_layer):
    """build.emitters.spread as import steps over two hand-made emitters in W (a rectangle and a trapezoid described
    at 0.5 and 0.8 m^2, under a Subdivision Surface at level 0, render level 2): it yields (0, 2) with both copies
    linked, then (1, 2) and (2, 2), with one view-layer update for both; each emitter's area is the description's times the evaluated mesh's over the
    mesh's, as evaluated_area measures it, and no object is left. Closed after its second step: the first emitter
    spread, the second not, no object left. Both emitters carry their Emission material (make_material, on their
    meshes and in built.emitters; maxdrop-6n0.8.1): spread at strength 2 writes each one's radiance x 2 between the
    measurements, with no update of its own, and the areas stay the evaluated ones; closed early, the second keeps
    its first strength."""
    import types
    from maxdrop.build import emitters as build_emitters
    from maxdrop.convert import lights
    from maxdrop.convert import modifiers as rules
    converted = (rules.ModifierDescription(1, rules.SUBSURF, "TurboSmooth", "TurboSmooth", False,
                                           (("levels", 0), ("render_levels", 2)), None, None),)
    obs = []
    for i, top in ((1, (0.0, 1.0)), (2, (0.8, 1.2))):
        mesh = bpy.data.meshes.new("SpreadSteps%d" % i)
        mesh.from_pydata([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (top[1] * 2.0 - top[0], 1.0, 0.0), (top[0], 1.0, 0.0)],
                         [], [(0, 1, 2, 3)])
        ob = bpy.data.objects.new("SpreadSteps%d" % i, mesh)
        scene.collection.objects.link(ob)
        smooth = ob.modifiers.new("TurboSmooth", 'SUBSURF')
        smooth.levels, smooth.render_levels, smooth.show_viewport = 0, 2, False
        obs.append(ob)
    try:
        described = {1: 0.5, 2: 0.8}
        want = []
        for k, ob in zip((1, 2), obs):
            base, under = build_emitters.evaluated_area(ob, converted, scene.collection, view_layer)
            want.append(described[k] * under / base)

        def run(stop_after=None):
            eds = {k: lights.EmitterDescription(k, "SpreadSteps%d" % k, area=described[k], units=lights.UNITS_W,
                                                multiplier=10.0) for k in (1, 2)}
            for k, ed in eds.items():
                ed.users = [k]
            desc = types.SimpleNamespace(nodes=[types.SimpleNamespace(index=k, emitter=k, converted=converted)
                                                for k in (1, 2)], emitters=eds, issues=[])
            materials = {k: build_emitters.make_material(eds[k], 2.0) for k in (1, 2)}
            first = {k: eds[k].radiance * 2.0 for k in (1, 2)}
            for k, ob in zip((1, 2), obs):
                ob.data.materials.append(materials[k])
            built = types.SimpleNamespace(objects={1: obs[0], 2: obs[1]}, emitters=materials)
            counted = _CountedViewLayer(view_layer)
            count = len(bpy.data.objects)
            steps, copies = [], []
            try:
                gen = build_emitters.spread(desc, built, scene.collection, view_layer=counted, strength=2.0)
                for step in gen:
                    steps.append(step)
                    copies.append(len(bpy.data.objects) - count)
                    if stop_after is not None and len(steps) == stop_after:
                        gen.close()
                        break
                strengths = [(materials[k].node_tree.nodes[build_emitters.EMISSION].inputs["Strength"].default_value,
                              eds[k].radiance * 2.0, first[k]) for k in (1, 2)]
            finally:
                for ob in obs:
                    ob.data.materials.clear()
                for material in materials.values():
                    bpy.data.materials.remove(material)
            return (steps, copies, counted.updates, [eds[k].area for k in (1, 2)], len(bpy.data.objects) - count,
                    strengths)

        steps, copies, updates, areas, left, strengths = run()
        check("spread steps: (0, 2), (1, 2), (2, 2) with both copies linked, one update, the evaluated areas, "
              "no object left", steps == [(0, 2), (1, 2), (2, 2)] and copies == [2, 2, 2] and updates == 1 and
              close(areas, want, 1e-9) and left == 0, "%s %s %d %s vs %s, %d left" % (
                  steps, copies, updates, areas, want, left))
        check("spread steps: both emitters' Emission Strength = their spread radiance x 2, changed",
              all(w > 0 and abs(g - w) <= w * 1e-6 and abs(w - f) > w * 1e-3 for g, w, f in strengths),
              str(strengths))
        steps, copies, updates, areas, left, strengths = run(stop_after=2)
        check("spread steps: closed after its second step: the first emitter spread, the second not, no object left",
              steps == [(0, 2), (1, 2)] and abs(areas[0] - want[0]) < 1e-9 and areas[1] == 0.8 and left == 0,
              "%s %s %d left" % (steps, areas, left))
        (g1, w1, f1), (g2, _w2, f2) = strengths
        check("spread steps: closed early: the first Strength spread, the second its first one",
              w1 > 0 and abs(g1 - w1) <= w1 * 1e-6 and abs(w1 - f1) > w1 * 1e-3 and abs(g2 - f2) <= max(f2, 1.0) * 1e-6,
              str(strengths))
    finally:
        for ob in obs:
            mesh = ob.data
            bpy.data.objects.remove(ob)
            bpy.data.meshes.remove(mesh)


def check_spread_cancel(path):
    """vray_mesh_light through the run's steps (pipeline._Run), closed while it measures its mesh lights (their copies
    linked to the scene's collection, the run's text saying so): nothing is left, the copies neither."""
    empty_scene()
    before = _state()
    scene = bpy.context.scene
    run = _cancel_run([path])
    steps = run.steps()
    held = _advance(steps, lambda: run.text.startswith("measuring the mesh lights of ") and
                    len(scene.collection.objects) > 0)
    text, copies = run.text, len(scene.collection.objects)
    steps.close()
    check("spread cancel: closed while it measures the mesh lights: nothing left, its copies neither",
          held and _state() == before and not scene.collection.objects, "%s %r, %d copies | %s | %s" % (
              held, text, copies, _state(), before))


def _layer_collections(lc):
    yield lc
    for child in lc.children:
        yield from _layer_collections(child)


def check_emitter(label, ob, ed, o, meters, spread=False):
    """A mesh light's node: a mesh object at the light's place whose box is the script's (EMITTER_BOXES), its mesh's
    only material an Emission of the radiance by hand (EMITTER_RADIANCE) times the operator's default Light Strength
    and the light's color; one side: a Mix Shader by Geometry Backfacing between it and a black Emission, in the order
    flip says; double-sided: the Emission alone; its flags (EMITTER_FLAGS: double-sided, flip, camera, shadow,
    diffuse, glossy). spread: its node has converted modifiers, so the radiance is the evaluated mesh's
    (build.emitters.spread), not the description's (convert.scene.read's, of the mesh below them)."""
    from maxdrop import options
    check(label + ": an emitter mesh object", ob.type == 'MESH', ob.type)
    if ob.type != 'MESH':
        return
    name = o["name"]
    mw = world_of(ob)
    world = [mw @ v.co for v in ob.data.vertices]
    lo = [min(p[k] for p in world) / meters for k in range(3)]
    hi = [max(p[k] for p in world) / meters for k in range(3)]
    box = EMITTER_BOXES.get(name)
    check(label + ": the source's mesh at the light's place", box is not None and close(lo, box[0], 1e-3) and
          close(hi, box[1], 1e-3), "%s..%s vs %s" % (["%.6g" % v for v in lo], ["%.6g" % v for v in hi], box))
    mats = [m for m in ob.data.materials]
    indices = {p.material_index for p in ob.data.polygons}
    check(label + ": one material on every face", len(mats) == 1 and mats[0] is not None and indices == {0} and
          all(not s.link == 'OBJECT' for s in ob.material_slots), "%s %s" % (mats, indices))
    if len(mats) != 1 or mats[0] is None:
        return
    nodes = mats[0].node_tree.nodes
    out = next((n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial"), None)
    lit = [n for n in nodes if n.bl_idname == "ShaderNodeEmission" and n.inputs["Strength"].default_value > 0]
    want = EMITTER_RADIANCE.get(name, -1.0) * options.LIGHT_STRENGTH
    got = lit[0].inputs["Strength"].default_value if len(lit) == 1 else None
    check(label + ": Emission strength = the radiance x Light Strength", got is not None and
          abs(got - want) <= want * 1e-5 and (spread or abs(got - ed.radiance * options.LIGHT_STRENGTH) <= want * 1e-6),
          "%s vs %g" % (got, want))
    check(label + ": Emission color = the light's", len(lit) == 1 and
          close(tuple(lit[0].inputs["Color"].default_value)[:3], ed.color, 1e-6), str(ed.color))
    surface = out.inputs["Surface"].links[0].from_node if out is not None and out.inputs["Surface"].links else None
    flags = EMITTER_FLAGS.get(name)
    double, flip = flags[:2] if flags else (None, None)
    if double:
        check(label + ": double-sided: the Emission alone", surface is not None and lit and surface == lit[0],
              str(surface))
    else:
        ok = surface is not None and surface.bl_idname == "ShaderNodeMixShader"
        fac = surface.inputs["Fac"].links[0].from_socket if ok and surface.inputs["Fac"].links else None
        sides = [surface.inputs[k].links[0].from_node if ok and surface.inputs[k].links else None for k in (1, 2)]
        lit_side = 1 if flip else 0  # the side the Emission is on: front (Backfacing 0, input 1) unless flipped
        check(label + ": one side: Backfacing mixes the Emission and black (%s)" % ("back" if flip else "front"),
              ok and fac is not None and fac.name == "Backfacing" and fac.node.bl_idname == "ShaderNodeNewGeometry"
              and lit and sides[lit_side] == lit[0] and sides[1 - lit_side] is not None and
              sides[1 - lit_side].inputs["Strength"].default_value == 0.0, str(sides))
    got = (ed.double_sided, ed.flip, ob.visible_camera, ob.visible_shadow, ob.visible_diffuse, ob.visible_glossy)
    check(label + ": double-sided, flip, camera, shadow, diffuse and glossy visibility", got == flags, str(got))


def check_light(label, ob, ld, o):
    """vray_lights: a LIGHT node's object holds its light: the description's type, shape and size; its -Z axis
    (where a V-Ray plane and a Blender area light shine) along the oracle's; its energy the watts 3ds Max computed
    with the rules source's own function (VRAY_LIGHT_WATTS) times the operator's default Light Strength, halved for
    the double-sided plane; its color, its object flags and its shadow switch (VRAY_NO_SHADOWS). Any other light:
    check_stock_light."""
    light = ob.data
    check(label + ": a light object", ob.type == 'LIGHT', ob.type)
    if ob.type != 'LIGHT':
        return
    if o["name"] not in VRAY_LIGHT_WATTS:
        check_stock_light(label, ob, ld, o)
        return
    size = (light.type, getattr(light, "shape", None) if light.type == 'AREA' else None,
            light.size if light.type == 'AREA' else 0.0,
            light.size_y if light.type == 'AREA' and light.shape == 'RECTANGLE' else 0.0,
            light.shadow_soft_size if light.type == 'POINT' else 0.0)
    want = (ld.kind, ld.shape, ld.size, ld.size_y if ld.shape == 'RECTANGLE' else 0.0, ld.radius)
    check(label + ": type, shape and size", size[:2] == want[:2] and close(size[2:], want[2:], 1e-7),
          "%s vs %s" % (size, want))
    expected = VRAY_LIGHT_SHAPES.get(o["name"])
    check(label + ": the shape the fixture script made", expected is not None and size[:2] == expected[:2] and
          close(size[2:], expected[2:], 1e-7), str(expected))
    rows = o["transform"]
    z = Vector(rows[6:9]).normalized()
    got = -(ob.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
    check(label + ": shines along the oracle's -Z", (got + z).length < 1e-5, "%s vs %s" % (tuple(got), tuple(-z)))
    from maxdrop import options
    watts = VRAY_LIGHT_WATTS[o["name"]] * VRAY_LIGHT_POWER.get(o["name"], 1.0)
    check(label + ": power = 3ds Max's watts x Light Strength", abs(light.energy - watts * options.LIGHT_STRENGTH) <=
          watts * options.LIGHT_STRENGTH * 1e-5, "%g vs %g" % (light.energy, watts * options.LIGHT_STRENGTH))
    color = VRAY_LIGHT_COLORS.get(o["name"], (1.0, 1.0, 1.0))
    check(label + ": color", close(tuple(light.color), color, 1e-5) and close(tuple(light.color), ld.color, 1e-6),
          str(tuple(light.color)))
    flags = (ob.visible_camera, ob.visible_diffuse, ob.visible_glossy, round(light.diffuse_factor, 6),
             round(light.specular_factor, 6))
    want = VRAY_LIGHT_FLAGS.get(o["name"], (True, True, True, 1.0, 1.0))
    check(label + ": camera, diffuse and glossy visibility, diffuse and specular factors", flags == want, str(flags))
    check(label + ": shadows as in 3ds Max", light.use_shadow == ld.shadow == (o["name"] not in VRAY_NO_SHADOWS),
          "%s, %s" % (light.use_shadow, ld.shadow))


def check_stock_light(label, ob, ld, o):
    """lights_standard, lights_photometric, lookat's target spot: the light's type, spot cone, size or radius as the
    description says, energy the watts of STOCK_LIGHTS times the default Light Strength, color, flags, shadows
    (STOCK_SHADOWS); its -Z axis (where a spot, an area light and a sun shine in both programs) along the oracle's."""
    from maxdrop import options
    light = ob.data
    kind, cone, blend, watts = STOCK_LIGHTS[o["name"]]
    check(label + ": type", light.type == kind == ld.kind, "%s vs %s" % (light.type, kind))
    if light.type == 'SPOT':
        check(label + ": spot size and blend", abs(math.degrees(light.spot_size) - cone) < 1e-4 and
              abs(light.spot_blend - blend) < 1e-6, "%g, %g" % (math.degrees(light.spot_size), light.spot_blend))
    if light.type == 'AREA':
        got = (light.shape, light.size, light.size_y if light.shape == 'RECTANGLE' else light.size)
        check(label + ": area shape and size", got[0] == ld.shape and close(got[1:], (ld.size, ld.size_y), 1e-7),
              str(got))
    elif light.type == 'SUN':
        check(label + ": sun angle", abs(light.angle - ld.angle) < 1e-7, "%g" % light.angle)
    else:
        check(label + ": radius", abs(light.shadow_soft_size - ld.radius) < 1e-7, "%g" % light.shadow_soft_size)
    want = watts * options.LIGHT_STRENGTH
    check(label + ": power = the rules' watts x Light Strength", abs(light.energy - want) <= max(want, 1.0) * 1e-5,
          "%g vs %g" % (light.energy, want))
    rgb = STOCK_COLORS.get(o["name"], (180, 180, 180) if o["name"] in STOCK_GREY else (255, 255, 255))
    color = tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (v / 255.0 for v in rgb))
    check(label + ": color", close(tuple(light.color), color, 1e-5), str(tuple(light.color)))
    rows = o["transform"]
    z = Vector(rows[6:9]).normalized()
    got = -(ob.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
    check(label + ": shines along the oracle's -Z", (got + z).length < 1e-5, "%s vs %s" % (tuple(got), tuple(-z)))
    flags = (ob.visible_camera, ob.visible_diffuse, ob.visible_glossy, round(light.diffuse_factor, 6),
             round(light.specular_factor, 6))
    want = STOCK_FLAGS.get(o["name"], (True, True, True, 1.0, 1.0))
    check(label + ": camera, diffuse and glossy visibility, diffuse and specular factors", flags == want, str(flags))
    check(label + ": shadows as in 3ds Max", light.use_shadow == ld.shadow == (o["name"] in STOCK_SHADOWS),
          "%s, %s" % (light.use_shadow, ld.shadow))


def check_dome(desc):
    """vray_dome: the dome is the World: Background strength (through the hemisphere's Math nodes) = 2 x 1500 /
    (683 pi) x Light Strength, its color an Environment Texture of fixture_dome.png (Linear Rec.709) through a Gamma
    node (the gamma-off fixture's Auto VRayBitmap: SRGB_TWICE), the texture's Mapping (scale 1, -1,
    1; turned 60 degrees about Z: -30 of the VRayBitmap's horizontal rotation, then the mirrored dome turned 90 about Z)
    and the hemisphere's (the dome's -90 about Z), camera rays off, diffuse and glossy on. The two spheres share one
    light, the scaled one has its own. The report says the World and the one it replaced, which is kept."""
    from maxdrop import options
    world = bpy.context.scene.world
    user = bpy.data.worlds.get(USER_WORLD)
    check("vray_dome: FixtureDome is the World, UserWorld kept with a fake user", world is not None and
          world.name == "FixtureDome" and user is not None and user.use_fake_user, world.name if world else "none")
    if world is None or world.name != "FixtureDome":
        return
    nodes = world.node_tree.nodes
    env = next((n for n in nodes if n.bl_idname == "ShaderNodeTexEnvironment"), None)
    times = next((n for n in nodes if n.bl_idname == "ShaderNodeMath" and n.operation == 'MULTIPLY'), None)
    above = next((n for n in nodes if n.bl_idname == "ShaderNodeMath" and n.operation == 'GREATER_THAN'), None)
    maps = {tuple(round(v, 6) for v in n.inputs["Scale"].default_value): n for n in nodes
            if n.bl_idname == "ShaderNodeMapping"}
    want = 2.0 * 1500.0 / (683.0 * math.pi) * options.LIGHT_STRENGTH
    check("vray_dome: hemisphere strength = 2 x 1500 / (683 pi) x Light Strength, masked by Z > 0",
          times is not None and above is not None and abs(times.inputs[1].default_value - want) < 1e-5 and
          times.inputs[0].links and times.inputs[0].links[0].from_node == above,
          "%s" % (times and times.inputs[1].default_value))
    from maxdrop.convert import texmaps as tx
    links = nodes["Background"].inputs["Color"].links
    power = links[0].from_node if links else None
    check("vray_dome: an Environment Texture of fixture_dome.png drives the color",
          env is not None and env.image is not None and env.image.name.startswith("fixture_dome") and
          power is not None and power.inputs["Color"].links and power.inputs["Color"].links[0].from_node == env,
          str(env and env.image))
    # transfer function Auto in the gamma-off fixture: V-Ray's sRGB curve shown decoded once more (maxdrop-em3.123)
    check("vray_dome: the texture in Linear Rec.709 through a Gamma node of SRGB_TWICE",
          power is not None and power.bl_idname == "ShaderNodeGamma" and
          abs(power.inputs["Gamma"].default_value - tx.SRGB_TWICE) < 1e-6 and env.image is not None and
          env.image.colorspace_settings.name == "Linear Rec.709",
          "%s %s" % (power and power.bl_idname, env and env.image and env.image.colorspace_settings.name))
    tex, up = maps.get((1.0, -1.0, 1.0)), maps.get((1.0, 1.0, 1.0))
    check("vray_dome: the texture's Mapping turned 60 degrees about Z, the hemisphere's -90",
          tex is not None and up is not None and
          close(tuple(tex.inputs["Rotation"].default_value), (0.0, 0.0, math.radians(60.0)), 1e-5) and
          close(tuple(up.inputs["Rotation"].default_value), (0.0, 0.0, math.radians(-90.0)), 1e-5),
          "%s %s" % (tex and tuple(tex.inputs["Rotation"].default_value),
                     up and tuple(up.inputs["Rotation"].default_value)))
    rays = world.cycles_visibility
    check("vray_dome: invisible: camera rays off, diffuse and glossy on", (rays.camera, rays.diffuse, rays.glossy) ==
          (False, True, True), str((rays.camera, rays.diffuse, rays.glossy)))
    ob = bpy.data.objects.get("FixtureDomeColor")
    check("vray_dome: FixtureDomeColor an empty", ob is not None and ob.type == 'EMPTY', ob and ob.type)
    check("vray_dome: three sphere objects, three lights (the scaled instance its own)",
          len([ob for ob in bpy.data.objects if ob.type == 'LIGHT']) == 3 and len(bpy.data.lights) == 3 and
          bpy.data.objects["FixtureSphereWide"].data != bpy.data.objects["FixtureSphereWideInst"].data,
          str(len(bpy.data.lights)))


def check_dome_undo(path):
    """vray_dome: the report names the World and the one it replaced; undo() of a finished modal run (the World is
    made at the end of the build), and a build that fails after making the World, put the scene's World back and
    remove the new one with everything else the run made."""
    from maxdrop import pipeline
    empty_scene()
    result = bpy.ops.import_scene.maxdrop(filepath=path)
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    check("dome undo: the report names the World and the one it replaced", result == {'FINISHED'} and
          "\nWorld: the dome light FixtureDome, in place of %s (kept)\n" % USER_WORLD in body, body[:600])
    empty_scene()
    for img in list(bpy.data.images):  # so that the run loads the dome's image anew, and undo() must remove it
        bpy.data.images.remove(img)
    before = _state()
    run = _cancel_run([path])
    for _ in run.steps():
        pass
    made = bpy.context.scene.world is not None and bpy.context.scene.world.name == "FixtureDome"
    run.undo()
    check("dome undo: undo() after the run: the World before is back without a fake user, nothing made",
          made and _state() == before and not bpy.data.worlds[USER_WORLD].use_fake_user,
          "%s | %s" % (_state(), before))
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    before = _state()
    original = pipeline._make_world

    def failing(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("maxdrop test: build fails after the World")

    pipeline._make_world = failing
    try:
        steps = _cancel_run([path]).steps()
        failed = False
        try:
            for _ in steps:
                pass
        except RuntimeError:
            failed = True
        except Exception as e:  # the runner may wrap it
            failed = "maxdrop test" in str(e)
    finally:
        pipeline._make_world = original
    check("dome undo: a build that fails after the World puts the World before back, nothing made",
          failed and _state() == before and not bpy.data.worlds[USER_WORLD].use_fake_user,
          "%s | %s" % (_state(), before))

    # a World that cannot be built: the scene is imported, the World stays, a line in the report
    from maxdrop.build import world as build_world
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    real = build_world.make_world

    def broken(*args, **kwargs):
        bpy.data.worlds.new("Half")
        raise RuntimeError("maxdrop test: World fails")

    build_world.make_world = broken
    try:
        result = bpy.ops.import_scene.maxdrop(filepath=path)
    finally:
        build_world.make_world = real
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    check("dome undo: a World that cannot be built: the scene imported, its World kept, nothing left, a report line",
          result == {'FINISHED'} and len(bpy.data.objects) == 7 and bpy.context.scene.world.name == USER_WORLD and
          [w.name for w in bpy.data.worlds] == [USER_WORLD] and not bpy.data.images and
          "the World is not built (RuntimeError: maxdrop test: World fails)" in body,
          "%s %d %s %s" % (result, len(bpy.data.objects), [w.name for w in bpy.data.worlds], body[-400:]))

    # two files with a dome: the first gives the World, the second's dome is a line in the report
    lights = os.path.join(os.path.dirname(path), "vray_lights.max")
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    before = _state()
    run = _cancel_run([path, lights])
    for _ in run.steps():
        pass
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    names = sorted(w.name for w in bpy.data.worlds)
    check("dome undo: two files with a dome: the first file's dome is the World, the second's a line in the report",
          bpy.context.scene.world.name == "FixtureDome" and names == ["FixtureDome", USER_WORLD] and
          "dome light not imported: an earlier file of this import gave the World (FixtureDome)" in body,
          "%s %s" % (names, body[-600:]))
    run.undo()
    check("dome undo: two files undone: the World before is back without a fake user, nothing made",
          _state() == before and not bpy.data.worlds[USER_WORLD].use_fake_user, "%s | %s" % (_state(), before))
    empty_scene()


def check_light_strength(path):
    """vray_lights imported again with Light Strength 2: every light's energy is its power times 2."""
    empty_scene()
    result = bpy.ops.import_scene.maxdrop(filepath=path, light_strength=2.0)
    check("vray_lights Light Strength 2: the operator finishes", result == {'FINISHED'}, str(result))
    sphere = bpy.data.objects.get("FixtureSphere")
    check("vray_lights Light Strength 2: 40 W x 2", sphere is not None and abs(sphere.data.energy - 80.0) < 1e-4,
          str(sphere and sphere.data.energy))


def check_light_nodes():
    """compat.light_nodes on a new point and spot light (4.x: use_nodes off, no tree; 5.x: a tree at once): the
    light's tree, a Light Output and an Emission linked into its Surface; a second call returns the same nodes and adds
    none; a tree emptied of its nodes gets both back, linked."""
    from maxdrop import compat
    for kind in ('POINT', 'SPOT'):
        light = bpy.data.lights.new("LightNodes" + kind.title(), kind)
        try:
            tree, emission, output = compat.light_nodes(light)
            label = "light nodes (%s)" % kind.lower()
            check(label + ": the light's tree, nodes enabled", tree is not None and tree == light.node_tree and
                  getattr(light, "use_nodes", True), str(tree))
            linked = [k.from_node for k in output.inputs["Surface"].links]
            check(label + ": an Emission linked into the Light Output's Surface",
                  output.bl_idname == "ShaderNodeOutputLight" and emission.bl_idname == "ShaderNodeEmission" and
                  linked == [emission], "%s %s %s" % (output.bl_idname, emission.bl_idname, linked))
            count = len(tree.nodes)
            again = compat.light_nodes(light)
            check(label + ": a second call returns the same nodes and adds none",
                  again == (tree, emission, output) and len(tree.nodes) == count, "%d -> %d" % (count, len(tree.nodes)))
            tree.nodes.clear()
            tree, emission, output = compat.light_nodes(light)
            linked = [k.from_node for k in output.inputs["Surface"].links]
            check(label + ": an emptied tree gets both nodes back, linked", len(tree.nodes) == 2 and
                  linked == [emission] and emission.bl_idname == "ShaderNodeEmission", str(len(tree.nodes)))
        finally:
            bpy.data.lights.remove(light)
