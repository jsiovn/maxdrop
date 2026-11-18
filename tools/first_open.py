# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""First open of a scene: import it as a user would, look through its camera, answer the gate's questions.

    python tools/first_open.py --blender <blender.exe> --profile <scratch dir> --label "scene A" --tag 52
                               --out <folder> [--size 640] [--pack-scene <name.max>] [--limit-minutes 30]
                               <file.max | pack>

Blender runs headless with --factory-startup and its own profile (--profile becomes BLENDER_USER_RESOURCES) and
runs this file inside it: the dev package of this checkout imports the file with the operator's default options
(Units: Auto), the scene is rendered through scene.camera with EEVEE (the world dark, so only the imported lights
light it; Standard view transform, so a missing texture's magenta stays magenta) at --size pixels along the long
side, once as imported and once with the imported lights switched off, and the result is written as
<out>/<label>-<tag>.json beside the images (.png, -lights-off.png) and Blender's console log (.log). --tag tells
runs of several Blender versions apart: a run replaces the files of the same label and tag. The answers, yes or no:

    traceback   Blender finished and its log holds no Python traceback
    magenta     at most MAGENTA_MAX of the pixels are magenta (a texture that did not load)
    lit         the mean luminance of the image is at least LIT_MEAN_MIN, and at least LIGHTS_SHARE_MIN of it goes
                when the imported lights are switched off (the lights work, not only emissive materials)
    closed      rays from the camera through each quadrant of its frame hit geometry, at least CLOSED_MIN of them
    scale       floor to ceiling in front of the camera (vertical rays) is within HEIGHT meters
    report      the report accounts for every node, light, camera and modifier class of the file read again, and
                every texture was found and loaded (accounting())

The JSON holds counts, class names and issue kinds (names, file names and numbers removed: issue_kind()) only; read
it before quoting it anywhere public, as a name the rules miss can slip through. The images and the log show and
name the scene: keep all of them outside the repository for scenes that are not yours. Exit 0 when every answer is
yes. Unlike tools/baseline.py there is no memory watch, only the time limit. Standard library only outside Blender.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAGENTA_MAX = 0.001       # share of the pixels
LIT_MEAN_MIN = 0.02       # mean Rec. 709 luminance of the display image, 0..1
CLOSED_MIN = 0.9          # share of the rays of each quadrant that hit geometry
HEIGHT = (2.2, 4.5)       # meters, floor to ceiling
GRID = 16                 # rays per quadrant side
RAY_LENGTH = 1000.0       # meters
LIT = 0.1                 # luminance of a pixel counted as lit
LIGHTS_SHARE_MIN = 0.5    # of the mean luminance that goes when the imported lights are switched off
NOT_LOADED = "texture not loaded"  # build.materials' issue of a texture file found that does not load
# The first parts of issue reasons that name a topic, not an object (convert.scene, convert.texmaps, ops).
TOPICS = {"light", "camera", "render", "modifiers", "transform", "primitive", "node", "geometry", "shape", "extrude",
          "uvw map", "layer", "Keep Targets", NOT_LOADED, "map N"}
_QUOTED = re.compile(r"(?<!\w)'[^']*'|\"[^\"]*\"")  # not the apostrophe of "sun's"
_FILE = re.compile(r"\S*[\\/]\S*|[\w.-]+\.(?:ies|jpe?g|png|tga|tiff?|exr|hdr|bmp|psd|gif|dds|max|vrmesh)\b",
                   re.IGNORECASE)
_NUMBER = re.compile(r"(?<![A-Za-z_\d])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def image_stats(pixels, width, height):
    """Mean luminance, the share of lit pixels and the share of magenta ones of a flat RGBA list (display values)."""
    count = width * height
    if len(pixels) != count * 4 or count == 0:
        raise ValueError("%d values for a %d x %d RGBA image" % (len(pixels), width, height))
    total = lit = magenta = 0
    for k in range(0, len(pixels), 4):
        r, g, b = pixels[k], pixels[k + 1], pixels[k + 2]
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        total += y
        lit += y >= LIT
        low, high = min(r, b), max(r, b)
        magenta += high >= 0.15 and low >= 0.6 * high and g <= 0.25 * low
    return {"mean_luminance": round(total / count, 4), "lit_share": round(lit / count, 4),
            "magenta_share": round(magenta / count, 5)}


def issue_kind(reason):
    """An issue reason without the names, file names and numbers it quotes: what kind of thing was not converted.
    Its first part stays only when it is a known topic or names its object in quotes (a map's "VRayBitmap 'x'");
    otherwise it may be a bare material name ("<name>: no sub-material")."""
    parts = _NUMBER.sub("N", _FILE.sub("<file>", _QUOTED.sub("<name>", reason))).split(": ")
    if len(parts) > 1 and parts[0] not in TOPICS and "<name>" not in parts[0]:
        parts[0] = "<name>"
    keep = 3 if len(parts) > 2 and parts[1] == "not built" else 2
    return ": ".join(parts[:keep]).strip()


def verdict(result):
    """{gate question: yes / no} and "passed" from a result of inside()."""
    image, rays, height = result.get("image"), result.get("rays"), result.get("room_height_m")
    answers = {
        "traceback": not result.get("traceback") and result.get("exit_code") == 0,
        "magenta": image is not None and image["magenta_share"] <= MAGENTA_MAX,
        "lit": image is not None and image["mean_luminance"] >= LIT_MEAN_MIN
        and image.get("lights_off_mean_luminance") is not None
        and image["mean_luminance"] - image["lights_off_mean_luminance"] >= LIGHTS_SHARE_MIN * image["mean_luminance"],
        "closed": bool(result.get("scene_camera")) and rays is not None
        and all(share >= CLOSED_MIN for share in rays["quadrants"]),
        "scale": height is not None and HEIGHT[0] <= height <= HEIGHT[1],
        "report": bool(result.get("accounting")) and all(result["accounting"].values()),
    }
    answers["passed"] = all(answers.values())
    return answers


def read_log(path):
    """Whether Blender's console log holds a Python traceback."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return any(line.startswith("Traceback (most recent call last)") for line in f)
    except OSError:
        return False


def safe_label(label):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "scene"


def inside(root, path, png, size, pack_scene=""):
    import bpy
    from mathutils import Vector

    sys.path.insert(0, os.path.abspath(root))
    import maxdrop
    maxdrop.register()
    from maxdrop.build import report as build_report
    from maxdrop.reader import cfb, classids
    from maxdrop.reader import scene as reader_scene
    from maxdrop.reader.chunks import ChunkError

    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.collections, bpy.data.lights,
                  bpy.data.cameras):
        for item in list(block):
            block.remove(item)

    reports = []
    publish = build_report.publish

    def keep(rep):
        reports.append(rep)
        return publish(rep)
    build_report.publish = keep
    start = time.perf_counter()
    try:
        result = bpy.ops.import_scene.maxdrop(filepath=path, **({"pack_scene": pack_scene} if pack_scene else {}))
    finally:
        build_report.publish = publish
    seconds = time.perf_counter() - start
    scene = bpy.context.scene
    found = {"blender": bpy.app.version_string, "result": sorted(result), "import_seconds": round(seconds, 1)}
    if not reports:
        found["error"] = "nothing imported"
        return found
    rep = reports[-1]
    objects = list(bpy.data.objects)
    types = {}
    for ob in objects:
        types[ob.type] = types.get(ob.type, 0) + 1
    missing_files = sum(1 for img in bpy.data.images if img.source == 'FILE' and not img.packed_file
                        and not os.path.isfile(bpy.path.abspath(img.filepath)))
    found["counts"] = {"objects": len(objects), "by_type": dict(sorted(types.items())),
                       "materials": len(bpy.data.materials), "images": len(bpy.data.images),
                       "image_files_missing": missing_files}
    kinds = {}
    for _label, reason in rep.issues + rep.geometry_errors + rep.material_issues:
        kind = issue_kind(reason)
        kinds[kind] = kinds.get(kind, 0) + 1
    found["report"] = {
        "unit": rep.unit, "meters_per_unit": rep.meters, "nodes": rep.nodes, "objects_built": rep.objects_built,
        "meshes": rep.meshes_built, "curves": rep.curves_built, "lights": rep.lights_built,
        "cameras": rep.cameras_built, "render_size": rep.render_size, "scene_camera": rep.scene_camera is not None,
        "materials_built": rep.materials_built, "materials_by_class": dict(rep.materials),
        "placeholders": dict(rep.placeholders), "modifiers_applied": dict(rep.modifiers_applied),
        "modifiers_converted": dict(rep.modifiers_converted), "modifiers_ignored": dict(rep.modifiers),
        "wrappers_peeled": dict(rep.wrappers), "maps_peeled": dict(rep.maps_peeled),
        "maps_unsupported": dict(rep.maps_unsupported), "grey_materials": dict(rep.grey_materials),
        "sockets_skipped": dict(rep.sockets_skipped), "textures_found": sum(n for _r, n in rep.textures_found),
        "textures_missing": len(rep.textures_missing), "unknown_controllers": dict(rep.unknown_controllers),
        "dropped_uv_layers": rep.dropped_uv_layers, "approximated": rep.approximated, "left_out": rep.left_out,
        "issue_kinds": dict(sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
    pack = getattr(rep, "pack", None)  # a pack's .max is the one the operator unpacked
    source = pack.max_path if pack is not None and getattr(pack, "max_path", None) else path
    census = file_census(source, cfb, classids, reader_scene, ChunkError)
    found["accounting"], counters = accounting(rep, census, types, missing_files)
    found["file"] = dict(census, **counters)

    camera = scene.camera
    found["scene_camera"] = camera is not None
    found["rays"] = found["room_height_m"] = found["image"] = None
    if camera is not None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        found["rays"] = _quadrant_rays(scene, depsgraph, camera, Vector)
        found["room_height_m"] = _room_height(scene, depsgraph, camera, Vector)
        found["image"] = _render(bpy, scene, png, size)
    return found


def file_census(path, cfb, classids, reader_scene, chunk_error):
    """What the file holds, read again with MaxDrop's reader (plain Python): its nodes, the nodes whose base object
    is a light or a camera (by superclass) and their classes, and per modifier class the nodes whose stack holds it.
    A node whose record or stack cannot be read counts as a node only: the import names it as a node issue."""
    census = {"nodes": 0, "light_nodes": 0, "camera_nodes": 0, "light_classes": [], "camera_classes": [],
              "modifier_nodes_by_class": {}}
    light_classes, camera_classes, modifier_nodes = set(), set(), census["modifier_nodes_by_class"]
    with cfb.CompoundFile(path) as cf:
        sc = reader_scene.Scene.from_file(cf)
        order = sc.walk()
        census["nodes"] = len(order)
        for i in order:
            try:
                node = sc.node(i)
                stack = sc.object_stack(node.object) if node.object is not None else None
            except chunk_error:
                continue
            if stack is None:
                continue
            entry = sc.entry(stack.base) if stack.base is not None else None
            if entry is not None and entry.superclass == classids.SC_LIGHT:
                census["light_nodes"] += 1
                light_classes.add(entry.name)
            elif entry is not None and entry.superclass == classids.SC_CAMERA:
                census["camera_nodes"] += 1
                camera_classes.add(entry.name)
            for name in {(sc.entry(m).name if sc.entry(m) is not None else "") for m in stack.modifiers}:
                modifier_nodes[name] = modifier_nodes.get(name, 0) + 1
    census["light_classes"], census["camera_classes"] = sorted(light_classes), sorted(camera_classes)
    return census


def accounting(rep, census, types, missing_files):
    """Whether the report (a convert.report.Report) accounts for what census says the file holds. types: {Blender
    object type: count} of the import; missing_files: loaded images whose file is not on disk. Each light or camera
    node must be a Blender light or camera, a placeholder of its class or a "not built" issue; each modifier class of
    a node counted as applied, converted or not applied (a node may count once under each); every texture found and
    loaded. ({check: yes / no}, {counter: value})."""
    not_built = {"light": 0, "camera": 0}
    for _label, reason in rep.issues:
        for what in not_built:
            if reason.startswith(what + ": not built"):
                not_built[what] += 1
    placed = {what: sum(rep.placeholders.get(c, 0) for c in census[what + "_classes"]) for what in not_built}
    counted = {name: rep.modifiers_applied.get(name, 0) + rep.modifiers_converted.get(name, 0)
               + rep.modifiers.get(name, 0) for name in census["modifier_nodes_by_class"]}
    not_loaded = sum(1 for _label, reason in rep.material_issues if reason.startswith(NOT_LOADED))
    counters = {"light_placeholders": placed["light"], "lights_not_built": not_built["light"],
                "camera_placeholders": placed["camera"], "cameras_not_built": not_built["camera"],
                "textures_not_found": len(rep.textures_missing), "textures_not_loaded": not_loaded}
    checks = {
        "nodes": census["nodes"] == rep.nodes == rep.objects_built,
        "lights": census["light_nodes"] == types.get("LIGHT", 0) + placed["light"] + not_built["light"],
        "cameras": census["camera_nodes"] == types.get("CAMERA", 0) + placed["camera"] + not_built["camera"],
        "modifiers": all(counted[name] >= n for name, n in census["modifier_nodes_by_class"].items()),
        "textures": not rep.textures_missing and not not_loaded and missing_files == 0,
    }
    return checks, counters


def _cast(scene, depsgraph, origin, direction, length=RAY_LENGTH):
    hit, location, _normal, _index, _ob, _matrix = scene.ray_cast(depsgraph, origin, direction, distance=length)
    return (location - origin).length if hit else None


def _quadrant_rays(scene, depsgraph, camera, Vector):
    """The share of rays that hit geometry in each quadrant of the camera's frame (top left, top right, bottom
    left, bottom right), GRID x GRID rays each, starting at the camera's clip start."""
    data, matrix = camera.data, camera.matrix_world
    top_right, _bottom_right, bottom_left, top_left = data.view_frame(scene=scene)
    axis = (matrix.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    shares = []
    for qv in (0, 1):
        for qu in (0, 1):
            hits = 0
            for a in range(GRID):
                for b in range(GRID):
                    u = (qu * GRID + a + 0.5) / (2 * GRID)
                    v = (qv * GRID + b + 0.5) / (2 * GRID)
                    p = top_left + (top_right - top_left) * u + (bottom_left - top_left) * v
                    if data.type == 'ORTHO':
                        origin, direction = matrix @ Vector((p.x, p.y, 0.0)), axis
                    else:
                        origin = matrix.translation
                        direction = ((matrix @ p) - origin).normalized()
                    start = origin + direction * data.clip_start
                    hits += _cast(scene, depsgraph, start, direction) is not None
            shares.append(round(hits / (GRID * GRID), 3))
    return {"quadrants": shares}


def _room_height(scene, depsgraph, camera, Vector):
    """Floor to ceiling in front of the camera: the median of up + down hit distances of vertical columns at the
    camera and 0.5, 1 and 2 m past its clip start along its horizontal view direction (a camera often stands behind
    a wall and clips it away), each also 0.5 m to the left and right; None when no column hits both."""
    up, down = Vector((0.0, 0.0, 1.0)), Vector((0.0, 0.0, -1.0))
    matrix = camera.matrix_world
    forward = matrix.to_3x3() @ Vector((0.0, 0.0, -1.0))
    forward.z = 0.0
    forward = forward.normalized() if forward.length > 1e-6 else Vector((0.0, 1.0, 0.0))
    side = Vector((forward.y, -forward.x, 0.0))
    clip = camera.data.clip_start
    heights = []
    for distance in (0.0, clip + 0.5, clip + 1.0, clip + 2.0):
        for offset in (0.0, 0.5, -0.5):
            origin = matrix.translation + forward * distance + side * offset
            a, b = _cast(scene, depsgraph, origin, up), _cast(scene, depsgraph, origin, down)
            if a is not None and b is not None:
                heights.append(a + b)
    if not heights:
        return None
    heights.sort()
    return round(heights[len(heights) // 2], 3)


def _render(bpy, scene, png, size):
    engines = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    scene.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in engines else 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 16
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    world = scene.world
    if world is not None:
        world.color = (0.0, 0.0, 0.0)
        tree = world.node_tree if getattr(world, "use_nodes", True) else None
        for node in (tree.nodes if tree else ()):
            if node.type == 'BACKGROUND':
                node.inputs["Strength"].default_value = 0.0
    r = scene.render
    long_side = max(r.resolution_x, r.resolution_y)
    r.resolution_percentage = max(1, min(100, round(100 * size / long_side)))
    r.film_transparent = False
    r.image_settings.file_format = 'PNG'
    r.image_settings.color_mode = 'RGBA'
    start = time.perf_counter()
    stats = _render_still(bpy, scene, png)
    stats.update(render_seconds=round(time.perf_counter() - start, 1), engine=r.engine)
    # Again without the imported lights: an emissive material alone must not pass for working lights.
    lights = [ob for ob in scene.objects if ob.type == 'LIGHT' and not ob.hide_render]
    stats["lights_off_mean_luminance"] = None
    if lights:
        for ob in lights:
            ob.hide_render = True
        off = os.path.splitext(png)[0] + "-lights-off.png"
        stats["lights_off_mean_luminance"] = _render_still(bpy, scene, off)["mean_luminance"]
        for ob in lights:
            ob.hide_render = False
    return stats


def _render_still(bpy, scene, png):
    scene.render.filepath = png
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(png, check_existing=False)
    width, height = img.size
    pixels = [0.0] * (width * height * 4)
    img.pixels.foreach_get(pixels)
    stats = image_stats(pixels, width, height)
    stats.update(width=width, height=height)
    bpy.data.images.remove(img)
    return stats


def run(args):
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    os.makedirs(args.profile, exist_ok=True)
    stem = os.path.join(out, safe_label(args.label) + "-" + safe_label(args.tag))
    result_json, log, png, inner = stem + ".json", stem + ".log", stem + ".png", stem + ".inner.json"
    for name in (result_json, log, png, stem + "-lights-off.png", inner):
        if os.path.exists(name):
            os.remove(name)
    env = dict(os.environ, BLENDER_USER_RESOURCES=os.path.abspath(args.profile), PYTHONIOENCODING="utf-8")
    command = [args.blender, "--background", "--factory-startup", "--python-exit-code", "1",
               "--python", os.path.abspath(__file__), "--", "inside", ROOT, os.path.abspath(args.file), inner, png,
               str(args.size), args.pack_scene]
    start = time.monotonic()
    outcome = "finished"
    with open(log, "wb") as sink:
        process = subprocess.Popen(command, stdout=sink, stderr=subprocess.STDOUT, env=env)
        try:
            process.wait(timeout=args.limit_minutes * 60)
        except subprocess.TimeoutExpired:
            process.kill()  # this process only: other Blender sessions on the machine are not ours
            process.wait()
            outcome = "stopped: time limit"
    found = {"label": args.label, "outcome": outcome, "exit_code": process.returncode,
             "wall_seconds": round(time.monotonic() - start, 1)}
    if os.path.isfile(inner):
        with open(inner, encoding="utf-8") as f:
            found.update(json.load(f))
        os.remove(inner)
    found["traceback"] = read_log(log)
    found["verdict"] = verdict(found)
    with open(result_json, "w", encoding="utf-8") as f:
        json.dump(found, f, indent=1)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", help="the .max file or scene pack to import")
    parser.add_argument("--blender", required=True, help="path of the Blender executable")
    parser.add_argument("--profile", required=True, help="scratch folder for Blender's profile")
    parser.add_argument("--label", default="scene", help="how the result names the file")
    parser.add_argument("--tag", required=True, help="the Blender version in the result's file names, e.g. 52")
    parser.add_argument("--out", required=True, help="folder for the JSON, the image and the log")
    parser.add_argument("--size", type=int, default=640, help="pixels along the long side of the image")
    parser.add_argument("--pack-scene", default="", help="the .max to import from a pack that holds several")
    parser.add_argument("--limit-minutes", type=float, default=30.0)
    args = parser.parse_args(argv)
    found = run(args)
    print(json.dumps(found, indent=1))
    return 0 if found["verdict"]["passed"] else 1


def _inside_main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    _mode, root, path, out_json, png, size, pack_scene = argv[:7]
    found = inside(root, path, png, int(size), pack_scene)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(found, f, indent=1)
    print("FIRST OPEN DONE")
    sys.stdout.flush()


if __name__ == "__main__":
    if "--" in sys.argv and sys.argv[sys.argv.index("--") + 1:][:1] == ["inside"]:
        _inside_main()
    else:
        sys.exit(main())
