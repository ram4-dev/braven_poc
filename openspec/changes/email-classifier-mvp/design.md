# Design: Email Classifier MVP (JEV-powered insurance email pipeline)

## Technical Approach

Python ports-and-adapters pipeline: ingest → normalize → score (JEV via anti-corruption port) → pure rules core → append-only SQLite → FastAPI read/review/metrics API. Implements `jev-scoring`, `classification-rules`, `classification-storage`, `email-ingestion`, `human-review`, `classification-dashboard`, `classification-metrics` specs. Engine capability (scoring) and product policy (rules) stay separate per PROD.md §20. Synthetic data only.

**Stack (decided here):** Python 3.12, FastAPI, SQLite (stdlib `sqlite3`), `httpx` (Zen client), `pydantic` (config/validation models), `PyYAML` (versioned configs), `pytest` + `pytest-cov` (tests), `ruff` (lint+format). Rationale: FastAPI gives typed request/response models matching the spec-driven API surface; SQLite is zero-ops and the append-only swap-out concern is isolated behind a repository port; httpx has timeouts/retries and a sync API simple enough for a PoC; pytest is the default Python runner and satisfies Strict TDD.

## Architecture Decisions

| # | Decision | Choice | Alternatives rejected | Rationale |
| --- | ---------- | -------- | ---------------------- | ----------- |
| D1 | Band naming | Canonical values `AUTOMATIC`, `UNCERTAIN`, `HUMAN_REVIEW` (stored field `classification_band`, never a taxonomy label) | `AUTO` (proposal shorthand), storing UNCERTAIN as a label | `openspec/config.yaml` rules require PROD.md §11 vocabulary; all 7 specs already use `AUTOMATIC`. Proposal's `AUTO` is corrected here. |
| D2 | Threshold table | Default: auto 0.90, review floor 0.65. Elevated tier (auto 0.95, paired review floor **0.40**): `primary_category/FRAUD_SUSPICION`, `primary_category/LEGAL`, `sensitivity/HIGHLY_CONFIDENTIAL`. `PERSONAL_DATA`, `SENSITIVE_PERSONAL_DATA` stay on default 0.90/0.65. Keys are `(dimension, label)`; loader rejects unknown labels and any floor ≥ auto | 0.55/0.60 floors (weaker recall guard); raising floors for PERSONAL_DATA too (lowers precision without evidence) | 0.40 is strictly below 0.65 → a mid-score fraud/legal/HIGHLY_CONFIDENTIAL signal routes to review instead of failing silently. Fail-closed override: any sensitive-tier label ≥ its floor forces review regardless of band. |
| D3 | JEV client | Port `ScoringEngine` (Protocol). Adapters: `ZenJevScorer` (httpx, `POST https://opencode.ai/zen/v1/systemone`, model `jev-1.13`, one request per email, timeout 30s, max 2 retries w/ exponential backoff on 5xx/network errors, fail-closed on exhaustion → status FAILED + review queue) and `FakeDeterministicScorer` (hash-seeded reproducible scores, same rules path). Response mapping: `answers.<question_id>.noul` per research.md; strict validation (missing/non-numeric/out-of-range ⇒ reject). API key read ONLY from env `OPENCODE_API_KEY` at adapter construction — never in code, config, or logs | requests (sync-only, no timeout ergonomics), waiting for real contract, pass-through engine vocabulary | Port isolates the one mapping point (D3 contract below); envelope field names come from research.md (docs-verified 2026-10-05); if the real API disagrees, only the adapter mapping changes. Fake scorer unblocks all TDD. |
| D4 | Package layout | `src/email_classifier/` with `domain/` (pure rules, models, zero I/O), `ports/` (Protocols), `adapters/` (`inbox_dataset`, `zen_jev`, `fake_scorer`, `sqlite_repo`), `pipeline/` (orchestration, replay), `api/` (FastAPI), `config/` (`questions.yaml`, `thresholds.yaml`, loaders/validators) | flat scripts; engine-first design | Dependency direction: `domain` ← everything; adapters depend on ports only; config is versioned data validated against the frozen label set at load. |
| D5 | Storage | Append-only SQLite; see DDL below. Composite `classifier_version = "tax-mvp1+qs-v1+eng-jev-1.13+th-<hash8>"` where th-hash is the SHA-256 prefix of `thresholds.yaml`. Replay copies `raw_scores`/engine version into new rows under a new threshold version; zero engine calls. Idempotency: `emails.message_id UNIQUE` + run id | mutable current-state rows; bare `insurance-email-v1` string | §14/§15 verbatim-score and version-comparison requirements; "why did this label change" must be answerable from the row alone. |
| D6 | Dataset format | `datasets/inbox_mvp_v1.json` (schema below), ~120 synthetic emails: ≥5 per primary category, ≥8 per sensitivity label, ~15 boundary cases (COMPLAINT/LEGAL overlap, claim triple, lead vs quote, sensitive at 0.40–0.95 scores), Argentine-Spanish bodies | smaller set; real data | Coverage of all 16 categories + 6 sensitivities with ground truth = the dataset itself (frozen slice, D7). |
| D7 | Frozen evaluation slice | **Accept** the residual closed-loop risk as mitigated by construction: the dataset's `expected` labels ARE the frozen ground truth, immutable, read-only to metrics; reviewer corrections append to `human_reviews` only and never touch `expected` | a separate hand-labeled holdout slice (redundant for a PoC whose corpus is fully synthetic) | Metrics spec requires exactly this; no real-world drift exists in a synthetic corpus. |
| D8 | API surface | FastAPI routes below (read + review + replay + metrics) | server-rendered dashboard | Spec requires a listing/queue/correction API; UI can come later. |

