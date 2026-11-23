# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run ruff on the tree at the version CI runs, the one `required-version` in pyproject.toml names, then the
unreachable-code check ruff has no rule for at that version.

    python -I tools/lint.py                              # ruff check .
    python -I tools/lint.py --output-format=github .     # the arguments go to `ruff check`

The ruff used is `ruff` on PATH when it is that version, otherwise `uvx --offline ruff@<version>` when uv has it
cached (`--offline`: never a download). The unreachable-code check reads the files ruff checks (`ruff check <the
arguments> --show-files`) and reports a statement that follows `return`, `raise`, `continue` or `break` in the same
block, or a compound statement no path through falls out of (a `with` whose body exits, an `if`/`else` exiting on
both branches, a `try` whose `finally` exits or whose body and handlers do, a `match` ending in an irrefutable
case with every case exiting): a test method left nested after a return drops out of its suite without a failure.
Loops are never followed (a `break` leaves them, `while True` included) and there is no suppression comment
(`return` then `yield`, the empty generator, is flagged too); a file this Python cannot parse is noted on stderr
and not checked; the check is skipped with an argument ruff refuses beside --show-files (--statistics,
--add-noqa, ...). Exit: ruff's own (0 clean, 1 findings, 2 a ruff error such as a bad argument; an unreachable
statement turns 0 into 1 unless --exit-zero), 3 when no ruff of that version is found or pyproject.toml has no
pin. Standard library only, Python 3.9 and later (no tomllib).
"""
import ast
import os
import re
import shutil
import subprocess
import sys

NOT_FOUND = 3  # ruff itself exits 0, 1 or 2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(ROOT, "pyproject.toml")


def pin(path=PYPROJECT):
    """The exact ruff version of `required-version = "==x.y.z"` in pyproject.toml."""
    with open(path, encoding="utf-8") as f:
        match = re.search(r'^required-version\s*=\s*"==(\d+(?:\.\d+)*)"\s*$', f.read(), re.MULTILINE)
    if match is None:
        raise ValueError('%s has no required-version = "==x.y.z"' % path)
    return match.group(1)


def _prints_version(argv, version):
    try:
        done = subprocess.run(argv + ["--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and done.stdout.split() == ["ruff", version]


def find_ruff(version):
    """The command that runs ruff `version` (a list), or None."""
    candidates = []
    if shutil.which("ruff"):
        candidates.append([shutil.which("ruff")])
    if shutil.which("uvx"):
        candidates.append([shutil.which("uvx"), "--offline", "ruff@" + version])
    for argv in candidates:
        if _prints_version(argv, version):
            return argv
    return None


def _echo(data, stream):
    """Ruff's bytes as they are: a redirected stdout on Windows is cp1252, and a finding quotes source lines."""
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(data.decode("utf-8", "replace"))
    else:
        stream.flush()
        buffer.write(data)
        buffer.flush()


_TERMINAL = (ast.Return, ast.Raise, ast.Continue, ast.Break)
_TRY = tuple(getattr(ast, name) for name in ("Try", "TryStar") if hasattr(ast, name))  # TryStar: 3.11
_MATCH = getattr(ast, "Match", None)  # 3.10
_NAMES = {"AsyncWith": "async with", "TryStar": "try"}


def _block_exits(block):
    # Control never passes a statement that exits, so a block exits when any statement in it does.
    return any(_exits(stmt) for stmt in block)


def _irrefutable(pattern):
    if isinstance(pattern, ast.MatchOr):
        return any(_irrefutable(p) for p in pattern.patterns)
    return isinstance(pattern, ast.MatchAs) and pattern.pattern is None  # `case _:` / `case name:`


def _exits(stmt):
    """True when no path through `stmt` falls through to the next statement. Loops never exit (a break leaves
    them, `while True` included), nor do definitions."""
    if isinstance(stmt, _TERMINAL):
        return True
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return _block_exits(stmt.body)
    if isinstance(stmt, ast.If):  # elif: an If in orelse
        return bool(stmt.orelse) and _block_exits(stmt.body) and _block_exits(stmt.orelse)
    if isinstance(stmt, _TRY):
        # The else runs only after the body completes: either one exiting covers the path without an exception.
        return _block_exits(stmt.finalbody) or (
            all(_block_exits(handler.body) for handler in stmt.handlers)
            and (_block_exits(stmt.body) or _block_exits(stmt.orelse)))
    if _MATCH is not None and isinstance(stmt, _MATCH):
        last = stmt.cases[-1]
        return (last.guard is None and _irrefutable(last.pattern)
                and all(_block_exits(case.body) for case in stmt.cases))
    return False


