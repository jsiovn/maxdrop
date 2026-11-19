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
machine that saved the file, ended by a NUL. What decides is the file's own bytes: the DLL file names and class
names of the directories are plain ASCII on every file seen, so UTF-16 shows as a zero in the second byte of each,
8-bit text as a letter there. Only when they say nothing (no directory, no name of two bytes or more) does the
version that wrote the file decide (`3ds Max Version` of the summary, 15 = 3ds Max 2013). The saved-as version
does not: 3ds Max 2015 saving in the 2012 format still writes UTF-16 (corpus scene A), and so does the root
container id (0x2014 = the 2012 format, written by both).

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
    """True when ASCII names are UTF-16LE, False when they are 8-bit, None when they do not say. names: (first two
    bytes, byte count) of each. The second byte of an ASCII character in UTF-16 is 0 (and the count even); the
    second character of an 8-bit name is not 0."""
    wide = narrow = 0
    for head, size in names:
        if size < 2 or len(head) < 2:
            continue
        if head[1] == 0 and not size & 1:
            wide += 1
        elif head[1] != 0:
            narrow += 1
    if wide == narrow:
        return None
    return wide > narrow


def _directory_names(cf):
    """(first two bytes, byte count) of the first SNIFF_NAMES DLL file names and class names of the file."""
    from . import classdir
    out = []
    for stream, entry, name in (("DllDirectory", classdir._DLL_ENTRY, classdir._DLL_FILE),
                                ("ClassDirectory3", classdir._CLASS_ENTRY, classdir._CLASS_NAME),
                                ("ClassDirectory", classdir._CLASS_ENTRY, classdir._CLASS_NAME)):
        if not cf.exists(stream):
            continue
        taken = 0
        for chunk in chunks.iter_chunks(cf.open(stream)):
            if taken == SNIFF_NAMES:
                break
            if chunk.id != entry or not chunk.container:
                continue
            found = chunk.first(name)
            if found is not None:
                out.append((bytes(found.view()[:2]), found.payload_size))
                taken += 1
        if stream == "ClassDirectory3" and taken:
            break  # ClassDirectory is the older name of the same stream
    return out


def code_page(cf):
    """The codec of the code page the file's summary records (DocumentSummaryInformation, else
    SummaryInformation), None when it records none or one that is not in CODE_PAGES."""
    for name in _SUMMARIES:
        if not cf.exists(name):
            continue
        try:
            page = metadata.code_page(cf.open(name, decompress=False).read())
        except ValueError:  # MetadataError, or a damaged stream (CfbError): this stream records none
            continue
        if page is not None:
            return CODE_PAGES.get(page)
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
    try:
        wide = looks_wide(_directory_names(cf))
    except ValueError:  # ChunkError or CfbError: the class directory's own reading reports the damage
        wide = None
    if wide is None:
        major = writer_version(cf)
        wide = major is None or major >= WIDE_FROM
    if wide:
        return UNICODE
    return Strings(False, code_page(cf) if choice == "AUTO" else choice)
