"""Core browsing: login, albums, photos, video, search, slideshow, auth modes, errors, cache (1.0.x)."""

import os, tempfile, time
from support import PROFILE, SETTINGS, LOG, HITS, MODE, cache, check, run


def test_core_browsing_flow():
    """A full session: menu, albums, photos, video, search, slideshow, re-login, app password, failures."""
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
    page = [i[0] for i in LOG["items"]]
    check(page == ["Photo 2", "Photo 3", "[B]Next page >>[/B]"] and "offset=4" in LOG["items"][-1][1], "photo page 2")
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


def test_cache_location():
    """A custom cache folder is used; an unusable one falls back with a notification."""
    custom = tempfile.mkdtemp(); SETTINGS["cache_path"] = custom; run("")
    check(os.path.isdir(os.path.join(custom, "photoprism_cache", "img")), "custom cache folder used")
    SETTINGS["cache_path"] = "/proc/nope"; run("")
    check(any("not writable" in n for n in LOG["notes"]), "invalid cache folder -> fallback + notify")
    ro = tempfile.mkdtemp(); os.chmod(ro, 0o500)
    r, fb = cache.resolve_dir(ro, PROFILE)
    if os.geteuid() != 0: check(fb, "read-only folder rejected")
    else: print("SKIP read-only check (running as root)")


def test_lru_and_ttl():
    """Disk cache: LRU eviction, TTL expiry, clear."""
    d = tempfile.mkdtemp(); c = cache.DiskCache(d, max_mb=1, ttl_hours=1)
    for i in range(6): c.put_image("k%d" % i, b"x" * 300000); os.utime(c._path("img", "k%d" % i, ".jpg"), (1000 + i, time.time()))
    c.image_path("k0")  # touch -> most recent
    c.evict(); kept = [i for i in range(6) if os.path.exists(c._path("img", "k%d" % i, ".jpg"))]
    check(c.size() <= 1024 * 1024 and 0 in kept and 1 not in kept, "LRU eviction keeps recently used (kept %s)" % kept)
    c.set_json("m", {"a": 1}); pth = c._path("meta", "m", ".json"); os.utime(pth, (time.time(), time.time() - 7200))
    check(c.get_json("m") is None and not os.path.exists(pth), "TTL expiry")
    check(c.clear() > 0 and c.size() == 0, "clear cache")


def test_clear_cache_action():
    """The 'Clear cache' action reports what it did."""
    SETTINGS["cache_path"] = ""; run("?action=clear_cache"); check(any("Cache cleared" in n for n in LOG["notes"]), "clear-cache action")
