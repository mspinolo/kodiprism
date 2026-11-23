# Kodi + PhotoPrism Add-on: Knowledge Base

Notes from building and testing `plugin.image.photoprism`, a Python 3 add-on for Kodi 21 "Omega".
Everything below marked **[verified]** was, according to the previous agent (Claude Opus, 2026-11-21), checked against a real PhotoPrism server (latest Docker image, Nov 2026) or by Kodi's tools. Anything marked **[unverified]** has not been run inside a real Kodi.

> **Provenance.** This file started as the previous agent's hand-over notes. The 2026-11-22 review session (Claude Sonnet) restructured the repository, fixed three bugs (see §7) and re-ran only the offline tests, pyflakes and mypy. It had **no** access to a real PhotoPrism server or a real Kodi, and `kodi-addon-checker` could not run offline (it downloads the official add-on list). Entries tagged **[review]** below are that session's additions. Start with [`../AGENTS.md`](../AGENTS.md) for the repository map and backlog.

## 1. Add-on structure
In this repository the add-on lives in the `plugin.image.photoprism/` folder (the zip is built from it by
`tools/build_zip.py`); tests, tools, assets and docs sit beside it. See `AGENTS.md` for the full repo map.
```
plugin.image.photoprism/
  addon.xml                      # id = folder name; xbmc.python 3.0.1; script.module.requests
  default.py                     # entry point -> resources.lib.plugin.run(sys.argv)
  resources/
    __init__.py
    settings.xml                 # new-style settings (version="1")
    icon.png                     # 512x512, must be solid, no transparency
    fanart.jpg                   # 1920x1080
    language/resource.language.en_gb/strings.po   # label ids 30000+
    lib/
      __init__.py
      api.py                     # REST client
      cache.py                   # disk cache: TTL + LRU
      plugin.py                  # routing + UI
```
- addon.xml uses extension `xbmc.python.pluginsource` with `<provides>image video</provides>`. Icon and fanart are listed under `<assets>`.
- Settings field types: `path` (folder browser, constraint `<writable>true</writable>`), `action` (button that runs `RunPlugin(plugin://.../?action=clear_cache)`), and hidden string fields for secrets (`<hidden>true</hidden>`). `<dependencies>` show or hide fields depending on the login method.
- Settings are read as strings with `ADDON.getSetting`. Always give a default when converting them to numbers.
- The profile folder is `xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))`.

## 2. PhotoPrism API (/api/v1) [verified]
### Authentication
- `POST /api/v1/session` with body `{"username","password"}` returns these keys: `access_token, config, data, expires_in, id, provider, scope, session_id, status, token_type, user`.
  - `config.previewToken` is needed in thumbnail and video URLs.
  - `config.downloadToken` is needed for original downloads.
- Send the token as `Authorization: Bearer <token>`. `X-Auth-Token` also works.
- App password / access token: send it as Bearer, then `GET /api/v1/config` to get `previewToken` and `downloadToken`.
- Create an app password with the CLI: `photoprism auth add -n kodi -s '*' -e -1 admin`. The output contains a token in the form `xxxxxx-xxxxxx-xxxxxx-xxxxxx`.
- A wrong password or token returns 401.

### Listing
- Albums: `GET /albums?count=&offset=&type=album|folder|moment|month|state&order=name|newest&q=`.
- Photos: `GET /photos?count=&offset=&merged=true&order=newest&q=<query>&s=<albumUID>`.
- **Paging trap:** with `merged=true`, `count` counts *file rows*. A video plus its JPEG preview is 2 rows but comes back as 1 photo, so the list can be shorter than `count`.
  - Use the response header **`X-Count`** (rows read). Next offset = `offset + X-Count`; there may be more if `X-Count >= count`.
  - Never use the "request count+1 and check the length" trick.
- Month albums (`type=month`) can be empty right after indexing. A background worker creates them later.
- `Title` is often empty. Fall back to the file name (`OriginalName` / `FileName`), and turn `clip.mp4.jpg` into `clip.mp4`.
- Video photos: `Type` is `video` (also `live` / `animated`). `Duration` is in **nanoseconds**. `Files[]` contains the JPEG preview (Primary) and the video file (`Video: true`, `MediaType: "video"`, `Codec: "avc1"`).
- Query syntax examples: `label:cat year:2023`, `type:video`, `type:image`, `favorite:true`, `filename:img5.jpg`, `country:de`.

