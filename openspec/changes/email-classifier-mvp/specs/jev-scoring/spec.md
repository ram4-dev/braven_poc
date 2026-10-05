# JEV Scoring Specification

## Purpose

Obtain probabilistic content signals for one normalized email from a replaceable semantic engine (JEV), driven by a versioned set of small binary decision questions, and guarantee that engine failures never produce fabricated labels.

**Label sets covered (MVP, exact strings):**

- Primary categories (16): `NEW_LEAD`, `QUOTE_REQUEST`, `NEW_POLICY`, `POLICY_RENEWAL`, `POLICY_CHANGE`, `POLICY_CANCELLATION`, `CLAIM_NEW`, `CLAIM_UPDATE`, `CLAIM_DOCUMENTATION`, `PAYMENT_BILLING`, `COMPLAINT`, `FRAUD_SUSPICION`, `LEGAL`, `REGULATORY`, `PARTNERSHIP`, `OTHER`
- Sensitivity (6): `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `HIGHLY_CONFIDENTIAL`, `PERSONAL_DATA`, `SENSITIVE_PERSONAL_DATA`
- Actions (6): `NO_ACTION`, `REPLY_REQUIRED`, `DOCUMENT_REQUIRED`, `APPROVAL_REQUIRED`, `ESCALATE`, `URGENT`
- Priority (4): `LOW`, `NORMAL`, `HIGH`, `CRITICAL`
- Deferred, MUST NOT be emitted: `CLAIM_PAYMENT`, `CLAIM_REJECTION`, `UNDERWRITING`, `BROKER_AGENT`, `REINSURANCE`, `SUPPLIER`

## Requirements

### Requirement: Anti-corruption scoring boundary

The system MUST reach the engine only through an engine-neutral boundary that accepts normalized email context plus a versioned question set and returns one probability per question. The engine's own vocabulary MUST NOT become the internal classification vocabulary, and taxonomy, thresholds, bands and selection MUST NOT be delegated to the engine.

#### Scenario: Engine replaced without policy changes

- GIVEN a scoring request for a normalized email
- WHEN the engine behind the boundary is replaced by a different implementation
- THEN the returned scores keep the same shape and the rules engine runs unchanged
- AND no taxonomy label, threshold or band changes

#### Scenario: Engine vocabulary does not leak

- GIVEN any engine response
- WHEN its answers are mapped to internal decision questions
- THEN internal question identifiers and taxonomy labels are unaffected by engine naming
- AND no engine-specific identifier is ever stored as a taxonomy label

### Requirement: Versioned decision-question set

All decision questions MUST be versioned configuration, never literals inside decision code. The MVP set MUST contain exactly one binary (yes/no) question per primary category, per sensitivity label and per action label — 16 + 6 + 6 questions — each carrying explicit true/false criteria describing the label boundary. Any change to wording or criteria MUST increment the question-set version.

#### Scenario: One question per MVP label

- GIVEN the MVP taxonomy above
- WHEN the question set is loaded
- THEN every primary category, sensitivity label and action label has exactly one binary question
- AND the loaded question-set version is reported

#### Scenario: Question set versioned

- GIVEN a change to any question wording or criteria
- WHEN the question set is loaded
- THEN its version differs from the previous version
- AND previously stored classifications keep the question-set version they were produced under

### Requirement: One scoring call per email

All decision questions for one email MUST be submitted together in a single scoring request, and the response MUST provide exactly one probability in the range 0..1 per question.

#### Scenario: All questions answered in one request

- GIVEN one normalized email and the full MVP question set
- WHEN the email is scored
- THEN exactly one scoring request is issued for that email
- AND one probability per question is returned

### Requirement: Strict response validation

A response MUST be rejected when it omits a question, returns a non-numeric value, or returns a value outside 0..1. Rejected values MUST NOT be coerced, clipped or defaulted into labels.

#### Scenario: Out-of-range probability

- GIVEN a response containing a probability outside 0..1 for one question
- WHEN the response is validated
- THEN the response is rejected
- AND the email is recorded as scoring failed

#### Scenario: Missing question

- GIVEN a response that omits one question
- WHEN the response is validated
- THEN the response is rejected
- AND no substituted score is invented for the missing question

### Requirement: Fail closed on engine failure

When the engine is unavailable, times out, or exhausts its bounded retry budget, the system MUST record the email as not classified with a failed status, MUST NOT fabricate any label, band or confidence, and MUST route the email to human review.

#### Scenario: Engine unavailable

- GIVEN the engine is unavailable for an email
- WHEN scoring finishes
- THEN the email has no primary category, no sensitivity, no actions and no confidence value
- AND its classification status is FAILED with human review required
- AND the email appears in the review queue

#### Scenario: No silent drop

- GIVEN at least one email whose scoring failed
- WHEN the run completes
- THEN the failed email is reported in the run counts
- AND it is not omitted from storage, the review queue or the metrics inputs

### Requirement: Deterministic fake scorer

The system MUST provide a deterministic fake scorer that produces reproducible scores without any engine network access, and it MUST feed the same rules path as the real engine.

#### Scenario: Reproducible scores

- GIVEN a normalized email scored by the fake scorer
- WHEN the same email is scored again
- THEN the scores are identical
- AND no network call is made

#### Scenario: No test-only decision path

- GIVEN a fake-scorer response
- WHEN rules are applied
- THEN bands, labels and review routing come from the same rules path used for the real engine
- AND no test-exclusive decision branch exists

### Requirement: Scoring provenance persisted

For every successful scoring the system MUST persist the engine request identifier, the engine/model version, the question-set version and every returned probability verbatim, at the precision the engine returned.

#### Scenario: Verbatim scores retained

- GIVEN a successful scoring returning probabilities with several decimal places
- WHEN the classification is stored
- THEN every returned probability is stored unchanged and complete
- AND the engine request identifier, engine version and question-set version accompany it

### Requirement: Deferred labels excluded

The scoring layer MUST NOT request, accept or emit any deferred category label.

#### Scenario: Deferred label requested

- GIVEN a question set containing a question for a deferred category
- WHEN the set is loaded
- THEN loading fails with an explicit error naming the deferred label
- AND no scoring runs with that set
