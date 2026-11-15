# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The system unit of a .max file: what one unit of its coordinates measures.

    with CompoundFile(path) as cf:
        unit = system_unit(cf)          # SystemUnit("millimeters", 0.001), or None
        unit.name, unit.meters          # meters per system unit

The Scene stream holds one object of class Scene ((0x2222, 0), superclass 0x100); its 0x8520 chunk is an i32 unit
type and an f32 scale: 1 unit = scale x the unit type. The types are those of the 3ds Max SDK (UNITS_INCHES = 0,
FEET, MILES, MILLIMETERS, CENTIMETERS, METERS, KILOMETERS = 6); docs/FORMAT.md says which fixture shows which.

A scale other than 1 (a custom unit, "1 unit = 2.5 centimeters") is named "2.5 centimeters" and folded into
meters. An unknown type, a scale that is not a positive finite number, a payload too short, a file without the
chunk and a Scene stream or class directory that cannot be read give None: the caller then asks the user. A
positive scale is taken as stored, however odd; judging it is the caller's part. No bpy.
"""
import collections
import math
import struct

from . import cfb, chunks, classids, scene as scene_mod

SYSTEM_UNIT_CHUNK = 0x8520

UNITS = {
    0: ("inches", 0.0254),
    1: ("feet", 0.3048),
    2: ("miles", 1609.344),
    3: ("millimeters", 0.001),
    4: ("centimeters", 0.01),
    5: ("meters", 1.0),
    6: ("kilometers", 1000.0),
}

_PAYLOAD = struct.Struct("<if")


class SystemUnit(collections.namedtuple("SystemUnit", "name meters")):
    """The unit's name and how many meters one system unit measures."""
    __slots__ = ()


def decode(payload):
    """The SystemUnit of a 0x8520 payload (bytes-like), None when it cannot be one."""
    if len(payload) < _PAYLOAD.size:
        return None
    unit_type, scale = _PAYLOAD.unpack_from(payload)
    unit = UNITS.get(unit_type)
    if unit is None or not math.isfinite(scale) or scale <= 0:
        return None
    name, meters = unit
    scale = float("%.7g" % scale)  # the f32's own precision: 2.54 stays 2.54, not 2.5399999618
    if scale == 1.0:
        return SystemUnit(name, meters)
    return SystemUnit("%g %s" % (scale, name), meters * scale)


def system_unit(source):
    """The SystemUnit of an open cfb.CompoundFile or a scene.Scene; None when the file does not say."""
    try:
        return _find(source if isinstance(source, scene_mod.Scene) else scene_mod.Scene.from_file(source))
    except (cfb.CfbError, chunks.ChunkError):
        return None


def _find(scene):
    holders = {e.index for e in scene.classes
               if e.superclass == classids.SC_REF_MAKER and e.class_id == classids.SCENE}
    if not holders:
        return None
    for i in range(len(scene)):
        if scene.class_index(i) in holders:
            chunk = scene.chunk(i)
            found = chunk.first(SYSTEM_UNIT_CHUNK) if chunk.container else None
            if found is not None:
                return decode(found.view())
    return None
