# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The import report: what an import read and built, and what it did not convert, as text for the user.

    rep = gather(desc, source="scene.max", objects_built=n, meshes_built=m, dropped_uv_layers=k, pack=result)
    add_materials(rep, len(built.materials), builder.classes, conv.stats, tex.stats, index.report,
                  sockets=builder.sockets_skipped, blender=bpy.app.version_string,
                  swatches=conv.swatches)   # when materials were made
    rep.text()                          # the whole report, lines joined with "\n"
    rep.summary()                       # (level, line): "INFO" when nothing was approximated or left out, else
                                        # "WARNING"

Modifiers have three outcomes, counted per class once per node whose stack holds one: applied (baked into the
mesh), converted (to a Blender modifier) and ignored (the object arrives as its base object, a "not applied" left
out). gather() counts every modifier of the description as ignored: no modifier is evaluated yet;
rep.add_modifiers(outcome, class names) counts one node's modifiers under an outcome.

desc is a convert.scene.SceneDescription. The counts of what build/ made default to the description's own. pack is
the result of maxdrop.intake.archive.unpack() when the import started from a scene pack (read by attribute, so
this module never imports the intake package), and pack_name the archive's file name: its block comes first.
add_materials takes the counters of convert.materials (MaterialConverter.stats), convert.texmaps
(TexmapConverter.stats), the texture lookup (convert.textures.TextureReport), build.materials and the scene's
swatch rule (convert.colors.Swatches: its line, and its note as an issue when the file did not say), all read by
attribute. The blocks follow the order of the log of the 3ds Max -> FBX exporter these rules come from: the scene,
the materials, the textures. A texture not found in a scene just unpacked from a pack says whether the archive
held a file of that name and why it was not written: that tells an archive at fault from the lookup.

