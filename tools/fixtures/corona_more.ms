-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Editable Poly boxes with the Corona materials and parameters corona_physical / corona_legacy / corona_layered
-- leave out: CoronaPhysicalMtl SSS, sheen (a CoronaColor in its amount slot), translucency, volumetric absorption
-- and scattering, a metal edge color, a complex IOR, an IOR mode other than the default; CoronaLegacyMtl SSS, and
-- with PBR mode off translucency and absorption; a CoronaLayeredMtl with three layers (one masked by a CoronaColor
-- at half mask amount, one switched off); CoronaSkinMtl, CoronaHairMtl, CoronaRaySwitchMtl, CoronaSelectMtl.
-- No file paths. Needs Corona (12, the one this was authored with).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local x = 0
	fn fixtureBox name x mat =
	(
		local o = Box name:name length:20 width:20 height:20 pos:[x,0,0] mapcoords:true
		o.material = mat
		convertToPoly o
		o
	)
	fn phys name col = CoronaPhysicalMtl name:name baseColor:col

	local m = phys "FixtureCoronaPhysSss" (color 230 190 170)
	m.sssAmount = 0.6
	m.sssRadius = 2.5
	m.sssScatterColor = color 220 80 50
	fixtureBox "FixtureCoronaPhysSssBox" x m; x += 40

	m = phys "FixtureCoronaPhysSheen" (color 60 40 120)
	m.sheenAmount = 0.7
	m.sheenColor = color 250 200 230
	m.sheenRoughness = 0.4
	m.sheenAmountTexmap = CoronaColor name:"FixtureCSheenAmount" color:(color 128 128 128)
	fixtureBox "FixtureCoronaPhysSheenBox" x m; x += 40

	m = phys "FixtureCoronaPhysTransl" (color 120 200 90)
	m.translucencyFraction = 0.3
	m.translucencyColor = color 200 255 120
	fixtureBox "FixtureCoronaPhysTranslBox" x m; x += 40

	m = phys "FixtureCoronaPhysAbsorb" (color 255 255 255)
	m.refractionAmount = 1.0
	m.baseRoughness = 0.0
	m.volumetricAbsorptionColor = color 100 180 255
	m.attenuationDistance = 5.0
	m.volumetricScatteringColor = color 40 40 40
	fixtureBox "FixtureCoronaPhysAbsorbBox" x m; x += 40

	m = phys "FixtureCoronaPhysEdge" (color 250 200 120)
	m.metalnessMode = 1
	m.baseRoughness = 0.25
	m.edgeColor = color 255 240 200
	fixtureBox "FixtureCoronaPhysEdgeBox" x m; x += 40

	m = phys "FixtureCoronaPhysComplex" (color 128 128 128)
	m.metalnessMode = 1
	m.baseRoughness = 0.3
	m.useComplexIor = true
	m.complexIorNRed = 0.2
	m.complexIorNGreen = 0.9
	m.complexIorNBlue = 1.1
	m.complexIorKRed = 3.9
	m.complexIorKGreen = 2.4
	m.complexIorKBlue = 2.2
	fixtureBox "FixtureCoronaPhysComplexBox" x m; x += 40

	m = phys "FixtureCoronaPhysIorMode" (color 128 128 128)
	m.iorMode = 1
	fixtureBox "FixtureCoronaPhysIorModeBox" x m; x += 40

	m = CoronaLegacyMtl name:"FixtureCoronaLegacySss" colorDiffuse:(color 210 170 150)
	m.levelSss = 0.8
	m.sssRadius = 1.5
	m.sssScatterColor = color 200 60 40
	fixtureBox "FixtureCoronaLegacySssBox" x m; x += 40

	m = CoronaLegacyMtl name:"FixtureCoronaLegacyNoPbr" colorDiffuse:(color 100 120 140)
	m.pbrMode = false
	m.levelReflect = 0.7
	m.reflectGlossiness = 0.6
	m.levelRefract = 0.5
	m.absorptionDistance = 3.0
	m.absorptionColor = color 90 150 60
	m.levelTranslucency = 0.4
	m.colorTranslucency = color 255 220 160
	fixtureBox "FixtureCoronaLegacyNoPbrBox" x m; x += 40

	m = CoronaLayeredMtl name:"FixtureCoronaLayers"
	m.baseMtl = phys "FixtureCoronaLayersBase" (color 90 160 70)
	m.layers[1] = phys "FixtureCoronaLayersOne" (color 240 240 240)
	m.amounts[1] = 30.0  -- percent in MAXScript, a fraction in the file
	m.layers[2] = CoronaLegacyMtl name:"FixtureCoronaLayersTwo" colorDiffuse:(color 200 60 40)
	m.amounts[2] = 60.0
	m.mixmaps[2] = CoronaColor name:"FixtureCLayersMask" color:(color 64 64 64)
	m.maskAmounts[2] = 50.0
	m.layers[3] = phys "FixtureCoronaLayersOff" (color 10 10 200)
	m.layersOn[3] = false
	fixtureBox "FixtureCoronaLayersBox" x m; x += 40

	m = CoronaSkinMtl name:"FixtureCoronaSkin"
	m.skinColor = color 200 150 120
	m.skinLevel = 0.9
	m.sssAmount = 0.8
	m.sssRadiusScale = 2.0
	m.reflection1Level = 0.6
	m.reflection1Glossiness = 0.7
	m.reflection1Ior = 1.45
	m.opacityLevel = 0.9
	fixtureBox "FixtureCoronaSkinBox" x m; x += 40

	m = CoronaHairMtl name:"FixtureCoronaHair"
	fixtureBox "FixtureCoronaHairBox" x m; x += 40

	m = CoronaRaySwitchMtl name:"FixtureCoronaRaySwitch"
	m.giMtl = phys "FixtureCoronaRaySwitchGi" (color 255 0 0)
	m.directMtl = phys "FixtureCoronaRaySwitchDirect" (color 0 0 255)
	fixtureBox "FixtureCoronaRaySwitchBox" x m; x += 40

	m = CoronaSelectMtl name:"FixtureCoronaSelect"
	m.mtlCount = 3
	m.materials[1] = phys "FixtureCoronaSelectA" (color 255 255 0)
	m.materials[2] = phys "FixtureCoronaSelectB" (color 0 255 255)
	m.materials[3] = phys "FixtureCoronaSelectC" (color 255 0 255)
	m.selected = 1
	fixtureBox "FixtureCoronaSelectBox" x m; x += 40

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\corona_more.max" quiet:true
	"corona_more: " + (objects.count as string) + " object(s)"
)
