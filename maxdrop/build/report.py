# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The import report in Blender: printed to the console line by line with the prefix "MaxDrop: ", and kept whole in
the text datablock "MaxDrop Report" (the Text Editor shows it; a new import replaces it).

    level, line = publish(rep)          # rep: a convert.report.Report
    operator.report({level}, line)
"""
import bpy

TEXT_NAME = "MaxDrop Report"
PREFIX = "MaxDrop: "


def publish(rep):
    """Print rep, write it into the text datablock; (level, line) for Operator.report."""
    text = rep.text()
    for line in text.split("\n"):
        print(PREFIX + line)
    block = bpy.data.texts.get(TEXT_NAME)
    if block is None:
        block = bpy.data.texts.new(TEXT_NAME)
    block.clear()
    block.write(text + "\n")
    return rep.summary()
