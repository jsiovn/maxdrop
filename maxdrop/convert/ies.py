# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The photometry of an IES file (IESNA LM-63): its rated lumens, the flux its candela table gives and its profile.

    p = read(path)                      # Photometry, IesError (a ValueError) and the reason when it is not read
    p = parse(data)                     # the same from the file's bytes
    p.scale                             # what V-Ray's power is multiplied by to give the flux it renders
    p.text, p.peak, p.nadir, p.up       # the profile: the text parsed, peak and nadir candela, the upward share
    lookup = Lookup(index)              # index: a convert.textures.TextureIndex; one per scene description
    p, why = lookup.photometry(path, resolved)   # (Photometry, None), (None, why it is not read), (None, None)
                                        # why also when it is not found and the texture search stopped short
    name, p, why = lookup.found(path, resolved)  # the same and the base name of the file found (None: not found)

A VRayIES with its intensity override off scales the file's candelas by its power over the file's rated lumens
(measured, docs/FORMAT.md "VRayIES power, measured"), so it renders power x flux / rated lumens; rated lumens of 0 or
below (-1: absolute photometry) make the power the flux. The layout, after any number of keyword lines: TILT=NONE,
TILT=<file> (nothing inline) or TILT=INCLUDE (lamp-to-luminaire geometry, the number of pairs n, n angles, n
factors); then the number of lamps, lumens per lamp, candela multiplier, the numbers of vertical and horizontal
angles, photometric type, units type, width, length, height; ballast factor, ballast-lamp photometric factor, input
watts; the vertical angles, the horizontal angles, and the candelas, one run of vertical values per horizontal angle.
Numbers are separated by white space or commas; a line ends at CR LF, LF or a lone CR.

What V-Ray 5.2 does, measured with self-authored files: the rated lumens are the number of lamps times the lumens per
lamp; the flux is the candela table's times the candela multiplier and the ballast factor (the ballast-lamp factor is
left out); the candelas are interpolated linearly in angle. Type C (vertical angles from the nadir, 0 to 180 degrees;
horizontal ones about the vertical axis): per horizontal plane the integral of I(t) sin t over the vertical angles,
then the trapezoid over the planes in radians, times 360 / their span (one plane: 2 pi; the span 90, 180 or 360
degrees of LM-63's symmetries from 0 or 90, 90 to 270 included; a file from 0 to past 180 but short of 360 is closed
with its first plane at 360). Types A and B (vertical angles a latitude from -90 or 0 to 90; horizontal ones from
-90 to 90, from -180 to 180 of which only -90 to 90 counts, or for type B from 0 to 90 mirrored): I(t) cos t
instead, the same trapezoid. Vertical angles from 0 are not mirrored: each run goes on below 0 along its first
segment, down to 0 cd at most; V-Ray renders that with 2 or 3 vertical angles or runs that do not vary, and the
lower half black otherwise (not read); a run that varies is read only with a first segment of 30 degrees or more
(the shortest measured). Type A with horizontal angles from 0 to 90 renders nothing: flux 0. An
isotropic file of I cd gives 4 pi I exactly (type C), 2 pi I (types A and B). Other ranges of type A and B (V-Ray
renders them by no rule found) are not read.

