# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A material's texture graphs, leveled to the node budget: texture_graphs()."""
import dataclasses

from .ids import BUMP, COLOR, MASK, MAX_NODES, NORMAL
from .ir import Constant, Mix, Multiply, TextureGraphIR, Tint, tree_size
from .dispatch import SLOT_KINDS


MEAN_ROW = (1.0 / 3.0,) * 3  # a Tint of these rows gives the mean of the channels in each


def _kept(root, value):
    """root, or Constant(value) where its images are missing: a slot Mix over a constant has it already, a bare map
    goes under a Mix at factor 1 over it (the builder draws the constant for a missing side)."""
    if isinstance(root, Constant) or (isinstance(root, Mix) and root.mask is None and isinstance(root.a, Constant)):
        return root
    return Mix(Constant(value), root, 1.0)


def _leveled(ir, tex, plain):
    """The base color graph of a Standard material with a Diffuse Level map (materials.DiffuseLevel): the diffuse at
    level 1 (the swatch with the diffuse map mixed over it by its amount, without its scale) times the mean of
    lerp(level, the map, its amount), the map a MASK (decoded with the gamma off, as the level is). plain: the base
    color graph without the level map (None: none), which stays when the level map gives no graph, and also, with
    an issue, when the product is past MAX_NODES: the diffuse then takes the level alone."""
    lv = ir.diffuse_level
    f = tex.convert(lv.map, MASK, lv.level)
    if f is None:
        return plain
    color = tuple(lv.color)
    ref = ir.base_color.map
    d = tex.convert(dataclasses.replace(ref, scale=1.0), COLOR, color) if ref is not None else None
    root = Multiply(Constant(color) if d is None else _kept(d.root, color),
                    Tint(_kept(f.root, lv.level), MEAN_ROW, MEAN_ROW, MEAN_ROW))
    if tree_size(root) > MAX_NODES:
        reason = "map %d: Diffuse Level map left out: the base color graph would be past %d nodes" % (
            lv.map.index, MAX_NODES)
        tex.note(lv.map.index, reason)
        return None if plain is None else dataclasses.replace(plain, issues=plain.issues + (reason,))
    parts = [g for g in (d, f) if g is not None]
    issues = tuple(dict.fromkeys(i for g in parts for i in g.issues))
    return TextureGraphIR(root, COLOR, any(g.approximated for g in parts), issues)


def texture_graphs(ir, tex):
    """{input name: TextureGraphIR} for the inputs of a MaterialIR that a usable map drives."""
    out = {}
    for name, kind in SLOT_KINDS:
        inp = getattr(ir, name)
        if inp.map is not None:
            g = tex.convert(inp.map, kind, inp.value)
            if g is not None:
                out[name] = g
    if ir.diffuse_level is not None:
        g = _leveled(ir, tex, out.get("base_color"))
        if g is not None:
            out["base_color"] = g
    for name, kind in (("normal", NORMAL), ("bump", BUMP)):
        ref = getattr(ir, name)
        if ref is not None:
            g = tex.convert(ref, kind)
            if g is not None:
                out[name] = g
    return out
