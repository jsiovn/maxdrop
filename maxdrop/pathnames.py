# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Name rules reader/, convert/ and intake/ share, kept in one place because they decide what is opened or
written.

    base_name(r"C:\\maps\\wood.jpg")    # "wood.jpg": the last part of a stored path, either separator
    is_reserved("con.txt")             # True: Windows opens a device for such a name, in any folder

The only module of the add-on outside those packages that they import: no bpy, no mathutils, no other import of
the add-on, so the plain tests load it under a package of their own.
"""

# Windows also reserves COM and LPT with a superscript digit.
RESERVED = frozenset(["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
                     + ["%s%s" % (p, d) for p in ("COM", "LPT") for d in "123456789¹²³"])


def base_name(path):
    """The last part of a stored path, with both separators 3ds Max may write."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def is_reserved(name):
    """True when Windows takes a file name for a device: the part before the first dot, trailing spaces
    dropped, is a reserved name in any case."""
    return name.split(".", 1)[0].rstrip(" ").upper() in RESERVED
