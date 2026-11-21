-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Transform controllers other than the default Position XYZ / Euler XYZ / Bezier Scale, on Point helpers: Euler
-- XYZ with three angles and in every other Tait-Bryan order; a Bezier Scale with a non-uniform scale along a turned
-- axis; ScaleXYZ; Linear, TCB and Bezier Position, Rotation (Bezier_Rotation is Smooth Rotation) and Scale; Position, Rotation and Scale Lists with a
-- weight of 50 % and an animated entry; Linear Float, TCB Float and Float List under Position XYZ; a Bezier Float
-- with three keys; a Target camera (Look At). Keys at frames 0, 20 and 50, and for two nodes at -10 and 40 (frame 0
-- between two keys) or at 10 and 50 (frame 0 before the first); saved with the time slider at frame 30, so a value
-- saved for the slider's frame is not the frame-0 value the oracle reports.
-- Positions stay below 100: the oracle keeps 6 significant digits.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)
	sliderTime = 0
	fn fixturePoint nm p = Point name:nm pos:p size:10 box:true

	-- Euler XYZ: three angles, then each other order (axisOrder 1 = XYZ ... 6 = ZYX)
	local multi = fixturePoint "FixtureEulerMulti" [-80,-80,0]
	multi.rotation.controller.x_rotation = 20
	multi.rotation.controller.y_rotation = 35
	multi.rotation.controller.z_rotation = -50
	local orders = #("XZY", "YZX", "YXZ", "ZXY", "ZYX")
	for k = 1 to orders.count do
	(
		local o = fixturePoint ("FixtureEuler" + orders[k]) [-80 + 20 * k,-80,0]
		o.rotation.controller.axisOrder = k + 1
		o.rotation.controller.x_rotation = 20
		o.rotation.controller.y_rotation = 35
		o.rotation.controller.z_rotation = -50
	)

	-- Bezier Scale [2, 0.5, 1] along axes turned 30 deg about Z and 20 deg about X, the node turned 40 deg about Y
	local axisNode = fixturePoint "FixtureScaleAxis" [0,0,0]
	local q = (eulerAngles 20 0 30) as matrix3
	axisNode.transform = (inverse q) * (scaleMatrix [2,0.5,1]) * q * ((eulerAngles 0 40 0) as matrix3) * \
		(transMatrix [10,-20,30])

	-- ScaleXYZ
	local sxyz = fixturePoint "FixtureScaleXYZ" [30,0,0]
	sxyz.scale.controller = ScaleXYZ()
	sxyz.scale.controller.x_scale = 150
	sxyz.scale.controller.y_scale = 50
	sxyz.scale.controller.z_scale = 200
	rotate sxyz (eulerAngles 0 0 25)

	-- keyframe Position, Rotation and Scale controllers, values set without keys
	fn keyframed nm p posCtrl rotCtrl scaleCtrl =
	(
		local o = fixturePoint nm [0,0,0]
		o.position.controller = posCtrl
		o.rotation.controller = rotCtrl
		o.scale.controller = scaleCtrl
		o.scale = [1.25,0.75,1.5]
		rotate o (eulerAngles 15 -25 60)
		o.pos = p
		o
	)
	keyframed "FixtureLinear" [-60,40,10] (Linear_Position()) (Linear_Rotation()) (Linear_Scale())
	keyframed "FixtureTCB" [-30,40,10] (TCB_Position()) (TCB_Rotation()) (TCB_Scale())
	keyframed "FixtureBezier" [0,40,10] (Bezier_Position()) (Bezier_Rotation()) (Bezier_Scale())
	-- the same with keys at frames 0 and 50
	fn keyed nm p posCtrl rotCtrl scaleCtrl =
	(
		local o = keyframed nm p posCtrl rotCtrl scaleCtrl
		with animate on at time 50
		(
			o.pos = p + [20,-10,5]
			rotate o (eulerAngles 0 0 45)
			o.scale = [0.5,2,1]
		)
		o
	)
	keyed "FixtureLinearKeyed" [-60,70,10] (Linear_Position()) (Linear_Rotation()) (Linear_Scale())
	keyed "FixtureTCBKeyed" [-30,70,10] (TCB_Position()) (TCB_Rotation()) (TCB_Scale())
	keyed "FixtureBezierKeyed" [0,70,10] (Bezier_Position()) (Bezier_Rotation()) (Bezier_Scale())
	-- keys at frames -10 and 40 (frame 0 between them, a fifth of the way) and at 10 and 50 (frame 0 before both)
	fn keyedAt nm p t0 t1 posCtrl rotCtrl scaleCtrl =
	(
		local o = fixturePoint nm [0,0,0]
		o.position.controller = posCtrl
		o.rotation.controller = rotCtrl
		o.scale.controller = scaleCtrl
		with animate on
		(
			at time t0 (o.scale = [1.25,0.75,1.5]; rotate o (eulerAngles 15 -25 60); o.pos = p)
			at time t1 (o.scale = [0.5,2,1]; rotate o (eulerAngles 0 0 45); o.pos = p + [20,-10,5])
		)
		-- the first key set away from frame 0 also put one at frame 0, with the value from before: removed
		for c in #(o.position.controller, o.rotation.controller, o.scale.controller) do
		(
			local k = getKeyIndex c 0f
			if k > 0 do deleteKey c k
		)
		o
	)
	keyedAt "FixtureLinearBetween" [-60,95,10] -10 40 (Linear_Position()) (Linear_Rotation()) (Linear_Scale())
	keyedAt "FixtureTCBBefore" [-30,95,10] 10 50 (TCB_Position()) (TCB_Rotation()) (TCB_Scale())

	-- lists: the existing controller is entry 1, a second entry is added; both weighted 50 %, the second animated
	local pl = fixturePoint "FixturePosList" [40,40,0]
	pl.position.controller = Position_List()
	pl.position.controller.Available.controller = Position_XYZ()
	pl.position.controller.weight[1] = 50
	pl.position.controller.weight[2] = 50
	pl.position.controller[2].controller.value = [10,20,30]
	with animate on at time 50 pl.position.controller[2].controller.value = [30,-20,10]

	local rl = fixturePoint "FixtureRotList" [70,40,0]
	rotate rl (eulerAngles 30 0 0)
	rl.rotation.controller = Rotation_List()
	rl.rotation.controller.Available.controller = Euler_XYZ()
	rl.rotation.controller.weight[1] = 50
	rl.rotation.controller.weight[2] = 50
	rl.rotation.controller[2].controller.z_rotation = 80
	with animate on at time 50 rl.rotation.controller[2].controller.z_rotation = 10

	local sl = fixturePoint "FixtureScaleList" [70,70,0]
	sl.scale = [2,1,1]
	sl.scale.controller = Scale_List()
	sl.scale.controller.Available.controller = Bezier_Scale()
	sl.scale.controller.weight[1] = 50
	sl.scale.controller.weight[2] = 50
	sl.scale.controller[2].controller.value = [1,3,0.5]
	with animate on at time 50 sl.scale.controller[2].controller.value = [1,1,1]

	-- float controllers under Position XYZ: Linear Float on X, TCB Float on Y, Float List (two Bezier Floats,
	-- weights 50 % and 100 %) on Z
	local fl = fixturePoint "FixtureFloats" [0,0,0]
	fl.position.controller.x_position.controller = Linear_Float()
	fl.position.controller.y_position.controller = TCB_Float()
	fl.position.controller.z_position.controller = Float_List()
	fl.position.controller.x_position = 11
	fl.position.controller.y_position = -22
	local zl = fl.position.controller.z_position.controller
	zl.Available.controller = Bezier_Float()
	zl.weight[1] = 50
	zl.weight[2] = 100
	zl[1].value = 30
	zl[2].value = 7
	local flk = fixturePoint "FixtureFloatsKeyed" [0,0,0]
	flk.position.controller.x_position.controller = Linear_Float()
	flk.position.controller.y_position.controller = TCB_Float()
	flk.position.controller.x_position = 15
	flk.position.controller.y_position = -25
	with animate on at time 50
	(
		flk.position.controller.x_position = 35
		flk.position.controller.y_position = -5
	)

	-- a Bezier Float with keys at frames 0, 20 and 50 (X), saved at frame 30
	local bf = fixturePoint "FixtureBezierKeys" [-20,-40,15]
	with animate on
	(
		at time 0 bf.position.controller.x_position = -20
		at time 20 bf.position.controller.x_position = 25
		at time 50 bf.position.controller.x_position = 60
	)

	-- a Target camera: Look At
	Targetcamera name:"FixtureCam" pos:[60,-60,40] target:(Targetobject name:"FixtureCam.Target" pos:[0,10,0])

	sliderTime = 30
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\controllers.max" quiet:true
	"controllers: " + (objects.count as string) + " objects"
)
