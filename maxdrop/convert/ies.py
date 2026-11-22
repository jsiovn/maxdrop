# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The photometry of an IES file (IESNA LM-63): its rated lumens and the flux its candela table gives.

    p = read(path)                      # Photometry, IesError (a ValueError) and the reason when it is not read
    p = parse(data)                     # the same from the file's bytes
    p.scale                             # what V-Ray's power is multiplied by to give the flux it renders
    lookup = Lookup(index)              # index: a convert.textures.TextureIndex; one per scene description
    p, why = lookup.photometry(path, resolved)   # (Photometry, None), (None, why it is not read), (None, None)

A VRayIES with its intensity override off scales the file's candelas by its power over the file's rated lumens
(measured, docs/FORMAT.md "VRayIES power, measured"), so it renders power x flux / rated lumens; rated lumens of -1
(absolute photometry) make the power the flux. The layout, after any number of keyword lines: TILT=NONE, TILT=<file>
(nothing inline) or TILT=INCLUDE (lamp-to-luminaire geometry, the number of pairs n, n angles, n factors); then the
number of lamps, lumens per lamp, candela multiplier, the numbers of vertical and horizontal angles, photometric type,
units type, width, length, height; ballast factor, ballast-lamp photometric factor, input watts; the vertical angles,
the horizontal angles, and the candelas, one run of vertical values per horizontal angle. Numbers are separated by
white space or commas; a line ends at CR LF, LF or a lone CR.

The flux is integrated for photometric type C (vertical angles from the nadir, 0 to 180 degrees; horizontal ones
about the vertical axis): per horizontal plane the sum over the zones between two vertical angles of their mean
intensity times (cos a - cos b), then the trapezoid over the planes in radians, times 360 / their span (one plane:
2 pi; the span 90, 180 or 360 degrees of LM-63's symmetries from 0 or 90, 90 to 270 included; a file from 0 to past
180 but short of 360 is closed with its first plane at 360). An isotropic file of I cd gives
4 pi I exactly. Candelas are multiplied by the candela multiplier; the ballast factors are left out (as Blender's
own IES reader does); the rated lumens are per lamp, the number of lamps not applied (V-Ray's use of either is not
measured). Type A and B files are not read.

The file comes from anywhere: at most MAX_BYTES are read (a larger file is refused), MAX_ANGLES per axis and
MAX_VALUES candelas, counts checked against the numbers there are before any list is made; every number finite, the
angles in order and in range, the candelas and the multiplier not negative. No bpy, no add-on import.
"""
import collections
import math
import re

MAX_BYTES = 4 << 20
MAX_ANGLES = 4096
MAX_VALUES = 1 << 20
TYPE_C = 1
_NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\Z")
_SEPARATORS = re.compile(rb"[\s,]+")
_LINES = re.compile(rb"[^\r\n]*")  # CR LF, LF or a lone CR (old Mac files) ends a line
_SPANS = (0.0, 90.0, 180.0, 360.0)


class IesError(ValueError):
    pass


class Photometry(collections.namedtuple("Photometry", "lamps rated multiplier flux")):
    """lamps: the number of lamps; rated: lumens per lamp (-1: absolute photometry); multiplier: the candela
    multiplier; flux: lumens of the candela table times the multiplier."""
    __slots__ = ()

    @property
    def scale(self):
        """V-Ray's power times this is the flux it renders: flux / rated lumens, 1 when they are not positive."""
        return self.flux / self.rated if self.rated > 0 else 1.0


def read(path):
    """The Photometry of the IES file at path; IesError with the reason when it cannot be read."""
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_BYTES + 1)
    except OSError as e:
        raise IesError("cannot be opened: %s" % (e.strerror or e)) from e
    if len(data) > MAX_BYTES:
        raise IesError("larger than %d MiB" % (MAX_BYTES >> 20))
    return parse(data)


class _Numbers:
    def __init__(self, tokens):
        self.tokens, self.at = tokens, 0

    def left(self):
        return len(self.tokens) - self.at

    def number(self, what):
        if self.at >= len(self.tokens):
            raise IesError("the file ends before its %s" % what)
        token = self.tokens[self.at]
        self.at += 1
        if not _NUMBER.match(token):  # the token itself stays out of the report: the file may be any local file
            raise IesError("its %s: not a number" % what)
        v = float(token)
        if not math.isfinite(v):
            raise IesError("its %s: a number out of range" % what)
        return v

    def count(self, what, low, high):
        v = self.number(what)
        if v != int(v) or not low <= v <= high:
            raise IesError("its %s %g is not a whole number from %d to %d" % (what, v, low, high))
        return int(v)

    def numbers(self, n, what):
        if n > self.left():
            raise IesError("the file ends inside its %s" % what)
        return [self.number(what) for _ in range(n)]


