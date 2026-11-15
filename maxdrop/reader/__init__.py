# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The .max file itself, read without Blender: the compound file container (cfb), and later its chunks, class
directory, scene index, nodes, controllers, geometry, parameter blocks, assets and units.

No module here imports bpy or mathutils, so the whole package runs under plain Python. Nothing is imported at
load: each module is imported on demand.
"""
