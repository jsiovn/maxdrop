# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Intake: turn what a scene was downloaded as (a .max, or an archive holding it) into a .max on disk.

Imported on demand, never by the add-on's register(). Nothing here imports bpy or mathutils, so it runs and is
tested under plain Python.
"""
