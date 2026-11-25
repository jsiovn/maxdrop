# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the tests of maxdrop/intake/archive/ share: the zip-only package loaded without Blender, patch_all,
the zip and file helpers and the Base test case."""
import importlib
import importlib.util
import os
import shutil
import struct
import sys
import tempfile
import types
import unittest
import zipfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTAKE = os.path.join(ROOT, "maxdrop", "intake")

# Under a package of its own whose path is maxdrop/: `import maxdrop` would pull bpy, and archive/ imports
# pathnames. Zip only: the .rar and .7z backends archive/ registers are tests/test_intake_external*.py's.
_PKG = "maxdrop_intake_zip_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
archive = importlib.import_module(_PKG + ".intake.archive")
_spec_patching = importlib.util.spec_from_file_location("maxdrop_test_patching",
                                                        os.path.join(ROOT, "tests", "patching.py"))
patching = importlib.util.module_from_spec(_spec_patching)
_spec_patching.loader.exec_module(patching)  # patch_all(): a split package's modules read their own names
for _kind in (archive.KIND_RAR, archive.KIND_7Z):
    archive._BACKENDS.pop(_kind, None)

PackError = archive.PackError


def write_zip(path, files, compression=zipfile.ZIP_DEFLATED):
    """files: (name, data) pairs, or (ZipInfo, data). A name is stored exactly as given (zipfile would turn a
    backslash into a slash on Windows)."""
    with zipfile.ZipFile(path, "w", compression) as z:
        for name, data in files:
            if isinstance(name, zipfile.ZipInfo):
                info = name
            else:
                info = zipfile.ZipInfo("placeholder", date_time=(2020, 1, 1, 0, 0, 0))
                info.filename = name
            info.compress_type = compression
            z.writestr(info, data)
    return path


def patch_entry(path, name, flags=0, method=None, size=None, volume=None):
    """Patch the local header and the central directory record of one entry."""
    with zipfile.ZipFile(path) as z:
        # By the stored name: getinfo() knows a backslash name only as its slash form, on Windows only.
        info = next(i for i in z.infolist() if i.orig_filename == name)
        start = z.start_dir
    raw = info.orig_filename.encode("utf-8" if info.flag_bits & 0x800 else "cp437")
    data = bytearray(read(path))
    local, central = info.header_offset, None
    pos = start
    while data[pos:pos + 4] == b"PK\x01\x02":
        nlen, xlen, clen = struct.unpack_from("<HHH", data, pos + 28)
        if bytes(data[pos + 46:pos + 46 + nlen]) == raw:
            central = pos
            break
        pos += 46 + nlen + xlen + clen
    assert central is not None
    for at, flag_at, method_at, size_at in ((local, 6, 8, 22), (central, 8, 10, 24)):
        struct.pack_into("<H", data, at + flag_at, struct.unpack_from("<H", data, at + flag_at)[0] | flags)
        if method is not None:
            struct.pack_into("<H", data, at + method_at, method)
        if size is not None:
            struct.pack_into("<L", data, at + size_at, size)
    if volume is not None:
        struct.pack_into("<H", data, central + 34, volume)
    write(path, bytes(data))


def replace_bytes(path, old, new):
    assert len(old) == len(new)
    data = read(path)
    assert data.count(old) == 2  # local header and central directory
    write(path, data.replace(old, new))


def to_zip64(path, declared=None):
    """Rewrite a zip with zip64 end records (zipfile writes them only past 65535 entries or 4 GiB): the zip64
    record and its locator before the end record, whose counts then say 0xFFFF. declared: the zip64 count, the
    real one when None."""
    data = read(path)
    at = data.rfind(b"PK\x05\x06")
    n, cd_size, cd_offset = struct.unpack_from("<HLL", data, at + 10)
    n = n if declared is None else declared
    record = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, n, n, cd_size, cd_offset)
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, at, 1)
    end = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF, cd_size, cd_offset, 0)
    write(path, data[:at] + record + locator + end)


def set_declared_count(path, n):
    """The entry counts of the end record (this disk and total), the central directory left as it is."""
    data = bytearray(read(path))
    at = data.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", data, at + 8, n, n)
    write(path, bytes(data))


def junction(target, link):
    """A Windows directory junction, or SkipTest elsewhere."""
    if os.name != "nt":
        raise unittest.SkipTest("junctions exist on Windows only")
    import _winapi
    _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(link))


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data=b""):
    with open(path, "wb") as f:
        f.write(data)


def files_under(root):
    found = set()
    for folder, _dirs, files in os.walk(root):
        found.update(os.path.join(folder, f) for f in files)
    return found


def inside(path, folder):
    return os.path.commonpath([os.path.abspath(path), os.path.abspath(folder)]) == os.path.abspath(folder)


def rename_through_os():
    """Folder renames through os.rename, as the look-then-rename fallback does: a test that patches os.rename to
    see or fail them would otherwise miss them on Linux and macOS, where the rename that never replaces is ctypes'
    (on Windows it is os.rename itself)."""
    return patching.patch_all(archive, "_noreplace", lambda: None)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maxdrop-intake-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = os.path.join(self.tmp, "out")
        os.mkdir(self.out)

    def pack(self, files, name="pack.zip", **kw):
        return write_zip(os.path.join(self.tmp, name), files, **kw)

    def assert_clean(self, before):
        """Nothing written anywhere: no new file, no staging folder left."""
        self.assertEqual(files_under(self.tmp), before)
        for folder, dirs, _files in os.walk(self.tmp):
            for d in dirs:
                self.assertFalse(d.startswith(archive.STAGING_PREFIX), os.path.join(folder, d))

    def listing(self, folder):
        return sorted(os.listdir(folder))
