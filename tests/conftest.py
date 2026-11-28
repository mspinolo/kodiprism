"""pytest wiring: fake Kodi modules on the path, live tests excluded, shared state reset before every test."""
import os
import shutil
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
pytest.register_assert_rewrite("support")

import kodi_mocks  # noqa: E402  -- installs the fake xbmc* modules before the add-on is imported
assert kodi_mocks.ADDON_DIR

# need a real PhotoPrism (see AGENTS.md / .github/workflows/live.yml); never collected by `pytest`
collect_ignore = ["test_live.py", "live_probe.py", "live_scale.py", "live_auth.py"]


@pytest.fixture(autouse=True)
def clean_state():
    """Every test starts from the same Kodi, add-on settings and fake server."""
    import support as s
    s.SETTINGS.clear(); s.SETTINGS.update(s.DEFAULT_SETTINGS, server_url=s.GOOD)
    s.MODE.clear(); s.MODE.update(s.DEFAULT_MODE)
    for b, d in zip(s.BIG, s.DEFAULT_BIG): b.clear(); b.update(d)
    s.HITS.update(session=0, photos=0, thumb=0, album_dates=0); s.HITS["albums_params"].clear(); s.HITS["photos_params"].clear()
    s.KBCFG.update(text="label:cat", ok=True); s.SELECT["value"] = 0; s.YESNO["value"] = False; s.LANG["code"] = "en_gb"
    s.WIN.clear(); s.ACTIVE["slideshow"] = False
    s.KODI_SETTINGS.clear(); s.KODI_SETTINGS.update(s.DEFAULT_KODI_SETTINGS)
    s.RPC.update(calls=[], fail_get=False, fail_set=False); s.MONITOR.update(seen=[], ticks=1)
    for k in s.LOG: s.LOG[k].clear()
    for d in ("cache", "photoprism_cache"):   # the default cache lives in the profile folder
        shutil.rmtree(os.path.join(s.PROFILE, d), ignore_errors=True)
    for f in ("session.json", "fx_restore.json", "debug.log", "debug.log.1", "stats.json"):
        try: os.remove(os.path.join(s.PROFILE, f))
        except OSError: pass
    yield


def pytest_collection_modifyitems(config, items):
    """KODIPRISM_SHUFFLE=<seed> runs the tests in a random (reproducible) order, to prove they are independent."""
    seed = os.environ.get("KODIPRISM_SHUFFLE")
    if seed:
        import random
        random.Random(seed).shuffle(items)
