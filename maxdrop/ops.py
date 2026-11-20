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


__author__ = "Sebastian Sille <nrgsille@gmail.com>"


import os
import re
import struct
import threading
import time
import traceback

import bpy
from bpy_extras.io_utils import (
    ImportHelper,
    orientation_helper,
    axis_conversion,
)
from mathutils import Matrix
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
# Per pack of the popup, by normalized path: (_key() of the archive, parent folder, the reason there is none as
# popup labels, {scene: _preview()}). An archive replaced at that path since invoke() keeps none of it (_target_of).
_TARGETS = {}
# The previews that name a .max already on disk.
_ON_DISK = ("reused", "in_place")
_CACHE_MAX = 16
_SHOWN_SCENES = 10
# Pre-flight lines of the .max files a drop or a script named, by normalized path.
_PREFLIGHT = {}
_SHOWN_FILES = 5
# A .max that cannot be read. The reader raises reader.errors.MaxFileError (a ValueError); IndexError, struct.error,
# MemoryError and RecursionError are caught too, so that a gap in its checks still reports the file as not imported
# instead of stopping the run.
_UNREADABLE = (OSError, ValueError, IndexError, struct.error, MemoryError, RecursionError)
# What a build makes besides objects and collections, in the order a failed build removes them. Addresses, not
# names: a new datablock could reuse the address of one freed meanwhile, but the build frees none.
_MADE = ("meshes", "curves", "lights", "cameras", "materials", "images")
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

# The default Light Strength: V-Ray 5.2 renders against Cycles renders of the same lights (docs/FORMAT.md,
# "VRayLight", where the measured ratios are). The standard, photometric, sun and IES powers are derived from V-Ray
# renders of the same scene so that this one factor holds for them too ("Standard and photometric lights", "Power,
# measured": 1.43 is pi 683 / 1500).
LIGHT_STRENGTH = 1.43

# Saved in presets by identifier; the numbers keep each item's value stable.
UNITS = (
    ('AUTO', "Auto", "The unit the file was saved with. A file that does not say: 1 unit = Scale meters", 0),
    ('MILLIMETERS', "Millimeters", "One unit of the file is a millimeter", 1),
    ('CENTIMETERS', "Centimeters", "One unit of the file is a centimeter", 2),
    ('METERS', "Meters", "One unit of the file is a meter", 3),
    ('INCHES', "Inches", "One unit of the file is an inch", 4),
    ('FEET', "Feet", "One unit of the file is a foot", 5),
)
# Saved in presets by identifier, like UNITS.
MODIFIERS = (
    ('KEEP', "Keep as Blender Modifiers",
     "TurboSmooth and MeshSmooth become Subdivision Surface, Shell Solidify, Symmetry Mirror", 0),
    ('IGNORE', "Ignore", "The objects arrive without these modifiers (each counted in the import report)", 1),
)
# Saved in presets by identifier, like UNITS. The codecs are reader.strings.CHOICES.
TEXT_ENCODINGS = (
    ('AUTO', "Auto", "The code page the file records, else UTF-8, else Western (1252)", 0),
    ('CP1252', "Western (1252)", "English and Western European names", 1),
    ('CP1250', "Central European (1250)", "Polish, Czech, Hungarian and other Central European names", 2),
    ('CP1251', "Cyrillic (1251)", "Russian, Ukrainian, Bulgarian and other Cyrillic names", 3),
    ('CP1253', "Greek (1253)", "Greek names", 4),
    ('CP1254', "Turkish (1254)", "Turkish names", 5),
    ('CP932', "Japanese (932)", "Japanese names (Shift JIS)", 6),
    ('CP936', "Simplified Chinese (936)", "Simplified Chinese names (GBK)", 7),
    ('CP949', "Korean (949)", "Korean names", 8),
    ('CP950', "Traditional Chinese (950)", "Traditional Chinese names (Big5)", 9),
    ('UTF_8', "UTF-8", "Names saved as UTF-8", 10),
)
TEXT_CODECS = {'CP1252': "cp1252", 'CP1250': "cp1250", 'CP1251': "cp1251", 'CP1253': "cp1253", 'CP1254': "cp1254",
               'CP932': "cp932", 'CP936': "cp936", 'CP949': "cp949", 'CP950': "cp950", 'UTF_8': "utf-8"}
UNIT_METERS = {'MILLIMETERS': 0.001, 'CENTIMETERS': 0.01, 'METERS': 1.0, 'INCHES': 0.0254, 'FEET': 0.3048}
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
    """(the folder the pack folder will be made in, None), or (None, the reason there is none as popup labels). The
    pack folder's own name is archive.unpack()'s choice (a free name, an earlier unpack, a copy extracted by hand),
    which archive.preview() tells beforehand."""
    try:
        return prefs.pack_parent(path, context), None
    except ValueError as e:
        return None, getattr(e, "lines", None) or (str(e),)


