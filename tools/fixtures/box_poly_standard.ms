-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- One Editable Poly box 20 x 30 x 40 at [10,20,0] (bounding box [0,5,0]..[20,35,40]), Standard material.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local mat = StandardMaterial name:"FixtureRed" diffuse:(color 200 40 30)
	local b = Box name:"FixtureBox" length:30 width:20 height:40 pos:[10,20,0] mapcoords:true
	b.material = mat
	convertToPoly b
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\box_poly_standard.max" quiet:true
	"box_poly_standard: " + (objects.count as string) + " object(s), " + (polyop.getNumVerts b as string) + " vertices"
)
