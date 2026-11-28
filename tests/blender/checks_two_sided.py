# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of the material builder on VRay2SidedMtl: its translucency and its back material (maxdrop-o53.1.7)."""
from .core import check, empty_scene
from .nodes import _bsdfs, _from, _shaders
from .tables import TRANSLUCENCY_ALPHA_LABEL, TRANSLUCENCY_LABEL


def _labelled(m, label):
    return [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeMixShader" and n.label == label]


def _kind(m, idname):
    return [n for n in m.node_tree.nodes if n.bl_idname == idname]


def _surface(m):
    out = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
    return _from(out.inputs["Surface"])


def check_builder_two_sided():
    """A translucency: a Translucent BSDF (its color translucency_color) under a Mix Shader (TRANSLUCENCY_LABEL) whose
    factor is the weight, over the Principled BSDF, into the output; none at 0; a weight graph linked into the factor;
    an alpha below 1 or linked cuts the Translucent BSDF by a Mix Shader from a Transparent BSDF; the normal is the
    BSDF's. A back layer: a Mix Shader driven by Geometry > Backfacing from the front to the back."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    empty_scene()
    try:
        make = build_materials.MaterialBuilder().make
        front = cm.MaterialIR(40, "TwoFront", "test", base_color=cm.Input((1.0, 0.0, 0.0)),
                              translucency=cm.Input(0.3), translucency_color=cm.Input((0.0, 1.0, 0.0)))
        m = make(front)
        mixes, translucent = _labelled(m, TRANSLUCENCY_LABEL), _kind(m, "ShaderNodeBsdfTranslucent")
        mix = mixes[0] if len(mixes) == 1 else None
        check("two-sided: one Translucent BSDF under one Mix Shader into the output", mix is not None
              and len(translucent) == 1 and _surface(m) == mix and _from(mix.inputs[2]) == translucent[0]
              and _from(mix.inputs[1]) == _bsdfs(m)[0], "%d Mix, %d Translucent" % (len(mixes), len(translucent)))
        check("two-sided: the factor is the weight 0.3, the color the back's green", mix is not None
              and not mix.inputs[0].is_linked and abs(mix.inputs[0].default_value - 0.3) < 1e-6
              and tuple(translucent[0].inputs["Color"].default_value)[:3] == (0.0, 1.0, 0.0))
        check("two-sided: no alpha cut at alpha 1", not _labelled(m, TRANSLUCENCY_ALPHA_LABEL)
              and not _kind(m, "ShaderNodeBsdfTransparent"))

        empty_scene()
        m = make(cm.MaterialIR(41, "Opaque", "test", translucency=cm.Input(0.0)))
        check("two-sided: no Translucent BSDF at translucency 0", not _kind(m, "ShaderNodeBsdfTranslucent")
              and not _labelled(m, TRANSLUCENCY_LABEL))

        empty_scene()
        graphed = cm.MaterialIR(42, "Graphed", "test", alpha=cm.Input(0.5), translucency=cm.Input(0.3, cm.MapRef(1)))
        graphed.textures["translucency"] = tx.TextureGraphIR(tx.Mix(tx.Constant(0.3), tx.Checker(tx.Mapping()), 0.5),
                                                             tx.DATA)
        m = make(graphed)
        mixes, cuts = _labelled(m, TRANSLUCENCY_LABEL), _labelled(m, TRANSLUCENCY_ALPHA_LABEL)
        check("two-sided: a weight graph linked into the factor", len(mixes) == 1 and mixes[0].inputs[0].is_linked)
        cut = cuts[0] if len(cuts) == 1 else None
        check("two-sided: alpha 0.5 cuts the Translucent BSDF from a Transparent BSDF by 0.5", cut is not None
              and not cut.inputs[0].is_linked and abs(cut.inputs[0].default_value - 0.5) < 1e-6
              and _from(cut.inputs[1]).bl_idname == "ShaderNodeBsdfTransparent"
              and _from(cut.inputs[2]).bl_idname == "ShaderNodeBsdfTranslucent" and _from(mixes[0].inputs[2]) == cut)

        empty_scene()
        leaf = cm.MaterialIR(43, "Leaf", "test", alpha=cm.Input(1.0, cm.MapRef(1)), translucency=cm.Input(0.4),
                             bump=cm.MapRef(2))
        leaf.textures["alpha"] = tx.TextureGraphIR(tx.Checker(tx.Mapping()), tx.DATA)
        leaf.textures["bump"] = tx.TextureGraphIR(tx.Bump(tx.Checker(tx.Mapping()), 1.0), tx.BUMP)
        m = make(leaf)
        p = _bsdfs(m)[0]
        cuts, translucent = _labelled(m, TRANSLUCENCY_ALPHA_LABEL), _kind(m, "ShaderNodeBsdfTranslucent")
        check("two-sided: a linked alpha cuts the Translucent BSDF by the Principled BSDF's own alpha", len(cuts) == 1
              and p.inputs["Alpha"].is_linked and cuts[0].inputs[0].is_linked
              and cuts[0].inputs[0].links[0].from_socket == p.inputs["Alpha"].links[0].from_socket)
        check("two-sided: the Translucent BSDF takes the Principled BSDF's normal", len(translucent) == 1
              and p.inputs["Normal"].is_linked and translucent[0].inputs["Normal"].is_linked
              and translucent[0].inputs["Normal"].links[0].from_socket == p.inputs["Normal"].links[0].from_socket)

        empty_scene()
        tinted = cm.MaterialIR(45, "Tinted", "test", base_color=cm.Input((1.0, 0.0, 0.0), cm.MapRef(1)),
                               translucency=cm.Input(0.4), translucency_color=cm.Input((1.0, 0.0, 0.0), cm.MapRef(1)))
        color = tx.TextureGraphIR(tx.Mix(tx.Constant((1.0, 0.0, 0.0)), tx.Constant((0.0, 0.0, 1.0)), 0.5,
                                         tx.Checker(tx.Mapping())), tx.COLOR)
        tinted.textures.update(base_color=color, translucency_color=color)
        m = make(tinted)
        p, translucent = _bsdfs(m)[0], _kind(m, "ShaderNodeBsdfTranslucent")
        check("two-sided: a translucency color graph linked into the Translucent BSDF, the base color's own nodes",
              len(translucent) == 1 and translucent[0].inputs["Color"].is_linked and p.inputs["Base Color"].is_linked
              and translucent[0].inputs["Color"].links[0].from_socket == p.inputs["Base Color"].links[0].from_socket)

        empty_scene()
        back = cm.MaterialIR(44, "TwoBack", "test", base_color=cm.Input((0.0, 1.0, 0.0)),
                             translucency=cm.Input(0.3), translucency_color=cm.Input((1.0, 0.0, 0.0)))
        front.layers = [cm.Layer(back, mode=cm.BACK)]
        m = make(front)
        shaders, mixes = _shaders(m), _labelled(m, TRANSLUCENCY_LABEL)
        facing = shaders[0] if len(shaders) == 1 else None
        geometry = _from(facing.inputs[0]) if facing is not None else None
        check("two-sided: a back layer by a Mix Shader driven by Geometry > Backfacing into the output",
              facing is not None and _surface(m) == facing and geometry is not None
              and geometry.bl_idname == "ShaderNodeNewGeometry"
              and facing.inputs[0].links[0].from_socket.identifier == "Backfacing", str(len(shaders)))
        check("two-sided: front and back each with their Translucent BSDF, the front's below", len(_bsdfs(m)) == 2
              and len(mixes) == 2 and facing is not None and _from(facing.inputs[1]) in mixes
              and _from(facing.inputs[2]) in mixes and _from(facing.inputs[1]) != _from(facing.inputs[2]))
    finally:
        empty_scene()
