import json, os, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from kodi_mocks import PROFILE, SETTINGS, LOG, KBCFG, SELECT, YESNO, LANG, WIN, ACTIVE, KODI_SETTINGS, RPC, MONITOR, ADDON_DIR

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

from resources.lib import plugin, cache
def run(qs=""):
    for k in LOG: LOG[k].clear()
    plugin.run(["plugin://plugin.image.photoprism/", "1", qs])
ok = 0
def check(c, msg):
    global ok
    assert c, msg; ok += 1; print("PASS", msg)

run(""); check(len(LOG["items"]) == 14 and LOG["end"] == [True], "root menu")
run("?action=albums&type=album")
check(HITS["session"] == 1, "password login via POST /session")
check([i[0] for i in LOG["items"]] == ["Search albums...", "Album 2 (2)", "Album 1 (1)", "[B]Next page >>[/B]"],
      "albums: newest-first by last photo date, search entry on top, pagination")
check("/api/v1/t/ah1/prev/tile_500" in LOG["items"][2][2], "album cover uses the album's Thumb hash with the normal thumbnail endpoint")
check("/api/v1/albums/a2/t/prev/tile_500" in LOG["items"][1][2], "album without Thumb falls back to the album cover endpoint")
run("?action=albums&type=album&offset=2")   # page 2 holds the empty album a0 (undated, last)
check([i[0] for i in LOG["items"]] == ["Album 0 (0)"] and "/api/v1/t/ah0/prev/tile_500" in LOG["items"][0][2], "second album page: empty album last")
time.sleep(0.3)
run("?action=albums&type=album")
check(HITS["session"] == 1, "session reused from profile")
check(LOG["items"][1][2].startswith(PROFILE), "thumbnail served from disk cache after prefetch")
run("?action=photos&offset=2")
labels = [i[0] for i in LOG["items"]]
check(labels == ["Photo 2", "Photo 3", "[B]Next page >>[/B]"] and "offset=4" in LOG["items"][-1][1], "photo page 2")
run("?action=photos")
vid = [i for i in LOG["items"] if i[0] == "Photo 1"][0]
check("action=play" in vid[1] and vid[3] is False, "video item is playable plugin url")
img = [i for i in LOG["items"] if i[0] == "Photo 0"][0]
check(img[1].endswith("/api/v1/t/h0/prev/fit_1920"), "image full-size url")
n = HITS["photos"]; run("?action=photos"); check(HITS["photos"] == n, "metadata served from cache")
run("?action=play&hash=h1"); check(LOG["resolved"] == [(True, SETTINGS["server_url"] + "/api/v1/videos/h1/prev/avc")], "video endpoint resolved")
run("?action=search"); check([i[0] for i in LOG["items"]][-1] == "Photo 0" and len(LOG["items"]) == 2, "search via keyboard (label:cat)")
run("?action=slideshow&album=a1"); check("SlideShow(" in LOG["builtin"][0] and "slideshow=1" in LOG["builtin"][0], "slideshow builtin")
run("?" + LOG["builtin"][0][len("SlideShow(plugin://plugin.image.photoprism/?"):-1] if False else "?action=photos&q=type%3Aimage&slideshow=1")
check(len(LOG["items"]) == 4 and all("Next" not in i[0] and "Slideshow" not in i[0] for i in LOG["items"]), "flat slideshow list, images only")
MODE["expire"] = True; run("?action=albums&type=moment")
check(HITS["session"] == 2 and LOG["end"] == [True], "expired session -> transparent re-login")
SETTINGS.update(auth_mode="1", token="app-pass"); run("?action=albums&type=folder")
check(LOG["end"] == [True] and HITS["session"] == 2, "app password auth (no /session call)")
SETTINGS["token"] = "bad"; run("?action=albums&type=month")
check(LOG["end"] == [False] and any("Authentication" in n for n in LOG["notes"]), "bad token -> notification")
SETTINGS.update(auth_mode="0", password="wrong"); run("?action=albums&type=album")
check(LOG["end"] == [False] and LOG["notes"], "bad password -> notification")
SETTINGS["password"] = "pw"; run("?action=photos&q=x"); MODE["slow"] = True
run("?action=photos&q=slowq"); MODE["slow"] = False
check(any("Timeout" in n for n in LOG["notes"]) and LOG["end"] == [False], "timeout -> notification")
SETTINGS["server_url"] = "http://127.0.0.1:1"; SETTINGS["username"] = "other"; run("?action=albums")
check(any("Connection refused by 127.0.0.1:1" in n for n in LOG["notes"]), "unreachable server -> clear notification")

# cache location
custom = tempfile.mkdtemp(); SETTINGS["cache_path"] = custom; run("")
check(os.path.isdir(os.path.join(custom, "photoprism_cache", "img")), "custom cache folder used")
SETTINGS["cache_path"] = "/proc/nope"; run("")
check(any("not writable" in n for n in LOG["notes"]), "invalid cache folder -> fallback + notify")
ro = tempfile.mkdtemp(); os.chmod(ro, 0o500)
r, fb = cache.resolve_dir(ro, PROFILE)
if os.geteuid() != 0: check(fb, "read-only folder rejected")
else: print("SKIP read-only check (running as root)")
# LRU + TTL
d = tempfile.mkdtemp(); c = cache.DiskCache(d, max_mb=1, ttl_hours=1)
for i in range(6): c.put_image("k%d" % i, b"x" * 300000); os.utime(c._path("img", "k%d" % i, ".jpg"), (1000 + i, time.time()))
c.image_path("k0")  # touch -> most recent
c.evict(); kept = [i for i in range(6) if os.path.exists(c._path("img", "k%d" % i, ".jpg"))]
check(c.size() <= 1024 * 1024 and 0 in kept and 1 not in kept, "LRU eviction keeps recently used (kept %s)" % kept)
c.set_json("m", {"a": 1}); pth = c._path("meta", "m", ".json"); os.utime(pth, (time.time(), time.time() - 7200))
check(c.get_json("m") is None and not os.path.exists(pth), "TTL expiry")
check(c.clear() > 0 and c.size() == 0, "clear cache")
SETTINGS["cache_path"] = ""; run("?action=clear_cache"); check(any("Cache cleared" in n for n in LOG["notes"]), "clear-cache action")
# ---- regression tests (1.0.1) ----
# 1) auth fingerprint must not depend on per-process hash randomisation
snippet = ("import sys; sys.path.insert(0, %r); import kodi_mocks; kodi_mocks.SETTINGS.update(password='pw');"
           "from resources.lib import plugin; print(plugin.Plugin(['plugin://x/', '1', ''])._auth_fingerprint())"
           % os.path.dirname(os.path.abspath(__file__)))
