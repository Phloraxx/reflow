.PHONY: install test lint type check

install:
	python -m pip install -e '.[dev]'

test:
	python -m pytest

lint:
	python -m ruff check .

type:
	python -m mypy src

check: lint type test
