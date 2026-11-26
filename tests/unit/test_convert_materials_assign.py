# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of maxdrop/convert/materials/ on the assignment of materials to meshes and curves, and the
parameters read at frame 0, no Blender.

    python -I -m unittest discover tests
"""
import collections
import importlib
import json
import os
import random
import sys
import types
import unittest

_TESTS = "maxdrop_unit_tests"  # tests/unit as a package: its files share their support modules, alone or under discover
if _TESTS not in sys.modules:
    _tests = types.ModuleType(_TESTS)
    _tests.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_TESTS] = _tests
from maxdrop_unit_tests.convert_materials_support import (  # noqa: E402 (after the loader)
    _corona, _desc, _fixture, _multi, _PKG, _spline, _standard, _vray, _wrapper, classdir, classids,
    Close, FakeBlock, FakeGraph, FakeMtl, FIXTURE_DIR, mat, numpy, pblock, reader_materials,
    reader_scene, Ref, texmaps,
)


@unittest.skipIf(numpy is None, "numpy missing")  # assign() and the mesh reader need it
class Assign(unittest.TestCase):
    def names(self, slots):
        return [[ir and ir.name for ir in s] for s in slots]

    def test_fixture_multi_box(self):
        cf, graph, by_name = _fixture("vray_wrappers")
        with cf:
            s = reader_scene.Scene.from_file(cf)
            desc = importlib.import_module(_PKG + ".convert.scene").describe(s, 0.001, None)
            conv = mat.MaterialConverter(graph)
            materials = mat.node_materials(s, desc)
            plan = mat.assign(desc, materials, conv)
        box = next(n for n in desc.nodes if n.name == "FixtureMultiBox")
        ms = plan[box.mesh]
        self.assertEqual(ms.users, [box.index])
        self.assertEqual(self.names(ms.slots), [["FixtureSubOne"], [None]])
        self.assertEqual(ms.indices.tolist(), [1, 0, 1, 1, 1, 1])  # face IDs 2 1 5 4 6 3: only ID 1 has a material
        two = next(n for n in desc.nodes if n.name == "FixtureTwoSidedBox")
        self.assertEqual(self.names(plan[two.mesh].slots), [["FixtureFront"]])
        self.assertEqual(plan[two.mesh].indices.tolist(), [0] * 6)
        self.assertEqual(plan[two.mesh].indices.dtype.name, "int32")

    def test_users_with_different_materials(self):
        objs = (_multi(0, [(0, Ref(1), 1), (2, Ref(2), 1), (6, Ref(3), 1)]), _vray(1, "One"), _vray(2, "Three"),
                _vray(3, "Seven"), _vray(4, "Plain"))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        plan = mat.assign(_desc(m=([10, 11], [6, 0, 2, 0, 5])), {10: 0, 11: 4}, conv)["m"]
        self.assertEqual(plan.users, [10, 11])
        self.assertEqual(self.names(plan.slots), [["One", "Plain"], ["Three", "Plain"], [None, "Plain"],
                                                  ["Seven", "Plain"]])
        self.assertEqual(plan.indices.tolist(), [3, 0, 1, 0, 2])

    def test_one_material_and_no_material(self):
        conv = mat.MaterialConverter(FakeGraph(_vray(4, "Plain")))
        plan = mat.assign(_desc(a=([1, 2], [3, 1, 2]), b=([3], [0, 5]), c=([5], [])), {1: 4, 2: 4, 3: None, 5: 4},
                          conv)
        self.assertEqual((self.names(plan["a"].slots), plan["a"].indices.tolist()), ([["Plain", "Plain"]], [0, 0, 0]))
        self.assertEqual((plan["b"].slots, plan["b"].indices.tolist()), ([], [0, 0]))
        self.assertEqual((self.names(plan["c"].slots), plan["c"].indices.tolist()), ([], []))
        self.assertEqual(plan.curves, {})

    def test_curves(self):
        """One slot: what each user gets for material ID 1 (a Multi/Sub-Object by that ID, none when its entry is
        off); no plan when no user has a material. The same key for a mesh and a curve: two dicts."""
        objs = (_vray(4, "Plain"), _vray(5, "Other"), _multi(6, [(0, Ref(5), 1), (1, Ref(4), 1)]),
                _multi(7, [(0, Ref(4), 0), (1, Ref(5), 1)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        curves = {"one": [1, 2], "two": [3, 4], "multi": [5], "off": [6], "bare": [7], "k": [8]}
        plan = mat.assign(_desc(curves=curves, k=([1], [0])), {1: 4, 2: 4, 3: 4, 4: 5, 5: 6, 6: 7, 7: None, 8: 5},
                          conv)
        self.assertIsInstance(plan, mat.Slots)
        got = {k: (p.users, self.names(p.slots), p.indices.tolist()) for k, p in plan.curves.items()}
        self.assertEqual(got, {"one": ([1, 2], [["Plain", "Plain"]], [0]), "two": ([3, 4], [["Plain", "Other"]], [0]),
                               "multi": ([5], [["Other"]], [0]), "k": ([8], [["Other"]], [0])})
        self.assertEqual(plan.curves["k"].indices.dtype.name, "int32")
        self.assertEqual(self.names(plan["k"].slots), [["Plain"]])

    def test_curve_splines(self):
        """Each spline on the slot of its material ID: slots in ID order, indices per spline; IDs a plain material
        gives alike share one slot; an ID whose entry is off is an empty slot beside the others."""
        objs = (_vray(4, "Plain"), _vray(5, "Other"), _multi(6, [(0, Ref(4), 1), (1, Ref(5), 1)]),
                _multi(7, [(0, Ref(4), 1), (1, Ref(5), 0)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        desc = _desc(curves={"multi": ([1], [1, 0, 1]), "plain": ([2], [1, 0]), "gap": ([3], [0, 1]),
                             "both": ([1, 2], [1, 0])})
        plan = mat.assign(desc, {1: 6, 2: 4, 3: 7}, conv)
        got = {k: (self.names(p.slots), p.indices.tolist()) for k, p in plan.curves.items()}
        self.assertEqual(got, {"multi": ([["Plain"], ["Other"]], [1, 0, 1]), "plain": ([["Plain"]], [0, 0]),
                               "gap": ([["Plain"], [None]], [0, 1]),
                               "both": ([["Plain", "Plain"], ["Other", "Plain"]], [1, 0])})
        self.assertEqual(plan.curves["multi"].indices.dtype.name, "int32")
        self.assertEqual(desc.issues, [])

    def test_curve_mixed_ids(self):
        """A spline mixing IDs is drawn with its first segment's: an issue (once, on the curve's first user) only
        when a user gets another material for one of its other IDs."""
        objs = (_vray(4, "Plain"), _vray(5, "Other"), _multi(6, [(0, Ref(4), 1), (1, Ref(5), 1)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        desc = _desc(curves={"multi": ([1, 2], [0, (1, 0), (1, 0, 2)]), "plain": ([3], [(1, 0)])})
        plan = mat.assign(desc, {1: 4, 2: 6, 3: 4}, conv)
        got = {k: (self.names(p.slots), p.indices.tolist()) for k, p in plan.curves.items()}
        self.assertEqual(got, {"multi": ([["Plain", "Plain"], ["Plain", "Other"]], [0, 1, 1]),
                               "plain": ([["Plain"]], [0])})
        self.assertEqual(desc.issues, [(1, "shape: spline 2 mixes material IDs 2, 1: drawn with ID 2's material "
                                           "(its first segment's)")])

    def test_curve_mixed_ids_convert_no_unused_material(self):
        """The mixed-ID check converts nothing: a sub-material only a mixed spline's other ID picks is not converted
        (no IR, no counts), the issue is named all the same."""
        objs = (_vray(4, "Used"), FakeMtl(5, classdir.ClassId(0x1234, 0x5678), "Unused", {}),
                _multi(6, [(0, Ref(4), 1), (1, Ref(5), 1)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        desc = _desc(curves={"c": ([1], [(0, 1)])})
        plan = mat.assign(desc, {1: 6}, conv)
        self.assertEqual(self.names(plan.curves["c"].slots), [["Used"]])
        self.assertNotIn(5, conv._done)
        self.assertEqual(dict(conv.stats.unknown), {})
        self.assertEqual(len(desc.issues), 1)
        self.assertEqual(conv.source_for(6, 1), 5)
        self.assertEqual(conv.source_for(6, 0), 4)
        self.assertIsNone(conv.source_for(None, 0))

    def test_curve_mixed_ids_wrappers_of_one_base(self):
        """Entries that are different wrappers around one base (or a wrapper and its base) draw the same: no line,
        though no wrapper was peeled before, and the check peels, converts and caches nothing. A line where the draw
        differs: another base, or a wrapper whose peel fails (its grey is its own)."""
        def objs():
            return (_vray(4, "Base"), _vray(5, "Other"),
                    _wrapper(30, classids.VRAY_MTL_WRAPPER, {0: Ref(4)}),
                    _wrapper(31, classids.VRAY_2SIDED_MTL, {0: Ref(4)}),
                    _wrapper(32, classids.VRAY_MTL_WRAPPER, {0: Ref(None)}),
                    _multi(6, [(0, Ref(30), 1), (1, Ref(31), 1), (2, Ref(4), 1), (3, Ref(5), 1), (4, Ref(32), 1)]))
        cd = types.SimpleNamespace(users=[1], splines=[_spline(t) for t in [(1, 0), (2, 0), (0, 2, 1)]])
        conv = mat.MaterialConverter(FakeGraph(*objs()))
        self.assertIsNone(mat._mixed(cd, {1: 6}, conv))
        self.assertEqual(dict(conv.stats.peeled), {})
        self.assertEqual((conv._done, conv._peels), ({}, {}))

        conv = mat.MaterialConverter(FakeGraph(*objs()))
        desc = _desc(curves={"c": ([1], [(1, 0), (1, 2, 0)])})  # one slot: ID 1's
        plan = mat.assign(desc, {1: 6}, conv)
        self.assertEqual(desc.issues, [])
        self.assertEqual(self.names(plan.curves["c"].slots), [["Base"]])
        self.assertEqual(set(conv._done), {4, 31}, "only what the slots converted")
        self.assertEqual(dict(conv.stats.peeled), {"VRay2SidedMtl": 1}, "the slot's own peel")

        for spline in [(3, 0), (4, 2)]:
            with self.subTest(spline):
                conv = mat.MaterialConverter(FakeGraph(*objs()))
                desc = _desc(curves={"c": ([1], [spline])})
                mat.assign(desc, {1: 6}, conv)
                self.assertEqual(len(desc.issues), 1)

    def test_source_for_unwalked_wrappers(self):
        """source_for answers a wrapper with what peel() reaches from it, without peeling: a cycle or a chain deeper
        than MAX_PEEL answers the wrapper itself (peel() fails from it), one level lower the base."""
        n = mat.MAX_PEEL + 1
        chain = [_wrapper(40 + k, classids.VRAY_MTL_WRAPPER, {0: Ref(41 + k)}) for k in range(n)]
        objs = (_vray(4, "Base"), _wrapper(30, classids.VRAY_MTL_WRAPPER, {0: Ref(4)}),
                _wrapper(33, classids.VRAY_MTL_WRAPPER, {0: Ref(34)}),
                _wrapper(34, classids.VRAY_2SIDED_MTL, {0: Ref(33)}),
                _multi(6, [(0, Ref(30), 1)]), *chain, _vray(40 + n, "Deep"))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertEqual(conv.source_for(6, 0), 4)
        self.assertEqual(conv.source_for(30, 0), 4)
        self.assertEqual(conv.source_for(33, 0), 33)
        self.assertEqual(conv.source_for(40, 0), 40)
        self.assertEqual(conv.source_for(41, 0), 40 + n)
        self.assertEqual((dict(conv.stats.peeled), conv._peels, conv._done), ({}, {}, {}))
        for top in (30, 33, 40, 41):
            want = conv.peel(top)[0]
            self.assertEqual(conv.source_for(top, 0), top if want is None else want, top)

    def test_source_for_matches_peel_of_every_wrapper(self):
        """On a fresh converter source_for answers each wrapper class as peel() does on another (the wrapper itself
        where the peel fails): Shell, CoronaSelect, switched-off slots, a CoronaLayeredMtl that mixes its layers (a
        material of its own: itself) or has no base (a wrapper)."""
        cases = [
            _wrapper(0, classids.SHELL_MTL, {1: 1, 2: Ref(1), 3: Ref(2)}),
            _wrapper(0, classids.SHELL_MTL, {1: 4, 2: Ref(1)}),  # render index out of range: fails
            _wrapper(0, classids.CORONA_SELECT_MTL, {312: [Ref(1), Ref(2)], 313: 1}),
            _wrapper(0, classids.CORONA_SELECT_MTL, {312: [Ref(1)], 313: 3}),  # fails
            _wrapper(0, classids.VRAY_OVERRIDE_MTL, {0: Ref(1), 1: 0, 2: Ref(2)}),  # base off: GI
            _wrapper(0, classids.DOUBLE_SIDED_MTL, {0: Ref(1), 1: Ref(2), 2: 0, 3: 0}),  # both off: fails
            _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(1), p1001=[Ref(2)]),  # mixes: itself
            _corona(0, classids.CORONA_LAYERED_MTL, p1000=Ref(None), p1001=[Ref(1), Ref(2)], p1004=[0, 1]),
            _wrapper(0, classids.VRAY_MTL_WRAPPER, {0: Ref(3)}),  # sub-material not a material: fails
        ]
        for top in cases:
            with self.subTest(top.class_id):
                objs = (top, _vray(1, "A"), _vray(2, "B"), FakeMtl(3, classids.VRAY_BITMAP, "T", {}, classids.SC_TEXMAP))
                peeled = mat.MaterialConverter(FakeGraph(*objs)).peel(0)[0]
                conv = mat.MaterialConverter(FakeGraph(*objs))
                self.assertEqual(conv.source_for(0, 0), 0 if peeled is None else peeled)
                self.assertEqual((dict(conv.stats.peeled), conv._peels), ({}, {}))

    def test_peel_and_source_for_share_the_wrapper_test(self):
        """peel() and source_for's walk stop on one predicate (_is_wrapper), so a wrapper class added there reaches
        both (maxdrop-6n0.7.5): each asks it of every object it walks."""
        objs = (_wrapper(0, classids.VRAY_MTL_WRAPPER, {0: Ref(1)}), _vray(1, "A"),
                _wrapper(2, classids.VRAY_MTL_WRAPPER, {0: Ref(1)}))
        for walk in ("peel", "source_for"):
            conv = mat.MaterialConverter(FakeGraph(*objs))
            asked, real = [], conv._is_wrapper
            conv._is_wrapper = lambda m, key: asked.append(m.index) or real(m, key)
            self.assertEqual(conv.peel(0) if walk == "peel" else conv.source_for(2, 0), (1, None) if walk == "peel"
                             else 1)
            self.assertEqual(asked, [0, 1] if walk == "peel" else [2, 1], walk)

    def test_source_for_walks_each_wrapper_once(self):
        """An unpeeled wrapper many IDs wrap onto is walked once, not once per ID: a curve of 1000 IDs, half on a
        CoronaLayeredMtl without a base and a long layers table (every layer off but the last), no line."""
        layers = [Ref(4)] * 500
        objs = (_vray(4, "Base"), _corona(30, classids.CORONA_LAYERED_MTL, p1000=Ref(None), p1001=layers,
                                          p1004=[0] * 499 + [1]),
                _multi(6, [(0, Ref(4), 1), (1, Ref(30), 1)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        calls, sub = collections.Counter(), conv._sub

        def counting(m, key):
            calls[m.index] += 1
            return sub(m, key)
        conv._sub = counting
        desc = _desc(curves={"c": ([1], [(0, k) for k in range(1, 1000)])})
        mat.assign(desc, {1: 6}, conv)
        self.assertEqual(desc.issues, [])
        self.assertEqual(dict(calls), {30: 1})

    def test_source_for_wrapper_around_multi(self):
        """A wrapper not yet peeled around a Multi/Sub-Object is looked up by the ID below it, as material_for
        converts it; a wrapper and a Multi/Sub-Object around each other give nothing, as material_for does."""
        objs = (_vray(4, "A"), _vray(5, "B"), _multi(6, [(0, Ref(4), 1), (1, Ref(5), 1)]),
                _wrapper(50, classids.VRAY_MTL_WRAPPER, {0: Ref(6)}),
                _wrapper(51, classids.VRAY_2SIDED_MTL, {0: Ref(50)}),
                _multi(7, [(0, Ref(52), 1), (1, Ref(51), 1)]),
                _wrapper(52, classids.VRAY_MTL_WRAPPER, {0: Ref(7)}))
        for top in (50, 51, 7, 52):
            for mid in range(4):
                with self.subTest((top, mid)):
                    conv = mat.MaterialConverter(FakeGraph(*objs))
                    ir = mat.MaterialConverter(FakeGraph(*objs)).material_for(top, mid)
                    self.assertEqual(conv.source_for(top, mid), ir and ir.index)
                    self.assertEqual((dict(conv.stats.peeled), conv._peels, conv._done), ({}, {}, {}))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        self.assertEqual([conv.source_for(51, mid) for mid in range(3)], [4, 5, 4])
        self.assertIsNone(conv.source_for(52, 0))

    def test_curve_mixed_ids_bounded(self):
        """The mixed-ID check asks source_for once per distinct (material, ID) pair, whatever the number of splines
        and users: a curve with no mix (where the check cannot stop early) over 40 users and 120 splines."""
        objs = (_vray(4, "Plain"), _vray(5, "Other"), _multi(6, [(k, Ref(4), 1) for k in range(12)]),
                _multi(7, [(k, Ref(5), 1) for k in range(12)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        calls, source_for = collections.Counter(), conv.source_for

        def counting(index, material_id):
            calls[(index, material_id)] += 1
            return source_for(index, material_id)
        conv.source_for = counting
        rng = random.Random(147)
        users = list(range(100, 140))
        materials = {u: (6, 7, 4, None)[k % 4] for k, u in enumerate(users)}
        splines = [tuple(rng.sample(range(12), rng.randint(2, 5))) for _ in range(120)]
        desc = _desc(curves={"c": (users, splines)})
        plan = mat.assign(desc, materials, conv)
        self.assertEqual(len(plan.curves["c"].slots), 1)
        self.assertEqual(desc.issues, [])
        self.assertEqual(max(calls.values()), 1)
        self.assertLessEqual(sum(calls.values()), 4 * 12)

    def test_curve_mixed_ids_last_spline_last_user(self):
        """Only the last spline mixes, and only for the last user: the line names that spline and the first user."""
        objs = (_vray(4, "Plain"), _vray(5, "Other"), _multi(6, [(0, Ref(4), 1), (1, Ref(5), 1), (2, Ref(4), 1)]))
        conv = mat.MaterialConverter(FakeGraph(*objs))
        users = list(range(1, 31))
        materials = dict.fromkeys(users, 4)
        materials[30] = 6
        splines = [(0, 2) if k % 2 else k % 3 for k in range(49)] + [(2, 1)]
        desc = _desc(curves={"c": (users, splines)})
        mat.assign(desc, materials, conv)
        self.assertEqual(desc.issues, [(1, "shape: spline 50 mixes material IDs 3, 2: drawn with ID 3's material "
                                           "(its first segment's)")])

    def test_curve_mixed_ids_match_reference(self):
        """The same result as the unbounded check (every user, every spline, every ID) on random curves: entries on,
        off, empty, wrapped (peeled or not) and nested, users sharing a material, plain or without one."""
        def reference(cd, materials, conv):
            for n, sd in enumerate(cd.splines):
                ids = sd.material_ids
                if len(ids) < 2:
                    continue
                for u in cd.users:
                    first = conv.source_for(materials.get(u), ids[0])
                    if any(conv.source_for(materials.get(u), mid) != first for mid in ids[1:]):
                        return (cd.users[0], "shape: spline %d mixes material IDs %s: drawn with ID %d's material "
                                "(its first segment's)" % (n + 1, ", ".join(str(m + 1) for m in ids), ids[0] + 1))
            return None

        outcomes = set()
        for seed in range(60):
            rng = random.Random(seed)
            plain = [10, 11, 12]
            leaves = plain + [None, 30, 31, 24]

            def entries(choices):
                return [(rng.randrange(6), Ref(rng.choice(choices)), rng.random() > 0.2)
                        for _ in range(rng.randint(1, 5))]
            objs = [_vray(i, "P%d" % i) for i in plain]
            objs += [_multi(i, entries(leaves)) for i in (20, 21, 22, 23)]
            objs += [_multi(24, entries(plain + [None]))]
            objs += [_wrapper(30, classids.VRAY_MTL_WRAPPER, {0: Ref(rng.choice(plain))}),
                     _wrapper(31, classids.VRAY_2SIDED_MTL, {0: Ref(rng.choice(plain))})]
            users = list(range(1, rng.randint(1, 9)))  # none at times
            materials = {u: rng.choice([None, 10, 20, 21, 22, 23, 30]) for u in users if rng.random() > 0.1}
            splines = [tuple(rng.sample(range(9), rng.randint(1, 4))) for _ in range(rng.randint(1, 8))]
            cd = types.SimpleNamespace(users=users, splines=[_spline(t) for t in splines])
            convs = [mat.MaterialConverter(FakeGraph(*objs)) for _ in range(2)]
            for conv in convs:  # the slots' IDs peeled, as _group leaves them
                for t in splines[::2]:
                    for u in users:
                        conv.material_for(materials.get(u), t[0])
            want = reference(cd, materials, convs[0])
            self.assertEqual(mat._mixed(cd, materials, convs[1]), want, seed)
            outcomes.add(want is None)
        self.assertEqual(outcomes, {True, False})

    def test_fixture_curves(self):
        """shapes_more: FixtureCurveStd has a Standard material, FixtureCurveMulti a Multi/Sub-Object (ID 1:
        FixtureCurveSubOne); FixtureCurveIds the same Multi/Sub-Object on splines at IDs 2 and 1, FixtureCurveMixed
        on one spline at IDs 2, 1, 1; the other shapes none."""
        cf, graph, _by_name = _fixture("shapes_more")
        with cf:
            s = reader_scene.Scene.from_file(cf)
            desc = importlib.import_module(_PKG + ".convert.scene").describe(s, 0.001, None)
            plan = mat.assign(desc, mat.node_materials(s, desc), mat.MaterialConverter(graph))
        names = {n.index: n.name for n in desc.nodes}
        got = {names[p.users[0]]: (self.names(p.slots), p.indices.tolist()) for p in plan.curves.values()}
        self.assertEqual(got, {"FixtureCurveStd": ([["FixtureCurveRed"]], [0]),
                               "FixtureCurveMulti": ([["FixtureCurveSubOne"]], [0]),
                               "FixtureCurveIds": ([["FixtureCurveSubOne"], ["FixtureCurveSubTwo"]], [1, 0]),
                               "FixtureCurveMixed": ([["FixtureCurveSubTwo"]], [0])})
        mixed = [r for i, r in desc.issues if names.get(i) == "FixtureCurveMixed"]
        self.assertEqual(mixed, ["shape: spline 1 mixes material IDs 2, 1: drawn with ID 2's material (its first "
                                 "segment's)"])


class FrameZeroParams(unittest.TestCase, Close):
    """pblock_animated: a parameter a controller holds converts to the controller's value at frame 0 (the oracle's
    controllers), not to the class default (maxdrop-em3.152)."""

    def setUp(self):
        self.cf, self.graph, self.by_name = _fixture("pblock_animated")
        self.addCleanup(self.cf.close)
        assets = importlib.import_module(_PKG + ".reader.assets")
        self.tex = texmaps.TexmapConverter(self.graph, assets.AssetTable.from_file(self.cf))
        self.conv = mat.MaterialConverter(self.graph, texmaps=self.tex)
        with open(os.path.join(FIXTURE_DIR, "pblock_animated.oracle.json"), encoding="utf-8") as f:
            oracle = {m["name"]: m for m in json.load(f)["material_graph"]}
        self.oracle = {(name, b["block_id"], c["id"], c["tab"]): c["value"]
                       for name, m in oracle.items() for b in m["blocks"] for c in b.get("controllers", ())}

    def want(self, name, block, pid, tab=0):
        v = self.oracle[(name, block, pid, tab)]
        return tuple(v) if isinstance(v, list) else float(v)

    def test_vray_mtl(self):
        """FixtureAnimVRay: diffuse (block 1, 1) and reflection_glossiness (block 1, 3) animated."""
        ir = self.conv.convert(self.by_name["FixtureAnimVRay"])
        self.close(ir.base_color.value, self.conv.swatches.color(self.want("FixtureAnimVRay", 1, 1)))
        self.close(ir.roughness.value, 1.0 - self.want("FixtureAnimVRay", 1, 3))  # brdf_useRoughness off
        self.assertNotAlmostEqual(ir.roughness.value, 0.0)  # the default glossiness 1.0 would give 0

    def test_vray_blend_mtl(self):
        """FixtureAnimBlend, block 0: blend (2) element 1 and texmap_blend_multiplier (4) element 0 animated; element 0
        of blend is stored."""
        m = self.conv.graph.get(self.by_name["FixtureAnimBlend"])
        self.close(m.param(2, 0, tab=1), self.want("FixtureAnimBlend", 0, 2, 1))
        self.close(m.param(2, 0, tab=0), (40 / 255, 50 / 255, 60 / 255))
        self.close(mat._num_tab(m, 4, 0, 100.0), self.want("FixtureAnimBlend", 0, 4, 0))
        self.close(mat._num_tab(m, 4, 1, -1.0), 100.0)  # stored

    def test_normal_map_multipliers(self):
        """FixtureAnimNormal: normal_map_multiplier and bump_map_multiplier animated, read as the normal map rule reads
        them (its Checker and Noise convert to nothing, so no NormalMap node is drawn here)."""
        ids = texmaps.NORMAL_MAPS[classids.VRAY_NORMAL_MAP]
        m = self.tex.graph.get(self.by_name["FixtureAnimNormal"])
        self.close(texmaps._num(m, ids.strength, 1.0), self.want("FixtureAnimNormal", 0, ids.strength))
        self.close(texmaps._num(m, ids.bump_strength, 1.0), self.want("FixtureAnimNormal", 0, ids.bump_strength))

    def test_part_params(self):
        """A part's block (a Standard shader's) resolves through the scene too: VRayMtl's block 1 stands in."""
        m = self.graph.get(self.by_name["FixtureAnimVRay"])
        part = reader_materials.Part(m.index, m.class_id, m.superclass, {0: m.block(1)}, {})
        self.assertIsInstance(mat._PartParams(part).param(1, 1), pblock.Animated)  # no scene: as stored
        self.close(mat._PartParams(part, self.graph.scene).param(1, 1), self.want("FixtureAnimVRay", 1, 1))

    def test_frame_zero_shapes(self):
        """A value of another shape than the parameter's type, or a fraction for an integer, stays the Animated."""
        params = importlib.import_module(_PKG + ".convert.params")
        s = self.graph.scene
        blend = self.graph.get(self.by_name["FixtureAnimBlend"]).block(0)
        color, mult = blend.get(2, 1), blend.get(4, 0)  # a Bezier Color, a Bezier Float (37.0)

        class Typed:
            def __init__(self, base_type):
                self.base_type = base_type

        class Block:
            def __init__(self, base_type):
                self._type = base_type

            def param(self, pid):
                return Typed(self._type)

        self.assertEqual(params.frame_zero(s, Block(13), 0, mult), 37)  # a radio button: a whole number
        self.assertIsInstance(params.frame_zero(s, Block(13), 0, mult), int)
        gloss = self.graph.get(self.by_name["FixtureAnimVRay"]).block(1).get(3)  # a Bezier Float at 0.41
        self.assertEqual(params.frame_zero(s, Block(13), 0, gloss), gloss)  # a fraction for an integer
        self.assertEqual(params.frame_zero(s, Block(2), 0, mult), mult)  # a float for a color
        self.assertEqual(params.frame_zero(s, Block(0), 0, color), color)  # a color for a float
        self.assertEqual(params.frame_zero(s, Block(22), 0, mult), mult)  # point4: not read
        self.assertEqual(params.frame_zero(None, Block(0), 0, mult), mult)  # no scene
        self.assertEqual(params.frame_zero(s, Block(0), 0, 0.5), 0.5)  # a stored value as it is

    def test_report_lines(self):
        """What a controller's read meets is reported once per material and line however often the rules read it
        (maxdrop-6n0.6.32): an approximation with the value, a controller left unread with its default."""
        from unittest import mock
        controllers = importlib.import_module(_PKG + ".reader.controllers")
        params = importlib.import_module(_PKG + ".convert.params")
        vray = self.by_name["FixtureAnimVRay"]
        diffuse, gloss = (self.graph.get(vray).block(1).get(pid).index for pid in (1, 3))
        real = controllers.parameter_value

        def value(scene, i):
            if i == diffuse:  # a color between two keys: interpolated, with its issue
                return (0.2, 0.4, 0.6), [controllers.Issue(None, i, None, None, controllers.KEYS_INTERPOLATED)]
            if i == gloss:  # another class
                return None, [controllers.Issue(None, i, None, None, controllers.UNKNOWN_CLASS)]
            return real(scene, i)

        with mock.patch.object(controllers, "parameter_value", value):
            conv = mat.MaterialConverter(self.graph, texmaps=self.tex)
            ir = conv.convert(vray)
            conv.convert(vray)
            conv.graph.get(vray).param(1, 1)  # read again: no second line
        self.close(ir.base_color.value, conv.swatches.color((0.2, 0.4, 0.6)))
        self.close(ir.roughness.value, 0.0)  # glossiness 1.0, the default
        lines = [(i, r) for i, r in conv.stats.issues if "at frame 0" in r]
        self.assertEqual(sorted(lines), sorted([
            (vray, "'FixtureAnimVRay': parameter 1 at frame 0 (controller %d): %s" % (
                diffuse, controllers.KEYS_INTERPOLATED)),
            (vray, "'FixtureAnimVRay': parameter 3 at frame 0 (controller %d): %s, %s" % (
                gloss, controllers.UNKNOWN_CLASS, params.DEFAULT_USED))]))

    def test_part_report_lines(self):
        """A Standard shader's controller lines go to the report under the material, once however often the rule
        reads the parameter; a read without an issue gives none."""
        from unittest import mock
        controllers = importlib.import_module(_PKG + ".reader.controllers")
        params = importlib.import_module(_PKG + ".convert.params")
        m = self.graph.get(self.by_name["FixtureAnimVRay"])
        part = reader_materials.Part(m.index, m.class_id, m.superclass, {0: m.block(1)}, {})
        heard = []
        value = mat._PartParams(part, self.graph.scene, lambda i, line: heard.append((i, line)), m).param(1, 1)
        self.close(value, self.want("FixtureAnimVRay", 1, 1))
        self.assertEqual(heard, [])  # read without an issue: no line

        class Typed(FakeBlock):
            def param(self, pid):
                return types.SimpleNamespace(base_type=2)

        std = _standard(0, classids.BLINN_SHADER, {1: pblock.Animated(9)}, name="Std")
        std.parts[2] = reader_materials.Part(50, classids.BLINN_SHADER, classids.SC_SHADER,
                                             {0: Typed(0, {1: pblock.Animated(9)})}, {})
        std.refs = {}  # no Texmaps object: the maps from block 3
        graph = FakeGraph(std)
        graph.scene = object()
        unknown = controllers.Issue(None, 9, None, None, controllers.UNKNOWN_CLASS)
        with mock.patch.object(controllers, "parameter_value", return_value=(None, [unknown])):
            conv = mat.MaterialConverter(graph)
            ir = conv.convert(0)
            mat._PartParams(std.parts[2], graph.scene, conv._issue_once, std).param(1, 0)  # read again
        self.close(ir.base_color.value, (150 / 255,) * 3)  # the default diffuse
        self.assertEqual([x for x in conv.stats.issues if "at frame 0" in x[1]], [
            (0, "'Std' shader: parameter 1 at frame 0 (controller 9): %s, %s"
             % (controllers.UNKNOWN_CLASS, params.DEFAULT_USED))])
        self.assertEqual(params.at_frame_zero(self.graph, heard.append).report, heard.append)


if __name__ == "__main__":
    unittest.main()
