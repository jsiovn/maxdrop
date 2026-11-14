# SPDX-FileCopyrightText: 2023-2026 Sebastian Schrand
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Modified for MaxDrop, 2026-11-14 (jsiovn). This file was `__init__.py` of io_scene_max 1.9.2. The operator, the
# file handler, the panel ids and the menu text are renamed so that MaxDrop can be installed next to io_scene_max;
# the export operator the handler named never existed and is gone; the package `__init__.py` now reloads the
# modules. The options and what they import are unchanged.


__author__ = "Sebastian Sille <nrgsille@gmail.com>"


import bpy
from bpy_extras.io_utils import (
    ImportHelper,
    orientation_helper,
    axis_conversion,
)
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    StringProperty,
    CollectionProperty,
)

from .compat import poll_file_object_drop


@orientation_helper(axis_forward='Y', axis_up='Z')
class IMPORT_SCENE_OT_maxdrop(bpy.types.Operator, ImportHelper):
    """Import a 3ds Max .max scene"""
    bl_idname = "import_scene.maxdrop"
    bl_label = "Import .max (MaxDrop)"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".max"
    filter_glob: StringProperty(default="*.max", options={'HIDDEN'})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH')

    scale_objects: FloatProperty(
        name="Scale",
        description="Scale factor for all objects",
        min=0.0, max=10000.0,
        soft_min=0.0, soft_max=10000.0,
        default=1.0,
    )
    use_image_search: BoolProperty(
        name="Image Search",
        description="Search subdirectories for any associated images "
        "(Warning, may be slow)",
        default=True,
    )
    object_filter: EnumProperty(
        name="Object Filter", options={'ENUM_FLAG'},
        items=(('MATERIAL', "Material".rjust(12), "", 'MATERIAL_DATA', 0x1),
               ('UV', "UV Maps".rjust(11), "", 'UV_DATA', 0x2),
               ('PRIMITIVE', "Primitive".rjust(13), "", 'CUBE', 0x4),
               ('EMPTY', "Empty".rjust(11), "", 'EMPTY_AXIS', 0x8),
               ('ARMATURE', "Armature".rjust(11), "", 'ARMATURE_DATA', 0x10),
               ),
        description="Object types to import",
        default={'MATERIAL', 'UV', 'PRIMITIVE', 'EMPTY', 'ARMATURE'},
    )
    use_collection: BoolProperty(
        name="Collection",
        description="Create a new collection",
        default=False,
    )
    use_apply_matrix: BoolProperty(
        name="Apply Matrix",
        description="Use matrix to transform the objects",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        import_include(layout, self)
        import_transform(layout, self)

    def execute(self, context):
        from . import import_max
        keywords = self.as_keywords(ignore=("axis_forward", "axis_up", "filter_glob"))
        global_matrix = axis_conversion(from_forward=self.axis_forward, from_up=self.axis_up,).to_4x4()
        keywords["global_matrix"] = global_matrix

        return import_max.load(self, context, **keywords)

    def invoke(self, context, event):
        return self.invoke_popup(context)


def import_include(layout, operator):
    header, body = layout.panel("MAXDROP_import_include", default_closed=False)
    header.label(text="Include")
    if body:
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_image_search")
        layrow.label(text="", icon='OUTLINER_OB_IMAGE' if operator.use_image_search else 'IMAGE_DATA')
        layout.column().prop(operator, "object_filter")
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_collection")
        layrow.label(text="", icon='OUTLINER_COLLECTION' if operator.use_collection else 'GROUP')


def import_transform(layout, operator):
    header, body = layout.panel("MAXDROP_import_transform", default_closed=False)
    header.label(text="Transform")
    if body:
        layout.prop(operator, "scale_objects")
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_apply_matrix")
        layrow.label(text="", icon='VIEW_ORTHO' if operator.use_apply_matrix else 'MESH_GRID')
        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")


class IO_FH_maxdrop(bpy.types.FileHandler):
    bl_idname = "IO_FH_maxdrop"
    bl_label = "MaxDrop (.max)"
    bl_import_operator = "import_scene.maxdrop"
    bl_file_extensions = ".max"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


def menu_func(self, context):
    self.layout.operator(IMPORT_SCENE_OT_maxdrop.bl_idname, text="MaxDrop (.max)")


_classes = (IMPORT_SCENE_OT_maxdrop, IO_FH_maxdrop)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