### Media URLs (no auth header needed; the token is in the URL)
- Thumbnail: `/api/v1/t/{fileHash}/{previewToken}/{size}`. Sizes: `tile_224, tile_500, fit_720, fit_1280, fit_1920, fit_2560, fit_3840`.
- Album cover: `/api/v1/albums/{uid}/t/{previewToken}/tile_500`. **[review]** On the owner's real server (1.0.2) covers did not show with this endpoint while photo thumbnails did. The album JSON has `Thumb` (hash of the cover photo), so since 1.0.3 covers use `/api/v1/t/{Thumb}/{previewToken}/{size}`; this endpoint is kept only as a fallback when `Thumb` is empty. Root cause of the old failure not confirmed (the debug log would show the HTTP status of the `fetch` line).
- Video: `/api/v1/videos/{hash}/{previewToken}/{avc|hevc|vp9|av01}`. Returns `video/mp4` and supports Range requests (206). Prefer the hash of the video file in `Files[]`; the photo's own hash also worked.
- Original file: `/api/v1/dl/{hash}?t={downloadToken}`.

## 3. Kodi plugin patterns (Omega)
- Routing: `argv = [base_url, handle, "?query"]`; read the query with `parse_qsl`.
- Folders: `addDirectoryItem(handle, url, li, isFolder=True)`, then `endOfDirectory(handle, succeeded=..., cacheToDisc=False)`. On an error, call `endOfDirectory(succeeded=False)`.
- Images: add them as non-folder items whose URL is the direct HTTP image URL. Call `setContent(handle, "images")`.
- Videos: point the item at the plugin URL `?action=play&hash=` with `setProperty("IsPlayable","true")`. In the play route, call `setResolvedUrl(handle, True, ListItem(path=url))`. Also call `setMimeType("video/mp4")` and `setContentLookup(False)` to avoid an extra HEAD request.
- Use the **InfoTag API** instead of the deprecated `setInfo`: `li.getVideoInfoTag().setTitle/setPlot/setDuration/setMediaType` and `li.getPictureInfoTag().setDateTimeTaken`.
- Slideshow: `xbmc.executebuiltin("SlideShow(plugin://...?action=photos&slideshow=1)")`. The plugin returns a flat list of images only (no paging or "Next" items), capped at around 1000.
- Search input: `xbmc.Keyboard(default, heading)`, then `.doModal()`, `.isConfirmed()`, `.getText()`.
- Notifications: `xbmcgui.Dialog().notification(name, msg, xbmcgui.NOTIFICATION_ERROR, 5000)`.
- Context menu: `li.addContextMenuItems([("Slideshow", "RunPlugin(url)")])`.

## 4. Design decisions
- **Secrets:** stored only in Kodi settings. The session state is saved in `profile/session.json` (chmod 600) together with a fingerprint of the login settings, so it's replaced when the settings change. On a 401, delete the session, log in again and retry once.
- **Errors:** `ApiError` and `AuthError` cover timeouts, connection failures, HTTP ≥ 400 and invalid JSON. Each is shown as a notification.
- **Cache (`cache.py`):**
  - The root is `<chosen folder>/photoprism_cache`. It's checked with makedirs plus writing a test file; if that fails, the profile folder's `cache` is used and a notification is shown.
  - `meta/` holds JSON (API responses keyed by URL and parameters). `img/` holds thumbnails. File names are sha1 hashes of the key.
  - TTL uses the file's mtime (write time). LRU uses atime, which is updated manually with `os.utime` on every read (don't rely on the filesystem's atime).
  - `evict()`: first remove expired files and leftover `.tmp` files, then the least recently used until under the size limit.
  - Writes go to a temp file first and then `os.replace` (atomic).
- **Prefetch:** thumbnails that aren't cached are shown from their remote URL and queued. After `endOfDirectory`, a thread pool downloads them into the cache, then `evict()` runs. The next time the list is shown, cached files are used.
- HTTP uses `script.module.requests` with one session, a timeout and a TLS-verification setting.

