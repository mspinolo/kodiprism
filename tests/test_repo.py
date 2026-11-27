"""The Kodi repository: the repository add-on itself and what tools/build_repo.py publishes."""
import hashlib
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPO = os.path.join(ROOT, "repository.kodiprism")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_repo  # noqa: E402
import build_zip  # noqa: E402

BASE = "https://raw.githubusercontent.com/mspinolo/kodiprism/repo/"
meta = ET.parse(os.path.join(REPO, "addon.xml")).getroot()


def make_zip(tmp, addon_id, version, extra=None):
    """A minimal valid add-on zip (one top folder named after the id)."""
    path = os.path.join(str(tmp), "%s-%s.zip" % (addon_id, version))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("%s/addon.xml" % addon_id, '<?xml version="1.0" encoding="UTF-8"?>\n<addon id="%s" version="%s" name="x" provider-name="y">'
                   '<extension point="xbmc.addon.metadata"><assets><icon>icon.png</icon></assets></extension></addon>' % (addon_id, version))
        z.writestr("%s/icon.png" % addon_id, b"PNG" + version.encode())
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def test_repository_addon_points_at_the_repo_branch():
    d = meta.find("extension[@point='xbmc.addon.repository']/dir")
    assert meta.get("id") == os.path.basename(REPO), "addon id == folder name"
    assert d.findtext("info") == BASE + "addons.xml" and d.find("info").get("compressed") == "false", "info: plain addons.xml on the repo branch"
    assert d.findtext("checksum") == BASE + "addons.xml.md5", "checksum next to addons.xml"
    assert d.findtext("datadir") == BASE and d.find("datadir").get("zip") == "true", "datadir: zips under <id>/<id>-<version>.zip"
    assert all(u.startswith("https://") for u in (d.findtext("info"), d.findtext("checksum"), d.findtext("datadir"))), "https only"


def test_repository_addon_metadata():
    m = meta.find("extension[@point='xbmc.addon.metadata']")
    assert {e.get("lang") for e in m.findall("summary")} == {"en_GB", "it_IT"}, "summary in English and Italian"
    assert all("Not affiliated" in e.text or "Non affiliato" in e.text for e in m.findall("description")), "trademark disclaimer"
    for rel in (m.findtext("assets/icon"), m.findtext("assets/fanart")):
        assert os.path.isfile(os.path.join(REPO, rel)), "asset %s exists" % rel
    assert m.findtext("license") == ET.parse(os.path.join(ROOT, "plugin.image.photoprism", "addon.xml")).getroot().findtext(".//license")


def test_build_repo_from_the_real_zips(tmp_path):
    plugin_zip = build_zip.main("plugin.image.photoprism")
    repo_zip = build_zip.main("repository.kodiprism")
    out = str(tmp_path / "repo")
    got = build_repo.build(out, [plugin_zip, repo_zip])
    pv = ET.parse(os.path.join(ROOT, "plugin.image.photoprism", "addon.xml")).getroot().get("version")
    assert got == {"plugin.image.photoprism": pv, "repository.kodiprism": meta.get("version")}
    data = open(os.path.join(out, "addons.xml"), "rb").read()
    assert open(os.path.join(out, "addons.xml.md5")).read() == hashlib.md5(data).hexdigest(), "md5 file matches addons.xml"
    addons = ET.fromstring(data)
    assert sorted(a.get("id") for a in addons) == ["plugin.image.photoprism", "repository.kodiprism"], "both add-ons listed"
    assert addons.find("addon[@id='plugin.image.photoprism']").find("requires/import[@addon='script.module.requests']") is not None, \
        "the plugin's dependencies are listed, so Kodi installs them from the official repository"
    for addon_id, ver in got.items():
        z = os.path.join(out, addon_id, "%s-%s.zip" % (addon_id, ver))
        assert os.path.isfile(z), "zip at <datadir>/<id>/<id>-<version>.zip"
        assert zipfile.ZipFile(z).testzip() is None
    assert os.path.isfile(os.path.join(out, "plugin.image.photoprism", "resources", "icon.png")), "plugin icon extracted for Kodi's browser"
    assert os.path.isfile(os.path.join(out, "plugin.image.photoprism", "resources", "fanart.jpg"))
    assert os.path.isfile(os.path.join(out, "repository.kodiprism", "icon.png"))


def test_build_repo_is_deterministic(tmp_path):
    zips = [make_zip(tmp_path, "plugin.x", "1.0.0"), make_zip(tmp_path, "repository.y", "2.0.0")]
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    build_repo.build(a, zips); build_repo.build(b, zips)
    assert open(os.path.join(a, "addons.xml"), "rb").read() == open(os.path.join(b, "addons.xml"), "rb").read()


def test_newest_version_wins(tmp_path):
    zips = [make_zip(tmp_path, "plugin.x", v) for v in ("1.9.2", "1.10.0", "1.10.0~beta1", "1.2.0")]
    out = str(tmp_path / "out")
    assert build_repo.build(out, zips) == {"plugin.x": "1.10.0"}, "1.10.0 > 1.10.0~beta1 > 1.9.2 (numeric, not text, order)"
    assert os.listdir(os.path.join(out, "plugin.x")) and not os.path.exists(os.path.join(out, "plugin.x", "plugin.x-1.9.2.zip")), "only the newest zip"
    assert open(os.path.join(out, "plugin.x", "icon.png"), "rb").read() == b"PNG1.10.0", "the icon comes from the newest zip"


def test_rebuild_drops_stale_files(tmp_path):
    out = str(tmp_path / "out")
    build_repo.build(out, [make_zip(tmp_path, "plugin.x", "1.0.0")])
    build_repo.build(out, [make_zip(tmp_path, "plugin.x", "1.1.0")])
    assert sorted(os.listdir(os.path.join(out, "plugin.x"))) == ["icon.png", "plugin.x-1.1.0.zip"], "old zip removed"


@pytest.mark.parametrize("bad", ["two_tops", "id_mismatch"])
def test_bad_zips_are_refused(tmp_path, bad):
    if bad == "two_tops":
        z = make_zip(tmp_path, "plugin.x", "1.0.0", {"other/file.txt": b"x"})
    else:
        z = os.path.join(str(tmp_path), "bad.zip")
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("plugin.x/addon.xml", '<addon id="plugin.y" version="1.0.0"/>')
    with pytest.raises(SystemExit):
        build_repo.build(str(tmp_path / "out"), [z])


def test_command_line(tmp_path):
    z = make_zip(tmp_path, "plugin.x", "1.0.0")
    done = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_repo.py"), str(tmp_path / "out"), z],
                          capture_output=True, text=True)
    assert done.returncode == 0 and "plugin.x 1.0.0" in done.stdout
