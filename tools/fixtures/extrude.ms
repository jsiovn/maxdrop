-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Extruded shapes, for the Extrude modifier (convert/extrude.py):
-- FixtureExtRect: a Rectangle 30 x 20, extruded 10 in 2 segments, with mapping coordinates.
-- FixtureExtL: an L-shaped closed Line of corner knots, extruded -15 (downwards), its pivot moved (an object
-- offset), the node turned 30 degrees about Z.
-- FixtureExtHole: a Rectangle and a Circle in one Editable Spline: a cap with a round hole.
-- FixtureExtIsland: three nested squares in one Editable Spline: a solid, a hole, an island in the hole.
-- FixtureExtOpen: an open Line (corner, smooth, corner): sides only, no cap.
-- FixtureExtMirror: an extruded Rectangle on a node scaled -1 in X (a mirrored transform).
-- FixtureExtAdaptive: an adaptive Circle with real-world mapping coordinates and no material IDs.
-- FixtureExtOff: an extruded Rectangle whose Extrude is switched off (a curve, as 3ds Max shows it).
-- One Standard material on every node.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)

	local rect = Rectangle name:"FixtureExtRect" length:20 width:30 cornerRadius:0 pos:[0,0,0]
	addModifier rect (Extrude amount:10 segs:2 mapcoords:true)

	local ln = line name:"FixtureExtL"
	addNewSpline ln
	addKnot ln 1 #corner #line [0,0,0]
	addKnot ln 1 #corner #line [20,0,0]
	addKnot ln 1 #corner #line [20,8,0]
	addKnot ln 1 #corner #line [8,8,0]
	addKnot ln 1 #corner #line [8,25,0]
	addKnot ln 1 #corner #line [0,25,0]
	close ln 1
	updateShape ln
	addModifier ln (Extrude amount:-15 segs:1)
	ln.pivot = [5,5,0]
	rotate ln (eulerAngles 0 0 30)
	ln.pos = [60,0,0]

	local hole = Rectangle name:"FixtureExtHole" length:40 width:40 cornerRadius:0
	convertToSplineShape hole
	local c = Circle radius:8 steps:6 pos:[4,2,0]
	convertToSplineShape c
	addAndWeld hole c -1
	updateShape hole
	addModifier hole (Extrude amount:5)
	hole.pos = [0,60,0]

	local island = Rectangle name:"FixtureExtIsland" length:40 width:40 cornerRadius:0
	convertToSplineShape island
	local mid = Rectangle length:24 width:24 cornerRadius:0
	convertToSplineShape mid
	addAndWeld island mid -1
	local core = Rectangle length:10 width:10 cornerRadius:0
	convertToSplineShape core
	addAndWeld island core -1
	updateShape island
	addModifier island (Extrude amount:6)
	island.pos = [60,60,0]

	local op = line name:"FixtureExtOpen"
	addNewSpline op
	addKnot op 1 #corner #curve [0,0,0]
	addKnot op 1 #smooth #curve [10,6,0]
	addKnot op 1 #corner #curve [20,0,0]
	updateShape op
	op.steps = 3
	addModifier op (Extrude amount:12)
	op.pos = [120,0,0]

	local mir = Rectangle name:"FixtureExtMirror" length:10 width:16 cornerRadius:2
	addModifier mir (Extrude amount:4)
	mir.scale = [-1,1,1]
	mir.pos = [170,0,0]

	local ad = Circle name:"FixtureExtAdaptive" radius:6 adaptive:true
	addModifier ad (Extrude amount:4 mapcoords:true realWorldMapSize:true matIDs:false)
	ad.pos = [220,0,0]

	local offr = Rectangle name:"FixtureExtOff" length:10 width:10 cornerRadius:0
	local ex = Extrude amount:5
	addModifier offr ex
	ex.enabled = false
	offr.pos = [260,0,0]

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\extrude.max" quiet:true
	"extrude: " + (objects.count as string) + " objects: " + ((for o in objects collect o.name) as string)
)
