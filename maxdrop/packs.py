# SPDX-FileCopyrightText: 2023-2026 Sebastian Schrand
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Modified for MaxDrop, 2026-11-25 (jsiovn). Moved here unchanged from ops.py, whose notes above its code record
# the earlier changes.

"""Scene packs in the popup: listings, the chosen scene, the target folder and the pre-flight lines."""
import os
import re
import struct
import traceback

from . import prefs
from .options import UNIT_METERS


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
# A defect of the reading (reader and scene description), never raised on purpose: _read_scene and _preflight report
# it as _ReadDefect, one of _UNREADABLE, its traceback in the console. Not in _UNREADABLE itself, whose net in
# _Run.steps also covers the build: a build's TypeError is a defect on Blender's side, not a file that cannot be
# read. tests/unit/fuzz.py still counts them as escaped. A windowed import may print the traceback twice for one
# file, from the pre-flight in invoke() and from the read: both are kept, they need not be the same.
# AttributeError is named (decided 2026-11-22): an attribute read on None (a chunk walker that found no child, a
# missing reference) is as likely a defect as a TypeError, and the reader raises none for a damaged file (that is
# MaxFileError); the one it raises on purpose, convert.primitives.Params for a missing key, cannot miss a key of
# its spec. The net stays this narrow, not Exception: NameError, ZeroDivisionError and the rest still end the run
# with a traceback, so that the fuzz campaign and the console show them.
_DEFECTS = (TypeError, KeyError, AttributeError)


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


class _ReadDefect(ValueError):
    """One of _DEFECTS raised while reading a file. Not a MaxFileError: the reader failed, not the file."""


def _defect(name, e):
    """The _ReadDefect of e (one of _DEFECTS) raised while reading the file name, its traceback printed for a bug
    report. Called inside the except clause."""
    print("MaxDrop: reading %s failed, a defect in MaxDrop (please report it with this traceback):\n%s"
          % (name, traceback.format_exc()), end="")
    return _ReadDefect("a defect in MaxDrop's reader (%s: %s), see the console" % (type(e).__name__, e))


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
    except _DEFECTS as e:
        return "Not readable as a .max file (%s)" % _reason(_defect(os.path.basename(path), e))
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
