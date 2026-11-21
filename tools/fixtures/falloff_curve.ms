-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- Falloff maps with an edited mix curve and Mix maps with Use Curve, for the curve rules of convert/texmaps.py.
-- One Editable Poly box per Standard material, its diffuse map the map named after the material:
-- FixtureCurveBezier: Perpendicular / Parallel, a Bezier point (0.4, 0.8), in handle (-0.1, -0.05), out (0.2, 0.1).
-- FixtureCurveCorner: Towards / Away, corner points (0.3, 0.6) and (0.7, 0.2) without handles.
-- FixtureCurveOvershoot: Fresnel, color 2 gray 128, a Bezier point (0.5, 0.9) whose out handle (0.2, 0.6) takes
-- the curve to 1.195 (3ds Max does not clamp it).
-- FixtureCurveClamped: Perpendicular / Parallel, points (0.3, 1.3) and (0.7, -0.2) with flat handles (+-0.1):
-- 3ds Max evaluates a point outside 0..1 at the nearest bound.
-- FixtureCurveLinear: a Falloff with its default curve (no node).
-- FixtureMixCurve: a Mix of two colors over a Bitmap mask, Use Curve, lower 0.2, upper 0.9.
-- FixtureMixCurveAmount: a Mix of two colors at mix amount 40, Use Curve, lower 0.3, upper 0.7 (no mask).
-- FixtureMixCurveStep: a Mix over a Bitmap mask, Use Curve, lower 0.6 above upper 0.4 (a step at 0.6).
-- The curve points are set through the .NET ICurve (MAXScript does not reach a map's curve control).
-- It also writes C:\maxdrop_fixtures\falloff_curve.curves.jsonl from the saved file loaded again: per Falloff its
-- curve as 3ds Max evaluates it (ICurve.GetValue, x = 0, 1/64 ... 1); per Mix with Use Curve the factor it mixes
-- by (renderMap of a copy over a constant mask, or without one at its mix amount, x = 0, 1/64 ... 1).
-- tests/unit/test_texmaps.py compares MaxDrop's curves with it. The bitmaps name files that do not exist, by a
-- bare file name.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)
	local g = (dotNetClass "Autodesk.Max.GlobalInterface").Instance

	fn num x = (local s = formattedPrint (x as float) format:".7g"; if s == "-0" then "0" else s)
	fn curveOf fo = (dotNetClass "Autodesk.Max.GlobalInterface").Instance.Animatable.GetAnimByHandle \
		(dotNetObject "System.UIntPtr" (getHandleByAnim fo.mixCurve.Curve_1))
	-- in and out are offsets from the point; flags 2 Bezier, 4 corner (3ds Max evaluates both the same). Each value
	-- as float: an integer 0 picks another Point2.Create and leaves a zero handle
	fn curvePoint g x y ix iy ox oy flags =
	(
		local p = g.CurvePoint.Create()
		p.P = g.Point2.Create (x as float) (y as float)
		p.In = g.Point2.Create (ix as float) (iy as float)
		p.Out = g.Point2.Create (ox as float) (oy as float)
		p.Flags = flags
		p
	)
	fn falloffMap g name tp pts =
	(
		local fo = Falloff name:name type:tp
		local cu = curveOf fo
		for k = 1 to pts.count do cu.Insert k pts[k] true
		fo
	)
	fn fixtureBox name m x =
	(
		local b = Box name:(name + "Box") length:10 width:10 height:10 pos:[x, 0, 0] mapcoords:true
		b.material = m
		convertToPoly b
	)

	local maps = #(
		falloffMap g "FixtureCurveBezier" 1 #(curvePoint g 0.4 0.8 -0.1 -0.05 0.2 0.1 2),
		falloffMap g "FixtureCurveCorner" 0 #(curvePoint g 0.3 0.6 0 0 0 0 4, curvePoint g 0.7 0.2 0 0 0 0 4),
		falloffMap g "FixtureCurveOvershoot" 2 #(curvePoint g 0.5 0.9 -0.2 0 0.2 0.6 2),
		falloffMap g "FixtureCurveClamped" 1 #(curvePoint g 0.3 1.3 -0.1 0 0.1 0 2, curvePoint g 0.7 -0.2 -0.1 0 0.1 0 2),
		Falloff name:"FixtureCurveLinear",
		Mix name:"FixtureMixCurve" color1:(color 20 40 60) color2:(color 220 200 180) useCurve:true lower:0.2 upper:0.9 \
			mask:(Bitmaptexture name:"FixtureMixCurveMask" filename:"curve_mask.png"),
		Mix name:"FixtureMixCurveAmount" color1:(color 0 0 0) color2:(color 255 255 255) useCurve:true lower:0.3 \
			upper:0.7 mixAmount:40.0,
		Mix name:"FixtureMixCurveStep" color1:(color 0 0 0) color2:(color 255 255 255) useCurve:true lower:0.6 \
			upper:0.4 mask:(Bitmaptexture name:"FixtureMixStepMask" filename:"step_mask.png"))
	maps[3].color2 = color 128 128 128
	for k = 1 to maps.count do
	(
		local m = StandardMaterial name:maps[k].name diffuse:(color 128 128 128)
		m.diffuseMap = maps[k]
		fixtureBox maps[k].name m ((k - 1) * 20)
	)

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\falloff_curve.max" quiet:true
	resetMaxFile #noPrompt
	loadMaxFile @"C:\maxdrop_fixtures\falloff_curve.max" quiet:true

	local f = createFile @"C:\maxdrop_fixtures\falloff_curve.curves.jsonl"
	for o in (for o in objects collect o) do
	(
		local mp = o.material.diffuseMap
		local ys = #()
		if classOf mp == Falloff then
		(
			local cu = curveOf mp
			for k = 0 to 64 do append ys (num (cu.GetValue 0 (k / 64.0) false))
		)
		else
		(
			for k = 0 to 64 do
			(
				local x = k / 64.0
				local probe = Mix color1:(color 0 0 0) color2:(color 255 255 255) useCurve:true lower:mp.lower \
					upper:mp.upper mixAmount:(if mp.mask == undefined then mp.mixAmount else x * 100.0)
				if mp.mask != undefined do probe.mask = Checker color1:(color (x * 255) (x * 255) (x * 255)) \
					color2:(color (x * 255) (x * 255) (x * 255))
				local bm = renderMap probe size:[2, 2]
				append ys (num ((getPixels bm [0, 0] 1)[1].r / 255.0))
				close bm
			)
		)
		local s = "{\"name\":\"" + mp.name + "\",\"y\":["
		for k = 1 to ys.count do s += (if k > 1 then "," else "") + ys[k]
		format "%]}\n" s to:f
	)
	close f
	"falloff_curve: " + (objects.count as string) + " objects"
)
