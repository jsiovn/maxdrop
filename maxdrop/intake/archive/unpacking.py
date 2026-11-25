# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Listing a pack, choosing its scene and maps, and unpacking them: list_pack(), preview(), unpack()."""
import dataclasses
import os
import shutil
import tempfile
from typing import Dict, List, Tuple

from .policy import (
    _Budget, _BY_HAND, _RACE_RETRIES, _size_text, _skip_key, ASSET_EXTENSIONS, DEFAULT_LIMITS, Entry, extension, kind,
    name_key, PackError, password_message, refused_reason, RESERVATION, SCENE_EXTENSION, STAGING_PREFIX,
)
from .zips import _BACKENDS
from .folders import (
    _clear_reclaimed, _create, _destination, _no_free_folder, _only_marker, _read_marker, _remove_stale_staging,
    _reserve, _wanted_at, _write_marker,
)


def backend_for(path):
    k = kind(path)
    if k is None:
        raise PackError("%s is not a .zip, .rar or .7z archive." % os.path.basename(path))
    backend = _BACKENDS.get(k)
    if backend is None:
        raise PackError("MaxDrop cannot read .%s archives yet. Extract %s by hand and import the .max."
                        % (k, os.path.basename(path)))
    return k, backend


def _read_entries(backend, path, limits):
    too_many = PackError("%s lists more than the %d entries MaxDrop reads. Extract it by hand."
                         % (os.path.basename(path), limits.entries))
    count = getattr(backend, "entry_count", None)
    if count is not None and count(path, limits.entries) > limits.entries:
        raise too_many
    entries = backend.names(path)
    if len(entries) > limits.entries:
        raise too_many
    # Shown and chosen with / whichever program listed them (UnRAR on Windows writes \); a backend keeps its
    # own spelling in the key.
    for e in entries:
        e.name = e.name.replace("\\", "/")
    return entries


def _listed_by(backend, entries):
    """The label of the program that listed the entries: a backend may go through several programs."""
    listed_by = getattr(backend, "listed_by", None)
    return backend.name if listed_by is None else listed_by(entries)


def _is_scene(e):
    return (not e.is_dir and e.regular and extension(e.base) == SCENE_EXTENSION
            and refused_reason(e.base) is None)


@dataclasses.dataclass
class PackListing:
    kind: str
    backend: str
    scenes: List[str]               # archive paths of the .max entries, in archive order
    assets: int                     # image and .ies names, valid and distinct: unpack() writes one file per name
    skipped: int                    # entries never written, whatever the scene
    problems: List[str]
    encrypted: List[str]
    guessed: List[str]


def list_pack(path, limits=DEFAULT_LIMITS):
    """The scenes of a pack and what unpacking would skip. Reads the archive's directory only."""
    k, backend = backend_for(path)
    entries = _read_entries(backend, path, limits)
    scenes, assets, skipped = [], set(), 0
    for e in entries:
        if e.is_dir:
            continue
        if _is_scene(e):
            scenes.append(e.name)
        elif e.regular and refused_reason(e.base) is None and extension(e.base) in ASSET_EXTENSIONS:
            assets.add(name_key(e.base))
        else:
            skipped += 1
    encrypted = [e.name for e in entries if e.encrypted and not e.is_dir]
    guessed = [e.name for e in entries if e.guessed]
    problems = []
    if encrypted:
        problems.append("%d encrypted entr%s: extract the archive by hand"
                        % (len(encrypted), "y" if len(encrypted) == 1 else "ies"))
    unsupported = [e.name for e in entries if e.unsupported and not e.is_dir]
    if unsupported:
        problems.append("%d entr%s MaxDrop cannot read: extract the archive by hand"
                        % (len(unsupported), "y" if len(unsupported) == 1 else "ies"))
    if guessed:
        problems.append("%d name%s stored without a known encoding, read as a guess"
                        % (len(guessed), "" if len(guessed) == 1 else "s"))
    return PackListing(k, _listed_by(backend, entries), scenes, len(assets), skipped, problems, encrypted, guessed)


