-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Bezier and TCB keys with frame 0 strictly between two of them, on Editable Poly boxes: Bezier Floats under
-- Position XYZ (auto tangents over four keys, smooth over three, a step out of the first key), Bezier Float custom
-- tangents with handle lengths other than a third, Bezier Position and Bezier Scale custom tangents with a length
-- per axis, Smooth Rotation (MAXScript Bezier_Rotation) over three keys, TCB Floats, TCB Position, TCB Rotation (a
-- turn of 200 degrees between two keys) and TCB Scale with tension, continuity, bias and ease set; a Linear Rotation
-- turning 270 degrees between two keys. Then (maxdrop-em3.144) free Bezier handles on Floats (steep, a free middle
-- key, a handle longer than its segment) and on a Position, constant velocity out of a Bezier Position key whose
-- later key has handle lengths, Bezier, TCB and Linear Scale keys whose scale axes differ, TCB Rotation turns of
-- 450, 400 and 760 degrees with frame 0 in the first half-turn, the last one and the turn between, a TCB turn of
-- exactly 360 degrees, a Linear Rotation turn of 360 degrees, a Scale List of two turned axes and a Rotation List of
-- two turns about several axes. Saved with the time
-- slider at frame 30, so the value saved for the slider's frame is not the frame-0 value the oracle reports. Values
-- and slopes stay moderate: next to a steep Bezier key the reader and 3ds Max differed by up to 1e-3 in a probe.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)
	sliderTime = 0
	local grey = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	fn fixtureBox nm p =
	(
		local o = Box name:nm length:10 width:10 height:10 pos:p
		convertToPoly o
		o.material = grey
		o
	)
	-- keys at the given frames; a key the first one away from frame 0 put at frame 0 is removed
	fn keyAll c times vals =
	(
		with animate on for k = 1 to times.count do at time times[k] c.value = vals[k]
		local k0 = getKeyIndex c 0f
		if k0 > 0 and findItem times 0 == 0 do deleteKey c k0
	)
	fn tcb key t c b easeTo easeFrom =
	(
		key.tension = t; key.continuity = c; key.bias = b; key.easeTo = easeTo; key.easeFrom = easeFrom
	)

	-- Bezier Floats under Position XYZ: X auto over four keys (frame 0 between the second and third), Y smooth over
	-- three, Z a step out of the first of three (the value saved at frame 30 holds for a whole step segment, so the
	-- slider is in the next one)
	local bf = fixtureBox "FixtureBezierFloats" [0,0,0]
	local pc = bf.position.controller
	pc.x_position.controller = Bezier_Float()
	pc.y_position.controller = Bezier_Float()
	pc.z_position.controller = Bezier_Float()
	keyAll pc.x_position.controller #(-30, -10, 20, 50) #(-40.0, -36.0, -30.0, -28.0)
	for k in pc.x_position.controller.keys do (k.inTangentType = #auto; k.outTangentType = #auto)
	keyAll pc.y_position.controller #(-20, 10, 40) #(-40.0, -35.0, -37.0)
	for k in pc.y_position.controller.keys do (k.inTangentType = #smooth; k.outTangentType = #smooth)
	keyAll pc.z_position.controller #(-10, 20, 40) #(5.0, 20.0, 12.0)
	pc.z_position.controller.keys[1].outTangentType = #step

	-- Bezier Float custom tangents, handle lengths 0.6 and 0.15 (not free handles)
	local bfc = fixtureBox "FixtureBezierCustom" [-20,0,0]
	local xc = bfc.position.controller.x_position.controller
	keyAll xc #(-10, 40) #(-25.0, -15.0)
	xc.keys[1].outTangentType = #custom; xc.keys[2].inTangentType = #custom
	xc.keys[1].outTangent = 0.3; xc.keys[2].inTangent = -0.2
	xc.keys[1].outTangentLength = 0.6; xc.keys[2].inTangentLength = 0.15

	-- Bezier Position custom tangents, a length per axis
	local bp = fixtureBox "FixtureBezierPosition" [0,0,0]
	bp.position.controller = Bezier_Position()
	local c = bp.position.controller
	keyAll c #(-10, 40) #([-10,30,5], [5,25,12])
	c.keys[1].outTangentType = #custom; c.keys[2].inTangentType = #custom
	c.keys[1].outTangent = [0.3,-0.15,0.1]; c.keys[2].inTangent = [-0.1,0.2,-0.25]
	c.keys[1].outTangentLength = [0.5,0.2,0.4]; c.keys[2].inTangentLength = [0.1,0.3,0.6]

	-- Bezier Scale custom tangents, a length per axis
	local bs = fixtureBox "FixtureBezierScale" [20,0,0]
	c = bs.scale.controller
	keyAll c #(-10, 40) #([1,1,1], [2,0.5,1.5])
	c.keys[1].outTangentType = #custom; c.keys[2].inTangentType = #custom
	c.keys[1].outTangent = [0.05,-0.02,0.01]; c.keys[2].inTangent = [-0.01,0.03,-0.02]
	c.keys[1].outTangentLength = [0.5,0.2,0.4]; c.keys[2].inTangentLength = [0.1,0.3,0.6]

	-- Smooth Rotation over three keys
	local q1 = (eulerAngles 15 -25 60) as quat
	local q2 = (eulerAngles 40 10 -30) as quat
	local q3 = (eulerAngles -20 70 45) as quat
	local sr = fixtureBox "FixtureSmoothRotation" [40,0,0]
	sr.rotation.controller = Bezier_Rotation()
	keyAll sr.rotation.controller #(-20, 10, 40) #(q1, q2, q3)

	-- TCB Floats under Position XYZ: X over three keys, Y over two
	local tf = fixtureBox "FixtureTCBFloats" [0,40,0]
	pc = tf.position.controller
	pc.x_position.controller = TCB_Float()
	pc.y_position.controller = TCB_Float()
	c = pc.x_position.controller
	keyAll c #(-20, 10, 40) #(-20.0, -14.0, -10.0)
	tcb c.keys[1] 10 40 60 0 20
	tcb c.keys[2] 35 15 30 40 10
	tcb c.keys[3] 0 25 10 0 0
	c = pc.y_position.controller
	keyAll c #(-10, 40) #(30.0, 40.0)
	tcb c.keys[1] 10 40 60 0 20
	tcb c.keys[2] 35 15 30 40 0

	-- TCB Position over three keys
	local tp = fixtureBox "FixtureTCBPosition" [0,0,0]
	tp.position.controller = TCB_Position()
	c = tp.position.controller
	keyAll c #(-20, 10, 40) #([20,40,3], [24,38,4], [30,35,6])
	tcb c.keys[1] 10 40 60 0 20
	tcb c.keys[2] 35 15 30 40 0

	-- TCB Rotation: a turn of 200 degrees about a diagonal from the first key to the second
	local tr = fixtureBox "FixtureTCBRotation" [40,40,0]
	tr.rotation.controller = TCB_Rotation()
	c = tr.rotation.controller
	with animate on
	(
		at time -20 c.value = (eulerAngles 10 20 30) as quat
		at time 10 rotate tr (angleAxis 200 (normalize [1,1,1]))
		at time 40 rotate tr (angleAxis 120 [0,1,0])
	)
	local k0 = getKeyIndex c 0f
	if k0 > 0 do deleteKey c k0
	tcb c.keys[1] 10 40 60 0 20
	tcb c.keys[2] 35 15 30 40 0

	-- TCB Scale over three keys
	local ts = fixtureBox "FixtureTCBScale" [60,40,0]
	ts.scale.controller = TCB_Scale()
	c = ts.scale.controller
	keyAll c #(-20, 10, 40) #([1,1,1], [1.5,0.8,1.2], [2,0.5,1.5])
	tcb c.keys[1] 10 40 25 0 0
	tcb c.keys[2] 25 25 30 40 0

	-- Linear Rotation: 270 degrees about Z between two keys, the long way round
	local lr = fixtureBox "FixtureLinearRotationWide" [60,0,0]
	lr.rotation.controller = Linear_Rotation()
	c = lr.rotation.controller
	with animate on
	(
		at time -10 c.value = (quat 0 0 0 1)
		at time 40 rotate lr (angleAxis 270 [0,0,1])
	)
	k0 = getKeyIndex c 0f
	if k0 > 0 do deleteKey c k0

	-- maxdrop-em3.144. Keys by addNewKey and value (no auto key at frame 0), turns by rotating the node after the
	-- first key, so each key keeps the turn it was given from the previous one.
	fn keysOn c times vals = (for k = 1 to times.count do (addNewKey c times[k]; c.keys[k].value = vals[k]))
	fn freeOut key tangent len = (key.outTangentType = #custom; key.outTangent = tangent; key.freeHandle = true; \
		key.outTangentLength = len)
	fn freeIn key tangent len = (key.inTangentType = #custom; key.inTangent = tangent; key.freeHandle = true; \
		key.inTangentLength = len)
	fn turnKeys o c t0 q0 turns = (
		o.rotation.controller = c
		addNewKey c t0
		c.keys[1].value = q0
		with animate on for tn in turns do at time tn[1] rotate o (angleAxis tn[2] tn[3])
	)
	-- scale keys through the node's transform, then the position and rotation keys that made are removed
	fn axisKeys o c times scales quats = (
		o.scale.controller = c
		with animate on for k = 1 to times.count do
			at time times[k] o.transform = (inverse (quats[k] as matrix3)) * (scaleMatrix scales[k]) * (quats[k] as matrix3)
		deleteKeys o.position.controller #allKeys
		deleteKeys o.rotation.controller #allKeys
		local k0 = getKeyIndex c 0f
		if k0 > 0 and findItem times 0 == 0 do deleteKey c k0
	)

	-- free handles on Bezier Floats: X steep (lengths 0.6 and 0.15 frames), Y a free middle key between custom keys
	-- (0.4 and 0.9 frames), Z handles longer than the segment (60 and 10 frames on 50)
	local fh = fixtureBox "FixtureFreeHandles" [0,-40,0]
	pc = fh.position.controller
	pc.x_position.controller = Bezier_Float()
	pc.y_position.controller = Bezier_Float()
	pc.z_position.controller = Bezier_Float()
	c = pc.x_position.controller
	keysOn c #(-10, 40) #(-25.0, -15.0)
	freeOut c.keys[1] 3.0 0.6; freeIn c.keys[2] -1.5 0.15
	c = pc.y_position.controller
	keysOn c #(-20, 10, 40) #(-45.0, -30.0, -35.0)
	c.keys[1].outTangentType = #custom; c.keys[1].outTangent = 0.5
	c.keys[3].inTangentType = #custom; c.keys[3].inTangent = -0.4
	freeIn c.keys[2] 2.0 0.4; freeOut c.keys[2] 2.0 0.9
	c = pc.z_position.controller
	keysOn c #(-10, 40) #(5.0, 15.0)
	freeOut c.keys[1] 0.3 60.0; freeIn c.keys[2] -0.2 10.0

	-- free handles on a Bezier Position, a length per axis
	local fp = fixtureBox "FixtureFreePosition" [0,0,0]
	fp.position.controller = Bezier_Position()
	c = fp.position.controller
	keysOn c #(-10, 40) #([-10,-30,5], [5,-25,12])
	freeOut c.keys[1] [0.3,-0.15,0.1] [0.5,0.2,0.4]; freeIn c.keys[2] [-0.1,0.2,-0.25] [0.1,0.3,0.6]

	-- constant velocity out of the earlier Bezier Position key; the later key's handle lengths do not count
	local cv = fixtureBox "FixtureConstantVelocity" [0,0,0]
	cv.position.controller = Bezier_Position()
	c = cv.position.controller
	keysOn c #(-10, 40) #([-10,-60,5], [5,-65,12])
	c.keys[1].outTangentType = #custom; c.keys[2].inTangentType = #custom
	c.keys[1].outTangent = [0.9,-0.6,0.4]; c.keys[2].inTangent = [-0.1,0.8,-0.5]
	c.keys[2].inTangentLength = [0.6,0.1,0.3]
	c.keys[1].constantVelocity = true

	-- scale axes that differ: Bezier and TCB over three keys, Linear over two
	local qa = (eulerAngles 20 0 30) as quat
	local qb = (eulerAngles -10 35 70) as quat
	local qc = (eulerAngles 50 -20 10) as quat
	local sab = fixtureBox "FixtureScaleAxesBezier" [0,0,0]
	axisKeys sab (Bezier_Scale()) #(-20, 10, 40) #([2,0.5,1], [1,1.5,3], [0.7,2,1.2]) #(qa, qb, qc)
	local sat = fixtureBox "FixtureScaleAxesTCB" [0,0,0]
	axisKeys sat (TCB_Scale()) #(-20, 10, 40) #([2,0.5,1], [1,1.5,3], [0.7,2,1.2]) #(qa, qb, qc)
	c = sat.scale.controller
	c.keys[1].tension = 10; c.keys[2].continuity = 40; c.keys[2].easeTo = 30
	local sal = fixtureBox "FixtureScaleAxesLinear" [0,0,0]
	axisKeys sal (Linear_Scale()) #(-10, 40) #([2,0.5,1], [1,1.5,3]) #(qa, qb)

	-- TCB Rotation turns of a revolution or more: 450 degrees with frame 0 in the first half-turn (tension,
	-- continuity, bias and ease set), 400 with frame 0 in the last half-turn, 760 after 400 with frame 0 half way,
	-- exactly 360 with frame 0 in its last half-turn
	local sq = (eulerAngles 15 -25 60) as quat
	local ax = normalize [1,2,3]
	local ss = fixtureBox "FixtureTCBSpinStart" [0,0,0]
	turnKeys ss (TCB_Rotation()) -25 sq #(#(-5, 30, [0,1,0]), #(25, 450, ax), #(55, 40, [1,0,0]))
	c = ss.rotation.controller
	tcb c.keys[1] 10 25 25 0 20
	tcb c.keys[2] 25 15 30 40 10
	tcb c.keys[3] 35 40 60 30 0
	local se = fixtureBox "FixtureTCBSpinEnd" [0,0,0]
	turnKeys se (TCB_Rotation()) -20 sq #(#(10, 400, ax), #(40, 60, [0,1,0]))
	local sm = fixtureBox "FixtureTCBSpinMiddle" [0,0,0]
	turnKeys sm (TCB_Rotation()) -45 sq #(#(-15, 400, ax), #(15, 760, [0,0,1]))
	local tt = fixtureBox "FixtureTCBTurn" [0,0,0]
	turnKeys tt (TCB_Rotation()) -20 sq #(#(10, 360, normalize [1,1,0]), #(40, 50, [0,0,1]))

	-- Linear Rotation: a whole turn between two keys (opposite quaternions)
	local lt = fixtureBox "FixtureLinearRotationTurn" [0,0,0]
	turnKeys lt (Linear_Rotation()) -10 sq #(#(40, 360, normalize [1,1,0]))

	-- a Scale List of two Bezier Scales along turned axes, and a Rotation List of two turns about several axes
	local sl = fixtureBox "FixtureScaleListAxes" [0,0,0]
	sl.transform = (inverse (qa as matrix3)) * (scaleMatrix [2,0.5,1]) * (qa as matrix3)
	sl.scale.controller = Scale_List()
	sl.scale.controller.Available.controller = Bezier_Scale()
	sl.scale.controller.setActive 2
	sl.transform = (inverse (qb as matrix3)) * (scaleMatrix [1,1.5,3]) * (qb as matrix3)
	local rl = fixtureBox "FixtureRotListMulti" [0,0,0]
	rl.rotation.controller = Rotation_List()
	rl.rotation.controller.Available.controller = Euler_XYZ()
	rl.rotation.controller[1].controller.value = (eulerAngles 30 40 50) as quat
	rl.rotation.controller[2].controller.value = (eulerAngles -20 60 10) as quat
	rl.rotation.controller.weight[1] = 50
	rl.rotation.controller.weight[2] = 30

	sliderTime = 30
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\controllers_tangents.max" quiet:true
	"controllers_tangents: " + (objects.count as string) + " objects"
)
