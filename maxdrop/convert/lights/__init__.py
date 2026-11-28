# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""3ds Max lights as Blender lights: shape, size in meters, linear color and power in watts.

    light_class(scene, i)               # VRAY, STANDARD, PHOTOMETRIC, SUN, IES or SKYLIGHT; None: not one read here
    values, issues = read_params(scene, i, assets, ies_files)   # the light's values, LightError without its block
    not_built(values)                   # why a Skylight or an unknown VRayLight type is not built, else None
    scale = area_scale(values, world)   # what a node's scale does to the area, rounded (part of the key)
    ld, issues = describe(key, name, values, meters, swatches, scale)   # LightDescription, or None and the reason
    is_dome(values)                     # a VRayLight dome: the scene's World, not a light (describe_dome)
    dd, issues = describe_dome(node, name, values, swatches, world)     # DomeDescription
    dt, issues = dome_texture(graph_ir, material_graph, swatches)   # DomeTexture of the dome's converted map, or None
    is_mesh_light(values)               # a VRayLight mesh light: an emissive mesh, not a light (describe_emitter)
    ed, issues = describe_emitter(key, name, values, swatches, area)   # EmitterDescription (area: the mesh's, m^2)
    gone, added = spread(ed, area)      # its radiance over another area (build: the mesh under its modifiers)
    watts(units, multiplier, area(kind, size0, size1, double_sided, meters))
    environment_sky(scene)              # the object index of a VRaySky that is the environment map, else None

A VRayLight's values are {parameter id: value}; every other family's {name: value}, with CLASS naming the family
(light_class).

VRayLight:

