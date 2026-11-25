# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers the checks share: the IRs of a file, the node trees' Principled BSDFs and inputs, what feeds an
input, images, media, PNGs written for a test, the cancelled runs' state and steps."""
import math

import bpy

from .core import _mirror_inputs, close
from .tables import DEG, MIRROR_LABEL, TIR_LABEL, TWIN_LABEL, VALUE_TOLERANCE, WEIGHT_LABEL


def _irs(path):
    """convert.scene.read of path and the slot plan of its materials, converted with the texture-map rules."""
    from maxdrop.convert import materials as convert_materials
    from maxdrop.convert import scene as convert_scene
    from maxdrop.convert import texmaps as convert_texmaps
    from maxdrop.reader import assets, cfb, materials as reader_materials, scene as reader_scene
    desc = convert_scene.read(path)
    with cfb.CompoundFile(path) as cf:
        sc = reader_scene.Scene.from_file(cf)
        graph = reader_materials.MaterialGraph(sc)
        tex = convert_texmaps.TexmapConverter(graph, assets.AssetTable.from_file(cf))
        conv = convert_materials.MaterialConverter(graph, texmaps=tex)
        slots = convert_materials.assign(desc, convert_materials.node_materials(sc, desc), conv)
    return desc, slots


def _bsdfs(material):
    """The Principled BSDFs of a material, the twins and mirrors of a reflection weight left out."""
    return [n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"
            and n.label not in (TWIN_LABEL, MIRROR_LABEL)]


def _shaders(material):
    """The Mix Shaders of a material's layers (a reflection weight's and its twin's left out)."""
    return [n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeMixShader"
            and n.label not in (WEIGHT_LABEL, TWIN_LABEL)]


def _principled(material):
    nodes = _bsdfs(material)
    return nodes[0] if len(nodes) == 1 else None


def _weight_mix(p):
    """The reflection weight's Mix Shader over Principled p, None when p's Specular IOR Level alone draws it. A
    mirror on refracting glass (bead maxdrop-6n0.7.2) leaves p unlinked: then the weight Mix Shader whose second
    shader is a mirror copy that repeats p and whose first is not a Principled BSDF."""
    out = next(s for s in p.outputs if s.identifier == "BSDF")
    mix = next((link.to_node for link in out.links if link.to_node.bl_idname == "ShaderNodeMixShader"
                and link.to_node.label == WEIGHT_LABEL), None)
    if mix is not None or out.is_linked:
        return mix
    found = []
    for n in p.id_data.nodes:
        copy = _from(n.inputs[2]) if n.bl_idname == "ShaderNodeMixShader" and n.label == WEIGHT_LABEL else None
        below = _from(n.inputs[1]) if copy is not None else None
        if getattr(copy, "label", "") == MIRROR_LABEL and below is not None \
                and below.bl_idname != "ShaderNodeBsdfPrincipled" \
                and _same_inputs(p, copy, _mirror_inputs(copy.inputs["Base Color"].default_value)) == []:
            found.append(n)
    return found[0] if found else None


def _weight_factor(mix):
    """The input a reflection weight's Mix Shader takes the weight from: its factor, or behind a total internal
    reflection mask the MAXIMUM's first input."""
    top = _from(mix.inputs[0])
    if top is not None and top.label == TIR_LABEL and top.bl_idname == "ShaderNodeMath":
        return top.inputs[0]
    return mix.inputs[0]


def _specular_socket(p):
    """The input the IR's specular drives: the reflection weight's factor, else Specular IOR Level."""
    mix = _weight_mix(p)
    return _weight_factor(mix) if mix is not None else p.inputs["Specular IOR Level"]


def _constant_one(p, name):
    s = p.inputs.get(name)
    return s is not None and not s.is_linked and s.default_value >= 1.0


