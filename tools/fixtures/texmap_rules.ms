-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Three Editable Poly boxes with a VRayMtl each, for the texture-map rules. FixtureTexPeel has a map in each slot
-- that the rules peel to the Bitmap below it (Falloff, VRayDirt, Output, VRayColor2Bump, RGB Tint), a Falloff
-- without a map and one whose map is switched off. FixtureTexKeep has the wrappers kept as nodes (Mix, RGB
-- Multiply, Color Correction), a Normal Bump with a normal and an additional bump map, and a glossiness Bitmap
-- with a gamma override of 1.0. FixtureTexPlace has a Composite, a Bitmap with cropping, map channel 3, U mirror,
-- V tiling off, U / V / W angles and a gamma override of 2.2, a Bitmap in placement mode on the vertex color
-- channel, one with environment mapping, one with an inverted Output, and a CoronaNormal. The bitmaps name files
-- that do not exist, by a bare file name: a drive path would make the file fail the privacy check. Needs V-Ray
-- (5.x) and Corona (12), the ones this was authored with.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	makeDir @"C:\maxdrop_fixtures" all:true  -- gammaBmp saves its image there
	fn fixtureBitmap name file = Bitmaptexture name:name filename:file
	-- A gamma override is kept by the bitmap's info only when set through a loaded image: load a tiny one, then
	-- rename the file to a bare name (the override stays, the path goes).
	fn gammaBmp name file gamma =
	(
		local src = @"C:\maxdrop_fixtures\gamma_probe.png"
		if not doesFileExist src do (
			local b = bitmap 4 4 color:(color 128 128 128) filename:src
			save b
			close b
		)
		local t = Bitmaptexture name:name
		t.bitmap = openBitmap src gamma:gamma
		t.filename = file
		t
	)

	local m1 = VRayMtl name:"FixtureTexPeel"
	m1.diffuse = color 150 140 130
	local fo = Falloff name:"FixtureFalloff"
	fo.map1 = fixtureBitmap "FixturePeelDiffuse" "peel_diffuse.png"
	fo.color2 = color 10 20 30
	m1.texmap_diffuse = fo
	local dirt = VRayDirt name:"FixtureDirt"
	dirt.texmap_unoccluded_color = fixtureBitmap "FixturePeelReflect" "peel_reflect.png"
	m1.texmap_reflection = dirt
	m1.texmap_reflection_multiplier = 80.0
	local outMap = Output name:"FixtureOutput"
	outMap.map1 = fixtureBitmap "FixturePeelGloss" "peel_gloss.png"
	m1.texmap_reflectionGlossiness = outMap
	local c2b = VRayColor2Bump name:"FixtureColor2Bump"
	c2b.map = fixtureBitmap "FixturePeelHeight" "peel_height.png"
	m1.texmap_bump = c2b
	m1.texmap_bump_multiplier = 40.0
	local tint = RGB_Tint name:"FixtureTint"
	tint.map1 = fixtureBitmap "FixturePeelOpacity" "peel_opacity.png"
	m1.texmap_opacity = tint
	local foEmpty = Falloff name:"FixtureFalloffEmpty"
	foEmpty.color1 = color 200 100 50
	m1.texmap_metalness = foEmpty
	local foOff = Falloff name:"FixtureFalloffOff"
	foOff.map1 = fixtureBitmap "FixturePeelOffMap" "peel_off.png"
	foOff.map1On = false
	foOff.color1 = color 255 0 0
	m1.texmap_self_illumination = foOff
	local a = Box name:"FixturePeelBox" length:20 width:20 height:20 pos:[0,0,0] mapcoords:true
	a.material = m1
	convertToPoly a

	local m2 = VRayMtl name:"FixtureTexKeep"
	local mixMap = Mix name:"FixtureMix"
	mixMap.map1 = fixtureBitmap "FixtureMixA" "keep_mix_a.png"
	mixMap.map2 = fixtureBitmap "FixtureMixB" "keep_mix_b.png"
	mixMap.mask = fixtureBitmap "FixtureMixMask" "keep_mix_mask.png"
	mixMap.mixAmount = 30.0
	m2.texmap_diffuse = mixMap
	local mul = RGB_Multiply name:"FixtureMultiply"
	mul.map1 = fixtureBitmap "FixtureMulMap" "keep_mul.png"
	mul.color2 = color 200 150 100
	m2.texmap_reflection = mul
	local cc = Color_Correction name:"FixtureColorCorrect"
	cc.map = fixtureBitmap "FixtureCCMap" "keep_cc.png"
	cc.hueShift = 30.0
	cc.saturation = 20.0
	cc.brightness = 10.0
	cc.contrast = 5.0
	cc.lightnessMode = 1
	cc.gammaRGB = 1.2
	m2.texmap_self_illumination = cc
	local nb = Normal_Bump name:"FixtureNormalBump"
	nb.normal_map = fixtureBitmap "FixtureNBNormal" "keep_normal.png"
	nb.bump_map = fixtureBitmap "FixtureNBBump" "keep_nb_bump.png"
	nb.mult_spin = 0.8
	nb.bump_spin = 0.4
	nb.flipgreen = true
	m2.texmap_bump = nb
	m2.texmap_reflectionGlossiness = gammaBmp "FixtureLinearGloss" "keep_gloss.png" 1.0
	local b = Box name:"FixtureKeepBox" length:20 width:20 height:20 pos:[30,0,0] mapcoords:true
	b.material = m2
	convertToPoly b

	local m3 = VRayMtl name:"FixtureTexPlace"
	local comp = CompositeTexturemap()  -- its "name" parameter is the layer names: the map keeps its default name
	comp.mapList.count = 2
	comp.mapList[1] = fixtureBitmap "FixtureCompBase" "place_comp_a.png"
	comp.mapList[2] = fixtureBitmap "FixtureCompTop" "place_comp_b.png"
	comp.opacity[2] = 60.0
	m3.texmap_diffuse = comp
	local crop = gammaBmp "FixtureCropMap" "place_crop.png" 2.2
	crop.apply = true
	crop.cropPlace = 0
	crop.clipu = 0.1
	crop.clipv = 0.2
	crop.clipw = 0.5
	crop.cliph = 0.6
	crop.coords.mapChannel = 3
	crop.coords.U_Mirror = true
	crop.coords.V_Tile = false
	crop.coords.U_Angle = 10.0
	crop.coords.V_Angle = 20.0
	crop.coords.W_Angle = 30.0
	crop.coords.U_Tiling = 2.0
	crop.coords.V_Tiling = 3.0
	m3.texmap_reflection = crop
	local place = fixtureBitmap "FixturePlaceMap" "place_place.png"
	place.apply = true
	place.cropPlace = 1
	place.clipu = 0.25
	place.clipv = 0.25
	place.clipw = 0.5
	place.cliph = 0.5
	place.coords.mapping = 1
	m3.texmap_opacity = place
	local env = fixtureBitmap "FixtureEnvMap" "place_env.png"
	env.coords.mappingType = 1
	m3.texmap_self_illumination = env
	local inv = fixtureBitmap "FixtureInvertMap" "place_invert.png"
	inv.output.invert = true
	m3.texmap_metalness = inv
	local cn = CoronaNormal name:"FixtureCoronaNormal"
	cn.normalMap = fixtureBitmap "FixtureCNNormal" "place_cnormal.png"
	cn.multiplier = 0.9
	cn.flipGreen = true
	cn.additionalBump = fixtureBitmap "FixtureCNBump" "place_cbump.png"
	cn.additionalBumpOn = true
	cn.additionalBumpStrength = 0.5
	m3.texmap_bump = cn
	local c = Box name:"FixturePlaceBox" length:20 width:20 height:20 pos:[60,0,0] mapcoords:true
	c.material = m3
	convertToPoly c

	saveMaxFile @"C:\maxdrop_fixtures\texmap_rules.max" quiet:true
	"texmap_rules: " + (objects.count as string) + " object(s)"
)
