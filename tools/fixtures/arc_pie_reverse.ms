-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Arcs with pie and reverse both on, for the knot order of reader/shapes.py and the Extrude built on it
-- (convert/extrude.py: the side U starts at the first knot, the caps wind from it):
-- FixturePieRev: an Arc of radius 12 from 20 to 130 degrees, pie and reverse.
-- FixturePieRevWrap: an Arc of radius 10 from 300 to 60 degrees (across 0), pie and reverse.
-- FixturePieRevExt, FixturePieRevWrapExt: the same two under an Extrude of 10 in 2 segments, with mapping
-- coordinates and material IDs.
-- FixturePieExt: FixturePieRevExt without reverse; FixtureArcRevExt: without pie (an open arc).
-- One Standard material on every node.
-- It also writes C:\maxdrop_fixtures\arc_pie_reverse.maps.jsonl: per extruded node, its evaluated mesh in object
-- space, per triangle in face order the positions of its three vertices, channel 1's three map vertices, its
-- material ID and smoothing groups. tests/unit/test_extrude.py compares MaxDrop's meshes with it.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)

	fn num x = (local s = formattedPrint (x as float) format:".7g"; if s == "-0" then "0" else s)
	fn p3 p = "[" + num p.x + "," + num p.y + "," + num p.z + "]"
	fn dumpMesh o =
	(
		local ss = stringStream ""
		local m = snapshotAsMesh o
		local back = inverse o.objectTransform  -- world -> object space
		format "{\"name\":\"%\",\"faces\":[" o.name to:ss
		for f = 1 to m.numfaces do
		(
			if f > 1 do format "," to:ss
			local v = getFace m f
			local t = meshop.getMapFace m 1 f
			format "{\"p\":[%,%,%],\"uv\":[%,%,%],\"mat\":%,\"sg\":%}" \
				(p3 ((getVert m v.x) * back)) (p3 ((getVert m v.y) * back)) (p3 ((getVert m v.z) * back)) \
				(p3 (meshop.getMapVert m 1 t.x)) (p3 (meshop.getMapVert m 1 t.y)) (p3 (meshop.getMapVert m 1 t.z)) \
				(getFaceMatID m f) (getFaceSmoothGroup m f) to:ss
		)
		format "]}" to:ss
		delete m
		ss as string
	)
	fn extruded o = (addModifier o (Extrude amount:10 segs:2 mapcoords:true matIDs:true); o)

	Arc name:"FixturePieRev" radius:12 from:20 to:130 pie:true reverse:true pos:[0, 0, 0]
	Arc name:"FixturePieRevWrap" radius:10 from:300 to:60 pie:true reverse:true pos:[40, 0, 0]
	local ext = #(
		extruded (Arc name:"FixturePieRevExt" radius:12 from:20 to:130 pie:true reverse:true pos:[0, 40, 0]),
		extruded (Arc name:"FixturePieRevWrapExt" radius:10 from:300 to:60 pie:true reverse:true pos:[40, 40, 0]),
		extruded (Arc name:"FixturePieExt" radius:12 from:20 to:130 pie:true pos:[80, 40, 0]),
		extruded (Arc name:"FixtureArcRevExt" radius:12 from:20 to:130 reverse:true pos:[120, 40, 0]))

	local cw = line name:"FixtureClockwiseExt"
	addNewSpline cw
	addKnot cw 1 #corner #line [0, 0, 0]
	addKnot cw 1 #corner #line [0, 20, 0]
	addKnot cw 1 #corner #line [25, 20, 0]
	addKnot cw 1 #corner #line [25, 0, 0]
	close cw 1
	updateShape cw
	cw.pos = [0, 80, 0]
	append ext (extruded cw)

	local hole = Rectangle name:"FixtureHoleExt" length:30 width:30 cornerRadius:0
	convertToSplineShape hole
	local c = Circle radius:6 pos:[3, 2, 0]
	convertToSplineShape c
	addAndWeld hole c -1
	updateShape hole
	hole.pos = [40, 80, 0]
	append ext (extruded hole)

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\arc_pie_reverse.max" quiet:true
	local f = createFile @"C:\maxdrop_fixtures\arc_pie_reverse.maps.jsonl"
	for o in ext do format "%\n" (dumpMesh o) to:f
	close f
	"arc_pie_reverse: " + (objects.count as string) + " objects: " + ((for o in objects collect o.name) as string)
)
