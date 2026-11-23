# Changelog

All notable changes to **MaxDrop** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The version is
`version` in `maxdrop/blender_manifest.toml`; publishing a version requires its section here.

## [Unreleased]

### Added

- Extrude: grid caps (Cap Type Grid) are made as 3ds Max makes them, with the grid of points 3ds Max puts inside
  each cap, so an extruded shape gets 3ds Max's vertex and triangle counts, instead of morph caps and a line in the
  report.
- Objects: a mesh or curve with Cast Shadows off in 3ds Max (Object Properties) casts no shadows in Blender. Receive
  Shadows off, which Blender cannot set per object, is a line in the report.
- Lights: a V-Ray light (plane, disc, sphere) whose own Cast shadows is off in 3ds Max casts no shadow in Blender;
  a dome light with it off is a line in the report (Blender's World has no such switch).
- CoronaMix: the Screen, Overlay, Color Dodge, Color Burn, Linear Burn, Linear Light, Hard Light and Exclusion
  operations are imported as nodes, in gamma 2.2 with "mix in sRGB" on as Corona does it, and Gamma when its top is
  a grey color, instead of the first bitmap below and a line in the report; Soft Light, Vivid Light, Pin Light and
  Hard Mix keep that, the line now naming the operation. An Add in sRGB mode whose sum is negative (negative
  offsets or multipliers) now gives its magnitude raised to 2.2, as Corona does, instead of the negative value.
- Lights: a V-Ray mesh light is imported as an emissive mesh (the mesh it emits, at the light's place) instead of an
  empty: its strength in every units mode as bright as V-Ray 5.2 (measured) times Light Strength, one side or both,
  Flip normals, invisible (not seen by the camera, no shadow), affect diffuse, specular and reflections, on / off.
  Also a mesh light made with "Replace mesh with light", which keeps the mesh itself. A mesh light without a mesh
  stays an empty with a line in the report; the modifiers of its mesh are left out (a line in the report).
- Corona materials: CoronaHairMtl is imported as a surface with the color Blender's Principled Hair BSDF gives its
  melanin, pheomelanin and tint (plus its diffuse color), its glossiness, IOR, opacity and bump, instead of grey; a
  CoronaShadowCatcherMtl makes its object a shadow catcher (Cycles) when the object has no other material. A
  CoronaVolumeMtl, CoronaScannedMtl or CoronaSlicerMtl stays grey, now with a line in the report naming what is
  left out, no longer listed as a material class without a rule.

### Fixed

- Materials: a Standard material whose shader was switched from Blinn after it was created (3ds Max creates every
  Standard material as Blinn) takes each map, its on switch and its amount where 3ds Max keeps them: a bump map whose
  amount was never set afterwards imports at 30 % instead of 100 %, a self-illumination map at 100 % instead of 30 %,
  and a map set before the switch (an Anisotropic bump map, for one) lands in its own input instead of another one.
- Materials: a CoronaPhysicalMtl, a Standard material with the Strauss shader and the grey material of an
  unsupported class reflect their IOR's full Fresnel (Specular IOR Level 0.5, Blender's default) instead of half of
  it (0.25), which made every non-metal CoronaPhysicalMtl reflect too little.
- Materials: a VRayMtl with reflection Fresnel off and a reflection map at full amount (the usual black to white
  Falloff) keeps its diffuse instead of becoming a dark metal colored by the map: the bright reflection swatch the
  map hides no longer makes it a metal; below full amount the swatch counts in proportion.
- Materials: a CoronaMtl (CoronaLegacyMtl) with a Fresnel IOR of 10 or more and a reflection map at full amount
  keeps its diffuse instead of becoming a metal colored by the map: as for VRayMtl, only the share of the reflection
  color the map leaves (times the reflection level) can make it a metal.
- Materials: a grey reflection (a VRayMtl's reflection color, a Standard, Physical or Corona reflection level below
  full) or a reflection map no longer brightens toward the silhouette: the whole Fresnel curve is scaled by it, as
  V-Ray does, through a Mix Shader over a copy of the Principled BSDF without reflection (a grey 128 sphere at IOR
  1.6 was about 50 % too bright near its rim in Cycles; it now matches V-Ray 5.2; the other renderers' materials
  follow the same rule, not checked against them). Such a material shades two Principled BSDFs instead of one: a
  scene of many may render somewhat slower (not measured).
- Materials: the maps of a VRayFastSSS2, VRayCarPaintMtl and VRayCarPaintMtl2 take their slot's multiplier as their
  amount, as VRayMtl's do (a bump at 30 % no longer arrives at full strength), and a VRayFastSSS2's specular amount
  scales its specular.
- Materials: a Double Sided whose facing material is switched off is a line in the report: MaxDrop draws that
  material, as V-Ray 5.2 renders it (measured; V-Ray does the same for a VRayOverrideMtl's base switched off), but
  the 3ds Max scanline renders that side black.
- Maps: a Bitmap that tiles or mirrors in one direction and not in the other, or a placed image that tiles, no
  longer shows a thin dark line at each tile and mirror line (EEVEE and Cycles): what it clips is now cut by a mask
  instead of Blender's Clip extension, which faded the image's border toward black.
- Lights: a VRayIES whose intensity is not overridden is as bright as V-Ray renders it when its IES file is found
  (by the texture lookup's rules): its power is scaled by the file's own flux over its rated lumens, as V-Ray scales
  the file (a relative-photometry file whose rated lumens exceed its luminaire's flux no longer arrives too bright).
  A file not found, or one MaxDrop does not read (photometric type A or B, damaged), keeps the power as the flux,
  a line in the report.
- Extrude: a shape extruded downwards (a negative amount) with only one of its caps on gets that cap facing the way
  3ds Max faces it (into the solid, as for an upward extrusion) and its material ID, instead of turned out.
- Extrude: the sides of an extruded pie Arc shade sharp at its corners (the arc's ends and the center), as in
  3ds Max, instead of round across the arc and both straight sides: the smoothing also breaks at a Bezier knot with
  a handle on its point.
- Modifiers: the rim a Shell builds on an open mesh (a panel, a wall, a box without its top) shades hard against both
  surfaces, as in 3ds Max, instead of smooth into them: the mesh's open edges are marked sharp before the Solidify.
  Where Blender still differs, the report says so: auto smooth splitting the rim's sharper corners (a plane's), or
  the smoothing-group override with auto smooth off.
- Shapes: a Multi/Sub-Object on a shape built as a curve gives each spline the entry for its segments' material ID,
  instead of ID 1's on every spline. A spline whose segments have different IDs takes its first segment's (a curve
  has one material per spline); the report says so when that changes its material.
- UVW Map: on a cylindrical or spherical map with a U tile that is not a whole number (2.5, say), the faces across
  the seam show the part of the image 3ds Max shows, instead of one half an image off; a vertex at a spherical
  map's center gets 3ds Max's coordinates (V 0.5, U of its face), instead of arbitrary ones from a rounding error.
- Animation: an object animated through frame 0 with Bezier, TCB or Smooth Rotation keys, in a file saved with the
  time slider elsewhere, is placed where 3ds Max places it at frame 0: between two keys the value follows their
  tangents (Bezier handles, step keys, tension, continuity, bias and ease), instead of a straight line and a line in
  the report. A Linear Rotation turning more than half a revolution between two keys turns the long way round, as in
  3ds Max. A key with a free handle, and a few rarer cases, still interpolate linearly with a line in the report.
- Materials: a Standard material with the Anisotropic, Multi-Layer, Oren-Nayar-Blinn, Translucent or Strauss shader
  takes each map from its shader's own map slot, instead of Blinn's: a Strauss glossiness map no longer arrives as
  the diffuse map, an Anisotropic self-illumination map as the bump. A Strauss metalness map drives the metallic.
  A map whose amount was left as it was after the shader switch can still get the amount of Blinn's slot (a bump
  map at 100 instead of 30), see docs/SUPPORT.md.
- Materials: a Standard material with the Anisotropic, Multi-Layer, Oren-Nayar-Blinn or Translucent shader takes
  its Diffuse Level into account: a diffuse color at a Diffuse Level of 40 % arrives as dark as 3ds Max renders it,
  instead of at full brightness (a diffuse map is not scaled yet). A missing or animated diffuse, glossiness or specular level takes
  its own shader's default instead of Blinn's.
- Materials: a VRayMtl with reflection Fresnel off reflects its reflection color or map as it is at every angle, as
  V-Ray does, instead of that amount times a Fresnel curve: a 0.2 reflection reflected about 0.011 facing the camera
  instead of 0.2, and the usual black to white Falloff in reflection reached a tenth of its brightness near the
  silhouette. It is drawn as a white metal mixed by the amount over the material without reflection (matches V-Ray
  5.2 in Cycles; EEVEE does not mirror neighbouring objects). A reflection bright enough for the metal rule is
  unchanged.
- Materials: in a scene saved with the gamma on (3ds Max's default), an image map on a glossiness, roughness,
  metallic or opacity input, or as a mask, is decoded by its gamma as 3ds Max and V-Ray read it, instead of taken as
  stored: a 128 grey glossiness map with automatic gamma gives glossiness 0.22 as in V-Ray 5.2, not 0.50, and image
  masks are no longer too bright. Normal and bump maps stay as stored. With the gamma off a mask image is decoded
  like the colors it mixes (a mask between black and white now shows as in 3ds Max).
- Materials: a color map's constant (VRayColor, CoronaColor, a Mix color) on a glossiness, roughness, metallic or
  opacity input, and a Corona material's opacity color, are taken as stored in a scene saved with the gamma off, as
  V-Ray 5.2 renders them (a grey 64 glossiness map is glossiness 0.25, not 0.05).
- Maps: in a scene saved with the gamma off, a VRayBitmap (transfer function Auto, sRGB, None or Inverse gamma) and
  an EXR or HDR image (a Bitmap, a VRayBitmap From 3ds Max or Auto) on a color map or a mask show as V-Ray 5.2
  renders them, their own decode decoded once more for the display-referred scene, instead of brighter (a 128 grey
  VRayBitmap in sRGB: 0.038 linear instead of 0.216, measured). A dome light's texture gamma is now drawn (a Gamma
  node in the World) instead of a line in the report, so a gamma-off dome with an 8-bit VRayBitmap is darker; an
  EXR or HDR dome texture stays linear there (a line in the report: not measured as a light). A CoronaBitmap and a CoronaColor's HDR color stay as before:
  whether Corona shows them as V-Ray does was not measured (no Corona render here).
- Shapes: an open shape that renders in 3ds Max with a round section (a Line, an Arc or an open Editable Spline
  with Enable In Renderer) is capped at both ends, as 3ds Max renders it, instead of a hollow tube with open ends.
- Shapes: a damaged or hostile file whose shape gives curve points past Blender's single precision (an NGon radius
  near the float range, say) imports that shape as an empty with a line in the report, instead of a curve with
  infinite or NaN points; a rectangular section or round thickness that large is left out, a line in the report.
- Import: an AttributeError while reading a file (a defect in MaxDrop's reader) reports the file as not imported,
  with the traceback in the console, as a TypeError or KeyError already did, instead of ending the import.
- Materials: an RGB Tint, Output or Color Correction on a roughness, metallic, opacity or bump input works on the
  color below it instead of on its grey mean (a tint over a colored VRayColor or over an empty VRayColor2Bump),
  and an RGB Tint's colors there are taken as stored, so a tint of (128, 0, 0), (0, 64, 0), (0, 0, 32) on opacity
  gives V-Ray's measured 0.293 in a scene saved with the gamma off, not 0.094. A constant color in a normal map's
  normal slot (an empty Output or RGB Tint, a VRayColor) now tilts the normal as V-Ray renders a white map there,
  instead of a line in the report or a flat normal.
- Lights: a VRayIES whose intensity is not overridden takes its IES file's header as V-Ray 5.2 renders it
  (measured): the ballast factor and the number of lamps now count, type A and B files are read, and the candelas
  are integrated linearly in angle (a coarse file's flux was over a third too high); the report line about a file
  of more lamps is gone.
- Modifiers: a Shell above a Symmetry (a half-modelled object, mirrored, then shelled) now shades its rim hard
  against both surfaces as 3ds Max does, without a seam on the mirror plane, instead of smoothing the rim into
  them.
- Lights: a VRayIES whose IES file is not found because the texture search stopped in a crowded folder says where
  it stopped, and the report lists that stop also when materials are not imported. The IES, dome and material
  lookups now walk the texture folders once per scene, not once each.
- Extrude: a closed spline whose own edges cross, touch or run over each other (a bowtie, a slit drawn over
  itself, a knot moved without its handles, two knots on one spot between straight segments) gets no cap, morph or
  grid, as in 3ds Max, instead of caps 3ds Max does not make; it is no longer taken as a hole in another spline's
  cap (or as its container) and keeps its own direction. One line in the report counts them. A curve segment
  from a knot back to the same spot gets no interpolation steps under Optimize, as in 3ds Max.
- Extrude: a curve segment drawn almost straight (a vector a little off the line between its knots, up to about 2 %
  of its length) gets no interpolation steps under Optimize, as in 3ds Max, instead of its steps; one whose vectors
  run far past its ends on that line gets its steps under Optimize, as in 3ds Max (a rounded Rectangle with very
  short sides: no cap), instead of none.

## [1.0.1] - 2026-11-22

### Added

- Maps: a Falloff's edited mix curve is drawn as a Float Curve on its ratio, as 3ds Max evaluates it (a curve that
  bends a reflection or sheen ramp no longer renders linear), and a Mix's Use Curve as its transition zone (a Map
  Range over the mask, or folded into the mix amount) instead of a line in the report.
- Shapes: an NGon's corner radius and an Ellipse's outline are drawn as 3ds Max draws them, and a shape that renders
  with a rectangular section gets that section (a hidden bevel object beside it) instead of a round one; none of
  them is a line in the report any more, but a rectangular section on a shape that is not flat, which may turn
  otherwise than in 3ds Max.
- Shapes: a shape imported as a curve gets its material (a renderable railing, cable or frame no longer renders with
  Blender's default material); with a Multi/Sub-Object, the entry for material ID 1.
- Extrude: Use Shape IDs is read: each side face gets the material ID of the shape segment it comes from, as in
  3ds Max, so a Multi/Sub-Object puts its sub-materials on the right sides; it is no longer a line in the report.
- Primitives: Slice on a Sphere, Cylinder, Cone, Tube or Torus and the hemisphere of a Sphere (chopped or squashed)
  or a GeoSphere are imported as the mesh 3ds Max builds, cut planes and bases with their material IDs, smoothing
  groups and UVs, instead of a placeholder with a line in the report.
- LookAt Constraint: Keep Initial Offset and Set Orientation are applied, so a constrained object keeps the turn
  it was given in 3ds Max instead of facing its target straight; neither is a line in the report any more.
- Lights: a standard, photometric or VRayIES light whose shadows are off in 3ds Max casts no shadow in Blender;
  a VRayIES with an overridden light shape gets a spot radius from it (soft shadows), a shape other than a sphere
  drawn as a sphere of its largest size, a line in the report.
- Corona: a CoronaLayeredMtl mixes its layers over its base (each by its amount and mask, a Mix Shader per layer)
  instead of giving the base alone. CoronaPhysicalMtl brings its sheen, subsurface scattering and a metal's complex
  IOR, CoronaMtl its subsurface scattering; CoronaSkinMtl is imported (simplified: one subsurface layer), and a
  CoronaRaySwitchMtl or CoronaSelectMtl gives the material the camera sees or the one selected, instead of grey.
  Translucency, volumetric absorption, a metal edge color and CoronaMtl's glossiness with PBR mode off are named in
  the report.
- Lights: a VRayLight dome becomes the scene's World instead of an empty: its color or temperature, or its
  spherical texture (VRayBitmap or Bitmap) turned and locked as V-Ray shows it, its strength as bright as V-Ray 5.2
  times Light Strength, a hemisphere when spherical is off, invisible and the affect switches. The World before is
  kept (with a fake user, so saving keeps it) and the report names both; a second dome, also one in a later file of
  the same import, is a line in the report. A mesh light's report line names the node whose mesh it emits.
- CoronaMix: the Add, Subtract, Divide, Minimum, Maximum and Difference operations are imported as nodes, in gamma
  2.2 when "mix in sRGB" is on as Corona does it, and the layer multipliers and offsets are applied, instead of the
  first bitmap below and a line in the report.

### Changed

- CoronaColor: a temperature takes Corona's own color (measured) instead of an approximate curve that was up to
  0.04 off.
- Materials: an Output or RGB Tint map without a map of its own (or with it switched off) is drawn as 3ds Max and
  V-Ray 5.2 render it, white through its own output levels or tint, and a VRayColor2Bump without a map as the
  color (0.5, 0.5, 1) it renders (flat in a bump slot), instead of being left out with a line in the report.
  Measured in 3ds Max 2020 and V-Ray 5.2; Corona not measured. In a normal map's normal slot such an empty map is
  still left out with a line in the report (V-Ray tilts the normal by that white).
- Import: Esc while a windowed import reads a very large mesh stops the reading inside that mesh, so the next
  import can start at once (one mesh of 5.6 million face corners kept it busy for about a second more).

### Fixed

- Lights: a VRayIES whose intensity is overridden in cd is as bright as V-Ray renders it: its stored power is
  already the flux in lumens, it was taken as candelas (4π times too bright). Without the override, a line in the
  report says the power is taken as the flux (V-Ray scales the IES file by the power over the file's rated lumens,
  which are not read), and power 0 says the light is dark in V-Ray too, not that V-Ray takes the file's own
  intensity. Measured in V-Ray 5.2.
- Lights: a scaled V-Ray sphere light takes its X scale alone, as V-Ray does: its radius grows with it (Blender's
  point light keeps its radius whatever its object's scale), its power in the area units with its square; a
  larger Y or Z scale no longer makes it brighter.
- Colored data maps: a colored map on roughness, metallic or opacity, a Mix or layer mask or a bump height
  gives the mean of its channels, where Blender's own conversion weighed them by luminance (red 0.21, green 0.72,
  blue 0.07), so such a map rendered too rough or too smooth, too opaque or too clear. Measured in V-Ray 5.2 on a
  Mix mask, a glossiness map and an opacity map: pure red, green or blue gives 1/3.
- Images and the scene's gamma: in a scene saved with the gamma on and a file input gamma other than 2.2, a Bitmap
  with automatic gamma (and a VRayBitmap whose transfer function is From 3ds Max) is read with that input gamma, as
  3ds Max reads it (input gamma 1.0: linear, where MaxDrop read it as sRGB). In a scene saved with the gamma off, a
  Bitmap's gamma override does nothing, as in 3ds Max: the image is read as sRGB (an override of 1.0 made it too
  bright). Measured in V-Ray 5.2 renders; the report names an input gamma other than 2.2.
- CoronaColor: a temperature in a scene saved with the gamma off is decoded from sRGB like every other color there
  (and like VRayColor's temperature), as V-Ray renders it: 3000 K showed too pale.
- Maps in a scene saved with the gamma off: a colored constant on a mask (a VRayColor, a CoronaColor, a Mix's or
  Falloff's own color) takes the mean of its swatch before the sRGB curve, as V-Ray renders a mask: a red mask over
  a black-to-white Mix gives 0.09 instead of 0.33, which showed much too bright. Other data inputs (roughness,
  metallic) follow the same rule, not yet checked against V-Ray. Grey constants and scenes with the gamma on are
  unchanged.
- Bitmap, CoronaBitmap, VRayBitmap: Mirror is drawn as 3ds Max draws it, two copies per tile with the second one
  mirrored (a cropped image too), and it wins over Tile: a mirrored map with the default tiling is no longer drawn
  as a plain repeat. Tile, mirror and neither are kept per direction also without a crop (Tile U only no longer
  repeats in V).
- Shapes: an Arc with both Pie Slice and Reverse on starts where 3ds Max starts it (at its From angle, then the
  center), so its first vertex and an Extrude's side UVs on it are 3ds Max's.
- Extrude: the side UVs of a closed spline drawn the other way round (a clockwise outline, a counter-clockwise hole)
  start where 3ds Max starts them, instead of one step along.
- UVW Map: a corner on the axis of a cylindrical or spherical map (the pole of a sphere, the center of a cap) gets
  the U 3ds Max gives it: a turned gizmo no longer gives it an arbitrary angle (a texture smeared at the pole), and
  on a cylindrical map it takes U 0.5 as in 3ds Max instead of the mean of its face.
- Shapes: an Arc whose from and to angles are equal is a point, not a full circle, and angles below 0 or past 360
  are held there as 3ds Max holds them (from 10 to 370 ends at 360 instead of going round to 10).
- Modifiers: an object with a world-space modifier (a Map Scaler or another space-warp binding) on its stack arrives
  as its mesh, with the binding named in the report among the modifiers not applied, instead of as a placeholder of
  an unnamed class.
- Materials: the report names a peeled Double Sided material as 3ds Max does (it said "DoubleSided"), and a
  VRayFastSSS2 whose subsurface color cannot be read (animated, damaged) takes V-Ray's default grey instead of white.
- Modifiers: a Shell whose inner and outer surfaces both lie on one side of the original (inner -1 and outer 2, for
  one) arrives as a Solidify there instead of being left out, and one whose amounts add up to less than zero is
  turned inside out as 3ds Max makes it (both amounts negative used to face the wrong way). The report no longer
  names a Shell's smoothing-group override while auto smooth is on, which ignores it.
- Materials: a material or map with an animated parameter beside maps of its own (a VRayBlendMtl with an animated
  blend color, a VRayNormalMap with an animated multiplier) gets its maps from the right place instead of one
  shifted or lost (the bump map of such a VRayNormalMap was dropped).
- Import: a defect in MaxDrop's reader (a TypeError or KeyError while reading a file) reports that file as not
  imported, with the error in the reason and its traceback in the console for a bug report, instead of ending the
  import with a Python error. The other files of the run are still imported.
- Scene packs on Linux and macOS: a folder another program creates at the name of the unpack's folder in the
  instant before it is put in place is no longer taken over (renamed with a rename that never replaces; Windows
  already refused).
- Transforms: a NaN rotation stored in the file (a TCB, Linear or Bezier rotation, the axis of a scale) or a NaN
  or infinite pivot rotation is reported as a non-finite transform instead of read as no rotation without a word;
  a non-finite pivot position or pivot scale is now reported too. Such a node is placed without its transform (its
  children still placed under it), or for a pivot, without its object offset, as other non-finite transforms are.
- Transforms: an animated object in a file saved with the time slider away from frame 0 stands where 3ds Max shows
  it at frame 0, read from its keys, instead of where it was at the saved frame. Linear Float, TCB Float and Float
  List controllers (under Position XYZ, Euler XYZ or ScaleXYZ) are read instead of left at their default; list
  controllers use their weights (they were taken as 100 % unless animated); the Euler orders other than XYZ are
  applied instead of read as XYZ.

## [1.0.0] - 2026-11-21

### Added

- **Version 1.0**: an import shows its progress and Esc cancels it, large scenes stay within a time and memory
  budget (see `docs/BASELINE.md`), the Falloff, Output and RGB Tint maps, Composite's blend modes and masks and
  Color Correction's rewiring are drawn as nodes, files of 3ds Max 2012 and older are read with their names
  (checked on made-up data), and hostile files are refused by limits instead of running Blender out of memory.
  Checked on two commercial interior scenes on Blender 4.2 and 5.2, as for 0.1.0. What is not imported yet stays
  listed in `docs/SUPPORT.md`.
- Import: started from a window (a drop, or File > Import), an import runs in steps: the status bar shows what it
  does (unpacking with the bytes written, reading, building with the count) and Blender keeps drawing. Esc
  cancels it and removes everything that import made (objects, meshes, materials, images, collections, the report
  text it created; the scene camera and render size are put back), also the scenes of the run it had finished; an
  unpack is stopped and its staging folder removed, a finished pack folder stays. A finished import is one undo step.
  An undo or a file load from another window during the import cancels it the same way.
  Imports from scripts (`bpy.ops.import_scene.maxdrop(filepath=...)`) and without a window stay synchronous.

- Materials: the map wrappers that were simplified to their first bitmap are drawn as nodes, from what 3ds Max
  2020 renders (measured): a Falloff (Perpendicular / Parallel, Fresnel, Towards / Away in the viewing direction)
  as its two sides mixed by Layer Weight, Fresnel or the facing ratio, each side mixed with its color by the map
  amount; a Composite with its blend modes (all but linear burn, soft light, pin light and hard mix) and layer
  masks; Color Correction's rewiring; an Output map's levels; an RGB Tint's channel mix. Other Falloff types and
  directions and the four blend modes left out are simplified as before.

- Import: files of 3ds Max 2012 and older, whose names are 8-bit text in the code page of the computer that saved
  them, are read with their names: in the code page the file records, else as UTF-8, else Western (1252). The new
  option **Text Encoding** picks another code page (Central European, Cyrillic, Greek, Turkish, Japanese,
  Simplified and Traditional Chinese, Korean, UTF-8); Unicode files of 3ds Max 2013 and later ignore it. The File
  line of the popup says which code page Auto reads such a file in. No file of those versions has been imported
  yet: checked on made-up data.
- Tests: files saved by 3ds Max 2020 in the 2017, 2018 and 2019 formats, with accented and Chinese names; docs/
  SUPPORT.md lists which 3ds Max versions are tested, expected to work or not supported.
- Landing page: three short videos (a scene pack chosen in File > Import, the same pack dropped from File Explorer,
  the unpacked .max chosen in File > Import), recorded in Blender 5.2 with the scene's contents blurred, and
  pictures of the options and the report. The page and the README no longer say Blender stops responding during
  an import.
- Landing page in Vietnamese (`vi.html`), with the same pictures and videos; a link in the header switches between
  English and Tiếng Việt.

### Changed

- Import: Esc while a windowed import reads its file stops the reading at the next object (it ran to the end of
  the file, and a new import was refused until then), and a very large mesh is built in several steps, so Blender
  keeps drawing and Esc answers during it.
- Primitives: a primitive is built with array operations instead of one Python step per face corner, the same mesh
  about ten times faster: one with segments in the thousands (up to the cap of 2,097,152 face corners) takes a few
  tenths of a second instead of up to 4 s, and a scene of many such primitives no longer stalls the reading.
- Materials: an inverted Output (of a Bitmap or an Output map) with an RGB offset subtracts the offset, as 3ds Max
  renders it (it was added).
- Report: a scene saved with a view through no camera active (common) names its scene camera, the first camera, in
  the render line instead of raising a warning; a damaged Config stream is named as such, not as "no saved view".
- Materials: an Output, RGB Tint or VRayColor2Bump map without a map of its own (or an Output or RGB Tint with it
  switched off) is named in the report; it is drawn as before (directly in a slot, the material keeps its own color
  or value), but no longer silently.
- Report: a VRaySky as the environment map is named under "environment" instead of "object N" (the number was the
  map's, not an object's).
- Materials: a color map read as linear (an EXR or HDR file under automatic gamma, a VRayBitmap transfer function
  None, a gamma override other than 2.2) is loaded in the Linear Rec.709 color space instead of Non-Color, so its
  colors keep their primaries in a scene whose working space is not Linear Rec.709 (Non-Color where Blender's color
  management config lacks it). Data maps stay Non-Color.
- Import: a scene with more than 1,048,576 objects is refused, and a mesh with more than 67,108,864 vertices (or map
  vertices in one channel) or 134,217,728 face corners is skipped with an issue naming the counts, instead of
  running Blender out of memory. A file whose reading runs out of memory or recursion depth ends in "Not imported"
  with a reason, like any other damaged file.
- Scene packs: `.7z` and `.rar` need 7-Zip 26.02 or newer (was 25.01) or bsdtar 3.8.8 or newer (was 3.7.4), the
  first versions with the vendors' fixes of overflows in their RAR and 7-Zip readers; UnRAR stays at 7.23. On
  Windows this applies to its own `tar.exe` too: an older one is not used (install WinRAR or 7-Zip instead).

### Fixed

- Scene pack popup: when every name the pack folder could take is already someone else's folder, the popup says so
  (what the import would stop with) instead of "Unpacks into a folder named after the archive"; a pack replaced at
  the same path while the popup is open no longer shows the folder of the old one. "No free folder" and "Cannot
  write into" put the folder on a line of its own, so a long path no longer cuts off the end of the message.
- Primitives: a standard primitive whose Real-World Map Size data is damaged is built with that option off instead
  of as a placeholder.
- Scene packs: Blender closing at the moment an unpack creates its folder (or the folder of a pack with several
  scenes) no longer leaves an empty folder behind that makes the next unpack use `<name> (2)`.
- Scene packs: the hidden folders left by rare crashes or by several unpacks of one pack at once are cleaned up by
  a later unpack of that pack (a half-filled `.maxdrop-reclaim-*` folder once stale; a leftover beside the folder
  of a pack with several scenes by every unpack of that pack that writes), and a folder holding a scene is kept
  instead of removed; a folder name freed from a stale unpack is taken again when its folder cannot be renamed
  into place.

## [0.1.0] - 2026-11-19

### Added

- **First open of a whole scene**: a dropped V-Ray interior scene now opens through its own camera, lit by its own
  lights, at its real size. Checked on two commercial interior scenes on Blender 4.2 and 5.2 (see
  `docs/BASELINE.md`).
- Target cameras, target lights and other objects aimed by a Look At controller or a LookAt Constraint point where
  they point in 3ds Max (they kept the rotation of no controller before); their targets arrive as empties, not
  placeholders. The new import option **Keep Targets** aims the ones with a Look At controller at their targets
  with a Track To constraint, so they follow when a target moves (a roll or the Y axis keeps the fixed rotation).
- V-Ray lights: plane and disc lights arrive as area lights, sphere lights as point lights, with their size, color
  or color temperature, on / off, invisibility and diffuse / specular / reflection switches, and a power in watts
  from their units. The new import option **Light Strength** (default 1.43, calibrated so that Cycles matches V-Ray's
  brightness) scales every light. A scaled light is as bright as in V-Ray. Instances share one light. Mesh and dome lights are not imported yet (a line in
  the report).
- Standard lights (Omni, Spot, Direct), photometric lights (every shape and distribution), VRaySun and VRayIES
  arrive as Blender point, spot, area and sun lights, as bright as V-Ray 5.2 renders them (measured), with their
  cones, colors, Kelvin temperatures, on / off and diffuse / specular switches. What Blender cannot hold is a line
  in the report: decay other than inverse square, a Direct's beam, IES and web distributions (a wide spot, the file
  named), the sky model's sun color. A Skylight and a VRaySky environment are not imported yet (a line each).
- Cameras: Free, Target, Physical and VRayPhysicalCamera arrive as Blender cameras with 3ds Max's framing: the
  horizontal field of view whatever the render aspect (zoom, lens breathing and a specified FOV included, as 3ds Max
  and V-Ray render them), lens shift, clipping and orthographic width. For a file with a camera, the camera of the view 3ds
  Max renders (the locked render view, else the active viewport), else the first, becomes the scene camera and the
  file's render size Blender's; a file without a camera leaves the scene's render settings alone. Depth of field, distortion, tilt correction and V-Ray's exposure are lines in the report.

### Changed

- Scene packs: the import popup names the exact folder a pack unpacks into (`<archive> (2)` when that name is
  taken, `<archive>/<scene>` for a pack with several scenes), and names it again when the Scene field picks
  another scene.
- Scene packs: a password-protected pack gives one message, naming the archive, whether it is a `.zip`, a `.rar`
  with a password on its data or one with encrypted names; entry names in messages and the Scene field are shown
  with `/` on every backend, and no message says "drop the .max" any more.
- Materials: importing a scene again, or a scene that shares texture files with one already imported, uses the
  images already in the `.blend` for the same file and color space instead of loading copies (`name.001`); an
  image that was painted on, packed, linked from a library or given another alpha mode is left alone and the file
  loaded anew.

### Fixed

- Materials: a Bitmap or CoronaBitmap with automatic gamma reads an EXR or HDR file as linear, as 3ds Max and
  Corona do, instead of as sRGB (too dark); a VRayBitmap already did.
- A damaged `.max` whose objects reference objects that do not exist no longer risks crashing Blender 4.2 and 4.5
  (Python 3.11) after the import is refused.
- Scene packs: a hidden `.maxdrop-staging-*` folder left by an unpack that never finished (Blender closed or crashed
  mid-way) is removed by the next unpack into that folder once it is hours old; two imports of the same pack at
  once no longer make the second fail or replace a folder made in between: it takes the next free folder name (or
  reuses the first one's folder); a `.zip` listing more entries than MaxDrop reads is refused before its directory
  is loaded into memory; a Windows junction is no longer searched or written into, like a link.
- Texture lookup: a folder with millions of files no longer slows an import down. Each search place reads at most
  200,000 files and folders, the listing of the `.max` file's folder and its parent for `maps` / `textures`
  folders included, instead of reading every entry of a huge folder before stopping; the report names the folder
  where a search stopped.
- Import report: the status line names material problems on their own ("2 material problems, 1 issue") and the text
  MaxDrop Report states their total; a texture file that was found but did not load is listed under the material
  issues instead of the other issues.
- Import report: a Falloff, VRayDirt, Output, RGB Tint or VRayColor2Bump over a map that converts to nothing is no
  longer listed as a simplified map (it draws nothing; its lost map is reported), and no longer marks a Mix that
  hides it as approximated.
- Import report: the Unpacker line of a `.rar` or `.7z` scene pack names the program that wrote the files when the
  first one failed and another took over, not the one that only listed the pack.
- Materials: a cropped or placed Bitmap with tiling off no longer repeats over the whole surface, and its mirror
  setting now applies, per direction; a map on map channel 0 (vertex colors) is drawn on UV channel 1 and named in
  the import report instead of sampling a UV map that does not exist; a texture file that holds no image is named
  in the report instead of rendering magenta; a material whose conversion or build fails no longer stops the whole
  scene from importing: the scene comes in without it and the report says so.

## [0.0.5] - 2026-11-18

### Added

- **Shapes as curves**: Line, Editable Spline, Rectangle, Circle, Ellipse, Arc and NGon arrive as Blender curve
  objects with their splines, knots and handles as 3ds Max draws them, straight segments straight, open or closed,
  at their place in the hierarchy. A shape set to render in 3ds Max gets its thickness as a round bevel. The import
  report counts the curves.
- **Extrude**: a shape with an Extrude arrives as the mesh 3ds Max makes of it: walls, floors and ceilings drawn as
  outlines are closed, with caps (holes where one outline lies inside another), outward normals, material IDs,
  sharp corners and mapping coordinates. The import report counts it as applied.
- **UVW Map**: planar, box, cylindrical (with cap) and spherical UVW Map modifiers give the mesh the mapping the
  artist set, in their map channel, with the gizmo's place, turn and size, tiling, flips, alignment and Real-World
  Map Size, also on an extruded shape and with several UVW Maps on one stack. Faces across the seam of a round map
  do not smear. Shrink-wrap, face and XYZ-to-UVW keep the stored coordinates, as does a UVW Map above a modifier
  MaxDrop does not apply (each a line in the report).
- **TurboSmooth, MeshSmooth, Shell and Symmetry as Blender modifiers**: they arrive as Subdivision Surface, Solidify
  and Mirror in 3ds Max's order, with their iterations, Smooth Result and smoothing-group creases, inner and outer
  amounts, axis, flip, slice, weld threshold and a moved or turned mirror gizmo (an empty), so the evaluated mesh
  matches 3ds Max's. New import option **Modifiers: Keep as Blender Modifiers / Ignore**. One above a modifier
  MaxDrop does not evaluate stays off (a line in the report); the report counts the converted ones.
- **Primitives**: Box, Plane, Pyramid, Sphere, GeoSphere, Cylinder, Cone, Tube and Torus arrive as the meshes 3ds
  Max builds from their parameters (segments, smoothing, material IDs, mapping coordinates, Real-World Map Size,
  negative sizes) instead of empties, and take UVW Maps and the modifiers kept as Blender modifiers like any mesh.
  Slice and hemispheres are not built yet: such a primitive stays an empty, with a line in the report.

### Changed

- **Import report, modifiers**: the line of modifiers not applied says what that means, "ignored: the object
  arrives as its base object, or as its Extrude makes it", and the report lists the modifiers applied (Extrude,
  UVW Map) apart from those converted to a Blender modifier.

### Fixed

- **Multi/Sub-Object material IDs past the list**: a face whose material ID has no entry gets the sub-material
  3ds Max renders it with instead of no material: the list repeats every *highest ID* IDs (with IDs 3 and 7,
  face ID 10 takes 3 and 14 takes 7), in nested Multi/Sub-Objects too.

## [0.0.4] - 2026-11-17

### Added

- **Materials by MaxDrop's own rules**: VRayMtl, VRayLightMtl, VRayFastSSS2, the V-Ray car paints, Standard (every
  shader) and Physical Material become a Principled BSDF with their colors converted to Blender's linear colors,
  roughness, metalness, IOR, transmission, emission with its strength, coat, subsurface, bump and normal maps.
  Every IOR is kept between 1 and 100, the coat IOR of VRayCarPaintMtl too (a full coat_strength gives 100).
  Wrappers (VRay2SidedMtl, VRayBlendMtl, VRayOverrideMtl, VRayMtlWrapper, Double Sided, Shellac, Shell Material)
  give their sub-material; Multi/Sub-Object gives one slot per material ID. Each 3ds Max material is one Blender
  material, also when instances carry different materials.
- **Texture maps as nodes**: a Bitmap keeps its tiling, offset, rotation, tile and mirror, cropping and map
  channel; Mix, RGB Multiply, Color Correction and Composite become nodes; Falloff, VRayDirt and other wrappers
  give the map below them. Color maps load as sRGB, data maps as Non-Color. A map MaxDrop cannot convert is named
  in the report and never replaced by the color its wrapper holds for that slot: below a Color Correction the
  material keeps its own color (not the Color Correction's black); a Mix, RGB Multiply or CoronaMix uses its other
  map, or the material keeps its own color.
- **Corona materials by MaxDrop's own rules**: CoronaPhysicalMtl, CoronaMtl (CoronaLegacyMtl) and CoronaLightMtl
  become a Principled BSDF (roughness or glossiness mode, metalness, refraction, opacity, self-illumination,
  clearcoat, bump); CoronaLayeredMtl gives its base material. CoronaBitmap is imported like a Bitmap, CoronaColor as a
  color, CoronaMix (mix and multiply) as nodes, CoronaNormal as a Normal Map node.
- **VRayBitmap (VRayHDRI) as an image texture**, like a Bitmap: its coordinates, cropping, transfer function (None,
  Inverse gamma, sRGB, Auto) and multipliers; a Composite, Color Correction or Mix above it keeps its image.
- **Color swatches follow the scene's gamma**: a scene saved with 3ds Max's gamma on (2.2, the default) takes
  every swatch as linear, as V-Ray renders it, instead of decoding it from sRGB, which made flat colors one display
  gamma too dark (a 128 grey swatch 0.216 instead of 0.502); a scene saved with the gamma off keeps the sRGB decode.
  This covers material colors and the colors of Mix, Falloff, Color Correction, VRayDirt, RGB Multiply, CoronaMix,
  VRayColor and CoronaColor's color and hex value. The import report names the rule; a file without the setting is
  taken as gamma on.
- **VRayColor as a color**: RGB or temperature, times its RGB multiplier, with its color gamma; a Falloff, Color
  Correction or Mix mask above it now gives its color instead of a wrong one.
- In a scene saved in the 3ds Max 2012 format, a map whose stored reference is stale (a Falloff's map, a Normal
  Bump's normal map) now gets the map 3ds Max shows.
- **The import report covers the materials**: materials built and converted by class, wrappers and maps that
  were simplified, material and map classes without a rule, textures found per lookup step and the ones not found
  by file name (for a scene pack: whether the archive held the file), the material inputs this Blender version
  lacks (Thin Wall on 4.2 and 4.5) and what a rule could not convert. The status bar line counts the materials and
  warns when anything was simplified or left out. The bug report form asks for the report.

### Removed

- io_scene_max's engine (`import_max.py`), which still made the materials: Arnold Standard Surface, Raytrace and
  Architectural materials now arrive as a grey material with their name until MaxDrop converts them.

### Changed

- **Faster, with far less memory**: the file is read once, by MaxDrop's reader. Two large interior scenes that
  needed 3.7 GB and 14.4 GB of memory in 0.0.3 now need about 1.3 and 1.4 GB, and import up to four times faster (see
  `docs/BASELINE.md`).
- **Textures are found in more places**: the scene's folder, then `maps` or `textures` folders beside the scene,
  then the **Texture Search Folders** of the preferences (now searched, with their subfolders), and last the path
  stored in the scene, only when it is on a local drive. Network and device paths stored in a scene are never
  opened. Texture paths are read from the scene's asset list, where 3ds Max keeps them.
- **Scene packs unpack only the maps the scene uses**: of a pack's image and `.ies` files, only those the chosen
  scene's asset list names are written (every one when that list cannot be read); the import report counts the
  files left out. A map the scene does not use no longer stops the unpack for being encrypted or unreadable.

## [0.0.3] - 2026-11-15

### Added

- **Units** in the import options: **Auto** (default) takes the unit the scene was saved with, so a scene in
  millimeters, centimeters, inches or feet arrives at its real size in meters; Millimeters, Centimeters, Meters,
  Inches and Feet override it. A file that does not state its unit is imported at one meter per unit, with a
  warning.
- A **File** line in the options popup of a dropped `.max` (or of a scene pack already unpacked): the 3ds Max
  version, the renderer, the number of objects and the unit.
- Smoothing groups (sharp edges, flat faces), instances as shared meshes, every UV channel, the whole parent chain
  matched by the file's object references, layers as nested collections, and the hidden, frozen and renderable
  flags of objects and layers.
- An **import report** after every import: the unit, the objects and meshes built, layers, hidden and frozen
  objects, groups, and what was not converted (placeholders by class, modifiers not applied, unknown controllers,
  geometry errors), plus the unpack of a scene pack. It is printed to the system console and kept in the text
  **MaxDrop Report** (Text Editor); importing several files at once keeps all their reports there. The status
  line says whether anything was left out.
- A shear inside an object's transform (a scale along a rotated axis) is kept: Blender's world matrix is the one
  3ds Max computes. The rest of the transform goes into the object's parent inverse; an object without a parent
  that needs it gets the empty **MaxDrop Shear** (at the origin, custom property `maxdrop_helper`) as its parent.

### Changed

- Nodes, meshes and transforms are read by MaxDrop's own reader instead of io_scene_max's engine; only the
  materials still come from that engine. An object it cannot convert arrives as an empty with its 3ds Max class in
  the custom property `maxdrop_class`.
- **Scale** is now an extra factor on top of **Units**: a preset or script that set it to `0.001` for a
  millimeter scene now shrinks the scene a thousand times more; set it back to `1`.
- Every import makes a collection named after the file in the active collection, with one collection per layer.
- A damaged or hostile `.max` reports "Not imported" and the other files of the run still import; an import that
  fails while building removes the objects, collections and meshes it made.
- Box, Sphere, Cylinder, Cone, Torus and Plane primitives, Boolean objects and Bipeds arrive as empties until a
  later version converts them (0.0.2 rebuilt the primitives as Blender primitives).
- Each mesh gets the material of its first object: instances share one mesh, so they share its material.
- A large scene imports in about two thirds of the time 0.0.2 took ([docs/BASELINE.md](docs/BASELINE.md)); peak
  memory drops only a little while the materials are read by the old engine.

### Removed

- The **Apply Matrix** option (`use_apply_matrix`): node transforms are always applied.
- The **Collection** option (`use_collection`): a collection named after the file is always made.
- The **Primitive**, **Empty** and **Armature** items of **Object Filter**, which keeps **Material** and **UV Maps**.
  A preset or script that names a removed option or item fails with an error until it is edited.

## [0.0.2] - 2026-11-15

### Added

- **Scene packs**: *File › Import › MaxDrop* also takes the `.zip`, `.rar` or `.7z` a scene was downloaded as, and
  a `.rar` or `.7z` can be dropped onto the 3D Viewport (a dropped `.zip` goes to Blender's extension installer).
  The chosen `.max` is unpacked with the pack's image and `.ies` files into a folder named after the archive and
  imported from there; nothing else in the pack is written or run. A pack with several scenes asks which one in
  the options popup (**Scene**). An unpacked pack is used again, and so is a folder you extracted yourself.
- `.rar` and `.7z` are unpacked by a program already installed (UnRAR, 7-Zip or bsdtar), from fixed paths and,
  except for a bsdtar of macOS or Linux itself, only in versions without known extraction problems. MaxDrop bundles
  none.
- **Unpack Scene Packs Into** in the add-on preferences: next to the archive (default) or a folder of your choice,
  which is also used when the archive's folder cannot be written.

### Changed

- The file handler is labelled `MaxDrop (.max, .rar, .7z)` and the menu entry `MaxDrop (.max, .zip, .rar, .7z)`;
  their ids are unchanged.
- The extension's file permission says that scene archives are unpacked.
- Several `.max` files chosen at once are imported one after the other, each on its own: an object can no longer
  be parented to an object of the same name from another file.

## [0.0.1] - 2026-11-14

First release: a fork of [io_scene_max](https://github.com/nrgsille76/io_scene_max) 1.9.2 by Sebastian Schrand,
made installable next to the original. It imports what io_scene_max 1.9.2 imports, nothing more yet;
[docs/SUPPORT.md](docs/SUPPORT.md) lists it. Free software under the GNU General Public License, either version 3
of the License, or (at your option) any later version (GPL-3.0-or-later); the license text is in the extension
zip.

### Added

- **Import of 3ds Max `.max` scenes without 3ds Max**: drop a file onto the 3D Viewport, or *File › Import ›
  MaxDrop (.max)*. Editable Mesh and Editable Poly objects with UVs and material IDs, six primitives, transforms
  and parenting, and materials (Standard, Physical, Multi/Sub-Object, V-Ray, Corona, Arnold Standard Surface) as
  a Principled BSDF with one image per channel.
- **Check for Updates** in the add-on preferences: compares with the published repository and lets Blender
  install the newer version.
- **Texture search folders** in the add-on preferences. The list is stored from this version on; the importer
  starts using it in a later one.

### Changed (from io_scene_max 1.9.2)

- The extension id is `maxdrop`, the operator `import_scene.maxdrop` and the file handler `MaxDrop (.max)`, so
  both importers can be enabled together.
- The file handler no longer names an export operator that never existed.
