"""Probe a REAL PhotoPrism server and write what it does to a JSON report (no assertions).

    PP_URL=http://127.0.0.1:2342 PP_PASS=... python3 tests/live_probe.py report.json

Used while developing tests/test_live_server.py: it records facts (status codes, orders, fields) so that the
assertions can be written against reality instead of memory. Expects the photos of tools/make_test_photos.py
to be indexed already.
"""
import json
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin.image.photoprism"))
from resources.lib import api as api_mod  # noqa: E402

BASE = os.environ.get("PP_URL", "http://127.0.0.1:2342")
PASSWORD = os.environ.get("PP_PASS", "ci-test-password-1")
R = {}
a = api_mod.PhotoPrism(BASE, timeout=60)


def step(name):
    def deco(fn):
        try:
            R[name] = fn()
        except Exception as e:  # keep going: one failing step must not hide the others
            R[name] = {"EXC": "%s: %s" % (type(e).__name__, str(e)[:300])}
        return fn
    return deco


def raw(method, path, **kw):
    """Plain request with the current auth headers; returns (response)."""
    return a.http.request(method, BASE + "/api/v1" + path, headers=a._headers(), timeout=60, **kw)


@step("status_without_login")
def _():
    r = requests.get(BASE + "/api/v1/status", timeout=30)
    return {"code": r.status_code, "body": r.text[:120], "content_type": r.headers.get("Content-Type")}


@step("unauthenticated_albums")
def _():
    r = requests.get(BASE + "/api/v1/albums", params={"count": 1}, timeout=30)
    r2 = requests.get(BASE + "/api/v1/albums", params={"count": 1}, headers={"Authorization": "Bearer nonsense"}, timeout=30)
    r3 = requests.post(BASE + "/api/v1/session", json={"username": "admin", "password": "wrong"}, timeout=30)
    return {"no_token": r.status_code, "bad_token": r2.status_code, "bad_password": [r3.status_code, r3.text[:100]]}


@step("login")
def _():
    data = a.login_password("admin", PASSWORD)
    cfg = data.get("config") or {}
    return {"top_keys": sorted(data)[:30], "config_key_count": len(cfg), "version": cfg.get("version"),
            "has_previewToken": bool(a.preview_token), "has_downloadToken": bool(a.download_token),
            "token_len": len(a.token or ""), "some_config_keys": sorted(cfg)[:25]}


PHOTOS = []


@step("photos_basic")
def _():
    global PHOTOS
    PHOTOS = a._req("GET", "/photos", params={"count": 100, "order": "oldest", "merged": "true"})
    p = PHOTOS[0] if PHOTOS else {}
    return {"count": len(PHOTOS), "keys": sorted(p), "first": {k: p.get(k) for k in (
        "UID", "Hash", "Type", "Title", "TakenAt", "TakenAtLocal", "Width", "Height", "Private", "Favorite", "CameraMake", "CameraModel", "FileName", "OriginalName")},
        "taken_oldest_first": [x.get("TakenAt") for x in PHOTOS]}


ALBUMS = {}


@step("create_albums")
def _():
    def uids(prefix):
        return [p["UID"] for p in PHOTOS if (p.get("TakenAt") or "").startswith(prefix)]
    spec = {"Bretagna": uids("2008-08"), "Roma": uids("2019-03"), "Cafe": uids("2015-07"),
            "Misto": uids("2008-08")[:1] + uids("2022-11"), "Vuoto": []}
    out = {}
    for title, ids in spec.items():
        alb = a._req("POST", "/albums", body={"Title": title})
        ALBUMS[title] = alb["UID"]
        added = None
        if ids:
            added = a._req("POST", "/albums/%s/photos" % alb["UID"], body={"photos": ids})
        out[title] = {"uid": alb["UID"], "created_keys": sorted(alb)[:40], "photos_added": len(ids), "add_response": str(added)[:120]}
    return out


@step("albums_listing")
def _():
    lst = a._req("GET", "/albums", params={"count": 100, "type": "album", "order": "name"}, with_rows=True)
    return {"rows": lst["rows"], "titles": [x.get("Title") for x in lst["items"]],
            "per_album": [{k: x.get(k) for k in ("Title", "PhotoCount", "Year", "Month", "Day", "Thumb", "CreatedAt", "UpdatedAt", "Order", "Favorite")} for x in lst["items"]],
            "all_keys": sorted(lst["items"][0]) if lst["items"] else []}


@step("album_order_values")
def _():
    out = {}
    for order in ("name", "newest", "oldest", "added", "edited", "favorites", "title", "random", "bogus"):
        r = raw("GET", "/albums", params={"count": 100, "type": "album", "order": order})
        out[order] = [r.status_code] + ([[x.get("Title") for x in r.json()]] if r.status_code == 200 else [r.text[:80]])
    return out