def _same_inputs(p, copy, own):
    """The identifiers of p's inputs copy does not repeat: own {name: value} unlinked on copy, the others p's link
    or value."""
    bad = []
    for a, b in zip(p.inputs, copy.inputs):
        if a.name in own:
            va, want = b.default_value, own[a.name]
            same = not b.is_linked and (close(list(va), list(want), 1e-6) if hasattr(want, "__len__")
                                        else abs(float(va) - want) <= 1e-6)
        elif a.is_linked:
            same = b.is_linked and b.links[0].from_socket == a.links[0].from_socket
        elif hasattr(a, "default_value"):
            va, vb = a.default_value, b.default_value
            same = not b.is_linked and (close(list(va), list(vb), 1e-6) if hasattr(va, "__len__")
                                        else abs(float(va) - float(vb)) <= 1e-6)
        else:
            same = True
        if not same:
            bad.append(a.identifier)
    return bad


def _on(p, name):
    s = p.inputs.get(name)
    if s is None:
        return False
    v = s.default_value
    return s.is_linked or max(tuple(v)[:3] if hasattr(v, "__len__") else (v,)) > 0.0


def _refracting(p):
    """Principled p refracts (Transmission Weight linked or above 0) with nothing a Refraction BSDF lacks (a
    metallic, an alpha below 1 or linked, an emission, a coat, a sheen): its twin refracts without reflecting."""
    alpha = p.inputs["Alpha"]
    return _on(p, "Transmission Weight") and not alpha.is_linked and alpha.default_value >= 1.0 \
        and not (_on(p, "Emission Strength") and _on(p, "Emission Color")) \
        and not any(_on(p, name) for name in ("Metallic", "Coat Weight", "Sheen Weight"))


def _thin(p):
    s = p.inputs.get("Thin Wall")
    return s is not None and not s.is_linked and bool(s.default_value)


def _same_source(a, b):
    """Input b takes input a's link, or its value when a is not linked."""
    if a.is_linked:
        return b.is_linked and b.links[0].from_socket == a.links[0].from_socket
    va, vb = a.default_value, b.default_value
    return not b.is_linked and (close(list(va)[:3], list(vb)[:3], 1e-6) if hasattr(va, "__len__")
                                else abs(float(va) - float(vb)) <= 1e-6)


def _layers_of(ir):
    """Every Layer of a MaterialIR, its layers' layers included, in the order the builder draws them."""
    out = []
    for layer in ir.layers:
        out.append(layer)
        out.extend(_layers_of(layer.ir))
    return out


def _alpha_of(ir, present):
    """(alpha linked, the constant alpha or None) the builder gives a Principled BSDF filled from ir."""
    folded = _fold(ir.textures["alpha"].root, present) if "alpha" in ir.textures else LOST
    if folded is MAP:
        return True, None
    return False, _mean(ir.alpha.value if folded is LOST else folded)


def _value_ok(socket, want):
    """The socket's value against want; a color input stores no negative, so want is held at 0 there."""
    got = socket.default_value
    if isinstance(want, (tuple, list)):
        if socket.type == 'RGBA':
            want = [max(0.0, w) for w in want]
        return close(list(got)[:3], list(want)[:3], VALUE_TOLERANCE)
    return abs(float(got) - float(want)) <= VALUE_TOLERANCE


def _mean(v):
    return sum(v[:3]) / 3.0 if isinstance(v, (tuple, list)) else v


def _images_of(ir):
    """The texmaps.Image nodes of every texture graph of an IR, its layers' and their masks' included, each once."""
    from maxdrop.convert import texmaps as tx
    seen, out = set(), []
    stack = [g.root for g in ir.textures.values()]
    for layer in _layers_of(ir):
        stack.extend(g.root for g in layer.ir.textures.values())
        if layer.graph is not None:
            stack.append(layer.graph.root)
    while stack:
        n = stack.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        if isinstance(n, tx.Image):
            out.append(n)
        stack.extend(tx._children(n))
    return out


MAP, LOST = "map", "lost"  # what _fold gives for a graph a node drives, and for one whose images are all missing