def _referenced_maps(max_path):
    """The file names a .max's asset list holds, for archive.unpack(references=...); None (every image and .ies
    file of the pack is unpacked) when the file has no asset list, a damaged one, or cannot be read. Every texture
    the import looks up comes from that list (convert.texmaps)."""
    from .reader import assets, cfb
    why = None
    try:
        with cfb.CompoundFile(max_path) as cf:
            table = assets.AssetTable.from_file(cf)
    except Exception as e:  # any reader failure only costs the filter, never the unpack
        why = "asset list not read (%s)" % e
    else:
        if table.stream is None:
            why = "no asset list"
        elif table.issues:
            why = "asset list damaged (%s)" % table.issues[0]
    if why is not None:
        print("MaxDrop: %s: %s, every map of the pack is unpacked" % (os.path.basename(max_path), why))
        return None
    return {e.name for e in table if e.name}


def _target_of(path):
    """(parent folder, the reason there is none, previews) invoke() stored for the pack; None when it stored none or
    the archive at that path is not the one it looked at (replaced, changed or gone since)."""
    found = _TARGETS.get(_norm(path))
    if found is None:
        return None
    try:
        key = _key(path)
    except OSError:
        return None
    return found[1:] if found[0] == key else None


def _preview(path, scenes, text):
    """archive.preview() of the scene text chooses, ("unpacked" | "reused" | "in_place", .max path), or ("none",
    message) when no folder name is free; computed once per pack and scene since invoke() and kept in _TARGETS.
    None when there is no parent folder, the scene is not chosen yet or its name matches none. A .max on disk gets
    its pre-flight line read."""
    found = _target_of(path)
    if found is None or found[0] is None:
        return None
    parent, _problem, previews = found
    archive = _archive()
    try:
        scene = _choose(path, scenes, text)
    except archive.PackError:
        return None
    if scene is None:
        return None
    if scene not in previews:
        if len(previews) >= _CACHE_MAX:
            previews.clear()
        try:
            previews[scene] = archive.preview(path, scene, len(scenes) > 1, parent, references=_referenced_maps)
        except archive.PackError as e:  # no folder name is free: unpack() would refuse with this message
            previews[scene] = ("none", str(e))
        except Exception as e:  # cached as None: draw() runs on every redraw
            print("MaxDrop: could not preview the pack folder of %s (%s)" % (os.path.basename(path), e))
            previews[scene] = None
        if previews[scene] and previews[scene][0] in _ON_DISK:
            _remember_preflight(previews[scene][1])
    return previews[scene]


def _drawn_preview(operator, path, listing):
    """_preview() for draw(), which must never raise; the Scene field may have named another scene since
    invoke()."""
    try:
        return _preview(path, listing.scenes, operator.pack_scene)
    except Exception as e:
        print("MaxDrop: could not preview the pack folder of %s (%s)" % (os.path.basename(path), e))
        return None


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


def _reason(e):
    """The message of one of _UNREADABLE for the report; a MemoryError or RecursionError often has none."""
    if isinstance(e, MemoryError):
        return str(e) or "not enough memory to read it"
    if isinstance(e, RecursionError):
        return "recursion too deep while importing it"
    return str(e) or type(e).__name__


def _plural(n, word, many=None):
    return "%d %s" % (n, word if n == 1 else many or word + "s")


def _meters(choice, unit, scale):
    """(meters per file unit, a note for the user or "") for a Units choice, the file's reader.units.SystemUnit
    (None when the file does not say) and the Scale factor."""
    if choice != 'AUTO':
        return UNIT_METERS[choice] * scale, ""
    if unit is not None:
        return unit.meters * scale, ""
    return scale, "does not state its unit: 1 unit = %g m (Scale)" % scale


def _preflight(path):
    """One line about a .max before it is imported: 3ds Max version, renderer, objects (nodes), unit. Reads the
    summary stream and the index of the Scene stream, not the objects (0.1 s on a scene of 800 MB)."""
    from .reader import cfb, metadata, strings, units
    from .reader import scene as reader_scene
    try:
        with cfb.CompoundFile(path) as cf:
            try:
                info = metadata.read(cf)
            except metadata.MetadataError:
                info = {}
            sc = reader_scene.Scene.from_file(cf)
            unit = units.system_unit(sc)
            nodes = len(sc.node_indices)
            names = sc.strings
    except _UNREADABLE as e:
        return "Not readable as a .max file (%s)" % _reason(e)
    release = info.get("max_release")
    parts = ["3ds Max %s" % release if release else "3ds Max version not stated"]
    renderer = (info.get("renderer") or {}).get("name")
    if renderer:
        parts.append(renderer)
    parts.append(_plural(nodes, "object"))
    parts.append(unit.name if unit is not None else "unit not stated")
    if not names.wide:  # what Auto chose for an 8-bit file, so the user knows whether to set Text Encoding
        parts.append("names: " + (dict(strings.CHOICES).get(names.codec, names.codec) if names.codec
                                  else "UTF-8, else Western (1252)"))
    return ", ".join(parts)


