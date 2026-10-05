# Proposal: Email Classifier MVP (JEV-powered insurance email pipeline)

## Intent

Build the MVP classification pipeline from PROD.md §17–§18: ingest emails, ask JEV many small binary content questions, convert probabilities into labels via insurer-owned rules, persist everything append-only, and expose a review queue, simple dashboard and metrics. Goal: demonstrate that JEV-driven probabilistic classification works correctly and measurably on an insurance email corpus, with sensitive classes failing closed to human review.

## Scope

### In Scope

- Inbox adapter port: JSON-dataset-backed mailbox simulation, replaceable later with a real reader (IMAP/Graph) without pipeline changes.
- Extraction/normalization: subject, body, sender, recipients, date, thread, attachment names; text-extractable attachment content (OCR gap recorded as metric caveat).
- JEV scoring port over OpenCode Zen (`jev-1.13`, `POST https://opencode.ai/zen/v1/systemone`, one request per email with all `noul` questions, `criteria` for boundaries); deterministic fake scorer as default/test adapter, real HTTP client via env config.
- Versioned decision-question set (~28 nouls: 16 categories + 6 sensitivity + 6 actions) as config, with per-question `criteria`.
- Rules engine: pure functions over (raw_scores, threshold config); per-(dimension,label) thresholds; 0.95 auto-tier for FRAUD_SUSPICION/HIGHLY_CONFIDENTIAL/LEGAL paired with a lower review floor; bands AUTO/UNCERTAIN/HUMAN_REVIEW as a separate field, never a label; UNCERTAIN band queued for review; `confidence` = primary category's score; implication/precedence rules (SENSITIVE_PERSONAL_DATA⇒PERSONAL_DATA, NO_ACTION exclusivity, priority precedence).
- Append-only SQLite storage: emails, classifications (composite classifier_version, verbatim raw_scores, engine_request_id, four-timestamp latency chain), per-label score/threshold/decision rows, human_reviews with per-dimension deltas; replay under new thresholds without engine calls.
- Review queue + minimal dashboard/API (FastAPI): list classified emails, queue, confirm/correct per dimension.
- Metrics endpoint fed by the synthetic dataset's expected labels: accuracy, precision/recall per category, sensitive-class false-negative rate, human review rate, latency; OTHER-rate metric.
- Synthetic dataset only (no real personal data) with expected labels as ground truth; taxonomy disambiguation rules (COMPLAINT/LEGAL, CLAIM_NEW/UPDATE/DOCUMENTATION, lead/quote) encoded in `criteria` + rules precedence.
- Test harness lands first (runner selected in design; `config.yaml` `test_command` updated before feature code).

### Out of Scope

- All §19 features: smart routing, search, alerts, analytics, workflow automation.
- Deferred categories: CLAIM_PAYMENT, CLAIM_REJECTION, UNDERWRITING, BROKER_AGENT, REINSURANCE, SUPPLIER.
- Real mailbox integration, OCR/vision, threshold tuning tooling, multi-user auth, deployment/infra.

## Capabilities

### New Capabilities

- `email-ingestion`: inbox adapter port + JSON dataset adapter + idempotent normalized-email intake.
- `jev-scoring`: anti-corruption scoring port, question-set config, Zen HTTP adapter, fake scorer, failure handling (fail-closed, no fabricated labels).
- `classification-rules`: versioned threshold config, banding, per-(dimension,label) overrides with paired review floors, implications, primary/secondary selection.
- `classification-storage`: append-only schema, composite classifier_version, verbatim raw scores, replay path.
- `human-review`: review queue, per-dimension corrections, review API.
- `classification-dashboard`: minimal read model/API for classified emails.
- `classification-metrics`: accuracy/precision/recall/FN-rate/review-rate/latency against dataset ground truth.

### Modified Capabilities

- None (greenfield; `openspec/specs/` is empty).

## Approach

Ports-and-adapters with a pure rules core: `EmailSource`, `ScoringEngine`, `ClassificationRepository`, `AttachmentExtractor` ports; decision logic as pure functions over (raw_scores, threshold_config). Stack: Python (FastAPI + SQLite) — user-confirmed; test runner and concrete commands are named in design, never asserted here. Engine capability and product policy stay separate per PROD.md §20.

## Affected Areas

| Area | Impact | Description |
| ------ | -------- | ------------- |
| `openspec/changes/email-classifier-mvp/` | New | SDD artifacts for this change |
| `openspec/config.yaml` | Modified | `test_command`/runner_status updated by design once decided |
| New Python package (paths fixed in design) | New | Pipeline, ports, adapters, API, storage |

## Risks

| Risk | Likelihood | Mitigation |
| ------ | ------------ | ------------ |
| Zen response envelope details differ from research (field names, errors) | Med | Design verifies against TypeSafe docs/SDK; port isolates mapping; fake scorer unblocks tests |
| 0.95 auto-tier drops sensitive signals without paired review floor | High impact | Paired lower review threshold is an explicit requirement; verify FN rate for sensitive classes |
| Question authoring quality drives everything | Med | Budgeted as real work; versioned; `criteria` encode disambiguation |
| Dataset ground truth biased by synthetic authoring | Med | Authoring guidelines + disambiguation rules; metrics interpreted as PoC-scope evidence |
| SQLite/FastAPI scale limits | Low | Acceptable for PoC; storage design keeps swap-out trivial |

## Rollback Plan

Greenfield change: revert the branch/commits; no pre-existing data or stored classifications are mutated. Append-only storage means no destructive migration to undo. `config.yaml` runner fields revert with the same revert.

## Dependencies

- `OPENCODE_API_KEY` via environment (never committed) for the real JEV adapter.
- Synthetic email dataset (authored in this change, ~100+ emails covering all 16 categories, 6 sensitivities, expected labels).
- Design phase must select test runner and commands before apply.

## Success Criteria

- [ ] Pipeline runs end-to-end on the synthetic dataset: adapter → normalize → JEV (real or fake) → rules → SQLite → dashboard/API.
- [ ] Every stored classification carries raw scores, composite classifier_version, and per-label threshold records.
- [ ] Sensitive classes auto-label only at ≥0.95 and are queued below the paired review floor; zero silent drops.
- [ ] Thresholds are config-only; relabeling stored emails via replay works without engine calls.
- [ ] Metrics endpoint reports accuracy, per-category precision/recall, sensitive FN rate, review rate, latency against dataset ground truth.
- [ ] Swapping JSON adapter for a mailbox reader (or fake scorer for real client) requires no pipeline changes.
