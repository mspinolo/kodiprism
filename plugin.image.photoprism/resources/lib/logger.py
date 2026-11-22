# -*- coding: utf-8 -*-
"""Add-on logging.

Two sinks:
  * Kodi's own log (kodi.log), prefixed with the add-on id;
  * a small rotating file in the add-on profile (debug.log) that can be read from
    inside Kodi (Settings > Troubleshooting > View add-on log), no SSH needed.

INFO/WARNING/ERROR are always recorded. DEBUG lines (one per HTTP request, timings...)
are recorded only when "Enable debug logging" is on; in that case they are written to
kodi.log at INFO level so they show up without enabling Kodi's global debug logging.

Secrets never reach either sink: exact secret values registered with add_secret()
(password, app password, session/preview/download tokens) and the token segments of
PhotoPrism URLs are replaced by ***.
"""
import os
import re
import threading
import time
import traceback

import xbmc

MAX_BYTES = 256 * 1024
LOG_NAME = "debug.log"

# Token-bearing PhotoPrism URL shapes. Order matters: the album pattern must run
# before the generic /t/<hash>/<token> one.
_URL_PATTERNS = [
    (re.compile(r"(/albums/[^/\s?]+/t/)[^/\s?]+"), r"\1***"),
    (re.compile(r"(/videos/[^/\s?]+/)[^/\s?]+"), r"\1***"),
    (re.compile(r"(/t/[^/\s?]+/)[^/\s?]+"), r"\1***"),
    (re.compile(r"([?&]t=)[^&\s]+"), r"\1***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1***"),
]


def redact_urls(text):
    """Mask token segments of PhotoPrism URLs (no knowledge of exact secrets needed)."""
    for pattern, repl in _URL_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class AddonLog(object):
    def __init__(self, addon_id, profile_dir, debug=False):
        self.addon_id = addon_id
        self.path = os.path.join(profile_dir, LOG_NAME)
        self.debug_enabled = bool(debug)
        self._lock = threading.Lock()
        self._secrets = set()

    # ---- secrets ----
    def add_secret(self, *values):
        for v in values:
            if v and len(str(v)) >= 4:
                self._secrets.add(str(v))

    def redact(self, text):
        text = redact_urls(str(text))
        # longest first so a secret that contains another one is fully masked
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, "***")
        return text

    # ---- levels ----
    def debug(self, msg):
        self._emit("DEBUG", msg)

    def info(self, msg):
        self._emit("INFO", msg)

    def warning(self, msg):
        self._emit("WARNING", msg)

    def error(self, msg):
        self._emit("ERROR", msg)

    def exception(self, msg):
        self._emit("ERROR", "%s\n%s" % (msg, traceback.format_exc().rstrip()))

    def _emit(self, level, msg):
        if level == "DEBUG" and not self.debug_enabled:
            return
        text = self.redact(msg)
        kodi_level = {"DEBUG": xbmc.LOGINFO, "INFO": xbmc.LOGINFO,
                      "WARNING": xbmc.LOGWARNING, "ERROR": xbmc.LOGERROR}[level]
        xbmc.log("[%s] %s" % (self.addon_id, text), kodi_level)
        self._write("%s %-7s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), level, text))

    # ---- file sink ----
    def _write(self, line):
        with self._lock:
            try:
                if os.path.exists(self.path) and os.path.getsize(self.path) > MAX_BYTES:
                    os.replace(self.path, self.path + ".1")
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                pass  # logging must never break the add-on

    def tail(self, max_lines=300):
        """Last lines of the add-on log (current file only), or '' if there is none."""
        try:
            with open(self.path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return ""
        return "".join(lines[-max_lines:])

    def clear(self):
        removed = 0
        for p in (self.path, self.path + ".1"):
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass
        return removed
