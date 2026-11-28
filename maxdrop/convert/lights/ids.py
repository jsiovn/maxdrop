# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The lights' class ids, parameter ids, units, defaults and the issue texts."""
import math

from ...reader import chunks, classids


ChunkError = chunks.ChunkError


class LightError(ChunkError):
    pass


SLOT_BLOCK = 0
PLANE, DOME, SPHERE, MESH, DISC = 0, 1, 2, 3, 4
TYPE_NAMES = {PLANE: "plane", DOME: "dome", SPHERE: "sphere", MESH: "mesh", DISC: "disc"}
UNITS_DEFAULT, UNITS_LM, UNITS_LM_M2_SR, UNITS_W, UNITS_W_M2_SR = 0, 1, 2, 3, 4
LUMENS_PER_WATT = 683.0
IMAGE_UNIT = 1500.0  # one default (image) unit is IMAGE_UNIT / pi cd/m^2

AREA, POINT, SPOT, SUN_LIGHT = "AREA", "POINT", "SPOT", "SUN"
RECTANGLE, DISK = "RECTANGLE", "DISK"

CLASS = "class"  # the family in a values dict (a VRayLight's has none: VRAY)
VRAY, STANDARD, PHOTOMETRIC, SUN, IES, SKYLIGHT = "VRayLight", "standard", "photometric", "VRaySun", "VRayIES", \
    "Skylight"
OMNI, SPOTLIGHT, DIRECT = "omni", "spot", "direct"
SHAPE_POINT, SHAPE_LINE, SHAPE_RECTANGLE, SHAPE_DISC, SHAPE_SPHERE, SHAPE_CYLINDER = \
    "point", "line", "rectangle", "disc", "sphere", "cylinder"
_FAMILIES = {classids.VRAY_LIGHT: VRAY, classids.VRAY_SUN: SUN, classids.VRAY_IES: IES, classids.SKYLIGHT: SKYLIGHT}
_STANDARD = {classids.OMNI: OMNI, classids.TARGET_SPOT: SPOTLIGHT, classids.FREE_SPOT: SPOTLIGHT,
             classids.FREE_DIRECT: DIRECT, classids.TARGET_DIRECT: DIRECT}
_PHOTOMETRIC = {classids.FREE_POINT_LIGHT: SHAPE_POINT, classids.TARGET_POINT_LIGHT: SHAPE_POINT,
                classids.FREE_LINE_LIGHT: SHAPE_LINE, classids.TARGET_LINE_LIGHT: SHAPE_LINE,
                classids.FREE_RECTANGLE_LIGHT: SHAPE_RECTANGLE, classids.TARGET_RECTANGLE_LIGHT: SHAPE_RECTANGLE,
                classids.FREE_DISC_LIGHT: SHAPE_DISC, classids.TARGET_DISC_LIGHT: SHAPE_DISC,
                classids.FREE_SPHERE_LIGHT: SHAPE_SPHERE, classids.TARGET_SPHERE_LIGHT: SHAPE_SPHERE,
                classids.FREE_CYLINDER_LIGHT: SHAPE_CYLINDER, classids.TARGET_CYLINDER_LIGHT: SHAPE_CYLINDER}

# Measured in V-Ray 5.2: a white floor's pixel is its illuminance in lx / LUX_PER_UNIT, and a standard light of
# multiplier m gives it m.
LUX_PER_UNIT = 1500.0
REFERENCE_DISTANCE = 1.0  # m: where a standard light without decay is as bright as in V-Ray
SUN_IRRADIANCE = 146.4  # W/m^2 per unit of a VRaySun's multiplier (the rules source's 100 klx / 683)
SUN_ANGLE = math.radians(0.53)  # the sun's angular diameter at size multiplier 1
WEB_FALLOFF, WEB_HOTSPOT = 170.0, 100.0  # degrees: the rules source's wide spot for a web or IES
LINE_WIDTH = 0.01  # m: the width of the area light of a diffuse line, the diameter of a diffuse point
MIN_CONE = math.radians(1.0)  # Blender's smallest spot size
# a dome's radiance in W/m^2/sr per unit of its multiplier, per units mode: V-Ray 5.2 white-floor renders against
# Cycles (docs/FORMAT.md, "VRayLight"); the lm modes measured 0.00213024 / 1.43109 (1 / 671.8, not 1 / 683)
DOME_LM = 0.00213024 / 1.43109
DOME_RADIANCE = {0: IMAGE_UNIT / (math.pi * LUMENS_PER_WATT), 1: DOME_LM, 2: DOME_LM, 3: 1.0, 4: 1.0}
ENVIRONMENT_MAP_SLOT = 5  # RenderEnvironment's reference to the environment map

