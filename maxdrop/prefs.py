# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preferences of MaxDrop: the version with Check for Updates, and the folders to search for textures."""

import os

import bpy
from bpy.props import CollectionProperty, IntProperty, StringProperty

from . import update

ISSUES_URL = "https://github.com/jsiovn/maxdrop/issues"


def _preferences(context=None):
    """The add-on preferences, None when the package is not an enabled add-on (headless runs import it from
    sys.path)."""
    addon = (context or bpy.context).preferences.addons.get(__package__)
    return getattr(addon, "preferences", None)


def texture_dirs(context=None):
    """The texture search folders that exist, in the order of the list, each once."""
    p = _preferences(context)
    found = []
    for item in (p.texture_dirs if p is not None else ()):
        folder = os.path.normpath(bpy.path.abspath(item.path)) if item.path else ""
        if folder and os.path.isdir(folder) and folder not in found:
            found.append(folder)
    return found


class MaxDropTextureDir(bpy.types.PropertyGroup):
    path: StringProperty(
        name="Folder",
        description="A folder that holds textures of your .max scenes",
        subtype='DIR_PATH',
    )


class MAXDROP_OT_texture_dir_add(bpy.types.Operator):
    bl_idname = "maxdrop.texture_dir_add"
    bl_label = "Add Folder"
    bl_description = "Add a row to the texture search folders"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _preferences(context) is not None

    def execute(self, context):
        _preferences(context).texture_dirs.add()
        return {'FINISHED'}


class MAXDROP_OT_texture_dir_remove(bpy.types.Operator):
    bl_idname = "maxdrop.texture_dir_remove"
    bl_label = "Remove Folder"
    bl_description = "Remove this folder from the list. Nothing is deleted on disk"
    bl_options = {'INTERNAL'}

    index: IntProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return _preferences(context) is not None

    def execute(self, context):
        dirs = _preferences(context).texture_dirs
        if not 0 <= self.index < len(dirs):
            return {'CANCELLED'}
        dirs.remove(self.index)
        return {'FINISHED'}


class MaxDropPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    texture_dirs: CollectionProperty(type=MaxDropTextureDir)

    def draw(self, context):
        col = self.layout.column()
        update.draw(col)
        col.separator()
        col.label(text="Texture Search Folders")
        for i, item in enumerate(self.texture_dirs):
            row = col.row(align=True)
            row.prop(item, "path", text="")
            row.operator(MAXDROP_OT_texture_dir_remove.bl_idname, text="", icon='X').index = i
        col.operator(MAXDROP_OT_texture_dir_add.bl_idname, icon='ADD')
        # The list is stored from the first release so that it survives updates; the importer starts using it
        # with the material rework.
        col.label(text="Not searched yet in this version: textures are looked up next to the .max file",
                  icon='INFO')
        col.separator()
        row = col.row(align=True)
        row.operator("wm.url_open", text="Install Page", icon='URL').url = update.INSTALL_PAGE
        row.operator("wm.url_open", text="Report a Bug", icon='URL').url = ISSUES_URL


_classes = (MaxDropTextureDir, MAXDROP_OT_texture_dir_add, MAXDROP_OT_texture_dir_remove, MaxDropPreferences)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
