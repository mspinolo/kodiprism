import json, os, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from kodi_mocks import PROFILE, SETTINGS, LOG

# ---- fake PhotoPrism ----
PHOTOS = [{"UID": "p%d" % i, "Hash": "h%d" % i, "Title": "Photo %d" % i,
           "Type": "video" if i == 1 else "image", "Duration": 5e9} for i in range(5)]
ALBUMS = [{"UID": "a%d" % i, "Title": "Album %d" % i, "PhotoCount": i, "Thumb": "ah%d" % i if i < 2 else ""} for i in range(3)]
HITS = {"session": 0, "photos": 0, "thumb": 0}
MODE = {"slow": False, "expire": False}
class H(BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def send(s, code, body, ct="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        s.send_response(code); s.send_header("Content-Type", ct); s.send_header("Content-Length", str(len(b))); s.end_headers(); s.wfile.write(b)
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
        if u.path.startswith("/api/v1/t/") or "/t/prev/" in u.path:
            HITS["thumb"] += 1
            return s.send(200, b"\xff\xd8JPEG" + u.path.encode(), "image/jpeg") if "/prev/" in u.path else s.send(403, {})
        if u.path == "/api/v1/status": return s.send(200, {"status": "operational"})
        if not s.authed(): return s.send(401, {"error": "Unauthorized"})
        if u.path == "/api/v1/config": return s.send(200, {"previewToken": "prev", "downloadToken": "dl", "version": "test-1.2"})
        off, cnt = int(q.get("offset", 0)), int(q.get("count", 10))
        if u.path == "/api/v1/albums": return s.send(200, ALBUMS[off:off + cnt])
        if u.path == "/api/v1/photos":
            HITS["photos"] += 1
            items = PHOTOS
            if q.get("q") == "label:cat": items = PHOTOS[:1]
            if "type:image" in q.get("q", ""): items = [p for p in PHOTOS if p["Type"] == "image"]
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

run(""); check(len(LOG["items"]) == 10 and LOG["end"] == [True], "root menu")
run("?action=albums&type=album")
check(HITS["session"] == 1, "password login via POST /session")
check([i[0] for i in LOG["items"]] == ["Album 0 (0)", "Album 1 (1)", "[B]Next page >>[/B]"], "album pagination")
check("/api/v1/t/ah0/prev/tile_500" in LOG["items"][0][2] and "/api/v1/t/ah1/prev/tile_500" in LOG["items"][1][2],
      "album cover uses the album's Thumb hash with the normal thumbnail endpoint")
run("?action=albums&type=album&offset=2")   # page 2 holds a2, which has no Thumb
check("/api/v1/albums/a2/t/prev/tile_500" in LOG["items"][0][2], "album without Thumb falls back to the album cover endpoint")
time.sleep(0.3)
run("?action=albums&type=album")
check(HITS["session"] == 1, "session reused from profile")
check(LOG["items"][0][2].startswith(PROFILE), "thumbnail served from disk cache after prefetch")
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
                    cache_path="", debug_log="false", verify_ssl="true", timeout="3", prefetch="true")
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

srv.shutdown(); print("ALL %d CHECKS PASSED" % ok)
