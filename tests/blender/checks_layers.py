# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of layers, shear, material and curve slots and creases on open edges."""
import os

import bpy
from mathutils import Matrix

from .core import build_scene, check, empty_scene, failures, ROOT, world_of


def check_layers_more(root, obs, view_layer):
    """layers_more as 3ds Max saved it: the flags of a hidden and a frozen layer go on their collections, not on their
    objects; a non-rendering layer's collection renders (its node is By Object, which 3ds Max renders); the child
    layer sits below its parent (which holds no node); a hidden parent leaves its child visible."""
    text = "FixtureLäyer中"
    check("layers_more: the layer collections, the child layer below its parent",
          [c.name for c in root.children] == ["0", "FixtureHiddenLayer", "FixtureFrozenLayer", "FixtureNoRenderLayer",
                                              "FixtureParentLayer", text]
          and [c.name for c in root.children["FixtureParentLayer"].children] == ["FixtureChildLayer"],
          str([c.name for c in root.children]))
    lcs = view_layer.layer_collection.children[root.name].children
    excluded = [lc.name for lc in lcs if lc.exclude]
    check("layers_more: the hidden layer excluded in the view layer", excluded == ["FixtureHiddenLayer"], str(excluded))
    flags = {c.name: (c.hide_select, c.hide_render) for c in root.children_recursive}
    want = {c: (c == "FixtureFrozenLayer", False) for c in flags}
    check("layers_more: hide_select on the frozen layer's collection, no hide_render on the non-rendering one's",
          flags == want, str(flags))
    visible = {ob.name for ob in view_layer.objects}
    check("layers_more: only the hidden layer's object is out of the view layer",
          {ob.name for ob in obs} - visible == {"FixtureOnHiddenLayer"}, str(sorted(visible)))
    own = {ob.name: (ob.hide_get(view_layer=view_layer), ob.hide_select, ob.hide_render) for ob in obs
           if ob.name in visible}
    check("layers_more: only the nodes' own flags on objects (FixtureHiddenParent hidden, FixtureFrozen frozen)",
          {k: v for k, v in own.items() if any(v)} == {"FixtureHiddenParent": (True, False, False),
                                                       "FixtureFrozen": (False, True, False)}, str(own))
    child = bpy.data.objects["FixtureVisibleChild"]
    check("layers_more: the hidden parent's child is visible, its child in Blender",
          child.parent is bpy.data.objects["FixtureHiddenParent"] and child.visible_get(view_layer=view_layer))


def check_layers_render(root, obs):
    """layers_render: Rendering Control By Layer. A By Layer node takes Renderable and Cast Shadows from its own layer
    (not from a parent layer, FixtureByLayerChild), a By Object node on the same layer keeps its own; no layer's
    collection gets hide_render."""
    check("layers_render: no collection with hide_render", not any(c.hide_render for c in root.children_recursive),
          str([c.name for c in root.children_recursive if c.hide_render]))
    no_render = sorted(ob.name for ob in obs if ob.hide_render)
    check("layers_render: only FixtureByLayerNoRender has hide_render", no_render == ["FixtureByLayerNoRender"],
          str(no_render))
    no_shadow = sorted(ob.name for ob in obs if not ob.visible_shadow)
    check("layers_render: only FixtureByLayerNoCast casts no shadows", no_shadow == ["FixtureByLayerNoCast"],
          str(no_shadow))


