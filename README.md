# PhotoPrism for Kodi (plugin.image.photoprism)

Lets you browse albums, folders, moments, the calendar, all photos, videos and favorites from a PhotoPrism server (/api/v1). Targets Kodi 21 "Omega", Python 3.

## Install
In Kodi go to Settings > Add-ons > Install from zip file and pick `plugin.image.photoprism-1.0.0.zip`. Kodi installs the `script.module.requests` dependency from the official repo.

## Settings
- **Server:** URL (default `http://localhost:2342`). Login method is either **username + password** (POST `/api/v1/session`) or an **app password / access token** (Bearer). Nothing secret is stored in the code. The session token is saved to `<profile>/session.json` (mode 0600). A new login happens automatically when the settings change or the token expires.
- **Browsing:** items per page, thumbnail size (`tile_224` to `fit_1280`), slideshow image size (up to `original` via `/api/v1/dl`), thumbnail prefetching (number of threads) and video format (`avc`, `hevc`, `vp9`, `av01`).
- **Cache:** an on/off switch and a folder browser for any folder or disk. A `photoprism_cache/` folder is created there. If the folder doesn't exist or can't be written to, the add-on uses the add-on profile folder instead and shows a notification. You can also set the max size in MB (default 500), the lifetime in hours (default 24) and use a **Clear cache** button. Metadata (JSON) and thumbnails are stored on disk. Old entries are removed by TTL, then least-recently-used entries are removed until the cache is under the size limit.

## Usage
- **Search...** takes PhotoPrism query syntax, e.g. `label:cat year:2023`, `country:de favorite:true`.
- **Slideshow:** use the entry at the top of any photo list, the album context menu, or the root menu. It starts Kodi's slideshow with up to 1000 images.
- **Videos** play through `/api/v1/videos/{hash}/{previewToken}/{format}`.
- Errors such as timeouts, bad logins, an unreachable server or HTTP errors are shown as Kodi notifications.

## Layout
`default.py` is the entry point. `resources/lib/api.py` is the REST client, `resources/lib/cache.py` is the disk cache, and `resources/lib/plugin.py` handles routing and the UI. Settings and strings are under `resources/`, along with `icon.png` (512²) and `fanart.jpg` (1920×1080), which are rendered from SVG with cairosvg.

## Tests
- `python3 tests/test_addon.py` runs the add-on with mocked xbmc modules against a fake PhotoPrism server.
- `PP_PASS=... PP_APP=<app password> PP_URL=http://host:2342 python3 tests/test_live.py` runs the add-on with mocked xbmc modules against a real PhotoPrism server. It expects an album named "Kodi Test" with 2 photos.
