# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update check against the published MaxDrop extension repository (GitHub Pages).

Blender does the actual download / upgrade: this module compares versions, registers the remote
repository on first use, and runs Blender's upgrade of that repository when a newer one exists.
The only code of the add-on that goes online, and only when the button is pressed.
"""

import functools
import json
import re
import time
import tomllib
import urllib.request
from pathlib import Path

import bpy

REPO_URL = "https://jsiovn.github.io/maxdrop/index.json"
INSTALL_PAGE = "https://jsiovn.github.io/maxdrop/"
REPO_NAME = "MaxDrop"
EXTENSION_ID = "maxdrop"

_status = ""


@functools.cache
def installed_version():
    with open(Path(__file__).with_name("blender_manifest.toml"), "rb") as f:
        return tomllib.load(f)["version"]


def _version_key(version):
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def fetch_latest_version(timeout=10):
    # Pages serves index.json with max-age=600; the query string skips stale caches.
    with urllib.request.urlopen("%s?t=%d" % (REPO_URL, time.time()), timeout=timeout) as resp:
        listing = json.load(resp)
    for pkg in listing.get("data", []):
        if pkg.get("id") == EXTENSION_ID:
            return pkg["version"]
    raise LookupError("%s is not listed in %s" % (EXTENSION_ID, REPO_URL))


def _repo_module_of_self():
    # Extensions load as bl_ext.<repository module>.<extension id>.
    parts = __package__.split(".")
    return parts[1] if len(parts) == 3 and parts[0] == "bl_ext" else None


def ensure_repo(context):
    """Index of our remote repository in Preferences, adding it on first use."""
    def find():
        for i, repo in enumerate(context.preferences.extensions.repos):
            if repo.use_remote_url and repo.remote_url == REPO_URL:
                return i
        return -1

    if find() < 0:
        bpy.ops.preferences.extension_repo_add(
            type='REMOTE', name=REPO_NAME, remote_url=REPO_URL, use_sync_on_startup=True
        )
    return find()


def _upgrade(index):
    # Run from a timer, after the operator returned: the upgrade unregisters this add-on,
    # including the operator that would otherwise still be executing.
    bpy.context.preferences.extensions.active_repo = index
    try:
        bpy.ops.extensions.package_upgrade_all(use_active_only=True)
    except Exception as ex:
        print("%s: update failed: %s" % (REPO_NAME, ex))
    return None


class MAXDROP_OT_check_updates(bpy.types.Operator):
    bl_idname = "maxdrop.check_updates"
    bl_label = "Check for Updates"
    bl_description = "Compare this version with the MaxDrop repository and install the newer one"

    def execute(self, context):
        global _status
        if not bpy.app.online_access:
            _status = "Online access is off"
            self.report({'WARNING'}, "Allow Online Access in Preferences > System > Network")
            return {'CANCELLED'}
        current = installed_version()
        try:
            latest = fetch_latest_version()
        except Exception as ex:
            _status = "Check failed"
            self.report({'WARNING'}, "Update check failed: %s" % ex)
            return {'CANCELLED'}
        if _version_key(latest) <= _version_key(current):
            _status = "Up to date"
            self.report({'INFO'}, "%s %s is up to date" % (REPO_NAME, current))
            return {'FINISHED'}

        index = ensure_repo(context)
        if index >= 0 and _repo_module_of_self() == context.preferences.extensions.repos[index].module:
            bpy.ops.extensions.repo_sync(repo_index=index)
            bpy.app.timers.register(functools.partial(_upgrade, index), first_interval=0.0)
            _status = "Updating to %s" % latest
            self.report({'INFO'}, "Updating %s %s to %s" % (REPO_NAME, current, latest))
            return {'FINISHED'}

        # Blender only upgrades an extension inside the repository it came from, and the
        # same id enabled from two repositories clashes on class registration.
        _status = "Update %s: reinstall from repo" % latest
        if index >= 0:
            context.preferences.extensions.active_repo = index
        if bpy.ops.screen.userpref_show.poll():
            bpy.ops.screen.userpref_show(section='EXTENSIONS')
        self.report(
            {'WARNING'},
            "This copy was installed from disk, so Blender cannot update it. Uninstall it, then "
            "install it from the %s repository in Get Extensions, or drag the link "
            "from %s into Blender" % (REPO_NAME, INSTALL_PAGE),
        )
        return {'FINISHED'}


def draw(layout):
    """Version, status and the button, for the add-on preferences."""
    layout.label(text="%s v%s" % (REPO_NAME, installed_version()))
    if _status:
        layout.label(text=_status)
    layout.operator(MAXDROP_OT_check_updates.bl_idname, icon='FILE_REFRESH')


_classes = (MAXDROP_OT_check_updates,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    global _status
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    _status = ""
