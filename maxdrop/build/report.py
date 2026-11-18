# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The import report in Blender: printed to the console line by line with the prefix "MaxDrop: ", and kept whole in
the text datablock "MaxDrop Report" (the Text Editor shows it). Each import replaces the text with its own report;
a run of several files then replaces it once more with every report of the run, in import order, and a line per
file that was not imported.

    level, line = publish(rep)          # rep: a convert.report.Report
    operator.report({level}, line)
    publish_run(reports, failed)        # after a run of several files, or of one with files not imported
"""
import bpy

from ..convert import report as convert_report

TEXT_NAME = "MaxDrop Report"
PREFIX = "MaxDrop: "


def publish(rep):
    """Print rep, write it into the text datablock; (level, line) for Operator.report."""
    text = rep.text()
    for line in text.split("\n"):
        print(PREFIX + line)
    _write(text)
    return rep.summary()


def publish_run(reports, failed):
    """Write the reports of one run (each printed already by publish) and the lines of the files not imported
    ("<file>: <reason>") into the text datablock."""
    _write(convert_report.run_text(reports, failed))


def _write(text):
    block = bpy.data.texts.get(TEXT_NAME)
    if block is None:
        block = bpy.data.texts.new(TEXT_NAME)
    block.clear()
    block.write(text + "\n")
