# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where two .max files differ, stream by stream and chunk path by chunk path, with noise filtered out. No Blender.

    python -I tools/maxdiff.py A.max A2.max B.max [--bytes N] [--stream NAME]
    python -I tools/maxdiff.py A.max B.max

A and A2 are two saves of the same scene, B the same scene with one setting changed: what differs between A and
B but not between A and A2 is printed, so time stamps and other per-save noise drop out. With two files nothing is
filtered.

A chunked stream (Scene, Config, ClassDirectory3, ...) is compared leaf by leaf: a leaf's path names each chunk
from the top as `ID#n`, the n-th sibling with that id, so the k-th object of the Scene stream keeps its path when
an object of another class is inserted before it. A path present in only one file, or a container whose children
differ in number, is reported too. Any other stream (the property sets, FileAssetMetaData) is compared byte by
byte, as ranges of differing bytes. Each difference shows the first N payload bytes (default 16) of both files in
hex.

Those bytes can hold names and paths: do not paste the output of a scene that is not ours. Exit code 0, 1 when a
file cannot be read, 2 for a usage error.
"""
import argparse
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_READER = os.path.join(ROOT, "maxdrop", "reader")


def _load(name, path, package_dir=None):
    if name in sys.modules:
        return sys.modules[name]
    kw = {"submodule_search_locations": [package_dir]} if package_dir else {}
    spec = importlib.util.spec_from_file_location(name, path, **kw)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# By path, as a package of its own: `import maxdrop` would run the add-on's __init__ and pull bpy.
_load("maxdrop_reader", os.path.join(_READER, "__init__.py"), _READER)
cfb = _load("maxdrop_reader.cfb", os.path.join(_READER, "cfb.py"))
chunks = _load("maxdrop_reader.chunks", os.path.join(_READER, "chunks.py"))

_GAP = 8  # differing byte ranges closer than this are reported as one


def _printable(name):
    return "".join(c if c.isprintable() else "\\x%02x" % ord(c) for c in name)


def leaves(stream):
    """{path: payload bytes} of every leaf of a chunked stream, plus {path: child count} of every container;
    None when the stream does not index as chunks to the bottom."""
    try:
        top = chunks.index(stream)
        out, kids = {}, {}
        stack = [("", top)]
        while stack:
            prefix, level = stack.pop()
            seen = {}
            for chunk in level:
                n = seen.get(chunk.id, 0)
                seen[chunk.id] = n + 1
                path = "%s/%04X#%d" % (prefix, chunk.id, n) if prefix else "%04X#%d" % (chunk.id, n)
                if chunk.container:
                    kids[path] = len(chunk.children)
                    stack.append((path, chunk.children))
                else:
                    out[path] = chunk.tobytes()
        return out, kids
    except chunks.ChunkError:
        return None


def byte_ranges(a, b):
    """[(start, end)] of the bytes where a and b differ; a length difference is a range at the end."""
    ranges, n = [], min(len(a), len(b))
    i = 0
    while i < n:
        if a[i] != b[i]:
            j = i + 1
            while j < n and (a[j] != b[j] or any(a[k] != b[k] for k in range(j, min(j + _GAP, n)))):
                j += 1
            ranges.append((i, j))
            i = j
        else:
            i += 1
    if len(a) != len(b):
        if ranges and ranges[-1][1] >= n - _GAP:
            ranges[-1] = (ranges[-1][0], max(len(a), len(b)))
        else:
            ranges.append((n, max(len(a), len(b))))
    return ranges


def _overlaps(r, noise):
    return any(r[0] < e and s < r[1] for s, e in noise)


def _streams(path):
    out = {}
    with cfb.CompoundFile(path) as cf:
        for name in cf.names():
            out[name] = cf.open(name).read()
    return out


class Difference:
    __slots__ = ("stream", "where", "a", "b", "note")

    def __init__(self, stream, where, a, b, note=""):
        self.stream, self.where, self.a, self.b, self.note = stream, where, a, b, note


def _chunk_diffs(name, la, lb, noise):
    (leaf_a, kids_a), (leaf_b, kids_b) = la, lb
    out = []
    for path in sorted(set(kids_a) | set(kids_b)):
        if kids_a.get(path) != kids_b.get(path) and path not in noise:
            out.append(Difference(name, path, None, None, "children %s -> %s" % (kids_a.get(path), kids_b.get(path))))
    for path in sorted(set(leaf_a) | set(leaf_b)):
        a, b = leaf_a.get(path), leaf_b.get(path)
        if a != b and path not in noise:
            note = "only in A" if b is None else "only in B" if a is None else "%d -> %d bytes" % (len(a), len(b))
            out.append(Difference(name, path, a, b, note))
    return out


def _noise_paths(la, la2):
    (leaf_a, kids_a), (leaf_a2, kids_a2) = la, la2
    noise = {p for p in set(kids_a) | set(kids_a2) if kids_a.get(p) != kids_a2.get(p)}
    noise |= {p for p in set(leaf_a) | set(leaf_a2) if leaf_a.get(p) != leaf_a2.get(p)}
    return noise


def diff(path_a, path_b, path_a2=None):
    """The list of Differences between A and B that do not also differ between A and A2."""
    sa, sb = _streams(path_a), _streams(path_b)
    sa2 = _streams(path_a2) if path_a2 else None
    out = []
    for name in sorted(set(sa) | set(sb)):
        a, b = sa.get(name), sb.get(name)
        if a is None or b is None:
            out.append(Difference(name, "", None, None, "stream only in %s" % ("B" if a is None else "A")))
            continue
        if a == b:
            continue
        a2 = sa2.get(name) if sa2 is not None else None
        if sa2 is not None and a2 is None:
            continue  # the stream itself comes and goes between saves
        la, lb = leaves(a), leaves(b)
        la2 = leaves(a2) if a2 is not None else None
        if la is not None and lb is not None and (a2 is None or la2 is not None):
            noise = _noise_paths(la, la2) if la2 is not None else set()
            out += _chunk_diffs(name, la, lb, noise)
            continue
        noise = byte_ranges(a, a2) if a2 is not None else []
        for r in byte_ranges(a, b):
            if not _overlaps(r, noise):
                out.append(Difference(name, "bytes %d..%d" % r, a[r[0]:r[1]], b[r[0]:r[1]],
                                      "%d -> %d bytes" % (len(a), len(b)) if len(a) != len(b) else ""))
    return out


def _hex(data, n):
    if data is None:
        return "-"
    text = data[:n].hex(" ")
    return text + (" ..." if len(data) > n else "")


def format_text(diffs, nbytes=16):
    if not diffs:
        return "no difference\n"
    out = []
    for d in diffs:
        where = "%s %s" % (_printable(d.stream), d.where) if d.where else _printable(d.stream)
        out.append("%s  %s" % (where, d.note) if d.note else where)
        if d.a is not None or d.b is not None:
            out.append("    A: %s" % _hex(d.a, nbytes))
            out.append("    B: %s" % _hex(d.b, nbytes))
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", metavar="FILE", help="A.max A2.max B.max, or A.max B.max")
    parser.add_argument("--bytes", type=int, default=16, help="payload bytes to show per difference")
    parser.add_argument("--stream", action="append", help="only this stream (repeatable)")
    args = parser.parse_args(argv)
    if len(args.files) not in (2, 3) or args.bytes < 0:
        parser.print_usage(sys.stderr)
        return 2
    for path in args.files:
        if not os.path.isfile(path):
            print("maxdiff: no such file", file=sys.stderr)
            return 2
    path_a, path_b = args.files[0], args.files[-1]
    path_a2 = args.files[1] if len(args.files) == 3 else None
    try:
        diffs = diff(path_a, path_b, path_a2)
    except ValueError as exc:
        print("maxdiff: cannot read a file: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:  # its str() carries the path
        print("maxdiff: cannot read a file: %s" % (exc.strerror or type(exc).__name__), file=sys.stderr)
        return 1
    if args.stream:
        wanted = {s.lower() for s in args.stream}
        diffs = [d for d in diffs if d.stream.lower().lstrip("\x05") in wanted or d.stream.lower() in wanted]
    sys.stdout.write(format_text(diffs, args.bytes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
