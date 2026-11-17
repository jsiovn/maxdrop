-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Shapes, for the reader of splines (reader/shapes.py) and the curves built from them (build/curves.py):
-- FixtureLine: a Line with two splines, a closed one with a corner, a smooth, a Bezier and a Bezier corner knot,
-- and an open one whose second segment is a straight line although its knots have vectors; renderable (Enable In
-- Renderer and In Viewport, thickness 2, 8 sides), 4 interpolation steps.
-- FixtureEditable: a Circle collapsed to an Editable Spline, its first knot moved.
-- FixtureOpen: an open spline of class SplineShape, a child of FixtureRect, turned 30 degrees about Z.
-- FixtureRect: a Rectangle with a corner radius; FixtureRectSharp: one without.
-- FixtureCircle (3 steps), FixtureEllipse, FixtureArc (stood up: turned 90 degrees about X), FixturePie (an Arc
-- closed through its center), FixtureArcWide (350 degrees, reversed), FixtureNGon (6 sides, adaptive),
-- FixtureNGonRound (5 sides, circular), FixtureNGonIn (3 sides, inscribed).
-- Knots are added with the node at the origin, so object space and world space agree while they are; the nodes
-- are placed afterwards. FixtureBox, a box with a Standard material, is there for the import smoke test, which
-- expects a mesh and a material from every fixture; the shapes have no material.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)

	local ln = line name:"FixtureLine"
	addNewSpline ln
	addKnot ln 1 #corner #curve [0,0,0]
	addKnot ln 1 #smooth #curve [20,0,0]
	addKnot ln 1 #bezier #curve [30,10,0] [25,15,0] [35,5,0]
	addKnot ln 1 #bezierCorner #curve [20,20,0] [28,22,0] [15,25,5]
	close ln 1
	addNewSpline ln
	addKnot ln 2 #corner #curve [0,30,0]
	addKnot ln 2 #bezier #line [10,40,0] [5,40,0] [15,40,0]
	addKnot ln 2 #corner #curve [20,30,0]
	updateShape ln
	ln.render_renderable = true
	ln.render_displayRenderMesh = true
	ln.render_thickness = 2.0
	ln.render_sides = 8
	ln.steps = 4
	ln.pos = [-40,0,0]

	local ed = Circle name:"FixtureEditable" radius:8
	convertToSplineShape ed
	setKnotPoint ed 1 1 [10,1,0]
	updateShape ed
	ed.pos = [60,0,0]

	local rect = Rectangle name:"FixtureRect" length:20 width:30 cornerRadius:3 pos:[0,-40,0]
	local sharp = Rectangle name:"FixtureRectSharp" length:10 width:12 cornerRadius:0 pos:[0,-80,0]

	local op = SplineShape name:"FixtureOpen"
	addNewSpline op
	addKnot op 1 #smooth #curve [0,0,0]
	addKnot op 1 #smooth #curve [10,5,0]
	addKnot op 1 #smooth #curve [20,0,3]
	updateShape op
	rotate op (eulerAngles 0 0 30)
	op.pos = [5,-35,0]
	op.parent = rect

	local c = Circle name:"FixtureCircle" radius:10 steps:3 pos:[40,-40,0]
	local e = Ellipse name:"FixtureEllipse" length:20 width:40 pos:[80,-40,0]
	local a = Arc name:"FixtureArc" radius:15 from:30 to:200
	rotate a (eulerAngles 90 0 0)
	a.pos = [120,-40,0]
	local p = Arc name:"FixturePie" radius:12 from:0 to:90 pie:true pos:[160,-40,0]
	local w = Arc name:"FixtureArcWide" radius:8 from:0 to:350 reverse:true pos:[200,-40,0]
	local ng = NGon name:"FixtureNGon" radius:10 nsides:6 adaptive:true pos:[40,-80,0]
	local ngr = NGon name:"FixtureNGonRound" radius:10 nsides:5 circular:true pos:[80,-80,0]
	local ngi = NGon name:"FixtureNGonIn" radius:10 nsides:3 scribe:1 pos:[120,-80,0]

	local slab = Box name:"FixtureBox" length:10 width:10 height:2 mapcoords:true pos:[0,40,0]
	convertToPoly slab
	slab.material = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\shapes.max" quiet:true
	"shapes: " + (objects.count as string) + " objects: " + ((for o in objects collect o.name) as string)
)
