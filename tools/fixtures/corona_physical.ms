-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Five Editable Poly boxes with a CoronaPhysicalMtl each. FixtureCoronaPhysRough: roughness mode, a dielectric
-- with base level, IOR, clearcoat (amount, IOR, roughness, absorption color), self-illumination and opacity.
-- FixtureCoronaPhysGloss: glossiness mode, metal, a clearcoat. FixtureCoronaPhysGlass: refraction in thin mode
-- with a thin absorption color. FixtureCoronaPhysSpec: IOR mode 1 (specular levels in the base and clearcoat IORs).
-- FixtureCoronaPhysTranslThin: translucency in thin mode. Needs Corona (12, the one this was authored with).
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

	local a = CoronaPhysicalMtl name:"FixtureCoronaPhysRough"
	a.baseColor = color 200 120 60
	a.baseLevel = 0.9
	a.roughnessMode = 0
	a.baseRoughness = 0.35
	a.metalnessMode = 0
	a.baseIor = 1.45
	a.clearcoatAmount = 0.4
	a.clearcoatIor = 1.6
	a.clearcoatRoughness = 0.2
	a.clearcoatAbsorptionColor = color 230 210 190
	a.selfIllumColor = color 255 128 0
	a.selfIllumLevel = 2.5
	a.opacityColor = color 200 200 200
	a.opacityLevel = 0.8
	fixtureBox "FixtureCoronaPhysRoughBox" 0 a

	local b = CoronaPhysicalMtl name:"FixtureCoronaPhysGloss"
	b.baseColor = color 220 180 90
	b.roughnessMode = 1
	b.baseRoughness = 0.7
	b.metalnessMode = 1
	b.clearcoatAmount = 0.5
	b.clearcoatRoughness = 0.9
	fixtureBox "FixtureCoronaPhysGlossBox" 40 b

	local c = CoronaPhysicalMtl name:"FixtureCoronaPhysGlass"
	c.baseColor = color 40 40 40
	c.refractionAmount = 0.9
	c.useThinMode = true
	c.thinAbsorptionColor = color 150 200 255
	c.baseIor = 1.52
	c.baseRoughness = 0.05
	fixtureBox "FixtureCoronaPhysGlassBox" 80 c

	-- IOR mode 1 (specular levels in the IOR parameters): set before the values, which its setter converts
	local d = CoronaPhysicalMtl name:"FixtureCoronaPhysSpec"
	d.baseColor = color 150 150 150
	d.iorMode = 1
	d.baseIor = 1.2
	d.clearcoatAmount = 0.5
	d.clearcoatIor = 0.8
	fixtureBox "FixtureCoronaPhysSpecBox" 120 d

	local e = CoronaPhysicalMtl name:"FixtureCoronaPhysTranslThin"
	e.baseColor = color 120 200 90
	e.useThinMode = true
	e.translucencyFraction = 0.4
	e.translucencyColor = color 200 255 120
	fixtureBox "FixtureCoronaPhysTranslThinBox" 160 e

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\corona_physical.max" quiet:true
	"corona_physical: " + (objects.count as string) + " object(s)"
)
