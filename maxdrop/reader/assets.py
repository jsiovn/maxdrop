# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The files a scene names: asset id -> (type, path), from the asset metadata stream.

    table = AssetTable.from_file(cf)    # cf: an open cfb.CompoundFile
    e = table.get(guid)                 # AssetEntry(guid, type, path, resolved), None when the id is unknown
    e.name                              # the file name of path (of resolved when path is empty)
    bitmap_file(table, mtl)             # the AssetEntry of a Bitmap map (MtlBase), None without one
    files_of(table, mtl)                # [(block id, param id, AssetEntry)] of every asset a map or material holds

The stream is FileAssetMetaData3 (files saved by 3ds Max 2018 and later, as far as the fixtures and the corpus
show) or FileAssetMetaData2 (older), empty when the scene names no file. Its records follow each other with no
header and no count. A string is a u32 count of UTF-16 units (the NUL not counted), the units, then a UTF-16 NUL,
which is there also for an empty string. A FileAssetMetaData2 record is the 16-byte asset id, the asset type
("Bitmap", "Photometric", ...) and the path as the scene stores it; a FileAssetMetaData3 record adds a third
string, the absolute path 3ds Max found the file at when it saved the scene (empty when it found none, or when the
stored path was absolute already). A parameter of type file name or bitmap holds the asset id (pblock.Asset): a
Bitmap's file is its parameter 13 in block 0. docs/FORMAT.md has the layout.

The file comes from anywhere: a stream over MAX_STREAM is not read, a string over MAX_STRING units or one that
leaves the stream ends the table there (the records before it are kept), a repeated asset id keeps the first
record; each is named in issues. The paths are data: nothing here opens them (convert/textures.py decides what may
be looked up). No bpy.
"""
import collections
import struct

from . import cfb, classids, pblock

STREAMS = (("FileAssetMetaData3", 3), ("FileAssetMetaData2", 2))
MAX_STREAM = 64 << 20
MAX_STRING = 32767  # UTF-16 units: the longest path Windows takes
GUID_SIZE = 16
BITMAP_FILE = 13  # Bitmap block 0, parameter "bitmap"

_COUNT = struct.Struct("<I")


class AssetEntry(collections.namedtuple("AssetEntry", "guid type path resolved")):
    """One file a scene names. resolved: the absolute path 3ds Max saved for it ("" when none, or in a
    FileAssetMetaData2 stream)."""
    __slots__ = ()

    @property
    def name(self):
        return base_name(self.path) or base_name(self.resolved)


def base_name(path):
    """The last part of a stored path, with both separators 3ds Max may write."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


class _Damaged(Exception):
    pass


def _string(data, pos):
    if pos + 4 > len(data):
        raise _Damaged("string count at %d leaves the stream" % pos)
    count, = _COUNT.unpack_from(data, pos)
    if count > MAX_STRING:
        raise _Damaged("string of %d units at %d is longer than %d" % (count, pos, MAX_STRING))
    start, end = pos + 4, pos + 4 + 2 * count
    if end + 2 > len(data):
        raise _Damaged("string at %d leaves the stream" % pos)
    if data[end:end + 2] != b"\0\0":
        raise _Damaged("string at %d does not end in a NUL" % pos)
    return bytes(data[start:end]).decode("utf-16-le", "replace"), end + 2


class AssetTable:
    """The asset records of one scene, by asset id."""

    def __init__(self, entries=(), issues=(), stream=None):
        self._by_guid = {}
        self.issues = list(issues)
        self.stream = stream
        for e in entries:
            if e.guid in self._by_guid:
                self.issues.append("asset id %s is listed twice: the first record is kept" % e.guid.hex())
            else:
                self._by_guid[e.guid] = e

    def __repr__(self):
        return "AssetTable(%d assets)" % len(self._by_guid)

    def __len__(self):
        return len(self._by_guid)

    def __iter__(self):
        return iter(self._by_guid.values())

    @classmethod
    def from_file(cls, cf):
        """The table of an open cfb.CompoundFile; empty when it has no asset stream."""
        for name, strings in STREAMS:
            if not cf.exists(name):
                continue
            try:
                data = cf.open(name, max_size=MAX_STREAM).read()
            except cfb.CfbError as e:
                return cls(issues=["%s not read: %s" % (name, e)], stream=name)
            if len(data) > MAX_STREAM:
                return cls(issues=["%s is larger than %d bytes: not read" % (name, MAX_STREAM)], stream=name)
            return cls.parse(data, strings, name)
        return cls()

    @classmethod
    def parse(cls, data, strings, stream=None):
        """The table of a stream's bytes; strings: 3 for FileAssetMetaData3, 2 for FileAssetMetaData2."""
        if strings not in (2, 3):
            raise ValueError("strings must be 2 or 3")
        if len(data) > MAX_STREAM:
            return cls(issues=["asset stream is larger than %d bytes: not read" % MAX_STREAM], stream=stream)
        entries, issues, pos = [], [], 0
        while pos < len(data):
            try:
                if pos + GUID_SIZE > len(data):
                    raise _Damaged("asset id at %d leaves the stream" % pos)
                guid = bytes(data[pos:pos + GUID_SIZE])
                kind, at = _string(data, pos + GUID_SIZE)
                path, at = _string(data, at)
                resolved = ""
                if strings == 3:
                    resolved, at = _string(data, at)
            except _Damaged as e:
                issues.append("asset record %d: %s; the records after it are not read" % (len(entries), e))
                break
            entries.append(AssetEntry(guid, kind, path, resolved))
            pos = at
        return cls(entries, issues, stream)

    def get(self, guid):
        """The entry of an asset id (16 bytes or a pblock.Asset), None when the table does not list it."""
        if isinstance(guid, pblock.Asset):
            guid = guid.guid
        return self._by_guid.get(guid)

    def entry(self, value):
        """The entry of a parameter value when it is an asset, else None."""
        return self.get(value.guid) if isinstance(value, pblock.Asset) else None


def _blocks(mtl):
    yield from sorted(mtl.blocks.items())
    for slot, part in sorted(mtl.parts.items()):
        yield from sorted(part.blocks.items())


def files_of(table, mtl):
    """[(block id, param id, AssetEntry)] for every asset value in a material's or map's blocks and parts' blocks
    that the table lists, in reference order."""
    out = []
    for _slot, block in _blocks(mtl):
        for p in block:
            for v in p.values or ():
                e = table.entry(v)
                if e is not None:
                    out.append((block.block_id, p.id, e))
    return out


def bitmap_file(table, mtl):
    """The file of a Bitmap map (superclass texmap, classids.BITMAP_TEX), None for another class or a Bitmap
    without one."""
    if mtl.superclass != classids.SC_TEXMAP or tuple(mtl.class_id) != tuple(classids.BITMAP_TEX):
        return None
    return table.entry(mtl.param(BITMAP_FILE, block_id=0))
