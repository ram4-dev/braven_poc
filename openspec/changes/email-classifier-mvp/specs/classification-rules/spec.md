# Classification Rules Specification

## Purpose

Convert probabilistic content signals into insurer-owned decisions — thresholds, confidence bands, label selection, implications, precedence and review routing — deterministically and exclusively from versioned configuration.

**Label sets covered (MVP, exact strings):**

- Primary categories (16): `NEW_LEAD`, `QUOTE_REQUEST`, `NEW_POLICY`, `POLICY_RENEWAL`, `POLICY_CHANGE`, `POLICY_CANCELLATION`, `CLAIM_NEW`, `CLAIM_UPDATE`, `CLAIM_DOCUMENTATION`, `PAYMENT_BILLING`, `COMPLAINT`, `FRAUD_SUSPICION`, `LEGAL`, `REGULATORY`, `PARTNERSHIP`, `OTHER`
- Sensitivity (6): `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `HIGHLY_CONFIDENTIAL`, `PERSONAL_DATA`, `SENSITIVE_PERSONAL_DATA`
- Actions (6): `NO_ACTION`, `REPLY_REQUIRED`, `DOCUMENT_REQUIRED`, `APPROVAL_REQUIRED`, `ESCALATE`, `URGENT`
- Priority (4): `LOW`, `NORMAL`, `HIGH`, `CRITICAL`

## Requirements

### Requirement: Confidence definition

Stored `confidence` MUST be the primary category's decision-question score.

#### Scenario: Confidence equals the primary score

- GIVEN raw scores where `CLAIM_NEW` scores 0.96 and `CLAIM_DOCUMENTATION` scores 0.81
- WHEN `CLAIM_NEW` is selected as primary category
- THEN stored confidence is 0.96

#### Scenario: Per-label scores remain available

- GIVEN the same email
- WHEN bands are evaluated per dimension
- THEN each label's own score is still available for banding
- AND no aggregate value replaces the per-label scores

### Requirement: Versioned threshold configuration

All thresholds and band values MUST live in versioned configuration that is validated against the frozen label set at load time. Decision paths MUST NOT hardcode thresholds. A configuration that names an unknown label, or sets a label's review floor at or above its auto threshold, MUST be rejected at load.

#### Scenario: Invalid configuration rejected

- GIVEN a configuration whose review floor for a label is not below that label's auto threshold
- WHEN the configuration is loaded
- THEN loading fails with an explicit error
- AND no classification runs under that configuration

#### Scenario: Configuration version recorded

- GIVEN a configuration that classifies emails
- WHEN decisions are stored
- THEN the threshold-set version that produced them is recorded
- AND two configurations differing in any threshold yield different versions

### Requirement: Banding with explicit threshold table

The system MUST store a classification band with exactly the values `AUTOMATIC`, `UNCERTAIN` and `HUMAN_REVIEW` (PROD.md §11 vocabulary: automatic classification / UNCERTAIN / HUMAN_REVIEW). The band MUST be a separate field and MUST NEVER be stored as a taxonomy label. The MVP threshold table (all values are configuration, not code):

| Dimension | Label | Auto threshold | Review floor | Banding outcome |
| --- | --- | --- | --- | --- |
| all dimensions | (default) | 0.90 | 0.65 | ≥0.90 `AUTOMATIC`; ≥0.65 and <0.90 `UNCERTAIN`; <0.65 `HUMAN_REVIEW` |
| primary_category | `FRAUD_SUSPICION` | 0.95 | 0.40 | ≥0.95 `AUTOMATIC`; ≥0.40 and <0.95 `UNCERTAIN`; <0.40 `HUMAN_REVIEW` |
| primary_category | `LEGAL` | 0.95 | 0.40 | ≥0.95 `AUTOMATIC`; ≥0.40 and <0.95 `UNCERTAIN`; <0.40 `HUMAN_REVIEW` |
| sensitivity | `HIGHLY_CONFIDENTIAL` | 0.95 | 0.40 | ≥0.95 `AUTOMATIC`; ≥0.40 and <0.95 `UNCERTAIN`; <0.40 `HUMAN_REVIEW` |

#### Scenario: Default band boundaries

- GIVEN the default policy and a primary category scoring 0.90
- WHEN rules run
- THEN the band is `AUTOMATIC`
- AND a score of 0.65 yields `UNCERTAIN` and a score of 0.64 yields `HUMAN_REVIEW`

#### Scenario: Elevated tier raises the auto bar

- GIVEN `FRAUD_SUSPICION` scoring 0.94 under the MVP table
- WHEN rules run
- THEN it is not auto-accepted
- AND the band for that signal is `UNCERTAIN`

#### Scenario: Band is not a label

- GIVEN any stored classification
- WHEN its label sets are read
- THEN no band value appears among primary categories, secondary categories, sensitivity, actions or priority

### Requirement: Paired review floor for every elevated threshold

Every label whose auto threshold is raised above the default MUST carry a paired review floor strictly below the default review floor. Configuration MUST be rejected when an elevated auto threshold has no paired lower review floor.

#### Scenario: Elevation without paired floor

- GIVEN a configuration raising a label's auto threshold above the default and leaving its review floor at the default
- WHEN the configuration is loaded
- THEN loading fails with an explicit error naming the label

#### Scenario: Paired floor routes a mid-score sensitive signal

- GIVEN `FRAUD_SUSPICION` scoring 0.80 with auto threshold 0.95 and its paired review floor below the default
- WHEN rules run
- THEN it is not auto-accepted as primary category
- AND human review is required and the email is queued

### Requirement: Sensitive classes fail closed with zero silent drops

Any email whose category or sensitivity dimension holds a sensitive-tier label — `FRAUD_SUSPICION`, `LEGAL`, `HIGHLY_CONFIDENTIAL`, `PERSONAL_DATA`, `SENSITIVE_PERSONAL_DATA` — scoring at or above that label's review floor MUST require human review even when the overall band is `AUTOMATIC`. No such signal may be discarded without a review entry.

#### Scenario: Sensitive signal overrides an automatic band

- GIVEN an email with an `AUTOMATIC` primary band and `PERSONAL_DATA` at or above its review floor
- WHEN rules run
- THEN human review is required and the email is queued
- AND the `AUTOMATIC` band does not suppress the review

#### Scenario: Zero silent drops

- GIVEN N emails carrying a sensitive-tier signal at or above its review floor
- WHEN the pipeline run completes
- THEN exactly N review-queue entries exist for them
- AND the count of sensitive emails with no review entry is zero

### Requirement: Primary and secondary category selection

`primary_category` MUST be the highest-scoring primary category at or above its auto threshold, chosen by a deterministic tie-break. Remaining categories at or above their floor MUST become `secondary_categories`. When no category clears its floor, `primary_category` MUST be `OTHER` with human review required, and the `OTHER` share MUST be reported as a metric.

#### Scenario: Multi-category email

- GIVEN `CLAIM_NEW` 0.96 and `CLAIM_DOCUMENTATION` 0.91 under the default policy
- WHEN rules run
- THEN `primary_category` is `CLAIM_NEW` and `secondary_categories` contains `CLAIM_DOCUMENTATION`

#### Scenario: Deterministic tie-break

- GIVEN two primary categories with identical top scores
- WHEN rules run twice, including on replay
- THEN both runs store the same `primary_category` and the same `secondary_categories`

#### Scenario: No category clears its floor

- GIVEN all primary-category scores below their floors
- WHEN rules run
- THEN `primary_category` is `OTHER` and human review is required
- AND the email is counted in the `OTHER`-share metric

### Requirement: Implication and precedence rules

Versioned implication rules MUST include `SENSITIVE_PERSONAL_DATA` implying `PERSONAL_DATA`. `NO_ACTION` MUST NOT coexist with any other action. `priority` MUST be single-valued and resolved by explicit precedence `CRITICAL` > `HIGH` > `NORMAL` > `LOW`. Every conflict MUST be resolved by a versioned rule, never by ordering accidents.

#### Scenario: Implication applied

- GIVEN `SENSITIVE_PERSONAL_DATA` at or above its floor and `PERSONAL_DATA` below its floor
- WHEN rules run
- THEN both `SENSITIVE_PERSONAL_DATA` and `PERSONAL_DATA` are stored
- AND the implication is attributed to its configuration version

#### Scenario: Action exclusivity

- GIVEN `NO_ACTION` selected together with `URGENT`
- WHEN rules run
- THEN `NO_ACTION` is dropped and `URGENT` is stored
- AND no stored actions list contains `NO_ACTION` alongside another action

#### Scenario: Priority precedence

- GIVEN signals raising both `HIGH` and `CRITICAL`
- WHEN rules run
- THEN exactly one priority, `CRITICAL`, is stored

### Requirement: Taxonomy boundary disambiguation

Ambiguous MVP boundaries — `COMPLAINT` vs `LEGAL`, `CLAIM_NEW` vs `CLAIM_UPDATE` vs `CLAIM_DOCUMENTATION`, and `NEW_LEAD` vs `QUOTE_REQUEST` — MUST be encoded as question criteria plus rules precedence, versioned with the question set and threshold configuration.

#### Scenario: Complaint that is also a legal notice

- GIVEN an email scored above the floor for both `COMPLAINT` and `LEGAL`
- WHEN rules run
- THEN the stored result follows the versioned precedence rule for that pair
- AND the configuration version that decided it is recorded with the classification

#### Scenario: New claim versus claim documentation

- GIVEN an email reporting a first claim event while attaching supporting documents
- WHEN rules run
- THEN the outcome follows the versioned precedence between `CLAIM_NEW` and `CLAIM_DOCUMENTATION`

### Requirement: Deterministic pure decision path

Given identical raw scores and an identical configuration version, the rules path MUST produce identical labels, bands and review routing, with no I/O and no engine access.

#### Scenario: Identical input, identical output

- GIVEN a stored raw-score map and configuration version
- WHEN rules run repeatedly, including on replay
- THEN label content, bands and review flags are identical every time
- AND no engine call is made