## Data Flow

```
inbox_mvp_v1.json ──> DatasetInboxAdapter ──> normalize EmailMessage
                                                  │
                                                  v
        ZenJevScorer / FakeScorer (1 HTTP req per email, all 28 nouls)
              │ answers.<qid>.noul  (fail-closed on error)
              v
        pure rules core: banding -> selection -> implications -> review routing
              │ raw_scores verbatim + band + labels + threshold hash
              v
        SQLite append-only ──> FastAPI (list, detail, queue, review, metrics, replay)
```

### Ingest-to-label sequence

```
Pipeline -> InboxSource.list() -> normalize -> persist email(+attachments)
Pipeline -> ScoringEngine.score(email, questions.yaml) -> validated scores
Pipeline -> rules.decide(raw_scores, thresholds.yaml) -> Decision
Pipeline -> ClassificationRepository.append(email, decision, timestamps)
       [review-required | failed] -> review_queue entry
```

### Human review correction sequence

```
GET /api/review-queue -> reviewer opens entry
POST /api/reviews {classification_id, status, deltas[]} -> validate labels
  -> INSERT human_reviews + human_review_deltas (append-only)
  -> queue entry closed; dashboard reads deltas over automated values as "current"
```

## File Changes

| File | Action | Description |
| ------ | -------- | ------------- |
| `pyproject.toml` | Create | PEP 621 project, deps, pytest/ruff config |
| `src/email_classifier/domain/models.py` | Create | `EmailMessage`, `Decision`, `Band` (AUTOMATIC/UNCERTAIN/HUMAN_REVIEW), frozen label enums |
| `src/email_classifier/domain/rules.py` | Create | Pure banding/selection/implications/precedence over `(raw_scores, ThresholdConfig)` |
| `src/email_classifier/ports/__init__.py` | Create | `EmailSource`, `ScoringEngine`, `ClassificationRepository`, `AttachmentExtractor` Protocols |
| `src/email_classifier/adapters/inbox_dataset.py` | Create | JSON dataset adapter, idempotent by message_id |
| `src/email_classifier/adapters/zen_jev.py` | Create | httpx Zen adapter, retry/timeout, `answers.<qid>.noul` mapping |
| `src/email_classifier/adapters/fake_scorer.py` | Create | Deterministic seeded scorer |
| `src/email_classifier/adapters/sqlite_repo.py` | Create | Append-only repository + read model + replay queries |
| `src/email_classifier/pipeline/pipeline.py`, `replay.py` | Create | Orchestration; replay under new thresholds (0 engine calls) |
| `src/email_classifier/api/app.py` | Create | FastAPI app + routes |
| `src/email_classifier/config/questions.yaml`, `thresholds.yaml`, `loader.py` | Create | Versioned question set (28 nouls w/ criteria) + threshold table; load-time validation |
| `datasets/inbox_mvp_v1.json` | Create | Synthetic corpus + expected labels (D6) |
| `tests/…` | Create | Unit (domain pure), adapter, integration (pipeline), API tests |
| `openspec/config.yaml` | Modify | testing commands + runner_status (below) |

## Interfaces / Contracts

```python
class ScoringEngine(Protocol):
    def score(self, email: EmailMessage, questions: QuestionSet) -> ScoreResult: ...
    # ScoreResult: scores: dict[qid, float 0..1] | raises ScoringError (fail-closed)

# Zen request: {"model": "jev-1.13", "state": <composed text>, "questions": {qid: {"type":"noul","instructions":..., "criteria":{"true":...,"false":...}}}}
# Zen response: answers.<question_id>.noul -> float  (per research.md; adapter-isolated)
```

