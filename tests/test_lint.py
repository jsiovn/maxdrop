# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ruff, locally as in CI: one version, written in pyproject.toml (`required-version`), and tools/lint.py running
it on the tree, then its own unreachable-code check. The pin checks, the unreachable-code check and main() with a
stand-in ruff need no ruff (CI installs ruff only after the plain tests); the lint checks run when tools/lint.py
finds a ruff of that version and skip with the reason otherwise.

    python -I -m unittest discover tests
"""
import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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


class FindTest(unittest.TestCase):
    """Which ruff tools/lint.py runs, and what it says when there is none; no ruff needed."""

    def test_wrong_version_on_path_falls_through_to_uvx(self):
        which = {"ruff": "/bin/ruff", "uvx": "/bin/uvx"}.get
        with mock.patch.object(lint.shutil, "which", which), \
                mock.patch.object(lint, "_prints_version", lambda argv, version: argv[0] == "/bin/uvx"):
            self.assertEqual(lint.find_ruff("1.2.3"), ["/bin/uvx", "--offline", "ruff@1.2.3"])

    def test_matching_ruff_on_path_wins(self):
        which = {"ruff": "/bin/ruff", "uvx": "/bin/uvx"}.get
        with mock.patch.object(lint.shutil, "which", which), \
                mock.patch.object(lint, "_prints_version", lambda argv, version: True):
            self.assertEqual(lint.find_ruff("1.2.3"), ["/bin/ruff"])

    def test_none_found_exits_not_found_with_instructions(self):
        with mock.patch.object(lint.shutil, "which", lambda name: None):
            code, out = run_main([], cwd=ROOT)
        self.assertEqual(code, lint.NOT_FOUND)
        self.assertNotIn(code, (0, 1, 2), "ruff's own exit codes")
        self.assertIn("no ruff %s found" % lint.pin(), out)

    def test_missing_pin_exits_not_found(self):
        with mock.patch.object(lint, "pin", side_effect=ValueError("no required-version")):
            code, out = run_main([], cwd=ROOT)
        self.assertEqual(code, lint.NOT_FOUND)
        self.assertIn("no required-version", out)


DEAD_TEST = '''import unittest


def helper():
    return 1


class Case(unittest.TestCase):
    def test_a(self):
        self.assertEqual(helper(), 1)

    def other(self):
        return 2

        def test_b(self):
            self.assertTrue(True)
'''


class UnreachableTest(unittest.TestCase):
    """The check ruff has no rule for at the pin: a statement after return, raise, continue or break in the same
    block, or after a with, if/else, try or match no path through falls out of (maxdrop-em3.111 lost two tests
    that way). No ruff needed."""

    def findings(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "probe.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
            return lint.unreachable(path)

    def test_def_after_return_inside_a_class(self):
        found = self.findings(DEAD_TEST)
        self.assertEqual([(line, col) for line, col, _ in found], [(15, 9)])
        self.assertIn("return", found[0][2])

    def test_bom_and_decorated_def(self):
        source = ("\ufeffclass C:\n    def f(self):\n        return 1\n\n"
                  "        @staticmethod\n        def g():\n            pass\n")
        self.assertEqual([line for line, _, _ in self.findings(source)], [6])

    def test_clean_file(self):
        self.assertEqual(self.findings("def f(x):\n    if x:\n        return 1\n    return 2\n"), [])

    def test_every_terminal_and_block(self):
        source = (
            "def f(xs):\n"
            "    for x in xs:\n"
            "        if x:\n"
            "            continue\n"
            "            x += 1\n"            # 5: after continue in an if body
            "        else:\n"
            "            break\n"
            "            x -= 1\n"            # 8: after break in an else
            "    try:\n"
            "        pass\n"
            "    except ValueError:\n"
            "        raise\n"
            "        pass\n"              # 13: after raise in an except
            "    finally:\n"
            "        return 0\n"
            "        f(xs)\n"             # 16: after return in a finally
        )
        self.assertEqual([line for line, _, _ in self.findings(source)], [5, 8, 13, 16])

    def test_one_finding_per_block(self):
        self.assertEqual(len(self.findings("def f():\n    return 1\n    a = 1\n    b = 2\n")), 1)

    def lines(self, source):
        return [line for line, _, _ in self.findings(source)]

    def test_def_after_with_that_returns(self):
        # maxdrop-6n0.7.1: the helper's last statement holds the return, the test def after it is nested.
        source = ("class T:\n"
                  "    def read(self, p):\n"
                  "        with open(p) as f:\n"
                  "            return f.read()\n"
                  "        def test_b(self):\n"      # 5
                  "            pass\n")
        found = self.findings(source)
        self.assertEqual([(line, col) for line, col, _ in found], [(5, 9)])
        self.assertIn("`with`", found[0][2])
        self.assertEqual(self.lines(source.replace("with open", "async with open")), [5])

    def test_after_if_else_both_exiting(self):
        self.assertEqual(self.lines("def f(x):\n    if x:\n        return 1\n    else:\n        raise ValueError\n"
                                    "    x = 2\n"), [6])
        self.assertEqual(self.lines("def f(x):\n    if x:\n        return 1\n    elif x is None:\n"
                                    "        return 2\n    else:\n        return 3\n    x = 2\n"), [8])
        # A body ending in a nested if/else that exits on both branches exits too.
        self.assertEqual(self.lines("def f(x, y):\n    with x:\n        if y:\n            return 1\n"
                                    "        else:\n            return 2\n    y = 3\n"), [7])

    def test_after_try_except_both_returning(self):
        self.assertEqual(self.lines("def f():\n    try:\n        return g()\n    except OSError:\n"
                                    "        return None\n    h()\n"), [6])
        # try/finally whose finally returns; a body that returns with else and handlers returning.
        self.assertEqual(self.lines("def f():\n    try:\n        g()\n    finally:\n        return 1\n    h()\n"),
                         [6])
        self.assertEqual(self.lines("def f():\n    try:\n        g()\n    except OSError:\n        raise\n"
                                    "    else:\n        return 1\n    h()\n"), [8])
        # One handler falls through: the statement after the try runs.
        self.assertEqual(self.lines("def f():\n    try:\n        return g()\n    except OSError:\n"
                                    "        return None\n    except ValueError:\n        pass\n    h()\n"), [])

    def test_not_after_loop_or_open_if(self):
        self.assertEqual(self.lines("def f(xs):\n    for x in xs:\n        return x\n    return None\n"), [])
        self.assertEqual(self.lines("def f():\n    while True:\n        return 1\n    return None\n"), [])
        self.assertEqual(self.lines("def f(x):\n    if x:\n        return 1\n    return 2\n"), [])
        self.assertEqual(self.lines("def f(x):\n    if x:\n        return 1\n    else:\n        x = 0\n"
                                    "    return x\n"), [])
        self.assertEqual(self.lines("def f(x):\n    with x:\n        pass\n    return x\n"), [])

    def test_not_after_with_that_raises(self):
        # __exit__ may swallow the exception (assertRaises, contextlib.suppress): the next statement runs.
        self.assertEqual(self.lines("def f(cm):\n    with cm:\n        raise ValueError\n    return 1\n"), [])
        self.assertEqual(self.lines("def f(self, staging, dest):\n    with self.assertRaises(RuntimeError):\n"
                                    "        with staging(dest):\n            raise RuntimeError('boom')\n"
                                    "    self.assertFalse(dest)\n"), [])
        self.assertEqual(self.lines("def f(cm, x):\n    with cm:\n        if x:\n            raise KeyError\n"
                                    "        else:\n            raise ValueError\n    return 1\n"), [])
        # A raise inside the with still makes what follows it inside the body dead.
        self.assertEqual(self.lines("def f(cm):\n    with cm:\n        raise ValueError\n        g()\n"), [4])

    def test_nested_compound_inside_loop(self):
        source = ("def f(xs):\n"
                  "    for x in xs:\n"
                  "        with x:\n"
                  "            continue\n"
                  "        x.close()\n"          # 5: dead inside the loop
                  "    return xs\n")             # 6: the loop is never terminal
        self.assertEqual(self.lines(source), [5])

    @unittest.skipIf(sys.version_info < (3, 10), "match needs Python 3.10")
    def test_after_match_with_wildcard(self):
        head = "def f(x):\n    match x:\n        case 1:\n            return 1\n"
        self.assertEqual(self.lines(head + "        case _:\n            return 2\n    x = 3\n"), [7])
        self.assertEqual(self.lines(head + "        case 2 | _:\n            return 2\n    x = 3\n"), [7])
        self.assertEqual(self.lines(head + "        case (_ as y):\n            return y\n    x = 3\n"), [7])
        self.assertEqual(self.lines(head + "        case 2:\n            return 2\n    x = 3\n"), [])
        self.assertEqual(self.lines(head + "        case _ if x:\n            return 2\n    x = 3\n"), [])
        self.assertEqual(self.lines(head + "        case _:\n            pass\n    x = 3\n"), [])

    def test_with_is_taken_not_to_swallow(self):
        # The known limit: a with whose body returns is terminal even when __exit__ swallows what the body's own
        # calls raise, so the fallback after `with suppress(...): return ...` is flagged; write it as try/except.
        self.assertEqual(self.lines("def get(d, k):\n    with suppress(KeyError):\n        return d[k]\n"
                                    "    return None\n"), [4])

    def test_syntax_error_is_raised_for_main_to_note(self):
        # Ruff's E9 reports it; main() prints a note and goes on with the other files.
        with self.assertRaises(SyntaxError):
            self.findings("def f(:\n    return\n")

    def test_syntax_error_does_not_stop_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.py")
            with open(bad, "w", encoding="utf-8") as f:
                f.write("def f(:\n")
            dead = os.path.join(tmp, "dead.py")
            with open(dead, "w", encoding="utf-8") as f:
                f.write(DEAD_TEST)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                count = lint.report_unreachable([bad, dead], tmp)
        self.assertEqual(count, 1)
        self.assertIn("dead.py:15:9:", out.getvalue())
        self.assertIn("bad.py", out.getvalue())


class MainWiringTest(unittest.TestCase):
    """main() runs the unreachable-code check on the files ruff lists, with a stand-in ruff: no ruff needed."""

    def run_fake(self, args, check_code=0, listed=("dead.py", "notes.txt")):
        calls = []

        def run(argv, cwd, capture_output):
            calls.append(argv)
            if argv[-1] == "--show-files":
                listing = "".join(os.path.join(cwd, name) + "\n" for name in listed)
                return subprocess.CompletedProcess(argv, 0, listing.encode("utf-8"), b"")
            return subprocess.CompletedProcess(argv, check_code, b"All checks passed!\n", b"")

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "dead.py"), "w", encoding="utf-8") as f:
                f.write(DEAD_TEST)
            with open(os.path.join(tmp, "notes.txt"), "w", encoding="utf-8") as f:
                f.write("return\nx\n")
            with mock.patch.object(lint, "find_ruff", lambda version: ["ruff"]), \
                    mock.patch.object(lint.subprocess, "run", run):
                code, out = run_main(args, cwd=tmp)
        return code, out, calls

    def test_finding_turns_a_clean_check_into_1(self):
        code, out, calls = self.run_fake(["."])
        self.assertEqual(code, 1, out)
        self.assertIn("dead.py:15:9: unreachable code after `return`", out)
        self.assertNotIn("notes.txt", out)
        self.assertEqual(calls, [["ruff", "check", "."], ["ruff", "check", ".", "--show-files"]])

    def test_no_arguments_check_the_tree(self):
        _, _, calls = self.run_fake([])
        self.assertEqual(calls[0], ["ruff", "check", "."])

    def test_clean_listing_keeps_ruffs_code(self):
        self.assertEqual(self.run_fake(["."], listed=())[0], 0)
        self.assertEqual(self.run_fake(["."], check_code=1, listed=())[0], 1)

    def test_ruff_error_is_returned_before_the_check(self):
        code, _, calls = self.run_fake(["."], check_code=2)
        self.assertEqual(code, 2)
        self.assertEqual(len(calls), 1)

    def test_exit_zero(self):
        code, out, _ = self.run_fake(["--exit-zero", "."])
        self.assertEqual(code, 0)
        self.assertIn("dead.py:15:9:", out)

    def test_flags_ruff_refuses_beside_show_files_skip_the_check(self):
        for flag in ("--statistics", "--add-noqa"):
            code, out, calls = self.run_fake([flag, "."])
            self.assertEqual(code, 0, flag)
            self.assertEqual(len(calls), 1, flag)
            self.assertIn("skipped with " + flag, out)

    def test_machine_format_keeps_stdout_its_own(self):
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            dead = os.path.join(tmp, "dead.py")
            with open(dead, "w", encoding="utf-8") as f:
                f.write(DEAD_TEST)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                count = lint.report_unreachable([dead], tmp, "json")
        self.assertEqual((count, out.getvalue()), (1, ""))
        self.assertIn("dead.py:15:9:", err.getvalue())

    def test_output_format_forms(self):
        self.assertEqual(lint._output_format(["--output-format=github", "."]), "github")
        self.assertEqual(lint._output_format(["--output-format", "json", "."]), "json")
        self.assertIsNone(lint._output_format(["."]))


class LintTest(unittest.TestCase):
    """ruff check passes on the tree and fails on a module-level import below a statement (E402); the
    unreachable-code check of tools/lint.py runs on the files ruff checks."""

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

    def test_unreachable_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(os.path.join(ROOT, "pyproject.toml"), tmp)
            with open(os.path.join(tmp, "probe.py"), "w", encoding="utf-8") as f:
                f.write(DEAD_TEST)
            code, out = run_main(["--no-cache", "."], cwd=tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("probe.py:15:9:", out)

    def test_unreachable_as_github_annotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(os.path.join(ROOT, "pyproject.toml"), tmp)
            with open(os.path.join(tmp, "probe.py"), "w", encoding="utf-8") as f:
                f.write(DEAD_TEST)
            code, out = run_main(["--no-cache", "--output-format=github", "."], cwd=tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("::error ", out)
        self.assertIn("line=15,col=9", out)

    def test_non_ascii_finding_reaches_a_cp1252_stdout(self):
        # A redirected stdout on Windows is cp1252; ruff quotes the source line of a finding.
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(os.path.join(ROOT, "pyproject.toml"), tmp)
            with open(os.path.join(tmp, "probe.py"), "w", encoding="utf-8") as f:
                f.write("import os\n\nx = os.sep\n\nimport sys  # noqa: F401  \u2194\n")
            raw = io.BytesIO()
            stdout = io.TextIOWrapper(raw, encoding="cp1252")
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                code = lint.main(["--no-cache", "."], cwd=tmp)
            stdout.flush()
        self.assertEqual(code, 1)
        self.assertIn(b"E402", raw.getvalue())
        self.assertIn("\u2194".encode("utf-8"), raw.getvalue())


if __name__ == "__main__":
    unittest.main()
