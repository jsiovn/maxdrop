-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Object Properties > Rendering Control By Layer (maxdrop-em3.145): a node set By Layer renders, casts and receives
-- shadows as its own layer says, whatever its own flags; a node set By Object on the same layer keeps its own. Layers
-- with Cast Shadows, Receive Shadows or Renderable off, one with all three on, and a child layer (all on) of a parent
-- layer with all three off (3ds Max takes only the node's own layer). FixtureByLayerOwnOff has its own three flags
-- off. A render flag set after renderByLayer turns By Layer off again, so each node's own flags come first.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local mat = StandardMaterial name:"FixtureRed" diffuse:(color 200 40 30)
	local noCast = LayerManager.newLayerFromName "FixtureNoCastLayer"
	local noReceive = LayerManager.newLayerFromName "FixtureNoReceiveLayer"
	local noRender = LayerManager.newLayerFromName "FixtureNoRenderLayer"
	local allOn = LayerManager.newLayerFromName "FixtureOnLayer"
	local parentLayer = LayerManager.newLayerFromName "FixtureNoRenderParent"
	local childLayer = LayerManager.newLayerFromName "FixtureChildLayer"
	childLayer.setParent parentLayer
	noCast.castShadows = false
	noReceive.receiveShadows = false
	noRender.renderable = false
	parentLayer.renderable = false
	parentLayer.castShadows = false
	parentLayer.receiveShadows = false
	local specs = #( \
		#("FixtureByLayerNoCast", noCast, true), \
		#("FixtureByObjectOnNoCast", noCast, false), \
		#("FixtureByLayerNoReceive", noReceive, true), \
		#("FixtureByLayerNoRender", noRender, true), \
		#("FixtureByObjectOnNoRender", noRender, false), \
		#("FixtureByLayerOwnOff", allOn, true), \
		#("FixtureByLayerChild", childLayer, true) \
	)
	local x = 0
	for s in specs do
	(
		local o = Box name:s[1] length:10 width:10 height:10 pos:[x, 0, 0]
		o.material = mat
		convertToPoly o
		s[2].addNode o
		if s[1] == "FixtureByLayerOwnOff" do
		(
			o.renderable = false
			o.castShadows = false
			o.receiveShadows = false
		)
		if s[3] do o.renderByLayer = true
		x += 20
	)
	(LayerManager.getLayer 0).current = true
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\layers_render.max" quiet:true
	"layers_render: " + (objects.count as string) + " objects, " + (LayerManager.count as string) + " layers"
)
