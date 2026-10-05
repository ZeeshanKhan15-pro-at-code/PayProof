PYTHON ?= python3
VENV := .venv
PY := $(VENV)/bin/python

.PHONY: setup verify lint format typecheck test build debug benchmark benchmark-extraction serve production demo demo-smoke

setup: $(VENV)/.ready

$(VENV)/.ready: pyproject.toml requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --disable-pip-version-check --no-cache-dir -r requirements-dev.txt
	$(PY) -m pip install --disable-pip-version-check --no-build-isolation --no-deps -e .
	touch $(VENV)/.ready

# Sequential sub-make keeps verification deterministic, even under make -j.
verify: setup
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test
	$(PY) -m payproof check
	$(MAKE) benchmark
	$(MAKE) build

lint: setup
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

format: setup
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

typecheck: setup
	$(PY) -m mypy

test: setup
	$(PY) -m pytest -q

# Standard distributable Python artifacts; no frontend asset compilation.
build: setup
	$(PY) -m build --no-isolation
	$(PY) scripts/check_wheel.py

debug: setup
	$(PY) -m payproof debug

benchmark: setup
	$(PY) -m payproof benchmark --output benchmarks/phase1-v1/results/gold

benchmark-extraction: setup
	$(PY) -m payproof benchmark --with-extraction --output benchmarks/phase1-v1/results/extraction

# Interactive instruction review; no independent verification is recorded.
demo: setup
	$(PY) -m payproof demo

# Explicitly simulated source review, confined to the seeded synthetic demo.
demo-smoke: setup
	$(PY) -m payproof demo --simulate-review

# Local read-only debug server, without the interactive debugger or reloader.
serve: setup
	$(PY) -m payproof serve

# A host/reverse proxy must restrict access and provide HTTPS.
production: setup
	PAYPROOF_ENV=production $(VENV)/bin/gunicorn --bind 127.0.0.1:8000 --workers 1 --threads 2 'payproof.web:create_app()'
