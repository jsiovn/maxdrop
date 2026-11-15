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
one-scene zip, a two-scene zip with another pack (refused), a good zip then one with a damaged scene (refused,
nothing imported, the message names the good one, which stays unpacked), a file named .zip that is not one
(refused). A .zip, .rar or .7z given as argument is imported through the operator as it is.

Without arguments, the units fixtures: with Units = Auto the box (10 x 20 x 30 system units in each file) measures
that many millimeters, centimeters and inches; with Units = Millimeters all three measure the same; Scale 2 doubles
it; Up Y turns it; a file that does not state its unit takes Scale as meters per unit, with a note. The pre-flight
line of a fixture names its 3ds Max version, its object count and its unit. Object Filter without UV Maps leaves
no UV layer, without Material no material slot. A file that is not a .max beside a fixture: the fixture is imported
and the other named in a warning; that file alone: cancelled with its name in the message.
After every import the text "MaxDrop Report" exists and its first line names the .max (and the archive of a pack);
for the fixtures the operator reported INFO with the report's summary, nothing left out. Two scenes in one run: the
text holds both reports.
Prints `IMPORT PASSED` (exit 0) or `IMPORT FAILED` (exit 1).
"""
import glob
import os
import shutil
import struct
import sys
import tempfile
import traceback
import zipfile

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ARCHIVES = (".zip", ".rar", ".7z")
SECOND = "second.max"
TEXT_NAME = "MaxDrop Report"
failures = []
REPORTS = []  # (level, message) of each scene the operator imported, while record_reports() wraps it


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
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.texts):
        for item in list(block):
            block.remove(item)


def record_reports(cls):
    """Wrap the operator's _import_scene so that the (level, line) pairs execute() reports for each scene land in
    REPORTS. Operator.report itself is an RNA function, which a Python attribute of the class cannot shadow. The
    original, to put back."""
    original = cls._import_scene

    def import_scene(self, *args, **kwargs):
        lines, rep = original(self, *args, **kwargs)
        REPORTS.extend(lines)
        return lines, rep

    cls._import_scene = import_scene
    return original


def check_report(name, max_name, pack_name=None):
    """The text MaxDrop Report after an import: it names the .max (and the archive of a pack); for the fixtures the
    operator reported INFO with the report's summary, nothing left out."""
    text = bpy.data.texts.get(TEXT_NAME)
    body = text.as_string() if text is not None else ""
    check("%s: the text %s exists" % (name, TEXT_NAME), text is not None)
    if max_name is not None:
        first = body.split("\n", 1)[0]
        check("%s: the report's first line names the file" % name, first == "MaxDrop import report: " + max_name,
              first)
    if pack_name is not None:
        check("%s: the report names the scene pack" % name, ("\nScene pack: %s\n" % pack_name) in body)
    if not argv:
        summaries = [(kind, m) for kind, m in REPORTS if m.startswith("Imported ")]
        check("%s: the operator reported INFO, nothing left out" % name,
              summaries and all(kind == 'INFO' and m.endswith("nothing left out.") for kind, m in summaries)
              and "\nNothing was left out." in body, str(summaries))


def import_one(path, label=None, max_name=None, pack_name=None, **options):
    """Import into an emptied scene and check it; the number of images. max_name: the .max the report must name,
    the file's own name by default when it is a .max; pack_name: the archive the report must name."""
    name = label or os.path.basename(path)
    if max_name is None and path.lower().endswith(".max"):
        max_name = os.path.basename(path)
    empty_scene()
    REPORTS.clear()
    result = bpy.ops.import_scene.maxdrop(filepath=path, **options)
    meshes = [ob for ob in bpy.data.objects if ob.type == 'MESH']
    check("%s: the operator finishes" % name, result == {'FINISHED'}, str(result))
    check_report(name, max_name, pack_name)
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


