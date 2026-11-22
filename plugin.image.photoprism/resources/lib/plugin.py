# -*- coding: utf-8 -*-
"""Kodi plugin routing and UI for PhotoPrism."""
import json
import os
import threading

from urllib.parse import urlencode, parse_qsl

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib.api import PhotoPrism, ApiError, AuthError
from resources.lib.cache import DiskCache, resolve_dir

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
NAME = ADDON.getAddonInfo("name")
ICON = ADDON.getAddonInfo("icon")
FANART = ADDON.getAddonInfo("fanart")
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))


def log(msg, level=xbmc.LOGINFO):
    xbmc.log("[%s] %s" % (ADDON_ID, msg), level)


def notify(msg, error=True):
    xbmcgui.Dialog().notification(NAME, msg,
                                  xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_INFO,
                                  5000)


def s(key):
    return ADDON.getSetting(key)


def s_int(key, default):
    try:
        return int(ADDON.getSetting(key))
    except (TypeError, ValueError):
        return default


def s_bool(key):
    return ADDON.getSetting(key).lower() == "true"


class Plugin(object):
    def __init__(self, argv):
        self.base = argv[0]
        self.handle = int(argv[1])
        self.params = dict(parse_qsl(argv[2].lstrip("?"))) if len(argv) > 2 else {}
        self.page_size = s_int("page_size", 60)
        self.thumb_size = s("thumb_size") or "tile_500"
        self.full_size = s("full_size") or "fit_1920"
        if not os.path.isdir(PROFILE):
            os.makedirs(PROFILE, exist_ok=True)
        user_dir = xbmcvfs.translatePath(s("cache_path")) if s("cache_path") else ""
        root, fell_back = resolve_dir(user_dir, PROFILE)
        if fell_back:
            log("Cache path %r not usable, falling back to %s" % (user_dir, root), xbmc.LOGWARNING)
            notify("Cache folder not writable - using add-on profile")
        self.cache = DiskCache(root, s_int("cache_max_mb", 500), s_int("cache_ttl_hours", 24),
                               s_bool("cache_enabled") if s("cache_enabled") else True)
        self.api = None

    # ---------- helpers ----------
    def url(self, **kw):
        return self.base + "?" + urlencode(kw)

    def _auth_fingerprint(self):
        return "|".join([s("server_url"), s("auth_mode"), s("username"),
                         str(hash(s("password") + s("token")))])

    def connect(self):
        if self.api:
            return self.api
        server = s("server_url").strip()
        if not server:
            raise AuthError("Set the PhotoPrism URL in settings")
        api = PhotoPrism(server, timeout=s_int("timeout", 15),
                         verify=s_bool("verify_ssl") if s("verify_ssl") else True)
        state_file = os.path.join(PROFILE, "session.json")
        fp = self._auth_fingerprint()
        try:
            with open(state_file) as fh:
                st = json.load(fh)
            if st.get("fp") == fp:
                api.restore(st)
                self.api = api
                return api
        except (OSError, ValueError):
            pass
        if s("auth_mode") == "1":
            tok = s("token").strip()
            if not tok:
                raise AuthError("Enter an app password / access token in settings")
            api.login_token(tok)
        else:
            if not s("username"):
                raise AuthError("Enter username and password in settings")
            api.login_password(s("username"), s("password"))
        st = api.state()
        st["fp"] = fp
        try:
            with open(state_file, "w") as fh:
                json.dump(st, fh)
            os.chmod(state_file, 0o600)
        except OSError:
            pass
        self.api = api
        return api

    def invalidate_session(self):
        try:
            os.remove(os.path.join(PROFILE, "session.json"))
        except OSError:
            pass
        self.api = None

    def cached_call(self, key, fn):
        data = self.cache.get_json(key)
        if data is not None:
            return data
        data = fn()
        self.cache.set_json(key, data)
        return data

    def thumb(self, key, remote):
        """Local cached path if present; otherwise remote URL (and queue for prefetch)."""
        p = self.cache.image_path(key)
        if p:
            return p
        self._prefetch.append((key, remote))
        return remote

    def run_prefetch(self):
        if not (self._prefetch and self.cache.enabled and
                (s_bool("prefetch") if s("prefetch") else True)):
            return
        jobs = list(self._prefetch)
        lock = threading.Lock()

        def worker():
            while True:
                with lock:
                    if not jobs:
                        return
                    key, url = jobs.pop()
                data = self.api.fetch_bytes(url)
                if data:
                    self.cache.put_image(key, data)

        threads = [threading.Thread(target=worker) for _ in range(max(1, s_int("prefetch_threads", 4)))]
        for t in threads:
            t.daemon = True
            t.start()
        for t in threads:
            t.join(60)
        self.cache.evict()

    def add_dir(self, label, url, thumb=None, folder=True):
        li = xbmcgui.ListItem(label)
        li.setArt({"icon": thumb or ICON, "thumb": thumb or ICON, "fanart": FANART})
        xbmcplugin.addDirectoryItem(self.handle, url, li, folder)

    # ---------- routes ----------
    def root(self):
        self.add_dir("Albums", self.url(action="albums", type="album"))
        self.add_dir("Folders", self.url(action="albums", type="folder"))
        self.add_dir("Moments", self.url(action="albums", type="moment"))
        self.add_dir("Calendar", self.url(action="albums", type="month"))
        self.add_dir("All photos", self.url(action="photos"))
        self.add_dir("Videos", self.url(action="photos", q="type:video"))
        self.add_dir("Favorites", self.url(action="photos", q="favorite:true"))
        self.add_dir("Search...", self.url(action="search"))
        self.add_dir("Slideshow: all photos", self.url(action="slideshow", q="type:image"), folder=False)
        self.add_dir("Clear cache", self.url(action="clear_cache"), folder=False)
        xbmcplugin.endOfDirectory(self.handle)

    def albums(self):
        api = self.connect()
        atype = self.params.get("type", "album")
        offset = int(self.params.get("offset", 0))
        key = "albums|%s|%s|%d|%d" % (api.base, atype, offset, self.page_size)
        res = self.cached_call(key, lambda: api.albums(self.page_size, offset, atype))
        items, rows = res["items"], res["rows"]
        more = rows >= self.page_size
        xbmcplugin.setContent(self.handle, "images")
        for a in items[:self.page_size]:
            uid = a.get("UID")
            title = a.get("Title") or uid
            n = a.get("PhotoCount")
            label = "%s (%s)" % (title, n) if n is not None else title
            art = self.thumb("album|%s|%s" % (uid, self.thumb_size),
                             api.album_cover_url(uid, self.thumb_size))
            li = xbmcgui.ListItem(label)
            li.setArt({"thumb": art, "icon": art, "fanart": FANART})
            li.addContextMenuItems([("Slideshow", "RunPlugin(%s)" % self.url(action="slideshow", album=uid))])
            xbmcplugin.addDirectoryItem(self.handle, self.url(action="photos", album=uid, title=title), li, True)
        if more:
            self.add_dir("[B]Next page >>[/B]", self.url(action="albums", type=atype, offset=offset + rows))
        xbmcplugin.endOfDirectory(self.handle, cacheToDisc=False)

    def _photo_query(self, offset, q, album, count):
        api = self.connect()
        key = "photos|%s|%s|%s|%d|%d" % (api.base, q, album, offset, count)
        return self.cached_call(key, lambda: api.photos(count, offset, q=q, album=album))

    def photos(self):
        api = self.connect()
        q = self.params.get("q", "")
        album = self.params.get("album", "")
        offset = int(self.params.get("offset", 0))
        flat = self.params.get("slideshow") == "1"
        if flat:  # slideshow: flat list of up to 1000 images, no navigation items
            items, batch, pos = [], 200, 0
            while len(items) < 1000:
                res = self._photo_query(pos, q, album, batch)
                items += res["items"]
                pos += res["rows"]
                if res["rows"] < batch or not res["items"]:
                    break
            rows, more = pos, False
        else:
            res = self._photo_query(offset, q, album, self.page_size)
            items, rows = res["items"], res["rows"]
            more = rows >= self.page_size and bool(items)
        xbmcplugin.setContent(self.handle, "images")
        if offset == 0 and items and not flat:
            self.add_dir("[I]> Slideshow[/I]", self.url(action="slideshow", q=q, album=album), folder=False)
        for p in items:
            h = p.get("Hash")
            if not h:
                continue
            title = api.title(p)
            art = self.thumb("t|%s|%s" % (h, self.thumb_size), api.thumb_url(h, self.thumb_size))
            is_video = p.get("Type") in ("video", "live", "animated")
            li = xbmcgui.ListItem(title)
            li.setArt({"thumb": art, "icon": art, "fanart": FANART})
            if is_video:
                tag = li.getVideoInfoTag()
                tag.setTitle(title)
                tag.setPlot(p.get("Description") or "")
                tag.setDuration(int((p.get("Duration") or 0) / 1e9))
                tag.setMediaType("video")
                li.setProperty("IsPlayable", "true")
                li.setMimeType("video/mp4")
                li.setContentLookup(False)
                plugin_url = self.url(action="play", hash=api.video_hash(p))
                xbmcplugin.addDirectoryItem(self.handle, plugin_url, li, False)
            else:
                url = self.image_url(h)
                taken = p.get("TakenAt") or ""
                if taken:
                    try:
                        li.getPictureInfoTag().setDateTimeTaken(taken.replace("Z", ""))
                    except (AttributeError, RuntimeError):
                        pass
                li.setMimeType("image/jpeg")
                xbmcplugin.addDirectoryItem(self.handle, url, li, False)
        if more:
            nxt = dict(self.params, action="photos", offset=offset + rows)
            self.add_dir("[B]Next page >>[/B]", self.url(**nxt))
        if not items:
            notify("No items found", error=False)
        xbmcplugin.endOfDirectory(self.handle, cacheToDisc=False)

    def image_url(self, h):
        if self.full_size == "original":
            return self.api.download_url(h)
        return self.api.thumb_url(h, self.full_size)

    def search(self):
        q = self.params.get("q")
        if not q:
            kb = xbmc.Keyboard("", "PhotoPrism search (e.g. label:cat year:2023)")
            kb.doModal()
            if not kb.isConfirmed() or not kb.getText().strip():
                xbmcplugin.endOfDirectory(self.handle, succeeded=False)
                return
            q = kb.getText().strip()
        self.params = {"q": q}
        self.photos()

    def play(self):
        api = self.connect()
        url = api.video_url(self.params["hash"], s("video_format") or "avc")
        li = xbmcgui.ListItem(path=url)
        li.setMimeType("video/mp4")
        li.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.handle, True, li)

    def slideshow(self):
        """Start Kodi's picture slideshow over a flat plugin listing (images only)."""
        q = self.params.get("q", "")
        if "type:" not in q:
            q = (q + " type:image").strip()
        xbmc.executebuiltin("SlideShow(%s)" % self.url(action="photos", q=q,
                            album=self.params.get("album", ""), slideshow="1"))

    def clear_cache(self):
        n = self.cache.clear()
        notify("Cache cleared (%d files)" % n, error=False)

    def dispatch(self):
        self._prefetch = []
        action = self.params.get("action")
        routes = {None: self.root, "albums": self.albums, "photos": self.photos,
                  "search": self.search, "play": self.play, "slideshow": self.slideshow,
                  "clear_cache": self.clear_cache}
        fn = routes.get(action)
        if fn is None:
            log("Unknown action %s" % action, xbmc.LOGWARNING)
            return
        try:
            try:
                fn()
            except AuthError:
                if self.api is None:
                    raise
                self.invalidate_session()  # stale token: retry once with fresh login
                self._prefetch = []
                fn()
        except AuthError as e:
            notify(str(e))
            self._fail(action)
        except ApiError as e:
            log("API error: %s" % e, xbmc.LOGERROR)
            notify(str(e))
            self._fail(action)
        else:
            if self.api:
                self.run_prefetch()

    def _fail(self, action):
        if action in ("albums", "photos", "search"):
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)
        elif action == "play":
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())


def run(argv):
    Plugin(argv).dispatch()
