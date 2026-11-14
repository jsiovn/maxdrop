# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene packs: list an archive and unpack the chosen .max with its maps into a flat folder.

A name stored in an archive never decides where a file is written. Of every entry only the base name is used, it
must pass the name policy (refused_reason) and the allow-list (the chosen .max, images, .ies), and the output is
flat: the .max and its maps side by side. Directory parts only rank duplicates. Everything is written into a
staging folder beside the destination, which is renamed to the destination once complete and removed on any
failure.

Formats are recognised by their magic bytes. A backend lists the entries (names) and writes chosen entries into
the staging folder (extract); the rules here are the same for every backend. Self-contained on purpose: the tests
load this file by path, without the add-on package (which needs bpy).
"""

import dataclasses
import json
import os
import re
import shutil
import stat
import struct
import tempfile
import time
import unicodedata
import zipfile
import zlib
from collections import Counter
from typing import Dict, List, Optional, Tuple

KIND_ZIP = "zip"
KIND_RAR = "rar"
KIND_7Z = "7z"

# Longest first: RAR 5's signature extends RAR 4's.
_MAGIC = (
    (b"Rar!\x1a\x07\x01\x00", KIND_RAR),
    (b"Rar!\x1a\x07\x00", KIND_RAR),
    (b"7z\xbc\xaf\x27\x1c", KIND_7Z),
    (b"PK\x03\x04", KIND_ZIP),
    (b"PK\x05\x06", KIND_ZIP),  # an empty archive
)

MARKER = ".maxdrop-pack.json"
MARKER_FORMAT = 1
STAGING_PREFIX = ".maxdrop-staging-"

IMAGE_EXTENSIONS = frozenset((
    "jpg", "jpeg", "png", "tif", "tiff", "tga", "bmp", "gif", "exr", "hdr", "psd", "dds", "webp", "jp2", "tx"))
ASSET_EXTENSIONS = IMAGE_EXTENSIONS | {"ies"}
SCENE_EXTENSION = "max"

MAX_NAME_LENGTH = 200
_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
    + ["%s%s" % (p, d) for p in ("COM", "LPT") for d in "123456789¹²³"])
# Besides ":" (an NTFS stream), the characters Windows cannot store in a name: refused everywhere, so that a
# flat write never fails half-way on one system and works on another.
_FORBIDDEN = frozenset(':<>"|?*')

# Names of zip entries without the UTF-8 flag that are not valid UTF-8: the first of these that decodes strictly
# is taken, and the name counts as guessed. Scene packs come mostly from Chinese and Japanese sites, then from
# Western Windows tools; cp437, the format's own default, decodes anything and comes last.
ZIP_NAME_GUESSES = ("gbk", "shift_jis", "cp1252")

# Folders of a user-extracted copy are searched this many levels below the candidate folder.
_COPY_DEPTH = 3
_COPY_VISIT_MAX = 20000
_CANDIDATES = 99
_CHUNK = 1 << 20
_MARKER_READ_MAX = 64 * 1024

_BY_HAND = "%s: MaxDrop cannot read it. Extract the archive by hand and import the .max from that folder."


class PackError(Exception):
    """The one error of this module; its message tells the user what to do."""


@dataclasses.dataclass(frozen=True)
class Limits:
    entries: int = 20000            # entries listed by the archive
    files: int = 5000               # files written from one pack
    file_bytes: int = 4 << 30       # bytes of one written file
    total_bytes: int = 16 << 30     # bytes written from one pack
    seconds: float = 900.0          # wall time of one unpack
    free_margin: int = 512 << 20    # free space left on the destination volume


DEFAULT_LIMITS = Limits()


def _size_text(n):
    for unit in ("bytes", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return ("%d %s" % (n, unit)) if unit == "bytes" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return ""


class _Budget:
    """Counts what is really written: a declared size can lie."""

    def __init__(self, limits):
        self.limits = limits
        self.files = 0
        self.total = 0
        self.current = 0
        self.name = ""
        self.deadline = time.monotonic() + limits.seconds

    def start_file(self, name):
        if self.files >= self.limits.files:
            raise PackError("The pack holds more than %d files to unpack, the most MaxDrop writes from one pack. "
                            "Extract it by hand." % self.limits.files)
        self.files += 1
        self.current = 0
        self.name = name
        self.check_time()

    def add(self, n):
        if self.current + n > self.limits.file_bytes:
            raise PackError("%s is larger than %s, the most MaxDrop unpacks for one file. Extract the archive by "
                            "hand." % (self.name, _size_text(self.limits.file_bytes)))
        if self.total + n > self.limits.total_bytes:
            raise PackError("The pack unpacks to more than %s, the most MaxDrop writes from one pack. Extract it "
                            "by hand." % _size_text(self.limits.total_bytes))
        self.current += n
        self.total += n
        self.check_time()

    def check_time(self):
        if time.monotonic() > self.deadline:
            raise PackError("Unpacking took longer than %d seconds and was stopped. Extract the archive by hand."
                            % self.limits.seconds)


_SEP = re.compile(r"[\\/]")


@dataclasses.dataclass
class Entry:
    """One entry of an archive, as a backend lists it."""
    name: str                       # the path stored in the archive, decoded
    size: Optional[int] = None      # declared size, None when unknown
    is_dir: bool = False
    regular: bool = True            # False for links and other non-regular files
    encrypted: bool = False
    unsupported: str = ""           # why the backend cannot read it, "" when it can
    guessed: bool = False           # the name's encoding was guessed
    key: object = None              # the backend's own handle

    @property
    def base(self):
        return _SEP.split(self.name)[-1]

    @property
    def dirs(self):
        return [p for p in _SEP.split(self.name)[:-1] if p not in ("", ".")]


def kind(path):
    """zip / rar / 7z from the first bytes of the file, None for anything else (the extension is not read)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    for magic, k in _MAGIC:
        if head.startswith(magic):
            return k
    return None