## 5. Icon and fanart
- Write an SVG (gradient background, stacked photo frames, sun and mountains), then render it with `pip install cairosvg`: `cairosvg.svg2png(url=..., output_width=512, output_height=512)`. Convert to RGB with Pillow.
- **[review]** Sources are `assets/icon.svg` and `assets/fanart.svg`; `make assets` (`tools/render_assets.py`) regenerates `icon.png` and `fanart.jpg` and was checked to reproduce the committed images pixel for pixel.
- `kodi-addon-checker` **rejects icons with transparency**. Use a full-bleed background (no rounded corners) and save as RGB.
- Fanart: 1920x1080 JPEG, quality 90, about 100 KB.

## 6. Testing outside Kodi
- **Mock modules:** put fake `xbmc`, `xbmcgui`, `xbmcplugin`, `xbmcaddon` and `xbmcvfs` modules into `sys.modules` before importing the plugin.
  - Record directory items, `endOfDirectory` results, `setResolvedUrl` calls, notifications and `executebuiltin` calls.
  - Use a settings dict for `getSetting` and a temporary folder as the profile.
  - The mock ListItem needs `getVideoInfoTag` / `getPictureInfoTag` returning tag objects that only allow the expected setters.
- **Fake API:** a `ThreadingHTTPServer` that implements session, config, albums, photos and thumbnail endpoints, plus switches for a slow response (to test timeouts) and an expired token.
- **Real server (best):**
```
dockerd &   # if no daemon is running
docker run -d --name pp --network host -e PHOTOPRISM_ADMIN_PASSWORD=insecure123 \
  -e PHOTOPRISM_DATABASE_DRIVER=sqlite -e PHOTOPRISM_HTTP_PORT=2342 -e PHOTOPRISM_DISABLE_TLS=true \
  -e PHOTOPRISM_DISABLE_TENSORFLOW=true -v /pp/originals:/photoprism/originals \
  -v /pp/storage:/photoprism/storage photoprism/photoprism:latest
curl localhost:2342/api/v1/status          # {"status":"operational"}
docker exec pp photoprism index --cleanup
```
  - Sample media: JPEGs made with Pillow, and a video from `ffmpeg -f lavfi -i testsrc=duration=3:size=640x360:rate=25 -pix_fmt yuv420p clip.mp4`.
  - Create an album: `POST /albums {"Title"}`, then `POST /albums/{uid}/photos {"photos":[uids]}`.
  - Check images by their JPEG magic bytes `FF D8`. Check the video with `Range: bytes=0-15`: expect 206 and `ftyp` in the data.
- **Static checks:**
  - `kodi-addon-checker --branch omega <dir>`: icon, XML, PO files and dimensions. **[review]** It needs internet at startup (it downloads the official add-on list, even with `--skip-dependency-checks`) and hangs in offline sandboxes, so it runs in CI. `tests/test_static.py` covers the offline-checkable parts.
  - `Kodistubs` + `mypy --ignore-missing-imports --check-untyped-defs`: checks Kodi API names and arguments.
  - `pyflakes`: unused or undefined names.
  - `vermin -t=3.8- --violations`: Python version compatibility. Remove Python 2 import fallbacks, or vermin will report errors.

## 7. Bugs found only by testing against a real server
1. Paging with `merged=true` (see the trap in section 2).
2. Empty titles shown as `clip.mp4.jpg`.
3. Icon transparency rejected by the checker.
4. Deprecated `ListItem.setInfo` (logs warnings in Omega).

### Bugs found by code review, fixed in 1.0.1 [review]
Each has a regression test in `tests/test_addon.py`.
5. `_auth_fingerprint` used the builtin `hash()`. Python salts `str` hashes per interpreter start, so the stored fingerprint never matched after a Kodi restart and the add-on logged in again every time. Use `hashlib.sha256`.
6. `session.json` was written with `open(..., "w")` and then `chmod 600`, leaving a window with default permissions. Create it with `os.open(..., 0o600)`.
7. `DiskCache.evict()` treated any path containing `.tmp` as a leftover temp file, so a cache folder such as `/x/.tmpcache` had all its files deleted on every eviction. Match on the file name only.

## 8. Still unverified (needs real Kodi 21)
How the screens and settings look (path browser, action button), how SlideShow handles plugin lists, video playback on real hardware, installing `script.module.requests` from the repository, and how the background prefetch behaves under Kodi's plugin process lifetime.

