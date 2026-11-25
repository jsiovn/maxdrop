# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The zip backend: entry names, flags, links, the entry count and ZipBackend."""
import os
import stat
import struct
import zipfile
import zlib

from .policy import _BY_HAND, _CHUNK, Entry, KIND_ZIP, PackError, password_message, ZIP_NAME_GUESSES


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
