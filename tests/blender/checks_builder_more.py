# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of the material builder: multiply, diffuse level, wrapper constants, the linear fallback,
image reuse, a double import, the builder's debt."""
import math
import os
import shutil
import tempfile

import bpy

from .core import check, close, empty_scene, ROOT
from .nodes import (
    _clip_axes_of, _color_into_float, _from, _image_of, _images_of, _input, _irs, _meaned, _principled, _write_png,
)


def check_builder_multiply():
    """A Multiply of two maps in a float graph (bead maxdrop-em3.124): V-Ray 5.2 takes the product of the two maps'
    means (red x green 1/9, measured on an RGB Multiply as a Mix mask and a glossiness map, a CoronaMix Multiply as
    a Mix mask), not the mean of their product (0). On roughness and on a color Mix's mask: a Math MULTIPLY of two
    DOT_PRODUCTs by (1/3, 1/3, 1/3), one from each image."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-multiply-")
    try:
        png = os.path.join(scratch, "mult.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        a = tx.Image(1, "mult.png", "mult.png", "", found, colorspace=tx.NON_COLOR)
        b = tx.Image(2, "mult.png", "mult.png", "", found, colorspace=tx.NON_COLOR,
                     mapping=tx.Mapping(tiling=(2.0, 2.0)))
        ir = cm.MaterialIR(52, "Multiply", "test", base_color=cm.Input((0.5,) * 3, cm.MapRef(1)),
                           roughness=cm.Input(0.5, cm.MapRef(1)))
        ir.textures = {
            "base_color": tx.TextureGraphIR(tx.Mix(tx.Constant((0.0,) * 3), tx.Constant((1.0,) * 3), 0.0,
                                                   tx.Multiply(a, b)), tx.COLOR),
            "roughness": tx.TextureGraphIR(tx.Multiply(a, b), tx.DATA)}
        m = build_materials.MaterialBuilder().make(ir)
        check("multiply: material built", m is not None)
        if m is None:
            return
        mixed = _color_into_float(m)
        check("multiply: no color output linked into a float input", mixed == [], str(mixed))
        p = _principled(m)

        def means_product(socket):
            mul = _from(socket)
            if mul is None or mul.bl_idname != "ShaderNodeMath" or mul.operation != 'MULTIPLY':
                return False
            sides = [_meaned(s) for s in mul.inputs[:2]]
            return all(getattr(n, "bl_idname", None) == "ShaderNodeTexImage" for n in sides) and sides[0] != sides[1]

        check("multiply: roughness is the product of the two images' means", means_product(p.inputs["Roughness"]))
        base = _from(p.inputs["Base Color"])
        check("multiply: a color Mix's mask is the product of the two images' means",
              base is not None and base.bl_idname == "ShaderNodeMix"
              and means_product(_input(base, "Factor_Float")))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_diffuse_level():
    """A Standard material's Diffuse Level map (bead maxdrop-em3.150): texmaps._leveled's base color graph, drawn.
    Images found: a color Mix MULTIPLY whose A is the diffuse (a Mix at factor 1 over the swatch, its B the diffuse
    image) and whose B is the mean (a Tint of rows 1/3) of a Mix of the level and the level image by the amount.
    Images missing: the swatch (unlinked A) times the level's Tint."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-level-")
    try:
        png = os.path.join(scratch, "level.png")
        _write_png(png)
        for present in (True, False):
            found = ct.Found(png, ct.SCENE) if present else None
            diffuse = tx.Image(1, "level.png", "level.png", "", found)
            level_map = tx.Image(2, "level.png", "level.png", "", found, mapping=tx.Mapping(tiling=(2.0, 2.0)))

            class Tex:  # what TexmapConverter.convert gives for the two slots, as its _slot makes them
                def convert(self, ref, kind, value=None):
                    if kind == tx.MASK:
                        return tx.TextureGraphIR(tx.Mix(tx.Constant(value), level_map, ref.amount), kind)
                    return tx.TextureGraphIR(diffuse, kind)

            color = (0.6, 0.4, 0.2)
            ir = cm.MaterialIR(53, "DiffuseLevel", "test",
                               base_color=cm.Input(tuple(c * 0.25 for c in color), cm.MapRef(1, 1.0, False, 0.25)))
            ir.diffuse_level = cm.DiffuseLevel(color, 0.25, cm.MapRef(2, 0.6))
            ir.textures = {"base_color": tx._leveled(ir, Tex(), None)}
            tag = "diffuse level (%s): " % ("images" if present else "images missing")
            m = build_materials.MaterialBuilder().make(ir)
            check(tag + "material built", m is not None)
            if m is None:
                continue
            p = _principled(m)
            mul = _from(p.inputs["Base Color"])
            ok = mul is not None and mul.bl_idname == "ShaderNodeMix" and mul.blend_type == 'MULTIPLY'
            check(tag + "Base Color is a color Mix MULTIPLY", ok, getattr(mul, "bl_idname", None))
            if not ok:
                continue
            a, b = _input(mul, "A_Color"), _input(mul, "B_Color")
            check(tag + "the level side is the Tint's sum (a Vector Math ADD)",
                  b.is_linked and _from(b).bl_idname == "ShaderNodeVectorMath" and _from(b).operation == 'ADD')
            scales = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeVectorMath" and n.operation == 'SCALE']
            check(tag + "three Tint rows of 1/3",
                  len(scales) == 3 and all(close(list(_input(n, "Vector").default_value), [1 / 3.0] * 3, 1e-6)
                                           for n in scales), str(len(scales)))
            images = sorted(n.label for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"
                            and any(o.is_linked for o in n.outputs))
            if present:
                dmix = _from(a)
                check(tag + "the diffuse side: a Mix at factor 1 over the swatch, the image on B",
                      dmix is not None and dmix.bl_idname == "ShaderNodeMix"
                      and close([_input(dmix, "Factor_Float").default_value], [1.0], 1e-6)
                      and close(list(_input(dmix, "A_Color").default_value)[:3], list(color), 1e-6)
                      and _from(_input(dmix, "B_Color")).bl_idname == "ShaderNodeTexImage")
                check(tag + "both images feed the graph", len(images) == 2, str(images))
            else:
                check(tag + "the diffuse side is the swatch", not a.is_linked
                      and close(list(a.default_value)[:3], list(color), 1e-6), str(tuple(a.default_value)))
                check(tag + "no image feeds the graph", images == [], str(images))
            mixed = _color_into_float(m)
            check(tag + "no color output linked into a float input", mixed == [], str(mixed))
            empty_scene()
            for img in list(bpy.data.images):
                bpy.data.images.remove(img)
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_builder_wrapper_constants():
    """A constant below a color wrapper keeps its color (bead maxdrop-em3.128): a Tint over a color Constant on
    Roughness is drawn in color, the mean taken after it (a DOT_PRODUCT fed by the Tint's last ADD); a NormalMap over
    a constant color is a Normal Map node fed by an RGB node of that color, not flat (V-Ray tilts the normal by it),
    also through the flips; one whose image is missing (a Mix left with its constant side) stays flat."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    empty_scene()
    tint = tx.Tint(tx.Constant((0.5, 0.5, 1.0)), (0.502, 0.0, 0.0), (0.0, 0.251, 0.0), (0.0, 0.0, 0.125))
    built = {}
    for label, normal in (("white", (1.0, 1.0, 1.0)), ("flat", (0.5, 0.5, 1.0))):
        ir = cm.MaterialIR(53, "WrapperConstant_" + label, "test", roughness=cm.Input(0.5, cm.MapRef(1)))
        ir.normal = cm.MapRef(2)
        ir.textures = {"roughness": tx.TextureGraphIR(tint, tx.DATA),
                       "normal": tx.TextureGraphIR(tx.NormalMap(tx.Constant(normal)), tx.NORMAL)}
        built[label] = build_materials.MaterialBuilder().make(ir)
    lost = tx.Image(9, "nothere.png", "nothere.png", "", None, colorspace=tx.NON_COLOR)
    extra = {}
    for label, normal in (("flipped", tx.NormalMap(tx.Constant((1.0, 0.5, 1.0)), flip_green=True)),
                          ("lost", tx.NormalMap(tx.Mix(lost, tx.Constant((0.0, 0.0, 0.0)), 0.5)))):
        ir = cm.MaterialIR(54, "WrapperConstant_" + label, "test")
        ir.normal = cm.MapRef(2)
        ir.textures = {"normal": tx.TextureGraphIR(normal, tx.NORMAL)}
        extra[label] = build_materials.MaterialBuilder().make(ir)
    try:
        m = extra["flipped"]
        sep = next((n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeSeparateColor"), None) if m else None
        nm = _from(_principled(m).inputs["Normal"]) if m else None
        check("wrapper constants: a flipped constant normal goes RGB -> Separate / Combine Color -> Normal Map",
              getattr(nm, "bl_idname", None) == "ShaderNodeNormalMap" and sep is not None
              and getattr(_from(sep.inputs["Color"]), "bl_idname", None) == "ShaderNodeRGB")
        m = extra["lost"]
        check("wrapper constants: a normal whose image is missing stays flat (no Normal Map node)",
              m is not None and not any(n.bl_idname == "ShaderNodeNormalMap" for n in m.node_tree.nodes)
              and not _principled(m).inputs["Normal"].is_linked)
        for label, normal in (("white", (1.0, 1.0, 1.0)), ("flat", (0.5, 0.5, 1.0))):
            m = built[label]
            check("wrapper constants (%s): material built" % label, m is not None)
            if m is None:
                continue
            mixed = _color_into_float(m)
            check("wrapper constants (%s): no color output linked into a float input" % label, mixed == [], str(mixed))
            p = _principled(m)
            add = _meaned(p.inputs["Roughness"])
            sep = next((n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeSeparateColor"), None)
            rgb = _from(sep.inputs["Color"]) if sep is not None else None
            check("wrapper constants (%s): roughness is the mean of the Tint of the color (0.5, 0.5, 1)" % label,
                  getattr(add, "bl_idname", None) == "ShaderNodeVectorMath" and add.operation == 'ADD'
                  and getattr(rgb, "bl_idname", None) == "ShaderNodeRGB"
                  and close(list(rgb.outputs[0].default_value)[:3], [0.5, 0.5, 1.0], 1e-6))
            nm = _from(p.inputs["Normal"])
            src = _from(nm.inputs["Color"]) if nm is not None and nm.bl_idname == "ShaderNodeNormalMap" else None
            check("wrapper constants (%s): the normal is a Normal Map node fed by an RGB node of %s" % (label, normal),
                  getattr(src, "bl_idname", None) == "ShaderNodeRGB"
                  and close(list(src.outputs[0].default_value)[:3], list(normal), 1e-6))
    finally:
        empty_scene()


def check_linear_fallback():
    """A color management config without Linear Rec.709 (a custom OCIO config; the stock one of every supported
    version has it): a linear color image falls back to Non-Color, shares the datablock of the same file as data,
    and keeps its gamma override's Gamma node (bead maxdrop-em3.62)."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-linear-")
    stock = build_materials._input_colorspaces
    try:
        check("linear fallback: the stock config has Linear Rec.709", tx.LINEAR in stock())
        png = os.path.join(scratch, "linear.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        build_materials.builder._input_colorspaces = lambda: frozenset((tx.SRGB, tx.NON_COLOR))
        ir = cm.MaterialIR(40, "LinearFallback", "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)),
                           roughness=cm.Input(0.5, cm.MapRef(2)))
        ir.textures = {
            "base_color": tx.TextureGraphIR(tx.Image(1, "linear.png", "linear.png", "", found, colorspace=tx.LINEAR,
                                                     gamma=1.8), tx.COLOR),
            "roughness": tx.TextureGraphIR(tx.Image(2, "linear.png", "linear.png", "", found,
                                                    colorspace=tx.NON_COLOR), tx.DATA)}
        builder = build_materials.MaterialBuilder()
        m = builder.make(ir)
        p = _principled(m)
        gam = _from(p.inputs["Base Color"])
        rough = _meaned(p.inputs["Roughness"])
        tex = _from(gam.inputs["Color"]) if gam is not None and gam.bl_idname == "ShaderNodeGamma" else None
        check("linear fallback: Non-Color, one datablock with the data image, the Gamma node kept",
              tex is not None and abs(gam.inputs["Gamma"].default_value - 1.8) < 1e-6
              and tex.image is not None and tex.image.colorspace_settings.name == tx.NON_COLOR
              and rough is not None and rough.image is not None
              and tex.image.as_pointer() == rough.image.as_pointer()
              and len(bpy.data.images) == 1,
              "%s %s" % (getattr(gam, "bl_idname", None), [i.colorspace_settings.name for i in bpy.data.images]))
    finally:
        build_materials.builder._input_colorspaces = stock
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def check_image_reuse():
    """MaterialBuilder reuses an image already in the file (an earlier import's) of the same file and color space,
    untouched (bead maxdrop-em3.43): a second builder adds no image; the same file in another color space is a new
    image and the first keeps its color space; a modified, a packed, a generated, a library image or one whose alpha
    mode was changed is not reused."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-reuse-")
    try:
        png = os.path.join(scratch, "reuse.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        spaces = [i.identifier for i in bpy.types.ColorManagedInputColorspaceSettings.bl_rna.properties["name"]
                  .enum_items if i.identifier not in (tx.SRGB, tx.NON_COLOR)]
        other = next((c for c in spaces if c.startswith("Linear")), spaces[0])

        def build(name, *colorspaces):
            """The images of a material whose base color and roughness are reuse.png in these color spaces, made by
            a builder of its own (another import)."""
            ir = cm.MaterialIR(30, name, "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)),
                               roughness=cm.Input(0.5, cm.MapRef(2)))
            a, b = (tx.Image(k + 1, "reuse.png", "reuse.png", "", found, colorspace=c)
                    for k, c in enumerate(colorspaces))
            ir.textures = {"base_color": tx.TextureGraphIR(a, tx.COLOR), "roughness": tx.TextureGraphIR(b, tx.DATA)}
            m = build_materials.MaterialBuilder().make(ir)
            return _from(_principled(m).inputs["Base Color"]).image, _meaned(_principled(m).inputs["Roughness"]).image

        def names():
            return [(i.name, i.colorspace_settings.name, i.is_dirty, i.source, bool(i.packed_file), bool(i.library))
                    for i in bpy.data.images]

        base, rough = build("ReuseA", tx.SRGB, tx.NON_COLOR)
        check("reuse: the first builder loads the file in sRGB and Non-Color", len(bpy.data.images) == 2
              and base.colorspace_settings.name == tx.SRGB and rough.colorspace_settings.name == tx.NON_COLOR,
              str(names()))
        base2, rough2 = build("ReuseB", tx.SRGB, tx.NON_COLOR)
        check("reuse: a second builder reuses both images, adds none", len(bpy.data.images) == 2
              and base2.as_pointer() == base.as_pointer() and rough2.as_pointer() == rough.as_pointer(),
              str(names()))
        base3, rough3 = build("ReuseC", other, tx.SRGB)
        check("reuse: the same file in %s is a new image, the sRGB one reused and still sRGB" % other,
              len(bpy.data.images) == 3 and rough3.as_pointer() == base.as_pointer()
              and base3.colorspace_settings.name == other and base.colorspace_settings.name == tx.SRGB,
              str(names()))
        base.pixels[0] = 0.25  # painted on: it no longer is the file
        check("reuse: writing a pixel makes the image dirty", base.is_dirty)
        base4, rough4 = build("ReuseD", tx.SRGB, tx.NON_COLOR)
        check("reuse: a modified image is not reused, a new one loaded", len(bpy.data.images) == 4
              and base4.as_pointer() != base.as_pointer() and base4.colorspace_settings.name == tx.SRGB
              and not base4.is_dirty and rough4.as_pointer() == rough.as_pointer(), str(names()))
        for img in (base, base4):
            bpy.data.images.remove(img)
        base5 = build("ReuseE", tx.SRGB, tx.NON_COLOR)[0]
        base5.pack()
        base6 = build("ReuseF", tx.SRGB, tx.NON_COLOR)[0]
        check("reuse: a packed image is not reused", base6.as_pointer() != base5.as_pointer()
              and base5.packed_file is not None and base6.packed_file is None, str(names()))
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        straight = build("ReuseAlpha", tx.SRGB, tx.NON_COLOR)[0]
        straight.alpha_mode = 'CHANNEL_PACKED'
        packed_alpha = build("ReuseAlpha2", tx.SRGB, tx.NON_COLOR)[0]
        check("reuse: an image whose alpha mode was changed is not reused",
              packed_alpha.as_pointer() != straight.as_pointer() and packed_alpha.alpha_mode == 'STRAIGHT',
              str(names()))
        exr = os.path.join(scratch, "reuse.exr")
        probe = bpy.data.images.new("maxdrop-probe", 4, 4, float_buffer=True)
        probe.filepath_raw = exr
        probe.file_format = 'OPEN_EXR'
        probe.save()
        bpy.data.images.remove(probe)

        def build_exr(name):
            ir = cm.MaterialIR(32, name, "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
            ir.textures = {"base_color": tx.TextureGraphIR(
                tx.Image(1, "reuse.exr", "reuse.exr", "", ct.Found(exr, ct.SCENE), colorspace=other), tx.COLOR)}
            m = build_materials.MaterialBuilder().make(ir)
            return _from(_principled(m).inputs["Base Color"]).image

        first_exr = build_exr("ReuseExr")
        count = len(bpy.data.images)
        again_exr = build_exr("ReuseExr2")
        check("reuse: an EXR (premultiplied on load) is reused too", first_exr.alpha_mode == 'PREMUL'
              and again_exr.as_pointer() == first_exr.as_pointer() and len(bpy.data.images) == count, str(names()))
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        generated = bpy.data.images.new("Generated", 4, 4)
        generated.filepath_raw = png  # a generated image with a file name, never loaded from it
        base7 = build("ReuseG", tx.SRGB, tx.NON_COLOR)[0]
        check("reuse: a generated image is not reused", generated.source == 'GENERATED'
              and base7.as_pointer() != generated.as_pointer() and base7.source == 'FILE', str(names()))
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        blend = os.path.join(scratch, "library.blend")
        own = bpy.data.images.load(png, check_existing=False)
        own.colorspace_settings.name = tx.SRGB
        bpy.data.libraries.write(blend, {own}, path_remap='ABSOLUTE')
        library_name = own.name
        bpy.data.images.remove(own)
        with bpy.data.libraries.load(blend, link=True) as (_src, dst):
            dst.images = [library_name]
        linked = [i for i in bpy.data.images if i.library is not None]
        base8 = build("ReuseH", tx.SRGB, tx.NON_COLOR)[0]
        check("reuse: an image linked from a library is not reused", len(linked) == 1
              and os.path.normcase(bpy.path.abspath(linked[0].filepath, library=linked[0].library)) ==
              os.path.normcase(png) and linked[0].colorspace_settings.name == tx.SRGB
              and base8.as_pointer() != linked[0].as_pointer() and base8.library is None, str(names()))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        for lib in list(bpy.data.libraries):
            bpy.data.libraries.remove(lib)
        shutil.rmtree(scratch, ignore_errors=True)


def check_double_import():
    """vray_maps copied beside a PNG for each texture, imported twice into an emptied scene whose images stay: the
    second import adds no image datablock and its nodes take the first import's images."""
    fixtures = os.path.join(ROOT, "tests", "fixtures")
    scratch = tempfile.mkdtemp(prefix="maxdrop-twice-")
    try:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        src = os.path.join(fixtures, "vray_maps.max")
        dst = os.path.join(scratch, "vray_maps.max")
        shutil.copy(src, dst)
        _desc, plan = _irs(src)
        files = {img.name for s in plan.values() for irs in s.slots for ir in irs if ir is not None
                 for img in _images_of(ir)}
        os.makedirs(os.path.join(scratch, "maps"), exist_ok=True)
        for file in files:
            _write_png(os.path.join(scratch, "maps", file))

        def used():
            return {n.image.as_pointer() for m in bpy.data.materials for n in m.node_tree.nodes
                    if n.bl_idname == "ShaderNodeTexImage" and n.image is not None}

        check("twice: first import", bpy.ops.import_scene.maxdrop(filepath=dst) == {'FINISHED'})
        before = {i.as_pointer() for i in bpy.data.images}
        first = used()
        empty_scene()
        check("twice: second import", bpy.ops.import_scene.maxdrop(filepath=dst) == {'FINISHED'})
        after = {i.as_pointer() for i in bpy.data.images}
        check("twice: the second import adds no image datablock, its nodes use the first import's images",
              bool(first) and after == before and used() == first,
              "%d images before, %d after, %d used" % (len(before), len(after), len(first)))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)