def _remember_preflight(path):
    if len(_PREFLIGHT) >= _CACHE_MAX:
        _PREFLIGHT.clear()
    try:
        _PREFLIGHT[_key(path)] = _preflight(path)
    except OSError:
        pass


def _preflight_of(path):
    """The line invoke() read for path, None when it read none or the file changed since."""
    try:
        return _PREFLIGHT.get(_key(path))
    except OSError:
        return None


def _material_slots(sc, desc, table, max_path, dirs, image_search):
    """(the material slots of desc's meshes {mesh key: MeshSlots}, (the material converter's, the texture-map
    converter's and the texture lookup's counters, the scene's swatch rule) for the import report): every material
    converted, its texture files looked up. sc: the reader Scene, which the converters read; table: the file's
    reader.assets.AssetTable (the one the scene description got); dirs: the texture search folders
    (prefs.texture_dirs); the counters hold no reference to either. Touches no Blender data."""
    from .convert import colors as convert_colors
    from .convert import materials as convert_materials
    from .convert import texmaps as convert_texmaps
    from .convert import textures as convert_textures
    from .reader import materials as reader_materials
    graph = reader_materials.MaterialGraph(sc)
    index = convert_textures.TextureIndex(max_path, dirs, scene_subfolders=image_search)
    swatches = convert_colors.of_scene(sc)
    tex = convert_texmaps.TexmapConverter(graph, table, textures=index, swatches=swatches)
    conv = convert_materials.MaterialConverter(graph, texmaps=tex, swatches=swatches)
    slots = convert_materials.assign(desc, convert_materials.node_materials(sc, desc), conv)
    return slots, (conv.stats, tex.stats, index.report, swatches)


def _remove(cols, before):
    """Remove what a failed build left: the objects of the file's collection tree, the collections, and the meshes,
    curves, lights, cameras, materials and images made since before ({kind: the as_pointer() of each datablock before
    the build}) that nothing uses."""
    for ob in list(cols.root.all_objects):
        bpy.data.objects.remove(ob)
    for col in list(cols.layers.values()) + [cols.root]:
        bpy.data.collections.remove(col)
    for kind in _MADE:  # meshes and curves first: they free their materials, a removed material its images
        blocks = getattr(bpy.data, kind)
        for block in [b for b in blocks if b.as_pointer() not in before[kind] and not b.users]:
            blocks.remove(block)


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


class ImportOptions:
    """The operator's settings an import reads, copied: a modal run outlives the operator that started it."""
    __slots__ = ("units", "scale_objects", "use_image_search", "object_filter", "modifiers", "light_strength",
                 "keep_targets", "axis_forward", "axis_up", "text_encoding")
    DEFAULTS = {"text_encoding": 'AUTO'}  # an option added after scripts and tests that build ImportOptions

    def __init__(self, **values):
        for name in self.__slots__:
            setattr(self, name, values[name] if name in values else self.DEFAULTS[name])

    @classmethod
    def of(cls, op):
        values = {name: getattr(op, name) for name in cls.__slots__}
        values["object_filter"] = set(values["object_filter"])
        return cls(**values)


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
    failures, the light colors' swatch note."""
    __slots__ = ("desc", "note", "slots", "counts", "failed", "light_note")


