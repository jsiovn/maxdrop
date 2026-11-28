# SPDX-FileCopyrightText: 2023-2026 Sebastian Schrand
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Modified for MaxDrop, 2026-11-25 (jsiovn). Moved here unchanged from ops.py, whose notes above its code record
# the earlier changes.

"""The import pipeline: a file read (in a worker thread from a window), its scene built in steps, and _Run,
which drains them, reports and removes what a cancelled run made."""
import os
import threading
import traceback

import bpy
from bpy_extras.io_utils import axis_conversion
from mathutils import Matrix

from . import prefs
from .options import TEXT_CODECS
from .packs import (
    _archive, _defect, _DEFECTS, _meters, _norm, _plural, _reason, _referenced_maps, _TARGETS, _UNREADABLE,
)


# What a build makes besides objects and collections, in the order a failed build removes them. Addresses, not
# names: a new datablock could reuse the address of one freed meanwhile, but the build frees none.
_MADE = ("meshes", "curves", "lights", "cameras", "materials", "worlds", "images")
# The render settings build.cameras.set_render() changes, put back when a run is cancelled.
_RENDER = ("resolution_x", "resolution_y", "resolution_percentage", "pixel_aspect_x", "pixel_aspect_y")
# A modal run: seconds of work per timer event, the timer's interval, the steps of the progress shown in the cursor,
# the share of a scene's progress its reading takes (scene B: 9 s of reading and describing, 7 s of building), how
# long an Esc during an unpack waits for the unpacker to stop and remove its staging folder, and how long one during
# a read waits for it to stop (asked between nodes and inside a large mesh; past this, _busy() covers the rest).
_SLICE = 0.1
_TICK = 0.05
_PROGRESS_STEPS = 1000
_READ_SHARE = 0.55
_STOP_WAIT = 10.0
_READ_WAIT = 0.5
# Runs execute() hands to maxdrop.import_progress, by key; the run being stepped, and the worker threads of runs
# (one that a cancel did not stop within its wait runs on), so that a second import waits.
_RUNS = {}
_ACTIVE = []
_WORKERS = []


def _material_slots(sc, desc, table, index, meters=None, renderer=None):
    """(the material slots of desc's meshes and curves (convert.materials.Slots), (the material converter's, the
    texture-map converter's and the texture lookup's counters, the scene's swatch rule) for the import report): every
    material converted, its texture files looked up. sc: the reader Scene, which the converters read; table: the
    file's reader.assets.AssetTable (the one the scene description got); index: the texture lookup
    (convert.textures.TextureIndex, a share of the import's: its counts are the materials'); meters: per file unit,
    as the geometry is scaled (lengths such as an SSS radius; None: the file's own unit); the counters hold no
    reference to sc or table. renderer: the scene's renderer ClassID (_renderer_id). Touches no Blender data."""
    from .convert import colors as convert_colors
    from .convert import materials as convert_materials
    from .convert import texmaps as convert_texmaps
    from .reader import materials as reader_materials
    graph = reader_materials.MaterialGraph(sc)
    swatches = convert_colors.of_scene(sc)
    tex = convert_texmaps.TexmapConverter(graph, table, textures=index, swatches=swatches, renderer=renderer,
                                          meters=meters)
    conv = convert_materials.MaterialConverter(graph, texmaps=tex, swatches=swatches, meters=meters)
    slots = convert_materials.assign(desc, convert_materials.node_materials(sc, desc), conv)
    return slots, (conv.stats, tex.stats, index.report, swatches)


