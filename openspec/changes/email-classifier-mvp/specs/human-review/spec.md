# Human Review Specification

## Purpose

Route ambiguous, failed and sensitive-but-undetermined emails to a human reviewer, capture per-dimension corrections as append-only history, and feed those decisions back into the stored classification view.

**Label sets covered:** primary categories (16), sensitivity (6), actions (6) and priority (4) as enumerated in the `classification-rules` spec; band values `AUTOMATIC`, `UNCERTAIN`, `HUMAN_REVIEW`.

## Requirements

### Requirement: Review queue routing

The system MUST place an email in the human review queue and mark review as required when any of these holds: band is `UNCERTAIN`; band is `HUMAN_REVIEW`; scoring failed; a sensitive-tier label scores at or above its review floor; or no primary category cleared its floor so `OTHER` was assigned.

#### Scenario: Uncertain band queued

- GIVEN an email whose band is `UNCERTAIN`
- WHEN the classification is stored
- THEN human review is required and the email appears in the queue

#### Scenario: Failed scoring queued

- GIVEN an email whose scoring failed
- WHEN the run completes
- THEN the email appears in the queue with no fabricated labels

#### Scenario: Sensitive signal queued despite an automatic band

- GIVEN an email with band `AUTOMATIC` and `SENSITIVE_PERSONAL_DATA` at or above its review floor
- WHEN the classification is stored
- THEN the email appears in the queue
- AND the queue entry states the reason it was queued

#### Scenario: No unfounded queue entries

- GIVEN an email with band `AUTOMATIC` and no sensitive-tier signal at or above its review floor
- WHEN the classification is stored
- THEN the email is not placed in the queue

### Requirement: Confirm or correct per dimension

A reviewer MUST be able to confirm the classification as-is, or correct it per dimension: primary category, secondary categories, sensitivity, actions and priority.

#### Scenario: Confirmation

- GIVEN a queued email
- WHEN a reviewer confirms the classification
- THEN a review record with status `CONFIRMED` is stored
- AND the email leaves the queue

#### Scenario: Single-dimension correction

- GIVEN a queued email classified `CLAIM_UPDATE`
- WHEN the reviewer changes only the primary category to `CLAIM_NEW`
- THEN one delta is stored for the primary-category dimension
- AND sensitivity, actions and priority are recorded as unchanged

#### Scenario: Multi-dimension correction

- GIVEN a queued email
- WHEN the reviewer changes sensitivity, actions and priority in one action
- THEN one review record exists with one delta per changed dimension
- AND each delta keeps the original value and the corrected value

### Requirement: Deltas are dimension-scoped and complete

Each correction delta MUST identify the dimension, the original value and the corrected value, supporting add and remove for multi-label dimensions. A correction touching several dimensions MUST NOT be representable only as a single label pair.

#### Scenario: Adding a secondary label

- GIVEN a queued email with one secondary category
- WHEN the reviewer adds a second secondary category
- THEN the delta records an add operation for that dimension
- AND the existing secondary category is preserved

#### Scenario: Removing a sensitivity label

- GIVEN a queued email with two sensitivity labels
- WHEN the reviewer removes one of them
- THEN the delta records a remove operation naming the removed label
- AND the remaining sensitivity label is preserved

### Requirement: Corrections are append-only

Review outcomes MUST be stored append-only. The original automated values MUST remain retrievable after any correction, together with reviewer identity, timestamp and review status.

#### Scenario: Original preserved after correction

- GIVEN an email corrected after automatic classification
- WHEN the email is read
- THEN the corrected values are current
- AND the original automated values, the reviewer, the timestamp and the review status remain retrievable

#### Scenario: Review history retained

- GIVEN an email reviewed more than once
- WHEN its history is read
- THEN every review record is retrievable in order
- AND no earlier review record was overwritten

### Requirement: Corrections never rewrite ground truth

Reviewer corrections MUST NOT modify the evaluation dataset's expected labels, and corrections MUST NOT be silently used to overwrite ground truth used by metrics.

#### Scenario: Correction stored outside ground truth

- GIVEN an evaluation email with expected labels
- WHEN a reviewer corrects that email's classification
- THEN the expected labels are unchanged
- AND the correction is stored as review history only

### Requirement: Review queue is retrievable

The review queue MUST be retrievable as a list, and each entry MUST expose the email, its stored dimensions, its band, its confidence and the reason it was queued.

#### Scenario: Listing the queue

- GIVEN queued emails exist
- WHEN the queue is requested
- THEN each entry exposes the email identity, stored dimensions, band, confidence and queue reason

#### Scenario: Filtering the queue by reason

- GIVEN the queue holds emails queued for different reasons
- WHEN the queue is requested filtered by one reason
- THEN only entries matching that reason are returned
- AND the total queue size remains unchanged