The report names nodes and files of the user's scene: it is shown to the user and never written into the
repository. Lists are cut after MAX_LISTED entries. No bpy.
"""
import collections
import os

from ..reader import controllers
from . import textures

MAX_LISTED = 50
APPLIED, CONVERTED, IGNORED = "applied", "converted", "ignored"
LEVEL_INFO, LEVEL_WARNING = "INFO", "WARNING"
GEOMETRY = "geometry: "
UNKNOWN_CONTROLLER = "transform: " + controllers.UNKNOWN_CLASS  # convert.scene's wording of that issue


class Report:
    """Counters and lists of one import. issues and geometry_errors are [(node label, reason)], material_issues
    [(material or map object index, reason)]. materials_built is None when the import made no materials."""
    __slots__ = ("source", "unit", "meters", "nodes", "objects_built", "meshes_built", "layers", "hidden_layers",
                 "hidden", "unrenderable", "frozen", "groups", "placeholders", "unknown_controllers", "modifiers",
                 "modifiers_applied", "modifiers_converted",
                 "dropped_uv_layers", "unknown_controller_nodes", "geometry_errors", "issues", "pack", "pack_name",
                 "materials_built", "materials", "wrappers", "grey_materials", "maps_peeled", "maps_unsupported",
                 "sockets_skipped", "blender", "textures_found", "textures_missing", "texture_search_stopped",
                 "material_issues", "swatches")

    def __init__(self, source=""):
        self.source, self.unit, self.meters = source, None, 1.0
        self.nodes = self.objects_built = self.meshes_built = self.layers = self.hidden_layers = 0
        self.hidden = self.unrenderable = self.frozen = self.groups = self.dropped_uv_layers = 0
        self.unknown_controller_nodes = 0  # their issues, listed by class in unknown_controllers instead
        self.placeholders = collections.Counter()
        self.unknown_controllers = collections.Counter()
        self.modifiers = collections.Counter()  # class name -> nodes whose stack holds it, ignored (not applied)
        self.modifiers_applied = collections.Counter()  # class name -> nodes, baked into the mesh
        self.modifiers_converted = collections.Counter()  # class name -> nodes, as a Blender modifier
        self.geometry_errors, self.issues = [], []
        self.pack, self.pack_name = None, ""
        self.materials_built, self.blender = None, ""
        self.materials = collections.Counter()  # class name -> materials converted by its rule
        self.wrappers = collections.Counter()  # class name -> wrapper objects peeled
        self.grey_materials = collections.Counter()  # class name -> materials without a rule, made grey
        self.maps_peeled = collections.Counter()  # class name -> map objects peeled to the map below
        self.maps_unsupported = collections.Counter()  # class name -> map objects without a usable map below
        self.sockets_skipped = collections.Counter()  # Principled input name -> materials that needed it
        self.textures_found = []  # [(lookup rule name, files found)] in lookup order
        self.textures_missing, self.texture_search_stopped, self.material_issues = [], [], []
        self.swatches = ""  # how color swatches were made linear (the scene's gamma)

    def add_modifiers(self, outcome, class_names):
        """Count one node's modifiers under outcome (APPLIED, CONVERTED or IGNORED): each class once."""
        counter = {APPLIED: self.modifiers_applied, CONVERTED: self.modifiers_converted,
                   IGNORED: self.modifiers}[outcome]
        counter.update(set(class_names))

    @property
    def approximated(self):
        """How many things were converted only in part: wrappers peeled to a sub-material, maps to the map below."""
        return sum(self.wrappers.values()) + sum(self.maps_peeled.values())

    @property
    def left_out(self):
        """How many things were not converted: placeholders, nodes with modifiers not applied, texture files not
        found, and the issues (_problems)."""
        return (sum(self.placeholders.values()) + sum(self.modifiers.values()) + len(self.textures_missing)
                + self._problems())

    def _problems(self):
        """UV channels without room, unknown controllers, geometry errors, materials without a rule, maps without a
        usable map below, Principled inputs this Blender lacks (per material), material issues, other issues."""
        return (len(self.geometry_errors) + len(self.issues) + self.dropped_uv_layers + self.unknown_controller_nodes
                + sum(self.grey_materials.values()) + sum(self.maps_unsupported.values())
                + sum(self.sockets_skipped.values()) + len(self.material_issues))

    def summary(self):
        """(level, one line) for the operator's report."""
        name = self.source or "the scene"
        built = "%s, %s" % (_plural(self.objects_built, "object"), _plural(self.meshes_built, "mesh", "meshes"))
        if self.materials_built is not None:
            built += ", " + _plural(self.materials_built, "material")
        if not self.left_out and not self.approximated:
            return LEVEL_INFO, "Imported %s: %s, nothing left out." % (name, built)
        parts = []
        if self.placeholders:
            parts.append(_plural(sum(self.placeholders.values()), "placeholder"))
        if self.modifiers:
            parts.append(_plural(sum(self.modifiers.values()), "modifier") + " not applied")
        if self.textures_missing:
            parts.append(_plural(len(self.textures_missing), "texture") + " missing")
        if self.approximated:
            parts.append("%d approximated" % self.approximated)
        problems = self._problems()
        if problems:
            parts.append(_plural(problems, "issue"))
        return LEVEL_WARNING, "Imported %s: %s; %s. See the text MaxDrop Report." % (name, built, ", ".join(parts))

    def text(self):
        lines = ["MaxDrop import report: %s" % (self.source or "the scene")]
        if self.pack is not None:
            lines += _pack_lines(self.pack, self.pack_name)
        if self.unit is not None:
            lines.append("Units: %s (%g m per unit)" % (self.unit, self.meters))
        else:
            lines.append("Units: not stated in the file, %g m per unit" % self.meters)
        lines.append("Nodes read: %d" % self.nodes)
        lines.append("Objects built: %d, meshes: %d" % (self.objects_built, self.meshes_built))
        lines.append("Layers: %d (%d hidden)" % (self.layers, self.hidden_layers))
        lines.append("Objects hidden: %d, not renderable: %d, frozen: %d" % (self.hidden, self.unrenderable,
                                                                             self.frozen))
        lines.append("Groups: %d" % self.groups)
        if self.modifiers_applied:
            lines.append("Modifiers applied (baked into the mesh), nodes by class: " + _counts(self.modifiers_applied))
        if self.modifiers_converted:
            lines.append("Modifiers converted to a Blender modifier, nodes by class: "
                         + _counts(self.modifiers_converted))
        if self.materials_built is not None:
            lines.append("Materials built: %d" % self.materials_built
                         + (" (converted by class: %s)" % _counts(self.materials) if self.materials else ""))
        if self.swatches:
            lines.append(self.swatches)
        if self.textures_found:
            lines.append("Textures found: %d (%s)" % (sum(n for _r, n in self.textures_found), ", ".join(
                "%s %d" % rn for rn in self.textures_found)))
        lines += self.texture_search_stopped
        if self.approximated:
            lines.append("Approximated:")
            if self.wrappers:
                lines.append("  Wrappers peeled to their sub-material, by class: " + _counts(self.wrappers))
            if self.maps_peeled:
                lines.append("  Maps peeled to the map below them, by class: " + _counts(self.maps_peeled))
        if not self.left_out:
            if not self.approximated:
                lines.append("Nothing was left out.")
            return "\n".join(lines)
        lines.append("Not converted:")
        if self.placeholders:
            lines.append("  Placeholders (empties) by class: " + _counts(self.placeholders))
        if self.modifiers:
            lines.append("  Modifiers not applied (ignored: the object arrives as its base object), nodes by class: "
                         + _counts(self.modifiers))
        if self.unknown_controllers:
            lines.append("  Unknown controllers by class (identity used): " + _counts(self.unknown_controllers))
        if self.dropped_uv_layers:
            lines.append("  UV channels past Blender's limit: %d" % self.dropped_uv_layers)
        if self.grey_materials:
            lines.append("  Material classes without a rule (grey material), by class: " + _counts(self.grey_materials))
        if self.maps_unsupported:
            lines.append("  Map classes without a map below (not used), by class: " + _counts(self.maps_unsupported))
        if self.sockets_skipped:
            lines.append("  Principled inputs not on Blender %s (not set), materials: %s" % (
                self.blender or "this version", _counts(self.sockets_skipped)))
        if self.textures_missing:
            where = _in_pack(self.pack)
            lines.append("  Textures not found: %d" % len(self.textures_missing))
            lines += _listed([name + where(name) for name in self.textures_missing])
        materials = [("object %d" % index, reason) for index, reason in self.material_issues]
        for title, items in (("Geometry errors", self.geometry_errors), ("Material issues", materials),
                             ("Other issues", self.issues)):
            if items:
                lines.append("  %s: %d" % (title, len(items)))
                lines += _listed(["%s: %s" % item for item in items])
        return "\n".join(lines)


