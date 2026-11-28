# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of the builder's volumes, the fixtures' materials, falloff curves, curve steps, the wrappers'
report and vray_maps' nodes."""
import json
import os
import shutil
import tempfile

import bpy

from .core import check, close, empty_scene, ROOT
from .tables import VALUE_TOLERANCE
from .nodes import _bsdfs, _decoded, _expected_mapping, _from, _input, _irs, _mapping_of, _meaned, _principled
from .checks_materials import check_medium, check_principled


def check_builder_volume():
    """Corona media (bead maxdrop-em3.163) drawn by MaterialBuilder and rendered in Cycles: a slab 10 m thick over an
    emitter of radiance 1, seen straight through by an orthographic camera, lets 0.8 / 0.5 / 0.2 through for an
    absorption color of 0.8 / 0.5 / 0.2 at 10 m (Corona 12 renders the color at its distance); an emission-only slab
    of 1 / 0.5 / 0.25 over 10 m adds that over 10 m and 0.5 times it over 5 m; a volume-only material (alpha 0, no
    medium) lets the emitter through unchanged; a medium of all three parts is built as check_medium reads it.
    maxdrop-6n0.6.29: a volume-only material with a medium leaves Surface unlinked, keeps the default render method
    and a viewport alpha of VOLUME_VIEWPORT_ALPHA; one with a surface, or alpha 0 without a medium, keeps its
    Principled BSDF on Surface and a viewport alpha of 1, as does alpha 0 with a medium under an alpha map or with a
    layer (not volume-only); a medium that scatters is a VOLUME_BOUNCES issue, not with single bounce on; six
    stacked 1 m slabs of a near-clear volume-only material let 0.9^0.06 through (an Alpha-0 Principled BSDF spends
    two of Cycles' 8 transparent bounces per slab: black)."""
    import dataclasses
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    empty_scene()
    class Meters:  # the converter's one attribute corona_medium reads: 1 m per world unit
        meters = 1.0
    absorb = cm.corona_medium(Meters, (0.8, 0.5, 0.2), 10.0, (0.0, 0.0, 0.0), 0.0)
    emit = cm.corona_medium(Meters, (1.0, 1.0, 1.0), 0.0, (0.0, 0.0, 0.0), 0.0, (1.0, 0.5, 0.25), 10.0)
    full = cm.corona_medium(Meters, (0.5, 0.25, 0.75), 2.0, (0.5, 1.0, 0.0), 0.4, (0.1, 0.2, 0.3), 4.0)
    irs = {"absorb": cm.MaterialIR(70, "MediumAbsorb", "test", base_color=cm.Input((1.0, 1.0, 1.0)),
                                       roughness=cm.Input(0.0), transmission=cm.Input(1.0), ior=1.0, medium=absorb),
           "emit": cm.MaterialIR(71, "MediumEmit", "test", alpha=cm.Input(0.0), medium=emit),
           "full": cm.MaterialIR(72, "MediumFull", "test", alpha=cm.Input(0.0), medium=full),
           "none": cm.MaterialIR(73, "MediumNone", "test", alpha=cm.Input(0.0)),
           "thin": cm.MaterialIR(74, "MediumThin", "test", alpha=cm.Input(0.0),
                                 medium=cm.corona_medium(Meters, (0.9, 0.9, 0.9), 100.0, (0.0, 0.0, 0.0), 0.0)),
           "single": cm.MaterialIR(75, "MediumSingle", "test", alpha=cm.Input(0.0),
                                   medium=dataclasses.replace(full, single=True)),
           "mapped": cm.MaterialIR(76, "MediumMapped", "test", alpha=cm.Input(0.0, cm.MapRef(1)), medium=absorb),
           "layered": cm.MaterialIR(77, "MediumLayered", "test", alpha=cm.Input(0.0), medium=absorb,
                                    layers=[cm.Layer(cm.MaterialIR(78, "MediumLayer", "test"), 0.5)])}
    irs["mapped"].textures = {"alpha": tx.TextureGraphIR(tx.Invert(tx.Constant(0.5)), tx.DATA)}
    builder = build_materials.MaterialBuilder()
    built = {k: builder.make(ir) for k, ir in irs.items()}
    scene = bpy.context.scene
    settings = ((scene.render, ("engine", "resolution_x", "resolution_y", "resolution_percentage", "filepath")),
                (scene.render.image_settings, ("file_format",)), (scene.view_settings, ("view_transform",)),
                (scene.cycles, ("samples", "use_denoising")))
    saved = (scene.camera, scene.world, [(o, a, getattr(o, a)) for o, names in settings for a in names])
    scratch = tempfile.mkdtemp(prefix="maxdrop-volume-")
    path = os.path.join(scratch, "slabs.exr")
    try:
        for k, ir in irs.items():
            check("volume (%s): material built" % k, built[k] is not None)
            if built[k] is not None:
                check_medium("volume (%s)" % k, built[k], ir)
        if any(m is None for m in built.values()):
            return
        for k, m in built.items():
            out = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
            surface = _from(out.inputs["Surface"])
            if k in ("emit", "full", "thin", "single"):
                check("volume (%s): volume-only: Surface unlinked, the default render method, viewport alpha %g"
                      % (k, build_materials.VOLUME_VIEWPORT_ALPHA), surface is None and m.surface_render_method
                      == 'DITHERED' and abs(m.diffuse_color[3] - build_materials.VOLUME_VIEWPORT_ALPHA) < 1e-6,
                      "%s %s %s" % (surface, m.surface_render_method, tuple(m.diffuse_color)))
            else:
                shader = "ShaderNodeMixShader" if k == "layered" else "ShaderNodeBsdfPrincipled"
                check("volume (%s): its %s on Surface, viewport alpha 1" % (k, shader[10:]), surface is not None
                      and surface.bl_idname == shader and m.diffuse_color[3] == 1.0,
                      "%s %s" % (surface, tuple(m.diffuse_color)))
        lines = [(label, r) for label, r in builder.issues() if r == build_materials.VOLUME_BOUNCES]
        check("volume: the Volume Bounces line for the medium that scatters only, not with single bounce on",
              lines == [("material " + built["full"].name, build_materials.VOLUME_BOUNCES)], str(builder.issues()))
        from maxdrop import compat
        world = bpy.data.worlds.new("MediumWorld")
        compat.node_tree(world).nodes["Background"].inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
        scene.world = world
        light = bpy.data.materials.new("MediumEmitter")
        tree = compat.node_tree(light)
        tree.nodes.clear()
        e = tree.nodes.new("ShaderNodeEmission")
        e.inputs["Strength"].default_value = 1.0
        tree.links.new(e.outputs[0], tree.nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
        mesh = bpy.data.meshes.new("MediumEmitter")
        mesh.from_pydata([(-200, -100, -50), (200, -100, -50), (200, 100, -50), (-200, 100, -50)], [], [(0, 1, 2, 3)])
        mesh.materials.append(light)
        bpy.context.collection.objects.link(bpy.data.objects.new("MediumEmitter", mesh))
        slabs = (("absorb", 10.0, -150.0), ("emit", 10.0, -75.0), ("emit", 5.0, 0.0), ("none", 10.0, 75.0))
        for k, h, x in slabs:
            box = bpy.data.meshes.new("MediumSlab")
            v = [(x - 20 + 40 * i, -20 + 40 * j, h * z) for z in (0, 1) for j in (0, 1) for i in (0, 1)]
            box.from_pydata(v, [], [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2),
                                    (1, 3, 7, 5)])
            box.materials.append(built[k])
            bpy.context.collection.objects.link(bpy.data.objects.new("MediumSlab", box))
        for z in range(0, 12, 2):  # six 1 m slabs, 12 crossings: past Cycles' 8 transparent bounces
            box = bpy.data.meshes.new("MediumStack")
            v = [(130 + 40 * i, -20 + 40 * j, z + c) for c in (0, 1) for j in (0, 1) for i in (0, 1)]
            box.from_pydata(v, [], [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2),
                                    (1, 3, 7, 5)])
            box.materials.append(built["thin"])
            bpy.context.collection.objects.link(bpy.data.objects.new("MediumStack", box))
        cam = bpy.data.cameras.new("MediumCamera")
        cam.type, cam.ortho_scale, cam.clip_end = 'ORTHO', 400.0, 1000.0
        cob = bpy.data.objects.new("MediumCamera", cam)
        cob.location = (0.0, 0.0, 300.0)
        bpy.context.collection.objects.link(cob)
        scene.camera = cob
        scene.render.engine = 'CYCLES'
        scene.cycles.samples, scene.cycles.use_denoising = 16, False
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 80, 20, 100
        scene.view_settings.view_transform = 'Standard'
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(path)
        px = list(img.pixels)
        bpy.data.images.remove(img)

        def at(x):  # the frame is 400 m wide on 80 px, 5 m a pixel; row 10 of 20 is y 0 to 5
            col = int(round(40 + x / 5.0))
            k = (10 * 80 + col) * 4
            return px[k:k + 3]
        wants = ((-150.0, [0.8, 0.5, 0.2], "absorption 0.8 / 0.5 / 0.2 at 10 m: the color"),
                 (-75.0, [2.0, 1.5, 1.25], "emission 1 / 0.5 / 0.25 over 10 m on the emitter's 1"),
                 (0.0, [1.5, 1.25, 1.125], "the same emission over 5 m: half"),
                 (75.0, [1.0, 1.0, 1.0], "a volume-only material without a medium: nothing"),
                 (150.0, [0.9 ** 0.06] * 3, "six stacked 1 m slabs of absorption 0.9 at 100 m: 0.9^0.06"))
        for x, want, what in wants:
            got = at(x)
            check("volume Cycles render: " + what, close(list(got), want, 0.01), "%s vs %s" % (list(got), want))
    finally:
        scene.camera, scene.world = saved[:2]
        for o, a, v in saved[2]:
            setattr(o, a, v)
        shutil.rmtree(scratch, ignore_errors=True)
        empty_scene()


