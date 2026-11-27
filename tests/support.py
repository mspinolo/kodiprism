"""Shared test support: the fake PhotoPrism server, the plugin runner and the state helpers.

Importing it installs the fake Kodi modules (kodi_mocks) and starts the fake server once per test session.
`tests/conftest.py` resets every piece of shared state before each test, so tests can run alone or in any order.
"""
import json, os, socket, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests  # noqa: F401  (tests use requests.exceptions through this module)
from kodi_mocks import PROFILE, SETTINGS, LOG, KBCFG, SELECT, YESNO, LANG, WIN, ACTIVE, KODI_SETTINGS, RPC, MONITOR, ADDON_DIR  # noqa: F401

# ---- fake PhotoPrism ----
PHOTOS = [{"UID": "p%d" % i, "Hash": "h%d" % i, "Title": "Photo %d" % i,
           "Type": "video" if i == 1 else "image", "Duration": 5e9, "TakenAt": "2021-03-0%dT10:00:00Z" % (i + 1),
           "Width": 4000, "Height": 3000} for i in range(5)]
ALBUMS = [{"UID": "a%d" % i, "Title": "Album %d" % i, "PhotoCount": i, "Thumb": "ah%d" % i if i < 2 else "",
           "UpdatedAt": "2025-01-0%dT00:00:00Z" % (i + 1)} for i in range(3)]
# a0 is empty (no date); a1 / a2 have photos whose newest TakenAt is below
ALBUM_DATES = {"a1": "2020-05-01T10:00:00Z", "a2": "2021-06-01T10:00:00Z"}
BIG = [{"UID": u, "Title": t, "Location": loc, "PhotoCount": n, "Thumb": "bh" + u, "UpdatedAt": "2025-02-01T00:00:00Z"}
       for u, t, loc, n, d in [("b0", "Bretagna e Normandia", "Normandia", 115, "2008-08-02T10:00:00Z"),
                               ("b1", "Langhe", "Piemonte", 47, "2008-11-23T10:00:00Z"),
                               ("b2", "Café del Mar", "Ibiza", 10, "2015-07-01T10:00:00Z"),
                               ("b3", "Città di Roma", "Lazio", 22, "2019-03-10T10:00:00Z"),
                               ("b4", "Toscana", "Toscana", 42, "2009-12-07T10:00:00Z"),
                               ("b5", "Vuoto", "", 0, ""), ("b6", "Senza data", "", 5, "")]]
ALBUM_DATES.update({"b0": "2008-08-02T10:00:00Z", "b1": "2008-11-23T10:00:00Z", "b2": "2015-07-01T10:00:00Z",
                    "b3": "2019-03-10T10:00:00Z", "b4": "2009-12-07T10:00:00Z"})
HITS = {"session": 0, "photos": 0, "thumb": 0, "album_dates": 0, "albums_params": [], "photos_params": []}
MANY = [{"UID": "m%d" % i, "Hash": "mh%d" % i, "Title": "Many %d" % i, "Type": "image"} for i in range(1250)]
MODE = {"slow": False, "expire": False, "big": False, "dates_500": False, "many": False,
        "force": None, "status401": False, "expire_on_dates": False}
