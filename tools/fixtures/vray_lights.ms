-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- VRayLights: one of each type (plane, disc, sphere, mesh, dome) and each units mode (default, lm, lm/m2/sr, W,
-- W/m2/sr). A rotated plane with an instance; a double-sided plane; a sphere in temperature mode; a switched-off
-- plane; an invisible disc that leaves out specular and reflections and halves its diffuse; a targeted plane aimed
-- at its target; an instance of the disc scaled 2, 1.5, 1 (V-Ray grows its area, so its flux in lm/m2/sr, three
-- times). The mesh light has no mesh picked. Needs V-Ray (5, the one this was authored with); the scene
-- stays on the default renderer.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local plane = VRayLight name:"FixturePlane" type:0 size0:20 size1:10 normalizeColor:0 multiplier:30 \
		color:(color 255 200 150) pos:[0,0,90]
	rotate plane (eulerAngles 30 0 20)
	local inst = instance plane
	inst.name = "FixturePlaneInst"
	inst.pos = [-60,0,90]
	VRayLight name:"FixturePlaneLm" type:0 size0:15 size1:15 normalizeColor:1 multiplier:1500 doubleSided:true \
		pos:[60,0,90]
	local disc = VRayLight name:"FixtureDisc" type:4 size0:15 normalizeColor:2 multiplier:3000 color:(color 120 160 255) \
		pos:[0,60,90]
	VRayLight name:"FixtureSphere" type:2 size0:5 normalizeColor:3 multiplier:40 pos:[60,60,50]
	VRayLight name:"FixtureSphereKelvin" type:2 size0:8 normalizeColor:4 multiplier:100 color_mode:1 \
		color_temperature:3500 pos:[-60,60,50]
	VRayLight name:"FixtureMesh" type:3 normalizeColor:3 multiplier:10 pos:[0,-60,50]
	VRayLight name:"FixtureDome" type:1 multiplier:1 pos:[0,0,0]
	local dark = VRayLight name:"FixtureOff" type:0 size0:10 size1:10 multiplier:5 pos:[60,-60,90]
	dark.on = false  -- on:false at creation does not stick
	-- affect_specualr: V-Ray's own spelling of the parameter
	VRayLight name:"FixtureInvisible" type:4 size0:10 normalizeColor:3 multiplier:20 invisible:true \
		affect_specualr:false affect_reflections:false diffuse_contribution:0.5 pos:[-60,-60,90]
	local aimed = VRayLight name:"FixtureTargeted" type:0 size0:10 size1:5 normalizeColor:3 multiplier:25 \
		pos:[-90,30,80]
	aimed.targeted = true  -- makes the target node and the Look At controller; targeted:true at creation does not
	aimed.target.name = "FixtureTargeted.Target"
	aimed.target.pos = [-40,30,0]
	local big = instance disc
	big.name = "FixtureDiscScaled"
	big.pos = [90,30,90]
	big.scale = [2,1.5,1]
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\vray_lights.max" quiet:true
	"vray_lights: " + (objects.count as string) + " objects"
)