@step("last_photo_date_vs_expected")
def _():
    expect = {"Bretagna": "2008-08-05", "Roma": "2019-03-12", "Cafe": "2015-07-02", "Misto": "2022-11-23", "Vuoto": ""}
    out = {}
    for title, uid in ALBUMS.items():
        got = a.last_photo_date(uid)
        out[title] = {"got": got, "expected_day": expect[title], "match": got[:10] == expect[title]}
    return out


@step("photo_order_values")
def _():
    out = {}
    for order in ("newest", "oldest", "added", "edited", "name", "random", "relevance", "bogus"):
        r = raw("GET", "/photos", params={"count": 20, "order": order, "merged": "true", "public": "true"})
        out[order] = [r.status_code] + ([[x.get("TakenAt", "")[:10] for x in r.json()][:12]] if r.status_code == 200 else [r.text[:80]])
    r1 = [x["UID"] for x in raw("GET", "/photos", params={"count": 20, "order": "random"}).json()]
    r2 = [x["UID"] for x in raw("GET", "/photos", params={"count": 20, "order": "random"}).json()]
    out["random_two_draws_identical"] = r1 == r2
    return out


@step("photo_filters")
def _():
    out = {}
    for q in ("month:11 day:23", "month:11", "year:2008", "type:image", "type:video", "favorite:true", "label:nothingmatches"):
        r = raw("GET", "/photos", params={"count": 50, "q": q, "merged": "true"})
        out[q] = [r.status_code, [x.get("TakenAt", "")[:10] for x in r.json()] if r.status_code == 200 else r.text[:80]]
    return out


@step("slideshow_style_request")
def _():
    out = {}
    for count in (500, 2000, 100000):
        r = raw("GET", "/photos", params={"count": count, "offset": 0, "q": "type:image", "order": "newest", "merged": "true", "public": "true"})
        out[str(count)] = [r.status_code, len(r.json()) if r.status_code == 200 else r.text[:80], r.headers.get("X-Count")]
    return out


@step("album_cover_endpoints")
def _():
    lst = a._req("GET", "/albums", params={"count": 100, "type": "album"})
    out = {}
    for x in lst:
        uid, thumb = x["UID"], x.get("Thumb")
        r1 = a.http.get("%s/api/v1/albums/%s/t/%s/tile_500" % (BASE, uid, a.preview_token), timeout=60)
        r2 = a.http.get("%s/api/v1/t/%s/%s/tile_500" % (BASE, thumb, a.preview_token), timeout=60) if thumb else None
        out[x["Title"]] = {"thumb_field": thumb, "album_endpoint": [r1.status_code, r1.headers.get("Content-Type"), len(r1.content)],
                           "thumb_endpoint": ([r2.status_code, r2.headers.get("Content-Type"), len(r2.content)] if r2 is not None else None)}
    return out


@step("public_param_and_private_photo")
def _():
    target = [p for p in PHOTOS if (p.get("TakenAt") or "").startswith("2022-01-05")]
    if not target:
        return {"skip": "photo not found"}
    uid = target[0]["UID"]
    upd = raw("PUT", "/photos/%s" % uid, json={"Private": True})
    def n(**kw):
        r = raw("GET", "/photos", params=dict({"count": 100, "merged": "true"}, **kw))
        return [r.status_code, len(r.json()) if r.status_code == 200 else r.text[:80]]
    out = {"put_private": [upd.status_code, upd.text[:80]], "no_public_param": n(), "public_true": n(public="true"),
           "public_false": n(public="false"), "private_true": n(private="true")}
    raw("PUT", "/photos/%s" % uid, json={"Private": False})
    out["after_unprivate_public_true"] = n(public="true")
    return out


@step("merged_and_xcount")
def _():
    r = raw("GET", "/photos", params={"count": 3, "merged": "true", "order": "oldest"})
    r2 = raw("GET", "/photos", params={"count": 3, "order": "oldest"})
    return {"merged_true": [len(r.json()), r.headers.get("X-Count")], "merged_absent": [len(r2.json()), r2.headers.get("X-Count")]}


@step("first_album_full_json")
def _():
    lst = a._req("GET", "/albums", params={"count": 1, "type": "album", "order": "name"})
    return lst[0] if lst else {}


@step("other_album_types")
def _():
    out = {}
    for t in ("folder", "moment", "month", "state"):
        r = raw("GET", "/albums", params={"count": 20, "type": t, "order": "newest"})
        out[t] = [r.status_code, [(x.get("Title"), x.get("Year"), x.get("Month"), x.get("PhotoCount")) for x in r.json()][:8]] if r.status_code == 200 else [r.status_code, r.text[:80]]
    return out


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "live_report.json"
    with open(path, "w") as fh:
        json.dump(R, fh, indent=1, default=str)
    print("probe done: %d steps, %d with exceptions" % (len(R), sum(1 for v in R.values() if isinstance(v, dict) and "EXC" in v)))