The profile, for a light that shines with the file's distribution (Blender's IES Texture node reads the text): the
text up to the last candela, the largest candela of the table and the one at the nadir (both times the multiplier
only: Blender's node applies the ballast factors itself, measured, docs/FORMAT.md "The IES Texture node in Blender,
measured"), the share of the flux above the horizontal, the ballast-lamp factor and the horizontal angles. Type C's
nadir is vertical 0 (the mean of its planes there; 0 when the table starts past 0, as Blender's node gives it). Types
A and B, not measured in Blender: the nadir is vertical 0 at horizontal 0, the axis V-Ray aims down; no flux goes
above the horizontal (V-Ray renders horizontal angles from -90 to 90 only); the peak is the whole table's, which
V-Ray's render can pass (a run going on below 0) or leave out (planes past +-90, type A from 0 to 90).

The file comes from anywhere: at most MAX_BYTES are read (a larger file is refused), MAX_ANGLES per axis and
MAX_VALUES candelas, counts checked against the numbers there are before any list is made; the numbers are read
one at a time, none split off before its turn (numbers past the table are never read); every number finite, the
angles in order and in range, the candelas, the multiplier and the ballast factor not negative. No bpy, no add-on
import.
"""
import bisect
import collections
import itertools
import math
import os
import re

MAX_BYTES = 4 << 20
MAX_ANGLES = 4096
MAX_VALUES = 1 << 20
TYPE_C, TYPE_B = 1, 2
_NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\Z")
_TOKEN = re.compile(rb"[^\s,]+")
_LINES = re.compile(rb"[^\r\n]*")  # CR LF, LF or a lone CR (old Mac files) ends a line
_SPANS = (0.0, 90.0, 180.0, 360.0)


class IesError(ValueError):
    pass


class Photometry(collections.namedtuple("Photometry",
                                         "lamps rated multiplier flux ballast_lamp horizontal peak nadir up text")):
    """lamps: the number of lamps; rated: lumens per lamp (-1: absolute photometry); multiplier: the candela
    multiplier; flux: lumens of the candela table times the multiplier and the ballast factor; ballast_lamp: the
    ballast-lamp photometric factor; horizontal: the horizontal angles (a tuple); peak, nadir: the largest candela
    and the one at the nadir, times the multiplier; up: the share of the flux above the horizontal, 0 to 1; text: the
    file up to its last candela (Latin-1: a character per byte)."""
    __slots__ = ()

    @property
    def scale(self):
        """V-Ray's power times this is the flux it renders: flux / (lamps x rated lumens); when they are not
        positive 1, or 0 for a flux of 0 (V-Ray renders such a table black; measured, docs/FORMAT.md "VRayIES
        header, measured" and "VRayIES type A and B ranges, measured")."""
        if self.rated > 0:
            return self.flux / (self.lamps * self.rated)
        return 1.0 if self.flux > 0 else 0.0


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
    """The numbers of data from the offset at, one token at a time: no token is split off before it is read."""

    def __init__(self, data, at):
        self.data, self.at = data, at

    def has(self, n):
        """At least n numbers are left: counted up to n, none kept."""
        return n <= 0 or next(itertools.islice(_TOKEN.finditer(self.data, self.at), n - 1, None), None) is not None

    def number(self, what):
        m = _TOKEN.search(self.data, self.at)
        if m is None:
            raise IesError("the file ends before its %s" % what)
        self.at = m.end()
        return _value(m.group(), what)

    def count(self, what, low, high):
        v = self.number(what)
        if v != int(v) or not low <= v <= high:
            raise IesError("its %s %g is not a whole number from %d to %d" % (what, v, low, high))
        return int(v)

    def numbers(self, n, what, counted=False):
        """The next n numbers; counted: has(n) is known to hold (checked for several lists at once)."""
        if not counted and not self.has(n):
            raise IesError("the file ends inside its %s" % what)
        values = []
        for m in itertools.islice(_TOKEN.finditer(self.data, self.at), n):
            values.append(_value(m.group(), what))
            self.at = m.end()
        return values


def _value(token, what):
    if not _NUMBER.match(token):  # the token itself stays out of the report: the file may be any local file
        raise IesError("its %s: not a number" % what)
    v = float(token)
    if not math.isfinite(v):
        raise IesError("its %s: a number out of range" % what)
    return v


def _after_tilt(data):
    """(the TILT value, the offset of the numbers after its line)."""
    for m in _LINES.finditer(data):
        line = m.group().strip()
        if line[:5].upper() == b"TILT=":
            return line[5:].strip().upper(), m.end()
    raise IesError("no TILT line")


def parse(data):
    """The Photometry of an IES file's bytes; IesError with the reason when they cannot be read."""
    data = bytes(data)
    tilt, at = _after_tilt(data)
    n = _Numbers(data, at)
    if tilt == b"INCLUDE":
        n.number("lamp-to-luminaire geometry")
        pairs = n.count("number of tilt angles", 0, MAX_ANGLES)
        n.numbers(2 * pairs, "tilt angles and factors")
    lamps = n.count("number of lamps", 1, MAX_VALUES)
    rated = n.number("lumens per lamp")
    if not math.isfinite(lamps * rated):
        raise IesError("its rated lumens are out of range")
    multiplier = n.number("candela multiplier")
    if multiplier < 0:
        raise IesError("its candela multiplier %g is negative" % multiplier)
    nv = n.count("number of vertical angles", 2, MAX_ANGLES)
    nh = n.count("number of horizontal angles", 1, MAX_ANGLES)
    kind = n.count("photometric type", 1, 3)
    n.numbers(4, "header")  # units type, width, length, height
    ballast = n.number("ballast factor")
    if ballast < 0:
        raise IesError("its ballast factor %g is negative" % ballast)
    ballast_lamp = n.numbers(2, "header")[0]  # and input watts; V-Ray leaves the factor out, Cycles not (measured)
    if nv * nh > MAX_VALUES:
        raise IesError("%d x %d candelas are more than %d" % (nv, nh, MAX_VALUES))
    if not n.has(nv + nh + nv * nh):
        raise IesError("the file ends inside its angles or candelas")
    vertical = n.numbers(nv, "vertical angles", counted=True)
    horizontal = n.numbers(nh, "horizontal angles", counted=True)
    candelas = n.numbers(nv * nh, "candelas", counted=True)
    if any(b < a for a, b in zip(vertical, vertical[1:])):
        raise IesError("its vertical angles are not in order" + (" from 0 to 180 degrees" if kind == TYPE_C else ""))
    if any(b < a for a, b in zip(horizontal, horizontal[1:])):
        raise IesError("its horizontal angles are not in order" + (" from 0 to 360 degrees" if kind == TYPE_C else ""))
    if any(c < 0 for c in candelas):
        raise IesError("a candela value is negative")
    table = _flux(vertical, horizontal, candelas) if kind == TYPE_C else \
        _flux_ab(vertical, horizontal, candelas, kind)
    flux = table * multiplier * ballast
    if not math.isfinite(flux):
        raise IesError("its flux is out of range")
    up = 0.0
    if kind == TYPE_C and table > 0:
        up = min(1.0, max(0.0, _flux(vertical, horizontal, candelas, above=90.0) / table))
    return Photometry(lamps, rated, multiplier, flux, ballast_lamp, tuple(horizontal), max(candelas) * multiplier,
                      _nadir(vertical, horizontal, candelas, kind) * multiplier, up, data[:n.at].decode("latin-1"))


def _at(xs, ys, x):
    """ys linear in xs (in order, x inside them) at x; a repeated angle takes its first value."""
    i = bisect.bisect_left(xs, x)
    if xs[i] == x:
        return ys[i]
    return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / (xs[i] - xs[i - 1])


def _nadir(vertical, horizontal, candelas, kind):
    """The candela straight down: type C at vertical 0 (the mean of the planes; 0 when the table starts past it),
    types A and B at vertical 0 and horizontal 0 (inside every range read)."""
    nv = len(vertical)
    if kind == TYPE_C:
        return sum(candelas[0::nv]) / len(horizontal) if vertical[0] == 0 else 0.0
    planes = [_at(vertical, candelas[j * nv:(j + 1) * nv], 0.0) for j in range(len(horizontal))]
    return _at(horizontal, planes, 0.0)


def _c_zone(a, b, ia, ib):
    """The integral of sin t over [a, b] (radians from the nadir) times the intensity linear in t from ia to ib."""
    return ia * math.cos(a) - ib * math.cos(b) + (ib - ia) * (math.sin(b) - math.sin(a)) / (b - a) if b > a else 0.0


def _ab_zone(a, b, ia, ib):
    """The integral of cos t over [a, b] (radians of latitude) times the intensity linear in t from ia to ib."""
    return ib * math.sin(b) - ia * math.sin(a) + (ib - ia) * (math.cos(b) - math.cos(a)) / (b - a) if b > a else 0.0


def _planes(vertical, horizontal, candelas, zone, above=None):
    """Per horizontal plane the integral over its vertical angles (the candelas linear in angle between them); above:
    over the angles past that one (degrees) only."""
    nv = len(vertical)
    rad = [math.radians(a) for a in vertical]
    planes = []
    for j in range(len(horizontal)):
        row = candelas[j * nv:(j + 1) * nv]
        total = 0.0
        for i in range(nv - 1):
            ra, ia, ib = rad[i], row[i], row[i + 1]
            if above is not None and vertical[i] < above:
                if vertical[i + 1] <= above:
                    continue
                ia += (ib - ia) * (above - vertical[i]) / (vertical[i + 1] - vertical[i])
                ra = math.radians(above)
            total += zone(ra, rad[i + 1], ia, ib)
        planes.append(total)
    return planes


def _trapezoid(planes, horizontal):
    return sum((p + q) * 0.5 * math.radians(b - a)
               for p, q, a, b in zip(planes, planes[1:], horizontal, horizontal[1:]))


def _flux(vertical, horizontal, candelas, above=None):
    """Lumens of a type C candela table (candelas: one run of len(vertical) per horizontal angle); above: those of
    the vertical angles past that one (degrees) only."""
    if vertical[0] < 0 or vertical[-1] > 180:
        raise IesError("its vertical angles are not in order from 0 to 180 degrees")
    if horizontal[0] < 0 or horizontal[-1] > 360:
        raise IesError("its horizontal angles are not in order from 0 to 360 degrees")
    nv = len(vertical)
    if horizontal[0] == 0 and 180 < horizontal[-1] < 360:  # no symmetry, the last plane short of 360: close it
        horizontal = horizontal + [360.0]
        candelas = candelas + candelas[:nv]
    span = horizontal[-1] - horizontal[0]
    if horizontal[0] not in (0, 90) or span not in _SPANS or (len(horizontal) > 1) != (span > 0):
        raise IesError("its horizontal angles run from %g to %g degrees: not one of LM-63's symmetries"
                       % (horizontal[0], horizontal[-1]))
    planes = _planes(vertical, horizontal, candelas, _c_zone, above)
    if len(planes) == 1:
        return 2.0 * math.pi * planes[0]
    return _trapezoid(planes, horizontal) * 360.0 / span


def _flux_ab(vertical, horizontal, candelas, kind):
    """Lumens of a type A or B candela table as V-Ray renders it (measured, docs/FORMAT.md "VRayIES type A and B
    ranges, measured"): vertical angles (latitude) from -90 or 0 to 90, each run from 0 going on below 0 along its first
    segment (floored at 0 cd); horizontal ones from -90 to 90, from -180 to 180 (only -90 to 90 counts), or (type
    B) from 0 to 90 mirrored; type A from 0 to 90 renders nothing."""
    name = "?CBA"[kind]
    if vertical[0] not in (-90, 0) or vertical[-1] != 90:
        raise IesError("its vertical angles run from %g to %g degrees: not one of type %s's"
                       % (vertical[0], vertical[-1], name))
    if (horizontal[0], horizontal[-1]) not in ((-90, 90), (-180, 180), (0, 90)):
        raise IesError("its horizontal angles run from %g to %g degrees: not one of type %s's"
                       % (horizontal[0], horizontal[-1], name))
    if horizontal[0] == 0 and kind != TYPE_B:
        return 0.0  # V-Ray renders type A from 0 to 90 black (its own flux of 100 cd: 1.257 lm)
    nv = len(vertical)
    # every plane counts here, also those past +-90 a cut drops: V-Ray's render of one plane depends on the others
    varies = vertical[0] == 0 and any(len(set(candelas[j:j + nv])) > 1 for j in range(0, len(candelas), nv))
    if varies and nv > 3:
        raise IesError("its candelas vary over %d vertical angles from 0: V-Ray renders the lower half black "
                       "where its own flux goes on below 0 (2 or 3 angles are read)" % nv)
    if varies and vertical[1] < 30:
        raise IesError("its candelas vary below a first vertical angle of %g degrees from 0: going on below 0 is "
                       "measured from 30" % vertical[1])
    planes = _planes(vertical, horizontal, candelas, _ab_zone)
    if vertical[0] == 0:  # a constant run adds its value at 0 whatever the first angle (0 included)
        planes = [p + (_below_0(math.radians(vertical[1]), candelas[j * nv], candelas[j * nv + 1]) if varies
                       else candelas[j * nv]) for j, p in enumerate(planes)]
    if horizontal[0] == -180:
        horizontal, planes = _cut(horizontal, planes)
    return _trapezoid(planes, horizontal) * (2.0 if horizontal[0] == 0 else 1.0)


def _below_0(b, i0, i1):
    """The integral of cos t over [-pi/2, 0] times the run's first segment (i0 cd at 0, i1 at b radians) going on
    below 0, floored at 0 cd."""
    slope = (i1 - i0) / b
    a = -0.5 * math.pi
    if i0 + slope * a < 0:
        a = -i0 / slope  # slope > 0 here: the line meets 0 cd at a, in (-pi/2, 0]
    return _ab_zone(a, 0.0, max(0.0, i0 + slope * a), i0)


def _cut(horizontal, planes):
    """The planes from -90 to 90 of horizontal angles from -180 to 180: the ends interpolated linearly."""
    def at(h, pairs):  # the segment nearest the counted side: a repeated angle takes its inner plane
        for a, b, p, q in pairs:
            if min(a, b) <= h <= max(a, b):
                return q if a == b else p + (q - p) * (h - a) / (b - a)
    forward = list(zip(horizontal, horizontal[1:], planes, planes[1:]))
    backward = [(b, a, q, p) for a, b, p, q in reversed(forward)]
    inner = [(h, p) for h, p in zip(horizontal, planes) if -90 < h < 90]
    return ([-90.0] + [h for h, _ in inner] + [90.0],
            [at(-90.0, backward)] + [p for _, p in inner] + [at(90.0, forward)])


class Lookup:
    """The IES files of one scene description: found by index (a convert.textures.TextureIndex: its rules, never a
    UNC path or a link), each file read once."""

    def __init__(self, index):
        self.index = index
        self._read = {}

    def photometry(self, path, resolved=""):
        """(Photometry, None) of the file a stored path names; (None, why) when it is found but not read, or not
        found where the walk of the texture folders stopped short (it may be past that); (None, None) when it is not
        found."""
        return self.found(path, resolved)[1:]

    def found(self, path, resolved=""):
        """(the base name of the file found, or None, then photometry()'s pair)."""
        found = self.index.find(path, resolved)
        if found is None:
            stopped = self.index.stopped_for(path, resolved)  # each rule was walked for this name
            return (None, None, "not found: " + "; ".join(stopped)) if stopped else (None, None, None)
        if found.path not in self._read:
            try:
                self._read[found.path] = read(found.path), None
            except IesError as e:
                self._read[found.path] = None, str(e)
        return (os.path.basename(found.path),) + self._read[found.path]
