-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- The same box (10 x 20 x 30 system units at [5,0,0]) saved with the system unit set to inches. The three
-- units fixtures (units_mm, units_cm, units_in) differ only in that setting; the display unit is fixed to metric
-- millimeters. The unit settings found are restored afterwards: they are 3ds Max preferences, not only scene data.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	local before = #(units.SystemType, units.SystemScale, units.DisplayType, units.MetricType)
	fn restore before =
	(
		units.SystemType = before[1]
		units.SystemScale = before[2]
		units.DisplayType = before[3]
		units.MetricType = before[4]
	)
	try
	(
		resetMaxFile #noPrompt
		units.SystemType = #inches
		units.SystemScale = 1.0
		units.DisplayType = #metric
		units.MetricType = #millimeters
		local mat = StandardMaterial name:"FixtureRed" diffuse:(color 200 40 30)
		local b = Box name:"FixtureUnitBox" length:20 width:10 height:30 pos:[5,0,0] mapcoords:true
		b.material = mat
		convertToPoly b
		makeDir @"C:\maxdrop_fixtures" all:true
		saveMaxFile @"C:\maxdrop_fixtures\units_in.max" quiet:true
	)
	catch
	(
		restore before
		throw()
	)
	restore before
	"units_in: saved; system unit back to " + (units.SystemType as string)
)