class H(BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def send(s, code, body, ct="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        try:
            s.send_response(code); s.send_header("Content-Type", ct); s.send_header("Content-Length", str(len(b))); s.end_headers(); s.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client gave up (the timeout test)
    def authed(s):
        t = s.headers.get("Authorization", "")
        return t in ("Bearer sess-tok", "Bearer app-pass") and not MODE["expire"]
    def do_POST(s):
        body = json.loads(s.rfile.read(int(s.headers["Content-Length"])))
        HITS["session"] += 1; MODE["expire"] = False
        if body["username"] == "admin" and body["password"] in ("pw", "S3cretPassw0rd"):
            s.send(200, {"id": "sid", "access_token": "sess-tok", "config": {"previewToken": "prev", "downloadToken": "dl", "version": "test-1.2"}})
        else: s.send(401, {"error": "Invalid credentials"})
    def do_GET(s):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(s.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if MODE["slow"]: time.sleep(5)
        HITS["ua"] = s.headers.get("User-Agent")
        if u.path.startswith("/api/v1/t/") or "/t/prev/" in u.path:
            HITS["thumb"] += 1
            return s.send(200, b"\xff\xd8JPEG" + u.path.encode(), "image/jpeg") if "/prev/" in u.path else s.send(403, {})
        if MODE["force"] and u.path == MODE["force"][0]: return s.send(*MODE["force"][1:])   # (path, code, body[, content type])
        if u.path == "/api/v1/status": return s.send(401, {}) if MODE["status401"] else s.send(200, {"status": "operational"})
        if not s.authed(): return s.send(401, {"error": "Unauthorized"})
        if u.path == "/api/v1/config": return s.send(200, {"previewToken": "prev", "downloadToken": "dl", "version": "test-1.2"})
        off, cnt = int(q.get("offset", 0)), int(q.get("count", 10))
        if u.path == "/api/v1/albums":
            HITS["albums_params"].append(q)
            return s.send(200, (BIG if MODE["big"] else ALBUMS)[off:off + cnt])
        if u.path == "/api/v1/photos" and q.get("s") and cnt == 1:      # "newest photo of this album"
            HITS["album_dates"] += 1
            if MODE["expire_on_dates"]:      # the session dies while the album dates are being read
                MODE["expire_on_dates"] = False; MODE["expire"] = True
                return s.send(401, {"error": "Unauthorized"})
            if MODE["dates_500"]: return s.send(500, {"error": "boom"})
            d = ALBUM_DATES.get(q["s"], "")
            return s.send(200, [{"Hash": "x", "TakenAt": d}] if d else [])
        if u.path == "/api/v1/photos":
            HITS["photos"] += 1
            HITS["photos_params"].append(q)
            items = MANY if MODE["many"] else PHOTOS
            if q.get("q") == "label:cat": items = PHOTOS[:1]
            if "type:image" in q.get("q", ""): items = [p for p in items if p["Type"] == "image"]
            return s.send(200, items[off:off + cnt])
        s.send(404, {})
srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
SETTINGS["server_url"] = "http://127.0.0.1:%d" % srv.server_port

from resources.lib import plugin, cache, api as api_mod, logger as logger_mod, catalog as cat, slideshow_fx as fx  # noqa: E402,F401

GOOD = "http://127.0.0.1:%d" % srv.server_port
LOGFILE = os.path.join(PROFILE, "debug.log")
STATE = os.path.join(PROFILE, "fx_restore.json")
_sk = socket.socket(); _sk.bind(("127.0.0.1", 0)); DEAD = _sk.getsockname()[1]; _sk.close()   # a port nobody listens on

# pristine copies, restored before every test by conftest.clean_state()
DEFAULT_SETTINGS = dict(SETTINGS)
DEFAULT_MODE = dict(MODE)
DEFAULT_KODI_SETTINGS = dict(KODI_SETTINGS)
DEFAULT_BIG = [dict(b) for b in BIG]


def check(c, msg):
    """One named check (kept from the script era so every failure says what was being verified)."""
    assert c, msg


def run(qs=""):
    for k in LOG: LOG[k].clear()
    plugin.run(["plugin://plugin.image.photoprism/", "1", qs])


def run_h(qs, handle):
    for k in LOG: LOG[k].clear()
    plugin.run(["plugin://plugin.image.photoprism/", str(handle), qs])


def reset(**kw):
    SETTINGS.update(server_url=GOOD, auth_mode="0", username="admin", password="pw", token="",
                    cache_path="", debug_log="false", verify_ssl="true", timeout="3", prefetch="true",
                    disable_pan_zoom="true", hide_empty_albums="false")
    SETTINGS.update(kw)
    for f in ("debug.log", "debug.log.1", "session.json"):
        try: os.remove(os.path.join(PROFILE, f))
        except OSError: pass


def read_log():
    return open(LOGFILE, encoding="utf-8").read() if os.path.exists(LOGFILE) else ""


def fresh(**kw):
    """New cache folder + defaults; the big album catalogue is served."""
    opts = dict(cache_path=tempfile.mkdtemp(), page_size="60", sort_order="0", slideshow_limit="2000")
    opts.update(kw)
    reset(**opts)
    MODE.update(big=True, dates_500=False, many=False, force=None, status401=False, expire_on_dates=False)
    HITS["album_dates"] = 0; HITS["albums_params"].clear(); HITS["photos_params"].clear()
    KBCFG.update(text="label:cat", ok=True); SELECT["value"] = 0


def labels(): return [i[0] for i in LOG["items"]]


# the timeout test above leaves a late "slowq" request in the fake server: ignore it
def PQ(): return [p for p in HITS["photos_params"] if p.get("q") != "slowq"]

def notes(): return " | ".join(LOG["notes"])

def kodi(**kw):
    KODI_SETTINGS.update({"slideshow.displayeffects": True}); RPC.update(calls=[], fail_get=False, fail_set=False); RPC.update(kw)
    WIN.clear(); ACTIVE["slideshow"] = False
    for f in ("fx_restore.json",):
        try: os.remove(os.path.join(PROFILE, f))
        except OSError: pass

__all__ = ["json", "os", "tempfile", "time", "requests", "PROFILE", "SETTINGS", "LOG", "KBCFG", "SELECT", "YESNO", "LANG",
           "WIN", "ACTIVE", "KODI_SETTINGS", "RPC", "MONITOR", "ADDON_DIR", "PHOTOS", "ALBUMS", "BIG", "HITS", "MODE", "srv",
           "plugin", "cache", "api_mod", "logger_mod", "cat", "fx", "GOOD", "LOGFILE", "STATE", "DEAD", "check", "run", "run_h",
           "reset", "read_log", "fresh", "labels", "PQ", "notes", "kodi"]
