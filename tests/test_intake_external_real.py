# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/intake/external.py with the real programs: each one found at its standard place on the
test packs of tests/fixtures/packs/, every case printed as RAN or SKIPPED with the reason; the registration
of the backends.

    python -I -m unittest discover tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
import zipfile

_TESTS = "maxdrop_tests"  # tests/ as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_tests.intake_external_support import (  # noqa: E402 (after the loader)
    archive, BSDTAR, EXPECTED, external, folder_files, INTAKE, PackError, PACKS, PY, ROOT, say,
    SEVENZIP, TempCase, TREE, UNRAR,
)


def _real_tools():
    tools, notes = {}, []
    usable, old = external.find_tools((UNRAR, SEVENZIP, BSDTAR))
    for t in usable:
        tools[t.flavor] = t
    for t in old:
        notes.append("%s at %s is below its floor %s" % (t.label, t.path, external.version_text(
            external.FLOORS[t.flavor], t.flavor)))
    extra = os.environ.get("MAXDROP_TEST_7Z")
    if extra and SEVENZIP not in tools:
        t = external.probe(SEVENZIP, extra)
        if t is None:
            notes.append("MAXDROP_TEST_7Z=%s is not a 7-Zip" % extra)
        elif t.too_old:
            notes.append("MAXDROP_TEST_7Z is %s, below the floor" % t.label)
        else:
            tools[SEVENZIP] = t
    return tools, notes


REAL, REAL_NOTES = _real_tools()


def _required(text):
    """The flavors MAXDROP_REQUIRE_TOOLS names (unknown names kept, for RequiredToolTests to name them)."""
    return {n.strip() for n in (text or "").split(",") if n.strip()}


REQUIRED = _required(os.environ.get("MAXDROP_REQUIRE_TOOLS"))


class RequiredToolTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(_required(None), set())
        self.assertEqual(_required(""), set())
        self.assertEqual(_required(" unrar , 7z,,bsdtar "), {UNRAR, SEVENZIP, BSDTAR})

    def test_known_names(self):
        unknown = sorted(REQUIRED - set(external.LABELS))
        self.assertFalse(unknown, "MAXDROP_REQUIRE_TOOLS names no program: %s (known: %s)"
                         % (", ".join(unknown), ", ".join(sorted(external.LABELS))))

    def test_required_found(self):
        missing = sorted(f for f in REQUIRED & set(external.LABELS) if f not in REAL)
        self.assertFalse(missing, "MAXDROP_REQUIRE_TOOLS requires %s, not found at its standard place or below its "
                         "floor%s" % (", ".join(external.LABELS[f] for f in missing),
                                      "".join("; " + n for n in REAL_NOTES)))


def _zip_reference(tmp):
    """What the zip backend unpacks from the same tree."""
    path = os.path.join(tmp, "reference.zip")
    with zipfile.ZipFile(path, "w") as z:
        for name, data in TREE.items():
            z.writestr(name, data)
    return folder_files(archive.unpack(path, dest_parent=tmp).folder)


