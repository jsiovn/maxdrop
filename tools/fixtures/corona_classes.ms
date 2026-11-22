-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Editable Poly boxes with the Corona material classes corona_more leaves out or holds only at their defaults:
-- CoronaHairMtl with every parameter MaxDrop reads set (a CoronaColor tint map at half amount, a CoronaColor melanin
-- map), CoronaVolumeMtl, CoronaShadowCatcherMtl (defaults; and with a reflection and a backplate map), CoronaScannedMtl
-- (no file), CoronaSlicerMtl, and a Multi/Sub-Object of a shadow catcher and a CoronaPhysicalMtl on one box.
-- CoronaPortalMtl is not creatable. No file paths. Needs Corona (12, the one this was authored with).
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

	local m = CoronaHairMtl name:"FixtureCoronaHairSet"
	m.melanin = 0.3
	m.pheomelanin = 0.6
	m.colorTint = color 230 200 180
	m.levelTint = 0.9
	m.colorDiffuse = color 40 30 20
	m.levelDiffuse = 0.5
	m.colorOpacity = color 200 200 200
	m.levelOpacity = 0.8
	m.ior = 1.6
	m.glossiness = 0.7
	m.texmapTint = CoronaColor name:"FixtureCHairTint" color:(color 128 64 32)
	m.mapamountTint = 50.0  -- percent in MAXScript, a fraction in the file
	m.texmapMelanin = CoronaColor name:"FixtureCHairMelanin" color:(color 100 100 100)
	fixtureBox "FixtureCoronaHairSetBox" x m; x += 40

	m = CoronaVolumeMtl name:"FixtureCoronaVolume"
	m.absorptionColor = color 200 150 100
	m.absorptionDist = 10.0
	m.scatteringColor = color 120 120 120
	m.scatteringDirectionality = 0.3
	m.emissionColor = color 255 128 0
	m.emissionDist = 5.0
	fixtureBox "FixtureCoronaVolumeBox" x m; x += 40

	m = CoronaShadowCatcherMtl name:"FixtureCoronaShadowCatcher"
	fixtureBox "FixtureCoronaShadowCatcherBox" x m; x += 40

	m = CoronaShadowCatcherMtl name:"FixtureCoronaShadowCatcherRefl"
	m.reflectLevel = 0.5
	m.backplateTexmap = CoronaColor name:"FixtureCCatcherBackplate" color:(color 90 140 200)
	fixtureBox "FixtureCoronaShadowCatcherReflBox" x m; x += 40

	m = CoronaScannedMtl name:"FixtureCoronaScanned"
	fixtureBox "FixtureCoronaScannedBox" x m; x += 40

	m = CoronaSlicerMtl name:"FixtureCoronaSlicer"
	fixtureBox "FixtureCoronaSlicerBox" x m; x += 40

	m = Multimaterial name:"FixtureCoronaCatcherMixed" numsubs:2
	m.materialList[1] = CoronaShadowCatcherMtl name:"FixtureCoronaCatcherMixedCatcher"
	m.materialList[2] = CoronaPhysicalMtl name:"FixtureCoronaCatcherMixedPhys" baseColor:(color 200 40 40)
	fixtureBox "FixtureCoronaCatcherMixedBox" x m; x += 40

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\corona_classes.max" quiet:true
	"corona_classes: " + (objects.count as string) + " object(s)"
)
