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


def light_nodes(light):
    """(tree, emission, output) of a Light: its node tree (4.x makes it when use_nodes is set, 5.x gives every light
    one), the active Light Output and the Emission linked into its Surface, made and linked when missing (a link of
    another node into that Surface is replaced). Nodes are found by type, not by name (a name may be translated)."""
    tree = node_tree(light)
    outputs = [n for n in tree.nodes if n.bl_idname == "ShaderNodeOutputLight"]
    output = next((n for n in outputs if n.is_active_output), outputs[0] if outputs else None)
    if output is None:
        output = tree.nodes.new("ShaderNodeOutputLight")
    surface = output.inputs["Surface"]
    emission = next((k.from_node for k in surface.links if k.from_node.bl_idname == "ShaderNodeEmission"), None)
    if emission is None:
        emission = tree.nodes.new("ShaderNodeEmission")
        tree.links.new(emission.outputs["Emission"], surface)
    return tree, emission, output


def ies_gain(horizontal):
    """The gain at which Cycles' IES Texture node reads a file of these horizontal angles over its candelas, at 10 to
    90 degrees from the axis (docs/FORMAT.md, "The IES Texture node in Blender, measured"): on 4.2 and 4.5 35/32 for
    one plane (0, or 0 and 360), 17/16 for planes 0 and 180, 1 for the other layouts (other layouts of 0 to 180 and
    4.3, 4.4, 5.0 and 5.1 not measured); 1 on 5.x."""
    import bpy
    if bpy.app.version >= (5, 0, 0):
        return 1.0
    planes = {h % 360.0 for h in horizontal}
    return 35.0 / 32.0 if planes == {0.0} else 17.0 / 16.0 if planes == {0.0, 180.0} else 1.0


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
