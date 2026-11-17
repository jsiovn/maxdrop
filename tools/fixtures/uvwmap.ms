-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- UVW Map modifiers, for convert/uvwmap.py (the oracle dumps each node's evaluated map channels, eval_maps):
-- FixtureUVWPlanar: planar, the gizmo as 3ds Max fits it.
-- FixtureUVWGizmo: planar into channel 2, the gizmo rotated, scaled and moved, size 23 x 17 x 13, tile 2 x 3 x 1.5,
-- U flipped.
-- FixtureUVWBox: box mapping under the same rotated gizmo, V flipped.
-- FixtureUVWCyl: a 16-sided cylinder, cylindrical with cap, W flipped and tiled 2.
-- FixtureUVWCylAxisX: cylindrical with cap, aligned to X, on a box.
-- FixtureUVWSphere: an Editable Mesh sphere, spherical, U tiled 2.
-- FixtureUVWAxisY: planar aligned to Y.
-- FixtureUVWRealWorld: planar with Real-World Map Size, V tiled 4.
-- FixtureUVWSharedA, FixtureUVWSharedB: one planar UVW Map added to both selected boxes (two modifier contexts).
-- FixtureUVWExtrude: a Rectangle, an Extrude without mapping coordinates, then box mapping.
-- FixtureUVWTwo: planar into channel 1, then spherical aligned to X into channel 3.
-- FixtureUVWShrink: shrink-wrap (not evaluated by MaxDrop: the stored channel stays).
-- FixtureUVWOff: a planar UVW Map switched off.
-- FixtureUVWAboveBend: cylindrical above a Bend (not evaluated by MaxDrop: the Bend is not).
-- Editable Poly boxes 30 x 20 x 10 (3 x 2 x 2 segments) unless said otherwise; one Standard material on every node.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)

	fn box_at name pos =
	(
		local b = Box name:name length:20 width:30 height:10 lengthsegs:2 widthsegs:3 heightsegs:2 mapcoords:true pos:pos
		convertToPoly b
		b
	)

	-- the modifier fits its gizmo to the object when it is first evaluated: evaluate it before changing anything
	fn uvw_on node =
	(
		local m = Uvwmap()
		addModifier node m
		local s = snapshotAsMesh node
		free s
		m
	)

	fn turn m =
	(
		m.gizmo.transform = (rotateXMatrix 20) * (rotateZMatrix 35) * (transMatrix [4, -3, 2])
	)

	uvw_on (box_at "FixtureUVWPlanar" [0, 0, 0])

	local m = uvw_on (box_at "FixtureUVWGizmo" [60, 0, 0])
	m.length = 17; m.width = 23; m.height = 13
	m.utile = 2; m.vtile = 3; m.wtile = 1.5
	m.uflip = true
	m.mapChannel = 2
	turn m
	m.gizmo.scale = [1.2, 0.8, 1]

	m = uvw_on (box_at "FixtureUVWBox" [120, 0, 0])
	m.maptype = 4
	m.length = 17; m.width = 23; m.height = 13
	m.vflip = true
	turn m

	local cyl = Cylinder name:"FixtureUVWCyl" radius:8 height:16 sides:16 heightsegs:2 capsegs:1 mapcoords:true \
		pos:[0, 60, 0]
	convertToPoly cyl
	m = uvw_on cyl
	m.maptype = 1
	m.cap = true
	m.wflip = true
	m.wtile = 2

	m = uvw_on (box_at "FixtureUVWCylAxisX" [60, 60, 0])
	m.maptype = 1
	m.cap = true
	m.length = 17; m.width = 23; m.height = 13
	turn m
	m.axis = 0

	local sph = Sphere name:"FixtureUVWSphere" radius:8 segs:12 mapcoords:true pos:[120, 60, 0]
	convertToMesh sph
	m = uvw_on sph
	m.maptype = 2
	m.utile = 2

	m = uvw_on (box_at "FixtureUVWAxisY" [0, 120, 0])
	m.axis = 1

	m = uvw_on (box_at "FixtureUVWRealWorld" [60, 120, 0])
	m.realWorldMapSize = true
	m.width = 60; m.length = 7; m.height = 3
	m.vtile = 4

	local a = box_at "FixtureUVWSharedA" [0, 180, 0]
	local b = Box name:"FixtureUVWSharedB" length:10 width:10 height:25 mapcoords:true pos:[45, 190, 0]
	convertToPoly b
	m = Uvwmap()
	-- added to both selected nodes at once, as in the modifier panel: one gizmo around both, a context per node
	max modify mode
	select #(a, b)
	modPanel.addModToSelection m ui:on
	clearSelection()
	(local s = snapshotAsMesh a; free s)
	m.gizmo.transform = (rotateZMatrix 15) * (transMatrix [3, 1, 2])
	m.gizmo.scale = [1.2, 0.8, 1]

	local rect = Rectangle name:"FixtureUVWExtrude" length:30 width:40 cornerRadius:0 pos:[110, 180, 0]
	addModifier rect (Extrude amount:25 mapcoords:false)
	m = uvw_on rect
	m.maptype = 4

	local two = box_at "FixtureUVWTwo" [0, 240, 0]
	uvw_on two
	m = uvw_on two
	m.maptype = 2
	m.axis = 0
	m.mapChannel = 3

	m = uvw_on (box_at "FixtureUVWShrink" [60, 240, 0])
	m.maptype = 3

	m = uvw_on (box_at "FixtureUVWOff" [120, 240, 0])
	m.length = 5; m.width = 5
	m.enabled = false

	local bent = box_at "FixtureUVWAboveBend" [0, 300, 0]
	addModifier bent (Bend angle:30 direction:0 axis:0)
	m = uvw_on bent
	m.maptype = 1

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\uvwmap.max" quiet:true
	"uvwmap: " + (objects.count as string) + " objects: " + ((for o in objects collect o.name) as string)
)
