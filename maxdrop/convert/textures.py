# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where the texture files of a scene are on this computer: a fixed lookup order that never follows a stored path
to a place the file should not reach.

    index = TextureIndex(max_path, prefs.texture_dirs(), scene_subfolders=image_search)   # once per import
    found = index.find(entry.path, entry.resolved)    # Found(path, rule) or None (reader/assets.AssetEntry)
    index.report.found[SCENE], index.report.missing, index.report.lines()

A scene stores a path for each file, written on another computer. Only its file name is looked up, compared
without regard to case, in this order:

1. SCENE: the scene's folder (with scene_subfolders, its subfolders too: the Image Search option).
2. SIBLING: the folders named maps or textures (any case) beside the scene file and beside the scene's folder,
   that is inside the scene's folder and inside its parent, with their subfolders.
3. USER: the user's texture search folders, in their order, with their subfolders.
4. ORIGINAL: the stored path itself (then the absolute path 3ds Max resolved when saving), only when it is an
   absolute path on a drive letter of a local drive (removable, fixed, CD-ROM or RAM disk; never a network
   drive) and names a plain file, not a link. A UNC path (\\\\server\\share), a device path (\\\\?\\, \\\\.\\, a reserved
   device name such as CON), a relative path, a path that climbs with .. and a drive-relative path (C:a.jpg) are
   never opened (refused_reason says why). Rule 4 exists on Windows only: elsewhere a 3ds Max path names nothing.

The first rule that has the name wins; inside a rule the file nearest to the folder searched wins (breadth
first, names sorted). Each rule's folders are walked once, when the rule is first needed, at most max_depth
folders deep and max_files files per rule (the report names a folder where the walk stopped); links and
reparse-point folders (junctions) are not entered, linked files are not taken, unreadable folders are skipped.
No bpy, no reader import: this takes the stored strings.
"""
import collections
import os
import stat
import unicodedata

SCENE, SIBLING, USER, ORIGINAL = 1, 2, 3, 4
RULES = (SCENE, SIBLING, USER, ORIGINAL)
RULE_NAMES = {SCENE: "the scene's folder", SIBLING: "maps or textures folders", USER: "texture search folders",
              ORIGINAL: "the stored path"}
SIBLING_NAMES = frozenset(("maps", "textures"))
DEFAULT_MAX_DEPTH = 8
DEFAULT_MAX_FILES = 200_000  # per rule

_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
_LOCAL_DRIVE_TYPES = frozenset((2, 3, 5, 6))  # GetDriveTypeW: removable, fixed, CD-ROM, RAM disk (4 = network)
_RESERVED = frozenset(["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"] + ["COM%d" % i for i in range(1, 10)]
                      + ["LPT%d" % i for i in range(1, 10)])


def base_name(path):
    """The last part of a stored path, with both separators 3ds Max may write."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


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
    if any(p.split(".", 1)[0].rstrip(" ").upper() in _RESERVED for p in parts):
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


def _plain_file(path):
    """A regular file that is neither a link nor a reparse point, checked without following either."""
    try:
        st = os.lstat(path)
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(st.st_mode) and not getattr(st, "st_file_attributes", 0) & _REPARSE_POINT


def _entries(folder):
    try:
        with os.scandir(folder) as it:
            return sorted(it, key=lambda e: e.name)
    except (OSError, ValueError):
        return []


def _plain_dir(entry):
    """A folder, neither a link nor a junction."""
    try:
        return (entry.is_dir(follow_symlinks=False)
                and not getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & _REPARSE_POINT)
    except OSError:
        return False


class Found(collections.namedtuple("Found", "path rule")):
    """A texture file on disk and the rule (SCENE, SIBLING, USER, ORIGINAL) that found it."""
    __slots__ = ()


class TextureReport:
    """What the lookups of one import found: files per rule and the names not found, each name counted once."""

    def __init__(self):
        self.found = dict.fromkeys(RULES, 0)
        self.truncated = []  # (folder, max_files) where a walk stopped
        self._seen = set()
        self._missing = {}

    def add(self, name, found):
        key = name_key(name)
        if key in self._seen:
            return
        self._seen.add(key)
        if found is None:
            self._missing[key] = name or "(no file name)"
        else:
            self.found[found.rule] += 1

    @property
    def missing(self):
        """The file names not found, sorted, each once."""
        return [self._missing[k] for k in sorted(self._missing)]

    def lines(self):
        total = sum(self.found.values())
        out = ["Textures found: %d (%s)" % (total, ", ".join(
            "%s %d" % (RULE_NAMES[r], self.found[r]) for r in RULES))]
        missing = self.missing
        if missing:
            out.append("Textures not found: %d: %s" % (len(missing), ", ".join(missing)))
        out.extend("Texture search stopped after %d files in %s" % (n, folder) for folder, n in self.truncated)
        return out


class TextureIndex:
    """The texture lookup of one import: each rule's folders walked once, on first need."""

    def __init__(self, scene_path, user_dirs=(), scene_subfolders=False, max_depth=DEFAULT_MAX_DEPTH,
                 max_files=DEFAULT_MAX_FILES, is_local_drive=is_local_drive):
        self.scene_dir = os.path.dirname(os.path.abspath(scene_path))
        self.user_dirs = list(dict.fromkeys(os.path.abspath(d) for d in user_dirs))
        self.scene_subfolders = scene_subfolders
        self.max_depth, self.max_files = max_depth, max_files
        self._is_local_drive = is_local_drive
        self._tiers = {}
        self._cache = {}
        self.report = TextureReport()

    def _roots(self, rule):
        if rule == SCENE:
            return [(self.scene_dir, self.scene_subfolders)]
        if rule == SIBLING:
            roots = []
            for folder in dict.fromkeys((self.scene_dir, os.path.dirname(self.scene_dir))):
                roots.extend((e.path, True) for e in _entries(folder)
                             if name_key(e.name) in SIBLING_NAMES and _plain_dir(e))
            return roots
        return [(d, True) for d in self.user_dirs]

    def _tier(self, rule):
        index = self._tiers.get(rule)
        if index is None:
            index = self._tiers[rule] = {}
            budget = [self.max_files]
            for root, recursive in self._roots(rule):
                self._walk(root, recursive, index, budget)
        return index

    def _walk(self, root, recursive, index, budget):
        queue = collections.deque([(root, 0)])
        while queue:
            folder, depth = queue.popleft()
            for e in _entries(folder):
                try:
                    if e.is_file(follow_symlinks=False):
                        if budget[0] <= 0:
                            self.report.truncated.append((root, self.max_files))
                            return
                        budget[0] -= 1
                        index.setdefault(name_key(e.name), e.path)
                    elif recursive and depth < self.max_depth and _plain_dir(e):
                        queue.append((e.path, depth + 1))
                except OSError:
                    continue

    def _find(self, path, resolved):
        name = base_name(path) or base_name(resolved)
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
            self.report.add(base_name(path) or base_name(resolved), found)
        return self._cache[key]
