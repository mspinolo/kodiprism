# AGENTS.md — start here

Orientation for any AI agent (or human) picking up this repository. Read this first, then
[`docs/knowledge.md`](docs/knowledge.md) for the detailed technical knowledge.

## What this is
**KodiPrism** (add-on id `plugin.image.photoprism`): a Kodi 21 "Omega" (Python 3) add-on that browses a self-hosted
[PhotoPrism](https://www.photoprism.app/) server — albums, folders, moments, calendar, all photos, videos,
favorites, PhotoPrism query search, slideshow — with password or app-password login and an on-disk cache.
Owner: Michele (`mspinolo`). Target setup: LibreELEC (Omega) 12.2.1 / Kodi 21 against PhotoPrism CE.
The first version was generated entirely by Claude Opus; the owner made the first commit by hand (the LICENSE).

## Current status (keep this section honest and up to date)
- Version **1.2.2** (see `CHANGELOG.md`). License **GPL-3.0** (`LICENSE`, mirrored in `addon.xml`).
- Verified in automation: unit/integration tests with mocked `xbmc*` modules against a fake PhotoPrism
  server (`tests/test_addon.py`), offline static checks (`tests/test_static.py`), pyflakes, mypy+Kodistubs.
- Reported by the previous agent but **not re-verified** by later sessions: `tests/test_live.py` against a real
  PhotoPrism Docker container (needs `PP_PASS`, `PP_APP`, `PP_URL`).
- **Real Kodi:** the owner confirmed (1.0.2, LibreELEC/Kodi 21) that connection and browsing work and photos
  display. Album covers were missing (fixed in 1.0.3, to be confirmed). Slideshow over a plugin list, the new
  1.1.0 features, video playback and prefetch thread behaviour are still unconfirmed in real Kodi.
- `kodi-addon-checker` needs internet (it downloads the official add-on list), so it runs in CI
  (`.github/workflows/ci.yml`), not in offline sandboxes. Check the CI result before claiming it passes.

## Repository map
```
plugin.image.photoprism/   the add-on exactly as Kodi sees it (this folder is what gets zipped)
  addon.xml  default.py  resources/{settings.xml,icon.png,fanart.jpg,language/,lib/{api,cache,plugin}.py}
tests/                     kodi_mocks.py (fake xbmc modules) · test_addon.py · test_live.py · test_static.py
tools/                     build_zip.py (-> dist/, gitignored) · render_assets.py (assets/*.svg -> icon/fanart)
assets/                    icon.svg, fanart.svg — sources of the generated artwork
docs/knowledge.md          API facts, Kodi patterns, design decisions, testing recipes, known bugs
.github/workflows/         ci.yml (every push/PR) · release.yml (tag vX.Y.Z -> GitHub Release with the zip)
                           live.yml (real PhotoPrism in Docker; manual + weekly, never blocking; report in annotations)
```
Code is small: `api.py` REST client (URL normalisation, error messages), `catalog.py` album search/sort/last-photo dates, `slideshow_fx.py` + `service.py` pan/zoom guard, `cache.py` TTL+LRU disk cache, `logger.py` logging with secret masking, `plugin.py` routing/UI.

## Commands
```
make test        # tests/test_addon.py + tests/test_properties.py (Hypothesis) + tests/test_static.py
make test-zip    # builds the zip, unpacks it elsewhere and runs the functional tests against that copy
make coverage    # same tests under coverage.py, fails below the threshold in the Makefile (needs: pip install coverage hypothesis)
make lint        # pyflakes + mypy (needs: pip install pyflakes mypy Kodistubs)
make build       # dist/plugin.image.photoprism-<version>.zip
make assets      # re-render icon.png/fanart.jpg from assets/*.svg (needs cairosvg, pillow)
make check       # test, test-zip, lint, build
```
Live test: `PP_URL=http://host:2342 PP_PASS=... PP_APP=<app password> python3 tests/test_live.py`
(expects an album called "Kodi Test" with 2 photos; recipe to create the server is in `docs/knowledge.md` §6).

## Conventions and rules
- Python must stay compatible with Kodi's interpreter (>=3.8 syntax). Use the **InfoTag API**, never `setInfo`.
- Settings ids live in `resources/settings.xml`; UI strings use ids >= 30000 in `strings.po`.
  `tests/test_static.py` fails if a label id is missing or a setting read by the code is undeclared.
- Bump `version` in `addon.xml` **and** add a `## [x.y.z]` entry to `CHANGELOG.md` together (also enforced).
- Never commit secrets (passwords, app passwords, tokens). Secrets live only in Kodi settings.
- UI text: never hard-code English in `plugin.py`; add a key to `STR`, the id to **both** `en_gb` and `it_it` `strings.po` (`tests/test_static.py` enforces parity).
- Log only through `self.log` (`AddonLog`), never `xbmc.log` directly; register any new secret with `add_secret()`. Tests prove that no secret reaches `debug.log` or `kodi.log`; keep it that way.
- Generated binaries (`icon.png`, `fanart.jpg`) are committed because the add-on must run from source;
  change the SVG and run `make assets` rather than editing them by hand.
- Work on a branch and open a PR; releases are cut by pushing a tag `vX.Y.Z` that matches `addon.xml`.
- When you learn or verify something non-obvious, record it in `docs/knowledge.md` and mark it
  `[verified]` only if you ran it yourself.

## Open items / backlog (highest value first)
1. **Test in the real Kodi** (LibreELEC 12.2.1): connection and browsing are confirmed; still to confirm are
   album covers (1.0.3), album dates and progress dialog (1.1.0), slideshow order, pan/zoom service, Italian UI,
   *Slideshow from here*, *On this day* and the other 1.2.0 items, video playback and the cache folder picker.
   The checklist is in issue #2.
2. (done in 1.2.2) Listings are re-read after 10 minutes (`LISTING_MAX_AGE`); thumbnails keep the long lifetime.
3. `public=true` in `api.photos()` hides Private photos (verified against a real server, knowledge.md §13); kept on
   purpose. Say so if the owner wants private photos shown.
4. (done in 1.2.2) 403 is its own error. (done in 1.2.2) root "Slideshow"/"Clear cache" are folder items closed
   with `endOfDirectory(succeeded=False)`; confirm in real Kodi that this leaves no spinner.
6. `run_prefetch()` joins worker threads (up to 60 s each) inside the plugin invocation; confirm it does not
   delay directory display in Kodi, otherwise move it to a service or detach it.
7. Preview/download tokens appear in image/video URLs, so they can show up in Kodi debug logs. Acceptable for a
   LAN setup; document it for users or mask in logs.
8. Optional: migrate `tests/` to pytest; consider `<reuselanguageinvoker>` (careful: module-level `ADDON`
   settings would then go stale); consider a Kodi repository add-on so updates install automatically.
