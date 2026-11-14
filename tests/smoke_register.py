# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Register smoke test for the MaxDrop dev package (no .blend, no .max, no network).

Run headless with an isolated profile so your own preferences are never touched:
  $env:BLENDER_USER_RESOURCES="<scratch>\\profile"
  & blender --background --factory-startup --python-exit-code 1 --python tests\\smoke_register.py [-- <repo root>]

Imports `maxdrop` from the repo root (default: one level above this file), registers it, checks every class in each
module's `_classes`, the operators, the file handler and the File > Import entry, reloads the package the way
Reload Scripts does, registers again, then unregisters and checks everything is gone.
Prints `SMOKE PASSED` (exit 0) or `SMOKE FAILED` (exit 1).
"""
import importlib
import os
import sys
import traceback

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ROOT = os.path.abspath(argv[0] if argv else os.path.join(os.path.dirname(__file__), ".."))
OPERATORS = ("IMPORT_SCENE_OT_maxdrop", "MAXDROP_OT_check_updates", "MAXDROP_OT_texture_dir_add",
             "MAXDROP_OT_texture_dir_remove")
HANDLER = "IO_FH_maxdrop"
ENGINE = "maxdrop.import_max"
INTAKE = "maxdrop.intake"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  [%s]" % detail if detail else ""))
    if not cond:
        failures.append(name)


def registered(pkg):
    """Every class, as (module, class name, is_registered)."""
    return [(m.__name__.rsplit(".", 1)[-1], c.__name__, c.is_registered) for m in pkg._modules for c in m._classes]


def operators():
    return [name for name in OPERATORS if hasattr(bpy.types, name)]


def in_import_menu(pkg):
    ops = sys.modules[pkg.__name__ + ".ops"]
    return ops.menu_func in bpy.types.TOPBAR_MT_file_import._dyn_ui_initialize()


def run():
    sys.path.insert(0, ROOT)
    import maxdrop as pkg
    check("package imported from the repo root",
          os.path.normcase(os.path.dirname(os.path.dirname(pkg.__file__))) == os.path.normcase(ROOT), pkg.__file__)
    check("_modules follows _NAMES", tuple(m.__name__.rsplit(".", 1)[-1] for m in pkg._modules) == pkg._NAMES)

    for round_ in ("register", "re-register after reload"):
        pkg.register()
        rows = registered(pkg)
        missing = ["%s.%s" % (m, c) for m, c, ok in rows if not ok]
        check("%s: %d classes registered" % (round_, len(rows)), rows and not missing, ", ".join(missing))
        check("%s: %d operators" % (round_, len(operators())), operators() == list(OPERATORS),
              sorted(set(OPERATORS) - set(operators())))
        handler = getattr(bpy.types, HANDLER, None)
        # .zip is left out on purpose: Blender's extension installer takes every dropped .zip first.
        check("%s: the file handler takes .max, .rar and .7z, imports with import_scene.maxdrop, exports nothing"
              % round_, handler is not None and handler.bl_import_operator == "import_scene.maxdrop"
              and handler.bl_file_extensions == ".max;.rar;.7z" and not getattr(handler, "bl_export_operator", ""))
        props = bpy.ops.import_scene.maxdrop.get_rna_type().properties
        check("%s: the operator has the Scene field of a pack" % round_, "pack_scene" in props.keys())
        check("%s: the file browser shows .max, .zip, .rar and .7z" % round_,
              props["filter_glob"].default == "*.max;*.zip;*.rar;*.7z")
        check("%s: File > Import has the entry" % round_, in_import_menu(pkg))
        check("%s: the preferences belong to the package" % round_,
              sys.modules[pkg.__name__ + ".prefs"].MaxDropPreferences.bl_idname == pkg.__name__)
        check("%s: the engine is not loaded before an import" % round_, ENGINE not in sys.modules)
        check("%s: the scene pack intake is not loaded before an import" % round_, INTAKE not in sys.modules)
        pkg.unregister()
        left = ["%s.%s" % (m, c) for m, c, ok in registered(pkg) if ok]
        check("%s: unregister removes every class" % round_, not left, ", ".join(left))
        check("%s: unregister removes the operators" % round_, not operators(), operators())
        check("%s: unregister removes the file handler" % round_, not hasattr(bpy.types, HANDLER))
        check("%s: unregister removes the File > Import entry" % round_, not in_import_menu(pkg))
        if round_ == "register":
            # What an import leaves behind must not survive a reload: the files may be a newer version's.
            engine = importlib.import_module(ENGINE)
            check("the engine loads", hasattr(engine, "load") and getattr(pkg, "import_max", None) is engine)
            intake = importlib.import_module(INTAKE + ".archive")
            check("the scene pack intake loads", hasattr(intake, "unpack") and hasattr(pkg, "intake"))
            pkg = importlib.reload(pkg)
            check("reload drops the cached engine", ENGINE not in sys.modules and not hasattr(pkg, "import_max"))
            check("reload drops the cached intake",
                  not [m for m in sys.modules if m.startswith(INTAKE)] and not hasattr(pkg, "intake"))


try:
    run()
except Exception:
    traceback.print_exc()
    failures.append("exception")

print("SMOKE FAILED: %s" % ", ".join(failures) if failures else "SMOKE PASSED")
sys.stdout.flush()
if failures:
    sys.exit(1)
