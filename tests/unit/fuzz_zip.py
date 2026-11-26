# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scene-pack side of the fuzz harness: zip seeds, mutations, cases and the unpack run on them."""
import os
import random
import struct
import time
import zipfile

from .fuzz_common import _extreme, _mod, _pick, _put32, _region_offset, _remove, _rng, Escaped, SEED


# --- zip -----------------------------------------------------------------------------------------------------------

_ZIP_KINDS = (("flip", 20), ("field", 25), ("names", 15), ("cut", 6), ("method", 8), ("flags", 8), ("attr", 6),
              ("eocd", 8), ("multi", 4))
_RISKY_NAMES = ("../evil.jpg", "..\\evil.jpg", "/abs.png", "\\abs.png", "C:\\x\\a.jpg", "C:a.jpg", "\\\\host\\s\\a.jpg",
                "a/../../b.png", "con.jpg", "AUX", "nul.max", "COM1.tga", "lpt9.png", "a:b.jpg", "a\x00b.jpg",
                "x\x01.png", "dots....", "space .jpg ", "tail.", "", ".", "..", "/", "a/", "maps/./c.jpg",
                "\u202egpj.exe", "\uff0e\uff0e\uff0fx.jpg", "x" * 300 + ".jpg", "\ud800.jpg", "scene.MAX",
                "sub/scene.max", "Scene Pack/scene.max", "a\\b\\c.ies", "COM\u00b9.png", "\u00e9t\u00e9.jpg",
                "\u6587\u4ef6.png", "?.jpg", "*.png", "a|b.jpg", "<x>.png", "q\".jpg", "trail/ ")
_ZIP_FIELDS_LOCAL = ((4, 2), (6, 2), (8, 2), (14, 4), (18, 4), (22, 4), (26, 2), (28, 2))
_ZIP_FIELDS_CENTRAL = ((4, 2), (6, 2), (8, 2), (10, 2), (16, 4), (20, 4), (24, 4), (28, 2), (30, 2), (32, 2),
                       (34, 2), (36, 2), (38, 4), (42, 4))
_ZIP_FIELDS_EOCD = ((4, 2), (6, 2), (8, 2), (10, 2), (12, 4), (16, 4), (20, 2))


def _zip_bytes(files):
    """A zip of (name, data, compression, external_attr) built in memory with fixed dates."""
    import io
    import warnings
    out = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(out, "w") as z:
        warnings.simplefilter("ignore")  # a duplicate name is a case, not a mistake
        for name, data, method, attr in files:
            info = zipfile.ZipInfo("placeholder", date_time=(2020, 1, 1, 0, 0, 0))
            info.filename = name
            info.compress_type = method
            info.external_attr = attr
            z.writestr(info, data)
    return out.getvalue()


