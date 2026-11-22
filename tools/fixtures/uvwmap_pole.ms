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
-- FixtureUVWPoleSphereTall: as FixtureUVWPoleSphereNear under a 16 x 16 x 32 gizmo (r = 0.5 at the poles), pushed
-- (6e-5, 0): off the axis (the bound scales with r).
-- FixtureUVWPoleCone: cylindrical with cap on over a cone (radius 8 to 0, its apex welded into one vertex), turned R1:
-- the apex on the side faces, the base center on a cap.
-- FixtureUVWPoleTile: as FixtureUVWPoleCylinder, U tile 2.5 (the seam's turn moves the image unless it is 3ds Max's).
-- FixtureUVWPoleSphereTile: as FixtureUVWPoleSphere (16 x 16 x 16), U tile 2.5 and U flip.
-- FixtureUVWPoleCenter: spherical on a cylinder, the gizmo centered on its top cap center, turned R2.
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
	fn turned_mesh name shape R push pos =
	(
		local n
		case shape of
		(
			#sphere: n = Sphere name:name radius:8 segs:10 mapcoords:true
			#cone: n = Cone name:name radius1:8 radius2:0 height:12 sides:10 heightsegs:1 capsegs:1 mapcoords:true
			default: n = Cylinder name:name radius:8 height:12 sides:10 heightsegs:1 capsegs:1 mapcoords:true
		)
		convertToMesh n
		-- a cone of radius2 0 keeps its top ring and cap: weld them into one apex (the faces between them go)
		if shape == #cone then meshop.weldVertsByThreshold n #{1..n.numverts} 0.01
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
	round_map (turned_mesh "FixtureUVWPoleCylinder" #cylinder R1 [0, 0, 0] [0, 0, 0]) cyl R1 [0, 0, 6] 16 16 12
	round_map (turned_mesh "FixtureUVWPoleSphere" #sphere R2 [0, 0, 0] [40, 0, 0]) sph R2 [0, 0, 0] 18 14 16
	round_map (turned_mesh "FixtureUVWPoleSphereCyl" #sphere R2 [0, 0, 0] [80, 0, 0]) cyl R2 [0, 0, 0] 16 16 16
	round_map (turned_mesh "FixtureUVWPoleNear" #cylinder R1 [3e-5 * 8, 0, 0] [0, 40, 0]) cyl R1 [0, 0, 6] 16 16 12
	round_map (turned_mesh "FixtureUVWPoleOff" #cylinder R1 [3e-4 * 8, 0, 0] [40, 40, 0]) cyl R1 [0, 0, 6] 16 16 12
	round_map (turned_mesh "FixtureUVWPoleDiagonal" #cylinder R1 [8e-5 * 8, 8e-5 * 8, 0] [80, 40, 0]) cyl R1 [0, 0, 6] \
		16 16 12
	round_map (turned_mesh "FixtureUVWPoleSphereNear" #sphere R2 [8e-5 * 8, 8e-5 * 8, 0] [0, 80, 0]) sph R2 [0, 0, 0] \
		16 16 16
	round_map (turned_mesh "FixtureUVWPoleSphereOff" #sphere R2 [3e-4 * 8, 0, 0] [40, 80, 0]) sph R2 [0, 0, 0] 16 16 16

	-- appended after the nodes above, so that their handles stay
	round_map (turned_mesh "FixtureUVWPoleSphereTall" #sphere R2 [6e-5 * 8, 0, 0] [80, 80, 0]) sph R2 [0, 0, 0] \
		16 16 32
	(round_map (turned_mesh "FixtureUVWPoleCone" #cone R1 [0, 0, 0] [0, 120, 0]) cyl R1 [0, 0, 6] 16 16 12).cap = true
	(round_map (turned_mesh "FixtureUVWPoleTile" #cylinder R1 [0, 0, 0] [40, 120, 0]) cyl R1 [0, 0, 6] \
		16 16 12).utile = 2.5
	local m = round_map (turned_mesh "FixtureUVWPoleSphereTile" #sphere R2 [0, 0, 0] [80, 120, 0]) sph R2 [0, 0, 0] \
		16 16 16
	m.utile = 2.5
	m.uflip = true
	round_map (turned_mesh "FixtureUVWPoleCenter" #cylinder R2 [0, 0, 0] [0, 160, 0]) sph R2 [0, 0, 12] 16 16 16

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\uvwmap_pole.max" quiet:true
	"uvwmap_pole: " + (objects.count as string) + " objects: " + ((for o in objects collect o.name) as string)
)
