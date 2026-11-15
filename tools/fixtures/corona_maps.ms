-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Two Editable Poly boxes for the Corona maps. FixtureCoronaMaps (CoronaPhysicalMtl, glossiness mode): a
-- CoronaBitmap in base color with tiling, offset, W angle, map channel 2, U mirror, V tiling off and blur, at 75 %;
-- a glossiness CoronaBitmap with gamma 1.0 at 60 %; an opacity CoronaBitmap placed into a rectangle that gives
-- its alpha; a CoronaNormal (flip green, multiplier 0.8, an additional bump at 0.3) in bump at 90 %; a CoronaColor
-- in metalness; a CoronaMix (operation Mix) of a CoronaBitmap over a color by a CoronaBitmap mask in
-- self-illumination. FixtureCoronaLegacyMaps (CoronaLegacyMtl): a CoronaMix (Multiply) of two CoronaBitmaps in
-- diffuse; a CoronaMix (Add) of a CoronaBitmap in reflection; a CoronaBitmap in glossiness and one in bump at 50 %;
-- a CoronaColor in HDR mode in opacity; a CoronaBitmap in self-illumination with the slot switched off. The bitmaps
-- name files that do not exist, by a bare file name: a drive path would make the file fail the privacy check.
-- Needs Corona (12, the one this was authored with).
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
	fn cbmp name file = CoronaBitmap name:name filename:file

	local a = CoronaPhysicalMtl name:"FixtureCoronaMaps"
	a.baseColor = color 150 140 130
	a.roughnessMode = 1
	a.baseRoughness = 0.6
	local base = cbmp "FixtureCBase" "fixture_c_base.png"
	base.uvwScale = [2.0, 3.0, 1.0]
	base.uvwOffset = [0.1, 0.2, 0.0]
	base.wAngle = 30.0
	base.uvwChannel = 2
	base.tilingU = 2
	base.tilingV = 0
	base.filteringBlur = 0.8
	a.baseTexmap = base
	a.baseMapAmount = 75.0  -- percent in MAXScript, a fraction in the file
	local gloss = cbmp "FixtureCGloss" "fixture_c_gloss.png"
	gloss.gamma = 1.0
	a.baseRoughnessTexmap = gloss
	a.baseRoughnessMapAmount = 60.0
	local opa = cbmp "FixtureCOpacity" "fixture_c_opacity.png"
	opa.clippingOn = true
	opa.clippingMode = 1
	opa.clippingU = 0.1
	opa.clippingV = 0.2
	opa.clippingWidth = 0.5
	opa.clippingHeight = 0.6
	opa.monoChannelOutput = 1
	a.opacityTexmap = opa
	local nrm = CoronaNormal name:"FixtureCNormal"
	nrm.normalMap = cbmp "FixtureCNormalMap" "fixture_c_normal.png"
	nrm.multiplier = 0.8
	nrm.flipGreen = true
	nrm.additionalBump = cbmp "FixtureCNormalBump" "fixture_c_normal_bump.png"
	nrm.additionalBumpStrength = 0.3
	a.baseBumpTexmap = nrm
	a.baseBumpMapAmount = 0.9
	a.metalnessTexmap = CoronaColor name:"FixtureCColor" color:(color 100 150 200)
	local mix = CoronaMix name:"FixtureCMix"
	mix.mixOperation = 6
	mix.mixAmount = 0.4
	mix.texmapTop = cbmp "FixtureCMixTop" "fixture_c_top.png"
	mix.colorBottom = color 10 20 30
	mix.texmapMix = cbmp "FixtureCMixMask" "fixture_c_mask.png"
	a.selfIllumTexmap = mix
	a.selfIllumLevel = 1.0
	fixtureBox "FixtureCoronaMapsBox" 0 a

	local b = CoronaLegacyMtl name:"FixtureCoronaLegacyMaps"
	b.colorReflect = color 200 200 200
	b.levelReflect = 0.5
	local mul = CoronaMix name:"FixtureCMultiply"
	mul.mixOperation = 2
	mul.mixAmount = 1.0
	mul.texmapTop = cbmp "FixtureCMulTop" "fixture_c_mul_top.png"
	mul.texmapBottom = cbmp "FixtureCMulBottom" "fixture_c_mul_bottom.png"
	b.texmapDiffuse = mul
	local add = CoronaMix name:"FixtureCAdd"
	add.mixOperation = 0
	add.texmapTop = cbmp "FixtureCAddTop" "fixture_c_add_top.png"
	b.texmapReflect = add
	b.texmapReflectGlossiness = cbmp "FixtureCLegacyGloss" "fixture_c_legacy_gloss.png"
	b.texmapBump = cbmp "FixtureCLegacyBump" "fixture_c_legacy_bump.png"
	b.mapamountBump = 0.5
	local hdr = CoronaColor name:"FixtureCHdr"
	hdr.method = 1
	hdr.colorHdr = [0.25, 0.5, 0.75]
	b.texmapOpacity = hdr
	b.texmapSelfIllum = cbmp "FixtureCLegacyEmitOff" "fixture_c_emit_off.png"
	b.texmapOnSelfIllum = false
	b.colorSelfIllum = color 255 255 255
	b.levelSelfIllum = 1.0
	fixtureBox "FixtureCoronaLegacyMapsBox" 40 b

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\corona_maps.max" quiet:true
	"corona_maps: " + (objects.count as string) + " object(s)"
)
