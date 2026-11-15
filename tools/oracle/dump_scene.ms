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
	version = 1,

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

	-- "key": value lines of one object, in the order given (callers pass keys sorted), at the given indent
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
		local mods = for m in n.modifiers collect inline #(#("class_id", cid (classOf m)), #("class_name", str ((classOf m) as string)))
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
		for i = 1 to nodes.count do
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
			#("materials", block matItems 2), \
			#("max_version", list #(intOrNull mv[1], intOrNull year)), \
			#("node_count", nodes.count as string), \
			#("nodes", block nodeItems 2), \
			#("oracle_version", version as string), \
			#("renderer", rend), \
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
		local sysType = units.SystemType
		local sysScale = units.SystemScale
		local result
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
		units.SystemType = sysType
		units.SystemScale = sysScale
		result
	),

	fn dumpFolder dir outDir =
	(
		local files = getFiles (dir + "\\*.max")
		sort files
		local lines = for f in files collect dumpFile f (outDir + "\\" + (getFilenameFile f) + ".oracle.json")
		local ss = stringStream ""
		for l in lines do format "%\n" l to:ss
		ss as string
	)
)

MaxDropOracle = MaxDropOracleStruct()
