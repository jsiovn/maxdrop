# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""MaxDrop: import 3ds Max .max scenes with their materials, without 3ds Max (File > Import, or drop the file).

One module per feature; each has register() / unregister() and its classes in a module-level _classes tuple.
"""

import importlib
import sys

# Register order, also the reload order: a module comes after the ones it imports at the top.
_NAMES = ("update", "prefs", "ops")


def _purge():
    # Everything else of the package is imported by these (options, packs and pipeline with ops) or on demand
    # (compat, the reader / convert / build sub-packages, the intake). A re-run of this file must not leave the old
    # ones cached, nor their names on the package: `from . import x` returns such a name without importing anything.
    prefix = __name__ + "."
    keep = {prefix + name for name in _NAMES}
    for full in [m for m in sys.modules if m.startswith(prefix) and m not in keep]:
        del sys.modules[full]
        globals().pop(full[len(prefix):], None)


def _load(name):
    # Reload Scripts and re-enabling after an upgrade on disk re-run this file while the old submodules
    # stay cached: reload those, import the ones a newer version added.
    full = "%s.%s" % (__name__, name)
    return importlib.reload(sys.modules[full]) if full in sys.modules else importlib.import_module(full)


_purge()
_modules = tuple(_load(name) for name in _NAMES)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