def check_layers_nested(root, obs, view_layer, oracle):
    """layers_nested as 3ds Max saved it: the flag sits on the parent layer only, and the layers below (one and two
    levels down) are hidden or frozen with it, as the oracle's layer flags (MAXScript's) say. Excluding a parent's
    collection leaves out the collections below it; hide_select on a parent's reaches them too."""
    flags = {la["name"]: la for la in oracle["layers"]}
    by_layer = {o["name"]: flags[o["layer"]] for o in oracle["nodes"]}
    want_out = {k for k, la in by_layer.items() if la["hidden"]}
    want_frozen = {k for k, la in by_layer.items() if la["frozen"]}
    check("layers_nested: the oracle calls the layers below a hidden or frozen parent hidden or frozen",
          want_out == {"FixtureUnderHiddenParent", "FixtureDeepNested"} and want_frozen == {"FixtureUnderFrozenParent"},
          "%s %s" % (sorted(want_out), sorted(want_frozen)))
    lcs = view_layer.layer_collection.children[root.name].children
    excluded = [lc.name for lc in lcs if lc.exclude]
    check("layers_nested: the hidden parent layers' collections excluded",
          excluded == ["FixtureHiddenParentLayer", "FixtureTopLayer"], str(excluded))
    check("layers_nested: hide_select on the frozen parent layer's collection only",
          [c.name for c in root.children_recursive if c.hide_select] == ["FixtureFrozenParentLayer"]
          and not any(c.hide_render for c in root.children_recursive))
    visible = {ob.name for ob in view_layer.objects}
    names = {ob.name for ob in obs}
    check("layers_nested: the objects below a hidden parent layer are out of the view layer",
          names - visible == want_out, str(sorted(names - visible)))
    shown = [ob for ob in obs if ob.name in visible]
    check("layers_nested: no object carries a flag of its own",
          not any(ob.hide_get(view_layer=view_layer) or ob.hide_select or ob.hide_render for ob in shown))
    for ob in shown:
        ob.select_set(True, view_layer=view_layer)
    picked = {ob.name for ob in shown if ob.select_get(view_layer=view_layer)}
    for ob in shown:
        ob.select_set(False, view_layer=view_layer)
    check("layers_nested: the object below the frozen parent layer cannot be selected, FixtureControl can",
          picked == {ob.name for ob in shown} - want_frozen and "FixtureControl" in picked, str(sorted(picked)))


def _local(a, t):
    """A Blender 4x4 (rows) of a 3x3 and a translation."""
    return tuple(tuple(a[r]) + (t[r],) for r in range(3)) + ((0.0, 0.0, 0.0, 1.0),)


