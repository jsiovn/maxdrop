# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How the strings of one .max file decode: UTF-16LE, or the 8-bit code page of a file 3ds Max 2012 or older saved.

    with CompoundFile(path) as cf:
        strings = of_file(cf)               # or of_file(cf, "cp949"): the user's choice for 8-bit strings
    strings.wide, strings.codec             # True, None for a file of 3ds Max 2013 or later
    strings.text(raw)                       # a string chunk's payload as text

3ds Max 2013 made its strings Unicode: since then a name chunk (node 0x0962, class 0x2042, material 0x4001, ...)
holds UTF-16LE without a terminator. Older versions wrote the same chunks as 8-bit text in the code page of the
machine that saved the file, ended by a NUL. What decides is the version that wrote the file (`3ds Max Version` of
the summary, 15 = 3ds Max 2013): from 15 on, UTF-16. The saved-as version does not: 3ds Max 2015 saving in the 2012
format still writes UTF-16 (corpus scene A), and so does the root container id (0x2014 = the 2012 format, written
by both). Below 15, or without a version, the DLL file names and class names of the directories vote: a name of
8-bit text ends with its only NUL; an ASCII name in UTF-16 has a zero in its second byte. A name that is neither
(a UTF-16 name in Chinese, a one-letter name) abstains. Below 15 the file is 8-bit unless the names say UTF-16;
without a version it is UTF-16 unless they say 8-bit.

An 8-bit string is cut at its first NUL and decoded with, by choice:
    "AUTO"      the code page the summary streams record (property 1), when it is one of CODE_PAGES; else each
                string as UTF-8 when it is valid UTF-8, else as cp1252
    a codec     one of CHOICES' codecs, errors replaced
A UTF-16 file ignores the choice. No bpy.
"""
from . import chunks, metadata

CHOICES = (  # (codec, label): the operator's "Text encoding" list after Auto
    ("cp1252", "Western (1252)"),
    ("cp1250", "Central European (1250)"),
    ("cp1251", "Cyrillic (1251)"),
    ("cp1253", "Greek (1253)"),
    ("cp1254", "Turkish (1254)"),
    ("cp932", "Japanese (932)"),
    ("cp936", "Simplified Chinese (936)"),
    ("cp949", "Korean (949)"),
    ("cp950", "Traditional Chinese (950)"),
    ("utf-8", "UTF-8"),
)
CODECS = frozenset(codec for codec, _label in CHOICES)
# The code pages a summary may record that name an 8-bit code page; 1200 (UTF-16) and 65001 (UTF-8, what every file
# of 3ds Max 2013 and later records) say nothing about an 8-bit name and leave Auto to its per-string rule.
CODE_PAGES = metadata.CODE_PAGES
WIDE_FROM = 15  # the major version of 3ds Max 2013, the first to write UTF-16
SNIFF_NAMES = 64  # names looked at per directory: enough to outvote a damaged one, bounded on a hostile file
MAX_NAME = 512  # bytes of one name looked at
_SUMMARIES = ("\x05DocumentSummaryInformation", "\x05SummaryInformation")


class Strings:
    """The strings of a file of 3ds Max 2012 or older (wide False): 8-bit, decoded with codec, or by the Auto rule
    when codec is None. Strings(True) decodes UTF-16LE as chunks.WIDE does."""
    __slots__ = ("wide", "codec")

    def __init__(self, wide, codec=None):
        if codec is not None and codec not in CODECS and codec not in CODE_PAGES.values():
            raise ValueError("unknown text encoding %r" % (codec,))
        self.wide, self.codec = bool(wide), codec

    def __repr__(self):
        return "Strings(%s)" % ("UTF-16" if self.wide else self.codec or "auto")

    def __eq__(self, other):
        return isinstance(other, Strings) and (self.wide, self.codec) == (other.wide, other.codec)

    def __hash__(self):
        return hash((self.wide, self.codec))

    def text(self, raw):
        """The text of a string's bytes (a bytes-like payload)."""
        if self.wide:
            return chunks.WIDE.text(raw)
        raw = bytes(raw).split(b"\0", 1)[0]
        if self.codec is not None:
            return raw.decode(self.codec, "replace")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1252", "replace")


UNICODE = Strings(True)


def looks_wide(names):
    """True when the names (bytes, at most MAX_NAME of each) look UTF-16LE, False when they look 8-bit, None when
    they do not say. An 8-bit name of two characters or more ends with its only NUL; an ASCII name in UTF-16 has a 0
    second byte and an even size; any other name abstains."""
    wide = narrow = 0
    for raw in names:
        if len(raw) < 3:
            continue  # b"x\0" is a one-letter 8-bit name and "x" in UTF-16 alike
        if raw[-1] == 0 and raw.count(0) == 1:
            narrow += 1
        elif raw[1] == 0 and not len(raw) & 1:
            wide += 1
    if wide == narrow:
        return None
    return wide > narrow


def _directory_names(cf):
    """The first SNIFF_NAMES DLL file names and class names of the file, as bytes; a name longer than MAX_NAME is
    left out (no ASCII DLL or class name is that long)."""
    from . import classdir
    out = []
    for stream, entry, name in (("DllDirectory", classdir.DLL_ENTRY, classdir.DLL_FILE),
                                ("ClassDirectory3", classdir.CLASS_ENTRY, classdir.CLASS_NAME),
                                ("ClassDirectory", classdir.CLASS_ENTRY, classdir.CLASS_NAME)):
        if not cf.exists(stream):
            continue
        taken = 0
        for chunk in chunks.iter_chunks(cf.open(stream)):
            if taken == SNIFF_NAMES:
                break
            if chunk.id != entry or not chunk.container:
                continue
            found = chunk.first(name)
            if found is not None and found.payload_size <= MAX_NAME:
                out.append(found.tobytes())
                taken += 1
        if stream == "ClassDirectory3" and taken:
            break  # ClassDirectory is the older name of the same stream
    return out


def code_page(cf):
    """The codec of the first code page of CODE_PAGES the file's summary records (DocumentSummaryInformation, then
    SummaryInformation), None when neither records one."""
    for name in _SUMMARIES:
        if not cf.exists(name):
            continue
        try:
            stream = cf.open(name, decompress=False)
            if stream.size > metadata.MAX_STREAM:
                continue
            page = metadata.code_page(stream.read())
        except ValueError:  # MetadataError, or a damaged stream (CfbError): this stream records none
            continue
        if page in CODE_PAGES:
            return CODE_PAGES[page]
    return None


def writer_version(cf):
    """The major version of the 3ds Max that wrote the file, None when its summary does not say."""
    try:
        version = metadata.read(cf).get("max_version")
    except ValueError:  # MetadataError or CfbError: the summary does not say
        return None
    return metadata.major(version)


def of_file(cf, choice="AUTO"):
    """The Strings of an open cfb.CompoundFile. choice: "AUTO" or one of CODECS, for 8-bit strings only."""
    if choice != "AUTO" and choice not in CODECS:
        raise ValueError("unknown text encoding %r" % (choice,))
    major = writer_version(cf)
    if major is not None and major >= WIDE_FROM:
        return UNICODE
    try:
        voted = looks_wide(_directory_names(cf))
    except ValueError:  # ChunkError or CfbError: the class directory's own reading reports the damage
        voted = None
    wide = voted is True if major is not None else voted is not False
    if wide:
        return UNICODE
    return Strings(False, code_page(cf) if choice == "AUTO" else choice)
