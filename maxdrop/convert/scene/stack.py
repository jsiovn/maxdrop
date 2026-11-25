# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A node's modifier stack: evaluated modifiers, UVW Map, extrusions, and the layers."""
from ...reader import controllers, shapes
from .. import extrude, modifiers as rules, uvwmap
from .descriptions import _SPENT, ChunkError, LayerDescription, MAX_BUILT_CORNERS, MeshError
from .meshes import _merged_edges, _positions, mesh_description
from .nodes import _shape
from .rims import _large, _rim_edges, _unit, lowered


def _evaluated(scene, stacks, node, issues, i, shape):
    """(Extrude, UVW Maps, rest): the bottom run of node i's modifiers that render and are evaluated here
    (reader.modifiers Modifiers, bottom first), and the modifiers that render above it. On a shape the run starts
    with an Extrude (None without one: no UVW Map either, no rest); an Extrude or a UVW Map above another modifier
    is an issue."""
    try:
        st = stacks.object_stack(node.object)
    except ChunkError as exc:
        issues.append((i, "modifiers: the modifier stack cannot be read: %s" % exc))
        return None, (), ()
    active = [m for m in st.modifiers if m.renders]  # bottom first
    ext, start = None, 0
    if shape:
        if not (active and extrude.is_extrude(active[0])):
            if any(extrude.is_extrude(m) for m in active):
                issues.append((i, "extrude: an Extrude above %s is not evaluated: the shape is a curve" %
                               (_class_name(scene, active[0].index) or "another modifier")))
            return None, (), ()
        ext, start = active[0], 1
    maps = []
    for m in active[start:]:
        if not uvwmap.is_uvwmap(m):
            break
        maps.append(m)
    rest = active[start + len(maps):]
    if any(uvwmap.is_uvwmap(m) for m in rest):
        issues.append((i, "uvw map: a UVW Map above %s is not evaluated" %
                       (_class_name(scene, rest[0].index) or "another modifier")))
    return ext, tuple(maps), tuple(rest)


def _offset(t, i):
    """Node i's object offset (a reader matrix), None for the identity."""
    offset = t.offset(i)
    return None if offset == controllers.IDENTITY else offset


def _converted(scene, rest, meters, offset, told, convert):
    """(ModifierDescriptions, issues): the bottom run of rest (the modifiers that render above those evaluated,
    bottom first) that convert.modifiers turns into Blender modifiers. The first other modifier, or one the rules
    refuse, ends the run; each convertible modifier above it is an issue. A UVW Map left unapplied is not in rest
    (it changes no geometry). The rules' own issues are named once per modifier (told). convert False: nothing."""
    out, issues, stop = [], [], None
    if not convert:
        return (), []
    for m in rest:
        cls = _class_name(scene, m.index) or "another modifier"
        if stop is not None:
            if rules.is_convertible(m):
                issues.append("modifiers: %s above %s is not converted" % (cls, stop))
            continue
        if not rules.is_convertible(m):
            stop = cls
            continue
        first = m.index not in told
        told.add(m.index)
        try:
            md, more = rules.convert(scene, m, meters, offset)
        except rules.ModifierError as exc:
            issues.append("modifiers: %s not converted: %s" % (cls, exc))
            stop = cls
            continue
        out.append(md)
        if first:
            issues.extend("modifiers: %s: %s" % (cls, x) for x in more)
    return tuple(out), issues


def _split(scene, stack_modifiers, done, converted=()):
    """(applied, rest): the class names of the modifiers done (reader Modifiers, bottom first) and of the rest of the
    stack (object indices, top first) without them and without those converted (ModifierDescriptions)."""
    rest = list(stack_modifiers)
    for m in tuple(done) + tuple(converted):
        if m.index in rest:
            rest.remove(m.index)
    return tuple(_class_name(scene, m.index) for m in done), tuple(_class_name(scene, m) for m in rest)