def refused_reason(base):
    """Why a base name is never written, or None when it may be."""
    if base in ("", ".", ".."):
        return "empty or a folder reference"
    if any(unicodedata.category(c) == "Cc" for c in base):
        return "control character"
    if any(c in _FORBIDDEN for c in base):
        return "character Windows cannot store"
    if base.split(".", 1)[0].rstrip(" ").upper() in _RESERVED:
        return "reserved device name"
    if base[-1] in ". ":
        return "ends in a dot or a space"
    if len(base) > MAX_NAME_LENGTH:
        return "longer than %d characters" % MAX_NAME_LENGTH
    return None


def extension(base):
    return base.rsplit(".", 1)[1].casefold() if "." in base else ""


def name_key(base):
    """Equal for names a case-insensitive file system treats as the same file."""
    return unicodedata.normalize("NFC", base).casefold()


def _skip_key(base):
    ext = extension(base)
    return "." + ext if ext else "(no extension)"


# --- zip -------------------------------------------------------------------------------------------------------

_ZIP_FLAG_ENCRYPTED = 0x1
_ZIP_FLAG_PATCHED = 0x20
_ZIP_FLAG_STRONG = 0x40
_ZIP_FLAG_UTF8 = 0x800
_WIN_DIRECTORY = 0x10
_WIN_REPARSE_POINT = 0x400


def _zip_methods():
    methods = {zipfile.ZIP_STORED: "", zipfile.ZIP_DEFLATED: ""}
    if getattr(zipfile, "bz2", None) is not None:
        methods[zipfile.ZIP_BZIP2] = ""
    if getattr(zipfile, "lzma", None) is not None:
        methods[zipfile.ZIP_LZMA] = ""
    return methods


def _zip_unicode_path(extra, raw):
    """The name of an Info-ZIP Unicode Path extra field (0x7075) that matches the raw name, else None. Only
    Python 3.13 applies it itself; reading it here gives every Blender the same names."""
    pos = 0
    while pos + 4 <= len(extra):
        tp, ln = struct.unpack_from("<HH", extra, pos)
        data = extra[pos + 4:pos + 4 + ln]
        pos += 4 + ln
        if tp != 0x7075 or len(data) < 5 or len(data) != ln:
            continue
        version, crc = struct.unpack_from("<BL", data, 0)
        if version == 1 and crc == zlib.crc32(raw):
            try:
                name = data[5:].decode("utf-8")
            except UnicodeDecodeError:
                return None
            return name or None
    return None


