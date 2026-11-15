-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- One Editable Mesh box with two smoothing groups (1: bottom and top, 2: the sides) and material IDs 1-3 (1: bottom
-- and top, 2: front and back, 3: right and left) under a Multi/Sub-Object material of three Standard materials.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local multi = MultiMaterial numsubs:3 name:"FixtureMulti"
	multi.materialList[1] = StandardMaterial name:"FixtureMatA" diffuse:(color 200 40 30)
	multi.materialList[2] = StandardMaterial name:"FixtureMatB" diffuse:(color 40 160 60)
	multi.materialList[3] = StandardMaterial name:"FixtureMatC" diffuse:(color 40 80 200)
	multi.materialIDList = #(1, 2, 3)
	local b = Box name:"FixtureMesh" length:20 width:20 height:20 pos:[0,0,0] mapcoords:true
	convertToMesh b
	-- Face order of a box: 1-2 bottom, 3-4 top, 5-6 front, 7-8 right, 9-10 back, 11-12 left.
	local ids = #(1, 1, 1, 1, 2, 2, 3, 3, 2, 2, 3, 3)
	for f = 1 to b.numfaces do
	(
		setFaceSmoothGroup b f (if f <= 4 then 1 else 2)
		setFaceMatID b f ids[f]
	)
	update b
	b.material = multi
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\editable_mesh.max" quiet:true
	"editable_mesh: " + (b.numfaces as string) + " faces, " + ((classOf b) as string)
)
