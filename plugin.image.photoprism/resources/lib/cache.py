# -*- coding: utf-8 -*-
"""Disk cache with TTL + LRU eviction for JSON metadata and binary thumbnails."""
import hashlib
import json
import os
import threading
import time

_lock = threading.Lock()


def validate_dir(path):
    """Return True if path exists (or can be created) and is writable."""
    if not path:
        return False
    try:
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".pp_write_test_%d" % os.getpid())
        with open(probe, "wb") as fh:
            fh.write(b"ok")
        os.remove(probe)
        return True
    except (OSError, IOError):
        return False


def resolve_dir(user_path, fallback):
    """Pick the cache root: user folder if valid, else fallback. Returns (path, used_fallback)."""
    if user_path:
        root = os.path.join(user_path, "photoprism_cache")
        if validate_dir(root):
            return root, False
    root = os.path.join(fallback, "cache")
    validate_dir(root)
    return root, bool(user_path)


class DiskCache(object):
    def __init__(self, root, max_mb=500, ttl_hours=24, enabled=True):
        self.root = root
        self.max_bytes = int(max_mb) * 1024 * 1024
        self.ttl = int(ttl_hours) * 3600
        self.enabled = enabled and bool(root)
        if self.enabled:
            for sub in ("meta", "img"):
                os.makedirs(os.path.join(root, sub), exist_ok=True)

    @staticmethod
    def _key(key):
        return hashlib.sha1(key.encode("utf-8")).hexdigest()

    def _path(self, kind, key, ext=""):
        return os.path.join(self.root, kind, self._key(key) + ext)

    def _fresh(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return False
        if time.time() - st.st_mtime > self.ttl:
            try:
                os.remove(path)
            except OSError:
                pass
            return False
        return True

    @staticmethod
    def _touch(path):
        # LRU: atime marks last use; mtime marks creation (for TTL)
        try:
            st = os.stat(path)
            os.utime(path, (time.time(), st.st_mtime))
        except OSError:
            pass

    def _write(self, path, data):
        tmp = path + ".tmp%d" % threading.get_ident()
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
        now = time.time()
        os.utime(path, (now, now))

    # --- metadata ---
    def get_json(self, key):
        if not self.enabled:
            return None
        p = self._path("meta", key, ".json")
        if not self._fresh(p):
            return None
        try:
            with open(p, "rb") as fh:
                data = json.loads(fh.read().decode("utf-8"))
        except (OSError, ValueError):
            return None
        self._touch(p)
        return data

    def set_json(self, key, value):
        if not self.enabled:
            return
        try:
            self._write(self._path("meta", key, ".json"), json.dumps(value).encode("utf-8"))
        except OSError:
            pass

    # --- images ---
    def image_path(self, key):
        """Return cached file path if fresh, else None."""
        if not self.enabled:
            return None
        p = self._path("img", key, ".jpg")
        if self._fresh(p):
            self._touch(p)
            return p
        return None

    def put_image(self, key, data):
        if not self.enabled or not data:
            return None
        p = self._path("img", key, ".jpg")
        try:
            self._write(p, data)
            return p
        except OSError:
            return None

    # --- maintenance ---
    def _entries(self):
        out = []
        for sub in ("meta", "img"):
            d = os.path.join(self.root, sub)
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for n in names:
                p = os.path.join(d, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out.append((p, st))
        return out

    def size(self):
        return sum(st.st_size for _, st in self._entries())

    def evict(self):
        """Drop expired entries, then least-recently-used until under max size."""
        if not self.enabled:
            return 0
        removed = 0
        with _lock:
            now = time.time()
            live, total = [], 0
            for p, st in self._entries():
                if now - st.st_mtime > self.ttl or ".tmp" in p:
                    try:
                        os.remove(p); removed += 1
                    except OSError:
                        pass
                else:
                    live.append((p, st)); total += st.st_size
            if total > self.max_bytes:
                live.sort(key=lambda e: max(e[1].st_atime, e[1].st_mtime))
                for p, st in live:
                    if total <= self.max_bytes:
                        break
                    try:
                        os.remove(p); total -= st.st_size; removed += 1
                    except OSError:
                        pass
        return removed

    def clear(self):
        n = 0
        for p, _ in self._entries():
            try:
                os.remove(p); n += 1
            except OSError:
                pass
        return n
