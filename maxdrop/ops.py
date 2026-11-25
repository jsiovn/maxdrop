# SPDX-FileCopyrightText: 2023-2026 Sebastian Schrand
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Modified for MaxDrop, 2026-11-14 (jsiovn). This file was `__init__.py` of io_scene_max 1.9.2. The operator, the
# file handler, the panel ids and the menu text are renamed so that MaxDrop can be installed next to io_scene_max;
# the export operator the handler named never existed and is gone; the package `__init__.py` now reloads the
# modules. The options and what they import are unchanged.
# Modified for MaxDrop, 2026-11-15 (jsiovn). Scene packs: the file browser also takes .zip, .rar and .7z, a drop
# also .rar and .7z; an archive is listed, its scene chosen (pack_scene), unpacked by maxdrop.intake, and the
# engine imports the .max from the pack folder, once per scene. The handler label and the menu text name the
# formats. The popup says when a folder already on disk will be used instead of unpacking.
# Modified for MaxDrop, 2026-11-15 (jsiovn). The import runs MaxDrop's reader, scene description and build (nodes,
# meshes, transforms, hierarchy, instances, layers); only the materials still come from import_max. New options:
# Units, with Scale as an extra factor. Removed: Apply Matrix, Collection and the Primitive, Empty and Armature
# items of Object Filter. The popup shows a pre-flight line per .max (3ds Max version, renderer, objects, unit).
# Modified for MaxDrop, 2026-11-15 (jsiovn). Every imported scene publishes MaxDrop's import report (console, the
# text "MaxDrop Report", its summary as the status line); a scene from a pack also reports the unpack.
# Modified for MaxDrop, 2026-11-15 (jsiovn). The axis conversion also turns the helper empty that carries the
# shear of top-level objects (build.objects.Built.roots).
# Modified for MaxDrop, 2026-11-15 (jsiovn). A file the reader cannot read reports "Not imported" also when it
# fails with an IndexError or struct.error, and a failed build also removes the meshes it made.
# Modified for MaxDrop, 2026-11-16 (jsiovn). The materials come from MaxDrop's material and texture-map rules
# (convert.materials, convert.texmaps) built as node trees (build.materials), one per 3ds Max material, with
# Multi/Sub-Object slots by material ID; import_max is gone. Missing textures and Principled inputs this Blender
# lacks are listed in the import report. A failed build also removes the materials and images it made.
# Modified for MaxDrop, 2026-11-16 (jsiovn). The import report also says what became of the materials and textures
# (convert.report.add_materials): converted by class, wrappers and maps peeled, classes without a rule, textures
# found per lookup rule and missing by name, Principled inputs this Blender lacks. The materials count is part of the
# summary line instead of a line of its own.
# Modified for MaxDrop, 2026-11-16 (jsiovn). A scene pack unpacks only the image and .ies files the chosen scene's
# asset list names (_referenced_maps), and the popup asks the same of an earlier unpack.
# Modified for MaxDrop, 2026-11-17 (jsiovn). Color swatches follow the gamma setting the scene was saved with
# (convert.colors): both converters share the rule read once, and the import report states it.
# Modified for MaxDrop, 2026-11-17 (jsiovn). Shapes are built as curves: a failed build also removes the curves it
# made, and the import report counts them.
# Modified for MaxDrop, 2026-11-17 (jsiovn). New option Modifiers (Keep as Blender Modifiers / Ignore): TurboSmooth,
# MeshSmooth, Shell and Symmetry become Subdivision Surface, Solidify and Mirror (build.modifiers).
# Modified for MaxDrop, 2026-11-18 (jsiovn). The material builder's issues are material issues of the import report,
# and build.report writes the text of a run of several files (publish_run).
# Modified for MaxDrop, 2026-11-18 (jsiovn). A failure of the material conversion imports the scene without
# materials and says so in the import report; materials the builder could not make are not counted as made.
# Modified for MaxDrop, 2026-11-18 (jsiovn). The popup names the exact folder a pack unpacks into
# (archive.preview), also after the Scene field names another scene of the pack.
# Modified for MaxDrop, 2026-11-18 (jsiovn). New option Keep Targets: objects aimed by a Look At controller get a
# Track To constraint to their target; the ones it cannot aim, and an axis conversion, are named in the report.
# Modified for MaxDrop, 2026-11-19 (jsiovn). The scene description gets the asset table: the report names the web
# and IES files of the lights.
# Modified for MaxDrop, 2026-11-19 (jsiovn). Cameras: the scene description gets the file's saved views, the build
# makes the cameras and, for a file with a camera, sets the scene camera and the render size; a failed build removes
# its cameras.
# Modified for MaxDrop, 2026-11-19 (jsiovn). The light colors' swatch note is reported also when the material
# conversion fails; the Keep Targets note on the axis conversion only when the file's up does not stay Blender's Z.
# Modified for MaxDrop, 2026-11-19 (jsiovn). An import reads the file's asset table once, for the scene description
# and the material conversion.
# Modified for MaxDrop, 2026-11-19 (jsiovn). The Scene Pack panel says when no pack folder name is free, and its
# previews are dropped when the archive at that path changed since invoke().
# Modified for MaxDrop, 2026-11-19 (jsiovn). The Scene Pack panel puts the folder of its error lines on a label of
# its own, and invoke() keeps no folder of a pack it cannot look at.
# Modified for MaxDrop, 2026-11-19 (jsiovn). An import started from a window runs in steps (maxdrop.import_progress):
# progress in the status bar, Esc cancels and removes what the run made. The unpack and the reading run in a worker
# thread there; an import from a script or without a window stays synchronous.
# Modified for MaxDrop, 2026-11-19 (jsiovn). New option Text Encoding: the code page of the names of a file saved by
# 3ds Max 2012 or older; the pre-flight line names the one Auto chose for such a file.
# Modified for MaxDrop, 2026-11-19 (jsiovn). A file whose reading runs out of memory or recursion depth is reported
# as not imported too, with a reason also when the error carries no message.
# Modified for MaxDrop, 2026-11-20 (jsiovn). A SystemExit or KeyboardInterrupt in the import's worker thread fails
# the run as a RuntimeError, so the progress runner still tears down and removes what the run made.
# Modified for MaxDrop, 2026-11-20 (jsiovn). Esc during a windowed import's read stops the worker at the next node
# (_read_scene's cancel check, _in_thread's wait).
# Modified for MaxDrop, 2026-11-21 (jsiovn). The read's cancel check is also asked inside a large mesh (comments).
# Modified for MaxDrop, 2026-11-21 (jsiovn). A TypeError or KeyError of the reading (a reader defect) reports the
# file as not imported, with its traceback in the console, instead of ending the operator.
# Modified for MaxDrop, 2026-11-21 (jsiovn). The material slots also hold those of shapes built as curves.
# Modified for MaxDrop, 2026-11-21 (jsiovn). The material converter gets the import's meters per unit (SSS radii).
# Modified for MaxDrop, 2026-11-21 (jsiovn). A VRayLight dome becomes the scene's World (its texture converted with
# the scene's), the first of a run; the World before keeps a fake user and the report says so. A World that cannot be
# built is an issue, not a failed import; a failed or cancelled build puts the World before back and removes the new
# one.
# Modified for MaxDrop, 2026-11-22 (jsiovn). The scene description gets a texture lookup of its own: a VRayIES whose
# intensity is not overridden finds its IES file, whose rated lumens and flux give its power.
# Modified for MaxDrop, 2026-11-22 (jsiovn). An AttributeError of the reading is a reader defect too (_DEFECTS).
# Modified for MaxDrop, 2026-11-23 (jsiovn). The IES, dome and material lookups share one walk of the texture folders
# (convert.textures.TextureIndex.share), each with its own counts; a walk that stopped short is in the report also
# without materials, and an IES file not found then says so.
# Modified for MaxDrop, 2026-11-24 (jsiovn). The texture-map converters get the scene's renderer from the summary
# stream (a rule Corona renders otherwise).
# Modified for MaxDrop, 2026-11-24 (jsiovn). After the modifiers are added, a mesh light's emitter is spread over
# its mesh's evaluated area (build.emitters.spread).
# Modified for MaxDrop, 2026-11-24 (jsiovn). That measurement runs as import steps with a progress text.
# Modified for MaxDrop, 2026-11-25 (jsiovn). Split by responsibility, the code moved unchanged: the option tables
# and ImportOptions are in options.py, the pack listing and the pre-flight in packs.py, the import pipeline
# (_read_file, _scene_steps, _Run) in pipeline.py; this file keeps the operators, the panels, the file handler
# and the registration.


