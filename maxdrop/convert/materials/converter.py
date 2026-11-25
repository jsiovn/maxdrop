# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""MaterialConverter: a material of the scene peeled to its rule and converted into a MaterialIR."""
from ...reader import classids, pblock
from ...reader.classdir import ClassId
from .. import colors, params
from .. import texmaps as _texmaps
from ..params import finite as _finite, flag as _flag, num as _num
from .ids import (
    ChunkError, CORONA_BASE, CORONA_LAYERS, CORONA_LAYERS_ON, CORONA_SELECT_INDEX, CORONA_SELECT_LIST,
    DOUBLE_SIDED_FACING_ON, GREY_SRGB, MAX_PEEL, MULTI_ENABLED, MULTI_IDS, MULTI_MATERIALS, SHELL_RENDER_INDEX,
    SHELL_SUBS, WRAPPER_STOPS, WRAPPERS,
)
from .ir import ConvertStats, Input, MapRef, MaterialIR
from .values import _scene_meters, class_name, mean
from .rules import RULES


class MaterialConverter:
    """Converts the materials of one MaterialGraph, each object once."""

    def __init__(self, graph, texmaps=None, swatches=None, meters=None):
        self.graph, self.texmaps = params.at_frame_zero(graph, self._issue_once), texmaps
        if swatches is None:
            swatches = texmaps.swatches if texmaps is not None else colors.of_graph(graph)
        self.swatches = swatches
        self.meters = meters if meters is not None else _scene_meters(graph)
        self.stats = ConvertStats()
        self._done, self._peels, self._counted = {}, {}, set()
        self._multis, self._for, self._reported = {}, {}, set()
        self._active = []  # the materials whose rule is running: a layer that comes back to one is a cycle
        self._bsdfs = {}  # id(MaterialIR) -> (the IR, the Principled BSDFs it draws): bsdf_count
        self._bases = {}  # object index -> peel()'s base found without peeling (None: the peel fails): source_for

    def rgb(self, m, pid, block, default, scale=1.0):
        """A swatch parameter as linear RGB by the scene's rule; default is the swatch value (0..1) used when the
        parameter is unusable; scale multiplies the swatch before the rule (which clamps it to 0..1)."""
        v = m.param(pid, block)
        if not (isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3])):
            v = default
        return self.swatches.color(tuple(c * scale for c in v[:3]) if scale != 1.0 else v)

    def mono_swatch(self, m, pid, block, default, ir=None):
        """A swatch parameter that stands for a number (an opacity color): the mean of the swatch as stored, each
        channel clamped to 0..1, with no swatch rule (see Colors above); default as rgb's. With ir, a colored swatch
        (channels apart by more than half a step) is an issue: Corona renders it per channel (maxdrop-6n0.6.35)."""
        v = m.param(pid, block)
        if not (isinstance(v, tuple) and len(v) >= 3 and all(_finite(c) for c in v[:3])):
            v = default
        v = tuple(min(1.0, max(0.0, c)) for c in v[:3])
        if ir is not None and max(v) - min(v) > 0.5 / 255:
            self.issue(m.index, "%s %r: opacity color (%.3f, %.3f, %.3f) drawn as its mean %.3f: Corona renders it per "
                       "channel" % ((class_name(m.superclass, m.class_id), m.name) + v + (mean(v),)), ir)
        return mean(v)

    def issue(self, index, reason, ir=None):
        self.stats.issues.append((index, reason))
        if ir is not None:
            ir.issues.append(reason)

    def _issue_once(self, index, reason):
        """An issue material_for finds again for every face ID, or a parameter's controller line (params.frame_zero)
        met at every read: reported once."""
        if (index, reason) not in self._reported:
            self._reported.add((index, reason))
            self.issue(index, reason)

    def to_map(self, m, ref, what, amount, invert=False, ir=None):
        """The MapRef of a reference found in material m's slot `what`: None for no reference or one that is not a
        map (an issue)."""
        if not isinstance(ref, pblock.Reference) or ref.index is None:
            return None
        if self.graph.superclass(ref.index) != classids.SC_TEXMAP:
            self.issue(m.index, "%s: object %d is not a map" % (what, ref.index), ir)
            return None
        return MapRef(ref.index, amount, invert)

    def map_ref(self, m, map_pid, on_pid, amount_pid, block, invert=False, ir=None, percent=True, default=None):
        """The MapRef of a map slot: None when it holds no map, is switched off or holds something else. The amount
        parameter is in percent, or a plain factor when not percent; default is the class's value of a missing
        one, in the same unit (None: full)."""
        if on_pid is not None and not _flag(m, on_pid, block, True):
            return None
        scale = 100.0 if percent else 1.0
        full = scale if default is None else default
        amount = 1.0 if amount_pid is None else max(0.0, _num(m, amount_pid, block, full) / scale)
        return self.to_map(m, m.param(map_pid, block), "parameter %d" % map_pid, amount, invert, ir)

    def is_class(self, index, superclass, class_id):
        try:
            m = self.graph.get(index)
        except ChunkError:
            return False
        return m.superclass == superclass and ClassId(*m.class_id) == class_id

    def bump_slot(self, ir, ref):
        """A map in a bump slot: a normal map class is the normal input, anything else a height map."""
        if ref is None:
            return
        if any(self.is_class(ref.index, classids.SC_TEXMAP, k) for k in _texmaps.NORMAL_MAPS):
            ir.normal = ref
        else:
            ir.bump = ref

    def _sub(self, m, key):
        """The sub-material a wrapper peels to: (object index or None, reason)."""
        if key == classids.SHELL_MTL:
            k = _num(m, SHELL_RENDER_INDEX, 0, 0.0)
            if k not in (0.0, 1.0):
                return None, "Shell Material: render index %r" % (k,)
            pids = (SHELL_SUBS[int(k)],)
        elif key == classids.CORONA_SELECT_MTL:
            return self._selected(m)
        else:
            pids = WRAPPERS[key]
        block = m.block(0)
        name = m.name or class_name(m.superclass, key)
        if key in WRAPPER_STOPS:
            slot, switch, shows = WRAPPER_STOPS[key]
            first = block.value(pids[0]) if block is not None else None
            if switch is not None and not _flag(m, switch, 0, True):
                return None, "%s: %s switched off: %s" % (name, slot, shows)
            if not isinstance(first, pblock.Reference) or first.index is None:
                return None, "%s: %s empty: %s" % (name, slot, shows)
        for pid in pids:
            values = block.value(pid) if block is not None else None
            for k, v in enumerate(values if isinstance(values, list) else [values]):
                if key == classids.CORONA_LAYERED_MTL and pid == CORONA_LAYERS:
                    on = m.param(CORONA_LAYERS_ON, 0, tab=k)
                    if _finite(on) and not on:
                        continue
                if isinstance(v, pblock.Reference) and v.index is not None:
                    if self.graph.superclass(v.index) != classids.SC_MATERIAL:
                        return None, "%s: sub-material %d is not a material" % (name, v.index)
                    if key == classids.DOUBLE_SIDED_MTL and pid == 0 and not _flag(m, DOUBLE_SIDED_FACING_ON, 0, True):
                        self._issue_once(m.index, "%s: facing material switched off: drawn all the same, as V-Ray "
                                         "renders it (the scanline renders it black)" % name)
                    if key == classids.VRAY_BLEND_MTL and pid != pids[0]:
                        self._issue_once(m.index, "%s: base material empty: drawn as its coat, which V-Ray renders "
                                         "over nothing (transparent where the blend is below white)" % name)
                    return v.index, None
        return None, "%s: no sub-material" % name

    def _selected(self, m):
        """CoronaSelectMtl: the material at selected (zero-based: its default is 0) in materials."""
        k = m.param(CORONA_SELECT_INDEX, 0)
        values = m.block(0).value(CORONA_SELECT_LIST) if m.block(0) is not None else None
        name = m.name or "CoronaSelectMtl"
        if not isinstance(k, int) or isinstance(k, bool) or not isinstance(values, list) or not 0 <= k < len(values):
            return None, "%s: selected %r has no material" % (name, k)
        v = values[k]
        if not isinstance(v, pblock.Reference) or v.index is None:
            return None, "%s: selected %d is empty" % (name, k)
        if self.graph.superclass(v.index) != classids.SC_MATERIAL:
            return None, "%s: sub-material %d is not a material" % (name, v.index)
        return v.index, None

    def corona_layers(self, m):
        """The layers of a CoronaLayeredMtl that are on and set: [(table position, object index)]."""
        block = m.block(0)
        values = block.value(CORONA_LAYERS) if block is not None else None
        out = []
        for k, v in enumerate(values if isinstance(values, list) else []):
            on = m.param(CORONA_LAYERS_ON, 0, tab=k)
            if (_finite(on) and not on) or not isinstance(v, pblock.Reference) or v.index is None:
                continue
            out.append((k, v.index))
        return out

    def bsdf_count(self, ir):
        """The Principled BSDFs build/materials/ draws for ir: one, plus its layers' at each use (a reflection
        weight's twin not counted: each BSDF draws at most one)."""
        k = id(ir)
        if k not in self._bsdfs:
            self._bsdfs[k] = (ir, 1 + sum(self.bsdf_count(layer.ir) for layer in ir.layers))
        return self._bsdfs[k][1]

    def _mixes_layers(self, m):
        """A CoronaLayeredMtl with a base and a layer on is a material of its own (corona_layered_mtl); without either
        it is a wrapper of the one it has."""
        base = m.param(CORONA_BASE, 0)
        return isinstance(base, pblock.Reference) and base.index is not None and bool(self.corona_layers(m))

    def _is_wrapper(self, m, key):
        """Material object m (ClassId key) stands for another one: peel() and source_for walk through it, stopping on
        anything else (not a material, not in WRAPPERS or the Shell, a CoronaLayeredMtl that mixes its layers)."""
        return m.superclass == classids.SC_MATERIAL and (key in WRAPPERS or key == classids.SHELL_MTL) and not (
            key == classids.CORONA_LAYERED_MTL and self._mixes_layers(m))

    def peel(self, index):
        """(object index of the material a wrapper stands for, None), the index itself for an object that is no
        wrapper; (None, reason) when the peel ends without a material. The depth guard counts from index, so the
        same chain can fail from its top and succeed from lower down; the wrappers a failed peel walked through are
        counted in stats.peeled all the same."""
        if index in self._peels:
            return self._peels[index]
        chain, i, out = [], index, None
        while out is None:
            try:
                m = self.graph.get(i)
            except ChunkError as e:
                out = (None, "object %d: %s" % (i, e))
                break
            key = ClassId(*m.class_id)
            if not self._is_wrapper(m, key):
                out = (i, None)
                break
            if len(chain) == MAX_PEEL:
                out = (None, "more than %d wrappers below object %d" % (MAX_PEEL, index))
                break
            if i not in self._counted:
                self._counted.add(i)
                self.stats.peeled[class_name(m.superclass, key)] += 1
            chain.append(i)
            sub, reason = self._sub(m, key)
            if sub is None:
                out = (None, reason)
            elif sub in chain:
                out = (None, "wrapper cycle through object %d" % sub)
            i = sub
        self._peels[index] = out
        return out

    def convert(self, index):
        """The MaterialIR of material object index, None for no index (a node without a material) or an object
        that is not a material."""
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        if index in self._done:
            return self._done[index]
        if self.graph.superclass(index) != classids.SC_MATERIAL:
            return None
        base, reason = self.peel(index)
        if base is None:
            ir = self._grey(index, reason)
        elif base != index:
            ir = self.convert(base)
        elif self.is_class(index, classids.SC_MATERIAL, classids.MULTI_SUB_MTL):
            ir = self._multi_default(index)
        elif index in self._active or len(self._active) >= MAX_PEEL:
            reason = ("material cycle through object %d" % index if index in self._active else
                      "more than %d layered materials below object %d" % (MAX_PEEL, self._active[0]))
            # Not kept for this object, but the materials converting above it keep IRs built around the grey:
            # only a damaged or crafted file (3ds Max authors neither a cycle nor 8 nested layered materials) gets
            # a result that depends on the order of conversion.
            return self._grey(index, reason)
        else:
            self._active.append(index)
            try:
                ir = self._rule(index)
            finally:
                self._active.pop()
        self._done[index] = ir
        return ir

    def _multi(self, index):
        """(entries {zero-based material ID: sub-material object index or None (off or empty)} of a Multi/Sub-Object,
        the IDs in list order: _entry wraps past the highest of them)."""
        if index in self._multis:
            return self._multis[index]
        block = self.graph.get(index).block(0)
        values = (lambda pid: block.value(pid)) if block is not None else (lambda pid: None)
        materials, enabled, ids = values(MULTI_MATERIALS), values(MULTI_ENABLED), values(MULTI_IDS)
        materials = materials if isinstance(materials, list) else []
        enabled = enabled if isinstance(enabled, list) else []
        if not isinstance(ids, list):
            ids = list(range(len(materials)))
        entries, order = {}, []
        for k, mid in enumerate(ids):
            if not isinstance(mid, int) or isinstance(mid, bool) or mid < 0 or mid in entries:
                continue
            ref = materials[k] if k < len(materials) else None
            on = enabled[k] if k < len(enabled) else 1
            off = _finite(on) and not on
            sub = None if off or not isinstance(ref, pblock.Reference) else ref.index
            entries[mid] = sub
            order.append(mid)
        self._multis[index] = entries, order
        return entries, order

    def _multi_default(self, index):
        """The IR of a Multi/Sub-Object for a caller without face IDs: its first entry that is on and set."""
        entries, order = self._multi(index)
        for mid in order:
            if entries[mid] is not None:
                ir = self.material_for(index, mid)
                if ir is not None:
                    return ir
        try:
            name = self.graph.get(index).name or "Multi/Sub-Object"
        except ChunkError:
            name = "Multi/Sub-Object"
        return self._grey(index, "%s: no sub-material" % name)

    def _entry(self, index, material_id):
        """The entry (sub-material object index or None) zero-based face ID material_id picks in Multi/Sub-Object
        index. An ID without an entry wraps modulo the highest ID of the list plus one, entries switched off or empty
        counted: what 3ds Max renders (one-based, as Max shows them: with IDs 3 and 7, face ID 10 gets 3, 14
        gets 7, 15 none). A negative ID never wraps: no entry."""
        entries, order = self._multi(index)
        if material_id not in entries and order and material_id >= 0:
            material_id %= max(order) + 1
        return entries.get(material_id)

    def material_for(self, index, material_id):
        """The MaterialIR a face with that zero-based material ID renders with under material object index: wrappers
        peeled, Multi/Sub-Objects looked up by the ID (_entry; nested ones with the same ID); None for no material,
        an ID without an entry after the wrap, an entry switched off or empty, or a Multi/Sub-Object cycle or chain
        deeper than MAX_PEEL (an issue)."""
        key = (index, material_id)
        if key in self._for:
            return self._for[key]
        chain, i, out = [], index, None
        while True:
            if not isinstance(i, int) or isinstance(i, bool) or self.graph.superclass(i) != classids.SC_MATERIAL:
                if chain and isinstance(i, int) and not isinstance(i, bool):
                    self._issue_once(chain[-1], "Multi/Sub-Object %d: sub-material %d is not a material"
                                     % (chain[-1], i))
                break
            base, _reason = self.peel(i)
            if base is None or not self.is_class(base, classids.SC_MATERIAL, classids.MULTI_SUB_MTL):
                out = self.convert(i)
                break
            if base in chain:
                self._issue_once(index, "Multi/Sub-Object cycle through object %d" % base)
                break
            if len(chain) == MAX_PEEL:
                self._issue_once(index, "more than %d nested Multi/Sub-Objects below object %d" % (MAX_PEEL, index))
                break
            chain.append(base)
            i = self._entry(base, material_id)
        self._for[key] = out
        return out

    def source_for(self, index, material_id):
        """The material object index material_for(index, material_id) converts, None where it gives none, found
        without converting or counting anything (no peel kept): Multi/Sub-Objects looked up by the ID, wrappers
        through peel()'s result or, for one peel() has not walked yet, its walk over _sub again (the same stop test,
        _is_wrapper, from the same object, so the same base; kept in _bases, one walk per object as peel() pays); a
        wrapper whose peel fails is its own answer (its grey IR is its own). To compare IDs that get no slot."""
        def base_of(j):
            if j in self._peels:
                return self._peels[j][0]
            if j not in self._bases:
                self._bases[j] = walk(j)
            return self._bases[j]

        def walk(j):
            chain = []
            while True:
                try:
                    m = self.graph.get(j)
                except ChunkError:
                    return None
                key = ClassId(*m.class_id)
                if not self._is_wrapper(m, key):
                    return j
                if len(chain) == MAX_PEEL:
                    return None
                chain.append(j)
                j = self._sub(m, key)[0]
                if j is None or j in chain:
                    return None

        seen, i = [], index
        while isinstance(i, int) and not isinstance(i, bool) and i not in seen and len(seen) <= MAX_PEEL:
            if self.graph.superclass(i) != classids.SC_MATERIAL:
                return None
            seen.append(i)
            base = base_of(i)
            if base is None or not self.is_class(base, classids.SC_MATERIAL, classids.MULTI_SUB_MTL):
                return i if base is None else base
            i = self._entry(base, material_id)
        return None

    def _grey(self, index, reason):
        """The grey material for an object no rule converts, named after it."""
        try:
            m = self.graph.get(index)
            name, source = m.name, class_name(m.superclass, m.class_id)
        except ChunkError:
            name, source = "", ""
        g = colors.srgb_to_linear(GREY_SRGB)
        ir = MaterialIR(index, name, source, base_color=Input((g, g, g)), unknown=True)
        if reason:
            self.issue(index, reason, ir)
        return ir

    def _rule(self, index):
        try:
            m = self.graph.get(index)
        except ChunkError as e:
            return self._grey(index, "object %d: %s" % (index, e))
        source = class_name(m.superclass, m.class_id)
        rule = RULES.get((m.superclass, ClassId(*m.class_id)))
        if rule is None:
            self.stats.unknown[source] += 1
            return self._grey(index, "")
        ir = MaterialIR(index, m.name, source)
        made = rule(self, m, ir)
        if made is not None:  # a rule that builds its IR from others' (corona_layered_mtl): textures done
            return made
        if self.texmaps is not None:
            ir.textures = _texmaps.texture_graphs(ir, self.texmaps)
            for g in ir.textures.values():
                ir.issues.extend(g.issues)
        return ir