# standard lights: chunks of the light object, old ParamBlock indices
_ON, _DECAY, _CONE, _OVERSHOOT, _NO_DIFFUSE, _NO_SPECULAR, _AMBIENT, _SHADOW = \
    0x2580, 0x25D0, 0x2573, 0x2575, 0x25B0, 0x25B1, 0x2600, 0x2570
DECAY_NONE, DECAY_INVERSE, DECAY_SQUARE = 0, 1, 2
_OLD_COLOR, _OLD_MULTIPLIER, _OLD_HOTSPOT, _OLD_FALLOFF = 0, 1, 4, 5
_OLD_START = {OMNI: 8, SPOTLIGHT: 11, DIRECT: 11}  # decay start
_OLD_NAMES = {_OLD_COLOR: "color", _OLD_MULTIPLIER: "multiplier", _OLD_HOTSPOT: "hotspot", _OLD_FALLOFF: "falloff",
              8: "decay start", 11: "decay start"}
_OLD_DEFAULTS = {_OLD_COLOR: (1.0, 1.0, 1.0), _OLD_MULTIPLIER: 1.0, _OLD_HOTSPOT: 43.0, _OLD_FALLOFF: 45.0,
                 8: 40.0, 11: 40.0}

ISOTROPIC, SPOT_DISTRIBUTION, DIFFUSE_DISTRIBUTION, WEB = 0, 1, 2, 3
# name: (block id, parameter id, default of 3ds Max 2020's new light; shadow on, as before it was read)
_PHOTOMETRIC_PARAMS = {"distribution": (0, 1, ISOTROPIC), "on": (0, 2, 1), "filter": (0, 5, (1.0, 1.0, 1.0)),
                       "intensity": (0, 6, 1500.0), "kelvin": (0, 8, 3600.0), "use_kelvin": (0, 10, 0),
                       "use_dimmer": (0, 18, 0), "dimmer": (0, 19, 100.0), "far": (0, 21, 0), "shadow": (0, 3, 1),
                       "hotspot": (2, 0, 30.0), "falloff": (2, 1, 60.0), "diffuse": (4, 4, 1), "specular": (4, 5, 1),
                       "ambient": (4, 6, 0), "length": (4, 11, 1220.0), "width": (4, 12, 610.0),
                       "radius": (4, 13, 130.0)}
_PHOTOMETRIC_FILE = (3, 0)
_WEB_ROTATION = ((3, 1), (3, 2), (3, 3))  # the web's X, Y, Z rotation, as stored (its unit is not measured)
_SUN_PARAMS = {"on": (0, 0, 1), "multiplier": (0, 2, 1.0), "size": (0, 3, 1.0), "invisible": (0, 9, 0),
               "diffuse": (0, 14, 1), "diffuse_contribution": (0, 19, 1.0), "specular": (0, 15, 1),
               "specular_contribution": (0, 20, 1.0), "filter": (0, 17, (1.0, 1.0, 1.0)), "color_mode": (0, 18, 0)}
_IES_PARAMS = {"on": (0, 0, 1), "temperature": (0, 7, 6500.0), "color": (0, 8, (1.0, 1.0, 1.0)),
               "color_mode": (0, 9, 0), "power": (0, 10, 1500.0), "diffuse": (0, 14, 1),
               "diffuse_contribution": (0, 30, 1.0), "specular": (0, 15, 1), "specular_contribution": (0, 31, 1.0),
               "intensity_type": (0, 32, 0), "override": (0, 34, 0), "shadow": (0, 4, 1), "use_shape": (0, 5, 1),
               "override_shape": (0, 21, 0), "shape_type": (0, 22, 0), "height": (0, 23, 0.0), "width": (0, 24, 0.0),
               "length": (0, 25, 0.0), "diameter": (0, 26, 0.0)}
_IES_FILE = (0, 1)
# a VRayIES shape: (name, the sizes V-Ray's panel enables for it); a sphere is what Blender's radius draws
IES_SPHERE = 3
IES_SHAPES = {0: ("point", ()), 1: ("rectangle", ("height", "width", "length")), 2: ("circle", ("diameter",)),
              IES_SPHERE: ("sphere", ("diameter",)), 4: ("vertical cylinder", ("height", "diameter")),
              5: ("horizontal cylinder", ("length", "diameter")), 6: ("horizontal cylinder", ("width", "diameter")),
              7: ("ellipse", ("height", "width", "length")), 8: ("ellipse", ("height", "width", "length")),
              9: ("ellipsoid", ("height", "width", "length")), 10: ("ellipsoid", ("height", "width", "length")),
              11: ("elliptic cylinder", ("height", "width", "length")),
              12: ("horizontal elliptic cylinder", ("height", "width", "length")),
              13: ("horizontal elliptic cylinder", ("height", "width", "length")), 14: ("vertical circle", ("width",)),
              15: ("vertical ellipse", ("height", "width")), 16: ("cuboid", ("height", "width", "length"))}

