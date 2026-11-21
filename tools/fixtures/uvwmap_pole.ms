-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Round UVW Maps with vertices on their axis, for the pole rule of convert/uvwmap.py: each mesh is turned by R (after
-- a turn of 7 degrees about its own axis, so that no vertex lies on the seam) and so is its gizmo, so the axis
-- vertices sit on the gizmo's axis up to a float residue. Cap off; Editable Mesh, so the cylinder keeps its cap
-- centers. Pushes are in gizmo radii, along the gizmo's X and Y.
-- FixtureUVWPoleCylinder: cylindrical on a cylinder (the cap centers on the axis), turned R1.
-- FixtureUVWPoleSphere: spherical on a sphere (the poles on the axis), turned R2, the gizmo 18 x 14 x 16.
-- FixtureUVWPoleSphereCyl: cylindrical on a sphere, turned R2.
-- FixtureUVWPoleNear: as FixtureUVWPoleCylinder, the cap centers pushed (3e-5, 0): still on the axis.
-- FixtureUVWPoleOff: as FixtureUVWPoleCylinder, pushed (3e-4, 0): off the axis.
-- FixtureUVWPoleDiagonal: as FixtureUVWPoleCylinder, pushed (8e-5, 8e-5): 1.13e-4 off the axis, off it.
-- FixtureUVWPoleSphereNear: as FixtureUVWPoleSphere (16 x 16 x 16), the poles pushed (8e-5, 8e-5): on the axis
-- (per axis).
-- FixtureUVWPoleSphereOff: as FixtureUVWPoleSphereNear, pushed (3e-4, 0): off the axis.
-- Cylinders of radius 8, height 12 and 10 sides; spheres of radius 8 and 10 segments; one Standard material.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)

	local R1 = (rotateXMatrix 25) * (rotateZMatrix 40)
	local R2 = (rotateYMatrix 33) * (rotateXMatrix -17) * (rotateZMatrix 71)

	-- an Editable Mesh whose vertices are turned 7 degrees about Z, those on the axis pushed by push (in object
	-- units), then all turned by R; built at the origin, then moved to pos
	fn turned_mesh name isSphere R push pos =
	(
		local n
		if isSphere then n = Sphere name:name radius:8 segs:10 mapcoords:true
		else n = Cylinder name:name radius:8 height:12 sides:10 heightsegs:1 capsegs:1 mapcoords:true
		convertToMesh n
		local spin = rotateZMatrix 7
		for i = 1 to n.numverts do
		(
			local p = getVert n i
			local onAxis = ((abs p.x) < 1e-6) and ((abs p.y) < 1e-6)
			p = p * spin
			if onAxis then p += push
			setVert n i (p * R)
		)
		update n
		n.pos = pos
		n
	)

	-- the modifier fits its gizmo to the object when it is first evaluated: evaluate it before changing anything
	fn round_map node kind R center l w h =
	(
		local m = Uvwmap()
		addModifier node m
		local s = snapshotAsMesh node
		free s
		m.maptype = kind
		m.cap = false
		m.length = l; m.width = w; m.height = h
		m.gizmo.transform = (transMatrix center) * R
		m
	)

	local cyl = 1, sph = 2
	round_map (turned_mesh "FixtureUVWPoleCylinder" false R1 [0, 0, 0] [0, 0, 0]) cyl R1 [0, 0, 6] 16 16 12
	round_map (turned_mesh "FixtureUVWPoleSphere" true R2 [0, 0, 0] [40, 0, 0]) sph R2 [0, 0, 0] 18 14 16
	round_map (turned_mesh "FixtureUVWPoleSphereCyl" true R2 [0, 0, 0] [80, 0, 0]) cyl R2 [0, 0, 0] 16 16 16
	round_map (turned_mesh "FixtureUVWPoleNear" false R1 [3e-5 * 8, 0, 0] [0, 40, 0]) cyl R1 [0, 0, 6] 16 16 12
	round_map (turned_mesh "FixtureUVWPoleOff" false R1 [3e-4 * 8, 0, 0] [40, 40, 0]) cyl R1 [0, 0, 6] 16 16 12
	round_map (turned_mesh "FixtureUVWPoleDiagonal" false R1 [8e-5 * 8, 8e-5 * 8, 0] [80, 40, 0]) cyl R1 [0, 0, 6] \
		16 16 12
	round_map (turned_mesh "FixtureUVWPoleSphereNear" true R2 [8e-5 * 8, 8e-5 * 8, 0] [0, 80, 0]) sph R2 [0, 0, 0] \
		16 16 16
	round_map (turned_mesh "FixtureUVWPoleSphereOff" true R2 [3e-4 * 8, 0, 0] [40, 80, 0]) sph R2 [0, 0, 0] 16 16 16

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\uvwmap_pole.max" quiet:true
	"uvwmap_pole: " + (objects.count as string) + " objects: " + ((for o in objects collect o.name) as string)
)
