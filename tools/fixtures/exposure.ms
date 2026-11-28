-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Exposure (render size 800 x 450, gamma off): five VRayPhysicalCameras and a Physical camera around a box with a
-- VRayMtl. V-Ray keeps a camera's exposure value and its f-number, shutter speed and ISO in step: setting the
-- f-number, the shutter speed or the ISO computes the exposure value again (EV = log2(N^2 * shutter * 100 / ISO)),
-- setting the exposure value computes the ISO, and with the exposure mode on 2 (exposure value) a new f-number or
-- shutter speed keeps the exposure value and computes the ISO. The values each camera stores (3ds Max 2020, V-Ray
-- 5.2; exposure 0 off, 1 physical exposure, 2 exposure value):
--   FixtureExpPhysical, targeted at the box: exposure 1, f-number 5.6, shutter speed 125, ISO 200, exposure value
--     10.9366 (computed).
--   FixtureExpOff: exposure 0, f-number 2.8, shutter speed 200, ISO 100, exposure value 10.6147 (computed).
--   FixtureExpValue: exposure 2, f-number 4, shutter speed 100, exposure value 10.5, ISO 110.485 (computed).
--   FixtureExpTint: exposure 1 at the defaults (f-number 8, shutter speed 200, ISO 100) with the stored exposure
--     value 13 (the default, not the 13.6439 they give: nothing set computed it), vignetting on with an amount of
--     0.5, white balance preset 5 (color 255 226.974 192.683).
--   FixtureExpStored: exposure 2 and nothing else: the stored exposure value 13, not the 13.6439 of its f-number 8,
--     shutter speed 200 and ISO 100.
--   FixturePhysDof, a Physical camera: depth of field on, f-number 2.8, focus distance 2500 specified (specify focus
--     1), target distance 5000.
-- Viewport 1 (active) looks through FixturePhysDof, viewport 2 through FixtureExpPhysical, and the render view is
-- locked on viewport 2: 3ds Max renders FixtureExpPhysical. Needs V-Ray (5, the one this was authored with); the
-- scene stays on the default renderer.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	renderWidth = 800
	renderHeight = 450
	renderPixelAspect = 1.0
	Box name:"FixtureExpBox" length:500 width:500 height:500 \
		material:(VRayMtl name:"FixtureExpMtl" diffuse:(color 180 180 180))
	local phys = VRayPhysicalCamera name:"FixtureExpPhysical" targeted:true pos:[3000,2000,1500] \
		target:(Targetobject name:"FixtureExpPhysical.Target" pos:[0,0,250])
	phys.exposure = 1
	phys.f_number = 5.6
	phys.shutter_speed = 125.0
	phys.ISO = 200.0
	local unexposed = VRayPhysicalCamera name:"FixtureExpOff" targeted:false pos:[-3000,0,1000]
	rotate unexposed (eulerAngles 85 0 -90)
	unexposed.exposure = 0
	unexposed.f_number = 2.8
	local ev = VRayPhysicalCamera name:"FixtureExpValue" targeted:false pos:[0,3000,800]
	rotate ev (eulerAngles 80 0 180)
	ev.exposure = 2
	ev.f_number = 4.0
	ev.shutter_speed = 100.0
	ev.exposure_value = 10.5
	local tint = VRayPhysicalCamera name:"FixtureExpTint" targeted:false pos:[-2000,2500,900]
	rotate tint (eulerAngles 80 0 -140)
	tint.exposure = 1
	tint.vignetting = true
	tint.vignetting_amount = 0.5
	tint.whiteBalance_preset = 5
	local stored = VRayPhysicalCamera name:"FixtureExpStored" targeted:false pos:[3000,-1500,700]
	rotate stored (eulerAngles 80 0 63)
	stored.exposure = 2
	local dof = Physical name:"FixturePhysDof" targeted:false pos:[2000,-3000,1200]
	rotate dof (eulerAngles 75 0 30)
	dof.use_dof = true
	dof.f_number = 2.8
	dof.specify_focus = 1
	dof.focus_distance = 2500.0
	viewport.activeViewport = 2
	viewport.setCamera phys
	viewport.activeViewport = 1
	viewport.setCamera dof
	rendUseActiveView = false
	rendViewIndex = 2
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\exposure.max" quiet:true
	"exposure: " + (objects.count as string) + " objects"
)
