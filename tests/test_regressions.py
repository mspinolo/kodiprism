"""Regression tests for the bugs fixed in 1.0.1."""

import os, tempfile
from support import PROFILE, SETTINGS, srv, cache, check, run
import subprocess, sys


def test_auth_fingerprint_is_stable():
    """The auth fingerprint does not depend on hash randomisation and holds no plaintext secret."""
    snippet = ("import sys; sys.path.insert(0, %r); import kodi_mocks; kodi_mocks.SETTINGS.update(password='pw');"
               "from resources.lib import plugin; print(plugin.Plugin(['plugin://x/', '1', ''])._auth_fingerprint())"
               % os.path.dirname(os.path.abspath(__file__)))
    fps = [subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True,
                          env=dict(os.environ, PYTHONHASHSEED=seed)).stdout.strip() for seed in ("1", "2")]
    check(fps[0] and fps[0] == fps[1] and "pw" not in fps[0], "auth fingerprint stable across processes, no plaintext secret")


def test_session_file_is_private():
    """session.json is created with mode 0600."""
    SETTINGS.update(server_url="http://127.0.0.1:%d" % srv.server_port, auth_mode="0", username="admin", password="pw", token="", cache_path="")
    sess = os.path.join(PROFILE, "session.json")
    if os.path.exists(sess): os.remove(sess)
    run("?action=albums&type=album")
    check(os.path.exists(sess) and (os.stat(sess).st_mode & 0o777) == 0o600, "session.json created with mode 0600")


def test_eviction_only_drops_tmp_files():
    """Eviction drops leftover *.tmp files by name, not everything under a '.tmp' path."""
    d = os.path.join(tempfile.mkdtemp(), ".tmpcache"); c = cache.DiskCache(d, max_mb=50, ttl_hours=24)
    c.put_image("keep", b"x" * 100); stale = os.path.join(d, "img", "abc.jpg.tmp123"); open(stale, "wb").write(b"y")
    c.evict()
    check(c.image_path("keep") is not None and not os.path.exists(stale), "evict keeps live files under a '.tmp' path, drops leftover tmp files")
