-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Editable Poly boxes with a CoronaPhysicalMtl each whose base map is a CoronaMix of two CoronaColors (top
-- 200 100 50, bottom 60 120 180): the operations add, subtract, divide, min, max and difference with mix in sRGB on
-- (the default), add with it off, a mix with multipliers and offsets on both layers, a subtract at amount 0.5 with
-- a CoronaColor mask; then three CoronaColor temperature maps (2000, 3000, 9000 K).
-- No file paths. Needs Corona (12, the one this was authored with).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local x = 0
	fn fixtureBox name x tex =
	(
		local o = Box name:(name + "Box") length:20 width:20 height:20 pos:[x,0,0] mapcoords:true
		o.material = CoronaPhysicalMtl name:name baseTexmap:tex
		convertToPoly o
		o
	)
	fn mixOf name op =
	(
		CoronaMix name:("FixtureCMix" + name) mixOperation:op mixAmount:1.0 \
			texmapTop:(CoronaColor name:("FixtureCMix" + name + "Top") color:(color 200 100 50)) \
			texmapBottom:(CoronaColor name:("FixtureCMix" + name + "Bottom") color:(color 60 120 180))
	)
	local ops = #(#("Add", 0), #("Subtract", 1), #("Divide", 3), #("Min", 4), #("Max", 5), #("Difference", 8))
	for o in ops do (
		fixtureBox ("FixtureCoronaMix" + o[1]) x (mixOf o[1] o[2]); x += 40
	)

	local t = mixOf "AddLinear" 0
	t.mixInSRgb = false
	fixtureBox "FixtureCoronaMixAddLinear" x t; x += 40

	t = mixOf "Scaled" 6
	t.mixAmount = 0.75
	t.multiplierTop = 0.5
	t.offsetTop = 0.2
	t.multiplierBottom = 2.0
	t.offsetBottom = -0.1
	fixtureBox "FixtureCoronaMixScaled" x t; x += 40

	t = mixOf "Masked" 1
	t.mixAmount = 0.5
	t.texmapMix = CoronaColor name:"FixtureCMixMaskedMask" color:(color 64 64 64)
	fixtureBox "FixtureCoronaMixMasked" x t; x += 40

	for k in #(2000, 3000, 9000) do (
		fixtureBox ("FixtureCoronaKelvin" + (k as string)) x (CoronaColor name:("FixtureCKelvin" + (k as string)) method:2 temperature:k)
		x += 40
	)

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\corona_mix_ops.max" quiet:true
	"corona_mix_ops: " + (objects.count as string) + " object(s)"
)
