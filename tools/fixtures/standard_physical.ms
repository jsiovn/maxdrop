-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Two Editable Poly boxes: a Standard material (Blinn) and a Physical Material, their value channels set to
-- distinct numbers, the Standard one with a Bitmap in diffuse.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local s = StandardMaterial name:"FixtureStandard"
	s.ambient = color 11 21 31
	s.diffuse = color 171 81 41
	s.specular = color 231 221 211
	s.specularLevel = 37.0
	s.glossiness = 23.0
	s.soften = 0.3
	s.selfIllumAmount = 13.0
	s.opacity = 83.0
	s.ior = 1.33
	s.twoSided = true
	s.diffuseMapAmount = 71.0
	s.diffuseMap = Bitmaptexture name:"FixtureStandardMap" filename:"fixture_standard.png"
	local a = Box name:"FixtureStandardBox" length:20 width:20 height:20 pos:[0,0,0] mapcoords:true
	a.material = s
	convertToPoly a

	local p = PhysicalMaterial name:"FixturePhysical"
	p.base_weight = 0.91
	p.base_color = color 0.71 0.31 0.11 1.0
	p.reflectivity = 0.81
	p.roughness = 0.27
	p.metalness = 0.43
	p.refl_color = color 0.9 0.8 0.7 1.0
	p.diff_roughness = 0.17
	p.trans_ior = 1.47
	p.transparency = 0.12
	p.trans_color = color 0.2 0.4 0.6 1.0
	p.emission = 0.05
	p.emit_color = color 0.6 0.5 0.4 1.0
	p.coating = 0.33
	p.coat_roughness = 0.21
	p.coat_ior = 1.61
	local b = Box name:"FixturePhysicalBox" length:20 width:20 height:20 pos:[40,0,0] mapcoords:true
	b.material = p
	convertToPoly b

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\standard_physical.max" quiet:true
	"standard_physical: " + (objects.count as string) + " object(s)"
)