def _mapping(scene, mapped, m, issues, node):
    """(Params, gizmo matrix) of UVW Map m, read once (mapped caches it; None when it is not evaluated: an issue on
    the first node only)."""
    if m.index not in mapped:
        mapped[m.index] = None
        try:
            params, more = uvwmap.read_params(scene, m)
            if not params.supported:
                issues.append((node, "uvw map: %s mapping is not evaluated: the stored channel stays" %
                               params.type_name))
            elif params.vertex_color:  # channel 0 is no UV layer: applying it would change nothing in Blender
                issues.append((node, "uvw map: the vertex color channel is not imported: not applied"))
            else:
                tm, gizmo_issues = uvwmap.gizmo(scene, m)
                mapped[m.index] = (params, tm)
                more = more + gizmo_issues
            issues.extend((node, "uvw map: %s" % x) for x in more)
        except uvwmap.UVWMapError as exc:
            issues.append((node, "uvw map: %s: the stored channel stays" % exc))
    return mapped[m.index]


def _mapped_mesh(scene, desc, mapped, key, data, maps, node, name, offset, meters, shading=None, check=None,
                 rim=False, mirrors=(), ranges=None, refusal="geometry: not built", above=()):
    """(the key in desc.meshes of reader MeshData data under the UVW Maps maps, the maps applied), made on first use:
    key extended by (modifier index, context matrix) per UVW Map evaluated, then by ("shading", shading) when a
    converted smoother changes the shading (SMOOTH: no sharp edge or flat face; CREASE: the sharp edges creased),
    then by ("rim", True) when a converted Shell's rim is hardened (_rim): the open edges join the sharp ones. Above
    the Mirrors mirrors (_mirrors), ("rim", their settings and mirror matrices) instead, and the open edges they
    weld shut stay smooth (_rim_edges): marked sharp, the weld would make them a hard seam. With Mirrors above right
    above the Shell (_seam; mirrors then those below it), ("seam", the settings and matrices of mirrors, those of
    above) before the shading entry; md.lowered and md.seam_issue say which of them go below the Shell (lowered()),
    and the rim is that of mirrors and those. check goes to
    mesh_description. (None, ()) when its positions do not fit single precision (MeshError: an issue), found before
    any UVW Map is read (the maps, the shading and the rim leave the positions as they are); ranges caches per key
    as given whether they fit, a refusal (its issue starts with refusal) then named on the first node only."""
    if ranges is not None and key in ranges:
        if not ranges[key]:
            return None, ()
    else:
        fits = True
        try:
            _positions(data, offset, meters)  # checked before the maps so a refused mesh gets no UVW Map issue
        except MeshError as exc:
            desc.issues.append((node, "%s: %s" % (refusal, exc)))
            fits = False
        if ranges is not None:
            ranges[key] = fits  # a flag: a kept MeshError's traceback would hold the refused mesh in memory
        if not fits:
            return None, ()
    usable = []
    for m in maps:
        found = _mapping(scene, mapped, m, desc.issues, node)
        if found is None:
            continue
        if m.context is None:
            desc.issues.append((node, "uvw map: no modifier context: the stored channel stays"))
            continue
        usable.append((m, found))
    key = key + tuple((m.index, m.context.tm) for m, _found in usable)
    if above:
        key = key + (("seam", tuple((m.settings, m.mirror) for m in mirrors),
                      tuple((m.settings, m.mirror) for m in above)),)
    if shading is not None:
        key = key + (("shading", shading),)
    if rim:
        key = key + (("rim", tuple((m.settings, m.mirror) for m in mirrors) or True),)
    md = desc.meshes.get(key)
    if md is None:
        done = []
        for m, (params, tm) in usable:
            try:
                data = uvwmap.apply(data, params, tm, m.context.tm)
                done.append(m)
            except uvwmap.UVWMapError as exc:
                desc.issues.append((node, "uvw map: %s: the stored channel stays" % exc))
        md = desc.meshes[key] = mesh_description(key, name, data, offset, meters, check)
        md.applied = tuple(done)
        if shading == rules.SMOOTH:
            md.sharp_faces[:] = False
            md.sharp_edges = md.sharp_edges[:0]
        if above:
            md.lowered, md.seam_issue = lowered(md, mirrors, above, _unit(offset, meters), _large(md, check))
        if rim:
            md.sharp_edges = _merged_edges(md.sharp_edges, _rim_edges(md, mirrors + tuple(above[:md.lowered]),
                                                                      _large(md, check)))
        md.creases = shading == rules.CREASE
        if md.dropped_faces:
            desc.issues.append((node, "geometry: %d faces with a repeated vertex or doubled, left out"
                                % md.dropped_faces))
        _name_zeroed(desc, md, node)
    md.users.append(node)
    return key, md.applied


