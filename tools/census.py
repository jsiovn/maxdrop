# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Class census of a .max file: what its Scene stream is made of, by class. No Blender.

    python -I tools/census.py <file.max> [--json]

Counts the objects per class (name, ClassID, superclass), the nodes per base-object class (through derived
objects, so a node with modifiers counts under the class at the bottom of its stack), and the modifier classes
of the derived objects. It reads the file through maxdrop/reader (scene.py), loaded by path so no bpy is pulled.

The output names classes only, never a node, material or layer, and not the file: it may be run on a scene that
is not ours and pasted into notes. A node that cannot be read counts as unreadable instead of stopping the run.
Exit code 0, 1 when the file cannot be read, 2 for a usage error.
"""
import argparse
import collections
import importlib.util
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_READER = os.path.join(ROOT, "maxdrop", "reader")


def _load(name, path, package_dir=None):
    if name in sys.modules:
        return sys.modules[name]
    kw = {"submodule_search_locations": [package_dir]} if package_dir else {}
    spec = importlib.util.spec_from_file_location(name, path, **kw)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# By path, as a package of its own: `import maxdrop` would run the add-on's __init__ and pull bpy.
_load("maxdrop_reader", os.path.join(_READER, "__init__.py"), _READER)
cfb = _load("maxdrop_reader.cfb", os.path.join(_READER, "cfb.py"))
chunks = _load("maxdrop_reader.chunks", os.path.join(_READER, "chunks.py"))
scene = _load("maxdrop_reader.scene", os.path.join(_READER, "scene.py"))

SPECIAL_NAMES = {scene.DERIVED_OBJECT: "(derived object)"}
NONE = {"name": "(none)", "class_id": None, "superclass": None}


def _describe(s, index):
    """The class of object `index` as a JSON-ready dict; special ids get a name of their own."""
    entry = s.entry(index)
    if entry is None:
        cid = s.class_index(index)
        return {"name": SPECIAL_NAMES.get(cid, "(special 0x%04X)" % cid), "class_id": None, "superclass": None,
                "special_id": "0x%04X" % cid}
    return {"name": entry.name, "class_id": ["0x%08X" % entry.class_a, "0x%08X" % entry.class_b],
            "superclass": "0x%X" % entry.superclass}


def _key(desc):
    return desc["name"], tuple(desc["class_id"] or ()), desc["superclass"] or "", desc.get("special_id", "")


def _rows(counter, descs):
    return [dict(descs[k], count=n) for k, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]


def census(path):
    """The census of one .max file as a dict (see format_text for what each part means)."""
    start = time.perf_counter()
    with cfb.CompoundFile(path) as cf:
        s = scene.Scene.from_file(cf)
        class_counts, firsts = collections.Counter(), {}
        for i in range(len(s)):
            cid = s.class_index(i)
            class_counts[cid] += 1
            firsts.setdefault(cid, i)
        classes, descs = collections.Counter(), {}
        for cid, n in class_counts.items():
            desc = _describe(s, firsts[cid])
            descs[_key(desc)] = desc
            classes[_key(desc)] += n

        base, base_descs = collections.Counter(), {}
        modifiers, modifier_descs = collections.Counter(), {}
        holders = collections.Counter()
        depths = collections.Counter()
        derived_seen = set()
        unreadable = with_modifiers = 0
        for i in s.node_indices:
            try:
                node = s.node(i)
                stack = s.object_stack(node.object) if node.object is not None else None
            except (chunks.ChunkError, IndexError):
                unreadable += 1
                continue
            desc = NONE if stack is None or stack.base is None else _describe(s, stack.base)
            base_descs[_key(desc)] = desc
            base[_key(desc)] += 1
            if stack is None:
                continue
            if stack.modifiers:
                with_modifiers += 1
            if stack.derived and stack.derived[0] not in derived_seen:  # an instanced stack counts once
                derived_seen.add(stack.derived[0])
                depths[len(stack.modifiers)] += 1
                held = set()
                for m in stack.modifiers:
                    mdesc = _describe(s, m)
                    modifier_descs[_key(mdesc)] = mdesc
                    modifiers[_key(mdesc)] += 1
                    held.add(_key(mdesc))
                for k in held:
                    holders[k] += 1
        top_level = len(s.children()) if s.node_indices else 0
        cut = len(s.cut_cycles)
        result = {
            "root_id": "0x%04X" % s.root_id,
            "objects": len(s),
            "classes_listed": len(s.classes),
            "classes": _rows(classes, descs),
            "nodes": {
                "total": len(s.node_indices),
                "top_level": top_level,
                "cycles_cut": cut,
                "unreadable": unreadable,
                "with_modifiers": with_modifiers,
                "by_base_class": _rows(base, base_descs),
            },
            "modifiers": {
                "stacks": len(derived_seen),
                "stack_depths": {str(k): v for k, v in sorted(depths.items())},
                "by_class": [dict(row, stacks=holders[_key(row)]) for row in _rows(modifiers, modifier_descs)],
            },
        }
        del s
    result["seconds"] = round(time.perf_counter() - start, 3)
    return result


def _class_line(row, extra=""):
    cid = "(%s, %s)" % tuple(row["class_id"]) if row["class_id"] else row.get("special_id", "")
    return "  %7d  %-36s %-26s %-7s%s" % (row["count"], row["name"][:36], cid, row["superclass"] or "", extra)


def format_text(result):
    out = ["Scene root 0x%s, %d objects of %d listed classes, read in %.2f s" %
           (result["root_id"][2:], result["objects"], result["classes_listed"], result["seconds"]), "",
           "Objects per class:"]
    out += [_class_line(row) for row in result["classes"]]
    nodes = result["nodes"]
    out += ["", "Nodes: %d (top level %d, with modifiers %d, unreadable %d, parent cycles cut %d)" %
            (nodes["total"], nodes["top_level"], nodes["with_modifiers"], nodes["unreadable"], nodes["cycles_cut"]),
            "Nodes per base-object class:"]
    out += [_class_line(row) for row in nodes["by_base_class"]]
    mods = result["modifiers"]
    depths = ", ".join("%s: %d" % kv for kv in mods["stack_depths"].items()) or "none"
    out += ["", "Modifier stacks: %d (modifiers per stack -> stacks: %s)" % (mods["stacks"], depths),
            "Modifiers per class (count, then the number of stacks holding it):"]
    out += [_class_line(row, "  in %d" % row["stacks"]) for row in mods["by_class"]]
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", help="a .max file")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.file):
        print("census: no such file", file=sys.stderr)
        return 2
    try:
        result = census(args.file)
    except ValueError as exc:
        print("census: cannot read the file: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:  # its str() carries the path
        print("census: cannot read the file: %s" % (exc.strerror or type(exc).__name__), file=sys.stderr)
        return 1
    if args.json:
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(format_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
