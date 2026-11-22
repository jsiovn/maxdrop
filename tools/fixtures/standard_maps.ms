-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Seven Editable Poly boxes, one Standard material each: Blinn, Anisotropic, Multi-Layer, Oren-Nayar-Blinn,
-- Translucent and Strauss with a named Checker map in every map channel MaxDrop reads (found by the name
-- 3ds Max gives the channel, getSubTexmapSlotName: the map tables follow each shader's own channel order), each
-- at an amount of its own; and one Anisotropic material, created as Blinn, whose bump and self-illumination maps
-- are set after the shader switch without touching their amounts (what the file stores at an occupied channel
-- whose amount was never set). Map names: "FixtureMap" + shader + channel field (Diffuse, Specular, Level,
-- Glossiness, SelfIllum, Opacity, Bump, Reflection, Metalness).
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

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\standard_maps.max" quiet:true
	"standard_maps: " + (objects.count as string) + " object(s)"
)
