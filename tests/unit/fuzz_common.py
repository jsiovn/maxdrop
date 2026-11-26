# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the fuzz harness's parts share: paths, budgets, the reader modules loaded without Blender, the
random source, the memory probe and the mutation helpers."""
import glob
import importlib
import os
import random
import shutil
import stat
import struct
import sys
import time
import types


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.max")))
SEED = 20261119
CASE_SECONDS = 5.0
MEMORY_LIMIT = 1 << 30
# One thread for numpy's BLAS: otherwise it reserves buffers per core at import, hundreds of MB on a 20-core
# machine, which the peak memory of a worker would count against MEMORY_LIMIT.
_BLAS_THREADS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")

# A package of its own whose path is maxdrop/: relative imports resolve and maxdrop/__init__.py (bpy) never runs.
_PKG = "maxdrop_fuzz"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [os.path.join(ROOT, "maxdrop")]
    sys.modules[_PKG] = _pkg


def _mod(name):
    return importlib.import_module(_PKG + "." + name)


errors = _mod("reader.errors")
cfb = _mod("reader.cfb")
chunks = _mod("reader.chunks")
MaxFileError = errors.MaxFileError

EXTREMES = (0, 1, 2, 3, 4, 5, 6, 7, 8, 13, 14, 15, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFFFF, 0x10000,
            0x7FFFFFFF, 0x80000000, 0x80000006, 0x8000000E, 0xFFFFFFF0, 0xFFFFFFFA, 0xFFFFFFFB, 0xFFFFFFFC,
            0xFFFFFFFD, 0xFFFFFFFE, 0xFFFFFFFF)
BYTES = (0x00, 0x01, 0x7F, 0x80, 0xFE, 0xFF)


def _rng(name, k, seed=SEED):
    return random.Random("%d/%s/%d" % (seed, name, k))  # a str seed hashes with SHA-512: the same in every process


def peak_memory():
    """The peak memory of this process in bytes (the larger of peak working set and peak private bytes on Windows,
    the peak resident set elsewhere); None when the system does not say."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
        c = Counters()
        c.cb = ctypes.sizeof(c)
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return None
        return max(c.PeakWorkingSetSize, c.PeakPagefileUsage)
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


class Escaped(AssertionError):
    """A case that ended in something other than ok / refused: the replay id, the mutation and the exception."""


def _pick(rng, weighted):
    total = sum(w for _, w in weighted)
    r = rng.uniform(0, total)
    for item, w in weighted:
        r -= w
        if r <= 0:
            return item
    return weighted[-1][0]


def _region_offset(rng, runs):
    total = sum(n for _, n in runs)
    r = rng.randrange(total)
    for start, n in runs:
        if r < n:
            return start + r
        r -= n
    raise AssertionError("empty region")


def _put32(buf, offsets, value):
    for off, b in zip(offsets, struct.pack("<I", value & 0xFFFFFFFF)):
        if off < len(buf):
            buf[off] = b


def _extreme(rng, old=None):
    if old is not None and rng.random() < 0.25:
        return (old + rng.choice((-7, -6, -1, 1, 6, 7, 1 << 16, 1 << 24))) & 0xFFFFFFFF
    if rng.random() < 0.15:
        return rng.getrandbits(32)
    return rng.choice(EXTREMES)


def _remove(path):
    def retry(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    for _ in range(5):
        shutil.rmtree(path, onerror=retry)
        if not os.path.exists(path):
            return
        time.sleep(0.05)
    raise AssertionError("could not remove %s" % path)
