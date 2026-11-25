# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pack folders on disk: the marker, the reservation, the destination search and the staging folders."""
import json
import os
import shutil
import stat
import sys
import time

from .policy import (
    _AT_FDCWD, _CANDIDATES, _COPY_DEPTH, _COPY_VISIT_MAX, _MARKER_READ_MAX, _NOREPLACE, _NOREPLACE_UNSUPPORTED,
    _RENAME_EXCL, _RENAME_NOREPLACE, _RESERVATION_STALE_SECONDS, _STALE_SECONDS, _TAKEN_ASIDE, ASSET_EXTENSIONS,
    extension, MARKER, MARKER_FORMAT, name_key, PackError, RECLAIM_PREFIX, refused_reason, RESERVATION, SCENE_EXTENSION,
    STAGING_PREFIX,
)
from .zips import _WIN_LINK_TAGS, _WIN_REPARSE_POINT


def _read_marker(folder):
    try:
        with open(os.path.join(folder, MARKER), "rb") as f:
            data = json.loads(f.read(_MARKER_READ_MAX).decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _wanted_at(wanted, max_path):
    """The name_key() set of the assets to write, None for every asset. wanted: such a set (or None), or a
    references callable, asked about the .max at max_path."""
    if not callable(wanted):
        return wanted
    names = wanted(max_path)
    # A scene also names proxies, xrefs and the like, which are never written: they would only swell the marker.
    return None if names is None else {name_key(n) for n in names if extension(n) in ASSET_EXTENSIONS}


def _marker_matches(marker, ident, scene_name, wanted=None, max_path=None):
    """wanted: the name_key() set asked for now, None for every asset, or a references callable (asked about
    max_path, the folder's .max, only when the folder was unpacked with a filter). A folder unpacked with a filter
    serves only a request it covers."""
    stored_scene = marker.get("scene") if marker is not None else None
    if isinstance(stored_scene, str):
        stored_scene = stored_scene.replace("\\", "/")  # an earlier version kept the \ of UnRAR's listing
    if not (marker is not None and marker.get("format") == MARKER_FORMAT and stored_scene == scene_name
            and all(marker.get(k) == v for k, v in ident.items())):
        return False
    stored = marker.get("wanted")
    if stored is None:
        return True
    if not isinstance(stored, list):
        return False
    wanted = _wanted_at(wanted, max_path)
    return wanted is not None and wanted <= set(stored)


def _write_marker(folder, ident, scene_name, files, wanted=None):
    data = dict(ident, format=MARKER_FORMAT, scene=scene_name, files=files,
                wanted=None if wanted is None else sorted(wanted))
    with open(os.path.join(folder, MARKER), "x", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)


def _write_reservation(folder, ident, maps):
    with open(os.path.join(folder, RESERVATION), "x", encoding="utf-8") as f:
        json.dump(dict(ident, format=MARKER_FORMAT, maps=sorted(maps)), f, indent=1, sort_keys=True)


def _stale_reservation(folder, ident):
    """The files of a destination an unpack of this pack (ident) reserved and never finished, or None. Stale only
    when the folder is a real one holding regular files only: its reservation file, untouched for
    _RESERVATION_STALE_SECONDS, and some of the maps that file lists; no marker and no .max (a folder whose scene
    was moved is complete but for its marker, and may be in use already). The file may come from an archive
    extracted by hand: it must name this pack, and listed names count only as maps the policy allows. Judged from
    the scan, never from the stored names."""
    if _is_link(folder) or not os.path.lexists(os.path.join(folder, RESERVATION)):
        return None
    try:
        with os.scandir(folder) as it:
            items = list(it)
    except OSError:
        return None
    by_key = {name_key(item.name): item for item in items}
    if len(by_key) != len(items):  # two names one key (a case-sensitive file system): one would go unchecked
        return None
    reservation = by_key.get(name_key(RESERVATION))
    try:
        if (reservation is None or not reservation.is_file(follow_symlinks=False)
                or reservation.stat(follow_symlinks=False).st_mtime > time.time() - _RESERVATION_STALE_SECONDS):
            return None
        with open(reservation.path, "rb") as f:
            data = json.loads(f.read(_MARKER_READ_MAX).decode("utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(data, dict) or data.get("format") != MARKER_FORMAT or not isinstance(data.get("maps"), list)
            or any(data.get(k) != v for k, v in ident.items())):
        return None
    maps = {name_key(n) for n in data["maps"]
            if isinstance(n, str) and refused_reason(n) is None and extension(n) in ASSET_EXTENSIONS}
    files = []
    for key, item in by_key.items():
        if item is reservation:
            continue
        try:
            if key not in maps or not item.is_file(follow_symlinks=False):
                return None
        except OSError:
            return None
        files.append(item.path)
    # The reservation last: _clear_stale_reservation removes in this order.
    return files + [reservation.path]


def _clear_stale_reservation(folder, ident):
    """Remove a stale reservation; False when the folder stays. It is first renamed to a staging name: of two
    unpacks clearing it at once only one rename succeeds, and nothing else writes into the renamed folder, so it
    is judged again there and only what that scan found is removed (the reservation file last); a failure
    meanwhile leaves a staging folder, removed as stale later. A folder no longer stale by then (cleared and
    filled anew meanwhile) is renamed back; should that fail (the name taken again, or the rename refused), it is
    renamed to a RECLAIM_PREFIX name, which only this judgement clears (_clear_reclaimed). It stays a staging
    folder only when that rename fails too or a crash comes between the renames: a stale folder taken aside is
    staging from the start, so that a crash while it is removed leaves nothing kept for ever, and stale-staging
    cleanup renames it to a RECLAIM_PREFIX name instead of removing it when it holds more than a stale folder can
    (_refilled)."""
    if _stale_reservation(folder, ident) is None:
        return False
    parent = os.path.dirname(folder)
    moved = os.path.join(parent, _TAKEN_ASIDE + os.urandom(6).hex())
    try:
        os.rename(folder, moved)
    except OSError:
        return False
    files = _stale_reservation(moved, ident)
    if files is None:
        try:
            back = _rename_new(moved, folder)
        except OSError:
            back = False
        if not back:
            try:
                os.rename(moved, os.path.join(parent, RECLAIM_PREFIX + os.urandom(6).hex()))
            except OSError:
                pass
        return False
    try:
        for file in files:
            os.remove(file)
        os.rmdir(moved)
    except OSError:
        pass  # a staging folder now: the name is free all the same
    return not os.path.lexists(folder)


def _noreplace():
    """The rename that never replaces its target, as rename(src, dst): True when renamed, False when this system or
    file system has none, an OSError otherwise (FileExistsError when dst exists). None where there is no such
    call (a POSIX system other than Linux and macOS, a libc without it)."""
    if not _NOREPLACE:
        _NOREPLACE.append(_load_noreplace())
    return _NOREPLACE[0]


def _load_noreplace():
    if os.name == "nt":
        def rename(src, dst):
            os.rename(src, dst)  # refuses an existing dst by itself
            return True
        return rename
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform.startswith("linux"):
            fn = libc.renameat2
            fn.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)

            def call(src, dst):
                return fn(_AT_FDCWD, src, _AT_FDCWD, dst, _RENAME_NOREPLACE)
        elif sys.platform == "darwin":
            fn = libc.renamex_np
            fn.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)

            def call(src, dst):
                return fn(src, dst, _RENAME_EXCL)
        else:
            return None
        fn.restype = ctypes.c_int
    except (ImportError, OSError, AttributeError):
        return None

    def rename(src, dst):
        if call(os.fsencode(src), os.fsencode(dst)) == 0:
            return True
        return _noreplace_failed(ctypes.get_errno(), src, dst)
    return rename


