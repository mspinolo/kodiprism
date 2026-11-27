#!/usr/bin/env python3
"""Build the release zip, unpack it somewhere else and run the functional tests against *that* copy.

This catches what testing the source tree cannot: a file missing from the package, a stray cache
or bytecode inside it, or a module that only works because the repository layout is around it.
"""
import os
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ADDON_ID = "plugin.image.photoprism"


def main():
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_zip.py")], check=True, stdout=subprocess.DEVNULL)
    import xml.etree.ElementTree as ET
    version = ET.parse(os.path.join(ROOT, ADDON_ID, "addon.xml")).getroot().get("version")
    path = os.path.join(ROOT, "dist", "%s-%s.zip" % (ADDON_ID, version))
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert all(n.startswith(ADDON_ID + "/") for n in names), "everything must be inside the %s/ folder" % ADDON_ID
        junk = [n for n in names if "__pycache__" in n or n.endswith((".pyc", ".orig", ".rej")) or ".mypy_cache" in n]
        assert not junk, "junk inside the zip: %s" % junk
        for need in ("addon.xml", "default.py", "service.py", "resources/settings.xml", "resources/icon.png", "resources/fanart.jpg",
                     "resources/language/resource.language.en_gb/strings.po", "resources/language/resource.language.it_it/strings.po"):
            assert "%s/%s" % (ADDON_ID, need) in names, "missing from the zip: " + need
        lib = {os.path.basename(n)[:-3] for n in names if "/resources/lib/" in n and n.endswith(".py")}
        need_lib = {"api", "cache", "catalog", "logger", "plugin", "service_main", "slideshow_fx"}
        assert need_lib <= lib, "library modules missing from the zip: %s" % sorted(need_lib - lib)
        tmp = tempfile.mkdtemp()
        z.extractall(tmp)
    unpacked = os.path.join(tmp, ADDON_ID)
    for base, _, files in os.walk(unpacked):  # every module must at least compile
        for f in files:
            if f.endswith(".py"):
                with open(os.path.join(base, f), encoding="utf-8") as fh:
                    compile(fh.read(), os.path.join(base, f), "exec")
    env = dict(os.environ, KODIPRISM_ADDON_DIR=unpacked)
    # every functional test, against the unpacked copy (the static checks read the source tree, so they are skipped)
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--ignore", os.path.join(ROOT, "tests", "test_static.py"),
                           os.path.join(ROOT, "tests")], env=env, capture_output=True, text=True, cwd=ROOT)
    last = (done.stdout.strip().splitlines() or ["(no output)"])[-1]
    print("tests against the unpacked zip: %s" % last)
    if done.returncode != 0:
        sys.exit(done.stdout[-3000:] + done.stderr[-2000:])
    print("ZIP OK: %s (%d files)" % (os.path.relpath(path, ROOT), len(names)))


if __name__ == "__main__":
    main()
