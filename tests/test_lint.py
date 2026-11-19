# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ruff, locally as in CI: one version, written in pyproject.toml (`required-version`), and tools/lint.py running
it on the tree. The pin checks need no ruff; the lint checks run when tools/lint.py finds a ruff of that version
and skip with the reason otherwise.

    python -I -m unittest discover tests
"""
import contextlib
import importlib.util
import io
import os
import re
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location("lint", os.path.join(ROOT, "tools", "lint.py"))
lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def run_main(args, cwd):
    """The exit code and the output of `tools/lint.py <args>` run in `cwd`."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = lint.main(args, cwd=cwd)
    return code, out.getvalue()


class PinTest(unittest.TestCase):
    """The ruff version is written once, in pyproject.toml; CI and CONTRIBUTING read it from there."""

    def test_pyproject_pins_an_exact_version(self):
        self.assertRegex(lint.pin(), r"^\d+\.\d+\.\d+$")

    def test_pin_errors_without_required_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pyproject.toml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[tool.ruff]\nline-length = 120\n")
            with self.assertRaises(ValueError):
                lint.pin(path)

    def test_workflow_reads_the_pin(self):
        workflow = read(".github", "workflows", "test.yml")
        self.assertIsNone(re.search(r"ruff\s*[=@]=?\s*\d", workflow), "test.yml names a ruff version of its own")
        self.assertIn("required-version", workflow)
        self.assertIn("tools/lint.py", workflow)

    def test_contributing_names_no_version(self):
        text = read("CONTRIBUTING.md")
        self.assertIsNone(re.search(r"ruff\s*[=@]=?\s*\d", text), "CONTRIBUTING.md names a ruff version of its own")
        self.assertIn("required-version", text)


class LintTest(unittest.TestCase):
    """ruff check passes on the tree and fails on a module-level import below a statement (E402)."""

    @classmethod
    def setUpClass(cls):
        cls.ruff = lint.find_ruff(lint.pin())

    def setUp(self):
        if self.ruff is None:
            self.skipTest("no ruff %s on PATH or in the uvx cache (tools/lint.py says how to get it)" % lint.pin())

    def test_tree_passes(self):
        code, out = run_main(["--no-cache", "."], cwd=ROOT)
        self.assertEqual(code, 0, out)

    def test_e402_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(os.path.join(ROOT, "pyproject.toml"), tmp)
            with open(os.path.join(tmp, "probe.py"), "w", encoding="utf-8") as f:
                f.write("import os\n\nx = os.sep\n\nimport sys  # noqa: F401\n")
            code, out = run_main(["--no-cache", "."], cwd=tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("E402", out)


if __name__ == "__main__":
    unittest.main()
