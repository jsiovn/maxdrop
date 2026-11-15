-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Two Editable Poly boxes with a CoronaLightMtl each. FixtureCoronaLight: color, intensity 12.5, a CoronaBitmap
-- as its texture and one as its opacity. FixtureCoronaLightPlain: color, intensity 3, emitting on both sides, its
-- texture slot switched off. The bitmaps name files that do not exist, by a bare file name. Needs Corona (12, the
-- one this was authored with).
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

	local a = CoronaLightMtl name:"FixtureCoronaLight"
	a.color = color 255 200 150
	a.intensity = 12.5
	a.texmap = CoronaBitmap name:"FixtureCLightTex" filename:"fixture_c_light.png"
	a.opacityTexmap = CoronaBitmap name:"FixtureCLightAlpha" filename:"fixture_c_light_alpha.png"
	fixtureBox "FixtureCoronaLightBox" 0 a

	local b = CoronaLightMtl name:"FixtureCoronaLightPlain"
	b.color = color 100 150 255
	b.intensity = 3.0
	b.twosidedEmission = true
	b.texmap = CoronaBitmap name:"FixtureCLightOff" filename:"fixture_c_light_off.png"
	b.texmapOn = false
	fixtureBox "FixtureCoronaLightPlainBox" 40 b

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\corona_light.max" quiet:true
	"corona_light: " + (objects.count as string) + " object(s)"
)