def _dome_texture(sc, dd, table, index, renderer=None):
    """(convert.lights DomeTexture of the dome dd's texture map, or None, issues): the map converted as a color input
    with a converter of its own (the materials' counters stay theirs), its file looked up by index (a share of the
    import's convert.textures.TextureIndex: its counts are its own)."""
    from .convert import colors as convert_colors
    from .convert import lights as convert_lights
    from .convert import materials as convert_materials
    from .convert import texmaps as convert_texmaps
    from .reader import materials as reader_materials
    graph = reader_materials.MaterialGraph(sc)
    tex = convert_texmaps.TexmapConverter(graph, table, textures=index, swatches=convert_colors.of_scene(sc),
                                          renderer=renderer)
    graph_ir = tex.convert(convert_materials.MapRef(dd.texmap), convert_texmaps.COLOR, dd.color)
    return convert_lights.dome_texture(graph_ir, graph)


def _make_world(scene, dd, builder, strength, axis, state):
    """Make the World of the dome dd (build.world) and assign it to scene: its texture's image through the import's
    MaterialBuilder (None when it does not load: the World has the dome's color). The World before gets a fake user
    when it would be left without one, so that saving keeps it. state, the run's world state (_world_state): records
    the World made and the one faked. None, or the reason the World is not built: a failure removes what it made
    (one World never costs the scene)."""
    from .build import world as build_world
    worlds = {w.as_pointer() for w in bpy.data.worlds}
    images = {i.as_pointer() for i in bpy.data.images}
    try:
        image = builder.image(dd.texture.image, "World") if dd.texture is not None else None
        world = build_world.make_world(dd, image, strength, axis)
    except Exception as e:
        print("MaxDrop: World of dome light %s not built:\n%s" % (dd.name, traceback.format_exc()), end="")
        for kind, known in (("worlds", worlds), ("images", images)):  # the World first: it frees its image
            blocks = getattr(bpy.data, kind)
            for block in [b for b in blocks if b.as_pointer() not in known and not b.users]:
                blocks.remove(block)
        return "the World is not built (%s: %s): the scene keeps its World" % (type(e).__name__, e)
    before = scene.world
    scene.world = world
    state["made"] = world
    if before is not None and not before.users and not before.use_fake_user:
        before.use_fake_user = True
        state["faked"] = before
    return None


def _world_state():
    """A run's world state: the World its first dome made ("made") and the World before it, faked ("faked")."""
    return {}


def _name_of(block):
    try:
        return block.name
    except ReferenceError:
        return "removed"


def _restore_world(scene, world, state=None):
    """Put scene's World back to world (None when it was removed meanwhile); a fake user state recorded on it is
    taken off again."""
    try:
        scene.world = world
    except ReferenceError:
        scene.world = None
    faked = state.pop("faked", None) if state is not None else None
    if faked is not None:
        try:
            faked.use_fake_user = False
        except ReferenceError:
            pass
    if state is not None:
        state.pop("made", None)


def _remove(cols, before):
    """Remove what a failed build left: the objects of the file's collection tree, the collections, the meshes,
    curves, lights, cameras, materials and images made since before ({kind: the as_pointer() of each datablock before
    the build}) that nothing uses, and every Text made since (an IES light's: a new Text has a fake user)."""
    for ob in list(cols.root.all_objects):
        bpy.data.objects.remove(ob)
    for col in list(cols.layers.values()) + [cols.root]:
        bpy.data.collections.remove(col)
    for kind in _MADE:  # meshes and curves first: they free their materials, a removed material its images
        blocks = getattr(bpy.data, kind)
        for block in [b for b in blocks if b.as_pointer() not in before[kind] and not b.users]:
            blocks.remove(block)
    for text in [t for t in bpy.data.texts if t.as_pointer() not in before["texts"]]:
        bpy.data.texts.remove(text)


def _summary(path, result):
    if result.mode == "unpacked":
        done = _plural(result.written, "file") + " written"
    elif result.mode == "reused":
        done = "unpacked before, %s reused" % _plural(result.reused, "file")
    else:
        done = "a file of that name already in that folder, used in place"
    skipped = (sum(result.skipped.values()) + len(result.refused) + len(result.not_regular) + len(result.collided)
               + result.unwanted)
    return "%s: %s from %s, %s, %d skipped" % (
        os.path.basename(path), os.path.basename(result.max_path), result.folder, done, skipped)


