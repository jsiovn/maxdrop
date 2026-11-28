# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The layered materials: CoronaLayeredMtl (a base and its layers) and VRayBlendMtl (a base and its coats)."""
import dataclasses

from ...reader import classids
from .. import texmaps as _texmaps
from ..params import finite as _finite
from .ids import (
    CORONA_AMOUNTS, CORONA_BASE, CORONA_MASK_AMOUNTS, CORONA_MASKS, CORONA_MASKS_ON, MAX_LAYER_BSDFS, MAX_LAYERS,
    VRAY_BLEND_ADDITIVE, VRAY_BLEND_BASE, VRAY_BLEND_COLOR, VRAY_BLEND_COLORS, VRAY_BLEND_MAPS,
    VRAY_BLEND_MULTIPLIERS,
)
from .ir import ADD, Layer, MIX
from .values import mean
from .corona import _flag_tab, _num_tab


def _layered(conv, m, ir, base_index, layers, weigh, noun="layer", item="layer %d"):
    """The base's IR, named after layered material m, with a Layer for each of layers ([(table position, object
    index)], bottom first): at most MAX_LAYERS, and no more than MAX_LAYER_BSDFS Principled BSDFs in all (the rest left
    out, an issue). A base or layer that is a Multi/Sub-Object gives its first entry (an issue); a shadow-catcher base
    mixes as its grey, not making the object a shadow catcher. weigh(k, layer IR, out) gives the Layer of table
    position k. Returns the IR: the textures are the base's, the weights' graphs made by weigh. The issues name a
    layer by noun (its plural by an s) and a layer object by item (its object index)."""
    base = conv.convert(base_index)
    if base is None:  # not a material (the peel checks only that it is set)
        return conv._grey(m.index, "%s: base is not a material" % (m.name or conv._class_name(m),))
    out = dataclasses.replace(base, index=ir.index, name=ir.name, source=ir.source, unknown=False, shadow_catcher=False,
                              textures=dict(base.textures), issues=list(base.issues), layers=list(base.layers))
    for sub in [base_index] + [i for _k, i in layers]:
        peeled = conv.peel(sub)[0]
        if peeled is not None and conv.is_class(peeled, classids.SC_MATERIAL, classids.MULTI_SUB_MTL):
            conv.issue(m.index, "%s: Multi/Sub-Object %d mixed as its first entry" % (out.name, sub), out)
    if len(layers) > MAX_LAYERS:
        conv.issue(m.index, "%s: %d %ss, only the first %d mixed" % (out.name, len(layers), noun, MAX_LAYERS), out)
    total = 1 + sum(conv.bsdf_count(layer.ir) for layer in out.layers)
    for k, index in layers[:MAX_LAYERS]:
        layer = conv.convert(index)
        if layer is None:
            conv.issue(m.index, "%s: %s is not a material" % (out.name, item % index), out)
            continue
        total += conv.bsdf_count(layer)
        if total > MAX_LAYER_BSDFS:
            conv.issue(m.index, "%s: %ss past %d Principled BSDFs not mixed" % (out.name, noun, MAX_LAYER_BSDFS), out)
            break
        if layer.medium is not None:
            conv.issue(m.index, "%s: %s's medium not converted" % (out.name, item % index), out)
        out.layers.append(weigh(k, layer, out))
    return out


def _mask_graph(conv, mask, value, out):
    """The TextureGraphIR (MASK: it mixes two shaded colors) of a layer's mask, its issues added to out; None without
    a mask or a TexmapConverter, or when no usable map is there."""
    if mask is None or conv.texmaps is None:
        return None
    graph = conv.texmaps.convert(mask, _texmaps.MASK, value)
    if graph is not None:
        out.issues.extend(r for r in graph.issues if r not in out.issues)
    return graph


def corona_layered_mtl(conv, m, ir):
    """CoronaLayeredMtl with a base and a layer on (block 0, CORONA_*): _layered over every layer that is on and set,
    each a Layer of its amount and its mask where masksOn, at the mask amount (lerp(1, mask, mask amount))."""
    def weigh(k, layer, out):
        amount = max(0.0, _num_tab(m, CORONA_AMOUNTS, k, 1.0))
        mask = None
        if _flag_tab(m, CORONA_MASKS_ON, k, True):
            mask_amount = max(0.0, _num_tab(m, CORONA_MASK_AMOUNTS, k, 1.0))
            mask = conv.to_map(m, m.param(CORONA_MASKS, 0, tab=k), "layer mask %d" % k, mask_amount, ir=out)
        return Layer(layer, amount, mask, _mask_graph(conv, mask, 1.0, out))

    return _layered(conv, m, ir, m.param(CORONA_BASE, 0).index, conv.corona_layers(m), weigh)


def vray_blend_mtl(conv, m, ir):
    """VRayBlendMtl with a base and a coat set and on (block 0, VRAY_BLEND_*): _layered over those coats (blend_coats),
    each a Layer mixed over what is below (MIX) or, in additive mode, added over it (ADD). Its weight: the blend color
    taken as a swatch on a mask (the scene's swatch rule on the mean of its channels, each clamped to 0..1: what V-Ray
    5.2 was measured to render for a constant mask, TexmapConverter._swatch); with a blend map, that weight and the
    map mixed by the map multiplier (percent) as a slot mixes its swatch and its map, a MASK graph. Without a graph
    (no TexmapConverter, an unusable map) the weight is the blend color's. A colored blend color where it counts is an
    issue: V-Ray blends per channel (coats numbered from 1, as 3ds Max shows them). The weights are not measured
    (maxdrop-o53.3.2 calibrates them)."""
    mode = ADD if _finite(m.param(VRAY_BLEND_ADDITIVE, 0)) and m.param(VRAY_BLEND_ADDITIVE, 0) else MIX
    name = m.name or conv._class_name(m)

    def weigh(k, layer, out):
        v = m.param(VRAY_BLEND_COLORS, 0, tab=k)
        if not (isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3])):
            v = VRAY_BLEND_COLOR
        stored = tuple(min(1.0, max(0.0, c)) for c in v[:3])
        weight = conv.swatches.channel(mean(stored))
        multiplier = max(0.0, _num_tab(m, VRAY_BLEND_MULTIPLIERS, k, 100.0) / 100.0)
        ref = m.param(VRAY_BLEND_MAPS, 0, tab=k)
        mask = conv.to_map(m, ref, "coat %d blend map" % (k + 1), multiplier, ir=out)
        graph = _mask_graph(conv, mask, weight, out)
        if (graph is None or multiplier < 1.0) and max(stored) - min(stored) > 0.5 / 255:
            conv.issue(m.index, "%s: coat %d's blend color (%.3f, %.3f, %.3f) drawn as its mean, not per channel"
                       % ((name, k + 1) + stored), out)
        return Layer(layer, 1.0 if graph is not None else weight, mask, graph, mode)

    return _layered(conv, m, ir, m.param(VRAY_BLEND_BASE, 0).index, conv.blend_coats(m), weigh, "coat",
                    "coat object %d")
