# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""_MapNodes: the nodes of the texture-map graphs (outputs, mixes, math, color corrections, blends)."""
import bpy

from ...convert import colors
from ...convert import texmaps as tx
from .sockets import (
    _as, _in, _mean, _out, BLEND_OPS, BLEND_TYPES, COLOR, FLOAT, MISSING, NON_NEGATIVE_BLENDS, SRGB_CURVE_COLUMNS,
)


class _MapNodes:
    """The nodes of the texture-map graphs: part of _Tree."""

    def output(self, o, out, depth):
        """A map's Output: level times the color plus offset (inverted: level times its inverse minus offset, as
        3ds Max renders it), then times amount."""
        if o.invert:
            out = self.invert(out, COLOR, depth)
        if o.level != 1.0 or o.offset != 0.0:
            n = self.node("ShaderNodeVectorMath", depth)
            n.operation = 'MULTIPLY_ADD'
            self.links.new(out, _in(n, "Vector"))
            _in(n, "Vector_001").default_value = (o.level,) * 3
            _in(n, "Vector_002").default_value = (-o.offset if o.invert else o.offset,) * 3
            out = _out(n, "Vector")
        if o.amount != 1.0:
            out = self.scale(out, o.amount, depth)
        return out

    def scale(self, out, factor, depth):
        n = self.node("ShaderNodeVectorMath", depth)
        n.operation = 'SCALE'
        self.links.new(out, _in(n, "Vector"))
        _in(n, "Scale").default_value = factor
        return _out(n, "Vector")

    def invert(self, v, space, depth):
        if v is MISSING:
            return MISSING
        if not isinstance(v, bpy.types.NodeSocket):
            return tuple(1.0 - c for c in v) if space == COLOR else 1.0 - v
        if space == COLOR:
            n = self.node("ShaderNodeInvert", depth)
            self.links.new(v, _in(n, "Color"))
            return _out(n, "Color")
        n = self.node("ShaderNodeMath", depth)
        n.operation = 'SUBTRACT'
        n.inputs[0].default_value = 1.0
        self.links.new(v, n.inputs[1])
        return n.outputs[0]

    def decode(self, n, space, depth):
        """A gamma-off scene's display-referred color as linear: its input in color, a constant through the sRGB
        curve, a socket through a Gamma node of 2.2 (texmaps.Decode); a mean (Decode.mean) the mean of its channels
        through the sRGB curve, a socket's in Math nodes (srgb_curve); MISSING stays."""
        mean = depth + SRGB_CURVE_COLUMNS  # mean_of's column, left of the curve's; the input one further left
        v = self.graph(n.input, COLOR, mean + 1 if n.mean else depth + 1)
        if v is MISSING:
            return v
        if isinstance(v, bpy.types.NodeSocket):
            if n.mean:
                return self.srgb_curve(self.mean_of(v, mean), depth)
            return self.gamma(v, tx.SRGB_GAMMA, depth)
        rgb = _as(v, COLOR)
        if n.mean:
            return _as(colors.srgb_to_linear(sum(rgb) / 3.0), space)
        return _as(tuple(colors.srgb_to_linear(c) for c in rgb), space)

    def srgb_curve(self, f, depth):
        """Float socket f through the sRGB curve (colors.srgb_to_linear), exact: f / 12.92 below 0.04045, else
        ((f + 0.055) / 1.055) ^ 2.4 (the two agree there within 1e-7); a FLOAT Mix by a LESS_THAN picks one."""
        def op(operation, col, *inputs):
            m = self.node("ShaderNodeMath", col)
            m.operation = operation
            for k, x in enumerate(inputs):
                if isinstance(x, bpy.types.NodeSocket):
                    self.links.new(x, m.inputs[k])
                else:
                    m.inputs[k].default_value = x
            return m.outputs[0]
        shifted = op('MULTIPLY_ADD', depth + 2, f, 1.0 / 1.055, 0.055 / 1.055)
        power = op('POWER', depth + 1, shifted, 2.4)
        linear = op('DIVIDE', depth + 1, f, 12.92)
        low = op('LESS_THAN', depth + 1, f, colors.SRGB_KNEE)
        node, a, b, result = self.mix_node(FLOAT, depth)
        self.links.new(power, a)
        self.links.new(linear, b)
        self.links.new(low, _in(node, "Factor_Float"))
        return result

    def mix_node(self, space, depth, blend='MIX'):
        """A Mix node of the space's data type: (node, A, B, Result)."""
        n = self.node("ShaderNodeMix", depth)
        n.data_type = 'RGBA' if space == COLOR else 'FLOAT'
        n.blend_type = blend
        kind = "Color" if space == COLOR else "Float"
        return n, _in(n, "A_" + kind), _in(n, "B_" + kind), _out(n, "Result_" + kind)

    def mix(self, n, space, depth):
        """A missing side gives the other one; a missing mask the mix amount. A constant side below 0: unclamped."""
        va, vb = self.graph(n.a, space, depth + 1), self.graph(n.b, space, depth + 1)
        mask = self.graph(n.mask, FLOAT, depth + 1) if n.mask is not None else MISSING  # its node even when unused
        if va is MISSING or vb is MISSING:
            return vb if va is MISSING else va
        node, a, b, result = self.mix_node(space, depth)
        self.feed(a, self.unclamped(va, space, depth + 1))
        self.feed(b, self.unclamped(vb, space, depth + 1))
        self.feed(_in(node, "Factor_Float"), n.factor if mask is MISSING else mask)
        # Only a Remap mask unclamps: a Smoothstep one's clamped Map Range (or step) never leaves 0..1.
        if isinstance(n.mask, tx.Remap) and mask is not MISSING:
            node.clamp_factor = False  # 3ds Max mixes by a Falloff's curve unclamped (measured: 1.195 renders 1.195)
        return result

    def multiply(self, n, space, depth):
        """A missing side gives the other one when that is a map, else MISSING (a slot amount times a lost map). A
        constant side below 0: unclamped."""
        va, vb = self.graph(n.a, space, depth + 1), self.graph(n.b, space, depth + 1)
        if va is MISSING or vb is MISSING:
            other = vb if va is MISSING else va
            return other if isinstance(other, bpy.types.NodeSocket) else MISSING
        if not isinstance(va, bpy.types.NodeSocket) and not isinstance(vb, bpy.types.NodeSocket):
            return tuple(x * y for x, y in zip(va, vb)) if space == COLOR else va * vb
        if space == COLOR:
            node, a, b, result = self.mix_node(space, depth, 'MULTIPLY')
            _in(node, "Factor_Float").default_value = 1.0
        else:
            node = self.node("ShaderNodeMath", depth)
            node.operation = 'MULTIPLY'
            a, b, result = node.inputs[0], node.inputs[1], node.outputs[0]
        self.feed(a, self.unclamped(va, space, depth + 1))
        self.feed(b, self.unclamped(vb, space, depth + 1))
        return result

    def arith(self, n, depth):
        """A Blend (a color socket): with a gamma both sides' magnitudes to the power 1 / gamma (a map side through a
        Vector Math ABSOLUTE and a Gamma node, a constant folded); the operation (a Mix node at factor 1, not
        clamped, A the bottom: subtract and linear burn floored at 0 by a Vector Math MAXIMUM, linear burn minus 1
        first; dodge, burn and exclusion as Vector Math nodes, Corona's unclamped formulas: _dodge_burn,
        multiply_add; a constant below 0 on a Mix input: unclamped); then a Vector Math ABSOLUTE (but for
        NON_NEGATIVE_BLENDS) and a Gamma node of gamma. A missing side gives the other one when that is a map, else
        MISSING, as for Multiply."""
        va, vb = self.graph(n.a, COLOR, depth + 2), self.graph(n.b, COLOR, depth + 2)
        if va is MISSING or vb is MISSING:
            other = vb if va is MISSING else va
            return other if isinstance(other, bpy.types.NodeSocket) else MISSING
        if not isinstance(va, bpy.types.NodeSocket) and not isinstance(vb, bpy.types.NodeSocket):
            return tx.blend_value(n.op, _as(va, COLOR), _as(vb, COLOR), n.gamma)
        sides = []
        for v in (va, vb):
            if n.gamma != 1.0:  # Corona takes a negative layer's magnitude (renderMap, maxdrop-em3.161)
                if isinstance(v, bpy.types.NodeSocket):
                    v = self.gamma(self.vector_math('ABSOLUTE', v, None, depth + 2), 1.0 / n.gamma, depth + 1)
                else:
                    v = tuple(abs(c) ** (1.0 / n.gamma) for c in _as(v, COLOR))
            sides.append(v)
        if n.op == tx.BLEND_DODGE:
            out = self._dodge_burn(sides[0], self.multiply_add(sides[1], -1.0, 1.0, depth), True, depth)
        elif n.op == tx.BLEND_BURN:
            out = self._dodge_burn(self.multiply_add(sides[0], -1.0, 1.0, depth), sides[1], False, depth)
        elif n.op == tx.BLEND_EXCLUSION:  # a + b (1 - 2a)
            out = self.multiply_add(sides[1], self.multiply_add(sides[0], -2.0, 1.0, depth), sides[0], depth)
        else:
            node, a, b, out = self.mix_node(COLOR, depth, BLEND_OPS[n.op])
            _in(node, "Factor_Float").default_value = 1.0
            node.clamp_result = False
            if n.op == tx.BLEND_HARD_LIGHT:  # overlay with the layers' roles swapped
                sides.reverse()
            for socket, v in zip((a, b), sides):
                self.feed(socket, self.unclamped(v, COLOR, depth + 1))
        if n.op == tx.BLEND_LINEAR_BURN:
            out = self.vector_math('ADD', out, (-1.0, -1.0, -1.0), depth)
        if n.op in (tx.BLEND_SUBTRACT, tx.BLEND_LINEAR_BURN):
            out = self.vector_math('MAXIMUM', out, (0.0, 0.0, 0.0), depth)
        if n.gamma == 1.0:
            return out
        if n.op not in NON_NEGATIVE_BLENDS:  # Corona raises the magnitude of a negative result
            out = self.vector_math('ABSOLUTE', out, None, depth)
        return self.gamma(out, n.gamma, depth)

    def _dodge_burn(self, x, d, dodge, depth):
        """K = max(0, nz - x / d), nz = ceil(min(|d|, 1)) (1 where d is not 0): Vector Math's DIVIDE gives 0 where d
        is 0, so K is max(0, 1 - x / d), and 0 at d = 0. Burn of a, b is K(1 - a, b) (0 at b = 0, Corona's); dodge
        is 1 - K(a, 1 - b): min(1, a / (1 - b)), 1 at b = 1 (black under white too, where Blender's DODGE leaves
        0)."""
        if isinstance(d, bpy.types.NodeSocket):
            nz = self.vector_math('ABSOLUTE', d, None, depth)
            nz = self.vector_math('CEIL', self.vector_math('MINIMUM', nz, (1.0, 1.0, 1.0), depth), None, depth)
        else:
            nz = tuple(1.0 if c != 0.0 else 0.0 for c in _as(d, COLOR))
        q = self.node("ShaderNodeVectorMath", depth)
        q.operation = 'DIVIDE'
        self.feed(_in(q, "Vector"), x)
        self.feed(_in(q, "Vector_001"), d)
        k = self.node("ShaderNodeVectorMath", depth)
        k.operation = 'SUBTRACT'
        self.feed(_in(k, "Vector"), nz)
        self.links.new(_out(q, "Vector"), _in(k, "Vector_001"))
        k = self.vector_math('MAXIMUM', _out(k, "Vector"), (0.0, 0.0, 0.0), depth)
        return self.multiply_add(k, -1.0, 1.0, depth) if dodge else k

    def unclamped(self, value, space, depth):
        """value for a Mix node's input: in color a constant with a channel below 0 as a Combine XYZ node's output (a
        color input clamps its own value at 0 in Blender 4.2 to 5.2, maxdrop-6n0.6.26), else value itself."""
        if space == COLOR and not isinstance(value, bpy.types.NodeSocket) and min(_as(value, COLOR)) < 0.0:
            return self.combine_xyz(value, depth)
        return value

    def combine_xyz(self, value, depth):
        """A constant color as a Combine XYZ node's output, which keeps a channel below 0."""
        c = self.node("ShaderNodeCombineXYZ", depth)
        for socket, v in zip(c.inputs, _as(value, COLOR)):
            socket.default_value = v
        return c.outputs[0]

    def multiply_add(self, v, scale, add, depth):
        """v x scale + add per channel (a Vector Math MULTIPLY_ADD); each a socket or a constant (a float: on every
        channel). Folded when none is a socket."""
        if not any(isinstance(x, bpy.types.NodeSocket) for x in (v, scale, add)):
            return tuple(x * y + z for x, y, z in zip(_as(v, COLOR), _as(scale, COLOR), _as(add, COLOR)))
        vm = self.node("ShaderNodeVectorMath", depth)
        vm.operation = 'MULTIPLY_ADD'
        for name, value in (("Vector", v), ("Vector_001", scale), ("Vector_002", add)):
            self.feed(_in(vm, name), value)
        return _out(vm, "Vector")

    def vector_math(self, operation, socket, value, depth):
        """A Vector Math node of operation over socket and the constant value (None: a one-input operation)."""
        vm = self.node("ShaderNodeVectorMath", depth)
        vm.operation = operation
        self.links.new(socket, _in(vm, "Vector"))
        if value is not None:
            _in(vm, "Vector_001").default_value = value
        return _out(vm, "Vector")

    def gamma(self, socket, value, depth):
        """socket raised to value (a Gamma node; a negative channel stays as it is)."""
        g = self.node("ShaderNodeGamma", depth)
        self.links.new(socket, _in(g, "Color"))
        _in(g, "Gamma").default_value = value
        return _out(g, "Color")

    def color_correct(self, n, space, depth):
        steps = [tuple(n.rewire) != tx.REWIRE_NONE, n.hue % 1.0 != 0.0, n.saturation != 1.0,
                 n.brightness != 0.0 or n.contrast != 0.0, n.gain != 1.0, n.gamma != 1.0 or n.magnitude]
        d = depth + sum(steps) + (n.gamma != 1.0 and n.magnitude) - 1  # the first step's column; the input further left
        v = self.graph(n.input, COLOR, d + 1)
        if v is MISSING:
            return MISSING
        if not any(steps):
            return v if space == COLOR or isinstance(v, bpy.types.NodeSocket) else _mean(v)
        v = self.socket(v, COLOR, d + 1)
        if steps[0]:
            v, d = self.rewire(v, tuple(n.rewire), d), d - 1
        steps = steps[1:]
        if steps[0]:
            h = self.node("ShaderNodeHueSaturation", d)
            _in(h, "Hue").default_value = (0.5 + n.hue) % 1.0
            self.links.new(v, _in(h, "Color"))
            v, d = _out(h, "Color"), d - 1
        steps = steps[1:]
        if steps[0]:
            v, d = self.saturate(v, max(0.0, n.saturation), d), d - 1
        if steps[1]:
            bc = self.node("ShaderNodeBrightContrast", d)
            _in(bc, "Bright").default_value = n.brightness
            _in(bc, "Contrast").default_value = n.contrast
            self.links.new(v, _in(bc, "Color"))
            v, d = _out(bc, "Color"), d - 1
        if steps[2]:
            v, d = self.scale(v, n.gain, d), d - 1
        if steps[3] and n.magnitude:  # Corona raises a negative channel's magnitude (renderMap, maxdrop-6n0.6.40)
            v, d = self.vector_math('ABSOLUTE', v, None, d), d - 1
        if steps[3] and n.gamma != 1.0:
            g = self.node("ShaderNodeGamma", d)
            _in(g, "Gamma").default_value = 1.0 / n.gamma
            self.links.new(v, _in(g, "Color"))
            v = _out(g, "Color")
        return v

    def saturate(self, v, s, depth):
        """Color socket v with its saturation scaled by s as 3ds Max's Color Correction does, in HSL: each channel
        lerp(L, c, s), L = (max + min) / 2 (V-Ray 5.2 renders, maxdrop-6n0.6.18: -50 % over (0.784, 0.392, 0.196)
        gives (0.637, 0.441, 0.343); the Hue/Saturation/Value node's HSV keeps the max, 0.784 / 0.588 / 0.490).
        Above 0 % (s > 1) a channel below 0 is 0, one above 1 kept (maxdrop-6n0.6.38: +100 % over (0.784, 0.392,
        0.196) gives 1.078 0.294 0): a Vector Math MAXIMUM of 0 after the lerp; up to 0 % no clamp (not measured;
        channels in 0..1 stay in 0..1 there)."""
        sep = self.node("ShaderNodeSeparateColor", depth)
        self.links.new(v, _in(sep, "Color"))

        def math(operation, a, b):
            m = self.node("ShaderNodeMath", depth)
            m.operation = operation
            for k, x in enumerate((a, b)):
                if isinstance(x, bpy.types.NodeSocket):
                    self.links.new(x, m.inputs[k])
                else:
                    m.inputs[k].default_value = x
            return m.outputs[0]
        r, g, b = (_out(sep, c) for c in ("Red", "Green", "Blue"))
        top = math('MAXIMUM', math('MAXIMUM', r, g), b)
        low = math('MINIMUM', math('MINIMUM', r, g), b)
        rest = math('MULTIPLY', math('ADD', top, low), 0.5 * (1.0 - s))
        vm = self.node("ShaderNodeVectorMath", depth)
        vm.operation = 'MULTIPLY_ADD'
        self.links.new(v, _in(vm, "Vector"))
        _in(vm, "Vector_001").default_value = (s, s, s)
        self.links.new(rest, _in(vm, "Vector_002"))
        if s > 1.0:
            return self.vector_math('MAXIMUM', _out(vm, "Vector"), (0.0, 0.0, 0.0), depth)
        return _out(vm, "Vector")

    def rewire(self, v, channels, depth):
        """A Color Correction's rewiring of color socket v: Invert, the mean of the channels, or Separate /
        Combine Color with each output from its source (texmaps' codes; an alpha source was made one or zero)."""
        if channels == tx.REWIRE_INVERT:
            return self.invert(v, COLOR, depth)
        mean = None

        def mono():
            nonlocal mean
            if mean is None:
                mean = self.mean_of(v, depth)
            return mean
        if channels == tx.REWIRE_MONO:
            return mono()
        sep = self.node("ShaderNodeSeparateColor", depth)
        comb = self.node("ShaderNodeCombineColor", depth)
        self.links.new(v, _in(sep, "Color"))
        names = ("Red", "Green", "Blue")
        for target, c in zip(names, channels):
            socket = _in(comb, target)
            if c in (0, 1, 2):
                self.links.new(_out(sep, names[c]), socket)
            elif c in (4, 5, 6):
                inv = self.node("ShaderNodeMath", depth)
                inv.operation = 'SUBTRACT'
                inv.inputs[0].default_value = 1.0
                self.links.new(_out(sep, names[c - 4]), inv.inputs[1])
                self.links.new(inv.outputs[0], socket)
            elif c == tx.RW_MONO:
                self.links.new(mono(), socket)
            else:
                socket.default_value = 1.0 if c == tx.RW_ONE else 0.0
        return _out(comb, "Color")

    def facing(self, n, depth):
        """A Falloff's ratio (a float socket): Layer Weight Facing at blend 0.5 is 1 - |N.I|; the Fresnel node at
        the IOR; towards / away (1 - N.I) / 2 from the Geometry node."""
        if n.mode == tx.FRESNEL:
            f = self.node("ShaderNodeFresnel", depth)
            _in(f, "IOR").default_value = n.ior
            return _out(f, "Fac")
        if n.mode == tx.PERPENDICULAR:
            lw = self.node("ShaderNodeLayerWeight", depth)
            _in(lw, "Blend").default_value = 0.5
            return _out(lw, "Facing")
        geo = self.node("ShaderNodeNewGeometry", depth + 2)
        dot = self.node("ShaderNodeVectorMath", depth + 1)
        dot.operation = 'DOT_PRODUCT'
        self.links.new(_out(geo, "Normal"), _in(dot, "Vector"))
        self.links.new(_out(geo, "Incoming"), _in(dot, "Vector_001"))
        m = self.node("ShaderNodeMath", depth)
        m.operation = 'MULTIPLY_ADD'
        self.links.new(_out(dot, "Value"), m.inputs[0])
        m.inputs[1].default_value, m.inputs[2].default_value = -0.5, 0.5
        return m.outputs[0]

    def remap(self, n, depth):
        """A float through a polyline (a float socket): a Float Curve whose points are VECTOR (straight between
        them), not clipped (3ds Max's curve can leave 0..1), flat past the ends; MISSING without its input."""
        v = self.graph(n.input, FLOAT, depth + 1)
        if v is MISSING:
            return MISSING
        fc = self.node("ShaderNodeFloatCurve", depth)
        mapping = fc.mapping
        mapping.use_clip = False
        mapping.extend = 'HORIZONTAL'
        points = mapping.curves[0].points  # a new Float Curve has two points: moved to the first two
        for p, (x, y) in zip(points, n.points[:2]):
            p.location = (x, y)
        for x, y in n.points[2:]:
            points.new(x, y)
        for p in points:
            p.handle_type = 'VECTOR'
        mapping.update()
        _in(fc, "Factor").default_value = 1.0
        self.feed(_in(fc, "Value"), v)
        return _out(fc, "Value")

    def smoothstep(self, n, depth):
        """Mix's Use Curve on a float (a float socket): Map Range SMOOTHSTEP from lower..upper to 0..1, or a step
        when lower >= upper, 1 from lower on (1 - LESS_THAN: 3ds Max gives 1 at lower itself, an 8-bit mask can hit
        it); MISSING without its input."""
        v = self.graph(n.input, FLOAT, depth + 2)
        if v is MISSING:
            return MISSING
        if n.lower >= n.upper:
            less = self.node("ShaderNodeMath", depth + 1)
            less.operation = 'LESS_THAN'
            self.feed(less.inputs[0], v)
            less.inputs[1].default_value = n.lower
            step = self.node("ShaderNodeMath", depth)
            step.operation = 'SUBTRACT'
            step.inputs[0].default_value = 1.0
            self.links.new(less.outputs[0], step.inputs[1])
            return step.outputs[0]
        mr = self.node("ShaderNodeMapRange", depth)
        mr.data_type = 'FLOAT'
        mr.interpolation_type = 'SMOOTHSTEP'
        mr.clamp = True
        self.feed(_in(mr, "Value"), v)
        _in(mr, "From Min").default_value, _in(mr, "From Max").default_value = n.lower, n.upper
        _in(mr, "To Min").default_value, _in(mr, "To Max").default_value = 0.0, 1.0
        return _out(mr, "Result")

    def adjust(self, n, depth):
        """A wrapper's Output over its input (a color socket), as an image's."""
        v = self.graph(n.input, COLOR, depth + 1)
        if v is MISSING:
            return MISSING
        return self.output(n.output, self.socket(v, COLOR, depth + 1), depth)

    def tint(self, n, depth):
        """RGB Tint: R x red + G x green + B x blue (a color socket)."""
        v = self.graph(n.input, COLOR, depth + 3)
        if v is MISSING:
            return MISSING
        sep = self.node("ShaderNodeSeparateColor", depth + 2)
        self.links.new(self.socket(v, COLOR, depth + 3), _in(sep, "Color"))
        out = None
        for channel, color in (("Red", n.red), ("Green", n.green), ("Blue", n.blue)):
            sc = self.node("ShaderNodeVectorMath", depth + 1)
            sc.operation = 'SCALE'
            _in(sc, "Vector").default_value = tuple(color[:3])
            self.links.new(_out(sep, channel), _in(sc, "Scale"))
            if out is None:
                out = _out(sc, "Vector")
                continue
            add = self.node("ShaderNodeVectorMath", depth)
            add.operation = 'ADD'
            self.links.new(out, _in(add, "Vector"))
            self.links.new(_out(sc, "Vector"), _in(add, "Vector_001"))
            out = _out(add, "Vector")
        return out

    def blend(self, mode, below, top, depth):
        """A Composite layer blended over below at factor 1 (a color socket); the opacity Mix comes after."""
        node, a, b, out = self.mix_node(COLOR, depth, BLEND_TYPES[mode])
        _in(node, "Factor_Float").default_value = 0.5 if mode == tx.AVERAGE else 1.0
        node.clamp_result = mode == tx.LINEAR_DODGE
        if mode == tx.HARD_LIGHT:  # overlay with the layers' roles swapped
            below, top = top, below
        below = self.unclamped(below, COLOR, depth + 1)  # one Combine XYZ for both Mix nodes of spotlight blend
        self.feed(a, below)
        self.feed(b, self.unclamped(top, COLOR, depth + 1))
        if mode == tx.SPOTLIGHT:
            return self.scale(out, 2.0, depth)
        if mode == tx.SPOTLIGHT_BLEND:  # below + below x top
            add, a2, b2, out2 = self.mix_node(COLOR, depth, 'ADD')
            _in(add, "Factor_Float").default_value = 1.0
            self.feed(a2, below)
            self.links.new(out, b2)
            return out2
        return out

    def composite(self, n, space, depth):
        """Each layer over the ones below: its blend at factor 1, then a Mix by opacity x mask (times an image's
        alpha), clamped for a blend other than normal (3ds Max's result stays within 0..1). The bottom layer is over
        black. A layer whose image is missing is left out, a missing mask leaves the opacity. With a blend mode the
        layers are drawn in color."""
        work = COLOR if any(layer.blend != tx.NORMAL_BLEND for layer in n.layers) else space
        result = MISSING
        for layer in n.layers:
            v = self.graph(layer.node, work, depth + 2)
            mask = self.weight(layer.mask, depth + 2)  # its node even when the layer is missing
            if v is MISSING:
                continue
            if result is MISSING and layer.opacity >= 1.0 and mask is MISSING:
                result = v
                continue
            if result is not MISSING:  # a constant below 0 on one Combine XYZ, for the blend and the opacity Mix
                result = self.unclamped(result, work, depth + 1)
            blended = result is not MISSING and layer.blend != tx.NORMAL_BLEND
            top = self.blend(layer.blend, result, v, depth + 1) if blended else v
            node, a, b, out = self.mix_node(work, depth)
            node.clamp_result = blended
            self.feed(a, _as(0.0, work) if result is MISSING else result)
            self.feed(b, self.unclamped(top, work, depth + 1))
            factor = layer.opacity
            if isinstance(mask, bpy.types.NodeSocket):
                factor = self.times(mask, factor, depth + 1)
            elif mask is not MISSING:
                factor *= _mean(mask)
            img = layer.node.input if isinstance(layer.node, tx.Decode) and layer.node.mean else layer.node  # its alpha
            tex = self.texture_nodes.get(id(img)) if isinstance(img, tx.Image) and not img.alpha else None
            if tex is not None and result is not MISSING:
                factor = self.times(self.masked(img, tex, "Alpha", depth + 1), factor, depth + 1)
            self.feed(_in(node, "Factor_Float"), factor)
            result = out
        if work == COLOR and space != COLOR and not isinstance(result, bpy.types.NodeSocket) and result is not MISSING:
            return _mean(result)  # a lone constant layer, drawn in color for the blend modes, in a float input
        return result

    def weight(self, n, depth):
        """A Composite mask as a float (an image through the mean of its channels, as every float graph: graph());
        MISSING without one."""
        if n is None:
            return MISSING
        return self.graph(n, FLOAT, depth + 1)

    def times(self, socket, factor, depth):
        """socket x factor (a float socket or constant) as a Math node's output."""
        mul = self.node("ShaderNodeMath", depth)
        mul.operation = 'MULTIPLY'
        self.links.new(socket, mul.inputs[0])
        self.feed(mul.inputs[1], factor)
        return mul.outputs[0]
