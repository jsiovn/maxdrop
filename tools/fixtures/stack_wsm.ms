-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- World-space modifiers (bindings) on boxes converted to Editable Poly, for Scene.object_stack and
-- reader/modifiers.py: a world-space modifier sits in a derived object of its own (special id 0x2033) above the
-- object-space stack. FixtureWSM: a UVW Map (box, 30 x 30 x 30), then a Map Scaler binding (node slot 1 = 0x2033
-- -> [Map Scaler, the 0x2032 derived object -> [UVW Map, the Editable Poly]]); FixtureWSMOnly: a Map Scaler binding
-- and no object-space modifier (0x2033 -> [Map Scaler, the Editable Poly]). One Standard material on both nodes.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)
	local wsm = Box name:"FixtureWSM" length:20 width:20 height:20 pos:[0,0,0] mapcoords:true
	convertToPoly wsm
	addModifier wsm (Uvwmap maptype:4 length:30 width:30 height:30 mapChannel:1)
	addModifier wsm (MapScaler scale:25)  -- MapScaler is the binding; MapScalerOSM is its object-space sibling

	local only = Box name:"FixtureWSMOnly" length:10 width:10 height:30 pos:[40,0,0] mapcoords:true
	convertToPoly only
	addModifier only (MapScaler scale:10)

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\stack_wsm.max" quiet:true
	"stack_wsm: " + (objects.count as string) + " objects; stacks: " + \
		((for o in objects collect (o.name + " " + (o.modifiers as string) + " " + \
			((for m in o.modifiers collect (superclassOf m) as string) as string))) as string)
)
