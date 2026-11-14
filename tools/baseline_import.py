# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Runs inside Blender for tools/baseline.py: import one .max with the dev package, write what arrived as JSON.

    blender --background --factory-startup --python tools/baseline_import.py -- <repo root> <file.max> <out.json>

The JSON holds counts only: no object, material or file name of the scene.
"""
import json
import os
import sys
import time

import bpy

ROOT, PATH, OUT = sys.argv[sys.argv.index("--") + 1:][:3]
sys.path.insert(0, os.path.abspath(ROOT))
import maxdrop  # noqa: E402  (the path above comes first)


def scene_nodes():
    """The nodes the engine walked, by its own test (make_scene). None once the engine no longer keeps them."""
    engine = sys.modules.get(maxdrop.__name__ + ".import_max")
    try:
        chunks = engine.SCENE_LIST[0].children
        return sum(1 for c in chunks if isinstance(c, engine.SceneChunk)
                   and (engine.get_guid(c) == 0x1 and engine.get_super_id(c) == 0x1) or engine.get_node_parent(c))
    except Exception:
        return None


maxdrop.register()
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob)
for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
    for item in list(block):
        block.remove(item)

start = time.perf_counter()
result = bpy.ops.import_scene.maxdrop(filepath=PATH)
seconds = time.perf_counter() - start

meshes = [ob for ob in bpy.data.objects if ob.type == 'MESH']
found = {
    "blender": bpy.app.version_string,
    "python": sys.version.split()[0],
    "result": sorted(result),
    "import_seconds": round(seconds, 1),
    "nodes": scene_nodes(),
    "objects": len(bpy.data.objects),
    "mesh_objects": len(meshes),
    "empties": sum(1 for ob in bpy.data.objects if ob.type == 'EMPTY'),
    "parented": sum(1 for ob in bpy.data.objects if ob.parent),
    "vertices": sum(len(ob.data.vertices) for ob in meshes),
    "polygons": sum(len(ob.data.polygons) for ob in meshes),
    "meshes_with_uv": sum(1 for ob in meshes if ob.data.uv_layers),
    "meshes_with_material": sum(1 for ob in meshes if any(slot.material for slot in ob.material_slots)),
    "materials": len(bpy.data.materials),
    "images": len(bpy.data.images),
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(found, f, indent=1)
print("BASELINE IMPORT DONE %s" % json.dumps(found))
sys.stdout.flush()
