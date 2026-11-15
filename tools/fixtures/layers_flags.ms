-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Two layers (FixtureLayerA, FixtureLayerB), one hidden object, one object that does not render and a group of two
-- boxes.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local mat = StandardMaterial name:"FixtureRed" diffuse:(color 200 40 30)
	local la = LayerManager.newLayerFromName "FixtureLayerA"
	local lb = LayerManager.newLayerFromName "FixtureLayerB"
	local visible = Box name:"FixtureVisible" length:10 width:10 height:10 pos:[0,0,0]
	local hidden = Box name:"FixtureHidden" length:10 width:10 height:10 pos:[20,0,0]
	local norender = Box name:"FixtureNoRender" length:10 width:10 height:10 pos:[40,0,0]
	local ga = Box name:"FixtureGroupA" length:10 width:10 height:10 pos:[0,30,0]
	local gb = Box name:"FixtureGroupB" length:10 width:10 height:10 pos:[20,30,0]
	for o in #(visible, hidden, norender, ga, gb) do
	(
		o.material = mat
		convertToPoly o
	)
	la.addNode visible
	lb.addNode hidden
	lb.addNode norender
	hidden.isHidden = true
	norender.renderable = false
	local g = group #(ga, gb) name:"FixtureGroup"
	for o in #(g, ga, gb) do la.addNode o
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\layers_flags.max" quiet:true
	"layers_flags: " + (objects.count as string) + " objects, " + (LayerManager.count as string) + " layers"
)
