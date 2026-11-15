# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Refuse a test file that holds a user name, a computer name or a user path, before it enters the repository.

    python -I tools/check_fixture.py tests/fixtures/*.max

The repository is public and its history permanent, and 3ds Max writes the Windows user and computer name into
every file it saves (tools/sanitize_fixture.py blanks them). A file fails when its bytes, or a gzip-compressed
stream of it unpacked, hold in ASCII or UTF-16LE, ignoring case:

- `user name`: the name of the user running this check;
- `computer name`: the name of this computer;
- `user folder`: `Users\\` or `Users/` followed by a name (`C:\\Users\\...`, `/Users/...`);
- `drive path`: a drive letter path (`X:\\` and two more path characters);

or when a value tools/sanitize_fixture.py blanks is not blank (`identity property not blank`), which catches a
file saved under another account. Only the kind of string is printed, never the string. Exit 0 when every file
is clean, 1 otherwise. Standard library only.
"""
import getpass
import glob
import importlib.util
import os
import re
import socket
import sys
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("sanitize_fixture", os.path.join(_HERE, "sanitize_fixture.py"))
sanitize_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sanitize_fixture)
cfb = sanitize_fixture.cfb

MIN_NAME = 3  # shorter names would match by chance anywhere in binary data
GZIP_CAP = 64 << 20
_PATH_CHAR = r'[^\x00-\x1f\\/:*?"<>|\ufffd]'
PATTERNS = (
    ("user folder", re.compile(r"users[\\/]" + _PATH_CHAR)),
    ("drive path", re.compile(r"(?<![a-z0-9])[a-z]:\\" + _PATH_CHAR + "{2}")),
)


def local_names():
    """{kind: names} of the user and computer running the check, casefolded, without the too short ones."""
    users = {os.environ.get("USERNAME"), os.environ.get("USER")}
    try:
        users.add(getpass.getuser())
    except (KeyError, OSError):
        pass
    host = socket.gethostname()
    computers = {host, host.split(".")[0], os.environ.get("COMPUTERNAME")}
    return {kind: sorted({n.casefold() for n in names if n and len(n) >= MIN_NAME})
            for kind, names in (("user name", users), ("computer name", computers))}


def _views(data):
    """(encoding label, text) views of bytes: ASCII-compatible, and UTF-16LE at both byte alignments."""
    yield "ASCII", data.decode("latin-1").casefold()
    for start in (0, 1):
        chunk = data[start:len(data) - (len(data) - start) % 2]
        yield "UTF-16LE", chunk.decode("utf-16-le", "replace").casefold()


def _haystacks(data):
    """(where, bytes): the whole file, then each gzip-compressed stream unpacked."""
    yield None, data
    if not cfb.is_cfb(data):
        return
    c = cfb.Compound(data)
    for name in c.names():
        stream = c.read(name)
        if stream[:2] != b"\x1f\x8b":
            continue
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        out = d.decompress(stream, GZIP_CAP)
        if d.unconsumed_tail:
            raise cfb.CfbError("compressed stream %r is too large to scan" % name)
        yield name, out


def problems(data, names=None):
    """Sorted (kind, encoding, stream or None) found in the bytes of a file; empty when clean."""
    names = local_names() if names is None else names
    found = set()
    try:
        stacks = list(_haystacks(data))
    except (ValueError, zlib.error) as e:
        found.add(("unreadable: %s" % e, "-", None))
        stacks = [(None, data)]
    for where, blob in stacks:
        for enc, text in _views(blob):
            for kind, values in names.items():
                if any(v in text for v in values):
                    found.add((kind, enc, where))
            for kind, pattern in PATTERNS:
                if pattern.search(text):
                    found.add((kind, enc, where))
    if cfb.is_cfb(data):
        try:
            if any(t.raw != t.fill_bytes() for t in sanitize_fixture.identity_values(data)):
                found.add(("identity property not blank", "-", None))
        except ValueError as e:
            found.add(("unreadable: %s" % e, "-", None))
    return sorted(found, key=lambda p: (p[0], p[1], p[2] or ""))


def main(argv):
    paths = [p for arg in argv[1:] for p in (sorted(glob.glob(arg)) if glob.has_magic(arg) else [arg])]
    if not paths:
        print(__doc__)
        return 2
    status = 0
    for path in paths:
        try:
            with open(path, "rb") as f:
                found = problems(f.read())
        except OSError as e:
            print("check_fixture: %s: cannot read (%s)" % (path, e.strerror), file=sys.stderr)
            status = 1
            continue
        if not found:
            print("check_fixture: %s: clean" % path)
            continue
        status = 1
        for kind, enc, where in found:
            detail = enc if where is None else "%s, stream %s" % (enc, where)
            print("check_fixture: %s: %s (%s)" % (path, kind, detail), file=sys.stderr)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
