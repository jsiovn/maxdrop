# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fixture tests of the new pipeline inside Blender: every tests/fixtures/*.max through convert.scene.read and
build.objects.build, compared with its 3ds Max oracle (tests/fixtures/<name>.oracle.json).

Run headless with an isolated profile so your own preferences are never touched:
  $env:BLENDER_USER_RESOURCES="<scratch>\\profile"
  & blender --background --factory-startup --python-exit-code 1 --python tests\\blender\\run.py [-- <file.max> ...]

Per fixture, into an emptied scene: node order and names, parents, world matrices (1e-4, in file units), world
bounding boxes of the meshes (1e-3), vertex and face counts, UV layers, sharp edges and flat faces, material
indices, which objects share a mesh (the oracle's instances), outward normals as rendered (the inverse transpose
of the world matrix times each face normal points away from the oracle's bounding box center, also on the
mirrored object) and the class of each placeholder. The oracle has no map channels or smoothing groups: those
expectations come from the fixture scripts (tools/fixtures/*.ms).
Prints `FIXTURES PASSED` (exit 0) or `FIXTURES FAILED` (exit 1).
"""
import glob
import json
import os
import sys
import traceback

import bpy
from mathutils import Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MATRIX_TOLERANCE = 1e-4
BBOX_TOLERANCE = 1e-3
UV_LAYERS = {  # mapcoords:true in the script gives channel 1
    "box_poly_standard": ["UVMap"],
    "editable_mesh": ["UVMap"],
    "hierarchy": [],
    "instances": ["UVMap"],
    "layers_flags": [],
    "multi_uv": ["UVMap", "UVChannel_2", "UVChannel_3"],
    "units_cm": ["UVMap"],
    "units_in": ["UVMap"],
    "units_mm": ["UVMap"],
}
SHARP_EDGES = {"editable_mesh": 8}  # group 1 on top and bottom, 2 on the sides; a box with a group per side: 12
SHARP_EDGES_DEFAULT = 12
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


def close(a, b, tolerance):
    return len(a) == len(b) and all(abs(x - y) <= tolerance for x, y in zip(a, b))


def max_rows(m, meters):
    """A Blender world matrix as the oracle's 12 floats: Max's rows, translation in file units."""
    out = []
    for r in range(3):
        out += [m[c][r] for c in range(3)]
    return out + [m[c][3] / meters for c in range(3)]


def run_fixture(path, convert_scene, build_objects):
    name = os.path.splitext(os.path.basename(path))[0]
    with open(path[:-4] + ".oracle.json", encoding="utf-8") as f:
        oracle = json.load(f)
    empty_scene()
    desc = convert_scene.read(path)
    built = build_objects.build(desc, bpy.context.scene.collection)
    bpy.context.view_layer.update()
    meters = desc.meters
    nodes = oracle["nodes"]
    check("%s: one object per node" % name, len(built.objects) == len(nodes) == len(bpy.data.objects),
          "%d objects, %d nodes" % (len(bpy.data.objects), len(nodes)))
    check("%s: nodes in oracle order" % name, [n.name for n in desc.nodes] == [n["name"] for n in nodes])
    obs = [built.objects[n.index] for n in desc.nodes]
    handle_of = {ob.as_pointer(): o["handle"] for ob, o in zip(obs, nodes)}
    for ob, node, o in zip(obs, desc.nodes, nodes):
        label = "%s/%s" % (name, o["name"])
        parent = handle_of.get(ob.parent.as_pointer()) if ob.parent else None
        check(label + ": parent", parent == o["parent"], "%r vs %r" % (parent, o["parent"]))
        got = max_rows(ob.matrix_world, meters)
        check(label + ": world matrix", close(got, o["transform"], MATRIX_TOLERANCE),
              "%s vs %s" % (["%.6g" % v for v in got], o["transform"]))
        if o["base_verts"] is None:
            check(label + ": placeholder empty", ob.type == 'EMPTY' and ob.get("maxdrop_class") == o["base_class_name"],
                  "%s %r" % (ob.type, ob.get("maxdrop_class")))
            continue
        check(label + ": mesh object", ob.type == 'MESH', ob.type)
        if ob.type != 'MESH':
            continue
        mesh = ob.data
        mw = ob.matrix_world
        world = [mw @ v.co for v in mesh.vertices]
        lo = [min(p[k] for p in world) / meters for k in range(3)]
        hi = [max(p[k] for p in world) / meters for k in range(3)]
        check(label + ": world bounding box", close(lo, o["bbox_min"], BBOX_TOLERANCE)
              and close(hi, o["bbox_max"], BBOX_TOLERANCE),
              "%s..%s vs %s..%s" % (["%.6g" % v for v in lo], ["%.6g" % v for v in hi], o["bbox_min"], o["bbox_max"]))
        check(label + ": vertex and face counts", (len(mesh.vertices), len(mesh.polygons)) ==
              (o["base_verts"], o["base_faces"]), "%d, %d" % (len(mesh.vertices), len(mesh.polygons)))
        uv = [layer.name for layer in mesh.uv_layers]
        check(label + ": UV layers", uv == UV_LAYERS[name], str(uv))
        md = desc.meshes[node.mesh]
        for (uv_name, uv_data), layer in zip(md.uv_layers, mesh.uv_layers):
            got = [c for d in layer.data for c in d.uv]
            check(label + ": UV data of " + uv_name, close(got, uv_data.ravel().tolist(), 1e-6))
        sharp = mesh.attributes.get("sharp_edge")
        count = sum(1 for d in sharp.data if d.value) if sharp else 0
        check(label + ": sharp edges", count == SHARP_EDGES.get(name, SHARP_EDGES_DEFAULT), str(count))
        flat = mesh.attributes.get("sharp_face")
        check(label + ": every face smooth", flat is None or not any(d.value for d in flat.data))
        indices = [p.material_index for p in mesh.polygons]
        check(label + ": material indices", indices == md.material_indices.tolist(), str(indices))
        sharing = sorted(handle_of[other.as_pointer()] for other in obs if other.data == mesh)
        check(label + ": objects sharing the mesh = oracle instances", sharing == o["instances"], str(sharing))
        center = (Vector(o["bbox_min"]) + Vector(o["bbox_max"])) * (meters / 2.0)
        normal_matrix = mw.to_3x3().inverted().transposed()
        outward = [(normal_matrix @ p.normal).dot(mw @ p.center - center) > 0 for p in mesh.polygons]
        check(label + ": normals outward as rendered", all(outward), "%d of %d" % (sum(outward), len(outward)))
    if name == "instances":
        users = sorted(m.users for m in bpy.data.meshes)
        check("instances: four objects share one mesh, the copy has its own", users == [1, 4], str(users))
    if name == "hierarchy":
        mirrored = [n.name for n in desc.nodes if n.mirrored]
        check("hierarchy: FixtureLeaf is the mirrored node", mirrored == ["FixtureLeaf"], str(mirrored))
    print("COUNTS %s: objects=%d meshes=%d placeholders=%d issues=%d" % (
        name, len(bpy.data.objects), len(bpy.data.meshes), sum(desc.placeholders.values()), len(desc.issues)))


def main():
    print("Blender " + bpy.app.version_string)
    sys.path.insert(0, ROOT)
    import maxdrop
    check("package imported from the repo root",
          os.path.normcase(os.path.dirname(os.path.dirname(maxdrop.__file__))) == os.path.normcase(ROOT))
    from maxdrop.build import objects as build_objects
    from maxdrop.convert import scene as convert_scene
    paths = argv or sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
    check("fixtures found", bool(paths))
    for path in paths:
        try:
            run_fixture(path, convert_scene, build_objects)
        except Exception:
            traceback.print_exc()
            check("%s: no exception" % os.path.basename(path), False)


try:
    main()
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FIXTURES FAILED: %s" % ", ".join(failures) if failures else "FIXTURES PASSED")
sys.stdout.flush()
sys.exit(1 if failures else 0)