P_ON, P_TYPE, P_SIZE0, P_SIZE1, P_COLOR, P_MULTIPLIER = 0, 1, 2, 3, 7, 8
P_DOUBLE_SIDED, P_INVISIBLE, P_UNITS, P_TEXMAP, P_TEXMAP_ON = 9, 10, 12, 18, 19
P_AFFECT_DIFFUSE, P_AFFECT_SPECULAR, P_AFFECT_REFLECTIONS, P_DIRECTIONAL = 25, 26, 30, 36
P_TEMPERATURE, P_COLOR_MODE, P_DIFFUSE, P_SPECULAR = 38, 39, 53, 54
P_DOME_SPHERICAL, P_MESH_SOURCE, P_DOME_LOCKED = 27, 34, 49
P_SHADOW, P_MESH_FLIP = 32, 35
SLOT_MESH = 1  # a mesh light's own mesh object (V-Ray's Pick mesh with Replace mesh with light on)
MESH_OBJECT = "mesh object"  # its object index in a VRayLight's values, None without one

# V-Ray 5.2's values of a new VRayLight (sizes in world units)
DEFAULTS = {P_ON: 1, P_TYPE: PLANE, P_SIZE0: 10.0, P_SIZE1: 10.0, P_COLOR: (1.0, 1.0, 1.0), P_MULTIPLIER: 30.0,
            P_DOUBLE_SIDED: 0, P_INVISIBLE: 0, P_UNITS: UNITS_DEFAULT, P_TEXMAP_ON: 1, P_AFFECT_DIFFUSE: 1,
            P_AFFECT_SPECULAR: 1, P_AFFECT_REFLECTIONS: 1, P_DIRECTIONAL: 0.0, P_TEMPERATURE: 6500.0,
            P_COLOR_MODE: 0, P_DIFFUSE: 1.0, P_SPECULAR: 1.0, P_DOME_SPHERICAL: 1, P_DOME_LOCKED: 0,
            P_SHADOW: 1, P_MESH_FLIP: 0}
_NAMES = {P_ON: "on", P_TYPE: "type", P_SIZE0: "size0", P_SIZE1: "size1", P_COLOR: "color",
          P_MULTIPLIER: "multiplier", P_DOUBLE_SIDED: "doubleSided", P_INVISIBLE: "invisible",
          P_UNITS: "normalizeColor", P_TEXMAP_ON: "texmap_on", P_AFFECT_DIFFUSE: "affect_diffuse",
          P_AFFECT_SPECULAR: "affect_specular", P_AFFECT_REFLECTIONS: "affect_reflections",
          P_DIRECTIONAL: "lightDistribution", P_TEMPERATURE: "color_temperature", P_COLOR_MODE: "color_mode",
          P_DIFFUSE: "diffuse_contribution", P_SPECULAR: "specular_contribution", P_DOME_SPHERICAL: "dome_spherical",
          P_DOME_LOCKED: "texmap_locktodome", P_SHADOW: "castShadows",
          P_MESH_FLIP: "mesh_flip"}

NO_MESH = "a mesh light without a mesh (none picked, or its node deleted): not imported"
EMITTER = "a mesh light is an emitter, not a light"
EMITTER_CLASS = "its mesh is a %s, which MaxDrop does not build: not imported"
EMITTER_UNREAD = "its mesh cannot be read: %s"
EMITTER_MODIFIERS = ("the modifiers of its mesh (%s) are not applied: the emitter is its mesh below them (V-Ray "
                     "emits the evaluated mesh, and in lm and W spreads the flux over that one's area)")
EMITTER_TEXMAP = "its texture is not imported: the emitter has its color"
EMITTER_CONTRIBUTION = "%s contribution %g is not imported: an emitter has no such factor"
EMITTER_GLOSSY = ("affect specular %s, affect reflections %s: Blender has one switch for both, glossy rays, "
                  "which stays on")
EMITTER_SHADOW = "cast shadows off is not imported: what the emitter lights casts shadows"
SPREAD_UNITS = (UNITS_LM, UNITS_W)  # the units modes whose flux a mesh light spreads over its mesh's area
EMITTER_FLAT = "its mesh has no area: 0 W/m2/sr (V-Ray spreads its %s over the mesh's area)"
NOT_SKYLIGHT = "a Skylight is not imported yet (Skylight -> World is later work)"
DOME_OFF = "dome light off: not imported"
SECOND_DOME = "a second dome light: not imported (Blender has one World, %s's)"
DOME_MIRRORED = "the dome node is mirrored: its rotation without the mirror is used"
DOME_FLAT = ("the dome node's scale is 0: its rotation is not known, none is used (a locked texture and a hemisphere "
             "take the world's axes)")
