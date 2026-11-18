-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Cameras (system unit millimeters, render size 800 x 450): a rotated Free camera; an orthographic Free camera with
-- a target distance of its own; a Free camera that clips manually and shows a vertical FOV; a Target camera and an
-- orthographic one, each with its target; a Physical camera focused at its target distance (lens breathing); a
-- targeted Physical camera with lens shift, depth of field and a tilt correction; a Physical camera with a
-- specified FOV and a zoom; a VRayPhysicalCamera with a zoom at a target distance of its own; a targeted
-- VRayPhysicalCamera with lens shift, a specified FOV, depth of field and clipping; a targeted VRayPhysicalCamera
-- focused at its target (its stored target distance is not the one it renders with). A box to look at. Viewport 1
-- (active) looks through the rotated Free camera, viewport 2 through the Target camera, and the render view is
-- locked on viewport 2: 3ds Max renders the Target camera. Needs V-Ray (5, the one this was authored with); the
-- scene stays on the default renderer.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	renderWidth = 800
	renderHeight = 450
	renderPixelAspect = 1.0
	Box name:"CamSubject" length:500 width:500 height:500 material:(Standardmaterial name:"CamSubjectMtl")
	local free = Freecamera name:"CamFree" fov:60 pos:[2000,-3000,1200]
	rotate free (eulerAngles 75 0 30)
	local ortho = Freecamera name:"CamFreeOrtho" fov:45 orthoProjection:true targetDistance:2500 pos:[0,-2500,250]
	rotate ortho (eulerAngles 90 0 0)
	local clip = Freecamera name:"CamFreeClip" fov:35 clipManually:true nearclip:120 farclip:4500 pos:[-2500,-2000,800]
	clip.fovType = 2  -- vertical: shown only, the stored FOV stays horizontal
	rotate clip (eulerAngles 80 0 -50)
	local target = Targetcamera name:"CamTarget" fov:40 pos:[3000,2000,1500] \
		target:(Targetobject name:"CamTarget.Target" pos:[0,0,250])
	Targetcamera name:"CamTargetOrtho" fov:50 orthoProjection:true pos:[0,0,4000] \
		target:(Targetobject name:"CamTargetOrtho.Target" pos:[0,10,0])
	local phys = Physical name:"CamPhysical" targeted:false focal_length_mm:35 film_width_mm:36 target_distance:3000 \
		pos:[-3000,0,1000]
	rotate phys (eulerAngles 85 0 -90)
	local shifted = Physical name:"CamPhysShift" targeted:true focal_length_mm:24 film_width_mm:36 \
		horizontal_shift:10 vertical_shift:-15 use_dof:true vertical_tilt_correction:5 pos:[1500,-2500,600] \
		target:(Targetobject name:"CamPhysShift.Target" pos:[0,0,400])
	local fov = Physical name:"CamPhysFov" targeted:false specify_fov:true fov:75 zoom_factor:1.25 pos:[0,3000,800]
	rotate fov (eulerAngles 80 0 180)
	local vray = VRayPhysicalCamera name:"CamVRay" targeted:false focal_length:28 film_width:36 zoom_factor:1.2 \
		target_distance:2000 pos:[-2000,2500,900]
	rotate vray (eulerAngles 80 0 -140)
	local vshift = VRayPhysicalCamera name:"CamVRayShift" targeted:true specify_fov:true fov:50 horizontal_shift:0.1 \
		vertical_shift:0.25 use_dof:true clip_on:true clip_near:200 clip_far:6000 pos:[2500,0,300] \
		target:(Targetobject name:"CamVRayShift.Target" pos:[0,0,600])
	VRayPhysicalCamera name:"CamVRayTarget" targeted:true focal_length:20 film_width:30 pos:[-1500,-1500,1600] \
		target:(Targetobject name:"CamVRayTarget.Target" pos:[100,0,0])
	viewport.activeViewport = 2
	viewport.setCamera target
	viewport.activeViewport = 1
	viewport.setCamera free
	rendUseActiveView = false
	rendViewIndex = 2
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\cameras.max" quiet:true
	"cameras: " + (objects.count as string) + " objects"
)