def zip_name(info):
    """(name, guessed) of a ZipInfo, from the raw bytes stored in the archive."""
    if info.flag_bits & _ZIP_FLAG_UTF8:
        return info.orig_filename, False
    try:
        raw = info.orig_filename.encode("cp437")
    except UnicodeEncodeError:  # opened with another metadata_encoding
        return info.orig_filename, False
    name = _zip_unicode_path(info.extra, raw)
    if name is not None:
        return name, False
    try:
        return raw.decode("utf-8"), False
    except UnicodeDecodeError:
        pass
    for encoding in ZIP_NAME_GUESSES:
        try:
            return raw.decode(encoding), True
        except UnicodeDecodeError:
            continue
    return raw.decode("cp437"), True


def _zip_regular(info):
    file_type = stat.S_IFMT(info.external_attr >> 16)
    if file_type and file_type != stat.S_IFREG:
        return False
    return not info.external_attr & (_WIN_DIRECTORY | _WIN_REPARSE_POINT)


def _zip_unsupported(info, methods):
    if info.flag_bits & (_ZIP_FLAG_STRONG | _ZIP_FLAG_PATCHED):
        return "uses a zip feature Python cannot read"
    if info.compress_type not in methods:
        return "uses compression method %d, which Python cannot read" % info.compress_type
    return ""


class ZipBackend:
    name = "zipfile"

    def _open(self, path):
        label = os.path.basename(path)
        try:
            return zipfile.ZipFile(path)
        except zipfile.BadZipFile as e:
            if "multiple disks" in str(e):
                raise PackError(_BY_HAND % ("%s is split over several parts" % label)) from None
            raise PackError("%s is not a readable .zip archive (%s)." % (label, e)) from None
        except NotImplementedError as e:
            raise PackError(_BY_HAND % ("%s needs %s" % (label, e))) from None
        except (OSError, ValueError, struct.error) as e:
            raise PackError("%s could not be read (%s)." % (label, e)) from None

    def names(self, path):
        methods = _zip_methods()
        with self._open(path) as zf:
            infos = zf.infolist()
        if any(info.volume for info in infos):
            raise PackError(_BY_HAND % ("%s is split over several parts" % os.path.basename(path)))
        entries = []
        for index, info in enumerate(infos):
            name, guessed = zip_name(info)
            entries.append(Entry(
                name=name, size=info.file_size, is_dir=name.endswith(("/", "\\")), regular=_zip_regular(info),
                encrypted=bool(info.flag_bits & _ZIP_FLAG_ENCRYPTED), unsupported=_zip_unsupported(info, methods),
                guessed=guessed, key=index))
        return entries

    def extract(self, path, wanted, staging, budget):
        """Write each (entry, target base name) of wanted into staging/<target>. Never extract(): the names
        stored in the archive are not used."""
        with self._open(path) as zf:
            infos = zf.infolist()
            for entry, target in wanted:
                budget.start_file(target)
                try:
                    with zf.open(infos[entry.key]) as src, open(os.path.join(staging, target), "xb") as out:
                        while True:
                            chunk = src.read(_CHUNK)
                            if not chunk:
                                break
                            budget.add(len(chunk))
                            out.write(chunk)
                except PackError:
                    raise
                except RuntimeError:
                    raise PackError(_BY_HAND % ("%s is encrypted" % entry.name)) from None
                except NotImplementedError as e:
                    raise PackError(_BY_HAND % ("%s needs %s" % (entry.name, e))) from None
                except Exception as e:  # damaged data (CRC, zlib, bz2, lzma) or a failed write
                    raise PackError("Could not unpack %s (%s). Extract the archive by hand." % (entry.name, e)) \
                        from None


_BACKENDS = {KIND_ZIP: ZipBackend()}


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
    entries = backend.names(path)
    if len(entries) > limits.entries:
        raise PackError("%s lists %d entries, more than the %d MaxDrop reads. Extract it by hand."
                        % (os.path.basename(path), len(entries), limits.entries))
    return entries


