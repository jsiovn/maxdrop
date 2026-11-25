# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The standard primitives as the meshes 3ds Max builds from their parameters: Box, Plane, Pyramid, Sphere,
GeoSphere, Cylinder, Cone, Tube and Torus (Teapot is not built: it stays a placeholder).

    is_primitive(scene, i)              # object i is one of the nine classes
    data, issues = mesh(scene, i)       # reader.geometry.MeshData in object space, file units; PrimitiveError
    params, issues = read_params(scene, i)   # Params: the class and its parameters by name

Each keeps one ParamBlock2 in reference slot 0, its parameters by id (docs/FORMAT.md, "Primitives"). The mesh is the
one the object's own TriMesh holds (`o.mesh`), checked vertex for vertex against 3ds Max 2020: the same vertices
(their order aside), the same triangles merged into the polygons 3ds Max shows (two triangles that share a hidden
edge are one quad; a cap's fan stays triangles around its center vertex, so the vertex and triangle counts are 3ds
Max's), smoothing groups and material IDs as 3ds Max assigns them (a Box's sides have IDs 1 to 6), and, when
Generate Mapping Coords is on, the map channel 1 3ds Max makes, real-world map size included (the UVs are then in
file units). The pivot is 3ds Max's: a Box, Plane, Pyramid, Cylinder, Cone and Tube stand on it, a Sphere, GeoSphere
and Torus are centered on it (Base To Pivot raises a Sphere or GeoSphere by its radius; a hemisphere stands on it).
Slice on a Sphere, Cylinder, Cone, Tube or Torus and the hemisphere of a Sphere (chopped or squashed) or a GeoSphere
are built as 3ds Max builds them, their cut planes and bases with their own IDs, groups and UVs. Plane's render
scale and density act only at render time: built at their viewport size (an issue when they are not 1).

The file comes from anywhere: a missing block, an animated parameter or one that is no number or not finite raise
PrimitiveError; segments below 3ds Max's own minimum are raised to it, a mesh past MAX_CORNERS face corners is
refused, and so is one whose points or UVs are not finite (sizes near the float range). A size of 0 builds the flat
or collapsed mesh 3ds Max builds (UVs that would divide by it take 0 there). No bpy; numpy is imported when a mesh is
made (or a chopped hemisphere's rings are counted), and every generator works on whole arrays of points and faces, in
the order 3ds Max makes them.
"""

import collections
import math
import struct

from ...reader import chunks, classids, geometry, pblock, realworld

from .specs import (
    ChunkError, SLOT_BLOCK, MAX_CORNERS, _TAU, _SEAM, PrimitiveError, _SPECS, Params, is_primitive, _value, params_of,
    read_params,
)
from .builder import _Builder, _stack, _corners, _first_use, _grid, _sign
from .flat import _box, _plane, _div, _pyramid
from .revolved import _pie, _sphere_rings, _sphere, _seam, _cylinder, _cylinder_pie, _tube, _alternate, _torus
from .geosphere import _f32, _solid, _slerp, _geo_uv, _geo_base, _geosphere
from .dispatch import _faces, build, _make, mesh
