-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- One Editable Poly box with a VRayMtl whose value channels are set to distinct numbers, so that a parameter read
-- under the wrong id cannot pass for the right one. Needs V-Ray (5.x, the one this was authored with).
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local m = VRayMtl name:"FixtureVRay"
	m.diffuse = color 201 31 41
	m.diffuse_roughness = 0.11
	m.selfIllumination = color 12 22 32
	m.selfIllumination_gi = false
	m.selfIllumination_multiplier = 1.7
	m.compensate_camera_exposure = true
	m.reflection = color 151 162 173
	m.reflection_glossiness = 0.83
	m.reflection_lockGlossiness = false
	m.hilight_glossiness = 0.77
	m.reflection_subdivs = 9
	m.reflection_fresnel = false
	m.reflection_maxDepth = 6
	m.reflection_exitColor = color 5 15 25
	m.reflection_lockIOR = false
	m.reflection_ior = 1.73
	m.reflection_metalness = 0.37
	m.reflection_dimDistance_on = true
	m.reflection_dimDistance = 43.5
	m.reflection_dimDistance_falloff = 0.19
	m.reflection_affectAlpha = 2
	m.refraction = color 61 71 81
	m.refraction_glossiness = 0.91
	m.refraction_subdivs = 7
	m.refraction_ior = 1.61
	m.refraction_fogColor = color 211 221 231
	m.refraction_fogMult = 0.47
	m.refraction_fogBias = 0.13
	m.refraction_affectShadows = true
	m.refraction_affectAlpha = 1
	m.refraction_maxDepth = 4
	m.refraction_exitColor = color 33 44 55
	m.refraction_useExitColor = true
	m.refraction_dispersion_on = true
	m.refraction_dispersion = 31.0
	m.refraction_thinWalled = true
	m.translucency_on = 3
	m.translucency_thickness = 77.0
	m.translucency_scatterCoeff = 0.23
	m.translucency_fbCoeff = 0.59
	m.translucency_multiplier = 0.81
	m.translucency_color = color 91 92 93
	m.sheen_color = color 101 111 121
	m.sheen_glossiness = 0.63
	m.coat_amount = 0.29
	m.coat_color = color 131 141 151
	m.coat_glossiness = 0.67
	m.coat_ior = 1.57
	m.coat_bump_lock = false
	m.bump_multiplier = 0.41
	m.brdf_type = 4
	m.anisotropy = 0.21
	m.anisotropy_rotation = 33.0
	m.anisotropy_axis = 1
	m.soften = 0.017
	m.gtr_gamma = 2.3
	m.brdf_useRoughness = true
	m.option_traceReflection = false
	m.option_doubleSided = false
	m.option_cutOff = 0.0123
	m.option_environment_priority = 3
	m.effect_id = 5
	m.override_effect_id = true
	m.option_opacityMode = 1
	m.texmap_diffuse_multiplier = 63.0
	m.texmap_reflection_multiplier = 57.0
	m.texmap_bump_multiplier = 41.0
	m.texmap_opacity_multiplier = 87.0
	m.texmap_reflectionGlossiness_multiplier = 69.0
	m.texmap_refraction_on = false
	local b = Box name:"FixtureVRayBox" length:20 width:20 height:20 pos:[0,0,0] mapcoords:true
	b.material = m
	convertToPoly b
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\vray_basic.max" quiet:true
	"vray_basic: " + (classOf b.material) as string + " saved"
)
