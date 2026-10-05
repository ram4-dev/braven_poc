# Email Classifier MVP

A JEV-powered insurance email classification pipeline: it ingests emails from a
JSON dataset (or any `EmailSource` implementation), scores every email against
a 28-question set in a single engine call, and applies a pure, versioned rules
core (banding, category/sensitivity/action selection, implications, precedence,
review routing) to produce an append-only classification record per email in
SQLite. Emails that fail scoring or carry sensitive signals above their review
floor are queued for human review — zero silent drops. Classification history
is immutable: a "replay" can relabel stored emails under a new threshold-set
version without a single engine call.

## Install

```bash
uv venv .venv
uv pip install -e . --python .venv/bin/python
```

(Or with pip in any Python 3.12+ virtualenv: `python -m pip install -e .`.)

## Run the pipeline

```python
from email_classifier.adapters.inbox_dataset import InboxDatasetSource
from email_classifier.adapters.fake_scorer import FakeDeterministicScorer
from email_classifier.adapters.sqlite_repo import SqliteRepository
from email_classifier.config.loader import load_questions, load_thresholds
from email_classifier.pipeline.pipeline import Pipeline

repo = SqliteRepository("inbox.db")
report = Pipeline(
    source=InboxDatasetSource.from_file("datasets/inbox_mvp_v1.json"),
    engine=FakeDeterministicScorer(),
    repository=repo,
    thresholds=load_thresholds("src/email_classifier/config/thresholds.yaml"),
    questions=load_questions("src/email_classifier/config/questions.yaml"),
).run()

print(report)  # ingested / processed / classified / failed / queued
print(len(repo.list_review_queue()), "emails queued for human review")
```

## Run the API

```bash
uvicorn email_classifier.api.app:app --port 8000
```

- `GET /api/health` — liveness.
- `GET /api/emails`, `GET /api/emails/{id}` — listing and classification detail
  (including full history).
- `GET /api/review-queue` — emails awaiting human review, filterable by reason.
- `POST /api/reviews` — record a CONFIRMED/CORRECTED review (append-only; never
  mutates a classification).
- `POST /api/replay` — relabel stored emails under a new threshold-set version.
- `GET /api/metrics` — evaluation metrics (precision/recall per label vs.
  `expected` ground truth, band distribution, queue share) attributed to the
  config versions that produced them.

## Run the tests

```bash
.venv/bin/python -m pytest -q                                  # full suite
.venv/bin/python -m pytest --cov=email_classifier --cov-report=term-missing
.venv/bin/ruff check .                                         # lint
```

## Fake vs. live scorer

The pipeline depends only on the `ScoringEngine` port, so the engine is a
drop-in swap:

- **Fake (offline, deterministic):** `FakeDeterministicScorer` — hash-seeded
  probabilities, zero network. Used by tests and local runs.
- **Live (Zen JEV):** `ZenJevScorer` — one POST per email to the Zen API,
  strict fail-closed validation of the `answers.<qid>.noul` envelope, bounded
  retry for 5xx/network errors. Requires `OPENCODE_API_KEY` in the
  environment:

  ```bash
  export OPENCODE_API_KEY=...   # required; never logged or embedded in errors
  ```

Both implement the same port — swap the constructor argument, nothing else
changes.

## Replay

Replay relabels stored emails from their **stored raw scores** through the same
pure rules path as the initial run — it issues **zero engine calls**. Under a
modified threshold configuration a new classification record is appended (the
old one stays retrievable); re-running with the same threshold set is an
idempotent no-op. Either via `POST /api/replay` or:

```python
from dataclasses import replace
from email_classifier.pipeline.replay import replay

strict = replace(thresholds, default_auto_threshold=0.99, version="th-strict")
replay(repository=repo, thresholds=strict, email_ids=report.email_ids)
```
