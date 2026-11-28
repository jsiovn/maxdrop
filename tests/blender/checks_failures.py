# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks of failures and lookups: a conversion failure, the light note, the renderer reaching the
converters, IES headers and search, reader defects, one asset table."""
import math
import os
import shutil
import sys
import tempfile

import bpy

from .checks_lights import FIXTURE_WEB
from .core import check, empty_scene
from .nodes import _advance, _cancel_run


def check_conversion_failure(max_path):
    """The material conversion raises: the operator imports the scene without materials and the report says so."""
    from maxdrop import pipeline
    empty_scene()
    original = pipeline._material_slots

    def failing(*args, **kwargs):
        raise RuntimeError("maxdrop test: conversion fails")

    pipeline._material_slots = failing
    try:
        result = bpy.ops.import_scene.maxdrop(filepath=max_path)
    finally:
        pipeline._material_slots = original
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    check("conversion failure: the scene imported without materials, the report says why",
          result == {'FINISHED'} and len(bpy.data.objects) > 0 and not bpy.data.materials
          and "materials: not converted (RuntimeError: maxdrop test: conversion fails): the scene is imported "
              "without materials" in body and "Material issues: 1" in body,
          "%s %d objects %d materials | %s" % (result, len(bpy.data.objects), len(bpy.data.materials), body[-500:]))
    empty_scene()


def check_light_note_on_failure(max_path):
    """A file with lights whose gamma setting is not found and whose material conversion raises: the swatch note of
    the light colors is still in the report (with converted materials it comes through them)."""
    from maxdrop import pipeline
    from maxdrop.convert import colors
    empty_scene()
    original_slots, original_rule = pipeline._material_slots, colors.of_scene

    def failing(*args, **kwargs):
        raise RuntimeError("maxdrop test: conversion fails")

    pipeline._material_slots, colors.of_scene = failing, lambda source: colors.UNKNOWN
    try:
        result = bpy.ops.import_scene.maxdrop(filepath=max_path)
    finally:
        pipeline._material_slots, colors.of_scene = original_slots, original_rule
    text = bpy.data.texts.get("MaxDrop Report")
    body = text.as_string() if text is not None else ""
    check("conversion failure: the light colors' swatch note is still reported",
          result == {'FINISHED'} and len(bpy.data.lights) > 0 and "color swatches: " + colors.GAMMA_NOTE in body,
          "%s %d lights | %s" % (result, len(bpy.data.lights), body[-500:]))
    empty_scene()


def check_renderer_reaches_converters(max_path):
    """One import of a file with a dome texture and materials hands the renderer ClassID of its summary stream
    (reader.metadata) to both texture-map converters it makes, the dome's and the materials' (maxdrop-em3.127: the
    Corona rules key on it)."""
    from maxdrop.convert import texmaps
    from maxdrop.reader import cfb, metadata
    with cfb.CompoundFile(max_path) as cf:
        expected = (metadata.read(cf).get("renderer") or {}).get("class_id")
    empty_scene()
    original, seen = texmaps.TexmapConverter, []

    class Recording(original):
        def __init__(self, *args, **kwargs):
            seen.append(kwargs.get("renderer"))
            super().__init__(*args, **kwargs)

    texmaps.TexmapConverter = Recording
    try:
        result = bpy.ops.import_scene.maxdrop(filepath=max_path)
    finally:
        texmaps.TexmapConverter = original
    check("renderer: the summary stream's renderer reaches the dome's and the materials' converters",
          result == {'FINISHED'} and expected is not None and len(seen) == 2
          and all(r is not None and tuple(r) == tuple(expected) for r in seen),
          "%s, expected %s, seen %s" % (result, expected, seen))
    empty_scene()


def check_ies_header(max_path):
    """max_path (lights_photometric) copied beside a self-authored fixture_web.ies, rated 500 lm, 100 cd in every
    direction, one plane: the import finds it, and IesPower, IesOverride and PhWeb shine with it, point lights sharing
    one Text "fixture_web.ies" (the profile's text): IesPower (1500, override off) as 1500 x 400 pi / 500 lm (s = 3),
    IesOverride (override on) as 300 lm (s = 300 / 400 pi), PhWeb (400 cd) as the file's peak at 400 cd (s = 4): each
    light's energy the flux it sheds x Light Strength (EEVEE's plain light), times its IES node's Strength input s x
    IES_WATTS x Light Strength over 4.x's one-plane gain 35/32; the report has no rated-lumens line for it."""
    from maxdrop import options
    from maxdrop.convert import lights
    empty_scene()
    scratch = tempfile.mkdtemp(prefix="maxdrop-ies-")
    try:
        dst = os.path.join(scratch, os.path.basename(max_path))
        shutil.copy(max_path, dst)
        with open(os.path.join(scratch, "fixture_web.ies"), "wb") as f:
            f.write(FIXTURE_WEB)
        result = bpy.ops.import_scene.maxdrop(filepath=dst)
        names = ("IesPower", "IesOverride", "PhWeb")
        lights_of = {n: bpy.data.objects[n].data for n in names if n in bpy.data.objects}
        energy = {n: light.energy for n, light in lights_of.items()}
        texts = [n.ies for light in lights_of.values() for n in (light.node_tree.nodes if light.node_tree else ())
                 if n.bl_idname == "ShaderNodeTexIES"]
        strength = {n: [k.inputs["Strength"].default_value for k in light.node_tree.nodes
                        if k.bl_idname == "ShaderNodeTexIES"][0] for n, light in lights_of.items() if light.node_tree}
        gain = 1.0 if bpy.app.version >= (5, 0, 0) else 35.0 / 32.0
        flux = 400.0 * math.pi  # the file's
        sheds = {"IesPower": 3.0 * flux, "IesOverride": 300.0, "PhWeb": 4.0 * flux}  # lm
        want = {n: lm / 683.0 * options.LIGHT_STRENGTH for n, lm in sheds.items()}
        check("ies header: IesPower, IesOverride and PhWeb point lights of the flux they shed x Light Strength",
              result == {'FINISHED'} and set(energy) == set(want) and
              all(light.type == 'POINT' for light in lights_of.values())
              and all(abs(energy[n] - w) <= w * 1e-5 for n, w in want.items()), "%s %s vs %s" % (result, energy, want))
        cycles = {n: s * lights.IES_WATTS * options.LIGHT_STRENGTH / gain for n, s in
                  (("IesPower", 3.0), ("IesOverride", 300.0 / flux), ("PhWeb", 4.0))}
        got = {n: energy[n] * strength[n] for n in strength if n in energy}
        check("ies header: energy x the IES node's Strength = the file's candelas x s x IES_WATTS over 4.x's gain",
              set(got) == set(cycles) and all(abs(got[n] - w) <= w * 1e-5 for n, w in cycles.items()),
              "%s vs %s" % (got, cycles))
        check("ies header: the three share one Text fixture_web.ies, the file's text",
              len(texts) == 3 and len(set(texts)) == 1 and texts[0].name == "fixture_web.ies" and
              texts[0].as_string() == FIXTURE_WEB.rstrip(b"\n").decode("ascii"), str(texts))
        text = bpy.data.texts.get("MaxDrop Report")
        body = text.as_string() if text is not None else ""
        check("ies header: no rated-lumens line in the report", text is not None and lights.IES_RATED not in body,
              body[-600:])
    finally:
        empty_scene()
        shutil.rmtree(scratch, ignore_errors=True)