Additional doubts raised by the review **[review, unverified]**:
- `api.photos()` always sends `public=true`. What this filter does in PhotoPrism (it may hide private photos) was not checked.
- HTTP 403 is handled like 401: the session is deleted and one retry is made. A genuine "forbidden" (insufficient scope of an app password) would cause a pointless re-login.
- Root-menu items "Slideshow: all photos" and "Clear cache" are non-folder, non-playable items whose handler never calls `endOfDirectory`. Confirm Kodi accepts this without a spinner or error.
- `run_prefetch()` joins its threads (60 s timeout each) before the plugin invocation ends.
- Preview and download tokens are embedded in thumbnail/video/download URLs and can appear in Kodi's debug log.
- All UI labels in `plugin.py` are hard-coded English; only the settings dialog is translatable via `strings.po`.

## 9. Reusable prompt snippet
> Build or extend a Kodi 21 (Python 3) plugin for PhotoPrism /api/v1. Use Bearer auth from POST /session (access_token, config.previewToken, config.downloadToken) or an app password plus GET /config. Page with the X-Count header when merged=true. Thumbnail URL is /t/{hash}/{previewToken}/{size}, video URL is /videos/{hash}/{previewToken}/avc, original is /dl/{hash}?t={downloadToken}. Use the InfoTag API, not setInfo. The icon must be solid RGB 512x512. Test with mocked xbmc modules, kodi-addon-checker --branch omega, Kodistubs+mypy, and a real photoprism/photoprism Docker container.

## 9. Diagnostics and logging (1.0.2) [review]
**Why.** In the first real-Kodi test the add-on could not connect and the only feedback was a notification with the exception class name. 1.0.2 adds clearer errors and logging.

**Design.**
- `resources/lib/logger.py` (`AddonLog`): sinks are `kodi.log` (prefix `[plugin.image.photoprism]`) and `debug.log` in the add-on profile (rotates at 256 KB to `debug.log.1`). INFO/WARNING/ERROR are always recorded; DEBUG (one line per HTTP request with status and ms) only when the `debug_log` setting is on, and then goes to `kodi.log` at INFO level so Kodi's global debug mode is not required.
- Masking: exact secrets registered with `add_secret()` (password, app password, session id/token, download token, preview token unless it is the generic `public`) plus regexes for token URL segments (`/t/<hash>/<token>/size`, `/albums/<uid>/t/<token>/size`, `/videos/<hash>/<token>/fmt`, `?t=`, `Bearer`). Tests check this end to end and with deliberate leaks; mutation checks confirmed that they fail when masking is disabled.
- `api.normalize_base_url()` fixes the address; `api.friendly_error()` maps `requests` exceptions to one actionable sentence; HTTP 401/403/404/429/5xx have their own messages. Messages stay short because they are shown in a Kodi notification.
- Settings: *Test connection* (`action=test_connection`, text viewer: address, `/api/v1/status` without login, login, version if the config reports one, albums+photos query), *Enable debug logging*, *View add-on log* (`action=show_log`, text viewer), *Clear add-on log*. `tests/test_static.py` checks that each button points to a routed action.
- Unexpected exceptions in `dispatch()` are logged with a traceback and shown as a notification.

**PhotoPrism side.** Verified in the official config-options documentation: `PHOTOPRISM_LOG_LEVEL` (trace, debug, info, warning, error, fatal, panic), `PHOTOPRISM_DEBUG` ("show non-essential log messages") and `PHOTOPRISM_TRACE` ("show all log messages"). Docker: `docker compose logs -f photoprism`. Not verified: whether PhotoPrism logs each API request at debug/trace level.

**Unverified (needs real Kodi / real PhotoPrism).**
- That `GET /api/v1/status` answers without authentication (the CLI `photoprism status` is believed to use it). If a PhotoPrism returns 401 the test treats it as "reachable".
- Whether the settings action buttons see values that were edited but not yet saved. The button label and the README say "uses saved settings"; if Kodi passes unsaved values this can be relaxed.
- That the config JSON has a `version` key (shown only if present).
- `xbmcgui.Dialog().textviewer` rendering of ~150 lines, and `special://logpath/kodi.log` resolving on all platforms (the header shows whatever Kodi returns).

