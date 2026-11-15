-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- One Editable Poly mesh shared by four nodes (the source and three instances, one rotated, one scaled) and one
-- independent copy.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local mat = StandardMaterial name:"FixtureGreen" diffuse:(color 40 160 60)
	local src = Box name:"FixtureSource" length:10 width:10 height:10 pos:[0,0,0] mapcoords:true
	src.material = mat
	convertToPoly src
	local a = instance src name:"FixtureInstance01" pos:[20,0,0]
	local b = instance src name:"FixtureInstance02" pos:[40,0,0]
	local c = instance src name:"FixtureInstance03" pos:[60,0,0]
	rotate b (eulerAngles 0 0 45)
	c.scale = [2,2,2]
	local cp = copy src name:"FixtureCopy" pos:[0,20,0]
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\instances.max" quiet:true
	local shared = #()
	InstanceMgr.GetInstances src &shared
	"instances: " + (objects.count as string) + " objects, " + (shared.count as string) + " share the source mesh"
)
