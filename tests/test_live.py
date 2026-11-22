import os, sys
from kodi_mocks import PROFILE, SETTINGS, LOG


import requests
BASE = os.environ.get("PP_URL", "http://localhost:2342")
SETTINGS.update(server_url=BASE, password=os.environ["PP_PASS"], page_size="4", timeout="15")
from resources.lib import plugin
def run(qs=""):
    for k in LOG: LOG[k].clear()
    plugin.run(["plugin://plugin.image.photoprism/", "1", qs])
ok = 0
def check(c, msg):
    global ok
    print(("PASS " if c else "FAIL ") + msg); ok += bool(c)
    if not c: FAILS.append(msg)
FAILS = []
def fetch(u):
    if u.startswith(PROFILE): return 200, open(u, "rb").read()[:4]
    r = requests.get(u, timeout=30); return r.status_code, r.content[:4]

run("?action=albums&type=album")
alb = [i for i in LOG["items"] if "Kodi Test" in i[0]]
check(LOG["end"] == [True] and alb, "password login + albums list (%s)" % [i[0] for i in LOG["items"]])
check(fetch(alb[0][2])[0] == 200, "album cover url loads %s" % alb[0][2])
uid = dict(__import__("urllib.parse").parse.parse_qsl(alb[0][1].split("?")[1]))["album"]
run("?action=photos&album=" + uid)
pics = [i for i in LOG["items"] if i[1].startswith(BASE)]
check(len(pics) == 2, "album contents = 2 photos (%d)" % len(pics))
run("?action=albums&type=folder"); check(any("Holiday" in i[0] for i in LOG["items"]), "folders list")
run("?action=albums&type=month"); check(LOG["end"] == [True], "calendar list (months may be empty until PhotoPrism's background worker runs)")
run("?action=photos")
names = [i[0] for i in LOG["items"]]
check("[B]Next page >>[/B]" in names, "pagination present with page_size=4 (%s)" % names)
imgs = [i for i in LOG["items"] if i[1].startswith(BASE)]
for i in imgs[:2]:
    st, magic = fetch(i[1]); check(st == 200 and magic[:2] == b"\xff\xd8", "full image JPEG %s" % i[1])
    st, magic = fetch(i[2]); check(st == 200 and magic[:2] == b"\xff\xd8", "thumbnail JPEG")
nxt = [i for i in LOG["items"] if "Next" in i[0]][0][1]
run("?" + nxt.split("?")[1]); check(LOG["items"], "page 2 (%d items)" % len(LOG["items"]))
run("?action=photos&q=type%3Avideo")
vids = [i for i in LOG["items"] if "action=play" in i[1]]
check(len(vids) == 1, "video listed as playable (%s)" % [i[0] for i in LOG["items"]])
h = dict(__import__("urllib.parse").parse.parse_qsl(vids[0][1].split("?")[1]))["hash"]
run("?action=play&hash=" + h)
okv, vurl = LOG["resolved"][0]
r = requests.get(vurl, timeout=120, headers={"Range": "bytes=0-15"})
check(okv and r.status_code in (200, 206) and b"ftyp" in r.content[:16], "video stream is MP4 (%s %s)" % (r.status_code, r.headers.get("Content-Type")))
SETTINGS["full_size"] = "original"; run("?action=photos&q=type%3Aimage")
st, magic = fetch([i for i in LOG["items"] if i[1].startswith(BASE)][0][1]); check(st == 200 and magic[:2] == b"\xff\xd8", "original download via /dl")
SETTINGS["full_size"] = "fit_1920"
run("?action=photos&q=" + "filename%3Aimg5.jpg"); check([i[0] for i in LOG["items"] if i[1].startswith(BASE)].__len__() == 1, "search query syntax filename:img5.jpg")
run("?action=photos&q=type%3Aimage&slideshow=1"); check(len(LOG["items"]) == 7, "slideshow flat list = 7 images (%d)" % len(LOG["items"]))
# token auth
SETTINGS.update(auth_mode="1", token=os.environ["PP_APP"]); run("?action=albums&type=album")
check(LOG["end"] == [True] and any("Kodi Test" in i[0] for i in LOG["items"]), "app password login")
run("?action=photos&q=type%3Aimage"); st, _ = fetch([i for i in LOG["items"] if i[1].startswith(BASE)][0][2]); check(st == 200, "thumbs with app-password preview token")
SETTINGS["token"] = "wrong-token"; run("?action=albums&type=moment"); check(LOG["end"] == [False] and LOG["notes"], "bad token -> notification %s" % LOG["notes"])
SETTINGS.update(auth_mode="0", password="nope"); run("?action=albums&type=state"); check(LOG["end"] == [False] and LOG["notes"], "bad password -> notification %s" % LOG["notes"])
print("%d passed, %d failed" % (ok, len(FAILS)))
sys.exit(1 if FAILS else 0)