__author__ = "Sebastian Sille <nrgsille@gmail.com>"


import os
import time
import traceback

import bpy
from bpy_extras.io_utils import (
    ImportHelper,
    orientation_helper,
)
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    StringProperty,
    CollectionProperty,
)

from . import prefs
from .compat import poll_file_object_drop
from .options import ImportOptions, LIGHT_STRENGTH, MODIFIERS, TEXT_ENCODINGS, UNITS
from .packs import (
    _archive, _base, _CACHE_MAX, _cached, _choose, _drawn_preview, _key, _norm, _ON_DISK, _packs, _paths, _plural,
    _preflight_of, _preview, _remember_preflight, _scene_list, _scene_search, _SHOWN_FILES, _target, _target_of,
    _TARGETS,
)
from .pipeline import _ACTIVE, _busy, _drain, _PROGRESS_STEPS, _Run, _RUNS, _scene_steps, _SLICE, _Stop, _TICK, _WAIT


def _store_last(source, wm):
    """Keep source's settings as the import's last-used ones, which Blender keeps only for an operator that
    returns FINISHED: the windowed import returns CANCELLED once maxdrop.import_progress has the run."""
    last = wm.operator_properties_last(IMPORT_SCENE_OT_maxdrop.bl_idname)
    for prop in last.bl_rna.properties:
        name = prop.identifier
        if name == "rna_type" or getattr(prop, "is_skip_save", True) or prop.is_readonly:
            continue
        try:
            setattr(last, name, getattr(source, name))
        except (AttributeError, TypeError, ValueError):
            pass


