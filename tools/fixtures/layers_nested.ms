-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Parent layers with a flag: a hidden parent layer (FixtureHiddenParentLayer) and a frozen one
-- (FixtureFrozenParentLayer), each with a child layer holding a box, and a three-level nest (FixtureTopLayer >
-- FixtureMiddleLayer > FixtureBottomLayer) whose top is hidden, a box on the bottom layer. FixtureControl is on
-- layer 0. 3ds Max keeps each flag on the layer it was set on; MAXScript's isHidden and isFrozen of the layers
-- below, and of their nodes, answer true.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local mat = StandardMaterial name:"FixtureRed" diffuse:(color 200 40 30)
	local hiddenParent = LayerManager.newLayerFromName "FixtureHiddenParentLayer"
	local hiddenChild = LayerManager.newLayerFromName "FixtureHiddenChildLayer"
	local frozenParent = LayerManager.newLayerFromName "FixtureFrozenParentLayer"
	local frozenChild = LayerManager.newLayerFromName "FixtureFrozenChildLayer"
	local top = LayerManager.newLayerFromName "FixtureTopLayer"
	local middle = LayerManager.newLayerFromName "FixtureMiddleLayer"
	local bottom = LayerManager.newLayerFromName "FixtureBottomLayer"
	hiddenChild.setParent hiddenParent
	frozenChild.setParent frozenParent
	middle.setParent top
	bottom.setParent middle
	local underHidden = Box name:"FixtureUnderHiddenParent" length:10 width:10 height:10 pos:[0,0,0]
	local underFrozen = Box name:"FixtureUnderFrozenParent" length:10 width:10 height:10 pos:[20,0,0]
	local deep = Box name:"FixtureDeepNested" length:10 width:10 height:10 pos:[40,0,0]
	local control = Box name:"FixtureControl" length:10 width:10 height:10 pos:[60,0,0]
	for o in #(underHidden, underFrozen, deep, control) do
	(
		o.material = mat
		convertToPoly o
	)
	hiddenChild.addNode underHidden
	frozenChild.addNode underFrozen
	bottom.addNode deep
	(LayerManager.getLayer 0).addNode control
	hiddenParent.isHidden = true
	frozenParent.isFrozen = true
	top.isHidden = true
	(LayerManager.getLayer 0).current = true
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\layers_nested.max" quiet:true
	"layers_nested: " + (objects.count as string) + " objects, " + (LayerManager.count as string) + " layers"
)
