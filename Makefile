PY ?= python3

.PHONY: test test-zip coverage lint build assets check clean
test:
	$(PY) tests/test_addon.py
	$(PY) tests/test_properties.py
	$(PY) tests/test_static.py

test-zip:
	$(PY) tools/test_zip.py

coverage:
	rm -f .coverage .coverage.*
	$(PY) -m coverage run -p --source=plugin.image.photoprism --omit=*/default.py tests/test_addon.py
	$(PY) -m coverage run -p --source=plugin.image.photoprism --omit=*/default.py tests/test_properties.py
	$(PY) -m coverage combine -q
	$(PY) -m coverage report -m --fail-under=93

lint:
	$(PY) -m pyflakes plugin.image.photoprism tests tools
	$(PY) -m mypy --ignore-missing-imports --check-untyped-defs plugin.image.photoprism

build:
	$(PY) tools/build_zip.py

assets:
	$(PY) tools/render_assets.py

check: test test-zip lint build

clean:
	rm -rf dist .mypy_cache .coverage .coverage.* .hypothesis
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
