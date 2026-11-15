# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/intake/external.py, the .rar and .7z backends that run a program already on the computer.

The argument builders, the listing parsers, the version floors, the header checks and the process runner are
tested without any unpacker (the runner with Python children). The real-tool tests run each program found at its
standard place on the test packs of tests/fixtures/packs/ and print every case as RAN or SKIPPED with the reason,
so a green run never hides that nothing ran. MAXDROP_TEST_7Z may name a 7-Zip outside the standard folders (a
portable copy) for the 7-Zip cases.

    python -I -m unittest discover tests
"""
import importlib.util
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTAKE = os.path.join(ROOT, "maxdrop", "intake")
PACKS = os.path.join(ROOT, "tests", "fixtures", "packs")


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(INTAKE, file))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# By path: `import maxdrop` would pull bpy. A name of its own, so tests/test_intake.py keeps a zip-only archive.py.
archive = _load("maxdrop_intake_archive_ext", "archive.py")
external = _load("maxdrop_intake_external", "external.py")
external.install(archive)

PackError = archive.PackError
Tool = external.Tool
UNRAR, SEVENZIP, BSDTAR = external.UNRAR, external.SEVENZIP, external.BSDTAR

# What every test pack holds.
TREE = {
    "pack/scene/scene.max": b"MAXDROP TEST SCENE",
    "pack/scene/maps/wood.jpg": b"near wood",
    "pack/other/wood.jpg": b"far wood",
    "pack/sub dir/my map.png": b"map with a space",
    "pack/scene/light.IES": b"ies",
    "pack/readme.txt": b"not unpacked",
}
EXPECTED = {"scene.max": b"MAXDROP TEST SCENE", "wood.jpg": b"near wood", "my map.png": b"map with a space",
            "light.IES": b"ies"}

PY = sys.executable


def say(case, ran, reason=""):
    sys.stderr.write("\n  real tool: %s: %s" % (case, "RAN" if ran else "SKIPPED (%s)" % reason))
    sys.stderr.flush()


def folder_files(folder):
    out = {}
    for name in os.listdir(folder):
        if name != archive.MARKER:
            with open(os.path.join(folder, name), "rb") as f:
                out[name] = f.read()
    return out


def rar5_header(htype, hflags=0, aflags=0, extra=()):
    body = bytes([htype, hflags]) + bytes(extra) + bytes([aflags])
    return b"Rar!\x1a\x07\x01\x00" + b"\0\0\0\0" + bytes([len(body)]) + body + b"\0" * 32


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maxdrop-ext-")
        self.addCleanup(external._remove_tree, external._long(self.tmp))



class VersionTests(unittest.TestCase):
    def test_banners(self):
        cases = [
            (UNRAR, "\nUNRAR 7.23 x64 freeware      Copyright (c) 1993-2026 Alexander Roshal\n", (7, 23)),
            (SEVENZIP, "\n7-Zip 26.06 (x64) : Copyright (c) 1999-2026 Igor Pavlov : 2026-11-06\n", (26, 6)),
            (SEVENZIP, "\n7-Zip [64] 16.02 : Copyright (c) 1999-2016 Igor Pavlov : 2016-05-21\n", (16, 2)),
            (SEVENZIP, "\n7-Zip (z) 23.01 (x64) : Copyright (c) 1999-2023 Igor Pavlov\n", (23, 1)),
            (BSDTAR, "bsdtar 3.8.9 - libarchive 3.8.9 zlib/1.2.13.1-motley liblzma/5.8.3\n", (3, 8, 9)),
            (BSDTAR, "bsdtar 3.5.3 - libarchive 3.7.4 zlib/1.2.12 liblzma/5.4.3\n", (3, 7, 4)),
            (BSDTAR, "tar (GNU tar) 1.35\nCopyright (C) 2023 Free Software Foundation, Inc.\n", None),
            (UNRAR, "RAR 7.23 x64   Copyright (c) 1993-2026 Alexander Roshal\n", None),
            (SEVENZIP, "UNRAR 7.23 x64 freeware\n", None),
        ]
        for flavor, text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(external.parse_version(flavor, text), expected)

    def test_floors(self):
        self.assertTrue(Tool(UNRAR, "x", (7, 13)).too_old)
        self.assertFalse(Tool(UNRAR, "x", (7, 23)).too_old)
        self.assertTrue(Tool(SEVENZIP, "x", (25, 0)).too_old)
        self.assertFalse(Tool(SEVENZIP, "x", (25, 1)).too_old)
        self.assertTrue(Tool(SEVENZIP, "x", (16, 2)).too_old)
        self.assertTrue(Tool(BSDTAR, "x", (3, 7, 3)).too_old)
        self.assertFalse(Tool(BSDTAR, "x", (3, 7, 4)).too_old)
        # A distribution's bsdtar: its number says nothing.
        self.assertFalse(Tool(BSDTAR, "/usr/bin/bsdtar", (3, 7, 2), system=True).too_old)
        self.assertEqual(Tool(UNRAR, "x", (7, 23)).label, "UnRAR 7.23")
        self.assertEqual(Tool(SEVENZIP, "x", (25, 1)).label, "7-Zip 25.01")
        self.assertEqual(Tool(BSDTAR, "x", (3, 7, 4)).label, "bsdtar 3.7.4")


class DiscoveryTests(TempCase):
    def make(self, name, data, executable=True):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        if executable:
            os.chmod(path, 0o755)
        return path

    def test_real_executable(self):
        native = b"MZ\x90\x00" if os.name == "nt" else b"\x7fELF"
        good = self.make("tool.exe" if os.name == "nt" else "tool", native + b"\0" * 64)
        self.assertTrue(external.real_executable(good))
        self.assertFalse(external.real_executable(os.path.basename(good)), "a bare name")
        self.assertFalse(external.real_executable(self.make("tool.bat", b"@echo off\r\n")))
        if os.name == "nt":  # a .cmd runs through cmd.exe, whatever its bytes
            self.assertFalse(external.real_executable(self.make("tool.cmd", native + b"\0" * 64)))
        self.assertFalse(external.real_executable(self.make("script", b"#!/bin/sh\nexec x\n")))
        self.assertFalse(external.real_executable(self.tmp), "a folder")
        self.assertFalse(external.real_executable(os.path.join(self.tmp, "missing.exe")))
        # Never a program inside the pack's folder.
        self.assertFalse(external.real_executable(good, pack_dir=self.tmp))
        other = tempfile.mkdtemp(prefix="maxdrop-ext-pack-")
        self.addCleanup(shutil.rmtree, other, True)
        self.assertTrue(external.real_executable(good, pack_dir=other))
        # A pack in a folder above the program (a drive root) does not hide it.
        self.assertTrue(external.real_executable(good, pack_dir=os.path.dirname(self.tmp)))
        self.assertTrue(external.real_executable(good, pack_dir=os.path.splitdrive(self.tmp)[0] + os.sep))

    def test_find_tools_order_floor_and_duplicates(self):
        tools = {"/a/unrar-old": Tool(UNRAR, "/a/unrar-old", (7, 1)), "/b/unrar": Tool(UNRAR, "/b/unrar", (7, 23)),
                 "/c/unrar": Tool(UNRAR, "/c/unrar", (7, 30)), "/d/tar": Tool(BSDTAR, "/d/tar", (3, 8, 9))}
        order = {UNRAR: ["/a/unrar-old", "/a/unrar-old", "/missing", "/b/unrar", "/c/unrar"], SEVENZIP: ["/none"],
                 BSDTAR: ["/d/tar"]}
        probed = []
        saved = (external.candidates, external.probe)
        self.addCleanup(lambda: (setattr(external, "candidates", saved[0]), setattr(external, "probe", saved[1])))
        external.candidates = lambda flavor, platform=None: order[flavor]
        external.probe = lambda flavor, path, pack_dir=None: probed.append(path) or tools.get(path)
        usable, old = external.find_tools((UNRAR, SEVENZIP, BSDTAR))
        self.assertEqual([t.path for t in usable], ["/b/unrar", "/d/tar"])
        self.assertEqual([t.path for t in old], ["/a/unrar-old"])
        self.assertEqual(probed.count("/a/unrar-old"), 1, "the same file is probed once")
        self.assertNotIn("/c/unrar", probed, "one usable program of each kind is enough")

    def test_candidates_are_absolute_and_fixed(self):
        for platform in ("linux", "darwin", "win32"):
            if platform == "win32" and os.name != "nt":
                continue
            for flavor in (UNRAR, SEVENZIP, BSDTAR):
                paths = external.candidates(flavor, platform)
                self.assertTrue(paths)
                for p in paths:
                    self.assertTrue(os.path.isabs(p) or p.startswith("/"), p)
        linux = external.candidates(BSDTAR, "linux")
        self.assertIn("/usr/bin/bsdtar", linux)
        self.assertTrue(all(os.path.dirname(p) in external._POSIX_DIRS for p in linux))
        if os.name == "nt":
            self.assertEqual(external.candidates(BSDTAR, "win32"),
                             [os.path.join(external._system32(), "tar.exe")])
            self.assertTrue(all(p.lower().endswith(".exe") for p in external.candidates(UNRAR, "win32")))

    def test_probe_refuses_what_is_not_the_program(self):
        # Python is a real executable, but no banner of an unpacker.
        self.assertIsNone(external.probe(UNRAR, PY))
        self.assertIsNone(external.probe(BSDTAR, PY))


UNRAR_LT = """
UNRAR 7.23 x64 freeware      Copyright (c) 1993-2026 Alexander Roshal

