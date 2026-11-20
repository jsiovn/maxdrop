# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/cfb.py, the compound file reader: no Blender. Every compound file is built here by
Builder (versions 3 and 4, fragmented chains, the mini stream, a storage, more FAT sectors than the header holds),
then damaged on purpose; the committed fixtures are checked against tools/cfb.py, a separate implementation.

    python -I -m unittest discover tests
"""
import glob
import gzip
import importlib.util
import os
import struct
import sys
import tempfile
import types
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_PKG = "maxdrop_convert_test"  # the package the convert tests make: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
cfb = importlib.import_module(_PKG + ".reader.cfb")
tools_cfb = _load("maxdrop_tools_cfb", os.path.join(ROOT, "tools", "cfb.py"))

CfbError = cfb.CfbError
FREE, END, FATSECT, DIFSECT, NOSTREAM = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC, 0xFFFFFFFF
HEADER = struct.Struct("<8s16sHHHHH6sIIIIIIIII109I")
ENTRY = struct.Struct("<64sHBBIII16sIQQIQ")


def payload(n, seed=0):
    """n bytes that differ from sector to sector, so a misplaced sector shows."""
    block = bytes((i * 7 + seed) & 0xFF for i in range(251))
    return (block * (n // 251 + 1))[:n]


def stored_member(size, seed=0):
    """A gzip member of exactly size bytes, its data in stored deflate blocks (the block sizes of gzip.compress
    depend on the zlib build): (member, data)."""
    # 10 header and 8 trailer bytes, 5 per block of at most 65535: try each block count m
    n = next(n for m in range(1, size // 65535 + 2) for n in [size - 18 - 5 * m]
             if n >= 0 and max(1, -(-n // 65535)) == m)
    data = payload(n, seed)
    blocks = [data[o:o + 65535] for o in range(0, n, 65535)] or [b""]
    body = b"".join(struct.pack("<BHH", k == len(blocks) - 1, len(b), len(b) ^ 0xFFFF) + b
                    for k, b in enumerate(blocks))
    return b"\x1f\x8b\x08\0\0\0\0\0\0\xff" + body + struct.pack("<II", zlib.crc32(data), n), data


class Builder:
    """Writes a compound file. add() streams (layout "contiguous" or "reverse"), interleave() two streams sector by
    sector; streams under 4096 bytes go to the mini stream. build() takes hooks that damage the FAT or the
    directory before they are written."""

    def __init__(self, version=4, mini_layout="contiguous"):
        self.version = version
        self.ss = 512 if version == 3 else 4096
        self.sectors, self.fat = [], []
        self.big, self.small = [], []  # (path, data, layout)
        self.storages = {}  # name -> [(name, data)]
        self.pairs = []
        self.mini_layout = mini_layout
        self.chains = {}  # path -> sector numbers (FAT or mini FAT)

    def add(self, name, data, layout="contiguous", storage=None):
        path = name if storage is None else storage + "/" + name
        if storage is not None:
            self.storages.setdefault(storage, []).append(name)
        (self.small if len(data) < 4096 else self.big).append((path, data, layout))
        return self

    def interleave(self, a, data_a, b, data_b):
        self.pairs.append(((a, data_a), (b, data_b)))
        return self

    def _alloc(self, n):
        start = len(self.sectors)
        self.sectors += [b""] * n
        self.fat += [FREE] * n
        return list(range(start, start + n))

    def _write(self, idx, data, ss=None, sectors=None, fat=None):
        ss = ss or self.ss
        sectors = self.sectors if sectors is None else sectors
        fat = self.fat if fat is None else fat
        for k, s in enumerate(idx):
            sectors[s] = data[k * ss:(k + 1) * ss].ljust(ss, b"\0")
            fat[s] = idx[k + 1] if k + 1 < len(idx) else END
        return idx[0] if idx else END

    def _n(self, data, ss=None):
        ss = ss or self.ss
        return (len(data) + ss - 1) // ss

    def _place(self, data, layout):
        idx = self._alloc(self._n(data))
        if layout == "reverse":
            idx = idx[::-1]
        self._write(idx, data)
        return idx

    def build(self, patch_fat=None, patch_dir=None):
        starts, sizes = {}, {}
        for path, data, layout in self.big:
            idx = self._place(data, layout)
            self.chains[path], starts[path], sizes[path] = idx, (idx[0] if idx else END), len(data)
        for (a, da), (b, db) in self.pairs:
            na, nb = self._n(da), self._n(db)
            idx = self._alloc(na + nb)
            ia, ib = idx[0:2 * min(na, nb):2] + idx[2 * min(na, nb):][:max(0, na - nb)], \
                idx[1:2 * min(na, nb):2] + idx[2 * min(na, nb):][:max(0, nb - na)]
            for path, data, chain in ((a, da, ia), (b, db, ib)):
                self._write(chain, data)
                self.chains[path], starts[path], sizes[path] = chain, chain[0], len(data)
        # The mini stream: 64-byte sectors with their own FAT, itself stored in FAT sectors.
        mini_sectors, minifat = [], []
        for path, data, _layout in self.small:
            n = self._n(data, 64)
            idx = list(range(len(mini_sectors), len(mini_sectors) + n))
            mini_sectors += [b""] * n
            minifat += [FREE] * n
            self._write(idx, data, 64, mini_sectors, minifat)
            self.chains[path], starts[path], sizes[path] = idx, (idx[0] if idx else END), len(data)
        mini = b"".join(mini_sectors)
        root_start = END
        if mini:
            root_start = self._place(mini, self.mini_layout)[0]
        first_minifat = END
        if minifat:
            minifat += [FREE] * (-len(minifat) % (self.ss // 4))
            idx = self._place(struct.pack("<%dI" % len(minifat), *minifat), "contiguous")
            first_minifat, nminifat = idx[0], len(idx)
            self.chains["<minifat>"] = idx
        else:
            nminifat = 0
        # Directory: the root, then the top-level entries as a chain of right siblings, a storage's children
        # the same way below it.
        entries = [dict(name="Root Entry", kind=5, start=root_start, size=len(mini), left=NOSTREAM,
                        right=NOSTREAM, child=NOSTREAM)]
        top = []
        for path in list(starts):
            if "/" not in path:
                entries.append(dict(name=path, kind=2, start=starts[path], size=sizes[path], left=NOSTREAM,
                                    right=NOSTREAM, child=NOSTREAM))
                top.append(len(entries) - 1)
        for storage, names in self.storages.items():
            entries.append(dict(name=storage, kind=1, start=0, size=0, left=NOSTREAM, right=NOSTREAM,
                                child=NOSTREAM))
            sid = len(entries) - 1
            top.append(sid)
            kids = []
            for name in names:
                path = storage + "/" + name
                entries.append(dict(name=name, kind=2, start=starts[path], size=sizes[path], left=NOSTREAM,
                                    right=NOSTREAM, child=NOSTREAM))
                kids.append(len(entries) - 1)
            entries[sid]["child"] = kids[0]
            for x, y in zip(kids, kids[1:]):
                entries[x]["right"] = y
        if top:
            entries[0]["child"] = top[0]
            for x, y in zip(top, top[1:]):
                entries[x]["right"] = y
        if patch_dir:
            patch_dir(entries)
        per = self.ss // 128
        while len(entries) % per:
            entries.append(dict(name="", kind=0, start=0, size=0, left=NOSTREAM, right=NOSTREAM, child=NOSTREAM))
        raw = b"".join(self._entry(e) for e in entries)
        dir_idx = self._place(raw, "contiguous")
        self.chains["<dir>"] = dir_idx
        # FAT and DIFAT sectors at the end; the FAT has to cover them too.
        epf = self.ss // 4
        nfat = ndifat = 0
        while True:
            total = len(self.sectors) + nfat + ndifat
            want_fat = (total + epf - 1) // epf
            want_difat = max(0, (want_fat - 109 + epf - 2) // (epf - 1))
            if (want_fat, want_difat) == (nfat, ndifat):
                break
            nfat, ndifat = want_fat, want_difat
        fat_idx = self._alloc(nfat)
        difat_idx = self._alloc(ndifat)
        for s in fat_idx:
            self.fat[s] = FATSECT
        for s in difat_idx:
            self.fat[s] = DIFSECT
        fat = self.fat + [FREE] * (nfat * epf - len(self.fat))
        if patch_fat:
            patch_fat(fat, self)
        for k, s in enumerate(fat_idx):
            self.sectors[s] = struct.pack("<%dI" % epf, *fat[k * epf:(k + 1) * epf])
        rest = fat_idx[109:]
        for k, s in enumerate(difat_idx):
            part = rest[k * (epf - 1):(k + 1) * (epf - 1)]
            part += [FREE] * (epf - 1 - len(part))
            nxt = difat_idx[k + 1] if k + 1 < len(difat_idx) else END
            self.sectors[s] = struct.pack("<%dI" % epf, *(part + [nxt]))
        head = fat_idx[:109] + [FREE] * (109 - min(109, nfat))
        header = HEADER.pack(cfb.MAGIC, b"\0" * 16, 0x3E, self.version, 0xFFFE, 9 if self.version == 3 else 12,
                             6, b"\0" * 6, len(dir_idx) if self.version == 4 else 0, nfat, dir_idx[0], 0,
                             4096, first_minifat, nminifat,
                             difat_idx[0] if difat_idx else END, ndifat, *head)
        header = header.ljust(self.ss, b"\0")
        self.fat_sectors = fat_idx
        return header + b"".join(self.sectors)

    def _entry(self, e):
        name = e["name"].encode("utf-16-le")
        name_len = len(name) + 2 if e["name"] else 0
        return ENTRY.pack(name.ljust(64, b"\0"), name_len, e["kind"], 1, e["left"], e["right"], e["child"],
                          b"\0" * 16, 0, 0, 0, e["start"], e["size"])


def sample(version=4, **kw):
    b = Builder(version, **kw)
    b.add("Scene", payload(5 * b.ss + 123, 1))
    b.add("ClassDirectory3", payload(9000, 2), layout="reverse")
    b.add("\x05SummaryInformation", payload(300, 3))
    b.add("Config", payload(4095, 4))
    b.add("Empty", b"")
    b.add("Child", payload(5000, 5), storage="Store")
    b.add("Tiny", payload(10, 6), storage="Store")
    return b


EXPECTED = {
    "Scene": lambda ss: payload(5 * ss + 123, 1),
    "ClassDirectory3": lambda ss: payload(9000, 2),
    "\x05SummaryInformation": lambda ss: payload(300, 3),
    "Config": lambda ss: payload(4095, 4),
    "Empty": lambda ss: b"",
    "Store/Child": lambda ss: payload(5000, 5),
    "Store/Tiny": lambda ss: payload(10, 6),
}


class RoundTrip(unittest.TestCase):
    def check_all(self, version):
        b = sample(version)
        data = b.build()
        with cfb.CompoundFile(data) as cf:
            self.assertEqual(cf.version, version)
            self.assertEqual(cf.sector_size, b.ss)
            self.assertEqual(sorted(cf.names()), sorted(EXPECTED))
            for name, want in EXPECTED.items():
                s = cf.open(name)
                self.assertEqual(s.size, len(want(b.ss)), name)
                self.assertEqual(s.read(), want(b.ss), name)
                self.assertEqual(bytes(s.buffer()), want(b.ss), name)
                self.assertFalse(s.compressed)
            self.assertIn("Store", [e.path for e in cf.entries() if e.kind == cfb.STORAGE])

    def test_version_3(self):
        self.check_all(3)

    def test_version_4(self):
        self.check_all(4)

    def test_runs_merge_consecutive_sectors(self):
        b = sample(4)
        with cfb.CompoundFile(b.build()) as cf:
            scene = cf.open("Scene")
            self.assertEqual(len(scene.runs), 1)
            self.assertEqual(scene.runs[0], ((b.chains["Scene"][0] + 1) * 4096, 5 * 4096 + 123))
            backwards = cf.open("ClassDirectory3")  # 3 sectors chained last to first
            self.assertEqual(len(backwards.runs), 3)
            self.assertEqual(sum(n for _, n in backwards.runs), 9000)

    def test_interleaved_streams(self):
        for version in (3, 4):
            b = Builder(version)
            a, c = payload(max(7 * b.ss, 8192) + 5, 11), payload(4 * b.ss + 4096, 12)  # both over the mini cutoff
            b.interleave("A", a, "C", c)
            with cfb.CompoundFile(b.build()) as cf:
                sa, sc = cf.open("A"), cf.open("C")
                self.assertEqual(sa.read(), a)
                self.assertEqual(sc.read(), c)
                self.assertGreater(len(sa.runs), 3)
                for off in (0, 1, b.ss - 1, b.ss, 3 * b.ss + 7, len(a) - 1):
                    for n in (1, 2, b.ss, 2 * b.ss + 3):
                        self.assertEqual(sa.read(off, n), a[off:off + n], (version, off, n))
                        self.assertEqual(bytes(sa.view(off, n)), a[off:off + n], (version, off, n))

    def test_mini_stream_across_reversed_sectors(self):
        b = Builder(3, mini_layout="reverse")
        small = [payload(n, n) for n in (1, 64, 65, 700, 3000)]
        for i, data in enumerate(small):
            b.add("s%d" % i, data)
        with cfb.CompoundFile(b.build()) as cf:
            for i, data in enumerate(small):
                s = cf.open("s%d" % i)
                self.assertEqual(s.read(), data)
            self.assertGreater(len(cf.open("s4").runs), 1)

    def test_lookup(self):
        with cfb.CompoundFile(sample().build()) as cf:
            self.assertTrue(cf.exists("scene"))
            self.assertTrue(cf.exists("STORE/child"))
            self.assertTrue(cf.exists(("Store", "Child")))
            self.assertFalse(cf.exists("Store"))  # a storage is not a stream
            self.assertFalse(cf.exists("Nope"))
            self.assertEqual(cf.open("SCENE").name, "Scene")
            with self.assertRaises(KeyError):
                cf.open("Nope")
            with self.assertRaises(KeyError):
                cf.open("Store")

    def test_view_is_zero_copy_inside_a_run(self):
        data = sample().build()
        with cfb.CompoundFile(data) as cf:
            scene = cf.open("Scene")
            v = scene.view(10, 100)
            self.assertIsInstance(v, memoryview)
            self.assertIs(v.obj, data)
            self.assertEqual(bytes(v), EXPECTED["Scene"](4096)[10:110])
            self.assertIs(scene.buffer().obj, data)
            v.release()

    def test_read_ranges(self):
        with cfb.CompoundFile(sample().build()) as cf:
            s = cf.open("Config")
            want = EXPECTED["Config"](4096)
            self.assertEqual(s.read(4000), want[4000:])
            self.assertEqual(s.read(5000, 10), b"")
            self.assertEqual(s.read(4090, 100), want[4090:])
            self.assertEqual(len(s), 4095)
            with self.assertRaises(CfbError):
                s.read(-1)

    def test_difat(self):
        # Version 3 with more than 109 FAT sectors: the rest are listed in a DIFAT sector.
        b = Builder(3)
        big = payload(14000 * 512, 9)
        b.add("Scene", big)
        data = b.build()
        self.assertGreater(len(b.fat_sectors), 109)
        with cfb.CompoundFile(data) as cf:
            self.assertEqual(cf.open("Scene").read(), big)

    def test_a_file_on_disk(self):
        data = sample().build()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.max")
            with open(path, "wb") as f:
                f.write(data)
            with cfb.CompoundFile(path) as cf:
                s = cf.open("Scene")
                self.assertEqual(s.read(), EXPECTED["Scene"](4096))
                v = s.view(0, 10)
                self.assertEqual(bytes(v), EXPECTED["Scene"](4096)[:10])
                v.release()
            with self.assertRaises(CfbError):
                cf.open("Scene")
            cf = cfb.CompoundFile(path)
            early = cf.open("Config")
            cf.close()
            with self.assertRaises(CfbError):
                early.read()
            cf = cfb.CompoundFile(path)
            held = cf.open("Scene").view(0, 4)
            cf.close()  # a view still held: close() must not raise; the file handle is closed
            self.assertEqual(bytes(held), EXPECTED["Scene"](4096)[:4])
            held.release()
            os.remove(path)  # Windows refuses while a handle or a mapping is open


class Gzip(unittest.TestCase):
    def build(self, *members, raw=None):
        b = Builder(4)
        body = raw if raw is not None else b"".join(gzip.compress(m) for m in members)
        b.add("Scene", body)
        b.add("Small", gzip.compress(b"tiny"))
        return b.build(), body

    def test_inflated(self):
        text = payload(300000, 3)
        data, body = self.build(text)
        with cfb.CompoundFile(data) as cf:
            s = cf.open("Scene")
            self.assertTrue(s.compressed)
            self.assertEqual(s.read(), text)
            self.assertEqual(s.size, len(text))
            self.assertEqual(bytes(s.view(5, 7)), text[5:12])
            raw = cf.open("Scene", decompress=False)
            self.assertTrue(raw.compressed)
            self.assertEqual(raw.read(), body)
            self.assertEqual(cf.open("Small").read(), b"tiny")

    def test_members_and_padding(self):
        a, b = payload(5000, 1), payload(70000, 2)
        data, _ = self.build(raw=gzip.compress(a) + gzip.compress(b) + b"\0" * 300)
        with cfb.CompoundFile(data) as cf:
            self.assertEqual(cf.open("Scene").read(), a + b)

    def test_size_cap(self):
        data, _ = self.build(b"\0" * 1000000)
        with cfb.CompoundFile(data) as cf:
            with self.assertRaises(CfbError):
                cf.open("Scene", max_size=999999)
            self.assertEqual(cf.open("Scene", max_size=1000000).size, 1000000)
            with self.assertRaises(ValueError):
                cf.open("Scene", max_size=-5)

    def test_output_held_inside_zlib(self):
        # 200 MiB of zeros from about 200 KB: one input piece yields more than one bounded call returns.
        text = b"\0" * (200 << 20)
        data, _ = self.build(text)
        with cfb.CompoundFile(data) as cf:
            s = cf.open("Scene")
            self.assertEqual(s.size, len(text))
            self.assertEqual(s.read(len(text) - 3), b"\0\0\0")

    def test_damaged_and_cut(self):
        body = gzip.compress(payload(100000, 4))
        broken = body[:20] + bytes(b ^ 0x55 for b in body[20:60]) + body[60:]
        for raw in (broken, body[:len(body) // 2]):
            data, _ = self.build(raw=raw)
            with cfb.CompoundFile(data) as cf:
                with self.assertRaises(CfbError):
                    cf.open("Scene")

    def test_member_ends_at_a_piece_end(self):
        # Fewer than 3 bytes after a member's end in this piece: the next piece tells a member from padding.
        piece, b = cfb._INFLATE_PIECE, payload(5000, 6)
        damaged = gzip.compress(b)
        damaged = damaged[:3] + bytes(x ^ 0x55 for x in damaged[3:40]) + damaged[40:]
        for k in (0, 1, 2, 3):  # 3: the magic fits, no refill
            a_member, a = stored_member(piece - k, 5)
            self.assertEqual(len(a_member), piece - k)
            with self.subTest(k=k):
                # b"\0" * k: padding that ends with the piece, nothing after it
                for tail, want in ((gzip.compress(b), a + b), (b"\0" * 300, a), (b"\0" * k, a)):
                    data, _ = self.build(raw=a_member + tail)
                    with cfb.CompoundFile(data) as cf:
                        self.assertEqual(cf.open("Scene").read(), want)
                data, _ = self.build(raw=a_member + damaged)
                with cfb.CompoundFile(data) as cf:
                    with self.assertRaises(CfbError):
                        cf.open("Scene")


class Hostile(unittest.TestCase):
    def assertRefused(self, data, **kw):
        with self.assertRaises(CfbError):
            with cfb.CompoundFile(data, **kw) as cf:
                for name in cf.names():
                    cf.open(name).read()

    def test_chain_cycle(self):
        def loop(fat, b):
            chain = b.chains["Scene"]
            fat[chain[3]] = chain[1]
        self.assertRefused(sample().build(patch_fat=loop))

    def test_self_loop(self):
        def loop(fat, b):
            fat[b.chains["Scene"][0]] = b.chains["Scene"][0]
        self.assertRefused(sample().build(patch_fat=loop))

    def test_sector_out_of_range(self):
        def far(fat, b):
            fat[b.chains["Scene"][2]] = 1000000
        self.assertRefused(sample().build(patch_fat=far))

    def test_free_sector_in_a_chain(self):
        def free(fat, b):
            fat[b.chains["Scene"][2]] = FREE
        self.assertRefused(sample().build(patch_fat=free))

    def test_chain_shorter_than_its_size(self):
        def short(fat, b):
            fat[b.chains["Scene"][2]] = END
        self.assertRefused(sample().build(patch_fat=short))

    def test_directory_chain_cycle(self):
        def loop(fat, b):
            fat[b.chains["<dir>"][-1]] = b.chains["<dir>"][0]
        b = Builder(3)
        for i in range(10):
            b.add("s%d" % i, payload(10, i))
        self.assertRefused(b.build(patch_fat=loop))

    def test_directory_tree_cycle(self):
        def loop(entries):
            entries[2]["right"] = 1
        self.assertRefused(sample().build(patch_dir=loop))

    def test_directory_entry_outside(self):
        def outside(entries):
            entries[1]["left"] = 5000
        self.assertRefused(sample().build(patch_dir=outside))

    def test_entry_cap(self):
        b = Builder(3)
        for i in range(40):
            b.add("s%d" % i, payload(10, i))
        data = b.build()
        self.assertRefused(data, max_entries=16)
        with cfb.CompoundFile(data, max_entries=64) as cf:
            self.assertEqual(len(cf.names()), 40)

    def test_mini_chain_out_of_range(self):
        b = sample(3)
        data = bytearray(b.build())
        # The first small stream's first mini sector points past the mini stream.
        first = b.chains["\x05SummaryInformation"][0]
        struct.pack_into("<I", data, (b.chains["<minifat>"][0] + 1) * 512 + 4 * first, 999999)
        self.assertRefused(bytes(data))

    def test_mini_chain_cycle(self):
        b = sample(3)
        data = bytearray(b.build())
        chain = b.chains["\x05SummaryInformation"]
        struct.pack_into("<I", data, (b.chains["<minifat>"][0] + 1) * 512 + 4 * chain[2], chain[0])
        self.assertRefused(bytes(data))

    def difat_file(self):
        b = Builder(3)
        b.add("Scene", payload(14000 * 512, 9))
        data = bytearray(b.build())
        difat = struct.unpack_from("<I", data, 68)[0]
        self.assertNotEqual(difat, END)
        return data, (difat + 1) * 512

    def test_difat_cycle(self):
        data, off = self.difat_file()
        struct.pack_into("<I", data, off + 508, struct.unpack_from("<I", data, 68)[0])  # next DIFAT = itself
        struct.pack_into("<I", data, 44, 0x200)  # more FAT sectors than the file lists, so the walk goes on
        self.assertRefused(bytes(data))

    def test_difat_sector_outside(self):
        data, _ = self.difat_file()
        struct.pack_into("<I", data, 68, 500000)
        self.assertRefused(bytes(data))

    def test_difat_hole(self):
        data, off = self.difat_file()
        struct.pack_into("<I", data, off, FREE)  # the first FAT sector the DIFAT lists
        self.assertRefused(bytes(data))

    def test_hostile_names_are_not_listed(self):
        def names(entries):
            entries[2]["name"] = "SCENE"  # the same name as entry 1 without case
            entries[3]["name"] = "a/b"
        with cfb.CompoundFile(sample().build(patch_dir=names)) as cf:
            listed = cf.names()
            self.assertNotIn("a/b", listed)
            self.assertNotIn("SCENE", listed)
            for name in listed:
                cf.open(name).read()

    def test_not_a_compound_file(self):
        self.assertRefused(b"PK\x03\x04" + b"\0" * 1000)
        self.assertRefused(b"")
        self.assertRefused(cfb.MAGIC + b"\0" * 100)

    def test_bad_header_fields(self):
        good = sample().build()
        for offset, value in ((26, 5), (28, 0xFEFF), (30, 10), (32, 7), (56, 0x800)):
            bad = bytearray(good)
            struct.pack_into("<I" if offset == 56 else "<H", bad, offset, value)
            self.assertRefused(bytes(bad))

    def test_fat_larger_than_file(self):
        bad = bytearray(sample().build())
        struct.pack_into("<I", bad, 44, 100000)
        self.assertRefused(bytes(bad))

    def test_truncated(self):
        good = sample().build()
        for cut in (513, 4096, 4096 + 100, len(good) // 2, len(good) - 4096):
            self.assertRefused(good[:cut])

    def test_errors_never_leak_other_exceptions(self):
        # Flip bytes all over a small file: every outcome is a working file or CfbError, and every listed name
        # opens.
        good = sample(3).build()
        for pos in range(0, len(good), 37):
            bad = bytearray(good)
            bad[pos] ^= 0xA5
            try:
                with cfb.CompoundFile(bytes(bad)) as cf:
                    for name in cf.names():
                        cf.open(name).read()
            except CfbError:
                pass


class Fixtures(unittest.TestCase):
    def test_every_fixture_matches_tools_cfb(self):
        files = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
        if not files:
            self.skipTest("no tests/fixtures/*.max")
        for path in files:
            with self.subTest(os.path.basename(path)):
                with open(path, "rb") as f:
                    data = f.read()
                other = tools_cfb.Compound(data)
                with cfb.CompoundFile(path) as cf:
                    self.assertEqual(sorted(cf.names()), sorted(other.names()))
                    for name in ("Scene", "ClassDirectory3", "ClassData", "Config"):
                        self.assertTrue(cf.exists(name), name)
                    for name in cf.names():
                        self.assertEqual(cf.open(name, decompress=False).read(), other.read(name), name)


if __name__ == "__main__":
    unittest.main()
