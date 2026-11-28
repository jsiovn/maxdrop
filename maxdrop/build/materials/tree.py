# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""_Tree: the node tree of one material (layout, the Principled inputs, build, fill, layers)."""
import bpy

from ... import compat
from ...convert import texmaps as tx
from ...convert import materials as cm
from .sockets import (
    _as, _default, _in, _mean, _out, COAT_WEIGHT_LABEL, COLOR, FLOAT, MAX_LAYER_DEPTH, MISSING, VOLUME_BOUNCES,
    VOLUME_VIEWPORT_ALPHA, X_STEP, Y_STEP,
)
from .surface import _Surface
from .textures import _Textures
from .map_nodes import _MapNodes


def _volume_only(ir):
    """Whether a MaterialIR renders no surface but its medium: alpha 0 without a map, no layers (CoronaVolumeMtl)."""
    return (ir.medium is not None and _mean(ir.alpha.value) == 0.0 and "alpha" not in ir.textures
            and not ir.layers)


class _Tree(_Surface, _Textures, _MapNodes):
    """The node tree of one material while it is built."""

    def __init__(self, builder, material, ir):
        self.builder, self.material, self.ir = builder, material, ir
        self.label = "material %s" % (material.name,)
        self.skipped = set()  # the Principled inputs the IR needs that this Blender lacks
        tree = compat.node_tree(material)
        self.nodes, self.links = tree.nodes, tree.links
        self.nodes.clear()
        self.memo, self.uvs, self.texture_nodes = {}, {}, {}
        self.clip_masks, self.clipped = {}, {}  # id(img) -> mask socket; (id(img), output) -> masked output
        self.columns, self.row = {}, 0.0
        self.bsdf = self.nodes.new("ShaderNodeBsdfPrincipled")
        self.bsdf.location = (0.0, 0.0)
        out = self.nodes.new("ShaderNodeOutputMaterial")
        out.location = (X_STEP, 0.0)
        self.links.new(_out(self.bsdf, "BSDF"), _in(out, "Surface"))

    # nodes and layout

    def node(self, kind, depth):
        """A new node at its column (depth to the left of the BSDF), below the nodes already there."""
        n = self.nodes.new(kind)
        y = min(self.row, self.columns.get(depth, self.row))
        n.location = (-X_STEP * (depth + 1), y)
        self.columns[depth] = y - Y_STEP
        return n

    def start_row(self):
        self.row = min(self.columns.values(), default=0.0)

    def feed(self, socket, value):
        """Link a node output into socket, or set a constant on it."""
        if isinstance(value, bpy.types.NodeSocket):
            self.links.new(value, socket)
        else:
            _default(socket, value)

    def socket(self, value, space, depth):
        """A node output for a value: the value itself when it is one, else an RGB or Value node holding it (a color
        with a channel below 0 a Combine XYZ node: unclamped)."""
        if isinstance(value, bpy.types.NodeSocket):
            return value
        held = self.unclamped(value, space, depth)
        if held is not value:
            return held
        if space == COLOR:
            n = self.node("ShaderNodeRGB", depth)
            n.outputs[0].default_value = _as(value, COLOR) + (1.0,)
        else:
            n = self.node("ShaderNodeValue", depth)
            n.outputs[0].default_value = _mean(value)
        return n.outputs[0]

    # the Principled inputs

    def bsdf_input(self, name, needed=True):
        """The Principled input of that name; None (counted when needed) on a Blender without it."""
        s = self.bsdf.inputs.get(name)
        if s is None and needed:
            self.skipped.add(name)
        return s

    def value(self, name, value, needed=True):
        s = self.bsdf_input(name, needed)
        if s is not None:
            _default(s, value)

    def color_input(self, name, inp, graph):
        s = self.bsdf_input(name)
        if s is None:
            return
        self.start_row()
        v = self.graph(graph.root, COLOR, 0) if graph is not None else MISSING
        self.feed(s, inp.value if v is MISSING else v)

    def float_input(self, name, inp, graph, scale=1.0):
        """A float input; a color graph on it goes through the mean of its channels, times scale. True when a
        node drives it."""
        s = self.bsdf_input(name)
        if s is None:
            return False
        v = self.float_value(inp, graph, scale)
        self.feed(s, v)
        return isinstance(v, bpy.types.NodeSocket)

    def float_value(self, inp, graph, scale=1.0):
        """A float input's value times scale: a node output when a node drives it, else a float."""
        self.start_row()
        color = graph is not None and graph.kind == tx.COLOR
        v = MISSING if graph is None else (
            self.graph(graph.root, COLOR, 1) if color else self.graph(graph.root, FLOAT, 0))
        if not isinstance(v, bpy.types.NodeSocket):
            return _mean(inp.value if v is MISSING else v) * scale
        if color:
            return self.mean_of(v, 0, scale / 3.0)
        if scale != 1.0:
            return self.times(v, scale, 0)
        return v

    def build(self):
        """Fill the material from its IR: its Principled BSDF, then each layer (MaterialIR.layers, bottom first,
        their own layers within) as a Principled BSDF of its own over what is below, by a Mix Shader whose factor is
        the layer's weight (its amount, times its mask graph), or for an added layer (Layer.mode ADD) by an Add Shader
        over the layer scaled by its weight."""
        ir = self.ir
        alphas = []
        top = self.layered(self.bsdf, ir, alphas, 0)
        out = next(n for n in self.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
        surface = self.links.new(top, _in(out, "Surface"))
        m = self.material
        linked = ir.medium is not None and self.volume(ir.medium, out)
        volume_only = linked and _volume_only(ir)
        if volume_only:  # a volume boundary, no surface (see Medium above)
            self.links.remove(surface)
        elif any(linked for linked, _v in alphas):
            m.surface_render_method = 'DITHERED'
        elif any(v is not None and v < 1.0 for _l, v in alphas):
            m.surface_render_method = 'BLENDED'
        m.diffuse_color = _as(ir.base_color.value, COLOR) + (VOLUME_VIEWPORT_ALPHA if volume_only else 1.0,)
        m.metallic = min(1.0, max(0.0, _mean(ir.metallic.value)))
        m.roughness = min(1.0, max(0.0, _mean(ir.roughness.value)))
        if linked and max(ir.medium.scattering) > 0.0 and not ir.medium.single:
            self.builder.issue(self.label, VOLUME_BOUNCES)

    def volume(self, medium, out):
        """A convert.materials.Medium on out's Volume socket (see Medium above); nothing for an empty one. Whether
        it linked the socket."""
        shaders = []
        y = min(self.columns.values(), default=0.0) - Y_STEP
        parts = (("ShaderNodeVolumeScatter", medium.scattering, False), ("ShaderNodeVolumeAbsorption",
                                                                         medium.absorption, True))
        for kind, coefficients, complement in parts:
            density = max(coefficients)
            if density <= 0.0:
                continue
            n = self.nodes.new(kind)
            share = tuple(c / density for c in coefficients)
            _in(n, "Color").default_value = tuple(1.0 - c if complement else c for c in share) + (1.0,)
            _in(n, "Density").default_value = density
            if not complement:
                _in(n, "Anisotropy").default_value = medium.anisotropy
            shaders.append(n)
        strength = max(medium.emission)
        if strength > 0.0:
            n = self.nodes.new("ShaderNodeEmission")
            _in(n, "Color").default_value = tuple(c / strength for c in medium.emission) + (1.0,)
            _in(n, "Strength").default_value = strength
            shaders.append(n)
        if not shaders:
            return False
        for i, n in enumerate(shaders):
            n.location = (0.0, y - i * Y_STEP)
        top = shaders[0].outputs[0]
        for n in shaders[1:]:
            add = self.nodes.new("ShaderNodeAddShader")
            add.location = (X_STEP * 0.5, n.location[1])
            self.links.new(top, add.inputs[0])
            self.links.new(n.outputs[0], add.inputs[1])
            top = add.outputs[0]
        self.links.new(top, _in(out, "Volume"))
        return True

    def layered(self, bsdf, ir, alphas, level):
        """Fill bsdf from ir and mix (or add) ir's layers over it: the shader output on top. alphas gets (alpha linked,
        alpha value or None) of every IR filled. An added layer is a Mix Shader (COAT_WEIGHT_LABEL) by its weight from
        nothing (its first shader unlinked: no closure) to the layer, into an Add Shader over what is below; a back
        layer (Layer.mode BACK) a Mix Shader by Geometry > Backfacing from what is below to the layer."""
        below, alpha = self.fill(bsdf, ir)
        alphas.append(alpha)
        if not ir.layers or level >= MAX_LAYER_DEPTH:
            return below
        for layer in ir.layers:
            self.start_row()
            node = self.nodes.new("ShaderNodeBsdfPrincipled")
            node.location = (0.0, self.row - Y_STEP)
            self.columns[-1] = self.row - 2 * Y_STEP
            sub = self.layered(node, layer.ir, alphas, level + 1)
            mix = self.nodes.new("ShaderNodeMixShader")
            mix.location = (X_STEP * 0.5, node.location[1])
            factor = MISSING
            if layer.graph is not None and layer.mode != cm.BACK:
                self.start_row()
                factor = self.graph(layer.graph.root, FLOAT, 1)
            if layer.mode == cm.BACK:  # shown on back faces instead of what is below
                geometry = self.nodes.new("ShaderNodeNewGeometry")
                geometry.location = (X_STEP * 0.25, node.location[1] + Y_STEP * 0.5)
                self.links.new(_out(geometry, "Backfacing"), mix.inputs[0])
            elif isinstance(factor, bpy.types.NodeSocket):
                if layer.amount != 1.0:
                    factor = self.times(factor, layer.amount, 0)
                    factor.node.use_clamp = True
                self.links.new(factor, mix.inputs[0])
            else:
                if factor is MISSING and layer.graph is not None and layer.fallback is not None:
                    weight = layer.fallback  # its map lost (no file): the blend color's weight, as a slot's swatch
                else:
                    weight = layer.amount * (1.0 if factor is MISSING else _mean(factor))
                mix.inputs[0].default_value = min(1.0, max(0.0, weight))
            self.links.new(sub, mix.inputs[2])
            if layer.mode == cm.ADD:
                mix.label = COAT_WEIGHT_LABEL
                add = self.nodes.new("ShaderNodeAddShader")
                add.location = (X_STEP, node.location[1])
                self.links.new(below, add.inputs[0])
                self.links.new(mix.outputs[0], add.inputs[1])
                below = add.outputs[0]
            else:
                self.links.new(below, mix.inputs[1])
                below = mix.outputs[0]
        return below

    def fill(self, bsdf, ir):
        """Set a Principled BSDF's inputs from a MaterialIR: (the shader output, (alpha linked, the constant alpha
        or None)); the output is bsdf's, or a Mix Shader's over a twin of it (reflection_weight), a Translucent BSDF
        mixed in by the translucency (translucent)."""
        self.bsdf, tex = bsdf, ir.textures
        self.color_input("Base Color", ir.base_color, tex.get("base_color"))
        self.float_input("Metallic", ir.metallic, tex.get("metallic"))
        self.float_input("Roughness", ir.roughness, tex.get("roughness"))
        self.value("IOR", ir.ior)
        self.float_input("Transmission Weight", ir.transmission, tex.get("transmission"))
        weight = self.specular(ir)
        self.color_input("Emission Color", ir.emission_color, tex.get("emission_color"))
        self.value("Emission Strength", ir.emission_strength)
        alpha_map = self.float_input("Alpha", ir.alpha, tex.get("alpha"))
        out = None
        for key in ("normal", "bump"):  # a bump on top of the normal map, when both are there
            if key in tex:
                self.start_row()
                out = self.normal_root(tex[key].root, 0, out)
        normal = self.bsdf_input("Normal") if out is not None else None
        if normal is not None:
            self.links.new(out, normal)
        self.value("Coat Weight", ir.coat_weight)
        self.value("Coat Roughness", ir.coat_roughness)
        self.value("Coat IOR", ir.coat_ior)
        self.value("Coat Tint", ir.coat_color)
        self.value("Subsurface Weight", ir.subsurface_weight)
        if ir.subsurface_weight > 0:
            self.value("Subsurface Radius", ir.subsurface_color)
            self.value("Subsurface Scale", ir.subsurface_radius)
        if ir.sheen_weight > 0:
            self.value("Sheen Weight", ir.sheen_weight)
            self.value("Sheen Tint", ir.sheen_color)
            self.value("Sheen Roughness", ir.sheen_roughness)
        if ir.thin_walled:
            self.value("Thin Wall", True)
        alpha = self.bsdf_input("Alpha", needed=False)
        top = _out(bsdf, "BSDF") if weight is None else self.reflection_weight(bsdf, *weight, color=ir.mirror_color)
        top = self.translucent(top, ir, out)
        return top, (alpha_map, (None if alpha is None or alpha_map else alpha.default_value))

    def graph(self, node, space, depth):
        """The output (a node socket) or constant of an IR node in a space; in FLOAT a color socket through the mean
        of its channels (see Data maps above)."""
        key = (id(node), space)
        if key not in self.memo:
            v = self._build(node, space, depth)
            if space == FLOAT and isinstance(v, bpy.types.NodeSocket) and v.type in ('RGBA', 'VECTOR'):
                v = self.mean_of(v, depth)
            self.memo[key] = v
        return self.memo[key]

    def mean_of(self, v, depth, weight=1.0 / 3.0):
        """Color socket v as a float: a DOT_PRODUCT by (weight, weight, weight), the mean for 1/3."""
        dot = self.node("ShaderNodeVectorMath", depth)
        dot.operation = 'DOT_PRODUCT'
        self.links.new(v, _in(dot, "Vector"))
        _in(dot, "Vector_001").default_value = (weight,) * 3
        return _out(dot, "Value")

    def _build(self, n, space, depth):
        if isinstance(n, tx.Constant):
            return _as(n.value, space)
        if isinstance(n, tx.Image):
            return self.image(n, space, depth)
        if isinstance(n, tx.Invert):
            return self.invert(self.graph(n.input, space, depth + 1), space, depth)
        if isinstance(n, tx.Decode):
            return self.decode(n, space, depth)
        if isinstance(n, tx.Mix):
            return self.mix(n, space, depth)
        if isinstance(n, tx.Multiply):
            return self.multiply(n, space, depth)
        if isinstance(n, tx.Blend):
            return self.arith(n, depth)
        if isinstance(n, tx.ColorCorrect):
            return self.color_correct(n, space, depth)
        if isinstance(n, tx.Composite):
            return self.composite(n, space, depth)
        if isinstance(n, tx.Facing):
            return self.facing(n, depth)
        if isinstance(n, tx.Checker):
            return self.checker(n, depth)
        if isinstance(n, tx.Noise):
            return self.noise(n, depth)
        if isinstance(n, tx.Remap):
            return self.remap(n, depth)
        if isinstance(n, tx.Smoothstep):
            return self.smoothstep(n, depth)
        if isinstance(n, tx.Adjust):
            return self.adjust(n, depth)
        if isinstance(n, tx.Tint):
            return self.tint(n, depth)
        if isinstance(n, (tx.NormalMap, tx.Bump)):  # texmaps puts these at a normal or bump root only: its image
            image = tx.first_image(n)
            return self.graph(image, space, depth) if image is not None else MISSING
        return MISSING
