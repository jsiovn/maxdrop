# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The owner's reference slot of each owner-held (P_OWNERS_REF) reference parameter, by class and block, for a
ParamBlock2 that has no 0x0013 table.

    owner_slots.slots((classids.SC_TEXMAP, classids.MIX), 0)   # {6: 1, 7: 2, 8: 3, 12: 4}

A file saved in the 3ds Max 2012 format (format 14000) stores no 0x0013 table in its blocks, and for some such
parameters the stored object index is -1 although the reference is set, or stale (another object's): the slot
wins wherever the owner holds a reference there. The slot is the parameter definition's
reference number, a constant of the class: the values here are the 0x0013 tables of the committed fixtures (saved
by 3ds Max 2020) and, where no fixture has the class, of corpus scene B (format 20000), equal in every object of
corpus scene A (format 14000). A table parameter's element k is at slot + k, as with 0x0013. Keyed by superclass
and ClassId (a ClassId is unique only within its superclass). No bpy.
"""
from . import classids
from .classdir import ClassId

# Classes no fixture has (reader/classids.py takes a class only with a fixture): measured by the M2 gate.
VRAY_OVERRIDE_MTL = ClassId(0x15D20E6B, 0x54E217EB)
VRAY_LIGHT_MTL = ClassId(0x7CCF263E, 0x3F5B39B9)
LAYERED_TEXMAP = ClassId(0xC90017A5, 0x111940BB)  # a composite-like map from a plug-in; name not needed

_MTL, _TEX = classids.SC_MATERIAL, classids.SC_TEXMAP

TABLE = {
    # from the fixtures' 0x0013
    (_MTL, classids.MULTI_SUB_MTL): {0: {0: 1}},
    (_MTL, classids.SHELL_MTL): {0: {2: 1, 3: 2}},
    (_MTL, classids.VRAY_2SIDED_MTL): {0: {0: 1, 1: 2}},
    (_MTL, classids.VRAY_MTL): {4: {100 + k: 7 + k for k in range(27)}},  # texmap_diffuse ... in the maps block
    (_TEX, classids.BITMAP_TEX): {0: {15: 2}},
    (_TEX, classids.VRAY_BITMAP): {0: {31: 2}},
    (_TEX, classids.RGB_TINT): {0: {3: 1}},
    (_TEX, classids.MIX): {0: {6: 1, 7: 2, 8: 3, 12: 4}},
    (_TEX, classids.NOISE): {0: {2: 2, 3: 3, 13: 4}},
    (_TEX, classids.RGB_MULTIPLY): {0: {2: 1, 3: 2}},
    (_TEX, classids.OUTPUT_MAP): {0: {2: 1}},
    (_TEX, classids.COLOR_CORRECTION): {0: {1: 1}},
    (_TEX, classids.NORMAL_BUMP): {0: {2: 1, 3: 2}},
    (_TEX, classids.FALLOFF): {0: {2: 4, 6: 5}},
    # no fixture: measured by the M2 gate on corpus scene B's 0x0013 tables
    (_MTL, VRAY_OVERRIDE_MTL): {0: {0: 1, 2: 2, 4: 3, 6: 4, 8: 5}},
    (_MTL, VRAY_LIGHT_MTL): {0: {2: 1, 5: 2, 9: 3}},
    # Composite: texmap_rules' (Max 2020) keeps its maps as block references (pids 9, 10) and has no 0x0013; pids 0
    # and 2 are the older parameters scene B's 0x0013 lists, both at slot 1 there
    (_TEX, classids.COMPOSITE): {0: {0: 1, 2: 1}},
    (_TEX, LAYERED_TEXMAP): {0: {21: 1, 22: 2, 3: 3, 4: 4, 5: 5}},
}

_NONE = {}


def slots(owner_class, block_id):
    """{param id: owner slot} of block block_id of a (superclass, ClassId) owner; empty when not known."""
    if owner_class is None:
        return _NONE
    superclass, class_id = owner_class
    return TABLE.get((superclass, ClassId(*class_id)), _NONE).get(block_id, _NONE)