def check_ies_search_stopped(max_path):
    """max_path (lights_photometric) copied beside fixture_web.ies and filler files that come first, the texture walk
    cut to 2 entries per rule: the IES file is not found, so IesPower (1500, override off) takes its power as its
    flux and its line says the search stopped; the report's stop line is there once, with materials and without
    (only the IES lookup walks then)."""
    from maxdrop import options
    from maxdrop.convert import lights, textures
    original = textures.TextureIndex

    class Small(original):
        def __init__(self, *args, **kwargs):
            kwargs["max_entries"] = 2
            super().__init__(*args, **kwargs)

    empty_scene()
    scratch = tempfile.mkdtemp(prefix="maxdrop-ies-stop-")
    try:
        dst = os.path.join(scratch, os.path.basename(max_path))
        shutil.copy(max_path, dst)
        for n in range(3):
            with open(os.path.join(scratch, "a%d.txt" % n), "wb") as f:
                f.write(b"x")
        with open(os.path.join(scratch, "fixture_web.ies"), "wb") as f:
            f.write(FIXTURE_WEB)
        stop = "Texture search of the scene's folder stopped after 2 files and folders, in " + scratch
        textures.TextureIndex = Small
        try:
            for label, kwargs in (("without materials", {"object_filter": {'UV'}}), ("with materials", {})):
                result = bpy.ops.import_scene.maxdrop(filepath=dst, **kwargs)
                ob = bpy.data.objects.get("IesPower")
                energy = ob.data.energy if ob is not None else None
                want = 1500.0 / 683.0 * options.LIGHT_STRENGTH
                text = bpy.data.texts.get("MaxDrop Report")
                body = text.as_string() if text is not None else ""
                line = next((x for x in body.splitlines() if "IesPower" in x and "rated lumens" in x), "")
                check("ies search stopped, %s: IesPower takes its power as its flux, its line says where the search "
                      "stopped, the report's stop line once" % label,
                      result == {'FINISHED'} and energy is not None and abs(energy - want) <= want * 1e-5
                      and lights.IES_UNREAD.split(", and ")[0] in line
                      and "(not found: texture search of the scene's folder stopped after 2 files and folders" in line
                      and body.count(stop) == 1 and lights.IES_RATED not in body,
                      "%s %s vs %s | %s" % (result, energy, want, body[-900:]))
                empty_scene()
        finally:
            textures.TextureIndex = original
    finally:
        empty_scene()
        shutil.rmtree(scratch, ignore_errors=True)


