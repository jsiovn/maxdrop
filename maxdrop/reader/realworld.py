# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real-World Map Size of an object or a modifier: the one reader convert.extrude, convert.uvwmap and
convert.primitives share.

    on = flag(scene.chunk(i), class_id)     # bool; class_id: the object's or the modifier's own ClassID

The flag is not in a parameter block: the object's or modifier's own chunk holds 0x2150 {0x0100 u32 1, 0x0110
{0x0120 naming a class (the first 8 bytes its ClassID), 0x0130 u32 flag}, ...}; no 0x2150 while mapping is off.
0x2150 can hold several 0x0110 entries (an instanced modifier, another plug-in's data): only the first one whose
0x0120 names class_id is the flag. docs/FORMAT.md says which fixture shows what.

The chunk comes from anywhere: a leaf 0x0110 or a 0x0120 shorter than a ClassID is skipped, a 0x0130 shorter than
a u32 in the entry of the class is off; a damaged chunk tree under the chunk raises ChunkError, as any walk of it
does (the callers decide what that costs). No bpy.
"""

HOLDER, ENTRY, CLASS, VALUE = 0x2150, 0x0110, 0x0120, 0x0130
_CLASS_SIZE, _VALUE_SIZE = 8, 4


def flag(chunk, class_id):
    """Whether Real-World Map Size is on in chunk (a reader.chunks chunk) for class_id (a ClassId or (a, b))."""
    if not chunk.container:
        return False
    holder = chunk.first(HOLDER)
    if holder is None or not holder.container:
        return False
    key = tuple(class_id)
    for entry in holder.find_all(ENTRY):
        if not entry.container:
            continue
        cls = entry.first(CLASS)
        if cls is None or cls.payload_size < _CLASS_SIZE or cls.unpack("<II") != key:
            continue
        value = entry.first(VALUE)
        return value is not None and value.payload_size >= _VALUE_SIZE and value.unpack("<I")[0] != 0
    return False
