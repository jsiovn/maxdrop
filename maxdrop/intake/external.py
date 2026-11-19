# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene packs in .rar and .7z: unpacked by a program already on the computer (UnRAR, 7-Zip or bsdtar).

Nothing is bundled. A program is only taken from a fixed absolute path (never the current folder, a bare name, a
script or a file inside the pack's folder) and only at or above the version that fixed the vendor's known path
traversal and link problems (FLOORS). It runs with an argument list (no shell), stdin closed, no console window,
the program's own folder as working directory, a reduced environment, a timeout and a capped output.

The listing only builds archive.py's plan. Extraction asks for the exact archive paths of that plan, into a
private work folder inside the staging folder; a non-zero exit, a timeout or a limit discards that folder. Then
every file is checked (a regular file with one link, inside the work folder, no link or reparse point, a name the
policy accepts, exactly the planned names) and moved flat into staging. archive.py registers these backends
through install(); this file never imports archive.py, so it loads on its own.
"""

import dataclasses
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata

_archive = None  # archive.py, given by install()

UNRAR = "unrar"
SEVENZIP = "7z"
BSDTAR = "bsdtar"
LABELS = {UNRAR: "UnRAR", SEVENZIP: "7-Zip", BSDTAR: "bsdtar"}

# The first version without the vendor's known path traversal or code execution problems on extraction. Checked
# against the vendors' pages on 2026-11-20.
FLOORS = {
    # WinRAR WhatsNew.txt, version 7.23: a symbolic link pointing outside the destination could be created by
    # UnRAR on every platform, and a heap overflow in RAR 5 recovery volumes; 7.13: Windows path traversal. The link
    # chain and recursion fixes of 7.30 are in betas only so far.
    UNRAR: (7, 23),
    # 7-zip.org history.txt, 26.02: CVE-2026-14266, heap overflow in XZ decompression (code execution); 26.01: heap
    # overflows and out-of-bounds reads in other handlers; 25.01: CVE-2025-55188, symbolic links on extraction;
    # 25.00: CVE-2025-11001/11002. 26.03 to 26.06 name no fix of extraction paths or code execution.
    SEVENZIP: (26, 2),
    # libarchive releases: 3.8.8 adds a missing bound check to the RAR reader and fixes a heap overflow of the 7-Zip
    # reader; 3.8.3 a buffer overrun on truncated 7-Zip headers; 3.8.0 CVE-2025-5915 (RAR heap buffer overflow) and
    # CVE-2025-5914 (RAR double free); 3.7.4 CVE-2024-26256 (RAR e8 filter). No libarchive advisory concerns path
    # traversal; bsdtar refuses "..", absolute paths and links by default.
    BSDTAR: (3, 8, 8),
}
# A bsdtar of the operating system on Linux and macOS is used whatever number it prints: distributions and
# Apple backport fixes without changing it (Ubuntu 24.04 prints 3.7.2), so the number says nothing.
_SYSTEM_DIRS = ("/usr/bin", "/bin")
_POSIX_DIRS = ("/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin", "/snap/bin")
_POSIX_NAMES = {UNRAR: ("unrar",), SEVENZIP: ("7zz", "7z", "7za"), BSDTAR: ("bsdtar", "tar")}

_RAR4_MAGIC = b"Rar!\x1a\x07\x00"
_RAR5_MAGIC = b"Rar!\x1a\x07\x01\x00"
_7Z_MAGIC = b"7z\xbc\xaf\x27\x1c"

# Order of the programs per archive kind: libarchive is the weakest reader of RAR, and RAR 4 could not be tested
# with it (RAR 7 no longer writes RAR 4), so RAR 4 is UnRAR / 7-Zip only.
_ORDER = {"rar": (UNRAR, SEVENZIP, BSDTAR), "rar4": (UNRAR, SEVENZIP), "7z": (SEVENZIP, BSDTAR)}

# Characters that turn an exact name into a pattern and cannot be escaped for that program (7-Zip runs with
# -spd: no wildcards; bsdtar takes \[ \* \? but a literal backslash would be read as an escape).
_PATTERN_CHARS = {UNRAR: "*?", SEVENZIP: "", BSDTAR: "\\"}
_BSDTAR_ESCAPE = re.compile(r"([\[\]*?])")
# 7-Zip asks for a password on an encrypted archive unless one is given.
_DUMMY_PASSWORD = "maxdrop-no-password"

PROBE_SECONDS = 15.0
LIST_SECONDS = 120.0
LIST_OUTPUT_CAP = 64 << 20
MESSAGE_OUTPUT_CAP = 64 << 10
_WATCH_EVERY = 0.5
_POLL = 0.05
_MESSAGE_CHARS = 300
# A copy of archive._BY_HAND_TAIL: archive.py is still loading when it imports this module.
_BY_YOURSELF = "Extract the archive by hand and import the .max from that folder."
WORK_PREFIX = ".maxdrop-work-"

_WINDOWS = os.name == "nt"
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def install(archive):
    """Register the .rar and .7z backends in archive.py (the module object)."""
    global _archive
    _archive = archive
    archive._BACKENDS[archive.KIND_RAR] = ExternalBackend(archive.KIND_RAR)
    archive._BACKENDS[archive.KIND_7Z] = ExternalBackend(archive.KIND_7Z)


def _error(message):
    return _archive.PackError(message)


_VERSION_RE = {
    UNRAR: re.compile(r"^\s*UNRAR (\d+)\.(\d+)", re.M),
    SEVENZIP: re.compile(r"^\s*7-Zip(?: \[\d+\]| \([a-z]+\))? (\d+)\.(\d+)", re.M),
    BSDTAR: re.compile(r"^bsdtar \S+ - libarchive (\d+)\.(\d+)\.(\d+)", re.M),
}


def parse_version(flavor, text):
    """The version tuple a program prints in its banner, None when the text is not that program's."""
    m = _VERSION_RE[flavor].search(text)
    return tuple(int(g) for g in m.groups()) if m else None


def version_text(version, flavor):
    """As the vendor writes it: UnRAR 7.01 and 7-Zip 25.01 have two-digit minors."""
    if flavor in (UNRAR, SEVENZIP) and len(version) == 2:
        return "%d.%02d" % version
    return ".".join(str(n) for n in version)


@dataclasses.dataclass(frozen=True)
class Tool:
    flavor: str
    path: str
    version: tuple
    system: bool = False            # a bsdtar of the operating system: no floor

    @property
    def label(self):
        return "%s %s" % (LABELS[self.flavor], version_text(self.version, self.flavor))

    @property
    def too_old(self):
        return not self.system and self.version < FLOORS[self.flavor]


_EXE_MAGIC_POSIX = (b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
                    b"\xca\xfe\xba\xbe")


_LONG_PREFIX = "\\\\?\\"


def _long(path):
    """On Windows, the extended form of an absolute path: the programs write deeper than 260 characters, and
    Python sees such files only through it unless long paths are enabled system-wide."""
    if not _WINDOWS or path.startswith(_LONG_PREFIX):
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\"):
        return _LONG_PREFIX + "UNC\\" + path[2:]
    return _LONG_PREFIX + path


def _plain(path):
    if path.startswith(_LONG_PREFIX + "UNC\\"):
        return "\\\\" + path[len(_LONG_PREFIX) + 4:]
    return path[len(_LONG_PREFIX):] if path.startswith(_LONG_PREFIX) else path


def _inside(path, folder):
    path, folder = os.path.normcase(_plain(path)), os.path.normcase(_plain(folder))
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:  # another drive
        return False


def real_executable(path, pack_dir=None):
    """True for a native program at an absolute path: never a script, a .bat / .cmd, or a file lying in the
    pack's own folder."""
    if not path or not os.path.isabs(path):
        return False
    try:
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode):
            return False
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError:
        return False
    if _WINDOWS:
        if os.path.splitext(path)[1].lower() != ".exe" or head[:2] != b"MZ":
            return False
    elif head not in _EXE_MAGIC_POSIX or not os.access(path, os.X_OK):
        return False
    # The pack's own folder, not every folder below it: a pack at a drive root still finds Program Files.
    if pack_dir and (os.path.normcase(os.path.dirname(os.path.realpath(path)))
                     == os.path.normcase(os.path.realpath(pack_dir))):
        return False
    return True


