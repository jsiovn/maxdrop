# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""_Surface: the reflection weight, the mirror and the refraction twin of a Principled BSDF; its translucency."""
import bpy

from .sockets import (
    _default, _in, _mean, _on, _out, COLOR, MIRROR_INPUTS, MIRROR_LABEL, MISSING, REFRACTION_LABEL, SPECULAR_LEVEL,
    TIR_FRESNEL, TIR_LABEL, TRANSLUCENCY_ALPHA_LABEL, TRANSLUCENCY_LABEL, TWIN_LABEL, WEIGHT_LABEL, X_STEP, Y_STEP,
)


class _Surface:
    """The Principled BSDF's reflection and refraction: part of _Tree."""

    def specular(self, ir):
        """Specular IOR Level from the IR's reflection weight; (the weight: a node output or a float, mirror) when it
        needs reflection_weight()'s Mix Shader, else None (the level alone draws it). mirror: the IR's fresnel is off
        and the weight is a node output or a swatch without a map (a map that did not convert, or whose image is not
        found, leaves its swatch: that keeps the twin, so a hidden bright swatch never becomes a mirror); Specular
        IOR Level is then 0, the reflection all the mirror's."""
        s = self.bsdf_input("Specular IOR Level")
        if s is None:
            return None
        graph = ir.textures.get("specular")
        if self.constant_at_least("Metallic", 1.0):
            self.float_input("Specular IOR Level", ir.specular, graph, SPECULAR_LEVEL)
            return None
        w = self.float_value(ir.specular, graph)
        if not isinstance(w, bpy.types.NodeSocket) and not 0.0 < w < 1.0:
            if w <= 0.0 and self.transmits(self.bsdf):  # level 0 leaves glass its reflection: the twin removes it
                _default(s, SPECULAR_LEVEL)
                return 0.0, False
            _default(s, max(0.0, min(1.0, w)) * SPECULAR_LEVEL)
            return None
        mirror = not ir.fresnel and (isinstance(w, bpy.types.NodeSocket) or ir.specular.map is None)
        _default(s, 0.0 if mirror else SPECULAR_LEVEL)
        return w, mirror

    def translucent(self, top, ir, normal):
        """top with a Translucent BSDF mixed in by the IR's translucency (a VRay2SidedMtl's share of the light arriving
        on the other side, convert/materials/), a Mix Shader (TRANSLUCENCY_LABEL); top itself where the translucency
        is 0 and no node drives it. The Translucent BSDF takes translucency_color and the Principled BSDF's normal
        (normal: a node output, or None), and the same alpha: below 1 or linked, a Mix Shader
        (TRANSLUCENCY_ALPHA_LABEL) from a Transparent BSDF to it by that alpha, so a leaf's cutout stays one."""
        tex = ir.textures
        graph = tex.get("translucency")
        if graph is None and _mean(ir.translucency.value) <= 0.0:
            return top
        weight = self.float_value(ir.translucency, graph)
        if not isinstance(weight, bpy.types.NodeSocket):
            weight = min(1.0, max(0.0, weight))
            if weight <= 0.0:
                return top
        self.start_row()
        y = self.row - Y_STEP
        self.columns[-1] = self.row - 2 * Y_STEP
        x = self.bsdf.location[0]
        node = self.nodes.new("ShaderNodeBsdfTranslucent")
        node.location = (x, y)
        color = self.graph(tex["translucency_color"].root, COLOR, 0) if "translucency_color" in tex else MISSING
        self.feed(_in(node, "Color"), ir.translucency_color.value if color is MISSING else color)
        if normal is not None:
            self.links.new(normal, _in(node, "Normal"))
        shader = _out(node, "BSDF")
        alpha = self.bsdf.inputs.get("Alpha")
        if alpha is not None and (alpha.is_linked or alpha.default_value < 1.0):
            transparent = self.nodes.new("ShaderNodeBsdfTransparent")
            transparent.location = (x, y - Y_STEP)
            self.columns[-1] = y - 2 * Y_STEP
            cut = self.nodes.new("ShaderNodeMixShader")
            cut.label = TRANSLUCENCY_ALPHA_LABEL
            cut.location = (x + X_STEP * 0.5, y)
            self.feed(cut.inputs[0], alpha.links[0].from_socket if alpha.is_linked else alpha.default_value)
            self.links.new(transparent.outputs[0], cut.inputs[1])
            self.links.new(shader, cut.inputs[2])
            shader = cut.outputs[0]
        self.thin = True
        mix = self.nodes.new("ShaderNodeMixShader")
        mix.label = TRANSLUCENCY_LABEL
        mix.location = (x + X_STEP * 0.75, y + Y_STEP * 0.5)
        self.feed(mix.inputs[0], weight)
        self.links.new(top, mix.inputs[1])
        self.links.new(shader, mix.inputs[2])
        return mix.outputs[0]

    def constant_at_least(self, name, bound):
        s = self.bsdf.inputs.get(name)
        return s is not None and not s.is_linked and s.default_value >= bound

    def reflection_weight(self, bsdf, weight, mirror=False, color=(1.0, 1.0, 1.0)):
        """bsdf (at the IOR's full Fresnel) mixed by weight over a twin without reflection: the Mix Shader's
        output. The twin has bsdf's links and values, but Specular IOR Level 0; on refracting glass it refracts
        without reflecting (refraction_twin), and the weight is 1 where the glass reflects totally (tir_weight).
        mirror: the second shader is bsdf's copy as a metal of color (MIRROR_LABEL: MIRROR_INPUTS with that Base
        Color, Specular IOR Level 0.5 only for an edit that lowers Metallic), the first bsdf (without reflection), or
        on refracting glass the refraction twin (bsdf, whose glass still reflects, then feeds nothing)."""
        self.start_row()
        y = self.row - Y_STEP
        self.columns[-1] = self.row - 2 * Y_STEP
        above = _out(bsdf, "BSDF")
        if mirror:
            own = dict(MIRROR_INPUTS, **{"Base Color": tuple(color[:3]) + (1.0,)})
            above = self.copy_principled(bsdf, MIRROR_LABEL, own, y)
        if self.refracting(bsdf):
            if mirror:
                y -= Y_STEP
                self.columns[-1] = y - Y_STEP
            below = self.refraction_twin(bsdf, y)
            if not self.thin_wall(bsdf):
                weight = self.tir_weight(bsdf, weight, y)
        elif mirror:
            below = _out(bsdf, "BSDF")
        else:
            below = self.copy_principled(bsdf, TWIN_LABEL, {"Specular IOR Level": 0.0}, y)
        mix = self.nodes.new("ShaderNodeMixShader")
        mix.label = WEIGHT_LABEL
        mix.location = (bsdf.location[0] + X_STEP * 0.5, y)
        self.feed(mix.inputs[0], weight)
        self.links.new(below, mix.inputs[1])
        self.links.new(above, mix.inputs[2])
        return mix.outputs[0]

    def copy_principled(self, bsdf, label, own, y):
        """A copy of Principled bsdf at height y: its links and values, but own {input name: value} unlinked; its
        BSDF output."""
        copy = self.nodes.new("ShaderNodeBsdfPrincipled")
        copy.label = label
        copy.location = (bsdf.location[0], y)
        copy.distribution, copy.subsurface_method = bsdf.distribution, bsdf.subsurface_method
        for src, dst in zip(bsdf.inputs, copy.inputs):
            if src.name in own:
                dst.default_value = own[src.name]
            else:
                self.copy_input(src, dst)
        return _out(copy, "BSDF")

    def copy_input(self, src, dst):
        """dst takes src's link, else its value."""
        if src.is_linked:
            self.links.new(src.links[0].from_socket, dst)
        elif hasattr(src, "default_value"):
            dst.default_value = src.default_value

    def transmits(self, bsdf):
        """Principled bsdf's Transmission Weight is linked or above 0."""
        return _on(bsdf, "Transmission Weight")

    def refracting(self, bsdf):
        """True for a Principled that refracts (transmits) and has nothing a Refraction BSDF lacks: a metallic, an
        alpha below 1, an emission, a coat or a sheen (linked or above 0) keep em3.119's twin (its glass still
        reflects in full)."""
        alpha = bsdf.inputs.get("Alpha")
        if alpha is not None and (alpha.is_linked or alpha.default_value < 1.0):
            return False
        emission = _on(bsdf, "Emission Strength") and _on(bsdf, "Emission Color")
        return self.transmits(bsdf) and not (emission or any(_on(bsdf, name) for name in (
            "Metallic", "Coat Weight", "Sheen Weight")))

    def thin_wall(self, bsdf):
        """The Principled's Thin Wall is on (an input of Blender 5.0 and later)."""
        s = bsdf.inputs.get("Thin Wall")
        return s is not None and not s.is_linked and bool(s.default_value)

    def refraction_twin(self, bsdf, y):
        """The part of a refracting Principled without reflection: a Refraction BSDF (REFRACTION_LABEL) tinted as
        the Principled tints each pass, by the square root of its Base Color through a solid (both engines tint
        twice through one, measured), by the Base Color itself and at IOR 1 through a thin wall (as Cycles does;
        EEVEE tints a closed thin-walled object once); its Roughness, IOR and Normal. A transmission that is not a
        constant of at least 1: a Mix Shader (TWIN_LABEL) by it from em3.119's twin, with Transmission Weight 0, to
        the Refraction BSDF. Its shader output."""
        thin = self.thin_wall(bsdf)
        refr = self.nodes.new("ShaderNodeBsdfRefraction")
        refr.label = REFRACTION_LABEL
        refr.location = (bsdf.location[0] - X_STEP * 0.5, y)
        refr.distribution = 'GGX'
        base, color = bsdf.inputs["Base Color"], _in(refr, "Color")
        if thin:
            self.copy_input(base, color)
        elif base.is_linked:
            root = self.nodes.new("ShaderNodeGamma")
            root.label = TWIN_LABEL
            root.location = (refr.location[0] - X_STEP * 0.5, y)
            self.links.new(base.links[0].from_socket, _in(root, "Color"))
            _in(root, "Gamma").default_value = 0.5
            self.links.new(_out(root, "Color"), color)
        else:
            color.default_value = tuple(max(0.0, c) ** 0.5 for c in tuple(base.default_value)[:3]) + (1.0,)
        for name in ("Roughness", "Normal"):
            self.copy_input(bsdf.inputs[name], _in(refr, name))
        if thin:
            _in(refr, "IOR").default_value = 1.0
        else:
            self.copy_input(bsdf.inputs["IOR"], _in(refr, "IOR"))
        full = bsdf.inputs["Transmission Weight"]
        if not full.is_linked and full.default_value >= 1.0:
            return _out(refr, "BSDF")
        twin = self.copy_principled(bsdf, TWIN_LABEL, {"Specular IOR Level": 0.0, "Transmission Weight": 0.0},
                                    y - Y_STEP)
        self.columns[-1] = min(self.columns[-1], y - 2 * Y_STEP)
        split = self.nodes.new("ShaderNodeMixShader")
        split.label = TWIN_LABEL
        split.location = (bsdf.location[0] + X_STEP * 0.25, y - Y_STEP * 0.5)
        self.copy_input(bsdf.inputs["Transmission Weight"], split.inputs[0])
        self.links.new(twin, split.inputs[1])
        self.links.new(_out(refr, "BSDF"), split.inputs[2])
        return split.outputs[0]

    def tir_weight(self, bsdf, weight, y):
        """The weight raised to 1 where the glass reflects totally (a Fresnel node at bsdf's IOR and normal above
        TIR_FRESNEL): Cycles' Refraction BSDF is black there, where the Principled reflects everything. Math nodes
        (TIR_LABEL): GREATER_THAN, then MAXIMUM of the weight (input 0) and that mask (input 1); its output. The
        whole Mix factor follows, so with a Transmission Weight below 1 the mask shows bsdf alone there, not the
        twin's share without transmission: intended, but not measured on such glass."""
        fresnel = self.nodes.new("ShaderNodeFresnel")
        greater = self.nodes.new("ShaderNodeMath")
        maximum = self.nodes.new("ShaderNodeMath")
        for i, n in enumerate((fresnel, greater, maximum)):
            n.label = TIR_LABEL
            n.location = (bsdf.location[0] - X_STEP * (2.5 - i), y + Y_STEP * 0.5)
        self.copy_input(bsdf.inputs["IOR"], _in(fresnel, "IOR"))
        self.copy_input(bsdf.inputs["Normal"], _in(fresnel, "Normal"))
        greater.operation, maximum.operation = 'GREATER_THAN', 'MAXIMUM'
        self.links.new(_out(fresnel, "Fac"), greater.inputs[0])
        greater.inputs[1].default_value = TIR_FRESNEL
        self.feed(maximum.inputs[0], weight)
        self.links.new(greater.outputs[0], maximum.inputs[1])
        return maximum.outputs[0]
