import json, os, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from kodi_mocks import PROFILE, SETTINGS, LOG

# ---- fake PhotoPrism ----
PHOTOS = [{"UID": "p%d" % i, "Hash": "h%d" % i, "Title": "Photo %d" % i,
           "Type": "video" if i == 1 else "image", "Duration": 5e9} for i in range(5)]
ALBUMS = [{"UID": "a%d" % i, "Title": "Album %d" % i, "PhotoCount": i} for i in range(3)]
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
        if body == {"username": "admin", "password": "pw"}:
            s.send(200, {"id": "sid", "access_token": "sess-tok", "config": {"previewToken": "prev", "downloadToken": "dl"}})
        else: s.send(401, {"error": "Invalid credentials"})
    def do_GET(s):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(s.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if MODE["slow"]: time.sleep(5)
        if u.path.startswith("/api/v1/t/") or "/t/prev/" in u.path:
            HITS["thumb"] += 1
            return s.send(200, b"\xff\xd8JPEG" + u.path.encode(), "image/jpeg") if "/prev/" in u.path else s.send(403, {})
        if not s.authed(): return s.send(401, {"error": "Unauthorized"})
        if u.path == "/api/v1/config": return s.send(200, {"previewToken": "prev", "downloadToken": "dl"})
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
check("/api/v1/albums/a0/t/prev/tile_500" in LOG["items"][0][2], "album cover url w/ preview token")
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
check(any("Connection failed" in n for n in LOG["notes"]), "unreachable server -> notification")

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
srv.shutdown(); print("ALL %d CHECKS PASSED" % ok)
