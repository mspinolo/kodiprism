"""Fake xbmc / xbmcgui / xbmcplugin / xbmcaddon / xbmcvfs modules.

Importing this module installs the fakes in sys.modules and puts the add-on
directory on sys.path, so `from resources.lib import plugin` works outside Kodi.
Exposes PROFILE (temp add-on profile dir), SETTINGS (mutable getSetting backing
dict) and LOG (what the plugin did: items, notes, end, resolved, builtin).
"""
import os
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
            "debug_log": "false"}
LOG = {"items": [], "notes": [], "end": [], "resolved": [], "builtin": [], "klog": [], "text": []}
def mod(n): m = types.ModuleType(n); sys.modules[n] = m; return m
x = mod("xbmc"); x.LOGDEBUG, x.LOGINFO, x.LOGWARNING, x.LOGERROR = 0, 1, 2, 3
x.log = lambda m, l=1: LOG["klog"].append((l, m))
x.executebuiltin = lambda c: LOG["builtin"].append(c)
class KB:
    def __init__(s, *a): pass
    def doModal(s): pass
    def isConfirmed(s): return True
    def getText(s): return "label:cat"
x.Keyboard = KB
a = mod("xbmcaddon")
class Addon:
    def getSetting(s, k): return SETTINGS.get(k, "")
    def getAddonInfo(s, k): return {"id": "plugin.image.photoprism", "name": "PhotoPrism", "profile": PROFILE, "version": "9.9.9"}.get(k, "")
a.Addon = Addon
g = mod("xbmcgui"); g.NOTIFICATION_ERROR, g.NOTIFICATION_INFO = "e", "i"
class LI:
    def __init__(s, label="", path=""): s.label, s.path, s.art, s.props = label, path, {}, {}
    def setArt(s, d): s.art = d
    def setInfo(s, *a): pass
    def setProperty(s, k, v): s.props[k] = v
    def setMimeType(s, m): pass
    def setContentLookup(s, b): pass
    def addContextMenuItems(s, i): pass
    def getVideoInfoTag(s): return Tag()
    def getPictureInfoTag(s): return Tag()
class Tag:
    def __getattr__(s, n):
        assert n in ("setTitle", "setPlot", "setDuration", "setMediaType", "setDateTimeTaken"), n
        return lambda *a: None
g.ListItem = LI
class D:
    def notification(s, h, m, *a): LOG["notes"].append(m)
    def textviewer(s, h, t, *a): LOG["text"].append((h, t))
g.Dialog = D
p = mod("xbmcplugin")
p.addDirectoryItem = lambda h, u, li, f=False: LOG["items"].append((li.label, u, li.art.get("thumb"), f))
p.endOfDirectory = lambda h, succeeded=True, **k: LOG["end"].append(succeeded)
p.setContent = lambda *a: None
p.setResolvedUrl = lambda h, ok, li: LOG["resolved"].append((ok, li.path))
v = mod("xbmcvfs"); v.translatePath = lambda p: p
