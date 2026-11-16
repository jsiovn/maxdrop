-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Three Editable Poly boxes, saved with the gamma ON (2.2; every other fixture was saved with it off): a VRayMtl
-- with 128 grey swatches, one whose diffuse is a Mix of two swatches and whose reflection is a VRayColor 128, and a
-- Standard with the diffuse of box_poly_standard. Needs V-Ray (5.x, the one this was authored with).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene and sets the Gamma/LUT
-- preferences, so run it in a 3ds Max session with nothing to keep, then sanitize and check the saved file before
-- it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #gamma
	IDisplayGamma.gamma = 2.2
	fileInGamma = 2.2
	fileOutGamma = 2.2

	local flat = VRayMtl name:"FixtureGammaFlat"
	flat.diffuse = color 128 128 128
	flat.reflection = color 64 64 64
	flat.selfIllumination = color 128 128 128

	local mx = Mix name:"FixtureGammaMix"
	mx.color1 = color 128 128 128
	mx.color2 = color 64 128 192
	mx.mixAmount = 25.0
	local vc = VRayColor name:"FixtureGammaVRayColor"
	vc.color = color 128 128 128
	local withMaps = VRayMtl name:"FixtureGammaMapped"
	withMaps.diffuse = color 10 20 30
	withMaps.texmap_diffuse = mx
	withMaps.reflection = color 0 0 0
	withMaps.texmap_reflection = vc

	local std = Standardmaterial name:"FixtureGammaStandard"
	std.diffuse = color 200 40 30

	local i = 0
	for m in #(flat, withMaps, std) do (
		local b = Box name:("FixtureGammaBox" + (i as string)) length:20 width:20 height:20 pos:[i * 30, 0, 0] mapcoords:true
		b.material = m
		convertToPoly b
		i += 1
	)
	saveMaxFile @"C:\maxdrop_fixtures\gamma_swatches.max" quiet:true
)
