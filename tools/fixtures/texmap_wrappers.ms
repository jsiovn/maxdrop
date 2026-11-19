-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Four Editable Poly boxes with a VRayMtl each, for the wrapper maps drawn as node graphs (maxdrop-3gc.3).
-- FixtureWrapFalloff: in diffuse a Falloff perpendicular / parallel (the default) whose map 1 is a Bitmap at 60 %
-- over color 1 (200 0 0), color 2 (0 0 255); in reflection a Fresnel Falloff at IOR 1.45; in self-illumination a
-- towards / away Falloff; in opacity a Falloff in the local X direction over a Bitmap and in reflection glossiness
-- a shadow / light one (both peeled).
-- FixtureWrapComposite: in diffuse a Composite of four Bitmaps: the base, one in multiply at 50 %, one in overlay
-- masked by a Falloff, one in screen at 70 %; in reflection one with a soft light layer (peeled); in
-- self-illumination one with a spotlight blend layer masked by a Bitmap.
-- FixtureWrapColor: Color Corrections over Bitmaps: monochrome in diffuse, invert with brightness 20 in reflection,
-- custom rewiring (blue, inverse red, monochrome) in self-illumination.
-- FixtureWrapOutput: in diffuse an Output map (level 2, offset 0.1, amount 0.5, inverted) over a Bitmap; in
-- reflection an RGB Tint (red 255 128 0) over a Bitmap; in self-illumination an Output with its defaults.
-- The bitmaps name files that do not exist, by a bare file name: a drive path would make the file fail the privacy
-- check. Needs V-Ray (5.x, the one this was authored with).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	fn fixtureBitmap name file = Bitmaptexture name:name filename:file
	fn fixtureBox name mtl x =
	(
		local b = Box name:name length:20 width:20 height:20 pos:[x,0,0] mapcoords:true
		b.material = mtl
		convertToPoly b
		b
	)

	local m1 = VRayMtl name:"FixtureWrapFalloff"
	local fo = Falloff name:"FixtureFoPerp"
	fo.map1 = fixtureBitmap "FixtureFoMap" "wrap_fo_map.png"
	fo.map1Amount = 60.0
	fo.color1 = color 200 0 0
	fo.color2 = color 0 0 255
	m1.texmap_diffuse = fo
	local fr = Falloff name:"FixtureFoFresnel"
	fr.type = 2
	fr.mtlIOROverride = true
	fr.ior = 1.45
	m1.texmap_reflection = fr
	local tw = Falloff name:"FixtureFoTowards"
	tw.type = 0
	tw.color1 = color 255 255 255
	tw.color2 = color 0 0 0
	m1.texmap_self_illumination = tw
	local dir = Falloff name:"FixtureFoLocalX"
	dir.direction = 1
	dir.map1 = fixtureBitmap "FixtureFoDirMap" "wrap_fo_dir.png"
	m1.texmap_opacity = dir
	local sl = Falloff name:"FixtureFoShadow"
	sl.type = 3
	sl.color1 = color 100 100 100
	m1.texmap_reflectionGlossiness = sl
	fixtureBox "FixtureWrapFalloffBox" m1 0

	local m2 = VRayMtl name:"FixtureWrapComposite"
	-- name: as a constructor keyword it is the layer names; assigned afterwards it is the map's name
	local comp = CompositeTexturemap()
	comp.name = "FixtureComposite"
	comp.mapList.count = 4
	comp.mapList[1] = fixtureBitmap "FixtureCompBase" "wrap_comp_base.png"
	comp.mapList[2] = fixtureBitmap "FixtureCompMul" "wrap_comp_mul.png"
	comp.mapList[3] = fixtureBitmap "FixtureCompOver" "wrap_comp_over.png"
	comp.mapList[4] = fixtureBitmap "FixtureCompScreen" "wrap_comp_screen.png"
	comp.blendMode[2] = 5
	comp.opacity[2] = 50.0
	comp.blendMode[3] = 14
	comp.Mask[3] = Falloff name:"FixtureCompMask"
	comp.blendMode[4] = 9
	comp.opacity[4] = 70.0
	m2.texmap_diffuse = comp
	local soft = CompositeTexturemap()
	soft.name = "FixtureCompSoft"
	soft.mapList.count = 2
	soft.mapList[1] = fixtureBitmap "FixtureSoftBase" "wrap_soft_base.png"
	soft.mapList[2] = fixtureBitmap "FixtureSoftTop" "wrap_soft_top.png"
	soft.blendMode[2] = 15
	m2.texmap_reflection = soft
	local spot = CompositeTexturemap()
	spot.name = "FixtureCompSpot"
	spot.mapList.count = 2
	spot.mapList[1] = fixtureBitmap "FixtureSpotBase" "wrap_spot_base.png"
	spot.mapList[2] = fixtureBitmap "FixtureSpotTop" "wrap_spot_top.png"
	spot.blendMode[2] = 13
	spot.Mask[2] = fixtureBitmap "FixtureSpotMask" "wrap_spot_mask.png"
	m2.texmap_self_illumination = spot
	fixtureBox "FixtureWrapCompositeBox" m2 30

	local m3 = VRayMtl name:"FixtureWrapColor"
	local mono = Color_Correction name:"FixtureCCMono"
	mono.map = fixtureBitmap "FixtureCCMonoMap" "wrap_cc_mono.png"
	mono.rewireMode = 1
	m3.texmap_diffuse = mono
	local inv = Color_Correction name:"FixtureCCInvert"
	inv.map = fixtureBitmap "FixtureCCInvertMap" "wrap_cc_invert.png"
	inv.rewireMode = 2
	inv.brightness = 20.0
	m3.texmap_reflection = inv
	local custom = Color_Correction name:"FixtureCCCustom"
	custom.map = fixtureBitmap "FixtureCCCustomMap" "wrap_cc_custom.png"
	custom.rewireMode = 3
	custom.rewireR = 2
	custom.rewireG = 4
	custom.rewireB = 8
	m3.texmap_self_illumination = custom
	fixtureBox "FixtureWrapColorBox" m3 60

	local m4 = VRayMtl name:"FixtureWrapOutput"
	local out = Output name:"FixtureOutLevels"
	out.map1 = fixtureBitmap "FixtureOutMap" "wrap_out.png"
	out.output.RGB_Level = 2.0
	out.output.RGB_Offset = 0.1
	out.output.output_amount = 0.5
	out.output.invert = true
	m4.texmap_diffuse = out
	local tint = RGB_Tint name:"FixtureTint"
	tint.map1 = fixtureBitmap "FixtureTintMap" "wrap_tint.png"
	tint.red = color 255 128 0
	m4.texmap_reflection = tint
	local plain = Output name:"FixtureOutPlain"
	plain.map1 = fixtureBitmap "FixtureOutPlainMap" "wrap_out_plain.png"
	m4.texmap_self_illumination = plain
	fixtureBox "FixtureWrapOutputBox" m4 90

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\texmap_wrappers.max" quiet:true
	"texmap_wrappers: " + (objects.count as string) + " object(s)"
)
