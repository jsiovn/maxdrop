# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The material IR: MapRef, Input, Medium, MaterialIR, Layer and the stats."""
import collections
import dataclasses


@dataclasses.dataclass(frozen=True)
class MapRef:
    """A map object driving an input: its object index, the slot's amount (1 = full), whether the map holds the
    inverse of the input (a glossiness map feeding roughness) and a factor on the map before the amount mixes it
    with the input's value (Standard's Diffuse Level on a diffuse map, a Fresnel-off VRayMtl's 1 - metalness;
    linear; 1: none)."""
    index: int
    amount: float = 1.0
    invert: bool = False
    scale: float = 1.0


@dataclasses.dataclass(frozen=True)
class DiffuseLevel:
    """Standard's Diffuse Level map: 3ds Max renders the diffuse at level 1 (color: the swatch, linear, with the
    diffuse map mixed over it by its amount) times lerp(level, the mean of the map, its amount) (maxdrop-em3.150).
    level: the Diffuse Level as the swatch rule makes it, not clamped; map: the MapRef of the Diffuse Level map."""
    color: tuple
    level: float
    map: MapRef


@dataclasses.dataclass(frozen=True)
class Input:
    """A value (linear RGB tuple or float) and the map that drives it, None without one."""
    value: object
    map: object = None


@dataclasses.dataclass(frozen=True)
class Medium:
    """A homogeneous medium inside a closed mesh, per channel and per meter, linear: scattering (sigma_s) and
    absorption (sigma_a) coefficients, the Henyey-Greenstein anisotropy of the scattering, the radiance emitted per
    meter of path; single: Corona's single bounce on (named; Cycles' default Volume Bounces of 0 renders it so)."""
    scattering: tuple = (0.0, 0.0, 0.0)
    absorption: tuple = (0.0, 0.0, 0.0)
    anisotropy: float = 0.0
    emission: tuple = (0.0, 0.0, 0.0)
    single: bool = False


@dataclasses.dataclass
class MaterialIR:
    """One material, renderer-neutral, linear color. index: the Max material object it was converted from; source:
    that material's class name; unknown: a grey material (a class without a rule, or one whose rule names what it
    leaves out: CORONA_GREY)."""
    index: object
    name: str
    source: str = ""
    base_color: Input = Input((0.8, 0.8, 0.8))
    metallic: Input = Input(0.0)
    roughness: Input = Input(0.5)
    specular: Input = Input(1.0)  # a reflection weight: 1 is the IOR's own Fresnel (Blender's 0.5)
    fresnel: bool = True  # False: the weight is reflected at every angle, no Fresnel curve (VRayMtl Fresnel off)
    mirror_color: tuple = (1.0, 1.0, 1.0)  # with fresnel False: the color of that reflection (VRayMtl: R / max(R))
    ior: float = 1.5
    transmission: Input = Input(0.0)
    thin_walled: bool = False
    emission_color: Input = Input((0.0, 0.0, 0.0))
    emission_strength: float = 0.0
    alpha: Input = Input(1.0)
    normal: object = None  # MapRef of a normal map
    bump: object = None  # MapRef of a height map
    diffuse_level: object = None  # DiffuseLevel of a Standard material with a Diffuse Level map
    subsurface_weight: float = 0.0
    subsurface_color: tuple = (1.0, 1.0, 1.0)
    subsurface_radius: float = 0.0  # meters
    coat_weight: float = 0.0
    coat_color: tuple = (1.0, 1.0, 1.0)
    coat_roughness: float = 0.0
    coat_ior: float = 1.5
    sheen_weight: float = 0.0
    sheen_color: tuple = (1.0, 1.0, 1.0)
    sheen_roughness: float = 0.5
    two_sided: bool = False  # Standard's twoSided: 3ds Max renders the back faces too
    shadow_catcher: bool = False  # CoronaShadowCatcherMtl: an object with nothing else is a shadow catcher
    medium: object = None  # Medium inside the mesh (Corona volumes), None without one
    unknown: bool = False
    textures: dict = dataclasses.field(default_factory=dict)  # {input name: texmaps.TextureGraphIR}
    issues: list = dataclasses.field(default_factory=list)
    layers: list = dataclasses.field(default_factory=list)  # [Layer] mixed over this one, bottom first


MIX, ADD = "mix", "add"  # Layer.mode


@dataclasses.dataclass
class Layer:
    """A material over the ones below it (CoronaLayeredMtl, a VRayBlendMtl's coat): its MaterialIR, its amount, its
    mask (a MapRef, or None) and the mask's TextureGraphIR (MASK) when a TexmapConverter made one. Its weight is amount
    x the mask graph: a CoronaLayeredMtl's graph is lerp(1, mask, mask amount) (Corona 12 renders), a VRayBlendMtl's
    lerp(blend, blend map, multiplier). mode: MIX mixes it over what is below by the weight; ADD adds it, scaled by
    the weight, over what is below (VRayBlendMtl's additive mode)."""
    ir: MaterialIR
    amount: float = 1.0
    mask: object = None
    graph: object = None
    mode: str = MIX


class ConvertStats:
    """What the report needs: peeled {class name: wrapper objects peeled}, unknown {class name: materials made
    grey}, issues [(object index, reason)]."""
    __slots__ = ("peeled", "unknown", "issues")

    def __init__(self):
        self.peeled, self.unknown, self.issues = collections.Counter(), collections.Counter(), []
