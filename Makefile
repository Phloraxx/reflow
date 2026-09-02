PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PIP_CONSTRAINT ?= requirements/ci-constraints.txt
PIP_VERSION ?= 26.2.1

.PHONY: install test lint type web-check check artifact-check submission-preflight submission-check

install:
	$(PYTHON) -m pip install --upgrade 'pip==$(PIP_VERSION)'
	$(PYTHON) -m pip install -c $(PIP_CONSTRAINT) -e '.[dev,postgres,web]'
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

artifact-check:
	$(PYTHON) -m reflow.evaluation.final_campaign --manifest data/eval/gate19/heldout_manifest.json --verify data/eval/gate19/final-heldout.json
	$(PYTHON) -m reflow.evaluation.failure_campaign --verify data/eval/gate19/failure-campaign.json
	$(PYTHON) -m reflow.evaluation.final_summary --check data/eval/gate19/final-summary.json
	$(PYTHON) -m reflow.evaluation.scale_runner --verify data/eval/gate17/scale-10000-clean.json
	$(PYTHON) -m reflow.evaluation.persistence_runner --verify data/eval/gate17/postgres-1000-cold-warm.json
	$(PYTHON) -m reflow.evaluation.final_report --check EVALUATION.md

submission-preflight:
	@test -n "$(REFLOW_TEST_POSTGRES_DSN)" || (echo 'REFLOW_TEST_POSTGRES_DSN is required: submission-check must exercise PostgreSQL durability tests.' >&2; exit 2)

submission-check: submission-preflight check artifact-check