def _system32():
    if _WINDOWS:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(520)
            n = ctypes.windll.kernel32.GetSystemDirectoryW(buf, len(buf))
            if 0 < n < len(buf):
                return buf.value
        except (OSError, AttributeError):
            pass
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")


def _registry_folders(flavor):
    """Install folders the WinRAR and 7-Zip installers record in HKEY_LOCAL_MACHINE."""
    try:
        import winreg
    except ImportError:
        return []
    keys = {UNRAR: [(r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WinRAR.exe", "Path")],
            SEVENZIP: [(r"SOFTWARE\7-Zip", "Path64"), (r"SOFTWARE\7-Zip", "Path")]}.get(flavor, [])
    folders = []
    for sub, value in keys:
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub, 0, winreg.KEY_READ | view) as key:
                    data, kind = winreg.QueryValueEx(key, value)
            except OSError:
                continue
            if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(data, str):
                data = os.path.expandvars(data) if kind == winreg.REG_EXPAND_SZ else data
                if os.path.isabs(data) and data not in folders:
                    folders.append(data)
    return folders


def candidates(flavor, platform=None):
    """Absolute paths where the program may be, in the order they are tried."""
    platform = platform or sys.platform
    if platform == "win32":
        if flavor == BSDTAR:
            return [os.path.join(_system32(), "tar.exe")]
        exe, sub = {UNRAR: ("UnRAR.exe", "WinRAR"), SEVENZIP: ("7z.exe", "7-Zip")}[flavor]
        roots = []
        for var in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(var)
            if root and os.path.isabs(root) and root not in roots:
                roots.append(root)
        paths = [os.path.join(r, sub, exe) for r in roots] + [os.path.join(f, exe) for f in _registry_folders(flavor)]
        return list(dict.fromkeys(paths))
    return ["%s/%s" % (d, n) for n in _POSIX_NAMES[flavor] for d in _POSIX_DIRS]


def _version_args(flavor, path):
    return [path, "--version"] if flavor == BSDTAR else [path]


_PROBED = {}


def probe(flavor, path, pack_dir=None):
    """The Tool at path (its version read from its banner), None when it is not that program or cannot run."""
    if not real_executable(path, pack_dir):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (flavor, path, st.st_size, st.st_mtime_ns)
    if key not in _PROBED:
        try:
            _code, out, err = run(_version_args(flavor, path), PROBE_SECONDS, MESSAGE_OUTPUT_CAP)
            text = out + "\n" + err
        except ToolFailed:
            text = ""
        version = parse_version(flavor, text)
        system = (flavor == BSDTAR and sys.platform != "win32" and os.path.dirname(path) in _SYSTEM_DIRS)
        _PROBED[key] = Tool(flavor, path, version, system) if version else None
    return _PROBED[key]


def find_tools(order, pack_dir=None):
    """(usable tools in order, tools refused for their version). One per program: the first candidate found."""
    usable, old = [], []
    for flavor in order:
        seen = set()
        for path in candidates(flavor):
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            tool = probe(flavor, path, pack_dir)
            if tool is None:
                continue
            if tool.too_old:
                old.append(tool)
                continue
            usable.append(tool)
            break
    return usable, old


class ToolFailed(Exception):
    """A program ended without doing its job; the next program may do better."""

    def __init__(self, tool_label, detail, output=""):
        super().__init__("%s: %s" % (tool_label, detail))
        self.tool_label = tool_label
        self.detail = detail
        self.output = output


def _environment():
    if _WINDOWS:
        env = {k: os.environ[k] for k in ("SystemRoot", "SystemDrive", "WINDIR", "TEMP", "TMP") if k in os.environ}
        env["PATH"] = _system32()
        return env
    return {"PATH": "/usr/bin:/bin", "LC_ALL": "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8"}


def _windows_job(proc):
    """A job object that ends the process and every child it starts when closed or terminated."""
    try:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", ctypes.c_ulonglong * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = Extended()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
                and k32.AssignProcessToJobObject(job, int(proc._handle))):
            return (k32, job)
        k32.CloseHandle(job)
    except (OSError, AttributeError, ValueError):
        pass
    return None


