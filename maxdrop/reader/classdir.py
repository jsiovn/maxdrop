# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The class directory of a .max: what class each Scene chunk id stands for.

    with CompoundFile(path) as cf:
        classes = ClassDirectory.from_file(cf)
    entry = classes.get(chunk.id)       # a Scene child's id is its class index, or a special id past the
                                        # directory (0x2032, a derived object), for which get() gives None
    entry.class_id == classids.EDITABLE_POLY; entry.superclass; entry.name; entry.dll_name

ClassDirectory3 (ClassDirectory in older files) holds one 0x2040 container per class: 0x2060 = i32 dll index,
u32 classA, u32 classB, u32 superclass id; 0x2042 = the class name in UTF-16LE. The class index counts the 0x2040
entries from 0. DllDirectory holds a 0x21C0 header chunk, then one 0x2038 container per plug-in DLL, 0x2039 =
description, 0x2037 = file name; a dll index counts the 0x2038 entries from 0, and a negative one means none
(-1: built into 3ds Max). The class name is for people: code compares ClassIds, never names. No bpy.
"""
import collections

from . import chunks

ChunkError = chunks.ChunkError

_CLASS_ENTRY, _CLASS_IDS, _CLASS_NAME = 0x2040, 0x2060, 0x2042
_DLL_ENTRY, _DLL_FILE, _DLL_DESCRIPTION = 0x2038, 0x2037, 0x2039
_U32 = 0xFFFFFFFF


class ClassId(tuple):
    """A 3ds Max Class_ID: compares and hashes as the tuple (classA, classB), prints as hex."""
    __slots__ = ()

    def __new__(cls, a, b):
        a, b = int(a), int(b)
        if not (0 <= a <= _U32 and 0 <= b <= _U32):
            raise ValueError("ClassId parts must be unsigned 32-bit: %r, %r" % (a, b))
        return tuple.__new__(cls, (a, b))

    @classmethod
    def from_int(cls, value):
        """From the single 64-bit number upstream's tables use: classB << 32 | classA."""
        return cls(value & _U32, value >> 32)

    @property
    def a(self):
        return self[0]

    @property
    def b(self):
        return self[1]

    def __int__(self):
        return self[1] << 32 | self[0]

    def __getnewargs__(self):
        return tuple(self)

    def __repr__(self):
        return "ClassId(0x%08X, 0x%08X)" % self

    def __str__(self):
        return "(0x%08X, 0x%08X)" % self


DllEntry = collections.namedtuple("DllEntry", "index file description")


class ClassEntry(collections.namedtuple("ClassEntry", "index class_id superclass name dll_index dll")):
    """One class: its index, ClassId, superclass id, name, raw dll index and DllEntry (None when it has none)."""
    __slots__ = ()

    @property
    def class_a(self):
        return self.class_id[0]

    @property
    def class_b(self):
        return self.class_id[1]

    @property
    def dll_name(self):
        return self.dll.file if self.dll is not None else None


def _text(container, cid):
    chunk = container.first(cid)
    return chunk.text() if chunk is not None else ""


def parse_dlls(data):
    """The DllEntry list of a DllDirectory stream (bytes-like or cfb.Stream)."""
    out = []
    for chunk in chunks.index(data):
        if chunk.id == _DLL_ENTRY and chunk.container:
            out.append(DllEntry(len(out), _text(chunk, _DLL_FILE), _text(chunk, _DLL_DESCRIPTION)))
    return out


class ClassDirectory:
    """The classes of a file by index, with their DLLs. `stream` names the stream they came from."""

    def __init__(self, classes, dlls=(), stream=None):
        self._classes = tuple(classes)
        self.dlls = tuple(dlls)
        self.stream = stream
        self._by_id = {}
        for entry in self._classes:
            self._by_id.setdefault(entry.class_id, []).append(entry)

    @classmethod
    def parse(cls, classdir_data, dlldir_data=None, stream=None):
        """From the bytes (or cfb.Streams) of ClassDirectory3 or ClassDirectory, and of DllDirectory."""
        dlls = parse_dlls(dlldir_data) if dlldir_data is not None else []
        classes = []
        for chunk in chunks.index(classdir_data):
            if chunk.id != _CLASS_ENTRY:
                continue
            ids = chunk.first(_CLASS_IDS) if chunk.container else None
            if ids is None:
                raise ChunkError("class entry %d at %d has no 0x%04X chunk" % (len(classes), chunk.offset, _CLASS_IDS))
            dll_index, a, b, superclass = ids.unpack("<iIII")
            dll = dlls[dll_index] if 0 <= dll_index < len(dlls) else None
            classes.append(ClassEntry(len(classes), ClassId(a, b), superclass, _text(chunk, _CLASS_NAME),
                                      dll_index, dll))
        return cls(classes, dlls, stream)

    @classmethod
    def from_file(cls, cf):
        """From an open cfb.CompoundFile: ClassDirectory3, else ClassDirectory; DllDirectory when present."""
        for name in ("ClassDirectory3", "ClassDirectory"):
            if cf.exists(name):
                break
        else:
            raise ChunkError("the file has no class directory")
        dlldir = cf.open("DllDirectory") if cf.exists("DllDirectory") else None
        return cls.parse(cf.open(name), dlldir, name)

    def __len__(self):
        return len(self._classes)

    def __getitem__(self, index):
        if index < 0:
            raise IndexError("class index %d" % index)
        return self._classes[index]

    def __iter__(self):
        return iter(self._classes)

    def __repr__(self):
        return "ClassDirectory(%d classes, %d dlls)" % (len(self._classes), len(self.dlls))

    def get(self, index):
        """The entry of a class index, or None when the file has no such class."""
        return self._classes[index] if 0 <= index < len(self._classes) else None

    def find(self, class_id):
        """Every entry of a ClassId (a file may list one twice)."""
        return list(self._by_id.get(ClassId(*class_id), ()))
