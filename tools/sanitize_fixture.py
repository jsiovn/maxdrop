# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blank the Windows user and computer name 3ds Max writes into every .max it saves, in place.

    python -I tools/sanitize_fixture.py tests/fixtures/<name>.max ...

3ds Max stores them in the two OLE property-set streams of the file: `User Name=<user>` and `Computer Name=<machine>`
in the DocumentSummaryInformation stream, and the user name in the author and last-author properties of the
SummaryInformation stream (Max 2020 also repeats it in property 34). Each of those values is overwritten with `x`
of the same length; any other string property of the two streams equal to one of them is blanked too. Nothing else
in the file changes: no byte moves, the scene, the thumbnail and every other stream stay as they are. The values
are never printed. Running it again changes nothing. A file without a `User Name=` slot is refused: its 3ds Max
version stores the names in a way this tool does not know (checked on files saved by 3ds Max 2020). Then run
tools/check_fixture.py, which also catches the names anywhere else. Standard library only.
"""
import importlib.util
import os
import struct
import sys
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cfb", os.path.join(_HERE, "cfb.py"))
cfb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cfb)

SUMMARY = "\x05SummaryInformation"
DOC_SUMMARY = "\x05DocumentSummaryInformation"
FMTID_SUMMARY = uuid.UUID("F29F85E0-4FF9-1068-AB91-08002B27B3D9").bytes_le
PREFIXES = (("User Name=", "user name"), ("Computer Name=", "computer name"))
AUTHOR_IDS = (4, 8)  # PIDSI_AUTHOR, PIDSI_LASTAUTHOR
FILL = "x"
WIDE, NARROW = "utf-16-le", "8bit"
CP_UTF16 = 1200

VT_I2, VT_I4, VT_LPSTR, VT_LPWSTR, VT_VARIANT, VT_VECTOR = 0x02, 0x03, 0x1E, 0x1F, 0x0C, 0x1000


class Target:
    """A string value in a property stream: where it is and what it holds."""

    def __init__(self, stream, offset, raw, encoding, kind=None):
        self.stream, self.offset, self.raw, self.encoding, self.kind = stream, offset, raw, encoding, kind

    @property
    def text(self):
        # Narrow strings are compared byte for byte, whatever their code page.
        return self.raw.decode(WIDE if self.encoding == WIDE else "latin-1", "replace")

    def blank(self):
        return FILL * (len(self.raw) // (2 if self.encoding == WIDE else 1))

    def fill_bytes(self):
        return self.blank().encode(WIDE if self.encoding == WIDE else "latin-1")


def _u32(b, at, end):
    if at + 4 > end:
        raise ValueError("property set truncated")
    return struct.unpack_from("<I", b, at)[0]


def _string(b, at, end, wide, count_is_chars):
    """(offset of the text, its bytes up to the first NUL, offset after the padded value)."""
    n = _u32(b, at, end)
    size = n * 2 if count_is_chars else n
    start, stop = at + 4, at + 4 + size
    if stop > end:
        raise ValueError("string runs past its property set")
    body = b[start:stop]
    if wide:
        cut = next((i for i in range(0, len(body) - 1, 2) if body[i:i + 2] == b"\0\0"), len(body) & ~1)
    else:
        cut = body.find(b"\0") if b"\0" in body else len(body)
    return start, body[:cut], stop + (-size) % 4  # each value is padded to a multiple of 4 bytes


def _code_page(stream, base, end, count):
    """Property 1 (VT_I2) of a section, as an unsigned code page; None when absent."""
    for j in range(count):
        pid, rel = _u32(stream, base + 8 + 8 * j, end), _u32(stream, base + 12 + 8 * j, end)
        if pid == 1:
            at = base + rel
            if at + 6 > end:
                raise ValueError("property set truncated")
            vt, value = struct.unpack_from("<Hxxh", stream, at)
            return value & 0xFFFF if vt == VT_I2 else None
    return None


def strings(stream):
    """Every string value of a property-set stream: (FMTID, property id, offset, bytes, WIDE or NARROW)."""
    if len(stream) < 28 or stream[:2] != b"\xfe\xff":
        raise ValueError("not a property-set stream")
    total = len(stream)
    for k in range(_u32(stream, 24, total)):
        head = 28 + 20 * k
        if head + 20 > total:
            raise ValueError("property set list truncated")
        fmtid, base = stream[head:head + 16], _u32(stream, head + 16, total)
        end = min(total, base + _u32(stream, base, total))
        count = _u32(stream, base + 4, end)
        utf16 = _code_page(stream, base, end, count) == CP_UTF16
        for j in range(count):
            pid, rel = _u32(stream, base + 8 + 8 * j, end), _u32(stream, base + 12 + 8 * j, end)
            if pid in (0, 1):  # dictionary, code page
                continue
            at = base + rel
            vt = _u32(stream, at, end) & 0xFFFF
            for offset, raw, wide in _values(stream, vt, at + 4, end, utf16):
                yield fmtid, pid, offset, raw, WIDE if wide else NARROW


def _values(b, vt, at, end, utf16):
    """(offset, bytes, wide) of the strings of one typed value. In a section of code page 1200 a VT_LPSTR holds
    UTF-16 text, its count in bytes."""
    def one(kind, p):
        wide = kind == VT_LPWSTR or utf16
        offset, raw, after = _string(b, p, end, wide, kind == VT_LPWSTR)
        return (offset, raw, wide), after

    if vt in (VT_LPSTR, VT_LPWSTR):
        yield one(vt, at)[0]
    elif vt in (VT_VECTOR | VT_LPSTR, VT_VECTOR | VT_LPWSTR):
        p = at + 4
        for _ in range(_u32(b, at, end)):
            item, p = one(vt & ~VT_VECTOR, p)
            yield item
    elif vt == VT_VECTOR | VT_VARIANT:
        p = at + 4
        for _ in range(_u32(b, at, end)):
            inner = _u32(b, p, end) & 0xFFFF
            if inner in (VT_LPSTR, VT_LPWSTR):
                item, p = one(inner, p + 4)
                yield item
            elif inner in (VT_I2, VT_I4):
                p += 8
            else:
                raise ValueError("a vector element of type 0x%x cannot be walked" % inner)


def identity_values(data):
    """The Targets that hold the user or computer name in a .max (bytes): what sanitize() blanks."""
    c = cfb.Compound(data)
    found, values = [], {}
    pool = []
    for name in (DOC_SUMMARY, SUMMARY):
        if name in c.names():
            pool += [(name,) + item for item in strings(c.read(name))]
    for name, fmtid, pid, offset, raw, enc in pool:
        target = None
        if name == DOC_SUMMARY:
            for prefix, kind in PREFIXES:
                head = prefix.encode(WIDE if enc == WIDE else "latin-1")
                if raw.startswith(head):
                    target = Target(name, offset + len(head), raw[len(head):], enc, kind)
        elif name == SUMMARY and fmtid == FMTID_SUMMARY and pid in AUTHOR_IDS:
            target = Target(name, offset, raw, enc, "user name")
        if target and target.raw:
            found.append(target)
            # Blank values too: a sanitized file still reports every slot, so the check can see one refilled.
            values.setdefault(target.text.casefold(), target.kind)
    taken = {(t.stream, t.offset) for t in found}
    for name, fmtid, pid, offset, raw, enc in pool:
        t = Target(name, offset, raw, enc)
        if (name, offset) not in taken and t.text.casefold() in values:
            t.kind = values[t.text.casefold()]
            found.append(t)
    return found


def slots_found(targets):
    """True when the DocumentSummaryInformation `User Name=` slot every 3ds Max file carries was found."""
    return any(t.stream == DOC_SUMMARY and t.kind == "user name" for t in targets)


def sanitize(data):
    """(the bytes with every identity value blanked, the number of values that changed)."""
    c = cfb.Compound(data)
    out = bytearray(data)
    changed = 0
    targets = identity_values(data)
    if not slots_found(targets):
        raise ValueError("no User Name= slot found: a 3ds Max version this tool does not know")
    for t in targets:
        fill = t.fill_bytes()
        if t.raw == fill:
            continue
        changed += 1
        _write(out, c.runs(t.stream), t.offset, fill)
    return bytes(out), changed


def _write(buf, runs, offset, payload):
    """Write payload at a stream offset, through the file pieces that hold the stream."""
    pos = 0
    for start, length in runs:
        if offset < pos + length and payload:
            skip = max(0, offset - pos)
            n = min(length - skip, len(payload))
            buf[start + skip:start + skip + n] = payload[:n]
            payload, offset = payload[n:], offset + n
        pos += length
    if payload:
        raise cfb.CfbError("value runs past its stream")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    status = 0
    for path in argv[1:]:
        try:
            with open(path, "rb") as f:
                data = f.read()
            new, changed = sanitize(data)
            if sanitize(new)[1] or any(t.raw != t.fill_bytes() for t in identity_values(new)):
                raise cfb.CfbError("a value is still not blank after sanitizing")
        except (OSError, ValueError) as e:
            print("sanitize_fixture: %s: %s" % (path, e), file=sys.stderr)
            status = 1
            continue
        if changed:
            temp = path + ".sanitizing"
            with open(temp, "wb") as f:
                f.write(new)
            os.replace(temp, path)
        print("sanitize_fixture: %s: %d value(s) blanked" % (path, changed))
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
