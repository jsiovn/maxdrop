-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Shells whose surfaces lie on one side of the original or turn it inside out, as Solidify (convert/modifiers.py),
-- and the rim's shading. Every node is an Editable Poly box 20 x 20 x 20 without its top face, so the shell has a
-- rim: the facing of its triangles (the oracle's eval_mesh) tells an inside-out shell from another.
-- FixtureShellOut: inner amount -1, outer amount 2 (both surfaces outside the original).
-- FixtureShellIn: inner amount 3, outer amount -1 (both inside).
-- FixtureShellCrossed: inner amount -2, outer amount 1 (inner + outer < 0: 3ds Max's shell is inside out).
-- FixtureShellNegative: inner amount -1, outer amount -2 (inside out too).
-- FixtureShellRim: inner amount 0, outer amount 1, the defaults (auto smooth on, 45 degrees): the rim in groups of its
-- own, hard against both surfaces.
-- One Standard material on every node.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)

	fn open_box name pos inner outer =
	(
		local b = Box name:name length:20 width:20 height:20 mapcoords:true pos:pos
		convertToPoly b
		polyop.deleteFaces b #{2}  -- face 2 of a Box is its top
		addModifier b (Shell innerAmount:inner outerAmount:outer)
		b
	)

	open_box "FixtureShellOut" [0, 0, 0] -1.0 2.0
	open_box "FixtureShellIn" [40, 0, 0] 3.0 -1.0
	open_box "FixtureShellCrossed" [80, 0, 0] -2.0 1.0
	open_box "FixtureShellNegative" [120, 0, 0] -1.0 -2.0
	open_box "FixtureShellRim" [160, 0, 0] 0.0 1.0

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\stack_shell.max" quiet:true
	"stack_shell: " + (objects.count as string) + " objects: " + \
		((for o in objects collect (o.name + " " + ((getnumverts (snapshotAsMesh o)) as string))) as string)
)
