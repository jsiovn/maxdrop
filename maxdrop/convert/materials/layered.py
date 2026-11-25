# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rule of CoronaLayeredMtl: a base and its layers."""
import dataclasses

from ...reader import classids
from .. import texmaps as _texmaps
from .ids import (
    CORONA_AMOUNTS, CORONA_BASE, CORONA_MASK_AMOUNTS, CORONA_MASKS, CORONA_MASKS_ON, MAX_LAYER_BSDFS, MAX_LAYERS,
)
from .ir import Layer
from .corona import _flag_tab, _num_tab


def corona_layered_mtl(conv, m, ir):
    """CoronaLayeredMtl with a base and a layer on (block 0, CORONA_*): the base's IR, named after the layered
    material, with every layer that is on and set as a Layer (its amount, its mask where masksOn, the mask amount);
    at most MAX_LAYERS, and no more than MAX_LAYER_BSDFS Principled BSDFs in all (the rest left out, an issue). A
    base or layer that is a Multi/Sub-Object gives its first entry (an issue); a shadow-catcher base mixes as its grey,
    not making the object a shadow catcher. Returns the IR: the textures are the base's, the masks' graphs made here."""
    base_index = m.param(CORONA_BASE, 0).index
    base = conv.convert(base_index)
    if base is None:  # not a material (the peel checks only that it is set)
        return conv._grey(m.index, "%s: base is not a material" % (m.name or "CoronaLayeredMtl",))
    out = dataclasses.replace(base, index=ir.index, name=ir.name, source=ir.source, unknown=False, shadow_catcher=False,
                              textures=dict(base.textures), issues=list(base.issues), layers=list(base.layers))
    layers = conv.corona_layers(m)
    for sub in [base_index] + [i for _k, i in layers]:
        peeled = conv.peel(sub)[0]
        if peeled is not None and conv.is_class(peeled, classids.SC_MATERIAL, classids.MULTI_SUB_MTL):
            conv.issue(m.index, "%s: Multi/Sub-Object %d mixed as its first entry" % (out.name, sub), out)
    if len(layers) > MAX_LAYERS:
        conv.issue(m.index, "%s: %d layers, only the first %d mixed" % (out.name, len(layers), MAX_LAYERS), out)
    total = 1 + sum(conv.bsdf_count(layer.ir) for layer in out.layers)
    for k, index in layers[:MAX_LAYERS]:
        layer = conv.convert(index)
        if layer is None:
            conv.issue(m.index, "%s: layer %d is not a material" % (out.name, index), out)
            continue
        total += conv.bsdf_count(layer)
        if total > MAX_LAYER_BSDFS:
            conv.issue(m.index, "%s: layers past %d Principled BSDFs not mixed" % (out.name, MAX_LAYER_BSDFS), out)
            break
        if layer.medium is not None:
            conv.issue(m.index, "%s: layer %d's medium not converted" % (out.name, index), out)
        amount = max(0.0, _num_tab(m, CORONA_AMOUNTS, k, 1.0))
        mask = None
        if _flag_tab(m, CORONA_MASKS_ON, k, True):
            mask_amount = max(0.0, _num_tab(m, CORONA_MASK_AMOUNTS, k, 1.0))
            mask = conv.to_map(m, m.param(CORONA_MASKS, 0, tab=k), "layer mask %d" % k, mask_amount, ir=out)
        graph = None
        if mask is not None and conv.texmaps is not None:
            graph = conv.texmaps.convert(mask, _texmaps.MASK, 1.0)  # it mixes two shaded colors
            if graph is not None:
                out.issues.extend(r for r in graph.issues if r not in out.issues)
        out.layers.append(Layer(layer, amount, mask, graph))
    return out