def _is_scene(e):
    return (not e.is_dir and e.regular and extension(e.base) == SCENE_EXTENSION
            and refused_reason(e.base) is None)


# --- listing ---------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class PackListing:
    kind: str
    backend: str
    scenes: List[str]               # archive paths of the .max entries, in archive order
    assets: int                     # image and .ies entries with a valid name
    skipped: int                    # entries never written, whatever the scene
    problems: List[str]
    encrypted: List[str]
    guessed: List[str]


def list_pack(path, limits=DEFAULT_LIMITS):
    """The scenes of a pack and what unpacking would skip. Reads the archive's directory only."""
    k, backend = backend_for(path)
    entries = _read_entries(backend, path, limits)
    scenes, assets, skipped = [], 0, 0
    for e in entries:
        if e.is_dir:
            continue
        if _is_scene(e):
            scenes.append(e.name)
        elif e.regular and refused_reason(e.base) is None and extension(e.base) in ASSET_EXTENSIONS:
            assets += 1
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
    return PackListing(k, backend.name, scenes, assets, skipped, problems, encrypted, guessed)


# --- unpacking -------------------------------------------------------------------------------------------------

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


def _read_marker(folder):
    try:
        with open(os.path.join(folder, MARKER), "rb") as f:
            data = json.loads(f.read(_MARKER_READ_MAX).decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _marker_matches(marker, ident, scene_name):
    return (marker is not None and marker.get("format") == MARKER_FORMAT and marker.get("scene") == scene_name
            and all(marker.get(k) == v for k, v in ident.items()))


def _write_marker(folder, ident, scene_name, files):
    data = dict(ident, format=MARKER_FORMAT, scene=scene_name, files=files)
    with open(os.path.join(folder, MARKER), "x", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)


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
                    if item.is_dir(follow_symlinks=False) and not item.name.startswith(STAGING_PREFIX):
                        below.append(item.path)
                except OSError:
                    continue
        level = below
    return None


def _candidates(parent, name):
    yield os.path.join(parent, name)
    for n in range(2, _CANDIDATES + 1):
        yield os.path.join(parent, "%s (%d)" % (name, n))


def _probe(folder, scene, ident):
    """What a candidate folder offers for the scene: "free", ("reused" | "in_place", .max path), or None (taken:
    never written into)."""
    if not os.path.lexists(folder):
        return "free"
    if os.path.islink(folder) or not os.path.isdir(folder):
        return None
    marker = _read_marker(folder)
    if marker is not None:
        max_path = os.path.join(folder, scene.base)
        if _marker_matches(marker, ident, scene.name) and os.path.isfile(max_path):
            return ("reused", max_path)
        return None
    found = _find_copy(folder, scene.base)
    return ("in_place", found) if found else None


def _safe_stem(name, fallback):
    stem = name[:-len(SCENE_EXTENSION) - 1] if extension(name) == SCENE_EXTENSION else os.path.splitext(name)[0]
    return stem if stem and refused_reason(stem) is None else fallback


def _destination(path, dest_parent, scene, several, ident):
    """("free", folder, container to create or None) or ("reused" | "in_place", .max path)."""
    stem = _safe_stem(os.path.basename(path), "pack")
    if not several:
        for folder in _candidates(dest_parent, stem):
            found = _probe(folder, scene, ident)
            if found == "free":
                return ("free", folder, None)
            if found:
                return found
    else:
        sub = _safe_stem(scene.base, "scene")
        for top in _candidates(dest_parent, stem):
            if not os.path.lexists(top):
                return ("free", os.path.join(top, sub), top)
            if os.path.islink(top) or not os.path.isdir(top):
                continue
            marker = _read_marker(top)
            if marker is None:
                found = _find_copy(top, scene.base)
                if found:
                    return ("in_place", found)
                continue
            if not _marker_matches(marker, ident, None):
                continue
            for folder in _candidates(top, sub):
                found = _probe(folder, scene, ident)
                if found == "free":
                    return ("free", folder, None)
                if found:
                    return found
            break
    raise PackError("No free folder for %s in %s: too many folders of that name exist."
                    % (os.path.basename(path), dest_parent))


def _check_space(entries, folder, limits):
    declared = 0
    for e in entries:
        size = e.size or 0
        if size > limits.file_bytes:
            raise PackError("%s is larger than %s, the most MaxDrop unpacks for one file. Extract the archive by "
                            "hand." % (e.name, _size_text(limits.file_bytes)))
        declared += size
    if declared > limits.total_bytes:
        raise PackError("The pack unpacks to more than %s, the most MaxDrop writes from one pack. Extract it by "
                        "hand." % _size_text(limits.total_bytes))
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return
    if declared + limits.free_margin > free:
        raise PackError("Not enough free space in %s: the scene needs about %s, %s are free."
                        % (folder, _size_text(declared + limits.free_margin), _size_text(free)))


def unpack(path, scene=None, dest_parent=None, limits=DEFAULT_LIMITS, wanted=None):
    """Unpack the scene (its archive path, as list_pack gives it; may be None when the pack holds one) with its
    maps. wanted: optional set of name_key() base names; when given, only those assets are written.

    The destination is <dest_parent>/<archive stem>/, or <dest_parent>/<archive stem>/<scene stem>/ when the pack
    holds several scenes; dest_parent defaults to the archive's folder.
    """
    path = os.path.abspath(path)
    _k, backend = backend_for(path)
    entries = _read_entries(backend, path, limits)
    scenes = [e for e in entries if _is_scene(e)]
    if not scenes:
        raise PackError("%s holds no .max scene." % os.path.basename(path))
    if scene is None and len(scenes) == 1:
        chosen = scenes[0]
    else:
        chosen = next((e for e in scenes if e.name == scene), None)
        if chosen is None:
            raise PackError("%s holds no scene %s." % (os.path.basename(path), scene))
    dest_parent = os.path.abspath(dest_parent or os.path.dirname(path))
    st = os.stat(path)
    ident = {"archive": os.path.basename(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns}

    result = UnpackResult(max_path="", folder="", mode="unpacked", backend=backend.name)
    result.guessed = [e.name for e in entries if e.guessed]
    found = _destination(path, dest_parent, chosen, len(scenes) > 1, ident)
    if found[0] in ("reused", "in_place"):
        result.mode, result.max_path = found
        result.folder = os.path.dirname(result.max_path)
        if result.mode == "reused":
            files = (_read_marker(result.folder) or {}).get("files")
            result.reused = files if isinstance(files, int) else 0
        return result

    _free, folder, container = found
    assets = _select(entries, chosen, None if wanted is None else {name_key(w) for w in wanted}, result)
    plan = [(chosen, chosen.base)] + [(e, e.base) for e in assets]
    for e, _target in plan:
        if e.encrypted:
            raise PackError(_BY_HAND % ("%s is encrypted" % e.name))
        if e.unsupported:
            raise PackError(_BY_HAND % ("%s %s" % (e.name, e.unsupported)))
    if len(plan) > limits.files:
        raise PackError("The scene needs %d files, more than the %d MaxDrop writes from one pack. Extract it by "
                        "hand." % (len(plan), limits.files))
    parent = os.path.dirname(folder)
    _check_space([e for e, _t in plan], container and os.path.dirname(container) or parent, limits)

    created = None
    try:
        if container is not None:
            os.mkdir(container)
            created = container
            _write_marker(container, ident, None, 0)
        staging = tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=parent)
        try:
            backend.extract(path, plan, staging, _Budget(limits))
            # By name_key: a file system may store a name in another Unicode normal form (macOS).
            on_disk = sorted(name_key(n) for n in os.listdir(staging))
            if on_disk != sorted(name_key(t) for _e, t in plan):
                raise PackError("Unpacking %s wrote other files than asked for. Extract it by hand."
                                % os.path.basename(path))
            _write_marker(staging, ident, chosen.name, len(plan))
            os.rename(staging, folder)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    except BaseException as e:
        if created is not None:
            shutil.rmtree(created, ignore_errors=True)
        if isinstance(e, OSError):
            raise PackError("Could not unpack %s into %s (%s)." % (os.path.basename(path), parent, e)) from None
        raise
    result.folder = folder
    result.max_path = os.path.join(folder, chosen.base)
    result.written = len(plan)
    return result
