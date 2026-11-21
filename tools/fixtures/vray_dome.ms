-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- VRayLight dome, mesh and scaled sphere lights. A dome (default units, multiplier 2, invisible, a hemisphere) with a
-- VRayBitmap in spherical mapping (fixture_dome.png beside the scene, horizontal rotation 30) locked to the dome,
-- whose node is turned 90 degrees about Z; a second dome (W, multiplier 0.5, a color), which MaxDrop does not
-- import; a mesh light whose mesh source is a box (set by script: V-Ray keeps the reference, not a copy of the
-- mesh); a sphere in W/m2/sr scaled 1, 1, 2.5 (V-Ray takes the X scale: unchanged); a sphere in W scaled 2, 1, 1
-- (radius twice, power the same) and an unscaled instance of it. Needs V-Ray (5, the one this was authored with);
-- the scene stays on the default renderer. The multipliers are set after the type and units: V-Ray converts the
-- multiplier when they change.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local map = VRayBitmap name:"FixtureDomeMap" HDRIMapName:"fixture_dome.png" mapType:2 horizontalRotation:30
	local dome = VRayLight name:"FixtureDome" type:1 pos:[0,0,100]
	dome.normalizeColor = 0
	dome.multiplier = 2.0
	dome.texmap = map
	dome.texmap_locktodome = 1
	dome.dome_spherical = false
	dome.invisible = true
	rotate dome (eulerAngles 0 0 90)
	local second = VRayLight name:"FixtureDomeColor" type:1 color:(color 200 220 255) pos:[50,0,100]
	second.normalizeColor = 3
	second.multiplier = 0.5
	local src = Box name:"FixtureMeshSource" width:20 length:20 height:10 pos:[0,-60,0]
	local mesh = VRayLight name:"FixtureMeshLight" type:3 pos:[0,-60,50]
	mesh.normalizeColor = 3
	mesh.multiplier = 10.0
	mesh.mesh_source = src
	local tall = VRayLight name:"FixtureSphereTall" type:2 size0:5 pos:[60,60,50]
	tall.normalizeColor = 4
	tall.multiplier = 2.0
	tall.scale = [1,1,2.5]
	local wide = VRayLight name:"FixtureSphereWide" type:2 size0:5 pos:[-60,60,50]
	wide.normalizeColor = 3
	wide.multiplier = 40.0
	wide.scale = [2,1,1]
	local inst = instance wide
	inst.name = "FixtureSphereWideInst"
	inst.scale = [1,1,1]
	inst.pos = [-90,60,50]
	renderers.current = Default_Scanline_Renderer()
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\vray_dome.max" quiet:true
	"vray_dome: " + (objects.count as string) + " objects; dome multiplier " + (dome.multiplier as string) + \
		", second " + (second.multiplier as string) + ", mesh " + (mesh.multiplier as string)
)