def _kill(proc, job):
    if job is not None:
        job[0].TerminateJobObject(job[1], 1)
    elif not _WINDOWS:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _output_encoding(flavor):
    if flavor == BSDTAR and _WINDOWS:
        try:
            import ctypes
            return "cp%d" % ctypes.windll.kernel32.GetACP()
        except (OSError, AttributeError):
            return "mbcs"
    return "utf-8"


def run(args, timeout, cap, watch=None, overflow_fatal=False, encoding="utf-8", label=None):
    """Run a program; (exit code, stdout, stderr), each at most cap bytes, decoded with surrogateescape. stderr is
    kept apart so that a warning never reads as a listed name. watch() is called while it runs and may raise to
    stop it. On a timeout, or more output than cap when overflow_fatal, the program and its children are ended
    and ToolFailed is raised."""
    label = label or os.path.basename(args[0])
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                  cwd=os.path.dirname(args[0]), env=_environment(), close_fds=True)
    if _WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(args, **kwargs)
    except (OSError, ValueError) as e:
        raise ToolFailed(label, "could not be started (%s)" % e) from None
    # A child started before the assignment would escape the job; these programs start none.
    job = _windows_job(proc) if _WINDOWS else None
    bufs = (bytearray(), bytearray())
    overflow = threading.Event()

    def reader(stream, buf):
        while True:
            chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
            if not chunk:
                return
            room = cap - len(buf)
            if room > 0:
                buf.extend(chunk[:room])
            if len(chunk) > room:
                overflow.set()

    threads = [threading.Thread(target=reader, args=(s, b), daemon=True) for s, b in zip((proc.stdout, proc.stderr), bufs)]
    for t in threads:
        t.start()
    deadline = time.monotonic() + max(timeout, 0.0)
    next_watch = 0.0
    reason = None
    try:
        while proc.poll() is None:
            now = time.monotonic()
            if now > deadline:
                reason = "did not finish within %d seconds" % timeout
                break
            if overflow_fatal and overflow.is_set():
                reason = "wrote more output than %d bytes" % cap
                break
            if watch is not None and now >= next_watch:
                watch()
                next_watch = now + _WATCH_EVERY
            try:
                proc.wait(_POLL)
            except subprocess.TimeoutExpired:
                pass
        if reason is not None:
            _kill(proc, job)
    except BaseException:
        _kill(proc, job)
        raise
    finally:
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            pass
        for t, stream in zip(threads, (proc.stdout, proc.stderr)):
            t.join(5)
            if not t.is_alive():
                stream.close()
        if job is not None:
            job[0].CloseHandle(job[1])
    out, err = (bytes(b).decode(encoding, "surrogateescape").lstrip("\ufeff") for b in bufs)
    if reason is None and overflow_fatal and overflow.is_set():
        reason = "wrote more output than %d bytes" % cap
    if reason is not None:
        raise ToolFailed(label, reason, _joined(out, err))
    return proc.returncode, out, err


