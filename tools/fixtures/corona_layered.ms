-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Two Editable Poly boxes with a CoronaLayeredMtl each. FixtureCoronaLayered has a CoronaPhysicalMtl base and a
-- CoronaPhysicalMtl layer at 50 % with a CoronaBitmap mask; FixtureCoronaLayeredNoBase has no base and a
-- CoronaLegacyMtl in its second layer slot. The bitmap names a file that does not exist, by a bare file name.
-- Needs Corona (12, the one this was authored with).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	fn fixtureBox name x mat =
	(
		local o = Box name:name length:20 width:20 height:20 pos:[x,0,0] mapcoords:true
		o.material = mat
		convertToPoly o
		o
	)

	local a = CoronaLayeredMtl name:"FixtureCoronaLayered"
	a.baseMtl = CoronaPhysicalMtl name:"FixtureCoronaLayerBase" baseColor:(color 90 160 70) baseRoughness:0.45
	a.layers[1] = CoronaPhysicalMtl name:"FixtureCoronaLayerCoat" baseColor:(color 240 240 240) baseRoughness:0.1
	a.mixmaps[1] = CoronaBitmap name:"FixtureCLayerMask" filename:"fixture_c_layer_mask.png"
	a.amounts[1] = 50.0  -- percent in MAXScript, a fraction in the file
	fixtureBox "FixtureCoronaLayeredBox" 0 a

	local b = CoronaLayeredMtl name:"FixtureCoronaLayeredNoBase"
	b.layers[2] = CoronaLegacyMtl name:"FixtureCoronaLayerOnly" colorDiffuse:(color 70 80 200)
	fixtureBox "FixtureCoronaLayeredNoBaseBox" 40 b

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\corona_layered.max" quiet:true
	"corona_layered: " + (objects.count as string) + " object(s)"
)
