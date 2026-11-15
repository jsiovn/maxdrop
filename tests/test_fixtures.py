# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of the fixture tools (tools/cfb.py, tools/sanitize_fixture.py, tools/check_fixture.py) and the scan of
every committed tests/fixtures/*.max for user names, computer names and user paths: no Blender, no network.

    python -I -m unittest discover tests
"""
import contextlib
import glob
import importlib.util
import io
import os
import shutil
import struct
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
BOX = os.path.join(ROOT, "tests", "fixtures", "box_poly_standard.max")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cfb = _load("cfb")
sanitize_fixture = _load("sanitize_fixture")
check_fixture = _load("check_fixture")

FREE, END, FATSECT, NOSTREAM = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF


def build_cfb(big, small, small_name="Small", reverse_big=False):
    """A version 3 compound file (512-byte sectors): stream "Big" in the FAT, stream small_name in the mini stream.
    reverse_big stores the sectors of "Big" in the file in reverse order, as a fragmented file would."""
    ss = 512
    mini = small + b"\0" * (-len(small) % 64)
    n_mini_sectors = len(mini) // 64
    n_ministream = -(-len(mini) // ss)
    n_big = -(-len(big) // ss)
    ms_start, first_big = 3, 3 + n_ministream
    fat = [FREE] * (ss // 4)
    fat[0], fat[1], fat[2] = FATSECT, END, END
    big_chain = list(range(first_big, first_big + n_big))
    if reverse_big:
        big_chain.reverse()
    for chain in (list(range(ms_start, ms_start + n_ministream)), big_chain):
        for i, s in enumerate(chain):
            fat[s] = chain[i + 1] if i + 1 < len(chain) else END
    big_start = big_chain[0]
    chunks = [big[i * ss:(i + 1) * ss].ljust(ss, b"\0") for i in range(n_big)]
    physical = b"".join(chunks[big_chain.index(s)] for s in range(first_big, first_big + n_big))
    minifat = [FREE] * (ss // 4)
    for i in range(n_mini_sectors):
        minifat[i] = i + 1 if i + 1 < n_mini_sectors else END

    def entry(name, kind, child, right, start, size):
        raw = name.encode("utf-16-le") + b"\0\0" if name else b""
        return (raw.ljust(64, b"\0") + struct.pack("<HBB", len(raw), kind, 1)
                + struct.pack("<III", NOSTREAM, right, child) + b"\0" * 36 + struct.pack("<IQ", start, size))

    directory = (entry("Root Entry", 5, 1, NOSTREAM, ms_start, len(mini)) + entry("Big", 2, NOSTREAM, 2, big_start,
                 len(big)) + entry(small_name, 2, NOSTREAM, NOSTREAM, 0, len(small)) + entry("", 0, NOSTREAM,
                 NOSTREAM, 0, 0))
    header = (cfb.MAGIC + b"\0" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
              + struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, 2, 1, END, 0)
              + struct.pack("<109I", 0, *([FREE] * 108)))
    body = (struct.pack("<128I", *fat) + directory + struct.pack("<128I", *minifat)
            + mini.ljust(n_ministream * ss, b"\0") + physical)
    return header + body


def property_stream(code_page, entries, vector=None):
    """A DocumentSummaryInformation-like stream: one section with the code page and property 13, a vector of
    strings (VT_LPSTR, encoded in UTF-16 when the code page is 1200, as the format says) or the typed value given."""
    if vector is None:
        wide = code_page == 1200
        items = b""
        for text in entries:
            raw = (text + "\0").encode("utf-16-le" if wide else "latin-1")
            items += struct.pack("<I", len(raw)) + raw + b"\0" * (-len(raw) % 4)
        vector = struct.pack("<HxxI", 0x101E, len(entries)) + items
    cp = struct.pack("<Hxxhxx", 0x02, code_page - 65536 if code_page > 32767 else code_page)
    props = [(1, cp), (13, vector)]
    offset, table, values = 8 + 8 * len(props), b"", b""
    for pid, value in props:
        table += struct.pack("<II", pid, offset + len(values))
        values += value
    section = struct.pack("<II", 8 + len(table) + len(values), len(props)) + table + values
    fmtid = bytes.fromhex("02d5cdd59c2e1b10939708002b2cf9ae")
    return struct.pack("<HHI", 0xFFFE, 0, 0x2000A) + b"\0" * 16 + struct.pack("<I", 1) + fmtid + struct.pack(
        "<I", 48) + section


def dirty(data, filler=b"Jdoe7Qmz"):
    """The fixture with every identity value set to fake text of the same length, as Max would save it."""
    c = cfb.Compound(data)
    out = bytearray(data)
    for t in sanitize_fixture.identity_values(data):
        fake = (filler * len(t.raw))[:len(t.raw)]
        sanitize_fixture._write(out, c.runs(t.stream), t.offset, fake)
    return bytes(out)


class CompoundFile(unittest.TestCase):
    big = bytes(range(256)) * 20       # 5120 bytes: above the 4096 cut-off, in the FAT
    small = b"mini stream data " * 6   # 102 bytes: in the mini stream

    def test_reads_both_kinds_of_stream(self):
        c = cfb.Compound(build_cfb(self.big, self.small))
        self.assertEqual(sorted(c.names()), ["Big", "Small"])
        self.assertEqual(c.read("Big"), self.big)
        self.assertEqual(c.read("Small"), self.small)

    def test_runs_point_at_the_stream_bytes_in_the_file(self):
        data = build_cfb(self.big, self.small)
        c = cfb.Compound(data)
        for name in ("Big", "Small"):
            self.assertEqual(b"".join(data[o:o + n] for o, n in c.runs(name)), c.read(name))

    def test_a_cycle_in_the_fat_is_refused(self):
        data = bytearray(build_cfb(self.big, self.small))
        big_start = 4
        struct.pack_into("<I", data, 512 + 4 * (big_start + 2), big_start)
        with self.assertRaises(cfb.CfbError):
            cfb.Compound(bytes(data)).read("Big")

    def test_a_stream_larger_than_its_chain_is_refused(self):
        data = bytearray(build_cfb(self.big, self.small))
        struct.pack_into("<I", data, 1024 + 128 + 120, len(self.big) * 4)
        with self.assertRaises(cfb.CfbError):
            cfb.Compound(bytes(data)).read("Big")

    def test_not_a_compound_file(self):
        with self.assertRaises(cfb.CfbError):
            cfb.Compound(b"PK\x03\x04" + b"\0" * 1020)

    def test_a_fragmented_stream_reads_in_stream_order(self):
        data = build_cfb(self.big, self.small, reverse_big=True)
        c = cfb.Compound(data)
        self.assertEqual(c.read("Big"), self.big)
        self.assertGreater(len(c.runs("Big")), 1)
        self.assertEqual(dict(c.streams())["Big"], self.big)

    def test_write_across_two_pieces_of_a_stream(self):
        data = bytearray(build_cfb(self.big, self.small, reverse_big=True))
        c = cfb.Compound(bytes(data))
        sanitize_fixture._write(data, c.runs("Big"), 510, b"ABCDEF")
        expected = self.big[:510] + b"ABCDEF" + self.big[516:]
        self.assertEqual(cfb.Compound(bytes(data)).read("Big"), expected)
        with self.assertRaises(ValueError):
            sanitize_fixture._write(data, c.runs("Big"), len(self.big) - 2, b"ABCD")


class PropertySets(unittest.TestCase):
    def test_utf16_code_page_strings_are_read_whole(self):
        stream = property_stream(1200, ["General", "User Name=jdoe7", "Computer Name=box-42"])
        found = [(raw.decode("utf-16-le"), enc) for _f, _p, _o, raw, enc in sanitize_fixture.strings(stream)]
        self.assertIn(("User Name=jdoe7", sanitize_fixture.WIDE), found)

    def test_utf16_identity_values_are_blanked(self):
        data = build_cfb(b"\0" * 5000, property_stream(1200, ["User Name=jdoe7", "Computer Name=box-42"]),
                         small_name=sanitize_fixture.DOC_SUMMARY)
        targets = sanitize_fixture.identity_values(data)
        self.assertEqual(sorted((t.kind, t.text) for t in targets), [("computer name", "box-42"),
                                                                     ("user name", "jdoe7")])
        new, changed = sanitize_fixture.sanitize(data)
        self.assertEqual(changed, 2)
        self.assertNotIn("jdoe7".encode("utf-16-le"), new)
        self.assertEqual(check_fixture.problems(new, {}), [])

    def test_an_element_of_unknown_type_is_refused(self):
        filetime_in_variants = struct.pack("<HxxI", 0x100C, 1) + struct.pack("<HxxQ", 0x40, 0)
        with self.assertRaises(ValueError):
            list(sanitize_fixture.strings(property_stream(65001, [], vector=filetime_in_variants)))

    def test_a_file_without_the_user_name_slot_is_refused(self):
        data = build_cfb(b"\0" * 5000, property_stream(65001, ["General"]), small_name=sanitize_fixture.DOC_SUMMARY)
        with self.assertRaises(ValueError):
            sanitize_fixture.sanitize(data)
        self.assertIn(("identity slots not found", "-", None), check_fixture.problems(data, {}))


@unittest.skipUnless(os.path.isfile(BOX), "tests/fixtures/box_poly_standard.max is missing")
class Sanitizer(unittest.TestCase):
    def setUp(self):
        with open(BOX, "rb") as f:
            self.clean = f.read()

    def test_finds_what_3ds_max_writes(self):
        # Max 2020: User Name= and Computer Name= in DocumentSummaryInformation; last author (8) and property 34,
        # found because it equals the user name, in SummaryInformation.
        targets = sanitize_fixture.identity_values(self.clean)
        kinds = sorted((t.stream, t.kind) for t in targets)
        self.assertEqual(kinds, sorted([(sanitize_fixture.DOC_SUMMARY, "user name"),
                                        (sanitize_fixture.DOC_SUMMARY, "computer name"),
                                        (sanitize_fixture.SUMMARY, "user name"),
                                        (sanitize_fixture.SUMMARY, "user name")]))
        self.assertTrue(all(t.text == t.blank() for t in targets))

    def test_committed_fixture_is_already_blank(self):
        self.assertEqual(sanitize_fixture.sanitize(self.clean), (self.clean, 0))

    def test_blanks_exactly_the_identity_values(self):
        soiled = dirty(self.clean)
        self.assertNotEqual(soiled, self.clean)
        new, changed = sanitize_fixture.sanitize(soiled)
        self.assertEqual(new, self.clean)
        self.assertEqual(changed, len(sanitize_fixture.identity_values(self.clean)))
        self.assertEqual(sanitize_fixture.sanitize(new), (new, 0))

    def test_cli_rewrites_in_place_without_printing_the_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dirty.max")
            with open(path, "wb") as f:
                f.write(dirty(self.clean))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(sanitize_fixture.main(["sanitize_fixture", path]), 0)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), self.clean)
            self.assertNotIn("Jdoe", out.getvalue())
            self.assertIn("value(s) blanked", out.getvalue())


@unittest.skipUnless(FIXTURES, "no tests/fixtures/*.max")
class Check(unittest.TestCase):
    def test_every_committed_fixture_is_clean(self):
        for path in FIXTURES:
            with open(path, "rb") as f:
                self.assertEqual(check_fixture.problems(f.read()), [], os.path.basename(path))

    def test_every_committed_fixture_is_small(self):
        for path in FIXTURES:
            self.assertLess(os.path.getsize(path), 1 << 20, os.path.basename(path))

    def inject(self, text, encoding, at=None):
        with open(BOX, "rb") as f:
            data = bytearray(f.read())
        raw = text.encode(encoding)
        at = len(data) // 2 if at is None else at
        data[at:at + len(raw)] = raw
        return bytes(data)

    def kinds(self, data, names=None):
        return {(kind, enc) for kind, enc, _where in check_fixture.problems(data, names)}

    def test_user_and_computer_names_in_both_encodings(self):
        names = {"user name": ["jdoe7"], "computer name": ["box-42"]}
        self.assertIn(("user name", "ASCII"), self.kinds(self.inject("JDOE7", "ascii"), names))
        self.assertIn(("user name", "UTF-16LE"), self.kinds(self.inject("jDoe7", "utf-16-le"), names))
        self.assertIn(("user name", "UTF-16LE"), self.kinds(self.inject("jdoe7", "utf-16-le", 12345), names))
        self.assertIn(("computer name", "ASCII"), self.kinds(self.inject("BOX-42", "ascii"), names))

    def test_the_current_user_and_computer(self):
        names = check_fixture.local_names()
        for kind, values in names.items():
            for value in values:
                self.assertIn((kind, "ASCII"), self.kinds(self.inject(value.upper(), "ascii")), kind)
                self.assertIn((kind, "UTF-16LE"), self.kinds(self.inject(value, "utf-16-le")), kind)

    def test_paths(self):
        self.assertIn(("drive path", "ASCII"), self.kinds(self.inject("D:\\scenes\\a.max", "ascii"), {}))
        self.assertIn(("user folder", "UTF-16LE"), self.kinds(self.inject("C:\\Users\\abc", "utf-16-le"), {}))
        self.assertIn(("user folder", "ASCII"), self.kinds(self.inject("/Users/abc/", "ascii"), {}))
        self.assertIn(("drive path", "UTF-16LE"), self.kinds(self.inject("e:/maps/wood.jpg", "utf-16-le"), {}))
        self.assertIn(("network path", "ASCII"), self.kinds(self.inject("\\\\fileserver\\share", "ascii"), {}))

    def test_a_non_ascii_name_in_utf8(self):
        names = {"user name": ["jürgen"]}
        self.assertIn(("user name", "UTF-8"), self.kinds(self.inject("JÜRGEN", "utf-8"), names))
        self.assertIn(("user name", "ASCII"), self.kinds(self.inject("jürgen", "cp1252"), names))

    def test_a_string_across_a_sector_boundary(self):
        big = bytearray(b"\0" * 5120)  # above the 4096-byte cut-off: in the FAT
        text = "C:\\Users\\abc\\maps".encode("utf-16-le")
        big[512 - 10:512 - 10 + len(text)] = text
        data = build_cfb(bytes(big), b"y" * 100, reverse_big=True)
        self.assertNotIn(text, data)
        self.assertIn(("user folder", "UTF-16LE", "Big"), check_fixture.problems(data, {}))

    def test_a_blank_that_is_not_blank(self):
        with open(BOX, "rb") as f:
            data = dirty(f.read())
        self.assertIn(("identity property not blank", "-"), self.kinds(data, {}))

    def test_a_compressed_stream_is_scanned_unpacked(self):
        import gzip
        big = gzip.compress(b"\0" * 3000 + "c:\\Users\\abc".encode("utf-16-le") + b"\0" * 3000)
        data = build_cfb(big.ljust(5000, b"\0"), b"x" * 100)
        self.assertNotIn(b"U\0s\0e\0r\0s", data)
        found = check_fixture.problems(data, {})
        self.assertIn(("user folder", "UTF-16LE", "Big"), found)

    def test_cli_names_the_kind_not_the_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean = os.path.join(tmp, "clean.max")
            shutil.copy(BOX, clean)
            dirty_path = os.path.join(tmp, "dirty.max")
            with open(dirty_path, "wb") as f:
                f.write(self.inject("Q:\\private\\scene.max", "ascii"))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(check_fixture.main(["check_fixture", clean]), 0)
                self.assertEqual(check_fixture.main(["check_fixture", clean, dirty_path]), 1)
            self.assertIn("clean.max: clean", out.getvalue())
            self.assertIn("dirty.max: drive path (ASCII)", err.getvalue())
            self.assertNotIn("private", err.getvalue().replace(dirty_path, ""))


if __name__ == "__main__":
    unittest.main()
