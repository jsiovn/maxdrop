-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- UVW Maps on faces at every angle, for the rules that pick a face's side from its normal (convert/uvwmap.py): box
-- mapping and the cap of a cylindrical map, under gizmos turned, scaled unevenly and mirrored, sizes all different.
-- FixtureUVWObliqueBox: box mapping on a sphere, the gizmo turned and scaled 1.3 x 0.7 x 1.1.
-- FixtureUVWObliqueMirror: box mapping on a sphere, the gizmo mirrored (scale -1.2 x 0.9 x 1).
-- FixtureUVWObliqueCap: cylindrical with cap on a 10-sided cylinder, the gizmo tilted and scaled 1 x 0.6 x 1.4.
-- FixtureUVWObliqueBoxX: box mapping aligned to X on a sphere, the gizmo turned.
-- FixtureUVWObliquePlanarX: planar aligned to X on a sphere, the gizmo turned.
-- Editable Poly spheres of 10 segments and radius 8; one Standard material on every node.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)

	fn sphere_at name pos =
	(
		local s = Sphere name:name radius:8 segs:10 mapcoords:true pos:pos
		convertToPoly s
		s
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

	local m = uvw_on (sphere_at "FixtureUVWObliqueBox" [0, 0, 0])
	m.maptype = 4
	m.length = 9; m.width = 21; m.height = 14
	m.gizmo.transform = (rotateXMatrix 25) * (rotateZMatrix 40) * (transMatrix [1, -2, 1.5])
	m.gizmo.scale = [1.3, 0.7, 1.1]

	m = uvw_on (sphere_at "FixtureUVWObliqueMirror" [40, 0, 0])
	m.maptype = 4
	m.length = 13; m.width = 17; m.height = 11
	m.gizmo.transform = (rotateZMatrix 20) * (transMatrix [0.5, 1, -1])
	m.gizmo.scale = [-1.2, 0.9, 1]

	local cyl = Cylinder name:"FixtureUVWObliqueCap" radius:8 height:12 sides:10 heightsegs:1 capsegs:1 \
		mapcoords:true pos:[80, 0, 0]
	convertToPoly cyl
	m = uvw_on cyl
	m.maptype = 1
	m.cap = true
	m.length = 12; m.width = 20; m.height = 9
	m.gizmo.transform = (rotateYMatrix 30) * (rotateZMatrix 15) * (transMatrix [0, 0, 6])
	m.gizmo.scale = [1, 0.6, 1.4]

	m = uvw_on (sphere_at "FixtureUVWObliqueBoxX" [0, 40, 0])
	m.maptype = 4
	m.length = 15; m.width = 19; m.height = 12
	m.gizmo.transform = (rotateYMatrix 35) * (rotateZMatrix -25)
	m.axis = 0

	m = uvw_on (sphere_at "FixtureUVWObliquePlanarX" [40, 40, 0])
	m.length = 15; m.width = 19; m.height = 12
	m.gizmo.transform = (rotateYMatrix 35) * (rotateZMatrix -25)
	m.axis = 0

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\uvwmap_oblique.max" quiet:true
	"uvwmap_oblique: " + (objects.count as string) + " objects: " + ((for o in objects collect o.name) as string)
)