def _joined(out, err):
    return "\n".join(t for t in (err, out) if t.strip())


def list_args(tool, archive):
    """The listing command(s) of a program: a list of argument lists."""
    p = tool.path
    if tool.flavor == UNRAR:
        return [[p, "lt", "-c-", "-cfg-", "-p-", "-scfr", "--", archive]]
    if tool.flavor == SEVENZIP:
        return [[p, "l", "-slt", "-sccUTF-8", "-bd", "-p" + _DUMMY_PASSWORD, "--", archive]]
    return [[p, "-tf", archive], [p, "-tvf", archive]]


def _lines(text):
    return [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]


def _int(value):
    value = value.strip()
    return int(value) if value.isdigit() else None


def parse_unrar(text):
    """(entries as dicts, multi-volume) from UnRAR lt: blocks of "Name: / Type: / Size: / Flags:" lines."""
    entries, current, volume = [], None, False
    for line in _lines(text):
        key, sep, value = line.lstrip(" ").partition(": ")
        if not sep:
            continue
        if key == "Details" and current is None:
            volume = any(v.strip() == "volume" for v in value.split(","))
        elif key == "Name":
            current = {"name": value, "type": "", "size": None, "flags": ""}
            entries.append(current)
        elif current is not None and key == "Type":
            current["type"] = value.strip()
        elif current is not None and key == "Size":
            current["size"] = _int(value)
        elif current is not None and key == "Flags":
            current["flags"] = value
    out = []
    for e in entries:
        kind = e["type"].casefold()
        out.append(dict(name=e["name"], size=e["size"], is_dir=kind == "directory", regular=kind == "file",
                        encrypted="encrypted" in e["flags"]))
    return out, volume


def parse_7z(text):
    """(entries as dicts, multi-volume) from 7z l -slt: the archive's block, "----------", then a block per
    entry."""
    header, blocks, current, in_entries = {}, [], None, False
    for line in _lines(text):
        if line == "----------":
            in_entries = True
            current = None
            continue
        key, sep, value = line.partition(" = ")
        if not sep:
            if not line:
                current = None
            continue
        if not in_entries:
            header.setdefault(key, value)
            continue
        if key == "Path":
            current = {}
            blocks.append(current)
        if current is not None:
            current[key] = value
    out = []
    for b in blocks:
        attrs = b.get("Attributes", "").split()
        mode = next((a for a in attrs if len(a) == 10 and a[0] in "-dlcbps"), "")
        is_dir = b.get("Folder") == "+" or (bool(attrs) and "D" in attrs[0] and not mode) or mode[:1] == "d"
        regular = (not is_dir and not b.get("Symbolic Link") and not b.get("Hard Link")
                   and b.get("Alternate Stream") != "+" and mode[:1] in ("", "-"))
        out.append(dict(name=b.get("Path", ""), size=_int(b.get("Size", "")), is_dir=is_dir, regular=regular,
                        encrypted=b.get("Encrypted") == "+"))
    return out, header.get("Multivolume") == "+"