def _tokens_after_tilt(data):
    """(the TILT value, the tokens after its line)."""
    for m in _LINES.finditer(data):
        line = m.group().strip()
        if line[:5].upper() == b"TILT=":
            return line[5:].strip().upper(), [t for t in _SEPARATORS.split(data[m.end():]) if t]
    raise IesError("no TILT line")


def parse(data):
    """The Photometry of an IES file's bytes; IesError with the reason when they cannot be read."""
    tilt, tokens = _tokens_after_tilt(bytes(data))
    n = _Numbers(tokens)
    if tilt == b"INCLUDE":
        n.number("lamp-to-luminaire geometry")
        pairs = n.count("number of tilt angles", 0, MAX_ANGLES)
        n.numbers(2 * pairs, "tilt angles and factors")
    lamps = n.count("number of lamps", 1, MAX_VALUES)
    rated = n.number("lumens per lamp")
    multiplier = n.number("candela multiplier")
    if multiplier < 0:
        raise IesError("its candela multiplier %g is negative" % multiplier)
    nv = n.count("number of vertical angles", 2, MAX_ANGLES)
    nh = n.count("number of horizontal angles", 1, MAX_ANGLES)
    kind = n.count("photometric type", 1, 3)
    if kind != TYPE_C:
        raise IesError("photometric type %s is not read" % "?CBA"[kind])
    n.numbers(7, "header")  # units type, width, length, height, ballast factor, ballast-lamp factor, input watts
    if nv * nh > MAX_VALUES:
        raise IesError("%d x %d candelas are more than %d" % (nv, nh, MAX_VALUES))
    if nv + nh + nv * nh > n.left():
        raise IesError("the file ends inside its angles or candelas")
    vertical = n.numbers(nv, "vertical angles")
    horizontal = n.numbers(nh, "horizontal angles")
    if any(b < a for a, b in zip(vertical, vertical[1:])) or vertical[0] < 0 or vertical[-1] > 180:
        raise IesError("its vertical angles are not in order from 0 to 180 degrees")
    if any(b < a for a, b in zip(horizontal, horizontal[1:])) or horizontal[0] < 0 or horizontal[-1] > 360:
        raise IesError("its horizontal angles are not in order from 0 to 360 degrees")
    candelas = n.numbers(nv * nh, "candelas")
    if any(c < 0 for c in candelas):
        raise IesError("a candela value is negative")
    if horizontal[0] == 0 and 180 < horizontal[-1] < 360:  # no symmetry, the last plane short of 360: close it
        horizontal.append(360.0)
        candelas += candelas[:nv]
    span = horizontal[-1] - horizontal[0]
    if horizontal[0] not in (0, 90) or span not in _SPANS or (len(horizontal) > 1) != (span > 0):
        raise IesError("its horizontal angles run from %g to %g degrees: not one of LM-63's symmetries"
                       % (horizontal[0], horizontal[-1]))
    flux = _flux(vertical, horizontal, candelas) * multiplier
    if not math.isfinite(flux):
        raise IesError("its flux is out of range")
    return Photometry(lamps, rated, multiplier, flux)


def _flux(vertical, horizontal, candelas):
    """Lumens of a type C candela table (candelas: one run of len(vertical) per horizontal angle)."""
    nv = len(vertical)
    zones = [math.cos(math.radians(a)) - math.cos(math.radians(b)) for a, b in zip(vertical, vertical[1:])]
    planes = []
    for j in range(len(horizontal)):
        row = candelas[j * nv:(j + 1) * nv]
        planes.append(sum((row[i] + row[i + 1]) * 0.5 * z for i, z in enumerate(zones)))
    if len(planes) == 1:
        return 2.0 * math.pi * planes[0]
    total = sum((p + q) * 0.5 * math.radians(b - a)
                for p, q, a, b in zip(planes, planes[1:], horizontal, horizontal[1:]))
    return total * 360.0 / (horizontal[-1] - horizontal[0])


class Lookup:
    """The IES files of one scene description: found by index (a convert.textures.TextureIndex: its rules, never a
    UNC path or a link), each file read once."""

    def __init__(self, index):
        self.index = index
        self._read = {}

    def photometry(self, path, resolved=""):
        """(Photometry, None) of the file a stored path names; (None, why) when it is found but not read; (None,
        None) when it is not found."""
        found = self.index.find(path, resolved)
        if found is None:
            return None, None
        if found.path not in self._read:
            try:
                self._read[found.path] = read(found.path), None
            except IesError as e:
                self._read[found.path] = None, str(e)
        return self._read[found.path]
