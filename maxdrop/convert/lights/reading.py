# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A light's parameter blocks read into one dictionary: read_params()."""
from ... import pathnames
from ...reader import classids, pblock
from ..params import finite
from .ids import (
    _AMBIENT, _CONE, _DECAY, _IES_FILE, _IES_PARAMS, _NAMES, _NO_DIFFUSE, _NO_SPECULAR, _OLD_COLOR, _OLD_DEFAULTS,
    _OLD_FALLOFF, _OLD_HOTSPOT, _OLD_MULTIPLIER, _OLD_NAMES, _OLD_START, _ON, _OVERSHOOT, _PHOTOMETRIC,
    _PHOTOMETRIC_FILE, _PHOTOMETRIC_PARAMS, _SHADOW, _STANDARD, _SUN_PARAMS, ChunkError, CLASS, DECAY_NONE, DEFAULTS,
    DIRECT, IES, LightError, MESH_OBJECT, MISSING, OMNI, P_MESH_SOURCE, P_TEXMAP, PHOTOMETRIC, SKYLIGHT, SLOT_BLOCK,
    SLOT_MESH, STANDARD, SUN,
)
from .families import light_class


def _value(block, pid, issues, default=None, name=None):
    if name is None:
        default, name = DEFAULTS[pid], _NAMES[pid]
    v = block.get(pid)
    if isinstance(v, pblock.Animated):
        issues.append("%s is animated: %r is used" % (name, default))
        return default
    if isinstance(default, tuple):
        ok = isinstance(v, tuple) and len(v) >= 3 and all(finite(c) for c in v[:3])
        return tuple(float(c) for c in v[:3]) if ok else default
    if not finite(v):
        return default
    return int(v) if isinstance(default, int) else float(v)


def read_params(scene, i, assets=None, ies_files=None):
    """(values of light object i, issues); LightError without its block. A VRayLight's are {parameter id: value} of
    every id of DEFAULTS, the others' {name: value} with CLASS; assets (reader.assets.AssetTable) names the file of
    a web or IES light; ies_files (convert.ies.Lookup) reads the IES file of a VRayIES whose power depends on it
    (override off, power above 0): values "photometry" (convert.ies.Photometry, or None) and "photometry_issue" (why
    a file found is not read, or None)."""
    family = light_class(scene, i)
    if family == STANDARD:
        return _read_standard(scene, i)
    if family == SKYLIGHT:
        return {CLASS: SKYLIGHT}, []
    if family in (PHOTOMETRIC, SUN, IES):
        return _read_blocks(scene, i, family, assets, ies_files)
    entry = scene.entry(i)
    refs = scene.refs(i)
    target = refs.get(SLOT_BLOCK)
    te = scene.entry(target) if target is not None and 0 <= target < len(scene) else None
    if te is None or te.superclass != classids.SC_PARAMETER_BLOCK2:
        raise LightError("no parameter block (reference slot 0)")
    block = pblock.ParamBlock2.from_chunk(scene.chunk(target), scene.refs(target), refs, len(scene),
                                          (entry.superclass, entry.class_id))
    issues = list(block.issues)
    values = {pid: _value(block, pid, issues) for pid in DEFAULTS}
    for pid in (P_TEXMAP, P_MESH_SOURCE):
        ref = block.get(pid)
        values[pid] = ref.index if isinstance(ref, pblock.Reference) else None
    own = refs.get(SLOT_MESH)
    values[MESH_OBJECT] = own if own is not None and 0 <= own < len(scene) else None
    return values, issues


def _blocks(scene, i):
    """({block id: ParamBlock2} of the ParamBlock2s light object i references (the first of each id), issues): a
    block that cannot be read is skipped, an issue (its id is unknown: a needed one then counts as missing)."""
    entry = scene.entry(i)
    refs = scene.refs(i)
    found, issues = {}, []
    for slot in sorted(refs):
        target = refs[slot]
        te = scene.entry(target) if target is not None and 0 <= target < len(scene) else None
        if te is None or te.superclass != classids.SC_PARAMETER_BLOCK2:
            continue
        try:
            block = pblock.ParamBlock2.from_chunk(scene.chunk(target), scene.refs(target), refs, len(scene),
                                                  (entry.superclass, entry.class_id))
        except ChunkError as exc:
            issues.append("the parameter block of reference %d cannot be read: %s" % (slot, exc))
            continue
        found.setdefault(block.block_id, block)
    return found, issues


