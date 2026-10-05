# Tasks: Email Classifier MVP (JEV-powered insurance email pipeline)

Inputs: `proposal.md`, `design.md` (authoritative for DDL, routes, dataset schema, commands), 7 delta specs (48 requirements), `openspec/config.yaml` (strict TDD, `python -m pytest -q`).

## Review Workload Forecast

| Field | Value |
| ------- | ------- |
| Estimated changed lines | ≈5,400 authored (≈1,750 source + ≈1,900 tests + ≈225 versioned YAML + ≈60 docs) plus ≈1,800 lines of dataset corpus (`datasets/inbox_mvp_v1.json`) |
| 400-line budget risk | High at change level; every work unit below is sized ≤400 (dataset unit is a documented `size:exception`) |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 17 (one work unit per PR) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

```text
Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High
```

### Suggested Work Units

Unit numbering = PR numbering. Units 2–17 are stacked on the previous one; `feature-branch-chain` bases are noted where they differ.

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
| ------ | ------ | ----------- | ---------------------- | ----------------- | ------------------- |
| 1 | Harness lands RED-then-GREEN before any feature code | PR 1 (base: tracker branch `email-classifier-mvp`) | `python -m pytest -q` | `python -m pip install -e . && python -m pytest -q` (package importable) | Delete `pyproject.toml`, `src/email_classifier/__init__.py`, `tests/test_smoke.py` |
| 2 | Pure domain contracts + port Protocols | PR 2 | `python -m pytest -q tests/domain/test_models.py tests/ports/test_ports.py` | N/A — import-only, zero I/O by design | Remove `domain/models.py`, `ports/__init__.py` |
| 3 | Banding + review routing (pure) | PR 3 | `python -m pytest -q tests/domain/test_rules_banding.py` | N/A — pure functions, no I/O | Remove banding/review-routing functions from `domain/rules.py` |
| 4 | Category selection, implications, precedence (pure) | PR 4 | `python -m pytest -q tests/domain/test_rules_selection.py` | N/A — pure functions, no I/O | Remove selection/implication functions from `domain/rules.py` |
| 5 | Threshold table config + load-time validation | PR 5 | `python -m pytest -q tests/config/test_thresholds_loader.py` | `python -c "from email_classifier.config.loader import load_thresholds as l; print(l('src/email_classifier/config/thresholds.yaml').version)"` | Remove `config/thresholds.yaml` + `load_thresholds` |
| 6 | 28-question set config + validation | PR 6 | `python -m pytest -q tests/config/test_questions_loader.py` | `python -c "from email_classifier.config.loader import load_questions as l; print(len(l('src/email_classifier/config/questions.yaml').questions))"` → 28 | Remove `config/questions.yaml` + `load_questions` |
| 7 | Offline adapters: fake scorer + dataset inbox | PR 7 | `python -m pytest -q tests/adapters/test_fake_scorer.py tests/adapters/test_inbox_dataset.py` | Real fixture `tests/fixtures/inbox_small.json` parsed end to end | Remove `adapters/fake_scorer.py`, `adapters/inbox_dataset.py`, fixture |
| 8 | Append-only schema + classification write/read | PR 8 | `python -m pytest -q tests/adapters/test_sqlite_repo.py` | Real SQLite file in `tmp_path` (no mocks) | Remove `sqlite_repo.py` classification surface; DB file is throwaway |
| 9 | Review persistence + queue read/filter | PR 9 | `python -m pytest -q tests/adapters/test_sqlite_reviews.py` | Real SQLite file in `tmp_path` | Remove review tables access from `sqlite_repo.py` |
| 10 | Zen JEV adapter (anti-corruption) | PR 10 | `python -m pytest -q tests/adapters/test_zen_jev.py` | `httpx.MockTransport`; live smoke gated in PR 17 | Remove `adapters/zen_jev.py` |
| 11 | Pipeline orchestration + run counts | PR 11 | `python -m pytest -q tests/pipeline/test_pipeline.py` | `python -m pytest -q tests/pipeline/test_pipeline.py` runs the full chain on the fixture | Remove `pipeline/pipeline.py` |
| 12 | Replay under new thresholds, zero engine calls | PR 12 | `python -m pytest -q tests/pipeline/test_replay.py` | Spy engine asserts 0 requests while new rows are appended | Remove `pipeline/replay.py`, `POST /api/replay` handler |
| 13 | Read API: listing, detail, queue, health | PR 13 | `python -m pytest -q tests/api/test_listing.py` | `uvicorn email_classifier.api.app:app --port 8000` + `curl /api/health` | Remove read routes from `api/app.py` |
| 14 | Review POST + replay endpoint | PR 14 | `python -m pytest -q tests/api/test_review_post.py` | `uvicorn …` + `curl -X POST /api/reviews` | Remove `POST /api/reviews` |
| 15 | Metrics engine + `/api/metrics` | PR 15 | `python -m pytest -q tests/pipeline/test_metrics.py` | `curl /api/metrics` after a fixture run | Remove `pipeline/metrics.py` + metrics route |
| 16 | Full synthetic corpus + coverage proof | PR 16 (`size:exception`) | `python -m pytest -q tests/dataset/test_corpus_coverage.py` | Corpus is data; coverage test asserts 16×5 / 6×8 / ≥15 boundary items | Delete `datasets/inbox_mvp_v1.json` (fixture corpus in PR 7 still works) |
| 17 | End-to-end corpus run, coverage, docs | PR 17 | `python -m pytest -q tests/e2e/test_corpus_run.py` | `python -m pytest --cov=email_classifier --cov-report=term-missing` + `ruff check .` | Remove e2e test + `README.md` |

