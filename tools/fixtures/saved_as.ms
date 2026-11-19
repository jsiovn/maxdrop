-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- One Editable Poly box 20 x 30 x 40 at [10,20,0] with a Standard material, on a layer of its own, saved in the
-- 3ds Max 2017, 2018 and 2019 formats (saved_as_2017.max, saved_as_2018.max, saved_as_2019.max). The node,
-- material and layer names hold non-ASCII characters (U+00F6, U+00E4, U+4E2D), built from their code points so
-- this file stays ASCII. Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so
-- run it in a 3ds Max 2020 session with nothing to keep, then sanitize and check each saved file before it goes
-- into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local oe = bit.intAsChar 0xF6
	local ae = bit.intAsChar 0xE4
	local zh = bit.intAsChar 0x4E2D
	local mat = StandardMaterial name:("FixtureR" + oe + "t" + zh) diffuse:(color 200 40 30)
	local b = Box name:("FixtureB" + oe + "x" + zh) length:30 width:20 height:40 pos:[10,20,0] mapcoords:true
	b.material = mat
	convertToPoly b
	local la = LayerManager.newLayerFromName ("FixtureL" + ae + "yer" + zh)
	la.addNode b
	makeDir @"C:\maxdrop_fixtures" all:true
	local saved = #()
	for v in #(2017, 2018, 2019) do
	(
		local path = @"C:\maxdrop_fixtures\saved_as_" + (v as string) + ".max"
		if saveMaxFile path saveAsVersion:v quiet:true do append saved (v as string)
	)
	"saved_as: " + (objects.count as string) + " object(s), saved as " + (saved as string)
)
