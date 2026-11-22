-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Bezier and TCB keys with frame 0 strictly between two of them, on Editable Poly boxes: Bezier Floats under
-- Position XYZ (auto tangents over four keys, smooth over three, a step out of the first key), Bezier Float custom
-- tangents with handle lengths other than a third, Bezier Position and Bezier Scale custom tangents with a length
-- per axis, Smooth Rotation (MAXScript Bezier_Rotation) over three keys, TCB Floats, TCB Position, TCB Rotation (a
-- turn of 200 degrees between two keys) and TCB Scale with tension, continuity, bias and ease set; a Linear Rotation
-- turning 270 degrees between two keys. Saved with the time
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

	sliderTime = 30
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\controllers_tangents.max" quiet:true
	"controllers_tangents: " + (objects.count as string) + " objects"
)
