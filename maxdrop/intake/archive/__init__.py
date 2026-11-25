# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene packs: list an archive and unpack the chosen .max with its maps into a flat folder.

A name stored in an archive never decides where a file is written. Of every entry only the base name is used, it
must pass the name policy (refused_reason) and the allow-list (the chosen .max, images, .ies), and the output is
flat: the .max and its maps side by side. Directory parts only rank duplicates. Everything is written into a
staging folder beside the destination; once complete, the destination is created (never an existing folder) and
the files move into it, the marker last. Staging is removed on any failure, and one a crash left behind is removed
by a later unpack (unless it is a folder a clear took aside holding more than a stale folder can: kept under a
reclaim name). A destination holds a reservation file while the files move in: one a crash left (old, of the
same pack, no marker, no .max yet, nothing but the maps it lists) is cleared by a later unpack of that pack, which
takes the name again unless a later folder serves. A destination, and the folder of a several-scene pack, is made
under a staging name already holding its reservation file (or marker) and renamed into place: a crash does not
leave it empty (unless the rename is refused, when it is made and filled as before). A folder such a clear took
aside and found filled anew by another unpack goes back to its name; when that name is taken or the rename is
refused, it is kept under a reclaim name, which a later unpack of the pack clears only once it holds a stale
reservation, as a destination.

Formats are recognised by their magic bytes. A backend lists the entries (names) and writes chosen entries into
the staging folder (extract); the rules here are the same for every backend. Of the add-on it imports only
external.py and the bpy-free pathnames.py and reader/errors.py (PackError is a MaxFileError): the tests load it
under a package of their own, without the add-on's __init__ (which needs bpy).
"""

import dataclasses
import errno
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

from ... import pathnames
from ...reader.errors import MaxFileError
from .. import external as _external

from .policy import (
    KIND_ZIP, KIND_RAR, KIND_7Z, _MAGIC, MARKER, MARKER_FORMAT, RESERVATION, STAGING_PREFIX, RECLAIM_PREFIX,
    _TAKEN_ASIDE, _AT_FDCWD, _RENAME_NOREPLACE, _RENAME_EXCL, _NOREPLACE_UNSUPPORTED, _NOREPLACE, IMAGE_EXTENSIONS,
    ASSET_EXTENSIONS, SCENE_EXTENSION, MAX_NAME_LENGTH, _NAME_UNITS_MAX, _FORBIDDEN, _UNSTORABLE, ZIP_NAME_GUESSES,
    _COPY_DEPTH, _COPY_VISIT_MAX, _CANDIDATES, _STALE_SECONDS, _RESERVATION_STALE_SECONDS, _RACE_RETRIES, _CHUNK,
    _MARKER_READ_MAX, _BY_HAND_TAIL, _BY_HAND, PackError, Cancelled, password_message, Limits, DEFAULT_LIMITS,
    _size_text, _Budget, _SEP, Entry, kind, refused_reason, extension, name_key, _skip_key,
)
from .zips import (
    _ZIP_FLAG_ENCRYPTED, _ZIP_FLAG_PATCHED, _ZIP_FLAG_STRONG, _ZIP_FLAG_UTF8, _WIN_DIRECTORY, _WIN_REPARSE_POINT,
    _WIN_LINK_TAGS, _EOCD, _EOCD64_LOCATOR, _EOCD64, _CENTRAL_HEAD, _zip_methods, _zip_unicode_path, zip_name,
    _zip_regular, _zip_unsupported, _zip_entry_count, ZipBackend, _BACKENDS,
)
from .folders import (
    _read_marker, _wanted_at, _marker_matches, _write_marker, _write_reservation, _stale_reservation,
    _clear_stale_reservation, _noreplace, _load_noreplace, _noreplace_failed, _rename_new, _make, _create, _is_link,
    _find_copy, _candidates, _probe, _safe_stem, _offer, _destination, _no_free_folder, _reserve, _only_marker,
    _refilled, _remove_stale_staging, _clear_reclaimed,
)
from .unpacking import (
    backend_for, _read_entries, _listed_by, _is_scene, PackListing, list_pack, UnpackResult, _rank, _select, _ident,
    preview, _check_space, _check_staging, _refuse_unreadable, unpack,
)

# .rar and .7z go through a program already on the computer (external.py), which registers itself here.
_external.install(sys.modules[__name__])