```sql
CREATE TABLE emails (email_id TEXT PK, message_id TEXT UNIQUE NOT NULL, thread_id,
  sender, recipients TEXT/*json*/, subject, body, received_at, ingested_at, source, raw_ref);
CREATE TABLE email_attachments (attachment_id TEXT PK, email_id REF, filename, mime,
  extracted_text, extraction_status CHECK(extraction_status IN ('extracted','not_text_extractable','failed')));
CREATE TABLE classifications (classification_id TEXT PK, email_id REF, status CHECK(status IN
  ('CLASSIFIED','FAILED','REPLAYED')), classifier_version TEXT NOT NULL, engine_version,
  question_set_version, threshold_set_version, raw_scores TEXT/*json verbatim*/,
  engine_request_id, confidence REAL, classification_band CHECK(classification_band IN
  ('AUTOMATIC','UNCERTAIN','HUMAN_REVIEW')), requires_human_review INT, primary_category,
  secondary_categories TEXT/*json*/, sensitivity TEXT/*json*/, actions TEXT/*json*/, priority,
  received_at, ingested_at, scored_at, classified_at, source_classification_id);
CREATE TABLE classification_labels (label_id TEXT PK, classification_id REF, dimension, label,
  score REAL, threshold_applied REAL, selected INT);
CREATE TABLE human_reviews (review_id TEXT PK, classification_id REF, status CHECK(status IN
  ('CONFIRMED','CORRECTED')), reviewer_id, reviewed_at, notes);
CREATE TABLE human_review_deltas (delta_id TEXT PK, review_id REF, dimension, operation
  CHECK(operation IN ('set','add','remove')), original_value, corrected_value);
```

### API routes

```
GET  /api/emails                      # listing: all dimensions + band + status
GET  /api/emails/{email_id}           # detail: current values, originals, raw scores, thresholds, classifier_version
GET  /api/review-queue?reason=        # entries with queue reason; filterable
POST /api/reviews                     # {classification_id, status, deltas[], reviewer_id}
POST /api/replay                      # {threshold_set_version} -> new append-only rows
GET  /api/metrics                     # accuracy (num/den), per-category P/R, sensitive FN rate, review rate, latency, OTHER rate, caveats, versions
GET  /api/health
```

### Dataset schema (`inbox_mvp_v1.json`)

```json
{"dataset_version": "v1",
 "emails": [{
   "message_id": "em-0001", "sender": "...", "recipients": ["..."],
   "subject": "...", "body": "...", "thread_id": "th-01|null",
   "received_at": "2026-10-05T14:32:00Z",
   "attachments": [{"filename": "denuncia.pdf", "mime": "application/pdf",
                    "extracted_text": "...|null", "status": "extracted"}],
   "expected": {"primary_category": "CLAIM_NEW", "secondary_categories": ["CLAIM_DOCUMENTATION"],
                "sensitivity": ["PERSONAL_DATA"], "actions": ["REPLY_REQUIRED"], "priority": "HIGH"}}]}
```

## Testing Strategy

| Layer | What to Test | Approach |
| ------- | ------------- | ---------- |
| Unit | Pure rules: band boundaries (0.65/0.90/0.95/0.40 inclusive/exclusive), tie-break determinism, implications, NO_ACTION exclusivity, priority precedence, config validation rejects | pytest against `domain/rules.py`, no I/O |
| Adapter | Fake scorer determinism; Zen adapter: envelope mapping, strict validation, timeout/retry → `ScoringError` (httpx MockTransport); dataset adapter idempotency | pytest |
| Integration | Full pipeline over dataset subset: end-to-end append-only writes, replay (0 engine calls, new rows), review flow, zero-silent-drop invariant | pytest + tmp SQLite file |
| API/E2E | Routes: listing, queue filter, review POST deltas, metrics numerators/denominators | FastAPI TestClient |
| Commands | test `python -m pytest -q` · lint `ruff check .` · coverage `python -m pytest --cov=src/email_classifier --cov-report=term-missing` · setup/build `python -m pip install -e .` | Harness lands in work unit 1 (RED first) |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary. Outbound HTTPS to Zen stays inside the `ScoringEngine` port; the API key is env-only, never logged or persisted.

## Migration / Rollout

Greenfield: no migration. Rollback = revert branch; append-only tables mean nothing destructive to undo. `config.yaml` command fields revert with the same revert.

## Open Questions

- [ ] Live smoke test of the real Zen envelope (`answers.<qid>.noul`) gated on `OPENCODE_API_KEY` being present — one optional apply-phase verification task; fake scorer is unaffected either way.
- [ ] Exact question wording for the 28 nouls is authoring work budgeted in tasks; versioning scheme `qs-v1` starts there.
