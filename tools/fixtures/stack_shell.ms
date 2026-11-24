-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Shells whose surfaces lie on one side of the original or turn it inside out, as Solidify (convert/modifiers.py),
-- and the rim's shading. Every node but the plane is an Editable Poly box 20 x 20 x 20 without its top face, so the
-- shell has a rim: the facing of its triangles (the oracle's eval_mesh) tells an inside-out shell from another.
-- FixtureShellOut: inner amount -1, outer amount 2 (both surfaces outside the original).
-- FixtureShellIn: inner amount 3, outer amount -1 (both inside).
-- FixtureShellCrossed: inner amount -2, outer amount 1 (inner + outer < 0: 3ds Max's shell is inside out).
-- FixtureShellNegative: inner amount -1, outer amount -2 (inside out too).
-- FixtureShellRim: inner amount 0, outer amount 1, the defaults (auto smooth on, 45 degrees): the rim in groups of its
-- own, hard against both surfaces.
-- FixtureShellPlane: a plane (1 x 1 segments), inner 0, outer 1, auto smooth on: its rim's corners (90 degrees,
-- sharper than 45) split the rim into four groups.
-- FixtureShellOverride: the open box with auto smooth off and the override smoothing group 4, the group of one side:
-- the rim merges into that side.
-- FixtureShellTurbo: the open box with a TurboSmooth (1 iteration, Smooth Result) below the Shell (inner 0, outer 1):
-- the rim still hard against both smoothed surfaces.
-- FixtureShellSmoothed: the open box with a TurboSmooth (1 iteration) above the Shell: everything smooth.
-- FixtureShellSymHalf: half of the open box (2 segments along X and Y, the half of x < 0 deleted), a Symmetry along X
-- (slice, weld) below the Shell (inner 0, outer 1): the cut's open edges lie on the mirror plane and weld shut, the
-- top's make the rim, hard against both surfaces.
-- FixtureShellSymClosed: half of the closed box, the same Symmetry and Shell: every open edge welds, no rim.
-- FixtureShellSymQuarter: a quarter of the open box, Symmetry along X, then along Y, then the Shell.
-- FixtureShellUnderSym: the half open box, the Shell (inner 0, outer 1) below the Symmetry along X (slice, weld): the
-- Shell's rim along the cut lies on the mirror plane, the slice drops it and the weld shuts the cut.
-- FixtureShellUnderSymTurbo: the same with a TurboSmooth (1 iteration, Smooth Result) above the Symmetry.
-- FixtureShellBetweenSym: the quarter open box, Symmetry along X, the Shell, then Symmetry along Y.
-- FixtureShellUnderSymNoWeld: the half open box, the Shell below the Symmetry with its weld off: the slice drops the
-- rim on the plane and leaves the cut open.
-- FixtureShellUnderSymExtrude: an open line of three segments from x = 0 to x = 0 (its ends on the plane), extruded 20
-- without caps, then the Shell and the Symmetry along X: the open box's half made from a shape.
-- One Standard material on every node.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)

	fn open_box name pos inner outer =
	(
		local b = Box name:name length:20 width:20 height:20 mapcoords:true pos:pos
		convertToPoly b
		polyop.deleteFaces b #{2}  -- face 2 of a Box is its top
		addModifier b (Shell innerAmount:inner outerAmount:outer)
		b
	)

	open_box "FixtureShellOut" [0, 0, 0] -1.0 2.0
	open_box "FixtureShellIn" [40, 0, 0] 3.0 -1.0
	open_box "FixtureShellCrossed" [80, 0, 0] -2.0 1.0
	open_box "FixtureShellNegative" [120, 0, 0] -1.0 -2.0
	open_box "FixtureShellRim" [160, 0, 0] 0.0 1.0

	local flat = Plane name:"FixtureShellPlane" length:20 width:20 lengthsegs:1 widthsegs:1 mapcoords:true \
		pos:[200, 0, 0]
	convertToPoly flat
	addModifier flat (Shell innerAmount:0.0 outerAmount:1.0)

	local over = open_box "FixtureShellOverride" [240, 0, 0] 0.0 1.0
	over.modifiers[1].autoSmooth = false
	over.modifiers[1].overrideSmoothingGroup = true
	over.modifiers[1].smoothGroup = 4  -- a group number: the side of normal -Y has group 4

	local turbo = Box name:"FixtureShellTurbo" length:20 width:20 height:20 mapcoords:true pos:[0, 40, 0]
	convertToPoly turbo
	polyop.deleteFaces turbo #{2}
	addModifier turbo (TurboSmooth iterations:1)
	addModifier turbo (Shell innerAmount:0.0 outerAmount:1.0)

	local smoothed = open_box "FixtureShellSmoothed" [40, 40, 0] 0.0 1.0
	addModifier smoothed (TurboSmooth iterations:1)

	-- a box with 2 segments along X and Y, the faces whose center is on the side of x < 0 (and y < 0) deleted, its
	-- top too unless closed: its cut edges lie on the plane x = 0 (and y = 0)
	fn part_box name pos closed quarter =
	(
		local b = Box name:name length:20 width:20 height:20 widthsegs:2 lengthsegs:2 mapcoords:true
		convertToPoly b
		local gone = #{}
		for f = 1 to polyop.getNumFaces b do
		(
			local c = polyop.getFaceCenter b f
			if (not closed and c.z > 19.99) or c.x < -0.001 or (quarter and c.y < -0.001) do gone[f] = true
		)
		polyop.deleteFaces b gone
		b.pos = pos
		b
	)
	local half = part_box "FixtureShellSymHalf" [80, 40, 0] false false
	addModifier half (Symmetry axis:0 flip:false slice:1 weld:1 threshold:0.1)
	addModifier half (Shell innerAmount:0.0 outerAmount:1.0)
	local closedHalf = part_box "FixtureShellSymClosed" [120, 40, 0] true false
	addModifier closedHalf (Symmetry axis:0 flip:false slice:1 weld:1 threshold:0.1)
	addModifier closedHalf (Shell innerAmount:0.0 outerAmount:1.0)
	local quarter = part_box "FixtureShellSymQuarter" [160, 40, 0] false true
	addModifier quarter (Symmetry axis:0 flip:false slice:1 weld:1 threshold:0.1)
	addModifier quarter (Symmetry axis:1 flip:false slice:1 weld:1 threshold:0.1)
	addModifier quarter (Shell innerAmount:0.0 outerAmount:1.0)
	local under = part_box "FixtureShellUnderSym" [200, 40, 0] false false
	addModifier under (Shell innerAmount:0.0 outerAmount:1.0)
	addModifier under (Symmetry axis:0 flip:false slice:1 weld:1 threshold:0.1)
	local underTurbo = part_box "FixtureShellUnderSymTurbo" [240, 40, 0] false false
	addModifier underTurbo (Shell innerAmount:0.0 outerAmount:1.0)
	addModifier underTurbo (Symmetry axis:0 flip:false slice:1 weld:1 threshold:0.1)
	addModifier underTurbo (TurboSmooth iterations:1)
	local between = part_box "FixtureShellBetweenSym" [280, 40, 0] false true
	addModifier between (Symmetry axis:0 flip:false slice:1 weld:1 threshold:0.1)
	addModifier between (Shell innerAmount:0.0 outerAmount:1.0)
	addModifier between (Symmetry axis:1 flip:false slice:1 weld:1 threshold:0.1)
	local noWeld = part_box "FixtureShellUnderSymNoWeld" [320, 40, 0] false false
	addModifier noWeld (Shell innerAmount:0.0 outerAmount:1.0)
	addModifier noWeld (Symmetry axis:0 flip:false slice:1 weld:0 threshold:0.1)
	local line = SplineShape name:"FixtureShellUnderSymExtrude"
	addNewSpline line
	for p in #([0, -10, 0], [10, -10, 0], [10, 10, 0], [0, 10, 0]) do addKnot line 1 #corner #line p
	updateShape line
	line.pos = [360, 40, 0]
	addModifier line (Extrude amount:20 segs:1 capStart:false capEnd:false mapCoords:true)
	addModifier line (Shell innerAmount:0.0 outerAmount:1.0)
	addModifier line (Symmetry axis:0 flip:false slice:1 weld:1 threshold:0.1)

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\stack_shell.max" quiet:true
	"stack_shell: " + (objects.count as string) + " objects: " + \
		((for o in objects collect (o.name + " " + ((getnumverts (snapshotAsMesh o)) as string))) as string)
)
