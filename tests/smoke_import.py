# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Import test for the MaxDrop dev package: every .max given, through the operator a user runs.

Run headless with an isolated profile so your own preferences are never touched:
  $env:BLENDER_USER_RESOURCES="<scratch>\\profile"
  & blender --background --factory-startup --python-exit-code 1 --python tests\\smoke_import.py -- <file or folder> ...

Without arguments it takes tests/fixtures/*.max; with no file at all it prints `IMPORT SKIPPED` and exits 0.
Each file is imported into an emptied scene with the default options and must bring at least one mesh with faces and
one material; the counts are printed so that runs on different Blender versions can be compared.
Prints `IMPORT PASSED` (exit 0) or `IMPORT FAILED` (exit 1).
"""
import glob
import os
import sys
import traceback

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  [%s]" % detail if detail else ""))
    if not cond:
        failures.append(name)


def fixtures():
    found = []
    for path in (argv or [os.path.join(ROOT, "tests", "fixtures")]):
        found += sorted(glob.glob(os.path.join(path, "*.max"))) if os.path.isdir(path) else [path]
    return found


def empty_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for item in list(block):
            block.remove(item)


def import_one(path):
    name = os.path.basename(path)
    empty_scene()
    result = bpy.ops.import_scene.maxdrop(filepath=path)
    meshes = [ob for ob in bpy.data.objects if ob.type == 'MESH']
    check("%s: the operator finishes" % name, result == {'FINISHED'}, str(result))
    check("%s: a mesh with faces arrives" % name, any(len(ob.data.polygons) for ob in meshes))
    check("%s: a material arrives on a mesh" % name, any(slot.material for ob in meshes for slot in ob.material_slots))
    print("COUNTS %s: objects=%d meshes=%d vertices=%d polygons=%d materials=%d images=%d" % (
        name, len(bpy.data.objects), len(meshes), sum(len(ob.data.vertices) for ob in meshes),
        sum(len(ob.data.polygons) for ob in meshes), len(bpy.data.materials), len(bpy.data.images)))


def run():
    files = fixtures()
    if not files:
        return False
    sys.path.insert(0, ROOT)
    import maxdrop
    maxdrop.register()
    try:
        for path in files:
            check("%s exists" % path, os.path.isfile(path))
            if os.path.isfile(path):
                import_one(path)
    finally:
        maxdrop.unregister()
    return True


try:
    ran = run()
except Exception:
    traceback.print_exc()
    failures.append("exception")
    ran = True

print("IMPORT FAILED: %s" % ", ".join(failures) if failures else "IMPORT PASSED" if ran
      else "IMPORT SKIPPED: no .max file given and none in tests/fixtures")
sys.stdout.flush()
if failures:
    sys.exit(1)
