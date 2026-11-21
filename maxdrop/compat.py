# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The differences between the Blender versions MaxDrop supports (4.2 LTS to 5.2 LTS), in one place."""


def node_tree(block):
    """The node tree of a material or World: 4.x makes a new one with use_nodes off (a World without a tree), 5.x
    always uses nodes (and deprecates the property, so a later version may drop it)."""
    if not getattr(block, "use_nodes", True):
        block.use_nodes = True
    return block.node_tree


material_node_tree = node_tree


try:
    from bpy_extras.io_utils import poll_file_object_drop
except ImportError:
    # The manifest claims 4.2.0 and the 4.2 API documentation does not list this helper (4.2.23 has it).
    def poll_file_object_drop(context):
        """A drop on the 3D Viewport or on the Outliner in View Layer mode, as bpy_extras defines it."""
        area = context.area
        if not area:
            return False
        return area.type == 'VIEW_3D' or (area.type == 'OUTLINER' and area.spaces.active.display_mode == 'VIEW_LAYER')