class _Stop(Exception):
    """A run ends with this message for the user, as execute() did with _error() before it ran in steps."""


# What _in_thread() yields while its worker runs: the driver of a modal run waits for the next timer event instead of
# asking again at once (which would take the interpreter from the worker).
_WAIT = object()


def _drain(steps):
    """Run a step generator to its end; its return value."""
    while True:
        try:
            next(steps)
        except StopIteration as end:
            return end.value


def _in_thread(fn, *args, stop=None, wait=_STOP_WAIT, **kwargs):
    """Step generator: fn(*args, **kwargs) in a worker thread, yielding _WAIT while it runs; its return value, or its
    exception raised here. fn must touch no Blender data. Closed early: stop (a threading.Event fn watches) is set
    and the worker given wait seconds to end; without stop, or past that, its result is dropped when it ends
    (_busy() refuses a new import meanwhile)."""
    box = {}

    def work():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as e:
            box["error"] = e

    worker = threading.Thread(target=work, name="MaxDrop import", daemon=True)
    _WORKERS[:] = [w for w in _WORKERS if w.is_alive()] + [worker]
    worker.start()
    try:
        while worker.is_alive():
            yield _WAIT
    except GeneratorExit:
        if stop is not None:
            stop.set()
            worker.join(wait)
        raise
    if "error" in box:
        error = box["error"]
        if not isinstance(error, Exception):
            # A worker's SystemExit or KeyboardInterrupt ended only the read; raised as it is, it would pass the
            # modal runner's except Exception and skip its teardown and the removal of what the run made.
            raise RuntimeError("the import thread ended with %s" % type(error).__name__) from error
        raise error
    return box["value"]


class _Read:
    """What _read_scene() read of a .max: desc, the unit note, the material slots and counters, the conversion
    failures, the light colors' swatch note, the texture walk's report (convert.textures.TextureReport: where it
    stopped, whichever lookup walked)."""
    __slots__ = ("desc", "note", "slots", "counts", "failed", "light_note", "walk")


def _read_scene(max_path, opts, dirs, cancel=None):
    """Reader, scene description and material conversion of one .max (ImportOptions opts, texture search folders
    dirs): everything the build needs, in a _Read. One of _UNREADABLE when the file cannot be read;
    convert.scene.Cancelled once cancel() holds, asked between nodes, inside a large mesh and around the material
    conversion. Touches no Blender data: a modal run calls it in a worker thread. A defect of the reading (one of
    _DEFECTS) is raised as _ReadDefect."""
    try:
        return _read_file(max_path, opts, dirs, cancel)
    except _DEFECTS as e:
        raise _defect(os.path.basename(max_path), e) from e


def _renderer_id(cf):
    """The ClassID (a, b) of the renderer the open .max cf was saved with (its summary stream), None when it does
    not say or the stream is not readable (an unreadable stream never costs the import; a reader defect still
    surfaces, as everywhere in the reading)."""
    from .reader import metadata
    try:
        return (metadata.read(cf).get("renderer") or {}).get("class_id")
    except _UNREADABLE:
        return None


