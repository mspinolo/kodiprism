"""Error paths a real user can hit (1.2.1, 1.2.2) and the support screen."""

import os, tempfile, time
from support import (
    PROFILE, SETTINGS, LOG, KBCFG, SELECT, HITS, MODE, srv, cache, fx, DEAD, check, run, run_h, read_log,
    fresh, labels, notes)


def test_session_expires_during_dates():
    """The session dies while album dates are read: log in again and finish."""
    fresh(); MODE["expire_on_dates"] = True; HITS["session"] = 0; run("?action=albums&type=album")
    check(HITS["session"] == 2 and labels()[1] == "Città di Roma (22)" and LOG["end"] == [True], "session expiring during the date lookups -> automatic re-login, complete newest-first list")


def test_unexpected_answers():
    """HTML instead of JSON, 403, 429, 418, 503."""
    fresh(); MODE["force"] = ("/api/v1/albums", 200, b"<html><body>Please log in to the proxy</body></html>", "text/html"); run("?action=albums&type=album")
    check("Invalid JSON from server" in notes() and LOG["end"] == [False] and "non-JSON body" in read_log(), "an HTML page instead of JSON (proxy login page) -> clear message, directory closed as failed")
    for code, text in ((403, "Access denied (403)"), (429, "Too many requests (429)"), (418, "HTTP 418 for /photos"), (503, "Server error (HTTP 503)")):
        fresh(); MODE["force"] = ("/api/v1/photos", code, {"error": "x"}); run("?action=photos")
        check(text in notes() and LOG["end"] == [False], "HTTP %d on photos -> '%s'" % (code, text))


def test_forbidden_is_not_expired():
    """403 is 'not allowed' (no second login); 401 still re-logs in."""
    fresh(); MODE["force"] = ("/api/v1/photos", 403, {"error": "x"}); HITS["session"] = 0; run("?action=photos")
    check(HITS["session"] == 1 and "Access denied (403)" in notes() and LOG["end"] == [False], "403 -> message, no second login attempt")
    fresh(); MODE["force"] = ("/api/v1/photos", 401, {"error": "x"}); HITS["session"] = 0; run("?action=photos")
    check(HITS["session"] == 2, "401 still triggers one transparent re-login")


def test_action_items_close_the_list():
    """Action items close the list; RunPlugin (handle -1) touches nothing."""
    fresh(); run_h("?action=clear_cache", 7); check(LOG["end"] == [False], "'Clear cache' picked from a list closes it as failed (Kodi stays on the list)")
    fresh(); run_h("?action=clear_cache", -1); check(LOG["end"] == [], "'Clear cache' via RunPlugin (handle -1) touches no directory")
    fresh(); SELECT["value"] = 0; run_h("?action=slideshow", 7)
    check(LOG["end"] == [False] and "SlideShow(" in LOG["builtin"][0], "'Slideshow' picked from a list starts it and closes the list")
    fresh(); SELECT["value"] = -1; run_h("?action=slideshow", 7); check(LOG["end"] == [False] and LOG["builtin"] == [], "cancelled slideshow still closes the list")
    fresh(); run(""); check(len(LOG["items"]) == 14 and all(i[3] for i in LOG["items"]), "every root item is a folder (Slideshow / Clear cache included)")


def test_listing_max_age():
    """Listings are re-read after 10 minutes even with a 24 h cache lifetime."""
    d = tempfile.mkdtemp(); c = cache.DiskCache(d, max_mb=10, ttl_hours=24)
    c.set_json("L", {"a": 1}); pth = c._path("meta", "L", ".json")
    os.utime(pth, (time.time(), time.time() - 300)); check(c.get_json("L", 600) == {"a": 1}, "listing 5 min old is still served")
    os.utime(pth, (time.time(), time.time() - 700)); check(c.get_json("L", 600) is None, "listing 12 min old is read again")
    c.set_json("L", {"a": 1}); os.utime(pth, (time.time(), time.time() - 700)); check(c.get_json("L") == {"a": 1}, "without max_age the normal lifetime applies")
    fresh(); run("?action=photos"); n = HITS["photos"]
    for f in os.listdir(os.path.join(SETTINGS["cache_path"], "photoprism_cache", "meta")):
        q = os.path.join(SETTINGS["cache_path"], "photoprism_cache", "meta", f); os.utime(q, (time.time(), time.time() - 700))
    run("?action=photos"); check(HITS["photos"] > n, "photo listing older than 10 min is fetched again by the add-on")


def test_missing_settings():
    """Settings not filled in -> clear messages."""
    fresh(auth_mode="1", token=""); run("?action=albums&type=album"); check("Enter an app password" in notes() and LOG["end"] == [False], "app-password mode without token -> message")
    fresh(username=""); run("?action=albums&type=album"); check("Enter username and password" in notes() and LOG["end"] == [False], "password mode without username -> message")
    fresh(server_url=""); run("?action=albums&type=album"); check("Set the PhotoPrism URL" in notes() and LOG["end"] == [False], "no server address -> message")


def test_test_connection_variants():
    """Test connection: status page behind login, app password."""
    fresh(); MODE["status401"] = True; run("?action=test_connection"); txt = LOG["text"][-1][1]
    check("its status page asks for a login" in txt and "All checks passed" in txt, "test connection: status page needs a login -> still counted as reachable")
    fresh(auth_mode="1", token="app-pass"); run("?action=test_connection"); txt = LOG["text"][-1][1]
    check("App password / access token accepted" in txt and "All checks passed" in txt and "[FAIL]" not in txt, "test connection with an app password")


def test_failures_close_the_directory():
    """Failures and cancellations close the directory; unknown actions are ignored."""
    fresh(server_url="127.0.0.1:%d" % DEAD); KBCFG["text"] = "x"; run("?action=search_albums")
    check(LOG["end"] == [False] and "Connection refused" in notes(), "search albums with the server down -> notification and directory closed as failed")
    fresh(); KBCFG["ok"] = False; run("?action=search"); check(LOG["end"] == [False] and labels() == [], "photo search cancelled -> directory closed as failed")
    fresh(); run("?action=play"); check(LOG["resolved"] and LOG["resolved"][-1][0] is False and "Unexpected error" in notes(), "play without a video hash -> failed resolve + notification, no crash")
    fresh(); run("?action=nonsense"); check("Unknown action" in read_log() and LOG["end"] == [], "unknown action is logged and ignored")


def test_next_page_and_original_size():
    """'Next page' keeps the search; 'original' uses the download endpoint."""
    fresh(page_size="2"); run("?action=albums&type=album&q=a")
    check("q=a" in LOG["items"][-1][1] and "offset=2" in LOG["items"][-1][1], "search results spread over pages keep the query in 'Next page'")
    fresh(full_size="original"); run("?action=photos")
    check(any("/api/v1/dl/h0?t=dl" in i[1] for i in LOG["items"]), "full size 'original' uses the download endpoint")


def test_jsonrpc_garbage():
    """Garbage JSON-RPC answers are handled."""
    check(fx.get_value(lambda raw: "not json at all") is None and fx.set_value(lambda raw: "{}", False) is False, "JSON-RPC garbage answers are handled")


def test_support_info():
    """Support info: versions, settings, timings, cache usage, never a secret."""
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
