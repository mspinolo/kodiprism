"""1.2.0: translation, new root entries, slideshow helpers, pan/zoom guard, service, first run."""

import json, os, time
from support import (
    PROFILE, LOG, SELECT, YESNO, LANG, WIN, KODI_SETTINGS, RPC, MONITOR, ADDON_DIR, HITS, fx, STATE, check,
    run, read_log, fresh, labels, PQ, kodi)
import runpy

from urllib.parse import urlparse, parse_qs

XRPC = __import__("xbmc").executeJSONRPC


class Clock:
    t = 1000.0
    def __call__(s): return s.t
class Log:
    def __init__(s): s.lines = []
    def info(s, m): s.lines.append(m)
    warning = debug = error = info


class FakeMonitor:
    def __init__(s, ticks): s.n = ticks
    def abortRequested(s): return s.n <= 0
    def waitForAbort(s, t): s.n -= 1; return s.n <= 0


def test_italian_ui():
    """The Italian strings are used."""
    LANG["code"] = "it_it"; fresh(); run("")
    check(labels()[:5] == ["Album", "Cartelle", "Momenti", "Calendario", "Tutte le foto"] and "Cerca album..." in labels()
          and "Foto casuali" in labels() and "In questo giorno" in labels() and "Svuota la cache" in labels(), "Italian UI: main menu is translated")
    fresh(page_size="3"); run("?action=albums&type=album")
    check("[B]Pagina successiva >>[/B]" in labels() and labels()[0] == "Cerca album...", "Italian UI: album list")
    SELECT["value"] = 0; run("?action=slideshow"); check(LOG["selects"][0] == ("Ordine dello slideshow", ["Prima le più recenti", "Prima le più vecchie", "Casuale"]), "Italian UI: slideshow order dialog")
    LANG["code"] = "en_gb"


def test_root_entries():
    """Recently added / On this day / Random photos."""
    fresh(); run("")
    q = lambda label: parse_qs(urlparse([i for i in LOG["items"] if i[0] == label][0][1]).query)
    tm = time.localtime()
    check(q("Recently added")["order"] == ["added"] and q("Recently added")["fresh"] == ["1"]
          and q("On this day")["q"] == ["month:%d day:%d" % (tm.tm_mon, tm.tm_mday)]
          and q("Random photos")["order"] == ["random"] and q("Random photos")["q"] == ["type:image"], "root: Recently added / On this day / Random photos")


def test_fresh_lists_not_cached():
    """'fresh' lists are never cached; normal lists are."""
    fresh(); run("?action=photos&order=added&fresh=1"); run("?action=photos&order=added&fresh=1")
    check(len(PQ()) == 2 and all(p["order"] == "added" for p in PQ()), "Recently added: server order=added, never cached")
    fresh(); run("?action=photos"); run("?action=photos"); check(len(PQ()) == 1, "ordinary photo list is served from the cache the second time")


def test_random_browsing():
    """Random photos: one draw, 'Shuffle again', never cached."""
    fresh(); run("?action=photos&q=type%3Aimage&order=random&title=Random+photos")
    check(labels() == ["> Slideshow".join(["[I]", "[/I]"])] + ["Photo %d" % i for i in (0, 2, 3, 4)] + ["[B]Shuffle again[/B]"]
          and ("category", "Random photos") in LOG["text"] and "r=" in LOG["items"][-1][1] and "order=random" in LOG["items"][-1][1], "random photos: single draw + 'Shuffle again' (%s)" % labels())
    run("?action=photos&q=type%3Aimage&order=random"); check(len(PQ()) == 2 and PQ()[-1]["count"] == "60", "random browsing is never cached")


def test_photo_items():
    """Photo items: date as label2, 'Slideshow from here' on images only."""
    fresh(); run("?action=photos")
    img = [i for i in LOG["items"] if i[0] == "Photo 0"][0]; vid = [i for i in LOG["items"] if i[0] == "Photo 1"][0]
    check(img[4] == "2021-03-01" and img[5][0][0] == "Slideshow from here" and "begin=h0" in img[5][0][1] and vid[5] == [],
          "photos: date as label2 and 'Slideshow from here' on images only")


