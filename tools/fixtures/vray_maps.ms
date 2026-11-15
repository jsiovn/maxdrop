-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Two Editable Poly boxes with a VRayMtl each. FixtureVRayMaps has a Bitmap in diffuse, reflection, reflection
-- glossiness, bump and opacity, each with its own tiling, offset, angle and blur, and distinct map multipliers;
-- FixtureVRayNormal has a VRayNormalMap in bump, with a Bitmap as normal map and one as bump map. The bitmaps name
-- files that do not exist, by a bare file name: a drive path would make the file fail the privacy check.
-- Needs V-Ray (5.x, the one this was authored with).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	fn fixtureBitmap name file tile offset angle blur =
	(
		local t = Bitmaptexture name:name filename:file
		t.coords.U_Tiling = tile
		t.coords.V_Tiling = tile + 0.5
		t.coords.U_Offset = offset
		t.coords.V_Offset = offset + 0.05
		t.coords.W_Angle = angle
		t.coords.Blur = blur
		t
	)
	local m = VRayMtl name:"FixtureVRayMaps"
	m.diffuse = color 180 120 60
	m.texmap_diffuse = fixtureBitmap "FixtureDiffuseMap" "fixture_diffuse.png" 2.0 0.1 15.0 1.1
	m.texmap_diffuse_multiplier = 91.0
	m.texmap_reflection = fixtureBitmap "FixtureReflectMap" "fixture_reflect.png" 3.0 0.2 25.0 1.2
	m.texmap_reflection_multiplier = 82.0
	m.texmap_reflectionGlossiness = fixtureBitmap "FixtureGlossMap" "fixture_gloss.png" 4.0 0.3 35.0 1.3
	m.texmap_reflectionGlossiness_multiplier = 73.0
	m.texmap_bump = fixtureBitmap "FixtureBumpMap" "fixture_bump.png" 5.0 0.4 45.0 1.4
	m.texmap_bump_multiplier = 64.0
	m.texmap_opacity = fixtureBitmap "FixtureOpacityMap" "fixture_opacity.png" 6.0 0.5 55.0 1.5
	m.texmap_opacity_multiplier = 55.0
	local a = Box name:"FixtureMapsBox" length:20 width:20 height:20 pos:[0,0,0] mapcoords:true
	a.material = m
	convertToPoly a

	local n = VRayNormalMap name:"FixtureNormalWrap"
	n.normal_map = fixtureBitmap "FixtureNormalMap" "fixture_normal.png" 1.5 0.05 5.0 0.7
	n.normal_map_multiplier = 0.85
	n.bump_map = fixtureBitmap "FixtureNormalBumpMap" "fixture_normal_bump.png" 2.5 0.15 65.0 0.9
	n.bump_map_multiplier = 0.35
	n.flip_green = true
	local m2 = VRayMtl name:"FixtureVRayNormal"
	m2.diffuse = color 60 90 120
	m2.texmap_bump = n
	m2.texmap_bump_multiplier = 100.0
	local b = Box name:"FixtureNormalBox" length:20 width:20 height:20 pos:[40,0,0] mapcoords:true
	b.material = m2
	convertToPoly b

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\vray_maps.max" quiet:true
	"vray_maps: " + (objects.count as string) + " object(s)"
)
