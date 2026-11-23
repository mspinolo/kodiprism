# -*- coding: utf-8 -*-
"""Kodi plugin routing and UI for PhotoPrism."""
import hashlib
import json
import os
import threading

from typing import List, Optional, Tuple
from urllib.parse import urlencode, parse_qsl

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib import catalog
from resources.lib.api import PhotoPrism, ApiError, AuthError, normalize_base_url
from resources.lib.cache import DiskCache, resolve_dir
from resources.lib.logger import AddonLog

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
NAME = ADDON.getAddonInfo("name")
ICON = ADDON.getAddonInfo("icon")
FANART = ADDON.getAddonInfo("fanart")
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))


SLIDESHOW_ORDERS = ("newest", "oldest", "random")
ORDERS = SLIDESHOW_ORDERS + ("name", "added")


def notify(msg, error=True):
    xbmcgui.Dialog().notification(NAME, msg,
                                  xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_INFO,
                                  8000 if error else 5000)


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
        self.log = AddonLog(ADDON_ID, PROFILE, s_bool("debug_log"))
        self.log.add_secret(s("password"), s("token"))
        self.user_agent = "KodiPrism/%s" % (ADDON.getAddonInfo("version") or "dev")
        self.sort = {0: "newest", 1: "oldest", 2: "name"}.get(s_int("sort_order", 0), "newest")
        if not os.path.isdir(PROFILE):
            os.makedirs(PROFILE, exist_ok=True)
        user_dir = xbmcvfs.translatePath(s("cache_path")) if s("cache_path") else ""
        root, fell_back = resolve_dir(user_dir, PROFILE)
        if fell_back:
            self.log.warning("Cache path %r not usable, falling back to %s" % (user_dir, root))
            notify("Cache folder not writable - using add-on profile")
        self.cache = DiskCache(root, s_int("cache_max_mb", 500), s_int("cache_ttl_hours", 24),
                               s_bool("cache_enabled") if s("cache_enabled") else True)
        self.api: Optional[PhotoPrism] = None
        self._prefetch: List[Tuple[str, str]] = []

    # ---------- helpers ----------
    def url(self, **kw):
        return self.base + "?" + urlencode(kw)

    def _auth_fingerprint(self):
        # Must be stable across processes: the builtin hash() of str is salted per
        # interpreter start, which would invalidate session.json on every Kodi restart.
        secret = hashlib.sha256((s("password") + "\0" + s("token")).encode("utf-8")).hexdigest()
        return "|".join([s("server_url"), s("auth_mode"), s("username"), secret])

    def connect(self):
        if self.api:
            return self.api
        raw = s("server_url").strip()
        if not raw:
            raise AuthError("Set the PhotoPrism URL in settings")
        server = normalize_base_url(raw)
        if server != raw.rstrip("/"):
            self.log.info("Server address %r normalised to %r" % (raw, server))
        self.log.debug("Connecting to %s (login method: %s)" % (
            server, "app password" if s("auth_mode") == "1" else "username/password"))
        api = PhotoPrism(server, timeout=s_int("timeout", 15),
                         verify=s_bool("verify_ssl") if s("verify_ssl") else True,
                         log=self.log, user_agent=self.user_agent)
        state_file = os.path.join(PROFILE, "session.json")
        fp = self._auth_fingerprint()
        try:
            with open(state_file) as fh:
                st = json.load(fh)
            if st.get("fp") == fp:
                api.restore(st)
                self._register_secrets(api)
                self.log.debug("Reusing saved session")
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
            # Create with 0600 from the start (no window where the file is world-readable).
            fd = os.open(state_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump(st, fh)
            os.chmod(state_file, 0o600)  # also tighten a pre-existing file
        except OSError:
            pass
        self._register_secrets(api)
        self.api = api
        return api

    def _register_secrets(self, api):
        """Make sure session/preview/download tokens can never be written to a log."""
        self.log.add_secret(api.token, api.session_id, api.download_token)
        if api.preview_token != "public":  # "public" is a generic word, not a secret
            self.log.add_secret(api.preview_token)

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
        api = self.api
        if api is None or not (self._prefetch and self.cache.enabled and
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
                data = api.fetch_bytes(url)
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
        self.add_dir("Search albums...", self.url(action="search_albums"))
        self.add_dir("Search photos...", self.url(action="search"))
        self.add_dir("Slideshow: all photos", self.url(action="slideshow", q="type:image"), folder=False)
        self.add_dir("Clear cache", self.url(action="clear_cache"), folder=False)
        xbmcplugin.endOfDirectory(self.handle)

    def _progress_bg(self):
        """Lazy background progress dialog: only shown when there is real work to do."""
        state: dict = {"dlg": None}

        def update(done, total):
            dlg = state["dlg"]
            if dlg is None:
                dlg = state["dlg"] = xbmcgui.DialogProgressBG()
                dlg.create(NAME, "Reading album dates...")
            dlg.update(int(100.0 * done / max(total, 1)), message="%d / %d" % (done, total))

        def close():
            if state["dlg"] is not None:
                state["dlg"].close()
        return update, close

    def _add_album(self, api, a, date=""):
        uid = a.get("UID")
        title = a.get("Title") or uid
        n = a.get("PhotoCount")
        label = "%s (%s)" % (title, n) if n is not None else title
        cover = a.get("Thumb")
        if cover:
            # Same endpoint (and cache entry) as photo thumbnails, which is known to work.
            art = self.thumb("t|%s|%s" % (cover, self.thumb_size), api.thumb_url(cover, self.thumb_size))
        else:  # no cover photo recorded: fall back to the album-specific endpoint
            art = self.thumb("album|%s|%s" % (uid, self.thumb_size), api.album_cover_url(uid, self.thumb_size))
        li = xbmcgui.ListItem(label)
        if date:
            li.setLabel2(catalog.day(date))
        li.setArt({"thumb": art, "icon": art, "fanart": FANART})
        li.addContextMenuItems([("Slideshow", "RunPlugin(%s)" % self.url(action="slideshow", album=uid))])
        xbmcplugin.addDirectoryItem(self.handle, self.url(action="photos", album=uid, title=title), li, True)

    def albums(self):
        api = self.connect()
        atype = self.params.get("type", "album")
        offset = int(self.params.get("offset", 0))
        xbmcplugin.setContent(self.handle, "images")
        if atype == "album":
            return self._album_catalogue(api, offset)
        # Folders / moments / calendar months have their own dates: let the server sort and page.
        key = "albums|%s|%s|%s|%d|%d" % (api.base, atype, self.sort, offset, self.page_size)
        res = self.cached_call(key, lambda: api.albums(self.page_size, offset, atype, order=self.sort))
        items, rows = res["items"], res["rows"]
        more = rows >= self.page_size
        for a in items[:self.page_size]:
            self._add_album(api, a)
        if more:
            self.add_dir("[B]Next page >>[/B]", self.url(action="albums", type=atype, offset=offset + rows))
        xbmcplugin.endOfDirectory(self.handle, cacheToDisc=False)

    def _album_catalogue(self, api, offset):
        """Albums: loaded completely, searched/sorted/paged locally (see catalog.py)."""
        q = self.params.get("q", "").strip()
        albums = catalog.load_all(api, "album")
        dates = {}
        if self.sort != "name":
            update, close = self._progress_bg()
            try:
                dates = catalog.last_photo_dates(api, self.cache, albums, self.log, progress=update,
                                                 max_age=s_int("cache_ttl_hours", 24) * 3600)
            finally:
                close()
        shown = [a for a in albums if catalog.matches(a, q)] if q else albums
        ordered = catalog.sort_albums(shown, dates, self.sort)
        page = ordered[offset:offset + self.page_size]
        if q:
            xbmcplugin.setPluginCategory(self.handle, "Search: %s" % q)
        elif offset == 0:
            self.add_dir("Search albums...", self.url(action="search_albums"))
        for a in page:
            self._add_album(api, a, dates.get(a["UID"], ""))
        if offset + self.page_size < len(ordered):
            nxt = {"action": "albums", "type": "album", "offset": offset + self.page_size}
            if q:
                nxt["q"] = q
            self.add_dir("[B]Next page >>[/B]", self.url(**nxt))
        if not ordered:
            notify("No albums found" if q else "No albums", error=False)
        xbmcplugin.endOfDirectory(self.handle, cacheToDisc=False)

    def search_albums(self):
        kb = xbmc.Keyboard("", "Search albums (title or place)")
        kb.doModal()
        if not kb.isConfirmed() or not kb.getText().strip():
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)
            return
        self.params = {"action": "albums", "type": "album", "q": kb.getText().strip()}
        self.albums()

    def _photo_query(self, offset, q, album, count, order=None):
        api = self.connect()
        order = order or self.sort
        if order == "random":  # every call must give a new draw: never cached
            return api.photos(count, offset, q=q, album=album, order=order)
        key = "photos|%s|%s|%s|%s|%d|%d" % (api.base, q, album, order, offset, count)
        return self.cached_call(key, lambda: api.photos(count, offset, q=q, album=album, order=order))

    def photos(self):
        api = self.connect()
        q = self.params.get("q", "")
        album = self.params.get("album", "")
        offset = int(self.params.get("offset", 0))
        flat = self.params.get("slideshow") == "1"
        order = self.params.get("order")
        if order not in ORDERS:
            order = self.sort
        if flat:  # slideshow: flat list of up to `slideshow_limit` images, no navigation items
            limit = s_int("slideshow_limit", 2000)
            items: list = []
            if order == "random":  # successive random draws would overlap: ask for everything at once
                res = self._photo_query(0, q, album, limit, order)
                items, pos = res["items"], res["rows"]
            else:
                pos = 0
                while len(items) < limit:
                    n = min(500, limit - len(items))
                    res = self._photo_query(pos, q, album, n, order)
                    items += res["items"]
                    pos += res["rows"]
                    if res["rows"] < n or not res["items"]:
                        break
            items = items[:limit]
            rows, more = pos, False
        else:
            res = self._photo_query(offset, q, album, self.page_size, order)
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
        api = self.connect()
        if self.full_size == "original":
            return api.download_url(h)
        return api.thumb_url(h, self.full_size)

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
        """Ask for the order, then start Kodi's picture slideshow over a flat plugin listing."""
        order = self.params.get("order")
        if order not in SLIDESHOW_ORDERS:
            choice = xbmcgui.Dialog().select("Slideshow order", ["Newest first", "Oldest first", "Random"])
            if choice < 0:  # cancelled
                return
            order = SLIDESHOW_ORDERS[choice]
        q = self.params.get("q", "")
        if "type:" not in q:
            q = (q + " type:image").strip()
        url = self.url(action="photos", q=q, album=self.params.get("album", ""), slideshow="1", order=order)
        self.log.info("Starting slideshow: order=%s album=%s q=%s" % (order, self.params.get("album", ""), q))
        # An explicit [not]random flag keeps Kodi's global "Randomise" setting from overriding the choice.
        xbmc.executebuiltin("SlideShow(%s,%s)" % (url, "random" if order == "random" else "notrandom"))

    def clear_cache(self):
        n = self.cache.clear()
        notify("Cache cleared (%d files)" % n, error=False)

    def test_connection(self):
        """Step-by-step connection check shown in a text viewer. Uses the *saved* settings."""
        lines = []

        def step(ok, text):
            lines.append("[%s] %s" % ("OK  " if ok else "FAIL", text))
            self.log.info("test_connection: %s" % lines[-1])

        raw = s("server_url").strip()
        lines.append("Server address entered: %s" % (raw or "(empty)"))
        passed = False
        try:
            base = normalize_base_url(raw)
            step(True, "Address used: %s%s" % (base, "" if base == raw else "  (corrected automatically)"))
            api = PhotoPrism(base, timeout=s_int("timeout", 15),
                             verify=s_bool("verify_ssl") if s("verify_ssl") else True,
                             log=self.log, user_agent=self.user_agent)
            try:
                ms, body = api.ping()
                step(True, "Server reachable in %d ms (status: %s)" % (ms, body.strip() or "empty reply"))
            except AuthError:
                step(True, "Server reachable (its status page asks for a login)")
            if s("auth_mode") == "1":
                if not s("token").strip():
                    raise AuthError("No app password / access token entered in settings")
                cfg = api.login_token(s("token").strip())
                who = "App password / access token accepted"
            else:
                if not s("username"):
                    raise AuthError("No username entered in settings")
                cfg = api.login_password(s("username"), s("password")).get("config") or {}
                who = "Logged in as '%s'" % s("username")
            self._register_secrets(api)
            step(True, who)
            if cfg.get("version"):
                step(True, "PhotoPrism version: %s" % cfg.get("version"))
            api.albums(count=1)
            api.photos(count=1)
            step(True, "Library readable (albums and photos queries answered)")
            passed = True
        except ApiError as e:
            step(False, str(e))
        lines.append("")
        if passed:
            lines.append("All checks passed. If browsing still fails, enable debug logging in")
            lines.append("Troubleshooting, retry, then open 'View add-on log'.")
        else:
            lines.append("Fix the first [FAIL] line above and run the test again.")
            lines.append("More detail: Settings > Troubleshooting > View add-on log.")
        lines.append("")
        lines.append("This test uses the saved settings: press OK in the settings dialog first.")
        xbmcgui.Dialog().textviewer("PhotoPrism - connection test", "\n".join(lines))

    def show_log(self):
        header = ["Add-on log: %s" % self.log.path,
                  "Kodi log:   %s   (search for [%s])" % (xbmcvfs.translatePath("special://logpath/kodi.log"), ADDON_ID),
                  "Debug logging: %s" % ("ON" if self.log.debug_enabled
                                         else "OFF - turn it on in Troubleshooting to record every request"),
                  "Newest entries are at the bottom.", "-" * 40]
        xbmcgui.Dialog().textviewer("PhotoPrism - add-on log",
                                    "\n".join(header) + "\n" + (self.log.tail(150) or "(the log is empty)\n"))

    def clear_log(self):
        self.log.clear()
        notify("Add-on log cleared", error=False)

    def dispatch(self):
        self._prefetch = []
        action = self.params.get("action")
        routes = {None: self.root, "albums": self.albums, "photos": self.photos,
                  "search": self.search, "search_albums": self.search_albums, "play": self.play,
                  "slideshow": self.slideshow,
                  "clear_cache": self.clear_cache, "test_connection": self.test_connection,
                  "show_log": self.show_log, "clear_log": self.clear_log}
        fn = routes.get(action)
        if fn is None:
            self.log.warning("Unknown action %s" % action)
            return
        self.log.debug("action=%s params=%s" % (action, self.params))
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
            self.log.warning("Action %s: %s" % (action, e))
            notify(str(e))
            self._fail(action)
        except ApiError as e:
            self.log.error("Action %s failed: %s" % (action, e))
            notify(str(e))
            self._fail(action)
        except Exception:
            self.log.exception("Unexpected error in action %r" % action)
            notify("Unexpected error - see Settings > Troubleshooting > View add-on log")
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
