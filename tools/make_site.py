# SPDX-FileCopyrightText: 2026 jsiovn
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Write the landing pages of the extension repository: dist/index.html and dist/vi.html from site/ and index.json.

    python tools/make_site.py dist [--site https://jsiovn.github.io/maxdrop/]

Blender's own `server-generate --html` page is a bare table and its template only knows ${body} and ${date}, so
the page is ours. The install link keeps the exact form Blender's generator emits (bl_pkg/cli/blender_ext.py,
_generate_html): Blender reads the repository and the version range from the query when the link is dropped on it.
PAGES are the same page in each language (English, Vietnamese), filled with the same values. Standard library only.
"""
import argparse
import datetime
import html
import json
import os
import re
import shutil
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTENSION_ID = "maxdrop"
TOKEN = re.compile(r"\{\{(\w+)\}\}")
PAGES = ("index.html", "vi.html")


def install_href(package):
    """The archive URL with the drag-and-drop parameters, as Blender's generator builds it."""
    parsed = urllib.parse.urlparse(package["archive_url"])
    query = {"repository": "./index.json"}
    for key in ("blender_version_min", "blender_version_max"):
        if package.get(key):
            query[key] = package[key]
    for key in ("platforms", "python_versions"):
        if package.get(key):
            query[key] = ",".join(package[key])
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params,
                                    urllib.parse.urlencode(query, doseq=True), parsed.fragment))


def size_text(size):
    if size >= 1024 ** 2:
        return "%.1f MB" % (size / 1024 ** 2)
    return "%d KB" % max(1, round(size / 1024))


def release_date(version, changelog):
    """The date of the version's CHANGELOG section, else today (UTC)."""
    try:
        with open(changelog, encoding="utf-8") as f:
            m = re.search(r"^## \[%s\] - (\d{4}-\d{2}-\d{2})" % re.escape(version), f.read(), re.M)
    except OSError:
        m = None
    return m.group(1) if m else datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def short_version(version):
    """"4.2.0" -> "4.2": how Blender names its releases."""
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) == 3 and parts[2] == "0" else version


def values(package, site="", changelog=os.path.join(ROOT, "CHANGELOG.md")):
    site = (site or package.get("website") or "").rstrip("/") + "/"
    archive = package["archive_url"]
    return {
        "version": package["version"],
        "zip_name": archive.rpartition("/")[2],
        "zip_href": archive,
        "install_href": install_href(package),
        "size": size_text(package["archive_size"]),
        "blender_min": short_version(package.get("blender_version_min", "")),
        "date": release_date(package["version"], changelog),
        "site_url": site,
        "repo_url": site + "index.json",
    }


def render(template, found, name="index.html"):
    """Fill every {{token}}; one the page asks for and we do not know is an error, not an empty string."""
    unknown = sorted(set(TOKEN.findall(template)) - set(found))
    if unknown:
        raise KeyError("site/%s asks for unknown values: %s" % (name, ", ".join(unknown)))
    return TOKEN.sub(lambda m: html.escape(found[m.group(1)], quote=True), template)


def package_of(index):
    for package in index.get("data", ()):
        if package.get("id") == EXTENSION_ID:
            return package
    raise LookupError("%s is not listed in index.json" % EXTENSION_ID)


def build(dist, site="", source=os.path.join(ROOT, "site")):
    with open(os.path.join(dist, "index.json"), encoding="utf-8") as f:
        found = values(package_of(json.load(f)), site)
    # The install link is relative to the page: the zip it names has to be published next to it.
    if not os.path.isfile(os.path.join(dist, found["zip_name"])):
        raise LookupError("index.json names %s, which is not in %s" % (found["zip_name"], dist))
    for name in PAGES:
        with open(os.path.join(source, name), encoding="utf-8") as f:
            page = render(f.read(), found, name)
        with open(os.path.join(dist, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(page)
    assets = os.path.join(source, "assets")
    if os.path.isdir(assets):
        shutil.copytree(assets, os.path.join(dist, "assets"), dirs_exist_ok=True)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist", help="folder holding index.json and the zip; the pages are written into it")
    parser.add_argument("--site", default="", help="public URL of the folder (default: the manifest's website)")
    args = parser.parse_args(argv)
    found = build(args.dist, args.site)
    print("Wrote %s (%s, %s)" % (", ".join(os.path.join(args.dist, name) for name in PAGES), found["zip_name"],
                                 found["install_href"]))


if __name__ == "__main__":
    sys.exit(main())
