"""Offline static checks of the add-on package (no Kodi, no network).

This does NOT replace `kodi-addon-checker --branch omega`, which needs internet
access to the official Kodi repository and runs in CI (.github/workflows/ci.yml).
"""
import os
import re
import xml.etree.ElementTree as ET

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ADDON = os.path.join(ROOT, "plugin.image.photoprism")
LANG = os.path.join(ADDON, "resources", "language")

addon = ET.parse(os.path.join(ADDON, "addon.xml")).getroot()
settings = ET.parse(os.path.join(ADDON, "resources", "settings.xml")).getroot()
code = open(os.path.join(ADDON, "resources", "lib", "plugin.py"), encoding="utf-8").read()


def po_entries(code_):
    text = open(os.path.join(LANG, "resource.language.%s" % code_, "strings.po"), encoding="utf-8").read()
    return {int(i): (en, tr) for i, en, tr in re.findall(r'msgctxt "#(\d+)"\nmsgid "(.*)"\nmsgstr "(.*)"', text)}


en_po, it_po = po_entries("en_gb"), po_entries("it_it")
service = [e for e in addon.findall("extension") if e.get("point") == "xbmc.service"]


def test_addon_identity():
    assert addon.get("id") == os.path.basename(ADDON), "addon id == folder name"
    assert addon.get("name") == "KodiPrism", "add-on display name is KodiPrism (the PhotoPrism name/logo are trademarks)"
    assert "Not affiliated" in (addon.findtext(".//description") or ""), "description says the add-on is not affiliated with PhotoPrism"


def test_settings_labels_exist():
    po = open(os.path.join(LANG, "resource.language.en_gb", "strings.po"), encoding="utf-8").read()
    ids = re.findall(r'msgctxt "#(\d+)"', po)
    defined, used = set(ids), set()
    for el in settings.iter():
        if el.get("label", "").isdigit():            # label="30001" on category/setting/option
            used.add(el.get("label"))
        if el.tag == "heading" and (el.text or "").strip().isdigit():
            used.add(el.text.strip())
    assert used and used <= defined, "all settings label ids exist in strings.po (missing: %s)" % sorted(used - defined)
    assert len(ids) == len(defined), "no duplicate string ids in strings.po"


def test_italian_translation_is_complete():
    assert set(en_po) == set(it_po), "it_it has exactly the string ids of en_gb (diff: %s)" % sorted(set(en_po) ^ set(it_po))
    assert all(it_po[i][1].strip() for i in it_po), "it_it: every string translated"
    assert all(it_po[i][0] == en_po[i][0] for i in it_po), "it_it: msgid equals the English source"
    ph = lambda t: sorted(re.findall(r"%[sd]", t))  # noqa: E731
    assert all(ph(en_po[i][0]) == ph(it_po[i][1]) for i in en_po), "it_it keeps the %d / %s placeholders of the English text"


def test_ui_text_is_localised():
    str_ids = {int(i) for i in re.findall(r'"[a-z_]+": (30\d{3})', code[code.index("STR = {"):code.index("def L(")])}
    assert str_ids and str_ids <= set(en_po), "every string id used by plugin.py exists in strings.po (missing: %s)" % sorted(str_ids - set(en_po))
    assert not re.findall(r'add_dir\("[A-Za-z]', code) and 'notify("' not in code, "no hard-coded English labels or notifications in plugin.py"


def test_service_declaration():
    """Learned from the real kodi-addon-checker (Omega schema): xbmc.service only accepts point/id/name/library,
    and entry-point scripts must stay at 15 counted lines or fewer."""
    assert len(service) == 1 and os.path.exists(os.path.join(ADDON, service[0].get("library"))), "xbmc.service declared and service.py exists"
    assert set(service[0].attrib) <= {"point", "id", "name", "library"}, "xbmc.service uses only attributes allowed by the Omega schema"
    lines = [l for l in open(os.path.join(ADDON, "service.py"), encoding="utf-8").read().splitlines()
             if l.strip() and not l.strip().startswith("#")]
    assert len(lines) <= 15, "service.py is a thin entry point (%d lines)" % len(lines)


def test_settings_read_by_code_are_declared():
    ids = {s.get("id") for s in settings.iter("setting")}
    referenced = set(re.findall(r'\bs(?:_int|_bool)?\("([a-z_]+)"', code))
    assert referenced <= ids, "settings read by plugin.py are declared (missing: %s)" % sorted(referenced - ids)


BUTTONS = sorted({m.group(1) for el in settings.iter("data") for m in [re.search(r"action=([a-z_]+)", el.text or "")] if m})


@pytest.mark.parametrize("action", BUTTONS)
def test_settings_button_is_routed(action):
    assert '"%s":' % action in code, "settings button action '%s' is routed in plugin.py" % action


def test_artwork():
    Image = pytest.importorskip("PIL.Image")
    icon = Image.open(os.path.join(ADDON, "resources", "icon.png"))
    fan = Image.open(os.path.join(ADDON, "resources", "fanart.jpg"))
    assert icon.size == (512, 512) and icon.mode == "RGB", "icon.png is 512x512 RGB (no transparency)"
    assert fan.size == (1920, 1080), "fanart.jpg is 1920x1080"


def test_license_matches():
    lic = open(os.path.join(ROOT, "LICENSE"), encoding="utf-8").read(200)
    expected = "GPL-3.0" if "GNU GENERAL PUBLIC LICENSE" in lic and "Version 3" in lic else None
    declared = addon.find(".//license").text or ""
    assert expected and declared.startswith(expected), "addon.xml <license> (%s) matches LICENSE file" % declared


def test_version_in_changelog():
    changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    assert "## [%s]" % addon.get("version") in changelog, "CHANGELOG.md has an entry for %s" % addon.get("version")