## Phase 1: Test Harness (work unit 1 — must land before feature code)

- [x] 1.1 Create the worktree with `wt switch --create email-classifier-mvp` (config `delivery.worktrees: worktrunk`; never raw `git worktree add`). <!-- sdd-owner: implementation --> (Note: orchestrator-created worktree `braven_poc.pr1-harness-domain`, branch `pr1-harness-domain` at f144e01; verified via `git worktree list`.)
- [x] 1.2 RED: write `tests/test_smoke.py` asserting `email_classifier.__version__` exists; run `python -m pytest -q` and record the collection/import failure verbatim. <!-- sdd-owner: implementation --> (RED evidence: `ModuleNotFoundError: No module named 'email_classifier'` — `1 error during collection`.)
- [x] 1.3 GREEN: add `pyproject.toml` (PEP 621, `src/` layout, deps fastapi/httpx/pydantic/PyYAML, dev pytest/pytest-cov/ruff, ruff config) + `src/email_classifier/__init__.py`; `python -m pip install -e .`, `python -m pytest -q` passes, `ruff check .` clean. <!-- sdd-owner: implementation --> (Installed into local Python 3.12 venv via uv; pytest 1 passed, ruff `All checks passed!`.)
- [x] 1.4 Verify `openspec/config.yaml` testing block (`test_command`, `build_command`, `lint_command`, `coverage_command`, `strict_tdd: true`) matches the landed harness; edit only on drift. <!-- sdd-owner: implementation --> (No drift — all commands match the landed harness; no edit made.)

## Phase 2: Domain Contracts and Ports (work unit 2)

- [x] 2.1 RED `tests/domain/test_models.py` + `tests/ports/test_ports.py`: `EmailMessage`/`Attachment` carry subject, body, sender, recipients, received_at, thread_id, attachment names + extracted text + status (ingestion: Normalized email intake, Missing optional fields); `Band` is exactly `AUTOMATIC`/`UNCERTAIN`/`HUMAN_REVIEW` and never a taxonomy label; label sets equal `taxonomy_mvp`; `ScoreResult`, `ThresholdConfig`, `QuestionSet`, `Decision` shapes; fake classes satisfy `EmailSource`/`ScoringEngine`/`ClassificationRepository`/`AttachmentExtractor` (§A: Anti-corruption scoring boundary). <!-- sdd-owner: implementation -->
- [x] 2.2 GREEN `src/email_classifier/domain/models.py` (pure dataclasses/enums, zero I/O) + `src/email_classifier/ports/__init__.py` (4 Protocols + port errors). <!-- sdd-owner: implementation -->
- [x] 2.3 Verification: import graph test proves `domain/` and `ports/` import no adapter/httpx/sqlite modules; `ruff check .` clean. <!-- sdd-owner: implementation -->

## Phase 3: Rules — Banding and Review Routing (work unit 3)

