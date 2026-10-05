# Exploration: Intelligent Email Classifier for an Insurance Company (greenfield MVP)

> Change slug `email-classifier-mvp` was assumed by the explore phase because the
> orchestrator supplied no change name and `openspec/changes/` was empty. If the
> proposal uses a different change name, move this file to
> `openspec/changes/{change-name}/exploration.md`.
>
> Source of truth: `PROD.md` (Spanish product spec). Section references (§n) below
> point at `PROD.md`. Label strings are copied verbatim from
> `openspec/config.yaml` `taxonomy_mvp` and MUST NOT be renamed.

## Current State

**Repository is greenfield: no executable code exists.**

```
braven_poc/
├── PROD.md                  <- product spec, Spanish, 20 sections
├── AGENTS.md                <- mandates HumanLayer design gate, then SDD
├── openspec/config.yaml     <- sdd-init output: dimensions, taxonomy, rules
├── openspec/changes/        <- empty (this is the first change)
└── .agents/skills/          <- installed SDD + shared skills
```

Consequences for this phase:

- There is no codebase to map, so this exploration is **product, domain and
  architecture** exploration. No call graph, no existing patterns to follow.
- CodeGraph was intentionally not initialized: the repository contains zero
  source files, so an index would be empty and would add no signal. It becomes
  worth initializing in the first change that lands source code.
- No test runner, no manifests, no CI. `openspec/config.yaml` records
  `strict_tdd: true` with `runner_status: unresolved` and empty `test_command`.
  Per the config note, no phase may invent a test command while it is empty.
- The stack is **undecided by design**; `config.yaml` says it is fixed in the
  first change's design phase. Any stack assertion in this artifact is a
  candidate, not a decision.

The product itself (from `PROD.md`) is: ingest inbound insurance emails →
normalize → ask JEV many small binary content questions → receive one probability
per question → apply insurer-owned rules and thresholds → persist emails plus
classification output plus raw scores plus versions → expose a simple dashboard
and a human review queue.

---

## Affected Areas

No code exists, so these are the areas the first change will **create or
constrain**. The existing files are constraints, not code to modify.

### Existing constraints (read-only inputs)

- `PROD.md` — the entire product contract; §9/§11 define the JEV usage model and
  the confidence bands, §12–§15 define persistence, §17–§19 define MVP scope and
  deferrals.
- `openspec/config.yaml` — binds the label set, the stored dimensions, the 0.95
  sensitive-category override list, and phase rules (thresholds must be versioned
  configuration, raw scores must be persisted with `classifier_version`, the test
  harness must land before feature code).
- `AGENTS.md` — the design gate must be approved before implementation; SDD is the
  implementation route afterwards.

### Areas the first change must establish (proposed shape, not a design)

| Area | Responsibility | Why it is affected |
| --- | --- | --- |
| Ingest + source port | Read historical emails (or a mailbox later) as a normalized `EmailMessage` | §17 leaves the MVP input open; the choice drives auth, sync state and failure modes |
| Extraction/normalization | subject, body, sender, recipients, date, thread, attachment names, attachment text, metadata (§3) | Attachment text is what makes `CLAIM_DOCUMENTATION` measurable; OCR/vision is a scope fork |
| Scoring port (anti-corruption layer) | Engine-neutral `ScoringRequest` / `ScoringResponse`; the only place that knows JEV's transport and vocabulary | §20 demands the engine/policy split; a leaked engine vocabulary makes the classifier unreplaceable |
| Decision-question set (versioned config) | Authoritative list of binary questions + ids + aggregation to labels | §9 makes the question set the real classification taxonomy; config rules forbid scattered literals |
| Rules engine (pure domain core) | Score → label decisions: per-(dimension,label) thresholds, banding, primary/secondary selection, action and priority derivation, conflict resolution | §20: policy belongs to the insurer, not the engine |
| Threshold/band configuration (versioned) | 0.90 / 0.65 bands plus per-(dimension,label) overrides (0.95 tier), `threshold_set_version` | §11; config rules require an explicit threshold table and versioning |
| Persistence | `emails`, `email_attachments`, `classifications`, `classification_labels`, `human_reviews` (+ per-dimension review deltas) | §12–§15; append-only history is what makes version comparison possible |
| Replay/derivation path | Recompute labels from stored raw scores under a new threshold set, without an engine call | §14: "change thresholds without reclassifying every email" |
| Review queue + review API | Route band-flagged and sensitive-undetermined emails to a reviewer; store corrections as deltas | §16; corrections are the only ground-truth source the PoC will have |
| Metrics/evaluation harness | accuracy, precision/recall per category, review rate, false-negative rate on sensitive classes, latency (§18) | Without an eval harness the 0.65/0.90 placeholders can never be tuned with real emails (§11) |
| Dashboard/read model | Simple list/search over classified emails (MVP) | §17 keeps this deliberately small; §19 search/analytics are deferred |
| Pipeline observability | Timestamps `received_at` → `ingested_at` → `scored_at` → `classified_at`, engine latency, failure counters | §18 requires processing latency as a first-class metric |

