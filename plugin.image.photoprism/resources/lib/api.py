# -*- coding: utf-8 -*-
"""Minimal PhotoPrism REST client (/api/v1)."""
import json

from urllib.parse import urlencode, quote

import requests


class ApiError(Exception):
    pass


class AuthError(ApiError):
    pass


class PhotoPrism(object):
    def __init__(self, base_url, timeout=15, verify=True, session=None):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.verify = verify
        self.http = session or requests.Session()
        self.token = None
        self.preview_token = "public"
        self.download_token = ""
        self.session_id = None

    # ---- low level ----
    def _headers(self):
        h = {"Accept": "application/json", "User-Agent": "Kodi-PhotoPrism/1.0"}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
            h["X-Auth-Token"] = self.token
        return h

    def _req(self, method, path, params=None, body=None, raw=False, with_rows=False):
        url = self.base + "/api/v1" + path
        try:
            r = self.http.request(method, url, params=params, headers=self._headers(),
                                  data=json.dumps(body) if body is not None else None,
                                  timeout=self.timeout, verify=self.verify)
        except requests.exceptions.Timeout:
            raise ApiError("Timeout contacting PhotoPrism")
        except requests.exceptions.RequestException as e:
            raise ApiError("Connection failed: %s" % e.__class__.__name__)
        if r.status_code in (401, 403):
            raise AuthError("Authentication failed (%d)" % r.status_code)
        if r.status_code >= 400:
            raise ApiError("HTTP %d for %s" % (r.status_code, path))
        if raw:
            return r.content
        try:
            data = r.json()
        except ValueError:
            raise ApiError("Invalid JSON from server")
        if with_rows:
            # X-Count = number of DB rows consumed. With merged=true several rows
            # (files) collapse into one photo, so len(data) can be < count.
            try:
                rows = int(r.headers.get("X-Count", len(data or [])))
            except (TypeError, ValueError):
                rows = len(data or [])
            return {"items": data or [], "rows": rows}
        return data

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
        return data

    def login_token(self, token):
        self.token = token
        self.refresh_config()

    def restore(self, state):
        self.token = state.get("token")
        self.session_id = state.get("session_id")
        self.preview_token = state.get("preview_token", "public")
        self.download_token = state.get("download_token", "")

    def state(self):
        return {"token": self.token, "session_id": self.session_id,
                "preview_token": self.preview_token, "download_token": self.download_token}

    def refresh_config(self):
        self._apply_config(self._req("GET", "/config"))

    # ---- data ----
    def albums(self, count=60, offset=0, atype="album", q=""):
        p = {"count": count, "offset": offset, "type": atype,
             "order": "name" if atype == "album" else "newest"}
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
        try:
            r = self.http.get(url, headers=self._headers(), timeout=self.timeout, verify=self.verify)
        except requests.exceptions.RequestException:
            return None
        return r.content if r.status_code == 200 else None
