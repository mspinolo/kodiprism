"""Diagnostics (1.0.2): address checks, error messages, logging, test connection, secrets never logged."""

import os, tempfile, time, requests
from support import LOG, srv, plugin, api_mod, logger_mod, GOOD, LOGFILE, DEAD, check, run, reset, read_log


def test_address_normalisation():
    """Addresses are normalised; unusable ones are rejected."""
    n = api_mod.normalize_base_url
    check(n("192.168.1.10:2342") == "http://192.168.1.10:2342" and n("  http://h:2342/ ") == "http://h:2342"
          and n("https://foto.lan/api/v1/") == "https://foto.lan" and n("HTTPS://Foto.lan:8443/photos/") == "https://Foto.lan:8443/photos",
          "address normalisation: scheme added, spaces/slash/'/api/v1' removed, sub-path kept")
    rejected = 0
    for u in ("", "   ", "ftp://h", "http://", "http://h:abc", "http://admin:pw@h:2342"):
        try: n(u)
        except api_mod.ApiError: rejected += 1
    check(rejected == 6, "unusable addresses (empty, ftp, no host, bad port, embedded credentials) are rejected")


def test_error_messages():
    """Every kind of failure becomes a clear message."""
    R = requests.exceptions
    fe = lambda e: api_mod.friendly_error(e, "http://foto.lan:2342", 7)
    cases = [(R.ConnectionError("Failed to establish a new connection: [Errno 111] Connection refused"), "refused by foto.lan:2342"),
             (R.ConnectionError("Failed to resolve 'foto.lan' ([Errno -2] Name or service not known)"), "Cannot resolve host name 'foto.lan'"),
             (R.ConnectionError("[Errno 113] No route to host"), "unreachable"),
             (R.ConnectionError("('Connection aborted.', RemoteDisconnected('Remote end closed connection'))"), "closed the connection"),
             (R.SSLError("[SSL: WRONG_VERSION_NUMBER] wrong version number"), "does not speak HTTPS"),
             (R.SSLError("CERTIFICATE_VERIFY_FAILED self-signed certificate"), "Verify TLS certificates"),
             (R.ConnectTimeout("timed out"), "Timeout after 7s"), (R.ReadTimeout("timed out"), "Timeout after 7s"),
             (R.MissingSchema("Invalid URL"), "Invalid server address"),
             (R.ChunkedEncodingError("x"), "failed (ChunkedEncodingError)")]
    wrong = [(type(e).__name__, want, fe(e)) for e, want in cases if want not in fe(e)]
    check(not wrong, "friendly_error: %d failure kinds -> clear messages %s" % (len(cases), wrong or ""))
    try: api_mod.PhotoPrism("127.0.0.1:%d" % DEAD, timeout=3).ping(); msg = ""
    except api_mod.ApiError as e: msg = str(e)
    check("Connection refused by 127.0.0.1:%d" % DEAD in msg, "real closed port (address typed without http://) -> '%s'" % msg)
    ms, body = api_mod.PhotoPrism(GOOD).ping()
    check(isinstance(ms, int) and "operational" in body, "ping() reaches /api/v1/status without credentials")
    a = api_mod.PhotoPrism(GOOD); a.login_password("admin", "pw")
    try: a._req("GET", "/nothing"); msg = ""
    except api_mod.ApiError as e: msg = str(e)
    check(msg.startswith("Not found (404) for /nothing"), "HTTP 404 -> hint that the address may not be PhotoPrism")
    try: api_mod.PhotoPrism(GOOD).login_password("admin", "bad"); msg = ""
    except api_mod.AuthError as e: msg = str(e)
    check(msg.startswith("Authentication failed (401)") and "username/password" in msg, "HTTP 401 -> authentication hint")


def test_logger():
    """Logger: redaction, levels, rotation, clear."""
    lg = logger_mod.AddonLog("x", tempfile.mkdtemp(), debug=True); lg.add_secret("S3cretPW", "tok-12345")
    red = lg.redact("GET http://h/api/v1/t/abc123/PREVTOKEN/tile_500 /albums/a1/t/PREVTOKEN/tile_224 /videos/h1/PREVTOKEN/avc "
                    "/dl/h1?t=DLTOKEN pw=S3cretPW Bearer tok-12345")
    check(not any(x in red for x in ("PREVTOKEN", "DLTOKEN", "S3cretPW", "tok-12345")) and "abc123" in red and "tile_500" in red,
          "redaction masks tokens/secrets but keeps hashes and sizes: %s" % red)
    lg = logger_mod.AddonLog("x", tempfile.mkdtemp(), debug=False); lg.debug("hidden-line"); lg.info("shown-line")
    check("hidden-line" not in lg.tail() and " INFO " in lg.tail() and "shown-line" in lg.tail(), "DEBUG lines are dropped unless debug logging is on")
    lg.debug_enabled = True; lg.debug("now-visible"); check("now-visible" in lg.tail(), "DEBUG lines recorded when enabled")
    for _ in range(300): lg.info("x" * 1000)
    check(os.path.exists(lg.path + ".1") and os.path.getsize(lg.path) <= logger_mod.MAX_BYTES + 2000, "log file rotates at 256 KB")
    lg.clear(); check(not os.path.exists(lg.path) and not os.path.exists(lg.path + ".1"), "clear() removes the log files")


