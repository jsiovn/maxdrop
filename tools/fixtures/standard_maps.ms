-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Thirteen Editable Poly boxes, one Standard material each: Blinn, Anisotropic, Multi-Layer, Oren-Nayar-Blinn,
-- Translucent and Strauss with a named Checker map in every map channel MaxDrop reads (found by the name
-- 3ds Max gives the channel, getSubTexmapSlotName: the map tables follow each shader's own channel order), each
-- at an amount of its own; and one Anisotropic material, created as Blinn, whose bump and self-illumination maps
-- are set after the shader switch without touching their amounts (what the file stores at an occupied channel
-- whose amount was never set); one created as Blinn with diffuse and bump maps, then switched to Anisotropic (the
-- map table keeps Blinn's layout, the Texmaps object 3ds Max's); one Anisotropic with its bump map switched off;
-- four ("Level" + shader: Anisotropic, Multi-Layer, Oren-Nayar-Blinn, Translucent) with a diffuse map at a Diffuse
-- Level away from 100 and a Diffuse Level map at an amount, at 100, switched off, or none.
-- Nothing reads a material before the save. Map names: "FixtureMap" + shader + channel field (Diffuse, Specular, Level,
-- Glossiness, SelfIllum, Opacity, Bump, Reflection, Metalness, DiffuseLevel).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	fn fixtureBox name x mat =
	(
		local o = Box name:name length:20 width:20 height:20 pos:[x,0,0] mapcoords:true
		o.material = mat
		convertToPoly o
		o
	)
	-- the 1-based sub-texmap (= map table element) 3ds Max names slotName on this material's shader
	fn channelOf s slotName =
	(
		local found = 0
		for i = 1 to getNumSubTexmaps s while found == 0 do
			if getSubTexmapSlotName s i == slotName then found = i
		if found == 0 then throw ("no map channel named " + slotName + " on " + s.shaderByName)
		found
	)
	-- channels: #(#(field, 3ds Max's channel name, amount %), ...); amount undefined leaves it as it is
	fn fixtureMaps s label channels =
	(
		for c in channels do
		(
			local i = channelOf s c[2]
			s.maps[i] = Checker name:("FixtureMap" + label + c[1])
			s.mapEnables[i] = true
			if c[3] != undefined then s.mapAmounts[i] = c[3]
		)
		s
	)
	-- shaderType: 0 Anisotropic, 1 Blinn, 2 Metal, 3 Multi-Layer, 4 Oren-Nayar-Blinn, 5 Phong, 6 Strauss,
	-- 7 Translucent Shader
	fn fixtureStandard name shader =
	(
		local s = StandardMaterial name:name
		s.shaderType = shader
		s.diffuse = color 150 120 90
		s.specularLevel = 20.0
		s.glossiness = 30.0
		s
	)
	fn usual specular level gloss =
		#(#("Diffuse", "Diffuse Color", 51.0), #("Specular", specular, 52.0), #("Level", level, 53.0), \
			#("Glossiness", gloss, 54.0), #("SelfIllum", "Self-Illumination", 55.0), #("Opacity", "Opacity", 56.0), \
			#("Bump", "Bump", 57.0), #("Reflection", "Reflection", 58.0))

	local plain = usual "Specular Color" "Specular Level" "Glossiness"
	fixtureBox "FixtureMapsBlinnBox" 0 (fixtureMaps (fixtureStandard "FixtureMapsBlinn" 1) "Blinn" plain)
	fixtureBox "FixtureMapsAnisotropicBox" 40 \
		(fixtureMaps (fixtureStandard "FixtureMapsAnisotropic" 0) "Anisotropic" plain)
	fixtureBox "FixtureMapsMultiLayerBox" 80 (fixtureMaps (fixtureStandard "FixtureMapsMultiLayer" 3) "MultiLayer" \
		(usual "Specular Color 1" "Specular Level 1" "Glossiness 1"))
	fixtureBox "FixtureMapsOrenNayarBlinnBox" 120 \
		(fixtureMaps (fixtureStandard "FixtureMapsOrenNayarBlinn" 4) "OrenNayarBlinn" plain)
	fixtureBox "FixtureMapsTranslucentBox" 160 \
		(fixtureMaps (fixtureStandard "FixtureMapsTranslucent" 7) "Translucent" plain)

	local strauss = StandardMaterial name:"FixtureMapsStrauss"
	strauss.shaderType = 6
	strauss.diffuse = color 150 120 90
	strauss.glossiness = 30.0
	strauss.metalness = 40.0
	fixtureMaps strauss "Strauss" #(#("Diffuse", "Color", 51.0), #("Glossiness", "Glossiness", 54.0), \
		#("Metalness", "Metalness", 59.0), #("Opacity", "Opacity", 56.0), #("Bump", "Bump", 57.0), \
		#("Reflection", "Reflection", 58.0))
	fixtureBox "FixtureMapsStraussBox" 200 strauss

	local unset = fixtureStandard "FixtureMapsUnsetAmounts" 0
	fixtureMaps unset "UnsetAmounts" #(#("SelfIllum", "Self-Illumination", undefined), #("Bump", "Bump", undefined))
	fixtureBox "FixtureMapsUnsetAmountsBox" 240 unset

	-- created as Blinn with diffuse and bump maps (amounts untouched), then switched to Anisotropic: 3ds Max moves
	-- the bump map to Anisotropic's bump channel, the map table keeps it at Blinn's
	local switched = fixtureStandard "FixtureMapsSwitchedAfter" 1
	fixtureMaps switched "SwitchedAfter" #(#("Diffuse", "Diffuse Color", undefined), #("Bump", "Bump", undefined))
	switched.shaderType = 0
	fixtureBox "FixtureMapsSwitchedAfterBox" 280 switched

	-- Anisotropic with self-illumination and bump maps, the bump map switched off
	local offMat = fixtureStandard "FixtureMapsSwitchedOff" 0
	fixtureMaps offMat "SwitchedOff" #(#("SelfIllum", "Self-Illumination", undefined), #("Bump", "Bump", undefined))
	offMat.mapEnables[channelOf offMat "Bump"] = false
	fixtureBox "FixtureMapsSwitchedOffBox" 320 offMat

	-- a diffuse map at a Diffuse Level away from 100, with a Diffuse Level map (on, at an amount; on at 100; off)
	-- or without one; label "Level" + shader
	fn fixtureLevel name shader level channels =
	(
		local s = fixtureStandard ("FixtureMaps" + name) shader
		s.diffuseLevel = level
		fixtureMaps s name channels
	)
	fixtureBox "FixtureMapsLevelAnisotropicBox" 360 (fixtureLevel "LevelAnisotropic" 0 40.0 \
		#(#("Diffuse", "Diffuse Color", 61.0), #("DiffuseLevel", "Diffuse Level", 62.0)))
	fixtureBox "FixtureMapsLevelMultiLayerBox" 400 (fixtureLevel "LevelMultiLayer" 3 150.0 \
		#(#("Diffuse", "Diffuse Color", 63.0), #("DiffuseLevel", "Diffuse Level", 100.0)))
	local levelOff = fixtureLevel "LevelOrenNayarBlinn" 4 65.0 \
		#(#("Diffuse", "Diffuse Color", 65.0), #("DiffuseLevel", "Diffuse Level", 64.0))
	levelOff.mapEnables[channelOf levelOff "Diffuse Level"] = false
	fixtureBox "FixtureMapsLevelOrenNayarBlinnBox" 440 levelOff
	fixtureBox "FixtureMapsLevelTranslucentBox" 480 (fixtureLevel "LevelTranslucent" 7 80.0 \
		#(#("Diffuse", "Diffuse Color", 66.0)))

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\standard_maps.max" quiet:true
	"standard_maps: " + (objects.count as string) + " object(s)"
)
