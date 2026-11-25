# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The controllers' limits, issue texts, chunk ids and key layouts."""
import collections
import math
import struct

from .. import chunks, classids


ChunkError = chunks.ChunkError

MAX_DEPTH = 32  # controllers below one node's transform controller
MAX_KEYS = 1 << 20  # per key chunk, read only without a saved value
MAX_LOOK_AT_DEPTH = 64  # nodes whose matrices wait on one another: a look-at's target aimed at another target...

IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))

UNKNOWN_CLASS = "unknown controller class"
KEYS_UNKNOWN = "keys of an unknown layout, not read"
KEYS_INTERPOLATED = "between two keys, interpolated linearly"
ANIMATED = "several keys beside a saved value without its interval, the saved value used"
LIST_WEIGHT = "list weight not stored, 1.0 used"
LIST_BLOCK = "damaged list weights, 1.0 used where unread"
EULER_ORDER = "unsupported Euler order, XYZ used"
NO_CONTROLLER = "node without a transform controller"
DAMAGED = "damaged controller"
NON_FINITE = "non-finite transform"
LOOK_AT_AXIS = "Look At axis out of range, Z used"
LOOK_AT_NODE = "look-at target or up node that is no node, none used"
LOOK_AT_PARENT = "look-at under a parent that cannot be inverted"
CONSTRAINT_EMPTY = "LookAt Constraint without a target of any weight, no rotation"
CONSTRAINT_OFFSET = "LookAt Constraint offset (Keep Initial Offset, Set Orientation) missing or damaged, not applied"
CONSTRAINT_DEGENERATE = "LookAt Constraint that cannot be aimed (on its target, up along the view), no rotation"
CONSTRAINT_SETTING = "animated or damaged LookAt Constraint setting, its default used"
CONSTRAINT_BLOCK = "damaged LookAt Constraint parameters, the defaults used where unread"
ORT_UNKNOWN = "out-of-range type not known, the value at the end of the range used"
ORT_APPROXIMATED = ("out-of-range type approximated (Loop over a range moved off the keys, scale axes that differ, "
                    "ORTs off beside a moved range)")
LIST_AVERAGE = "Scale List average of turned scale axes, the weighted mean of the matrices used"
SCALE_LIST_WEIGHT = "Scale List weight on turned scale axes, applied as on plain ones"


class Issue(collections.namedtuple("Issue", "node controller superclass class_id reason")):
    """One thing the transforms could not follow: node and controller are object indices (controller None when
    the node has none), superclass and class_id those of the controller (None when unknown)."""
    __slots__ = ()


class LookAt(collections.namedtuple("LookAt", "target axis flip roll target_up")):
    """A node's Look At controller: target the target node's object index (None without one), axis 0, 1 or 2 (-X,
    -Y or -Z looks at the target), flip (+ that axis looks instead), roll in radians, target_up whether the
    target's Z axis is the up direction (else the world's)."""
    __slots__ = ()


