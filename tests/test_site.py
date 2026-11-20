# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests of tools/make_site.py, the landing page generator, and of the page it fills: no Blender, no network.

    python -I -m unittest discover tests
"""
import importlib.util
import json
import os
import re
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location("make_site", os.path.join(ROOT, "tools", "make_site.py"))
make_site = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_site)

# As `blender --command extension server-generate` writes it.
PACKAGE = {
    "schema_version": "1.0.0", "id": "maxdrop", "name": "MaxDrop", "version": "1.2.3",
    "tagline": "Import 3ds Max .max scenes with materials, no 3ds Max needed", "type": "add-on",
    "blender_version_min": "4.2.0", "website": "https://jsiovn.github.io/maxdrop/",
    "archive_url": "./maxdrop-1.2.3.zip", "archive_size": 22740, "archive_hash": "sha256:00",
}


def manifest_value(key):
    with open(os.path.join(ROOT, "maxdrop", "blender_manifest.toml"), encoding="utf-8") as f:
        return re.search(r'^%s\s*=\s*"([^"]+)"' % key, f.read(), re.M).group(1)


class InstallLink(unittest.TestCase):
    def test_the_form_blender_reads_on_a_drop(self):
        self.assertEqual(make_site.install_href(PACKAGE),
                         "./maxdrop-1.2.3.zip?repository=.%2Findex.json&blender_version_min=4.2.0")

    def test_every_parameter_of_blenders_own_page(self):
        package = dict(PACKAGE, blender_version_max="6.0.0", platforms=["windows-x64", "linux-x64"],
                       python_versions=["3.11"])
        self.assertEqual(
            make_site.install_href(package),
            "./maxdrop-1.2.3.zip?repository=.%2Findex.json&blender_version_min=4.2.0"
            "&blender_version_max=6.0.0&platforms=windows-x64%2Clinux-x64&python_versions=3.11")

    def test_the_manifest_gives_the_link_of_this_release(self):
        # The oldest Blender the link lets in is the one the manifest claims and the test workflow runs.
        package = dict(PACKAGE, version=manifest_value("version"),
                       archive_url="./maxdrop-%s.zip" % manifest_value("version"),
                       blender_version_min=manifest_value("blender_version_min"))
        self.assertEqual(make_site.install_href(package),
                         "./maxdrop-%s.zip?repository=.%%2Findex.json&blender_version_min=4.2.0"
                         % manifest_value("version"))


class Values(unittest.TestCase):
    def test_values(self):
        found = make_site.values(PACKAGE, changelog=os.devnull)
        self.assertEqual(found["version"], "1.2.3")
        self.assertEqual(found["zip_name"], "maxdrop-1.2.3.zip")
        self.assertEqual(found["zip_href"], "./maxdrop-1.2.3.zip")
        self.assertEqual(found["size"], "22 KB")
        self.assertEqual(found["blender_min"], "4.2")
        self.assertEqual(found["repo_url"], "https://jsiovn.github.io/maxdrop/index.json")
        self.assertEqual(found["site_url"], "https://jsiovn.github.io/maxdrop/")
        self.assertRegex(found["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(make_site.values(PACKAGE, "https://example.org/x", os.devnull)["repo_url"],
                         "https://example.org/x/index.json")

    def test_sizes_and_versions(self):
        self.assertEqual(make_site.size_text(100), "1 KB")
        self.assertEqual(make_site.size_text(3 * 1024 ** 2), "3.0 MB")
        self.assertEqual(make_site.short_version("4.2.0"), "4.2")
        self.assertEqual(make_site.short_version("4.2.1"), "4.2.1")

    def test_the_date_is_the_one_of_the_changelog_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            changelog = os.path.join(tmp, "CHANGELOG.md")
            with open(changelog, "w", encoding="utf-8") as f:
                f.write("# Changelog\n\n## [1.2.4] - 2027-01-01\n\n## [1.2.3] - 2026-12-24\n\n- x\n")
            self.assertEqual(make_site.release_date("1.2.3", changelog), "2026-12-24")

    def test_this_release_is_in_the_changelog(self):
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            self.assertIn("## [%s] - " % manifest_value("version"), f.read(),
                          "the Publish workflow refuses a version without its section")


class Page(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maxdrop-site-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def repository(self, with_zip=True):
        with open(os.path.join(self.tmp, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"version": "v1", "blocklist": [], "data": [dict(PACKAGE, id="other"), PACKAGE]}, f)
        if with_zip:
            with open(os.path.join(self.tmp, "maxdrop-1.2.3.zip"), "wb") as f:
                f.write(b"PK")

    def page(self):
        self.repository()
        make_site.build(self.tmp)
        with open(os.path.join(self.tmp, "index.html"), encoding="utf-8") as f:
            return f.read()

    def test_render_escapes_and_refuses_unknown_values(self):
        self.assertEqual(make_site.render('<a href="{{href}}">{{name}}</a>', {"href": "a?b=1&c=2", "name": "<x>"}),
                         '<a href="a?b=1&amp;c=2">&lt;x&gt;</a>')
        with self.assertRaises(KeyError):
            make_site.render("{{missing}}", {})

    def test_build_writes_the_page_of_this_repository(self):
        page = self.page()
        self.assertFalse("{{" in page or "}}" in page, "a value of the template was left unfilled")
        self.assertEqual(page.count(
            'href="./maxdrop-1.2.3.zip?repository=.%2Findex.json&amp;blender_version_min=4.2.0"'), 2)
        for needle in ('data-copy="https://jsiovn.github.io/maxdrop/index.json"', "Version 1.2.3",
                       "GPL-3.0-or-later", "either version 3 of the License, or (at your option) any later version"):
            self.assertTrue(needle in page, needle)
        for name in os.listdir(os.path.join(ROOT, "site", "assets")):
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, "assets", name)), name)
            self.assertTrue("assets/" + name in page, "%s is in site/assets but not on the page" % name)

    def test_the_page_loads_nothing_from_another_site(self):
        page = self.page()
        for needle in ('src="http', "src='http", "src=\"//", '<link rel="stylesheet"', "@import", "url(http",
                       "<iframe", "fonts.googleapis"):
            self.assertFalse(needle in page, needle)
        self.assertEqual(re.findall(r'<link[^>]+href="(?!assets/)[^"]*"', page), [])
        self.assertEqual(re.findall(r'<(?:script|img)[^>]+src="(?!assets/)[^"]*"', page), [])

    def test_the_page_says_what_this_release_is(self):
        page = self.page()
        for needle in (
                "stable, not complete",                            # not a finished product
                "io_scene_max", "Sebastian Schrand", "Jens M. Plonka", "Philippe Lagadec",
                "not affiliated with, endorsed by or supported by Autodesk or Chaos",
                "Not imported yet", "Lights and cameras", "Modifiers", "Editable Mesh and Editable Poly",
                "<strong>Scene units</strong>: a scene saved in millimeters, centimeters, inches or feet arrives at its "
                "real size.",
                "<strong>Units: Auto</strong> takes the unit the scene was saved with",
                "<strong>Primitives</strong> (Box, Plane, Pyramid, Sphere, GeoSphere, Cylinder, Cone, Tube, Torus) as "
                "the meshes 3ds Max builds", "<strong>Extrude</strong> on a shape as its mesh",
                "<strong>Other modifiers</strong>",
                "<strong>Lights and cameras</strong>: V-Ray plane, disc and sphere lights",
                "<strong>Light Strength</strong> scales every light",
                "<strong>Text Encoding</strong> picks the code page"):
            self.assertTrue(needle in page, needle)

    def test_the_page_names_no_option_the_importer_lost(self):
        page = self.page()
        for gone in ("Splines and shapes", "<strong>Primitives</strong> (Box, Sphere, Cylinder…)",
                     "<strong>Modifiers</strong> (Extrude", "Apply Matrix", "<strong>Collection</strong>",
                     "one 3ds Max unit becomes one meter",
                     "imports exactly what that importer imports",
                     "Lights and cameras are not read yet", "early release", "Lights and cameras are not imported yet",
                     "Falloff and other procedural maps", "<strong>Lights and cameras</strong>, V-Ray lights included"):
            self.assertFalse(gone in page, gone)

    def test_the_page_says_how_scene_packs_are_imported(self):
        page = self.page()
        for needle in (
                "MaxDrop (.max, .zip, .rar, .7z)",                 # the menu entry
                "MaxDrop (.max, .rar, .7z)",                       # the file handler, for a drop
                "into a folder named after the archive, next to it",
                "Nothing else in the pack is written or run.",
                "Blender takes every dropped <code>.zip</code> for an extension to install",
                "UnRAR (installed with WinRAR), 7-Zip, or a recent bsdtar",
                "<strong>Scene</strong> picks the <code>.max</code> to import from a pack that holds several."):
            self.assertTrue(needle in page, needle)

    def test_the_page_adapts_to_the_screen_and_the_color_scheme(self):
        page = self.page()
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', page)
        self.assertIn("@media (prefers-color-scheme: dark)", page)
        self.assertIn('<meta name="color-scheme" content="light dark">', page)

    def test_a_missing_package_is_an_error(self):
        with self.assertRaises(LookupError):
            make_site.package_of({"data": [dict(PACKAGE, id="other")]})

    def test_a_link_to_a_zip_that_is_not_there_is_an_error(self):
        self.repository(with_zip=False)
        with self.assertRaises(LookupError):
            make_site.build(self.tmp)


if __name__ == "__main__":
    unittest.main()
