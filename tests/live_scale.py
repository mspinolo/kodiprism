"""Scale probe against a REAL PhotoPrism: ~2100 photos, 100 albums (see .github/workflows/live.yml).

    PP_URL=http://127.0.0.1:2342 PP_PASS=... python3 tests/live_scale.py report.json

Measures what the owner's choices depend on: is a request for 2000 photos accepted and ordered, how long
does the album catalogue (date of the newest photo of every album) take to load, and is the second load
served from the cache. Writes facts and a list of `problems`; exits 1 if there are any.
"""
import json
import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin.image.photoprism"))
from resources.lib import api as api_mod, cache as cache_mod, catalog  # noqa: E402

BASE = os.environ.get("PP_URL", "http://127.0.0.1:2342")
PASSWORD = os.environ.get("PP_PASS", "ci-test-password-1")
R, PROBLEMS = {}, []
a = api_mod.PhotoPrism(BASE, timeout=120)
a.login_password("admin", PASSWORD)


def expect(ok, text):
    if not ok:
        PROBLEMS.append(text)
    return ok


def timed(fn):
    t = time.time()
    out = fn()
    return out, round(time.time() - t, 2)


# 1. how many photos, and are big requests accepted?
total = 0
while True:
    res = a._req("GET", "/photos", params={"count": 1000, "offset": total, "merged": "true", "order": "newest", "public": "true"}, with_rows=True)
    total += res["rows"]
    if res["rows"] < 1000:
        break
R["photos_total"] = total
expect(total >= 2000, "only %d photos indexed (expected ~2110)" % total)
for count in (2000, 5000):
    rows, secs = timed(lambda c=count: a.photos(c, 0, order="newest"))
    dates = [(p.get("TakenAt") or "")[:19] for p in rows["items"]]
    R["photos_count_%d" % count] = {"returned": len(dates), "seconds": secs, "newest_first": dates == sorted(dates, reverse=True),
                                   "first": dates[:1], "last": dates[-1:]}
    expect(len(dates) == min(count, total), "count=%d returned %d of %d" % (count, len(dates), min(count, total)))
    expect(dates == sorted(dates, reverse=True), "count=%d is not strictly newest first" % count)
oldest, secs = timed(lambda: a.photos(2000, 0, order="oldest"))
d = [(p.get("TakenAt") or "")[:19] for p in oldest["items"]]
R["photos_oldest_2000"] = {"returned": len(d), "seconds": secs, "oldest_first": d == sorted(d)}
expect(d == sorted(d), "oldest 2000 not in order")
rnd, secs = timed(lambda: a.photos(2000, 0, order="random"))
R["photos_random_2000"] = {"returned": len(rnd["items"]), "seconds": secs}

# 2. 100 albums with known content
newest = a.photos(400, 0, order="newest")["items"]
rng = random.Random(7)
expected, created = {}, 0
t0 = time.time()
for i in range(100):
    picks = rng.sample(newest, 5)
    alb = a._req("POST", "/albums", body={"Title": "Scale %03d" % i})
    a._req("POST", "/albums/%s/photos" % alb["UID"], body={"photos": [p["UID"] for p in picks]})
    expected[alb["UID"]] = max((p.get("TakenAt") or "")[:19] for p in picks)
    created += 1
R["albums_created"] = {"count": created, "seconds": round(time.time() - t0, 1)}

# 3. the add-on's catalogue on a cold and a warm cache
albums, secs_list = timed(lambda: catalog.load_all(a))
R["albums_listed"] = {"count": len(albums), "seconds": secs_list}
expect(len(albums) >= 100, "album listing returned %d" % len(albums))
c = cache_mod.DiskCache(tempfile.mkdtemp(), max_mb=50, ttl_hours=24)
st1 = {}
dates, cold = timed(lambda: catalog.last_photo_dates(a, c, albums, a.log, stats=st1))
st2 = {}
dates2, warm = timed(lambda: catalog.last_photo_dates(a, c, albums, a.log, stats=st2))
bad = [u for u, d0 in expected.items() if (dates.get(u) or "")[:19] != d0]
R["catalogue"] = {"cold_seconds": cold, "warm_seconds": warm, "cold_stats": st1, "warm_stats": st2,
                  "wrong_dates": len(bad), "checked": len(expected)}
expect(not bad, "%d album dates differ from the expected newest photo" % len(bad))
expect(dates2 == dates, "warm catalogue differs from the cold one")
expect(warm < max(1.0, cold / 3), "warm load (%.2fs) is not much faster than cold (%.2fs)" % (warm, cold))

R["problems"] = PROBLEMS
with open(sys.argv[1] if len(sys.argv) > 1 else "scale_report.json", "w") as fh:
    json.dump(R, fh, indent=1, default=str)
print("scale probe: %d problems" % len(PROBLEMS))
for p in PROBLEMS:
    print(" -", p)
sys.exit(1 if PROBLEMS else 0)