---

## Design Tension 1 — The JEV integration boundary

### What the spec fixes

- JEV receives **many small binary questions** ("Does this email report a new
  insurance claim? YES/NO") and returns **one probability per question** (§9, §20).
- JEV is never asked "what is this?" against a giant category list (§9).
- Example response: `{"new_claim": 0.96, "claim_documentation": 0.81,
  "personal_data": 0.97, "fraud_suspicion": 0.08}` — one object per email, many
  question results.
- §8 adds a conflict: JEV *may alternatively* return a numeric 1–5 scale that
  internal rules convert.

### What the system must obtain from JEV

| Requirement | Proposed shape | Notes / open issue |
| --- | --- | --- |
| Transport contract | Unknown. Port must be defined before the adapter is written | Highest-unknown in the whole product; the adapter is the only component that may depend on it |
| Request payload | Normalized email context (§3): subject, body, sender, recipients, date, thread, attachment names, extracted attachment text, metadata | Attachment text availability gates sensitive-class recall |
| Response payload | `map<question_id, probability in [0,1]>` + engine/model version identifier + request id | Non-numeric, out-of-range or missing entries must be rejected explicitly, never coerced |
| Question set | Versioned configuration owned by the system, mapped to engine-side question identifiers | The engine's own wording/ids must not be the internal vocabulary |
| Batch behavior | One call per email carrying all questions (as §9's example implies); cross-email batching unstated | Latency/rate limits matter for historical ingest; concurrency, retry budget and idempotency keys are design decisions |
| Failure handling | Timeout, bounded retry, partial-response handling, unavailable → `status = FAILED`, never a fabricated label; failed emails enter the review queue | Fail-closed is the only defensible default for a compliance-adjacent product |
| Determinism | Fix seed/temperature if the engine allows; store verbatim scores + request id + version | If scores drift run-to-run, audit claims and metric comparability degrade silently |
| Language | Emails are Argentine Spanish; §9 examples are in English | Question language must be an explicit decision, not an accident |

### What the system must own (never delegated to JEV)

Labels and taxonomy; thresholds, bands and the 0.95 override tier; primary vs
secondary selection; priority mapping from any numeric scale; action derivation
and contradiction pruning; `requires_human_review`; conflict resolution;
implication rules between labels; storage, versioning, audit and the review loop.

### Approaches

1. **Contract-first port + fake adapter** — define engine-neutral DTOs, a
   versioned question set and a deterministic fake scorer; defer the real JEV
   adapter until its interface is known.
   - Pros: unblocks every downstream phase; fully testable under Strict TDD; the
     anti-corruption boundary is enforced by types; engine swap stops being a
     rewrite; no rework of the rules engine when the real contract lands.
   - Cons: the eventual mapping layer may still need adjustment; requires
     discipline to keep internal ids engine-neutral.
   - Effort: Low–Medium.

2. **Wait for the real JEV contract, integrate directly** — no speculative port.
   - Pros: no speculative code; no mapping mismatch.
   - Cons: blocks the entire SDD chain on a third party; the rest of the pipeline
     cannot be built, tested or demoed; Strict TDD becomes impossible.
   - Effort: High (schedule risk, not code effort).

3. **Adopt JEV's native question/label vocabulary as the internal model** —
   thin pass-through.
   - Pros: fastest path to a first integration; least code.
   - Cons: directly violates §20 — business policy leaks into the engine
     namespace; thresholds and taxonomy become coupled to the engine; the promise
     "change policy without replacing the classifier" is lost.
   - Effort: Low now, High later.

**Recommendation: approach 1**, with an explicit "JEV contract discovery" item in
the first change: ask the product owner for JEV's transport, request/response
shape, batching, rate limits, determinism guarantees and pricing model, and record
the outcome as an ADR. The fake adapter is a testing seam, not a permanent
substitute.

---

## Design Tension 2 — Rules engine and thresholds

### The core modelling gap: one `confidence`, many probabilities

§11 bands are expressed in terms of a single `confidence` value, but §9/§14 give
one probability per question. The spec's own §13 example is the clue:
`confidence: 0.96` is exactly the `claim_new` score, i.e. the winning primary
category's score. That reading must be made explicit and versioned, because
`confidence` drives the whole automation decision.

Candidate definitions (design must pick one and document it):

- **(a) primary-category score** — matches §13's example; simple; blind to a
  high-scoring sensitive label that is not the primary category.
- **(b) minimum over all selected labels** — conservative; drags almost every
  multi-label email into review.
- **(c) mean/max over selected labels** — arbitrary aggregation, no audit story.
- **(d) per-dimension confidence** (`primary_confidence`, `sensitivity_confidence`,
  `actions_confidence`, `priority_confidence`) plus an overall roll-up.

Recommendation: keep a single stored `confidence` **defined as the primary
category's score** (per §13), and store per-label scores in
`classification_labels` so every dimension can be banded independently. That
keeps the documented field meaningful without losing information.

### Threshold table must be keyed by (dimension, label), not by label

§11 lists `FRAUD_SUSPICION` (a business category), `HIGHLY_CONFIDENTIAL` (a
sensitivity label) and `LEGAL` (a business category) in one override list. The
threshold configuration therefore needs `(dimension, label) -> threshold` keys,
with the default band (0.90 / 0.65) as the fallback.

### The 0.95 override needs a second, lower threshold (fail-closed stance)

Raising the auto-classification threshold for a sensitive label reduces false
positives but, if nothing else changes, a fraud signal scoring 0.80 is silently
binned as clean — exactly the false negative §18 calls "especially critical".
The 0.95 tier should therefore be paired with a **review threshold** below the
default: high bar to auto-label, low bar to pull a human in. Without this, the
override list is a recall regression disguised as caution.

### Multi-label semantics and cross-dimension coupling

- Sensitivity is cumulative: `PUBLIC`/`INTERNAL`/`CONFIDENTIAL`/`HIGHLY_CONFIDENTIAL`
  and `PERSONAL_DATA`/`SENSITIVE_PERSONAL_DATA` may coexist (§5).
- The spec never states the relationships. Implication rules belong in the rules
  engine as versioned configuration (candidates: `SENSITIVE_PERSONAL_DATA` ⇒
  `PERSONAL_DATA`; fraud/legal/security-incident signals ⇒ `HIGHLY_CONFIDENTIAL`).
  The earlier example where `fraud_suspicion` should drive `HIGHLY_CONFIDENTIAL`
  is exactly such a rule.
- Actions may coexist (§7), but `NO_ACTION` is mutually exclusive with the other
  five; a pruning rule must exist or the stored output contradicts itself.
- Priority is single-valued (§8): derivation needs an explicit precedence
  (CRITICAL > HIGH > NORMAL > LOW) over the signals that raise it.
- Multi-question labels need an aggregation rule (max vs OR vs weighted) — same
  class of versioned configuration.

### Primary/secondary and the `OTHER` escape hatch

- `primary_category` = highest-scoring category above its floor; the rest that
  clear their floors become `secondary_categories[]` (§10).
- Unresolved: does `primary_category` become `OTHER`, or `null` plus review, when
  nothing clears the floor? Recommendation: `OTHER` + `requires_human_review = true`,
  and a dedicated `OTHER` rate metric, because a silent `OTHER` can mask
  systematic engine failure while polluting accuracy.
- Deterministic tie-break is required (equal probabilities must not produce
  different labels on replay).

### Band naming must not pollute the label sets

§11 says the middle band is "clasificación + UNCERTAIN". If `UNCERTAIN` is stored
as a taxonomy label it contaminates `sensitivity`/`actions` and breaks the
label-set contract. Recommendation: a separate `classification_band` field with
values `AUTO` / `UNCERTAIN` / `HUMAN_REVIEW`, keeping the PROD.md band names as the
documented vocabulary and `UNCERTAIN` as a band, not a label.

### Band → review routing needs an explicit rule

`openspec/config.yaml` says `requires_human_review` is derived from confidence
bands, but §11 leaves it ambiguous whether the UNCERTAIN band is auto-accepted
with a flag or queued for review. Recommendation: band `AUTO` ⇒ no review; band
`UNCERTAIN` ⇒ flagged and queued; band `HUMAN_REVIEW` ⇒ queued; plus a
fail-closed override: any sensitive label above its review threshold forces
review regardless of band. This is a genuine product decision with large
operational impact on the human review rate, and it should be settled in the
proposal rather than assumed in design.

### Are the band numbers meaningful in a PoC?

0.65/0.90 are placeholders (§11 explicitly says they will be adjusted with real
emails). With no calibration set and no reviewer history, they are a starting
policy, not a measurement. Two consequences: the evaluation harness must exist
before tuning can be honest, and threshold edits must be configuration changes
with a version, never code edits.

### Approaches for thresholds

1. **Versioned declarative threshold file, pure-function evaluator** — a YAML/JSON
   document holding band defaults, `(dimension,label)` overrides, aggregation
   rules, implications and precedence, loaded and validated at startup and
   hashed into `threshold_set_version`.
   - Pros: changeable without reclassification; auditable ("which policy produced
     this label set?"); trivially unit-testable as pure functions; satisfies the
     config rule that thresholds are never hardcoded.
   - Cons: needs a validation layer to prevent nonsense configs (unknown labels,
     inverted bands); config drift between environments.
   - Effort: Low–Medium.

2. **Thresholds in code constants per rules module** — fastest to write.
   - Pros: no config plumbing.
   - Cons: every policy change is a deploy; replay audit becomes archaeology;
     directly violates the `apply` guideline in `openspec/config.yaml`.
   - Effort: Low now, High later. **Reject.**

3. **Per-email threshold rules in the database, editable at runtime** — a policy
   table with a UI.
   - Pros: maximum operational flexibility; no deploy for tuning.
   - Cons: unbounded surface; versioning and testing get much harder; far beyond
     MVP.
   - Effort: Medium–High. Defer past MVP.

**Recommendation: approach 1**, with the config document validated against the
frozen label set at load time and its hash persisted on every classification row.

---

## Design Tension 3 — Storage, auditability and versioning

### The primary structural gap: §12–§13 read as mutable current state

§13 shows a single result object per email. If `classification_results` is one
mutable row per email, then §14 (keep raw scores) and §15 (compare versions) lose
their point: historical decisions are overwritten. The read model needs "latest
per email", but the write model must be **append-only**.

### Proposed write model (sketch, for design to refine)

```
emails(email_id, message_id UNIQUE, thread_id, sender, recipients, subject, body,
       received_at, ingested_at, source, raw_ref)
email_attachments(attachment_id, email_id, filename, mime, extracted_text_ref,
                  extraction_status)
classifications(classification_id, email_id, engine_version, question_set_version,
                taxonomy_version, threshold_set_version, classifier_version,
                raw_scores, confidence, classification_band,
                requires_human_review, primary_category, priority,
                status, engine_request_id, latency_ms, classified_at)
classification_labels(label_id, classification_id, dimension, label,
                      score, threshold_applied, selected)
human_reviews(review_id, email_id, classification_id, review_status,
              reviewer_id, reviewed_at, notes)
human_review_deltas(delta_id, review_id, dimension, operation,
                    original_label, corrected_label)
```

- `classifier_version` must be **composite** (`taxonomy` + `question_set` +
  `engine/model` + `threshold_set`), because §15 lists definitions, questions,
  thresholds, model and rules as independent change triggers. A bare
  `insurance-email-v1` string cannot express that, and the answer to "why did this
  email change label?" must be answerable from the row alone.
- `raw_scores` is stored verbatim, keyed by question id, at full returned
  precision, together with `engine_request_id`.
- Storing derived labels (in `classification_labels`) is a **materialized decision
  record** with the applied threshold recorded, so audit can answer "was this
  label chosen because of the score or because of the policy in force?".
- Replay under a new threshold set inserts new classification rows that **copy
  `raw_scores` and `engine_version`** but carry the new `threshold_set_version`,
  linked to the source row. No engine call happens; no historical row mutates.
  This is what makes §14's promise testable.
- Idempotency: `message_id` uniqueness plus an ingest run id, so re-running ingest
  cannot duplicate or silently re-classify.
- Latency metric needs the four-timestamp chain, which is why the timestamps are
  in the schema rather than derived later.

### Sensitive-data handling is a product-level tension, not a detail

The PoC's whole purpose is to detect emails containing health data, identity
numbers and financial data — and then store those emails in full. Retention,
at-rest protection, access control and whether the PoC should run on
synthetic/anonymized samples instead of real inbox data are decisions the proposal
must make explicitly. Treating this as "later hardening" is a legal risk, not a
technical debt.

### Attachment handling

§3 lists attachment names and extracted attachment text; §6/§17 examples feature
photographs and scanned police reports. Text extraction from PDFs is one scope
step; OCR of images is another. If images are excluded, `CLAIM_DOCUMENTATION`
recall will be understated in the PoC metrics and that must be stated as a known
limitation rather than discovered as a surprise. Recommendation: implement
extraction behind its own port, cover text-extractable attachments in the first
slice, and record the OCR gap as an explicit metric caveat.

---

## Design Tension 4 — Human review loop and MVP scope

### Review loop gaps in §16

- Reviewer actions listed: confirm, change primary category, add/remove secondary
  labels, change sensitivity, modify priority. Missing: changing `actions`, free
  text notes, "cannot determine / defer", and marking an email as out of domain.
  A single `original_label`/`corrected_label` pair (as in §16's example) cannot
  express a correction that touches several dimensions, so the stored shape needs
  per-dimension deltas.
- Corrections are declared to become an evaluation dataset (§16), which makes them
  the PoC's only ground truth. Risk: tuning thresholds on the same corrections
  used for evaluation is a closed loop that flatters the system. The proposal
  should define a frozen, hand-labeled evaluation slice that reviewers' ongoing
  corrections do not silently overwrite.
- §18 asks for precision/recall per category and false-negative rate, but never
  says where truth comes from. That source must be named in the proposal, or the
  metrics are unfalsifiable.

### MVP in scope (from §17–§18 plus `config.yaml`)

6 sensitivity labels; 16 primary categories; 6 actions; 4 priorities; ingest from
historical emails or a mailbox; JEV scoring; rules and thresholds; storage; a
simple dashboard; a human review queue with stored corrections; the five MVP
metrics; the stored dimension set from `openspec/config.yaml`.

### Explicitly deferred (§19, and the `deferred_categories` list)

Smart routing, search, alerts, analytics and workflow automation — all §19. Plus
categories `CLAIM_PAYMENT`, `CLAIM_REJECTION`, `UNDERWRITING`, `BROKER_AGENT`,
`REINSURANCE`, `SUPPLIER`, which `openspec/config.yaml` marks out of scope. These
must appear as non-goals in the proposal so the deferred labels are not quietly
smuggled in through question authoring.

### Taxonomy disambiguation is missing and it blocks metrics

The spec defines each category with prose, but several boundaries overlap:
`CLAIM_NEW` vs `CLAIM_UPDATE` vs `CLAIM_DOCUMENTATION`; `COMPLAINT` vs `LEGAL`
(a carta documento is both); `FRAUD_SUSPICION` vs a claim under investigation;
`REGULATORY` vs `LEGAL`; `NEW_LEAD` vs `QUOTE_REQUEST`. Without written
disambiguation rules, per-category precision/recall is not measurable because two
reviewers will not agree on truth. Disambiguation belongs to the domain layer
(question wording constraints plus rules-engine precedence), and authoring it is
real work the proposal must budget for.

---

## Design Tension 5 — Question set authorship

The decision-question set is the real classification schema. A plausible MVP set
is ~25–30 questions: roughly 15 category-indicator questions (one per MVP
category, `OTHER` being the no-question fallback), ~6 sensitivity questions
(PII, sensitive personal data, confidential business info, highly confidential
business info, public/marketing content, internal operational content), and ~5–7
action/urgency intent questions (reply expected, documents expected or missing,
approval needed, time-critical, urgency signal). Priority is best derived by rules
from category and sensitivity rather than asked directly, because "CRITICAL" is
insurer policy, not content.

Three tensions in that set:

- **Action derivation**: ask JEV directly ("does this email expect a reply?") or
  derive actions purely from category and sensitivity? Direct questions capture
  implicit requests that category rules miss; pure derivation is deterministic and
  costs no engine calls. A hybrid (small intent question set + rule derivation for
  the rest) is the likely answer.
- **Language**: emails are Spanish; §9's example questions are English. The
  choice affects engine quality and evaluability.
- **Ownership**: someone must own and version question wording. Changing a
  question invalidates comparability with prior versions but, per §14, does not
  force reclassification of already-stored emails.

---

## Approaches — overall shape of the first slice

1. **Ports-and-adapters core with a pure rules domain** — ports for
   `EmailSource`, `ScoringEngine`, `ClassificationRepository`, `ReviewQueue`,
   `AttachmentExtractor`; the decision logic is pure functions over
   `(raw_scores, threshold_config)`.
   - Pros: the rules engine and threshold behaviour become unit-testable without
     any I/O, which is what Strict TDD with an unresolved runner needs; JEV stays
     swappable; replay and evaluation reuse the same pure core; language/stack
     choice stays open.
   - Cons: slightly more structure up front for a PoC; ports must not become
     speculative abstraction.
   - Effort: Medium.

2. **Single pipeline script with inline rules** — read emails, call JEV, apply
   thresholds in one module, write to DB.
   - Pros: fastest demo; least ceremony.
   - Cons: the rules engine — the actual product value and the part most likely to
     change — ends up entangled with I/O and untestable in isolation; replay and
     metrics require re-running the engine.
   - Effort: Low now, High at the second change.

3. **Engine-first: lean on JEV for decisions too** — let JEV's output drive labels
   directly.
   - Pros: least code in the PoC.
   - Cons: contradicts §20 outright and forfeits the insurer-owned policy story
     that is the product's stated architectural principle.
   - Effort: Low. **Reject.**

**Recommendation: approach 1**, scoped tightly — only the ports that the first
slice actually exercises, with the pure rules core as the centre of gravity and
the fake scorer as the default adapter until JEV's contract is known.

---

## Recommendation

Proceed to proposal with these positions:

1. **JEV boundary**: contract-first anti-corruption port plus a deterministic fake
   adapter; a named discovery item to obtain JEV's real transport and semantics
   before the design gate closes. The system owns taxonomy, thresholds, bands,
   selection, priorities, implications, review routing, storage and audit.
2. **Rules engine**: a pure, versioned, declarative policy over
   `(raw_scores, config)`; threshold keys are `(dimension, label)`; the 0.95 tier
   gets a paired lower review threshold so sensitive classes fail closed; band is
   a separate field (`AUTO`/`UNCERTAIN`/`HUMAN_REVIEW`), never a taxonomy label;
   `confidence` is defined as the primary category's score, matching §13.
3. **Storage**: append-only classifications with a composite
   `classifier_version`, verbatim `raw_scores`, per-label score/threshold/decision
   rows, four-timestamp latency chain, idempotent ingest; replay copies scores and
   writes new rows under a new threshold-set version.
4. **Review loop**: per-dimension correction deltas, an explicitly named ground
   truth for metrics, and a frozen evaluation slice that reviewer corrections do
   not silently rewrite.
5. **Scope**: MVP as listed in §17–§18; everything in §19 plus the six deferred
   categories is a named non-goal; attachment handling limited to
   text-extractable attachments in the first slice, with the OCR gap recorded as a
   metric caveat.

Constraints the proposal and design must respect from `openspec/config.yaml`:
label strings are frozen, the test harness must land before feature code in any
change that touches classification, thresholds are never hardcoded, raw scores and
`classifier_version` are always persisted, no stack may be asserted before design
decides it, and no test command may be invented while `test_command` is empty.

---

## Risks

| # | Risk | Impact | Where it must be resolved |
| --- | --- | --- | --- |
| 1 | JEV transport/contract unknown (is it an API, a library, a batch job, an annotation tool? determinism? rate limits?) | Blocks design; adapter rework if guessed | Proposal scope + design ADR, with a discovery spike |
| 2 | Single `confidence` semantics vs per-question probabilities unresolved in the spec | Automation routing is ill-defined; replay comparisons ambiguous | Design decision, versioned |
| 3 | 0.95 override without a lower review threshold silently drops fraud/legal signals | **High** — false negatives on exactly the classes §18 calls critical | Proposal/design; verify false negatives explicitly |
| 4 | Band → review routing ambiguity (`UNCERTAIN` auto-accepted vs queued) | Human review rate swings by an order of magnitude | Product decision in the proposal |
| 5 | No ground truth for §18 metrics; corrections are the only truth source and risk a closed tuning/eval loop | Metrics unfalsifiable | Proposal must name the eval source and freeze a slice |
| 6 | Taxonomy boundaries overlap (COMPLAINT/LEGAL, CLAIM_NEW/UPDATE/DOCUMENTATION, lead/quote) | Per-category precision/recall unmeasurable; engine questions ill-posed | Domain disambiguation rules, budgeted as real work |
| 7 | Storing full emails with health and identity data in a PoC | **High** — legal/privacy exposure | Proposal must decide retention, at-rest protection and whether synthetic/anonymized samples are used |
| 8 | Engine non-determinism | Audit trail and metric comparability decay silently | Design: store verbatim scores + request id + engine version; fix seed/temperature if possible |
| 9 | Question set authorship (≈25–30 questions, Spanish/English wording, versioning) is unscoped work | Classification quality collapses if under-resourced | Proposal must budget it explicitly |
| 10 | Stack and test runner undecided while Strict TDD is on | Cannot start apply; harness-first rule blocks feature code | Design must name runner plus concrete commands before apply |
| 11 | Attachment OCR/vision excluded while CLAIM_DOCUMENTATION is a headline category | Understated recall presented as a quality result | Proposal: explicit limitation or in-scope extraction |
| 12 | Historical-ingest vs mailbox ambiguity hides auth/sync/incremental complexity | Scope creep mid-change | Proposal/design: ports for the source, mailbox adapter deferred |
| 13 | Mutable classification rows would erase §15 version comparison | Rework of persistence and audit | Design: append-only write model |
| 14 | `OTHER` used as a silent fallback masks systematic engine failure | Metric pollution; false confidence | Rules decision plus an `OTHER`-rate metric |
| 15 | Cross-dimension coupling rules (sensitivity implications, HIGHLY_CONFIDENTIAL from fraud/legal signals, NO_ACTION exclusivity) unspecified | Contradictory stored output | Versioned implication/precedence config |

---

## Ready for Proposal

**Yes.** The product spec is detailed enough to scope a first slice, and the
exploration produced concrete positions for the five focus areas plus a
constraint set that keeps engine capability and product policy separate.

The orchestrator should tell the user:

- The change is scoped as the MVP classification pipeline only: ingest →
  normalize → scoring port → rules/thresholds → storage → simple dashboard →
  human review queue, with §19 features and the six deferred categories as
  explicit non-goals.
- Two questions genuinely need a human answer before the design gate closes:
  **what is JEV's actual interface and how deterministic is it**, and **what data
  may the PoC process** (real inbox emails vs anonymized samples), because the
  product stores the exact sensitive content it detects.
- One product decision should be settled in the proposal rather than assumed in
  design: whether the `UNCERTAIN` band is auto-accepted with a flag or queued for
  human review, and whether sensitive classes get a paired lower review threshold.
- This exploration lives at `openspec/changes/email-classifier-mvp/exploration.md`;
  if the proposal picks a different change slug, the file should be moved.
