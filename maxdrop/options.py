# SPDX-FileCopyrightText: 2023-2026 Sebastian Schrand
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Modified for MaxDrop, 2026-11-25 (jsiovn). Moved here unchanged from ops.py, whose notes above its code record
# the earlier changes.

"""The import options: the choices of the operator's enums and ImportOptions, what a run reads of them."""


# The default Light Strength: V-Ray 5.2 renders against Cycles renders of the same lights (docs/FORMAT.md,
# "VRayLight", where the measured ratios are). The standard, photometric, sun and IES powers are derived from V-Ray
# renders of the same scene so that this one factor holds for them too ("Standard and photometric lights", "Power,
# measured": 1.43 is pi 683 / 1500).
LIGHT_STRENGTH = 1.43

# Saved in presets by identifier; the numbers keep each item's value stable.
UNITS = (
    ('AUTO', "Auto", "The unit the file was saved with. A file that does not say: 1 unit = Scale meters", 0),
    ('MILLIMETERS', "Millimeters", "One unit of the file is a millimeter", 1),
    ('CENTIMETERS', "Centimeters", "One unit of the file is a centimeter", 2),
    ('METERS', "Meters", "One unit of the file is a meter", 3),
    ('INCHES', "Inches", "One unit of the file is an inch", 4),
    ('FEET', "Feet", "One unit of the file is a foot", 5),
)
# Saved in presets by identifier, like UNITS.
MODIFIERS = (
    ('KEEP', "Keep as Blender Modifiers",
     "TurboSmooth and MeshSmooth become Subdivision Surface, Shell Solidify, Symmetry Mirror", 0),
    ('IGNORE', "Ignore", "The objects arrive without these modifiers (each counted in the import report)", 1),
)
# Saved in presets by identifier, like UNITS. The codecs are reader.strings.CHOICES.
TEXT_ENCODINGS = (
    ('AUTO', "Auto", "The code page the file records, else UTF-8, else Western (1252)", 0),
    ('CP1252', "Western (1252)", "English and Western European names", 1),
    ('CP1250', "Central European (1250)", "Polish, Czech, Hungarian and other Central European names", 2),
    ('CP1251', "Cyrillic (1251)", "Russian, Ukrainian, Bulgarian and other Cyrillic names", 3),
    ('CP1253', "Greek (1253)", "Greek names", 4),
    ('CP1254', "Turkish (1254)", "Turkish names", 5),
    ('CP932', "Japanese (932)", "Japanese names (Shift JIS)", 6),
    ('CP936', "Simplified Chinese (936)", "Simplified Chinese names (GBK)", 7),
    ('CP949', "Korean (949)", "Korean names", 8),
    ('CP950', "Traditional Chinese (950)", "Traditional Chinese names (Big5)", 9),
    ('UTF_8', "UTF-8", "Names saved as UTF-8", 10),
)
TEXT_CODECS = {'CP1252': "cp1252", 'CP1250': "cp1250", 'CP1251': "cp1251", 'CP1253': "cp1253", 'CP1254': "cp1254",
               'CP932': "cp932", 'CP936': "cp936", 'CP949': "cp949", 'CP950': "cp950", 'UTF_8': "utf-8"}
UNIT_METERS = {'MILLIMETERS': 0.001, 'CENTIMETERS': 0.01, 'METERS': 1.0, 'INCHES': 0.0254, 'FEET': 0.3048}


class ImportOptions:
    """The operator's settings an import reads, copied: a modal run outlives the operator that started it."""
    __slots__ = ("units", "scale_objects", "use_image_search", "object_filter", "modifiers", "light_strength",
                 "keep_targets", "axis_forward", "axis_up", "text_encoding")
    DEFAULTS = {"text_encoding": 'AUTO'}  # an option added after scripts and tests that build ImportOptions

    def __init__(self, **values):
        for name in self.__slots__:
            setattr(self, name, values[name] if name in values else self.DEFAULTS[name])

    @classmethod
    def of(cls, op):
        values = {name: getattr(op, name) for name in cls.__slots__}
        values["object_filter"] = set(values["object_filter"])
        return cls(**values)
