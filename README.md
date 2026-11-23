# KodiPrism

A Kodi add-on for [PhotoPrism](https://www.photoprism.app/) (add-on id `plugin.image.photoprism`). Browse albums, folders, moments, the calendar, all photos, videos and favorites of your own PhotoPrism server (/api/v1), search albums, and run slideshows. Targets Kodi 21 "Omega", Python 3. Licensed under GPL-3.0. Not affiliated with or endorsed by PhotoPrism; the PhotoPrism name and logo are their trademarks and the logo is not used here.

> **Status:** the owner uses it in a real Kodi against a real PhotoPrism (connection and browsing confirmed with 1.0.2); newer features are tested with mocked Kodi modules and a fake server and still need confirmation in Kodi. See [AGENTS.md](AGENTS.md).

## Install
Download `plugin.image.photoprism-<version>.zip` from the [Releases](https://github.com/mspinolo/kodiprism/releases) page (or build it with `make build`; it lands in `dist/`). In Kodi go to Settings > Add-ons > Install from zip file and pick the zip. Kodi installs the `script.module.requests` dependency from the official repo.

## Settings
- **Server:** URL (default `http://localhost:2342`). Login method is either **username + password** (POST `/api/v1/session`) or an **app password / access token** (Bearer). Nothing secret is stored in the code. The session token is saved to `<profile>/session.json` (mode 0600). A new login happens automatically when the settings change or the token expires.
- **Browsing:** items per page, **sort order** (newest first, oldest first, name), **maximum images per slideshow** (default 2000), thumbnail size (`tile_224` to `fit_1280`), slideshow image size (up to `original` via `/api/v1/dl`), thumbnail prefetching (number of threads) and video format (`avc`, `hevc`, `vp9`, `av01`).
- **Cache:** an on/off switch and a folder browser for any folder or disk. A `photoprism_cache/` folder is created there. If the folder doesn't exist or can't be written to, the add-on uses the add-on profile folder instead and shows a notification. You can also set the max size in MB (default 500), the lifetime in hours (default 24) and use a **Clear cache** button. Metadata (JSON) and thumbnails are stored on disk. Old entries are removed by TTL, then least-recently-used entries are removed until the cache is under the size limit.

## Usage
- **Search...** takes PhotoPrism query syntax, e.g. `label:cat year:2023`, `country:de favorite:true`.
- **Slideshow:** use the entry at the top of any photo list, the album context menu, or the root menu. It starts Kodi's slideshow with up to 1000 images.
- **Videos** play through `/api/v1/videos/{hash}/{previewToken}/{format}`.
- Errors such as timeouts, bad logins, an unreachable server or HTTP errors are shown as Kodi notifications.

## Albums, search and sorting
- **Albums** are loaded completely and searched, sorted and paged locally. *Search albums...* (main menu and top of the Albums list) matches every word in the title or place, ignoring case and accents.
- **Newest first** is the default everywhere. Manual PhotoPrism albums have no date of their own, so an album's date is the date of the **newest photo it contains**, shown next to the album. It is read with one small request per album the first time, then kept in the cache and only re-read for albums whose `UpdatedAt` or photo count changed (about 0.25 KB per album; 100 albums take a second or two the first time). Empty albums and albums whose lookup failed go last. Folders, moments and calendar months have their own dates and are sorted by the server.
- The sort order setting applies to albums (by last-photo date), photos and the other lists.

## Slideshow
Starting a slideshow (main menu, album context menu or the *Slideshow* entry of a photo list) asks for the order: **newest first, oldest first or random**. The limit is 2000 images by default (setting). Random draws from the whole library or album, not only the newest photos. The ordered modes explicitly disable Kodi's own *Randomise* option so your choice is respected.

## Troubleshooting
**Server address.** Write it as Kodi must reach it, including the protocol and, unless it is the standard one
(80 for http, 443 for https), the port: PhotoPrism listens on **2342** by default, so a standard install is
`http://192.168.1.20:2342`. Behind a reverse proxy on 443 it is just `https://photos.example.com`. Do not use
`localhost` unless PhotoPrism runs on the same device as Kodi. If you forget `http://` the add-on adds it.

**Test connection.** *Settings > Server > Test connection* checks the address, whether the server answers, the
login and the library, and tells you which step fails. It uses the *saved* settings, so press OK in the
settings dialog first.

| Message | Meaning |
|---|---|
| Connection refused by host:port | wrong port, or PhotoPrism is not running / not published on that port |
| Cannot resolve host name | typo in the name, or Kodi's DNS does not know it (try the IP address) |
| host:port is unreachable | network or firewall problem between Kodi and the server |
| does not speak HTTPS / TLS certificate error | https on a plain-http port, or a self-signed certificate (turn off *Verify TLS certificates*) |
| Timeout after N s | server too slow or silently dropping packets; raise the timeout |
| Authentication failed (401) | server reached, wrong username/password or app password |
| Not found (404) | the address answers but is not PhotoPrism's root (reverse-proxy path?) |

**Logs.** Turn on *Settings > Troubleshooting > Enable debug logging*, reproduce the problem, then open
*View add-on log* (newest entries at the bottom). The same lines are in Kodi's own log (`kodi.log`: on
LibreELEC `/storage/.kodi/temp/kodi.log`; the viewer shows the exact path), prefixed with
`[plugin.image.photoprism]`. Passwords, app passwords and tokens are masked, so the log can be shared.
On the PhotoPrism side you can raise its verbosity with `PHOTOPRISM_LOG_LEVEL=debug` (or `trace`) and read it
with `docker compose logs -f photoprism`; the add-on identifies itself with the `User-Agent`
`KodiPrism/<version>`, which also shows up in reverse-proxy access logs.

## Repository layout
```
plugin.image.photoprism/   the add-on as Kodi sees it (default.py, addon.xml, resources/)
tests/                     mocked-Kodi tests, live-server test, offline static checks
tools/                     build_zip.py, render_assets.py
assets/                    SVG sources of icon and fanart
docs/knowledge.md          API facts, Kodi patterns, design decisions, known bugs
.github/workflows/         CI (tests, lint, kodi-addon-checker, zip) and tag-based release
```
Inside the add-on: `default.py` is the entry point, `resources/lib/api.py` the REST client, `resources/lib/cache.py` the disk cache, `resources/lib/logger.py` logging (with secret masking) and `resources/lib/plugin.py` routing and UI. Settings and strings are under `resources/`, along with `icon.png` (512x512) and `fanart.jpg` (1920x1080), rendered from `assets/*.svg`.

## Development
- `make test` runs `tests/test_addon.py` (add-on with mocked xbmc modules against a fake PhotoPrism server) and `tests/test_static.py` (offline package checks).
- `make lint` runs pyflakes and mypy (`pip install pyflakes mypy Kodistubs`). `make build` creates the zip. `make assets` re-renders the artwork (`pip install cairosvg pillow`).
- `PP_PASS=... PP_APP=<app password> PP_URL=http://host:2342 python3 tests/test_live.py` runs the add-on against a real PhotoPrism server. It expects an album named "Kodi Test" with 2 photos.
- GitHub Actions (`.github/workflows/`): `ci.yml` runs all of the above plus `kodi-addon-checker --branch omega`; `release.yml` publishes a GitHub Release with the zip when you push a tag `vX.Y.Z` that matches `addon.xml`.
- Contributors and AI agents: read [AGENTS.md](AGENTS.md) first.