class RealToolTests(TempCase):
    CASES = {UNRAR: ("normal.rar", "solid.rar"), SEVENZIP: ("normal.rar", "solid.rar", "plain.7z"),
             BSDTAR: ("normal.rar", "solid.rar", "plain.7z")}

    @classmethod
    def setUpClass(cls):
        for note in REAL_NOTES:
            sys.stderr.write("\n  real tool: note: %s" % note)
        # Which file runs: a newer copy elsewhere on the search path would be taken before the one CI installs.
        for t in REAL.values():
            sys.stderr.write("\n  real tool: using %s at %s" % (t.label, t.path))

    def setUp(self):
        super().setUp()
        saved = dict(archive._BACKENDS)
        self.addCleanup(lambda: (archive._BACKENDS.clear(), archive._BACKENDS.update(saved)))

    def copy(self, name):
        dest = os.path.join(self.tmp, name)
        shutil.copyfile(os.path.join(PACKS, name), dest)
        return dest

    def only(self, tool):
        for k in ("rar", "7z"):
            archive._BACKENDS[k] = external.ExternalBackend(k, tools=[tool])

    def tools_for(self, case, flavors=(UNRAR, SEVENZIP, BSDTAR)):
        """(tool, label) of each program present; a SKIPPED line for each one missing. A required one missing
        fails RequiredToolTests, here only when no program is present: the ones present still run and print RAN."""
        found, required = [], []
        for flavor in flavors:
            label = "%s: %s" % (external.LABELS[flavor], case)
            tool = REAL.get(flavor)
            if tool is None:
                say(label, False, "%s not found at its standard place or below its floor" % external.LABELS[flavor])
                if flavor in REQUIRED:
                    required.append(external.LABELS[flavor])
            else:
                found.append((tool, "%s (%s)" % (label, tool.path)))
        if not found:
            if required:
                self.fail("no unpacker here, MAXDROP_REQUIRE_TOOLS requires %s" % ", ".join(required))
            self.skipTest("no unpacker here")
        return found

    def test_same_files_as_the_zip_backend(self):
        reference = _zip_reference(self.tmp)
        self.assertEqual(reference, EXPECTED)
        for name in ("normal.rar", "solid.rar", "plain.7z"):
            flavors = [f for f in (UNRAR, SEVENZIP, BSDTAR) if name in self.CASES[f]]
            for tool, label in self.tools_for("unpack %s" % name, flavors):
                with self.subTest(tool=tool.label):
                    self.only(tool)
                    case_dir = tempfile.mkdtemp(dir=self.tmp)
                    pack = os.path.join(case_dir, name)
                    shutil.copyfile(os.path.join(PACKS, name), pack)
                    listing = archive.list_pack(pack)
                    self.assertEqual([os.path.basename(s.replace("\\", "/")) for s in listing.scenes], ["scene.max"])
                    result = archive.unpack(pack)
                    self.assertEqual(folder_files(result.folder), reference)
                    self.assertEqual(result.backend, tool.label)
                    # Two wood.jpg: the one beside the scene is kept, the other reported.
                    self.assertEqual([c.replace("\\", "/") for c in result.collided], ["pack/other/wood.jpg"])
                    self.assertEqual(sorted(os.listdir(case_dir)), sorted([name, name.rsplit(".", 1)[0]]))
                    say(label, True)

    def test_cancelled_by_the_watch(self):
        """A watch that raises Cancelled ends the program and leaves only the pack in its folder."""
        for name in ("normal.rar", "plain.7z"):
            flavors = [f for f in (UNRAR, SEVENZIP, BSDTAR) if name in self.CASES[f]]
            for tool, label in self.tools_for("cancel %s" % name, flavors):
                with self.subTest(tool=tool.label, pack=name):
                    self.only(tool)
                    case_dir = tempfile.mkdtemp(dir=self.tmp)
                    pack = os.path.join(case_dir, name)
                    shutil.copyfile(os.path.join(PACKS, name), pack)
                    seen = []

                    def stop(n):
                        seen.append(n)
                        raise archive.Cancelled()

                    with self.assertRaises(archive.Cancelled):
                        archive.unpack(pack, watch=stop)
                    self.assertEqual(seen, [0])
                    self.assertEqual(os.listdir(case_dir), [name])
                    say(label, True)

    def test_references_unpack_only_the_named_maps(self):
        """Two phases through one program: the scene alone, then only the maps its asset list names."""
        for name in ("normal.rar", "solid.rar", "plain.7z"):
            flavors = [f for f in (UNRAR, SEVENZIP, BSDTAR) if name in self.CASES[f]]
            for tool, label in self.tools_for("references, %s" % name, flavors):
                with self.subTest(tool=tool.label, pack=name):
                    self.only(tool)
                    case_dir = tempfile.mkdtemp(dir=self.tmp)
                    pack = os.path.join(case_dir, name)
                    shutil.copyfile(os.path.join(PACKS, name), pack)
                    asked = []

                    def refs(max_path):
                        # The scene is on disk, alone, before any map is asked for.
                        with open(max_path, "rb") as f:
                            asked.append((max_path, f.read(), sorted(os.listdir(os.path.dirname(max_path)))))
                        return ["wood.jpg"]

                    result = archive.unpack(pack, references=refs)
                    self.assertEqual(len(asked), 1)
                    staged, data, beside = asked[0]
                    self.assertEqual(data, TREE["pack/scene/scene.max"])
                    self.assertEqual(beside, ["scene.max"])
                    # Asked about the staged scene: in a staging folder beside the pack, not the final folder.
                    self.assertEqual(os.path.normcase(os.path.dirname(os.path.dirname(staged))),
                                     os.path.normcase(case_dir))
                    self.assertTrue(os.path.basename(os.path.dirname(staged)).startswith(archive.STAGING_PREFIX))
                    self.assertEqual(folder_files(result.folder),
                                     {"scene.max": TREE["pack/scene/scene.max"], "wood.jpg": b"near wood"})
                    self.assertEqual((result.mode, result.written, result.unwanted), ("unpacked", 2, 2))
                    self.assertEqual([c.replace("\\", "/") for c in result.collided], ["pack/other/wood.jpg"])
                    self.assertEqual(result.backend, tool.label)
                    self.assertEqual(archive._read_marker(result.folder)["wanted"], ["wood.jpg"])
                    self.assertEqual(sorted(os.listdir(case_dir)), sorted([name, name.rsplit(".", 1)[0]]))
                    say(label, True)

    def test_password_on_the_data(self):
        for tool, label in self.tools_for("pwdata.rar -> PackError, nothing left", (UNRAR, SEVENZIP, BSDTAR)):
            with self.subTest(tool=tool.label):
                self.only(tool)
                case_dir = tempfile.mkdtemp(dir=self.tmp)
                pack = os.path.join(case_dir, "pwdata.rar")
                shutil.copyfile(os.path.join(PACKS, "pwdata.rar"), pack)
                start = time.monotonic()
                # The message comes from the program; an older libarchive may not name the password.
                with self.assertRaisesRegex(PackError, "encrypted|password|could not be unpacked"):
                    archive.unpack(pack)
                self.assertLess(time.monotonic() - start, 30)
                self.assertEqual(os.listdir(case_dir), ["pwdata.rar"])
                say(label, True)

    def test_tar_discards_garbage_of_encrypted_data(self):
        # bsdtar lists no encryption flag and writes full-size garbage, exiting 1: the work folder must go.
        for tool, label in self.tools_for("pwdata.rar extraction exit 1 discarded", (BSDTAR,)):
            with self.subTest(tool=tool.label):
                self.only(tool)
                case_dir = tempfile.mkdtemp(dir=self.tmp)
                pack = os.path.join(case_dir, "pwdata.rar")
                shutil.copyfile(os.path.join(PACKS, "pwdata.rar"), pack)
                entries = external.list_entries(tool, pack)
                self.assertFalse(any(e.encrypted for e in entries))
                with self.assertRaisesRegex(PackError, "password-protected|could not be unpacked"):
                    archive.unpack(pack)
                self.assertEqual(os.listdir(case_dir), ["pwdata.rar"])
                say(label, True)

    def make_7z(self, tool, files):
        """A .7z written by bsdtar from files {relative path: data}, in a folder of its own."""
        src = os.path.join(self.tmp, "src")
        for rel, data in files.items():
            path = os.path.abspath(os.path.join(src, *rel.split("/")))
            if os.name == "nt":  # written through the extended form, independent of the code under test
                path = "\\\\?\\" + path
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        case_dir = tempfile.mkdtemp(dir=self.tmp)
        pack = os.path.join(case_dir, "made.7z")
        tops = sorted({rel.split("/")[0] for rel in files})
        done = subprocess.run([tool.path, "-a", "-cf", pack, "-C", src] + tops, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=60)
        if done.returncode != 0:
            self.skipTest("bsdtar could not write the test pack: %r" % done.stderr[-300:])
        return case_dir, pack

    def test_tar_brackets_and_wildcards_in_folder_names(self):
        for tool, label in self.tools_for("[ ] in folder and file names", (BSDTAR,)):
            with self.subTest(tool=tool.label):
                self.only(tool)
                case_dir, pack = self.make_7z(tool, {"[site] room/scene.max": b"S", "[site] room/wood[1].jpg": b"W"})
                result = archive.unpack(pack)
                self.assertEqual(folder_files(result.folder), {"scene.max": b"S", "wood[1].jpg": b"W"})
                say(label, True)

    def test_tar_deep_paths(self):
        """Deeper than Windows' 260 characters: unpacked, and nothing left behind on failure either."""
        deep = "/".join(["d%02d_%s" % (i, "x" * 40) for i in range(6)])
        for tool, label in self.tools_for("paths over 260 characters", (BSDTAR,)):
            with self.subTest(tool=tool.label):
                self.only(tool)
                case_dir, pack = self.make_7z(tool, {"pack/%s/scene.max" % deep: b"S",
                                                     "pack/%s/wood.jpg" % deep: b"W"})
                result = archive.unpack(pack)
                self.assertEqual(folder_files(result.folder), {"scene.max": b"S", "wood.jpg": b"W"})
                self.assertEqual(sorted(os.listdir(case_dir)), ["made", "made.7z"])
                say(label, True)

    def test_password_on_the_headers(self):
        pack = self.copy("pwhead.rar")
        for tool, label in self.tools_for("pwhead.rar -> PackError, no prompt, no hang"):
            with self.subTest(tool=tool.label):
                self.only(tool)
                with self.assertRaisesRegex(PackError, "password-protected"):
                    archive.unpack(pack)
                # The program itself, past the header check: it must end on its own, without a prompt.
                start = time.monotonic()
                with self.assertRaises(external.ToolFailed) as caught:
                    external.list_entries(tool, pack)
                self.assertLess(time.monotonic() - start, external.LIST_SECONDS)
                self.assertNotIn("did not finish", str(caught.exception))
                say(label, True)
        self.assertEqual(os.listdir(self.tmp), ["pwhead.rar"])

    def test_discovered_chain(self):
        """The backends archive/ really registers: the first usable program of the chain."""
        if not REAL:
            say("discovered chain: normal.rar", False, "no unpacker here")
            if REQUIRED:
                self.fail("no unpacker here, MAXDROP_REQUIRE_TOOLS is %s" % ", ".join(sorted(REQUIRED)))
            self.skipTest("no unpacker here")
        archive._BACKENDS["rar"] = external.ExternalBackend("rar")
        pack = self.copy("normal.rar")
        result = archive.unpack(pack)
        self.assertEqual(folder_files(result.folder), EXPECTED)
        say("discovered chain: normal.rar with %s" % result.backend, True)


class RegistrationTests(unittest.TestCase):
    def test_install(self):
        self.assertIsInstance(archive._BACKENDS[archive.KIND_RAR], external.ExternalBackend)
        self.assertIsInstance(archive._BACKENDS[archive.KIND_7Z], external.ExternalBackend)
        self.assertIsInstance(archive._BACKENDS[archive.KIND_ZIP], archive.ZipBackend)

    def test_archive_registers_in_its_package(self):
        """Imported as maxdrop.intake.archive (without maxdrop/__init__.py, which needs bpy), archive/ registers
        the external backends itself."""
        code = ("import importlib.util, sys, types\n"
                "pkg = types.ModuleType('mdpkg'); pkg.__path__ = [%r]; sys.modules['mdpkg'] = pkg\n"
                "import mdpkg.intake.archive as a\n"
                "print(type(a._BACKENDS['rar']).__name__, type(a._BACKENDS['7z']).__name__)\n"
                % os.path.join(ROOT, "maxdrop"))
        out = subprocess.run([PY, "-I", "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.split(), ["ExternalBackend", "ExternalBackend"])

    def test_no_bpy(self):
        with open(os.path.join(INTAKE, "external.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("import bpy", "from bpy", "mathutils", "shell=True", "os.system", "extractall"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