_FLOAT_VALUE, _POINT_VALUE, _QUAT_VALUE, _SCALE_VALUE = 0x2501, 0x2503, 0x2504, 0x2505
_INTERVAL, _WRAP = 0x2500, 0x7127
_EULER_ORDER = 0x1003
_EULER_ORDER_BASE = 100  # 3ds Max 2020 saves XYZ as 0 and the other orders as 100 + order
_LIST_COUNT = 0x1010
_LIST_WEIGHTS, _LIST_AVERAGE = 0, 1  # parameters of the list's ParamBlock2
# beside a keyframe controller's keys: the out-of-range types (0x8499: 0x3000 before, 0x3001 after, 0x3003 1 when
# they are switched off) and the range they apply outside (0x3003: start and end time); the same id twice on
# purpose: _ORT_OFF is looked up inside 0x8499, _RANGE beside it
_ORT, _ORT_BEFORE, _ORT_AFTER, _ORT_OFF, _RANGE = 0x8499, 0x3000, 0x3001, 0x3003, 0x3003
_ORT_CONSTANT, _ORT_CYCLE, _ORT_LOOP, _ORT_PING_PONG, _ORT_LINEAR, _ORT_RELATIVE = 1, 2, 3, 4, 5, 7
_ORT_KNOWN = frozenset((_ORT_CONSTANT, _ORT_CYCLE, _ORT_LOOP, _ORT_PING_PONG, _ORT_LINEAR, _ORT_RELATIVE))
_NO_TIME = -2 ** 31
# bit arrays (in 0x2700: i32 count, then a bit per key) of the Bezier keys whose in / out tangent is auto
_AUTO_IN, _AUTO_OUT, _BITS = 0x2533, 0x2534, 0x2700
_KEY_IDS = range(0x2510, 0x2530)
_KEY_VALUE = 8  # a key record: i32 time, u32 flags, then the value
_TIME = struct.Struct("<i")
_INTERVAL_FORMAT = "<ii"  # start and end time
# keyframe controllers: (superclass, ClassId) -> (value chunk, floats of the value, key chunk, bytes per key)
_KEYFRAMED = {
    (classids.SC_CTRL_FLOAT, classids.LINEAR_FLOAT): (_FLOAT_VALUE, 1, 0x2511, 12),
    (classids.SC_CTRL_FLOAT, classids.TCB_FLOAT): (_FLOAT_VALUE, 1, 0x2520, 40),
    (classids.SC_CTRL_FLOAT, classids.BEZIER_FLOAT): (_FLOAT_VALUE, 1, 0x2525, 28),
    (classids.SC_CTRL_POSITION, classids.LINEAR_POSITION): (_POINT_VALUE, 3, 0x2513, 20),
    (classids.SC_CTRL_POSITION, classids.TCB_POSITION): (_POINT_VALUE, 3, 0x2521, 64),
    (classids.SC_CTRL_POSITION, classids.BEZIER_POSITION): (_POINT_VALUE, 3, 0x2526, 80),
    (classids.SC_CTRL_ROTATION, classids.LINEAR_ROTATION): (_QUAT_VALUE, 4, 0x2514, 24),
    (classids.SC_CTRL_ROTATION, classids.TCB_ROTATION): (_QUAT_VALUE, 4, 0x2522, 92),
    (classids.SC_CTRL_ROTATION, classids.BEZIER_ROTATION): (_QUAT_VALUE, 4, 0x2527, 88),
    (classids.SC_CTRL_SCALE, classids.LINEAR_SCALE): (_SCALE_VALUE, 7, 0x2515, 36),
    (classids.SC_CTRL_SCALE, classids.TCB_SCALE): (_SCALE_VALUE, 7, 0x2523, 112),
    (classids.SC_CTRL_SCALE, classids.BEZIER_SCALE): (_SCALE_VALUE, 7, 0x2528, 148),
    # a color parameter's (parameter_value): the saved color in 0x2501, its keys laid out as Bezier Position's
    (classids.SC_CTRL_POINT3, classids.BEZIER_COLOR): (_FLOAT_VALUE, 3, 0x2526, 80),
}
_LINEAR = frozenset((classids.LINEAR_FLOAT, classids.LINEAR_POSITION, classids.LINEAR_ROTATION,
                     classids.LINEAR_SCALE))
_BEZIER = frozenset((classids.BEZIER_FLOAT, classids.BEZIER_POSITION, classids.BEZIER_SCALE))
_TCB = frozenset((classids.TCB_FLOAT, classids.TCB_POSITION, classids.TCB_SCALE))
# a Bezier key's flags: the in tangent's type in bits 7-9, the out tangent's in bits 10-12 (1 linear, 2 step, 5 custom
# or auto, 0 smooth, 3 fast, 4 slow); constant velocity; a free handle, whose length is in frames, not a fraction
_IN_TYPE, _OUT_TYPE, _LINEAR_TANGENT, _STEP, _CUSTOM = 7, 10, 1, 2, 5
_CONSTANT_VELOCITY, _FREE_HANDLE = 0x8000, 0x100000
_DEFAULT_LENGTH = 1.0 / 3.0  # a handle length stored as -1
_SOLVE_STEPS = 60  # bisections of a Bezier segment's time curve: well below a tick
_CHORDS = 40  # constant velocity: the segment's curve as this many chords of equal parameter, as 3ds Max 2020 does
_SPIN = 2.0 * math.pi  # a TCB Rotation turn from here on spins (the f32 of a whole turn, 6.2831855, is above it)
_SPIN_GAP = math.radians(10.0)  # a TCB turn this close below a revolution: 3ds Max's curve is not known
_OPPOSITE = 5e-7  # 1 + the dot of two unit quaternions below this: opposite, a whole revolution apart
_NEAR_OPPOSITE = 1e-3  # 1 + the dot below this but not opposite: which branch 3ds Max takes is not known
_LOOK_AXIS, _LOOK_FLIP, _LOOK_TARGET_UP = 0x0100, 0x0110, 0x0201
# the LookAt Constraint's ParamBlock2 (3 viewline length, 12 viewline length absolute: display only)
(_LC_WEIGHTS, _LC_TARGETS, _LC_RELATIVE, _LC_SET_ORIENTATION, _LC_AXIS, _LC_AXIS_FLIP, _LC_UP_AXIS, _LC_UP_WORLD,
 _LC_UP_NODE, _LC_SOURCE_UP, _LC_SOURCE_UP_FLIP, _LC_UP_CONTROL) = 0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 13
# the constraint's own chunks, Max quaternions: the node's local rotation when the constraint was assigned, the aimed
# frame at its first evaluation, the Set Orientation rotation (0x1001 the world rotation at assignment and 0x1005 a
# u32: not read)
_LC_INITIAL_LOCAL, _LC_INITIAL_FRAME, _LC_USER = 0x1002, 0x1003, 0x1004
_LC_WEIGHT_DEFAULT = 50.0  # a weight not read: appendTarget's, on the constraint's 0-100 scale
_TINY = 1e-12
