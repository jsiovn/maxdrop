# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Check a built extension zip before it is published: it must carry the license text.

    python tools/check_zip.py dist/maxdrop-1.0.0.zip

The GPL asks that whoever receives the add-on receives the license with it. Blender packs the whole package
folder, so maxdrop/LICENSE (the root LICENSE again, kept identical by tests/test_license.py) is in every
zip; this fails the build if one ever comes out without it. Standard library only.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "LICENSE"


def problem(zip_path, license_path=ROOT / NAME):
    """None when zip_path carries the text of license_path at its top level, else what is wrong."""
    want = Path(license_path).read_bytes()
    with zipfile.ZipFile(zip_path) as archive:
        if NAME not in archive.namelist():
            return "no %s in %s" % (NAME, zip_path)
        if archive.read(NAME) != want:
            return "%s in %s is not the text of %s" % (NAME, zip_path, license_path)
    return None


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    why = problem(argv[1])
    if why:
        print("check_zip: " + why, file=sys.stderr)
        return 1
    print("check_zip: %s carries %s" % (argv[1], NAME))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