DOME_NO_TEXTURE = "its texture converts to nothing: the World has its color"
DOME_ROOT = "its texture is not an image map (%s): the World has its color"
DOME_NOT_FOUND = "its texture %s is not found: the World has its color"
DOME_PROJECTION = "its texture %s is not in spherical mapping (%s): drawn as spherical"
DOME_CORONA = ("its texture %s is a CoronaBitmap, which V-Ray 5.2 does not project on a dome (one flat color, "
               "measured): drawn as spherical")
DOME_VERTICAL = "its texture %s's vertical rotation %g degrees is not imported"
DOME_AXIAL = "its texture %s's axial rotation %g degrees is not imported"
DOME_SWITCH = "its texture %s's %s is not imported"
DOME_PLACEMENT = "its texture %s's offset, tiling or angle is not imported"
DOME_OUTPUT = "its texture %s's Output (invert, RGB level or offset) is not imported"
DOME_GAMMA = "its texture %s's gamma %g is not applied"
DOME_FLOAT_OFF = ("its texture %s is a float image in a scene saved with the gamma off: the camera sees the sky decoded, "
                  "as V-Ray 5.2 shows it, but the light it gives (reflections and the sky through glass too) is kept "
                  "linear (its own decode), as the dome's multiplier is; V-Ray shows that light display-referred, so "
                  "below 1 it is brighter and above 1 darker than V-Ray's (measured; decoded as on a material a sun "
                  "would be orders of magnitude too bright)")
DOME_CROP = "its texture %s's crop or placement is not imported"
DOME_SHADOW = "cast shadows off is not imported: the World casts shadows"
SKY = "the environment map is a VRaySky: not imported yet (environment -> World is later work)"
NO_DECAY = "no decay: Blender's light falls off with the square of the distance; as bright as in 3ds Max at %g m"
INVERSE = "inverse decay: Blender's light falls off with the square of the distance; as bright as in 3ds Max at %g m"
ZERO_START = "decay start 0: its power grows with the square of the decay start, so 0 W"
BEAM = "its beam (%g m across) is not imported: the sun lights the whole scene"
RECTANGLE_CONE = "its rectangular cone is drawn round"
OVERSHOOT = "overshoot is not imported: the spot lights its cone only"
AMBIENT = "ambient only is not imported: it lights as any light"
FAR = "far attenuation is not imported"
NEGATIVE = "%s %g is negative: 0 W"
SHAPE = "its %s shape is %s"
WEB_FILE = "its photometric web %s is approximated by a spot of 170 degrees"
IES_FILE = "its IES file %s is approximated by a spot of 170 degrees"
IES_ZERO = "power 0: it gives no light, in V-Ray too: 0 W"
IES_RATED = ("its power is taken as its flux: V-Ray scales the IES file's candelas by the power over the file's "
             "rated lumens, which are not read (the file is not found: beside the scene, in its maps or textures "
             "folder or a texture search folder it would be)")
IES_UNREAD = ("its power is taken as its flux: V-Ray scales the IES file's candelas by the power over the file's "
              "rated lumens, and %s cannot be read (%s)")
IES_DARK = "its IES file %s gives no light: 0 W"
IES_SHAPE = "its %s light shape is a sphere %g m across"
NO_FILE = "(no file)"
SUN_ZENITH = "its strength is the sun's at the zenith: the sky model's dimming toward the horizon is not imported"
SUN_COLOR = "its color is its filter color: the sky model's sun color is not imported"
MISSING = "%s is animated or not stored: %r is used"
DOUBLE_SIDED = "double-sided: Blender's area light shines on one side, with half the power"
TEXMAP = "its texture is not imported: the light has its color"
DIRECTIONAL = "directional %g is not imported: it shines over the whole hemisphere"
GLOSSY = ("affect specular %s, affect reflections %s: Cycles has one switch for both and keeps the light in glossy "
          "rays; EEVEE's specular factor follows affect specular")
NOT_FINITE = "the power is out of range (sizes %g, %g): 0 W"
OUT_OF_RANGE = "the power is out of range: 0 W"
MAX_FLOAT = 3.4028234663852886e38  # the largest float32: what a Blender light's power or radius holds
MAX_POWER = MAX_FLOAT
CONTRIBUTION = "%s contribution %g: Blender's %s factor, which only EEVEE uses"
