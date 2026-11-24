"""Property-based tests (Hypothesis): invariants checked on many generated inputs.

Deterministic by default (CI). To hunt for new counter-examples run with KODIPRISM_EXPLORE=1
(random seed, ten times more examples).
"""
import json
import os
import tempfile

import kodi_mocks  # installs the fake Kodi modules
from hypothesis import given, settings, strategies as st

from resources.lib import api as api_mod, catalog, slideshow_fx as fx
from resources.lib.logger import AddonLog

assert kodi_mocks.ADDON_DIR
EXPLORE = bool(os.environ.get("KODIPRISM_EXPLORE"))
CFG = settings(max_examples=3000 if EXPLORE else 300, derandomize=not EXPLORE, deadline=None, database=None)
ok = 0


def prop(fn):
    """Run a @given-decorated property once under the shared settings and count it."""
    global ok
    CFG(fn)()
    ok += 1
    print("PASS", fn.__name__)


# ---- the server address is either rejected with ApiError or turned into a stable, usable base URL
@given(st.text(max_size=60))
def addresses_are_rejected_or_stable(raw):
    try:
        out = api_mod.normalize_base_url(raw)
    except api_mod.ApiError:
        return
    assert out.startswith(("http://", "https://")) and not out.endswith("/")
    assert not any(c.isspace() or ord(c) < 32 for c in out), repr(out)
    assert api_mod.normalize_base_url(out) == out          # idempotent


# ---- search: folding is stable and any piece of a title finds that title
@given(st.text(max_size=40))
def fold_is_idempotent(t):
    assert catalog.fold(catalog.fold(t)) == catalog.fold(t)


@given(st.text(min_size=1, max_size=30), st.data())
def a_piece_of_a_title_matches_it(title, data):
    i = data.draw(st.integers(0, len(title) - 1)); j = data.draw(st.integers(i + 1, len(title)))
    piece = title[i:j]
    if not catalog.fold(piece).strip():
        return
    assert catalog.matches({"Title": title}, piece), (title, piece)


# ---- sorting
UIDS = st.text(alphabet="abcdef", min_size=1, max_size=3)
DATES = st.sampled_from(["", "2008-08-02T10:00:00Z", "2020-01-01T00:00:00Z", "2020-01-01T00:00:01Z", "2021-06-01T10:00:00.123Z"])


@given(st.lists(st.fixed_dictionaries({"UID": UIDS, "Title": st.text(max_size=10)}), unique_by=lambda a: a["UID"], max_size=12),
       st.dictionaries(UIDS, DATES, max_size=12), st.sampled_from(["newest", "oldest", "name"]))
def sorting_keeps_every_album_in_a_sensible_order(albums, dates, mode):
    out = catalog.sort_albums(albums, dates, mode)
    assert sorted(a["UID"] for a in out) == sorted(a["UID"] for a in albums)             # nothing lost or duplicated
    assert catalog.sort_albums(out, dates, mode) == out                                   # stable / idempotent
    names = lambda items: [catalog.fold(a["Title"] or a["UID"]) for a in items]   # an untitled album is shown (and sorted) by its UID
    if mode == "name":
        assert names(out) == sorted(names(out))
        return
    k = sum(1 for a in out if dates.get(a["UID"]))
    assert all(dates.get(a["UID"]) for a in out[:k]) and not any(dates.get(a["UID"]) for a in out[k:])   # undated last
    keys = [dates[a["UID"]][:19] for a in out[:k]]
    assert keys == sorted(keys, reverse=(mode == "newest"))
    assert names(out[k:]) == sorted(names(out[k:]))


# ---- logging never lets a registered secret through
TOKENS = st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")), min_size=4, max_size=16)


@given(TOKENS, st.text(max_size=40))
def secrets_never_survive_redaction(secret, noise):
    log = AddonLog("x", tempfile.mkdtemp(), debug=True); log.add_secret(secret)
    out = log.redact("%s %s /api/v1/t/h1/%s/tile_500 /dl/h1?t=%s %s" % (noise, secret, secret, secret, noise))
    assert secret not in out
    assert log.redact(out) == out                                                          # idempotent


# ---- pan/zoom guard: whatever happens, the user's original Kodi setting comes back
OPS = st.lists(st.sampled_from(["prepare", "tick_on", "tick_off", "restore", "wait", "fail_set", "ok_set", "fail_get", "ok_get"]), max_size=40)


@given(st.booleans(), OPS)
def pan_zoom_setting_always_returns_to_its_original_value(initial, ops):
    kodi, flags, now = {"v": initial}, {"fail_set": False, "fail_get": False}, [1000.0]

    def rpc(raw):
        req = json.loads(raw); p = req["params"]
        if req["method"] == "Settings.GetSettingValue":
            return json.dumps({"error": {}} if flags["fail_get"] else {"result": {"value": kodi["v"]}})
        if flags["fail_set"]:
            return json.dumps({"error": {}})
        kodi["v"] = p["value"]; return json.dumps({"result": True})

    class Log:
        def info(s, m): pass
        warning = debug = error = info

    guard = fx.Guard(rpc, tempfile.mkdtemp(), Log(), lambda: now[0])
    for op in ops:
        if op == "prepare": guard.prepare()
        elif op == "tick_on": guard.tick(True)
        elif op == "tick_off": guard.tick(False)
        elif op == "restore": guard.restore()
        elif op == "wait": now[0] += fx.GRACE / 2
        elif op in ("fail_set", "ok_set", "fail_get", "ok_get"):
            flags[op[5:] if op.startswith("fail_") else op[3:]] = op.startswith("fail_")
    flags["fail_set"] = flags["fail_get"] = False
    guard.restore()                                            # what the service does on exit
    assert kodi["v"] == initial and not guard.pending(), (initial, ops)


for fn in (addresses_are_rejected_or_stable, fold_is_idempotent, a_piece_of_a_title_matches_it,
           sorting_keeps_every_album_in_a_sensible_order, secrets_never_survive_redaction,
           pan_zoom_setting_always_returns_to_its_original_value):
    prop(fn)
print("ALL %d PROPERTIES HELD" % ok)
