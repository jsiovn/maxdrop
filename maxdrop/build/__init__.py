# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The only part of MaxDrop's new pipeline that creates Blender data: objects and meshes from a
convert.scene.SceneDescription, later collections, node graphs, lights and cameras.

Nothing is imported at load: each module is imported on demand.
"""
