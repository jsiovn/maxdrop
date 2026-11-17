-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Modifiers MaxDrop converts to Blender modifiers (convert/modifiers.py): TurboSmooth and MeshSmooth to
-- Subdivision Surface, Shell to Solidify, Symmetry to Mirror. The oracle's eval_verts and bbox are after the stack.
-- FixtureTurboOne: TurboSmooth, one iteration.
-- FixtureTurboRender: TurboSmooth, one iteration, two in the renderer, separate by smoothing groups.
-- FixtureMeshSmooth: MeshSmooth NURMS, two iterations.
-- FixtureShell: Shell, inner amount 1, outer amount 2.
-- FixtureSymmetry: Symmetry along X, its mirror gizmo moved 5 along X.
-- FixtureSymmetryTurned: Symmetry along Y, flipped, the gizmo turned 30 degrees about Z and moved [2, 3, 0].
-- FixtureSymmetryNoSlice: Symmetry along Z, slice along mirror off, no weld.
-- FixtureOrder: Shell (outer amount 1), then Symmetry along X, then TurboSmooth (one iteration).
-- FixtureBlocked: a Bend, then a TurboSmooth (not converted: MaxDrop does not evaluate the Bend).
-- Editable Poly boxes 20 x 20 x 20; one Standard material on every node.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)

	fn box_at name pos =
	(
		local b = Box name:name length:20 width:20 height:20 mapcoords:true pos:pos
		convertToPoly b
		b
	)

	addModifier (box_at "FixtureTurboOne" [0, 0, 0]) (TurboSmooth iterations:1)
	addModifier (box_at "FixtureTurboRender" [40, 0, 0]) \
		(TurboSmooth iterations:1 useRenderIterations:true renderIterations:2 sepBySmGroups:true)
	addModifier (box_at "FixtureMeshSmooth" [80, 0, 0]) (MeshSmooth subdivMethod:2 iterations:2)
	addModifier (box_at "FixtureShell" [120, 0, 0]) (Shell innerAmount:1.0 outerAmount:2.0)

	local sym = box_at "FixtureSymmetry" [0, 60, 0]
	local s = Symmetry axis:0 flip:false slice:1 weld:1 threshold:0.1
	addModifier sym s
	s.mirror.position = [5, 0, 0]

	local turned = box_at "FixtureSymmetryTurned" [40, 60, 0]
	local t = Symmetry axis:1 flip:true slice:1 weld:1 threshold:0.2
	addModifier turned t
	t.mirror.rotation = eulerangles 0 0 30
	t.mirror.position = [2, 3, 0]

	addModifier (box_at "FixtureSymmetryNoSlice" [80, 60, 0]) (Symmetry axis:2 flip:false slice:0 weld:0)

	local order = box_at "FixtureOrder" [0, 120, 0]
	addModifier order (Shell innerAmount:0.0 outerAmount:1.0)
	addModifier order (Symmetry axis:0 slice:1 weld:1)
	addModifier order (TurboSmooth iterations:1)

	local blocked = box_at "FixtureBlocked" [40, 120, 0]
	addModifier blocked (Bend angle:30 axis:2)
	addModifier blocked (TurboSmooth iterations:1)

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\stack_convert.max" quiet:true
	"stack_convert: " + (objects.count as string) + " objects: " + \
		((for o in objects collect (o.name + " " + ((getnumverts (snapshotAsMesh o)) as string))) as string)
)
