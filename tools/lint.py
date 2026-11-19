# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run ruff on the tree at the version CI runs, the one `required-version` in pyproject.toml names.

    python -I tools/lint.py                              # ruff check .
    python -I tools/lint.py --output-format=github .     # the arguments go to `ruff check`

The ruff used is `ruff` on PATH when it is that version, otherwise `uvx --offline ruff@<version>` when uv has it
cached (`--offline`: never a download). Exit: ruff's own (0 clean, 1 findings), 2 when no ruff of that version is
found. Standard library only, Python 3.9 and later (no tomllib).
"""
import os
import re
import shutil
import subprocess
import sys

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


def main(args, cwd=ROOT):
    version = pin()
    ruff = find_ruff(version)
    if ruff is None:
        sys.stderr.write(
            "MaxDrop lint: no ruff %s found, neither `ruff` on PATH nor in the uv cache.\n"
            "Get it once with `uvx ruff@%s --version` (uv fetches it), or pip-install `ruff==%s` into a virtual\n"
            "environment of its own and activate it (CONTRIBUTING.md).\n" % (version, version, version))
        return 2
    done = subprocess.run(ruff + ["check"] + (args or ["."]), cwd=cwd, capture_output=True,
                          encoding="utf-8", errors="replace")
    sys.stdout.write(done.stdout)
    sys.stderr.write(done.stderr)
    return done.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