@orientation_helper(axis_forward='Y', axis_up='Z')
class IMPORT_SCENE_OT_maxdrop(bpy.types.Operator, ImportHelper):
    """Import a 3ds Max .max scene, or a .zip, .rar or .7z scene pack holding one"""
    bl_idname = "import_scene.maxdrop"
    bl_label = "Import .max (MaxDrop)"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".max"
    filter_glob: StringProperty(default="*.max;*.zip;*.rar;*.7z", options={'HIDDEN'})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH')

    units: EnumProperty(
        name="Units",
        description="What one unit of the file measures",
        items=UNITS,
        default='AUTO',
    )
    scale_objects: FloatProperty(
        name="Scale",
        description="Extra factor on every length, after Units",
        min=0.0001, max=10000.0,
        soft_min=0.001, soft_max=10000.0,
        default=1.0,
    )
    use_image_search: BoolProperty(
        name="Image Search",
        description="Search subdirectories for any associated images "
        "(Warning, may be slow)",
        default=True,
    )
    object_filter: EnumProperty(
        name="Object Filter", options={'ENUM_FLAG'},
        items=(('MATERIAL', "Material".rjust(12), "Materials of the meshes", 'MATERIAL_DATA', 0x1),
               ('UV', "UV Maps".rjust(11), "UV layers of the meshes", 'UV_DATA', 0x2),
               ),
        description="What to bring in with the objects",
        default={'MATERIAL', 'UV'},
    )
    modifiers: EnumProperty(
        name="Modifiers",
        description="What becomes of the 3ds Max modifiers Blender has an equivalent for",
        items=MODIFIERS,
        default='KEEP',
    )
    light_strength: FloatProperty(
        name="Light Strength",
        description="Factor on the power of every light, in watts from the 3ds Max light's own units. "
        "1.43 gives V-Ray's brightness in Cycles",
        min=0.0, max=1000000.0,
        soft_min=0.0, soft_max=1000.0,
        default=LIGHT_STRENGTH,
    )
    text_encoding: EnumProperty(
        name="Text Encoding",
        description="How the names of a file saved by 3ds Max 2012 or older are read (they are in the code page "
        "of the computer that saved it). Files of 3ds Max 2013 and later are Unicode and ignore it",
        items=TEXT_ENCODINGS,
        default='AUTO',
    )
    keep_targets: BoolProperty(
        name="Keep Targets",
        description="Aim target cameras, target lights and other objects with a Look At controller at their "
        "target with a Track To constraint, so they follow when the target moves. Off: the rotation 3ds Max "
        "had, fixed",
        default=False,
    )
    # SKIP_PRESET as well as SKIP_SAVE: the operator has presets, and a scene name belongs to one pack.
    pack_scene: StringProperty(
        name="Scene",
        description="The .max scene to import from a pack that holds several",
        search=_scene_search,
        options={'SKIP_SAVE', 'SKIP_PRESET'},
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        packs = [(p, _cached(p)) for p in _paths(self)]
        packs = [(p, listing) for p, listing in packs if listing is not None]
        space = getattr(context, "space_data", None)
        if packs:
            import_pack(layout, self, packs)
        elif space is not None and space.type == 'FILE_BROWSER':
            import_pack(layout, self, None)
        if space is None or space.type != 'FILE_BROWSER':  # invoke() reads only what a drop or a script named
            import_files(layout, self)
        import_include(layout, self)
        import_transform(layout, self)

    def _error(self, message):
        self.report({'ERROR'}, message)
        print("MaxDrop: " + message)
        return {'CANCELLED'}

    def _reopen(self, path):
        """Show the options popup again, with the Scene field: after the file browser Blender runs execute()."""
        names = [f.name for f in self.files if f.name]
        where = {"directory": self.directory, "files": [{"name": n} for n in names]} if names else {}
        options = self.as_keywords(ignore=("filter_glob", "files", "directory", "filepath", "pack_scene"))
        try:
            result = bpy.ops.import_scene.maxdrop('INVOKE_DEFAULT', filepath=path, **where, **options)
        except (RuntimeError, TypeError) as e:
            print("MaxDrop: could not show the scene choice (%s)" % e)
            return False
        return 'RUNNING_MODAL' in result

    def execute(self, context):
        archive = _archive()
        paths = _paths(self)
        if not paths:
            return self._error("No file chosen.")
        missing = [p for p in paths if not os.path.isfile(p)]
        if missing:
            return self._error("File not found: %s" % ", ".join(missing))
        try:
            packs = _packs(paths)
            chosen = {path: _choose(path, listing.scenes, self.pack_scene) for path, listing in packs}
        except archive.PackError as e:
            return self._error(str(e))

        open_choice = [path for path, scene in chosen.items() if scene is None]
        if open_choice:
            path = open_choice[0]
            # Only with a window: without one INVOKE_DEFAULT runs execute() again, which would loop.
            if self.options.is_invoke and not bpy.app.background:
                self.report({'WARNING'}, "%s holds several scenes: choose one in the Scene field."
                            % os.path.basename(path))
                if self._reopen(path):
                    return {'CANCELLED'}
            scenes = dict(packs)[path].scenes
            return self._error("%s holds %d scenes: %s. Type one into the Scene field and import again."
                               % (os.path.basename(path), len(scenes), _scene_list(scenes)))

        busy = _busy()
        if busy:
            return self._error(busy)
        run = _Run(ImportOptions.of(self), paths, chosen, context)
        # A window shows the progress and takes Esc; scripts (EXEC) and background runs stay synchronous.
        if self.options.is_invoke and not bpy.app.background and context.window is not None:
            key = "%x" % id(run)
            _RUNS.clear()  # a run whose runner never started
            _RUNS[key] = run
            try:
                started = 'RUNNING_MODAL' in bpy.ops.maxdrop.import_progress('INVOKE_DEFAULT', run_key=key)
            except RuntimeError as e:
                print("MaxDrop: could not show the progress, importing at once (%s)" % e)
                started = False
            finally:
                _RUNS.pop(key, None)
            if started:  # maxdrop.import_progress reports, and makes the undo step when it finishes
                _store_last(self, context.window_manager)
                return {'CANCELLED'}
        run.import_scene = lambda max_path, result, pack_name: self._import_scene(context, max_path, result,
                                                                                 pack_name, run.world)
        window = context.window
        if window:
            window.cursor_set('WAIT')
        try:
            _drain(run.steps())
        except _Stop as e:
            self._report(run.lines)
            return self._error(str(e))
        except BaseException:
            self._report(run.lines)  # the scenes imported before the error
            raise
        finally:
            if window:
                window.cursor_set('DEFAULT')
        self._report(run.lines)
        return {'FINISHED'}

    def _report(self, lines):
        for level, line in lines:
            self.report({level}, line)

    def _import_scene(self, context, max_path, pack=None, pack_name="", world=None):
        """One .max imported at once (_scene_steps; world: the run's world state): ([(report level, line)], the
        convert.report.Report); one of _UNREADABLE when the file cannot be read."""
        return _drain(_scene_steps(ImportOptions.of(self), context.scene, context.view_layer, max_path, pack,
                                   pack_name, prefs.texture_dirs(context), world=world))

    def invoke(self, context, event):
        # A filepath remembered from an earlier run is not "set": only a drop's or a caller's own path is listed.
        if self.properties.is_property_set("filepath"):
            archive = _archive()
            window = context.window
            if window:
                window.cursor_set('WAIT')
            try:
                packs = _packs(_paths(self))
            except archive.PackError as e:
                return self._error(str(e))
            finally:
                if window:
                    window.cursor_set('DEFAULT')
            if len(_TARGETS) >= _CACHE_MAX:
                _TARGETS.clear()
            # Here, not in draw(): finding the parent folder probes it by creating a folder. The folder of the scene
            # known now is previewed here too; draw() previews another one the Scene field names (read only).
            for path, found in packs:
                parent, problem = _target(path, context)
                try:
                    _TARGETS[_norm(path)] = (_key(path), parent, problem, {})
                except OSError:  # gone since it was listed: the popup shows no folder for it
                    _TARGETS.pop(_norm(path), None)
                    continue
                _preview(path, found.scenes, self.pack_scene)  # a pack is never unpacked here
            listed = {_norm(path) for path, _found in packs}
            for path in _paths(self)[:_SHOWN_FILES]:
                if _norm(path) not in listed and os.path.isfile(path):
                    _remember_preflight(path)
        return self.invoke_popup(context)


class MAXDROP_OT_import_progress(bpy.types.Operator):
    """Run an import started from a window: progress in the status bar, Esc to cancel"""
    bl_idname = "maxdrop.import_progress"
    bl_label = "Import .max (MaxDrop)"
    bl_options = {'UNDO', 'INTERNAL'}

    run_key: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        run = _RUNS.pop(self.run_key, None)
        if run is None or context.window is None or _busy():
            return {'CANCELLED'}
        self._run, self._steps, self._timer = run, run.steps(threaded=True), None
        run.close = self._steps.close
        wm = context.window_manager
        try:
            wm.progress_begin(0, _PROGRESS_STEPS)
            self._show(context)
            self._timer = wm.event_timer_add(_TICK, window=context.window)
            _ACTIVE.append(run)
            _guard(True)
            wm.modal_handler_add(self)
        except Exception:
            traceback.print_exc()
            self._teardown(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        try:
            if self._run.stopped:  # an undo, redo or file load in another window closed it (_stop_active)
                return self._finish(context, cancelled=True)
            if event.type == 'ESC' and event.value == 'PRESS':
                return self._finish(context, cancelled=True)
            if event.type != 'TIMER':
                # Swallowed: an undo, a delete or a file load meanwhile would free the datablocks the run holds.
                return {'RUNNING_MODAL'}
            end = time.monotonic() + _SLICE
            try:
                while time.monotonic() < end:
                    if next(self._steps) is _WAIT:
                        break
            except StopIteration:
                return self._finish(context)
            except _Stop as e:
                return self._finish(context, error=str(e))
            self._flush()
            self._show(context)
            return {'PASS_THROUGH'}  # other timers' events reach their owners
        except Exception as e:
            traceback.print_exc()
            try:
                self._steps.close()  # suspended mid-build when the error came from _flush() or _show()
                self._run.undo()
                kept = "nothing was kept"
            except Exception:
                traceback.print_exc()
                kept = "not everything it made could be removed"
            return self._finish(context, error="Import failed, %s (%s: %s)" % (kept, type(e).__name__, e))

    def cancel(self, context):
        # Blender ends the run (a window closed, a file loaded): nothing it made stays.
        self._finish(context, cancelled=True)

    def _show(self, context):
        context.window_manager.progress_update(int(self._run.fraction * _PROGRESS_STEPS))
        if context.workspace is not None:
            context.workspace.status_text_set("MaxDrop: %s (Esc to cancel)" % (self._run.text or "importing"))

    def _flush(self):
        lines, self._run.lines = self._run.lines, []
        for level, line in lines:
            self.report({level}, line)

    def _teardown(self, context):
        """Idempotent. The run leaves _ACTIVE first: an error below must never block the next import."""
        if self._run in _ACTIVE:
            _ACTIVE.remove(self._run)
        if not _ACTIVE:
            _guard(False)
        wm = context.window_manager
        timer, self._timer = self._timer, None
        workspace = context.workspace
        for step in (lambda: timer is not None and wm.event_timer_remove(timer), wm.progress_end,
                     lambda: workspace is not None and workspace.status_text_set(None)):
            try:
                step()
            except Exception:
                traceback.print_exc()

    def _finish(self, context, cancelled=False, error=None):
        self._teardown(context)
        if cancelled:
            try:
                self._steps.close()
                done = "nothing was kept"
            except Exception:
                traceback.print_exc()
                done = "not everything it made could be removed (see the console)"
            self._run.lines = []
            self.report({'WARNING'}, "Import cancelled: " + done)
            print("MaxDrop: import cancelled, " + done)
            return {'CANCELLED'}
        self._flush()
        if error is not None:
            self.report({'ERROR'}, error)
            print("MaxDrop: " + error)
            return {'CANCELLED'}
        return {'FINISHED'}


@bpy.app.handlers.persistent
def _stop_active(*_args):
    """undo_pre, redo_pre and load_pre while a run is active: the run removes what it made before the data it holds
    is freed. The runner swallows the events of its own window only, not those of another window."""
    for run in list(_ACTIVE):
        run.stopped = True
        try:
            run.close()
        except Exception:
            traceback.print_exc()


_GUARDED = ("undo_pre", "redo_pre", "load_pre")


def _guard(on):
    for name in _GUARDED:
        handlers = getattr(bpy.app.handlers, name)
        if on and _stop_active not in handlers:
            handlers.append(_stop_active)
        elif not on and _stop_active in handlers:
            handlers.remove(_stop_active)


def import_pack(layout, operator, packs):
    """packs: [(path, listing)] of a drop or a re-opened popup; None in the file browser, where nothing is listed."""
    header, body = layout.panel("MAXDROP_import_pack", default_closed=False)
    header.label(text="Scene Pack")
    if not body:
        return
    if packs is None:
        body.prop(operator, "pack_scene")
        body.label(text="Only for a pack that holds several .max scenes")
        return
    for path, listing in packs:
        if len(packs) > 1:
            body.label(text=os.path.basename(path), icon='FILE_ARCHIVE')
        if len(listing.scenes) > 1:
            row = body.row()
            row.alert = not operator.pack_scene.strip()
            row.prop(operator, "pack_scene")
        else:
            body.label(text="Scene: " + _base(listing.scenes[0]))
        body.label(text=_plural(listing.assets, "texture file"))
        parent, problem, _previews = _target_of(path) or (None, None, None)
        found = None if problem else _drawn_preview(operator, path, listing)
        if problem:
            body.label(text=problem[0], icon='ERROR')
            for line in problem[1:]:
                body.label(text=line)
        elif found and found[0] == "none":  # found[1], the message execute() would stop with, split into labels
            body.label(text="No free folder for %s in" % os.path.basename(path), icon='ERROR')
            body.label(text=parent)
            body.label(text="Too many folders of that name exist.")
        elif found:
            mode, max_path = found
            if mode == "unpacked":
                body.label(text="Unpacks into")
            elif mode == "reused":
                body.label(text="Unpacked before: imports from")
            else:
                body.label(text="Not unpacked: imports the scene already in", icon='INFO')
            body.label(text=os.path.dirname(max_path))
        else:
            body.label(text="Unpacks into a folder named after the archive" + (" in" if parent else ""))
            if parent:
                body.label(text=parent)



def import_files(layout, operator):
    """The pre-flight line of each .max invoke() read: a drop's or a script's, or a pack's folder on disk."""
    rows = []
    for path in _paths(operator):
        listing = _cached(path)
        found = _drawn_preview(operator, path, listing) if listing is not None else None
        target = found[1] if found and found[0] in _ON_DISK else path
        line = _preflight_of(target)
        if line is not None:
            rows.append((os.path.basename(target), line))
    if not rows:
        return
    header, body = layout.panel("MAXDROP_import_files", default_closed=False)
    header.label(text="File")
    if not body:
        return
    for name, line in rows[:_SHOWN_FILES]:
        body.label(text=name, icon='FILE_3D')
        body.label(text=line)
    if len(rows) > _SHOWN_FILES:
        body.label(text="and %d more" % (len(rows) - _SHOWN_FILES))


def import_include(layout, operator):
    header, body = layout.panel("MAXDROP_import_include", default_closed=False)
    header.label(text="Include")
    if body:
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_image_search")
        layrow.label(text="", icon='OUTLINER_OB_IMAGE' if operator.use_image_search else 'IMAGE_DATA')
        layout.column().prop(operator, "object_filter")
        layout.prop(operator, "modifiers")
        layout.prop(operator, "light_strength")
        layout.prop(operator, "text_encoding")


def import_transform(layout, operator):
    header, body = layout.panel("MAXDROP_import_transform", default_closed=False)
    header.label(text="Transform")
    if body:
        layout.prop(operator, "units")
        layout.prop(operator, "scale_objects")
        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")
        layout.prop(operator, "keep_targets")


class IO_FH_maxdrop(bpy.types.FileHandler):
    bl_idname = "IO_FH_maxdrop"
    bl_label = "MaxDrop (.max, .rar, .7z)"
    bl_import_operator = "import_scene.maxdrop"
    # Not .zip: Blender's own extension installer takes every dropped .zip before a file handler is asked.
    bl_file_extensions = ".max;.rar;.7z"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


def menu_func(self, context):
    self.layout.operator(IMPORT_SCENE_OT_maxdrop.bl_idname, text="MaxDrop (.max, .zip, .rar, .7z)")


_classes = (IMPORT_SCENE_OT_maxdrop, MAXDROP_OT_import_progress, IO_FH_maxdrop)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func)


def unregister():
    _guard(False)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
