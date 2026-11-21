-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Eight Editable Poly boxes, one per material class MaxDrop has a rule for: VRayLightMtl, VRayFastSSS2,
-- VRayCarPaintMtl, VRayCarPaintMtl2, VRayOverrideMtl, VRayMtlWrapper, DoubleSided and Shellac. Every parameter a
-- rule reads has its own value, away from the class default (a scatter radius times scale unlike both factors),
-- as do the unread look-alikes beside them (scatter, overall and flake colors); Checker and Noise maps sit in the
-- map slots, one switched off in the light, FastSSS2 and CarPaint2 materials, the map multipliers away from their
-- defaults.
-- Each wrapper slot holds its own VRayMtl (diffuse and glossiness).
-- Needs V-Ray (5.x, the one this was authored with).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	fn fixtureVRay name r g b gloss = VRayMtl name:name diffuse:(color r g b) reflection_glossiness:gloss
	fn fixtureBox name x mat =
	(
		local o = Box name:name length:20 width:20 height:20 pos:[x,0,0] mapcoords:true
		o.material = mat
		convertToPoly o
		o
	)

	local light = VRayLightMtl name:"FixtureLightMtl"
	light.color = color 250 120 30
	light.multiplier = 3.7
	light.texmap = Checker name:"FixtureLightMap"
	light.texmap_on = true
	light.opacity_texmap = Noise name:"FixtureLightOpacityMap"
	light.opacity_texmap_on = false
	light.displacement_texmap = Checker name:"FixtureLightDisplaceMap"
	fixtureBox "FixtureLightMtlBox" 0 light

	local sss = VRayFastSSS2 name:"FixtureFastSSS2"
	sss.diffuse_color = color 180 120 90
	sss.texmap_diffuse_color = Checker name:"FixtureSSSDiffuseMap"
	sss.texmap_diffuse_color_multiplier = 71.0
	sss.diffuse_amount = 0.35
	sss.sub_surface_color = color 220 90 70
	sss.scatter_color = color 60 200 100
	sss.overall_color = color 240 235 225
	sss.scatter_radius = 3.0
	sss.scale = 0.7
	sss.IOR = 1.45
	sss.specular_color = color 200 210 220
	sss.specular_amount = 0.8
	sss.specular_glossiness = 0.72
	sss.texmap_bump = Noise name:"FixtureSSSBumpMap"
	sss.texmap_bump_multiplier = 47.0
	sss.texmap_opacity = Checker name:"FixtureSSSOpacityMap"
	sss.texmap_opacity_on = false
	sss.texmap_opacity_multiplier = 83.0
	fixtureBox "FixtureFastSSS2Box" 40 sss

	local paint = VRayCarPaintMtl name:"FixtureCarPaint"
	paint.base_color = color 150 20 30
	paint.texmap_base_color = Checker name:"FixtureCarPaintColorMap"
	paint.texmap_base_color_multiplier = 66.0
	paint.base_reflection = 0.45
	paint.base_glossiness = 0.77
	paint.flake_color = color 90 200 60
	paint.flake_glossiness = 0.55
	paint.coat_color = color 240 230 220
	paint.coat_strength = 0.09
	paint.coat_glossiness = 0.93
	paint.texmap_base_bump = Noise name:"FixtureCarPaintBumpMap"
	paint.texmap_base_bump_multiplier = 44.0
	fixtureBox "FixtureCarPaintBox" 80 paint

	local paint2 = VRayCarPaintMtl2 name:"FixtureCarPaint2"
	paint2.base_color = color 20 60 150
	paint2.texmap_base_color = Checker name:"FixtureCarPaint2ColorMap"
	paint2.texmap_base_color_on = false
	paint2.texmap_base_color_multiplier = 58.0
	paint2.base_reflection = 0.35
	paint2.base_glossiness = 0.66
	paint2.flake_color = color 200 180 40
	paint2.flake_glossiness = 0.61
	paint2.coat_color = color 230 240 250
	paint2.coat_amount = 0.82
	paint2.coat_ior = 1.62
	paint2.coat_glossiness = 0.88
	paint2.texmap_base_bump = Noise name:"FixtureCarPaint2BumpMap"
	paint2.texmap_base_bump_multiplier = 39.0
	fixtureBox "FixtureCarPaint2Box" 120 paint2

	local override = VRayOverrideMtl name:"FixtureOverride"
	override.baseMtl = fixtureVRay "FixtureOverrideBase" 200 40 40 0.51
	override.giMtl = fixtureVRay "FixtureOverrideGI" 40 200 40 0.52
	override.reflectMtl = fixtureVRay "FixtureOverrideReflect" 40 40 200 0.53
	override.refractMtl = fixtureVRay "FixtureOverrideRefract" 200 200 40 0.54
	override.shadowMtl = fixtureVRay "FixtureOverrideShadow" 40 200 200 0.55
	fixtureBox "FixtureOverrideBox" 160 override

	local wrapper = VRayMtlWrapper name:"FixtureMtlWrapper"
	wrapper.baseMtl = fixtureVRay "FixtureWrapperBase" 160 90 200 0.56
	wrapper.generateGIMult = 0.7
	fixtureBox "FixtureMtlWrapperBox" 200 wrapper

	local two = DoubleSided name:"FixtureDoubleSided"
	two.material1 = fixtureVRay "FixtureFacing" 210 150 60 0.57
	two.material2 = fixtureVRay "FixtureBackFacing" 60 150 210 0.58
	two.translucency = 23.0
	fixtureBox "FixtureDoubleSidedBox" 240 two

	local coated = Shellac name:"FixtureShellac"
	coated.shellacMtl1 = fixtureVRay "FixtureShellacBase" 120 200 160 0.59
	coated.shellacMtl2 = fixtureVRay "FixtureShellacCoat" 250 250 250 0.74
	coated.shellacColorBlend = 37.0
	fixtureBox "FixtureShellacBox" 280 coated

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\vray_more.max" quiet:true
	"vray_more: " + (objects.count as string) + " object(s)"
)