def _fold(n, present):
    """What build.materials makes of a texture graph: MAP when a node drives the input, LOST when the missing images
    leave nothing, else the constant it folds to. present: whether the graph's image files were found. Written from
    the builder's rules (a missing side of a Mix or Multiply gives the other, a Composite drops missing layers)."""
    from maxdrop.convert import texmaps as tx
    if isinstance(n, tx.Constant):
        return n.value
    if isinstance(n, tx.Image):
        return MAP if present else LOST
    if isinstance(n, tx.Invert):
        v = _fold(n.input, present)
        if v in (MAP, LOST):
            return v
        return tuple(1.0 - c for c in v) if isinstance(v, tuple) else 1.0 - v
    if isinstance(n, tx.Decode):  # a Gamma node over its input, a constant through the sRGB curve
        from maxdrop.convert import colors
        v = _fold(n.input, present)
        if v in (MAP, LOST):
            return v
        if n.mean:  # the mean through the sRGB curve (maxdrop-6n0.6.36)
            return colors.srgb_to_linear(sum(v) / 3.0 if isinstance(v, tuple) else v)
        return tuple(colors.srgb_to_linear(c) for c in (v if isinstance(v, tuple) else (v,) * 3))
    if isinstance(n, tx.Mix):
        a, b = _fold(n.a, present), _fold(n.b, present)
        return (b if a is LOST else a) if LOST in (a, b) else MAP
    if isinstance(n, tx.Multiply):
        a, b = _fold(n.a, present), _fold(n.b, present)
        if LOST in (a, b):
            other = b if a is LOST else a
            return MAP if other is MAP else LOST
        if MAP in (a, b):
            return MAP
        return tuple(x * y for x, y in zip(a, b)) if isinstance(a, tuple) else a * b
    if isinstance(n, tx.Blend):
        a, b = _fold(n.a, present), _fold(n.b, present)
        if LOST in (a, b):
            other = b if a is LOST else a
            return MAP if other is MAP else LOST
        if MAP in (a, b):
            return MAP
        return tx.blend_value(n.op, a, b, n.gamma)
    if isinstance(n, tx.ColorCorrect):
        v = _fold(n.input, present)
        changes = n.hue % 1.0 != 0.0 or n.saturation != 1.0 or n.brightness or n.contrast or n.gain != 1.0 \
            or n.gamma != 1.0 or tuple(n.rewire) != tx.REWIRE_NONE
        return v if v is LOST or not changes else MAP
    if isinstance(n, (tx.Adjust, tx.Tint)):  # made only when they change something: nodes
        v = _fold(n.input, present)
        return LOST if v is LOST else MAP
    if isinstance(n, tx.Facing):
        return MAP
    if isinstance(n, (tx.Remap, tx.Smoothstep)):  # a float through a curve: a node over its input
        v = _fold(n.input, present)
        return LOST if v is LOST else MAP
    if isinstance(n, tx.Composite):
        layers = [(v, la) for v, la in ((_fold(la.node, present), la) for la in n.layers) if v is not LOST]
        if not layers:
            return LOST
        v, la = layers[0]
        masked = la.mask is not None and _fold(la.mask, present) is not LOST
        return v if len(layers) == 1 and la.opacity >= 1.0 and not masked else MAP
    image = tx.first_image(n)
    return _fold(image, present) if image is not None else LOST


def _normal_linked(tex, present):
    from maxdrop.convert import texmaps as tx
    linked = False
    for key in ("normal", "bump"):
        if key in tex:
            r = tex[key].root
            if isinstance(r, tx.NormalMap):
                linked = linked or _fold(r.input, present) is MAP or (
                    r.bump is not None and _fold(r.bump.input, present) is MAP)
            else:
                linked = linked or _fold(r.input if isinstance(r, tx.Bump) else r, present) is MAP
    return linked


