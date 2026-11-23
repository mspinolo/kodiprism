# -*- coding: utf-8 -*-
"""Turn Kodi's "Use pan and zoom effects" off while an add-on slideshow runs, then put it back.

Kodi has no per-slideshow switch for this: it is the global setting `slideshow.displayeffects`
(Settings > Player > Pictures). So:

  * before starting a slideshow the plugin calls Guard.prepare(): if the effect is on, the previous
    value is written to <profile>/fx_restore.json and the setting is switched off;
  * the background service (service.py) calls Guard.tick() every second and, when the slideshow window
    has closed (or never opened), Guard.restore() puts the value back and deletes the file;
  * if Kodi stopped in between (crash, power cut) the service restores the value on its next start.

The plugin only touches the setting while the service is alive (Window(10000) property), because
nothing else would restore it. All Kodi access goes through the injected `execute` (JSON-RPC) so the
logic is unit-testable.
"""
import json
import os
import time

SETTING_ID = "slideshow.displayeffects"
STATE_NAME = "fx_restore.json"
SERVICE_PROP = "kodiprism.service"      # set on the Home window while service.py runs
GRACE = 90                               # seconds to wait for the slideshow window to appear


def _call(execute, method, params):
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        out = json.loads(execute(json.dumps(request)))
    except (ValueError, TypeError):
        return None
    return out if isinstance(out, dict) else None


def get_value(execute, setting=SETTING_ID):
    """Current boolean value of a Kodi setting, or None if it cannot be read."""
    out = _call(execute, "Settings.GetSettingValue", {"setting": setting})
    if not out or "error" in out:
        return None
    value = (out.get("result") or {}).get("value")
    return value if isinstance(value, bool) else None


def set_value(execute, value, setting=SETTING_ID):
    out = _call(execute, "Settings.SetSettingValue", {"setting": setting, "value": value})
    return bool(out) and "error" not in out and out.get("result") is True


class Guard(object):
    def __init__(self, execute, profile_dir, log, clock=time.time):
        self.execute = execute
        self.path = os.path.join(profile_dir, STATE_NAME)
        self.log = log
        self.clock = clock
        self.seen_active = False

    # ---- state file ----
    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            return None
        return st if isinstance(st, dict) else None

    def _write(self, st):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(st, fh)

    def _remove(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def pending(self):
        return self._read() is not None

    # ---- plugin side ----
    def prepare(self):
        """Call right before starting a slideshow. True if the effect is (now) off or was already off."""
        st = self._read()
        if st:  # an earlier slideshow has not been restored yet: keep the original value, restart the grace period
            st["ts"] = self.clock()
            self._write(st)
            self.seen_active = False
            return True
        current = get_value(self.execute)
        if current is None:
            self.log.warning("Cannot read Kodi setting %s: pan/zoom left unchanged" % SETTING_ID)
            return False
        if not current:
            return True
        self._write({"setting": SETTING_ID, "value": current, "ts": self.clock()})
        if not set_value(self.execute, False):
            self._remove()
            self.log.warning("Cannot change Kodi setting %s: pan/zoom left unchanged" % SETTING_ID)
            return False
        self.seen_active = False
        self.log.info("Pan and zoom switched off for the slideshow (restored when it ends)")
        return True

    # ---- service side ----
    def restore(self):
        """Put the saved value back. True when nothing is left to restore."""
        st = self._read()
        if not st:
            return True
        if set_value(self.execute, st.get("value", True), st.get("setting", SETTING_ID)):
            self._remove()
            self.seen_active = False
            self.log.info("Pan and zoom setting restored")
            return True
        self.log.warning("Could not restore Kodi setting %s yet; will retry" % st.get("setting", SETTING_ID))
        return False

    def tick(self, slideshow_active):
        st = self._read()
        if not st:
            self.seen_active = False
            return
        if slideshow_active:
            self.seen_active = True
        elif self.seen_active:
            self.restore()                                    # the slideshow has just ended
        elif self.clock() - st.get("ts", 0) > GRACE:
            self.log.warning("Slideshow window never appeared: restoring pan/zoom")
            self.restore()


def service_loop(guard, monitor, is_slideshow_active):
    """Body of service.py: restore leftovers, then watch until Kodi exits."""
    guard.restore()
    while not monitor.abortRequested():
        guard.tick(is_slideshow_active())
        if monitor.waitForAbort(1):
            break
    guard.restore()


def describe(execute, profile_dir, service_alive):
    """Text for the 'Check slideshow settings' diagnostic: which Kodi settings exist and their values."""
    lines = ["KodiPrism background service: %s" % ("running" if service_alive else "NOT running (pan/zoom option has no effect)"),
             "Pan/zoom restore pending: %s" % ("yes" if os.path.exists(os.path.join(profile_dir, STATE_NAME)) else "no"),
             "Setting used: %s = %s" % (SETTING_ID, get_value(execute)), ""]
    out = _call(execute, "Settings.GetSettings", {"level": "expert"})
    settings = ((out or {}).get("result") or {}).get("settings") or []
    found = [s for s in settings if "slideshow" in str(s.get("id", "")) or "picture" in str(s.get("id", ""))]
    lines.append("Kodi settings whose id mentions slideshow/picture (%d):" % len(found))
    for s in sorted(found, key=lambda x: x.get("id", "")):
        lines.append("  %s = %s" % (s.get("id"), s.get("value")))
    if not found:
        lines.append("  (none found: JSON-RPC may be disabled or the names differ in this Kodi version)")
    return "\n".join(lines)
