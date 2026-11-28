# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""RULES: the rule of each material class."""
from ...reader import classids
from .vray import vray_car_paint_mtl, vray_car_paint_mtl2, vray_fast_sss2, vray_light_mtl, vray_mtl
from .standard import physical_mtl, standard_mtl
from .corona import (
    corona_hair_mtl, corona_legacy_mtl, corona_light_mtl, corona_named_grey, corona_physical_mtl,
    corona_shadow_catcher_mtl, corona_skin_mtl, corona_volume_mtl,
)
from .layered import corona_layered_mtl, vray_2sided_mtl, vray_blend_mtl


# (superclass, ClassId) -> rule(converter, MtlBase, MaterialIR): fills the IR in place, or returns the IR it made
RULES = {
    (classids.SC_MATERIAL, classids.STANDARD_MTL): standard_mtl,
    (classids.SC_MATERIAL, classids.PHYSICAL_MTL): physical_mtl,
    (classids.SC_MATERIAL, classids.VRAY_MTL): vray_mtl,
    (classids.SC_MATERIAL, classids.VRAY_LIGHT_MTL): vray_light_mtl,
    (classids.SC_MATERIAL, classids.VRAY_FAST_SSS2): vray_fast_sss2,
    (classids.SC_MATERIAL, classids.VRAY_CAR_PAINT_MTL): vray_car_paint_mtl,
    (classids.SC_MATERIAL, classids.VRAY_CAR_PAINT_MTL2): vray_car_paint_mtl2,
    (classids.SC_MATERIAL, classids.CORONA_PHYSICAL_MTL): corona_physical_mtl,
    (classids.SC_MATERIAL, classids.CORONA_LEGACY_MTL): corona_legacy_mtl,
    (classids.SC_MATERIAL, classids.CORONA_LIGHT_MTL): corona_light_mtl,
    (classids.SC_MATERIAL, classids.CORONA_LAYERED_MTL): corona_layered_mtl,  # a wrapper without a layer on
    (classids.SC_MATERIAL, classids.VRAY_BLEND_MTL): vray_blend_mtl,  # a wrapper without a coat set and on
    (classids.SC_MATERIAL, classids.VRAY_2SIDED_MTL): vray_2sided_mtl,  # a wrapper without translucency or a back
    (classids.SC_MATERIAL, classids.CORONA_SKIN_MTL): corona_skin_mtl,
    (classids.SC_MATERIAL, classids.CORONA_HAIR_MTL): corona_hair_mtl,
    (classids.SC_MATERIAL, classids.CORONA_SHADOW_CATCHER_MTL): corona_shadow_catcher_mtl,
    (classids.SC_MATERIAL, classids.CORONA_VOLUME_MTL): corona_volume_mtl,
    (classids.SC_MATERIAL, classids.CORONA_SCANNED_MTL): corona_named_grey,
    (classids.SC_MATERIAL, classids.CORONA_SLICER_MTL): corona_named_grey,
}