fps = [subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True,
                      env=dict(os.environ, PYTHONHASHSEED=seed)).stdout.strip() for seed in ("1", "2")]
check(fps[0] and fps[0] == fps[1] and "pw" not in fps[0], "auth fingerprint stable across processes, no plaintext secret")
# 2) session file is private
SETTINGS.update(server_url="http://127.0.0.1:%d" % srv.server_port, auth_mode="0", username="admin", password="pw", token="", cache_path="")
sess = os.path.join(PROFILE, "session.json")
if os.path.exists(sess): os.remove(sess)
run("?action=albums&type=album")
check(os.path.exists(sess) and (os.stat(sess).st_mode & 0o777) == 0o600, "session.json created with mode 0600")
# 3) eviction must only drop *.tmp files by name, not everything under a path containing '.tmp'
d = os.path.join(tempfile.mkdtemp(), ".tmpcache"); c = cache.DiskCache(d, max_mb=50, ttl_hours=24)
c.put_image("keep", b"x" * 100); stale = os.path.join(d, "img", "abc.jpg.tmp123"); open(stale, "wb").write(b"y")
c.evict()
check(c.image_path("keep") is not None and not os.path.exists(stale), "evict keeps live files under a '.tmp' path, drops leftover tmp files")
# ---- diagnostics (1.0.2) ----
import socket
import requests
from resources.lib import api as api_mod, logger as logger_mod
GOOD = "http://127.0.0.1:%d" % srv.server_port
LOGFILE = os.path.join(PROFILE, "debug.log")
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); DEAD = sk.getsockname()[1]; sk.close()   # a port nobody listens on


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


# 1) address normalisation
n = api_mod.normalize_base_url
check(n("192.168.1.10:2342") == "http://192.168.1.10:2342" and n("  http://h:2342/ ") == "http://h:2342"
      and n("https://foto.lan/api/v1/") == "https://foto.lan" and n("HTTPS://Foto.lan:8443/photos/") == "https://Foto.lan:8443/photos",
      "address normalisation: scheme added, spaces/slash/'/api/v1' removed, sub-path kept")
rejected = 0
for u in ("", "   ", "ftp://h", "http://", "http://h:abc", "http://admin:pw@h:2342"):
    try: n(u)
    except api_mod.ApiError: rejected += 1
check(rejected == 6, "unusable addresses (empty, ftp, no host, bad port, embedded credentials) are rejected")

# 2) error kinds -> clear messages
R = requests.exceptions
fe = lambda e: api_mod.friendly_error(e, "http://foto.lan:2342", 7)
cases = [(R.ConnectionError("Failed to establish a new connection: [Errno 111] Connection refused"), "refused by foto.lan:2342"),
         (R.ConnectionError("Failed to resolve 'foto.lan' ([Errno -2] Name or service not known)"), "Cannot resolve host name 'foto.lan'"),
         (R.ConnectionError("[Errno 113] No route to host"), "unreachable"),
         (R.ConnectionError("('Connection aborted.', RemoteDisconnected('Remote end closed connection'))"), "closed the connection"),
         (R.SSLError("[SSL: WRONG_VERSION_NUMBER] wrong version number"), "does not speak HTTPS"),
         (R.SSLError("CERTIFICATE_VERIFY_FAILED self-signed certificate"), "Verify TLS certificates"),
         (R.ConnectTimeout("timed out"), "Timeout after 7s"), (R.ReadTimeout("timed out"), "Timeout after 7s"),
         (R.MissingSchema("Invalid URL"), "Invalid server address"),
         (R.ChunkedEncodingError("x"), "failed (ChunkedEncodingError)")]
wrong = [(type(e).__name__, want, fe(e)) for e, want in cases if want not in fe(e)]
check(not wrong, "friendly_error: %d failure kinds -> clear messages %s" % (len(cases), wrong or ""))
try: api_mod.PhotoPrism("127.0.0.1:%d" % DEAD, timeout=3).ping(); msg = ""
except api_mod.ApiError as e: msg = str(e)
check("Connection refused by 127.0.0.1:%d" % DEAD in msg, "real closed port (address typed without http://) -> '%s'" % msg)
ms, body = api_mod.PhotoPrism(GOOD).ping()
check(isinstance(ms, int) and "operational" in body, "ping() reaches /api/v1/status without credentials")
a = api_mod.PhotoPrism(GOOD); a.login_password("admin", "pw")
try: a._req("GET", "/nothing"); msg = ""
except api_mod.ApiError as e: msg = str(e)
check(msg.startswith("Not found (404) for /nothing"), "HTTP 404 -> hint that the address may not be PhotoPrism")
try: api_mod.PhotoPrism(GOOD).login_password("admin", "bad"); msg = ""
except api_mod.AuthError as e: msg = str(e)
check(msg.startswith("Authentication failed (401)") and "username/password" in msg, "HTTP 401 -> authentication hint")

