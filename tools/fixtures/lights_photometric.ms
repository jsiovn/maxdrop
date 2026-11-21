-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Photometric lights and VRayIES (system unit millimeters): a point Free Light, isotropic, Kelvin 3000, and its
-- instance; a rotated point Free Light, spotlight, dimmed to 50 %; a Free Rectangle, a Free Disc and a Free Line of
-- uniform diffuse distribution; an isotropic Free Sphere; an isotropic Free Cylinder that leaves out specular; a Target
-- Disc aimed at its target with a web distribution; a switched-off Free Light with a filter color; a VRayIES by its
-- power; a VRayIES whose intensity is overridden in cd, in temperature mode; a Target Light of each other shape,
-- isotropic, aimed straight down. A light made by MAXScript has its shadows off: PhPoint (and so its instance) and
-- PhSpot switch them on (baseObject.castShadows: a light node's castShadows is the node's render flag); a VRayIES has
-- them on, IesOverride switches them off. IesPower's light shape is overridden as a rectangle, IesOverride's as a
-- sphere. The web file and the IES file are a bare file name that does not exist (no path goes into the file). Needs
-- V-Ray (5, the one this was authored with); the scene stays on the default renderer.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local pt = Free_Light name:"PhPoint" pos:[0,0,1500]
	pt.distribution = 0  -- isotropic
	pt.intensity = 1200.0
	pt.useKelvin = true
	pt.kelvin = 3000.0
	pt.baseObject.castShadows = true
	local inst = instance pt
	inst.name = "PhPointInst"
	inst.pos = [-500,0,1500]
	local sp = Free_Light name:"PhSpot" pos:[500,0,1500]
	sp.distribution = 1  -- spotlight
	sp.intensity = 2000.0
	sp.hotspot = 40.0
	sp.falloff = 70.0
	sp.useKelvin = false
	sp.useMultiplier = true
	sp.multiplier = 50.0
	rotate sp (eulerAngles 15 25 0)
	sp.baseObject.castShadows = true
	local rc = Free_Light name:"PhRect" pos:[1000,0,2500]
	rc.type = #Free_Rectangle
	rc.distribution = 2  -- uniform diffuse
	rc.light_length = 600.0
	rc.light_width = 200.0
	rc.intensity = 800.0
	rc.useKelvin = false
	local dc = Free_Light name:"PhDisc" pos:[1500,0,2500]
	dc.type = #Free_Disc
	dc.distribution = 2
	dc.light_radius = 150.0
	dc.intensity = 500.0
	dc.useKelvin = false
	local ln = Free_Light name:"PhLine" pos:[0,500,2500]
	ln.type = #Free_Line
	ln.distribution = 2
	ln.light_length = 1000.0
	ln.intensity = 300.0
	ln.useKelvin = false
	local sph = Free_Light name:"PhSphere" pos:[500,500,1500]
	sph.type = #Free_Sphere
	sph.distribution = 0
	sph.light_radius = 50.0
	sph.intensity = 900.0
	sph.useKelvin = false
	local cy = Free_Light name:"PhCylinder" pos:[1000,500,1500]
	cy.type = #Free_Cylinder
	cy.distribution = 0
	cy.light_length = 400.0
	cy.light_radius = 30.0
	cy.intensity = 700.0
	cy.useKelvin = false
	cy.affectSpecular = false
	local web = Target_Light name:"PhWeb" pos:[1500,500,2500] \
		target:(Targetobject name:"PhWeb.Target" pos:[1700,700,0])
	web.type = #Target_Disc
	web.distribution = 3  -- photometric web
	web.webfile = "fixture_web.ies"
	web.light_radius = 80.0
	web.intensity = 400.0
	web.useKelvin = false
	local dark = Free_Light name:"PhOff" pos:[0,1000,1500]
	dark.intensity = 1000.0
	dark.useKelvin = false
	dark.rgbFilter = (color 255 128 0)
	dark.on = false
	local ies = VRayIES name:"IesPower" pos:[500,1000,2500]
	ies.targeted = false
	ies.ies_file = "fixture_web.ies"
	ies.power = 1500.0
	ies.override_shape = true
	ies.shape = 1  -- rectangle
	ies.width = 200.0
	ies.length = 400.0
	local ov = VRayIES name:"IesOverride" pos:[1000,1000,2500]
	ov.targeted = false
	ov.ies_file = "fixture_web.ies"
	ov.override_intensity = 1
	ov.intensity_type = 1  -- cd
	ov.intensity_value = 300.0
	ov.color_mode = 1  -- temperature
	ov.color_temperature = 4000.0
	ov.affect_specular = false
	ov.cast_shadows = false
	ov.override_shape = true
	ov.shape = 3  -- sphere
	ov.diameter = 100.0
	rotate ov (eulerAngles 0 30 0)
	-- the other target shapes, for their classes
	local x = 0
	for t in #(#Target_Point, #Target_Line, #Target_Rectangle, #Target_Sphere, #Target_Cylinder) do
	(
		local n = "PhT" + (substring (t as string) 8 -1)
		local tl = Target_Light name:n pos:[x,1500,2000] target:(Targetobject name:(n + ".Target") pos:[x,1500,0])
		tl.type = t
		tl.intensity = 100.0
		tl.useKelvin = false
		x += 500
	)
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\lights_photometric.max" quiet:true
	"lights_photometric: " + (objects.count as string) + " objects"
)
