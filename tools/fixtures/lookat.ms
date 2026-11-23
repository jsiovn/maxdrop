-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Look At controllers and Look At constraints. Target cameras and a target spot (each with its target node), one
-- straight above its target, one with a roll, one under a rotated and scaled Dummy; boxes with a Look At
-- controller of another axis, flipped, rolled, scaled, with the target as up node; boxes with a Look At
-- constraint: two weighted targets, the axis options, an up node it looks at or aligns with, one under the Dummy;
-- the constraint's offsets: Keep Initial Offset under the Dummy, Set Orientation, both, Set Orientation turned off.
-- An animated target weight (keys at 0 and 50, a frame-0 value of its own): the second of two, and the one of a
-- constraint with an up node it looks at.
-- Positions 3ds Max computes (the children of the Dummy) stay below 100: the oracle keeps 6 significant digits.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	fn makeTargetCamera nm p t = Targetcamera name:nm pos:p target:(Targetobject name:(nm + ".Target") pos:t)
	local cam = makeTargetCamera "FixtureCam" [100,-200,80] [0,0,20]
	local roll = makeTargetCamera "FixtureCamRoll" [-120,-80,60] [20,30,10]
	roll.transform.controller.roll_angle = 30
	local down = makeTargetCamera "FixtureCamDown" [0,100,200] [0,100,0]
	local spot = targetSpot name:"FixtureSpot" pos:[-50,50,150] \
		target:(Targetobject name:"FixtureSpot.Target" pos:[10,10,0])
	local rig = Dummy name:"FixtureRig" pos:[60,0,0]
	rotate rig (eulerAngles 0 0 40)
	rig.scale = [1.5,1.5,1.5]
	local child = makeTargetCamera "FixtureCamChild" [0,0,0] [150,60,0]
	child.parent = rig
	in coordsys parent child.pos = [30,0,50]
	local aim = Point name:"FixtureAim" pos:[30,-40,50]
	in coordsys local rotate aim (eulerAngles 0 25 0)
	-- Look At controllers on boxes: -X flipped (so +X) at the target, the target's Z as up, a scale of its own
	local looker = Box name:"FixtureLooker" length:10 width:10 height:10 pos:[-100,-100,0]
	looker.transform.controller = lookat()
	looker.target = aim
	looker.transform.controller.axis = 0
	looker.transform.controller.flip = true
	looker.transform.controller.UseTargetAsUpNode = true
	looker.transform.controller.scale = [2,1,1]
	local lookerY = Box name:"FixtureLookerY" length:10 width:10 height:10 pos:[60,-120,20]
	lookerY.transform.controller = lookat()
	lookerY.target = aim
	lookerY.transform.controller.axis = 1
	lookerY.transform.controller.roll_angle = 15
	-- Look At constraints (a rotation controller). Setting target_axis also moves StoUP_axis and upnode_axis off it,
	-- so the axes are set first and the up options after.
	local both = Box name:"FixtureConstrained" length:10 width:10 height:10 pos:[80,80,0]
	local lc = LookAt_Constraint()
	both.rotation.controller = lc
	lc.appendTarget aim 50
	lc.appendTarget cam.target 100
	lc.target_axis = 1
	lc.target_axisFlip = true
	lc.StoUP_axis = 2
	lc.upnode_axis = 2
	lc.upnode_ctrl = 1
	both.scale = [1,2,1]
	local upLook = Box name:"FixtureConstrainedUp" length:10 width:10 height:10 pos:[-80,80,30]
	lc = LookAt_Constraint()
	upLook.rotation.controller = lc
	lc.appendTarget aim 50
	lc.target_axis = 2
	lc.StoUP_axis = 1
	lc.StoUP_axisFlip = true
	lc.upnode_world = false
	lc.pickUpNode = rig
	lc.upnode_ctrl = 0
	local upAxis = Box name:"FixtureConstrainedAxis" length:10 width:10 height:10
	upAxis.parent = rig
	in coordsys parent upAxis.pos = [-20,10,5]
	lc = LookAt_Constraint()
	upAxis.rotation.controller = lc
	lc.appendTarget spot.target 50
	lc.upnode_world = false
	lc.pickUpNode = aim
	lc.upnode_ctrl = 1
	lc.upnode_axis = 0
	-- the constraint's offsets, each box turned before or after its constraint, the target moved after all of them
	local offsetAim = Dummy name:"FixtureOffsetAim" pos:[20,30,10]
	local keep = Box name:"FixtureKeepOffset" length:10 width:10 height:10
	keep.parent = rig
	in coordsys parent keep.pos = [10,-20,-5]
	in coordsys local rotate keep (eulerAngles 20 30 40)
	lc = LookAt_Constraint()
	keep.rotation.controller = lc
	lc.appendTarget offsetAim 50
	lc.relative = true
	keep.transform  -- 3ds Max takes the aimed frame the offset is kept from at the constraint's first evaluation
	local orient = Box name:"FixtureSetOrientation" length:10 width:10 height:10 pos:[-60,-60,10]
	lc = LookAt_Constraint()
	orient.rotation.controller = lc
	lc.appendTarget offsetAim 50
	lc.set_orientation = true
	in coordsys local rotate orient (eulerAngles 15 0 25)
	local offsets = Box name:"FixtureBothOffsets" length:10 width:10 height:10 pos:[70,30,-10]
	rotate offsets (eulerAngles -10 25 60)
	lc = LookAt_Constraint()
	offsets.rotation.controller = lc
	lc.appendTarget offsetAim 50
	lc.relative = true
	lc.set_orientation = true
	in coordsys local rotate offsets (eulerAngles 0 20 -15)
	local orientOff = Box name:"FixtureOrientationOff" length:10 width:10 height:10 pos:[-20,-70,0]
	lc = LookAt_Constraint()
	orientOff.rotation.controller = lc
	lc.appendTarget offsetAim 50
	lc.set_orientation = true
	in coordsys local rotate orientOff (eulerAngles 25 10 0)
	lc.set_orientation = false
	offsetAim.pos = [-10,50,30]
	-- an animated weight: its controller is the block's first reference, before the targets and the up node
	local weighted = Box name:"FixtureWeightAnimated" length:10 width:10 height:10 pos:[40,-90,10]
	lc = LookAt_Constraint()
	weighted.rotation.controller = lc
	lc.appendTarget aim 50
	lc.appendTarget cam.target 20
	with animate on at time 50 lc.weight[2] = 90
	local weightedUp = Box name:"FixtureWeightUp" length:10 width:10 height:10 pos:[-90,-20,40]
	lc = LookAt_Constraint()
	weightedUp.rotation.controller = lc
	lc.appendTarget aim 60
	lc.upnode_world = false
	lc.pickUpNode = rig
	lc.upnode_ctrl = 0
	with animate on at time 50 lc.weight[1] = 10
	sliderTime = 0
	local grey = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for b in #(looker, lookerY, both, upLook, upAxis, keep, orient, offsets, orientOff, weighted, weightedUp) do
		b.material = grey
	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\lookat.max" quiet:true
	"lookat: " + (objects.count as string) + " objects"
)