def check_shear(modules):
    """A hand-made description with sheared local matrices (a scale along a rotated axis), with and without a
    parent, one with a zero scale: Blender's world matrices equal the products of the locals."""
    import numpy
    convert_scene, build_objects = modules[0], modules[2]
    empty_scene()
    desc = convert_scene.SceneDescription(1.0)
    md = convert_scene.MeshDescription(
        "tri", "ShearTri", numpy.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], dtype=numpy.float32),
        numpy.array([0, 1, 2], dtype=numpy.int32), numpy.array([0], dtype=numpy.int32),
        numpy.array([3], dtype=numpy.int32), numpy.zeros(1, dtype=numpy.int32), numpy.zeros(1, dtype=bool),
        numpy.zeros((0, 2), dtype=numpy.int32), [])
    desc.meshes["tri"] = md
    c, s = 0.8, 0.6
    plain = _local(((c, -s, 0), (s, c, 0), (0, 0, 1)), (0.5, -1.0, 2.0))
    nodes = [  # index, name, parent, local, kind, sheared, hidden
        (1, "ShearTop", None, _local(((1, 0.4, 0), (0.1, 1.2, 0.3), (0, 0, 0.8)), (1, 2, 3)), "EMPTY", True, False),
        (2, "ShearChild", 1, _local(((0.9, 0, 0.5), (0.2, 1.1, 0), (0, -0.3, 1.4)), (-2, 0.5, 1)), "MESH", True,
         False),
        (3, "ShearGrandchild", 2, plain, "MESH", False, False),
        (4, "ShearHiddenTop", None, _local(((2, 0.7, 0), (0, 1, 0), (0.2, 0, 1)), (3, -1, 0)), "MESH", True, True),
        (5, "PlainTop", None, plain, "EMPTY", False, False),
        (6, "ShearZeroScale", 5, _local(((0, 0.5, 0), (0, 1, 0), (0, 0.3, 1)), (1, 1, 1)), "EMPTY", True, False),
    ]
    expected = {}
    for index, name, parent, local, kind, sheared, hidden in nodes:
        m = numpy.array(local, dtype=numpy.float64)
        expected[name] = (expected[nodes[parent - 1][1]] @ m) if parent else m
        mesh = "tri" if kind == "MESH" else None
        if mesh:
            md.users.append(index)
        desc.nodes.append(convert_scene.NodeDescription(
            index, name, parent, local, tuple(map(tuple, expected[name].tolist())), kind, mesh, "", False, (),
            hidden=hidden, sheared=sheared))
    cols, built, view_layer = build_scene(desc, "shear", modules)
    helpers = built.helpers
    check("shear: one helper empty, at the identity, in the file's collection",
          len(helpers) == 1 and helpers[0].type == 'EMPTY' and helpers[0].parent is None
          and helpers[0].matrix_world == Matrix.Identity(4)
          and [col.name for col in helpers[0].users_collection] == [cols.root.name],
          str([(h.name, [col.name for col in h.users_collection]) for h in helpers]))
    for index, name, parent, _local_m, _kind, sheared, _hidden in nodes:
        ob = built.objects[index]
        want = built.objects[parent] if parent else (helpers[0] if sheared and helpers else None)
        check("shear/%s: parent" % name, ob.parent == want, "%r" % (ob.parent and ob.parent.name))
        got = numpy.array(world_of(ob), dtype=numpy.float64)
        error = float(numpy.abs(got - expected[name]).max())
        check("shear/%s: world matrix = the product of the locals" % name, error <= 1e-6, "%.3g" % error)
    roots = sorted(ob.name for ob in built.roots())
    check("shear: roots are the plain top-level object and the helper",
          roots == sorted(["PlainTop"] + [h.name for h in helpers]), str(roots))
    axis = numpy.array([(1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)], dtype=numpy.float64)
    for ob in built.roots():
        ob.matrix_basis = Matrix(axis.tolist()) @ ob.matrix_basis
    view_layer.update()
    errors = {name: float(numpy.abs(numpy.array(world_of(built.objects[index]), dtype=numpy.float64)
                                    - axis @ expected[name]).max()) for index, name, *_rest in nodes}
    check("shear: an axis change on the roots turns every object", max(errors.values()) <= 1e-6, str(errors))
    plain_only = convert_scene.SceneDescription(1.0)
    plain_only.nodes.append(convert_scene.NodeDescription(1, "PlainOnly", None, plain, plain, "EMPTY", None, "",
                                                          False, ()))
    empty_scene()
    _cols, built, _vl = build_scene(plain_only, "no_shear", modules)
    check("shear: no helper without a sheared top-level node", built.helpers == [] and len(bpy.data.objects) == 1)
    if build_objects.SHEAR_HELPER in bpy.data.objects:
        failures.append("shear: helper left over")


def _plan(path, edit=None, pick=None):
    """convert.scene.read of path, edit(desc) applied, then its slot plan; pick(desc, materials) may change the
    {node index: material object index} the plan is made from."""
    from maxdrop.convert import materials as convert_materials
    from maxdrop.convert import scene as convert_scene
    from maxdrop.reader import cfb, materials as reader_materials, scene as reader_scene
    desc = convert_scene.read(path)
    if edit is not None:
        edit(desc)
    with cfb.CompoundFile(path) as cf:
        sc = reader_scene.Scene.from_file(cf)
        conv = convert_materials.MaterialConverter(reader_materials.MaterialGraph(sc))
        materials = convert_materials.node_materials(sc, desc)
        if pick is not None:
            pick(desc, materials)
        slots = convert_materials.assign(desc, materials, conv)
    return desc, slots


def _faces(ob):
    """The material name each face of ob renders with (None: an empty slot)."""
    return [(lambda m: m and m.name)(ob.material_slots[p.material_index].material) for p in ob.data.polygons]


