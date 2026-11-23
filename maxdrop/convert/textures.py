# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where the texture files of a scene are on this computer: a fixed lookup order that never follows a stored path
to a place the file should not reach.

    index = TextureIndex(max_path, prefs.texture_dirs(), scene_subfolders=image_search)   # once per import
    found = index.find(entry.path, entry.resolved)    # Found(path, rule) or None (reader/assets.AssetEntry)
    lights = index.share()                            # the same walk, counts of its own
    index.report.found[SCENE], index.report.missing, index.report.truncated   # worded by convert.report

A scene stores a path for each file, written on another computer. Only its file name is looked up, compared
without regard to case, in this order:

1. SCENE: the scene's folder (with scene_subfolders, its subfolders too: the Image Search option).
2. SIBLING: the folders named maps or textures (any case) beside the scene file and beside the scene's folder,
   that is inside the scene's folder and inside its parent, with their subfolders.
3. USER: the user's texture search folders, in their order, with their subfolders.
4. ORIGINAL: the stored path itself (then the absolute path 3ds Max resolved when saving), only when it is an
   absolute path on a drive letter of a local drive (removable, fixed, CD-ROM or RAM disk; never a network
   drive) and names a plain file. A UNC path (\\\\server\\share), a device path (\\\\?\\, \\\\.\\, a reserved
   device name such as CON), a relative path, a path that climbs with .. and a drive-relative path (C:a.jpg) are
   never opened (refused_reason says why). Each part of the path, from the drive root down, is checked with lstat
   before the next: a symbolic link or junction anywhere in it (one may point at a network share) refuses the
   path before anything behind it is touched. Rule 4 exists on Windows only: elsewhere a 3ds Max path names
   nothing.

