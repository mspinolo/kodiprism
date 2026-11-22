PY ?= python3

.PHONY: test lint build assets check clean
test:
	$(PY) tests/test_addon.py
	$(PY) tests/test_static.py

lint:
	$(PY) -m pyflakes plugin.image.photoprism tests tools
	$(PY) -m mypy --ignore-missing-imports --check-untyped-defs plugin.image.photoprism

build:
	$(PY) tools/build_zip.py

assets:
	$(PY) tools/render_assets.py

check: test lint build

clean:
	rm -rf dist .mypy_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