def check_material_slots(modules):
    """Multi/Sub-Object by material ID, slots shared by objects or linked to each, one slot per plain material."""
    import numpy
    fixtures = os.path.join(ROOT, "tests", "fixtures")

    def make(ir):
        return bpy.data.materials.new(ir.name)

    def share(desc):
        nodes = {n.name: n for n in desc.nodes}
        multi, shell = nodes["FixtureMultiBox"], nodes["FixtureShellBox"]
        md = desc.meshes[multi.mesh]
        md.material_indices = numpy.array([0, 2, 6, 0, 2, 6], dtype=numpy.int32)  # IDs 1, 3, 7 (stored zero-based)
        del desc.meshes[shell.mesh]
        shell.mesh = multi.mesh
        md.users = sorted([shell.index, multi.index])

    empty_scene()
    desc, slots = _plan(os.path.join(fixtures, "vray_wrappers.max"), share)
    _cols, built, _vl = build_scene(desc, "material_slots", modules, slots=slots, material=make)
    obs = {n.name: built.objects[n.index] for n in desc.nodes}
    multi, shell = obs["FixtureMultiBox"], obs["FixtureShellBox"]
    check("material slots: faces with IDs 1, 3, 7 on the slots of their sub-materials",
          _faces(multi) == ["FixtureSubOne", None, "FixtureSubSeven"] * 2, str(_faces(multi)))
    check("material slots: three slots on the shared mesh, linked to each object",
          len(multi.data.materials) == 3 and multi.data is shell.data
          and all(s.link == 'OBJECT' for ob in (multi, shell) for s in ob.material_slots),
          str([(s.link, s.material and s.material.name) for s in multi.material_slots]))
    check("material slots: the Shell box renders its original material on every face",
          _faces(shell) == ["FixtureShellOriginal"] * 6, str(_faces(shell)))
    two = obs["FixtureTwoSidedBox"]
    check("material slots: a translucent VRay2SidedMtl gives one slot on the mesh, named after it",
          [m.name for m in two.data.materials] == ["FixtureTwoSided"] and two.material_slots[0].link == 'DATA'
          and _faces(two) == ["FixtureTwoSided"] * 6, str(_faces(two)))
    names = sorted(m.name for m in bpy.data.materials)
    check("material slots: one Blender material per Max material",
          names == sorted(["FixtureTwoSided", "FixtureBlend", "FixtureShellOriginal", "FixtureSubOne",
                           "FixtureSubSeven"]) and len(built.materials) == 5, str(names))

    empty_scene()
    desc, slots = _plan(os.path.join(fixtures, "standard_physical.max"))
    _cols, built, _vl = build_scene(desc, "standard_physical_slots", modules, slots=slots, material=make)
    got = {n.name: [m.name for m in built.objects[n.index].data.materials] for n in desc.nodes}
    faces = {n.name: [p.material_index for p in built.objects[n.index].data.polygons] for n in desc.nodes}
    check("material slots: Standard and Physical boxes, one slot each",
          got == {"FixtureStandardBox": ["FixtureStandard"], "FixturePhysicalBox": ["FixturePhysical"]}
          and all(v == [0] * 6 for v in faces.values()), "%s %s" % (got, faces))
    check_curve_slots(modules, make)