# 3) logger: secrets, levels, rotation
lg = logger_mod.AddonLog("x", tempfile.mkdtemp(), debug=True); lg.add_secret("S3cretPW", "tok-12345")
red = lg.redact("GET http://h/api/v1/t/abc123/PREVTOKEN/tile_500 /albums/a1/t/PREVTOKEN/tile_224 /videos/h1/PREVTOKEN/avc "
                "/dl/h1?t=DLTOKEN pw=S3cretPW Bearer tok-12345")
check(not any(x in red for x in ("PREVTOKEN", "DLTOKEN", "S3cretPW", "tok-12345")) and "abc123" in red and "tile_500" in red,
      "redaction masks tokens/secrets but keeps hashes and sizes: %s" % red)
lg = logger_mod.AddonLog("x", tempfile.mkdtemp(), debug=False); lg.debug("hidden-line"); lg.info("shown-line")
check("hidden-line" not in lg.tail() and " INFO " in lg.tail() and "shown-line" in lg.tail(), "DEBUG lines are dropped unless debug logging is on")
lg.debug_enabled = True; lg.debug("now-visible"); check("now-visible" in lg.tail(), "DEBUG lines recorded when enabled")
for _ in range(300): lg.info("x" * 1000)
check(os.path.exists(lg.path + ".1") and os.path.getsize(lg.path) <= logger_mod.MAX_BYTES + 2000, "log file rotates at 256 KB")
lg.clear(); check(not os.path.exists(lg.path) and not os.path.exists(lg.path + ".1"), "clear() removes the log files")

# 4) test-connection action
reset(); run("?action=test_connection"); txt = LOG["text"][-1][1]
check("[FAIL]" not in txt and "Server reachable in" in txt and "Logged in as 'admin'" in txt and "PhotoPrism version: test-1.2" in txt
      and "Library readable" in txt and "All checks passed" in txt, "test connection: everything OK")
reset(password="wrong"); run("?action=test_connection"); txt = LOG["text"][-1][1]
check("Server reachable" in txt and "[FAIL] Authentication failed (401)" in txt and "All checks passed" not in txt, "test connection: reachable but wrong password")
reset(server_url="127.0.0.1:%d" % DEAD); run("?action=test_connection"); txt = LOG["text"][-1][1]
check("corrected automatically" in txt and "[FAIL] Connection refused by 127.0.0.1:%d" % DEAD in txt, "test connection: typo'd port, address auto-corrected")
reset(server_url=""); run("?action=test_connection"); txt = LOG["text"][-1][1]
check("[FAIL] Server address is empty" in txt, "test connection: empty address")
reset(auth_mode="1", token=""); run("?action=test_connection"); txt = LOG["text"][-1][1]
check("[FAIL] No app password" in txt, "test connection: app-password mode without token")

# 5) browsing with an address typed without http://
reset(server_url="127.0.0.1:%d" % srv.server_port); run("?action=albums&type=album")
check(LOG["end"] == [True] and "normalised" in read_log(), "browsing works with 'host:port' typed without http:// (normalisation logged)")

# 6) end-to-end: debug logging must never leak a secret
reset(debug_log="true", password="S3cretPassw0rd", cache_path=tempfile.mkdtemp())
for q in ("", "?action=albums&type=album", "?action=photos", "?action=play&hash=h1", "?action=slideshow&album=a1", "?action=test_connection"):
    run(q)
time.sleep(0.6)  # let the prefetch threads finish
logtxt = read_log()
check("S3cretPassw0rd" not in logtxt and "sess-tok" not in logtxt and "/prev/" not in logtxt, "full debug session: no password, session token or preview token in debug.log")
check("GET /albums" in logtxt and "-> HTTP 200 (" in logtxt and "/t/h0/***/" in logtxt and "Logged in as 'admin'" in logtxt,
      "debug log has one line per request with status and timing (tokens masked)")
reset(debug_log="true", auth_mode="1", token="app-pass"); run("?action=albums&type=album")
check("app-pass" not in read_log() and "app-pass" not in " ".join(m for _, m in LOG["klog"]), "app password never logged (debug.log and kodi.log)")
check(any(m.startswith("[plugin.image.photoprism]") for _, m in LOG["klog"]), "messages also go to kodi.log with the add-on id prefix")

# 6b) defence in depth: even a *deliberate* slip must be masked (password, app password, session token)
reset(debug_log="true", password="S3cretPassw0rd", token="tokenvalue123", cache_path=tempfile.mkdtemp())
pl = plugin.Plugin(["plugin://plugin.image.photoprism/", "1", ""]); pl.connect()
pl.log.info("accidental slip: S3cretPassw0rd tokenvalue123 sess-tok")
lt = read_log()
check("accidental slip" in lt and not any(x in lt for x in ("S3cretPassw0rd", "tokenvalue123", "sess-tok")),
      "configured password, app password and session token are masked even if logged by mistake")

# 7) in-Kodi log viewer and clear
reset(debug_log="true", auth_mode="0", password="pw"); run("?action=albums&type=album"); run("?action=show_log")
h, t = LOG["text"][-1]
check("Add-on log:" in t and "kodi.log" in t and "Debug logging: ON" in t and "Logged in as 'admin'" in t, "View add-on log shows header and entries")
run("?action=clear_log"); check(not os.path.exists(LOGFILE) and any("cleared" in m for m in LOG["notes"]), "Clear add-on log")
reset(); run("?action=show_log"); check("(the log is empty)" in LOG["text"][-1][1] and "Debug logging: OFF" in LOG["text"][-1][1], "empty log message, debug OFF shown")