def _listed(items):
    """The lines of a list in the report, indented, cut after MAX_LISTED."""
    lines = ["    " + item for item in items[:MAX_LISTED]]
    if len(items) > MAX_LISTED:
        lines.append("    ... and %d more" % (len(items) - MAX_LISTED))
    return lines


def _in_pack(pack):
    """name -> what the archive held of a texture file of that name; "" for every name when the scene was not
    unpacked just now (only an unpack lists the archive)."""
    if pack is None or getattr(pack, "mode", "") != "unpacked":
        return lambda name: ""
    held = {}  # name key -> note; the first kind that names the file wins
    for path, reason in getattr(pack, "refused", None) or ():
        held.setdefault(_key(path), ": in the archive, refused: %s" % reason)
    for path in getattr(pack, "not_regular", None) or ():
        held.setdefault(_key(path), ": in the archive, not a regular file")
    # a collided name had another copy written beside the scene: only a lookup fault leaves it missing
    for path in getattr(pack, "collided", None) or ():
        held.setdefault(_key(path), ": in the archive more than once, a copy written (not written: %s)" % path)
    skipped = {k.casefold() for k in (getattr(pack, "skipped", None) or {})}

    def where(name):
        note = held.get(_key(name))
        if note:
            return note
        ext = os.path.splitext(name)[1].casefold() or "(no extension)"
        if ext in skipped:
            return ": the archive's %s files were skipped" % ext
        return ": not in the archive"
    return where


def _key(path):
    return textures.name_key(textures.base_name(path))


def _plural(n, word, plural=None):
    return "%d %s" % (n, word if n == 1 else (plural or word + "s"))


def _counts(counter):
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = ", ".join("%s %d" % (k or "(unnamed class)", v) for k, v in items[:MAX_LISTED])
    if len(items) > MAX_LISTED:
        shown += ", ... and %d more classes" % (len(items) - MAX_LISTED)
    return shown


def _names(items):
    shown = ", ".join(str(x) for x in items[:MAX_LISTED])
    if len(items) > MAX_LISTED:
        shown += ", ... and %d more" % (len(items) - MAX_LISTED)
    return shown


