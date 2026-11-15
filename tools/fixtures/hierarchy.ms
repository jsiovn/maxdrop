-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- A three-level hierarchy: a root rotated 30 degrees about Z with a moved pivot, a child with a moved pivot, a leaf
-- with a negative scale, and two objects both named FixtureTwin (one a child of the root, one at the top level).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	local root = Box name:"FixtureRoot" length:20 width:20 height:10 pos:[0,0,0]
	local child = Box name:"FixtureChild" length:10 width:10 height:10 pos:[30,0,0]
	local leaf = Box name:"FixtureLeaf" length:6 width:6 height:6 pos:[50,0,0]
	local twinA = Box name:"FixtureTwin" length:8 width:8 height:8 pos:[0,40,0]
	local twinB = Box name:"FixtureTwin" length:8 width:8 height:8 pos:[0,-40,0]
	for o in #(root, child, leaf, twinA, twinB) do
	(
		o.material = mat
		convertToPoly o
	)
	root.pivot = [-5,-5,0]
	child.pivot = [25,-5,0]
	child.parent = root
	leaf.parent = child
	twinA.parent = root
	leaf.scale = [-1,1,1]
	rotate root (eulerAngles 0 0 30)
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\hierarchy.max" quiet:true
	"hierarchy: " + (objects.count as string) + " objects"
)
