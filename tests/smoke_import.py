# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Import test for the MaxDrop dev package: every .max given, through the operator a user runs, also as a pack.

Run headless with an isolated profile so your own preferences are never touched:
  $env:BLENDER_USER_RESOURCES="<scratch>\\profile"
  & blender --background --factory-startup --python-exit-code 1 --python tests\\smoke_import.py -- <file or folder> ...

Without arguments it takes tests/fixtures/*.max; with no file at all it prints `IMPORT SKIPPED` and exits 0.
Each file is imported into an emptied scene with the default options and must bring at least one mesh with faces and
one material; the counts are printed so that runs on different Blender versions can be compared.

Every .max is then packed into a .zip in a scratch folder (the scene with the image and .ies files of its folder
tree) and imported from it: same checks, no fewer images, unpacked beside the zip. A zip holding it twice under two
names must be refused in EXEC mode with both names in the message, then import once the scene is named. The same
files are also chosen through directory + files, as the file browser and a drop pass them: a .max with a
one-scene zip, a two-scene zip with another pack (refused), a file named .zip that is not one (refused). A .zip,
.rar or .7z given as argument is imported through the operator as it is.
Prints `IMPORT PASSED` (exit 0) or `IMPORT FAILED` (exit 1).
"""
import glob
import os
import shutil
import sys
import tempfile
import traceback
import zipfile

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ARCHIVES = (".zip", ".rar", ".7z")
SECOND = "second.max"
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


def import_one(path, label=None, **options):
    """Import into an emptied scene and check it; the number of images."""
    name = label or os.path.basename(path)
    empty_scene()
    result = bpy.ops.import_scene.maxdrop(filepath=path, **options)
    meshes = [ob for ob in bpy.data.objects if ob.type == 'MESH']
    check("%s: the operator finishes" % name, result == {'FINISHED'}, str(result))
    check("%s: a mesh with faces arrives" % name, any(len(ob.data.polygons) for ob in meshes))
    check("%s: a material arrives on a mesh" % name, any(slot.material for ob in meshes for slot in ob.material_slots))
    print("COUNTS %s: objects=%d meshes=%d vertices=%d polygons=%d materials=%d images=%d" % (
        name, len(bpy.data.objects), len(meshes), sum(len(ob.data.vertices) for ob in meshes),
        sum(len(ob.data.polygons) for ob in meshes), len(bpy.data.materials), len(bpy.data.images)))
    return len(bpy.data.images)


def inside(path, folder):
    path, folder = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return os.path.commonpath([path, folder]) == folder


def maps_of(max_path, extensions):
    """(path in the zip, file) of the image and .ies files of the scene's folder tree."""
    root = os.path.dirname(os.path.abspath(max_path))
    for folder, _dirs, names in os.walk(root):
        for n in sorted(names):
            if n.rsplit(".", 1)[-1].casefold() in extensions:
                full = os.path.join(folder, n)
                yield os.path.relpath(full, root).replace(os.sep, "/"), full


def make_zip(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for arcname, source in entries:
            zf.write(source, arcname)
    return path


def as_pack(max_path, scratch, images_of_max, archive):
    name = os.path.basename(max_path)
    stem = os.path.splitext(name)[0]
    folder = os.path.join(scratch, "one")
    entries = [(stem + "/" + name, max_path)]
    entries += [(stem + "/" + arc, full) for arc, full in maps_of(max_path, archive.ASSET_EXTENSIONS)]
    zip_path = make_zip(os.path.join(folder, stem + ".zip"), entries)
    images = import_one(zip_path, "%s in a .zip (%d map files)" % (name, len(entries) - 1))
    check("%s in a .zip: no fewer images than from the .max" % name, images >= images_of_max,
          "%d from the .zip, %d from the .max" % (images, images_of_max))
    pack = os.path.join(folder, stem)
    check("%s in a .zip: unpacked beside the zip with its marker" % name,
          os.path.isfile(os.path.join(pack, name)) and os.path.isfile(os.path.join(pack, archive.MARKER)), pack)
    outside = [img.filepath for img in bpy.data.images
               if img.filepath and not inside(bpy.path.abspath(img.filepath), pack)]
    check("%s in a .zip: every image comes from the pack folder" % name, not outside, ", ".join(outside[:5]))


def attempt(**options):
    """(result, error message) of the operator in an emptied scene."""
    empty_scene()
    try:
        return bpy.ops.import_scene.maxdrop(**options), ""
    except RuntimeError as e:  # bpy.ops raises with the message when the operator reports an error
        return {'CANCELLED'}, str(e)


def two_scenes(max_path, scratch):
    name = os.path.basename(max_path)
    folder = os.path.join(scratch, "two")
    zip_path = make_zip(os.path.join(folder, "two.zip"), [("a/" + name, max_path), ("b/" + SECOND, max_path)])
    result, message = attempt(filepath=zip_path)
    check("two scenes in a .zip, none named: cancelled in EXEC mode", result == {'CANCELLED'}, str(result))
    check("two scenes in a .zip, none named: the message names both",
          ("a/" + name) in message and ("b/" + SECOND) in message, message.strip())
    check("two scenes in a .zip, none named: nothing unpacked", not os.path.exists(os.path.join(folder, "two")))
    import_one(zip_path, "two scenes in a .zip, %s named" % SECOND, pack_scene=SECOND)
    check("two scenes in a .zip: the named scene is unpacked into its own folder",
          os.path.isfile(os.path.join(folder, "two", "second", SECOND)))


def selections(max_path, scratch):
    """directory + files, as the file browser and a drop fill them."""
    name = os.path.basename(max_path)
    folder = os.path.join(scratch, "selection")
    os.makedirs(folder)
    shutil.copy(max_path, os.path.join(folder, name))
    make_zip(os.path.join(folder, "one.zip"), [("x/" + SECOND, max_path)])
    make_zip(os.path.join(folder, "two.zip"), [("a/" + name, max_path), ("b/" + SECOND, max_path)])
    with open(os.path.join(folder, "fake.zip"), "wb") as f:
        f.write(b"not an archive, whatever its name says")

    result, message = attempt(directory=folder, files=[{"name": name}, {"name": "one.zip"}])
    meshes = [ob for ob in bpy.data.objects if ob.type == 'MESH' and len(ob.data.polygons)]
    check("a .max and a one-scene .zip chosen together: both imported", result == {'FINISHED'} and len(meshes) >= 2,
          "%s, %d meshes %s" % (result, len(meshes), message.strip()))
    check("a .max and a one-scene .zip chosen together: the pack is unpacked",
          os.path.isfile(os.path.join(folder, "one", SECOND)))

    result, message = attempt(directory=folder, files=[{"name": "two.zip"}, {"name": "one.zip"}])
    check("a two-scene .zip chosen with another pack: cancelled, import it alone",
          result == {'CANCELLED'} and "import that pack alone" in message, message.strip())
    check("a two-scene .zip chosen with another pack: nothing of it unpacked",
          not os.path.exists(os.path.join(folder, "two")))

    result, message = attempt(directory=folder, files=[{"name": "fake.zip"}])
    check("a file named .zip that is not an archive: cancelled with a message",
          result == {'CANCELLED'} and "is not a .zip, .rar or .7z archive" in message, message.strip())


def run():
    files = fixtures()
    if not files:
        return False
    sys.path.insert(0, ROOT)
    import maxdrop
    maxdrop.register()
    scratch = tempfile.mkdtemp(prefix="maxdrop-smoke-")
    try:
        from maxdrop.intake import archive
        for n, path in enumerate(files):
            check("%s exists" % path, os.path.isfile(path))
            if not os.path.isfile(path):
                continue
            if path.lower().endswith(ARCHIVES):
                import_one(path)
                continue
            images = import_one(path)
            work = os.path.join(scratch, str(n))
            as_pack(path, work, images, archive)
            two_scenes(path, work)
            selections(path, work)
    finally:
        maxdrop.unregister()
        shutil.rmtree(scratch, ignore_errors=True)
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
