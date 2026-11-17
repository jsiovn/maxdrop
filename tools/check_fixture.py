# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Refuse a test file that holds a user name, a computer name or a user path, before it enters the repository.

    python -I tools/check_fixture.py "tests/fixtures/**/*"

A pattern (`**` included, for any depth) expands to the files it matches, hidden ones too from Python 3.11 on; the
folders it matches are left out.

The repository is public and its history permanent, and 3ds Max writes the Windows user and computer name into
every file it saves (tools/sanitize_fixture.py blanks them). A file fails when its bytes, or any of its streams
put back together (gzip streams unpacked), hold in ASCII, UTF-8 or UTF-16LE, ignoring case:

- `user name`: the name of the user running this check;
- `computer name`: the name of this computer;
- `user folder`: `Users\\` or `Users/` followed by a name (`C:\\Users\\...`, `/Users/...`);
- `drive path`: a drive letter path (`X:\\` or `X:/` and two more path characters);
- `network path`: `\\\\server\\` and a share name;

or when a value tools/sanitize_fixture.py blanks is not blank (`identity property not blank`), which catches a
file saved under another account, or when the file has no `User Name=` slot (`identity slots not found`): its
3ds Max version stores the names in a way the tools do not know. Only the kind of string is printed, never the
string. Exit 0 when every file
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
    ("drive path", re.compile(r"(?<![a-z0-9])[a-z]:[\\/]" + _PATH_CHAR + "{2}")),
    ("network path", re.compile(r"(?<!\\)\\\\[a-z0-9][a-z0-9._$-]+\\" + _PATH_CHAR)),
)


def _local():
    users = {os.environ.get("USERNAME"), os.environ.get("USER")}
    try:
        users.add(getpass.getuser())
    except (KeyError, OSError):
        pass
    host = socket.gethostname()
    computers = {host, host.split(".")[0], os.environ.get("COMPUTERNAME")}
    return (("user name", {n for n in users if n}), ("computer name", {n for n in computers if n}))


def local_names():
    """{kind: names} of the user and computer running the check, casefolded, without the too short ones."""
    return {kind: sorted({n.casefold() for n in names if len(n) >= MIN_NAME}) for kind, names in _local()}


def too_short():
    """The kinds whose local name is too short to be searched for."""
    return [kind for kind, names in _local() if any(len(n) < MIN_NAME for n in names)]


def _views(data):
    """(encoding label, text) views of bytes: one byte per character, UTF-8, UTF-16LE at both byte alignments."""
    yield "ASCII", data.decode("latin-1").casefold()
    yield "UTF-8", data.decode("utf-8", "replace").casefold()
    for start in (0, 1):
        chunk = data[start:len(data) - (len(data) - start) % 2]
        yield "UTF-16LE", chunk.decode("utf-16-le", "replace").casefold()


def _haystacks(data):
    """(where, bytes): the whole file, then every stream put back together, gzip streams unpacked. The sectors of
    a stream need not follow each other in the file, so a string can be whole only in the stream."""
    yield None, data
    if not cfb.is_cfb(data):
        return
    for name, stream in cfb.Compound(data).streams():
        if stream[:2] == b"\x1f\x8b":
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            stream = d.decompress(stream, GZIP_CAP)
            if d.unconsumed_tail:
                raise cfb.CfbError("compressed stream %r is too large to scan" % name)
        yield name, stream


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
            utf8 = enc == "UTF-8"  # adds only what the byte view cannot see: names with non-ASCII letters
            for kind, values in names.items():
                if any(v in text for v in values if not utf8 or not v.isascii()):
                    found.add((kind, enc, where))
            for kind, pattern in () if utf8 else PATTERNS:
                if pattern.search(text):
                    found.add((kind, enc, where))
    if cfb.is_cfb(data):
        try:
            targets = sanitize_fixture.identity_values(data)
            if not sanitize_fixture.slots_found(targets):
                found.add(("identity slots not found", "-", None))
            if any(t.raw != t.fill_bytes() for t in targets):
                found.add(("identity property not blank", "-", None))
        except ValueError as e:
            found.add(("unreadable: %s" % e, "-", None))
    return sorted(found, key=lambda p: (p[0], p[1], p[2] or ""))


def _expand(arg):
    """The files a command-line argument names: a pattern expands to the files it matches, directories left out;
    anything else is taken as it is."""
    if not glob.has_magic(arg):
        return [arg]
    # Hidden names too (a pack's .maxdrop-pack.json holds the archive name); glob can only from Python 3.11 on.
    hidden = {"include_hidden": True} if sys.version_info >= (3, 11) else {}
    return [p for p in sorted(glob.glob(arg, recursive=True, **hidden)) if os.path.isfile(p)]


def main(argv):
    paths = [p for arg in argv[1:] for p in _expand(arg)]
    if not paths:
        print(__doc__)
        return 2
    for kind in too_short():
        print("check_fixture: the local %s is shorter than %d characters and is not searched for" % (kind, MIN_NAME),
              file=sys.stderr)
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
            detail = enc if where is None else "%s, stream %s" % (enc, "".join(c for c in where if c.isprintable()))
            print("check_fixture: %s: %s (%s)" % (path, kind, detail), file=sys.stderr)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
