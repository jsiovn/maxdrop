# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""main(): every fixture, then the checks that are not one fixture's, each guarded."""
import glob
import importlib.util
import os
import sys
import traceback

import bpy

from .core import argv, check, ROOT
from .checks_objects import check_ignore_option
from .checks_lights import check_dome_undo, check_ies_cleanup, check_ies_light, check_light_nodes, check_spread_cancel
from .checks_maps import check_builder_volume, check_curve_step
from .checks_operator import check_mesh_steps, check_read_cancel, check_worker_errors
from .checks_builder import (
    check_builder, check_builder_blend, check_builder_blend_modes, check_builder_gamma_magnitude, check_builder_weight,
    check_found_textures,
)
from .checks_builder_inputs import (
    check_builder_fresnel_off, check_builder_mask_mean, check_builder_mono, check_builder_negative_constants,
    check_builder_saturation, check_world_shown_render, check_world_shown_sky,
)
from .checks_builder_more import (
    check_builder_debt, check_builder_diffuse_level, check_builder_multiply, check_builder_wrapper_constants,
    check_double_import, check_image_reuse, check_linear_fallback,
)
from .checks_placement import check_builder_clip_mask, check_builder_clipped_normal, check_builder_mirror
from .checks_failures import (
    check_asset_table_once, check_conversion_failure, check_ies_header, check_ies_search_stopped,
    check_light_note_on_failure, check_reader_defect, check_renderer_reaches_converters,
)
from .checks_layers import check_crease_open_edges, check_material_slots, check_shear
from .fixture import run_fixture


def _bench():
    """tests/blender/bench.py, the performance budget of one big mesh (its own docstring says what it checks)."""
    spec = importlib.util.spec_from_file_location("maxdrop_bench", os.path.join(ROOT, "tests", "blender", "bench.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    print("Blender " + bpy.app.version_string)
    sys.path.insert(0, ROOT)
    import maxdrop
    maxdrop.register()
    check("package imported from the repo root",
          os.path.normcase(os.path.dirname(os.path.dirname(maxdrop.__file__))) == os.path.normcase(ROOT))
    from maxdrop.build import collections as build_collections
    from maxdrop.build import objects as build_objects
    from maxdrop.build import report as build_report
    from maxdrop.convert import report as convert_report
    from maxdrop.convert import scene as convert_scene
    modules = (convert_scene, convert_report, build_objects, build_collections, build_report)
    paths = argv or sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
    check("fixtures found", bool(paths))
    for path in paths:
        try:
            run_fixture(path, modules)
        except Exception:
            traceback.print_exc()
            check("%s: no exception" % os.path.basename(path), False)
    if not argv:
        try:
            check_shear(modules)
        except Exception:
            traceback.print_exc()
            check("shear: no exception", False)
        try:
            check_ignore_option(os.path.join(ROOT, "tests", "fixtures", "stack_convert.max"), modules)
        except Exception:
            traceback.print_exc()
            check("modifiers ignored: no exception", False)
        for label, run_check in (("material slots", lambda: check_material_slots(modules)),
                                 ("found textures", check_found_textures), ("builder", check_builder),
                                 ("builder debt", check_builder_debt), ("builder mirror", check_builder_mirror),
                                 ("builder blend", check_builder_blend), ("builder mono", check_builder_mono),
                                 ("builder blend modes", check_builder_blend_modes),
                                 ("builder gamma magnitude", check_builder_gamma_magnitude),
                                 ("builder multiply", check_builder_multiply),
                                 ("builder negative constants", check_builder_negative_constants),
                                 ("builder diffuse level", check_builder_diffuse_level),
                                 ("builder wrapper constants", check_builder_wrapper_constants),
                                 ("builder volume", check_builder_volume),
                                 ("builder weight", check_builder_weight),
                                 ("builder fresnel off", check_builder_fresnel_off),
                                 ("builder clip mask", check_builder_clip_mask),
                                 ("builder clipped normal", check_builder_clipped_normal),
                                 ("builder mask mean", check_builder_mask_mean),
                                 ("builder saturation", check_builder_saturation),
                                 ("world shown sky", check_world_shown_sky),
                                 ("world shown render", check_world_shown_render),
                                 ("curve step", check_curve_step),
                                 ("crease open edges", check_crease_open_edges),
                                 ("linear fallback", check_linear_fallback),
                                 ("image reuse", check_image_reuse), ("double import", check_double_import),
                                 ("worker errors", check_worker_errors),
                                 ("read cancel", lambda: check_read_cancel(
                                     os.path.join(ROOT, "tests", "fixtures", "primitives.max"))),
                                 ("mesh steps", lambda: check_mesh_steps(
                                     [os.path.join(ROOT, "tests", "fixtures", n) for n in ("multi_uv.max",
                                                                                          "primitives.max")],
                                     os.path.join(ROOT, "tests", "fixtures", "primitives.max"))),
                                 ("conversion failure", lambda: check_conversion_failure(
                                     os.path.join(ROOT, "tests", "fixtures", "vray_maps.max"))),
                                 ("light note on failure", lambda: check_light_note_on_failure(
                                     os.path.join(ROOT, "tests", "fixtures", "vray_lights.max"))),
                                 ("dome undo", lambda: check_dome_undo(
                                     os.path.join(ROOT, "tests", "fixtures", "vray_dome.max"))),
                                 ("reader defect", lambda: check_reader_defect(
                                     os.path.join(ROOT, "tests", "fixtures", "primitives.max"),
                                     os.path.join(ROOT, "tests", "fixtures", "multi_uv.max"))),
                                 ("asset table once", lambda: check_asset_table_once(
                                     os.path.join(ROOT, "tests", "fixtures", "vray_lights.max"))),
                                 ("renderer reaches converters", lambda: check_renderer_reaches_converters(
                                     os.path.join(ROOT, "tests", "fixtures", "vray_dome.max"))),
                                 ("ies header", lambda: check_ies_header(
                                     os.path.join(ROOT, "tests", "fixtures", "lights_photometric.max"))),
                                 ("ies search stopped", lambda: check_ies_search_stopped(
                                     os.path.join(ROOT, "tests", "fixtures", "lights_photometric.max"))),
                                 ("light nodes", check_light_nodes),
                                 ("ies light", check_ies_light),
                                 ("ies cleanup", lambda: check_ies_cleanup(
                                     os.path.join(ROOT, "tests", "fixtures", "lights_photometric.max"))),
                                 ("spread cancel", lambda: check_spread_cancel(
                                     os.path.join(ROOT, "tests", "fixtures", "vray_mesh_light.max"))),
                                 ("benchmark", lambda: _bench().run(check))):
            try:
                run_check()
            except Exception:
                traceback.print_exc()
                check("%s: no exception" % label, False)
