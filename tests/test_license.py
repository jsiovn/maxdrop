# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The license: the unmodified GPL v3 text at the root, the same text inside the package (so in every zip Blender
builds), the manifest naming it, and tools/check_zip.py telling a zip that carries it from one that does not.

    python -I -m unittest discover tests
"""
import contextlib
import hashlib
import importlib.util
import io
import os
import re
import shutil
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "maxdrop")

_spec = importlib.util.spec_from_file_location("check_zip", os.path.join(ROOT, "tools", "check_zip.py"))
check_zip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_zip)

# gpl-3.0.txt as the Free Software Foundation publishes it (the COPYING of the GNU packages).
GPL3_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"


def read(path):
    with open(path, "rb") as f:
        return f.read()


def run_main(path):
    """The exit code of `check_zip.py <path>`, its messages kept off the test output."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return check_zip.main(["check_zip.py", path])


class LicenseText(unittest.TestCase):
    def test_the_root_file_is_the_unmodified_gpl3_text(self):
        self.assertEqual(hashlib.sha256(read(os.path.join(ROOT, "LICENSE"))).hexdigest(), GPL3_SHA256)

    def test_the_package_carries_the_same_file(self):
        self.assertEqual(read(os.path.join(PACKAGE, "LICENSE")), read(os.path.join(ROOT, "LICENSE")))

    def test_the_manifest_names_it_and_packs_it(self):
        text = read(os.path.join(PACKAGE, "blender_manifest.toml")).decode("utf-8")
        named = re.search(r"^license\s*=\s*\[(.*?)\]", text, re.M | re.S).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', named), ["SPDX:GPL-3.0-or-later"])
        # Blender packs every file of the folder but the excluded ones; a `paths` list would pack only its own.
        excluded = re.search(r"^paths_exclude_pattern\s*=\s*\[(.*?)\]", text, re.M | re.S).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', excluded), ["__pycache__/"])
        self.assertIsNone(re.search(r"^paths\s*=", text, re.M))


class CheckZip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maxdrop-zip-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def zip_of(self, **members):
        path = os.path.join(self.tmp, "%d.zip" % len(os.listdir(self.tmp)))
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in members.items():
                archive.writestr(name.replace("__", "/"), data)
        return path

    def test_a_zip_with_the_license_passes(self):
        text = read(os.path.join(ROOT, "LICENSE"))
        self.assertIsNone(check_zip.problem(self.zip_of(LICENSE=text, blender_manifest="x")))
        self.assertEqual(run_main(self.zip_of(LICENSE=text)), 0)

    def test_a_zip_without_it_fails(self):
        path = self.zip_of(blender_manifest="x")
        self.assertIn("no LICENSE", check_zip.problem(path))
        self.assertEqual(run_main(path), 1)

    def test_only_the_top_level_counts(self):
        text = read(os.path.join(ROOT, "LICENSE"))
        self.assertIn("no LICENSE", check_zip.problem(self.zip_of(docs__LICENSE=text)))

    def test_another_text_fails(self):
        self.assertIn("is not the text", check_zip.problem(self.zip_of(LICENSE=b"All rights reserved.\n")))


if __name__ == "__main__":
    unittest.main()
