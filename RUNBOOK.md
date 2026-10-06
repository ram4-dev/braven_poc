# Runbook — Email Classifier MVP

Operational guide for running, testing and evaluating the insurance email
classification pipeline. For architecture and design rationale, see
`openspec/changes/email-classifier-mvp/design.md`.

## Prerequisites

| Requirement | Check | Install if missing |
| --- | --- | --- |
| Python 3.12 (via uv) | `.venv/bin/python --version` | `brew install uv` |
| Docker via Colima (optional, not needed for tests) | `colima status` | `brew install colima docker` |
| OpenCode API key (live runs only) | `.env` contains `OPENCODE_API_KEY=...` | key lives in the Secret Vault (`OPENCODE_GO_API_KEY`) |

## One-time setup

```bash
make install            # creates/updates .venv (uv-managed, Python 3.12)
```

The `.venv/` directory is gitignored. Every `make` target uses it; no system
Python is touched (macOS system Python is 3.9 and unsupported).

## Daily commands

| Command | What it does |
| --- | --- |
| `make test` | Full suite: 247 tests (unit, adapters, pipeline, API, dataset, e2e) |
| `make test-e2e` | End-to-end proof only: 125-email corpus through the real pipeline |
| `make demo` | Same corpus run, human-readable output at every stage |
| `make lint` | ruff checks |
| `make coverage` | full suite + coverage report (expect ~97%) |
| `make live` | REAL JEV evaluation over the corpus (costs tokens; needs `.env`) |

## What the e2e test actually verifies

`make test-e2e` runs `tests/e2e/test_corpus_run.py`: the full system, no mocks.

```
datasets/inbox_mvp_v1.json (125 synthetic emails)
  -> InboxDatasetSource (JSON adapter)
  -> scoring engine (28 questions, one request per email)
  -> pure rules (banding, selection, implications)
  -> real SQLite file (append-only, 6-table DDL)
  -> review queue + replay under new thresholds
```

Five invariants, each machine-checked:

1. **Item count**: all 125 emails ingested, 125 unique email_ids in storage.
2. **One current classification per email**: history length is exactly 1 on a
   first run; the current record equals the history's only record.
3. **Zero silent drops**: the set of emails that MUST be queued is recomputed
   independently (stored raw_scores x threshold floors) and cross-checked
   against the actual review queue. Any sensitive signal at/above its floor
   that is not in the queue fails the test.
4. **Failures are never dropped**: one email is forced to fail scoring
   (`ScoreError`); it must appear in storage as `FAILED` (no fabricated
   labels) and in the queue with reason `scoring_failed`.
5. **Replay with zero engine calls**: relabeling the whole corpus under a new
   threshold config appends 125 rows, keeps raw scores byte-identical, keeps
   the prior record retrievable, and the spy engine proves the scoring engine
   was called only by the initial run (125 requests total, never 250).

Expected output: `5 passed`. Exit code 0.

## Inspectable demo (when you want to SEE it work)

```bash
make demo
```

Prints six stages: ingest counts, pipeline run counts, the audit trail of one
email (raw scores, classifier version, band), the review-queue breakdown by
reason, a replay showing how many labels changed, and metrics against the
dataset's frozen ground truth. Safe to run repeatedly (throwaway SQLite file
in a temp dir).

## Live evaluation with real JEV

```bash
make live
```

Runs the same 125-email corpus through `ZenJevScorer` against
`https://opencode.ai/zen/v1/systemone` (model `jev-1.13`). Reads the key from
`.env` (`OPENCODE_API_KEY`). Reference result from 2026-10-05:

```
accuracy: 83/125 = 66.4%          review rate: 79.2%
FN rate  : PERSONAL_DATA 4.2%     SENSITIVE_PERSONAL_DATA 0.0%
           HIGHLY_CONFIDENTIAL 0.0%
failures : 0                      wall time: ~74s
```

Notes:

- The free tier (`jev-1.13-free`) returns identical answers; switch it with
  `OPENCODE_MODEL=jev-1.13-free`.
- The gateway rejects requests without a coding-agent `User-Agent`
  (Cloudflare 403, error 1010). The adapter already sends
  `poc-classifier/0.1.0` and a stable `x-opencode-session` — do not remove
  those headers.
- The accuracy number is only meaningful with the real engine: the offline
  `FakeDeterministicScorer` is hash-random by design.

## Threshold tuning (without re-classifying)

Raw scores are stored verbatim per classification, so new thresholds never
require new engine calls:

```bash
.venv/bin/python -c "
from email_classifier.pipeline.replay import replay
from email_classifier.adapters.sqlite_repo import SqliteRepository
from email_classifier.config.loader import load_thresholds
from dataclasses import replace
repo = SqliteRepository('path/to/db.sqlite3')
t2 = replace(load_thresholds('src/email_classifier/config/thresholds.yaml'),
             default_auto_threshold=0.85, version='th-tuned-v1')
print(replay(repository=repo, thresholds=t2, email_ids=[...]))
"
```

Replay is idempotent per threshold version: re-running the same version
appends nothing. History is append-only; the previous labels stay auditable.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ModuleNotFoundError: email_classifier` | venv missing or editable install stale | `make install` |
| `ModuleNotFoundError: email_classifier.domain` under a fresh checkout | no `.venv` yet | `make install` |
| pytest resolves Python 3.9 | system python leaked into PATH | always use `.venv/bin/python` or `make` targets |
| Pyright flags `enum.StrEnum` / `httpx` unresolved | editor resolving system Python | `pyrightconfig.json` already pins 3.12 + `.venv`; reload the editor window |
| `ZenJevScorer` raises `ValueError: OPENCODE_API_KEY is not set` | live key not exported | create `.env` with `OPENCODE_API_KEY=...` (key lives in the Secret Vault) |
| Live run: HTTP 403 error 1010 | gateway bot shield | already fixed in the adapter (agent `User-Agent` + session header); if you wrote your own client, add those headers |
| `ConfigError: ... has no paired review floor` | threshold YAML edited badly | every label above the default auto threshold needs `review_floor:` strictly below the default floor |
| Live smoke returns 429 | free-tier rate limit | retry with backoff or switch to paid `jev-1.13` |

## Where things live

| Path | Purpose |
| --- | --- |
| `src/email_classifier/domain/` | pure rules + models (zero I/O, enforced by test) |
| `src/email_classifier/adapters/` | fake scorer, Zen JEV client, dataset inbox, SQLite repo |
| `src/email_classifier/config/` | versioned `questions.yaml` (28 nouls) + `thresholds.yaml` |
| `src/email_classifier/pipeline/` | orchestration, replay, metrics |
| `src/email_classifier/api/` | FastAPI surface |
| `datasets/inbox_mvp_v1.json` | 125-email synthetic corpus + frozen expected labels |
| `scripts/live_corpus.py` | live JEV runner (`make live`) |
| `scripts/e2e_demo.py` | inspectable demo (`make demo`) |
| `tests/e2e/test_corpus_run.py` | the e2e invariants (`make test-e2e`) |

## Known limitations (PoC scope)

- Attachment text extraction is pass-through from the dataset (`extracted_text`
  provided); no OCR/vision — image-only attachments count in the metrics'
  attachment-gap limitation.
- Ground truth is the synthetic corpus's own `expected` labels (frozen slice);
  reviewer corrections never rewrite it.
- SQLite is single-writer; fine for PoC volumes, swap the repository port for
  Postgres when scaling.
- The human-review API has no auth — bind to localhost only.
