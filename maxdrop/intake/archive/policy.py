# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What a pack may hold: kinds by magic bytes, the name policy, the limits and the errors."""
import dataclasses
import errno
import os
import re
import time
import unicodedata
from typing import Optional

from ... import pathnames
from ...reader.errors import MaxFileError


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
# A folder a clear of a stale reservation took aside and could not put back: another unpack had filled it anew (it
# may hold a complete scene), so it is never removed as stale staging; only a stale reservation of the pack an
# unpack writes is cleared from it (_clear_reclaimed), as from a destination.
RECLAIM_PREFIX = ".maxdrop-reclaim-"
# The staging name a clear of a stale reservation takes a folder aside under (see _clear_stale_reservation).
_TAKEN_ASIDE = STAGING_PREFIX + "reclaim-"
# A rename that never replaces its target (_noreplace): Linux renameat2 relative to the working directory, as
# os.rename, and macOS renamex_np.
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 0x4
# Its errors when the kernel (ENOSYS) or the file system (EINVAL, ENOTSUP / EOPNOTSUPP) has no such rename.
_NOREPLACE_UNSUPPORTED = frozenset(
    e for e in (errno.ENOSYS, errno.EINVAL, getattr(errno, "ENOTSUP", None), getattr(errno, "EOPNOTSUPP", None))
    if e is not None)
_NOREPLACE = []  # [the rename, or None], loaded on first use

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
# Likewise refused everywhere: APFS refuses a name with an unassigned code point (noncharacters included) or bytes
# that are not UTF-8 (EILSEQ), and off Windows a lone surrogate outside surrogateescape's range has no bytes.
# "Unassigned" follows this Python's Unicode tables (14.0 on 3.11, 15.1 on 3.13), older than APFS's: a map named
# with a newer character is skipped and reported, also where it could be stored.
_UNSTORABLE = frozenset(("Cn", "Cs"))

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


class PackError(MaxFileError):
    """The one error of this module; its message tells the user what to do."""


class Cancelled(PackError):
    """The unpack was stopped by its watch (unpack(watch=...)): the user cancelled the import."""

    def __init__(self, message="Unpacking was cancelled."):
        super().__init__(message)


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

    def __init__(self, limits, watch=None):
        self.limits = limits
        self.watch = watch
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

    def check_time(self, seen=None):
        """seen: the bytes written so far when total does not count them yet (a program writing them)."""
        if self.watch is not None:
            self.watch(self.total if seen is None else seen)
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
    if any(unicodedata.category(c) in _UNSTORABLE for c in base):
        return "unassigned or unpaired Unicode character"
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
