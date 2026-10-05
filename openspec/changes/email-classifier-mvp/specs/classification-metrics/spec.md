# Classification Metrics Specification

## Purpose

Measure whether JEV-driven probabilistic classification works, using the synthetic dataset's expected labels as the sole ground truth, and report the MVP quality, safety and latency metrics.

**Label sets covered:** the five sensitive classes reported separately — `FRAUD_SUSPICION`, `LEGAL`, `PERSONAL_DATA`, `SENSITIVE_PERSONAL_DATA`, `HIGHLY_CONFIDENTIAL` — plus all 16 MVP primary categories for per-category metrics (`NEW_LEAD`, `QUOTE_REQUEST`, `NEW_POLICY`, `POLICY_RENEWAL`, `POLICY_CHANGE`, `POLICY_CANCELLATION`, `CLAIM_NEW`, `CLAIM_UPDATE`, `CLAIM_DOCUMENTATION`, `PAYMENT_BILLING`, `COMPLAINT`, `FRAUD_SUSPICION`, `LEGAL`, `REGULATORY`, `PARTNERSHIP`, `OTHER`).

## Requirements

### Requirement: Dataset expected labels are the ground truth

Metrics MUST be computed by comparing stored classifications against the synthetic dataset's expected labels for the same emails. Reviewer corrections MUST NOT replace those expected labels as the truth source.

#### Scenario: Metrics use expected labels

- GIVEN the synthetic dataset with expected labels and a completed pipeline run
- WHEN metrics are produced
- THEN every comparison uses the dataset's expected labels

#### Scenario: Corrections do not rewrite truth

- GIVEN reviewer corrections exist for emails in the evaluation dataset
- WHEN metrics are produced
- THEN the expected labels are unchanged and metrics remain comparable with earlier runs

### Requirement: Classification accuracy

The system MUST report classification accuracy as the share of emails whose stored primary category equals the expected primary category, over all processed emails.

#### Scenario: Accuracy reported

- GIVEN 100 processed emails with expected labels
- WHEN metrics are produced
- THEN accuracy is reported as a share of the 100 emails
- AND the numerator and denominator are exposed, not only the ratio

#### Scenario: Failed emails are accounted for

- GIVEN some emails whose scoring failed
- WHEN accuracy is produced
- THEN those emails are counted as incorrect or reported as a separate failed subset
- AND they are never dropped from the denominator silently

### Requirement: Per-category precision and recall

The system MUST report precision and recall for every MVP primary category, and MUST report them separately for the sensitive classes.

#### Scenario: Per-category metrics

- GIVEN processed emails spanning several categories
- WHEN metrics are produced
- THEN each MVP primary category present in the dataset has precision and recall reported
- AND a category with no predicted or no expected instances is reported as such instead of as zero

#### Scenario: Sensitive classes are not aggregated away

- GIVEN the metric report
- WHEN sensitive classes are inspected
- THEN `FRAUD_SUSPICION`, `LEGAL`, `PERSONAL_DATA`, `SENSITIVE_PERSONAL_DATA` and `HIGHLY_CONFIDENTIAL` each have their own precision and recall
- AND none of them is merged into a combined bucket

### Requirement: Sensitive-class false-negative rate

The system MUST report a false-negative rate for each sensitive class, being the share of emails whose expected labels include that sensitive class but whose stored output does not.

#### Scenario: False negative detected

- GIVEN an email whose expected sensitivity includes `SENSITIVE_PERSONAL_DATA`
- WHEN the stored output does not contain that label
- THEN it counts toward the `SENSITIVE_PERSONAL_DATA` false-negative rate

#### Scenario: Auto-tier gap is measurable

- GIVEN a sensitive email whose score sits between its review floor and its elevated auto threshold
- WHEN metrics are produced
- THEN the email counts as a human-reviewed case and not as a silent miss
- AND the false-negative rate reflects any email that produced no review entry at all

### Requirement: Human review rate

The system MUST report the human review rate as the number of emails placed in the review queue divided by the number of emails processed.

#### Scenario: Review rate reported

- GIVEN 100 processed emails of which 30 required review
- WHEN metrics are produced
- THEN the review rate is reported together with both raw counts

#### Scenario: Failed emails included

- GIVEN emails whose scoring failed and were queued
- WHEN the review rate is produced
- THEN those emails are included in both the queued and processed counts

### Requirement: Processing latency

The system MUST report processing latency per email, derived from the stored timestamp chain, including an aggregate for the run.

#### Scenario: Latency reported per run

- GIVEN a completed run
- WHEN metrics are produced
- THEN per-email latency and a run aggregate are reported
- AND latency for emails with failed scoring is reported separately

### Requirement: OTHER rate

The system MUST report the share of emails whose primary category is `OTHER`, so a silent `OTHER` fallback cannot hide systematic engine failure.

#### Scenario: Other rate reported

- GIVEN emails classified as `OTHER`
- WHEN metrics are produced
- THEN the `OTHER` share is reported with the count of such emails
- AND the share of those `OTHER` emails that cleared no category floor at all is reported

### Requirement: Metrics are version-attributed

Every metric report MUST state the dataset version, the question-set version, the threshold-set version, the engine/model version and the composite classifier version it was computed from.

#### Scenario: Comparability of runs

- GIVEN two metric reports from different configuration versions
- WHEN they are compared
- THEN the differing version component is identifiable from the reports alone

### Requirement: Known limitations are reported with the metrics

The report MUST state that images and other non-text attachments were excluded from scoring, and that OCR coverage is therefore outside the measurement.

#### Scenario: Attachment gap stated

- GIVEN a run over a dataset containing image attachments
- WHEN metrics are produced
- THEN the report states that non-text attachment content was not scored
- AND the affected attachment count is reported
