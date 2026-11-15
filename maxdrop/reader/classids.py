# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The 3ds Max classes the project knows, by constant name: superclass ids and ClassIds.

A ClassId is unique only within its superclass (Standard material and RootNode are both (2, 0)), so dispatch
compares both: `entry.superclass == MATERIAL and entry.class_id == STANDARD_MTL`. CLASSES maps each known pair to
the class name 3ds Max writes; tests/unit/test_classdir.py checks every entry against the class directory of a
committed fixture, so add a class here only together with a fixture that has it. No bpy.
"""
from .classdir import ClassId

# Superclass ids (SClass_ID of the 3ds Max SDK).
BASENODE = 0x0001
PARAMETER_BLOCK = 0x0008
GEOMOBJECT = 0x0010
HELPER = 0x0050
PARAMETER_BLOCK2 = 0x0082
REF_MAKER = 0x0100
REF_TARGET = 0x0200
MATERIAL = 0x0C00
LAYER = 0x10F0
CTRL_FLOAT = 0x9003
CTRL_POINT3 = 0x9005
CTRL_MATRIX3 = 0x9008
CTRL_POSITION = 0x900B
CTRL_ROTATION = 0x900C
CTRL_SCALE = 0x900D
CTRL_MASTERPOINT = 0x9010

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
    (BASENODE, NODE): "Node",
    (BASENODE, ROOT_NODE): "RootNode",
    (REF_MAKER, SCENE): "Scene",
    (LAYER, BASE_LAYER): "Base Layer",
    (REF_TARGET, LAYER_MANAGER): "Layer Manager",
    (PARAMETER_BLOCK, PARAM_BLOCK): "ParamBlock",
    (PARAMETER_BLOCK2, PARAM_BLOCK2): "ParamBlock2",
    (GEOMOBJECT, EDITABLE_MESH): "Editable Mesh",
    (GEOMOBJECT, EDITABLE_POLY): "Editable Poly",
    (HELPER, DUMMY): "Dummy",
    (MATERIAL, STANDARD_MTL): "Standard",
    (MATERIAL, MULTI_SUB_MTL): "Multi/Sub-Object",
    (CTRL_MATRIX3, PRS): "Position/Rotation/Scale",
    (CTRL_FLOAT, BEZIER_FLOAT): "Bezier Float",
    (CTRL_SCALE, BEZIER_SCALE): "Bezier Scale",
    (CTRL_ROTATION, EULER_XYZ): "Euler XYZ",
    (CTRL_POSITION, POSITION_XYZ): "Position XYZ",
    (CTRL_FLOAT, FLOAT_LIST): "Float List",
    (CTRL_POSITION, POSITION_LIST): "Position List",
    (CTRL_ROTATION, ROTATION_LIST): "Rotation List",
    (CTRL_SCALE, SCALE_LIST): "Scale List",
    (CTRL_MASTERPOINT, MASTER_POINT): "Master Point Controller",
}


def name_of(superclass, class_id):
    """The class name of a known (superclass, ClassId) pair, else None."""
    return CLASSES.get((superclass, ClassId(*class_id)))
