# -*- coding: utf-8 -*-
"""Album catalogue helpers: search, sorting and the date of each album's last photo.

Why: manual PhotoPrism albums have no usable date of their own (Year/Month/Day are 0 and
CreatedAt/UpdatedAt are the import dates), so "newest first" needs the date of the most
recent photo inside each album. That costs one small request per album. The result is
cached per album and only re-read when the album's UpdatedAt or PhotoCount changes (or the
entry is older than the cache TTL), so after the first load it is almost free.
"""
import threading
import time
import unicodedata

from resources.lib.api import ApiError, AuthError

WORKERS = 6


def fold(text):
    """Case- and accent-insensitive key: 'Café' -> 'cafe'."""
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).casefold()


def matches(album, query):
    """True when every word of the query appears in the album's title or location."""
    hay = fold("%s %s" % (album.get("Title") or "", album.get("Location") or ""))
    return all(term in hay for term in fold(query).split())


def day(date):
    """'2008-08-02T10:00:00Z' -> '2008-08-02' ('' when unknown)."""
    return (date or "")[:10]


def sort_albums(albums, dates, mode):
    """Sort by last-photo date ('newest' / 'oldest') or by 'name'.

    Albums without a known date (empty albums, failed lookups) always go last,
    in name order. Ties are broken by name.
    """
    by_name = sorted(albums, key=lambda a: fold(a.get("Title") or a.get("UID") or ""))
    if mode == "name":
        return by_name
    dated = [a for a in by_name if dates.get(a.get("UID"))]
    undated = [a for a in by_name if not dates.get(a.get("UID"))]
    dated.sort(key=lambda a: dates[a["UID"]][:19], reverse=(mode != "oldest"))  # stable: ties stay by name
    return dated + undated


def load_all(api, atype="album", batch=500, max_batches=100):
    """Every album of a type (paged requests, so large libraries work)."""
    out, offset = [], 0
    for _ in range(max_batches):
        res = api.albums(batch, offset, atype)
        items = res["items"]
        out += items
        offset += res["rows"]
        if res["rows"] < batch or not items:
            break
    return [a for a in out if a.get("UID")]


def last_photo_dates(api, cache, albums, log, progress=None, max_age=86400, workers=WORKERS, stats=None):
    """{album uid: ISO date of its newest photo ('' if empty or unknown)}.

    Reads only what changed since the last call (see module docstring). `progress(done, total)`
    is called from the calling thread while album dates are being fetched.
    Raises AuthError if the session expired (so the caller can log in again and retry).
    """
    key = "albumdates|%s" % api.base
    stored = cache.get_json(key)
    if not isinstance(stored, dict):
        stored = {}
    now = time.time()
    dates, todo = {}, []
    for a in albums:
        uid, count = a["UID"], a.get("PhotoCount") or 0
        if count == 0:
            dates[uid] = ""
            continue
        e = stored.get(uid)
        if isinstance(e, dict) and e.get("u") == a.get("UpdatedAt") and e.get("n") == count \
                and now - e.get("ts", 0) < max_age:
            dates[uid] = e.get("d") or ""
        else:
            todo.append(a)

    if stats is not None:
        stats["fetched"] = len(todo)
    fresh: dict = {}
    auth_error: list = []
    lock = threading.Lock()
    pending = list(todo)

    def worker():
        while True:
            with lock:
                if not pending or auth_error:
                    return
                a = pending.pop()
            try:
                d = api.last_photo_date(a["UID"])
            except AuthError as e:
                with lock:
                    auth_error.append(e)
                return
            except ApiError as e:
                log.warning("Cannot read the last photo date of album %s: %s" % (a["UID"], e))
                d = None
            with lock:
                fresh[a["UID"]] = d

    if todo:
        log.debug("Reading the last photo date of %d album(s) (%d cached)" % (len(todo), len(albums) - len(todo)))
        threads = [threading.Thread(target=worker) for _ in range(max(1, min(workers, len(todo))))]
        for t in threads:
            t.daemon = True
            t.start()
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(0.05)
            if progress:
                progress(len(fresh), len(todo))
        if progress:
            progress(len(fresh), len(todo))
        if auth_error:
            raise auth_error[0]

    for a in todo:
        d = fresh.get(a["UID"])
        dates[a["UID"]] = d or ""
        if d is not None:  # failed lookups are not stored, so they are retried next time
            stored[a["UID"]] = {"u": a.get("UpdatedAt"), "n": a.get("PhotoCount"), "d": d, "ts": now}
    keep = {a["UID"] for a in albums}
    cache.set_json(key, {uid: e for uid, e in stored.items() if uid in keep})  # also refreshes the file's age
    return dates
