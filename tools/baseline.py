# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Measure one import: wall time, peak memory and what arrived, with a time limit and a memory watch.

    python tools/baseline.py --blender <blender.exe> --profile <scratch dir> --label "scene A" --out <result.json>
                             [--limit-minutes 30] [--max-memory-gb 40] [--min-free-gb 6] <file.max>

Blender runs headless with --factory-startup and its own profile (--profile becomes BLENDER_USER_RESOURCES), imports
the file with the dev package of this checkout (tools/baseline_import.py) and is stopped, by its process id, when
the time is up, when it holds more than --max-memory-gb, or when the machine has less than --min-free-gb left.

The result JSON and this tool's output name the scene only by --label (import_report holds the counts of the
operator's "Imported ..." line, not its scene name); Blender's console log (next to the JSON, <out>.log) does name
objects and texture files, so keep both outside the repository for scenes that are not yours.
The memory watch uses the Windows process API; elsewhere the tool refuses to run. Standard library only.
"""
import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The operator's summary of one scene (convert/report.py, Report.summary, printed with "MaxDrop: "). The name is
# greedy, so a name holding ": " still parses. Curves are named only when some were built; group 5 is what was
# left out, e.g. "3 placeholders, 2 issues".
IMPORTED = re.compile(r"^MaxDrop: Imported .*: (\d+) objects?, (\d+) mesh(?:es)?(?:, (\d+) curves?)?"
                      r"(?:, (\d+) materials?)?"
                      r"(?:, nothing left out\.|; (.*)\. See the text MaxDrop Report\.)$")
LEFT_OUT = re.compile(r"(\d+) (placeholder|modifier|texture|approximated|material problem|issue)")
LEFT_OUT_KEYS = {"placeholder": "placeholders", "modifier": "modifiers_not_applied",
                 "texture": "textures_missing", "approximated": "approximated",
                 "material problem": "material_problems", "issue": "issues"}
GB = 1024 ** 3


class _Counters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


class _Memory(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def process_memory(handle):
    """(working set, peak working set, commit, peak commit) of the process, in bytes."""
    counters = _Counters()
    counters.cb = ctypes.sizeof(counters)
    get = ctypes.windll.psapi.GetProcessMemoryInfo
    get.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not get(handle, ctypes.byref(counters), counters.cb):
        return None
    return (counters.WorkingSetSize, counters.PeakWorkingSetSize, counters.PagefileUsage,
            counters.PeakPagefileUsage)


def free_memory():
    """Physical memory the machine has left, in bytes."""
    status = _Memory()
    status.dwLength = ctypes.sizeof(status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.ullAvailPhys


def read_log(path):
    """What the operator printed, without the names: the counts of its "Imported ..." lines (summed when a pack
    held several scenes, None without one; materials is None only when no line names them) and whether a
    traceback was printed."""
    report, traceback = None, False
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = IMPORTED.match(line.rstrip("\r\n"))
                if m:
                    if report is None:
                        report = dict({"objects": 0, "meshes": 0, "curves": 0, "materials": None},
                                      **{key: 0 for key in LEFT_OUT_KEYS.values()})
                    report["objects"] += int(m.group(1))
                    report["meshes"] += int(m.group(2))
                    report["curves"] += int(m.group(3) or 0)
                    if m.group(4) is not None:
                        report["materials"] = (report["materials"] or 0) + int(m.group(4))
                    for n, word in LEFT_OUT.findall(m.group(5) or ""):
                        report[LEFT_OUT_KEYS[word]] += int(n)
                elif line.startswith("Traceback (most recent call last)"):
                    traceback = True
    except OSError:
        pass
    return {"import_report": report, "traceback": traceback}


def run(args):
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    log, counts = out + ".log", out + ".counts.json"
    for path in (out, log, counts):
        if os.path.exists(path):
            os.remove(path)
    os.makedirs(args.profile, exist_ok=True)
    env = dict(os.environ, BLENDER_USER_RESOURCES=os.path.abspath(args.profile), PYTHONIOENCODING="utf-8")
    command = [args.blender, "--background", "--factory-startup", "--python-exit-code", "1",
               "--python", os.path.join(ROOT, "tools", "baseline_import.py"),
               "--", ROOT, os.path.abspath(args.file), counts]
    peak_set = peak_commit = 0
    least_free = free_memory()
    outcome = "finished"
    start = time.monotonic()
    with open(log, "wb") as sink:
        process = subprocess.Popen(command, stdout=sink, stderr=subprocess.STDOUT, env=env)
        handle = int(process._handle)
        while process.poll() is None:
            memory = process_memory(handle)
            if memory:
                peak_set, peak_commit = max(peak_set, memory[1]), max(peak_commit, memory[3])
            free = free_memory()
            least_free = min(least_free, free)
            elapsed = time.monotonic() - start
            if elapsed > args.limit_minutes * 60:
                outcome = "stopped: time limit"
            elif memory and memory[2] > args.max_memory_gb * GB:
                outcome = "stopped: memory limit"
            elif free < args.min_free_gb * GB:
                outcome = "stopped: machine low on memory"
            if outcome != "finished":
                process.kill()   # this process only: other Blender sessions on the machine are not ours
                process.wait()
                break
            time.sleep(0.5)
        memory = process_memory(handle)
        if memory:
            peak_set, peak_commit = max(peak_set, memory[1]), max(peak_commit, memory[3])
    wall = time.monotonic() - start
    found = {
        "label": args.label,
        "outcome": outcome if outcome != "finished" or process.returncode == 0 else "failed",
        "exit_code": process.returncode,
        "wall_seconds": round(wall, 1),
        "peak_working_set_gb": round(peak_set / GB, 2),
        "peak_commit_gb": round(peak_commit / GB, 2),
        "least_free_memory_gb": round(least_free / GB, 1),
        "file_mb": round(os.path.getsize(args.file) / 1024 ** 2),
        "limits": {"minutes": args.limit_minutes, "max_memory_gb": args.max_memory_gb,
                   "min_free_gb": args.min_free_gb},
        "counts": None,
    }
    if os.path.isfile(counts):
        with open(counts, encoding="utf-8") as f:
            found["counts"] = json.load(f)
        os.remove(counts)
    found.update(read_log(log))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(found, f, indent=1)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", help="the .max file to import")
    parser.add_argument("--blender", required=True, help="path of the Blender executable")
    parser.add_argument("--profile", required=True, help="scratch folder for Blender's profile")
    parser.add_argument("--label", default="scene", help="how the result names the file")
    parser.add_argument("--out", required=True, help="result JSON; Blender's console log goes to <out>.log")
    parser.add_argument("--limit-minutes", type=float, default=30.0)
    parser.add_argument("--max-memory-gb", type=float, default=40.0)
    parser.add_argument("--min-free-gb", type=float, default=6.0)
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("the memory watch uses the Windows process API")
    found = run(args)
    print(json.dumps(found, indent=1))
    return 0 if found["outcome"] == "finished" else 1


if __name__ == "__main__":
    sys.exit(main())