def _read_file(max_path, opts, dirs, cancel):
    """_read_scene() without its net for _DEFECTS."""
    from .convert import cameras, colors
    from .convert import scene as convert_scene
    from .convert import textures as convert_textures
    from .reader import assets, cfb, units
    from .reader import scene as reader_scene
    name = os.path.basename(max_path)
    read = _Read()
    with cfb.CompoundFile(max_path) as cf:
        sc = reader_scene.Scene.from_file(cf, encoding=TEXT_CODECS.get(opts.text_encoding, "AUTO"))
        unit = units.system_unit(sc)
        meters, read.note = _meters(opts.units, unit, opts.scale_objects)
        table = assets.AssetTable.from_file(cf)
        renderer = _renderer_id(cf)
        # one walk of the texture folders, a share per lookup: the materials' counts are their textures only
        files = convert_textures.TextureIndex(max_path, dirs, scene_subfolders=opts.use_image_search)
        read.walk = files.report
        desc = convert_scene.describe(sc, meters, unit, convert_modifiers=opts.modifiers == 'KEEP',
                                      assets=table, views=cameras.saved_views(cf), cancel=cancel,
                                      files=files.share())
        read.slots, read.counts, read.failed = None, None, []
        if desc.dome is not None and desc.dome.texmap is not None:
            try:
                desc.dome.texture, issues = _dome_texture(sc, desc.dome, table, files.share(), renderer)
            except Exception as e:  # a texture rule's bug costs the World its texture, never the scene
                print("MaxDrop: dome texture of %s not converted:\n%s" % (name, traceback.format_exc()), end="")
                issues = ["its texture is not converted (%s: %s): the World has its color" % (type(e).__name__, e)]
            desc.issues.extend((desc.dome.node, "light: %s" % x) for x in issues)
        if 'MATERIAL' in opts.object_filter:
            # asked here, not inside: the except below would take a Cancelled for a material rule's bug
            if cancel is not None and cancel():
                raise convert_scene.Cancelled()
            try:
                read.slots, read.counts = _material_slots(sc, desc, table, files.share(), meters,
                                                            renderer)
            except Exception as e:  # a material rule's bug costs the materials, never the scene
                print("MaxDrop: materials of %s not converted:\n%s" % (name, traceback.format_exc()), end="")
                read.failed.append(("materials", "not converted (%s: %s): the scene is imported without materials"
                                    % (type(e).__name__, e)))
            if cancel is not None and cancel():
                raise convert_scene.Cancelled()
        # light colors follow the swatch rule too; converted materials bring its note to the report
        read.light_note = colors.of_scene(sc).note if (desc.lights or desc.emitters) and read.counts is None else ""
        del sc  # the Scene holds the inflated stream of a compressed file
    if 'UV' not in opts.object_filter:
        for md in desc.meshes.values():
            md.uv_layers = []
    read.desc = desc
    return read


def _quiet(_text, _fraction):
    pass


def _busy():
    """Why an import cannot start now, "" when it can."""
    if _ACTIVE:
        return "An import is running: wait for it to finish, or press Esc to cancel it."
    if any(w.is_alive() for w in _WORKERS):
        return "A cancelled import is still reading its file: try again in a moment."
    return ""


