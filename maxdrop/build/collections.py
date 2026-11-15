# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The collections of an import: one named after the file, and below it one per 3ds Max layer, nested like the
layers.

    cols = make(desc, parent, "scene")  # parent: the collection the file's collection goes into
    built = objects.build(desc, cols.root, cols, view_layer)
    finish(cols, view_layer)            # the layers' visibility, once the objects are in

cols.of(node) is the collection of a node's object: its layer's, or the file's collection when the node has no
layer. A layer hidden in 3ds Max is excluded in the view layer (LayerCollection.exclude), which also leaves out
the layers below it, as 3ds Max hides them; a layer that does not render gets hide_render, a frozen one
hide_select. finish() comes after the objects are linked: an object of an excluded collection is not in the view
layer, and hiding it there (Object.hide_set) would fail.
"""
import bpy


class Collections:
    """root the file's collection, layers {layer object index: Collection}, hidden the layers to exclude."""
    __slots__ = ("root", "layers", "hidden")

    def __init__(self, root):
        self.root, self.layers, self.hidden = root, {}, []

    def of(self, node):
        return self.layers.get(node.layer, self.root) if node.layer is not None else self.root


def make(desc, parent, name):
    """The file's collection, linked to parent, with a child collection per layer of desc (parents first)."""
    root = bpy.data.collections.new(name)
    parent.children.link(root)
    cols = Collections(root)
    for layer in desc.layers:
        col = bpy.data.collections.new(layer.name)
        cols.layers.get(layer.parent, root).children.link(col)
        cols.layers[layer.index] = col
        col.hide_render = not layer.renderable
        col.hide_select = layer.frozen
        if layer.hidden:
            cols.hidden.append(col)
    return cols


def layer_collection(view_layer, collection):
    """The LayerCollection of collection in view_layer, None when the view layer does not hold it."""
    stack = [view_layer.layer_collection]
    while stack:
        lc = stack.pop()
        if lc.collection == collection:
            return lc
        stack.extend(lc.children)
    return None


def finish(cols, view_layer):
    """Exclude the hidden layers' collections from view_layer."""
    for col in cols.hidden:
        lc = layer_collection(view_layer, col)
        if lc is not None:
            lc.exclude = True