def _medium_of(material):
    """The medium a material's Volume socket draws (maxdrop-em3.163): (scattering, absorption, anisotropy, emission)
    per channel and per meter, summed over its Add Shaders; None when the socket is not linked."""
    out = next((n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial"), None)
    socket = out.inputs["Volume"] if out is not None else None
    if socket is None or not socket.is_linked:
        return None
    sums = {"scattering": [0.0] * 3, "absorption": [0.0] * 3, "emission": [0.0] * 3, "anisotropy": [0.0],
            "other": []}
    stack = [_from(socket)]
    while stack:
        n = stack.pop()
        kind = getattr(n, "bl_idname", None)
        if kind == "ShaderNodeAddShader":
            stack.extend(_from(i) for i in n.inputs if i.is_linked)
            continue
        color = list(n.inputs["Color"].default_value)[:3] if kind else None
        if kind == "ShaderNodeVolumeScatter":
            d = n.inputs["Density"].default_value
            sums["scattering"] = [a + c * d for a, c in zip(sums["scattering"], color)]
            sums["anisotropy"] = [n.inputs["Anisotropy"].default_value]
        elif kind == "ShaderNodeVolumeAbsorption":
            d = n.inputs["Density"].default_value
            sums["absorption"] = [a + (1.0 - c) * d for a, c in zip(sums["absorption"], color)]
        elif kind == "ShaderNodeEmission":
            d = n.inputs["Strength"].default_value
            sums["emission"] = [a + c * d for a, c in zip(sums["emission"], color)]
        else:
            sums["other"].append(kind)
    return sums


def _decoded(node):
    """The node a Decode's Gamma node of 2.2 is drawn over (a gamma-off color Mix or Composite, maxdrop-em3.158; a
    Falloff, Color Correction, Output or Tint, maxdrop-6n0.6.18), None when node is not such a Gamma node."""
    if node is None or node.bl_idname != "ShaderNodeGamma" or abs(_input(node, "Gamma").default_value - 2.2) > 1e-6:
        return None
    return _from(_input(node, "Color"))


def _expected_mapping(tiling, offset, w_degrees):
    """The Mapping node values for a W angle only: location = 0.5 - R S (0.5 + offset), by hand."""
    c, s = math.cos(w_degrees * DEG), math.sin(w_degrees * DEG)
    x, y = tiling[0] * (0.5 + offset[0]), tiling[1] * (0.5 + offset[1])
    return (0.5 - (c * x - s * y), 0.5 - (s * x + c * y), 0.0), (0.0, 0.0, w_degrees * DEG), (tiling[0], tiling[1], 1.0)


def _mapping_of(material, label):
    """The values of the Mapping node feeding the Image Texture node labelled label."""
    tex = next(n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.label == label)
    link = tex.inputs["Vector"].links[0] if tex.inputs["Vector"].is_linked else None
    m = link.from_node if link is not None else None
    if m is None or m.bl_idname != "ShaderNodeMapping":
        return None, tex
    return tuple(tuple(m.inputs[k].default_value) for k in ("Location", "Rotation", "Scale")), tex


def _from(socket):
    """The node feeding an input, None when it is not linked."""
    return socket.links[0].from_node if socket.is_linked else None


def _input(node, identifier):
    return next(s for s in node.inputs if s.identifier == identifier)


def _meaned(socket):
    """The node whose output a DOT_PRODUCT by (1/3, 1/3, 1/3) turns into the float feeding socket, else None."""
    dot = _from(socket)
    if dot is None or dot.bl_idname != "ShaderNodeVectorMath" or dot.operation != 'DOT_PRODUCT' \
            or not close(list(_input(dot, "Vector_001").default_value), [1 / 3.0] * 3, 1e-6):
        return None
    return _from(_input(dot, "Vector"))


def _color_into_float(material):
    """Every link of a material's tree from a color output into a float input, as 'node.output -> node.input':
    Blender converts there by its luminance, where 3ds Max and V-Ray take the mean of the channels."""
    return ["%s.%s -> %s.%s" % (k.from_node.name, k.from_socket.identifier, k.to_node.name, k.to_socket.identifier)
            for k in material.node_tree.links if k.from_socket.type == 'RGBA' and k.to_socket.type == 'VALUE']


def _write_png(path):
    img = bpy.data.images.new("maxdrop-probe", 4, 4)
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


CANCEL_KINDS = ("objects", "meshes", "curves", "lights", "cameras", "materials", "images", "collections", "texts",
                "node_groups", "worlds")


def _state():
    """What a cancelled run must leave as it found it: the datablocks of each kind, the scene camera, render size,
    the scene's World."""
    r = bpy.context.scene.render
    return ({kind: sorted(b.as_pointer() for b in getattr(bpy.data, kind)) for kind in CANCEL_KINDS},
            bpy.context.scene.camera, (r.resolution_x, r.resolution_y, r.resolution_percentage, r.pixel_aspect_x,
                                       r.pixel_aspect_y), bpy.context.scene.world)


def _cancel_run(paths):
    from maxdrop import options, pipeline
    opts = options.ImportOptions(units='AUTO', scale_objects=1.0, use_image_search=True,
                                 object_filter={'MATERIAL', 'UV'}, modifiers='KEEP',
                                 light_strength=options.LIGHT_STRENGTH, keep_targets=False, axis_forward='Y',
                                 axis_up='Z')
    return pipeline._Run(opts, list(paths), {}, bpy.context)


def _advance(steps, until, limit=100000):
    """next() on steps until until() holds (a short sleep while a worker thread reads); whether it held before the
    run ended."""
    import time
    from maxdrop import pipeline
    for _ in range(limit):
        if until():
            return True
        try:
            if next(steps) is pipeline._WAIT:
                time.sleep(0.005)
        except StopIteration:
            return False
    return False


def _reaches_image(socket, depth=4):
    """Whether an Image Texture node feeds socket, through at most depth nodes."""
    if depth == 0 or not socket.is_linked:
        return False
    n = socket.links[0].from_node
    return n.bl_idname == "ShaderNodeTexImage" or any(_reaches_image(i, depth - 1) for i in n.inputs)


CLIP_LABEL = "Clip"  # the CLIP_LABEL of build/materials/ (the package is imported inside the checks)


def _clip_mask_input(node):
    """The input of a Clip node that carries the clip mask (Math MULTIPLY for Alpha, Vector Math SCALE for Color)."""
    return node.inputs[1] if node.bl_idname == "ShaderNodeMath" else _input(node, "Scale")


def _image_of(socket):
    """(the Image Texture feeding an input, the input of its Clip node that carries the clip mask, or None without
    one)."""
    n = _from(socket)
    if n is not None and n.label == CLIP_LABEL:
        return _from(n.inputs[0]), _clip_mask_input(n)
    return n, None


def _clip_axes_of(tex):
    """The axes ("X", "Y") an Image Texture's clip mask tests (Math COMPARE, |x - 0.5| <= 0.5, of the vector the
    node reads), [] without a mask; None for a mask of another form or Clip nodes that disagree."""
    clips = [n for n in tex.id_data.nodes if n.label == CLIP_LABEL and _from(n.inputs[0]) == tex]
    if not clips:
        return []
    found = set()
    for clip in clips:
        todo, axes = [_from(_clip_mask_input(clip))], []
        while todo:
            n = todo.pop()
            if n is None or n.bl_idname != "ShaderNodeMath":
                return None
            if n.operation == 'MULTIPLY':
                todo += [_from(i) for i in n.inputs[:2]]
                continue
            sep = _from(n.inputs[0])
            if n.operation != 'COMPARE' or n.inputs[1].default_value != 0.5 or n.inputs[2].default_value != 0.5 \
                    or sep is None or sep.bl_idname != "ShaderNodeSeparateXYZ" or not tex.inputs["Vector"].is_linked \
                    or sep.inputs["Vector"].links[0].from_socket != tex.inputs["Vector"].links[0].from_socket:
                return None
            axes.append(n.inputs[0].links[0].from_socket.identifier)
        found.add(tuple(sorted(axes)))
    return list(found.pop()) if len(found) == 1 else None


def _node_kinds(material):
    """{bl_idname, and bl_idname:operation or :blend_type where a node has one} of a material's nodes."""
    out = set()
    for n in material.node_tree.nodes:
        out.add(n.bl_idname)
        for attr in ("operation", "blend_type"):
            if hasattr(n, attr):
                out.add("%s:%s" % (n.bl_idname, getattr(n, attr)))
    return out


def _upstream(socket):
    """Every node that feeds socket, directly or further up."""
    out, todo = {}, [socket]
    while todo:
        for link in todo.pop().links:
            n = link.from_node
            if n.name not in out:
                out[n.name] = n
                todo.extend(n.inputs)
    return list(out.values())