def _read_scene(max_path, opts, dirs, cancel=None):
    """Reader, scene description and material conversion of one .max (ImportOptions opts, texture search folders
    dirs): everything the build needs, in a _Read. One of _UNREADABLE when the file cannot be read;
    convert.scene.Cancelled once cancel() holds, asked between nodes, inside a large mesh and around the material
    conversion. Touches no Blender data: a modal run calls it in a worker thread."""
    from .convert import cameras, colors
    from .convert import scene as convert_scene
    from .reader import assets, cfb, units
    from .reader import scene as reader_scene
    name = os.path.basename(max_path)
    read = _Read()
    with cfb.CompoundFile(max_path) as cf:
        sc = reader_scene.Scene.from_file(cf, encoding=TEXT_CODECS.get(opts.text_encoding, "AUTO"))
        unit = units.system_unit(sc)
        meters, read.note = _meters(opts.units, unit, opts.scale_objects)
        table = assets.AssetTable.from_file(cf)
        desc = convert_scene.describe(sc, meters, unit, convert_modifiers=opts.modifiers == 'KEEP',
                                      assets=table, views=cameras.saved_views(cf), cancel=cancel)
        read.slots, read.counts, read.failed = None, None, []
        if 'MATERIAL' in opts.object_filter:
            # asked here, not inside: the except below would take a Cancelled for a material rule's bug
            if cancel is not None and cancel():
                raise convert_scene.Cancelled()
            try:
                read.slots, read.counts = _material_slots(sc, desc, table, max_path, dirs, opts.use_image_search)
            except Exception as e:  # a material rule's bug costs the materials, never the scene
                print("MaxDrop: materials of %s not converted:\n%s" % (name, traceback.format_exc()), end="")
                read.failed.append(("materials", "not converted (%s: %s): the scene is imported without materials"
                                    % (type(e).__name__, e)))
            if cancel is not None and cancel():
                raise convert_scene.Cancelled()
        # light colors follow the swatch rule too; converted materials bring its note to the report
        read.light_note = colors.of_scene(sc).note if desc.lights and read.counts is None else ""
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


def _scene_steps(opts, scene, view_layer, max_path, pack=None, pack_name="", dirs=(), threaded=False,
                 progress=_quiet, made=None):
    """Step generator of one .max: read, describe and build it with its materials into a collection named after it
    in view_layer's active collection, set scene's render size and camera, then publish its import report (console
    and the text "MaxDrop Report"). pack: archive.unpack()'s result when the scene came from a scene pack, pack_name
    the archive's file name. Returns ([(report level, line)], the convert.report.Report), the report's summary last;
    raises one of _UNREADABLE when the file cannot be read. A build that fails or is closed early is removed again
    (objects, collections, meshes, curves, lights, cameras, materials, images) before the exception goes on.
    threaded: the reading in a worker thread (_in_thread), yielding _WAIT meanwhile, stopped when closed;
    progress(text, fraction of the scene) is told what it does; made: a list the scene's build.collections.Collections
    is appended to once built."""
    from .build import cameras as build_cameras
    from .build import collections as build_collections
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
    before = {kind: {d.as_pointer() for d in getattr(bpy.data, kind)} for kind in _MADE}
    cols = build_collections.make(desc, view_layer.active_layer_collection.collection, os.path.splitext(name)[0])
    builder = build_materials.MaterialBuilder()
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
        kept = build_objects.track_targets(desc, built) if opts.keep_targets else []
        build_collections.finish(cols, view_layer)
        build_cameras.set_render(scene, desc, built)  # last: a failed build leaves the scene's alone
    except BaseException:
        _remove(cols, before)
        raise
    if made is not None:
        made.append(cols)
    del slots
    rep = convert_report.gather(desc, source=name, objects_built=len(built.objects),
                                meshes_built=len(built.meshes), curves_built=len(built.curves),
                                lights_built=len(built.lights), cameras_built=len(built.cameras),
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
    if materials:
        conv_stats, tex_stats, lookup, swatches = counts or (None, None, None, None)
        made_materials = sum(m is not None for m in built.materials.values())
        convert_report.add_materials(rep, made_materials, builder.classes, conv_stats=conv_stats,
                                     tex_stats=tex_stats, lookup=lookup, sockets=builder.sockets_skipped,
                                     blender=bpy.app.version_string, swatches=swatches,
                                     build_issues=failed + builder.issues())
    del desc
    axis = axis_conversion(from_forward=opts.axis_forward, from_up=opts.axis_up).to_4x4()
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
        self._render = (self.scene.camera, [getattr(render, name) for name in _RENDER])
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
                            threaded=threaded, progress=self._at(index), made=self._made)
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
        for kind in _MADE:  # meshes and curves first: they free their materials, a removed material its images
            blocks = getattr(bpy.data, kind)
            for block in [b for b in blocks if b.as_pointer() not in self._before[kind] and not b.users]:
                blocks.remove(block)
        for text in [t for t in bpy.data.texts if t.as_pointer() not in self._before["texts"]]:
            bpy.data.texts.remove(text)
        camera, values = self._render
        try:
            self.scene.camera = camera
        except ReferenceError:  # an object removed meanwhile: the scene keeps none
            self.scene.camera = None
        for name, value in zip(_RENDER, values):
            setattr(self.scene.render, name, value)


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
                                                                                 pack_name)
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

    def _import_scene(self, context, max_path, pack=None, pack_name=""):
        """One .max imported at once (_scene_steps): ([(report level, line)], the convert.report.Report); one of
        _UNREADABLE when the file cannot be read."""
        return _drain(_scene_steps(ImportOptions.of(self), context.scene, context.view_layer, max_path, pack,
                                   pack_name, prefs.texture_dirs(context)))

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