- [x] 3.1 RED `tests/domain/test_rules_banding.py` covering classification-rules: Default band boundaries (0.90 → AUTOMATIC, 0.65 → UNCERTAIN, 0.64 → HUMAN_REVIEW), Elevated tier raises the auto bar (FRAUD_SUSPICION 0.94 → UNCERTAIN), Band is not a label, Paired floor routes a mid-score sensitive signal (0.80 → review + queue), Sensitive signal overrides an automatic band, Zero silent drops, plus human-review: Uncertain band queued, Failed scoring queued, Sensitive signal queued despite an automatic band (queue reason stated), No unfounded queue entries. <!-- sdd-owner: implementation --> (RED: `ModuleNotFoundError: No module named 'email_classifier.domain.rules'`, 1 collection error. GREEN: 19 passed.)
- [x] 3.2 GREEN `src/email_classifier/domain/rules.py`: `resolve_bands(raw_scores, thresholds)` over the MVP table (default 0.90/0.65; elevated 0.95/0.40 for `primary_category/FRAUD_SUSPICION`, `primary_category/LEGAL`, `sensitivity/HIGHLY_CONFIDENTIAL`) and `review_routing(...)` returning `requires_human_review` + queue reason. <!-- sdd-owner: implementation --> (Reason precedence: failed → sensitive ≥ floor → HUMAN_REVIEW band → UNCERTAIN band; sensitive-tier set = 5 labels from spec.)
- [x] 3.3 Boundary matrix test at 0.40 / 0.6499 / 0.65 / 0.8999 / 0.90 / 0.9499 / 0.95 for both default and elevated tiers (inclusive/exclusive edges proven). <!-- sdd-owner: implementation --> (Matrix asserts 7 scores × 2 tiers; full suite 47 passed, ruff clean.)

## Phase 4: Rules — Selection, Implications, Precedence (work unit 4)

- [x] 4.1 RED `tests/domain/test_rules_selection.py`: Confidence equals the primary score, Per-label scores remain available, Multi-category email, Deterministic tie-break (identical on replay), No category clears its floor (→ `OTHER` + review + counted for OTHER share), Implication applied (`SENSITIVE_PERSONAL_DATA` ⇒ `PERSONAL_DATA`), Action exclusivity (`NO_ACTION` dropped), Priority precedence (`CRITICAL` > `HIGH` > `NORMAL` > `LOW`), Complaint that is also a legal notice, New claim versus claim documentation, Identical input identical output. <!-- sdd-owner: implementation --> (RED: `ModuleNotFoundError: No module named 'email_classifier.domain.rules'` from prior partial run; continuation added 5 RED tests: per-label elevated auto eligibility (LEGAL/FRAUD_SUSPICION below 0.95 wrongly selected), pairwise precedence leak across unrelated pairs, version attribution — 4–5 failed.)
- [x] 4.2 GREEN selection + implication + precedence + version attribution in `src/email_classifier/domain/rules.py`, producing the full `Decision`. <!-- sdd-owner: implementation --> (Fixed per-label auto-threshold eligibility + pairwise `_ambiguity_demoted`; focused `tests/domain/test_rules_selection.py` → 29 passed.)
- [x] 4.3 Test that the precedence/implication configuration version is recorded in the `Decision` and differs when rules config changes. <!-- sdd-owner: implementation --> (`TestVersionAttribution`: config version recorded, classifier_version composite, differing configs → differing versions, implication attributed to config version.)

## Phase 5: Versioned Configuration (work units 5–6)

- [x] 5.1 RED `tests/config/test_thresholds_loader.py`: Invalid configuration rejected (floor ≥ auto → explicit load error, no classification runs), unknown label rejected, elevation without paired lower review floor rejected naming the label, Configuration version recorded, two configs differing in any threshold yield different versions. <!-- sdd-owner: implementation --> (RED: `ModuleNotFoundError: No module named 'email_classifier.config'`, 8 failed.)
- [x] 5.2 GREEN `src/email_classifier/config/thresholds.yaml` (default row + 3 elevated rows) + `load_thresholds` in `src/email_classifier/config/loader.py` (YAML → domain `ThresholdConfig`, version = SHA-256 prefix). <!-- sdd-owner: implementation --> (Focused: 8 passed; full suite 84 passed; ruff clean; runtime harness prints version `35d4c41e`. Also fixed test-pollution in `test_import_graph.py` runtime check: purge forbidden root modules alongside `email_classifier` before importing.)
- [x] 5.3 RED `tests/config/test_questions_loader.py`: One question per MVP label (16 categories + 6 sensitivity + 6 actions = 28, version reported), Question set versioned (wording/criteria change bumps version; stored classifications keep theirs), Deferred label requested (loading fails naming the deferred label, no scoring runs). <!-- sdd-owner: implementation --> (RED: `ImportError: cannot import name 'load_questions'`, 17 failed. Final: 17 passed incl. all 6 deferred-label rejections naming each label.)
- [x] 5.4 GREEN `src/email_classifier/config/questions.yaml` (28 nouls, each with `type: noul` + true/false criteria; disambiguation criteria for COMPLAINT/LEGAL, CLAIM_NEW/UPDATE/DOCUMENTATION, NEW_LEAD/QUOTE_REQUEST) + `load_questions` validation. <!-- sdd-owner: implementation --> (17 passed; shipped YAML → 28 questions, version `8439d61e`; loader rejects deferred labels, duplicates, unknown labels/dimensions, non-noul types, missing criteria.)

