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


__author__ = "Sebastian Sille <nrgsille@gmail.com>"


import os
import re
from pathlib import Path

import bpy
from bpy_extras.io_utils import (
    ImportHelper,
    orientation_helper,
    axis_conversion,
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

_ARCHIVE_EXTENSIONS = (".zip", ".rar", ".7z")
# Listings of the packs a drop or a script named, for the popup and the Scene search. Keyed by path, size and
# modification time, so that a changed archive is listed again.
_LISTINGS = {}
_TARGETS = {}
_CACHE_MAX = 16
_SHOWN_SCENES = 10
_SEP = re.compile(r"[\\/]")


def _archive():
    # On demand: register() does not load the intake package (see __init__._purge).
    from .intake import archive
    return archive


def _paths(op):
    """The files the operator was given: directory + files (file browser, drop), else filepath (scripts)."""
    names = [f.name for f in op.files if f.name]
    if names:
        return [os.path.join(op.directory, n) for n in names]
    return [op.filepath] if op.filepath else []


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _key(path):
    st = os.stat(path)
    return (_norm(path), st.st_size, st.st_mtime_ns)


def _cached(path):
    try:
        return _LISTINGS.get(_key(path))
    except OSError:
        return None


def _listing(path):
    archive = _archive()
    try:
        key = _key(path)
    except OSError as e:
        raise archive.PackError("%s could not be read (%s)." % (os.path.basename(path), e)) from None
    found = _LISTINGS.get(key)
    if found is None:
        found = archive.list_pack(path)
        if len(_LISTINGS) >= _CACHE_MAX:
            _LISTINGS.clear()
        _LISTINGS[key] = found
    return found


def _base(name):
    return _SEP.split(name)[-1]


def _scene_list(scenes):
    more = len(scenes) - _SHOWN_SCENES
    return ", ".join(scenes[:_SHOWN_SCENES]) + (" and %d more" % more if more > 0 else "")


def _packs(paths):
    """[(path, listing)] of the archives among paths, recognised by their content. PackError when a pack cannot be
    imported as given."""
    archive = _archive()
    packs = []
    for path in paths:
        if archive.kind(path) is None:
            if path.lower().endswith(_ARCHIVE_EXTENSIONS):
                archive.backend_for(path)  # raises: not an archive, whatever its name says
            continue
        packs.append((path, _listing(path)))
    for path, listing in packs:
        if not listing.scenes:
            raise archive.PackError("%s holds no .max scene: it is not a scene pack." % os.path.basename(path))
    if len(packs) > 1:
        for path, listing in packs:
            if len(listing.scenes) > 1:
                raise archive.PackError("%s holds %d scenes: import that pack alone to choose one."
                                        % (os.path.basename(path), len(listing.scenes)))
    return packs


def _choose(path, scenes, text):
    """The scene of a pack: the only one, else the one text names (its path in the archive, or its file name when
    that is unique). None when a choice is needed and text is empty."""
    if len(scenes) == 1:
        return scenes[0]
    text = text.strip()
    if not text:
        return None
    if text in scenes:
        return text
    key = text.replace("\\", "/").casefold()
    matches = ([s for s in scenes if s.replace("\\", "/").casefold() == key]
               or [s for s in scenes if _base(s).casefold() == key])
    if len(matches) == 1:
        return matches[0]
    raise _archive().PackError("%s holds no single scene named %s. Its scenes: %s."
                               % (os.path.basename(path), text, _scene_list(scenes)))


def _target(path, context):
    """(the folder the pack folder will be made in, None), or (None, the reason there is none). The pack folder's
    own name is archive.unpack()'s choice (a free name, an earlier unpack, a copy extracted by hand)."""
    try:
        return prefs.pack_parent(path, context), None
    except ValueError as e:
        return None, str(e)


def _existing(path, scenes, text, parent):
    """("reused" | "in_place", .max path) when the import will use a folder already on disk, None when it will
    unpack, or when the scene is not chosen yet."""
    archive = _archive()
    try:
        scene = _choose(path, scenes, text)
    except archive.PackError:
        return None
    if scene is None:
        return None
    return archive.existing_folder(path, scene, len(scenes) > 1, parent)


def _scene_search(self, context, edit_text):
    try:
        archive = _archive()
        packs = [p for p in _paths(self) if archive.kind(p) is not None]
        found = _cached(packs[0]) if len(packs) == 1 else None
        # Listing a .rar or .7z starts a program: only a .zip is listed from a keystroke.
        if found is None and len(packs) == 1 and archive.kind(packs[0]) == archive.KIND_ZIP:
            found = _listing(packs[0])
        scenes = found.scenes if found is not None else []
    except Exception:  # a suggestion list must never raise in the UI
        return []
    if edit_text in scenes:
        return scenes
    text = edit_text.casefold()
    return [s for s in scenes if text in s.casefold()] or scenes


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


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

    scale_objects: FloatProperty(
        name="Scale",
        description="Scale factor for all objects",
        min=0.0, max=10000.0,
        soft_min=0.0, soft_max=10000.0,
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
        items=(('MATERIAL', "Material".rjust(12), "", 'MATERIAL_DATA', 0x1),
               ('UV', "UV Maps".rjust(11), "", 'UV_DATA', 0x2),
               ('PRIMITIVE', "Primitive".rjust(13), "", 'CUBE', 0x4),
               ('EMPTY', "Empty".rjust(11), "", 'EMPTY_AXIS', 0x8),
               ('ARMATURE', "Armature".rjust(11), "", 'ARMATURE_DATA', 0x10),
               ),
        description="Object types to import",
        default={'MATERIAL', 'UV', 'PRIMITIVE', 'EMPTY', 'ARMATURE'},
    )
    use_collection: BoolProperty(
        name="Collection",
        description="Create a new collection",
        default=False,
    )
    use_apply_matrix: BoolProperty(
        name="Apply Matrix",
        description="Use matrix to transform the objects",
        default=True,
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

        resolved, summaries, written = [], [], []
        window = context.window
        for path in paths:
            if path not in chosen:
                resolved.append(path)
                continue
            if window:
                window.cursor_set('WAIT')
            try:
                result = archive.unpack(path, chosen[path], prefs.pack_parent(path, context))
            except (archive.PackError, ValueError) as e:
                if written:
                    return self._error("%s Nothing was imported. Already unpacked, and used again by the next "
                                       "import: %s." % (e, ", ".join(written)))
                return self._error(str(e))
            finally:
                if window:
                    window.cursor_set('DEFAULT')
            if result.mode == "unpacked":
                written.append("%s into %s" % (os.path.basename(path), result.folder))
            resolved.append(result.max_path)
            summaries.append(_summary(path, result))
            if result.guessed:
                print("MaxDrop: %s: %s stored without a known encoding, read as a guess"
                      % (os.path.basename(path), _plural(len(result.guessed), "name")))

        from . import import_max
        keywords = self.as_keywords(ignore=("axis_forward", "axis_up", "filter_glob", "files", "directory",
                                            "filepath", "pack_scene"))
        keywords["global_matrix"] = axis_conversion(from_forward=self.axis_forward, from_up=self.axis_up,).to_4x4()
        for max_path in resolved:
            import_max.load(self, context, files=[Path(os.path.basename(max_path))],
                            directory=os.path.dirname(max_path), **keywords)
        for line in summaries:
            self.report({'INFO'}, line)
            print("MaxDrop: " + line)
        return {'FINISHED'}

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
            # Here, not in draw(): finding the folder probes it by creating a folder, and an existing copy is
            # searched for on disk.
            for path, found in packs:
                parent, problem = _target(path, context)
                existing = _existing(path, found.scenes, self.pack_scene, parent) if parent else None
                _TARGETS[_norm(path)] = (parent, problem, existing)
        return self.invoke_popup(context)


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
        parent, problem, existing = _TARGETS.get(_norm(path), (None, None, None))
        if problem:
            body.label(text=problem, icon='ERROR')
        elif existing:
            mode, max_path = existing
            if mode == "reused":
                body.label(text="Unpacked before: imports from")
            else:
                body.label(text="Not unpacked: imports the scene already in", icon='INFO')
            body.label(text=os.path.dirname(max_path))
        else:
            body.label(text="Unpacks into a folder named after the archive" + (" in" if parent else ""))
            if parent:
                body.label(text=parent)


def import_include(layout, operator):
    header, body = layout.panel("MAXDROP_import_include", default_closed=False)
    header.label(text="Include")
    if body:
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_image_search")
        layrow.label(text="", icon='OUTLINER_OB_IMAGE' if operator.use_image_search else 'IMAGE_DATA')
        layout.column().prop(operator, "object_filter")
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_collection")
        layrow.label(text="", icon='OUTLINER_COLLECTION' if operator.use_collection else 'GROUP')


def import_transform(layout, operator):
    header, body = layout.panel("MAXDROP_import_transform", default_closed=False)
    header.label(text="Transform")
    if body:
        layout.prop(operator, "scale_objects")
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_apply_matrix")
        layrow.label(text="", icon='VIEW_ORTHO' if operator.use_apply_matrix else 'MESH_GRID')
        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")


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


_classes = (IMPORT_SCENE_OT_maxdrop, IO_FH_maxdrop)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