@dataclasses.dataclass
class UnpackResult:
    max_path: str
    folder: str
    mode: str                       # "unpacked", "reused" (an earlier unpack) or "in_place" (a copy the user made)
    backend: str
    written: int = 0                # files written now
    reused: int = 0                 # files of an earlier unpack used again
    skipped: Dict[str, int] = dataclasses.field(default_factory=dict)       # by extension
    refused: List[Tuple[str, str]] = dataclasses.field(default_factory=list)  # (archive path, reason)
    not_regular: List[str] = dataclasses.field(default_factory=list)
    collided: List[str] = dataclasses.field(default_factory=list)         # duplicates that lost
    unwanted: int = 0               # assets left out by `wanted`
    guessed: List[str] = dataclasses.field(default_factory=list)


def _rank(scene_dirs, dirs):
    """Smaller is nearer to the scene: same folder, then below it, then by the number of path steps."""
    s = [p.casefold() for p in scene_dirs]
    d = [p.casefold() for p in dirs]
    if d == s:
        return (0, 0)
    if d[:len(s)] == s:
        return (1, len(d) - len(s))
    common = 0
    while common < min(len(s), len(d)) and s[common] == d[common]:
        common += 1
    return (2, len(s) + len(d) - 2 * common)


def _select(entries, scene, wanted, result):
    """The asset entries to write with the scene, one per name, nearest to the scene first in archive order."""
    best = {}
    for index, e in enumerate(entries):
        if e.is_dir or e is scene:
            continue
        reason = refused_reason(e.base)
        if not e.regular:
            result.not_regular.append(e.name)
        elif reason is not None:
            result.refused.append((e.name, reason))
        elif extension(e.base) not in ASSET_EXTENSIONS:
            result.skipped[_skip_key(e.base)] = result.skipped.get(_skip_key(e.base), 0) + 1
        elif wanted is not None and name_key(e.base) not in wanted:
            result.unwanted += 1
        else:
            key = name_key(e.base)
            candidate = (_rank(scene.dirs, e.dirs), index, e)
            current = best.get(key)
            if current is None or candidate[:2] < current[:2]:
                if current is not None:
                    result.collided.append(current[2].name)
                best[key] = candidate
            else:
                result.collided.append(e.name)
    return [c[2] for c in sorted(best.values(), key=lambda c: c[1])]