def test_test_connection():
    """The 'Test connection' screen for the common situations."""
    reset(); run("?action=test_connection"); txt = LOG["text"][-1][1]
    check("[FAIL]" not in txt and "Server reachable in" in txt and "Logged in as 'admin'" in txt and "PhotoPrism version: test-1.2" in txt
          and "Library readable" in txt and "All checks passed" in txt, "test connection: everything OK")
    reset(password="wrong"); run("?action=test_connection"); txt = LOG["text"][-1][1]
    check("Server reachable" in txt and "[FAIL] Authentication failed (401)" in txt and "All checks passed" not in txt, "test connection: reachable but wrong password")
    reset(server_url="127.0.0.1:%d" % DEAD); run("?action=test_connection"); txt = LOG["text"][-1][1]
    check("corrected automatically" in txt and "[FAIL] Connection refused by 127.0.0.1:%d" % DEAD in txt, "test connection: typo'd port, address auto-corrected")
    reset(server_url=""); run("?action=test_connection"); txt = LOG["text"][-1][1]
    check("[FAIL] Server address is empty" in txt, "test connection: empty address")
    reset(auth_mode="1", token=""); run("?action=test_connection"); txt = LOG["text"][-1][1]
    check("[FAIL] No app password" in txt, "test connection: app-password mode without token")


def test_host_port_without_scheme():
    """Browsing works with 'host:port' typed without http://."""
    reset(server_url="127.0.0.1:%d" % srv.server_port); run("?action=albums&type=album")
    check(LOG["end"] == [True] and "normalised" in read_log(), "browsing works with 'host:port' typed without http:// (normalisation logged)")


def test_debug_log_never_leaks_secrets():
    """A full debug session writes no password, token or preview token."""
    reset(debug_log="true", password="S3cretPassw0rd", cache_path=tempfile.mkdtemp())
    for q in ("", "?action=albums&type=album", "?action=photos", "?action=play&hash=h1", "?action=slideshow&album=a1", "?action=test_connection"):
        run(q)
    time.sleep(0.6)  # let the prefetch threads finish
    logtxt = read_log()
    check("S3cretPassw0rd" not in logtxt and "sess-tok" not in logtxt and "/prev/" not in logtxt, "full debug session: no password, session token or preview token in debug.log")
    check("GET /albums" in logtxt and "-> HTTP 200 (" in logtxt and "/t/h0/***/" in logtxt and "Logged in as 'admin'" in logtxt,
          "debug log has one line per request with status and timing (tokens masked)")
    reset(debug_log="true", auth_mode="1", token="app-pass"); run("?action=albums&type=album")
    check("app-pass" not in read_log() and "app-pass" not in " ".join(m for _, m in LOG["klog"]), "app password never logged (debug.log and kodi.log)")
    check(any(m.startswith("[plugin.image.photoprism]") for _, m in LOG["klog"]), "messages also go to kodi.log with the add-on id prefix")


def test_deliberate_slip_is_masked():
    """Secrets are masked even when logged by mistake."""
    reset(debug_log="true", password="S3cretPassw0rd", token="tokenvalue123", cache_path=tempfile.mkdtemp())
    pl = plugin.Plugin(["plugin://plugin.image.photoprism/", "1", ""]); pl.connect()
    pl.log.info("accidental slip: S3cretPassw0rd tokenvalue123 sess-tok")
    lt = read_log()
    check("accidental slip" in lt and not any(x in lt for x in ("S3cretPassw0rd", "tokenvalue123", "sess-tok")),
          "configured password, app password and session token are masked even if logged by mistake")


def test_log_viewer_and_clear():
    """View add-on log / Clear add-on log."""
    reset(debug_log="true", auth_mode="0", password="pw"); run("?action=albums&type=album"); run("?action=show_log")
    h, t = LOG["text"][-1]
    check("Add-on log:" in t and "kodi.log" in t and "Debug logging: ON" in t and "Logged in as 'admin'" in t, "View add-on log shows header and entries")
    run("?action=clear_log"); check(not os.path.exists(LOGFILE) and any("cleared" in m for m in LOG["notes"]), "Clear add-on log")
    reset(); run("?action=show_log"); check("(the log is empty)" in LOG["text"][-1][1] and "Debug logging: OFF" in LOG["text"][-1][1], "empty log message, debug OFF shown")


def test_unexpected_exception():
    """An unexpected exception: notification, traceback in the log, failed directory."""
    orig_albums = plugin.Plugin.albums
    def boom(self): raise RuntimeError("kaboom")
    plugin.Plugin.albums = boom
    reset(); run("?action=albums&type=album")
    plugin.Plugin.albums = orig_albums
    check(LOG["end"] == [False] and any("Unexpected error" in m for m in LOG["notes"]) and "RuntimeError: kaboom" in read_log() and "Traceback" in read_log(),
          "unexpected exception -> notification + traceback in log + failed directory")
