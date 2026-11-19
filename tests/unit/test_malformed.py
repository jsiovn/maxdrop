# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Damaged input through the whole reader path the operator runs (compound file, summary, class directory, Scene
index, unit, scene description): no Blender. A .max comes from anywhere, so whatever is wrong with it must come
out as a MaxFileError (CfbError, ChunkError, MetadataError, GeometryError), never IndexError, struct.error or
another exception. Every fixture is cut short at a few lengths and garbled with a fixed seed, so a failure is
reproducible; its chunk tree is also written again with records cut short and with references past the last
object, the input that reaches the reader's IndexError and struct.error paths if a check is missing. The fuzz
harness (tests/unit/fuzz.py, test_fuzz.py) mutates the same fixtures in many more ways and at depth; the counts
here stay small to keep the plain suite fast.

    python -I -m unittest discover tests
"""
import glob
import importlib
import os
import random
import struct
import sys
import types
import unittest

try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
SEED = 20261115
GARBLED_PER_FIXTURE = 10
CUTS_PER_FIXTURE = 8
RECORDS_PER_FIXTURE = 10

# A package named apart from the add-on whose path is maxdrop/: relative imports resolve, and maxdrop/__init__.py
# (which imports bpy) never runs.
_PKG = "maxdrop_malformed_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
cfb = importlib.import_module(_PKG + ".reader.cfb")
chunks = importlib.import_module(_PKG + ".reader.chunks")
classdir = importlib.import_module(_PKG + ".reader.classdir")
metadata = importlib.import_module(_PKG + ".reader.metadata")
reader_scene = importlib.import_module(_PKG + ".reader.scene")
units = importlib.import_module(_PKG + ".reader.units")
conv = importlib.import_module(_PKG + ".convert.scene")
MaxFileError = importlib.import_module(_PKG + ".reader.errors").MaxFileError


def _describe(sc):
    unit = units.system_unit(sc)
    if numpy is not None:  # the description reads the meshes through numpy
        conv.describe(sc, 0.0254, unit)


def _streams(path):
    with cfb.CompoundFile(path) as cf:
        name = "ClassDirectory3" if cf.exists("ClassDirectory3") else "ClassDirectory"
        dlls = bytes(cf.open("DllDirectory").read()) if cf.exists("DllDirectory") else None
        return bytes(cf.open("Scene").read()), bytes(cf.open(name).read()), dlls


def _read_streams(scene, classes, dlls):
    _describe(reader_scene.Scene(scene, classdir.ClassDirectory.parse(classes, dlls)))


def _read_file(data):
    with cfb.CompoundFile(data) as cf:
        try:
            metadata.read(cf)
        except metadata.MetadataError:  # the operator reads on without the summary
            pass
        _describe(reader_scene.Scene.from_file(cf))


def _garble(rng, data, near=None):
    out = bytearray(data)
    for _ in range(rng.randint(1, 6)):
        span = min(len(out), near) if near and rng.random() < 0.6 else len(out)
        out[rng.randrange(span)] = rng.randrange(256)
    if rng.random() < 0.15:
        del out[rng.randrange(1, len(out)):]
    return bytes(out)


def _leaves(chunk):
    if not chunk.container:
        return [chunk]
    return [leaf for child in chunk.children for leaf in _leaves(child)]


def _rewritten(scene, offset, payload):
    """scene with payload in place of the leaf at offset, the sizes of the leaf and of its containers fixed."""
    path, level = [], chunks.index(scene)
    while not path or path[-1].offset != offset:
        path.append(next(c for c in level if c.offset <= offset < c.end))
        level = path[-1].children
    leaf = path[-1]
    out = bytearray(scene[:leaf.payload_offset] + payload + scene[leaf.end:])
    for chunk in path:  # every header comes before the leaf's payload: its offset did not move
        if chunk.header != 6:
            raise AssertionError("a 64-bit chunk header in a fixture")
        raw, = struct.unpack_from("<I", out, chunk.offset + 2)
        struct.pack_into("<I", out, chunk.offset + 2, raw + len(payload) - leaf.payload_size)  # bit 31 kept
    return bytes(out)


def _cuts(size):
    return sorted({max(1, size * k // CUTS_PER_FIXTURE) for k in range(CUTS_PER_FIXTURE)} | {size - 1})


class DamagedInputTest(unittest.TestCase):
    def assertOnlyMaxFileError(self, read, *args, what=""):
        try:
            read(*args)
        except MaxFileError:
            pass
        except Exception as exc:  # a defect: the reader's errors are MaxFileErrors
            self.fail("%s: %s escaped the reader: %s" % (what, type(exc).__name__, exc))

    def test_fixtures_present(self):
        self.assertTrue(FIXTURES)

    def test_truncated_scene_and_class_directory(self):
        for path in FIXTURES:
            scene, classes, dlls = _streams(path)
            name = os.path.basename(path)
            for n in _cuts(len(scene)):
                self.assertOnlyMaxFileError(_read_streams, scene[:n], classes, dlls,
                                          what="%s Scene cut at %d" % (name, n))
            for n in _cuts(len(classes)):
                self.assertOnlyMaxFileError(_read_streams, scene, classes[:n], dlls,
                                          what="%s class directory cut at %d" % (name, n))

    def test_garbled_scene_and_class_directory(self):
        rng = random.Random(SEED)
        for path in FIXTURES:
            scene, classes, dlls = _streams(path)
            name = os.path.basename(path)
            for k in range(GARBLED_PER_FIXTURE):
                if k % 5:
                    args, which = (_garble(rng, scene), classes, dlls), "Scene"
                else:
                    args, which = (scene, _garble(rng, classes), dlls), "class directory"
                self.assertOnlyMaxFileError(_read_streams, *args, what="%s garbled %s #%d" % (name, which, k))

    def test_records_cut_short(self):
        rng = random.Random(SEED + 2)
        for path in FIXTURES:
            scene, classes, dlls = _streams(path)
            name = os.path.basename(path)
            first = _leaves(chunks.index(scene)[0])[0]
            self.assertEqual(_rewritten(scene, first.offset, first.tobytes()), scene)
            leaves = [c for c in _leaves(chunks.index(scene)[0]) if c.payload_size]
            for leaf in rng.sample(leaves, min(RECORDS_PER_FIXTURE, len(leaves))):
                for n in (0, leaf.payload_size // 2, leaf.payload_size - 1):
                    self.assertOnlyMaxFileError(_read_streams, _rewritten(scene, leaf.offset, leaf.tobytes()[:n]),
                                              classes, dlls,
                                              what="%s %04X at %d cut to %d bytes" % (name, leaf.id, leaf.offset, n))

    def test_references_past_the_objects(self):
        rng = random.Random(SEED + 3)
        for path in FIXTURES:
            scene, classes, dlls = _streams(path)
            name = os.path.basename(path)
            objects = chunks.index(scene)[0].children
            past = len(objects) + 5
            refs = [c for obj in objects if obj.container for c in obj.children if c.id in (0x2034, 0x2035)]
            self.assertTrue(refs, name)
            for ref in rng.sample(refs, min(RECORDS_PER_FIXTURE, len(refs))):
                raw = ref.tobytes()
                if ref.id == 0x2034:  # i32 object indices
                    bad = struct.pack("<%di" % (len(raw) // 4), *[past] * (len(raw) // 4))
                else:  # a u32, then (u32 slot, i32 object index) pairs
                    pairs = struct.unpack("<%dI" % ((len(raw) - 4) // 4), raw[4:])
                    bad = raw[:4] + struct.pack("<%dI" % len(pairs), *[v if k % 2 == 0 else past
                                                                       for k, v in enumerate(pairs)])
                self.assertOnlyMaxFileError(_read_streams, _rewritten(scene, ref.offset, bad), classes, dlls,
                                          what="%s %04X at %d past the objects" % (name, ref.id, ref.offset))

    def test_failed_reference_read_keeps_no_iterator(self):
        # A struct unpack iterator over a chunk's view holds a buffer export of it. Left in a frame of the
        # traceback, it crashes Python <= 3.11 when the garbage collector clears that memoryview. 0x2034 is the
        # case that crashed (a comprehension frame keeps its iterator); 0x2035 guards the pairs loop.
        unpack_iterator = type(struct.iter_unpack("<i", b""))
        for path in FIXTURES:
            scene, classes, dlls = _streams(path)
            name = os.path.basename(path)
            objects = chunks.index(scene)[0].children
            for wanted in (0x2034, 0x2035):
                ref = next((c for obj in objects if obj.container for c in obj.children
                            if c.id == wanted and c.payload_size >= (4 if wanted == 0x2034 else 12)), None)
                if ref is None:
                    continue
                raw, past = ref.tobytes(), len(objects) + 5
                if wanted == 0x2034:
                    bad = struct.pack("<%di" % (len(raw) // 4), *[past] * (len(raw) // 4))
                else:
                    bad = raw[:4] + struct.pack("<Ii", 0, past) * ((len(raw) - 4) // 8)
                sc = reader_scene.Scene(_rewritten(scene, ref.offset, bad),
                                        classdir.ClassDirectory.parse(classes, dlls))
                held = None
                for i in range(len(sc)):
                    try:
                        sc.refs(i)
                    except chunks.ChunkError as exc:
                        tb, held = exc.__traceback__, []
                        while tb is not None:
                            held += [k for k, v in tb.tb_frame.f_locals.items() if isinstance(v, unpack_iterator)]
                            tb = tb.tb_next
                        del exc, tb
                        break
                self.assertIsNotNone(held, "%s %04X: no reference read failed" % (name, wanted))
                self.assertEqual(held, [], "%s %04X: an unpack iterator outlives the raise" % (name, wanted))

    def test_truncated_and_garbled_files(self):
        rng = random.Random(SEED + 1)
        for path in FIXTURES:
            with open(path, "rb") as f:
                raw = f.read()
            name = os.path.basename(path)
            for n in _cuts(len(raw)):
                self.assertOnlyMaxFileError(_read_file, raw[:n], what="%s cut at %d" % (name, n))
            for k in range(GARBLED_PER_FIXTURE):  # biased to the header, the FAT and the directory
                self.assertOnlyMaxFileError(_read_file, _garble(rng, raw, near=4096), what="%s garbled #%d" % (name, k))


if __name__ == "__main__":
    unittest.main()
