-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Animated parameters in ParamBlock2 blocks that also hold references of their own. FixtureAnimBlend: a
-- VRayBlendMtl with a base, two coats and a Checker as the first coat's blend map (block-held references), its
-- second blend color and first blend multiplier animated. FixtureAnimVRay: a VRayMtl with its diffuse color and
-- reflection glossiness animated, and as bump a VRayNormalMap with a Checker normal map, a Noise bump map and both
-- multipliers animated. Each animated value has keys at frames 0 and 50 and a frame-0 value of its own; the
-- controllers are made in reverse parameter order (the file keeps them in parameter order). Saved at frame 0.
-- Needs V-Ray (5.x, the one this was authored with).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)
	sliderTime = 0
	fn fixtureVRay name r g b = VRayMtl name:name diffuse:(color r g b)
	fn fixtureBox name x mat =
	(
		local o = Box name:name length:20 width:20 height:20 pos:[x,0,0] mapcoords:true
		o.material = mat
		convertToPoly o
		o
	)

	local blend = VRayBlendMtl name:"FixtureAnimBlend"
	blend.baseMtl = fixtureVRay "FixtureAnimBase" 20 20 210
	blend.coatMtl[1] = fixtureVRay "FixtureAnimCoatA" 200 200 20
	blend.coatMtl[2] = fixtureVRay "FixtureAnimCoatB" 20 200 200
	blend.texmap_blend[1] = Checker name:"FixtureAnimBlendMap"
	blend.blend[1] = color 40 50 60
	blend.blend[2] = color 70 80 90
	blend.texmap_blend_multiplier[1] = 37.0
	with animate on at time 50 blend.texmap_blend_multiplier[1] = 81.0
	with animate on at time 50 blend.blend[2] = color 200 10 10
	fixtureBox "FixtureAnimBlendBox" 0 blend

	local normal = VRayNormalMap name:"FixtureAnimNormal"
	normal.normal_map = Checker name:"FixtureAnimNormalMap"
	normal.bump_map = Noise name:"FixtureAnimBumpMap"
	normal.normal_map_multiplier = 0.55
	normal.bump_map_multiplier = 0.35
	with animate on at time 50 normal.bump_map_multiplier = 0.15
	with animate on at time 50 normal.normal_map_multiplier = 0.95

	local vray = VRayMtl name:"FixtureAnimVRay"
	vray.diffuse = color 10 20 30
	vray.reflection_glossiness = 0.41
	vray.texmap_bump = normal
	with animate on at time 50 vray.reflection_glossiness = 0.9
	with animate on at time 50 vray.diffuse = color 250 250 0
	fixtureBox "FixtureAnimVRayBox" 40 vray

	sliderTime = 0
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\pblock_animated.max" quiet:true
	"pblock_animated: " + (objects.count as string) + " object(s)"
)