def _asset(blocks, where, assets):
    """The reader.assets.AssetEntry at (block id, parameter id), None when there is none or the table lacks it."""
    block = blocks.get(where[0])
    return assets.entry(block.get(where[1])) if block is not None and assets is not None else None


def _file_name(entry):
    """The base name of an asset entry, None without one."""
    if entry is None:
        return None
    return pathnames.base_name(entry.path) or pathnames.base_name(entry.resolved) or None


def _read_blocks(scene, i, family, assets, ies_files=None):
    """The values of a photometric light, VRaySun or VRayIES: its parameters by name, its file's name."""
    spec, where = {PHOTOMETRIC: (_PHOTOMETRIC_PARAMS, _PHOTOMETRIC_FILE), SUN: (_SUN_PARAMS, None),
                   IES: (_IES_PARAMS, _IES_FILE)}[family]
    blocks, issues = _blocks(scene, i)
    if 0 not in blocks:
        raise LightError("no parameter block 0" + ("".join("; " + x for x in issues)))
    issues += [x for b in blocks.values() for x in b.issues]
    values = {CLASS: family}
    for name, (bid, pid, default) in spec.items():
        block = blocks.get(bid)
        values[name] = default if block is None else _value(block, pid, issues, default, name)
    for bid in sorted({bid for bid, _pid, _default in spec.values()} - set(blocks)):
        issues.append("parameter block %d is missing: its defaults are used" % bid)
    if family == PHOTOMETRIC:
        values["shape"] = _PHOTOMETRIC[scene.entry(i).class_id]
    entry = _asset(blocks, where, assets) if where else None
    values["file"] = _file_name(entry)
    if family == IES:
        values["photometry"] = values["photometry_issue"] = None
        if ies_files is not None and entry is not None and not values["override"] and values["power"] > 0:
            values["photometry"], values["photometry_issue"] = ies_files.photometry(entry.path, entry.resolved)
    return values, issues


def _u16(chunk, cid, default):
    c = chunk.first(cid) if chunk.container else None
    if c is None or c.container or c.payload_size < 2:
        return default
    return c.unpack("<H")[0]


def _read_standard(scene, i):
    """The values of a standard light: its old ParamBlock (reference 0) and the chunks of the light object."""
    entry = scene.entry(i)
    target = scene.refs(i).get(SLOT_BLOCK)
    if target is None or not 0 <= target < len(scene) or not scene.is_a(target, classids.SC_PARAMETER_BLOCK,
                                                                         classids.PARAM_BLOCK):
        raise LightError("no parameter block (reference slot 0)")
    block = pblock.ParamBlock.from_chunk(scene.chunk(target))
    issues = list(block.issues)
    kind = _STANDARD[entry.class_id]

    def old(index):
        default = _OLD_DEFAULTS[index]
        v = block.get(index)
        if isinstance(default, tuple):
            ok = isinstance(v, tuple) and len(v) >= 3 and all(finite(c) for c in v[:3])
            v = tuple(float(c) for c in v[:3]) if ok else None
        elif finite(v):
            v = float(v)
        else:
            v = None
        if v is None:
            issues.append(MISSING % (_OLD_NAMES[index], default))
            return default
        return v

    chunk = scene.chunk(i)

    def present(cid):
        return chunk.container and chunk.first(cid) is not None

    values = {CLASS: STANDARD, "shape": kind, "on": _u16(chunk, _ON, 1), "decay": _u16(chunk, _DECAY, DECAY_NONE),
              "color": old(_OLD_COLOR), "multiplier": old(_OLD_MULTIPLIER), "start": 0.0,
              "rectangle": kind != OMNI and _u16(chunk, _CONE, 1) == 0, "overshoot": present(_OVERSHOOT),
              "diffuse": not present(_NO_DIFFUSE), "specular": not present(_NO_SPECULAR),
              "ambient": present(_AMBIENT), "shadow": _u16(chunk, _SHADOW, 1)}
    if kind != DIRECT and values["decay"] != DECAY_NONE:  # unused otherwise: no issue when it is missing
        values["start"] = old(_OLD_START[kind])
    if kind != OMNI:
        values["hotspot"], values["falloff"] = old(_OLD_HOTSPOT), old(_OLD_FALLOFF)
    return values, issues