def _scene_steps(opts, scene, view_layer, max_path, pack=None, pack_name="", dirs=(), threaded=False,
                 progress=_quiet, made=None, world=None):
    """Step generator of one .max: read, describe and build it with its materials into a collection named after it
    in view_layer's active collection, set scene's render size and camera, then publish its import report (console
    and the text "MaxDrop Report"). pack: archive.unpack()'s result when the scene came from a scene pack, pack_name
    the archive's file name. Returns ([(report level, line)], the convert.report.Report), the report's summary last;
    raises one of _UNREADABLE when the file cannot be read. A build that fails or is closed early is removed again
    (objects, collections, meshes, curves, lights, cameras, materials, images, texts) before the exception goes on.
    threaded: the reading in a worker thread (_in_thread), yielding _WAIT meanwhile, stopped when closed;
    progress(text, fraction of the scene) is told what it does; made: a list the scene's build.collections.Collections
    is appended to once built; world: the run's world state (_world_state; None: a run of this file alone): a dome
    becomes the World only when no earlier file of the run made one."""
    from .build import cameras as build_cameras
    from .build import collections as build_collections
    from .build import emitters as build_emitters
    from .build import materials as build_materials
    from .build import modifiers as build_modifiers
    from .build import objects as build_objects
    from .build import report as build_report
    from .convert import report as convert_report
    name = os.path.basename(max_path)
    materials = 'MATERIAL' in opts.object_filter
    progress("reading " + name, 0.0)
    if threaded:
        stop = threading.Event()  # set when the steps are closed: the reading ends at its next check
        read = yield from _in_thread(_read_scene, max_path, opts, dirs, stop.is_set, stop=stop, wait=_READ_WAIT)
    else:
        read = _read_scene(max_path, opts, dirs)
    desc, slots, counts, failed = read.desc, read.slots, read.counts, read.failed
    before = {kind: {d.as_pointer() for d in getattr(bpy.data, kind)} for kind in _MADE + ("texts",)}
    cols = build_collections.make(desc, view_layer.active_layer_collection.collection, os.path.splitext(name)[0])
    builder = build_materials.MaterialBuilder()
    axis = axis_conversion(from_forward=opts.axis_forward, from_up=opts.axis_up).to_4x4()
    world = _world_state() if world is None else world
    world_before, earlier = scene.world, world.get("made")
    world_issue = None
    try:
        steps = build_objects.build_steps(desc, cols.root, cols, view_layer, slots=slots,
                                          material=builder.make if materials else None,
                                          light_strength=opts.light_strength)
        while True:
            try:
                done, total = next(steps)
            except StopIteration as end:
                built = end.value
                break
            progress("building %s: %d / %d" % (name, done, total), _READ_SHARE + (1.0 - _READ_SHARE) * done / total)
            yield
        settings_skipped = build_modifiers.add(desc, built)
        spread = build_emitters.spread(desc, built, scene.collection, view_layer, opts.light_strength)
        try:  # closed here, not left to the collector: its copies are in scene.collection, out of _remove's reach
            for done, total in spread:
                progress("measuring the mesh lights of %s: %d / %d" % (name, done, total), None)
                yield
        finally:
            spread.close()
        kept = build_objects.track_targets(desc, built) if opts.keep_targets else []
        build_collections.finish(cols, view_layer)
        if desc.dome is not None and earlier is None:
            world_issue = _make_world(scene, desc.dome, builder, opts.light_strength, axis.to_3x3(), world)
        build_cameras.set_render(scene, desc, built)  # last: a failed build leaves the scene's alone
    except BaseException:
        if earlier is None and world.get("made") is not None:  # this file's World: put the one before back first,
            _restore_world(scene, world_before, world)        # so the new one has no user and goes with the rest
        _remove(cols, before)
        raise
    if made is not None:
        made.append(cols)
    del slots
    rep = convert_report.gather(desc, source=name, objects_built=len(built.objects),
                                meshes_built=len(built.meshes), curves_built=len(built.curves),
                                lights_built=len(built.lights) + len(built.emitters),
                                cameras_built=len(built.cameras),
                                dropped_uv_layers=built.dropped_uv_layers,
                                pack=pack, pack_name=pack_name)
    if settings_skipped:
        rep.issues.append(("modifiers", "%d settings not on Blender %s, not set" % (settings_skipped,
                                                                                   bpy.app.version_string)))
    names = {node.index: node.name or "object %d" % node.index for node in desc.nodes}
    rep.issues.extend((names[i], "Keep Targets: no Track To, the rotation stays fixed: %s" % reason)
                      for i, reason in kept)
    if read.light_note:
        rep.issues.append(("color swatches", read.light_note))
    if desc.dome is not None:
        dome = desc.dome.name or "object %d" % desc.dome.node
        if earlier is not None:
            rep.issues.append((dome, "light: dome light not imported: an earlier file of this import gave the World "
                                     "(%s)" % _name_of(earlier)))
        elif world_issue is not None:
            rep.issues.append((dome, "light: " + world_issue))
        else:
            was = world_before.name if world_before is not None else None
            rep.world = "the dome light %s%s" % (dome, ", in place of %s (kept)" % was if was else "")
        if not materials:  # with materials the builder's issues come with theirs
            rep.issues.extend(x for x in builder.issues() if x[0] == "World")
    if materials:
        conv_stats, tex_stats, lookup, swatches = counts or (None, None, None, None)
        made_materials = sum(m is not None for m in built.materials.values())
        convert_report.add_materials(rep, made_materials, builder.classes, conv_stats=conv_stats,
                                     tex_stats=tex_stats, lookup=lookup, sockets=builder.sockets_skipped,
                                     blender=bpy.app.version_string, swatches=swatches,
                                     build_issues=failed + builder.issues())
    # the walk every lookup shared (the materials' lookup has the same stops): also without materials
    rep.texture_search_stopped = convert_report.search_stopped(read.walk)
    del desc
    if axis != Matrix.Identity(4):
        for ob in built.roots():
            ob.matrix_basis = axis @ ob.matrix_basis
        # the target's own Z (use_target_z) turns with the scene; the world's does not, which matters only when
        # the file's up does not stay Blender's Z
        if tuple(axis.col[2][:3]) != (0.0, 0.0, 1.0) and any(
                c.name == build_objects.TRACK_TO_NAME and not c.use_target_z
                for ob in built.objects.values() for c in ob.constraints):
            rep.issues.append(("Keep Targets", "Track To keeps Blender's Z up, not the converted axes' up"))
    lines = [('WARNING', "%s %s" % (name, read.note))] if read.note else []
    lines.append(build_report.publish(rep))
    return lines, rep


