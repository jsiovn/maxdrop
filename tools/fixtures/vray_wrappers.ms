-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Four Editable Poly boxes, each with a material that wraps others: a VRay2SidedMtl (front and back VRayMtl), a
-- VRayBlendMtl (a base and two coats with their blend colors), a Shell Material (original and baked) and a
-- Multi/Sub-Object with material IDs 1, 3 and 7. Every VRayMtl inside has its own diffuse color and glossiness.
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

	local two = VRay2SidedMtl name:"FixtureTwoSided"
	two.frontMtl = fixtureVRay "FixtureFront" 210 20 20 0.61
	two.backMtl = fixtureVRay "FixtureBack" 20 210 20 0.62
	two.translucency = color 64 96 128
	two.force1SidedSubMtls = false
	fixtureBox "FixtureTwoSidedBox" 0 two

	local blend = VRayBlendMtl name:"FixtureBlend"
	blend.baseMtl = fixtureVRay "FixtureBlendBase" 20 20 210 0.63
	blend.coatMtl[1] = fixtureVRay "FixtureCoatA" 200 200 20 0.64
	blend.Blend[1] = color 40 50 60
	blend.coatMtl[2] = fixtureVRay "FixtureCoatB" 20 200 200 0.65
	blend.Blend[2] = color 70 80 90
	blend.additiveMode = true
	fixtureBox "FixtureBlendBox" 40 blend

	local shell = Shell_Material name:"FixtureShell"
	shell.originalMaterial = fixtureVRay "FixtureShellOriginal" 120 60 30 0.66
	shell.bakedMaterial = fixtureVRay "FixtureShellBaked" 30 60 120 0.67
	shell.viewportMtlIndex = 1
	shell.renderMtlIndex = 0
	fixtureBox "FixtureShellBox" 80 shell

	local multi = MultiMaterial name:"FixtureMulti" numsubs:3
	multi.materialIDList = #(1, 3, 7)
	multi.materialList[1] = fixtureVRay "FixtureSubOne" 250 10 130 0.68
	multi.materialList[2] = fixtureVRay "FixtureSubThree" 10 250 130 0.69
	multi.materialList[3] = fixtureVRay "FixtureSubSeven" 130 10 250 0.71
	multi.names = #("SlotOne", "SlotThree", "SlotSeven")
	multi.mapEnabled = #(true, false, true)
	fixtureBox "FixtureMultiBox" 120 multi

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\vray_wrappers.max" quiet:true
	"vray_wrappers: " + (objects.count as string) + " object(s)"
)