# 8) unexpected exceptions are logged with a traceback and shown as a notification
orig_albums = plugin.Plugin.albums
def boom(self): raise RuntimeError("kaboom")
plugin.Plugin.albums = boom
reset(); run("?action=albums&type=album")
plugin.Plugin.albums = orig_albums
check(LOG["end"] == [False] and any("Unexpected error" in m for m in LOG["notes"]) and "RuntimeError: kaboom" in read_log() and "Traceback" in read_log(),
      "unexpected exception -> notification + traceback in log + failed directory")

# ---- 1.1.0: album catalogue, ordering, search, slideshow ----
from resources.lib import catalog as cat


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


# pure functions
check(cat.fold("Café Città") == "cafe citta", "fold: accents and case ignored")
cafe = {"Title": "Café del Mar", "Location": "Ibiza"}
check(cat.matches(cafe, "CAFE mar") and cat.matches(cafe, "ibiza") and not cat.matches(cafe, "roma") and cat.matches(cafe, ""),
      "search matches every word in title or place, ignoring case and accents")
al = [{"UID": "x", "Title": "B"}, {"UID": "y", "Title": "A"}, {"UID": "z", "Title": "C"}, {"UID": "w", "Title": "D"}]
dt = {"x": "2020-01-01T00:00:00Z", "y": "2020-01-01T00:00:00Z", "z": "2019-01-01T00:00:00Z", "w": ""}
ids = lambda mode: [a["UID"] for a in cat.sort_albums(al, dt, mode)]
check(ids("newest") == ["y", "x", "z", "w"] and ids("oldest") == ["z", "y", "x", "w"] and ids("name") == ["y", "x", "z", "w"],
      "sort: ties broken by name, undated albums last in both directions")

# newest first, dates, progress, cache
fresh(); run("?action=albums&type=album")
check(labels() == ["Search albums...", "Città di Roma (22)", "Café del Mar (10)", "Toscana (42)", "Langhe (47)",
                   "Bretagna e Normandia (115)", "Senza data (5)", "Vuoto (0)"], "albums newest first by date of the last photo, undated last: %s" % labels())
check(LOG["items"][1][4] == "2019-03-10" and LOG["items"][7][4] == "", "each album shows the date of its last photo (label2)")
check(HITS["album_dates"] == 6 and LOG["progress"][0] == "create" and LOG["progress"][-1] == "close",
      "one date lookup per non-empty album (6), with a background progress dialog")
run("?action=albums&type=album")
check(HITS["album_dates"] == 6 and LOG["progress"] == [], "second load: dates come from the cache (no requests, no progress dialog)")
BIG[2]["UpdatedAt"] = "2025-03-01T00:00:00Z"        # one album changed on the server
run("?action=albums&type=album")
check(HITS["album_dates"] == 7, "only the album whose UpdatedAt changed is looked up again")

# other sort modes
fresh(sort_order="1"); run("?action=albums&type=album")
check(labels()[1:] == ["Bretagna e Normandia (115)", "Langhe (47)", "Toscana (42)", "Café del Mar (10)", "Città di Roma (22)",
                       "Senza data (5)", "Vuoto (0)"], "sort oldest first: %s" % labels())
fresh(sort_order="2"); run("?action=albums&type=album")
check(labels()[1:] == ["Bretagna e Normandia (115)", "Café del Mar (10)", "Città di Roma (22)", "Langhe (47)", "Senza data (5)",
                       "Toscana (42)", "Vuoto (0)"] and HITS["album_dates"] == 0, "sort by name needs no date lookups")

# search albums
fresh(); KBCFG["text"] = "cafe"; run("?action=search_albums")
check(labels() == ["Café del Mar (10)"] and ("category", "Search: cafe") in LOG["text"] and LOG["end"] == [True], "search albums: 'cafe' finds 'Café del Mar'")
KBCFG["text"] = "piemonte"; run("?action=search_albums"); check(labels() == ["Langhe (47)"], "search albums also matches the place")
KBCFG["text"] = "zzz"; run("?action=search_albums")
check(labels() == [] and any("No albums found" in n for n in LOG["notes"]) and LOG["end"] == [True], "search albums: no result -> message, empty list")
KBCFG["ok"] = False; run("?action=search_albums"); check(LOG["end"] == [False] and labels() == [], "search albums cancelled -> nothing listed")
run("?action=albums&type=album&q=roma"); check(labels() == ["Città di Roma (22)"], "albums list accepts q= directly (used by 'Next page')")

# local pagination
fresh(page_size="3"); run("?action=albums&type=album")
check(labels() == ["Search albums...", "Città di Roma (22)", "Café del Mar (10)", "Toscana (42)", "[B]Next page >>[/B]"]
      and "offset=3" in LOG["items"][-1][1], "albums page 1 of 3 with Next")
run("?action=albums&type=album&offset=6")
check(labels() == ["Vuoto (0)"], "albums last page has no Next and no search entry")

# server-side ordering for the other album types and for photos
for so, want in (("0", "newest"), ("1", "oldest"), ("2", "name")):
    fresh(sort_order=so); run("?action=albums&type=moment")
    p1 = HITS["albums_params"][-1]
    run("?action=photos")
    p2 = PQ()[-1]
    check(p1["order"] == want and p1["type"] == "moment" and p2["order"] == want, "sort setting %s -> server order '%s' for moments and photos" % (so, want))

# slideshow prompt
fresh(); SELECT["value"] = 1; run("?action=slideshow&album=b0")
b = LOG["builtin"][0] if LOG["builtin"] else ""
check(LOG["selects"][0][1] == ["Newest first", "Oldest first", "Random"] and b.startswith("SlideShow(") and "order=oldest" in b
      and "album=b0" in b and "slideshow=1" in b and b.endswith(",notrandom)"), "slideshow asks the order; oldest -> notrandom: %s" % b)