def check_fixture_materials(name, plan, desc, obs):
    """Each face slot of each imported object holds a material equal to the IR the same file converts to (plan:
    the slot plan of _irs)."""
    by_index = {node.index: ob for node, ob in zip(desc.nodes, obs)}
    checked = set()
    corona = []
    for slots in list(plan.values()) + list(plan.curves.values()):
        for s, irs in enumerate(slots.slots):
            for node, ir in zip(slots.users, irs):
                ob = by_index[node]
                material = ob.material_slots[s].material if s < len(ob.material_slots) else None
                if ir is None:
                    check("%s/%s: slot %d empty" % (name, ob.name, s), material is None)
                    continue
                if material is None or material.name in checked:
                    check("%s/%s: slot %d has a material" % (name, ob.name, s), material is not None)
                    continue
                checked.add(material.name)
                check("%s/%s: material named after the 3ds Max material" % (name, material.name),
                      material.name.split(".")[0] == (ir.name or "Material").split(".")[0], ir.name)
                check_principled("%s/%s" % (name, material.name), material, ir)
                if ir.source == "CoronaPhysicalMtl":
                    corona.append(material)
    if name == "corona_physical":  # absolute: check_principled follows the IR, which drew 0.25 (maxdrop-em3.121)
        sockets = [(m.name, n.inputs["Specular IOR Level"]) for m in corona for n in _bsdfs(m)]
        levels = [(name, s.is_linked, round(s.default_value, 6)) for name, s in sockets]
        check("corona_physical: every CoronaPhysicalMtl reflects the IOR's own Fresnel (Specular IOR Level 0.5)",
              len(levels) >= 3 and all(not linked and v == 0.5 for _n, linked, v in levels), str(levels))
    for key, cd in desc.curves.items():  # each spline on its slot; without a plan, 0
        ob = next((by_index[u] for u in cd.users if u in by_index), None)
        if ob is None:
            continue
        got = [sp.material_index for sp in ob.data.splines]
        want = plan.curves[key].indices.tolist() if key in plan.curves else [0] * len(cd.splines)
        check("%s/%s: each spline on its material's slot" % (name, ob.name), got == want, "%s vs %s" % (got, want))
    if name == "corona_classes":  # a shadow catcher only where every slot is a CoronaShadowCatcherMtl
        catchers = sorted(ob.name for ob in obs if ob.is_shadow_catcher)
        check("corona_classes: the shadow-catcher boxes are shadow catchers, the mixed box and the others not",
              catchers == ["FixtureCoronaShadowCatcherBox", "FixtureCoronaShadowCatcherReflBox"], str(catchers))
    if name == "pblock_animated":  # absolute: the controllers' frame-0 values (the oracle's), not the defaults
        animated = bpy.data.materials.get("FixtureAnimVRay")
        bsdf = _bsdfs(animated)[0] if animated is not None and _bsdfs(animated) else None

        def decoded(c):  # the fixture is saved with the gamma off: a swatch is decoded from sRGB
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        want = [decoded(c / 255.0) for c in (10, 20, 30)]
        got = list(bsdf.inputs["Base Color"].default_value)[:3] if bsdf is not None else None
        check("pblock_animated: FixtureAnimVRay's animated diffuse at its frame-0 color (10, 20, 30)",
              got is not None and all(abs(a - b) < 1e-4 for a, b in zip(got, want)), "%s vs %s" % (got, want))
        rough = bsdf.inputs["Roughness"].default_value if bsdf is not None else None
        check("pblock_animated: FixtureAnimVRay's animated glossiness at its frame-0 0.41 (roughness 0.59)",
              rough is not None and abs(rough - 0.59) < 1e-4, str(rough))
    if name == "falloff_curve":
        check_falloff_curve(textured=False)
    if name == "vray_maps":
        check_vray_maps_nodes(textured=False)
        text = bpy.data.texts.get("MaxDrop Report")
        lines = text.as_string().split("\n") if text else []
        names = sorted(("fixture_diffuse.png", "fixture_reflect.png", "fixture_gloss.png", "fixture_bump.png",
                        "fixture_opacity.png", "fixture_normal.png", "fixture_normal_bump.png"), key=str.casefold)
        at = lines.index("  Textures not found: 7") if "  Textures not found: 7" in lines else -1
        check("vray_maps: the report names each texture not found, once, by file name",
              at >= 0 and lines[at + 1:at + 8] == ["    " + n for n in names], "\n".join(lines[-14:]))
        empty = [n.label for m in bpy.data.materials for n in m.node_tree.nodes
                 if n.bl_idname == "ShaderNodeTexImage" and n.image is not None]
        check("vray_maps: texture nodes without an image when the files are missing", empty == [], str(empty))


