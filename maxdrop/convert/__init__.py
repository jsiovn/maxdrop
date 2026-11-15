# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the reader found, turned into a scene description Blender can be built from: meters, Z up, Blender's
matrix convention. Later also material, texture, light and camera rules and the import report.

No module here imports bpy or mathutils, so the whole package runs under plain Python. Nothing is imported at
load: each module is imported on demand.
"""
