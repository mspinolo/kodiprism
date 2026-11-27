"""Album catalogue, ordering, search and slideshow (1.1.0)."""

from support import LOG, KBCFG, SELECT, BIG, HITS, MODE, cat, check, run, read_log, fresh, labels, PQ


def test_pure_functions():
    """fold / matches / sort_albums."""
    check(cat.fold("Café Città") == "cafe citta", "fold: accents and case ignored")
    cafe = {"Title": "Café del Mar", "Location": "Ibiza"}
    check(cat.matches(cafe, "CAFE mar") and cat.matches(cafe, "ibiza") and not cat.matches(cafe, "roma") and cat.matches(cafe, ""),
          "search matches every word in title or place, ignoring case and accents")
    al = [{"UID": "x", "Title": "B"}, {"UID": "y", "Title": "A"}, {"UID": "z", "Title": "C"}, {"UID": "w", "Title": "D"}]
    dt = {"x": "2020-01-01T00:00:00Z", "y": "2020-01-01T00:00:00Z", "z": "2019-01-01T00:00:00Z", "w": ""}
    ids = lambda mode: [a["UID"] for a in cat.sort_albums(al, dt, mode)]
    check(ids("newest") == ["y", "x", "z", "w"] and ids("oldest") == ["z", "y", "x", "w"] and ids("name") == ["y", "x", "z", "w"],
          "sort: ties broken by name, undated albums last in both directions")


def test_newest_first_dates_cache():
    """Albums newest first by last photo date, cached, refreshed only when an album changes."""
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


def test_other_sort_modes():
    """Oldest first and by name."""
    fresh(sort_order="1"); run("?action=albums&type=album")
    check(labels()[1:] == ["Bretagna e Normandia (115)", "Langhe (47)", "Toscana (42)", "Café del Mar (10)", "Città di Roma (22)",
                           "Senza data (5)", "Vuoto (0)"], "sort oldest first: %s" % labels())
    fresh(sort_order="2"); run("?action=albums&type=album")
    check(labels()[1:] == ["Bretagna e Normandia (115)", "Café del Mar (10)", "Città di Roma (22)", "Langhe (47)", "Senza data (5)",
                           "Toscana (42)", "Vuoto (0)"] and HITS["album_dates"] == 0, "sort by name needs no date lookups")


def test_search_albums():
    """Search albums by title or place, ignoring case and accents."""
    fresh(); KBCFG["text"] = "cafe"; run("?action=search_albums")
    check(labels() == ["Café del Mar (10)"] and ("category", "Search: cafe") in LOG["text"] and LOG["end"] == [True], "search albums: 'cafe' finds 'Café del Mar'")
    KBCFG["text"] = "piemonte"; run("?action=search_albums"); check(labels() == ["Langhe (47)"], "search albums also matches the place")
    KBCFG["text"] = "zzz"; run("?action=search_albums")
    check(labels() == [] and any("No albums found" in n for n in LOG["notes"]) and LOG["end"] == [True], "search albums: no result -> message, empty list")
    KBCFG["ok"] = False; run("?action=search_albums"); check(LOG["end"] == [False] and labels() == [], "search albums cancelled -> nothing listed")
    run("?action=albums&type=album&q=roma"); check(labels() == ["Città di Roma (22)"], "albums list accepts q= directly (used by 'Next page')")


def test_local_pagination():
    """Album pages are cut locally."""
    fresh(page_size="3"); run("?action=albums&type=album")
    check(labels() == ["Search albums...", "Città di Roma (22)", "Café del Mar (10)", "Toscana (42)", "[B]Next page >>[/B]"]
          and "offset=3" in LOG["items"][-1][1], "albums page 1 of 3 with Next")
    run("?action=albums&type=album&offset=6")
    check(labels() == ["Vuoto (0)"], "albums last page has no Next and no search entry")


def test_server_side_ordering():
    """The sort setting reaches the server for moments and photos."""
    for so, want in (("0", "newest"), ("1", "oldest"), ("2", "name")):
        fresh(sort_order=so); run("?action=albums&type=moment")
        p1 = HITS["albums_params"][-1]
        run("?action=photos")
        p2 = PQ()[-1]
        check(p1["order"] == want and p1["type"] == "moment" and p2["order"] == want, "sort setting %s -> server order '%s' for moments and photos" % (so, want))


def test_slideshow_prompt():
    """The slideshow asks the order."""
    fresh(); SELECT["value"] = 1; run("?action=slideshow&album=b0")
    b = LOG["builtin"][0] if LOG["builtin"] else ""
    check(LOG["selects"][0][1] == ["Newest first", "Oldest first", "Random"] and b.startswith("SlideShow(") and "order=oldest" in b
          and "album=b0" in b and "slideshow=1" in b and b.endswith(",notrandom)"), "slideshow asks the order; oldest -> notrandom: %s" % b)
    SELECT["value"] = 2; run("?action=slideshow")
    check("order=random" in LOG["builtin"][0] and LOG["builtin"][0].endswith(",random)"), "slideshow: random")
    SELECT["value"] = -1; run("?action=slideshow"); check(LOG["builtin"] == [], "slideshow cancelled -> nothing starts")
    run("?action=slideshow&order=newest"); check(LOG["selects"] == [] and "order=newest" in LOG["builtin"][0], "slideshow with an explicit order does not ask")


def test_slideshow_listing():
    """Flat slideshow list: order, limit, batches, random."""
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


def test_failing_date_lookups():
    """Failing date lookups do not break the list and are retried."""
    fresh(); MODE["dates_500"] = True; run("?action=albums&type=album")
    check(labels()[1:] == ["Bretagna e Normandia (115)", "Café del Mar (10)", "Città di Roma (22)", "Langhe (47)", "Senza data (5)", "Toscana (42)", "Vuoto (0)"]
          and "Cannot read the last photo date" in read_log(), "date lookups failing: albums still listed (by name), warning logged")
    MODE["dates_500"] = False; run("?action=albums&type=album")
    check(labels()[1] == "Città di Roma (22)", "failed lookups are not cached: dates appear on the next load")


def test_user_agent():
    """Requests carry a KodiPrism User-Agent."""
    fresh(); run("?action=photos")
    check(str(HITS["ua"]).startswith("KodiPrism/"), "User-Agent identifies KodiPrism (%s)" % HITS["ua"])