SELECT["value"] = 2; run("?action=slideshow")
check("order=random" in LOG["builtin"][0] and LOG["builtin"][0].endswith(",random)"), "slideshow: random")
SELECT["value"] = -1; run("?action=slideshow"); check(LOG["builtin"] == [], "slideshow cancelled -> nothing starts")
run("?action=slideshow&order=newest"); check(LOG["selects"] == [] and "order=newest" in LOG["builtin"][0], "slideshow with an explicit order does not ask")

# flat slideshow listing: order, limit, random
fresh(); run("?action=photos&slideshow=1&order=oldest&q=type%3Aimage")
check(len(LOG["items"]) == 4 and PQ()[-1]["order"] == "oldest" and PQ()[-1]["count"] == "500", "slideshow list: 4 images, oldest first, batch of 500")
fresh(slideshow_limit="2"); run("?action=photos&slideshow=1&order=newest&q=type%3Aimage")
check(len(LOG["items"]) == 2 and PQ()[-1]["count"] == "2", "slideshow limit is respected")
fresh(); MODE["many"] = True; run("?action=photos&slideshow=1&order=newest&q=type%3Aimage")
check(len(LOG["items"]) == 1250 and len(PQ()) == 3, "1250 photos are read in 3 batches (500 + 500 + 250)")
fresh(slideshow_limit="1000"); MODE["many"] = True; run("?action=photos&slideshow=1&order=newest&q=type%3Aimage")
check(len(LOG["items"]) == 1000 and len(PQ()) == 2, "limit 1000 stops after 2 batches")
fresh(slideshow_limit="2000"); run("?action=photos&slideshow=1&order=random&q=type%3Aimage"); run("?action=photos&slideshow=1&order=random&q=type%3Aimage")
rp = PQ()
check(len(rp) == 2 and all(p["order"] == "random" and p["count"] == "2000" for p in rp), "random slideshow: one request for the whole limit, never cached")

# a failing date lookup must not break the list, and is retried next time
fresh(); MODE["dates_500"] = True; run("?action=albums&type=album")
check(labels()[1:] == ["Bretagna e Normandia (115)", "Café del Mar (10)", "Città di Roma (22)", "Langhe (47)", "Senza data (5)", "Toscana (42)", "Vuoto (0)"]
      and "Cannot read the last photo date" in read_log(), "date lookups failing: albums still listed (by name), warning logged")
MODE["dates_500"] = False; run("?action=albums&type=album")
check(labels()[1] == "Città di Roma (22)", "failed lookups are not cached: dates appear on the next load")

check(str(HITS["ua"]).startswith("KodiPrism/"), "User-Agent identifies KodiPrism (%s)" % HITS["ua"])

# ---- 1.2.0: translation, new entries, slideshow helpers, pan/zoom guard, first run ----
from urllib.parse import urlparse, parse_qs
from resources.lib import slideshow_fx as fx

# translation (the fakes read the add-on's real strings.po)
LANG["code"] = "it_it"; fresh(); run("")
check(labels()[:5] == ["Album", "Cartelle", "Momenti", "Calendario", "Tutte le foto"] and "Cerca album..." in labels()
      and "Foto casuali" in labels() and "In questo giorno" in labels() and "Svuota la cache" in labels(), "Italian UI: main menu is translated")
fresh(page_size="3"); run("?action=albums&type=album")
check("[B]Pagina successiva >>[/B]" in labels() and labels()[0] == "Cerca album...", "Italian UI: album list")
SELECT["value"] = 0; run("?action=slideshow"); check(LOG["selects"][0] == ("Ordine dello slideshow", ["Prima le più recenti", "Prima le più vecchie", "Casuale"]), "Italian UI: slideshow order dialog")
LANG["code"] = "en_gb"

# new root entries
fresh(); run("")
q = lambda label: parse_qs(urlparse([i for i in LOG["items"] if i[0] == label][0][1]).query)
tm = time.localtime()
check(q("Recently added")["order"] == ["added"] and q("Recently added")["fresh"] == ["1"]
      and q("On this day")["q"] == ["month:%d day:%d" % (tm.tm_mon, tm.tm_mday)]
      and q("Random photos")["order"] == ["random"] and q("Random photos")["q"] == ["type:image"], "root: Recently added / On this day / Random photos")

# 'fresh' lists are never cached; normal lists are
fresh(); run("?action=photos&order=added&fresh=1"); run("?action=photos&order=added&fresh=1")
check(len(PQ()) == 2 and all(p["order"] == "added" for p in PQ()), "Recently added: server order=added, never cached")
fresh(); run("?action=photos"); run("?action=photos"); check(len(PQ()) == 1, "ordinary photo list is served from the cache the second time")

# random browsing: one draw, no paging, 'shuffle again', never cached
fresh(); run("?action=photos&q=type%3Aimage&order=random&title=Random+photos")
check(labels() == ["> Slideshow".join(["[I]", "[/I]"])] + ["Photo %d" % i for i in (0, 2, 3, 4)] + ["[B]Shuffle again[/B]"]
      and ("category", "Random photos") in LOG["text"] and "r=" in LOG["items"][-1][1] and "order=random" in LOG["items"][-1][1], "random photos: single draw + 'Shuffle again' (%s)" % labels())
run("?action=photos&q=type%3Aimage&order=random"); check(len(PQ()) == 2 and PQ()[-1]["count"] == "60", "random browsing is never cached")

# photo items: date as second label, context menu, videos without it
fresh(); run("?action=photos")
img = [i for i in LOG["items"] if i[0] == "Photo 0"][0]; vid = [i for i in LOG["items"] if i[0] == "Photo 1"][0]
check(img[4] == "2021-03-01" and img[5][0][0] == "Slideshow from here" and "begin=h0" in img[5][0][1] and vid[5] == [],
      "photos: date as label2 and 'Slideshow from here' on images only")