## Phase 6: Adapters (work units 7–10)

- [x] 6.1 RED `tests/adapters/test_fake_scorer.py`: Reproducible scores (same email twice, byte-identical, no network), one probability per question in 0..1, No test-only decision path. <!-- sdd-owner: implementation --> (RED: `ModuleNotFoundError: No module named 'email_classifier.adapters'`. Final: 7 passed incl. byte-identical replay, `httpx` never imported, same `decide()` rules path.)
- [x] 6.2 GREEN `src/email_classifier/adapters/fake_scorer.py` (hash-seeded determinism, no httpx import). <!-- sdd-owner: implementation --> (7 passed; 28 probabilities per email in 0..1; provenance carries question-set version `8439d61e`.)
- [x] 6.3 RED `tests/adapters/test_inbox_dataset.py` + `tests/fixtures/inbox_small.json`: Complete email normalized, Missing optional fields, Text-extractable attachment, Image-only attachment (`not_text_extractable`), Non-synthetic item rejected (reported, not silently skipped), Ingest replayed (one record per message_id, no reclassification), Empty source (zero ingested, no error, no record). <!-- sdd-owner: implementation --> (RED: same adapters ModuleNotFoundError; fixture has 4 synthetic emails incl. extracted PDF + image-only attachment. Final: 7 passed.)
- [x] 6.4 GREEN `src/email_classifier/adapters/inbox_dataset.py` per the dataset schema in design (`message_id`, `expected`, attachment `status`). <!-- sdd-owner: implementation --> (14 adapter tests passed; runtime harness: fixture ingest → 4 ingested, replay 0, `expected_for` returns frozen ground truth; design D6 schema.)
- [x] 6.5 RED `tests/adapters/test_sqlite_repo.py` on a real `tmp_path` DB: Relabeling appends, Review does not mutate the original, Explaining why a label changed (composite `classifier_version` = `tax-mvp1+qs-v1+eng-jev-1.13+th-<hash8>`), Labels are never stored alone (raw scores complete for the whole question set), Full returned precision (no rounding on read-back), Auditing a rejected label (score + threshold + not-selected + threshold version), Latency computable from storage, Failed scoring still timestamps, Reading the current classification (3 records → latest), Repeated run idempotent. <!-- sdd-owner: implementation --> (Lane B. RED: same adapters ModuleNotFoundError, 22 errors. Final: 22 passed; idempotency keyed on email + classifier_version + raw_scores + engine_request_id.)
- [x] 6.6 GREEN `src/email_classifier/adapters/sqlite_repo.py`: DDL exactly as design (`emails`, `email_attachments`, `classifications`, `classification_labels`, `human_reviews`, `human_review_deltas`, with CHECK constraints and `message_id UNIQUE`) + append classified/failed, labels, latest-record read model, history. <!-- sdd-owner: implementation --> (Lane B. Documented deviation: additive nullable `classifications.queue_reason` column — spec requires queue entries to state their reason; DDL had no home for it.)
- [x] 6.7 RED `tests/adapters/test_sqlite_reviews.py`: Confirmation (`CONFIRMED`, leaves queue), Single-dimension correction (one delta, other dimensions recorded unchanged), Multi-dimension correction (one review, one delta per changed dimension), Adding a secondary label (`add`), Removing a sensitivity label (`remove`), Original preserved after correction (reviewer, timestamp, status retrievable), Review history retained and ordered, Listing the queue (email, dimensions, band, confidence, reason), Filtering the queue by reason (totals unchanged), Correction stored outside ground truth (expected labels untouched). <!-- sdd-owner: implementation --> (Lane B. RED: 11 failed (NotImplementedError + projection), 1 passed. Final: 12 passed.)
- [x] 6.8 GREEN `append_review`, `list_review_queue(reason=None)`, and the "current values = deltas over automated values" projection in `sqlite_repo.py`. <!-- sdd-owner: implementation --> (Lane B. Projection lives in the read model; stored automated record stays byte-identical after corrections.)
- [x] 6.9 RED `tests/adapters/test_zen_jev.py` with `httpx.MockTransport`: All questions answered in one request (exactly one POST to `https://opencode.ai/zen/v1/systemone`, model `jev-1.13`, 28 question keys), envelope mapping `answers.<question_id>.noul`, Engine vocabulary does not leak (no engine identifier stored as label), Out-of-range probability rejected (→ scoring failed, no coercion), Missing question rejected (no substituted score), Engine unavailable/timeout exhausted → `ScoringError` after max 2 retries with exponential backoff, API key read only from env `OPENCODE_API_KEY` and never logged. <!-- sdd-owner: implementation --> (Lane A. RED verbatim: `ModuleNotFoundError: No module named 'email_classifier.adapters.zen_jev'`, collection error. 26 tests incl. non-numeric/boolean/malformed-JSON rejection, 4xx-no-retry, backoff growth 0.25→0.5, env/configurable base_url+model.)
- [x] 6.10 GREEN `src/email_classifier/adapters/zen_jev.py` (30s timeout, 2 retries, fail-closed). <!-- sdd-owner: implementation --> (Lane A. `ZenJevScorer`: lazy httpx import, env key at construction w/ clear ValueError, 5xx/network retried ≤2 w/ exponential backoff, 4xx and malformed JSON fail immediately, strict `answers.<qid>.noul` validation. Focused: 26 passed; full suite 175 passed; ruff clean.)

