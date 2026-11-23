"""Fake xbmc / xbmcgui / xbmcplugin / xbmcaddon / xbmcvfs modules.

Importing this module installs the fakes in sys.modules and puts the add-on
directory on sys.path, so `from resources.lib import plugin` works outside Kodi.
Exposes PROFILE (temp add-on profile dir), SETTINGS (mutable getSetting backing
dict) and LOG (what the plugin did: items, notes, end, resolved, builtin).
"""
import json
import os
import re
import sys
import tempfile
import types

ADDON_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "..", "plugin.image.photoprism"))
sys.path.insert(0, ADDON_DIR)
PROFILE = tempfile.mkdtemp()
SETTINGS = {"server_url": "", "auth_mode": "0", "username": "admin", "password": "pw", "token": "",
            "page_size": "2", "thumb_size": "tile_500", "full_size": "fit_1920", "prefetch": "true",
            "prefetch_threads": "2", "cache_enabled": "true", "cache_path": "", "cache_max_mb": "500",
            "cache_ttl_hours": "24", "timeout": "3", "verify_ssl": "true", "video_format": "avc",
            "debug_log": "false", "hide_empty_albums": "false"}
LOG = {"items": [], "notes": [], "end": [], "resolved": [], "builtin": [], "klog": [], "text": [], "progress": [], "selects": [], "yesno": [], "opened": []}
KBCFG = {"text": "label:cat", "ok": True}   # what the fake on-screen keyboard returns
SELECT = {"value": 0}                       # which entry the fake Dialog().select() picks (-1 = cancel)
YESNO = {"value": False}                    # answer of the fake Dialog().yesno()
LANG = {"code": "en_gb"}                    # which strings.po getLocalizedString() reads
WIN = {}                                    # properties of the fake Home window
ACTIVE = {"slideshow": False}               # what Window.IsActive(slideshow) returns
# fake Kodi settings reachable through JSON-RPC; fail_* simulate JSON-RPC errors
KODI_SETTINGS = {"slideshow.displayeffects": True, "slideshow.staytime": 5, "pictures.thumbsize": 192, "player.other": 1}
RPC = {"calls": [], "fail_get": False, "fail_set": False}
def mod(n): m = types.ModuleType(n); sys.modules[n] = m; return m
x = mod("xbmc"); x.LOGDEBUG, x.LOGINFO, x.LOGWARNING, x.LOGERROR = 0, 1, 2, 3
x.log = lambda m, l=1: LOG["klog"].append((l, m))
x.executebuiltin = lambda c: LOG["builtin"].append(c)
x.getCondVisibility = lambda c: ACTIVE["slideshow"] if "slideshow" in c else False


def _rpc(raw):
    req = json.loads(raw); m, pr = req["method"], req["params"]; RPC["calls"].append((m, pr))
    if m == "Settings.GetSettingValue":
        if RPC["fail_get"] or pr["setting"] not in KODI_SETTINGS: return json.dumps({"error": {"code": -32602}})
        return json.dumps({"result": {"value": KODI_SETTINGS[pr["setting"]]}})
    if m == "Settings.SetSettingValue":
        if RPC["fail_set"] or pr["setting"] not in KODI_SETTINGS: return json.dumps({"error": {"code": -32602}})
        KODI_SETTINGS[pr["setting"]] = pr["value"]; return json.dumps({"result": True})
    if m == "Settings.GetSettings":
        return json.dumps({"result": {"settings": [{"id": k, "value": v} for k, v in KODI_SETTINGS.items()]}})
    return json.dumps({"error": {"code": -32601}})
x.executeJSONRPC = _rpc
MONITOR = {"seen": [], "ticks": 1}          # what the service loop saw (Home-window property) at each wait


class Monitor:
    def abortRequested(s): return MONITOR["ticks"] <= 0
    def waitForAbort(s, t):
        MONITOR["seen"].append(WIN.get("kodiprism.service")); MONITOR["ticks"] -= 1; return MONITOR["ticks"] <= 0
x.Monitor = Monitor
class KB:
    def __init__(s, *a): pass
    def doModal(s): pass
    def isConfirmed(s): return KBCFG["ok"]
    def getText(s): return KBCFG["text"]
x.Keyboard = KB
a = mod("xbmcaddon")
def _po(code):
    """{id: (english, translation)} read from the add-on's real strings.po files."""
    path = os.path.join(ADDON_DIR, "resources", "language", "resource.language.%s" % code, "strings.po")
    text = open(path, encoding="utf-8").read()
    un = lambda t: t.replace('\\"', '"').replace("\\\\", "\\")
    return {int(i): (un(en), un(tr)) for i, en, tr in re.findall(r'msgctxt "#(\d+)"\nmsgid "(.*)"\nmsgstr "(.*)"', text)}


class Addon:
    def getSetting(s, k): return SETTINGS.get(k, "")
    def getLocalizedString(s, i):
        en, tr = _po(LANG["code"]).get(i, ("", ""))
        return tr or en
    def openSettings(s): LOG["opened"].append(1)
    def getAddonInfo(s, k): return {"id": "plugin.image.photoprism", "name": "PhotoPrism", "profile": PROFILE, "version": "9.9.9"}.get(k, "")
a.Addon = Addon
g = mod("xbmcgui"); g.NOTIFICATION_ERROR, g.NOTIFICATION_INFO = "e", "i"
class LI:
    def __init__(s, label="", path=""): s.label, s.path, s.art, s.props, s.label2, s.ctx = label, path, {}, {}, "", []
    def setArt(s, d): s.art = d
    def setInfo(s, *a): pass
    def setLabel2(s, v): s.label2 = v
    def setProperty(s, k, v): s.props[k] = v
    def setMimeType(s, m): pass
    def setContentLookup(s, b): pass
    def addContextMenuItems(s, i): s.ctx = list(i)
    def getVideoInfoTag(s): return Tag()
    def getPictureInfoTag(s): return Tag()
class Tag:
    def __getattr__(s, n):
        assert n in ("setTitle", "setPlot", "setDuration", "setMediaType", "setDateTimeTaken", "setResolution"), n
        return lambda *a: None
g.ListItem = LI
class D:
    def notification(s, h, m, *a): LOG["notes"].append(m)
    def textviewer(s, h, t, *a): LOG["text"].append((h, t))
    def select(s, h, opts, *a): LOG["selects"].append((h, list(opts))); return SELECT["value"]
    def yesno(s, h, m, nolabel="", yeslabel="", *a): LOG["yesno"].append((h, m, nolabel, yeslabel)); return YESNO["value"]
class PBG:
    def create(s, h, m=""): LOG["progress"].append("create")
    def update(s, pct=0, heading="", message=""): LOG["progress"].append("update")
    def close(s): LOG["progress"].append("close")
g.DialogProgressBG = PBG
class Window:
    def __init__(s, i): pass
    def getProperty(s, k): return WIN.get(k, "")
    def setProperty(s, k, v): WIN[k] = v
    def clearProperty(s, k): WIN.pop(k, None)
g.Window = Window
g.Dialog = D
p = mod("xbmcplugin")
p.addDirectoryItem = lambda h, u, li, f=False: LOG["items"].append((li.label, u, li.art.get("thumb"), f, li.label2, li.ctx))
p.setPluginCategory = lambda h, c: LOG["text"].append(("category", c))
p.endOfDirectory = lambda h, succeeded=True, **k: LOG["end"].append(succeeded)
p.setContent = lambda *a: None
p.setResolvedUrl = lambda h, ok, li: LOG["resolved"].append((ok, li.path))
v = mod("xbmcvfs"); v.translatePath = lambda p: p
