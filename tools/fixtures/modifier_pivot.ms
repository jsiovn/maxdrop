-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- One Editable Poly box 10 x 10 x 40 (four height segments: 20 vertices, 18 quads) shared by three nodes:
-- FixtureSource, the bare base object; FixtureBent, a reference with a UVW Map under a Bend (stack top to bottom:
-- Bend, UVW Map) and its pivot alone rotated +30 degrees about Z (the object stays where it was, so the object
-- offset rotation is -30 degrees); FixtureSmooth, a reference with a TurboSmooth (one iteration), which changes the
-- evaluated counts. References, not instances: a modifier added to an instance goes to every instance.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local mat = StandardMaterial name:"FixtureBlue" diffuse:(color 40 80 200)
	local src = Box name:"FixtureSource" length:10 width:10 height:40 heightsegs:4 pos:[0,0,0] mapcoords:true
	src.material = mat
	convertToPoly src
	local bent = reference src name:"FixtureBent" pos:[30,0,0]
	local smooth = reference src name:"FixtureSmooth" pos:[60,0,0]
	-- Affect Pivot Only: turn the node, then turn the object offset back by the same rotation
	local q = inverse ((eulerAngles 0 0 30) as quat)
	in coordsys local bent.rotation *= q
	bent.objectOffsetRot *= q
	bent.objectOffsetPos *= q
	addModifier bent (Uvwmap())
	addModifier bent (Bend angle:60 axis:2)
	addModifier smooth (TurboSmooth iterations:1)
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\modifier_pivot.max" quiet:true
	"modifier_pivot: " + (objects.count as string) + " objects; stacks: " + (src.modifiers as string) + ", " + \
		(bent.modifiers as string) + ", " + (smooth.modifiers as string)
)