## Phase 7: Pipeline and Replay (work units 11–12)

- [ ] 7.1 RED `tests/pipeline/test_pipeline.py`: ingest → score → rules → append over the fixture, exactly one scoring request per email, Engine replaced without policy changes (swap fake/zen, same `Decision` shape), Source replacement leaves the pipeline unchanged, No silent drop (failed email present in storage, review queue and run counts), Empty-run counts. <!-- sdd-owner: implementation -->
- [ ] 7.2 GREEN `src/email_classifier/pipeline/pipeline.py` (orchestration, `FAILED` status + review routing, run report counts). <!-- sdd-owner: implementation -->
- [ ] 7.3 RED `tests/pipeline/test_replay.py`: Replay relabels from stored scores under T2 (new rows carry T2 + unchanged raw scores + engine version), zero engine requests (spy asserts 0), Replay preserves history (T2 current, T1 retrievable, same raw scores), Relabeling appends. <!-- sdd-owner: implementation -->
- [ ] 7.4 GREEN `src/email_classifier/pipeline/replay.py`. <!-- sdd-owner: implementation -->

## Phase 8: API (work units 13–14)

- [ ] 8.1 RED `tests/api/test_listing.py` (FastAPI TestClient): Listing classified emails (complete dimension set + band, no stored email omitted), Unclassified email visible as unclassified (no invented category/sensitivity/confidence), Corrected values shown as current with originals retrievable, Unreviewed values unchanged, Explaining a stored decision (raw scores + applied thresholds + composite version, zero engine calls), Explaining a sensitive non-auto label (score, auto threshold, review floor, routing), `GET /api/health`, queue listing + reason filter. <!-- sdd-owner: implementation -->
- [ ] 8.2 GREEN `src/email_classifier/api/app.py`: `GET /api/emails`, `GET /api/emails/{email_id}`, `GET /api/review-queue?reason=`, `GET /api/health` over the repository port. <!-- sdd-owner: implementation -->
- [ ] 8.3 RED `tests/api/test_review_post.py`: `POST /api/reviews` confirm and correct (delta ops validated against the frozen label set; unknown label → 422), queue entry closed, replay-triggering route rejected for unknown threshold version, Correction stored outside ground truth. <!-- sdd-owner: implementation -->
- [ ] 8.4 GREEN `POST /api/reviews` + `POST /api/replay` (`{threshold_set_version}` → new append-only rows) in `api/app.py`. <!-- sdd-owner: implementation -->

## Phase 9: Metrics (work unit 15)

- [ ] 9.1 RED `tests/pipeline/test_metrics.py`: Metrics use expected labels, Corrections do not rewrite truth, Accuracy reported (numerator + denominator exposed), Failed emails accounted for (never dropped from denominator), Per-category metrics (per-category P/R; absent instances reported as such, not zero), Sensitive classes are not aggregated away (FRAUD_SUSPICION, LEGAL, PERSONAL_DATA, SENSITIVE_PERSONAL_DATA, HIGHLY_CONFIDENTIAL separately), False negative detected, Auto-tier gap measurable (floor..auto counts as reviewed, not silent miss), Review rate reported with raw counts, Failed emails included, Latency reported per run (per-email + aggregate + failed subset), Other rate reported (incl. share that cleared no floor), Comparability of runs (dataset/question-set/threshold-set/engine/composite versions stated), Attachment gap stated (non-text excluded + affected count). <!-- sdd-owner: implementation -->
- [ ] 9.2 GREEN `src/email_classifier/pipeline/metrics.py` + `GET /api/metrics`. <!-- sdd-owner: implementation -->

