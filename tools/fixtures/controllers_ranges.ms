-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Out-of-range types, list Average and Bezier tangent types (maxdrop-6n0.6.12), on Editable Poly boxes: Bezier Floats
-- under Position XYZ with frame 0 before their keys (Cycle, Ping Pong, Relative Repeat, Loop, Linear, a Cycle
-- switched off) and after them (Cycle, Relative Repeat, Linear), ranges moved off the keys (Loop over a wider range,
-- Constant and Cycle over a narrower one), the types on a Bezier Position, a TCB Rotation, a Linear Rotation, a
-- Bezier Scale, a Linear Position, a TCB Float and a Linear Float; Float, Position, Rotation and Scale Lists with
-- Average on, a Scale List of one turned entry at 60 %; Linear tangents beside custom and auto keys, smooth and
-- auto keys whose stored handle lengths are not a third, a Bezier Position with a Linear tangent beside an auto key.
-- Keys are made by addNewKey and their values set (no key at frame 0), and the file is saved with the time slider at
-- frame 30. A Linear type is extended from a key next to frame 0 whose value is 0: 3ds Max extrapolates the slope of
-- one tick in single precision, which grows with the distance.
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
	fn keysOn c times vals = (for k = 1 to times.count do (addNewKey c times[k]; c.keys[k].value = vals[k]))
	-- a Bezier Float with curved custom tangents (in and out tangents differ at the ends)
	fn curved c times vals = (
		keysOn c times vals
		local n = times.count
		c.keys[1].inTangentType = #custom; c.keys[1].outTangentType = #custom
		c.keys[1].inTangent = -3.0; c.keys[1].outTangent = 2.0
		for k = 2 to n - 1 do (c.keys[k].inTangentType = #smooth; c.keys[k].outTangentType = #smooth)
		c.keys[n].inTangentType = #custom; c.keys[n].outTangentType = #custom
		c.keys[n].inTangent = -1.0; c.keys[n].outTangent = 4.0
	)
	fn floats o = (
		local pc = o.position.controller
		local cs = #(Bezier_Float(), Bezier_Float(), Bezier_Float())
		pc.x_position.controller = cs[1]; pc.y_position.controller = cs[2]; pc.z_position.controller = cs[3]
		cs
	)

	-- before the keys at frames 10, 30, 50: X Cycle, Y Ping Pong, Z Relative Repeat
	local cs = floats (fixtureBox "FixtureFloatTypes" [0,0,0])
	curved cs[1] #(10, 30, 50) #(0.0, 20.0, 5.0); setBeforeORT cs[1] #cycle
	curved cs[2] #(10, 30, 50) #(0.0, 20.0, 5.0); setBeforeORT cs[2] #pingPong
	curved cs[3] #(10, 30, 50) #(0.0, 20.0, 5.0); setBeforeORT cs[3] #relativeRepeat
	-- X Loop (range on the keys: as Cycle), Y Linear from a key at frame 1, Z Cycle with the types switched off
	cs = floats (fixtureBox "FixtureFloatTypesMore" [0,0,0])
	curved cs[1] #(10, 30, 50) #(0.0, 20.0, 5.0); setBeforeORT cs[1] #loop; setAfterORT cs[1] #loop
	curved cs[2] #(1, 20, 40) #(0.0, 20.0, 5.0); setBeforeORT cs[2] #linear
	curved cs[3] #(10, 30, 50) #(0.0, 20.0, 5.0); setBeforeORT cs[3] #cycle; enableORTs cs[3] false
	-- after the keys: X Cycle, Y Relative Repeat (keys at -50, -30, -10), Z Linear from a key at frame -1
	cs = floats (fixtureBox "FixtureFloatAfter" [0,0,0])
	curved cs[1] #(-50, -30, -10) #(0.0, 20.0, 5.0); setAfterORT cs[1] #cycle
	curved cs[2] #(-50, -30, -10) #(0.0, 20.0, 5.0); setAfterORT cs[2] #relativeRepeat
	curved cs[3] #(-40, -20, -1) #(5.0, 20.0, 0.0); setAfterORT cs[3] #linear
	-- a straight last segment: how 3ds Max solves the time curve one tick before a curved end is not followed
	cs[3].keys[2].outTangentType = #linear; cs[3].keys[3].inTangentType = #linear
	-- ranges moved off the keys at 10, 30, 50: X Loop over 0 to 60 (frame 0 in the gap from the last key to the
	-- first), Y Constant over 20 to 40 (frame 20's value), Z Cycle over 20 to 40
	cs = floats (fixtureBox "FixtureFloatRanges" [0,0,0])
	curved cs[1] #(10, 30, 50) #(0.0, 20.0, 5.0); setBeforeORT cs[1] #loop; setAfterORT cs[1] #loop
	setTimeRange cs[1] (interval 0 60)
	curved cs[2] #(10, 30, 50) #(0.0, 20.0, 5.0); setTimeRange cs[2] (interval 20 40)
	curved cs[3] #(10, 30, 50) #(0.0, 20.0, 5.0); setBeforeORT cs[3] #cycle; setTimeRange cs[3] (interval 20 40)

	-- the types on other classes
	local o = fixtureBox "FixtureORTPosition" [0,0,0]
	o.position.controller = Bezier_Position()
	local c = o.position.controller
	keysOn c #(10, 30, 50) #([0,4,-2], [20,-6,9], [5,12,3])
	c.keys[1].outTangentType = #custom; c.keys[1].outTangent = [2,-1,1.5]
	c.keys[3].inTangentType = #custom; c.keys[3].inTangent = [-1,0.5,2]
	setBeforeORT c #cycle
	local q1 = (eulerAngles 15 -25 60) as quat
	o = fixtureBox "FixtureORTRotation" [0,0,0]
	o.rotation.controller = TCB_Rotation()
	c = o.rotation.controller
	addNewKey c 10; c.keys[1].value = q1
	with animate on (
		at time 30 rotate o (angleAxis 70 [0,1,0])
		at time 50 rotate o (angleAxis 50 (normalize [1,2,3]))
	)
	setBeforeORT c #relativeRepeat
	o = fixtureBox "FixtureORTLinearRotation" [0,0,0]
	o.rotation.controller = Linear_Rotation()
	c = o.rotation.controller
	addNewKey c 1; c.keys[1].value = quat 1
	with animate on at time 30 rotate o (angleAxis 60 (normalize [1,2,3]))
	setBeforeORT c #linear
	o = fixtureBox "FixtureORTScale" [0,0,0]
	o.scale.controller = Bezier_Scale()
	c = o.scale.controller
	keysOn c #(10, 30, 50) #([1,1,1], [2,0.5,1.5], [0.8,1.2,3])
	setBeforeORT c #pingPong
	o = fixtureBox "FixtureORTLinearPosition" [0,0,0]
	o.position.controller = Linear_Position()
	c = o.position.controller
	keysOn c #(-50, -30, -10) #([0,4,-2], [20,-6,9], [5,12,3])
	setAfterORT c #relativeRepeat
	o = fixtureBox "FixtureORTTCBFloat" [0,0,0]
	local pc = o.position.controller
	pc.x_position.controller = TCB_Float(); pc.y_position.controller = Linear_Float()
	c = pc.x_position.controller
	keysOn c #(-50, -30, -10) #(0.0, 20.0, 5.0)
	c.keys[2].tension = 35; c.keys[1].easeFrom = 20
	setAfterORT c #pingPong
	c = pc.y_position.controller
	keysOn c #(10, 30, 50) #(0.0, 20.0, 5.0)
	setBeforeORT c #cycle

	-- lists with Average on: a Position List of three entries, a Rotation List of three turns, a Scale List of two
	-- plain scales; a Float List of two entries
	o = fixtureBox "FixtureListAverages" [0,0,0]
	o.position.controller = Position_List()
	c = o.position.controller
	c.Available.controller = Bezier_Position(); c.Available.controller = Bezier_Position()
	c[1].controller.value = [10,20,30]; c[2].controller.value = [-4,8,2]; c[3].controller.value = [7,-3,5]
	c.weight[1] = 20; c.weight[2] = 30; c.weight[3] = 70
	c.average = true
	o.rotation.controller = Rotation_List()
	c = o.rotation.controller
	c.Available.controller = Euler_XYZ(); c.Available.controller = Euler_XYZ()
	c[1].controller.value = (eulerAngles 30 0 0) as quat
	c[2].controller.value = (eulerAngles 0 45 0) as quat
	c[3].controller.value = (eulerAngles 0 0 80) as quat
	c.weight[1] = 50; c.weight[2] = 70; c.weight[3] = 20
	c.average = true
	o.scale = [2,1,1]
	o.scale.controller = Scale_List()
	c = o.scale.controller
	c.Available.controller = Bezier_Scale()
	c[2].controller.value = [1,3,0.5]
	c.weight[1] = 50; c.weight[2] = 100
	c.average = true
	o = fixtureBox "FixtureFloatListAverage" [0,0,0]
	local fl = Float_List()
	o.position.controller.x_position.controller = fl
	fl.Available.controller = Bezier_Float()
	fl[1].controller.value = 30.0; fl[2].controller.value = 7.0
	fl.weight[1] = 50; fl.weight[2] = 100
	fl.average = true
	local qa = (eulerAngles 20 0 30) as quat
	o = fixtureBox "FixtureScaleListTurned" [0,0,0]
	o.transform = (inverse (qa as matrix3)) * (scaleMatrix [2,0.5,1]) * (qa as matrix3)
	o.scale.controller = Scale_List()
	o.scale.controller.weight[1] = 60

	-- Bezier tangent types, keys at frames -20, 10, 40 (and 55): X a Linear tangent on either side of a custom key,
	-- Y on either side of an auto key, Z an auto in tangent and a custom out tangent on the second key, the reverse on
	-- the third, Linear at the ends
	cs = floats (fixtureBox "FixtureLinearTangents" [0,0,0])
	c = cs[1]
	keysOn c #(-20, 10, 40) #(-25.0, -10.0, -15.0)
	c.keys[1].outTangentType = #linear; c.keys[3].inTangentType = #linear
	c.keys[2].inTangentType = #custom; c.keys[2].outTangentType = #custom
	c.keys[2].inTangent = 2.0; c.keys[2].outTangent = 2.0
	c.keys[2].inTangentLength = 0.4; c.keys[2].outTangentLength = 0.9
	c = cs[2]
	keysOn c #(-20, 10, 40) #(-25.0, -10.0, -15.0)
	c.keys[2].inTangentType = #auto; c.keys[2].outTangentType = #auto
	c.keys[1].outTangentType = #linear; c.keys[3].inTangentType = #linear
	c = cs[3]
	keysOn c #(-20, 10, 40, 55) #(-25.0, -10.0, 5.0, 30.0)
	c.keys[2].inTangentType = #auto; c.keys[2].outTangentType = #custom; c.keys[2].outTangent = 1.0
	c.keys[3].inTangentType = #custom; c.keys[3].inTangent = 0.5; c.keys[3].outTangentType = #auto
	-- X smooth keys, Y auto keys (frame 0 between the first two)
	cs = floats (fixtureBox "FixtureSmoothAuto" [0,0,0])
	keysOn cs[1] #(-20, 10, 40, 55) #(-25.0, -10.0, -15.0, 30.0)
	for k in cs[1].keys do (k.inTangentType = #smooth; k.outTangentType = #smooth)
	keysOn cs[2] #(-20, 10, 40, 55) #(-25.0, -10.0, 5.0, 30.0)
	for k in cs[2].keys do (k.inTangentType = #auto; k.outTangentType = #auto)
	-- a Bezier Position: Linear tangents on either side of an auto key
	o = fixtureBox "FixtureLinearPosition" [0,0,0]
	o.position.controller = Bezier_Position()
	c = o.position.controller
	keysOn c #(-20, 10, 40) #([-25,3,7], [-10,20,-4], [-15,5,10])
	c.keys[2].inTangentType = #auto; c.keys[2].outTangentType = #auto
	c.keys[1].outTangentType = #linear; c.keys[3].inTangentType = #linear

	-- a Bezier key stores the smooth and auto tangents 3ds Max last computed: evaluate every node once, as a viewport
	-- does, or a key whose neighbours changed after it was made keeps a stale one
	for o in objects do at time 0 o.transform
	sliderTime = 30
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\controllers_ranges.max" quiet:true
	"controllers_ranges: " + (objects.count as string) + " objects"
)
