# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The 3ds Max classes the project knows, by constant name: superclass ids (SC_*, ints) and ClassIds.

A ClassId is unique only within its superclass (Standard material and RootNode are both (2, 0)), so dispatch
compares both: `entry.superclass == SC_MATERIAL and entry.class_id == STANDARD_MTL`. CLASSES maps each known
pair to the class name 3ds Max writes; tests/unit/test_classdir.py checks every entry against the class directory
of a committed fixture, so add a class here only together with a fixture that has it. No bpy.
"""
from .classdir import ClassId

# Superclass ids (SClass_ID of the 3ds Max SDK).
SC_BASENODE = 0x0001
SC_PARAMETER_BLOCK = 0x0008
SC_GEOMOBJECT = 0x0010
SC_HELPER = 0x0050
SC_PARAMETER_BLOCK2 = 0x0082
SC_REF_MAKER = 0x0100
SC_REF_TARGET = 0x0200
SC_MATERIAL = 0x0C00
SC_LAYER = 0x10F0
SC_CTRL_FLOAT = 0x9003
SC_CTRL_POINT3 = 0x9005
SC_CTRL_MATRIX3 = 0x9008
SC_CTRL_POSITION = 0x900B
SC_CTRL_ROTATION = 0x900C
SC_CTRL_SCALE = 0x900D
SC_CTRL_MASTERPOINT = 0x9010

# Scene structure.
NODE = ClassId(0x00000001, 0)
ROOT_NODE = ClassId(0x00000002, 0)
SCENE = ClassId(0x00002222, 0)
BASE_LAYER = ClassId(0x7E9858FE, 0x1DBA1DF0)
LAYER_MANAGER = ClassId(0x0D7374FC, 0x51FF028E)
PARAM_BLOCK = ClassId(0x00000008, 0)
PARAM_BLOCK2 = ClassId(0x00000082, 0)

# Geometry and helpers.
EDITABLE_MESH = ClassId(0xE44F10B3, 0)
EDITABLE_POLY = ClassId(0x1BF8338D, 0x192F6098)
DUMMY = ClassId(0x00876234, 0)

# Materials.
STANDARD_MTL = ClassId(0x00000002, 0)
MULTI_SUB_MTL = ClassId(0x00000200, 0)

# Controllers.
PRS = ClassId(0x00002005, 0)
BEZIER_FLOAT = ClassId(0x00002007, 0)
BEZIER_SCALE = ClassId(0x00002010, 0)
EULER_XYZ = ClassId(0x00002012, 0)
POSITION_XYZ = ClassId(0x118F7E02, 0xFFEE238A)
FLOAT_LIST = ClassId(0x4B4B1000, 0)
POSITION_LIST = ClassId(0x4B4B1002, 0)
ROTATION_LIST = ClassId(0x4B4B1003, 0)
SCALE_LIST = ClassId(0x4B4B1004, 0)
MASTER_POINT = ClassId(0x0D9C20FF, 0)

CLASSES = {
    (SC_BASENODE, NODE): "Node",
    (SC_BASENODE, ROOT_NODE): "RootNode",
    (SC_REF_MAKER, SCENE): "Scene",
    (SC_LAYER, BASE_LAYER): "Base Layer",
    (SC_REF_TARGET, LAYER_MANAGER): "Layer Manager",
    (SC_PARAMETER_BLOCK, PARAM_BLOCK): "ParamBlock",
    (SC_PARAMETER_BLOCK2, PARAM_BLOCK2): "ParamBlock2",
    (SC_GEOMOBJECT, EDITABLE_MESH): "Editable Mesh",
    (SC_GEOMOBJECT, EDITABLE_POLY): "Editable Poly",
    (SC_HELPER, DUMMY): "Dummy",
    (SC_MATERIAL, STANDARD_MTL): "Standard",
    (SC_MATERIAL, MULTI_SUB_MTL): "Multi/Sub-Object",
    (SC_CTRL_MATRIX3, PRS): "Position/Rotation/Scale",
    (SC_CTRL_FLOAT, BEZIER_FLOAT): "Bezier Float",
    (SC_CTRL_SCALE, BEZIER_SCALE): "Bezier Scale",
    (SC_CTRL_ROTATION, EULER_XYZ): "Euler XYZ",
    (SC_CTRL_POSITION, POSITION_XYZ): "Position XYZ",
    (SC_CTRL_FLOAT, FLOAT_LIST): "Float List",
    (SC_CTRL_POSITION, POSITION_LIST): "Position List",
    (SC_CTRL_ROTATION, ROTATION_LIST): "Rotation List",
    (SC_CTRL_SCALE, SCALE_LIST): "Scale List",
    (SC_CTRL_MASTERPOINT, MASTER_POINT): "Master Point Controller",
}


def name_of(superclass, class_id):
    """The class name of a known (superclass, ClassId) pair, else None."""
    return CLASSES.get((superclass, ClassId(*class_id)))