def damage(zip_path):
    """Flip one byte of the first member's stored data: the directory still lists it, unpacking fails its CRC."""
    with zipfile.ZipFile(zip_path) as zf:
        info = zf.infolist()[0]
    with open(zip_path, "r+b") as f:
        f.seek(info.header_offset + 26)
        name_len, extra_len = struct.unpack("<HH", f.read(4))
        f.seek(info.header_offset + 30 + name_len + extra_len + info.file_size // 2)
        byte = f.read(1)[0]
        f.seek(-1, os.SEEK_CUR)
        f.write(bytes([byte ^ 0xFF]))


def as_pack(max_path, scratch, images_of_max, archive):
    name = os.path.basename(max_path)
    stem = os.path.splitext(name)[0]
    folder = os.path.join(scratch, "one")
    entries = [(stem + "/" + name, max_path)]
    entries += [(stem + "/" + arc, full) for arc, full in maps_of(max_path, archive.ASSET_EXTENSIONS)]
    zip_path = make_zip(os.path.join(folder, stem + ".zip"), entries)
    images = import_one(zip_path, "%s in a .zip (%d map files)" % (name, len(entries) - 1), max_name=name,
                        pack_name=os.path.basename(zip_path))
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
    import_one(zip_path, "two scenes in a .zip, %s named" % SECOND, max_name=SECOND, pack_name="two.zip",
               pack_scene=SECOND)
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
    text = bpy.data.texts.get(TEXT_NAME)
    body = text.as_string() if text is not None else ""
    check("a .max and a one-scene .zip chosen together: the text holds both reports, in import order",
          body.startswith("MaxDrop import report: %s\n" % name) and body.count("MaxDrop import report: ") == 2
          and ("\n\nMaxDrop import report: %s\nScene pack: one.zip\n" % SECOND) in body, body[:200])

    result, message = attempt(directory=folder, files=[{"name": "two.zip"}, {"name": "one.zip"}])
    check("a two-scene .zip chosen with another pack: cancelled, import it alone",
          result == {'CANCELLED'} and "import that pack alone" in message, message.strip())
    check("a two-scene .zip chosen with another pack: nothing of it unpacked",
          not os.path.exists(os.path.join(folder, "two")))

    make_zip(os.path.join(folder, "first.zip"), [("x/" + SECOND, max_path)])
    damage(make_zip(os.path.join(folder, "broken.zip"), [("y/" + name, max_path)]))
    result, message = attempt(directory=folder, files=[{"name": "first.zip"}, {"name": "broken.zip"}])
    check("a good pack, then a damaged one: cancelled, nothing imported, the unpacked pack named",
          result == {'CANCELLED'} and "Nothing was imported" in message and "first.zip into " in message
          and not bpy.data.objects, "%s, %d objects %s" % (result, len(bpy.data.objects), message.strip()))
    check("a good pack, then a damaged one: the good pack stays unpacked, the damaged one leaves nothing",
          os.path.isfile(os.path.join(folder, "first", SECOND)) and not os.path.exists(os.path.join(folder, "broken")))

    result, message = attempt(directory=folder, files=[{"name": "fake.zip"}])
    check("a file named .zip that is not an archive: cancelled with a message",
          result == {'CANCELLED'} and "is not a .zip, .rar or .7z archive" in message, message.strip())


def box_size():
    """The world bounding box size of the only mesh object after an import of units_*.max."""
    ob = next(ob for ob in bpy.data.objects if ob.type == 'MESH')
    world = [ob.matrix_world @ v.co for v in ob.data.vertices]
    return [max(p[k] for p in world) - min(p[k] for p in world) for k in range(3)]


def close(a, b, tolerance=1e-6):
    return all(abs(x - y) <= tolerance * max(1.0, abs(y)) for x, y in zip(a, b))


class FakeLayout:
    """Records the labels a draw function puts into a panel (no window in the background)."""

    def __init__(self):
        self.labels = []

    def panel(self, idname, default_closed=False):
        return self, self

    def label(self, text="", icon='NONE'):
        self.labels.append(text)


class FakeOperator:
    def __init__(self, path):
        self.files, self.directory, self.filepath = [], "", path


def preflight_panel(ops, path):
    """The File panel of the popup: invoke() remembers the line of a dropped .max, draw shows it."""
    ops._PREFLIGHT.clear()
    layout = FakeLayout()
    ops.import_files(layout, FakeOperator(path))
    check("File panel: nothing before invoke() read the file", layout.labels == [], str(layout.labels))
    ops._remember_preflight(path)
    ops.import_files(layout, FakeOperator(path))
    check("File panel: the file name, then its pre-flight line",
          layout.labels == ["File", os.path.basename(path), ops._preflight(path)], str(layout.labels))


def units_and_preflight(ops):
    fixtures_dir = os.path.join(ROOT, "tests", "fixtures")
    box = (10.0, 20.0, 30.0)
    sizes = {}
    for name, meters in (("units_mm", 0.001), ("units_cm", 0.01), ("units_in", 0.0254)):
        path = os.path.join(fixtures_dir, name + ".max")
        import_one(path, "%s, Units Auto" % name)
        got = box_size()
        check("%s, Units Auto: the box measures 10 x 20 x 30 of its unit" % name,
              close(got, [v * meters for v in box]), str(got))
        import_one(path, "%s, Units Millimeters" % name, units='MILLIMETERS')
        sizes[name] = box_size()
    check("units_mm, units_cm, units_in with Units Millimeters: the same box size in meters",
          close(sizes["units_cm"], sizes["units_mm"]) and close(sizes["units_in"], sizes["units_mm"])
          and close(sizes["units_mm"], [v * 0.001 for v in box]), str(sizes))
    import_one(os.path.join(fixtures_dir, "units_cm.max"), "units_cm, Units Auto, Scale 2", scale_objects=2.0)
    got = box_size()
    check("units_cm, Scale 2: twice the size", close(got, [v * 0.02 for v in box]), str(got))
    import_one(os.path.join(fixtures_dir, "units_mm.max"), "units_mm, Up Y, Forward -Z", axis_up='Y',
               axis_forward='-Z')
    got = box_size()
    check("units_mm, Up Y: the top-level object is turned, Y up becomes Z up",
          close(got, [0.01, 0.03, 0.02]), str(got))
    meters, note = ops._meters('AUTO', None, 0.5)
    check("a file without a unit: Scale is the meters per unit, with a note", meters == 0.5 and "0.5" in note, note)
    check("Units Feet ignores the file's unit", ops._meters('FEET', None, 1.0) == (0.3048, ""))
    line = ops._preflight(os.path.join(fixtures_dir, "hierarchy.max"))
    check("pre-flight line: 3ds Max version, object count, unit",
          line.startswith("3ds Max 2020, ") and ", 5 objects, millimeters" in line, line)
    line = ops._preflight(os.path.join(fixtures_dir, "units_in.max"))
    check("pre-flight line of units_in: 1 object, inches", line.endswith(", 1 object, inches"), line)
    preflight_panel(ops, os.path.join(fixtures_dir, "hierarchy.max"))
    with open(os.path.join(tempfile.gettempdir(), "maxdrop-not-a-max.max"), "wb") as f:
        f.write(b"not a 3ds Max file")
        bad = f.name
    try:
        line = ops._preflight(bad)
    finally:
        os.remove(bad)
    check("pre-flight line of a file that is not a .max: says so", line.startswith("Not readable as a .max file"),
          line)


def filters_and_failures(scratch):
    fixtures_dir = os.path.join(ROOT, "tests", "fixtures")
    path = os.path.join(fixtures_dir, "multi_uv.max")
    attempt(filepath=path, object_filter={'MATERIAL'})
    meshes = [ob.data for ob in bpy.data.objects if ob.type == 'MESH']
    check("Object Filter without UV Maps: meshes without UV layers, with materials",
          meshes and not any(m.uv_layers for m in meshes) and all(m.materials for m in meshes))
    attempt(filepath=path, object_filter={'UV'})
    meshes = [ob.data for ob in bpy.data.objects if ob.type == 'MESH']
    check("Object Filter without Material: meshes with UV layers, without material slots",
          meshes and all(m.uv_layers for m in meshes) and not any(m.materials for m in meshes))
    folder = os.path.join(scratch, "failures")
    os.makedirs(folder)
    shutil.copy(path, os.path.join(folder, "good.max"))
    with open(os.path.join(folder, "junk.max"), "wb") as f:
        f.write(b"not a 3ds Max file" * 200)
    result, message = attempt(directory=folder, files=[{"name": "good.max"}, {"name": "junk.max"}])
    check("a good .max and a file that is not one: the good one imported", result == {'FINISHED'}
          and "good" in bpy.data.collections and any(ob.type == 'MESH' for ob in bpy.data.objects),
          "%s %s" % (result, message.strip()))
    check("a good .max and a file that is not one: no collection of the bad one", "junk" not in bpy.data.collections)
    result, message = attempt(directory=folder, files=[{"name": "junk.max"}])
    check("only a file that is not a .max: cancelled, named in the message",
          result == {'CANCELLED'} and "Nothing imported" in message and "junk.max" in message, message.strip())


def run():
    files = fixtures()
    if not files:
        return False
    sys.path.insert(0, ROOT)
    import maxdrop
    maxdrop.register()
    ops = sys.modules[maxdrop.__name__ + ".ops"]
    import_scene = record_reports(ops.IMPORT_SCENE_OT_maxdrop)
    scratch = tempfile.mkdtemp(prefix="maxdrop-smoke-")
    try:
        from maxdrop.intake import archive
        for n, path in enumerate(files):
            check("%s exists" % path, os.path.isfile(path))
            if not os.path.isfile(path):
                continue
            if path.lower().endswith(ARCHIVES):
                import_one(path, pack_name=os.path.basename(path))
                continue
            images = import_one(path)
            work = os.path.join(scratch, str(n))
            as_pack(path, work, images, archive)
            two_scenes(path, work)
            selections(path, work)
        if not argv:
            units_and_preflight(ops)
            filters_and_failures(scratch)
    finally:
        ops.IMPORT_SCENE_OT_maxdrop._import_scene = import_scene
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
