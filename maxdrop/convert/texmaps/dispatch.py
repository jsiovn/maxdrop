# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The map rules by ClassID (kept, peeled) and the kind of each material slot."""
from ...reader import classids
from .ids import (
    CHECKER, COLOR, COLOR_CORRECTION, COMPOSITE, DATA, FALLOFF, MIX, NOISE, OUTPUT, RGB_MULTIPLY, RGB_TINT,
    VRAY_COLOR2BUMP, VRAY_DIRT,
)
from .maps import (
    _color2bump, _color_correction, _composite, _falloff, _mix, _output_map, _rgb_multiply, _rgb_tint, _vray_dirt,
)
from .maps_color import _corona_color, _corona_mix, _vray_color
from .maps_pattern import _checker
from .maps_xyz import _noise


_KEEP = {MIX: _mix, RGB_MULTIPLY: _rgb_multiply, COLOR_CORRECTION: _color_correction, COMPOSITE: _composite,
         classids.CORONA_COLOR: _corona_color, classids.CORONA_MIX: _corona_mix, classids.VRAY_COLOR: _vray_color,
         FALLOFF: _falloff, OUTPUT: _output_map, RGB_TINT: _rgb_tint, VRAY_COLOR2BUMP: _color2bump,
         CHECKER: _checker, NOISE: _noise}
_PEEL = {VRAY_DIRT: _vray_dirt}

# MaterialIR input -> its kind (normal and bump: MapRefs of their own)
SLOT_KINDS = (("base_color", COLOR), ("metallic", DATA), ("roughness", DATA), ("specular", COLOR),
              ("transmission", COLOR), ("emission_color", COLOR), ("alpha", DATA), ("translucency", DATA))