def _name_zeroed(desc, md, node):
    """The issue of the UV coordinates of MeshDescription md that were not numbers, on node (none when there were
    none)."""
    if md.zeroed_uvs:
        desc.issues.append((node, "geometry: %d UV coordinates that are not numbers set to 0" % md.zeroed_uvs))


def _extruded(scene, desc, extrusions, mapped, base, ext, maps, node, name, offset, meters, shading=None, check=None,
              rim=False, mirrors=(), ranges=None, above=()):
    """(the key in desc.meshes of shape base under the Extrude ext and the UVW Maps maps, the maps applied), made on
    first use; (None, ()) when the shape or the Extrude cannot be read or the scene's MAX_BUILT_CORNERS are spent (an
    issue, once per base object and Extrude: _Extrusions), or when its positions do not fit single precision
    (_mapped_mesh, which gets ranges; the shape is then drawn as a curve)."""
    data = extrusions.get(base, ext, node)
    if isinstance(data, tuple):
        kind, text = data
        if kind != _SHAPE_KIND and extrusions.tell(base, ext):  # a refused shape: _shape named it
            desc.issues.append((node, "extrude: " + ("not made: " + text if kind == _SPENT_KIND else text)))
        return None, ()
    offset = None if offset == controllers.IDENTITY else offset
    return _mapped_mesh(scene, desc, mapped, (base, offset, ext.index), data, maps, node, name, offset, meters,
                        shading, check, rim, mirrors, ranges, "extrude: not made", above)


_SHAPE_KIND, _SPENT_KIND, _EXTRUDE_KIND = "shape", "spent", "extrude"  # why _Extrusions did not make one
_DROPPED = "dropped"  # an extrusion made, named and counted, whose MeshData is gone