# slideshow from here
fresh(); SELECT["value"] = 0; run("?action=slideshow&begin=h2")
b = LOG["builtin"][0]
check('beginslide="http' in b and "/t/h2/prev/fit_1920" in b and ",notrandom," in b, "slideshow from here: beginslide points at that picture: %s" % b[-90:])
SELECT["value"] = 2; run("?action=slideshow&begin=h2"); check("beginslide" not in LOG["builtin"][0], "no beginslide in random mode")

# pan / zoom guard through the plugin
def kodi(**kw):
    KODI_SETTINGS.update({"slideshow.displayeffects": True}); RPC.update(calls=[], fail_get=False, fail_set=False); RPC.update(kw)
    WIN.clear(); ACTIVE["slideshow"] = False
    for f in ("fx_restore.json",):
        try: os.remove(os.path.join(PROFILE, f))
        except OSError: pass
STATE = os.path.join(PROFILE, "fx_restore.json")
fresh(debug_log="false"); kodi(); run("?action=slideshow")
check(RPC["calls"] == [] and KODI_SETTINGS["slideshow.displayeffects"] is True and len(LOG["builtin"]) == 1 and "service is not running" in read_log(),
      "pan/zoom: background service not running -> Kodi setting untouched, slideshow still starts, warning logged")
fresh(); kodi(); WIN[fx.SERVICE_PROP] = "1"; run("?action=slideshow")
check(KODI_SETTINGS["slideshow.displayeffects"] is False and json.load(open(STATE))["value"] is True and len(LOG["builtin"]) == 1, "pan/zoom switched off before the slideshow, previous value saved")
run("?action=slideshow"); check(json.load(open(STATE))["value"] is True and KODI_SETTINGS["slideshow.displayeffects"] is False, "second slideshow keeps the ORIGINAL saved value")
fresh(); kodi(); WIN[fx.SERVICE_PROP] = "1"; KODI_SETTINGS["slideshow.displayeffects"] = False; run("?action=slideshow")
check(not os.path.exists(STATE) and not any(c[0] == "Settings.SetSettingValue" for c in RPC["calls"]), "effects already off: nothing changed, nothing to restore")
fresh(disable_pan_zoom="false"); kodi(); WIN[fx.SERVICE_PROP] = "1"; run("?action=slideshow")
check(RPC["calls"] == [] and len(LOG["builtin"]) == 1, "option turned off: no JSON-RPC at all")
fresh(); kodi(fail_get=True); WIN[fx.SERVICE_PROP] = "1"; run("?action=slideshow")
check(not os.path.exists(STATE) and len(LOG["builtin"]) == 1 and "Cannot read Kodi setting" in read_log(), "cannot read the Kodi setting: left alone, warning, slideshow starts")
fresh(); kodi(fail_set=True); WIN[fx.SERVICE_PROP] = "1"; run("?action=slideshow")
check(not os.path.exists(STATE) and KODI_SETTINGS["slideshow.displayeffects"] is True and len(LOG["builtin"]) == 1, "cannot change the Kodi setting: no stale restore file, slideshow starts")

# the service side, with a simulated clock
XRPC = __import__("xbmc").executeJSONRPC


class Clock:
    t = 1000.0
    def __call__(s): return s.t
class Log:
    def __init__(s): s.lines = []
    def info(s, m): s.lines.append(m)
    warning = debug = error = info
clk = Clock(); glog = Log(); kodi(); guard = fx.Guard(XRPC, PROFILE, glog, clk)
check(guard.prepare() and guard.pending() and KODI_SETTINGS["slideshow.displayeffects"] is False, "guard.prepare switches the effect off")
guard.tick(False); check(KODI_SETTINGS["slideshow.displayeffects"] is False, "slideshow window not open yet: still off (grace period)")
guard.tick(True); guard.tick(True); check(KODI_SETTINGS["slideshow.displayeffects"] is False, "slideshow running: still off")
guard.tick(False); check(KODI_SETTINGS["slideshow.displayeffects"] is True and not os.path.exists(STATE), "slideshow closed: effect restored, state file removed")
kodi(); clk.t = 1000.0; guard = fx.Guard(XRPC, PROFILE, glog, clk); guard.prepare()
clk.t += fx.GRACE - 1; guard.tick(False); still = KODI_SETTINGS["slideshow.displayeffects"] is False
clk.t += 5; guard.tick(False)
check(still and KODI_SETTINGS["slideshow.displayeffects"] is True, "slideshow window never appears: restored after the grace period (%ds)" % fx.GRACE)
kodi(); clk.t = 1000.0; g4 = fx.Guard(XRPC, PROFILE, glog, clk); g4.prepare()
clk.t += fx.GRACE - 10; g4.prepare()            # a second slideshow starts just before the first grace period ends
clk.t += 20; g4.tick(False)
check(KODI_SETTINGS["slideshow.displayeffects"] is False and g4.pending(), "a second slideshow restarts the grace period (no premature restore)")
kodi(); guard = fx.Guard(XRPC, PROFILE, glog, clk); guard.prepare()
RPC["fail_set"] = True; guard.tick(True); guard.tick(False)
check(guard.pending() and KODI_SETTINGS["slideshow.displayeffects"] is False, "restore failing: state kept for a retry")
RPC["fail_set"] = False; guard.tick(False); clk.t += fx.GRACE + 1; guard.tick(False)
check(KODI_SETTINGS["slideshow.displayeffects"] is True and not guard.pending(), "restore retried and done")

class FakeMonitor:
    def __init__(s, ticks): s.n = ticks
    def abortRequested(s): return s.n <= 0
    def waitForAbort(s, t): s.n -= 1; return s.n <= 0
