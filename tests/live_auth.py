"""App-password probe against a REAL PhotoPrism (container `pp`, see .github/workflows/live.yml).

    PP_URL=http://127.0.0.1:2342 PP_PASS=... python3 tests/live_auth.py report.json

Answers, with the add-on's own API client, what the README tells users about app passwords: which scope KodiPrism
needs, what an app password can NOT do, what happens when it expires or is revoked, and whether changing the account
password affects it. Every CLI command and its output is recorded, so the report stays readable even if a parse fails.
"""
import json
import os
import re
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin.image.photoprism"))
from resources.lib import api as api_mod  # noqa: E402

BASE = os.environ.get("PP_URL", "http://127.0.0.1:2342")
PASSWORD = os.environ.get("PP_PASS", "ci-test-password-1")
TOKEN_RE = re.compile(r"\b[A-Za-z0-9]{6}-[A-Za-z0-9]{6}-[A-Za-z0-9]{6}-[A-Za-z0-9]{6}\b")
R = {"cli": []}


def cli(*args):
    p = subprocess.run(["docker", "exec", "pp", "photoprism"] + list(args), capture_output=True, text=True, timeout=120)
    out = (p.stdout + p.stderr).strip()
    R["cli"].append({"cmd": "photoprism " + " ".join(args), "rc": p.returncode, "out": out[-3000:]})
    return out


def new_app_password(name, scope, expires):
    out = cli("auth", "add", "-n", name, "-s", scope, "-e", str(expires), "admin")
    m = TOKEN_RE.search(out)
    return m.group(0) if m else None


def use(token, label):
    """What the add-on sees with this app password: login_token + albums + photos."""
    a = api_mod.PhotoPrism(BASE, timeout=30)
    res = {}
    try:
        a.login_token(token)
        res["login"] = "ok"
        res["albums"] = len(a.albums(10))
        res["photos"] = len(a.photos(10)["items"])
    except Exception as e:  # noqa: BLE001
        res["error"] = "%s: %s" % (type(e).__name__, e)
    raw = requests.get(BASE + "/api/v1/albums", params={"count": 1}, headers={"Authorization": "Bearer " + token}, timeout=30)
    res["raw_albums_status"] = raw.status_code
    res["raw_albums_body"] = raw.text[:200]
    R[label] = res
    return res


# help texts first: they document the flags of this PhotoPrism version
cli("auth", "--help"); cli("auth", "add", "--help"); cli("auth", "rm", "--help")

# 1. scopes
full = new_app_password("kodi-full", "*", -1)
webdav = new_app_password("kodi-webdav", "webdav", -1)
R["tokens_created"] = {"full": bool(full), "webdav": bool(webdav)}
if full: use(full, "scope_full")
if webdav: use(webdav, "scope_webdav")

# 2. what an app password cannot do (docs: no password change, no user management)
s = requests.post(BASE + "/api/v1/session", json={"username": "admin", "password": PASSWORD}, timeout=30).json()
uid = (s.get("user") or {}).get("UID")
R["admin_uid_found"] = bool(uid)
if full and uid:
    h = {"Authorization": "Bearer " + full}
    r = requests.put(BASE + "/api/v1/users/%s/password" % uid, json={"old": PASSWORD, "new": "changed-by-app-1"}, headers=h, timeout=30)
    R["app_changes_password"] = {"status": r.status_code, "body": r.text[:200]}
    r = requests.get(BASE + "/api/v1/users", headers=h, timeout=30)
    R["app_lists_users"] = {"status": r.status_code, "body": r.text[:150]}
    r = requests.post(BASE + "/api/v1/session", json={"username": "admin", "password": PASSWORD}, timeout=30)
    R["account_password_still_valid"] = r.status_code

# 3. changing the account password (with a normal session) -> does the app password keep working?
if full and uid:
    sh = {"Authorization": "Bearer " + s.get("access_token", "")}
    r = requests.put(BASE + "/api/v1/users/%s/password" % uid, json={"old": PASSWORD, "new": "ci-test-password-2"}, headers=sh, timeout=30)
    R["owner_changes_password"] = {"status": r.status_code, "body": r.text[:200]}
    use(full, "full_after_password_change")
    requests.put(BASE + "/api/v1/users/%s/password" % uid, json={"old": "ci-test-password-2", "new": PASSWORD}, headers=sh, timeout=30)

# 4. expiry
short = new_app_password("kodi-expiring", "*", 20)
if short:
    use(short, "expiring_before")
    time.sleep(35)
    use(short, "expiring_after_35s")

# 5. revocation: find the app password in the listing and remove it
listing = cli("auth", "ls")
ids = []
for line in listing.splitlines():
    if "kodi-full" in line:
        ids += re.findall(r"\bsess[a-z0-9]{8}\b", line)   # e.g. sess7wcu1luo (auth ls, PhotoPrism 2026)
R["revoke_candidate_ids"] = ids
if full and ids:
    cli("auth", "rm", "-y", ids[0])
    after = cli("auth", "ls")
    R["listed_after_revoke"] = {"kodi-full": "kodi-full" in after, "kodi-webdav": "kodi-webdav" in after}
    use(full, "full_after_revoke")
    if webdav:
        use(webdav, "webdav_after_revoking_the_other")

with open(sys.argv[1] if len(sys.argv) > 1 else "auth_report.json", "w") as fh:
    json.dump(R, fh, indent=1, default=str)
print(json.dumps({k: v for k, v in R.items() if k != "cli"}, indent=1, default=str))
