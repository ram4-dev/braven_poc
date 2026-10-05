# Classification Storage Specification

## Purpose

Persist emails, raw engine scores, derived decisions, provenance and review history as append-only history, so every stored decision is auditable and re-derivable without contacting the engine.

**Label sets covered:** all MVP dimensions as enumerated in the `classification-rules` spec (16 primary categories, 6 sensitivity labels, 6 actions, 4 priorities).

## Requirements

### Requirement: Append-only classification history

Classification records MUST be append-only. No pipeline run, replay or review MUST update or delete an existing classification record; the current view of an email is derived from its most recent record.

#### Scenario: Relabeling appends

- GIVEN a stored classification for email X
- WHEN X is reclassified under a new configuration
- THEN a new classification record is appended
- AND the previous record is unchanged and still readable

#### Scenario: Review does not mutate the original

- GIVEN a classification corrected in human review
- WHEN storage is inspected
- THEN the automated classification record is unchanged
- AND the correction exists as separate review history

### Requirement: Composite classifier version

Every classification MUST carry a composite classifier version identifying at minimum the taxonomy version, the question-set version, the engine/model version and the threshold-set version.

#### Scenario: Explaining why a label changed

- GIVEN two classification records for the same email with different labels
- WHEN the records are compared
- THEN the differing component version is identifiable from the records alone
- AND no external lookup is required

### Requirement: Verbatim raw scores

Every classification MUST persist the raw probabilistic scores verbatim, keyed by decision-question identifier, at the precision the engine returned, together with the engine request identifier. Derived labels MUST NOT be stored without the raw scores that produced them.

#### Scenario: Labels are never stored alone

- GIVEN any stored classification
- WHEN it is read
- THEN its raw-score map is present and complete for every question in the question-set version
- AND no classification record exists with labels but no raw scores

#### Scenario: Full returned precision

- GIVEN the engine returned a score with several decimal places
- WHEN it is stored and read back
- THEN the stored value equals the returned value exactly
- AND no rounding or reformatting is applied

### Requirement: Per-label decision records

For every label considered, the system MUST store the dimension, the label, the score, the threshold applied and the resulting selection decision.

#### Scenario: Auditing a rejected label

- GIVEN a label scored below its threshold and not selected
- WHEN its decision record is read
- THEN its score, the applied threshold and the not-selected decision are visible
- AND the record shows the threshold-set version in force

### Requirement: Latency timestamp chain

Each classification MUST record the four timestamps for received, ingested, scored and classified, so processing latency and per-stage latency are computable.

#### Scenario: Latency computable from storage

- GIVEN a completed classification
- WHEN latency is computed
- THEN total processing latency and per-stage latency are derivable from stored timestamps
- AND no reconstruction from logs is needed

#### Scenario: Failed scoring still timestamps

- GIVEN an email whose scoring failed
- WHEN the failure is stored
- THEN the received and ingested timestamps are present
- AND the failure is distinguishable from a completed classification

### Requirement: Replay under new thresholds

The system MUST be able to recompute labels for stored emails from their stored raw scores under a different threshold-set version, writing new append-only records that copy the original raw scores and engine version while carrying the new threshold-set version, and issuing zero engine calls.

#### Scenario: Replay relabels from stored scores

- GIVEN emails stored with raw scores under threshold set T1
- WHEN replay runs under threshold set T2
- THEN the new records carry T2 together with the unchanged original raw scores
- AND zero engine requests are issued

#### Scenario: Replay preserves history

- GIVEN email X has records under T1 and T2
- WHEN X is read
- THEN the T2 record is current and the T1 record remains retrievable
- AND both records reference the same original raw scores

### Requirement: Latest-record read model

The system MUST expose, per email, the most recent classification record together with its raw scores, while keeping all earlier records retrievable as history.

#### Scenario: Reading the current classification

- GIVEN email X has three classification records
- WHEN X is read through the read model
- THEN the most recent record is returned
- AND all three records remain retrievable in history

### Requirement: Idempotent writes

A single email and a single scoring outcome MUST NOT produce duplicate classification records when the same pipeline run or replay is repeated.

#### Scenario: Repeated run

- GIVEN a completed pipeline run for a dataset
- WHEN the identical run is repeated
- THEN the number of email records and classification records is unchanged
- AND the run reports the duplicates as already processed
