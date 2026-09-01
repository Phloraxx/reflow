PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: install test lint type web-check check

install:
	$(PYTHON) -m pip install -e '.[dev,postgres,web]'
	cd web && npm ci

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

type:
	$(PYTHON) -m mypy src

web-check:
	cd web && npm run check
	cd web && npm test
	cd web && npm run build

check: lint type test web-check