def check_falloff_curve(textured):
    """falloff_curve imported: each edited Falloff curve is a Float Curve on the Falloff's ratio that evaluates as 3ds
    Max 2020 does (tests/fixtures/falloff_curve.curves.jsonl, x = k / 64) and drives an unclamped Mix; the default
    curve makes none. FixtureCurveJump's two points at one x (a falling jump) stay in their order and the curve
    evaluates as that polyline on either side of the jump. Each Mix's Use Curve: textured, a Map Range SMOOTHSTEP
    (lower < upper) or a step (1 - LESS_THAN) over its mask; without the mask's file, the mix amount through the
    curve (mix_factor; 3ds Max's own factor at that amount, the jsonl's "amount")."""
    from maxdrop.convert import texmaps as tx

    with open(os.path.join(ROOT, "tests", "fixtures", "falloff_curve.curves.jsonl"), encoding="ascii") as f:
        records = {r["name"]: r for r in map(json.loads, f)}
    rows = {name: r["y"] for name, r in records.items()}
    ratios = {"FixtureCurveBezier": "ShaderNodeLayerWeight", "FixtureCurveCorner": "ShaderNodeMath",
              "FixtureCurveOvershoot": "ShaderNodeFresnel", "FixtureCurveClamped": "ShaderNodeLayerWeight",
              "FixtureCurveJump": "ShaderNodeLayerWeight"}
    for name, ratio in ratios.items():
        # the gamma-off fixture: the Falloff mixed as stored under a Gamma node of 2.2 (maxdrop-6n0.6.18)
        mix = _decoded(_from(_principled(bpy.data.materials[name]).inputs["Base Color"]))
        check("falloff_curve/%s: under a Gamma node of 2.2" % name, mix is not None and mix.bl_idname == "ShaderNodeMix")
        if mix is None:
            continue
        fc = _from(_input(mix, "Factor_Float"))
        ok = fc is not None and fc.bl_idname == "ShaderNodeFloatCurve"
        check("falloff_curve/%s: a Float Curve drives the Mix, unclamped" % name,
              ok and not mix.clamp_factor and _from(_input(fc, "Value")).bl_idname == ratio
              and abs(_input(fc, "Factor").default_value - 1.0) < 1e-6,
              "%s %s" % (getattr(fc, "bl_idname", None), getattr(mix, "clamp_factor", None)))
        if ok:
            mapping = fc.mapping
            mapping.initialize()
            err = max(abs(mapping.evaluate(mapping.curves[0], k / 64.0) - y) for k, y in enumerate(rows[name]))
            check("falloff_curve/%s: the Float Curve evaluates as 3ds Max's curve, within 0.001" % name, err < 1e-3,
                  str(err))
            if name == "FixtureCurveJump" and not textured:  # the same curve in both runs: checked once
                check_falloff_jump(mapping, 32.5 / 64)
    linear = bpy.data.materials["FixtureCurveLinear"]
    check("falloff_curve: the default curve makes no Float Curve",
          not any(n.bl_idname == "ShaderNodeFloatCurve" for n in linear.node_tree.nodes)
          and _from(_input(_decoded(_from(_principled(linear).inputs["Base Color"])), "Factor_Float")).bl_idname
          == "ShaderNodeLayerWeight")
    from maxdrop.convert import colors
    amount = _principled(bpy.data.materials["FixtureMixCurveAmount"]).inputs["Base Color"]
    want = colors.srgb_to_linear(0.15625)  # black to white, gamma off: mixed as stored, shown decoded (em3.158)
    check("falloff_curve: a Mix's Use Curve folded into its amount (0.4 -> 0.15625), shown decoded",
          not amount.is_linked and close(list(amount.default_value)[:3], [want] * 3, 1e-4),
          "%s %s" % (amount.is_linked, list(amount.default_value)))
    # mix amount, lower, upper of each masked Mix (tools/fixtures/falloff_curve.ms)
    masked = {"FixtureMixCurve": (0.5, 0.2, 0.9), "FixtureMixCurveStep": (0.7, 0.6, 0.4)}
    for name, kind in (("FixtureMixCurve", "SMOOTHSTEP"), ("FixtureMixCurveStep", "STEP")):
        mix = _decoded(_from(_principled(bpy.data.materials[name]).inputs["Base Color"]))
        check("falloff_curve/%s: the gamma-off color Mix under a Gamma node of 2.2 (maxdrop-em3.158)" % name,
              mix is not None and mix.bl_idname == "ShaderNodeMix")
        if mix is None:
            continue
        factor = _from(_input(mix, "Factor_Float"))
        if not textured:
            want = tx.mix_factor(*masked[name])
            got = _input(mix, "Factor_Float").default_value
            check("falloff_curve/%s: without its mask's file, the mix amount through the curve (%.5f)" % (name, want),
                  factor is None and want > 0.0 and abs(got - want) < 1e-4
                  and abs(got - records[name]["amount"]) < 1e-3, "%s %s" % (getattr(factor, "bl_idname", None), got))
            continue
        if kind == "SMOOTHSTEP":
            ok = factor is not None and factor.bl_idname == "ShaderNodeMapRange" and \
                factor.interpolation_type == 'SMOOTHSTEP' and factor.clamp and \
                close([_input(factor, k).default_value for k in ("From Min", "From Max", "To Min", "To Max")],
                      [0.2, 0.9, 0.0, 1.0], 1e-6)
        else:  # 1 - LESS_THAN(mask, lower)
            less = _from(factor.inputs[1]) if factor is not None and factor.bl_idname == "ShaderNodeMath" else None
            ok = less is not None and factor.operation == 'SUBTRACT' and factor.inputs[0].default_value == 1.0 \
                and less.operation == 'LESS_THAN' and abs(less.inputs[1].default_value - 0.6) < 1e-6
            factor = less
        image = _from(_input(factor, "Value") if kind == "SMOOTHSTEP" else factor.inputs[0]) if factor else None
        check("falloff_curve/%s: Use Curve as a %s over its mask image" % (name, kind),
              ok and image is not None and image.bl_idname in ("ShaderNodeTexImage", "ShaderNodeVectorMath"),
              "%s %s" % (getattr(factor, "bl_idname", None), getattr(image, "bl_idname", None)))


