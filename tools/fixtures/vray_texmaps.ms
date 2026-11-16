-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Ten Editable Poly boxes with a VRayMtl each, for V-Ray's own maps: VRayBitmap (VRayHDRI before V-Ray 5: the
-- same class) and VRayColor, and the wrappers above them.
-- FixtureVBDiffuse: a VRayBitmap in diffuse with its defaults (transfer function Auto), one with spherical mapping
-- in reflection. FixtureVBPlace: a VRayBitmap in diffuse with an overall multiplier of 1.5, a render multiplier of
-- 2, tiling 2 x 3, offset 0.1 / 0.2, W angle 30 and blur 0.8 in its own Placement; in reflection one with transfer
-- function None, in refraction one with Inverse gamma 2.0, in reflection glossiness one with sRGB, in opacity one
-- with mono output Alpha. FixtureVBBump: a VRayBitmap in bump at 50 %. FixtureVBNormal: a VRayNormalMap (normal
-- 0.9) over a VRayBitmap with transfer function None. FixtureVColor: a VRayColor in diffuse (200 100 50, RGB
-- multiplier 1.5) and one in reflection (128 gray, color gamma 2.2). FixtureVFalloff: a Falloff whose map 1 is a
-- VRayColor. FixtureCCColor: a Color Correction (saturation 20) over a VRayColor. FixtureCCComposite: a Color
-- Correction (brightness 10) over a Composite of two VRayBitmaps, the top one at 50 %. FixtureMixMask: a Mix of a
-- VRayBitmap and blue whose mask is a VRayColor. FixtureCCNoise: a Color Correction over a Noise (no bitmap below).
-- The maps name files that do not exist, by a bare file name: a drive path would make the file fail the privacy
-- check. Needs V-Ray (5.x, the one this was authored with).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	fn vbm name file = VRayBitmap name:name HDRIMapName:file
	fn vcolor name c = (local v = VRayColor name:name; v.color = c; v)
	fn fixtureBox name mtl x =
	(
		local b = Box name:name length:20 width:20 height:20 pos:[x,0,0] mapcoords:true
		b.material = mtl
		convertToPoly b
		b
	)

	local m1 = VRayMtl name:"FixtureVBDiffuse"
	m1.texmap_diffuse = vbm "FixtureVBDiffuseMap" "vtx_diffuse.png"
	local sphere = vbm "FixtureVBSphereMap" "vtx_sphere.png"
	sphere.maptype = 2
	m1.texmap_reflection = sphere
	fixtureBox "FixtureVBDiffuseBox" m1 0

	local m2 = VRayMtl name:"FixtureVBPlace"
	local place = vbm "FixtureVBPlaceMap" "vtx_place.png"
	place.multiplier = 1.5
	place.renderMultiplier = 2.0
	place.coords.U_Tiling = 2.0
	place.coords.V_Tiling = 3.0
	place.coords.U_Offset = 0.1
	place.coords.V_Offset = 0.2
	place.coords.W_Angle = 30.0
	place.coords.Blur = 0.8
	m2.texmap_diffuse = place
	local lin = vbm "FixtureVBLinearMap" "vtx_linear.png"
	lin.color_space = 0
	m2.texmap_reflection = lin
	local inv = vbm "FixtureVBInvGammaMap" "vtx_invgamma.png"
	inv.color_space = 1
	inv.gamma = 2.0
	m2.texmap_refraction = inv
	local srgb = vbm "FixtureVBGlossMap" "vtx_gloss.png"
	srgb.color_space = 2
	m2.texmap_reflectionGlossiness = srgb
	local alpha = vbm "FixtureVBAlphaMap" "vtx_alpha.png"
	alpha.monoOutput = 1
	m2.texmap_opacity = alpha
	fixtureBox "FixtureVBPlaceBox" m2 30

	local m3 = VRayMtl name:"FixtureVBBump"
	m3.texmap_bump = vbm "FixtureVBBumpMap" "vtx_bump.png"
	m3.texmap_bump_multiplier = 50.0
	fixtureBox "FixtureVBBumpBox" m3 60

	local m4 = VRayMtl name:"FixtureVBNormal"
	local nm = VRayNormalMap name:"FixtureVBNormalWrap"
	local nimg = vbm "FixtureVBNormalMap" "vtx_normal.png"
	nimg.color_space = 0
	nm.normal_map = nimg
	nm.normal_map_multiplier = 0.9
	m4.texmap_bump = nm
	m4.texmap_bump_multiplier = 100.0
	fixtureBox "FixtureVBNormalBox" m4 90

	local m5 = VRayMtl name:"FixtureVColor"
	local vc = vcolor "FixtureVColorDiffuse" (color 200 100 50)
	vc.rgb_multiplier = 1.5
	m5.texmap_diffuse = vc
	local vg = vcolor "FixtureVColorGamma" (color 128 128 128)
	vg.color_gamma = 2.2
	m5.texmap_reflection = vg
	fixtureBox "FixtureVColorBox" m5 120

	local m6 = VRayMtl name:"FixtureVFalloff"
	local fo = Falloff name:"FixtureVFalloffMap"
	fo.map1 = vcolor "FixtureVFalloffColor" (color 50 150 250)
	m6.texmap_diffuse = fo
	fixtureBox "FixtureVFalloffBox" m6 150

	local m7 = VRayMtl name:"FixtureCCColor"
	local cc1 = Color_Correction name:"FixtureCCColorMap"
	cc1.map = vcolor "FixtureCCColorInput" (color 100 200 50)
	cc1.saturation = 20.0
	m7.texmap_diffuse = cc1
	fixtureBox "FixtureCCColorBox" m7 180

	local m8 = VRayMtl name:"FixtureCCComposite"
	local comp = CompositeTexturemap()  -- its "name" parameter is the layer names: the map keeps its default name
	comp.mapList.count = 2
	comp.mapList[1] = vbm "FixtureCompLayerA" "vtx_layer_a.png"
	comp.mapList[2] = vbm "FixtureCompLayerB" "vtx_layer_b.png"
	comp.opacity[2] = 50.0
	local cc2 = Color_Correction name:"FixtureCCCompositeMap"
	cc2.map = comp
	cc2.brightness = 10.0
	m8.texmap_diffuse = cc2
	fixtureBox "FixtureCCCompositeBox" m8 210

	local m9 = VRayMtl name:"FixtureMixMask"
	local mx = Mix name:"FixtureMixMaskMap"
	mx.map1 = vbm "FixtureMixMaskA" "vtx_mix_a.png"
	mx.color2 = color 0 0 255
	mx.mask = vcolor "FixtureMixMaskColor" (color 64 64 64)
	m9.texmap_diffuse = mx
	fixtureBox "FixtureMixMaskBox" m9 240

	local m10 = VRayMtl name:"FixtureCCNoise"
	local cc3 = Color_Correction name:"FixtureCCNoiseMap"
	cc3.map = Noise name:"FixtureNoise"
	m10.texmap_diffuse = cc3
	fixtureBox "FixtureCCNoiseBox" m10 270

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\vray_texmaps.max" quiet:true
	"vray_texmaps: " + (objects.count as string) + " object(s)"
)
