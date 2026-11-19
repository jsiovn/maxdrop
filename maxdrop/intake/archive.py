# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene packs: list an archive and unpack the chosen .max with its maps into a flat folder.

A name stored in an archive never decides where a file is written. Of every entry only the base name is used, it
must pass the name policy (refused_reason) and the allow-list (the chosen .max, images, .ies), and the output is
flat: the .max and its maps side by side. Directory parts only rank duplicates. Everything is written into a
staging folder beside the destination; once complete, the destination is created (never an existing folder) and
the files move into it, the marker last. Staging is removed on any failure, and one a crash left behind is removed
by a later unpack. A destination holds a reservation file while the files move in: one a crash left (old, of the
same pack, no marker, no .max yet, nothing but the maps it lists) is cleared by a later unpack of that pack, which
takes the name again unless a later folder serves. A crash right after creating the destination, before the
reservation file, still leaves an empty folder that keeps its name; so does one between the folder of a
several-scene pack and its marker.

Formats are recognised by their magic bytes. A backend lists the entries (names) and writes chosen entries into
the staging folder (extract); the rules here are the same for every backend. Of the add-on it imports only
external.py and the bpy-free pathnames.py: the tests load it under a package of their own, without the add-on's
__init__ (which needs bpy).
"""

import dataclasses
import json
import os
import re
import shutil
import stat
import struct
import sys
import tempfile
import time
import unicodedata
import zipfile
import zlib
from typing import Dict, List, Optional, Tuple

from .. import pathnames
from . import external as _external

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
# Lives in a destination only while the files move in: see _stale_reservation.
RESERVATION = ".maxdrop-reserved.json"
STAGING_PREFIX = ".maxdrop-staging-"

IMAGE_EXTENSIONS = frozenset((
    "jpg", "jpeg", "png", "tif", "tiff", "tga", "bmp", "gif", "exr", "hdr", "psd", "dds", "webp", "jp2", "tx"))
ASSET_EXTENSIONS = IMAGE_EXTENSIONS | {"ies"}
SCENE_EXTENSION = "max"

MAX_NAME_LENGTH = 200
# NTFS stores 255 UTF-16 units per name, ext4 and APFS 255 UTF-8 bytes: a name within 200 characters can still
# exceed either.
_NAME_UNITS_MAX = 255
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
# An unpack is stopped after Limits.seconds (15 minutes by default): a staging folder untouched for this long was
# left by one that never finished.
_STALE_SECONDS = 6 * 3600
# A reservation lives only while files move within one volume (seconds): one this old was left by a crash. An hour
# leaves room for slow network shares and clock skew between the computer and a file server.
_RESERVATION_STALE_SECONDS = 3600
# Times a pack folder another unpack created first sends the destination search round again.
_RACE_RETRIES = 3
_CHUNK = 1 << 20
# A marker lists the asset names a filtered unpack wrote for: thousands of escaped CJK names fit.
_MARKER_READ_MAX = 4 << 20

_BY_HAND_TAIL = "Extract the archive by hand and import the .max from that folder."
_BY_HAND = "%s: MaxDrop cannot read it. " + _BY_HAND_TAIL


class PackError(Exception):
    """The one error of this module; its message tells the user what to do."""


def password_message(path):
    """The one message for a pack with a password, whichever backend found it and on which entry."""
    return "%s is password-protected: MaxDrop does not ask for passwords. %s" % (os.path.basename(path),
                                                                                 _BY_HAND_TAIL)


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
    if n < 1024:
        return "%d bytes" % n
    for unit in ("KiB", "MiB", "GiB"):
        n /= 1024.0
        if n < 1024 or unit == "GiB":
            return "%.1f %s" % (n, unit)


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
            raise PackError("The pack holds more files to unpack than the %d MaxDrop writes from one pack. "
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
    if pathnames.is_reserved(base):
        return "reserved device name"
    if base[-1] in ". ":
        return "ends in a dot or a space"
    if (len(base) > MAX_NAME_LENGTH or len(base.encode("utf-16-le", "surrogatepass")) // 2 > _NAME_UNITS_MAX
            or len(base.encode("utf-8", "surrogatepass")) > _NAME_UNITS_MAX):
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


_ZIP_FLAG_ENCRYPTED = 0x1
_ZIP_FLAG_PATCHED = 0x20
_ZIP_FLAG_STRONG = 0x40
_ZIP_FLAG_UTF8 = 0x800
_WIN_DIRECTORY = 0x10
_WIN_REPARSE_POINT = 0x400
# IO_REPARSE_TAG_MOUNT_POINT (a junction) and IO_REPARSE_TAG_SYMLINK. Not every reparse point: OneDrive
# placeholders are reparse points too, and are plain folders to the user.
_WIN_LINK_TAGS = (0xA0000003, 0xA000000C)

_EOCD = struct.Struct("<4s4H2LH")
_EOCD64_LOCATOR = struct.Struct("<4sLQL")
_EOCD64 = struct.Struct("<4sQ2H2L4Q")
_CENTRAL_HEAD = 46


def _zip_methods():
    methods = {zipfile.ZIP_STORED: "", zipfile.ZIP_DEFLATED: ""}
    if getattr(zipfile, "bz2", None) is not None:
        methods[zipfile.ZIP_BZIP2] = ""
    if getattr(zipfile, "lzma", None) is not None:
        methods[zipfile.ZIP_LZMA] = ""
    return methods


def _zip_unicode_path(extra, raw):
    """The name of an Info-ZIP Unicode Path extra field (0x7075) that matches the raw name, else None. Only
    Python 3.13 applies it itself; reading it here gives every Blender the same names for well-formed fields (a
    malformed one is ignored here but makes Python 3.13 refuse the archive)."""
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


def _zip_entry_count(path, cap):
    """The entries of a zip, without building them: the count its end record declares (zip64 too), or the
    records of its central directory counted one by one when that is more (zipfile walks the directory by its
    size, so a count can lie). Stops counting above cap; 0 when the end record is not found (zipfile then says
    what is wrong)."""
    with open(path, "rb") as f:
        size = f.seek(0, 2)
        tail_len = min(size, _EOCD.size + 0xFFFF)
        f.seek(size - tail_len)
        tail = f.read(tail_len)
        pos = tail.rfind(b"PK\x05\x06")
        if pos < 0 or len(tail) - pos < _EOCD.size:
            return 0
        eocd_at = size - tail_len + pos
        declared, cd_size = _EOCD.unpack_from(tail, pos)[4:6]
        end = eocd_at
        # As zipfile: the zip64 locator lies right before the end record, the zip64 record right before it. Newer
        # Pythons check more of these records; a count here only refuses early, zipfile still judges the archive.
        if eocd_at >= _EOCD64_LOCATOR.size + _EOCD64.size:
            f.seek(eocd_at - _EOCD64_LOCATOR.size - _EOCD64.size)
            head = f.read(_EOCD64.size + _EOCD64_LOCATOR.size)
            if head[:4] == b"PK\x06\x06" and head[_EOCD64.size:_EOCD64.size + 4] == b"PK\x06\x07":
                declared, cd_size = _EOCD64.unpack_from(head)[7:9]
                end = eocd_at - _EOCD64_LOCATOR.size - _EOCD64.size
        if declared > cap or cd_size > end:
            return declared
        # From the end, not from the stored offset: data before the archive (a self-extractor) shifts that.
        at = f.seek(end - cd_size)
        count = 0
        while at + _CENTRAL_HEAD <= end:
            head = f.read(_CENTRAL_HEAD)
            if len(head) < _CENTRAL_HEAD or head[:4] != b"PK\x01\x02":
                break
            count += 1
            if count > cap:
                break
            at = f.seek(sum(struct.unpack_from("<3H", head, 28)), 1)
        return max(declared, count)


class ZipBackend:
    name = "zipfile"

    def entry_count(self, path, cap):
        """Read before names(): ZipFile builds every entry of the directory at once."""
        try:
            return _zip_entry_count(path, cap)
        except (OSError, struct.error):
            return 0

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
        """Write each (entry, target base name) of wanted into staging/<target>; returns the label of what wrote
        them. Never extract(): the names stored in the archive are not used."""
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
                except NotImplementedError as e:  # a RuntimeError too: first
                    raise PackError(_BY_HAND % ("%s needs %s" % (entry.name, e))) from None
                except RuntimeError:  # zipfile: an encrypted entry and no password
                    raise PackError(password_message(path)) from None
                except Exception as e:  # damaged data (CRC, zlib, bz2, lzma) or a failed write
                    raise PackError("Could not unpack %s (%s). Extract the archive by hand." % (entry.name, e)) \
                        from None
        return self.name


_BACKENDS = {KIND_ZIP: ZipBackend()}

# .rar and .7z go through a program already on the computer (external.py), which registers itself here.
_external.install(sys.modules[__name__])


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
    return files + [reservation.path]


def _clear_stale_reservation(folder, ident):
    """Remove a stale reservation; False when the folder stays. It is first renamed to a staging name: of two
    unpacks clearing it at once only one rename succeeds, and nothing else writes into the renamed folder, so it
    is judged again there and only what that scan found is removed (the reservation file last). A folder no longer
    stale by then (cleared and made anew meanwhile) is renamed back; should that fail it stays a staging folder,
    removed as stale later like any other."""
    if _stale_reservation(folder, ident) is None:
        return False
    moved = os.path.join(os.path.dirname(folder), STAGING_PREFIX + "reclaim-" + os.urandom(6).hex())
    try:
        os.rename(folder, moved)
    except OSError:
        return False
    files = _stale_reservation(moved, ident)
    try:
        if files is None:
            os.rename(moved, folder)
            return False
        for file in files:
            os.remove(file)
        os.rmdir(moved)
    except OSError:
        pass  # a staging folder now: the name is free all the same
    return not os.path.lexists(folder)


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


def _reserve(path, folders, ident):
    """Create the first of folders that does not exist yet. One that appeared since _destination looked (another
    unpack of the same pack, or anything else) is never written into: the next name is taken. A stale reservation
    is cleared and its name taken again."""
    for folder in folders:
        try:
            os.mkdir(folder)
        except FileExistsError:
            if not _clear_stale_reservation(folder, ident):
                continue
            try:
                os.mkdir(folder)
            except OSError:  # made again meanwhile, or still pending delete (Windows)
                continue
        return folder
    raise _no_free_folder(path, os.path.dirname(folders[0]))


def _only_marker(folder):
    try:
        return set(os.listdir(folder)) <= {MARKER}
    except OSError:
        return False


def _remove_stale_staging(parent, limits):
    """Remove the staging folders of unpacks that never finished (Blender stopped mid-way): only real folders
    (not links) named with STAGING_PREFIX and untouched for a long time. Nothing else in parent is looked at.
    Best effort."""
    cutoff = time.time() - max(_STALE_SECONDS, 2 * limits.seconds)
    try:
        with os.scandir(parent) as it:
            stale = [item.path for item in it if item.name.startswith(STAGING_PREFIX)]
    except OSError:
        return
    for folder in stale:
        try:
            st = os.lstat(folder)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode) and not _is_link(folder) and st.st_mtime < cutoff:
            shutil.rmtree(folder, ignore_errors=True)


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


def unpack(path, scene=None, dest_parent=None, limits=DEFAULT_LIMITS, wanted=None, references=None):
    """Unpack the scene (its archive path, as list_pack gives it; may be None when the pack holds one) with its
    maps. wanted: optional set of name_key() base names; when given, only those assets are written. references:
    instead of wanted, a callable asked about a .max path that returns the base names of the files that scene
    uses, or None for every asset. It is asked about the scene once written into the staging folder (the maps
    follow), or about the .max of an earlier unpack that may be used again; it must leave no file open.

    The destination is <dest_parent>/<archive stem>/, or <dest_parent>/<archive stem>/<scene stem>/ when the pack
    holds several scenes; dest_parent defaults to the archive's folder.
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
        while container is not None:
            try:
                os.mkdir(container)
            except FileExistsError:
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
            _write_marker(container, ident, None, 0)
            break
        parent = os.path.dirname(folder)
        _remove_stale_staging(parent, limits)
        staging = tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=parent)
        reserved = None
        budget = _Budget(limits)
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
            reserved = _reserve(path, folders, ident)
            _write_reservation(reserved, ident, [t for _e, t in plan[1:]])
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