def check_falloff_jump(mapping, x):
    """falloff_curve's FixtureCurveJump as a Float Curve: the convert side's Remap points (two at x, (x, 0.8) then
    (x, 0.3)), kept in that order, and the curve evaluates as that polyline 0.005 and 0.01 away from the jump (nearer,
    Blender's table of 256 steps over 0..1 draws the jump across one step, as check_curve_step skips 0.005 there)."""
    _desc, plan = _irs(os.path.join(ROOT, "tests", "fixtures", "falloff_curve.max"))
    ir = next(ir for p in plan.values() for irs in p.slots for ir in irs
              if ir is not None and ir.name == "FixtureCurveJump")
    pts = list(ir.textures["base_color"].root.input.mask.points)  # the gamma-off Falloff under its Decode
    stored = [tuple(p.location) for p in mapping.curves[0].points]
    at = [p for p in pts if abs(p[0] - x) < 1e-6]
    check("falloff_curve/FixtureCurveJump: the convert side's points, the two at the jump in their order (0.8, 0.3)",
          len(at) == 2 and abs(at[0][1] - 0.8) < 1e-6 and abs(at[1][1] - 0.3) < 1e-6 and len(stored) == len(pts)
          and all(close(a, b, 1e-6) for a, b in zip(stored, pts)),
          "%s, at the jump %s" % (len(stored), [p for p in stored if abs(p[0] - x) < 1e-6]))

    def polyline(u):
        if u <= pts[0][0]:
            return pts[0][1]
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            if xa <= u < xb:
                return ya + (yb - ya) * (u - xa) / (xb - xa)
        return pts[-1][1]

    err = max(abs(mapping.evaluate(mapping.curves[0], x + d) - polyline(x + d)) for d in (-0.01, -0.005, 0.005, 0.01))
    check("falloff_curve/FixtureCurveJump: evaluates as the convert polyline on either side of the jump, within 0.001",
          err < 1e-3, str(err))