The first rule that has the name wins; inside a rule the file nearest to the folder searched wins (breadth
first, names sorted). Each rule's folders are walked once, when the rule is first needed, at most max_depth
folders deep. The bound on work is a count, no time limit: a rule reads at most max_entries files and folders (one
more to see the budget run out), the SIBLING rule's listing of the scene's folder and its parent included, and a
folder's listing is read no further than the budget left, so a folder of millions of entries costs no more than
the budget. The report says where a rule stopped; of the folder it stopped in, the entries taken follow the order
the file system lists them (case-insensitive name order on NTFS), then names sorted. A link is a symbolic link or a name-surrogate
reparse point (junction, mount point): never entered, never taken, in any rule; other reparse points (cloud
placeholders, deduplicated files) are ordinary files and folders. Unreadable folders are skipped. No bpy, no reader
import: this takes the stored strings.
"""
import collections
import copy
import itertools
import os
import stat
import unicodedata

from .. import pathnames

SCENE, SIBLING, USER, ORIGINAL = 1, 2, 3, 4
RULES = (SCENE, SIBLING, USER, ORIGINAL)
RULE_NAMES = {SCENE: "the scene's folder", SIBLING: "maps or textures folders", USER: "texture search folders",
              ORIGINAL: "the stored path"}
SIBLING_NAMES = frozenset(("maps", "textures"))
DEFAULT_MAX_DEPTH = 8
DEFAULT_MAX_ENTRIES = 200_000  # files and folders, per rule

_NAME_SURROGATE = 0x20000000  # reparse tag bit of symbolic links, junctions and mount points
_LOCAL_DRIVE_TYPES = frozenset((2, 3, 5, 6))  # GetDriveTypeW: removable, fixed, CD-ROM, RAM disk (4 = network)


def name_key(name):
    """Equal for names a case-insensitive file system treats as the same file."""
    return unicodedata.normalize("NFC", name).casefold()


def _control(text):
    return any(unicodedata.category(c) == "Cc" for c in text)


def name_refused(name):
    """Why a file name is not looked up, None when it is."""
    if name in ("", ".", ".."):
        return "empty or a folder reference"
    if _control(name):
        return "control character"
    if ":" in name:
        return "drive or stream name"
    return None


def refused_reason(path):
    """Why a stored path is never opened where it points (rule 4), None when it may be."""
    if not path:
        return "empty"
    if _control(path):
        return "control character"
    if path[:1] in "\\/" and path[1:2] in ("\\", "/"):
        return "network or device path"
    if not (len(path) >= 3 and path[0].isascii() and path[0].isalpha() and path[1] == ":" and path[2] in "\\/"):
        return "not an absolute path on a drive"
    if ":" in path[2:]:
        return "stream name"
    parts = path[3:].replace("\\", "/").split("/")
    if ".." in parts:
        return "climbs out with .."
    if any(pathnames.is_reserved(p) for p in parts):
        return "device name"
    return None


def is_local_drive(path):
    """True when path (refused_reason None) is on a local drive; always False off Windows."""
    if os.name != "nt":
        return False
    import ctypes
    try:
        kind = ctypes.windll.kernel32.GetDriveTypeW(path[:2] + "\\")
    except (AttributeError, OSError):
        return False
    return kind in _LOCAL_DRIVE_TYPES


def _link(st):
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_reparse_tag", 0) & _NAME_SURROGATE)


def _plain_file(path):
    """path (refused_reason None) names a regular file and no part of it is a link, each part checked with
    lstat from the drive root down, so nothing behind a link is touched."""
    current = path[:3]
    parts = [p for p in path[3:].replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts:
        return False
    try:
        for i, part in enumerate(parts):
            current = os.path.join(current, part)
            st = os.lstat(current)
            if _link(st):
                return False
            if i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
                return False
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(st.st_mode)


def _by_name(entry):
    return entry.name


def _entries(folder, limit):
    """At most limit entries of folder, sorted by name: the listing is read no further, however many entries the
    folder has. All of them when it has no more than limit."""
    try:
        with os.scandir(folder) as it:
            return sorted(itertools.islice(it, max(limit, 0)), key=_by_name)
    except (OSError, ValueError):
        return []


def _named(folder, keys, budget):
    """(the entries of folder whose name_key is in keys, sorted by name; True when the listing was cut). Each entry
    read is charged to budget, a one-item list; the listing stops at the first entry that finds it at 0."""
    found, cut = [], False
    try:
        with os.scandir(folder) as it:
            for e in it:
                if budget[0] <= 0:
                    cut = True
                    break
                budget[0] -= 1
                if name_key(e.name) in keys:
                    found.append(e)
    except (OSError, ValueError):
        pass
    return sorted(found, key=_by_name), cut


def _kind(entry):
    """'file', 'dir' or None (a link, anything else, or unreadable), without following links."""
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    if _link(st):
        return None
    if stat.S_ISREG(st.st_mode):
        return "file"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    return None


class Found(collections.namedtuple("Found", "path rule")):
    """A texture file on disk and the rule (SCENE, SIBLING, USER, ORIGINAL) that found it."""
    __slots__ = ()


class TextureReport:
    """What the lookups of one import found: files per rule and the names not found, each name counted once (a
    name found by a later lookup is no longer missing)."""

    def __init__(self):
        self.found = dict.fromkeys(RULES, 0)
        self.truncated = []  # (rule, folder, max_entries): the search of that rule stopped in folder
        self._found = set()
        self._missing = {}

    def add(self, name, found):
        key = name_key(name)
        if key in self._found:
            return
        if found is None:
            self._missing.setdefault(key, name or "(no file name)")
        else:
            self._found.add(key)
            self._missing.pop(key, None)
            self.found[found.rule] += 1

    @property
    def missing(self):
        """The file names not found, sorted, each once."""
        return [self._missing[k] for k in sorted(self._missing)]


class TextureIndex:
    """The texture lookup of one import: each rule's folders walked once, on first need."""

    def __init__(self, scene_path, user_dirs=(), scene_subfolders=False, max_depth=DEFAULT_MAX_DEPTH,
                 max_entries=DEFAULT_MAX_ENTRIES, is_local_drive=is_local_drive):
        self.scene_dir = os.path.dirname(os.path.abspath(scene_path))
        self.user_dirs = list(dict.fromkeys(os.path.abspath(d) for d in user_dirs))
        self.scene_subfolders = scene_subfolders
        self.max_depth, self.max_entries = max_depth, max_entries
        self._is_local_drive = is_local_drive
        self._tiers = {}
        self._cache = {}
        self.report = TextureReport()

    def share(self):
        """A lookup over this one's walk: the same folders and bounds, each rule's folders walked once for both
        (and every other share), a stopped walk in the report of each; its own cache and its own found and missing
        counts (the materials' report counts their textures, not an IES file or the dome's image)."""
        other = copy.copy(self)
        other._cache = {}
        other.report = TextureReport()
        other.report.truncated = self.report.truncated
        return other

    def _roots(self, rule, budget):
        """The folders rule walks, in order, as (folder, whether its subfolders too); (folder, None) when the budget
        ran out while listing folder to find them."""
        if rule == SCENE:
            yield self.scene_dir, self.scene_subfolders
        elif rule == SIBLING:
            # lazy: the scene folder's maps are walked before its parent is listed, so a crowded parent (a
            # download folder) cannot spend the budget they need
            for folder in dict.fromkeys((self.scene_dir, os.path.dirname(self.scene_dir))):
                named, cut = _named(folder, SIBLING_NAMES, budget)
                if cut:
                    yield folder, None
                    return
                for e in named:
                    if _kind(e) == "dir":
                        yield e.path, True
        else:
            for d in self.user_dirs:
                yield d, True

    def _tier(self, rule):
        index = self._tiers.get(rule)
        if index is None:
            index = self._tiers[rule] = {}
            budget = [self.max_entries]
            for root, recursive in self._roots(rule, budget):
                stopped = root if recursive is None else self._walk(root, recursive, index, budget)
                if stopped is not None:
                    self.report.truncated.append((rule, stopped, self.max_entries))
                    break
        return index

    def _walk(self, root, recursive, index, budget):
        """Add root's files to index; the folder where the budget ran out, None when it did not."""
        queue = collections.deque([(root, 0)])
        while queue:
            folder, depth = queue.popleft()
            for e in _entries(folder, budget[0] + 1):  # one past the budget: enough to see it run out
                if budget[0] <= 0:
                    return folder
                budget[0] -= 1
                kind = _kind(e)
                if kind == "file":
                    index.setdefault(name_key(e.name), e.path)
                elif kind == "dir" and recursive and depth < self.max_depth:
                    queue.append((e.path, depth + 1))
        return None

    def _find(self, path, resolved):
        name = pathnames.base_name(path) or pathnames.base_name(resolved)
        if name_refused(name) is None:
            key = name_key(name)
            for rule in (SCENE, SIBLING, USER):
                hit = self._tier(rule).get(key)
                if hit is not None:
                    return Found(hit, rule)
        for p in (path, resolved):
            if p and refused_reason(p) is None and self._is_local_drive(p) and _plain_file(p):
                return Found(os.path.normpath(p), ORIGINAL)
        return None

    def find(self, path, resolved=""):
        """Found(path, rule) for a stored path (and the resolved one of a FileAssetMetaData3 record), None when
        no rule finds it. Recorded in report."""
        path, resolved = path or "", resolved or ""
        key = (path, resolved)
        if key not in self._cache:
            found = self._cache[key] = self._find(path, resolved)
            self.report.add(pathnames.base_name(path) or pathnames.base_name(resolved), found)
        return self._cache[key]
