-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Standard lights, a Skylight and a VRaySun (system unit millimeters): an Omni without decay and its instance; an
-- Omni with inverse-square decay; an Omni with inverse decay, switched off; an Omni of negative multiplier; an Omni
-- that leaves out diffuse; an ambient-only Omni; a rotated Free Spot with inverse-square decay; a Free Spot with a
-- rectangular cone and overshoot that leaves out specular; a Target Spot and a Target Direct aimed at their targets;
-- a rotated Free Direct; a Skylight; a VRaySun aimed at its target; a VRaySky as the environment map. A light made
-- by MAXScript has its shadows off: StdOmni (and so its instance), StdSpot and StdTargetDirect switch them on, by
-- the light's own switch (baseObject.castShadows: a light node's castShadows is the node's render flag). Needs V-Ray
-- (5, the one this was authored with); the scene stays on the default renderer.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local omni = Omnilight name:"StdOmni" multiplier:1.5 rgb:(color 255 200 150) pos:[0,0,1500]
	omni.baseObject.castShadows = true
	local inst = instance omni
	inst.name = "StdOmniInst"
	inst.pos = [-500,0,1500]
	local sq = Omnilight name:"StdOmniSquare" multiplier:2.0 pos:[500,0,1500]
	sq.attenDecay = 3  -- inverse square
	sq.decayRadius = 800.0
	local inv = Omnilight name:"StdOmniInverse" multiplier:1.0 pos:[1000,0,1500]
	inv.attenDecay = 2  -- inverse
	inv.decayRadius = 500.0
	inv.on = false
	Omnilight name:"StdOmniNegative" multiplier:-1.0 pos:[1500,0,1500]
	local nd = Omnilight name:"StdOmniNoDiffuse" multiplier:1.0 pos:[0,500,1500]
	nd.affectDiffuse = false
	local amb = Omnilight name:"StdOmniAmbient" multiplier:0.5 pos:[500,500,1500]
	amb.ambientOnly = true
	local spot = freeSpot name:"StdSpot" multiplier:3.0 rgb:(color 120 160 255) hotspot:30 falloff:50 pos:[1000,500,1500]
	spot.attenDecay = 3
	spot.decayRadius = 1000.0
	rotate spot (eulerAngles 20 -10 30)
	spot.baseObject.castShadows = true
	local rect = freeSpot name:"StdSpotRect" multiplier:1.0 hotspot:40 falloff:45 pos:[1500,500,1500]
	rect.coneShape = 2  -- rectangle
	rect.aspect = 2.0
	rect.overShoot = true
	rect.affectSpecular = false
	targetSpot name:"StdTargetSpot" multiplier:2.0 hotspot:20 falloff:60 pos:[0,1000,1500] \
		target:(Targetobject name:"StdTargetSpot.Target" pos:[300,1200,0])
	local td = TargetDirectionallight name:"StdTargetDirect" multiplier:0.8 hotspot:500 falloff:700 \
		pos:[500,1000,2000] target:(Targetobject name:"StdTargetDirect.Target" pos:[200,900,0])
	td.baseObject.castShadows = true
	local dir = Directionallight name:"StdDirect" multiplier:1.2 rgb:(color 255 240 220) hotspot:300 falloff:400 \
		pos:[1000,1000,2000]
	rotate dir (eulerAngles 30 0 45)
	Skylight name:"StdSky" multiplier:0.7 pos:[1500,1000,0]
	VRaySun name:"StdSun" intensity_multiplier:0.5 size_multiplier:3.0 filter_Color:(color 255 230 200) \
		pos:[-3000,-2000,5000] target:(Targetobject name:"StdSun.Target" pos:[0,0,0])
	environmentMap = VRaySky()
	useEnvironmentMap = true
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\lights_standard.max" quiet:true
	"lights_standard: " + (objects.count as string) + " objects"
)
