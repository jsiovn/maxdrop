# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transform controllers at frame 0: every node's local, world and object-offset matrix, as 3ds Max computes them.

    t = Transforms(scene)
    t.world(i)          # node i's world transform (node.transform in MAXScript, the pivot)
    t.offset(i)         # object offset: where the object sits relative to the pivot
    t.object_world(i)   # offset * world (node.objectTransform): object-space vertices times this = world
    t.issues            # Issue(node, controller, superclass, class_id, reason), in the order met
    m, issues = matrix(scene, i)        # Matrix3 controller i alone (a modifier's gizmo); Issue.node is None
    v, issues = parameter_value(scene, i)   # the float or color controller of a material or map parameter
                                        # (pblock.Animated) at frame 0; None where it cannot be evaluated

Matrices are 4x4 tuples of row tuples of floats (float64) in Max's row-vector convention: a point p becomes
p * M, row 4 holds the translation, and A * B applies A first. That is the layout of the oracle's `transform`.
Local = scale * rotation * position (PRS); world = local * parent world through the whole parent chain.
Negative scale is kept as it is (a mirrored node has a negative determinant).

Controllers are dispatched on (superclass, ClassId). A keyframe controller (Linear, Bezier or TCB Float, Position,
Rotation or Scale) saves its value at the time slider of the save in 0x2501 (float), 0x2503 (point), 0x2504
(quaternion) or 0x2505 (3 x f32 scale, then the scale axis as a 4 x f32 quaternion) (a Bezier Color, the Point3
controller of an animated color parameter: 0x2501 with 3 x f32, its keys laid out as Bezier Position's), directly or
inside 0x7127, with 0x2500, the interval that value holds for (forever without keys), and its keys in a chunk of its
class (_KEYFRAMED: i32 time, u32 flags, the value at byte 8, then tangents or TCB parameters). The saved value is used
when its interval holds time 0; otherwise the keys are evaluated at time 0. Outside the controller's range (0x3003,
the keys' first and last time unless the range bar was moved) its out-of-range types (0x8499) map the time back
into it (out_of_range: Constant, Cycle, Loop, Ping Pong, Relative Repeat, Linear); inside the range the keys give the
first key's value before them and the last's after them, between two keys linear for a Linear controller
(rotation by slerp the way the stored signs give, opposite quaternions a whole turn about the earlier key's local Z),
along the tangents for Bezier (the cubic of the handles, its time curve solved; a handle a third long but for a
custom tangent, auto ones flagged in 0x2533 / 0x2534; a Linear tangent facing a custom or auto one the chord's slope;
a free handle's length in frames of Scene.ticks_per_frame; a step key held; constant velocity out of a Position key
by length along 40 chords) and TCB (Hermite at the eased fraction; rotations by squad, a turn of a revolution or
more with a half-turn of squad at either end), a scale axis by slerp at the time fraction, and linear with an issue
where 3ds Max's curve is not known (_between). A saved value without an
interval is used as it is, with an issue when several keys animate it (it may be another frame's). Euler angles
are radians, the axis order (0x1003) 0 for XYZ and 100 + order for the others; a Max quaternion (x, y, z, w) as
stored is the conjugate of the usual one, so the standard column-vector formula applied to it gives the row-vector
matrix. List controllers keep their entry count in 0x1010
and the entries at reference slots 0..n-1; their weights are parameter 0 of the list's ParamBlock2 (a float table:
stored values, or controllers where animated). A list sums its entries times their weights (Float and Position
List), multiplies I + (S - I) * weight (Scale List) or the rotations turned by their weights, a later entry first
(Rotation List). With Average on (parameter 1) a Float, Position or Scale List divides that weighted sum by the
weights' sum (nothing, or identity, when they add up to 0) and a Rotation List slerps from no rotation towards each
entry in turn by its weight. A Scale List weight after a turned scale axis, and an average of one, are issues.

A Look At controller (a Matrix3 controller: target cameras and lights) and a LookAt Constraint (a rotation
controller in a PRS) give the node's world matrix from the world positions of other nodes (the target, the
constraint's targets and up node): scale * aim frame * translation(P), P the position controller's value times the
parent's world matrix; the parent's rotation and scale do not reach the frame. The node's local matrix is that
world matrix times the parent's inverse, and its children follow the world matrix. The constraint's offsets are
quaternions of its own: with Keep Initial Offset the aim frame becomes (local rotation at assignment) * (aim frame at
the first evaluation)^-1 * frame, without it frame * (the Set Orientation rotation). look_frame() and
constraint_frame() say how a frame is aimed, look_at(i) describes a node's Look At controller. Every node of a
look-at cycle (one aimed at itself included) is damaged, whichever node is asked for first; a look-at that waits on
more than MAX_LOOK_AT_DEPTH others is damaged.

Anything not supported gives identity (zero position, no rotation, unit scale) for that controller and an Issue:
an unknown class (also a Look At or a constraint outside a node, as a modifier's gizmo, and a constraint anywhere
but a PRS's rotation), keys of an unknown layout, a list weight that is not stored, an Euler order other than
the six Tait-Bryan ones, a damaged controller (a reference cycle, a chain deeper than MAX_DEPTH, a payload too
short) or a non-finite result. An unknown out-of-range type keeps the keys' value (the range end's outside the
range), with an issue. The file comes from anywhere: one bad controller poisons only its own node's local matrix.
Every class read here is in a committed fixture (docs/FORMAT.md). No bpy, no mathutils, no numpy.
"""

import bisect
import collections
import math
import struct

from .. import chunks, classids, pblock, scene as scene_mod
from ..errors import MaxFileError

from .ids import (
    ChunkError, MAX_DEPTH, MAX_KEYS, MAX_LOOK_AT_DEPTH, IDENTITY, UNKNOWN_CLASS, KEYS_UNKNOWN, KEYS_INTERPOLATED,
    ANIMATED, LIST_WEIGHT, LIST_BLOCK, EULER_ORDER, NO_CONTROLLER, DAMAGED, NON_FINITE, LOOK_AT_AXIS, LOOK_AT_NODE,
    LOOK_AT_PARENT, CONSTRAINT_EMPTY, CONSTRAINT_OFFSET, CONSTRAINT_DEGENERATE, CONSTRAINT_SETTING, CONSTRAINT_BLOCK,
    ORT_UNKNOWN, ORT_APPROXIMATED, LIST_AVERAGE, SCALE_LIST_WEIGHT, Issue, LookAt, _FLOAT_VALUE, _POINT_VALUE,
    _QUAT_VALUE, _SCALE_VALUE, _INTERVAL, _WRAP, _EULER_ORDER, _EULER_ORDER_BASE, _LIST_COUNT, _LIST_WEIGHTS,
    _LIST_AVERAGE, _ORT, _ORT_BEFORE, _ORT_AFTER, _ORT_OFF, _RANGE, _ORT_CONSTANT, _ORT_CYCLE, _ORT_LOOP,
    _ORT_PING_PONG, _ORT_LINEAR, _ORT_RELATIVE, _ORT_KNOWN, _NO_TIME, _AUTO_IN, _AUTO_OUT, _BITS, _KEY_IDS, _KEY_VALUE,
    _TIME, _INTERVAL_FORMAT, _KEYFRAMED, _LINEAR, _BEZIER, _TCB, _IN_TYPE, _OUT_TYPE, _LINEAR_TANGENT, _STEP, _CUSTOM,
    _CONSTANT_VELOCITY, _FREE_HANDLE, _DEFAULT_LENGTH, _SOLVE_STEPS, _CHORDS, _SPIN, _SPIN_GAP, _OPPOSITE,
    _NEAR_OPPOSITE, _LOOK_AXIS, _LOOK_FLIP, _LOOK_TARGET_UP, _LC_WEIGHTS, _LC_TARGETS, _LC_RELATIVE,
    _LC_SET_ORIENTATION, _LC_AXIS, _LC_AXIS_FLIP, _LC_UP_AXIS, _LC_UP_WORLD, _LC_UP_NODE, _LC_SOURCE_UP,
    _LC_SOURCE_UP_FLIP, _LC_UP_CONTROL, _LC_INITIAL_LOCAL, _LC_INITIAL_FRAME, _LC_USER, _LC_WEIGHT_DEFAULT, _TINY,
)
from .math3d import (
    multiply, _mat3, translation, _NAN_MATRIX, quat_matrix, _cos_sin, _axis, EULER_ORDERS, euler_matrix, _transpose3,
    _rows3, scale_matrix, _weighted_quat, _qpow, _matrix_quat, _unit_quat, slerp, _slerp_long, _opposite, _qmul, turn,
    spin, squad, _bits, _finite, _near_identity, _diagonal, _sub, _dot, _cross, _neg, _unit, _point, _inverse,
    look_frame, constraint_frame,
)
from .keys import (
    ease, hermite, handle, _cubic, bezier, constant_velocity, _tangents, _between, _interpolate, _scale_value, _Keys,
    _conjugate, _repeat, _extend, out_of_range,
)
from .evaluate import _At, _Eval
from .transforms import Transforms, parameter_value, matrix
