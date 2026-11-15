-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- One Editable Poly box with map channels 1 (the box's own coordinates), 2 (planar UVW Map) and 3 (cylindrical
-- UVW Map), the modifiers collapsed.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local mat = StandardMaterial name:"FixtureBlue" diffuse:(color 40 80 200)
	local b = Box name:"FixtureUV" length:20 width:20 height:20 pos:[0,0,0] mapcoords:true
	addModifier b (Uvwmap maptype:0 mapChannel:2 length:40 width:40)
	addModifier b (Uvwmap maptype:1 mapChannel:3 length:20 width:20 height:20)
	b.material = mat
	convertToPoly b
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\multi_uv.max" quiet:true
	local chans = for c = 1 to (polyop.getNumMaps b - 1) where polyop.getMapSupport b c collect c
	"multi_uv: map channels " + (chans as string)
)
