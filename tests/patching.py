# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""patch_all(): mock.patch.object on a name of a package and on every module of it that holds the same object.

A module split into a package (convert/scene/, convert/extrude/, ...) keeps its names in its __init__.py, but its
code reads a name in the module that defines or imports it: patching the package alone misses those readers.

    with patch_all(extrude, "MAX_LOOPS", 1): ...
    with patch_all(extrude, "triangulate", wraps=extrude.triangulate) as tried: ...

The arguments are mock.patch.object's; the replacement is made once (by the patch of the package) and set in every
holder, so `as` gives the one object all of them see. Only modules under the package are searched: a module
outside it that imports the name with `from ... import` keeps its own binding. Plain Python, no Blender.
"""
import contextlib
import sys
from unittest import mock


def holders(package, name):
    """The package and the modules under it whose `name` is the package's object, the package first."""
    original = getattr(package, name)
    prefix = package.__name__ + "."
    found = [package]
    for full, module in sorted(sys.modules.items()):
        if full.startswith(prefix) and module is not None and module is not package:
            if name in vars(module) and vars(module)[name] is original:
                found.append(module)
    return found


class patch_all:
    """A context manager, also with start() / stop() as a mock patcher has."""

    def __init__(self, package, name, *args, **kwargs):
        self.package, self.name, self.args, self.kwargs = package, name, args, kwargs
        self._stack = None

    def start(self):
        modules = holders(self.package, self.name)
        self._stack = contextlib.ExitStack()
        replacement = self._stack.enter_context(mock.patch.object(self.package, self.name, *self.args, **self.kwargs))
        for module in modules[1:]:
            self._stack.enter_context(mock.patch.object(module, self.name, getattr(self.package, self.name)))
        return replacement

    def stop(self):
        stack, self._stack = self._stack, None
        stack.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False