def parse_tar(names_text, verbose_text):
    """Entries as dicts from bsdtar -tf (the names) and -tvf (type and size), line by line; None when the two
    listings do not line up."""
    names = _lines(names_text)
    verbose = _lines(verbose_text)
    while names and names[-1] == "":
        names.pop()
    while verbose and verbose[-1] == "":
        verbose.pop()
    if len(names) != len(verbose):
        return None
    out = []
    for name, line in zip(names, verbose):
        fields = line.split()
        mode = fields[0] if fields else ""
        is_dir = mode.startswith("d") or name.endswith("/")
        # A link's line ends in "-> target" or "link to target", not in its name.
        regular = mode.startswith("-") and line.endswith(" " + name) and not is_dir
        size = _int(fields[4]) if len(fields) > 4 else None
        out.append(dict(name=name, size=size, is_dir=is_dir, regular=regular, encrypted=False))
    return out


def _unaskable(flavor, name):
    """Why the program cannot be asked for this exact name, "" when it can."""
    if any(c in name for c in "\n\r\0"):
        return "has a line break in its name"
    chars = [c for c in _PATTERN_CHARS[flavor] if c in name]
    if chars:
        return "has %s in its name, which %s reads as a pattern" % (" ".join(chars), LABELS[flavor])
    if flavor == BSDTAR and name.startswith("-"):
        return "starts with -, which %s reads as an option" % LABELS[flavor]
    return ""


def list_entries(tool, archive):
    """The archive's entries (archive.Entry, key = (tool, name as the program spells it)); ToolFailed when the
    program cannot list it, PackError for a multi-volume archive."""
    encoding = _output_encoding(tool.flavor)
    texts = []
    for args in list_args(tool, archive):
        code, out, err = run(args, LIST_SECONDS, LIST_OUTPUT_CAP, overflow_fatal=True, encoding=encoding,
                             label=tool.label)
        if code != 0:
            raise ToolFailed(tool.label, "exit code %d" % code, _joined(out, err))
        texts.append(out)
    volume = False
    if tool.flavor == UNRAR:
        raw, volume = parse_unrar(texts[0])
    elif tool.flavor == SEVENZIP:
        raw, volume = parse_7z(texts[0])
    else:
        raw = parse_tar(texts[0], texts[1])
        if raw is None:
            raise ToolFailed(tool.label, "its two listings do not match")
    if volume:
        raise _error(_volume_message(archive))
    entries = []
    for r in raw:
        entries.append(_archive.Entry(
            name=r["name"], size=r["size"], is_dir=r["is_dir"], regular=r["regular"], encrypted=r["encrypted"],
            unsupported="" if r["is_dir"] else _unaskable(tool.flavor, r["name"]), key=(tool, r["name"])))
    return entries


def _vint(data, pos):
    value = shift = 0
    while pos < len(data) and shift < 64:
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, pos
        shift += 7
    raise ValueError("truncated")


def header_problem(head, file_size):
    """"volume", "encrypted" (file names encrypted) or "split" from the first bytes of an archive, else None."""
    try:
        if head.startswith(_RAR5_MAGIC):
            pos = len(_RAR5_MAGIC) + 4  # header CRC
            _size, pos = _vint(head, pos)
            htype, pos = _vint(head, pos)
            hflags, pos = _vint(head, pos)
            if htype == 4:
                return "encrypted"
            if htype != 1:
                return None
            if hflags & 0x1:
                _extra, pos = _vint(head, pos)
            if hflags & 0x2:
                _data, pos = _vint(head, pos)
            aflags, pos = _vint(head, pos)
            return "volume" if aflags & 0x1 else None
        if head.startswith(_RAR4_MAGIC):
            base = len(_RAR4_MAGIC)
            if len(head) < base + 5 or head[base + 2] != 0x73:
                return None
            flags = head[base + 3] | head[base + 4] << 8
            if flags & 0x0001:
                return "volume"
            if flags & 0x0080:
                return "encrypted"
            return None
        if head.startswith(_7Z_MAGIC) and len(head) >= 32:
            offset = int.from_bytes(head[12:20], "little")
            size = int.from_bytes(head[20:28], "little")
            if 32 + offset + size > file_size:
                return "split"
    except ValueError:
        return None
    return None