Archive: C:\\x\\normal.rar
Details: RAR 5

        Name: pack\\scene\\scene.max
        Type: File
        Size: 18
 Packed size: 18
    Modified: 2020-01-01 00:00:00,000000000
  Attributes: ..A....
     Host OS: Windows

        Name: pack\\secret.jpg
        Type: File
        Size: 3
       Flags: encrypted

        Name: pack\\link.jpg
        Type: Symbolic link
      Target: ..\\..\\evil

        Name: pack\\scene
        Type: Directory
    Modified: 2020-01-01 00:00:00,000000000

"""

SEVENZIP_SLT = """
7-Zip 26.06 (x64) : Copyright (c) 1999-2026 Igor Pavlov : 2026-11-06

Scanning the drive for archives:
1 file, 603 bytes (1 KiB)

Listing archive: normal.rar

--
Path = normal.rar
Type = Rar5
Multivolume = -
Volumes = 1

----------
Path = pack\\scene\\scene.max
Folder = -
Size = 18
Attributes = A
Encrypted = -
Symbolic Link =
Hard Link =
Alternate Stream = -

Path = pack\\secret.jpg
Folder = -
Size = 3
Attributes = A
Encrypted = +
Symbolic Link =
Hard Link =

Path = pack/link.jpg
Folder = -
Size = 5
Attributes = A_ lrwxrwxrwx
Encrypted = -
Symbolic Link = ../../evil
Hard Link =

