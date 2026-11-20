-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Layer and node flags layers_flags does not have: a hidden layer, a frozen layer, a layer that does not render,
-- a nested layer (FixtureChildLayer, its parent FixtureParentLayer set with setParent; the parent holds no node), a
-- layer whose name holds U+00E4 and U+4E2D (built from their code points so this file stays ASCII), a frozen node
-- and a hidden parent node with a visible child. One box per layer.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local mat = StandardMaterial name:"FixtureRed" diffuse:(color 200 40 30)
	local hiddenLayer = LayerManager.newLayerFromName "FixtureHiddenLayer"
	local frozenLayer = LayerManager.newLayerFromName "FixtureFrozenLayer"
	local noRenderLayer = LayerManager.newLayerFromName "FixtureNoRenderLayer"
	local parentLayer = LayerManager.newLayerFromName "FixtureParentLayer"
	local childLayer = LayerManager.newLayerFromName "FixtureChildLayer"
	local textLayer = LayerManager.newLayerFromName ("FixtureL" + (bit.intAsChar 0xE4) + "yer" + (bit.intAsChar 0x4E2D))
	childLayer.setParent parentLayer
	local onHidden = Box name:"FixtureOnHiddenLayer" length:10 width:10 height:10 pos:[0,0,0]
	local onFrozen = Box name:"FixtureOnFrozenLayer" length:10 width:10 height:10 pos:[20,0,0]
	local onNoRender = Box name:"FixtureOnNoRenderLayer" length:10 width:10 height:10 pos:[40,0,0]
	local nested = Box name:"FixtureNested" length:10 width:10 height:10 pos:[60,0,0]
	local onText = Box name:"FixtureOnTextLayer" length:10 width:10 height:10 pos:[80,0,0]
	local frozen = Box name:"FixtureFrozen" length:10 width:10 height:10 pos:[0,30,0]
	local hiddenParent = Box name:"FixtureHiddenParent" length:10 width:10 height:10 pos:[20,30,0]
	local child = Box name:"FixtureVisibleChild" length:10 width:10 height:10 pos:[40,30,0]
	for o in #(onHidden, onFrozen, onNoRender, nested, onText, frozen, hiddenParent, child) do
	(
		o.material = mat
		convertToPoly o
	)
	hiddenLayer.addNode onHidden
	frozenLayer.addNode onFrozen
	noRenderLayer.addNode onNoRender
	childLayer.addNode nested
	textLayer.addNode onText
	child.parent = hiddenParent
	frozen.isFrozen = true
	hiddenParent.isHidden = true
	hiddenLayer.isHidden = true
	frozenLayer.isFrozen = true
	noRenderLayer.renderable = false
	(LayerManager.getLayer 0).current = true
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\layers_more.max" quiet:true
	"layers_more: " + (objects.count as string) + " objects, " + (LayerManager.count as string) + " layers"
)
