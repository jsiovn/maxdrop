-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- The standard primitives MaxDrop builds from their parameters (convert/primitives.py), one of each with
-- non-default segments, left as primitives (not collapsed):
-- FixtureBox: length 20, width 30, height 40; 3 x 2 x 4 segments (width, length, height).
-- FixtureBoxDown: length 10, width 12, height -15 (dragged down), Real-World Map Size.
-- FixtureBoxNoMap: 10 x 10 x 10, Generate Mapping Coords off.
-- FixtureBoxCopy: an instance of FixtureBox.
-- FixtureBoxSmooth: 10 x 10 x 10 under a TurboSmooth (one iteration).
-- FixturePlane: length 20, width 30; 3 x 2 segments.
-- FixturePyramid: width 20, depth 30, height 25; 2 x 3 x 2 segments.
-- FixtureSphere: radius 10, 12 segments.
-- FixtureGeoSphere: icosahedron, radius 10, 3 segments.
-- FixtureGeoOcta: octahedron, radius 8, 2 segments, not smoothed, Base To Pivot.
-- FixtureCylinder: radius 10, height 20; 3 height and 2 cap segments, 10 sides; turned 30 degrees about X.
-- FixtureCone: radius 8 and 3, height 20; 2 height and 2 cap segments, 9 sides; Real-World Map Size.
-- FixtureTube: radius 10 and 6, height 20; 2 height and 2 cap segments, 8 sides.
-- FixtureTorus: radius 10 and 3, 12 segments, 8 sides, rotation 20, twist 30, smooth 1 (a group per side,
-- alternating).
-- Signs and edge cases: FixtureBoxInside (width -12: 3ds Max's faces point in), FixturePlaneDown (width -12: its
-- faces point down), FixtureCylinderDown (height -10), FixtureConeTip (radius 2 of 0), FixtureTubeSwap (radius 1
-- smaller than radius 2), FixtureTorusOdd (7 segments, 5 sides, smooth 3, Real-World Map Size).
-- Real-World Map Size on the rest: FixturePlaneReal, FixturePyramidDown (height -10), FixtureSphereOdd (13
-- segments, Base To Pivot), FixtureGeoReal (tetrahedron, 4 segments), FixtureCylinderReal (2 cap segments),
-- FixtureTubeDown (height -8).
-- Slice and hemispheres (appended, so the nodes above keep their handles): FixtureSphereHemi (radius 8, 12 segments,
-- hemisphere 0.5 chopped: a ring doubled at the cut), FixtureSphereSquash (radius 6, 13 segments, hemisphere 0.3
-- squashed, Base To Pivot, Real-World Map Size), FixtureSphereSlice (9 segments, Slice From 30 To 250),
-- FixtureSphereSliceHemi (12 segments, hemisphere 0.4 squashed, Slice From 200 To 30, Real-World Map Size),
-- FixtureGeoHemi (icosahedron, 3 segments, hemisphere), FixtureGeoHemiTetra (tetrahedron, 2 segments, hemisphere,
-- Base To Pivot, Real-World Map Size), FixtureCylinderSlice (2 height and 2 cap segments, 7 sides, From 20 To 250),
-- FixtureCylinderSliceDown (height -8, 6 sides, From 300 To 45, Real-World Map Size), FixtureConeSlice (radius 6
-- and 2, 8 sides, From 40 To 160, Real-World Map Size), FixtureTubeSlice (7 sides, From 20 To 250),
-- FixtureTorusSlice (9 segments, 6 sides, twist 45, smooth 3, From 20 To 250, Real-World Map Size).
-- One Standard material on every node.
-- It also writes C:\maxdrop_fixtures\primitives.mesh.jsonl: per primitive node, its base object's TriMesh (object
-- space): vertices, and per triangle its vertices, edge visibility, material ID, smoothing groups and channel 1's
-- map vertices. tests/unit/test_primitives.py compares MaxDrop's meshes with it.
-- Authored for MaxDrop's tests (see CONTRIBUTING.md, "Test files"): it resets the scene, so run it in a 3ds Max
-- session with nothing to keep, then sanitize and check the saved file before it goes into tests/fixtures/.
(
	resetMaxFile #noPrompt
	IDisplayGamma.colorCorrectionMode = #none  -- the fixtures are saved with the gamma off (CONTRIBUTING.md)

	fn num x = (local s = formattedPrint (x as float) format:".7g"; if s == "-0" then "0" else s)
	fn p3 p = "[" + num p.x + "," + num p.y + "," + num p.z + "]"
	fn flag b = if b then "1" else "0"
	fn dumpMesh o =
	(
		local ss = stringStream ""
		local m = o.baseObject.mesh
		format "{\"name\":\"%\",\"class\":\"%\",\"verts\":[" o.name ((classOf o) as string) to:ss
		for i = 1 to m.numverts do (if i > 1 do format "," to:ss; format "%" (p3 (getVert m i)) to:ss)
		format "],\"faces\":[" to:ss
		local hasMap = meshop.getMapSupport m 1
		for f = 1 to m.numfaces do
		(
			if f > 1 do format "," to:ss
			local v = getFace m f
			format "{\"v\":[%,%,%],\"vis\":[%,%,%],\"mat\":%,\"sg\":%" ((v.x as integer) - 1) ((v.y as integer) - 1) \
				((v.z as integer) - 1) (flag (getEdgeVis m f 1)) (flag (getEdgeVis m f 2)) (flag (getEdgeVis m f 3)) \
				(getFaceMatID m f) (getFaceSmoothGroup m f) to:ss
			if hasMap do
			(
				local t = meshop.getMapFace m 1 f
				format ",\"uv\":[%,%,%]" (p3 (meshop.getMapVert m 1 t.x)) (p3 (meshop.getMapVert m 1 t.y)) \
					(p3 (meshop.getMapVert m 1 t.z)) to:ss
			)
			format "}" to:ss
		)
		format "]}" to:ss
		ss as string
	)

	local firstBox = Box name:"FixtureBox" length:20 width:30 height:40 widthsegs:3 lengthsegs:2 heightsegs:4 \
		mapcoords:true pos:[0, 0, 0]
	Box name:"FixtureBoxDown" length:10 width:12 height:-15 mapcoords:true realWorldMapSize:true pos:[40, 0, 0]
	Box name:"FixtureBoxNoMap" length:10 width:10 height:10 mapcoords:false pos:[70, 0, 0]
	local copyOf = instance firstBox
	copyOf.name = "FixtureBoxCopy"
	copyOf.pos = [0, -40, 0]
	local smoothed = Box name:"FixtureBoxSmooth" length:10 width:10 height:10 mapcoords:true pos:[40, -40, 0]
	addModifier smoothed (TurboSmooth iterations:1)
	Plane name:"FixturePlane" length:20 width:30 widthsegs:3 lengthsegs:2 mapcoords:true pos:[100, 0, 0]
	Pyramid name:"FixturePyramid" width:20 depth:30 height:25 widthsegs:2 depthsegs:3 heightsegs:2 mapcoords:true \
		pos:[140, 0, 0]
	Sphere name:"FixtureSphere" radius:10 segs:12 smooth:true mapcoords:true pos:[0, 60, 10]
	GeoSphere name:"FixtureGeoSphere" radius:10 segs:3 baseType:2 smooth:true mapcoords:true pos:[40, 60, 10]
	GeoSphere name:"FixtureGeoOcta" radius:8 segs:2 baseType:1 smooth:false baseToPivot:true mapcoords:true \
		pos:[70, 60, 0]
	local cyl = Cylinder name:"FixtureCylinder" radius:10 height:20 heightsegs:3 capsegs:2 sides:10 smooth:true \
		mapcoords:true pos:[100, 60, 0]
	rotate cyl (eulerangles 30 0 0)
	Cone name:"FixtureCone" radius1:8 radius2:3 height:20 heightsegs:2 capsegs:2 sides:9 smooth:true mapcoords:true \
		realWorldMapSize:true pos:[140, 60, 0]
	Tube name:"FixtureTube" radius1:10 radius2:6 height:20 heightsegs:2 capsegs:2 sides:8 smooth:true mapcoords:true \
		pos:[0, 110, 0]
	Torus name:"FixtureTorus" radius1:10 radius2:3 segs:12 sides:8 tubeRotation:20 tubeTwist:30 smooth:1 \
		mapcoords:true pos:[40, 110, 0]
	Box name:"FixtureBoxInside" length:10 width:-12 height:8 widthsegs:2 mapcoords:true pos:[0, 160, 0]
	Plane name:"FixturePlaneDown" length:10 width:-12 widthsegs:2 lengthsegs:1 mapcoords:true pos:[30, 160, 0]
	Cylinder name:"FixtureCylinderDown" radius:5 height:-10 heightsegs:1 capsegs:1 sides:7 mapcoords:true \
		pos:[60, 160, 0]
	Cone name:"FixtureConeTip" radius1:5 radius2:0 height:10 heightsegs:2 capsegs:1 sides:7 mapcoords:true \
		pos:[90, 160, 0]
	Tube name:"FixtureTubeSwap" radius1:3 radius2:5 height:10 heightsegs:1 capsegs:1 sides:7 mapcoords:true \
		pos:[120, 160, 0]
	Torus name:"FixtureTorusOdd" radius1:8 radius2:2 segs:7 sides:5 smooth:3 mapcoords:true realWorldMapSize:true \
		pos:[150, 160, 0]
	Plane name:"FixturePlaneReal" length:10 width:12 widthsegs:2 lengthsegs:3 mapcoords:true realWorldMapSize:true \
		pos:[0, 210, 0]
	Pyramid name:"FixturePyramidDown" width:10 depth:14 height:-10 widthsegs:2 depthsegs:1 heightsegs:2 \
		mapcoords:true realWorldMapSize:true pos:[30, 210, 0]
	Sphere name:"FixtureSphereOdd" radius:6 segs:13 recenter:true mapcoords:true realWorldMapSize:true \
		pos:[60, 210, 0]
	GeoSphere name:"FixtureGeoReal" radius:6 segs:4 baseType:0 mapcoords:true realWorldMapSize:true pos:[90, 210, 0]
	Cylinder name:"FixtureCylinderReal" radius:5 height:10 heightsegs:2 capsegs:2 sides:7 mapcoords:true \
		realWorldMapSize:true pos:[120, 210, 0]
	Tube name:"FixtureTubeDown" radius1:5 radius2:3 height:-8 heightsegs:1 capsegs:1 sides:7 mapcoords:true \
		realWorldMapSize:true pos:[150, 210, 0]
	Sphere name:"FixtureSphereHemi" radius:8 segs:12 hemisphere:0.5 chop:0 mapcoords:true pos:[0, 260, 0]
	Sphere name:"FixtureSphereSquash" radius:6 segs:13 hemisphere:0.3 chop:1 recenter:true mapcoords:true \
		realWorldMapSize:true pos:[30, 260, 0]
	Sphere name:"FixtureSphereSlice" radius:6 segs:9 slice:true sliceFrom:30 sliceTo:250 mapcoords:true \
		pos:[60, 260, 0]
	Sphere name:"FixtureSphereSliceHemi" radius:6 segs:12 hemisphere:0.4 chop:1 slice:true sliceFrom:200 \
		sliceTo:30 mapcoords:true realWorldMapSize:true pos:[90, 260, 0]
	GeoSphere name:"FixtureGeoHemi" radius:8 segs:3 baseType:2 hemisphere:true mapcoords:true pos:[120, 260, 0]
	GeoSphere name:"FixtureGeoHemiTetra" radius:6 segs:2 baseType:0 hemisphere:true baseToPivot:true mapcoords:true \
		realWorldMapSize:true pos:[150, 260, 0]
	Cylinder name:"FixtureCylinderSlice" radius:5 height:10 heightsegs:2 capsegs:2 sides:7 slice:true sliceFrom:20 \
		sliceTo:250 mapcoords:true pos:[0, 310, 0]
	Cylinder name:"FixtureCylinderSliceDown" radius:5 height:-8 heightsegs:1 capsegs:1 sides:6 slice:true \
		sliceFrom:300 sliceTo:45 mapcoords:true realWorldMapSize:true pos:[30, 310, 0]
	Cone name:"FixtureConeSlice" radius1:6 radius2:2 height:10 heightsegs:2 capsegs:1 sides:8 slice:true \
		sliceFrom:40 sliceTo:160 mapcoords:true realWorldMapSize:true pos:[60, 310, 0]
	Tube name:"FixtureTubeSlice" radius1:6 radius2:4 height:8 heightsegs:1 capsegs:1 sides:7 slice:true \
		sliceFrom:20 sliceTo:250 mapcoords:true pos:[90, 310, 0]
	Torus name:"FixtureTorusSlice" radius1:8 radius2:2 segs:9 sides:6 tubeTwist:45 smooth:3 slice:true sliceFrom:20 \
		sliceTo:250 mapcoords:true realWorldMapSize:true pos:[120, 310, 0]

	local mat = StandardMaterial name:"FixtureGrey" diffuse:(color 128 128 128)
	for o in objects do o.material = mat

	makeDir @"C:\maxdrop_fixtures" all:true
	saveMaxFile @"C:\maxdrop_fixtures\primitives.max" quiet:true
	local f = createFile @"C:\maxdrop_fixtures\primitives.mesh.jsonl"
	for o in objects where o != copyOf do format "%\n" (dumpMesh o) to:f
	close f
	"primitives: " + (objects.count as string) + " objects"
)
