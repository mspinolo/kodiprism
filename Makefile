PY ?= python3

.PHONY: test test-zip coverage lint build repo assets check clean
test:
	$(PY) -m pytest -q

test-zip:
	$(PY) tools/test_zip.py

coverage:
	rm -f .coverage .coverage.*
	$(PY) -m coverage run -p --source=plugin.image.photoprism --omit=*/default.py -m pytest -q
	$(PY) -m coverage combine -q
	$(PY) -m coverage report -m --fail-under=93

lint:
	$(PY) -m pyflakes plugin.image.photoprism tests tools
	$(PY) -m mypy --ignore-missing-imports --check-untyped-defs plugin.image.photoprism

build:
	$(PY) tools/build_zip.py
	$(PY) tools/build_zip.py repository.kodiprism

repo: build
	$(PY) tools/build_repo.py dist/repo dist/plugin.image.photoprism-*.zip dist/repository.kodiprism-*.zip

assets:
	$(PY) tools/render_assets.py

check: test test-zip lint repo

clean:
	rm -rf dist .mypy_cache .pytest_cache .coverage .coverage.* .hypothesis
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