def _crop_case(builder, cm, tx, found, name, mapping, crop):
    """A material whose base color is one cropped image: (its Image Texture node, the node feeding the crop
    Mapping)."""
    ir = cm.MaterialIR(20, name, "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
    img = tx.Image(1, "shared.png", "shared.png", "", found, mapping=mapping, crop=crop)
    ir.textures = {"base_color": tx.TextureGraphIR(img, tx.COLOR)}
    m = builder.make(ir)
    tex = _image_of(_principled(m).inputs["Base Color"])[0]
    return tex, _from(_from(tex.inputs["Vector"]).inputs["Vector"])


def check_builder_debt():
    """MaterialBuilder on hand-made IRs (bead maxdrop-em3.26): a crop repeats per axis as its tile and mirror say
    (wrap, ping-pong, clip); map channel 0 drawn on channel 1 and reported; a texture file without image data
    reported and left out; a material whose build raises is removed, its slot empty, the failure reported."""
    import dataclasses
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.convert import textures as ct
    empty_scene()
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    scratch = tempfile.mkdtemp(prefix="maxdrop-builder-debt-")
    try:
        png = os.path.join(scratch, "shared.png")
        _write_png(png)
        found = ct.Found(png, ct.SCENE)
        builder = build_materials.MaterialBuilder()
        crop = tx.Crop(0.25, 0.0, 0.5, 0.25)

        tex, comb = _crop_case(builder, cm, tx, found, "CropClip", tx.Mapping(tile=(False, False)), crop)
        chain = [_from(comb.inputs[a]) for a in ("X", "Y")]
        floors = [_from(n.inputs[0]) for n in chain]
        ks = [n.inputs[1].default_value for n in chain]
        check("builder debt: a crop with tile off: c + K floor(c) per axis, K = 1/w + 1 and 1/h + 1, image CLIP, "
              "no mask",
              tex.extension == 'CLIP' and all(n.operation == 'MULTIPLY_ADD' for n in chain) and not _clip_axes_of(tex)
              and all(f.operation == 'FLOOR' for f in floors) and close(ks, [3.0, 5.0], 1e-6)
              and all(_from(n.inputs[2]) == _from(f.inputs[0]) for n, f in zip(chain, floors))
              and _from(chain[0].inputs[2]).bl_idname == "ShaderNodeSeparateXYZ",
              "%s %s %s" % (tex.extension, [n.operation for n in chain], ks))
        # the formula itself (the nodes and K are checked above): the image coordinate the crop Mapping (POINT:
        # c * size + location) gives each cell coordinate c
        inside = []
        for size, loc, k in ((0.5, 0.25, ks[0]), (0.25, 0.75, ks[1])):
            for c in (-2.5, -0.01, 0.0, 0.3, 0.99, 1.0, 1.4, 7.0):
                x = (c + k * math.floor(c)) * size + loc
                inside.append((0.0 <= x <= 1.0) == (0.0 <= c < 1.0))
        check("builder debt: a clipped crop axis keeps the 0..1 cell in the image and sends every other c out",
              all(inside), str(inside))

        tex, comb = _crop_case(builder, cm, tx, found, "CropMirrorU",
                               tx.Mapping(tile=(True, True), mirror=(True, False)), crop)
        chain = [_from(comb.inputs[a]) for a in ("X", "Y")]
        double = _from(_from(chain[0].inputs[0]).inputs["Vector"])
        check("builder debt: a crop mirrored in U, tiled in V: U doubled, ping-pong on X, wrap 0..1 on Y, image "
              "EXTEND",
              tex.extension == 'EXTEND' and chain[0].operation == 'PINGPONG'
              and chain[0].inputs[1].default_value == 1.0 and chain[1].operation == 'WRAP'
              and chain[1].inputs[1].default_value == 1.0 and chain[1].inputs[2].default_value == 0.0
              and double.bl_idname == "ShaderNodeVectorMath" and double.operation == 'MULTIPLY'
              and close(list(_input(double, "Vector_001").default_value), [2.0, 1.0, 1.0], 1e-6),
              "%s %s %s" % (tex.extension, [n.operation for n in chain], double.bl_idname))

        tex, comb = _crop_case(builder, cm, tx, found, "CropMirrorNoTile",
                               tx.Mapping(tile=(False, False), mirror=(True, True)), crop)
        pings = [_from(comb.inputs[a]) for a in ("X", "Y")]
        chain = [n.operation for n in pings]
        double = _from(_from(pings[0].inputs[0]).inputs["Vector"])
        check("builder debt: mirror on with tile off still mirrors (mirror tiles), both axes doubled, image EXTEND",
              tex.extension == 'EXTEND' and chain == ['PINGPONG', 'PINGPONG']
              and double.bl_idname == "ShaderNodeVectorMath" and double.operation == 'MULTIPLY'
              and close(list(_input(double, "Vector_001").default_value), [2.0, 2.0, 1.0], 1e-6),
              "%s %s %s" % (tex.extension, chain, double.bl_idname))

        tex, comb = _crop_case(builder, cm, tx, found, "PlaceMixed", tx.Mapping(tile=(True, False)),
                               tx.Crop(0.25, 0.0, 0.5, 0.25, place=True))
        x, y = _from(comb.inputs["X"]), _from(comb.inputs["Y"])
        check("builder debt: a placed image tiled in U, clipped in V: wrap on X, V straight through, image EXTEND, "
              "the placed rectangle masked on both axes",
              tex.extension == 'EXTEND' and x.operation == 'WRAP' and y.bl_idname == "ShaderNodeSeparateXYZ"
              and comb.outputs["Vector"].links[0].to_node.vector_type == 'TEXTURE'
              and _clip_axes_of(tex) == ["X", "Y"], "%s %s %s %s" % (tex.extension, x.operation, y.bl_idname,
                                                                      _clip_axes_of(tex)))

        tex, frac = _crop_case(builder, cm, tx, found, "CropTile", tx.Mapping(), crop)
        check("builder debt: a crop tiled both ways: one Fraction, image EXTEND",
              tex.extension == 'EXTEND' and frac.bl_idname == "ShaderNodeVectorMath" and frac.operation == 'FRACTION',
              "%s %s" % (tex.extension, frac.bl_idname))

        tex, uv = _crop_case(builder, cm, tx, found, "PlaceClip", tx.Mapping(tile=(False, False)),
                             tx.Crop(0.25, 0.0, 0.5, 0.25, place=True))
        check("builder debt: a placed image with tile off: the UV straight into the TEXTURE Mapping, image CLIP",
              tex.extension == 'CLIP' and uv.bl_idname == "ShaderNodeTexCoord",
              "%s %s" % (tex.extension, uv.bl_idname))

        zero = tx.Image(5, "channel0.png", "channel0.png", "", found, mapping=tx.Mapping(channel=0))
        ir = cm.MaterialIR(21, "ChannelZero", "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
        ir.textures = {"base_color": tx.TextureGraphIR(zero, tx.COLOR),
                       "normal": tx.TextureGraphIR(tx.NormalMap(dataclasses.replace(zero, colorspace=tx.NON_COLOR),
                                                                1.0, channel=0), tx.NORMAL)}
        before = len(builder.issues())
        m = builder.make(ir)
        nodes = m.node_tree.nodes
        nm = next(n for n in nodes if n.bl_idname == "ShaderNodeNormalMap")
        new = builder.issues()[before:]
        check("builder debt: map channel 0 drawn on UV channel 1: no UV Map node, the normal map's default "
              "tangents, one report line", not any(n.bl_idname == "ShaderNodeUVMap" for n in nodes)
              and nm.uv_map == "" and new == [("material ChannelZero", "map channel 0 (vertex color) not imported: "
                                                                       "channel0.png on UV channel 1")], str(new))

        junk = os.path.join(scratch, "junk.png")
        with open(junk, "wb") as f:
            f.write(b"this is not an image at all")
        empty = os.path.join(scratch, "empty.jpg")
        open(empty, "wb").close()
        tga = os.path.join(scratch, "any.tga")
        with open(tga, "wb") as f:
            f.write(b"junk without a header")
        targa = os.path.join(scratch, "really_tga.png")  # an uncompressed 24-bit Targa header, 1 x 1
        with open(targa, "wb") as f:
            f.write(b"\x00\x00\x02" + bytes(9) + b"\x01\x00\x01\x00\x18\x00" + b"\x10\x20\x30")
        renamed = os.path.join(scratch, "really_png.jpg")
        shutil.copy(png, renamed)
        has = [build_materials.image_has_data(p) for p in (png, renamed, tga, targa, junk, empty)]
        check("builder debt: image_has_data: a PNG yes, a PNG named .jpg yes, any .tga (no signature) yes, a Targa "
              "named .png yes, text named .png no, an empty file no", has == [True, True, True, True, False, False],
              str(has))
        images = len(bpy.data.images)
        ir = cm.MaterialIR(22, "Undecodable", "test", base_color=cm.Input((0.2, 0.3, 0.4), cm.MapRef(1)))
        lost = tx.Image(6, "junk.png", "junk.png", "", ct.Found(junk, ct.SCENE))
        ir.textures = {"base_color": tx.TextureGraphIR(lost, tx.COLOR)}
        before = len(builder.issues())
        m = builder.make(ir)
        node = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage")
        base = _principled(m).inputs["Base Color"]
        new = builder.issues()[before:]
        check("builder debt: a texture file without image data: node without image, no datablock, the swatch, one "
              "report line", node.image is None and len(bpy.data.images) == images and not base.is_linked
              and close(list(base.default_value)[:3], [0.2, 0.3, 0.4], 1e-6)
              and new == [("material Undecodable", "texture not loaded: junk.png (no image data)")], str(new))

        original = build_materials._Tree.build

        def failing(self):
            raise RuntimeError("maxdrop test: tree fails")

        build_materials._Tree.build = failing
        try:
            materials = len(bpy.data.materials)
            got = builder.make(cm.MaterialIR(23, "Broken", "test"))
        finally:
            build_materials._Tree.build = original
        new = builder.issues()[-1]
        check("builder debt: a material whose build raises: None, removed again, reported, not counted",
              got is None and len(bpy.data.materials) == materials and "Broken" not in bpy.data.materials
              and new == ("material Broken", "material not built (RuntimeError: maxdrop test: tree fails)")
              and builder.classes["test"] == 8, "%s %s %s" % (got, new, dict(builder.classes)))
    finally:
        empty_scene()
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)
        shutil.rmtree(scratch, ignore_errors=True)
