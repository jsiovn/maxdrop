-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- The shape settings shapes.max leaves out, for reader/shapes.py and build/curves.py:
-- FixtureNGonCorner (6 sides, corner radius 2), FixtureNGonCornerIn (3 sides, inscribed, corner radius 1.5),
-- FixtureNGonCornerRound (5 sides, circular: the corner radius is ignored), FixtureNGonCornerBig (4 sides, a corner
-- radius past half a side: the knots cross).
-- FixtureEllOutline (outline 3: a second spline outside), FixtureEllInset (outline -15: the short semi-axis
-- clamped at 0).
-- FixtureRectOver: a Rectangle whose corner radius is more than half its length.
-- FixtureArcSame (from = to: a zero-length arc), FixtureArcOver (to past 360), FixtureArcUnder (from below 0),
-- FixtureArcWrap (to below from).
-- FixtureSection: a straight Line along X, renderable with a rectangular section (width 4, length 1, angle 30) and
-- a round angle of 15 (a value apart from the rectangular one). FixtureSectionLoop: a Circle with a rectangular
-- section (width 3, length 1.5).
-- FixtureCurveStd: a renderable Circle with a Standard material (FixtureCurveRed). FixtureCurveMulti: a renderable
-- Line with a Multi/Sub-Object (ID 1 FixtureCurveSubOne, ID 2 FixtureCurveSubTwo), its segments at ID 1. They come
-- after FixtureBox, so the nodes above keep their handles.
-- FixtureCurveIds: a renderable Line under the same Multi/Sub-Object, two open splines, the first one's segments at
-- ID 2, the second one's at ID 1 (each spline its own sub-material). FixtureCurveMixed: one open spline whose
-- segments are at IDs 2, 1, 1 (a curve has one material per spline: the first segment's). They come last.
-- FixtureBox, a box with a Standard material, is there for the import smoke test, which expects a mesh and a
-- material from every fixture; the other shapes have no material.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)

	NGon name:"FixtureNGonCorner" radius:10 nsides:6 cornerRadius:2 pos:[0,0,0]
	NGon name:"FixtureNGonCornerIn" radius:10 nsides:3 scribe:1 cornerRadius:1.5 pos:[40,0,0]
	NGon name:"FixtureNGonCornerRound" radius:10 nsides:5 circular:true cornerRadius:2 pos:[80,0,0]
	NGon name:"FixtureNGonCornerBig" radius:10 nsides:4 cornerRadius:30 pos:[140,0,0]

	Ellipse name:"FixtureEllOutline" length:20 width:40 ellipse_outline:true ellipse_thickness:3 pos:[0,-60,0]
	Ellipse name:"FixtureEllInset" length:20 width:40 ellipse_outline:true ellipse_thickness:-15 pos:[60,-60,0]
	Rectangle name:"FixtureRectOver" length:10 width:30 cornerRadius:8 pos:[120,-60,0]

	Arc name:"FixtureArcSame" radius:10 from:40 to:40 pos:[0,-100,0]
	Arc name:"FixtureArcOver" radius:10 from:10 to:370 pos:[40,-100,0]
	Arc name:"FixtureArcUnder" radius:10 from:-30 to:60 pos:[80,-100,0]
	Arc name:"FixtureArcWrap" radius:10 from:100 to:50 pos:[120,-100,0]

	local ln = line name:"FixtureSection"
	addNewSpline ln
	addKnot ln 1 #corner #line [0,0,0]
	addKnot ln 1 #corner #line [10,0,0]
	updateShape ln
	ln.render_renderable = true
	ln.render_rectangular = true
	ln.render_width = 4.0
	ln.render_length = 1.0
	ln.render_angle2 = 30.0
	ln.render_angle = 15.0
	ln.pos = [0,-140,0]

	local loop = Circle name:"FixtureSectionLoop" radius:10 pos:[40,-140,0]
	loop.render_renderable = true
	loop.render_rectangular = true
	loop.render_width = 3.0
	loop.render_length = 1.5

	local slab = Box name:"FixtureBox" length:10 width:10 height:2 mapcoords:true pos:[0,40,0]
	convertToPoly slab
	slab.material = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)

	local red = Circle name:"FixtureCurveStd" radius:5 pos:[80,-140,0]
	red.render_renderable = true
	red.render_thickness = 1.0
	red.material = StandardMaterial name:"FixtureCurveRed" diffuse:(color 200 30 20)

	local wire = line name:"FixtureCurveMulti"
	addNewSpline wire
	addKnot wire 1 #corner #line [0,0,0]
	addKnot wire 1 #corner #line [10,0,0]
	addKnot wire 1 #corner #line [10,10,0]
	updateShape wire
	wire.render_renderable = true
	wire.render_thickness = 1.0
	wire.pos = [120,-140,0]
	local multi = MultiMaterial name:"FixtureCurveMulti" numsubs:2
	multi.materialList[1] = StandardMaterial name:"FixtureCurveSubOne" diffuse:(color 20 30 200)
	multi.materialList[2] = StandardMaterial name:"FixtureCurveSubTwo" diffuse:(color 20 200 30)
	wire.material = multi

	local ids = line name:"FixtureCurveIds"
	addNewSpline ids
	addKnot ids 1 #corner #line [0,0,0]
	addKnot ids 1 #corner #line [10,0,0]
	addKnot ids 1 #corner #line [10,10,0]
	addNewSpline ids
	addKnot ids 2 #corner #line [0,4,0]
	addKnot ids 2 #corner #line [6,4,0]
	addKnot ids 2 #corner #line [6,10,0]
	updateShape ids
	for seg = 1 to 2 do (setMaterialID ids 1 seg 2; setMaterialID ids 2 seg 1)
	updateShape ids
	ids.render_renderable = true
	ids.render_thickness = 1.0
	ids.pos = [160,-140,0]
	ids.material = multi

	local mixed = line name:"FixtureCurveMixed"
	addNewSpline mixed
	addKnot mixed 1 #corner #line [0,0,0]
	addKnot mixed 1 #corner #line [10,0,0]
	addKnot mixed 1 #corner #line [10,10,0]
	addKnot mixed 1 #corner #line [0,10,0]
	updateShape mixed
	setMaterialID mixed 1 1 2
	setMaterialID mixed 1 2 1
	setMaterialID mixed 1 3 1
	updateShape mixed
	mixed.render_renderable = true
	mixed.render_thickness = 1.0
	mixed.pos = [200,-140,0]
	mixed.material = multi

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\shapes_more.max" quiet:true
	"shapes_more: " + (objects.count as string) + " objects: " + ((for o in objects collect o.name) as string)
)
