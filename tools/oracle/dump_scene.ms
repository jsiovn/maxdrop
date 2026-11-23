-- SPDX-FileCopyrightText: 2026 jsiovn
--
-- SPDX-License-Identifier: GPL-3.0-or-later

-- The oracle: what 3ds Max itself says about a scene, written as deterministic JSON, so that MaxDrop's reader can
-- be checked against the truth instead of against itself. docs/ORACLE.md describes every field.
--
--   fileIn @"<repo>\tools\oracle\dump_scene.ms"
--   MaxDropOracle.dumpScene @"<out>.json"                 -- the scene that is open
--   MaxDropOracle.dumpFile @"<scene>.max" @"<out>.json"   -- resets, loads, dumps (the open scene is lost)
--   MaxDropOracle.dumpFolder @"<dir>" @"<outDir>"         -- every <dir>\*.max into <outDir>\<name>.oracle.json
--
-- The output is byte-identical for the same file: keys in sorted order, floats with 6 significant digits, every
-- character outside printable ASCII escaped, LF line ends. Only the base name of a file is written, never a path.

global MaxDropOracle

struct MaxDropOracleStruct
(
	version = 14,

	fn num v =
	(
		if v == undefined do return "null"
		local s = formattedPrint (v as float) format:".6g"
		-- inf and nan print as "inf", "nan", "1.#INF" ...: none of them is a JSON number
		if (findString s "n") != undefined or (findString s "N") != undefined or (findString s "#") != undefined do
			return "null"
		if s == "-0" do s = "0"
		s
	),

	fn intOrNull v = if v == undefined then "null" else ((v as integer) as string),

	fn bool v = if v == true then "true" else "false",

	fn str s =
	(
		local ss = stringStream ""
		format "\"" to:ss
		for i = 1 to s.count do
		(
			local c = s[i]
			local n = bit.charAsInt c
			case of
			(
				(c == "\""): format "\\\"" to:ss
				(c == "\\"): format "\\\\" to:ss
				(n < 32 or n > 126): format "\\u%" (formattedPrint n format:"04x") to:ss
				default: format "%" c to:ss
			)
		)
		format "\"" to:ss
		ss as string
	),

	fn list items =
	(
		local ss = stringStream ""
		format "[" to:ss
		for i = 1 to items.count do
		(
			if i > 1 do format ", " to:ss
			format "%" items[i] to:ss
		)
		format "]" to:ss
		ss as string
	),

	fn vec p = if p == undefined then "null" else list #(num p.x, num p.y, num p.z),

	fn quat4 q = list #(num q.x, num q.y, num q.z, num q.w),

	fn mat12 m =
	(
		local out = #()
		for r in #(m.row1, m.row2, m.row3, m.row4) do join out #(num r.x, num r.y, num r.z)
		list out
	),

	fn cid c = list #(str ("0x" + (formattedPrint c.classID[1] format:"08x")), str ("0x" + (formattedPrint c.classID[2] format:"08x"))),

	-- callers pass the keys sorted: nothing here sorts them
	fn obj pairs indent =
	(
		local pad = ""
		for i = 1 to indent do pad += " "
		local ss = stringStream ""
		format "{\n" to:ss
		for i = 1 to pairs.count do
		(
			format "%  %: %" pad (str pairs[i][1]) pairs[i][2] to:ss
			if i < pairs.count do format "," to:ss
			format "\n" to:ss
		)
		format "%}" pad to:ss
		ss as string
	),

	fn inline pairs =
	(
		local items = for p in pairs collect ((str p[1]) + ": " + p[2])
		local ss = stringStream ""
		format "{" to:ss
		for i = 1 to items.count do
		(
			if i > 1 do format ", " to:ss
			format "%" items[i] to:ss
		)
		format "}" to:ss
		ss as string
	),

	fn block items indent =
	(
		if items.count == 0 do return "[]"
		local pad = ""
		for i = 1 to indent do pad += " "
		local ss = stringStream ""
		format "[\n" to:ss
		for i = 1 to items.count do
		(
			format "%  %" pad items[i] to:ss
			if i < items.count do format "," to:ss
			format "\n" to:ss
		)
		format "%]" pad to:ss
		ss as string
	),

	fn walk n acc =
	(
		append acc n
		for c in n.children do walk c acc
		acc
	),

	fn sceneNodes =
	(
		local acc = #()
		for c in rootNode.children do walk c acc
		acc
	),

	fn baseCounts b =
	(
		case classOf b of
		(
			Editable_Poly: #(polyop.getNumVerts b, polyop.getNumFaces b)
			Editable_mesh: #(b.mesh.numverts, b.mesh.numfaces)
			default: #(undefined, undefined)
		)
	),

	fn evalCounts n =
	(
		if superClassOf n != GeometryClass do return #(undefined, undefined)
		try
		(
			local m = snapshotAsMesh n
			local r = #(m.numverts, m.numfaces)
			free m
			r
		)
		catch #(undefined, undefined)
	),

	fn instanceHandles n =
	(
		local b = n.baseObject
		local hs = for d in (refs.dependentNodes b) where isValidNode d and d.baseObject == b collect d.handle
		if (findItem hs n.handle) == 0 do append hs n.handle
		sort hs
	),

	-- the modifier context of m on node n: its transform and box (an empty box is +1e30 .. -1e30), and the flags
	fn modJson n m =
	(
		local tm = try (getModContextTM n m) catch undefined
		inline #( \
			#("class_id", cid (classOf m)), \
			#("class_name", str ((classOf m) as string)), \
			#("context_bbox_max", vec (try (getModContextBBoxMax n m) catch undefined)), \
			#("context_bbox_min", vec (try (getModContextBBoxMin n m) catch undefined)), \
			#("context_tm", if tm == undefined then "null" else mat12 tm), \
			#("enabled", bool m.enabled), \
			#("enabled_in_renders", bool m.enabledInRenders), \
			#("enabled_in_views", bool m.enabledInViews), \
			#("name", str m.name) \
		)
	),

	-- the base object of a shape node as 3ds Max's own Bezier: a copy of the node without its modifiers, collapsed to
	-- an Editable Spline; knots and vectors in object space (getKnotPoint answers in world space)
	fn shapeJson n =
	(
		local b = n.baseObject
		if superClassOf b != shape do return "null"
		local t = copy n
		while t.modifiers.count > 0 do deleteModifier t 1
		convertToSplineShape t
		local inv = inverse t.objectTransform
		local splines = #()
		for s = 1 to numSplines t do
		(
			local segs = numSegments t s
			local knots = for k = 1 to numKnots t s collect inline #( \
				#("in", vec ((getInVec t s k) * inv)), \
				#("material", if k <= segs then intOrNull (getMaterialID t s k) else "null"), \
				#("mid", if k <= segs then vec ((interpBezier3D t s k 0.5) * inv) else "null"), \
				#("out", vec ((getOutVec t s k) * inv)), \
				#("pos", vec ((getKnotPoint t s k) * inv)), \
				#("segment", if k <= segs then str ((getSegmentType t s k) as string) else "null"), \
				#("type", str ((getKnotType t s k) as string)) \
			)
			append splines (obj #(#("closed", bool (isClosed t s)), #("knots", block knots 12)) 10)
		)
		delete t
		obj #( \
			#("adaptive", bool b.adaptive), \
			#("angle", num b.render_angle), \
			#("display_render_mesh", bool b.render_displayRenderMesh), \
			#("length", num b.render_length), \
			#("optimize", bool b.optimize), \
			#("rectangular", bool b.render_rectangular), \
			#("renderable", bool b.render_renderable), \
			#("sides", intOrNull b.render_sides), \
			#("splines", block splines 8), \
			#("steps", intOrNull b.steps), \
			#("thickness", num b.render_thickness), \
			#("width", num b.render_width) \
		) 6
	),

	-- the map channels the node's UVW Map modifiers write, evaluated: per triangle corner of snapshotAsMesh (world
	-- space) the position, the face normal and the map vertex; null without a UVW Map
	fn evalMapsJson n =
	(
		local chans = #()
		for m in n.modifiers where classOf m == Uvwmap do
		(
			local ch = if m.channel == 1 then 0 else m.mapChannel
			appendIfUnique chans ch
		)
		if chans.count == 0 or superClassOf n != GeometryClass do return "null"
		sort chans
		local s = try (snapshotAsMesh n) catch undefined
		if s == undefined do return "null"
		local items = #()
		for ch in chans do
		(
			local corners = #()
			if meshop.getMapSupport s ch do for f = 1 to s.numfaces do
			(
				local fc = getFace s f
				local mf = meshop.getMapFace s ch f
				local nrm = getFaceNormal s f
				for k = 1 to 3 do
				(
					local p = getVert s fc[k]
					local t = meshop.getMapVert s ch mf[k]
					append corners (list #(num p.x, num p.y, num p.z, num nrm.x, num nrm.y, num nrm.z, num t.x, num t.y, num t.z))
				)
			)
			append items (obj #(#("channel", ch as string), #("corners", block corners 10)) 8)
		)
		free s
		block items 6
	),

	-- the root of face f in the union-find array par (path halving)
	fn ufRoot par f =
	(
		while par[f] != f do
		(
			par[f] = par[par[f]]
			f = par[f]
		)
		f
	),

	-- how a TriMesh is shaded by its smoothing groups: flat, its triangles of group 0; hard_edges, the edges with
	-- exactly two triangles, both smoothed, without a common group; regions, the smoothed triangles joined through
	-- the edges of two triangles with a common group, counted. An edge is a pair of vertex indices (an unwelded
	-- seam is no edge), found in a list per lower vertex: no meshop call per edge, which took minutes on 100,000
	-- triangles.
	fn smoothJson s =
	(
		local nf = s.numfaces
		local g = for f = 1 to nf collect getFaceSmoothGroup s f
		local par = for f = 1 to nf collect f
		local edges = for v = 1 to s.numverts collect #()  -- per lower vertex: higher vertex, face, ...
		for f = 1 to nf do
		(
			local fc = getFace s f
			local vs = #(fc.x as integer, fc.y as integer, fc.z as integer)
			for k = 1 to 3 do
			(
				local a = vs[k]
				local b = vs[(mod k 3) as integer + 1]
				if a > b do swap a b
				append edges[a] b
				append edges[a] f
			)
		)
		local hard = 0
		for l in edges where l.count > 2 do
		(
			local done = #{}
			for i = 1 to l.count by 2 where not done[i] do
			(
				local fs = #(l[i + 1])
				for j = i + 2 to l.count by 2 where l[j] == l[i] do
				(
					append fs l[j + 1]
					done[j] = true
				)
				if fs.count == 2 and g[fs[1]] != 0 and g[fs[2]] != 0 do
				(
					if (bit.and g[fs[1]] g[fs[2]]) != 0 then
					(
						local a = ufRoot par fs[1]
						local b = ufRoot par fs[2]
						if a != b do par[a] = b
					)
					else hard += 1
				)
			)
		)
		local flat = 0
		local roots = #{}
		for f = 1 to nf do if g[f] == 0 then flat += 1 else roots[ufRoot par f] = true
		inline #(#("flat", flat as string), #("hard_edges", hard as string), #("regions", roots.numberSet as string))
	),

	-- what an evaluated mesh carries per face: the triangles of each material ID (1-based, as 3ds Max shows it) by
	-- the way they face in object space (the vertices of snapshotAsMesh taken back by the inverse object transform,
	-- the winding normal's z: up, down, side; a degenerate face is side), map channel 1's vertex count and range over
	-- the map vertices its faces use (and, under an Extrude, every corner: object-space position, winding normal and
	-- map vertex), and its shading by smoothing groups; null unless a modifier made the mesh
	fn evalMeshJson n =
	(
		if n.modifiers.count == 0 or superClassOf n != GeometryClass do return "null"
		local s = try (snapshotAsMesh n) catch undefined
		if s == undefined do return "null"
		local inv = inverse n.objectTransform
		local extruded = false
		for m in n.modifiers where classOf m == Extrude do extruded = true
		local corners = if extruded and (meshop.getMapSupport s 1) then #() else undefined
		local hist = #()
		for f = 1 to s.numfaces do
		(
			local fc = getFace s f
			local a = (getVert s fc[1]) * inv
			local nrm = cross (((getVert s fc[2]) * inv) - a) (((getVert s fc[3]) * inv) - a)
			local unit = if (length nrm) < 1e-12 then [0, 0, 0] else normalize nrm
			local z = unit.z
			if corners != undefined do
			(
				local mf = meshop.getMapFace s 1 f
				for c = 1 to 3 do
				(
					local p = (getVert s fc[c]) * inv
					local t = meshop.getMapVert s 1 mf[c]
					append corners (list #(num p.x, num p.y, num p.z, num unit.x, num unit.y, num unit.z, num t.x, num t.y, num t.z))
				)
			)
			local k = if z > 1e-4 then 2 else (if z < -1e-4 then 3 else 4)
			local id = getFaceMatID s f
			while hist.count < id do append hist #(hist.count + 1, 0, 0, 0)
			hist[id][k] += 1
		)
		local ids = for h in hist where (h[2] + h[3] + h[4]) > 0 collect list (for x in h collect x as string)
		local map1 = "null"
		if meshop.getMapSupport s 1 do
		(
			local used = #{}
			for f = 1 to s.numfaces do
			(
				local mf = meshop.getMapFace s 1 f
				for x in #(mf.x, mf.y, mf.z) do used[x as integer] = true
			)
			local lo = undefined
			local hi = undefined
			for i in used do
			(
				local t = meshop.getMapVert s 1 i
				if lo == undefined then (lo = t; hi = t)
				else
				(
					lo = [amin lo.x t.x, amin lo.y t.y, amin lo.z t.z]
					hi = [amax hi.x t.x, amax hi.y t.y, amax hi.z t.z]
				)
			)
			local pairs = #(#("corners", "null"), #("count", (meshop.getNumMapVerts s 1) as string), #("max", vec hi), #("min", vec lo))
			if corners == undefined then map1 = inline pairs
			else
			(
				pairs[1][2] = block corners 10
				map1 = obj pairs 8
			)
		)
		local smoothing = smoothJson s
		free s
		obj #(#("map_channel_1", map1), #("material_ids", list ids), #("smoothing", smoothing)) 6
	),

	-- a camera's state as 3ds Max (and V-Ray) render it: CameraObject::EvalCameraState at frame 0, the horizontal FOV in
	-- degrees after zoom, lens breathing and a specified FOV. A lens shift changes the state's FOV (Physical and
	-- VRayPhysicalCamera) but not the rendered one, which renders show: the state is read with the shift at 0, then
	-- the shift is put back.
	fn cameraJson n =
	(
		local b = n.baseObject
		if superClassOf b != camera do return "null"
		local g = (dotNetClass "Autodesk.Max.GlobalInterface").Instance
		local a = g.Animatable.GetAnimByHandle (dotNetObject "System.UIntPtr" (getHandleByAnim b))
		local cs = g.CameraState.Create()
		local iv = g.Interval.Create()
		iv.SetInfinite()
		local shifts = for p in #(#horizontal_shift, #vertical_shift) where isProperty b p collect #(p, getProperty b p)
		for s in shifts do setProperty b s[1] 0.0
		a.EvalCameraState 0 iv cs
		for s in shifts do setProperty b s[1] s[2]
		local mc = cs.ManualClip
		inline #(#("fov", num (radToDeg cs.Fov)), #("hither", num cs.Hither), #("manual_clip", bool (mc == true or mc == 1)), #("ortho", bool cs.IsOrtho), #("tdist", num cs.Tdist), #("yon", num cs.Yon))
	),

	-- the render size and the camera of the view 3ds Max renders: the locked render view, else the active viewport
	fn renderJson =
	(
		local idx = if rendUseActiveView then viewport.activeViewport else rendViewIndex
		local cam = try (viewport.getCamera index:idx) catch undefined
		if cam != undefined and superClassOf cam.baseObject != camera do cam = undefined
		inline #(#("camera", if cam == undefined then "null" else cam.handle as string), #("height", renderHeight as string), #("pixel_aspect", num renderPixelAspect), #("width", renderWidth as string))
	),

	fn nodeJson n index mats =
	(
		local b = n.baseObject
		local bc = baseCounts b
		local ev = evalCounts n
		-- node.min / node.max transform the object's local box (loose under rotation); this one is the tight box of
		-- the evaluated points in world space
		local bb = try (nodeGetBoundingBox n (matrix3 1)) catch undefined
		local bmin = if bb == undefined then "null" else vec bb[1]
		local bmax = if bb == undefined then "null" else vec bb[2]
		local mods = for m in n.modifiers collect modJson n m
		local matIndex = if n.material == undefined then "null" else (((findItem mats n.material) - 1) as string)
		local parent = if n.parent == undefined then "null" else (n.parent.handle as string)
		-- the node's own flags: MAXScript's isHidden and isFrozen also say true for a node on a hidden or frozen layer
		local inode = (dotNetClass "Autodesk.Max.GlobalInterface").Instance.COREInterface.GetINodeByHandle n.handle
		obj #( \
			#("base_class_id", cid (classOf b)), \
			#("base_class_name", str ((classOf b) as string)), \
			#("base_faces", intOrNull bc[2]), \
			#("base_superclass", ((classOf b).superclassID as integer) as string), \
			#("base_verts", intOrNull bc[1]), \
			#("bbox_max", bmax), \
			#("bbox_min", bmin), \
			#("camera", cameraJson n), \
			#("cast_shadows", bool n.castShadows), \
			#("eval_faces", intOrNull ev[2]), \
			#("eval_maps", evalMapsJson n), \
			#("eval_mesh", evalMeshJson n), \
			#("eval_verts", intOrNull ev[1]), \
			#("frozen", bool inode.IsObjectFrozen), \
			#("handle", n.handle as string), \
			#("hidden", bool inode.IsObjectHidden), \
			#("index", index as string), \
			#("instances", list (for h in (instanceHandles n) collect h as string)), \
			#("layer", str n.layer.name), \
			#("material", matIndex), \
			#("modifiers", list mods), \
			#("name", str n.name), \
			#("object_transform", mat12 n.objectTransform), \
			#("offset_pos", vec n.objectOffsetPos), \
			#("offset_rot", quat4 n.objectOffsetRot), \
			#("offset_scale", vec n.objectOffsetScale), \
			#("parent", parent), \
			#("receive_shadows", bool n.receiveShadows), \
			#("render_by_layer", bool n.renderByLayer), \
			#("renderable", bool n.renderable), \
			#("shape", shapeJson n), \
			#("transform", mat12 n.transform) \
		) 4
	),

	fn subCount m = try (getNumSubMtls m) catch 0,

	fn materialJson m index =
	(
		inline #( \
			#("class_id", cid (classOf m)), \
			#("class_name", str ((classOf m) as string)), \
			#("index", index as string), \
			#("name", str m.name), \
			#("sub_count", (subCount m) as string) \
		)
	),

	-- The material graph: every material and map reachable from a node's material (sub-materials, then sub-maps,
	-- depth first), with every parameter of its parameter blocks by id, read through the SDK's .NET wrapper because
	-- MAXScript names parameters but never gives their ids. Values are the stored ones: radians, fractions, colors
	-- as 0..1 floats, not the degrees and percentages MAXScript shows.
	fn animOf v = (dotNetClass "Autodesk.Max.GlobalInterface").Instance.Animatable.GetAnimByHandle (dotNetObject "System.UIntPtr" (getHandleByAnim v)),

	fn ptrOf a = if a == undefined then undefined else a.INativeObject__NativePointer,

	fn isGraphValue v = v != undefined and ((superClassOf v) == material or (superClassOf v) == textureMap),

	-- sub-materials and sub-maps, then every material or map a property holds: getSubMtl misses some (a
	-- Multi/Sub-Object answers by material ID and skips one of IDs 1, 3, 7), the property lists do not
	fn graphVisit m acc =
	(
		if m == undefined or (findItem acc m) > 0 do return acc
		append acc m
		local n = try (getNumSubMtls m) catch 0
		for i = 1 to n do graphVisit (getSubMtl m i) acc
		local k = try (getNumSubTexmaps m) catch 0
		for i = 1 to k do graphVisit (getSubTexmap m i) acc
		local vals = #()
		for p in (getPropNames m) do append vals (try (getProperty m p) catch undefined)
		for v in vals do
		(
			if isGraphValue v do graphVisit v acc
			if classOf v == Array or classOf v == ArrayParameter do for x in v do (if isGraphValue x do graphVisit x acc)
		)
		acc
	),

	-- acc holds the graph's pointers (ptrOf), in graph order
	fn graphIndex a acc =
	(
		local p = ptrOf a
		local i = if p == undefined then 0 else findItem acc p
		if i == 0 then "null" else ((i - 1) as string)
	),

	fn rgb3 c = list #(num c.r, num c.g, num c.b),
	fn rgb4 c = list #(num c.r, num c.g, num c.b, num c.a),
	fn xy p = list #(num p.x, num p.y),
	fn xyzw p = list #(num p.x, num p.y, num p.z, num p.w),
	fn strOrNull s = if s == undefined then "null" else str s,
	fn baseOrNull s = if s == undefined then "null" else str (filenameFromPath s),

	fn pbValue pb id tp tab acc =
	(
		local base = bit.and tp 0x7FF
		case of
		(
			((findItem #(0, 5, 6, 7, 11) base) > 0): num (pb.GetFloat id 0 tab)
			((findItem #(1, 4, 12, 13, 19) base) > 0): (pb.GetInt id 0 tab) as string
			(base == 2 or base == 10): rgb3 (pb.GetColor id 0 tab)
			(base == 3): vec (pb.GetPoint3 id 0 tab)
			(base == 22): xyzw (pb.GetPoint4 id 0 tab)
			(base == 23): rgb4 (pb.GetAColor id 0 tab)
			(base == 30): xy (pb.GetPoint2 id 0 tab)
			(base == 8): strOrNull (pb.GetStr id 0 tab)
			(base == 9): baseOrNull (pb.GetStr id 0 tab)
			(base == 14): graphIndex (pb.GetMtl id 0 tab) acc
			(base == 15): graphIndex (pb.GetTexmap id 0 tab) acc
			default: "null"
		)
	),

	-- a separate function: a for-collect over a local inside an if-expression breaks MAXScript's closures
	fn tabValue pb id tp acc =
	(
		local items = #()
		for k = 0 to (pb.Count id) - 1 do append items (pbValue pb id tp k acc)
		list items
	),

	fn classPair c = list #(str ("0x" + (formattedPrint c.ClassID.PartA format:"08x")), str ("0x" + (formattedPrint c.ClassID.PartB format:"08x"))),

	-- the controllers of a block's animated parameters (one per table element that has one): the controller's class,
	-- the block reference that holds it (-1: none of them) and the parameter's value at frame 0
	fn controllersOf pb id tp acc =
	(
		local out = #()
		local n = if (bit.and tp 0x800) != 0 then pb.Count id else 1
		for k = 0 to n - 1 do
		(
			local c = try (pb.GetControllerByID id k) catch undefined
			if c != undefined do
			(
				local slot = -1
				for s = 0 to pb.NumRefs - 1 do
				(
					local x = pb.GetReference s
					if x != undefined and (ptrOf x) == (ptrOf c) do slot = s
				)
				append out (inline #(#("class_id", classPair c), #("id", (id as integer) as string), #("slot", slot as string), #("tab", k as string), #("value", pbValue pb id tp k acc)))
			)
		)
		out
	),

	fn pb2Json pb r acc =
	(
		local items = #()
		local ctrls = #()
		for i = 0 to pb.NumParams - 1 do
		(
			local id = pb.IndextoID i
			local d = pb.GetParamDef id
			local tp = d.Type.value__
			local v = if (bit.and tp 0x800) != 0 then tabValue pb id tp acc else pbValue pb id tp 0 acc
			append items (inline #(#("id", (id as integer) as string), #("name", str d.IntName), #("transient", bool ((bit.and (d.Flags as integer) 2) != 0)), #("type", tp as string), #("value", v)))
			join ctrls (controllersOf pb id tp acc)
		)
		obj #(#("block_id", (pb.Id as integer) as string), #("controllers", block ctrls 8), #("kind", str "pb2"), #("params", block items 8), #("ref", r as string)) 6
	),

	fn pb1Value pb i tp =
	(
		case tp of
		(
			0: num (pb.GetFloat i 0)
			1: (pb.GetInt i 0) as string
			4: (pb.GetInt i 0) as string
			2: rgb3 (pb.GetColor i 0)
			3: vec (pb.GetPoint3 i 0)
			default: "null"
		)
	),

	fn pb1Json pb r =
	(
		local items = #()
		for i = 0 to pb.NumParams - 1 do
		(
			local tp = (pb.GetParameterType i).value__
			append items (inline #(#("index", i as string), #("type", tp as string), #("value", pb1Value pb i tp)))
		)
		obj #(#("block_id", "null"), #("controllers", "[]"), #("kind", str "pb1"), #("params", block items 8), #("ref", r as string)) 6
	),

	fn ownBlocks t acc =
	(
		local out = #()
		for r = 0 to t.NumRefs - 1 do
		(
			local x = t.GetReference r
			if x != undefined and x.SuperClassID.value__ == 0x82 do append out (pb2Json x r acc)
			if x != undefined and x.SuperClassID.value__ == 0x8 do append out (pb1Json x r)
		)
		out
	),

	fn partJson t r acc =
	(
		obj #(#("blocks", block (ownBlocks t acc) 6), #("class_id", classPair t), #("ref", r as string)) 6
	),

	-- the parameter blocks among the references of a, and the parts that carry blocks of their own (a map's
	-- coordinates and output, a Standard material's shader and sampler)
	fn blocksOf a acc =
	(
		local blocks = #()
		local parts = #()
		for r = 0 to a.NumRefs - 1 do
		(
			local t = a.GetReference r
			if t != undefined do
			(
				local sc = t.SuperClassID.value__
				case of
				(
					(sc == 0x82): append blocks (pb2Json t r acc)
					(sc == 0x8): append blocks (pb1Json t r)
					-- UVGen, XYZGen, TexOutput, Shader, Sampler: nothing else is followed (a map can reference nodes)
					((findItem #(0xC20, 0xC30, 0xC40, 0x10B0, 0x1110) sc) > 0): append parts (partJson t r acc)
				)
			)
		)
		#(blocks, parts)
	),

	fn graphEntryJson m index graph acc =
	(
		local a = animOf m
		local bp = blocksOf a acc
		local subs = #()
		local n = try (getNumSubMtls m) catch 0
		for i = 1 to n do
		(
			local s = getSubMtl m i
			if s != undefined do append subs (inline #(#("kind", str "material"), #("slot", (i - 1) as string), #("target", ((findItem graph s) - 1) as string)))
		)
		local k = try (getNumSubTexmaps m) catch 0
		for i = 1 to k do
		(
			local s = getSubTexmap m i
			if s != undefined do append subs (inline #(#("kind", str "map"), #("slot", (i - 1) as string), #("target", ((findItem graph s) - 1) as string)))
		)
		obj #( \
			#("blocks", block bp[1] 4), \
			#("class_id", cid (classOf m)), \
			#("class_name", str ((classOf m) as string)), \
			#("index", index as string), \
			#("name", str m.name), \
			#("parts", block bp[2] 4), \
			#("subs", block subs 4), \
			#("superclass", ((classOf m).superclassID as integer) as string) \
		) 4
	),

	fn graphJson mats =
	(
		local graph = #()
		for m in mats do graphVisit m graph
		local ptrs = for m in graph collect ptrOf (animOf m)
		local items = #()
		for i = 1 to graph.count do append items (graphEntryJson graph[i] (i - 1) graph ptrs)
		block items 2
	),

	fn layersJson =
	(
		local items = #()
		for i = 0 to LayerManager.count - 1 do
		(
			local l = LayerManager.getLayer i
			local p = l.getParent()
			append items (inline #(#("cast_shadows", bool l.castShadows), #("frozen", bool l.isFrozen), #("hidden", bool l.isHidden), #("name", str l.name), #("parent", if p == undefined then "null" else str p.name), #("receive_shadows", bool l.receiveShadows), #("renderable", bool l.renderable)))
		)
		block items 2
	),

	fn fileVersion =
	(
		local f = maxFilePath + maxFileName
		if maxFileName == "" do return "null"
		local v = try (getMaxFileVersionData f) catch undefined
		if v == undefined then "null" else list (for x in v collect (x as integer) as string)
	),

	fn sceneJson =
	(
		local nodes = sceneNodes()
		local mats = #()
		for n in nodes where n.material != undefined and (findItem mats n.material) == 0 do append mats n.material
		local nodeItems = #()
		-- a file opens at the frame it was saved at; frame 0 is what a reader evaluates by default
		at time 0f for i = 1 to nodes.count do
		(
			append nodeItems (nodeJson nodes[i] (i - 1) mats)
			if (mod i 100) == 0 do gc light:true
		)
		local matItems = for i = 1 to mats.count collect materialJson mats[i] (i - 1)
		local mv = maxVersion()
		local year = if mv.count >= 8 then mv[8] else undefined
		local r = renderers.current
		local rend = if r == undefined then "null" else inline #(#("class_id", cid (classOf r)), #("class_name", str ((classOf r) as string)))
		local units_ = inline #( \
			#("display_metric", str (units.MetricType as string)), \
			#("display_type", str (units.DisplayType as string)), \
			#("display_us", str (units.USType as string)), \
			#("system_scale", num units.SystemScale), \
			#("system_type", str (units.SystemType as string)) \
		)
		(obj #( \
			#("file", if maxFileName == "" then "null" else str maxFileName), \
			#("file_version", fileVersion()), \
			#("layers", layersJson()), \
			#("material_graph", graphJson mats), \
			#("materials", block matItems 2), \
			#("max_version", list #(intOrNull mv[1], intOrNull year)), \
			#("node_count", nodes.count as string), \
			#("nodes", block nodeItems 2), \
			#("oracle_version", version as string), \
			#("render", renderJson()), \
			#("renderer", rend), \
			#("time", "0"), \
			#("units", units_) \
		) 0) + "\n"
	),

	fn writeText path text =
	(
		makeDir (getFilenamePath path) all:true
		local enc = dotNetObject "System.Text.UTF8Encoding" false
		(dotNetClass "System.IO.File").WriteAllText path text enc
		path
	),

	fn dumpScene outPath =
	(
		local t0 = timeStamp()
		local text = sceneJson()
		writeText outPath text
		"MaxDrop oracle: " + (sceneNodes()).count as string + " nodes, " + (((timeStamp() - t0) / 1000.0) as string) + " s -> " + (filenameFromPath outPath)
	),

	fn loadQuiet maxPath =
	(
		local ok = try (loadMaxFile maxPath useFileUnits:true quiet:true missingExtFilesAction:#logmsg missingDLLsAction:#logmsg missingXRefsAction:#logmsg) catch undefined
		if ok == undefined do ok = loadMaxFile maxPath useFileUnits:true quiet:true
		ok
	),

	fn dumpFile maxPath outPath =
	(
		-- loading with the file's units changes these session preferences, not only the scene
		local before = #(units.SystemType, units.SystemScale, units.DisplayType, units.MetricType, units.USType, units.USFrac)
		local result
		if doesFileExist outPath do deleteFile outPath
		try
		(
			resetMaxFile #noPrompt
			local t0 = timeStamp()
			if not (loadQuiet maxPath) do throw ("MaxDrop oracle: cannot load " + (filenameFromPath maxPath))
			local tLoad = (timeStamp() - t0) / 1000.0
			result = (dumpScene outPath) + " (load " + (tLoad as string) + " s)"
		)
		catch
		(
			result = "MaxDrop oracle: failed: " + getCurrentException()
		)
		resetMaxFile #noPrompt
		units.SystemType = before[1]
		units.SystemScale = before[2]
		units.DisplayType = before[3]
		units.MetricType = before[4]
		units.USType = before[5]
		units.USFrac = before[6]
		result
	),

	fn dumpFolder dir outDir =
	(
		local files = getFiles (dir + "\\*.max")
		sort files
		local lines = for f in files collect dumpFile f (outDir + "\\" + (getFilenameFile f) + ".oracle.json")
		local failed = 0
		local ss = stringStream ""
		for l in lines do
		(
			if (findString l ": failed: ") != undefined do failed += 1
			format "%\n" l to:ss
		)
		format "MaxDrop oracle: % file(s), % failed\n" lines.count failed to:ss
		ss as string
	)
)

MaxDropOracle = MaxDropOracleStruct()
