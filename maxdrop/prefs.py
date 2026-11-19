# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preferences of MaxDrop: the version with Check for Updates, where scene packs are unpacked, and the folders to
search for textures."""

import os
import tempfile

import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, StringProperty

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


def writable(folder):
    """True when a folder can be created in folder: os.access does not see Windows ACLs."""
    try:
        os.rmdir(tempfile.mkdtemp(prefix=".maxdrop-probe-", dir=folder))
    except OSError:
        return False
    return True


_CHOOSE = "Choose a folder under Unpack Scene Packs Into in the MaxDrop preferences."


class PackFolderError(ValueError):
    """No folder to unpack a scene pack into. str() is the message; lines are the same words as popup labels, the
    folder on one of its own (a label does not wrap)."""

    def __init__(self, message, lines):
        super().__init__(message)
        self.lines = tuple(lines)


def pack_parent(archive_path, context=None):
    """The folder a scene pack is unpacked into (its pack folder is made inside). PackFolderError with the message
    for the user when there is none."""
    p = _preferences(context)
    folder = os.path.normpath(bpy.path.abspath(p.pack_dir)) if p is not None and p.pack_dir else ""
    if p is not None and p.pack_target == 'FOLDER':
        if not folder or not os.path.isdir(folder):
            first = "The folder to unpack scene packs into does not exist."
            raise PackFolderError(first + " " + _CHOOSE, (first, _CHOOSE))
        return folder
    beside = os.path.dirname(os.path.abspath(archive_path))
    if writable(beside):
        return beside
    if folder and os.path.isdir(folder) and writable(folder):
        return folder
    raise PackFolderError("Cannot write into %s. %s" % (beside, _CHOOSE), ("Cannot write into", beside, _CHOOSE))


_LOOKUP = ("A folder that holds textures of your .max scenes, searched with its subfolders. A texture is looked "
           "for by its file name: in the scene's folder, then in folders named maps or textures beside the scene file or its folder, "
           "then in these folders in their order, and last at the path stored in the scene, only when it is on a "
           "local drive. Network and device paths stored in a scene are never opened")


class MaxDropTextureDir(bpy.types.PropertyGroup):
    path: StringProperty(
        name="Folder",
        description=_LOOKUP,
        subtype='DIR_PATH',
    )


class MAXDROP_OT_texture_dir_add(bpy.types.Operator):
    bl_idname = "maxdrop.texture_dir_add"
    bl_label = "Add Folder"
    bl_description = ("Add a folder to search for textures, after the scene's folder and its maps or textures "
                      "folders")
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
    pack_target: EnumProperty(
        name="Unpack Scene Packs Into",
        description="Where a .zip, .rar or .7z scene pack is unpacked before the import",
        items=(('ARCHIVE', "Next to the Archive", "A folder named after the archive, beside it. The folder below "
                "is used when the archive's folder cannot be written"),
               ('FOLDER', "This Folder", "A folder named after the archive, inside the folder below")),
        default='ARCHIVE',
    )
    pack_dir: StringProperty(
        name="Folder",
        description="Where scene packs are unpacked with This Folder, and when the archive's own folder cannot "
        "be written",
        subtype='DIR_PATH',
    )

    def draw(self, context):
        col = self.layout.column()
        update.draw(col)
        col.separator()
        col.label(text="Unpack Scene Packs Into")
        col.row().prop(self, "pack_target", expand=True)
        col.prop(self, "pack_dir", text="")
        col.separator()
        col.label(text="Texture Search Folders")
        for i, item in enumerate(self.texture_dirs):
            row = col.row(align=True)
            row.prop(item, "path", text="")
            row.operator(MAXDROP_OT_texture_dir_remove.bl_idname, text="", icon='X').index = i
        col.operator(MAXDROP_OT_texture_dir_add.bl_idname, icon='ADD')
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
