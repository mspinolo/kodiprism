"""Offline static checks of the add-on package (no Kodi, no network).

This does NOT replace `kodi-addon-checker --branch omega`, which needs internet
access to the official Kodi repository and runs in CI (docs/ci/ci.yml once activated).
"""
import os
import re
import xml.etree.ElementTree as ET

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ADDON = os.path.join(ROOT, "plugin.image.photoprism")
ok = 0


def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("PASS", msg)


addon = ET.parse(os.path.join(ADDON, "addon.xml")).getroot()
settings = ET.parse(os.path.join(ADDON, "resources", "settings.xml")).getroot()
check(addon.get("id") == os.path.basename(ADDON), "addon id == folder name")

# every numeric label used by settings.xml exists in strings.po
po = open(os.path.join(ADDON, "resources", "language", "resource.language.en_gb", "strings.po"),
          encoding="utf-8").read()
defined = set(re.findall(r'msgctxt "#(\d+)"', po))
used = set()
for el in settings.iter():
    if el.get("label", "").isdigit():            # label="30001" on category/setting/option
        used.add(el.get("label"))
    if el.tag == "heading" and (el.text or "").strip().isdigit():
        used.add(el.text.strip())
check(used and used <= defined, "all settings label ids exist in strings.po (missing: %s)" % sorted(used - defined))
check(len(re.findall(r'msgctxt "#(\d+)"', po)) == len(defined), "no duplicate string ids in strings.po")

# every setting id referenced by the code exists in settings.xml
ids = {s.get("id") for s in settings.iter("setting")}
code = open(os.path.join(ADDON, "resources", "lib", "plugin.py"), encoding="utf-8").read()
referenced = set(re.findall(r'\bs(?:_int|_bool)?\("([a-z_]+)"', code))
check(referenced <= ids, "settings read by plugin.py are declared (missing: %s)" % sorted(referenced - ids))

# artwork
try:
    from PIL import Image
except ImportError:
    Image = None
if Image:
    icon = Image.open(os.path.join(ADDON, "resources", "icon.png"))
    fan = Image.open(os.path.join(ADDON, "resources", "fanart.jpg"))
    check(icon.size == (512, 512) and icon.mode == "RGB", "icon.png is 512x512 RGB (no transparency)")
    check(fan.size == (1920, 1080), "fanart.jpg is 1920x1080")

# license metadata matches the LICENSE file
lic = open(os.path.join(ROOT, "LICENSE"), encoding="utf-8").read(200)
expected = "GPL-3.0" if "GNU GENERAL PUBLIC LICENSE" in lic and "Version 3" in lic else None
declared = addon.find(".//license").text or ""
check(expected and declared.startswith(expected), "addon.xml <license> (%s) matches LICENSE file" % declared)

# version is documented in the changelog
changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
check("## [%s]" % addon.get("version") in changelog, "CHANGELOG.md has an entry for %s" % addon.get("version"))
print("ALL %d STATIC CHECKS PASSED" % ok)
