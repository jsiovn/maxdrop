# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the tests of maxdrop/convert/materials/ share: numpy when present, the package loaded without
Blender, the fake blocks, materials and graphs, Close and the builders of materials, fixtures and IRs."""
import ast
import importlib
import json
import math
import os
import sys
import types


try:
    import numpy
except ImportError:  # optional here: CI installs it, Blender ships it
    numpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
TOLERANCE = 1e-5

# A package named apart from the add-on (see test_convert_scene.py): maxdrop/__init__.py, which imports bpy, never
# runs.
_PKG = "maxdrop_convert_test"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
mat = importlib.import_module(_PKG + ".convert.materials")
colors = importlib.import_module(_PKG + ".convert.colors")
texmaps = importlib.import_module(_PKG + ".convert.texmaps")
cfb = importlib.import_module(_PKG + ".reader.cfb")
chunks = importlib.import_module(_PKG + ".reader.chunks")
classdir = importlib.import_module(_PKG + ".reader.classdir")
classids = importlib.import_module(_PKG + ".reader.classids")
pblock = importlib.import_module(_PKG + ".reader.pblock")
reader_materials = importlib.import_module(_PKG + ".reader.materials")
reader_scene = importlib.import_module(_PKG + ".reader.scene")

Ref = pblock.Reference
GREY = (0.215861,) * 3  # sRGB 128 grey, linear


class FakeBlock:
    def __init__(self, block_id, params):
        self.block_id, self._params = block_id, params

    def __contains__(self, pid):
        return pid in self._params

    def value(self, pid, default=None):
        v = self._params.get(pid, default)
        return list(v) if isinstance(v, list) else v

    def get(self, pid, tab=0, default=None):
        v = self._params.get(pid, default)
        return (v[tab] if 0 <= tab < len(v) else default) if isinstance(v, list) else v


class FakeMtl:
    """A MtlBase stand-in: blocks {block id: {param id: value}}, a list for a table."""

    def __init__(self, index, class_id, name="", blocks=None, superclass=classids.SC_MATERIAL, parts=None):
        self.index, self.class_id, self.name, self.superclass = index, class_id, name, superclass
        self._blocks = [FakeBlock(b, p) for b, p in sorted((blocks or {}).items())]
        self.parts = parts or {}

    def block(self, block_id):
        return next((b for b in self._blocks if b.block_id == block_id), None)

    def param(self, pid, block_id=None, tab=0, default=None):
        for b in [self.block(block_id)] if block_id is not None else self._blocks:
            if b is not None and pid in b:
                return b.get(pid, tab, default)
        return default


class FakeGraph:
    def __init__(self, *objects):
        self.objects = {o.index: o for o in objects}

    def get(self, i):
        if not 0 <= i:  # as MaterialGraph.get: TypeError for None
            raise chunks.ChunkError("object %d is not a material or map" % i)
        if i not in self.objects:
            raise chunks.ChunkError("object %d is not a material or map" % i)
        return self.objects[i]

    def superclass(self, i):
        if not 0 <= i:  # as MaterialGraph.superclass: an int index, TypeError for None
            return None
        o = self.objects.get(i)
        return None if o is None else o.superclass


def _map(index, class_id=classids.BITMAP_TEX, name="map"):
    return FakeMtl(index, class_id, name, superclass=classids.SC_TEXMAP)


def _vray(index, name="V", **blocks):
    return FakeMtl(index, classids.VRAY_MTL, name, {int(k[1:]): v for k, v in blocks.items()})


def _convert(*objects, index=0):
    conv = mat.MaterialConverter(FakeGraph(*objects))
    return conv, conv.convert(index)


def _build_constant(name):
    """A module-level constant of maxdrop/build/materials/sockets.py, whose package imports bpy: read from its
    source."""
    path = os.path.join(ROOT, "maxdrop", "build", "materials", "sockets.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets):
            return ast.literal_eval(stmt.value)
    raise AssertionError("no %s in maxdrop/build/materials/sockets.py" % name)


class Close:
    def close(self, ours, theirs, what=""):
        if isinstance(theirs, tuple):
            self.assertEqual(len(ours), len(theirs), what)
            for a, b in zip(ours, theirs):
                self.assertAlmostEqual(a, b, delta=TOLERANCE, msg=what)
        else:
            self.assertAlmostEqual(ours, theirs, delta=TOLERANCE, msg=what)


def _wrapper(index, class_id, params, name="W"):
    return FakeMtl(index, class_id, name, {0: params})


def _fixture(name):
    cf = cfb.CompoundFile(os.path.join(FIXTURE_DIR, name + ".max"))
    s = reader_scene.Scene.from_file(cf)
    graph = reader_materials.MaterialGraph(s)
    by_name = {graph.get(i).name: i for i in graph.walk(s.node(n).material for n in s.walk())}
    return cf, graph, by_name


def _standard(index, shader_class, shader, blocks=None, maps=None, name="S"):
    """A Standard material with its shader part (block 0 of the part = shader) and maps {slot: (ref, on, amount)}."""
    blocks = {k: dict(v) for k, v in (blocks or {}).items()}
    if maps:
        enables, refs, amounts = [0] * 24, [Ref(None)] * 24, [1.0] * 24
        for slot, (ref, on, amount) in maps.items():
            refs[slot], enables[slot], amounts[slot] = ref, on, amount
        blocks[3] = {0: enables, 1: refs, 2: amounts}
    parts = {}
    if shader_class is not None:
        parts[2] = reader_materials.Part(50, shader_class, classids.SC_SHADER, {0: FakeBlock(0, shader)}, {})
    return FakeMtl(index, classids.STANDARD_MTL, name, blocks, parts=parts)


def _srgb(*rgb):
    return tuple(colors.srgb_to_linear(c / 255.0) for c in rgb)


def _oracle_graph(name):
    with open(os.path.join(FIXTURE_DIR, name + ".oracle.json"), encoding="ascii") as f:
        return {e["name"]: e for e in json.load(f)["material_graph"]}


def _names(block):
    return {p["id"]: p["name"] for p in block["params"]}


def _multi(index, entries, name="Multi", ids=True):
    """A Multi/Sub-Object of entries [(material id, ref, on)]."""
    block = {0: [r for _i, r, _on in entries], 1: [on for _i, _r, on in entries]}
    if ids:
        block[3] = [i for i, _r, _on in entries]
    return FakeMtl(index, classids.MULTI_SUB_MTL, name, {0: block})


def _spline(ids):
    """A SplineDescription stand-in: ids, one segment material ID or the distinct ones in segment order."""
    ids = (ids,) if isinstance(ids, int) else tuple(ids)
    return types.SimpleNamespace(material=ids[0], material_ids=ids)


def _desc(curves=None, **meshes):
    """A SceneDescription stand-in: meshes {key: (users, face material IDs)}, curves {key: users, or (users, the
    material IDs of each spline: an int, or a tuple for a spline that mixes them)} (a list of users alone: one spline
    at ID 0)."""
    def curve(v):
        users, splines = (v, [0]) if isinstance(v, list) else v
        return types.SimpleNamespace(users=users, splines=[_spline(x) for x in splines])
    return types.SimpleNamespace(meshes={k: types.SimpleNamespace(users=u, material_indices=numpy.array(f,
                                                                                                      dtype=numpy.int32))
                                         for k, (u, f) in meshes.items()},
                                 curves={k: curve(v) for k, v in (curves or {}).items()}, issues=[])


def _lin(s):
    c = s / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lins(*s):
    return tuple(_lin(c) for c in s)


def _hair_color(melanin, pheomelanin, tint, diffuse=(0.0, 0.0, 0.0), transmission=(1.0, 1.0, 1.0)):
    """CoronaHairMtl's base color as Corona 12 renders the material on a plane in a white furnace (maxdrop-em3.164):
    the color h = exp(-u) per channel, u = (7.68 m^2 + 1.2 m^3) x ((1 - p) x eumelanin + 0.685 p x pheomelanin)
    (Cycles' absorption shapes) + 0.054 ln(tint)^2, times the transmission color; Corona renders 0.070 + 0.929 h, a
    Principled BSDF 0.043 + 0.957 x its base (Cycles 5.2, IOR 1.55, roughness 0.5); a diffuse color d mixed in as d +
    (1 - max d) x that base."""
    k = 7.68 * melanin ** 2 + 1.2 * melanin ** 3
    w = max(diffuse)
    out = []
    for eu, pheo, t, d, tr in zip((0.506, 0.841, 1.653), (0.343, 0.733, 1.924), tint, diffuse, transmission):
        u = k * ((1.0 - pheomelanin) * eu + 0.685 * pheomelanin * pheo) + 0.054 * math.log(min(1.0, max(1e-4, t))) ** 2
        base = (0.070 + 0.929 * math.exp(-u) * tr - 0.043) / 0.957
        out.append(min(1.0, d + (1.0 - w) * base))
    return tuple(out)


def _corona(index, class_id, **params):
    return FakeMtl(index, class_id, "C", {0: {int(k[1:]): v for k, v in params.items()}})


def _medium(color, meters, albedo, g=0.0, emission=(0.0, 0.0, 0.0)):
    """The Medium of an absorption color reached at `meters`, a scattering albedo, a directionality and an emission
    per meter: sigma_t = -ln(color) / meters per channel, sigma_s = albedo x sigma_t, sigma_a the rest."""
    t = tuple(-math.log(c) / meters for c in color)
    return mat.Medium(tuple(a * x for a, x in zip(albedo, t)), tuple((1.0 - a) * x for a, x in zip(albedo, t)), g,
                      emission)


def _close_medium(case, got, want):
    for field in ("scattering", "absorption", "emission"):
        for a, b in zip(getattr(got, field), getattr(want, field)):
            case.assertAlmostEqual(a, b, delta=max(TOLERANCE, abs(b) * 1e-6), msg=field)
    case.assertAlmostEqual(got.anisotropy, want.anisotropy, delta=TOLERANCE)