A VRayLight keeps one ParamBlock2 in reference slot 0 (docs/FORMAT.md, "VRayLight"): 0 on, 1 type (0 plane, 1 dome,
2 sphere, 3 mesh, 4 disc), 2 / 3 size0 / size1 (a plane's half length along local X and half width along local Y;
a disc's or sphere's radius), 7 color, 8 multiplier, 9 double-sided, 10 invisible, 12 units (0 default, 1 lm,
2 lm/m2/sr, 3 W, 4 W/m2/sr), 18 / 19 texmap (on), 25 / 26 / 30 affect diffuse / specular / reflections, 32 cast
shadows, 36 directional, 38 color temperature, 39 color mode (1: temperature), 53 / 54 diffuse / specular
contribution; a dome's 27 spherical (off: the half above its local XY plane) and 49 texture locked to the dome, a
mesh light's 34 mesh source (a node) and 35 flip normals; a mesh light's own mesh object in reference SLOT_MESH (what
V-Ray's Pick mesh with "Replace mesh with light" keeps, the picked node deleted).

The rules are the ones of the 3ds Max -> FBX exporter (f_export_scene.ms, ocbaby_exsVrayLightWatts and
ocbaby_exsKelvinRGB): the power is the total radiant flux in watts. Radiance units are integrated over the emitting
area (plane 2 size0 x 2 size1, disc pi size0^2, sphere 4 pi size0^2, in m^2; a double-sided plane or disc twice
that), photometric units at 683 lm/W, and one default (image) unit is 1500 / pi cd/m^2. One change, measured
against V-Ray 5.2 renders (docs/FORMAT.md, "VRayLight"): in lm/m2/sr and W/m2/sr a disc emits as if its area were
(2 size0)^2, 4 / pi times its own; in the default units it does not. A node's scale grows the area in V-Ray (in
the default units, lm/m2/sr and W/m2/sr, where the flux follows the area; not in lm and W): a plane or disc by its X
times its Y scale (measured with a scale of 2, 1.5, 1: 3), a sphere by the square of its X scale alone, its radius by
the X scale, and it stays round (measured: (2, 1, 1) and (2, 2, 2) give 4, (1, 2, 1), (1, 1, 2) and (1, 2, 3) give 1;
the visible sphere twice as wide at (2, 1, 1), the same at (1, 3, 1)). Blender's area light grows with the object's
scale but keeps its power, so the power takes that factor; its point light's radius does not follow the object's
scale (measured on 4.2, 4.5 and 5.2, Cycles and EEVEE), so a sphere's radius takes the X scale, in every units mode.
The nodes of one VRayLight share one LightDescription per factor (area_scale). Blender's area light shines
on one side only: a double-sided plane or disc gets half the flux, the side it faces (an issue). Cycles has no
per-light diffuse or specular factor: affect diffuse off hides the light from diffuse rays, affect specular and
affect reflections both off from glossy rays (one switch for both: an issue when only one is off); a contribution
other than 1 sets the light's diffuse or specular factor, which only EEVEE uses (an issue). Cast shadows off ->
shadow False (not stored: on, V-Ray's default). The color is the
scene's swatch rule (convert.colors) of the color, or in temperature mode kelvin_rgb (convert.texmaps) decoded from
sRGB, as CoronaColor's temperature; V-Ray's own temperature color, which it also stores, is not used.

Plane -> AREA RECTANGLE, disc -> AREA DISK, sphere -> POINT with the radius: a V-Ray plane shines along its local
-Z, as a Blender area light does, so the node transform stays. The FBX route's spot mirrors and light de-instancing
are dropped: the nodes of one VRayLight with the same area_scale share one LightDescription. build/ multiplies the
power by the import's Light Strength.

A mesh light is an emissive mesh (describe_emitter; docs/FORMAT.md, "VRayLight"): V-Ray 5.2 emits its mesh object's
mesh (reference SLOT_MESH, else the object of the node 34 names; neither: not built, the reason) in object space at
the light node's object transform, along the faces' normals (35: the other side; double-sided: both), its back black,
with the radiance of the units mode's flux spread over the mesh's object-space area as a Lambertian emitter (flux =
pi L a; the node's scale does not change it): emitter_radiance. That is the evaluated mesh's area: convert.scene
describes the mesh below the modifiers MaxDrop converts, build/ measures it under them and spreads (spread).
Invisible: not seen by the camera and no occluder (a visible one shadows other lights, measured); affect diffuse / specular / reflections as a light's; its texture,
directional spread, contributions and cast shadows off are not imported (issues). convert.scene builds the mesh.

A dome light is the scene's World (describe_dome; docs/FORMAT.md, "VRayLight"): V-Ray 5.2 lights a white floor under
a white dome of multiplier m with m in the default units, m x 0.00213024 in lm and lm/m2/sr, m x 1.43109 in W and
W/m2/sr (a dome has no area: the flux and radiance units agree), and Cycles with S under a World of strength S. So the
dome's radiance in W/m2/sr is m x DOME_RADIANCE[units] and the World's strength that times the Light Strength (1.43:
the default units within 0.05 %). Its color as a light's; a texture replaces the color (measured) and takes the same
strength. Spherical off: only the half above the dome's local XY plane shines (it turns with the node, measured).
Invisible: the camera does not see it; affect diffuse / specular / reflections as a light's; cast shadows off is
not imported (a World has no such switch: an issue). The texture
(dome_texture): a VRayBitmap in spherical mapping (u = 0.5 + phi / 2 pi + its horizontal rotation / 2 pi, phi =
atan2(y, x)) or a Bitmap in spherical environment mapping (u = 0.75 + phi / 2 pi), v up the image, in the world's
frame or, locked to the dome, in the dome node's; another root is not used (the World keeps the color, an issue),
another projection is drawn as spherical (an issue), a CoronaBitmap too (V-Ray 5.2 renders it on a dome as one flat
color, measured: an issue). Its gamma is drawn as a material's image's is (its color space, a Gamma node on a
Linear Rec.709 image: build.world), but a float file (EXR, HDR) in a scene saved with the gamma off keeps its own
decode (linear for automatic; an issue), as the dome's multiplier is: V-Ray 5.2 shows the light display-referred,
which no decode of each texel matches; the display decode V-Ray shows on a material (maxdrop-em3.123) matches a
uniform sky but makes a sun orders of magnitude too bright, its own decode is the nearest (measured,
maxdrop-em3.166; docs/FORMAT.md, Scene gamma). The first
dome that is on is the World; another one, or one that
is off, is an issue (convert.scene).

The other lights (docs/FORMAT.md, "Standard and photometric lights"): V-Ray 5.2 lights a white floor at distance d
from a light of intensity I cd with a pixel of I / d^2 / 1500 (lx / 1500), whatever the light's class, and Blender
(Cycles) with P / (4 pi^2 d^2) from a point or spot light of P watts, P / (pi^2 d^2) on the axis of a small area
light, S / pi from a sun of strength S; the Light Strength 1.43 is pi 683 / 1500. So the power here is the flux in
watts at 683 lm/W: 4 pi I / 683 for a point or spot light of on-axis intensity I, pi I / 683 for a uniform diffuse
(Lambertian) one, and a sun of illuminance E lx gets E / 683 W/m^2.

- Standard (Omni, Free / Target Spot, Free / Target Direct; an old ParamBlock by index and chunks of the light):
  V-Ray lights the floor at distance d with m x 1500 lx (m the multiplier) without decay, m (d0 / d)^2 x 1500 lx with
  inverse-square decay from d0, m d0 / d x 1500 lx with inverse decay: the intensity is 1500 m d0^2 cd, d0 the decay
  start (exact past it with inverse-square decay; at it with inverse decay, an issue), REFERENCE_DISTANCE without
  decay (an issue: Blender's light falls off). Omni -> POINT, Spot -> SPOT (_cone: size the falloff, the blend
  that puts Blender's full-intensity edge on the hotspot; Blender blends in cosine space, (cos theta - cos(size / 2))
  / ((1 - cos(size / 2)) blend)), Direct -> SUN of 1500 m lx (its beam, the falloff's cylinder, is not: an issue,
  but with overshoot). Radius and angle 0: they are point sources with hard shadows. Decay from a start of 0 gives
  0 W (an issue).
- Photometric (Free / Target Light in its six shapes, one class each; ParamBlock2s 0, 2, 3, 4): the intensity is
  always cd, times the dimmer. Isotropic -> POINT, spotlight -> SPOT (block 2's cone), web -> SPOT of WEB_CONE
  (the rules source's wide spot, falloff 170 and hotspot 100 degrees; the web file named in an issue; with the
  file found and read its Profile, the web's X, Y, Z rotation of block 3 as stored, and it shines with it: below),
  uniform diffuse -> AREA (a rectangle or disc as it is; a line a rectangle LINE_WIDTH wide, a point a disc
  LINE_WIDTH across, a sphere or cylinder a disc of its diameter). A point or spot light gets the radius of a disc,
  sphere or cylinder. The color is white, or in Kelvin mode kelvin_rgb decoded from sRGB, times the filter color.
- VRaySun -> SUN of SUN_IRRADIANCE W/m^2 per unit of its multiplier (the rules source's 100 klx / 683; V-Ray 5.2
  measured 102.7 klx at the zenith), angle SUN_ANGLE x its size multiplier, its filter color; the sky model's
  dimming and color are not imported (issues).
- VRayIES: its power in lm (V-Ray's flux with the intensity overridden, in either unit; without the override V-Ray
  scales the IES file's candelas by power over its rated lumens: with the file found (read_params' ies_files, a
  convert.ies.Lookup) the lumens are power x the file's flux / its rated lumens (convert.ies, as V-Ray reads the
  header: flux times the candela multiplier and the ballast factor, rated lumens times the number of lamps; the
  power itself for rated lumens of 0 or below); a file not found or not read, the power, an issue) -> SPOT of
  WEB_CONE, power lm / 683, its color or temperature, the IES file named in an issue; a power of 0 (dark in V-Ray
  too) is 0 W, an issue. The file is looked up whatever the override and the power: found and read, the light has
  its Profile (the file's distribution, convert.ies), else None. With its light shape used and overridden, the
  spot's radius is half the largest size the shape uses (IES_SHAPES: a sphere's diameter exactly, any other shape
  an issue); without the override V-Ray takes the file's shape, which is not read: radius 0.
- A light with a Profile (docs/FORMAT.md, "The IES Texture node in Blender, measured") shines with it: a POINT light
  (a spot cuts the profile at half its size and above its horizon), power s x IES_WATTS over the file's ballast-lamp
  factor, s the factor on the file's candelas: a VRayIES's lumens over the file's flux (V-Ray's measured rule); a
  web's cd over the file's peak (not measured: maxdrop-o53.3.5). Its issue line is WEB_PROFILE or IES_PROFILE in
  place of WEB_FILE or IES_FILE, UPWARD appended when the file sends light upward. A file whose ballast-lamp factor
  is not above 0 gives no Profile.
- Skylight: not built (the reason; its World is later work). environment_sky finds a VRaySky as the environment map
  (RenderEnvironment reference ENVIRONMENT_MAP_SLOT) for convert.scene's report line.

Every light shines along its local -Z, as Blender's spot, area and sun lights do: the node transform stays. Off ->
hidden; affect diffuse / specular and V-Ray's contributions as for the VRayLight; ambient only, far attenuation: issues.
Shadows off (a standard light's chunk 0x2570, a photometric light's castShadows, a VRayIES's cast_shadows, as a
VRayLight's 32; a VRaySun has no switch) -> shadow False; when the switch is not stored, on. A negative multiplier
or intensity is 0 W (an issue).
Their instances share one description (area_scale is 1 but for VRayLights).

The file comes from anywhere: a parameter that is animated, missing or no finite number takes its default (the
animated one an issue; for a standard light a missing one too); a block that cannot be read raises LightError (a
photometric light's, VRaySun's or VRayIES's other blocks are skipped, an issue, their parameters take defaults);
a power past the float32 range (sizes near the float range) is 0 W, an issue; environment_sky skips a
RenderEnvironment whose references cannot be read. No bpy.
"""

import math

from ... import pathnames
from ...reader import chunks, classids, pblock
from ...reader import materials as reader_materials
from .. import colors, params, texmaps
from ..params import finite

from .ids import (
    ChunkError, LightError, SLOT_BLOCK, PLANE, DOME, SPHERE, MESH, DISC, TYPE_NAMES, UNITS_DEFAULT, UNITS_LM,
    UNITS_LM_M2_SR, UNITS_W, UNITS_W_M2_SR, LUMENS_PER_WATT, IMAGE_UNIT, AREA, POINT, SPOT, SUN_LIGHT, RECTANGLE, DISK,
    CLASS, VRAY, STANDARD, PHOTOMETRIC, SUN, IES, SKYLIGHT, OMNI, SPOTLIGHT, DIRECT, SHAPE_POINT, SHAPE_LINE,
    SHAPE_RECTANGLE, SHAPE_DISC, SHAPE_SPHERE, SHAPE_CYLINDER, _FAMILIES, _STANDARD, _PHOTOMETRIC, LUX_PER_UNIT,
    REFERENCE_DISTANCE, SUN_IRRADIANCE, SUN_ANGLE, WEB_FALLOFF, WEB_HOTSPOT, LINE_WIDTH, MIN_CONE, DOME_LM,
    DOME_RADIANCE, ENVIRONMENT_MAP_SLOT, _ON, _DECAY, _CONE, _OVERSHOOT, _NO_DIFFUSE, _NO_SPECULAR, _AMBIENT, _SHADOW,
    DECAY_NONE, DECAY_INVERSE, DECAY_SQUARE, _OLD_COLOR, _OLD_MULTIPLIER, _OLD_HOTSPOT, _OLD_FALLOFF, _OLD_START,
    _OLD_NAMES, _OLD_DEFAULTS, ISOTROPIC, SPOT_DISTRIBUTION, DIFFUSE_DISTRIBUTION, WEB, _PHOTOMETRIC_PARAMS,
    _PHOTOMETRIC_FILE, _SUN_PARAMS, _IES_PARAMS, _IES_FILE, IES_SPHERE, IES_SHAPES, P_ON, P_TYPE, P_SIZE0, P_SIZE1,
    P_COLOR, P_MULTIPLIER, P_DOUBLE_SIDED, P_INVISIBLE, P_UNITS, P_TEXMAP, P_TEXMAP_ON, P_AFFECT_DIFFUSE,
    P_AFFECT_SPECULAR, P_AFFECT_REFLECTIONS, P_DIRECTIONAL, P_TEMPERATURE, P_COLOR_MODE, P_DIFFUSE, P_SPECULAR,
    P_DOME_SPHERICAL, P_MESH_SOURCE, P_DOME_LOCKED, P_SHADOW, P_MESH_FLIP, SLOT_MESH, MESH_OBJECT, DEFAULTS, _NAMES,
    NO_MESH, EMITTER, EMITTER_CLASS, EMITTER_UNREAD, EMITTER_MODIFIERS, EMITTER_TEXMAP, EMITTER_CONTRIBUTION,
    EMITTER_GLOSSY, EMITTER_SHADOW, SPREAD_UNITS, EMITTER_FLAT, NOT_SKYLIGHT, DOME_OFF, SECOND_DOME, DOME_MIRRORED,
    DOME_FLAT, DOME_NO_TEXTURE, DOME_ROOT, DOME_NOT_FOUND, DOME_PROJECTION, DOME_CORONA, DOME_VERTICAL, DOME_AXIAL,
    DOME_SWITCH, DOME_PLACEMENT, DOME_OUTPUT, DOME_GAMMA, DOME_FLOAT_OFF, DOME_CROP, DOME_SHADOW, SKY, NO_DECAY,
    INVERSE, ZERO_START, BEAM, RECTANGLE_CONE, OVERSHOOT, AMBIENT, FAR, NEGATIVE, SHAPE, WEB_FILE, IES_FILE, IES_ZERO,
    IES_RATED, IES_UNREAD, IES_DARK, IES_SHAPE, NO_FILE, SUN_ZENITH, SUN_COLOR, MISSING, DOUBLE_SIDED, TEXMAP,
    DIRECTIONAL, GLOSSY, NOT_FINITE, OUT_OF_RANGE, MAX_FLOAT, MAX_POWER, CONTRIBUTION, _WEB_ROTATION, IES_NODE_CD,
    IES_WATTS, WEB_PROFILE, IES_PROFILE, UPWARD,
)
from .families import (
    LightDescription, light_class, environment_sky, area, area_scale, watts, light_color, is_dome, is_mesh_light,
    not_built, describe, _rays, _nonnegative, _cone, WEB_CONE, WEB_BLEND, point_watts, _describe_standard,
    _describe_photometric, _describe_sun, _describe_ies, _ies_radius, _DESCRIBE, Profile, _profile, _shine,
)
from .reading import _value, read_params, _blocks, _asset, _file_name, _read_blocks, _u16, _read_standard
from .emitters import EmitterDescription, emitter_radiance, _emitter_strength, spread, describe_emitter
from .dome import (
    DomeDescription, DomeTexture, _rotation, describe_dome, VB_H_ROTATION, VB_V_ROTATION, VB_SPHERICAL, VB_H_FLIP,
    VB_V_FLIP, VB_GROUND, VB_AXIAL, _VB_PROJECTIONS, ENV_SPHERICAL, _ENV_PROJECTIONS, dome_texture,
)
