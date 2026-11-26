# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The performance budget of one big mesh inside Blender: a synthetic Editable Poly object of a million faces
(tests/synthetic_poly.py) read (reader.geometry), described (convert.scene.mesh_description) and built
(build.objects.make_mesh).

Run alone, headless with an isolated profile so your own preferences are never touched:
  $env:BLENDER_USER_RESOURCES="<scratch>\\profile"
  & blender --background --factory-startup --python-exit-code 1 --python tests\\blender\\bench.py
It prints `BENCH PASSED` (exit 0) or `BENCH FAILED` (exit 1). tests/blender/run.py (suite.py) calls run(check) too,
so CI's fixture step runs it.

As in tests/unit/test_perf.py, no limit is a number of seconds: each time is the best of a few runs divided by the
best time of a reference in the same process, and the limit is about twice the ratio measured on Blender 4.2, 4.5
and 5.2, so that code three times as slow fails. The build's reference makes a mesh of the same arrays with nothing
but Blender's own calls (vertices.add, loops.add, polygons.add, foreach_set of the positions, the loop vertices and
the loop starts, update with calc_edges): what make_mesh adds on top (material indices, flat faces, sharp edges, the
UV layer) is what the ratio watches. The read and describe ratios repeat the plain test's at the size of a big
scene's biggest mesh. The built mesh is also checked: its counts and exactly the sharp edges of the description
(none when the description has none).
"""
import importlib.util
import os
import sys
import traceback

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FACES = 1_000_000
RUNS = 3
# measured on CI 2026-11-20 (1 001 200 faces, two attempts of a run, Linux) on Blender 4.2.23, 4.5.16 and 5.2.4: read
# 2.27 to 2.54, describe 1.92 to 2.35, build 1.96 to 2.29; on Windows locally on 4.2.23, 4.5.16 and 5.2.0 (alone and
# from run.py): read 2.1 to 2.7, build 2.1 to 2.7 (2026-11-19), describe 1.80 to 2.24 (2026-11-20)
READ_LIMIT = 6.0
DESCRIBE_LIMIT = 5.2
BUILD_LIMIT = 5.5


def _synthetic():
    spec = importlib.util.spec_from_file_location("synthetic_poly", os.path.join(ROOT, "tests", "synthetic_poly.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bare_mesh(md):
    """The reference: a mesh of md's arrays with Blender's own calls only."""
    import numpy
    mesh = bpy.data.meshes.new("MaxDrop bench reference")
    mesh.vertices.add(len(md.positions))
    mesh.loops.add(len(md.loop_vertices))
    mesh.polygons.add(len(md.loop_starts))
    mesh.vertices.foreach_set("co", numpy.ascontiguousarray(md.positions, dtype=numpy.float32).ravel())
    mesh.loops.foreach_set("vertex_index", numpy.ascontiguousarray(md.loop_vertices, dtype=numpy.int32))
    mesh.polygons.foreach_set("loop_start", numpy.ascontiguousarray(md.loop_starts, dtype=numpy.int32))
    mesh.update(calc_edges=True)
    return mesh


def _remove(made):
    bpy.data.meshes.remove(made[0] if isinstance(made, tuple) else made)


def _ratio(check, what, work, reference, limit):
    ratio = work / reference
    print("%s: %.3f s / reference %.3f s = %.2f (limit %.1f)" % (what, work, reference, ratio, limit))
    check("%s within its budget: %.2f times its reference, limit %.1f" % (what, ratio, limit), ratio < limit)


def _sharp_count(mesh):
    import numpy
    flags = numpy.zeros(len(mesh.edges), dtype=bool)
    attr = mesh.attributes.get("sharp_edge")
    if attr is not None:
        attr.data.foreach_get("value", flags)
    return int(flags.sum())


def run(check):
    """The benchmark; check(name, condition) records each result."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from maxdrop.build import objects as build_objects
    from maxdrop.convert import scene as convert_scene
    from maxdrop.reader import chunks, geometry
    sp = _synthetic()
    data = sp.poly_object(FACES)

    def read():
        return geometry.read_editable_poly(chunks.index(data)[0])

    def describe(md):
        return convert_scene.mesh_description(0, "MaxDrop bench", md, None, 1.0)

    md = read()
    faces = len(md.loop_starts)
    _ratio(check, "read %d faces" % faces, *sp.timed(read, lambda: sp.reference_loop(faces), RUNS), READ_LIMIT)
    desc = describe(md)
    _ratio(check, "describe %d faces" % faces, *sp.timed(lambda: describe(md), sp.describe_reference(md.loop_vertices),
                                                          RUNS), DESCRIBE_LIMIT)
    md = None  # the reader's arrays are not needed for the build
    _ratio(check, "build %d faces" % len(desc.loop_starts),
           *sp.timed(lambda: build_objects.make_mesh(desc), lambda: _bare_mesh(desc), RUNS, after=_remove), BUILD_LIMIT)
    mesh, dropped = build_objects.make_mesh(desc)
    try:
        check("bench mesh: %d vertices, %d faces" % (len(desc.positions), len(desc.loop_starts)),
              len(mesh.vertices) == len(desc.positions) and len(mesh.polygons) == len(desc.loop_starts)
              and dropped == 0 and len(mesh.uv_layers) == 1)
        sharp = _sharp_count(mesh)
        check("bench mesh: the %d sharp edges of the description" % len(desc.sharp_edges),
              len(desc.sharp_edges) > 0 and sharp == len(desc.sharp_edges), sharp)
    finally:
        bpy.data.meshes.remove(mesh)
    desc.sharp_edges = desc.sharp_edges[:0]
    mesh, _dropped = build_objects.make_mesh(desc)
    try:
        check("bench mesh without sharp edges has none", _sharp_count(mesh) == 0)
    finally:
        bpy.data.meshes.remove(mesh)


def main():
    failures = []

    def check(name, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + name + ("  [%s]" % (detail,) if detail != "" else ""))
        if not cond:
            failures.append(name)

    print("Blender " + bpy.app.version_string)
    try:
        run(check)
    except Exception:
        traceback.print_exc()
        failures.append("exception")
    print("BENCH FAILED: %s" % ", ".join(failures) if failures else "BENCH PASSED")
    sys.stdout.flush()
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
