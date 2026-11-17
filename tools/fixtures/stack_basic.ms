-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Modifier stacks on boxes converted to Editable Poly, for the reader of the stack (reader/modifiers.py):
-- FixtureTurbo: a UVW Map (box, 30 x 30 x 30, renamed FixtureUVW) under a TurboSmooth (two iterations);
-- FixtureFlags: a Bend switched off, a Taper off in the viewport only, a Twist off in the renderer only;
-- FixtureSharedA and FixtureSharedB: one Noise modifier (renamed FixtureNoise) on both nodes, an instanced
-- modifier with a context per node;
-- FixtureNested: a Taper on the box; FixtureNestedRef, a reference of it with a Twist above the reference line
-- (a derived object whose base is another derived object). One Standard material on every node.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)
	local smooth = Box name:"FixtureTurbo" length:20 width:20 height:20 pos:[0,0,0] mapcoords:true
	convertToPoly smooth
	local uvw = Uvwmap maptype:4 length:30 width:30 height:30 mapChannel:1
	addModifier smooth uvw
	uvw.name = "FixtureUVW"
	addModifier smooth (TurboSmooth iterations:2)

	local flags = Box name:"FixtureFlags" length:10 width:10 height:40 mapcoords:true pos:[40,0,0]
	convertToPoly flags
	local bendMod = Bend angle:45 axis:2
	local taperMod = Taper amount:0.5
	local twistMod = Twist angle:90 axis:2
	addModifier flags bendMod
	addModifier flags taperMod
	addModifier flags twistMod
	bendMod.enabled = false
	taperMod.enabledInViews = false
	twistMod.enabledInRenders = false

	local a = Box name:"FixtureSharedA" length:10 width:10 height:10 mapcoords:true pos:[80,0,0]
	convertToPoly a
	local b = Box name:"FixtureSharedB" length:10 width:10 height:20 mapcoords:true pos:[100,0,0]
	convertToPoly b
	local noise = NoiseModifier strength:[2,2,2] seed:3
	-- added to both selected nodes at once, as in the modifier panel: one gizmo around both boxes, so each node's
	-- modifier context has a transform of its own (addModifier would give each an identity context)
	max modify mode
	select #(a, b)
	modPanel.addModToSelection noise ui:on
	clearSelection()
	noise.name = "FixtureNoise"

	local nested = Box name:"FixtureNested" length:10 width:10 height:30 mapcoords:true pos:[140,0,0]
	convertToPoly nested
	addModifier nested (Taper amount:-0.5)
	local ref = reference nested name:"FixtureNestedRef" pos:[160,0,0]
	addModifier ref (Twist angle:45 axis:2)

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\stack_basic.max" quiet:true
	"stack_basic: " + (objects.count as string) + " objects; stacks: " + \
		((for o in objects collect (o.name + " " + (o.modifiers as string))) as string)
)
