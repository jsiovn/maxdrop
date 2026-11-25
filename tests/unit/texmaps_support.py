# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the tests of maxdrop/convert/texmaps/ share: the package loaded without Blender, the fixtures,
the fake scenes, blocks, maps and graphs, the map builders and the Checks test case."""
import collections
import importlib
import math
import os
import struct
import sys
import types
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
TOLERANCE = 1e-5

_PKG = "maxdrop_convert_test"  # the package test_convert_materials.py makes: maxdrop/__init__.py never runs
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg
tx = importlib.import_module(_PKG + ".convert.texmaps")
mat = importlib.import_module(_PKG + ".convert.materials")
colors = importlib.import_module(_PKG + ".convert.colors")
assets = importlib.import_module(_PKG + ".reader.assets")
cfb = importlib.import_module(_PKG + ".reader.cfb")
chunks = importlib.import_module(_PKG + ".reader.chunks")
classdir = importlib.import_module(_PKG + ".reader.classdir")
classids = importlib.import_module(_PKG + ".reader.classids")
pblock = importlib.import_module(_PKG + ".reader.pblock")
reader_materials = importlib.import_module(_PKG + ".reader.materials")
reader_scene = importlib.import_module(_PKG + ".reader.scene")
controllers_mod = importlib.import_module(_PKG + ".reader.controllers")
params_mod = importlib.import_module(_PKG + ".convert.params")

Ref = pblock.Reference
DEG = math.pi / 180.0


def _lin(c):
    """A swatch 0..255 of a fixture (saved with the gamma off) as linear: the sRGB curve."""
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


class Fixture:
    """A fixture's converters, its materials by name and its nodes' IRs."""

    def __init__(self, name):
        self.cf = cfb.CompoundFile(os.path.join(FIXTURE_DIR, name + ".max"))
        self.scene = reader_scene.Scene.from_file(self.cf)
        self.graph = reader_materials.MaterialGraph(self.scene)
        self.tex = tx.TexmapConverter(self.graph, assets.AssetTable.from_file(self.cf))
        self.conv = mat.MaterialConverter(self.graph, texmaps=self.tex)
        self.irs = {}
        for n in self.scene.walk():
            ir = self.conv.convert(self.scene.node(n).material)
            if ir is not None:
                self.irs[ir.name] = ir

    def close(self):
        self.cf.close()


class _Swatch:
    """A material whose parameter (pid, block id) reads value, the rest as saved."""

    def __init__(self, m, key, value):
        self._m, self._key, self._value = m, key, value

    def __getattr__(self, name):
        return getattr(self._m, name)

    def param(self, pid, block_id=None, tab=0, default=None):
        return self._value if (pid, block_id) == self._key else self._m.param(pid, block_id, tab, default)


class Checks(unittest.TestCase):
    def close(self, ours, theirs, what=""):
        if isinstance(theirs, tuple):
            self.assertEqual(len(ours), len(theirs), what)
            for a, b in zip(ours, theirs):
                self.assertAlmostEqual(a, b, delta=TOLERANCE, msg=what)
        else:
            self.assertAlmostEqual(ours, theirs, delta=TOLERANCE, msg=what)

    def held(self, root, what=""):
        """The graph under a gamma-off color root's Decode: the map computed on the values the renderer holds
        (maxdrop-em3.158, maxdrop-6n0.6.18)."""
        self.assertIsInstance(root, tx.Decode, what)
        self.assertFalse(root.mean, what)
        return root.input

    def image(self, node, name, colorspace, tiling=(1.0, 1.0), offset=(0.0, 0.0), w_angle=0.0, channel=1):
        self.assertIsInstance(node, tx.Image, name)
        self.assertEqual(node.name, name)
        self.assertEqual(node.colorspace, colorspace, name)
        self.close(node.mapping.tiling, tiling, name)
        self.close(node.mapping.offset, offset, name)
        self.close(node.mapping.angle[2], w_angle * DEG, name)
        self.assertEqual(node.mapping.channel, channel, name)


# Synthetic maps: a MaterialGraph stand-in whose scene has no chunks (every Placement and Output takes its defaults).

G1 = bytes(range(16))


class FakeEntry(collections.namedtuple("FakeEntry", "name")):
    pass


class FakeScene:
    def __init__(self, objects, chunk_map=None):
        self.objects, self.chunks = objects, chunk_map or {}

    def __len__(self):
        return max(list(self.objects) + list(self.chunks), default=-1) + 1

    def entry(self, i):
        o = self.objects.get(i)
        return FakeEntry(o.cls) if o is not None else None

    def chunk(self, i):
        if i not in self.chunks:
            raise chunks.ChunkError("no chunks here")
        return self.chunks[i]


class FakeChunk:
    """A chunk: a leaf with a payload, or a container with children."""

    def __init__(self, cid, payload=None, children=None):
        self.id, self.container = cid, children is not None
        self.children, self._payload = list(children or ()), payload or b""
        self.payload_size = len(self._payload)

    def tobytes(self):
        return self._payload

    def unpack(self, fmt):
        return struct.unpack_from(fmt, self._payload)

    def first(self, cid):
        return next((c for c in self.children if c.id == cid), None)


class FakeOld:
    """An old ParamBlock: values by index."""

    def __init__(self, values):
        self._values = values

    def get(self, i, default=None):
        return self._values.get(i, default)

    def controller(self, i):
        return None


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


class FakeMap:
    def __init__(self, index, class_id, params=None, children=(), cls="", superclass=classids.SC_TEXMAP,
                 name="map"):
        self.index, self.class_id, self.superclass, self.name, self.cls = index, class_id, superclass, name, cls
        self.blocks = {0: FakeBlock(0, params or {})}
        self.refs, self.parts, self.children = {}, {}, list(children)

    def block(self, block_id):
        return self.blocks.get(0) if block_id == 0 else None

    def param(self, pid, block_id=None, tab=0, default=None):
        b = self.blocks[0]
        return b.get(pid, tab, default) if pid in b else default


class FakeGraph:
    def __init__(self, *objects, chunk_map=None):
        self.objects = {o.index: o for o in objects}
        self.scene = FakeScene(self.objects, chunk_map)

    def get(self, i):
        if i not in self.objects:
            raise chunks.ChunkError("object %d is not a material or map" % i)
        return self.objects[i]

    def superclass(self, i):
        o = self.objects.get(i)
        return None if o is None else o.superclass


def _bitmap(index, guid=G1):
    return FakeMap(index, classids.BITMAP_TEX, {13: pblock.Asset(guid)}, cls="Bitmap")


def _falloff(index, map1=None, color1=(0.5, 0.5, 0.5), ftype=1, name="map"):
    return FakeMap(index, tx.FALLOFF, {0: color1, 2: Ref(map1), 3: 1, 8: ftype}, [map1] if map1 is not None else [],
                   cls="Falloff", name=name)


def _table():
    return assets.AssetTable([assets.AssetEntry(G1, "Bitmap", "maps\\a.png", "")])


def _tex(*objects, table=None):
    return tx.TexmapConverter(FakeGraph(*objects), _table() if table is None else table)


UVGEN_OBJECT, INFO_BLOCK = 50, 60


def _placed(index=1, uv=None, old=None, info=None):
    """A Bitmap with a Placement part (its chunk uv, its old ParamBlock old) and BitmapInfo bytes info; and the
    chunk map of its scene."""
    b = _bitmap(index)
    b.parts = {0: reader_materials.Part(UVGEN_OBJECT, classids.STD_UVGEN, classids.SC_UVGEN, {},
                                        {0: FakeOld(old or {})})}
    chunk_map = {UVGEN_OBJECT: uv} if uv is not None else {}
    if info is not None:
        b.refs = {0: INFO_BLOCK}
        chunk_map[INFO_BLOCK] = FakeChunk(0x82, children=[FakeChunk(0x0003, children=[FakeChunk(0x1201, info)])])
    return b, chunk_map


def _info(gamma, flags):
    return bytes(56) + struct.pack("<fI", gamma, flags) + bytes(6)  # 70 bytes, the gamma tail 14 from the end


def _image(b, chunk_map, kind=tx.COLOR):
    tex = tx.TexmapConverter(FakeGraph(b, chunk_map=chunk_map), _table())
    return tex, tex.convert(mat.MapRef(b.index), kind)


G2 = bytes(range(16, 32))


def _cbitmap(index, guid=G1, **params):
    p = {101: pblock.Asset(guid)}
    p.update({int(k[1:]): v for k, v in params.items()})
    return FakeMap(index, classids.CORONA_BITMAP, p, cls="CoronaBitmap")


def _ccolor(index, **params):
    return FakeMap(index, classids.CORONA_COLOR, {int(k[1:]): v for k, v in params.items()}, cls="CoronaColor")


# probe1's P5 layers (maxdrop-em3.117): bottom (0.2, 0.6, 0.3) and top (0.8, 0.1, 1.1), each with offset 3 (-0.3)
P5_BOTTOM, P5_TOP = (-0.1, 0.3, 0.0), (0.5, -0.2, 0.8)


def _cmix(index, children=(), **params):
    return FakeMap(index, classids.CORONA_MIX, {int(k[1:]): v for k, v in params.items()}, children,
                   cls="CoronaMix")


def _vbitmap(index, guid=G1, **params):
    p = {0: pblock.Asset(guid)}
    p.update({int(k[1:]): v for k, v in params.items()})
    return FakeMap(index, classids.VRAY_BITMAP, p, cls="VRayBitmap", name="vb")


def _noise(index):
    """An unsupported map class with no bitmap below: converts to nothing."""
    return FakeMap(index, (0x1234, 0), cls="Noise", name="n")


def _rgb(value):
    return tuple(value) if isinstance(value, tuple) else (value,) * 3


# rows 128 / 64 / 32 of em3.76's measured RGB Tint, as stored
ROWS = {0: (128 / 255, 0.0, 0.0), 1: (0.0, 64 / 255, 0.0), 2: (0.0, 0.0, 32 / 255)}


def _wtint(index, map_ref=None, rows=ROWS):
    params = dict(rows)
    params[3] = Ref(map_ref)
    return FakeMap(index, tx.RGB_TINT, params, [map_ref] if map_ref is not None else [], cls="RGB Tint", name="t")


def _vcolor(index, rgb):
    return FakeMap(index, classids.VRAY_COLOR, {tx.VC_COLOR: rgb}, cls="VRayColor", name="vc")


def _vnormal(index, normal):
    return FakeMap(index, classids.VRAY_NORMAL_MAP, {0: Ref(normal), 2: 1, 3: 1.0}, [normal], cls="VRayNormalMap")


PROBE_COLOR = (200 / 255, 100 / 255, 50 / 255)  # maxdrop-6n0.6.2's VRayColor


def _wout(index, map_ref=None, level=0.5):
    """An Output whose Output part has that RGB level."""
    out = FakeMap(index, tx.OUTPUT, {0: Ref(map_ref)}, [map_ref] if map_ref is not None else [], cls="Output",
                  name="out")
    part = FakeMap(index + 40, (0x100, 0), superclass=classids.SC_TEXOUTPUT)
    part.legacy = {0: FakeOld({0: level})}  # an old ParamBlock: level stored, the rest neither stored nor animated
    out.parts = {2: part}
    return out


def _bw_mix(index, mask):
    """A Mix black -> white at amount 0 whose mask is map mask: what V-Ray renders is the mask's value."""
    return FakeMap(index, tx.MIX, {0: 0.0, 8: Ref(mask)}, [mask], cls="Mix", name="mix")


MEAN = "mean"  # SceneGammaImages.check: Decode(mean) over the image read as stored (Non-Color)


def _decodes(root):
    """The Decode nodes of a graph."""
    seen, stack, out = set(), [root], []
    while stack:
        n = stack.pop()
        if n is None or id(n) in seen:
            continue
        seen.add(id(n))
        if isinstance(n, tx.Decode):
            out.append(n)
        stack.extend(tx._children(n))
    return out
