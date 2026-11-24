# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/). Versions follow `addon.xml`.

## [1.2.1] - 2026-11-24
### Fixed
- *Search albums* never closed the directory when the server could not be reached, which can leave Kodi waiting.
  Every action that builds a directory now fails cleanly.
- Server addresses with spaces or control characters, or an unbalanced `[`, are rejected with a clear message
  (they used to be accepted or raised an internal error).
### Added
- **Troubleshooting > Support info (for bug reports)**: add-on/Kodi/OS/skin/language, key settings, cache usage,
  background-service state, the latest album-date and slideshow-list timings and the last log lines, in one
  block of text with no passwords, tokens or server name.
- Tests: error paths (session expiring during the album dates, HTML instead of JSON, 403/429/5xx, missing
  credentials, status page asking for login), property-based tests (Hypothesis) for addresses, search, sorting,
  log redaction and the pan/zoom state machine, a test of the **unpacked release zip**, and a coverage
  threshold (95% measured). CI now runs on Python 3.8, 3.11 and 3.13.

## [1.2.0] - 2026-11-23
### Added
- **Italian translation** (closes #3). Every menu label, prompt and notification now goes through
  `strings.po`; Kodi falls back to English for other languages. Technical messages (connection errors, the
  test-connection and log viewers) stay in English.
- **Pan and zoom off during slideshows** (new setting, on by default). Kodi only has a global switch
  (`slideshow.displayeffects`), so a small background service turns it off when a KodiPrism slideshow starts
  and restores the previous value when the slideshow window closes (also after a crash or when Kodi quits).
  *Troubleshooting > Check slideshow settings* shows the service state and the relevant Kodi settings.
- Main menu: **Recently added** (server order `added`, never cached), **On this day** (`month:M day:D`) and
  **Random photos** (one random draw, *Shuffle again* entry).
- **Slideshow from here** (context menu on a picture).
- Photos show their date as second label and report their resolution to Kodi.
- **Hide empty albums** setting (on by default).
- **First-run guide**: when the server address was never set, offers once to open the settings.
### Changed
- The service's logic lives in `resources/lib/service_main.py`; `service.py` is a 4-line entry point (the add-on checker
  rejects entry points over 15 lines and the `start` attribute on `xbmc.service`).
- Random lists are never cached; lists marked `fresh` (Recently added) are never cached either.

## [1.1.0] - 2026-11-22
### Added
- **Search albums** (main menu and top of the Albums list): every word must appear in the title or place;
  case and accents are ignored.
- **Sort order** setting (newest first by default, oldest first, name) applied to every list. Albums have no
  date of their own on a typical server (Year/Month/Day are 0), so they are sorted by the date of the **newest
  photo they contain**, shown as the album's second label. Dates are read once per album (6 in parallel, with a
  background progress dialog) and cached; only albums whose `UpdatedAt` / photo count changed are re-read.
- **Slideshow order prompt**: newest first, oldest first or random, from every entry point. Random is drawn by
  the server over the whole library/album; ordered modes pass `notrandom` so Kodi's global *Randomise* option
  cannot override the choice.
- **Maximum images per slideshow** setting (default 2000, was a fixed 1000).
### Changed
- Display name is now **KodiPrism** (the add-on id stays `plugin.image.photoprism`, so updates keep working);
  description states that it is not affiliated with PhotoPrism. The PhotoPrism logo is not used.
- User-Agent is `KodiPrism/<version>`. Root menu: *Search...* is now *Search photos...*.
- Albums are always fetched fresh (one request); only their dates are cached.

## [1.0.3] - 2026-11-22
### Fixed
- Album covers were not displayed on a real server. The add-on used the album-specific cover endpoint
  (`/albums/<uid>/t/...`); it now uses the album's `Thumb` (cover photo hash) with the normal thumbnail
  endpoint, the same one photo thumbnails use (and share their cache entries). Albums without a recorded cover
  still fall back to the old endpoint.

## [1.0.2] - 2026-11-22
### Added
- **Troubleshooting** settings section: *Enable debug logging*, *View add-on log* (opens the log inside Kodi, no
  SSH needed) and *Clear add-on log*; **Test connection** button in the Server section that checks, step by
  step, the address, reachability, login and library access and shows the result in a text viewer.
- Add-on log file (`debug.log` in the add-on profile, rotated at 256 KB) in addition to `kodi.log`. With debug
  logging on, every HTTP request is logged with status and timing (also written to `kodi.log` at INFO level so
  Kodi's global debug mode is not needed). Passwords, app passwords, session/preview/download tokens and token
  URL segments are always masked.
- The add-on sends `User-Agent: Kodi-PhotoPrism/<version>` so its requests can be recognised in proxy logs.
### Changed
- The server address is corrected automatically: `http://` is added when missing; spaces, a trailing `/` and a
  pasted `/api/v1` are removed. Unusable addresses (empty, wrong scheme, bad port, embedded credentials) get a
  specific message.
- Connection errors now say what is wrong: connection refused (check the port), unknown host name, host
  unreachable, TLS/certificate problem, http/https mismatch, timeout, wrong address (404), server error (5xx).
- Unexpected exceptions are logged with a traceback and shown as a notification instead of failing silently.
- Error notifications stay on screen for 8 s.

## [1.0.1] - 2026-11-22
### Fixed
- Session fingerprint used Python's `hash()`, which is randomised per interpreter start, so the saved
  session was discarded and a new login happened after every Kodi restart. Now SHA-256 (no plaintext
  secret in `session.json`).
- `session.json` is created with mode 0600 from the start (previously created with default permissions
  and tightened afterwards).
- Cache `evict()` deleted *every* file when the cache path contained the text `.tmp`; it now only drops
  leftover `*.tmp*` files by file name.
- Type-annotation fixes reported by mypy (`api` is optional, `_prefetch` initialised in `__init__`).
### Changed
- `addon.xml` license is now `GPL-3.0-only`, matching the `LICENSE` file (it said MIT). Added website/source.
- Repository restructured: add-on sources live in `plugin.image.photoprism/`, tests in `tests/` (shared
  Kodi mocks), tools in `tools/`, notes in `docs/`. The release zip is no longer committed.
### Added
- `tools/build_zip.py` (clean, deterministic zip), `tools/render_assets.py` (SVG -> icon/fanart).
- Regression tests for the fixes above and offline static checks (`tests/test_static.py`).
- GitHub Actions workflows: CI (tests, pyflakes, mypy, kodi-addon-checker, zip artifact) and tag-based release.

## [1.0.0] - 2026-11-21
- First version, generated by Claude Opus: browse albums/folders/moments/calendar, all photos, videos,
  favorites, PhotoPrism search syntax, slideshow, password or app-password login, disk cache with
  TTL + LRU, thumbnail prefetch.
