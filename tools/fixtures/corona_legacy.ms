-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Three Editable Poly boxes with a CoronaLegacyMtl (CoronaMtl) each. FixtureCoronaLegacyPbr: PBR mode on, diffuse
-- and reflection levels, Fresnel IOR, self-illumination and opacity. FixtureCoronaLegacyGloss: PBR mode off,
-- refraction with its IOR in thin mode. FixtureCoronaLegacyMetal: Fresnel IOR 999 with a bright reflection, the way
-- a metal is made in this material. Needs Corona (12, the one this was authored with).
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

	local a = CoronaLegacyMtl name:"FixtureCoronaLegacyPbr"
	a.colorDiffuse = color 180 60 40
	a.levelDiffuse = 0.85
	a.colorReflect = color 220 220 220
	a.levelReflect = 0.6
	a.reflectGlossiness = 0.72
	a.fresnelIor = 1.6
	a.pbrMode = true
	a.colorSelfIllum = color 0 128 255
	a.levelSelfIllum = 1.5
	a.colorOpacity = color 230 230 230
	a.levelOpacity = 0.9
	fixtureBox "FixtureCoronaLegacyPbrBox" 0 a

	local b = CoronaLegacyMtl name:"FixtureCoronaLegacyGloss"
	b.colorDiffuse = color 90 110 130
	b.colorReflect = color 255 255 255
	b.levelReflect = 1.0
	b.reflectGlossiness = 0.4
	b.pbrMode = false
	b.colorRefract = color 200 230 255
	b.levelRefract = 0.75
	b.ior = 1.33
	b.thin = true
	fixtureBox "FixtureCoronaLegacyGlossBox" 40 b

	local c = CoronaLegacyMtl name:"FixtureCoronaLegacyMetal"
	c.colorDiffuse = color 20 20 20
	c.colorReflect = color 250 200 120
	c.levelReflect = 1.0
	c.reflectGlossiness = 0.9
	c.fresnelIor = 999.0
	fixtureBox "FixtureCoronaLegacyMetalBox" 80 c

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\corona_legacy.max" quiet:true
	"corona_legacy: " + (objects.count as string) + " object(s)"
)
