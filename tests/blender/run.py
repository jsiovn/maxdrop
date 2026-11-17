# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fixture tests of the new pipeline inside Blender: every tests/fixtures/*.max imported through the operator
(import_scene.maxdrop, default options: Units Auto), compared with its 3ds Max oracle
(tests/fixtures/<name>.oracle.json) and with convert.scene.read of the same file.

Run headless with an isolated profile so your own preferences are never touched:
  $env:BLENDER_USER_RESOURCES="<scratch>\\profile"
  & blender --background --factory-startup --python-exit-code 1 --python tests\\blender\\run.py [-- <file.max> ...]

Per fixture, into an emptied scene, below a collection named after the file with one collection per layer
(build.collections), objects found by node name (objects are made in walk order, so the second node of a name is
"<name>.001" in the emptied scene): node order and names, parents, each object in its layer's collection, the oracle's
hidden, renderable and frozen flags, world matrices (1e-4, in file units), world bounding boxes of the meshes (1e-3),
vertex and face counts, UV layers, sharp edges and flat faces, material indices, which objects share a mesh (the
oracle's instances), outward normals as rendered (the inverse transpose of the world matrix times each face normal
points away from the oracle's bounding box center, also on the mirrored object) and the class of each placeholder. The
oracle has no map channels or smoothing groups: those expectations come from the fixture scripts (tools/fixtures/*.ms).
shapes: each shape node a curve object (3D, FREE handles) with the oracle's splines, point counts and cyclic flags,
its points where 3ds Max has its knots, each segment's middle (mathutils.geometry.interpolate_bezier) where 3ds Max
interpolates it (the straight segment included), the resolution from the steps, a bevel and faces only on the
renderable FixtureLine.
layers_flags: two layer collections, one hidden object, one with hide_render, the group head as the parent of its two
members. modifier_pivot: a node with modifiers gets its base mesh (no bounding box check, the oracle's is after the
modifiers), the report names the modifiers not applied, and the node whose pivot alone is rotated keeps its object
in place. Each fixture's import report is published (build.report) and must say nothing was left out; the one the
operator published for vray_wrappers lists its three peeled wrappers by class. A changed layers_flags description
checks a hidden, a frozen, a non-rendering and a nested layer, which no fixture has. A hand-made description with sheared local matrices (top-level and parented, hidden, a zero scale) checks that
Blender's world matrices equal the products of the locals, through the helper empty for top-level ones. Material
slots (build with convert.materials.assign): vray_wrappers' Multi/Sub-Object box with its faces set to IDs 1, 3
and 7 lands them on the slots of FixtureSubOne, an empty one (ID 3 is switched off) and FixtureSubSeven; the same
mesh shared with the Shell box gets slots linked to each object; standard_physical's boxes one slot each.
Materials (build.materials through the operator): each face on its material's slot, each slot's material named after
the 3ds Max material, its Principled inputs equal to the MaterialIR the same file converts to (values, or linked when
a texture graph drives them), the render method, one Image Texture node per file; vray_maps' Mapping values by hand
from its authoring script, texture nodes without an image and each missing file listed once by name; vray_maps,
texmap_rules, corona_maps, corona_light and vray_texmaps copied beside generated PNGs load every image in its color
space, one datablock per file and color space, the report counts every file as found; hand-made IRs check shared
images, a missing file, the materials counted by class, Thin Wall (set on 5.x, counted on 4.x), a name clash,
BLENDED / DITHERED and every node kind.
Prints `FIXTURES PASSED` (exit 0) or `FIXTURES FAILED` (exit 1).
"""
import collections
import glob
import json
import math
import os
import shutil
import sys
import tempfile
import traceback

import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import interpolate_bezier

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MATRIX_TOLERANCE = 1e-4
BBOX_TOLERANCE = 1e-3
UV_LAYERS = {  # mapcoords:true in the script gives channel 1
    "box_poly_standard": ["UVMap"],
    "corona_layered": ["UVMap"],
    "corona_legacy": ["UVMap"],
    "corona_light": ["UVMap"],
    "corona_maps": ["UVMap"],
    "corona_physical": ["UVMap"],
    "editable_mesh": ["UVMap"],
    "extrude": [],  # per mesh: EXTRUDE_UV_LAYERS
    "gamma_swatches": ["UVMap"],
    "hierarchy": [],
    "instances": ["UVMap"],
    "layers_flags": [],
    "modifier_pivot": ["UVMap"],  # FixtureBent's UVW Map writes channel 1 (applied, the Bend above it is not)
    "multi_uv": ["UVMap", "UVChannel_2", "UVChannel_3"],
    "shapes": ["UVMap"],  # FixtureBox; the shapes are curves
    "stack_basic": ["UVMap"],  # FixtureTurbo's UVW Map writes channel 1; no other modifier is applied
    "standard_physical": ["UVMap"],
    "texmap_rules": ["UVMap"],
    "units_cm": ["UVMap"],
    "units_in": ["UVMap"],
    "units_mm": ["UVMap"],
    "vray_basic": ["UVMap"],
    "vray_maps": ["UVMap"],
    "vray_texmaps": ["UVMap"],
    "vray_wrappers": ["UVMap"],
    "uvwmap": {"FixtureUVWGizmo": ["UVMap", "UVChannel_2"], "FixtureUVWTwo": ["UVMap", "UVChannel_3"]},  # else UVMap
    "uvwmap_oblique": ["UVMap"],
}
# editable_mesh: group 1 on top and bottom, 2 on the sides; a box with a group per side: 12; modifier_pivot's box of
# four height segments: 4 x 4 vertical side edges and both rims
SHARP_EDGES = {"editable_mesh": 8, "modifier_pivot": 24,
               # boxes of 3 x 2 x 2 segments: 28; the cylinder's rims 2 x 16; the sphere is smooth
               "uvwmap": {"FixtureUVWCyl": 32, "FixtureUVWSphere": 0, "FixtureUVWSharedB": 12, None: 28},
               # smooth spheres, the rims of a 10-sided cylinder
               "uvwmap_oblique": {"FixtureUVWObliqueCap": 20, None: 0}}
SHARP_EDGES_DEFAULT = 12
# extrude (Generate Mapping Coords on two nodes); sharp edges: the vertical edges at corner knots, one per level, and
# both rims of every capped outline; V - E + F: a solid 2, one with a round tunnel 0, a ring and its island 0 + 2
EXTRUDE_UV_LAYERS = {"FixtureExtRect": ["UVMap"], "FixtureExtAdaptive": ["UVMap"],
                     "FixtureUVWExtrude": ["UVMap"]}  # uvwmap: no mapping from the Extrude, the UVW Map's
EXTRUDE_SHARP_EDGES = {"FixtureExtRect": 16, "FixtureExtL": 18, "FixtureExtHole": 68, "FixtureExtIsland": 36,
                       "FixtureExtOpen": 0, "FixtureExtMirror": 72, "FixtureExtAdaptive": 256, "FixtureUVWExtrude": 12}
EXTRUDE_EULER = {"FixtureExtRect": 2, "FixtureExtL": 2, "FixtureExtHole": 0, "FixtureExtIsland": 2,
                 "FixtureExtOpen": None, "FixtureExtMirror": 2, "FixtureExtAdaptive": 2, "FixtureUVWExtrude": 2}
VALUE_TOLERANCE = 1e-4
SPECULAR_LEVEL = 0.5  # the IR's specular is a reflection weight: 1 is Blender's Specular IOR Level 0.5
DEG = math.pi / 180.0
failures = []


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
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)
    for text in list(bpy.data.texts):
        bpy.data.texts.remove(text)
    for material in list(bpy.data.materials):
        bpy.data.materials.remove(material)


def close(a, b, tolerance):
    return len(a) == len(b) and all(abs(x - y) <= tolerance for x, y in zip(a, b))


def world_of(ob):
    """ob's world matrix: matrix_world, or for an object hidden in the viewport (left out of the evaluated scene,
    so its matrix_world is never updated) the same product Blender evaluates, up the parent chain. A visible child
    of a hidden parent is read from matrix_world: Blender must place it."""
    if not ob.hide_viewport:
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
    if name == "vray_wrappers":
        check_wrappers_report()
    view_layer = bpy.context.view_layer
    view_layer.update()
    root = bpy.data.collections.get(name)
    meters = desc.meters
    nodes = oracle["nodes"]
    check("%s: one object per node" % name, len(desc.nodes) == len(nodes) == len(bpy.data.objects),
          "%d objects, %d nodes" % (len(bpy.data.objects), len(nodes)))
    check("%s: nodes in oracle order" % name, [n.name for n in desc.nodes] == [n["name"] for n in nodes])
    obs = objects_of(desc)
    meshes = {ob.data.name: ob.data for ob in obs if ob.type == 'MESH'}
    handle_of = {ob.as_pointer(): o["handle"] for ob, o in zip(obs, nodes)}
    offset_of = {o["handle"]: (o["offset_pos"], o["offset_rot"], o["offset_scale"]) for o in nodes}
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
        check(label + ": hidden, renderable and frozen flags",
              flags == (o["hidden"], o["hidden"], not o["renderable"], o["frozen"]), str(flags))
        if o["shape"] is not None and node.kind == convert_scene.MESH:
            check_extruded(label, ob, node, o, meters, plan)
            continue
        if o["shape"] is not None:
            check_curve(label, ob, o["shape"], meters)
            continue
        if o["base_verts"] is None:
            check(label + ": placeholder empty", ob.type == 'EMPTY' and ob.get("maxdrop_class") == o["base_class_name"],
                  "%s %r" % (ob.type, ob.get("maxdrop_class")))
            continue
        check(label + ": mesh object", ob.type == 'MESH', ob.type)
        if ob.type != 'MESH':
            continue
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
        check(label + ": vertex and face counts", (len(mesh.vertices), len(mesh.polygons)) ==
              (o["base_verts"], o["base_faces"]), "%d, %d" % (len(mesh.vertices), len(mesh.polygons)))
        uv = [layer.name for layer in mesh.uv_layers]
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
        check(label + ": every face smooth", flat is None or not any(d.value for d in flat.data))
        indices = [p.material_index for p in mesh.polygons]
        check(label + ": each face on its material's slot", indices == plan[node.mesh].indices.tolist(),
              str(indices))
        sharing = sorted(handle_of[other.as_pointer()] for other in obs if other.data == mesh)
        # the object offset is baked into the mesh: only the instances with the same offset share it
        same_offset = [h for h in o["instances"] if offset_of[h] == offset_of[o["handle"]]]
        check(label + ": objects sharing the mesh = oracle instances with its offset", sharing == same_offset,
              str(sharing))
        box = (lo, hi) if o["modifiers"] else (o["bbox_min"], o["bbox_max"])
        center = (Vector(box[0]) + Vector(box[1])) * (meters / 2.0)
        normal_matrix = mw.to_3x3().inverted().transposed()
        outward = [(normal_matrix @ p.normal).dot(mw @ p.center - center) > 0 for p in mesh.polygons]
        check(label + ": normals outward as rendered", all(outward), "%d of %d" % (sum(outward), len(outward)))
    if name == "instances":
        users = sorted(m.users for m in bpy.data.meshes)
        check("instances: four objects share one mesh, the copy has its own", users == [1, 4], str(users))
    if name == "modifier_pivot":
        check_modifier_pivot(obs, meters)
    if name == "extrude":
        kinds = [ob.type for ob in obs]
        check("extrude: seven meshes, the switched-off Extrude a curve", kinds == ['MESH'] * 7 + ['CURVE'],
              str(kinds))
    if name == "shapes":
        curves = sorted(c.name for c in bpy.data.curves)
        shaped = sum(1 for o in nodes if o["shape"] is not None)
        check("shapes: one curve per shape node, one mesh", len(curves) == shaped == 13 and len(meshes) == 1,
              str(curves))
    if name == "hierarchy":
        mirrored = [n.name for n in desc.nodes if n.mirrored]
        check("hierarchy: FixtureLeaf is the mirrored node", mirrored == ["FixtureLeaf"], str(mirrored))
    layer_names = [c.name for c in root.children] if root else []
    expected = [la["name"] for la in oracle["layers"] if any(o["layer"] == la["name"] for o in nodes)]
    check("%s: one collection per layer below the file's collection" % name,
          root is not None and layer_names == expected and root.name in bpy.context.scene.collection.children,
          "%s: %s" % (root and root.name, layer_names))
    if name == "layers_flags":
        check("layers_flags: two layer collections", layer_names == ["FixtureLayerA", "FixtureLayerB"])
        hidden = [ob.name for ob in obs if ob.hide_viewport and ob.hide_get(view_layer=view_layer)]
        check("layers_flags: one hidden object", hidden == ["FixtureHidden"], str(hidden))
        no_render = [ob.name for ob in obs if ob.hide_render]
        check("layers_flags: one object with hide_render", no_render == ["FixtureNoRender"], str(no_render))
        group = bpy.data.objects["FixtureGroup"]
        members = sorted(ob.name for ob in group.children)
        check("layers_flags: the group head is an empty with its members as children",
              group.type == 'EMPTY' and members == ["FixtureGroupA", "FixtureGroupB"], "%s %s" % (group.type, members))
        excluded = [lc.name for lc in view_layer.layer_collection.children[name].children if lc.exclude]
        check("layers_flags: no layer excluded (none is hidden in 3ds Max)", excluded == [], str(excluded))
    bare = sorted(ob.name for ob in obs if ob.type == 'MESH' and not any(sl.material for sl in ob.material_slots))
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
    split = [len(n.applied) + len(n.modifiers) for n in desc.nodes]
    check("%s: each modifier applied or not" % name, split == [len(o["modifiers"]) for o in nodes], str(split))
    modified = sum(len(set(n.modifiers)) for n in desc.nodes)
    applied = sum(len(set(n.applied)) for n in desc.nodes)
    issues = len(desc.issues)  # the issues a fixture is made to raise (tests/unit/test_convert_scene.py)
    check("%s: the report counts each applied modifier" % name, sum(rep.modifiers_applied.values()) == applied,
          str(dict(rep.modifiers_applied)))
    if modified:
        check("%s: report published, nothing left out but the %d modifiers and %d issues" % (name, modified, issues),
              level == "WARNING" and published and not rep.approximated
              and rep.left_out == sum(rep.modifiers.values()) + issues and sum(rep.modifiers.values()) == modified
              and line.endswith("; %d modifier%s not applied%s. See the text %s." % (
                  modified, "" if modified == 1 else "s", ", %d issue%s" % (issues, "" if issues == 1 else "s")
                  if issues else "", build_report.TEXT_NAME)),
              line)
    else:
        check("%s: report published, nothing left out" % name, level == "INFO" and published, line)
    print("COUNTS %s: objects=%d meshes=%d placeholders=%d issues=%d" % (
        name, len(bpy.data.objects), len(bpy.data.meshes), sum(desc.placeholders.values()), len(desc.issues)))


def check_extruded(label, ob, node, o, meters, plan):
    """A shape under an Extrude: a mesh with the oracle's world box, vertex count and triangle count, closed with
    normals outward as rendered (the signed volume of the world mesh, times the sign of the world matrix's
    determinant, is positive) when capped, its UV layers, sharp edges and material slots."""
    check(label + ": mesh object", ob.type == 'MESH', ob.type)
    if ob.type != 'MESH':
        return
    mesh, mw = ob.data, world_of(ob)
    world = [mw @ v.co for v in mesh.vertices]
    lo = [min(p[k] for p in world) / meters for k in range(3)]
    hi = [max(p[k] for p in world) / meters for k in range(3)]
    check(label + ": world bounding box", close(lo, o["bbox_min"], BBOX_TOLERANCE)
          and close(hi, o["bbox_max"], BBOX_TOLERANCE),
          "%s..%s vs %s..%s" % (["%.6g" % v for v in lo], ["%.6g" % v for v in hi], o["bbox_min"], o["bbox_max"]))
    triangles = sum(len(p.vertices) - 2 for p in mesh.polygons)
    check(label + ": vertex and triangle counts", (len(mesh.vertices), triangles) == (o["eval_verts"], o["eval_faces"]),
          "%d, %d" % (len(mesh.vertices), triangles))
    name = o["name"]
    euler = EXTRUDE_EULER[name]
    if euler is not None:
        uses = collections.Counter(tuple(sorted(e.vertices)) for p in mesh.polygons for e in
                                   (mesh.edges[mesh.loops[i].edge_index] for i in p.loop_indices))
        check(label + ": closed (every edge has two faces)", set(uses.values()) == {2}, str(set(uses.values())))
        check(label + ": V - E + F", len(mesh.vertices) - len(mesh.edges) + len(mesh.polygons) == euler)
        volume = 0.0
        for p in mesh.polygons:
            v = [world[i] for i in p.vertices]
            for k in range(1, len(v) - 1):
                volume += v[0].dot(v[k].cross(v[k + 1])) / 6.0
        check(label + ": normals outward as rendered", volume * mw.to_3x3().determinant() > 0, "%g" % volume)
    uv = [layer.name for layer in mesh.uv_layers]
    check(label + ": UV layers", uv == EXTRUDE_UV_LAYERS.get(name, []), str(uv))
    sharp = mesh.attributes.get("sharp_edge")
    count = sum(1 for d in sharp.data if d.value) if sharp else 0
    check(label + ": sharp edges", count == EXTRUDE_SHARP_EDGES[name], str(count))
    indices = [p.material_index for p in mesh.polygons]
    check(label + ": each face on its material's slot", indices == plan[node.mesh].indices.tolist(), str(indices))
    check(label + ": a material", any(sl.material for sl in ob.material_slots))


def check_curve(label, ob, shape, meters):
    """A shape node's curve object against the oracle's knots (object space: no fixture shape has an object
    offset): splines, points, cyclic flags, each segment's middle, resolution and bevel."""
    check(label + ": curve object", ob.type == 'CURVE', ob.type)
    if ob.type != 'CURVE':
        return
    cu = ob.data
    want = shape["splines"]
    got = [(len(sp.bezier_points), sp.use_cyclic_u, sp.type) for sp in cu.splines]
    check(label + ": splines, points and cyclic flags", got == [(len(w["knots"]), w["closed"], 'BEZIER') for w in want],
          str(got))
    check(label + ": 3D", cu.dimensions == '3D', cu.dimensions)
    steps = 12 if shape["adaptive"] else shape["steps"] + 1
    check(label + ": resolution from the steps", cu.resolution_u == steps and
          all(sp.resolution_u == steps for sp in cu.splines), "%d vs %d" % (cu.resolution_u, steps))
    if shape["renderable"]:
        check(label + ": a bevel of the thickness", abs(cu.bevel_depth - shape["thickness"] / 2 * meters) < 1e-9 and
              cu.bevel_resolution == (shape["sides"] - 4) // 2, "%g, %d" % (cu.bevel_depth, cu.bevel_resolution))
    else:
        check(label + ": no bevel", cu.bevel_depth == 0, str(cu.bevel_depth))
    for k, (sp, w) in enumerate(zip(cu.splines, want)):
        pts = sp.bezier_points
        n = len(pts)
        knots = [list(p.co / meters) for p in pts]
        check("%s spline %d: points at the knots" % (label, k),
              close([c for p in knots for c in p], [c for x in w["knots"] for c in x["pos"]], MATRIX_TOLERANCE))
        check("%s spline %d: FREE handles" % (label, k),
              all(p.handle_left_type == p.handle_right_type == 'FREE' for p in pts))
        mids, expected = [], []
        for j, x in enumerate(w["knots"]):
            if x["mid"] is None:
                continue
            a, b = pts[j], pts[(j + 1) % n]
            mid = interpolate_bezier(a.co, a.handle_right, b.handle_left, b.co, 3)[1]
            mids += list(mid / meters)
            expected += x["mid"]
        check("%s spline %d: segment middles where 3ds Max interpolates them" % (label, k),
              close(mids, expected, MATRIX_TOLERANCE), "%s vs %s" % (["%.6g" % v for v in mids], expected))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = ob.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    faces = len(mesh.polygons)
    evaluated.to_mesh_clear()
    check(label + ": faces exactly when it renders", (faces > 0) == shape["renderable"], str(faces))


def check_modifier_pivot(obs, meters):
    """FixtureBent's pivot alone is turned 30 degrees about Z: its base mesh lands where the source's does, moved by
    the 30 units between the two nodes (the offset rotation undoes the pivot's)."""
    by_name = {ob.name: ob for ob in obs}
    src, bent = by_name["FixtureSource"], by_name["FixtureBent"]
    a = [c / meters for v in src.data.vertices for c in src.matrix_world @ v.co]
    b = [c / meters for v in bent.data.vertices for c in bent.matrix_world @ v.co - Vector((30 * meters, 0, 0))]
    check("modifier_pivot: FixtureBent has a mesh of its own", src.data != bent.data)
    check("modifier_pivot: the rotated pivot leaves the object in place", close(b, a, BBOX_TOLERANCE))


def _irs(path):
    """convert.scene.read of path and the slot plan of its materials, converted with the texture-map rules."""
    from maxdrop.convert import materials as convert_materials
    from maxdrop.convert import scene as convert_scene
    from maxdrop.convert import texmaps as convert_texmaps
    from maxdrop.reader import assets, cfb, materials as reader_materials, scene as reader_scene
    desc = convert_scene.read(path)
    with cfb.CompoundFile(path) as cf:
        sc = reader_scene.Scene.from_file(cf)
        graph = reader_materials.MaterialGraph(sc)
        tex = convert_texmaps.TexmapConverter(graph, assets.AssetTable.from_file(cf))
        conv = convert_materials.MaterialConverter(graph, texmaps=tex)
        slots = convert_materials.assign(desc, convert_materials.node_materials(sc, desc), conv)
    return desc, slots


def _principled(material):
    nodes = [n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"]
    return nodes[0] if len(nodes) == 1 else None


def _value_ok(socket, want):
    got = socket.default_value
    if isinstance(want, (tuple, list)):
        return close(list(got)[:3], list(want)[:3], VALUE_TOLERANCE)
    return abs(float(got) - float(want)) <= VALUE_TOLERANCE


def _mean(v):
    return sum(v[:3]) / 3.0 if isinstance(v, (tuple, list)) else v


def _images_of(ir):
    """The texmaps.Image nodes of every texture graph of an IR, each once."""
    from maxdrop.convert import texmaps as tx
    seen, out = set(), []
    stack = [g.root for g in ir.textures.values()]
    while stack:
        n = stack.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        if isinstance(n, tx.Image):
            out.append(n)
        stack.extend(tx._children(n))
    return out


MAP, LOST = "map", "lost"  # what _fold gives for a graph a node drives, and for one whose images are all missing


def _fold(n, present):
    """What build.materials makes of a texture graph: MAP when a node drives the input, LOST when the missing images
    leave nothing, else the constant it folds to. present: whether the graph's image files were found. Written from
    the builder's rules (a missing side of a Mix or Multiply gives the other, a Composite drops missing layers)."""
    from maxdrop.convert import texmaps as tx
    if isinstance(n, tx.Constant):
        return n.value
    if isinstance(n, tx.Image):
        return MAP if present else LOST
    if isinstance(n, tx.Invert):
        v = _fold(n.input, present)
        if v in (MAP, LOST):
            return v
        return tuple(1.0 - c for c in v) if isinstance(v, tuple) else 1.0 - v
    if isinstance(n, tx.Mix):
        a, b = _fold(n.a, present), _fold(n.b, present)
        return (b if a is LOST else a) if LOST in (a, b) else MAP
    if isinstance(n, tx.Multiply):
        a, b = _fold(n.a, present), _fold(n.b, present)
        if LOST in (a, b):
            other = b if a is LOST else a
            return MAP if other is MAP else LOST
        if MAP in (a, b):
            return MAP
        return tuple(x * y for x, y in zip(a, b)) if isinstance(a, tuple) else a * b
    if isinstance(n, tx.ColorCorrect):
        v = _fold(n.input, present)
        changes = n.hue % 1.0 != 0.0 or n.saturation != 1.0 or n.brightness or n.contrast or n.gain != 1.0 \
            or n.gamma != 1.0
        return v if v is LOST or not changes else MAP
    if isinstance(n, tx.Composite):
        layers = [(v, o) for v, o in ((_fold(layer, present), o) for layer, o in n.layers) if v is not LOST]
        if not layers:
            return LOST
        return layers[0][0] if len(layers) == 1 and layers[0][1] >= 1.0 else MAP
    image = tx.first_image(n)
    return _fold(image, present) if image is not None else LOST


def _normal_linked(tex, present):
    from maxdrop.convert import texmaps as tx
    linked = False
    for key in ("normal", "bump"):
        if key in tex:
            r = tex[key].root
            if isinstance(r, tx.NormalMap):
                linked = linked or _fold(r.input, present) is MAP or (
                    r.bump is not None and _fold(r.bump.input, present) is MAP)
            else:
                linked = linked or _fold(r.input if isinstance(r, tx.Bump) else r, present) is MAP
    return linked


def check_principled(label, material, ir, present=False):
    """A Blender material against its MaterialIR: every Principled input (linked when a node drives it, else the
    value the graph folds to, or the IR's when its images are missing), the render method, one Image Texture node
    per file. present: whether the texture files were found."""
    p = _principled(material) if material is not None and material.node_tree else None
    check(label + ": one Principled BSDF", p is not None)
    if p is None:
        return
    tex = ir.textures
    wants = [
        ("Base Color", "base_color", ir.base_color.value, None),
        ("Metallic", "metallic", ir.metallic.value, 1.0),
        ("Roughness", "roughness", ir.roughness.value, 1.0),
        ("Specular IOR Level", "specular", ir.specular.value, SPECULAR_LEVEL),
        ("Transmission Weight", "transmission", ir.transmission.value, 1.0),
        ("Emission Color", "emission_color", ir.emission_color.value, None),
        ("Alpha", "alpha", ir.alpha.value, 1.0),
    ]
    alpha = None
    for socket, key, want, scale in wants:
        s = p.inputs[socket]
        folded = _fold(tex[key].root, present) if key in tex else LOST
        linked = folded is MAP
        if folded not in (MAP, LOST):
            want = folded
        if scale is not None:
            want = _mean(want) * scale
        if socket == "Alpha":
            alpha = None if linked else want
        check("%s: %s %s" % (label, socket, "linked" if linked else "value"),
              s.is_linked == linked and (linked or _value_ok(s, want)),
              "linked %s, %r vs %r" % (s.is_linked, tuple(s.default_value) if hasattr(s.default_value, "__len__")
                                       else s.default_value, want))
    values = [("IOR", ir.ior), ("Emission Strength", ir.emission_strength), ("Coat Weight", ir.coat_weight),
              ("Coat Roughness", ir.coat_roughness), ("Coat IOR", ir.coat_ior), ("Coat Tint", ir.coat_color),
              ("Subsurface Weight", ir.subsurface_weight)]
    for socket, want in values:
        check("%s: %s" % (label, socket), _value_ok(p.inputs[socket], want),
              "%r vs %r" % (p.inputs[socket].default_value, want))
    normal = _normal_linked(tex, present)
    check(label + ": Normal linked iff a normal or bump map with its image", p.inputs["Normal"].is_linked == normal)
    thin = p.inputs.get("Thin Wall")
    check(label + ": Thin Wall", (thin is None and bpy.app.version < (5, 0, 0)) or
          (thin is not None and bool(thin.default_value) == ir.thin_walled))
    method = 'BLENDED' if alpha is not None and alpha < 1.0 else 'DITHERED'
    check(label + ": surface_render_method", material.surface_render_method == method,
          "%s vs %s" % (material.surface_render_method, method))
    want_images = sorted({img.name for img in _images_of(ir)})
    got_images = sorted({n.label for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"})
    check(label + ": one Image Texture node per file", got_images == want_images, "%s vs %s" % (got_images,
                                                                                               want_images))
    loose = [n.label for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.image is None
             and any(o.is_linked for o in n.outputs)]
    check(label + ": an Image Texture node without an image feeds nothing", loose == [], str(loose))


def check_fixture_materials(name, plan, desc, obs):
    """Each face slot of each imported object holds a material equal to the IR the same file converts to (plan:
    the slot plan of _irs)."""
    by_index = {node.index: ob for node, ob in zip(desc.nodes, obs)}
    checked = set()
    for slots in plan.values():
        for s, irs in enumerate(slots.slots):
            for node, ir in zip(slots.users, irs):
                ob = by_index[node]
                material = ob.material_slots[s].material if s < len(ob.material_slots) else None
                if ir is None:
                    check("%s/%s: slot %d empty" % (name, ob.name, s), material is None)
                    continue
                if material is None or material.name in checked:
                    check("%s/%s: slot %d has a material" % (name, ob.name, s), material is not None)
                    continue
                checked.add(material.name)
                check("%s/%s: material named after the 3ds Max material" % (name, material.name),
                      material.name.split(".")[0] == (ir.name or "Material").split(".")[0], ir.name)
                check_principled("%s/%s" % (name, material.name), material, ir)
    if name == "vray_maps":
        check_vray_maps_nodes(textured=False)
        text = bpy.data.texts.get("MaxDrop Report")
        lines = text.as_string().split("\n") if text else []
        names = sorted(("fixture_diffuse.png", "fixture_reflect.png", "fixture_gloss.png", "fixture_bump.png",
                        "fixture_opacity.png", "fixture_normal.png", "fixture_normal_bump.png"), key=str.casefold)
        at = lines.index("  Textures not found: 7") if "  Textures not found: 7" in lines else -1
        check("vray_maps: the report names each texture not found, once, by file name",
              at >= 0 and lines[at + 1:at + 8] == ["    " + n for n in names], "\n".join(lines[-14:]))
        empty = [n.label for m in bpy.data.materials for n in m.node_tree.nodes
                 if n.bl_idname == "ShaderNodeTexImage" and n.image is not None]
        check("vray_maps: texture nodes without an image when the files are missing", empty == [], str(empty))


def check_wrappers_report():
    """Right after the operator imported vray_wrappers: the text MaxDrop Report counts the materials and lists the
    wrappers it peeled by class, and the summary warns about them."""
    text = bpy.data.texts.get("MaxDrop Report")
    lines = text.as_string().split("\n") if text else []
    check("vray_wrappers: the report counts the materials built",
          any(line.startswith("Materials built: ") for line in lines), "\n".join(lines))
    check("vray_wrappers: the report lists the peeled wrappers by class",
          "  Wrappers peeled to their sub-material, by class: Shell Material 1, VRay2SidedMtl 1, VRayBlendMtl 1"
          in lines and lines.index("Approximated:") < lines.index(
              "  Wrappers peeled to their sub-material, by class: Shell Material 1, VRay2SidedMtl 1, VRayBlendMtl 1"),
          "\n".join(lines))


def _expected_mapping(tiling, offset, w_degrees):
    """The Mapping node values for a W angle only: location = 0.5 - R S (0.5 + offset), by hand."""
    c, s = math.cos(w_degrees * DEG), math.sin(w_degrees * DEG)
    x, y = tiling[0] * (0.5 + offset[0]), tiling[1] * (0.5 + offset[1])
    return (0.5 - (c * x - s * y), 0.5 - (s * x + c * y), 0.0), (0.0, 0.0, w_degrees * DEG), (tiling[0], tiling[1], 1.0)


def _mapping_of(material, label):
    """The values of the Mapping node feeding the Image Texture node labelled label."""
    tex = next(n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.label == label)
    link = tex.inputs["Vector"].links[0] if tex.inputs["Vector"].is_linked else None
    m = link.from_node if link is not None else None
    if m is None or m.bl_idname != "ShaderNodeMapping":
        return None, tex
    return tuple(tuple(m.inputs[k].default_value) for k in ("Location", "Rotation", "Scale")), tex


def _from(socket):
    """The node feeding an input, None when it is not linked."""
    return socket.links[0].from_node if socket.is_linked else None


def _input(node, identifier):
    return next(s for s in node.inputs if s.identifier == identifier)


def check_vray_maps_nodes(textured):
    """FixtureVRayMaps' bitmaps: tiling, offset and W angle as Mapping values (the authoring script's numbers),
    extension REPEAT. With its textures: the gloss map inverted (1 - x) into the Mix of the roughness, the bump map a
    Bump node, FixtureVRayNormal's Normal Map node (strength 0.85, its green flipped) under its bump map's Bump node.
    Without them: no Normal Map node and the Normal input free."""
    m = bpy.data.materials.get("FixtureVRayMaps")
    for file, tile, offset, angle in (("fixture_diffuse.png", 2.0, 0.1, 15.0), ("fixture_reflect.png", 3.0, 0.2, 25.0),
                                      ("fixture_gloss.png", 4.0, 0.3, 35.0), ("fixture_bump.png", 5.0, 0.4, 45.0),
                                      ("fixture_opacity.png", 6.0, 0.5, 55.0)):
        got, tex = _mapping_of(m, file)
        want = _expected_mapping((tile, tile + 0.5), (offset, offset + 0.05), angle)
        ok = got is not None and all(close(g, w, VALUE_TOLERANCE) for g, w in zip(got, want))
        check("vray_maps/%s: Mapping location, rotation, scale" % file, ok, "%s vs %s" % (got, want))
        check("vray_maps/%s: extension REPEAT" % file, tex.extension == 'REPEAT', tex.extension)
    n = bpy.data.materials.get("FixtureVRayNormal")
    if not textured:
        check("vray_maps without textures: no Normal Map node, the Normal input free",
              not any(x.bl_idname == "ShaderNodeNormalMap" for x in n.node_tree.nodes)
              and not _principled(n).inputs["Normal"].is_linked)
        return
    mix = _from(_principled(m).inputs["Roughness"])
    inv = _from(_input(mix, "B_Float")) if mix is not None and mix.bl_idname == "ShaderNodeMix" else None
    gloss = _from(inv.inputs[1]) if inv is not None and inv.bl_idname == "ShaderNodeMath" else None
    check("vray_maps: the gloss map as 1 - x into the roughness Mix at 73 %, glossiness 1 beside it",
          gloss is not None and gloss.label == "fixture_gloss.png" and inv.operation == 'SUBTRACT'
          and abs(inv.inputs[0].default_value - 1.0) < 1e-6 and abs(_input(mix, "Factor_Float").default_value - 0.73)
          < 1e-5 and abs(_input(mix, "A_Float").default_value) < 1e-6)
    bump = _from(_principled(m).inputs["Normal"])
    check("vray_maps: the bump map through a Bump node of strength 0.64",
          bump is not None and bump.bl_idname == "ShaderNodeBump" and not bump.invert
          and abs(bump.inputs["Strength"].default_value - 0.64) < 1e-5
          and _from(bump.inputs["Height"]).label == "fixture_bump.png")
    top = _from(_principled(n).inputs["Normal"])
    nm = _from(top.inputs["Normal"]) if top is not None and top.bl_idname == "ShaderNodeBump" else None
    comb = _from(nm.inputs["Color"]) if nm is not None and nm.bl_idname == "ShaderNodeNormalMap" else None
    green = _from(comb.inputs["Green"]) if comb is not None and comb.bl_idname == "ShaderNodeCombineColor" else None
    sep = _from(green.inputs[1]) if green is not None and green.bl_idname == "ShaderNodeMath" else None
    check("vray_maps: FixtureVRayNormal: Bump (its bump map) over a Normal Map node of strength 0.85, green 1 - G",
          sep is not None and sep.bl_idname == "ShaderNodeSeparateColor"
          and green.inputs[1].links[0].from_socket.identifier == "Green"
          and _from(comb.inputs["Red"]) == sep and abs(nm.inputs["Strength"].default_value - 0.85) < 1e-5
          and _from(top.inputs["Height"]).label == "fixture_normal_bump.png"
          and _from(sep.inputs["Color"]).label == "fixture_normal.png")


def check_failed_build_cleanup(max_path):
    """A build that fails after its materials were made: the operator removes the materials and images it made and
    leaves a material and an image that were there before."""
    from maxdrop.build import objects as build_objects
    keep_material = bpy.data.materials.new("UserMaterial")
    keep_image = bpy.data.images.new("UserImage", 2, 2)
    before = ({m.as_pointer() for m in bpy.data.materials}, {i.as_pointer() for i in bpy.data.images})
    original, made = build_objects.build, []

    def failing(*args, **kwargs):
        built = original(*args, **kwargs)
        made.append((len(built.materials), len(bpy.data.images)))
        raise RuntimeError("maxdrop test: build fails")

    build_objects.build = failing
    try:
        try:
            bpy.ops.import_scene.maxdrop(filepath=max_path)
            raised = False
        except RuntimeError:
            raised = True
    finally:
        build_objects.build = original
    after = ({m.as_pointer() for m in bpy.data.materials}, {i.as_pointer() for i in bpy.data.images})
    check("failed build: materials and images were made before it failed",
          raised and made and made[0][0] > 0 and made[0][1] > len(before[1]), str(made))
    check("failed build: the materials and images it made are removed, the user's stay",
          after == before and keep_material.name in bpy.data.materials and keep_image.name in bpy.data.images
          and not bpy.data.objects, "%d / %d materials, %d / %d images" % (
              len(after[0]), len(before[0]), len(after[1]), len(before[1])))
    bpy.data.materials.remove(keep_material)
    bpy.data.images.remove(keep_image)


def _write_png(path):
    img = bpy.data.images.new("maxdrop-probe", 4, 4)
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def check_found_textures():
    """vray_maps, texmap_rules, corona_maps, corona_light and vray_texmaps copied beside a PNG for each texture name:
    every Image Texture node gets its file, in the color space the IR asks for, one datablock per file and color
    space; the report lists no texture."""
    fixtures = os.path.join(ROOT, "tests", "fixtures")
    scratch = tempfile.mkdtemp(prefix="maxdrop-textures-")
    try:
        for name in ("vray_maps", "texmap_rules", "corona_maps", "corona_light", "vray_texmaps"):
            empty_scene()
            for ob in list(bpy.data.images):
                bpy.data.images.remove(ob)
            src = os.path.join(fixtures, name + ".max")
            dst = os.path.join(scratch, name + ".max")
            shutil.copy(src, dst)
            _desc, plan = _irs(src)
            irs = {ir.name: ir for s in plan.values() for irs in s.slots for ir in irs if ir is not None}
            wants = {}
            for ir in irs.values():
                for img in _images_of(ir):
                    wants.setdefault(img.name, set()).add(img.colorspace)
            os.makedirs(os.path.join(scratch, "maps"), exist_ok=True)
            for file in wants:  # in the maps folder beside the scene: the lookup's second rule
                _write_png(os.path.join(scratch, "maps", file))
            result = bpy.ops.import_scene.maxdrop(filepath=dst)
            check("%s with its textures: imported" % name, result == {'FINISHED'})
            got = {}
            for m in bpy.data.materials:
                for n in m.node_tree.nodes:
                    if n.bl_idname == "ShaderNodeTexImage":
                        img = n.image
                        check("%s/%s/%s: image loaded" % (name, m.name, n.label), img is not None)
                        if img is not None:
                            check("%s/%s/%s: its file" % (name, m.name, n.label),
                                  os.path.normcase(bpy.path.abspath(img.filepath)) ==
                                  os.path.normcase(os.path.join(scratch, "maps", n.label)), img.filepath)
                            got.setdefault(n.label, set()).add((img.colorspace_settings.name, img.name))
            colorspaces = {k: {c for c, _n in v} for k, v in got.items()}
            check("%s with its textures: the color space of every image as the IR asks" % name,
                  colorspaces == wants, "%s vs %s" % (colorspaces, wants))
            images = sum(len(v) for v in wants.values())
            check("%s with its textures: one image datablock per file and color space" % name,
                  len(bpy.data.images) == images and all(len(v) == len(colorspaces[k]) for k, v in got.items()),
                  "%d images, %d wanted" % (len(bpy.data.images), images))
            text = bpy.data.texts.get("MaxDrop Report")
            body = text.as_string() if text is not None else ""
            check("%s with its textures: no texture reported missing, every file counted as found" % name,
                  text is not None and "Textures not found" not in body
                  and "\nTextures found: %d (" % len(wants) in body, body[-600:])
            for ir in irs.values():
                check_principled("%s with its textures/%s" % (name, ir.name), bpy.data.materials.get(ir.name), ir,
                                 present=True)
            if name == "vray_maps":
                check_vray_maps_nodes(textured=True)
                empty_scene()
                for img in list(bpy.data.images):
                    bpy.data.images.remove(img)
                check_failed_build_cleanup(dst)
            if name == "texmap_rules":
                m = bpy.data.materials["FixtureTexPlace"]
                cropped = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"
                               and n.label == "place_crop.png")
                uv = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeUVMap"]
                check("texmap_rules: place_crop.png mirrored, on map channel 3, cropped",
                      cropped.extension == 'MIRROR' and any(n.uv_map == "UVChannel_3" for n in uv)
                      and any(n.bl_idname == "ShaderNodeVectorMath" and n.operation == 'FRACTION'
                              for n in m.node_tree.nodes), "%s %s" % (cropped.extension, [n.uv_map for n in uv]))
                keep = bpy.data.materials["FixtureTexKeep"]
                kinds = {n.bl_idname for n in keep.node_tree.nodes}
                check("texmap_rules: Mix with a mask, Multiply, Color Correction as nodes",
                      {"ShaderNodeMix", "ShaderNodeHueSaturation", "ShaderNodeGamma"} <= kinds, str(sorted(kinds)))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder():
    """MaterialBuilder on hand-made IRs: one file in two color spaces is two images, the same twice is one; a file
    not found leaves its node without an image and a report line; Thin Wall on 5.x, skipped with a line on 4.x;
    two materials of one name both kept; BLENDED for a constant alpha, DITHERED for an alpha map; every node kind."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-builder-")
    try:
        png = os.path.join(scratch, "shared.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        srgb = tx.Image(1, "shared.png", "shared.png", "", found)
        data = tx.Image(1, "shared.png", "shared.png", "", found, colorspace=tx.NON_COLOR)
        lost = tx.Image(2, "nothere.png", "C:\\x\\nothere.png", "", None)
        placed = tx.Image(3, "shared.png", "shared.png", "", found,
                          mapping=tx.Mapping(channel=2, tiling=(2.0, 1.0), angle=(0.0, 0.0, 0.5),
                                             tile=(False, False), mirror=(True, True)),
                          crop=tx.Crop(0.1, 0.2, 0.5, 0.5, place=True),
                          output=tx.TexOutput(invert=True, amount=0.5, level=2.0, offset=0.1))
        gamma = tx.Image(4, "shared.png", "shared.png", "", found, colorspace=tx.NON_COLOR, gamma=1.8)

        def graph(root, kind):
            return tx.TextureGraphIR(root, kind)

        a = cm.MaterialIR(10, "Clash", "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)),
                          roughness=cm.Input(0.4, cm.MapRef(1)), specular=cm.Input(0.6, cm.MapRef(1)),
                          thin_walled=True, alpha=cm.Input(0.5))
        a.textures = {"base_color": graph(tx.Mix(tx.Constant((0.5, 0.5, 0.5)), srgb, 0.7, data), tx.COLOR),
                      "roughness": graph(tx.Invert(data), tx.DATA),
                      "specular": graph(tx.Multiply(srgb, tx.Constant((2.0, 2.0, 2.0))), tx.COLOR)}
        b = cm.MaterialIR(11, "Clash", "test", alpha=cm.Input(1.0, cm.MapRef(2)),
                          emission_color=cm.Input((1.0, 0.5, 0.0), cm.MapRef(3)), emission_strength=2.0)
        b.textures = {"alpha": graph(lost, tx.DATA),
                      "emission_color": graph(tx.ColorCorrect(tx.Composite(((placed, 1.0), (gamma, 0.5))),
                                                              hue=0.25, saturation=1.5, brightness=0.1,
                                                              contrast=0.2, gain=1.2, gamma=1.1), tx.COLOR),
                      "normal": graph(tx.NormalMap(data, 0.7, flip_red=True, flip_green=True, swap=True,
                                                   bump=tx.Bump(data, 2.0), channel=2), tx.NORMAL),
                      "metallic": graph(tx.Constant(0.3), tx.DATA)}
        builder = build_materials.MaterialBuilder()
        ma, mb = builder.make(a), builder.make(b)
        check("builder: two materials named Clash both kept", sorted([ma.name, mb.name]) == ["Clash", "Clash.001"],
              "%s %s" % (ma.name, mb.name))
        shared = sorted(i.colorspace_settings.name for i in bpy.data.images)
        check("builder: shared.png in sRGB and Non-Color is two images, reused by every node",
              shared == ["Non-Color", "sRGB"] and len(builder.images) == 2, str(shared))
        lost_nodes = [n for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.label == "nothere.png"]
        issues = builder.issues()
        check("builder: a file not found keeps its node, without an image, and is no builder issue (the texture "
              "lookup reports it by name)", len(lost_nodes) == 1 and lost_nodes[0].image is None and issues == [],
              str(issues))
        check("builder: materials counted by class", dict(builder.classes) == {"test": 2}, str(builder.classes))
        thin = _principled(ma).inputs.get("Thin Wall")
        skipped = dict(builder.sockets_skipped)
        if bpy.app.version >= (5, 0, 0):
            check("builder: Thin Wall set on Blender 5", thin is not None and thin.default_value and not skipped)
        else:
            check("builder: Thin Wall skipped and counted once on Blender 4", thin is None
                  and skipped == {"Thin Wall": 1}, str(skipped))
        check("builder: BLENDED for a constant alpha below 1, DITHERED for an alpha map",
              ma.surface_render_method == 'BLENDED' and mb.surface_render_method == 'DITHERED')
        pb = _principled(mb)
        check("builder: emission, normal linked; metallic from a constant graph",
              pb.inputs["Emission Color"].is_linked and pb.inputs["Normal"].is_linked
              and not pb.inputs["Metallic"].is_linked and abs(pb.inputs["Metallic"].default_value - 0.3) < 1e-6
              and abs(pb.inputs["Emission Strength"].default_value - 2.0) < 1e-6)
        kinds = {n.bl_idname for n in mb.node_tree.nodes}
        need = {"ShaderNodeHueSaturation", "ShaderNodeBrightContrast", "ShaderNodeGamma", "ShaderNodeMix",
                "ShaderNodeNormalMap", "ShaderNodeBump", "ShaderNodeSeparateColor", "ShaderNodeCombineColor",
                "ShaderNodeUVMap", "ShaderNodeMapping", "ShaderNodeVectorMath", "ShaderNodeInvert"}
        check("builder: every node kind of the graphs", need <= kinds, str(sorted(need - kinds)))
        place = next(n for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.label == "shared.png"
                     and n.inputs["Vector"].is_linked)
        check("builder: a placed crop clips", place.extension == 'CLIP', place.extension)
        uv = [n.uv_map for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeUVMap"]
        nm = next(n for n in mb.node_tree.nodes if n.bl_idname == "ShaderNodeNormalMap")
        check("builder: map channel 2 is UVChannel_2, for the image and the normal map's tangents",
              uv == ["UVChannel_2"] and nm.uv_map == "UVChannel_2", "%s %s" % (uv, nm.uv_map))
        spec = _principled(ma).inputs["Specular IOR Level"]
        dot = spec.links[0].from_node if spec.is_linked else None
        check("builder: a color graph on the specular goes through the mean, times 0.5",
              dot is not None and dot.operation == 'DOT_PRODUCT'
              and close(list(dot.inputs[1].default_value), [1 / 6.0] * 3, 1e-6))
        check("builder: the viewport color is the base color", close(list(ma.diffuse_color)[:3], [0.5] * 3, 1e-6))
        check_builder_wiring(ma, mb, builder, cm, tx, srgb, data, lost, gamma)
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_wiring(ma, mb, builder, cm, tx, srgb, data, lost, gamma):
    """The links and values of the hand-made IRs' nodes, against numbers worked out by hand."""
    pa, pb = _principled(ma), _principled(mb)
    mix = _from(pa.inputs["Base Color"])
    check("wiring: base color Mix: A the swatch, B the sRGB image, the mask image on the factor",
          mix.bl_idname == "ShaderNodeMix" and mix.blend_type == 'MIX' and not _input(mix, "A_Color").is_linked
          and close(list(_input(mix, "A_Color").default_value)[:3], [0.5] * 3, 1e-6)
          and _from(_input(mix, "B_Color")).image.colorspace_settings.name == "sRGB"
          and _from(_input(mix, "Factor_Float")).image.colorspace_settings.name == "Non-Color")
    inv = _from(pa.inputs["Roughness"])
    check("wiring: roughness 1 - the data image", inv.bl_idname == "ShaderNodeMath" and inv.operation == 'SUBTRACT'
          and inv.inputs[0].default_value == 1.0 and _from(inv.inputs[1]).bl_idname == "ShaderNodeTexImage")
    dot = _from(pa.inputs["Specular IOR Level"])
    mul = _from(dot.inputs[0])
    check("wiring: specular map times 2 through a Multiply Mix", mul.bl_idname == "ShaderNodeMix"
          and mul.blend_type == 'MULTIPLY' and _input(mul, "Factor_Float").default_value == 1.0
          and close(list(_input(mul, "B_Color").default_value)[:3], [2.0] * 3, 1e-6))
    gam = _from(pb.inputs["Emission Color"])
    gain = _from(gam.inputs["Color"])
    bc = _from(gain.inputs[0])
    hue = _from(bc.inputs["Color"])
    comp = _from(hue.inputs["Color"])
    check("wiring: Color Correction: Hue 0.75, Saturation 1.5, Bright 0.1, Contrast 0.2, gain 1.2, Gamma 1 / 1.1",
          gam.bl_idname == "ShaderNodeGamma" and abs(gam.inputs["Gamma"].default_value - 1 / 1.1) < 1e-6
          and gain.bl_idname == "ShaderNodeVectorMath" and gain.operation == 'SCALE'
          and abs(_input(gain, "Scale").default_value - 1.2) < 1e-6
          and bc.bl_idname == "ShaderNodeBrightContrast" and abs(_input(bc, "Bright").default_value - 0.1) < 1e-6
          and abs(_input(bc, "Contrast").default_value - 0.2) < 1e-6
          and hue.bl_idname == "ShaderNodeHueSaturation" and abs(hue.inputs["Hue"].default_value - 0.75) < 1e-6
          and abs(hue.inputs["Saturation"].default_value - 1.5) < 1e-6)
    factor = _from(_input(comp, "Factor_Float"))
    top = _from(_input(comp, "B_Color"))
    check("wiring: Composite: the top layer over the bottom by its alpha times 0.5, its gamma override 1.8 applied",
          comp.bl_idname == "ShaderNodeMix" and factor.bl_idname == "ShaderNodeMath" and factor.operation == 'MULTIPLY'
          and abs(factor.inputs[1].default_value - 0.5) < 1e-6 and factor.inputs[0].links[0].from_socket.name == "Alpha"
          and top.bl_idname == "ShaderNodeGamma" and abs(top.inputs["Gamma"].default_value - 1.8) < 1e-6)
    amount = _from(_input(comp, "A_Color"))
    level = _from(amount.inputs[0])
    out_inv = _from(level.inputs[0])
    tex = _from(out_inv.inputs["Color"])
    crop = _from(tex.inputs["Vector"])
    frac = _from(crop.inputs["Vector"])
    place = _from(frac.inputs[0])
    uv = _from(place.inputs["Vector"])
    from maxdrop.build import materials as build_materials
    want = build_materials.uv_transform(tx.Mapping(tiling=(2.0, 1.0), angle=(0.0, 0.0, 0.5)))
    check("wiring: Output: inverted, times 2 plus 0.1, times 0.5",
          amount.operation == 'SCALE' and abs(_input(amount, "Scale").default_value - 0.5) < 1e-6
          and level.operation == 'MULTIPLY_ADD' and close(list(_input(level, "Vector_001").default_value), [2.0] * 3,
                                                          1e-6)
          and close(list(_input(level, "Vector_002").default_value), [0.1] * 3, 1e-6)
          and out_inv.bl_idname == "ShaderNodeInvert")
    check("wiring: a placed crop: UVChannel_2 -> placement -> fraction -> Mapping TEXTURE at (0.1, 0.3) x 0.5",
          crop.bl_idname == "ShaderNodeMapping" and crop.vector_type == 'TEXTURE'
          and close(list(crop.inputs["Location"].default_value), [0.1, 0.3, 0.0], 1e-6)
          and close(list(crop.inputs["Scale"].default_value), [0.5, 0.5, 1.0], 1e-6)
          and frac.operation == 'FRACTION' and place.bl_idname == "ShaderNodeMapping" and place.vector_type == 'POINT'
          and close(list(place.inputs["Location"].default_value), list(want[0]), 1e-6)
          and close(list(place.inputs["Rotation"].default_value), [0.0, 0.0, 0.5], 1e-6)
          and uv.bl_idname == "ShaderNodeUVMap" and uv.uv_map == "UVChannel_2")
    bump = _from(pb.inputs["Normal"])
    nm = _from(bump.inputs["Normal"])
    comb = _from(nm.inputs["Color"])
    red, green = _from(comb.inputs["Red"]), _from(comb.inputs["Green"])
    check("wiring: normal map swapped then flipped: Red = 1 - G, Green = 1 - R, Blue = B; its bump at 2 (1, distance 2)",
          bump.bl_idname == "ShaderNodeBump" and bump.inputs["Strength"].default_value == 1.0
          and bump.inputs["Distance"].default_value == 2.0 and abs(nm.inputs["Strength"].default_value - 0.7) < 1e-6
          and red.operation == 'SUBTRACT' and red.inputs[1].links[0].from_socket.identifier == "Green"
          and green.operation == 'SUBTRACT' and green.inputs[1].links[0].from_socket.identifier == "Red"
          and comb.inputs["Blue"].links[0].from_socket.identifier == "Blue")
    c = cm.MaterialIR(12, "Inverted", "test", base_color=cm.Input((0.2, 0.3, 0.4), cm.MapRef(5)))
    c.textures = {"bump": tx.TextureGraphIR(tx.Bump(data, -0.5), tx.BUMP),
                  "base_color": tx.TextureGraphIR(tx.Mix(tx.Constant((0.2, 0.3, 0.4)), srgb, 0.5, gamma), tx.COLOR)}
    d = cm.MaterialIR(13, "Lost", "test", alpha=cm.Input(0.8, cm.MapRef(6)), base_color=cm.Input((0.1, 0.2, 0.3),
                                                                                                  cm.MapRef(7)))
    d.textures = {"normal": tx.TextureGraphIR(tx.NormalMap(lost, 1.0, bump=tx.Bump(lost, 0.5)), tx.NORMAL),
                  "alpha": tx.TextureGraphIR(tx.Mix(tx.Constant(0.8), lost, 0.6), tx.DATA),
                  "base_color": tx.TextureGraphIR(tx.ColorCorrect(lost, hue=0.1), tx.COLOR)}
    mc, md = builder.make(c), builder.make(d)
    b = _from(_principled(mc).inputs["Normal"])
    check("wiring: a negative bump amount inverts the Bump node", b.invert and b.inputs["Strength"].default_value == 0.5)
    mask = _from(_input(_from(_principled(mc).inputs["Base Color"]), "Factor_Float"))
    check("wiring: a mask with a gamma override gets no Gamma node", mask.bl_idname == "ShaderNodeTexImage")
    pd = _principled(md)
    check("wiring: missing images leave the IR's values: Normal free, alpha 0.8 (BLENDED), base color the swatch",
          not pd.inputs["Normal"].is_linked and not pd.inputs["Alpha"].is_linked
          and abs(pd.inputs["Alpha"].default_value - 0.8) < 1e-6 and md.surface_render_method == 'BLENDED'
          and not pd.inputs["Base Color"].is_linked
          and close(list(pd.inputs["Base Color"].default_value)[:3], [0.1, 0.2, 0.3], 1e-6)
          and not any(o.is_linked for n in md.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" for o in n.outputs)
          and len([n for n in md.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"]) == 1)


def check_layer_flags(modules):
    """layers_flags with its description changed: FixtureLayerB hidden in 3ds Max, FixtureLayerA frozen and not
    rendering, a child layer of FixtureLayerB holding FixtureHidden."""
    convert_scene = modules[0]
    empty_scene()
    desc = convert_scene.read(os.path.join(ROOT, "tests", "fixtures", "layers_flags.max"))
    a, b = desc.layers
    b.hidden, a.frozen, a.renderable = True, True, False
    child = convert_scene.LayerDescription(-1, "FixtureChildLayer", parent=b.index)
    desc.layers.append(child)
    moved = next(n for n in desc.nodes if n.name == "FixtureHidden")
    moved.layer = child.index
    head = next(n for n in desc.nodes if n.name == "FixtureGroup")
    head.hidden = True  # hiding a parent in 3ds Max leaves its children visible
    cols, _built, view_layer = build_scene(desc, "layer_flags", modules)
    members = {ob.name: ob for ob in bpy.data.objects["FixtureGroup"].children}
    placed = {name: tuple(round(v / desc.meters, 4) for v in ob.matrix_world.translation)
              for name, ob in members.items()}
    check("hidden parent: its visible children are placed by Blender",
          placed == {"FixtureGroupA": (0.0, 30.0, 0.0), "FixtureGroupB": (20.0, 30.0, 0.0)}
          and not any(ob.hide_get(view_layer=view_layer) for ob in members.values()), str(placed))
    lcs = view_layer.layer_collection.children["layer_flags"].children
    check("hidden layer: excluded in the view layer", lcs[b.name].exclude and not lcs[a.name].exclude)
    check("hidden layer: its child layer is nested below it",
          [c.name for c in cols.layers[b.index].children] == ["FixtureChildLayer"])
    visible = {ob.name for ob in view_layer.objects}
    check("hidden layer: its objects and its child layer's are out of the view layer",
          not visible & {"FixtureHidden", "FixtureNoRender"} and "FixtureVisible" in visible, str(sorted(visible)))
    col_a = cols.layers[a.index]
    check("frozen, non-rendering layer: hide_select and hide_render on its collection",
          col_a.hide_select and col_a.hide_render and not cols.layers[b.index].hide_render)


def _local(a, t):
    """A Blender 4x4 (rows) of a 3x3 and a translation."""
    return tuple(tuple(a[r]) + (t[r],) for r in range(3)) + ((0.0, 0.0, 0.0, 1.0),)


def check_shear(modules):
    """A hand-made description with sheared local matrices (a scale along a rotated axis), with and without a
    parent, one with a zero scale: Blender's world matrices equal the products of the locals."""
    import numpy
    convert_scene, build_objects = modules[0], modules[2]
    empty_scene()
    desc = convert_scene.SceneDescription(1.0)
    md = convert_scene.MeshDescription(
        "tri", "ShearTri", numpy.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], dtype=numpy.float32),
        numpy.array([0, 1, 2], dtype=numpy.int32), numpy.array([0], dtype=numpy.int32),
        numpy.array([3], dtype=numpy.int32), numpy.zeros(1, dtype=numpy.int32), numpy.zeros(1, dtype=bool),
        numpy.zeros((0, 2), dtype=numpy.int32), [])
    desc.meshes["tri"] = md
    c, s = 0.8, 0.6
    plain = _local(((c, -s, 0), (s, c, 0), (0, 0, 1)), (0.5, -1.0, 2.0))
    nodes = [  # index, name, parent, local, kind, sheared, hidden
        (1, "ShearTop", None, _local(((1, 0.4, 0), (0.1, 1.2, 0.3), (0, 0, 0.8)), (1, 2, 3)), "EMPTY", True, False),
        (2, "ShearChild", 1, _local(((0.9, 0, 0.5), (0.2, 1.1, 0), (0, -0.3, 1.4)), (-2, 0.5, 1)), "MESH", True,
         False),
        (3, "ShearGrandchild", 2, plain, "MESH", False, False),
        (4, "ShearHiddenTop", None, _local(((2, 0.7, 0), (0, 1, 0), (0.2, 0, 1)), (3, -1, 0)), "MESH", True, True),
        (5, "PlainTop", None, plain, "EMPTY", False, False),
        (6, "ShearZeroScale", 5, _local(((0, 0.5, 0), (0, 1, 0), (0, 0.3, 1)), (1, 1, 1)), "EMPTY", True, False),
    ]
    expected = {}
    for index, name, parent, local, kind, sheared, hidden in nodes:
        m = numpy.array(local, dtype=numpy.float64)
        expected[name] = (expected[nodes[parent - 1][1]] @ m) if parent else m
        mesh = "tri" if kind == "MESH" else None
        if mesh:
            md.users.append(index)
        desc.nodes.append(convert_scene.NodeDescription(
            index, name, parent, local, tuple(map(tuple, expected[name].tolist())), kind, mesh, "", False, (),
            hidden=hidden, sheared=sheared))
    cols, built, view_layer = build_scene(desc, "shear", modules)
    helpers = built.helpers
    check("shear: one helper empty, at the identity, in the file's collection",
          len(helpers) == 1 and helpers[0].type == 'EMPTY' and helpers[0].parent is None
          and helpers[0].matrix_world == Matrix.Identity(4)
          and [col.name for col in helpers[0].users_collection] == [cols.root.name],
          str([(h.name, [col.name for col in h.users_collection]) for h in helpers]))
    for index, name, parent, _local_m, _kind, sheared, _hidden in nodes:
        ob = built.objects[index]
        want = built.objects[parent] if parent else (helpers[0] if sheared and helpers else None)
        check("shear/%s: parent" % name, ob.parent == want, "%r" % (ob.parent and ob.parent.name))
        got = numpy.array(world_of(ob), dtype=numpy.float64)
        error = float(numpy.abs(got - expected[name]).max())
        check("shear/%s: world matrix = the product of the locals" % name, error <= 1e-6, "%.3g" % error)
    roots = sorted(ob.name for ob in built.roots())
    check("shear: roots are the plain top-level object and the helper",
          roots == sorted(["PlainTop"] + [h.name for h in helpers]), str(roots))
    axis = numpy.array([(1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)], dtype=numpy.float64)
    for ob in built.roots():
        ob.matrix_basis = Matrix(axis.tolist()) @ ob.matrix_basis
    view_layer.update()
    errors = {name: float(numpy.abs(numpy.array(world_of(built.objects[index]), dtype=numpy.float64)
                                    - axis @ expected[name]).max()) for index, name, *_rest in nodes}
    check("shear: an axis change on the roots turns every object", max(errors.values()) <= 1e-6, str(errors))
    plain_only = convert_scene.SceneDescription(1.0)
    plain_only.nodes.append(convert_scene.NodeDescription(1, "PlainOnly", None, plain, plain, "EMPTY", None, "",
                                                          False, ()))
    empty_scene()
    _cols, built, _vl = build_scene(plain_only, "no_shear", modules)
    check("shear: no helper without a sheared top-level node", built.helpers == [] and len(bpy.data.objects) == 1)
    if build_objects.SHEAR_HELPER in bpy.data.objects:
        failures.append("shear: helper left over")


def _plan(path, edit=None):
    """convert.scene.read of path, edit(desc) applied, then its slot plan."""
    from maxdrop.convert import materials as convert_materials
    from maxdrop.convert import scene as convert_scene
    from maxdrop.reader import cfb, materials as reader_materials, scene as reader_scene
    desc = convert_scene.read(path)
    if edit is not None:
        edit(desc)
    with cfb.CompoundFile(path) as cf:
        sc = reader_scene.Scene.from_file(cf)
        conv = convert_materials.MaterialConverter(reader_materials.MaterialGraph(sc))
        slots = convert_materials.assign(desc, convert_materials.node_materials(sc, desc), conv)
    return desc, slots


def _faces(ob):
    """The material name each face of ob renders with (None: an empty slot)."""
    return [(lambda m: m and m.name)(ob.material_slots[p.material_index].material) for p in ob.data.polygons]


def check_material_slots(modules):
    """Multi/Sub-Object by material ID, slots shared by objects or linked to each, one slot per plain material."""
    import numpy
    fixtures = os.path.join(ROOT, "tests", "fixtures")

    def make(ir):
        return bpy.data.materials.new(ir.name)

    def share(desc):
        nodes = {n.name: n for n in desc.nodes}
        multi, shell = nodes["FixtureMultiBox"], nodes["FixtureShellBox"]
        md = desc.meshes[multi.mesh]
        md.material_indices = numpy.array([0, 2, 6, 0, 2, 6], dtype=numpy.int32)  # IDs 1, 3, 7 (stored zero-based)
        del desc.meshes[shell.mesh]
        shell.mesh = multi.mesh
        md.users = sorted([shell.index, multi.index])

    empty_scene()
    desc, slots = _plan(os.path.join(fixtures, "vray_wrappers.max"), share)
    _cols, built, _vl = build_scene(desc, "material_slots", modules, slots=slots, material=make)
    obs = {n.name: built.objects[n.index] for n in desc.nodes}
    multi, shell = obs["FixtureMultiBox"], obs["FixtureShellBox"]
    check("material slots: faces with IDs 1, 3, 7 on the slots of their sub-materials",
          _faces(multi) == ["FixtureSubOne", None, "FixtureSubSeven"] * 2, str(_faces(multi)))
    check("material slots: three slots on the shared mesh, linked to each object",
          len(multi.data.materials) == 3 and multi.data is shell.data
          and all(s.link == 'OBJECT' for ob in (multi, shell) for s in ob.material_slots),
          str([(s.link, s.material and s.material.name) for s in multi.material_slots]))
    check("material slots: the Shell box renders its original material on every face",
          _faces(shell) == ["FixtureShellOriginal"] * 6, str(_faces(shell)))
    two = obs["FixtureTwoSidedBox"]
    check("material slots: a wrapper gives one slot on the mesh",
          [m.name for m in two.data.materials] == ["FixtureFront"] and two.material_slots[0].link == 'DATA'
          and _faces(two) == ["FixtureFront"] * 6, str(_faces(two)))
    names = sorted(m.name for m in bpy.data.materials)
    check("material slots: one Blender material per Max material",
          names == sorted(["FixtureFront", "FixtureBlendBase", "FixtureShellOriginal", "FixtureSubOne",
                           "FixtureSubSeven"]) and len(built.materials) == 5, str(names))

    empty_scene()
    desc, slots = _plan(os.path.join(fixtures, "standard_physical.max"))
    _cols, built, _vl = build_scene(desc, "standard_physical_slots", modules, slots=slots, material=make)
    got = {n.name: [m.name for m in built.objects[n.index].data.materials] for n in desc.nodes}
    faces = {n.name: [p.material_index for p in built.objects[n.index].data.polygons] for n in desc.nodes}
    check("material slots: Standard and Physical boxes, one slot each",
          got == {"FixtureStandardBox": ["FixtureStandard"], "FixturePhysicalBox": ["FixturePhysical"]}
          and all(v == [0] * 6 for v in faces.values()), "%s %s" % (got, faces))


def main():
    print("Blender " + bpy.app.version_string)
    sys.path.insert(0, ROOT)
    import maxdrop
    maxdrop.register()
    check("package imported from the repo root",
          os.path.normcase(os.path.dirname(os.path.dirname(maxdrop.__file__))) == os.path.normcase(ROOT))
    from maxdrop.build import collections as build_collections
    from maxdrop.build import objects as build_objects
    from maxdrop.build import report as build_report
    from maxdrop.convert import report as convert_report
    from maxdrop.convert import scene as convert_scene
    modules = (convert_scene, convert_report, build_objects, build_collections, build_report)
    paths = argv or sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
    check("fixtures found", bool(paths))
    for path in paths:
        try:
            run_fixture(path, modules)
        except Exception:
            traceback.print_exc()
            check("%s: no exception" % os.path.basename(path), False)
    if not argv:
        try:
            check_layer_flags(modules)
        except Exception:
            traceback.print_exc()
            check("layer flags: no exception", False)
        try:
            check_shear(modules)
        except Exception:
            traceback.print_exc()
            check("shear: no exception", False)
        for label, run_check in (("material slots", lambda: check_material_slots(modules)),
                                 ("found textures", check_found_textures), ("builder", check_builder)):
            try:
                run_check()
            except Exception:
                traceback.print_exc()
                check("%s: no exception" % label, False)


try:
    main()
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FIXTURES FAILED: %s" % ", ".join(failures) if failures else "FIXTURES PASSED")
sys.stdout.flush()
sys.exit(1 if failures else 0)