def _ident(path, st):
    return {"archive": os.path.basename(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def preview(path, scene, several, dest_parent=None, references=None):
    """(mode, .max path) of what unpack() of the scene (its archive path; several: the pack holds more than one)
    would do now, as UnpackResult names it: "unpacked" into the first free folder, "reused" (an earlier unpack) or
    "in_place" (a copy extracted by hand: no marker needed, any file named like the scene counts). None when the
    archive cannot be read; PackError, with the message unpack() would refuse with, when no folder name is free.
    Reads the disk only, for the options popup; unpack() takes the next free name when something makes that folder
    first. references: what the caller passes to unpack(); it decides whether a folder unpacked with a filter
    serves."""
    path = os.path.abspath(path)
    dest_parent = os.path.abspath(dest_parent or os.path.dirname(path))
    entry = Entry(scene.replace("\\", "/"))
    try:
        found = _destination(path, dest_parent, entry, several, _ident(path, os.stat(path)), references)
    except OSError:
        return None
    if found[0] == "free":
        return ("unpacked", os.path.join(found[1], entry.base))
    return found


def _check_space(entries, folder, limits, written=0):
    """written: bytes this unpack has written already: they count against the pack's limit, and are no longer
    free space."""
    declared = 0
    for e in entries:
        size = e.size or 0
        if size > limits.file_bytes:
            raise PackError("%s is larger than %s, the most MaxDrop unpacks for one file. Extract the archive by "
                            "hand." % (e.name, _size_text(limits.file_bytes)))
        declared += size
    if declared + written > limits.total_bytes:
        raise PackError("The pack unpacks to more than %s, the most MaxDrop writes from one pack. Extract it by "
                        "hand." % _size_text(limits.total_bytes))
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return
    if declared + limits.free_margin > free:
        raise PackError("Not enough free space in %s: the scene needs about %s, %s are free."
                        % (folder, _size_text(declared + limits.free_margin), _size_text(free)))


def _check_staging(staging, targets, path):
    """Exactly the planned names, each a regular file with one link: a backend must not leave a link, a folder
    or anything else behind."""
    on_disk = []
    with os.scandir(staging) as it:
        for item in it:
            if not item.is_file(follow_symlinks=False) or os.lstat(item.path).st_nlink != 1:
                on_disk = None
                break
            on_disk.append(name_key(item.name))
    # By name_key: a file system may store a name in another Unicode normal form (macOS).
    if on_disk is None or sorted(on_disk) != sorted(name_key(t) for t in targets):
        raise PackError("Unpacking %s wrote other files than asked for. Extract it by hand."
                        % os.path.basename(path))


def _refuse_unreadable(entries, path):
    for e in entries:
        if e.encrypted:
            raise PackError(password_message(path))
        if e.unsupported:
            raise PackError(_BY_HAND % ("%s %s" % (e.name, e.unsupported)))


def unpack(path, scene=None, dest_parent=None, limits=DEFAULT_LIMITS, wanted=None, references=None, watch=None):
    """Unpack the scene (its archive path, as list_pack gives it; may be None when the pack holds one) with its
    maps. wanted: optional set of name_key() base names; when given, only those assets are written. references:
    instead of wanted, a callable asked about a .max path that returns the base names of the files that scene
    uses, or None for every asset. It is asked about the scene once written into the staging folder (the maps
    follow), or about the .max of an earlier unpack that may be used again; it must leave no file open.

    The destination is <dest_parent>/<archive stem>/, or <dest_parent>/<archive stem>/<scene stem>/ when the pack
    holds several scenes; dest_parent defaults to the archive's folder.

    watch: called with the bytes written so far while the files are written (often: every chunk, or every half
    second while a program unpacks), in the thread that unpacks. It may raise Cancelled to stop: the program is
    ended, the staging folder removed, and a pack folder made for this unpack removed while it holds nothing else.
    """
    if wanted is not None and references is not None:
        raise ValueError("pass wanted or references, not both")
    path = os.path.abspath(path)
    _k, backend = backend_for(path)
    entries = _read_entries(backend, path, limits)
    scenes = [e for e in entries if _is_scene(e)]
    if not scenes:
        raise PackError("%s holds no .max scene." % os.path.basename(path))
    if scene is None and len(scenes) == 1:
        chosen = scenes[0]
    elif scene is None:
        raise PackError("%s holds %d scenes: choose one." % (os.path.basename(path), len(scenes)))
    else:
        chosen = next((e for e in scenes if e.name == scene.replace("\\", "/")), None)
        if chosen is None:
            raise PackError("%s holds no scene %s." % (os.path.basename(path), scene))
    dest_parent = os.path.abspath(dest_parent or os.path.dirname(path))
    try:
        st = os.stat(path)
    except OSError as e:
        raise PackError("%s could not be read (%s)." % (os.path.basename(path), e)) from None
    ident = _ident(path, st)

    # Nothing is written for a reused or in-place result: it names the program that listed the pack.
    result = UnpackResult(max_path="", folder="", mode="unpacked", backend=_listed_by(backend, entries))
    result.guessed = [e.name for e in entries if e.guessed]
    wanted = None if wanted is None else {name_key(w) for w in wanted}
    asked = wanted if references is None else references

    def existing(found):
        result.mode, result.max_path = found
        result.folder = os.path.dirname(result.max_path)
        if result.mode == "reused":
            files = (_read_marker(result.folder) or {}).get("files")
            result.reused = files if isinstance(files, int) else 0
        return result

    found = _destination(path, dest_parent, chosen, len(scenes) > 1, ident, asked)
    if found[0] in ("reused", "in_place"):
        return existing(found)

    _free, folder, container, folders = found
    space_at = os.path.dirname(container or folder)
    scene_plan = [(chosen, chosen.base)]
    _refuse_unreadable([chosen], path)

    def asset_plan(want, scene_written=None):
        """(entry, target) of the maps to write; scene_written: the bytes of the scene when it is on disk
        already, None when it is written with the maps."""
        assets = _select(entries, chosen, want, result)
        _refuse_unreadable(assets, path)
        if len(assets) + 1 > limits.files:
            raise PackError("The scene needs %d files, more than the %d MaxDrop writes from one pack. Extract it "
                            "by hand." % (len(assets) + 1, limits.files))
        if scene_written is None:
            _check_space([chosen] + assets, space_at, limits)
        else:
            _check_space(assets, space_at, limits, scene_written)
        return [(e, e.base) for e in assets]

    if references is None:
        plan = scene_plan + asset_plan(wanted)
    else:
        _check_space([chosen], space_at, limits)

    created = None
    try:
        retries = 0
        if len(scenes) > 1:
            # A pack folder is made under a staging name beside it: one a crash left there is removed by every
            # unpack of the pack, not only by the next one that makes a pack folder.
            _remove_stale_staging(dest_parent, limits)
        while container is not None:
            if _create([container], lambda f: _write_marker(f, ident, None, 0)) is None:
                # Another unpack of this pack made it first: it may hold the folder to reuse.
                retries += 1
                if retries > _RACE_RETRIES:
                    raise _no_free_folder(path, dest_parent) from None
                found = _destination(path, dest_parent, chosen, True, ident, asked)
                if found[0] in ("reused", "in_place"):
                    return existing(found)
                _free, folder, container, folders = found
                continue
            created = container
            break
        parent = os.path.dirname(folder)
        # The unpack's staging and _reserve's are made beside the folder (dest_parent itself for one scene), and
        # so are the folders a clear takes aside.
        _remove_stale_staging(parent, limits)
        _clear_reclaimed(parent, ident)
        staging = tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=parent)
        reserved = None
        budget = _Budget(limits, watch)
        labels = []

        def extract(part):
            # A backend that tries several programs may write the scene with one and its maps with another.
            label = backend.extract(path, part, staging, budget) or backend.name
            if label not in labels:
                labels.append(label)

        try:
            if references is None:
                extract(plan)
            else:
                # The scene alone first: only its own asset table says which maps it needs. A solid .rar or .7z
                # is then decompressed twice, within the one time limit.
                extract(scene_plan)
                _check_staging(staging, [chosen.base], path)
                wanted = _wanted_at(references, os.path.join(staging, chosen.base))
                maps = asset_plan(wanted, scene_written=budget.total)
                if maps:
                    extract(maps)
                plan = scene_plan + maps
            _check_staging(staging, [t for _e, t in plan], path)
            reserved = _reserve(path, folders, ident, [t for _e, t in plan[1:]])
            # The maps, then the scene, then the marker: a folder seen half-filled has no .max to import yet,
            # and only a complete one carries the marker that lets it be reused.
            for target in [t for _e, t in plan[1:]] + [chosen.base]:
                os.rename(os.path.join(staging, target), os.path.join(reserved, target))
            _write_marker(reserved, ident, chosen.name, len(plan), wanted)
            try:
                os.remove(os.path.join(reserved, RESERVATION))
            except OSError:
                pass  # complete all the same: a marker and a .max are never stale
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            if reserved is not None:
                shutil.rmtree(reserved, ignore_errors=True)
            raise
        folder = reserved
        try:
            os.rmdir(staging)  # empty: _check_staging allowed only the files that were moved
        except OSError:
            pass  # removed as stale by a later unpack
    except BaseException as e:
        # Only while it holds nothing but its marker: another unpack of this pack may have put a scene in it.
        if created is not None and _only_marker(created):
            shutil.rmtree(created, ignore_errors=True)
        if isinstance(e, OSError):
            raise PackError("Could not unpack %s into %s (%s)." % (os.path.basename(path), os.path.dirname(folder),
                                                                    e)) from None
        raise
    result.folder = folder
    result.max_path = os.path.join(folder, chosen.base)
    result.written = len(plan)
    result.backend = " and ".join(labels)
    return result
