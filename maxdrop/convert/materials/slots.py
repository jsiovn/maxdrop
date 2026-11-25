# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material slots of a mesh: the materials of each node and their assignment."""
from ...reader.errors import MaxFileError


class MeshSlots:
    """The material slots of one mesh or curve: users the object indices of the nodes sharing it
    (MeshDescription.users, CurveDescription.users); slots [[MaterialIR or None per user]] per slot (None: an empty
    slot); indices int32 per face (per spline for a curve), its slot."""
    __slots__ = ("users", "slots", "indices")

    def __init__(self, users, slots, indices):
        self.users, self.slots, self.indices = users, slots, indices

    def __repr__(self):
        return "MeshSlots(%d users, %d slots)" % (len(self.users), len(self.slots))


def shadow_catcher_users(plan):
    """The users of a MeshSlots whose every slot holds a shadow-catcher material (MaterialIR.shadow_catcher): none
    without a slot."""
    return [node for u, node in enumerate(plan.users)
            if plan.slots and all(s[u] is not None and s[u].shadow_catcher for s in plan.slots)]


class Slots(dict):
    """assign()'s result: {mesh key: MeshSlots}, and curves {curve key: MeshSlots} (mesh and curve keys can be
    equal: two dicts)."""
    __slots__ = ("curves",)

    def __init__(self):
        super().__init__()
        self.curves = {}


def node_materials(scene, desc):
    """{node object index: its material's object index, None without one} for the nodes of desc (a reader Scene
    and the SceneDescription made from it)."""
    out = {}
    for node in desc.nodes:
        try:
            out[node.index] = scene.node(node.index).material
        except MaxFileError:
            out[node.index] = None
    return out


def _group(users, ids, materials, conv):
    """(slots, slot of each id) for material IDs ids (distinct, ascending): each id keyed by the materials users get
    for it (material_for, by identity), one slot per key in order of first appearance. A single key without any
    material gives no slot."""
    groups, slots, slot_of_id = {}, [], []
    for mid in ids:
        irs = [conv.material_for(materials.get(u), mid) for u in users]
        k = tuple(id(ir) for ir in irs)  # the IRs stay referenced by slots: their ids are not reused
        if k not in groups:
            groups[k] = len(slots)
            slots.append(irs)
        slot_of_id.append(groups[k])
    if len(slots) == 1 and all(ir is None for ir in slots[0]):
        return [], [0] * len(slot_of_id)
    return slots, slot_of_id


def _mixed(cd, materials, conv):
    """The issue (node, text) of a curve whose spline mixes material IDs that some user gets different materials for
    (conv.source_for: the IDs without a slot are not converted), named once on its first user; None without one.
    Bounded for an untrusted file: one source_for per distinct (material, ID) pair of the mixed splines (users sharing
    a material asked once), then each spline by dict lookups. The cache lives in this call only (source_for answers
    the same whether a wrapper was peeled yet or not: its own walk shares peel()'s stop test)."""
    splines = [sd.material_ids for sd in cd.splines]
    mixed = {mid for ids in splines if len(ids) >= 2 for mid in ids}
    if not mixed:
        return None
    mats = list(dict.fromkeys(materials.get(u) for u in cd.users))
    kinds = {}  # the sources of an ID over mats -> a small int: IDs of one kind draw alike for every user
    kind = {mid: kinds.setdefault(tuple(conv.source_for(m, mid) for m in mats), len(kinds)) for mid in mixed}
    for n, ids in enumerate(splines):
        if len(ids) >= 2 and any(kind[mid] != kind[ids[0]] for mid in ids[1:]):
            return (cd.users[0], "shape: spline %d mixes material IDs %s: drawn with ID %d's material (its first "
                    "segment's)" % (n + 1, ", ".join(str(m + 1) for m in ids), ids[0] + 1))
    return None


def assign(desc, materials, conv):
    """Slots {mesh key: MeshSlots} for the meshes of desc, its curves {curve key: MeshSlots} for the curves of desc.
    materials: {node object index: material object index or None} (node_materials). A mesh's distinct face IDs,
    ascending, are grouped by the materials its users get for them (material_for, by identity): one slot per group
    in order of first appearance. A mesh whose only group has no material gets no slot. A curve's splines the same
    by their material IDs (SplineDescription.material), indices per spline; a curve none of whose users gets a
    material is left out. A spline mixing IDs that render differently adds an issue to desc.issues. A mesh light's
    emitter mesh (its nodes' emitter set) is left out: build.objects gives it the emitter's Emission material."""
    import numpy
    out, mixed = Slots(), []
    for key, cd in desc.curves.items():
        users = list(cd.users)
        per_spline = [sd.material for sd in cd.splines]
        ids = sorted(set(per_spline)) or [0]
        slots, slot_of_id = _group(users, ids, materials, conv)
        if slots:
            where = dict(zip(ids, slot_of_id))
            out.curves[key] = MeshSlots(users, slots, numpy.asarray([where[m] for m in per_spline], dtype=numpy.int32))
            mixed.append(_mixed(cd, materials, conv))
    emitters = {n.mesh for n in getattr(desc, "nodes", ()) if getattr(n, "emitter", None) is not None}
    for key, md in desc.meshes.items():
        if key in emitters:
            continue
        users = list(md.users)
        faces = numpy.asarray(md.material_indices, dtype=numpy.int64).ravel()
        ids, inverse = numpy.unique(faces, return_inverse=True)
        slots, slot_of_id = _group(users, ids.tolist(), materials, conv)
        indices = numpy.asarray(slot_of_id, dtype=numpy.int32)[inverse.ravel()] if len(faces) else \
            numpy.zeros(0, dtype=numpy.int32)
        out[key] = MeshSlots(users, slots, numpy.ascontiguousarray(indices, dtype=numpy.int32))
    desc.issues.extend(x for x in mixed if x is not None)  # once every material converted: none if one raises
    return out