def check_reader_defect(first, second):
    """A TypeError, KeyError or AttributeError of the reading (a reader defect, never raised on purpose) reports the
    file as not imported, its type in the reason, instead of ending the operator: in a run of two files, synchronous
    and with the reading in the worker thread, the other file is still imported; alone, the operator reports Nothing
    imported; the pre-flight line says it is not readable."""
    import contextlib
    import io
    from maxdrop import packs
    from maxdrop.reader import assets
    from maxdrop.reader import scene as reader_scene
    name = os.path.basename(first)
    reason = "a defect in MaxDrop's reader (TypeError: maxdrop test: reader defect), see the console"
    original_table = assets.AssetTable.__dict__["from_file"]  # the classmethods themselves, put back as they were
    original_scene = reader_scene.Scene.__dict__["from_file"]
    calls = []

    def failing_first(cls, cf):
        calls.append(cf)
        if len(calls) == 1:
            raise TypeError("maxdrop test: reader defect")
        return original_table.__func__(cls, cf)

    def no_scene(cls, *args, **kwargs):
        raise KeyError("maxdrop test")

    try:
        for threaded in (False, True):
            label = "threaded" if threaded else "synchronous"
            empty_scene()
            del calls[:]
            assets.AssetTable.from_file = classmethod(failing_first)
            run = _cancel_run([first, second])
            steps = run.steps(threaded=threaded)
            console = io.StringIO()
            with contextlib.redirect_stdout(console):
                _advance(steps, lambda: False)
            assets.AssetTable.from_file = original_table
            printed = console.getvalue()
            sys.stdout.write(printed)
            check("reader defect: %s run, the traceback is in the console" % label,
                  "MaxDrop: reading %s failed, a defect in MaxDrop (please report it with this traceback):" % name
                  in printed and "Traceback (most recent call last)" in printed
                  and "TypeError: maxdrop test: reader defect" in printed, printed[-500:])
            check("reader defect: %s run, the file is not imported, the other one is" % label,
                  ('WARNING', "Not imported: %s: %s" % (name, reason)) in run.lines and len(bpy.data.objects) > 0
                  and len(calls) == 2,
                  "%d objects, %d calls | %s" % (len(bpy.data.objects), len(calls), run.lines[-3:]))
        empty_scene()
        del calls[:]
        assets.AssetTable.from_file = classmethod(failing_first)
        try:
            result, message = bpy.ops.import_scene.maxdrop(filepath=first), ""
        except RuntimeError as e:  # bpy.ops raises with the message when the operator reports an error
            result, message = {'CANCELLED'}, str(e)
        assets.AssetTable.from_file = original_table
        check("reader defect: one file, the operator reports Nothing imported with the reason",
              result == {'CANCELLED'} and "Nothing imported. %s: %s" % (name, reason) in message
              and not bpy.data.objects, "%s %r" % (result, message))
        reader_scene.Scene.from_file = classmethod(no_scene)
        line = packs._preflight(first)
        reader_scene.Scene.from_file = original_scene
        check("reader defect: the pre-flight line of a KeyError says the file is not readable",
              line == "Not readable as a .max file (a defect in MaxDrop's reader (KeyError: 'maxdrop test'), see "
                      "the console)", repr(line))
        # An AttributeError (an attribute read on None in a chunk walker) is in the net too. Its message is given,
        # so that the reason is the same on Python 3.11 and 3.13.
        def attribute_scene(cls, *args, **kwargs):
            raise AttributeError("maxdrop test: reader defect")

        def attribute_first(cls, cf):
            calls.append(cf)
            if len(calls) == 1:
                raise AttributeError("maxdrop test: reader defect")
            return original_table.__func__(cls, cf)

        reader_scene.Scene.from_file = classmethod(attribute_scene)
        line = packs._preflight(first)
        reader_scene.Scene.from_file = original_scene
        check("reader defect: the pre-flight line of an AttributeError says the file is not readable",
              line == "Not readable as a .max file (a defect in MaxDrop's reader (AttributeError: maxdrop test: "
                      "reader defect), see the console)", repr(line))
        empty_scene()
        del calls[:]
        assets.AssetTable.from_file = classmethod(attribute_first)
        run = _cancel_run([first, second])
        console = io.StringIO()
        with contextlib.redirect_stdout(console):
            _advance(run.steps(threaded=False), lambda: False)
        assets.AssetTable.from_file = original_table
        printed = console.getvalue()
        sys.stdout.write(printed)
        check("reader defect: an AttributeError of the read, the traceback is in the console",
              "MaxDrop: reading %s failed, a defect in MaxDrop (please report it with this traceback):" % name
              in printed and "AttributeError: maxdrop test: reader defect" in printed, printed[-500:])
        attribute_reason = reason.replace("TypeError", "AttributeError")
        check("reader defect: an AttributeError of the read, the file is not imported, the other one is",
              ('WARNING', "Not imported: %s: %s" % (name, attribute_reason)) in run.lines
              and len(bpy.data.objects) > 0 and len(calls) == 2,
              "%d objects, %d calls | %s" % (len(bpy.data.objects), len(calls), run.lines[-3:]))
    finally:
        assets.AssetTable.from_file = original_table
        reader_scene.Scene.from_file = original_scene
        empty_scene()


def check_asset_table_once(max_path):
    """One import of a file with lights and materials reads the file's asset table once (the scene description and
    the material conversion share it)."""
    from maxdrop.reader import assets
    empty_scene()
    original = assets.AssetTable.__dict__["from_file"]  # the classmethod itself, put back as it was
    calls = []

    def counting(cls, cf):
        calls.append(cf)
        return original.__func__(cls, cf)

    assets.AssetTable.from_file = classmethod(counting)
    try:
        result = bpy.ops.import_scene.maxdrop(filepath=max_path)
    finally:
        assets.AssetTable.from_file = original
    check("asset table: read once per import", result == {'FINISHED'} and len(calls) == 1,
          "%s, %d reads" % (result, len(calls)))
    empty_scene()
