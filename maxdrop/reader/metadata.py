# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What a .max file says about itself before it is read: 3ds Max version, renderer, scene totals, plug-ins.

    with CompoundFile(path) as cf:
        info = read(cf)
        info["max_release"], info["max_version"], info["renderer"]["name"], info["counts"]["objects"]

3ds Max writes a DocumentSummaryInformation property set ([MS-OLEPS]) into every file. Its section D5CDD502-...
holds the heading pairs (property 12: a vector of variants, a heading string then an i4 count) that cut the
document parts (property 13: a vector of strings) into groups: General (version, build, saved-as version,
compressed or not), Mesh Totals, Scene Totals, External Dependencies, Objects, Materials, Used Plug-Ins and
Render Data. docs/FORMAT.md lists them as the fixtures show them.

The groups also hold the Windows user and computer name (Render Data), node and material names and file paths:
read() keeps only the facts it names below and never returns any of those. SummaryInformation holds the
thumbnail, dates and the author fields: nothing is taken from it.

read() returns a dict with, each only when the file has it:
    max_version "22.00", max_release 2020, saved_as_version "22.00", build "22.2.0.2176", compressed False,
    renderer {"name": ..., "class_id": (a, b)}, counts {objects, shapes, lights, cameras, helpers, space_warps,
    total, vertices, faces, materials}, plugins [dll names]
