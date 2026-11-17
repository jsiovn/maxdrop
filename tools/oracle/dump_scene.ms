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
	version = 3,

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
		obj #( \
			#("base_class_id", cid (classOf b)), \
			#("base_class_name", str ((classOf b) as string)), \
			#("base_faces", intOrNull bc[2]), \
			#("base_superclass", ((classOf b).superclassID as integer) as string), \
			#("base_verts", intOrNull bc[1]), \
			#("bbox_max", bmax), \
			#("bbox_min", bmin), \
			#("eval_faces", intOrNull ev[2]), \
			#("eval_verts", intOrNull ev[1]), \
			#("frozen", bool n.isFrozen), \
			#("handle", n.handle as string), \
			#("hidden", bool n.isHidden), \
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
			#("renderable", bool n.renderable), \
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

	fn pb2Json pb r acc =
	(
		local items = #()
		for i = 0 to pb.NumParams - 1 do
		(
			local id = pb.IndextoID i
			local d = pb.GetParamDef id
			local tp = d.Type.value__
			local v = if (bit.and tp 0x800) != 0 then tabValue pb id tp acc else pbValue pb id tp 0 acc
			append items (inline #(#("id", (id as integer) as string), #("name", str d.IntName), #("transient", bool ((bit.and (d.Flags as integer) 2) != 0)), #("type", tp as string), #("value", v)))
		)
		obj #(#("block_id", (pb.Id as integer) as string), #("kind", str "pb2"), #("params", block items 8), #("ref", r as string)) 6
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
		obj #(#("block_id", "null"), #("kind", str "pb1"), #("params", block items 8), #("ref", r as string)) 6
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
		local c = t.ClassID
		local pcid = list #(str ("0x" + (formattedPrint c.PartA format:"08x")), str ("0x" + (formattedPrint c.PartB format:"08x")))
		obj #(#("blocks", block (ownBlocks t acc) 6), #("class_id", pcid), #("ref", r as string)) 6
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
			append items (inline #(#("frozen", bool l.isFrozen), #("hidden", bool l.isHidden), #("name", str l.name), #("renderable", bool l.renderable)))
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
