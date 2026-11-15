# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The import report: what an import read and built, and what it did not convert, as text for the user.

    rep = gather(desc, source="scene.max", objects_built=n, meshes_built=m, dropped_uv_layers=k, pack=result)
    rep.text()                          # the whole report, lines joined with "\n"
    rep.summary()                       # (level, line): "INFO" when nothing was left out, else "WARNING"

desc is a convert.scene.SceneDescription. The counts of what build/ made default to the description's own. pack is
the result of maxdrop.intake.archive.unpack() when the import started from a scene pack (read by attribute, so
this module never imports the intake package), and pack_name the archive's file name: its block comes first.

The report names nodes and files of the user's scene: it is shown to the user and never written into the
repository. Lists are cut after MAX_LISTED entries. No bpy.
"""
import collections
import os

MAX_LISTED = 50
LEVEL_INFO, LEVEL_WARNING = "INFO", "WARNING"
GEOMETRY = "geometry: "


class Report:
    """Counters and lists of one import. issues and geometry_errors are [(node label, reason)]."""
    __slots__ = ("source", "unit", "meters", "nodes", "objects_built", "meshes_built", "layers", "hidden_layers",
                 "hidden", "unrenderable", "frozen", "groups", "placeholders", "unknown_controllers", "modifiers",
                 "dropped_uv_layers", "geometry_errors", "issues", "pack", "pack_name")

    def __init__(self, source=""):
        self.source, self.unit, self.meters = source, None, 1.0
        self.nodes = self.objects_built = self.meshes_built = self.layers = self.hidden_layers = 0
        self.hidden = self.unrenderable = self.frozen = self.groups = self.dropped_uv_layers = 0
        self.placeholders = collections.Counter()
        self.unknown_controllers = collections.Counter()
        self.modifiers = collections.Counter()  # class name -> nodes whose stack holds it, not applied
        self.geometry_errors, self.issues = [], []
        self.pack, self.pack_name = None, ""

    @property
    def left_out(self):
        """How many things were not converted: placeholders, nodes with modifiers not applied, UV channels without
        room, geometry errors and other issues."""
        return (sum(self.placeholders.values()) + sum(self.modifiers.values()) + self.dropped_uv_layers
                + len(self.geometry_errors) + len(self.issues))

    def summary(self):
        """(level, one line) for the operator's report."""
        name = self.source or "the scene"
        built = "%s, %s" % (_plural(self.objects_built, "object"), _plural(self.meshes_built, "mesh", "meshes"))
        if not self.left_out:
            return LEVEL_INFO, "Imported %s: %s, nothing left out." % (name, built)
        parts = []
        if self.placeholders:
            parts.append(_plural(sum(self.placeholders.values()), "placeholder"))
        if self.modifiers:
            parts.append(_plural(sum(self.modifiers.values()), "modifier") + " not applied")
        problems = len(self.geometry_errors) + len(self.issues) + self.dropped_uv_layers
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
        if not self.left_out:
            lines.append("Nothing was left out.")
            return "\n".join(lines)
        lines.append("Not converted:")
        if self.placeholders:
            lines.append("  Placeholders (empties) by class: " + _counts(self.placeholders))
        if self.modifiers:
            lines.append("  Modifiers not applied (the base mesh is built), nodes by class: " + _counts(self.modifiers))
        if self.unknown_controllers:
            lines.append("  Unknown controllers by class (identity used): " + _counts(self.unknown_controllers))
        if self.dropped_uv_layers:
            lines.append("  UV channels past Blender's limit: %d" % self.dropped_uv_layers)
        for title, items in (("Geometry errors", self.geometry_errors), ("Other issues", self.issues)):
            if items:
                lines.append("  %s: %d" % (title, len(items)))
                lines += ["    %s: %s" % item for item in items[:MAX_LISTED]]
                if len(items) > MAX_LISTED:
                    lines.append("    ... and %d more" % (len(items) - MAX_LISTED))
        return "\n".join(lines)


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
        rep.modifiers.update(set(node.modifiers))
    rep.placeholders.update(desc.placeholders)
    rep.unknown_controllers.update(desc.unknown_controllers)
    labels = {node.index: node.name or "object %d" % node.index for node in desc.nodes}
    for index, reason in desc.issues:
        label = labels.get(index, "object %d" % index)
        if reason.startswith(GEOMETRY):
            rep.geometry_errors.append((label, reason[len(GEOMETRY):]))
        else:
            rep.issues.append((label, reason))
    rep.pack, rep.pack_name = pack, pack_name
    return rep