kodi(); json.dump({"setting": fx.SETTING_ID, "value": True, "ts": 1.0}, open(STATE, "w")); KODI_SETTINGS["slideshow.displayeffects"] = False
fx.service_loop(fx.Guard(XRPC, PROFILE, glog, clk), FakeMonitor(0), lambda: False)
check(KODI_SETTINGS["slideshow.displayeffects"] is True and not os.path.exists(STATE), "service start: a leftover from a crash is restored")
kodi(); g2 = fx.Guard(XRPC, PROFILE, glog, clk); g2.prepare()
flags = iter([False, True, True, False, False]); fx.service_loop(g2, FakeMonitor(10), lambda: next(flags, False))
check(KODI_SETTINGS["slideshow.displayeffects"] is True and not g2.pending(), "service loop: full cycle restores the effect")
kodi(); g3 = fx.Guard(XRPC, PROFILE, glog, clk); g3.prepare()
fx.service_loop(g3, FakeMonitor(3), lambda: True)
check(KODI_SETTINGS["slideshow.displayeffects"] is True and not g3.pending(), "Kodi exits during a slideshow: effect restored on the way out")

# service.py itself, run as Kodi would run it (restores a leftover, announces itself, cleans up)
import runpy
kodi(); json.dump({"setting": fx.SETTING_ID, "value": True, "ts": 1.0}, open(STATE, "w")); KODI_SETTINGS["slideshow.displayeffects"] = False
MONITOR.update(seen=[], ticks=2); runpy.run_path(os.path.join(ADDON_DIR, "service.py"))
check(MONITOR["seen"] == ["1", "1"] and fx.SERVICE_PROP not in WIN and KODI_SETTINGS["slideshow.displayeffects"] is True and not os.path.exists(STATE),
      "service.py: announces itself while running, restores a leftover, clears its flag on exit")

# diagnostic screen
fresh(); kodi(); WIN[fx.SERVICE_PROP] = "1"; run("?action=slideshow_settings"); txt = LOG["text"][-1][1]
check("running" in txt and "slideshow.displayeffects = True" in txt and "slideshow.staytime = 5" in txt and "pictures.thumbsize" in txt and "player.other" not in txt,
      "'Check slideshow settings' lists the relevant Kodi settings and the service state")
WIN.clear(); run("?action=slideshow_settings"); check("NOT running" in LOG["text"][-1][1], "diagnostic says when the service is not running")

# first run
marker = os.path.join(PROFILE, "first_run_done")
def first(**kw):
    fresh(**kw)
    if os.path.exists(marker): os.remove(marker)
first(server_url="http://localhost:2342"); YESNO["value"] = False; run("")
check(len(LOG["yesno"]) == 1 and LOG["opened"] == [] and len(LOG["items"]) == 14 and os.path.exists(marker), "first run: asked once, 'Later' shows the menu")
run(""); check(LOG["yesno"] == [], "first run: not asked again")
first(server_url="http://localhost:2342"); YESNO["value"] = True; run("")
check(LOG["opened"] == [1] and LOG["items"] == [] and LOG["end"] == [False], "first run: 'Open settings' opens the settings dialog")
first(); run(""); check(LOG["yesno"] == [] and len(LOG["items"]) == 14, "configured server: no first-run question")

# hide empty albums
fresh(hide_empty_albums="true"); run("?action=albums&type=album")
check("Vuoto (0)" not in labels() and "Senza data (5)" in labels() and len(labels()) == 7 and HITS["album_dates"] == 6, "hide empty albums: 'Vuoto (0)' is gone, others stay")
fresh(hide_empty_albums="false"); run("?action=albums&type=album"); check("Vuoto (0)" in labels(), "hide empty albums off: empty albums are listed (last)")

# ---- 1.2.1: error paths a real user can hit ----
def notes(): return " | ".join(LOG["notes"])

# the session dies while album dates are being read: log in again and finish the listing
fresh(); MODE["expire_on_dates"] = True; HITS["session"] = 0; run("?action=albums&type=album")
check(HITS["session"] == 2 and labels()[1] == "Città di Roma (22)" and LOG["end"] == [True], "session expiring during the date lookups -> automatic re-login, complete newest-first list")

# unexpected answers from the server or from something in front of it
fresh(); MODE["force"] = ("/api/v1/albums", 200, b"<html><body>Please log in to the proxy</body></html>", "text/html"); run("?action=albums&type=album")
check("Invalid JSON from server" in notes() and LOG["end"] == [False] and "non-JSON body" in read_log(), "an HTML page instead of JSON (proxy login page) -> clear message, directory closed as failed")
for code, text in ((403, "Access denied (403)"), (429, "Too many requests (429)"), (418, "HTTP 418 for /photos"), (503, "Server error (HTTP 503)")):
    fresh(); MODE["force"] = ("/api/v1/photos", code, {"error": "x"}); run("?action=photos")
    check(text in notes() and LOG["end"] == [False], "HTTP %d on photos -> '%s'" % (code, text))

# 1.2.2: 403 means "not allowed", not "log in again"
fresh(); MODE["force"] = ("/api/v1/photos", 403, {"error": "x"}); HITS["session"] = 0; run("?action=photos")
check(HITS["session"] == 1 and "Access denied (403)" in notes() and LOG["end"] == [False], "403 -> message, no second login attempt")
fresh(); MODE["force"] = ("/api/v1/photos", 401, {"error": "x"}); HITS["session"] = 0; run("?action=photos")
check(HITS["session"] == 2, "401 still triggers one transparent re-login")

# 1.2.2: action items in a list must close the list (no endless spinner in Kodi); RunPlugin (handle -1) must not
def run_h(qs, handle):
    for k in LOG: LOG[k].clear()
    plugin.run(["plugin://plugin.image.photoprism/", str(handle), qs])
