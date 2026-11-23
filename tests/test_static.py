"""Offline static checks of the add-on package (no Kodi, no network).

This does NOT replace `kodi-addon-checker --branch omega`, which needs internet
access to the official Kodi repository and runs in CI (.github/workflows/ci.yml).
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
check(addon.get("name") == "KodiPrism", "add-on display name is KodiPrism (the PhotoPrism name/logo are trademarks)")
check("Not affiliated" in (addon.findtext(".//description") or ""), "description says the add-on is not affiliated with PhotoPrism")

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

# translations: Italian has every id of the English source, translated, with the same placeholders
lang = os.path.join(ADDON, "resources", "language")
def po_entries(code):
    text = open(os.path.join(lang, "resource.language.%s" % code, "strings.po"), encoding="utf-8").read()
    return {int(i): (en, tr) for i, en, tr in re.findall(r'msgctxt "#(\d+)"\nmsgid "(.*)"\nmsgstr "(.*)"', text)}
en_po, it_po = po_entries("en_gb"), po_entries("it_it")
check(set(en_po) == set(it_po), "it_it has exactly the string ids of en_gb (diff: %s)" % sorted(set(en_po) ^ set(it_po)))
check(all(it_po[i][1].strip() for i in it_po) and all(it_po[i][0] == en_po[i][0] for i in it_po), "it_it: every string translated, msgid equals the English source")
ph = lambda t: sorted(re.findall(r"%[sd]", t))
check(all(ph(en_po[i][0]) == ph(it_po[i][1]) for i in en_po), "it_it keeps the %d / %s placeholders of the English text")
src = open(os.path.join(ADDON, "resources", "lib", "plugin.py"), encoding="utf-8").read()
str_ids = {int(i) for i in re.findall(r'"[a-z_]+": (30\d{3})', src[src.index("STR = {"):src.index("def L(")])}
check(str_ids and str_ids <= set(en_po), "every string id used by plugin.py exists in strings.po (missing: %s)" % sorted(str_ids - set(en_po)))
check(not re.findall(r'add_dir\("[A-Za-z]', src) and "notify(\"" not in src, "no hard-coded English labels or notifications left in plugin.py")

# the background service is declared and its file exists
svc = [e for e in addon.findall("extension") if e.get("point") == "xbmc.service"]
check(len(svc) == 1 and os.path.exists(os.path.join(ADDON, svc[0].get("library"))), "xbmc.service extension declared and service.py exists")

# every setting id referenced by the code exists in settings.xml
ids = {s.get("id") for s in settings.iter("setting")}
code = open(os.path.join(ADDON, "resources", "lib", "plugin.py"), encoding="utf-8").read()
referenced = set(re.findall(r'\bs(?:_int|_bool)?\("([a-z_]+)"', code))
check(referenced <= ids, "settings read by plugin.py are declared (missing: %s)" % sorted(referenced - ids))

# every action button in settings.xml is routed by plugin.py
for el in settings.iter("data"):
    m = re.search(r"action=([a-z_]+)", el.text or "")
    if m:
        check('"%s":' % m.group(1) in code, "settings button action '%s' is routed in plugin.py" % m.group(1))

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
