# -*- coding: utf-8 -*-
"""Minimal PhotoPrism REST client (/api/v1)."""
import json
import time

from urllib.parse import urlencode, quote, urlparse

import requests


class ApiError(Exception):
    pass


class AuthError(ApiError):
    pass


class _NullLog(object):
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def normalize_base_url(url):
    """Turn what the user typed into a usable base URL.

    '192.168.1.10:2342' -> 'http://192.168.1.10:2342'; surrounding spaces, a trailing '/'
    and a pasted '/api/v1' are removed. Raises ApiError for addresses that cannot work.
    """
    raw = (url or "").strip()
    if not raw:
        raise ApiError("Server address is empty - set it in the add-on settings")
    u = raw if "://" in raw else "http://" + raw
    if any(c.isspace() or ord(c) < 32 for c in u):
        raise ApiError("Invalid server address '%s' - it must not contain spaces" % raw.encode("ascii", "replace").decode())
    try:
        parts = urlparse(u)
        parts.port
    except ValueError:  # e.g. an unbalanced '[' of an IPv6 address, or a non-numeric port
        raise ApiError("Invalid server address or port '%s' - use the form http://host:2342" % raw)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ApiError("Invalid server address '%s' - use the form http://host:2342" % raw)
    if parts.username or parts.password:
        raise ApiError("Do not put username/password in the address - use the login fields")
    path = parts.path.rstrip("/")
    if path.endswith("/api/v1"):
        path = path[:-len("/api/v1")]
    return "%s://%s%s" % (parts.scheme.lower(), parts.netloc, path)


def friendly_error(exc, base, timeout):
    """One short, actionable sentence for a failed HTTP request (fits a Kodi notification)."""
    parts = urlparse(base)
    hostport = parts.netloc or base
    host = parts.hostname or base
    low = str(exc).lower()
    if isinstance(exc, requests.exceptions.SSLError):
        if "wrong_version_number" in low or "wrong version number" in low:
            return "%s does not speak HTTPS - try http:// instead of https://" % hostport
        return ("TLS/certificate error with %s - fix the certificate or turn off "
                "'Verify TLS certificates'" % hostport)
    if isinstance(exc, requests.exceptions.Timeout):
        return "Timeout after %ss contacting %s" % (timeout, hostport)
    if isinstance(exc, (requests.exceptions.MissingSchema, requests.exceptions.InvalidSchema,
                        requests.exceptions.InvalidURL)):
        return "Invalid server address '%s' - use the form http://host:2342" % base
    if isinstance(exc, requests.exceptions.ConnectionError):
        if any(k in low for k in ("name or service not known", "failed to resolve", "getaddrinfo",
                                  "nodename nor servname", "name resolution")):
            return "Cannot resolve host name '%s' - check the address" % host
        if "refused" in low or "errno 111" in low or "winerror 10061" in low:
            return "Connection refused by %s - check the port and that PhotoPrism is running" % hostport
        if any(k in low for k in ("no route to host", "network is unreachable", "errno 113", "errno 101")):
            return "%s is unreachable - check the network and the address" % hostport
        if any(k in low for k in ("connection aborted", "remotedisconnected", "connection reset", "errno 104")):
            return "%s closed the connection - wrong port, or http/https mismatch?" % hostport
        return "Cannot connect to %s (%s)" % (hostport, exc.__class__.__name__)
    return "Request to %s failed (%s)" % (hostport, exc.__class__.__name__)


