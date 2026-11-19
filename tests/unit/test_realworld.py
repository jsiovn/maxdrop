# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/reader/realworld.py, the Real-World Map Size flag convert.extrude, convert.uvwmap and
convert.primitives share: no Blender. Synthetic chunks: the entry of the class among others in either order, short
and damaged entries, no entry.

    python -I -m unittest discover tests
"""
import importlib
import os
import struct
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PKG = "maxdrop_convert_test"  # the package the convert tests make: maxdrop/__init__.py (bpy) never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
chunks = importlib.import_module(_PKG + ".reader.chunks")
classids = importlib.import_module(_PKG + ".reader.classids")
realworld = importlib.import_module(_PKG + ".reader.realworld")

OWN, OTHER = classids.SPHERE, (0x1234, 0x5678)


def leaf(cid, payload):
    return struct.pack("<HI", cid, 6 + len(payload)) + payload


def holder(cid, *children):
    body = b"".join(children)
    return struct.pack("<HI", cid, (6 + len(body)) | 0x80000000) + body


def entry(cls, value, value_bytes=None):
    payload = struct.pack("<I", value) if value_bytes is None else value_bytes
    return holder(0x0110, leaf(0x0120, struct.pack("<5I", cls[0], cls[1], 0x10, 0, 4)), leaf(0x0130, payload))


def flag(*entries, class_id=OWN):
    chunk = chunks.index(holder(0x0001, holder(0x2150, leaf(0x0100, struct.pack("<I", 1)), *entries)))[0]
    return realworld.flag(chunk, class_id)


class Flag(unittest.TestCase):
    def test_the_entry_of_its_own_class(self):
        self.assertTrue(flag(entry(OWN, 1)))
        self.assertFalse(flag(entry(OWN, 0)))
        self.assertTrue(flag(entry(OWN, 7)))  # any non-zero u32

    def test_another_class_entry_is_not_the_flag(self):
        self.assertFalse(flag(entry(OTHER, 1)))
        self.assertTrue(flag(entry(OTHER, 1), class_id=OTHER))

    def test_both_orders(self):
        self.assertTrue(flag(entry(OTHER, 0), entry(OWN, 1)))
        self.assertFalse(flag(entry(OTHER, 1), entry(OWN, 0)))
        self.assertTrue(flag(entry(OWN, 1), entry(OTHER, 0)))
        self.assertFalse(flag(entry(OWN, 0), entry(OTHER, 1)))

    def test_the_first_entry_of_the_class_decides(self):
        self.assertFalse(flag(entry(OWN, 0), entry(OWN, 1)))
        self.assertTrue(flag(entry(OWN, 1), entry(OWN, 0)))

    def test_a_short_value_is_off(self):
        self.assertFalse(flag(entry(OWN, 0, b"\x01\x00")))
        self.assertFalse(flag(entry(OWN, 0, b"")))
        self.assertFalse(flag(entry(OWN, 0, b"\x01\x00"), entry(OWN, 1)))  # it is the class's entry: no fallback
        self.assertTrue(flag(entry(OTHER, 0, b"\x01"), entry(OWN, 1)))
        self.assertTrue(flag(entry(OWN, 0, struct.pack("<IH", 1, 0))))  # longer: the first u32

    def test_an_entry_without_a_value_is_off(self):
        no_value = holder(0x0110, leaf(0x0120, struct.pack("<5I", OWN[0], OWN[1], 0x10, 0, 4)))
        self.assertFalse(flag(no_value, entry(OWN, 1)))

    def test_damaged_entries_are_skipped(self):
        short_class = holder(0x0110, leaf(0x0120, struct.pack("<I", OWN[0])), leaf(0x0130, struct.pack("<I", 0)))
        no_class = holder(0x0110, leaf(0x0130, struct.pack("<I", 0)))
        leaf_entry = leaf(0x0110, struct.pack("<I", 0))
        for damaged in (short_class, no_class, leaf_entry):
            self.assertFalse(flag(damaged))
            self.assertTrue(flag(damaged, entry(OWN, 1)))

    def test_no_entry_and_no_holder(self):
        self.assertFalse(flag())
        no_holder = chunks.index(holder(0x0001, leaf(0x0100, struct.pack("<I", 1))))[0]
        self.assertFalse(realworld.flag(no_holder, OWN))
        leaf_holder = chunks.index(holder(0x0001, leaf(0x2150, struct.pack("<I", 1))))[0]
        self.assertFalse(realworld.flag(leaf_holder, OWN))
        a_leaf = chunks.index(leaf(0x0001, struct.pack("<I", 1)))[0]
        self.assertFalse(realworld.flag(a_leaf, OWN))

    def test_class_id_as_a_plain_tuple(self):
        self.assertTrue(flag(entry(OWN, 1), class_id=(OWN[0], OWN[1])))
        self.assertTrue(flag(entry(OWN, 1), class_id=[OWN[0], OWN[1]]))


if __name__ == "__main__":
    unittest.main()