def _payload(rng, n):
    return bytes(rng.getrandbits(8) for _ in range(n // 2)) + b"MaxDrop fuzz " * (n // 26)


class ZipSeed:
    """A scene pack built here: its files and where its structures lie."""

    def __init__(self, name):
        self.name = name
        rng = random.Random(name)
        regular = 0o100644 << 16
        files = [("Scene Pack/scene.max", _payload(rng, 4000), zipfile.ZIP_DEFLATED, regular),
                 ("Scene Pack/maps/", b"", zipfile.ZIP_STORED, (0o40755 << 16) | 0x10),
                 ("Scene Pack/maps/wood.jpg", _payload(rng, 1500), zipfile.ZIP_STORED, regular),
                 ("Scene Pack/maps/sub/stone.png", _payload(rng, 2000), zipfile.ZIP_DEFLATED, regular),
                 ("Scene Pack/light.ies", b"IESNA:LM-63-2002\n" * 20, zipfile.ZIP_DEFLATED, regular),
                 ("readme.txt", b"read me\n" * 30, zipfile.ZIP_DEFLATED, regular)]
        if name == "zip:two":
            files += [("Other/second.max", _payload(rng, 3000), zipfile.ZIP_DEFLATED, regular),
                      ("Other/maps/wood.jpg", _payload(rng, 800), zipfile.ZIP_STORED, regular)]
        self.files = files
        self.raw = _zip_bytes(files)
        self._index()

    def _index(self):
        raw = self.raw
        eocd = raw.rindex(b"PK\x05\x06")
        self.eocd = eocd
        count, size, start = struct.unpack_from("<HII", raw, eocd + 10)
        self.central, self.local, self.names = [], [], []
        pos = start
        for _ in range(count):
            nlen, xlen, clen = struct.unpack_from("<HHH", raw, pos + 28)
            local = struct.unpack_from("<I", raw, pos + 42)[0]
            self.central.append(pos)
            self.local.append(local)
            self.names.append((pos + 46, nlen))
            lnlen = struct.unpack_from("<H", raw, local + 26)[0]
            self.names.append((local + 30, lnlen))
            pos += 46 + nlen + xlen + clen
        self.regions = {"local": [(0, start)], "central": [(start, size)], "eocd": [(eocd, len(raw) - eocd)]}


def _mutate_zip(seed, buf, rng, kind):
    if kind == "flip":
        region = _pick(rng, [("local", 2), ("central", 5), ("eocd", 1)])
        offs = [_region_offset(rng, seed.regions[region]) for _ in range(rng.randint(1, 6))]
        for off in offs:
            buf[off] ^= 1 << rng.randrange(8)
        return "flip %s %s" % (region, offs)
    if kind == "field":
        if rng.random() < 0.6:
            at, (field, size) = rng.choice(seed.central), rng.choice(_ZIP_FIELDS_CENTRAL)
        else:
            at, (field, size) = rng.choice(seed.local), rng.choice(_ZIP_FIELDS_LOCAL)
        value = _extreme(rng) if size == 4 else rng.choice((0, 1, 0x7FFF, 0x8000, 0xFFFF, rng.randrange(1 << 16)))
        buf[at + field:at + field + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
        return "field %d+%d=0x%X" % (at, field, value)
    if kind == "eocd":
        field, size = rng.choice(_ZIP_FIELDS_EOCD)
        value = _extreme(rng) if size == 4 else rng.choice((0, 1, 2, 0xFFFF, rng.randrange(1 << 16)))
        at = seed.eocd + field
        buf[at:at + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
        return "eocd +%d=0x%X" % (field, value)
    if kind == "cut":
        n = rng.randrange(len(buf))
        del buf[n:]
        return "cut %d" % n
    if kind == "method":
        at = rng.choice(seed.central + seed.local)
        value = rng.choice((0, 1, 6, 8, 9, 12, 14, 19, 93, 95, 98, 99, 0xFFFF))
        field = at + (10 if at in seed.central else 8)
        buf[field:field + 2] = value.to_bytes(2, "little")
        return "method %d=%d" % (field, value)
    if kind == "flags":
        at = rng.choice(seed.central + seed.local)
        field = at + (8 if at in seed.central else 6)
        value = rng.choice((0x1, 0x8, 0x20, 0x40, 0x800, 0x2000, 0xFFFF, rng.randrange(1 << 16)))
        buf[field:field + 2] = value.to_bytes(2, "little")
        return "flags %d=0x%X" % (field, value)
    if kind == "attr":
        at = rng.choice(seed.central)
        value = rng.choice((0o120777 << 16, 0o20644 << 16, 0o60644 << 16, 0o10644 << 16, 0o140644 << 16, 0x10,
                            0x400, 0x410, 0xFFFFFFFF, 0))
        _put32(buf, range(at + 38, at + 42), value)
        return "attr %d=0x%X" % (at + 38, value)
    if kind == "names":
        files = list(seed.files)
        picks = []
        for _ in range(rng.randint(1, 3)):
            i = rng.randrange(len(files))
            name, data, method, attr = files[i]
            new = rng.choice(_RISKY_NAMES)
            if rng.random() < 0.5 and "/" not in new and "\\" not in new:
                new = name.rsplit("/", 1)[0] + "/" + new
            files[i] = (new, data, method, attr)
            picks.append(new)
        if rng.random() < 0.3:  # a name twice
            files.append(files[rng.randrange(len(files))])
        try:
            buf[:] = _zip_bytes(files)
        except (UnicodeEncodeError, ValueError, struct.error):
            return "names %r (not writable)" % picks
        return "names %r" % picks
    raise ValueError(kind)


def zip_case(seed, k, base=SEED):
    rng = _rng(seed.name, k, base)
    buf = bytearray(seed.raw)
    kind = _pick(rng, _ZIP_KINDS)
    if kind == "multi":
        kinds = [_pick(rng, [kw for kw in _ZIP_KINDS[:-1] if kw[0] not in ("names", "cut")])
                 for _ in range(rng.randint(2, 4))]
        spec = "; ".join(_mutate_zip(seed, buf, rng, kd) for kd in kinds)
    else:
        spec = _mutate_zip(seed, buf, rng, kind)
    return bytes(buf), spec


_ARCHIVE = None


def _archive():
    global _ARCHIVE
    if _ARCHIVE is None:
        _ARCHIVE = _mod("intake.archive")
        for k in (_ARCHIVE.KIND_RAR, _ARCHIVE.KIND_7Z):  # no program is ever started
            _ARCHIVE._BACKENDS.pop(k, None)
    return _ARCHIVE


def _tree(folder):
    out = []
    for parent, dirs, files in os.walk(folder):
        rel = os.path.relpath(parent, folder)
        out += [os.path.normpath(os.path.join(rel, d)) + os.sep for d in dirs]
        out += [os.path.normpath(os.path.join(rel, f)) for f in files]
    return sorted(out)


def read_zip(data, sandbox):
    """'ok' or 'refused' for one pack in sandbox (an empty folder); anything else raises. Checks afterwards that
    nothing was written outside sandbox/out and that no staging folder is left."""
    archive = _archive()
    pack, out = os.path.join(sandbox, "pack.zip"), os.path.join(sandbox, "out")
    os.mkdir(out)
    with open(pack, "wb") as f:
        f.write(data)
    outcome, result = "ok", None
    try:
        listing = archive.list_pack(pack)
        if listing.scenes:
            result = archive.unpack(pack, listing.scenes[0], out)
    except archive.PackError:
        outcome = "refused"
    if result is not None and not (os.path.isfile(result.max_path) and os.path.commonpath(
            [os.path.abspath(result.max_path), os.path.abspath(out)]) == os.path.abspath(out)):
        raise AssertionError("unpacked, but its scene is not in the destination: %r" % result.max_path)
    entries = _tree(sandbox)
    stray = [p for p in entries if p not in ("pack.zip", "out" + os.sep) and not p.startswith("out" + os.sep)]
    if stray:
        raise AssertionError("written outside the destination: %r" % stray)
    staging = [p for p in entries if os.path.basename(p.rstrip(os.sep)).startswith(
        (archive.STAGING_PREFIX, archive.RECLAIM_PREFIX))]
    if staging:
        raise AssertionError("staging left behind: %r" % staging)
    for p in entries:
        if p.startswith("out" + os.sep) and not p.endswith(os.sep):
            depth = p.count(os.sep)
            if depth not in (2, 3):  # out/<pack>/<file>, or out/<pack>/<scene>/<file> for a pack of several scenes
                raise AssertionError("a file outside the flat pack folder: %r" % p)
    return outcome


def run_zip(seed, k, folder, base=SEED):
    """(outcome, seconds) of pack case k in a sandbox under folder; Escaped when the case escapes."""
    data, spec = zip_case(seed, k, base)
    sandbox = os.path.join(folder, "case")
    os.mkdir(sandbox)
    start = time.perf_counter()
    try:
        outcome = read_zip(data, sandbox)
    except Exception as e:
        raise Escaped("%s:%d (%s): %s: %s" % (seed.name, k, spec, type(e).__name__, e)) from e
    finally:
        seconds = time.perf_counter() - start
        _remove(sandbox)
    if os.listdir(folder):
        raise Escaped("%s:%d (%s): left %r beside its sandbox" % (seed.name, k, spec, os.listdir(folder)))
    return outcome, seconds


ZIP_SEEDS = ("zip:one", "zip:two")