Path = pack/hard.jpg
Folder = -
Size = 5
Attributes = A_ -rw-r--r--
Hard Link = pack/other.jpg

Path = pack\\scene
Folder = +
Size = 0
Attributes = D

"""

TAR_T = "pack/scene/scene.max\npack/link.jpg\npack/hard.jpg\npack/scene\npack/sub dir/my map.png\n"
TAR_TV = ("-rw-r--r--  0 0      0          18 Jan  1  2020 pack/scene/scene.max\n"
          "lrwxr-xr-x  0 0      0           0 Jan  1  2020 pack/link.jpg -> ../../evil\n"
          "-rw-r--r--  0 0      0           0 Jan  1  2020 pack/hard.jpg link to pack/scene/scene.max\n"
          "drwxr-xr-x  0 0      0           0 Jan  1  2020 pack/scene\n"
          "-rw-r--r--  0 0      0          16 Jan  1  2020 pack/sub dir/my map.png\n")


class ParserTests(unittest.TestCase):
    def test_unrar(self):
        entries, volume = external.parse_unrar(UNRAR_LT)
        self.assertFalse(volume)
        self.assertEqual([e["name"] for e in entries],
                         ["pack\\scene\\scene.max", "pack\\secret.jpg", "pack\\link.jpg", "pack\\scene"])
        scene, secret, link, folder = entries
        self.assertEqual((scene["size"], scene["regular"], scene["is_dir"], scene["encrypted"]), (18, True, False, False))
        self.assertTrue(secret["encrypted"])
        self.assertFalse(link["regular"])
        self.assertTrue(folder["is_dir"])
        _e, volume = external.parse_unrar("Archive: x.part1.rar\nDetails: RAR 5, volume\n")
        self.assertTrue(volume)

    def test_7z(self):
        entries, volume = external.parse_7z(SEVENZIP_SLT)
        self.assertFalse(volume)
        names = [e["name"] for e in entries]
        self.assertEqual(names, ["pack\\scene\\scene.max", "pack\\secret.jpg", "pack/link.jpg", "pack/hard.jpg",
                                 "pack\\scene"])
        scene, secret, link, hard, folder = entries
        self.assertTrue(scene["regular"] and not scene["encrypted"] and scene["size"] == 18)
        self.assertTrue(secret["encrypted"])
        self.assertFalse(link["regular"])
        self.assertFalse(hard["regular"])
        self.assertTrue(folder["is_dir"] and not folder["regular"])
        _e, volume = external.parse_7z("--\nPath = x.7z.001\nMultivolume = +\n\n----------\n")
        self.assertTrue(volume)

    def test_tar(self):
        entries = external.parse_tar(TAR_T, TAR_TV)
        self.assertEqual([e["name"] for e in entries], TAR_T.split("\n")[:-1])
        scene, link, hard, folder, spaced = entries
        self.assertTrue(scene["regular"] and scene["size"] == 18)
        self.assertFalse(link["regular"])
        self.assertFalse(hard["regular"])
        self.assertTrue(folder["is_dir"] and not folder["regular"])
        self.assertTrue(spaced["regular"] and spaced["size"] == 16)
        self.assertIsNone(external.parse_tar(TAR_T, TAR_TV + "-rw-r--r-- 0 0 0 1 Jan 1 2020 extra\n"))

    def test_names_a_program_cannot_ask_for(self):
        self.assertEqual(external._unaskable(UNRAR, "pack\\a.jpg"), "")
        self.assertIn("pattern", external._unaskable(UNRAR, "pack*\\a.jpg"))
        self.assertIn("pattern", external._unaskable(UNRAR, "a?.jpg"))
        self.assertEqual(external._unaskable(UNRAR, "[a].jpg"), "")
        self.assertEqual(external._unaskable(BSDTAR, "[site] room/a*b?.jpg"), "", "escaped in the list file")
        self.assertIn("pattern", external._unaskable(BSDTAR, "dir\\a.jpg"))
        self.assertIn("option", external._unaskable(BSDTAR, "-C/a.jpg"))
        self.assertEqual(external._unaskable(SEVENZIP, "*[?].jpg"), "")
        self.assertIn("line break", external._unaskable(SEVENZIP, "a\nb.jpg"))


class ArgumentTests(unittest.TestCase):
    unrar = Tool(UNRAR, os.path.abspath("/tools/UnRAR.exe"), (7, 23))
    sevenzip = Tool(SEVENZIP, os.path.abspath("/tools/7z.exe"), (26, 6))
    tar = Tool(BSDTAR, os.path.abspath("/tools/tar.exe"), (3, 8, 9))
    archive_path = os.path.abspath("/packs/-tricky name.rar")

    def test_listing(self):
        (u,) = external.list_args(self.unrar, self.archive_path)
        self.assertEqual(u[0], self.unrar.path)
        self.assertEqual(u[1], "lt")
        for switch in ("-c-", "-cfg-", "-p-", "-scfr"):
            self.assertIn(switch, u)
        self.assertEqual(u[-2:], ["--", self.archive_path])
        (z,) = external.list_args(self.sevenzip, self.archive_path)
        self.assertEqual(z[1:3], ["l", "-slt"])
        self.assertEqual(z[-2:], ["--", self.archive_path])
        self.assertTrue(any(a.startswith("-p") and len(a) > 2 for a in z), "a dummy password: no prompt")
        names, verbose = external.list_args(self.tar, self.archive_path)
        self.assertEqual(names[1:], ["-tf", self.archive_path])
        self.assertEqual(verbose[1:], ["-tvf", self.archive_path])

    def test_extraction(self):
        out = os.path.abspath("/stage/out")
        lst = os.path.abspath("/stage/names.lst")
        u = external.extract_args(self.unrar, self.archive_path, lst, out)
        self.assertEqual(u[:2], [self.unrar.path, "e"])
        for switch in ("-c-", "-cfg-", "-p-", "-y", "-o-", "-ol-", "-ai", "-scfl"):
            self.assertIn(switch, u)
        self.assertEqual(u[-4:], ["--", self.archive_path, "@" + lst, out + os.sep])
        z = external.extract_args(self.sevenzip, self.archive_path, lst, out)
        self.assertEqual(z[:2], [self.sevenzip.path, "e"])
        for switch in ("-spd", "-r-", "-aos", "-sns-", "-scsUTF-8", "-o" + out, "-i@" + lst):
            self.assertIn(switch, z)
        self.assertFalse([a for a in z if a.startswith("-snl")], "-snld lifts 7-Zip's link checks")
        self.assertEqual(z[-2:], ["--", self.archive_path])
        t = external.extract_args(self.tar, self.archive_path, lst, out)
        self.assertEqual(t[:2], [self.tar.path, "-x"])
        for switch in ("-k", "-o", "--no-same-permissions", "--no-acls", "--no-xattrs", "--no-fflags", "--null"):
            self.assertIn(switch, t)
        self.assertNotIn("-P", t)
        self.assertEqual(t[t.index("-f") + 1], self.archive_path)
        self.assertEqual(t[t.index("-C") + 1], out)
        self.assertEqual(t[t.index("-T") + 1], lst)

    def test_list_file(self):
        names = ["pack\\scene.max", "pack\\café.jpg"]
        self.assertEqual(external.list_file_bytes(self.unrar, names), "pack\\scene.max\npack\\café.jpg\n".encode())
        self.assertEqual(external.list_file_bytes(self.tar, ["a/b.jpg", "c.max"]), b"a/b.jpg\0c.max\0")
        self.assertEqual(external.list_file_bytes(self.tar, ["[s] r/w[1]*?.jpg"]),
                         b"\\[s\\] r/w\\[1\\]\\*\\?.jpg\0")


class HeaderTests(unittest.TestCase):
    def test_rar5(self):
        self.assertIsNone(external.header_problem(rar5_header(1), 1000))
        self.assertEqual(external.header_problem(rar5_header(1, aflags=0x1), 1000), "volume")
        self.assertEqual(external.header_problem(rar5_header(1, hflags=0x1, extra=(5,), aflags=0x1), 1000),
                         "volume")
        self.assertEqual(external.header_problem(rar5_header(4), 1000), "encrypted")
        self.assertIsNone(external.header_problem(b"Rar!\x1a\x07\x01\x00\0\0\0\0\xff", 1000), "truncated")

    def test_rar4(self):
        def head(flags):
            return b"Rar!\x1a\x07\x00" + b"\0\0\x73" + struct.pack("<H", flags) + b"\0" * 20
        self.assertIsNone(external.header_problem(head(0), 1000))
        self.assertEqual(external.header_problem(head(0x0101), 1000), "volume")
        self.assertEqual(external.header_problem(head(0x0080), 1000), "encrypted")

    def test_7z(self):
        def head(offset, size):
            return b"7z\xbc\xaf\x27\x1c\x00\x04" + b"\0" * 4 + struct.pack("<QQ", offset, size) + b"\0" * 4
        self.assertIsNone(external.header_problem(head(100, 50), 182))
        self.assertEqual(external.header_problem(head(100, 50), 181), "split")

    def test_fixtures(self):
        for name, expected in (("normal.rar", None), ("solid.rar", None), ("pwdata.rar", None),
                               ("pwhead.rar", "encrypted"), ("plain.7z", None)):
            path = os.path.join(PACKS, name)
            with open(path, "rb") as f:
                head = f.read(64)
            self.assertEqual(external.header_problem(head, os.path.getsize(path)), expected, name)

    def test_backend_refuses_a_volume_before_any_program(self):
        tmp = tempfile.mkdtemp(prefix="maxdrop-ext-")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "scene.part1.rar")
        with open(path, "wb") as f:
            f.write(rar5_header(1, aflags=0x1))
        with self.assertRaisesRegex(PackError, "split into several"):
            external.ExternalBackend("rar", tools=[]).names(path)
        with open(path, "wb") as f:
            f.write(rar5_header(4))
        with self.assertRaisesRegex(PackError, "password-protected"):
            external.ExternalBackend("rar", tools=[]).names(path)


class MessageTests(unittest.TestCase):
    def test_no_program(self):
        tmp = tempfile.mkdtemp(prefix="maxdrop-ext-")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "scene.rar")
        with open(path, "wb") as f:
            f.write(rar5_header(1))
        with self.assertRaisesRegex(PackError, "No program to unpack .rar archives was found.*extract the archive "
                                               "yourself"):
            external.ExternalBackend("rar", tools=[]).names(path)

    def test_too_old(self):
        backend = external.ExternalBackend("rar")
        message = backend._none_message("/p/scene.rar", "rar", [Tool(UNRAR, "/opt/UnRAR.exe", (7, 1))])
        self.assertIn("UnRAR 7.01", message)
        self.assertIn("older than 7.23", message)
        self.assertIn("update it", message)

    def test_rar4_on_linux_does_not_suggest_bsdtar(self):
        backend = external.ExternalBackend("rar")
        platform = external.sys.platform
        external.sys.platform = "linux"
        try:
            rar4 = backend._none_message("/p/scene.rar", "rar4", [])
            rar5 = backend._none_message("/p/scene.rar", "rar", [])
        finally:
            external.sys.platform = platform
        self.assertIn("No program to unpack RAR 4 archives", rar4)
        self.assertIn("bsdtar does not read RAR 4", rar4)
        self.assertNotIn("libarchive-tools", rar4)
        self.assertIn("libarchive-tools", rar5)

    def test_password_and_tool_error(self):
        backend = external.ExternalBackend("rar")
        failures = [external.ToolFailed("UnRAR 7.23", "exit code 11", "Incorrect password for x.jpg")]
        self.assertIn("password-protected", backend._failure("/p/scene.rar", failures))
        failures = [external.ToolFailed("bsdtar 3.8.9", "exit code 1", "line\n" * 50 + "x" * 1000)]
        message = backend._failure("/p/scene.rar", failures)
        self.assertIn("bsdtar 3.8.9: exit code 1", message)
        self.assertLess(len(message), 600)



class RunTests(TempCase):
    def test_output_and_exit_code(self):
        code, text, _r = external.run([PY, "-I", "-c", "import sys; print('hello'); sys.exit(3)"], 30, 1000)
        self.assertEqual(code, 3)
        self.assertEqual(text.strip(), "hello")

    def test_stderr_apart(self):
        code, out, err = external.run([PY, "-I", "-c", "import sys; print('name'); sys.stderr.write('warn')"],
                                      30, 1000)
        self.assertEqual((code, out.strip(), err.strip()), (0, "name", "warn"))

    def test_stdin_is_closed(self):
        code, text, _r = external.run([PY, "-I", "-c", "import sys; print(repr(sys.stdin.read()))"], 30, 1000)
        self.assertEqual((code, text.strip()), (0, "''"))

    def test_working_directory_is_the_programs_folder(self):
        _c, text, _r = external.run([PY, "-I", "-c", "import os; print(os.getcwd())"], 30, 1000)
        self.assertEqual(os.path.normcase(text.strip()), os.path.normcase(os.path.dirname(PY)))

    def test_timeout_ends_the_process_tree(self):
        flag = os.path.join(self.tmp, "grandchild-was-here")
        grandchild = "import time; time.sleep(3); open(%r, 'w').write('x')" % flag
        child = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-I', '-c', %r]); time.sleep(60)"
                 % grandchild)
        start = time.monotonic()
        with self.assertRaisesRegex(external.ToolFailed, "did not finish within 1 seconds"):
            external.run([PY, "-I", "-c", child], 1, 1000)
        self.assertLess(time.monotonic() - start, 15)
        time.sleep(4)
        self.assertFalse(os.path.exists(flag), "the grandchild outlived the timeout")

    def test_output_cap(self):
        noisy = [PY, "-I", "-c", "import sys; sys.stdout.write('x' * 2000000)"]
        code, text, _r = external.run(noisy, 30, 1000)
        self.assertEqual((code, len(text)), (0, 1000))
        with self.assertRaisesRegex(external.ToolFailed, "more output"):
            external.run(noisy, 30, 1000, overflow_fatal=True)

    def test_watch_stops_the_program(self):
        calls = []

        def watch():
            calls.append(1)
            if len(calls) > 1:
                raise PackError("over a limit")
        start = time.monotonic()
        with self.assertRaisesRegex(PackError, "over a limit"):
            external.run([PY, "-I", "-c", "import time; time.sleep(60)"], 60, 1000, watch=watch)
        self.assertLess(time.monotonic() - start, 15)


class CollectTests(TempCase):
    def write(self, rel, data=b"x"):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_plain_files(self):
        self.write("a.jpg", b"abc")
        self.write("scene.max")
        found = external.collect(self.tmp, True, "t", 100)
        self.assertEqual(sorted(found), ["a.jpg", "scene.max"])
        self.assertEqual(found["a.jpg"][1], 3)

    def test_folders_only_when_not_flat(self):
        self.write("pack/maps/a.jpg")
        self.assertEqual(sorted(external.collect(self.tmp, False, "t", 100)), ["a.jpg"])
        with self.assertRaisesRegex(PackError, "a folder"):
            external.collect(self.tmp, True, "t", 100)

    def test_two_files_named_alike(self):
        self.write("x/Wood.jpg")
        self.write("y/wood.JPG")
        with self.assertRaisesRegex(PackError, "two files"):
            external.collect(self.tmp, False, "t", 100)

    def test_hard_link(self):
        a = self.write("a.jpg")
        try:
            os.link(a, os.path.join(self.tmp, "b.jpg"))
        except (OSError, NotImplementedError) as e:
            self.skipTest("no hard links here: %s" % e)
        with self.assertRaisesRegex(PackError, "not a plain file"):
            external.collect(self.tmp, True, "t", 100)

    def test_symlink(self):
        target = self.write("t/a.jpg")
        try:
            os.symlink(target, os.path.join(self.tmp, "link.jpg"))
        except (OSError, NotImplementedError) as e:
            self.skipTest("no symbolic links here: %s" % e)
        with self.assertRaisesRegex(PackError, "a link"):
            external.collect(self.tmp, False, "t", 100)

    @unittest.skipUnless(os.name == "nt", "NTFS streams")
    def test_drop_streams(self):
        path = self.write("a.jpg", b"main")
        try:
            with open(path + ":hidden", "wb") as f:
                f.write(b"stream")
        except OSError as e:
            self.skipTest("no streams on this volume: %s" % e)
        external.drop_streams(external._long(path))
        with self.assertRaises(OSError):
            open(path + ":hidden", "rb").close()
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"main")

    def test_count_guard(self):
        for i in range(5):
            self.write("f%d.jpg" % i)
        with self.assertRaisesRegex(PackError, "too many"):
            external.collect(self.tmp, True, "t", 3)



FAKE_RAR = rar5_header(1)
PLAN = ["pack\\scene.max", "pack\\maps\\wood.jpg"]


class StandInTests(TempCase):
    """The backend's rules with Python standing in for the unpacker: what a program writes, how it ends."""

    def setUp(self):
        super().setUp()
        self.pack = os.path.join(self.tmp, "scene.rar")
        with open(self.pack, "wb") as f:
            f.write(FAKE_RAR)
        self.first = Tool(UNRAR, PY, (7, 23))
        self.second = Tool(SEVENZIP, PY, (26, 6))
        self.scripts = {}
        saved = (external.list_entries, external.extract_args, archive._BACKENDS.get("rar"))
        self.addCleanup(self._restore, saved)
        external.list_entries = self._list
        external.extract_args = self._extract_args

    def _restore(self, saved):
        external.list_entries, external.extract_args, backend = saved
        archive._BACKENDS["rar"] = backend

    def _list(self, tool, path):
        return [archive.Entry(name=n, size=3, key=(tool, n)) for n in PLAN]

    def _extract_args(self, tool, path, list_file, out):
        return [PY, "-I", "-c", self.scripts[tool.flavor], out, list_file]

    def use(self, *tools, limits=archive.DEFAULT_LIMITS):
        archive._BACKENDS["rar"] = external.ExternalBackend("rar", tools=list(tools))
        return lambda: archive.unpack(self.pack, limits=limits)

    def left(self):
        return sorted(os.listdir(self.tmp))

    WRITE = ("import os, sys\nout = sys.argv[1]\n"
             "for n, d in (('scene.max', b'MAX'), ('wood.jpg', b'WOOD')):\n"
             "    open(os.path.join(out, n), 'wb').write(d)\n")

    def test_good_program(self):
        self.scripts[UNRAR] = self.WRITE
        result = self.use(self.first)()
        self.assertEqual(folder_files(result.folder), {"scene.max": b"MAX", "wood.jpg": b"WOOD"})
        self.assertEqual(result.backend, "UnRAR 7.23")
        self.assertEqual(self.left(), ["scene", "scene.rar"])

    def test_non_zero_exit_discards_what_was_written(self):
        self.scripts[UNRAR] = self.WRITE + "sys.exit(1)\n"
        with self.assertRaisesRegex(PackError, "could not be unpacked.*exit code 1"):
            self.use(self.first)()
        self.assertEqual(self.left(), ["scene.rar"])

    def test_password_message(self):
        self.scripts[UNRAR] = "import sys\nprint('Incorrect password for pack/scene.max')\nsys.exit(11)\n"
        with self.assertRaisesRegex(PackError, "password-protected"):
            self.use(self.first)()
        self.assertEqual(self.left(), ["scene.rar"])

    def test_next_program_on_a_fresh_folder(self):
        self.scripts[UNRAR] = self.WRITE + "open(os.path.join(out, 'junk.jpg'), 'wb').write(b'x')\nsys.exit(2)\n"
        self.scripts[SEVENZIP] = self.WRITE
        result = self.use(self.first, self.second)()
        self.assertEqual(folder_files(result.folder), {"scene.max": b"MAX", "wood.jpg": b"WOOD"})
        # The result names the program that listed the pack; the backend names the one that unpacked it.
        self.assertEqual(archive._BACKENDS["rar"].name, "7-Zip 26.06")

    def test_other_files_than_asked(self):
        self.scripts[UNRAR] = self.WRITE + "open(os.path.join(out, 'evil.jpg'), 'wb').write(b'x')\n"
        with self.assertRaisesRegex(PackError, "other files than asked for"):
            self.use(self.first)()
        self.assertEqual(self.left(), ["scene.rar"])

    def test_a_planned_file_missing(self):
        self.scripts[UNRAR] = "pass\n"
        with self.assertRaisesRegex(PackError, "did not write"):
            self.use(self.first)()
        self.assertEqual(self.left(), ["scene.rar"])

    def test_names_come_through_the_list_file(self):
        self.scripts[UNRAR] = ("import sys\nnames = open(sys.argv[2], 'rb').read().decode('utf-8').split('\\n')\n"
                               "sys.exit(0 if names[:2] == %r else 5)\n" % PLAN)
        with self.assertRaisesRegex(PackError, "did not write"):  # the names were right: exit 0, nothing written
            self.use(self.first)()

    def test_watchdog_ends_a_program_over_the_byte_limit(self):
        self.scripts[UNRAR] = ("import os, sys, time\nf = open(os.path.join(sys.argv[1], 'wood.jpg'), 'wb')\n"
                               "for _ in range(600):\n    f.write(b'x' * 65536); f.flush(); time.sleep(0.01)\n")
        limits = archive.Limits(total_bytes=1 << 20, free_margin=0)
        start = time.monotonic()
        with self.assertRaisesRegex(PackError, "unpacks to more than"):
            self.use(self.first, limits=limits)()
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(self.left(), ["scene.rar"])

    def test_pack_time_limit(self):
        self.scripts[UNRAR] = "import time\ntime.sleep(60)\n"
        limits = archive.Limits(seconds=1.5, free_margin=0)
        start = time.monotonic()
        with self.assertRaisesRegex(PackError, "longer than"):
            self.use(self.first, limits=limits)()
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(self.left(), ["scene.rar"])



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
        """(tool, label) of each program present; a SKIPPED line for each one missing."""
        found = []
        for flavor in flavors:
            label = "%s: %s" % (external.LABELS[flavor], case)
            tool = REAL.get(flavor)
            if tool is None:
                say(label, False, "%s not found at its standard place or below its floor" % external.LABELS[flavor])
            else:
                found.append((tool, "%s (%s)" % (label, tool.path)))
        if not found:
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
        """The backends archive.py really registers: the first usable program of the chain."""
        if not REAL:
            say("discovered chain: normal.rar", False, "no unpacker here")
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
        """Imported as maxdrop.intake.archive (without maxdrop/__init__.py, which needs bpy), archive.py registers
        the external backends itself."""
        code = ("import importlib.util, sys, types\n"
                "pkg = types.ModuleType('mdpkg'); pkg.__path__ = [%r]; sys.modules['mdpkg'] = pkg\n"
                "import mdpkg.archive as a\n"
                "print(type(a._BACKENDS['rar']).__name__, type(a._BACKENDS['7z']).__name__)\n" % INTAKE)
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
