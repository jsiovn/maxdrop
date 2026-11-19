# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The one exception family of a file MaxDrop cannot read.

    MaxFileError
        cfb.CfbError                the compound file container
        chunks.ChunkError           the chunk tree, and what is read from it: geometry.GeometryError,
                                    shapes.ShapeError, the convert/ rules' errors (lights, cameras, primitives...)
        metadata.MetadataError      the summary streams
        intake.archive.PackError    a scene pack (.zip, .rar, .7z)

Its message is written for the user: the operator reports it as the reason a file was not imported. It is a
ValueError, so code that caught the layers' errors as ValueError before keeps working. Anything else coming out
of the reader is a defect (tests/unit/fuzz.py fails on it). No imports: every bpy-free package may use it.
"""


class MaxFileError(ValueError):
    pass