def check_curve_slots(modules, make):
    """shapes_more: FixtureCurveStd (FixtureCurveRed) and FixtureCurveMulti (ID 1: FixtureCurveSubOne) made to share
    one curve: an empty slot on the curve, linked to each object with its own material; FixtureBox given
    FixtureCurveRed: the mesh and the curve share one Blender material; build_steps counts the curve's slots."""
    build_objects = modules[2]
    nodes_of = {}

    def share(desc):
        nodes_of.update((n.name, n) for n in desc.nodes)
        std, multi = nodes_of["FixtureCurveStd"], nodes_of["FixtureCurveMulti"]
        del desc.curves[multi.curve]
        multi.curve = std.curve
        desc.curves[std.curve].users = sorted([std.index, multi.index])

    def pick(desc, materials):
        materials[nodes_of["FixtureBox"].index] = materials[nodes_of["FixtureCurveStd"].index]

    empty_scene()
    desc, slots = _plan(os.path.join(ROOT, "tests", "fixtures", "shapes_more.max"), share, pick)
    steps = build_objects.build_steps(desc, bpy.context.scene.collection, slots=slots, material=make)
    counts = []
    while True:
        try:
            counts.append(next(steps))
        except StopIteration as end:
            built = end.value
            break
    total = build_objects.steps_of(desc, slots)
    check("curve slots: build_steps ends at steps_of, which counts the curve plans",
          counts[-1] == (total, total) and len(slots.curves) == 3
          and total == build_objects.steps_of(desc, dict(slots)) + 3, "%s %d" % (counts[-1:], total))
    obs = {n.name: built.objects[n.index] for n in desc.nodes}
    std, multi, box = obs["FixtureCurveStd"], obs["FixtureCurveMulti"], obs["FixtureBox"]
    got = [(s.link, s.material and s.material.name) for ob in (std, multi) for s in ob.material_slots]
    check("curve slots: a curve shared by objects with different materials, its slot linked to each object",
          std.data is multi.data and list(std.data.materials) == [None]
          and got == [('OBJECT', "FixtureCurveRed"), ('OBJECT', "FixtureCurveSubOne")], str(got))
    reds = [m.name for m in bpy.data.materials if m.name.startswith("FixtureCurveRed")]
    check("curve slots: a mesh and a curve with the same 3ds Max material share one Blender material",
          reds == ["FixtureCurveRed"] and box.data.materials[0] is std.material_slots[0].material, str(reds))
    with_slots = sorted(ob.name for ob in obs.values() if ob.type == 'CURVE' and len(ob.data.materials))
    check("curve slots: curves without a material get no slot",
          with_slots == ["FixtureCurveIds", "FixtureCurveMixed", "FixtureCurveMulti", "FixtureCurveStd"],
          str(with_slots))

    def curves_only(desc):
        share(desc)
        box = nodes_of["FixtureBox"]
        desc.meshes.clear()
        desc.nodes = [n for n in desc.nodes if n is not box]  # no node is FixtureBox's child

    empty_scene()
    desc, slots = _plan(os.path.join(ROOT, "tests", "fixtures", "shapes_more.max"), curves_only)
    steps = build_objects.build_steps(desc, bpy.context.scene.collection, slots=slots, material=make)
    counts = []
    while True:
        try:
            counts.append(next(steps))
        except StopIteration as end:
            built = end.value
            break
    total = build_objects.steps_of(desc, slots)
    std = built.objects[nodes_of["FixtureCurveStd"].index]
    check("curve slots: a scene without meshes (a Slots that is empty as a dict) still gets its curve slots",
          not slots and len(slots.curves) == 3 and counts[-1] == (total, total)
          and [s.material and s.material.name for s in std.material_slots] == ["FixtureCurveRed"],
          "%s %s" % (counts[-1:], [s.material for s in std.material_slots]))


def check_crease_open_edges():
    """build.modifiers: a mesh that asks for creases gets none on its open edges (sharp for a Shell's rim), its other
    sharp edges creased."""
    from maxdrop.build import modifiers as build_modifiers
    mesh = bpy.data.meshes.new("maxdrop crease test")
    try:
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)], [],
                         [(0, 1, 4, 3), (1, 2, 5, 4)])
        sharp = mesh.attributes.get("sharp_edge") or mesh.attributes.new("sharp_edge", 'BOOLEAN', 'EDGE')
        sharp.data.foreach_set("value", [True] * len(mesh.edges))
        build_modifiers._crease(mesh)
        crease = [d.value for d in mesh.attributes["crease_edge"].data]
        want = [1.0 if tuple(sorted(e.vertices)) == (1, 4) else 0.0 for e in mesh.edges]
        check("crease: the sharp edge between two faces creased, the open ones not", crease == want, str(crease))
    finally:
        bpy.data.meshes.remove(mesh)
