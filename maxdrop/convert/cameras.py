# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""3ds Max cameras as Blender cameras: the lens and sensor that give 3ds Max's horizontal field of view whatever the
render aspect, lens shift, clipping and orthographic width in meters; the render size and the view 3ds Max renders.

    camera_class(scene, i)              # FREE, TARGET, PHYSICAL, VRAY; None: not a camera read here
    values, issues = read_params(scene, i)   # {name: value} with CLASS; CameraError without its block
    distance = focus_target(values, target)  # the target distance that counts: a targeted camera's to its target
    uses_target(values)                 # whether the framing depends on it (part of the key)
    cd, issues = describe(key, name, values, meters, mm, target)   # CameraDescription
    fov = horizontal_fov(values, mm, target)  # radians, as 3ds Max and V-Ray render
    settings, issues = render_settings(scene)   # RenderSettings or None: width, height, pixel aspect, locked view
    views = saved_views(cf)             # SavedViews of the current viewport layout (Config stream), or None
    views = views_of(chunk)             # the same of the Config stream's 0x2080 chunk
    node, issue, note = render_camera(settings, views, cameras)   # the camera node of the view 3ds Max renders

The field of view (docs/FORMAT.md, "Cameras"; checked against 3ds Max's own camera state, EvalCameraState, in the
fixture's oracle, and against renders):

- Free / Target camera: the FOV parameter (radians, horizontal whatever FOV type is shown). Orthographic: the view
  is 2 tdist tan(FOV / 2) wide, tdist a free camera's target distance or a target camera's distance to its target.
- Physical: a specified FOV as it is; else the thin lens focused at d (the focus distance when specified, else the
  target distance: a targeted camera's distance to its target, which the stored one need not be), in mm through
  the system unit: v = 1 / (1/f - 1/d), the effective focal length zoom (f + breathing (v - f)), FOV 2 atan(film /
  (2 f_eff)).
- VRayPhysicalCamera: the same with a breathing of 1 (V-Ray renders the focused image distance; the rules source's
  2 atan(film / (2 f zoom)) does not); a specified FOV without the zoom.

A focus distance at or inside the focal length, or none, takes no breathing (an issue). Blender gets sensor_fit
HORIZONTAL, so its horizontal FOV is 2 atan(sensor / (2 lens)) for any aspect: sensor = 36 mm for the standard cameras
(3ds Max's aperture width), the film width for the others; lens = sensor / (2 tan(FOV / 2)), at least Blender's 1 mm
(an issue). Lens shift (renders: the image only translates): both store it as a fraction of the film width
(Physical's UI shows percent), which is Blender's shift in image widths, negated (Blender moves the frame, 3ds Max
the image). Tilt corrections,
depth of field, distortion, a multi-pass effect and V-Ray's exposure have no Blender equivalent here: issues. Clipping
(clip manually, clip on) sets clip_start / clip_end in meters; without it Blender's own stay.

Render settings: the RenderEnvironment object's chunk 0x0110 / 0x2000: width, height, pixel aspect and, when the
render view is locked, its viewport index. Saved views: the Config stream's current layout, each viewport's view type
and the node it looks through. render_camera picks the locked render view, else the active viewport; when it looks
through a built camera that is the scene camera, else the first camera: a note when the saved views were read (a
view through no camera is common and loses nothing), an issue otherwise (none stored, a damaged Config stream:
SavedViews.damaged, no view to pick, its viewport record unreadable, or a view through a camera not built).

The file comes from anywhere: a parameter that is animated, missing or no finite number takes its default (an
issue); a block that cannot be read raises CameraError; render settings and views out of range are left out (an issue
or None). No bpy.
"""
import collections
import math
import struct

from ..reader import chunks, classids, pblock
from ..reader.errors import MaxFileError
from .params import finite

ChunkError = chunks.ChunkError


class CameraError(ChunkError):
    pass


CLASS = "class"
FREE, TARGET, PHYSICAL, VRAY = "Free", "Target", "Physical", "VRayPhysicalCamera"
_FAMILIES = {classids.FREE_CAMERA: FREE, classids.TARGET_CAMERA: TARGET, classids.PHYSICAL_CAMERA: PHYSICAL,
             classids.VRAY_PHYSICAL_CAMERA: VRAY}
PERSP, ORTHO = "PERSP", "ORTHO"

STANDARD_SENSOR = 36.0  # mm: 3ds Max's render aperture width, the standard cameras' film
MIN_LENS = 1.0  # mm: Blender's smallest Camera.lens (hard limit; the 5000 mm of its slider is soft)
MIN_SENSOR = 1.0  # mm: Blender's smallest Camera.sensor_width
MIN_CLIP = 1e-6  # m: Blender's smallest clip_start
MAX_FILM = 1e6  # mm: a film or gate past this is no camera's: the standard 36 mm is used
RESOLUTION_RANGE = (4, 65536)  # Blender's render size per axis
ASPECT_RANGE = (1.0 / 200.0, 200.0)  # Blender's pixel_aspect_x / pixel_aspect_y run from 1 to 200
MAX_VIEWPORTS = 16

# standard cameras: old ParamBlock indices and chunks of the camera object
_OLD_FOV, _OLD_TDIST, _OLD_NEAR, _OLD_FAR, _OLD_MULTIPASS = 0, 1, 2, 3, 6
_OLD = {"fov": (_OLD_FOV, math.radians(45.0)), "target_distance": (_OLD_TDIST, 160.0), "near": (_OLD_NEAR, 1.0),
        "far": (_OLD_FAR, 1000.0), "multipass": (_OLD_MULTIPASS, 0)}
_ORTHO, _CLIP = 0x268C, 0x2686

# name: (parameter id, default of a new camera) in ParamBlock2 block 0
_PHYSICAL = {"targeted": (0, 1), "target_distance": (8, 5000.0), "film": (4, 36.0), "focal": (5, 40.0),
             "specify_fov": (19, 0), "fov_degrees": (20, 45.0), "zoom": (7, 1.0), "breathing": (54, 1.0),
             "specify_focus": (10, 0), "focus": (9, 5000.0), "dof": (11, 0), "shift_x": (39, 0.0),
             "shift_y": (40, 0.0), "tilt_x": (41, 0.0), "tilt_y": (42, 0.0), "distortion": (44, 0),
             "clip": (47, 0), "near": (48, 0.0), "far": (49, 1e6)}
_VRAY = {"targeted": (8, 1), "target_distance": (5, 200.0), "film": (0, 36.0), "focal": (1, 40.0),
         "specify_fov": (47, 0), "fov_degrees": (48, 45.0), "zoom": (3, 1.0), "specify_focus": (7, 0),
         "focus": (6, 200.0), "dof": (25, 0), "shift_x": (41, 0.0), "shift_y": (42, 0.0), "tilt_y": (18, 0.0),
         "tilt_x": (40, 0.0), "distortion": (4, 0.0), "exposure": (10, 1), "clip": (32, 0), "near": (33, 0.0),
         "far": (34, 1000.0)}
_NEEDED = ("film", "focal", "fov_degrees", "zoom")

MISSING = "%s is animated or not stored: %r is used"
NO_FOCUS = "focused at %g mm, not beyond its focal length (%g mm): its field of view is taken without lens breathing"
DOF = "depth of field is not imported"
TILT = "its tilt correction (%g, %g) is not imported: Blender has no keystone correction"
DISTORTION = "its lens distortion is not imported"
EXPOSURE = "its exposure is not imported: Blender renders as if the camera had none"
MULTIPASS = "its multi-pass effect (depth of field or motion blur) is not imported"
LENS = "its field of view (%g degrees) needs a lens of %g mm: Blender's shortest, %g mm, is used"
SENSOR = "film width %r mm is out of Blender's range: %g mm is used"
NO_LENS = "focal length %r mm with zoom %r gives no field of view: 45 degrees is used"
NO_WIDTH = "its orthographic width cannot be computed (target distance %r): 1 m is used"
NO_TARGET = "its orthographic width needs the distance to its target, which is not imported: 1 m is used"
BAD_SIZE = "the render size %s is out of Blender's range: Blender's is kept"
BAD_ASPECT = "pixel aspect %r is out of Blender's range: Blender's is kept"
NO_VIEW = "no saved view: the first camera, %s, is the scene camera"
DAMAGED_VIEWS = "the saved views cannot be read (%s): the first camera, %s, is the scene camera"
BAD_VIEW = "the saved view of viewport %d cannot be read: the first camera, %s, is the scene camera"
UNBUILT_VIEW = "the view 3ds Max renders (viewport %d) looks through a camera that is not imported: the first " \
    "camera, %s, is the scene camera"
NOT_A_CAMERA = "the first camera: the view 3ds Max renders (viewport %d) looks through no camera"  # a note


class CameraDescription:
    """One camera: kind PERSP or ORTHO; lens and sensor (mm; sensor_fit HORIZONTAL), fov the horizontal field of view
    (radians); shift_x, shift_y in image widths; clip_start, clip_end in meters (None: Blender's own); ortho_scale the
    orthographic width in meters; users the object indices of the nodes that share it, in walk order."""
    __slots__ = ("key", "name", "kind", "lens", "sensor", "fov", "shift_x", "shift_y", "clip_start", "clip_end",
                 "ortho_scale", "users")

    def __init__(self, key, name, kind=PERSP, lens=50.0, sensor=STANDARD_SENSOR, fov=0.0, shift_x=0.0, shift_y=0.0,
                 clip_start=None, clip_end=None, ortho_scale=1.0):
        self.key, self.name, self.kind, self.lens, self.sensor, self.fov = key, name, kind, lens, sensor, fov
        self.shift_x, self.shift_y, self.clip_start, self.clip_end = shift_x, shift_y, clip_start, clip_end
        self.ortho_scale = ortho_scale
        self.users = []

    def __repr__(self):
        return "CameraDescription(%r, %s, %g mm on %g mm)" % (self.name, self.kind, self.lens, self.sensor)


RenderSettings = collections.namedtuple("RenderSettings", "width height pixel_aspect view index")
RenderSettings.__doc__ = """The render settings: width and height in pixels, pixel_aspect (each None when not stored
or out of Blender's range), view the 0-based viewport index of a locked render view (None: the active viewport
renders), index the RenderEnvironment's object index."""
SavedViews = collections.namedtuple("SavedViews", "viewports active damaged", defaults=(None,))
SavedViews.__doc__ = """The current viewport layout: viewports [(view type, node object index or None)], active the
0-based index of the active viewport (None when not stored); damaged the reason the Config stream cannot be read
(then no viewports), else None."""
CAMERA_VIEW = 8  # the view type of a viewport that looks through a camera


def camera_class(scene, i):
    """The family of camera object i (FREE, TARGET, PHYSICAL, VRAY), None for any other object."""
    entry = scene.entry(i)
    if entry is None or entry.superclass != classids.SC_CAMERA:
        return None
    return _FAMILIES.get(entry.class_id)


def _block(scene, i, kind):
    """The parameter block of camera object i at reference 0: an old ParamBlock (kind 1) or a ParamBlock2."""
    refs = scene.refs(i)
    target = refs.get(0)
    if kind == 1:
        if target is None or not 0 <= target < len(scene) or not scene.is_a(target, classids.SC_PARAMETER_BLOCK,
                                                                             classids.PARAM_BLOCK):
            raise CameraError("no parameter block (reference slot 0)")
        return pblock.ParamBlock.from_chunk(scene.chunk(target))
    te = scene.entry(target) if target is not None and 0 <= target < len(scene) else None
    if te is None or te.superclass != classids.SC_PARAMETER_BLOCK2:
        raise CameraError("no parameter block (reference slot 0)")
    entry = scene.entry(i)
    return pblock.ParamBlock2.from_chunk(scene.chunk(target), scene.refs(target), refs, len(scene),
                                         (entry.superclass, entry.class_id))


def _number(v, default):
    if not finite(v):
        return None
    return int(v) if isinstance(default, int) else float(v)


def read_params(scene, i):
    """(values of camera object i, issues): {name: value} with CLASS; CameraError without its block."""
    family = camera_class(scene, i)
    if family is None:
        raise CameraError("not a camera read here")
    values, issues = {CLASS: family}, []
    if family in (FREE, TARGET):
        block = _block(scene, i, 1)
        issues += block.issues
        for name, (index, default) in _OLD.items():
            v = _number(block.get(index), default)
            if v is None:
                issues.append(MISSING % (name, default))
                v = default
            values[name] = v
        chunk = scene.chunk(i)
        values["ortho"] = chunk.container and chunk.first(_ORTHO) is not None
        values["clip"] = chunk.container and chunk.first(_CLIP) is not None
        return values, issues
    block = _block(scene, i, 2)
    issues += block.issues
    for name, (pid, default) in (_PHYSICAL if family == PHYSICAL else _VRAY).items():
        raw = block.get(pid)
        v = None if isinstance(raw, pblock.Animated) else _number(raw, default)
        if v is None:
            if raw is not None or name in _NEEDED:  # animated or no number; a missing other one is its default
                issues.append(MISSING % (name, default))
            v = default
        values[name] = v
    if family == VRAY:
        values["breathing"] = 1.0
    values["ortho"] = False
    return values, issues


def focus_target(values, target):
    """The target distance that counts (file units): a targeted Physical or V-Ray camera's distance to its target
    node when it has one (target), else the stored one; a target camera's distance to its target; a free camera's
    own."""
    family = values[CLASS]
    if family == TARGET or (family in (PHYSICAL, VRAY) and values["targeted"]):
        if target is not None:
            return target
    return values["target_distance"] if family != TARGET else 0.0


def uses_target(values):
    """Whether the camera's framing depends on the distance to its target: an orthographic width, or the thin lens of
    a Physical or V-Ray camera focused at its target."""
    if values.get("ortho"):
        return True
    return values[CLASS] in (PHYSICAL, VRAY) and not values["specify_fov"] and not values["specify_focus"]


def horizontal_fov(values, mm=1.0, target=None, issues=None):
    """The horizontal field of view in radians that 3ds Max and V-Ray render with; mm: millimeters per file unit
    (the focus distance is in file units, the focal length in mm); target: the distance to a target node."""
    family = values[CLASS]
    if family in (FREE, TARGET):
        return values["fov"]
    if values["specify_fov"]:
        return math.radians(values["fov_degrees"])
    f = values["focal"]
    d = (values["focus"] if values["specify_focus"] else focus_target(values, target)) * mm
    if finite(d) and d > f > 0:
        v = 1.0 / (1.0 / f - 1.0 / d)
        f = f + values["breathing"] * (v - f)
    elif issues is not None and values["breathing"] and finite(f) and f > 0:
        issues.append(NO_FOCUS % (d, f))
    f *= values["zoom"]
    if not (finite(f) and f > 0 and values["film"] > 0):
        if issues is not None:
            issues.append(NO_LENS % (values["focal"], values["zoom"]))
        return math.radians(45.0)
    return 2.0 * math.atan(values["film"] / (2.0 * f))


def describe(key, name, values, meters=1.0, mm=1.0, target=None):
    """(CameraDescription of a camera's values, issues). meters: per file unit (clipping, orthographic width); mm:
    millimeters per file unit for the thin lens (the system unit's, whatever the import's scale); target: the
    distance to its target node in file units (None without one)."""
    family = values[CLASS]
    issues = []
    fov = horizontal_fov(values, mm, target, issues)
    if not (finite(fov) and 0 < fov < math.pi):
        issues.append("field of view %r is out of range: 45 degrees is used" % (fov,))
        fov = math.radians(45.0)
    sensor = STANDARD_SENSOR if family in (FREE, TARGET) else values["film"]
    if not (finite(sensor) and MIN_SENSOR <= sensor <= MAX_FILM):
        clamped = STANDARD_SENSOR if not finite(sensor) or sensor > MAX_FILM else MIN_SENSOR
        issues.append(SENSOR % (sensor, clamped))
        sensor = clamped
    lens = sensor / (2.0 * math.tan(fov / 2.0))
    if lens < MIN_LENS:
        issues.append(LENS % (math.degrees(fov), lens, MIN_LENS))
        lens = MIN_LENS
    cd = CameraDescription(key, name, lens=lens, sensor=sensor, fov=fov)
    if values.get("ortho"):
        cd.kind = ORTHO
        distance = focus_target(values, target)
        width = 2.0 * abs(distance) * math.tan(fov / 2.0) * meters
        if finite(width) and width > 0:
            cd.ortho_scale = width
        else:
            issues.append(NO_TARGET if family == TARGET and target is None else NO_WIDTH % (distance,))
    if values.get("clip"):
        near, far = abs(values["near"]) * meters, abs(values["far"]) * meters
        cd.clip_start = max(MIN_CLIP, near)
        cd.clip_end = max(cd.clip_start * 1.001, far)
    if family in (PHYSICAL, VRAY):
        cd.shift_x, cd.shift_y = -values["shift_x"], -values["shift_y"]
        if values["tilt_x"] or values["tilt_y"]:
            issues.append(TILT % (values["tilt_x"], values["tilt_y"]))
        if values["dof"]:
            issues.append(DOF)
        if values["distortion"]:
            issues.append(DISTORTION)
        if family == VRAY and values["exposure"]:
            issues.append(EXPOSURE)
    elif values["multipass"]:
        issues.append(MULTIPASS)
    return cd, issues


# RenderEnvironment: chunk 0x0110 / 0x2000
_RENDER, _RENDER_DATA = 0x0110, 0x2000
_WIDTH, _HEIGHT, _ASPECT, _LOCKED_VIEW = 0x0190, 0x0200, 0x0210, 0x05F0


def _leaf(parent, cid, fmt):
    c = parent.first(cid)
    if c is None or c.container or c.payload_size < struct.calcsize(fmt):
        return None
    return c.unpack(fmt)[0]


def render_settings(scene):
    """(RenderSettings, issues) of the scene's RenderEnvironment: width and height None when not stored, an issue when
    out of range; (None, issues) when there is none or its render settings cannot be read (an issue)."""
    holders = {e.index for e in scene.classes
               if e.superclass == classids.SC_RENDER_ENVIRONMENT and e.class_id == classids.RENDER_ENVIRONMENT}
    for i in range(len(scene) if holders else 0):
        if scene.class_index(i) not in holders:
            continue
        try:
            chunk = scene.chunk(i)
            data = chunk.first(_RENDER) if chunk.container else None
            data = data.first(_RENDER_DATA) if data is not None and data.container else None
            if data is None or not data.container:
                continue
            width, height = _leaf(data, _WIDTH, "<i"), _leaf(data, _HEIGHT, "<i")
            aspect, view = _leaf(data, _ASPECT, "<f"), _leaf(data, _LOCKED_VIEW, "<i")
        except ChunkError as exc:
            return None, ["render settings cannot be read: %s" % exc]
        issues = []
        low, high = RESOLUTION_RANGE
        if width is None or height is None:  # not stored: the report says Blender's is kept
            width = height = None
        elif not (low <= width <= high and low <= height <= high):
            issues.append(BAD_SIZE % ("%d x %d" % (width, height)))
            width = height = None
        if aspect is not None and not (finite(aspect) and ASPECT_RANGE[0] <= aspect <= ASPECT_RANGE[1]):
            issues.append(BAD_ASPECT % aspect)
            aspect = None
        if view is not None and not 0 <= view < MAX_VIEWPORTS:
            view = None
        return RenderSettings(width, height, None if aspect is None else float(aspect), view, i), issues
    return None, []


# Config stream: 0x2080 holds the viewport layout (a file saved as 3ds Max 2012), or 0x8200 the layout tabs
_LAYOUTS, _LAYOUT_SET, _CURRENT, _LAYOUT = 0x2080, 0x8200, 0x8210, 0x8220
_VIEWPORT, _ACTIVE = 0x2810, 0x2820
_VIEW_TYPE_AT, _VIEW_NODE_AT, _VIEW_SIZE = 4, 76, 80
MAX_CONFIG = 1 << 24  # bytes: a Config stream is tens of kilobytes


def saved_views(cf):
    """The SavedViews of the current viewport layout in a compound file's Config stream, None when it has no Config
    stream or no layout; a damaged one (or one compressed past the cap) gives SavedViews([], None, reason)."""
    try:
        if not cf.exists("Config"):
            return None
        return views_of(chunks.index(cf.open("Config", max_size=MAX_CONFIG)).first(_LAYOUTS))
    except (MaxFileError, OSError) as exc:
        return SavedViews([], None, str(exc) or type(exc).__name__)


def views_of(holder):
    """The SavedViews of the Config stream's 0x2080 chunk: its 0x8200 tabs, 0x8210 the current tab's position among
    the 0x8220 layouts (the 0x8240 before each is not its index: 0 on every tab of corpus scene B); without 0x8200,
    0x2080 is the layout itself. None when there is no layout; ChunkError when a chunk is damaged."""
    if holder is None or not holder.container:
        return None
    tabs = holder.first(_LAYOUT_SET)
    if tabs is None:
        layout = holder
    elif not tabs.container:
        return None
    else:
        current = _leaf(tabs, _CURRENT, "<i")
        layouts = [c for c in tabs.children if c.id == _LAYOUT and c.container]
        if current is None or not 0 <= current < len(layouts):
            return None
        layout = layouts[current]
    viewports = []
    for k in range(MAX_VIEWPORTS):
        v = layout.first(_VIEWPORT + k)
        if v is None:
            break
        if v.container or v.payload_size < _VIEW_SIZE:
            viewports.append((None, None))
            continue
        kind = v.unpack("<I", _VIEW_TYPE_AT)[0]
        node = v.unpack("<i", _VIEW_NODE_AT)[0]
        viewports.append((kind, node if kind == CAMERA_VIEW and node >= 0 else None))
    if not viewports:
        return None
    active = _leaf(layout, _ACTIVE, "<i")
    return SavedViews(viewports, active if active is not None and 0 <= active < len(viewports) else None)


def render_camera(settings, views, cameras, names=None):
    """(node index of the scene camera, issue, note): the camera the locked render view, else the active viewport
    looks through when it is among cameras (node indices of the camera nodes built, in walk order), with neither;
    else the first of cameras with a note when the view was read and looks through no camera, or an issue (no saved
    views, damaged ones, no view index in range, its viewport record unreadable, a camera that was not built). (None,
    None, None) without cameras. names: {node index: name} for the issue."""
    if not cameras:
        return None, None, None
    first = cameras[0]
    label = (names or {}).get(first, "object %d" % first)
    if views is not None and views.damaged is not None:
        return first, DAMAGED_VIEWS % (views.damaged, label), None
    view = settings.view if settings is not None and settings.view is not None else (
        views.active if views is not None else None)
    if views is None or view is None or not 0 <= view < len(views.viewports):
        return first, NO_VIEW % label, None
    kind, node = views.viewports[view]
    if kind is None:  # its record cannot be read
        return first, BAD_VIEW % (view + 1, label), None
    if kind == CAMERA_VIEW:
        if node in cameras:
            return node, None, None
        return first, UNBUILT_VIEW % (view + 1, label), None
    return first, None, NOT_A_CAMERA % (view + 1)