def _blocks(node):
    # An except handler and a match case are nodes of their own with a body: ast.walk reaches them.
    for field in ("body", "orelse", "finalbody"):
        block = getattr(node, field, None)
        if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
            yield block


def unreachable(path):
    """[(line, column, message)] of the first statement after one that exits (`_exits`), once per block; columns
    from 1. Raises SyntaxError when this Python cannot parse the file (ruff's E9 reports a real one)."""
    with open(path, "rb") as f:
        tree = ast.parse(f.read(), path)
    found = []
    for node in ast.walk(tree):
        for block in _blocks(node):
            for before, dead in zip(block, block[1:]):
                if _exits(before):
                    name = type(before).__name__
                    found.append((dead.lineno, dead.col_offset + 1,
                                  "unreachable code after `%s`" % _NAMES.get(name, name.lower())))
                    break
    return sorted(found)


def _shown(path, cwd):
    try:
        return os.path.relpath(path, cwd)
    except ValueError:  # another drive
        return path


def report_unreachable(paths, cwd, output_format=None):
    """Print the unreachable statements of `paths`; their count. Ruff's concise form on stdout, GitHub annotations
    for `github`, the concise form on stderr for another machine format (stdout stays that format's own)."""
    out = sys.stdout if output_format in (None, "concise", "full", "github") else sys.stderr
    count = 0
    for path in paths:
        try:
            found = unreachable(path)
        except (SyntaxError, ValueError) as error:
            sys.stderr.write("MaxDrop lint: %s not parsed by Python %d.%d, unreachable-code check skipped: %s\n"
                             % (_shown(path, cwd), sys.version_info[0], sys.version_info[1], error))
            continue
        for line, col, message in found:
            where = "%s:%d:%d: %s" % (_shown(path, cwd), line, col, message)
            if output_format == "github":
                out.write("::error title=MaxDrop lint (unreachable),file=%s,line=%d,col=%d::%s\n"
                          % (_shown(path, cwd).replace(os.sep, "/"), line, col, where))
            else:
                out.write(where + "\n")
            count += 1
    if count:
        out.write("Found %d unreachable statement%s.\n" % (count, "" if count == 1 else "s"))
    out.flush()
    return count


# Ruff refuses these beside --show-files (and --add-noqa has rewritten files by then).
_NO_FILE_LIST = ("--statistics", "--add-noqa", "--show-settings", "--show-files", "--watch")


def _output_format(args):
    for i, arg in enumerate(args):
        if arg.startswith("--output-format="):
            return arg.split("=", 1)[1]
        if arg == "--output-format" and i + 1 < len(args):
            return args[i + 1]
    return None


def main(args, cwd=ROOT):
    try:
        version = pin()
    except (OSError, ValueError) as error:
        sys.stderr.write("MaxDrop lint: %s\n" % error)
        return NOT_FOUND
    ruff = find_ruff(version)
    if ruff is None:
        sys.stderr.write(
            "MaxDrop lint: no ruff %s found, neither `ruff` on PATH nor in the uv cache.\n"
            "Get it once with `uvx ruff@%s --version` (uv fetches it), or pip-install `ruff==%s` into a virtual\n"
            "environment of its own and put it on PATH (CONTRIBUTING.md).\n" % (version, version, version))
        return NOT_FOUND
    args = args or ["."]
    done = subprocess.run(ruff + ["check"] + args, cwd=cwd, capture_output=True)
    _echo(done.stdout, sys.stdout)
    _echo(done.stderr, sys.stderr)
    if done.returncode not in (0, 1):
        return done.returncode
    clash = [arg for arg in args if arg.split("=", 1)[0] in _NO_FILE_LIST]
    if clash:
        sys.stderr.write("MaxDrop lint: unreachable-code check skipped with %s\n" % clash[0])
        return done.returncode
    shown = subprocess.run(ruff + ["check"] + args + ["--show-files"], cwd=cwd, capture_output=True)
    if shown.returncode != 0:
        _echo(shown.stderr, sys.stderr)
        return shown.returncode
    paths = [os.path.join(cwd, line.strip()) for line in shown.stdout.decode("utf-8", "replace").splitlines()
             if line.strip().endswith(".py")]
    if report_unreachable(paths, cwd, _output_format(args)) and "--exit-zero" not in args:
        return 1
    return done.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