fresh(); run_h("?action=clear_cache", 7); check(LOG["end"] == [False], "'Clear cache' picked from a list closes it as failed (Kodi stays on the list)")
fresh(); run_h("?action=clear_cache", -1); check(LOG["end"] == [], "'Clear cache' via RunPlugin (handle -1) touches no directory")
fresh(); SELECT["value"] = 0; run_h("?action=slideshow", 7)
check(LOG["end"] == [False] and "SlideShow(" in LOG["builtin"][0], "'Slideshow' picked from a list starts it and closes the list")
fresh(); SELECT["value"] = -1; run_h("?action=slideshow", 7); check(LOG["end"] == [False] and LOG["builtin"] == [], "cancelled slideshow still closes the list")
fresh(); run(""); check(len(LOG["items"]) == 14 and all(i[3] for i in LOG["items"]), "every root item is a folder (Slideshow / Clear cache included)")

# 1.2.2: listings are re-read after 10 minutes even with a 24 h cache lifetime
d = tempfile.mkdtemp(); c = cache.DiskCache(d, max_mb=10, ttl_hours=24)
c.set_json("L", {"a": 1}); pth = c._path("meta", "L", ".json")
os.utime(pth, (time.time(), time.time() - 300)); check(c.get_json("L", 600) == {"a": 1}, "listing 5 min old is still served")
os.utime(pth, (time.time(), time.time() - 700)); check(c.get_json("L", 600) is None, "listing 12 min old is read again")
c.set_json("L", {"a": 1}); os.utime(pth, (time.time(), time.time() - 700)); check(c.get_json("L") == {"a": 1}, "without max_age the normal lifetime applies")
fresh(); run("?action=photos"); n = HITS["photos"]
for f in os.listdir(os.path.join(SETTINGS["cache_path"], "photoprism_cache", "meta")):
    q = os.path.join(SETTINGS["cache_path"], "photoprism_cache", "meta", f); os.utime(q, (time.time(), time.time() - 700))
run("?action=photos"); check(HITS["photos"] > n, "photo listing older than 10 min is fetched again by the add-on")

# settings not filled in
fresh(auth_mode="1", token=""); run("?action=albums&type=album"); check("Enter an app password" in notes() and LOG["end"] == [False], "app-password mode without token -> message")
fresh(username=""); run("?action=albums&type=album"); check("Enter username and password" in notes() and LOG["end"] == [False], "password mode without username -> message")
fresh(server_url=""); run("?action=albums&type=album"); check("Set the PhotoPrism URL" in notes() and LOG["end"] == [False], "no server address -> message")

# test-connection variants
fresh(); MODE["status401"] = True; run("?action=test_connection"); txt = LOG["text"][-1][1]
check("its status page asks for a login" in txt and "All checks passed" in txt, "test connection: status page needs a login -> still counted as reachable")
fresh(auth_mode="1", token="app-pass"); run("?action=test_connection"); txt = LOG["text"][-1][1]
check("App password / access token accepted" in txt and "All checks passed" in txt and "[FAIL]" not in txt, "test connection with an app password")

# a failing network during 'Search albums' must still close the directory (this used to hang Kodi's spinner)
fresh(server_url="127.0.0.1:%d" % DEAD); KBCFG["text"] = "x"; run("?action=search_albums")
check(LOG["end"] == [False] and "Connection refused" in notes(), "search albums with the server down -> notification and directory closed as failed")
fresh(); KBCFG["ok"] = False; run("?action=search"); check(LOG["end"] == [False] and labels() == [], "photo search cancelled -> directory closed as failed")
fresh(); run("?action=play"); check(LOG["resolved"] and LOG["resolved"][-1][0] is False and "Unexpected error" in notes(), "play without a video hash -> failed resolve + notification, no crash")
fresh(); run("?action=nonsense"); check("Unknown action" in read_log() and LOG["end"] == [], "unknown action is logged and ignored")

# 'Next page' of an album search keeps the query; original-size images use the download endpoint
fresh(page_size="2"); run("?action=albums&type=album&q=a")
check("q=a" in LOG["items"][-1][1] and "offset=2" in LOG["items"][-1][1], "search results spread over pages keep the query in 'Next page'")
fresh(full_size="original"); run("?action=photos")
check(any("/api/v1/dl/h0?t=dl" in i[1] for i in LOG["items"]), "full size 'original' uses the download endpoint")

# low-level robustness
check(fx.get_value(lambda raw: "not json at all") is None and fx.set_value(lambda raw: "{}", False) is False, "JSON-RPC garbage answers are handled")

# ---- Support info (for bug reports) ----
STATS = os.path.join(PROFILE, "stats.json")
if os.path.exists(STATS): os.remove(STATS)
fresh(password="S3cretPassw0rd", token="tok-xyz-123"); run("?action=support_info"); txt = LOG["text"][-1][1]
check("(none yet" in txt and "Last log lines:" in txt, "support info before any measurement says so")
run("?action=albums&type=album"); run("?action=photos&slideshow=1&order=newest&q=type%3Aimage"); run("?action=support_info"); txt = LOG["text"][-1][1]
check("Add-on: KodiPrism 9.9.9 (plugin.image.photoprism)" in txt
      and "Kodi: 21.2 (test) | OS: LibreELEC (test) | Skin: skin.estuary | Language: Italian" in txt
      and "Server: http://<host hidden>:%d" % srv.server_port in txt and "login: username/password" in txt
      and "sort=newest" in txt and "Background service: NOT running" in txt, "support info: versions, skin, language, settings, service state")
check("album_dates: albums=7, at=" in txt and "fetched=6" in txt and "slideshow_list: at=" in txt and "images=4" in txt and "order=newest" in txt,
      "support info: latest album-date load and slideshow list timings")
check("files," in txt and " MB used" in txt, "support info: cache usage")
check(not any(x in txt for x in ("S3cretPassw0rd", "tok-xyz-123", "127.0.0.1", "sess-tok")), "support info never contains a secret or the server name")

srv.shutdown(); print("ALL %d CHECKS PASSED" % ok)
