# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""No code file over MAX_LINES lines (CLAUDE.md): the Python files under ROOTS. tests/ joins ROOTS once its last
files over the limit are split.

    python -I -m unittest discover tests
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOTS = ("maxdrop", "tools")
MAX_LINES = 1000


def python_files(top):
    for folder, dirs, files in os.walk(os.path.join(ROOT, top)):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(folder, name)


def line_count(path):
    with open(path, "rb") as f:  # bytes: the count does not depend on the locale's encoding
        return sum(1 for _ in f)


class FileSizeTest(unittest.TestCase):
    def test_no_python_file_over_the_limit(self):
        seen = 0
        over = []
        for top in ROOTS:
            for path in python_files(top):
                seen += 1
                count = line_count(path)
                if count > MAX_LINES:
                    over.append("%s: %d lines" % (os.path.relpath(path, ROOT), count))
        self.assertGreater(seen, 0)
        self.assertEqual(over, [], "over %d lines, split by responsibility:\n%s" % (MAX_LINES, "\n".join(over)))


if __name__ == "__main__":
    unittest.main()
