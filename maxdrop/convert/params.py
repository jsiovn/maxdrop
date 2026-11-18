# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parameter values as the rules use them: a number only when it is a finite int or float (a bool, None, NaN or
a damaged value is not), else the rule's default. Shared by materials.py and texmaps.py (materials imports texmaps,
so neither can hold them for the other). No bpy.

    num(m, pid, block, default)     # float of parameter pid of MtlBase m (block None: the first that stores it)
    flag(m, pid, block, default)    # bool of the same
"""
import math


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def num(m, pid, block, default):
    v = m.param(pid, block)
    return float(v) if finite(v) else default


def flag(m, pid, block, default):
    v = m.param(pid, block)
    return bool(v) if finite(v) else default