def _noreplace_failed(err, src, dst):
    """False when err says there is no such rename here; otherwise the OSError of err (its subclass, as os.rename
    raises it) is raised."""
    # EINVAL also means a real fault (a folder moved into itself): the fallback's os.rename then raises it, so the
    # fault is not hidden, only reported one call later.
    if err in _NOREPLACE_UNSUPPORTED:
        return False
    raise OSError(err, os.strerror(err), os.fspath(src), None, os.fspath(dst))


def _rename_new(src, dst):
    """Rename the folder src to dst; False when dst exists. A POSIX rename replaces an empty folder, so a rename
    that never replaces is used (_noreplace). Where there is none, dst is looked at first: an empty folder made in
    that instant would be replaced, and would then hold what src held (no file is lost)."""
    rename = _noreplace()
    try:
        if rename is not None and rename(src, dst):
            return True
        if os.path.lexists(dst):
            return False
        os.rename(src, dst)
    except OSError:
        if os.path.lexists(dst):
            return False
        raise
    return True


def _make(folder, fill):
    """_create's fallback: make folder, then fill it (a crash in between leaves it empty). False when it exists;
    any other error of its own stops the unpack."""
    try:
        os.mkdir(folder)
    except FileExistsError:
        return False
    try:
        fill(folder)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return True


