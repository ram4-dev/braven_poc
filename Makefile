# Email classifier MVP — developer tasks.
# All commands use the project's uv-managed Python 3.12 venv.

PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff

.PHONY: install test test-e2e test-rules test-adapters test-api lint coverage live replay-help

## install: set up the venv package in editable mode (run once after cloning)
install:
	uv pip install -e ".[dev]" -p $(PYTHON)

## test: run the full test suite
test:
	$(PYTHON) -m pytest

## test-e2e: run ONLY the end-to-end corpus proof (125 emails through the
## full pipeline: ingest -> score -> rules -> SQLite -> review queue -> replay)
test-e2e:
	$(PYTHON) -m pytest tests/e2e -v

## test-rules: pure domain rules only (fast, no I/O)
test-rules:
	$(PYTHON) -m pytest tests/domain -v

## test-adapters: scorer/inbox/SQLite adapter tests
test-adapters:
	$(PYTHON) -m pytest tests/adapters -v

## test-api: FastAPI surface tests
test-api:
	$(PYTHON) -m pytest tests/api -v

## lint: ruff checks
lint:
	$(RUFF) check .

## coverage: full suite with coverage report
coverage:
	$(PYTHON) -m pytest --cov=email_classifier --cov-report=term-missing

## live: run the 125-email corpus through the REAL JEV engine
## (requires OPENCODE_API_KEY in .env or the environment; costs tokens)
live:
	set -a && source .env && set +a && $(PYTHON) scripts/live_corpus.py
