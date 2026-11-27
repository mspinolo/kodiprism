#!/usr/bin/env python3
"""Build an installable Kodi zip: dist/<addon-id>-<version>.zip

    python3 tools/build_zip.py                         # the add-on (plugin.image.photoprism)
    python3 tools/build_zip.py repository.kodiprism    # the repository add-on

The zip contains a single top-level folder named after the add-on id (Kodi
requires this) and only the files Kodi needs: no caches, bytecode or VCS files.
Output is deterministic (sorted entries, fixed timestamps).
"""
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
EXCLUDE_DIRS = {"__pycache__", ".mypy_cache", ".pytest_cache", ".git"}
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".orig", ".rej", ".swp", ".DS_Store")
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def main(folder="plugin.image.photoprism"):
    src = os.path.join(ROOT, folder)
    if not os.path.isfile(os.path.join(src, "addon.xml")):
        sys.exit("add-on folder not found: %s" % src)
    meta = ET.parse(os.path.join(src, "addon.xml")).getroot()
    addon_id, version = meta.get("id"), meta.get("version")
    if addon_id != os.path.basename(src):
        sys.exit("folder %s does not match the add-on id %s" % (folder, addon_id))
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", "%s-%s.zip" % (addon_id, version))
    files = []
    for base, dirs, names in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for n in sorted(names):
            if not n.endswith(EXCLUDE_SUFFIX):
                files.append(os.path.join(base, n))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in files:
            arc = os.path.join(addon_id, os.path.relpath(path, src)).replace(os.sep, "/")
            info = zipfile.ZipInfo(arc, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as fh:
                z.writestr(info, fh.read())
    print("%s  (%d files, %d bytes)" % (os.path.relpath(out, ROOT), len(files), os.path.getsize(out)))
    return out


if __name__ == "__main__":
    main(*sys.argv[1:2])