class PhotoPrism(object):
    def __init__(self, base_url, timeout=15, verify=True, session=None, log=None, user_agent=None):
        self.base = normalize_base_url(base_url)
        self.timeout = timeout
        self.verify = verify
        self.log = log or _NullLog()
        self.user_agent = user_agent or "Kodi-PhotoPrism"
        self.http = session or requests.Session()
        self.token = None
        self.preview_token = "public"
        self.download_token = ""
        self.session_id = None

    # ---- low level ----
    def _headers(self):
        h = {"Accept": "application/json", "User-Agent": self.user_agent}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
            h["X-Auth-Token"] = self.token
        return h

    def _req(self, method, path, params=None, body=None, raw=False, with_rows=False):
        url = self.base + "/api/v1" + path
        t0 = time.time()
        try:
            r = self.http.request(method, url, params=params, headers=self._headers(),
                                  data=json.dumps(body) if body is not None else None,
                                  timeout=self.timeout, verify=self.verify)
        except requests.exceptions.RequestException as e:
            msg = friendly_error(e, self.base, self.timeout)
            self.log.warning("%s %s failed: %s [%s: %s]" % (method, path, msg, e.__class__.__name__, e))
            raise ApiError(msg)
        self.log.debug("%s %s%s -> HTTP %d (%d ms)" % (
            method, path, " " + str(params) if params else "", r.status_code,
            int((time.time() - t0) * 1000)))
        if r.status_code == 401:
            raise AuthError("Authentication failed (401) - check username/password or app password")
        if r.status_code == 403:
            raise AuthError("Access denied (403) - check the account permissions / app password scope")
        if r.status_code == 404:
            raise ApiError("Not found (404) for %s - is %s really PhotoPrism (not a proxy path)?"
                           % (path, urlparse(self.base).netloc))
        if r.status_code == 429:
            raise ApiError("Too many requests (429) - wait a moment and try again")
        if r.status_code >= 500:
            raise ApiError("Server error (HTTP %d) from %s" % (r.status_code, urlparse(self.base).netloc))
        if r.status_code >= 400:
            raise ApiError("HTTP %d for %s" % (r.status_code, path))
        if raw:
            return r.content
        try:
            data = r.json()
        except ValueError:
            self.log.warning("%s %s returned a non-JSON body: %r" % (method, path, r.text[:120]))
            raise ApiError("Invalid JSON from server - is %s really PhotoPrism?" % urlparse(self.base).netloc)
        if with_rows:
            # X-Count = number of DB rows consumed. With merged=true several rows
            # (files) collapse into one photo, so len(data) can be < count.
            try:
                rows = int(r.headers.get("X-Count", len(data or [])))
            except (TypeError, ValueError):
                rows = len(data or [])
            return {"items": data or [], "rows": rows}
        return data

    def ping(self):
        """GET /status without logging in: is this address a reachable PhotoPrism?
        Returns (milliseconds, first bytes of the body)."""
        t0 = time.time()
        body = self._req("GET", "/status", raw=True)
        return int((time.time() - t0) * 1000), body[:80].decode("utf-8", "replace")

    def _apply_config(self, cfg):
        cfg = cfg or {}
        self.preview_token = cfg.get("previewToken") or self.preview_token
        self.download_token = cfg.get("downloadToken") or self.download_token

    # ---- auth ----
    def login_password(self, username, password):
        data = self._req("POST", "/session", body={"username": username, "password": password})
        self.token = data.get("access_token") or data.get("id")
        self.session_id = data.get("id")
        if not self.token:
            raise AuthError("No session token returned")
        self._apply_config(data.get("config"))
        if not data.get("config"):
            self.refresh_config()
        self.log.info("Logged in as '%s'" % username)
        return data

    def login_token(self, token):
        self.token = token
        cfg = self.refresh_config()
        self.log.info("Authenticated with app password / access token")
        return cfg

    def restore(self, state):
        self.token = state.get("token")
        self.session_id = state.get("session_id")
        self.preview_token = state.get("preview_token", "public")
        self.download_token = state.get("download_token", "")

    def state(self):
        return {"token": self.token, "session_id": self.session_id,
                "preview_token": self.preview_token, "download_token": self.download_token}

    def refresh_config(self):
        cfg = self._req("GET", "/config")
        self._apply_config(cfg)
        return cfg

    # ---- data ----
    def albums(self, count=60, offset=0, atype="album", q="", order=None):
        p = {"count": count, "offset": offset, "type": atype,
             "order": order or ("name" if atype == "album" else "newest")}
        if q:
            p["q"] = q
        return self._req("GET", "/albums", params=p, with_rows=True)

    def photos(self, count=60, offset=0, q="", album="", order="newest"):
        p = {"count": count, "offset": offset, "merged": "true", "order": order, "public": "true"}
        if q:
            p["q"] = q
        if album:
            p["s"] = album
        return self._req("GET", "/photos", params=p, with_rows=True)

    def last_photo_date(self, album_uid):
        """TakenAt of the newest photo in an album ('' when the album is empty)."""
        items = self.photos(count=1, album=album_uid, order="newest")["items"]
        return (items[0].get("TakenAt") or "") if items else ""

    # ---- helpers ----
    @staticmethod
    def video_hash(photo):
        """Hash of the playable video file (merged results carry the JPEG sidecar hash)."""
        for f in photo.get("Files") or []:
            if f.get("Video") or f.get("MediaType") == "video":
                return f.get("Hash")
        return photo.get("Hash")

    @staticmethod
    def title(photo):
        t = photo.get("Title")
        if t:
            return t
        name = photo.get("OriginalName") or photo.get("FileName") or photo.get("UID") or "?"
        name = name.rsplit("/", 1)[-1]
        for ext in (".jpg", ".jpeg"):
            if name.lower().endswith(ext) and "." in name[:-len(ext)]:
                name = name[:-len(ext)]  # clip.mp4.jpg -> clip.mp4
        return name

    # ---- urls ----
    def thumb_url(self, file_hash, size):
        return "%s/api/v1/t/%s/%s/%s" % (self.base, file_hash, quote(self.preview_token), size)

    def album_cover_url(self, uid, size):
        return "%s/api/v1/albums/%s/t/%s/%s" % (self.base, uid, quote(self.preview_token), size)

    def download_url(self, file_hash):
        return "%s/api/v1/dl/%s?%s" % (self.base, file_hash, urlencode({"t": self.download_token}))

    def video_url(self, file_hash, fmt="avc"):
        return "%s/api/v1/videos/%s/%s/%s" % (self.base, file_hash, quote(self.preview_token), fmt)

    def fetch_bytes(self, url):
        t0 = time.time()
        try:
            r = self.http.get(url, headers=self._headers(), timeout=self.timeout, verify=self.verify)
        except requests.exceptions.RequestException as e:
            self.log.debug("fetch %s failed: %s: %s" % (url, e.__class__.__name__, e))
            return None
        self.log.debug("fetch %s -> HTTP %d (%d ms)" % (url, r.status_code, int((time.time() - t0) * 1000)))
        return r.content if r.status_code == 200 else None
