# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of cameras, render settings, extrusions, converted modifiers, curves, sections, modifier pivots and
Look At."""
import collections
import math

import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import interpolate_bezier

from .core import check, close, empty_scene, max_rows, objects_of, world_of
from .tables import (
    BBOX_TOLERANCE, CAMERA_SENSORS, CAMERA_SHIFTS, EXTRUDE_EULER, EXTRUDE_SHARP_EDGES, EXTRUDE_UV_LAYERS, FOV_TOLERANCE,
    KEPT_SIZE, MATRIX_TOLERANCE,
)


def check_camera(label, ob, node, desc, o):
    """A camera node: a camera object whose Camera is the description's, frames 3ds Max's horizontal field of view
    (the oracle's) and looks along the oracle's -Z with its +Y up."""
    check(label + ": a camera object", ob.type == 'CAMERA' and node.kind == "CAMERA", ob.type)
    if ob.type != 'CAMERA':
        return
    cam, cd = ob.data, desc.cameras[node.camera]
    got = (cam.type, cam.sensor_fit, cam.sensor_width, cam.lens, cam.shift_x, cam.shift_y, cam.dof.use_dof)
    want = (cd.kind, 'HORIZONTAL', cd.sensor, cd.lens, cd.shift_x, cd.shift_y, False)
    check(label + ": type, sensor fit, sensor, lens, shift, no depth of field", got[:2] == want[:2] and
          close(got[2:6], want[2:6], 1e-5) and got[6] == want[6], "%s vs %s" % (got, want))
    sx, sy = CAMERA_SHIFTS.get(o["name"], (0.0, 0.0))
    check(label + ": the shift and sensor the fixture script made", close((cam.shift_x, cam.shift_y), (sx, sy), 1e-6)
          and abs(cam.sensor_width - CAMERA_SENSORS.get(o["name"], 36.0)) < 1e-5, "%g, %g, %g" % (
              cam.shift_x, cam.shift_y, cam.sensor_width))
    fov = math.degrees(cam.angle_x)
    check(label + ": horizontal field of view = 3ds Max's", abs(fov - o["camera"]["fov"]) < FOV_TOLERANCE,
          "%g vs %g" % (fov, o["camera"]["fov"]))
    check(label + ": orthographic as in 3ds Max", (cam.type == 'ORTHO') == o["camera"]["ortho"], cam.type)
    if cam.type == 'ORTHO':
        check(label + ": orthographic width", abs(cam.ortho_scale - cd.ortho_scale) < 1e-6, "%g" % cam.ortho_scale)
    if o["camera"]["manual_clip"]:
        want = (o["camera"]["hither"] * desc.meters, o["camera"]["yon"] * desc.meters)
        check(label + ": clipping = 3ds Max's", close((cam.clip_start, cam.clip_end), want, 1e-6),
              "%g, %g" % (cam.clip_start, cam.clip_end))
    rows = o["transform"]
    m = ob.matrix_world.to_3x3()
    for axis, k, sign in (("-Z", 6, -1.0), ("+Y", 3, 1.0)):
        want = Vector(rows[k:k + 3]).normalized() * sign
        got = (m @ Vector((0.0, 0.0, 1.0) if k == 6 else (0.0, 1.0, 0.0))).normalized() * sign
        check(label + ": %s along the oracle's" % axis, (got - want).length < 1e-5, "%s vs %s" % (
            tuple(got), tuple(want)))


def check_render(name, oracle, obs, desc):
    """Every fixture: with a camera, the scene's render size is the oracle's and scene.camera the oracle's render
    camera or else the first camera; without one, the scene's render size and camera stay as they were."""
    scene = bpy.context.scene
    r = oracle["render"]
    got = (scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage,
           scene.render.pixel_aspect_x / scene.render.pixel_aspect_y)
    by_handle = {o["handle"]: ob for ob, o in zip(obs, oracle["nodes"])}
    cams = [ob for ob, o in zip(obs, oracle["nodes"]) if o["camera"] is not None]
    want = by_handle[r["camera"]] if r["camera"] is not None else (cams[0] if cams else None)
    if want is not None:
        check("%s: render size = 3ds Max's" % name, got[:3] == (r["width"], r["height"], 100) and
              abs(got[3] - r["pixel_aspect"]) < 1e-6, str(got))
        check("%s: scene camera = %s" % (name, want.name), scene.camera == want,
              scene.camera.name if scene.camera else "none")
    else:
        check("%s: no camera: the scene's render size and camera are kept" % name,
              got == KEPT_SIZE + (1.0,) and scene.camera is None, "%s %s" % (got, scene.camera))
    if name == "cameras":
        check("cameras: eleven camera objects, one Camera each, CamTarget the scene camera",
              len(cams) == 11 and len(bpy.data.cameras) == 11 and scene.camera.name == "CamTarget",
              "%d, %d" % (len(cams), len(bpy.data.cameras)))
    if name == "lookat":
        check("lookat: FixtureCam (the first camera) is the scene camera, a note, no camera issue",
              scene.camera is not None and scene.camera.name == "FixtureCam" and desc.camera is not None
              and desc.camera_note is not None and not any(r.startswith("camera: ") for _i, r in desc.issues),
              str(desc.camera_note))


def check_extruded(label, ob, node, o, meters, plan):
    """A shape under an Extrude: a mesh with the oracle's world box, vertex count and triangle count (with converted
    modifiers above the Extrude, the oracle's are after them: check_converted compares the evaluated mesh), closed
    with normals outward as rendered (the signed volume of the world mesh, times the sign of the world matrix's
    determinant, is positive) when capped, its UV layers, sharp edges and material slots."""
    check(label + ": mesh object", ob.type == 'MESH', ob.type)
    if ob.type != 'MESH':
        return
    mesh, mw = ob.data, world_of(ob)
    world = [mw @ v.co for v in mesh.vertices]
    lo = [min(p[k] for p in world) / meters for k in range(3)]
    hi = [max(p[k] for p in world) / meters for k in range(3)]
    if not node.converted:
        check(label + ": world bounding box", close(lo, o["bbox_min"], BBOX_TOLERANCE)
              and close(hi, o["bbox_max"], BBOX_TOLERANCE),
              "%s..%s vs %s..%s" % (["%.6g" % v for v in lo], ["%.6g" % v for v in hi], o["bbox_min"], o["bbox_max"]))
        triangles = sum(len(p.vertices) - 2 for p in mesh.polygons)
        check(label + ": vertex and triangle counts", (len(mesh.vertices), triangles) ==
              (o["eval_verts"], o["eval_faces"]), "%d, %d" % (len(mesh.vertices), triangles))
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


# 3ds Max leaves the seam of FixtureOrder's shelled boxes unwelded (32 vertices before the TurboSmooth, 100 after);
# Blender's Mirror welds it (84): the same surface, so only the box is compared there
# FixtureShellUnderSymNoWeld: 3ds Max's slice drops the Shell's rim on the plane and leaves the cut open (44 vertices,
# 64 triangles), Blender's Mirror without its weld keeps both copies of that rim (80 triangles): the report names it
EVAL_COUNT_DIFFERS = {"FixtureOrder", "FixtureShellUnderSymNoWeld"}
# Blender's evaluated (flat, regions, hard edges) where it is not 3ds Max's, pinned so that a change shows. 3ds Max
# gives a Shell's rim smoothing groups of its own, hard against both surfaces, which the open edges marked sharp give
# Blender too, but for two cases the report names: auto smooth also splits the rim where its faces turn by more than
# 45 degrees (FixtureShellPlane: 3ds Max 6 regions and 12 hard edges), and the override group with auto smooth off
# merges the rim into the side of that group (FixtureShellOverride: 3ds Max 9 and 22).
# FixtureSymmetryTurned: Blender's Mirror welds the corner 0.062 off the plane onto it, where 3ds Max slices beside
# it: 3ds Max keeps a sliver of the side beyond the box's sharp vertical corner edge, smooth with its mirror copy;
# in Blender that corner edge lands on the plane as the seam between the other side and its copy, a hard edge that
# splits one more region (the vertex and triangle counts agree).
SMOOTHING_DIFFERS = {"FixtureShellPlane": (0, 3, 8), "FixtureShellOverride": (0, 11, 24),
                     "FixtureSymmetryTurned": (0, 7, 17)}
FACING_TOLERANCE = 1e-4  # the oracle's: a winding normal's z within it faces sideways


def _smoothing(mesh):
    """How an evaluated mesh is shaded, as the oracle's eval_mesh.smoothing: (flat, regions, hard edges): the
    triangles of flat faces; the smooth faces joined through the edges with exactly two faces, both smooth, not
    sharp, counted; such edges marked sharp."""
    n = len(mesh.polygons)
    attr = mesh.attributes.get("sharp_face")
    flat = [d.value for d in attr.data] if attr else [False] * n
    attr = mesh.attributes.get("sharp_edge")
    sharp = [d.value for d in attr.data] if attr else [False] * len(mesh.edges)
    faces_of = collections.defaultdict(list)
    for p in mesh.polygons:
        for i in p.loop_indices:
            faces_of[mesh.loops[i].edge_index].append(p.index)
    parent = list(range(n))

    def root(f):
        while parent[f] != f:
            parent[f] = parent[parent[f]]
            f = parent[f]
        return f

    hard = 0
    for e, fs in faces_of.items():
        if len(fs) != 2 or flat[fs[0]] or flat[fs[1]]:
            continue
        if sharp[e]:
            hard += 1
        else:
            a, b = root(fs[0]), root(fs[1])
            if a != b:
                parent[a] = b
    return (sum(len(p.vertices) - 2 for p in mesh.polygons if flat[p.index]),
            len({root(p.index) for p in mesh.polygons if not flat[p.index]}), hard)


def _facing(mesh, mw, meters, object_transform):
    """The evaluated triangles by the way they face in 3ds Max's object space, as the oracle's eval_mesh counts
    them, summed over material IDs: [up, down, side]. The world vertices (file units) are taken back by the
    inverse of the oracle's object transform (rows, row vectors); a face's triangles share its winding normal."""
    t = object_transform
    to_object = Matrix(((t[0], t[3], t[6], t[9]), (t[1], t[4], t[7], t[10]), (t[2], t[5], t[8], t[11]),
                        (0.0, 0.0, 0.0, 1.0))).inverted()
    pts = [to_object @ ((mw @ v.co) / meters) for v in mesh.vertices]
    counts = [0, 0, 0]
    for p in mesh.polygons:
        v = [pts[i] for i in p.vertices]
        for k in range(1, len(v) - 1):
            nrm = (v[k] - v[0]).cross(v[k + 1] - v[0])
            z = nrm.normalized().z if nrm.length > 1e-12 else 0.0
            counts[0 if z > FACING_TOLERANCE else 1 if z < -FACING_TOLERANCE else 2] += 1
    return counts


def _setting_ok(got, want):
    if isinstance(want, tuple):
        return tuple(got) == want
    if isinstance(want, float):
        return abs(got - want) <= 1e-6 * max(1.0, abs(want))
    return got == want


def _unique_names(names):
    """names as Blender keeps them on one object, where a modifier's name is unique: a repeat gets .001, .002, ...
    (FixtureShellSymQuarter's two Symmetries)."""
    seen, out = collections.Counter(), []
    for n in names:
        out.append(n if not seen[n] else "%s.%03d" % (n, seen[n]))
        seen[n] += 1
    return out


def check_converted(label, ob, node, o, meters, desc):
    """The Blender modifiers of a node (node.converted, convert.modifiers): types, order, names, settings and mirror
    objects; when MaxDrop evaluates the rest of the stack, the evaluated mesh has 3ds Max's vertex and triangle
    counts (eval_verts, eval_faces) and world box. Creases on the sharp edges of a mesh that asks for them, but its
    open edges (a hardened Shell rim's)."""
    md = desc.meshes[node.mesh]
    crease = ob.data.attributes.get("crease_edge")
    sharp = ob.data.attributes.get("sharp_edge")
    if md.creases:
        faces = collections.Counter(lp.edge_index for lp in ob.data.loops)
        flags = [d.value and faces[k] != 1 for k, d in enumerate(sharp.data)] if sharp else []
        check(label + ": sharp edges creased", crease is not None and len(flags) == len(crease.data)
              and all((c.value == 1.0) == f for c, f in zip(crease.data, flags)) and any(flags))
    else:
        check(label + ": no crease", crease is None or not any(d.value for d in crease.data))
    mods = list(ob.modifiers)
    check(label + ": Blender modifiers in the converted order", [(m.type, m.name) for m in mods] ==
          list(zip([c.kind for c in node.converted], _unique_names([c.name for c in node.converted]))),
          str([(m.type, m.name) for m in mods]))
    if not node.converted:
        return
    for mod, c in zip(mods, node.converted):
        bad = [a for a, v in c.settings if not _setting_ok(getattr(mod, a), v)]
        check(label + ": %s settings" % mod.name, not bad and mod.show_viewport == c.show_viewport, str(bad))
        if mod.type == 'MIRROR':
            mirror = mod.mirror_object
            if c.mirror is None:
                check(label + ": no mirror object", mirror is None)
            else:
                check(label + ": the mirror object an empty child at the gizmo", mirror is not None
                      and mirror.type == 'EMPTY' and mirror.parent == ob and close(
                          [v for row in mirror.matrix_basis for v in row], [v for row in c.mirror for v in row],
                          1e-6), mirror and str(mirror.matrix_basis))
    if node.modifiers:
        return
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    mesh = ev.to_mesh()
    try:
        mw = world_of(ob)
        world = [mw @ v.co for v in mesh.vertices]
        triangles = sum(len(p.vertices) - 2 for p in mesh.polygons)
        counts = (len(mesh.vertices), triangles)
        smoothing = _smoothing(mesh)
        facing = _facing(mesh, mw, meters, o["object_transform"]) if any(
            c.kind == 'SOLIDIFY' for c in node.converted) else None
    finally:
        ev.to_mesh_clear()
    lo = [min(p[k] for p in world) / meters for k in range(3)]
    hi = [max(p[k] for p in world) / meters for k in range(3)]
    # a vertex within the weld threshold of the mirror plane: Blender's Mirror merges it with its copy onto the
    # plane, 3ds Max's Symmetry slices beside it (FixtureSymmetryTurned: a corner 0.062 off the plane, threshold 0.2)
    weld = max([dict(c.settings)["merge_threshold"] / meters for c in node.converted
                if c.kind == 'MIRROR' and dict(c.settings)["use_mirror_merge"]] or [0.0])
    tolerance = BBOX_TOLERANCE + weld
    check(label + ": evaluated world box = 3ds Max's", close(lo, o["bbox_min"], tolerance)
          and close(hi, o["bbox_max"], tolerance),
          "%s..%s vs %s..%s" % (["%.6g" % v for v in lo], ["%.6g" % v for v in hi], o["bbox_min"], o["bbox_max"]))
    if o["name"] not in EVAL_COUNT_DIFFERS:
        check(label + ": evaluated vertex and triangle counts = 3ds Max's", counts == (o["eval_verts"],
                                                                                       o["eval_faces"]),
              "%d, %d vs %s, %s" % (counts + (o["eval_verts"], o["eval_faces"])))
        sm = o["eval_mesh"]["smoothing"]
        want = (sm["flat"], sm["regions"], sm["hard_edges"])
        if o["name"] in SMOOTHING_DIFFERS:
            check(label + ": evaluated shading (flat, regions, hard edges) as pinned, 3ds Max's %s" % (want,),
                  smoothing == SMOOTHING_DIFFERS[o["name"]] and smoothing != want, str(smoothing))
        else:
            check(label + ": evaluated shading (flat, regions, hard edges) = 3ds Max's", smoothing == want,
                  "%s vs %s" % (smoothing, want))
        if facing is not None:  # a Shell's side and facing (inside out or not)
            want = [sum(h[k] for h in o["eval_mesh"]["material_ids"]) for k in (1, 2, 3)]
            check(label + ": evaluated triangles facing up, down, sideways = 3ds Max's", facing == want,
                  "%s vs %s" % (facing, want))


def check_ignore_option(path, modules):
    """stack_convert imported with Modifiers: Ignore: no Blender modifier, no mirror empty, every modifier counted as
    not applied."""
    empty_scene()
    result = bpy.ops.import_scene.maxdrop(filepath=path, modifiers='IGNORE')
    check("stack_convert: Ignore: the operator finishes", result == {'FINISHED'}, str(result))
    mods = [m.type for ob in bpy.data.objects for m in ob.modifiers]
    check("stack_convert: Ignore: no Blender modifier, no empty", mods == [] and all(
        ob.type == 'MESH' for ob in bpy.data.objects), str(mods))
    text = bpy.data.texts.get(modules[4].TEXT_NAME)
    check("stack_convert: Ignore: the report counts them as not applied", text is not None and
          "nodes by class: Symmetry 5, TurboSmooth 5, Shell 2, Bend 1, MeshSmooth 1" in text.as_string()
          and "converted to a Blender modifier" not in text.as_string())


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
    if shape["renderable"] and shape["rectangular"]:
        check_section(label, ob, shape, meters)
    elif shape["renderable"]:
        check(label + ": a bevel of the thickness", abs(cu.bevel_depth - shape["thickness"] / 2 * meters) < 1e-9 and
              cu.bevel_resolution == (shape["sides"] - 4) // 2 and cu.bevel_mode == 'ROUND',
              "%g, %d, %s" % (cu.bevel_depth, cu.bevel_resolution, cu.bevel_mode))
        check_round_caps(label, ob, shape)
    else:
        check(label + ": no bevel", cu.bevel_depth == 0 and cu.bevel_object is None, str(cu.bevel_depth))
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


def check_round_caps(label, ob, shape):
    """A round bevel's ends, as 3ds Max renders an open shape: each end of an open spline capped (faces whose every
    vertex lies on the bevel ring around the end point, together the regular polygon of the bevel ring), a
    closed spline uncapped. Blender caps with n - 2 triangles over a ring of their own."""
    cu = ob.data
    r, n = cu.bevel_depth, 4 + 2 * cu.bevel_resolution  # the ring Blender sweeps: 3ds Max's even sides
    ngon = n / 2 * r * r * math.sin(2 * math.pi / n)
    evaluated = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()

    def cap_area(point):
        return sum(f.area for f in mesh.polygons
                   if all((mesh.vertices[i].co - point).length < r * (1 + 1e-6) for i in f.vertices))

    for k, sp in enumerate(cu.splines):
        pts = sp.bezier_points
        if sp.use_cyclic_u:
            area = cap_area(pts[0].co)
            check("%s spline %d: closed, no cap" % (label, k), area == 0, str(area))
            continue
        areas = [cap_area(pts[0].co), cap_area(pts[-1].co)]
        check("%s spline %d: open, capped at both ends as 3ds Max caps it (the %d-gon of its sides each)" %
              (label, k, n), all(abs(a - ngon) < 1e-6 * ngon for a in areas), "%s vs %g" % (areas, ngon))
    evaluated.to_mesh_clear()


def check_section(label, ob, shape, meters):
    """A rectangular section: a bevel object of the width x length rectangle (any angle), hidden, unselectable, in
    the import's collection tree (the cleanup removes that tree; an unlinked one is lost on save)."""
    cu = ob.data
    sec = cu.bevel_object
    check(label + ": a bevel object, no round bevel", cu.bevel_mode == 'OBJECT' and sec is not None and
          sec.type == 'CURVE' and cu.bevel_depth == 0, "%s %r %g" % (cu.bevel_mode, sec, cu.bevel_depth))
    if sec is None or sec.type != 'CURVE':
        return
    root = bpy.data.collections.get(label.split("/")[0])  # the import's collection is named after the file
    flags = (sec.hide_viewport, sec.hide_render, sec.hide_select, sec.get("maxdrop_helper"))
    check(label + ": the section object hidden, marked, in the import's collection",
          flags == (True, True, True, "section") and root is not None and sec.name in root.all_objects,
          "%s %s" % (flags, [c.name for c in sec.users_collection]))
    pts = [p.co for sp in sec.data.splines for p in sp.points]
    half = math.hypot(shape["width"], shape["length"]) / 2 * meters
    check(label + ": the section a closed 2D rectangle of width x length", sec.data.dimensions == '2D' and
          sec.data.fill_mode == 'NONE' and len(sec.data.splines) == 1 and sec.data.splines[0].use_cyclic_u and
          len(pts) == 4 and all(abs(math.hypot(p.x, p.y) - half) < 1e-9 for p in pts) and
          abs((pts[0] - pts[1]).length - shape["width"] * meters) < 1e-9 and
          abs((pts[1] - pts[2]).length - shape["length"] * meters) < 1e-9, str([tuple(p) for p in pts]))


def check_shapes_more(obs, meters):
    """The rectangular sections against 3ds Max's render meshes (snapshotAsMesh renderMesh:true; the fixture's
    script): FixtureSection, a line along X with width 4, length 1 and angle 30, has at x = 0 the corners
    (Y, Z) = (-1.48205, 1.43301), (1.98205, -0.566987), (1.48205, -1.43301), (-1.98205, 0.566987) and a cap at each
    end; FixtureSectionLoop,
    a circle of radius 10 with width 3, length 1.5, spans 8.49005 .. 11.5099 out from its center (3ds Max mitres at
    its polyline points, Blender a little less) and Z -0.75 .. 0.75."""
    by_name = {ob.name: ob for ob in obs}
    depsgraph = bpy.context.evaluated_depsgraph_get()

    def verts(ob):
        evaluated = ob.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        out = [Vector(v.co) / meters for v in mesh.vertices]
        evaluated.to_mesh_clear()
        return out

    got = sorted({(round(v.y, 4), round(v.z, 4)) for v in verts(by_name["FixtureSection"]) if abs(v.x) < 1e-6})
    want = sorted((round(y, 4), round(z, 4)) for y, z in ((-1.48205, 1.43301), (1.98205, -0.566987),
                                                          (1.48205, -1.43301), (-1.98205, 0.566987)))
    check("shapes_more/FixtureSection: the section's corners where 3ds Max renders them",
          len(got) == 4 and close([c for p in got for c in p], [c for p in want for c in p], 1e-3),
          "%s vs %s" % (got, want))
    evaluated = by_name["FixtureSection"].evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    caps = [0.0, 0.0]  # the area of the faces lying in the planes x = 0 and x = 10, in square units
    for f in mesh.polygons:
        xs = [mesh.vertices[i].co.x / meters for i in f.vertices]
        for k, end in enumerate((0.0, 10.0)):
            if all(abs(x - end) < 1e-6 for x in xs):
                caps[k] += f.area / meters ** 2
    evaluated.to_mesh_clear()
    check("shapes_more/FixtureSection: capped at both ends, as 3ds Max caps it (width x length each)",
          all(abs(a - 4.0) < 1e-4 for a in caps), str(caps))
    loop = verts(by_name["FixtureSectionLoop"])
    radial = [math.hypot(v.x, v.y) for v in loop]
    zs = [v.z for v in loop]
    check("shapes_more/FixtureSectionLoop: the section across the circle and up",
          abs(min(radial) - 8.49005) < 0.02 and abs(max(radial) - 11.5099) < 0.02 and
          abs(min(zs) + 0.75) < 1e-6 and abs(max(zs) - 0.75) < 1e-6,
          "%g .. %g, z %g .. %g" % (min(radial), max(radial), min(zs), max(zs)))
    slots = {ob.name: [(s.link, s.material and s.material.name) for s in ob.material_slots]
             for ob in obs if ob.type == 'CURVE'}
    want = dict.fromkeys(slots, [])
    want.update(FixtureCurveStd=[('DATA', "FixtureCurveRed")], FixtureCurveMulti=[('DATA', "FixtureCurveSubOne")],
                FixtureCurveIds=[('DATA', "FixtureCurveSubOne"), ('DATA', "FixtureCurveSubTwo")],
                FixtureCurveMixed=[('DATA', "FixtureCurveSubTwo")])
    check("shapes_more: a curve's 3ds Max materials in slots on the curve (a Multi/Sub-Object's entries for its "
          "splines' IDs), none on the others", slots == want and len(slots) == 17, str(slots))
    indices = {name: [sp.material_index for sp in by_name[name].data.splines]
               for name in ("FixtureCurveIds", "FixtureCurveMixed", "FixtureCurveMulti")}
    check("shapes_more: each spline on the slot of its segments' material ID (FixtureCurveIds: ID 2 then ID 1; "
          "FixtureCurveMixed: its first segment's)",
          indices == {"FixtureCurveIds": [1, 0], "FixtureCurveMixed": [0], "FixtureCurveMulti": [0]}, str(indices))


def check_modifier_pivot(obs, meters):
    """FixtureBent's pivot alone is turned 30 degrees about Z: its base mesh lands where the source's does, moved by
    the 30 units between the two nodes (the offset rotation undoes the pivot's)."""
    by_name = {ob.name: ob for ob in obs}
    src, bent = by_name["FixtureSource"], by_name["FixtureBent"]
    a = [c / meters for v in src.data.vertices for c in src.matrix_world @ v.co]
    b = [c / meters for v in bent.data.vertices for c in bent.matrix_world @ v.co - Vector((30 * meters, 0, 0))]
    check("modifier_pivot: FixtureBent has a mesh of its own", src.data != bent.data)
    check("modifier_pivot: the rotated pivot leaves the object in place", close(b, a, BBOX_TOLERANCE))


def check_lookat(path, desc, obs, nodes, meters):
    """lookat: the Target objects are empties, not placeholders; by default nothing is constrained (the rotation is
    baked, checked with every world matrix above). With Keep Targets each node whose Look At a Track To can follow
    gets one, aimed at its target's object, and its evaluated world matrix is still 3ds Max's; a roll and the Y axis
    keep the baked rotation and the report names them."""
    targets = [ob.name for ob, o in zip(obs, nodes) if o["base_class_name"] == "Targetobject"]
    # the target cameras are cameras, the target spot a light: the Point helper is the one placeholder
    check("lookat: the five targets are empties, no placeholders", len(targets) == 5 and all(
        bpy.data.objects[t].type == 'EMPTY' for t in targets) and dict(desc.placeholders) == {"Point": 1},
        str(dict(desc.placeholders)))
    check("lookat: no constraint without Keep Targets", not any(ob.constraints for ob in obs))
    empty_scene()
    result = bpy.ops.import_scene.maxdrop(filepath=path, keep_targets=True)
    check("lookat Keep Targets: the operator finishes", result == {'FINISHED'}, str(result))
    bpy.context.view_layer.update()
    obs = objects_of(desc)
    by_index = {node.index: ob for node, ob in zip(desc.nodes, obs)}
    tracked = []
    for ob, node, o in zip(obs, desc.nodes, nodes):
        label = "lookat Keep Targets/%s" % o["name"]
        look = node.look_at
        cons = [(c.type, c.name) for c in ob.constraints]
        if look is None or look.track is None:
            check(label + ": no constraint", cons == [], str(cons))
            continue
        tracked.append(o["name"])
        c = ob.constraints.get("MaxDrop Target")
        check(label + ": one Track To aimed at its target", cons == [('TRACK_TO', "MaxDrop Target")] and
              c.target == by_index[look.target] and (c.track_axis, c.up_axis, c.use_target_z) ==
              (look.track, look.up, look.target_z), "%s %s" % (cons, c and (c.track_axis, c.up_axis)))
        got = max_rows(ob.matrix_world, meters)
        check(label + ": evaluated world matrix = 3ds Max's", close(got, o["transform"], MATRIX_TOLERANCE),
              "%s vs %s" % (["%.6g" % v for v in got], o["transform"]))
    check("lookat Keep Targets: the Look At nodes a Track To can aim", tracked == [
        "FixtureCam", "FixtureCamDown", "FixtureSpot", "FixtureCamChild", "FixtureLooker"], str(tracked))
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    named = [n for n in ("FixtureCamRoll", "FixtureLookerY") if any(
        n in line and "Keep Targets" in line for line in body.splitlines())]
    check("lookat Keep Targets: the report names the two kept fixed", named == ["FixtureCamRoll", "FixtureLookerY"],
          str(named))
    # a look-at whose target was not built, or that aims at itself, keeps its rotation and is named with the reason.
    # No .max reaches either guard (every node is built; a self-aim is damaged by reader.controllers, look_at None):
    # hand-built descriptions
    from types import SimpleNamespace
    from maxdrop.build import objects as build_objects
    from maxdrop.convert.scene import LookAtDescription
    lone = [bpy.data.objects.new("FixtureLone%d" % k, None) for k in range(2)]
    aim = ("TRACK_NEGATIVE_Z", "UP_Y", False, None)
    fake = SimpleNamespace(nodes=[SimpleNamespace(index=0, look_at=LookAtDescription(99, *aim)),
                                  SimpleNamespace(index=1, look_at=LookAtDescription(1, *aim))])
    kept = build_objects.track_targets(fake, SimpleNamespace(objects={0: lone[0], 1: lone[1]}))
    check("lookat Keep Targets: a missing or self target is returned with its reason, no constraint",
          kept == [(0, build_objects.NO_TARGET), (1, build_objects.SELF_TARGET)]
          and not any(ob.constraints for ob in lone), str(kept))
    for ob in lone:
        bpy.data.objects.remove(ob)
    # the note on the axis conversion: only when the file's up does not stay Blender's Z
    for forward, up, expected in (('X', 'Z', False), ('-Z', 'Y', True)):
        empty_scene()
        result = bpy.ops.import_scene.maxdrop(filepath=path, keep_targets=True, axis_forward=forward, axis_up=up)
        text = bpy.data.texts.get("MaxDrop Report")
        noted = text is not None and "Track To keeps Blender's Z up" in text.as_string()
        label = "lookat Keep Targets, Forward %s, Up %s" % (forward, up)
        check(label + ": the up note " + ("given" if expected else "not given"),
              result == {'FINISHED'} and noted == expected, "%s, noted %s" % (result, noted))
