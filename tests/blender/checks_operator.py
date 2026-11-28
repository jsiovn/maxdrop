# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of the operator's runs: a failed build cleaned up, cancels, guards, the read in a worker, mesh
steps, worker errors, a cancelled unpack."""
import os
import shutil
import tempfile

import bpy

from .core import check, empty_scene
from .nodes import _advance, _cancel_run, _state


def check_failed_build_cleanup(max_path):
    """A build that fails after its materials were made: the operator removes the materials and images it made and
    leaves a material and an image that were there before."""
    from maxdrop.build import objects as build_objects
    keep_material = bpy.data.materials.new("UserMaterial")
    keep_image = bpy.data.images.new("UserImage", 2, 2)
    before = ({m.as_pointer() for m in bpy.data.materials}, {i.as_pointer() for i in bpy.data.images})
    original, made = build_objects.build_steps, []

    def failing(*args, **kwargs):
        built = yield from original(*args, **kwargs)
        made.append((len(built.materials), len(bpy.data.images)))
        raise RuntimeError("maxdrop test: build fails")

    build_objects.build_steps = failing
    try:
        try:
            bpy.ops.import_scene.maxdrop(filepath=max_path)
            raised = False
        except RuntimeError:
            raised = True
    finally:
        build_objects.build_steps = original
    after = ({m.as_pointer() for m in bpy.data.materials}, {i.as_pointer() for i in bpy.data.images})
    check("failed build: materials and images were made before it failed",
          raised and made and made[0][0] > 0 and made[0][1] > len(before[1]), str(made))
    check("failed build: the materials and images it made are removed, the user's stay",
          after == before and keep_material.name in bpy.data.materials and keep_image.name in bpy.data.images
          and not bpy.data.objects, "%d / %d materials, %d / %d images" % (
              len(after[0]), len(before[0]), len(after[1]), len(before[1])))
    bpy.data.materials.remove(keep_material)
    bpy.data.images.remove(keep_image)


def check_cancel(textured, other):
    """The modal import's step generator (pipeline._Run.steps), driven without a window: closed early (Esc) it leaves
    the datablocks, the scene camera, the render size and view exposure as they were, the user's own material and
    image too. textured: a .max whose textures are found (materials and images are made); other: a .max with a camera
    (it sets the scene camera and render size)."""
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    keep_material = bpy.data.materials.new("UserMaterial")
    keep_image = bpy.data.images.new("UserImage", 2, 2)
    before = _state()
    images = len(bpy.data.images)

    run = _cancel_run([textured])
    steps = run.steps()
    held = _advance(steps, lambda: len(bpy.data.images) > images)
    made = len(bpy.data.objects), len(bpy.data.materials), len(bpy.data.images)
    steps.close()
    check("cancel: one file closed during its build, after materials and images were made", held, str(made))
    check("cancel: one file: every datablock it made is removed, the user's stay", _state() == before,
          "%s | %s" % (_state(), before))

    run = _cancel_run([other, textured])
    steps = run.steps()
    held = _advance(steps, lambda: len(run._made) == 1 and len(bpy.data.images) > images)
    camera = bpy.context.scene.camera
    camera = camera is not None and camera.type == 'CAMERA'
    steps.close()
    check("cancel: two files closed in the second one's build, the first one finished with its camera",
          held and camera)
    check("cancel: two files: both removed, the report text too, the scene camera and render size put back",
          _state() == before, "%s | %s" % (_state(), before))

    import time
    from maxdrop import pipeline
    real_read, saw = pipeline._read_scene, []

    def held_read(max_path, opts, dirs, cancel=None):
        # the worker stays in the read until close() stops it: a small file read to its end before the first step
        # would start the build, and that step would not be _WAIT
        deadline = time.perf_counter() + 30.0
        while not (cancel is not None and cancel()) and time.perf_counter() < deadline:
            time.sleep(0.005)
        saw.append(cancel is not None and cancel())
        return real_read(max_path, opts, dirs, cancel)

    run = _cancel_run([textured])
    pipeline._read_scene = held_read  # _scene_steps looks it up when the read starts
    try:
        steps = run.steps(threaded=True)
        waited = next(steps) is pipeline._WAIT
        steps.close()
    finally:
        pipeline._read_scene = real_read
        for worker in list(pipeline._WORKERS):  # close() waits only _READ_WAIT: here until the read has ended
            worker.join(60)
    check("cancel: threaded, closed while the worker reads: nothing made",
          waited and saw == [True] and pipeline._busy() == "" and _state() == before,
          "waited %s, stop seen %s, busy %r" % (waited, saw, pipeline._busy()))
    run = _cancel_run([other, textured])
    steps = run.steps(threaded=True)
    held = _advance(steps, lambda: len(run._made) == 1 and len(bpy.data.objects) > len(before[0]["objects"]) + 1)
    steps.close()
    check("cancel: threaded, two files closed in the second one's build: nothing left",
          held and _state() == before, "%s | %s" % (_state(), before))

    run = _cancel_run([other, textured])
    steps = run.steps(threaded=True)
    ended = not _advance(steps, lambda: False)
    report = bpy.data.texts.get("MaxDrop Report")
    check("cancel: threaded, run to its end: both files imported, the run's report written",
          ended and len(run._made) == 2 and bpy.context.scene.camera is not None and report is not None
          and report.as_string().count("MaxDrop import report: ") == 2,
          "%s %d %s" % (ended, len(run._made), report and report.as_string()[:200]))
    run.undo()
    check("cancel: undo() after a finished run removes it", _state() == before, "%s | %s" % (_state(), before))

    run = _cancel_run([os.path.join(os.path.dirname(other), "shapes_more.max")])  # its sections: hidden objects
    steps = run.steps()
    ended = not _advance(steps, lambda: False)
    sections = sum(1 for ob in bpy.data.objects if ob.get("maxdrop_helper") == "section")
    run.undo()
    check("cancel: undo() removes the rectangular sections' objects and curves too",
          ended and sections == 2 and _state() == before, "%d sections | %s | %s" % (sections, _state(), before))
    bpy.data.materials.remove(keep_material)
    bpy.data.images.remove(keep_image)


def check_run_guards(textured):
    """The modal runner's safety nets without a window: an undo or file load elsewhere closes the active run
    (ops._stop_active), the runner's teardown never leaves a run active even when the window manager raises, the
    windowed import keeps its settings as the last-used ones (ops._store_last), and a cancelled read still running
    keeps the next import waiting (pipeline._busy)."""
    import threading
    import types
    from maxdrop import ops, pipeline
    empty_scene()
    before = _state()
    run = _cancel_run([textured])
    steps = run.steps()
    run.close = steps.close
    held = _advance(steps, lambda: len(bpy.data.objects) > 0)
    pipeline._ACTIVE.append(run)
    ops._guard(True)
    try:
        guarded = all(ops._stop_active in getattr(bpy.app.handlers, n) for n in ops._GUARDED)
        ops._stop_active()
        check("guards: an undo or file load elsewhere closes the active run, nothing left",
              held and guarded and run.stopped and _state() == before, "%s | %s" % (_state(), before))

        def raising(*_args):
            raise RuntimeError("maxdrop test: window manager fails")

        wm = types.SimpleNamespace(event_timer_remove=raising, progress_end=raising)
        context = types.SimpleNamespace(window_manager=wm, workspace=types.SimpleNamespace(status_text_set=raising))
        runner = types.SimpleNamespace(_run=run, _timer=object())
        ops.MAXDROP_OT_import_progress._teardown(runner, context)
        check("guards: teardown with a failing window manager: no run active, the handlers removed",
              not pipeline._ACTIVE and not any(ops._stop_active in getattr(bpy.app.handlers, n) for n in ops._GUARDED)
              and runner._timer is None and not pipeline._busy())
    finally:
        pipeline._ACTIVE.clear()
        ops._guard(False)

    source = types.SimpleNamespace(units='CENTIMETERS', scale_objects=2.0, light_strength=2.5, keep_targets=True,
                                   modifiers='IGNORE', object_filter={'UV'}, pack_scene="not kept")
    ops._store_last(source, bpy.context.window_manager)
    last = bpy.context.window_manager.operator_properties_last("import_scene.maxdrop")
    check("guards: the windowed import's settings kept as the last-used ones (Scene is not)",
          last.units == 'CENTIMETERS' and abs(last.scale_objects - 2.0) < 1e-6 and abs(last.light_strength - 2.5) < 1e-6
          and last.keep_targets and last.modifiers == 'IGNORE' and set(last.object_filter) == {'UV'}
          and last.pack_scene == "",
          "%s %s %s %s %s %s %r" % (last.units, last.scale_objects, last.light_strength, last.keep_targets,
                                    last.modifiers, set(last.object_filter), last.pack_scene))
    for name in ("units", "scale_objects", "light_strength", "keep_targets", "modifiers", "object_filter"):
        last.property_unset(name)

    release = threading.Event()
    steps = pipeline._in_thread(release.wait, 30)
    waited = next(steps) is pipeline._WAIT
    steps.close()
    busy = pipeline._busy()
    release.set()
    for worker in list(pipeline._WORKERS):
        worker.join(10)
    check("guards: a cancelled read still running keeps the next import waiting, until it ends",
          waited and "still reading" in busy and pipeline._busy() == "", busy)


def check_read_cancel(path):
    """Esc while a threaded run reads: the reading stops at the next node (convert.scene.describe's cancel check), so
    close() ends the worker and the next import is not refused (pipeline._busy). The read is slowed per node."""
    import time
    from maxdrop import pipeline
    from maxdrop.convert import scene as convert_scene
    empty_scene()
    before = _state()
    original, calls = convert_scene.blender_matrix, []

    def slow(*args, **kwargs):
        calls.append(None)
        time.sleep(0.2)  # twice per node: the read of every node takes 0.4 s
        return original(*args, **kwargs)

    convert_scene.walk.blender_matrix = slow
    try:
        run = _cancel_run([path])
        steps = run.steps(threaded=True)
        held = _advance(steps, lambda: len(calls) > 0)
        start = time.perf_counter()
        steps.close()
        closed = time.perf_counter() - start
        while pipeline._busy() and time.perf_counter() - start < 1.0:
            time.sleep(0.01)
        free = pipeline._busy() == ""
        seen = len(calls)
        time.sleep(0.5)
        check("read cancel: closed while the worker reads, it stops at the next node: close() within 1 s, the next "
              "import not refused within 1 s, nothing made",
              held and closed < 1.0 and free and len(calls) == seen and _state() == before,
              "close %.2f s, busy %r, %d -> %d calls" % (closed, pipeline._busy(), seen, len(calls)))
    finally:
        for worker in list(pipeline._WORKERS):
            worker.join(60)
        convert_scene.walk.blender_matrix = original

    # around the material conversion: before it (which is then not run) and after it
    opts, converted = _cancel_run([path]).opts, []
    real_slots = pipeline._material_slots

    def counting(after):
        calls = []

        def cancel():
            calls.append(None)
            return len(calls) > after
        return cancel, calls

    def slots(*args, **kwargs):
        converted.append(None)
        return real_slots(*args, **kwargs)

    pipeline._material_slots = slots
    try:
        cancel, calls = counting(10 ** 9)
        pipeline._read_scene(path, opts, (), cancel)
        total, outcomes = len(calls), []
        for after in (total - 2, total - 1):
            converted.clear()
            try:
                pipeline._read_scene(path, opts, (), counting(after)[0])
                outcomes.append(None)
            except convert_scene.Cancelled:
                outcomes.append(len(converted))
        check("read cancel: asked just before the material conversion (not run then) and just after it",
              outcomes == [0, 1], "%d calls, %s" % (total, outcomes))
    finally:
        pipeline._material_slots = real_slots


def _mesh_arrays(mesh):
    """Every array build.objects writes into a Mesh, as lists."""
    import numpy

    def get(seq, attr, width, dtype):
        out = numpy.empty(len(seq) * width, dtype=dtype)
        seq.foreach_get(attr, out)
        return out.tolist()

    arrays = {"co": get(mesh.vertices, "co", 3, numpy.float32),
              "vertex_index": get(mesh.loops, "vertex_index", 1, numpy.int32),
              "loop_start": get(mesh.polygons, "loop_start", 1, numpy.int32),
              "material_index": get(mesh.polygons, "material_index", 1, numpy.int32),
              "edges": get(mesh.edges, "vertices", 2, numpy.int32)}
    for name in ("sharp_face", "sharp_edge"):
        attr = mesh.attributes.get(name)
        arrays[name] = get(attr.data, "value", 1, bool) if attr is not None else None
    arrays["uv"] = [(layer.name, get(layer.data, "uv", 2, numpy.float32)) for layer in mesh.uv_layers]
    return arrays


def check_mesh_steps(paths, cancel_path):
    """build.objects.build_steps() makes a mesh above STEP_LOOPS face corners in phases (mesh_steps), looking its
    sharp edges up EDGE_CHUNK edges at a time: the same mesh as make_mesh() in one go, several yields per mesh with
    the count repeated; a run closed while a mesh is half made leaves nothing."""
    from maxdrop.build import objects as build_objects
    from maxdrop.convert import scene as convert_scene
    saved = build_objects.STEP_LOOPS, build_objects.EDGE_CHUNK, build_objects.mesh_steps
    try:
        for path in paths:
            empty_scene()
            name = os.path.basename(path)
            desc = convert_scene.read(path)
            whole = {}
            for key, md in desc.meshes.items():
                mesh, _dropped = build_objects.make_mesh(md)
                whole[key] = _mesh_arrays(mesh)
                bpy.data.meshes.remove(mesh)
            build_objects.STEP_LOOPS, build_objects.EDGE_CHUNK = 0, 7
            steps = build_objects.build_steps(desc, bpy.context.scene.collection)
            counts = []
            while True:
                try:
                    counts.append(next(steps))
                except StopIteration as end:
                    built = end.value
                    break
            build_objects.STEP_LOOPS, build_objects.EDGE_CHUNK = saved[:2]
            total = build_objects.steps_of(desc)
            dones = [d for d, _t in counts]
            sharp = sum(sum(a["sharp_edge"] or []) for a in whole.values())
            check("mesh steps: %s: 3 or more yields per mesh, the count repeated, never back, ending at the total" % name,
                  len(counts) >= total + 3 * len(desc.meshes) and dones == sorted(dones) and dones[-1] == total
                  and {t for _d, t in counts} == {total}, "%d yields, %d steps" % (len(counts), total))
            same = {key: _mesh_arrays(built.meshes[key]) == arrays for key, arrays in whole.items()}
            check("mesh steps: %s: every mesh built in phases equals make_mesh's (%d meshes, %d sharp edges, UVs)"
                  % (name, len(whole), sharp), whole and all(same.values()) and sharp > 0,
                  str([k for k, ok in same.items() if not ok]))
            import numpy
            key, md = max(desc.meshes.items(), key=lambda item: len(item[1].sharp_edges))
            pairs = numpy.asarray(md.sharp_edges)
            shuffled = numpy.concatenate((pairs[::-1], pairs[:3]))  # not sorted, repeated pairs
            flags = build_objects._sharp_edge_flags(built.meshes[key], shuffled)
            check("mesh steps: %s: sharp pairs out of order or repeated mark the same edges" % name,
                  flags.tolist() == whole[key]["sharp_edge"] and len(pairs) > 3, str(len(pairs)))
            flags = build_objects._sharp_edge_flags(built.meshes[key], pairs[:, ::-1])  # each pair (high, low)
            check("mesh steps: %s: sharp pairs given (high, low) mark the same edges" % name,
                  flags.tolist() == whole[key]["sharp_edge"] and len(pairs) > 3, str(len(pairs)))

        empty_scene()
        before = _state()
        inside = []

        def tracked(md, indices=None):
            inside.append(md)
            result = yield from saved[2](md, indices)
            inside.remove(md)
            return result

        build_objects.STEP_LOOPS, build_objects.EDGE_CHUNK, build_objects.mesh_steps = 0, 7, tracked
        meshes = len(bpy.data.meshes)
        run = _cancel_run([cancel_path])
        steps = run.steps()
        held = _advance(steps, lambda: bool(inside) and len(bpy.data.meshes) > meshes + 1)
        steps.close()
        check("mesh steps: closed while a mesh is half made: nothing left", held and _state() == before,
              "%s | %s" % (_state(), before))
    finally:
        build_objects.STEP_LOOPS, build_objects.EDGE_CHUNK, build_objects.mesh_steps = saved


def check_worker_errors():
    """pipeline._in_thread() hands the worker's outcome to the main thread: its value; an Exception unchanged; a
    SystemExit as a RuntimeError caused by it, so that the modal runner's except Exception still tears the run down."""
    from maxdrop import pipeline

    def outcome(fn):
        try:
            return pipeline._drain(pipeline._in_thread(fn))
        except BaseException as e:  # a SystemExit let through must fail this check, not end Blender
            return e

    def exits():
        raise SystemExit(3)

    def fails():
        raise ValueError("maxdrop test: read fails")

    got = outcome(lambda: 42)
    check("worker errors: a worker's value is returned", got == 42, repr(got))
    got = outcome(fails)
    check("worker errors: a worker's ValueError is raised unchanged",
          type(got) is ValueError and str(got) == "maxdrop test: read fails", repr(got))
    got = outcome(exits)
    check("worker errors: a worker's SystemExit is raised as a RuntimeError caused by it",
          type(got) is RuntimeError and type(got.__cause__) is SystemExit and got.__cause__.code == 3,
          "%r from %r" % (got, getattr(got, "__cause__", None)))


def check_pack_cancel(fixture):
    """The threaded unpack of a .zip pack as the run's first step: closed while it unpacks, no staging folder and no
    pack folder are left; closed during the build after it, the finished pack folder stays and nothing in Blender;
    run to its end, the unpack's summary is reported."""
    import time
    import zipfile
    from maxdrop import packs, pipeline
    archive = packs._archive()
    empty_scene()
    before = _state()
    scratch = tempfile.mkdtemp(prefix="maxdrop-pack-cancel-")
    original = archive.unpack
    try:
        pack = os.path.join(scratch, "pack.zip")
        with zipfile.ZipFile(pack, "w") as z:
            z.write(fixture, "pack/" + os.path.basename(fixture))
        scene = "pack/" + os.path.basename(fixture)

        saw = []

        def held(*args, watch=None, **kwargs):
            def holding(n):
                # the worker stays in the unpack until close() stops it: a small pack unpacked before the first
                # step would start the read, and that step would not be _WAIT
                deadline = time.perf_counter() + 30.0
                while time.perf_counter() < deadline:
                    try:
                        watch(n)  # archive.Cancelled once the steps are closed
                    except archive.Cancelled:
                        saw.append(True)
                        raise
                    time.sleep(0.005)
                saw.append(False)
                watch(n)
            return original(*args, watch=holding, **kwargs)

        archive.unpack = held
        run = pipeline._Run(_cancel_run([pack]).opts, [pack], {pack: scene}, bpy.context)
        try:
            steps = run.steps(threaded=True)
            waited = next(steps) is pipeline._WAIT
            steps.close()
        finally:
            archive.unpack = original
            for worker in list(pipeline._WORKERS):  # close() waits _STOP_WAIT at most: here until the unpack has ended
                worker.join(60)
        check("pack cancel: closed while it unpacks: only the archive is left, nothing in Blender",
              waited and saw == [True] and pipeline._busy() == "" and os.listdir(scratch) == ["pack.zip"]
              and _state() == before, "waited %s, stop seen %s, busy %r, %s %s" % (
                  waited, saw, pipeline._busy(), os.listdir(scratch), run.text))

        run = pipeline._Run(_cancel_run([pack]).opts, [pack], {pack: scene}, bpy.context)
        steps = run.steps(threaded=True)
        held = _advance(steps, lambda: len(bpy.data.objects) > 0)
        steps.close()
        folder = os.path.join(scratch, "pack")
        check("pack cancel: closed during the build: the finished pack folder stays, nothing in Blender",
              held and os.path.isfile(os.path.join(folder, os.path.basename(fixture)))
              and os.path.isfile(os.path.join(folder, archive.MARKER)) and _state() == before,
              "%s %s" % (sorted(os.listdir(scratch)), held))

        run = pipeline._Run(_cancel_run([pack]).opts, [pack], {pack: scene}, bpy.context)
        ended = not _advance(run.steps(threaded=True), lambda: False)
        check("pack cancel: run to its end: the unpack's summary reported, the scene imported",
              ended and any(level == 'INFO' and line.startswith("pack.zip: ") for level, line in run.lines)
              and len(run._made) == 1, str(run.lines[:2]))
        run.undo()
    finally:
        archive.unpack = original
        shutil.rmtree(scratch, ignore_errors=True)