def _volume_message(archive):
    return ("%s is one part of an archive split into several (.part1.rar, .r00, .7z.001). MaxDrop does not join "
            "parts. %s" % (os.path.basename(archive), _BY_YOURSELF))


def _precheck(archive):
    """PackError for what no program will do here; the RAR kind ("rar4" or "rar") otherwise."""
    try:
        with open(archive, "rb") as f:
            head = f.read(64)
        size = os.path.getsize(archive)
    except OSError as e:
        raise _error("%s could not be read (%s)." % (os.path.basename(archive), e)) from None
    problem = header_problem(head, size)
    if problem == "volume":
        raise _error(_volume_message(archive))
    if problem == "encrypted":
        raise _error(_archive.password_message(archive))
    if problem == "split":
        raise _error("%s is incomplete or one part of an archive split into several (.7z.001). %s"
                     % (os.path.basename(archive), _BY_YOURSELF))
    return "rar4" if head.startswith(_RAR4_MAGIC) else None


def extract_args(tool, archive, list_file, out):
    """The extraction command: the names come from list_file (one per line, NUL-separated for bsdtar)."""
    p = tool.path
    if tool.flavor == UNRAR:
        # e: no paths; -o-: never overwrite (the first of two equal names stays); -ol-: skip links;
        # -ai: no file attributes (a read-only file would survive the clean-up).
        return [p, "e", "-c-", "-cfg-", "-p-", "-y", "-o-", "-ol-", "-ai", "-idq", "-scfl", "-scfr", "--", archive,
                "@" + list_file, out + os.sep]
    if tool.flavor == SEVENZIP:
        # -spd: names are not wildcards; -r-: no recursion; -aos: never overwrite; -sns-: no NTFS streams, which
        # the file check cannot see. Never -snld: it lifts 7-Zip's link checks.
        return [p, "e", "-y", "-aos", "-bd", "-bso0", "-bsp0", "-sccUTF-8", "-scsUTF-8", "-spd", "-r-", "-sns-",
                "-p" + _DUMMY_PASSWORD, "-o" + out, "-i@" + list_file, "--", archive]
    # bsdtar has no flat mode: paths are kept under out and flattened afterwards. -k: never overwrite.
    return [p, "-x", "-k", "-o", "--no-same-permissions", "--no-acls", "--no-xattrs", "--no-fflags", "-f", archive,
            "-C", out, "--null", "-T", list_file]


def list_file_bytes(tool, names):
    if tool.flavor == BSDTAR:
        encoding = _output_encoding(BSDTAR)
        return b"".join(_BSDTAR_ESCAPE.sub(r"\\\1", n).encode(encoding, "surrogateescape") + b"\0" for n in names)
    return "".join(n + "\n" for n in names).encode("utf-8", "surrogateescape")


def _short(output):
    lines = [line.strip() for line in _lines(output) if line.strip()]
    text = " | ".join(lines[-4:])
    return text if len(text) <= _MESSAGE_CHARS else "..." + text[-_MESSAGE_CHARS:]