## 10. Album catalogue, ordering and slideshow (1.1.0) [review]
**Real data from the owner's server** (PhotoPrism CE, manual albums): `Year`, `Month`, `Day` are all 0; `CreatedAt`/`UpdatedAt` are import dates; `Thumb` holds the cover photo hash; `PhotoCount` is present; titles start with `YYMMDD - ` (a naming convention, used only as a cross-check). So the only usable date is the one of the photos inside the album.
- **Design (`resources/lib/catalog.py`).** Albums of type `album` are all loaded (batches of 500) on every visit; searched, sorted and paged locally. The date of an album is `TakenAt` of its newest photo (`GET /photos?s=<uid>&count=1&order=newest`), cached in `albumdates|<server>` with `{UpdatedAt, PhotoCount, date, ts}` per album and re-read only when `UpdatedAt`/`PhotoCount` change or the entry is older than the cache TTL. Six worker threads, a background progress dialog, failures are not cached (retried next load). Empty/undated albums go last. Cost estimate: ~0.25 KB per album; ~40 KB per cover image (assumption, not measured).
- **Not local:** folders, moments and months have dates and are sorted/paged by the server (`order=newest|oldest|name`; `newest` is what the add-on already used for moments).
- **Slideshow order.** `SlideShow(<plugin url>,random|notrandom)`: an explicit flag stops Kodi's global *Randomise* from overriding the choice. `oldest`/`newest` are server orders (so the 2000-image window starts at the right end of the library). `random` is `order=random` in one request of `count=limit`: paging a random order with offsets would return overlapping draws, and it is never cached. The photo `order` value `random` and the `added` value come from PhotoPrism release notes and sources; the exact accepted strings were **not** verified against a real server.
- **Listing cache caveat.** Listings of photos are cached for the cache TTL (24 h by default), so new photos can take that long to appear in *All photos* or a slideshow until *Clear cache* is used. Albums themselves are always fetched fresh.
- **Unverified in real Kodi:** the progress dialog, label2 display in the owner's skin, the `SlideShow(...,notrandom)` parameter form, behaviour of `Dialog().select` when launched from a non-folder item, and time to read the dates on a real server.
- **PhotoPrism trademark.** Its policy asks third-party apps not to use the logo or the name in their own name and to say "for PhotoPrism"; hence the display name KodiPrism, the disclaimer in the description, and no logo. Not legal advice.

## 11. Localisation, pan/zoom service and extras (1.2.0) [review]
- **Localisation.** Every UI string is a key of `STR` in `plugin.py` (-> id in `strings.po`) read with `L("key")`; English is the msgid, `resource.language.it_it/strings.po` holds the translation. The test fakes read the real `.po` files, so tests see the same strings; `tests/test_static.py` checks that Italian has every id, translated, with the same `%d`/`%s` placeholders, and that no hard-coded English label is left. Errors raised by `api.py` and the text of the test-connection / log viewers stay English on purpose (technical, shared in bug reports).
- **Pan/zoom (`slideshow_fx.py`, `service.py`).** Kodi offers only the global setting `slideshow.displayeffects` (Settings > Player > Pictures); `SlideShow()` cannot override it. `Guard.prepare()` (plugin) saves the old value in `<profile>/fx_restore.json` and switches the effect off through JSON-RPC; the service ticks every second: restores when the slideshow window has been seen and closed, or after 90 s if it never opened, and also on service start (crash recovery) and on exit. The plugin only touches the setting if the service has set the Home-window property `kodiprism.service`. All logic takes an injected JSON-RPC function and clock, so it is unit-tested with a fake Kodi (including failures of get/set, grace period, leftovers, exit mid-slideshow).
- **Unverified in real Kodi:** that the setting id is exactly `slideshow.displayeffects` (the *Check slideshow settings* screen lists the ids that mention slideshow/picture so it can be corrected), that `Window.IsActive(slideshow)` is true while an add-on slideshow runs, that the service starts right after install (otherwise one Kodi restart), `SlideShow(...,beginslide="<url>")` matching the item path, the `month:`/`day:` search filters used by *On this day* and `order=added`, and how the picture tag (only date and resolution are settable in Kodi 21) shows in the owner's skin.
- **Photo "info".** Kodi 21's picture info tag only accepts date taken and resolution, so nothing else (camera, place) can be passed; the date is also the second label.
- **Random photos.** One draw of `page_size` images; paging offsets of a random order would overlap, so there is no *Next page*, only *Shuffle again* (`r=<time>` makes the URL differ).