def test_slideshow_from_here():
    """beginslide points at the chosen picture."""
    fresh(); SELECT["value"] = 0; run("?action=slideshow&begin=h2")
    b = LOG["builtin"][0]
    check('beginslide="http' in b and "/t/h2/prev/fit_1920" in b and ",notrandom," in b, "slideshow from here: beginslide points at that picture: %s" % b[-90:])
    SELECT["value"] = 2; run("?action=slideshow&begin=h2"); check("beginslide" not in LOG["builtin"][0], "no beginslide in random mode")


def test_pan_zoom_via_plugin():
    """The plugin side of the pan/zoom guard."""
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


def test_guard_with_simulated_clock():
    """Guard: off during the slideshow, restored after it or after the grace period."""
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


def test_service_loop():
    """service_loop: leftovers restored, full cycle, Kodi exiting mid-slideshow."""
    clk = Clock(); glog = Log()
    kodi(); json.dump({"setting": fx.SETTING_ID, "value": True, "ts": 1.0}, open(STATE, "w")); KODI_SETTINGS["slideshow.displayeffects"] = False
    fx.service_loop(fx.Guard(XRPC, PROFILE, glog, clk), FakeMonitor(0), lambda: False)
    check(KODI_SETTINGS["slideshow.displayeffects"] is True and not os.path.exists(STATE), "service start: a leftover from a crash is restored")
    kodi(); g2 = fx.Guard(XRPC, PROFILE, glog, clk); g2.prepare()
    flags = iter([False, True, True, False, False]); fx.service_loop(g2, FakeMonitor(10), lambda: next(flags, False))
    check(KODI_SETTINGS["slideshow.displayeffects"] is True and not g2.pending(), "service loop: full cycle restores the effect")
    kodi(); g3 = fx.Guard(XRPC, PROFILE, glog, clk); g3.prepare()
    fx.service_loop(g3, FakeMonitor(3), lambda: True)
    check(KODI_SETTINGS["slideshow.displayeffects"] is True and not g3.pending(), "Kodi exits during a slideshow: effect restored on the way out")


def test_service_py():
    """service.py run as Kodi would run it."""
    kodi(); json.dump({"setting": fx.SETTING_ID, "value": True, "ts": 1.0}, open(STATE, "w")); KODI_SETTINGS["slideshow.displayeffects"] = False
    MONITOR.update(seen=[], ticks=2); runpy.run_path(os.path.join(ADDON_DIR, "service.py"))
    check(MONITOR["seen"] == ["1", "1"] and fx.SERVICE_PROP not in WIN and KODI_SETTINGS["slideshow.displayeffects"] is True and not os.path.exists(STATE),
          "service.py: announces itself while running, restores a leftover, clears its flag on exit")


def test_slideshow_settings_screen():
    """'Check slideshow settings' lists the relevant Kodi settings."""
    fresh(); kodi(); WIN[fx.SERVICE_PROP] = "1"; run("?action=slideshow_settings"); txt = LOG["text"][-1][1]
    check("running" in txt and "slideshow.displayeffects = True" in txt and "slideshow.staytime = 5" in txt and "pictures.thumbsize" in txt and "player.other" not in txt,
          "'Check slideshow settings' lists the relevant Kodi settings and the service state")
    WIN.clear(); run("?action=slideshow_settings"); check("NOT running" in LOG["text"][-1][1], "diagnostic says when the service is not running")


def test_first_run():
    """The first-run question."""
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


def test_hide_empty_albums():
    """The 'hide empty albums' option."""
    fresh(hide_empty_albums="true"); run("?action=albums&type=album")
    check("Vuoto (0)" not in labels() and "Senza data (5)" in labels() and len(labels()) == 7 and HITS["album_dates"] == 6, "hide empty albums: 'Vuoto (0)' is gone, others stay")
    fresh(hide_empty_albums="false"); run("?action=albums&type=album"); check("Vuoto (0)" in labels(), "hide empty albums off: empty albums are listed (last)")