class _Run:
    """One import of the files execute() was given, after its checks: the unpack of each pack, then each scene.

        run = _Run(opts, paths, chosen, context)    # chosen: {archive path: its scene}
        steps = run.steps(threaded)                 # a step generator; run.text, run.fraction: where it is
        run.lines                                   # [(report level, line)] to report, each printed already

    The steps raise _Stop with the message to report when the run ends without importing. Closing them early
    (Esc) removes everything the run made in Blender (undo()): the scene being built, the scenes it finished, a
    "MaxDrop Report" text it created; the scene camera and render size are put back. A pack folder it unpacked
    stays."""

    def __init__(self, opts, paths, chosen, context, import_scene=None):
        self.opts, self.paths, self.chosen = opts, paths, chosen
        self.scene, self.view_layer = context.scene, context.view_layer
        self.dirs = prefs.texture_dirs(context)
        self.parents = {}
        for path in chosen:
            try:
                self.parents[path] = (prefs.pack_parent(path, context), None)
            except ValueError as e:
                self.parents[path] = (None, e)
        # Synchronous: import_scene(max_path, unpack result, pack name) -> (lines, rep), the operator's own.
        self.import_scene = import_scene
        self.lines, self.text, self.fraction = [], "", 0.0
        self._made, self._before, self._render = [], None, None
        self.world = _world_state()  # the World the run's first dome made, the World before it if faked
        # The runner's close of its steps, for _stop_active; stopped once that closed them.
        self.close, self.stopped = (lambda: None), False

    def _say(self, level, line, printed=None):
        self.lines.append((level, line))
        print("MaxDrop: " + (line if printed is None else printed))

    def _at(self, index):
        """progress(text, fraction of the scene); fraction None: the text alone (an unpack, whose share of the run is
        not known)."""
        def progress(text, fraction):
            self.text = text if len(self.paths) == 1 else "%s (%d of %d)" % (text, index + 1, len(self.paths))
            if fraction is not None:
                self.fraction = (index + fraction) / len(self.paths)
        return progress

    def steps(self, threaded=False):
        """The step generator; threaded: the unpacks and the reading in a worker thread."""
        archive = _archive()
        self._before = {kind: {d.as_pointer() for d in getattr(bpy.data, kind)} for kind in _MADE + ("texts",)}
        render = self.scene.render
        self._render = (self.scene.camera, [getattr(render, name) for name in _RENDER], self.scene.world)
        try:
            resolved, summaries, written = [], [], []  # resolved: [(.max path, unpack result, archive path)]
            for index, path in enumerate(self.paths):
                if path not in self.chosen:
                    resolved.append((path, None, None))
                    continue
                result = yield from self._unpack(archive, index, path, written, threaded)
                _TARGETS.pop(_norm(path), None)  # its previews are out of date now: the next invoke() makes new ones
                if result.mode == "unpacked":
                    written.append("%s into %s" % (os.path.basename(path), result.folder))
                resolved.append((result.max_path, result, path))
                summaries.append(_summary(path, result))
                if result.guessed:
                    print("MaxDrop: %s: %s stored without a known encoding, read as a guess"
                          % (os.path.basename(path), _plural(len(result.guessed), "name")))
            # Before the scenes: the status bar shows the last report, which is to be a scene's summary (or a failure).
            for line in summaries:
                self._say('INFO', line)
            reports, failed = [], []
            for index, (max_path, result, pack_path) in enumerate(resolved):
                pack_name = os.path.basename(pack_path) if pack_path else ""
                try:
                    if self.import_scene is not None:
                        lines, rep = self.import_scene(max_path, result, pack_name)
                    else:
                        lines, rep = yield from _scene_steps(
                            self.opts, self.scene, self.view_layer, max_path, result, pack_name, self.dirs,
                            threaded=threaded, progress=self._at(index), made=self._made, world=self.world)
                except _UNREADABLE as e:
                    failed.append("%s: %s" % (os.path.basename(max_path), _reason(e)))
                    continue
                reports.append(rep)
                for level, line in lines:
                    self._say(level, line)
            if not reports:
                raise _Stop("Nothing imported. " + "; ".join(failed))
            if len(reports) > 1 or failed:
                from .build import report as build_report
                build_report.publish_run(reports, failed)
            for line in failed:
                self._say('WARNING', "Not imported: " + line, "not imported: " + line)
        except GeneratorExit:
            self.undo()
            raise

    def _unpack(self, archive, index, path, written, threaded):
        """Step generator: archive.unpack() of the pack at path; _Stop when it fails."""
        name = os.path.basename(path)
        progress = self._at(index)
        progress("unpacking " + name, None)
        parent, problem = self.parents[path]
        try:
            if problem is not None:
                raise problem
            if not threaded:
                return archive.unpack(path, self.chosen[path], parent, references=_referenced_maps)
            stop = threading.Event()

            def watch(n):
                progress("unpacking %s: %.1f MiB" % (name, n / 1048576.0), None)
                if stop.is_set():
                    raise archive.Cancelled()

            return (yield from _in_thread(archive.unpack, path, self.chosen[path], parent,
                                          references=_referenced_maps, watch=watch, stop=stop))
        except (archive.PackError, ValueError) as e:
            if written:
                raise _Stop("%s Nothing was imported. Already unpacked, and used again by the next import: %s."
                            % (e, ", ".join(written))) from None
            raise _Stop(str(e)) from None

    def undo(self):
        """Remove what the run made in Blender; a no-op before steps() started."""
        if self._before is None:
            return
        for cols in self._made:
            for ob in list(cols.root.all_objects):
                bpy.data.objects.remove(ob)
            for col in list(cols.layers.values()) + [cols.root]:
                bpy.data.collections.remove(col)
        self._made = []
        camera, values, world = self._render
        _restore_world(self.scene, world, self.world)  # before the removal: a World the run made then has no user
        for kind in _MADE:  # meshes and curves first: they free their materials, a removed material its images
            blocks = getattr(bpy.data, kind)
            for block in [b for b in blocks if b.as_pointer() not in self._before[kind] and not b.users]:
                blocks.remove(block)
        for text in [t for t in bpy.data.texts if t.as_pointer() not in self._before["texts"]]:
            bpy.data.texts.remove(text)
        try:
            self.scene.camera = camera
        except ReferenceError:  # an object removed meanwhile: the scene keeps none
            self.scene.camera = None
        for name, value in zip(_RENDER, values):
            setattr(self.scene.render, name, value)