def _pack_lines(pack, pack_name):
    lines = ["Scene pack: %s" % (pack_name or os.path.basename(getattr(pack, "folder", "") or "") or "(archive)")]
    lines.append("  Pack folder: %s" % getattr(pack, "folder", ""))
    lines.append("  Unpacker: %s" % getattr(pack, "backend", ""))
    mode = getattr(pack, "mode", "")
    if mode == "in_place":
        lines.append("  Files: a copy already in that folder, used in place")
    else:
        lines.append("  Files written: %d, reused from an earlier unpack: %d" % (getattr(pack, "written", 0),
                                                                                getattr(pack, "reused", 0)))
    skipped = getattr(pack, "skipped", None) or {}
    if skipped:
        lines.append("  Skipped by extension: " + _counts(collections.Counter(skipped)))
    collided = list(getattr(pack, "collided", None) or ())
    if collided:
        lines.append("  Names that collided (the copy nearer the scene was kept): %d: %s" % (len(collided),
                                                                                            _names(collided)))
    refused = list(getattr(pack, "refused", None) or ())
    if refused:
        lines.append("  Refused: %d: %s" % (len(refused), _names(["%s (%s)" % r for r in refused])))
    not_regular = list(getattr(pack, "not_regular", None) or ())
    if not_regular:
        lines.append("  Not regular files: %d: %s" % (len(not_regular), _names(not_regular)))
    if getattr(pack, "unwanted", 0):
        lines.append("  Files the scene does not use, left out: %d" % pack.unwanted)
    guessed = list(getattr(pack, "guessed", None) or ())
    if guessed:
        lines.append("  Names stored without a known encoding, read as a guess: %d" % len(guessed))
    return lines


def gather(desc, source="", objects_built=None, meshes_built=None, dropped_uv_layers=0, pack=None, pack_name=""):
    """The Report of one import from its SceneDescription and what build/ made of it."""
    rep = Report(source)
    rep.unit = desc.unit.name if desc.unit is not None else None
    rep.meters = desc.meters
    rep.nodes = len(desc.nodes)
    rep.objects_built = len(desc.nodes) if objects_built is None else objects_built
    rep.meshes_built = len(desc.meshes) if meshes_built is None else meshes_built
    rep.dropped_uv_layers = dropped_uv_layers
    rep.layers = len(desc.layers)
    rep.hidden_layers = sum(1 for la in desc.layers if la.hidden)
    for node in desc.nodes:
        rep.hidden += node.hidden
        rep.unrenderable += not node.renderable
        rep.frozen += node.frozen
        rep.groups += node.group_head
        rep.add_modifiers(IGNORED, node.modifiers)
    rep.placeholders.update(desc.placeholders)
    rep.unknown_controllers.update(desc.unknown_controllers)
    labels = {node.index: node.name or "object %d" % node.index for node in desc.nodes}
    for index, reason in desc.issues:
        label = labels.get(index, "object %d" % index)
        if reason == UNKNOWN_CONTROLLER and desc.unknown_controllers:  # counted by class already
            rep.unknown_controller_nodes += 1
        elif reason.startswith(GEOMETRY):
            rep.geometry_errors.append((label, reason[len(GEOMETRY):]))
        else:
            rep.issues.append((label, reason))
    rep.pack, rep.pack_name = pack, pack_name
    return rep


def add_materials(rep, materials_built, classes=(), conv_stats=None, tex_stats=None, lookup=None, sockets=(),
                  blender="", swatches=None):
    """Add what the material import did to rep: materials_built (Blender materials made), classes {class name:
    materials converted by a rule} and sockets {Principled input name: materials that needed it} from
    build.materials; conv_stats (peeled, unknown, issues), tex_stats (peeled, unsupported, issues) and lookup (a
    TextureReport: found, missing, truncated) from the converters; blender: the version the sockets are missing
    from; swatches: the converters' convert.colors.Swatches (its line; its note, set when the scene's gamma was not
    found, an issue).
    """
    rep.materials_built, rep.blender = materials_built, blender
    if swatches is not None:
        rep.swatches = swatches.line()
        if swatches.note:
            rep.issues.append(("color swatches", swatches.note))
    rep.materials.update(classes)
    rep.sockets_skipped.update(sockets)
    if conv_stats is not None:
        rep.wrappers.update(conv_stats.peeled)
        rep.grey_materials.update(conv_stats.unknown)
        rep.material_issues.extend(conv_stats.issues)
    if tex_stats is not None:
        rep.maps_peeled.update(tex_stats.peeled)
        rep.maps_unsupported.update(tex_stats.unsupported)
        rep.material_issues.extend(tex_stats.issues)
    if lookup is not None:
        rep.textures_found = [(textures.RULE_NAMES[r], lookup.found.get(r, 0)) for r in textures.RULES]
        rep.textures_missing = list(lookup.missing)
        rep.texture_search_stopped = [
            "Texture search of %s stopped after %d files and folders, in %s" % (textures.RULE_NAMES[r], n, folder)
            for r, folder, n in lookup.truncated]
    return rep
