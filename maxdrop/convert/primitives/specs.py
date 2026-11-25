# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The primitives' parameter blocks: the classes, their parameters and read_params()."""
import collections
import math

from ...reader import chunks, classids, pblock, realworld


ChunkError = chunks.ChunkError

SLOT_BLOCK = 0
# Face corners one primitive may make (a file can ask for any number of segments): 524,288 quads, measured at the
# cap in 0.1 to 0.4 s (Box, Plane and GeoSphere the slowest; a GeoSphere's hemisphere slerps its lower half too, about
# twice a full GeoSphere's lattice) and a few hundred MB at most, of the order of the budget of convert/extrude/.
MAX_CORNERS = 1 << 21
_TAU = 2.0 * math.pi
_SEAM = 1e-6


class PrimitiveError(ChunkError):
    """A primitive that is not built; its node stays a placeholder."""


# class -> (name, {parameter: (id, kind, default, minimum)}); kind "f" a length or angle, "i" a count, "b" a switch
_SPECS = {
    classids.BOX: ("Box", {"length": (0, "f", 0.0, None), "width": (1, "f", 0.0, None),
                           "height": (2, "f", 0.0, None), "width_segs": (3, "i", 1, 1),
                           "length_segs": (4, "i", 1, 1), "height_segs": (5, "i", 1, 1),
                           "mapping": (6, "b", True, None)}),
    classids.PLANE: ("Plane", {"length": (0, "f", 0.0, None), "width": (1, "f", 0.0, None),
                               "width_segs": (2, "i", 4, 1), "length_segs": (3, "i", 4, 1),
                               "density": (4, "f", 1.0, None), "render_scale": (5, "f", 1.0, None),
                               "mapping": (6, "b", True, None)}),
    classids.PYRAMID: ("Pyramid", {"width": (0, "f", 0.0, None), "depth": (1, "f", 0.0, None),
                                   "height": (2, "f", 0.0, None), "width_segs": (3, "i", 1, 1),
                                   "depth_segs": (4, "i", 1, 1), "height_segs": (5, "i", 1, 1),
                                   "mapping": (6, "b", True, None)}),
    classids.SPHERE: ("Sphere", {"radius": (0, "f", 0.0, None), "segs": (1, "i", 32, 4),
                                 "smooth": (2, "b", True, None), "hemisphere": (3, "f", 0.0, None),
                                 "squash": (4, "b", False, None), "base_to_pivot": (5, "b", False, None),
                                 "mapping": (6, "b", True, None), "slice": (7, "b", False, None),
                                 "slice_from": (8, "f", 0.0, None), "slice_to": (9, "f", 0.0, None)}),
    classids.GEOSPHERE: ("GeoSphere", {"radius": (0, "f", 0.0, None), "segs": (1, "i", 4, 1),
                                       "base_type": (2, "i", 2, None), "hemisphere": (3, "b", False, None),
                                       "smooth": (4, "b", True, None), "base_to_pivot": (5, "b", False, None),
                                       "mapping": (6, "b", True, None)}),
    classids.CYLINDER: ("Cylinder", {"radius": (0, "f", 0.0, None), "height": (1, "f", 0.0, None),
                                     "height_segs": (2, "i", 5, 1), "cap_segs": (3, "i", 1, 1),
                                     "sides": (4, "i", 18, 3), "smooth": (5, "b", True, None),
                                     "slice": (6, "b", False, None), "slice_from": (7, "f", 0.0, None),
                                     "slice_to": (8, "f", 0.0, None), "mapping": (9, "b", True, None)}),
    classids.CONE: ("Cone", {"radius1": (0, "f", 0.0, None), "radius2": (1, "f", 0.0, None),
                             "height": (2, "f", 0.0, None), "height_segs": (3, "i", 5, 1),
                             "cap_segs": (4, "i", 1, 1), "sides": (5, "i", 24, 3), "smooth": (6, "b", True, None),
                             "slice": (7, "b", False, None), "slice_from": (8, "f", 0.0, None),
                             "slice_to": (9, "f", 0.0, None), "mapping": (10, "b", True, None)}),
    classids.TUBE: ("Tube", {"radius1": (0, "f", 0.0, None), "radius2": (1, "f", 0.0, None),
                             "height": (2, "f", 0.0, None), "sides": (3, "i", 18, 3), "cap_segs": (4, "i", 1, 1),
                             "height_segs": (5, "i", 5, 1), "smooth": (6, "b", True, None),
                             "slice": (7, "b", False, None), "slice_from": (8, "f", 0.0, None),
                             "slice_to": (9, "f", 0.0, None), "mapping": (10, "b", True, None)}),
    classids.TORUS: ("Torus", {"radius1": (0, "f", 0.0, None), "radius2": (1, "f", 0.0, None),
                               "rotation": (2, "f", 0.0, None), "twist": (3, "f", 0.0, None),
                               "segs": (4, "i", 24, 3), "sides": (5, "i", 12, 3), "smooth": (6, "i", 2, None),
                               # Torus alone keeps the slice's end before its start
                               "slice": (7, "b", False, None), "slice_to": (8, "f", 0.0, None),
                               "slice_from": (9, "f", 0.0, None), "mapping": (10, "b", True, None)}),
}


class Params(collections.namedtuple("Params", "class_id name values real_world")):
    """A primitive's parameters: class_id, name (its class), values {parameter: value}, real_world whether Real-World
    Map Size is on."""
    __slots__ = ()

    def __getattr__(self, key):
        try:
            return self.values[key]
        except KeyError:
            raise AttributeError(key) from None


def is_primitive(scene, i):
    entry = scene.entry(i)
    return entry is not None and entry.superclass == classids.SC_GEOMOBJECT and entry.class_id in _SPECS


def _value(block, pid, kind, default):
    v = block.get(pid)
    if v is None:
        return default
    if isinstance(v, pblock.Animated):
        raise PrimitiveError("parameter %d is animated (a controller)" % pid)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise PrimitiveError("parameter %d is not a number: %r" % (pid, v))
    if kind == "b":
        return bool(v)
    if kind == "i":
        return int(v)
    return float(v)


def params_of(class_id, block, real_world=False):
    """(Params of a primitive of class_id from its ParamBlock2 block, issues): parameters by id, the defaults for
    those not stored; segments below 3ds Max's minimum raised to it (an issue)."""
    name, spec = _SPECS[class_id]
    issues = list(getattr(block, "issues", ()))
    values = {}
    for key, (pid, kind, default, minimum) in spec.items():
        v = _value(block, pid, kind, default)
        if minimum is not None and v < minimum:
            issues.append("%s %d, made %d" % (key.replace("_", " "), v, minimum))
            v = minimum
        values[key] = v
    return Params(class_id, name, values, real_world), issues


def read_params(scene, i):
    """(Params of primitive object i, issues): its block in reference slot 0 (params_of) and its Real-World Map Size
    flag."""
    entry = scene.entry(i)
    if not is_primitive(scene, i):
        raise PrimitiveError("object %d is not a primitive" % i)
    refs = scene.refs(i)
    target = refs.get(SLOT_BLOCK)
    te = scene.entry(target) if target is not None and 0 <= target < len(scene) else None
    if te is None or te.superclass != classids.SC_PARAMETER_BLOCK2:
        raise PrimitiveError("no parameter block (reference slot 0)")
    block = pblock.ParamBlock2.from_chunk(scene.chunk(target), scene.refs(target), refs, len(scene),
                                          (entry.superclass, entry.class_id))
    return params_of(entry.class_id, block, realworld.flag(scene.chunk(i), entry.class_id))
