# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""run_fixture(): one fixture imported through the operator and compared with its oracle and with convert.scene."""
import json
import math
import os

import bpy
from mathutils import Vector

from .core import check, close, empty_scene, max_rows, objects_of, world_of
from .tables import (
    BARE_MESHES, BBOX_TOLERANCE, CLASS_NAMES, FLAT_SHADED, HOLLOW, INSIDE_OUT, MATRIX_TOLERANCE, PLANE_NORMALS,
    PRIMITIVE_CLASSES, SHARP_EDGES, SHARP_EDGES_DEFAULT, USER_WORLD, UV_LAYERS,
)
from .nodes import _irs
from .checks_objects import (
    check_camera, check_converted, check_curve, check_extruded, check_lookat, check_modifier_pivot, check_render,
    check_shapes_more,
)
from .checks_lights import check_dome, check_emitter, check_light, check_light_strength, check_spread
from .checks_maps import check_fixture_materials, check_wrappers_report
from .checks_layers import check_layers_more, check_layers_nested, check_layers_render


def run_fixture(path, modules):
    convert_scene, convert_report, _bo, _bc, build_report = modules
    name = os.path.splitext(os.path.basename(path))[0]
    with open(path[:-4] + ".oracle.json", encoding="utf-8") as f:
        oracle = json.load(f)
    empty_scene()
    desc = convert_scene.read(path)
    _same, plan = _irs(path)
    result = bpy.ops.import_scene.maxdrop(filepath=path)
    check("%s: the operator finishes" % name, result == {'FINISHED'}, str(result))
    listed = name in UV_LAYERS  # a named failure, not a KeyError (the plain suite also checks the keys)
    check("%s: listed in UV_LAYERS of tests/blender/tables.py" % name, listed)
    if name == "vray_wrappers":
        check_wrappers_report()
    view_layer = bpy.context.view_layer
    view_layer.update()
    root = bpy.data.collections.get(name)
    meters = desc.meters
    nodes = oracle["nodes"]
    helpers = [ob for ob in bpy.data.objects if ob.get("maxdrop_helper") == "mirror"]
    mirrors = sum(1 for n in desc.nodes for m in n.converted if m.mirror is not None)
    shears = [ob for ob in bpy.data.objects if ob.get("maxdrop_helper") == "shear"]
    sheared = any(n.sheared and n.parent is None for n in desc.nodes)  # controllers: FixtureScaleAxis
    sections = [ob for ob in bpy.data.objects if ob.get("maxdrop_helper") == "section"]
    sectioned = sum(1 for cd in desc.curves.values() if cd.section is not None)
    check("%s: one object per node, one empty per mirror object, one for top-level sheared nodes, one per section"
          % name, len(desc.nodes) == len(nodes) == len(bpy.data.objects) - len(helpers) - len(shears) - len(sections)
          and len(helpers) == mirrors and len(shears) == int(sheared) and len(sections) == sectioned,
          "%d objects, %d nodes, %d mirror empties, %d shear empties, %d sections" % (
              len(bpy.data.objects), len(nodes), len(helpers), len(shears), len(sections)))
    check("%s: nodes in oracle order" % name, [n.name for n in desc.nodes] == [n["name"] for n in nodes])
    obs = objects_of(desc)
    meshes = {ob.data.name: ob.data for ob in obs if ob.type == 'MESH'}
    handle_of = {ob.as_pointer(): o["handle"] for ob, o in zip(obs, nodes)}
    offset_of = {o["handle"]: (o["offset_pos"], o["offset_rot"], o["offset_scale"]) for o in nodes}
    shading_of = {o["handle"]: next((m.shading for m in node.converted if m.kind == "SUBSURF"), None)
                  for node, o in zip(desc.nodes, nodes)}
    for ob, node, o in zip(obs, desc.nodes, nodes):
        label = "%s/%s" % (name, o["name"])
        parent = handle_of.get(ob.parent.as_pointer()) if ob.parent else None
        check(label + ": parent", parent == o["parent"], "%r vs %r" % (parent, o["parent"]))
        got = max_rows(world_of(ob), meters)
        check(label + ": world matrix", close(got, o["transform"], MATRIX_TOLERANCE),
              "%s vs %s" % (["%.6g" % v for v in got], o["transform"]))
        homes = [c.name for c in ob.users_collection]
        check(label + ": in its layer's collection", homes == [o["layer"]], str(homes))
        flags = (ob.hide_viewport, ob.hide_get(view_layer=view_layer), ob.hide_render, ob.hide_select)
        want = (o["hidden"], o["hidden"], not o["renderable"], o["frozen"])
        if node.kind == convert_scene.LIGHT and not desc.lights[node.light].on or \
                node.emitter is not None and not desc.emitters[node.emitter].on:  # a light switched off
            want = (True, o["hidden"], True, o["frozen"])
        check(label + ": hidden, renderable and frozen flags", flags == want, str(flags))
        if node.emitter is not None:
            check_emitter(label, ob, desc.emitters[node.emitter], o, meters, bool(node.converted))
            continue
        if node.kind in (convert_scene.MESH, convert_scene.CURVE):
            check(label + ": casts shadows as in 3ds Max", ob.visible_shadow == o["cast_shadows"],
                  str(ob.visible_shadow))
        if node.kind == convert_scene.LIGHT:
            check_light(label, ob, desc.lights[node.light], o)
            continue
        if o["camera"] is not None:
            check_camera(label, ob, node, desc, o)
            continue
        if o["shape"] is not None and node.kind == convert_scene.MESH:
            check_extruded(label, ob, node, o, meters, plan)
            if node.converted:
                check_converted(label, ob, node, o, meters, desc)
            continue
        if o["shape"] is not None:
            check_curve(label, ob, o["shape"], meters)
            continue
        primitive = tuple(o["base_class_id"]) in PRIMITIVE_CLASSES  # built from its parameters
        if o["base_verts"] is None and not primitive:
            want = CLASS_NAMES.get(o["base_class_name"], o["base_class_name"])
            check(label + ": placeholder empty", ob.type == 'EMPTY' and ob.get("maxdrop_class") == want,
                  "%s %r" % (ob.type, ob.get("maxdrop_class")))
            continue
        check(label + ": mesh object", ob.type == 'MESH', ob.type)
        if ob.type != 'MESH':
            continue
        check_converted(label, ob, node, o, meters, desc)
        mesh = ob.data
        mw = world_of(ob)
        world = [mw @ v.co for v in mesh.vertices]
        lo = [min(p[k] for p in world) / meters for k in range(3)]
        hi = [max(p[k] for p in world) / meters for k in range(3)]
        if not o["modifiers"]:  # the oracle's box is after the modifiers, the base mesh is built
            check(label + ": world bounding box", close(lo, o["bbox_min"], BBOX_TOLERANCE)
                  and close(hi, o["bbox_max"], BBOX_TOLERANCE),
                  "%s..%s vs %s..%s" % (["%.6g" % v for v in lo], ["%.6g" % v for v in hi], o["bbox_min"],
                                        o["bbox_max"]))
        if primitive:  # the oracle counts the triangles of the TriMesh 3ds Max builds, after the modifiers
            if not o["modifiers"]:
                triangles = sum(len(p.vertices) - 2 for p in mesh.polygons)
                check(label + ": vertex and triangle counts = 3ds Max's", (len(mesh.vertices), triangles) ==
                      (o["eval_verts"], o["eval_faces"]), "%d, %d" % (len(mesh.vertices), triangles))
        else:
            check(label + ": vertex and face counts", (len(mesh.vertices), len(mesh.polygons)) ==
                  (o["base_verts"], o["base_faces"]), "%d, %d" % (len(mesh.vertices), len(mesh.polygons)))
        uv = [layer.name for layer in mesh.uv_layers]
        if listed:
            want = UV_LAYERS[name]
            check(label + ": UV layers", uv == (want.get(o["name"], ["UVMap"]) if isinstance(want, dict) else want),
                  str(uv))
        md = desc.meshes[node.mesh]
        for (uv_name, uv_data), layer in zip(md.uv_layers, mesh.uv_layers):
            got = [c for d in layer.data for c in d.uv]
            check(label + ": UV data of " + uv_name, close(got, uv_data.ravel().tolist(), 1e-6))
        sharp = mesh.attributes.get("sharp_edge")
        count = sum(1 for d in sharp.data if d.value) if sharp else 0
        want = SHARP_EDGES.get(name, SHARP_EDGES_DEFAULT)
        want = want.get(o["name"], want[None]) if isinstance(want, dict) else want
        check(label + ": sharp edges", count == want, str(count))
        flat = mesh.attributes.get("sharp_face")
        if o["name"] in FLAT_SHADED:
            check(label + ": every face flat", flat is not None and all(d.value for d in flat.data))
        else:
            check(label + ": every face smooth", flat is None or not any(d.value for d in flat.data))
        indices = [p.material_index for p in mesh.polygons]
        check(label + ": each face on its material's slot", indices == plan[node.mesh].indices.tolist(),
              str(indices))
        sharing = sorted(handle_of[other.as_pointer()] for other in obs if other.data == mesh)
        # the object offset is baked into the mesh: only the instances with the same offset share it
        same_offset = [h for h in o["instances"] if offset_of[h] == offset_of[o["handle"]]
                       and shading_of[h] == shading_of[o["handle"]]]  # a converted smoother's shading: own mesh
        check(label + ": objects sharing the mesh = oracle instances with its offset", sharing == same_offset,
              str(sharing))
        box = (lo, hi) if o["modifiers"] else (o["bbox_min"], o["bbox_max"])
        center = (Vector(box[0]) + Vector(box[1])) * (meters / 2.0)
        normal_matrix = mw.to_3x3().inverted().transposed()
        faces = [p for p in mesh.polygons if p.area > 1e-12]  # a cone's tip cap: its points all in one place
        if o["name"] in HOLLOW:
            volume = 0.0
            for p in mesh.polygons:
                a = mesh.vertices[p.vertices[0]].co
                for k in range(1, len(p.vertices) - 1):
                    volume += a.dot(mesh.vertices[p.vertices[k]].co.cross(mesh.vertices[p.vertices[k + 1]].co)) / 6
            check(label + ": a closed mesh facing out (positive volume)", volume * mw.determinant() > 0, str(volume))
        elif o["name"] in PLANE_NORMALS:
            up = [(normal_matrix @ p.normal).z * PLANE_NORMALS[o["name"]] > 0 for p in faces]
            check(label + ": normals point %s as in 3ds Max" % ("up" if PLANE_NORMALS[o["name"]] > 0 else "down"),
                  all(up), "%d of %d" % (sum(up), len(up)))
        else:
            outward = [(normal_matrix @ p.normal).dot(mw @ p.center - center) > 0 for p in faces]
            if o["name"] in INSIDE_OUT:
                check(label + ": normals inward as 3ds Max makes them", not any(outward),
                      "%d of %d out" % (sum(outward), len(outward)))
            else:
                check(label + ": normals outward as rendered", all(outward), "%d of %d" % (sum(outward),
                                                                                          len(outward)))
    if name == "instances":
        users = sorted(m.users for m in bpy.data.meshes)
        check("instances: four objects share one mesh, the copy has its own", users == [1, 4], str(users))
    if name == "modifier_pivot":
        check_modifier_pivot(obs, meters)
    if name == "extrude":
        kinds = [ob.type for ob in obs]
        check("extrude: thirteen meshes, the switched-off Extrude a curve",
              kinds == ['MESH'] * 7 + ['CURVE'] + ['MESH'] * 6, str(kinds))
    if name == "shapes":
        curves = sorted(c.name for c in bpy.data.curves)
        shaped = sum(1 for o in nodes if o["shape"] is not None)
        check("shapes: one curve per shape node, one mesh", len(curves) == shaped == 13 and len(meshes) == 1,
              str(curves))
    if name == "shapes_more":
        check_shapes_more(obs, meters)
    if name == "hierarchy":
        mirrored = [n.name for n in desc.nodes if n.mirrored]
        check("hierarchy: FixtureLeaf is the mirrored node", mirrored == ["FixtureLeaf"], str(mirrored))
    layer_names = [c.name for c in root.children] if root else []
    parent_of = {la["name"]: la["parent"] for la in oracle["layers"]}
    kept = {o["layer"] for o in nodes}
    for layer in list(kept):  # a parent layer is kept, nodes or not
        while parent_of[layer] is not None:
            layer = parent_of[layer]
            kept.add(layer)
    order = [la["name"] for la in oracle["layers"]]

    def tree(col):
        return [(c.name, tree(c)) for c in col.children]

    def layer_tree(parent):  # Layer Manager order: every fixture makes a parent layer before its children
        return [(la, layer_tree(la)) for la in order if la in kept and parent_of[la] == parent]
    got = tree(root) if root else []
    check("%s: one collection per layer below the file's collection, nested as the layers" % name,
          root is not None and got == layer_tree(None) and root.name in bpy.context.scene.collection.children,
          "%s: %s" % (root and root.name, got))
    if name == "layers_flags":
        check("layers_flags: two layer collections", layer_names == ["FixtureLayerA", "FixtureLayerB"])
        hidden = [ob.name for ob in obs if ob.hide_viewport and ob.hide_get(view_layer=view_layer)]
        check("layers_flags: one hidden object", hidden == ["FixtureHidden"], str(hidden))
        no_render = [ob.name for ob in obs if ob.hide_render]
        check("layers_flags: one object with hide_render", no_render == ["FixtureNoRender"], str(no_render))
        no_shadow = [ob.name for ob in obs if not ob.visible_shadow]
        check("layers_flags: one object that casts no shadows", no_shadow == ["FixtureNoCastShadow"], str(no_shadow))
        group = bpy.data.objects["FixtureGroup"]
        members = sorted(ob.name for ob in group.children)
        check("layers_flags: the group head is an empty with its members as children",
              group.type == 'EMPTY' and members == ["FixtureGroupA", "FixtureGroupB"], "%s %s" % (group.type, members))
        excluded = [lc.name for lc in view_layer.layer_collection.children[name].children if lc.exclude]
        check("layers_flags: no layer excluded (none is hidden in 3ds Max)", excluded == [], str(excluded))
    if name == "layers_more":
        check_layers_more(root, obs, view_layer)
    if name == "layers_nested":
        check_layers_nested(root, obs, view_layer, oracle)
    if name == "layers_render":
        check_layers_render(root, obs)
    bare = sorted(ob.name for ob in obs if ob.type == 'MESH' and not any(sl.material for sl in ob.material_slots)
                  and ob.name not in BARE_MESHES)
    check("%s: a material on every mesh" % name, bare == [], str(bare))
    check_fixture_materials(name, plan, desc, obs)
    rep = convert_report.gather(desc, source=os.path.basename(path), objects_built=len(obs),
                                meshes_built=len(meshes))
    level, line = build_report.publish(rep)
    text = bpy.data.texts.get(build_report.TEXT_NAME)
    published = text is not None and text.as_string().rstrip("\n") == rep.text()
    # the report counts each modifier class once per node whose stack holds it, applied (an Extrude on a shape, the
    # UVW Maps right above it or a mesh) or not (the rest: the base mesh is built); every modifier of the oracle is
    # one or the other
    split = [len(n.applied) + (len(n.converted) if n.emitter is None else 0) + len(n.modifiers)
             for n in desc.nodes]  # an emitter's converted modifiers are its mesh object's, not the light node's
    check("%s: each modifier applied or not" % name, split == [len(o["modifiers"]) for o in nodes], str(split))
    modified = sum(len(set(n.modifiers)) for n in desc.nodes)
    applied = sum(len(set(n.applied)) for n in desc.nodes)
    issues = len(desc.issues)  # the issues a fixture is made to raise (tests/unit/test_convert_scene.py)
    check("%s: the report counts each applied modifier" % name, sum(rep.modifiers_applied.values()) == applied,
          str(dict(rep.modifiers_applied)))
    converted = sum(len({m.class_name for m in n.converted}) for n in desc.nodes)
    check("%s: the report counts each converted modifier" % name,
          sum(rep.modifiers_converted.values()) == converted, str(dict(rep.modifiers_converted)))

    if modified:
        check("%s: report published, nothing left out but the %d modifiers and %d issues" % (name, modified, issues),
              level == "WARNING" and published and not rep.approximated
              and rep.left_out == sum(rep.modifiers.values()) + issues and sum(rep.modifiers.values()) == modified
              and line.endswith("; %d modifier%s not applied%s. See the text %s." % (
                  modified, "" if modified == 1 else "s", ", %d issue%s" % (issues, "" if issues == 1 else "s")
                  if issues else "", build_report.TEXT_NAME)),
              line)
    elif desc.placeholders:
        held = sum(desc.placeholders.values())
        check("%s: report published, nothing left out but the %d placeholders and %d issues" % (name, held, issues),
              level == "WARNING" and published and rep.left_out == held + issues, line)
    elif issues:
        check("%s: report published, nothing left out but the %d issues" % (name, issues),
              level == "WARNING" and published and rep.left_out == issues, line)
    else:
        check("%s: report published, nothing left out" % name, level == "INFO" and published, line)
    print("COUNTS %s: objects=%d meshes=%d placeholders=%d issues=%d" % (
        name, len(bpy.data.objects), len(bpy.data.meshes), sum(desc.placeholders.values()), len(desc.issues)))
    check_render(name, oracle, obs, desc)
    if name == "lookat":  # imports the file again: last
        check_lookat(path, desc, obs, nodes, meters)
    if name == "vray_lights":
        lit = sorted(ob.name for ob in obs if ob.type == 'LIGHT')
        check("vray_lights: eleven light objects, ten lights (the instance shares one, the scaled one has its own)",
              len(lit) == 11 and len(bpy.data.lights) == 10 and bpy.data.objects["FixturePlane"].data ==
              bpy.data.objects["FixturePlaneInst"].data and bpy.data.objects["FixtureDisc"].data !=
              bpy.data.objects["FixtureDiscScaled"].data, "%s, %d lights" % (lit, len(bpy.data.lights)))
        world = bpy.context.scene.world
        strength = world.node_tree.nodes.get("Background").inputs["Strength"].default_value if world else None
        from maxdrop import options
        check("vray_lights: its dome (white, multiplier 1 in the default units) is the World, strength 1500 / (683 pi) "
              "x Light Strength", world is not None and world.name == "FixtureDome" and strength is not None and
              abs(strength - 1500.0 / (683.0 * math.pi) * options.LIGHT_STRENGTH) < 1e-5 and
              bpy.data.worlds.get(USER_WORLD) is not None, "%s %s" % (world and world.name, strength))
        check_light_strength(path)
    if name == "vray_dome":
        check_dome(desc)
    if name == "vray_mesh_light":
        lit = sorted(ob.name for ob in obs if ob.type == 'MESH' and ob.name.startswith("FixtureEmitter")
                     and ob.name != "FixtureEmitterSource")
        none = bpy.data.objects.get("FixtureEmitterNone")
        check("vray_mesh_light: three emitters, three Emission materials, the mesh light without a mesh an empty",
              lit == ["FixtureEmitter", "FixtureEmitterOwn", "FixtureEmitterW"] and len(bpy.data.materials) == 3
              and none is not None and none.type == 'EMPTY', "%s %d" % (lit, len(bpy.data.materials)))
        check_spread(desc, meters)
    if name in ("lights_standard", "lights_photometric"):
        lit = [ob for ob in obs if ob.type == 'LIGHT']
        shared = {"lights_standard": ("StdOmni", "StdOmniInst"), "lights_photometric": ("PhPoint", "PhPointInst")}
        a, b = (bpy.data.objects[n] for n in shared[name])
        count = {"lights_standard": 13, "lights_photometric": 17}[name]
        check("%s: %d light objects, the instance shares its light" % (name, count),
              len(lit) == count and len(bpy.data.lights) == count - 1 and a.data == b.data, "%d, %d lights" % (
                  len(lit), len(bpy.data.lights)))