class _Extrusions:
    """The extrusions of one scene's shapes, one per (shape base object, Extrude modifier index), shared by the shape's
    own nodes (_extruded) and the mesh lights that pick it (_emitter_shape): made, its shape and Extrude issues named
    (on the node that makes it) and its face corners counted against MAX_BUILT_CORNERS once (a refused adaptive
    Extrude's ExtrudeError.spent too, once for both paths). drop() lets the MeshData go once no node needs it; a mesh
    light after that gets the same mesh made again, naming and counting nothing. Mesh lights that pick one shape
    share its count as nodes of the shape at different offsets do (each still gets a mesh of its own in desc.meshes).
    A shape a mesh light reads first and the reader refuses is not kept in shape_of: the shape's own node reads it
    again and names the refusal (_shape), where a user looks for it. shape_of: the scene's reader Shapes (_shape);
    built: [face corners made so far]."""

    def __init__(self, scene, desc, shape_of, built):
        self.scene, self.desc, self.shape_of, self.built = scene, desc, shape_of, built
        self.made = {}  # base -> {Extrude index: MeshData, _DROPPED or (kind, text) why it is not made}
        self.told = set()  # (base, Extrude index) whose refusal a shape's node named

    def get(self, base, ext, node, light=False):
        """The reader MeshData of shape base under the Extrude ext (a reader Modifier) for node (light: a mesh light's),
        or (kind, text) why it is not made: _SHAPE_KIND (the shape is refused; text its reason), _SPENT_KIND
        (MAX_BUILT_CORNERS; text says so) or _EXTRUDE_KIND (the Extrude cannot be read or made)."""
        cache = self.made.setdefault(base, {})
        found = cache.get(ext.index)
        if found is None:
            found = cache[ext.index] = self._make(base, ext, node, light)
        elif found is _DROPPED:
            try:
                found, _issues = extrude.extrude(self.shape_of[base], extrude.read_params(self.scene, ext)[0])
            except ChunkError as exc:  # it did not fail the first time; a refusal all the same
                found = (_EXTRUDE_KIND, str(exc))
        return found

    def _make(self, base, ext, node, light):
        if light and base not in self.shape_of:
            try:
                sh = shapes.read_shape(self.scene, base)
            except ChunkError as exc:  # not kept: the shape's own node reads it again and names it
                return _SHAPE_KIND, str(exc)
            self.shape_of[base] = sh
            self.desc.issues.extend((node, "shape: %s" % x) for x in sh.issues)
        else:
            sh = _shape(self.scene, self.desc, self.shape_of, base, node)
        if sh is None:
            return _SHAPE_KIND, self.shape_of[base]
        if self.built[0] >= MAX_BUILT_CORNERS:
            return _SPENT_KIND, _SPENT % MAX_BUILT_CORNERS
        try:
            params, issues = extrude.read_params(self.scene, ext)
            data, more = extrude.extrude(sh, params)
        except ChunkError as exc:  # ExtrudeError, or a block the reader refuses
            self.built[0] += getattr(exc, "spent", 0)  # a refused adaptive Extrude made its points first
            return _EXTRUDE_KIND, str(exc)
        self.built[0] += len(data.loop_vertices)
        self.desc.issues.extend((node, "extrude: %s" % x) for x in issues + more)
        return data

    def tell(self, base, ext):
        """Whether a shape's node is the first to meet the refusal of base under ext (it names it then)."""
        key = (base, ext.index)
        if key in self.told:
            return False
        self.told.add(key)
        return True

    def drop(self, base):
        """The MeshData of base's extrusions let go; what they were (made, or why not) stays known."""
        cache = self.made.get(base, {})
        for index, found in cache.items():
            if not isinstance(found, tuple):
                cache[index] = _DROPPED


def _layer(scene, i, layers, issues, node):
    """The object index of node's layer i, or None (no layer, or a record that cannot be read: an issue, once per
    node); layers caches the reader records."""
    if i is None:
        return None
    if i not in layers:
        try:
            layers[i] = scene.layer(i)
        except ChunkError as exc:
            layers[i] = exc
    if isinstance(layers[i], ChunkError):
        issues.append((node, "layer: %s" % layers[i]))
        return None
    return i


def _layer_descriptions(scene, used):
    """The layers that hold a node and their parent layers, in the Layer Manager's order, every parent first."""
    records = {i: la for i, la in used.items() if not isinstance(la, ChunkError)}
    wanted = set()
    for la in list(records.values()):
        seen = set()
        while la is not None and la.index not in seen:  # parents are cycle-free; seen only bounds the walk
            seen.add(la.index)
            wanted.add(la.index)
            if la.parent is None:
                break
            try:
                la = records[la.parent] if la.parent in records else scene.layer(la.parent)
            except ChunkError:
                break
            records[la.index] = la
    out, done = [], set()
    for i in scene.layer_order():
        if i not in wanted or i in done:
            continue
        chain, j = [], i
        while j is not None and j in wanted and j not in done:
            chain.append(j)
            done.add(j)
            j = records[j].parent
        for j in reversed(chain):
            la = records[j]
            parent = la.parent if la.parent in wanted else None
            out.append(LayerDescription(j, la.name, parent, la.hidden, la.frozen, la.renderable))
    return out


def _class_name(scene, i):
    entry = scene.entry(i)
    return entry.name if entry is not None else ""