def check_curve_step():
    """A Remap with two points at one x (curve_samples' vertical step: a segment with no width) as a Float Curve:
    the points stay in their order, also when the step is the first two points (set, not added) or comes out of
    curve_samples, and the curve evaluates as the polyline on either side of the step (at the step x itself
    either side is right) and flat past the ends."""
    from maxdrop.build import materials as build_materials
    from maxdrop.convert import materials as cm
    from maxdrop.convert import texmaps as tx
    from maxdrop.reader.materials import CurvePoint

    def polyline(points, x):
        if x <= points[0][0]:
            return points[0][1]
        for (xa, ya), (xb, yb) in zip(points, points[1:]):
            if xa <= x < xb:
                return ya + (yb - ya) * (x - xa) / (xb - xa)
        return points[-1][1]

    corner = [CurvePoint((0.0, 1.0), (0.0, 1.0), (0.2, 1.0), 0), CurvePoint((0.5, 0.9), (0.4, 0.9), (0.5, 0.9), 0),
              CurvePoint((0.5, 0.1), (0.5, 0.1), (0.6, 0.1), 0), CurvePoint((1.0, 0.0), (0.9, 0.0), (1.0, 0.0), 0)]
    cases = (("falling step", ((0.0, 1.0), (0.5, 0.9), (0.5, 0.1), (1.0, 0.0))),
             ("rising step", ((0.0, 0.0), (0.5, 0.2), (0.5, 0.8), (1.0, 1.0))),
             ("step in the first two points", ((0.2, 0.9), (0.2, 0.1), (1.0, 0.0))),
             ("step from curve_samples", tx.curve_samples(corner)))
    empty_scene()
    builder = build_materials.MaterialBuilder()
    for label, points in cases:
        ir = cm.MaterialIR(1, "CurveStep", "test", base_color=cm.Input((0.5, 0.5, 0.5), cm.MapRef(1)))
        mix = tx.Mix(tx.Constant((0.0, 0.0, 0.0)), tx.Constant((1.0, 1.0, 1.0)), 0.0, tx.Remap(tx.Facing(), points))
        ir.textures = {"base_color": tx.TextureGraphIR(mix, tx.COLOR)}
        material = builder.make(ir)
        fc = next((n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeFloatCurve"), None) \
            if material is not None else None
        if fc is None:
            check("curve step/%s: a Float Curve" % label, False)
            continue
        mapping = fc.mapping
        mapping.initialize()
        stored = [tuple(p.location) for p in mapping.curves[0].points]
        steps = [a[0] for a, b in zip(points, points[1:]) if a[0] == b[0]]
        check("curve step/%s: the points kept in their order" % label,
              len(stored) == len(points) and all(close(a, b, 1e-6) for a, b in zip(stored, points)),
              "%d points, at the step %s" % (len(stored), [p for p in stored if any(abs(p[0] - s) < 1e-6
                                                                                 for s in steps)]))
        xs = [k / 64.0 for k in range(-4, 69)] + [x + d for x in steps for d in (-0.01, 0.01)]
        err = max(abs(mapping.evaluate(mapping.curves[0], x) - polyline(points, x)) for x in xs
                  if all(abs(x - s) > 0.005 for s in steps))
        check("curve step/%s: evaluates as the polyline beside the step, within 0.001" % label, err < 1e-3, str(err))


def check_wrappers_report():
    """Right after the operator imported vray_wrappers: the text MaxDrop Report counts the materials and lists the
    wrappers it peeled by class (not the VRayBlendMtl, whose coats are layers: maxdrop-o53.1.6, nor the VRay2SidedMtl,
    which lets light through: maxdrop-o53.1.7), and the summary warns about them."""
    text = bpy.data.texts.get("MaxDrop Report")
    lines = text.as_string().split("\n") if text else []
    check("vray_wrappers: the report counts the materials built",
          any(line.startswith("Materials built: ") for line in lines), "\n".join(lines))
    check("vray_wrappers: the report lists the peeled wrappers by class",
          "  Wrappers peeled to their sub-material, by class: Shell Material 1"
          in lines and lines.index("Approximated:") < lines.index(
              "  Wrappers peeled to their sub-material, by class: Shell Material 1"),
          "\n".join(lines))


def check_vray_maps_nodes(textured):
    """FixtureVRayMaps' bitmaps: tiling, offset and W angle as Mapping values (the authoring script's numbers),
    extension REPEAT. With its textures: the gloss map's mean inverted (1 - x) into the Mix of the roughness, the bump
    map's mean a Bump node's height, FixtureVRayNormal's Normal Map node (strength 0.85, its green flipped) under its
    bump map's Bump node. Without them: no Normal Map node and the Normal input free."""
    m = bpy.data.materials.get("FixtureVRayMaps")
    for file, tile, offset, angle in (("fixture_diffuse.png", 2.0, 0.1, 15.0), ("fixture_reflect.png", 3.0, 0.2, 25.0),
                                      ("fixture_gloss.png", 4.0, 0.3, 35.0), ("fixture_bump.png", 5.0, 0.4, 45.0),
                                      ("fixture_opacity.png", 6.0, 0.5, 55.0)):
        got, tex = _mapping_of(m, file)
        want = _expected_mapping((tile, tile + 0.5), (offset, offset + 0.05), angle)
        ok = got is not None and all(close(g, w, VALUE_TOLERANCE) for g, w in zip(got, want))
        check("vray_maps/%s: Mapping location, rotation, scale" % file, ok, "%s vs %s" % (got, want))
        check("vray_maps/%s: extension REPEAT" % file, tex.extension == 'REPEAT', tex.extension)
    n = bpy.data.materials.get("FixtureVRayNormal")
    if not textured:
        check("vray_maps without textures: no Normal Map node, the Normal input free",
              not any(x.bl_idname == "ShaderNodeNormalMap" for x in n.node_tree.nodes)
              and not _principled(n).inputs["Normal"].is_linked)
        return
    mix = _from(_principled(m).inputs["Roughness"])
    inv = _from(_input(mix, "B_Float")) if mix is not None and mix.bl_idname == "ShaderNodeMix" else None
    gloss = _meaned(inv.inputs[1]) if inv is not None and inv.bl_idname == "ShaderNodeMath" else None
    check("vray_maps: the gloss map as 1 - its mean into the roughness Mix at 73 %, glossiness 1 beside it",
          gloss is not None and gloss.label == "fixture_gloss.png" and inv.operation == 'SUBTRACT'
          and abs(inv.inputs[0].default_value - 1.0) < 1e-6 and abs(_input(mix, "Factor_Float").default_value - 0.73)
          < 1e-5 and abs(_input(mix, "A_Float").default_value) < 1e-6)
    bump = _from(_principled(m).inputs["Normal"])
    check("vray_maps: the bump map through a Bump node of strength 0.64",
          bump is not None and bump.bl_idname == "ShaderNodeBump" and not bump.invert
          and abs(bump.inputs["Strength"].default_value - 0.64) < 1e-5
          and getattr(_meaned(bump.inputs["Height"]), "label", None) == "fixture_bump.png")
    top = _from(_principled(n).inputs["Normal"])
    nm = _from(top.inputs["Normal"]) if top is not None and top.bl_idname == "ShaderNodeBump" else None
    comb = _from(nm.inputs["Color"]) if nm is not None and nm.bl_idname == "ShaderNodeNormalMap" else None
    green = _from(comb.inputs["Green"]) if comb is not None and comb.bl_idname == "ShaderNodeCombineColor" else None
    sep = _from(green.inputs[1]) if green is not None and green.bl_idname == "ShaderNodeMath" else None
    check("vray_maps: FixtureVRayNormal: Bump (its bump map) over a Normal Map node of strength 0.85, green 1 - G",
          sep is not None and sep.bl_idname == "ShaderNodeSeparateColor"
          and green.inputs[1].links[0].from_socket.identifier == "Green"
          and _from(comb.inputs["Red"]) == sep and abs(nm.inputs["Strength"].default_value - 0.85) < 1e-5
          and getattr(_meaned(top.inputs["Height"]), "label", None) == "fixture_normal_bump.png"
          and _from(sep.inputs["Color"]).label == "fixture_normal.png")