## Phase 10: Dataset and End-to-End Proof (work units 16–17)

- [ ] 10.1 Author `datasets/inbox_mvp_v1.json` (~120 synthetic emails, Argentine-Spanish bodies): ≥5 per primary category, ≥8 per sensitivity label, ≥15 boundary cases (COMPLAINT/LEGAL overlap, claim triple, lead vs quote, sensitive signals between 0.40 and 0.95), ≥4 image-only attachments, `expected` labels drawn only from `taxonomy_mvp`. <!-- sdd-owner: implementation -->
- [ ] 10.2 RED+GREEN `tests/dataset/test_corpus_coverage.py`: asserts the `dataset_version`/schema shape, coverage counts above, unique `message_id`, no deferred category, every `expected` label inside `taxonomy_mvp`. <!-- sdd-owner: implementation -->
- [ ] 10.3 RED then GREEN `tests/e2e/test_corpus_run.py`: full corpus through the pipeline with `FakeDeterministicScorer` — item count, exactly one classification per email, zero silent drops for sensitive signals, failed emails stored + queued, metrics report version-attributed. <!-- sdd-owner: implementation -->
- [ ] 10.4 Run `python -m pytest -q`, `python -m pytest --cov=email_classifier --cov-report=term-missing`, `ruff check .`, `python -m pip install -e .`; record command output as apply-phase evidence. <!-- sdd-owner: implementation -->
- [ ] 10.5 Add `README.md` with install/run/test/replay instructions and the fake-vs-live scorer switch. <!-- sdd-owner: implementation -->
- [ ] 10.6 Optional, gated: live Zen smoke test of `answers.<qid>.noul` when `OPENCODE_API_KEY` is present (skipped otherwise); record the result as a design open-question resolution. <!-- sdd-owner: implementation -->

## Phase 11: Post-Apply Gates (parent-owned)

- [ ] 11.1 Start or reuse bounded review for each work-unit PR per repository review policy, after source-mutating normalization is complete. <!-- sdd-owner: parent -->
- [ ] 11.2 Run lifecycle delivery gates (pre-commit / pre-push / pre-pr / release) and the archive gate on the exact reviewed candidate. <!-- sdd-owner: parent -->

## Coverage Map (requirement → task)

| Spec | Requirements | Tasks |
| ------ | -------------- | ------- |
| email-ingestion (5) | replaceable source, normalized intake, idempotent intake, attachment status, synthetic only | 2.1, 6.3, 6.4, 7.1, 9.1 |
| jev-scoring (8) | anti-corruption, versioned questions, one call/email, strict validation, fail-closed, fake scorer, provenance, deferred excluded | 2.1, 5.3, 5.4, 6.1, 6.9, 7.1 |
| classification-rules (9) | confidence, versioned thresholds, banding table, paired floor, sensitive fail-closed, selection, implications/precedence, disambiguation, pure determinism | 3.1, 3.2, 4.1, 4.2, 5.1, 5.4, 7.3 |
| classification-storage (8) | append-only, composite version, verbatim scores, per-label records, latency chain, replay, latest-record read, idempotency | 6.5, 6.6, 7.3 |
| human-review (6) | queue routing, confirm/correct, deltas, append-only, never rewrite truth, queue retrievable | 3.1, 6.7, 6.8, 8.3 |
| classification-dashboard (3) | listing, current values after review, decision evidence | 8.1, 8.2 |
| classification-metrics (9) | ground truth, accuracy, per-category P/R, sensitive FN rate, review rate, latency, OTHER rate, version attribution, limitations | 9.1, 9.2 |

## Strict TDD Evidence Expectations

Per work unit: commit a RED step (failing test + verbatim failure output) before the GREEN step (implementation + passing run), then a TRIANGULATE/REFACTOR step only if the unit adds edge cases or cleanup. `sdd-apply` must record, per unit: test file paths, the RED failure message, the GREEN pass output, and `ruff check .` result. Unit 1 (harness) proves the runner; every later unit is RED-first against its own test path. No unit may skip RED.