and {} for a file without the stream. The stream comes from anywhere: every offset and count is checked against
its section, the property and vector counts are capped, only the properties asked for are decoded, and the bytes
decoded in all are capped at twice the stream (property ids or sections that share one large value would
otherwise decode it thousands of times). A returned string is at most MAX_TEXT characters, a plug-in entry that
is not a bare file name is dropped. A malformed property set raises MetadataError (a ValueError), never another
exception. No bpy.
"""
import struct
import uuid

from .errors import MaxFileError

DOC_SUMMARY = "\x05DocumentSummaryInformation"
FMTID_DOC_SUMMARY = uuid.UUID("D5CDD502-2E9C-101B-9397-08002B2CF9AE")
FMTID_SUMMARY = uuid.UUID("F29F85E0-4FF9-1068-AB91-08002B27B3D9")
PID_CODEPAGE, PID_HEADING_PAIRS, PID_DOC_PARTS = 1, 12, 13

MAX_STREAM = 16 << 20
MAX_SECTIONS = 16
MAX_PROPERTIES = 4096
MAX_VECTOR = 1 << 16
MAX_TEXT = 256
WANTED = {FMTID_DOC_SUMMARY: (PID_HEADING_PAIRS, PID_DOC_PARTS)}

VT_I2, VT_I4, VT_BOOL, VT_VARIANT, VT_UI4, VT_LPSTR, VT_LPWSTR = 0x02, 0x03, 0x0B, 0x0C, 0x13, 0x1E, 0x1F
VT_VECTOR = 0x1000

COUNTS = {
    "Objects": "objects", "Shapes": "shapes", "Lights": "lights", "Cameras": "cameras", "Helpers": "helpers",
    "Space Warps": "space_warps", "Total": "total", "Vertices": "vertices", "Faces": "faces",
}
# The Windows ANSI code pages a property set (or an older file's 8-bit strings, reader/strings.py) may be in
CODE_PAGES = {1250: "cp1250", 1251: "cp1251", 1252: "cp1252", 1253: "cp1253", 1254: "cp1254", 1255: "cp1255",
              1256: "cp1256", 1257: "cp1257", 1258: "cp1258", 874: "cp874", 932: "cp932", 936: "cp936",
              949: "cp949", 950: "cp950"}
_CODECS = {1200: "utf-16-le", 65001: "utf-8", **CODE_PAGES}


class MetadataError(MaxFileError):
    pass


class _Section:
    """One section of a property set: bounds-checked reads relative to its start."""

    def __init__(self, data, base, end, budget):
        self.data, self.base, self.end = data, base, end
        self.codec = "cp1252"
        self.budget = budget  # a one-item list shared by every section of the stream: bytes left to decode

    def spend(self, n):
        self.budget[0] -= n
        if self.budget[0] < 0:
            raise MetadataError("property set: values decoded more than twice the stream")

    def u32(self, at):
        if at < self.base or at + 4 > self.end:
            raise MetadataError("property set: read at %d outside its section" % at)
        return struct.unpack_from("<I", self.data, at)[0]

    def string(self, at, wide):
        """(text, offset after the padded value). A VT_LPSTR's count is in bytes, a VT_LPWSTR's in characters."""
        n = self.u32(at)
        size = n * 2 if wide else n
        start = at + 4
        if size > self.end - start:
            raise MetadataError("property set: string runs past its section")
        self.spend(4 + size)
        raw = bytes(self.data[start:start + size])
        codec = "utf-16-le" if wide else self.codec
        text = raw.decode(codec, "replace").split("\0", 1)[0]
        return text, start + size + (-size) % 4

    def value(self, at, nested=False):
        """(value, offset after it) of a typed value; (None, None) for a type that is not read. A vector item
        (nested) cannot be a vector itself, so a hostile stream cannot nest them as deep as it is long."""
        vt = self.u32(at) & 0xFFFF
        p = at + 4
        self.spend(4)
        if vt == VT_I2:
            return struct.unpack("<h", self._bytes(p, 2))[0], p + 4
        if vt in (VT_I4, VT_UI4, VT_BOOL):
            raw = self._bytes(p, 4)
            if vt == VT_BOOL:
                return struct.unpack("<h", raw[:2])[0] != 0, p + 4
            return struct.unpack("<i" if vt == VT_I4 else "<I", raw)[0], p + 4
        if vt in (VT_LPSTR, VT_LPWSTR):
            return self.string(p, vt == VT_LPWSTR)
        if vt & VT_VECTOR and not nested and vt & ~VT_VECTOR in (VT_LPSTR, VT_LPWSTR, VT_VARIANT):
            count = self.u32(p)
            if count > MAX_VECTOR:
                raise MetadataError("property set: vector of %d items" % count)
            p += 4
            out = []
            for _ in range(count):
                if vt & ~VT_VECTOR == VT_VARIANT:
                    item, p = self.value(p, nested=True)
                    if p is None:
                        raise MetadataError("property set: a vector item of a type that is not read")
                else:
                    item, p = self.string(p, vt & ~VT_VECTOR == VT_LPWSTR)
                out.append(item)
            return out, p
        return None, None

    def _bytes(self, at, n):
        if at < self.base or at + n > self.end:
            raise MetadataError("property set: value at %d outside its section" % at)
        return bytes(self.data[at:at + n])


def property_sets(data, wanted=None):
    """{FMTID (uuid.UUID): {property id: value}} of a property-set stream; values of types not read are left
    out. wanted = {FMTID: property ids}: only those sections and properties are decoded (all of them when
    None); the code page of a wanted section is always read."""
    data = memoryview(data).cast("B")
    total = len(data)
    if total > MAX_STREAM:
        raise MetadataError("property set stream of %d bytes" % total)
    if total < 28 or bytes(data[:2]) != b"\xfe\xff":
        raise MetadataError("not a property-set stream")
    count = struct.unpack_from("<I", data, 24)[0]
    if count > MAX_SECTIONS or 28 + 20 * count > total:
        raise MetadataError("property set: %d sections do not fit" % count)
    out, budget = {}, [2 * total]
    for k in range(count):
        head = 28 + 20 * k
        fmtid = uuid.UUID(bytes_le=bytes(data[head:head + 16]))
        base = struct.unpack_from("<I", data, head + 16)[0]
        if base + 8 > total:
            raise MetadataError("property set: section %d starts past the stream" % k)
        size, nprops = struct.unpack_from("<II", data, base)
        if size < 8 or size > total - base:
            raise MetadataError("property set: section %d of %d bytes does not fit" % (k, size))
        if nprops > MAX_PROPERTIES or 8 + 8 * nprops > size:
            raise MetadataError("property set: section %d lists %d properties" % (k, nprops))
        if wanted is not None and (fmtid not in wanted or fmtid in out):
            continue
        pids = None if wanted is None else frozenset(wanted[fmtid])
        section = _Section(data, base, base + size, budget)
        offsets = [struct.unpack_from("<II", data, base + 8 + 8 * j) for j in range(nprops)]
        for pid, rel in offsets:
            if pid == PID_CODEPAGE:
                codepage, _ = section.value(base + rel)
                if isinstance(codepage, int):
                    section.codec = _CODECS.get(codepage & 0xFFFF, "cp1252")
        props = {}
        for pid, rel in offsets:
            if pid == 0 or pid & 0x80000000:  # the dictionary and the locale / behavior properties
                continue
            if pids is not None and pid not in pids:
                continue
            value, _ = section.value(base + rel)
            if value is not None:
                props[pid] = value
        out[fmtid] = props
    return out


def groups(props):
    """{heading: [document parts]} of a DocumentSummaryInformation section."""
    pairs, parts = props.get(PID_HEADING_PAIRS), props.get(PID_DOC_PARTS)
    if not isinstance(pairs, list) or not isinstance(parts, list):
        return {}
    if not all(isinstance(p, str) for p in parts):
        raise MetadataError("document summary: a document part is not a string")
    out, at = {}, 0
    for i in range(0, len(pairs) - 1, 2):
        heading, n = pairs[i], pairs[i + 1]
        if not isinstance(heading, str) or not isinstance(n, int) or n < 0 or at + n > len(parts):
            raise MetadataError("document summary: heading pairs do not match the parts")
        out[heading] = parts[at:at + n]
        at += n
    return out


def _fields(lines, sep):
    out = {}
    for line in lines:
        key, found, value = line.partition(sep)
        if found:
            out[key.strip()] = value.strip()
    return out


def _int(text):
    """A non-negative decimal of at most 20 digits, else None."""
    if not isinstance(text, str) or not (text.isascii() and text.isdigit()) or len(text) > 20:
        return None
    return int(text)


def _text(value):
    return value[:MAX_TEXT]


def _is_file_name(name):
    return 0 < len(name) <= MAX_TEXT and not any(c in name for c in "\\/:")


def major(version):
    """The major version of a version string ("22.00" -> 22), None when it does not start with a number."""
    return _int((version or "").split(".", 1)[0])


def code_page(data):
    """The code page (property 1, as an unsigned 16-bit number) a SummaryInformation or DocumentSummaryInformation
    stream records, None when it records none."""
    sets = property_sets(data, {FMTID_DOC_SUMMARY: (PID_CODEPAGE,), FMTID_SUMMARY: (PID_CODEPAGE,)})
    for fmtid in (FMTID_DOC_SUMMARY, FMTID_SUMMARY):
        page = sets.get(fmtid, {}).get(PID_CODEPAGE)
        if isinstance(page, int) and not isinstance(page, bool):
            return page & 0xFFFF
    return None


def release(version):
    """The 3ds Max release year of a version string ("22.00" -> 2020); None outside versions 10 (3ds Max 2008)
    to 99."""
    n = major(version)
    return n + 1998 if n is not None and 10 <= n <= 99 else None


def _class_part(text):
    """One half of a ClassID as 3ds Max writes it: a decimal u32, negative when the high bit is set."""
    if isinstance(text, str) and text.startswith("-"):
        value = _int(text[1:])
        return None if value is None or value > 0x80000000 else -value & 0xFFFFFFFF
    value = _int(text)
    return None if value is None or value > 0xFFFFFFFF else value


def summarize(group_map):
    """The facts read() returns, from the groups of a DocumentSummaryInformation section."""
    info = {}
    general = group_map.get("General", [])
    fields = _fields(general, ":")
    if "3ds Max Version" in fields:
        info["max_version"] = _text(fields["3ds Max Version"])
        year = release(fields["3ds Max Version"])
        if year is not None:
            info["max_release"] = year
    if "Saved As Version" in fields:
        info["saved_as_version"] = _text(fields["Saved As Version"])
    if "Build" in fields:
        info["build"] = _text(fields["Build"])
    flags = {line.strip() for line in general}
    if "Compressed" in flags or "Uncompressed" in flags:
        info["compressed"] = "Compressed" in flags

    counts = {}
    for name in ("Mesh Totals", "Scene Totals"):
        for key, value in _fields(group_map.get(name, []), ":").items():
            if key in COUNTS and _int(value) is not None:
                counts[COUNTS[key]] = _int(value)
    if "Materials" in group_map:
        counts["materials"] = len(group_map["Materials"])
    if counts:
        info["counts"] = counts

    render = _fields(group_map.get("Render Data", []), "=")
    renderer = {}
    if "Renderer Name" in render:
        renderer["name"] = _text(render["Renderer Name"])
    a, b = _class_part(render.get("Renderer ClassIDA")), _class_part(render.get("Renderer ClassIDB"))
    if a is not None and b is not None:
        renderer["class_id"] = (a, b)
    if renderer:
        info["renderer"] = renderer

    if "Used Plug-Ins" in group_map:
        info["plugins"] = [p for p in group_map["Used Plug-Ins"] if _is_file_name(p)]
    return info


def read(cf):
    """The pre-flight facts of an open cfb.CompoundFile (see the module docstring)."""
    if not cf.exists(DOC_SUMMARY):
        return {}
    stream = cf.open(DOC_SUMMARY, decompress=False)
    if stream.size > MAX_STREAM:
        raise MetadataError("property set stream of %d bytes" % stream.size)
    props = property_sets(stream.read(), WANTED).get(FMTID_DOC_SUMMARY)
    if props is None:
        return {}
    return summarize(groups(props))
