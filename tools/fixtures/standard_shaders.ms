-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Ten Editable Poly boxes: one Standard material per shader (Anisotropic, Blinn, Metal, Multi-Layer,
-- Oren-Nayar-Blinn, Phong, Strauss, Translucent) and two Physical Materials. Each Standard material sets ambient
-- (Anisotropic, Multi-Layer, Oren-Nayar-Blinn and Translucent store their diffuse there whatever is set), diffuse,
-- specular color, specular level, glossiness, self-illumination amount and color to its own values, the
-- self-illumination color switched on for Blinn, Metal, Oren-Nayar-Blinn and Translucent; Multi-Layer's second
-- layer and Translucent's translucent color hold values the first layer does not. Both Physical Materials hold a
-- Checker or Noise map in the same nine slots (base color, reflectivity, roughness, metalness, transparency,
-- emission, emission color, bump, cutout), each slot switched off in one of them and on in the other; the first
-- inverts its roughness and coat roughness and is thin-walled.
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
	-- shaderType: 0 Anisotropic, 1 Blinn, 2 Metal, 3 Multi-Layer, 4 Oren-Nayar-Blinn, 5 Phong, 6 Strauss,
	-- 7 Translucent Shader
	fn fixtureStandard name shader amb dif spec level gloss siAmount siColor useSIColor =
	(
		local s = StandardMaterial name:name
		s.shaderType = shader
		s.adLock = false
		s.diffuse = dif
		s.ambient = amb
		s.specular = spec
		s.specularLevel = level
		s.glossiness = gloss
		s.selfIllumAmount = siAmount
		s.selfIllumColor = siColor
		s.useSelfIllumColor = useSIColor
		s
	)

	fixtureBox "FixtureBlinnBox" 0 (fixtureStandard "FixtureBlinn" 1 \
		(color 12 22 32) (color 200 60 40) (color 220 210 200) 41.0 31.0 17.0 (color 30 90 200) true)
	fixtureBox "FixturePhongBox" 40 (fixtureStandard "FixturePhong" 5 \
		(color 13 23 33) (color 60 180 90) (color 210 220 230) 52.0 42.0 19.0 (color 200 30 90) false)
	fixtureBox "FixtureMetalBox" 80 (fixtureStandard "FixtureMetal" 2 \
		(color 14 24 34) (color 180 140 60) (color 240 230 200) 63.0 53.0 21.0 (color 90 200 30) true)
	fixtureBox "FixtureAnisotropicBox" 120 (fixtureStandard "FixtureAnisotropic" 0 \
		(color 15 25 35) (color 90 60 200) (color 190 200 210) 74.0 64.0 23.0 (color 40 160 220) false)
	fixtureBox "FixtureOrenNayarBlinnBox" 160 (fixtureStandard "FixtureOrenNayarBlinn" 4 \
		(color 16 26 36) (color 150 90 120) (color 230 220 210) 35.0 45.0 27.0 (color 220 120 40) true)

	local layered = fixtureStandard "FixtureMultiLayer" 3 \
		(color 17 27 37) (color 100 170 160) (color 200 190 180) 46.0 56.0 29.0 (color 160 40 220) false
	layered.specular2 = color 50 60 70
	layered.specularLevel2 = 88.0
	layered.glossiness2 = 77.0
	fixtureBox "FixtureMultiLayerBox" 200 layered

	local translucent = fixtureStandard "FixtureTranslucent" 7 \
		(color 18 28 38) (color 170 110 80) (color 215 225 235) 57.0 67.0 31.0 (color 30 220 160) true
	translucent.translucentColor = color 20 40 60
	fixtureBox "FixtureTranslucentBox" 240 translucent

	local strauss = StandardMaterial name:"FixtureStrauss"
	strauss.shaderType = 6
	strauss.diffuse = color 120 130 210
	strauss.glossiness = 37.0
	strauss.metalness = 48.0
	fixtureBox "FixtureStraussBox" 280 strauss

	-- The nine map slots of the Physical rule; offSlots: those switched off (all default on).
	fn fixturePhysicalMaps p prefix offSlots =
	(
		local slots = #(#base_color_map, #reflectivity_map, #roughness_map, #metalness_map, #transparency_map, \
			#emission_map, #emit_color_map, #bump_map, #cutout_map)
		local labels = #("Base", "Reflectivity", "Roughness", "Metalness", "Transparency", "Emission", "EmitColor", \
			"Bump", "Cutout")
		for k = 1 to slots.count do
		(
			local mapName = "FixturePhys" + prefix + labels[k] + "Map"
			local m = if mod k 2 == 1 then Checker name:mapName else Noise name:mapName
			setProperty p slots[k] m
			setProperty p ((slots[k] as string + "_on") as name) (findItem offSlots slots[k] == 0)
		)
	)

	local p = PhysicalMaterial name:"FixturePhysicalMaps"
	p.base_weight = 0.8
	p.base_color = color 200 100 50
	p.reflectivity = 0.7
	p.refl_color = color 210 200 190
	p.roughness = 0.35
	p.roughness_inv = true
	p.metalness = 0.25
	p.transparency = 0.2
	p.trans_color = color 60 120 180
	p.trans_ior = 1.4
	p.thin_walled = true
	p.emission = 0.6
	p.emit_color = color 220 180 140
	p.emit_luminance = 900.0
	p.coating = 0.45
	p.coat_color = color 230 200 170
	p.coat_roughness = 0.15
	p.coat_roughness_inv = true
	p.coat_ior = 1.7
	p.bump_map_amt = 0.55
	fixturePhysicalMaps p "Maps" #(#transparency_map, #emission_map)
	fixtureBox "FixturePhysicalMapsBox" 320 p

	local q = PhysicalMaterial name:"FixturePhysicalOff"
	q.base_weight = 0.9
	q.base_color = color 70 140 210
	q.reflectivity = 0.55
	q.refl_color = color 180 190 200
	q.roughness = 0.4
	q.metalness = 0.6
	q.transparency = 0.3
	q.trans_color = color 200 150 100
	q.trans_ior = 1.6
	q.emission = 0.4
	q.emit_color = color 100 150 250
	q.emit_luminance = 2400.0
	q.coating = 0.2
	q.coat_color = color 150 200 250
	q.coat_roughness = 0.3
	q.coat_ior = 1.55
	q.bump_map_amt = 0.8
	fixturePhysicalMaps q "Off" #(#base_color_map, #reflectivity_map, #roughness_map, #metalness_map, \
		#emit_color_map, #bump_map, #cutout_map)
	fixtureBox "FixturePhysicalOffBox" 360 q

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\standard_shaders.max" quiet:true
	"standard_shaders: " + (objects.count as string) + " object(s)"
)
