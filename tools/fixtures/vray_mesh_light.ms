-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- VRayLight mesh lights. A Plane source (40 x 20, normal +Z); FixtureEmitter picks it (default units, multiplier 2,
-- turned 180 degrees about X so it shines down, visible); FixtureEmitterW picks it too (W, multiplier 5,
-- double-sided, Flip normals, invisible, scaled 2, 1, 1, object offset 10, 0, 0); FixtureEmitterOwn holds its own
-- mesh in reference 1, as V-Ray's Pick mesh with "Replace mesh with light" on leaves it (a Plane 30 x 10 with a
-- Shell; the light takes the plane's transform and the plane's node is deleted; lm, multiplier 100, affect specular
-- and reflections off); FixtureEmitterNone has no mesh. Needs V-Ray (5, the one this was authored with); the scene
-- stays on the default renderer. The multipliers are set after the type and units: V-Ray converts the multiplier
-- when they change.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	local src = Plane name:"FixtureEmitterSource" width:40 length:20 lengthsegs:1 widthsegs:1 pos:[0,-80,0]
	local a = VRayLight name:"FixtureEmitter" type:3 pos:[0,0,50]
	a.normalizeColor = 0
	a.multiplier = 2.0
	a.mesh_source = src
	rotate a (eulerAngles 180 0 0)
	local w = VRayLight name:"FixtureEmitterW" type:3 pos:[80,0,50]
	w.normalizeColor = 3
	w.multiplier = 5.0
	w.mesh_source = src
	w.DoubleSided = true
	w.mesh_flip = true
	w.invisible = true
	w.scale = [2,1,1]
	w.objectoffsetpos = [10,0,0]
	-- Replace mesh with light: the light holds the picked node's object (reference 1, MAXScript's 2) and takes its
	-- place; the node goes
	local own = Plane name:"FixtureEmitterOwnMesh" width:30 length:10 lengthsegs:1 widthsegs:1 pos:[-80,0,40]
	rotate own (eulerAngles 0 0 30)
	addModifier own (Shell outerAmount:0 innerAmount:2)
	local o = VRayLight name:"FixtureEmitterOwn" type:3
	o.normalizeColor = 1
	o.multiplier = 100.0
	o.affect_specualr = false
	o.affect_reflections = false
	o.transform = own.transform
	refs.replaceReference o.baseObject 2 (refs.getReference own 2)
	delete own
	local none = VRayLight name:"FixtureEmitterNone" type:3 pos:[0,80,50]
	none.normalizeColor = 3
	none.multiplier = 1.0
	renderers.current = Default_Scanline_Renderer()
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\vray_mesh_light.max" quiet:true
	"vray_mesh_light: " + (objects.count as string) + " objects; multipliers " + (a.multiplier as string) + ", " + \
		(w.multiplier as string) + ", " + (o.multiplier as string) + "; own mesh " + \
		((refs.getReference o.baseObject 2) as string)
)
