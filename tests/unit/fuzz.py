# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deterministic fuzzing of the .max reader and of the zip intake, without Blender.

Case k of a seed is a pure function of (SEED, the seed's name, k): a failure names `<seed>:<k>` and replays
anywhere. A .max case mutates a committed fixture (bits and bytes flipped in the header, the FAT, the directory and
the streams the reader opens, the file cut short, chunk sizes and leading counts set to extremes, container bits
toggled, directory entries and header fields bent, FAT entries redirected, sectors swapped) and runs it through what
the operator runs: the pre-flight (summary, Scene, unit), then the reading (Scene, unit, asset table, scene
description with the saved views, the material and texture-map conversion and the swatch note). A seed named
`<fixture>+gzip` (GZIP_SEEDS) is that fixture with its Scene stream rewritten here as gzip members, as 3ds Max's
Compress on Save writes it: a compressed stream is not walked for chunks; its cases bend the deflate bytes and the
gzip framing instead (headers, trailers, block types, member boundaries, members dropped or repeated, the stream
cut, a member that inflates to megabytes). Deflate output depends on the zlib build, so such a seed replays on the
same zlib only. A zip case mutates a scene pack built here (central directory, local headers, end record, names,
sizes, flags, methods, attributes, truncation) and runs list_pack and unpack in a sandbox of its own.

A case passes when it reads (`ok`), is refused with a MaxFileError (`refused`; PackError for a pack), or, for a
.max, fails inside the material stage, which the operator turns into a report line (`materials`: counted, not a
failure). Anything else is `escaped`: a defect. Every case must end within CASE_SECONDS and the process stay under
MEMORY_LIMIT. A pack case also checks the sandbox afterwards: nothing outside the destination, no staging folder.

    python -I tests/unit/fuzz.py max --cases 100000 --jobs 18 --out <results.jsonl> [--minutes 9]
    python -I tests/unit/fuzz.py zip --cases 100000 --jobs 18 --out <results.jsonl>
    python -I tests/unit/fuzz.py summary --out <results.jsonl>
    python -I tests/unit/fuzz.py replay box_poly_standard.max:4711
    python -I tests/unit/fuzz.py max --seeds box_poly_standard.max+gzip --cases 100000 --out <results.jsonl>
    python -I tests/unit/fuzz.py slice --target max --cases 16           # one JSON line: what the plain suite runs

The campaign runs shards of cases in worker processes; a case that runs past CASE_SECONDS ends its worker
(faulthandler) and is recorded as a hang. Results are appended to the --out file, one JSON line per shard, so a
campaign stopped by --minutes resumes where it was. tests/unit/test_fuzz.py and tests/test_intake_fuzz.py run a
bounded slice in the plain test suite.
"""
import argparse
import faulthandler
import json
import os
import sys
import tempfile
import time
import types


# The parts are modules of a package of their own whose path is this folder, whatever name this file runs under (a
# script, a spawned worker, the tests' module); every name of the harness stays reachable from here.
_PARTS = "maxdrop_fuzz_parts"
if _PARTS not in sys.modules:
    _parts = types.ModuleType(_PARTS)
    _parts.__path__ = [os.path.dirname(os.path.abspath(__file__))]
    sys.modules[_PARTS] = _parts
from maxdrop_fuzz_parts.fuzz_common import (  # noqa: E402,F401 (after the loader; re-exported)
    ROOT, FIXTURES, SEED, CASE_SECONDS, MEMORY_LIMIT, _BLAS_THREADS, _PKG, _pkg, _mod, errors, cfb, chunks,
    MaxFileError, EXTREMES, BYTES, _rng, peak_memory, Escaped, _pick, _region_offset, _put32, _extreme, _remove,
)
from maxdrop_fuzz_parts.fuzz_max import (  # noqa: E402,F401 (after the loader; re-exported)
    _STREAMS, _CHUNKED, _REGION_WEIGHTS, _KINDS, _HEADER_FIELDS, _DIR_FIELDS, GZIP_SEEDS, GZIP_SUFFIX, _GZIP_PARTS,
    _GZIP_PADDING, _GZIP_KINDS, _GZIP_REWRITES, _GZIP_FLG, _EXPAND, gzip_member, gzip_members, _chain_runs, _dir_entry,
    _put, _set_size, _write_stream, gzip_scene, GzipStream, _file_offsets, MaxSeed, _EXPANDED, _expanded, _mutate_gzip,
    _mutate_max, max_case, _Reader, run_max,
)
from maxdrop_fuzz_parts.fuzz_zip import (  # noqa: E402,F401 (after the loader; re-exported)
    _ZIP_KINDS, _RISKY_NAMES, _ZIP_FIELDS_LOCAL, _ZIP_FIELDS_CENTRAL, _ZIP_FIELDS_EOCD, _zip_bytes, _payload, ZipSeed,
    _mutate_zip, zip_case, _archive, _tree, read_zip, run_zip, ZIP_SEEDS,
)


def seed_names(target):
    """The names of the seeds of target: the fixtures and their gzip variants, or the packs."""
    if target == "max":
        names = [os.path.basename(p) for p in FIXTURES]
        return names + [n + GZIP_SUFFIX for n in GZIP_SEEDS if n in names]
    return list(ZIP_SEEDS)


def max_seed(name):
    fixture = name[:-len(GZIP_SUFFIX)] if name.endswith(GZIP_SUFFIX) else name
    with open(os.path.join(ROOT, "tests", "fixtures", fixture), "rb") as f:
        raw = f.read()
    return MaxSeed(name, gzip_scene(raw) if fixture != name else raw)


def seeds(target, names=None):
    picked = [n for n in seed_names(target) if names is None or n in names]
    if target == "max":
        return [max_seed(n) for n in picked]
    return [ZipSeed(n) for n in picked]


def run_case(target, seed, k, folder, base=SEED):
    return (run_max if target == "max" else run_zip)(seed, k, folder, base)


# --- campaign ------------------------------------------------------------------------------------------------------

def run_range(target, seed, start, stop, current=None, announce=False):
    """Cases [start, stop) of seed, each under the faulthandler watchdog (a case past CASE_SECONDS ends the
    process with its stack): {"counts", "materials", "escapes", "slowest", "slowest_case"}. current: a
    multiprocessing.Value told the case being run."""
    folder = tempfile.mkdtemp(prefix="maxdrop-fuzz-")
    counts, materials, escapes = {}, {}, []
    slowest = (0.0, None)
    try:
        for k in range(start, stop):
            if current is not None:
                current.value = k
            if announce:  # the last line before a faulthandler stack names the case that hung
                sys.stderr.write("%s:%d\n" % (seed.name, k))
                sys.stderr.flush()
            faulthandler.dump_traceback_later(CASE_SECONDS, exit=True)
            try:
                outcome, seconds = run_case(target, seed, k, folder)
            except Escaped as e:
                outcome, seconds = "escaped", 0.0
                if len(escapes) < 50:
                    escapes.append(str(e)[:600])
            finally:
                faulthandler.cancel_dump_traceback_later()
            if isinstance(outcome, tuple):
                kind = type(outcome[1]).__name__
                materials[kind] = materials.get(kind, 0) + 1
                outcome = "materials"
            counts[outcome] = counts.get(outcome, 0) + 1
            if seconds > slowest[0]:
                slowest = (seconds, k)
    finally:
        _remove(folder)
    return {"counts": counts, "materials": materials, "escapes": escapes, "slowest": slowest[0],
            "slowest_case": slowest[1]}


def run_slice(target, cases):
    """Cases [0, cases) of every seed of target in this process: the summed counts, the escapes, the slowest case
    and this process's peak memory, for the plain suite (which runs it in a child process of its own, so that the
    peak is the slice's alone)."""
    total = {"counts": {}, "materials": {}, "escapes": [], "slowest": 0.0, "slowest_case": None}
    for seed in seeds(target):
        r = run_range(target, seed, 0, cases, announce=True)
        for key in ("counts", "materials"):
            for k, v in r[key].items():
                total[key][k] = total[key].get(k, 0) + v
        total["escapes"] += r["escapes"]
        if r["slowest"] >= total["slowest"]:
            total["slowest"], total["slowest_case"] = r["slowest"], "%s:%s" % (seed.name, r["slowest_case"])
    total["peak_memory"] = peak_memory()
    return total


def _worker(target, name, start, stop, current, results):
    r = run_range(target, seeds(target, {name})[0], start, stop, current)
    r.update({"target": target, "seed": name, "start": start, "stop": stop, "peak_memory": peak_memory()})
    results.put(r)


def _covered(out):
    """{(target, seed): [(start, stop)]}: the case ranges the --out file already holds (a shard split by a hang
    is held as its pieces)."""
    done = {}
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                done.setdefault((r["target"], r["seed"]), []).append((r["start"], r["stop"]))
    return done


def _missing(ranges, start, stop):
    """The pieces of [start, stop) that ranges do not cover."""
    out, at = [], start
    for a, b in sorted(ranges):
        if b <= at or a >= stop:
            continue
        if a > at:
            out.append((at, a))
        at = max(at, b)
    if at < stop:
        out.append((at, stop))
    return out


def _write(out, record):
    with open(out, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def campaign(target, cases, jobs, out, shard, minutes, names=None, first=0):
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    all_names = seed_names(target)
    if names:
        all_names = [n for n in all_names if n in names]
    covered = _covered(out)
    todo = [(n, a, b) for s in range(first, cases, shard) for n in all_names
            for a, b in _missing(covered.get((target, n), ()), s, min(s + shard, cases))]
    for name in _BLAS_THREADS:  # spawned workers inherit it: numpy then reserves no buffers per core
        os.environ[name] = "1"
    results = ctx.Queue()
    running = {}  # process -> (shard, current)
    deadline = time.time() + 60 * minutes if minutes else None
    finished = 0
    pending = {}
    while todo or running:
        while todo and len(running) < jobs and (deadline is None or time.time() < deadline):
            name, start, stop = todo.pop(0)
            current = ctx.Value("q", start)
            p = ctx.Process(target=_worker, args=(target, name, start, stop, current, results), daemon=True)
            p.start()
            running[p] = ((name, start, stop), current)
        if not running:
            break
        try:
            r = results.get(timeout=0.5)
            pending[(r["seed"], r["start"], r["stop"])] = r
        except Exception:
            pass
        for p in [p for p in running if not p.is_alive()]:
            (name, start, stop), current = running[p]
            key = (name, start, stop)
            if p.exitcode == 0:
                r = pending.pop(key, None)
                if r is None:
                    t = time.time() + 30
                    while key not in pending and time.time() < t:
                        try:
                            r2 = results.get(timeout=0.5)
                            pending[(r2["seed"], r2["start"], r2["stop"])] = r2
                        except Exception:
                            pass
                    r = pending.pop(key, None)
                if r is None:  # ended cleanly without a result: recorded, never run again on its own
                    r = {"target": target, "seed": name, "start": start, "stop": stop,
                         "counts": {"lost": stop - start}, "materials": {},
                         "escapes": ["%s:%d-%d: worker ended without a result" % (name, start, stop)],
                         "slowest": 0.0, "slowest_case": None, "peak_memory": None}
                _write(out, r)
                finished += 1
            else:
                k = current.value
                _write(out, {"target": target, "seed": name, "start": k, "stop": k + 1, "counts": {"hang": 1},
                             "materials": {}, "escapes": ["%s:%d: worker ended with code %s (over %.0f s, or a crash)"
                                                          % (name, k, p.exitcode, CASE_SECONDS)],
                             "slowest": CASE_SECONDS, "slowest_case": k, "peak_memory": None})
                if start < k:
                    todo.insert(0, (name, start, k))
                if k + 1 < stop:
                    todo.insert(0, (name, k + 1, stop))
            p.join()
            del running[p]
        if deadline is not None and time.time() >= deadline and not running:
            break
    print("%d shards done, %d left" % (finished, len(todo)))
    return len(todo)


def summary(out):
    totals, per_seed, escapes, materials = {}, {}, [], {}
    slowest, peak = (0.0, None), 0
    with open(out, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            s = per_seed.setdefault((r["target"], r["seed"]), {})
            for k, v in r["counts"].items():
                totals[k] = totals.get(k, 0) + v
                s[k] = s.get(k, 0) + v
            for k, v in r["materials"].items():
                materials[k] = materials.get(k, 0) + v
            escapes += r["escapes"]
            if r["slowest"] > slowest[0]:
                slowest = (r["slowest"], "%s:%s" % (r["seed"], r["slowest_case"]))
            peak = max(peak, r["peak_memory"] or 0)
    cases = sum(totals.values())
    print("cases %d: %s" % (cases, ", ".join("%s %d" % kv for kv in sorted(totals.items()))))
    print("material-stage failures by type: %s" % (materials or "none"))
    print("slowest case %.3f s (%s); peak worker memory %.1f MB" % (slowest[0], slowest[1], peak / 1e6))
    print("seeds: %d, cases per seed: %s" % (len(per_seed), sorted({sum(v.values()) for v in per_seed.values()})))
    for e in escapes[:20]:
        print("ESCAPED " + e)
    return totals, escapes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("max", "zip", "summary", "replay", "slice"))
    ap.add_argument("case", nargs="?", help="replay: <seed>:<k>")
    ap.add_argument("--cases", type=int, default=100000, help="cases [--first, --cases) of each seed")
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--shard", type=int, default=2000)
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--seeds", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--target", choices=("max", "zip"), default="max", help="slice: which harness")
    a = ap.parse_args(argv)
    if a.command == "slice":
        print(json.dumps(run_slice(a.target, a.cases)))
        return 0
    if a.command == "summary":
        totals, escapes = summary(a.out)
        return 1 if escapes or totals.get("hang") or totals.get("lost") else 0
    if a.command == "replay":
        name, k = a.case.rsplit(":", 1)
        target = "zip" if name.startswith("zip:") else "max"
        folder = tempfile.mkdtemp(prefix="maxdrop-fuzz-")
        try:
            seed = seeds(target, {name})[0]
            spec = (max_case if target == "max" else zip_case)(seed, int(k))[1]
            print("%s:%s %s" % (name, k, spec))
            print(run_case(target, seed, int(k), folder))
        finally:
            _remove(folder)
        return 0
    left = campaign(a.command, a.cases, a.jobs, a.out, a.shard, a.minutes, set(a.seeds) if a.seeds else None,
                    a.first)
    return 2 if left else 0


if __name__ == "__main__":
    sys.exit(main())