def _create(folders, fill, clear=None):
    """Create the first of folders that does not exist yet, already holding what fill(folder) writes into it: it
    is filled under a staging name beside folders[0] and renamed into place, so that a crash never leaves it empty
    (the staging folder a crash leaves is removed as stale later). Only when that rename is refused (Windows: a
    file in it held open, by a virus scan) is the folder made and filled as before, with the old window (_make).
    clear(folder): True when an existing folder was removed (renamed aside first) and its name may be taken again,
    with the same fallback. Returns the folder, None when every one exists."""
    temp = os.path.join(os.path.dirname(folders[0]), STAGING_PREFIX + "new-" + os.urandom(6).hex())
    os.mkdir(temp)
    moved = False
    try:
        fill(temp)
        for folder in folders:
            for freed in (False, True):
                if freed and (clear is None or not clear(folder)):
                    break
                try:
                    moved = _rename_new(temp, folder)
                except OSError:
                    if _make(folder, fill):
                        return folder
                    break
                if moved:
                    return folder
        return None
    finally:
        if not moved:
            shutil.rmtree(temp, ignore_errors=True)


def _is_link(path):
    """A symbolic link, or on Windows a junction (os.path.islink does not see one; os.path.isjunction exists
    from Python 3.12 only). False when path cannot be read."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return (bool(getattr(st, "st_file_attributes", 0) & _WIN_REPARSE_POINT)
            and getattr(st, "st_reparse_tag", 0) in _WIN_LINK_TAGS)


def _find_copy(root, base):
    """A file named like the scene in root or up to _COPY_DEPTH folders below it, shallowest first; links are
    not followed."""
    key = name_key(base)
    level, visited = [root], 0
    for _depth in range(_COPY_DEPTH + 1):
        below = []
        for folder in level:
            try:
                with os.scandir(folder) as it:
                    items = sorted(it, key=lambda d: d.name)
            except OSError:
                continue
            for item in items:
                visited += 1
                if visited > _COPY_VISIT_MAX:
                    return None
                try:
                    if item.is_file(follow_symlinks=False) and name_key(item.name) == key:
                        return item.path
                    if (item.is_dir(follow_symlinks=False) and not item.name.startswith(STAGING_PREFIX)
                            and not _is_link(item.path)):
                        below.append(item.path)
                except OSError:
                    continue
        level = below
    return None


def _candidates(parent, name):
    yield os.path.join(parent, name)
    for n in range(2, _CANDIDATES + 1):
        yield os.path.join(parent, "%s (%d)" % (name, n))


def _probe(folder, scene, ident, wanted):
    """What a candidate folder offers for the scene: "free", "stale" (a reservation a crash left, which unpack()
    clears), ("reused" | "in_place", .max path), or None (taken: never written into)."""
    if not os.path.lexists(folder):
        return "free"
    if _is_link(folder) or not os.path.isdir(folder):
        return None
    if _stale_reservation(folder, ident) is not None:
        return "stale"
    marker = _read_marker(folder)
    if marker is not None:
        max_path = os.path.join(folder, scene.base)
        if os.path.isfile(max_path) and _marker_matches(marker, ident, scene.name, wanted, max_path):
            return ("reused", max_path)
        return None
    found = _find_copy(folder, scene.base)
    return ("in_place", found) if found else None


def _safe_stem(name, fallback):
    stem = name[:-len(SCENE_EXTENSION) - 1] if extension(name) == SCENE_EXTENSION else os.path.splitext(name)[0]
    return stem if stem and refused_reason(stem) is None else fallback


def _offer(folders, scene, ident, wanted):
    """The first candidate to reuse, use in place or write into, as _destination returns it; None when every one
    is taken. A stale reservation is written into only when no later existing candidate serves: a retry after the
    crash may have completed one."""
    stale = None
    for i, folder in enumerate(folders):
        found = _probe(folder, scene, ident, wanted)
        if found == "stale":
            stale = i if stale is None else stale
        elif found == "free":
            i = i if stale is None else stale
            return ("free", folders[i], None, folders[i:])
        elif found:
            return found
    return None if stale is None else ("free", folders[stale], None, folders[stale:])


def _destination(path, dest_parent, scene, several, ident, wanted):
    """("free", folder, container to create or None, the candidate folders from folder on) or ("reused" |
    "in_place", .max path)."""
    stem = _safe_stem(os.path.basename(path), "pack")
    if not several:
        found = _offer(list(_candidates(dest_parent, stem)), scene, ident, wanted)
        if found:
            return found
    else:
        sub = _safe_stem(scene.base, "scene")
        for top in _candidates(dest_parent, stem):
            if not os.path.lexists(top):
                folders = list(_candidates(top, sub))
                return ("free", folders[0], top, folders)
            if _is_link(top) or not os.path.isdir(top):
                continue
            marker = _read_marker(top)
            if marker is None:
                found = _find_copy(top, scene.base)
                if found:
                    return ("in_place", found)
                continue
            if not _marker_matches(marker, ident, None):
                continue
            found = _offer(list(_candidates(top, sub)), scene, ident, wanted)
            if found:
                return found
            break
    raise _no_free_folder(path, dest_parent)


def _no_free_folder(path, parent):
    return PackError("No free folder for %s in %s: too many folders of that name exist."
                     % (os.path.basename(path), parent))


def _reserve(path, folders, ident, maps):
    """Create the first of folders that does not exist yet, holding the reservation file for maps. One that
    appeared since _destination looked (another unpack of the same pack, or anything else) is never written into:
    the next name is taken. A stale reservation is cleared and its name taken again."""
    folder = _create(folders, lambda f: _write_reservation(f, ident, maps),
                     lambda f: _clear_stale_reservation(f, ident))
    if folder is None:
        raise _no_free_folder(path, os.path.dirname(folders[0]))
    return folder


def _only_marker(folder):
    try:
        return set(os.listdir(folder)) <= {MARKER}
    except OSError:
        return False


def _refilled(folder):
    """A folder a clear took aside holds more than a stale one can (_stale_reservation: its reservation file and
    maps, regular files only): a marker, a .max, anything else. Another unpack had filled it anew, or it holds a
    file this code never wrote. True when it cannot be read: kept."""
    reservation = name_key(RESERVATION)
    try:
        with os.scandir(folder) as it:
            return any(not item.is_file(follow_symlinks=False)
                       or (name_key(item.name) != reservation and extension(item.name) not in ASSET_EXTENSIONS)
                       for item in it)
    except OSError:
        return True


def _remove_stale_staging(parent, limits):
    """Remove the staging folders of unpacks that never finished (Blender stopped mid-way): only real folders
    (not links) named with STAGING_PREFIX and untouched for a long time. Nothing else in parent is looked at.
    One a clear took aside and a crash left there holding more than a stale folder can (_refilled) is renamed to
    a RECLAIM_PREFIX name instead: it may hold a complete scene. Best effort."""
    cutoff = time.time() - max(_STALE_SECONDS, 2 * limits.seconds)
    try:
        with os.scandir(parent) as it:
            stale = [item for item in it if item.name.startswith(STAGING_PREFIX)]
    except OSError:
        return
    for item in stale:
        folder = item.path
        try:
            st = os.lstat(folder)
        except OSError:
            continue
        if not stat.S_ISDIR(st.st_mode) or _is_link(folder) or st.st_mtime >= cutoff:
            continue
        if item.name.startswith(_TAKEN_ASIDE) and _refilled(folder):
            try:
                os.rename(folder, os.path.join(parent, RECLAIM_PREFIX + os.urandom(6).hex()))
            except OSError:
                pass  # left as it is: never removed while it holds more than a stale folder
            continue
        shutil.rmtree(folder, ignore_errors=True)


def _clear_reclaimed(parent, ident):
    """Clear the RECLAIM_PREFIX folders in parent that hold a stale reservation of this pack (ident): the
    half-filled folder of an unpack that failed once its folder was taken aside. Judged and removed as a
    destination is (_clear_stale_reservation); any other one stays, a complete scene included. Best effort."""
    try:
        with os.scandir(parent) as it:
            kept = [item.path for item in it if item.name.startswith(RECLAIM_PREFIX)]
    except OSError:
        return
    for folder in kept:
        _clear_stale_reservation(folder, ident)
