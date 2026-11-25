# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""MaterialBuilder: one Blender material per MaterialIR, images reused per file and color space."""
import collections
import os
import traceback

import bpy

from ...convert import texmaps as tx
from .sockets import image_has_data
from .tree import _Tree


class MaterialBuilder:
    """Makes the materials of one import; images shared between them."""

    def __init__(self):
        self.images = {}  # (normalized path, color space) -> Image or None (not loaded)
        self._existing = None  # the same key -> an Image that was in the file before this builder: _existing_images
        self._linear = None  # the color space tx.LINEAR resolves to on this Blender: colorspace
        self._issues = []
        self._seen = set()
        self.classes = collections.Counter()
        self.sockets_skipped = collections.Counter()

    def issue(self, label, reason):
        if (label, reason) not in self._seen:
            self._seen.add((label, reason))
            self._issues.append((label, reason))

    def issues(self):
        """[(label, reason)] for the import report, each once, in the order met."""
        return list(self._issues)

    def make(self, ir):
        """A new Material for a MaterialIR; None (an empty slot, and an issue) when building it fails: one material
        never costs the scene."""
        material = bpy.data.materials.new(ir.name or "Material")
        try:
            tree = _Tree(self, material, ir)
            tree.build()
        except Exception as e:
            name = material.name
            bpy.data.materials.remove(material)
            print("MaxDrop: material %s not built:\n%s" % (name, traceback.format_exc()), end="")
            self.issue("material %s" % name, "material not built (%s: %s)" % (type(e).__name__, e))
            return None
        self.sockets_skipped.update(tree.skipped)
        if not ir.unknown:
            self.classes[ir.source] += 1
        return material

    def colorspace(self, name):
        """The color space an image the IR puts in name is loaded in: tx.LINEAR where this Blender's color
        management config has it (the stock one of every supported version does), Non-Color otherwise."""
        if name != tx.LINEAR:
            return name
        if self._linear is None:
            self._linear = tx.LINEAR if tx.LINEAR in _input_colorspaces() else tx.NON_COLOR
        return self._linear

    def image(self, img, label):
        """The Image of a texmaps.Image (None when its file was not found or does not load)."""
        if img.found is None:
            return None
        space = self.colorspace(img.colorspace)
        key = _key(img.found.path, space)
        if key not in self.images:
            if not image_has_data(img.found.path):
                self.issue(label, "texture not loaded: %s (no image data)" % img.name)
                self.images[key] = None
                return None
            existing = self._existing_images().get(key)
            if existing is not None:
                self.images[key] = existing
                return existing
            try:
                image = bpy.data.images.load(img.found.path, check_existing=False)
            except RuntimeError as e:
                self.issue(label, "texture not loaded: %s (%s)" % (img.name, e))
                image = None
            if image is not None:
                image.colorspace_settings.name = space
            self.images[key] = image
        return self.images[key]

    def _existing_images(self):
        """{key: Image} of the images in the file before this builder's first load that may be reused (_reusable),
        the first by name for a key; read once, on the first texture."""
        if self._existing is None:
            self._existing = {}
            for image in bpy.data.images:
                if self._reusable(image):
                    self._existing.setdefault(_key(bpy.path.abspath(image.filepath), image.colorspace_settings.name),
                                              image)
        return self._existing

    @staticmethod
    def _reusable(image):
        """True for an image that still is its file as a load would give it: local (not from a library), loaded
        from a file, not packed, not modified, the alpha mode of a load, its path resolvable. Reads no pixels."""
        path = image.filepath
        return (image.library is None and image.source == 'FILE' and image.packed_file is None
                and not image.is_dirty and bool(path) and image.alpha_mode == _load_alpha_mode(path)
                and not (path.startswith("//") and not bpy.data.filepath))


# mirrors Blender's BKE_image_alpha_mode_from_extension: if Blender's list changes, an image of a format it now treats
# otherwise fails _reusable as loaded and is loaded anew (a missed reuse); only one whose alpha mode was set by hand
# to this list's value would still be reused
_PREMUL_ON_LOAD = (".exr", ".cin", ".dpx", ".hdr")


def _input_colorspaces():
    """The names of the image color spaces of the running Blender's color management (OCIO) config."""
    prop = bpy.types.ColorManagedInputColorspaceSettings.bl_rna.properties["name"]
    return frozenset(item.identifier for item in prop.enum_items)


def _load_alpha_mode(path):
    """The alpha mode images.load gives a file: premultiplied for the float formats, straight for the others."""
    return 'PREMUL' if os.path.splitext(path)[1].lower() in _PREMUL_ON_LOAD else 'STRAIGHT'


def _key(path, colorspace):
    """The key of a texture file in one color space: its absolute path, normalized for case and separators."""
    return os.path.normcase(os.path.abspath(path)), colorspace
