-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Editable Poly boxes with a CoronaPhysicalMtl each whose base map is a CoronaMix of two CoronaColor HDR maps
-- (bottom 0.05 0.4 0.9, top 0.6 0.2 0.75): the operations screen, overlay, color dodge, color burn, linear burn,
-- linear light, hard light and exclusion with mix in sRGB on (the default), linear light and linear burn with it
-- off, linear light over dark layers (bottom 0 0.05 0.2, top 0 0.1 0.05); then gamma of the same bottom under a
-- grey top color (white, multiplier 0.5) at amount 1 and 0.5; last, gamma under a mid-grey top swatch (128) over a
-- CoronaBitmap bottom (a bare file name that need not exist), mix in sRGB on. corona_mix_ops holds the other
-- operations (a file of its own: both together pass 1 MB).
-- No file paths. Needs Corona (12, the one this was authored with).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)
	local x = 0
	local t
	fn fixtureBox name x tex =
	(
		local o = Box name:(name + "Box") length:20 width:20 height:20 pos:[x,0,0] mapcoords:true
		o.material = CoronaPhysicalMtl name:name baseTexmap:tex
		convertToPoly o
		o
	)
	fn hdrMixOf name op bottom top =
	(
		CoronaMix name:("FixtureCMix" + name) mixOperation:op mixAmount:1.0 \
			texmapTop:(CoronaColor name:("FixtureCMix" + name + "Top") method:1 colorHdr:top) \
			texmapBottom:(CoronaColor name:("FixtureCMix" + name + "Bottom") method:1 colorHdr:bottom)
	)
	local hdrOps = #(#("Screen", 9), #("Overlay", 10), #("ColorDodge", 11), #("ColorBurn", 12), #("LinearBurn", 13),
		#("LinearLight", 14), #("HardLight", 16), #("Exclusion", 20))
	for o in hdrOps do (
		fixtureBox ("FixtureCoronaMix" + o[1]) x (hdrMixOf o[1] o[2] [0.05,0.4,0.9] [0.6,0.2,0.75]); x += 40
	)
	for o in #(#("LinearLightLinear", 14), #("LinearBurnLinear", 13)) do (
		t = hdrMixOf o[1] o[2] [0.05,0.4,0.9] [0.6,0.2,0.75]
		t.mixInSRgb = false
		fixtureBox ("FixtureCoronaMix" + o[1]) x t; x += 40
	)
	fixtureBox "FixtureCoronaMixLinearLightDark" x (hdrMixOf "LinearLightDark" 14 [0,0.05,0.2] [0,0.1,0.05]); x += 40
	for o in #(#("Gamma", 1.0), #("GammaHalf", 0.5)) do (
		t = CoronaMix name:("FixtureCMix" + o[1]) mixOperation:7 mixAmount:o[2] colorTop:white multiplierTop:0.5 \
			texmapBottom:(CoronaColor name:("FixtureCMix" + o[1] + "Bottom") method:1 colorHdr:[0.05,0.4,0.9])
		fixtureBox ("FixtureCoronaMix" + o[1]) x t; x += 40
	)
	t = CoronaMix name:"FixtureCMixGammaGrey" mixOperation:7 mixAmount:1.0 colorTop:(color 128 128 128) \
		texmapBottom:(CoronaBitmap name:"FixtureCMixGammaGreyBottom" filename:"cmix_gamma_bottom.png")
	t.mixInSRgb = true
	fixtureBox "FixtureCoronaMixGammaGrey" x t; x += 40

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\corona_mix_blends.max" quiet:true
	"corona_mix_blends: " + (objects.count as string) + " object(s)"
)