def _remove_tree(path):
    def retry(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def drop_streams(path):
    """Remove the NTFS alternate data streams of a file (UnRAR restores them and has no switch against it): the
    file check sees only the main stream. No-op off Windows or on a volume without streams."""
    if not _WINDOWS:
        return
    import ctypes
    from ctypes import wintypes

    class FindStreamData(ctypes.Structure):
        _fields_ = [("StreamSize", ctypes.c_int64), ("cStreamName", ctypes.c_wchar * 296)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.FindFirstStreamW.restype = wintypes.HANDLE
    k32.FindFirstStreamW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.FindNextStreamW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k32.FindClose.argtypes = [wintypes.HANDLE]
    data = FindStreamData()
    handle = k32.FindFirstStreamW(path, 0, ctypes.byref(data), 0)
    if handle in (None, wintypes.HANDLE(-1).value):
        return
    names = []
    try:
        while True:
            if data.cStreamName != "::$DATA":
                names.append(data.cStreamName)
            if not k32.FindNextStreamW(handle, ctypes.byref(data)):
                break
    finally:
        k32.FindClose(handle)
    for name in names:  # ":name:$DATA"
        os.remove(path + name[:-len(":$DATA")] if name.endswith(":$DATA") else path + name)


def _is_link(item, st):
    if item.is_symlink() or stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def collect(out, flat, label, limit):
    """{name_key: (path, size)} of the files a program wrote under out. PackError for anything but plain files
    inside out (a link, a reparse point, a hard link, a name the policy refuses, two files named alike) and for
    a folder when flat."""
    unsafe = "%s wrote something MaxDrop does not accept (%s). %s"
    real_out = os.path.realpath(out)
    found, stack, seen = {}, [out], 0
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as it:
            items = list(it)
        for item in items:
            seen += 1
            if seen > limit:
                raise _error(unsafe % (label, "too many files", _BY_YOURSELF))
            st = os.lstat(item.path)
            if _is_link(item, st):
                raise _error(unsafe % (label, "a link: %s" % item.name, _BY_YOURSELF))
            if stat.S_ISDIR(st.st_mode):
                if flat:
                    raise _error(unsafe % (label, "a folder: %s" % item.name, _BY_YOURSELF))
                stack.append(item.path)
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise _error(unsafe % (label, "not a plain file: %s" % item.name, _BY_YOURSELF))
            if not _inside(os.path.realpath(item.path), real_out):
                raise _error(unsafe % (label, "a file outside its folder", _BY_YOURSELF))
            if _archive.refused_reason(item.name) is not None:
                raise _error(unsafe % (label, "the name %r" % item.name, _BY_YOURSELF))
            key = _archive.name_key(item.name)
            if key in found:
                raise _error(unsafe % (label, "two files named %s" % item.name, _BY_YOURSELF))
            found[key] = (item.path, st.st_size)
    return found


def _watcher(out, budget):
    limits = budget.limits
    size_text = _archive._size_text

    def watch():
        # From what earlier extract() calls of the same unpack wrote: the scene goes first, its maps after it.
        files, total = budget.files, budget.total
        for root, _dirs, names in os.walk(out):
            for n in names:
                files += 1
                try:
                    size = os.lstat(os.path.join(root, n)).st_size
                except OSError:
                    continue
                if size > limits.file_bytes:
                    raise _error("%s is larger than %s, the most MaxDrop unpacks for one file. Extract the archive "
                                 "by hand." % (n, size_text(limits.file_bytes)))
                total += size
        if files > limits.files:
            raise _error("The pack holds more files to unpack than the %d MaxDrop writes from one pack. Extract "
                         "it by hand." % limits.files)
        if total > limits.total_bytes:
            raise _error("The pack unpacks to more than %s, the most MaxDrop writes from one pack. Extract it by "
                         "hand." % size_text(limits.total_bytes))
        budget.check_time(total)
    return watch


def _normal(name):
    return unicodedata.normalize("NFC", name.replace("\\", "/"))


class ExternalBackend:
    """The archive.py backend of one archive kind ("rar" or "7z"), through the first usable program."""

    def __init__(self, kind, tools=None):
        self.kind = kind
        self._fixed = tools                 # tests: these tools instead of the discovery
        # Never reassigned: one backend serves every pack of its kind, so the program used for a pack is not kept.
        self.name = " / ".join(LABELS[f] for f in _ORDER[kind])

    def _tools(self, archive, order_kind):
        if self._fixed is not None:
            return [t for t in self._fixed if t.flavor in _ORDER[order_kind]], []
        return find_tools(_ORDER[order_kind], os.path.dirname(os.path.abspath(archive)))

    def _usable(self, archive):
        order_kind = _precheck(archive) or self.kind
        tools, old = self._tools(archive, order_kind)
        if tools:
            return tools
        raise _error(self._none_message(archive, order_kind, old))

    def _none_message(self, archive, order_kind, old):
        base = os.path.basename(archive)
        if old:
            told = " ".join("%s (%s) is older than %s, the first version without known path traversal problems: "
                            "update it." % (t.label, t.path, version_text(FLOORS[t.flavor], t.flavor)) for t in old)
            return "%s cannot be unpacked safely here. %s Or extract the archive by hand and import the .max " \
                "from that folder." % (base, told)
        if sys.platform == "win32":
            what = "7-Zip (7-zip.org)" if order_kind == "7z" else "WinRAR (rarlab.com) or 7-Zip (7-zip.org)"
        elif sys.platform == "darwin":
            what = "7-Zip (7zz) or unrar, for example with Homebrew"
        elif order_kind == "rar4":
            what = "7-Zip (7zz) or unrar (bsdtar does not read RAR 4)"
        else:
            what = "bsdtar (package libarchive-tools or libarchive), 7-Zip (7zz) or unrar"
        kind = "RAR 4" if order_kind == "rar4" else "." + self.kind
        return ("No program to unpack %s archives was found for %s. Install %s in its standard folder, or extract "
                "the archive by hand and import the .max from that folder." % (kind, base, what))

    def _failure(self, archive, failures):
        if any(_mentions_password(f.output) for f in failures):
            return _archive.password_message(archive)
        detail = "; ".join("%s: %s%s" % (f.tool_label, f.detail, (" (%s)" % _short(f.output)) if f.output else "")
                           for f in failures)
        return "%s could not be unpacked (%s). %s" % (os.path.basename(archive), detail, _BY_YOURSELF)

    def names(self, path):
        failures = []
        for tool in self._usable(path):
            try:
                entries = list_entries(tool, path)
            except ToolFailed as e:
                failures.append(e)
                continue
            return entries
        raise _error(self._failure(path, failures))

    def listed_by(self, entries):
        """The label of the program that listed these entries (each key holds its tool)."""
        return entries[0].key[0].label if entries else self.name

    def _names_for(self, tool, path, wanted):
        """The names to ask this tool for, one per planned entry; None when it cannot be asked for all of them."""
        if all(e.key[0] == tool for e, _t in wanted):
            return [e.key[1] for e, _t in wanted]
        listed = {}
        for e in list_entries(tool, path):
            if not e.is_dir and e.regular and not e.unsupported:
                listed.setdefault(_normal(e.name), e.key[1])
        names = [listed.get(_normal(e.name)) for e, _t in wanted]
        return None if None in names else names

    def extract(self, path, wanted, staging, budget):
        """Returns the label of the program that wrote the files: the next one is tried when one fails."""
        first = wanted[0][0].key[0]
        tools = [first] + [t for t in self._usable(path) if t != first]
        failures = []
        for tool in tools:
            try:
                names = self._names_for(tool, path, wanted)
            except ToolFailed as e:
                failures.append(e)
                continue
            if names is None:
                failures.append(ToolFailed(tool.label, "cannot ask for every file of the scene by its name"))
                continue
            work = tempfile.mkdtemp(prefix=WORK_PREFIX, dir=staging)
            try:
                self._extract_with(tool, path, wanted, names, work, staging, budget)
                return tool.label
            except ToolFailed as e:
                failures.append(e)
            finally:
                _remove_tree(_long(work))
        raise _error(self._failure(path, failures))

    def _extract_with(self, tool, path, wanted, names, work, staging, budget):
        list_file = os.path.join(work, "names.lst")
        out = os.path.join(work, "out")
        os.mkdir(out)
        with open(list_file, "xb") as f:
            f.write(list_file_bytes(tool, names))
        remaining = budget.deadline - time.monotonic()
        if remaining <= 0:
            budget.check_time()
        try:
            code, out_text, err_text = run(extract_args(tool, path, list_file, out), remaining, MESSAGE_OUTPUT_CAP,
                                           watch=_watcher(_long(out), budget), encoding=_output_encoding(tool.flavor),
                                           label=tool.label)
        except ToolFailed:
            budget.check_time()     # a timeout of the pack's own budget ends everything
            raise
        text = _joined(out_text, err_text)
        if code != 0:
            raise ToolFailed(tool.label, "exit code %d" % code, text)
        found = collect(_long(out), tool.flavor != BSDTAR, tool.label, budget.limits.files + len(wanted) + 64)
        targets = {_archive.name_key(t): t for _e, t in wanted}
        extra = sorted(set(found) - set(targets))
        if extra:
            raise _error("%s wrote other files than asked for (%s). %s" % (tool.label, extra[0], _BY_YOURSELF))
        missing = [targets[k] for k in targets if k not in found]
        if missing:
            raise ToolFailed(tool.label, "did not write %s" % missing[0], text)
        for key, target in targets.items():
            src, size = found[key]
            budget.start_file(target)
            budget.add(size)
            os.chmod(src, 0o644)
            drop_streams(src)
            os.rename(src, os.path.join(_long(staging), target))


def _mentions_password(output):
    low = output.casefold()
    return any(w in low for w in ("password", "encrypted", "encryption"))
