# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""_Textures: normal and bump maps, UVs, image texture nodes, crops and repeats."""
import bpy

from ...convert import texmaps as tx
from .sockets import (
    _EPS, _in, _out, clip_axes, CLIP_LABEL, COLOR, extension, FLOAT, mirror_scale, MISSING, per_axis, repeat_axes,
    uv_layer_name, uv_transform,
)


class _Textures:
    """Normal and bump maps, UVs and image textures: part of _Tree."""

    def normal_root(self, n, depth, normal):
        """The Normal output of a normal or bump graph's root (normal when its images are missing); normal: a
        normal to bump further, or None."""
        if isinstance(n, tx.NormalMap):
            out = self.normal_map(n, depth + (1 if n.bump is not None else 0))
            out = normal if out is None else out
            return self.bump(n.bump, depth, out) if n.bump is not None else out
        if not isinstance(n, tx.Bump):
            n = tx.Bump(n)
        return self.bump(n, depth, normal)

    def bump(self, n, depth, normal):
        """A Bump node over normal (None: the surface's); normal itself when the height map is missing."""
        height = self.graph(n.input, FLOAT, depth + 1)
        if not isinstance(height, bpy.types.NodeSocket):
            return normal
        b = self.node("ShaderNodeBump", depth)
        self.links.new(height, _in(b, "Height"))
        b.invert = n.strength < 0  # a negative bump amount inverts the height
        _in(b, "Strength").default_value = min(1.0, abs(n.strength))
        _in(b, "Distance").default_value = max(1.0, abs(n.strength))
        if normal is not None:
            self.links.new(normal, _in(b, "Normal"))
        return _out(b, "Normal")

    def normal_map(self, n, depth):
        """A Normal Map node, None when its image is missing. A normal input without an image, a constant color, is
        drawn through an RGB node: V-Ray tilts the normal by it as by an image of that color ((0.5, 0.5, 1) is flat;
        maxdrop-em3.76, em3.128). One whose image is missing and left a constant (a Mix's other side) stays None."""
        flips = n.flip_red or n.flip_green or n.swap
        color = self.graph(n.input, COLOR, depth + (3 if flips else 1))
        if color is MISSING or (not isinstance(color, bpy.types.NodeSocket) and tx.first_image(n.input) is not None):
            return None
        color = self.socket(color, COLOR, depth + (3 if flips else 1))
        nm = self.node("ShaderNodeNormalMap", depth)
        nm.space = 'TANGENT'
        channel = self.channel(n.channel, tx.first_image(n))
        if channel != 1:
            nm.uv_map = uv_layer_name(channel)
        _in(nm, "Strength").default_value = max(0.0, n.strength)
        if flips:
            sep = self.node("ShaderNodeSeparateColor", depth + 2)
            comb = self.node("ShaderNodeCombineColor", depth + 1)
            self.links.new(color, _in(sep, "Color"))
            red, green = _out(sep, "Red"), _out(sep, "Green")
            if n.swap:
                red, green = green, red
            for out, flip, target in ((red, n.flip_red, "Red"), (green, n.flip_green, "Green")):
                if flip:
                    inv = self.node("ShaderNodeMath", depth + 1)
                    inv.operation = 'SUBTRACT'
                    inv.inputs[0].default_value = 1.0
                    self.links.new(out, inv.inputs[1])
                    out = inv.outputs[0]
                self.links.new(out, _in(comb, target))
            self.links.new(_out(sep, "Blue"), _in(comb, "Blue"))
            color = _out(comb, "Color")
        self.links.new(color, _in(nm, "Color"))
        return _out(nm, "Normal")

    def channel(self, channel, img):
        """The map channel drawn for img: channel 0 (the vertex color as UVW) is no UV layer build.objects makes,
        so UV channel 1, reported."""
        if channel != 0:
            return channel
        self.builder.issue(self.label, "map channel 0 (vertex color) not imported: %s on UV channel 1"
                           % (img.name if img is not None else "a normal map"))
        return 1

    def uv(self, channel, depth):
        if channel not in self.uvs:
            if channel == 1:
                n = self.node("ShaderNodeTexCoord", depth)
            else:
                n = self.node("ShaderNodeUVMap", depth)
                n.uv_map = uv_layer_name(channel)
            self.uvs[channel] = _out(n, "UV")
        return self.uvs[channel]

    def image(self, img, space, depth):
        """The output of an Image's Texture node (made once per material), MISSING when it has no image."""
        tex = self.texture_nodes.get(id(img))
        if tex is None:
            tex = self.texture_nodes[id(img)] = self.texture_node(img, depth)
        if tex.image is None:
            return MISSING
        out = self.masked(img, tex, "Alpha" if img.alpha else "Color", depth)
        # texmaps made the image Linear Rec.709 (Non-Color where Blender lacks it) for its gamma: decode it with that
        # gamma, on a color, data or mask input alike (a data input's image is Non-Color where its pixels are taken
        # as stored). The power comes after Blender's primaries conversion: exact in the default working space
        # (Linear Rec.709) and on greys; in FLOAT the mean is taken after it, of the decoded channels.
        if not img.alpha and tx.drawn_gamma(img) is not None:
            out = self.gamma(out, img.gamma, depth)
        return self.output(img.output, out, depth) if img.output is not None else out

    def texture_node(self, img, depth):
        tex = self.node("ShaderNodeTexImage", depth)
        tex.image = self.builder.image(img, self.label)
        tex.label = img.name
        tex.extension = extension(img.mapping, img.crop)
        placed = uv_transform(img.mapping)
        double = mirror_scale(img.mapping)
        cell = per_axis(img.mapping, img.crop)
        channel = self.channel(img.mapping.channel, img)
        vector = None
        if placed is not None or double is not None or cell or channel != 1:
            vector = self.uv(channel, depth + 6)
        if placed is not None:
            vector = self.placement(vector, placed, depth + 5)
        if double is not None:
            n = self.node("ShaderNodeVectorMath", depth + 4)
            n.operation = 'MULTIPLY'
            self.links.new(vector, _in(n, "Vector"))
            _in(n, "Vector_001").default_value = double
            vector = _out(n, "Vector")
        if cell:
            vector = self.repeat_cell(vector, img.mapping, img.crop, depth + 1)
        if img.crop is not None:
            c = img.crop
            m = self.node("ShaderNodeMapping", depth + 1)
            m.vector_type = 'TEXTURE' if c.place else 'POINT'
            _in(m, "Location").default_value = (c.u, 1.0 - c.v - c.h, 0.0)
            _in(m, "Scale").default_value = (c.w, c.h, 1.0)
            self.links.new(vector, _in(m, "Vector"))
            vector = _out(m, "Vector")
        if vector is not None:
            self.links.new(vector, _in(tex, "Vector"))
        clip = clip_axes(img.mapping, img.crop)
        if clip and tex.image is not None:
            self.clip_masks[id(img)] = self.clip_mask(vector, clip, depth + 1)
        return tex

    def placement(self, vector, placed, depth):
        """vector through a POINT Mapping node of placed's (location, rotation, scale)."""
        m = self.node("ShaderNodeMapping", depth)
        m.vector_type = 'POINT'
        _in(m, "Location").default_value = placed[0]
        _in(m, "Rotation").default_value = placed[1]
        _in(m, "Scale").default_value = placed[2]
        self.links.new(vector, _in(m, "Vector"))
        return _out(m, "Vector")

    def checker(self, n, depth):
        """A Checker leaf's pattern, a float socket (texmaps.checker_value, drawn): the UV placed as a Bitmap's
        and scaled by the squares per tile (one Mapping node: k (L + R S uv) is kL + R (kS) uv), the parity of
        floor(x) + floor(y) by a Math WRAP to 0..2 (0 or 1, also below 0). Math nodes, so that the tests' node
        evaluator reads the pattern without a render."""
        k = tx.CHECKER_SQUARES
        location, rotation, scale = uv_transform(n.mapping) or ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        vector = self.placement(self.uv(n.mapping.channel, depth + 5),
                                (tuple(k * c for c in location), rotation, tuple(k * c for c in scale)), depth + 4)
        sep = self.node("ShaderNodeSeparateXYZ", depth + 3)
        self.links.new(vector, _in(sep, "Vector"))
        floors = []
        for axis in "XY":
            f = self.node("ShaderNodeMath", depth + 2)
            f.operation = 'FLOOR'
            self.links.new(_out(sep, axis), _in(f, "Value"))
            floors.append(_out(f, "Value"))
        add = self.node("ShaderNodeMath", depth + 1)
        add.operation = 'ADD'
        self.links.new(floors[0], _in(add, "Value"))
        self.links.new(floors[1], _in(add, "Value_001"))
        wrap = self.node("ShaderNodeMath", depth)
        wrap.operation = 'WRAP'  # inputs: value, max, min
        self.links.new(_out(add, "Value"), _in(wrap, "Value"))
        _in(wrap, "Value_001").default_value, _in(wrap, "Value_002").default_value = 2.0, 0.0
        return _out(wrap, "Value")

    def clip_mask(self, vector, axes, depth):
        """1 where the image coordinate lies in 0..1 on each of the axes, else 0 (Math COMPARE, |x - 0.5| <= 0.5)."""
        sep = self.node("ShaderNodeSeparateXYZ", depth + 1)
        self.links.new(vector, _in(sep, "Vector"))
        mask = None
        for axis in axes:
            n = self.node("ShaderNodeMath", depth)
            n.operation = 'COMPARE'
            self.links.new(_out(sep, "XYZ"[axis]), n.inputs[0])
            n.inputs[1].default_value = n.inputs[2].default_value = 0.5
            mask = n.outputs[0] if mask is None else self.times(mask, n.outputs[0], depth)
        return mask

    def masked(self, img, tex, name, depth):
        """The Image Texture's output name ("Color" or "Alpha"), times the image's clip mask where it has one
        (one Clip node per image and output): 0 where the CLIP extension would give transparent black."""
        out = tex.outputs[name]
        mask = self.clip_masks.get(id(img))
        if mask is None:
            return out
        key = (id(img), name)
        if key not in self.clipped:
            if name == "Color":
                n = self.node("ShaderNodeVectorMath", depth)
                n.operation = 'SCALE'
                self.links.new(out, _in(n, "Vector"))
                self.links.new(mask, _in(n, "Scale"))
                self.clipped[key] = _out(n, "Vector")
            else:
                n = self.node("ShaderNodeMath", depth)
                n.operation = 'MULTIPLY'
                self.links.new(out, n.inputs[0])
                self.links.new(mask, n.inputs[1])
                self.clipped[key] = n.outputs[0]
            n.label = CLIP_LABEL
        return self.clipped[key]

    def repeat_cell(self, vector, mapping, crop, depth):
        """The UV of the 0..1 cell (the image's, or a crop's), per axis: wrapped (tile), ping-ponged (mirror, after
        mirror_scale doubled it) or left as it is (clip). A cropped image's clipped axis goes c + K floor(c),
        K = 1 / size + 1: 0 <= c < 1 stays, any other c lands outside the image once the crop mapping scales it into
        the crop rectangle. An image without a crop or a placed one needs nothing there: the CLIP extension, or the
        TEXTURE mapping, already sends a c outside 0..1 out of the image; where the other axis repeats the clip mask
        (clip_axes) cuts it, the image coordinate outside 0..1 either way."""
        axes = repeat_axes(mapping)
        clip_out = crop is None or crop.place
        if axes == ('REPEAT', 'REPEAT'):
            frac = self.node("ShaderNodeVectorMath", depth + 1)
            frac.operation = 'FRACTION'
            self.links.new(vector, _in(frac, "Vector"))
            return _out(frac, "Vector")
        if clip_out and axes == ('CLIP', 'CLIP'):
            return vector
        sep = self.node("ShaderNodeSeparateXYZ", depth + 2)
        comb = self.node("ShaderNodeCombineXYZ", depth)
        self.links.new(vector, _in(sep, "Vector"))
        for axis, how, size in (("X", axes[0], crop and crop.w), ("Y", axes[1], crop and crop.h)):
            v = _out(sep, axis)
            if how == 'CLIP' and not clip_out:
                fl = self.node("ShaderNodeMath", depth + 1)
                fl.operation = 'FLOOR'
                self.links.new(v, fl.inputs[0])
                n = self.node("ShaderNodeMath", depth + 1)
                n.operation = 'MULTIPLY_ADD'
                self.links.new(fl.outputs[0], n.inputs[0])
                n.inputs[1].default_value = 1.0 / max(size, _EPS) + 1.0
                self.links.new(v, n.inputs[2])
                v = n.outputs[0]
            elif how != 'CLIP':
                n = self.node("ShaderNodeMath", depth + 1)
                self.links.new(v, n.inputs[0])
                if how == 'REPEAT':
                    n.operation = 'WRAP'
                    n.inputs[1].default_value, n.inputs[2].default_value = 1.0, 0.0
                else:
                    n.operation = 'PINGPONG'
                    n.inputs[1].default_value = 1.0
                v = n.outputs[0]
            self.links.new(v, _in(comb, axis))
        return _out(comb, "Vector")
